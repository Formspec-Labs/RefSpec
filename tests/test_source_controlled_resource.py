from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION,
    SourceControlledResourceError,
    SourceControlledResourceView,
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import SourceRegistrationEvent

SOURCE_ID = "https://example.test/terms.json"
SOURCE_BYTES = b'{"terms":[{"code":"A","label":"Alpha"}]}\n'
SOURCE_DIGEST = "sha256:184a8d10ce7ae8b28286b733d1d2df1cec782f32c85d6b43931ecacdc67aee7d"
SCHEME_SOURCE_ID = "https://example.test/schemes/example.json"
SCHEME_SOURCE_BYTES = b'{"id":"https://example.test/schemes/example"}\n'
REGISTRATION_EVENT = SourceRegistrationEvent(
    registration_id="019fc9f2-c758-7b5c-9c19-f7fe5e2bf611",
    registered_at="2026-08-03T23:25:59Z",
)
SCHEME_FETCH_ID = "019fc9f2-c758-728f-8dbb-232379d1c9a3"


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
        "uses": ["sourceAssignedEvidence"],
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
        observations=(_observation(),),
        source_artifacts={SOURCE_ID: SOURCE_BYTES},
    )


def test_common_builder_preserves_a_complete_real_covered_projection(
    tmp_path: Path,
) -> None:
    """Exercise the generic builder with its covered Federal Register package."""

    source_path = os.environ.get("REFSPEC_FR_TOPICS_PATH")
    if source_path is None:
        pytest.skip("real Federal Register topics response is not configured")

    from refspec.registry.federal_register_topics_api import (
        FEDERAL_REGISTER_TOPICS_API_URL,
        capture_federal_register_topics,
    )
    from refspec.registry.packages.federal_register_topics_package import (
        FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT,
        FEDERAL_REGISTER_TOPICS_CAPTURED_AT,
        FEDERAL_REGISTER_TOPICS_REGISTRATION_EVENT,
        FEDERAL_REGISTER_TOPICS_RESOURCE_ID,
        build_federal_register_topics_source_package,
    )

    acquired = capture_federal_register_topics(
        tmp_path / "capture",
        source_path=Path(source_path),
        retrieved_at=FEDERAL_REGISTER_TOPICS_CAPTURED_AT,
        fetch_event=FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT,
    )
    covered_package = build_federal_register_topics_source_package(acquired)
    source_bytes = Path(source_path).read_bytes()

    rebuilt = build_source_controlled_resource_bundle(
        resource_id=FEDERAL_REGISTER_TOPICS_RESOURCE_ID,
        title="FederalRegister.gov Topics API source observations",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("sourceAssignedEvidence",),
        captured_at=FEDERAL_REGISTER_TOPICS_CAPTURED_AT,
        observations=covered_package.observations,
        source_artifacts={FEDERAL_REGISTER_TOPICS_API_URL: source_bytes},
        registration_event=FEDERAL_REGISTER_TOPICS_REGISTRATION_EVENT.as_dict(),
    )

    assert rebuilt.logical_digest == covered_package.logical_digest
    assert rebuilt.coverage_report["packagedCount"] == 7_767
    assert rebuilt.source_artifacts[FEDERAL_REGISTER_TOPICS_API_URL] == source_bytes


def test_package_round_trips_and_rechecks_exact_sources(tmp_path: Path) -> None:
    package = _bundle()
    package_path = package.write_to(tmp_path / "package")
    opened = SourceControlledResourceView.open(package_path)

    assert opened.logical_digest == package.logical_digest
    assert opened.observations[0]["id"] == package.observations[0]["id"]
    assert opened.observations[0]["labels"][0]["value"] == package.observations[0]["labels"][0]["value"]
    assert opened.source_artifact_bytes(SOURCE_ID) == SOURCE_BYTES
    assert opened.coverage_report["reportStatus"] == "pass"


