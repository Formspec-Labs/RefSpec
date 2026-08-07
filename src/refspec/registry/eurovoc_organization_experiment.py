"""Build and verify the non-authoritative EuroVoc organization experiment.

The sidecar preserves the 21 EuroVoc domains, the 127 notated
microthesaurus schemes, and the exact concept-to-microthesaurus
``skos:inScheme`` assertions in one pinned SKOS Core release.  A separate
candidate member records notation-prefix domain links.  Those links are never
presented as publisher assertions.

This module does not change the Atlas binding, create canonical Atlas facts, or
grant a search consumer permission to use the candidates.
"""

from __future__ import annotations

import os
import platform
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rdflib
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, SKOS

from refspec.registry.eurovoc_thesaurus import (
    SCHEME_MEMBERSHIP_PREDICATE_IRI,
    AcquiredEuroVocRelease,
    EuroVocReleaseSource,
    EuroVocVocabulary,
    acquire_eurovoc_release,
    parse_acquired_eurovoc_release,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    canonical_jsonl_bytes,
    sha256_digest,
)
from refspec.registry.infrastructure.semantic_foundation import RightsMetadata

DCAT = Namespace("http://www.w3.org/ns/dcat#")
EUVOC = Namespace("http://publications.europa.eu/ontology/euvoc#")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
VOID = Namespace("http://rdfs.org/ns/void#")

EXPERIMENT_NAME = "EuroVocOrganizationExperiment"
SCHEMA_VERSION = "1.0"
RECIPE_VERSION = "1.0"
DEFAULT_NORMALIZED_PARTITION_IRI = (
    "http://publications.europa.eu/resource/dataset/"
    "eurovoc/20260708-0#thesaurus-concepts"
)

MANIFEST_PATH = "experiment-manifest.json"
OBJECTS_PATH = "publisher-organization-objects.jsonl"
ASSERTIONS_PATH = "publisher-organization-assertions.jsonl"
CANDIDATES_PATH = "operator-derived-domain-candidates.jsonl"
CHANGE_EVENTS_PATH = "change-events.jsonl"
ACCOUNTING_PATH = "source-accounting.json"
RIGHTS_PATH = "rights.json"
VALIDATION_PATH = "validation-receipt.json"

MEMBER_ROLES = {
    OBJECTS_PATH: "publisherOrganizationObjects",
    ASSERTIONS_PATH: "publisherOrganizationAssertions",
    CANDIDATES_PATH: "operatorDerivedDomainCandidates",
    CHANGE_EVENTS_PATH: "organizationChangeEvents",
    ACCOUNTING_PATH: "sourceAccounting",
    RIGHTS_PATH: "sourceRights",
    VALIDATION_PATH: "producerValidation",
}
EXPECTED_FILE_SET = frozenset({MANIFEST_PATH, *MEMBER_ROLES})

_DOCUMENTATION_PREDICATES = (
    SKOS.definition,
    SKOS.scopeNote,
    SKOS.note,
    SKOS.historyNote,
    SKOS.changeNote,
    SKOS.editorialNote,
    SKOS.example,
)


class EuroVocOrganizationExperimentError(ValueError):
    """The experiment could not be built or verified without weakening it."""


@dataclass(frozen=True, slots=True)
class EuroVocOrganizationArtifact:
    """Canonical bytes for one closed experiment directory."""

    files: Mapping[str, bytes]
    manifest: Mapping[str, Any]

    @property
    def manifest_sha256(self) -> str:
        return sha256_digest(self.files[MANIFEST_PATH])


@dataclass(frozen=True, slots=True)
class _PublisherMetadata:
    source_iri: str
    dataset_iri: str
    archetype_iris: tuple[str, ...]
    version: str
    issued: str
    modified: str
    publisher_iris: tuple[str, ...]
    license_iris: tuple[str, ...]
    distributions: tuple[Mapping[str, Any], ...]
    rdf_concept_count: int | None
    triple_count: int


def _require_iri(value: object, label: str) -> str:
    if not isinstance(value, URIRef):
        raise EuroVocOrganizationExperimentError(f"{label} must be an IRI")
    return str(value)


def _one(values: Sequence[Any], label: str) -> Any:
    if len(values) != 1:
        raise EuroVocOrganizationExperimentError(
            f"{label} must have exactly one value, got {len(values)}"
        )
    return values[0]


def _literal_record(value: Literal) -> dict[str, str | None]:
    return {
        "value": str(value),
        "language": str(value.language) if value.language is not None else None,
        "datatype": str(value.datatype) if value.datatype is not None else None,
    }


def _literal_records(graph: Graph, subject: URIRef, predicate: URIRef) -> list[dict[str, str | None]]:
    result: list[dict[str, str | None]] = []
    for value in graph.objects(subject, predicate):
        if not isinstance(value, Literal):
            raise EuroVocOrganizationExperimentError(
                f"{subject} {predicate} must point to a literal"
            )
        result.append(_literal_record(value))
    return sorted(result, key=lambda row: (row["language"] or "", row["datatype"] or "", row["value"] or ""))


