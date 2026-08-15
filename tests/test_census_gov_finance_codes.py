"""Census APES/ASPEP government-finance classification code-list capture tests.

These sources are a cross-state mapping reference only (see the catalog
decision for ``Census government-finance classifications``): they never
replace a state's enacted chart of accounts or the legal identity of a state
program. The NASBO State Expenditure Report "Chapters" unit this module once
captured left under REF-032 -- a serial publication's table of contents is
not a publisher-written code list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import census_gov_finance_codes as cgfc
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "census_gov_finance_codes"
FUNCTION_FIXTURE = FIXTURES / "census-aspep-function-item-codes-2026-08-03.html"
FLAGS_FIXTURE = FIXTURES / "census-aspep-data-flag-codes-2026-08-03.html"


def _acquire(
    tmp_path: Path,
    pin: cgfc.CensusFinanceSnapshotPin,
    source_path: Path,
) -> cgfc.AcquiredCensusFinancePage:
    return cgfc.acquire_census_finance_page(pin, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> cgfc.CensusFinancePortfolio:
    functions = cgfc.parse_census_function_item_codes(
        _acquire(tmp_path, cgfc.CENSUS_FUNCTION_ITEM_CODES_2026_08_03, FUNCTION_FIXTURE)
    )
    flags = cgfc.parse_census_data_flag_codes(_acquire(tmp_path, cgfc.CENSUS_DATA_FLAG_CODES_2026_08_03, FLAGS_FIXTURE))
    return cgfc.assemble_census_finance_portfolio((functions, flags))


def test_module_import_opens_no_network_connection() -> None:
    # Importing must never perform I/O; only an explicit fetcher call may.
    assert hasattr(cgfc, "acquire_census_finance_page")
    assert hasattr(cgfc, "CensusFinancePageFetcher")


def test_live_snapshot_pins_match_exact_official_bytes() -> None:
    functions = FUNCTION_FIXTURE.read_bytes()
    flags = FLAGS_FIXTURE.read_bytes()

    assert len(functions) == 321_793
    assert cgfc.sha256_digest(functions) == ("sha256:77b6ddf18572165b6e4526042dacba9fcff80b79cc7f21f1193db3210730dcb3")
    assert len(flags) == 323_893
    assert cgfc.sha256_digest(flags) == ("sha256:ef47e5a56d2997b4a05f1a3d5c6d112c92735bc876990ae03038020d07b19c39")


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = cgfc.CENSUS_FUNCTION_ITEM_CODES_2026_08_03

    acquired = _acquire(tmp_path, pin, FUNCTION_FIXTURE)
    cached = cgfc.acquire_census_finance_page(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = FLAGS_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> cgfc.FetchedCensusFinancePage:
            calls.append((source_url, timeout_seconds))
            return cgfc.FetchedCensusFinancePage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = cgfc.acquire_census_finance_page(
        cgfc.CENSUS_DATA_FLAG_CODES_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=11.0,
    )

    assert calls == [(cgfc.CENSUS_DATA_FLAG_CODES_SOURCE.source_url, 11.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_function_item_codes_are_mapping_metadata_not_general_subject_concepts(
    tmp_path: Path,
) -> None:
    resource = cgfc.parse_census_function_item_codes(
        _acquire(tmp_path, cgfc.CENSUS_FUNCTION_ITEM_CODES_2026_08_03, FUNCTION_FIXTURE)
    )

    assert len(resource.codes) == 33
    by_code = resource.by_code()
    assert by_code["025"].publisher_label == "Judicial & Legal"
    # The publisher's own misspelling is preserved verbatim, not corrected.
    assert by_code["023"].publisher_label == "Financial Adminstration"
    assert by_code["025"].identifiers == (
        cgfc.ControlledIdentifier(
            value="025",
            kind="censusFunctionItemCode",
            authority_uri=cgfc.CENSUS_IDENTIFIER_AUTHORITY_URI,
            source_uri=cgfc.CENSUS_FUNCTION_ITEM_CODES_SOURCE.source_url,
            observed_at="2026-08-03T19:15:00Z",
            effective_at=None,
            source_digest=cgfc.CENSUS_FUNCTION_ITEM_CODES_2026_08_03.expected_sha256,
        ),
    )
    assert all(code.use == "deterministicMetadata" for code in resource.codes)
    assert all(not code.is_general_subject_concept for code in resource.codes)
    assert all(code.section is None for code in resource.codes)


def test_data_flag_codes_retain_publisher_sections(tmp_path: Path) -> None:
    resource = cgfc.parse_census_data_flag_codes(
        _acquire(tmp_path, cgfc.CENSUS_DATA_FLAG_CODES_2026_08_03, FLAGS_FIXTURE)
    )

    assert len(resource.codes) == 16
    by_code = resource.by_code()
    assert by_code["C"].section == "Reported Data"
    assert by_code["A"].section == "Imputed Data"
    assert by_code["Z"].publisher_label == (
        "Data are the summation of multiple individual state agencies (i.e., state "
        "level data) or the summation of multiple data function codes (i.e., total "
        'data function code of "000").'
    )
    reported = [code.identifiers[0].value for code in resource.codes if code.section == "Reported Data"]
    imputed = [code.identifiers[0].value for code in resource.codes if code.section == "Imputed Data"]
    assert reported == ["C", "K", "R", "T", "U", "V", "Z"]
    assert imputed == ["A", "B", "D", "G", "J", "P", "Q", "S", "X"]
    assert all(code.use == "deterministicMetadata" for code in resource.codes)
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_portfolio_records_the_mapping_only_role_and_pdf_gap(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert portfolio.census_function_item_codes.source.resource_name == "censusFunctionItemCodes"
    assert portfolio.census_data_flag_codes.source.resource_name == "censusDataFlagCodes"
    assert any("do not replace any state's enacted chart of accounts" in gap for gap in portfolio.gaps)
    assert any("2006 Government Finance and Employment Classification Manual PDF" in gap for gap in portfolio.gaps)


def test_portfolio_requires_exactly_the_two_census_resources(tmp_path: Path) -> None:
    functions = cgfc.parse_census_function_item_codes(
        _acquire(tmp_path, cgfc.CENSUS_FUNCTION_ITEM_CODES_2026_08_03, FUNCTION_FIXTURE)
    )

    with pytest.raises(cgfc.CensusFinanceSourceDriftError, match="requires exactly"):
        cgfc.assemble_census_finance_portfolio((functions,))


def test_state_budget_mapping_validates_without_replacing_native_identity(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    validated = cgfc.validate_census_finance_mapping(
        {
            "state_budget_line_item": "TX-HHSC-2025-Medicaid-Acute",
            "census_function_item_code": "032",
        },
        portfolio,
    )

    assert validated.state_native_reference == "TX-HHSC-2025-Medicaid-Acute"
    assert validated.census_function_item is not None
    assert validated.census_function_item.publisher_label == "Health"
    assert validated.census_function_item.identifiers[0].value == "032"
    assert not validated.census_function_item.is_general_subject_concept


def test_mapping_with_only_a_native_reference_omits_optional_assignments(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    validated = cgfc.validate_census_finance_mapping(
        {"state_budget_line_item": "CA-DOF-2025-line-88"},
        portfolio,
    )

    assert validated.state_native_reference == "CA-DOF-2025-line-88"
    assert validated.census_function_item is None


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ({}, "state_budget_line_item"),
        ({"state_budget_line_item": "  "}, "state_budget_line_item"),
        (
            {"state_budget_line_item": "X", "census_function_item_code": "999"},
            "unknown Census function item code",
        ),
    ],
)
def test_unknown_or_missing_mapping_fails_closed(
    tmp_path: Path,
    mapping: dict[str, object],
    message: str,
) -> None:
    portfolio = _portfolio(tmp_path)

    with pytest.raises(cgfc.CensusFinanceMappingError, match=message):
        cgfc.validate_census_finance_mapping(mapping, portfolio)


def test_digest_drift_never_produces_a_parsed_resource(tmp_path: Path) -> None:
    payload = FUNCTION_FIXTURE.read_bytes()
    changed = payload.replace(b"Judicial &amp; Legal", b"Judicial &amp; Legit")
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> cgfc.FetchedCensusFinancePage:
            del timeout_seconds
            return cgfc.FetchedCensusFinancePage(
                body=changed,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(cgfc.CensusFinanceSourceDriftError, match="digest drift"):
        cgfc.acquire_census_finance_page(
            cgfc.CENSUS_FUNCTION_ITEM_CODES_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def _write_and_acquire(
    tmp_path: Path,
    source: cgfc.CensusFinanceSource,
    payload: bytes,
) -> cgfc.AcquiredCensusFinancePage:
    source_path = tmp_path / "crafted.html"
    source_path.write_bytes(payload)
    pin = cgfc.CensusFinanceSnapshotPin(
        source=source,
        retrieved_at="2026-08-03T19:15:00Z",
        expected_sha256=cgfc.sha256_digest(payload),
        expected_byte_length=len(payload),
    )
    return cgfc.acquire_census_finance_page(pin, tmp_path / "store", source_path=source_path)


def test_wrong_heading_is_rejected_as_shape_drift(tmp_path: Path) -> None:
    payload = (
        b"<!doctype html><html><body>"
        b'<h1 class="cmp-title__text">Some Other Page</h1>'
        b"<table><tbody><tr><td>000 = Total</td></tr></tbody></table>"
        b"</body></html>"
    )
    acquired = _write_and_acquire(tmp_path, cgfc.CENSUS_FUNCTION_ITEM_CODES_SOURCE, payload)

    with pytest.raises(cgfc.CensusFinanceSourceDriftError, match="heading"):
        cgfc.parse_census_function_item_codes(acquired)


def test_missing_table_is_rejected_as_shape_drift(tmp_path: Path) -> None:
    payload = (
        b"<!doctype html><html><body>"
        b'<h1 class="cmp-title__text">Item Code (Functional Category)</h1>'
        b"<p>no table here</p>"
        b"</body></html>"
    )
    acquired = _write_and_acquire(tmp_path, cgfc.CENSUS_FUNCTION_ITEM_CODES_SOURCE, payload)

    with pytest.raises(cgfc.CensusFinanceSourceDriftError, match="exactly one function item code table"):
        cgfc.parse_census_function_item_codes(acquired)


def test_data_flag_row_before_any_section_header_fails_closed(tmp_path: Path) -> None:
    payload = (
        b"<!doctype html><html><body>"
        b'<h1 class="cmp-title__text">Data Flags</h1>'
        b"<table><tbody>"
        b"<tr><td>C</td><td>orphan row with no section</td></tr>"
        b'<tr><th colspan="2">Reported Data</th></tr>'
        b"</tbody></table>"
        b"</body></html>"
    )
    acquired = _write_and_acquire(tmp_path, cgfc.CENSUS_DATA_FLAG_CODES_SOURCE, payload)

    with pytest.raises(cgfc.CensusFinanceSourceDriftError, match="appears before any section header"):
        cgfc.parse_census_data_flag_codes(acquired)


def test_data_flag_duplicate_code_fails_closed(tmp_path: Path) -> None:
    payload = (
        b"<!doctype html><html><body>"
        b'<h1 class="cmp-title__text">Data Flags</h1>'
        b"<table><tbody>"
        b'<tr><th colspan="2">Reported Data</th></tr>'
        b"<tr><td>C</td><td>first definition</td></tr>"
        b"<tr><td>C</td><td>second definition</td></tr>"
        b"</tbody></table>"
        b"</body></html>"
    )
    acquired = _write_and_acquire(tmp_path, cgfc.CENSUS_DATA_FLAG_CODES_SOURCE, payload)

    with pytest.raises(cgfc.CensusFinanceSourceDriftError, match="data flag code 'C' is duplicated"):
        cgfc.parse_census_data_flag_codes(acquired)


def test_builds_two_distinct_controlled_code_list_packages(tmp_path: Path) -> None:
    function_page = _acquire(tmp_path, cgfc.CENSUS_FUNCTION_ITEM_CODES_2026_08_03, FUNCTION_FIXTURE)
    flags_page = _acquire(tmp_path, cgfc.CENSUS_DATA_FLAG_CODES_2026_08_03, FLAGS_FIXTURE)

    functions = cgfc.build_census_function_item_code_package(
        function_page, cgfc.parse_census_function_item_codes(function_page)
    )
    flags = cgfc.build_census_data_flag_code_package(flags_page, cgfc.parse_census_data_flag_codes(flags_page))

    for bundle, expected_count in ((functions, 33), (flags, 16)):
        assert bundle.resource_manifest["schemaVersion"] == "2.0"
        assert "candidateUseAuthorized" not in bundle.resource_manifest
        assert bundle.resource_manifest["resourceKind"] == "controlledCodeList"
        assert bundle.resource_manifest["identityStatus"] == "publisherIdentifiersPreserved"
        assert "usageCeiling" not in bundle.resource_manifest
        assert "acceptedOutputUseAuthorized" not in bundle.resource_manifest
        assert bundle.resource_manifest["conceptIdentityClaimed"] is False
        assert bundle.resource_manifest["uses"] == ("deterministicMetadata",)
        assert bundle.resource_manifest["observationCount"] == expected_count
        assert all(observation["conceptIdentityClaimed"] is False for observation in bundle.observations)
        assert {gap["kind"] for gap in bundle.coverage_report["gaps"]} >= {"mappingOnlyRole"}

    assert functions.resource_manifest["id"] != flags.resource_manifest["id"]


def test_generation_is_byte_deterministic(tmp_path: Path) -> None:
    page = _acquire(tmp_path, cgfc.CENSUS_FUNCTION_ITEM_CODES_2026_08_03, FUNCTION_FIXTURE)
    parsed = cgfc.parse_census_function_item_codes(page)

    first = cgfc.build_census_function_item_code_package(page, parsed)
    second = cgfc.build_census_function_item_code_package(page, parsed)

    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.logical_digest == second.logical_digest


def test_package_round_trips_through_a_written_closed_directory(tmp_path: Path) -> None:
    page = _acquire(tmp_path, cgfc.CENSUS_DATA_FLAG_CODES_2026_08_03, FLAGS_FIXTURE)
    parsed = cgfc.parse_census_data_flag_codes(page)
    bundle = cgfc.build_census_data_flag_code_package(page, parsed)

    written = bundle.write_to(tmp_path / "package")
    reopened = SourceControlledResourceView.open(written)

    assert reopened.logical_digest == bundle.logical_digest
    assert len(reopened.observations) == 16
    assert reopened.resource_manifest["resourceId"] == "census-aspep-data-flag-codes-2026-08-03"
