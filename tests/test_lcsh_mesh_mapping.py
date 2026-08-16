"""Exact-byte and semantic tests for Northwestern's MeSH--LCSH mapping."""

from __future__ import annotations

import io
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import pytest
from rdflib.namespace import SKOS

from refspec.registry import lcsh_mesh_mapping as mapping

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "lcsh_mesh_mapping" / "mesh-lcsh-mini.xml"
REAL_SOURCE = ROOT / "output" / "registry-real-data-sources" / mapping.LCSH_MESH_MAPPING_FILENAME


def test_fixture_translates_only_honest_marc_750_relationships() -> None:
    capture = mapping.parse_lcsh_mesh_marcxml(FIXTURE.read_bytes())

    assert capture.record_count == 8
    assert capture.linking_record_count == 8
    assert capture.linking_field_count == 10
    assert capture.accepted_source_field_count == 4
    assert len(capture.mappings) == 4
    assert capture.predicate_counts == {
        str(SKOS.broadMatch): 1,
        str(SKOS.exactMatch): 1,
        str(SKOS.narrowMatch): 1,
        str(SKOS.relatedMatch): 1,
    }
    assert capture.refusal_counts == {
        "complex-linking-field": 1,
        "no-single-lcsh-control-number": 1,
        "subject-not-mesh-descriptor": 1,
        "subdivision-linking-field": 1,
        "target-vocabulary-not-lcsh": 1,
        "unsupported-marc-relationship": 1,
    }
    assert capture.accepted_source_field_count + len(capture.refusals) == capture.linking_field_count


def test_fixture_retains_native_field_order_and_explicit_translation_basis() -> None:
    capture = mapping.parse_lcsh_mesh_marcxml(FIXTURE.read_bytes())
    exact = next(row for row in capture.mappings if row.predicate_iri == str(SKOS.exactMatch))
    broad = next(row for row in capture.mappings if row.predicate_iri == str(SKOS.broadMatch))

    assert exact.source_predicate_iri == mapping.MARC_750_FIELD_IRI
    assert exact.translation_basis == "MARC 750 corresponding heading"
    assert broad.translation_basis == "MARC 750 $4 BM"
    assert exact.source_fields[0].native_payload()["subfields"] == [
        {"code": "a", "value": "Calcimycin"},
        {"code": "0", "value": "(DLC)sh 85018645"},
    ]
    triples = {(row.subject_iri, row.predicate_iri, row.object_iri) for row in capture.mappings}
    assert all((obj, predicate, subject) not in triples for subject, predicate, obj in triples)


def test_zip_reader_refuses_an_unexpected_member() -> None:
    payload = io.BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("not-the-published-member.xml", FIXTURE.read_bytes())

    with pytest.raises(mapping.LcshMeshMappingError, match="membership drifted"):
        mapping.parse_lcsh_mesh_mapping_zip(payload.getvalue())


@pytest.mark.skipif(not REAL_SOURCE.is_file(), reason="pinned mapping source is not cached")
def test_pinned_release_accounts_for_every_linking_field() -> None:
    capture = mapping.load_lcsh_mesh_mapping(REAL_SOURCE)

    assert capture.record_count == mapping.EXPECTED_RECORD_COUNT == 13_329
    assert mapping.PUBLISHER_DECLARED_RECORD_COUNT == 13_453
    assert capture.linking_record_count == mapping.EXPECTED_LINKING_RECORD_COUNT == 13_286
    assert capture.linking_field_count == mapping.EXPECTED_LINKING_FIELD_COUNT == 14_195
    assert capture.accepted_source_field_count == mapping.EXPECTED_ACCEPTED_SOURCE_FIELD_COUNT == 13_278
    assert len(capture.mappings) == mapping.EXPECTED_UNIQUE_MAPPING_COUNT == 13_270
    assert sum(len(row.source_fields) for row in capture.mappings) == capture.accepted_source_field_count
    assert capture.predicate_counts == dict(mapping.EXPECTED_PREDICATE_COUNTS)
    assert capture.refusal_counts == dict(mapping.EXPECTED_REFUSAL_COUNTS)
    assert len(capture.refusals) == mapping.EXPECTED_REFUSAL_COUNT == 917
    assert capture.accepted_source_field_count + len(capture.refusals) == capture.linking_field_count
    assert {row.source_predicate_iri for row in capture.mappings} == {mapping.MARC_750_FIELD_IRI}
    assert capture.source_url == mapping.LCSH_MESH_MAPPING_SOURCE_URL
    assert capture.retrieved_at == mapping.LCSH_MESH_MAPPING_RETRIEVED_AT
    assert capture.source_sha256 == mapping.LCSH_MESH_MAPPING_SHA256
    assert capture.source_byte_length == mapping.LCSH_MESH_MAPPING_BYTE_LENGTH
    assert capture.member_sha256 == mapping.LCSH_MESH_MAPPING_MEMBER_SHA256
    assert capture.member_byte_length == mapping.LCSH_MESH_MAPPING_MEMBER_BYTE_LENGTH
    assert mapping.LCSH_MESH_LICENSE_STATEMENT == "Creative Commons Public Domain Mark 1.0"
    assert mapping.LCSH_MESH_LICENSE_URL == "http://creativecommons.org/publicdomain/mark/1.0"
    assert "rights are unverified" in mapping.LCSH_MESH_WORKING_FILE_RIGHTS_NOTE


@pytest.mark.skipif(not REAL_SOURCE.is_file(), reason="pinned mapping source is not cached")
def test_pinned_loader_refuses_distribution_drift(tmp_path: Path) -> None:
    drifted = tmp_path / mapping.LCSH_MESH_MAPPING_FILENAME
    drifted.write_bytes(REAL_SOURCE.read_bytes()[:-1])

    with pytest.raises(mapping.LcshMeshMappingError, match="byte length drift"):
        mapping.load_lcsh_mesh_mapping(drifted)


@pytest.mark.skipif(not REAL_SOURCE.is_file(), reason="pinned mapping source is not cached")
def test_pinned_predicate_mix_does_not_promote_refused_fields() -> None:
    capture = mapping.load_lcsh_mesh_mapping(REAL_SOURCE)
    field_tags = Counter(item.source_field.tag for item in capture.refusals)

    assert field_tags["780"] == mapping.EXPECTED_REFUSAL_COUNTS["subdivision-linking-field"]
    assert field_tags["788"] == mapping.EXPECTED_REFUSAL_COUNTS["complex-linking-field"]
    assert all(row.predicate_iri in mapping.EXPECTED_PREDICATE_COUNTS for row in capture.mappings)
