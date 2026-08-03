"""OCLC FAST topical facet CSV capture, streaming parse, and mapping-only packaging tests.

OCLC's official FAST download page names MARC, MARCXML, and RDF N-Triples bulk
files for the Topical facet; it names no CSV artifact, and the bulk-data host
(researchworks.oclc.org) returned a Cloudflare bot-block response to an
automated request during development. These tests therefore exercise a
constructed fixture, not a captured official byte stream, and never open a
live network connection.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import fast_topical as fast
from refspec.registry.source_controlled_resource import SourceControlledResourceView

FIXTURE = Path(__file__).parent / "fixtures" / "fast_topical" / "fast-topical-mini.csv"
LANDING_PAGE_FIXTURE = Path(__file__).parent / "fixtures" / "fast_topical" / "fast-download-landing-2026-08-04.html"


def test_landing_page_capture_matches_its_reference_pin() -> None:
    payload = LANDING_PAGE_FIXTURE.read_bytes()
    assert len(payload) == fast.FAST_LANDING_PAGE_CAPTURE_BYTE_LENGTH
    assert fast.sha256_digest(payload) == fast.FAST_LANDING_PAGE_CAPTURE_SHA256
FIXTURE_SHA256 = "sha256:4f1906f7475cc8818c8c702a12ad8fad6b4099d7207854d5324b40b92e940698"
FIXTURE_BYTE_LENGTH = 447
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
    assert parsed.rows[0].heading == "Environmental protection"
    assert parsed.rows[0].source_ordinal == 1
    assert parsed.rows[-1].heading == "Environmental policy--United States"
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
    assert package.resource_manifest["usageCeiling"] == "developmentOnly"
    assert package.resource_manifest["candidateUseAuthorized"] is True
    assert package.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert package.resource_manifest["conceptIdentityClaimed"] is False
    assert package.resource_manifest["uses"] == ["searchExpansion"]
    assert package.coverage_report["packagedCount"] == FIXTURE_ROW_COUNT
    assert package.coverage_report["reportStatus"] == "gap"

    for observation in package.observations:
        assert observation["eligibleUses"] == ["searchExpansion"]
        assert "sourceAssignedEvidence" not in observation["eligibleUses"]
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
    assert first["labels"] == [{"value": "Environmental protection", "language": "en", "role": "preferred"}]


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
