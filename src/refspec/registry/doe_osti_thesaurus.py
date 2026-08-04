"""Source-faithful capture of the DOE OSTI Semantic Thesaurus 2020 RDF/SKOS export.

Source: DOE Data Explorer dataset record
https://www.osti.gov/dataexplorer/biblio/dataset/1668761 (OSTI identifier
1668761, DOI https://doi.org/10.11578/1668761), "OSTI Semantic Thesaurus v1",
publication date stated as 2020-09-30. The record's own abstract states: "This
dataset is an export from the OSTI Semantic Thesaurus in RDF/SKOS format...
While the full thesaurus includes additional relation types which may be
included in future revisions, this export is limited to broader, narrower,
and related term relations. Definitions and scope notes are included where
available." The distribution file itself was verified 2026-08-03 by
downloading https://www.osti.gov/servlets/purl/1668761 (18,087,998 bytes,
sha256:aeb9fb2d16caff675c7c9e12e0baff04ac4aded07488944acdf73ed859abe1d5) --
this module's pinned digest and byte length for ``DOE_OSTI_THESAURUS_V1_2020``
are the exact result of that verified capture, not a guess.

Catalog scope (binding): the 2026-07-28 catalog recorded this as a "Public
2020 Resource Description Framework/SKOS artifact; no newer public release or
changelog was verified", specialist role "Energy/science mapping research",
decision "Reject/defer canonical use until the owner provides a current,
licensed, reproducible release." The importing agent's guidance frames this as
a best-in-category inclusion -- nothing newer exists for energy/physical
science -- to be imported "with the staleness recorded prominently in package
metadata," in a mapping/research role, not as a governed current authority.
This module captures a real, verified 2020 export and keeps every staleness
and license verification gap explicit (``DOE_OSTI_THESAURUS_VERIFICATION_GAPS``)
rather than resolving or hiding them. The capture carries no permission
fields; exact product policy governs use.

Source shape (verified against the real 2020-09-30 distribution): a single
``<rdf:RDF>`` document holding one ``skos:ConceptScheme`` (IRI
``https://www.osti.gov/thesaurus``) and 23,626 ``skos:Concept`` elements. Every
literal in the verified distribution carries only an "en" language tag; there
is no ``skos:altLabel``, ``skos:hiddenLabel``, ``skos:notation``, no
``skos:*Match`` mapping relation, and no ``dcterms:*`` metadata embedded in
the graph at all (the 2020-09-30 publication date lives only in the Data
Explorer record, never in the RDF itself). Concept identifiers are the
publisher's own numeric thesaurus IRIs (for example
``https://www.osti.gov/thesaurus/3792``); per house rule this module reuses
those IRIs exactly and never mints a concept identity of its own. Because the
abstract itself warns that "the full thesaurus includes additional relation
types which may be included in future revisions," the parser refuses any
predicate outside its fixed allow-list instead of silently accepting or
dropping an unverified shape change.

Importing this module never opens a network connection. A caller must either
supply already-fetched bytes or inject a fetcher; direct network access
requires the caller to opt in explicitly.
"""

from __future__ import annotations

import dataclasses
import hashlib
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rdflib import RDF, Graph, Literal, URIRef
from rdflib.namespace import SKOS
from rdflib.term import Identifier

from refspec.storage import canonical_json

DOE_OSTI_PUBLISHER = "US Department of Energy, Office of Scientific and Technical Information (OSTI)"
DOE_OSTI_LANDING_PAGE_URL = "https://www.osti.gov/dataexplorer/biblio/dataset/1668761"
DOE_OSTI_DOI_URL = "https://doi.org/10.11578/1668761"
DOE_OSTI_CONCEPT_SCHEME_IRI = "https://www.osti.gov/thesaurus"
# The only date this research pass found anywhere for this record: the Data
# Explorer / search-API "publication_date". It is asserted in record
# metadata only -- the RDF distribution embeds no dct:issued or version
# literal at all. See the "statedPublicationDate" verification gap.
DOE_OSTI_STATED_PUBLICATION_DATE = "2020-09-30"

PREF_LABEL_PREDICATE_IRI = str(SKOS.prefLabel)
DEFINITION_PREDICATE_IRI = str(SKOS.definition)
SCOPE_NOTE_PREDICATE_IRI = str(SKOS.scopeNote)
BROADER_PREDICATE_IRI = str(SKOS.broader)
NARROWER_PREDICATE_IRI = str(SKOS.narrower)
RELATED_PREDICATE_IRI = str(SKOS.related)
IN_SCHEME_PREDICATE_IRI = str(SKOS.inScheme)
TOP_CONCEPT_OF_PREDICATE_IRI = str(SKOS.topConceptOf)
HAS_TOP_CONCEPT_PREDICATE_IRI = str(SKOS.hasTopConcept)
RDF_TYPE_PREDICATE_IRI = str(RDF.type)

