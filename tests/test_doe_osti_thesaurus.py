"""DOE OSTI Semantic Thesaurus (2020 RDF/SKOS export) parser and capture tests.

The primary fixture is a real, byte-faithful excerpt of the 2020-09-30
distribution (https://www.osti.gov/servlets/purl/1668761, OSTI identifier
1668761), captured 2026-08-03. It keeps whole ``<skos:Concept>`` elements
copied verbatim from the real 18,087,998-byte file -- including a genuine
dangling ``skos:hasTopConcept`` reference the real distribution itself
contains -- rather than hand-authoring plausible-looking RDF. No test opens
a network connection: every payload is a fixture file already checked into
the repo or a small synthetic string built for one edge case.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from refspec.registry.doe_osti_thesaurus import (
    BROADER_PREDICATE_IRI,
    DOE_OSTI_CONCEPT_SCHEME_IRI,
    DOE_OSTI_LANDING_PAGE_URL,
    DOE_OSTI_PUBLISHER,
    DOE_OSTI_STATED_PUBLICATION_DATE,
    DOE_OSTI_THESAURUS_CATALOG_ROLE,
    DOE_OSTI_THESAURUS_V1_2020,
    DOE_OSTI_THESAURUS_VERIFICATION_GAPS,
    NARROWER_PREDICATE_IRI,
    RELATED_PREDICATE_IRI,
    DoeOstiFetchedResource,
    DoeOstiImportCounts,
    DoeOstiThesaurusError,
    acquire_doe_osti_thesaurus_export,
    doe_osti_thesaurus_capture_digest,
    doe_osti_thesaurus_capture_manifest,
    parse_doe_osti_thesaurus_file,
    parse_doe_osti_thesaurus_rdfxml,
)


def test_real_full_distribution_shape_count_and_boundary_samples() -> None:
    source_path_text = os.environ.get("REFSPEC_DOE_OSTI_THESAURUS_PATH")
    if source_path_text is None:
        pytest.skip("real DOE OSTI distribution is not configured")
    release = DOE_OSTI_THESAURUS_V1_2020
    thesaurus = parse_doe_osti_thesaurus_file(
        Path(source_path_text),
        source_url=release.source_url,
        expected_sha256=release.expected_sha256,
        expected_byte_length=release.expected_byte_length,
    )

    assert thesaurus.source_bytes == 18_087_998
    assert thesaurus.triple_count == 247_184
    assert len(thesaurus.concepts) == 23_626
    assert thesaurus.concepts[0].concept_iri == "https://www.osti.gov/thesaurus/10001"
    assert thesaurus.concepts[-1].concept_iri == "https://www.osti.gov/thesaurus/9999"

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "doe_osti_thesaurus" / "osti-semantic-thesaurus-2020-mini.rdf"
FIXTURE_SOURCE_URL = "https://example.test/osti-semantic-thesaurus-2020-mini.rdf"

CASTLE_PROJECT = "https://www.osti.gov/thesaurus/3792"
CASTOR = "https://www.osti.gov/thesaurus/3793"
SOLAR_FLUX = "https://www.osti.gov/thesaurus/22777"
METROLOGY = "https://www.osti.gov/thesaurus/76446"
INCLINOMETERS = "https://www.osti.gov/thesaurus/76445"
SEVERE_ACCIDENTS = "https://www.osti.gov/thesaurus/76395"
DANGLING_TOP_CONCEPT = "https://www.osti.gov/thesaurus/29668"

SYNTHETIC_MINIMAL_TURTLE = """\
<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF
  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  xmlns:skos="http://www.w3.org/2004/02/skos/core#">
  <skos:ConceptScheme rdf:about="https://www.osti.gov/thesaurus">
    <skos:hasTopConcept rdf:resource="https://www.osti.gov/thesaurus/1"/>
    <skos:prefLabel xml:lang="en">OSTI Thesaurus</skos:prefLabel>
  </skos:ConceptScheme>
  <skos:Concept rdf:about="https://www.osti.gov/thesaurus/1">
    <skos:inScheme rdf:resource="https://www.osti.gov/thesaurus"/>
    <skos:prefLabel xml:lang="en">Edge Concept</skos:prefLabel>
    <skos:topConceptOf rdf:resource="https://www.osti.gov/thesaurus"/>
  </skos:Concept>
