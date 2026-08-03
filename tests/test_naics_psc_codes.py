"""NAICS industry code and PSC product/service code capture tests.

Both sources are deterministic facets and optional ranking signals (see the
catalog decision for ``NAICS`` and ``Product and Service Codes``): neither
states a document's policy topic, and no code here is ever promoted to a
general subject concept.

The fixtures under ``tests/fixtures/naics_psc_codes`` are a constructed
rendering faithful to each publisher's documented column layout, not a
verified live capture -- see the module docstring's "Acquisition honesty"
note for what was and was not confirmed live this session.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import naics_psc_codes as npc
from refspec.registry.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "naics_psc_codes"
NAICS_FIXTURE = FIXTURES / "naics-2022-us-structure-2026-08-03.csv"
PSC_FIXTURE = FIXTURES / "psc-manual-april-2025-2026-08-03.csv"


def _acquire(
    tmp_path: Path,
    pin: npc.NaicsPscSnapshotPin,
    source_path: Path,
) -> npc.AcquiredNaicsPscSource:
    return npc.acquire_naics_psc_source(pin, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> npc.NaicsPscPortfolio:
    naics = npc.parse_naics_codes(_acquire(tmp_path, npc.NAICS_CODES_2026_08_03, NAICS_FIXTURE))
    psc = npc.parse_psc_codes(_acquire(tmp_path, npc.PSC_CODES_2026_08_03, PSC_FIXTURE))
    return npc.assemble_naics_psc_portfolio((naics, psc))


def test_module_import_opens_no_network_connection() -> None:
    # Importing must never perform I/O; only an explicit fetcher call may.
    assert hasattr(npc, "acquire_naics_psc_source")
    assert hasattr(npc, "NaicsPscFetcher")


def test_fixture_pins_match_exact_captured_bytes() -> None:
    naics = NAICS_FIXTURE.read_bytes()
    psc = PSC_FIXTURE.read_bytes()

    assert len(naics) == 517
    assert npc.sha256_digest(naics) == ("sha256:a8e7fb37571ba8c2e7eb8281e2805f9f4a3ef77104fed3c3bd43e7be072c3539")
    assert len(psc) == 545
    assert npc.sha256_digest(psc) == ("sha256:dd6c5307bb761b842152ed91d20be99943b890c38c4c1f92ae15cb60b3dc9ba5")


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = npc.NAICS_CODES_2026_08_03

    acquired = _acquire(tmp_path, pin, NAICS_FIXTURE)
    cached = npc.acquire_naics_psc_source(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = PSC_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> npc.FetchedNaicsPscResponse:
            calls.append((source_url, timeout_seconds))
            return npc.FetchedNaicsPscResponse(
                body=payload,
                status_code=200,
                content_type="text/csv; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = npc.acquire_naics_psc_source(
        npc.PSC_CODES_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=9.0,
    )

    assert calls == [(npc.PSC_CODES_SOURCE.source_url, 9.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_naics_codes_are_deterministic_facets_not_general_subject_concepts(
    tmp_path: Path,
) -> None:
    resource = npc.parse_naics_codes(_acquire(tmp_path, npc.NAICS_CODES_2026_08_03, NAICS_FIXTURE))

    assert len(resource.codes) == 14
    assert resource.edition == "2022"
    by_code = resource.by_code()
    assert by_code["11"].publisher_label == "Agriculture, Forestry, Fishing and Hunting"
    assert by_code["11"].facet == "sector"
    assert by_code["111"].facet == "subsector"
    assert by_code["1111"].facet == "industryGroup"
    assert by_code["11111"].facet == "naicsIndustry"
    assert by_code["111110"].facet == "nationalIndustry"
    assert by_code["111110"].identifiers == (
        npc.ControlledIdentifier(
            value="111110",
            kind="naicsCode",
            authority_uri=npc.NAICS_IDENTIFIER_AUTHORITY_URI,
            source_uri=npc.NAICS_CODES_SOURCE.source_url,
            observed_at="2026-08-03T20:00:00Z",
            effective_at=None,
            source_digest=npc.NAICS_CODES_2026_08_03.expected_sha256,
        ),
    )
    assert all(code.use == "deterministicMetadata" for code in resource.codes)
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_naics_hyphenated_sector_range_is_preserved_verbatim(tmp_path: Path) -> None:
    resource = npc.parse_naics_codes(_acquire(tmp_path, npc.NAICS_CODES_2026_08_03, NAICS_FIXTURE))

    by_code = resource.by_code()
    assert by_code["31-33"].publisher_label == "Manufacturing"
    assert by_code["31-33"].facet == "sector"
    assert by_code["44-45"].publisher_label == "Retail Trade"
    assert by_code["48-49"].publisher_label == "Transportation and Warehousing"


def test_psc_codes_retain_publisher_category_facet(tmp_path: Path) -> None:
    resource = npc.parse_psc_codes(_acquire(tmp_path, npc.PSC_CODES_2026_08_03, PSC_FIXTURE))

    assert len(resource.codes) == 8
    assert resource.edition == "April 2025"
    by_code = resource.by_code()
    assert by_code["1005"].publisher_label == "Guns, through 30mm"
    assert by_code["1005"].facet == "Product"
    assert by_code["D302"].facet == "Service"
    assert by_code["AC12"].facet == "Research and Development"
    assert by_code["D302"].identifiers == (
        npc.ControlledIdentifier(
            value="D302",
            kind="pscCode",
            authority_uri=npc.PSC_IDENTIFIER_AUTHORITY_URI,
            source_uri=npc.PSC_CODES_SOURCE.source_url,
            observed_at="2026-08-03T20:00:00Z",
            effective_at=None,
            source_digest=npc.PSC_CODES_2026_08_03.expected_sha256,
        ),
    )
    assert all(code.use == "deterministicMetadata" for code in resource.codes)
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_portfolio_records_vintage_edition_and_capture_honesty_gaps(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    assert portfolio.naics_codes.source.resource_name == "naicsCodes"
    assert portfolio.psc_codes.source.resource_name == "pscCodes"
    assert npc.NAICS_2027_STRUCTURE_PUBLISHED is False
    assert any("do not state a document's policy topic" in gap for gap in portfolio.gaps)
    assert any("2027" in gap and "five-year cycle" in gap for gap in portfolio.gaps)
    assert any("Excel workbook" in gap and "April 2025" in gap for gap in portfolio.gaps)
    assert any("HTTP 403" in gap for gap in portfolio.gaps)


def test_naics_psc_classification_validates_without_becoming_subjects(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    validated = npc.validate_naics_psc_classification(
        {
            "record_reference": "AWARD-2026-000123",
            "naics_code": "311111",
            "psc_code": "R425",
        },
        portfolio,
    )

    assert validated.record_reference == "AWARD-2026-000123"
    assert validated.naics is not None
    assert validated.naics.publisher_label == "Dog and Cat Food Manufacturing"
    assert validated.naics.facet == "nationalIndustry"
    assert not validated.naics.is_general_subject_concept
    assert validated.psc is not None
    assert validated.psc.publisher_label == "Engineering and Technical Services"
    assert validated.psc.facet == "Service"
    assert not validated.psc.is_general_subject_concept


def test_mapping_with_only_a_native_reference_omits_optional_assignments(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    validated = npc.validate_naics_psc_classification(
        {"record_reference": "AWARD-2026-000999"},
        portfolio,
    )

    assert validated.record_reference == "AWARD-2026-000999"
    assert validated.naics is None
    assert validated.psc is None


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({}, "record_reference"),
        ({"record_reference": "  "}, "record_reference"),
        (
            {"record_reference": "X", "naics_code": "999999"},
            "unknown NAICS code",
        ),
        (
            {"record_reference": "X", "psc_code": "ZZZZ"},
            "unknown PSC code",
        ),
    ],
)
def test_unknown_or_missing_classification_fails_closed(
    tmp_path: Path,
    record: dict[str, object],
    message: str,
) -> None:
    portfolio = _portfolio(tmp_path)

    with pytest.raises(npc.NaicsPscAssignmentError, match=message):
        npc.validate_naics_psc_classification(record, portfolio)


def test_digest_drift_never_produces_a_parsed_resource(tmp_path: Path) -> None:
    payload = NAICS_FIXTURE.read_bytes()
    changed = payload.replace(b"Public Administration", b"Public AdministratIon")
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> npc.FetchedNaicsPscResponse:
            del timeout_seconds
            return npc.FetchedNaicsPscResponse(
                body=changed,
                status_code=200,
                content_type="text/csv",
                resolved_url=source_url,
            )

    with pytest.raises(npc.NaicsPscSourceDriftError, match="digest drift"):
        npc.acquire_naics_psc_source(
            npc.NAICS_CODES_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def _write_and_acquire(
    tmp_path: Path,
    source: npc.NaicsPscSource,
    payload: bytes,
) -> npc.AcquiredNaicsPscSource:
    source_path = tmp_path / "crafted.csv"
    source_path.write_bytes(payload)
    pin = npc.NaicsPscSnapshotPin(
        source=source,
        retrieved_at="2026-08-03T20:00:00Z",
        expected_sha256=npc.sha256_digest(payload),
        expected_byte_length=len(payload),
    )
    return npc.acquire_naics_psc_source(pin, tmp_path / "store", source_path=source_path)


def test_wrong_naics_header_is_rejected_as_shape_drift(tmp_path: Path) -> None:
    payload = b"Seq. No.,Wrong Column,2022 NAICS US Title\n1,11,Agriculture\n"
    acquired = _write_and_acquire(tmp_path, npc.NAICS_CODES_SOURCE, payload)

    with pytest.raises(npc.NaicsPscSourceDriftError, match="header drifted"):
        npc.parse_naics_codes(acquired)


def test_malformed_naics_code_is_rejected_as_shape_drift(tmp_path: Path) -> None:
    payload = b"Seq. No.,2022 NAICS US Code,2022 NAICS US Title\n1,1A,Agriculture\n"
    source = replace(npc.NAICS_CODES_SOURCE, expected_count=1)
    acquired = _write_and_acquire(tmp_path, source, payload)

    with pytest.raises(npc.NaicsPscSourceDriftError, match="malformed code"):
        npc.parse_naics_codes(acquired)


def test_naics_out_of_sequence_row_is_rejected_as_shape_drift(tmp_path: Path) -> None:
    payload = b"Seq. No.,2022 NAICS US Code,2022 NAICS US Title\n2,11,Agriculture\n"
    source = replace(npc.NAICS_CODES_SOURCE, expected_count=1)
    acquired = _write_and_acquire(tmp_path, source, payload)

    with pytest.raises(npc.NaicsPscSourceDriftError, match="out-of-sequence"):
        npc.parse_naics_codes(acquired)


def test_naics_duplicate_code_fails_closed(tmp_path: Path) -> None:
    # Two identical data rows under a crafted source whose expected_count
    # matches, so the duplicate check -- not the row-count check -- fires.
    payload = (
        b'Seq. No.,2022 NAICS US Code,2022 NAICS US Title\n'
        b'1,11,"Agriculture, Forestry, Fishing and Hunting"\n'
        b'2,11,"Agriculture, Forestry, Fishing and Hunting"\n'
    )
    source = replace(npc.NAICS_CODES_SOURCE, expected_count=2)
    acquired = _write_and_acquire(tmp_path, source, payload)

    with pytest.raises(npc.NaicsPscSourceDriftError, match="is duplicated"):
        npc.parse_naics_codes(acquired)


def test_psc_edition_mismatch_is_rejected_as_shape_drift(tmp_path: Path) -> None:
    payload = b"PSC Code,PSC Name,Category,Manual Edition\n1005,Guns,Product,April 2024\n"
    source = replace(npc.PSC_CODES_SOURCE, expected_count=1)
    acquired = _write_and_acquire(tmp_path, source, payload)

    with pytest.raises(npc.NaicsPscSourceDriftError, match="does not match pinned edition"):
        npc.parse_psc_codes(acquired)


def test_psc_unknown_category_is_rejected_as_shape_drift(tmp_path: Path) -> None:
    payload = b"PSC Code,PSC Name,Category,Manual Edition\n1005,Guns,Weapons,April 2025\n"
    source = replace(npc.PSC_CODES_SOURCE, expected_count=1)
    acquired = _write_and_acquire(tmp_path, source, payload)

    with pytest.raises(npc.NaicsPscSourceDriftError, match="unknown Category"):
        npc.parse_psc_codes(acquired)


def test_builds_two_distinct_controlled_code_list_packages(tmp_path: Path) -> None:
    naics_source = _acquire(tmp_path, npc.NAICS_CODES_2026_08_03, NAICS_FIXTURE)
    psc_source = _acquire(tmp_path, npc.PSC_CODES_2026_08_03, PSC_FIXTURE)

    naics_bundle = npc.build_naics_code_package(naics_source, npc.parse_naics_codes(naics_source))
    psc_bundle = npc.build_psc_code_package(psc_source, npc.parse_psc_codes(psc_source))

    for bundle, expected_count, gap_kind in (
        (naics_bundle, 14, "naicsVintageUnavailable"),
        (psc_bundle, 8, "pscManualBinaryFormat"),
    ):
        assert bundle.resource_manifest["resourceKind"] == "controlledCodeList"
        assert bundle.resource_manifest["identityStatus"] == "publisherIdentifiersPreserved"
        assert bundle.resource_manifest["usageCeiling"] == "developmentOnly"
        assert bundle.resource_manifest["candidateUseAuthorized"] is True
        assert bundle.resource_manifest["acceptedOutputUseAuthorized"] is False
        assert bundle.resource_manifest["conceptIdentityClaimed"] is False
        assert bundle.resource_manifest["uses"] == ["deterministicMetadata"]
        assert bundle.resource_manifest["observationCount"] == expected_count
        assert all(observation["conceptIdentityClaimed"] is False for observation in bundle.observations)
        gap_kinds = {gap["kind"] for gap in bundle.coverage_report["gaps"]}
        assert {"deterministicFacetRole", "unverifiedLiveCapture", gap_kind} <= gap_kinds

    assert naics_bundle.resource_manifest["id"] != psc_bundle.resource_manifest["id"]


def test_generation_is_byte_deterministic(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path, npc.NAICS_CODES_2026_08_03, NAICS_FIXTURE)
    parsed = npc.parse_naics_codes(acquired)

    first = npc.build_naics_code_package(acquired, parsed)
    second = npc.build_naics_code_package(acquired, parsed)

    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.logical_digest == second.logical_digest


def test_package_round_trips_through_a_written_closed_directory(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path, npc.PSC_CODES_2026_08_03, PSC_FIXTURE)
    parsed = npc.parse_psc_codes(acquired)
    bundle = npc.build_psc_code_package(acquired, parsed)

    written = bundle.write_to(tmp_path / "package")
    reopened = SourceControlledResourceView.open(written)

    assert reopened.logical_digest == bundle.logical_digest
    assert len(reopened.observations) == 8
    assert reopened.resource_manifest["resourceId"] == "psc-manual-april-2025-2026-08-03"