SKOS_CONCEPT_TYPE_IRI = str(SKOS.Concept)
SKOS_CONCEPT_SCHEME_TYPE_IRI = str(SKOS.ConceptScheme)

NOTE_PREDICATE_IRIS = (DEFINITION_PREDICATE_IRI, SCOPE_NOTE_PREDICATE_IRI)
SEMANTIC_RELATION_PREDICATE_IRIS = (BROADER_PREDICATE_IRI, NARROWER_PREDICATE_IRI, RELATED_PREDICATE_IRI)
STRUCTURE_RELATION_PREDICATE_IRIS = (
    IN_SCHEME_PREDICATE_IRI,
    TOP_CONCEPT_OF_PREDICATE_IRI,
    HAS_TOP_CONCEPT_PREDICATE_IRI,
)
# The complete predicate allow-list this research pass verified against the
# real 2020-09-30 distribution. A predicate outside this set means the
# source shape has changed since this importer was written -- the abstract's
# own "may be included in future revisions" warning -- so the parser refuses
# rather than silently accepting or dropping it.
ALLOWED_PREDICATE_IRIS = frozenset(
    {
        PREF_LABEL_PREDICATE_IRI,
        *NOTE_PREDICATE_IRIS,
        *SEMANTIC_RELATION_PREDICATE_IRIS,
        *STRUCTURE_RELATION_PREDICATE_IRIS,
    }
)

_DIGEST_PREFIX = "sha256:"


class DoeOstiThesaurusError(ValueError):
    """A DOE OSTI Semantic Thesaurus feature cannot be preserved without guessing."""


# Verbatim framing of the catalog's decision for this source plus the
# importing agent's staleness-handling instruction, kept exact so downstream
# readers see the same scope decision that produced this module.
DOE_OSTI_THESAURUS_CATALOG_ROLE = (
    "Energy and physical science mapping/research source, not a governed subject "
    "module. The 2026-07-28 catalog recorded: Public 2020 Resource Description "
    "Framework/SKOS artifact; no newer public release or changelog was verified. "
    "Specialist role: Energy/science mapping research. Decision: Reject/defer "
    "canonical use until the owner provides a current, licensed, reproducible "
    "release. This is a best-in-category inclusion -- nothing newer exists for "
    "energy/physical science -- imported with its staleness recorded prominently "
    "in this capture manifest rather than skipped; it authorizes no candidate or "
    "accepted-output use."
)


@dataclass(frozen=True, slots=True)
class DoeOstiVerificationGap:
    """One explicit, unresolved verification gap this research pass found."""

    kind: str
    finding: str


# Findings from the 2026-08-03 research pass against the live Data Explorer
# record, its search API, and the real distribution bytes. Each gap is
# recorded, not resolved; none of them is silently assumed favorable.
DOE_OSTI_THESAURUS_VERIFICATION_GAPS: tuple[DoeOstiVerificationGap, ...] = (
    DoeOstiVerificationGap(
        kind="statedPublicationDate",
        finding=(
            "The Data Explorer landing page and search API both state "
            "publication_date 2020-09-30 for osti_id 1668761 ('OSTI Semantic "
            "Thesaurus v1'); the RDF/SKOS distribution itself embeds no "
            "dct:issued, dct:modified, or version literal, so 2020-09-30 is "
            "asserted only in record metadata, never inside the exported "
            "RDF graph."
        ),
    ),
    DoeOstiVerificationGap(
        kind="noNewerReleaseFound",
        finding=(
            "A 2026-08-03 OSTI Data Explorer search for 'OSTI Semantic "
            "Thesaurus' returned exactly one dataset record (osti_id "
            "1668761); no v2 or later dataset record was found."
        ),
    ),
    DoeOstiVerificationGap(
        kind="recordReindexedWithoutChangelog",
        finding=(
            "The same search API response reports entry_date "
            "2025-01-21T09:39:45Z for this one record, and the "
            "distribution's HTTP Last-Modified header (observed "
            "2026-08-03) is 2024-10-25; neither is accompanied by a "
            "changelog, dated release note, or version bump, so whether "
            "thesaurus content changed since 2020-09-30 is unverified. "
            "These dates are recorded as unresolved re-index/copy "
            "signals, not treated as evidence of a newer semantic release."
        ),
    ),
    DoeOstiVerificationGap(
        kind="license",
        finding=(
            "Neither the Data Explorer landing page nor the search API "
            "response for this record publishes a content license or "
            "reuse terms for the thesaurus data; DOE/OSTI's general site "
            "footer policies are not a dataset content license."
        ),
    ),
    DoeOstiVerificationGap(
        kind="distributionShapeIsNarrower",
        finding=(
            "The dataset abstract states the export 'is limited to "
            "broader, narrower, and related term relations' and that "
            "'the full thesaurus includes additional relation types which "
            "may be included in future revisions'; this module's parser "
            "therefore refuses any predicate outside its fixed allow-list "
            "instead of silently accepting or dropping a shape it has not "
            "verified."
        ),
    ),
    DoeOstiVerificationGap(
        kind="monolingualSourceOnly",
        finding=(
            "Every literal in the verified 2020-09-30 distribution "
            "carries only an 'en' language tag; no other language, no "
            "skos:altLabel, no skos:hiddenLabel, no skos:notation, and no "
            "skos:*Match mapping relation was found anywhere in the "
            "23,626-concept export."
        ),
    ),
    DoeOstiVerificationGap(
        kind="knownDanglingReference",
        finding=(
            "The verified distribution asserts one skos:hasTopConcept "
            "object (https://www.osti.gov/thesaurus/29668) that is never "
            "itself defined as a skos:Concept anywhere in the same "
            "distribution. This module preserves the assertion verbatim "
            "and exposes it through unresolved_top_concept_iris rather "
            "than silently dropping or repairing it."
        ),
    ),
    DoeOstiVerificationGap(
        kind="strayEmptyDescription",
        finding=(
            "The verified distribution also declares one empty "
            "rdf:Description for https://www.osti.gov/thesaurus/ "
            "(trailing slash; distinct from the concept scheme IRI "
            "https://www.osti.gov/thesaurus without one) that asserts no "
            "properties. It produces zero RDF triples and so is invisible "
            "to any triple-based parser, this module included; it is "
            "recorded here only as a documented artifact of the real "
            "capture."
        ),
    ),
)


