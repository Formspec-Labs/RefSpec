"""CRS development-package tests for lookup without invented concept identity."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from refspec.immutable import deep_freeze_json
from refspec.registry import crs_legislative_resources as crs
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceView,
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import (
    SourceRegistrationEvent,
    derive_uuid7,
    validate_uuid7,
    validate_uuid7_urn,
)
from refspec.registry.packages import crs_source_packages as crs_packages
from refspec.registry.packages.crs_source_packages import (
    CRS_COMPLETE_CAPTURED_AT,
    CRS_LEGISLATIVE_SUBJECT_TERMS_RESOURCE_ID,
    CRS_POLICY_AREAS_RESOURCE_ID,
    CRS_REGISTRATION_EVENT,
    CRSIdentityLink,
    CRSIdentityReview,
    build_crs_source_packages,
    build_crs_source_packages_from_capture_root,
    crs_source_package_evidence_bytes,
    load_packaged_crs_scheme_authorities,
)

PROJECT_ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
FULL_CAPTURE_ROOT = PROJECT_ROOT / "output" / "refspec-vocabulary-portfolio" / "crs" / "2026-07-30"
EVIDENCE = PROJECT_ROOT / "research" / "evidence" / "crs-source-packages-2026-08-03" / "package-evidence.json"

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


def _fixture_acquisitions(
    tmp_path: Path,
    *,
    retrieved_at: str = "2026-07-30T12:33:34Z",
    payload_overrides: dict[str, bytes] | None = None,
) -> tuple[crs.AcquiredCRSPage, ...]:
    result: list[crs.AcquiredCRSPage] = []
    overrides = {} if payload_overrides is None else payload_overrides
    for original_source, fixture_name, count in _FIXTURE_PAGES:
        source = replace(original_source, expected_term_count=count)
        fixture = FIXTURES / fixture_name
        payload = overrides.get(fixture_name, fixture.read_bytes())
        source_path = fixture
        if fixture_name in overrides:
            source_path = tmp_path / "changed-sources" / fixture_name
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(payload)
        pin = crs.CRSPageSnapshotPin(
            source=source,
            retrieved_at=retrieved_at,
            fetch_id=derive_uuid7(
                retrieved_at,
                seed=f"fixture-fetch:{source.term_category}".encode(),
            ),
            expected_sha256=crs.sha256_digest(payload),
            expected_byte_length=len(payload),
        )
        result.append(
            crs.acquire_crs_page(
                pin,
                tmp_path / "capture",
                source_path=source_path,
            )
        )
    return tuple(result)


def _registration_event(registered_at: str, seed: bytes) -> SourceRegistrationEvent:
    return SourceRegistrationEvent(
        registration_id=derive_uuid7(registered_at, seed=seed),
        registered_at=registered_at,
    )


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
    assert "candidateUseAuthorized" not in detailed.resource_manifest
    assert detailed.resource_manifest["registrationEvent"] == CRS_REGISTRATION_EVENT.as_dict()
    assert detailed.resource_manifest["uses"] == (
        "searchExpansion",
        "sourceAssignedEvidence",
    )
    assert detailed.resource_manifest["sourceScheme"] == {
        "id": "http://id.loc.gov/vocabulary/subjectSchemes/lst",
        "code": "lst",
        "label": "Legislative subject terms",
        "sourceArtifact": "https://id.loc.gov/vocabulary/subjectSchemes/lst.json",
        "sourceFetchId": "019fc9f2-c758-728f-8dbb-232379d1c9a3",
        "sourceObservedAt": "2026-08-03T23:25:59Z",
    }
    assert len(detailed.observations) == 7
    assert {row["category"] for row in detailed.observations} == {
        "subject",
        "geographicEntity",
        "organizationName",
    }

    assert policy.resource_manifest["resourceId"] == (CRS_POLICY_AREAS_RESOURCE_ID)
    assert policy.resource_manifest["resourceKind"] == "navigationList"
    assert "candidateUseAuthorized" not in policy.resource_manifest
    assert policy.resource_manifest["uses"] == (
        "navigation",
        "sourceAssignedEvidence",
    )
    assert policy.resource_manifest["sourceScheme"] == {
        "id": "http://id.loc.gov/vocabulary/subjectSchemes/cgpa",
        "code": "cgpa",
        "label": "Congress.gov Policy Areas",
        "sourceArtifact": "https://id.loc.gov/vocabulary/subjectSchemes/cgpa.json",
        "sourceFetchId": "019fc9f2-c758-7bc2-903d-3b5365220f26",
        "sourceObservedAt": "2026-08-03T23:25:59Z",
    }
    assert len(policy.observations) == 2
    assert {row["category"] for row in policy.observations} == {"policyArea"}
    assert all("definition" in row for row in policy.observations)
    assert [report.status for report in packages.reconciliations] == [
        "initial",
        "initial",
    ]
    assert all(not report.requires_human_review for report in packages.reconciliations)


def test_observations_are_searchable_but_never_claim_publisher_identity(
    tmp_path: Path,
) -> None:
    packages = build_crs_source_packages(
        _fixture_acquisitions(tmp_path),
        captured_at=CRS_COMPLETE_CAPTURED_AT,
    )

    for package in packages.resources():
        assert "usageCeiling" not in package.resource_manifest
        assert package.resource_manifest["identityStatus"] == "captureLocalObservationsOnly"
        assert "acceptedOutputUseAuthorized" not in package.resource_manifest
        assert package.resource_manifest["conceptIdentityClaimed"] is False
        assert package.coverage_report["reportStatus"] == "gap"
        assert package.coverage_report["excludedCount"] == 0
        assert package.coverage_report["failedCount"] == 0
        assert package.coverage_report["sourceObservedCount"] == len(package.observations)
        assert package.coverage_report["localRecordIdSetDigest"].startswith("sha256:")
        assert package.coverage_report["localRecordContentSetDigest"].startswith("sha256:")
        assert {gap["code"] for gap in package.coverage_report["gaps"]} == {
            "publisherTermIdentifiersAbsent",
            "publisherNamedReleaseAbsent",
        }
        assert all(
            row["id"].startswith("urn:ref:crs-source-record:")
            and validate_uuid7_urn(row["localRecordId"]) == row["localRecordId"]
            and validate_uuid7(row["sourceFetchId"]) == row["sourceFetchId"]
            and not row["identifiers"]
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


def test_refetch_reuses_local_ids_when_source_terms_are_unchanged(
    tmp_path: Path,
) -> None:
    first = build_crs_source_packages(
        _fixture_acquisitions(tmp_path / "first"),
        captured_at=CRS_COMPLETE_CAPTURED_AT,
    )
    next_time = "2026-08-04T12:00:00Z"
    second = build_crs_source_packages(
        _fixture_acquisitions(
            tmp_path / "second",
            retrieved_at=next_time,
        ),
        captured_at=next_time,
        registration_event=_registration_event(next_time, b"unchanged-refetch"),
        predecessor=first,
    )

    for previous, current, report in zip(
        first.resources(),
        second.resources(),
        second.reconciliations,
        strict=True,
    ):
        assert [row["localRecordId"] for row in current.observations] == [
            row["localRecordId"] for row in previous.observations
        ]
        assert current.coverage_report["localRecordIdSetDigest"] == previous.coverage_report["localRecordIdSetDigest"]
        assert (
            current.coverage_report["localRecordContentSetDigest"]
            == previous.coverage_report["localRecordContentSetDigest"]
        )
        assert report.status == "unchanged"
        assert report.auto_matched_count == len(current.observations)
        assert report.requires_human_review is False
    second.require_reconciled()


def test_publisher_identifier_matches_before_a_changed_label(tmp_path: Path) -> None:
    pages = _fixture_acquisitions(tmp_path)
    parsed = tuple(crs.parse_crs_field_value_page(page) for page in pages[:3])
    resource = crs.assemble_crs_legislative_subject_terms(parsed)
    original = resource.terms[0]
    identifier = ControlledIdentifier(
        value="publisher-term-1",
        kind="publisherCode",
        authority_uri=resource.source_scheme.scheme_iri,
        source_uri=original.source_url,
        observed_at=pages[0].pin.retrieved_at,
        effective_at=None,
        source_digest=pages[0].sha256,
    )
    current_term = replace(
        original,
        official_label=original.official_label + " renamed",
        identifiers=(identifier,),
    )
    current = replace(resource, terms=(current_term, *resource.terms[1:]))
    previous_local_id = CRS_REGISTRATION_EVENT.derived_record_urn(
        purpose="test-prior-record",
        source_key="publisher-term-1",
    )
    predecessor = SimpleNamespace(
        resource_manifest={"sourceScheme": {"id": resource.source_scheme.scheme_iri}},
        coverage_report={"localRecordIdSetDigest": "sha256:" + "0" * 64},
        observations=(
            {
                "category": original.category,
                "localRecordId": previous_local_id,
                "labels": [{"value": original.official_label, "language": "en", "role": "preferred"}],
                "identifiers": [
                    {
                        "value": identifier.value,
                        "kind": identifier.kind,
                        "authorityUri": identifier.authority_uri,
                    }
                ],
            },
        ),
    )

    assigned, matched = crs_packages._assign_local_record_ids(
        current,
        _registration_event("2026-08-04T12:00:00Z", b"identifier-refetch"),
        predecessor,  # type: ignore[arg-type]
    )

    assert assigned[current_term.record_iri] == previous_local_id
    assert matched == 1


def test_cosmetic_source_change_is_recorded_without_identity_review(
    tmp_path: Path,
) -> None:
    first = build_crs_source_packages(
        _fixture_acquisitions(tmp_path / "first"),
        captured_at=CRS_COMPLETE_CAPTURED_AT,
    )
    fixture_name = "crs-legislative-subjects-mini.html"
    changed_payload = (
        (FIXTURES / fixture_name)
        .read_bytes()
        .replace(
            b"</body>",
            b"<!-- capture formatting changed --></body>",
        )
    )
    next_time = "2026-08-04T12:01:00Z"
    second = build_crs_source_packages(
        _fixture_acquisitions(
            tmp_path / "second",
            retrieved_at=next_time,
            payload_overrides={fixture_name: changed_payload},
        ),
        captured_at=next_time,
        registration_event=_registration_event(next_time, b"cosmetic-refetch"),
        predecessor=first,
    )

    detailed_report = second.reconciliations[0]
    assert detailed_report.status == "sourceOnlyChange"
    assert detailed_report.requires_human_review is False
    assert detailed_report.current_local_record_id_set_digest == (detailed_report.previous_local_record_id_set_digest)
    assert detailed_report.current_local_record_content_set_digest == (
        detailed_report.previous_local_record_content_set_digest
    )


def test_any_capture_independent_content_change_requires_review(tmp_path: Path) -> None:
    first = build_crs_source_packages(
        _fixture_acquisitions(tmp_path / "first"),
        captured_at=CRS_COMPLETE_CAPTURED_AT,
    )
    detailed = first.legislative_subject_terms
    changed_observations = (
        {
            **dict(detailed.observations[0]),
            "uses": ["sourceAssignedEvidence"],
        },
        *detailed.observations[1:],
    )
    manifest = detailed.resource_manifest
    coverage = detailed.coverage_report
    changed_predecessor = build_source_controlled_resource_bundle(
        resource_id=str(manifest["resourceId"]),
        title=str(manifest["title"]),
        resource_kind=manifest["resourceKind"],
        identity_status=manifest["identityStatus"],
        uses=manifest["uses"],
        captured_at=str(manifest["capturedAt"]),
        observations=changed_observations,
        source_artifacts=detailed.source_artifacts,
        registration_event=manifest["registrationEvent"],
        source_scheme=manifest["sourceScheme"],
        source_observed_count=int(coverage["sourceObservedCount"]),
        excluded_count=int(coverage["excludedCount"]),
        failed_count=int(coverage["failedCount"]),
        gaps=coverage["gaps"],
    )
    predecessor = replace(first, legislative_subject_terms=changed_predecessor)
    next_time = "2026-08-04T12:01:30Z"

    second = build_crs_source_packages(
        _fixture_acquisitions(tmp_path / "second", retrieved_at=next_time),
        captured_at=next_time,
        registration_event=_registration_event(next_time, b"content-refetch"),
        predecessor=predecessor,
    )

    report = second.reconciliations[0]
    assert report.status == "reviewRequired"
    assert report.requires_human_review is True
    assert report.changed_records[0]["changedFields"] == ["uses"]


def test_term_change_creates_a_review_queue_instead_of_guessing_identity(
    tmp_path: Path,
) -> None:
    first = build_crs_source_packages(
        _fixture_acquisitions(tmp_path / "first"),
        captured_at=CRS_COMPLETE_CAPTURED_AT,
    )
    fixture_name = "crs-legislative-subjects-mini.html"
    changed_payload = (
        (FIXTURES / fixture_name)
        .read_bytes()
        .replace(
            b"Congressional oversight",
            b"Congressional oversight activities",
        )
    )
    next_time = "2026-08-04T12:02:00Z"
    second = build_crs_source_packages(
        _fixture_acquisitions(
            tmp_path / "second",
            retrieved_at=next_time,
            payload_overrides={fixture_name: changed_payload},
        ),
        captured_at=next_time,
        registration_event=_registration_event(next_time, b"term-change-refetch"),
        predecessor=first,
    )

    detailed_report = second.reconciliations[0]
    assert detailed_report.status == "reviewRequired"
    assert detailed_report.requires_human_review is True
    assert len(detailed_report.added_records) == 1
    assert len(detailed_report.removed_records) == 1
    assert detailed_report.added_records[0]["label"] == "Congressional oversight activities"
    assert detailed_report.removed_records[0]["label"] == "Congressional oversight"
    assert detailed_report.match_suggestions[0]["decision"] == "humanReviewRequired"
    assert detailed_report.current_local_record_id_set_digest != (detailed_report.previous_local_record_id_set_digest)
    with pytest.raises(crs.CRSIdentityError, match="human identity review"):
        second.require_reconciled()

    review_time = "2026-08-04T13:00:00Z"
    review = CRSIdentityReview(
        review_id="urn:uuid:" + derive_uuid7(review_time, seed=b"human-review"),
        resource_name="legislativeSubjectTerms",
        proposal_change_digest=detailed_report.change_digest,
        reviewed_at=review_time,
        reviewed_by="urn:ref:person:crs-vocabulary-reviewer",
        identity_links=(
            CRSIdentityLink(
                current_observation_id=str(detailed_report.added_records[0]["observationId"]),
                previous_local_record_id=str(detailed_report.removed_records[0]["localRecordId"]),
                reason="CRS retained the subject and extended its display label.",
            ),
        ),
        reason="Reviewed the exact changed-capture report and accepted this rename.",
    )
    reviewed = build_crs_source_packages(
        _fixture_acquisitions(
            tmp_path / "reviewed",
            retrieved_at=next_time,
            payload_overrides={fixture_name: changed_payload},
        ),
        captured_at=next_time,
        registration_event=_registration_event(next_time, b"term-change-refetch"),
        predecessor=first,
        identity_reviews=(review,),
    )

    reviewed_report = reviewed.reconciliations[0]
    assert reviewed_report.status == "reviewed"
    assert reviewed_report.requires_human_review is False
    assert reviewed_report.review == review.as_dict()
    assert reviewed_report.added_records == ()
    assert reviewed_report.removed_records == ()
    assert reviewed_report.changed_records[0]["changedFields"] == ["labels"]
    reviewed.require_reconciled()


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
        assert opened.observations == deep_freeze_json(package.observations)
        assert opened.source_artifacts == package.source_artifacts

    packaged_payloads = {payload for package in packages.resources() for payload in package.source_artifacts.values()}
    scheme_payloads = {capture.payload for capture in load_packaged_crs_scheme_authorities()}
    page_payloads = {(FIXTURES / fixture_name).read_bytes() for _, fixture_name, _ in _FIXTURE_PAGES}
    assert packaged_payloads == page_payloads | scheme_payloads


def test_complete_ledger_round_trips_and_can_be_the_next_predecessor(tmp_path: Path) -> None:
    first = build_crs_source_packages(
        _fixture_acquisitions(tmp_path / "first"),
        captured_at=CRS_COMPLETE_CAPTURED_AT,
    )
    ledger_path = first.write_to(tmp_path / "ledger-2026-08-03")

    reopened = type(first).open(ledger_path)
    assert reopened.reconciliations == first.reconciliations
    assert [package.logical_digest for package in reopened.resources()] == [
        package.logical_digest for package in first.resources()
    ]

    next_time = "2026-08-04T12:04:00Z"
    second = build_crs_source_packages(
        _fixture_acquisitions(tmp_path / "second", retrieved_at=next_time),
        captured_at=next_time,
        registration_event=_registration_event(next_time, b"ledger-refetch"),
        predecessor=reopened,
    )
    assert [report.status for report in second.reconciliations] == ["unchanged", "unchanged"]
    assert [row["localRecordId"] for row in second.legislative_subject_terms.observations] == [
        row["localRecordId"] for row in reopened.legislative_subject_terms.observations
    ]

    with pytest.raises(crs.CRSIdentityError, match="already exists"):
        first.write_to(ledger_path)


def test_packaged_loc_scheme_authorities_are_exact_and_resource_specific() -> None:
    captures = load_packaged_crs_scheme_authorities()

    assert [capture.pin.scheme.code for capture in captures] == ["lst", "cgpa"]
    assert [capture.pin.expected_byte_length for capture in captures] == [3_153, 3_127]
    assert [crs.sha256_digest(capture.payload) for capture in captures] == [
        "sha256:f4765c3cf7ab685e1cc05ba0f0b71ae288a5433bda29a801be3ca62a25be36f3",
        "sha256:3b91e326475799c99ed24b6bf7eb692efb0196812b9c9af99606f0b41ac03286",
    ]


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
    assert len(detailed.source_artifacts) == 4
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
    assert len(policy.source_artifacts) == 2
    assert crs_source_package_evidence_bytes(packages) == EVIDENCE.read_bytes()
