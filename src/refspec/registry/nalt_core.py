"""Lossless RDF/SKOS feature reader for pinned NALT Core concept captures.

Source: National Agricultural Library Thesaurus (NALT) Core, published by the
USDA National Agricultural Library at https://lod.nal.usda.gov/nalt-core/ (a
Skosmos vocabulary distinct from the far larger "NALT Full" instance at
https://lod.nal.usda.gov/nalt/). NALT does not publish a single downloadable
Core distribution; it serves one concise bounded description (CBD) per
concept from ``https://lod.nal.usda.gov/rest/v1/nalt-core/data``. This module
therefore treats one exact concept CBD as the unit of source-faithful capture,
the same way the ELSST reader treats one exact release Turtle file: byte
capture, sha256 pinning, and lossless RDF feature rows, with no minted concept
identity beyond the IRIs NALT itself publishes.

Catalog scope (binding): pilot NALT Core only. NALT Full is mappings-support
and is never promoted into this module's concept-scheme role; a payload or a
requested concept that does not assert membership in the NALT Core scheme
(https://lod.nal.usda.gov/nalt-core) is refused, not silently included.

License (unresolved, recorded not decided): NALT's own vocabulary description
page states CC BY 4.0, which conflicts with USDA's broader public-domain/CC0
posture for USDA works. Both claims are carried in every package manifest;
neither is asserted as authoritative here.

Importing this module never opens a network connection.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS
from rdflib.parser import create_input_source
from rdflib.plugins.parsers.notation3 import RDFSink, SinkParser
from rdflib.term import Identifier

from refspec.registry.infrastructure.source_controlled_resource import LabelRole as NaltLabelRole

NALT_VOCABULARY_NAMESPACE_IRI = "https://lod.nal.usda.gov/naltv#"
NALT_CORE_SCHEME_IRI = "https://lod.nal.usda.gov/nalt-core"
NALT_FULL_SCHEME_IRI = "https://lod.nal.usda.gov/nalt"
NALT_CORE_DATA_ENDPOINT = "https://lod.nal.usda.gov/rest/v1/nalt-core/data"
NALT_CORE_PUBLISHER = "USDA National Agricultural Library"
# Verbatim framing from the source-vocabulary-ontology-thesaurus catalog row
# for NALT; kept exact so downstream readers see the same scope decision.
NALT_CORE_CATALOG_ROLE = (
    "Pilot Core only after reconciling the exact release and conflicting CC "
    "BY 4.0 versus broader USDA public-domain/CC0 statements. NALT Core has "
    "about 14,000 concepts; NALT Full is mappings-support and is not "
    "promoted into this module's concept-scheme role."
)

PREF_LABEL_PREDICATE_IRI = str(SKOS.prefLabel)
ALT_LABEL_PREDICATE_IRI = str(SKOS.altLabel)
HIDDEN_LABEL_PREDICATE_IRI = str(SKOS.hiddenLabel)

# NALT does not attach skos:definition literals directly; it points to a
# publisher-minted definition-node IRI carrying rdf:value (localized text)
# and dc:source (attribution). That indirection is preserved as-is below
# rather than flattened into a single literal, to avoid inventing a shape
# the source does not publish.
DEFINITION_PREDICATE_IRI = str(SKOS.definition)
REIFIED_VALUE_PREDICATE_IRI = str(RDF.value)
REIFIED_SOURCE_PREDICATE_IRI = str(DCTERMS.source)

BROADER_PREDICATE_IRI = str(SKOS.broader)
NARROWER_PREDICATE_IRI = str(SKOS.narrower)
RELATED_PREDICATE_IRI = str(SKOS.related)
HIERARCHY_PREDICATE_IRIS = (BROADER_PREDICATE_IRI, NARROWER_PREDICATE_IRI, RELATED_PREDICATE_IRI)

SKOS_MAPPING_PREDICATE_IRIS = (
    str(SKOS.mappingRelation),
    str(SKOS.broadMatch),
    str(SKOS.narrowMatch),
    str(SKOS.relatedMatch),
    str(SKOS.closeMatch),
    str(SKOS.exactMatch),
)

CREATED_PREDICATE_IRI = str(DCTERMS.created)
MODIFIED_PREDICATE_IRI = str(DCTERMS.modified)
MARC001_PREDICATE_IRI = NALT_VOCABULARY_NAMESPACE_IRI + "marc001"
NALT_METADATA_LITERAL_PREDICATE_IRIS = (
    CREATED_PREDICATE_IRI,
    MODIFIED_PREDICATE_IRI,
    MARC001_PREDICATE_IRI,
)

SCHEME_LABEL_PREDICATE_IRI = str(RDFS.label)
SCHEME_PUBLISHER_PREDICATE_IRI = str(DCTERMS.publisher)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class NaltCoreError(ValueError):
    """A NALT feature cannot be preserved, or scoped to Core, without guessing."""


class _LexicalRDFSink(RDFSink):
    """Create literals without RDFLib's value-based lexical normalization."""

    def newLiteral(
        self,
        s: str,
        dt: URIRef | None,
        lang: str | None,
    ) -> Literal:
        return Literal(
            s,
            datatype=dt,
            lang=None if dt is not None else lang,
            normalize=False,
        )


