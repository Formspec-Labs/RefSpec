"""The batch road to a qualification receipt, proven offline for both vendors.

Every test here runs against a fake provider that speaks both wire shapes: the
OpenAI Batch API end to end, and Gemini's split arrangement — OpenAI-shaped job
control, native File API for the bytes.  Nothing is uploaded and nothing is
spent.

Group size one is byte-for-byte the serial request and retains the same receipt
field set.  Production groups record the actual shared request/response digests
plus each extracted answer digest, then prove those richer receipts still pass
the same per-candidate readers, bundle gate, resume key, and spend accounting.
"""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import threading
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
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
        omit_task_ids: frozenset[str] = frozenset(),
        duplicate_task_ids: frozenset[str] = frozenset(),
        malformed_task_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.files: dict[str, bytes] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.upload_sessions: dict[str, str] = {}
        self.verdict = verdict
        self.wrong_task_id_for = wrong_task_id_for
        self.error_for = error_for
        self.omit = omit
        self.omit_task_ids = omit_task_ids
        self.duplicate_task_ids = duplicate_task_ids
        self.malformed_task_ids = malformed_task_ids
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
        scoring = "semantic_plausibility" in str(body["messages"][0]["content"])

        def answer_for(task_id: str) -> dict[str, Any]:
            if scoring:
                return {
                    "task_id": task_id,
                    "semantic_plausibility": 91,
                    "evidence_sufficiency": 84,
                    "likely_relation": "near_same",
                    "reason": "the supplied concept facts support close review",
                }
            return {
                "reason": "the labels denote the same concept",
                "task_id": task_id,
                "verdict": self.verdict,
            }

        if "rows" in payload:
            answers: list[dict[str, Any]] = []
            for row in payload["rows"]:
                task_id = str(row["taskId"])
                if task_id in self.omit_task_ids:
                    continue
                answer = answer_for(task_id)
                if task_id in self.malformed_task_ids:
                    answer.pop("semantic_plausibility" if scoring else "verdict")
                answers.append(answer)
                if task_id in self.duplicate_task_ids:
                    answers.append(dict(answer))
            answer: Mapping[str, Any] = {"answers": answers, "group_id": payload["group_id"]}
        else:
            task_id = "task-not-the-one-asked-about" if token in self.wrong_task_id_for else payload["taskId"]
            answer = answer_for(task_id)
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


class _ProcessSubmitTransport:
    """Spawn-safe fake that reports provider creates through a shared queue."""

    def __init__(self, label: str, events: Any) -> None:
        self.label = label
        self.events = events

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        del headers, timeout
        if method == "POST" and url.endswith("/v1/files"):
            return 200, {}, _json({"id": f"file-in-{self.label}"})
        if method == "POST" and url.endswith("/v1/batches"):
            request = json.loads((body or b"{}").decode("utf-8"))
            self.events.put(("create", self.label, 1))
            return 200, {}, _json(
                {
                    "completion_window": request["completion_window"],
                    "endpoint": request["endpoint"],
                    "id": f"batch-{self.label}",
                    "input_file_id": request["input_file_id"],
                    "request_counts": {"completed": 0, "failed": 0, "total": 0},
                    "status": "validating",
                }
            )
        raise AssertionError(f"unexpected process transport request: {method} {url}")


class _GuardRaceTransport:
    """Report any provider access that crosses an under-lock mutation guard."""

    def __init__(self, operation: str, events: Any) -> None:
        self.operation = operation
        self.events = events

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        del headers, body, timeout
        self.events.put(("provider", self.operation, method, url))
        raise AssertionError("a sealed scorer mutation reached the provider")


def _concurrent_submit_worker(
    *,
    label: str,
    run_root: str,
    sidecar_name: str,
    coordination_name: str,
    receipts_name: str,
    rows: list[qbatch.CandidateRow],
    work_kind: qbatch.WorkKind,
    events: Any,
) -> None:
    root = Path(run_root)
    events.put(("started", label, 0))
    try:
        summary = qbatch.submit(
            transport=_ProcessSubmitTransport(label, events),
            receipts_path=root / receipts_name,
            sidecar_path=root / sidecar_name,
            families=(qual.OPENAI_FAMILY,),
            keys={"openai": "offline-process-secret"},
            models={"openai": OPENAI_MODEL},
            rows=rows,
            protocol=(qual.PROTOCOL if work_kind == "validation" else qual.SCORING_PROTOCOL),
            work_kind=work_kind,
            group_size=1,
            coordination_sidecars=(root / coordination_name,),
        )
    except BaseException as error:  # noqa: BLE001 - child returns diagnostic to parent
        events.put(("error", label, repr(error)))
        return
    events.put(("finished", label, len(summary["jobs"])))


def _queued_scoring_mutation_worker(
    *,
    run_root: str,
    operation: str,
    events: Any,
) -> None:
    root = Path(run_root)
    rows = _batch_rows_from_run(root, scoring=True)
    sidecar_path = root / RUNNER.SCORING_BATCH_SIDECAR
    transport = _GuardRaceTransport(operation, events)
    common = {
        "transport": transport,
        "sidecar_path": sidecar_path,
        "families": {"openai": qual.OPENAI_FAMILY},
        "keys": {"openai": "offline-process-secret"},
        "mutation_guard": lambda: RUNNER._refuse_scoring_mutation_after_judging(
            root
        ),
    }
    events.put(("started", operation))
    try:
        if operation == "submit":
            qbatch.submit(
                transport=transport,
                receipts_path=root / RUNNER.SCORING_RECEIPTS,
                sidecar_path=sidecar_path,
                families=(qual.OPENAI_FAMILY,),
                keys={"openai": "offline-process-secret"},
                models={"openai": OPENAI_MODEL},
                rows=rows,
                protocol=qual.SCORING_PROTOCOL,
                work_kind="scoring",
                coordination_sidecars=(root / qbatch.SIDECAR,),
                mutation_guard=common["mutation_guard"],
            )
        elif operation == "reconcile":
            qbatch.reconcile(
                **common,
                rows=rows,
                work_kind="scoring",
                coordination_sidecars=(root / qbatch.SIDECAR,),
            )
        elif operation == "poll":
            qbatch.poll(**common)
        elif operation == "collect":
            qbatch.collect(
                **common,
                receipts_path=root / RUNNER.SCORING_RECEIPTS,
                rows=rows,
                protocol=qual.SCORING_PROTOCOL,
                work_kind="scoring",
            )
        elif operation == "cancel":
            qbatch.cancel(**common)
        else:
            raise AssertionError(f"unknown guarded operation {operation}")
    except SystemExit as error:
        events.put(("blocked", operation, str(error)))
    except BaseException as error:  # noqa: BLE001 - child returns diagnostic
        events.put(("error", operation, repr(error)))
    else:
        events.put(("finished", operation))


def _hold_process_submit_lock(
    run_root: str,
    ready: Any,
    release: Any,
) -> None:
    root = Path(run_root)
    with qbatch._run_submit_lock(
        root / qbatch.SIDECAR,
        (root / RUNNER.SCORING_BATCH_SIDECAR,),
    ):
        ready.set()
        release.wait(timeout=20)


def _run(monkeypatch: pytest.MonkeyPatch, server: FakeProviders, output: Path, *arguments: str) -> int:
    monkeypatch.setattr(qbatch, "default_transport", lambda: server)
    selected = list(arguments)
    if selected and selected[0] in {"batch-submit", "score-batch-submit"} and "--group-size" not in selected:
        selected.extend(("--group-size", "1"))
    return RUNNER.main(["--output", str(output), *selected, "--env", str(output / "env")])


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


def _batch_rows_from_run(output: Path, *, scoring: bool = False) -> list[qbatch.CandidateRow]:
    catalog = json.loads((output / RUNNER.CANDIDATES).read_text(encoding="utf-8"))
    return [
        qbatch.CandidateRow(
            candidate_id=str(row["candidateId"]),
            pair=RUNNER._pair_from_dict(row),
            input_digest=(
                qual.scoring_input_digest(RUNNER._pair_from_dict(row))
                if scoring
                else str(row["inputDigest"])
            ),
        )
        for row in catalog["candidates"]
    ]


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


@pytest.mark.parametrize("group_size", [1, 25])
def test_gemini_36_batch_bodies_drop_legacy_generation_controls(
    run_dir: Path,
    group_size: int,
) -> None:
    requests = qbatch.build_provider_requests(
        qual.GEMINI_FAMILY,
        GEMINI_MODEL,
        _batch_rows_from_run(run_dir),
        protocol=qual.PROTOCOL,
        group_size=group_size,
    )
    assert requests
    assert all(
        qual.GEMINI_36_DEPRECATED_GENERATION_CONTROLS.isdisjoint(request.body)
        for request in requests
    )


def test_custom_ids_are_deterministic_and_family_scoped() -> None:
    first = qbatch.custom_id(qual.OPENAI_FAMILY, "urn:ref:candidate:one")
    assert first == qbatch.custom_id(qual.OPENAI_FAMILY, "urn:ref:candidate:one")
    assert first != qbatch.custom_id(qual.GEMINI_FAMILY, "urn:ref:candidate:one")


def test_production_grouping_is_deterministic_bounded_and_explicit(run_dir: Path) -> None:
    rows = _batch_rows_from_run(run_dir)
    first = qbatch.deterministic_groups(rows, group_size=25)
    second = qbatch.deterministic_groups(list(reversed(rows)), group_size=25)

    assert [[row.candidate_id for row in group] for group in first] == [
        [row.candidate_id for row in group] for group in second
    ]
    assert sum(len(group) for group in first) == len(rows)
    assert max(map(len, first)) <= 25
    assert all(qbatch._group_input_size(group, work_kind="validation")[0] <= qbatch.GROUP_INPUT_BYTE_LIMIT for group in first if len(group) > 1)
    assert all(qbatch._group_input_size(group, work_kind="validation")[1] <= qbatch.GROUP_INPUT_TOKEN_LIMIT for group in first if len(group) > 1)

    requests = qbatch.build_provider_requests(
        qual.OPENAI_FAMILY,
        OPENAI_MODEL,
        rows,
        protocol=qual.PROTOCOL,
        group_size=25,
    )
    assert len(requests) < len(rows)


def _priority_provenance(
    candidate_ids: Sequence[str],
    *,
    score_digit: str = "4",
) -> dict[str, Any]:
    candidate_count = len(candidate_ids)
    basis = {
        "type": qual.SCORER_PRIORITY_PROVENANCE_TYPE,
        "schemaVersion": qual.SCORER_PRIORITY_PROVENANCE_VERSION,
        "policy": qual.SCORER_PRIORITY_POLICY,
        "candidateCatalogFileDigest": "sha256:" + "1" * 64,
        "candidateCount": candidate_count,
        "orderedCandidateIdsDigest": qual._sha256_text(
            canonical_json(list(candidate_ids))
        ),
        "scoreVectorDigest": "sha256:" + score_digit * 64,
        "scorerFamily": "openai",
        "scorerModelId": OPENAI_MODEL,
        "scoringProtocol": qual.SCORING_PROTOCOL,
        "scoringReceiptCount": candidate_count,
        "scoringReceiptLogFileDigest": "sha256:" + "5" * 64,
        "scoringSidecarFileDigest": "sha256:" + "6" * 64,
    }
    return {
        **basis,
        "priorityDigest": qual._sha256_text(canonical_json(basis)),
    }


def test_ranked_judging_packs_in_score_order_without_revealing_scores(
    run_dir: Path,
) -> None:
    unranked = _batch_rows_from_run(run_dir)
    desired = list(reversed(unranked))
    ranks = {row.candidate_id: rank for rank, row in enumerate(desired)}
    rows = [
        qbatch.CandidateRow(
            row.candidate_id,
            row.pair,
            row.input_digest,
            ranks[row.candidate_id],
        )
        for row in unranked
    ]

    requests = qbatch.build_provider_requests(
        qual.OPENAI_FAMILY,
        OPENAI_MODEL,
        rows,
        protocol=qual.PROTOCOL,
        group_size=25,
    )

    actual = [
        candidate_id
        for request in requests
        for candidate_id in (
            request.candidate_ids
            if isinstance(request, qbatch.GroupedBatchRequest)
            else (request.candidate_id,)
        )
    ]
    assert actual == [row.candidate_id for row in desired]
    request_text = "\n".join(request.line() for request in requests)
    assert "semantic_plausibility" not in request_text
    assert "evidence_sufficiency" not in request_text
    assert "priority" not in request_text.casefold()
    assert all(isinstance(request, qbatch.GroupedBatchRequest) for request in requests)
    for request in requests:
        assert request.request_sha256 == qual._sha256_text(canonical_json(request.body))
        assert request.body[qual.OPENAI_FAMILY.max_output_tokens_field] == qbatch.grouped_output_allowance(
            qual.OPENAI_FAMILY, len(request.rows)
        )
        assert len(request.custom_id) <= 64
        assert request.group_id in request.body["messages"][1]["content"]

    parser = RUNNER.build_parser()
    parsed = parser.parse_args(["--output", "run", "batch-submit", "--env", "env"])
    assert parsed.group_size == 25
    recovery = parser.parse_args(
        ["--output", "run", "batch-submit", "--env", "env", "--group-size", "1"]
    )
    assert recovery.group_size == 1


