"""Exact-source tests for OCLC's bulk FAST external links."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import oclc_fast_external_links as fast

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "oclc_fast_external_links" / "fast-external-links-mini.nt"
SOURCE = ROOT / "output" / "registry-real-data-sources" / fast.FAST_EXTERNAL_LINKS_FILENAME
HAS_SOURCE = SOURCE.is_file()


def test_statement_reader_preserves_positive_predicates_and_refuses_nonmappings() -> None:
    lines = FIXTURE.read_bytes().splitlines(keepends=True)
    parsed = [
        fast.parse_oclc_fast_external_link_statement(line, line_number=index)
        for index, line in enumerate(lines, start=1)
    ]

    assert [row.predicate_iri for row in parsed if row is not None] == [
        fast.SCHEMA_SAME_AS,
        fast.SKOS_RELATED_MATCH,
        fast.SKOS_RELATED_MATCH,
        fast.RDFS_SEE_ALSO,
    ]
    assert [row.target_vocabulary for row in parsed if row is not None] == [
        "lcsh",
        "wikidata",
        "lcsh",
        "wikipedia",
    ]
    assert parsed[4:] == [None]
    assert all(row.native_statement == lines[row.line_number - 1].decode().rstrip() for row in parsed[:4])


def test_statement_reader_rejects_an_unclassified_positive_target() -> None:
    line = b"<http://id.worldcat.org/fast/1> <http://schema.org/sameAs> <http://example.test/not-a-known-target/1> .\n"
    with pytest.raises(fast.OclcFastExternalLinksError, match="unclassified"):
        fast.parse_oclc_fast_external_link_statement(line, line_number=1)


def test_publisher_pins_and_rights_statement_are_explicit() -> None:
    assert fast.FAST_EXTERNAL_LINKS_SOURCE_URL == (
        "https://researchworks.oclc.org/researchdata/fast/FASTTopical.nt.zip"
    )
    assert fast.FAST_EXTERNAL_LINKS_SHA256 == (
        "sha256:217826c90649895bfca71e81e2ed88919b2e061646ec42a185bc12d0bd3c19db"
    )
    assert fast.FAST_EXTERNAL_LINKS_BYTE_LENGTH == 55_099_212
    assert fast.FAST_EXTERNAL_LINKS_RETRIEVED_AT == "2026-07-27"
    assert fast.FAST_EXTERNAL_LINKS_HAS_VERSIONED_URL is False
    assert fast.FAST_EXTERNAL_LINKS_LICENSE_URL == ("https://www.oclc.org/research/areas/data-science/fast/odcby.html")
    assert fast.FAST_EXTERNAL_LINKS_LICENSE_TITLE == ("Open Data Commons Attribution License (ODC-By) v1.0")
    assert "made available by OCLC" in fast.FAST_EXTERNAL_LINKS_LICENSE_ARCHIVE_STATEMENT


@pytest.fixture(scope="module")
def capture():
    if not HAS_SOURCE:
        pytest.skip("pinned OCLC FAST external-links archive is not cached")
    return fast.parse_oclc_fast_external_links_file(
        SOURCE,
        retained_subject_iris={"http://id.worldcat.org/fast/1023619"},
    )


def test_official_capture_accounts_for_every_mapping_and_refusal(capture) -> None:
    assert capture.assertion_count == 935_540
    assert capture.predicate_counts == {
        fast.RDFS_SEE_ALSO: 155_171,
        fast.SCHEMA_SAME_AS: 311_890,
        fast.SKOS_RELATED_MATCH: 468_479,
    }
    assert capture.refused_predicate_counts == {
        fast.RDFS_SEE_ALSO: 2,
        fast.OWL_SAME_AS: 2,
    }
    assert capture.distinct_subject_count == 473_130
    assert [
        (row.subject_iri, row.predicate_iri, row.object_iri) for row in capture.retained_links
    ] == [
        (
            "http://id.worldcat.org/fast/1023619",
            fast.SKOS_RELATED_MATCH,
            "http://id.loc.gov/authorities/subjects/sh85085975",
        ),
        (
            "http://id.worldcat.org/fast/1023619",
            fast.SKOS_RELATED_MATCH,
            "http://id.loc.gov/authorities/subjects/sh2002006218",
        ),
    ]


def test_official_capture_pins_each_target_vocabulary_mix(capture) -> None:
    assert capture.target_predicate_counts == {
        target: dict(counts) for target, counts in fast.EXPECTED_TARGET_PREDICATE_COUNTS.items()
    }
    assert (
        sum(
            count
            for predicate_counts in capture.target_predicate_counts.values()
            for count in predicate_counts.values()
        )
        == 935_540
    )


def test_file_reader_refuses_source_drift(tmp_path: Path) -> None:
    changed = tmp_path / fast.FAST_EXTERNAL_LINKS_FILENAME
    changed.write_bytes(FIXTURE.read_bytes())

    with pytest.raises(fast.OclcFastExternalLinksError, match="input pin differs"):
        fast.parse_oclc_fast_external_links_file(changed)
