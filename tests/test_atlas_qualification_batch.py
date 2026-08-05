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


@pytest.mark.parametrize(
    ("declared_type", "expected_reader"),
    (
        (
            "urn:ref:type:FederalRegisterThesaurus2025ManagedReleaseManifest",
            "federal-register",
        ),
        ("urn:ref:type:IcpsrManagedReleaseManifest", "icpsr"),
        ("urn:ref:type:UnknownManagedReleaseManifest", "managed"),
        (["not", "a", "string"], "managed"),
    ),
)
def test_qualification_runner_privately_selects_the_managed_release_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    declared_type: object,
    expected_reader: str,
) -> None:
    manifest = tmp_path / "managed-release.json"
    manifest.write_text(json.dumps({"type": declared_type}), encoding="utf-8")
    calls: list[tuple[str, Path, str]] = []

    def reader(label: str) -> type:
        class FakeReader:
            @staticmethod
            def open(
                manifest_path: Path,
                *,
                expected_manifest_digest: str,
            ) -> str:
                calls.append((label, manifest_path, expected_manifest_digest))
                return label

        return FakeReader

    monkeypatch.setattr(RUNNER, "PinnedManagedRelease", reader("managed"))
    monkeypatch.setattr(
        RUNNER,
        "PinnedFederalRegisterThesaurus2025AtlasRelease",
        reader("federal-register"),
    )
    monkeypatch.setattr(
        RUNNER,
        "PinnedIcpsrSubjectAtlasRelease",
        reader("icpsr"),
    )

    digest = "sha256:" + "a" * 64
    assert RUNNER._open_managed_release(manifest, digest) == expected_reader
    assert calls == [(expected_reader, manifest, digest)]


def test_qualification_runner_selects_source_concept_release_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "bundle-manifest.json"
    manifest.write_text(json.dumps({"packageKind": "sourceConceptRelease"}), encoding="utf-8")
    calls: list[tuple[Path, str]] = []

    class FakeSourceConceptReleaseView:
        @staticmethod
        def open(manifest_path: Path, *, expected_manifest_digest: str) -> str:
            calls.append((manifest_path, expected_manifest_digest))
            return "source-release-view"

    monkeypatch.setattr(RUNNER, "SourceConceptReleaseView", FakeSourceConceptReleaseView)
    digest = "sha256:" + "a" * 64

    assert RUNNER._open_qualification_release(manifest, digest) == (
        "sourceConceptRelease",
        "source-release-view",
    )
    assert calls == [(manifest, digest)]


@pytest.mark.parametrize(
    ("declared_type", "expected"),
    [
        (
            "urn:ref:type:FederalRegisterThesaurus2025ManagedReleaseManifest",
            "PinnedFederalRegisterManagedConceptRelease",
        ),
        ("urn:ref:type:IcpsrManagedReleaseManifest", "PinnedIcpsrManagedConceptRelease"),
        ("urn:ref:type:UnknownManagedReleaseManifest", "PinnedManagedConceptRelease"),
    ],
)
def test_relation_sealing_selects_source_specific_managed_concept_readers(
    declared_type: str,
    expected: str,
) -> None:
    reader = RUNNER._managed_concept_release_reader({"type": declared_type})
    assert reader.__name__ == expected


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
                "protocol": qual.PROTOCOL,
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
        verdict: str = "near_same",
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
        if "semantic_plausibility" in str(body["messages"][0]["content"]):
            answer = {
                "task_id": task_id,
                "semantic_plausibility": 91,
                "evidence_sufficiency": 84,
                "likely_relation": "near_same",
                "reason": "the supplied concept facts support close review",
            }
        else:
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

        # -- cancel ---------------------------------------------------------
        if url.endswith(("/cancel", ":cancel")):
            target = url[: -len("/cancel")] if url.endswith("/cancel") else url[: -len(":cancel")]
            job_id = next((key for key in self.jobs if target.endswith(key)), None)
            if job_id is None:
                return 404, {}, b"{}"
            self.jobs[job_id]["status"] = "cancelled"
            return 200, {}, _json(self.jobs[job_id])

        # -- batches, identical for both vendors ----------------------------
        if url.endswith("/batches") and method == "POST":
            request = json.loads((body or b"{}").decode("utf-8"))
            vendor = "google" if "googleapis" in url else "openai"
            # Gemini hands back the native resource name even through the
            # compatibility layer, exactly as the live runs recorded.
            job_id = self._next("batches/g" if vendor == "google" else "batch_openai")
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
            # Suffix match, because Gemini's job identity is the native
            # resource name ("batches/xyz") even through the compatibility
            # layer, so the retrieve URL doubles the segment -- and Google
            # answers it, as the live runs recorded.
            job_id = next((key for key in self.jobs if url.endswith(key)), None)
            if job_id is None:
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


