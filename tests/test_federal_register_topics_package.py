from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry.federal_register_topics_api import (
    FEDERAL_REGISTER_TOPICS_API_URL,
    FederalRegisterTopicsError,
    capture_federal_register_topics,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceView,
)
from refspec.registry.packages.federal_register_topics_package import (
    FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT,
    FEDERAL_REGISTER_TOPICS_CAPTURED_AT,
    FEDERAL_REGISTER_TOPICS_REGISTRATION_EVENT,
    FEDERAL_REGISTER_TOPICS_RESOURCE_ID,
    build_federal_register_topics_source_package,
)

FIXTURE = Path(__file__).parent / "fixtures" / "federal-register-topics-mini.json"


def _acquired(tmp_path: Path):
    return capture_federal_register_topics(
        tmp_path / "capture",
        source_path=FIXTURE,
    )


def test_packages_every_current_topic_as_source_evidence(
    tmp_path: Path,
) -> None:
    package = build_federal_register_topics_source_package(
        _acquired(tmp_path),
        observed_at=FEDERAL_REGISTER_TOPICS_CAPTURED_AT,
    )

    assert package.resource_manifest["resourceId"] == (FEDERAL_REGISTER_TOPICS_RESOURCE_ID)
    assert package.resource_manifest["candidateUseAuthorized"] is False
    assert package.resource_manifest["conceptIdentityClaimed"] is False
    assert package.resource_manifest["registrationEvent"] == (
        FEDERAL_REGISTER_TOPICS_REGISTRATION_EVENT.as_dict()
    )
    assert package.coverage_report["reportStatus"] == "pass"
    assert package.coverage_report["sourceObservedCount"] == 3
    assert package.coverage_report["packagedCount"] == 3
    assert "localRecordIdSetDigest" in package.coverage_report
    assert {row["collection"] for row in package.observations} == {
        "thesaurus",
        "ad_hoc",
    }
    assert all(not row["identifiers"] for row in package.observations)
    assert all(row["eligibleUses"] == ["sourceAssignedEvidence"] for row in package.observations)
    assert all(row["localRecordId"].startswith("urn:uuid:") for row in package.observations)
    assert all(
        row["sourceFetchId"] == FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT.fetch_id
        for row in package.observations
    )
    assert all(
        row["sourceObservedAt"] == FEDERAL_REGISTER_TOPICS_CAPTURED_AT
        for row in package.observations
    )
    assert len({row["localRecordId"] for row in package.observations}) == 3


def test_package_round_trips_exact_topics_source(tmp_path: Path) -> None:
    package = build_federal_register_topics_source_package(
        _acquired(tmp_path),
        observed_at=FEDERAL_REGISTER_TOPICS_CAPTURED_AT,
    )
    opened = SourceControlledResourceView.open(package.write_to(tmp_path / "package"))

    assert opened.logical_digest == package.logical_digest
    assert opened.source_artifact_bytes(FEDERAL_REGISTER_TOPICS_API_URL) == FIXTURE.read_bytes()
    assert opened.observations[0]["nativeRecord"]
    assert opened.resource_manifest["registrationEvent"]["registrationId"] == (
        FEDERAL_REGISTER_TOPICS_REGISTRATION_EVENT.registration_id
    )


def test_package_rechecks_the_retained_source_before_build(
    tmp_path: Path,
) -> None:
    acquired = _acquired(tmp_path)
    acquired.path.write_bytes(acquired.path.read_bytes() + b"\n")

    with pytest.raises(FederalRegisterTopicsError, match="byte length"):
        build_federal_register_topics_source_package(
            acquired,
            observed_at=FEDERAL_REGISTER_TOPICS_CAPTURED_AT,
        )


def test_package_requires_registration_time_to_match_observed_at(
    tmp_path: Path,
) -> None:
    with pytest.raises(FederalRegisterTopicsError, match="registration event time"):
        build_federal_register_topics_source_package(
            _acquired(tmp_path),
            observed_at="2026-07-31T12:00:00Z",
        )
