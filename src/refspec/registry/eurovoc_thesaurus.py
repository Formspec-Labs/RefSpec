"""Lossless SKOS reader and acquisition for a pinned EuroVoc mapping sample.

The catalog role for EuroVoc is explicit: "Benchmark and mapping reference
only; do not import its European Union-centered scheme wholesale" (see
research/source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md). This
module honors that constraint structurally, not only in prose:

* ``parse_eurovoc_turtle`` requires a caller to pass
  ``accepted_use="mappingReference"`` and refuses any other value. There is
  no code path here that produces a RefSpec-governed concept scheme.
* EuroVoc's own data doubly types each of its 21 domains as both
  ``eurovoc:schema#Domain`` and ``skos:Concept``. This reader keeps domains
  and thesaurus concepts as two disjoint record kinds; a domain IRI never
  appears in the concept set.
* Every domain, micro-thesaurus ("domain group"), and concept identifier
  returned here is the publisher's own ``dc:identifier`` /
  ``dcterms:identifier`` / ``skos:notation`` value, cross-checked for
  agreement. Nothing is minted; a record without a publisher-supplied
  identifier is refused rather than assigned one.

Only plain string and language-tagged literals occur in the predicates this
reader captures (no typed numeric or date literals), so the standard RDFLib
Turtle parser is exact for this shape; ELSST's lossless custom literal sink
is unnecessary here and is not duplicated.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Literal as LiteralType

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, SKOS, XSD
from rdflib.term import Identifier

from refspec.registry.infrastructure.pinned_acquisition import (
    AcquiredPinnedSource,
    PinnedAcquisitionError,
    PinnedAcquisitionLabels,
    acquire_pinned_source,
    expected_digest_hex,
)

DC11 = Namespace("http://purl.org/dc/elements/1.1/")
EUVOC = Namespace("http://publications.europa.eu/ontology/euvoc#")
EUROVOC_SCHEMA = Namespace("http://eurovoc.europa.eu/schema#")

PREF_LABEL_PREDICATE_IRI = str(SKOS.prefLabel)
ALT_LABEL_PREDICATE_IRI = str(SKOS.altLabel)
HIDDEN_LABEL_PREDICATE_IRI = str(SKOS.hiddenLabel)
SCHEME_MEMBERSHIP_PREDICATE_IRI = str(SKOS.inScheme)
TOP_CONCEPT_OF_PREDICATE_IRI = str(SKOS.topConceptOf)
HAS_TOP_CONCEPT_PREDICATE_IRI = str(SKOS.hasTopConcept)
STATUS_PREDICATE_IRI = str(EUVOC.status)
BROADER_PREDICATE_IRI = str(SKOS.broader)
NARROWER_PREDICATE_IRI = str(SKOS.narrower)
HIERARCHY_PREDICATE_IRIS = (BROADER_PREDICATE_IRI, NARROWER_PREDICATE_IRI)

ACCEPTED_USE_MAPPING_REFERENCE = "mappingReference"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

EuroVocLabelRole = LiteralType["preferred", "alternate", "hidden"]
EuroVocAcceptedUse = LiteralType["mappingReference"]


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
class EuroVocMappingSample:
    """A deterministic, source-faithful EuroVoc sample for mapping use only.

    ``role`` is always ``"mappingReference"``: this object is never a
    governed RefSpec concept scheme, and no function in this module
    promotes it into one.
    """

    role: EuroVocAcceptedUse
    source_url: str
    source_sha256: str
    source_bytes: int
    triple_count: int
    source_iris: tuple[str, ...]
    thesaurus_iri: str
    thesaurus_version: str
    domains_scheme_iri: str | None
    domains: tuple[EuroVocDomain, ...]
    domain_groups: tuple[EuroVocDomainGroup, ...]
    concepts: tuple[EuroVocConcept, ...]
    labels: tuple[EuroVocLabelExpression, ...]
    scheme_memberships: tuple[EuroVocIriRelation, ...]
    top_concept_of_relations: tuple[EuroVocIriRelation, ...]
    has_top_concept_relations: tuple[EuroVocIriRelation, ...]
    hierarchy_relations: tuple[EuroVocIriRelation, ...]
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
        raise EuroVocThesaurusError(f"EuroVoc Turtle is not valid UTF-8 at byte {error.start}") from error
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

    EuroVoc always carries the same value on ``dc:identifier``,
    ``dcterms:identifier``, and ``skos:notation``. Requiring all three to be
    present and equal keeps this reader from ever guessing an identifier for
    a resource the publisher did not clearly identify.
    """

    dc_value = _identifier_literal(graph, subject, DC11.identifier, predicate_label="dc:identifier")
    dcterms_value = _identifier_literal(graph, subject, DCTERMS.identifier, predicate_label="dcterms:identifier")
    notation_value = _identifier_literal(graph, subject, SKOS.notation, predicate_label="skos:notation")
    if dc_value is None and dcterms_value is None and notation_value is None:
        raise EuroVocThesaurusError(
            f"{label} {subject} has no publisher-supplied identifier "
            "(dc:identifier, dcterms:identifier, or skos:notation)"
        )
    if dc_value is None or dcterms_value is None or notation_value is None:
        raise EuroVocThesaurusError(
            f"{label} {subject} must carry a publisher-supplied identifier on all of dc:identifier, "
            "dcterms:identifier, and skos:notation; a mapping-only reader will not guess a missing one"
        )
    if len({dc_value, dcterms_value, notation_value}) != 1:
        raise EuroVocThesaurusError(
            f"{label} {subject} dc:identifier, dcterms:identifier, and skos:notation disagree; "
            "a mapping-only reader will not guess between them"
        )
    return dc_value


