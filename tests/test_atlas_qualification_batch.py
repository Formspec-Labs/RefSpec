"""The batch road to a qualification receipt, proven offline for both vendors.

Every test here runs against a fake provider that speaks both wire shapes: the
OpenAI Batch API end to end, and Gemini's split arrangement — OpenAI-shaped job
control, native File API for the bytes.  Nothing is uploaded and nothing is
spent.

The property that matters is that a batch receipt is indistinguishable from a
serial one: the same field set, the same digests over the same request bytes,
the same deterministic checks read back by the same ``reading_from_receipt``.
So the central test asserts field-set equality against a receipt the serial
path actually produced, rather than against a list copied out of it.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas import qualification as qual
from refspec.atlas import qualification_batch as qbatch
from refspec.storage import canonical_json

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REFSPEC_ROOT / "tools" / "run_atlas_qualification.py"
_RUNNER_SPEC = importlib.util.spec_from_file_location("_refspec_atlas_qualification_runner", RUNNER_PATH)
assert _RUNNER_SPEC is not None and _RUNNER_SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(_RUNNER_SPEC)
_RUNNER_SPEC.loader.exec_module(RUNNER)

GENERATED_AT = "2026-08-03T12:00:00Z"
SOURCE_RELEASE = "urn:ref:test:alpha:reference-resource-release"
TARGET_RELEASE = "urn:ref:test:beta:reference-resource-release"

OPENAI_MODEL = "gpt-5.6-terra"
GEMINI_MODEL = "models/gemini-3.6-flash"


# ---------------------------------------------------------------------------
# fixtures: a small run directory
# ---------------------------------------------------------------------------


def _source(member: str, label: str, **kwargs: Any) -> qual.AtlasConcept:
    return qual.AtlasConcept(member=member, release=SOURCE_RELEASE, pref_label=label, **kwargs)


def _target(member: str, label: str, **kwargs: Any) -> qual.AtlasConcept:
    return qual.AtlasConcept(member=member, release=TARGET_RELEASE, pref_label=label, **kwargs)


def _pairs() -> tuple[qual.CandidatePair, ...]:
    sources = (
        _source("urn:ref:test:alpha:1", "Energy policy"),
        _source("urn:ref:test:alpha:2", "Water pollution"),
        _source("urn:ref:test:alpha:3", "Labor unions", alt_labels=("Trade unions",)),
        _source("urn:ref:test:alpha:4", "Accountants"),
        _source("urn:ref:test:alpha:5", "Milk marketing orders"),
    )
    targets = (
        _target("urn:ref:test:beta:1", "energy POLICY ", broader=("urn:ref:test:beta:9",)),
        _target("urn:ref:test:beta:2", "Water pollution control", broader=("urn:ref:test:beta:9",)),
        _target("urn:ref:test:beta:3", "Trade unions"),
        _target("urn:ref:test:beta:4", "Accountant"),
        _target("urn:ref:test:beta:5", "Volcanology"),
        _target("urn:ref:test:beta:6", "Air pollution control", broader=("urn:ref:test:beta:9",)),
        _target("urn:ref:test:beta:9", "Pollution control"),
    )
    return qual.generate_candidate_pairs(sources, targets)


def _candidate_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in _pairs():
        entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
        context = next(item for item in entry.artifacts if item.role == "inputContext")
        rows.append(
            {
                "candidateId": entry.candidate.identifier,
                "evidence": dict(pair.evidence),
                "generationClass": pair.generation_class,
                "inputDigest": context.content_digest,
                "source": RUNNER._concept_dict(pair.source),
                "target": RUNNER._concept_dict(pair.target),
            }
        )
    return rows


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    output = tmp_path / "run"
    output.mkdir()
    rows = _candidate_rows()
    (output / RUNNER.CANDIDATES).write_text(
        canonical_json(
            {
                "candidates": rows,
                "generatedAt": GENERATED_AT,
                "generationPolicy": qual.CANDIDATE_GENERATION_POLICY,
                "proposedRelation": qual.PROPOSED_RELATION,
                "sourceManifestDigest": "sha256:" + "0" * 64,
                "targetManifestDigest": "sha256:" + "1" * 64,
                "total": len(rows),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "env").write_text(
        "OPENAI_API_KEY=OPENAI-SECRET-VALUE\nGEMINI_API_KEY=GEMINI-SECRET-VALUE\n",
        encoding="utf-8",
    )
    return output


# ---------------------------------------------------------------------------
# the fake provider
# ---------------------------------------------------------------------------


class FakeProviders:
    """One transport that answers both vendors' batch wire shapes.

    Requests are recorded verbatim so a test can assert which endpoint a vendor
    was actually driven through — that is the whole point of the Gemini path,
    whose bytes never touch the OpenAI-compatible ``/files`` endpoint.
    """

    def __init__(
        self,
        *,
        verdict: str = "same_or_near_same",
        wrong_task_id_for: frozenset[str] = frozenset(),
        error_for: frozenset[str] = frozenset(),
        omit: frozenset[str] = frozenset(),
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.files: dict[str, bytes] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.upload_sessions: dict[str, str] = {}
        self.verdict = verdict
        self.wrong_task_id_for = wrong_task_id_for
        self.error_for = error_for
        self.omit = omit
        self._counter = 0

    # -- helpers ------------------------------------------------------------

    def _next(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter}"

    def urls(self) -> list[str]:
        return [call["url"] for call in self.calls]

    def complete_jobs(self) -> None:
        """Flip every submitted job to completed and materialize its output."""

        for job in self.jobs.values():
            if job["status"] == "completed":
                continue
            output_lines: list[str] = []
            error_lines: list[str] = []
            for line in self.files[job["input_file_id"]].decode("utf-8").splitlines():
                if not line.strip():
                    continue
                request = json.loads(line)
                token = str(request["custom_id"])
                if token in self.omit:
                    continue
                if token in self.error_for:
                    error_lines.append(canonical_json(self._error_line(token)))
                    continue
                output_lines.append(canonical_json(self._output_line(token, request["body"])))
            output_id = self._next("files/out") if job["vendor"] == "google" else self._next("file-out")
            self.files[output_id] = ("\n".join(output_lines) + "\n").encode("utf-8")
            job["output_file_id"] = output_id
            if error_lines:
                error_id = self._next("files/err") if job["vendor"] == "google" else self._next("file-err")
                self.files[error_id] = ("\n".join(error_lines) + "\n").encode("utf-8")
                job["error_file_id"] = error_id
            job["status"] = "completed"
            job["completed_at"] = 1785000000
            job["request_counts"] = {
                "completed": len(output_lines),
                "failed": len(error_lines),
                "total": len(output_lines) + len(error_lines),
            }

    def _output_line(self, token: str, body: Mapping[str, Any]) -> dict[str, Any]:
        payload = json.loads(body["messages"][1]["content"])
        task_id = "task-not-the-one-asked-about" if token in self.wrong_task_id_for else payload["taskId"]
        answer = {"reason": "the labels denote the same concept", "task_id": task_id, "verdict": self.verdict}
        return {
            "custom_id": token,
            "error": None,
            "id": f"batch_req_{token}",
            "response": {
                "body": {
                    "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                    "model": str(body["model"]),
                    "usage": {"completion_tokens": 120, "prompt_tokens": 500},
                },
                "request_id": f"req_{token}",
                "status_code": 200,
            },
        }

    def _error_line(self, token: str) -> dict[str, Any]:
        return {
            "custom_id": token,
            "error": {"code": "rate_limit_exceeded", "message": "the provider declined this request"},
            "id": f"batch_req_{token}",
            "response": None,
        }

    # -- transport ----------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.calls.append({"body": body, "headers": dict(headers), "method": method, "url": url})
        status, response_headers, payload = self._route(method, url, headers, body)
        return status, response_headers, payload

    def _route(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> tuple[int, dict[str, str], bytes]:
        if url.endswith("/models"):
            ids = [GEMINI_MODEL] if "googleapis" in url else [OPENAI_MODEL]
            return 200, {}, _json({"data": [{"id": model} for model in ids]})

        # -- Gemini native File API (resumable upload, native download) -----
        if url.endswith("/upload/v1beta/files"):
            session = self._next("https://generativelanguage.googleapis.com/upload/v1beta/session")
            self.upload_sessions[session] = self._next("files/in")
            return 200, {"X-Goog-Upload-URL": session}, b"{}"
        if url in self.upload_sessions:
            name = self.upload_sessions[url]
            self.files[name] = body or b""
            return 200, {}, _json({"file": {"name": name, "uri": f"https://example.invalid/{name}"}})
        if "/download/v1beta/" in url:
            name = url.split("/download/v1beta/", 1)[1].split(":download", 1)[0]
            if name not in self.files:
                return 404, {}, b"{}"
            return 200, {}, self.files[name]

        # -- OpenAI files ---------------------------------------------------
        if url.endswith("/v1/files") and method == "POST":
            file_id = self._next("file-in")
            self.files[file_id] = _multipart_file(body or b"")
            return 200, {}, _json({"id": file_id, "object": "file", "purpose": "batch"})
        if url.endswith("/content"):
            file_id = url.rsplit("/", 2)[-2]
            if file_id not in self.files:
                return 404, {}, b"{}"
            return 200, {}, self.files[file_id]

        # -- batches, identical for both vendors ----------------------------
        if url.endswith("/batches") and method == "POST":
            request = json.loads((body or b"{}").decode("utf-8"))
            vendor = "google" if "googleapis" in url else "openai"
            job_id = self._next(f"batch_{vendor}")
            self.jobs[job_id] = {
                "completion_window": request["completion_window"],
                "endpoint": request["endpoint"],
                "error_file_id": None,
                "id": job_id,
                "input_file_id": request["input_file_id"],
                "output_file_id": None,
                "request_counts": {"completed": 0, "failed": 0, "total": 0},
                "status": "validating",
                "vendor": vendor,
            }
            return 200, {}, _json(self.jobs[job_id])
        if "/batches/" in url and method == "GET":
            job_id = url.rsplit("/", 1)[-1]
            if job_id not in self.jobs:
                return 404, {}, b"{}"
            return 200, {}, _json(self.jobs[job_id])
        raise AssertionError(f"the fake provider was asked for an unrouted URL: {method} {url}")


def _json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _multipart_file(body: bytes) -> bytes:
    """Recover the file part of a multipart/form-data body."""

    marker = b'name="file"'
    start = body.index(marker)
    start = body.index(b"\r\n\r\n", start) + 4
    end = body.rindex(b"\r\n------refspec-batch-")
    return body[start:end]


def _run(monkeypatch: pytest.MonkeyPatch, server: FakeProviders, output: Path, *arguments: str) -> int:
    monkeypatch.setattr(qbatch, "default_transport", lambda: server)
    return RUNNER.main(["--output", str(output), *arguments, "--env", str(output / "env")])


def _receipts(output: Path) -> list[dict[str, Any]]:
    path = output / RUNNER.RECEIPTS
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sidecar(output: Path) -> dict[str, Any]:
    return json.loads((output / qbatch.SIDECAR).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# the request a batch line carries is the request the serial path would send
# ---------------------------------------------------------------------------


def test_a_batch_line_carries_the_serial_request_body_and_digest() -> None:
    pair = _pairs()[0]
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    row = qbatch.CandidateRow(entry.candidate.identifier, pair, context.content_digest)
    protocol = qbatch.resolved_protocol()

    request = qbatch.build_request(qual.OPENAI_FAMILY, OPENAI_MODEL, row, protocol=protocol)

    system_text, user_text = qual.model_input_texts(pair, **qbatch._protocol_kwargs(qual.model_input_texts, protocol))
    expected = qual._request_body(qual.OPENAI_FAMILY, OPENAI_MODEL, system_text, user_text)
    assert request.body == expected
    assert request.request_sha256 == qual._sha256_text(canonical_json(expected))
    assert request.task_id == qual.task_id(pair)

    line = json.loads(request.line())
    assert line["method"] == "POST"
    assert line["url"] == qbatch.BATCH_REQUEST_URL
    assert line["custom_id"] == request.custom_id
    assert len(line["custom_id"]) <= 64


def test_custom_ids_are_deterministic_and_family_scoped() -> None:
    first = qbatch.custom_id(qual.OPENAI_FAMILY, "urn:ref:candidate:one")
    assert first == qbatch.custom_id(qual.OPENAI_FAMILY, "urn:ref:candidate:one")
    assert first != qbatch.custom_id(qual.GEMINI_FAMILY, "urn:ref:candidate:one")


# ---------------------------------------------------------------------------
# a full round trip, per vendor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family_name", ["openai", "gemini"])
def test_a_round_trip_appends_receipts_the_bundle_stage_can_read(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    family_name: str,
) -> None:
    server = FakeProviders()
    assert _run(monkeypatch, server, run_dir, "batch-submit", "--families", family_name) == 0
    assert _receipts(run_dir) == []

    assert _run(monkeypatch, server, run_dir, "batch-status") == 0
    assert [job["state"] for job in _sidecar(run_dir)["jobs"]] == ["pending"]

    server.complete_jobs()
    assert _run(monkeypatch, server, run_dir, "batch-status") == 0
    assert [job["state"] for job in _sidecar(run_dir)["jobs"]] == ["succeeded"]

    assert _run(monkeypatch, server, run_dir, "batch-collect") == 0
    receipts = _receipts(run_dir)
    assert receipts
    assert {receipt["family"] for receipt in receipts} == {family_name}
    assert {receipt["outcome"] for receipt in receipts} == {"completed"}

    family = qual.VALIDATOR_FAMILIES[family_name]
    job = _sidecar(run_dir)["jobs"][0]
    # The provider's epoch completion time, carried as the ISO-Z the format wants.
    assert job["completedAt"] == "2026-07-25T17:20:00Z"
    for receipt in receipts:
        reading = qual.reading_from_receipt(receipt, family, job["modelId"])
        assert reading is not None
        assert reading.deterministic_checks_passed
        assert reading.endpoint_host == qual.endpoint_host(family.base_url)
        assert reading.completed_at == job["completedAt"]
        assert receipt["started_at"] == job["submittedAt"]


def test_the_bundle_stage_seals_batch_receipts_without_knowing_they_are_batched(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """The end the whole exercise is for: two machines, one sealed bundle.

    ``bundle`` is untouched by this workstream, so if it qualifies candidates
    off batch-collected receipts then the receipts really are the serial ones.
    """

    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai,gemini")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    assert RUNNER.main(["--output", str(run_dir), "bundle"]) == 0
    receipt = json.loads((run_dir / RUNNER.RUN_RECEIPT).read_text(encoding="utf-8"))
    assert receipt["callOutcomes"] == {"completed": len(_receipts(run_dir))}
    assert receipt["qualifiedCandidates"] == receipt["totalCandidates"]
    assert receipt["spend"]["totalBatchAssumedCostUsd"] > 0
    assert {item["family"] for item in receipt["models"]} == {"gemini", "openai"}
    assert (run_dir / RUNNER.BUNDLE).exists()


def test_a_batch_receipt_has_exactly_the_serial_receipt_fields(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")
    batched = _receipts(run_dir)[0]

    pair = next(pair for pair in _pairs() if pair.source.member == batched["source_member"])
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    serial = qual.validate_candidate(
        _SerialStub(qual.task_id(pair)),
        qual.OPENAI_FAMILY,
        "OPENAI-SECRET-VALUE",
        OPENAI_MODEL,
        pair=pair,
        candidate_id=entry.candidate.identifier,
        input_digest=context.content_digest,
        tracker=qual.SpendTracker(qual.OPENAI_FAMILY),
    )

    assert set(batched) == set(serial)
    assert batched["request_sha256"] == serial["request_sha256"]
    assert batched["request_url"] == serial["request_url"]
    assert batched["request_headers"] == serial["request_headers"]
    assert batched["usage"] == serial["usage"]
    # Half price for the same tokens: the one number a batch is allowed to move.
    assert batched["assumed_cost_usd"] == pytest.approx(serial["assumed_cost_usd"] * qbatch.BATCH_PRICE_FACTOR)


class _SerialStub:
    """A one-shot chat-completions transport shaped like the fake's output."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, bytes]:
        answer = {"reason": "the labels denote the same concept", "task_id": self.task_id, "verdict": "same_or_near_same"}
        return 200, _json(
            {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                "model": OPENAI_MODEL,
                "usage": {"completion_tokens": 120, "prompt_tokens": 500},
            }
        )


