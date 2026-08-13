"""Lossless SKOS reader and acquisition for a pinned EuroVoc release.

The official SKOS Core distribution is a one-member ZIP containing RDF/XML.
This module verifies the published ZIP and its RDF member independently,
then preserves the publisher's concept and concept-scheme IRIs, identifiers,
preferred/alternate/hidden label roles, scheme membership, and direct SKOS
hierarchy assertions. It does not infer a transitive hierarchy or mint source
identifiers.

Some richer EuroVoc serializations add ``eurovoc:schema#Domain`` and
``eurovoc:schema#MicroThesaurus`` types plus redundant identifier predicates.
The reader retains those distinctions when present while also supporting the
SKOS Core release, which identifies resources with ``skos:notation`` and does
not carry the richer types.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import urllib.parse
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal as LiteralType

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, SKOS, XSD
from rdflib.term import Identifier

from refspec.registry.infrastructure.pinned_acquisition import (
    AcquiredPinnedSource,
    AcquisitionMode,
    PinnedAcquisitionError,
    PinnedAcquisitionLabels,
    acquire_pinned_source,
    expected_digest_hex,
)
from refspec.registry.infrastructure.source_controlled_resource import LabelRole as EuroVocLabelRole

DC11 = Namespace("http://purl.org/dc/elements/1.1/")
EUVOC = Namespace("http://publications.europa.eu/ontology/euvoc#")
EUROVOC_SCHEMA = Namespace("http://eurovoc.europa.eu/schema#")

PREF_LABEL_PREDICATE_IRI = str(SKOS.prefLabel)
ALT_LABEL_PREDICATE_IRI = str(SKOS.altLabel)
HIDDEN_LABEL_PREDICATE_IRI = str(SKOS.hiddenLabel)
DEFINITION_PREDICATE_IRI = str(SKOS.definition)
SCOPE_NOTE_PREDICATE_IRI = str(SKOS.scopeNote)
SCHEME_MEMBERSHIP_PREDICATE_IRI = str(SKOS.inScheme)
TOP_CONCEPT_OF_PREDICATE_IRI = str(SKOS.topConceptOf)
HAS_TOP_CONCEPT_PREDICATE_IRI = str(SKOS.hasTopConcept)
STATUS_PREDICATE_IRI = str(EUVOC.status)
BROADER_PREDICATE_IRI = str(SKOS.broader)
NARROWER_PREDICATE_IRI = str(SKOS.narrower)
RELATED_PREDICATE_IRI = str(SKOS.related)
HIERARCHY_PREDICATE_IRIS = (BROADER_PREDICATE_IRI, NARROWER_PREDICATE_IRI)
SEMANTIC_RELATION_PREDICATE_IRIS = (*HIERARCHY_PREDICATE_IRIS, RELATED_PREDICATE_IRI)
EUROVOC_CONCEPT_SCHEME_IRI = "http://eurovoc.europa.eu/100141"
EUROVOC_DOMAINS_SCHEME_IRI = "http://eurovoc.europa.eu/domains"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class EuroVocThesaurusError(ValueError):
    """A EuroVoc SKOS feature cannot be preserved, or its role was misused."""


@dataclass(frozen=True, slots=True)
class EuroVocLiteral:
    """One RDF literal with its lexical form and required language tag."""

    lexical_form: str
    language_tag: str | None


@dataclass(frozen=True, slots=True)
class EuroVocLabelExpression:
    """One authored SKOS label assertion for any EuroVoc resource."""

    subject_iri: str
    property_iri: str
    role: EuroVocLabelRole
    value: EuroVocLiteral


@dataclass(frozen=True, slots=True)
class EuroVocIriRelation:
    """One RDF assertion whose subject and object remain exact source IRIs."""

    subject_iri: str
    predicate_iri: str
    object_iri: str


@dataclass(frozen=True, slots=True)
class EuroVocLiteralAssertion:
    """One authored literal assertion outside the SKOS label roles."""

    subject_iri: str
    property_iri: str
    value: EuroVocLiteral


@dataclass(frozen=True, slots=True)
class EuroVocDomain:
    """One of EuroVoc's 21 top-level domains, kept apart from its concepts."""

    domain_iri: str
    code: str


@dataclass(frozen=True, slots=True)
class EuroVocDomainGroup:
    """One EuroVoc micro-thesaurus, grouped under exactly one domain."""

    group_iri: str
    code: str
    domain_iri: str


@dataclass(frozen=True, slots=True)
class EuroVocConcept:
    """One EuroVoc thesaurus concept, excluding domain-typed resources."""

    concept_iri: str
    notation: str