def _parse_lossless_turtle(
    graph: Graph,
    payload: bytes,
    *,
    source_url: str,
) -> None:
    source = create_input_source(
        source=io.BytesIO(payload),
        publicID=source_url,
        format="turtle",
    )
    sink = _LexicalRDFSink(graph)
    base_uri = graph.absolutize(source.getPublicId() or source.getSystemId() or "")
    parser = SinkParser(sink, baseURI=base_uri, turtle=True)
    stream = source.getCharacterStream() or source.getByteStream()
    parser.loadStream(stream)
    for prefix, namespace in parser._bindings.items():
        graph.bind(prefix, namespace)


@dataclass(frozen=True, slots=True)
class NaltLiteral:
    """One RDF literal with its lexical form, language, and datatype."""

    lexical_form: str
    language_tag: str | None
    datatype_iri: str | None


@dataclass(frozen=True, slots=True)
class NaltConcept:
    """One captured ``skos:Concept`` and the scheme assertions this payload carries for it.

    A concept that appears only as a broader/narrower/related neighbor in a
    capture (no ``skos:inScheme``/``skos:topConceptOf`` triple of its own in
    that payload) has empty ``scheme_iris``/``top_concept_of_iris``; it is
    never assumed to share the requested concept's scheme membership.
    """

    concept_iri: str
    scheme_iris: tuple[str, ...]
    top_concept_of_iris: tuple[str, ...]
    type_iris: tuple[str, ...]

    @property
    def in_core_scope(self) -> bool:
        return NALT_CORE_SCHEME_IRI in self.scheme_iris or NALT_CORE_SCHEME_IRI in self.top_concept_of_iris


@dataclass(frozen=True, slots=True)
class NaltConceptScheme:
    """One source ``skos:ConceptScheme`` and its own top concepts, labels, and publisher."""

    scheme_iri: str
    top_concept_iris: tuple[str, ...]
    labels: tuple[NaltLiteral, ...]
    publisher_iris: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NaltLabelExpression:
    """One authored SKOS label assertion."""

    subject_iri: str
    property_iri: str
    role: NaltLabelRole
    value: NaltLiteral


@dataclass(frozen=True, slots=True)
class NaltIriRelation:
    """One RDF assertion whose subject and object remain exact source IRIs."""

    subject_iri: str
    predicate_iri: str
    object_iri: str


@dataclass(frozen=True, slots=True)
class NaltReifiedLiteral:
    """One literal on a NALT reified value node (for example a definition target)."""

    subject_iri: str
    property_iri: str
    value: NaltLiteral


@dataclass(frozen=True, slots=True)
class NaltMetadataLiteral:
    """One authored source lifecycle date or source-native identifier literal."""

    subject_iri: str
    property_iri: str
    value: NaltLiteral


@dataclass(frozen=True, slots=True)
class NaltPredicateCount:
    """An observed predicate count used to make import coverage explicit."""

    predicate_iri: str
    assertion_count: int


@dataclass(frozen=True, slots=True)
class NaltImportCounts:
    """Feature counts for regression and import-coverage checks."""

    source_bytes: int
    triples: int
    source_iris: int
    concepts: int
    core_scope_concepts: int
    concept_schemes: int
    preferred_labels: int
    alternate_labels: int
    hidden_labels: int
    broader_relations: int
    narrower_relations: int
    related_relations: int
    mapping_relations: int
    definition_relations: int
    reified_values: int
    reified_sources: int
    metadata_literals: int
    created_assertions: int
    modified_assertions: int
    marc001_assertions: int


