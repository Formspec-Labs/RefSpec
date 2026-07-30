"""Lossless RDF/SKOS feature reader for pinned ELSST Turtle releases.

The reader uses RDFLib's Turtle parser and keeps the authored release IRIs,
stable-identity IRIs, prior-version IRIs, language tags, literal datatypes, and
one record per RDF assertion for the vocabulary features RefSpec consumes. It
does not turn a stable concept IRI, a release-specific concept IRI, and a prior
version IRI into one identifier.
"""

from __future__ import annotations

import hashlib
import io
import re
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Literal as LiteralType

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, SKOS, XSD
from rdflib.parser import create_input_source
from rdflib.plugins.parsers.notation3 import RDFSink, SinkParser
from rdflib.term import Identifier

if TYPE_CHECKING:
    from refspec.registry.elsst_acquisition import AcquiredElsstSource

PREF_LABEL_PREDICATE_IRI = str(SKOS.prefLabel)
ALT_LABEL_PREDICATE_IRI = str(SKOS.altLabel)
HIDDEN_LABEL_PREDICATE_IRI = str(SKOS.hiddenLabel)
NOTATION_PREDICATE_IRI = str(SKOS.notation)

NOTE_PREDICATE_IRIS = (
    str(SKOS.definition),
    str(SKOS.example),
    str(SKOS.note),
    str(SKOS.scopeNote),
    str(SKOS.editorialNote),
    str(SKOS.historyNote),
    str(SKOS.changeNote),
)
ADDITIONAL_CONTENT_NOTE_PREDICATE_IRI = "http://rdf-vocabulary.ddialliance.org/xkos#additionalContentNote"
ELSST_NOTE_PREDICATE_IRIS = (*NOTE_PREDICATE_IRIS, ADDITIONAL_CONTENT_NOTE_PREDICATE_IRI)

BROADER_PREDICATE_IRI = str(SKOS.broader)
NARROWER_PREDICATE_IRI = str(SKOS.narrower)
RELATED_PREDICATE_IRI = str(SKOS.related)
HIERARCHY_AND_ASSOCIATIVE_PREDICATE_IRIS = (
    BROADER_PREDICATE_IRI,
    NARROWER_PREDICATE_IRI,
    RELATED_PREDICATE_IRI,
)
SKOS_MAPPING_PREDICATE_IRIS = (
    str(SKOS.mappingRelation),
    str(SKOS.broadMatch),
    str(SKOS.narrowMatch),
    str(SKOS.relatedMatch),
    str(SKOS.closeMatch),
    str(SKOS.exactMatch),
)

DEPRECATED_PREDICATE_IRI = str(OWL.deprecated)
IS_REPLACED_BY_PREDICATE_IRI = str(DCTERMS.isReplacedBy)
REPLACES_PREDICATE_IRI = str(DCTERMS.replaces)
IS_VERSION_OF_PREDICATE_IRI = str(DCTERMS.isVersionOf)
PRIOR_VERSION_PREDICATE_IRI = str(OWL.priorVersion)
IDENTIFIER_PREDICATE_IRI = str(DCTERMS.identifier)
ISSUED_PREDICATE_IRI = str(DCTERMS.issued)
MODIFIED_PREDICATE_IRI = str(DCTERMS.modified)
ELSST_METADATA_LITERAL_PREDICATE_IRIS = (
    IDENTIFIER_PREDICATE_IRI,
    ISSUED_PREDICATE_IRI,
    MODIFIED_PREDICATE_IRI,
    str(DCTERMS.license),
    str(DCTERMS.publisher),
    str(DCTERMS.rightsHolder),
    str(DCTERMS.description),
    str(OWL.versionInfo),
)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

ElsstLabelRole = LiteralType["preferred", "alternate", "hidden"]


class ElsstParseError(ValueError):
    """An ELSST RDF feature cannot be preserved without guessing."""


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
    base_uri = graph.absolutize(
        source.getPublicId() or source.getSystemId() or ""
    )
    parser = SinkParser(sink, baseURI=base_uri, turtle=True)
    stream = source.getCharacterStream() or source.getByteStream()
    parser.loadStream(stream)
    for prefix, namespace in parser._bindings.items():
        graph.bind(prefix, namespace)


@dataclass(frozen=True, slots=True)
class ElsstLiteral:
    """One RDF literal with its lexical form, language, and datatype."""

    lexical_form: str
    language_tag: str | None
    datatype_iri: str | None


