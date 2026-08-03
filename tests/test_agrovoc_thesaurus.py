"""Lossless AGROVOC mapping-source reader tests.

AGROVOC is scoped by the source catalog as a mapping source for NALT-backed
subjects and multilingual expansion; it must not be promoted into a general
concept scheme, and its IRIs must never be combined with NALT identifiers.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from refspec.registry.agrovoc_thesaurus import (
    AGROVOC_C330_SAMPLE,
    AGROVOC_SCHEME_IRI,
    ALT_LABEL_PREDICATE_IRI,
    BROADER_PREDICATE_IRI,
    CREATED_PREDICATE_IRI,
    HIDDEN_LABEL_PREDICATE_IRI,
    MODIFIED_PREDICATE_IRI,
    NALT_IRI_PREFIXES,
    NARROWER_PREDICATE_IRI,
    NOTE_PREDICATE_IRIS,
    PREF_LABEL_PREDICATE_IRI,
    RELATED_PREDICATE_IRI,
    AgrovocAcquisitionError,
    AgrovocImportCounts,
    AgrovocParseError,
    AgrovocSampleSource,
    acquire_agrovoc_sample,
    parse_acquired_agrovoc_sample,
    parse_agrovoc_file,
    parse_agrovoc_turtle,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "agrovoc_thesaurus" / "agrovoc-mini.ttl"
REAL_SAMPLE_PATH = Path(__file__).parent / "fixtures" / "agrovoc_thesaurus" / "agrovoc-c330-sample.ttl"
FIXTURE_SOURCE_URL = "https://example.test/agrovoc-mini.ttl"

CURRENT = "http://aims.fao.org/aos/agrovoc/c_330"
BROADER = "http://aims.fao.org/aos/agrovoc/c_331078"
NARROWER = "http://aims.fao.org/aos/agrovoc/c_331"
NALT_TARGET = "https://lod.nal.usda.gov/nalt/71469"
LOC_TARGET = "http://id.loc.gov/authorities/subjects/sh85004113"
DBPEDIA_TARGET = "http://dbpedia.org/resource/Amaryllidaceae"

SYNTHETIC_FEATURE_EDGE_TURTLE = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
<urn:example:edge> a skos:Concept ;
    skos:prefLabel "Edge concept"@en ;
    skos:hiddenLabel "Internal term"@en ;
    skos:notation "AGR-001"^^<urn:example:notation-datatype> ;
    skos:definition "Definition."@en ;
    skos:example "Example."@en ;
    skos:note "Note."@en ;
    skos:scopeNote "Scope."@en ;
    skos:editorialNote "Editorial."@en ;
    skos:historyNote "History."@en ;
    skos:changeNote "Change."@en .
"""

SAME_AS_TURTLE = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://aims.fao.org/aos/agrovoc/c_1> a skos:Concept ;
    skos:prefLabel "Test"@en ;
    owl:sameAs <https://lod.nal.usda.gov/nalt/9999> .
"""

NALT_NAMESPACED_CONCEPT_TURTLE = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
<https://lod.nal.usda.gov/nalt/71469> a skos:Concept ;
    skos:prefLabel "Should not be minted as an AGROVOC concept"@en .
"""


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def _real_sample_bytes() -> bytes:
    return REAL_SAMPLE_PATH.read_bytes()


def test_parser_preserves_multilingual_labels_notes_metadata_and_iris() -> None:
    source = _fixture_bytes()
    parsed = parse_agrovoc_turtle(source, source_url=FIXTURE_SOURCE_URL)

    assert parsed.source_url == FIXTURE_SOURCE_URL
    assert parsed.source_bytes == len(source)
    assert parsed.source_sha256 == "sha256:" + hashlib.sha256(source).hexdigest()
    assert parsed.triple_count > 0
    assert parsed == parse_agrovoc_turtle(source, source_url=FIXTURE_SOURCE_URL)

    current_labels = [item for item in parsed.labels if item.subject_iri == CURRENT]
    preferred = {
        item.value.language_tag: item.value.lexical_form
        for item in current_labels
        if item.property_iri == PREF_LABEL_PREDICATE_IRI
    }
    assert preferred == {
        "en": "Amaryllidaceae",
        "fr": "Amaryllidacées",
        "es": "Amarilidáceas",
    }
    assert {
        (item.property_iri, item.value.language_tag, item.value.lexical_form)
        for item in current_labels
        if item.role != "preferred"
    } == {
        (ALT_LABEL_PREDICATE_IRI, "en", "Amaryllis family"),
        (ALT_LABEL_PREDICATE_IRI, "de", "Amaryllisgewächse"),
    }

    assert {item.property_iri for item in parsed.notes} == {
        "http://www.w3.org/2004/02/skos/core#definition",
        "http://www.w3.org/2004/02/skos/core#scopeNote",
        "http://www.w3.org/2004/02/skos/core#historyNote",
    }
    assert parsed.notations == ()

    current_metadata = {
        item.property_iri: item.value.lexical_form
        for item in parsed.metadata_literals
        if item.subject_iri == CURRENT
    }
    assert current_metadata == {
        CREATED_PREDICATE_IRI: "2011-11-20T19:46:55Z",
        MODIFIED_PREDICATE_IRI: "2026-06-02T07:11:39Z",
    }

    assert CURRENT in parsed.source_iris
    assert AGROVOC_SCHEME_IRI in parsed.source_iris