def _require_absolute_iri(value: str, label: str) -> str:
    if not urllib.parse.urlsplit(value).scheme:
        raise DoeOstiThesaurusError(f"{label} must be an absolute IRI, got {value!r}")
    return value


def _validate_source_url(value: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DoeOstiThesaurusError("source_url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise DoeOstiThesaurusError("source_url must not contain credentials")


def _expected_hex(expected_sha256: str) -> str:
    if not expected_sha256.startswith(_DIGEST_PREFIX) or len(expected_sha256) != len(_DIGEST_PREFIX) + 64:
        raise DoeOstiThesaurusError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
    hex_part = expected_sha256[len(_DIGEST_PREFIX) :]
    if any(character not in "0123456789abcdef" for character in hex_part):
        raise DoeOstiThesaurusError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
    return hex_part


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
        raise DoeOstiThesaurusError(
            f"DOE OSTI Semantic Thesaurus export is not valid UTF-8 at byte {error.start}"
        ) from error
    return payload


def _iri(term: Identifier, label: str) -> str:
    if not isinstance(term, URIRef):
        kind = type(term).__name__
        raise DoeOstiThesaurusError(f"{label} must be an IRI, got {kind}")
    return _require_absolute_iri(str(term), label)


@dataclass(frozen=True, slots=True)
class DoeOstiLiteral:
    """One RDF literal with its lexical form and language tag.

    The verified 2020-09-30 distribution never emits a typed literal (see
    the "monolingualSourceOnly" gap); ``datatype_iri`` is retained purely as
    a loud failure signal if a future capture ever does.
    """

    lexical_form: str
    language_tag: str | None
    datatype_iri: str | None


@dataclass(frozen=True, slots=True)
class DoeOstiLabel:
    """One authored ``skos:prefLabel`` assertion, on a concept or the scheme."""

    subject_iri: str
    value: DoeOstiLiteral


@dataclass(frozen=True, slots=True)
class DoeOstiNote:
    """One authored ``skos:definition`` or ``skos:scopeNote`` assertion."""

    subject_iri: str
    property_iri: str
    value: DoeOstiLiteral


@dataclass(frozen=True, slots=True)
class DoeOstiIriRelation:
    """One RDF assertion whose subject and object remain exact source IRIs."""

    subject_iri: str
    predicate_iri: str
    object_iri: str


@dataclass(frozen=True, slots=True)
class DoeOstiConcept:
    """One ``skos:Concept`` and its ``skos:inScheme``/``skos:topConceptOf`` assertions."""

    concept_iri: str
    scheme_iris: tuple[str, ...]
    top_concept_of_iris: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DoeOstiConceptScheme:
    """One ``skos:ConceptScheme`` and its explicit ``skos:hasTopConcept`` assertions."""

    scheme_iri: str
    top_concept_iris: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DoeOstiPredicateCount:
    """An observed predicate count used to make import coverage explicit."""

    predicate_iri: str
    assertion_count: int


@dataclass(frozen=True, slots=True)
class DoeOstiImportCounts:
    """Feature counts for regression and import-coverage checks."""

    source_bytes: int
    triples: int
    source_iris: int
    concepts: int
    concept_schemes: int
    preferred_labels: int
    definitions: int
    scope_notes: int
    broader_relations: int
    narrower_relations: int
    related_relations: int
    has_top_concept_relations: int
    top_concept_of_relations: int
    in_scheme_relations: int
    unresolved_top_concept_iris: int


@dataclass(frozen=True, slots=True)
class DoeOstiThesaurus:
    """Deterministic parsed view of one exact DOE OSTI Semantic Thesaurus RDF/XML payload."""

    source_url: str
    source_sha256: str
    source_bytes: int
    triple_count: int
    source_iris: tuple[str, ...]
    predicate_counts: tuple[DoeOstiPredicateCount, ...]
    concept_scheme_iri: str
    concepts: tuple[DoeOstiConcept, ...]
    concept_schemes: tuple[DoeOstiConceptScheme, ...]
    labels: tuple[DoeOstiLabel, ...]
    notes: tuple[DoeOstiNote, ...]
    semantic_relations: tuple[DoeOstiIriRelation, ...]
    structure_relations: tuple[DoeOstiIriRelation, ...]

    @property
    def unresolved_top_concept_iris(self) -> tuple[str, ...]:
        """``skos:hasTopConcept`` objects this distribution never itself defines as a concept."""

        concept_iris = {item.concept_iri for item in self.concepts}
        dangling = {
            item.object_iri
            for item in self.structure_relations
            if item.predicate_iri == HAS_TOP_CONCEPT_PREDICATE_IRI and item.object_iri not in concept_iris
        }
        return tuple(sorted(dangling))

    @property
    def counts(self) -> DoeOstiImportCounts:
        semantics = Counter(item.predicate_iri for item in self.semantic_relations)
        structure = Counter(item.predicate_iri for item in self.structure_relations)
        notes = Counter(item.property_iri for item in self.notes)
        return DoeOstiImportCounts(
            source_bytes=self.source_bytes,
            triples=self.triple_count,
            source_iris=len(self.source_iris),
            concepts=len(self.concepts),
            concept_schemes=len(self.concept_schemes),
            preferred_labels=len(self.labels),
            definitions=notes[DEFINITION_PREDICATE_IRI],
            scope_notes=notes[SCOPE_NOTE_PREDICATE_IRI],
            broader_relations=semantics[BROADER_PREDICATE_IRI],
            narrower_relations=semantics[NARROWER_PREDICATE_IRI],
            related_relations=semantics[RELATED_PREDICATE_IRI],
            has_top_concept_relations=structure[HAS_TOP_CONCEPT_PREDICATE_IRI],
            top_concept_of_relations=structure[TOP_CONCEPT_OF_PREDICATE_IRI],
            in_scheme_relations=structure[IN_SCHEME_PREDICATE_IRI],
            unresolved_top_concept_iris=len(self.unresolved_top_concept_iris),
        )


def _literal(term: Identifier, label: str) -> DoeOstiLiteral:
    if not isinstance(term, Literal):
        raise DoeOstiThesaurusError(f"{label} must be an RDF literal")
    language_tag = str(term.language) if term.language is not None else None
    datatype_iri = str(term.datatype) if term.datatype is not None else None
    if datatype_iri is not None:
        _require_absolute_iri(datatype_iri, f"{label} datatype")
    return DoeOstiLiteral(lexical_form=str(term), language_tag=language_tag, datatype_iri=datatype_iri)


def _check_predicate_allow_list(graph: Graph) -> None:
    for predicate in set(graph.predicates()):
        predicate_iri = str(predicate)
        if predicate_iri == RDF_TYPE_PREDICATE_IRI:
            continue
        if predicate_iri not in ALLOWED_PREDICATE_IRIS:
            raise DoeOstiThesaurusError(
                f"unsupported predicate {predicate_iri!r}; the source shape may have "
                "changed since this importer was written"
            )


def _check_rdf_type_allow_list(graph: Graph) -> None:
    allowed_types = {SKOS.Concept, SKOS.ConceptScheme}
    for _, type_object in graph.subject_objects(RDF.type):
        if type_object not in allowed_types:
            raise DoeOstiThesaurusError(f"unsupported rdf:type object {type_object!r}")


def _labels(graph: Graph) -> tuple[DoeOstiLabel, ...]:
    labels: list[DoeOstiLabel] = []
    preferred_by_language: dict[tuple[str, str], str] = {}
    for subject, value in graph.subject_objects(SKOS.prefLabel):
        subject_iri = _iri(subject, "prefLabel subject")
        literal = _literal(value, "prefLabel")
        if literal.language_tag is None:
            raise DoeOstiThesaurusError(
                f"prefLabel on {subject_iri} is untagged; source labels must retain a language tag"
            )
        key = (subject_iri, literal.language_tag.casefold())
        previous = preferred_by_language.get(key)
        if previous is not None and previous != literal.lexical_form:
            raise DoeOstiThesaurusError(
                f"{subject_iri} has more than one preferred label for language {literal.language_tag}"
            )
        preferred_by_language[key] = literal.lexical_form
        labels.append(DoeOstiLabel(subject_iri=subject_iri, value=literal))
    return tuple(
        sorted(
            labels,
            key=lambda item: (item.subject_iri, item.value.language_tag or "", item.value.lexical_form),
        )
    )


def _notes(graph: Graph) -> tuple[DoeOstiNote, ...]:
    notes: list[DoeOstiNote] = []
    for predicate_iri in NOTE_PREDICATE_IRIS:
        for subject, value in graph.subject_objects(URIRef(predicate_iri)):
            subject_iri = _iri(subject, f"{predicate_iri} subject")
            literal = _literal(value, f"{predicate_iri} value")
            if literal.language_tag is None:
                raise DoeOstiThesaurusError(
                    f"{predicate_iri} on {subject_iri} is untagged; source notes must retain a language tag"
                )
            notes.append(DoeOstiNote(subject_iri=subject_iri, property_iri=predicate_iri, value=literal))
    return tuple(
        sorted(
            notes,
            key=lambda item: (
                item.subject_iri,
                item.property_iri,
                item.value.language_tag or "",
                item.value.lexical_form,
            ),
        )
    )


def _iri_relations(graph: Graph, predicate_iris: tuple[str, ...], *, label: str) -> tuple[DoeOstiIriRelation, ...]:
    relations: list[DoeOstiIriRelation] = []
    for predicate_iri in predicate_iris:
        for subject, object_ in graph.subject_objects(URIRef(predicate_iri)):
            relations.append(
                DoeOstiIriRelation(
                    subject_iri=_iri(subject, f"{label} subject"),
                    predicate_iri=predicate_iri,
                    object_iri=_iri(object_, f"{label} object"),
                )
            )
    return tuple(sorted(relations, key=lambda item: (item.subject_iri, item.predicate_iri, item.object_iri)))


def _concepts(graph: Graph) -> tuple[DoeOstiConcept, ...]:
    concepts: list[DoeOstiConcept] = []
    for subject in set(graph.subjects(RDF.type, SKOS.Concept)):
        concept_iri = _iri(subject, "concept")
        schemes = tuple(sorted(_iri(item, "skos:inScheme object") for item in graph.objects(subject, SKOS.inScheme)))
        top_schemes = tuple(
            sorted(_iri(item, "skos:topConceptOf object") for item in graph.objects(subject, SKOS.topConceptOf))
        )
        concepts.append(DoeOstiConcept(concept_iri=concept_iri, scheme_iris=schemes, top_concept_of_iris=top_schemes))
    return tuple(sorted(concepts, key=lambda item: item.concept_iri))


def _concept_schemes(graph: Graph) -> tuple[DoeOstiConceptScheme, ...]:
    schemes: list[DoeOstiConceptScheme] = []
    for subject in set(graph.subjects(RDF.type, SKOS.ConceptScheme)):
        scheme_iri = _iri(subject, "concept scheme")
        top_concepts = tuple(
            sorted(_iri(item, "skos:hasTopConcept object") for item in graph.objects(subject, SKOS.hasTopConcept))
        )
        schemes.append(DoeOstiConceptScheme(scheme_iri=scheme_iri, top_concept_iris=top_concepts))
    return tuple(sorted(schemes, key=lambda item: item.scheme_iri))


def parse_doe_osti_thesaurus_rdfxml(
    source: str | bytes,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
    expected_concept_scheme_iri: str | None = DOE_OSTI_CONCEPT_SCHEME_IRI,
) -> DoeOstiThesaurus:
    """Parse one DOE OSTI Semantic Thesaurus RDF/XML payload into deterministic, lossless feature rows.

    This never turns a concept's own publisher-supplied numeric IRI into a
    minted identifier of any other shape, and it refuses (rather than drops)
    any predicate or ``rdf:type`` object outside the exact allow-list this
    research pass verified against the real 2020-09-30 distribution.
    """

    _require_absolute_iri(source_url, "source_url")
    payload = _source_payload(source)
    source_sha256 = _DIGEST_PREFIX + hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None:
        _expected_hex(expected_sha256)
        if source_sha256 != expected_sha256:
            raise DoeOstiThesaurusError(f"source digest mismatch: expected {expected_sha256}, got {source_sha256}")
    if expected_byte_length is not None:
        if expected_byte_length <= 0:
            raise DoeOstiThesaurusError("expected_byte_length must be positive")
        if len(payload) != expected_byte_length:
            raise DoeOstiThesaurusError(
                f"source byte length mismatch: expected {expected_byte_length}, got {len(payload)}"
            )

    graph = Graph()
    try:
        graph.parse(data=payload, publicID=source_url, format="xml")
    except Exception as error:
        raise DoeOstiThesaurusError(f"could not parse DOE OSTI Semantic Thesaurus RDF/XML: {error}") from error

    _check_predicate_allow_list(graph)
    _check_rdf_type_allow_list(graph)

    concept_schemes = _concept_schemes(graph)
    if len(concept_schemes) != 1:
        raise DoeOstiThesaurusError(f"source must declare exactly one skos:ConceptScheme, found {len(concept_schemes)}")
    concept_scheme_iri = concept_schemes[0].scheme_iri
    if expected_concept_scheme_iri is not None and concept_scheme_iri != expected_concept_scheme_iri:
        raise DoeOstiThesaurusError(
            f"concept scheme mismatch: expected {expected_concept_scheme_iri!r}, got {concept_scheme_iri!r}"
        )

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

    return DoeOstiThesaurus(
        source_url=source_url,
        source_sha256=source_sha256,
        source_bytes=len(payload),
        triple_count=len(graph),
        source_iris=source_iris,
        predicate_counts=tuple(
            DoeOstiPredicateCount(predicate_iri=predicate, assertion_count=count)
            for predicate, count in sorted(predicate_counts.items())
        ),
        concept_scheme_iri=concept_scheme_iri,
        concepts=_concepts(graph),
        concept_schemes=concept_schemes,
        labels=_labels(graph),
        notes=_notes(graph),
        semantic_relations=_iri_relations(graph, SEMANTIC_RELATION_PREDICATE_IRIS, label="SKOS semantic relation"),
        structure_relations=_iri_relations(graph, STRUCTURE_RELATION_PREDICATE_IRIS, label="SKOS structure relation"),
    )


def parse_doe_osti_thesaurus_file(
    path: Path,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
    expected_concept_scheme_iri: str | None = DOE_OSTI_CONCEPT_SCHEME_IRI,
) -> DoeOstiThesaurus:
    """Parse one local RDF/XML file while retaining its external source identity."""

    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise DoeOstiThesaurusError(f"DOE OSTI Semantic Thesaurus source is not a regular file: {source_path}")
    return parse_doe_osti_thesaurus_rdfxml(
        source_path.read_bytes(),
        source_url=source_url,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
        expected_concept_scheme_iri=expected_concept_scheme_iri,
    )


@dataclass(frozen=True, slots=True)
class DoeOstiThesaurusRelease:
    """One exact, externally published DOE OSTI Semantic Thesaurus RDF/XML distribution."""

    version: str
    concept_scheme_iri: str
    landing_page_url: str
    doi_url: str
    stated_publication_date: str
    source_url: str
    expected_sha256: str
    expected_byte_length: int
    filename: str
    publisher: str = DOE_OSTI_PUBLISHER

    def __post_init__(self) -> None:
        if not self.version:
            raise DoeOstiThesaurusError("version must not be empty")
        _require_absolute_iri(self.concept_scheme_iri, "concept_scheme_iri")
        _validate_source_url(self.landing_page_url)
        _require_absolute_iri(self.doi_url, "doi_url")
        if not self.stated_publication_date.strip():
            raise DoeOstiThesaurusError("stated_publication_date must not be empty")
        _validate_source_url(self.source_url)
        _expected_hex(self.expected_sha256)
        if self.expected_byte_length <= 0:
            raise DoeOstiThesaurusError("expected_byte_length must be positive")
        if not self.filename or Path(self.filename).name != self.filename:
            raise DoeOstiThesaurusError("filename must be one plain path component")
        if not self.publisher:
            raise DoeOstiThesaurusError("publisher must not be empty")


# The exact, verified 2020-09-30 distribution this research pass captured
# 2026-08-03. See the module docstring and DOE_OSTI_THESAURUS_VERIFICATION_GAPS
# for what remains unverified about it.
DOE_OSTI_THESAURUS_V1_2020 = DoeOstiThesaurusRelease(
    version="v1-2020",
    concept_scheme_iri=DOE_OSTI_CONCEPT_SCHEME_IRI,
    landing_page_url=DOE_OSTI_LANDING_PAGE_URL,
    doi_url=DOE_OSTI_DOI_URL,
    stated_publication_date=DOE_OSTI_STATED_PUBLICATION_DATE,
    source_url="https://www.osti.gov/servlets/purl/1668761",
    expected_sha256="sha256:aeb9fb2d16caff675c7c9e12e0baff04ac4aded07488944acdf73ed859abe1d5",
    expected_byte_length=18_087_998,
    filename="osti-semantic-thesaurus-v1-2020.rdf",
)


@dataclass(frozen=True, slots=True)
class DoeOstiFetchedResource:
    """One bounded response supplied by an acquisition transport."""

    requested_url: str
    resolved_url: str
    status_code: int
    content_type: str | None
    body: bytes

    def __post_init__(self) -> None:
        for value, field in ((self.requested_url, "requested_url"), (self.resolved_url, "resolved_url")):
            _validate_source_url(value)
        if self.status_code < 100 or self.status_code > 599:
            raise DoeOstiThesaurusError("status_code must be an HTTP status")
        if not isinstance(self.body, bytes):
            raise DoeOstiThesaurusError("resource body must be bytes")


class DoeOstiThesaurusFetcher(Protocol):
    """Transport boundary used by explicit DOE OSTI Semantic Thesaurus acquisition."""

    def __call__(self, url: str, *, timeout_seconds: float, max_bytes: int) -> DoeOstiFetchedResource: ...


DOE_OSTI_USER_AGENT = (
    "RefSpec bounded DOE OSTI Semantic Thesaurus resolver/1.0 (research capture; contact via repository)"
)
# The real 2020-09-30 distribution is 18,087,998 bytes; this default gives
# comfortable headroom without being an unbounded read.
DEFAULT_MAX_DOE_OSTI_THESAURUS_BYTES = 32 * 1024 * 1024


def fetch_doe_osti_thesaurus_with_urllib(
    url: str,
    *,
    timeout_seconds: float,
    max_bytes: int,
) -> DoeOstiFetchedResource:
    """Fetch one distribution URL directly; callers must opt into this transport."""

    if timeout_seconds <= 0:
        raise DoeOstiThesaurusError("timeout_seconds must be positive")
    if max_bytes <= 0:
        raise DoeOstiThesaurusError("max_bytes must be positive")
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/rdf+xml", "User-Agent": DOE_OSTI_USER_AGENT},
        method="GET",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as error:
        raise DoeOstiThesaurusError(f"DOE OSTI Semantic Thesaurus returned HTTP {error.code} for {url}") from error
    except (OSError, urllib.error.URLError) as error:
        raise DoeOstiThesaurusError(f"could not fetch {url}: {error}") from error
    with response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise DoeOstiThesaurusError(f"DOE OSTI Semantic Thesaurus response exceeds max_bytes={max_bytes}: {url}")
        return DoeOstiFetchedResource(
            requested_url=url,
            resolved_url=response.geturl(),
            status_code=getattr(response, "status", 200),
            content_type=response.headers.get("Content-Type"),
            body=body,
        )


def acquire_doe_osti_thesaurus_export(
    source_url: str = DOE_OSTI_THESAURUS_V1_2020.source_url,
    *,
    fetch: DoeOstiThesaurusFetcher | None = None,
    allow_direct_network: bool = False,
    timeout_seconds: float = 60.0,
    max_bytes: int = DEFAULT_MAX_DOE_OSTI_THESAURUS_BYTES,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
    expected_concept_scheme_iri: str | None = DOE_OSTI_CONCEPT_SCHEME_IRI,
) -> DoeOstiThesaurus:
    """Acquire, verify, and parse one DOE OSTI Semantic Thesaurus distribution.

    Importing this module never opens a network connection. A caller must
    either inject ``fetch`` or set ``allow_direct_network=True``.
    """

    if timeout_seconds <= 0:
        raise DoeOstiThesaurusError("timeout_seconds must be positive")
    if max_bytes <= 0:
        raise DoeOstiThesaurusError("max_bytes must be positive")
    if fetch is None:
        if not allow_direct_network:
            raise DoeOstiThesaurusError(
                "live DOE OSTI Semantic Thesaurus acquisition requires fetch or allow_direct_network=True"
            )
        fetch = fetch_doe_osti_thesaurus_with_urllib

    resource = fetch(source_url, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
    if resource.requested_url != source_url:
        raise DoeOstiThesaurusError("thesaurus fetcher returned a different requested_url")
    if resource.status_code != 200:
        raise DoeOstiThesaurusError(
            f"DOE OSTI Semantic Thesaurus returned HTTP {resource.status_code} for {source_url}"
        )
    if len(resource.body) > max_bytes:
        raise DoeOstiThesaurusError(f"DOE OSTI Semantic Thesaurus response exceeds max_bytes={max_bytes}")
    return parse_doe_osti_thesaurus_rdfxml(
        resource.body,
        source_url=resource.resolved_url,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
        expected_concept_scheme_iri=expected_concept_scheme_iri,
    )


def doe_osti_thesaurus_capture_manifest(
    thesaurus: DoeOstiThesaurus,
    *,
    retrieved_at: str,
) -> dict[str, object]:
    """Deterministic, closed description of one verified DOE OSTI Semantic Thesaurus capture.

    ``sourceIsNativeSkosRdf`` and ``conceptIdentityClaimed`` stay true: this
    is a real SKOS/RDF export and its concept IRIs are the publisher's own.
    The catalog's "Reject/defer canonical use" decision remains policy, so
    this manifest records staleness without carrying a permission field.
    """

    if not retrieved_at.strip():
        raise DoeOstiThesaurusError("retrieved_at must not be empty")
    return {
        "kind": "skosVocabulary",
        "catalogRole": DOE_OSTI_THESAURUS_CATALOG_ROLE,
        "publisher": DOE_OSTI_PUBLISHER,
        "landingPageUrl": DOE_OSTI_LANDING_PAGE_URL,
        "doiUrl": DOE_OSTI_DOI_URL,
        "statedPublicationDate": DOE_OSTI_STATED_PUBLICATION_DATE,
        "sourceUrl": thesaurus.source_url,
        "sourceSha256": thesaurus.source_sha256,
        "sourceBytes": thesaurus.source_bytes,
        "retrievedAt": retrieved_at,
        "conceptSchemeIri": thesaurus.concept_scheme_iri,
        "nativeFormat": "rdfXmlSkos",
        "sourceIsNativeSkosRdf": True,
        "conceptIdentityClaimed": True,
        "role": "energyPhysicalScienceMappingResearch",
        "verificationGaps": [dataclasses.asdict(gap) for gap in DOE_OSTI_THESAURUS_VERIFICATION_GAPS],
        "counts": dataclasses.asdict(thesaurus.counts),
    }


def doe_osti_thesaurus_capture_digest(
    thesaurus: DoeOstiThesaurus,
    *,
    retrieved_at: str,
) -> str:
    """A stable sha256 over the deterministic capture manifest."""

    manifest = doe_osti_thesaurus_capture_manifest(thesaurus, retrieved_at=retrieved_at)
    return _DIGEST_PREFIX + hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()


__all__ = [
    "ALLOWED_PREDICATE_IRIS",
    "BROADER_PREDICATE_IRI",
    "DEFAULT_MAX_DOE_OSTI_THESAURUS_BYTES",
    "DEFINITION_PREDICATE_IRI",
    "DOE_OSTI_CONCEPT_SCHEME_IRI",
    "DOE_OSTI_DOI_URL",
    "DOE_OSTI_LANDING_PAGE_URL",
    "DOE_OSTI_PUBLISHER",
    "DOE_OSTI_STATED_PUBLICATION_DATE",
    "DOE_OSTI_THESAURUS_CATALOG_ROLE",
    "DOE_OSTI_THESAURUS_V1_2020",
    "DOE_OSTI_THESAURUS_VERIFICATION_GAPS",
    "DOE_OSTI_USER_AGENT",
    "HAS_TOP_CONCEPT_PREDICATE_IRI",
    "IN_SCHEME_PREDICATE_IRI",
    "NARROWER_PREDICATE_IRI",
    "NOTE_PREDICATE_IRIS",
    "PREF_LABEL_PREDICATE_IRI",
    "RELATED_PREDICATE_IRI",
    "SCOPE_NOTE_PREDICATE_IRI",
    "SEMANTIC_RELATION_PREDICATE_IRIS",
    "STRUCTURE_RELATION_PREDICATE_IRIS",
    "TOP_CONCEPT_OF_PREDICATE_IRI",
    "DoeOstiConcept",
    "DoeOstiConceptScheme",
    "DoeOstiFetchedResource",
    "DoeOstiImportCounts",
    "DoeOstiIriRelation",
    "DoeOstiLabel",
    "DoeOstiLiteral",
    "DoeOstiNote",
    "DoeOstiPredicateCount",
    "DoeOstiThesaurus",
    "DoeOstiThesaurusError",
    "DoeOstiThesaurusFetcher",
    "DoeOstiThesaurusRelease",
    "DoeOstiVerificationGap",
    "acquire_doe_osti_thesaurus_export",
    "doe_osti_thesaurus_capture_digest",
    "doe_osti_thesaurus_capture_manifest",
    "fetch_doe_osti_thesaurus_with_urllib",
    "parse_doe_osti_thesaurus_file",
    "parse_doe_osti_thesaurus_rdfxml",
]
