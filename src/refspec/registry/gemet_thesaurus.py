"""Lossless RDF/SKOS feature reader for pinned GEMET RDF/XML releases.

GEMET (the General Multilingual Environmental Thesaurus) publishes its
SKOS export as gzip-compressed RDF/XML, not the fully-qualified Turtle other
RefSpec thesaurus readers consume, and its concept IRIs
(``http://www.eionet.europa.eu/gemet/concept/<id>``) are the publisher's own
stable identity: unlike a per-release namespace, GEMET does not emit
``owl:deprecated``, ``owl:priorVersion``, or ``dct:isVersionOf``/
``dct:isReplacedBy`` assertions, so there is no separate release-to-release
identity join to model here. The reader keeps every authored concept and
concept-scheme IRI, language tag, literal datatype, and one record per RDF
assertion for the vocabulary features RefSpec consumes; it never mints an
identifier the publisher did not supply.

GEMET's RDF/XML also publishes a second, independent organizing layer above
its concepts: 32 ``Group``, 4 ``SuperGroup``, and 40 ``Theme`` resources
(every one of them also typed ``skos:Collection``), plus the two named
meta-collections ``groupCollection`` and ``superGroupCollection`` that
enumerate the Groups and SuperGroups via ``skos:member``. These are genuine
publisher assertions -- every Group and SuperGroup carries multilingual
``skos:prefLabel`` labels, every Theme carries a multilingual ``rdfs:label`` and
a (narrower-coverage) GEMET-native ``acronymLabel``, every Group states
exactly one GEMET-native ``subGroupOf`` parent SuperGroup, and Group/Theme
membership is asserted as ``skos:member`` triples on the collection, never
as a reverse predicate on the concept. This reader preserves all of it,
scoped to exactly those 78 collection subjects and kept in its own
``organization_resources``/``organization_labels``/
``organization_metadata_literals``/``organization_membership_relations``/
``organization_hierarchy_relations`` fields rather than mixed into the
concept-scoped ``labels``/``metadata_literals`` above. Themes are *not*
nested under Group/SuperGroup or vice versa -- the two hierarchies are
parallel, disjoint classifications GEMET never links to one another, and
neither one is built from (or even fully covers) the 112 concepts that are
``skos:Concept`` roots under ``skos:broader``/``skos:hasTopConcept``.

The one entity kind this reader still does not model is GEMET's 87
bibliographic ``Source`` records, which reuse some SKOS predicates in ways
inconsistent with how GEMET uses them on concepts -- most notably an
untagged ``skos:notation`` on every record. The catalog scope for this
source is "preserve source concept IRIs, scheme membership, and the
publisher's Group/SuperGroup/Theme organization", so every typed feature
extractor below is restricted to subjects that are the pinned concept
scheme, an ``rdf:type skos:Concept`` subject, or one of the 78 organization
subjects; nothing beyond that boundary is promoted into a modeled feature.
No triple is silently dropped from view: ``predicate_counts`` and
``source_iris`` census every predicate and IRI the payload actually
contains, typed or not, so a reviewer can see what this reader chose not to
model.

Importing this module never opens a network connection. A caller must either
supply an existing local distribution or set ``allow_network=True``. Every
acquisition path is subject to the release's exact byte-length and SHA-256
digest pins, applied both to the compressed download (as GEMET serves it)
and to the decompressed RDF/XML payload the parser reads.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import logging
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal as LiteralType

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS
from rdflib.term import Identifier

from refspec.registry.infrastructure.pinned_acquisition import AcquisitionMode
from refspec.registry.infrastructure.source_controlled_resource import LabelRole as GemetLabelRole

GEMET_SCHEMA_NAMESPACE = "http://www.eionet.europa.eu/gemet/2004/06/gemet-schema.rdf#"
GEMET_DEFINITION_SOURCE_PREDICATE_IRI = GEMET_SCHEMA_NAMESPACE + "source"

PREF_LABEL_PREDICATE_IRI = str(SKOS.prefLabel)
ALT_LABEL_PREDICATE_IRI = str(SKOS.altLabel)
HIDDEN_LABEL_PREDICATE_IRI = str(SKOS.hiddenLabel)
NOTATION_PREDICATE_IRI = str(SKOS.notation)

# Only the SKOS note predicates GEMET's 4.2.3 RDF/XML actually emits, plus
# its one native definition-source citation. skos:example, skos:note,
# skos:historyNote, and skos:changeNote are absent from the publication (0
# occurrences); adding speculative support for shapes never observed in the
# pinned release would be a guess, not a preservation.
NOTE_PREDICATE_IRIS = (
    str(SKOS.definition),
    str(SKOS.scopeNote),
    str(SKOS.editorialNote),
)
GEMET_NOTE_PREDICATE_IRIS = (*NOTE_PREDICATE_IRIS, GEMET_DEFINITION_SOURCE_PREDICATE_IRI)

BROADER_PREDICATE_IRI = str(SKOS.broader)
NARROWER_PREDICATE_IRI = str(SKOS.narrower)
RELATED_PREDICATE_IRI = str(SKOS.related)
HIERARCHY_AND_ASSOCIATIVE_PREDICATE_IRIS = (
    BROADER_PREDICATE_IRI,
    NARROWER_PREDICATE_IRI,
    RELATED_PREDICATE_IRI,
)
EXACT_MATCH_PREDICATE_IRI = str(SKOS.exactMatch)
CLOSE_MATCH_PREDICATE_IRI = str(SKOS.closeMatch)
BROAD_MATCH_PREDICATE_IRI = str(SKOS.broadMatch)
NARROW_MATCH_PREDICATE_IRI = str(SKOS.narrowMatch)
RELATED_MATCH_PREDICATE_IRI = str(SKOS.relatedMatch)
SKOS_MAPPING_PREDICATE_IRIS = (
    str(SKOS.mappingRelation),
    BROAD_MATCH_PREDICATE_IRI,
    NARROW_MATCH_PREDICATE_IRI,
    RELATED_MATCH_PREDICATE_IRI,
    CLOSE_MATCH_PREDICATE_IRI,
    EXACT_MATCH_PREDICATE_IRI,
)

LICENSE_PREDICATE_IRI = "http://purl.org/dc/terms/licence"

CREATED_PREDICATE_IRI = "http://purl.org/dc/terms/created"
MODIFIED_PREDICATE_IRI = "http://purl.org/dc/terms/modified"
DISPLAY_LABEL_PREDICATE_IRI = "http://www.w3.org/2000/01/rdf-schema#label"
GEMET_METADATA_LITERAL_PREDICATE_IRIS = (
    CREATED_PREDICATE_IRI,
    MODIFIED_PREDICATE_IRI,
    DISPLAY_LABEL_PREDICATE_IRI,
)

# GEMET's second, publisher-asserted organizing layer: Group, SuperGroup, and
# Theme skos:Collections, plus the two named meta-collections that enumerate
# the Groups and SuperGroups. See the module docstring for the exact shape.
GROUP_TYPE_IRI = GEMET_SCHEMA_NAMESPACE + "Group"
SUPER_GROUP_TYPE_IRI = GEMET_SCHEMA_NAMESPACE + "SuperGroup"
THEME_TYPE_IRI = GEMET_SCHEMA_NAMESPACE + "Theme"
SUB_GROUP_OF_PREDICATE_IRI = GEMET_SCHEMA_NAMESPACE + "subGroupOf"
ACRONYM_LABEL_PREDICATE_IRI = GEMET_SCHEMA_NAMESPACE + "acronymLabel"
MEMBER_PREDICATE_IRI = str(SKOS.member)
GROUP_COLLECTION_IRI = "http://www.eionet.europa.eu/gemet/groupCollection"
SUPER_GROUP_COLLECTION_IRI = "http://www.eionet.europa.eu/gemet/superGroupCollection"

# skos:member is the only predicate ever used to assert Group/Theme
# membership or SuperGroup/groupCollection/superGroupCollection enumeration;
# gemet-schema:subGroupOf is the only predicate linking a Group to its
# SuperGroup. Both are exhaustively confirmed against the pinned 4.2.3
# release: every skos:member triple in the payload has one of the 78
# organization subjects below on the left, and every subGroupOf triple has a
# Group on the left and a SuperGroup on the right.
ORGANIZATION_MEMBERSHIP_PREDICATE_IRIS = (MEMBER_PREDICATE_IRI,)
ORGANIZATION_HIERARCHY_PREDICATE_IRIS = (SUB_GROUP_OF_PREDICATE_IRI,)

# Group and SuperGroup individuals carry only skos:prefLabel (never
# altLabel/hiddenLabel); Theme individuals and the two meta-collections carry
# rdfs:label (the same predicate the concept scheme's own display label
# uses) and, for a narrower set of languages, the GEMET-native acronymLabel;
# Group/SuperGroup/Theme individuals (never the two meta-collections) carry
# dct:created/dct:modified exactly as concepts do.
ORGANIZATION_METADATA_LITERAL_PREDICATE_IRIS = (
    CREATED_PREDICATE_IRI,
    MODIFIED_PREDICATE_IRI,
    DISPLAY_LABEL_PREDICATE_IRI,
    ACRONYM_LABEL_PREDICATE_IRI,
)

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_GZIP_MAGIC = b"\x1f\x8b"


class GemetParseError(ValueError):
    """A GEMET RDF feature cannot be preserved without guessing."""


class GemetAcquisitionError(ValueError):
    """A GEMET source could not be acquired without weakening its pin."""


def _require_absolute_iri(value: str, label: str) -> str:
    if not urllib.parse.urlsplit(value).scheme:
        raise GemetParseError(f"{label} must be an absolute IRI, got {value!r}")
    return value


def _iri(term: Identifier, label: str) -> str:
    if not isinstance(term, URIRef):
        kind = "blank node" if not isinstance(term, Literal) else "RDF literal"
        raise GemetParseError(f"{label} must be an IRI, got {kind}")
    return _require_absolute_iri(str(term), label)


def _literal(term: Identifier, label: str) -> GemetLiteral:
    if not isinstance(term, Literal):
        raise GemetParseError(f"{label} must be an RDF literal")
    language_tag = str(term.language) if term.language is not None else None
    datatype_iri = str(term.datatype) if term.datatype is not None else None
    if datatype_iri is not None:
        _require_absolute_iri(datatype_iri, f"{label} datatype")
    return GemetLiteral(
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
        raise GemetParseError(f"GEMET RDF/XML is not valid UTF-8 at byte {error.start}") from error
    return payload


@dataclass(frozen=True, slots=True)
class GemetLiteral:
    """One RDF literal with its lexical form, language, and datatype."""

    lexical_form: str
    language_tag: str | None
    datatype_iri: str | None


@dataclass(frozen=True, slots=True)
class GemetConcept:
    """One ``skos:Concept`` and its scheme assertions."""

    concept_iri: str
    scheme_iris: tuple[str, ...]
    top_concept_of_iris: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GemetConceptScheme:
    """The GEMET ``skos:ConceptScheme`` and its explicit top concepts."""

    scheme_iri: str
    top_concept_iris: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GemetLabelExpression:
    """One authored SKOS label assertion on a GEMET concept."""

    subject_iri: str
    property_iri: str
    role: GemetLabelRole
    value: GemetLiteral


@dataclass(frozen=True, slots=True)
class GemetNote:
    """One supported SKOS or GEMET-native note assertion on a concept."""

    subject_iri: str
    property_iri: str
    value: GemetLiteral


@dataclass(frozen=True, slots=True)
class GemetNotation:
    """One ``skos:notation`` as GEMET actually publishes it: a language-tagged
    plain literal (e.g. the chemical-formula synonym ``"Cd"@en``), not the
    typed literal the SKOS specification illustrates."""

    subject_iri: str
    property_iri: str
    value: GemetLiteral


@dataclass(frozen=True, slots=True)
class GemetIriRelation:
    """One RDF assertion whose subject and object remain exact source IRIs."""

    subject_iri: str
    predicate_iri: str
    object_iri: str


@dataclass(frozen=True, slots=True)
class GemetMetadataLiteral:
    """One authored lifecycle or display-label literal on a concept, scheme,
    or (see ``organization_metadata_literals``) Group/SuperGroup/Theme/
    meta-collection organization resource."""

    subject_iri: str
    property_iri: str
    value: GemetLiteral


GemetOrganizationResourceKind = LiteralType[
    "groupCollection", "superGroupCollection", "superGroup", "group", "theme"
]


@dataclass(frozen=True, slots=True)
class GemetOrganizationResource:
    """One of GEMET's 78 publisher-asserted organization resources: a
    ``Group``, ``SuperGroup``, or ``Theme`` individual (each also typed
    ``skos:Collection``), or one of the two named meta-collections
    (``groupCollection``/``superGroupCollection``) that enumerate the Groups
    and SuperGroups via ``skos:member``. Never a ``skos:Concept``."""

    resource_iri: str
    kind: GemetOrganizationResourceKind
    type_iris: tuple[str, ...]
    scheme_iris: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GemetPredicateCount:
    """An observed predicate count used to make import coverage explicit."""

    predicate_iri: str
    assertion_count: int


@dataclass(frozen=True, slots=True)
class GemetImportCounts:
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
    exact_match_relations: int
    close_match_relations: int
    broad_match_relations: int
    narrow_match_relations: int
    related_match_relations: int
    mapping_relations: int
    license_relations: int
    metadata_literals: int
    created_assertions: int
    modified_assertions: int
    display_label_assertions: int
    organization_resources: int
    groups: int
    super_groups: int
    themes: int
    organization_meta_collections: int
    organization_labels: int
    organization_metadata_literals: int
    organization_created_assertions: int
    organization_modified_assertions: int
    organization_display_label_assertions: int
    organization_acronym_label_assertions: int
    organization_membership_relations: int
    organization_hierarchy_relations: int


@dataclass(frozen=True, slots=True)
class GemetVocabulary:
    """Deterministic parsed view of one exact GEMET RDF/XML payload."""

    source_url: str
    source_sha256: str
    source_bytes: int
    triple_count: int
    source_iris: tuple[str, ...]
    predicate_counts: tuple[GemetPredicateCount, ...]
    concepts: tuple[GemetConcept, ...]
    concept_schemes: tuple[GemetConceptScheme, ...]
    labels: tuple[GemetLabelExpression, ...]
    notes: tuple[GemetNote, ...]
    notations: tuple[GemetNotation, ...]
    semantic_relations: tuple[GemetIriRelation, ...]
    mapping_relations: tuple[GemetIriRelation, ...]
    license_relations: tuple[GemetIriRelation, ...]
    metadata_literals: tuple[GemetMetadataLiteral, ...]
    organization_resources: tuple[GemetOrganizationResource, ...]
    organization_labels: tuple[GemetLabelExpression, ...]
    organization_metadata_literals: tuple[GemetMetadataLiteral, ...]
    organization_membership_relations: tuple[GemetIriRelation, ...]
    organization_hierarchy_relations: tuple[GemetIriRelation, ...]

    @property
    def counts(self) -> GemetImportCounts:
        labels = Counter(item.role for item in self.labels)
        semantics = Counter(item.predicate_iri for item in self.semantic_relations)
        mappings = Counter(item.predicate_iri for item in self.mapping_relations)
        metadata = Counter(item.property_iri for item in self.metadata_literals)
        organization_kinds = Counter(item.kind for item in self.organization_resources)
        organization_metadata = Counter(item.property_iri for item in self.organization_metadata_literals)
        return GemetImportCounts(
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
            exact_match_relations=mappings[EXACT_MATCH_PREDICATE_IRI],
            close_match_relations=mappings[CLOSE_MATCH_PREDICATE_IRI],
            broad_match_relations=mappings[BROAD_MATCH_PREDICATE_IRI],
            narrow_match_relations=mappings[NARROW_MATCH_PREDICATE_IRI],
            related_match_relations=mappings[RELATED_MATCH_PREDICATE_IRI],
            mapping_relations=len(self.mapping_relations),
            license_relations=len(self.license_relations),
            metadata_literals=len(self.metadata_literals),
            created_assertions=metadata[CREATED_PREDICATE_IRI],
            modified_assertions=metadata[MODIFIED_PREDICATE_IRI],
            display_label_assertions=metadata[DISPLAY_LABEL_PREDICATE_IRI],
            organization_resources=len(self.organization_resources),
            groups=organization_kinds["group"],
            super_groups=organization_kinds["superGroup"],
            themes=organization_kinds["theme"],
            organization_meta_collections=(
                organization_kinds["groupCollection"] + organization_kinds["superGroupCollection"]
            ),
            organization_labels=len(self.organization_labels),
            organization_metadata_literals=len(self.organization_metadata_literals),
            organization_created_assertions=organization_metadata[CREATED_PREDICATE_IRI],
            organization_modified_assertions=organization_metadata[MODIFIED_PREDICATE_IRI],
            organization_display_label_assertions=organization_metadata[DISPLAY_LABEL_PREDICATE_IRI],
            organization_acronym_label_assertions=organization_metadata[ACRONYM_LABEL_PREDICATE_IRI],
            organization_membership_relations=len(self.organization_membership_relations),
            organization_hierarchy_relations=len(self.organization_hierarchy_relations),
        )


def _label_expressions(graph: Graph, subjects: frozenset[URIRef]) -> tuple[GemetLabelExpression, ...]:
    """SKOS label assertions on the given subjects. Used both for concepts
    (which publish prefLabel/altLabel/hiddenLabel) and, with a
    Group/SuperGroup subject set, for the organization layer (which
    publishes only prefLabel -- the loop still checks all three so an
    unexpected future altLabel/hiddenLabel on a Group is preserved rather
    than silently dropped)."""

    properties: tuple[tuple[URIRef, GemetLabelRole], ...] = (
        (SKOS.prefLabel, "preferred"),
        (SKOS.altLabel, "alternate"),
        (SKOS.hiddenLabel, "hidden"),
    )
    labels: list[GemetLabelExpression] = []
    preferred_by_language: dict[tuple[str, str], str] = {}
    for predicate, role in properties:
        for subject, value in graph.subject_objects(predicate):
            if subject not in subjects:
                continue
            subject_iri = _iri(subject, f"{role} label subject")
            literal = _literal(value, f"{role} label")
            if literal.language_tag is None:
                raise GemetParseError(
                    f"{role} label on {subject_iri} is untagged; GEMET labels must retain a language tag"
                )
            if role == "preferred":
                key = (subject_iri, literal.language_tag.casefold())
                previous = preferred_by_language.get(key)
                if previous is not None and previous != literal.lexical_form:
                    raise GemetParseError(
                        f"{subject_iri} has more than one preferred label for language {literal.language_tag}"
                    )
                preferred_by_language[key] = literal.lexical_form
            labels.append(
                GemetLabelExpression(
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


def _notes(graph: Graph, concept_iris: frozenset[URIRef]) -> tuple[GemetNote, ...]:
    notes: list[GemetNote] = []
    for predicate_iri in GEMET_NOTE_PREDICATE_IRIS:
        predicate = URIRef(predicate_iri)
        for subject, value in graph.subject_objects(predicate):
            if subject not in concept_iris:
                continue
            notes.append(
                GemetNote(
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


def _notations(graph: Graph, concept_iris: frozenset[URIRef]) -> tuple[GemetNotation, ...]:
    notations: list[GemetNotation] = []
    for subject, value in graph.subject_objects(SKOS.notation):
        if subject not in concept_iris:
            continue
        subject_iri = _iri(subject, "notation subject")
        literal = _literal(value, "notation")
        if literal.datatype_iri is not None:
            raise GemetParseError(
                f"notation on {subject_iri} has a datatype; GEMET concept notations are plain, "
                "language-tagged literals, not typed literals"
            )
        if literal.language_tag is None:
            raise GemetParseError(f"notation on {subject_iri} is untagged; GEMET concept notations retain a language tag")
        notations.append(
            GemetNotation(
                subject_iri=subject_iri,
                property_iri=NOTATION_PREDICATE_IRI,
                value=literal,
            )
        )
    return tuple(
        sorted(
            notations,
            key=lambda item: (item.subject_iri, item.value.language_tag or "", item.value.lexical_form),
        )
    )


def _iri_relations(
    graph: Graph,
    predicate_iris: tuple[str, ...],
    *,
    subjects: frozenset[URIRef],
    label: str,
) -> tuple[GemetIriRelation, ...]:
    relations: list[GemetIriRelation] = []
    for predicate_iri in predicate_iris:
        for subject, object_ in graph.subject_objects(URIRef(predicate_iri)):
            if subject not in subjects:
                continue
            relations.append(
                GemetIriRelation(
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


def _concepts(graph: Graph, concept_iris: frozenset[URIRef]) -> tuple[GemetConcept, ...]:
    concepts: list[GemetConcept] = []
    for subject in concept_iris:
        concept_iri = _iri(subject, "concept")
        schemes = tuple(sorted(_iri(item, "skos:inScheme object") for item in graph.objects(subject, SKOS.inScheme)))
        top_schemes = tuple(
            sorted(_iri(item, "skos:topConceptOf object") for item in graph.objects(subject, SKOS.topConceptOf))
        )
        concepts.append(
            GemetConcept(
                concept_iri=concept_iri,
                scheme_iris=schemes,
                top_concept_of_iris=top_schemes,
            )
        )
    return tuple(sorted(concepts, key=lambda item: item.concept_iri))


def _concept_schemes(graph: Graph, scheme_iris: frozenset[URIRef]) -> tuple[GemetConceptScheme, ...]:
    schemes: list[GemetConceptScheme] = []
    for subject in scheme_iris:
        scheme_iri = _iri(subject, "concept scheme")
        top_concepts = tuple(
            sorted(_iri(item, "skos:hasTopConcept object") for item in graph.objects(subject, SKOS.hasTopConcept))
        )
        schemes.append(
            GemetConceptScheme(
                scheme_iri=scheme_iri,
                top_concept_iris=top_concepts,
            )
        )
    return tuple(sorted(schemes, key=lambda item: item.scheme_iri))


def _metadata_literals(
    graph: Graph,
    subjects: frozenset[URIRef],
    *,
    predicate_iris: tuple[str, ...] = GEMET_METADATA_LITERAL_PREDICATE_IRIS,
) -> tuple[GemetMetadataLiteral, ...]:
    assertions: list[GemetMetadataLiteral] = []
    for predicate_iri in predicate_iris:
        for subject, value in graph.subject_objects(URIRef(predicate_iri)):
            if subject not in subjects:
                continue
            assertions.append(
                GemetMetadataLiteral(
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


def _organization_resources(
    graph: Graph,
    kind_by_subject: Mapping[URIRef, GemetOrganizationResourceKind],
) -> tuple[GemetOrganizationResource, ...]:
    resources: list[GemetOrganizationResource] = []
    for subject, kind in kind_by_subject.items():
        resource_iri = _iri(subject, f"{kind} organization resource")
        type_iris = tuple(
            sorted(_iri(item, f"{kind} rdf:type object") for item in graph.objects(subject, RDF.type))
        )
        scheme_iris = tuple(
            sorted(_iri(item, f"{kind} skos:inScheme object") for item in graph.objects(subject, SKOS.inScheme))
        )
        resources.append(
            GemetOrganizationResource(
                resource_iri=resource_iri,
                kind=kind,
                type_iris=type_iris,
                scheme_iris=scheme_iris,
            )
        )
    return tuple(sorted(resources, key=lambda item: item.resource_iri))


def parse_gemet_rdf_xml(
    source: str | bytes,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> GemetVocabulary:
    """Parse one exact GEMET RDF/XML payload into deterministic feature rows."""

    _require_absolute_iri(source_url, "source_url")
    payload = _source_payload(source)
    source_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None:
        if _DIGEST.fullmatch(expected_sha256) is None:
            raise GemetParseError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if source_sha256 != expected_sha256:
            raise GemetParseError(f"source digest mismatch: expected {expected_sha256}, got {source_sha256}")
    if expected_byte_length is not None:
        if expected_byte_length <= 0:
            raise GemetParseError("expected_byte_length must be positive")
        if len(payload) != expected_byte_length:
            raise GemetParseError(f"source byte length mismatch: expected {expected_byte_length}, got {len(payload)}")

    graph = Graph()
    # GEMET emits an empty xsd:dateTime literal on every concept's
    # dcterms:created/dcterms:modified; RDFLib preserves the (empty) lexical
    # form but logs a non-fatal cast warning for each one when parsing
    # RDF/XML. Preserving the source byte-for-byte means keeping that empty
    # literal rather than rejecting it, so the expected warning is silenced
    # rather than left to look like a parse failure.
    term_logger = logging.getLogger("rdflib.term")
    previous_level = term_logger.level
    term_logger.setLevel(logging.ERROR)
    try:
        graph.parse(data=payload, format="xml", publicID=source_url)
    except Exception as error:
        raise GemetParseError(f"could not parse GEMET RDF/XML: {error}") from error
    finally:
        term_logger.setLevel(previous_level)

    concept_iris = frozenset(graph.subjects(RDF.type, SKOS.Concept))
    scheme_iris = frozenset(graph.subjects(RDF.type, SKOS.ConceptScheme))
    metadata_subjects = concept_iris | scheme_iris

    group_iris = frozenset(graph.subjects(RDF.type, URIRef(GROUP_TYPE_IRI)))
    super_group_iris = frozenset(graph.subjects(RDF.type, URIRef(SUPER_GROUP_TYPE_IRI)))
    theme_iris = frozenset(graph.subjects(RDF.type, URIRef(THEME_TYPE_IRI)))
    group_collection_iri = URIRef(GROUP_COLLECTION_IRI)
    super_group_collection_iri = URIRef(SUPER_GROUP_COLLECTION_IRI)

    organization_type_overlap = (group_iris | super_group_iris | theme_iris) & (concept_iris | scheme_iris)
    if organization_type_overlap:
        raise GemetParseError(
            "a GEMET Group/SuperGroup/Theme subject is also typed skos:Concept or "
            f"skos:ConceptScheme: {sorted(str(item) for item in organization_type_overlap)[:5]!r}"
        )

    all_subjects = frozenset(graph.subjects())
    kind_by_subject: dict[URIRef, GemetOrganizationResourceKind] = {}
    kind_by_subject.update(dict.fromkeys(group_iris, "group"))
    kind_by_subject.update(dict.fromkeys(super_group_iris, "superGroup"))
    kind_by_subject.update(dict.fromkeys(theme_iris, "theme"))
    # The two meta-collections are identified by their fixed, publisher-named
    # IRI rather than an rdf:type -- unlike Group/SuperGroup/Theme, GEMET
    # gives them no gemet-schema type at all, only skos:Collection. Only
    # register one if the payload actually asserts a triple about it, so a
    # trimmed fixture that omits it does not get a phantom resource.
    if group_collection_iri in all_subjects:
        kind_by_subject[group_collection_iri] = "groupCollection"
    if super_group_collection_iri in all_subjects:
        kind_by_subject[super_group_collection_iri] = "superGroupCollection"
    organization_iris = frozenset(kind_by_subject)

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

    return GemetVocabulary(
        source_url=source_url,
        source_sha256=source_sha256,
        source_bytes=len(payload),
        triple_count=len(graph),
        source_iris=source_iris,
        predicate_counts=tuple(
            GemetPredicateCount(predicate_iri=predicate, assertion_count=count)
            for predicate, count in sorted(predicate_counts.items())
        ),
        concepts=_concepts(graph, concept_iris),
        concept_schemes=_concept_schemes(graph, scheme_iris),
        labels=_label_expressions(graph, concept_iris),
        notes=_notes(graph, concept_iris),
        notations=_notations(graph, concept_iris),
        semantic_relations=_iri_relations(
            graph,
            HIERARCHY_AND_ASSOCIATIVE_PREDICATE_IRIS,
            subjects=concept_iris,
            label="SKOS semantic relation",
        ),
        mapping_relations=_iri_relations(
            graph,
            SKOS_MAPPING_PREDICATE_IRIS,
            subjects=concept_iris,
            label="SKOS mapping relation",
        ),
        license_relations=_iri_relations(
            graph,
            (LICENSE_PREDICATE_IRI,),
            subjects=scheme_iris,
            label="license relation",
        ),
        metadata_literals=_metadata_literals(graph, metadata_subjects),
        organization_resources=_organization_resources(graph, kind_by_subject),
        organization_labels=_label_expressions(graph, group_iris | super_group_iris),
        organization_metadata_literals=_metadata_literals(
            graph,
            organization_iris,
            predicate_iris=ORGANIZATION_METADATA_LITERAL_PREDICATE_IRIS,
        ),
        organization_membership_relations=_iri_relations(
            graph,
            ORGANIZATION_MEMBERSHIP_PREDICATE_IRIS,
            subjects=organization_iris,
            label="GEMET organization membership",
        ),
        organization_hierarchy_relations=_iri_relations(
            graph,
            ORGANIZATION_HIERARCHY_PREDICATE_IRIS,
            subjects=group_iris,
            label="GEMET group super-group relation",
        ),
    )


def parse_gemet_file(
    path: Path,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> GemetVocabulary:
    """Parse one local, already-decompressed RDF/XML file while retaining its
    external source identity."""

    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise GemetParseError(f"GEMET source is not a regular file: {source_path}")
    return parse_gemet_rdf_xml(
        source_path.read_bytes(),
        source_url=source_url,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )


# --- Acquisition -----------------------------------------------------------
#
# GEMET serves its SKOS export gzip-compressed
# (https://www.eionet.europa.eu/gemet/latest/gemet.rdf.gz), unlike the
# fully-decompressed distributions other RefSpec thesaurus readers acquire.
# Acquisition therefore pins two digests: the compressed bytes exactly as
# GEMET serves them over HTTP, and the decompressed RDF/XML payload the
# parser above reads. A caller may also hand acquisition an
# already-decompressed local file (detected by the absence of the gzip
# magic bytes), in which case only the decompressed pin applies.

GEMET_LICENSE_IRI = "https://creativecommons.org/licenses/by/4.0/"
GEMET_LICENSE_LABEL = "Creative Commons Attribution 4.0 International"
GEMET_ATTRIBUTION = (
    "European Environment Agency (EEA) and the European Environment Information and Observation Network "
    "(Eionet) -- GEMET, the General Multilingual Environmental Thesaurus"
)
GEMET_PUBLISHER = "European Environment Agency / Eionet"
GEMET_CONCEPT_SCHEME_IRI = "http://www.eionet.europa.eu/gemet/gemetThesaurus"


def _validate_http_url(value: str, label: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GemetAcquisitionError(f"{label} must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise GemetAcquisitionError(f"{label} must not contain credentials")


def _require_absolute_iri_for_acquisition(value: str, label: str) -> None:
    if not urllib.parse.urlsplit(value).scheme:
        raise GemetAcquisitionError(f"{label} must be an absolute IRI")


def _expected_hex(expected_sha256: str) -> str:
    match = _DIGEST.fullmatch(expected_sha256)
    if match is None:
        raise GemetAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
    return match.group(1)


def _optional_digest(value: str | None, label: str) -> None:
    if value is not None and _DIGEST.fullmatch(value) is None:
        raise GemetAcquisitionError(f"{label} must be a lowercase sha256:<64 hex> digest")


@dataclass(frozen=True, slots=True)
class GemetReleaseSource:
    """One exact, externally published GEMET RDF/XML distribution."""

    version: str
    concept_scheme_iri: str
    source_url: str
    landing_page_url: str
    expected_sha256: str
    expected_byte_length: int
    filename: str
    expected_compressed_sha256: str | None = None
    expected_compressed_byte_length: int | None = None
    publisher: str = GEMET_PUBLISHER
    attribution: str = GEMET_ATTRIBUTION
    license_iri: str = GEMET_LICENSE_IRI
    license_label: str = GEMET_LICENSE_LABEL

    def __post_init__(self) -> None:
        if not self.version:
            raise GemetAcquisitionError("version must not be empty")
        _require_absolute_iri_for_acquisition(self.concept_scheme_iri, "concept_scheme_iri")
        _validate_http_url(self.source_url, "source_url")
        _validate_http_url(self.landing_page_url, "landing_page_url")
        _expected_hex(self.expected_sha256)
        if self.expected_byte_length <= 0:
            raise GemetAcquisitionError("expected_byte_length must be positive")
        _optional_digest(self.expected_compressed_sha256, "expected_compressed_sha256")
        if self.expected_compressed_byte_length is not None and self.expected_compressed_byte_length <= 0:
            raise GemetAcquisitionError("expected_compressed_byte_length must be positive")
        if not self.filename or Path(self.filename).name != self.filename:
            raise GemetAcquisitionError("filename must be one plain path component")
        _require_absolute_iri_for_acquisition(self.license_iri, "license_iri")
        if not self.publisher or not self.attribution or not self.license_label:
            raise GemetAcquisitionError("publisher, attribution, and license_label must not be empty")


GEMET_RELEASE_4_2_3 = GemetReleaseSource(
    version="4.2.3",
    concept_scheme_iri=GEMET_CONCEPT_SCHEME_IRI,
    source_url="https://www.eionet.europa.eu/gemet/latest/gemet.rdf.gz",
    landing_page_url="https://www.eionet.europa.eu/gemet/en/exports/rdf/latest",
    expected_sha256="sha256:1b784b1a6387b8ec6c0d75ea5f0543970933172fcb0428a52de2c8ca536d20f1",
    expected_byte_length=33_332_557,
    expected_compressed_sha256="sha256:96002bb7cd1f89bccb05ee174fb834a04dd7342bdd1428f32105cd47fd6b73b6",
    expected_compressed_byte_length=7_423_725,
    filename="gemet.rdf",
)
GEMET_RELEASES = {"4.2.3": GEMET_RELEASE_4_2_3}


@dataclass(frozen=True, slots=True)
class AcquiredGemetSource:
    """One verified, decompressed GEMET object in a content-addressed local store."""

    release: GemetReleaseSource
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    compressed_sha256: str | None
    compressed_byte_length: int | None
    cache_hit: bool
    acquisition_mode: AcquisitionMode
    local_source_path: Path | None


def _is_gzip(payload: bytes) -> bool:
    return payload[:2] == _GZIP_MAGIC


def _verify_decompressed_payload(
    payload: bytes,
    release: GemetReleaseSource,
    *,
    location: str,
) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != release.expected_byte_length:
        raise GemetAcquisitionError(
            f"{location} byte length mismatch: expected {release.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual_sha256 != release.expected_sha256:
        raise GemetAcquisitionError(f"{location} digest mismatch: expected {release.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing(path: Path, release: GemetReleaseSource) -> AcquiredGemetSource:
    if path.is_symlink() or not path.is_file():
        raise GemetAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_decompressed_payload(
        path.read_bytes(),
        release,
        location="cached GEMET source",
    )
    return AcquiredGemetSource(
        release=release,
        path=path,
        source_url=release.source_url,
        resolved_url=None,
        sha256=actual_sha256,
        byte_length=byte_length,
        compressed_sha256=None,
        compressed_byte_length=None,
        cache_hit=True,
        acquisition_mode="cache",
        local_source_path=None,
    )


def _publish_decompressed_payload(
    decompressed: bytes,
    release: GemetReleaseSource,
    final_path: Path,
    *,
    acquisition_mode: LiteralType["local", "network"],
    resolved_url: str | None,
    local_source_path: Path | None,
    compressed_sha256: str | None,
    compressed_byte_length: int | None,
) -> AcquiredGemetSource:
    actual_sha256, byte_length = _verify_decompressed_payload(
        decompressed,
        release,
        location="GEMET source",
    )

    object_dir = final_path.parent
    object_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".acquire-",
        suffix=".tmp",
        dir=object_dir,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(decompressed)
            output.flush()
            os.fsync(output.fileno())

        try:
            os.link(temporary_path, final_path)
        except FileExistsError:
            return _verify_existing(final_path, release)

        return AcquiredGemetSource(
            release=release,
            path=final_path,
            source_url=release.source_url,
            resolved_url=resolved_url,
            sha256=actual_sha256,
            byte_length=byte_length,
            compressed_sha256=compressed_sha256,
            compressed_byte_length=compressed_byte_length,
            cache_hit=False,
            acquisition_mode=acquisition_mode,
            local_source_path=local_source_path,
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def _publish_downloaded_bytes(
    payload: bytes,
    release: GemetReleaseSource,
    final_path: Path,
    *,
    acquisition_mode: LiteralType["local", "network"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredGemetSource:
    if _is_gzip(payload):
        compressed_byte_length = len(payload)
        compressed_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
        if release.expected_compressed_sha256 is not None and compressed_sha256 != release.expected_compressed_sha256:
            raise GemetAcquisitionError(
                f"compressed GEMET source digest mismatch: expected {release.expected_compressed_sha256}, "
                f"got {compressed_sha256}"
            )
        if (
            release.expected_compressed_byte_length is not None
            and compressed_byte_length != release.expected_compressed_byte_length
        ):
            raise GemetAcquisitionError(
                f"compressed GEMET source byte length mismatch: expected "
                f"{release.expected_compressed_byte_length}, got {compressed_byte_length}"
            )
        try:
            decompressed = gzip.decompress(payload)
        except OSError as error:
            raise GemetAcquisitionError(f"could not decompress GEMET source: {error}") from error
    else:
        compressed_sha256 = None
        compressed_byte_length = None
        decompressed = payload

    return _publish_decompressed_payload(
        decompressed,
        release,
        final_path,
        acquisition_mode=acquisition_mode,
        resolved_url=resolved_url,
        local_source_path=local_source_path,
        compressed_sha256=compressed_sha256,
        compressed_byte_length=compressed_byte_length,
    )


def acquire_gemet_release(
    release: GemetReleaseSource,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    allow_network: bool = False,
    timeout_seconds: float = 60.0,
) -> AcquiredGemetSource:
    """Resolve one pinned GEMET release from cache, a local file, or the network.

    Cache lookup is always local, keyed by the decompressed payload's pinned
    digest. A supplied ``source_path`` is read locally and may be either the
    gzip-compressed distribution or an already-decompressed RDF/XML file.
    Otherwise, a cache miss fails unless ``allow_network`` is explicitly
    true. Every path is subject to the release's exact byte-length and
    digest pins.
    """

    if timeout_seconds <= 0:
        raise GemetAcquisitionError("timeout_seconds must be positive")

    digest_hex = _expected_hex(release.expected_sha256)
    final_path = Path(store_dir) / "sha256" / digest_hex / release.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, release)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise GemetAcquisitionError(f"local GEMET source is not a regular file: {local_path}")
        return _publish_downloaded_bytes(
            local_path.read_bytes(),
            release,
            final_path,
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if not allow_network:
        raise GemetAcquisitionError(
            "GEMET source is not cached; provide source_path or set allow_network=True explicitly"
        )

    request = urllib.request.Request(
        release.source_url,
        headers={"User-Agent": "RefSpec explicit GEMET source resolver/1.0"},
        method="GET",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
    except (OSError, urllib.error.URLError) as error:
        raise GemetAcquisitionError(f"could not acquire {release.source_url}: {error}") from error
    with response:
        return _publish_downloaded_bytes(
            response.read(),
            release,
            final_path,
            acquisition_mode="network",
            resolved_url=response.geturl(),
            local_source_path=None,
        )


def parse_acquired_gemet_source(acquired: AcquiredGemetSource) -> GemetVocabulary:
    """Reverify and parse an object returned by the GEMET acquisition adapter."""

    if acquired.path.is_symlink() or not acquired.path.is_file():
        raise GemetParseError(f"acquired GEMET source is not a regular file: {acquired.path}")
    parsed = parse_gemet_rdf_xml(
        acquired.path.read_bytes(),
        source_url=acquired.release.source_url,
        expected_sha256=acquired.release.expected_sha256,
        expected_byte_length=acquired.release.expected_byte_length,
    )
    scheme_iris = {item.scheme_iri for item in parsed.concept_schemes}
    if acquired.release.concept_scheme_iri not in scheme_iris:
        raise GemetParseError(
            f"pinned GEMET concept scheme {acquired.release.concept_scheme_iri} is absent from the distribution"
        )
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Acquire one exact GEMET RDF/XML release into a content-addressed local store."
    )
    parser.add_argument("version", choices=tuple(GEMET_RELEASES))
    parser.add_argument("store", type=Path)
    parser.add_argument("--source-path", type=Path)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        acquired = acquire_gemet_release(
            GEMET_RELEASES[args.version],
            args.store,
            source_path=args.source_path,
            allow_network=args.allow_network,
            timeout_seconds=args.timeout_seconds,
        )
    except GemetAcquisitionError as error:
        parser.error(str(error))
    print(acquired.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
