"""EuroVoc SKOS mapping-reference reader tests.

EuroVoc's catalog role is "Benchmark and mapping reference only; do not
import its European Union-centered scheme wholesale" (see
research/source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md). These
tests hold the parser to that role: it must refuse any accepted use other
than ``mappingReference``, and it must keep EuroVoc's 21 domains, its
micro-thesauri, and its concepts as separate, publisher-identified records
rather than a promoted RefSpec concept scheme.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from refspec.registry.eurovoc_thesaurus import (
    EUROVOC_SAMPLE_2026_08_03,
    HAS_TOP_CONCEPT_PREDICATE_IRI,
    HIERARCHY_PREDICATE_IRIS,
    SCHEME_MEMBERSHIP_PREDICATE_IRI,
    STATUS_PREDICATE_IRI,
    TOP_CONCEPT_OF_PREDICATE_IRI,
    AcquiredEuroVocSample,
    EuroVocAcquisitionError,
    EuroVocSampleSource,
    EuroVocThesaurusError,
    acquire_eurovoc_sample,
    parse_acquired_eurovoc_sample,
    parse_eurovoc_file,
    parse_eurovoc_turtle,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "eurovoc_thesaurus" / "eurovoc-domains-sample-2026-08-03.ttl"
FIXTURE_SOURCE_URL = EUROVOC_SAMPLE_2026_08_03.source_url

CONCEPT_SEAT = "http://eurovoc.europa.eu/4157"
CONCEPT_VACANT_SEAT = "http://eurovoc.europa.eu/4159"
CONCEPT_ALLOCATION = "http://eurovoc.europa.eu/3313"
CONCEPT_INTL_ORG = "http://eurovoc.europa.eu/2189"
DOMAIN_POLITICS = "http://eurovoc.europa.eu/100142"
DOMAIN_INTL_RELATIONS = "http://eurovoc.europa.eu/100143"
GROUP_ELECTORAL = "http://eurovoc.europa.eu/100165"
GROUP_INTL_AFFAIRS = "http://eurovoc.europa.eu/100170"
THESAURUS_IRI = "http://eurovoc.europa.eu/100141"
DOMAINS_SCHEME_IRI = "http://eurovoc.europa.eu/domains"
CURRENT_STATUS_IRI = "http://publications.europa.eu/resource/authority/concept-status/CURRENT"

SYNTHETIC_EDGE_TURTLE = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dc: <http://purl.org/dc/elements/1.1/> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix schema: <http://eurovoc.europa.eu/schema#> .
@prefix euvoc: <http://publications.europa.eu/ontology/euvoc#> .

<urn:example:thesaurus> a skos:ConceptScheme, schema:Thesaurus ;
    owl:versionInfo "9.9" .

<urn:example:domains> a skos:ConceptScheme ;
    skos:hasTopConcept <urn:example:domain-01> .

<urn:example:domain-01> a schema:Domain, skos:Concept ;
    skos:inScheme <urn:example:domains> ;
    skos:topConceptOf <urn:example:domains> ;
    dc:identifier "01" ;
    dcterms:identifier "01" ;
    skos:notation "01" ;
    skos:prefLabel "Edge domain"@en .

<urn:example:group-0101> a skos:ConceptScheme, schema:MicroThesaurus ;
    dc:identifier "0101" ;
    dcterms:identifier "0101" ;
    skos:notation "0101" ;
    dcterms:isPartOf <urn:example:thesaurus> ;
    euvoc:domain <urn:example:domain-01> ;
    skos:hasTopConcept <urn:example:edge> .

<urn:example:edge> a skos:Concept ;
    skos:inScheme <urn:example:thesaurus>, <urn:example:group-0101> ;
    skos:topConceptOf <urn:example:group-0101> ;
    dc:identifier "900001" ;
    dcterms:identifier "900001" ;
    skos:notation "900001" ;
    skos:prefLabel "Edge concept"@en ;
    skos:hiddenLabel "Internal term"@en ;
    euvoc:status <http://publications.europa.eu/resource/authority/concept-status/CURRENT> .
"""


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def test_parser_separates_domains_domain_groups_and_concepts_with_source_identifiers() -> None:
    source = _fixture_bytes()
    parsed = parse_eurovoc_turtle(source, source_url=FIXTURE_SOURCE_URL, accepted_use="mappingReference")

    assert parsed.source_url == FIXTURE_SOURCE_URL
    assert parsed.source_bytes == len(source)
    assert parsed.source_sha256 == "sha256:" + hashlib.sha256(source).hexdigest()
    assert parsed.triple_count > 0
    assert parsed.role == "mappingReference"
    assert parsed == parse_eurovoc_turtle(source, source_url=FIXTURE_SOURCE_URL, accepted_use="mappingReference")

    assert parsed.thesaurus_iri == THESAURUS_IRI
    assert parsed.thesaurus_version == "4.24"
    assert parsed.domains_scheme_iri == DOMAINS_SCHEME_IRI

    assert {(item.domain_iri, item.code) for item in parsed.domains} == {
        (DOMAIN_POLITICS, "04"),
        (DOMAIN_INTL_RELATIONS, "08"),
    }
    assert {(item.group_iri, item.code, item.domain_iri) for item in parsed.domain_groups} == {
        (GROUP_ELECTORAL, "0416", DOMAIN_POLITICS),
        (GROUP_INTL_AFFAIRS, "0806", DOMAIN_INTL_RELATIONS),
    }
    assert {(item.concept_iri, item.notation) for item in parsed.concepts} == {
        (CONCEPT_SEAT, "4157"),
        (CONCEPT_VACANT_SEAT, "4159"),
        (CONCEPT_ALLOCATION, "3313"),
        (CONCEPT_INTL_ORG, "2189"),
    }

    # A domain is also typed skos:Concept in EuroVoc's own data; it must not
    # be double-counted as a thesaurus concept in a mapping-only package.
    concept_iris = {item.concept_iri for item in parsed.concepts}
    assert DOMAIN_POLITICS not in concept_iris
    assert DOMAIN_INTL_RELATIONS not in concept_iris

    preferred = {
        item.value.language_tag: item.value.lexical_form
        for item in parsed.labels
        if item.subject_iri == CONCEPT_SEAT and item.role == "preferred"
    }
    assert preferred == {
        "en": "parliamentary seat",
        "fr": "siège parlementaire",
        "es": "escaño parlamentario",
        "de": "Parlamentssitz",
        "el": "βουλευτική έδρα",
    }
    alternate_languages = {
        item.value.language_tag
        for item in parsed.labels
        if item.subject_iri == CONCEPT_INTL_ORG and item.role == "alternate"
    }
    assert alternate_languages == {"en", "fr", "de", "es", "el"}


