"""OCLC FAST native bulk/change validation plus legacy CSV compatibility tests.

OCLC's official FAST download page names MARC, MARCXML, and RDF N-Triples bulk
files for the Topical facet; it names no CSV artifact, and the bulk-data host
(researchworks.oclc.org) returned a Cloudflare bot-block response to an
automated request during development. The real-data tests use the exact
archived publisher ZIP and four live OCLC MARC change files; no test opens a
network connection.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import fast_topical as fast
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURE = Path(__file__).parent / "fixtures" / "fast_topical" / "fast-topical-mini.csv"
LANDING_PAGE_FIXTURE = Path(__file__).parent / "fixtures" / "fast_topical" / "fast-download-landing-2026-08-04.html"
TERM_RDF_FIXTURE = Path(__file__).parent / "fixtures" / "fast_topical" / "fast-term-1923093-2026-08-04.rdf.xml"
SUGGEST_FIXTURE = Path(__file__).parent / "fixtures" / "fast_topical" / "fast-suggest-water-quality-2026-08-04.json"


def test_landing_page_capture_matches_its_reference_pin() -> None:
    payload = LANDING_PAGE_FIXTURE.read_bytes()
    assert len(payload) == fast.FAST_LANDING_PAGE_CAPTURE_BYTE_LENGTH
    assert fast.sha256_digest(payload) == fast.FAST_LANDING_PAGE_CAPTURE_SHA256


def test_term_rdf_capture_matches_its_reference_pin() -> None:
    payload = TERM_RDF_FIXTURE.read_bytes()
    assert len(payload) == fast.FAST_TERM_RDF_CAPTURE_BYTE_LENGTH
    assert fast.sha256_digest(payload) == fast.FAST_TERM_RDF_CAPTURE_SHA256


def test_term_rdf_capture_parses_as_xml_with_rdf_root_and_contains_the_fast_uri() -> None:
    from urllib.parse import urljoin
    from xml.etree import ElementTree

    RDF_NS = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"

    root = ElementTree.fromstring(TERM_RDF_FIXTURE.read_bytes())

    assert root.tag == f"{RDF_NS}RDF"

    base = root.get("{http://www.w3.org/XML/1998/namespace}base")
    abouts = [element.get(f"{RDF_NS}about") for element in root.iter(f"{RDF_NS}Description")]
    resolved_uris = {urljoin(base, about) for about in abouts if about is not None}

    assert "http://id.worldcat.org/fast/1923093" in resolved_uris


def test_suggest_capture_matches_its_reference_pin() -> None:
    payload = SUGGEST_FIXTURE.read_bytes()
    assert len(payload) == fast.FAST_SUGGEST_CAPTURE_BYTE_LENGTH
    assert fast.sha256_digest(payload) == fast.FAST_SUGGEST_CAPTURE_SHA256


def test_suggest_capture_parses_and_has_its_real_top_level_shape() -> None:
    import json

    payload = json.loads(SUGGEST_FIXTURE.read_bytes())

    # This is the actual shape read from the fixture: a Solr-style envelope
    # with "responseHeader" and "response" keys, the latter carrying
    # "numFound"/"start"/"docs", where each doc is a single-key
    # {"suggestall": [...]} match.
    assert set(payload) == {"responseHeader", "response"}
    assert payload["responseHeader"]["params"]["rows"] == "5"
    assert payload["response"]["numFound"] == 476
    assert payload["response"]["start"] == 0
    docs = payload["response"]["docs"]
    assert len(docs) == 5
    assert all(set(doc) == {"suggestall"} for doc in docs)
    assert docs[0]["suggestall"] == ["Water quality"]


def test_suggest_api_observed_daily_rate_limit_is_recorded_as_observed_not_policy() -> None:
    assert fast.FAST_SUGGEST_API_OBSERVED_DAILY_RATE_LIMIT == 10_000


def test_gaps_document_the_native_bulk_change_and_per_term_channels() -> None:
    joined = " ".join(fast.FAST_TOPICAL_GAPS)
    assert "id.worldcat.org" in joined
    assert "10,000" in joined
    assert "multi-week" in joined
    assert "FAST Changes" in joined
    assert "441,127" in joined
    assert "2026-08-04" in joined


def _native_path(environment_name: str, fallback_name: str) -> Path:
    configured = os.environ.get(environment_name)
    path = (
        Path(configured)
        if configured
        else Path(__file__).parents[1] / "output" / "registry-real-data-sources" / fallback_name
    )
    if not path.is_file():
        pytest.skip(f"set {environment_name} to the exact pinned OCLC source")
    return path


@pytest.fixture(scope="module")
def native_snapshot() -> fast.ParsedFASTTopicalNativeSnapshot:
    return fast.parse_fast_topical_native_snapshot(
        _native_path("REFSPEC_FAST_TOPICAL_NT_ZIP_PATH", "FASTTopical.nt.zip"),
        (
            _native_path("REFSPEC_FAST_CHANGES_2024_10_27_PATH", "FASTChanges2024-10-27.mrc"),
            _native_path("REFSPEC_FAST_CHANGES_2024_12_04_PATH", "FASTChanges2024-12-04.mrc"),
            _native_path("REFSPEC_FAST_CHANGES_2025_05_01_PATH", "FASTChanges2025-05-01.mrc"),
            _native_path("REFSPEC_FAST_CHANGES_2026_02_13_PATH", "FASTChanges2026-02-13.mrc"),
        ),
    )


@pytest.mark.slow
def test_native_sources_rebuild_the_measured_current_topical_shape(
    native_snapshot: fast.ParsedFASTTopicalNativeSnapshot,
) -> None:
    assert native_snapshot.base_sha256 == fast.FAST_TOPICAL_NATIVE_BASE_PIN.expected_sha256
    assert native_snapshot.base_byte_length == fast.FAST_TOPICAL_NATIVE_BASE_PIN.expected_byte_length
    assert native_snapshot.base_active_count == 440_612
    assert len(native_snapshot.rows) == 441_127
    assert native_snapshot.facet_migration_count == 33

    assert [summary.all_facet_record_count for summary in native_snapshot.change_summaries] == [
        3_276,
        2_153,
        4_350,
        12_633,
    ]
    assert [summary.topical_status_counts for summary in native_snapshot.change_summaries] == [
        {"c": 363, "n": 3},
        {"c": 153, "n": 24},
        {"c": 200, "d": 3, "n": 282, "x": 5},
        {"c": 1_019, "n": 328, "x": 57},
    ]
    assert native_snapshot.topical_event_count == 2_437
    assert native_snapshot.unique_changed_id_count == 2_056
    assert native_snapshot.latest_change_status_counts == {"c": 1_527, "d": 3, "n": 464, "x": 62}


@pytest.mark.slow
def test_native_snapshot_pins_current_lcsh_link_shape(
    native_snapshot: fast.ParsedFASTTopicalNativeSnapshot,
) -> None:
    counts = Counter(
        link.predicate_iri
        for row in native_snapshot.rows
        for link in row.lcsh_links
    )

    assert sum(bool(row.lcsh_links) for row in native_snapshot.rows) == 427_423
    assert counts == {
        fast.FAST_SCHEMA_SAME_AS: 252_535,
        fast.FAST_SKOS_RELATED_MATCH: 349_932,
    }


@pytest.mark.slow
def test_native_snapshot_preserves_publisher_lcsh_statements_without_promotion(
    native_snapshot: fast.ParsedFASTTopicalNativeSnapshot,
) -> None:
    by_id = native_snapshot.by_numeric_id()
    base_exact = by_id["435760"].lcsh_links[0]
    changed_related = next(
        link
        for link in by_id["822259"].lcsh_links
        if link.target_iri.endswith("sh85009971")
    )

    assert base_exact.predicate_iri == fast.FAST_SCHEMA_SAME_AS
    assert base_exact.native_statement == (
        "<http://id.worldcat.org/fast/435760> <http://schema.org/sameAs> "
        "<http://id.loc.gov/authorities/subjects/sh2012001440> ."
    )
    assert base_exact.source_encoding == "ntriplesStatement"
    assert base_exact.source_record_digest == fast.sha256_digest(
        base_exact.native_statement.encode("utf-8")
    )

    assert "$wnnd" in changed_related.native_statement
    assert changed_related.predicate_iri == fast.FAST_SKOS_RELATED_MATCH
    assert changed_related.source_encoding == "marc21Record"
    assert changed_related.source_record_digest == (
        "sha256:3bcb5207d42e7bcbfaf9dd29827878f04b12f7dd51de520a4d9ed0f4cf232852"
    )


@pytest.mark.slow
def test_native_snapshot_preserves_real_ids_labels_synonyms_and_hierarchy(
    native_snapshot: fast.ParsedFASTTopicalNativeSnapshot,
) -> None:
    by_id = native_snapshot.by_numeric_id()

    assert by_id["801013"].heading == "Agricultural laborers--Wounds and injuries"
    environmental = by_id["913324"]
    assert environmental.legacy_fst_id == "fst00913324"
    assert environmental.uri == "http://id.worldcat.org/fast/913324"
    assert environmental.heading == "Environmental protection"
    assert environmental.alt_labels == ("Protection of environment", "Environmental quality management")
    assert environmental.broader_ids == ("913474",)
    assert native_snapshot.rows[0].numeric_id == "435760"
    assert native_snapshot.rows[0].heading == "Aparecida, Nossa Senhora"
    assert native_snapshot.rows[-1].numeric_id == "2073609"
    assert native_snapshot.rows[-1].heading == "New mothers--Mental health"


@pytest.mark.slow
def test_native_snapshot_preserves_replacement_and_obsolete_tombstones(
    native_snapshot: fast.ParsedFASTTopicalNativeSnapshot,
) -> None:
    assert len(native_snapshot.tombstones) == 65
    assert sum(row.status == "x" for row in native_snapshot.tombstones) == 62
    assert sum(row.status == "d" for row in native_snapshot.tombstones) == 3
    assert sum(len(row.replacement_ids) == 1 for row in native_snapshot.tombstones) == 59
    assert sum(len(row.replacement_ids) == 2 for row in native_snapshot.tombstones) == 3
    assert all(row.automatically_linked for row in native_snapshot.tombstones if row.status == "x")
    assert all(not row.replacement_ids for row in native_snapshot.tombstones if row.status == "d")


def test_native_parser_rejects_source_byte_drift(tmp_path: Path) -> None:
    changed = tmp_path / "FASTTopical.nt.zip"
    changed.write_bytes(b"not the OCLC archive")
    with pytest.raises(fast.FASTTopicalSourceDriftError, match="byte length drift"):
        fast.parse_fast_topical_native_snapshot(
            changed,
            tuple(Path("unused") for _ in fast.FAST_TOPICAL_CHANGE_PINS),
        )


FIXTURE_SHA256 = "sha256:799c9d51a2ec621790c30c93dba5327e156266460a5460c06531379737c89b64"
FIXTURE_BYTE_LENGTH = 464
FIXTURE_ROW_COUNT = 6


def _pin(**overrides: object) -> fast.FASTTopicalExtractPin:
    values: dict[str, object] = {
        "filename": "fast-topical-mini.csv",
        "retrieved_at": "2026-08-03T15:00:00Z",
        "expected_sha256": FIXTURE_SHA256,
        "expected_byte_length": FIXTURE_BYTE_LENGTH,
        "expected_row_count": FIXTURE_ROW_COUNT,
    }
    values.update(overrides)
    return fast.FASTTopicalExtractPin(**values)  # type: ignore[arg-type]


def _acquire(tmp_path: Path, pin: fast.FASTTopicalExtractPin | None = None) -> fast.AcquiredFASTTopicalExtract:
    return fast.acquire_fast_topical_extract(pin or _pin(), tmp_path, source_path=FIXTURE)


def _parsed(tmp_path: Path) -> fast.ParsedFASTTopicalExtract:
    return fast.parse_fast_topical_extract(_acquire(tmp_path))


def test_fixture_pin_matches_exact_local_bytes() -> None:
    payload = FIXTURE.read_bytes()

    assert len(payload) == FIXTURE_BYTE_LENGTH
    assert fast.sha256_digest(payload) == FIXTURE_SHA256


def test_official_download_page_offers_no_csv_format() -> None:
    # This module packages a locally supplied CSV rendering because OCLC's
    # documented bulk formats for the Topical facet are MARC, MARCXML, and
    # RDF N-Triples only.
    assert fast.FAST_TOPICAL_OFFICIAL_BULK_FORMATS == ("marc", "marcxml", "ntriples")
    assert "csv" not in fast.FAST_TOPICAL_OFFICIAL_BULK_FORMATS
    assert fast.FAST_TOPICAL_DOCUMENTED_ROW_COUNT == 440_599


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = _pin()

    acquired = _acquire(tmp_path, pin)
    cached = fast.acquire_fast_topical_extract(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_importing_this_module_never_opens_a_network_connection() -> None:
    # No fetcher protocol exists for this source: OCLC publishes no CSV
    # endpoint to fetch. Acquisition only accepts an already-local file.
    assert not hasattr(fast, "FASTTopicalFetcher")
    import inspect

    source = inspect.getsource(fast)
    for forbidden in ("urllib.request", "http.client", "requests", "socket.create_connection"):
        assert forbidden not in source


def test_streaming_parse_yields_every_row_in_source_order(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)

    assert len(parsed.rows) == FIXTURE_ROW_COUNT
    assert parsed.rows[0].fast_id == "fst00801013"
    assert parsed.rows[0].uri == "http://id.worldcat.org/fast/801013"
    assert parsed.rows[0].heading == "Agricultural laborers--Wounds and injuries"
    assert parsed.rows[0].source_ordinal == 1
    assert parsed.rows[-1].heading == "Politics and government"
    assert parsed.source_sha256 == FIXTURE_SHA256
    assert parsed.documented_total_row_count == 440_599


def test_iter_rows_is_a_true_generator_not_a_materialized_list(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    rows = fast.iter_fast_topical_rows(acquired.path)

    assert hasattr(rows, "__next__")
    first = next(rows)
    assert first.fast_id == "fst00801013"
    remaining = list(rows)
    assert len(remaining) == FIXTURE_ROW_COUNT - 1


def test_row_count_drift_against_the_pin_fails_closed(tmp_path: Path) -> None:
    pin = _pin(expected_row_count=FIXTURE_ROW_COUNT + 1)
    acquired = fast.acquire_fast_topical_extract(pin, tmp_path, source_path=FIXTURE)

    with pytest.raises(fast.FASTTopicalSourceDriftError, match="row count drift"):
        fast.parse_fast_topical_extract(acquired)


def test_digest_or_byte_length_drift_never_becomes_an_acquired_source(
    tmp_path: Path,
) -> None:
    pin = _pin(expected_sha256=fast.sha256_digest(b"not the real fixture"))

    with pytest.raises(fast.FASTTopicalSourceDriftError, match="digest drift"):
        fast.acquire_fast_topical_extract(pin, tmp_path, source_path=FIXTURE)


def test_header_drift_fails_closed(tmp_path: Path) -> None:
    payload = b"id,label\nfst00801013,Environmental protection\n"
    source_path = tmp_path / "bad-header.csv"
    source_path.write_bytes(payload)
    pin = _pin(
        filename="bad-header.csv",
        expected_sha256=fast.sha256_digest(payload),
        expected_byte_length=len(payload),
        expected_row_count=1,
    )

    with pytest.raises(fast.FASTTopicalSourceDriftError, match="header drifted"):
        fast.parse_fast_topical_extract(
            fast.acquire_fast_topical_extract(pin, tmp_path / "store", source_path=source_path)
        )


def test_malformed_fast_id_fails_closed(tmp_path: Path) -> None:
    payload = b"fast_id,uri,heading\nnot-an-id,http://id.worldcat.org/fast/1,Widgets\n"
    source_path = tmp_path / "bad-id.csv"
    source_path.write_bytes(payload)
    pin = _pin(
        filename="bad-id.csv",
        expected_sha256=fast.sha256_digest(payload),
        expected_byte_length=len(payload),
        expected_row_count=1,
    )

    with pytest.raises(fast.FASTTopicalSourceDriftError, match="malformed fast_id"):
        fast.parse_fast_topical_extract(
            fast.acquire_fast_topical_extract(pin, tmp_path / "store", source_path=source_path)
        )


def test_uri_not_derived_from_fast_id_fails_closed(tmp_path: Path) -> None:
    payload = b"fast_id,uri,heading\nfst00801013,http://id.worldcat.org/fast/999999,Widgets\n"
    source_path = tmp_path / "bad-uri.csv"
    source_path.write_bytes(payload)
    pin = _pin(
        filename="bad-uri.csv",
        expected_sha256=fast.sha256_digest(payload),
        expected_byte_length=len(payload),
        expected_row_count=1,
    )

    with pytest.raises(fast.FASTTopicalSourceDriftError, match="does not match fast_id"):
        fast.parse_fast_topical_extract(
            fast.acquire_fast_topical_extract(pin, tmp_path / "store", source_path=source_path)
        )


def test_duplicate_fast_id_fails_closed(tmp_path: Path) -> None:
    payload = (
        b"fast_id,uri,heading\n"
        b"fst00801013,http://id.worldcat.org/fast/801013,Environmental protection\n"
        b"fst00801013,http://id.worldcat.org/fast/801013,Environmental protection\n"
    )
    source_path = tmp_path / "dup.csv"
    source_path.write_bytes(payload)
    pin = _pin(
        filename="dup.csv",
        expected_sha256=fast.sha256_digest(payload),
        expected_byte_length=len(payload),
        expected_row_count=2,
    )

    with pytest.raises(fast.FASTTopicalSourceDriftError, match="duplicate fast_id"):
        fast.parse_fast_topical_extract(
            fast.acquire_fast_topical_extract(pin, tmp_path / "store", source_path=source_path)
        )


def test_ragged_row_field_count_fails_closed(tmp_path: Path) -> None:
    payload = b"fast_id,uri,heading\nfst00801013,http://id.worldcat.org/fast/801013\n"
    source_path = tmp_path / "ragged.csv"
    source_path.write_bytes(payload)
    pin = _pin(
        filename="ragged.csv",
        expected_sha256=fast.sha256_digest(payload),
        expected_byte_length=len(payload),
        expected_row_count=1,
    )

    with pytest.raises(fast.FASTTopicalSourceDriftError, match="fields, expected"):
        fast.parse_fast_topical_extract(
            fast.acquire_fast_topical_extract(pin, tmp_path / "store", source_path=source_path)
        )


def test_package_is_mapping_only_and_never_reserves_a_classifier_output_slot(
    tmp_path: Path,
) -> None:
    parsed = _parsed(tmp_path)

    package = fast.build_fast_topical_source_package(
        parsed,
        captured_at="2026-08-03T15:05:00Z",
        source_bytes=FIXTURE.read_bytes(),
    )

    assert package.resource_manifest["resourceId"] == fast.FAST_TOPICAL_RESOURCE_ID
    assert package.resource_manifest["resourceKind"] == "sourceTermSnapshot"
    assert package.resource_manifest["identityStatus"] == "publisherIdentifiersPreserved"
    assert "usageCeiling" not in package.resource_manifest
    assert package.resource_manifest["schemaVersion"] == "2.0"
    assert "candidateUseAuthorized" not in package.resource_manifest
    assert "acceptedOutputUseAuthorized" not in package.resource_manifest
    assert package.resource_manifest["conceptIdentityClaimed"] is False
    assert package.resource_manifest["uses"] == ("mappingReference", "searchExpansion")
    assert package.coverage_report["packagedCount"] == FIXTURE_ROW_COUNT
    assert package.coverage_report["reportStatus"] == "gap"

    for observation in package.observations:
        assert observation["uses"] == ("mappingReference", "searchExpansion")
        assert "sourceAssignedEvidence" not in observation["uses"]
        assert observation["conceptIdentityClaimed"] is False


def test_package_preserves_publisher_identifiers_exactly(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)
    package = fast.build_fast_topical_source_package(
        parsed,
        captured_at="2026-08-03T15:05:00Z",
        source_bytes=FIXTURE.read_bytes(),
    )

    first = package.observations[0]
    identifier_kinds = {identifier["kind"] for identifier in first["identifiers"]}
    identifier_values = {identifier["value"] for identifier in first["identifiers"]}
    assert identifier_kinds == {"fastId", "fastUri"}
    assert identifier_values == {"fst00801013", "http://id.worldcat.org/fast/801013"}
    assert first["labels"] == (
        {"value": "Agricultural laborers--Wounds and injuries", "language": "en", "role": "preferred"},
    )


def test_package_round_trips_exact_fast_source_bytes(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)
    package = fast.build_fast_topical_source_package(
        parsed,
        captured_at="2026-08-03T15:05:00Z",
        source_bytes=FIXTURE.read_bytes(),
    )
    opened = SourceControlledResourceView.open(package.write_to(tmp_path / "package"))

    assert opened.logical_digest == package.logical_digest
    assert len(opened.observations) == FIXTURE_ROW_COUNT
    (source_bytes,) = opened.source_artifacts.values()
    assert source_bytes == FIXTURE.read_bytes()


def test_package_gaps_document_the_absent_official_csv_format(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)
    package = fast.build_fast_topical_source_package(
        parsed,
        captured_at="2026-08-03T15:05:00Z",
        source_bytes=FIXTURE.read_bytes(),
    )

    gap_codes = {gap["code"] for gap in package.coverage_report["gaps"]}
    assert "fastNoOfficialCsvFormat" in gap_codes
    assert "fastLegacyCsvCompatibilityView" in gap_codes
    assert "fastDevelopmentSampleNotFullExtract" in gap_codes


def test_attribution_notice_is_recorded_for_the_odc_by_license() -> None:
    assert "ODC" in fast.FAST_ATTRIBUTION_NOTICE
    assert "OCLC Online Computer Library Center" in fast.FAST_ATTRIBUTION_NOTICE
    assert fast.FAST_LICENSE_URL.startswith("https://www.oclc.org/")


def test_acquisition_rejects_a_missing_local_source(tmp_path: Path) -> None:
    with pytest.raises(fast.FASTTopicalAcquisitionError):
        fast.acquire_fast_topical_extract(_pin(), tmp_path, source_path=tmp_path / "missing.csv")


def test_pin_rejects_nonpositive_counts() -> None:
    with pytest.raises(fast.FASTTopicalAcquisitionError):
        _pin(expected_row_count=0)
    with pytest.raises(fast.FASTTopicalAcquisitionError):
        _pin(expected_byte_length=0)


def test_pin_is_immutable_and_replace_still_validates() -> None:
    pin = _pin()
    with pytest.raises(fast.FASTTopicalAcquisitionError):
        replace(pin, expected_sha256="not-a-digest")