def _one_iri_object(graph: Graph, subject: URIRef, predicate: URIRef, *, label: str) -> str:
    objects = list(graph.objects(subject, predicate))
    if len(objects) != 1:
        raise EuroVocThesaurusError(f"{label} must have exactly one {predicate}")
    return _iri(objects[0], label)


def _domains(graph: Graph) -> tuple[EuroVocDomain, ...]:
    domains: list[EuroVocDomain] = []
    for subject in set(graph.subjects(RDF.type, EUROVOC_SCHEMA.Domain)):
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
            # EuroVoc double-types each domain as skos:Concept. A mapping
            # package keeps domains and concepts as disjoint record kinds.
            continue
        notation = _required_source_identifier(graph, subject, label="concept")
        concepts.append(EuroVocConcept(concept_iri=concept_iri, notation=notation))
    return tuple(sorted(concepts, key=lambda item: item.concept_iri))


def _thesaurus_identity(graph: Graph) -> tuple[str, str]:
    subjects = set(graph.subjects(RDF.type, EUROVOC_SCHEMA.Thesaurus))
    if len(subjects) != 1:
        raise EuroVocThesaurusError("EuroVoc Turtle must contain exactly one eurovoc:schema#Thesaurus resource")
    subject = next(iter(subjects))
    thesaurus_iri = _iri(subject, "thesaurus")
    versions = list(graph.objects(subject, OWL.versionInfo))
    if len(versions) != 1 or not isinstance(versions[0], Literal):
        raise EuroVocThesaurusError(f"{thesaurus_iri} must have exactly one owl:versionInfo literal")
    return thesaurus_iri, str(versions[0])


