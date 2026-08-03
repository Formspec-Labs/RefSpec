"""Lossless GEMET RDF/XML parser and acquisition tests."""

from __future__ import annotations

import gzip
import hashlib
import os
from pathlib import Path

import pytest

from refspec.registry.gemet_thesaurus import (
    ALT_LABEL_PREDICATE_IRI,
    BROADER_PREDICATE_IRI,
    GEMET_CONCEPT_SCHEME_IRI,
    GEMET_DEFINITION_SOURCE_PREDICATE_IRI,
    GEMET_METADATA_LITERAL_PREDICATE_IRIS,
    GEMET_NOTE_PREDICATE_IRIS,
    GEMET_RELEASE_4_2_3,
    HIDDEN_LABEL_PREDICATE_IRI,
    LICENSE_PREDICATE_IRI,
    NARROWER_PREDICATE_IRI,
    NOTE_PREDICATE_IRIS,
    PREF_LABEL_PREDICATE_IRI,
    RELATED_PREDICATE_IRI,
    GemetAcquisitionError,
    GemetImportCounts,
    GemetParseError,
    GemetReleaseSource,
    acquire_gemet_release,
    parse_acquired_gemet_source,
    parse_gemet_file,
    parse_gemet_rdf_xml,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "gemet_thesaurus" / "gemet-mini.rdf"
FIXTURE_SOURCE_URL = "https://example.test/gemet-mini.rdf"

BUILT_ENVIRONMENT = "http://www.eionet.europa.eu/gemet/concept/1063"
BUILT_UP_AREA = "http://www.eionet.europa.eu/gemet/concept/1065"
BUILDING = "http://www.eionet.europa.eu/gemet/concept/1029"
INFRASTRUCTURE = "http://www.eionet.europa.eu/gemet/concept/4321"
CADMIUM = "http://www.eionet.europa.eu/gemet/concept/1100"
CHEMICAL = "http://www.eionet.europa.eu/gemet/concept/1327"
NIMBY_APTITUDE = "http://www.eionet.europa.eu/gemet/concept/10968"
ANIMAL_LIFE = "http://www.eionet.europa.eu/gemet/concept/10003"

# Clearly synthetic: not copied from any GEMET distribution. It exercises the
# real (but out-of-scope) shape of GEMET's Group/Collection entities -- which
# reuse skos:prefLabel and, unlike concepts, an untagged skos:notation -- to
# prove the reader scopes typed features to concepts and the concept scheme
# rather than crashing on, or silently absorbing, shapes it does not model.
SYNTHETIC_OUT_OF_SCOPE_ENTITY_RDF_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:skos="http://www.w3.org/2004/02/skos/core#"
 xml:base="http://www.eionet.europa.eu/gemet/">

<skos:ConceptScheme rdf:about="gemetThesaurus">
  <skos:hasTopConcept rdf:resource="concept/1"/>
</skos:ConceptScheme>

<skos:Concept rdf:about="concept/1">
  <skos:inScheme rdf:resource="http://www.eionet.europa.eu/gemet/gemetThesaurus"/>
  <skos:prefLabel xml:lang="en">edge concept</skos:prefLabel>
</skos:Concept>

<rdf:Description rdf:about="group/1">
  <rdf:type rdf:resource="http://www.eionet.europa.eu/gemet/2004/06/gemet-schema.rdf#Group"/>
  <rdf:type rdf:resource="http://www.w3.org/2004/02/skos/core#Collection"/>
  <skos:prefLabel xml:lang="en">out-of-scope group label</skos:prefLabel>
  <skos:notation>untagged-group-notation</skos:notation>
</rdf:Description>

</rdf:RDF>
"""


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def _fixture_text() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_parser_preserves_source_derived_multilingual_labels_notes_and_iris() -> None:
    source = _fixture_bytes()
    parsed = parse_gemet_rdf_xml(source, source_url=FIXTURE_SOURCE_URL)

    assert parsed.source_url == FIXTURE_SOURCE_URL
    assert parsed.source_bytes == len(source)
    assert parsed.source_sha256 == "sha256:" + hashlib.sha256(source).hexdigest()
    assert parsed.triple_count > 0
    assert parsed == parse_gemet_rdf_xml(source, source_url=FIXTURE_SOURCE_URL)

    built_environment_labels = [item for item in parsed.labels if item.subject_iri == BUILT_ENVIRONMENT]
    preferred = {
        item.value.language_tag: item.value.lexical_form
        for item in built_environment_labels
        if item.property_iri == PREF_LABEL_PREDICATE_IRI
    }
    assert preferred == {
        "en": "built environment",
        "es": "ambiente construido",
        "fr": "environnement bâti",
    }
    assert {
        (item.property_iri, item.value.language_tag, item.value.lexical_form)
        for item in built_environment_labels
        if item.role != "preferred"
    } == {
        (ALT_LABEL_PREDICATE_IRI, "el", "αστικοποιημένο περιβάλλον"),
    }

    # A concept published with only one language pair (real, not trimmed)
    # is preserved as-is rather than requiring uniform language coverage.
    chemical_labels = [item for item in parsed.labels if item.subject_iri == CHEMICAL and item.role == "preferred"]
    assert len(chemical_labels) == 1
    assert chemical_labels[0].value.language_tag == "en"

    assert {item.property_iri for item in parsed.notes} == set(GEMET_NOTE_PREDICATE_IRIS)
    assert set(NOTE_PREDICATE_IRIS).issubset(item.property_iri for item in parsed.notes)
    source_note = next(
        item
        for item in parsed.notes
        if item.subject_iri == BUILT_ENVIRONMENT and item.property_iri == GEMET_DEFINITION_SOURCE_PREDICATE_IRI
    )
    assert source_note.value.lexical_form == "Goodall, B., Dictionary of Human Geography, Penguin Books, London, 1987"

    # A concept can carry an editorial note with no definition at all.
    assert not [item for item in parsed.notes if item.subject_iri == ANIMAL_LIFE and item.property_iri == "http://www.w3.org/2004/02/skos/core#definition"]
    assert any(item.subject_iri == ANIMAL_LIFE and item.property_iri == "http://www.w3.org/2004/02/skos/core#editorialNote" for item in parsed.notes)

    assert BUILT_ENVIRONMENT in parsed.source_iris
    # Relation targets outside this trimmed fixture remain visible, exact
    # dangling IRIs rather than being silently dropped or requiring a local
    # concept definition to exist.
    assert "http://www.eionet.europa.eu/gemet/concept/8629" in parsed.source_iris


def test_parser_relates_the_concept_scheme_hierarchy_and_crosswalk_mappings() -> None:
    parsed = parse_gemet_rdf_xml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    assert {
        (item.predicate_iri, item.object_iri) for item in parsed.semantic_relations if item.subject_iri == BUILT_ENVIRONMENT
    } == {
        (NARROWER_PREDICATE_IRI, BUILDING),
        (NARROWER_PREDICATE_IRI, INFRASTRUCTURE),
        (RELATED_PREDICATE_IRI, BUILT_UP_AREA),
    }
    assert {
        (item.predicate_iri, item.object_iri) for item in parsed.semantic_relations if item.subject_iri == BUILDING
    } == {
        (BROADER_PREDICATE_IRI, BUILT_ENVIRONMENT),
        (NARROWER_PREDICATE_IRI, "http://www.eionet.europa.eu/gemet/concept/1033"),
        (NARROWER_PREDICATE_IRI, "http://www.eionet.europa.eu/gemet/concept/1064"),
        (RELATED_PREDICATE_IRI, "http://www.eionet.europa.eu/gemet/concept/1046"),
        (RELATED_PREDICATE_IRI, "http://www.eionet.europa.eu/gemet/concept/4211"),
    }

    # Crosswalk targets are preserved as exact external authority IRIs.
    cadmium_mappings = {
        (item.predicate_iri, item.object_iri) for item in parsed.mapping_relations if item.subject_iri == CADMIUM
    }
    assert cadmium_mappings == {
        ("http://www.w3.org/2004/02/skos/core#exactMatch", "http://aims.fao.org/aos/agrovoc/c_1178"),
        ("http://www.w3.org/2004/02/skos/core#exactMatch", "http://eurovoc.europa.eu/3836"),
        ("http://www.w3.org/2004/02/skos/core#closeMatch", "http://data.uba.de/umt/_00005866"),
        ("http://www.w3.org/2004/02/skos/core#closeMatch", "http://dbpedia.org/resource/Cadmium"),
    }

    assert len(parsed.license_relations) == 1
    license_relation = parsed.license_relations[0]
    assert license_relation.subject_iri == GEMET_CONCEPT_SCHEME_IRI
    assert license_relation.predicate_iri == LICENSE_PREDICATE_IRI
    assert license_relation.object_iri == "http://creativecommons.org/licenses/by/4.0/"

    scheme = next(item for item in parsed.concept_schemes if item.scheme_iri == GEMET_CONCEPT_SCHEME_IRI)
    assert scheme.top_concept_iris == (
        BUILT_ENVIRONMENT,
        "http://www.eionet.europa.eu/gemet/concept/1084",
        "http://www.eionet.europa.eu/gemet/concept/11089",
        CHEMICAL,
    )

    built_environment_concept = next(item for item in parsed.concepts if item.concept_iri == BUILT_ENVIRONMENT)
    assert built_environment_concept.scheme_iris == (GEMET_CONCEPT_SCHEME_IRI,)
    assert built_environment_concept.top_concept_of_iris == ()

    display_label = next(
        item
        for item in parsed.metadata_literals
        if item.subject_iri == GEMET_CONCEPT_SCHEME_IRI and item.property_iri == "http://www.w3.org/2000/01/rdf-schema#label"
    )
    assert display_label.value.lexical_form == "GEMET - Concepts, version 4.2.3, 2021-12-06T13:37:25.364764+00:00"
    assert set(GEMET_METADATA_LITERAL_PREDICATE_IRIS).issuperset(item.property_iri for item in parsed.metadata_literals)


def test_notation_is_preserved_as_a_language_tagged_literal_not_a_typed_one() -> None:
    parsed = parse_gemet_rdf_xml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    assert len(parsed.notations) == 1
    notation = parsed.notations[0]
    assert notation.subject_iri == CADMIUM
    assert notation.value.lexical_form == "Cd"
    assert notation.value.language_tag == "en"
    assert notation.value.datatype_iri is None


def test_created_and_modified_are_preserved_as_the_empty_literal_gemet_actually_publishes() -> None:
    parsed = parse_gemet_rdf_xml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    lifecycle = [
        item
        for item in parsed.metadata_literals
        if item.subject_iri == BUILT_ENVIRONMENT
        and item.property_iri in ("http://purl.org/dc/terms/created", "http://purl.org/dc/terms/modified")
    ]
    assert len(lifecycle) == 2
    for item in lifecycle:
        assert item.value.lexical_form == ""
        assert item.value.datatype_iri == "http://www.w3.org/2001/XMLSchema#dateTime"
        assert item.value.language_tag is None


def test_hidden_label_is_scoped_to_the_concept_that_publishes_it() -> None:
    parsed = parse_gemet_rdf_xml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    assert {
        (item.subject_iri, item.value.lexical_form)
        for item in parsed.labels
        if item.property_iri == HIDDEN_LABEL_PREDICATE_IRI
    } == {(CHEMICAL, "chemicals")}


def test_scope_note_preserves_embedded_quote_characters_verbatim() -> None:
    parsed = parse_gemet_rdf_xml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    scope_note = next(
        item
        for item in parsed.notes
        if item.subject_iri == NIMBY_APTITUDE and item.property_iri == "http://www.w3.org/2004/02/skos/core#scopeNote"
    )
    assert scope_note.value.lexical_form == 'aptitude "not in my back yard"'


def test_typed_features_are_scoped_to_concepts_and_the_scheme_not_other_gemet_entities() -> None:
    """GEMET's own Group/Theme/SuperGroup collections and Source citations
    reuse SKOS predicates in shapes concepts do not use (e.g. an untagged
    skos:notation). The reader must neither crash on nor silently model
    those out-of-scope assertions -- it should leave them entirely out of
    the typed features while keeping them visible in the raw census."""

    parsed = parse_gemet_rdf_xml(SYNTHETIC_OUT_OF_SCOPE_ENTITY_RDF_XML, source_url="https://example.test/synthetic.rdf")

    assert len(parsed.concepts) == 1
    assert parsed.concepts[0].concept_iri == "http://www.eionet.europa.eu/gemet/concept/1"
    assert [item.value.lexical_form for item in parsed.labels] == ["edge concept"]
    assert parsed.notations == ()

    group_iri = "http://www.eionet.europa.eu/gemet/group/1"
    assert group_iri in parsed.source_iris
    predicate_counts = {item.predicate_iri: item.assertion_count for item in parsed.predicate_counts}
    assert predicate_counts["http://www.w3.org/2004/02/skos/core#prefLabel"] == 2
    assert predicate_counts["http://www.w3.org/2004/02/skos/core#notation"] == 1


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            lambda: _fixture_text().replace(
                '<skos:prefLabel xml:lang="en">built environment</skos:prefLabel>',
                "<skos:prefLabel>built environment</skos:prefLabel>",
                1,
            ),
            "untagged",
        ),
        (
            lambda: _fixture_text().replace(
                '<skos:notation xml:lang="en">Cd</skos:notation>',
                '<skos:notation rdf:datatype="urn:example:notation-datatype">Cd</skos:notation>',
                1,
            ),
            "has a datatype",
        ),
        (
            lambda: _fixture_text().replace(
                '<skos:notation xml:lang="en">Cd</skos:notation>',
                "<skos:notation>Cd</skos:notation>",
                1,
            ),
            "untagged",
        ),
        (
            lambda: _fixture_text().replace(
                '<skos:prefLabel xml:lang="en">built environment</skos:prefLabel>',
                '<skos:prefLabel xml:lang="en">built environment</skos:prefLabel>'
                '<skos:prefLabel xml:lang="en">CONFLICTING LABEL</skos:prefLabel>',
                1,
            ),
            "more than one preferred label",
        ),
        (
            lambda: _fixture_text().replace(
                '<skos:narrower rdf:resource="concept/1029"/>',
                '<skos:narrower rdf:nodeID="bn1"/>',
                1,
            ),
            "must be an IRI",
        ),
    ],
)
def test_parser_rejects_lossy_or_ambiguous_skos_features(source, message: str) -> None:
    with pytest.raises(GemetParseError, match=message):
        parse_gemet_rdf_xml(source(), source_url=FIXTURE_SOURCE_URL)


def test_parser_enforces_optional_distribution_digest_and_size_pins() -> None:
    source = _fixture_bytes()
    digest = "sha256:" + hashlib.sha256(source).hexdigest()
    parsed = parse_gemet_rdf_xml(
        source,
        source_url=FIXTURE_SOURCE_URL,
        expected_sha256=digest,
        expected_byte_length=len(source),
    )
    assert parsed.source_sha256 == digest

    with pytest.raises(GemetParseError, match="digest mismatch"):
        parse_gemet_rdf_xml(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_sha256="sha256:" + "0" * 64,
        )
    with pytest.raises(GemetParseError, match="byte length mismatch"):
        parse_gemet_rdf_xml(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_byte_length=len(source) + 1,
        )


def test_parse_gemet_file_reads_a_local_already_decompressed_distribution(tmp_path: Path) -> None:
    source = _fixture_bytes()
    path = tmp_path / "gemet-mini.rdf"
    path.write_bytes(source)

    parsed = parse_gemet_file(path, source_url=FIXTURE_SOURCE_URL)

    assert parsed.source_sha256 == "sha256:" + hashlib.sha256(source).hexdigest()


def _fixture_release(*, compressed: bool) -> tuple[GemetReleaseSource, bytes]:
    source = _fixture_bytes()
    payload = gzip.compress(source) if compressed else source
    release = GemetReleaseSource(
        version="fixture",
        concept_scheme_iri=GEMET_CONCEPT_SCHEME_IRI,
        source_url=FIXTURE_SOURCE_URL,
        landing_page_url="https://example.test/gemet-landing-page",
        expected_sha256="sha256:" + hashlib.sha256(source).hexdigest(),
        expected_byte_length=len(source),
        expected_compressed_sha256=("sha256:" + hashlib.sha256(payload).hexdigest()) if compressed else None,
        expected_compressed_byte_length=len(payload) if compressed else None,
        filename="gemet-mini.rdf",
    )
    return release, payload


def test_verified_local_acquisition_of_an_already_decompressed_source_parses(tmp_path: Path) -> None:
    release, payload = _fixture_release(compressed=False)
    source_path = tmp_path / "gemet-mini-source.rdf"
    source_path.write_bytes(payload)

    acquired = acquire_gemet_release(release, tmp_path / "store", source_path=source_path)

    assert acquired.cache_hit is False
    assert acquired.acquisition_mode == "local"
    assert acquired.compressed_sha256 is None

    parsed = parse_acquired_gemet_source(acquired)
    assert parsed.source_sha256 == acquired.sha256
    assert {item.scheme_iri for item in parsed.concept_schemes} == {release.concept_scheme_iri}


def test_verified_local_acquisition_decompresses_and_pins_both_the_compressed_and_raw_payload(tmp_path: Path) -> None:
    release, payload = _fixture_release(compressed=True)
    source_path = tmp_path / "gemet-mini-source.rdf.gz"
    source_path.write_bytes(payload)

    acquired = acquire_gemet_release(release, tmp_path / "store", source_path=source_path)

    assert acquired.compressed_sha256 == release.expected_compressed_sha256
    assert acquired.compressed_byte_length == len(payload)
    assert acquired.sha256 == release.expected_sha256

    parsed = parse_acquired_gemet_source(acquired)
    assert {item.scheme_iri for item in parsed.concept_schemes} == {release.concept_scheme_iri}

    # A second acquisition of the same pinned release hits the
    # content-addressed cache and no longer needs the compressed wrapper.
    acquired_again = acquire_gemet_release(release, tmp_path / "store", source_path=source_path)
    assert acquired_again.cache_hit is True
    assert acquired_again.compressed_sha256 is None


def test_acquisition_rejects_a_compressed_payload_that_does_not_match_the_pin(tmp_path: Path) -> None:
    release, payload = _fixture_release(compressed=True)
    tampered = payload + b"\x00"
    source_path = tmp_path / "tampered.rdf.gz"
    source_path.write_bytes(tampered)

    with pytest.raises(GemetAcquisitionError, match="compressed GEMET source"):
        acquire_gemet_release(release, tmp_path / "store", source_path=source_path)


def test_acquisition_rejects_a_decompressed_payload_that_does_not_match_the_pin(tmp_path: Path) -> None:
    release, _payload = _fixture_release(compressed=False)
    source_path = tmp_path / "tampered.rdf"
    # Same byte length, different content, so this exercises the digest
    # check rather than the (separately tested) byte-length check.
    tampered = _fixture_bytes().replace(b"cadmium", b"CADMIUM", 1)
    assert len(tampered) == len(_fixture_bytes())
    source_path.write_bytes(tampered)

    with pytest.raises(GemetAcquisitionError, match="digest mismatch"):
        acquire_gemet_release(release, tmp_path / "store", source_path=source_path)


def test_acquisition_refuses_the_network_without_explicit_opt_in(tmp_path: Path) -> None:
    release, _payload = _fixture_release(compressed=False)

    with pytest.raises(GemetAcquisitionError, match="allow_network"):
        acquire_gemet_release(release, tmp_path / "store")


def test_gemet_release_4_2_3_preserves_the_catalog_cited_landing_page_and_license() -> None:
    assert GEMET_RELEASE_4_2_3.version == "4.2.3"
    assert GEMET_RELEASE_4_2_3.concept_scheme_iri == GEMET_CONCEPT_SCHEME_IRI
    assert GEMET_RELEASE_4_2_3.landing_page_url == "https://www.eionet.europa.eu/gemet/en/exports/rdf/latest"
    assert GEMET_RELEASE_4_2_3.license_iri == "https://creativecommons.org/licenses/by/4.0/"


PINNED_REAL_COUNTS = GemetImportCounts(
    source_bytes=33_332_557,
    triples=323_635,
    source_iris=17_412,
    concepts=5_573,
    concept_schemes=1,
    preferred_labels=195_398,
    alternate_labels=5_598,
    hidden_labels=17,
    notes=52_044,
    notations=20,
    broader_relations=5_685,
    narrower_relations=5_689,
    related_relations=3_390,
    exact_match_relations=2_903,
    close_match_relations=5_522,
    broad_match_relations=221,
    narrow_match_relations=40,
    related_match_relations=972,
    mapping_relations=9_658,
    license_relations=1,
    metadata_literals=11_147,
    created_assertions=5_573,
    modified_assertions=5_573,
    display_label_assertions=1,
)


def test_opt_in_pinned_real_distribution_counts() -> None:
    source_path = os.environ.get("REFSPEC_GEMET_PATH")
    if source_path is None:
        pytest.skip(
            "set REFSPEC_GEMET_PATH to the exact verified, decompressed gemet.rdf distribution "
            f"({GEMET_RELEASE_4_2_3.expected_sha256})"
        )

    parsed = parse_gemet_file(
        Path(source_path),
        source_url=GEMET_RELEASE_4_2_3.source_url,
        expected_sha256=GEMET_RELEASE_4_2_3.expected_sha256,
        expected_byte_length=GEMET_RELEASE_4_2_3.expected_byte_length,
    )

    assert parsed.counts == PINNED_REAL_COUNTS
    assert {item.scheme_iri for item in parsed.concept_schemes} == {GEMET_RELEASE_4_2_3.concept_scheme_iri}
