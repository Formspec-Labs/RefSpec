"""Census ACS variable, TIGER GEOID, and GNIS feature identifier structure tests."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from refspec.registry import census_geo_codes as geo
from refspec.registry.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "census_geo_codes"
ACS_FIXTURE = FIXTURES / "acs-variables-2026-08-03.html"
GEOID_FIXTURE = FIXTURES / "geoid-structure-2026-08-03.html"
GNIS_FIXTURE = FIXTURES / "gnis-file-format-2026-08-03.pdf"


def _acs_geography_span(tmp_path: Path) -> geo.AcquiredCensusGeoHtmlSpan:
    return geo.acquire_census_geo_html_span(
        geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03, tmp_path, source_path=ACS_FIXTURE
    )


def _acs_estimate_span(tmp_path: Path) -> geo.AcquiredCensusGeoHtmlSpan:
    return geo.acquire_census_geo_html_span(
        geo.ACS_S0201_ESTIMATE_VARIABLES_SPAN_2026_08_03, tmp_path, source_path=ACS_FIXTURE
    )


def _geoid_structure_span(tmp_path: Path) -> geo.AcquiredCensusGeoHtmlSpan:
    return geo.acquire_census_geo_html_span(
        geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03, tmp_path, source_path=GEOID_FIXTURE
    )


def _geoid_example_span(tmp_path: Path) -> geo.AcquiredCensusGeoHtmlSpan:
    return geo.acquire_census_geo_html_span(
        geo.GEOID_DOWNLOAD_EXAMPLE_TABLE_SPAN_2026_08_03, tmp_path, source_path=GEOID_FIXTURE
    )


def _gnis_pdf(tmp_path: Path) -> geo.AcquiredGNISFileFormat:
    return geo.acquire_gnis_file_format(geo.GNIS_FILE_FORMAT_PIN_2026_08_03, tmp_path, source_path=GNIS_FIXTURE)


def _package(tmp_path: Path) -> geo.SourceControlledResourceBundle:
    return geo.build_census_geo_identifier_authority_package(
        _acs_geography_span(tmp_path),
        _acs_estimate_span(tmp_path),
        _geoid_structure_span(tmp_path),
        _geoid_example_span(tmp_path),
        _gnis_pdf(tmp_path),
    )


# ---------------------------------------------------------------------------
# Acquisition: pinned real bytes, local capture, cache, injected fetcher.
# ---------------------------------------------------------------------------


def test_live_span_pins_match_exact_official_html_bytes(tmp_path: Path) -> None:
    acs_geo = _acs_geography_span(tmp_path)
    assert acs_geo.byte_length == geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03.expected_byte_length
    assert acs_geo.sha256 == geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03.expected_sha256

    acs_est = _acs_estimate_span(tmp_path)
    assert acs_est.sha256 == geo.ACS_S0201_ESTIMATE_VARIABLES_SPAN_2026_08_03.expected_sha256

    geoid_struct = _geoid_structure_span(tmp_path)
    assert geoid_struct.sha256 == geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03.expected_sha256

    geoid_example = _geoid_example_span(tmp_path)
    assert geoid_example.sha256 == geo.GEOID_DOWNLOAD_EXAMPLE_TABLE_SPAN_2026_08_03.expected_sha256


def test_live_gnis_pdf_pin_matches_exact_official_bytes(tmp_path: Path) -> None:
    acquired = _gnis_pdf(tmp_path)

    assert acquired.byte_length == geo.GNIS_FILE_FORMAT_PIN_2026_08_03.expected_byte_length
    assert acquired.sha256 == geo.GNIS_FILE_FORMAT_PIN_2026_08_03.expected_sha256
    assert acquired.acquisition_mode == "local"


def test_local_span_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03

    acquired = geo.acquire_census_geo_html_span(pin, tmp_path, source_path=ACS_FIXTURE)
    cached = geo.acquire_census_geo_html_span(pin, tmp_path)

    assert acquired.path == (
        tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / f"{pin.span.span_id}.html"
    )
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary_for_spans(tmp_path: Path) -> None:
    payload = ACS_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> geo.FetchedCensusGeoPage:
            calls.append((source_url, timeout_seconds))
            return geo.FetchedCensusGeoPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=utf-8",
                resolved_url=source_url,
            )

    acquired = geo.acquire_census_geo_html_span(
        geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=12.0,
    )

    assert calls == [(geo.CENSUS_ACS_VARIABLES_AUTHORITY_URI, 12.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.sha256 == geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03.expected_sha256


def test_injected_fetcher_is_the_only_live_transport_boundary_for_gnis_pdf(tmp_path: Path) -> None:
    payload = GNIS_FIXTURE.read_bytes()
    calls: list[str] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> geo.FetchedCensusGeoPage:
            del timeout_seconds
            calls.append(source_url)
            return geo.FetchedCensusGeoPage(
                body=payload,
                status_code=200,
                content_type="application/pdf",
                resolved_url=source_url,
            )

    acquired = geo.acquire_gnis_file_format(geo.GNIS_FILE_FORMAT_PIN_2026_08_03, tmp_path, fetcher=Fetcher())

    assert calls == [geo.GNIS_FILE_FORMAT_PDF_URL]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.sha256 == geo.GNIS_FILE_FORMAT_PIN_2026_08_03.expected_sha256


def test_acquisition_rejects_both_source_path_and_fetcher(tmp_path: Path) -> None:
    with pytest.raises(geo.CensusGeoAcquisitionError, match="not both"):
        geo.acquire_census_geo_html_span(
            geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03,
            tmp_path,
            source_path=ACS_FIXTURE,
            fetcher=object(),  # type: ignore[arg-type]
        )


def test_acquisition_without_cache_local_or_fetcher_refuses(tmp_path: Path) -> None:
    with pytest.raises(geo.CensusGeoAcquisitionError, match="not cached"):
        geo.acquire_census_geo_html_span(geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03, tmp_path)


# ---------------------------------------------------------------------------
# Parsing: exact row shapes and identifier grammar.
# ---------------------------------------------------------------------------


def test_acs_geography_and_predicate_rows_parse_with_known_shapes(tmp_path: Path) -> None:
    rows = geo.parse_acs_variable_span(
        _acs_geography_span(tmp_path), expected_names=geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_ROW_NAMES
    )
    by_name = {row.name: row for row in rows}

    assert by_name["for"].required == "predicate-only"
    assert by_name["for"].predicate_type == "fips-for"
    assert by_name["in"].required == "predicate-only"
    assert by_name["COUNTY"].predicate_type == "(not a predicate)"
    assert by_name["GEO_ID"].label == "Geography"
    assert "S0201PR" in by_name["GEO_ID"].group_raw
    assert "S0201" in by_name["GEO_ID"].group_raw
    assert by_name["GEOCOMP"].label == "GEO_ID Component"


def test_acs_s0201_estimate_rows_carry_the_measure_variable_grammar(tmp_path: Path) -> None:
    rows = geo.parse_acs_variable_span(
        _acs_estimate_span(tmp_path), expected_names=geo.ACS_S0201_ESTIMATE_VARIABLES_SPAN_ROW_NAMES
    )

    assert [row.name for row in rows] == ["S0201_001E", "S0201_002E"]
    assert all(geo._ACS_MEASURE_VARIABLE_RE.fullmatch(row.name) for row in rows)
    assert rows[0].predicate_type == "int"
    assert rows[1].predicate_type == "float"
    assert re.sub(r"<[^>]+>", "", rows[0].group_raw) == "S0201"


def test_acs_row_order_drift_fails_closed(tmp_path: Path) -> None:
    span = _acs_geography_span(tmp_path)
    with pytest.raises(geo.CensusGeoSourceDriftError, match="row order drifted"):
        geo.parse_acs_variable_span(span, expected_names=("NOT", "THE", "REAL", "ORDER"))


def test_geoid_structure_table_parses_all_eleven_area_types(tmp_path: Path) -> None:
    rows = geo.parse_geoid_structure_span(_geoid_structure_span(tmp_path))
    by_area = {row.area_type: row for row in rows}

    assert tuple(row.area_type for row in rows) == geo.GEOID_STRUCTURE_TABLE_AREA_TYPES
    assert by_area["State"].structure == "STATE"
    assert by_area["State"].number_of_digits == "2"
    assert by_area["State"].example_geoid == "48"
    assert by_area["County"].structure == "STATE+COUNTY"
    assert by_area["County"].example_geoid == "48201"
    assert by_area["Census Tract"].structure == "STATE+COUNTY+TRACT"
    assert by_area["Census Tract"].example_geoid == "48201223100"
    assert by_area["Block Group"].structure == "STATE+COUNTY+TRACT+BLOCK GROUP"
    # <sup> footnote markers are stripped from the area-type label.
    assert by_area["Block"].structure == "STATE+COUNTY+TRACT+BLOCK"
    assert by_area["ZCTA"].structure == "ZCTA"


def test_geoid_example_table_drops_its_column_label_row(tmp_path: Path) -> None:
    rows = geo.parse_geoid_example_span(_geoid_example_span(tmp_path))

    assert [row.geoid for row in rows] == ["0500000US10001", "0500000US10003", "0500000US10005"]
    assert rows[0].name == "Kent County, Delaware"
    assert all(row.geoid.startswith("0500000US") for row in rows)


def test_gnis_file_format_parses_pinned_national_file_fields(tmp_path: Path) -> None:
    fields = geo.parse_gnis_file_format(_gnis_pdf(tmp_path))
    by_name = {field.field_name: field for field in fields}

    assert set(by_name) == {"feature_id", "state_numeric", "county_numeric"}
    assert by_name["feature_id"].field_type == "Number"
    assert by_name["feature_id"].length == "10"
    assert "INCITS 446-2008" in by_name["feature_id"].standard_citation
    assert "INCITS 38-2009" in by_name["state_numeric"].standard_citation
    assert "INCITS 31-2009" in by_name["county_numeric"].standard_citation


# ---------------------------------------------------------------------------
# Drift detection: digest, span-marker, and content mismatches fail closed.
# ---------------------------------------------------------------------------


def test_span_digest_drift_is_rejected(tmp_path: Path) -> None:
    from dataclasses import replace

    bad_pin = replace(geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03, expected_sha256="sha256:" + "0" * 64)

    with pytest.raises(geo.CensusGeoSourceDriftError, match="digest drift"):
        geo.acquire_census_geo_html_span(bad_pin, tmp_path, source_path=ACS_FIXTURE)


def test_span_byte_length_drift_is_rejected(tmp_path: Path) -> None:
    from dataclasses import replace

    bad_pin = replace(geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03, expected_byte_length=1)

    with pytest.raises(geo.CensusGeoSourceDriftError, match="byte length drift"):
        geo.acquire_census_geo_html_span(bad_pin, tmp_path, source_path=ACS_FIXTURE)


def test_begin_marker_repeated_in_source_fails_closed(tmp_path: Path) -> None:
    doubled = ACS_FIXTURE.read_bytes()
    doubled = doubled + doubled[len(b"<!doctype html>\n") :]
    local = tmp_path / "doubled.html"
    local.write_bytes(doubled)

    with pytest.raises(geo.CensusGeoSourceDriftError, match="occurs 2 times"):
        geo.acquire_census_geo_html_span(
            geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03, tmp_path / "store", source_path=local
        )


def test_begin_marker_missing_from_source_fails_closed(tmp_path: Path) -> None:
    empty = tmp_path / "empty.html"
    empty.write_bytes(b"<!doctype html><html><body>nothing here</body></html>")

    with pytest.raises(geo.CensusGeoSourceDriftError, match="occurs 0 times"):
        geo.acquire_census_geo_html_span(geo.ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03, tmp_path, source_path=empty)


def test_gnis_pdf_page_count_drift_fails_closed(tmp_path: Path) -> None:
    from dataclasses import replace

    bad_pin = replace(geo.GNIS_FILE_FORMAT_PIN_2026_08_03, expected_page_count=999)
    acquired = geo.acquire_gnis_file_format(bad_pin, tmp_path, source_path=GNIS_FIXTURE)

    with pytest.raises(geo.CensusGeoSourceDriftError, match="page count drifted"):
        geo.parse_gnis_file_format(acquired)


def test_gnis_non_pdf_bytes_are_rejected(tmp_path: Path) -> None:
    from dataclasses import replace

    not_pdf = b"not a pdf" * 10_000
    bad_pin = replace(
        geo.GNIS_FILE_FORMAT_PIN_2026_08_03,
        expected_sha256=geo.sha256_digest(not_pdf),
        expected_byte_length=len(not_pdf),
    )
    local = tmp_path / "not-a-pdf.bin"
    local.write_bytes(not_pdf)

    with pytest.raises(geo.CensusGeoSourceDriftError, match="not a PDF"):
        geo.acquire_gnis_file_format(bad_pin, tmp_path, source_path=local)


def test_gnis_fetcher_rejects_non_official_resolved_url(tmp_path: Path) -> None:
    payload = GNIS_FIXTURE.read_bytes()

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> geo.FetchedCensusGeoPage:
            del source_url, timeout_seconds
            return geo.FetchedCensusGeoPage(
                body=payload,
                status_code=200,
                content_type="application/pdf",
                resolved_url="https://evil.example/GNIS_file_format.pdf",
            )

    with pytest.raises(geo.CensusGeoAcquisitionError, match="official HTTPS"):
        geo.acquire_gnis_file_format(geo.GNIS_FILE_FORMAT_PIN_2026_08_03, tmp_path, fetcher=Fetcher())


# ---------------------------------------------------------------------------
# Package assembly: closed, deterministic, publisher-identifier preserving.
# ---------------------------------------------------------------------------


def test_package_covers_every_declared_identifier_family(tmp_path: Path) -> None:
    bundle = _package(tmp_path)

    kinds = {identifier["kind"] for obs in bundle.observations for identifier in obs["identifiers"]}
    assert kinds == {
        "acsApiPredicateParameterName",
        "acsVariableName",
        "tigerGeoidComposition",
        "tigerGeoidExampleValue",
        "gnisNationalFileFieldName",
    }
    # 5 ACS geography/predicate rows (COUNTY, for, GEO_ID, GEOCOMP, in) + 2 S0201
    # estimate rows + 11 GEOID structure rows + 3 GEOID example rows + 3 GNIS fields.
    assert bundle.resource_manifest["observationCount"] == 24
    assert len(bundle.observations) == 24


def test_package_never_claims_concept_identity(tmp_path: Path) -> None:
    bundle = _package(tmp_path)

    assert bundle.resource_manifest["conceptIdentityClaimed"] is False
    assert bundle.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert all(obs["conceptIdentityClaimed"] is False for obs in bundle.observations)


def test_package_preserves_every_publisher_identifier_value(tmp_path: Path) -> None:
    bundle = _package(tmp_path)

    values = {identifier["value"] for obs in bundle.observations for identifier in obs["identifiers"]}
    assert {"for", "in", "GEO_ID", "GEOCOMP", "COUNTY", "S0201_001E", "S0201_002E"} <= values
    assert {"STATE", "STATE+COUNTY", "STATE+COUNTY+TRACT"} <= values
    assert "0500000US10001" in values
    assert {"feature_id", "state_numeric", "county_numeric"} <= values


def test_package_records_product_vintage_and_universe_fields(tmp_path: Path) -> None:
    bundle = _package(tmp_path)

    acs_observations = [
        obs
        for obs in bundle.observations
        if obs["identifiers"][0]["kind"] in {"acsVariableName", "acsApiPredicateParameterName"}
    ]
    assert all(obs["product"] == "acs1" for obs in acs_observations)
    assert all(obs["vintage"] == "2024" for obs in acs_observations)

    geoid_observations = [
        obs for obs in bundle.observations if obs["identifiers"][0]["kind"] == "tigerGeoidComposition"
    ]
    assert all("numberOfDigits" in obs for obs in geoid_observations)

    gnis_observations = [
        obs for obs in bundle.observations if obs["identifiers"][0]["kind"] == "gnisNationalFileFieldName"
    ]
    assert all("standardCitation" in obs for obs in gnis_observations)


def test_package_coverage_report_accounts_for_excluded_rows(tmp_path: Path) -> None:
    bundle = _package(tmp_path)
    coverage = bundle.coverage_report

    assert coverage["packagedCount"] == 24
    assert coverage["parsedCount"] == 24
    assert coverage["reportStatus"] == "gap"
    assert coverage["excludedCount"] > 0
    assert (
        coverage["sourceObservedCount"] == coverage["parsedCount"] + coverage["excludedCount"] + coverage["failedCount"]
    )
    assert len(coverage["gaps"]) >= 4


def test_package_round_trips_through_a_written_and_reopened_directory(tmp_path: Path) -> None:
    bundle = _package(tmp_path)
    package_dir = tmp_path / "package"
    bundle.write_to(package_dir)

    reopened = SourceControlledResourceView.open(package_dir)

    assert reopened.logical_digest == bundle.logical_digest
    assert len(reopened.observations) == 24
    assert reopened.resource_manifest["resourceKind"] == "controlledCodeList"
    assert reopened.resource_manifest["identityStatus"] == "publisherIdentifiersPreserved"
    assert set(reopened.source_artifacts) == set(bundle.source_artifacts)


def test_package_is_byte_deterministic_across_rebuilds(tmp_path: Path) -> None:
    first = _package(tmp_path / "run1")
    second = _package(tmp_path / "run2")

    assert first.logical_digest == second.logical_digest
    assert first.artifact_bytes() == second.artifact_bytes()
