"""Generated full CRS source-concept releases stay pinned and reproducible."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseView,
    source_scoped_concept_iri,
)

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "generate_crs_source_concept_releases.py"
EVIDENCE_ROOT = ROOT / "research" / "evidence" / "crs-source-concept-releases-2026-08-04"
EVIDENCE_PATH = EVIDENCE_ROOT / "release-evidence.json"

_EXPECTED_RELEASES = {
    "legislativeSubjects": {
        "path": "legislative-subjects",
        "conceptCount": 565,
        "rightsRecordCount": 1,
        "rightsSetDigest": "sha256:6b75d98b460ef532b4abc0412e6d0999da0db0e6b1ef06d503d81c44dcfda4f8",
        "rightsStatuses": ["notStated"],
        "releaseId": (
            "urn:ref:source-concept-release:subject:" "d137bdbae553a0ca59fb879458703de0a0a9047b49c119cb79a0765de75f3567"
        ),
        "releaseDigest": ("sha256:d137bdbae553a0ca59fb879458703de0a0a9047b49c119cb79a0765de75f3567"),
        "logicalDigest": ("sha256:39c876bd1b7b577c09248a47ba63fdba68543ebd18185c5f71e99871217a577b"),
        "manifestDigest": ("sha256:f20d688f08134a8b6b1c9a6e202e84c5e051e2786c743df66708be27b55b12e7"),
    },
    "legislativeEntities": {
        "path": "legislative-entities",
        "conceptCount": 478,
        "rightsRecordCount": 2,
        "rightsSetDigest": "sha256:6489216d696f41bb43927e8edd643e86bd9d9c22e5a66f36fc1305f4de8059e6",
        "rightsStatuses": ["notStated"],
        "releaseId": (
            "urn:ref:source-concept-release:entity:" "79db00f21940827fdf62a0af51e1d0d9161fdc438f345700f50590439b0f5822"
        ),
        "releaseDigest": ("sha256:79db00f21940827fdf62a0af51e1d0d9161fdc438f345700f50590439b0f5822"),
        "logicalDigest": ("sha256:8437a64121d1608055bfe18df643f67e2f082170e3870b4f5f7e688ec873be7f"),
        "manifestDigest": ("sha256:aa80aaf0495a5e74a5194374cac05075fe8bcc0f0046261853293521544959fd"),
    },
    "policyAreas": {
        "path": "policy-areas",
        "conceptCount": 32,
        "rightsRecordCount": 1,
        "rightsSetDigest": "sha256:e8edc57fb971ad3bbba08fdd48c51f49df66c6ec34840dba6c17bbabb6de2adf",
        "rightsStatuses": ["notStated"],
        "releaseId": (
            "urn:ref:source-concept-release:subject:" "3e2d1e3d598d818c4d53e9514c05ad8a5a804a3f138e1325f1605c7eed517d7e"
        ),
        "releaseDigest": ("sha256:3e2d1e3d598d818c4d53e9514c05ad8a5a804a3f138e1325f1605c7eed517d7e"),
        "logicalDigest": ("sha256:11eadd5a0c435f016e2e3230b625fcc4b5bce99090638daa635fb9995c6b9bf4"),
        "manifestDigest": ("sha256:b5966cb93cc1a28cc87ea914538f9c2f3da0b44fb37f66385170b56954dabeb8"),
    },
}


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _evidence(root: Path = EVIDENCE_ROOT) -> dict[str, object]:
    return json.loads((root / "release-evidence.json").read_text(encoding="utf-8"))


def _files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_checked_generator_reproduces_exact_retained_capture_releases() -> None:
    result = _run("--check")

    assert result.returncode == 0, result.stderr
    assert "CRS source-concept evidence is current" in result.stdout


def test_summary_carries_external_pins_and_all_content_derived_identities() -> None:
    evidence = _evidence()
    assert evidence["summary"] == {
        "releaseCount": 3,
        "subjectReleaseCount": 2,
        "entityReleaseCount": 1,
        "conceptCount": 1_075,
    }
    rows = {
        str(row["name"]): row
        for row in evidence["releases"]  # type: ignore[union-attr]
    }
    assert rows.keys() == _EXPECTED_RELEASES.keys()
    for name, expected in _EXPECTED_RELEASES.items():
        row = rows[name]
        for field, value in expected.items():
            assert row[field] == value
        assert row["releaseId"].endswith(str(row["releaseDigest"]).removeprefix("sha256:"))
        assert set(row["sourceCapture"]) == {
            "resourceManifest",
            "logicalDigest",
            "observationSetDigest",
            "reconciliationDigest",
        }


def test_every_package_reopens_and_preserves_the_reconciled_source_identity() -> None:
    evidence = _evidence()
    all_concept_ids: set[str] = set()
    for row in evidence["releases"]:  # type: ignore[union-attr]
        view = SourceConceptReleaseView.open(
            EVIDENCE_ROOT / row["path"] / "bundle-manifest.json",
            expected_manifest_digest=row["manifestDigest"],
        )
        observations = {str(observation["id"]): observation for observation in view.source_bundle.observations}
        source_scheme = str(view.release_manifest["sourceScheme"]["id"])
        assert len(view.concepts) == row["conceptCount"]
        assert view.release_id == row["releaseId"]
        assert view.release_digest == row["releaseDigest"]
        assert view.logical_digest == row["logicalDigest"]
        assert view.manifest_digest == row["manifestDigest"]
        selected_artifacts = {
            str(observations[str(concept["sourceObservation"])]["sourceArtifact"]) for concept in view.concepts
        }
        assert {str(value["sourceArtifact"]) for value in view.rights_metadata} == (selected_artifacts)
        assert {str(value["rightsStatus"]) for value in view.rights_metadata} == {"notStated"}
        for value in view.rights_metadata:
            source_artifact = str(value["sourceArtifact"])
            assert (
                value["sourceDigest"]
                == "sha256:" + hashlib.sha256(view.source_bundle.source_artifacts[source_artifact]).hexdigest()
            )
        for concept in view.concepts:
            observation = observations[str(concept["sourceObservation"])]
            assert concept["identityKind"] == "refspecSourceScoped"
            assert concept["id"] == source_scoped_concept_iri(
                source_scheme,
                str(observation["localRecordId"]),
            )
            assert concept["id"] not in all_concept_ids
            all_concept_ids.add(str(concept["id"]))
    assert len(all_concept_ids) == 1_075


def test_write_reproduces_from_the_checked_embedded_source_packages(
    tmp_path: Path,
) -> None:
    output = tmp_path / "generated"

    result = _run(
        "--write",
        "--source-evidence",
        str(EVIDENCE_ROOT),
        "--output",
        str(output),
    )
    assert result.returncode == 0, result.stderr
    assert _files(output) == _files(EVIDENCE_ROOT)

    checked = _run(
        "--check",
        "--source-evidence",
        str(EVIDENCE_ROOT),
        "--output",
        str(output),
    )
    assert checked.returncode == 0, checked.stderr


def test_check_refuses_tampered_release_bytes(tmp_path: Path) -> None:
    output = tmp_path / "tampered"
    shutil.copytree(EVIDENCE_ROOT, output)
    concepts = output / "legislative-subjects" / "concepts.jsonl"
    concepts.write_bytes(concepts.read_bytes() + b"{}\n")

    result = _run(
        "--check",
        "--source-evidence",
        str(EVIDENCE_ROOT),
        "--output",
        str(output),
    )

    assert result.returncode == 1
    assert "bytes differ" in result.stderr