@dataclass(frozen=True, slots=True)
class NaltVocabulary:
    """Deterministic parsed view of one exact NALT Turtle payload."""

    source_url: str
    source_sha256: str
    source_bytes: int
    triple_count: int
    source_iris: tuple[str, ...]
    predicate_counts: tuple[NaltPredicateCount, ...]
    concepts: tuple[NaltConcept, ...]
    concept_schemes: tuple[NaltConceptScheme, ...]
    labels: tuple[NaltLabelExpression, ...]
    semantic_relations: tuple[NaltIriRelation, ...]
    mapping_relations: tuple[NaltIriRelation, ...]
    definition_relations: tuple[NaltIriRelation, ...]
    reified_values: tuple[NaltReifiedLiteral, ...]
    reified_sources: tuple[NaltReifiedLiteral, ...]
    metadata_literals: tuple[NaltMetadataLiteral, ...]

    @property
    def core_scope_concepts(self) -> tuple[NaltConcept, ...]:
        return tuple(item for item in self.concepts if item.in_core_scope)

    @property
    def counts(self) -> NaltImportCounts:
        labels = Counter(item.role for item in self.labels)
        semantics = Counter(item.predicate_iri for item in self.semantic_relations)
        metadata = Counter(item.property_iri for item in self.metadata_literals)
        return NaltImportCounts(
            source_bytes=self.source_bytes,
            triples=self.triple_count,
            source_iris=len(self.source_iris),
            concepts=len(self.concepts),
            core_scope_concepts=len(self.core_scope_concepts),
            concept_schemes=len(self.concept_schemes),
            preferred_labels=labels["preferred"],
            alternate_labels=labels["alternate"],
            hidden_labels=labels["hidden"],
            broader_relations=semantics[BROADER_PREDICATE_IRI],
            narrower_relations=semantics[NARROWER_PREDICATE_IRI],
            related_relations=semantics[RELATED_PREDICATE_IRI],
            mapping_relations=len(self.mapping_relations),
            definition_relations=len(self.definition_relations),
            reified_values=len(self.reified_values),
            reified_sources=len(self.reified_sources),
            metadata_literals=len(self.metadata_literals),
            created_assertions=metadata[CREATED_PREDICATE_IRI],
            modified_assertions=metadata[MODIFIED_PREDICATE_IRI],
            marc001_assertions=metadata[MARC001_PREDICATE_IRI],
        )


def _require_absolute_iri(value: str, label: str) -> str:
    if not urllib.parse.urlsplit(value).scheme:
        raise NaltCoreError(f"{label} must be an absolute IRI, got {value!r}")
    return value