@dataclass(frozen=True, slots=True)
class ElsstConcept:
    """One release-specific ``skos:Concept`` and its scheme assertions."""

    concept_iri: str
    scheme_iris: tuple[str, ...]
    top_concept_of_iris: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ElsstConceptScheme:
    """One source ``skos:ConceptScheme`` and its explicit top concepts."""

    scheme_iri: str
    top_concept_iris: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ElsstLabelExpression:
    """One authored SKOS label assertion."""

    subject_iri: str
    property_iri: str
    role: ElsstLabelRole
    value: ElsstLiteral


@dataclass(frozen=True, slots=True)
class ElsstNote:
    """One supported SKOS or ELSST-native note assertion."""

    subject_iri: str
    property_iri: str
    value: ElsstLiteral


@dataclass(frozen=True, slots=True)
class ElsstNotation:
    """One SKOS notation with its required absolute datatype IRI."""

    subject_iri: str
    property_iri: str
    value: ElsstLiteral


@dataclass(frozen=True, slots=True)
class ElsstIriRelation:
    """One RDF assertion whose subject and object remain exact source IRIs."""

    subject_iri: str
    predicate_iri: str
    object_iri: str


@dataclass(frozen=True, slots=True)
class ElsstDeprecation:
    """One exact ``owl:deprecated`` literal assertion."""

    subject_iri: str
    predicate_iri: str
    value: ElsstLiteral


@dataclass(frozen=True, slots=True)
class ElsstMetadataLiteral:
    """One authored source identifier or release/concept metadata literal."""

    subject_iri: str
    property_iri: str
    value: ElsstLiteral


@dataclass(frozen=True, slots=True)
class ElsstPredicateCount:
    """An observed predicate count used to make import coverage explicit."""

    predicate_iri: str
    assertion_count: int


@dataclass(frozen=True, slots=True)
class ElsstImportCounts:
    """Feature counts for regression and import-coverage checks."""

    source_bytes: int
    triples: int
    source_iris: int
    concepts: int
    concept_schemes: int
    preferred_labels: int
    alternate_labels: int
    hidden_labels: int
    notes: int
    notations: int
    broader_relations: int
    narrower_relations: int
    related_relations: int
    deprecated_assertions: int
    metadata_literals: int
    identifier_assertions: int
    issued_assertions: int
    modified_assertions: int
    is_replaced_by_relations: int
    replaces_relations: int
    is_version_of_relations: int
    prior_version_relations: int


@dataclass(frozen=True, slots=True)
class ElsstVocabulary:
    """Deterministic parsed view of one exact ELSST Turtle payload."""

    source_url: str
    source_sha256: str
    source_bytes: int
    triple_count: int
    source_iris: tuple[str, ...]
    predicate_counts: tuple[ElsstPredicateCount, ...]
    concepts: tuple[ElsstConcept, ...]
    concept_schemes: tuple[ElsstConceptScheme, ...]
    labels: tuple[ElsstLabelExpression, ...]
    notes: tuple[ElsstNote, ...]
    notations: tuple[ElsstNotation, ...]
    semantic_relations: tuple[ElsstIriRelation, ...]
    mapping_relations: tuple[ElsstIriRelation, ...]
    replacement_relations: tuple[ElsstIriRelation, ...]
    version_relations: tuple[ElsstIriRelation, ...]
    deprecated_assertions: tuple[ElsstDeprecation, ...]
    metadata_literals: tuple[ElsstMetadataLiteral, ...]

    @property
    def counts(self) -> ElsstImportCounts:
        labels = Counter(item.role for item in self.labels)
        semantics = Counter(item.predicate_iri for item in self.semantic_relations)
        replacements = Counter(item.predicate_iri for item in self.replacement_relations)
        versions = Counter(item.predicate_iri for item in self.version_relations)
        metadata = Counter(item.property_iri for item in self.metadata_literals)
        return ElsstImportCounts(
            source_bytes=self.source_bytes,
            triples=self.triple_count,
            source_iris=len(self.source_iris),
            concepts=len(self.concepts),
            concept_schemes=len(self.concept_schemes),
            preferred_labels=labels["preferred"],
            alternate_labels=labels["alternate"],
            hidden_labels=labels["hidden"],
            notes=len(self.notes),
            notations=len(self.notations),
            broader_relations=semantics[BROADER_PREDICATE_IRI],
            narrower_relations=semantics[NARROWER_PREDICATE_IRI],
            related_relations=semantics[RELATED_PREDICATE_IRI],
            deprecated_assertions=len(self.deprecated_assertions),
            metadata_literals=len(self.metadata_literals),
            identifier_assertions=metadata[IDENTIFIER_PREDICATE_IRI],
            issued_assertions=metadata[ISSUED_PREDICATE_IRI],
            modified_assertions=metadata[MODIFIED_PREDICATE_IRI],
            is_replaced_by_relations=replacements[IS_REPLACED_BY_PREDICATE_IRI],
            replaces_relations=replacements[REPLACES_PREDICATE_IRI],
            is_version_of_relations=versions[IS_VERSION_OF_PREDICATE_IRI],
            prior_version_relations=versions[PRIOR_VERSION_PREDICATE_IRI],
        )


