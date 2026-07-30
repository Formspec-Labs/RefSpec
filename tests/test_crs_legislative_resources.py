"""CRS Legislative Subject Term and Policy Area source-foundation tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import crs_legislative_resources as crs

FIXTURES = Path(__file__).parent / "fixtures"


def _payload(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _pin(source: crs.CRSPageSource, payload: bytes) -> crs.CRSPageSnapshotPin:
    return crs.CRSPageSnapshotPin(
        source=source,
        retrieved_at="2026-07-30T12:33:34Z",
        expected_sha256=crs.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def _acquire_fixture(
    tmp_path: Path,
    source: crs.CRSPageSource,
    fixture_name: str,
) -> crs.AcquiredCRSPage:
    path = FIXTURES / fixture_name
    return crs.acquire_crs_page(
        _pin(source, path.read_bytes()),
        tmp_path,
        source_path=path,
    )


def test_current_official_pages_keep_the_two_resources_separate() -> None:
    assert [source.expected_term_count for source in crs.CRS_LEGISLATIVE_SUBJECT_TERM_PAGES] == [
        565,
        301,
        177,
    ]
    assert crs.CRS_LEGISLATIVE_SUBJECT_TERM_LISTED_COUNT == 1_043
    assert crs.CRS_POLICY_AREAS_PAGE.expected_term_count == 32
    assert {source.resource_name for source in crs.CRS_LEGISLATIVE_SUBJECT_TERM_PAGES} == {"legislativeSubjectTerms"}
    assert crs.CRS_POLICY_AREAS_PAGE.resource_name == "policyAreas"
    assert crs.CRS_POLICY_AREAS_PAGE.role == "navigation"


def test_local_capture_is_exact_and_content_addressed(tmp_path: Path) -> None:
    payload = _payload("crs-legislative-subjects-mini.html")
    source = replace(crs.CRS_LEGISLATIVE_SUBJECTS_PAGE, expected_term_count=3)
    pin = _pin(source, payload)

    acquired = crs.acquire_crs_page(
        pin,
        tmp_path,
        source_path=FIXTURES / "crs-legislative-subjects-mini.html",
    )
    cached = crs.acquire_crs_page(pin, tmp_path)

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    assert acquired.path == tmp_path / "sha256" / digest_hex / source.filename
    assert acquired.path.read_bytes() == payload
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = _payload("crs-legislative-subjects-mini.html")
    source = replace(crs.CRS_LEGISLATIVE_SUBJECTS_PAGE, expected_term_count=3)
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> crs.FetchedCRSPage:
            calls.append((source_url, timeout_seconds))
            return crs.FetchedCRSPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = crs.acquire_crs_page(
        _pin(source, payload),
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )

    assert calls == [(source.source_url, 17.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.content_type == "text/html; charset=UTF-8"


def test_initial_capture_establishes_pin_before_strict_reopen(
    tmp_path: Path,
) -> None:
    payload = _payload("crs-legislative-subjects-mini.html")
    source = replace(
        crs.CRS_LEGISLATIVE_SUBJECTS_PAGE,
        expected_term_count=3,
    )

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> crs.FetchedCRSPage:
            assert timeout_seconds == 17.0
            return crs.FetchedCRSPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    captured = crs.capture_initial_crs_page_snapshot(
        source,
        tmp_path,
        retrieved_at="2026-07-30T12:33:34Z",
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )
    reopened = crs.acquire_crs_page(captured.pin, tmp_path)

    assert captured.sha256 == crs.sha256_digest(payload)
    assert captured.byte_length == len(payload)
    assert captured.path.read_bytes() == payload
    assert captured.content_type == "text/html; charset=UTF-8"
    assert reopened.cache_hit is True
    assert reopened.pin == captured.pin


def test_challenge_page_never_publishes_source(tmp_path: Path) -> None:
    source = replace(crs.CRS_LEGISLATIVE_SUBJECTS_PAGE, expected_term_count=3)
    expected_payload = _payload("crs-legislative-subjects-mini.html")
    pin = _pin(source, expected_payload)

    class ChallengeFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> crs.FetchedCRSPage:
            del timeout_seconds
            return crs.FetchedCRSPage(
                body=b"<!doctype html><html><title>Just a moment...</title><div class='cf-chl-widget'></div></html>",
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(crs.CRSSourceDriftError, match="challenge page"):
        crs.acquire_crs_page(pin, tmp_path, fetcher=ChallengeFetcher())

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / source.filename
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_digest_drift_never_publishes_source(tmp_path: Path) -> None:
    expected_payload = _payload("crs-legislative-subjects-mini.html")
    changed_payload = expected_payload.replace(b"Postal service", b"Postal servicf")
    assert len(changed_payload) == len(expected_payload)
    source = replace(crs.CRS_LEGISLATIVE_SUBJECTS_PAGE, expected_term_count=3)
    pin = _pin(source, expected_payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> crs.FetchedCRSPage:
            del timeout_seconds
            return crs.FetchedCRSPage(
                body=changed_payload,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(crs.CRSSourceDriftError, match="digest drift"):
        crs.acquire_crs_page(pin, tmp_path, fetcher=ChangedFetcher())

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / source.filename
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_legislative_pages_preserve_category_labels_without_minting_ids(
    tmp_path: Path,
) -> None:
    subject_source = replace(crs.CRS_LEGISLATIVE_SUBJECTS_PAGE, expected_term_count=3)
    geographic_source = replace(
        crs.CRS_LEGISLATIVE_GEOGRAPHIC_PAGE,
        expected_term_count=2,
    )
    organization_source = replace(
        crs.CRS_LEGISLATIVE_ORGANIZATIONS_PAGE,
        expected_term_count=2,
    )
    pages = [
        crs.parse_crs_field_value_page(
            _acquire_fixture(
                tmp_path,
                subject_source,
                "crs-legislative-subjects-mini.html",
            )
        ),
        crs.parse_crs_field_value_page(
            _acquire_fixture(
                tmp_path,
                geographic_source,
                "crs-legislative-geographic-mini.html",
            )
        ),
        crs.parse_crs_field_value_page(
            _acquire_fixture(
                tmp_path,
                organization_source,
                "crs-legislative-organizations-mini.html",
            )
        ),
    ]

    resource = crs.assemble_crs_legislative_subject_terms(pages)

    assert resource.resource_name == "legislativeSubjectTerms"
    assert resource.role == "selectableSubject"
    assert [term.official_label for term in resource.terms] == [
        "Administrative law and regulatory procedures",
        "Congressional oversight",
        "Postal service",
        "District of Columbia",
        "Puerto Rico",
        "Congressional Research Service (CRS)",
        "U.S. Postal Service",
    ]
    assert [term.category for term in resource.terms] == [
        "subject",
        "subject",
        "subject",
        "geographicEntity",
        "geographicEntity",
        "organizationName",
        "organizationName",
    ]
    assert all(term.publisher_identifier is None for term in resource.terms)
    assert all(term.publisher_term_iri is None for term in resource.terms)
    assert all(term.identifiers == () for term in resource.terms)
    assert all(term.identity_status == "publisherIdentifierAbsent" for term in resource.terms)
    subject_digest = crs.sha256_digest(_payload("crs-legislative-subjects-mini.html")).removeprefix("sha256:")
    assert resource.terms[0].record_iri == (
        f"urn:ref:crs-source-record:{subject_digest}:subject:%2Fhelp%2Ffield-values%2Flegislative-subject-terms:1"
    )
    assert len({term.record_iri for term in resource.terms}) == len(resource.terms)
    assert resource.readiness.ready is False
    assert resource.readiness.publisher_identified_term_count == 0
    with pytest.raises(crs.CRSIdentityError, match="does not publish stable identifiers"):
        resource.readiness.require_ready()


def test_repeated_source_labels_remain_distinct_capture_records(
    tmp_path: Path,
) -> None:
    source = replace(crs.CRS_LEGISLATIVE_SUBJECTS_PAGE, expected_term_count=4)
    page = crs.parse_crs_field_value_page(
        _acquire_fixture(
            tmp_path,
            source,
            "crs-legislative-subjects-duplicate-mini.html",
        )
    )

    repeated = tuple(term for term in page.terms if term.official_label == "Agricultural marketing and promotion")
    assert len(repeated) == 2
    assert repeated[0].record_iri != repeated[1].record_iri
    assert [term.source_ordinal for term in repeated] == [1, 3]
    assert page.duplicate_label_evidence == (
        crs.CRSDuplicateLabelEvidence(
            official_label="Agricultural marketing and promotion",
            record_iris=(repeated[0].record_iri, repeated[1].record_iri),
            source_ordinals=(1, 3),
        ),
    )


def test_policy_areas_preserve_scope_notes_as_a_separate_navigation_resource(
    tmp_path: Path,
) -> None:
    source = replace(crs.CRS_POLICY_AREAS_PAGE, expected_term_count=2)
    page = crs.parse_crs_field_value_page(_acquire_fixture(tmp_path, source, "crs-policy-areas-mini.html"))

    resource = crs.assemble_crs_policy_areas(page)

    assert resource.resource_name == "policyAreas"
    assert resource.role == "navigation"
    assert [term.official_label for term in resource.terms] == [
        "Government Operations and Politics",
        "Health",
    ]
    assert all(term.category == "policyArea" for term in resource.terms)
    assert all(term.definition and term.definition.startswith("Primary focus") for term in resource.terms)
    assert all(term.identity_status == "publisherIdentifierAbsent" for term in resource.terms)
    assert resource.readiness.ready is False


def test_structure_or_count_change_fails_as_source_drift(tmp_path: Path) -> None:
    source = replace(crs.CRS_LEGISLATIVE_SUBJECTS_PAGE, expected_term_count=4)
    page = _acquire_fixture(
        tmp_path,
        source,
        "crs-legislative-subjects-mini.html",
    )

    with pytest.raises(crs.CRSSourceDriftError, match="category/count marker"):
        crs.parse_crs_field_value_page(page)


def test_live_api_fixture_preserves_assignment_dates_and_explicit_missing_ids() -> None:
    payload = _payload("crs-bill-subjects-117-hr-3076.json")

    parsed = crs.parse_crs_bill_subject_assignments(payload)

    assert parsed.source_byte_length == 2_738
    assert parsed.source_sha256 == ("sha256:4138f9326d17aa347defe7c0554477b3a2ada5ee9a7a45bbbef238fc73a3338c")
    assert len(parsed.legislative_subjects) == 16
    assert parsed.legislative_subjects[0] == crs.CRSBillSubjectAssignment(
        category="legislativeSubject",
        official_label="Congressional oversight",
        assignment_update_date="2021-09-17T17:30:20Z",
        identifiers=(),
    )
    assert parsed.policy_area == crs.CRSBillSubjectAssignment(
        category="policyArea",
        official_label="Government Operations and Politics",
        assignment_update_date="2021-05-18T14:45:17Z",
        identifiers=(),
    )


def test_api_shape_change_with_unreviewed_fields_fails_closed() -> None:
    payload = b"""
    {
      "pagination": {"count": 1},
      "request": {"billUrl": "https://api.congress.gov/v3/bill/119/hr/1?format=json"},
      "subjects": {
        "legislativeSubjects": [
          {"name": "Taxation", "updateDate": "2026-01-01T00:00:00Z", "slug": "taxation"}
        ]
      }
    }
    """

    with pytest.raises(crs.CRSSourceDriftError, match="unreviewed fields"):
        crs.parse_crs_bill_subject_assignments(payload)


def test_api_parser_preserves_a_future_publisher_identifier_instead_of_minting_one() -> None:
    payload = b"""
    {
      "pagination": {"count": 1},
      "request": {"billUrl": "https://api.congress.gov/v3/bill/119/hr/1?format=json"},
      "subjects": {
        "legislativeSubjects": [
          {
            "name": "Taxation",
            "updateDate": "2026-01-01T00:00:00Z",
            "id": "publisher-term-42",
            "uri": "https://api.congress.gov/v3/legislative-subject/publisher-term-42"
          }
        ]
      }
    }
    """

    parsed = crs.parse_crs_bill_subject_assignments(payload)

    assert parsed.legislative_subjects[0].publisher_identifier == "publisher-term-42"
    assert parsed.legislative_subjects[0].publisher_term_iri == (
        "https://api.congress.gov/v3/legislative-subject/publisher-term-42"
    )
    assert parsed.legislative_subjects[0].identity_status == "publisherIdentifierPresent"


def test_api_parser_retains_multiple_structured_identifiers_without_conflict() -> None:
    payload = b"""
    {
      "pagination": {"count": 1},
      "request": {"billUrl": "https://api.congress.gov/v3/bill/119/hr/1?format=json"},
      "subjects": {
        "legislativeSubjects": [
          {
            "name": "Taxation",
            "updateDate": "2026-01-01T00:00:00Z",
            "id": "publisher-term-42",
            "identifier": ["alternate-7", "publisher-term-42"],
            "code": "TAX",
            "uri": [
              "https://api.congress.gov/v3/legislative-subject/publisher-term-42",
              "https://id.congress.gov/subject/TAX"
            ],
            "url": "https://id.congress.gov/subject/TAX"
          }
        ]
      }
    }
    """

    parsed = crs.parse_crs_bill_subject_assignments(payload)
    assignment = parsed.legislative_subjects[0]

    assert assignment.publisher_identifiers == (
        "publisher-term-42",
        "alternate-7",
        "TAX",
    )
    assert assignment.publisher_term_iris == (
        "https://api.congress.gov/v3/legislative-subject/publisher-term-42",
        "https://id.congress.gov/subject/TAX",
    )
    assert assignment.publisher_identifier is None
    assert assignment.publisher_term_iri is None
    assert {identifier.kind for identifier in assignment.identifiers} == {
        "publisherId",
        "publisherIdentifier",
        "publisherCode",
        "publisherTermUri",
        "publisherTermUrl",
    }
    assert all(
        identifier.authority_uri == "https://www.congress.gov/"
        and identifier.source_uri == "https://api.congress.gov/v3/bill/119/hr/1?format=json"
        and identifier.observed_at is None
        and identifier.effective_at == "2026-01-01T00:00:00Z"
        and identifier.source_digest == parsed.source_sha256
        for identifier in assignment.identifiers
    )


def test_fixture_digest_is_derived_from_exact_bytes() -> None:
    payload = _payload("crs-bill-subjects-117-hr-3076.json")

    assert crs.sha256_digest(payload) == "sha256:" + hashlib.sha256(payload).hexdigest()
