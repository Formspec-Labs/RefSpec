"""Provider batch-API path for crosswalk qualification: submit, poll, collect.

The serial path in :mod:`refspec.atlas.qualification` asks one question per
HTTPS round trip.  Both providers also sell the same question asynchronously at
half price with a 24-hour turnaround, and a qualification slice is exactly the
workload that shape suits: hundreds of independent, order-free questions whose
answers are not needed until the ``bundle`` stage runs.

This module is a second *road to the same receipt*, never a second receipt
format.  Every row it appends to ``receipts.jsonl`` carries the field set
:func:`refspec.atlas.qualification.validate_candidate` writes, hashed over the
same request-body bytes, checked by the same
:func:`refspec.atlas.qualification._parse_answer`, and read back by the same
:func:`refspec.atlas.qualification.reading_from_receipt` — so ``bundle`` and the
resume-by-done-set logic cannot tell which road a row came down.  Everything
that *is* batch-specific — job identifiers, provider endpoints, submit and
completion timestamps, request counts, the halved pricing assumption — lives in
a sidecar, ``batch-jobs.json``, and never in a receipt field.

Three things a batch changes about the discipline, each handled here:

* **A batch cannot be stopped mid-flight.**  The serial path checks its spend
  cap before every single call and stops the family the moment realized spend
  would cross it.  A submitted batch is already bought, so the cap is enforced
  once, at submit time, against a conservative projection over the whole batch
  — and against what earlier live jobs already projected.
* **A batch answers out of band.**  ``started_at`` is when the job was
  submitted and ``finished_at`` is when the provider says it finished; both are
  facts the sidecar also records against the job identifier.
* **A batch can lose a request.**  A ``custom_id`` absent from both the output
  and the error file is receipted as nothing at all, so a later
  ``batch-submit`` re-asks it.  A request the provider *answered* with an error
  is receipted exactly as the serial path receipts a provider error, and is
  therefore never asked twice.

Wire shapes, researched rather than remembered (2026-08-03):

* OpenAI Batch API — JSONL upload to ``/v1/files`` with ``purpose=batch``,
  ``POST /v1/batches`` with ``input_file_id`` / ``endpoint`` /
  ``completion_window`` (``24h`` only), ``GET /v1/batches/{id}`` reporting
  ``status`` in {validating, in_progress, finalizing, completed, failed,
  expired, cancelling, cancelled} plus ``output_file_id`` / ``error_file_id`` /
  ``request_counts``, results downloaded from ``GET /v1/files/{id}/content`` as
  JSONL lines shaped ``{"id", "custom_id", "response": {"status_code",
  "body"}, "error"}``:
  https://developers.openai.com/api/docs/guides/batch
  https://platform.openai.com/docs/api-reference/batch/create
* Gemini Batch Mode, OpenAI-compatibility flavour — the same JSONL input
  format and the same ``batches`` create/retrieve calls under
  ``https://generativelanguage.googleapis.com/v1beta/openai/``, but "compatibility
  for upload and download is currently not supported", so the input file goes
  up through the native resumable File API and the result file comes back down
  through the native download endpoint:
  https://ai.google.dev/gemini-api/docs/openai (Batch API section)
  https://ai.google.dev/gemini-api/docs/batch-api
  https://developers.googleblog.com/en/gemini-batch-api-now-supports-embeddings-and-openai-compatibility/
* Gemini native File API resumable upload headers
  (``X-Goog-Upload-Protocol: resumable``, ``X-Goog-Upload-Command: start`` then
  ``upload, finalize``, upload URL returned in the ``X-Goog-Upload-URL``
  response header) and the ``download/v1beta/{file}:download?alt=media`` result
  fetch: https://ai.google.dev/gemini-api/docs/batch-api

Nothing here imports a new dependency, and nothing here copies a prompt, a
schema, or a verdict vocabulary: those are referenced out of
:mod:`refspec.atlas.qualification` so a protocol change there arrives here for
free.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import inspect
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from refspec.storage import canonical_json

from . import qualification as qual
from .qualification import CandidatePair, ValidatorFamily

# ---------------------------------------------------------------------------
# pinned batch policy
# ---------------------------------------------------------------------------

#: The sidecar carrying every batch-specific fact.  A receipt never grows a
#: field for it: ``bundle`` reads receipts, and a receipt that only a batch run
#: could produce would make the two roads distinguishable downstream.
SIDECAR = "batch-jobs.json"

SIDECAR_PROTOCOL = "refspec-atlas-crosswalk-batch-v1"

#: The only window either provider offers, and the one both documents pin.
COMPLETION_WINDOW = "24h"

#: The relative URL every input line names, and the ``endpoint`` both providers
#: want on the create call.  It is the batch spelling of the very path
#: ``validate_candidate`` POSTs to.
BATCH_REQUEST_URL = "/v1/chat/completions"

#: Both providers bill batch work at half the synchronous rate.  Assumed, like
#: every other price in this pipeline: the token counts the provider reports
#: are the durable fact, the factor lets a reader recompute the bill.
BATCH_PRICE_FACTOR = 0.5

#: Same conservative per-call input estimate the serial runner's
#: ``_projected_cost`` uses, so the two projections are comparable.
PROJECTION_INPUT_TOKENS = 900

#: ``custom_id`` is bounded by the provider (64 characters at OpenAI) and a
#: candidate identifier is longer than that, so the id is a digest of it —
#: deterministic, so a resubmit of the same candidate produces the same token,
#: and prefixed by family so one file could never collide with the other's.
CUSTOM_ID_DIGEST_CHARACTERS = 32

#: Normalized job states.  Both providers are mapped onto these so the sidecar
#: reads the same for either, and only ``succeeded`` releases results.
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "expired"})

_OPENAI_STATES: Mapping[str, str] = {
    "validating": "pending",
    "in_progress": "running",
    "finalizing": "running",
    "cancelling": "running",
    "completed": "succeeded",
    "failed": "failed",
    "expired": "expired",
    "cancelled": "cancelled",
}

_GEMINI_STATES: Mapping[str, str] = {
    "JOB_STATE_PENDING": "pending",
    "JOB_STATE_RUNNING": "running",
    "JOB_STATE_SUCCEEDED": "succeeded",
    "JOB_STATE_FAILED": "failed",
    "JOB_STATE_CANCELLED": "cancelled",
    "JOB_STATE_EXPIRED": "expired",
}


class BatchError(qual.QualificationError):
    """A batch endpoint refused, or answered something unusable."""


class BatchSpendCapReached(RuntimeError):
    """Submitting this batch would carry the projection past a hard cap.

    Raised *before* anything is bought.  There is no in-flight equivalent: a
    submitted batch cannot be stopped, which is the whole reason the check
    moved to submit time.
    """


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------


class BatchHttpTransport(Protocol):
    """Like ``qual.HttpTransport``, but the response headers come back too.

    Gemini's resumable upload returns the URL to upload to in an
    ``X-Goog-Upload-URL`` response header, and no amount of body parsing can
    recover it, so the batch seam needs one field the serial seam never did.
    """

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]: ...


class UrllibBatchTransport:
    """Stdlib HTTPS transport that also surfaces response headers."""

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status), _lower_headers(response.headers.items()), response.read()
        except urllib.error.HTTPError as error:
            return int(error.code), _lower_headers(error.headers.items()), error.read()


@dataclass(frozen=True, slots=True)
class PlainTransport:
    """Adapt a batch transport back to ``qual.HttpTransport``.

    Model resolution is the same question in both roads, so it is asked with
    the same ``qual.list_models`` rather than a batch-flavoured copy of it.
    """

    inner: BatchHttpTransport

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, bytes]:
        status, _headers, payload = self.inner.request(method, url, headers, body, timeout)
        return status, payload


def default_transport() -> BatchHttpTransport:
    """The transport the CLI uses; tests replace this one name."""

    return UrllibBatchTransport()


def _lower_headers(items: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in items}


# ---------------------------------------------------------------------------
# pricing, projection, identity
# ---------------------------------------------------------------------------


def batch_family(family: ValidatorFamily) -> ValidatorFamily:
    """The same family at batch pricing.

    Only the two assumed prices move.  Name, vendor, independence group,
    requested model and cap are the family's identity and its budget, and none
    of those change because the question was asked asynchronously.
    """

    return replace(
        family,
        assumed_input_usd_per_mtok=family.assumed_input_usd_per_mtok * BATCH_PRICE_FACTOR,
        assumed_output_usd_per_mtok=family.assumed_output_usd_per_mtok * BATCH_PRICE_FACTOR,
    )


def projected_batch_cost(family: ValidatorFamily, calls: int) -> float:
    """Conservative pre-submit projection, at batch pricing.

    Same shape as the serial runner's ``_projected_cost``: assume every call
    spends the pinned input estimate and the whole output budget.  It is the
    only cap check a batch gets, so it deliberately over-counts.
    """

    tracker = qual.SpendTracker(batch_family(family))
    return tracker.cost(calls * PROJECTION_INPUT_TOKENS, calls * family.max_output_tokens)


def custom_id(family: ValidatorFamily, candidate_id: str) -> str:
    """The per-request token the provider echoes back beside its answer."""

    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:CUSTOM_ID_DIGEST_CHARACTERS]
    return f"{family.name}-{digest}"


def run_protocol(catalog: Mapping[str, Any], *, requested: str | None = None) -> str:
    """The verdict protocol *this run* speaks, taken from its own candidates.

    Single-sourced from ``candidates.json`` on purpose.  Defaulting it from
    anywhere else — a library signature, a flag that was not passed — is how a
    run generated under one rubric gets asked under another: the candidates say
    v2, the batch asks v1, and the answers look valid while measuring the wrong
    question.  Batch makes that unrecoverable, because the wrong question is
    already bought by the time anyone reads a receipt.

    A catalog with no protocol is refused rather than assumed.
    """

    recorded = catalog.get("protocol")
    if not recorded:
        raise BatchError(
            "candidates.json records no protocol; regenerate the run with "
            "`generate --protocol ...` so the rubric is pinned by the candidates themselves"
        )
    speaks = str(recorded)
    if requested is not None and requested != speaks:
        raise BatchError(
            f"--protocol {requested!r} contradicts candidates.json, which records {speaks!r}; "
            "the candidates are the run's protocol, so drop the flag or regenerate the run"
        )
    return speaks


def protocol_verdicts(protocol: str) -> tuple[str, ...]:
    """The verdict vocabulary one protocol admits, referenced not restated."""

    if protocol == "v2":
        return tuple(getattr(qual, "VERDICTS_V2", qual.VERDICTS))
    return tuple(qual.VERDICTS)


def distinguishing_verdicts(protocol: str) -> tuple[str, ...]:
    """Verdicts this protocol admits and the other one does not.

    These are the tokens whose presence in a request body proves which rubric
    the bytes actually carry.  Derived from the vocabularies rather than
    written down, so a protocol change cannot leave the check asserting a
    string nobody sends any more.
    """

    other = "v1" if protocol == "v2" else "v2"
    return tuple(sorted(set(protocol_verdicts(protocol)) - set(protocol_verdicts(other))))


def _protocol_kwargs(function: Callable[..., Any], protocol: str) -> dict[str, str]:
    """Pass ``protocol=`` only to a callee that takes it."""

    if "protocol" in inspect.signature(function).parameters:
        return {"protocol": protocol}
    return {}


# ---------------------------------------------------------------------------
# request construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateRow:
    """One row of ``candidates.json``, reduced to what a batch call needs."""

    candidate_id: str
    pair: CandidatePair
    input_digest: str


@dataclass(frozen=True, slots=True)
class BatchRequest:
    """One line of the input JSONL, plus the identity its receipt will carry."""

    candidate_id: str
    custom_id: str
    task_id: str
    request_sha256: str
    body: Mapping[str, Any]

    def line(self) -> str:
        return canonical_json(
            {
                "body": dict(self.body),
                "custom_id": self.custom_id,
                "method": "POST",
                "url": BATCH_REQUEST_URL,
            }
        )


def build_request(
    family: ValidatorFamily,
    model_id: str,
    row: CandidateRow,
    *,
    protocol: str,
) -> BatchRequest:
    """Build the exact body ``validate_candidate`` would have POSTed.

    Not "an equivalent body": the same ``model_input_texts`` and the same
    ``_request_body``, hashed the same way, so ``request_sha256`` means the
    same thing in a batch receipt as in a serial one.
    """

    system_text, user_text = qual.model_input_texts(
        row.pair, **_protocol_kwargs(qual.model_input_texts, protocol)
    )
    body = qual._request_body(family, model_id, system_text, user_text)
    return BatchRequest(
        candidate_id=row.candidate_id,
        custom_id=custom_id(family, row.candidate_id),
        task_id=qual.task_id(row.pair),
        request_sha256=qual._sha256_text(canonical_json(body)),
        body=body,
    )


def input_jsonl(requests: Sequence[BatchRequest]) -> bytes:
    """The upload payload: one canonical JSON object per line."""

    return "".join(request.line() + "\n" for request in requests).encode("utf-8")


def assert_payload_speaks(payload: bytes, protocol: str, *, rows: Sequence[CandidateRow]) -> None:
    """Refuse to upload bytes that do not carry this run's rubric.

    The last gate before money is spent, and the only one that inspects what is
    actually going up rather than what the code believes it built.  A batch
    asking the wrong rubric cannot be recalled, cannot be told from a right one
    by looking at its receipts, and costs the whole slice; the check is cheap
    and it reads the bytes.
    """

    if not rows:
        return
    text = payload.decode("utf-8")
    system, _user = qual.model_input_texts(rows[0].pair, **_protocol_kwargs(qual.model_input_texts, protocol))
    # The system text appears JSON-escaped inside each line, so it is compared
    # in the encoding it is actually written in.
    escaped = canonical_json(system)[1:-1]
    if escaped not in text:
        raise BatchError(
            f"the batch payload does not carry the protocol {protocol!r} instructions; refusing to upload"
        )
    missing = [verdict for verdict in distinguishing_verdicts(protocol) if verdict not in text]
    if missing:
        raise BatchError(
            f"the batch payload is missing the verdicts {missing} that identify protocol {protocol!r}; "
            "refusing to upload a batch that would ask the wrong rubric"
        )


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------


def _decode_json(status: int, payload: bytes, what: str) -> dict[str, Any]:
    text = payload.decode("utf-8", errors="replace")
    if status < 200 or status >= 300:
        raise BatchError(f"{what} returned HTTP {status}: {text[:500]}")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise BatchError(f"{what} returned unparseable JSON: {text[:500]}") from error
    if not isinstance(parsed, dict):
        raise BatchError(f"{what} returned {type(parsed).__name__}, not an object")
    return parsed


def _multipart(fields: Mapping[str, str], filename: str, payload: bytes) -> tuple[str, bytes]:
    """A ``multipart/form-data`` body with a content-derived boundary."""

    boundary = "----refspec-batch-" + hashlib.sha256(payload).hexdigest()[:24]
    chunks: list[bytes] = []
    for name, value in sorted(fields.items()):
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    chunks.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/jsonl\r\n\r\n".encode()
    )
    chunks.append(payload)
    chunks.append(f"\r\n--{boundary}--\r\n".encode())
    return boundary, b"".join(chunks)


@dataclass(frozen=True, slots=True)
class UploadedInput:
    file_id: str
    endpoint: str


class BatchProvider:
    """One family's batch wiring.

    Job control is identical for both families — both speak the OpenAI
    ``batches`` shape — so it lives here once.  Only file transfer is
    overridden, because that is the only place the two providers disagree.
    """

    #: OpenAI documents an optional ``metadata`` object on create.  Gemini's
    #: compatibility layer documents three fields and not that one, so the
    #: compat family does not send a field its own documentation never claims.
    supports_metadata = True

    def __init__(self, family: ValidatorFamily) -> None:
        self.family = family

    # -- shared job control -------------------------------------------------

    @property
    def batches_url(self) -> str:
        return self.family.base_url.rstrip("/") + "/batches"

    def job_url(self, job_id: str) -> str:
        return self.batches_url + "/" + job_id

    def _bearer(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def create_job(
        self,
        transport: BatchHttpTransport,
        api_key: str,
        input_file_id: str,
        *,
        metadata: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "completion_window": COMPLETION_WINDOW,
            "endpoint": BATCH_REQUEST_URL,
            "input_file_id": input_file_id,
        }
        if metadata and self.supports_metadata:
            body["metadata"] = dict(metadata)
        status, _headers, payload = transport.request(
            "POST",
            self.batches_url,
            self._bearer(api_key),
            canonical_json(body).encode("utf-8"),
            self.family.timeout_seconds,
        )
        return _decode_json(status, payload, f"{self.family.name} batch create")

    def retrieve_job(self, transport: BatchHttpTransport, api_key: str, job_id: str) -> dict[str, Any]:
        status, _headers, payload = transport.request(
            "GET",
            self.job_url(job_id),
            {"Authorization": f"Bearer {api_key}"},
            None,
            self.family.timeout_seconds,
        )
        return _decode_json(status, payload, f"{self.family.name} batch retrieve")

    def cancel_job(self, transport: BatchHttpTransport, api_key: str, job_id: str) -> dict[str, Any]:
        """Stop a job that should never have been bought.

        The only lever a batch offers after submit.  It does not refund what
        already ran, so what it buys back is the remainder.
        """

        url = self.job_url(job_id) + "/cancel"
        status, _headers, payload = transport.request(
            "POST", url, self._bearer(api_key), b"", self.family.timeout_seconds
        )
        text = payload.decode("utf-8", errors="replace")
        return {"endpoint": url, "response": text[:2000], "status": status}

    # -- per-vendor file transfer ------------------------------------------

    def upload_input(self, transport: BatchHttpTransport, api_key: str, payload: bytes, name: str) -> UploadedInput:
        raise NotImplementedError

    def download_file(self, transport: BatchHttpTransport, api_key: str, file_id: str) -> tuple[bytes, str]:
        raise NotImplementedError

    def normalize_state(self, job: Mapping[str, Any]) -> str:
        raw = str(job.get("status") or "")
        if raw in _OPENAI_STATES:
            return _OPENAI_STATES[raw]
        metadata = job.get("metadata")
        native = str(metadata.get("state")) if isinstance(metadata, Mapping) else str(job.get("state") or "")
        if native in _GEMINI_STATES:
            return _GEMINI_STATES[native]
        return raw or native or "unknown"


class OpenAIBatchProvider(BatchProvider):
    """OpenAI: files, batches and downloads all live under the same base URL."""

    @property
    def files_url(self) -> str:
        return self.family.base_url.rstrip("/") + "/files"

    def upload_input(self, transport: BatchHttpTransport, api_key: str, payload: bytes, name: str) -> UploadedInput:
        boundary, body = _multipart({"purpose": "batch"}, name, payload)
        status, _headers, response = transport.request(
            "POST",
            self.files_url,
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            body,
            self.family.timeout_seconds,
        )
        parsed = _decode_json(status, response, f"{self.family.name} file upload")
        file_id = str(parsed.get("id") or "")
        if not file_id:
            raise BatchError(f"{self.family.name} file upload returned no id")
        return UploadedInput(file_id=file_id, endpoint=self.files_url)

    def download_file(self, transport: BatchHttpTransport, api_key: str, file_id: str) -> tuple[bytes, str]:
        url = f"{self.files_url}/{file_id}/content"
        status, _headers, payload = transport.request(
            "GET", url, {"Authorization": f"Bearer {api_key}"}, None, self.family.timeout_seconds
        )
        if status < 200 or status >= 300:
            raise BatchError(f"{self.family.name} file download returned HTTP {status}")
        return payload, url


class GeminiBatchProvider(BatchProvider):
    """Gemini: OpenAI-shaped job control, native File API for the bytes.

    The compatibility layer says so in as many words — "compatibility for
    upload and download is currently not supported" — so the input file goes up
    the resumable File API and the result comes back down the native download
    endpoint.  Both are derived from the family's own base URL rather than
    restated, so a base-URL change carries here too.
    """

    supports_metadata = False

    @property
    def _root(self) -> str:
        parsed = urlparse(self.family.base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def _api_version(self) -> str:
        segments = [segment for segment in urlparse(self.family.base_url).path.split("/") if segment]
        return segments[0] if segments else "v1beta"

    @property
    def upload_url(self) -> str:
        return f"{self._root}/upload/{self._api_version}/files"

    def download_url(self, file_id: str) -> str:
        return f"{self._root}/download/{self._api_version}/{file_id.lstrip('/')}:download?alt=media"

    def upload_input(self, transport: BatchHttpTransport, api_key: str, payload: bytes, name: str) -> UploadedInput:
        start_headers = {
            "Content-Type": "application/json",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(payload)),
            "X-Goog-Upload-Header-Content-Type": "application/jsonl",
            "X-Goog-Upload-Protocol": "resumable",
            "x-goog-api-key": api_key,
        }
        status, headers, response = transport.request(
            "POST",
            self.upload_url,
            start_headers,
            canonical_json({"file": {"display_name": name}}).encode("utf-8"),
            self.family.timeout_seconds,
        )
        if status < 200 or status >= 300:
            raise BatchError(
                f"{self.family.name} resumable upload start returned HTTP {status}: "
                f"{response.decode('utf-8', errors='replace')[:500]}"
            )
        session_url = _lower_headers(headers.items()).get("x-goog-upload-url")
        if not session_url:
            raise BatchError(f"{self.family.name} resumable upload start returned no X-Goog-Upload-URL header")
        status, _headers, response = transport.request(
            "POST",
            session_url,
            {
                "Content-Length": str(len(payload)),
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
            },
            payload,
            self.family.timeout_seconds,
        )
        parsed = _decode_json(status, response, f"{self.family.name} resumable upload finalize")
        described = parsed.get("file") if isinstance(parsed.get("file"), Mapping) else parsed
        file_id = str(described.get("name") or "")
        if not file_id:
            raise BatchError(f"{self.family.name} resumable upload returned no file name")
        return UploadedInput(file_id=file_id, endpoint=self.upload_url)

    def cancel_job(self, transport: BatchHttpTransport, api_key: str, job_id: str) -> dict[str, Any]:
        """Cancel through the native endpoint; the compat layer has no cancel.

        The compatibility layer covers creating a batch, watching it, and
        reading its results — not cancelling one — so this goes to
        ``v1beta/{batches/id}:cancel`` with the native credential header.  The
        job id is already the native resource name, which is what that path
        wants.
        """

        url = f"{self._root}/{self._api_version}/{job_id.lstrip('/')}:cancel"
        status, _headers, payload = transport.request(
            "POST", url, {"x-goog-api-key": api_key, "Content-Type": "application/json"}, b"", self.family.timeout_seconds
        )
        text = payload.decode("utf-8", errors="replace")
        return {"endpoint": url, "response": text[:2000], "status": status}

    def download_file(self, transport: BatchHttpTransport, api_key: str, file_id: str) -> tuple[bytes, str]:
        url = self.download_url(file_id)
        status, _headers, payload = transport.request(
            "GET", url, {"x-goog-api-key": api_key}, None, self.family.timeout_seconds
        )
        if status < 200 or status >= 300:
            raise BatchError(f"{self.family.name} file download returned HTTP {status}")
        return payload, url


def provider_for(family: ValidatorFamily) -> BatchProvider:
    """Pick the file-transfer flavour by vendor; job control is shared."""

    if family.vendor == "google":
        return GeminiBatchProvider(family)
    return OpenAIBatchProvider(family)


# ---------------------------------------------------------------------------
# results -> receipts
# ---------------------------------------------------------------------------


def _raw_value_slice(line: str, key: str, expected: Any) -> str | None:
    """The provider's own bytes for one nested JSON value, if recoverable.

    The serial path hashes the exact response body the endpoint sent.  A batch
    output line embeds that same object, so hashing the provider's substring
    keeps ``response_sha256`` meaning what it means in a serial receipt instead
    of meaning "our re-serialization of it".  Returns ``None`` when the slice
    cannot be located, and the caller falls back to canonical bytes.
    """

    decoder = json.JSONDecoder()
    needle = json.dumps(key)
    cursor = 0
    while True:
        found = line.find(needle, cursor)
        if found < 0:
            return None
        after = found + len(needle)
        while after < len(line) and line[after] in " \t\r\n":
            after += 1
        if after >= len(line) or line[after] != ":":
            cursor = found + 1
            continue
        after += 1
        while after < len(line) and line[after] in " \t\r\n":
            after += 1
        try:
            value, end = decoder.raw_decode(line, after)
        except ValueError:
            cursor = found + 1
            continue
        if value == expected:
            return line[after:end]
        cursor = found + 1


def _epoch_to_iso(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        moment = _dt.datetime.fromtimestamp(float(value), tz=_dt.timezone.utc)
        return moment.isoformat(timespec="seconds").replace("+00:00", "Z")
    text = str(value).strip()
    return text or None


def receipt_from_result(
    *,
    family: ValidatorFamily,
    model_id: str,
    protocol: str,
    row: CandidateRow,
    request: BatchRequest,
    result: Mapping[str, Any],
    raw_line: str,
    started_at: str,
    finished_at: str,
    tracker: qual.SpendTracker,
) -> dict[str, Any]:
    """Turn one batch output line into the receipt the serial path would write.

    Field for field on the ``completed`` path, which is the path ``bundle``
    reads.  The deviations are only those a batch makes true:

    * ``attempts`` is one and both retry counters are zero, because a batch
      line is delivered once;
    * ``dropped_parameters`` is empty, because there is no 400 to correct
      against — the body went up unchanged;
    * an error-file line yields ``provider_error`` with ``response_status:
      None`` and an ``error_code``, a combination the serial path only ever
      writes for ``transport_error``.  The provider genuinely returned no HTTP
      status for that request, and its own error code is the most informative
      thing there is to record; a reader tells the two apart by ``outcome``,
      which is the field that carries the distinction.  Nothing downstream
      reads either: ``reading_from_receipt`` yields nothing for both.
    """

    url = family.base_url.rstrip("/") + "/chat/completions"
    # The same header shape the serial path records, run through the same
    # scrubber.  The credential is never put in to begin with: the batch job
    # carries the authorization, not the line, and a receipt records the
    # request identity rather than the socket that delivered it.
    headers = {"Authorization": "", "Content-Type": "application/json"}
    receipt: dict[str, Any] = {
        "attempts": 1,
        "candidate_id": row.candidate_id,
        "declined_retries": 0,
        "dropped_parameters": [],
        "family": family.name,
        "finished_at": finished_at,
        "generation_class": row.pair.generation_class,
        "independence_group": family.independence_group,
        "input_digest": row.input_digest,
        "kind": "crosswalk_validation",
        "model_id": model_id,
        "model_requested": family.requested_model,
        "request_headers": qual.scrubbed_headers(headers),
        "request_sha256": request.request_sha256,
        "request_url": url,
        "source_member": row.pair.source.member,
        "started_at": started_at,
        "structured_mode": "prompted",
        "target_member": row.pair.target.member,
        "task_id": request.task_id,
        "transport_retries": 0,
        "vendor": family.vendor,
    }
    if _serial_receipt_carries_protocol():
        receipt["protocol"] = protocol

    response = result.get("response") if isinstance(result.get("response"), Mapping) else None
    error = result.get("error")
    if response is None:
        # The provider answered with an error object instead of a response.
        # That is a provider error exactly as a non-200 is in the serial path.
        text = canonical_json(error) if error is not None else canonical_json(dict(result))
        receipt.update(
            {
                "error_code": _error_code(error),
                "outcome": "provider_error",
                "response_bytes": text[:2000],
                "response_sha256": qual._sha256_text(text),
                "response_status": None,
            }
        )
        tracker.record(0, 0, failed=True)
        return receipt

    status = response.get("status_code")
    body = response.get("body")
    raw_body = _raw_value_slice(raw_line, "body", body)
    body_text = raw_body if raw_body is not None else canonical_json(body)
    receipt.update(
        {
            "response_sha256": qual._sha256_text(body_text),
            "response_status": int(status) if isinstance(status, int) else None,
        }
    )
    if receipt["response_status"] != 200:
        receipt["outcome"] = "provider_error"
        receipt["response_bytes"] = body_text[:2000]
        tracker.record(0, 0, failed=True)
        return receipt
    try:
        content = str(body["choices"][0]["message"]["content"])
        usage = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
    except (KeyError, IndexError, TypeError) as failure:
        receipt.update({"error_code": type(failure).__name__, "outcome": "unparseable_response"})
        tracker.record(0, 0, failed=True)
        return receipt
    input_tokens = int((usage or {}).get("prompt_tokens") or 0)
    output_tokens = int((usage or {}).get("completion_tokens") or 0)
    tracker.record(input_tokens, output_tokens)
    receipt.update(
        {
            "assumed_cost_usd": round(tracker.cost(input_tokens, output_tokens), 6),
            "finish_reason": (body["choices"][0] or {}).get("finish_reason"),
            "response_model": body.get("model"),
            "usage": {"completion_tokens": output_tokens, "prompt_tokens": input_tokens},
        }
    )
    answer = qual._parse_answer(content, **_protocol_kwargs(qual._parse_answer, protocol))
    if answer is None:
        receipt.update({"answer_text": content[:1000], "outcome": "unusable_answer"})
        return receipt
    receipt.update({"answer": answer, "outcome": "completed"})
    return receipt


def _error_code(error: Any) -> str:
    if isinstance(error, Mapping):
        for key in ("code", "type", "status"):
            value = error.get(key)
            if isinstance(value, str) and value:
                return value
    return "BatchResultError"


def _serial_receipt_carries_protocol() -> bool:
    return "protocol" in inspect.signature(qual.validate_candidate).parameters


def echo_check_passed(receipt: Mapping[str, Any]) -> bool:
    """Whether this receipt's answer echoed its own ``task_id``.

    The same fact ``reading_from_receipt`` computes at bundle time; surfaced
    here only so the sidecar can count mismatches per job, which is a property
    of the batch and not of any one candidate.
    """

    answer = receipt.get("answer")
    if not isinstance(answer, Mapping):
        return False
    return str(answer.get("task_id")) == str(receipt.get("task_id"))


# ---------------------------------------------------------------------------
# run-directory state
# ---------------------------------------------------------------------------


def read_receipt_pairs(receipts_path: Path) -> set[tuple[str, str]]:
    """The resume key the serial runner uses: ``(candidate_id, family)``."""

    done: set[tuple[str, str]] = set()
    if not receipts_path.exists():
        return done
    for line in receipts_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        done.add((str(record["candidate_id"]), str(record["family"])))
    return done


def read_sidecar(sidecar_path: Path) -> dict[str, Any]:
    if not sidecar_path.exists():
        return {"batchPricingFactor": BATCH_PRICE_FACTOR, "jobs": [], "protocol": SIDECAR_PROTOCOL}
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    payload.setdefault("jobs", [])
    return payload


def write_sidecar(sidecar_path: Path, payload: Mapping[str, Any]) -> str:
    """Replace the sidecar atomically.

    It is the only record that a live batch exists, and it is rewritten after
    every job is created, so a crash during the write must not be able to
    leave a half-file where the job list used to be.
    """

    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    text = canonical_json(payload) + "\n"
    staging = sidecar_path.with_name(sidecar_path.name + ".partial")
    staging.write_text(text, encoding="utf-8")
    staging.replace(sidecar_path)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def has_results(job: Mapping[str, Any]) -> bool:
    """Whether the provider left this job any file to read.

    Not the same question as "did it succeed".  OpenAI documents that an
    *expired* batch still publishes whatever finished — "any responses to
    completed requests are made available via the batch's output file. You will
    be charged for tokens consumed from any completed requests" — so a job that
    ran out of window is answers already paid for, not a job that never ran.
    """

    return bool(job.get("outputFileId") or job.get("errorFileId"))


def released(job: Mapping[str, Any]) -> bool:
    """Whether this job has stopped holding its candidates.

    A job holds them until its answers are in hand, and lets go in exactly two
    situations: it has been collected (whatever it answered is in the receipt
    file, and whatever it lost is askable again), or it reached a terminal
    state with nothing to read (it never ran, so nothing was bought).
    """

    if job.get("collectedAt"):
        return True
    if str(job.get("state")) not in {"failed", "cancelled", "expired"}:
        return False
    return not has_results(job)


def in_flight_pairs(sidecar: Mapping[str, Any]) -> set[tuple[str, str]]:
    """Candidates a live job already bought, so a resubmit never buys twice.

    A collected job holds nothing: the pairs it answered are held by
    ``receipts.jsonl`` instead, and the ``custom_id``s the provider lost are
    deliberately let go so a later ``batch-submit`` re-asks them.  That is the
    only way a lost request ever gets asked again.
    """

    held: set[tuple[str, str]] = set()
    for job in sidecar.get("jobs", ()):
        if released(job):
            continue
        family = str(job.get("family"))
        for request in job.get("requests", ()):
            held.add((str(request["candidateId"]), family))
    return held


def committed_by_family(sidecar: Mapping[str, Any]) -> dict[str, float]:
    """What earlier jobs already put on the bill, per family.

    A collected job contributes what it actually spent; a live one contributes
    its conservative projection; a job that reached a terminal state with
    nothing to read contributes nothing, because nothing was bought.  Money
    that has already left never stops counting against a cap.
    """

    totals: dict[str, float] = {}
    for job in sidecar.get("jobs", ()):
        family = str(job.get("family"))
        if job.get("collectedAt"):
            collection = job.get("collection") or {}
            totals[family] = totals.get(family, 0.0) + float(collection.get("assumedCostUsd") or 0.0)
            continue
        if released(job):
            continue
        totals[family] = totals.get(family, 0.0) + float(job.get("projectedCostUsd") or 0.0)
    return totals


# ---------------------------------------------------------------------------
# the three operations
# ---------------------------------------------------------------------------


def submit(
    *,
    transport: BatchHttpTransport,
    receipts_path: Path,
    sidecar_path: Path,
    families: Sequence[ValidatorFamily],
    keys: Mapping[str, str],
    models: Mapping[str, str],
    rows: Sequence[CandidateRow],
    caps: Mapping[str, float] | None = None,
    protocol: str,
    now: Callable[[], str] = qual._utcnow,
) -> dict[str, Any]:
    """Build, price-check, upload and create one batch job per family.

    The cap is checked before a single byte is uploaded, and it is checked
    against this batch *plus* whatever live jobs already committed, because a
    second submit against the same run directory spends real money the first
    one has not finished spending yet.
    """

    speaks = protocol
    sidecar = read_sidecar(sidecar_path)
    excluded = read_receipt_pairs(receipts_path) | in_flight_pairs(sidecar)
    committed = committed_by_family(sidecar)

    planned: list[tuple[ValidatorFamily, list[CandidateRow], float]] = []
    for family in families:
        pending = [row for row in rows if (row.candidate_id, family.name) not in excluded]
        if not pending:
            planned.append((family, pending, 0.0))
            continue
        projection = projected_batch_cost(family, len(pending))
        cap = float(caps.get(family.name)) if caps and family.name in caps else family.spend_cap_usd
        already = committed.get(family.name, 0.0)
        if projection + already > cap:
            raise BatchSpendCapReached(
                f"{family.name}: submitting {len(pending)} batch calls projects "
                f"${projection:.4f} which, with ${already:.4f} already in flight, "
                f"exceeds the ${cap:.2f} cap; shrink the slice with --max-candidates"
            )
        planned.append((family, pending, projection))

    # The total counts what earlier submits already bought too.  Checking only
    # this invocation would let N single-family submits walk past a ceiling one
    # combined submit would have refused.
    total = sum(projection for _family, _pending, projection in planned)
    running = total + sum(committed.values())
    if running > qual.TOTAL_SPEND_CAP_USD:
        raise BatchSpendCapReached(
            f"projected ${total:.2f} which, with ${sum(committed.values()):.2f} already committed, "
            f"exceeds the ${qual.TOTAL_SPEND_CAP_USD:.2f} total cap; shrink the slice"
        )

    sidecar["batchPricingFactor"] = BATCH_PRICE_FACTOR
    sidecar["protocol"] = SIDECAR_PROTOCOL

    submitted: list[dict[str, Any]] = []
    for family, pending, projection in planned:
        if not pending:
            continue
        provider = provider_for(family)
        priced = batch_family(family)
        model_id = models[family.name]
        requests = [build_request(family, model_id, row, protocol=speaks) for row in pending]
        payload = input_jsonl(requests)
        assert_payload_speaks(payload, speaks, rows=pending)
        display_name = f"refspec-atlas-crosswalk-{family.name}-{len(requests)}"
        uploaded = provider.upload_input(transport, keys[family.name], payload, display_name + ".jsonl")
        job = provider.create_job(
            transport,
            keys[family.name],
            uploaded.file_id,
            metadata={"refspec": SIDECAR_PROTOCOL, "family": family.name},
        )
        job_id = str(job.get("id") or job.get("name") or "")
        if not job_id:
            raise BatchError(f"{family.name} batch create returned no job id")
        record = {
            "assumedPricingUsdPerMtok": {
                "input": priced.assumed_input_usd_per_mtok,
                "output": priced.assumed_output_usd_per_mtok,
            },
            "batchPricingFactor": BATCH_PRICE_FACTOR,
            "candidateCount": len(requests),
            "collectedAt": None,
            "completedAt": None,
            "completionWindow": COMPLETION_WINDOW,
            "createEndpoint": provider.batches_url,
            "displayName": display_name,
            "errorFileId": None,
            "family": family.name,
            "inputFileBytes": len(payload),
            "inputFileId": uploaded.file_id,
            "inputFileSha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "inputUploadEndpoint": uploaded.endpoint,
            "jobId": job_id,
            "modelId": model_id,
            "outputFileId": None,
            "projectedCostUsd": round(projection, 6),
            "protocol": speaks,
            "providerStatus": str(job.get("status") or ""),
            "requestCounts": dict(job.get("request_counts") or {}),
            "requests": [
                {
                    "candidateId": request.candidate_id,
                    "customId": request.custom_id,
                    "requestSha256": request.request_sha256,
                    "taskId": request.task_id,
                }
                for request in requests
            ],
            "spendCapUsd": float(caps.get(family.name)) if caps and family.name in caps else family.spend_cap_usd,
            "state": provider.normalize_state(job),
            "statusEndpoint": provider.job_url(job_id),
            "submittedAt": now(),
            "vendor": family.vendor,
        }
        sidecar.setdefault("jobs", []).append(record)
        submitted.append(record)
        # Written per job, never once at the end.  A job that exists at the
        # provider and not in the sidecar is 24 hours of uncancellable spend
        # that the next submit cannot see, so it would buy the same slice
        # again.  If the family after this one raises, this job is still on
        # record.
        sidecar["updatedAt"] = now()
        write_sidecar(sidecar_path, sidecar)

    sidecar["updatedAt"] = now()
    write_sidecar(sidecar_path, sidecar)
    return {
        "jobs": [
            {
                "candidateCount": record["candidateCount"],
                "family": record["family"],
                "jobId": record["jobId"],
                "projectedCostUsd": record["projectedCostUsd"],
                "state": record["state"],
            }
            for record in submitted
        ],
        "protocol": speaks,
        "totalProjectedCostUsd": round(total, 6),
    }


def poll(
    *,
    transport: BatchHttpTransport,
    sidecar_path: Path,
    families: Mapping[str, ValidatorFamily],
    keys: Mapping[str, str],
    now: Callable[[], str] = qual._utcnow,
) -> dict[str, Any]:
    """Refresh every non-terminal job's state into the sidecar."""

    sidecar = read_sidecar(sidecar_path)
    states: list[dict[str, Any]] = []
    for job in sidecar.get("jobs", ()):
        family = families[str(job["family"])]
        provider = provider_for(family)
        if str(job.get("state")) in TERMINAL_STATES and job.get("collectedAt"):
            states.append(_job_state_row(job))
            continue
        payload = provider.retrieve_job(transport, keys[family.name], str(job["jobId"]))
        job["providerStatus"] = str(payload.get("status") or "")
        job["state"] = provider.normalize_state(payload)
        job["requestCounts"] = dict(payload.get("request_counts") or job.get("requestCounts") or {})
        job["outputFileId"] = payload.get("output_file_id") or job.get("outputFileId")
        job["errorFileId"] = payload.get("error_file_id") or job.get("errorFileId")
        completed = _epoch_to_iso(payload.get("completed_at"))
        if completed:
            job["completedAt"] = completed
        job["polledAt"] = now()
        states.append(_job_state_row(job))
    sidecar["updatedAt"] = now()
    write_sidecar(sidecar_path, sidecar)
    return {"jobs": states}


