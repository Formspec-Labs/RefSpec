from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from refspec.atlas.v1_release import read_vocabulary_atlas_v1_release_definition

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/prepare_vocabulary_atlas_v1_baseline_release.py"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_prepares_and_rechecks_exact_baseline_evidence_definition(
    tmp_path: Path,
) -> None:
    output = tmp_path / "baseline-evidence-definition.json"
    prepared = _run("--output", str(output))

    assert prepared.returncode == 0, prepared.stderr
    summary = json.loads(prepared.stdout)
    assert summary == {
        "definitionFileDigest": summary["definitionFileDigest"],
        "definitionId": summary["definitionId"],
        "definitionPath": str(output.resolve()),
        "mappingProofCount": 582,
        "providerCalls": False,
        "releaseCount": 6,
        "status": "prepared",
    }
    definition = read_vocabulary_atlas_v1_release_definition(
        output,
        expected_file_digest=summary["definitionFileDigest"],
    )
    record = definition.as_record()
    assert record["releaseMode"] == "baselineEvidenceRc"
    assert record["scopeKind"] == "bench"
    assert record["productionQualificationRuns"] == []
    assert len(record["baselineQualificationRuns"]) == 3
    assert len(record["publication"]["rowDispositions"]) == 87
    assert sum(
        row["disposition"] == "included"
        for row in record["publication"]["rowDispositions"]
    ) == 6
    assert len(record["publication"]["sourceApprovals"]) == 6
    assert all(
        approval["disposition"] == "approved"
        for approval in record["publication"]["sourceApprovals"]
    )
    icpsr = next(
        approval
        for approval in record["publication"]["sourceApprovals"]
        if ":icpsr:" in approval["releaseId"]
    )
    assert [condition["kind"] for condition in icpsr["conditions"]] == [
        "developmentOnly"
    ]
    proof_counts = {
        row["key"]: len(row["machineProofs"])
        for row in cast(list[dict[str, Any]], record["relationBundles"])
    }
    assert proof_counts == {
        "elsst-icpsr": 191,
        "federal-register-elsst": 190,
        "federal-register-icpsr": 201,
    }
    assert {
        field: record["expectedCounts"][field]
        for field in (
            "releaseCount",
            "planningRowCount",
            "includedPlanningRowCount",
            "conceptTotal",
            "nativeRelationTotal",
            "mappingMinimumTotal",
        )
    } == {
        "releaseCount": 6,
        "planningRowCount": 87,
        "includedPlanningRowCount": 6,
        "conceptTotal": 9_010,
        "nativeRelationTotal": 32_684,
        "mappingMinimumTotal": 582,
    }

    checked = _run("--output", str(output), "--check")
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == {**summary, "status": "verified"}


def test_check_rejects_a_definition_with_changed_bytes(tmp_path: Path) -> None:
    output = tmp_path / "baseline-evidence-definition.json"
    prepared = _run("--output", str(output))
    assert prepared.returncode == 0, prepared.stderr
    output.write_text("{}\n", encoding="utf-8")

    checked = _run("--output", str(output), "--check")

    assert checked.returncode == 2
    assert "differs from the exact current inputs" in checked.stderr