@dataclass(frozen=True, slots=True)
class EuroVocConceptScheme:
    """One source-declared SKOS concept scheme.

    The main EuroVoc scheme and the domains grouping scheme have no notation;
    micro-thesaurus schemes carry their four-digit publisher notation.
    """

    scheme_iri: str
    notation: str | None


@dataclass(frozen=True, slots=True)
class EuroVocVocabulary:
    """A deterministic, source-faithful EuroVoc SKOS release."""

    source_url: str
    source_sha256: str
    source_bytes: int
    source_format: LiteralType["turtle", "xml"]
    triple_count: int
    source_iris: tuple[str, ...]
    thesaurus_iri: str
    thesaurus_version: str | None
    domains_scheme_iri: str | None
    domains: tuple[EuroVocDomain, ...]
    domain_groups: tuple[EuroVocDomainGroup, ...]
    concept_schemes: tuple[EuroVocConceptScheme, ...]
    concepts: tuple[EuroVocConcept, ...]
    labels: tuple[EuroVocLabelExpression, ...]
    annotations: tuple[EuroVocLiteralAssertion, ...]
    scheme_memberships: tuple[EuroVocIriRelation, ...]
    top_concept_of_relations: tuple[EuroVocIriRelation, ...]
    has_top_concept_relations: tuple[EuroVocIriRelation, ...]
    hierarchy_relations: tuple[EuroVocIriRelation, ...]
    semantic_relations: tuple[EuroVocIriRelation, ...]
    status_assertions: tuple[EuroVocIriRelation, ...]


def _require_absolute_iri(value: str, label: str) -> str:
    if not urllib.parse.urlsplit(value).scheme:
        raise EuroVocThesaurusError(f"{label} must be an absolute IRI, got {value!r}")
    return value


def _iri(term: Identifier, label: str) -> str:
    if not isinstance(term, URIRef):
        kind = "blank node" if isinstance(term, BNode) else type(term).__name__
        raise EuroVocThesaurusError(f"{label} must be an IRI, got {kind}")
    return _require_absolute_iri(str(term), label)


def _literal(term: Identifier, label: str) -> EuroVocLiteral:
    if not isinstance(term, Literal):
        raise EuroVocThesaurusError(f"{label} must be an RDF literal")
    language_tag = str(term.language) if term.language is not None else None
    return EuroVocLiteral(lexical_form=str(term), language_tag=language_tag)


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
        raise EuroVocThesaurusError(f"EuroVoc RDF is not valid UTF-8 at byte {error.start}") from error
    return payload


def _label_expressions(graph: Graph) -> tuple[EuroVocLabelExpression, ...]:
    properties: tuple[tuple[URIRef, EuroVocLabelRole], ...] = (
        (SKOS.prefLabel, "preferred"),
        (SKOS.altLabel, "alternate"),
        (SKOS.hiddenLabel, "hidden"),
    )
    labels: list[EuroVocLabelExpression] = []
    preferred_by_language: dict[tuple[str, str], str] = {}
    for predicate, role in properties:
        for subject, value in graph.subject_objects(predicate):
            subject_iri = _iri(subject, f"{role} label subject")
            literal = _literal(value, f"{role} label")
            if literal.language_tag is None:
                raise EuroVocThesaurusError(
                    f"{role} label on {subject_iri} is untagged; EuroVoc labels must retain a language tag"
                )
            if role == "preferred":
                key = (subject_iri, literal.language_tag.casefold())
                previous = preferred_by_language.get(key)
                if previous is not None and previous != literal.lexical_form:
                    raise EuroVocThesaurusError(
                        f"{subject_iri} has more than one preferred label for language {literal.language_tag}"
                    )
                preferred_by_language[key] = literal.lexical_form
            labels.append(
                EuroVocLabelExpression(
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
            ),
        )
    )


def _iri_relations(
    graph: Graph,
    predicate_iris: tuple[str, ...],
    *,
    label: str,
) -> tuple[EuroVocIriRelation, ...]:
    relations: list[EuroVocIriRelation] = []
    for predicate_iri in predicate_iris:
        for subject, obj in graph.subject_objects(URIRef(predicate_iri)):
            relations.append(
                EuroVocIriRelation(
                    subject_iri=_iri(subject, f"{label} subject"),
                    predicate_iri=predicate_iri,
                    object_iri=_iri(obj, f"{label} object"),
                )
            )
    return tuple(
        sorted(
            relations,
            key=lambda item: (item.subject_iri, item.predicate_iri, item.object_iri),
        )
    )