def test_parser_keeps_hierarchy_and_mapping_relations_as_distinct_iri_rows() -> None:
    parsed = parse_agrovoc_turtle(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    assert {
        (item.predicate_iri, item.object_iri) for item in parsed.semantic_relations if item.subject_iri == CURRENT
    } == {
        (BROADER_PREDICATE_IRI, BROADER),
        (NARROWER_PREDICATE_IRI, NARROWER),
    }
    assert {
        (item.predicate_iri, item.object_iri) for item in parsed.semantic_relations if item.subject_iri == NARROWER
    } == {
        (BROADER_PREDICATE_IRI, CURRENT),
        (RELATED_PREDICATE_IRI, BROADER),
    }

    mapping_targets = {
        (item.predicate_iri, item.object_iri) for item in parsed.mapping_relations if item.subject_iri == CURRENT
    }
    assert mapping_targets == {
        ("http://www.w3.org/2004/02/skos/core#closeMatch", DBPEDIA_TARGET),
        ("http://www.w3.org/2004/02/skos/core#exactMatch", NALT_TARGET),
        ("http://www.w3.org/2004/02/skos/core#exactMatch", LOC_TARGET),
    }

    concept = next(item for item in parsed.concepts if item.concept_iri == CURRENT)
    assert concept.scheme_iris == (AGROVOC_SCHEME_IRI,)
    assert parsed.concept_schemes[0].scheme_iri == AGROVOC_SCHEME_IRI


def test_nalt_crosswalk_relations_isolate_only_nalt_targets_without_merging_identity() -> None:
    parsed = parse_agrovoc_turtle(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    crosswalk = parsed.nalt_crosswalk_relations
    assert {item.object_iri for item in crosswalk} == {NALT_TARGET}
    for relation in crosswalk:
        assert any(relation.object_iri.startswith(prefix) for prefix in NALT_IRI_PREFIXES)
        # A crosswalk relation is a plain (subject, predicate, object) row: it
        # never becomes one merged identifier shared with the NALT concept.
        assert relation.subject_iri != relation.object_iri
        assert relation.subject_iri == CURRENT


def test_clearly_synthetic_edge_input_covers_hidden_labels_typed_notation_and_all_notes() -> None:
    parsed = parse_agrovoc_turtle(
        SYNTHETIC_FEATURE_EDGE_TURTLE,
        source_url="https://example.test/synthetic-feature-edge.ttl",
    )

    assert any(item.property_iri == HIDDEN_LABEL_PREDICATE_IRI for item in parsed.labels)
    assert len(parsed.notations) == 1
    notation = parsed.notations[0]
    assert notation.value.lexical_form == "AGR-001"
    assert notation.value.language_tag is None
    assert notation.value.datatype_iri == "urn:example:notation-datatype"
    assert {item.property_iri for item in parsed.notes} == set(NOTE_PREDICATE_IRIS)


def test_parser_rejects_identity_merging_owl_same_as_assertions() -> None:
    with pytest.raises(AgrovocParseError, match="owl:sameAs"):
        parse_agrovoc_turtle(SAME_AS_TURTLE, source_url="https://example.test/same-as.ttl")


def test_parser_rejects_a_concept_minted_inside_the_nalt_namespace() -> None:
    with pytest.raises(AgrovocParseError, match="NALT"):
        parse_agrovoc_turtle(
            NALT_NAMESPACED_CONCEPT_TURTLE,
            source_url="https://example.test/nalt-namespaced-concept.ttl",
        )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            lambda: (
                _fixture_bytes()
                .decode("utf-8")
                .replace('"Amaryllidaceae"@en', '"Amaryllidaceae"', 1)
            ),
            "untagged",
        ),
        (
            lambda: SYNTHETIC_FEATURE_EDGE_TURTLE.replace(
                '"AGR-001"^^<urn:example:notation-datatype>',
                '"AGR-001"',
                1,
            ),
            "typed literal",
        ),
        (
            lambda: (
                _fixture_bytes()
                .decode("utf-8")
                .replace(
                    '"Amaryllidaceae"@en,',
                    '"Amaryllidaceae (alt)"@en, "Amaryllidaceae"@en,',
                    1,
                )
            ),
            "more than one preferred label",
        ),
        (
            lambda: (
                _fixture_bytes()
                .decode("utf-8")
                .replace(
                    "<http://aims.fao.org/aos/agrovoc/c_331078>",
                    "[]",
                    1,
                )
            ),
            "must be an IRI",
        ),
    ],
)
def test_parser_rejects_lossy_or_ambiguous_skos_features(
    source,
    message: str,
) -> None:
    with pytest.raises(AgrovocParseError, match=message):
        parse_agrovoc_turtle(source(), source_url=FIXTURE_SOURCE_URL)


