"""NRC ADAMS identifier-shape and current search-facet capture and parsing tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import nrc_adams_codes as adams

FIXTURES = Path(__file__).parent / "fixtures" / "nrc_adams_codes"
LANDING_FIXTURE = FIXTURES / "nrc-adams-landing-page-2026-08-03.html"
HELP_REFERENCE_FIXTURE = FIXTURES / "nrc-adams-help-reference-2026-08-03.html"
FAQ_FIXTURE = FIXTURES / "nrc-adams-faq-2026-08-03.html"
RESULT_FIELD_FIXTURE = FIXTURES / "nrc-aps-result-field-labels-excerpt-2026-08-03.js"
LIBRARY_FACET_FIXTURE = FIXTURES / "nrc-aps-library-facet-labels-excerpt-2026-08-03.js"
SYSTEM_NOTICES_FIXTURE = FIXTURES / "nrc-adams-system-notices-2026-08-03.html"


def _acquire(tmp_path: Path, pin: adams.AdamsSnapshotPin, source_path: Path) -> adams.AcquiredAdamsSource:
    return adams.acquire_adams_source(pin, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> adams.NrcAdamsControlPortfolio:
    faq = _acquire(tmp_path, adams.NRC_ADAMS_FAQ_2026_08_03, FAQ_FIXTURE)
    landing = _acquire(tmp_path, adams.NRC_ADAMS_LANDING_PAGE_2026_08_03, LANDING_FIXTURE)
    help_reference = _acquire(tmp_path, adams.NRC_ADAMS_HELP_REFERENCE_2026_08_03, HELP_REFERENCE_FIXTURE)
    result_fields = _acquire(tmp_path, adams.NRC_APS_RESULT_FIELD_LABELS_2026_08_03, RESULT_FIELD_FIXTURE)
    library_facets = _acquire(tmp_path, adams.NRC_APS_LIBRARY_FACET_LABELS_2026_08_03, LIBRARY_FACET_FIXTURE)
    return adams.assemble_nrc_adams_control_portfolio(
        docket_number_shape=adams.parse_docket_number_shape(faq),
        legacy_library_accession_number_shape=adams.parse_legacy_library_accession_number_shape(faq),
        current_accession_number_shape=adams.parse_current_accession_number_shape(landing),
        docket_number_category_links=adams.parse_docket_number_category_links(help_reference),
        aps_result_field_labels=adams.parse_aps_result_field_labels(result_fields),
        aps_library_facet_labels=adams.parse_aps_library_facet_labels(library_facets),
    )


def test_fixture_pins_match_exact_real_captured_bytes() -> None:
    pins = (
        (LANDING_FIXTURE, adams.NRC_ADAMS_LANDING_PAGE_2026_08_03),
        (HELP_REFERENCE_FIXTURE, adams.NRC_ADAMS_HELP_REFERENCE_2026_08_03),
        (FAQ_FIXTURE, adams.NRC_ADAMS_FAQ_2026_08_03),
        (RESULT_FIELD_FIXTURE, adams.NRC_APS_RESULT_FIELD_LABELS_2026_08_03),
        (LIBRARY_FACET_FIXTURE, adams.NRC_APS_LIBRARY_FACET_LABELS_2026_08_03),
        (SYSTEM_NOTICES_FIXTURE, adams.NRC_ADAMS_SYSTEM_NOTICES_2026_08_03),
    )
    for fixture_path, pin in pins:
        payload = fixture_path.read_bytes()
        assert len(payload) == pin.expected_byte_length
        assert adams.sha256_digest(payload) == pin.expected_sha256

    assert adams.NRC_ADAMS_LANDING_PAGE_2026_08_03.capture_kind == "fullOfficialResponse"
    assert adams.NRC_APS_RESULT_FIELD_LABELS_2026_08_03.capture_kind == "verbatimExcerptOfLargerOfficialAsset"
    assert adams.NRC_APS_RESULT_FIELD_LABELS_2026_08_03.full_asset_byte_length == 1_578_086


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(tmp_path: Path) -> None:
    pin = adams.NRC_ADAMS_FAQ_2026_08_03

    acquired = _acquire(tmp_path, pin, FAQ_FIXTURE)
    cached = adams.acquire_adams_source(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = RESULT_FIELD_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> adams.FetchedAdamsResponse:
            calls.append((source_url, timeout_seconds))
            return adams.FetchedAdamsResponse(
                body=payload,
                status_code=200,
                content_type="text/javascript; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = adams.acquire_adams_source(
        adams.NRC_APS_RESULT_FIELD_LABELS_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(adams.NRC_APS_RESULT_FIELD_LABELS_SOURCE.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_aps_result_field_labels_are_deterministic_metadata_not_subjects(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path, adams.NRC_APS_RESULT_FIELD_LABELS_2026_08_03, RESULT_FIELD_FIXTURE)
    codes = adams.parse_aps_result_field_labels(acquired)

    assert [code.publisher_label for code in codes] == [
        "Author(s)",
        "Author Affiliation",
        "Addressee Name",
        "Addressee Affiliation",
        "Case Reference Number",
        "License Number",
        "Document Date",
        "Document Type",
        "Document Report Number",
        "Docket Number",
        "Date Docketed",
        "Comment",
    ]
    docket_row = next(code for code in codes if code.publisher_label == "Docket Number")
    assert [identifier.kind for identifier in docket_row.identifiers] == [
        "apsResultFieldLabel",
        "apsResultFieldPropertyKey",
    ]
    assert docket_row.identifiers[1].value == "DocketNumber"
    assert all(code.use == "deterministicMetadata" for code in codes)
    assert all(not code.is_general_subject_concept for code in codes)


def test_aps_library_facet_labels_are_captured(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path, adams.NRC_APS_LIBRARY_FACET_LABELS_2026_08_03, LIBRARY_FACET_FIXTURE)
    codes = adams.parse_aps_library_facet_labels(acquired)

    assert [(code.publisher_label, code.identifiers[1].value) for code in codes] == [
        ("Public Main Library", "mainLibFilter"),
        ("Public Legacy Library", "legacyLibFilter"),
    ]
    assert all(code.identifiers[0].kind == "apsLibraryFacetLabel" for code in codes)
    assert all(code.identifiers[1].kind == "apsLibraryFacetControlName" for code in codes)


def test_docket_number_category_links_are_captured(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path, adams.NRC_ADAMS_HELP_REFERENCE_2026_08_03, HELP_REFERENCE_FIXTURE)
    codes = adams.parse_docket_number_category_links(acquired)

    assert [code.publisher_label for code in codes] == [
        "List of Power Reactors and Docket Numbers",
        "Source Materials Licenses",
        "Special Nuclear Materials Licenses",
        "Spent Fuel and Dry Cask Licenses",
        "High Level Waste and Low Level Waste Docket Numbers",
    ]
    source_materials = next(code for code in codes if code.publisher_label == "Source Materials Licenses")
    assert source_materials.identifiers[1].kind == "docketNumberCategoryReferenceUrl"
    assert source_materials.identifiers[1].value.endswith("docket40.pdf")


def test_docket_number_shape_matches_documented_examples_and_rejects_hyphenated_form(
    tmp_path: Path,
) -> None:
    acquired = _acquire(tmp_path, adams.NRC_ADAMS_FAQ_2026_08_03, FAQ_FIXTURE)
    shape = adams.parse_docket_number_shape(acquired)

    assert shape.identifier_kind == "docketNumber"
    assert shape.shape_basis == "publisherDocumentedProse"
    assert shape.sample_values == ("05000271", "05200017", "07007001")
    assert shape.matches("05000271") is True
    assert shape.matches("50-271") is False
    assert shape.matches("0500027") is False
    assert any("50-271" in note for note in shape.raw_notes)
    assert any("Docket 52 (new reactors)" in note for note in shape.raw_notes)


def test_legacy_library_accession_number_shape_has_no_textual_sample_but_validates_digits(
    tmp_path: Path,
) -> None:
    acquired = _acquire(tmp_path, adams.NRC_ADAMS_FAQ_2026_08_03, FAQ_FIXTURE)
    shape = adams.parse_legacy_library_accession_number_shape(acquired)

    assert shape.identifier_kind == "legacyLibraryAccessionNumber"
    assert shape.sample_values == ()
    assert shape.matches("1234567890") is True
    assert shape.matches("123456789") is False
    assert any("NUDOCS" in note for note in shape.raw_notes)


def test_current_accession_number_shape_is_inferred_from_real_examples(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path, adams.NRC_ADAMS_LANDING_PAGE_2026_08_03, LANDING_FIXTURE)
    shape = adams.parse_current_accession_number_shape(acquired)

    assert shape.identifier_kind == "currentAccessionNumber"
    assert shape.shape_basis == "observedFromRealExamples"
    assert shape.sample_values == ("ML25017A086", "ml050630229")
    assert shape.matches("ML25017A086") is True
    assert shape.matches("ml050630229") is True
    assert shape.matches("ML250") is False
    assert (
        "not state" in shape.explanation.lower()
        or "does not state" in shape.explanation.lower()
        or "states" in shape.explanation.lower()
    )


def test_portfolio_records_documented_gaps(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert any("content-hashed filename" in gap for gap in portfolio.gaps)
    assert any("License Number is a confirmed APS result-field label" in gap for gap in portfolio.gaps)
    assert any("not kept in sync" in gap for gap in portfolio.gaps)
    assert portfolio.gaps == adams.NRC_ADAMS_PORTFOLIO_GAPS


def test_validate_adams_identifiers_accepts_known_shapes_and_fields(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    record = {
        "docket_number": "05000271",
        "accession_number": "ML25017A086",
        "aps_search_field": "Docket Number",
    }

    validated = adams.validate_adams_identifiers(record, portfolio)

    assert validated.docket_number == "05000271"
    assert validated.legacy_accession_number is None
    assert validated.current_accession_number == "ML25017A086"
    assert validated.aps_search_field is not None
    assert validated.aps_search_field.publisher_label == "Docket Number"
    assert validated.gaps == portfolio.gaps


def test_record_without_any_identifier_fields_still_validates(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    validated = adams.validate_adams_identifiers({}, portfolio)

    assert validated.docket_number is None
    assert validated.legacy_accession_number is None
    assert validated.current_accession_number is None
    assert validated.aps_search_field is None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("docket_number", "50-271", "does not match the documented 8-digit shape"),
        ("legacy_accession_number", "12345", "does not match the documented 10-digit shape"),
        ("accession_number", "not-an-accession-number", "does not match the observed ML-number shape"),
        ("aps_search_field", "Invented Field", "unknown APS search field"),
    ],
)
def test_malformed_or_unknown_identifier_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    portfolio = _portfolio(tmp_path)

    with pytest.raises(adams.AdamsAssignmentError, match=message):
        adams.validate_adams_identifiers({field: value}, portfolio)


def test_digest_drift_never_becomes_an_acquired_source(tmp_path: Path) -> None:
    payload = FAQ_FIXTURE.read_bytes()
    changed = payload.replace(b"05000271", b"0500027")
    assert len(changed) != len(payload)

    class ChangedFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> adams.FetchedAdamsResponse:
            del timeout_seconds
            return adams.FetchedAdamsResponse(
                body=changed,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(adams.AdamsSourceDriftError, match="byte length drift"):
        adams.acquire_adams_source(
            adams.NRC_ADAMS_FAQ_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def test_structural_shape_drift_never_becomes_a_parsed_resource(tmp_path: Path) -> None:
    # A byte-faithful but restructured excerpt: only 4 of the 5 license
    # categories survive. The parser must reject the count drift rather than
    # silently returning a shorter list.
    mini_payload = (
        b'<h2 id="ListofLicenses">Lists of Licenses and Docket Numbers</h2><ul>'
        b'<li data-list-item-id="aaaa1111"><a href="/a">Category A</a></li>'
        b'<li data-list-item-id="bbbb2222"><a href="/b">Category B</a></li>'
        b'<li data-list-item-id="cccc3333"><a href="/c">Category C</a></li>'
        b'<li data-list-item-id="dddd4444"><a href="/d">Category D</a></li>'
        b"</ul>"
    )
    mini_source = replace(adams.NRC_ADAMS_HELP_REFERENCE, filename="mini-help-reference.html")
    mini_pin = adams.AdamsSnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T19:29:40Z",
        expected_sha256=adams.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
        capture_kind="fullOfficialResponse",
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_payload)
    acquired = adams.acquire_adams_source(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(adams.AdamsSourceDriftError, match="category count drift"):
        adams.parse_docket_number_category_links(acquired)


def test_missing_docket_sentence_fails_closed(tmp_path: Path) -> None:
    mini_payload = b"<p>Nothing about docket numbers here.</p>"
    mini_source = replace(adams.NRC_ADAMS_FAQ, filename="mini-faq.html")
    mini_pin = adams.AdamsSnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T19:29:41Z",
        expected_sha256=adams.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
        capture_kind="fullOfficialResponse",
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_payload)
    acquired = adams.acquire_adams_source(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(adams.AdamsSourceDriftError, match="docket-number format paragraph"):
        adams.parse_docket_number_shape(acquired)


def test_accession_number_format_is_publisher_stated_on_system_notices_page(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path, adams.NRC_ADAMS_SYSTEM_NOTICES_2026_08_03, SYSTEM_NOTICES_FIXTURE)
    shape = adams.parse_accession_number_format_notice(acquired)

    assert shape.identifier_kind == "currentAccessionNumber"
    assert shape.shape_basis == "publisherDocumentedProse"
    assert shape.sample_values == ("ML100010001", "ML10001A001")
    assert shape.source_url == adams.NRC_ADAMS_SYSTEM_NOTICES_URL
    # Both publisher-stated forms validate; a letter anywhere but the
    # example's position does not.
    assert shape.matches("ML100010001")
    assert shape.matches("ML10001A001")
    assert shape.matches("ml10001A001")
    assert not shape.matches("ML1000A0001")
    assert not shape.matches("ML10001A01")
    assert not shape.matches("NUDOCS9604040088")


def test_missing_format_notice_sentence_fails_closed(tmp_path: Path) -> None:
    mini_payload = b"<p>System notices, but not the renumbering announcement.</p>"
    mini_source = replace(adams.NRC_ADAMS_SYSTEM_NOTICES, filename="mini-system-notices.html")
    mini_pin = adams.AdamsSnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T23:04:00Z",
        expected_sha256=adams.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
        capture_kind="fullOfficialResponse",
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_payload)
    acquired = adams.acquire_adams_source(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(adams.AdamsSourceDriftError, match="format notice sentence"):
        adams.parse_accession_number_format_notice(acquired)


def test_portfolio_assembly_requires_every_resource(tmp_path: Path) -> None:
    faq = _acquire(tmp_path, adams.NRC_ADAMS_FAQ_2026_08_03, FAQ_FIXTURE)
    landing = _acquire(tmp_path, adams.NRC_ADAMS_LANDING_PAGE_2026_08_03, LANDING_FIXTURE)
    help_reference = _acquire(tmp_path, adams.NRC_ADAMS_HELP_REFERENCE_2026_08_03, HELP_REFERENCE_FIXTURE)
    result_fields = _acquire(tmp_path, adams.NRC_APS_RESULT_FIELD_LABELS_2026_08_03, RESULT_FIELD_FIXTURE)

    with pytest.raises(adams.AdamsSourceDriftError, match="requires every captured resource"):
        adams.assemble_nrc_adams_control_portfolio(
            docket_number_shape=adams.parse_docket_number_shape(faq),
            legacy_library_accession_number_shape=adams.parse_legacy_library_accession_number_shape(faq),
            current_accession_number_shape=adams.parse_current_accession_number_shape(landing),
            docket_number_category_links=adams.parse_docket_number_category_links(help_reference),
            aps_result_field_labels=adams.parse_aps_result_field_labels(result_fields),
            aps_library_facet_labels=(),
        )


def test_source_url_and_host_are_pinned_to_official_nrc_domains() -> None:
    assert adams.NRC_ADAMS_FAQ.source_url == "https://www.nrc.gov/reading-rm/adams/faq.html"
    with pytest.raises(adams.AdamsAcquisitionError, match="official HTTPS www.nrc.gov"):
        adams.AdamsSource(resource_name="faqPage", source_url="https://example.com/faq.html", filename="x.html")

    assert adams.NRC_APS_RESULT_FIELD_LABELS_SOURCE.source_url == adams.NRC_APS_SEARCH_BUNDLE_URL
    with pytest.raises(adams.AdamsAcquisitionError, match="official HTTPS adams-search.nrc.gov"):
        adams.AdamsSource(
            resource_name="apsResultFieldLabels",
            source_url="https://example.com/main.js",
            filename="x.js",
        )


def test_excerpt_pin_requires_parent_asset_provenance() -> None:
    with pytest.raises(adams.AdamsAcquisitionError, match="must record its full_asset_sha256"):
        adams.AdamsSnapshotPin(
            source=adams.NRC_APS_RESULT_FIELD_LABELS_SOURCE,
            retrieved_at="2026-08-03T19:33:10Z",
            expected_sha256=adams.sha256_digest(b"x"),
            expected_byte_length=1,
            capture_kind="verbatimExcerptOfLargerOfficialAsset",
        )
    with pytest.raises(adams.AdamsAcquisitionError, match="must not declare a parent asset"):
        adams.AdamsSnapshotPin(
            source=adams.NRC_ADAMS_FAQ,
            retrieved_at="2026-08-03T19:29:41Z",
            expected_sha256=adams.sha256_digest(b"x"),
            expected_byte_length=1,
            capture_kind="fullOfficialResponse",
            full_asset_sha256=adams.sha256_digest(b"y"),
            full_asset_byte_length=2,
        )