def test_parser_keeps_hierarchy_scheme_membership_and_top_concept_facts_as_flat_relations() -> None:
    parsed = parse_eurovoc_turtle(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL, accepted_use="mappingReference")

    assert HIERARCHY_PREDICATE_IRIS == (
        "http://www.w3.org/2004/02/skos/core#broader",
        "http://www.w3.org/2004/02/skos/core#narrower",
    )
    assert {
        (item.predicate_iri, item.object_iri) for item in parsed.hierarchy_relations if item.subject_iri == CONCEPT_SEAT
    } == {
        ("http://www.w3.org/2004/02/skos/core#narrower", CONCEPT_ALLOCATION),
        ("http://www.w3.org/2004/02/skos/core#narrower", CONCEPT_VACANT_SEAT),
    }
    assert {
        (item.predicate_iri, item.object_iri)
        for item in parsed.hierarchy_relations
        if item.subject_iri == CONCEPT_ALLOCATION
    } == {("http://www.w3.org/2004/02/skos/core#broader", CONCEPT_SEAT)} | {
        (item.predicate_iri, item.object_iri)
        for item in parsed.hierarchy_relations
        if item.subject_iri == CONCEPT_ALLOCATION and item.predicate_iri.endswith("narrower")
    }

    memberships = {(item.predicate_iri, item.object_iri) for item in parsed.scheme_memberships if item.subject_iri == CONCEPT_SEAT}
    assert memberships == {
        (SCHEME_MEMBERSHIP_PREDICATE_IRI, THESAURUS_IRI),
        (SCHEME_MEMBERSHIP_PREDICATE_IRI, GROUP_ELECTORAL),
        (SCHEME_MEMBERSHIP_PREDICATE_IRI, "http://eurovoc.europa.eu"),
    }
    top_concept_of = {
        (item.predicate_iri, item.object_iri) for item in parsed.top_concept_of_relations if item.subject_iri == CONCEPT_SEAT
    }
    assert top_concept_of == {
        (TOP_CONCEPT_OF_PREDICATE_IRI, THESAURUS_IRI),
        (TOP_CONCEPT_OF_PREDICATE_IRI, GROUP_ELECTORAL),
    }
    has_top_concept = {
        (item.subject_iri, item.object_iri)
        for item in parsed.has_top_concept_relations
        if item.predicate_iri == HAS_TOP_CONCEPT_PREDICATE_IRI
    }
    assert (GROUP_ELECTORAL, CONCEPT_SEAT) in has_top_concept
    assert (DOMAINS_SCHEME_IRI, DOMAIN_POLITICS) in has_top_concept

    status = {(item.subject_iri, item.object_iri) for item in parsed.status_assertions if item.predicate_iri == STATUS_PREDICATE_IRI}
    assert (CONCEPT_SEAT, CURRENT_STATUS_IRI) in status
    assert (DOMAIN_POLITICS, CURRENT_STATUS_IRI) in status


