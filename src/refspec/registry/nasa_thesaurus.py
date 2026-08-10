"""Lossless RDF/XML reader and acquisition for the pinned NASA Thesaurus SKOS distribution.

The NASA Thesaurus SKOS/RDF distribution is RDF/XML, not Turtle, and every
concept, relation-edge, and term-note identifier the source assigns is a
same-document numeric fragment (for example ``#37801``), resolved against the
document's own download URL. The publisher supplies no externally minted
concept IRI and no ``skos:ConceptScheme`` resource; this module does not
invent one.

RDF/XML gives an ``rdf:ID`` on a property element (used here for every
``skos:broader``/``narrower``/``related`` and ``skm:UF``/``skm:Use`` edge, and
every ``zthes:termNote``) an automatic reification -- ``rdf:type
rdf:Statement`` plus ``rdf:subject``/``rdf:predicate``/``rdf:object`` -- that
resolves against the base with a leading ``#``. The document's own
``<rdf:Description rdf:about="...">`` blocks that carry the real
``zthes:label`` definition/scope-note text and ``zthes:weight`` edge weight
reuse the *identical local string*, but without a leading ``#``, which
resolves as a same-level relative path segment, not a fragment. Verified
against the full published distribution, these two id spaces never collide.
This module preserves both sets of assertions exactly as given and does not
synthesize a link between a term note or relation edge and its detached
annotation literal by string-matching local ids; that would mint an
association the source RDF itself does not assert.

Importing this module never opens a network connection. A caller must either
supply an existing local distribution or set ``allow_network=True``, and in
both cases RefSpec verifies the exact published byte length and SHA-256
digest before making the object visible in the content-addressed store.

The source states no explicit reuse license for the Thesaurus data files; it
states only a citation/attribution request. That attribution requirement is
retained as source metadata; it does not act as a runtime authorization gate.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import urllib.parse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal as LiteralType

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS
from rdflib.term import Identifier

from refspec.registry.infrastructure.pinned_acquisition import (
    AcquiredPinnedSource,
    AcquisitionMode,
    PinnedAcquisitionError,
    PinnedAcquisitionLabels,
    acquire_pinned_source,
    expected_digest_hex,
)

SKOS_PREF_LABEL_PREDICATE_IRI = str(SKOS.prefLabel)
SKOS_ALT_LABEL_PREDICATE_IRI = str(SKOS.altLabel)
SKOS_BROADER_PREDICATE_IRI = str(SKOS.broader)
SKOS_NARROWER_PREDICATE_IRI = str(SKOS.narrower)
SKOS_RELATED_PREDICATE_IRI = str(SKOS.related)

# ZThes and SKM ("Synaptica Knowledge Manager") are not W3C vocabularies and
# have no rdflib.namespace entry; the source document itself declares these
# two namespace IRIs on its root element.
ZTHES_NAMESPACE_IRI = "http://synaptica.net/zthes/"
SKM_NAMESPACE_IRI = "http://synaptica.net/skm/"

TERM_ID_PREDICATE_IRI = ZTHES_NAMESPACE_IRI + "termID"
TERM_VOCABULARY_PREDICATE_IRI = ZTHES_NAMESPACE_IRI + "termVocabulary"
TERM_NOTE_PREDICATE_IRI = ZTHES_NAMESPACE_IRI + "termNote"
LABEL_ANNOTATION_PREDICATE_IRI = ZTHES_NAMESPACE_IRI + "label"
WEIGHT_ANNOTATION_PREDICATE_IRI = ZTHES_NAMESPACE_IRI + "weight"
TERM_UPDATE_PREDICATE_IRI = SKM_NAMESPACE_IRI + "termUpdate"
USED_FOR_PREDICATE_IRI = SKM_NAMESPACE_IRI + "UF"
USE_INSTEAD_PREDICATE_IRI = SKM_NAMESPACE_IRI + "Use"

HIERARCHY_PREDICATE_IRIS = (
    SKOS_BROADER_PREDICATE_IRI,
    SKOS_NARROWER_PREDICATE_IRI,
    SKOS_RELATED_PREDICATE_IRI,
)
USE_REFERENCE_PREDICATE_IRIS = (USED_FOR_PREDICATE_IRI, USE_INSTEAD_PREDICATE_IRI)
METADATA_LITERAL_PREDICATE_IRIS = (
    TERM_ID_PREDICATE_IRI,
    TERM_VOCABULARY_PREDICATE_IRI,
    TERM_UPDATE_PREDICATE_IRI,
)
ANNOTATION_LITERAL_PREDICATE_IRIS = (LABEL_ANNOTATION_PREDICATE_IRI, WEIGHT_ANNOTATION_PREDICATE_IRI)

# Verified against the full 2026-04-24 SKOS distribution: every zthes:termNote
# inline literal is one of exactly these three fixed marker strings, never the
# note's own text.
KNOWN_TERM_NOTE_MARKERS = ("Definition", "Definition Source", "Scope Note")

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_CONTENT_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Deliberately narrower than refspec.registry.infrastructure
# .source_controlled_resource.LabelRole: this reader only ever emits
# skos:prefLabel/skos:altLabel assertions (see SKOS_PREF_LABEL_PREDICATE_IRI
# / SKOS_ALT_LABEL_PREDICATE_IRI above); the NASA Thesaurus source never
# supplies a skos:hiddenLabel this module reads, so "hidden" is not a value
# this type should accept.
NasaThesaurusLabelRole = LiteralType["preferred", "alternate"]


class NasaThesaurusParseError(ValueError):
    """A NASA Thesaurus RDF/XML feature cannot be preserved without guessing."""


class NasaThesaurusAcquisitionError(ValueError):
    """A NASA Thesaurus source could not be acquired without weakening its pin."""


def _require_absolute_iri(value: str, label: str) -> str:
    if not urllib.parse.urlsplit(value).scheme:
        raise NasaThesaurusParseError(f"{label} must be an absolute IRI, got {value!r}")
    return value


def _iri(term: Identifier, label: str) -> str:
    if not isinstance(term, URIRef):
        kind = "blank node" if isinstance(term, BNode) else type(term).__name__
        raise NasaThesaurusParseError(f"{label} must be an IRI, got {kind}")
    return _require_absolute_iri(str(term), label)


@dataclass(frozen=True, slots=True)
class NasaThesaurusLiteral:
    """One RDF literal with its lexical form, language, and datatype."""

    lexical_form: str
    language_tag: str | None
    datatype_iri: str | None


def _literal(term: Identifier, label: str) -> NasaThesaurusLiteral:
    if not isinstance(term, Literal):
        raise NasaThesaurusParseError(f"{label} must be an RDF literal")
    language_tag = str(term.language) if term.language is not None else None
    datatype_iri = str(term.datatype) if term.datatype is not None else None
    if datatype_iri is not None:
        _require_absolute_iri(datatype_iri, f"{label} datatype")
    return NasaThesaurusLiteral(
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
        raise NasaThesaurusParseError(f"NASA Thesaurus RDF/XML is not valid UTF-8 at byte {error.start}") from error
    return payload


@dataclass(frozen=True, slots=True)
class NasaThesaurusConcept:
    """One ``skos:Concept`` from the source. No scheme is asserted or minted."""

    concept_iri: str


@dataclass(frozen=True, slots=True)
class NasaThesaurusLabelExpression:
    """One authored ``skos:prefLabel`` or ``skos:altLabel`` assertion."""

    subject_iri: str
    property_iri: str
    role: NasaThesaurusLabelRole
    value: NasaThesaurusLiteral


@dataclass(frozen=True, slots=True)
class NasaThesaurusNote:
    """One ``zthes:termNote`` assertion. The value is a note-kind marker, not
    the note's own text -- see the module docstring for where the real text
    lives and why it is not joined here."""

    subject_iri: str
    property_iri: str
    value: NasaThesaurusLiteral


@dataclass(frozen=True, slots=True)
class NasaThesaurusIriRelation:
    """One RDF assertion whose subject and object remain exact source IRIs."""

    subject_iri: str
    predicate_iri: str
    object_iri: str


@dataclass(frozen=True, slots=True)
class NasaThesaurusMetadataLiteral:
    """One authored source-native identifier or vocabulary/update literal."""

    subject_iri: str
    property_iri: str
    value: NasaThesaurusLiteral


@dataclass(frozen=True, slots=True)
class NasaThesaurusAnnotationLiteral:
    """One detached ``zthes:label``/``zthes:weight`` annotation literal.

    Its subject is its own resolved IRI. RefSpec does not assert this
    resource is the same as, or linked to, any concept or relation edge; the
    source RDF itself makes no such assertion (see module docstring).
    """

    subject_iri: str
    property_iri: str
    value: NasaThesaurusLiteral


@dataclass(frozen=True, slots=True)
class NasaThesaurusImportCounts:
    """Feature counts for regression and import-coverage checks."""

    source_bytes: int
    triples: int
    source_iris: int
    concepts: int
    preferred_labels: int
    alternate_labels: int
    notes: int
    broader_relations: int
    narrower_relations: int
    related_relations: int
    used_for_relations: int
    use_relations: int
    term_id_assertions: int
    term_vocabulary_assertions: int
    term_update_assertions: int
    label_annotations: int
    weight_annotations: int


@dataclass(frozen=True, slots=True)
class NasaThesaurusPredicateCount:
    """An observed predicate count used to make import coverage explicit."""

    predicate_iri: str
    assertion_count: int


@dataclass(frozen=True, slots=True)
class NasaThesaurusVocabulary:
    """Deterministic parsed view of one exact NASA Thesaurus RDF/XML payload."""

    source_url: str
    source_sha256: str
    source_bytes: int
    triple_count: int
    source_iris: tuple[str, ...]
    predicate_counts: tuple[NasaThesaurusPredicateCount, ...]
    concepts: tuple[NasaThesaurusConcept, ...]
    labels: tuple[NasaThesaurusLabelExpression, ...]
    notes: tuple[NasaThesaurusNote, ...]
    semantic_relations: tuple[NasaThesaurusIriRelation, ...]
    use_reference_relations: tuple[NasaThesaurusIriRelation, ...]
    metadata_literals: tuple[NasaThesaurusMetadataLiteral, ...]
    annotation_literals: tuple[NasaThesaurusAnnotationLiteral, ...]

    @property
    def counts(self) -> NasaThesaurusImportCounts:
        labels = Counter(item.role for item in self.labels)
        semantics = Counter(item.predicate_iri for item in self.semantic_relations)
        use_references = Counter(item.predicate_iri for item in self.use_reference_relations)
        metadata = Counter(item.property_iri for item in self.metadata_literals)
        annotations = Counter(item.property_iri for item in self.annotation_literals)
        return NasaThesaurusImportCounts(
            source_bytes=self.source_bytes,
            triples=self.triple_count,
            source_iris=len(self.source_iris),
            concepts=len(self.concepts),
            preferred_labels=labels["preferred"],
            alternate_labels=labels["alternate"],
            notes=len(self.notes),
            broader_relations=semantics[SKOS_BROADER_PREDICATE_IRI],
            narrower_relations=semantics[SKOS_NARROWER_PREDICATE_IRI],
            related_relations=semantics[SKOS_RELATED_PREDICATE_IRI],
            used_for_relations=use_references[USED_FOR_PREDICATE_IRI],
            use_relations=use_references[USE_INSTEAD_PREDICATE_IRI],
            term_id_assertions=metadata[TERM_ID_PREDICATE_IRI],
            term_vocabulary_assertions=metadata[TERM_VOCABULARY_PREDICATE_IRI],
            term_update_assertions=metadata[TERM_UPDATE_PREDICATE_IRI],
            label_annotations=annotations[LABEL_ANNOTATION_PREDICATE_IRI],
            weight_annotations=annotations[WEIGHT_ANNOTATION_PREDICATE_IRI],
        )


def _label_expressions(graph: Graph) -> tuple[NasaThesaurusLabelExpression, ...]:
    properties: tuple[tuple[URIRef, NasaThesaurusLabelRole], ...] = (
        (SKOS.prefLabel, "preferred"),
        (SKOS.altLabel, "alternate"),
    )
    labels: list[NasaThesaurusLabelExpression] = []
    for predicate, role in properties:
        for subject, value in graph.subject_objects(predicate):
            labels.append(
                NasaThesaurusLabelExpression(
                    subject_iri=_iri(subject, f"{role} label subject"),
                    property_iri=str(predicate),
                    role=role,
                    value=_literal(value, f"{role} label"),
                )
            )
    return tuple(
        sorted(
            labels,
            key=lambda item: (
                item.subject_iri,
                item.property_iri,
                item.value.lexical_form,
            ),
        )
    )


def _concepts(
    graph: Graph,
    labels: tuple[NasaThesaurusLabelExpression, ...],
) -> tuple[NasaThesaurusConcept, ...]:
    preferred_count = Counter(item.subject_iri for item in labels if item.role == "preferred")
    concepts: list[NasaThesaurusConcept] = []
    for subject in set(graph.subjects(RDF.type, SKOS.Concept)):
        concept_iri = _iri(subject, "concept")
        count = preferred_count.get(concept_iri, 0)
        if count != 1:
            raise NasaThesaurusParseError(
                f"{concept_iri} has {count} skos:prefLabel assertions; exactly one is required"
            )
        concepts.append(NasaThesaurusConcept(concept_iri=concept_iri))
    return tuple(sorted(concepts, key=lambda item: item.concept_iri))


def _notes(graph: Graph) -> tuple[NasaThesaurusNote, ...]:
    notes: list[NasaThesaurusNote] = []
    for subject, value in graph.subject_objects(URIRef(TERM_NOTE_PREDICATE_IRI)):
        subject_iri = _iri(subject, "term note subject")
        literal = _literal(value, "term note value")
        if literal.lexical_form not in KNOWN_TERM_NOTE_MARKERS:
            raise NasaThesaurusParseError(
                f"{subject_iri} has an unrecognized zthes:termNote marker {literal.lexical_form!r}; "
                f"expected one of {KNOWN_TERM_NOTE_MARKERS}"
            )
        notes.append(NasaThesaurusNote(subject_iri=subject_iri, property_iri=TERM_NOTE_PREDICATE_IRI, value=literal))
    return tuple(sorted(notes, key=lambda item: (item.subject_iri, item.value.lexical_form)))


def _iri_relations(
    graph: Graph,
    predicate_iris: tuple[str, ...],
    *,
    label: str,
) -> tuple[NasaThesaurusIriRelation, ...]:
    relations: list[NasaThesaurusIriRelation] = []
    for predicate_iri in predicate_iris:
        for subject, object_ in graph.subject_objects(URIRef(predicate_iri)):
            relations.append(
                NasaThesaurusIriRelation(
                    subject_iri=_iri(subject, f"{label} subject"),
                    predicate_iri=predicate_iri,
                    object_iri=_iri(object_, f"{label} object"),
                )
            )
    return tuple(sorted(relations, key=lambda item: (item.subject_iri, item.predicate_iri, item.object_iri)))


def _metadata_literals(graph: Graph) -> tuple[NasaThesaurusMetadataLiteral, ...]:
    assertions: list[NasaThesaurusMetadataLiteral] = []
    for predicate_iri in METADATA_LITERAL_PREDICATE_IRIS:
        for subject, value in graph.subject_objects(URIRef(predicate_iri)):
            assertions.append(
                NasaThesaurusMetadataLiteral(
                    subject_iri=_iri(subject, f"{predicate_iri} subject"),
                    property_iri=predicate_iri,
                    value=_literal(value, f"{predicate_iri} value"),
                )
            )
    return tuple(
        sorted(
            assertions,
            key=lambda item: (item.subject_iri, item.property_iri, item.value.lexical_form),
        )
    )


def _annotation_literals(graph: Graph) -> tuple[NasaThesaurusAnnotationLiteral, ...]:
    assertions: list[NasaThesaurusAnnotationLiteral] = []
    for predicate_iri in ANNOTATION_LITERAL_PREDICATE_IRIS:
        for subject, value in graph.subject_objects(URIRef(predicate_iri)):
            assertions.append(
                NasaThesaurusAnnotationLiteral(
                    subject_iri=_iri(subject, f"{predicate_iri} subject"),
                    property_iri=predicate_iri,
                    value=_literal(value, f"{predicate_iri} value"),
                )
            )
    return tuple(
        sorted(
            assertions,
            key=lambda item: (item.subject_iri, item.property_iri, item.value.lexical_form),
        )
    )


def parse_nasa_thesaurus_xml(
    source: str | bytes,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> NasaThesaurusVocabulary:
    """Parse one exact NASA Thesaurus RDF/XML payload into deterministic rows."""

    _require_absolute_iri(source_url, "source_url")
    payload = _source_payload(source)
    source_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None:
        if _DIGEST.fullmatch(expected_sha256) is None:
            raise NasaThesaurusParseError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if source_sha256 != expected_sha256:
            raise NasaThesaurusParseError(f"source digest mismatch: expected {expected_sha256}, got {source_sha256}")
    if expected_byte_length is not None:
        if expected_byte_length <= 0:
            raise NasaThesaurusParseError("expected_byte_length must be positive")
        if len(payload) != expected_byte_length:
            raise NasaThesaurusParseError(
                f"source byte length mismatch: expected {expected_byte_length}, got {len(payload)}"
            )

    graph = Graph()
    try:
        graph.parse(data=payload, format="xml", publicID=source_url)
    except Exception as error:
        raise NasaThesaurusParseError(f"could not parse NASA Thesaurus RDF/XML: {error}") from error

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

    labels = _label_expressions(graph)
    return NasaThesaurusVocabulary(
        source_url=source_url,
        source_sha256=source_sha256,
        source_bytes=len(payload),
        triple_count=len(graph),
        source_iris=source_iris,
        predicate_counts=tuple(
            NasaThesaurusPredicateCount(predicate_iri=predicate, assertion_count=count)
            for predicate, count in sorted(predicate_counts.items())
        ),
        concepts=_concepts(graph, labels),
        labels=labels,
        notes=_notes(graph),
        semantic_relations=_iri_relations(graph, HIERARCHY_PREDICATE_IRIS, label="SKOS semantic relation"),
        use_reference_relations=_iri_relations(graph, USE_REFERENCE_PREDICATE_IRIS, label="USE cross-reference"),
        metadata_literals=_metadata_literals(graph),
        annotation_literals=_annotation_literals(graph),
    )


def parse_nasa_thesaurus_file(
    path: Path,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> NasaThesaurusVocabulary:
    """Parse one local RDF/XML file while retaining its external source identity."""

    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise NasaThesaurusParseError(f"NASA Thesaurus source is not a regular file: {source_path}")
    return parse_nasa_thesaurus_xml(
        source_path.read_bytes(),
        source_url=source_url,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )


# --- Acquisition -----------------------------------------------------------
#
# The source page (https://sti.nasa.gov/nasa-thesaurus/) states no explicit
# reuse license for the Thesaurus data files. It states a citation request
# ("Please cite the NASA STI Program...") with APA/MLA/Chicago examples that
# all use citation year 2012, while the binary distributions themselves carry
# an HTTP Last-Modified date that can be newer than that citation year -- the
# two dates are retained separately below and must not be conflated.


def _expected_hex(expected_sha256: str) -> str:
    try:
        return expected_digest_hex(expected_sha256)
    except PinnedAcquisitionError as error:
        raise NasaThesaurusAcquisitionError(str(error)) from error


_NASA_THESAURUS_ACQUIRE_LABELS = PinnedAcquisitionLabels(
    source_label="NASA Thesaurus source",
    cached_location="cached NASA Thesaurus source",
    local_file_label="local NASA Thesaurus source",
    not_cached_message=(
        "NASA Thesaurus source is not cached; provide source_path or set allow_network=True explicitly"
    ),
    request_headers={"User-Agent": "RefSpec explicit NASA Thesaurus source resolver/1.0"},
)


def _validate_source_url(source_url: str) -> None:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NasaThesaurusAcquisitionError("source_url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise NasaThesaurusAcquisitionError("source_url must not contain credentials")


@dataclass(frozen=True, slots=True)
class NasaThesaurusReleaseSource:
    """One exact, externally published NASA Thesaurus distribution file."""

    format_name: str
    source_url: str
    expected_sha256: str
    expected_byte_length: int
    filename: str
    content_last_modified: str
    citation_year: int
    citation_apa: str
    citation_mla: str
    citation_chicago: str
    attribution_requirement: str
    source_page_url: str
    publisher: str = "NASA STI Program"
    attribution_organization: str = "National Aeronautics and Space Administration"

    def __post_init__(self) -> None:
        if not self.format_name:
            raise NasaThesaurusAcquisitionError("format_name must not be empty")
        _validate_source_url(self.source_url)
        _expected_hex(self.expected_sha256)
        if self.expected_byte_length <= 0:
            raise NasaThesaurusAcquisitionError("expected_byte_length must be positive")
        if not self.filename or Path(self.filename).name != self.filename:
            raise NasaThesaurusAcquisitionError("filename must be one plain path component")
        if _CONTENT_DATE.fullmatch(self.content_last_modified) is None:
            raise NasaThesaurusAcquisitionError("content_last_modified must be an ISO date (YYYY-MM-DD)")
        if not 1958 <= self.citation_year <= 2100:
            raise NasaThesaurusAcquisitionError("citation_year is not a plausible NASA STI Program year")
        _require_absolute_source_page_url(self.source_page_url)
        if not (
            self.citation_apa
            and self.citation_mla
            and self.citation_chicago
            and self.attribution_requirement
            and self.publisher
            and self.attribution_organization
        ):
            raise NasaThesaurusAcquisitionError("citation and attribution fields must not be empty")


def _require_absolute_source_page_url(value: str) -> None:
    if not urllib.parse.urlsplit(value).scheme:
        raise NasaThesaurusAcquisitionError(f"source_page_url must be an absolute IRI, got {value!r}")


NASA_THESAURUS_SKOS = NasaThesaurusReleaseSource(
    format_name="SKOS",
    source_url="https://sti.nasa.gov/docs/thesaurus/thesaurus-SKOS.xml",
    expected_sha256="sha256:3cd92a0eb67c5656e4c740394abd2d27042ded79a4acf3e1286e73a7d863010f",
    expected_byte_length=32_943_406,
    filename="thesaurus-SKOS.xml",
    # HTTP Last-Modified of the pinned download, captured 2026-08-03. Distinct
    # from the citation year below, which the source's own citation examples
    # hold fixed at 2012 regardless of file format or download date.
    content_last_modified="2026-04-24",
    citation_year=2012,
    citation_apa=(
        "NASA STI Program. (2012). NASA thesaurus [Data file]. Retrieved from https://sti.nasa.gov/nasa-thesaurus/"
    ),
    citation_mla=(
        "NASA STI Program. NASA Thesaurus. Washington, DC: National Aeronautics and Space Administration, 2012. SKOS."
    ),
    citation_chicago=(
        "NASA STI Program. NASA Thesaurus. SKOS. Washington, DC: National Aeronautics and Space Administration, 2012."
    ),
    attribution_requirement=(
        "Please cite the NASA STI Program in your work if you incorporate/use the NASA Thesaurus."
    ),
    source_page_url="https://sti.nasa.gov/nasa-thesaurus/",
)
NASA_THESAURUS_RELEASES: dict[str, NasaThesaurusReleaseSource] = {"skos": NASA_THESAURUS_SKOS}


@dataclass(frozen=True, slots=True)
class AcquiredNasaThesaurusSource:
    """One verified NASA Thesaurus object in a content-addressed local store."""

    release: NasaThesaurusReleaseSource
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    cache_hit: bool
    acquisition_mode: AcquisitionMode
    local_source_path: Path | None


def _as_acquired_nasa_thesaurus(
    release: NasaThesaurusReleaseSource,
    acquired: AcquiredPinnedSource,
) -> AcquiredNasaThesaurusSource:
    return AcquiredNasaThesaurusSource(
        release=release,
        path=acquired.path,
        source_url=acquired.source_url,
        resolved_url=acquired.resolved_url,
        sha256=acquired.sha256,
        byte_length=acquired.byte_length,
        cache_hit=acquired.cache_hit,
        acquisition_mode=acquired.acquisition_mode,
        local_source_path=acquired.local_source_path,
    )


def acquire_nasa_thesaurus_release(
    release: NasaThesaurusReleaseSource,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    allow_network: bool = False,
    timeout_seconds: float = 60.0,
) -> AcquiredNasaThesaurusSource:
    """Resolve one pinned NASA Thesaurus release from cache, a local file, or the network.

    Cache lookup is always local. A supplied ``source_path`` is read locally.
    Otherwise, a cache miss fails unless ``allow_network`` is explicitly true.
    Every path is subject to the release's exact byte-length and digest pins.
    """

    try:
        acquired = acquire_pinned_source(
            release,
            store_dir,
            labels=_NASA_THESAURUS_ACQUIRE_LABELS,
            source_path=source_path,
            allow_network=allow_network,
            timeout_seconds=timeout_seconds,
        )
    except PinnedAcquisitionError as error:
        raise NasaThesaurusAcquisitionError(str(error)) from error
    return _as_acquired_nasa_thesaurus(release, acquired)


def parse_acquired_nasa_thesaurus_source(acquired: AcquiredNasaThesaurusSource) -> NasaThesaurusVocabulary:
    """Reverify and parse an object returned by the NASA Thesaurus acquisition adapter."""

    if acquired.path.is_symlink() or not acquired.path.is_file():
        raise NasaThesaurusParseError(f"acquired NASA Thesaurus source is not a regular file: {acquired.path}")
    parsed = parse_nasa_thesaurus_xml(
        acquired.path.read_bytes(),
        source_url=acquired.release.source_url,
        expected_sha256=acquired.release.expected_sha256,
        expected_byte_length=acquired.release.expected_byte_length,
    )
    if not parsed.concepts:
        raise NasaThesaurusParseError("pinned NASA Thesaurus distribution has no skos:Concept assertions")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Acquire one exact NASA Thesaurus distribution into a content-addressed local store."
    )
    parser.add_argument("format", choices=tuple(NASA_THESAURUS_RELEASES))
    parser.add_argument("store", type=Path)
    parser.add_argument("--source-path", type=Path)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        acquired = acquire_nasa_thesaurus_release(
            NASA_THESAURUS_RELEASES[args.format],
            args.store,
            source_path=args.source_path,
            allow_network=args.allow_network,
            timeout_seconds=args.timeout_seconds,
        )
    except NasaThesaurusAcquisitionError as error:
        parser.error(str(error))
    print(acquired.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
