from __future__ import annotations

import json
from pathlib import Path

import pytest

from refspec.registry.source_controlled_resource import (
    SourceControlledResourceError,
    SourceControlledResourceView,
    build_source_controlled_resource_bundle,
)

SOURCE_ID = "https://example.test/terms.json"
SOURCE_BYTES = b'{"terms":[{"code":"A","label":"Alpha"}]}\n'
SOURCE_DIGEST = "sha256:184a8d10ce7ae8b28286b733d1d2df1cec782f32c85d6b43931ecacdc67aee7d"


def _observation() -> dict[str, object]:
    return {
        "id": "urn:ref:source-record:example:c01e5feb:0",
        "sourceArtifact": SOURCE_ID,
        "sourcePath": "$.terms[0]",
        "sourceOrdinal": 0,
        "labels": [
            {
                "value": "Alpha",
                "language": "en",
                "role": "preferred",
            }
        ],
        "identifiers": [
            {
                "value": "A",
                "kind": "publisherCode",
                "authorityUri": "https://example.test/terms",
                "sourceUri": SOURCE_ID,
                "sourcePath": "$.terms[0].code",
                "observedAt": "2026-07-30T12:00:00Z",
                "sourceDigest": SOURCE_DIGEST,
            }
        ],
        "eligibleUses": ["sourceAssignedEvidence"],
        "conceptIdentityClaimed": False,
    }


def _bundle():
    return build_source_controlled_resource_bundle(
        resource_id="example-terms",
        title="Example terms",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("sourceAssignedEvidence",),
        captured_at="2026-07-30T12:00:00Z",
        candidate_use_authorized=True,
        observations=(_observation(),),
        source_artifacts={SOURCE_ID: SOURCE_BYTES},
    )


def test_package_round_trips_and_rechecks_exact_sources(tmp_path: Path) -> None:
    package = _bundle()
    package_path = package.write_to(tmp_path / "package")
    opened = SourceControlledResourceView.open(package_path)

    assert opened.logical_digest == package.logical_digest
    assert opened.observations == package.observations
    assert opened.source_artifact_bytes(SOURCE_ID) == SOURCE_BYTES
    assert opened.coverage_report["reportStatus"] == "pass"


def test_package_generation_is_deterministic(tmp_path: Path) -> None:
    first = _bundle()
    second = _bundle()

    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.logical_digest == second.logical_digest

    first.write_to(tmp_path / "first")
    second.write_to(tmp_path / "second")
    assert {
        path.relative_to(tmp_path / "first").as_posix(): path.read_bytes()
        for path in (tmp_path / "first").rglob("*")
        if path.is_file()
    } == {
        path.relative_to(tmp_path / "second").as_posix(): path.read_bytes()
        for path in (tmp_path / "second").rglob("*")
        if path.is_file()
    }


def test_package_rejects_concept_or_accepted_output_claims() -> None:
    package = _bundle()
    manifest = dict(package.resource_manifest)
    manifest["conceptIdentityClaimed"] = True
    with pytest.raises(SourceControlledResourceError, match="concept identity"):
        type(package)(
            resource_manifest=manifest,
            coverage_report=package.coverage_report,
            observations=package.observations,
            source_artifacts=package.source_artifacts,
        )

    manifest["conceptIdentityClaimed"] = False
    manifest["acceptedOutputUseAuthorized"] = True
    with pytest.raises(SourceControlledResourceError, match="accepted output"):
        type(package)(
            resource_manifest=manifest,
            coverage_report=package.coverage_report,
            observations=package.observations,
            source_artifacts=package.source_artifacts,
        )


def test_package_rejects_tampering_and_extra_files(tmp_path: Path) -> None:
    package_path = _bundle().write_to(tmp_path / "package")
    observations = package_path / "observations.jsonl"
    row = json.loads(observations.read_bytes())
    row["labels"][0]["value"] = "Tampered"
    observations.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(SourceControlledResourceError, match="artifact pin"):
        SourceControlledResourceView.open(package_path)

    clean_path = _bundle().write_to(tmp_path / "clean")
    (clean_path / "extra.txt").write_text("not declared", encoding="utf-8")
    with pytest.raises(SourceControlledResourceError, match="file set"):
        SourceControlledResourceView.open(clean_path)


def test_package_rejects_duplicate_observation_ids() -> None:
    observation = _observation()
    with pytest.raises(SourceControlledResourceError, match="unique"):
        build_source_controlled_resource_bundle(
            resource_id="example-terms",
            title="Example terms",
            resource_kind="controlledCodeList",
            identity_status="publisherIdentifiersPreserved",
            uses=("sourceAssignedEvidence",),
            captured_at="2026-07-30T12:00:00Z",
            candidate_use_authorized=True,
            observations=(observation, observation),
            source_artifacts={SOURCE_ID: SOURCE_BYTES},
        )


def test_package_records_explicit_coverage_gaps() -> None:
    package = build_source_controlled_resource_bundle(
        resource_id="example-terms",
        title="Example terms",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("sourceAssignedEvidence",),
        captured_at="2026-07-30T12:00:00Z",
        candidate_use_authorized=True,
        observations=(_observation(),),
        source_artifacts={SOURCE_ID: SOURCE_BYTES},
        source_observed_count=2,
        excluded_count=1,
        gaps=(
            {
                "kind": "sourceRecordNotPackaged",
                "count": 1,
                "reason": "source record lacks a usable label",
            },
        ),
    )

    assert package.coverage_report["reportStatus"] == "gap"
    assert package.coverage_report["sourceObservedCount"] == 2
    assert package.coverage_report["packagedCount"] == 1
