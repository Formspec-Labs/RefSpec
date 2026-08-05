"""Provider Batch API path for crosswalk qualification: submit, poll, collect.

The serial path in :mod:`refspec.atlas.qualification` asks one candidate per
HTTPS round trip.  Production batch mode puts up to 25 independent candidates
in a spreadsheet-shaped model request, then sends those requests through each
provider's asynchronous Batch API at its recorded price factor.  ``--group-size
1`` remains the exact serial-shaped recovery and A/B path.

Both modes end in the same per-candidate decision semantics.  Every completed
row is read by :func:`refspec.atlas.qualification.reading_from_receipt`, and
``bundle`` plus the resume key still operate on ``(candidate_id, family)``.
Grouped receipts honestly add the shared request and response digests and the
canonical extracted-answer digest; they never label grouped bytes as the serial
request.  Job identifiers, provider endpoints, submit and completion times,
request counts, and exact group membership live in ``batch-jobs.json``.

Three things a batch changes about the discipline, each handled here:

* **A submitted batch is already billable.**  Cancellation is asynchronous and
  can save only work the provider has not run.  The cap is therefore enforced
  once, at submit time, against a conservative projection over the whole batch
  — and against what earlier live jobs already projected.
* **A batch answers out of band.**  ``started_at`` is when the job was
  submitted and ``finished_at`` is when the provider says it finished; both are
  facts the sidecar also records against the job identifier.
* **A batch can lose a request or one grouped answer.**  A missing
  ``custom_id``, provider error, malformed answer, missing task id, or duplicated
  task id stays in immutable raw evidence without becoming a candidate reading.
  A later submit therefore recovers only the affected rows.

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
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from refspec.storage import canonical_json

from . import qualification as qual
from .model import CrosswalkBundle
from .qualification import CandidatePair, ValidatorFamily

# ---------------------------------------------------------------------------
# pinned batch policy
# ---------------------------------------------------------------------------

#: The sidecar carrying every batch-specific fact. Candidate receipts retain
#: exact attempt/job/result-line identity so public reopening can resolve them
#: to this sidecar and the immutable provider bytes it pins.
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

#: Production uses spreadsheet-shaped requests so the rubric is paid for once
#: per small group instead of once per candidate.  Twenty-five is deliberately
#: modest: it amortizes the prompt while keeping a malformed answer's recovery
#: slice reviewable by a person.
DEFAULT_REQUEST_GROUP_SIZE = 25
MAX_REQUEST_GROUP_SIZE = 25

#: A row-count bound alone is not enough because definitions and hierarchy
#: context vary in size.  Multi-row requests stop at both limits.  A single
#: oversized row falls back to the exact serial-shaped request rather than
#: becoming unaskable.
GROUP_INPUT_BYTE_LIMIT = 240_000
GROUP_INPUT_TOKEN_LIMIT = 60_000

#: Grouped answers share one reasoning budget.  Four hundred tokens per row is
#: an explicit ceiling for the small JSON object defined by the response schema
#: plus model reasoning; the request still keeps the family's 2,000-token
#: minimum for groups of five or fewer.
GROUP_OUTPUT_TOKENS_PER_ROW = 400

#: One provider job must fit the lowest paid queue tier with meaningful
#: headroom.  The estimate is deliberately the same conservative body-byte
#: estimate used for the spend plan, so a shard that passes locally never
#: depends on an unverified account tier.
MAX_PROVIDER_JOB_INPUT_TOKENS = 1_000_000
MAX_PROVIDER_REQUESTS_PER_JOB = 50_000
OPENAI_MAX_INPUT_FILE_BYTES = 200_000_000
GEMINI_MAX_INPUT_FILE_BYTES = 2_000_000_000

#: Exact provider output and error files are retained below the run directory
#: by content digest.  The sidecar pins these paths; collection and every
#: public reopen parse only the retained bytes.
BATCH_EVIDENCE_DIRECTORY = "provider-batch-evidence"

#: Provider-create intent is durable outside the replace-in-place sidecar.  One
#: immutable file records each attempt phase, so a stale writer or an accidental
#: sidecar edit cannot erase a billable attempt and make the same allocation
#: look available again.
BATCH_ATTEMPT_JOURNAL_DIRECTORY = "provider-batch-attempt-journal"
BATCH_ATTEMPT_JOURNAL_VERSION = "2.0"

#: Judging and scoring sidecars share this advisory lock in their common run
#: directory.  The kernel releases ``flock`` when a process exits, including a
#: crash, while the stable inode prevents a third process from bypassing a
#: waiter by racing an unlink/recreate cycle.
SUBMIT_LOCK_FILE = ".provider-batch-submit.lock"
DEFAULT_SUBMIT_LOCK_TIMEOUT_SECONDS = 30.0
SUBMIT_LOCK_POLL_SECONDS = 0.05

GROUPED_REQUEST_PROTOCOL = qual.GROUPED_PROVIDER_REQUEST_PROTOCOL
GROUPING_SEED = "refspec-atlas-crosswalk-grouping-2026-08-04"

#: ``custom_id`` is bounded by the provider (64 characters at OpenAI) and a
#: candidate identifier is longer than that, so the id is a digest of it —
#: deterministic, so a resubmit of the same candidate produces the same token,
#: and prefixed by family so one file could never collide with the other's.
CUSTOM_ID_DIGEST_CHARACTERS = 32

#: Normalized job states.  Both providers are mapped onto these so the sidecar
#: reads the same for either, and only ``succeeded`` releases results.
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "expired"})
WorkKind = Literal["validation", "scoring"]

#: These responses unambiguously reject the submitted request.  Server errors,
#: timeouts, and conflict-like responses can follow a successful commit and
#: therefore keep their spend reservation.
DEFINITE_CREATE_REJECTION_STATUSES = frozenset(
    {400, 401, 403, 404, 405, 413, 415, 422, 429}
)

_OPENAI_STATES: Mapping[str, str] = {
    "validating": "pending",
    "in_progress": "running",
    "finalizing": "running",
    "cancelling": "cancelling",
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
    submitted batch cannot be un-bought, which is the whole reason the check
    moved to submit time.
    """


class BatchSubmitBusy(BatchError):
    """Another process is still deciding or creating a job for this run."""


class BatchCreateRejected(BatchError):
    """The provider definitively declined a create request.

    Unlike a timeout, dropped connection, server error, or conflict-like
    response, one status in the conservative client-rejection allowlist proves
    that no Batch job was accepted.  Callers retain the exact response and can
    release the affected rows without weakening the fail-closed path.
    """

    def __init__(self, family: str, endpoint: str, status: int, payload: bytes) -> None:
        self.endpoint = endpoint
        self.family = family
        self.payload = payload
        self.status = status
        text = payload.decode("utf-8", errors="replace")
        super().__init__(f"{family} batch create returned HTTP {status}: {text[:500]}")


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


def projected_request_cost(family: ValidatorFamily, requests: Sequence[ProviderRequest]) -> float:
    """Price the exact request shapes that would be uploaded.

    JSON bytes divided by three is intentionally more conservative than the
    serial runner's character-divided-by-four estimate.  Output uses the exact
    allowance pinned in each body.  This makes a grouped cap smaller because
    repeated rubrics and per-call output ceilings are genuinely absent, not
    because the estimator pretends 25 rows are one row.
    """

    input_tokens = sum(estimated_request_input_tokens(request) for request in requests)
    output_tokens = sum(int(request.body[family.max_output_tokens_field]) for request in requests)
    return qual.SpendTracker(batch_family(family)).cost(input_tokens, output_tokens)


def custom_id(family: ValidatorFamily, candidate_id: str) -> str:
    """The per-request token the provider echoes back beside its answer."""

    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:CUSTOM_ID_DIGEST_CHARACTERS]
    return f"{family.name}-{digest}"


def run_protocol(catalog: Mapping[str, Any]) -> str:
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
            "candidates.json records no protocol; regenerate the run so its v2 rubric is pinned by the candidates"
        )
    speaks = str(recorded)
    try:
        qual.require_protocol_v2(speaks)
    except qual.QualificationError as error:
        raise BatchError(str(error)) from error
    return speaks


def protocol_verdicts(protocol: str) -> tuple[str, ...]:
    """The verdict vocabulary the adopted protocol admits."""

    qual.require_protocol_v2(protocol)
    return tuple(qual.VERDICTS)


def distinguishing_verdicts(protocol: str) -> tuple[str, ...]:
    """Verdicts whose presence proves the upload carries the full v2 rubric.

    Derived from the canonical vocabulary rather than restated, so a protocol
    change cannot leave this gate asserting a string nobody sends any more.
    """

    return tuple(sorted(protocol_verdicts(protocol)))


def _require_work_protocol(protocol: str, work_kind: WorkKind) -> str:
    if work_kind == "validation":
        return qual.require_protocol_v2(protocol)
    if protocol != qual.SCORING_PROTOCOL:
        raise BatchError(f"unsupported scoring protocol {protocol!r}")
    return protocol


# ---------------------------------------------------------------------------
# request construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateRow:
    """One row of ``candidates.json``, reduced to what a batch call needs."""

    candidate_id: str
    pair: CandidatePair
    input_digest: str
    priority_rank: int | None = None


def _context_from_catalog(payload: Mapping[str, Any]) -> qual.AtlasConceptContext:
    return qual.AtlasConceptContext(
        member=str(payload["member"]),
        pref_label=str(payload["prefLabel"]),
        alt_labels=tuple(str(value) for value in payload.get("altLabels", ())),
        definition=payload.get("definition"),
        scope_note=payload.get("scopeNote"),
    )


def _concept_from_catalog(payload: Mapping[str, Any]) -> qual.AtlasConcept:
    return qual.AtlasConcept(
        member=str(payload["member"]),
        release=str(payload["release"]),
        pref_label=str(payload["prefLabel"]),
        alt_labels=tuple(str(value) for value in payload.get("altLabels", ())),
        definition=payload.get("definition"),
        scope_note=payload.get("scopeNote"),
        broader=tuple(str(value) for value in payload.get("broader", ())),
        vocabulary=str(payload.get("vocabulary", "")),
        parents=tuple(_context_from_catalog(value) for value in payload.get("parents", ())),
        children=tuple(_context_from_catalog(value) for value in payload.get("children", ())),
    )


def candidate_rows_from_catalog(
    catalog: Mapping[str, Any],
    *,
    work_kind: WorkKind,
) -> tuple[CandidateRow, ...]:
    """Reopen the exact candidate rows used by batch request construction."""

    rows: list[CandidateRow] = []
    raw_rows = catalog.get("candidates")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise BatchError("candidate catalog has no candidate rows")
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise BatchError(f"candidate catalog row {index} is not an object")
        try:
            pair = qual.CandidatePair(
                source=_concept_from_catalog(raw["source"]),
                target=_concept_from_catalog(raw["target"]),
                generation_class=str(raw["generationClass"]),
                evidence=dict(raw["evidence"]),
                generation_policy=str(
                    raw.get("generationPolicy", qual.CANDIDATE_GENERATION_POLICY)
                ),
            )
            input_digest = (
                str(raw.get("scoringInputDigest") or qual.scoring_input_digest(pair))
                if work_kind == "scoring"
                else str(raw["inputDigest"])
            )
            rows.append(
                CandidateRow(
                    candidate_id=str(raw["candidateId"]),
                    pair=pair,
                    input_digest=input_digest,
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise BatchError(f"candidate catalog row {index} is incomplete") from error
    return tuple(rows)


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


@dataclass(frozen=True, slots=True)
class GroupedBatchRequest:
    """One provider request carrying several independent candidate rows.

    ``request_sha256`` hashes the grouped body actually uploaded.  It is never
    described as the serial request digest.  Each candidate keeps its sealed
    ``input_digest`` and exact row payload digest in the sidecar, while the
    collector adds the grouped response digest and extracted-answer digest to
    the per-candidate receipt.
    """

    group_id: str
    rows: tuple[CandidateRow, ...]
    custom_id: str
    request_sha256: str
    row_input_sha256: Mapping[str, str]
    task_ids: Mapping[str, str]
    body: Mapping[str, Any]

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(row.candidate_id for row in self.rows)

    def line(self) -> str:
        return canonical_json(
            {
                "body": dict(self.body),
                "custom_id": self.custom_id,
                "method": "POST",
                "url": BATCH_REQUEST_URL,
            }
        )


ProviderRequest = BatchRequest | GroupedBatchRequest


def _row_payload(row: CandidateRow, work_kind: WorkKind) -> Mapping[str, Any]:
    if work_kind == "validation":
        return qual.model_input_payload(row.pair)
    return qual.scoring_input_payload(row.pair)


def _group_schema(work_kind: WorkKind) -> Mapping[str, Any]:
    answer_schema = qual.RESPONSE_SCHEMA if work_kind == "validation" else qual.SCORING_RESPONSE_SCHEMA
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["group_id", "answers"],
        "properties": {
            "group_id": {"type": "string"},
            "answers": {"type": "array", "items": dict(answer_schema)},
        },
    }


def grouped_instructions_text(work_kind: WorkKind) -> str:
    """The canonical single-row rubric with one explicit multi-row wrapper.

    The decision rules still come from :mod:`qualification`; this module owns
    only the request wrapper.  The final paragraph explicitly replaces the
    single-object response instruction, avoiding two competing output shapes.
    """

    single = qual.instructions_text() if work_kind == "validation" else qual.scoring_instructions_text()
    marker = "Return exactly one JSON object and nothing else."
    before, found, _after = single.partition(marker)
    if not found:
        raise BatchError("the canonical qualification instructions no longer expose their response boundary")
    return (
        before
        + "For this grouped request, judge every row independently. Do not compare rows, infer a "
        "generation pattern, or let one row affect another. Return exactly one JSON object and nothing "
        "else. Echo group_id exactly, return exactly one answer for every supplied taskId, and echo each "
        "task_id exactly. The object must match this JSON Schema:\n\n"
        + canonical_json(_group_schema(work_kind))
    )


def group_id(rows: Sequence[CandidateRow], *, protocol: str, work_kind: WorkKind) -> str:
    identity = {
        "candidateIds": [row.candidate_id for row in rows],
        "inputDigests": [row.input_digest for row in rows],
        "protocol": protocol,
        "requestProtocol": GROUPED_REQUEST_PROTOCOL,
        "workKind": work_kind,
    }
    return "group-" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:32]


def grouped_custom_id(family: ValidatorFamily, identifier: str) -> str:
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:CUSTOM_ID_DIGEST_CHARACTERS]
    return f"{family.name}-group-{digest}"


def _group_user_payload(rows: Sequence[CandidateRow], *, identifier: str, work_kind: WorkKind) -> dict[str, Any]:
    return {
        "group_id": identifier,
        "requestProtocol": GROUPED_REQUEST_PROTOCOL,
        "rows": [dict(_row_payload(row, work_kind)) for row in rows],
    }


def _group_input_size(rows: Sequence[CandidateRow], *, work_kind: WorkKind) -> tuple[int, int]:
    identifier = group_id(
        rows,
        protocol=qual.PROTOCOL if work_kind == "validation" else qual.SCORING_PROTOCOL,
        work_kind=work_kind,
    )
    system = grouped_instructions_text(work_kind)
    user = canonical_json(_group_user_payload(rows, identifier=identifier, work_kind=work_kind))
    encoded = (system + user).encode("utf-8")
    return len(encoded), qual._estimate_tokens(system) + qual._estimate_tokens(user)


def deterministic_groups(
    rows: Sequence[CandidateRow],
    *,
    group_size: int = DEFAULT_REQUEST_GROUP_SIZE,
    work_kind: WorkKind = "validation",
) -> tuple[tuple[CandidateRow, ...], ...]:
    """Deterministically order and pack rows under row, byte, and token bounds.

    Score-ranked production judging uses its sealed rank. Other work uses hash
    ordering, which mixes generation classes without revealing them to a model.
    Both judge families receive the same ordered groups. Resume submits re-pack
    only the missing rows, so every recovery group remains a deterministic
    function of the governed order and the work still needed.
    """

    if isinstance(group_size, bool) or not 1 <= group_size <= MAX_REQUEST_GROUP_SIZE:
        raise ValueError(f"group size must be between 1 and {MAX_REQUEST_GROUP_SIZE}")
    ranked = [row for row in rows if row.priority_rank is not None]
    if ranked and len(ranked) != len(rows):
        raise ValueError("candidate priority must cover every submitted row")
    if ranked:
        ranks = [row.priority_rank for row in ranked]
        if any(
            isinstance(rank, bool) or not isinstance(rank, int) or rank < 0
            for rank in ranks
        ) or len(set(ranks)) != len(ranks):
            raise ValueError("candidate priority ranks must be unique nonnegative integers")
        ordered = sorted(rows, key=lambda row: (int(row.priority_rank or 0), row.candidate_id))
    else:
        ordered = sorted(
            rows,
            key=lambda row: (
                hashlib.sha256(
                    f"{GROUPING_SEED}|{work_kind}|{row.candidate_id}".encode()
                ).hexdigest(),
                row.candidate_id,
            ),
        )
    if group_size == 1:
        return tuple((row,) for row in ordered)
    groups: list[tuple[CandidateRow, ...]] = []
    active: list[CandidateRow] = []
    for row in ordered:
        proposed = [*active, row]
        byte_count, token_count = _group_input_size(proposed, work_kind=work_kind)
        if active and (
            len(proposed) > group_size
            or byte_count > GROUP_INPUT_BYTE_LIMIT
            or token_count > GROUP_INPUT_TOKEN_LIMIT
        ):
            groups.append(tuple(active))
            active = [row]
        else:
            active = proposed
    if active:
        groups.append(tuple(active))
    return tuple(groups)


def grouped_output_allowance(family: ValidatorFamily, row_count: int) -> int:
    if row_count < 1:
        raise ValueError("a grouped request needs at least one row")
    return max(family.max_output_tokens, row_count * GROUP_OUTPUT_TOKENS_PER_ROW)


def build_grouped_request(
    family: ValidatorFamily,
    model_id: str,
    rows: Sequence[CandidateRow],
    *,
    protocol: str,
    work_kind: WorkKind = "validation",
) -> GroupedBatchRequest:
    """Build one honest multi-row request and pin every level of its input."""

    _require_work_protocol(protocol, work_kind)
    if len(rows) < 2 or len(rows) > MAX_REQUEST_GROUP_SIZE:
        raise ValueError(f"a grouped request needs 2 through {MAX_REQUEST_GROUP_SIZE} rows")
    identifier = group_id(rows, protocol=protocol, work_kind=work_kind)
    row_payloads = {row.candidate_id: dict(_row_payload(row, work_kind)) for row in rows}
    user = canonical_json(
        {
            "group_id": identifier,
            "requestProtocol": GROUPED_REQUEST_PROTOCOL,
            "rows": [row_payloads[row.candidate_id] for row in rows],
        }
    )
    body = qual._request_body(family, model_id, grouped_instructions_text(work_kind), user)
    body[family.max_output_tokens_field] = grouped_output_allowance(family, len(rows))
    return GroupedBatchRequest(
        group_id=identifier,
        rows=tuple(rows),
        custom_id=grouped_custom_id(family, identifier),
        request_sha256=qual._sha256_text(canonical_json(body)),
        row_input_sha256={
            candidate_id: qual._sha256_text(canonical_json(payload))
            for candidate_id, payload in row_payloads.items()
        },
        task_ids={
            row.candidate_id: (
                qual.task_id(row.pair) if work_kind == "validation" else qual.scoring_task_id(row.pair)
            )
            for row in rows
        },
        body=body,
    )


def build_provider_requests(
    family: ValidatorFamily,
    model_id: str,
    rows: Sequence[CandidateRow],
    *,
    protocol: str,
    work_kind: WorkKind = "validation",
    group_size: int = DEFAULT_REQUEST_GROUP_SIZE,
) -> tuple[ProviderRequest, ...]:
    requests: list[ProviderRequest] = []
    for grouped_rows in deterministic_groups(rows, group_size=group_size, work_kind=work_kind):
        if len(grouped_rows) == 1:
            requests.append(
                build_request(family, model_id, grouped_rows[0], protocol=protocol, work_kind=work_kind)
            )
        else:
            requests.append(
                build_grouped_request(
                    family,
                    model_id,
                    grouped_rows,
                    protocol=protocol,
                    work_kind=work_kind,
                )
            )
    return tuple(requests)


def estimated_request_input_tokens(request: ProviderRequest) -> int:
    """Conservatively estimate one provider request's enqueued input tokens."""

    return max(
        PROJECTION_INPUT_TOKENS,
        math.ceil(len(canonical_json(request.body).encode("utf-8")) / 3),
    )


def provider_input_file_limit(family: ValidatorFamily) -> int:
    return GEMINI_MAX_INPUT_FILE_BYTES if family.vendor == "google" else OPENAI_MAX_INPUT_FILE_BYTES


@dataclass(frozen=True, slots=True)
class RequestShard:
    """One deterministic provider job, bounded by queue and file limits."""

    shard_id: str
    requests: tuple[ProviderRequest, ...]
    input_bytes: int
    projected_input_tokens: int
    projected_output_tokens: int

    @property
    def candidate_count(self) -> int:
        return sum(
            len(request.rows) if isinstance(request, GroupedBatchRequest) else 1
            for request in self.requests
        )


def _request_shard(
    family: ValidatorFamily,
    model_id: str,
    requests: Sequence[ProviderRequest],
    *,
    protocol: str,
    work_kind: WorkKind,
) -> RequestShard:
    payload = input_jsonl(requests)
    input_tokens = sum(estimated_request_input_tokens(request) for request in requests)
    output_tokens = sum(
        int(request.body[family.max_output_tokens_field]) for request in requests
    )
    identity = {
        "family": family.name,
        "inputFileSha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "modelId": model_id,
        "protocol": protocol,
        "workKind": work_kind,
    }
    return RequestShard(
        shard_id="shard-" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest(),
        requests=tuple(requests),
        input_bytes=len(payload),
        projected_input_tokens=input_tokens,
        projected_output_tokens=output_tokens,
    )


def deterministic_request_shards(
    family: ValidatorFamily,
    model_id: str,
    requests: Sequence[ProviderRequest],
    *,
    protocol: str,
    work_kind: WorkKind,
) -> tuple[RequestShard, ...]:
    """Pack stable request order into queue-safe, resumable provider jobs."""

    file_limit = provider_input_file_limit(family)
    shards: list[RequestShard] = []
    active: list[ProviderRequest] = []
    active_bytes = 0
    active_tokens = 0
    for request in requests:
        line_bytes = len((request.line() + "\n").encode("utf-8"))
        request_tokens = estimated_request_input_tokens(request)
        if (
            line_bytes > file_limit
            or request_tokens > MAX_PROVIDER_JOB_INPUT_TOKENS
        ):
            raise BatchError(
                f"{family.name} request {request.custom_id} exceeds one provider-job limit"
            )
        if active and (
            len(active) + 1 > MAX_PROVIDER_REQUESTS_PER_JOB
            or active_bytes + line_bytes > file_limit
            or active_tokens + request_tokens > MAX_PROVIDER_JOB_INPUT_TOKENS
        ):
            shards.append(
                _request_shard(
                    family,
                    model_id,
                    active,
                    protocol=protocol,
                    work_kind=work_kind,
                )
            )
            active = []
            active_bytes = 0
            active_tokens = 0
        active.append(request)
        active_bytes += line_bytes
        active_tokens += request_tokens
    if active:
        shards.append(
            _request_shard(
                family,
                model_id,
                active,
                protocol=protocol,
                work_kind=work_kind,
            )
        )
    return tuple(shards)