def _scoring_receipts(output: Path) -> list[dict[str, Any]]:
    path = output / RUNNER.SCORING_RECEIPTS
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
    protocol = qbatch.run_protocol({"protocol": qual.PROTOCOL})

    request = qbatch.build_request(qual.OPENAI_FAMILY, OPENAI_MODEL, row, protocol=protocol)

    system_text, user_text = qual.model_input_texts(pair, protocol=protocol)
    expected = qual._request_body(qual.OPENAI_FAMILY, OPENAI_MODEL, system_text, user_text)
    assert request.body == expected
    assert request.request_sha256 == qual._sha256_text(canonical_json(expected))
    assert request.task_id == qual.task_id(pair)


def test_a_scoring_batch_line_carries_the_serial_scorer_request() -> None:
    pair = _pairs()[0]
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    row = qbatch.CandidateRow(entry.candidate.identifier, pair, qual.scoring_input_digest(pair))

    request = qbatch.build_request(
        qual.OPENAI_FAMILY,
        OPENAI_MODEL,
        row,
        protocol=qual.SCORING_PROTOCOL,
        work_kind="scoring",
    )

    system_text, user_text = qual.scoring_input_texts(pair)
    expected = qual._request_body(qual.OPENAI_FAMILY, OPENAI_MODEL, system_text, user_text)
    assert request.body == expected
    assert request.request_sha256 == qual._sha256_text(canonical_json(expected))
    assert request.task_id == qual.scoring_task_id(pair)
    assert pair.generation_class not in request.line()

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
        answer = {"reason": "the labels denote the same concept", "task_id": self.task_id, "verdict": "near_same"}
        return 200, _json(
            {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                "model": OPENAI_MODEL,
                "usage": {"completion_tokens": 120, "prompt_tokens": 500},
            }
        )


class _ScoringSerialStub:
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
        answer = {
            "task_id": self.task_id,
            "semantic_plausibility": 91,
            "evidence_sufficiency": 84,
            "likely_relation": "near_same",
            "reason": "the supplied concept facts support close review",
        }
        return 200, _json(
            {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                "model": OPENAI_MODEL,
                "usage": {"completion_tokens": 120, "prompt_tokens": 500},
            }
        )