def test_gemini_uses_the_native_file_api_and_the_compatible_batches_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """The one place the two providers genuinely disagree."""

    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "gemini")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    urls = server.urls()
    assert any(url.endswith("/upload/v1beta/files") for url in urls)
    assert any("/download/v1beta/" in url and url.endswith(":download?alt=media") for url in urls)
    assert any(url == "https://generativelanguage.googleapis.com/v1beta/openai/batches" for url in urls)
    # The compatibility layer does not carry files; nothing may go through it.
    assert not any(url.endswith("/v1beta/openai/files") for url in urls)

    start = next(call for call in server.calls if call["url"].endswith("/upload/v1beta/files"))
    assert start["headers"]["X-Goog-Upload-Protocol"] == "resumable"
    assert start["headers"]["X-Goog-Upload-Command"] == "start"
    assert start["headers"]["x-goog-api-key"] == "GEMINI-SECRET-VALUE"
    finalize = next(call for call in server.calls if call["url"] in server.upload_sessions)
    assert finalize["headers"]["X-Goog-Upload-Command"] == "upload, finalize"

    sidecar = _sidecar(run_dir)
    job = sidecar["jobs"][0]
    assert job["inputUploadEndpoint"] == "https://generativelanguage.googleapis.com/upload/v1beta/files"
    assert job["createEndpoint"] == "https://generativelanguage.googleapis.com/v1beta/openai/batches"


