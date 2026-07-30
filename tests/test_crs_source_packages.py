"""CRS development-package tests for lookup without invented concept identity."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import crs_legislative_resources as crs
from refspec.registry.crs_source_packages import (
    CRS_COMPLETE_CAPTURED_AT,
    CRS_LEGISLATIVE_SUBJECT_TERMS_RESOURCE_ID,
    CRS_POLICY_AREAS_RESOURCE_ID,
    build_crs_source_packages,
    build_crs_source_packages_from_capture_root,
    crs_source_package_evidence_bytes,
)
from refspec.registry.source_controlled_resource import (
    SourceControlledResourceView,
)

PROJECT_ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
FULL_CAPTURE_ROOT = PROJECT_ROOT.parent / "output" / "refspec-vocabulary-portfolio" / "crs" / "2026-07-30"
EVIDENCE = PROJECT_ROOT / "research" / "evidence" / "crs-source-packages-2026-07-30" / "package-evidence.json"

_FIXTURE_PAGES = (
    (
        crs.CRS_LEGISLATIVE_SUBJECTS_PAGE,
        "crs-legislative-subjects-mini.html",
        3,
    ),
    (
        crs.CRS_LEGISLATIVE_GEOGRAPHIC_PAGE,
        "crs-legislative-geographic-mini.html",
        2,
    ),
    (
        crs.CRS_LEGISLATIVE_ORGANIZATIONS_PAGE,
        "crs-legislative-organizations-mini.html",
        2,
    ),
    (
        crs.CRS_POLICY_AREAS_PAGE,
        "crs-policy-areas-mini.html",
        2,
    ),
)


def _fixture_acquisitions(tmp_path: Path) -> tuple[crs.AcquiredCRSPage, ...]:
    result: list[crs.AcquiredCRSPage] = []
    for original_source, fixture_name, count in _FIXTURE_PAGES:
        source = replace(original_source, expected_term_count=count)
        fixture = FIXTURES / fixture_name
        payload = fixture.read_bytes()
        pin = crs.CRSPageSnapshotPin(
            source=source,
            retrieved_at="2026-07-30T12:33:34Z",
            expected_sha256=crs.sha256_digest(payload),
            expected_byte_length=len(payload),
        )
        result.append(
            crs.acquire_crs_page(
                pin,
                tmp_path / "capture",
                source_path=fixture,
            )
        )
    return tuple(result)


def test_keeps_detailed_terms_and_broad_policy_areas_separate(
    tmp_path: Path,
) -> None:
    packages = build_crs_source_packages(
        _fixture_acquisitions(tmp_path),
        captured_at=CRS_COMPLETE_CAPTURED_AT,
    )
    detailed = packages.legislative_subject_terms
    policy = packages.policy_areas

    assert detailed.resource_manifest["resourceId"] == (CRS_LEGISLATIVE_SUBJECT_TERMS_RESOURCE_ID)
    assert detailed.resource_manifest["resourceKind"] == "sourceTermSnapshot"
    assert detailed.resource_manifest["candidateUseAuthorized"] is True
    assert detailed.resource_manifest["uses"] == [
        "sourceAssignedEvidence",
        "searchExpansion",
    ]
    assert len(detailed.observations) == 7
    assert {row["category"] for row in detailed.observations} == {
        "subject",
        "geographicEntity",
        "organizationName",
    }

    assert policy.resource_manifest["resourceId"] == (CRS_POLICY_AREAS_RESOURCE_ID)
    assert policy.resource_manifest["resourceKind"] == "navigationList"
    assert policy.resource_manifest["candidateUseAuthorized"] is False
    assert policy.resource_manifest["uses"] == [
        "sourceAssignedEvidence",
        "navigation",
    ]
    assert len(policy.observations) == 2
    assert {row["category"] for row in policy.observations} == {"policyArea"}
    assert all("definition" in row for row in policy.observations)


def test_observations_are_searchable_but_never_claim_publisher_identity(
    tmp_path: Path,
) -> None:
    packages = build_crs_source_packages(
        _fixture_acquisitions(tmp_path),
        captured_at=CRS_COMPLETE_CAPTURED_AT,
    )

    for package in packages.resources():
        assert package.resource_manifest["usageCeiling"] == "developmentOnly"
        assert package.resource_manifest["identityStatus"] == "captureLocalObservationsOnly"
        assert package.resource_manifest["acceptedOutputUseAuthorized"] is False
        assert package.resource_manifest["conceptIdentityClaimed"] is False
        assert package.coverage_report["reportStatus"] == "gap"
        assert package.coverage_report["excludedCount"] == 0
        assert package.coverage_report["failedCount"] == 0
        assert package.coverage_report["sourceObservedCount"] == len(package.observations)
        assert {gap["code"] for gap in package.coverage_report["gaps"]} == {
            "publisherTermIdentifiersAbsent",
            "publisherNamedReleaseAbsent",
        }
        assert all(
            row["id"].startswith("urn:ref:crs-source-record:")
            and row["identifiers"] == []
            and row["conceptIdentityClaimed"] is False
            and row["identityStatus"] == "publisherIdentifierAbsent"
            and row["publisherReleaseStatus"] == "namedReleaseAbsent"
            for row in package.observations
        )


def test_input_order_does_not_change_package_bytes(tmp_path: Path) -> None:
    pages = _fixture_acquisitions(tmp_path)

    forward = build_crs_source_packages(
        pages,
        captured_at=CRS_COMPLETE_CAPTURED_AT,
    )
    reverse = build_crs_source_packages(
        tuple(reversed(pages)),
        captured_at=CRS_COMPLETE_CAPTURED_AT,
    )

    assert forward.legislative_subject_terms.artifact_bytes() == reverse.legislative_subject_terms.artifact_bytes()
    assert forward.policy_areas.artifact_bytes() == reverse.policy_areas.artifact_bytes()


def test_both_packages_round_trip_with_exact_source_bytes(
    tmp_path: Path,
) -> None:
    pages = _fixture_acquisitions(tmp_path)
    packages = build_crs_source_packages(
        pages,
        captured_at=CRS_COMPLETE_CAPTURED_AT,
    )

    for package in packages.resources():
        destination = tmp_path / "packages" / str(package.resource_manifest["resourceId"])
        opened = SourceControlledResourceView.open(package.write_to(destination))
        assert opened.logical_digest == package.logical_digest
        assert opened.observations == package.observations
        assert opened.source_artifacts == package.source_artifacts

    packaged_payloads = {payload for package in packages.resources() for payload in package.source_artifacts.values()}
    assert packaged_payloads == {(FIXTURES / fixture_name).read_bytes() for _, fixture_name, _ in _FIXTURE_PAGES}


def test_requires_all_four_reviewed_pages(tmp_path: Path) -> None:
    pages = _fixture_acquisitions(tmp_path)

    with pytest.raises(
        crs.CRSSourceDriftError,
        match="require all four reviewed pages",
    ):
        build_crs_source_packages(
            pages[:-1],
            captured_at=CRS_COMPLETE_CAPTURED_AT,
        )


def test_exact_ignored_captures_match_checked_in_package_evidence() -> None:
    if not FULL_CAPTURE_ROOT.is_dir():
        pytest.skip("exact 2026-07-30 CRS captures are not present")

    packages = build_crs_source_packages_from_capture_root(FULL_CAPTURE_ROOT)
    detailed = packages.legislative_subject_terms
    policy = packages.policy_areas

    assert len(detailed.observations) == 1_043
    assert len(detailed.source_artifacts) == 3
    assert {
        category: sum(row["category"] == category for row in detailed.observations)
        for category in (
            "subject",
            "geographicEntity",
            "organizationName",
        )
    } == {
        "subject": 565,
        "geographicEntity": 301,
        "organizationName": 177,
    }
    assert len(policy.observations) == 32
    assert len(policy.source_artifacts) == 1
    assert crs_source_package_evidence_bytes(packages) == EVIDENCE.read_bytes()
