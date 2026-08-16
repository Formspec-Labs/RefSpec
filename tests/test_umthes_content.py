"""Exact-response tests for the UMTHES content capture."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import umthes_content as umthes

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "gemet_alignments" / "umthes-record-mini.nt"
SOURCE = ROOT / "output" / "registry-real-data-sources" / umthes.UMTHES_CAPTURE_FILENAME


def test_record_parser_keeps_real_multilingual_labels_and_definition() -> None:
    record = umthes.parse_umthes_record_nt(
        FIXTURE.read_bytes(),
        legacy_iri="http://data.uba.de/umt/_00028759",
        source_url="https://sns.uba.de/umthes/de/concepts/_00028759.nt",
        retrieved_at="2026-08-16T00:21:03Z",
    )

    assert record.concept_iri == "https://sns.uba.de/umthes/_00028759"
    assert {(label.value, label.language, label.role) for label in record.labels} == {
        ("Brücke", "de", "preferred"),
        ("bridge", "en", "preferred"),
        ("Viadukt", "de", "alternate"),
    }
    assert [(value.value, value.language) for value in record.definitions] == [
        ("A structure that spans an obstacle.", "en")
    ]
    assert [(relation.predicate_iri, relation.object_iri) for relation in record.relations] == [
        (
            "http://www.w3.org/2004/02/skos/core#broader",
            "https://sns.uba.de/umthes/_00029829",
        )
    ]
    assert record.deprecated is False
    assert record.source_sha256.startswith("sha256:")


def test_record_parser_refuses_namespace_substitution() -> None:
    changed = FIXTURE.read_bytes().replace(
        b"https://sns.uba.de/umthes/_00028759",
        b"https://example.test/umthes/_00028759",
    )

    with pytest.raises(umthes.UmthesContentError, match="does not describe the requested concept"):
        umthes.parse_umthes_record_nt(
            changed,
            legacy_iri="http://data.uba.de/umt/_00028759",
            source_url="https://sns.uba.de/umthes/de/concepts/_00028759.nt",
            retrieved_at="2026-08-16T00:21:03Z",
        )


@pytest.mark.skipif(not SOURCE.is_file(), reason="pinned UMTHES capture is not cached")
def test_real_capture_pins_every_distinct_gemet_target() -> None:
    capture = umthes.load_umthes_content_capture(SOURCE)

    assert len(capture.records) == umthes.UMTHES_EXPECTED_RECORD_COUNT
    assert len({record.legacy_iri for record in capture.records}) == umthes.UMTHES_EXPECTED_RECORD_COUNT
    assert capture.source_sha256 == umthes.UMTHES_CAPTURE_SHA256
    assert capture.source_byte_length == umthes.UMTHES_CAPTURE_BYTE_LENGTH
    assert capture.retrieved_at == umthes.UMTHES_RETRIEVED_AT
    assert all(record.labels for record in capture.records)
    assert capture.label_counts_by_language == {"de": 11_127, "en": 6_116}
    assert capture.definition_counts_by_language == {}
    assert len(capture.unavailable_records) == 13
    assert {record["httpStatus"] for record in capture.unavailable_records} == {404}
    assert {record["url"] for record in capture.unavailable_records} == {
        umthes.UMTHES_RECORD_URL_TEMPLATE.format(concept_id=concept_id)
        for concept_id in umthes.UMTHES_UNAVAILABLE_CONCEPT_IDS
    }


def test_capture_pin_and_license_wording_are_frozen() -> None:
    assert umthes.UMTHES_CAPTURE_BYTE_LENGTH == 11_935_413
    assert umthes.UMTHES_CAPTURE_SHA256 == (
        "sha256:978b10cd1e3f2f8729372a86f2afa1b62d2790e4810c6d57af5343835259d25f"
    )
    assert "CC BY-NC 4.0" in umthes.UMTHES_LICENSE_STATEMENT
    assert "Eine kommerzielle Nutzung ist nicht gestattet." in umthes.UMTHES_LICENSE_STATEMENT