def _literal_assertions(
    graph: Graph,
    predicate_iris: tuple[str, ...],
    *,
    label: str,
) -> tuple[EuroVocLiteralAssertion, ...]:
    assertions: list[EuroVocLiteralAssertion] = []
    for predicate_iri in predicate_iris:
        for subject, value in graph.subject_objects(URIRef(predicate_iri)):
            assertions.append(
                EuroVocLiteralAssertion(
                    subject_iri=_iri(subject, f"{label} subject"),
                    property_iri=predicate_iri,
                    value=_literal(value, label),
                )
            )
    return tuple(
        sorted(
            assertions,
            key=lambda item: (
                item.subject_iri,
                item.property_iri,
                item.value.language_tag or "",
                item.value.lexical_form,
            ),
        )
    )


def _identifier_literal(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    *,
    predicate_label: str,
) -> str | None:
    values = list(graph.objects(subject, predicate))
    if not values:
        return None
    if len(values) > 1:
        raise EuroVocThesaurusError(f"{subject} has more than one {predicate_label}")
    value = values[0]
    if (
        not isinstance(value, Literal)
        or value.language is not None
        or (value.datatype is not None and str(value.datatype) != str(XSD.string))
    ):
        raise EuroVocThesaurusError(f"{subject} {predicate_label} must be a plain string literal")
    return str(value)


def _required_source_identifier(graph: Graph, subject: URIRef, *, label: str) -> str:
    """Return the one publisher-supplied identifier, refusing to mint one.

    Rich EuroVoc exports repeat an identifier on ``dc:identifier``,
    ``dcterms:identifier``, and ``skos:notation``. SKOS Core carries only the
    notation. All values that are present must agree.
    """

    dc_value = _identifier_literal(graph, subject, DC11.identifier, predicate_label="dc:identifier")
    dcterms_value = _identifier_literal(graph, subject, DCTERMS.identifier, predicate_label="dcterms:identifier")
    notation_value = _identifier_literal(graph, subject, SKOS.notation, predicate_label="skos:notation")
    supplied = [value for value in (dc_value, dcterms_value, notation_value) if value is not None]
    if not supplied:
        raise EuroVocThesaurusError(
            f"{label} {subject} has no publisher-supplied identifier "
            "(dc:identifier, dcterms:identifier, or skos:notation)"
        )
    if len(set(supplied)) != 1:
        raise EuroVocThesaurusError(
            f"{label} {subject} dc:identifier, dcterms:identifier, and skos:notation disagree; "
            "the reader will not guess between them"
        )
    return supplied[0]


def _one_iri_object(graph: Graph, subject: URIRef, predicate: URIRef, *, label: str) -> str:
    objects = list(graph.objects(subject, predicate))
    if len(objects) != 1:
        raise EuroVocThesaurusError(f"{label} must have exactly one {predicate}")
    return _iri(objects[0], label)


def _domains(graph: Graph) -> tuple[EuroVocDomain, ...]:
    domains: list[EuroVocDomain] = []
    subjects = set(graph.subjects(RDF.type, EUROVOC_SCHEMA.Domain))
    subjects.update(graph.subjects(SKOS.inScheme, URIRef(EUROVOC_DOMAINS_SCHEME_IRI)))
    for subject in subjects:
        domain_iri = _iri(subject, "domain")
        code = _required_source_identifier(graph, subject, label="domain")
        domains.append(EuroVocDomain(domain_iri=domain_iri, code=code))
    return tuple(sorted(domains, key=lambda item: item.domain_iri))


def _domains_scheme_iri(graph: Graph, domains: tuple[EuroVocDomain, ...]) -> str | None:
    if not domains:
        return None
    scheme_iris: set[str] = set()
    for domain in domains:
        objects = {
            _iri(item, "domain skos:inScheme object") for item in graph.objects(URIRef(domain.domain_iri), SKOS.inScheme)
        }
        if len(objects) != 1:
            raise EuroVocThesaurusError(f"domain {domain.domain_iri} must have exactly one skos:inScheme grouping IRI")
        scheme_iris |= objects
    if len(scheme_iris) != 1:
        raise EuroVocThesaurusError("EuroVoc domains disagree on their shared skos:inScheme grouping scheme")
    return next(iter(scheme_iris))


