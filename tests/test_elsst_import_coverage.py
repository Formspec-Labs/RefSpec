"""Independent ELSST source, parser, and managed-output coverage gates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import SKOS

from refspec.registry.elsst import (
    HIDDEN_LABEL_PREDICATE_IRI,
    IDENTIFIER_PREDICATE_IRI,
    ElsstVocabulary,
    parse_elsst_turtle,
)
from refspec.registry.elsst_import_coverage import (
    ELSST_COVERAGE_FEATURES,
    ElsstImportCoverageError,
    census_indexed_elsst,
    census_parsed_elsst,
    census_raw_elsst_turtle,
    require_complete_elsst_import_coverage,
    validate_elsst_import_coverage,
)

SOURCE_URL = "https://example.test/elsst-coverage.ttl"
RELEASE_IRI = "urn:test:release:elsst-coverage"
SCHEME_IRI = "urn:test:scheme:elsst-coverage"
CONCEPT_A = "urn:test:concept:a"
CONCEPT_B = "urn:test:concept:b"
CONCEPT_C = "urn:test:concept:c"
EXTERNAL_CONCEPT = "urn:test:external:concept"
_PROV = Namespace("http://www.w3.org/ns/prov#")

SOURCE = b"""\
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix ex: <urn:test:> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:test:scheme:elsst-coverage>
    a skos:ConceptScheme ;
    skos:prefLabel "Coverage topics"@en, "Temas de cobertura"@es ;
    skos:definition "The scheme definition."@en ;
    dcterms:identifier "scheme-coverage"@en ;
    dcterms:isVersionOf <urn:test:stable:scheme> ;
    owl:priorVersion <urn:test:prior:scheme> ;
    skos:hasTopConcept <urn:test:concept:a> .

<urn:test:concept:a>
    a skos:Concept ;
    skos:inScheme <urn:test:scheme:elsst-coverage> ;
    skos:topConceptOf <urn:test:scheme:elsst-coverage> ;
    skos:prefLabel "Alpha"@en, "\xce\x86\xce\xbb\xcf\x86\xce\xb1"@el ;
    skos:altLabel "First concept"@en ;
    skos:hiddenLabel "Internal alpha"@en ;
    skos:notation "A-001"^^<urn:test:notation-code> ;
    skos:definition "Alpha definition."@en ;
    skos:historyNote "Alpha history."@en ;
    dcterms:identifier "concept-a"@en ;
    dcterms:isVersionOf <urn:test:stable:concept-a> ;
    owl:priorVersion <urn:test:prior:concept-a> ;
    skos:broader <urn:test:concept:b> ;
    skos:related <urn:test:concept:c> ;
    skos:exactMatch <urn:test:external:concept> ;
    owl:deprecated "false"^^xsd:boolean .

<urn:test:concept:b>
    a skos:Concept ;
    skos:inScheme <urn:test:scheme:elsst-coverage> ;
    skos:prefLabel "Beta"@en ;
    skos:narrower <urn:test:concept:a> ;
    dcterms:isReplacedBy <urn:test:concept:c> .

<urn:test:concept:c>
    a skos:Concept ;
    skos:inScheme <urn:test:scheme:elsst-coverage> ;
    skos:prefLabel "Gamma"@en ;
    dcterms:replaces <urn:test:concept:b> .