def _iri_records(graph: Graph, subject: URIRef, predicate: URIRef) -> list[str]:
    return sorted(_require_iri(value, f"{subject} {predicate} object") for value in graph.objects(subject, predicate))


def _record_hash(kind: str, identity: Mapping[str, Any]) -> str:
    digest = sha256_digest(canonical_json_bytes({"kind": kind, **identity}))
    return digest.removeprefix("sha256:")


def _semantic_key(kind: str, identity: Mapping[str, Any]) -> str:
    return f"urn:ref:eurovoc-organization-experiment:{kind}:{_record_hash(kind, identity)}"


def _record_id(
    kind: str,
    identity: Mapping[str, Any],
    *,
    dataset_iri: str,
    rdf_member_digest: str,
) -> str:
    versioned_identity = {
        **identity,
        "publisherDatasetIri": dataset_iri,
        "skosRdfMemberDigest": rdf_member_digest,
    }
    return (
        f"urn:ref:eurovoc-organization-experiment:{kind}-record:"
        f"{_record_hash(kind + '-record', versioned_identity)}"
    )


def _source_types(graph: Graph, source_iri: str) -> list[str]:
    return _iri_records(graph, URIRef(source_iri), RDF.type)


def _documentation(graph: Graph, source_iri: str) -> list[dict[str, Any]]:
    subject = URIRef(source_iri)
    records: list[dict[str, Any]] = []
    for predicate in _DOCUMENTATION_PREDICATES:
        for value in graph.objects(subject, predicate):
            if not isinstance(value, Literal):
                raise EuroVocOrganizationExperimentError(
                    f"{source_iri} {predicate} must point to a literal"
                )
            records.append({"predicate": str(predicate), **_literal_record(value)})
    return sorted(
        records,
        key=lambda row: (
            row["predicate"],
            row["language"] or "",
            row["datatype"] or "",
            row["value"],
        ),
    )


def _publisher_metadata(acquired: AcquiredEuroVocRelease) -> _PublisherMetadata:
    if acquired.metadata is None or acquired.release.metadata_source is None:
        raise EuroVocOrganizationExperimentError(
            "publisher metadata is required for EuroVocOrganizationExperiment"
        )
    payload = acquired.metadata.path.read_bytes()
    if len(payload) != acquired.release.metadata_source.expected_byte_length:
        raise EuroVocOrganizationExperimentError("publisher metadata byte length changed after acquisition")
    if sha256_digest(payload) != acquired.release.metadata_source.expected_sha256:
        raise EuroVocOrganizationExperimentError("publisher metadata digest changed after acquisition")

    graph = Graph()
    try:
        graph.parse(data=payload, format="turtle", publicID=acquired.metadata.source_url)
    except Exception as error:
        raise EuroVocOrganizationExperimentError(f"could not parse publisher metadata: {error}") from error

    descriptions = sorted(
        _require_iri(subject, "VoID dataset description")
        for subject in graph.subjects(RDF.type, VOID.DatasetDescription)
    )
    source_iri = _one(descriptions, "publisher metadata dataset description")

    dataset_candidates = sorted(
        {
            _require_iri(subject, "publisher dataset")
            for subject, version in graph.subject_objects(DCAT.version)
            if isinstance(version, Literal) and str(version) == acquired.release.version
        }
    )
    dataset_iri = _one(dataset_candidates, f"publisher dataset for version {acquired.release.version}")
    dataset = URIRef(dataset_iri)
    if (dataset, RDF.type, DCAT.Dataset) not in graph:
        raise EuroVocOrganizationExperimentError(f"{dataset_iri} is not typed dcat:Dataset")

    version_value = _one(list(graph.objects(dataset, DCAT.version)), "publisher dataset version")
    issued_value = _one(list(graph.objects(dataset, DCTERMS.issued)), "publisher dataset issued")
    modified_value = _one(list(graph.objects(dataset, DCTERMS.modified)), "publisher dataset modified")
    if not all(isinstance(value, Literal) for value in (version_value, issued_value, modified_value)):
        raise EuroVocOrganizationExperimentError("publisher version and dates must be RDF literals")
    version = str(version_value)
    issued = str(issued_value)
    modified = str(modified_value)
    if version != acquired.release.version:
        raise EuroVocOrganizationExperimentError(
            f"publisher metadata version {version!r} differs from acquired version {acquired.release.version!r}"
        )

    archetype_iris = tuple(
        sorted(
            {
                _require_iri(subject, "publisher dataset archetype")
                for subject in graph.subjects(DCAT.currentVersion, dataset)
            }
        )
    )
    if not archetype_iris:
        raise EuroVocOrganizationExperimentError(
            f"publisher metadata has no dcat:currentVersion link to {dataset_iri}"
        )

    rights_subjects = (dataset, *(URIRef(iri) for iri in archetype_iris))
    publisher_iris = tuple(
        sorted(
            {
                _require_iri(value, "publisher metadata dcterms:publisher")
                for subject in rights_subjects
                for value in graph.objects(subject, DCTERMS.publisher)
            }
        )
    )
    license_iris = tuple(
        sorted(
            {
                _require_iri(value, "publisher metadata dcterms:license")
                for subject in rights_subjects
                for value in graph.objects(subject, DCTERMS.license)
            }
        )
    )
    if not publisher_iris or not license_iris:
        raise EuroVocOrganizationExperimentError(
            "publisher metadata must state dcterms:publisher and dcterms:license"
        )

    distribution_iris = _iri_records(graph, dataset, DCAT.distribution)
    if not distribution_iris:
        raise EuroVocOrganizationExperimentError("publisher dataset has no dcat:distribution records")
    distributions: list[Mapping[str, Any]] = []
    for distribution_iri in distribution_iris:
        distribution = URIRef(distribution_iri)
        distributions.append(
            {
                "sourceIri": distribution_iri,
                "sourceTypes": _source_types(graph, distribution_iri),
                "titles": _literal_records(graph, distribution, DCTERMS.title),
                "downloadUrls": _iri_records(graph, distribution, DCAT.downloadURL),
                "accessUrls": _iri_records(graph, distribution, DCAT.accessURL),
                "dataDumpUrls": _iri_records(graph, distribution, VOID.dataDump),
                "mediaTypes": _iri_records(graph, distribution, DCAT.mediaType),
                "compressFormats": _iri_records(graph, distribution, DCAT.compressFormat),
            }
        )

    rdf_concept_counts: set[int] = set()
    for partition in graph.subjects(VOID["class"], SKOS.Concept):
        for value in graph.objects(partition, VOID.entities):
            if isinstance(value, Literal):
                try:
                    rdf_concept_counts.add(int(str(value)))
                except ValueError as error:
                    raise EuroVocOrganizationExperimentError(
                        "publisher metadata void:entities for skos:Concept is not an integer"
                    ) from error
    rdf_concept_count = _one(sorted(rdf_concept_counts), "publisher RDF concept count") if rdf_concept_counts else None

    primary_topics = _iri_records(graph, URIRef(source_iri), FOAF.primaryTopic)
    if not primary_topics:
        raise EuroVocOrganizationExperimentError("publisher metadata description has no foaf:primaryTopic")

    return _PublisherMetadata(
        source_iri=source_iri,
        dataset_iri=dataset_iri,
        archetype_iris=archetype_iris,
        version=version,
        issued=issued,
        modified=modified,
        publisher_iris=publisher_iris,
        license_iris=license_iris,
        distributions=tuple(sorted(distributions, key=lambda row: str(row["sourceIri"]))),
        rdf_concept_count=rdf_concept_count,
        triple_count=len(graph),
    )