</rdf:RDF>
"""


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def test_parser_preserves_the_real_2020_export_excerpt_verbatim() -> None:
    source = _fixture_bytes()
    thesaurus = parse_doe_osti_thesaurus_rdfxml(source, source_url=FIXTURE_SOURCE_URL)

    assert thesaurus.source_url == FIXTURE_SOURCE_URL
    assert thesaurus.source_bytes == len(source)
    assert thesaurus.source_sha256 == "sha256:" + hashlib.sha256(source).hexdigest()
    assert thesaurus.concept_scheme_iri == DOE_OSTI_CONCEPT_SCHEME_IRI
    assert thesaurus == parse_doe_osti_thesaurus_rdfxml(source, source_url=FIXTURE_SOURCE_URL)

    assert thesaurus.counts == DoeOstiImportCounts(
        source_bytes=len(source),
        triples=89,
        source_iris=55,
        concepts=9,
        concept_schemes=1,
        preferred_labels=10,
        definitions=1,
        scope_notes=1,
        broader_relations=9,
        narrower_relations=10,
        related_relations=20,
        has_top_concept_relations=10,
        top_concept_of_relations=9,
        in_scheme_relations=9,
        unresolved_top_concept_iris=1,
    )

    castle_labels = {item.value.lexical_form for item in thesaurus.labels if item.subject_iri == CASTLE_PROJECT}
    assert castle_labels == {"Castle Project"}
    castle_related = {
        item.object_iri
        for item in thesaurus.semantic_relations
        if item.subject_iri == CASTLE_PROJECT and item.predicate_iri == RELATED_PREDICATE_IRI
    }
    assert castle_related == {
        "https://www.osti.gov/thesaurus/16903",
        "https://www.osti.gov/thesaurus/24105",
        "https://www.osti.gov/thesaurus/24971",
        "https://www.osti.gov/thesaurus/1708",
        "https://www.osti.gov/thesaurus/2463",
    }

    solar_flux_narrower = {
        item.object_iri
        for item in thesaurus.semantic_relations
        if item.subject_iri == SOLAR_FLUX and item.predicate_iri == NARROWER_PREDICATE_IRI
    }
    assert len(solar_flux_narrower) == 6

    definition = next(item for item in thesaurus.notes if item.subject_iri == INCLINOMETERS)
    assert definition.value.lexical_form.startswith("Instruments for measuring angles")
    assert definition.value.language_tag == "en"
    assert definition.value.datatype_iri is None

    scope_note = next(item for item in thesaurus.notes if item.subject_iri == SEVERE_ACCIDENTS)
    assert "REACTOR ACCIDENTS" in scope_note.value.lexical_form

    # The real distribution asserts skos:hasTopConcept for a concept IRI it
    # never itself defines with skos:Concept; this genuine gap is preserved
    # and surfaced explicitly rather than silently dropped or repaired.
    assert thesaurus.unresolved_top_concept_iris == (DANGLING_TOP_CONCEPT,)


def test_parser_preserves_concept_scheme_and_hierarchy_structure() -> None:
    thesaurus = parse_doe_osti_thesaurus_rdfxml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)

    assert len(thesaurus.concept_schemes) == 1
    scheme = thesaurus.concept_schemes[0]
    assert scheme.scheme_iri == DOE_OSTI_CONCEPT_SCHEME_IRI
    assert DANGLING_TOP_CONCEPT in scheme.top_concept_iris
    assert METROLOGY in scheme.top_concept_iris

    scheme_labels = {item.value.lexical_form for item in thesaurus.labels if item.subject_iri == scheme.scheme_iri}
    assert scheme_labels == {"OSTI Thesaurus"}

    castor = next(item for item in thesaurus.concepts if item.concept_iri == CASTOR)
    assert castor.scheme_iris == (DOE_OSTI_CONCEPT_SCHEME_IRI,)
    assert castor.top_concept_of_iris == (DOE_OSTI_CONCEPT_SCHEME_IRI,)

    metrology_broader_children = {
        item.subject_iri
        for item in thesaurus.semantic_relations
        if item.object_iri == METROLOGY and item.predicate_iri == BROADER_PREDICATE_IRI
    }
    assert metrology_broader_children == {
        "https://www.osti.gov/thesaurus/76447",
        "https://www.osti.gov/thesaurus/76448",
    }


def test_parser_rejects_a_relative_source_url() -> None:
    with pytest.raises(DoeOstiThesaurusError, match="absolute IRI"):
        parse_doe_osti_thesaurus_rdfxml(SYNTHETIC_MINIMAL_TURTLE, source_url="not-a-url")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            SYNTHETIC_MINIMAL_TURTLE.replace('xml:lang="en">Edge Concept', ">Edge Concept"),
            "untagged",
        ),
        (
            SYNTHETIC_MINIMAL_TURTLE.replace(
                '<skos:prefLabel xml:lang="en">Edge Concept</skos:prefLabel>',
                (
                    '<skos:prefLabel xml:lang="en">Edge Concept</skos:prefLabel>'
                    '<skos:prefLabel xml:lang="en">Renamed Edge Concept</skos:prefLabel>'
                ),
            ),
            "more than one",
        ),
        (
            SYNTHETIC_MINIMAL_TURTLE.replace(
                '<skos:topConceptOf rdf:resource="https://www.osti.gov/thesaurus"/>',
                (
                    '<skos:topConceptOf rdf:resource="https://www.osti.gov/thesaurus"/>'
                    '<skos:altLabel xml:lang="en">Edge Alt Label</skos:altLabel>'
                ),
            ),
            "unsupported predicate",
        ),
        (
            SYNTHETIC_MINIMAL_TURTLE.replace(
                '<skos:inScheme rdf:resource="https://www.osti.gov/thesaurus"/>',
                (
                    '<skos:inScheme rdf:resource="https://www.osti.gov/thesaurus"/>'
                    '<rdf:type rdf:resource="http://www.w3.org/2004/02/skos/core#Collection"/>'
                ),
            ),
            "unsupported rdf:type",
        ),
        (
            SYNTHETIC_MINIMAL_TURTLE.replace(
                "</skos:ConceptScheme>",
                '</skos:ConceptScheme>\n  <skos:ConceptScheme rdf:about="https://www.osti.gov/thesaurus/2"/>',
            ),
            "exactly one",
        ),
        (
            "not xml at all",
            "could not parse",
        ),
    ],
)
def test_parser_rejects_lossy_or_ambiguous_skos_shapes(source: str, message: str) -> None:
    with pytest.raises(DoeOstiThesaurusError, match=message):
        parse_doe_osti_thesaurus_rdfxml(source, source_url=FIXTURE_SOURCE_URL)


def test_parser_rejects_a_blank_node_relation_object() -> None:
    source = SYNTHETIC_MINIMAL_TURTLE.replace(
        "</skos:Concept>",
        "  <skos:broader><rdf:Description/></skos:broader>\n  </skos:Concept>",
    )
    with pytest.raises(DoeOstiThesaurusError, match="must be an IRI"):
        parse_doe_osti_thesaurus_rdfxml(source, source_url=FIXTURE_SOURCE_URL)


def test_parser_enforces_optional_distribution_digest_and_size_pins() -> None:
    source = _fixture_bytes()
    digest = "sha256:" + hashlib.sha256(source).hexdigest()
    parsed = parse_doe_osti_thesaurus_rdfxml(
        source,
        source_url=FIXTURE_SOURCE_URL,
        expected_sha256=digest,
        expected_byte_length=len(source),
    )
    assert parsed.source_sha256 == digest

    with pytest.raises(DoeOstiThesaurusError, match="digest mismatch"):
        parse_doe_osti_thesaurus_rdfxml(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_sha256="sha256:" + "0" * 64,
        )
    with pytest.raises(DoeOstiThesaurusError, match="byte length mismatch"):
        parse_doe_osti_thesaurus_rdfxml(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_byte_length=len(source) + 1,
        )
    with pytest.raises(DoeOstiThesaurusError, match="sha256:<64 hex>"):
        parse_doe_osti_thesaurus_rdfxml(
            source,
            source_url=FIXTURE_SOURCE_URL,
            expected_sha256="not-a-digest",
        )


def test_parser_rejects_a_concept_scheme_iri_mismatch() -> None:
    with pytest.raises(DoeOstiThesaurusError, match="concept scheme"):
        parse_doe_osti_thesaurus_rdfxml(
            _fixture_bytes(),
            source_url=FIXTURE_SOURCE_URL,
            expected_concept_scheme_iri="https://www.osti.gov/thesaurus/not-the-real-one",
        )


def test_parse_doe_osti_thesaurus_file_reads_a_local_pinned_fixture(tmp_path: Path) -> None:
    source = _fixture_bytes()
    local_path = tmp_path / "capture.rdf"
    local_path.write_bytes(source)

    thesaurus = parse_doe_osti_thesaurus_file(
        local_path,
        source_url=FIXTURE_SOURCE_URL,
        expected_sha256="sha256:" + hashlib.sha256(source).hexdigest(),
        expected_byte_length=len(source),
    )
    assert thesaurus.source_bytes == len(source)

    with pytest.raises(DoeOstiThesaurusError, match="not a regular file"):
        parse_doe_osti_thesaurus_file(tmp_path / "missing.rdf", source_url=FIXTURE_SOURCE_URL)


def test_acquire_export_requires_an_explicit_transport() -> None:
    with pytest.raises(DoeOstiThesaurusError, match="requires fetch or allow_direct_network=True"):
        acquire_doe_osti_thesaurus_export("https://example.test/osti-thesaurus-edge.rdf")


def test_acquire_export_uses_an_injected_fetcher_and_matches_direct_parsing() -> None:
    body = _fixture_bytes()
    url = "https://example.test/osti-thesaurus-injected.rdf"

    def fetch(requested_url: str, *, timeout_seconds: float, max_bytes: int) -> DoeOstiFetchedResource:
        assert requested_url == url
        assert timeout_seconds > 0
        assert max_bytes > 0
        return DoeOstiFetchedResource(
            requested_url=requested_url,
            resolved_url=requested_url,
            status_code=200,
            content_type="application/rdf+xml",
            body=body,
        )

    acquired = acquire_doe_osti_thesaurus_export(url, fetch=fetch)
    direct = parse_doe_osti_thesaurus_rdfxml(body, source_url=url)
    assert acquired == direct


def test_acquire_export_rejects_a_non_200_response() -> None:
    def fetch(requested_url: str, *, timeout_seconds: float, max_bytes: int) -> DoeOstiFetchedResource:
        return DoeOstiFetchedResource(
            requested_url=requested_url,
            resolved_url=requested_url,
            status_code=404,
            content_type="text/html",
            body=b"not found",
        )

    with pytest.raises(DoeOstiThesaurusError, match="HTTP 404"):
        acquire_doe_osti_thesaurus_export("https://example.test/osti-thesaurus-edge.rdf", fetch=fetch)


def test_acquire_export_rejects_a_mismatched_requested_url() -> None:
    def fetch(requested_url: str, *, timeout_seconds: float, max_bytes: int) -> DoeOstiFetchedResource:
        return DoeOstiFetchedResource(
            requested_url="https://example.test/wrong.rdf",
            resolved_url="https://example.test/wrong.rdf",
            status_code=200,
            content_type="application/rdf+xml",
            body=b"",
        )

    with pytest.raises(DoeOstiThesaurusError, match="different requested_url"):
        acquire_doe_osti_thesaurus_export("https://example.test/osti-thesaurus-edge.rdf", fetch=fetch)


def test_acquire_export_rejects_a_response_over_max_bytes() -> None:
    def fetch(requested_url: str, *, timeout_seconds: float, max_bytes: int) -> DoeOstiFetchedResource:
        return DoeOstiFetchedResource(
            requested_url=requested_url,
            resolved_url=requested_url,
            status_code=200,
            content_type="application/rdf+xml",
            body=b"x" * (max_bytes + 1),
        )

    with pytest.raises(DoeOstiThesaurusError, match="exceeds max_bytes"):
        acquire_doe_osti_thesaurus_export("https://example.test/osti-thesaurus-edge.rdf", fetch=fetch, max_bytes=16)


def test_pinned_release_matches_the_committed_fixture_shape() -> None:
    # DOE_OSTI_THESAURUS_V1_2020 pins the real, verified 18,087,998-byte
    # distribution this fixture was excerpted from; the fixture itself is
    # deliberately much smaller and is not expected to match those pins.
    assert DOE_OSTI_THESAURUS_V1_2020.concept_scheme_iri == DOE_OSTI_CONCEPT_SCHEME_IRI
    assert DOE_OSTI_THESAURUS_V1_2020.source_url == "https://www.osti.gov/servlets/purl/1668761"
    assert DOE_OSTI_THESAURUS_V1_2020.expected_sha256 == (
        "sha256:aeb9fb2d16caff675c7c9e12e0baff04ac4aded07488944acdf73ed859abe1d5"
    )
    assert DOE_OSTI_THESAURUS_V1_2020.expected_byte_length == 18_087_998
    assert DOE_OSTI_THESAURUS_V1_2020.stated_publication_date == "2020-09-30"


def test_capture_manifest_is_deterministic_and_records_every_verification_gap() -> None:
    thesaurus = parse_doe_osti_thesaurus_rdfxml(_fixture_bytes(), source_url=FIXTURE_SOURCE_URL)
    manifest = doe_osti_thesaurus_capture_manifest(thesaurus, retrieved_at="2026-08-03T00:00:00Z")
    assert manifest == doe_osti_thesaurus_capture_manifest(thesaurus, retrieved_at="2026-08-03T00:00:00Z")

    assert manifest["kind"] == "skosVocabulary"
    assert manifest["publisher"] == DOE_OSTI_PUBLISHER
    assert manifest["landingPageUrl"] == DOE_OSTI_LANDING_PAGE_URL
    assert manifest["statedPublicationDate"] == DOE_OSTI_STATED_PUBLICATION_DATE
    assert manifest["catalogRole"] == DOE_OSTI_THESAURUS_CATALOG_ROLE
    assert "Reject/defer canonical use" in manifest["catalogRole"]
    assert manifest["sourceIsNativeSkosRdf"] is True
    assert manifest["conceptIdentityClaimed"] is True
    assert manifest["candidateUseAuthorized"] is False

    gap_kinds = {gap["kind"] for gap in manifest["verificationGaps"]}
    assert gap_kinds == {gap.kind for gap in DOE_OSTI_THESAURUS_VERIFICATION_GAPS}
    assert {"noNewerReleaseFound", "license", "knownDanglingReference"}.issubset(gap_kinds)

    digest_a = doe_osti_thesaurus_capture_digest(thesaurus, retrieved_at="2026-08-03T00:00:00Z")
    digest_b = doe_osti_thesaurus_capture_digest(thesaurus, retrieved_at="2026-08-03T00:00:00Z")
    assert digest_a == digest_b
    assert digest_a.startswith("sha256:")

    digest_c = doe_osti_thesaurus_capture_digest(thesaurus, retrieved_at="2026-08-04T00:00:00Z")
    assert digest_c != digest_a