def test_built_package_is_deeply_immutable() -> None:
    package = _bundle()
    original = package.artifact_bytes()

    with pytest.raises(TypeError):
        package.resource_manifest["title"] = "Changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        package.observations[0]["labels"][0]["value"] = "Changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        package.coverage_report["gaps"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        package.source_artifacts[SOURCE_ID] = b"changed"  # type: ignore[index]

    assert package.artifact_bytes() == original


def test_package_uses_version_2_0_across_every_manifest(tmp_path: Path) -> None:
    package = _bundle()
    artifacts = package.artifact_bytes()

    assert SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION == "2.0"
    assert package.resource_manifest["schemaVersion"] == "2.0"
    assert package.coverage_report["schemaVersion"] == "2.0"
    assert json.loads(artifacts["bundle-manifest.json"])["schemaVersion"] == "2.0"

    opened = SourceControlledResourceView.open(package.write_to(tmp_path / "package"))
    assert opened.resource_manifest["schemaVersion"] == "2.0"
    assert opened.coverage_report["schemaVersion"] == "2.0"


def test_package_carries_no_permission_fields(tmp_path: Path) -> None:
    package = build_source_controlled_resource_bundle(
        resource_id="example-terms",
        title="Example terms",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("sourceAssignedEvidence",),
        captured_at="2026-07-30T12:00:00Z",
        observations=(_observation(),),
        source_artifacts={SOURCE_ID: SOURCE_BYTES},
    )

    assert {
        "acceptedOutputUseAuthorized",
        "candidateUseAuthorized",
        "usageCeiling",
    }.isdisjoint(package.resource_manifest)
    opened = SourceControlledResourceView.open(package.write_to(tmp_path / "package"))
    assert {
        "acceptedOutputUseAuthorized",
        "candidateUseAuthorized",
        "usageCeiling",
    }.isdisjoint(opened.resource_manifest)


@pytest.mark.parametrize(
    "field",
    [
        "acceptedOutputUseAuthorized",
        "candidateUseAuthorized",
        "emissionAuthorized",
        "usageCeiling",
    ],
)
def test_package_rejects_permission_fields(field: str) -> None:
    package = _bundle()
    manifest = dict(package.resource_manifest)
    manifest[field] = False

    with pytest.raises(SourceControlledResourceError, match="fields do not match"):
        type(package)(
            resource_manifest=manifest,
            coverage_report=package.coverage_report,
            observations=package.observations,
            source_artifacts=package.source_artifacts,
        )


@pytest.mark.parametrize(
    "field",
    [
        "admissionReview",
        "candidateUseAuthorized",
        "emissionAuthorized",
        "permission",
    ],
)
def test_observations_reject_governance_fields_recursively(field: str) -> None:
    observation = _observation()
    observation["metadata"] = {field: True}

    with pytest.raises(
        SourceControlledResourceError,
        match="unqualified identity or governance fields",
    ):
        build_source_controlled_resource_bundle(
            resource_id="example-terms",
            title="Example terms",
            resource_kind="controlledCodeList",
            identity_status="publisherIdentifiersPreserved",
            uses=("sourceAssignedEvidence",),
            captured_at="2026-07-30T12:00:00Z",
            observations=(observation,),
            source_artifacts={SOURCE_ID: SOURCE_BYTES},
        )


def test_mapping_reference_is_a_supported_resource_use(tmp_path: Path) -> None:
    observation = {**_observation(), "uses": ["mappingReference"]}
    package = build_source_controlled_resource_bundle(
        resource_id="example-mapping-reference",
        title="Example mapping reference",
        resource_kind="sourceTermSnapshot",
        identity_status="publisherIdentifiersPreserved",
        uses=("mappingReference",),
        captured_at="2026-07-30T12:00:00Z",
        observations=(observation,),
        source_artifacts={SOURCE_ID: SOURCE_BYTES},
    )

    assert package.resource_manifest["uses"] == ("mappingReference",)
    assert package.observations[0]["uses"] == ("mappingReference",)
    opened = SourceControlledResourceView.open(package.write_to(tmp_path / "package"))
    assert opened.resource_manifest["uses"] == ("mappingReference",)


def test_package_rejects_cross_artifact_schema_versions(tmp_path: Path) -> None:
    package = _bundle()
    coverage = dict(package.coverage_report)
    coverage["schemaVersion"] = "1.0"
    with pytest.raises(SourceControlledResourceError, match="schemaVersion values disagree"):
        type(package)(
            resource_manifest=package.resource_manifest,
            coverage_report=coverage,
            observations=package.observations,
            source_artifacts=package.source_artifacts,
        )

    package_path = package.write_to(tmp_path / "package")
    resource_manifest_path = package_path / "resource-manifest.json"
    resource_manifest = json.loads(resource_manifest_path.read_bytes())
    resource_manifest["schemaVersion"] = "1.0"
    resource_manifest_bytes = canonical_json_bytes(resource_manifest)
    resource_manifest_path.write_bytes(resource_manifest_bytes)

    bundle_manifest_path = package_path / "bundle-manifest.json"
    bundle_manifest = json.loads(bundle_manifest_path.read_bytes())
    descriptor = next(value for value in bundle_manifest["artifacts"] if value["path"] == "resource-manifest.json")
    descriptor["sha256"] = sha256_digest(resource_manifest_bytes)
    descriptor["byteLength"] = len(resource_manifest_bytes)
    bundle_manifest_path.write_bytes(canonical_json_bytes(bundle_manifest))

    with pytest.raises(SourceControlledResourceError, match="schemaVersion values disagree"):
        SourceControlledResourceView.open(package_path)


def test_package_rejects_version_1_0() -> None:
    package = _bundle()
    manifest = dict(package.resource_manifest)
    manifest["schemaVersion"] = "1.0"

    with pytest.raises(SourceControlledResourceError, match="schemaVersion is unsupported"):
        type(package)(
            resource_manifest=manifest,
            coverage_report=package.coverage_report,
            observations=package.observations,
            source_artifacts=package.source_artifacts,
        )


def test_verified_view_deep_freezes_records_after_open(
    tmp_path: Path,
) -> None:
    package_path = _bundle().write_to(tmp_path / "package")
    opened = SourceControlledResourceView.open(package_path)

    assert opened.path == package_path
    assert isinstance(opened.resource_manifest["uses"], tuple)
    assert isinstance(
        opened.resource_manifest["sourceArtifacts"],
        tuple,
    )
    assert isinstance(opened.coverage_report["gaps"], tuple)
    assert isinstance(opened.observations[0]["labels"], tuple)
    assert isinstance(opened.observations[0]["identifiers"], tuple)
    assert opened.observations[0]["labels"][0]["value"] == "Alpha"
    assert opened.source_artifact_bytes(SOURCE_ID) == SOURCE_BYTES

    with pytest.raises(TypeError):
        opened.resource_manifest["sourceArtifacts"][0]["path"] = (  # type: ignore[index]
            "changed"
        )
    with pytest.raises(TypeError):
        opened.observations[0]["labels"][0]["value"] = "Changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        opened.source_artifacts[SOURCE_ID] = b"changed"  # type: ignore[index]

    assert opened.observations[0]["labels"][0]["value"] == "Alpha"
    assert opened.source_artifact_bytes(SOURCE_ID) == SOURCE_BYTES


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


def test_capture_package_rejects_concept_identity_claims() -> None:
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


def test_package_preserves_an_optional_source_scheme_authority_record(
    tmp_path: Path,
) -> None:
    package = build_source_controlled_resource_bundle(
        resource_id="example-terms",
        title="Example terms",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("sourceAssignedEvidence",),
        captured_at="2026-08-03T23:25:59Z",
        observations=(_observation(),),
        source_artifacts={
            SOURCE_ID: SOURCE_BYTES,
            SCHEME_SOURCE_ID: SCHEME_SOURCE_BYTES,
        },
        source_scheme={
            "id": "https://example.test/schemes/example",
            "code": "example",
            "label": "Example scheme",
            "sourceArtifact": SCHEME_SOURCE_ID,
            "sourceFetchId": SCHEME_FETCH_ID,
            "sourceObservedAt": "2026-08-03T23:25:59Z",
        },
    )

    opened = SourceControlledResourceView.open(package.write_to(tmp_path / "scheme-package"))

    assert opened.resource_manifest["sourceScheme"] == {
        "id": "https://example.test/schemes/example",
        "code": "example",
        "label": "Example scheme",
        "sourceArtifact": SCHEME_SOURCE_ID,
        "sourceFetchId": SCHEME_FETCH_ID,
        "sourceObservedAt": "2026-08-03T23:25:59Z",
    }
    assert opened.source_artifact_bytes(SCHEME_SOURCE_ID) == SCHEME_SOURCE_BYTES


def test_package_rejects_a_source_scheme_without_its_authority_record() -> None:
    with pytest.raises(SourceControlledResourceError, match="not in the package source set"):
        build_source_controlled_resource_bundle(
            resource_id="example-terms",
            title="Example terms",
            resource_kind="controlledCodeList",
            identity_status="publisherIdentifiersPreserved",
            uses=("sourceAssignedEvidence",),
            captured_at="2026-08-03T23:25:59Z",
            observations=(_observation(),),
            source_artifacts={SOURCE_ID: SOURCE_BYTES},
            source_scheme={
                "id": "https://example.test/schemes/example",
                "code": "example",
                "label": "Example scheme",
                "sourceArtifact": SCHEME_SOURCE_ID,
                "sourceFetchId": SCHEME_FETCH_ID,
                "sourceObservedAt": "2026-08-03T23:25:59Z",
            },
        )


def test_package_hashes_local_record_membership_and_capture_independent_content() -> None:
    observation = {
        **_observation(),
        "localRecordId": REGISTRATION_EVENT.derived_record_urn(
            purpose="example-local-record",
            source_key="$.terms[0]",
        ),
    }
    package = build_source_controlled_resource_bundle(
        resource_id="example-terms",
        title="Example terms",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("sourceAssignedEvidence",),
        captured_at=REGISTRATION_EVENT.registered_at,
        observations=(observation,),
        source_artifacts={SOURCE_ID: SOURCE_BYTES},
        registration_event=REGISTRATION_EVENT.as_dict(),
    )

    assert package.resource_manifest["registrationEvent"] == REGISTRATION_EVENT.as_dict()
    assert package.coverage_report["localRecordIdSetDigest"].startswith("sha256:")
    assert package.coverage_report["localRecordContentSetDigest"].startswith("sha256:")

    moved_observation = {
        **observation,
        "id": "urn:ref:source-record:example:another-capture:7",
        "sourcePath": "$.terms[7]",
        "sourceOrdinal": 7,
        "identifiers": [
            {
                "value": "A",
                "kind": "publisherCode",
                "authorityUri": "https://example.test/terms",
                "sourceUri": "https://example.test/another-capture.json",
                "sourcePath": "$.values[7].code",
                "observedAt": "2026-08-03T23:25:59Z",
                "sourceDigest": SOURCE_DIGEST,
            }
        ],
    }
    moved = build_source_controlled_resource_bundle(
        resource_id="example-terms",
        title="Example terms",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("sourceAssignedEvidence",),
        captured_at=REGISTRATION_EVENT.registered_at,
        observations=(moved_observation,),
        source_artifacts={SOURCE_ID: SOURCE_BYTES},
        registration_event=REGISTRATION_EVENT.as_dict(),
    )

    assert moved.coverage_report["observationSetDigest"] != package.coverage_report["observationSetDigest"]
    assert moved.coverage_report["localRecordIdSetDigest"] == package.coverage_report["localRecordIdSetDigest"]
    assert (
        moved.coverage_report["localRecordContentSetDigest"] == package.coverage_report["localRecordContentSetDigest"]
    )


def test_package_rejects_partial_or_duplicate_local_record_ids() -> None:
    local_id = REGISTRATION_EVENT.derived_record_urn(
        purpose="example-local-record",
        source_key="$.terms[0]",
    )
    first = {**_observation(), "localRecordId": local_id}
    second = {
        **_observation(),
        "id": "urn:ref:source-record:example:c01e5feb:1",
        "sourcePath": "$.terms[1]",
        "sourceOrdinal": 1,
    }

    with pytest.raises(SourceControlledResourceError, match="every observation"):
        build_source_controlled_resource_bundle(
            resource_id="example-terms",
            title="Example terms",
            resource_kind="controlledCodeList",
            identity_status="publisherIdentifiersPreserved",
            uses=("sourceAssignedEvidence",),
            captured_at=REGISTRATION_EVENT.registered_at,
            observations=(first, second),
            source_artifacts={SOURCE_ID: SOURCE_BYTES},
            registration_event=REGISTRATION_EVENT.as_dict(),
        )

    with pytest.raises(SourceControlledResourceError, match="unique localRecordId"):
        build_source_controlled_resource_bundle(
            resource_id="example-terms",
            title="Example terms",
            resource_kind="controlledCodeList",
            identity_status="publisherIdentifiersPreserved",
            uses=("sourceAssignedEvidence",),
            captured_at=REGISTRATION_EVENT.registered_at,
            observations=(first, {**second, "localRecordId": local_id}),
            source_artifacts={SOURCE_ID: SOURCE_BYTES},
            registration_event=REGISTRATION_EVENT.as_dict(),
        )