def _domain_groups(graph: Graph, domains_by_iri: dict[str, EuroVocDomain]) -> tuple[EuroVocDomainGroup, ...]:
    groups: list[EuroVocDomainGroup] = []
    for subject in set(graph.subjects(RDF.type, EUROVOC_SCHEMA.MicroThesaurus)):
        group_iri = _iri(subject, "domain group")
        code = _required_source_identifier(graph, subject, label="domain group")
        domain_iri = _one_iri_object(graph, subject, EUVOC.domain, label=f"domain group {group_iri} euvoc:domain")
        domain = domains_by_iri.get(domain_iri)
        if domain is not None and not code.startswith(domain.code):
            raise EuroVocThesaurusError(
                f"domain group {group_iri} has code {code!r}, which does not start with the prefix "
                f"of its declared domain {domain_iri} (code {domain.code!r})"
            )
        groups.append(EuroVocDomainGroup(group_iri=group_iri, code=code, domain_iri=domain_iri))
    return tuple(sorted(groups, key=lambda item: item.group_iri))


def _concepts(graph: Graph, domain_iris: set[str]) -> tuple[EuroVocConcept, ...]:
    concepts: list[EuroVocConcept] = []
    for subject in set(graph.subjects(RDF.type, SKOS.Concept)):
        concept_iri = _iri(subject, "concept")
        if concept_iri in domain_iris:
            # EuroVoc models domains as skos:Concept resources. Keep them and
            # ordinary thesaurus concepts as disjoint source record kinds.
            continue
        notation = _required_source_identifier(graph, subject, label="concept")
        concepts.append(EuroVocConcept(concept_iri=concept_iri, notation=notation))
    return tuple(sorted(concepts, key=lambda item: item.concept_iri))


def _concept_schemes(graph: Graph) -> tuple[EuroVocConceptScheme, ...]:
    schemes: list[EuroVocConceptScheme] = []
    for subject in set(graph.subjects(RDF.type, SKOS.ConceptScheme)):
        scheme_iri = _iri(subject, "concept scheme")
        notation = _identifier_literal(graph, subject, SKOS.notation, predicate_label="skos:notation")
        schemes.append(EuroVocConceptScheme(scheme_iri=scheme_iri, notation=notation))
    return tuple(sorted(schemes, key=lambda item: item.scheme_iri))


def _thesaurus_identity(
    graph: Graph,
    *,
    expected_thesaurus_iri: str | None,
    release_version: str | None,
) -> tuple[str, str | None]:
    rich_subjects = set(graph.subjects(RDF.type, EUROVOC_SCHEMA.Thesaurus))
    scheme_subjects = set(graph.subjects(RDF.type, SKOS.ConceptScheme))
    if expected_thesaurus_iri is not None:
        subject = URIRef(_require_absolute_iri(expected_thesaurus_iri, "expected_thesaurus_iri"))
        if subject not in scheme_subjects:
            raise EuroVocThesaurusError(
                f"expected EuroVoc thesaurus {expected_thesaurus_iri} is not a skos:ConceptScheme"
            )
    elif len(rich_subjects) == 1:
        subject = next(iter(rich_subjects))
    elif URIRef(EUROVOC_CONCEPT_SCHEME_IRI) in scheme_subjects:
        subject = URIRef(EUROVOC_CONCEPT_SCHEME_IRI)
    elif len(scheme_subjects) == 1:
        subject = next(iter(scheme_subjects))
    else:
        raise EuroVocThesaurusError(
            "EuroVoc RDF must identify one main thesaurus concept scheme"
        )
    thesaurus_iri = _iri(subject, "thesaurus")
    versions = list(graph.objects(subject, OWL.versionInfo))
    if len(versions) > 1 or (versions and not isinstance(versions[0], Literal)):
        raise EuroVocThesaurusError(f"{thesaurus_iri} must have at most one owl:versionInfo literal")
    source_version = str(versions[0]) if versions else None
    if release_version is not None and source_version is not None and source_version != release_version:
        raise EuroVocThesaurusError(
            f"EuroVoc version mismatch: release says {release_version!r}, RDF says {source_version!r}"
        )
    return thesaurus_iri, release_version or source_version