def _validate_source_url(source_url: str) -> None:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NaltCoreError("source_url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise NaltCoreError("source_url must not contain credentials")


def _expected_hex(expected_sha256: str) -> str:
    match = _DIGEST.fullmatch(expected_sha256)
    if match is None:
        raise NaltCoreError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
    return match.group(0)[len("sha256:") :]


def _iri(term: Identifier, label: str) -> str:
    if not isinstance(term, URIRef):
        kind = "blank node" if isinstance(term, BNode) else type(term).__name__
        raise NaltCoreError(f"{label} must be an IRI, got {kind}")
    return _require_absolute_iri(str(term), label)


def _literal(term: Identifier, label: str) -> NaltLiteral:
    if not isinstance(term, Literal):
        raise NaltCoreError(f"{label} must be an RDF literal")
    language_tag = str(term.language) if term.language is not None else None
    datatype_iri = str(term.datatype) if term.datatype is not None else None
    if datatype_iri is not None:
        _require_absolute_iri(datatype_iri, f"{label} datatype")
    return NaltLiteral(
        lexical_form=str(term),
        language_tag=language_tag,
        datatype_iri=datatype_iri,
    )


def _source_payload(source: str | bytes) -> bytes:
    if isinstance(source, bytes):
        payload = source
    elif isinstance(source, str):
        payload = source.encode("utf-8")
    else:
        raise TypeError("source must be str or bytes")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise NaltCoreError(f"NALT Turtle is not valid UTF-8 at byte {error.start}") from error
    return payload


def _labels(graph: Graph) -> tuple[NaltLabelExpression, ...]:
    properties: tuple[tuple[URIRef, NaltLabelRole], ...] = (
        (SKOS.prefLabel, "preferred"),
        (SKOS.altLabel, "alternate"),
        (SKOS.hiddenLabel, "hidden"),
    )
    labels: list[NaltLabelExpression] = []
    preferred_by_language: dict[tuple[str, str], str] = {}
    for predicate, role in properties:
        for subject, value in graph.subject_objects(predicate):
            subject_iri = _iri(subject, f"{role} label subject")
            literal = _literal(value, f"{role} label")
            if literal.language_tag is None:
                raise NaltCoreError(
                    f"{role} label on {subject_iri} is untagged; NALT labels must retain a language tag"
                )
            if role == "preferred":
                key = (subject_iri, literal.language_tag.casefold())
                previous = preferred_by_language.get(key)
                if previous is not None and previous != literal.lexical_form:
                    raise NaltCoreError(
                        f"{subject_iri} has more than one preferred label for language {literal.language_tag}"
                    )
                preferred_by_language[key] = literal.lexical_form
            labels.append(
                NaltLabelExpression(
                    subject_iri=subject_iri,
                    property_iri=str(predicate),
                    role=role,
                    value=literal,
                )
            )
    return tuple(
        sorted(
            labels,
            key=lambda item: (
                item.subject_iri,
                item.property_iri,
                item.value.language_tag or "",
                item.value.lexical_form,
                item.value.datatype_iri or "",
            ),
        )
    )


def _iri_relations(
    graph: Graph,
    predicate_iris: tuple[str, ...],
    *,
    label: str,
) -> tuple[NaltIriRelation, ...]:
    relations: list[NaltIriRelation] = []
    for predicate_iri in predicate_iris:
        for subject, object_ in graph.subject_objects(URIRef(predicate_iri)):
            relations.append(
                NaltIriRelation(
                    subject_iri=_iri(subject, f"{label} subject"),
                    predicate_iri=predicate_iri,
                    object_iri=_iri(object_, f"{label} object"),
                )
            )
    return tuple(
        sorted(
            relations,
            key=lambda item: (item.subject_iri, item.predicate_iri, item.object_iri),
        )
    )


def _reified_literals(
    graph: Graph,
    predicate: URIRef,
    *,
    label: str,
    require_language_tag: bool,
) -> tuple[NaltReifiedLiteral, ...]:
    rows: list[NaltReifiedLiteral] = []
    for subject, value in graph.subject_objects(predicate):
        subject_iri = _iri(subject, f"{label} subject")
        literal = _literal(value, label)
        if require_language_tag and literal.language_tag is None:
            raise NaltCoreError(f"{label} on {subject_iri} is untagged; NALT reified values must retain a language tag")
        rows.append(NaltReifiedLiteral(subject_iri=subject_iri, property_iri=str(predicate), value=literal))
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                item.subject_iri,
                item.value.language_tag or "",
                item.value.lexical_form,
                item.value.datatype_iri or "",
            ),
        )
    )


def _concepts(graph: Graph) -> tuple[NaltConcept, ...]:
    concepts: list[NaltConcept] = []
    for subject in set(graph.subjects(RDF.type, SKOS.Concept)):
        concept_iri = _iri(subject, "concept")
        schemes = tuple(sorted(_iri(item, "skos:inScheme object") for item in graph.objects(subject, SKOS.inScheme)))
        top_schemes = tuple(
            sorted(_iri(item, "skos:topConceptOf object") for item in graph.objects(subject, SKOS.topConceptOf))
        )
        type_iris = tuple(
            sorted(
                _iri(item, "rdf:type object")
                for item in graph.objects(subject, RDF.type)
                if item != SKOS.Concept
            )
        )
        concepts.append(
            NaltConcept(
                concept_iri=concept_iri,
                scheme_iris=schemes,
                top_concept_of_iris=top_schemes,
                type_iris=type_iris,
            )
        )
    return tuple(sorted(concepts, key=lambda item: item.concept_iri))


def _concept_schemes(graph: Graph) -> tuple[NaltConceptScheme, ...]:
    schemes: list[NaltConceptScheme] = []
    for subject in set(graph.subjects(RDF.type, SKOS.ConceptScheme)):
        scheme_iri = _iri(subject, "concept scheme")
        top_concepts = tuple(
            sorted(_iri(item, "skos:hasTopConcept object") for item in graph.objects(subject, SKOS.hasTopConcept))
        )
        labels: list[NaltLiteral] = []
        for value in graph.objects(subject, RDFS.label):
            literal = _literal(value, "concept scheme rdfs:label")
            if literal.language_tag is None:
                raise NaltCoreError(f"{scheme_iri} rdfs:label is untagged; NALT scheme labels must retain a language tag")
            labels.append(literal)
        publishers = tuple(
            sorted(_iri(item, "dc:publisher object") for item in graph.objects(subject, DCTERMS.publisher))
        )
        schemes.append(
            NaltConceptScheme(
                scheme_iri=scheme_iri,
                top_concept_iris=top_concepts,
                labels=tuple(sorted(labels, key=lambda item: (item.language_tag or "", item.lexical_form))),
                publisher_iris=publishers,
            )
        )
    return tuple(sorted(schemes, key=lambda item: item.scheme_iri))