def _provider_request_plan(request: ProviderRequest) -> dict[str, Any]:
    if isinstance(request, BatchRequest):
        return {
            "candidateCount": 1,
            "candidateIds": [request.candidate_id],
            "customId": request.custom_id,
            "groupId": None,
            "requestKind": "serialEquivalent",
            "requestSha256": request.request_sha256,
        }
    return {
        "candidateCount": len(request.rows),
        "candidateIds": list(request.candidate_ids),
        "customId": request.custom_id,
        "groupId": request.group_id,
        "requestKind": "grouped",
        "requestSha256": request.request_sha256,
    }


def _candidate_request_plans(request: ProviderRequest) -> list[dict[str, Any]]:
    if isinstance(request, BatchRequest):
        return [
            {
                "candidateId": request.candidate_id,
                "customId": request.custom_id,
                "groupId": None,
                "groupSize": 1,
                "itemInputSha256": None,
                "requestKind": "serialEquivalent",
                "requestSha256": request.request_sha256,
                "taskId": request.task_id,
            }
        ]
    return [
        {
            "candidateId": row.candidate_id,
            "customId": request.custom_id,
            "groupId": request.group_id,
            "groupSize": len(request.rows),
            "itemInputSha256": request.row_input_sha256[row.candidate_id],
            "requestKind": "grouped",
            "requestSha256": request.request_sha256,
            "taskId": request.task_ids[row.candidate_id],
        }
        for row in request.rows
    ]


def _planned_shard_record(
    family: ValidatorFamily,
    model_id: str,
    shard: RequestShard,
    *,
    protocol: str,
    work_kind: WorkKind,
    group_size: int,
) -> dict[str, Any]:
    payload = input_jsonl(shard.requests)
    return {
        "candidateCount": shard.candidate_count,
        "family": family.name,
        "inputFileBytes": shard.input_bytes,
        "inputFileSha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "maxRequestGroupSize": group_size,
        "modelId": model_id,
        "projectedCostUsd": round(projected_request_cost(family, shard.requests), 6),
        "projectedInputTokens": shard.projected_input_tokens,
        "projectedOutputTokenAllowance": shard.projected_output_tokens,
        "protocol": protocol,
        "providerRequestCount": len(shard.requests),
        "providerRequests": [_provider_request_plan(request) for request in shard.requests],
        "requests": [
            item for request in shard.requests for item in _candidate_request_plans(request)
        ],
        "shardId": shard.shard_id,
        "workKind": work_kind,
    }


def _rebuild_requests_from_record(
    record: Mapping[str, Any],
    *,
    family: ValidatorFamily,
    rows_by_id: Mapping[str, CandidateRow],
) -> tuple[ProviderRequest, ...]:
    protocol = str(record.get("protocol") or "")
    work_kind = str(record.get("workKind") or "validation")
    if work_kind not in {"validation", "scoring"}:
        raise BatchError("provider batch plan has an invalid work kind")
    typed_work_kind: WorkKind = work_kind  # type: ignore[assignment]
    _require_work_protocol(protocol, typed_work_kind)
    raw_plans = record.get("providerRequests")
    if not isinstance(raw_plans, Sequence) or isinstance(raw_plans, (str, bytes)):
        raise BatchError("provider batch plan has no provider requests")
    rebuilt: list[ProviderRequest] = []
    seen: set[str] = set()
    for index, raw_plan in enumerate(raw_plans):
        if not isinstance(raw_plan, Mapping):
            raise BatchError(f"provider request plan {index} is not an object")
        candidate_ids = raw_plan.get("candidateIds")
        if not isinstance(candidate_ids, Sequence) or isinstance(candidate_ids, (str, bytes)):
            raise BatchError(f"provider request plan {index} has no candidate ids")
        request_rows: list[CandidateRow] = []
        for raw_candidate_id in candidate_ids:
            candidate_id = str(raw_candidate_id)
            if candidate_id in seen:
                raise BatchError(f"provider batch plan repeats candidate {candidate_id}")
            row = rows_by_id.get(candidate_id)
            if row is None:
                raise BatchError("provider batch plan names a candidate outside the catalog")
            seen.add(candidate_id)
            request_rows.append(row)
        kind = str(raw_plan.get("requestKind") or "")
        if kind == "serialEquivalent" and len(request_rows) == 1:
            request: ProviderRequest = build_request(
                family,
                str(record["modelId"]),
                request_rows[0],
                protocol=protocol,
                work_kind=typed_work_kind,
            )
        elif kind == "grouped" and len(request_rows) >= 2:
            request = build_grouped_request(
                family,
                str(record["modelId"]),
                request_rows,
                protocol=protocol,
                work_kind=typed_work_kind,
            )
        else:
            raise BatchError("provider batch plan has an invalid request kind or group size")
        if dict(raw_plan) != _provider_request_plan(request):
            raise BatchError("provider request plan does not reproduce")
        rebuilt.append(request)
    return tuple(rebuilt)


def request_plan_summary(
    family: ValidatorFamily,
    model_id: str,
    rows: Sequence[CandidateRow],
    *,
    protocol: str,
    work_kind: WorkKind = "validation",
    group_size: int = DEFAULT_REQUEST_GROUP_SIZE,
) -> dict[str, Any]:
    """Return the exact local request shape and conservative price projection."""

    requests = build_provider_requests(
        family,
        model_id,
        rows,
        protocol=protocol,
        work_kind=work_kind,
        group_size=group_size,
    )
    group_sizes = [len(request.rows) if isinstance(request, GroupedBatchRequest) else 1 for request in requests]
    input_bytes = len(input_jsonl(requests))
    input_tokens = sum(estimated_request_input_tokens(request) for request in requests)
    output_tokens = sum(int(request.body[family.max_output_tokens_field]) for request in requests)
    shards = deterministic_request_shards(
        family,
        model_id,
        requests,
        protocol=protocol,
        work_kind=work_kind,
    )
    return {
        "candidateCount": len(rows),
        "family": family.name,
        "groupSizeDistribution": {
            str(size): count for size, count in sorted(Counter(group_sizes).items())
        },
        "inputFileBytes": input_bytes,
        "modelId": model_id,
        "projectedInputTokens": input_tokens,
        "projectedOutputTokenAllowance": output_tokens,
        "projectedCostUsd": round(projected_request_cost(family, requests), 6),
        "providerJobCount": len(shards),
        "providerRequestCount": len(requests),
        "requestGroupSizeLimit": group_size,
        "shards": [
            {
                "candidateCount": shard.candidate_count,
                "inputFileBytes": shard.input_bytes,
                "projectedCostUsd": round(
                    projected_request_cost(family, shard.requests), 6
                ),
                "projectedInputTokens": shard.projected_input_tokens,
                "projectedOutputTokenAllowance": shard.projected_output_tokens,
                "providerRequestCount": len(shard.requests),
                "shardId": shard.shard_id,
            }
            for shard in shards
        ],
        "workKind": work_kind,
    }


def verify_sidecar_request_lineage(
    sidecar: Mapping[str, Any],
    *,
    families: Mapping[str, ValidatorFamily],
    rows: Sequence[CandidateRow],
    work_kind: WorkKind,
) -> dict[str, Any]:
    """Rebuild every planned shard and immutable provider attempt."""

    if sidecar.get("protocol") != SIDECAR_PROTOCOL:
        raise BatchError("provider batch sidecar has the wrong protocol")
    if sidecar.get("batchPricingFactor") != BATCH_PRICE_FACTOR:
        raise BatchError("provider batch sidecar has the wrong pricing factor")
    journal_version = sidecar.get("attemptJournalVersion")
    if (
        journal_version is not None
        and journal_version != BATCH_ATTEMPT_JOURNAL_VERSION
    ):
        raise BatchError("provider batch sidecar has an unsupported attempt journal")
    total_cap = sidecar.get("totalSpendCapUsd")
    if isinstance(total_cap, bool) or not isinstance(total_cap, (int, float)) or not math.isfinite(float(total_cap)) or float(total_cap) <= 0:
        raise BatchError("provider batch sidecar has an invalid total spend cap")
    if sidecar.get("queuePolicy") != {
        "accountTier": "notChecked",
        "maxInputTokensPerJob": MAX_PROVIDER_JOB_INPUT_TOKENS,
        "maxProviderRequestsPerJob": MAX_PROVIDER_REQUESTS_PER_JOB,
        "oneActiveShardPerFamilyModel": True,
    }:
        raise BatchError("provider batch sidecar has an unsupported queue policy")
    spend_authority = sidecar.get("spendAuthority")
    if spend_authority is not None and (
        not isinstance(spend_authority, Mapping) or not spend_authority
    ):
        raise BatchError("provider batch sidecar has an invalid spend authority")
    governed_models = (
        spend_authority.get("modelsByFamily")
        if isinstance(spend_authority, Mapping)
        else None
    )
    if governed_models is not None and not isinstance(governed_models, Mapping):
        raise BatchError("provider batch spend authority has invalid governed models")
    priority_provenance = sidecar.get("priorityProvenance")
    if priority_provenance is not None:
        if work_kind != "validation":
            raise BatchError("only judging may carry scorer priority provenance")
        try:
            qual.validate_scorer_priority_provenance(priority_provenance)
        except qual.QualificationError as error:
            raise BatchError(f"provider batch priority provenance is invalid: {error}") from error
    rows_by_id = {row.candidate_id: row for row in rows}
    if len(rows_by_id) != len(rows):
        raise BatchError("current provider batch rows repeat a candidate identity")
    ranked_rows = [row for row in rows if row.priority_rank is not None]
    if ranked_rows and len(ranked_rows) != len(rows):
        raise BatchError("current provider batch row priority is incomplete")
    row_order: dict[str, int] | None = None
    # Public reopening can validate an official ranked judging sidecar from
    # its ordinary unranked catalog rows; the production authority verifier
    # separately re-derives and checks the complete scorer order. Resume paths
    # supply ranked rows and therefore always execute this last pre-POST gate.
    if priority_provenance is None or ranked_rows:
        try:
            ordered_rows = tuple(
                group[0]
                for group in deterministic_groups(
                    rows,
                    group_size=1,
                    work_kind=work_kind,
                )
            )
        except ValueError as error:
            raise BatchError(
                f"current provider batch row order is invalid: {error}"
            ) from error
        row_order = {
            row.candidate_id: ordinal for ordinal, row in enumerate(ordered_rows)
        }
    plans: dict[str, Mapping[str, Any]] = {}
    verified_planned_candidates = 0
    verified_planned_requests = 0
    for raw_plan in sidecar.get("plannedShards", ()):
        if not isinstance(raw_plan, Mapping):
            raise BatchError("planned shard is not an object")
        if str(raw_plan.get("workKind") or "") != work_kind:
            raise BatchError("planned shard has the wrong work kind")
        family_name = str(raw_plan.get("family") or "")
        family = families.get(family_name)
        if family is None:
            raise BatchError(f"planned shard names unknown family {family_name!r}")
        if (
            isinstance(governed_models, Mapping)
            and governed_models.get(family_name) != raw_plan.get("modelId")
        ):
            raise BatchError(
                f"planned shard {raw_plan.get('shardId')} uses a model outside its spend authority"
            )
        rebuilt = _rebuild_requests_from_record(
            raw_plan,
            family=family,
            rows_by_id=rows_by_id,
        )
        candidate_plans = [
            item for request in rebuilt for item in _candidate_request_plans(request)
        ]
        planned_order = (
            [row_order[str(item["candidateId"])] for item in candidate_plans]
            if row_order is not None
            else None
        )
        if planned_order is not None and planned_order != sorted(planned_order):
            raise BatchError(
                f"planned shard {raw_plan.get('shardId')} differs from the current governed row order"
            )
        payload = input_jsonl(rebuilt)
        rebuilt_shard = _request_shard(
            family,
            str(raw_plan["modelId"]),
            rebuilt,
            protocol=str(raw_plan["protocol"]),
            work_kind=work_kind,
        )
        expected = _planned_shard_record(
            family,
            str(raw_plan["modelId"]),
            rebuilt_shard,
            protocol=str(raw_plan["protocol"]),
            work_kind=work_kind,
            group_size=int(raw_plan["maxRequestGroupSize"]),
        )
        actual = dict(raw_plan)
        order = actual.pop("planOrder", None)
        if isinstance(order, bool) or not isinstance(order, int) or order < 1:
            raise BatchError("planned shard has no positive plan order")
        if actual != expected:
            raise BatchError(f"planned shard {raw_plan.get('shardId')} does not reproduce")
        if (
            rebuilt_shard.projected_input_tokens > MAX_PROVIDER_JOB_INPUT_TOKENS
            or len(rebuilt) > MAX_PROVIDER_REQUESTS_PER_JOB
            or len(payload) > provider_input_file_limit(family)
        ):
            raise BatchError(f"planned shard {raw_plan.get('shardId')} exceeds provider limits")
        shard_id = str(raw_plan["shardId"])
        if shard_id in plans:
            raise BatchError(f"provider batch sidecar repeats planned shard {shard_id}")
        plans[shard_id] = raw_plan
        verified_planned_candidates += len(candidate_plans)
        verified_planned_requests += len(rebuilt)

    spend_caps = sidecar.get("spendCapsByFamily")
    planned_families = {str(plan["family"]) for plan in plans.values()}
    if not isinstance(spend_caps, Mapping) or set(spend_caps) != planned_families:
        raise BatchError("provider batch sidecar family spend caps do not match its plans")
    for family_name, value in spend_caps.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
            raise BatchError(f"provider batch sidecar has an invalid {family_name} spend cap")

    attempts: set[str] = set()
    job_ids: set[str] = set()
    verified_candidates = 0
    verified_requests = 0
    raw_artifacts = 0
    result_lines = 0
    status_artifacts = 0
    active_by_family_model: Counter[tuple[str, str]] = Counter()
    for job in sidecar.get("jobs", ()):
        if not isinstance(job, Mapping):
            raise BatchError("provider batch attempt is not an object")
        if str(job.get("workKind") or "") != work_kind:
            raise BatchError(f"job {job.get('jobId')} has the wrong work kind")
        shard_id = str(job.get("shardId") or "")
        plan = plans.get(shard_id)
        if plan is None:
            raise BatchError(f"job {job.get('jobId')} has no planned shard")
        for key, value in plan.items():
            if key == "planOrder":
                continue
            if job.get(key) != value:
                raise BatchError(f"job {job.get('jobId')} differs from planned shard {shard_id}")
        attempt_id = str(job.get("attemptId") or "")
        ordinal = job.get("attemptOrdinal")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
            raise BatchError(f"job {job.get('jobId')} has no attempt ordinal")
        expected_attempt = "attempt-" + hashlib.sha256(
            f"{shard_id}|{ordinal}".encode()
        ).hexdigest()
        if attempt_id != expected_attempt or attempt_id in attempts:
            raise BatchError(f"job {job.get('jobId')} has an invalid or duplicate attempt identity")
        attempts.add(attempt_id)
        family = families[str(job["family"])]
        priced = batch_family(family)
        provider = provider_for(family)
        expected_display_name = (
            f"refspec-atlas-crosswalk-{work_kind}-{family.name}-"
            f"{shard_id[-12:]}-{int(job['providerRequestCount'])}-requests"
        )
        if (
            job.get("batchPricingFactor") != BATCH_PRICE_FACTOR
            or job.get("assumedPricingUsdPerMtok")
            != {
                "input": priced.assumed_input_usd_per_mtok,
                "output": priced.assumed_output_usd_per_mtok,
            }
            or job.get("vendor") != family.vendor
            or job.get("completionWindow") != COMPLETION_WINDOW
            or job.get("createEndpoint") != provider.batches_url
            or job.get("displayName") != expected_display_name
            or job.get("spendCapUsd") != spend_caps[family.name]
            or job.get("totalSpendCapUsd") != total_cap
            or job.get("spendAuthority") != spend_authority
        ):
            raise BatchError(f"job {job.get('jobId')} has inconsistent provider or spend facts")
        job_id = str(job.get("jobId") or "")
        attempt_state = str(job.get("attemptState") or "")
        if job_id:
            if job_id in job_ids:
                raise BatchError(f"provider batch sidecar repeats job id {job_id}")
            job_ids.add(job_id)
            if (
                attempt_state not in {"submitted", "createReceived", "createMismatch"}
                or not job.get("inputFileId")
                or not job.get("submittedAt")
                or job.get("statusEndpoint") != provider.job_url(job_id)
            ):
                raise BatchError(f"job {job_id} has inconsistent submitted-attempt facts")
            if attempt_state == "createMismatch" and not job.get("createResponseIssue"):
                raise BatchError(f"job {job_id} has no create-response mismatch evidence")
            if attempt_state != "submitted" and job.get("collectedAt"):
                raise BatchError(f"job {job_id} trusted an unverified create response")
        elif (
            attempt_state
            not in {
                "intent",
                "uploaded",
                "creating",
                "uncertain",
                "uploadFailed",
                "preCreateReleased",
                "createRejected",
            }
            or str(job.get("state"))
            not in {"intent", "uploaded", "creating", "uncertain", "failed"}
        ):
            raise BatchError("provider batch attempt without a job id has an invalid state")
        if attempt_state == "createRejected" and _create_rejection_pin(job) is None:
            raise BatchError("provider batch attempt has an invalid create rejection")
        if (job.get("outputFileId") or job.get("errorFileId") or job.get("collectedAt")) and not job_id:
            raise BatchError("provider batch result facts have no provider job identity")
        if job.get("collectedAt") and not isinstance(job.get("collection"), Mapping):
            raise BatchError(f"job {job_id} is collected without accounting")
        input_file_id = job.get("inputFileId")
        if input_file_id:
            expected_upload = (
                provider.upload_url
                if isinstance(provider, GeminiBatchProvider)
                else provider.files_url
            )
            if job.get("inputUploadEndpoint") != expected_upload:
                raise BatchError(f"job {job_id} has an invalid upload endpoint")
        elif job.get("inputUploadEndpoint") is not None:
            raise BatchError(f"job {job_id} has an upload endpoint without a file")
        if not released(job):
            active_by_family_model[(str(job["family"]), str(job["modelId"]))] += 1
        artifacts = job.get("resultArtifacts") or ()
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
            raise BatchError(f"job {job.get('jobId')} result artifacts are invalid")
        raw_artifacts += len(artifacts)
        status_pins = job.get("statusArtifacts") or ()
        if not isinstance(status_pins, Sequence) or isinstance(status_pins, (str, bytes)):
            raise BatchError(f"job {job.get('jobId')} status artifacts are invalid")
        status_artifacts += len(status_pins)
        result_lines += sum(
            int(pin.get("lineCount") or 0) for pin in artifacts if isinstance(pin, Mapping)
        )
        verified_candidates += int(job["candidateCount"])
        verified_requests += int(job["providerRequestCount"])
    if any(count > 1 for count in active_by_family_model.values()):
        raise BatchError("provider batch sidecar has more than one active shard for a family/model")
    return {
        "attempts": len(attempts),
        "candidateRequests": verified_candidates,
        "jobs": len(attempts),
        "plannedCandidateRequests": verified_planned_candidates,
        "plannedProviderRequests": verified_planned_requests,
        "plannedShards": len(plans),
        "providerRequests": verified_requests,
        "rawArtifacts": raw_artifacts,
        "resultLines": result_lines,
        "statusArtifacts": status_artifacts,
        "workKind": work_kind,
    }


def verify_receipt_request_lineage(
    receipts: Sequence[Mapping[str, Any]],
    *,
    sidecar: Mapping[str, Any],
    work_kind: WorkKind,
) -> None:
    """Require each batch receipt to name one exact attempt and request plan."""

    jobs = {
        str(job.get("attemptId")): job
        for job in sidecar.get("jobs", ())
        if isinstance(job, Mapping) and str(job.get("workKind") or "") == work_kind
    }
    for receipt in receipts:
        if receipt.get("batch_execution_mode") != "batch":
            continue
        key = (str(receipt.get("candidate_id") or ""), str(receipt.get("family") or ""))
        job = jobs.get(str(receipt.get("batch_attempt_id") or ""))
        if (
            job is None
            or str(job.get("jobId") or "") != str(receipt.get("batch_job_id") or "")
            or str(job.get("shardId") or "") != str(receipt.get("batch_shard_id") or "")
        ):
            raise BatchError(f"receipt for {key[0]} / {key[1]} has no exact batch attempt")
        matches = [
            plan
            for plan in job.get("requests", ())
            if str(plan.get("candidateId") or "") == key[0]
            and str(plan.get("customId") or "") == str(receipt.get("batch_custom_id") or "")
            and str(plan.get("requestSha256") or "") == str(receipt.get("request_sha256") or "")
            and str(plan.get("taskId") or "") == str(receipt.get("task_id") or "")
            and str(plan.get("groupId") or "") == str(receipt.get("group_id") or "")
            and str(plan.get("itemInputSha256") or "")
            == str(receipt.get("item_input_sha256") or "")
        ]
        if len(matches) != 1:
            raise BatchError(f"receipt for {key[0]} / {key[1]} has no exact provider request")


def build_request(
    family: ValidatorFamily,
    model_id: str,
    row: CandidateRow,
    *,
    protocol: str,
    work_kind: WorkKind = "validation",
) -> BatchRequest:
    """Build the exact body ``validate_candidate`` would have POSTed.

    Not "an equivalent body": the same ``model_input_texts`` and the same
    ``_request_body``, hashed the same way, so ``request_sha256`` means the
    same thing in a batch receipt as in a serial one.
    """

    _require_work_protocol(protocol, work_kind)
    if work_kind == "validation":
        system_text, user_text = qual.model_input_texts(row.pair, protocol=protocol)
        echo_token = qual.task_id(row.pair)
    else:
        system_text, user_text = qual.scoring_input_texts(row.pair)
        echo_token = qual.scoring_task_id(row.pair)
    body = qual._request_body(family, model_id, system_text, user_text)
    return BatchRequest(
        candidate_id=row.candidate_id,
        custom_id=custom_id(family, row.candidate_id),
        task_id=echo_token,
        request_sha256=qual._sha256_text(canonical_json(body)),
        body=body,
    )


def input_jsonl(requests: Sequence[ProviderRequest]) -> bytes:
    """The upload payload: one canonical JSON object per line."""

    return "".join(request.line() + "\n" for request in requests).encode("utf-8")


