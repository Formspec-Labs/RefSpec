"""EuroVoc pinned SKOS Core release reader tests."""

from __future__ import annotations

import hashlib
import io
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from rdflib import Graph

from refspec.registry.eurovoc_thesaurus import (
    DEFINITION_PREDICATE_IRI,
    EUROVOC_4_24_METADATA,
    EUROVOC_RELEASE_4_24,
    HAS_TOP_CONCEPT_PREDICATE_IRI,
    HIERARCHY_PREDICATE_IRIS,
    SCHEME_MEMBERSHIP_PREDICATE_IRI,
    SCOPE_NOTE_PREDICATE_IRI,
    STATUS_PREDICATE_IRI,
    TOP_CONCEPT_OF_PREDICATE_IRI,
    AcquiredEuroVocRelease,
    EuroVocAcquisitionError,
    EuroVocMetadataSource,
    EuroVocReleaseSource,
    EuroVocThesaurusError,
    acquire_eurovoc_release,
    parse_acquired_eurovoc_release,
    parse_eurovoc_file,
    parse_eurovoc_rdf_xml,
    parse_eurovoc_turtle,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "eurovoc_thesaurus" / "eurovoc-domains-sample-2026-08-03.ttl"
FIXTURE_SOURCE_URL = "https://example.test/eurovoc-domains-sample.ttl"

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
    skos:definition "An English definition."@en-GB, "Une définition."@fr ;
    skos:scopeNote "An English scope note."@en-US ;
    euvoc:status <http://publications.europa.eu/resource/authority/concept-status/CURRENT> .
"""


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def _synthetic_rdf_xml() -> bytes:
    graph = Graph()
    graph.parse(
        data=SYNTHETIC_EDGE_TURTLE + "\n<urn:example:edge> skos:broader <urn:example:parent> .\n",
        format="turtle",
    )
    return graph.serialize(format="xml", encoding="utf-8")


def _zip_payload(member: bytes, *, member_name: str = "eurovoc.rdf", extra_member: bool = False) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, member)
        if extra_member:
            archive.writestr("unexpected.txt", b"unexpected")
    return output.getvalue()


def _release_for_archive(
    archive: bytes,
    member: bytes,
    *,
    member_name: str = "eurovoc.rdf",
    metadata_source: EuroVocMetadataSource | None = None,
) -> EuroVocReleaseSource:
    return EuroVocReleaseSource(
        release_id="fixture-9.9",
        version="9.9",
        issued="2026-07-08",
        concept_scheme_iri="urn:example:thesaurus",
        source_url="https://example.test/eurovoc.zip",
        landing_page_url="https://example.test/eurovoc",
        expected_sha256="sha256:" + hashlib.sha256(archive).hexdigest(),
        expected_byte_length=len(archive),
        filename="eurovoc.zip",
        member_filename=member_name,
        expected_member_sha256="sha256:" + hashlib.sha256(member).hexdigest(),
        expected_member_byte_length=len(member),
        metadata_source=metadata_source,
    )


def test_parser_separates_domains_domain_groups_and_concepts_with_source_identifiers() -> None:
    source = _fixture_bytes()
    parsed = parse_eurovoc_turtle(source, source_url=FIXTURE_SOURCE_URL)

    assert parsed.source_url == FIXTURE_SOURCE_URL
    assert parsed.source_bytes == len(source)
    assert parsed.source_sha256 == "sha256:" + hashlib.sha256(source).hexdigest()
    assert parsed.triple_count > 0
    assert parsed.source_format == "turtle"
    assert parsed == parse_eurovoc_turtle(source, source_url=FIXTURE_SOURCE_URL)

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
    # be double-counted as an ordinary thesaurus concept.
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
    parsed = parse_eurovoc_turtle(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

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


def test_synthetic_edge_input_round_trips_domain_group_and_hidden_label() -> None:
    parsed = parse_eurovoc_turtle(
        SYNTHETIC_EDGE_TURTLE,
        source_url="https://example.test/synthetic-eurovoc-edge.ttl",
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
    assert {
        (item.property_iri, item.value.language_tag, item.value.lexical_form)
        for item in parsed.annotations
        if item.subject_iri == "urn:example:edge"
    } == {
        (DEFINITION_PREDICATE_IRI, "en-GB", "An English definition."),
        (DEFINITION_PREDICATE_IRI, "fr", "Une définition."),
        (SCOPE_NOTE_PREDICATE_IRI, "en-US", "An English scope note."),
    }


def test_skos_core_domain_membership_separates_domains_from_thesaurus_concepts() -> None:
    core_shape = SYNTHETIC_EDGE_TURTLE.replace(
        "a schema:Domain, skos:Concept ;",
        "a skos:Concept ;",
    ).replace("urn:example:domains", "http://eurovoc.europa.eu/domains")
    parsed = parse_eurovoc_turtle(
        core_shape,
        source_url="https://example.test/eurovoc-core.ttl",
    )
    assert [item.domain_iri for item in parsed.domains] == ["urn:example:domain-01"]
    assert {item.concept_iri for item in parsed.concepts} == {"urn:example:edge"}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda text: text.replace('"Edge concept"@en', '"Edge concept"'),
            "language tag",
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
        )


def test_parser_refuses_a_domain_group_whose_code_does_not_match_its_domains_prefix() -> None:
    mutated = SYNTHETIC_EDGE_TURTLE.replace('skos:notation "0101" ;', 'skos:notation "0201" ;').replace(
        'dcterms:identifier "0101" ;', 'dcterms:identifier "0201" ;'
    ).replace('dc:identifier "0101" ;', 'dc:identifier "0201" ;')
    with pytest.raises(EuroVocThesaurusError, match="prefix"):
        parse_eurovoc_turtle(
            mutated,
            source_url="https://example.test/synthetic-eurovoc-edge.ttl",
        )


def test_parser_rejects_a_blank_node_in_place_of_a_required_iri() -> None:
    mutated = SYNTHETIC_EDGE_TURTLE.replace("<urn:example:domain-01>", "[]", 1)
    with pytest.raises(EuroVocThesaurusError, match="must be an IRI"):
        parse_eurovoc_turtle(
            mutated,
            source_url="https://example.test/synthetic-eurovoc-edge.ttl",
        )


def test_parser_rejects_an_iri_valued_definition() -> None:
    mutated = SYNTHETIC_EDGE_TURTLE.replace(
        'skos:definition "An English definition."@en-GB, "Une définition."@fr ;',
        "skos:definition <urn:example:definition> ;",
    )
    with pytest.raises(EuroVocThesaurusError, match="must be an RDF literal"):
        parse_eurovoc_turtle(
            mutated,
            source_url="https://example.test/synthetic-eurovoc-edge.ttl",
        )


def test_parser_enforces_optional_distribution_digest_and_size_pins() -> None:
    source = _fixture_bytes()
    digest = "sha256:" + hashlib.sha256(source).hexdigest()
    parsed = parse_eurovoc_turtle(
        source,
        source_url=FIXTURE_SOURCE_URL,
        expected_sha256=digest,
        expected_byte_length=len(source),
    )
    assert parsed.source_sha256 == digest

    with pytest.raises(EuroVocThesaurusError, match="digest mismatch"):
        parse_eurovoc_turtle(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_sha256="sha256:" + "0" * 64,
        )
    with pytest.raises(EuroVocThesaurusError, match="byte length mismatch"):
        parse_eurovoc_turtle(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_byte_length=len(source) + 1,
        )


def test_parse_eurovoc_file_reads_from_disk(tmp_path: Path) -> None:
    source = _fixture_bytes()
    path = tmp_path / "eurovoc.ttl"
    path.write_bytes(source)
    parsed = parse_eurovoc_file(path, source_url=FIXTURE_SOURCE_URL)
    assert parsed.source_bytes == len(source)


def test_skos_core_notation_is_a_complete_publisher_identifier() -> None:
    source = SYNTHETIC_EDGE_TURTLE.replace('dc:identifier "900001" ;\n', "").replace(
        'dcterms:identifier "900001" ;\n', ""
    )
    parsed = parse_eurovoc_turtle(
        source,
        source_url="https://example.test/eurovoc-core.ttl",
    )
    assert parsed.concepts[0].notation == "900001"


def test_rdf_xml_reader_preserves_roles_schemes_and_direct_hierarchy() -> None:
    source = _synthetic_rdf_xml()
    parsed = parse_eurovoc_rdf_xml(
        source,
        source_url="https://example.test/eurovoc.rdf",
        release_version="9.9",
        expected_thesaurus_iri="urn:example:thesaurus",
    )
    assert parsed.source_format == "xml"
    assert parsed.thesaurus_version == "9.9"
    assert {item.scheme_iri for item in parsed.concept_schemes} == {
        "urn:example:domains",
        "urn:example:group-0101",
        "urn:example:thesaurus",
    }
    assert any(item.role == "hidden" and item.value.lexical_form == "Internal term" for item in parsed.labels)
    assert [(item.predicate_iri, item.object_iri) for item in parsed.hierarchy_relations] == [
        ("http://www.w3.org/2004/02/skos/core#broader", "urn:example:parent")
    ]


def test_official_4_24_release_and_metadata_are_fully_pinned() -> None:
    release = EUROVOC_RELEASE_4_24
    assert release.version == "4.24"
    assert release.issued == "2026-07-08"
    assert release.expected_sha256 == "sha256:91bdb24e833ba431707f3980a19f475434ea8dcddb2b4d5e32e79e9fc1a0ca2f"
    assert release.expected_byte_length == 8_567_290
    assert release.expected_member_sha256 == (
        "sha256:6c362f79ad03e325ba1b4818f1ca3a847bb6167c2a8f7167e2e4df91305b6620"
    )
    assert release.expected_member_byte_length == 60_691_531
    assert "20260708-0%2Fzip%2Fskos_core" in release.source_url
    assert release.metadata_source is EUROVOC_4_24_METADATA
    assert EUROVOC_4_24_METADATA.expected_sha256 == (
        "sha256:2c58402422f8588aada476f3516051e7fc980182130557a0d8c67497ffd8731d"
    )
    assert EUROVOC_4_24_METADATA.expected_byte_length == 36_011


def test_verified_local_zip_acquisition_parses_and_caches_member(tmp_path: Path) -> None:
    member = _synthetic_rdf_xml()
    archive = _zip_payload(member)
    archive_path = tmp_path / "eurovoc.zip"
    archive_path.write_bytes(archive)
    release = _release_for_archive(archive, member)

    acquired = acquire_eurovoc_release(
        release,
        tmp_path / "store",
        source_path=archive_path,
    )
    assert isinstance(acquired, AcquiredEuroVocRelease)
    assert acquired.acquisition_mode == "local"
    assert acquired.archive_sha256 == release.expected_sha256
    assert acquired.sha256 == release.expected_member_sha256

    parsed = parse_acquired_eurovoc_release(acquired)
    assert parsed.source_sha256 == acquired.sha256
    assert parsed.source_bytes == acquired.byte_length
    assert parsed.thesaurus_iri == "urn:example:thesaurus"

    cached = acquire_eurovoc_release(release, tmp_path / "store")
    assert cached.cache_hit is True
    assert cached.acquisition_mode == "cache"


def test_optional_metadata_is_independently_pinned(tmp_path: Path) -> None:
    member = _synthetic_rdf_xml()
    archive = _zip_payload(member)
    metadata = b"@prefix dcterms: <http://purl.org/dc/terms/> .\n"
    metadata_source = EuroVocMetadataSource(
        source_url="https://example.test/eurovoc-metadata.ttl",
        expected_sha256="sha256:" + hashlib.sha256(metadata).hexdigest(),
        expected_byte_length=len(metadata),
        filename="eurovoc-metadata.ttl",
    )
    release = _release_for_archive(archive, member, metadata_source=metadata_source)
    archive_path = tmp_path / "eurovoc.zip"
    metadata_path = tmp_path / "metadata.ttl"
    archive_path.write_bytes(archive)
    metadata_path.write_bytes(metadata)

    acquired = acquire_eurovoc_release(
        release,
        tmp_path / "store",
        source_path=archive_path,
        metadata_path=metadata_path,
    )
    assert acquired.metadata is not None
    assert acquired.metadata.sha256 == metadata_source.expected_sha256

    metadata_path.write_bytes(metadata + b"# changed\n")
    with pytest.raises(EuroVocAcquisitionError, match="expected byte length"):
        acquire_eurovoc_release(
            release,
            tmp_path / "other-store",
            source_path=archive_path,
            metadata_path=metadata_path,
        )


def test_zip_container_member_count_name_size_and_digest_are_closed() -> None:
    member = _synthetic_rdf_xml()

    extra_archive = _zip_payload(member, extra_member=True)
    with pytest.raises(EuroVocAcquisitionError, match="exactly one member"):
        _acquire_fixture_archive(extra_archive, _release_for_archive(extra_archive, member))

    wrong_name_archive = _zip_payload(member, member_name="wrong.rdf")
    with pytest.raises(EuroVocAcquisitionError, match="archive member"):
        _acquire_fixture_archive(wrong_name_archive, _release_for_archive(wrong_name_archive, member))

    archive = _zip_payload(member)
    wrong_size = replace(_release_for_archive(archive, member), expected_member_byte_length=len(member) + 1)
    with pytest.raises(EuroVocAcquisitionError, match="member byte length mismatch"):
        _acquire_fixture_archive(archive, wrong_size)

    wrong_digest = replace(
        _release_for_archive(archive, member),
        expected_member_sha256="sha256:" + "0" * 64,
    )
    with pytest.raises(EuroVocAcquisitionError, match="member digest mismatch"):
        _acquire_fixture_archive(archive, wrong_digest)


def _acquire_fixture_archive(archive: bytes, release: EuroVocReleaseSource) -> AcquiredEuroVocRelease:
    with tempfile.TemporaryDirectory() as temporary_dir:
        root = Path(temporary_dir)
        source_path = root / "source.zip"
        source_path.write_bytes(archive)
        return acquire_eurovoc_release(release, root / "store", source_path=source_path)


def test_acquisition_refuses_the_network_unless_explicitly_allowed(tmp_path: Path) -> None:
    with pytest.raises(EuroVocAcquisitionError, match="allow_network"):
        acquire_eurovoc_release(EUROVOC_RELEASE_4_24, tmp_path / "store")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_url", "not-a-url"),
        ("expected_sha256", "not-a-digest"),
        ("expected_byte_length", 0),
        ("member_filename", "nested/eurovoc.rdf"),
        ("issued", "2026/07/08"),
    ],
)
def test_acquisition_source_rejects_malformed_pins(field: str, value: object) -> None:
    with pytest.raises(EuroVocAcquisitionError):
        replace(EUROVOC_RELEASE_4_24, **{field: value})
