"""Lossless SKOS mapping-source reader for pinned AGROVOC Turtle exports.

The source catalog scopes AGROVOC (Food and Agriculture Organization
multilingual concept scheme) as a crosswalk and multilingual-expansion
mapping source for NALT-backed subjects, not as a general subject vocabulary.
This module packages AGROVOC under that role: it keeps AGROVOC's own
concepts, multilingual labels, and SKOS mapping-relation assertions exactly
as published, and it refuses to combine an AGROVOC concept identity with a
target scheme's identity (for example, NALT). No AGROVOC concept identity is
minted here; every identifier is the exact source IRI.

AGROVOC concept IRIs are stable and are not versioned per release the way
ELSST's `/id/<version>/` IRIs are, so this module does not attempt a
release-to-release identity comparison. A live check of the AGROVOC dataset
description (https://aims.fao.org/aos/agrovoc/void.ttl, 2026-08-03) reports
`dct:license <https://creativecommons.org/licenses/by/4.0/>`. The source
catalog separately warns to track language-specific contributor rights and
CC BY 3.0 IGO attribution rather than assume one license covers every
language; that per-language reconciliation is unresolved and is recorded as
a follow-up, not silently dropped.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import urllib.parse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, SKOS
from rdflib.parser import create_input_source
from rdflib.plugins.parsers.notation3 import RDFSink, SinkParser
from rdflib.term import Identifier

from refspec.registry.infrastructure.pinned_acquisition import (
    AcquiredPinnedSource,
    AcquisitionMode,
    PinnedAcquisitionError,
    PinnedAcquisitionLabels,
    acquire_pinned_source,
    expected_digest_hex,
)
from refspec.registry.infrastructure.source_controlled_resource import LabelRole as AgrovocLabelRole

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

BROADER_PREDICATE_IRI = str(SKOS.broader)
NARROWER_PREDICATE_IRI = str(SKOS.narrower)
RELATED_PREDICATE_IRI = str(SKOS.related)
HIERARCHY_AND_ASSOCIATIVE_PREDICATE_IRIS = (
    BROADER_PREDICATE_IRI,
    NARROWER_PREDICATE_IRI,
    RELATED_PREDICATE_IRI,
)
# The catalog's crosswalk role is carried by these five SKOS mapping
# predicates; a mapping relation is always a plain (subject, predicate,
# object) row and never a merged identifier.
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
AGROVOC_METADATA_LITERAL_PREDICATE_IRIS = (
    CREATED_PREDICATE_IRI,
    MODIFIED_PREDICATE_IRI,
)

SAME_AS_PREDICATE_IRI = str(OWL.sameAs)

# The National Agricultural Library Thesaurus (NALT) namespace. Concept
# catalog guidance: "do not combine identifiers with NALT — keep AGROVOC
# IRIs authoritative and separate." An AGROVOC concept identity must never be
# minted inside this namespace, and a crosswalk relation into it stays a
# plain mapping row rather than a merged identifier.
NALT_IRI_PREFIXES = (
    "https://lod.nal.usda.gov/nalt/",
    "http://lod.nal.usda.gov/nalt/",
)

AGROVOC_PUBLISHER = "Food and Agriculture Organization of the United Nations (FAO)"
AGROVOC_LICENSE_IRI = "https://creativecommons.org/licenses/by/4.0/"
AGROVOC_LICENSE_LABEL = "Creative Commons Attribution 4.0 International"
AGROVOC_ATTRIBUTION = "Food and Agriculture Organization of the United Nations (FAO), AGROVOC Multilingual Thesaurus"
AGROVOC_SCHEME_IRI = "http://aims.fao.org/aos/agrovoc"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class AgrovocParseError(ValueError):
    """An AGROVOC RDF feature cannot be preserved without guessing or merging identity."""


class AgrovocAcquisitionError(ValueError):
    """An AGROVOC source could not be acquired without weakening its pin."""


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
class AgrovocLiteral:
    """One RDF literal with its lexical form, language, and datatype."""

    lexical_form: str
    language_tag: str | None
    datatype_iri: str | None


@dataclass(frozen=True, slots=True)
class AgrovocConcept:
    """One AGROVOC ``skos:Concept`` and its scheme membership."""

    concept_iri: str
    scheme_iris: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AgrovocConceptScheme:
    """One source ``skos:ConceptScheme``."""

    scheme_iri: str


@dataclass(frozen=True, slots=True)
class AgrovocLabelExpression:
    """One authored SKOS label assertion."""

    subject_iri: str
    property_iri: str
    role: AgrovocLabelRole
    value: AgrovocLiteral


@dataclass(frozen=True, slots=True)
class AgrovocNote:
    """One SKOS note assertion."""

    subject_iri: str
    property_iri: str
    value: AgrovocLiteral


@dataclass(frozen=True, slots=True)
class AgrovocNotation:
    """One SKOS notation with its required absolute datatype IRI."""

    subject_iri: str
    property_iri: str
    value: AgrovocLiteral


@dataclass(frozen=True, slots=True)
class AgrovocIriRelation:
    """One RDF assertion whose subject and object remain exact source IRIs.

    Used for both SKOS hierarchy/associative relations and SKOS mapping
    relations. It never becomes one merged identifier: the subject, the
    predicate, and the object stay three separate fields.
    """

    subject_iri: str
    predicate_iri: str
    object_iri: str


@dataclass(frozen=True, slots=True)
class AgrovocMetadataLiteral:
    """One authored ``dct:created``/``dct:modified`` literal assertion."""

    subject_iri: str
    property_iri: str
    value: AgrovocLiteral


@dataclass(frozen=True, slots=True)
class AgrovocPredicateCount:
    """An observed predicate count used to make import coverage explicit."""

    predicate_iri: str
    assertion_count: int


@dataclass(frozen=True, slots=True)
class AgrovocImportCounts:
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
    mapping_relations: int
    metadata_literals: int


@dataclass(frozen=True, slots=True)
class AgrovocMappingSource:
    """Deterministic parsed view of one exact AGROVOC Turtle payload.

    This is a mapping-source package, not a promoted concept scheme: callers
    that need document subjects use NALT (or another subject module)
    directly and consult this package only for crosswalk and multilingual
    label expansion.
    """

    source_url: str
    source_sha256: str
    source_bytes: int
    triple_count: int
    source_iris: tuple[str, ...]
    predicate_counts: tuple[AgrovocPredicateCount, ...]
    concepts: tuple[AgrovocConcept, ...]
    concept_schemes: tuple[AgrovocConceptScheme, ...]
    labels: tuple[AgrovocLabelExpression, ...]
    notes: tuple[AgrovocNote, ...]
    notations: tuple[AgrovocNotation, ...]
    semantic_relations: tuple[AgrovocIriRelation, ...]
    mapping_relations: tuple[AgrovocIriRelation, ...]
    metadata_literals: tuple[AgrovocMetadataLiteral, ...]

    @property
    def counts(self) -> AgrovocImportCounts:
        labels = Counter(item.role for item in self.labels)
        semantics = Counter(item.predicate_iri for item in self.semantic_relations)
        return AgrovocImportCounts(
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
            mapping_relations=len(self.mapping_relations),
            metadata_literals=len(self.metadata_literals),
        )

    @property
    def nalt_crosswalk_relations(self) -> tuple[AgrovocIriRelation, ...]:
        """Mapping relations whose object falls in the NALT namespace.

        This is read-only crosswalk evidence for NALT-backed subjects. It
        does not join, merge, or mint any identifier shared with NALT.
        """

        return tuple(
            relation
            for relation in self.mapping_relations
            if any(relation.object_iri.startswith(prefix) for prefix in NALT_IRI_PREFIXES)
        )


def _require_absolute_iri(value: str, label: str) -> str:
    if not urllib.parse.urlsplit(value).scheme:
        raise AgrovocParseError(f"{label} must be an absolute IRI, got {value!r}")
    return value


def _require_not_nalt_namespaced(value: str, label: str) -> str:
    if any(value.startswith(prefix) for prefix in NALT_IRI_PREFIXES):
        raise AgrovocParseError(
            f"{label} {value!r} must not mint an AGROVOC identity inside the NALT namespace; "
            "AGROVOC and NALT IRIs stay authoritative and separate"
        )
    return value


def _iri(term: Identifier, label: str) -> str:
    if not isinstance(term, URIRef):
        kind = "blank node" if isinstance(term, BNode) else type(term).__name__
        raise AgrovocParseError(f"{label} must be an IRI, got {kind}")
    return _require_absolute_iri(str(term), label)


def _literal(term: Identifier, label: str) -> AgrovocLiteral:
    if not isinstance(term, Literal):
        raise AgrovocParseError(f"{label} must be an RDF literal")
    language_tag = str(term.language) if term.language is not None else None
    datatype_iri = str(term.datatype) if term.datatype is not None else None
    if datatype_iri is not None:
        _require_absolute_iri(datatype_iri, f"{label} datatype")
    return AgrovocLiteral(
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
        raise AgrovocParseError(f"AGROVOC Turtle is not valid UTF-8 at byte {error.start}") from error
    return payload


def _reject_identity_merging_assertions(graph: Graph) -> None:
    for subject, _, obj in graph.triples((None, OWL.sameAs, None)):
        subject_display = str(subject) if isinstance(subject, URIRef) else repr(subject)
        object_display = str(obj) if isinstance(obj, URIRef) else repr(obj)
        raise AgrovocParseError(
            f"owl:sameAs ({subject_display} -> {object_display}) would merge AGROVOC identity with "
            "another scheme; this mapping source keeps identifiers separate"
        )


def _label_expressions(graph: Graph) -> tuple[AgrovocLabelExpression, ...]:
    properties: tuple[tuple[URIRef, AgrovocLabelRole], ...] = (
        (SKOS.prefLabel, "preferred"),
        (SKOS.altLabel, "alternate"),
        (SKOS.hiddenLabel, "hidden"),
    )
    labels: list[AgrovocLabelExpression] = []
    preferred_by_language: dict[tuple[str, str], str] = {}
    for predicate, role in properties:
        for subject, value in graph.subject_objects(predicate):
            subject_iri = _iri(subject, f"{role} label subject")
            literal = _literal(value, f"{role} label")
            if literal.language_tag is None:
                raise AgrovocParseError(
                    f"{role} label on {subject_iri} is untagged; AGROVOC labels must retain a language tag"
                )
            if role == "preferred":
                key = (subject_iri, literal.language_tag.casefold())
                previous = preferred_by_language.get(key)
                if previous is not None and previous != literal.lexical_form:
                    raise AgrovocParseError(
                        f"{subject_iri} has more than one preferred label for language {literal.language_tag}"
                    )
                preferred_by_language[key] = literal.lexical_form
            labels.append(
                AgrovocLabelExpression(
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


def _notes(graph: Graph) -> tuple[AgrovocNote, ...]:
    notes: list[AgrovocNote] = []
    for predicate_iri in NOTE_PREDICATE_IRIS:
        predicate = URIRef(predicate_iri)
        for subject, value in graph.subject_objects(predicate):
            notes.append(
                AgrovocNote(
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


def _notations(graph: Graph) -> tuple[AgrovocNotation, ...]:
    notations: list[AgrovocNotation] = []
    for subject, value in graph.subject_objects(SKOS.notation):
        subject_iri = _iri(subject, "notation subject")
        literal = _literal(value, "notation")
        if literal.language_tag is not None or literal.datatype_iri is None:
            raise AgrovocParseError(f"notation on {subject_iri} must be a typed literal with an absolute datatype IRI")
        notations.append(
            AgrovocNotation(
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
) -> tuple[AgrovocIriRelation, ...]:
    relations: list[AgrovocIriRelation] = []
    for predicate_iri in predicate_iris:
        for subject, object_ in graph.subject_objects(URIRef(predicate_iri)):
            relations.append(
                AgrovocIriRelation(
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


def _concepts(graph: Graph) -> tuple[AgrovocConcept, ...]:
    concepts: list[AgrovocConcept] = []
    for subject in set(graph.subjects(RDF.type, SKOS.Concept)):
        concept_iri = _iri(subject, "concept")
        _require_not_nalt_namespaced(concept_iri, "concept")
        schemes = tuple(sorted(_iri(item, "skos:inScheme object") for item in graph.objects(subject, SKOS.inScheme)))
        concepts.append(
            AgrovocConcept(
                concept_iri=concept_iri,
                scheme_iris=schemes,
            )
        )
    return tuple(sorted(concepts, key=lambda item: item.concept_iri))


def _concept_schemes(graph: Graph) -> tuple[AgrovocConceptScheme, ...]:
    schemes: list[AgrovocConceptScheme] = []
    for subject in set(graph.subjects(RDF.type, SKOS.ConceptScheme)):
        scheme_iri = _iri(subject, "concept scheme")
        _require_not_nalt_namespaced(scheme_iri, "concept scheme")
        schemes.append(AgrovocConceptScheme(scheme_iri=scheme_iri))
    return tuple(sorted(schemes, key=lambda item: item.scheme_iri))


def _metadata_literals(graph: Graph) -> tuple[AgrovocMetadataLiteral, ...]:
    assertions: list[AgrovocMetadataLiteral] = []
    for predicate_iri in AGROVOC_METADATA_LITERAL_PREDICATE_IRIS:
        for subject, value in graph.subject_objects(URIRef(predicate_iri)):
            assertions.append(
                AgrovocMetadataLiteral(
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


def parse_agrovoc_turtle(
    source: str | bytes,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> AgrovocMappingSource:
    """Parse one AGROVOC Turtle payload into deterministic, lossless feature rows.

    The result is a mapping-source package: it captures AGROVOC's own
    concepts, labels, and mapping-relation crosswalks faithfully, and it
    refuses (via ``AgrovocParseError``) any assertion that would merge an
    AGROVOC concept identity with a NALT identity.
    """

    _require_absolute_iri(source_url, "source_url")
    payload = _source_payload(source)
    source_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None:
        if _DIGEST.fullmatch(expected_sha256) is None:
            raise AgrovocParseError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if source_sha256 != expected_sha256:
            raise AgrovocParseError(f"source digest mismatch: expected {expected_sha256}, got {source_sha256}")
    if expected_byte_length is not None:
        if expected_byte_length <= 0:
            raise AgrovocParseError("expected_byte_length must be positive")
        if len(payload) != expected_byte_length:
            raise AgrovocParseError(f"source byte length mismatch: expected {expected_byte_length}, got {len(payload)}")

    graph = Graph()
    try:
        _parse_lossless_turtle(
            graph,
            payload,
            source_url=source_url,
        )
    except Exception as error:
        raise AgrovocParseError(f"could not parse AGROVOC Turtle: {error}") from error

    _reject_identity_merging_assertions(graph)

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

    return AgrovocMappingSource(
        source_url=source_url,
        source_sha256=source_sha256,
        source_bytes=len(payload),
        triple_count=len(graph),
        source_iris=source_iris,
        predicate_counts=tuple(
            AgrovocPredicateCount(predicate_iri=predicate, assertion_count=count)
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
        metadata_literals=_metadata_literals(graph),
    )


def parse_agrovoc_file(
    path: Path,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> AgrovocMappingSource:
    """Parse one local Turtle file while retaining its external source identity."""

    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise AgrovocParseError(f"AGROVOC source is not a regular file: {source_path}")
    return parse_agrovoc_turtle(
        source_path.read_bytes(),
        source_url=source_url,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )


def _expected_hex(expected_sha256: str) -> str:
    try:
        return expected_digest_hex(expected_sha256)
    except PinnedAcquisitionError as error:
        raise AgrovocAcquisitionError(str(error)) from error


_AGROVOC_ACQUIRE_LABELS = PinnedAcquisitionLabels(
    source_label="AGROVOC source",
    cached_location="cached AGROVOC source",
    local_file_label="local AGROVOC source",
    not_cached_message=(
        "AGROVOC source is not cached; provide source_path or set allow_network=True explicitly"
    ),
    request_headers={
        "User-Agent": "RefSpec explicit AGROVOC source resolver/1.0",
        "Accept": "text/turtle",
    },
)


def _validate_source_url(source_url: str) -> None:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgrovocAcquisitionError("source_url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise AgrovocAcquisitionError("source_url must not contain credentials")


def _require_absolute_iri_for_acquisition(value: str, label: str) -> None:
    if not urllib.parse.urlsplit(value).scheme:
        raise AgrovocAcquisitionError(f"{label} must be an absolute IRI")


def _require_not_nalt_namespaced_for_acquisition(value: str, label: str) -> None:
    if any(value.startswith(prefix) for prefix in NALT_IRI_PREFIXES):
        raise AgrovocAcquisitionError(
            f"{label} {value!r} must not sit inside the NALT namespace; AGROVOC and NALT IRIs stay separate"
        )


@dataclass(frozen=True, slots=True)
class AgrovocSampleSource:
    """One exact, externally published AGROVOC Turtle concept export.

    AGROVOC concept IRIs are stable and are not versioned per release the
    way ELSST's ``/id/<version>/`` IRIs are; ``dct:modified`` can change
    between fetches, so this pins one exact captured export rather than a
    dated bulk release.
    """

    label: str
    concept_iri: str
    scheme_iri: str
    source_url: str
    expected_sha256: str
    expected_byte_length: int
    filename: str
    publisher: str = AGROVOC_PUBLISHER
    attribution: str = AGROVOC_ATTRIBUTION
    license_iri: str = AGROVOC_LICENSE_IRI
    license_label: str = AGROVOC_LICENSE_LABEL

    def __post_init__(self) -> None:
        if not self.label:
            raise AgrovocAcquisitionError("label must not be empty")
        _require_absolute_iri_for_acquisition(self.concept_iri, "concept_iri")
        _require_not_nalt_namespaced_for_acquisition(self.concept_iri, "concept_iri")
        _require_absolute_iri_for_acquisition(self.scheme_iri, "scheme_iri")
        _require_not_nalt_namespaced_for_acquisition(self.scheme_iri, "scheme_iri")
        _validate_source_url(self.source_url)
        _expected_hex(self.expected_sha256)
        if self.expected_byte_length <= 0:
            raise AgrovocAcquisitionError("expected_byte_length must be positive")
        if not self.filename or Path(self.filename).name != self.filename:
            raise AgrovocAcquisitionError("filename must be one plain path component")
        _require_absolute_iri_for_acquisition(self.license_iri, "license_iri")
        if not self.publisher or not self.attribution or not self.license_label:
            raise AgrovocAcquisitionError("publisher, attribution, and license_label must not be empty")


# A real concept export captured 2026-08-03 from
# https://aims.fao.org/aos/agrovoc/c_330.ttl. Its skos:exactMatch to
# https://lod.nal.usda.gov/nalt/71469 is genuine, published AGROVOC-to-NALT
# crosswalk evidence, kept as a plain mapping row (see
# ``AgrovocMappingSource.nalt_crosswalk_relations``).
AGROVOC_C330_SAMPLE = AgrovocSampleSource(
    label="c_330-2026-08-03",
    concept_iri="http://aims.fao.org/aos/agrovoc/c_330",
    scheme_iri=AGROVOC_SCHEME_IRI,
    source_url="https://aims.fao.org/aos/agrovoc/c_330.ttl",
    expected_sha256="sha256:6e66080437622f9ccff470ec930203ca125e3c1e778df9f43a3fe4d78d98df15",
    expected_byte_length=5338,
    filename="agrovoc-c330-sample.ttl",
)
AGROVOC_SAMPLES = {AGROVOC_C330_SAMPLE.label: AGROVOC_C330_SAMPLE}


@dataclass(frozen=True, slots=True)
class AcquiredAgrovocSample:
    """One verified AGROVOC object in a content-addressed local store."""

    sample: AgrovocSampleSource
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    cache_hit: bool
    acquisition_mode: AcquisitionMode
    local_source_path: Path | None


def _as_acquired_agrovoc(sample: AgrovocSampleSource, acquired: AcquiredPinnedSource) -> AcquiredAgrovocSample:
    return AcquiredAgrovocSample(
        sample=sample,
        path=acquired.path,
        source_url=acquired.source_url,
        resolved_url=acquired.resolved_url,
        sha256=acquired.sha256,
        byte_length=acquired.byte_length,
        cache_hit=acquired.cache_hit,
        acquisition_mode=acquired.acquisition_mode,
        local_source_path=acquired.local_source_path,
    )


def acquire_agrovoc_sample(
    sample: AgrovocSampleSource,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    allow_network: bool = False,
    timeout_seconds: float = 60.0,
) -> AcquiredAgrovocSample:
    """Resolve one pinned AGROVOC sample from cache, a local file, or the network.

    Importing this module never opens a network connection. Cache lookup is
    always local. A supplied ``source_path`` is read locally. Otherwise, a
    cache miss fails unless ``allow_network`` is explicitly true. Every path
    is subject to the sample's exact byte-length and digest pins.
    """

    try:
        acquired = acquire_pinned_source(
            sample,
            store_dir,
            labels=_AGROVOC_ACQUIRE_LABELS,
            source_path=source_path,
            allow_network=allow_network,
            timeout_seconds=timeout_seconds,
        )
    except PinnedAcquisitionError as error:
        raise AgrovocAcquisitionError(str(error)) from error
    return _as_acquired_agrovoc(sample, acquired)


def parse_acquired_agrovoc_sample(acquired: AcquiredAgrovocSample) -> AgrovocMappingSource:
    """Reverify and parse an object returned by the AGROVOC acquisition adapter."""

    if acquired.path.is_symlink() or not acquired.path.is_file():
        raise AgrovocParseError(f"acquired AGROVOC source is not a regular file: {acquired.path}")
    parsed = parse_agrovoc_turtle(
        acquired.path.read_bytes(),
        source_url=acquired.sample.source_url,
        expected_sha256=acquired.sample.expected_sha256,
        expected_byte_length=acquired.sample.expected_byte_length,
    )
    concept_iris = {item.concept_iri for item in parsed.concepts}
    if acquired.sample.concept_iri not in concept_iris:
        raise AgrovocParseError(
            f"pinned AGROVOC concept {acquired.sample.concept_iri} is absent from the distribution"
        )
    concept = next(item for item in parsed.concepts if item.concept_iri == acquired.sample.concept_iri)
    if acquired.sample.scheme_iri not in concept.scheme_iris:
        raise AgrovocParseError(
            f"pinned AGROVOC concept scheme {acquired.sample.scheme_iri} is absent from the concept's schemes"
        )
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Acquire one exact AGROVOC Turtle sample into a content-addressed local store."
    )
    parser.add_argument("sample", choices=tuple(AGROVOC_SAMPLES))
    parser.add_argument("store", type=Path)
    parser.add_argument("--source-path", type=Path)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        acquired = acquire_agrovoc_sample(
            AGROVOC_SAMPLES[args.sample],
            args.store,
            source_path=args.source_path,
            allow_network=args.allow_network,
            timeout_seconds=args.timeout_seconds,
        )
    except AgrovocAcquisitionError as error:
        parser.error(str(error))
    print(acquired.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
