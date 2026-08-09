"""Acceptance gate for the executable current-module registry audit."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUDIT_TOOL = REPOSITORY_ROOT / "tools" / "verify_registry_audit.py"
MANIFEST_TOOL = REPOSITORY_ROOT / "tools" / "build_registry_source_manifest.py"
AUDIT_SUMMARY = REPOSITORY_ROOT / "research" / "evidence" / "registry-real-data-audit-2026-08-03" / "summary.json"
SOURCE_MANIFEST = AUDIT_SUMMARY.with_name("sources.json")

_SPEC = importlib.util.spec_from_file_location("refspec_registry_audit", AUDIT_TOOL)
assert _SPEC is not None and _SPEC.loader is not None
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)

_MANIFEST_SPEC = importlib.util.spec_from_file_location("refspec_registry_manifest", MANIFEST_TOOL)
assert _MANIFEST_SPEC is not None and _MANIFEST_SPEC.loader is not None
manifest_builder = importlib.util.module_from_spec(_MANIFEST_SPEC)
_MANIFEST_SPEC.loader.exec_module(manifest_builder)

_RECEIPT_PLUGIN = REPOSITORY_ROOT / "tools" / "registry_real_data_pytest_plugin.py"
_PLUGIN_SPEC = importlib.util.spec_from_file_location("refspec_registry_receipt_plugin", _RECEIPT_PLUGIN)
assert _PLUGIN_SPEC is not None and _PLUGIN_SPEC.loader is not None
receipt_plugin = importlib.util.module_from_spec(_PLUGIN_SPEC)
_PLUGIN_SPEC.loader.exec_module(receipt_plugin)


def _publisher_reader_manifest(*descriptors: dict) -> dict:
    return {
        "modules": [
            {
                "module": "example_reader.py",
                "auditRole": "dataReader",
                "coveredBy": [],
                "sourceStatus": "publisherBytes",
                "testInputs": list(descriptors),
            }
        ]
    }


def _receipts(*executions: dict) -> dict:
    return {
        "format": "refspec-registry-execution-receipts/v1",
        "modules": [{"module": "example_reader.py", "executions": list(executions)}],
    }


def _execution(*, digests: list[str], counts: dict[str, int]) -> dict:
    return {
        "function": "parse_example",
        "counts": counts,
        "shape": {"type": "mapping", "count": 1},
        "sample": {"records": [{"code": "A"}]},
        "sourceEvidence": {
            "digests": digests,
            "byteLengths": [10],
            "paths": [],
            "urls": ["https://publisher.example/data.json"],
        },
    }


def test_registry_audit_snapshot_is_current_and_honest_about_open_gaps() -> None:
    """Keep the default suite green while preserving the separate red acceptance gate."""

    payload = json.loads(AUDIT_SUMMARY.read_text(encoding="utf-8"))
    sources = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    rows = tuple(sources["modules"])

    assert payload["format"] == "refspec-registry-audit-summary/v1"
    assert sources["format"] == "refspec-registry-source-links/v1"
    assert sources == manifest_builder.build_manifest(REPOSITORY_ROOT)
    assert payload["modules"] == sources["modules"]
    current_modules = set(audit.registry_modules(REPOSITORY_ROOT))
    assert sources["moduleCount"] == len(current_modules)
    assert {row["module"] for row in sources["modules"]} == current_modules
    assert all(isinstance(row["declaredUrls"], list) for row in sources["modules"])
    publisher_inputs = [
        publisher_input
        for row in sources["modules"]
        for input_descriptor in row["testInputs"]
        for publisher_input in (
            input_descriptor.get("members", [])
            if input_descriptor.get("kind") == "sourceCollection"
            else [input_descriptor]
        )
    ]
    assert all(
        input_descriptor["publisherUrl"].startswith(("http://", "https://"))
        and input_descriptor["sha256"].startswith("sha256:")
        and input_descriptor["byteLength"] > 0
        for input_descriptor in publisher_inputs
    )
    assert payload["execution"]["failures"] == 0
    assert payload["execution"]["errors"] == 0
    audit.verify_inventory(REPOSITORY_ROOT, rows)
    audit.direct_test_paths(REPOSITORY_ROOT, rows)
    expected_failures = (
        *audit.real_data_evidence_failures(rows),
        *audit.execution_receipt_failures(sources, payload["executionReceipts"]),
    )
    assert payload["realDataGate"] == {
        "status": "failed" if expected_failures else "passed",
        "failures": list(expected_failures),
    }
    assert all(
        row["testInputs"]
        for row in rows
        if row["auditRole"] == "dataReader" and row["sourceStatus"] == "publisherBytes"
    )


def test_gao_fedrules_reference_page_is_not_a_required_package_receipt() -> None:
    """The package uses the search form; the scalar FedRules page is supporting evidence."""

    manifest = manifest_builder.build_manifest(REPOSITORY_ROOT)
    row = next(module for module in manifest["modules"] if module["module"] == "gao_cra_facets.py")
    inputs = {descriptor["name"]: descriptor for descriptor in row["testInputs"]}

    assert inputs["gaoCraDatabase"].get("receiptRequired", True) is True
    assert inputs["gaoFedRulesRecord"]["receiptRequired"] is False


def test_registry_audit_inventory_includes_nested_runtime_modules() -> None:
    modules = set(audit.registry_modules(REPOSITORY_ROOT))
    manifest = manifest_builder.build_manifest(REPOSITORY_ROOT)

    # Derived, not hardcoded: a literal count fails on every added module without
    # saying anything, while this catches the drift that actually matters.
    assert modules == {row["module"] for row in manifest["modules"]}
    assert "adapters/crs_zyte.py" in modules
    assert "infrastructure/pinned_acquisition.py" in modules
    assert "infrastructure/rdf_claim_export.py" in modules
    assert "infrastructure/registry_claim_release.py" in modules
    assert "infrastructure/semantic_foundation.py" in modules
    assert "infrastructure/source_concept_release.py" in modules
    assert "managed_releases/icpsr_managed_release.py" in modules
    assert "packages/federal_register_topics_package.py" in modules
    assert "packages/crs_source_concept_releases.py" in modules
    assert not any(module.endswith("/__init__.py") for module in modules)


def test_nested_data_paths_name_real_inputs_and_measured_coverage() -> None:
    manifest = manifest_builder.build_manifest(REPOSITORY_ROOT)
    by_module = {row["module"]: row for row in manifest["modules"]}

    for module in manifest_builder.NESTED_MODULE_AUDIT:
        row = by_module[module]
        if row["auditRole"] == "support":
            assert row["sourceStatus"] == "notApplicable"
            continue
        assert row["sourceStatus"] == "publisherBytes"
        assert row["testInputs"]
        assert row["coveredBy"]
        publisher_inputs = [
            publisher_input
            for item in row["testInputs"]
            for publisher_input in (item.get("members", []) if item.get("kind") == "sourceCollection" else [item])
        ]
        assert all(item["publisherUrl"].startswith("https://") for item in publisher_inputs)


def test_treasury_manifest_requires_counts_from_the_workbook_not_its_description_page() -> None:
    manifest = manifest_builder.build_manifest(REPOSITORY_ROOT)
    treasury = next(row for row in manifest["modules"] if row["module"] == "treasury_tas_fast_book.py")
    by_name = {item["name"]: item for item in treasury["testInputs"]}

    assert by_name["treasuryFastBook"]["receiptRequired"] is False
    assert by_name["treasuryFastBookPartIIIII"].get("receiptRequired", True) is True
    assert by_name["treasuryFastBookPartIIIII"]["sha256"] == (
        "sha256:0e40902a2e4bfee7439fbe24d90fd9ff39fad859b4ba432725256866b06cb461"
    )


def test_materializer_rejects_paths_outside_refspec(tmp_path: Path) -> None:
    manifest = {
        "modules": [
            {
                "testInputs": [
                    {
                        "name": "naics2022Xlsx",
                        "localPath": "../outside.xlsx",
                        "sha256": "sha256:" + "0" * 64,
                        "byteLength": 1,
                    }
                ]
            }
        ]
    }

    with pytest.raises(audit.RegistryAuditError, match="RefSpec-owned relative path"):
        audit.materialize_test_inputs(tmp_path, manifest)


def test_materializer_rejects_local_bytes_that_drift_from_the_pin(tmp_path: Path) -> None:
    source = tmp_path / "output" / "input.xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"wrong")
    manifest = {
        "modules": [
            {
                "testInputs": [
                    {
                        "name": "naics2022Xlsx",
                        "localPath": "output/input.xlsx",
                        "sha256": "sha256:" + "0" * 64,
                        "byteLength": len(b"wrong"),
                    }
                ]
            }
        ]
    }

    with pytest.raises(audit.RegistryAuditError, match="digest drift"):
        audit.materialize_test_inputs(tmp_path, manifest)


def test_full_suite_uses_the_same_manifest_input_environment_as_qualification() -> None:
    assert audit._test_input_environment(
        {
            "ecfrTitles": "/repo/ecfr-titles.json",
            "unrecognizedInput": "/repo/ignored.json",
        }
    ) == {"REFSPEC_ECFR_TITLES_PATH": "/repo/ecfr-titles.json"}


def test_receipt_gate_requires_each_pin_and_parsed_counts_in_the_same_execution() -> None:
    pin = "sha256:" + "1" * 64
    manifest = _publisher_reader_manifest({"sha256": pin, "receiptRequired": True})
    receipts = _receipts(
        _execution(digests=[pin], counts={}),
        _execution(digests=["sha256:" + "2" * 64], counts={"records": 3}),
    )

    failures = audit.execution_receipt_failures(manifest, receipts)

    assert any("same execution" in failure and pin in failure for failure in failures)


def test_receipt_gate_allows_reference_only_secondary_pin_without_collection_counts() -> None:
    primary = "sha256:" + "1" * 64
    reference = "sha256:" + "2" * 64
    manifest = _publisher_reader_manifest(
        {"sha256": primary, "receiptRequired": True},
        {"sha256": reference, "receiptRequired": False},
    )
    receipts = _receipts(
        _execution(digests=[primary], counts={"observations": 6}),
        _execution(digests=[reference], counts={}),
    )

    assert audit.execution_receipt_failures(manifest, receipts) == ()


def test_receipt_gate_rejects_gap_only_counts_as_substantive_output() -> None:
    pin = "sha256:" + "3" * 64
    manifest = _publisher_reader_manifest({"sha256": pin, "receiptRequired": True})

    failures = audit.execution_receipt_failures(
        manifest,
        _receipts(_execution(digests=[pin], counts={"gaps": 4, "blockers": 1})),
    )

    assert any("substantive" in failure and pin in failure for failure in failures)


def test_receipt_gate_checks_collection_capture_and_member_pins() -> None:
    capture = "sha256:" + "4" * 64
    member_a = "sha256:" + "5" * 64
    member_b = "sha256:" + "6" * 64
    manifest = _publisher_reader_manifest(
        {
            "kind": "sourceCollection",
            "captureDigest": capture,
            "receiptRequired": True,
            "members": [{"sha256": member_a}, {"sha256": member_b}],
        }
    )

    assert (
        audit.execution_receipt_failures(
            manifest,
            _receipts(_execution(digests=[capture, member_a, member_b], counts={"concepts": 7})),
        )
        == ()
    )

    failures = audit.execution_receipt_failures(
        manifest,
        _receipts(_execution(digests=[capture, member_a], counts={"concepts": 7})),
    )
    assert any(member_b in failure for failure in failures)


def test_receipt_collector_preserves_distinct_pinned_inputs() -> None:
    receipt_plugin._MODULES["example"] = {"module": "example.py", "executions": []}
    payloads = [f"publisher payload {index}".encode() for index in range(5)]

    for payload in payloads:
        receipt_plugin._record(
            "example",
            "parse_example",
            (payload, "https://publisher.example/data"),
            {"records": [{"value": payload.decode()}]},
        )

    executions = receipt_plugin._MODULES["example"]["executions"]
    retained_digests = {digest for execution in executions for digest in execution["sourceEvidence"]["digests"]}
    assert retained_digests == {"sha256:" + hashlib.sha256(payload).hexdigest() for payload in payloads}


def test_receipt_collector_prefers_publisher_location_for_the_same_pin() -> None:
    receipt_plugin._MODULES["example"] = {"module": "example.py", "executions": []}
    payload = b"same real publisher bytes"
    result = {"records": [{"code": "A"}]}

    receipt_plugin._record(
        "example",
        "parse_example",
        (payload, "https://example.test/copied-fixture"),
        result,
    )
    receipt_plugin._record(
        "example",
        "parse_example",
        (payload, "https://publisher.example/data"),
        result,
    )

    executions = receipt_plugin._MODULES["example"]["executions"]
    assert len(executions) == 1
    assert executions[0]["sourceEvidence"]["urls"] == ["https://publisher.example/data"]


def test_receipt_collector_records_only_the_outer_production_call() -> None:
    receipt_plugin._MODULES["example"] = {"module": "example.py", "executions": []}
    payload = b"publisher bytes"

    def inner(value: bytes) -> dict:
        return {"records": [{"value": value.decode()}]}

    def outer(value: bytes) -> dict:
        return receipt_plugin._call_and_record("example", "inner", inner, (value,), {})

    result = receipt_plugin._call_and_record("example", "outer", outer, (payload,), {})

    assert result == {"records": [{"value": "publisher bytes"}]}
    assert [execution["function"] for execution in receipt_plugin._MODULES["example"]["executions"]] == ["outer"]