def _metadata_literals(graph: Graph) -> tuple[NaltMetadataLiteral, ...]:
    assertions: list[NaltMetadataLiteral] = []
    for predicate_iri in NALT_METADATA_LITERAL_PREDICATE_IRIS:
        for subject, value in graph.subject_objects(URIRef(predicate_iri)):
            assertions.append(
                NaltMetadataLiteral(
                    subject_iri=_iri(subject, f"{predicate_iri} subject"),
                    property_iri=predicate_iri,
                    value=_literal(value, f"{predicate_iri} value"),
                )
            )
    return tuple(
        sorted(
            assertions,
            key=lambda item: (
                item.subject_iri,
                item.property_iri,
                item.value.language_tag or "",
                item.value.datatype_iri or "",
                item.value.lexical_form,
            ),
        )
    )


def parse_nalt_turtle(
    source: str | bytes,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> NaltVocabulary:
    """Parse one NALT Turtle payload into deterministic, lossless feature rows.

    This function does not require NALT Core scope; it parses exactly what
    the payload asserts. Use ``parse_nalt_core_capture`` to additionally
    refuse a payload or concept that is not scoped to NALT Core.
    """

    _require_absolute_iri(source_url, "source_url")
    payload = _source_payload(source)
    source_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None:
        if _DIGEST.fullmatch(expected_sha256) is None:
            raise NaltCoreError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if source_sha256 != expected_sha256:
            raise NaltCoreError(f"source digest mismatch: expected {expected_sha256}, got {source_sha256}")
    if expected_byte_length is not None:
        if expected_byte_length <= 0:
            raise NaltCoreError("expected_byte_length must be positive")
        if len(payload) != expected_byte_length:
            raise NaltCoreError(f"source byte length mismatch: expected {expected_byte_length}, got {len(payload)}")

    graph = Graph()
    try:
        _parse_lossless_turtle(graph, payload, source_url=source_url)
    except Exception as error:
        raise NaltCoreError(f"could not parse NALT Turtle: {error}") from error

    source_iris = tuple(
        sorted(
            {
                _require_absolute_iri(str(term), "source RDF IRI")
                for triple in graph
                for term in triple
                if isinstance(term, URIRef)
            }
        )
    )
    predicate_counts = Counter(str(predicate) for predicate in graph.predicates())

    return NaltVocabulary(
        source_url=source_url,
        source_sha256=source_sha256,
        source_bytes=len(payload),
        triple_count=len(graph),
        source_iris=source_iris,
        predicate_counts=tuple(
            NaltPredicateCount(predicate_iri=predicate, assertion_count=count)
            for predicate, count in sorted(predicate_counts.items())
        ),
        concepts=_concepts(graph),
        concept_schemes=_concept_schemes(graph),
        labels=_labels(graph),
        semantic_relations=_iri_relations(graph, HIERARCHY_PREDICATE_IRIS, label="SKOS hierarchy relation"),
        mapping_relations=_iri_relations(graph, SKOS_MAPPING_PREDICATE_IRIS, label="SKOS mapping relation"),
        definition_relations=_iri_relations(graph, (DEFINITION_PREDICATE_IRI,), label="skos:definition relation"),
        reified_values=_reified_literals(
            graph,
            RDF.value,
            label="reified value",
            require_language_tag=True,
        ),
        reified_sources=_reified_literals(
            graph,
            DCTERMS.source,
            label="reified source",
            require_language_tag=False,
        ),
        metadata_literals=_metadata_literals(graph),
    )


@dataclass(frozen=True, slots=True)
class NaltCoreCapture:
    """One verified NALT Core concept capture: a parsed payload plus the one
    requested concept confirmed to carry NALT Core scheme membership."""

    vocabulary: NaltVocabulary
    requested_concept_iri: str

    @property
    def requested_concept(self) -> NaltConcept:
        for item in self.vocabulary.concepts:
            if item.concept_iri == self.requested_concept_iri:
                return item
        raise NaltCoreError(f"requested concept {self.requested_concept_iri} is absent from the capture")


def parse_nalt_core_capture(
    source: str | bytes,
    *,
    source_url: str,
    concept_iri: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> NaltCoreCapture:
    """Parse one exact NALT Turtle payload and refuse anything not scoped to Core.

    Refuses (a) a payload that never asserts the NALT Core concept scheme,
    (b) a requested concept absent from the payload, and (c) a requested
    concept present but not asserted as a NALT Core member. This is the only
    way this module promotes a concept into the concept-scheme role.
    """

    vocabulary = parse_nalt_turtle(
        source,
        source_url=source_url,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )
    scheme_iris = {item.scheme_iri for item in vocabulary.concept_schemes}
    if NALT_CORE_SCHEME_IRI not in scheme_iris:
        raise NaltCoreError(f"capture does not assert the NALT Core concept scheme {NALT_CORE_SCHEME_IRI}")
    by_iri = {item.concept_iri: item for item in vocabulary.concepts}
    concept = by_iri.get(concept_iri)
    if concept is None:
        raise NaltCoreError(f"requested concept {concept_iri} is absent from the capture")
    if not concept.in_core_scope:
        raise NaltCoreError(
            f"requested concept {concept_iri} is not asserted as a member of NALT Core "
            f"({NALT_CORE_SCHEME_IRI}); refusing to promote it into the Core role"
        )
    return NaltCoreCapture(vocabulary=vocabulary, requested_concept_iri=concept_iri)


def parse_nalt_core_file(
    path: Path,
    *,
    source_url: str,
    concept_iri: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> NaltCoreCapture:
    """Parse one local Turtle file while retaining its external source identity."""

    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise NaltCoreError(f"NALT source is not a regular file: {source_path}")
    return parse_nalt_core_capture(
        source_path.read_bytes(),
        source_url=source_url,
        concept_iri=concept_iri,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )


@dataclass(frozen=True, slots=True)
class NaltCorePinnedCapture:
    """One verified, byte-pinned NALT concept capture used for regression tests."""

    concept_iri: str
    source_url: str
    expected_sha256: str
    expected_byte_length: int
    filename: str

    def __post_init__(self) -> None:
        _require_absolute_iri(self.concept_iri, "concept_iri")
        _validate_source_url(self.source_url)
        _expected_hex(self.expected_sha256)
        if self.expected_byte_length <= 0:
            raise NaltCoreError("expected_byte_length must be positive")
        if not self.filename or Path(self.filename).name != self.filename:
            raise NaltCoreError("filename must be one plain path component")


def _core_concept_data_url(concept_iri: str) -> str:
    _require_absolute_iri(concept_iri, "concept_iri")
    query = urllib.parse.urlencode({"uri": concept_iri, "format": "text/turtle"})
    return f"{NALT_CORE_DATA_ENDPOINT}?{query}"


# Real captures fetched 2026-08-03 from https://lod.nal.usda.gov/rest/v1/nalt-core/data
# (and, for the negative-scope fixture, .../rest/v1/nalt/data). Bytes are
# committed verbatim under tests/fixtures/nalt_core/.
NALT_CORE_ANIMAL_WELFARE_CAPTURE = NaltCorePinnedCapture(
    concept_iri="https://lod.nal.usda.gov/nalt/9084",
    source_url=_core_concept_data_url("https://lod.nal.usda.gov/nalt/9084"),
    expected_sha256="sha256:a038aff09a7ae825ea947a3f564748b3702ef36fe53cdc117cb22fc0aa8b3691",
    expected_byte_length=5523,
    filename="nalt-core-9084-animal-welfare.ttl",
)
NALT_CORE_TOP_CONCEPT_CAPTURE = NaltCorePinnedCapture(
    concept_iri="https://lod.nal.usda.gov/nalt/127295",
    source_url=_core_concept_data_url("https://lod.nal.usda.gov/nalt/127295"),
    expected_sha256="sha256:ff37a0cb2d33a080c6d55b0bcf338673cbc26db6ea48a094761edc02c0e4e2ee",
    expected_byte_length=3238,
    filename="nalt-core-127295-top-concept.ttl",
)
NALT_FULL_OUT_OF_SCOPE_CAPTURE = NaltCorePinnedCapture(
    concept_iri="https://lod.nal.usda.gov/nalt/143005",
    source_url=(
        "https://lod.nal.usda.gov/rest/v1/nalt/data"
        "?" + urllib.parse.urlencode({"uri": "https://lod.nal.usda.gov/nalt/143005", "format": "text/turtle"})
    ),
    expected_sha256="sha256:cea1a3f350fd3aa7297cec8b2f3217a00109a6b73e16aaab35ed2b8be497afc8",
    expected_byte_length=2144,
    filename="nalt-full-143005-out-of-core-scope.ttl",
)


@dataclass(frozen=True, slots=True)
class NaltFetchedResource:
    """One bounded response supplied by an acquisition transport."""

    requested_url: str
    resolved_url: str
    status_code: int
    content_type: str | None
    body: bytes

    def __post_init__(self) -> None:
        for value, field in (
            (self.requested_url, "requested_url"),
            (self.resolved_url, "resolved_url"),
        ):
            parsed = urllib.parse.urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise NaltCoreError(f"{field} must be an absolute HTTP(S) URL")
        if self.status_code < 100 or self.status_code > 599:
            raise NaltCoreError("status_code must be an HTTP status")
        if not isinstance(self.body, bytes):
            raise NaltCoreError("resource body must be bytes")


class NaltConceptFetcher(Protocol):
    """Transport boundary used by explicit NALT Core acquisition."""

    def __call__(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> NaltFetchedResource: ...


NALT_USER_AGENT = "RefSpec bounded NALT Core concept resolver/1.0 (research capture; contact via repository)"
DEFAULT_MAX_CONCEPT_BYTES = 2 * 1024 * 1024


def fetch_nalt_concept_with_urllib(
    url: str,
    *,
    timeout_seconds: float,
    max_bytes: int,
) -> NaltFetchedResource:
    """Fetch one concept CBD directly; callers must opt into this transport."""

    if timeout_seconds <= 0:
        raise NaltCoreError("timeout_seconds must be positive")
    if max_bytes <= 0:
        raise NaltCoreError("max_bytes must be positive")
    request = urllib.request.Request(
        url,
        headers={"Accept": "text/turtle", "User-Agent": NALT_USER_AGENT},
        method="GET",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as error:
        raise NaltCoreError(f"NALT Core returned HTTP {error.code} for {url}") from error
    except (OSError, urllib.error.URLError) as error:
        raise NaltCoreError(f"could not fetch {url}: {error}") from error
    with response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise NaltCoreError(f"NALT Core response exceeds max_bytes={max_bytes}: {url}")
        return NaltFetchedResource(
            requested_url=url,
            resolved_url=response.geturl(),
            status_code=getattr(response, "status", 200),
            content_type=response.headers.get("Content-Type"),
            body=body,
        )


def acquire_nalt_core_concept(
    concept_iri: str,
    *,
    fetch: NaltConceptFetcher | None = None,
    allow_direct_network: bool = False,
    timeout_seconds: float = 30.0,
    max_bytes: int = DEFAULT_MAX_CONCEPT_BYTES,
) -> NaltCoreCapture:
    """Acquire and verify one NALT Core concept's concise bounded description.

    Importing this module never opens a network connection. A caller must
    either inject ``fetch`` or set ``allow_direct_network=True``.
    """

    if timeout_seconds <= 0:
        raise NaltCoreError("timeout_seconds must be positive")
    if max_bytes <= 0:
        raise NaltCoreError("max_bytes must be positive")
    if fetch is None:
        if not allow_direct_network:
            raise NaltCoreError("live NALT acquisition requires fetch or allow_direct_network=True")
        fetch = fetch_nalt_concept_with_urllib

    url = _core_concept_data_url(concept_iri)
    resource = fetch(url, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
    if resource.requested_url != url:
        raise NaltCoreError("concept fetcher returned a different requested_url")
    if resource.status_code != 200:
        raise NaltCoreError(f"NALT Core returned HTTP {resource.status_code} for {url}")
    if len(resource.body) > max_bytes:
        raise NaltCoreError(f"NALT Core response exceeds max_bytes={max_bytes}")
    return parse_nalt_core_capture(resource.body, source_url=resource.resolved_url, concept_iri=concept_iri)


@dataclass(frozen=True, slots=True)
class NaltLicenseNotice:
    """The two unreconciled license claims covering NALT content.

    NALT's own vocabulary description page publishes CC BY 4.0, but USDA's
    broader public-domain/CC0 posture for USDA works has not been reconciled
    against that specific notice. This module records both claims; it
    resolves neither.
    """

    stated_license_iri: str = "https://creativecommons.org/licenses/by/4.0/"
    stated_license_label: str = "Creative Commons Attribution 4.0 International"
    conflicting_claim: str = (
        "USDA publishes a public-domain/CC0 posture for USDA works generally; "
        "that claim has not been reconciled with the CC BY 4.0 notice stated "
        "on the NALT vocabulary description page. Both claims are recorded "
        "here verbatim; neither is asserted as authoritative."
    )
    resolved: bool = False


NALT_CORE_LICENSE_NOTICE = NaltLicenseNotice()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def nalt_core_capture_manifest(capture: NaltCoreCapture) -> dict[str, object]:
    """Deterministic, closed description of one verified NALT Core concept capture."""

    vocabulary = capture.vocabulary
    concept = capture.requested_concept
    return {
        "kind": "skosVocabulary",
        "catalogRole": NALT_CORE_CATALOG_ROLE,
        "publisher": NALT_CORE_PUBLISHER,
        "conceptSchemeIri": NALT_CORE_SCHEME_IRI,
        "sourceUrl": vocabulary.source_url,
        "sourceSha256": vocabulary.source_sha256,
        "sourceBytes": vocabulary.source_bytes,
        "requestedConceptIri": capture.requested_concept_iri,
        "requestedConceptTypeIris": list(concept.type_iris),
        "requestedConceptSchemeIris": list(concept.scheme_iris),
        "license": {
            "statedLicenseIri": NALT_CORE_LICENSE_NOTICE.stated_license_iri,
            "statedLicenseLabel": NALT_CORE_LICENSE_NOTICE.stated_license_label,
            "conflictingClaim": NALT_CORE_LICENSE_NOTICE.conflicting_claim,
            "resolved": NALT_CORE_LICENSE_NOTICE.resolved,
        },
        "counts": dataclasses.asdict(vocabulary.counts),
    }


def nalt_core_capture_digest(capture: NaltCoreCapture) -> str:
    """A stable sha256 over the deterministic capture manifest."""

    return "sha256:" + hashlib.sha256(_canonical_json(nalt_core_capture_manifest(capture))).hexdigest()


__all__ = [
    "ALT_LABEL_PREDICATE_IRI",
    "BROADER_PREDICATE_IRI",
    "CREATED_PREDICATE_IRI",
    "DEFAULT_MAX_CONCEPT_BYTES",
    "DEFINITION_PREDICATE_IRI",
    "HIDDEN_LABEL_PREDICATE_IRI",
    "MARC001_PREDICATE_IRI",
    "MODIFIED_PREDICATE_IRI",
    "NALT_CORE_ANIMAL_WELFARE_CAPTURE",
    "NALT_CORE_CATALOG_ROLE",
    "NALT_CORE_DATA_ENDPOINT",
    "NALT_CORE_LICENSE_NOTICE",
    "NALT_CORE_PUBLISHER",
    "NALT_CORE_SCHEME_IRI",
    "NALT_CORE_TOP_CONCEPT_CAPTURE",
    "NALT_FULL_OUT_OF_SCOPE_CAPTURE",
    "NALT_FULL_SCHEME_IRI",
    "NALT_METADATA_LITERAL_PREDICATE_IRIS",
    "NALT_USER_AGENT",
    "NALT_VOCABULARY_NAMESPACE_IRI",
    "NARROWER_PREDICATE_IRI",
    "PREF_LABEL_PREDICATE_IRI",
    "REIFIED_SOURCE_PREDICATE_IRI",
    "REIFIED_VALUE_PREDICATE_IRI",
    "RELATED_PREDICATE_IRI",
    "SCHEME_LABEL_PREDICATE_IRI",
    "SCHEME_PUBLISHER_PREDICATE_IRI",
    "SKOS_MAPPING_PREDICATE_IRIS",
    "NaltConcept",
    "NaltConceptFetcher",
    "NaltConceptScheme",
    "NaltCoreCapture",
    "NaltCoreError",
    "NaltCorePinnedCapture",
    "NaltFetchedResource",
    "NaltImportCounts",
    "NaltIriRelation",
    "NaltLabelExpression",
    "NaltLabelRole",
    "NaltLicenseNotice",
    "NaltLiteral",
    "NaltMetadataLiteral",
    "NaltPredicateCount",
    "NaltReifiedLiteral",
    "NaltVocabulary",
    "acquire_nalt_core_concept",
    "fetch_nalt_concept_with_urllib",
    "nalt_core_capture_digest",
    "nalt_core_capture_manifest",
    "parse_nalt_core_capture",
    "parse_nalt_core_file",
    "parse_nalt_turtle",
]
