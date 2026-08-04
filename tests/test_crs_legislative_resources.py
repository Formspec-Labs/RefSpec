"""CRS Legislative Subject Term and Policy Area source-foundation tests."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import crs_legislative_resources as crs
from refspec.registry.infrastructure.source_identity import derive_uuid7

FIXTURES = Path(__file__).parent / "fixtures"
REFSPEC_ROOT = Path(__file__).resolve().parents[1]
FULL_CAPTURE_SPECS = (
    (
        crs.CRS_LEGISLATIVE_SUBJECTS_PAGE,
        "REFSPEC_CRS_LEGISLATIVE_SUBJECTS_PATH",
        (
            "output/refspec-vocabulary-portfolio/crs/2026-07-30/sha256/"
            "8b4964a8cea53d63bce0a029bac38a2bc260059883120bc36e1759a4b5e844d1/"
            "legislative-subject-terms.html"
        ),
        "sha256:8b4964a8cea53d63bce0a029bac38a2bc260059883120bc36e1759a4b5e844d1",
        410_454,
    ),
    (
        crs.CRS_LEGISLATIVE_GEOGRAPHIC_PAGE,
        "REFSPEC_CRS_LEGISLATIVE_GEOGRAPHIC_PATH",
        (
            "output/refspec-vocabulary-portfolio/crs/2026-07-30/sha256/"
            "7dfefc6e8b17b3a86a9c9009453e792453eef01b099177ef29f4dc172d19d3d0/"
            "legislative-subject-geographic-entities.html"
        ),
        "sha256:7dfefc6e8b17b3a86a9c9009453e792453eef01b099177ef29f4dc172d19d3d0",
        384_627,
    ),
    (
        crs.CRS_LEGISLATIVE_ORGANIZATIONS_PAGE,
        "REFSPEC_CRS_LEGISLATIVE_ORGANIZATIONS_PATH",
        (
            "output/refspec-vocabulary-portfolio/crs/2026-07-30/sha256/"
            "fa870ff36352c3482a68aad4d9cff69bd8ff98294a7dd21b1e36f0a534b2b880/"
            "legislative-subject-organization-names.html"
        ),
        "sha256:fa870ff36352c3482a68aad4d9cff69bd8ff98294a7dd21b1e36f0a534b2b880",
        381_186,
    ),
    (
        crs.CRS_POLICY_AREAS_PAGE,
        "REFSPEC_CRS_POLICY_AREAS_PATH",
        (
            "output/refspec-vocabulary-portfolio/crs/2026-07-30/sha256/"
            "16d806e4a07df391de776d0bd5fade9d0bce89fe33b564036c94e0749df91326/"
            "policy-areas.html"
        ),
        "sha256:16d806e4a07df391de776d0bd5fade9d0bce89fe33b564036c94e0749df91326",
        383_558,
    ),
)


def _payload(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _pin(source: crs.CRSPageSource, payload: bytes) -> crs.CRSPageSnapshotPin:
    return crs.CRSPageSnapshotPin(
        source=source,
        retrieved_at="2026-07-30T12:33:34Z",
        fetch_id=derive_uuid7(
            "2026-07-30T12:33:34Z",
            seed=f"fixture-fetch:{source.term_category}".encode(),
        ),
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
    assert crs.crs_source_scheme("legislativeSubjectTerms") == crs.CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME
    assert crs.crs_source_scheme("policyAreas") == crs.CRS_POLICY_AREAS_SCHEME


def test_all_four_full_publisher_pages_parse_to_observed_current_counts(tmp_path: Path) -> None:
    parsed = []
    for source, environment_name, default_path, digest, byte_length in FULL_CAPTURE_SPECS:
        path = Path(os.environ.get(environment_name, REFSPEC_ROOT / default_path))
        if not path.is_file():
            pytest.skip(f"full CRS publisher capture is unavailable: {path}")
        pin = crs.CRSPageSnapshotPin(
            source=source,
            retrieved_at="2026-07-30T12:46:40Z",
            fetch_id=derive_uuid7("2026-07-30T12:46:40Z", seed=source.source_url.encode()),
            expected_sha256=digest,
            expected_byte_length=byte_length,
        )
        acquired = crs.acquire_crs_page(pin, tmp_path / "full", source_path=path)
        parsed.append(crs.parse_crs_field_value_page(acquired))

    detailed = crs.assemble_crs_legislative_subject_terms(parsed[:3])
    policy = crs.assemble_crs_policy_areas(parsed[3])

    assert len(detailed.terms) == 1_043
    assert [len(page.terms) for page in detailed.pages] == [565, 301, 177]
    assert len(policy.terms) == 32


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
    assert resource.source_scheme == crs.CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME
    assert resource.source_scheme.scheme_iri == "http://id.loc.gov/vocabulary/subjectSchemes/lst"
    assert resource.source_scheme.code == "lst"
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
    assert resource.source_scheme == crs.CRS_POLICY_AREAS_SCHEME
    assert resource.source_scheme.scheme_iri == "http://id.loc.gov/vocabulary/subjectSchemes/cgpa"
    assert resource.source_scheme.code == "cgpa"
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