def test_parser_refuses_any_accepted_use_other_than_mapping_reference() -> None:
    with pytest.raises(EuroVocThesaurusError, match="mappingReference"):
        parse_eurovoc_turtle(
            _fixture_bytes(),
            source_url=FIXTURE_SOURCE_URL,
            accepted_use="governedSubjectScheme",
        )


def test_synthetic_edge_input_round_trips_domain_group_and_hidden_label() -> None:
    parsed = parse_eurovoc_turtle(
        SYNTHETIC_EDGE_TURTLE,
        source_url="https://example.test/synthetic-eurovoc-edge.ttl",
        accepted_use="mappingReference",
    )

    assert parsed.thesaurus_iri == "urn:example:thesaurus"
    assert parsed.thesaurus_version == "9.9"
    assert parsed.domains == (
        parsed.domains[0].__class__(domain_iri="urn:example:domain-01", code="01"),
    )
    assert parsed.domain_groups[0].domain_iri == "urn:example:domain-01"
    assert parsed.domain_groups[0].code == "0101"
    assert parsed.concepts[0].concept_iri == "urn:example:edge"
    assert parsed.concepts[0].notation == "900001"
    assert any(item.role == "hidden" and item.value.lexical_form == "Internal term" for item in parsed.labels)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda text: text.replace('"Edge concept"@en', '"Edge concept"'),
            "language tag",
        ),
        (
            lambda text: text.replace('dcterms:identifier "900001" ;\n', ""),
            "identifier",
        ),
        (
            lambda text: text.replace('dc:identifier "900001" ;', 'dc:identifier "900002" ;'),
            "disagree",
        ),
    ],
)
def test_parser_rejects_lossy_or_ambiguous_concept_features(mutate, message: str) -> None:
    with pytest.raises(EuroVocThesaurusError, match=message):
        parse_eurovoc_turtle(
            mutate(SYNTHETIC_EDGE_TURTLE),
            source_url="https://example.test/synthetic-eurovoc-edge.ttl",
            accepted_use="mappingReference",
        )


def test_parser_refuses_a_domain_group_whose_code_does_not_match_its_domains_prefix() -> None:
    mutated = SYNTHETIC_EDGE_TURTLE.replace('skos:notation "0101" ;', 'skos:notation "0201" ;').replace(
        'dcterms:identifier "0101" ;', 'dcterms:identifier "0201" ;'
    ).replace('dc:identifier "0101" ;', 'dc:identifier "0201" ;')
    with pytest.raises(EuroVocThesaurusError, match="prefix"):
        parse_eurovoc_turtle(
            mutated,
            source_url="https://example.test/synthetic-eurovoc-edge.ttl",
            accepted_use="mappingReference",
        )


def test_parser_rejects_a_blank_node_in_place_of_a_required_iri() -> None:
    mutated = SYNTHETIC_EDGE_TURTLE.replace("<urn:example:domain-01>", "[]", 1)
    with pytest.raises(EuroVocThesaurusError, match="must be an IRI"):
        parse_eurovoc_turtle(
            mutated,
            source_url="https://example.test/synthetic-eurovoc-edge.ttl",
            accepted_use="mappingReference",
        )


