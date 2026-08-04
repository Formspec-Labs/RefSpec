"""FERC eLibrary class/type, docket-prefix, sector, and security capture and parsing tests."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import ferc_elibrary_codes as ferc
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier

FIXTURES = Path(__file__).parent / "fixtures" / "ferc_elibrary_codes"
PAGE_FIXTURE = FIXTURES / "ferc-elibrary-classtype-information-fixture.html"


def _acquire(tmp_path: Path, source_path: Path = PAGE_FIXTURE) -> ferc.AcquiredFercSource:
    return ferc.acquire_ferc_elibrary_page(ferc.FERC_ELIBRARY_2026_08_03_FIXTURE, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> ferc.FercELibraryControlPortfolio:
    acquired = _acquire(tmp_path)
    resources = [
        ferc.parse_ferc_elibrary_resource(acquired, name)
        for name in ("documentClass", "documentType", "docketPrefix", "sector", "securityLevel")
    ]
    accession = ferc.parse_ferc_accession_number_format(acquired)
    return ferc.assemble_ferc_elibrary_control_portfolio(resources, accession)


def test_fixture_pin_matches_exact_constructed_reference_bytes() -> None:
    payload = PAGE_FIXTURE.read_bytes()

    assert len(payload) == 2_202
    assert ferc.sha256_digest(payload) == ("sha256:265f506c80143ae9ec97bcac215f7f19eeb3b5620e699d8442b84ced892e2874")
    assert ferc.FERC_ELIBRARY_2026_08_03_FIXTURE.provenance == "constructedFixture"


def test_full_official_class_type_pdf_shape_count_and_samples() -> None:
    source_path = os.environ.get("REFSPEC_FERC_CLASS_TYPES_2025_PDF_PATH")
    if source_path is None:
        pytest.skip("full official FERC class/type PDF is not materialized")

    capture = ferc.parse_ferc_class_type_pdf(Path(source_path).read_bytes())

    assert capture.source_url == ferc.FERC_CLASS_TYPE_PDF_URL
    assert capture.source_sha256 == ferc.FERC_CLASS_TYPE_PDF_SHA256
    assert capture.source_byte_length == 193_934
    assert capture.page_count == 7
    assert len(capture.rows) == 235
    assert sum(row.category == "Issuance" for row in capture.rows) == 54
    assert sum(row.category == "Submittal" for row in capture.rows) == 181
    assert capture.rows[0].text.endswith(
        "ALJ Initial Decision/Certification of Initial Decision and Record"
    )
    assert capture.rows[-1].text.endswith("Form 552 ‐ Annual Report of Natural Gas Transactions")


def test_full_official_docket_prefix_pdf_shape_count_and_samples() -> None:
    source_path = os.environ.get("REFSPEC_FERC_DOCKET_PREFIX_2025_PDF_PATH")
    if source_path is None:
        pytest.skip("full official FERC docket-prefix PDF is not materialized")

    capture = ferc.parse_ferc_docket_prefix_pdf(Path(source_path).read_bytes())

    assert capture.source_url == ferc.FERC_DOCKET_PREFIX_PDF_URL
    assert capture.source_sha256 == ferc.FERC_DOCKET_PREFIX_PDF_SHA256
    assert capture.source_byte_length == 282_729
    assert capture.page_count == 6
    assert len(capture.rows) == 95
    assert sum(row.status == "active" for row in capture.rows) == 77
    assert sum(row.status == "discontinued" for row in capture.rows) == 18
    assert capture.rows[0] == ferc.FercPublishedDocketPrefixRow(
        status="active",
        prefix="AC",
        library="Gen",
        definition="Requests for Approval by Chief Accountant",
    )
    assert capture.rows[-1].prefix == "TA"
    assert capture.rows[-1].definition == "Annual Tracking Filings of Interstate Natural Gas Pipelines"


def test_official_search_help_sector_security_shape_and_samples() -> None:
    source_path = os.environ.get("REFSPEC_FERC_GENERAL_SEARCH_HELP_PATH")
    if source_path is None:
        pytest.skip("official FERC general-search help is not materialized")

    capture = ferc.parse_ferc_general_search_help(Path(source_path).read_bytes())

    assert capture.source_url == ferc.FERC_GENERAL_SEARCH_HELP_URL
    assert capture.source_sha256 == ferc.FERC_GENERAL_SEARCH_HELP_SHA256
    assert capture.source_byte_length == 7_447
    assert capture.sectors == ("Electric", "Natural Gas", "Oil", "Rulemaking", "Hydro", "General")
    assert capture.security_levels == ("CEII", "Protected", "Priviledged", "Public")


def test_official_accessibility_help_accession_formats() -> None:
    source_path = os.environ.get("REFSPEC_FERC_ACCESSIBILITY_TIPS_PATH")
    if source_path is None:
        pytest.skip("official FERC accessibility guide is not materialized")

    capture = ferc.parse_ferc_accessibility_tips(Path(source_path).read_bytes())

    assert capture.source_url == ferc.FERC_ACCESSIBILITY_TIPS_URL
    assert capture.source_sha256 == ferc.FERC_ACCESSIBILITY_TIPS_SHA256
    assert capture.source_byte_length == 39_466
    assert capture.accession_formats == ("19940824-0052", "19940824*")


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = ferc.FERC_ELIBRARY_2026_08_03_FIXTURE

    acquired = _acquire(tmp_path)
    cached = ferc.acquire_ferc_elibrary_page(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = PAGE_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> ferc.FetchedFercResponse:
            calls.append((source_url, timeout_seconds))
            return ferc.FetchedFercResponse(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = ferc.acquire_ferc_elibrary_page(
        ferc.FERC_ELIBRARY_2026_08_03_FIXTURE,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(ferc.FERC_ELIBRARY_SOURCE.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_document_classes_are_deterministic_metadata_not_general_subject_concepts(
    tmp_path: Path,
) -> None:
    resource = ferc.parse_ferc_elibrary_resource(_acquire(tmp_path), "documentClass")

    assert [code.publisher_label for code in resource.codes] == ["Correspondence", "Filing", "Order"]
    assert resource.by_code()["Filing"] == ferc.FercCode(
        resource_name="documentClass",
        use="deterministicMetadata",
        publisher_label="Filing",
        source_url=ferc.FERC_ELIBRARY_SOURCE.source_url,
        identifiers=(
            ControlledIdentifier(
                value="Filing",
                kind="documentClassLabel",
                authority_uri=ferc.FERC_IDENTIFIER_AUTHORITY_URI,
                source_uri=ferc.FERC_ELIBRARY_SOURCE.source_url,
                observed_at=ferc.FERC_ELIBRARY_2026_08_03_FIXTURE.retrieved_at,
                effective_at=None,
                source_digest=ferc.FERC_ELIBRARY_2026_08_03_FIXTURE.expected_sha256,
            ),
        ),
        is_general_subject_concept=False,
    )
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_document_types_retain_their_parent_class_as_a_second_identifier(
    tmp_path: Path,
) -> None:
    resource = ferc.parse_ferc_elibrary_resource(_acquire(tmp_path), "documentType")

    assert len(resource.codes) == 7
    compliance_filing = resource.by_code()["Compliance Filing"]
    assert [identifier.kind for identifier in compliance_filing.identifiers] == [
        "documentTypeLabel",
        "documentClassLabel",
    ]
    assert compliance_filing.identifiers[0].value == "Compliance Filing"
    assert compliance_filing.identifiers[1].value == "Filing"
    assert compliance_filing.use == "deterministicMetadata"
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_docket_prefixes_are_short_publisher_codes(tmp_path: Path) -> None:
    resource = ferc.parse_ferc_elibrary_resource(_acquire(tmp_path), "docketPrefix")

    assert len(resource.codes) == 8
    assert resource.by_code()["CP"].publisher_label == "Certificate - Natural Gas Pipeline"
    assert resource.by_code()["RM"].publisher_label == "Rulemaking"
    assert all(code.identifiers[0].kind == "docketPrefixCode" for code in resource.codes)
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_sectors_and_security_levels_are_captured(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    sectors = ferc.parse_ferc_elibrary_resource(acquired, "sector")
    security = ferc.parse_ferc_elibrary_resource(acquired, "securityLevel")

    assert [code.publisher_label for code in sectors.codes] == [
        "Electric",
        "Natural Gas",
        "Hydropower",
        "Oil",
        "Certificates",
    ]
    assert [code.publisher_label for code in security.codes] == ["Public", "Privileged", "CEII"]
    assert security.by_code()["CEII"].identifiers[0].kind == "securityLevelCode"
    assert all(code.use == "deterministicMetadata" for code in (*sectors.codes, *security.codes))


def test_accession_number_format_is_a_pattern_not_an_enumerated_code_list(
    tmp_path: Path,
) -> None:
    accession = ferc.parse_ferc_accession_number_format(_acquire(tmp_path))

    assert accession.pattern == "YYYYMMDD-NNNN"
    assert "daily sequence number" in accession.explanation


def test_portfolio_records_acquisition_and_cross_agency_gaps(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert any("HTTP 403" in gap for gap in portfolio.gaps)
    assert any("constructed reference fixture" in gap for gap in portfolio.gaps)
    assert any("does not publish a list revision number" in gap for gap in portfolio.gaps)
    assert any("must not reuse a FERC docket prefix" in gap for gap in portfolio.gaps)
    assert portfolio.accession_number_format.pattern == "YYYYMMDD-NNNN"


def test_current_ferc_document_fields_validate_without_becoming_subjects(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    record = {
        "document_type": "Compliance Filing",
        "docket_prefix": "RP",
        "sector": "Natural Gas",
        "security_level": "Public",
    }

    validated = ferc.validate_ferc_elibrary_fields(record, portfolio)

    assert validated.document_type.publisher_label == "Compliance Filing"
    assert validated.docket_prefix.publisher_label == "Rate - Natural Gas Pipeline"
    assert validated.sector is not None
    assert validated.sector.publisher_label == "Natural Gas"
    assert validated.security_level.publisher_label == "Public"
    assert all(
        not assignment.is_general_subject_concept
        for assignment in (validated.document_type, validated.docket_prefix, validated.security_level)
    )


def test_record_without_optional_sector_still_validates(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    record = {
        "document_type": "Letter",
        "docket_prefix": "AC",
        "security_level": "Privileged",
    }

    validated = ferc.validate_ferc_elibrary_fields(record, portfolio)

    assert validated.sector is None
    assert validated.docket_prefix.publisher_label == "Accounting"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("document_type", "Invented Type", "unknown FERC eLibrary document_type"),
        ("docket_prefix", "ZZ", "unknown FERC eLibrary docket_prefix"),
        ("sector", "Space", "unknown FERC eLibrary sector"),
        ("security_level", "Top Secret", "unknown FERC eLibrary security_level"),
    ],
)
def test_unknown_field_value_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    portfolio = _portfolio(tmp_path)
    record = {
        "document_type": "Letter",
        "docket_prefix": "AC",
        "security_level": "Public",
        field: value,
    }

    with pytest.raises(ferc.FercAssignmentError, match=message):
        ferc.validate_ferc_elibrary_fields(record, portfolio)


def test_missing_required_field_fails_closed(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    with pytest.raises(ferc.FercAssignmentError, match="must carry a string document_type"):
        ferc.validate_ferc_elibrary_fields({}, portfolio)


def test_digest_drift_never_becomes_an_acquired_source(tmp_path: Path) -> None:
    payload = PAGE_FIXTURE.read_bytes()
    changed = payload.replace(b">Rulemaking<", b">Rulemakinh<")
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> ferc.FetchedFercResponse:
            del timeout_seconds
            return ferc.FetchedFercResponse(
                body=changed,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(ferc.FercSourceDriftError, match="digest drift"):
        ferc.acquire_ferc_elibrary_page(
            ferc.FERC_ELIBRARY_2026_08_03_FIXTURE,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def test_structural_shape_drift_never_becomes_a_parsed_resource(tmp_path: Path) -> None:
    # A byte-faithful but restructured document: Sectors keeps only 4 of its 5
    # rows. The parser must reject the count drift rather than silently
    # returning a shorter list.
    mini_payload = (
        b"<!doctype html>\n<title>eLibrary Class/Type Information</title>\n"
        b"<h2>Sectors</h2>\n<table>\n<thead>\n<tr><th>Sector</th></tr>\n</thead>\n<tbody>\n"
        b"<tr><td>Electric</td></tr>\n<tr><td>Natural Gas</td></tr>\n"
        b"<tr><td>Hydropower</td></tr>\n<tr><td>Oil</td></tr>\n</tbody>\n</table>\n"
    )
    mini_source = replace(ferc.FERC_ELIBRARY_SOURCE, filename="mini-elibrary.html")
    mini_pin = ferc.FercSnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T19:18:32Z",
        expected_sha256=ferc.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
        provenance="constructedFixture",
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_payload)
    acquired = ferc.acquire_ferc_elibrary_page(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(ferc.FercSourceDriftError, match="count drift"):
        ferc.parse_ferc_elibrary_resource(acquired, "sector")


def test_missing_table_fails_closed(tmp_path: Path) -> None:
    mini_payload = b"<!doctype html>\n<title>eLibrary Class/Type Information</title>\n<p>No tables here.</p>\n"
    mini_source = replace(ferc.FERC_ELIBRARY_SOURCE, filename="no-tables.html")
    mini_pin = ferc.FercSnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T19:18:32Z",
        expected_sha256=ferc.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
        provenance="constructedFixture",
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_payload)
    acquired = ferc.acquire_ferc_elibrary_page(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(ferc.FercSourceDriftError, match="table was not found"):
        ferc.parse_ferc_elibrary_resource(acquired, "docketPrefix")


def test_missing_title_marker_fails_closed(tmp_path: Path) -> None:
    mini_payload = b"<!doctype html>\n<title>Some Other Page</title>\n<p>Not eLibrary.</p>\n"
    mini_source = replace(ferc.FERC_ELIBRARY_SOURCE, filename="wrong-title.html")
    mini_pin = ferc.FercSnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T19:18:32Z",
        expected_sha256=ferc.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
        provenance="constructedFixture",
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_payload)

    with pytest.raises(ferc.FercSourceDriftError, match="title marker"):
        ferc.acquire_ferc_elibrary_page(mini_pin, tmp_path / "store", source_path=mini_path)


def test_portfolio_assembly_requires_all_five_resources(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    document_class = ferc.parse_ferc_elibrary_resource(acquired, "documentClass")
    accession = ferc.parse_ferc_accession_number_format(acquired)

    with pytest.raises(ferc.FercSourceDriftError, match="requires exactly one"):
        ferc.assemble_ferc_elibrary_control_portfolio([document_class], accession)


def test_source_url_and_host_are_pinned_to_the_official_ferc_domain() -> None:
    assert ferc.FERC_ELIBRARY_SOURCE.source_url == "https://www.ferc.gov/media/elibrary-classtype-information"
    with pytest.raises(ferc.FercAcquisitionError, match="official HTTPS www.ferc.gov"):
        ferc.FercELibrarySource(source_url="https://example.com/elibrary-classtype-information", filename="x.html")