def _parse_eurovoc_rdf(
    source: str | bytes,
    *,
    source_url: str,
    rdf_format: LiteralType["turtle", "xml"],
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
    expected_thesaurus_iri: str | None = None,
    release_version: str | None = None,
) -> EuroVocVocabulary:
    _require_absolute_iri(source_url, "source_url")
    payload = _source_payload(source)
    source_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None:
        if _DIGEST.fullmatch(expected_sha256) is None:
            raise EuroVocThesaurusError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if source_sha256 != expected_sha256:
            raise EuroVocThesaurusError(f"source digest mismatch: expected {expected_sha256}, got {source_sha256}")
    if expected_byte_length is not None:
        if expected_byte_length <= 0:
            raise EuroVocThesaurusError("expected_byte_length must be positive")
        if len(payload) != expected_byte_length:
            raise EuroVocThesaurusError(f"source byte length mismatch: expected {expected_byte_length}, got {len(payload)}")

    graph = Graph()
    try:
        graph.parse(data=payload, format=rdf_format, publicID=source_url)
    except Exception as error:
        raise EuroVocThesaurusError(f"could not parse EuroVoc {rdf_format} RDF: {error}") from error

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

    thesaurus_iri, thesaurus_version = _thesaurus_identity(
        graph,
        expected_thesaurus_iri=expected_thesaurus_iri,
        release_version=release_version,
    )
    domains = _domains(graph)
    domains_by_iri = {item.domain_iri: item for item in domains}
    domain_groups = _domain_groups(graph, domains_by_iri)
    concept_schemes = _concept_schemes(graph)
    concepts = _concepts(graph, set(domains_by_iri))
    domains_scheme_iri = _domains_scheme_iri(graph, domains)
    if domains_scheme_iri is None and any(
        item.scheme_iri == EUROVOC_DOMAINS_SCHEME_IRI for item in concept_schemes
    ):
        domains_scheme_iri = EUROVOC_DOMAINS_SCHEME_IRI

    return EuroVocVocabulary(
        source_url=source_url,
        source_sha256=source_sha256,
        source_bytes=len(payload),
        source_format=rdf_format,
        triple_count=len(graph),
        source_iris=source_iris,
        thesaurus_iri=thesaurus_iri,
        thesaurus_version=thesaurus_version,
        domains_scheme_iri=domains_scheme_iri,
        domains=domains,
        domain_groups=domain_groups,
        concept_schemes=concept_schemes,
        concepts=concepts,
        labels=_label_expressions(graph),
        annotations=_literal_assertions(
            graph,
            (DEFINITION_PREDICATE_IRI, SCOPE_NOTE_PREDICATE_IRI),
            label="SKOS definition or scope note",
        ),
        scheme_memberships=_iri_relations(graph, (SCHEME_MEMBERSHIP_PREDICATE_IRI,), label="skos:inScheme"),
        top_concept_of_relations=_iri_relations(graph, (TOP_CONCEPT_OF_PREDICATE_IRI,), label="skos:topConceptOf"),
        has_top_concept_relations=_iri_relations(graph, (HAS_TOP_CONCEPT_PREDICATE_IRI,), label="skos:hasTopConcept"),
        hierarchy_relations=_iri_relations(graph, HIERARCHY_PREDICATE_IRIS, label="SKOS hierarchy relation"),
        semantic_relations=_iri_relations(
            graph,
            SEMANTIC_RELATION_PREDICATE_IRIS,
            label="SKOS semantic relation",
        ),
        status_assertions=_iri_relations(graph, (STATUS_PREDICATE_IRI,), label="euvoc:status"),
    )


def parse_eurovoc_turtle(
    source: str | bytes,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
    expected_thesaurus_iri: str | None = None,
    release_version: str | None = None,
) -> EuroVocVocabulary:
    """Parse one EuroVoc Turtle payload without imposing an adoption policy."""

    return _parse_eurovoc_rdf(
        source,
        source_url=source_url,
        rdf_format="turtle",
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
        expected_thesaurus_iri=expected_thesaurus_iri,
        release_version=release_version,
    )


def parse_eurovoc_rdf_xml(
    source: str | bytes,
    *,
    source_url: str,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
    expected_thesaurus_iri: str | None = None,
    release_version: str | None = None,
) -> EuroVocVocabulary:
    """Parse one EuroVoc RDF/XML payload without deriving extra relations."""

    return _parse_eurovoc_rdf(
        source,
        source_url=source_url,
        rdf_format="xml",
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
        expected_thesaurus_iri=expected_thesaurus_iri,
        release_version=release_version,
    )


def parse_eurovoc_file(
    path: Path,
    *,
    source_url: str,
    rdf_format: LiteralType["turtle", "xml"] | None = None,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
    expected_thesaurus_iri: str | None = None,
    release_version: str | None = None,
) -> EuroVocVocabulary:
    """Parse one local RDF file while retaining its external source identity."""

    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise EuroVocThesaurusError(f"EuroVoc source is not a regular file: {source_path}")
    selected_format = rdf_format
    if selected_format is None:
        selected_format = "turtle" if source_path.suffix.casefold() in {".ttl", ".turtle"} else "xml"
    return _parse_eurovoc_rdf(
        source_path.read_bytes(),
        source_url=source_url,
        rdf_format=selected_format,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
        expected_thesaurus_iri=expected_thesaurus_iri,
        release_version=release_version,
    )


