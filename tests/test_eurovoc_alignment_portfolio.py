"""Exact-source tests for the 17-file EuroVoc alignment portfolio."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest
from rdflib.namespace import SKOS

from refspec.registry import eurovoc_alignment_portfolio as eurovoc

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "output" / "registry-real-data-sources"
FIXTURE = ROOT / "tests" / "fixtures" / "eurovoc_alignment_portfolio" / "alignment-mini.rdf"
HAS_SOURCES = all((SOURCE_ROOT / pin.filename).is_file() for pin in eurovoc.EUROVOC_ALIGNMENT_PINS)

EXPECTED_ALIGNMENT_COUNTS = {
    "agrovoc": 1_814,
    "country": 246,
    "det": 1_499,
    "eclas": 3_999,
    "eige": 75,
    "esco": 2,
    "gemet": 2_036,
    "gesis": 2,
    "gnd": 215,
    "inspire": 14,
    "mesh": 11,
    "rameau": 316,
    "umt": 23,
    "unbis": 2_790,
    "unesco": 1_370,
    "wikidata": 5_650,
    "zbw": 2_648,
}


def _fixture_pin(payload: bytes) -> eurovoc.EuroVocAlignmentPin:
    return eurovoc.EuroVocAlignmentPin(
        key="fixture",
        title="Fixture",
        version="20260815-0",
        publisher_filename=FIXTURE.name,
        filename=FIXTURE.name,
        source_url="https://example.test/versioned/alignment-mini.rdf",
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_byte_length=len(payload),
        retrieved_at="2026-08-15T00:00:00Z",
        expected_predicate_counts=MappingProxyType(
            {
                str(SKOS.closeMatch): 1,
                str(SKOS.exactMatch): 1,
            }
        ),
        expected_non_eurovoc_mapping_count=1,
    )


def test_fixture_reader_keeps_publisher_direction_and_counts_anomalies() -> None:
    payload = FIXTURE.read_bytes()
    capture = eurovoc.parse_eurovoc_alignment_bytes(payload, pin=_fixture_pin(payload))

    assert len(capture.mappings) == 2
    assert capture.predicate_counts == {
        str(SKOS.closeMatch): 1,
        str(SKOS.exactMatch): 1,
    }
    assert capture.non_eurovoc_mapping_count == 1
    assert all(row.subject_iri.startswith(eurovoc.EUROVOC_CONCEPT_PREFIX) for row in capture.mappings)
    assert all(not row.object_iri.startswith(eurovoc.EUROVOC_CONCEPT_PREFIX) for row in capture.mappings)


def test_reader_refuses_an_unadmitted_publisher_predicate() -> None:
    payload = FIXTURE.read_bytes().replace(
        b"</rdf:RDF>",
        b"""
  <rdf:Description rdf:about="http://eurovoc.europa.eu/4">
    <skos:relatedMatch rdf:resource="http://example.test/vocabulary/four"/>
  </rdf:Description>
</rdf:RDF>""",
    )
    pin = replace(
        _fixture_pin(payload),
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_byte_length=len(payload),
    )

    with pytest.raises(eurovoc.EuroVocAlignmentPortfolioError, match="unsupported mapping predicates"):
        eurovoc.parse_eurovoc_alignment_bytes(payload, pin=pin)


def test_portfolio_pins_are_versioned_and_record_rights_ambiguity() -> None:
    assert len(eurovoc.EUROVOC_ALIGNMENT_PINS) == 17
    assert set(eurovoc.EUROVOC_ALIGNMENT_PINS_BY_KEY) == set(EXPECTED_ALIGNMENT_COUNTS)
    assert all("cellarURI=" in pin.source_url for pin in eurovoc.EUROVOC_ALIGNMENT_PINS)
    assert all(pin.version in pin.source_url for pin in eurovoc.EUROVOC_ALIGNMENT_PINS)
    assert all(pin.retrieved_at.endswith("Z") for pin in eurovoc.EUROVOC_ALIGNMENT_PINS)
    assert eurovoc.EUROVOC_ALIGNMENT_LICENSE_STATEMENT == "publisher states no license"
    assert eurovoc.EUROVOC_ALIGNMENT_GENERAL_REUSE_BASIS_URL.endswith("CELEX:32011D0833")
    assert "intellectual property rights of third parties" in (eurovoc.EUROVOC_ALIGNMENT_THIRD_PARTY_RIGHTS_EXCLUSION)


@pytest.fixture(scope="module")
def portfolio():
    if not HAS_SOURCES:
        pytest.skip("pinned EuroVoc alignment files are not cached")
    return eurovoc.load_eurovoc_alignment_portfolio(SOURCE_ROOT)


def test_official_portfolio_pins_every_alignment_count_and_predicate_mix(portfolio) -> None:
    observed = {alignment.pin.key: len(alignment.mappings) for alignment in portfolio.alignments}
    assert observed == EXPECTED_ALIGNMENT_COUNTS
    assert all(
        alignment.predicate_counts == dict(alignment.pin.expected_predicate_counts)
        for alignment in portfolio.alignments
    )
    assert portfolio.assertion_count == 22_710
    assert portfolio.predicate_counts == {
        str(SKOS.closeMatch): 1_446,
        str(SKOS.exactMatch): 21_264,
    }
    assert portfolio.non_eurovoc_mapping_count == 3


def test_complete_catalogue_count_and_exact_percentage_include_existing_lcsh(portfolio) -> None:
    assert portfolio.assertion_count + 2_003 == 24_713
    assert round((portfolio.predicate_counts[str(SKOS.exactMatch)] + 1_904) / 24_713 * 100, 2) == 93.75
    assert eurovoc.EXPECTED_COMPLETE_CATALOGUE_ASSERTION_COUNT == 24_713
    assert eurovoc.EXPECTED_COMPLETE_CATALOGUE_EXACT_PERCENT == 93.75


def test_file_reader_refuses_source_drift(tmp_path: Path) -> None:
    pin = eurovoc.EUROVOC_ALIGNMENT_PINS_BY_KEY["esco"]
    changed = tmp_path / pin.filename
    changed.write_bytes((SOURCE_ROOT / pin.filename).read_bytes() + b"drift" if HAS_SOURCES else b"drift")

    with pytest.raises(eurovoc.EuroVocAlignmentPortfolioError, match="input pin differs"):
        eurovoc.parse_eurovoc_alignment_file(changed, pin=pin)
