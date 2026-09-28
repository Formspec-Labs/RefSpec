"""Qualification refuses wrong pins, incomplete fidelity and failed phases."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from refspec.atlas.parquet_artifact import file_sha256
from tools import qualify_atlas_release as qualification


@pytest.fixture(autouse=True)
def executable_checkout(tmp_path, monkeypatch):
    """Never mutate the shared checkout while exercising executable drift."""
    root = tmp_path / "checkout"
    files = {
        "tools/qualify_atlas_release.py": "# qualifier\n",
        "tools/read_source.py": "# reader\n",
        "src/refspec/reader.py": "# runtime\n",
        "src/refspec/data/schema.json": "{}",
        "bindings/atlas/3.1/tools/validate.py": "# validator\n",
        "bindings/atlas/3.1/shapes.ttl": "# shapes\n",
        "bindings/atlas/3.1/ontology.ttl": "# ontology\n",
        "bindings/atlas/3.1/requirements.txt": "rdflib==7.5.0\n",
        "pyproject.toml": "[project]\n",
        "uv.lock": "version = 1\n",
        ".python-version": "3.12\n",
        "head": "original-commit",
    }
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    monkeypatch.setattr(qualification, "ROOT", root)
    monkeypatch.setattr(qualification, "_source_commit", lambda path: (path / "head").read_text())
    monkeypatch.setattr(qualification, "_source_dirty", lambda path: True)
    return root


def _fixture(tmp_path):
    distribution, full, agency = (tmp_path / name for name in ("distribution", "full", "agency"))
    for path in (distribution, full, agency):
        path.mkdir()
    (distribution / "atlas-manifest.json").write_text("{}")
    distribution_pin = file_sha256(distribution / "atlas-manifest.json")
    (full / "view-manifest.json").write_text(json.dumps({"input": {"manifestSha256": distribution_pin}}))
    (agency / "view-manifest.json").write_text("{}")
    evidence, review = tmp_path / "evidence.json", tmp_path / "review.json"
    evidence.write_text("{}")
    review.write_text("{}")
    return SimpleNamespace(
        distribution=distribution,
        distribution_manifest_sha256=distribution_pin,
        full_view=full,
        full_view_manifest_sha256=file_sha256(full / "view-manifest.json"),
        compact_view=tmp_path / "compact",
        report_root=tmp_path / "qualification",
        agency_view=agency,
        agency_view_manifest_sha256=file_sha256(agency / "view-manifest.json"),
        agency_audit_evidence_manifest=evidence,
        agency_audit_evidence_sha256=file_sha256(evidence),
        agency_review_receipt=review,
        agency_review_receipt_sha256=file_sha256(review),
        source_root=tmp_path / "sources",
        memory_gib=30,
        phase_timeout_seconds=60,
        total_timeout_seconds=3600,
        cgroup_parent=None,
        swap_gib=0,
    )


def _fidelity(pin):
    return {
        "comparisons": [
            json.loads(
                (Path(__file__).parent / "fixtures/atlas_release_qualification/agency-comparison.json").read_text()
            )["comparison"]
        ],
        "expectations": {"requireCompleteCoverage": True, "requireInputPins": True, "requirePackPins": True},
        "passed": True,
        "manifestDigest": pin,
        "scope": {"complete": True, "scopedOutUnits": [], "scopedOutComparisons": []},
        "coverage": {
            "constructionUnitCount": 1,
            "exactUnitCount": 1,
            "uncoveredUnits": [],
            "constructionUnits": [{"key": "agency-registry-2026-09-26", "status": "exact"}],
        },
    }


def _runner(args, calls, *, fail=None, scoped=False, mutate_pin=False):
    def run(command, **kwargs):
        name = kwargs["name"]
        calls.append((name, command, kwargs))
        if name == "publisher-fidelity":
            payload = _fidelity(args.distribution_manifest_sha256)
            if scoped:
                payload["scope"]["scopedOutUnits"] = ["missing"]
            Path(command[command.index("--output") + 1]).write_text(json.dumps(payload))
        if name == "build-compact-view":
            args.compact_view.mkdir()
            (args.compact_view / "search-view-manifest.json").write_text("{}")
        if mutate_pin:
            (args.distribution / "atlas-manifest.json").write_text('{"changed":true}')
        return {"status": "command-failed" if name == fail else "passed", "log": str(kwargs["report"])}

    return run


def test_complete_sequence_copies_binding_and_uses_audit(tmp_path):
    args, calls = _fixture(tmp_path), []
    result = qualification.qualify(args, phase_runner=_runner(args, calls))
    assert result["status"] == "passed", result
    assert [row[0] for row in calls] == [
        "pack-inventory",
        "standalone-audit",
        "verify-agency-view",
        "publisher-fidelity",
        "full-view",
        "build-compact-view",
        "verify-compact-view",
    ]
    audit = calls[1]
    assert "--no-project" in audit[1] and "--cache-dir" not in audit[1]
    assert str(args.report_root / "standalone-binding/tools/validate.py") in audit[1]
    assert all(options["env"]["REFSPEC_ATLAS_VALIDATION_MODE"] == "audit" for _, _, options in calls)
    assert "--only" not in calls[3][1]


def test_phases_share_one_total_budget_and_its_end_leaves_a_receipt(tmp_path, monkeypatch):
    args, calls = _fixture(tmp_path), []
    args.total_timeout_seconds = 100
    clock = [0.0]
    monkeypatch.setattr(qualification.time, "monotonic", lambda: clock[0])
    run = _runner(args, calls)

    def slow(command, **kwargs):
        clock[0] += 50
        return run(command, **kwargs)

    result = qualification.qualify(args, phase_runner=slow)
    assert [options["timeout_seconds"] for _, _, options in calls] == [60, 50]
    assert result["status"] == "incomplete" and "budget is spent" in result["error"]
    assert json.loads((args.report_root / "qualification.json").read_text())["totalTimeoutSeconds"] == 100


def test_main_turns_sigterm_and_sigint_into_a_written_receipt(tmp_path, monkeypatch):
    import signal

    installed = {}
    monkeypatch.setattr(qualification.signal, "signal", lambda signum, handler: installed.setdefault(signum, handler))
    monkeypatch.setattr(qualification, "qualify", lambda args: {"status": "passed"})
    qualification.main(
        [
            *("--distribution", "d", "--distribution-manifest-sha256", "x", "--full-view", "f"),
            *("--full-view-manifest-sha256", "x", "--compact-view", "c", "--report-root", "r"),
            *("--agency-view-manifest-sha256", "x", "--agency-audit-evidence-manifest", "e"),
            *("--agency-audit-evidence-sha256", "x", "--agency-review-receipt", "v"),
            *("--agency-review-receipt-sha256", "x"),
        ]
    )
    assert installed == {signal.SIGTERM: qualification._interrupted, signal.SIGINT: qualification._interrupted}


def test_an_interrupt_during_a_phase_still_writes_the_receipt(tmp_path):
    args, calls = _fixture(tmp_path), []
    run = _runner(args, calls)

    def interrupted(command, **kwargs):
        if kwargs["name"] == "standalone-audit":
            qualification._interrupted(15, None)
        return run(command, **kwargs)

    with pytest.raises(KeyboardInterrupt):
        qualification.qualify(args, phase_runner=interrupted)
    receipt = json.loads((args.report_root / "qualification.json").read_text())
    assert receipt["status"] == "incomplete" and receipt["error"] == "KeyboardInterrupt: signal 15"


@pytest.mark.parametrize(
    "failed_phase", ["pack-inventory", "standalone-audit", "publisher-fidelity", "full-view", "verify-compact-view"]
)
def test_failed_phase_stops_qualification(tmp_path, failed_phase):
    args, calls = _fixture(tmp_path), []
    result = qualification.qualify(args, phase_runner=_runner(args, calls, fail=failed_phase))
    assert result["status"] != "passed"
    assert calls[-1][0] == failed_phase
    assert (args.report_root / "qualification.json").is_file()


def test_scoped_fidelity_does_not_qualify_even_if_command_succeeds(tmp_path):
    args, calls = _fixture(tmp_path), []
    result = qualification.qualify(args, phase_runner=_runner(args, calls, scoped=True))
    assert result["status"] != "passed"
    assert calls[-1][0] == "publisher-fidelity"


def test_changed_input_during_phase_fails_before_next_command(tmp_path):
    args, calls = _fixture(tmp_path), []
    result = qualification.qualify(args, phase_runner=_runner(args, calls, mutate_pin=True))
    assert result["status"] != "passed"
    assert len(calls) == 1


def test_wrong_manifest_pin_prevents_all_commands(tmp_path):
    args, calls = _fixture(tmp_path), []
    args.distribution_manifest_sha256 = "sha256:" + "0" * 64
    result = qualification.qualify(args, phase_runner=_runner(args, calls))
    assert result["status"] != "passed"
    assert not calls


def test_full_view_from_other_distribution_is_refused(tmp_path):
    args, calls = _fixture(tmp_path), []
    (args.full_view / "view-manifest.json").write_text('{"input":{"manifestSha256":"other"}}')
    args.full_view_manifest_sha256 = file_sha256(args.full_view / "view-manifest.json")
    result = qualification.qualify(args, phase_runner=_runner(args, calls))
    assert result["status"] != "passed"
    assert not calls


@pytest.mark.parametrize("input_name", ["distribution", "full_view", "agency_view"])
def test_compact_output_cannot_change_a_previously_verified_artifact(tmp_path, input_name):
    args, calls = _fixture(tmp_path), []
    args.compact_view = getattr(args, input_name) / "compact"
    with pytest.raises(ValueError, match="overlap"):
        qualification.qualify(args, phase_runner=_runner(args, calls))
    assert not calls


@pytest.mark.parametrize(
    "relative",
    [
        "tools/read_source.py",
        "src/refspec/reader.py",
        "src/refspec/data/schema.json",
        "bindings/atlas/3.1/tools/validate.py",
        "bindings/atlas/3.1/shapes.ttl",
        "bindings/atlas/3.1/ontology.ttl",
        "bindings/atlas/3.1/requirements.txt",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "head",
        "copied-shapes",
    ],
)
def test_executable_change_during_phase_refuses_qualification(tmp_path, executable_checkout, relative):
    args, calls = _fixture(tmp_path), []
    runner = _runner(args, calls)

    def mutate(command, **kwargs):
        record = runner(command, **kwargs)
        path = (
            args.report_root / "standalone-binding/shapes.ttl"
            if relative == "copied-shapes"
            else executable_checkout / relative
        )
        path.write_text(path.read_text() + "changed")
        return record

    result = qualification.qualify(args, phase_runner=mutate)
    assert result["status"] == "incomplete"
    assert "changed" in result["error"]
    assert len(calls) == 1
    assert result["sourceCommit"] == "original-commit"
    assert result["sourceDirty"] is True
    if relative == "copied-shapes":
        assert result["executableInputDigests"]["standalone-binding/shapes.ttl"] == file_sha256(
            executable_checkout / "bindings/atlas/3.1/shapes.ttl"
        )


@pytest.mark.parametrize("operation", ["add", "delete"])
def test_executable_membership_change_is_refused(tmp_path, executable_checkout, operation):
    args, calls = _fixture(tmp_path), []
    runner = _runner(args, calls)

    def mutate(command, **kwargs):
        record = runner(command, **kwargs)
        if operation == "add":
            (executable_checkout / "tools/new_reader.py").write_text("# added\n")
        else:
            (executable_checkout / "tools/read_source.py").unlink()
        return record

    result = qualification.qualify(args, phase_runner=mutate)
    assert result["status"] == "incomplete"
    assert "executable inputs changed" in result["error"]
    assert len(calls) == 1


def test_executable_change_before_first_phase_prevents_launch(tmp_path, executable_checkout, monkeypatch):
    args, calls = _fixture(tmp_path), []
    copytree = qualification.shutil.copytree

    def mutate_after_copy(*arguments, **options):
        result = copytree(*arguments, **options)
        (executable_checkout / "src/refspec/reader.py").write_text("changed")
        return result

    monkeypatch.setattr(qualification.shutil, "copytree", mutate_after_copy)
    result = qualification.qualify(args, phase_runner=_runner(args, calls))
    assert result["status"] == "incomplete"
    assert "executable inputs changed" in result["error"]
    assert not calls


def test_unrelated_docs_and_generated_binding_fixtures_do_not_interrupt(tmp_path, executable_checkout):
    args, calls = _fixture(tmp_path), []
    runner = _runner(args, calls)

    def mutate_ignored(command, **kwargs):
        record = runner(command, **kwargs)
        for relative in (
            "docs/notes.md",
            "bindings/atlas/3.1/README.md",
            "bindings/atlas/3.1/valid/generated.nq",
            "src/refspec/__pycache__/reader.pyc",
        ):
            path = executable_checkout / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("generated or documented")
        return record

    result = qualification.qualify(args, phase_runner=mutate_ignored)
    assert result["status"] == "passed", result
    assert result["sourceDirty"] is True
    assert "src/refspec/data/schema.json" in result["executableInputDigests"]


def test_retained_agency_schema_qualifies_without_invented_top_level_field(tmp_path):
    receipt = _fidelity("sha256:" + "a" * 64)
    assert "independentAgencyComparison" not in receipt
    assert receipt["comparisons"][0]["claimScope"]["independentAgencyComparison"]["status"] == "passed"
    path = tmp_path / "fidelity.json"
    path.write_text(json.dumps(receipt))
    assert qualification.require_complete_fidelity(path, receipt["manifestDigest"]) == receipt


@pytest.mark.parametrize(
    "field,value",
    [
        ("comparisons", None),
        ("comparisons", {}),
        ("comparisons", []),
        ("comparisons", [None]),
        ("coverage", []),
        ("scope", []),
        ("expectations", []),
    ],
)
def test_malformed_receipt_container_is_refused(tmp_path, field, value):
    receipt = _fidelity("pin")
    receipt[field] = value
    # A fabricated legacy field must never substitute for the emitted comparison.
    receipt["independentAgencyComparison"] = {"status": "passed"}
    path = tmp_path / "fidelity.json"
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="publisher fidelity"):
        qualification.require_complete_fidelity(path, "pin")


@pytest.mark.parametrize(
    "path,value",
    [
        (("comparisons", 0, "name"), "other"),
        (("comparisons", 0, "publisherReader"), "other"),
        (("comparisons", 0, "releaseKeys"), ["other"]),
        (("comparisons", 0, "kind"), "other"),
        (("comparisons", 0, "publisherLoaded"), False),
        (("comparisons", 0, "atlasLoaded"), False),
        (("comparisons", 0, "fidelityStatus"), "not-evaluated"),
        (("comparisons", 0, "claimScope"), None),
        (("comparisons", 0, "claimScope"), []),
        (("comparisons", 0, "claimScope", "status"), "not-evaluated"),
        (("comparisons", 0, "claimScope", "independentAgencyComparison"), None),
        (("comparisons", 0, "claimScope", "independentAgencyComparison"), []),
        (("comparisons", 0, "claimScope", "independentAgencyComparison", "status"), "unevaluated"),
        (("comparisons", 0, "claimScope", "independentAgencyComparison", "status"), "failed"),
        (("comparisons", 0, "claimScope", "independentAgencyComparison", "failures"), ["mismatch"]),
        (("coverage", "constructionUnits", 0, "key"), "other"),
        (("coverage", "constructionUnits", 0, "status"), "not-evaluated"),
        (("coverage", "constructionUnitCount"), 2),
        (("coverage", "constructionUnitCount"), True),
        (("coverage", "exactUnitCount"), True),
        (("coverage", "constructionUnits"), [None]),
        (("scope", "scopedOutUnits"), ["other"]),
        (("scope", "scopedOutComparisons"), ["other"]),
        (("scope", "complete"), False),
        (("coverage", "uncoveredUnits"), ["other"]),
        (("expectations", "requireInputPins"), False),
        (("manifestDigest",), "other"),
        (("passed",), False),
    ],
)
def test_required_agency_and_coverage_conditions_fail_closed(tmp_path, path, value):
    receipt = _fidelity("pin")
    target = receipt
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    output = tmp_path / "fidelity.json"
    output.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="publisher fidelity"):
        qualification.require_complete_fidelity(output, "pin")


@pytest.mark.parametrize("duplicate", ["agency", "unit"])
def test_duplicate_agency_or_coverage_entry_is_refused(tmp_path, duplicate):
    receipt = _fidelity("pin")
    if duplicate == "agency":
        receipt["comparisons"] *= 2
    else:
        receipt["coverage"]["constructionUnits"] *= 2
        receipt["coverage"].update(constructionUnitCount=2, exactUnitCount=2)
    output = tmp_path / "fidelity.json"
    output.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="publisher fidelity"):
        qualification.require_complete_fidelity(output, "pin")