def test_scoring_batch_and_serial_paths_produce_the_same_receipt_shape(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "score-batch-submit", "--family", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "score-batch-status")
    _run(monkeypatch, server, run_dir, "score-batch-collect")
    batched = _scoring_receipts(run_dir)[0]
    row = next(item for item in _candidate_rows() if item["candidateId"] == batched["candidate_id"])
    pair = RUNNER._pair_from_dict(row)
    serial = qual.score_candidate(
        _ScoringSerialStub(qual.scoring_task_id(pair)),
        qual.OPENAI_FAMILY,
        "OPENAI-SECRET-VALUE",
        OPENAI_MODEL,
        pair=pair,
        candidate_id=str(row["candidateId"]),
        input_digest=qual.scoring_input_digest(pair),
        tracker=qual.SpendTracker(qual.OPENAI_FAMILY),
    )

    assert set(batched) == set(serial)
    assert batched["request_sha256"] == serial["request_sha256"]
    assert batched["kind"] == "crosswalk_scoring"
    reading = qual.score_reading_from_receipt(batched, qual.OPENAI_FAMILY, OPENAI_MODEL)
    assert reading is not None and reading.deterministic_checks_passed
    assert reading.semantic_plausibility == 91
    assert batched["assumed_cost_usd"] == pytest.approx(
        serial["assumed_cost_usd"] * qbatch.BATCH_PRICE_FACTOR
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


def test_a_run_is_submitted_under_the_only_supported_rubric(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """The catalog, upload, job, and receipts all carry the adopted rubric.

    A prior implementation defaulted provider execution independently of the
    candidates and bought a batch that asked a different question.
    """

    server = FakeProviders(verdict=qual.VERDICTS[0])
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")

    job = _sidecar(run_dir)["jobs"][0]
    assert job["protocol"] == qual.PROTOCOL
    uploaded = server.files[job["inputFileId"]].decode("utf-8")
    assert "target_is_broader" in uploaded


@pytest.mark.parametrize("command", ["qualify", "batch-submit"])
def test_a_non_v2_candidate_catalog_is_refused_before_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    command: str,
) -> None:
    catalog = json.loads((run_dir / RUNNER.CANDIDATES).read_text(encoding="utf-8"))
    catalog["protocol"] = "v1"
    (run_dir / RUNNER.CANDIDATES).write_text(canonical_json(catalog) + "\n", encoding="utf-8")
    server = FakeProviders()
    with pytest.raises(qbatch.BatchError) as failure:
        _run(monkeypatch, server, run_dir, command, "--families", "openai")
    assert "supports only 'v2'" in str(failure.value)
    assert server.calls == []
    assert not (run_dir / qbatch.SIDECAR).exists()


def test_cli_has_no_protocol_override() -> None:
    parser = RUNNER.build_parser()
    parsed = parser.parse_args(["--output", "run", "generate", "--generated-at", GENERATED_AT])
    assert not hasattr(parsed, "protocol")
    with pytest.raises(SystemExit):
        parser.parse_args(["--output", "run", "generate", "--generated-at", GENERATED_AT, "--protocol", "v1"])


def test_production_cli_rejects_pilot_caps_and_execution_subsets() -> None:
    parser = RUNNER.build_parser()
    parsed = parser.parse_args(
        ["--output", "run", "generate", "--generated-at", GENERATED_AT, "--production"]
    )
    assert parsed.production is True
    catalog = {
        "coverageMode": qual.PRODUCTION_COVERAGE_MODE,
        "generationPolicy": qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
        "productionFloor": qual.PRODUCTION_FLOOR,
        "limits": None,
    }

    with pytest.raises(SystemExit, match="complete candidate catalog"):
        RUNNER._refuse_production_subset(catalog, 10)
    with pytest.raises(SystemExit, match="pilot limit"):
        RUNNER._coverage_mode({**catalog, "limits": {"normalizedLabelEquality": 10}})


def test_candidates_without_a_protocol_are_refused(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    """Absent is refused, never assumed; assuming is what bought the bad batch."""

    catalog = json.loads((run_dir / RUNNER.CANDIDATES).read_text(encoding="utf-8"))
    del catalog["protocol"]
    (run_dir / RUNNER.CANDIDATES).write_text(canonical_json(catalog) + "\n", encoding="utf-8")
    server = FakeProviders()
    with pytest.raises(qbatch.BatchError) as failure:
        _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    assert "records no protocol" in str(failure.value)


def test_a_payload_that_does_not_carry_the_rubric_is_never_uploaded(run_dir: Path) -> None:
    """The last gate before money: read the bytes, not the intention."""

    rows = [
        qbatch.CandidateRow(str(row["candidateId"]), RUNNER._pair_from_dict(row), str(row["inputDigest"]))
        for row in json.loads((run_dir / RUNNER.CANDIDATES).read_text(encoding="utf-8"))["candidates"]
    ]
    with pytest.raises(qual.QualificationError, match="supports only 'v2'"):
        qbatch.build_request(qual.OPENAI_FAMILY, OPENAI_MODEL, rows[0], protocol="v1")

    payload = qbatch.input_jsonl(
        [qbatch.build_request(qual.OPENAI_FAMILY, OPENAI_MODEL, row, protocol=qual.PROTOCOL) for row in rows]
    )
    assert "target_is_broader" in qbatch.distinguishing_verdicts(qual.PROTOCOL)
    assert "target_is_broader" in payload.decode("utf-8")
    qbatch.assert_payload_speaks(payload, qual.PROTOCOL, rows=rows)

    # Losing the vocabulary anywhere in the payload is refused too.  The
    # instructions carry the schema, so this trips the first gate rather than
    # the second; both refuse, which is the property that matters.
    hollowed = payload.decode("utf-8").replace("target_is_broader", "REDACTED").encode("utf-8")
    with pytest.raises(qbatch.BatchError):
        qbatch.assert_payload_speaks(hollowed, qual.PROTOCOL, rows=rows)


def test_collect_refuses_answers_to_the_other_rubric(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> None:
    """A polluted sidecar must never reach receipts.jsonl."""

    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    sidecar = _sidecar(run_dir)
    sidecar["jobs"][0]["protocol"] = "v1"
    (run_dir / qbatch.SIDECAR).write_text(canonical_json(sidecar) + "\n", encoding="utf-8")
    with pytest.raises(qbatch.BatchError) as failure:
        _run(monkeypatch, server, run_dir, "batch-collect")
    assert "asked protocol 'v1' but this run is 'v2'" in str(failure.value)
    assert _receipts(run_dir) == []


def test_cancelling_records_the_outcome_against_every_live_job(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai,gemini")
    assert _run(monkeypatch, server, run_dir, "batch-cancel") == 0

    urls = server.urls()
    assert any(url.startswith("https://api.openai.com/v1/batches/") and url.endswith("/cancel") for url in urls)
    # The compatibility layer has no cancel; Gemini goes native.
    assert any(url.startswith("https://generativelanguage.googleapis.com/v1beta/batches/") for url in urls)
    assert any(url.endswith(":cancel") for url in urls)

    for job in _sidecar(run_dir)["jobs"]:
        assert job["state"] == "cancelled"
        assert job["cancellation"]["accepted"] is True
        assert job["cancellation"]["requestedAt"].endswith("Z")


def test_the_verdict_protocol_is_referenced_never_restated(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """Whatever protocol the run speaks, the batch path speaks too.

    The prompt, the schema and the verdict vocabulary all live in
    ``qualification``; this asserts the batch road carries the choice through
    rather than owning a copy of it.
    """

    server = FakeProviders(verdict=qual.VERDICTS[0])
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    assert _sidecar(run_dir)["jobs"][0]["protocol"] == qual.PROTOCOL
    uploaded = server.files[_sidecar(run_dir)["jobs"][0]["inputFileId"]].decode("utf-8")
    system = json.loads(uploaded.splitlines()[0])["body"]["messages"][0]["content"]
    assert system == qual.model_input_texts(_pairs()[0])[0]

    for receipt in _receipts(run_dir):
        assert receipt["protocol"] == qual.PROTOCOL
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


def test_the_default_total_cap_refuses_before_upload(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    monkeypatch.setattr(qual, "TOTAL_SPEND_CAP_USD", 0.01)
    server = FakeProviders()

    with pytest.raises(SystemExit, match=r"exceeds the \$0\.01 total cap"):
        _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")

    assert all(not url.endswith(("/files", "/batches")) for url in server.urls())
    assert not (run_dir / qbatch.SIDECAR).exists()


def test_an_explicit_total_cap_allows_the_complete_catalog(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    monkeypatch.setattr(qual, "TOTAL_SPEND_CAP_USD", 0.01)
    server = FakeProviders()

    assert (
        _run(
            monkeypatch,
            server,
            run_dir,
            "batch-submit",
            "--families",
            "openai",
            "--total-cap",
            "1.25",
        )
        == 0
    )
    assert _sidecar(run_dir)["jobs"][0]["candidateCount"] == len(_candidate_rows())


@pytest.mark.parametrize(
    ("command", "sidecar_name"),
    [
        ("batch-submit", qbatch.SIDECAR),
        ("score-batch-submit", RUNNER.SCORING_BATCH_SIDECAR),
    ],
)
def test_the_effective_total_cap_is_recorded_in_the_summary_and_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    sidecar_name: str,
) -> None:
    server = FakeProviders()
    family_option = "--families" if command == "batch-submit" else "--family"
    _run(
        monkeypatch,
        server,
        run_dir,
        command,
        family_option,
        "openai",
        "--total-cap",
        "1.25",
    )

    sidecar = json.loads((run_dir / sidecar_name).read_text(encoding="utf-8"))
    assert sidecar["totalSpendCapUsd"] == 1.25
    assert sidecar["jobs"][0]["totalSpendCapUsd"] == 1.25
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["totalSpendCapUsd"] == 1.25


@pytest.mark.parametrize("command", ["batch-submit", "score-batch-submit"])
@pytest.mark.parametrize("cap", ["0", "-1", "nan", "inf", "-inf"])
def test_total_cap_must_be_positive_and_finite(command: str, cap: str) -> None:
    parser = RUNNER.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--output", "run", command, "--env", "env", "--total-cap", cap]
        )


@pytest.mark.parametrize("command", ["batch-submit", "score-batch-submit"])
@pytest.mark.parametrize("cap", ["0", "-1", "nan", "inf", "-inf"])
def test_family_cap_must_be_positive_and_finite(command: str, cap: str) -> None:
    parser = RUNNER.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--output",
                "run",
                command,
                "--env",
                "env",
                "--cap",
                f"openai={cap}",
            ]
        )


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