def parse_eurovoc_turtle(
    source: str | bytes,
    *,
    source_url: str,
    accepted_use: EuroVocAcceptedUse,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> EuroVocMappingSample:
    """Parse one EuroVoc Turtle payload into a deterministic mapping sample.

    ``accepted_use`` must be ``"mappingReference"``; this is a refusal gate,
    not a formality, matching the catalog's binding scope constraint for
    EuroVoc.
    """

    if accepted_use != ACCEPTED_USE_MAPPING_REFERENCE:
        raise EuroVocThesaurusError(
            "EuroVoc may only be parsed for the 'mappingReference' accepted use; the catalog treats it as a "
            f"benchmark and mapping reference only, not an importable governed subject scheme (got {accepted_use!r})"
        )

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
        graph.parse(data=payload, format="turtle", publicID=source_url)
    except Exception as error:
        raise EuroVocThesaurusError(f"could not parse EuroVoc Turtle: {error}") from error

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

    thesaurus_iri, thesaurus_version = _thesaurus_identity(graph)
    domains = _domains(graph)
    domains_by_iri = {item.domain_iri: item for item in domains}
    domain_groups = _domain_groups(graph, domains_by_iri)
    concepts = _concepts(graph, set(domains_by_iri))

    return EuroVocMappingSample(
        role=ACCEPTED_USE_MAPPING_REFERENCE,
        source_url=source_url,
        source_sha256=source_sha256,
        source_bytes=len(payload),
        triple_count=len(graph),
        source_iris=source_iris,
        thesaurus_iri=thesaurus_iri,
        thesaurus_version=thesaurus_version,
        domains_scheme_iri=_domains_scheme_iri(graph, domains),
        domains=domains,
        domain_groups=domain_groups,
        concepts=concepts,
        labels=_label_expressions(graph),
        scheme_memberships=_iri_relations(graph, (SCHEME_MEMBERSHIP_PREDICATE_IRI,), label="skos:inScheme"),
        top_concept_of_relations=_iri_relations(graph, (TOP_CONCEPT_OF_PREDICATE_IRI,), label="skos:topConceptOf"),
        has_top_concept_relations=_iri_relations(graph, (HAS_TOP_CONCEPT_PREDICATE_IRI,), label="skos:hasTopConcept"),
        hierarchy_relations=_iri_relations(graph, HIERARCHY_PREDICATE_IRIS, label="SKOS hierarchy relation"),
        status_assertions=_iri_relations(graph, (STATUS_PREDICATE_IRI,), label="euvoc:status"),
    )


def parse_eurovoc_file(
    path: Path,
    *,
    source_url: str,
    accepted_use: EuroVocAcceptedUse,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> EuroVocMappingSample:
    """Parse one local Turtle file while retaining its external source identity."""

    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise EuroVocThesaurusError(f"EuroVoc source is not a regular file: {source_path}")
    return parse_eurovoc_turtle(
        source_path.read_bytes(),
        source_url=source_url,
        accepted_use=accepted_use,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )


# --- Acquisition -----------------------------------------------------------
#
# Importing this module never opens a network connection. A caller must
# either provide an existing local sample or set ``allow_network=True``. In
# both cases, RefSpec verifies the exact published byte length and SHA-256
# digest before making the object visible in the content-addressed store.
#
# The publisher attribution and license are retained as source metadata.
# They describe the publication; they do not act as a runtime authorization
# gate.

EUROVOC_PUBLISHER = "Publications Office of the European Union"
EUROVOC_ATTRIBUTION = "Publications Office of the European Union, EU Vocabularies SPARQL endpoint"
EUROVOC_LICENSE_IRI = "https://creativecommons.org/licenses/by/4.0/"
EUROVOC_LICENSE_LABEL = "Creative Commons Attribution 4.0 International"

AcquisitionMode = LiteralType["cache", "local", "network"]


class EuroVocAcquisitionError(ValueError):
    """A EuroVoc sample could not be acquired without weakening its pin."""


def _expected_hex(expected_sha256: str) -> str:
    try:
        return expected_digest_hex(expected_sha256)
    except PinnedAcquisitionError as error:
        raise EuroVocAcquisitionError(str(error)) from error


_EUROVOC_ACQUIRE_LABELS = PinnedAcquisitionLabels(
    source_label="EuroVoc sample",
    cached_location="cached EuroVoc sample",
    local_file_label="local EuroVoc source",
    not_cached_message=(
        "EuroVoc sample is not cached; provide source_path or set allow_network=True explicitly"
    ),
    request_headers={"User-Agent": "RefSpec explicit EuroVoc source resolver/1.0"},
)


def _validate_source_url(source_url: str) -> None:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EuroVocAcquisitionError("source_url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise EuroVocAcquisitionError("source_url must not contain credentials")


def _require_absolute_iri_acquisition(value: str, label: str) -> None:
    if not urllib.parse.urlsplit(value).scheme:
        raise EuroVocAcquisitionError(f"{label} must be an absolute IRI")


@dataclass(frozen=True, slots=True)
class EuroVocSampleSource:
    """One exact, externally published EuroVoc Turtle sample."""

    sample_id: str
    source_url: str
    expected_sha256: str
    expected_byte_length: int
    filename: str
    publisher: str = EUROVOC_PUBLISHER
    attribution: str = EUROVOC_ATTRIBUTION
    license_iri: str = EUROVOC_LICENSE_IRI
    license_label: str = EUROVOC_LICENSE_LABEL

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise EuroVocAcquisitionError("sample_id must not be empty")
        _validate_source_url(self.source_url)
        _expected_hex(self.expected_sha256)
        if self.expected_byte_length <= 0:
            raise EuroVocAcquisitionError("expected_byte_length must be positive")
        if not self.filename or Path(self.filename).name != self.filename:
            raise EuroVocAcquisitionError("filename must be one plain path component")
        _require_absolute_iri_acquisition(self.license_iri, "license_iri")
        if not self.publisher or not self.attribution or not self.license_label:
            raise EuroVocAcquisitionError("publisher, attribution, and license_label must not be empty")


EUROVOC_SAMPLE_2026_08_03 = EuroVocSampleSource(
    sample_id="eurovoc-domains-politics-international-relations-2026-08-03",
    source_url=(
        "http://publications.europa.eu/webapi/rdf/sparql?query="
        "PREFIX+rdf%3A+%3Chttp%3A%2F%2Fwww.w3.org%2F1999%2F02%2F22-rdf-syntax-ns%23%3E%0A"
        "PREFIX+skos%3A+%3Chttp%3A%2F%2Fwww.w3.org%2F2004%2F02%2Fskos%2Fcore%23%3E%0A"
        "PREFIX+dc%3A+%3Chttp%3A%2F%2Fpurl.org%2Fdc%2Felements%2F1.1%2F%3E%0A"
        "PREFIX+dcterms%3A+%3Chttp%3A%2F%2Fpurl.org%2Fdc%2Fterms%2F%3E%0A"
        "PREFIX+owl%3A+%3Chttp%3A%2F%2Fwww.w3.org%2F2002%2F07%2Fowl%23%3E%0A"
        "PREFIX+euvoc%3A+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fontology%2Feuvoc%23%3E%0A"
        "CONSTRUCT+%7B+%3Fs+%3Fp+%3Fo+.+%7D%0AWHERE+%7B%0A++VALUES+%3Fs+%7B%0A"
        "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100141%3E%0A"
        "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2Fdomains%3E%0A"
        "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100142%3E%0A"
        "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100143%3E%0A"
        "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100165%3E%0A"
        "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100170%3E%0A"
        "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F4157%3E%0A"
        "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F4159%3E%0A"
        "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F3313%3E%0A"
        "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F2189%3E%0A++%7D%0A++%3Fs+%3Fp+%3Fo+.%0A++FILTER%28%0A"
        "++++%3Fp+IN+%28%0A++++++rdf%3Atype%2C+skos%3AinScheme%2C+skos%3AtopConceptOf%2C%0A"
        "++++++skos%3Abroader%2C+skos%3Anarrower%2C+skos%3Anotation%2C+dc%3Aidentifier%2C%0A"
        "++++++dcterms%3Aidentifier%2C+dcterms%3AisPartOf%2C+euvoc%3Adomain%2C+euvoc%3Astatus%2C%0A"
        "++++++owl%3AversionInfo%0A++++%29%0A"
        "++++%7C%7C+%28%3Fp+%3D+skos%3AhasTopConcept+%26%26+%3Fs+%21%3D+%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100141%3E%29%0A"
        "++++%7C%7C+%28%3Fp+IN+%28skos%3AprefLabel%2C+skos%3AaltLabel%29+%26%26+lang%28%3Fo%29+IN+"
        "%28%22en%22%2C%22fr%22%2C%22de%22%2C%22es%22%2C%22el%22%29%29%0A++%29%0A%7D%0A"
    ),
    expected_sha256="sha256:94e5a1999c4a67d057f57558452f473c98858ad7bf9a39add9f3a52135f3e390",
    expected_byte_length=9897,
    filename="eurovoc-domains-sample-2026-08-03.ttl",
)


@dataclass(frozen=True, slots=True)
class AcquiredEuroVocSample:
    """One verified EuroVoc sample object in a content-addressed local store."""

    source: EuroVocSampleSource
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    cache_hit: bool
    acquisition_mode: AcquisitionMode
    local_source_path: Path | None


def _as_acquired_eurovoc(source: EuroVocSampleSource, acquired: AcquiredPinnedSource) -> AcquiredEuroVocSample:
    return AcquiredEuroVocSample(
        source=source,
        path=acquired.path,
        source_url=acquired.source_url,
        resolved_url=acquired.resolved_url,
        sha256=acquired.sha256,
        byte_length=acquired.byte_length,
        cache_hit=acquired.cache_hit,
        acquisition_mode=acquired.acquisition_mode,
        local_source_path=acquired.local_source_path,
    )


def acquire_eurovoc_sample(
    source: EuroVocSampleSource,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    allow_network: bool = False,
    timeout_seconds: float = 60.0,
) -> AcquiredEuroVocSample:
    """Resolve one pinned EuroVoc sample from cache, a local file, or the network.

    Cache lookup is always local. A supplied ``source_path`` is read locally.
    Otherwise, a cache miss fails unless ``allow_network`` is explicitly
    true. Every path is subject to the source's exact byte-length and digest
    pins.
    """

    try:
        acquired = acquire_pinned_source(
            source,
            store_dir,
            labels=_EUROVOC_ACQUIRE_LABELS,
            source_path=source_path,
            allow_network=allow_network,
            timeout_seconds=timeout_seconds,
        )
    except PinnedAcquisitionError as error:
        raise EuroVocAcquisitionError(str(error)) from error
    return _as_acquired_eurovoc(source, acquired)


def parse_acquired_eurovoc_sample(
    acquired: AcquiredEuroVocSample,
    *,
    accepted_use: EuroVocAcceptedUse,
) -> EuroVocMappingSample:
    """Reverify and parse an object returned by the EuroVoc acquisition adapter."""

    if acquired.path.is_symlink() or not acquired.path.is_file():
        raise EuroVocThesaurusError(f"acquired EuroVoc source is not a regular file: {acquired.path}")
    return parse_eurovoc_turtle(
        acquired.path.read_bytes(),
        source_url=acquired.source.source_url,
        accepted_use=accepted_use,
        expected_sha256=acquired.source.expected_sha256,
        expected_byte_length=acquired.source.expected_byte_length,
    )
