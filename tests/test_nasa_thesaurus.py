"""Lossless NASA Thesaurus RDF/XML parser and acquisition tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from refspec.registry.nasa_thesaurus import (
    ANNOTATION_LITERAL_PREDICATE_IRIS,
    KNOWN_TERM_NOTE_MARKERS,
    LABEL_ANNOTATION_PREDICATE_IRI,
    METADATA_LITERAL_PREDICATE_IRIS,
    NASA_THESAURUS_RELEASES,
    NASA_THESAURUS_SKOS,
    SKOS_BROADER_PREDICATE_IRI,
    SKOS_NARROWER_PREDICATE_IRI,
    SKOS_RELATED_PREDICATE_IRI,
    TERM_ID_PREDICATE_IRI,
    TERM_NOTE_PREDICATE_IRI,
    TERM_UPDATE_PREDICATE_IRI,
    TERM_VOCABULARY_PREDICATE_IRI,
    USE_INSTEAD_PREDICATE_IRI,
    USED_FOR_PREDICATE_IRI,
    WEIGHT_ANNOTATION_PREDICATE_IRI,
    NasaThesaurusAcquisitionError,
    NasaThesaurusImportCounts,
    NasaThesaurusParseError,
    NasaThesaurusReleaseSource,
    acquire_nasa_thesaurus_release,
    parse_acquired_nasa_thesaurus_source,
    parse_nasa_thesaurus_file,
    parse_nasa_thesaurus_xml,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nasa_thesaurus" / "nasa-thesaurus-mini.xml"
FIXTURE_SOURCE_URL = "https://sti.nasa.gov/docs/thesaurus/thesaurus-SKOS.xml"

MARS_ODYSSEY = f"{FIXTURE_SOURCE_URL}#64538"
A1_AIRCRAFT = f"{FIXTURE_SOURCE_URL}#37801"
SKYRAIDER_ENTRY = f"{FIXTURE_SOURCE_URL}#185582"
ABILITIES = f"{FIXTURE_SOURCE_URL}#37824"
TILDE_ABSORBERS = f"{FIXTURE_SOURCE_URL}#37841"

# This edge case is deliberately synthetic: it is not a verbatim source excerpt,
# only a minimal probe for the reification-vs-annotation id split explained in
# the module docstring.
SYNTHETIC_REIFICATION_SPLIT_XML = """\
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
xmlns:skos="http://www.w3.org/2004/02/skos/core#"
xmlns:zthes="http://synaptica.net/zthes/"
xmlns:skm="http://synaptica.net/skm/">
<skos:Concept rdf:about="#1">
<skos:prefLabel>Probe term</skos:prefLabel>
<skos:related rdf:resource="#2" rdf:ID="r1-2" />
</skos:Concept>
<rdf:Description rdf:about="r1-2">
<zthes:weight>100</zthes:weight>
</rdf:Description>
</rdf:RDF>
"""


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def test_parser_preserves_real_captured_concepts_labels_relations_and_metadata() -> None:
    source = _fixture_bytes()
    parsed = parse_nasa_thesaurus_xml(source, source_url=FIXTURE_SOURCE_URL)

    assert parsed.source_url == FIXTURE_SOURCE_URL
    assert parsed.source_bytes == len(source)
    assert parsed.source_sha256 == "sha256:" + hashlib.sha256(source).hexdigest()
    assert parsed.triple_count > 0
    assert parsed == parse_nasa_thesaurus_xml(source, source_url=FIXTURE_SOURCE_URL)

    assert {item.concept_iri for item in parsed.concepts} == {
        MARS_ODYSSEY,
        A1_AIRCRAFT,
        SKYRAIDER_ENTRY,
        ABILITIES,
        TILDE_ABSORBERS,
    }

    preferred = {item.subject_iri: item.value.lexical_form for item in parsed.labels if item.role == "preferred"}
    assert preferred[MARS_ODYSSEY] == "2001 Mars Odyssey"
    assert preferred[A1_AIRCRAFT] == "A-1 aircraft"
    assert preferred[SKYRAIDER_ENTRY] == "Skyraider aircraft"
    assert preferred[TILDE_ABSORBERS] == "~ absorbers"

    alternate = {(item.subject_iri, item.value.lexical_form) for item in parsed.labels if item.role == "alternate"}
    assert alternate == {
        (A1_AIRCRAFT, "Skyraider aircraft"),
        (ABILITIES, "proficiency"),
        (ABILITIES, "skills"),
    }
    # The source never tags these labels; the parser must not require one.
    assert all(item.value.language_tag is None for item in parsed.labels)


def test_parser_keeps_use_reference_and_hierarchy_relations_as_distinct_predicates() -> None:
    parsed = parse_nasa_thesaurus_xml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    used_for = {
        (item.subject_iri, item.object_iri)
        for item in parsed.use_reference_relations
        if item.predicate_iri == USED_FOR_PREDICATE_IRI
    }
    assert used_for == {
        (A1_AIRCRAFT, SKYRAIDER_ENTRY),
        (ABILITIES, f"{FIXTURE_SOURCE_URL}#185093"),
        (ABILITIES, f"{FIXTURE_SOURCE_URL}#185576"),
    }
    use_instead = {
        (item.subject_iri, item.object_iri)
        for item in parsed.use_reference_relations
        if item.predicate_iri == USE_INSTEAD_PREDICATE_IRI
    }
    assert use_instead == {(SKYRAIDER_ENTRY, A1_AIRCRAFT)}

    broader = {
        (item.subject_iri, item.object_iri)
        for item in parsed.semantic_relations
        if item.predicate_iri == SKOS_BROADER_PREDICATE_IRI
    }
    assert (MARS_ODYSSEY, f"{FIXTURE_SOURCE_URL}#55662") in broader
    assert len(broader) == 4
    narrower = [item for item in parsed.semantic_relations if item.predicate_iri == SKOS_NARROWER_PREDICATE_IRI]
    assert narrower == [
        type(narrower[0])(
            subject_iri=ABILITIES,
            predicate_iri=SKOS_NARROWER_PREDICATE_IRI,
            object_iri=f"{FIXTURE_SOURCE_URL}#38627",
        )
    ]
    related = [item for item in parsed.semantic_relations if item.predicate_iri == SKOS_RELATED_PREDICATE_IRI]
    assert len(related) == 10


def test_parser_keeps_term_notes_as_verbatim_markers_not_resolved_text() -> None:
    parsed = parse_nasa_thesaurus_xml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    notes_by_subject = {item.subject_iri: item.value.lexical_form for item in parsed.notes}
    assert notes_by_subject[TILDE_ABSORBERS] == "Scope Note"
    assert all(item.value.lexical_form in KNOWN_TERM_NOTE_MARKERS for item in parsed.notes)
    assert all(item.property_iri == TERM_NOTE_PREDICATE_IRI for item in parsed.notes)


def test_parser_keeps_detached_annotation_literals_unlinked_from_any_concept() -> None:
    """The real distribution never asserts a triple joining a term note or
    relation edge to its detached ``zthes:label``/``zthes:weight`` annotation:
    ``rdf:ID`` on a property element always resolves to ``<base>#<id>``, while
    the matching ``<rdf:Description rdf:about="<id>">`` (no leading ``#``)
    resolves as a same-level relative path. This test locks that fact down so
    a future NASA capture that changes the convention is caught, not silently
    misjoined.
    """

    parsed = parse_nasa_thesaurus_xml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    definition_text = next(
        item.value.lexical_form
        for item in parsed.annotation_literals
        if item.property_iri == LABEL_ANNOTATION_PREDICATE_IRI and "Definition-64538" in item.subject_iri
    )
    assert definition_text.startswith("Mars orbiter mission")

    reified_definition_subject = f"{FIXTURE_SOURCE_URL}#Definition-64538"
    annotation_subjects = {item.subject_iri for item in parsed.annotation_literals}
    assert reified_definition_subject not in annotation_subjects
    assert all(subject != MARS_ODYSSEY for subject in annotation_subjects)

    weights = {
        item.value.lexical_form
        for item in parsed.annotation_literals
        if item.property_iri == WEIGHT_ANNOTATION_PREDICATE_IRI
    }
    assert weights == {"100"}
    assert set(ANNOTATION_LITERAL_PREDICATE_IRIS) == {LABEL_ANNOTATION_PREDICATE_IRI, WEIGHT_ANNOTATION_PREDICATE_IRI}


def test_parser_keeps_source_native_term_identifiers_as_metadata_literals() -> None:
    parsed = parse_nasa_thesaurus_xml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    term_ids = {
        item.subject_iri: item.value.lexical_form
        for item in parsed.metadata_literals
        if item.property_iri == TERM_ID_PREDICATE_IRI
    }
    assert term_ids[MARS_ODYSSEY] == "64538"
    assert term_ids[A1_AIRCRAFT] == "37801"
    assert {
        item.value.lexical_form
        for item in parsed.metadata_literals
        if item.property_iri == TERM_VOCABULARY_PREDICATE_IRI
    } == {"NASA Thesaurus"}
    assert {
        item.value.lexical_form for item in parsed.metadata_literals if item.property_iri == TERM_UPDATE_PREDICATE_IRI
    } == {"add"}
    assert set(METADATA_LITERAL_PREDICATE_IRIS).issuperset(item.property_iri for item in parsed.metadata_literals)


def test_counts_reflect_the_fixture_exactly() -> None:
    parsed = parse_nasa_thesaurus_xml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)
    counts = parsed.counts
    assert isinstance(counts, NasaThesaurusImportCounts)
    assert counts.concepts == 5
    assert counts.preferred_labels == 5
    assert counts.alternate_labels == 3
    assert counts.notes == 3
    assert counts.broader_relations == 4
    assert counts.narrower_relations == 1
    assert counts.related_relations == 10
    assert counts.used_for_relations == 3
    assert counts.use_relations == 1
    assert counts.label_annotations == 3
    assert counts.weight_annotations == 15


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            lambda: SYNTHETIC_REIFICATION_SPLIT_XML.replace("<skos:prefLabel>Probe term</skos:prefLabel>", "", 1),
            "prefLabel",
        ),
        (
            lambda: SYNTHETIC_REIFICATION_SPLIT_XML.replace(
                "<skos:prefLabel>Probe term</skos:prefLabel>",
                "<skos:prefLabel>Probe term</skos:prefLabel><skos:prefLabel>Second label</skos:prefLabel>",
                1,
            ),
            "prefLabel",
        ),
        (
            lambda: _fixture_bytes().decode("utf-8").replace(">Scope Note<", ">Unrecognized Note Kind<", 1),
            "unrecognized",
        ),
        (
            lambda: "not RDF/XML at all",
            "could not parse",
        ),
    ],
)
def test_parser_rejects_lossy_or_unrecognized_shapes(source, message: str) -> None:
    with pytest.raises(NasaThesaurusParseError, match=message):
        parse_nasa_thesaurus_xml(source(), source_url=FIXTURE_SOURCE_URL)


def test_parse_rejects_relative_source_url() -> None:
    with pytest.raises(NasaThesaurusParseError, match="absolute IRI"):
        parse_nasa_thesaurus_xml(_fixture_bytes(), source_url="/docs/thesaurus/thesaurus-SKOS.xml")


def test_parser_enforces_optional_distribution_digest_and_size_pins() -> None:
    source = _fixture_bytes()
    digest = "sha256:" + hashlib.sha256(source).hexdigest()
    parsed = parse_nasa_thesaurus_xml(
        source,
        source_url=FIXTURE_SOURCE_URL,
        expected_sha256=digest,
        expected_byte_length=len(source),
    )
    assert parsed.source_sha256 == digest

    with pytest.raises(NasaThesaurusParseError, match="digest mismatch"):
        parse_nasa_thesaurus_xml(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_sha256="sha256:" + "0" * 64,
        )
    with pytest.raises(NasaThesaurusParseError, match="byte length mismatch"):
        parse_nasa_thesaurus_xml(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_byte_length=len(source) + 1,
        )


def test_release_source_pins_the_real_captured_skos_distribution_and_its_attribution() -> None:
    assert NASA_THESAURUS_SKOS.source_url == FIXTURE_SOURCE_URL
    assert NASA_THESAURUS_SKOS.expected_sha256 == (
        "sha256:3cd92a0eb67c5656e4c740394abd2d27042ded79a4acf3e1286e73a7d863010f"
    )
    assert NASA_THESAURUS_SKOS.expected_byte_length == 32_943_406
    assert NASA_THESAURUS_SKOS.content_last_modified == "2026-04-24"
    assert NASA_THESAURUS_SKOS.citation_year == 2012
    assert "NASA STI Program" in NASA_THESAURUS_SKOS.citation_apa
    assert "cite the NASA STI Program" in NASA_THESAURUS_SKOS.attribution_requirement
    assert NASA_THESAURUS_RELEASES["skos"] is NASA_THESAURUS_SKOS


def test_release_source_rejects_incomplete_or_malformed_pins() -> None:
    base_kwargs = {
        "format_name": "SKOS",
        "source_url": FIXTURE_SOURCE_URL,
        "expected_sha256": "sha256:" + "a" * 64,
        "expected_byte_length": 100,
        "filename": "thesaurus-SKOS.xml",
        "content_last_modified": "2026-04-24",
        "citation_year": 2012,
        "citation_apa": "cite",
        "citation_mla": "cite",
        "citation_chicago": "cite",
        "attribution_requirement": "cite the NASA STI Program",
        "source_page_url": "https://sti.nasa.gov/nasa-thesaurus/",
    }
    with pytest.raises(NasaThesaurusAcquisitionError, match="content_last_modified"):
        NasaThesaurusReleaseSource(**{**base_kwargs, "content_last_modified": "04/24/2026"})
    with pytest.raises(NasaThesaurusAcquisitionError, match="filename"):
        NasaThesaurusReleaseSource(**{**base_kwargs, "filename": "sub/thesaurus-SKOS.xml"})
    with pytest.raises(NasaThesaurusAcquisitionError, match="expected_byte_length"):
        NasaThesaurusReleaseSource(**{**base_kwargs, "expected_byte_length": 0})


def test_verified_local_acquisition_parses_with_the_same_release_pin(tmp_path: Path) -> None:
    source = _fixture_bytes()
    source_path = tmp_path / "nasa-thesaurus-mini.xml"
    source_path.write_bytes(source)
    release = NasaThesaurusReleaseSource(
        format_name="SKOS",
        source_url=FIXTURE_SOURCE_URL,
        expected_sha256="sha256:" + hashlib.sha256(source).hexdigest(),
        expected_byte_length=len(source),
        filename="nasa-thesaurus-mini.xml",
        content_last_modified="2026-04-24",
        citation_year=2012,
        citation_apa="cite",
        citation_mla="cite",
        citation_chicago="cite",
        attribution_requirement="cite the NASA STI Program",
        source_page_url="https://sti.nasa.gov/nasa-thesaurus/",
    )
    acquired = acquire_nasa_thesaurus_release(
        release,
        tmp_path / "store",
        source_path=source_path,
    )

    parsed = parse_acquired_nasa_thesaurus_source(acquired)

    assert parsed.source_sha256 == acquired.sha256
    assert parsed.source_bytes == acquired.byte_length
    assert len(parsed.concepts) == 5


def test_acquisition_refuses_network_without_explicit_opt_in(tmp_path: Path) -> None:
    from refspec.registry.nasa_thesaurus import NasaThesaurusAcquisitionError as AcqError

    with pytest.raises(AcqError, match="allow_network"):
        acquire_nasa_thesaurus_release(NASA_THESAURUS_SKOS, tmp_path / "store")


PINNED_REAL_SKOS_COUNTS = NasaThesaurusImportCounts(
    source_bytes=32_943_406,
    triples=1_137_769,
    source_iris=362_693,
    concepts=22_622,
    preferred_labels=22_622,
    alternate_labels=4_503,
    notes=9_656,
    broader_relations=17_012,
    narrower_relations=17_012,
    related_relations=117_340,
    used_for_relations=4_503,
    use_relations=4_503,
    term_id_assertions=22_622,
    term_vocabulary_assertions=22_622,
    term_update_assertions=22_622,
    label_annotations=9_656,
    weight_annotations=160_370,
)


def test_opt_in_pinned_real_distribution_counts() -> None:
    source_path = os.environ.get("REFSPEC_NASA_THESAURUS_SKOS_PATH")
    if source_path is None:
        pytest.skip("set REFSPEC_NASA_THESAURUS_SKOS_PATH to the exact verified thesaurus-SKOS.xml distribution")

    parsed = parse_nasa_thesaurus_file(
        Path(source_path),
        source_url=NASA_THESAURUS_SKOS.source_url,
        expected_sha256=NASA_THESAURUS_SKOS.expected_sha256,
        expected_byte_length=NASA_THESAURUS_SKOS.expected_byte_length,
    )

    assert parsed.counts == PINNED_REAL_SKOS_COUNTS