def test_parser_enforces_optional_distribution_digest_and_size_pins() -> None:
    source = _fixture_bytes()
    digest = "sha256:" + hashlib.sha256(source).hexdigest()
    parsed = parse_agrovoc_turtle(
        source,
        source_url=FIXTURE_SOURCE_URL,
        expected_sha256=digest,
        expected_byte_length=len(source),
    )
    assert parsed.source_sha256 == digest

    with pytest.raises(AgrovocParseError, match="digest mismatch"):
        parse_agrovoc_turtle(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_sha256="sha256:" + "0" * 64,
        )
    with pytest.raises(AgrovocParseError, match="byte length mismatch"):
        parse_agrovoc_turtle(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_byte_length=len(source) + 1,
        )


def test_import_counts_are_deterministic_over_the_mini_fixture() -> None:
    parsed = parse_agrovoc_turtle(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    assert parsed.counts == AgrovocImportCounts(
        source_bytes=len(_fixture_bytes()),
        triples=parsed.triple_count,
        source_iris=len(parsed.source_iris),
        concepts=3,
        concept_schemes=1,
        preferred_labels=5,
        alternate_labels=2,
        hidden_labels=0,
        notes=3,
        notations=0,
        broader_relations=2,
        narrower_relations=2,
        related_relations=1,
        mapping_relations=3,
        metadata_literals=2,
    )


def test_real_captured_sample_matches_its_pinned_digest_and_exposes_the_real_nalt_crosswalk() -> None:
    source = _real_sample_bytes()
    assert "sha256:" + hashlib.sha256(source).hexdigest() == AGROVOC_C330_SAMPLE.expected_sha256
    assert len(source) == AGROVOC_C330_SAMPLE.expected_byte_length

    parsed = parse_agrovoc_turtle(
        source,
        source_url=AGROVOC_C330_SAMPLE.source_url,
        expected_sha256=AGROVOC_C330_SAMPLE.expected_sha256,
        expected_byte_length=AGROVOC_C330_SAMPLE.expected_byte_length,
    )

    assert any(item.concept_iri == AGROVOC_C330_SAMPLE.concept_iri for item in parsed.concepts)
    concept = next(item for item in parsed.concepts if item.concept_iri == AGROVOC_C330_SAMPLE.concept_iri)
    assert AGROVOC_SCHEME_IRI in concept.scheme_iris

    crosswalk_targets = {item.object_iri for item in parsed.nalt_crosswalk_relations}
    assert NALT_TARGET in crosswalk_targets


def test_verified_local_acquisition_parses_with_the_same_sample_pin(tmp_path: Path) -> None:
    source = _real_sample_bytes()
    source_path = tmp_path / "agrovoc-c330-sample.ttl"
    source_path.write_bytes(source)

    acquired = acquire_agrovoc_sample(
        AGROVOC_C330_SAMPLE,
        tmp_path / "store",
        source_path=source_path,
    )
    assert acquired.cache_hit is False
    assert acquired.acquisition_mode == "local"

    parsed = parse_acquired_agrovoc_sample(acquired)
    assert parsed.source_sha256 == acquired.sha256
    assert parsed.source_bytes == acquired.byte_length

    reacquired = acquire_agrovoc_sample(
        AGROVOC_C330_SAMPLE,
        tmp_path / "store",
        source_path=source_path,
    )
    assert reacquired.cache_hit is True
    assert reacquired.acquisition_mode == "cache"


def test_acquisition_refuses_network_without_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(AgrovocAcquisitionError, match="allow_network"):
        acquire_agrovoc_sample(AGROVOC_C330_SAMPLE, tmp_path / "store")


def test_acquisition_rejects_a_local_source_that_fails_its_digest_pin(tmp_path: Path) -> None:
    bad_path = tmp_path / "wrong.ttl"
    bad_path.write_bytes(b"@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n")

    with pytest.raises(AgrovocAcquisitionError, match="mismatch"):
        acquire_agrovoc_sample(
            AGROVOC_C330_SAMPLE,
            tmp_path / "store",
            source_path=bad_path,
        )


def test_sample_source_rejects_a_concept_iri_inside_the_nalt_namespace() -> None:
    with pytest.raises(AgrovocAcquisitionError, match="NALT"):
        AgrovocSampleSource(
            label="bad",
            concept_iri="https://lod.nal.usda.gov/nalt/71469",
            scheme_iri=AGROVOC_SCHEME_IRI,
            source_url="https://example.test/bad.ttl",
            expected_sha256="sha256:" + "0" * 64,
            expected_byte_length=1,
            filename="bad.ttl",
        )


def test_parse_agrovoc_file_reads_a_local_file_while_keeping_its_external_source_url(
    tmp_path: Path,
) -> None:
    source = _fixture_bytes()
    source_path = tmp_path / "agrovoc-mini.ttl"
    source_path.write_bytes(source)

    parsed = parse_agrovoc_file(source_path, source_url=FIXTURE_SOURCE_URL)
    assert parsed.source_url == FIXTURE_SOURCE_URL
    assert parsed.source_bytes == len(source)
