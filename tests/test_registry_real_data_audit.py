"""Acceptance gate for the executable current-module registry audit."""

from __future__ import annotations

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
    assert all(
        input_descriptor["publisherUrl"].startswith(("http://", "https://"))
        and input_descriptor["sha256"].startswith("sha256:")
        and input_descriptor["byteLength"] > 0
        for row in sources["modules"]
        for input_descriptor in row["testInputs"]
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