def test_priority_provenance_is_immutable_across_restart_and_recovery(
    run_dir: Path,
) -> None:
    server = FakeProviders()
    base_rows = _batch_rows_from_run(run_dir)
    rows = [
        qbatch.CandidateRow(
            row.candidate_id,
            row.pair,
            row.input_digest,
            rank,
        )
        for rank, row in enumerate(base_rows)
    ]
    sidecar = run_dir / qbatch.SIDECAR
    ordered_ids = [row.candidate_id for row in rows]
    provenance = _priority_provenance(ordered_ids)
    submit = {
        "transport": server,
        "receipts_path": run_dir / RUNNER.RECEIPTS,
        "sidecar_path": sidecar,
        "families": (qual.OPENAI_FAMILY,),
        "keys": {"openai": "offline-secret"},
        "models": {"openai": OPENAI_MODEL},
        "rows": rows,
        "protocol": qual.PROTOCOL,
        "group_size": 25,
        "priority_provenance": provenance,
    }

    qbatch.submit(**submit)
    creates = sum(call["url"].endswith("/batches") for call in server.calls)
    qbatch.submit(**submit)
    assert sum(call["url"].endswith("/batches") for call in server.calls) == creates
    assert _sidecar(run_dir)["priorityProvenance"] == provenance

    changed = {
        **submit,
        "priority_provenance": _priority_provenance(
            ordered_ids,
            score_digit="7",
        ),
    }
    with pytest.raises(qbatch.BatchError, match="cannot change"):
        qbatch.submit(**changed)
    with pytest.raises(qbatch.BatchError, match="require priority provenance"):
        qbatch.submit(**{key: value for key, value in submit.items() if key != "priority_provenance"})

    fresh_sidecar = run_dir / "changed-order-batch-jobs.json"
    changed_rows = [
        qbatch.CandidateRow(
            row.candidate_id,
            row.pair,
            row.input_digest,
            len(rows) - rank - 1,
        )
        for rank, row in enumerate(base_rows)
    ]
    calls_before = len(server.calls)
    with pytest.raises(qbatch.BatchError, match="ranks differ from priority provenance"):
        qbatch.submit(
            **{
                **submit,
                "sidecar_path": fresh_sidecar,
                "rows": changed_rows,
            }
        )
    assert len(server.calls) == calls_before
    assert not fresh_sidecar.exists()


def test_waiting_official_judging_rechecks_priority_under_the_run_lock(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    base_rows = _batch_rows_from_run(run_dir)
    rows = [
        qbatch.CandidateRow(
            row.candidate_id,
            row.pair,
            row.input_digest,
            rank,
        )
        for rank, row in enumerate(base_rows)
    ]
    ordered_ids = [row.candidate_id for row in rows]
    provenance = _priority_provenance(ordered_ids)
    current = {"rows": rows, "provenance": provenance}
    authority = {"authorityId": "urn:ref:test:production-authority"}

    def derive_current(
        _output: Path,
        _authority: Mapping[str, Any],
    ) -> tuple[list[qbatch.CandidateRow], dict[str, Any]]:
        return current["rows"], current["provenance"]

    monkeypatch.setattr(RUNNER, "_official_judging_priority", derive_current)
    guard = RUNNER._official_judging_priority_guard(
        run_dir,
        authority,
        rows,
        provenance,
    )
    server = FakeProviders()
    started = threading.Event()
    outcome: list[BaseException | dict[str, Any]] = []

    def waiting_submit() -> None:
        started.set()
        try:
            outcome.append(
                qbatch.submit(
                    transport=server,
                    receipts_path=run_dir / RUNNER.RECEIPTS,
                    sidecar_path=run_dir / qbatch.SIDECAR,
                    families=(qual.OPENAI_FAMILY,),
                    keys={"openai": "offline-secret"},
                    models={"openai": OPENAI_MODEL},
                    rows=rows,
                    protocol=qual.PROTOCOL,
                    coordination_sidecars=(run_dir / RUNNER.SCORING_BATCH_SIDECAR,),
                    spend_authority=authority,
                    priority_provenance=provenance,
                    mutation_guard=guard,
                    lock_timeout_seconds=5,
                )
            )
        except BaseException as error:  # noqa: BLE001 - thread reports to test
            outcome.append(error)

    with qbatch._run_submit_lock(
        run_dir / qbatch.SIDECAR,
        (run_dir / RUNNER.SCORING_BATCH_SIDECAR,),
    ):
        worker = threading.Thread(target=waiting_submit)
        worker.start()
        assert started.wait(timeout=5)
        changed_ids = list(reversed(ordered_ids))
        ranks = {
            candidate_id: rank for rank, candidate_id in enumerate(changed_ids)
        }
        current["rows"] = [
            replace(row, priority_rank=ranks[row.candidate_id]) for row in rows
        ]
        current["provenance"] = _priority_provenance(
            changed_ids,
            score_digit="7",
        )

    worker.join(timeout=5)
    assert not worker.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], qbatch.BatchError)
    assert "changed after judging preflight" in str(outcome[0])
    assert server.calls == []
    assert not (run_dir / qbatch.SIDECAR).exists()