def _job_state_row(job: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidateCount": job.get("candidateCount"),
        "collectedAt": job.get("collectedAt"),
        "family": job.get("family"),
        "jobId": job.get("jobId"),
        "providerStatus": job.get("providerStatus"),
        "requestCounts": job.get("requestCounts"),
        "state": job.get("state"),
    }


def collect(
    *,
    transport: BatchHttpTransport,
    receipts_path: Path,
    sidecar_path: Path,
    families: Mapping[str, ValidatorFamily],
    keys: Mapping[str, str],
    rows: Sequence[CandidateRow],
    protocol: str,
    now: Callable[[], str] = qual._utcnow,
) -> dict[str, Any]:
    """Download finished jobs, receipt every answer, and never receipt twice.

    Idempotent in both directions, which are two different claims:

    * no ``(candidate_id, family)`` is receipted twice — the same key
      ``qualify`` resumes on, re-read from the receipt file every run;
    * a job already collected is not re-read, re-counted, or re-summarized.
      Re-walking it would find every pair already receipted, spend nothing,
      and then overwrite the job's recorded spend and outcomes with zeros —
      turning "safe to run twice" into evidence destruction.

    Any job with a result file is collected, whatever terminal state it
    reached.  An expired batch publishes what it finished and bills for it, so
    treating expiry as "nothing to read" would both discard paid-for answers
    and let the same slice be bought again.

    A job whose recorded protocol disagrees with the run's is refused outright.
    Its answers are to a different question, and letting them into
    ``receipts.jsonl`` would put two rubrics in one bundle with nothing in the
    receipt to tell them apart.
    """

    sidecar = read_sidecar(sidecar_path)
    for job in sidecar.get("jobs", ()):
        asked = str(job.get("protocol") or "")
        if asked and asked != protocol:
            raise BatchError(
                f"job {job.get('jobId')} ({job.get('family')}) asked protocol {asked!r} but this run is "
                f"{protocol!r}; move its sidecar aside rather than collecting answers to another question"
            )
    done = read_receipt_pairs(receipts_path)
    rows_by_id = {row.candidate_id: row for row in rows}
    trackers: dict[str, qual.SpendTracker] = {}
    summaries: list[dict[str, Any]] = []
    written: list[str] = []

    receipts_path.parent.mkdir(parents=True, exist_ok=True)
    with receipts_path.open("a", encoding="utf-8") as handle:
        for job in sidecar.get("jobs", ()):
            family = families[str(job["family"])]
            provider = provider_for(family)
            if job.get("collectedAt"):
                summaries.append(
                    {"family": family.name, "jobId": job["jobId"], "skipped": "collected", **_collected_row(job)}
                )
                continue
            if not has_results(job):
                summaries.append({"family": family.name, "jobId": job["jobId"], "skipped": str(job.get("state"))})
                continue
            tracker = trackers.setdefault(family.name, qual.SpendTracker(batch_family(family)))
            spent_before = tracker.assumed_cost_usd
            results, endpoints = _download_results(transport, provider, keys[family.name], job)
            by_custom_id = {str(item["customId"]): item for item in job.get("requests", ())}
            outcomes: dict[str, int] = {}
            duplicates = 0
            appended = 0
            mismatches = 0
            seen: set[str] = set()
            for line, parsed in results:
                token = str(parsed.get("custom_id") or "")
                planned = by_custom_id.get(token)
                if planned is None:
                    outcomes["unmatched_custom_id"] = outcomes.get("unmatched_custom_id", 0) + 1
                    continue
                seen.add(token)
                candidate_id = str(planned["candidateId"])
                row = rows_by_id.get(candidate_id)
                if row is None:
                    outcomes["unknown_candidate"] = outcomes.get("unknown_candidate", 0) + 1
                    continue
                if (candidate_id, family.name) in done:
                    duplicates += 1
                    continue
                request = BatchRequest(
                    candidate_id=candidate_id,
                    custom_id=token,
                    task_id=str(planned["taskId"]),
                    request_sha256=str(planned["requestSha256"]),
                    body={},
                )
                receipt = receipt_from_result(
                    family=family,
                    model_id=str(job["modelId"]),
                    protocol=str(job.get("protocol") or protocol),
                    row=row,
                    request=request,
                    result=parsed,
                    raw_line=line,
                    started_at=str(job.get("submittedAt") or now()),
                    finished_at=str(job.get("completedAt") or now()),
                    tracker=tracker,
                )
                handle.write(canonical_json(receipt) + "\n")
                handle.flush()
                done.add((candidate_id, family.name))
                written.append(candidate_id)
                appended += 1
                outcome = str(receipt["outcome"])
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
                if outcome == "completed" and not echo_check_passed(receipt):
                    mismatches += 1
            missing = sorted(set(by_custom_id) - seen)
            job["collectedAt"] = now()
            job["collection"] = {
                # What this job really cost, so a later cap check counts money
                # already gone instead of the projection it replaced.
                "assumedCostUsd": round(tracker.assumed_cost_usd - spent_before, 6),
                "downloadEndpoints": endpoints,
                "duplicateSkips": duplicates,
                "missingCustomIds": missing,
                "outcomes": dict(sorted(outcomes.items())),
                "receiptsAppended": appended,
                "resultLines": len(results),
                "taskIdEchoMismatches": mismatches,
            }
            summaries.append(
                {
                    "family": family.name,
                    "jobId": job["jobId"],
                    "missing": len(missing),
                    "outcomes": dict(sorted(outcomes.items())),
                    "receiptsAppended": appended,
                    "taskIdEchoMismatches": mismatches,
                }
            )

    spend = merge_spend(sidecar.get("spendByFamily", ()), trackers.values())
    sidecar["spendByFamily"] = spend
    sidecar["totalBatchAssumedCostUsd"] = round(sum(item["assumed_cost_usd"] for item in spend), 6)
    sidecar["updatedAt"] = now()
    write_sidecar(sidecar_path, sidecar)
    return {
        "jobs": summaries,
        "receiptsAppended": len(written),
        "spendByFamily": spend,
        "totalBatchAssumedCostUsd": sidecar["totalBatchAssumedCostUsd"],
    }


