"""Exact-byte and semantic tests for the GEMET 4.2.3 mapping reader."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib.namespace import SKOS

from refspec.registry import gemet_alignments as gemet

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "gemet_alignments" / "gemet-alignments-mini.rdf"
REAL_SOURCE = ROOT / "output" / "registry-real-data-sources" / gemet.GEMET_ALIGNMENT_FILENAME


def test_fixture_preserves_all_five_predicates_and_endpoint_status() -> None:
    rows = gemet.parse_gemet_alignment_rdf(FIXTURE.read_bytes())

    assert len(rows) == 5
    assert {row.predicate_iri for row in rows} == gemet.SKOS_MAPPING_PREDICATES
    assert {row.target_system for row in rows} == set(gemet.TARGET_PREFIXES)
    assert {row.target_system for row in rows if row.target_is_held} == {"eurovoc"}
    assert all(row.subject_iri == gemet.GEMET_CONCEPT_PREFIX + "100" for row in rows)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        (
            b"http://dbpedia.org/",
            b"https://unknown.example/",
            "no declared endpoint system",
        ),
        (
            b"http://creativecommons.org/licenses/by/4.0/",
            b"https://creativecommons.org/licenses/by/4.0/",
            "license assertion drifted",
        ),
    ),
)
def test_fixture_refuses_unknown_targets_and_license_drift(
    old: bytes,
    new: bytes,
    message: str,
) -> None:
    payload = FIXTURE.read_bytes().replace(old, new)

    with pytest.raises(gemet.GemetAlignmentError, match=message):
        gemet.parse_gemet_alignment_rdf(payload)


def test_fixture_refuses_a_repeated_publisher_triple() -> None:
    payload = FIXTURE.read_bytes().replace(
        b"    <skos:closeMatch",
        (b'    <skos:exactMatch rdf:resource="http://eurovoc.europa.eu/1"/>\n    <skos:closeMatch'),
    )

    with pytest.raises(gemet.GemetAlignmentError, match="repeats mapping triple"):
        gemet.parse_gemet_alignment_rdf(payload)


@pytest.mark.skipif(not REAL_SOURCE.is_file(), reason="pinned GEMET source is not cached")
def test_pinned_release_accounts_for_every_published_mapping_row() -> None:
    capture = gemet.load_gemet_alignments(REAL_SOURCE)

    assert len(capture.mappings) == gemet.EXPECTED_MAPPING_COUNT == 9_658
    assert capture.pair_predicate_counts == {
        pair: dict(sorted(counts.items())) for pair, counts in gemet.EXPECTED_PAIR_PREDICATE_COUNTS.items()
    }
    assert capture.pair_predicate_counts["eurovoc"] == {
        str(SKOS.broadMatch): 217,
        str(SKOS.exactMatch): 1_683,
        str(SKOS.narrowMatch): 38,
    }
    assert capture.source_url == gemet.GEMET_ALIGNMENT_SOURCE_URL
    assert capture.retrieved_at == gemet.GEMET_ALIGNMENT_RETRIEVED_AT
    assert capture.source_sha256 == gemet.GEMET_ALIGNMENT_SHA256
    assert capture.source_byte_length == gemet.GEMET_ALIGNMENT_BYTE_LENGTH
    assert capture.rdf_sha256 == gemet.GEMET_ALIGNMENT_RDF_SHA256
    assert capture.rdf_byte_length == gemet.GEMET_ALIGNMENT_RDF_BYTE_LENGTH
    assert capture.license_statement == "Attribution 4.0 International (CC BY 4.0)"
    assert capture.license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert "/4.2.3/" in capture.source_url
    assert "latest" not in capture.source_url
    assert "imported from exact SNS responses" in gemet.UMTHES_CONTENT_RIGHTS_NOTE
    assert "CC BY-NC 4.0" in gemet.UMTHES_CONTENT_RIGHTS_NOTE


@pytest.mark.skipif(not REAL_SOURCE.is_file(), reason="pinned GEMET source is not cached")
def test_pinned_loader_refuses_distribution_drift(tmp_path: Path) -> None:
    drifted = tmp_path / gemet.GEMET_ALIGNMENT_FILENAME
    drifted.write_bytes(REAL_SOURCE.read_bytes() + b"drift")

    with pytest.raises(gemet.GemetAlignmentError, match="byte length drift"):
        gemet.load_gemet_alignments(drifted)