def test_openai_uploads_through_the_files_endpoint_with_the_batch_purpose(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")

    upload = next(call for call in server.calls if call["url"] == "https://api.openai.com/v1/files")
    assert upload["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="purpose"' in upload["body"]
    assert b"batch" in upload["body"]

    create = next(call for call in server.calls if call["url"] == "https://api.openai.com/v1/batches")
    body = json.loads(create["body"].decode("utf-8"))
    assert body["completion_window"] == qbatch.COMPLETION_WINDOW == "24h"
    assert body["endpoint"] == "/v1/chat/completions"
    assert body["input_file_id"].startswith("file-in-")
    assert body["metadata"]["family"] == "openai"


def test_the_gemini_create_call_sends_only_the_fields_its_docs_claim(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """The compatibility layer documents three fields; it gets three fields."""

    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "gemini")
    create = next(
        call
        for call in server.calls
        if call["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/batches"
    )
    body = json.loads(create["body"].decode("utf-8"))
    assert set(body) == {"completion_window", "endpoint", "input_file_id"}
    assert body["input_file_id"].startswith("files/in-")


# ---------------------------------------------------------------------------
# the deterministic checks survive the detour
# ---------------------------------------------------------------------------


def test_an_answer_that_does_not_echo_the_task_id_fails_the_deterministic_check(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """A completed call, a usable verdict, and a check the bundle stage fails."""

    rows = _candidate_rows()
    liar = qbatch.custom_id(qual.OPENAI_FAMILY, rows[0]["candidateId"])
    server = FakeProviders(wrong_task_id_for=frozenset({liar}))
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    receipts = {receipt["candidate_id"]: receipt for receipt in _receipts(run_dir)}
    bad = receipts[rows[0]["candidateId"]]
    assert bad["outcome"] == "completed"
    assert bad["answer"]["task_id"] != bad["task_id"]
    reading = qual.reading_from_receipt(bad, qual.OPENAI_FAMILY, OPENAI_MODEL)
    assert reading is not None and reading.deterministic_checks_passed is False

    good = next(receipt for key, receipt in receipts.items() if key != rows[0]["candidateId"])
    other = qual.reading_from_receipt(good, qual.OPENAI_FAMILY, OPENAI_MODEL)
    assert other is not None and other.deterministic_checks_passed is True

    assert _sidecar(run_dir)["jobs"][0]["collection"]["taskIdEchoMismatches"] == 1


def test_the_verdict_protocol_is_referenced_never_restated(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """Whatever protocol the serial path speaks, the batch path speaks too.

    The prompt, the schema and the verdict vocabulary all live in
    ``qualification``; this asserts the batch road carries the choice through
    rather than owning a copy of it.
    """

    verdicts = getattr(qual, "VERDICTS_V2", None)
    if not verdicts:
        pytest.skip("the serial path offers only one verdict protocol")

    server = FakeProviders(verdict=verdicts[0])
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai", "--protocol", "v2")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    assert _sidecar(run_dir)["jobs"][0]["protocol"] == "v2"
    uploaded = server.files[_sidecar(run_dir)["jobs"][0]["inputFileId"]].decode("utf-8")
    system = json.loads(uploaded.splitlines()[0])["body"]["messages"][0]["content"]
    assert system == qual.model_input_texts(_pairs()[0], protocol="v2")[0]
    assert system != qual.model_input_texts(_pairs()[0], protocol="v1")[0]

    for receipt in _receipts(run_dir):
        assert receipt["protocol"] == "v2"
        assert receipt["outcome"] == "completed"
        reading = qual.reading_from_receipt(receipt, qual.OPENAI_FAMILY, OPENAI_MODEL)
        assert reading is not None and reading.deterministic_checks_passed


def test_an_unusable_answer_is_receipted_as_unusable(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    server = FakeProviders(verdict="a verdict no enum admits")
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    receipts = _receipts(run_dir)
    assert {receipt["outcome"] for receipt in receipts} == {"unusable_answer"}
    assert all("answer_text" in receipt for receipt in receipts)
    assert all(qual.reading_from_receipt(receipt, qual.OPENAI_FAMILY, OPENAI_MODEL) is None for receipt in receipts)


def test_an_error_line_is_receipted_as_a_provider_error(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    rows = _candidate_rows()
    failed = qbatch.custom_id(qual.OPENAI_FAMILY, rows[1]["candidateId"])
    server = FakeProviders(error_for=frozenset({failed}))
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    receipts = {receipt["candidate_id"]: receipt for receipt in _receipts(run_dir)}
    broken = receipts[rows[1]["candidateId"]]
    assert broken["outcome"] == "provider_error"
    assert broken["error_code"] == "rate_limit_exceeded"
    assert broken["response_sha256"].startswith("sha256:")
    assert qual.reading_from_receipt(broken, qual.OPENAI_FAMILY, OPENAI_MODEL) is None


def test_a_result_the_provider_never_returned_is_not_receipted(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """A lost request stays askable; receipting it would bury it forever."""

    rows = _candidate_rows()
    lost = qbatch.custom_id(qual.OPENAI_FAMILY, rows[2]["candidateId"])
    server = FakeProviders(omit=frozenset({lost}))
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    receipted = {receipt["candidate_id"] for receipt in _receipts(run_dir)}
    assert rows[2]["candidateId"] not in receipted
    assert _sidecar(run_dir)["jobs"][0]["collection"]["missingCustomIds"] == [lost]

    # ...and "not receipted" only means something if a later submit re-asks it.
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    jobs = _sidecar(run_dir)["jobs"]
    assert len(jobs) == 2
    assert [item["candidateId"] for item in jobs[1]["requests"]] == [rows[2]["candidateId"]]


def test_an_expired_job_still_yields_the_answers_it_was_billed_for(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """OpenAI publishes an expired batch's finished requests, and bills them.

    Treating expiry as "nothing to read" would throw those answers away and
    then buy the identical slice a second time.
    """

    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    for job in server.jobs.values():
        job["status"] = "expired"

    _run(monkeypatch, server, run_dir, "batch-collect")
    receipts = _receipts(run_dir)
    assert len(receipts) == 33
    assert {receipt["outcome"] for receipt in receipts} == {"completed"}
    assert _sidecar(run_dir)["jobs"][0]["state"] == "expired"

    # Nothing left to re-ask, so nothing is bought again.
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    assert len(_sidecar(run_dir)["jobs"]) == 1


def test_a_receipt_never_carries_the_credential(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai,gemini")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    written = (run_dir / RUNNER.RECEIPTS).read_text(encoding="utf-8")
    written += (run_dir / qbatch.SIDECAR).read_text(encoding="utf-8")
    assert "OPENAI-SECRET-VALUE" not in written
    assert "GEMINI-SECRET-VALUE" not in written
    for receipt in _receipts(run_dir):
        assert receipt["request_headers"]["Authorization"] == "<redacted>"
    # ...but the wire did carry it.
    assert any(call["headers"].get("Authorization") == "Bearer OPENAI-SECRET-VALUE" for call in server.calls)


# ---------------------------------------------------------------------------
# resume safety
# ---------------------------------------------------------------------------


def test_collecting_twice_appends_nothing_the_second_time(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")
    first = (run_dir / RUNNER.RECEIPTS).read_text(encoding="utf-8")
    downloads = sum(url.endswith("/content") for url in server.urls())

    spent = _sidecar(run_dir)["totalBatchAssumedCostUsd"]
    evidence = _sidecar(run_dir)["jobs"][0]["collection"]
    assert spent > 0

    _run(monkeypatch, server, run_dir, "batch-collect")
    second = (run_dir / RUNNER.RECEIPTS).read_text(encoding="utf-8")

    assert second == first
    keys = [(receipt["candidate_id"], receipt["family"]) for receipt in _receipts(run_dir)]
    assert len(keys) == len(set(keys))
    # A re-collect must not spend the receipted evidence it re-walks past.  A
    # tracker that recorded nothing, written over the sidecar, would seal a run
    # receipt claiming this batch cost nothing and found no echo mismatches.
    assert _sidecar(run_dir)["totalBatchAssumedCostUsd"] == spent
    assert _sidecar(run_dir)["jobs"][0]["collection"] == evidence
    assert json.loads((run_dir / "spend.json").read_text(encoding="utf-8"))["totalBatchAssumedCostUsd"] == spent
    # The finished job is not re-downloaded either.
    assert sum(url.endswith("/content") for url in server.urls()) == downloads == 1


def test_a_second_submit_never_re_asks_a_receipted_or_in_flight_candidate(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    # Everything is in flight, so a second submit has nothing left to buy.
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    assert len(_sidecar(run_dir)["jobs"]) == 1

    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")
    before = len(_receipts(run_dir))

    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    assert len(_sidecar(run_dir)["jobs"]) == 1
    assert len(_receipts(run_dir)) == before


def test_the_batch_road_leaves_a_serial_receipt_alone(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    """A pair the serial path already answered is never bought again."""

    rows = _candidate_rows()
    serial = {
        "candidate_id": rows[0]["candidateId"],
        "family": "openai",
        "kind": "crosswalk_validation",
        "outcome": "completed",
    }
    (run_dir / RUNNER.RECEIPTS).write_text(canonical_json(serial) + "\n", encoding="utf-8")

    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    planned = {item["candidateId"] for item in _sidecar(run_dir)["jobs"][0]["requests"]}
    assert rows[0]["candidateId"] not in planned
    assert len(planned) == len(rows) - 1


# ---------------------------------------------------------------------------
# spend
# ---------------------------------------------------------------------------


def test_submit_refuses_a_batch_whose_projection_exceeds_the_family_cap(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """The cap moves to submit time because a batch cannot be stopped."""

    server = FakeProviders()
    with pytest.raises(SystemExit) as failure:
        _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai", "--cap", "openai=0.001")
    assert "exceeds the $0.00 cap" in str(failure.value)
    assert not (run_dir / qbatch.SIDECAR).exists()
    # Model resolution happened; nothing was uploaded and no job was created.
    assert all(not url.endswith("/files") for url in server.urls())
    assert all(not url.endswith("/batches") for url in server.urls())


def test_a_job_created_before_a_later_failure_is_still_recorded(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """The worst thing a batch runner can do is forget it bought something.

    A job exists at the provider for 24 uncancellable hours.  If the submit
    that created it dies before the sidecar is written, the next submit cannot
    see it and buys the identical slice again.
    """

    class FailsOnGemini(FakeProviders):
        def _route(self, method, url, headers, body):  # type: ignore[no-untyped-def]
            if url.endswith("/upload/v1beta/files"):
                return 500, {}, b'{"error": "upload unavailable"}'
            return super()._route(method, url, headers, body)

    server = FailsOnGemini()
    with pytest.raises(qbatch.BatchError):
        _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai,gemini")

    created = [url for url in server.urls() if url.endswith("/batches")]
    assert created == ["https://api.openai.com/v1/batches"]
    assert [job["family"] for job in _sidecar(run_dir)["jobs"]] == ["openai"]

    # The recorded job holds its candidates, so the retry buys only gemini.
    retry = FakeProviders()
    _run(monkeypatch, retry, run_dir, "batch-submit", "--families", "openai,gemini")
    assert [job["family"] for job in _sidecar(run_dir)["jobs"]] == ["openai", "gemini"]
    assert len([url for url in retry.urls() if url.endswith("/batches")]) == 1


def test_collect_polls_first_so_it_never_reports_success_on_stale_state(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """Job state lives in the sidecar; collect must refresh it, not trust it."""

    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()

    # No batch-status in between: the sidecar still says `pending`.
    assert _sidecar(run_dir)["jobs"][0]["state"] == "pending"
    assert _run(monkeypatch, server, run_dir, "batch-collect") == 0
    assert len(_receipts(run_dir)) == 33


def test_a_sidecar_naming_an_unknown_family_refuses_with_a_message(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    (run_dir / qbatch.SIDECAR).write_text(
        canonical_json({"jobs": [{"family": "anthropic", "jobId": "batch_x", "requests": []}]}) + "\n",
        encoding="utf-8",
    )
    server = FakeProviders()
    with pytest.raises(SystemExit) as failure:
        _run(monkeypatch, server, run_dir, "batch-status")
    assert "anthropic" in str(failure.value)


def test_submitting_one_family_keeps_the_others_model_resolution(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """Batch submits arrive one family at a time; the run receipt keeps both."""

    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "gemini")
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    families = json.loads((run_dir / RUNNER.MODELS_RECEIPT).read_text(encoding="utf-8"))["families"]
    assert {item["family"] for item in families} == {"gemini", "openai"}
    assert {item["resolved_model_id"] for item in families} == {OPENAI_MODEL, GEMINI_MODEL}


def test_the_total_cap_counts_what_earlier_submits_already_bought(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """One family at a time must not walk past a ceiling both together hit."""

    monkeypatch.setattr(qual, "TOTAL_SPEND_CAP_USD", 0.40)
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    assert _sidecar(run_dir)["jobs"][0]["projectedCostUsd"] > 0.20

    with pytest.raises(SystemExit) as failure:
        _run(monkeypatch, server, run_dir, "batch-submit", "--families", "gemini")
    assert "already committed" in str(failure.value)
    assert len(_sidecar(run_dir)["jobs"]) == 1


def test_the_cap_counts_live_projections_and_money_already_spent() -> None:
    """A job releases its projection only when nothing was ever bought."""

    sidecar = {
        "jobs": [
            # live: still its conservative projection
            {"family": "openai", "projectedCostUsd": 5.0, "requests": [], "state": "running"},
            # dead with nothing to read: never ran, so nothing is owed
            {"family": "openai", "projectedCostUsd": 9.0, "requests": [], "state": "failed"},
            # collected: what it really cost, forever
            {
                "collectedAt": "2026-08-03T00:00:00Z",
                "collection": {"assumedCostUsd": 0.25},
                "family": "openai",
                "projectedCostUsd": 9.0,
                "requests": [],
                "state": "succeeded",
            },
            # expired but holding answers the provider already billed for
            {
                "family": "gemini",
                "outputFileId": "files/out-1",
                "projectedCostUsd": 3.0,
                "requests": [],
                "state": "expired",
            },
        ]
    }
    assert qbatch.committed_by_family(sidecar) == {"gemini": 3.0, "openai": 5.25}


def test_a_job_holds_its_candidates_until_its_answers_are_in_hand() -> None:
    def job(**overrides: Any) -> dict[str, Any]:
        return {"family": "openai", "requests": [{"candidateId": "c"}], "state": "succeeded", **overrides}

    assert qbatch.released(job()) is False
    assert qbatch.released(job(state="failed")) is True
    # Terminal, but the provider left a file: those answers were paid for.
    assert qbatch.released(job(state="expired", outputFileId="file-out-1")) is False
    assert qbatch.released(job(state="expired")) is True
    # Collected: the receipt file holds what it answered, and what it lost
    # goes back in the pool so a later submit can ask again.
    assert qbatch.released(job(collectedAt="2026-08-03T00:00:00Z")) is True


def test_batch_pricing_is_half_the_serial_pricing() -> None:
    priced = qbatch.batch_family(qual.OPENAI_FAMILY)
    assert priced.assumed_input_usd_per_mtok == qual.OPENAI_FAMILY.assumed_input_usd_per_mtok / 2
    assert priced.assumed_output_usd_per_mtok == qual.OPENAI_FAMILY.assumed_output_usd_per_mtok / 2
    # Identity and budget are untouched: only the price of the question moved.
    assert priced.name == qual.OPENAI_FAMILY.name
    assert priced.independence_group == qual.OPENAI_FAMILY.independence_group
    assert priced.spend_cap_usd == qual.OPENAI_FAMILY.spend_cap_usd
    serial = qual.SpendTracker(qual.OPENAI_FAMILY).cost(900, 2000)
    assert qbatch.projected_batch_cost(qual.OPENAI_FAMILY, 1) == pytest.approx(serial / 2)


def test_the_sidecar_records_the_assumed_batch_pricing(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai,gemini")
    sidecar = _sidecar(run_dir)
    assert sidecar["protocol"] == qbatch.SIDECAR_PROTOCOL
    assert sidecar["batchPricingFactor"] == 0.5
    for job in sidecar["jobs"]:
        family = qual.VALIDATOR_FAMILIES[job["family"]]
        assert job["assumedPricingUsdPerMtok"] == {
            "input": family.assumed_input_usd_per_mtok / 2,
            "output": family.assumed_output_usd_per_mtok / 2,
        }
        assert job["completionWindow"] == "24h"
        assert job["projectedCostUsd"] > 0
        assert job["submittedAt"].endswith("Z")
        assert job["inputFileSha256"].startswith("sha256:")


def test_collect_adds_batch_spend_beside_whatever_qualify_wrote(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    (run_dir / "spend.json").write_text(
        canonical_json({"spendByFamily": [{"family": "openai"}], "totalAssumedCostUsd": 1.5}) + "\n",
        encoding="utf-8",
    )
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    spend = json.loads((run_dir / "spend.json").read_text(encoding="utf-8"))
    assert spend["spendByFamily"] == [{"family": "openai"}]
    assert spend["totalAssumedCostUsd"] == 1.5
    assert spend["totalBatchAssumedCostUsd"] > 0
    assert spend["batchSpendByFamily"][0]["family"] == "openai"


# ---------------------------------------------------------------------------
# subsetting and slicing
# ---------------------------------------------------------------------------


def test_max_candidates_batches_a_stratified_subset(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    rows = _candidate_rows()
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai", "--max-candidates", "4")
    job = _sidecar(run_dir)["jobs"][0]
    assert job["candidateCount"] == 4
    chosen = {item["candidateId"] for item in job["requests"]}
    expected = {row["candidateId"] for row in qual.stratified_subset(rows, 4)}
    assert chosen == expected


def test_the_uploaded_file_is_one_json_object_per_candidate(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    job = _sidecar(run_dir)["jobs"][0]
    uploaded = server.files[job["inputFileId"]].decode("utf-8")
    lines = [json.loads(line) for line in uploaded.splitlines() if line.strip()]
    assert len(lines) == job["candidateCount"]
    assert {line["custom_id"] for line in lines} == {item["customId"] for item in job["requests"]}
    for line in lines:
        assert line["body"]["model"] == OPENAI_MODEL
        assert [message["role"] for message in line["body"]["messages"]] == ["system", "user"]


# ---------------------------------------------------------------------------
# state normalization and raw-byte digests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": "validating"}, "pending"),
        ({"status": "in_progress"}, "running"),
        ({"status": "finalizing"}, "running"),
        ({"status": "completed"}, "succeeded"),
        ({"status": "failed"}, "failed"),
        ({"status": "expired"}, "expired"),
        ({"status": "cancelled"}, "cancelled"),
        ({"metadata": {"state": "JOB_STATE_RUNNING"}}, "running"),
        ({"metadata": {"state": "JOB_STATE_SUCCEEDED"}}, "succeeded"),
        ({"state": "JOB_STATE_EXPIRED"}, "expired"),
    ],
)
def test_both_vendors_state_vocabularies_normalize(payload: Mapping[str, Any], expected: str) -> None:
    provider = qbatch.provider_for(qual.GEMINI_FAMILY)
    assert provider.normalize_state(payload) == expected


def test_the_response_digest_is_taken_over_the_providers_own_bytes() -> None:
    """Not our re-serialization of it: the substring the provider wrote."""

    body = {"choices": [{"message": {"content": "{}"}}], "model": "m"}
    line = json.dumps({"custom_id": "x", "response": {"body": body, "status_code": 200}})
    recovered = qbatch._raw_value_slice(line, "body", body)
    assert recovered is not None
    assert json.loads(recovered) == body
    assert recovered in line
    # Provider spacing is preserved rather than normalized away.
    assert recovered != canonical_json(body)


def test_a_slice_that_cannot_be_recovered_falls_back_to_canonical_bytes() -> None:
    assert qbatch._raw_value_slice('{"custom_id": "x"}', "body", {"a": 1}) is None


def test_status_on_an_empty_run_directory_is_quiet(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    server = FakeProviders()
    assert _run(monkeypatch, server, run_dir, "batch-status") == 0
    assert _run(monkeypatch, server, run_dir, "batch-collect") == 0
    assert server.calls == []


def test_the_module_documents_the_endpoints_it_was_written_against() -> None:
    """The wire shapes were researched, and the receipt says where."""

    doc = qbatch.__doc__ or ""
    for url in (
        "https://developers.openai.com/api/docs/guides/batch",
        "https://ai.google.dev/gemini-api/docs/batch-api",
        "https://ai.google.dev/gemini-api/docs/openai",
    ):
        assert url in doc