def _common_provenance(
    acquired: AcquiredEuroVocRelease,
    metadata: _PublisherMetadata,
    normalized_partition_iri: str,
) -> dict[str, Any]:
    return {
        "publisherDatasetIri": metadata.dataset_iri,
        "publisherVersion": metadata.version,
        "publisherIssued": metadata.issued,
        "publisherMetadataSourceIri": metadata.source_iri,
        "publisherMetadataArtifactDigest": acquired.metadata.sha256 if acquired.metadata else None,
        "skosInputArtifactDigest": acquired.archive_sha256,
        "skosRdfMemberDigest": acquired.sha256,
        "normalizedPartitionIri": normalized_partition_iri,
        "normalizedPartitionAuthority": "RefSpecOperator",
    }


def _organization_rows(
    acquired: AcquiredEuroVocRelease,
    metadata: _PublisherMetadata,
    parsed: EuroVocVocabulary,
    graph: Graph,
    normalized_partition_iri: str,
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    domains = {domain.domain_iri: domain.code for domain in parsed.domains}
    microthesauri = {
        scheme.scheme_iri: scheme.notation
        for scheme in parsed.concept_schemes
        if scheme.notation is not None
        and len(scheme.notation) == 4
        and scheme.notation.isdigit()
    }
    if set(domains) & set(microthesauri):
        raise EuroVocOrganizationExperimentError("domain and microthesaurus object sets overlap")

    object_iris = set(domains) | set(microthesauri)
    labels_by_iri: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for label in parsed.labels:
        if label.subject_iri not in object_iris:
            continue
        labels_by_iri[label.subject_iri].append(
            {
                "predicate": label.property_iri,
                "role": label.role,
                "value": label.value.lexical_form,
                "language": label.value.language_tag,
            }
        )
    for records in labels_by_iri.values():
        records.sort(key=lambda row: (row["predicate"], row["language"] or "", row["value"]))

    provenance = _common_provenance(acquired, metadata, normalized_partition_iri)
    rows: list[dict[str, Any]] = []
    for organization_kind, objects in (("domain", domains), ("microthesaurus", microthesauri)):
        for source_iri, notation in sorted(objects.items()):
            identity = {"recordType": "publisherOrganizationObject", "sourceIri": source_iri}
            labels = labels_by_iri.get(source_iri, [])
            if not labels:
                raise EuroVocOrganizationExperimentError(f"publisher organization object has no labels: {source_iri}")
            source_types = _source_types(graph, source_iri)
            if not source_types:
                raise EuroVocOrganizationExperimentError(f"publisher organization object has no RDF type: {source_iri}")
            rows.append(
                {
                    **identity,
                    "organizationKind": organization_kind,
                    "sourceTypes": source_types,
                    "notation": notation,
                    "labels": labels,
                    "documentation": _documentation(graph, source_iri),
                    **provenance,
                    "semanticKey": _semantic_key("object", identity),
                    "experimentRecord": _record_id(
                        "object",
                        identity,
                        dataset_iri=metadata.dataset_iri,
                        rdf_member_digest=acquired.sha256,
                    ),
                }
            )
    rows.sort(key=lambda row: row["sourceIri"])
    return rows, set(domains), set(microthesauri)


def _assertion_rows(
    acquired: AcquiredEuroVocRelease,
    metadata: _PublisherMetadata,
    parsed: EuroVocVocabulary,
    normalized_partition_iri: str,
    microthesaurus_iris: set[str],
) -> tuple[list[dict[str, Any]], set[str], Counter[int], Counter[str]]:
    concepts = {concept.concept_iri for concept in parsed.concepts}
    provenance = _common_provenance(acquired, metadata, normalized_partition_iri)
    memberships = [
        relation
        for relation in parsed.scheme_memberships
        if relation.subject_iri in concepts and relation.object_iri in microthesaurus_iris
    ]
    rows: list[dict[str, Any]] = []
    membership_counts: Counter[str] = Counter()
    scheme_member_counts: Counter[str] = Counter()
    seen: set[tuple[str, str, str]] = set()
    for relation in memberships:
        triple = (relation.subject_iri, relation.predicate_iri, relation.object_iri)
        if triple in seen:
            raise EuroVocOrganizationExperimentError(f"duplicate publisher membership assertion: {triple!r}")
        seen.add(triple)
        if relation.predicate_iri != SCHEME_MEMBERSHIP_PREDICATE_IRI:
            raise EuroVocOrganizationExperimentError("microthesaurus assertion predicate is not skos:inScheme")
        identity = {
            "recordType": "publisherOrganizationAssertion",
            "sourceSubject": relation.subject_iri,
            "sourcePredicate": relation.predicate_iri,
            "sourceObject": relation.object_iri,
        }
        rows.append(
            {
                **identity,
                "assertionKind": "conceptMicrothesaurusMembership",
                **provenance,
                "semanticKey": _semantic_key("assertion", identity),
                "experimentRecord": _record_id(
                    "assertion",
                    identity,
                    dataset_iri=metadata.dataset_iri,
                    rdf_member_digest=acquired.sha256,
                ),
            }
        )
        membership_counts[relation.subject_iri] += 1
        scheme_member_counts[relation.object_iri] += 1

    if set(membership_counts) != concepts:
        missing = sorted(concepts - set(membership_counts))
        extra = sorted(set(membership_counts) - concepts)
        raise EuroVocOrganizationExperimentError(
            f"microthesaurus membership subject closure failed; missing={missing[:5]!r}, extra={extra[:5]!r}"
        )
    if set(scheme_member_counts) != microthesaurus_iris:
        raise EuroVocOrganizationExperimentError("not every microthesaurus is referenced by a membership")
    if min(membership_counts.values()) < 1 or max(membership_counts.values()) > 4:
        raise EuroVocOrganizationExperimentError("concept microthesaurus membership cardinality is outside 1-4")

    rows.sort(key=lambda row: (row["sourceSubject"], row["sourcePredicate"], row["sourceObject"]))
    cardinalities = Counter(membership_counts.values())
    return rows, concepts, cardinalities, scheme_member_counts


def _candidate_rows(
    acquired: AcquiredEuroVocRelease,
    metadata: _PublisherMetadata,
    normalized_partition_iri: str,
    object_rows: Sequence[Mapping[str, Any]],
    graph: Graph,
) -> list[dict[str, Any]]:
    domain_by_code = {
        str(row["notation"]): str(row["sourceIri"])
        for row in object_rows
        if row["organizationKind"] == "domain"
    }
    micro_rows = [row for row in object_rows if row["organizationKind"] == "microthesaurus"]
    provenance = _common_provenance(acquired, metadata, normalized_partition_iri)
    rows: list[dict[str, Any]] = []
    for micro in micro_rows:
        notation = str(micro["notation"])
        domain_code = notation[:2]
        domain_iri = domain_by_code.get(domain_code)
        if domain_iri is None:
            raise EuroVocOrganizationExperimentError(
                f"microthesaurus notation {notation!r} has no unique two-digit domain"
            )
        source_iri = str(micro["sourceIri"])
        if (URIRef(source_iri), EUVOC.domain, URIRef(domain_iri)) in graph:
            raise EuroVocOrganizationExperimentError(
                "candidate layer is unnecessary because the source already asserts euvoc:domain"
            )
        identity = {
            "recordType": "operatorDerivedDomainCandidate",
            "candidateSubject": source_iri,
            "candidatePredicate": str(EUVOC.domain),
            "candidateObject": domain_iri,
        }
        semantic_key = _semantic_key("domain-candidate", identity)
        rows.append(
            {
                **identity,
                "authority": "RefSpecOperator",
                "generationMethod": "microthesaurusNotationTwoDigitPrefix",
                "generationEvidence": {
                    "microthesaurusNotation": notation,
                    "matchedDomainCode": domain_code,
                },
                "reviewDisposition": "proposed",
                "validity": "current",
                "changeEventReference": None,
                "publisherAssertion": False,
                **provenance,
                "semanticKey": semantic_key,
                "experimentRecord": _record_id(
                    "domain-candidate",
                    identity,
                    dataset_iri=metadata.dataset_iri,
                    rdf_member_digest=acquired.sha256,
                ),
                "generationReceipt": _semantic_key(
                    "generation-receipt",
                    {
                        "candidate": semantic_key,
                        "method": "microthesaurusNotationTwoDigitPrefix",
                        "recipeVersion": RECIPE_VERSION,
                    },
                ),
            }
        )
    rows.sort(key=lambda row: (row["candidateSubject"], row["candidateObject"]))
    return rows


def _assert_production_invariants(
    acquired: AcquiredEuroVocRelease,
    metadata: _PublisherMetadata,
    *,
    object_rows: Sequence[Mapping[str, Any]],
    assertion_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
    concept_count: int,
) -> None:
    if acquired.release.release_id != "eurovoc-4.24":
        return
    counts = {
        "domains": sum(row["organizationKind"] == "domain" for row in object_rows),
        "microthesauri": sum(row["organizationKind"] == "microthesaurus" for row in object_rows),
        "concepts": concept_count,
        "memberships": len(assertion_rows),
        "candidates": len(candidate_rows),
        "distributions": len(metadata.distributions),
    }
    expected = {
        "domains": 21,
        "microthesauri": 127,
        "concepts": 7_515,
        "memberships": 7_902,
        "candidates": 127,
        "distributions": 4,
    }
    if counts != expected:
        raise EuroVocOrganizationExperimentError(
            f"EuroVoc 4.24 organization counts differ: expected {expected!r}, got {counts!r}"
        )
    if metadata.dataset_iri != "http://eurovoc.europa.eu/void.ttl#dataset_eurovoc-20260709":
        raise EuroVocOrganizationExperimentError("EuroVoc 4.24 publisher dataset IRI changed")
    if metadata.issued != "2026-07-09" or acquired.release.issued != "2026-07-08":
        raise EuroVocOrganizationExperimentError("EuroVoc 4.24 provenance date discrepancy changed")
    if metadata.rdf_concept_count != 7_486:
        raise EuroVocOrganizationExperimentError("EuroVoc 4.24 metadata RDF concept count changed")
    if acquired.release.license_iri not in metadata.license_iris:
        raise EuroVocOrganizationExperimentError("EuroVoc 4.24 metadata license differs from release configuration")


def _code_digest(module_path: Path) -> str:
    if module_path.is_symlink() or not module_path.is_file():
        raise EuroVocOrganizationExperimentError(f"recipe module is not a regular file: {module_path}")
    return sha256_digest(module_path.read_bytes())


def build_eurovoc_organization_artifact(
    acquired: AcquiredEuroVocRelease,
    *,
    normalized_partition_iri: str = DEFAULT_NORMALIZED_PARTITION_IRI,
) -> EuroVocOrganizationArtifact:
    """Return canonical experiment bytes from independently pinned inputs."""

    if not normalized_partition_iri or ":" not in normalized_partition_iri:
        raise EuroVocOrganizationExperimentError("normalized_partition_iri must be an absolute IRI")
    metadata = _publisher_metadata(acquired)
    parsed = parse_acquired_eurovoc_release(acquired)
    rdf_payload = acquired.path.read_bytes()
    graph = Graph()
    try:
        graph.parse(data=rdf_payload, format="xml", publicID=acquired.source_url)
    except Exception as error:
        raise EuroVocOrganizationExperimentError(f"could not parse pinned EuroVoc RDF member: {error}") from error

    object_rows, domain_iris, microthesaurus_iris = _organization_rows(
        acquired, metadata, parsed, graph, normalized_partition_iri
    )
    assertion_rows, concept_iris, membership_cardinalities, scheme_member_counts = _assertion_rows(
        acquired, metadata, parsed, normalized_partition_iri, microthesaurus_iris
    )
    candidate_rows = _candidate_rows(
        acquired, metadata, normalized_partition_iri, object_rows, graph
    )

    publisher_domain_relations = sorted(
        (
            str(subject),
            str(EUVOC.domain),
            str(obj),
        )
        for subject, obj in graph.subject_objects(EUVOC.domain)
        if str(subject) in microthesaurus_iris
    )
    if publisher_domain_relations:
        raise EuroVocOrganizationExperimentError(
            "pinned source unexpectedly contains publisher microthesaurus-domain assertions"
        )

    _assert_production_invariants(
        acquired,
        metadata,
        object_rows=object_rows,
        assertion_rows=assertion_rows,
        candidate_rows=candidate_rows,
        concept_count=len(concept_iris),
    )

    all_memberships = parsed.scheme_memberships
    concept_main = sum(
        relation.subject_iri in concept_iris and relation.object_iri == parsed.thesaurus_iri
        for relation in all_memberships
    )
    domain_scheme = sum(
        relation.subject_iri in domain_iris and relation.object_iri == parsed.domains_scheme_iri
        for relation in all_memberships
    )
    scoped_membership_set = {
        (row["sourceSubject"], row["sourcePredicate"], row["sourceObject"])
        for row in assertion_rows
    }
    unclassified = [
        relation
        for relation in all_memberships
        if (relation.subject_iri, relation.predicate_iri, relation.object_iri)
        not in scoped_membership_set
        and not (
            relation.subject_iri in concept_iris
            and relation.object_iri == parsed.thesaurus_iri
        )
        and not (
            relation.subject_iri in domain_iris
            and relation.object_iri == parsed.domains_scheme_iri
        )
    ]
    if unclassified:
        raise EuroVocOrganizationExperimentError(
            f"{len(unclassified)} skos:inScheme assertions are not source-accounted"
        )

    distribution_urls = sorted(
        {
            url
            for distribution in metadata.distributions
            for field in ("downloadUrls", "accessUrls", "dataDumpUrls")
            for url in distribution[field]
        }
    )
    matching_distribution_urls = sorted(
        url for url in distribution_urls if url == acquired.release.source_url
    )
    if matching_distribution_urls:
        raise EuroVocOrganizationExperimentError(
            "publisher metadata unexpectedly identifies the pinned SKOS Core acquisition"
        )

    label_languages = sorted(
        {
            label["language"]
            for row in object_rows
            for label in row["labels"]
            if label["language"] is not None
        }
    )
    source_accounting = {
        "recordType": "EuroVocOrganizationSourceAccounting",
        "releaseId": acquired.release.release_id,
        "scope": {
            "publisherOrganizationObjectKinds": ["domain", "microthesaurus"],
            "publisherAssertionKinds": ["conceptMicrothesaurusMembership"],
            "completePublisherOrganizationGraph": False,
            "outOfScopeExactPublisherAssertionKinds": [
                "conceptMainSchemeMembership",
                "domainDomainsSchemeMembership",
            ],
        },
        "sourceGraph": {
            "tripleCount": parsed.triple_count,
            "domainCount": len(domain_iris),
            "notatedMicrothesaurusCount": len(microthesaurus_iris),
            "totalConceptSchemeCount": len(parsed.concept_schemes),
            "ordinaryConceptCount": len(concept_iris),
            "totalSchemeMembershipCount": len(all_memberships),
            "publisherMicrothesaurusDomainAssertionCount": 0,
        },
        "emitted": {
            "publisherOrganizationObjectCount": len(object_rows),
            "publisherOrganizationLabelCount": sum(len(row["labels"]) for row in object_rows),
            "publisherOrganizationLabelLanguages": label_languages,
            "publisherConceptMicrothesaurusMembershipCount": len(assertion_rows),
            "operatorDerivedDomainCandidateCount": len(candidate_rows),
            "changeEventCount": 0,
        },
        "membershipCardinalityByConcept": {
            str(cardinality): membership_cardinalities[cardinality]
            for cardinality in sorted(membership_cardinalities)
        },
        "microthesaurusMemberCountRange": {
            "minimum": min(scheme_member_counts.values()),
            "maximum": max(scheme_member_counts.values()),
        },
        "membershipDisposition": {
            "emittedConceptToMicrothesaurus": len(assertion_rows),
            "outOfScopeConceptToMainScheme": concept_main,
            "outOfScopeDomainToDomainsScheme": domain_scheme,
            "unclassified": 0,
        },
        "endpointClosure": {
            "assertionSubjectsArePinnedOrdinaryConcepts": True,
            "assertionObjectsAreEmittedMicrothesauri": True,
            "allPinnedOrdinaryConceptsHaveMicrothesaurusMembership": True,
            "allEmittedMicrothesauriHaveMembers": True,
        },
        "lifecycle": {
            "comparison": "notPerformedSinglePinnedRelease",
            "lifecycleSupportClaimed": False,
            "supportedChangeEventTypesAfterTwoReleaseComparison": [
                "add",
                "remove",
                "replace",
                "split",
                "merge",
                "relabel",
                "reparent",
            ],
        },
    }

    rights_metadata = RightsMetadata(
        rights_status="stated",
        source_artifact=acquired.metadata.source_url,
        source_digest=acquired.metadata.sha256,
        rights_statement=acquired.release.license_iri,
        license=acquired.release.license_iri,
        attribution=acquired.release.attribution,
    )
    rights = {
        "recordType": "EuroVocOrganizationExperimentRights",
        "publisherRightsMetadata": rights_metadata.as_record(),
        "sourcePublisher": {
            "label": acquired.release.publisher,
            "sourceIris": list(metadata.publisher_iris),
            "evidencePredicate": str(DCTERMS.publisher),
            "metadataArtifactDigest": acquired.metadata.sha256,
        },
        "licenseLabel": acquired.release.license_label,
        "evaluationDecision": "localInternalEvaluationAllowedSubjectToSourceTerms",
        "publicRedistributionDecision": "notAuthorizedByThisExperiment",
        "notice": "Internal evaluation and public redistribution require separate approval.",
    }

    identity_reconciliation = {
        "status": "unresolvedSameVersionLineage",
        "commonVersion": metadata.version,
        "publisherDataset": {
            "iri": metadata.dataset_iri,
            "archetypeIris": list(metadata.archetype_iris),
            "issued": metadata.issued,
            "modified": metadata.modified,
            "metadataRdfConceptCount": metadata.rdf_concept_count,
        },
        "publisherDistributions": list(metadata.distributions),
        "skosCoreAcquisition": {
            "sourceUrl": acquired.release.source_url,
            "archiveDigest": acquired.archive_sha256,
            "archiveByteLength": acquired.archive_byte_length,
            "memberName": acquired.release.member_filename,
            "memberDigest": acquired.sha256,
            "memberByteLength": acquired.byte_length,
            "acquisitionDateLabel": acquired.release.issued,
            "skosConceptCount": len(concept_iris) + len(domain_iris),
        },
        "refspecNormalizedPartition": {
            "iri": normalized_partition_iri,
            "authority": "RefSpecOperator",
        },
        "publisherDistributionMatchesSkosCoreAcquisition": matching_distribution_urls,
        "finding": (
            "The artifacts agree on version 4.24, but the 20260709 publisher metadata neither "
            "names the pinned 20260708 SKOS Core archive nor reports the same concept count. "
            "The experiment preserves all identities and does not assert distribution equivalence."
        ),
    }

    validation = {
        "recordType": "EuroVocOrganizationExperimentValidationReceipt",
        "verdict": "passed",
        "checks": [
            "independentMetadataAndSkosPins",
            "publisherDatasetAndDistributionCardinality",
            "selectedOrganizationObjectSetClosure",
            "exactMembershipSetClosureAndDirection",
            "membershipCardinalityOneToFour",
            "publisherDomainRelationAbsence",
            "candidatePublisherSeparation",
            "sourceAccountingClosure",
            "identityDiscrepancyPreserved",
            "lifecycleSupportNotClaimed",
        ],
        "counts": {
            "domains": len(domain_iris),
            "microthesauri": len(microthesaurus_iris),
            "ordinaryConcepts": len(concept_iris),
            "publisherMembershipAssertions": len(assertion_rows),
            "operatorDerivedDomainCandidates": len(candidate_rows),
        },
    }

    member_payloads: dict[str, bytes] = {
        OBJECTS_PATH: canonical_jsonl_bytes(object_rows),
        ASSERTIONS_PATH: canonical_jsonl_bytes(assertion_rows),
        CANDIDATES_PATH: canonical_jsonl_bytes(candidate_rows),
        CHANGE_EVENTS_PATH: b"",
        ACCOUNTING_PATH: canonical_json_bytes(source_accounting),
        RIGHTS_PATH: canonical_json_bytes(rights),
        VALIDATION_PATH: canonical_json_bytes(validation),
    }
    row_counts = {
        OBJECTS_PATH: len(object_rows),
        ASSERTIONS_PATH: len(assertion_rows),
        CANDIDATES_PATH: len(candidate_rows),
        CHANGE_EVENTS_PATH: 0,
        ACCOUNTING_PATH: 1,
        RIGHTS_PATH: 1,
        VALIDATION_PATH: 1,
    }
    members = [
        {
            "path": path,
            "role": MEMBER_ROLES[path],
            "mediaType": "application/x-ndjson" if path.endswith(".jsonl") else "application/json",
            "sha256": sha256_digest(payload),
            "byteLength": len(payload),
            "rowCount": row_counts[path],
        }
        for path, payload in sorted(member_payloads.items())
    ]

    module_path = Path(__file__).resolve()
    parser_path = Path(__file__).with_name("eurovoc_thesaurus.py").resolve()
    package_identity = {
        "experiment": EXPERIMENT_NAME,
        "schemaVersion": SCHEMA_VERSION,
        "recipeVersion": RECIPE_VERSION,
        "publisherDatasetIri": metadata.dataset_iri,
        "skosArchiveDigest": acquired.archive_sha256,
        "skosRdfMemberDigest": acquired.sha256,
        "metadataDigest": acquired.metadata.sha256 if acquired.metadata else None,
    }
    manifest_basis: dict[str, Any] = {
        "recordType": f"{EXPERIMENT_NAME}Manifest",
        "experimentId": _semantic_key("package", package_identity),
        "schemaVersion": SCHEMA_VERSION,
        "status": {
            "developmentOnly": True,
            "candidateUseOnly": True,
            "canonicalAtlas": False,
            "atlasSearchView": False,
            "spicySearchUseAuthorized": False,
            "publicRelease": False,
        },
        "construction": {
            "recipe": "refspec.registry.eurovoc_organization_experiment",
            "recipeVersion": RECIPE_VERSION,
            "recipeCodeDigest": _code_digest(module_path),
            "parser": "refspec.registry.eurovoc_thesaurus.parse_acquired_eurovoc_release",
            "parserCodeDigest": _code_digest(parser_path),
            "pythonVersion": platform.python_version(),
            "rdflibVersion": rdflib.__version__,
            "canonicalJson": "UTF-8, sorted keys, compact separators, terminal LF per JSON value",
        },
        "inputs": {
            "publisherMetadata": {
                "acquisitionUrl": acquired.metadata.source_url if acquired.metadata else None,
                "sourceIri": metadata.source_iri,
                "sha256": acquired.metadata.sha256 if acquired.metadata else None,
                "byteLength": acquired.metadata.byte_length if acquired.metadata else None,
                "tripleCount": metadata.triple_count,
            },
            "skosCoreArchive": {
                "acquisitionUrl": acquired.release.source_url,
                "sha256": acquired.archive_sha256,
                "byteLength": acquired.archive_byte_length,
            },
            "skosRdfMember": {
                "name": acquired.release.member_filename,
                "sha256": acquired.sha256,
                "byteLength": acquired.byte_length,
            },
        },
        "identityReconciliation": identity_reconciliation,
        "claims": {
            "publisherOrganizationSlicePreserved": True,
            "completePublisherOrganizationGraphPreserved": False,
            "publisherMicrothesaurusDomainRelationsPresent": False,
            "operatorDomainLinksAreCandidatesOnly": True,
            "lifecycleSupport": False,
            "taxonomyAdopted": False,
            "metaSubjectsCreated": False,
        },
        "members": members,
    }
    manifest_basis["canonicalPayloadDigest"] = sha256_digest(canonical_json_bytes(manifest_basis))
    manifest_payload = canonical_json_bytes(manifest_basis)
    files = {MANIFEST_PATH: manifest_payload, **member_payloads}
    return EuroVocOrganizationArtifact(files=files, manifest=manifest_basis)


def build_eurovoc_organization_artifact_from_paths(
    release: EuroVocReleaseSource,
    *,
    archive_path: Path,
    metadata_path: Path,
    normalized_partition_iri: str = DEFAULT_NORMALIZED_PARTITION_IRI,
) -> EuroVocOrganizationArtifact:
    """Acquire exact local inputs into a temporary store, then build."""

    with tempfile.TemporaryDirectory(prefix="refspec-eurovoc-organization-") as temporary:
        acquired = acquire_eurovoc_release(
            release,
            Path(temporary),
            source_path=archive_path,
            metadata_path=metadata_path,
            include_metadata=True,
            allow_network=False,
        )
        return build_eurovoc_organization_artifact(
            acquired,
            normalized_partition_iri=normalized_partition_iri,
        )


def verify_eurovoc_organization_directory(
    output_dir: Path,
    expected: EuroVocOrganizationArtifact,
) -> None:
    """Refuse any missing, extra, linked, or byte-different output member."""

    root = Path(output_dir)
    if root.is_symlink() or not root.is_dir():
        raise EuroVocOrganizationExperimentError(f"experiment output is not a regular directory: {root}")
    actual_names = {path.name for path in root.iterdir()}
    if actual_names != EXPECTED_FILE_SET:
        raise EuroVocOrganizationExperimentError(
            f"experiment file set differs: expected {sorted(EXPECTED_FILE_SET)!r}, got {sorted(actual_names)!r}"
        )
    for name in sorted(EXPECTED_FILE_SET):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise EuroVocOrganizationExperimentError(f"experiment member is not a regular file: {path}")
        actual = path.read_bytes()
        wanted = expected.files[name]
        if actual != wanted:
            raise EuroVocOrganizationExperimentError(
                f"experiment member differs from a cold rebuild: {name}; "
                f"expected {sha256_digest(wanted)}, got {sha256_digest(actual)}"
            )


def materialize_eurovoc_organization_artifact(
    output_dir: Path,
    artifact: EuroVocOrganizationArtifact,
) -> bool:
    """Publish once atomically; refuse to overwrite a differing directory.

    Returns ``True`` for a new directory and ``False`` when an identical,
    already verified directory was present.
    """

    root = Path(output_dir)
    if root.exists() or root.is_symlink():
        verify_eurovoc_organization_directory(root, artifact)
        return False
    parent = root.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{root.name}-", dir=parent))
    try:
        for name, payload in sorted(artifact.files.items()):
            path = temporary / name
            with path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(temporary, root)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    verify_eurovoc_organization_directory(root, artifact)
    return True


__all__ = [
    "ACCOUNTING_PATH",
    "ASSERTIONS_PATH",
    "CANDIDATES_PATH",
    "CHANGE_EVENTS_PATH",
    "DEFAULT_NORMALIZED_PARTITION_IRI",
    "MANIFEST_PATH",
    "OBJECTS_PATH",
    "RIGHTS_PATH",
    "VALIDATION_PATH",
    "EuroVocOrganizationArtifact",
    "EuroVocOrganizationExperimentError",
    "build_eurovoc_organization_artifact",
    "build_eurovoc_organization_artifact_from_paths",
    "materialize_eurovoc_organization_artifact",
    "verify_eurovoc_organization_directory",
]
