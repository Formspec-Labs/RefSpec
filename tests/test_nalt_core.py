"""Lossless NALT Core RDF/SKOS parser tests.

Fixtures are real, byte-exact Skosmos REST captures from
https://lod.nal.usda.gov/rest/v1/nalt-core/data (and, for the negative-scope
fixture, https://lod.nal.usda.gov/rest/v1/nalt/data). No test opens a network
connection; every payload is a fixture file already checked into the repo.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from refspec.registry.nalt_core import (
    ALT_LABEL_PREDICATE_IRI,
    BROADER_PREDICATE_IRI,
    HIDDEN_LABEL_PREDICATE_IRI,
    NALT_CORE_ANIMAL_WELFARE_CAPTURE,
    NALT_CORE_CATALOG_ROLE,
    NALT_CORE_LICENSE_NOTICE,
    NALT_CORE_PUBLISHER,
    NALT_CORE_SCHEME_IRI,
    NALT_CORE_TOP_CONCEPT_CAPTURE,
    NALT_FULL_OUT_OF_SCOPE_CAPTURE,
    NARROWER_PREDICATE_IRI,
    PREF_LABEL_PREDICATE_IRI,
    RELATED_PREDICATE_IRI,
    NaltCoreError,
    NaltFetchedResource,
    NaltImportCounts,
    acquire_nalt_core_concept,
    nalt_core_capture_digest,
    nalt_core_capture_manifest,
    parse_nalt_core_capture,
    parse_nalt_core_file,
    parse_nalt_turtle,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "nalt_core"
ANIMAL_WELFARE_PATH = FIXTURE_DIR / "nalt-core-9084-animal-welfare.ttl"
TOP_CONCEPT_PATH = FIXTURE_DIR / "nalt-core-127295-top-concept.ttl"
OUT_OF_SCOPE_PATH = FIXTURE_DIR / "nalt-full-143005-out-of-core-scope.ttl"

ANIMAL_WELFARE_IRI = "https://lod.nal.usda.gov/nalt/9084"
TOP_CONCEPT_IRI = "https://lod.nal.usda.gov/nalt/127295"
OUT_OF_SCOPE_IRI = "https://lod.nal.usda.gov/nalt/143005"
NEIGHBOR_ORGANISM_IRI = "https://lod.nal.usda.gov/nalt/65"
NALT_TOPIC_TYPE_IRI = "https://lod.nal.usda.gov/naltv#Topic"
NALT_ORGANISM_TYPE_IRI = "https://lod.nal.usda.gov/naltv#Organism"
NALT_FULL_SCHEME_IRI = "https://lod.nal.usda.gov/nalt"

SYNTHETIC_MINIMAL_CORE_TURTLE = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
<https://lod.nal.usda.gov/nalt-core> a skos:ConceptScheme .
<urn:example:edge> a skos:Concept ;
    skos:inScheme <https://lod.nal.usda.gov/nalt-core> ;
    skos:prefLabel "Edge concept"@en ;
    skos:hiddenLabel "Internal term"@en .
"""

SYNTHETIC_UNTAGGED_VALUE_TURTLE = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
<https://lod.nal.usda.gov/nalt-core> a skos:ConceptScheme .
<urn:example:edge> a skos:Concept ;
    skos:inScheme <https://lod.nal.usda.gov/nalt-core> ;
    skos:prefLabel "Edge concept"@en ;
    skos:definition <urn:example:edge_def> .
