"""Separate development packages for the two official LDA code lists."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry.lda_controlled_codes import LDASourceDriftError
from refspec.registry.lda_controlled_list_resources import (
    LDA_FILING_TYPE_PACKAGE,
    LDA_GENERAL_ISSUE_CODE_PACKAGE,
    LDAControlledListPackageError,
    LDAControlledListView,
    build_lda_filing_type_package,
    build_lda_general_issue_code_package,
)
from refspec.registry.source_controlled_resource import (
    build_source_controlled_resource_bundle,
)

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REFSPEC_ROOT / "tests" / "fixtures"
ISSUES_FIXTURE = FIXTURES / "lda-general-issue-codes-2026-07-30.json"
FILING_TYPES_FIXTURE = FIXTURES / "lda-filing-types-2026-07-30.json"
EVIDENCE_ROOT = REFSPEC_ROOT / "research" / "evidence" / "lda-controlled-lists-2026-07-30"


def test_builds_two_distinct_typed_development_resources() -> None:
    issues = build_lda_general_issue_code_package(ISSUES_FIXTURE)
    filing_types = build_lda_filing_type_package(FILING_TYPES_FIXTURE)

    assert issues.resource_manifest == {
        **issues.resource_manifest,
        "resourceId": "lda-general-issue-codes-2026-07-30",
        "resourceKind": "controlledCodeList",
        "usageCeiling": "developmentOnly",
        "candidateUseAuthorized": True,
        "acceptedOutputUseAuthorized": False,
        "conceptIdentityClaimed": False,
        "uses": ["sourceAssignedEvidence"],
        "observationCount": 79,
    }
    assert filing_types.resource_manifest == {
        **filing_types.resource_manifest,
        "resourceId": "lda-filing-types-2026-07-30",
        "resourceKind": "controlledCodeList",
        "usageCeiling": "developmentOnly",
        "candidateUseAuthorized": True,
        "acceptedOutputUseAuthorized": False,
        "conceptIdentityClaimed": False,
        "uses": ["deterministicMetadata"],
        "observationCount": 50,
    }
    assert issues.resource_manifest["id"] != filing_types.resource_manifest["id"]
    assert issues.logical_digest == (LDA_GENERAL_ISSUE_CODE_PACKAGE.expected_logical_digest)
    assert filing_types.logical_digest == (LDA_FILING_TYPE_PACKAGE.expected_logical_digest)


def test_preserves_exact_codes_labels_identifiers_and_source_pins() -> None:
    issues = build_lda_general_issue_code_package(ISSUES_FIXTURE)
    filing_types = build_lda_filing_type_package(FILING_TYPES_FIXTURE)

    issue_by_code = {observation["identifiers"][0]["value"]: observation for observation in issues.observations}
    telecom = issue_by_code["TEC"]
    assert telecom["labels"] == [
        {
            "value": "Telecommunications",
            "language": "en",
            "role": "preferred",
        }
    ]
    assert telecom["identifiers"] == [
        {
            "value": "TEC",
            "kind": "generalIssueCode",
            "authorityUri": "https://lda.gov/",
            "sourceUri": ("https://lda.gov/api/v1/constants/filing/lobbyingactivityissues/"),
            "sourcePath": "$[66].value",
            "observedAt": "2026-07-30T12:45:14Z",
            "sourceDigest": ("sha256:e1820ef17f3e63048ae50e526c2f56e507b2cf60d720fc227c76ee7c3610d5bf"),
        }
    ]
    assert telecom["sourceOrdinal"] == 66
    assert telecom["id"].startswith("urn:ref:source-observation:lda-general-issue-codes-2026-07-30:")
    assert telecom["eligibleUses"] == ["sourceAssignedEvidence"]
    assert telecom["conceptIdentityClaimed"] is False

    filing_by_code = {observation["identifiers"][0]["value"]: observation for observation in filing_types.observations}
    assert filing_by_code["Q1"]["labels"][0]["value"] == ("1st Quarter - Report")
    assert filing_by_code["Q1"]["eligibleUses"] == ["deterministicMetadata"]
    assert all(
        observation["conceptIdentityClaimed"] is False
        for observation in (*issues.observations, *filing_types.observations)
    )
    assert issues.source_artifacts == {
        LDA_GENERAL_ISSUE_CODE_PACKAGE.pin.source.source_url: (ISSUES_FIXTURE.read_bytes())
    }
    assert filing_types.source_artifacts == {
        LDA_FILING_TYPE_PACKAGE.pin.source.source_url: (FILING_TYPES_FIXTURE.read_bytes())
    }


def test_coverage_is_complete_and_keeps_publisher_gaps_explicit() -> None:
    issues = build_lda_general_issue_code_package(ISSUES_FIXTURE)
    filing_types = build_lda_filing_type_package(FILING_TYPES_FIXTURE)

    for bundle, expected_count in ((issues, 79), (filing_types, 50)):
        assert bundle.coverage_report["sourceObservedCount"] == expected_count
        assert bundle.coverage_report["parsedCount"] == expected_count
        assert bundle.coverage_report["packagedCount"] == expected_count
        assert bundle.coverage_report["excludedCount"] == 0
        assert bundle.coverage_report["failedCount"] == 0
        assert bundle.coverage_report["reportStatus"] == "gap"

    assert {gap["kind"] for gap in issues.coverage_report["gaps"]} == {"publisherReleaseUnavailable"}
    assert {gap["kind"] for gap in filing_types.coverage_report["gaps"]} == {
        "publisherReleaseUnavailable",
        "standaloneFilingPeriodListUnavailable",
        "standaloneFilingStatusListUnavailable",
    }


def test_generation_is_byte_deterministic() -> None:
    for builder, fixture in (
        (build_lda_general_issue_code_package, ISSUES_FIXTURE),
        (build_lda_filing_type_package, FILING_TYPES_FIXTURE),
    ):
        first = builder(fixture)
        second = builder(fixture)

        assert first.artifact_bytes() == second.artifact_bytes()
        assert first.logical_digest == second.logical_digest


def test_tracked_packages_reopen_and_support_exact_code_lookup() -> None:
    issues = LDAControlledListView.open(EVIDENCE_ROOT / "general-issue-codes")
    filing_types = LDAControlledListView.open(EVIDENCE_ROOT / "filing-types")

    assert issues.spec is LDA_GENERAL_ISSUE_CODE_PACKAGE
    assert len(issues.observations_by_code) == 79
    assert issues.lookup_code("TEC")["labels"][0]["value"] == ("Telecommunications")
    assert issues.lookup_code("ZZZ") is None

    assert filing_types.spec is LDA_FILING_TYPE_PACKAGE
    assert len(filing_types.observations_by_code) == 50
    assert filing_types.lookup_code("Q1")["labels"][0]["value"] == ("1st Quarter - Report")
    assert filing_types.lookup_code("Q1")["eligibleUses"] == ["deterministicMetadata"]


def test_lda_reader_rejects_a_self_consistent_unpinned_repackage(
    tmp_path: Path,
) -> None:
    original = build_lda_general_issue_code_package(ISSUES_FIXTURE)
    repackaged = build_source_controlled_resource_bundle(
        resource_id=LDA_GENERAL_ISSUE_CODE_PACKAGE.resource_id,
        title=LDA_GENERAL_ISSUE_CODE_PACKAGE.title,
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=LDA_GENERAL_ISSUE_CODE_PACKAGE.uses,
        captured_at=LDA_GENERAL_ISSUE_CODE_PACKAGE.pin.retrieved_at,
        candidate_use_authorized=False,
        observations=original.observations,
        source_artifacts=original.source_artifacts,
        source_observed_count=79,
        gaps=LDA_GENERAL_ISSUE_CODE_PACKAGE.known_gaps,
    )
    package_path = repackaged.write_to(tmp_path / "repackaged")

    with pytest.raises(
        LDAControlledListPackageError,
        match="external pin",
    ):
        LDAControlledListView.open(package_path)


def test_source_drift_cannot_produce_a_new_package(tmp_path: Path) -> None:
    payload = ISSUES_FIXTURE.read_bytes().replace(
        b'"Telecommunications"',
        b'"Telecommunicationt"',
    )
    assert len(payload) == len(ISSUES_FIXTURE.read_bytes())
    changed = tmp_path / "changed.json"
    changed.write_bytes(payload)

    with pytest.raises(LDASourceDriftError, match="digest drift"):
        build_lda_general_issue_code_package(changed)