"""


def _source_graph(
    *,
    source: bytes,
    drop_mapping: bool,
    emitted_status_lexical: str | None,
    scheme_identifier_mode: str,
) -> Mapping[str, object]:
    graph = Graph()
    graph.parse(data=source.decode("utf-8"), format="turtle")
    release = URIRef(RELEASE_IRI)
    for member in (CONCEPT_A, CONCEPT_B, CONCEPT_C):
        graph.add((release, _PROV.hadMember, URIRef(member)))
    if drop_mapping:
        graph.remove(
            (
                URIRef(CONCEPT_A),
                SKOS.exactMatch,
                URIRef(EXTERNAL_CONCEPT),
            )
        )
    scheme_identifier = (
        URIRef(SCHEME_IRI),
        URIRef(IDENTIFIER_PREDICATE_IRI),
        Literal("scheme-coverage", lang="en"),
    )
    if scheme_identifier_mode in {"omitted", "tampered"}:
        graph.remove(scheme_identifier)
    if scheme_identifier_mode == "tampered":
        graph.add(
            (
                URIRef(SCHEME_IRI),
                URIRef(IDENTIFIER_PREDICATE_IRI),
                Literal("scheme-tampered", lang="en"),
            )
        )
    serialized = json.loads(graph.serialize(format="json-ld"))
    assert isinstance(serialized, list)
    if emitted_status_lexical is not None:
        concept = next(node for node in serialized if node.get("@id") == CONCEPT_A)
        concept["http://www.w3.org/2002/07/owl#deprecated"] = [
            {
                "@value": emitted_status_lexical,
                "@type": ("http://www.w3.org/2001/XMLSchema#boolean"),
            }
        ]
    return {"@graph": serialized}


def _expression(
    *,
    predicate: str,
    subject: str,
    lexical_form: str,
    language: str | None,
    datatype: str | None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "referenceResourceRelease": {
            "id": RELEASE_IRI,
            "version": "fixture",
            "digest": "sha256:" + "1" * 64,
        },
        "member": subject,
        "scheme": SCHEME_IRI,
        "semanticProperty": predicate,
        "originalLiteral": lexical_form,
    }
    if language is not None:
        record["language"] = language
    if datatype is not None:
        record["datatype"] = datatype
    return record


def _emitted_expressions(
    parsed: ElsstVocabulary,
    *,
    drop_hidden_label: bool,
) -> tuple[Mapping[str, object], ...]:
    members = {CONCEPT_A, CONCEPT_B, CONCEPT_C}
    expressions: list[Mapping[str, object]] = []
    for item in parsed.labels:
        if item.subject_iri not in members:
            continue
        if drop_hidden_label and item.property_iri == HIDDEN_LABEL_PREDICATE_IRI:
            continue
        expressions.append(
            _expression(
                predicate=item.property_iri,
                subject=item.subject_iri,
                lexical_form=item.value.lexical_form,
                language=item.value.language_tag,
                datatype=item.value.datatype_iri,
            )
        )
    for values in (
        parsed.notes,
        parsed.notations,
        tuple(item for item in parsed.metadata_literals if item.property_iri == IDENTIFIER_PREDICATE_IRI),
    ):
        for item in values:
            if item.subject_iri not in members:
                continue
            expressions.append(
                _expression(
                    predicate=item.property_iri,
                    subject=item.subject_iri,
                    lexical_form=item.value.lexical_form,
                    language=item.value.language_tag,
                    datatype=item.value.datatype_iri,
                )
            )
    return tuple(expressions)


def _normalized_labels(
    parsed: ElsstVocabulary,
) -> tuple[Mapping[str, object], ...]:
    members = {CONCEPT_A, CONCEPT_B, CONCEPT_C}
    return tuple(
        {
            "release_iri": RELEASE_IRI,
            "concept_iri": item.subject_iri,
            "source_property_iri": item.property_iri,
            "original_literal": item.value.lexical_form,
            "language_tag": item.value.language_tag,
            "migration_only": False,
        }
        for item in parsed.labels
        if item.subject_iri in members
    )


def _normalized_relations(
    parsed: ElsstVocabulary,
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        {
            "release_iri": RELEASE_IRI,
            "subject_concept_iri": item.subject_iri,
            "predicate_iri": item.predicate_iri,
            "object_concept_iri": item.object_iri,
            "migration_only": False,
        }
        for item in parsed.semantic_relations
    )


def _censuses(
    *,
    source: bytes = SOURCE,
    drop_mapping: bool = False,
    drop_hidden_label: bool = False,
    emitted_status_lexical: str | None = None,
    scheme_identifier_mode: str = "exact",
):
    source_sha256 = "sha256:" + hashlib.sha256(source).hexdigest()
    parsed = parse_elsst_turtle(
        source,
        source_url=SOURCE_URL,
        expected_sha256=source_sha256,
        expected_byte_length=len(source),
    )
    raw_census = census_raw_elsst_turtle(
        source,
        source_url=SOURCE_URL,
        release_iri=RELEASE_IRI,
        expected_sha256=source_sha256,
        expected_byte_length=len(source),
    )
    parsed_census = census_parsed_elsst(
        parsed,
        release_iri=RELEASE_IRI,
    )
    indexed_census = census_indexed_elsst(
        source_sha256=source_sha256,
        release_iri=RELEASE_IRI,
        concept_scheme_iri=SCHEME_IRI,
        expressions=_emitted_expressions(
            parsed,
            drop_hidden_label=drop_hidden_label,
        ),
        rulespec_graph=_source_graph(
            source=source,
            drop_mapping=drop_mapping,
            emitted_status_lexical=emitted_status_lexical,
            scheme_identifier_mode=scheme_identifier_mode,
        ),
        normalized_labels=_normalized_labels(parsed),
        normalized_relations=_normalized_relations(parsed),
    )
    return raw_census, parsed_census, indexed_census


def test_independent_censuses_close_every_source_assertion() -> None:
    raw, parsed, indexed = _censuses()

    result = require_complete_elsst_import_coverage(
        raw,
        parsed,
        indexed,
    )

    assert result.passed
    assert raw is not parsed
    assert parsed is not indexed
    assert tuple(item.feature for item in raw.features) == (ELSST_COVERAGE_FEATURES)
    assert all(raw.feature(name).count > 0 for name in ELSST_COVERAGE_FEATURES)
    assert raw.feature("mappings").count == 1
    assert raw.feature("identifiers").count == 6
    for census in (raw, parsed, indexed):
        for feature in ELSST_COVERAGE_FEATURES:
            item = census.feature(feature)
            assert all(
                len(assertion_hash) == 32
                for assertion_hash in item.assertion_hashes
            )
            assert len(item.canonical_examples) <= 3
    rows = result.feature_rows()
    assert len(rows) == len(ELSST_COVERAGE_FEATURES)
    assert all(row["sourceObservedCount"] == row["parsedCount"] == row["indexedCount"] for row in rows)
    assert all(row["sourceObservedDigest"] == row["parsedDigest"] == row["indexedDigest"] for row in rows)


def test_dropped_mapping_fails_assertion_level_indexed_coverage() -> None:
    raw, parsed, indexed = _censuses(drop_mapping=True)

    result = validate_elsst_import_coverage(raw, parsed, indexed)

    difference = next(
        item for item in result.differences if item.feature == "mappings" and item.transition == "parsedToIndexed"
    )
    assert difference.missing_count == 1
    assert difference.unexpected_count == 0
    assert difference.expected_digest != difference.actual_digest
    with pytest.raises(
        ElsstImportCoverageError,
        match=r"mappings parsedToIndexed missing=1",
    ):
        require_complete_elsst_import_coverage(
            raw,
            parsed,
            indexed,
        )


def test_dropped_hidden_label_expression_fails_even_when_graph_retains_it() -> None:
    raw, parsed, indexed = _censuses(drop_hidden_label=True)

    result = validate_elsst_import_coverage(raw, parsed, indexed)

    difference = next(
        item for item in result.differences if item.feature == "labels" and item.transition == "parsedToIndexed"
    )
    assert difference.missing_count == 1
    assert difference.unexpected_count == 0
    assert difference.missing_examples[0].startswith("sha256:")


@pytest.mark.parametrize(
    ("scheme_identifier_mode", "unexpected_count"),
    [
        ("omitted", 0),
        ("tampered", 1),
    ],
)
def test_omitted_or_tampered_scheme_identifier_fails_coverage(
    scheme_identifier_mode: str,
    unexpected_count: int,
) -> None:
    raw, parsed, indexed = _censuses(
        scheme_identifier_mode=scheme_identifier_mode,
    )

    result = validate_elsst_import_coverage(raw, parsed, indexed)

    difference = next(
        item
        for item in result.differences
        if item.feature == "identifiers"
        and item.transition == "parsedToIndexed"
    )
    assert difference.missing_count == 1
    assert difference.unexpected_count == unexpected_count
    assert any(
        item.feature == "languages"
        and item.transition == "parsedToIndexed"
        and item.missing_count == 1
        and item.unexpected_count == unexpected_count
        for item in result.differences
    )


def test_raw_census_requires_exact_bytes_not_parser_output() -> None:
    parsed = parse_elsst_turtle(SOURCE, source_url=SOURCE_URL)

    with pytest.raises(
        TypeError,
        match="exact Turtle bytes",
    ):
        census_raw_elsst_turtle(  # type: ignore[arg-type]
            parsed,
            source_url=SOURCE_URL,
            release_iri=RELEASE_IRI,
            expected_sha256=parsed.source_sha256,
            expected_byte_length=parsed.source_bytes,
        )


def test_boolean_status_lexical_form_survives_all_three_stages() -> None:
    source = SOURCE.replace(
        b'"false"^^xsd:boolean',
        b'"0"^^xsd:boolean',
    )
    raw, parsed, indexed = _censuses(
        source=source,
        emitted_status_lexical="0",
    )

    result = require_complete_elsst_import_coverage(
        raw,
        parsed,
        indexed,
    )

    assert result.passed
    assert any(
        '"lexicalForm":"0"' in identity
        for _assertion_hash, identity in (
            raw.feature("status").canonical_examples
        )
    )