<urn:example:edge_def> rdf:value "Untagged definition text" .
"""


def _fixture_bytes(path: Path) -> bytes:
    return path.read_bytes()


def test_parser_preserves_labels_definitions_mappings_and_facet_type_for_a_core_concept() -> None:
    source = _fixture_bytes(ANIMAL_WELFARE_PATH)
    vocabulary = parse_nalt_turtle(source, source_url=NALT_CORE_ANIMAL_WELFARE_CAPTURE.source_url)

    assert vocabulary.source_bytes == len(source)
    assert vocabulary.source_sha256 == "sha256:" + hashlib.sha256(source).hexdigest()
    assert vocabulary == parse_nalt_turtle(source, source_url=NALT_CORE_ANIMAL_WELFARE_CAPTURE.source_url)

    concept = next(item for item in vocabulary.concepts if item.concept_iri == ANIMAL_WELFARE_IRI)
    assert concept.in_core_scope is True
    assert set(concept.scheme_iris) == {
        NALT_CORE_SCHEME_IRI,
        "https://lod.nal.usda.gov/nalt-awic",
        NALT_FULL_SCHEME_IRI,
    }
    assert concept.top_concept_of_iris == ()
    assert concept.type_iris == (NALT_TOPIC_TYPE_IRI,)

    preferred = {
        item.value.language_tag: item.value.lexical_form
        for item in vocabulary.labels
        if item.subject_iri == ANIMAL_WELFARE_IRI and item.property_iri == PREF_LABEL_PREDICATE_IRI
    }
    assert preferred == {"en": "animal welfare", "es": "mantenimiento del bienestar animal"}
    assert {
        item.value.lexical_form
        for item in vocabulary.labels
        if item.subject_iri == ANIMAL_WELFARE_IRI and item.property_iri == ALT_LABEL_PREDICATE_IRI
    } == {
        "humane treatment of animals",
        "anticruelty law (animals)",
        "derechos de los animales",
        "animal rights",
        "animal abuse",
        "tratamiento humanitario de los animales",
        "ley contra la crueldad con los animales",
        "cruelty to animals",
        "animal cruelty",
        "anti-cruelty law (animals)",
    }
    assert {
        item.value.lexical_form
        for item in vocabulary.labels
        if item.subject_iri == ANIMAL_WELFARE_IRI and item.property_iri == HIDDEN_LABEL_PREDICATE_IRI
    } == {
        "livestock welfare",
        "fish welfare",
        "animal welfare-based",
        "welfare of animals",
        "animal-welfare",
        "animal friendliness",
    }

    definition_relation = next(item for item in vocabulary.definition_relations if item.subject_iri == ANIMAL_WELFARE_IRI)
    definition_iri = definition_relation.object_iri
    assert definition_iri == f"{ANIMAL_WELFARE_IRI}_def"
    values = {
        item.value.language_tag: item.value.lexical_form
        for item in vocabulary.reified_values
        if item.subject_iri == definition_iri
    }
    assert values["en"].startswith("The protection of animals in laboratories")
    assert values["es"].startswith("Protección de los animales")
    sources = [item.value.lexical_form for item in vocabulary.reified_sources if item.subject_iri == definition_iri]
    assert sources == ["Medical Subject Headings AWIC Staff"]

    mapping_objects = {
        (item.predicate_iri, item.object_iri) for item in vocabulary.mapping_relations if item.subject_iri == ANIMAL_WELFARE_IRI
    }
    assert mapping_objects == {
        ("http://www.w3.org/2004/02/skos/core#closeMatch", "http://id.loc.gov/authorities/subjects/sh89005495"),
        ("http://www.w3.org/2004/02/skos/core#exactMatch", "http://id.cabi.org/cabt/10710"),
        ("http://www.w3.org/2004/02/skos/core#exactMatch", "http://id.agrisemantics.org/gacs/C2208"),
        ("http://www.w3.org/2004/02/skos/core#exactMatch", "http://aims.fao.org/aos/agrovoc/c_443"),
    }

    assert {
        (item.predicate_iri, item.object_iri)
        for item in vocabulary.semantic_relations
        if item.subject_iri == ANIMAL_WELFARE_IRI and item.predicate_iri != RELATED_PREDICATE_IRI
    } == {
        (BROADER_PREDICATE_IRI, "https://lod.nal.usda.gov/nalt/127295"),
        (BROADER_PREDICATE_IRI, "https://lod.nal.usda.gov/nalt/127297"),
        (NARROWER_PREDICATE_IRI, "https://lod.nal.usda.gov/nalt/34035"),
        (NARROWER_PREDICATE_IRI, "https://lod.nal.usda.gov/nalt/198222"),
        (NARROWER_PREDICATE_IRI, "https://lod.nal.usda.gov/nalt/1733"),
        (NARROWER_PREDICATE_IRI, "https://lod.nal.usda.gov/nalt/7182"),
        (NARROWER_PREDICATE_IRI, "https://lod.nal.usda.gov/nalt/9565"),
        (NARROWER_PREDICATE_IRI, "https://lod.nal.usda.gov/nalt/9237"),
    }
    related_objects = {
        item.object_iri for item in vocabulary.semantic_relations
        if item.subject_iri == ANIMAL_WELFARE_IRI and item.predicate_iri == RELATED_PREDICATE_IRI
    }
    assert len(related_objects) == 10

    metadata = {
        item.property_iri: item.value.lexical_form
        for item in vocabulary.metadata_literals
        if item.subject_iri == ANIMAL_WELFARE_IRI
    }
    assert metadata["http://purl.org/dc/terms/created"] == "2006-01-19"
    assert metadata["http://purl.org/dc/terms/modified"] == "2020-04-14"
    assert metadata["https://lod.nal.usda.gov/naltv#marc001"] == "2603"

    scheme = next(item for item in vocabulary.concept_schemes if item.scheme_iri == NALT_CORE_SCHEME_IRI)
    assert {(label.language_tag, label.lexical_form) for label in scheme.labels} == {
        ("en", "NALT Core"),
        ("es", "NALT Core"),
    }
    assert scheme.publisher_iris == ()

    assert vocabulary.counts == NaltImportCounts(
        source_bytes=len(source),
        triples=148,
        source_iris=vocabulary.counts.source_iris,
        concepts=19,
        core_scope_concepts=1,
        concept_schemes=1,
        preferred_labels=38,
        alternate_labels=10,
        hidden_labels=6,
        broader_relations=8,
        narrower_relations=8,
        related_relations=20,
        mapping_relations=4,
        definition_relations=1,
        reified_values=2,
        reified_sources=1,
        metadata_literals=3,
        created_assertions=1,
        modified_assertions=1,
        marc001_assertions=1,
    )


def test_parser_scopes_top_concept_and_never_promotes_a_bare_neighbor_stub_into_core() -> None:
    source = _fixture_bytes(TOP_CONCEPT_PATH)
    vocabulary = parse_nalt_turtle(source, source_url=NALT_CORE_TOP_CONCEPT_CAPTURE.source_url)

    concept = next(item for item in vocabulary.concepts if item.concept_iri == TOP_CONCEPT_IRI)
    assert concept.in_core_scope is True
    assert concept.top_concept_of_iris == (NALT_CORE_SCHEME_IRI,)
    assert set(concept.scheme_iris) == {NALT_CORE_SCHEME_IRI, NALT_FULL_SCHEME_IRI}

    scheme = next(item for item in vocabulary.concept_schemes if item.scheme_iri == NALT_CORE_SCHEME_IRI)
    assert scheme.top_concept_iris == (TOP_CONCEPT_IRI,)

    # nalt:65 is only ever referenced as a broader-relation neighbor in this
    # capture; it carries no skos:inScheme assertion of its own here, so it
    # must not be reported as a Core-scope concept even though it is typed
    # naltv:Organism and is a genuine skos:Concept in the payload.
    neighbor = next(item for item in vocabulary.concepts if item.concept_iri == NEIGHBOR_ORGANISM_IRI)
    assert neighbor.scheme_iris == ()
    assert neighbor.in_core_scope is False
    assert neighbor.type_iris == (NALT_ORGANISM_TYPE_IRI,)

    # The definition node exists but was captured with neither an rdf:value
    # nor a dc:source; the relation is preserved without inventing content.
    definition_relation = next(item for item in vocabulary.definition_relations if item.subject_iri == TOP_CONCEPT_IRI)
    assert not [item for item in vocabulary.reified_values if item.subject_iri == definition_relation.object_iri]
    assert not [item for item in vocabulary.reified_sources if item.subject_iri == definition_relation.object_iri]

    assert vocabulary.counts == NaltImportCounts(
        source_bytes=len(source),
        triples=99,
        source_iris=vocabulary.counts.source_iris,
        concepts=14,
        core_scope_concepts=1,
        concept_schemes=1,
        preferred_labels=28,
        alternate_labels=0,
        hidden_labels=3,
        broader_relations=13,
        narrower_relations=13,
        related_relations=0,
        mapping_relations=0,
        definition_relations=1,
        reified_values=0,
        reified_sources=0,
        metadata_literals=3,
        created_assertions=1,
        modified_assertions=1,
        marc001_assertions=1,
    )


def test_parse_nalt_core_capture_refuses_a_payload_that_never_asserts_the_core_scheme() -> None:
    source = _fixture_bytes(OUT_OF_SCOPE_PATH)

    # Sanity: the source genuinely omits Core; it publishes the Full scheme.
    vocabulary = parse_nalt_turtle(source, source_url=NALT_FULL_OUT_OF_SCOPE_CAPTURE.source_url)
    assert {item.scheme_iri for item in vocabulary.concept_schemes} == {NALT_FULL_SCHEME_IRI}
    full_scheme = vocabulary.concept_schemes[0]
    assert {(label.language_tag, label.lexical_form) for label in full_scheme.labels} == {("en", "NALT Full")}
    assert full_scheme.publisher_iris == (OUT_OF_SCOPE_IRI,)

    with pytest.raises(NaltCoreError, match="does not assert the NALT Core concept scheme"):
        parse_nalt_core_capture(
            source,
            source_url=NALT_FULL_OUT_OF_SCOPE_CAPTURE.source_url,
            concept_iri=OUT_OF_SCOPE_IRI,
        )


def test_parse_nalt_core_capture_refuses_a_requested_concept_missing_core_membership() -> None:
    payload = SYNTHETIC_MINIMAL_CORE_TURTLE.replace(
        "skos:inScheme <https://lod.nal.usda.gov/nalt-core> ;\n    ",
        "",
    )
    with pytest.raises(NaltCoreError, match="is not asserted as a member of NALT Core"):
        parse_nalt_core_capture(
            payload,
            source_url="https://example.test/nalt-core-edge.ttl",
            concept_iri="urn:example:edge",
        )


def test_parse_nalt_core_capture_refuses_a_requested_concept_absent_from_the_payload() -> None:
    with pytest.raises(NaltCoreError, match="absent from the capture"):
        parse_nalt_core_capture(
            SYNTHETIC_MINIMAL_CORE_TURTLE,
            source_url="https://example.test/nalt-core-edge.ttl",
            concept_iri="urn:example:does-not-exist",
        )


def test_parse_nalt_core_capture_accepts_a_synthetic_minimal_core_concept() -> None:
    capture = parse_nalt_core_capture(
        SYNTHETIC_MINIMAL_CORE_TURTLE,
        source_url="https://example.test/nalt-core-edge.ttl",
        concept_iri="urn:example:edge",
    )
    assert capture.requested_concept.in_core_scope is True
    assert capture.requested_concept.concept_iri == "urn:example:edge"


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            SYNTHETIC_MINIMAL_CORE_TURTLE.replace('"Edge concept"@en', '"Edge concept"'),
            "untagged",
        ),
        (
            SYNTHETIC_MINIMAL_CORE_TURTLE.replace(
                "<urn:example:edge>",
                "[]",
            ),
            "must be an IRI",
        ),
        (
            SYNTHETIC_UNTAGGED_VALUE_TURTLE,
            "untagged",
        ),
    ],
)
def test_parser_rejects_lossy_or_ambiguous_features(source: str, message: str) -> None:
    with pytest.raises(NaltCoreError, match=message):
        parse_nalt_turtle(source, source_url="https://example.test/nalt-core-edge.ttl")


def test_parser_enforces_optional_distribution_digest_and_size_pins() -> None:
    source = _fixture_bytes(ANIMAL_WELFARE_PATH)
    digest = "sha256:" + hashlib.sha256(source).hexdigest()
    parsed = parse_nalt_turtle(
        source,
        source_url=NALT_CORE_ANIMAL_WELFARE_CAPTURE.source_url,
        expected_sha256=digest,
        expected_byte_length=len(source),
    )
    assert parsed.source_sha256 == digest

    with pytest.raises(NaltCoreError, match="digest mismatch"):
        parse_nalt_turtle(
            source,
            source_url=NALT_CORE_ANIMAL_WELFARE_CAPTURE.source_url,
            expected_sha256="sha256:" + "0" * 64,
        )
    with pytest.raises(NaltCoreError, match="byte length mismatch"):
        parse_nalt_turtle(
            source,
            source_url=NALT_CORE_ANIMAL_WELFARE_CAPTURE.source_url,
            expected_byte_length=len(source) + 1,
        )


@pytest.mark.parametrize(
    ("pinned", "path"),
    [
        (NALT_CORE_ANIMAL_WELFARE_CAPTURE, ANIMAL_WELFARE_PATH),
        (NALT_CORE_TOP_CONCEPT_CAPTURE, TOP_CONCEPT_PATH),
    ],
)
def test_pinned_real_captures_match_committed_fixture_bytes_and_parse_as_core(pinned, path: Path) -> None:
    source = path.read_bytes()
    assert len(source) == pinned.expected_byte_length
    assert "sha256:" + hashlib.sha256(source).hexdigest() == pinned.expected_sha256

    capture = parse_nalt_core_capture(
        source,
        source_url=pinned.source_url,
        concept_iri=pinned.concept_iri,
        expected_sha256=pinned.expected_sha256,
        expected_byte_length=pinned.expected_byte_length,
    )
    assert capture.requested_concept_iri == pinned.concept_iri
    assert capture.requested_concept.in_core_scope is True


def test_pinned_out_of_scope_capture_matches_bytes_but_still_refuses_core_promotion() -> None:
    source = OUT_OF_SCOPE_PATH.read_bytes()
    pinned = NALT_FULL_OUT_OF_SCOPE_CAPTURE
    assert len(source) == pinned.expected_byte_length
    assert "sha256:" + hashlib.sha256(source).hexdigest() == pinned.expected_sha256

    with pytest.raises(NaltCoreError):
        parse_nalt_core_capture(
            source,
            source_url=pinned.source_url,
            concept_iri=pinned.concept_iri,
            expected_sha256=pinned.expected_sha256,
            expected_byte_length=pinned.expected_byte_length,
        )


def test_parse_nalt_core_file_reads_a_local_pinned_fixture(tmp_path: Path) -> None:
    pinned = NALT_CORE_ANIMAL_WELFARE_CAPTURE
    source = ANIMAL_WELFARE_PATH.read_bytes()
    local_path = tmp_path / "capture.ttl"
    local_path.write_bytes(source)

    capture = parse_nalt_core_file(
        local_path,
        source_url=pinned.source_url,
        concept_iri=pinned.concept_iri,
        expected_sha256=pinned.expected_sha256,
        expected_byte_length=pinned.expected_byte_length,
    )
    assert capture.requested_concept_iri == pinned.concept_iri

    with pytest.raises(NaltCoreError, match="not a regular file"):
        parse_nalt_core_file(
            tmp_path / "missing.ttl",
            source_url=pinned.source_url,
            concept_iri=pinned.concept_iri,
        )


def test_acquire_nalt_core_concept_requires_an_explicit_transport() -> None:
    with pytest.raises(NaltCoreError, match="requires fetch or allow_direct_network=True"):
        acquire_nalt_core_concept(ANIMAL_WELFARE_IRI)


def test_acquire_nalt_core_concept_uses_an_injected_fetcher_and_matches_direct_parsing() -> None:
    body = _fixture_bytes(ANIMAL_WELFARE_PATH)
    expected_url = (
        "https://lod.nal.usda.gov/rest/v1/nalt-core/data"
        f"?uri={ANIMAL_WELFARE_IRI.replace(':', '%3A').replace('/', '%2F')}&format=text%2Fturtle"
    )

    def fetch(url: str, *, timeout_seconds: float, max_bytes: int) -> NaltFetchedResource:
        assert url == expected_url
        assert timeout_seconds > 0
        assert max_bytes > 0
        return NaltFetchedResource(
            requested_url=url,
            resolved_url=url,
            status_code=200,
            content_type="text/turtle; charset=utf-8",
            body=body,
        )

    capture = acquire_nalt_core_concept(ANIMAL_WELFARE_IRI, fetch=fetch)
    direct = parse_nalt_core_capture(body, source_url=expected_url, concept_iri=ANIMAL_WELFARE_IRI)
    assert capture == direct


def test_acquire_nalt_core_concept_rejects_a_non_200_response() -> None:
    def fetch(url: str, *, timeout_seconds: float, max_bytes: int) -> NaltFetchedResource:
        return NaltFetchedResource(
            requested_url=url,
            resolved_url=url,
            status_code=404,
            content_type="text/html",
            body=b"not found",
        )

    with pytest.raises(NaltCoreError, match="HTTP 404"):
        acquire_nalt_core_concept(ANIMAL_WELFARE_IRI, fetch=fetch)


def test_acquire_nalt_core_concept_rejects_a_mismatched_requested_url() -> None:
    def fetch(url: str, *, timeout_seconds: float, max_bytes: int) -> NaltFetchedResource:
        return NaltFetchedResource(
            requested_url="https://lod.nal.usda.gov/rest/v1/nalt-core/data?uri=wrong",
            resolved_url="https://lod.nal.usda.gov/rest/v1/nalt-core/data?uri=wrong",
            status_code=200,
            content_type="text/turtle",
            body=b"",
        )

    with pytest.raises(NaltCoreError, match="different requested_url"):
        acquire_nalt_core_concept(ANIMAL_WELFARE_IRI, fetch=fetch)


def test_acquire_nalt_core_concept_rejects_a_response_over_max_bytes() -> None:
    def fetch(url: str, *, timeout_seconds: float, max_bytes: int) -> NaltFetchedResource:
        return NaltFetchedResource(
            requested_url=url,
            resolved_url=url,
            status_code=200,
            content_type="text/turtle",
            body=b"x" * (max_bytes + 1),
        )

    with pytest.raises(NaltCoreError, match="exceeds max_bytes"):
        acquire_nalt_core_concept(ANIMAL_WELFARE_IRI, fetch=fetch, max_bytes=16)


def test_nalt_core_capture_manifest_is_deterministic_and_records_the_license_conflict() -> None:
    capture = parse_nalt_core_capture(
        _fixture_bytes(ANIMAL_WELFARE_PATH),
        source_url=NALT_CORE_ANIMAL_WELFARE_CAPTURE.source_url,
        concept_iri=ANIMAL_WELFARE_IRI,
    )
    manifest = nalt_core_capture_manifest(capture)
    assert manifest == nalt_core_capture_manifest(capture)
    assert manifest["conceptSchemeIri"] == NALT_CORE_SCHEME_IRI
    assert manifest["publisher"] == NALT_CORE_PUBLISHER
    assert "Pilot Core only" in manifest["catalogRole"]
    assert "NALT Full is mappings-support" in manifest["catalogRole"]
    assert manifest["catalogRole"] == NALT_CORE_CATALOG_ROLE

    license_notice = manifest["license"]
    assert license_notice["statedLicenseIri"] == "https://creativecommons.org/licenses/by/4.0/"
    assert license_notice["resolved"] is False
    assert "public domain" in license_notice["conflictingClaim"].lower() or "cc0" in license_notice["conflictingClaim"].lower()
    assert NALT_CORE_LICENSE_NOTICE.resolved is False

    digest_a = nalt_core_capture_digest(capture)
    digest_b = nalt_core_capture_digest(capture)
    assert digest_a == digest_b
    assert digest_a.startswith("sha256:")

    other_capture = parse_nalt_core_capture(
        _fixture_bytes(TOP_CONCEPT_PATH),
        source_url=NALT_CORE_TOP_CONCEPT_CAPTURE.source_url,
        concept_iri=TOP_CONCEPT_IRI,
    )
    assert nalt_core_capture_digest(other_capture) != digest_a
