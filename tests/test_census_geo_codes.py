"""Census TIGER GEOID structure and GNIS National File layout capture tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import census_geo_codes as geo
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "census_geo_codes"
GEOID_FIXTURE = FIXTURES / "geoid-structure-2026-08-03.html"
GNIS_FIXTURE = FIXTURES / "gnis-file-format-2026-08-03.pdf"


def _geoid_structure_span(tmp_path: Path) -> geo.AcquiredCensusGeoHtmlSpan:
    return geo.acquire_census_geo_html_span(
        geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03, tmp_path, source_path=GEOID_FIXTURE
    )


def _gnis_pdf(tmp_path: Path) -> geo.AcquiredGNISFileFormat:
    return geo.acquire_gnis_file_format(geo.GNIS_FILE_FORMAT_PIN_2026_08_03, tmp_path, source_path=GNIS_FIXTURE)


def _package(tmp_path: Path) -> geo.SourceControlledResourceBundle:
    return geo.build_census_geo_identifier_authority_package(
        _geoid_structure_span(tmp_path),
        _gnis_pdf(tmp_path),
    )


# ---------------------------------------------------------------------------
# Acquisition: pinned real bytes, local capture, cache, injected fetcher.
# ---------------------------------------------------------------------------


def test_live_span_pin_matches_exact_official_html_bytes(tmp_path: Path) -> None:
    geoid_struct = _geoid_structure_span(tmp_path)

    assert geoid_struct.byte_length == geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03.expected_byte_length
    assert geoid_struct.sha256 == geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03.expected_sha256


def test_live_gnis_pdf_pin_matches_exact_official_bytes(tmp_path: Path) -> None:
    acquired = _gnis_pdf(tmp_path)

    assert acquired.byte_length == geo.GNIS_FILE_FORMAT_PIN_2026_08_03.expected_byte_length
    assert acquired.sha256 == geo.GNIS_FILE_FORMAT_PIN_2026_08_03.expected_sha256
    assert acquired.acquisition_mode == "local"


def test_local_span_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03

    acquired = geo.acquire_census_geo_html_span(pin, tmp_path, source_path=GEOID_FIXTURE)
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
    payload = GEOID_FIXTURE.read_bytes()
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
        geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=12.0,
    )

    assert calls == [(geo.CENSUS_GEOID_GUIDANCE_URL, 12.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.sha256 == geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03.expected_sha256


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
            geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03,
            tmp_path,
            source_path=GEOID_FIXTURE,
            fetcher=object(),  # type: ignore[arg-type]
        )


def test_acquisition_without_cache_local_or_fetcher_refuses(tmp_path: Path) -> None:
    with pytest.raises(geo.CensusGeoAcquisitionError, match="not cached"):
        geo.acquire_census_geo_html_span(geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03, tmp_path)


# ---------------------------------------------------------------------------
# Parsing: exact row shapes and identifier grammar.
# ---------------------------------------------------------------------------


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


def test_gnis_file_format_parses_the_complete_national_file_layout(tmp_path: Path) -> None:
    fields = geo.parse_gnis_file_format(_gnis_pdf(tmp_path))

    assert len(fields) == geo.GNIS_NATIONAL_FILE_FIELD_COUNT == 21
    assert tuple(
        (field.field_name, field.field_type, field.length_decimals) for field in fields
    ) == geo.GNIS_NATIONAL_FILE_EXPECTED_ROWS
    assert [field.source_ordinal for field in fields] == list(range(21))


def test_gnis_descriptions_are_publisher_wording_with_shared_cells_recorded(
    tmp_path: Path,
) -> None:
    fields = {field.field_name: field for field in geo.parse_gnis_file_format(_gnis_pdf(tmp_path))}

    # Fields with their own description cell carry it verbatim (PDF
    # presentation forms folded), and record no sharing.
    assert fields["feature_id"].description == (
        "Permanent, unique feature record identifier. See Appendix 3, number 1."
    )
    assert fields["feature_id"].description_shared_with == ()
    assert fields["feature_name"].description == "Official feature name."
    assert fields["date_created"].description == "Date the record was initially entered into GNIS."

    # The publisher merges one description cell across the state, county,
    # BGN, and coordinate row groups; each member carries the shared cell
    # verbatim, with the whole group named.
    assert fields["state_numeric"].description == (
        "The name of the state containing the primary coordinates. The state_name is "
        "the short form of the official state name. See Appendix 3, number 2."
    )
    assert fields["state_numeric"].description_shared_with == ("state_name", "state_numeric")
    assert fields["county_numeric"].description_shared_with == ("county_name", "county_numeric")
    assert fields["bgn_date"].description_shared_with == ("bgn_type", "bgn_authority", "bgn_date")
    assert fields["source_long_dec"].description_shared_with == (
        "prim_lat_dms",
        "prim_long_dms",
        "prim_lat_dec",
        "prim_long_dec",
        "source_lat_dms",
        "source_long_dms",
        "source_lat_dec",
        "source_long_dec",
    )
    assert fields["prim_lat_dms"].description.startswith("The official feature location.")

    # The RefSpec-authored description defect must not survive: no field
    # carries a sentence absent from the pinned PDF. These were the two
    # synthesized strings the audit flagged.
    for field in fields.values():
        assert "Two-digit code for the state" not in field.description
        assert "Three-digit code for the county" not in field.description


def test_gnis_table_shape_drift_fails_closed(tmp_path: Path) -> None:
    acquired = _gnis_pdf(tmp_path)
    original = geo.GNIS_NATIONAL_FILE_EXPECTED_ROWS
    try:
        geo.GNIS_NATIONAL_FILE_EXPECTED_ROWS = original[:-1]
        with pytest.raises(geo.CensusGeoSourceDriftError, match="shape drifted"):
            geo.parse_gnis_file_format(acquired)
    finally:
        geo.GNIS_NATIONAL_FILE_EXPECTED_ROWS = original


# ---------------------------------------------------------------------------
# Drift detection: digest, span-marker, and content mismatches fail closed.
# ---------------------------------------------------------------------------


def test_span_digest_drift_is_rejected(tmp_path: Path) -> None:
    from dataclasses import replace

    bad_pin = replace(geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03, expected_sha256="sha256:" + "0" * 64)

    with pytest.raises(geo.CensusGeoSourceDriftError, match="digest drift"):
        geo.acquire_census_geo_html_span(bad_pin, tmp_path, source_path=GEOID_FIXTURE)


def test_span_byte_length_drift_is_rejected(tmp_path: Path) -> None:
    from dataclasses import replace

    bad_pin = replace(geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03, expected_byte_length=1)

    with pytest.raises(geo.CensusGeoSourceDriftError, match="byte length drift"):
        geo.acquire_census_geo_html_span(bad_pin, tmp_path, source_path=GEOID_FIXTURE)


def test_begin_marker_repeated_in_source_fails_closed(tmp_path: Path) -> None:
    doubled = GEOID_FIXTURE.read_bytes()
    doubled = doubled + doubled[len(b"<!doctype html>\n") :]
    local = tmp_path / "doubled.html"
    local.write_bytes(doubled)

    with pytest.raises(geo.CensusGeoSourceDriftError, match="occurs 2 times"):
        geo.acquire_census_geo_html_span(
            geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03, tmp_path / "store", source_path=local
        )


def test_begin_marker_missing_from_source_fails_closed(tmp_path: Path) -> None:
    empty = tmp_path / "empty.html"
    empty.write_bytes(b"<!doctype html><html><body>nothing here</body></html>")

    with pytest.raises(geo.CensusGeoSourceDriftError, match="occurs 0 times"):
        geo.acquire_census_geo_html_span(geo.GEOID_STRUCTURE_TABLE_SPAN_2026_08_03, tmp_path, source_path=empty)


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


def test_package_covers_exactly_the_two_publisher_tables(tmp_path: Path) -> None:
    bundle = _package(tmp_path)

    kinds = {identifier["kind"] for obs in bundle.observations for identifier in obs["identifiers"]}
    assert kinds == {"tigerGeoidComposition", "gnisNationalFileFieldName"}
    # 11 GEOID structure rows + 21 GNIS National File fields. The three
    # example GEOIDs and the ACS variables sample left under REF-032.
    assert bundle.resource_manifest["observationCount"] == 32
    assert len(bundle.observations) == 32


def test_package_never_claims_concept_identity(tmp_path: Path) -> None:
    bundle = _package(tmp_path)

    assert bundle.resource_manifest["schemaVersion"] == "2.0"
    assert "candidateUseAuthorized" not in bundle.resource_manifest
    assert bundle.resource_manifest["conceptIdentityClaimed"] is False
    assert "acceptedOutputUseAuthorized" not in bundle.resource_manifest
    assert all(obs["conceptIdentityClaimed"] is False for obs in bundle.observations)


def test_package_preserves_every_publisher_identifier_value(tmp_path: Path) -> None:
    bundle = _package(tmp_path)

    values = {identifier["value"] for obs in bundle.observations for identifier in obs["identifiers"]}
    assert {"STATE", "STATE+COUNTY", "STATE+COUNTY+TRACT"} <= values
    assert {"feature_id", "state_numeric", "county_numeric", "map_name", "source_long_dec"} <= values
    # Example GEOID values are not vocabulary and never appear.
    assert not any(value.startswith("0500000US") for value in values)


def test_package_emits_no_example_values_and_no_acs_sample(tmp_path: Path) -> None:
    bundle = _package(tmp_path)

    kinds = {identifier["kind"] for obs in bundle.observations for identifier in obs["identifiers"]}
    assert "tigerGeoidExampleValue" not in kinds
    assert "acsVariableName" not in kinds
    assert "acsApiPredicateParameterName" not in kinds
    assert {gap["kind"] for gap in bundle.coverage_report["gaps"]} >= {"exampleValuesExcluded"}


def test_package_gnis_observations_carry_publisher_descriptions_and_medium(
    tmp_path: Path,
) -> None:
    bundle = _package(tmp_path)
    gnis_observations = [
        obs for obs in bundle.observations if obs["identifiers"][0]["kind"] == "gnisNationalFileFieldName"
    ]

    assert len(gnis_observations) == 21
    by_field = {obs["identifiers"][0]["value"]: obs for obs in gnis_observations}
    assert by_field["feature_id"]["labels"][0]["value"] == "feature_id"
    assert by_field["feature_id"]["description"] == (
        "Permanent, unique feature record identifier. See Appendix 3, number 1."
    )
    assert by_field["feature_id"]["fieldType"] == "Number"
    assert by_field["feature_id"]["lengthDecimals"] == "10"
    assert all(obs["sourceMedium"] == "pdf" for obs in gnis_observations)
    assert all(obs["description"] for obs in gnis_observations)
    assert by_field["state_numeric"]["descriptionSharedWithFields"] == ("state_name", "state_numeric")
    assert "descriptionSharedWithFields" not in by_field["feature_id"]


def test_package_records_geoid_composition_fields(tmp_path: Path) -> None:
    bundle = _package(tmp_path)

    geoid_observations = [
        obs for obs in bundle.observations if obs["identifiers"][0]["kind"] == "tigerGeoidComposition"
    ]
    assert len(geoid_observations) == 11
    assert all("numberOfDigits" in obs for obs in geoid_observations)
    assert all(obs["product"] == "tigerLineGeoid" for obs in geoid_observations)


def test_package_round_trips_through_a_written_and_reopened_directory(tmp_path: Path) -> None:
    bundle = _package(tmp_path)
    package_dir = tmp_path / "package"
    bundle.write_to(package_dir)

    reopened = SourceControlledResourceView.open(package_dir)

    assert reopened.logical_digest == bundle.logical_digest
    assert len(reopened.observations) == 32
    assert reopened.resource_manifest["resourceKind"] == "controlledCodeList"
    assert reopened.resource_manifest["identityStatus"] == "publisherIdentifiersPreserved"
    assert set(reopened.source_artifacts) == set(bundle.source_artifacts)


def test_package_is_byte_deterministic_across_rebuilds(tmp_path: Path) -> None:
    first = _package(tmp_path / "run1")
    second = _package(tmp_path / "run2")

    assert first.logical_digest == second.logical_digest
    assert first.artifact_bytes() == second.artifact_bytes()