def test_batch_plan_is_read_only_and_reports_exact_request_shape(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        qbatch,
        "default_transport",
        lambda: (_ for _ in ()).throw(AssertionError("planning must not open a provider transport")),
    )
    assert RUNNER.main(["--output", str(run_dir), "batch-plan", "--group-size", "25"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["providerCalls"] is False
    assert plan["candidateCount"] == len(_candidate_rows())
    assert len(plan["jobs"]) == 3
    assert {(job["workKind"], job["family"]) for job in plan["jobs"]} == {
        ("scoring", "openai"),
        ("validation", "gemini"),
        ("validation", "openai"),
    }
    assert all(job["providerRequestCount"] < job["candidateCount"] for job in plan["jobs"])
    assert all(job["inputFileBytes"] > 0 for job in plan["jobs"])
    assert all(job["projectedInputTokens"] > 0 for job in plan["jobs"])
    assert all(job["projectedOutputTokenAllowance"] > 0 for job in plan["jobs"])
    assert plan["providerJobCount"] == sum(job["providerJobCount"] for job in plan["jobs"])
    assert all(job["providerJobCount"] == len(job["shards"]) for job in plan["jobs"])
    assert plan["totalProjectedCostUsd"] == pytest.approx(
        sum(job["projectedCostUsd"] for job in plan["jobs"])
    )

    assert RUNNER.main(
        ["--output", str(run_dir), "batch-plan", "--smoke-candidates", "7"]
    ) == 0
    smoke = json.loads(capsys.readouterr().out)
    assert smoke["planningMode"] == "stratifiedSmoke"
    assert smoke["candidateCount"] == 7
    assert all(job["candidateCount"] == 7 for job in smoke["jobs"])


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
    assert job["completedAtSource"] == {
        "kind": "providerStatus",
        "statusArtifactDigest": job["statusArtifacts"][-1]["fileDigest"],
        "statusArtifactFile": job["statusArtifacts"][-1]["file"],
        "statusPollOrdinal": job["statusArtifacts"][-1]["pollOrdinal"],
    }
    for receipt in receipts:
        reading = qual.reading_from_receipt(receipt, family, job["modelId"])
        assert reading is not None
        assert reading.deterministic_checks_passed
        assert reading.endpoint_host == qual.endpoint_host(family.base_url)
        assert reading.completed_at == job["completedAt"]
        assert receipt["started_at"] == job["submittedAt"]


def test_grouped_blind_judging_fans_out_complete_per_candidate_receipts(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(
        monkeypatch,
        server,
        run_dir,
        "batch-submit",
        "--families",
        "openai,gemini",
        "--group-size",
        "25",
    )
    jobs = _sidecar(run_dir)["jobs"]
    assert {job["candidateCount"] for job in jobs} == {len(_candidate_rows())}
    assert all(job["providerRequestCount"] < job["candidateCount"] for job in jobs)
    assert all(job["maxRequestGroupSize"] == 25 for job in jobs)
    assert {request["groupId"] for request in jobs[0]["providerRequests"]} == {
        request["groupId"] for request in jobs[1]["providerRequests"]
    }

    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")
    receipts = _receipts(run_dir)
    assert len(receipts) == 2 * len(_candidate_rows())
    assert {
        (receipt["candidate_id"], receipt["family"])
        for receipt in receipts
    } == {
        (str(row["candidateId"]), family)
        for row in _candidate_rows()
        for family in ("gemini", "openai")
    }
    for receipt in receipts:
        family = qual.VALIDATOR_FAMILIES[str(receipt["family"])]
        model = OPENAI_MODEL if family.name == "openai" else GEMINI_MODEL
        reading = qual.reading_from_receipt(receipt, family, model)
        assert reading is not None and reading.deterministic_checks_passed
        assert receipt["batch_request_kind"] == "grouped"
        assert receipt["request_sha256"] == receipt["group_request_sha256"]
        assert receipt["response_sha256"] == receipt["group_response_sha256"]
        assert receipt["answer_sha256"] == qual._sha256_text(canonical_json(receipt["answer"]))
        assert receipt["item_input_sha256"].startswith("sha256:")
        assert receipt["usage_scope"] == "sharedProviderRequest"
    assert RUNNER.main(["--output", str(run_dir), "bundle"]) == 0
    bundle = json.loads((run_dir / RUNNER.BUNDLE).read_text(encoding="utf-8"))
    response_artifacts = [
        artifact for artifact in bundle["artifacts"] if artifact["role"] == "validationResponse"
    ]
    assert len(response_artifacts) == len(receipts)
    assert all(
        artifact["content"]["providerRequest"]["protocol"]
        == qual.GROUPED_PROVIDER_REQUEST_PROTOCOL
        and artifact["content"]["providerRequest"]["kind"] == "grouped"
        and artifact["content"]["providerRequest"]["itemInputSha256"].startswith("sha256:")
        and artifact["content"]["providerRequest"]["answerSha256"].startswith("sha256:")
        for artifact in response_artifacts
    )
    run_receipt = json.loads((run_dir / RUNNER.RUN_RECEIPT).read_text(encoding="utf-8"))
    assert set(run_receipt["providerBatchEvidence"]) == {"judging"}
    assert run_receipt["providerBatchEvidence"]["judging"]["fileDigest"].startswith("sha256:")


def test_grouped_scoring_fans_out_verified_score_readings(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(
        monkeypatch,
        server,
        run_dir,
        "score-batch-submit",
        "--family",
        "openai",
        "--group-size",
        "25",
    )
    sidecar = json.loads((run_dir / RUNNER.SCORING_BATCH_SIDECAR).read_text(encoding="utf-8"))
    assert sidecar["jobs"][0]["providerRequestCount"] < sidecar["jobs"][0]["candidateCount"]
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "score-batch-collect")
    receipts = _scoring_receipts(run_dir)
    assert len(receipts) == len(_candidate_rows())
    for receipt in receipts:
        reading = qual.score_reading_from_receipt(receipt, qual.OPENAI_FAMILY, OPENAI_MODEL)
        assert reading is not None and reading.deterministic_checks_passed
        assert receipt["batch_request_kind"] == "grouped"
        assert receipt["answer_sha256"] == qual._sha256_text(canonical_json(receipt["answer"]))


def test_one_group_provider_failure_does_not_discard_other_groups(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(
        monkeypatch,
        server,
        run_dir,
        "batch-submit",
        "--families",
        "openai",
        "--group-size",
        "25",
    )
    job = _sidecar(run_dir)["jobs"][0]
    failed_request = job["providerRequests"][0]
    server.error_for = frozenset({str(failed_request["customId"])})
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")

    receipts = {receipt["candidate_id"]: receipt for receipt in _receipts(run_dir)}
    failed_ids = set(failed_request["candidateIds"])
    assert set(receipts) == {row["candidateId"] for row in _candidate_rows()} - failed_ids
    assert {receipt["outcome"] for receipt in receipts.values()} == {"completed"}
    collection = _sidecar(run_dir)["jobs"][0]["collection"]
    assert collection["groupIssues"][0]["groupOutcome"] == "provider_error"
    assert collection["lineIssues"]

    _run(
        monkeypatch,
        server,
        run_dir,
        "batch-submit",
        "--families",
        "openai",
        "--group-size",
        "25",
    )
    assert _sidecar(run_dir)["jobs"][-1]["candidateCount"] == len(failed_ids)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("itemInputSha256", "sha256:" + "0" * 64),
        ("groupId", "group-not-the-requested-group"),
        ("taskId", "task-not-the-requested-row"),
    ],
)
def test_bundle_refuses_tampered_group_row_and_task_lineage(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    field: str,
    replacement: str,
) -> None:
    server = FakeProviders()
    _run(
        monkeypatch,
        server,
        run_dir,
        "batch-submit",
        "--families",
        "openai,gemini",
        "--group-size",
        "25",
    )
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")
    sidecar = _sidecar(run_dir)
    sidecar["jobs"][0]["requests"][0][field] = replacement
    (run_dir / qbatch.SIDECAR).write_text(canonical_json(sidecar) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="provider request lineage failed"):
        RUNNER.main(["--output", str(run_dir), "bundle"])


def test_the_bundle_stage_seals_batch_receipts_without_knowing_they_are_batched(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    """The end the whole exercise is for: two machines, one sealed bundle.

    ``bundle`` is untouched by this workstream, so qualifying from collected
    receipts proves the per-candidate decision semantics are unchanged.
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


def test_a_singleton_batch_receipt_preserves_serial_semantics_and_adds_exact_lineage(
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

    assert set(serial) <= set(batched)
    assert batched["batch_execution_mode"] == "batch"
    assert batched["batch_attempt_id"].startswith("attempt-")
    assert batched["batch_shard_id"].startswith("shard-")
    assert batched["batch_result_id"].startswith("batch_req_")
    assert batched["batch_artifact_sha256"].startswith("sha256:")
    assert batched["batch_result_line_sha256"].startswith("sha256:")
    assert batched["request_sha256"] == serial["request_sha256"]
    assert batched["request_url"] == serial["request_url"]
    assert batched["request_headers"] == serial["request_headers"]
    assert batched["usage"]["prompt_tokens"] == serial["usage"]["prompt_tokens"]
    assert batched["usage"]["completion_tokens"] == serial["usage"]["completion_tokens"]
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


def test_scoring_batch_and_serial_paths_preserve_the_same_reading_semantics(
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

    assert set(serial) <= set(batched)
    assert batched["batch_execution_mode"] == "batch"
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
    assert rows[0]["candidateId"] not in receipts

    good = next(receipt for key, receipt in receipts.items() if key != rows[0]["candidateId"])
    other = qual.reading_from_receipt(good, qual.OPENAI_FAMILY, OPENAI_MODEL)
    assert other is not None and other.deterministic_checks_passed is True

    collection = _sidecar(run_dir)["jobs"][0]["collection"]
    assert any(issue.get("outcome") == "completed" for issue in collection["lineIssues"])


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

    cancelling = _sidecar(run_dir)["jobs"]
    for job in cancelling:
        assert job["state"] == "cancelling"
        assert job["cancellation"]["accepted"] is True
        assert job["cancellation"]["requestedAt"].endswith("Z")
        assert not qbatch.released(job)

    creates = sum(url.endswith("/batches") for url in server.urls())
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai,gemini")
    assert sum(url.endswith("/batches") for url in server.urls()) == creates

    # Only provider-reported terminal status releases the held attempts.
    _run(monkeypatch, server, run_dir, "batch-status")
    for job in _sidecar(run_dir)["jobs"]:
        assert job["state"] == "cancelled"
        assert job["statusArtifacts"]


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


def test_an_unusable_answer_stays_in_raw_evidence_and_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders(verdict="a verdict no enum admits")
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    assert _receipts(run_dir) == []
    collection = _sidecar(run_dir)["jobs"][0]["collection"]
    assert collection["outcomes"] == {"unusable_answer": len(_candidate_rows())}
    assert len(collection["lineIssues"]) == len(_candidate_rows())
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    assert _sidecar(run_dir)["jobs"][-1]["attemptOrdinal"] == 2


def test_an_error_line_stays_in_raw_evidence_and_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    rows = _candidate_rows()
    failed = qbatch.custom_id(qual.OPENAI_FAMILY, rows[1]["candidateId"])
    server = FakeProviders(error_for=frozenset({failed}))
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-status")
    _run(monkeypatch, server, run_dir, "batch-collect")

    receipts = {receipt["candidate_id"]: receipt for receipt in _receipts(run_dir)}
    assert rows[1]["candidateId"] not in receipts
    collection = _sidecar(run_dir)["jobs"][0]["collection"]
    assert collection["outcomes"]["provider_error"] == 1
    assert any(issue.get("candidateId") == rows[1]["candidateId"] for issue in collection["lineIssues"])


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


def test_grouped_missing_duplicate_and_malformed_rows_recover_only_affected_rows(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    rows = _batch_rows_from_run(run_dir)
    missing_task = qual.task_id(rows[0].pair)
    duplicate_task = qual.task_id(rows[1].pair)
    malformed_task = qual.task_id(rows[2].pair)
    server = FakeProviders(
        omit_task_ids=frozenset({missing_task}),
        duplicate_task_ids=frozenset({duplicate_task}),
        malformed_task_ids=frozenset({malformed_task}),
    )
    _run(
        monkeypatch,
        server,
        run_dir,
        "batch-submit",
        "--families",
        "openai",
        "--group-size",
        "25",
    )
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")

    first_receipts = _receipts(run_dir)
    assert len(first_receipts) == len(rows) - 3
    assert {receipt["task_id"] for receipt in first_receipts}.isdisjoint(
        {missing_task, duplicate_task, malformed_task}
    )
    issues = _sidecar(run_dir)["jobs"][0]["collection"]["groupIssues"]
    assert any(missing_task in issue.get("missingTaskIds", ()) for issue in issues)
    assert any(duplicate_task in issue.get("duplicateTaskIds", ()) for issue in issues)
    assert any(malformed_task in issue.get("invalidTaskIds", ()) for issue in issues)

    # Collection is idempotent, including its partial-recovery evidence.
    before = (run_dir / RUNNER.RECEIPTS).read_bytes()
    _run(monkeypatch, server, run_dir, "batch-collect")
    assert (run_dir / RUNNER.RECEIPTS).read_bytes() == before

    # A deliberate serial-shaped recovery asks only the two rows for which the
    # grouped response supplied no unambiguous answer.
    server.omit_task_ids = frozenset()
    server.duplicate_task_ids = frozenset()
    server.malformed_task_ids = frozenset()
    _run(
        monkeypatch,
        server,
        run_dir,
        "batch-submit",
        "--families",
        "openai",
        "--group-size",
        "1",
    )
    recovery = _sidecar(run_dir)["jobs"][1]
    assert recovery["candidateCount"] == 3
    assert recovery["providerRequestCount"] == 3
    assert {item["taskId"] for item in recovery["requests"]} == {
        missing_task,
        duplicate_task,
        malformed_task,
    }
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")
    assert len(_receipts(run_dir)) == len(rows)
    assert len({(receipt["candidate_id"], receipt["family"]) for receipt in _receipts(run_dir)}) == len(rows)


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
    assert [(job["family"], job["attemptState"]) for job in _sidecar(run_dir)["jobs"]] == [
        ("openai", "submitted"),
        ("gemini", "uploadFailed"),
    ]

    # The recorded job holds its candidates, so the retry buys only gemini.
    retry = FakeProviders()
    _run(monkeypatch, retry, run_dir, "batch-submit", "--families", "openai,gemini")
    assert [job["family"] for job in _sidecar(run_dir)["jobs"]] == ["openai", "gemini", "gemini"]
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

    monkeypatch.setattr(qual, "TOTAL_SPEND_CAP_USD", 0.65)
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    assert _sidecar(run_dir)["jobs"][0]["projectedCostUsd"] > 0.50

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


def test_a_spend_authority_is_pinned_before_submission_and_cannot_change(
    run_dir: Path,
) -> None:
    server = FakeProviders()
    rows = _batch_rows_from_run(run_dir)
    authority = {
        "authorityId": "urn:ref:test:spend-authority:one",
        "authorityRecordDigest": "sha256:" + "1" * 64,
        "jobKey": "test-job",
        "runSpendCapUsd": 1.25,
    }

    qbatch.submit(
        transport=server,
        receipts_path=run_dir / RUNNER.RECEIPTS,
        sidecar_path=run_dir / qbatch.SIDECAR,
        families=(qual.OPENAI_FAMILY,),
        keys={"openai": "offline-secret"},
        models={"openai": OPENAI_MODEL},
        rows=rows,
        caps={"openai": 1.25},
        total_cap_usd=1.25,
        protocol=qual.PROTOCOL,
        group_size=1,
        spend_authority=authority,
    )

    sidecar = _sidecar(run_dir)
    assert sidecar["spendAuthority"] == authority
    assert sidecar["jobs"][0]["spendAuthority"] == authority
    verification = qbatch.verify_sidecar_request_lineage(
        sidecar,
        families=qual.VALIDATOR_FAMILIES,
        rows=rows,
        work_kind="validation",
    )
    assert verification["jobs"] == 1

    for replacement in (
        None,
        {**authority, "authorityId": "urn:ref:test:spend-authority:two"},
    ):
        with pytest.raises(
            qbatch.BatchError,
            match="spend authority cannot change or be omitted",
        ):
            qbatch.submit(
                transport=server,
                receipts_path=run_dir / RUNNER.RECEIPTS,
                sidecar_path=run_dir / qbatch.SIDECAR,
                families=(qual.OPENAI_FAMILY,),
                keys={"openai": "offline-secret"},
                models={"openai": OPENAI_MODEL},
                rows=rows,
                caps={"openai": 1.25},
                total_cap_usd=1.25,
                protocol=qual.PROTOCOL,
                group_size=1,
                spend_authority=replacement,
            )

    sidecar["jobs"][0]["spendAuthority"] = None
    with pytest.raises(qbatch.BatchError, match="inconsistent provider or spend facts"):
        qbatch.verify_sidecar_request_lineage(
            sidecar,
            families=qual.VALIDATOR_FAMILIES,
            rows=rows,
            work_kind="validation",
        )


def test_official_production_refuses_before_provider_io_without_spend_authority(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    monkeypatch.setattr(
        RUNNER,
        "_official_production_job",
        lambda _output: {
            "key": "crs-policy-areas--federal-register-thesaurus-2025",
            "outputPath": "output/official",
        },
    )
    monkeypatch.setattr(
        qbatch,
        "default_transport",
        lambda: (_ for _ in ()).throw(
            AssertionError("authority must be checked before provider transport")
        ),
    )

    with pytest.raises(SystemExit, match="requires --spend-authority before any provider call"):
        RUNNER.main(
            [
                "--output",
                str(run_dir),
                "batch-submit",
                "--env",
                str(run_dir / "env"),
                "--group-size",
                "25",
            ]
        )

    with pytest.raises(SystemExit, match="Batch endpoints"):
        RUNNER.main(
            [
                "--output",
                str(run_dir),
                "score",
                "--env",
                str(run_dir / "env"),
            ]
        )


def test_official_production_uses_only_the_authority_run_allocation(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    tmp_path: Path,
) -> None:
    job = {
        "key": "crs-policy-areas--federal-register-thesaurus-2025",
        "outputPath": "output/official",
    }
    authority_file = tmp_path / "authority.json"
    authority_file.write_text("{}\n", encoding="utf-8")
    allocation = {
        "batchPlanDigest": "sha256:" + "c" * 64,
        "jobKey": job["key"],
        "outputPath": job["outputPath"],
        "runSpendCapUsd": "1.000000",
    }
    authority = SimpleNamespace(
        approved_total_spend_cap_usd=112.0,
        batch_policy_digest="sha256:" + "d" * 64,
        file_digest="sha256:" + "a" * 64,
        identifier="urn:ref:vocabulary-atlas-v1-production-spend-authority:" + "b" * 64,
        record={
            "approvedTotalSpendCapUsd": "112.000000",
            "batchPolicy": {
                "modelsByFamily": {
                    "gemini": GEMINI_MODEL,
                    "openai": OPENAI_MODEL,
                }
            },
        },
        record_digest="sha256:" + "b" * 64,
        job=lambda key: allocation if key == job["key"] else None,
    )
    monkeypatch.setattr(RUNNER, "ROOT", tmp_path)
    monkeypatch.setattr(RUNNER, "_official_production_job", lambda _output: job)
    monkeypatch.setattr(RUNNER, "_production_qualification_manifest", lambda: object())
    monkeypatch.setattr(
        RUNNER.qspend,
        "read_vocabulary_atlas_v1_production_spend_authority",
        lambda *_args, **_kwargs: authority,
    )
    args = RUNNER.build_parser().parse_args(
        [
            "--output",
            str(run_dir),
            "batch-submit",
            "--env",
            str(run_dir / "env"),
            "--group-size",
            "25",
            "--spend-authority",
            str(authority_file),
        ]
    )

    caps, total_cap, descriptor = RUNNER._production_batch_controls(
        args,
        work_kind="validation",
    )

    assert caps == {"gemini": 1.0, "openai": 1.0}
    assert total_cap == 1.0
    assert descriptor == {
        "approvedTotalSpendCapUsd": "112.000000",
        "batchPlanDigest": "sha256:" + "c" * 64,
        "batchPolicyDigest": "sha256:" + "d" * 64,
        "modelsByFamily": {
            "gemini": GEMINI_MODEL,
            "openai": OPENAI_MODEL,
        },
        "authorityFile": "authority.json",
        "authorityFileDigest": "sha256:" + "a" * 64,
        "authorityId": authority.identifier,
        "authorityRecordDigest": "sha256:" + "b" * 64,
        "jobKey": job["key"],
        "runSpendCapUsd": "1.000000",
    }

    args.group_size = 1
    with pytest.raises(SystemExit, match="same-stage 25-row Batch evidence"):
        RUNNER._production_batch_controls(args, work_kind="validation")

    (run_dir / RUNNER.SCORING_BATCH_SIDECAR).write_text(
        canonical_json(
            {
                "plannedShards": [
                    {"maxRequestGroupSize": 25, "workKind": "scoring"}
                ],
                "spendAuthority": descriptor,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="same-stage 25-row Batch evidence"):
        RUNNER._production_batch_controls(args, work_kind="validation")

    (run_dir / qbatch.SIDECAR).write_text(
        canonical_json({"plannedShards": [], "spendAuthority": descriptor})
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="same-stage 25-row Batch evidence"):
        RUNNER._production_batch_controls(args, work_kind="validation")

    (run_dir / qbatch.SIDECAR).write_text(
        canonical_json(
            {
                "plannedShards": [
                    {"maxRequestGroupSize": 25, "workKind": "validation"}
                ],
                "spendAuthority": descriptor,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert RUNNER._production_batch_controls(
        args,
        work_kind="validation",
    ) == (caps, total_cap, descriptor)

    args.group_size = 25
    args.total_cap = 112.0
    with pytest.raises(SystemExit, match="remove manual --cap and --total-cap"):
        RUNNER._production_batch_controls(args, work_kind="validation")


def test_official_production_refuses_a_dated_model_variant_before_batch_create(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    class DatedModelsOnly(FakeProviders):
        def _route(self, method, url, headers, body):  # type: ignore[no-untyped-def]
            if url.endswith("/models"):
                requested = (
                    qual.GEMINI_FAMILY.requested_model
                    if "googleapis" in url
                    else qual.OPENAI_FAMILY.requested_model
                )
                prefix = "models/" if "googleapis" in url else ""
                return 200, {}, _json(
                    {"data": [{"id": f"{prefix}{requested}-2026-08-05"}]}
                )
            return super()._route(method, url, headers, body)

    server = DatedModelsOnly()
    monkeypatch.setattr(qbatch, "default_transport", lambda: server)
    monkeypatch.setattr(
        RUNNER,
        "_production_batch_controls",
        lambda _args, *, work_kind: (
            {"gemini": 10.0, "openai": 10.0},
            10.0,
            {
                "authorityId": "urn:ref:test:production-authority",
                "jobKey": "test-job",
                "modelsByFamily": {
                    "gemini": GEMINI_MODEL,
                    "openai": OPENAI_MODEL,
                },
            },
            ),
        )
    monkeypatch.setattr(
        RUNNER,
        "_official_judging_priority",
        lambda output, _authority: (
            RUNNER._batch_rows(
                SimpleNamespace(output=output, max_candidates=None),
                subset=False,
            ),
            {"priorityDigest": "sha256:" + "0" * 64},
        ),
    )

    with pytest.raises(SystemExit, match="requires the exact approved gemini model"):
        RUNNER.main(
            [
                "--output",
                str(run_dir),
                "batch-submit",
                "--env",
                str(run_dir / "env"),
                "--group-size",
                "25",
            ]
        )

    assert not [call for call in server.calls if call["method"] == "POST"]


def test_official_judging_requires_complete_scoring_before_provider_access(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    provider_accessed = False

    def provider_forbidden() -> None:
        nonlocal provider_accessed
        provider_accessed = True
        raise AssertionError("provider access must follow complete scoring")

    monkeypatch.setattr(qbatch, "default_transport", provider_forbidden)
    monkeypatch.setattr(
        RUNNER,
        "_production_batch_controls",
        lambda _args, *, work_kind: (
            {"gemini": 10.0, "openai": 10.0},
            10.0,
            {
                "authorityId": "urn:ref:test:production-authority",
                "jobKey": "test-job",
                "modelsByFamily": {
                    "gemini": GEMINI_MODEL,
                    "openai": OPENAI_MODEL,
                },
            },
        ),
    )

    with pytest.raises(SystemExit, match="complete verified scoring Batch evidence"):
        RUNNER.main(
            [
                "--output",
                str(run_dir),
                "batch-submit",
                "--env",
                str(run_dir / "env"),
                "--group-size",
                "25",
            ]
        )

    assert provider_accessed is False


def test_official_judging_reconcile_derives_priority_before_provider_setup(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    descriptor = {"authorityId": "urn:ref:test:production-authority"}
    (run_dir / qbatch.SIDECAR).write_text(
        canonical_json(
            {
                "jobs": [],
                "plannedShards": [{"family": "openai"}],
                "spendAuthority": descriptor,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    base_rows = _batch_rows_from_run(run_dir)
    judge_rows = [
        qbatch.CandidateRow(
            row.candidate_id,
            row.pair,
            row.input_digest,
            rank,
        )
        for rank, row in enumerate(base_rows)
    ]
    provenance = _priority_provenance(
        [row.candidate_id for row in judge_rows]
    )
    events: list[str] = []
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        RUNNER,
        "_official_production_job",
        lambda _output: {"key": "test-job", "outputPath": str(run_dir)},
    )
    monkeypatch.setattr(
        RUNNER,
        "_production_reconcile_spend_authority",
        lambda _args: descriptor,
    )

    def priority_first(
        output: Path,
        spend_authority: Mapping[str, Any],
    ) -> tuple[list[qbatch.CandidateRow], dict[str, Any]]:
        events.append("priority")
        assert output == run_dir
        assert spend_authority == descriptor
        return judge_rows, provenance

    def provider_after_priority() -> object:
        events.append("transport")
        return object()

    def keys_after_priority(
        _args: Any,
        families: Sequence[qual.ValidatorFamily],
    ) -> dict[str, str]:
        events.append("keys")
        assert [family.name for family in families] == ["openai"]
        return {"openai": "offline-secret"}

    def reconcile_after_priority(**kwargs: Any) -> dict[str, Any]:
        kwargs["mutation_guard"]()
        events.append("reconcile")
        captured.update(kwargs)
        return {"jobs": [], "resumed": []}

    monkeypatch.setattr(RUNNER, "_official_judging_priority", priority_first)
    monkeypatch.setattr(qbatch, "default_transport", provider_after_priority)
    monkeypatch.setattr(RUNNER, "_batch_keys", keys_after_priority)
    monkeypatch.setattr(qbatch, "reconcile", reconcile_after_priority)

    assert RUNNER.command_batch_reconcile(
        SimpleNamespace(output=run_dir, env=run_dir / "env")
    ) == 0
    assert events == ["priority", "transport", "keys", "priority", "reconcile"]
    assert captured["rows"] == judge_rows
    assert captured["work_kind"] == "validation"
    assert captured["spend_authority"] == descriptor
    assert captured["priority_provenance"] == provenance
    assert callable(captured["mutation_guard"])


def test_official_reconcile_requires_an_independent_spend_authority_file(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    monkeypatch.setattr(
        RUNNER,
        "_official_production_job",
        lambda _output: {"key": "test-job", "outputPath": str(run_dir)},
    )
    with pytest.raises(SystemExit, match="requires --spend-authority"):
        RUNNER._production_reconcile_spend_authority(
            SimpleNamespace(output=run_dir, spend_authority=None)
        )

    authority_path = REFSPEC_ROOT / "portfolio" / "test-spend-authority.json"
    descriptor = {"authorityId": "urn:ref:test:production-authority"}
    requested: list[tuple[Path, Path]] = []

    def read_requested(
        output: Path,
        path: Path,
    ) -> tuple[object, Mapping[str, Any], dict[str, Any]]:
        requested.append((output, path))
        return object(), {"jobKey": "test-job"}, descriptor

    monkeypatch.setattr(
        RUNNER,
        "_read_requested_official_spend_authority",
        read_requested,
    )
    assert RUNNER._production_reconcile_spend_authority(
        SimpleNamespace(output=run_dir, spend_authority=authority_path)
    ) == descriptor
    assert requested == [(run_dir, authority_path)]

    parsed = RUNNER.build_parser().parse_args(
        [
            "--output",
            str(run_dir),
            "batch-reconcile",
            "--env",
            str(run_dir / "env"),
            "--spend-authority",
            str(authority_path),
        ]
    )
    assert parsed.spend_authority == authority_path


def test_official_judging_reconcile_requires_scoring_before_provider_setup(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    descriptor = {"authorityId": "urn:ref:test:production-authority"}
    (run_dir / qbatch.SIDECAR).write_text(
        canonical_json(
            {
                "jobs": [],
                "plannedShards": [{"family": "openai"}],
                "spendAuthority": descriptor,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    provider_accessed = False

    monkeypatch.setattr(
        RUNNER,
        "_official_production_job",
        lambda _output: {"key": "test-job", "outputPath": str(run_dir)},
    )
    monkeypatch.setattr(
        RUNNER,
        "_production_reconcile_spend_authority",
        lambda _args: descriptor,
    )

    def provider_forbidden() -> None:
        nonlocal provider_accessed
        provider_accessed = True
        raise AssertionError("provider access must follow complete scoring")

    monkeypatch.setattr(qbatch, "default_transport", provider_forbidden)

    with pytest.raises(SystemExit, match="complete verified scoring Batch evidence"):
        RUNNER.command_batch_reconcile(
            SimpleNamespace(output=run_dir, env=run_dir / "env")
        )
    assert provider_accessed is False


def test_official_partial_score_recovery_uses_complete_verified_receipts(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    rows = _batch_rows_from_run(run_dir, scoring=True)
    omitted_task = qual.scoring_task_id(rows[0].pair)
    server = FakeProviders(omit_task_ids=frozenset({omitted_task}))
    descriptor = {
        "authorityId": "urn:ref:test:production-authority",
        "modelsByFamily": {"openai": OPENAI_MODEL},
    }
    submit = {
        "transport": server,
        "receipts_path": run_dir / RUNNER.SCORING_RECEIPTS,
        "sidecar_path": run_dir / RUNNER.SCORING_BATCH_SIDECAR,
        "families": (qual.OPENAI_FAMILY,),
        "keys": {"openai": "offline-secret"},
        "models": {"openai": OPENAI_MODEL},
        "rows": rows,
        "caps": {"openai": 10.0},
        "total_cap_usd": 10.0,
        "protocol": qual.SCORING_PROTOCOL,
        "work_kind": "scoring",
        "group_size": 25,
        "coordination_sidecars": (run_dir / qbatch.SIDECAR,),
        "spend_authority": descriptor,
    }

    qbatch.submit(**submit)
    server.complete_jobs()
    qbatch.poll(
        transport=server,
        sidecar_path=run_dir / RUNNER.SCORING_BATCH_SIDECAR,
        families={"openai": qual.OPENAI_FAMILY},
        keys={"openai": "offline-secret"},
    )
    qbatch.collect(
        transport=server,
        receipts_path=run_dir / RUNNER.SCORING_RECEIPTS,
        sidecar_path=run_dir / RUNNER.SCORING_BATCH_SIDECAR,
        families={"openai": qual.OPENAI_FAMILY},
        keys={"openai": "offline-secret"},
        rows=rows,
        protocol=qual.SCORING_PROTOCOL,
        work_kind="scoring",
    )
    assert 0 < len(_scoring_receipts(run_dir)) < len(rows)

    server.omit_task_ids = frozenset()
    qbatch.submit(**{**submit, "group_size": 1})
    server.complete_jobs()
    qbatch.poll(
        transport=server,
        sidecar_path=run_dir / RUNNER.SCORING_BATCH_SIDECAR,
        families={"openai": qual.OPENAI_FAMILY},
        keys={"openai": "offline-secret"},
    )
    qbatch.collect(
        transport=server,
        receipts_path=run_dir / RUNNER.SCORING_RECEIPTS,
        sidecar_path=run_dir / RUNNER.SCORING_BATCH_SIDECAR,
        families={"openai": qual.OPENAI_FAMILY},
        keys={"openai": "offline-secret"},
        rows=rows,
        protocol=qual.SCORING_PROTOCOL,
        work_kind="scoring",
    )
    receipts = _scoring_receipts(run_dir)
    verification = qbatch.verify_provider_batch_evidence(
        sidecar_path=run_dir / RUNNER.SCORING_BATCH_SIDECAR,
        families=qual.VALIDATOR_FAMILIES,
        rows=rows,
        receipts=receipts,
        work_kind="scoring",
    )
    assert verification["candidateRequests"] > len(rows)
    assert verification["verifiedReceipts"] == len(rows)

    monkeypatch.setattr(
        RUNNER,
        "_verify_official_spend_authority_descriptor",
        lambda _output, _descriptor: (
            object(),
            {"jobKey": "test-job", "runSpendCapUsd": "10.000000"},
        ),
    )
    monkeypatch.setattr(
        RUNNER.qspend,
        "verify_vocabulary_atlas_v1_production_batch_sidecar",
        lambda *_args, **_kwargs: {},
    )
    judge_rows, provenance = RUNNER._official_judging_priority(
        run_dir,
        descriptor,
    )
    assert len(judge_rows) == len(rows)
    assert {row.priority_rank for row in judge_rows} == set(range(len(rows)))
    assert provenance["scoringReceiptCount"] == len(rows)

    receipt_path = run_dir / RUNNER.SCORING_RECEIPTS
    original = [dict(receipt) for receipt in receipts]
    tampered = [dict(receipt) for receipt in original]
    tampered[0] = {
        **tampered[0],
        "answer": {
            **dict(tampered[0]["answer"]),
            "task_id": "urn:ref:task:tampered",
        },
    }
    invalid_logs = (
        original[:-1],
        [*original, original[0]],
        tampered,
    )
    for invalid in invalid_logs:
        receipt_path.write_text(
            "".join(canonical_json(receipt) + "\n" for receipt in invalid),
            encoding="utf-8",
        )
        with pytest.raises(
            SystemExit,
            match="complete verified scoring Batch evidence|complete scoring coverage",
        ):
            RUNNER._official_judging_priority(run_dir, descriptor)


@pytest.mark.parametrize("retained_key", ["plannedShards", "jobs"])
def test_scoring_evidence_stays_sealed_when_judging_priority_is_deleted(
    run_dir: Path,
    retained_key: str,
) -> None:
    (run_dir / qbatch.SIDECAR).write_text(
        canonical_json(
            {
                "jobs": [{"jobId": "batch-1"}] if retained_key == "jobs" else [],
                "plannedShards": (
                    [{"shardId": "shard-1"}]
                    if retained_key == "plannedShards"
                    else []
                ),
                "spendAuthority": {"authorityId": "urn:ref:test:authority"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="sealed as judging priority provenance"):
        RUNNER._refuse_scoring_mutation_after_judging(run_dir)


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


def test_mutable_terminal_state_cannot_release_a_created_attempt(
    run_dir: Path,
) -> None:
    server = FakeProviders()
    rows = _batch_rows_from_run(run_dir)
    sidecar_path = run_dir / qbatch.SIDECAR
    submit = {
        "transport": server,
        "receipts_path": run_dir / RUNNER.RECEIPTS,
        "sidecar_path": sidecar_path,
        "families": (qual.OPENAI_FAMILY,),
        "keys": {"openai": "offline-secret"},
        "models": {"openai": OPENAI_MODEL},
        "rows": rows,
        "protocol": qual.PROTOCOL,
        "group_size": 1,
    }
    qbatch.submit(**submit)
    sidecar = _sidecar(run_dir)
    projection = sidecar["jobs"][0]["projectedCostUsd"]
    sidecar["jobs"][0]["state"] = "failed"
    sidecar["jobs"][0]["providerStatus"] = "failed"
    sidecar["jobs"][0]["statusArtifacts"] = []
    sidecar["jobs"][0].pop("terminalRelease", None)
    sidecar_path.write_text(canonical_json(sidecar) + "\n", encoding="utf-8")
    calls_before = len(server.calls)

    summary = qbatch.submit(**submit)

    assert summary["jobs"] == []
    assert len(server.calls) == calls_before
    assert qbatch.committed_by_family(_sidecar(run_dir)) == {
        "openai": projection
    }


def test_retained_terminal_status_can_release_a_created_attempt(
    run_dir: Path,
) -> None:
    server = FakeProviders()
    rows = _batch_rows_from_run(run_dir)
    sidecar_path = run_dir / qbatch.SIDECAR
    submit = {
        "transport": server,
        "receipts_path": run_dir / RUNNER.RECEIPTS,
        "sidecar_path": sidecar_path,
        "families": (qual.OPENAI_FAMILY,),
        "keys": {"openai": "offline-secret"},
        "models": {"openai": OPENAI_MODEL},
        "rows": rows,
        "protocol": qual.PROTOCOL,
        "group_size": 1,
    }
    qbatch.submit(**submit)
    provider_job = next(iter(server.jobs.values()))
    provider_job["status"] = "failed"
    qbatch.poll(
        transport=server,
        sidecar_path=sidecar_path,
        families={"openai": qual.OPENAI_FAMILY},
        keys={"openai": "offline-secret"},
    )
    failed = _sidecar(run_dir)["jobs"][0]
    assert failed["terminalRelease"]["kind"] == "providerTerminalWithoutResults"
    assert qbatch.released(failed)

    summary = qbatch.submit(**submit)

    assert len(summary["jobs"]) == 1
    assert len(_sidecar(run_dir)["jobs"]) == 2


def test_attempt_journal_blocks_deleted_sidecar_job_before_provider_io(
    run_dir: Path,
) -> None:
    server = FakeProviders()
    rows = _batch_rows_from_run(run_dir)
    sidecar_path = run_dir / qbatch.SIDECAR
    submit = {
        "transport": server,
        "receipts_path": run_dir / RUNNER.RECEIPTS,
        "sidecar_path": sidecar_path,
        "families": (qual.OPENAI_FAMILY,),
        "keys": {"openai": "offline-secret"},
        "models": {"openai": OPENAI_MODEL},
        "rows": rows,
        "protocol": qual.PROTOCOL,
        "group_size": 1,
    }
    qbatch.submit(**submit)
    sidecar = _sidecar(run_dir)
    sidecar["jobs"] = []
    sidecar_path.write_text(canonical_json(sidecar) + "\n", encoding="utf-8")
    calls_before = len(server.calls)

    with pytest.raises(
        qbatch.BatchError,
        match="sidecar attempts differ from the immutable attempt journal",
    ):
        qbatch.submit(**submit)

    assert len(server.calls) == calls_before


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


def test_current_standard_price_assumptions_and_grouped_projection_are_explicit(
    run_dir: Path,
) -> None:
    assert (
        qual.OPENAI_FAMILY.assumed_input_usd_per_mtok,
        qual.OPENAI_FAMILY.assumed_output_usd_per_mtok,
    ) == (2.50, 15.00)
    assert (
        qual.GEMINI_FAMILY.assumed_input_usd_per_mtok,
        qual.GEMINI_FAMILY.assumed_output_usd_per_mtok,
    ) == (1.50, 7.50)

    rows = _batch_rows_from_run(run_dir)
    grouped = qbatch.build_provider_requests(
        qual.OPENAI_FAMILY,
        OPENAI_MODEL,
        rows,
        protocol=qual.PROTOCOL,
        group_size=25,
    )
    assert qbatch.projected_request_cost(qual.OPENAI_FAMILY, grouped) < qbatch.projected_batch_cost(
        qual.OPENAI_FAMILY, len(rows)
    )


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


# ---------------------------------------------------------------------------
# release-grade attempt, shard, raw-evidence, and usage exactness
# ---------------------------------------------------------------------------


def test_provider_job_shards_are_deterministic_complete_and_queue_safe() -> None:
    base = _pairs()[0]
    rows: list[qbatch.CandidateRow] = []
    for index in range(100):
        source = replace(
            base.source,
            member=f"urn:ref:test:large:{index}",
            definition=("bounded provider-job evidence " * 1400) + str(index),
        )
        pair = replace(base, source=source)
        rows.append(
            qbatch.CandidateRow(
                candidate_id=f"urn:ref:test:candidate:{index}",
                pair=pair,
                input_digest="sha256:" + f"{index:064x}"[-64:],
            )
        )

    def plan(values: list[qbatch.CandidateRow]) -> tuple[qbatch.RequestShard, ...]:
        requests = qbatch.build_provider_requests(
            qual.OPENAI_FAMILY,
            OPENAI_MODEL,
            values,
            protocol=qual.PROTOCOL,
            group_size=1,
        )
        return qbatch.deterministic_request_shards(
            qual.OPENAI_FAMILY,
            OPENAI_MODEL,
            requests,
            protocol=qual.PROTOCOL,
            work_kind="validation",
        )

    forward = plan(rows)
    reversed_plan = plan(list(reversed(rows)))
    assert [shard.shard_id for shard in forward] == [shard.shard_id for shard in reversed_plan]
    assert len(forward) > 1
    assert sum(shard.candidate_count for shard in forward) == len(rows)
    assert len({request.custom_id for shard in forward for request in shard.requests}) == len(rows)
    assert all(shard.projected_input_tokens <= qbatch.MAX_PROVIDER_JOB_INPUT_TOKENS for shard in forward)
    assert all(len(shard.requests) <= qbatch.MAX_PROVIDER_REQUESTS_PER_JOB for shard in forward)
    assert all(shard.input_bytes <= qbatch.OPENAI_MAX_INPUT_FILE_BYTES for shard in forward)


@pytest.mark.parametrize(
    ("family", "payload", "expected"),
    [
        (
            qual.OPENAI_FAMILY,
            {"usage": {"completion_tokens": 3, "prompt_tokens": 10, "total_tokens": 13}},
            (10, 3, 13, "providerReported"),
        ),
        (
            qual.GEMINI_FAMILY,
            {"usage": {"completionTokens": 3, "promptTokens": 10, "totalTokens": 15}},
            (10, 5, 15, "geminiCompatibleReported"),
        ),
        (
            qual.GEMINI_FAMILY,
            {
                "usageMetadata": {
                    "candidatesTokenCount": 2,
                    "promptTokenCount": 10,
                    "thoughtsTokenCount": 3,
                    "totalTokenCount": 15,
                }
            },
            (10, 5, 15, "nativeReported"),
        ),
        (
            qual.OPENAI_FAMILY,
            {"usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}},
            (10, 4, 14, "providerReported"),
        ),
        (qual.GEMINI_FAMILY, {}, (None, None, None, "missing")),
    ],
)
def test_provider_usage_normalization_preserves_missing_and_gemini_reasoning(
    family: qual.ValidatorFamily,
    payload: Mapping[str, Any],
    expected: tuple[int | None, int | None, int | None, str],
) -> None:
    usage = qbatch.normalize_provider_usage(payload, family)
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens, usage.status) == expected


def test_missing_usage_keeps_the_conservative_projection_committed(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    class OmitsUsage(FakeProviders):
        def _output_line(self, token: str, body: Mapping[str, Any]) -> dict[str, Any]:
            line = super()._output_line(token, body)
            del line["response"]["body"]["usage"]
            return line

    server = OmitsUsage()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "gemini")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")

    job = _sidecar(run_dir)["jobs"][0]
    assert job["collection"]["usageStatus"] == "missing"
    assert job["collection"]["exactCostUsd"] is None
    assert job["collection"]["committedCostUsd"] == job["projectedCostUsd"]
    assert qbatch.committed_by_family(_sidecar(run_dir)) == {
        "gemini": job["projectedCostUsd"]
    }


def test_unmatched_extra_result_line_keeps_projected_cost_committed(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    provider_job = next(iter(server.jobs.values()))
    output_id = str(provider_job["output_file_id"])
    first = json.loads(server.files[output_id].splitlines()[0])
    extra = {
        **first,
        "custom_id": "request-unmatched-extra-line",
        "id": "batch-request-unmatched-extra-line",
    }
    server.files[output_id] += _json(extra) + b"\n"

    _run(monkeypatch, server, run_dir, "batch-collect")
    job = _sidecar(run_dir)["jobs"][0]
    collection = job["collection"]
    assert collection["usageStatus"] == "missing"
    assert collection["exactCostUsd"] is None
    assert collection["committedCostUsd"] == job["projectedCostUsd"]
    assert any(
        issue["kind"] == "unmatchedCustomId"
        for issue in collection["lineIssues"]
    )
    assert collection["resultLines"] == job["providerRequestCount"] + 1

    verification = qbatch.verify_provider_batch_evidence(
        sidecar_path=run_dir / qbatch.SIDECAR,
        families=qual.VALIDATOR_FAMILIES,
        rows=_batch_rows_from_run(run_dir),
        receipts=_receipts(run_dir),
        work_kind="validation",
    )
    assert verification["committedCostUsd"] == job["projectedCostUsd"]


def test_aggregate_usage_mismatch_blocks_collection_after_retaining_raw_bytes(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    for job in server.jobs.values():
        job["usage"] = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}

    with pytest.raises(qbatch.BatchError, match="aggregate usage differs"):
        _run(monkeypatch, server, run_dir, "batch-collect")
    job = _sidecar(run_dir)["jobs"][0]
    assert job["resultArtifacts"]
    assert _receipts(run_dir) == []


def test_duplicate_custom_id_lines_are_evidenced_blocked_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    first_job = _sidecar(run_dir)["jobs"][0]
    duplicated_candidate = str(first_job["requests"][0]["candidateId"])
    server.complete_jobs()
    output_id = next(iter(server.jobs.values()))["output_file_id"]
    first_line = server.files[output_id].splitlines(keepends=True)[0]
    server.files[output_id] = first_line + server.files[output_id]
    _run(monkeypatch, server, run_dir, "batch-collect")

    assert duplicated_candidate not in {row["candidate_id"] for row in _receipts(run_dir)}
    issues = _sidecar(run_dir)["jobs"][0]["collection"]["lineIssues"]
    assert sum(issue["kind"] == "duplicateCustomId" for issue in issues) == 2
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    assert _sidecar(run_dir)["jobs"][-1]["candidateCount"] == 1


def test_same_shape_retry_has_a_new_attempt_identity_and_exact_lineage(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    catalog_path = run_dir / RUNNER.CANDIDATES
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["candidates"] = catalog["candidates"][:1]
    catalog["total"] = 1
    catalog_path.write_text(canonical_json(catalog) + "\n", encoding="utf-8")
    candidate_id = str(catalog["candidates"][0]["candidateId"])
    token = qbatch.custom_id(qual.OPENAI_FAMILY, candidate_id)
    server = FakeProviders(omit=frozenset({token}))

    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")
    assert _receipts(run_dir) == []
    first = _sidecar(run_dir)["jobs"][0]

    server.omit = frozenset()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    second = _sidecar(run_dir)["jobs"][1]
    assert second["shardId"] == first["shardId"]
    assert second["attemptId"] != first["attemptId"]
    assert second["attemptOrdinal"] == 2
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")

    receipt = _receipts(run_dir)[0]
    assert receipt["batch_attempt_id"] == second["attemptId"]
    summary = qbatch.verify_provider_batch_evidence(
        sidecar_path=run_dir / qbatch.SIDECAR,
        families=qual.VALIDATOR_FAMILIES,
        rows=_batch_rows_from_run(run_dir),
        receipts=_receipts(run_dir),
        work_kind="validation",
    )
    assert summary["attempts"] == 2
    assert summary["verifiedReceipts"] == 1


def test_create_timeout_holds_the_intent_and_prevents_duplicate_purchase(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    class LosesCreateResponse(FakeProviders):
        def request(self, method, url, headers, body, timeout):  # type: ignore[no-untyped-def]
            response = super().request(method, url, headers, body, timeout)
            if method == "POST" and url.endswith("/batches"):
                raise TimeoutError("create response was lost")
            return response

    server = LosesCreateResponse()
    with pytest.raises(TimeoutError, match="response was lost"):
        _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    attempt = _sidecar(run_dir)["jobs"][0]
    assert attempt["attemptState"] == "uncertain"
    assert attempt["state"] == "uncertain"
    assert attempt["jobId"] is None
    creates_before = sum(call["url"].endswith("/batches") for call in server.calls)
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    assert sum(call["url"].endswith("/batches") for call in server.calls) == creates_before
    assert len(_sidecar(run_dir)["jobs"]) == 1


@pytest.mark.parametrize("response_status", [400, 429])
def test_definite_create_rejection_releases_rows_for_a_new_attempt(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    response_status: int,
) -> None:
    class RejectsCreate(FakeProviders):
        def _route(self, method, url, headers, body):  # type: ignore[no-untyped-def]
            if method == "POST" and url.endswith("/batches"):
                return response_status, {}, _json({"error": {"status": response_status}})
            return super()._route(method, url, headers, body)

    rejected = RejectsCreate()
    with pytest.raises(qbatch.BatchCreateRejected, match=f"HTTP {response_status}"):
        _run(monkeypatch, rejected, run_dir, "batch-submit", "--families", "openai")
    first = _sidecar(run_dir)["jobs"][0]
    assert first["attemptState"] == "createRejected"
    assert first["state"] == "failed"
    assert qbatch.released(first)
    assert qbatch.committed_by_family(_sidecar(run_dir)) == {}
    rejection = first["createRejection"]
    assert rejection["responseStatus"] == response_status
    assert (run_dir / rejection["file"]).is_file()

    accepted = FakeProviders()
    assert _run(monkeypatch, accepted, run_dir, "batch-submit", "--families", "openai") == 0
    attempts = _sidecar(run_dir)["jobs"]
    assert [attempt["attemptOrdinal"] for attempt in attempts] == [1, 2]
    assert attempts[1]["attemptState"] == "submitted"


def test_server_error_create_response_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    class ServerErrorAfterCreateMayHaveCommitted(FakeProviders):
        def _route(self, method, url, headers, body):  # type: ignore[no-untyped-def]
            if method == "POST" and url.endswith("/batches"):
                return 500, {}, _json({"error": {"status": 500}})
            return super()._route(method, url, headers, body)

    server = ServerErrorAfterCreateMayHaveCommitted()
    with pytest.raises(qbatch.BatchError, match="HTTP 500"):
        _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    attempt = _sidecar(run_dir)["jobs"][0]
    assert attempt["attemptState"] == "uncertain"
    assert not qbatch.released(attempt)
    assert attempt["createRejection"] is None
    creates_before = sum(call["url"].endswith("/batches") for call in server.calls)

    assert _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai") == 0
    assert sum(call["url"].endswith("/batches") for call in server.calls) == creates_before
    assert len(_sidecar(run_dir)["jobs"]) == 1


def test_journal_only_intent_repairs_without_provider_io(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    original_write = qbatch.write_sidecar
    crashed = False

    def crash_before_intent_sidecar(path, payload):  # type: ignore[no-untyped-def]
        nonlocal crashed
        jobs = payload.get("jobs", ())
        if (
            not crashed
            and jobs
            and jobs[-1].get("attemptState") == "intent"
            and jobs[-1].get("inputFileId") is None
        ):
            crashed = True
            raise RuntimeError("crash after intent journal")
        return original_write(path, payload)

    monkeypatch.setattr(qbatch, "write_sidecar", crash_before_intent_sidecar)
    with pytest.raises(RuntimeError, match="intent journal"):
        _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    monkeypatch.setattr(qbatch, "write_sidecar", original_write)
    assert _sidecar(run_dir)["jobs"] == []
    calls_before = len(server.calls)

    assert _run(monkeypatch, server, run_dir, "batch-reconcile") == 0
    assert len(server.calls) == calls_before
    repaired = _sidecar(run_dir)["jobs"][0]
    assert repaired["attemptState"] == "preCreateReleased"
    assert qbatch.released(repaired)

    assert _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai") == 0
    assert [job["attemptOrdinal"] for job in _sidecar(run_dir)["jobs"]] == [1, 2]


def test_journal_only_upload_resumes_create_without_reuploading(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    original_event = qbatch._write_attempt_event
    crashed = False

    def crash_after_upload_event(path, job, *, phase):  # type: ignore[no-untyped-def]
        nonlocal crashed
        original_event(path, job, phase=phase)
        if phase == "uploaded" and not crashed:
            crashed = True
            raise RuntimeError("crash after uploaded journal")

    monkeypatch.setattr(qbatch, "_write_attempt_event", crash_after_upload_event)
    with pytest.raises(RuntimeError, match="uploaded journal"):
        _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    monkeypatch.setattr(qbatch, "_write_attempt_event", original_event)
    attempt_id = _sidecar(run_dir)["jobs"][0]["attemptId"]
    uploads_before = sum(call["url"].endswith("/files") for call in server.calls)
    creates_before = sum(call["url"].endswith("/batches") for call in server.calls)

    assert _run(monkeypatch, server, run_dir, "batch-reconcile") == 0
    assert sum(call["url"].endswith("/files") for call in server.calls) == uploads_before
    assert sum(call["url"].endswith("/batches") for call in server.calls) == creates_before + 1
    attempt = _sidecar(run_dir)["jobs"][0]
    assert attempt["attemptId"] == attempt_id
    assert attempt["attemptState"] == "submitted"


@pytest.mark.parametrize(
    "changed_context",
    ("rows", "workKind", "spendAuthority", "priorityProvenance"),
)
def test_uploaded_resume_rechecks_current_rows_and_governance_before_create(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    changed_context: str,
) -> None:
    server = FakeProviders()
    base_rows = _batch_rows_from_run(run_dir)
    rows = [
        qbatch.CandidateRow(
            row.candidate_id,
            row.pair,
            row.input_digest,
            rank,
        )
        for rank, row in enumerate(base_rows)
    ]
    ordered_ids = [row.candidate_id for row in rows]
    authority = {
        "authorityId": "urn:ref:test:resume-authority",
        "modelsByFamily": {"openai": OPENAI_MODEL},
    }
    provenance = _priority_provenance(ordered_ids)
    original_event = qbatch._write_attempt_event
    crashed = False

    def crash_after_upload_event(path, job, *, phase):  # type: ignore[no-untyped-def]
        nonlocal crashed
        original_event(path, job, phase=phase)
        if phase == "uploaded" and not crashed:
            crashed = True
            raise RuntimeError("crash after uploaded journal")

    monkeypatch.setattr(qbatch, "_write_attempt_event", crash_after_upload_event)
    with pytest.raises(RuntimeError, match="uploaded journal"):
        qbatch.submit(
            transport=server,
            receipts_path=run_dir / RUNNER.RECEIPTS,
            sidecar_path=run_dir / qbatch.SIDECAR,
            families=(qual.OPENAI_FAMILY,),
            keys={"openai": "offline-secret"},
            models={"openai": OPENAI_MODEL},
            rows=rows,
            protocol=qual.PROTOCOL,
            group_size=25,
            spend_authority=authority,
            priority_provenance=provenance,
        )
    monkeypatch.setattr(qbatch, "_write_attempt_event", original_event)

    current_rows = rows
    work_kind: qbatch.WorkKind = "validation"
    current_authority = authority
    current_provenance = provenance
    if changed_context == "rows":
        changed_pair = replace(
            rows[0].pair,
            source=replace(
                rows[0].pair.source,
                pref_label=rows[0].pair.source.pref_label + " changed",
            ),
        )
        current_rows = [replace(rows[0], pair=changed_pair), *rows[1:]]
    elif changed_context == "workKind":
        work_kind = "scoring"
    elif changed_context == "spendAuthority":
        current_authority = {
            **authority,
            "authorityId": "urn:ref:test:another-authority",
        }
    else:
        current_provenance = _priority_provenance(
            ordered_ids,
            score_digit="7",
        )

    creates_before = sum(
        call["method"] == "POST" and call["url"].endswith("/batches")
        for call in server.calls
    )
    with pytest.raises(qbatch.BatchError):
        qbatch.reconcile(
            transport=server,
            sidecar_path=run_dir / qbatch.SIDECAR,
            families={"openai": qual.OPENAI_FAMILY},
            keys={"openai": "offline-secret"},
            rows=current_rows,
            work_kind=work_kind,
            spend_authority=current_authority,
            priority_provenance=current_provenance,
        )
    assert sum(
        call["method"] == "POST" and call["url"].endswith("/batches")
        for call in server.calls
    ) == creates_before
    assert _sidecar(run_dir)["jobs"][0]["attemptState"] == "uploaded"


def test_submit_resume_rebuilds_current_rows_before_create(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    rows = _batch_rows_from_run(run_dir)
    original_event = qbatch._write_attempt_event
    crashed = False

    def crash_after_upload_event(path, job, *, phase):  # type: ignore[no-untyped-def]
        nonlocal crashed
        original_event(path, job, phase=phase)
        if phase == "uploaded" and not crashed:
            crashed = True
            raise RuntimeError("crash after uploaded journal")

    common = {
        "transport": server,
        "receipts_path": run_dir / RUNNER.RECEIPTS,
        "sidecar_path": run_dir / qbatch.SIDECAR,
        "families": (qual.OPENAI_FAMILY,),
        "keys": {"openai": "offline-secret"},
        "models": {"openai": OPENAI_MODEL},
        "rows": rows,
        "protocol": qual.PROTOCOL,
        "group_size": 25,
    }
    monkeypatch.setattr(qbatch, "_write_attempt_event", crash_after_upload_event)
    with pytest.raises(RuntimeError, match="uploaded journal"):
        qbatch.submit(**common)
    monkeypatch.setattr(qbatch, "_write_attempt_event", original_event)

    changed_pair = replace(
        rows[0].pair,
        target=replace(
            rows[0].pair.target,
            definition="current catalog definition changed",
        ),
    )
    changed_rows = [replace(rows[0], pair=changed_pair), *rows[1:]]
    creates_before = sum(
        call["method"] == "POST" and call["url"].endswith("/batches")
        for call in server.calls
    )
    with pytest.raises(qbatch.BatchError, match="does not reproduce"):
        qbatch.submit(**{**common, "rows": changed_rows})
    assert sum(
        call["method"] == "POST" and call["url"].endswith("/batches")
        for call in server.calls
    ) == creates_before
    assert _sidecar(run_dir)["jobs"][0]["attemptState"] == "uploaded"


@pytest.mark.parametrize(
    ("changed_cap", "message"),
    (
        ("selected", "batch spend cap cannot change after planning"),
        ("coordinated", "coordinated batch sidecars must use one spend cap"),
        ("missingTopLevel", "family spend caps do not match its plans"),
    ),
)
def test_uploaded_resume_validates_current_family_caps_before_create(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    changed_cap: str,
    message: str,
) -> None:
    server = FakeProviders()
    rows = _batch_rows_from_run(run_dir)
    scoring_sidecar = run_dir / RUNNER.SCORING_BATCH_SIDECAR
    original_event = qbatch._write_attempt_event
    crashed = False

    def crash_after_upload_event(path, job, *, phase):  # type: ignore[no-untyped-def]
        nonlocal crashed
        original_event(path, job, phase=phase)
        if phase == "uploaded" and not crashed:
            crashed = True
            raise RuntimeError("crash after uploaded journal")

    common = {
        "transport": server,
        "receipts_path": run_dir / RUNNER.RECEIPTS,
        "sidecar_path": run_dir / qbatch.SIDECAR,
        "families": (qual.OPENAI_FAMILY,),
        "keys": {"openai": "offline-secret"},
        "models": {"openai": OPENAI_MODEL},
        "rows": rows,
        "caps": {"openai": 10.0},
        "total_cap_usd": 20.0,
        "protocol": qual.PROTOCOL,
        "group_size": 25,
        "coordination_sidecars": (scoring_sidecar,),
    }
    monkeypatch.setattr(qbatch, "_write_attempt_event", crash_after_upload_event)
    with pytest.raises(RuntimeError, match="uploaded journal"):
        qbatch.submit(**common)
    monkeypatch.setattr(qbatch, "_write_attempt_event", original_event)

    resumed = dict(common)
    if changed_cap == "selected":
        resumed["caps"] = {"openai": 11.0}
    elif changed_cap == "coordinated":
        qbatch.write_sidecar(
            scoring_sidecar,
            {
                "batchPricingFactor": qbatch.BATCH_PRICE_FACTOR,
                "jobs": [],
                "plannedShards": [],
                "protocol": qbatch.SIDECAR_PROTOCOL,
                "spendCapsByFamily": {"openai": 11.0},
                "totalSpendCapUsd": 20.0,
            },
        )
    else:
        sidecar = _sidecar(run_dir)
        del sidecar["spendCapsByFamily"]
        qbatch.write_sidecar(run_dir / qbatch.SIDECAR, sidecar)

    creates_before = sum(
        call["method"] == "POST" and call["url"].endswith("/batches")
        for call in server.calls
    )
    with pytest.raises(qbatch.BatchError, match=message):
        if changed_cap == "coordinated":
            qbatch.reconcile(
                transport=server,
                sidecar_path=run_dir / qbatch.SIDECAR,
                families={"openai": qual.OPENAI_FAMILY},
                keys={"openai": "offline-secret"},
                rows=rows,
                work_kind="validation",
                coordination_sidecars=(scoring_sidecar,),
            )
        else:
            qbatch.submit(**resumed)
    assert sum(
        call["method"] == "POST" and call["url"].endswith("/batches")
        for call in server.calls
    ) == creates_before
    assert _sidecar(run_dir)["jobs"][0]["attemptState"] == "uploaded"


def test_reconcile_requires_one_coordinated_spend_authority_before_create(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    rows = _batch_rows_from_run(run_dir)
    scoring_rows = _batch_rows_from_run(run_dir, scoring=True)
    scoring_sidecar = run_dir / RUNNER.SCORING_BATCH_SIDECAR
    original_event = qbatch._write_attempt_event
    crashed = False

    def crash_after_upload_event(path, job, *, phase):  # type: ignore[no-untyped-def]
        nonlocal crashed
        original_event(path, job, phase=phase)
        if phase == "uploaded" and not crashed:
            crashed = True
            raise RuntimeError("crash after uploaded journal")

    authority = {"authorityId": "approved-campaign"}
    cap = 10.0
    monkeypatch.setattr(qbatch, "_write_attempt_event", crash_after_upload_event)
    with pytest.raises(RuntimeError, match="uploaded journal"):
        qbatch.submit(
            transport=server,
            receipts_path=run_dir / RUNNER.RECEIPTS,
            sidecar_path=run_dir / qbatch.SIDECAR,
            families=(qual.OPENAI_FAMILY,),
            keys={"openai": "offline-secret"},
            models={"openai": OPENAI_MODEL},
            rows=rows,
            caps={"openai": cap},
            total_cap_usd=cap,
            protocol=qual.PROTOCOL,
            group_size=25,
            coordination_sidecars=(scoring_sidecar,),
            spend_authority=authority,
        )
    monkeypatch.setattr(qbatch, "_write_attempt_event", original_event)

    qbatch.submit(
        transport=server,
        receipts_path=run_dir / RUNNER.SCORING_RECEIPTS,
        sidecar_path=scoring_sidecar,
        families=(qual.OPENAI_FAMILY,),
        keys={"openai": "offline-secret"},
        models={"openai": OPENAI_MODEL},
        rows=scoring_rows,
        caps={"openai": cap},
        total_cap_usd=cap,
        protocol=qual.SCORING_PROTOCOL,
        work_kind="scoring",
        group_size=25,
        spend_authority={"authorityId": "another-campaign"},
    )
    creates_before = sum(
        call["method"] == "POST" and call["url"].endswith("/batches")
        for call in server.calls
    )

    with pytest.raises(qbatch.BatchError, match="use one spend authority"):
        qbatch.reconcile(
            transport=server,
            sidecar_path=run_dir / qbatch.SIDECAR,
            families={"openai": qual.OPENAI_FAMILY},
            keys={"openai": "offline-secret"},
            rows=rows,
            work_kind="validation",
            coordination_sidecars=(scoring_sidecar,),
            spend_authority=authority,
        )
    assert sum(
        call["method"] == "POST" and call["url"].endswith("/batches")
        for call in server.calls
    ) == creates_before
    assert _sidecar(run_dir)["jobs"][0]["attemptState"] == "uploaded"


def test_reconcile_rechecks_coordinated_committed_spend_before_create(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    rows = _batch_rows_from_run(run_dir)
    scoring_rows = _batch_rows_from_run(run_dir, scoring=True)
    scoring_sidecar = run_dir / RUNNER.SCORING_BATCH_SIDECAR
    judge_cost = float(
        qbatch.request_plan_summary(
            qual.OPENAI_FAMILY,
            OPENAI_MODEL,
            rows,
            protocol=qual.PROTOCOL,
            work_kind="validation",
            group_size=25,
        )["projectedCostUsd"]
    )
    scoring_cost = float(
        qbatch.request_plan_summary(
            qual.OPENAI_FAMILY,
            OPENAI_MODEL,
            scoring_rows,
            protocol=qual.SCORING_PROTOCOL,
            work_kind="scoring",
            group_size=25,
        )["projectedCostUsd"]
    )
    cap = max(judge_cost, scoring_cost) + min(judge_cost, scoring_cost) * 0.75
    authority = {"authorityId": "approved-campaign"}
    original_event = qbatch._write_attempt_event
    crashed = False

    def crash_after_upload_event(path, job, *, phase):  # type: ignore[no-untyped-def]
        nonlocal crashed
        original_event(path, job, phase=phase)
        if phase == "uploaded" and not crashed:
            crashed = True
            raise RuntimeError("crash after uploaded journal")

    monkeypatch.setattr(qbatch, "_write_attempt_event", crash_after_upload_event)
    with pytest.raises(RuntimeError, match="uploaded journal"):
        qbatch.submit(
            transport=server,
            receipts_path=run_dir / RUNNER.RECEIPTS,
            sidecar_path=run_dir / qbatch.SIDECAR,
            families=(qual.OPENAI_FAMILY,),
            keys={"openai": "offline-secret"},
            models={"openai": OPENAI_MODEL},
            rows=rows,
            caps={"openai": cap},
            total_cap_usd=cap,
            protocol=qual.PROTOCOL,
            group_size=25,
            coordination_sidecars=(scoring_sidecar,),
            spend_authority=authority,
        )
    monkeypatch.setattr(qbatch, "_write_attempt_event", original_event)

    qbatch.submit(
        transport=server,
        receipts_path=run_dir / RUNNER.SCORING_RECEIPTS,
        sidecar_path=scoring_sidecar,
        families=(qual.OPENAI_FAMILY,),
        keys={"openai": "offline-secret"},
        models={"openai": OPENAI_MODEL},
        rows=scoring_rows,
        caps={"openai": cap},
        total_cap_usd=cap,
        protocol=qual.SCORING_PROTOCOL,
        work_kind="scoring",
        group_size=25,
        spend_authority=authority,
    )
    combined = qbatch.committed_by_family(_sidecar(run_dir))["openai"]
    combined += qbatch.committed_by_family(
        qbatch.read_sidecar(scoring_sidecar)
    )["openai"]
    assert combined > cap
    creates_before = sum(
        call["method"] == "POST" and call["url"].endswith("/batches")
        for call in server.calls
    )

    with pytest.raises(qbatch.BatchSpendCapReached, match="already committed"):
        qbatch.reconcile(
            transport=server,
            sidecar_path=run_dir / qbatch.SIDECAR,
            families={"openai": qual.OPENAI_FAMILY},
            keys={"openai": "offline-secret"},
            rows=rows,
            work_kind="validation",
            coordination_sidecars=(scoring_sidecar,),
            spend_authority=authority,
        )
    assert sum(
        call["method"] == "POST" and call["url"].endswith("/batches")
        for call in server.calls
    ) == creates_before
    assert _sidecar(run_dir)["jobs"][0]["attemptState"] == "uploaded"


def test_journal_only_created_job_repairs_without_a_second_create(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    original_event = qbatch._write_attempt_event
    crashed = False

    def crash_after_created_event(path, job, *, phase):  # type: ignore[no-untyped-def]
        nonlocal crashed
        original_event(path, job, phase=phase)
        if phase == "created" and not crashed:
            crashed = True
            raise RuntimeError("crash after created journal")

    monkeypatch.setattr(qbatch, "_write_attempt_event", crash_after_created_event)
    with pytest.raises(RuntimeError, match="created journal"):
        _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    monkeypatch.setattr(qbatch, "_write_attempt_event", original_event)
    assert _sidecar(run_dir)["jobs"][0]["jobId"] is None
    creates_before = sum(call["url"].endswith("/batches") for call in server.calls)

    assert _run(monkeypatch, server, run_dir, "batch-reconcile") == 0
    assert sum(call["url"].endswith("/batches") for call in server.calls) == creates_before
    attempt = _sidecar(run_dir)["jobs"][0]
    assert attempt["attemptState"] == "submitted"
    assert attempt["jobId"] in server.jobs


def test_exact_raw_result_bytes_are_pinned_and_tampering_blocks_bundle(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")
    artifact = _sidecar(run_dir)["jobs"][0]["resultArtifacts"][0]
    artifact_path = run_dir / artifact["file"]
    assert artifact_path.read_bytes() == next(
        payload for file_id, payload in server.files.items() if file_id == artifact["providerFileId"]
    )
    artifact_path.write_bytes(artifact_path.read_bytes() + b" ")

    with pytest.raises(SystemExit, match="provider request lineage failed"):
        RUNNER.main(["--output", str(run_dir), "bundle"])


def test_singleton_batch_receipt_requires_its_sidecar_at_bundle_time(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")
    (run_dir / qbatch.SIDECAR).rename(run_dir / "held-batch-sidecar.json")

    with pytest.raises(SystemExit, match="batch judging receipts require their batch sidecar"):
        RUNNER.main(["--output", str(run_dir), "bundle"])


def test_recomputed_aggregate_spend_rejects_sidecar_tampering(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")
    sidecar_path = run_dir / qbatch.SIDECAR
    sidecar = _sidecar(run_dir)
    sidecar["totalBatchAssumedCostUsd"] += 1
    sidecar_path.write_text(canonical_json(sidecar) + "\n", encoding="utf-8")

    with pytest.raises(qbatch.BatchError, match="committed total"):
        qbatch.verify_provider_batch_evidence(
            sidecar_path=sidecar_path,
            families=qual.VALIDATOR_FAMILIES,
            rows=_batch_rows_from_run(run_dir),
            receipts=_receipts(run_dir),
            work_kind="validation",
        )


def test_provider_create_echo_mismatch_retains_pollable_untrusted_job_identity(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    class EchoesAnotherInput(FakeProviders):
        def _route(self, method, url, headers, body):  # type: ignore[no-untyped-def]
            status, response_headers, payload = super()._route(method, url, headers, body)
            if method == "POST" and url.endswith("/batches"):
                parsed = json.loads(payload)
                parsed["input_file_id"] = "file-not-the-uploaded-shard"
                payload = _json(parsed)
            return status, response_headers, payload

    server = EchoesAnotherInput()
    with pytest.raises(qbatch.BatchError, match="echoed another input_file_id"):
        _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    attempt = _sidecar(run_dir)["jobs"][0]
    assert attempt["attemptState"] == "createMismatch"
    assert attempt["state"] == "uncertain"
    assert attempt["jobId"] in server.jobs
    assert attempt["statusEndpoint"].endswith(attempt["jobId"])

    creates = sum(call["url"].endswith("/batches") for call in server.calls)
    _run(monkeypatch, server, run_dir, "batch-status")
    attempt = _sidecar(run_dir)["jobs"][0]
    assert attempt["attemptState"] == "createMismatch"
    assert attempt["state"] == "pending"
    assert attempt["statusArtifacts"]
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    assert sum(call["url"].endswith("/batches") for call in server.calls) == creates

    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-cancel")
    assert _sidecar(run_dir)["jobs"][0]["state"] == "cancelling"
    with pytest.raises(qbatch.BatchError, match="untrusted create response"):
        _run(monkeypatch, server, run_dir, "batch-collect")
    assert _receipts(run_dir) == []


def test_run_reopen_recomputes_raw_provider_evidence_beyond_the_sidecar_pin(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")
    assert RUNNER.main(["--output", str(run_dir), "bundle"]) == 0
    run_path = run_dir / RUNNER.RUN_RECEIPT
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert qbatch.verify_run_provider_batch_evidence(run_path, run)["judging"][
        "verifiedReceipts"
    ] == len(_candidate_rows())

    artifact = _sidecar(run_dir)["jobs"][0]["resultArtifacts"][0]
    artifact_path = run_dir / artifact["file"]
    artifact_path.write_bytes(artifact_path.read_bytes() + b" ")
    with pytest.raises(qbatch.BatchError, match="artifact differs"):
        qbatch.verify_run_provider_batch_evidence(run_path, run)


def test_production_reopen_requires_every_receipt_to_be_raw_batch_backed() -> None:
    receipt_rows = (
        {"batch_execution_mode": "batch"},
        {"batch_execution_mode": "serial"},
    )
    with pytest.raises(
        qbatch.BatchError,
        match="must all reproduce from retained raw batch results",
    ):
        qbatch._require_complete_production_batch_receipts(
            {"coverageMode": qual.PRODUCTION_COVERAGE_MODE},
            evidence_name="judging",
            receipt_rows=receipt_rows,
            verification={"verifiedReceipts": 1},
        )

    qbatch._require_complete_production_batch_receipts(
        {"coverageMode": qual.PILOT_COVERAGE_MODE},
        evidence_name="judging",
        receipt_rows=receipt_rows,
        verification={"verifiedReceipts": 1},
    )


def test_aggregate_usage_is_linked_to_exact_raw_status_bytes(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    for provider_job in server.jobs.values():
        calls = int(provider_job["request_counts"]["total"])
        provider_job["usage"] = {
            "input_tokens": 500 * calls,
            "output_tokens": 120 * calls,
            "total_tokens": 620 * calls,
        }
    _run(monkeypatch, server, run_dir, "batch-collect")

    job = _sidecar(run_dir)["jobs"][0]
    status_pin = job["statusArtifacts"][-1]
    aggregate = job["aggregateUsage"]
    assert aggregate["statusArtifactDigest"] == status_pin["fileDigest"]
    assert aggregate["statusArtifactFile"] == status_pin["file"]
    assert aggregate["statusPollOrdinal"] == status_pin["pollOrdinal"]
    assert job["collection"]["usageStatus"] == "aggregateReported"
    raw_status = run_dir / status_pin["file"]
    assert raw_status.read_bytes() == _json(server.jobs[job["jobId"]])

    assert RUNNER.main(["--output", str(run_dir), "bundle"]) == 0
    run_path = run_dir / RUNNER.RUN_RECEIPT
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert qbatch.verify_run_provider_batch_evidence(run_path, run)["judging"][
        "statusArtifacts"
    ] == 1

    raw_status.write_bytes(raw_status.read_bytes() + b" ")
    with pytest.raises(qbatch.BatchError, match="artifact differs"):
        qbatch.verify_run_provider_batch_evidence(run_path, run)


def test_retained_status_controls_result_file_identity_not_sidecar_agreement(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")

    sidecar_path = run_dir / qbatch.SIDECAR
    sidecar = _sidecar(run_dir)
    job = sidecar["jobs"][0]
    fabricated_file_id = "file-fabricated-consistent-sidecar"
    fabricated_endpoint = (
        f"{qbatch.provider_for(qual.OPENAI_FAMILY).files_url}/"
        f"{fabricated_file_id}/content"
    )
    job["outputFileId"] = fabricated_file_id
    result_pin = next(
        pin for pin in job["resultArtifacts"] if pin["role"] == "output"
    )
    result_pin["providerFileId"] = fabricated_file_id
    result_pin["endpoint"] = fabricated_endpoint
    job["collection"]["downloadEndpoints"] = [fabricated_endpoint]
    sidecar_path.write_text(canonical_json(sidecar) + "\n", encoding="utf-8")

    with pytest.raises(qbatch.BatchError, match="output file identity differs from retained status"):
        qbatch.verify_provider_batch_evidence(
            sidecar_path=sidecar_path,
            families=qual.VALIDATOR_FAMILIES,
            rows=_batch_rows_from_run(run_dir),
            receipts=_receipts(run_dir),
            work_kind="validation",
        )


def test_terminal_status_without_usage_replaces_older_pending_usage(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    class ReturnsIncompleteResultUsage(FakeProviders):
        def _output_line(self, token: str, body: Mapping[str, Any]) -> dict[str, Any]:
            line = super()._output_line(token, body)
            line["response"]["body"]["usage"] = {"prompt_tokens": 500}
            return line

    server = ReturnsIncompleteResultUsage()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    provider_job = next(iter(server.jobs.values()))
    provider_job["usage"] = {
        "input_tokens": 1,
        "output_tokens": 1,
        "total_tokens": 2,
    }
    _run(monkeypatch, server, run_dir, "batch-status")
    pending = _sidecar(run_dir)["jobs"][0]
    assert pending["aggregateUsage"]["statusPollOrdinal"] == 1

    server.complete_jobs()
    provider_job.pop("usage")
    _run(monkeypatch, server, run_dir, "batch-collect")
    job = _sidecar(run_dir)["jobs"][0]
    assert len(job["statusArtifacts"]) == 2
    assert "aggregateUsage" not in job
    assert job["collection"]["usageStatus"] == "missing"
    assert job["collection"]["exactCostUsd"] is None
    assert job["collection"]["committedCostUsd"] == job["projectedCostUsd"]

    summary = qbatch.verify_provider_batch_evidence(
        sidecar_path=run_dir / qbatch.SIDECAR,
        families=qual.VALIDATOR_FAMILIES,
        rows=_batch_rows_from_run(run_dir),
        receipts=_receipts(run_dir),
        work_kind="validation",
    )
    assert summary["committedCostUsd"] == job["projectedCostUsd"]


@pytest.mark.parametrize(
    ("field", "fabricated", "message"),
    (
        (
            "requestCounts",
            {"completed": 99, "failed": 0, "total": 99},
            "request counts differ from retained status",
        ),
        (
            "completedAt",
            "2026-08-05T11:59:00Z",
            "completion time has no retained source",
        ),
    ),
)
def test_absent_status_fact_cannot_be_fabricated_in_the_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    field: str,
    fabricated: object,
    message: str,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    provider_job = next(iter(server.jobs.values()))
    provider_job.pop("request_counts")
    provider_job.pop("completed_at")
    families = {"openai": qual.OPENAI_FAMILY}
    keys = {"openai": "OPENAI-SECRET-VALUE"}
    qbatch.poll(
        transport=server,
        sidecar_path=run_dir / qbatch.SIDECAR,
        families=families,
        keys=keys,
    )

    sidecar_path = run_dir / qbatch.SIDECAR
    sidecar = _sidecar(run_dir)
    job = sidecar["jobs"][0]
    assert job["requestCounts"] == {}
    assert job["completedAt"] is None
    assert job["completedAtSource"] is None
    job[field] = fabricated
    sidecar_path.write_text(canonical_json(sidecar) + "\n", encoding="utf-8")

    with pytest.raises(qbatch.BatchError, match=message):
        qbatch.collect(
            transport=server,
            receipts_path=run_dir / RUNNER.RECEIPTS,
            sidecar_path=sidecar_path,
            families=families,
            keys=keys,
            rows=_batch_rows_from_run(run_dir),
            protocol=qual.PROTOCOL,
        )


def test_synthesized_completion_is_checkpointed_before_receipt_append(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    server.complete_jobs()
    for provider_job in server.jobs.values():
        provider_job.pop("completed_at", None)
    families = {"openai": qual.OPENAI_FAMILY}
    keys = {"openai": "OPENAI-SECRET-VALUE"}
    qbatch.poll(
        transport=server,
        sidecar_path=run_dir / qbatch.SIDECAR,
        families=families,
        keys=keys,
        now=lambda: "2026-08-05T10:00:00Z",
    )

    class InjectedCrash(RuntimeError):
        pass

    original_recompute = qbatch.recompute_sidecar_spend

    def crash_after_receipts(_sidecar: Mapping[str, Any]) -> tuple[list[dict[str, Any]], float]:
        raise InjectedCrash("after receipt append")

    monkeypatch.setattr(qbatch, "recompute_sidecar_spend", crash_after_receipts)
    with pytest.raises(InjectedCrash, match="after receipt append"):
        qbatch.collect(
            transport=server,
            receipts_path=run_dir / RUNNER.RECEIPTS,
            sidecar_path=run_dir / qbatch.SIDECAR,
            families=families,
            keys=keys,
            rows=_batch_rows_from_run(run_dir),
            protocol=qual.PROTOCOL,
            now=lambda: "2026-08-05T10:01:00Z",
        )
    first_receipts = (run_dir / RUNNER.RECEIPTS).read_bytes()
    checkpoint = _sidecar(run_dir)["jobs"][0]
    assert checkpoint["completedAt"] == "2026-08-05T10:01:00Z"
    assert checkpoint["completedAtSource"] == {"kind": "collectionCheckpoint"}
    assert checkpoint["collectedAt"] is None

    monkeypatch.setattr(qbatch, "recompute_sidecar_spend", original_recompute)
    summary = qbatch.collect(
        transport=server,
        receipts_path=run_dir / RUNNER.RECEIPTS,
        sidecar_path=run_dir / qbatch.SIDECAR,
        families=families,
        keys=keys,
        rows=_batch_rows_from_run(run_dir),
        protocol=qual.PROTOCOL,
        now=lambda: "2026-08-05T10:02:00Z",
    )
    assert summary["receiptsAppended"] == 0
    assert (run_dir / RUNNER.RECEIPTS).read_bytes() == first_receipts
    assert all(
        receipt["finished_at"] == "2026-08-05T10:01:00Z"
        for receipt in _receipts(run_dir)
    )


def test_scoring_and_judging_share_one_active_shard_per_family_model(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
) -> None:
    server = FakeProviders()
    _run(monkeypatch, server, run_dir, "batch-submit", "--families", "openai")
    creates = sum(call["url"].endswith("/batches") for call in server.calls)

    _run(monkeypatch, server, run_dir, "score-batch-submit", "--family", "openai")
    assert sum(call["url"].endswith("/batches") for call in server.calls) == creates
    scoring_sidecar = json.loads(
        (run_dir / RUNNER.SCORING_BATCH_SIDECAR).read_text(encoding="utf-8")
    )
    assert scoring_sidecar["plannedShards"]
    assert scoring_sidecar["jobs"] == []

    server.complete_jobs()
    _run(monkeypatch, server, run_dir, "batch-collect")
    _run(monkeypatch, server, run_dir, "score-batch-submit", "--family", "openai")
    scoring_sidecar = json.loads(
        (run_dir / RUNNER.SCORING_BATCH_SIDECAR).read_text(encoding="utf-8")
    )
    assert len(scoring_sidecar["jobs"]) == 1


def test_run_lock_prevents_concurrent_judging_and_scoring_provider_creates(
    run_dir: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    events = context.Queue()
    judging_sidecar = run_dir / qbatch.SIDECAR
    scoring_sidecar = run_dir / RUNNER.SCORING_BATCH_SIDECAR
    judging_rows = _batch_rows_from_run(run_dir)
    scoring_rows = [
        qbatch.CandidateRow(
            candidate_id=row.candidate_id,
            pair=row.pair,
            input_digest=qual.scoring_input_digest(row.pair),
        )
        for row in judging_rows
    ]
    workers = [
        context.Process(
            target=_concurrent_submit_worker,
            kwargs={
                "label": "judging",
                "run_root": str(run_dir),
                "sidecar_name": qbatch.SIDECAR,
                "coordination_name": RUNNER.SCORING_BATCH_SIDECAR,
                "receipts_name": RUNNER.RECEIPTS,
                "rows": judging_rows,
                "work_kind": "validation",
                "events": events,
            },
        ),
        context.Process(
            target=_concurrent_submit_worker,
            kwargs={
                "label": "scoring",
                "run_root": str(run_dir),
                "sidecar_name": RUNNER.SCORING_BATCH_SIDECAR,
                "coordination_name": qbatch.SIDECAR,
                "receipts_name": RUNNER.SCORING_RECEIPTS,
                "rows": scoring_rows,
                "work_kind": "scoring",
                "events": events,
            },
        ),
    ]

    # Queue both real processes behind the same kernel lock so contention does
    # not depend on scheduler timing.
    with qbatch._run_submit_lock(judging_sidecar, (scoring_sidecar,)):
        for worker in workers:
            worker.start()
        started = [events.get(timeout=15) for _worker in workers]
        assert {event[:2] for event in started} == {
            ("started", "judging"),
            ("started", "scoring"),
        }

    for worker in workers:
        worker.join(timeout=20)
        assert not worker.is_alive()
        assert worker.exitcode == 0
    completed = [events.get(timeout=10) for _ in range(3)]
    assert not [event for event in completed if event[0] == "error"]
    assert sum(int(event[2]) for event in completed if event[0] == "create") == 1
    assert sorted(int(event[2]) for event in completed if event[0] == "finished") == [0, 1]

    sidecars = [
        json.loads(judging_sidecar.read_text(encoding="utf-8")),
        json.loads(scoring_sidecar.read_text(encoding="utf-8")),
    ]
    jobs = [job for sidecar in sidecars for job in sidecar["jobs"]]
    assert len(jobs) == 1
    assert {(job["family"], job["modelId"]) for job in jobs} == {
        ("openai", OPENAI_MODEL)
    }


def test_poll_collect_and_cancel_share_the_submit_lock(
    run_dir: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_process_submit_lock,
        args=(str(run_dir), ready, release),
    )
    holder.start()
    assert ready.wait(timeout=15)
    server = FakeProviders()
    common = {
        "transport": server,
        "sidecar_path": run_dir / qbatch.SIDECAR,
        "families": {"openai": qual.OPENAI_FAMILY},
        "keys": {"openai": "offline-secret"},
        "lock_timeout_seconds": 0.01,
    }
    try:
        with pytest.raises(qbatch.BatchSubmitBusy):
            qbatch.poll(**common)
        with pytest.raises(qbatch.BatchSubmitBusy):
            qbatch.collect(
                **common,
                receipts_path=run_dir / RUNNER.RECEIPTS,
                rows=_batch_rows_from_run(run_dir),
                protocol=qual.PROTOCOL,
            )
        with pytest.raises(qbatch.BatchSubmitBusy):
            qbatch.cancel(**common)
    finally:
        release.set()
        holder.join(timeout=20)
    assert holder.exitcode == 0
    assert server.calls == []


@pytest.mark.parametrize(
    "operation",
    ("submit", "reconcile", "poll", "collect", "cancel"),
)
def test_waiting_scorer_mutation_rechecks_judging_seal_under_the_run_lock(
    run_dir: Path,
    operation: str,
) -> None:
    scoring_sidecar = run_dir / RUNNER.SCORING_BATCH_SIDECAR
    judging_sidecar = run_dir / qbatch.SIDECAR
    rows = _batch_rows_from_run(run_dir, scoring=True)
    qbatch.submit(
        transport=FakeProviders(),
        receipts_path=run_dir / RUNNER.SCORING_RECEIPTS,
        sidecar_path=scoring_sidecar,
        families=(qual.OPENAI_FAMILY,),
        keys={"openai": "offline-secret"},
        models={"openai": OPENAI_MODEL},
        rows=rows,
        protocol=qual.SCORING_PROTOCOL,
        work_kind="scoring",
        coordination_sidecars=(judging_sidecar,),
    )
    scoring_before = scoring_sidecar.read_bytes()
    context = multiprocessing.get_context("spawn")
    events = context.Queue()
    worker = context.Process(
        target=_queued_scoring_mutation_worker,
        kwargs={
            "run_root": str(run_dir),
            "operation": operation,
            "events": events,
        },
    )

    with qbatch._run_submit_lock(scoring_sidecar, (judging_sidecar,)):
        worker.start()
        assert events.get(timeout=15) == ("started", operation)
        judging_sidecar.write_text(
            canonical_json(
                {
                    "jobs": [],
                    "plannedShards": [{"shardId": "sealed-judging-plan"}],
                    "priorityProvenance": {
                        "priorityDigest": "sha256:" + "a" * 64
                    },
                    "protocol": qbatch.SIDECAR_PROTOCOL,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    worker.join(timeout=20)
    assert not worker.is_alive()
    assert worker.exitcode == 0
    result = events.get(timeout=10)
    assert result[:2] == ("blocked", operation)
    assert "sealed as judging priority provenance" in result[2]
    assert events.empty()
    assert scoring_sidecar.read_bytes() == scoring_before


def test_run_lock_times_out_with_retryable_error_and_refuses_symlinks(
    run_dir: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_process_submit_lock,
        args=(str(run_dir), ready, release),
    )
    holder.start()
    assert ready.wait(timeout=15)
    with (
        pytest.raises(qbatch.BatchSubmitBusy, match="retry after the active submit finishes"),
        qbatch._run_submit_lock(
            run_dir / qbatch.SIDECAR,
            (run_dir / RUNNER.SCORING_BATCH_SIDECAR,),
            timeout_seconds=0.01,
        ),
    ):
        raise AssertionError("a held run lock must not be entered")
    release.set()
    holder.join(timeout=20)
    assert holder.exitcode == 0

    lock_path = run_dir / qbatch.SUBMIT_LOCK_FILE
    lock_path.unlink()
    target = run_dir / "not-the-submit-lock"
    target.write_text("unsafe\n", encoding="utf-8")
    lock_path.symlink_to(target.name)
    with (
        pytest.raises(qbatch.BatchError, match="unavailable or unsafe"),
        qbatch._run_submit_lock(
            run_dir / qbatch.SIDECAR,
            (),
            timeout_seconds=0,
        ),
    ):
        raise AssertionError("a symlink lock must not be entered")