@dataclass(frozen=True, slots=True)
class ElsstStableIdentityMatch:
    """One exact stable IRI shared by two release-specific concepts."""

    stable_identity_iri: str
    previous_concept_iri: str
    current_concept_iri: str
    asserted_prior_version_iri: str | None


@dataclass(frozen=True, slots=True)
class ElsstReleaseComparison:
    """Identity-based release differences without label-derived joins."""

    previous_source_sha256: str
    current_source_sha256: str
    retained_stable_identities: tuple[ElsstStableIdentityMatch, ...]
    added_concept_iris: tuple[str, ...]
    new_deprecated_concept_iris: tuple[str, ...]
    replacement_pairs: tuple[ElsstIriRelation, ...]


def _require_absolute_iri(value: str, label: str) -> str:
    if not urllib.parse.urlsplit(value).scheme:
        raise ElsstParseError(f"{label} must be an absolute IRI, got {value!r}")
    return value


def _iri(term: Identifier, label: str) -> str:
    if not isinstance(term, URIRef):
        kind = "blank node" if isinstance(term, BNode) else type(term).__name__
        raise ElsstParseError(f"{label} must be an IRI, got {kind}")
    return _require_absolute_iri(str(term), label)


def _literal(term: Identifier, label: str) -> ElsstLiteral:
    if not isinstance(term, Literal):
        raise ElsstParseError(f"{label} must be an RDF literal")
    language_tag = str(term.language) if term.language is not None else None
    datatype_iri = str(term.datatype) if term.datatype is not None else None
    if datatype_iri is not None:
        _require_absolute_iri(datatype_iri, f"{label} datatype")
    return ElsstLiteral(
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
        raise ElsstParseError(f"ELSST Turtle is not valid UTF-8 at byte {error.start}") from error
    return payload


def _label_expressions(graph: Graph) -> tuple[ElsstLabelExpression, ...]:
    properties: tuple[tuple[URIRef, ElsstLabelRole], ...] = (
        (SKOS.prefLabel, "preferred"),
        (SKOS.altLabel, "alternate"),
        (SKOS.hiddenLabel, "hidden"),
    )
    labels: list[ElsstLabelExpression] = []
    preferred_by_language: dict[tuple[str, str], str] = {}
    for predicate, role in properties:
        for subject, value in graph.subject_objects(predicate):
            subject_iri = _iri(subject, f"{role} label subject")
            literal = _literal(value, f"{role} label")
            if literal.language_tag is None:
                raise ElsstParseError(
                    f"{role} label on {subject_iri} is untagged; ELSST labels must retain a language tag"
                )
            if role == "preferred":
                key = (subject_iri, literal.language_tag.casefold())
                previous = preferred_by_language.get(key)
                if previous is not None and previous != literal.lexical_form:
                    raise ElsstParseError(
                        f"{subject_iri} has more than one preferred label for language {literal.language_tag}"
                    )
                preferred_by_language[key] = literal.lexical_form
            labels.append(
                ElsstLabelExpression(
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


def _notes(graph: Graph) -> tuple[ElsstNote, ...]:
    notes: list[ElsstNote] = []
    for predicate_iri in ELSST_NOTE_PREDICATE_IRIS:
        predicate = URIRef(predicate_iri)
        for subject, value in graph.subject_objects(predicate):
            notes.append(
                ElsstNote(
                    subject_iri=_iri(subject, "note subject"),
                    property_iri=predicate_iri,
                    value=_literal(value, f"{predicate_iri} value"),
                )
            )
    return tuple(
        sorted(
            notes,
            key=lambda item: (
                item.subject_iri,
                item.property_iri,
                item.value.language_tag or "",
                item.value.lexical_form,
                item.value.datatype_iri or "",
            ),
        )
    )


def _notations(graph: Graph) -> tuple[ElsstNotation, ...]:
    notations: list[ElsstNotation] = []
    for subject, value in graph.subject_objects(SKOS.notation):
        subject_iri = _iri(subject, "notation subject")
        literal = _literal(value, "notation")
        if literal.language_tag is not None or literal.datatype_iri is None:
            raise ElsstParseError(f"notation on {subject_iri} must be a typed literal with an absolute datatype IRI")
        notations.append(
            ElsstNotation(
                subject_iri=subject_iri,
                property_iri=NOTATION_PREDICATE_IRI,
                value=literal,
            )
        )
    return tuple(
        sorted(
            notations,
            key=lambda item: (
                item.subject_iri,
                item.value.datatype_iri or "",
                item.value.lexical_form,
            ),
        )
    )


def _iri_relations(
    graph: Graph,
    predicate_iris: tuple[str, ...],
    *,
    label: str,
) -> tuple[ElsstIriRelation, ...]:
    relations: list[ElsstIriRelation] = []
    for predicate_iri in predicate_iris:
        for subject, object_ in graph.subject_objects(URIRef(predicate_iri)):
            relations.append(
                ElsstIriRelation(
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


def _concepts(graph: Graph) -> tuple[ElsstConcept, ...]:
    concepts: list[ElsstConcept] = []
    for subject in set(graph.subjects(RDF.type, SKOS.Concept)):
        concept_iri = _iri(subject, "concept")
        schemes = tuple(sorted(_iri(item, "skos:inScheme object") for item in graph.objects(subject, SKOS.inScheme)))
        top_schemes = tuple(
            sorted(_iri(item, "skos:topConceptOf object") for item in graph.objects(subject, SKOS.topConceptOf))
        )
        concepts.append(
            ElsstConcept(
                concept_iri=concept_iri,
                scheme_iris=schemes,
                top_concept_of_iris=top_schemes,
            )
        )
    return tuple(sorted(concepts, key=lambda item: item.concept_iri))


def _concept_schemes(graph: Graph) -> tuple[ElsstConceptScheme, ...]:
    schemes: list[ElsstConceptScheme] = []
    for subject in set(graph.subjects(RDF.type, SKOS.ConceptScheme)):
        scheme_iri = _iri(subject, "concept scheme")
        top_concepts = tuple(
            sorted(_iri(item, "skos:hasTopConcept object") for item in graph.objects(subject, SKOS.hasTopConcept))
        )
        schemes.append(
            ElsstConceptScheme(
                scheme_iri=scheme_iri,
                top_concept_iris=top_concepts,
            )
        )
    return tuple(sorted(schemes, key=lambda item: item.scheme_iri))


def _deprecations(graph: Graph) -> tuple[ElsstDeprecation, ...]:
    assertions: list[ElsstDeprecation] = []
    for subject, value in graph.subject_objects(OWL.deprecated):
        assertions.append(
            ElsstDeprecation(
                subject_iri=_iri(subject, "owl:deprecated subject"),
                predicate_iri=DEPRECATED_PREDICATE_IRI,
                value=_literal(value, "owl:deprecated value"),
            )
        )
    return tuple(
        sorted(
            assertions,
            key=lambda item: (
                item.subject_iri,
                item.value.datatype_iri or "",
                item.value.lexical_form,
            ),
        )
    )


def _metadata_literals(graph: Graph) -> tuple[ElsstMetadataLiteral, ...]:
    assertions: list[ElsstMetadataLiteral] = []
    for predicate_iri in ELSST_METADATA_LITERAL_PREDICATE_IRIS:
        for subject, value in graph.subject_objects(URIRef(predicate_iri)):
            assertions.append(
                ElsstMetadataLiteral(
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


def parse_elsst_turtle(
    source: str | bytes,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> ElsstVocabulary:
    """Parse one ELSST Turtle payload into deterministic, lossless feature rows."""

    _require_absolute_iri(source_url, "source_url")
    payload = _source_payload(source)
    source_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None:
        if _DIGEST.fullmatch(expected_sha256) is None:
            raise ElsstParseError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if source_sha256 != expected_sha256:
            raise ElsstParseError(f"source digest mismatch: expected {expected_sha256}, got {source_sha256}")
    if expected_byte_length is not None:
        if expected_byte_length <= 0:
            raise ElsstParseError("expected_byte_length must be positive")
        if len(payload) != expected_byte_length:
            raise ElsstParseError(f"source byte length mismatch: expected {expected_byte_length}, got {len(payload)}")

    graph = Graph()
    try:
        _parse_lossless_turtle(
            graph,
            payload,
            source_url=source_url,
        )
    except Exception as error:
        raise ElsstParseError(f"could not parse ELSST Turtle: {error}") from error

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

    return ElsstVocabulary(
        source_url=source_url,
        source_sha256=source_sha256,
        source_bytes=len(payload),
        triple_count=len(graph),
        source_iris=source_iris,
        predicate_counts=tuple(
            ElsstPredicateCount(predicate_iri=predicate, assertion_count=count)
            for predicate, count in sorted(predicate_counts.items())
        ),
        concepts=_concepts(graph),
        concept_schemes=_concept_schemes(graph),
        labels=_label_expressions(graph),
        notes=_notes(graph),
        notations=_notations(graph),
        semantic_relations=_iri_relations(
            graph,
            HIERARCHY_AND_ASSOCIATIVE_PREDICATE_IRIS,
            label="SKOS semantic relation",
        ),
        mapping_relations=_iri_relations(
            graph,
            SKOS_MAPPING_PREDICATE_IRIS,
            label="SKOS mapping relation",
        ),
        replacement_relations=_iri_relations(
            graph,
            (IS_REPLACED_BY_PREDICATE_IRI, REPLACES_PREDICATE_IRI),
            label="replacement relation",
        ),
        version_relations=_iri_relations(
            graph,
            (IS_VERSION_OF_PREDICATE_IRI, PRIOR_VERSION_PREDICATE_IRI),
            label="version relation",
        ),
        deprecated_assertions=_deprecations(graph),
        metadata_literals=_metadata_literals(graph),
    )


def parse_acquired_elsst_source(acquired: AcquiredElsstSource) -> ElsstVocabulary:
    """Reverify and parse an object returned by the ELSST acquisition adapter."""

    if acquired.path.is_symlink() or not acquired.path.is_file():
        raise ElsstParseError(f"acquired ELSST source is not a regular file: {acquired.path}")
    parsed = parse_elsst_turtle(
        acquired.path.read_bytes(),
        source_url=acquired.release.source_url,
        expected_sha256=acquired.release.expected_sha256,
        expected_byte_length=acquired.release.expected_byte_length,
    )
    scheme_iris = {item.scheme_iri for item in parsed.concept_schemes}
    if acquired.release.concept_scheme_iri not in scheme_iris:
        raise ElsstParseError(
            f"pinned ELSST concept scheme {acquired.release.concept_scheme_iri} is absent from the distribution"
        )
    return parsed


def parse_elsst_file(
    path: Path,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> ElsstVocabulary:
    """Parse one local Turtle file while retaining its external source identity."""

    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise ElsstParseError(f"ELSST source is not a regular file: {source_path}")
    return parse_elsst_turtle(
        source_path.read_bytes(),
        source_url=source_url,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )


def _one_relation_object_by_subject(
    vocabulary: ElsstVocabulary,
    *,
    predicate_iri: str,
    concept_iris: set[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for relation in vocabulary.version_relations:
        if relation.predicate_iri != predicate_iri or relation.subject_iri not in concept_iris:
            continue
        previous = result.get(relation.subject_iri)
        if previous is not None and previous != relation.object_iri:
            raise ElsstParseError(f"{relation.subject_iri} has more than one {predicate_iri} object")
        result[relation.subject_iri] = relation.object_iri
    return result


def _true_deprecation_subjects(vocabulary: ElsstVocabulary) -> set[str]:
    subjects: set[str] = set()
    for assertion in vocabulary.deprecated_assertions:
        value = assertion.value
        if (
            value.language_tag is not None
            or value.datatype_iri != str(XSD.boolean)
            or value.lexical_form
            not in {"true", "1", "false", "0"}
        ):
            raise ElsstParseError(
                f"{assertion.subject_iri} has an unsupported "
                "owl:deprecated literal"
            )
        if value.lexical_form in {"true", "1"}:
            subjects.add(assertion.subject_iri)
    return subjects


def compare_elsst_releases(
    previous: ElsstVocabulary,
    current: ElsstVocabulary,
) -> ElsstReleaseComparison:
    """Compare ELSST releases only through exact RDF identity assertions.

    No label, notation, or URI-shape heuristic participates in the join.
    ``dct:isVersionOf`` supplies stable identities and ``owl:priorVersion``
    supplies an explicit predecessor when present.
    """

    previous_concepts = {item.concept_iri for item in previous.concepts}
    current_concepts = {item.concept_iri for item in current.concepts}
    previous_stable_by_concept = _one_relation_object_by_subject(
        previous,
        predicate_iri=IS_VERSION_OF_PREDICATE_IRI,
        concept_iris=previous_concepts,
    )
    current_stable_by_concept = _one_relation_object_by_subject(
        current,
        predicate_iri=IS_VERSION_OF_PREDICATE_IRI,
        concept_iris=current_concepts,
    )
    current_prior_by_concept = _one_relation_object_by_subject(
        current,
        predicate_iri=PRIOR_VERSION_PREDICATE_IRI,
        concept_iris=current_concepts,
    )

    previous_concept_by_stable: dict[str, str] = {}
    for concept_iri, stable_iri in previous_stable_by_concept.items():
        other = previous_concept_by_stable.get(stable_iri)
        if other is not None and other != concept_iri:
            raise ElsstParseError(f"previous release maps stable identity {stable_iri} to more than one concept")
        previous_concept_by_stable[stable_iri] = concept_iri

    current_concept_by_stable: dict[str, str] = {}
    for concept_iri, stable_iri in current_stable_by_concept.items():
        other = current_concept_by_stable.get(stable_iri)
        if other is not None and other != concept_iri:
            raise ElsstParseError(f"current release maps stable identity {stable_iri} to more than one concept")
        current_concept_by_stable[stable_iri] = concept_iri

    retained: list[ElsstStableIdentityMatch] = []
    predecessor_by_current: dict[str, str] = {}
    for stable_iri in sorted(previous_concept_by_stable.keys() & current_concept_by_stable.keys()):
        previous_concept_iri = previous_concept_by_stable[stable_iri]
        current_concept_iri = current_concept_by_stable[stable_iri]
        asserted_prior = current_prior_by_concept.get(current_concept_iri)
        if asserted_prior is not None and asserted_prior != previous_concept_iri:
            raise ElsstParseError(f"{current_concept_iri} has conflicting dct:isVersionOf and owl:priorVersion joins")
        predecessor_by_current[current_concept_iri] = previous_concept_iri
        retained.append(
            ElsstStableIdentityMatch(
                stable_identity_iri=stable_iri,
                previous_concept_iri=previous_concept_iri,
                current_concept_iri=current_concept_iri,
                asserted_prior_version_iri=asserted_prior,
            )
        )

    for current_concept_iri, prior_iri in current_prior_by_concept.items():
        if prior_iri not in previous_concepts:
            continue
        existing = predecessor_by_current.get(current_concept_iri)
        if existing is not None and existing != prior_iri:
            raise ElsstParseError(f"{current_concept_iri} has conflicting exact predecessor assertions")
        predecessor_by_current[current_concept_iri] = prior_iri

    added = tuple(sorted(current_concepts - predecessor_by_current.keys()))
    previous_deprecated = _true_deprecation_subjects(previous)
    current_deprecated = _true_deprecation_subjects(current)
    new_deprecated = tuple(
        sorted(
            concept_iri
            for concept_iri in current_deprecated
            if predecessor_by_current.get(concept_iri) not in previous_deprecated
        )
    )
    replacement_pairs = tuple(
        relation for relation in current.replacement_relations if relation.predicate_iri == IS_REPLACED_BY_PREDICATE_IRI
    )

    return ElsstReleaseComparison(
        previous_source_sha256=previous.source_sha256,
        current_source_sha256=current.source_sha256,
        retained_stable_identities=tuple(retained),
        added_concept_iris=added,
        new_deprecated_concept_iris=new_deprecated,
        replacement_pairs=replacement_pairs,
    )