def assert_payload_speaks(
    payload: bytes,
    protocol: str,
    *,
    rows: Sequence[CandidateRow],
    work_kind: WorkKind = "validation",
) -> None:
    """Refuse to upload bytes that do not carry this run's rubric.

    The last gate before money is spent, and the only one that inspects what is
    actually going up rather than what the code believes it built.  A batch
    asking the wrong rubric cannot be recalled, cannot be told from a right one
    by looking at its receipts, and costs the whole slice; the check is cheap
    and it reads the bytes.
    """

    _require_work_protocol(protocol, work_kind)
    if not rows:
        return
    text = payload.decode("utf-8")
    single_system, _user = (
        qual.model_input_texts(rows[0].pair, protocol=protocol)
        if work_kind == "validation"
        else qual.scoring_input_texts(rows[0].pair)
    )
    # System text appears JSON-escaped inside each line.  A payload may contain
    # exact serial-shaped singleton recovery requests, grouped requests, or
    # both when the byte/token bound leaves one large row on its own.
    accepted_systems = (single_system, grouped_instructions_text(work_kind))
    escaped_systems = tuple(canonical_json(value)[1:-1] for value in accepted_systems)
    if not any(escaped in text for escaped in escaped_systems):
        raise BatchError(
            f"the batch payload does not carry the protocol {protocol!r} instructions; refusing to upload"
        )
    for line in text.splitlines():
        try:
            request = json.loads(line)
            system = request["body"]["messages"][0]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise BatchError("the batch payload contains an unreadable request line") from error
        if system not in accepted_systems:
            raise BatchError(
                f"a batch request does not carry the protocol {protocol!r} instructions; refusing to upload"
            )
    expected_terms = (
        distinguishing_verdicts(protocol)
        if work_kind == "validation"
        else ("semantic_plausibility", "evidence_sufficiency", "likely_relation")
    )
    missing = [term for term in expected_terms if term not in text]
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


@dataclass(frozen=True, slots=True)
class RetrievedJob:
    """One parsed status response plus the exact bytes that supplied it."""

    endpoint: str
    payload: dict[str, Any]
    raw_bytes: bytes
    response_status: int


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
        if status in DEFINITE_CREATE_REJECTION_STATUSES:
            raise BatchCreateRejected(
                self.family.name,
                self.batches_url,
                status,
                payload,
            )
        return _decode_json(status, payload, f"{self.family.name} batch create")

    def retrieve_job(self, transport: BatchHttpTransport, api_key: str, job_id: str) -> RetrievedJob:
        endpoint = self.job_url(job_id)
        status, _headers, payload = transport.request(
            "GET",
            endpoint,
            {"Authorization": f"Bearer {api_key}"},
            None,
            self.family.timeout_seconds,
        )
        return RetrievedJob(
            endpoint=endpoint,
            payload=_decode_json(status, payload, f"{self.family.name} batch retrieve"),
            raw_bytes=payload,
            response_status=status,
        )

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


@dataclass(frozen=True, slots=True)
class NormalizedUsage:
    """Provider token usage without treating an absent report as zero."""

    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    raw: Mapping[str, Any]
    status: str

    @property
    def exact(self) -> bool:
        return self.input_tokens is not None and self.output_tokens is not None

    def record(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "raw": dict(self.raw),
            "status": self.status,
            "total_tokens": self.total_tokens,
        }


def _token_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    count = int(value)
    return count if count >= 0 and count == value else None


def normalize_provider_usage(
    payload: Mapping[str, Any],
    family: ValidatorFamily,
) -> NormalizedUsage:
    """Normalize documented and observed OpenAI/Gemini token fields.

    Gemini reasoning tokens are billable output.  When the provider gives a
    total, output is therefore ``total - prompt`` rather than only the visible
    completion count.
    """

    raw: Mapping[str, Any] | None = None
    status = "missing"
    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        raw = usage
        if any(key in usage for key in ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens")):
            status = "providerReported"
            prompt = _token_count(usage.get("prompt_tokens"))
            completion = _token_count(usage.get("completion_tokens"))
            if prompt is None:
                prompt = _token_count(usage.get("input_tokens"))
            if completion is None:
                completion = _token_count(usage.get("output_tokens"))
            total = _token_count(usage.get("total_tokens"))
        elif any(key in usage for key in ("promptTokens", "completionTokens", "totalTokens")):
            status = "geminiCompatibleReported"
            prompt = _token_count(usage.get("promptTokens"))
            completion = _token_count(usage.get("completionTokens"))
            total = _token_count(usage.get("totalTokens"))
        else:
            prompt = completion = total = None
    else:
        metadata = payload.get("usageMetadata")
        if not isinstance(metadata, Mapping):
            metadata = payload.get("usage_metadata")
        if isinstance(metadata, Mapping):
            raw = metadata
            status = "nativeReported"
            prompt = _token_count(
                metadata.get("promptTokenCount", metadata.get("promptTokens"))
            )
            completion = _token_count(
                metadata.get("candidatesTokenCount", metadata.get("completionTokens"))
            )
            thoughts = _token_count(metadata.get("thoughtsTokenCount"))
            if completion is not None and thoughts is not None:
                completion += thoughts
            total = _token_count(
                metadata.get("totalTokenCount", metadata.get("totalTokens"))
            )
        elif any(key in payload for key in ("input_tokens", "output_tokens", "total_tokens")):
            raw = {
                key: payload[key]
                for key in ("input_tokens", "output_tokens", "total_tokens")
                if key in payload
            }
            status = "providerReported"
            prompt = _token_count(payload.get("input_tokens"))
            completion = _token_count(payload.get("output_tokens"))
            total = _token_count(payload.get("total_tokens"))
        else:
            prompt = completion = total = None

    if family.vendor == "google" and prompt is not None and total is not None and total >= prompt:
        completion = total - prompt
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    if prompt is None or completion is None:
        return NormalizedUsage(None, None, total, dict(raw or {}), "missing")
    return NormalizedUsage(prompt, completion, total, dict(raw or {}), status)


def _record_usage(
    tracker: qual.SpendTracker,
    usage: NormalizedUsage,
    *,
    failed: bool = False,
) -> float | None:
    if not usage.exact:
        return None
    assert usage.input_tokens is not None and usage.output_tokens is not None
    tracker.record(usage.input_tokens, usage.output_tokens, failed=failed)
    return round(tracker.cost(usage.input_tokens, usage.output_tokens), 6)


@dataclass(frozen=True, slots=True)
class ResultLineEvidence:
    """One exact retained JSONL line and its source identity."""

    artifact: Mapping[str, Any]
    line_ordinal: int
    raw_bytes: bytes
    raw_text: str
    parsed: Mapping[str, Any] | None

    @property
    def line_digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.raw_bytes).hexdigest()

    def receipt_identity(self, job: Mapping[str, Any]) -> dict[str, Any]:
        result_id = str(self.parsed.get("id") or "") if self.parsed is not None else ""
        custom = str(self.parsed.get("custom_id") or "") if self.parsed is not None else ""
        return {
            "batch_artifact_file": self.artifact["file"],
            "batch_artifact_sha256": self.artifact["fileDigest"],
            "batch_attempt_id": job["attemptId"],
            "batch_custom_id": custom,
            "batch_execution_mode": "batch",
            "batch_job_id": job["jobId"],
            "batch_result_id": result_id,
            "batch_result_line": self.line_ordinal,
            "batch_result_line_sha256": self.line_digest,
            "batch_shard_id": job["shardId"],
        }


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


def _receipt_identity(
    *,
    family: ValidatorFamily,
    model_id: str,
    protocol: str,
    row: CandidateRow,
    task_id_value: str,
    request_sha256: str,
    started_at: str,
    finished_at: str,
    work_kind: WorkKind,
    result_identity: Mapping[str, Any],
) -> dict[str, Any]:
    url = family.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": "", "Content-Type": "application/json"}
    receipt: dict[str, Any] = {
        "attempts": 1,
        "candidate_id": row.candidate_id,
        "declined_retries": 0,
        "dropped_parameters": [],
        "family": family.name,
        "finished_at": finished_at,
        "generation_class": row.pair.generation_class,
        "input_digest": row.input_digest,
        "kind": "crosswalk_validation" if work_kind == "validation" else "crosswalk_scoring",
        "model_id": model_id,
        "model_requested": family.requested_model,
        "request_headers": qual.scrubbed_headers(headers),
        "request_sha256": request_sha256,
        "request_url": url,
        "source_member": row.pair.source.member,
        "started_at": started_at,
        "structured_mode": "prompted",
        "target_member": row.pair.target.member,
        "task_id": task_id_value,
        "transport_retries": 0,
        "vendor": family.vendor,
        "protocol": protocol,
    }
    receipt.update(result_identity)
    if work_kind == "validation":
        receipt["independence_group"] = family.independence_group
    return receipt


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
    result_identity: Mapping[str, Any],
    work_kind: WorkKind = "validation",
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

    _require_work_protocol(protocol, work_kind)
    receipt = _receipt_identity(
        family=family,
        model_id=model_id,
        protocol=protocol,
        row=row,
        task_id_value=request.task_id,
        request_sha256=request.request_sha256,
        started_at=started_at,
        finished_at=finished_at,
        work_kind=work_kind,
        result_identity=result_identity,
    )
    receipt.update(
        {
            "batch_request_kind": "serialEquivalent",
            "group_id": None,
            "item_input_sha256": None,
            "provider_request_protocol": qual.SINGLE_PROVIDER_REQUEST_PROTOCOL,
        }
    )

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
        if isinstance(body, Mapping):
            _record_usage(tracker, normalize_provider_usage(body, family), failed=True)
        return receipt
    try:
        content = str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as failure:
        receipt.update({"error_code": type(failure).__name__, "outcome": "unparseable_response"})
        if isinstance(body, Mapping):
            _record_usage(tracker, normalize_provider_usage(body, family), failed=True)
        return receipt
    usage = normalize_provider_usage(body, family)
    assumed_cost = _record_usage(tracker, usage)
    receipt.update(
        {
            "assumed_cost_usd": assumed_cost,
            "finish_reason": (body["choices"][0] or {}).get("finish_reason"),
            "provider_usage": dict(usage.raw),
            "response_model": body.get("model"),
            "usage": {
                "completion_tokens": usage.output_tokens,
                "prompt_tokens": usage.input_tokens,
                "total_tokens": usage.total_tokens,
            },
            "usage_status": usage.status,
        }
    )
    answer = (
        qual._parse_answer(content, protocol=protocol)
        if work_kind == "validation"
        else qual._parse_scoring_answer(content)
    )
    if answer is None:
        receipt.update({"answer_text": content[:1000], "outcome": "unusable_answer"})
        return receipt
    receipt.update({"answer": answer, "outcome": "completed"})
    return receipt