def cancel(
    *,
    transport: BatchHttpTransport,
    sidecar_path: Path,
    families: Mapping[str, ValidatorFamily],
    keys: Mapping[str, str],
    now: Callable[[], str] = qual._utcnow,
) -> dict[str, Any]:
    """Cancel every non-terminal job and record the outcome in the sidecar.

    The cancellation is receipted whether or not it worked.  "We tried to stop
    this and the provider said no" is exactly the fact a spend audit needs, and
    it is the fact that goes missing if a failed cancel is silently retried or
    silently dropped.
    """

    sidecar = read_sidecar(sidecar_path)
    outcomes: list[dict[str, Any]] = []
    for job in sidecar.get("jobs", ()):
        family = families[str(job["family"])]
        if str(job.get("state")) in TERMINAL_STATES:
            outcomes.append({"family": family.name, "jobId": job["jobId"], "skipped": str(job.get("state"))})
            continue
        provider = provider_for(family)
        result = provider.cancel_job(transport, keys[family.name], str(job["jobId"]))
        accepted = 200 <= int(result["status"]) < 300
        job["cancellation"] = {
            "accepted": accepted,
            "endpoint": result["endpoint"],
            "requestedAt": now(),
            "responseStatus": result["status"],
            "response": result["response"],
        }
        if accepted:
            job["state"] = "cancelled"
            job["providerStatus"] = "cancelled"
        outcomes.append(
            {
                "accepted": accepted,
                "endpoint": result["endpoint"],
                "family": family.name,
                "jobId": job["jobId"],
                "responseStatus": result["status"],
            }
        )
    sidecar["updatedAt"] = now()
    write_sidecar(sidecar_path, sidecar)
    return {"cancellations": outcomes}