def test_parser_enforces_optional_distribution_digest_and_size_pins() -> None:
    source = _fixture_bytes()
    digest = "sha256:" + hashlib.sha256(source).hexdigest()
    parsed = parse_eurovoc_turtle(
        source,
        source_url=FIXTURE_SOURCE_URL,
        accepted_use="mappingReference",
        expected_sha256=digest,
        expected_byte_length=len(source),
    )
    assert parsed.source_sha256 == digest

    with pytest.raises(EuroVocThesaurusError, match="digest mismatch"):
        parse_eurovoc_turtle(
            source,
            source_url=FIXTURE_SOURCE_URL,
            accepted_use="mappingReference",
            expected_sha256="sha256:" + "0" * 64,
        )
    with pytest.raises(EuroVocThesaurusError, match="byte length mismatch"):
        parse_eurovoc_turtle(
            source,
            source_url=FIXTURE_SOURCE_URL,
            accepted_use="mappingReference",
            expected_byte_length=len(source) + 1,
        )


def test_parse_eurovoc_file_reads_from_disk(tmp_path: Path) -> None:
    source = _fixture_bytes()
    path = tmp_path / "eurovoc.ttl"
    path.write_bytes(source)
    parsed = parse_eurovoc_file(path, source_url=FIXTURE_SOURCE_URL, accepted_use="mappingReference")
    assert parsed.source_bytes == len(source)


def test_pinned_real_sample_matches_the_captured_snapshot() -> None:
    source = _fixture_bytes()
    assert len(source) == EUROVOC_SAMPLE_2026_08_03.expected_byte_length
    assert "sha256:" + hashlib.sha256(source).hexdigest() == EUROVOC_SAMPLE_2026_08_03.expected_sha256

    parsed = parse_eurovoc_turtle(
        source,
        source_url=EUROVOC_SAMPLE_2026_08_03.source_url,
        accepted_use="mappingReference",
        expected_sha256=EUROVOC_SAMPLE_2026_08_03.expected_sha256,
        expected_byte_length=EUROVOC_SAMPLE_2026_08_03.expected_byte_length,
    )
    assert {item.code for item in parsed.domains} == {"04", "08"}
    assert {item.code for item in parsed.domain_groups} == {"0416", "0806"}
    assert {item.notation for item in parsed.concepts} == {"4157", "4159", "3313", "2189"}


def test_verified_local_acquisition_parses_with_the_same_source_pin(tmp_path: Path) -> None:
    source = _fixture_bytes()
    source_path = tmp_path / "eurovoc-mini.ttl"
    source_path.write_bytes(source)
    sample_source = EuroVocSampleSource(
        sample_id="fixture",
        source_url=FIXTURE_SOURCE_URL,
        expected_sha256="sha256:" + hashlib.sha256(source).hexdigest(),
        expected_byte_length=len(source),
        filename="eurovoc-mini.ttl",
    )
    acquired = acquire_eurovoc_sample(
        sample_source,
        tmp_path / "store",
        source_path=source_path,
    )
    assert isinstance(acquired, AcquiredEuroVocSample)
    assert acquired.acquisition_mode == "local"

    parsed = parse_acquired_eurovoc_sample(acquired, accepted_use="mappingReference")
    assert parsed.source_sha256 == acquired.sha256
    assert parsed.source_bytes == acquired.byte_length
    assert parsed.thesaurus_iri == THESAURUS_IRI

    cached = acquire_eurovoc_sample(sample_source, tmp_path / "store")
    assert cached.cache_hit is True
    assert cached.acquisition_mode == "cache"


def test_acquisition_refuses_the_network_unless_explicitly_allowed(tmp_path: Path) -> None:
    with pytest.raises(EuroVocAcquisitionError, match="allow_network"):
        acquire_eurovoc_sample(EUROVOC_SAMPLE_2026_08_03, tmp_path / "store")


def test_acquisition_source_rejects_malformed_pins() -> None:
    with pytest.raises(EuroVocAcquisitionError):
        EuroVocSampleSource(
            sample_id="bad",
            source_url="not-a-url",
            expected_sha256="sha256:" + "0" * 64,
            expected_byte_length=10,
            filename="x.ttl",
        )
    with pytest.raises(EuroVocAcquisitionError):
        EuroVocSampleSource(
            sample_id="bad",
            source_url="https://example.test/x.ttl",
            expected_sha256="not-a-digest",
            expected_byte_length=10,
            filename="x.ttl",
        )
    with pytest.raises(EuroVocAcquisitionError):
        EuroVocSampleSource(
            sample_id="bad",
            source_url="https://example.test/x.ttl",
            expected_sha256="sha256:" + "0" * 64,
            expected_byte_length=0,
            filename="x.ttl",
        )