def _group_receipts_from_result(
    *,
    family: ValidatorFamily,
    model_id: str,
    protocol: str,
    planned_rows: Sequence[tuple[CandidateRow, Mapping[str, Any]]],
    result: Mapping[str, Any],
    raw_line: str,
    started_at: str,
    finished_at: str,
    tracker: qual.SpendTracker,
    work_kind: WorkKind,
    result_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Fan one grouped provider result into independently readable receipts.

    A missing or duplicated task id is not receipted.  The provider did not
    return one unambiguous answer for that candidate, so a later explicit
    submit may recover just that row (including with ``--group-size 1``).
    Answers that are present but fail the candidate schema are also omitted
    from the receipt log.  Their exact provider bytes remain in batch evidence,
    and a later explicit submit may recover only those affected candidates.
    """

    first_plan = planned_rows[0][1]
    identifier = str(first_plan.get("groupId") or "")
    request_sha256 = str(first_plan["requestSha256"])

    def base(row: CandidateRow, plan: Mapping[str, Any]) -> dict[str, Any]:
        receipt = _receipt_identity(
            family=family,
            model_id=model_id,
            protocol=protocol,
            row=row,
            task_id_value=str(plan["taskId"]),
            request_sha256=request_sha256,
            started_at=started_at,
            finished_at=finished_at,
            work_kind=work_kind,
            result_identity=result_identity,
        )
        receipt.update(
            {
                "batch_request_kind": "grouped",
                "group_id": identifier,
                "group_request_sha256": request_sha256,
                "group_size": len(planned_rows),
                "item_input_sha256": str(plan["itemInputSha256"]),
                "provider_request_protocol": GROUPED_REQUEST_PROTOCOL,
            }
        )
        return receipt

    response = result.get("response") if isinstance(result.get("response"), Mapping) else None
    error = result.get("error")
    if response is None:
        text = canonical_json(error) if error is not None else canonical_json(dict(result))
        response_sha256 = qual._sha256_text(text)
        receipts = []
        for row, plan in planned_rows:
            receipt = base(row, plan)
            receipt.update(
                {
                    "error_code": _error_code(error),
                    "group_response_sha256": response_sha256,
                    "outcome": "provider_error",
                    "response_bytes": text[:2000],
                    "response_sha256": response_sha256,
                    "response_status": None,
                }
            )
            receipts.append(receipt)
        return {"groupOutcome": "provider_error", "receipts": receipts}

    status = response.get("status_code")
    body = response.get("body")
    raw_body = _raw_value_slice(raw_line, "body", body)
    body_text = raw_body if raw_body is not None else canonical_json(body)
    response_sha256 = qual._sha256_text(body_text)
    if not isinstance(status, int) or status != 200:
        receipts = []
        for row, plan in planned_rows:
            receipt = base(row, plan)
            receipt.update(
                {
                    "group_response_sha256": response_sha256,
                    "outcome": "provider_error",
                    "response_bytes": body_text[:2000],
                    "response_sha256": response_sha256,
                    "response_status": int(status) if isinstance(status, int) else None,
                }
            )
            receipts.append(receipt)
        if isinstance(body, Mapping):
            _record_usage(tracker, normalize_provider_usage(body, family), failed=True)
        return {"groupOutcome": "provider_error", "receipts": receipts}

    try:
        content = str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as failure:
        if isinstance(body, Mapping):
            _record_usage(tracker, normalize_provider_usage(body, family), failed=True)
        return {
            "errorCode": type(failure).__name__,
            "groupOutcome": "unparseable_response",
            "groupResponseSha256": response_sha256,
            "receipts": [],
        }

    usage = normalize_provider_usage(body, family)
    group_cost = _record_usage(tracker, usage)
    group_usage = {
        "completion_tokens": usage.output_tokens,
        "prompt_tokens": usage.input_tokens,
        "total_tokens": usage.total_tokens,
    }

    answer_text = content.strip()
    if answer_text.startswith("```"):
        answer_text = re.sub(r"^```[A-Za-z]*\n?", "", answer_text)
        answer_text = re.sub(r"\n?```$", "", answer_text.strip())
    try:
        wrapper = json.loads(answer_text)
    except json.JSONDecodeError:
        wrapper = None
    if (
        not isinstance(wrapper, Mapping)
        or set(wrapper) != {"group_id", "answers"}
        or str(wrapper.get("group_id") or "") != identifier
    ):
        return {
            "groupOutcome": "unusable_group_answer",
            "groupResponseSha256": response_sha256,
            "groupUsage": group_usage,
            "receipts": [],
        }
    raw_answers = wrapper.get("answers")
    if not isinstance(raw_answers, list):
        return {
            "groupOutcome": "unusable_group_answer",
            "groupResponseSha256": response_sha256,
            "groupUsage": group_usage,
            "receipts": [],
        }

    answers_by_task: dict[str, list[Mapping[str, Any]]] = {}
    invalid_answer_count = 0
    for raw_answer in raw_answers:
        if not isinstance(raw_answer, Mapping):
            invalid_answer_count += 1
            continue
        task = raw_answer.get("task_id")
        if isinstance(task, str) and task:
            answers_by_task.setdefault(task, []).append(raw_answer)
        else:
            invalid_answer_count += 1

    expected_tasks = {str(plan["taskId"]) for _row, plan in planned_rows}
    duplicate_task_ids = sorted(task for task, answers in answers_by_task.items() if len(answers) > 1)
    missing_task_ids = sorted(expected_tasks - set(answers_by_task))
    unexpected_task_ids = sorted(set(answers_by_task) - expected_tasks)
    receipts: list[dict[str, Any]] = []
    invalid_task_ids: list[str] = []
    for row, plan in planned_rows:
        expected = str(plan["taskId"])
        answers = answers_by_task.get(expected, ())
        if len(answers) != 1:
            continue
        raw_answer = dict(answers[0])
        answer_canonical = canonical_json(raw_answer)
        receipt = base(row, plan)
        receipt.update(
            {
                "answer_sha256": qual._sha256_text(answer_canonical),
                "assumed_group_cost_usd": group_cost,
                "finish_reason": (body["choices"][0] or {}).get("finish_reason"),
                "group_response_sha256": response_sha256,
                "group_usage": group_usage,
                "provider_usage": dict(usage.raw),
                "response_model": body.get("model"),
                "response_sha256": response_sha256,
                "response_status": 200,
                "usage_scope": "sharedProviderRequest",
                "usage_status": usage.status,
            }
        )
        parsed = (
            qual._parse_answer(answer_canonical, protocol=protocol)
            if work_kind == "validation"
            else qual._parse_scoring_answer(answer_canonical)
        )
        if parsed is None:
            invalid_task_ids.append(expected)
            continue
        receipt.update({"answer": parsed, "outcome": "completed"})
        receipts.append(receipt)

    has_issues = bool(
        duplicate_task_ids
        or invalid_answer_count
        or invalid_task_ids
        or missing_task_ids
        or unexpected_task_ids
        or len(raw_answers) != len(planned_rows)
    )
    return {
        "duplicateTaskIds": duplicate_task_ids,
        "groupOutcome": "partial" if has_issues else "completed",
        "groupResponseSha256": response_sha256,
        "groupUsage": group_usage,
        "invalidAnswerCount": invalid_answer_count,
        "invalidTaskIds": sorted(invalid_task_ids),
        "missingTaskIds": missing_task_ids,
        "receipts": receipts,
        "unexpectedTaskIds": unexpected_task_ids,
    }


def _error_code(error: Any) -> str:
    if isinstance(error, Mapping):
        for key in ("code", "type", "status"):
            value = error.get(key)
            if isinstance(value, str) and value:
                return value
    return "BatchResultError"


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


@contextmanager
def _run_submit_lock(
    sidecar_path: Path,
    coordination_sidecars: Sequence[Path],
    *,
    timeout_seconds: float = DEFAULT_SUBMIT_LOCK_TIMEOUT_SECONDS,
) -> Iterator[Path]:
    """Serialize every submit decision and create call for one run directory."""

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or float(timeout_seconds) < 0
    ):
        raise ValueError("provider batch submit lock timeout must be finite and nonnegative")

    roots = {
        path.parent.resolve()
        for path in (sidecar_path, *coordination_sidecars)
    }
    if len(roots) != 1:
        raise BatchError("coordinated batch sidecars must share one run directory")
    run_root = roots.pop()
    run_root.mkdir(parents=True, exist_ok=True)
    lock_path = run_root / SUBMIT_LOCK_FILE
    if not hasattr(os, "O_NOFOLLOW"):
        raise BatchError("provider batch submit lock requires O_NOFOLLOW support")
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise BatchError("provider batch submit lock is unavailable or unsafe") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise BatchError("provider batch submit lock is not a regular file")
        deadline = time.monotonic() + float(timeout_seconds)
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BatchSubmitBusy(
                        f"provider batch submit is busy for {run_root}; "
                        f"retry after the active submit finishes (waited {float(timeout_seconds):g}s)"
                    ) from error
                time.sleep(min(SUBMIT_LOCK_POLL_SECONDS, remaining))
    except Exception:
        os.close(descriptor)
        raise
    try:
        yield lock_path
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


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
        return {
            "batchPricingFactor": BATCH_PRICE_FACTOR,
            "jobs": [],
            "plannedShards": [],
            "protocol": SIDECAR_PROTOCOL,
        }
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    payload.setdefault("jobs", [])
    payload.setdefault("plannedShards", [])
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


def _line_count(payload: bytes) -> int:
    if not payload:
        return 0
    return payload.count(b"\n") + (0 if payload.endswith(b"\n") else 1)


def _safe_run_relative_path(run_root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise BatchError("provider batch evidence path is unsafe")
    current = run_root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise BatchError("provider batch evidence path traverses a symlink")
    return current


_ATTEMPT_ID_PATTERN = re.compile(r"^attempt-[0-9a-f]{64}$")
_ATTEMPT_JOURNAL_EVENT_TYPE = "ProviderBatchAttemptJournalEvent"
_ATTEMPT_RECORDED_PHASES = {
    "intent": "intentRecorded",
    "preCreateReleased": "preCreateReleasedRecorded",
    "uploaded": "uploadedRecorded",
    "createStarted": "createStartedRecorded",
    "created": "createdRecorded",
    "createRejected": "createRejectedRecorded",
}
_ATTEMPT_RECORDED_SOURCES = {
    recorded: source for source, recorded in _ATTEMPT_RECORDED_PHASES.items()
}
_ATTEMPT_JOURNAL_PHASES = frozenset(
    {*_ATTEMPT_RECORDED_PHASES, *_ATTEMPT_RECORDED_SOURCES}
)


def _attempt_journal_root(sidecar_path: Path, *, create: bool) -> Path:
    root = _safe_run_relative_path(
        sidecar_path.parent,
        BATCH_ATTEMPT_JOURNAL_DIRECTORY,
    )
    if root.exists() or root.is_symlink():
        if root.is_symlink() or not root.is_dir():
            raise BatchError("provider batch attempt journal directory is unsafe")
    elif create:
        root.mkdir(mode=0o700)
    return root


def _attempt_event_record(
    sidecar_path: Path,
    job: Mapping[str, Any],
    *,
    phase: str,
) -> dict[str, Any]:
    attempt_id = str(job.get("attemptId") or "")
    if phase not in _ATTEMPT_JOURNAL_PHASES or _ATTEMPT_ID_PATTERN.fullmatch(attempt_id) is None:
        raise BatchError("provider batch attempt journal identity is invalid")
    if phase in _ATTEMPT_RECORDED_SOURCES:
        source_phase = _ATTEMPT_RECORDED_SOURCES[phase]
        source = _attempt_event_record(sidecar_path, job, phase=source_phase)
        facts = {
            "recordedEvent": source_phase,
            "recordedEventDigest": "sha256:"
            + hashlib.sha256(canonical_json(source).encode("utf-8")).hexdigest(),
        }
    elif phase == "intent":
        facts = {
            "attemptOrdinal": job.get("attemptOrdinal"),
            "family": job.get("family"),
            "inputFileSha256": job.get("inputFileSha256"),
            "modelId": job.get("modelId"),
            "projectedCostUsd": job.get("projectedCostUsd"),
            "providerRequestCount": job.get("providerRequestCount"),
            "shardId": job.get("shardId"),
            "spendAuthority": job.get("spendAuthority"),
            "spendCapUsd": job.get("spendCapUsd"),
            "totalSpendCapUsd": job.get("totalSpendCapUsd"),
            "workKind": job.get("workKind"),
        }
    elif phase == "preCreateReleased":
        facts = {
            "preCreateReleasedAt": job.get("preCreateReleasedAt"),
            "preCreateReleaseReason": job.get("preCreateReleaseReason"),
            "releasedAttemptState": job.get("attemptState"),
            "releasedState": job.get("state"),
        }
    elif phase == "uploaded":
        facts = {
            "inputFileId": job.get("inputFileId"),
            "inputUploadEndpoint": job.get("inputUploadEndpoint"),
        }
    elif phase == "createStarted":
        facts = {
            "createEndpoint": job.get("createEndpoint"),
            "createStartedAt": job.get("createStartedAt"),
        }
    elif phase == "created":
        facts = {
            "createNormalizedState": job.get("createNormalizedState"),
            "createProviderStatus": job.get("createProviderStatus"),
            "createRequestCounts": job.get("createRequestCounts"),
            "createResponseIssue": job.get("createResponseIssue"),
            "jobId": job.get("jobId"),
            "statusEndpoint": job.get("statusEndpoint"),
            "submittedAt": job.get("submittedAt"),
        }
    else:
        facts = {
            "createRejectedAt": job.get("createRejectedAt"),
            "createRejection": job.get("createRejection"),
        }
    return {
        "type": _ATTEMPT_JOURNAL_EVENT_TYPE,
        "schemaVersion": BATCH_ATTEMPT_JOURNAL_VERSION,
        "attemptId": attempt_id,
        "event": phase,
        "facts": facts,
        "sidecarFile": sidecar_path.name,
    }


def _attempt_event_path(
    sidecar_path: Path,
    *,
    attempt_id: str,
    phase: str,
) -> Path:
    if _ATTEMPT_ID_PATTERN.fullmatch(attempt_id) is None or phase not in _ATTEMPT_JOURNAL_PHASES:
        raise BatchError("provider batch attempt journal identity is invalid")
    root = _attempt_journal_root(sidecar_path, create=True)
    return root / f"{attempt_id}.{phase}.json"


def _write_attempt_event(
    sidecar_path: Path,
    job: Mapping[str, Any],
    *,
    phase: str,
) -> None:
    """Create one immutable attempt event while the run lock is held."""

    record = _attempt_event_record(sidecar_path, job, phase=phase)
    payload = (canonical_json(record) + "\n").encode("utf-8")
    destination = _attempt_event_path(
        sidecar_path,
        attempt_id=str(record["attemptId"]),
        phase=phase,
    )
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file():
            raise BatchError("provider batch attempt journal event is unsafe")
        if destination.read_bytes() != payload:
            raise BatchError("provider batch attempt journal event differs from its immutable intent")
        return
    if not hasattr(os, "O_NOFOLLOW"):
        raise BatchError("provider batch attempt journal requires O_NOFOLLOW support")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(destination, flags, 0o600)
    except OSError as error:
        raise BatchError("provider batch attempt journal event could not be created safely") from error
    # A partial O_EXCL file is intentionally retained after a write failure.
    # Reconciliation then fails closed instead of forgetting whether provider
    # I/O could follow.
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _write_attempt_recorded(
    sidecar_path: Path,
    job: Mapping[str, Any],
    *,
    phase: str,
) -> None:
    """Acknowledge that one immutable phase reached the mutable sidecar."""

    try:
        recorded_phase = _ATTEMPT_RECORDED_PHASES[phase]
    except KeyError as error:
        raise BatchError("provider batch attempt recorded phase is invalid") from error
    _write_attempt_event(sidecar_path, job, phase=recorded_phase)


def _read_attempt_events(sidecar_path: Path) -> dict[tuple[str, str], Mapping[str, Any]]:
    root = _attempt_journal_root(sidecar_path, create=False)
    if not root.exists():
        return {}
    events: dict[tuple[str, str], Mapping[str, Any]] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file():
            raise BatchError("provider batch attempt journal contains an unsafe entry")
        try:
            payload = path.read_bytes()
            parsed = json.loads(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BatchError("provider batch attempt journal event is invalid") from error
        if (
            not isinstance(parsed, Mapping)
            or (canonical_json(parsed) + "\n").encode("utf-8") != payload
            or set(parsed)
            != {
                "attemptId",
                "event",
                "facts",
                "schemaVersion",
                "sidecarFile",
                "type",
            }
            or parsed.get("type") != _ATTEMPT_JOURNAL_EVENT_TYPE
            or parsed.get("schemaVersion") != BATCH_ATTEMPT_JOURNAL_VERSION
            or not isinstance(parsed.get("facts"), Mapping)
        ):
            raise BatchError("provider batch attempt journal event is invalid")
        attempt_id = str(parsed.get("attemptId") or "")
        phase = str(parsed.get("event") or "")
        expected_name = f"{attempt_id}.{phase}.json"
        if (
            _ATTEMPT_ID_PATTERN.fullmatch(attempt_id) is None
            or phase not in _ATTEMPT_JOURNAL_PHASES
            or path.name != expected_name
            or not isinstance(parsed.get("sidecarFile"), str)
            or Path(str(parsed["sidecarFile"])).name != parsed["sidecarFile"]
        ):
            raise BatchError("provider batch attempt journal event identity is invalid")
        if parsed["sidecarFile"] != sidecar_path.name:
            continue
        key = (attempt_id, phase)
        if key in events:
            raise BatchError("provider batch attempt journal repeats an event")
        events[key] = parsed
    return events


def _merge_reconciled_facts(
    job: dict[str, Any],
    facts: Mapping[str, Any],
    *,
    label: str,
) -> None:
    """Fill journal-authored fields while refusing conflicting sidecar facts."""

    for key, value in facts.items():
        current = job.get(key)
        if current is not None and current != value:
            raise BatchError(f"provider batch {label} differs from its attempt journal")
        job[key] = json.loads(canonical_json(value))


def _attempt_from_intent(
    sidecar_path: Path,
    sidecar: Mapping[str, Any],
    intent: Mapping[str, Any],
    *,
    families: Mapping[str, ValidatorFamily],
) -> dict[str, Any]:
    """Rebuild a sidecar row lost after its immutable intent was written."""

    facts = intent.get("facts")
    if not isinstance(facts, Mapping):
        raise BatchError("provider batch attempt intent has no facts")
    family_name = str(facts.get("family") or "")
    family = families.get(family_name)
    if family is None:
        raise BatchError(f"provider batch attempt names unknown family {family_name!r}")
    shard_id = str(facts.get("shardId") or "")
    plans = [
        plan
        for plan in sidecar.get("plannedShards", ())
        if isinstance(plan, Mapping) and str(plan.get("shardId") or "") == shard_id
    ]
    if len(plans) != 1:
        raise BatchError(
            "provider batch attempt cannot be deterministically reconciled to one planned shard"
        )
    ordinal = facts.get("attemptOrdinal")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        raise BatchError("provider batch attempt intent has no positive ordinal")
    attempt_id = str(intent.get("attemptId") or "")
    expected_id = "attempt-" + hashlib.sha256(
        f"{shard_id}|{ordinal}".encode()
    ).hexdigest()
    if attempt_id != expected_id:
        raise BatchError("provider batch attempt intent has an invalid identity")
    spend_cap = facts.get("spendCapUsd")
    total_cap = facts.get("totalSpendCapUsd")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
        for value in (spend_cap, total_cap)
    ):
        raise BatchError("provider batch attempt intent has invalid spend caps")
    authority = facts.get("spendAuthority")
    if authority is not None and not isinstance(authority, Mapping):
        raise BatchError("provider batch attempt intent has invalid spend authority")
    job = _new_attempt_record(
        plans[0],
        family=family,
        attempt_id=attempt_id,
        attempt_ordinal=ordinal,
        spend_cap_usd=float(spend_cap),
        total_spend_cap_usd=float(total_cap),
        spend_authority=authority,
    )
    if _attempt_event_record(sidecar_path, job, phase="intent") != intent:
        raise BatchError("provider batch attempt intent differs from its planned shard")
    return job


def _reconcile_attempt_journal(
    sidecar_path: Path,
    sidecar: dict[str, Any],
    *,
    families: Mapping[str, ValidatorFamily],
    now: Callable[[], str],
) -> dict[str, Any]:
    """Repair only state that immutable journal phases determine exactly.

    ``uploaded`` without ``createStarted`` is resumable.  Once create started,
    a missing response remains ambiguous and keeps its reservation.  A created
    job identity or definite client rejection can be restored from its exact
    immutable phase after a sidecar-write crash.
    """

    events = _read_attempt_events(sidecar_path)
    if not events:
        return {
            "heldAmbiguousAttemptIds": [],
            "repairedAttemptIds": [],
            "rejectedAttemptIds": [],
            "resumableAttemptIds": [],
        }
    version = sidecar.get("attemptJournalVersion")
    if version not in {None, BATCH_ATTEMPT_JOURNAL_VERSION}:
        raise BatchError("provider batch sidecar has an unsupported attempt journal")
    journal_attempts = sorted(
        {attempt_id for attempt_id, phase in events if phase == "intent"}
    )
    if any(attempt_id not in journal_attempts for attempt_id, _phase in events):
        raise BatchError("provider batch attempt journal has an event without an intent")
    jobs: dict[str, dict[str, Any]] = {}
    for raw_job in sidecar.get("jobs", ()):
        if not isinstance(raw_job, dict):
            raise BatchError("provider batch sidecar contains a non-object attempt")
        attempt_id = str(raw_job.get("attemptId") or "")
        if attempt_id in jobs:
            raise BatchError("provider batch sidecar repeats an attempt identity")
        jobs[attempt_id] = raw_job

    repaired: list[str] = []
    missing_recorded: list[tuple[dict[str, Any], str]] = []
    for attempt_id in journal_attempts:
        intent = events[(attempt_id, "intent")]
        intent_recorded = events.get((attempt_id, "intentRecorded"))
        job = jobs.get(attempt_id)
        if job is None:
            if intent_recorded is not None:
                raise BatchError(
                    "provider batch sidecar attempts differ from the immutable attempt journal"
                )
            job = _attempt_from_intent(
                sidecar_path,
                sidecar,
                intent,
                families=families,
            )
            sidecar.setdefault("jobs", []).append(job)
            jobs[attempt_id] = job
            repaired.append(attempt_id)
        elif _attempt_event_record(sidecar_path, job, phase="intent") != intent:
            raise BatchError("provider batch attempt differs from its immutable intent")

        before = canonical_json(job)
        pre_released = events.get((attempt_id, "preCreateReleased"))
        upload = events.get((attempt_id, "uploaded"))
        started = events.get((attempt_id, "createStarted"))
        created = events.get((attempt_id, "created"))
        rejected = events.get((attempt_id, "createRejected"))
        if (
            pre_released is None
            and upload is None
            and started is None
            and created is None
            and rejected is None
        ):
            job["attemptState"] = "preCreateReleased"
            job["preCreateReleasedAt"] = now()
            job["preCreateReleaseReason"] = "reconciledNoCreateBegan"
            job["state"] = "failed"
            _write_attempt_event(sidecar_path, job, phase="preCreateReleased")
            pre_released = _attempt_event_record(
                sidecar_path,
                job,
                phase="preCreateReleased",
            )
            events[(attempt_id, "preCreateReleased")] = pre_released
        phase_events = {
            "intent": intent,
            "preCreateReleased": pre_released,
            "uploaded": upload,
            "createStarted": started,
            "created": created,
            "createRejected": rejected,
        }
        for phase, event in phase_events.items():
            recorded_phase = _ATTEMPT_RECORDED_PHASES[phase]
            recorded = events.get((attempt_id, recorded_phase))
            if event is None and recorded is not None:
                raise BatchError("provider batch sidecar acknowledgement has no source event")
            if recorded is not None and recorded != _attempt_event_record(
                sidecar_path,
                job,
                phase=recorded_phase,
            ):
                raise BatchError(
                    "provider batch sidecar differs from an acknowledged journal phase"
                )
            if event is not None and recorded is None:
                missing_recorded.append((job, phase))
        if started is not None and upload is None:
            raise BatchError("provider batch create began without an uploaded input")
        if pre_released is not None and any(
            event is not None for event in (upload, started, created, rejected)
        ):
            raise BatchError("provider batch pre-create release conflicts with later provider I/O")
        if (created is not None or rejected is not None) and started is None:
            raise BatchError("provider batch create outcome has no create-start intent")
        if created is not None and rejected is not None:
            raise BatchError("provider batch attempt has two create outcomes")

        if pre_released is not None:
            release_facts = pre_released["facts"]
            _merge_reconciled_facts(
                job,
                {
                    "preCreateReleasedAt": release_facts.get("preCreateReleasedAt"),
                    "preCreateReleaseReason": release_facts.get("preCreateReleaseReason"),
                },
                label="pre-create release",
            )
        if upload is not None:
            _merge_reconciled_facts(
                job,
                upload["facts"],
                label="upload identity",
            )
        if started is not None:
            _merge_reconciled_facts(
                job,
                started["facts"],
                label="create start",
            )
        if pre_released is not None:
            released_attempt_state = str(
                pre_released["facts"].get("releasedAttemptState") or ""
            )
            released_state = str(pre_released["facts"].get("releasedState") or "")
            if (
                released_attempt_state not in {"uploadFailed", "preCreateReleased"}
                or released_state != "failed"
                or str(job.get("attemptState") or "")
                not in {
                    "intent",
                    "uploadFailed",
                    "preCreateReleased",
                }
            ):
                raise BatchError("provider batch pre-create release has conflicting state")
            job["attemptState"] = released_attempt_state
            job["state"] = released_state
        elif created is not None:
            if str(job.get("attemptState") or "") not in {
                "intent",
                "uploaded",
                "creating",
                "uncertain",
                "createReceived",
                "createMismatch",
                "submitted",
            }:
                raise BatchError("provider batch created attempt has conflicting mutable state")
            _merge_reconciled_facts(
                job,
                created["facts"],
                label="job identity",
            )
            issue = job.get("createResponseIssue")
            expected_attempt_state = "createMismatch" if issue else "submitted"
            if str(job.get("attemptState") or "") in {"createMismatch", "submitted"} and str(
                job.get("attemptState")
            ) != expected_attempt_state:
                raise BatchError("provider batch created attempt conflicts with its response evidence")
            job["attemptState"] = expected_attempt_state
            if not job.get("statusArtifacts"):
                job["providerStatus"] = str(job.get("createProviderStatus") or "")
                job["requestCounts"] = dict(job.get("createRequestCounts") or {})
                job["state"] = (
                    "uncertain" if issue else str(job.get("createNormalizedState") or "unknown")
                )
        elif rejected is not None:
            if str(job.get("attemptState") or "") not in {
                "intent",
                "uploaded",
                "creating",
                "uncertain",
                "createRejected",
            }:
                raise BatchError("provider batch rejected attempt has conflicting mutable state")
            _merge_reconciled_facts(
                job,
                rejected["facts"],
                label="create rejection",
            )
            job["attemptState"] = "createRejected"
            job["state"] = "failed"
        elif started is not None:
            if str(job.get("attemptState") or "") not in {
                "intent",
                "uploaded",
                "creating",
                "uncertain",
            }:
                raise BatchError("provider batch ambiguous attempt has conflicting mutable state")
            job["attemptState"] = "uncertain"
            job["state"] = "uncertain"
        elif upload is not None:
            if str(job.get("attemptState") or "") not in {"intent", "uploaded"}:
                raise BatchError("provider batch resumable upload has conflicting mutable state")
            job["attemptState"] = "uploaded"
            job["state"] = "uploaded"
        elif str(job.get("attemptState") or "") not in {"intent", "uploadFailed"}:
            raise BatchError("provider batch intent-only attempt has conflicting mutable state")
        if canonical_json(job) != before and attempt_id not in repaired:
            repaired.append(attempt_id)

    if set(jobs) != set(journal_attempts):
        raise BatchError("provider batch sidecar attempts differ from the immutable attempt journal")
    version_changed = sidecar.get("attemptJournalVersion") != BATCH_ATTEMPT_JOURNAL_VERSION
    sidecar["attemptJournalVersion"] = BATCH_ATTEMPT_JOURNAL_VERSION
    if repaired or version_changed:
        sidecar["updatedAt"] = now()
        write_sidecar(sidecar_path, sidecar)
    for job, phase in missing_recorded:
        _write_attempt_recorded(sidecar_path, job, phase=phase)
    return {
        "heldAmbiguousAttemptIds": sorted(
            attempt_id
            for attempt_id, job in jobs.items()
            if job.get("attemptState") == "uncertain" and not job.get("jobId")
        ),
        "repairedAttemptIds": sorted(repaired),
        "rejectedAttemptIds": sorted(
            attempt_id
            for attempt_id, job in jobs.items()
            if job.get("attemptState") == "createRejected"
        ),
        "resumableAttemptIds": sorted(
            attempt_id
            for attempt_id, job in jobs.items()
            if job.get("attemptState") == "uploaded"
        ),
    }


def _verify_attempt_journal(
    sidecar_path: Path,
    sidecar: Mapping[str, Any],
    *,
    allow_legacy_read_only: bool = False,
) -> None:
    """Require mutable sidecar attempts to equal the immutable local journal."""

    events = _read_attempt_events(sidecar_path)
    jobs: dict[str, Mapping[str, Any]] = {}
    for raw_job in sidecar.get("jobs", ()):
        if not isinstance(raw_job, Mapping):
            raise BatchError("provider batch sidecar contains a non-object attempt")
        attempt_id = str(raw_job.get("attemptId") or "")
        if attempt_id in jobs:
            raise BatchError("provider batch sidecar repeats an attempt identity")
        jobs[attempt_id] = raw_job
    journal_attempts = {
        attempt_id
        for attempt_id, phase in events
        if phase == "intent"
    }
    if (
        allow_legacy_read_only
        and jobs
        and not events
        and sidecar.get("attemptJournalVersion") is None
        and sidecar.get("spendAuthority") is None
        and all(
            job.get("attemptId") is None and job.get("attemptState") is None
            for job in jobs.values()
        )
    ):
        return
    if set(jobs) != journal_attempts:
        raise BatchError(
            "provider batch sidecar attempts differ from the immutable attempt journal"
        )
    for attempt_id, job in jobs.items():
        intent = events.get((attempt_id, "intent"))
        expected_intent = _attempt_event_record(sidecar_path, job, phase="intent")
        if intent != expected_intent:
            raise BatchError("provider batch attempt differs from its immutable intent")
        for phase, recorded_phase in _ATTEMPT_RECORDED_PHASES.items():
            event = events.get((attempt_id, phase))
            recorded = events.get((attempt_id, recorded_phase))
            if (event is None) != (recorded is None):
                raise BatchError("provider batch attempt has an unacknowledged journal phase")
            if recorded is not None and recorded != _attempt_event_record(
                sidecar_path,
                job,
                phase=recorded_phase,
            ):
                raise BatchError(
                    "provider batch sidecar differs from an acknowledged journal phase"
                )
        pre_released = events.get((attempt_id, "preCreateReleased"))
        if (job.get("attemptState") in {"uploadFailed", "preCreateReleased"}) != (
            pre_released is not None
        ):
            raise BatchError("provider batch pre-create release differs from its journal")
        if pre_released is not None and pre_released != _attempt_event_record(
            sidecar_path,
            job,
            phase="preCreateReleased",
        ):
            raise BatchError("provider batch pre-create release differs from its journal")
        upload = events.get((attempt_id, "uploaded"))
        if bool(job.get("inputFileId")) != (upload is not None):
            raise BatchError("provider batch upload identity differs from its attempt journal")
        if upload is not None and upload != _attempt_event_record(
            sidecar_path,
            job,
            phase="uploaded",
        ):
            raise BatchError("provider batch upload identity differs from its attempt journal")
        started = events.get((attempt_id, "createStarted"))
        if bool(job.get("createStartedAt")) != (started is not None):
            raise BatchError("provider batch create start differs from its attempt journal")
        if started is not None and started != _attempt_event_record(
            sidecar_path,
            job,
            phase="createStarted",
        ):
            raise BatchError("provider batch create start differs from its attempt journal")
        created = events.get((attempt_id, "created"))
        if bool(job.get("jobId")) != (created is not None):
            raise BatchError("provider batch job identity differs from its attempt journal")
        if created is not None and created != _attempt_event_record(
            sidecar_path,
            job,
            phase="created",
        ):
            raise BatchError("provider batch job identity differs from its attempt journal")
        rejected = events.get((attempt_id, "createRejected"))
        if (job.get("attemptState") == "createRejected") != (rejected is not None):
            raise BatchError("provider batch create rejection differs from its attempt journal")
        if rejected is not None and rejected != _attempt_event_record(
            sidecar_path,
            job,
            phase="createRejected",
        ):
            raise BatchError("provider batch create rejection differs from its attempt journal")
        if rejected is not None:
            _verify_create_rejection(sidecar_path, job)
        if started is not None and upload is None:
            raise BatchError("provider batch create began without an uploaded input")
        if pre_released is not None and any(
            event is not None for event in (upload, started, created, rejected)
        ):
            raise BatchError("provider batch pre-create release conflicts with later provider I/O")
        if (created is not None or rejected is not None) and started is None:
            raise BatchError("provider batch create outcome has no create-start intent")
        if created is not None and rejected is not None:
            raise BatchError("provider batch attempt has two create outcomes")
    if any(attempt_id not in journal_attempts for attempt_id, _phase in events):
        raise BatchError("provider batch attempt journal has an event without an intent")


def _retain_content_addressed_bytes(
    sidecar_path: Path,
    payload: bytes,
    *,
    suffix: str,
) -> tuple[str, str]:
    """Atomically retain immutable provider bytes and return path plus digest."""

    digest_hex = hashlib.sha256(payload).hexdigest()
    digest = "sha256:" + digest_hex
    relative = f"{BATCH_EVIDENCE_DIRECTORY}/sha256-{digest_hex}{suffix}"
    destination = _safe_run_relative_path(sidecar_path.parent, relative)
    evidence_root = destination.parent
    if evidence_root.exists() and (evidence_root.is_symlink() or not evidence_root.is_dir()):
        raise BatchError("provider batch evidence directory is unsafe")
    evidence_root.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.is_symlink() or not destination.is_file() or destination.read_bytes() != payload:
            raise BatchError("content-addressed provider batch evidence differs from its digest")
    else:
        staging = evidence_root / f".{digest_hex}.{os.getpid()}.partial"
        try:
            with staging.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(staging, destination)
            except FileExistsError:
                if destination.is_symlink() or destination.read_bytes() != payload:
                    raise BatchError("content-addressed provider evidence raced with different bytes")
        finally:
            if staging.exists():
                staging.unlink()
    return relative, digest


def retain_result_artifact(
    sidecar_path: Path,
    payload: bytes,
    *,
    role: str,
    provider_file_id: str,
    endpoint: str,
) -> dict[str, Any]:
    """Atomically retain immutable provider result bytes under their digest."""

    relative, digest = _retain_content_addressed_bytes(
        sidecar_path,
        payload,
        suffix=".jsonl",
    )
    return {
        "bytes": len(payload),
        "endpoint": endpoint,
        "file": relative,
        "fileDigest": digest,
        "lineCount": _line_count(payload),
        "mediaType": "application/jsonl",
        "providerFileId": provider_file_id,
        "role": role,
    }


def retain_status_artifact(
    sidecar_path: Path,
    response: RetrievedJob,
    *,
    observed_at: str,
    poll_ordinal: int,
) -> dict[str, Any]:
    """Retain one exact provider status response before trusting its usage."""

    relative, digest = _retain_content_addressed_bytes(
        sidecar_path,
        response.raw_bytes,
        suffix=".json",
    )
    return {
        "bytes": len(response.raw_bytes),
        "endpoint": response.endpoint,
        "file": relative,
        "fileDigest": digest,
        "mediaType": "application/json",
        "observedAt": observed_at,
        "pollOrdinal": poll_ordinal,
        "responseStatus": response.response_status,
        "role": "status",
    }


def retain_create_rejection_artifact(
    sidecar_path: Path,
    rejection: BatchCreateRejected,
) -> dict[str, Any]:
    """Retain the exact definite create rejection before releasing its rows."""

    relative, digest = _retain_content_addressed_bytes(
        sidecar_path,
        rejection.payload,
        suffix=".bin",
    )
    return {
        "bytes": len(rejection.payload),
        "endpoint": rejection.endpoint,
        "file": relative,
        "fileDigest": digest,
        "mediaType": "application/octet-stream",
        "responseStatus": rejection.status,
        "role": "createRejection",
    }


def _read_pinned_provider_bytes(
    run_root: Path,
    pin: Mapping[str, Any],
    *,
    media_type: str,
) -> bytes:
    relative = pin.get("file")
    if not isinstance(relative, str):
        raise BatchError("provider batch artifact has no path")
    path = _safe_run_relative_path(run_root, relative)
    if not path.is_file() or path.is_symlink():
        raise BatchError("provider batch artifact is missing or unsafe")
    payload = path.read_bytes()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if (
        pin.get("fileDigest") != digest
        or pin.get("bytes") != len(payload)
        or pin.get("mediaType") != media_type
    ):
        raise BatchError("provider batch artifact differs from its pin")
    return payload


def read_result_artifact(run_root: Path, pin: Mapping[str, Any]) -> bytes:
    payload = _read_pinned_provider_bytes(
        run_root,
        pin,
        media_type="application/jsonl",
    )
    if pin.get("lineCount") != _line_count(payload):
        raise BatchError("provider batch result artifact differs from its pin")
    return payload


def result_lines_from_artifacts(
    run_root: Path,
    artifacts: Sequence[Mapping[str, Any]],
) -> tuple[ResultLineEvidence, ...]:
    lines: list[ResultLineEvidence] = []
    for artifact in artifacts:
        payload = read_result_artifact(run_root, artifact)
        for ordinal, raw_bytes in enumerate(payload.splitlines(keepends=True), start=1):
            content = raw_bytes[:-1] if raw_bytes.endswith(b"\n") else raw_bytes
            if content.endswith(b"\r"):
                content = content[:-1]
            try:
                text = content.decode("utf-8")
                parsed_value = json.loads(text) if text.strip() else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                text = content.decode("utf-8", errors="replace")
                parsed_value = None
            parsed = parsed_value if isinstance(parsed_value, Mapping) else None
            lines.append(
                ResultLineEvidence(
                    artifact=artifact,
                    line_ordinal=ordinal,
                    raw_bytes=raw_bytes,
                    raw_text=text,
                    parsed=parsed,
                )
            )
    return tuple(lines)


def has_results(job: Mapping[str, Any]) -> bool:
    """Whether the provider left this job any file to read.

    Not the same question as "did it succeed".  OpenAI documents that an
    *expired* batch still publishes whatever finished — "any responses to
    completed requests are made available via the batch's output file. You will
    be charged for tokens consumed from any completed requests" — so a job that
    ran out of window is answers already paid for, not a job that never ran.
    """

    return bool(job.get("outputFileId") or job.get("errorFileId"))


def _terminal_release_pin(job: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return a structurally linked terminal-release proof, if one remains."""

    proof = job.get("terminalRelease")
    artifacts = job.get("statusArtifacts")
    if (
        not isinstance(proof, Mapping)
        or not isinstance(artifacts, Sequence)
        or isinstance(artifacts, (str, bytes))
        or not artifacts
        or not isinstance(artifacts[-1], Mapping)
        or str(job.get("state")) not in {"failed", "cancelled", "expired"}
        or has_results(job)
    ):
        return None
    latest = artifacts[-1]
    expected = {
        "kind": "providerTerminalWithoutResults",
        "providerStatus": job.get("providerStatus"),
        "state": job.get("state"),
        "statusArtifactDigest": latest.get("fileDigest"),
        "statusArtifactFile": latest.get("file"),
        "statusPollOrdinal": latest.get("pollOrdinal"),
    }
    return proof if dict(proof) == expected else None


def _create_rejection_pin(job: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the exact definite create-rejection pin, when structurally valid."""

    pin = job.get("createRejection")
    if not isinstance(pin, Mapping):
        return None
    status = pin.get("responseStatus")
    if (
        job.get("jobId") is not None
        or job.get("attemptState") != "createRejected"
        or status not in DEFINITE_CREATE_REJECTION_STATUSES
        or pin.get("endpoint") != job.get("createEndpoint")
        or pin.get("role") != "createRejection"
    ):
        return None
    return pin


def _verify_create_rejection(sidecar_path: Path, job: Mapping[str, Any]) -> None:
    pin = _create_rejection_pin(job)
    if pin is None:
        raise BatchError("provider batch create rejection is invalid")
    _read_pinned_provider_bytes(
        sidecar_path.parent,
        pin,
        media_type="application/octet-stream",
    )


def released(job: Mapping[str, Any]) -> bool:
    """Whether this job has stopped holding its candidates.

    A job holds them until its answers are in hand, and lets go in exactly two
    situations: it has been collected (whatever it answered is in the receipt
    file, and whatever it lost is askable again), or retained provider status
    proves a terminal state with nothing to read. Mutable state alone never
    releases a created attempt or its conservative spend reserve.
    """

    if job.get("collectedAt"):
        return True
    if has_results(job):
        return False
    if str(job.get("state")) not in {"failed", "cancelled", "expired"}:
        return False
    # An upload failure before any provider job identity exists is safe to ask
    # again.  Once upload/create could have reached the provider, mutable state
    # alone never releases the conservative projection.
    if not job.get("jobId"):
        attempt_state = str(job.get("attemptState") or "")
        if attempt_state == "createRejected":
            return _create_rejection_pin(job) is not None
        return not job.get("inputFileId") and attempt_state not in {
            "creating",
            "createReceived",
            "createMismatch",
            "submitted",
            "uncertain",
        }
    return _terminal_release_pin(job) is not None


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
            committed = collection.get("committedCostUsd")
            if committed is None:
                legacy_actual = collection.get("assumedCostUsd")
                committed = (
                    float(legacy_actual)
                    if legacy_actual is not None
                    else float(job.get("projectedCostUsd") or 0.0)
                )
            totals[family] = totals.get(family, 0.0) + float(committed)
            continue
        if released(job):
            continue
        totals[family] = totals.get(family, 0.0) + float(job.get("projectedCostUsd") or 0.0)
    return totals


def _new_attempt_record(
    plan: Mapping[str, Any],
    *,
    family: ValidatorFamily,
    attempt_id: str,
    attempt_ordinal: int,
    spend_cap_usd: float,
    total_spend_cap_usd: float,
    spend_authority: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build the deterministic sidecar row named by an immutable intent."""

    provider = provider_for(family)
    priced = batch_family(family)
    return {
        **dict(plan),
        "assumedPricingUsdPerMtok": {
            "input": priced.assumed_input_usd_per_mtok,
            "output": priced.assumed_output_usd_per_mtok,
        },
        "attemptId": attempt_id,
        "attemptOrdinal": attempt_ordinal,
        "attemptState": "intent",
        "batchPricingFactor": BATCH_PRICE_FACTOR,
        "collectedAt": None,
        "completedAt": None,
        "completedAtSource": None,
        "completionWindow": COMPLETION_WINDOW,
        "createEndpoint": provider.batches_url,
        "createNormalizedState": None,
        "createProviderStatus": None,
        "createRejectedAt": None,
        "createRejection": None,
        "createRequestCounts": None,
        "createResponseIssue": None,
        "createStartedAt": None,
        "displayName": (
            f"refspec-atlas-crosswalk-{plan['workKind']}-{family.name}-"
            f"{str(plan['shardId'])[-12:]}-{int(plan['providerRequestCount'])}-requests"
        ),
        "errorFileId": None,
        "inputFileId": None,
        "inputUploadEndpoint": None,
        "jobId": None,
        "outputFileId": None,
        "preCreateReleasedAt": None,
        "preCreateReleaseReason": None,
        "providerStatus": "",
        "requestCounts": {},
        "resultArtifacts": [],
        "statusArtifacts": [],
        "spendCapUsd": spend_cap_usd,
        "spendAuthority": spend_authority,
        "state": "intent",
        "statusEndpoint": None,
        "submittedAt": None,
        "totalSpendCapUsd": total_spend_cap_usd,
        "vendor": family.vendor,
    }


def _create_uploaded_attempt(
    *,
    transport: BatchHttpTransport,
    sidecar_path: Path,
    sidecar: dict[str, Any],
    family: ValidatorFamily,
    api_key: str,
    record: dict[str, Any],
    now: Callable[[], str],
) -> dict[str, Any]:
    """Create one proven upload, retaining a durable boundary around the call."""

    if (
        record.get("attemptState") != "uploaded"
        or not record.get("inputFileId")
        or record.get("jobId")
        or record.get("createStartedAt")
    ):
        raise BatchError("provider batch upload is not safe to resume")
    provider = provider_for(family)
    create_metadata = {
        "attemptId": str(record["attemptId"]),
        "family": family.name,
        "refspec": SIDECAR_PROTOCOL,
        "shardId": str(record["shardId"]),
        "workKind": str(record["workKind"]),
    }
    create_started_at = now()
    started_record = {**record, "createStartedAt": create_started_at}
    _write_attempt_event(sidecar_path, started_record, phase="createStarted")
    record["attemptState"] = "creating"
    record["createStartedAt"] = create_started_at
    record["state"] = "creating"
    sidecar["updatedAt"] = create_started_at
    write_sidecar(sidecar_path, sidecar)
    _write_attempt_recorded(sidecar_path, record, phase="createStarted")

    try:
        job = provider.create_job(
            transport,
            api_key,
            str(record["inputFileId"]),
            metadata=create_metadata,
        )
    except BatchCreateRejected as error:
        rejected_at = now()
        rejection_pin = retain_create_rejection_artifact(sidecar_path, error)
        rejected_record = {
            **record,
            "createRejectedAt": rejected_at,
            "createRejection": rejection_pin,
        }
        _write_attempt_event(sidecar_path, rejected_record, phase="createRejected")
        record["attemptState"] = "createRejected"
        record["createRejectedAt"] = rejected_at
        record["createRejection"] = rejection_pin
        record["state"] = "failed"
        sidecar["updatedAt"] = rejected_at
        write_sidecar(sidecar_path, sidecar)
        _write_attempt_recorded(sidecar_path, record, phase="createRejected")
        raise
    except Exception:
        # Any missing response, server-side failure, 408, 409, or unclassified
        # status can follow a committed create.  It therefore stays reserved.
        record["attemptState"] = "uncertain"
        record["state"] = "uncertain"
        sidecar["updatedAt"] = now()
        write_sidecar(sidecar_path, sidecar)
        raise

    job_id = str(job.get("id") or job.get("name") or "")
    if not job_id:
        record["attemptState"] = "uncertain"
        record["state"] = "uncertain"
        sidecar["updatedAt"] = now()
        write_sidecar(sidecar_path, sidecar)
        raise BatchError(f"{family.name} batch create returned no job id")

    response_issue: str | None = None
    for field, expected in (
        ("input_file_id", record["inputFileId"]),
        ("endpoint", BATCH_REQUEST_URL),
        ("completion_window", COMPLETION_WINDOW),
    ):
        if field in job and job[field] != expected:
            response_issue = f"{family.name} batch create echoed another {field}"
            break
    echoed_metadata = job.get("metadata")
    if response_issue is None and isinstance(echoed_metadata, Mapping) and any(
        key in echoed_metadata and echoed_metadata[key] != value
        for key, value in create_metadata.items()
    ):
        response_issue = f"{family.name} batch create echoed different metadata"

    submitted_at = now()
    provider_status = str(job.get("status") or "")
    request_counts = dict(job.get("request_counts") or {})
    normalized_state = provider.normalize_state(job)
    created_record = {
        **record,
        "attemptState": "createMismatch" if response_issue else "submitted",
        "createNormalizedState": normalized_state,
        "createProviderStatus": provider_status,
        "createRequestCounts": request_counts,
        "createResponseIssue": response_issue,
        "jobId": job_id,
        "providerStatus": provider_status,
        "requestCounts": request_counts,
        "state": "uncertain" if response_issue else normalized_state,
        "statusEndpoint": provider.job_url(job_id),
        "submittedAt": submitted_at,
    }
    _write_attempt_event(sidecar_path, created_record, phase="created")
    record.update(created_record)
    sidecar["updatedAt"] = submitted_at
    write_sidecar(sidecar_path, sidecar)
    _write_attempt_recorded(sidecar_path, record, phase="created")
    if response_issue is not None:
        raise BatchError(response_issue)
    return record


# ---------------------------------------------------------------------------
# the three operations
# ---------------------------------------------------------------------------


def _validated_execution_controls(
    sidecar: Mapping[str, Any],
    *,
    rows: Sequence[CandidateRow],
    work_kind: WorkKind,
    spend_authority: Mapping[str, Any] | None,
    priority_provenance: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """Validate caller-supplied authority and governed row order exactly.

    Recovery callers must supply the same controls as the original submit.
    Treating an omitted expected value as "accept whatever the sidecar says"
    would let a repaired upload bypass the current local authority decision.
    """

    authority = (
        json.loads(canonical_json(dict(spend_authority)))
        if spend_authority is not None
        else None
    )
    if authority is not None and not authority:
        raise BatchError("provider batch spend authority must be a nonempty object")
    priority = (
        json.loads(canonical_json(dict(priority_provenance)))
        if priority_provenance is not None
        else None
    )
    if priority is not None and not priority:
        raise BatchError("provider batch priority provenance must be a nonempty object")
    ranked_rows = [row for row in rows if row.priority_rank is not None]
    if priority is not None:
        if work_kind != "validation" or len(ranked_rows) != len(rows):
            raise BatchError(
                "provider batch priority provenance requires ranked judging rows"
            )
        try:
            verified_priority = qual.validate_scorer_priority_provenance(priority)
        except qual.QualificationError as error:
            raise BatchError(
                f"provider batch priority provenance is invalid: {error}"
            ) from error
        if verified_priority["candidateCount"] != len(rows):
            raise BatchError(
                "provider batch priority provenance does not cover every judging row"
            )
        rank_values = [row.priority_rank for row in rows]
        if any(
            isinstance(rank, bool) or not isinstance(rank, int)
            for rank in rank_values
        ) or set(rank_values) != set(range(len(rows))):
            raise BatchError(
                "provider batch judging priority ranks must be contiguous from zero"
            )
        ordered_ids = [
            row.candidate_id
            for row in sorted(
                rows,
                key=lambda row: int(row.priority_rank or 0),
            )
        ]
        if qual._sha256_text(canonical_json(ordered_ids)) != verified_priority[
            "orderedCandidateIdsDigest"
        ]:
            raise BatchError(
                "provider batch judging ranks differ from priority provenance"
            )
    elif ranked_rows:
        raise BatchError("ranked judging rows require priority provenance")
    recorded_priority = sidecar.get("priorityProvenance")
    if (
        recorded_priority is not None
        or sidecar.get("jobs")
        or sidecar.get("plannedShards")
    ) and recorded_priority != priority:
        raise BatchError("provider batch priority provenance cannot change or be omitted")
    recorded_authority = sidecar.get("spendAuthority")
    if (
        recorded_authority is not None
        or sidecar.get("jobs")
        or sidecar.get("plannedShards")
    ) and recorded_authority != authority:
        raise BatchError("provider batch spend authority cannot change or be omitted")
    return authority, priority


def _validated_sidecar_caps(
    sidecar: Mapping[str, Any],
    *,
    label: str,
) -> tuple[dict[str, float], float | None]:
    """Reproduce family and total caps from mutable fields and journaled jobs."""

    raw_caps = sidecar.get("spendCapsByFamily")
    if raw_caps is None:
        raw_caps = {}
    if not isinstance(raw_caps, Mapping):
        raise BatchError(f"{label} has invalid family spend caps")
    family_caps: dict[str, float] = {}
    for raw_family, raw_cap in raw_caps.items():
        if (
            isinstance(raw_cap, bool)
            or not isinstance(raw_cap, (int, float))
            or not math.isfinite(float(raw_cap))
            or float(raw_cap) <= 0
        ):
            raise BatchError(f"{label} has an invalid {raw_family} spend cap")
        family_caps[str(raw_family)] = float(raw_cap)

    job_totals: set[float] = set()
    for job in sidecar.get("jobs", ()):
        if not isinstance(job, Mapping):
            raise BatchError(f"{label} contains a non-object provider attempt")
        family_name = str(job.get("family") or "")
        raw_family_cap = job.get("spendCapUsd")
        raw_total_cap = job.get("totalSpendCapUsd")
        if (
            not family_name
            or isinstance(raw_family_cap, bool)
            or not isinstance(raw_family_cap, (int, float))
            or not math.isfinite(float(raw_family_cap))
            or float(raw_family_cap) <= 0
            or isinstance(raw_total_cap, bool)
            or not isinstance(raw_total_cap, (int, float))
            or not math.isfinite(float(raw_total_cap))
            or float(raw_total_cap) <= 0
        ):
            raise BatchError(f"{label} has invalid journal-pinned spend caps")
        family_cap = float(raw_family_cap)
        declared = family_caps.get(family_name)
        if declared is not None and declared != family_cap:
            raise BatchError(
                f"{label} {family_name} spend cap differs from its provider attempt"
            )
        family_caps[family_name] = family_cap
        job_totals.add(float(raw_total_cap))
    if len(job_totals) > 1:
        raise BatchError(f"{label} provider attempts disagree on the total spend cap")

    raw_total = sidecar.get("totalSpendCapUsd")
    if raw_total is not None and (
        isinstance(raw_total, bool)
        or not isinstance(raw_total, (int, float))
        or not math.isfinite(float(raw_total))
        or float(raw_total) <= 0
    ):
        raise BatchError(f"{label} has an invalid total spend cap")
    total_cap = float(raw_total) if raw_total is not None else None
    if job_totals:
        job_total = next(iter(job_totals))
        if total_cap is not None and total_cap != job_total:
            raise BatchError(
                f"{label} total spend cap differs from its provider attempts"
            )
        total_cap = job_total
    return family_caps, total_cap


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
    total_cap_usd: float | None = None,
    protocol: str,
    work_kind: WorkKind = "validation",
    group_size: int = DEFAULT_REQUEST_GROUP_SIZE,
    coordination_sidecars: Sequence[Path] = (),
    spend_authority: Mapping[str, Any] | None = None,
    priority_provenance: Mapping[str, Any] | None = None,
    mutation_guard: Callable[[], None] | None = None,
    lock_timeout_seconds: float = DEFAULT_SUBMIT_LOCK_TIMEOUT_SECONDS,
    now: Callable[[], str] = qual._utcnow,
) -> dict[str, Any]:
    """Serialize, plan, and create at most one active shard per family/model."""

    with _run_submit_lock(
        sidecar_path,
        coordination_sidecars,
        timeout_seconds=lock_timeout_seconds,
    ):
        if mutation_guard is not None:
            mutation_guard()
        return _submit_locked(
            transport=transport,
            receipts_path=receipts_path,
            sidecar_path=sidecar_path,
            families=families,
            keys=keys,
            models=models,
            rows=rows,
            caps=caps,
            total_cap_usd=total_cap_usd,
            protocol=protocol,
            work_kind=work_kind,
            group_size=group_size,
            coordination_sidecars=coordination_sidecars,
            spend_authority=spend_authority,
            priority_provenance=priority_provenance,
            now=now,
        )


def _submit_locked(
    *,
    transport: BatchHttpTransport,
    receipts_path: Path,
    sidecar_path: Path,
    families: Sequence[ValidatorFamily],
    keys: Mapping[str, str],
    models: Mapping[str, str],
    rows: Sequence[CandidateRow],
    caps: Mapping[str, float] | None = None,
    total_cap_usd: float | None = None,
    protocol: str,
    work_kind: WorkKind = "validation",
    group_size: int = DEFAULT_REQUEST_GROUP_SIZE,
    coordination_sidecars: Sequence[Path] = (),
    spend_authority: Mapping[str, Any] | None = None,
    priority_provenance: Mapping[str, Any] | None = None,
    now: Callable[[], str] = qual._utcnow,
) -> dict[str, Any]:
    """Plan and create while the caller holds the run-wide submit lock."""

    effective_total_cap = (
        qual.TOTAL_SPEND_CAP_USD if total_cap_usd is None else float(total_cap_usd)
    )
    if not math.isfinite(effective_total_cap) or effective_total_cap <= 0:
        raise ValueError("total batch spend cap must be a positive finite USD value")

    speaks = _require_work_protocol(protocol, work_kind)
    sidecar = read_sidecar(sidecar_path)
    known_families = {
        **qual.VALIDATOR_FAMILIES,
        **{family.name: family for family in families},
    }
    _reconcile_attempt_journal(
        sidecar_path,
        sidecar,
        families=known_families,
        now=now,
    )
    _verify_attempt_journal(sidecar_path, sidecar)
    _verify_terminal_releases(sidecar_path, sidecar, known_families)
    authority, priority = _validated_execution_controls(
        sidecar,
        rows=rows,
        work_kind=work_kind,
        spend_authority=spend_authority,
        priority_provenance=priority_provenance,
    )
    recorded_total_cap = sidecar.get("totalSpendCapUsd")
    if (
        recorded_total_cap is not None
        and sidecar.get("jobs")
        and float(recorded_total_cap) != effective_total_cap
    ):
        raise BatchError("batch total spend cap cannot change after the first submission intent")
    excluded = read_receipt_pairs(receipts_path) | in_flight_pairs(sidecar)
    committed = committed_by_family(sidecar)
    rows_by_id = {row.candidate_id: row for row in rows}
    coordination_states: list[dict[str, Any]] = []
    for coordination_path in coordination_sidecars:
        other = read_sidecar(coordination_path)
        _reconcile_attempt_journal(
            coordination_path,
            other,
            families=known_families,
            now=now,
        )
        _verify_attempt_journal(coordination_path, other)
        _verify_terminal_releases(coordination_path, other, known_families)
        coordination_states.append(other)
        other_authority = other.get("spendAuthority")
        if (
            other_authority is not None
            or other.get("jobs")
            or other.get("plannedShards")
        ) and other_authority != authority:
            raise BatchError("coordinated batch sidecars must use one spend authority")
        for family_name, amount in committed_by_family(other).items():
            committed[family_name] = committed.get(family_name, 0.0) + amount
    if sidecar.get("plannedShards") or sidecar.get("jobs"):
        verify_sidecar_request_lineage(
            sidecar,
            families=known_families,
            rows=rows,
            work_kind=work_kind,
        )
    spend_caps, pinned_total_cap = _validated_sidecar_caps(
        sidecar,
        label="provider batch sidecar",
    )
    if pinned_total_cap is not None and pinned_total_cap != effective_total_cap:
        raise BatchError(
            "batch total spend cap cannot change after the first submission intent"
        )
    coordinated_caps: dict[str, float] = {}
    for other in coordination_states:
        other_caps, other_total_cap = _validated_sidecar_caps(
            other,
            label="coordinated batch sidecar",
        )
        if other_total_cap is not None and other_total_cap != effective_total_cap:
            raise BatchError(
                "coordinated batch sidecars must use one total spend cap"
            )
        for family_name, cap in other_caps.items():
            prior = coordinated_caps.get(family_name)
            if prior is not None and prior != cap:
                raise BatchError(
                    f"{family_name} coordinated batch sidecars disagree on their spend cap"
                )
            coordinated_caps[family_name] = cap
    selected_caps: dict[str, float] = {}
    for family in families:
        cap = (
            float(caps[family.name])
            if caps is not None and family.name in caps
            else family.spend_cap_usd
        )
        if not math.isfinite(cap) or cap <= 0:
            raise ValueError(
                f"{family.name} batch spend cap must be a positive finite USD value"
            )
        if family.name in spend_caps and float(spend_caps[family.name]) != cap:
            raise BatchError(
                f"{family.name} batch spend cap cannot change after planning"
            )
        if (
            family.name in coordinated_caps
            and coordinated_caps[family.name] != cap
        ):
            raise BatchError(
                f"{family.name} coordinated batch sidecars must use one spend cap"
            )
        if committed.get(family.name, 0.0) > cap:
            raise BatchSpendCapReached(
                f"{family.name}: ${committed[family.name]:.4f} already committed "
                f"exceeds the current ${cap:.2f} cap"
            )
        selected_caps[family.name] = cap
    if sum(committed.values()) > effective_total_cap:
        raise BatchSpendCapReached(
            f"${sum(committed.values()):.2f} already committed exceeds the "
            f"${effective_total_cap:.2f} total cap"
        )
    selected_families = {family.name: family for family in families}
    resumed: list[dict[str, Any]] = []
    for raw_job in sidecar.get("jobs", ()):
        if not isinstance(raw_job, dict) or raw_job.get("attemptState") != "uploaded":
            continue
        family_name = str(raw_job.get("family") or "")
        family = selected_families.get(family_name)
        if family is None:
            continue
        if (
            float(raw_job.get("spendCapUsd") or 0.0)
            != selected_caps[family_name]
            or float(raw_job.get("totalSpendCapUsd") or 0.0)
            != effective_total_cap
        ):
            raise BatchError(
                f"resumable {family_name} upload differs from the current spend caps"
            )
        if str(raw_job.get("modelId") or "") != str(models.get(family_name) or ""):
            raise BatchError("resumable provider upload uses another resolved model")
        resumed.append(
            _create_uploaded_attempt(
                transport=transport,
                sidecar_path=sidecar_path,
                sidecar=sidecar,
                family=family,
                api_key=keys[family_name],
                record=raw_job,
                now=now,
            )
        )
    if resumed:
        _verify_attempt_journal(sidecar_path, sidecar)
    externally_active = {
        (str(job.get("family")), str(job.get("modelId")))
        for other in coordination_states
        for job in other.get("jobs", ())
        if isinstance(job, Mapping) and not released(job)
    }

    if isinstance(group_size, bool) or not 1 <= group_size <= MAX_REQUEST_GROUP_SIZE:
        raise ValueError(f"group size must be between 1 and {MAX_REQUEST_GROUP_SIZE}")

    planned: list[
        tuple[ValidatorFamily, list[CandidateRow], tuple[ProviderRequest, ...], float]
    ] = []
    existing_plans = {
        str(plan.get("shardId")): plan
        for plan in sidecar.get("plannedShards", ())
        if isinstance(plan, Mapping)
    }
    submitted_shards = {
        str(job.get("shardId"))
        for job in sidecar.get("jobs", ())
        if isinstance(job, Mapping)
    }
    for family in families:
        pending = [row for row in rows if (row.candidate_id, family.name) not in excluded]
        if not pending:
            planned.append((family, pending, (), 0.0))
            continue

        pending_ids = {row.candidate_id for row in pending}
        reserved_ids: set[str] = set()
        reserved_requests: list[ProviderRequest] = []
        for plan in sidecar.get("plannedShards", ()):
            if (
                not isinstance(plan, Mapping)
                or str(plan.get("family")) != family.name
                or str(plan.get("modelId")) != models[family.name]
                or str(plan.get("protocol")) != speaks
                or str(plan.get("workKind")) != work_kind
                or str(plan.get("shardId")) in submitted_shards
            ):
                continue
            plan_ids = {
                str(item.get("candidateId"))
                for item in plan.get("requests", ())
                if isinstance(item, Mapping)
            }
            if plan_ids and plan_ids <= pending_ids and not (plan_ids & reserved_ids):
                reserved_ids.update(plan_ids)
                reserved_requests.extend(
                    _rebuild_requests_from_record(
                        plan,
                        family=family,
                        rows_by_id=rows_by_id,
                    )
                )

        recovery_rows = [row for row in pending if row.candidate_id not in reserved_ids]
        recovery_requests = build_provider_requests(
            family,
            models[family.name],
            recovery_rows,
            protocol=speaks,
            work_kind=work_kind,
            group_size=group_size,
        )
        recovery_shards = deterministic_request_shards(
            family,
            models[family.name],
            recovery_requests,
            protocol=speaks,
            work_kind=work_kind,
        )
        for shard in recovery_shards:
            record = _planned_shard_record(
                family,
                models[family.name],
                shard,
                protocol=speaks,
                work_kind=work_kind,
                group_size=group_size,
            )
            existing = existing_plans.get(shard.shard_id)
            if existing is not None:
                comparable = dict(existing)
                comparable.pop("planOrder", None)
                if comparable != record:
                    raise BatchError(f"planned shard {shard.shard_id} changed identity")
            if existing is None:
                record["planOrder"] = len(sidecar.setdefault("plannedShards", [])) + 1
                sidecar["plannedShards"].append(record)
                existing_plans[shard.shard_id] = record
        requests = (*reserved_requests, *recovery_requests)
        projection = projected_request_cost(family, requests)
        cap = selected_caps[family.name]
        spend_caps[family.name] = cap
        already = committed.get(family.name, 0.0)
        if projection + already > cap:
            raise BatchSpendCapReached(
                f"{family.name}: submitting {len(pending)} candidates in {len(requests)} batch requests projects "
                f"${projection:.4f} which, with ${already:.4f} already in flight, "
                f"exceeds the ${cap:.2f} cap; shrink the slice with --max-candidates"
            )
        planned.append((family, pending, requests, projection))

    # The total counts what earlier submits already bought too.  Checking only
    # this invocation would let N single-family submits walk past a ceiling one
    # combined submit would have refused.
    total = sum(projection for _family, _pending, _requests, projection in planned)
    running = total + sum(committed.values())
    if running > effective_total_cap:
        raise BatchSpendCapReached(
            f"projected ${total:.2f} which, with ${sum(committed.values()):.2f} already committed, "
            f"exceeds the ${effective_total_cap:.2f} total cap; shrink the slice"
        )

    sidecar["batchPricingFactor"] = BATCH_PRICE_FACTOR
    sidecar["attemptJournalVersion"] = BATCH_ATTEMPT_JOURNAL_VERSION
    sidecar["protocol"] = SIDECAR_PROTOCOL
    if authority is not None:
        sidecar["spendAuthority"] = authority
    if priority is not None:
        sidecar["priorityProvenance"] = priority
    sidecar["totalSpendCapUsd"] = effective_total_cap
    sidecar["spendCapsByFamily"] = dict(sorted(spend_caps.items()))
    sidecar["queuePolicy"] = {
        "accountTier": "notChecked",
        "maxInputTokensPerJob": MAX_PROVIDER_JOB_INPUT_TOKENS,
        "maxProviderRequestsPerJob": MAX_PROVIDER_REQUESTS_PER_JOB,
        "oneActiveShardPerFamilyModel": True,
    }
    sidecar["updatedAt"] = now()
    # All provider jobs are pinned before the first byte can leave the process.
    write_sidecar(sidecar_path, sidecar)

    submitted: list[dict[str, Any]] = list(resumed)
    pending_by_family = {
        family.name: {row.candidate_id for row in pending}
        for family, pending, _requests, _projection in planned
    }
    for family, pending, _requests, _projection in planned:
        if not pending:
            continue
        provider = provider_for(family)
        model_id = models[family.name]
        active = [
            job
            for job in sidecar.get("jobs", ())
            if isinstance(job, Mapping)
            and str(job.get("family")) == family.name
            and str(job.get("modelId")) == model_id
            and not released(job)
        ]
        if active or (family.name, model_id) in externally_active:
            continue
        eligible: list[Mapping[str, Any]] = []
        for plan in sidecar.get("plannedShards", ()):
            if (
                not isinstance(plan, Mapping)
                or str(plan.get("family")) != family.name
                or str(plan.get("modelId")) != model_id
                or str(plan.get("protocol")) != speaks
                or str(plan.get("workKind")) != work_kind
            ):
                continue
            plan_ids = {
                str(item.get("candidateId"))
                for item in plan.get("requests", ())
                if isinstance(item, Mapping)
            }
            if plan_ids and plan_ids <= pending_by_family[family.name]:
                eligible.append(plan)
        if not eligible:
            continue
        shard_plan = min(eligible, key=lambda item: (int(item.get("planOrder") or 0), str(item["shardId"])))
        requests = _rebuild_requests_from_record(
            shard_plan,
            family=family,
            rows_by_id=rows_by_id,
        )
        payload = input_jsonl(requests)
        shard_rows = [
            rows_by_id[str(item["candidateId"])]
            for item in shard_plan["requests"]
        ]
        assert_payload_speaks(payload, speaks, rows=shard_rows, work_kind=work_kind)
        prior_attempts = [
            job
            for job in sidecar.get("jobs", ())
            if isinstance(job, Mapping) and job.get("shardId") == shard_plan["shardId"]
        ]
        attempt_ordinal = 1 + max(
            (int(job.get("attemptOrdinal") or 0) for job in prior_attempts),
            default=0,
        )
        attempt_id = "attempt-" + hashlib.sha256(
            f"{shard_plan['shardId']}|{attempt_ordinal}".encode()
        ).hexdigest()
        record = _new_attempt_record(
            shard_plan,
            family=family,
            attempt_id=attempt_id,
            attempt_ordinal=attempt_ordinal,
            spend_cap_usd=(
                float(caps.get(family.name))
                if caps and family.name in caps
                else family.spend_cap_usd
            ),
            total_spend_cap_usd=effective_total_cap,
            spend_authority=authority,
        )
        # This immutable intent exists before the first provider byte leaves.
        # If the replace-in-place sidecar later loses this job, reconciliation
        # fails closed instead of buying the shard again.
        _write_attempt_event(sidecar_path, record, phase="intent")
        sidecar.setdefault("jobs", []).append(record)
        sidecar["updatedAt"] = now()
        write_sidecar(sidecar_path, sidecar)
        _write_attempt_recorded(sidecar_path, record, phase="intent")

        try:
            uploaded = provider.upload_input(
                transport,
                keys[family.name],
                payload,
                str(record["displayName"]) + ".jsonl",
            )
        except Exception:
            released_at = now()
            record["attemptState"] = "uploadFailed"
            record["preCreateReleasedAt"] = released_at
            record["preCreateReleaseReason"] = "uploadDidNotYieldFileIdentity"
            record["state"] = "failed"
            _write_attempt_event(sidecar_path, record, phase="preCreateReleased")
            sidecar["updatedAt"] = released_at
            write_sidecar(sidecar_path, sidecar)
            _write_attempt_recorded(sidecar_path, record, phase="preCreateReleased")
            raise
        uploaded_record = {
            **record,
            "inputFileId": uploaded.file_id,
            "inputUploadEndpoint": uploaded.endpoint,
        }
        _write_attempt_event(sidecar_path, uploaded_record, phase="uploaded")
        record["attemptState"] = "uploaded"
        record["inputFileId"] = uploaded.file_id
        record["inputUploadEndpoint"] = uploaded.endpoint
        record["state"] = "uploaded"
        sidecar["updatedAt"] = now()
        write_sidecar(sidecar_path, sidecar)
        _write_attempt_recorded(sidecar_path, record, phase="uploaded")
        submitted.append(
            _create_uploaded_attempt(
                transport=transport,
                sidecar_path=sidecar_path,
                sidecar=sidecar,
                family=family,
                api_key=keys[family.name],
                record=record,
                now=now,
            )
        )

    sidecar["updatedAt"] = now()
    write_sidecar(sidecar_path, sidecar)
    return {
        "jobs": [
            {
                "candidateCount": record["candidateCount"],
                "family": record["family"],
                "jobId": record["jobId"],
                "attemptId": record["attemptId"],
                "projectedCostUsd": record["projectedCostUsd"],
                "providerRequestCount": record["providerRequestCount"],
                "shardId": record["shardId"],
                "state": record["state"],
            }
            for record in submitted
        ],
        "protocol": speaks,
        "providerJobCount": len(sidecar.get("plannedShards", ())),
        "totalSpendCapUsd": effective_total_cap,
        "totalProjectedCostUsd": round(total, 6),
    }


def reconcile(
    *,
    transport: BatchHttpTransport,
    sidecar_path: Path,
    families: Mapping[str, ValidatorFamily],
    keys: Mapping[str, str],
    rows: Sequence[CandidateRow],
    work_kind: WorkKind,
    coordination_sidecars: Sequence[Path] = (),
    spend_authority: Mapping[str, Any] | None = None,
    priority_provenance: Mapping[str, Any] | None = None,
    mutation_guard: Callable[[], None] | None = None,
    lock_timeout_seconds: float = DEFAULT_SUBMIT_LOCK_TIMEOUT_SECONDS,
    now: Callable[[], str] = qual._utcnow,
) -> dict[str, Any]:
    """Repair journal state and resume only after rebuilding its exact plan."""

    with _run_submit_lock(
        sidecar_path,
        coordination_sidecars,
        timeout_seconds=lock_timeout_seconds,
    ):
        if mutation_guard is not None:
            mutation_guard()
        sidecar = read_sidecar(sidecar_path)
        known_families = {**qual.VALIDATOR_FAMILIES, **dict(families)}
        summary = _reconcile_attempt_journal(
            sidecar_path,
            sidecar,
            families=known_families,
            now=now,
        )
        _verify_attempt_journal(sidecar_path, sidecar)
        _verify_terminal_releases(sidecar_path, sidecar, known_families)
        coordination_states: list[Mapping[str, Any]] = []
        for coordination_path in coordination_sidecars:
            other = read_sidecar(coordination_path)
            _reconcile_attempt_journal(
                coordination_path,
                other,
                families=known_families,
                now=now,
            )
            _verify_attempt_journal(coordination_path, other)
            _verify_terminal_releases(coordination_path, other, known_families)
            coordination_states.append(other)

        authority, _priority = _validated_execution_controls(
            sidecar,
            rows=rows,
            work_kind=work_kind,
            spend_authority=spend_authority,
            priority_provenance=priority_provenance,
        )
        committed = committed_by_family(sidecar)
        for other in coordination_states:
            other_authority = other.get("spendAuthority")
            if (
                other_authority is not None
                or other.get("jobs")
                or other.get("plannedShards")
            ) and other_authority != authority:
                raise BatchError(
                    "coordinated batch sidecars must use one spend authority"
                )
            for family_name, amount in committed_by_family(other).items():
                committed[family_name] = committed.get(family_name, 0.0) + amount
        if sidecar.get("plannedShards") or sidecar.get("jobs"):
            verify_sidecar_request_lineage(
                sidecar,
                families=known_families,
                rows=rows,
                work_kind=work_kind,
            )
        selected_caps, selected_total_cap = _validated_sidecar_caps(
            sidecar,
            label="provider batch sidecar",
        )
        authority_cap = (
            spend_authority.get("runSpendCapUsd")
            if isinstance(spend_authority, Mapping)
            else None
        )
        if authority_cap is not None:
            if (
                isinstance(authority_cap, bool)
                or not isinstance(authority_cap, (int, float, str))
            ):
                raise BatchError("provider batch spend authority has an invalid run cap")
            try:
                current_total_cap = float(authority_cap)
            except ValueError as error:
                raise BatchError(
                    "provider batch spend authority has an invalid run cap"
                ) from error
            if not math.isfinite(current_total_cap) or current_total_cap <= 0:
                raise BatchError("provider batch spend authority has an invalid run cap")
        else:
            current_total_cap = selected_total_cap
        coordinated_caps: dict[str, float] = {}
        for other in coordination_states:
            other_caps, other_total_cap = _validated_sidecar_caps(
                other,
                label="coordinated batch sidecar",
            )
            if (
                current_total_cap is not None
                and other_total_cap is not None
                and other_total_cap != current_total_cap
            ):
                raise BatchError(
                    "coordinated batch sidecars must use one total spend cap"
                )
            for family_name, cap in other_caps.items():
                prior = coordinated_caps.get(family_name)
                if prior is not None and prior != cap:
                    raise BatchError(
                        f"{family_name} coordinated batch sidecars disagree on their spend cap"
                )
                coordinated_caps[family_name] = cap
        has_resumable_upload = any(
            isinstance(job, Mapping)
            and job.get("attemptState") == "uploaded"
            and str(job.get("family") or "") in families
            for job in sidecar.get("jobs", ())
        )
        if has_resumable_upload:
            effective_caps = dict(coordinated_caps)
            for family_name, cap in selected_caps.items():
                coordinated_cap = effective_caps.get(family_name)
                if coordinated_cap is not None and coordinated_cap != cap:
                    raise BatchError(
                        f"{family_name} coordinated batch sidecars must use one spend cap"
                    )
                effective_caps[family_name] = cap
            for family_name, amount in committed.items():
                cap = effective_caps.get(family_name)
                if cap is None:
                    raise BatchError(
                        f"committed {family_name} provider work has no current spend cap"
                    )
                if amount > cap:
                    raise BatchSpendCapReached(
                        f"{family_name}: ${amount:.4f} already committed exceeds the "
                        f"current ${cap:.2f} cap"
                    )
            if current_total_cap is None:
                raise BatchError(
                    "resumable provider upload has no current total spend cap"
                )
            if sum(committed.values()) > current_total_cap:
                raise BatchSpendCapReached(
                    f"${sum(committed.values()):.2f} already committed exceeds the "
                    f"${current_total_cap:.2f} total cap"
                )
        for raw_job in sidecar.get("jobs", ()):
            if not isinstance(raw_job, Mapping) or raw_job.get("attemptState") != "uploaded":
                continue
            family_name = str(raw_job.get("family") or "")
            if family_name not in families:
                continue
            selected_cap = selected_caps.get(family_name)
            if selected_cap is None or current_total_cap is None:
                raise BatchError(
                    f"resumable {family_name} upload has no current spend caps"
                )
            if authority_cap is not None and selected_cap != current_total_cap:
                raise BatchError(
                    f"resumable {family_name} upload differs from its spend authority cap"
                )
            if (
                family_name in coordinated_caps
                and coordinated_caps[family_name] != selected_cap
            ):
                raise BatchError(
                    f"{family_name} coordinated batch sidecars must use one spend cap"
                )
            if (
                float(raw_job.get("spendCapUsd") or 0.0) != selected_cap
                or float(raw_job.get("totalSpendCapUsd") or 0.0)
                != current_total_cap
            ):
                raise BatchError(
                    f"resumable {family_name} upload differs from the current spend caps"
                )

        resumed: list[dict[str, Any]] = []
        definite_rejections: list[dict[str, Any]] = []
        for raw_job in sidecar.get("jobs", ()):
            if not isinstance(raw_job, dict) or raw_job.get("attemptState") != "uploaded":
                continue
            family_name = str(raw_job.get("family") or "")
            family = families.get(family_name)
            if family is None or family_name not in keys:
                raise BatchError(
                    f"resumable provider upload requires credentials for {family_name!r}"
                )
            try:
                resumed_job = _create_uploaded_attempt(
                    transport=transport,
                    sidecar_path=sidecar_path,
                    sidecar=sidecar,
                    family=family,
                    api_key=keys[family_name],
                    record=raw_job,
                    now=now,
                )
            except BatchCreateRejected as error:
                definite_rejections.append(
                    {
                        "attemptId": raw_job.get("attemptId"),
                        "family": family_name,
                        "responseStatus": error.status,
                    }
                )
                continue
            resumed.append(
                {
                    "attemptId": resumed_job.get("attemptId"),
                    "family": family_name,
                    "jobId": resumed_job.get("jobId"),
                    "state": resumed_job.get("state"),
                }
            )
        _verify_attempt_journal(sidecar_path, sidecar)
        refreshed = _reconcile_attempt_journal(
            sidecar_path,
            sidecar,
            families=known_families,
            now=now,
        )
        return {
            **summary,
            "definiteCreateRejections": definite_rejections,
            "heldAmbiguousAttemptIds": refreshed["heldAmbiguousAttemptIds"],
            "rejectedAttemptIds": refreshed["rejectedAttemptIds"],
            "resumableAttemptIds": refreshed["resumableAttemptIds"],
            "resumedJobs": resumed,
        }


@dataclass(frozen=True, slots=True)
class ProviderStatusFacts:
    """Fields one provider status response can authoritatively supply."""

    aggregate_usage: NormalizedUsage
    completed_at: str | None
    error_file_field: bool
    error_file_id: str | None
    output_file_field: bool
    output_file_id: str | None
    provider_status: str
    request_counts: Mapping[str, Any] | None
    state: str


def _status_file_field(payload: Mapping[str, Any], field: str) -> tuple[bool, str | None]:
    if field not in payload:
        return False, None
    value = payload.get(field)
    if value is None:
        return True, None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise BatchError(f"provider batch status {field} is invalid")
    return True, value


def _provider_status_facts(
    payload: Mapping[str, Any],
    family: ValidatorFamily,
) -> ProviderStatusFacts:
    provider = provider_for(family)
    raw_counts = payload.get("request_counts")
    if raw_counts is not None and not isinstance(raw_counts, Mapping):
        raise BatchError("provider batch status request_counts is invalid")
    output_field, output_file_id = _status_file_field(payload, "output_file_id")
    error_field, error_file_id = _status_file_field(payload, "error_file_id")
    return ProviderStatusFacts(
        aggregate_usage=normalize_provider_usage(payload, family),
        completed_at=_epoch_to_iso(payload.get("completed_at")),
        error_file_field=error_field,
        error_file_id=error_file_id,
        output_file_field=output_field,
        output_file_id=output_file_id,
        provider_status=str(payload.get("status") or ""),
        request_counts=(dict(raw_counts) if isinstance(raw_counts, Mapping) else None),
        state=provider.normalize_state(payload),
    )


def poll(
    *,
    transport: BatchHttpTransport,
    sidecar_path: Path,
    families: Mapping[str, ValidatorFamily],
    keys: Mapping[str, str],
    mutation_guard: Callable[[], None] | None = None,
    lock_timeout_seconds: float = DEFAULT_SUBMIT_LOCK_TIMEOUT_SECONDS,
    now: Callable[[], str] = qual._utcnow,
) -> dict[str, Any]:
    """Refresh every non-terminal job's state into the sidecar."""

    with _run_submit_lock(
        sidecar_path,
        (),
        timeout_seconds=lock_timeout_seconds,
    ):
        if mutation_guard is not None:
            mutation_guard()
        return _poll_locked(
            transport=transport,
            sidecar_path=sidecar_path,
            families=families,
            keys=keys,
            now=now,
        )


def _poll_locked(
    *,
    transport: BatchHttpTransport,
    sidecar_path: Path,
    families: Mapping[str, ValidatorFamily],
    keys: Mapping[str, str],
    now: Callable[[], str],
) -> dict[str, Any]:
    """Poll while the caller owns the run-wide sidecar mutation lock."""

    sidecar = read_sidecar(sidecar_path)
    known_families = {**qual.VALIDATOR_FAMILIES, **families}
    _verify_attempt_journal(sidecar_path, sidecar)
    _verify_terminal_releases(sidecar_path, sidecar, known_families)
    states: list[dict[str, Any]] = []
    for job in sidecar.get("jobs", ()):
        family = families[str(job["family"])]
        provider = provider_for(family)
        job_id = job.get("jobId")
        state = str(job.get("state"))
        trusted_terminal = state == "succeeded" or has_results(job) or released(job)
        if not job_id or (state in TERMINAL_STATES and trusted_terminal):
            states.append(_job_state_row(job))
            continue
        response = provider.retrieve_job(transport, keys[family.name], str(job_id))
        payload = response.payload
        polled_at = now()
        status_artifacts = job.setdefault("statusArtifacts", [])
        if not isinstance(status_artifacts, list):
            raise BatchError(f"job {job_id} status artifacts are invalid")
        status_pin = retain_status_artifact(
            sidecar_path,
            response,
            observed_at=polled_at,
            poll_ordinal=len(status_artifacts) + 1,
        )
        status_artifacts.append(status_pin)
        facts = _provider_status_facts(payload, family)
        job["providerStatus"] = facts.provider_status
        job["state"] = facts.state
        job["requestCounts"] = dict(facts.request_counts or {})
        if facts.output_file_field:
            job["outputFileId"] = facts.output_file_id
        if facts.error_file_field:
            job["errorFileId"] = facts.error_file_id
        if facts.aggregate_usage.raw:
            job["aggregateUsage"] = {
                "statusArtifactDigest": status_pin["fileDigest"],
                "statusArtifactFile": status_pin["file"],
                "statusPollOrdinal": status_pin["pollOrdinal"],
                "usage": facts.aggregate_usage.record(),
            }
        else:
            job.pop("aggregateUsage", None)
        if facts.completed_at:
            job["completedAt"] = facts.completed_at
            job["completedAtSource"] = {
                "kind": "providerStatus",
                "statusArtifactDigest": status_pin["fileDigest"],
                "statusArtifactFile": status_pin["file"],
                "statusPollOrdinal": status_pin["pollOrdinal"],
            }
        if (
            facts.state in {"failed", "cancelled", "expired"}
            and not has_results(job)
            and _usage_allows_terminal_release(facts.aggregate_usage)
        ):
            job["terminalRelease"] = _terminal_release_record(job, status_pin)
        else:
            job.pop("terminalRelease", None)
        job["polledAt"] = polled_at
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


@dataclass(frozen=True, slots=True)
class VerifiedStatusEvidence:
    """Job facts reproduced from the ordered retained status responses."""

    aggregate_usage: NormalizedUsage
    completed_at: str | None
    error_file_id: str | None
    output_file_id: str | None
    provider_status: str | None
    request_counts: Mapping[str, Any] | None
    state: str | None

    @property
    def has_results(self) -> bool:
        return bool(self.output_file_id or self.error_file_id)


def _verified_status_evidence(
    run_root: Path,
    job: Mapping[str, Any],
    family: ValidatorFamily,
) -> VerifiedStatusEvidence:
    """Reopen ordered status bytes and reproduce every authoritative job fact."""

    raw_artifacts = job.get("statusArtifacts") or ()
    if not isinstance(raw_artifacts, Sequence) or isinstance(raw_artifacts, (str, bytes)):
        raise BatchError(f"job {job.get('jobId')} status artifacts are invalid")
    provider = provider_for(family)
    job_id = str(job.get("jobId") or "")
    latest_pin: Mapping[str, Any] | None = None
    latest_facts: ProviderStatusFacts | None = None
    request_counts: Mapping[str, Any] | None = None
    output_file_id: str | None = None
    error_file_id: str | None = None
    completed_at: str | None = None
    completed_pin: Mapping[str, Any] | None = None
    for expected_ordinal, raw_pin in enumerate(raw_artifacts, start=1):
        if not isinstance(raw_pin, Mapping):
            raise BatchError(f"job {job_id} has an invalid status artifact pin")
        ordinal = raw_pin.get("pollOrdinal")
        response_status = raw_pin.get("responseStatus")
        observed_at = raw_pin.get("observedAt")
        if (
            raw_pin.get("role") != "status"
            or raw_pin.get("endpoint") != provider.job_url(job_id)
            or isinstance(ordinal, bool)
            or ordinal != expected_ordinal
            or isinstance(response_status, bool)
            or not isinstance(response_status, int)
            or not 200 <= response_status < 300
            or not isinstance(observed_at, str)
            or not observed_at
            or observed_at != observed_at.strip()
        ):
            raise BatchError(f"job {job_id} status artifact identity is invalid")
        payload = _read_pinned_provider_bytes(
            run_root,
            raw_pin,
            media_type="application/json",
        )
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BatchError(f"job {job_id} status artifact is not UTF-8 JSON") from error
        if not isinstance(parsed, Mapping):
            raise BatchError(f"job {job_id} status artifact is not an object")
        echoed_job_id = str(parsed.get("id") or parsed.get("name") or "")
        if echoed_job_id and echoed_job_id != job_id:
            raise BatchError(f"job {job_id} status artifact names another provider job")
        facts = _provider_status_facts(parsed, family)
        latest_pin = raw_pin
        latest_facts = facts
        # Polling replaces request counts on every response.  An omitted
        # field is therefore authoritative empty evidence, rather than an
        # opening through which a sidecar can invent counts.
        request_counts = dict(facts.request_counts or {})
        if facts.output_file_field:
            output_file_id = facts.output_file_id
        if facts.error_file_field:
            error_file_id = facts.error_file_id
        if facts.completed_at is not None:
            completed_at = facts.completed_at
            completed_pin = raw_pin

    if latest_facts is not None:
        if job.get("providerStatus") != latest_facts.provider_status:
            raise BatchError(f"job {job_id} provider status differs from retained status")
        if job.get("state") != latest_facts.state:
            raise BatchError(f"job {job_id} state differs from retained status")
        if job.get("requestCounts") != request_counts:
            raise BatchError(f"job {job_id} request counts differ from retained status")
        if latest_pin is not None and job.get("polledAt") != latest_pin.get("observedAt"):
            raise BatchError(f"job {job_id} poll time differs from retained status")
    if job.get("outputFileId") != output_file_id:
        raise BatchError(f"job {job_id} output file identity differs from retained status")
    if job.get("errorFileId") != error_file_id:
        raise BatchError(f"job {job_id} error file identity differs from retained status")
    completed_source = job.get("completedAtSource")
    if completed_at is not None:
        expected_source = {
            "kind": "providerStatus",
            "statusArtifactDigest": completed_pin.get("fileDigest") if completed_pin else None,
            "statusArtifactFile": completed_pin.get("file") if completed_pin else None,
            "statusPollOrdinal": completed_pin.get("pollOrdinal") if completed_pin else None,
        }
        if job.get("completedAt") != completed_at:
            raise BatchError(f"job {job_id} completion time differs from retained status")
        if completed_source != expected_source:
            raise BatchError(f"job {job_id} completion source differs from retained status")
    elif job.get("completedAt") is None:
        if completed_source is not None:
            raise BatchError(f"job {job_id} has a completion source without a completion time")
    elif completed_source != {"kind": "collectionCheckpoint"} or not (
        (output_file_id or error_file_id) and job.get("resultArtifacts")
    ):
        raise BatchError(f"job {job_id} completion time has no retained source")

    raw_aggregate = job.get("aggregateUsage")
    latest_usage = (
        latest_facts.aggregate_usage
        if latest_facts is not None
        else NormalizedUsage(None, None, None, {}, "missing")
    )
    if not latest_usage.raw:
        if raw_aggregate is not None:
            raise BatchError(f"job {job_id} aggregate usage is stale relative to its latest status")
        aggregate_usage = NormalizedUsage(None, None, None, {}, "missing")
    else:
        if not isinstance(raw_aggregate, Mapping):
            raise BatchError(f"job {job_id} latest status usage is not linked")
        ordinal = raw_aggregate.get("statusPollOrdinal")
        if (
            isinstance(ordinal, bool)
            or ordinal != len(raw_artifacts)
            or latest_pin is None
            or raw_aggregate.get("statusArtifactDigest") != latest_pin.get("fileDigest")
            or raw_aggregate.get("statusArtifactFile") != latest_pin.get("file")
        ):
            raise BatchError(f"job {job_id} aggregate usage does not name its latest status artifact")
        stored = raw_aggregate.get("usage")
        if not isinstance(stored, Mapping) or dict(stored) != latest_usage.record():
            raise BatchError(f"job {job_id} aggregate usage differs from its status artifact")
        aggregate_usage = latest_usage
    return VerifiedStatusEvidence(
        aggregate_usage=aggregate_usage,
        completed_at=completed_at,
        error_file_id=error_file_id,
        output_file_id=output_file_id,
        provider_status=(latest_facts.provider_status if latest_facts is not None else None),
        request_counts=request_counts,
        state=(latest_facts.state if latest_facts is not None else None),
    )


def _usage_allows_terminal_release(usage: NormalizedUsage) -> bool:
    if not usage.raw:
        return True
    return bool(
        usage.exact
        and usage.input_tokens == 0
        and usage.output_tokens == 0
    )


def _terminal_release_record(
    job: Mapping[str, Any],
    status_pin: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "kind": "providerTerminalWithoutResults",
        "providerStatus": job.get("providerStatus"),
        "state": job.get("state"),
        "statusArtifactDigest": status_pin.get("fileDigest"),
        "statusArtifactFile": status_pin.get("file"),
        "statusPollOrdinal": status_pin.get("pollOrdinal"),
    }


def _verify_terminal_releases(
    sidecar_path: Path,
    sidecar: Mapping[str, Any],
    families: Mapping[str, ValidatorFamily],
) -> None:
    """Reopen every proof that allows a created attempt to free its reserve."""

    for raw_job in sidecar.get("jobs", ()):
        if not isinstance(raw_job, Mapping) or raw_job.get("terminalRelease") is None:
            continue
        family = families.get(str(raw_job.get("family") or ""))
        if family is None:
            raise BatchError("provider terminal release names an unknown family")
        status = _verified_status_evidence(sidecar_path.parent, raw_job, family)
        artifacts = raw_job.get("statusArtifacts")
        latest = (
            artifacts[-1]
            if isinstance(artifacts, Sequence)
            and not isinstance(artifacts, (str, bytes))
            and artifacts
            and isinstance(artifacts[-1], Mapping)
            else None
        )
        if (
            latest is None
            or status.state not in {"failed", "cancelled", "expired"}
            or status.has_results
            or not _usage_allows_terminal_release(status.aggregate_usage)
            or raw_job.get("terminalRelease")
            != _terminal_release_record(raw_job, latest)
        ):
            raise BatchError(
                f"job {raw_job.get('jobId')} terminal release does not reproduce from retained status"
            )


def _result_download_endpoint(provider: BatchProvider, file_id: str) -> str:
    if isinstance(provider, GeminiBatchProvider):
        return provider.download_url(file_id)
    if isinstance(provider, OpenAIBatchProvider):
        return f"{provider.files_url}/{file_id}/content"
    raise BatchError("provider batch result has no supported download endpoint")


def _verified_result_artifact_roles(
    job: Mapping[str, Any],
    artifacts: object,
    *,
    provider: BatchProvider,
    status_evidence: VerifiedStatusEvidence,
) -> set[str]:
    """Verify result pins against file identities recovered from raw status."""

    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        raise BatchError(f"job {job.get('jobId')} result artifacts are invalid")
    roles: set[str] = set()
    expected_ids = {
        "error": status_evidence.error_file_id,
        "output": status_evidence.output_file_id,
    }
    for pin in artifacts:
        if not isinstance(pin, Mapping):
            raise BatchError(f"job {job.get('jobId')} has an invalid result artifact pin")
        role = str(pin.get("role") or "")
        expected_file_id = expected_ids.get(role)
        if (
            role in roles
            or not expected_file_id
            or pin.get("providerFileId") != expected_file_id
            or pin.get("endpoint")
            != _result_download_endpoint(provider, expected_file_id)
        ):
            raise BatchError(f"job {job.get('jobId')} result artifact identity is invalid")
        roles.add(role)
    return roles


def evaluate_retained_job_results(
    job: Mapping[str, Any],
    *,
    family: ValidatorFamily,
    rows_by_id: Mapping[str, CandidateRow],
    result_lines: Sequence[ResultLineEvidence],
    aggregate_usage: NormalizedUsage,
    work_kind: WorkKind,
) -> dict[str, Any]:
    """Derive valid candidate receipts and complete line accounting from raw bytes."""

    tracker = qual.SpendTracker(batch_family(family))
    plans_by_custom: dict[str, list[Mapping[str, Any]]] = {}
    for item in job.get("requests", ()):
        if isinstance(item, Mapping):
            plans_by_custom.setdefault(str(item.get("customId") or ""), []).append(item)

    lines_by_custom: dict[str, list[ResultLineEvidence]] = {}
    line_issues: list[dict[str, Any]] = []
    outcomes: Counter[str] = Counter()
    response_usage_lines = 0
    missing_usage_lines = 0
    for line in result_lines:
        if line.parsed is None:
            line_issues.append(
                {
                    "artifactDigest": line.artifact["fileDigest"],
                    "kind": "malformedResultLine",
                    "line": line.line_ordinal,
                    "lineDigest": line.line_digest,
                }
            )
            outcomes["malformed_result_line"] += 1
            continue
        token = str(line.parsed.get("custom_id") or "")
        result_id = str(line.parsed.get("id") or "")
        if not result_id:
            line_issues.append(
                {
                    "artifactDigest": line.artifact["fileDigest"],
                    "customId": token,
                    "kind": "missingProviderResultId",
                    "line": line.line_ordinal,
                    "lineDigest": line.line_digest,
                }
            )
            outcomes["missing_provider_result_id"] += 1
            continue
        if not token or token not in plans_by_custom:
            line_issues.append(
                {
                    "artifactDigest": line.artifact["fileDigest"],
                    "customId": token,
                    "kind": "unmatchedCustomId",
                    "line": line.line_ordinal,
                    "lineDigest": line.line_digest,
                }
            )
            outcomes["unmatched_custom_id"] += 1
            continue
        lines_by_custom.setdefault(token, []).append(line)

    candidate_receipts: list[dict[str, Any]] = []
    group_issues: list[dict[str, Any]] = []
    for token, planned_items in plans_by_custom.items():
        matched_lines = lines_by_custom.get(token, ())
        if len(matched_lines) > 1:
            for line in matched_lines:
                line_issues.append(
                    {
                        "artifactDigest": line.artifact["fileDigest"],
                        "customId": token,
                        "kind": "duplicateCustomId",
                        "line": line.line_ordinal,
                        "lineDigest": line.line_digest,
                    }
                )
            outcomes["duplicate_custom_id"] += len(matched_lines)
            continue
        if not matched_lines:
            continue
        line = matched_lines[0]
        assert line.parsed is not None
        response = line.parsed.get("response")
        if isinstance(response, Mapping) and isinstance(response.get("body"), Mapping):
            response_usage_lines += 1
            if not normalize_provider_usage(response["body"], family).exact:
                missing_usage_lines += 1
        planned_rows: list[tuple[CandidateRow, Mapping[str, Any]]] = []
        for planned in planned_items:
            candidate_id = str(planned.get("candidateId") or "")
            row = rows_by_id.get(candidate_id)
            if row is None:
                line_issues.append(
                    {
                        "candidateId": candidate_id,
                        "customId": token,
                        "kind": "unknownCandidate",
                        "line": line.line_ordinal,
                        "lineDigest": line.line_digest,
                    }
                )
                outcomes["unknown_candidate"] += 1
                continue
            planned_rows.append((row, planned))
        if len(planned_rows) != len(planned_items):
            continue
        identity = line.receipt_identity(job)
        grouped = str(planned_rows[0][1].get("requestKind") or "") == "grouped"
        if grouped:
            collected = _group_receipts_from_result(
                family=family,
                model_id=str(job["modelId"]),
                protocol=str(job["protocol"]),
                planned_rows=planned_rows,
                result=line.parsed,
                raw_line=line.raw_text,
                started_at=str(job.get("submittedAt") or ""),
                finished_at=str(job.get("completedAt") or job.get("collectedAt") or ""),
                tracker=tracker,
                work_kind=work_kind,
                result_identity=identity,
            )
            if collected.get("groupOutcome") != "completed":
                issue = {
                    key: collected[key]
                    for key in (
                        "duplicateTaskIds",
                        "groupOutcome",
                        "groupResponseSha256",
                        "invalidAnswerCount",
                        "invalidTaskIds",
                        "missingTaskIds",
                        "unexpectedTaskIds",
                    )
                    if collected.get(key)
                }
                issue.update(
                    {
                        "artifactDigest": line.artifact["fileDigest"],
                        "customId": token,
                        "groupId": planned_rows[0][1].get("groupId"),
                        "line": line.line_ordinal,
                        "lineDigest": line.line_digest,
                    }
                )
                group_issues.append(issue)
                outcomes[str(collected.get("groupOutcome") or "unusable_group_answer")] += 1
            receipts = list(collected["receipts"])
        else:
            row, planned = planned_rows[0]
            request = BatchRequest(
                candidate_id=row.candidate_id,
                custom_id=token,
                task_id=str(planned["taskId"]),
                request_sha256=str(planned["requestSha256"]),
                body={},
            )
            receipts = [
                receipt_from_result(
                    family=family,
                    model_id=str(job["modelId"]),
                    protocol=str(job["protocol"]),
                    row=row,
                    request=request,
                    result=line.parsed,
                    raw_line=line.raw_text,
                    started_at=str(job.get("submittedAt") or ""),
                    finished_at=str(job.get("completedAt") or job.get("collectedAt") or ""),
                    tracker=tracker,
                    result_identity=identity,
                    work_kind=work_kind,
                )
            ]
        for receipt in receipts:
            outcome = str(receipt.get("outcome") or "unusable_answer")
            if outcome != "completed" or not echo_check_passed(receipt):
                line_issues.append(
                    {
                        "candidateId": receipt.get("candidate_id"),
                        "customId": token,
                        "kind": "invalidCandidateReading",
                        "line": line.line_ordinal,
                        "lineDigest": line.line_digest,
                        "outcome": outcome,
                    }
                )
                outcomes["echo_mismatch" if outcome == "completed" else outcome] += 1
                continue
            candidate_receipts.append(receipt)
            outcomes["completed"] += 1

    missing_custom_ids = sorted(set(plans_by_custom) - set(lines_by_custom))
    aggregate = aggregate_usage
    line_summary = tracker.summary()
    line_complete = (
        not missing_custom_ids
        and len(result_lines) == len(plans_by_custom)
        and set(lines_by_custom) == set(plans_by_custom)
        and all(len(lines) == 1 for lines in lines_by_custom.values())
        and missing_usage_lines == 0
        and response_usage_lines == len(result_lines)
    )
    if aggregate.exact and line_complete:
        assert aggregate.input_tokens is not None and aggregate.output_tokens is not None
        if (
            int(line_summary["input_tokens"]) != aggregate.input_tokens
            or int(line_summary["output_tokens"]) != aggregate.output_tokens
        ):
            raise BatchError(f"job {job.get('jobId')} aggregate usage differs from its result lines")
    if aggregate.exact:
        exact_usage = aggregate
        usage_status = "aggregateReported"
    elif line_complete:
        exact_usage = NormalizedUsage(
            int(line_summary["input_tokens"]),
            int(line_summary["output_tokens"]),
            int(line_summary["input_tokens"]) + int(line_summary["output_tokens"]),
            {},
            "lineReported",
        )
        usage_status = "lineReported"
    else:
        exact_usage = NormalizedUsage(None, None, None, {}, "missing")
        usage_status = "missing"
    exact_cost = (
        round(
            tracker.cost(
                int(exact_usage.input_tokens),
                int(exact_usage.output_tokens),
            ),
            6,
        )
        if exact_usage.exact
        else None
    )
    committed_cost = (
        float(exact_cost)
        if exact_cost is not None
        else float(job.get("projectedCostUsd") or 0.0)
    )
    return {
        "committedCostUsd": round(committed_cost, 6),
        "exactCostUsd": exact_cost,
        "groupIssues": group_issues,
        "lineIssues": line_issues,
        "missingCustomIds": missing_custom_ids,
        "outcomes": dict(sorted(outcomes.items())),
        "receipts": candidate_receipts,
        "resultLines": len(result_lines),
        "usage": exact_usage.record(),
        "usageStatus": usage_status,
    }


def recompute_sidecar_spend(sidecar: Mapping[str, Any]) -> tuple[list[dict[str, Any]], float]:
    """Rebuild family spend from verified job collections, including unknown usage."""

    spend_by_family: dict[str, dict[str, Any]] = {}
    for job in sidecar.get("jobs", ()):
        collection = job.get("collection") if isinstance(job, Mapping) else None
        if not isinstance(collection, Mapping):
            continue
        family_name = str(job.get("family"))
        item = spend_by_family.setdefault(
            family_name,
            {
                "assumed_cost_usd": 0.0,
                "committed_cost_usd": 0.0,
                "family": family_name,
                "input_tokens": 0,
                "output_tokens": 0,
                "usage_status": "reported",
            },
        )
        item["committed_cost_usd"] += float(collection.get("committedCostUsd") or 0.0)
        if collection.get("exactCostUsd") is None:
            item["usage_status"] = "missing"
            item["assumed_cost_usd"] += float(collection.get("committedCostUsd") or 0.0)
            continue
        item["assumed_cost_usd"] += float(collection["exactCostUsd"])
        usage = collection.get("usage") if isinstance(collection.get("usage"), Mapping) else {}
        input_tokens = _token_count(usage.get("input_tokens"))
        output_tokens = _token_count(usage.get("output_tokens"))
        if input_tokens is None or output_tokens is None:
            raise BatchError("exact collection cost has incomplete normalized usage")
        item["input_tokens"] += input_tokens
        item["output_tokens"] += output_tokens
    spend: list[dict[str, Any]] = []
    for family_name in sorted(spend_by_family):
        item = spend_by_family[family_name]
        item["assumed_cost_usd"] = round(float(item["assumed_cost_usd"]), 6)
        item["committed_cost_usd"] = round(float(item["committed_cost_usd"]), 6)
        spend.append(item)
    total = round(sum(float(item["committed_cost_usd"]) for item in spend), 6)
    return spend, total


def collect(
    *,
    transport: BatchHttpTransport,
    receipts_path: Path,
    sidecar_path: Path,
    families: Mapping[str, ValidatorFamily],
    keys: Mapping[str, str],
    rows: Sequence[CandidateRow],
    protocol: str,
    work_kind: WorkKind = "validation",
    mutation_guard: Callable[[], None] | None = None,
    lock_timeout_seconds: float = DEFAULT_SUBMIT_LOCK_TIMEOUT_SECONDS,
    now: Callable[[], str] = qual._utcnow,
) -> dict[str, Any]:
    """Retain finished jobs and append only deterministic valid readings.

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

    with _run_submit_lock(
        sidecar_path,
        (),
        timeout_seconds=lock_timeout_seconds,
    ):
        if mutation_guard is not None:
            mutation_guard()
        return _collect_locked(
            transport=transport,
            receipts_path=receipts_path,
            sidecar_path=sidecar_path,
            families=families,
            keys=keys,
            rows=rows,
            protocol=protocol,
            work_kind=work_kind,
            now=now,
        )


def _collect_locked(
    *,
    transport: BatchHttpTransport,
    receipts_path: Path,
    sidecar_path: Path,
    families: Mapping[str, ValidatorFamily],
    keys: Mapping[str, str],
    rows: Sequence[CandidateRow],
    protocol: str,
    work_kind: WorkKind,
    now: Callable[[], str],
) -> dict[str, Any]:
    """Collect while the caller owns the run-wide sidecar mutation lock."""

    protocol = _require_work_protocol(protocol, work_kind)
    sidecar = read_sidecar(sidecar_path)
    known_families = {**qual.VALIDATOR_FAMILIES, **families}
    _verify_attempt_journal(sidecar_path, sidecar)
    _verify_terminal_releases(sidecar_path, sidecar, known_families)
    for job in sidecar.get("jobs", ()):
        recorded_work_kind = str(job.get("workKind") or "validation")
        if recorded_work_kind != work_kind:
            raise BatchError(
                f"job {job.get('jobId')} carries {recorded_work_kind!r} work, not {work_kind!r} work"
            )
        asked = str(job.get("protocol") or "")
        if asked != protocol:
            raise BatchError(
                f"job {job.get('jobId')} ({job.get('family')}) asked protocol {asked!r} but this run is "
                f"{protocol!r}; move its sidecar aside rather than collecting answers to another question"
            )
    existing_receipts: dict[tuple[str, str], Mapping[str, Any]] = {}
    if receipts_path.exists():
        for line in receipts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            receipt = json.loads(line)
            key = (str(receipt["candidate_id"]), str(receipt["family"]))
            if key in existing_receipts:
                raise BatchError("receipt log already repeats a candidate/family")
            existing_receipts[key] = receipt
    rows_by_id = {row.candidate_id: row for row in rows}
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
            status_evidence = _verified_status_evidence(
                sidecar_path.parent,
                job,
                family,
            )
            if not status_evidence.has_results:
                summaries.append({"family": family.name, "jobId": job["jobId"], "skipped": str(job.get("state"))})
                continue
            if job.get("attemptState") != "submitted":
                raise BatchError(
                    f"job {job.get('jobId')} has an untrusted create response and cannot be collected"
                )
            raw_artifacts = job.get("resultArtifacts") or ()
            retained_roles = _verified_result_artifact_roles(
                job,
                raw_artifacts,
                provider=provider,
                status_evidence=status_evidence,
            )
            artifacts = list(raw_artifacts)
            for role, file_id in (
                ("output", status_evidence.output_file_id),
                ("error", status_evidence.error_file_id),
            ):
                if not file_id or role in retained_roles:
                    continue
                payload, endpoint = provider.download_file(
                    transport,
                    keys[family.name],
                    str(file_id),
                )
                artifact = retain_result_artifact(
                    sidecar_path,
                    payload,
                    role=role,
                    provider_file_id=str(file_id),
                    endpoint=endpoint,
                )
                artifacts.append(artifact)
                job["resultArtifacts"] = artifacts
                sidecar["updatedAt"] = now()
                # The pin is durable before parsing or appending a receipt.
                write_sidecar(sidecar_path, sidecar)
            collection_time = now()
            if not job.get("completedAt"):
                job["completedAt"] = collection_time
                job["completedAtSource"] = {"kind": "collectionCheckpoint"}
                sidecar["updatedAt"] = collection_time
                # Receipt identity includes ``finished_at``.  Checkpoint a
                # synthesized value before the first append so a crash retry
                # derives byte-identical receipts.
                write_sidecar(sidecar_path, sidecar)
            result_lines = result_lines_from_artifacts(sidecar_path.parent, artifacts)
            evaluation = evaluate_retained_job_results(
                job,
                aggregate_usage=status_evidence.aggregate_usage,
                family=family,
                rows_by_id=rows_by_id,
                result_lines=result_lines,
                work_kind=work_kind,
            )
            appended = 0
            for receipt in evaluation["receipts"]:
                candidate_id = str(receipt["candidate_id"])
                key = (candidate_id, family.name)
                existing = existing_receipts.get(key)
                if existing is not None:
                    if dict(existing) != receipt:
                        raise BatchError(
                            f"candidate {candidate_id} / {family.name} resolves to two different batch results"
                        )
                    continue
                handle.write(canonical_json(receipt) + "\n")
                handle.flush()
                existing_receipts[key] = receipt
                written.append(candidate_id)
                appended += 1
            job["collectedAt"] = collection_time
            job["collection"] = {
                "assumedCostUsd": evaluation["exactCostUsd"],
                "committedCostUsd": evaluation["committedCostUsd"],
                "downloadEndpoints": [str(pin["endpoint"]) for pin in artifacts],
                "exactCostUsd": evaluation["exactCostUsd"],
                "groupIssues": evaluation["groupIssues"],
                "lineIssues": evaluation["lineIssues"],
                "missingCustomIds": evaluation["missingCustomIds"],
                "outcomes": evaluation["outcomes"],
                "receiptCount": len(evaluation["receipts"]),
                "receiptsAppended": appended,
                "resultLines": evaluation["resultLines"],
                "usage": evaluation["usage"],
                "usageStatus": evaluation["usageStatus"],
            }
            summaries.append(
                {
                    "attemptId": job["attemptId"],
                    "family": family.name,
                    "jobId": job["jobId"],
                    "groupIssues": len(evaluation["groupIssues"]),
                    "lineIssues": len(evaluation["lineIssues"]),
                    "missing": len(evaluation["missingCustomIds"]),
                    "outcomes": evaluation["outcomes"],
                    "receiptsAppended": appended,
                    "shardId": job["shardId"],
                    "usageStatus": evaluation["usageStatus"],
                }
            )

    spend, total_committed = recompute_sidecar_spend(sidecar)
    sidecar["spendByFamily"] = spend
    sidecar["totalBatchAssumedCostUsd"] = total_committed
    sidecar["updatedAt"] = now()
    write_sidecar(sidecar_path, sidecar)
    return {
        "jobs": summaries,
        "receiptsAppended": len(written),
        "spendByFamily": spend,
        "totalBatchAssumedCostUsd": sidecar["totalBatchAssumedCostUsd"],
    }


def verify_provider_batch_evidence(
    *,
    sidecar_path: Path,
    families: Mapping[str, ValidatorFamily],
    rows: Sequence[CandidateRow],
    receipts: Sequence[Mapping[str, Any]],
    work_kind: WorkKind,
) -> dict[str, Any]:
    """Recompute requests, retained responses, readings, usage, and accounting."""

    sidecar = read_sidecar(sidecar_path)
    known_families = {**qual.VALIDATOR_FAMILIES, **families}
    _verify_attempt_journal(
        sidecar_path,
        sidecar,
        allow_legacy_read_only=True,
    )
    _verify_terminal_releases(sidecar_path, sidecar, known_families)
    summary = verify_sidecar_request_lineage(
        sidecar,
        families=families,
        rows=rows,
        work_kind=work_kind,
    )
    verify_receipt_request_lineage(receipts, sidecar=sidecar, work_kind=work_kind)
    rows_by_id = {row.candidate_id: row for row in rows}
    expected_receipts: dict[tuple[str, str], Mapping[str, Any]] = {}
    collected_jobs = 0
    issue_lines = 0
    for job in sidecar.get("jobs", ()):
        if not isinstance(job, Mapping) or str(job.get("workKind")) != work_kind:
            continue
        family = families.get(str(job.get("family") or ""))
        if family is None:
            raise BatchError(f"job {job.get('jobId')} names an unknown family")
        status_evidence = _verified_status_evidence(sidecar_path.parent, job, family)
        provider = provider_for(family)
        artifacts = job.get("resultArtifacts") or ()
        roles = _verified_result_artifact_roles(
            job,
            artifacts,
            provider=provider,
            status_evidence=status_evidence,
        )
        expected_roles = {
            role
            for role, file_id in (
                ("output", status_evidence.output_file_id),
                ("error", status_evidence.error_file_id),
            )
            if file_id
        }
        if job.get("collectedAt") and roles != expected_roles:
            raise BatchError(f"job {job.get('jobId')} did not retain every provider result file")
        if status_evidence.has_results and job.get("collectedAt") and not artifacts:
            raise BatchError(f"job {job.get('jobId')} discarded its provider result bytes")
        if not job.get("collectedAt"):
            continue
        collected_jobs += 1
        result_lines = result_lines_from_artifacts(sidecar_path.parent, artifacts)
        evaluation = evaluate_retained_job_results(
            job,
            aggregate_usage=status_evidence.aggregate_usage,
            family=family,
            rows_by_id=rows_by_id,
            result_lines=result_lines,
            work_kind=work_kind,
        )
        collection = job.get("collection")
        if not isinstance(collection, Mapping):
            raise BatchError(f"job {job.get('jobId')} has no collection accounting")
        for key in (
            "committedCostUsd",
            "exactCostUsd",
            "groupIssues",
            "lineIssues",
            "missingCustomIds",
            "outcomes",
            "receiptCount",
            "resultLines",
            "usage",
            "usageStatus",
        ):
            expected_value = (
                len(evaluation["receipts"]) if key == "receiptCount" else evaluation[key]
            )
            if collection.get(key) != expected_value:
                raise BatchError(f"job {job.get('jobId')} collection {key} does not recompute")
        issue_lines += len(evaluation["lineIssues"]) + len(evaluation["groupIssues"])
        for receipt in evaluation["receipts"]:
            key = (str(receipt["candidate_id"]), str(receipt["family"]))
            prior = expected_receipts.get(key)
            if prior is not None and dict(prior) != receipt:
                raise BatchError(f"candidate {key[0]} / {key[1]} has two valid provider batch results")
            expected_receipts[key] = receipt

    actual_receipts = {
        (str(receipt.get("candidate_id") or ""), str(receipt.get("family") or "")): receipt
        for receipt in receipts
        if receipt.get("batch_execution_mode") == "batch"
    }
    if len(actual_receipts) != sum(
        1 for receipt in receipts if receipt.get("batch_execution_mode") == "batch"
    ):
        raise BatchError("batch receipt log repeats a candidate/family")
    if set(actual_receipts) != set(expected_receipts):
        raise BatchError("batch receipt log does not equal the valid readings recomputed from raw results")
    for key, expected in expected_receipts.items():
        if dict(actual_receipts[key]) != expected:
            raise BatchError(f"batch receipt for {key[0]} / {key[1]} differs from raw result bytes")
    spend, total_committed = recompute_sidecar_spend(sidecar)
    if sidecar.get("spendByFamily") != spend:
        raise BatchError("provider batch family spend does not recompute from job collections")
    if sidecar.get("totalBatchAssumedCostUsd") != total_committed:
        raise BatchError("provider batch committed total does not recompute from job collections")
    return {
        **summary,
        "collectedJobs": collected_jobs,
        "committedCostUsd": total_committed,
        "issueLines": issue_lines,
        "verifiedReceipts": len(expected_receipts),
    }


def _pinned_run_file(run_path: Path, pin: Mapping[str, Any], *, label: str) -> Path:
    name = pin.get("file")
    if not isinstance(name, str) or Path(name).name != name:
        raise BatchError(f"{label} path is unsafe")
    path = run_path.parent / name
    if path.is_symlink() or not path.is_file():
        raise BatchError(f"{label} is missing or unsafe")
    payload = path.read_bytes()
    if "sha256:" + hashlib.sha256(payload).hexdigest() != pin.get("fileDigest"):
        raise BatchError(f"{label} differs from its pin")
    return path


def _canonical_receipt_rows(path: Path) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for ordinal, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, Mapping) or canonical_json(parsed) != line:
            raise BatchError(f"receipt log line {ordinal} is not canonical JSON")
        rows.append(parsed)
    return tuple(rows)


def _require_complete_production_batch_receipts(
    run: Mapping[str, Any],
    *,
    evidence_name: str,
    receipt_rows: Sequence[Mapping[str, Any]],
    verification: Mapping[str, Any],
) -> None:
    """Require every production receipt row to derive from retained Batch bytes."""

    if (
        run.get("coverageMode") == qual.PRODUCTION_COVERAGE_MODE
        and verification.get("verifiedReceipts") != len(receipt_rows)
    ):
        raise BatchError(
            f"production {evidence_name} receipts must all reproduce from retained raw batch results"
        )


def verify_run_provider_batch_evidence(
    run_path: Path,
    run: Mapping[str, Any],
    *,
    families: Mapping[str, ValidatorFamily] = qual.VALIDATOR_FAMILIES,
) -> dict[str, Any]:
    """Reopen every provider-batch pin named by a qualification run receipt."""

    raw_evidence = run.get("providerBatchEvidence")
    if raw_evidence is None:
        return {}
    if not isinstance(raw_evidence, Mapping):
        raise BatchError("qualification run provider batch evidence is invalid")
    catalog_pin = run.get("candidateCatalog")
    if not isinstance(catalog_pin, Mapping):
        raise BatchError("qualification run has no candidate catalog pin")
    catalog_path = _pinned_run_file(run_path, catalog_pin, label="candidate catalog")
    catalog_bytes = catalog_path.read_bytes()
    catalog = json.loads(catalog_bytes)
    if not isinstance(catalog, Mapping) or (canonical_json(catalog) + "\n").encode("utf-8") != catalog_bytes:
        raise BatchError("candidate catalog is not canonical JSON")
    summaries: dict[str, Any] = {}
    judging_receipts: tuple[Mapping[str, Any], ...] | None = None
    scoring_receipts: tuple[Mapping[str, Any], ...] | None = None
    sidecars: dict[str, Mapping[str, Any]] = {}
    combined_by_family: dict[str, float] = {}
    declared_family_caps: dict[str, float] = {}
    declared_total_cap: float | None = None
    declared_spend_authority: object = None
    authority_seen = False
    for name, raw_pin in raw_evidence.items():
        if not isinstance(raw_pin, Mapping):
            raise BatchError(f"provider batch evidence {name} is invalid")
        if name == "judging":
            work_kind: WorkKind = "validation"
            receipt_pin = run.get("receiptLog")
        elif name == "scoring":
            work_kind = "scoring"
            scoring = run.get("scoring")
            receipt_pin = scoring.get("receiptLog") if isinstance(scoring, Mapping) else None
        else:
            raise BatchError(f"provider batch evidence {name} has an unsupported work kind")
        if not isinstance(receipt_pin, Mapping):
            raise BatchError(f"provider batch evidence {name} has no receipt-log pin")
        sidecar_path = _pinned_run_file(run_path, raw_pin, label=f"{name} batch sidecar")
        sidecar = read_sidecar(sidecar_path)
        sidecars[str(name)] = sidecar
        sidecar_authority = sidecar.get("spendAuthority")
        if authority_seen and sidecar_authority != declared_spend_authority:
            raise BatchError("qualification run batch sidecars disagree on spend authority")
        declared_spend_authority = sidecar_authority
        authority_seen = True
        receipt_path = _pinned_run_file(run_path, receipt_pin, label=f"{name} receipt log")
        receipt_rows = _canonical_receipt_rows(receipt_path)
        summary = verify_provider_batch_evidence(
            sidecar_path=sidecar_path,
            families=families,
            rows=candidate_rows_from_catalog(catalog, work_kind=work_kind),
            receipts=receipt_rows,
            work_kind=work_kind,
        )
        _require_complete_production_batch_receipts(
            run,
            evidence_name=str(name),
            receipt_rows=receipt_rows,
            verification=summary,
        )
        if name == "judging":
            judging_receipts = receipt_rows
        else:
            scoring_receipts = receipt_rows
        if raw_pin.get("verification") != summary:
            raise BatchError(f"provider batch evidence {name} summary differs from recomputation")
        sidecar_total_cap = float(sidecar["totalSpendCapUsd"])
        if declared_total_cap is not None and declared_total_cap != sidecar_total_cap:
            raise BatchError("qualification run batch sidecars disagree on the total spend cap")
        declared_total_cap = sidecar_total_cap
        for family_name, value in sidecar["spendCapsByFamily"].items():
            cap = float(value)
            if family_name in declared_family_caps and declared_family_caps[family_name] != cap:
                raise BatchError(f"qualification run batch sidecars disagree on {family_name} spend cap")
            declared_family_caps[str(family_name)] = cap
        for item in sidecar["spendByFamily"]:
            family_name = str(item["family"])
            combined_by_family[family_name] = combined_by_family.get(family_name, 0.0) + float(
                item["committed_cost_usd"]
            )
        summaries[str(name)] = summary
    if run.get("spendAuthority") != declared_spend_authority:
        raise BatchError("qualification run spend authority differs from its batch sidecars")
    raw_priority = run.get("judgingPriority")
    if raw_priority is not None:
        try:
            priority = qual.validate_scorer_priority_provenance(raw_priority)
            scorer_family = families[str(priority["scorerFamily"])]
            scoring_run = run.get("scoring")
            scoring_evidence = raw_evidence.get("scoring")
            if (
                scoring_receipts is None
                or not isinstance(scoring_run, Mapping)
                or not isinstance(scoring_run.get("receiptLog"), Mapping)
                or not isinstance(scoring_evidence, Mapping)
            ):
                raise BatchError(
                    "qualification run judging priority has no scoring evidence"
                )
            reproduced_priority, ordered_ids = qual.scorer_priority_provenance(
                catalog,
                scoring_receipts,
                scorer_family=scorer_family,
                scorer_model_id=str(priority["scorerModelId"]),
                candidate_catalog_file_digest=str(catalog_pin["fileDigest"]),
                scoring_receipt_log_file_digest=str(
                    scoring_run["receiptLog"]["fileDigest"]
                ),
                scoring_sidecar_file_digest=str(
                    scoring_evidence["fileDigest"]
                ),
            )
        except (KeyError, qual.QualificationError) as error:
            raise BatchError(
                f"qualification run judging priority does not reproduce: {error}"
            ) from error
        judging_sidecar = sidecars.get("judging")
        if (
            reproduced_priority != priority
            or not isinstance(judging_sidecar, Mapping)
            or judging_sidecar.get("priorityProvenance") != priority
        ):
            raise BatchError(
                "qualification run judging priority differs from its scoring evidence or sidecar"
            )
        judge_families = {
            str(plan.get("family"))
            for plan in judging_sidecar.get("plannedShards", ())
            if isinstance(plan, Mapping)
            and plan.get("workKind") == "validation"
            and plan.get("maxRequestGroupSize") == MAX_REQUEST_GROUP_SIZE
        }
        for family_name in judge_families:
            plans = sorted(
                (
                    plan
                    for plan in judging_sidecar.get("plannedShards", ())
                    if isinstance(plan, Mapping)
                    and plan.get("family") == family_name
                    and plan.get("workKind") == "validation"
                    and plan.get("maxRequestGroupSize") == MAX_REQUEST_GROUP_SIZE
                ),
                key=lambda plan: int(plan.get("planOrder") or 0),
            )
            actual_order = tuple(
                str(candidate_id)
                for plan in plans
                for request in plan.get("providerRequests", ())
                if isinstance(request, Mapping)
                for candidate_id in request.get("candidateIds", ())
            )
            if actual_order != ordered_ids:
                raise BatchError(
                    f"qualification run {family_name} judging order differs from scorer priority"
                )
    if run.get("coverageMode") == qual.PRODUCTION_COVERAGE_MODE:
        if judging_receipts is None or scoring_receipts is None:
            raise BatchError(
                "production qualification requires verified judging and scoring receipt rows"
            )
        bundle_pin = run.get("bundle")
        accounting = run.get("candidateAccounting")
        if not isinstance(bundle_pin, Mapping):
            raise BatchError("production qualification has no Crosswalk bundle pin")
        if not isinstance(accounting, Sequence) or isinstance(
            accounting,
            (str, bytes),
        ):
            raise BatchError("production qualification has no candidate accounting")
        bundle_path = _pinned_run_file(
            run_path,
            bundle_pin,
            label="Crosswalk bundle",
        )
        try:
            bundle = CrosswalkBundle.open(
                bundle_path,
                expected_file_digest=str(bundle_pin.get("fileDigest") or ""),
                expected_bundle_digest=str(bundle_pin.get("bundleDigest") or ""),
            )
            if bundle.identifier != bundle_pin.get("id"):
                raise BatchError("production Crosswalk bundle identity differs")
            qual.verify_production_qualification_reproduction(
                catalog=catalog,
                judge_receipts=judging_receipts,
                scorer_receipts=scoring_receipts,
                bundle=bundle,
                candidate_accounting=accounting,
            )
        except (OSError, qual.QualificationError, ValueError) as error:
            if isinstance(error, BatchError):
                raise
            raise BatchError(
                f"production qualification does not reproduce from provider evidence: {error}"
            ) from error
    combined_total = round(sum(combined_by_family.values()), 6)
    if declared_total_cap is not None and combined_total > declared_total_cap:
        raise BatchError("qualification run provider batch spend exceeds its total cap")
    for family_name, amount in combined_by_family.items():
        if family_name not in declared_family_caps or amount > declared_family_caps[family_name]:
            raise BatchError(f"qualification run provider batch spend exceeds the {family_name} cap")
    return summaries


def cancel(
    *,
    transport: BatchHttpTransport,
    sidecar_path: Path,
    families: Mapping[str, ValidatorFamily],
    keys: Mapping[str, str],
    mutation_guard: Callable[[], None] | None = None,
    lock_timeout_seconds: float = DEFAULT_SUBMIT_LOCK_TIMEOUT_SECONDS,
    now: Callable[[], str] = qual._utcnow,
) -> dict[str, Any]:
    """Cancel every non-terminal job and record the outcome in the sidecar.

    The cancellation is receipted whether or not it worked.  Acceptance starts
    an asynchronous ``cancelling`` state; only a later provider status response
    may move the job to a terminal state and release its candidates.
    """

    with _run_submit_lock(
        sidecar_path,
        (),
        timeout_seconds=lock_timeout_seconds,
    ):
        if mutation_guard is not None:
            mutation_guard()
        return _cancel_locked(
            transport=transport,
            sidecar_path=sidecar_path,
            families=families,
            keys=keys,
            now=now,
        )


def _cancel_locked(
    *,
    transport: BatchHttpTransport,
    sidecar_path: Path,
    families: Mapping[str, ValidatorFamily],
    keys: Mapping[str, str],
    now: Callable[[], str],
) -> dict[str, Any]:
    """Cancel while the caller owns the run-wide sidecar mutation lock."""

    sidecar = read_sidecar(sidecar_path)
    known_families = {**qual.VALIDATOR_FAMILIES, **families}
    _verify_attempt_journal(sidecar_path, sidecar)
    _verify_terminal_releases(sidecar_path, sidecar, known_families)
    outcomes: list[dict[str, Any]] = []
    for job in sidecar.get("jobs", ()):
        family = families[str(job["family"])]
        if not job.get("jobId"):
            outcomes.append(
                {
                    "attemptId": job.get("attemptId"),
                    "family": family.name,
                    "jobId": None,
                    "skipped": str(job.get("state")),
                }
            )
            continue
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
            job["state"] = "cancelling"
            job["providerStatus"] = "cancelling"
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
        "usageStatus": collection.get("usageStatus"),
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