# --- Acquisition -----------------------------------------------------------
#
# Importing this module never opens a network connection. A caller must
# provide local files or explicitly allow network acquisition. The ZIP, its
# sole RDF member, and optional metadata are independently pinned.

EUROVOC_PUBLISHER = "Publications Office of the European Union"
EUROVOC_ATTRIBUTION = "Publications Office of the European Union, EuroVoc"
EUROVOC_LICENSE_IRI = "https://creativecommons.org/licenses/by/4.0/"
EUROVOC_LICENSE_LABEL = "Creative Commons Attribution 4.0 International"
EUROVOC_LANDING_PAGE_URL = (
    "https://op.europa.eu/en/web/eu-vocabularies/dataset/-/resource?"
    "uri=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdataset%2Feurovoc"
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class EuroVocAcquisitionError(ValueError):
    """A EuroVoc release could not be acquired without weakening its pins."""


def _expected_hex(expected_sha256: str) -> str:
    try:
        return expected_digest_hex(expected_sha256)
    except PinnedAcquisitionError as error:
        raise EuroVocAcquisitionError(str(error)) from error


def _validate_source_url(source_url: str, label: str = "source_url") -> None:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EuroVocAcquisitionError(f"{label} must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise EuroVocAcquisitionError(f"{label} must not contain credentials")


def _require_absolute_iri_acquisition(value: str, label: str) -> None:
    if not urllib.parse.urlsplit(value).scheme:
        raise EuroVocAcquisitionError(f"{label} must be an absolute IRI")


def _validate_plain_filename(value: str, label: str) -> None:
    if not value or Path(value).name != value:
        raise EuroVocAcquisitionError(f"{label} must be one plain path component")


@dataclass(frozen=True, slots=True)
class EuroVocMetadataSource:
    """One optional, exact EuroVoc release-metadata artifact."""

    source_url: str
    expected_sha256: str
    expected_byte_length: int
    filename: str

    def __post_init__(self) -> None:
        _validate_source_url(self.source_url, "metadata source_url")
        _expected_hex(self.expected_sha256)
        if self.expected_byte_length <= 0:
            raise EuroVocAcquisitionError("metadata expected_byte_length must be positive")
        _validate_plain_filename(self.filename, "metadata filename")


@dataclass(frozen=True, slots=True)
class EuroVocReleaseSource:
    """One exact, externally published EuroVoc SKOS Core ZIP release."""

    release_id: str
    version: str
    issued: str
    concept_scheme_iri: str
    source_url: str
    landing_page_url: str
    expected_sha256: str
    expected_byte_length: int
    filename: str
    member_filename: str
    expected_member_sha256: str
    expected_member_byte_length: int
    metadata_source: EuroVocMetadataSource | None = None
    publisher: str = EUROVOC_PUBLISHER
    attribution: str = EUROVOC_ATTRIBUTION
    license_iri: str = EUROVOC_LICENSE_IRI
    license_label: str = EUROVOC_LICENSE_LABEL

    def __post_init__(self) -> None:
        if not self.release_id or not self.version:
            raise EuroVocAcquisitionError("release_id and version must not be empty")
        if _ISO_DATE.fullmatch(self.issued) is None:
            raise EuroVocAcquisitionError("issued must be an ISO date (YYYY-MM-DD)")
        _require_absolute_iri_acquisition(self.concept_scheme_iri, "concept_scheme_iri")
        _validate_source_url(self.source_url)
        _validate_source_url(self.landing_page_url, "landing_page_url")
        _expected_hex(self.expected_sha256)
        _expected_hex(self.expected_member_sha256)
        if self.expected_byte_length <= 0 or self.expected_member_byte_length <= 0:
            raise EuroVocAcquisitionError("archive and member byte lengths must be positive")
        _validate_plain_filename(self.filename, "filename")
        _validate_plain_filename(self.member_filename, "member_filename")
        _require_absolute_iri_acquisition(self.license_iri, "license_iri")
        if not self.publisher or not self.attribution or not self.license_label:
            raise EuroVocAcquisitionError("publisher, attribution, and license_label must not be empty")


EUROVOC_4_24_METADATA = EuroVocMetadataSource(
    source_url=(
        "https://op.europa.eu/o/opportal-service/euvoc-download-handler?"
        "cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2F"
        "eurovoc%2F20260708-0%2Fttl%2Fmetadata%2Feurovoc_metadata.ttl&"
        "fileName=eurovoc_metadata.ttl"
    ),
    expected_sha256="sha256:2c58402422f8588aada476f3516051e7fc980182130557a0d8c67497ffd8731d",
    expected_byte_length=36_011,
    filename="eurovoc_metadata.ttl",
)

EUROVOC_RELEASE_4_24 = EuroVocReleaseSource(
    release_id="eurovoc-4.24",
    version="4.24",
    issued="2026-07-08",
    concept_scheme_iri=EUROVOC_CONCEPT_SCHEME_IRI,
    source_url=(
        "https://op.europa.eu/o/opportal-service/euvoc-download-handler?"
        "cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2F"
        "eurovoc%2F20260708-0%2Fzip%2Fskos_core%2Feurovoc_in_skos_core_concepts.zip&"
        "fileName=eurovoc_in_skos_core_concepts.zip"
    ),
    landing_page_url=EUROVOC_LANDING_PAGE_URL,
    expected_sha256="sha256:91bdb24e833ba431707f3980a19f475434ea8dcddb2b4d5e32e79e9fc1a0ca2f",
    expected_byte_length=8_567_290,
    filename="eurovoc_in_skos_core_concepts.zip",
    member_filename="eurovoc_in_skos_core_concepts.rdf",
    expected_member_sha256="sha256:6c362f79ad03e325ba1b4818f1ca3a847bb6167c2a8f7167e2e4df91305b6620",
    expected_member_byte_length=60_691_531,
    metadata_source=EUROVOC_4_24_METADATA,
)
EUROVOC_RELEASES: dict[str, EuroVocReleaseSource] = {"4.24": EUROVOC_RELEASE_4_24}


_EUROVOC_ARCHIVE_LABELS = PinnedAcquisitionLabels(
    source_label="EuroVoc release archive",
    cached_location="cached EuroVoc release archive",
    local_file_label="local EuroVoc release archive",
    not_cached_message=(
        "EuroVoc release archive is not cached; provide source_path or set allow_network=True explicitly"
    ),
    request_headers={"User-Agent": "RefSpec explicit EuroVoc source resolver/1.0"},
)
_EUROVOC_METADATA_LABELS = PinnedAcquisitionLabels(
    source_label="EuroVoc release metadata",
    cached_location="cached EuroVoc release metadata",
    local_file_label="local EuroVoc release metadata",
    not_cached_message=(
        "EuroVoc release metadata is not cached; provide metadata_path or set allow_network=True explicitly"
    ),
    request_headers={"User-Agent": "RefSpec explicit EuroVoc metadata resolver/1.0"},
)


@dataclass(frozen=True, slots=True)
class AcquiredEuroVocRelease:
    """One verified EuroVoc RDF member and its independently verified ZIP."""

    release: EuroVocReleaseSource
    path: Path
    archive_path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    archive_sha256: str
    archive_byte_length: int
    cache_hit: bool
    acquisition_mode: AcquisitionMode
    local_source_path: Path | None
    metadata: AcquiredPinnedSource | None


def _verified_member_payload(archive_path: Path, release: EuroVocReleaseSource) -> bytes:
    if archive_path.is_symlink() or not archive_path.is_file():
        raise EuroVocAcquisitionError(f"EuroVoc archive is not a regular file: {archive_path}")
    archive_payload = archive_path.read_bytes()
    if len(archive_payload) != release.expected_byte_length:
        raise EuroVocAcquisitionError(
            "EuroVoc archive byte length mismatch: expected "
            f"{release.expected_byte_length}, got {len(archive_payload)}"
        )
    archive_sha256 = "sha256:" + hashlib.sha256(archive_payload).hexdigest()
    if archive_sha256 != release.expected_sha256:
        raise EuroVocAcquisitionError(
            f"EuroVoc archive digest mismatch: expected {release.expected_sha256}, got {archive_sha256}"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(archive_payload)) as archive:
            members = archive.infolist()
            if len(members) != 1:
                raise EuroVocAcquisitionError(
                    f"EuroVoc archive must contain exactly one member, got {len(members)}"
                )
            member = members[0]
            if member.is_dir() or member.filename != release.member_filename:
                raise EuroVocAcquisitionError(
                    f"EuroVoc archive member must be {release.member_filename!r}, got {member.filename!r}"
                )
            if member.file_size != release.expected_member_byte_length:
                raise EuroVocAcquisitionError(
                    "EuroVoc RDF member byte length mismatch: expected "
                    f"{release.expected_member_byte_length}, got {member.file_size}"
                )
            payload = archive.read(member)
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise EuroVocAcquisitionError(f"could not read EuroVoc ZIP: {error}") from error
    actual_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual_sha256 != release.expected_member_sha256:
        raise EuroVocAcquisitionError(
            "EuroVoc RDF member digest mismatch: expected "
            f"{release.expected_member_sha256}, got {actual_sha256}"
        )
    return payload


def _verify_cached_member(path: Path, release: EuroVocReleaseSource) -> None:
    if path.is_symlink() or not path.is_file():
        raise EuroVocAcquisitionError(f"cached EuroVoc RDF member is not a regular file: {path}")
    payload = path.read_bytes()
    if len(payload) != release.expected_member_byte_length:
        raise EuroVocAcquisitionError(
            "cached EuroVoc RDF member byte length mismatch: expected "
            f"{release.expected_member_byte_length}, got {len(payload)}"
        )
    actual_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual_sha256 != release.expected_member_sha256:
        raise EuroVocAcquisitionError(
            "cached EuroVoc RDF member digest mismatch: expected "
            f"{release.expected_member_sha256}, got {actual_sha256}"
        )


def _publish_member(payload: bytes, release: EuroVocReleaseSource, store_dir: Path) -> tuple[Path, bool]:
    digest_hex = _expected_hex(release.expected_member_sha256)
    final_path = Path(store_dir) / "sha256" / digest_hex / release.member_filename
    if final_path.exists() or final_path.is_symlink():
        _verify_cached_member(final_path, release)
        return final_path, True

    object_dir = final_path.parent
    object_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".acquire-", suffix=".tmp", dir=object_dir)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary_path, final_path)
        except FileExistsError:
            _verify_cached_member(final_path, release)
            return final_path, True
        return final_path, False
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def acquire_eurovoc_release(
    release: EuroVocReleaseSource,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    metadata_path: Path | None = None,
    include_metadata: bool = False,
    allow_network: bool = False,
    timeout_seconds: float = 60.0,
) -> AcquiredEuroVocRelease:
    """Acquire and verify a EuroVoc ZIP, RDF member, and optional metadata.

    Metadata acquisition is opt-in. Supplying ``metadata_path`` implies
    ``include_metadata=True``. This keeps a local archive import offline while
    still allowing the separately pinned metadata artifact to accompany it.
    """

    try:
        archive = acquire_pinned_source(
            release,
            store_dir,
            labels=_EUROVOC_ARCHIVE_LABELS,
            source_path=source_path,
            allow_network=allow_network,
            timeout_seconds=timeout_seconds,
        )
    except PinnedAcquisitionError as error:
        raise EuroVocAcquisitionError(str(error)) from error

    payload = _verified_member_payload(archive.path, release)
    member_path, member_cache_hit = _publish_member(payload, release, store_dir)

    metadata: AcquiredPinnedSource | None = None
    if include_metadata or metadata_path is not None:
        if release.metadata_source is None:
            raise EuroVocAcquisitionError("this EuroVoc release has no pinned metadata source")
        try:
            metadata = acquire_pinned_source(
                release.metadata_source,
                store_dir,
                labels=_EUROVOC_METADATA_LABELS,
                source_path=metadata_path,
                allow_network=allow_network,
                timeout_seconds=timeout_seconds,
            )
        except PinnedAcquisitionError as error:
            raise EuroVocAcquisitionError(str(error)) from error

    return AcquiredEuroVocRelease(
        release=release,
        path=member_path,
        archive_path=archive.path,
        source_url=archive.source_url,
        resolved_url=archive.resolved_url,
        sha256=release.expected_member_sha256,
        byte_length=release.expected_member_byte_length,
        archive_sha256=archive.sha256,
        archive_byte_length=archive.byte_length,
        cache_hit=archive.cache_hit and member_cache_hit,
        acquisition_mode=archive.acquisition_mode,
        local_source_path=archive.local_source_path,
        metadata=metadata,
    )


def parse_acquired_eurovoc_release(acquired: AcquiredEuroVocRelease) -> EuroVocVocabulary:
    """Reverify both ZIP and extracted member, then parse the pinned release."""

    archive_payload = _verified_member_payload(acquired.archive_path, acquired.release)
    _verify_cached_member(acquired.path, acquired.release)
    if archive_payload != acquired.path.read_bytes():
        raise EuroVocThesaurusError("cached EuroVoc RDF member differs from its pinned archive member")
    return parse_eurovoc_rdf_xml(
        archive_payload,
        source_url=acquired.release.source_url,
        expected_sha256=acquired.release.expected_member_sha256,
        expected_byte_length=acquired.release.expected_member_byte_length,
        expected_thesaurus_iri=acquired.release.concept_scheme_iri,
        release_version=acquired.release.version,
    )