def _collected_row(job: Mapping[str, Any]) -> dict[str, Any]:
    collection = job.get("collection") or {}
    return {
        "collectedAt": job.get("collectedAt"),
        "receiptsAppended": collection.get("receiptsAppended"),
        "taskIdEchoMismatches": collection.get("taskIdEchoMismatches"),
    }


def merge_spend(
    existing: Iterable[Mapping[str, Any]],
    trackers: Iterable[qual.SpendTracker],
) -> list[dict[str, Any]]:
    """Add this run's spend to what earlier collections already recorded.

    Assignment would be wrong: a batch run collects across several
    invocations, and the sidecar is the only record of what the earlier ones
    cost.
    """

    merged: dict[str, dict[str, Any]] = {str(item["family"]): dict(item) for item in existing}
    for tracker in trackers:
        summary = tracker.summary()
        current = merged.get(summary["family"])
        if current is None:
            merged[summary["family"]] = summary
            continue
        for key in ("calls", "failed_calls", "input_tokens", "output_tokens"):
            current[key] = int(current.get(key, 0)) + int(summary[key])
        current["assumed_cost_usd"] = round(float(current.get("assumed_cost_usd", 0.0)) + summary["assumed_cost_usd"], 6)
        current["assumed_pricing_usd_per_mtok"] = summary["assumed_pricing_usd_per_mtok"]
        current["spend_cap_usd"] = summary["spend_cap_usd"]
    return [merged[name] for name in sorted(merged)]


def _download_results(
    transport: BatchHttpTransport,
    provider: BatchProvider,
    api_key: str,
    job: Mapping[str, Any],
) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    """Both result files, parsed, with the endpoints they came from.

    The error file is downloaded too: a request the provider *answered* with an
    error is a provider error, which the serial path receipts rather than
    silently drops.
    """

    results: list[tuple[str, dict[str, Any]]] = []
    endpoints: list[str] = []
    for key in ("outputFileId", "errorFileId"):
        file_id = job.get(key)
        if not file_id:
            continue
        payload, endpoint = provider.download_file(transport, api_key, str(file_id))
        endpoints.append(endpoint)
        for line in payload.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                results.append((line, parsed))
    return results, endpoints
