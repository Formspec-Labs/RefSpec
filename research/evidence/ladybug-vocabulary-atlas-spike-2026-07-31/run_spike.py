"""Build and verify a disposable LadybugDB view of one vocabulary atlas.

The N-Quads and atlas manifest remain authoritative.  This script projects a
bounded, typed property graph, compares representative Cypher results with
direct RDF baselines, and then proves that the database can be served read-only.

LadybugDB and PyOxigraph are intentionally spike-only dependencies.  See the
adjacent README for the isolated installation command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import tempfile
import time
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ladybug
import pyarrow as pa
import pyarrow.parquet as pq
import pyoxigraph
from pyoxigraph import Literal, NamedNode, RdfFormat, Store

ATLAS = "https://spicy-regs.dev/ns/vocabulary-atlas#"
RKAF = "https://rulespec.org/ns/v1#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
DCTERMS = "http://purl.org/dc/terms/"
PROV = "http://www.w3.org/ns/prov#"
DCAT_VERSION = "http://www.w3.org/ns/dcat#version"

API_TOPIC = f"{ATLAS}FederalRegisterApiTopic"
LISTS_OF_SUBJECTS = f"{ATLAS}FederalRegisterListOfSubjects"
FR_AGENCY = f"{ATLAS}FederalRegisterAgency"
FR_DOCUMENT_TYPE = f"{ATLAS}FederalRegisterDocumentType"
FR_CFR_REFERENCE = f"{ATLAS}FederalRegisterCfrReference"
REVIEW_QUEUE_ONLY = f"{RKAF}reviewQueueOnly"
LOCAL_OPERATIONAL_USE = f"{RKAF}localOperationalUse"
UNDETERMINED_MAPPING = f"{ATLAS}UndeterminedMappingRelation"
UNRESOLVED = f"{ATLAS}Unresolved"
FR_2025_RELEASE = "urn:ref:federal-register-thesaurus:2025-04-01:managed-release:v1"

PREFIXES = f"""
PREFIX va: <{ATLAS}>
PREFIX rkaf: <{RKAF}>
PREFIX rdf: <{RDF}>
PREFIX rdfs: <{RDFS}>
PREFIX skos: <{SKOS}>
PREFIX dcterms: <{DCTERMS}>
PREFIX prov: <{PROV}>
"""


@dataclass(slots=True)
class TableSpec:
    """One deterministic Parquet table and its Ladybug DDL."""

    name: str
    columns: tuple[tuple[str, pa.DataType], ...]
    kind: str
    source_table: str | None = None
    target_table: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def schema(self) -> pa.Schema:
        return pa.schema([pa.field(name, datatype) for name, datatype in self.columns])

    @property
    def ddl(self) -> str:
        type_names = {
            pa.string(): "STRING",
            pa.bool_(): "BOOL",
            pa.int64(): "INT64",
            pa.float64(): "DOUBLE",
        }
        if self.kind == "node":
            fields = [f"{name} {type_names[datatype]}" for name, datatype in self.columns]
            fields.append(f"PRIMARY KEY({self.columns[0][0]})")
            return f"CREATE NODE TABLE {self.name}({', '.join(fields)})"
        properties = [f"{name} {type_names[datatype]}" for name, datatype in self.columns[2:]]
        tail = f", {', '.join(properties)}" if properties else ""
        return f"CREATE REL TABLE {self.name}(FROM {self.source_table} TO {self.target_table}{tail})"


def node(name: str, *columns: tuple[str, pa.DataType]) -> TableSpec:
    return TableSpec(name, (("iri", pa.string()), *columns), "node")


def relation(
    name: str,
    source: str,
    target: str,
    *columns: tuple[str, pa.DataType],
) -> TableSpec:
    return TableSpec(
        name,
        (("from_iri", pa.string()), ("to_iri", pa.string()), *columns),
        "relationship",
        source,
        target,
    )


def make_tables() -> dict[str, TableSpec]:
    specs = [
        node(
            "AtlasGeneration",
            ("generation_digest", pa.string()),
            ("schema_version", pa.string()),
            ("asserted_graph_iri", pa.string()),
            ("analysis_graph_iri", pa.string()),
            ("rdf_sha256", pa.string()),
        ),
        node("ConceptScheme", ("label", pa.string())),
        node(
            "ManagedRelease",
            ("version", pa.string()),
            ("release_digest", pa.string()),
            ("usage_ceiling", pa.string()),
            ("source_priority_policy", pa.string()),
            ("candidate_lookup_allowed", pa.bool_()),
            ("accepted_output_allowed", pa.bool_()),
            ("root_ontology", pa.bool_()),
        ),
        node(
            "CandidateRoute",
            ("facet_iri", pa.string()),
            ("role_iri", pa.string()),
            ("resource_route", pa.string()),
            ("authorization_basis_iri", pa.string()),
            ("candidate_use_allowed", pa.bool_()),
            ("accepted_output_allowed", pa.bool_()),
        ),
        node(
            "Concept",
            ("label", pa.string()),
            ("release_iri", pa.string()),
            ("scheme_iri", pa.string()),
        ),
        node(
            "VocabularyExpression",
            ("text_value", pa.string()),
            ("language", pa.string()),
            ("datatype_iri", pa.string()),
            ("semantic_property_iri", pa.string()),
            ("label_role", pa.string()),
            ("indexed_text", pa.string()),
            ("source_path", pa.string()),
            ("candidate_eligible", pa.bool_()),
        ),
        node(
            "LabelKey",
            ("normalized_label", pa.string()),
            ("concept_identity_claimed", pa.bool_()),
        ),
        node(
            "Document",
            ("identifier", pa.string()),
            ("title", pa.string()),
            ("source_record_digest", pa.string()),
            ("source_url", pa.string()),
        ),
        node("Docket", ("identifier", pa.string())),
        node(
            "IdentitySignal",
            ("family", pa.string()),
            ("predicate_iri", pa.string()),
            ("value_term_kind", pa.string()),
            ("value_lexical", pa.string()),
            ("value_language", pa.string()),
            ("value_datatype_iri", pa.string()),
        ),
        node(
            "SourceObservationSnapshot",
            ("release_digest", pa.string()),
            ("concept_identity_claimed", pa.bool_()),
        ),
        node(
            "SourceControlObservation",
            ("kind_iri", pa.string()),
            ("facet_iri", pa.string()),
            ("value_term_kind", pa.string()),
            ("value_lexical", pa.string()),
            ("value_datatype_iri", pa.string()),
            ("value_language", pa.string()),
            ("source_path", pa.string()),
            ("source_record_digest", pa.string()),
            ("concept_identity_claimed", pa.bool_()),
        ),
        node(
            "SourceTermObservation",
            ("kind_iri", pa.string()),
            ("source_collection", pa.string()),
            ("label_record_iri", pa.string()),
            ("label", pa.string()),
            ("label_language", pa.string()),
            ("label_role", pa.string()),
            ("normalized_label", pa.string()),
            ("source_path", pa.string()),
            ("source_record_digest", pa.string()),
            ("concept_identity_claimed", pa.bool_()),
        ),
        node(
            "SourceTermResolution",
            ("status", pa.string()),
            ("policy_version", pa.string()),
            ("reason", pa.string()),
            ("concept_minted", pa.bool_()),
            ("variant_ids_json", pa.string()),
        ),
        node(
            "SourceFragment",
            ("text_value", pa.string()),
            ("language", pa.string()),
            ("datatype_iri", pa.string()),
            ("source_path", pa.string()),
            ("source_record_digest", pa.string()),
        ),
        node(
            "CandidateAssignment",
            ("role_iri", pa.string()),
            ("origin_iri", pa.string()),
            ("polarity_iri", pa.string()),
            ("eligibility_iri", pa.string()),
            ("source_observation_iri", pa.string()),
            ("resolution_iri", pa.string()),
        ),
        node(
            "AcceptedAssignment",
            ("role_iri", pa.string()),
            ("origin_iri", pa.string()),
            ("polarity_iri", pa.string()),
            ("eligibility_iri", pa.string()),
            ("source_observation_iri", pa.string()),
            ("resolution_iri", pa.string()),
        ),
        node(
            "ConceptMappingCandidate",
            ("proposed_relation_iri", pa.string()),
            ("generation_method_iri", pa.string()),
            ("normalized_label", pa.string()),
            ("source_label", pa.string()),
            ("target_label", pa.string()),
            ("review_status_iri", pa.string()),
        ),
        node(
            "ReviewedConceptMapping",
            ("relation_iri", pa.string()),
            ("review_status_iri", pa.string()),
            ("origin_iri", pa.string()),
            ("basis_iri", pa.string()),
            ("eligibility_iri", pa.string()),
            ("polarity_iri", pa.string()),
        ),
        node(
            "ObservationConceptCandidate",
            ("facet_iri", pa.string()),
            ("role_iri", pa.string()),
            ("normalized_label", pa.string()),
            ("generation_method_iri", pa.string()),
            ("review_status_iri", pa.string()),
        ),
        node(
            "RelatednessPolicy",
            ("policy_digest", pa.string()),
            ("max_document_frequency_ratio", pa.float64()),
            ("minimum_document_population", pa.int64()),
            ("source_topic_observation_kinds_json", pa.string()),
            ("source_relation_use_iri", pa.string()),
            ("output_authority_iri", pa.string()),
        ),
        node(
            "RelatednessDimension",
            ("facet_iri", pa.string()),
            ("role_iri", pa.string()),
        ),
        node(
            "UnresolvedVocabularyRelation",
            ("source_concept_iri", pa.string()),
            ("predicate_iri", pa.string()),
            ("release_iri", pa.string()),
        ),
        relation("RELEASE_OF", "ManagedRelease", "ConceptScheme"),
        relation("ROUTES_RELEASE", "CandidateRoute", "ManagedRelease"),
        relation("MEMBER_OF_RELEASE", "Concept", "ManagedRelease"),
        relation("IN_SCHEME", "Concept", "ConceptScheme"),
        relation("EXPRESSION_OF", "VocabularyExpression", "Concept"),
        relation("EXPRESSION_IN_RELEASE", "VocabularyExpression", "ManagedRelease"),
        relation("EXPRESSION_KEY", "VocabularyExpression", "LabelKey"),
        relation("ELIGIBLE_VIA", "VocabularyExpression", "CandidateRoute"),
        relation(
            "BROADER",
            "Concept",
            "Concept",
            ("record_iri", pa.string()),
            ("release_iri", pa.string()),
        ),
        relation(
            "NARROWER",
            "Concept",
            "Concept",
            ("record_iri", pa.string()),
            ("release_iri", pa.string()),
        ),
        relation(
            "RELATED",
            "Concept",
            "Concept",
            ("record_iri", pa.string()),
            ("release_iri", pa.string()),
        ),
        relation(
            "REDIRECTS_TO",
            "Concept",
            "Concept",
            ("record_iri", pa.string()),
            ("release_iri", pa.string()),
        ),
        relation(
            "REDIRECTED_FROM",
            "Concept",
            "Concept",
            ("record_iri", pa.string()),
            ("release_iri", pa.string()),
        ),
        relation("CONTROL_ON", "SourceControlObservation", "Document"),
        relation("TERM_ON", "SourceTermObservation", "Document"),
        relation(
            "TERM_IN_SNAPSHOT",
            "SourceTermObservation",
            "SourceObservationSnapshot",
        ),
        relation("OBSERVATION_KEY", "SourceTermObservation", "LabelKey"),
        relation("RESOLUTION_OF", "SourceTermResolution", "SourceTermObservation"),
        relation("RESOLVES_TO", "SourceTermResolution", "Concept"),
        relation("FRAGMENT_OF", "SourceFragment", "Document"),
        relation("PUBLISHED_IN_DOCKET", "Document", "Docket"),
        relation("SIGNAL_ON", "IdentitySignal", "Document"),
        relation(
            "EXPLICIT_LINK",
            "Document",
            "Document",
            ("assertion_iri", pa.string()),
            ("predicate_iri", pa.string()),
            ("polarity_iri", pa.string()),
            ("eligibility_iri", pa.string()),
            ("origin_iri", pa.string()),
            ("source_path", pa.string()),
            ("join_value", pa.string()),
            ("left_digest", pa.string()),
            ("right_digest", pa.string()),
        ),
        relation("CANDIDATE_ASSIGNS_DOCUMENT", "CandidateAssignment", "Document"),
        relation("CANDIDATE_ASSIGNS_CONCEPT", "CandidateAssignment", "Concept"),
        relation("CANDIDATE_ASSIGNED_RELEASE", "CandidateAssignment", "ManagedRelease"),
        relation("CANDIDATE_USES_ROUTE", "CandidateAssignment", "CandidateRoute"),
        relation(
            "CANDIDATE_FROM_OBSERVATION",
            "CandidateAssignment",
            "SourceTermObservation",
        ),
        relation(
            "CANDIDATE_AUTHORIZED_BY_RESOLUTION",
            "CandidateAssignment",
            "SourceTermResolution",
        ),
        relation(
            "CANDIDATE_EVIDENCED_BY",
            "CandidateAssignment",
            "SourceFragment",
            ("binding_iri", pa.string()),
        ),
        relation("ACCEPTED_ASSIGNS_DOCUMENT", "AcceptedAssignment", "Document"),
        relation("ACCEPTED_ASSIGNS_CONCEPT", "AcceptedAssignment", "Concept"),
        relation("ACCEPTED_ASSIGNED_RELEASE", "AcceptedAssignment", "ManagedRelease"),
        relation(
            "ACCEPTED_EVIDENCED_BY",
            "AcceptedAssignment",
            "SourceFragment",
            ("binding_iri", pa.string()),
        ),
        relation("MAPPING_CANDIDATE_FROM", "ConceptMappingCandidate", "Concept"),
        relation("MAPPING_CANDIDATE_TO", "ConceptMappingCandidate", "Concept"),
        relation("REVIEWED_MAPPING_FROM", "ReviewedConceptMapping", "Concept"),
        relation("REVIEWED_MAPPING_TO", "ReviewedConceptMapping", "Concept"),
        relation(
            "OBSERVATION_CANDIDATE_FROM",
            "ObservationConceptCandidate",
            "SourceTermObservation",
        ),
        relation(
            "OBSERVATION_CANDIDATE_TO",
            "ObservationConceptCandidate",
            "Concept",
        ),
        relation(
            "MATCHED_EXPRESSION",
            "ObservationConceptCandidate",
            "VocabularyExpression",
        ),
        relation(
            "OBSERVATION_CANDIDATE_USES_ROUTE",
            "ObservationConceptCandidate",
            "CandidateRoute",
        ),
        relation(
            "POLICY_ALLOWS_DIMENSION",
            "RelatednessPolicy",
            "RelatednessDimension",
        ),
    ]
    return {spec.name: spec for spec in specs}


ANALYSIS_TABLES = frozenset(
    {
        "CandidateAssignment",
        "CANDIDATE_ASSIGNS_DOCUMENT",
        "CANDIDATE_ASSIGNS_CONCEPT",
        "CANDIDATE_ASSIGNED_RELEASE",
        "CANDIDATE_USES_ROUTE",
        "CANDIDATE_FROM_OBSERVATION",
        "CANDIDATE_AUTHORIZED_BY_RESOLUTION",
        "CANDIDATE_EVIDENCED_BY",
        "ConceptMappingCandidate",
        "MAPPING_CANDIDATE_FROM",
        "MAPPING_CANDIDATE_TO",
        "ObservationConceptCandidate",
        "OBSERVATION_CANDIDATE_FROM",
        "OBSERVATION_CANDIDATE_TO",
        "MATCHED_EXPRESSION",
        "OBSERVATION_CANDIDATE_USES_ROUTE",
        "RelatednessPolicy",
        "RelatednessDimension",
        "POLICY_ALLOWS_DIMENSION",
    }
)
DERIVED_INDEX_TABLES = frozenset(
    {
        "LabelKey",
        "EXPRESSION_KEY",
        "OBSERVATION_KEY",
        "IdentitySignal",
        "SIGNAL_ON",
    }
)


def table_authority_class(table_name: str) -> str:
    if table_name in ANALYSIS_TABLES:
        return "analysis"
    if table_name in DERIVED_INDEX_TABLES:
        return "derived-index"
    return "asserted"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def normalized_label(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def label_key_iri(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"urn:spicy-regs:ladybug-label-key:{digest}"


def value(term: NamedNode | Literal | None) -> str | None:
    return None if term is None else term.value


def boolean(term: NamedNode | Literal | None) -> bool | None:
    if term is None:
        return None
    return term.value.casefold() == "true"


def integer(term: NamedNode | Literal | None) -> int | None:
    return None if term is None else int(term.value)


def floating(term: NamedNode | Literal | None) -> float | None:
    return None if term is None else float(term.value)


def term_parts(term: NamedNode | Literal) -> tuple[str, str, str | None, str | None]:
    if isinstance(term, NamedNode):
        return "iri", term.value, None, None
    datatype = term.datatype.value if term.datatype is not None else None
    return "literal", term.value, datatype, term.language


def solution(row: pyoxigraph.QuerySolution, *names: str) -> dict[str, Any]:
    return {name: row[name] for name in names}


def query_rows(store: Store, query: str, *names: str) -> list[dict[str, Any]]:
    return [solution(row, *names) for row in store.query(PREFIXES + query)]


def graph_query(graph_iri: str, body: str) -> str:
    return f"SELECT * WHERE {{ GRAPH <{graph_iri}> {{ {body} }} }}"


def add_row(tables: dict[str, TableSpec], table: str, **row: Any) -> None:
    spec = tables[table]
    expected = {name for name, _ in spec.columns}
    if set(row) != expected:
        missing = sorted(expected - set(row))
        extra = sorted(set(row) - expected)
        raise ValueError(f"{table} row mismatch; missing={missing}, extra={extra}")
    spec.rows.append(row)


def best_label(values: Iterable[Literal]) -> str | None:
    candidates = list(values)
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            0 if item.language == "en" else 1 if item.language is None else 2,
            normalized_label(item.value),
            item.value,
        )
    )
    return candidates[0].value


def extract_projection(
    store: Store,
    manifest: dict[str, Any],
    tables: dict[str, TableSpec],
) -> None:
    asserted = manifest["graphs"]["atlas"]["id"]
    analysis = manifest["graphs"]["analysis"]["id"]
    generation = query_rows(
        store,
        graph_query(
            asserted,
            "?iri a va:AtlasGeneration ; va:generationDigest ?digest ; va:analysisGraph ?analysis .",
        ),
        "iri",
        "digest",
        "analysis",
    )
    if len(generation) != 1:
        raise ValueError(f"expected one atlas generation, found {len(generation)}")
    generation_identity = {
        "assertedGraphIri": value(generation[0]["iri"]),
        "generationDigest": value(generation[0]["digest"]),
        "analysisGraphIri": value(generation[0]["analysis"]),
    }
    expected_generation_identity = {
        "assertedGraphIri": asserted,
        "generationDigest": manifest["generationDigest"],
        "analysisGraphIri": analysis,
    }
    if generation_identity != expected_generation_identity:
        raise ValueError(
            "RDF generation identity differs from the atlas manifest: "
            + json.dumps(
                {
                    "actual": generation_identity,
                    "expected": expected_generation_identity,
                },
                sort_keys=True,
            )
        )
    analysis_generation = query_rows(
        store,
        graph_query(
            analysis,
            "?iri a va:AnalysisGeneration ; prov:wasDerivedFrom ?asserted .",
        ),
        "iri",
        "asserted",
    )
    actual_analysis_generation = [
        {
            "analysisGraphIri": value(row["iri"]),
            "assertedGraphIri": value(row["asserted"]),
        }
        for row in analysis_generation
    ]
    expected_analysis_generation = [
        {
            "analysisGraphIri": analysis,
            "assertedGraphIri": asserted,
        }
    ]
    if actual_analysis_generation != expected_analysis_generation:
        raise ValueError(
            "analysis graph provenance differs from the atlas manifest: "
            + json.dumps(
                {
                    "actual": actual_analysis_generation,
                    "expected": expected_analysis_generation,
                },
                sort_keys=True,
            )
        )
    add_row(
        tables,
        "AtlasGeneration",
        iri=generation_identity["assertedGraphIri"],
        generation_digest=generation_identity["generationDigest"],
        schema_version=manifest["schemaVersion"],
        asserted_graph_iri=asserted,
        analysis_graph_iri=generation_identity["analysisGraphIri"],
        rdf_sha256=manifest["output"]["sha256"],
    )

    scheme_labels: dict[str, list[Literal]] = defaultdict(list)
    for row in query_rows(
        store,
        graph_query(
            asserted,
            "?iri a skos:ConceptScheme . OPTIONAL { ?iri skos:prefLabel ?label . }",
        ),
        "iri",
        "label",
    ):
        if row["label"] is not None:
            scheme_labels[value(row["iri"])].append(row["label"])
    scheme_ids = sorted(
        {
            value(row["iri"])
            for row in query_rows(
                store,
                graph_query(asserted, "?iri a skos:ConceptScheme ."),
                "iri",
            )
        }
    )
    for iri in scheme_ids:
        add_row(tables, "ConceptScheme", iri=iri, label=best_label(scheme_labels[iri]))

    for row in query_rows(
        store,
        graph_query(
            asserted,
            f"""
            ?iri a va:ManagedVocabularySnapshot ;
                 dcterms:isVersionOf ?scheme ;
                 <{DCAT_VERSION}> ?version ;
                 va:releaseDigest ?release_digest ;
                 va:usageCeiling ?usage_ceiling .
            OPTIONAL {{ ?iri va:sourcePriorityPolicy ?priority . }}
            OPTIONAL {{ ?iri va:candidateLookupAllowed ?lookup_allowed . }}
            OPTIONAL {{ ?iri va:acceptedOutputAllowed ?accepted_allowed . }}
            OPTIONAL {{ ?iri va:rootOntology ?root_ontology . }}
            """,
        ),
        "iri",
        "scheme",
        "version",
        "release_digest",
        "usage_ceiling",
        "priority",
        "lookup_allowed",
        "accepted_allowed",
        "root_ontology",
    ):
        release_iri = value(row["iri"])
        scheme_iri = value(row["scheme"])
        add_row(
            tables,
            "ManagedRelease",
            iri=release_iri,
            version=value(row["version"]),
            release_digest=value(row["release_digest"]),
            usage_ceiling=value(row["usage_ceiling"]),
            source_priority_policy=value(row["priority"]),
            candidate_lookup_allowed=boolean(row["lookup_allowed"]),
            accepted_output_allowed=boolean(row["accepted_allowed"]),
            root_ontology=boolean(row["root_ontology"]),
        )
        add_row(tables, "RELEASE_OF", from_iri=release_iri, to_iri=scheme_iri)

    for row in query_rows(
        store,
        graph_query(
            asserted,
            """
            ?iri a va:CandidateRoute ; va:memberRelease ?release ;
                va:semanticFacet ?facet ; va:assignmentRole ?role ;
                va:resourceRoute ?resource_route ;
                va:authorizationBasis ?basis ;
                va:candidateUseAllowed ?candidate_allowed ;
                va:acceptedOutputAllowed ?accepted_allowed .
            """,
        ),
        "iri",
        "release",
        "facet",
        "role",
        "resource_route",
        "basis",
        "candidate_allowed",
        "accepted_allowed",
    ):
        route_iri = value(row["iri"])
        release_iri = value(row["release"])
        add_row(
            tables,
            "CandidateRoute",
            iri=route_iri,
            facet_iri=value(row["facet"]),
            role_iri=value(row["role"]),
            resource_route=value(row["resource_route"]),
            authorization_basis_iri=value(row["basis"]),
            candidate_use_allowed=boolean(row["candidate_allowed"]),
            accepted_output_allowed=boolean(row["accepted_allowed"]),
        )
        add_row(tables, "ROUTES_RELEASE", from_iri=route_iri, to_iri=release_iri)

    concept_labels: dict[str, list[Literal]] = defaultdict(list)
    for row in query_rows(
        store,
        graph_query(
            asserted,
            "?iri a skos:Concept . OPTIONAL { ?iri skos:prefLabel ?label . }",
        ),
        "iri",
        "label",
    ):
        if row["label"] is not None:
            concept_labels[value(row["iri"])].append(row["label"])
    for row in query_rows(
        store,
        graph_query(
            asserted,
            "?iri a skos:Concept ; va:memberOf ?release ; skos:inScheme ?scheme .",
        ),
        "iri",
        "release",
        "scheme",
    ):
        concept_iri = value(row["iri"])
        release_iri = value(row["release"])
        scheme_iri = value(row["scheme"])
        add_row(
            tables,
            "Concept",
            iri=concept_iri,
            label=best_label(concept_labels[concept_iri]),
            release_iri=release_iri,
            scheme_iri=scheme_iri,
        )
        add_row(tables, "MEMBER_OF_RELEASE", from_iri=concept_iri, to_iri=release_iri)
        add_row(tables, "IN_SCHEME", from_iri=concept_iri, to_iri=scheme_iri)

    label_keys: dict[str, str] = {}

    def ensure_key(label: str) -> str:
        normalized = normalized_label(label)
        key_iri = label_keys.get(normalized)
        if key_iri is None:
            key_iri = label_key_iri(normalized)
            label_keys[normalized] = key_iri
            add_row(
                tables,
                "LabelKey",
                iri=key_iri,
                normalized_label=normalized,
                concept_identity_claimed=False,
            )
        return key_iri

    expression_rows = query_rows(
        store,
        graph_query(
            asserted,
            """
            ?iri a va:IndexedVocabularyExpression ; va:member ?concept ;
                va:memberRelease ?release ; va:semanticProperty ?property ;
                rdf:value ?text ; va:labelRole ?role ;
                va:candidateEligible ?eligible ; va:sourcePropertyOrPath ?path .
            OPTIONAL { ?iri va:indexedText ?indexed . }
            """,
        ),
        "iri",
        "concept",
        "release",
        "property",
        "text",
        "role",
        "eligible",
        "path",
        "indexed",
    )
    label_predicates = {f"{SKOS}prefLabel", f"{SKOS}altLabel", f"{SKOS}hiddenLabel"}
    for row in expression_rows:
        expression_iri = value(row["iri"])
        concept_iri = value(row["concept"])
        release_iri = value(row["release"])
        text_term = row["text"]
        _, text_value, datatype_iri, language = term_parts(text_term)
        property_iri = value(row["property"])
        indexed = value(row["indexed"])
        add_row(
            tables,
            "VocabularyExpression",
            iri=expression_iri,
            text_value=text_value,
            language=language,
            datatype_iri=datatype_iri,
            semantic_property_iri=property_iri,
            label_role=value(row["role"]),
            indexed_text=indexed,
            source_path=value(row["path"]),
            candidate_eligible=boolean(row["eligible"]),
        )
        add_row(tables, "EXPRESSION_OF", from_iri=expression_iri, to_iri=concept_iri)
        add_row(
            tables,
            "EXPRESSION_IN_RELEASE",
            from_iri=expression_iri,
            to_iri=release_iri,
        )
        if property_iri in label_predicates:
            key_iri = ensure_key(indexed or text_value)
            add_row(tables, "EXPRESSION_KEY", from_iri=expression_iri, to_iri=key_iri)

    for row in query_rows(
        store,
        graph_query(asserted, "?expression va:candidateRoute ?route ."),
        "expression",
        "route",
    ):
        add_row(
            tables,
            "ELIGIBLE_VIA",
            from_iri=value(row["expression"]),
            to_iri=value(row["route"]),
        )

    relation_rows = query_rows(
        store,
        graph_query(
            asserted,
            """
            ?record a va:SourceRelationRecord ; va:assertsSubject ?source ;
                va:assertsPredicate ?predicate ; va:memberRelease ?release .
            OPTIONAL { ?record va:assertsObject ?target . }
            """,
        ),
        "record",
        "source",
        "predicate",
        "release",
        "target",
    )
    relation_table_by_predicate = {
        f"{SKOS}broader": "BROADER",
        f"{SKOS}narrower": "NARROWER",
        f"{SKOS}related": "RELATED",
        f"{ATLAS}redirectsTo": "REDIRECTS_TO",
        f"{ATLAS}redirectedFrom": "REDIRECTED_FROM",
    }
    for row in relation_rows:
        record_iri = value(row["record"])
        if row["target"] is None:
            add_row(
                tables,
                "UnresolvedVocabularyRelation",
                iri=record_iri,
                source_concept_iri=value(row["source"]),
                predicate_iri=value(row["predicate"]),
                release_iri=value(row["release"]),
            )
        else:
            predicate_iri = value(row["predicate"])
            relation_table = relation_table_by_predicate.get(predicate_iri)
            if relation_table is None:
                raise ValueError(f"unsupported source relation predicate: {predicate_iri}")
            add_row(
                tables,
                relation_table,
                from_iri=value(row["source"]),
                to_iri=value(row["target"]),
                record_iri=record_iri,
                release_iri=value(row["release"]),
            )

    extract_documents(store, asserted, tables)
    extract_source_observations(store, asserted, tables, ensure_key)
    extract_analysis(store, asserted, analysis, tables)


def extract_documents(
    store: Store,
    asserted: str,
    tables: dict[str, TableSpec],
) -> None:
    for row in query_rows(
        store,
        graph_query(
            asserted,
            """
            ?iri a rkaf:Artifact .
            OPTIONAL { ?iri dcterms:identifier ?identifier . }
            OPTIONAL { ?iri dcterms:title ?title . }
            OPTIONAL { ?iri va:sourceRecordDigest ?digest . }
            OPTIONAL { ?iri va:sourceUrl ?source_url . }
            """,
        ),
        "iri",
        "identifier",
        "title",
        "digest",
        "source_url",
    ):
        add_row(
            tables,
            "Document",
            iri=value(row["iri"]),
            identifier=value(row["identifier"]),
            title=value(row["title"]),
            source_record_digest=value(row["digest"]),
            source_url=value(row["source_url"]),
        )

    for row in query_rows(
        store,
        graph_query(
            asserted,
            "?iri a rkaf:Docket . OPTIONAL { ?iri dcterms:identifier ?identifier . }",
        ),
        "iri",
        "identifier",
    ):
        add_row(
            tables,
            "Docket",
            iri=value(row["iri"]),
            identifier=value(row["identifier"]),
        )
    for row in query_rows(
        store,
        graph_query(asserted, "?document rkaf:publishedInDocket ?docket ."),
        "document",
        "docket",
    ):
        add_row(
            tables,
            "PUBLISHED_IN_DOCKET",
            from_iri=value(row["document"]),
            to_iri=value(row["docket"]),
        )

    identity_families = {
        f"{RKAF}hasArtifactIdentifier": "artifact-identifier",
        f"{DCTERMS}identifier": "artifact-identifier",
        f"{RKAF}hasRegulatoryIdentifier": "regulatory-identifier",
        f"{RKAF}hasContentDigest": "content-digest",
        f"{ATLAS}identitySignal": "source-identity-signal",
    }
    predicates = " ".join(f"<{iri}>" for iri in identity_families)
    for row in query_rows(
        store,
        graph_query(
            asserted,
            f"?document a rkaf:Artifact ; ?predicate ?signal . VALUES ?predicate {{ {predicates} }}",
        ),
        "document",
        "predicate",
        "signal",
    ):
        document_iri = value(row["document"])
        predicate_iri = value(row["predicate"])
        kind, lexical, datatype, language = term_parts(row["signal"])
        signal_payload = f"{document_iri}\u001f{predicate_iri}\u001f{kind}\u001f{lexical}"
        signal_iri = (
            "urn:spicy-regs:ladybug-identity-signal:" + hashlib.sha256(signal_payload.encode("utf-8")).hexdigest()
        )
        add_row(
            tables,
            "IdentitySignal",
            iri=signal_iri,
            family=identity_families[predicate_iri],
            predicate_iri=predicate_iri,
            value_term_kind=kind,
            value_lexical=lexical,
            value_language=language,
            value_datatype_iri=datatype,
        )
        add_row(tables, "SIGNAL_ON", from_iri=signal_iri, to_iri=document_iri)

    for row in query_rows(
        store,
        graph_query(
            asserted,
            """
            ?iri a va:SourceControlObservation ; va:controlSubject ?document ;
                va:controlKind ?kind ; va:semanticFacet ?facet ;
                va:controlValue ?control_value ; va:sourcePropertyOrPath ?path ;
                va:sourceRecordDigest ?digest ;
                va:conceptIdentityClaimed ?identity_claimed .
            """,
        ),
        "iri",
        "document",
        "kind",
        "facet",
        "control_value",
        "path",
        "digest",
        "identity_claimed",
    ):
        kind, lexical, datatype, language = term_parts(row["control_value"])
        control_iri = value(row["iri"])
        add_row(
            tables,
            "SourceControlObservation",
            iri=control_iri,
            kind_iri=value(row["kind"]),
            facet_iri=value(row["facet"]),
            value_term_kind=kind,
            value_lexical=lexical,
            value_datatype_iri=datatype,
            value_language=language,
            source_path=value(row["path"]),
            source_record_digest=value(row["digest"]),
            concept_identity_claimed=boolean(row["identity_claimed"]),
        )
        add_row(
            tables,
            "CONTROL_ON",
            from_iri=control_iri,
            to_iri=value(row["document"]),
        )

    for row in query_rows(
        store,
        graph_query(
            asserted,
            """
            ?iri a rkaf:SourceFragment ; va:fragmentOf ?document ;
                rdf:value ?text ; va:sourcePropertyOrPath ?path ;
                va:sourceRecordDigest ?digest .
            """,
        ),
        "iri",
        "document",
        "text",
        "path",
        "digest",
    ):
        _, lexical, datatype, language = term_parts(row["text"])
        fragment_iri = value(row["iri"])
        add_row(
            tables,
            "SourceFragment",
            iri=fragment_iri,
            text_value=lexical,
            language=language,
            datatype_iri=datatype,
            source_path=value(row["path"]),
            source_record_digest=value(row["digest"]),
        )
        add_row(
            tables,
            "FRAGMENT_OF",
            from_iri=fragment_iri,
            to_iri=value(row["document"]),
        )

    for row in query_rows(
        store,
        graph_query(
            asserted,
            """
            ?assertion a rkaf:RelationshipAssertion ;
                rkaf:assertsSubject ?left ; rkaf:assertsPredicate ?predicate ;
                rkaf:assertsObject ?right ; rkaf:assertionPolarity ?polarity ;
                rkaf:usageEligibility ?eligibility ; rkaf:assertionOrigin ?origin .
            OPTIONAL { ?assertion va:sourcePropertyOrPath ?source_path . }
            OPTIONAL { ?assertion va:joinValue ?join_value . }
            OPTIONAL { ?assertion va:leftSourceRecordDigest ?left_digest . }
            OPTIONAL { ?assertion va:rightSourceRecordDigest ?right_digest . }
            """,
        ),
        "assertion",
        "left",
        "predicate",
        "right",
        "polarity",
        "eligibility",
        "origin",
        "source_path",
        "join_value",
        "left_digest",
        "right_digest",
    ):
        add_row(
            tables,
            "EXPLICIT_LINK",
            from_iri=value(row["left"]),
            to_iri=value(row["right"]),
            assertion_iri=value(row["assertion"]),
            predicate_iri=value(row["predicate"]),
            polarity_iri=value(row["polarity"]),
            eligibility_iri=value(row["eligibility"]),
            origin_iri=value(row["origin"]),
            source_path=value(row["source_path"]),
            join_value=value(row["join_value"]),
            left_digest=value(row["left_digest"]),
            right_digest=value(row["right_digest"]),
        )


def extract_source_observations(
    store: Store,
    asserted: str,
    tables: dict[str, TableSpec],
    ensure_key: Any,
) -> None:
    for row in query_rows(
        store,
        graph_query(
            asserted,
            """
            ?iri a va:SourceObservationSnapshot ; va:releaseDigest ?digest ;
                va:conceptIdentityClaimed ?identity_claimed .
            """,
        ),
        "iri",
        "digest",
        "identity_claimed",
    ):
        add_row(
            tables,
            "SourceObservationSnapshot",
            iri=value(row["iri"]),
            release_digest=value(row["digest"]),
            concept_identity_claimed=boolean(row["identity_claimed"]),
        )

    observations = query_rows(
        store,
        graph_query(
            asserted,
            """
            ?iri a va:SourceTermObservation ; va:conceptIdentityClaimed ?identity_claimed ;
                va:sourcePropertyOrPath ?path ; va:sourceRecordDigest ?digest .
            ?label_record a va:SourceObservationLabelRecord ; va:observation ?iri ;
                rdf:value ?label ; va:labelRole ?label_role ;
                va:normalizedLabel ?normalized_label .
            OPTIONAL { ?iri va:observationKind ?kind . }
            OPTIONAL { ?iri va:sourceCollection ?collection . }
            OPTIONAL { ?iri va:observedOn ?document . }
            OPTIONAL { ?iri va:observedIn ?snapshot . }
            """,
        ),
        "iri",
        "identity_claimed",
        "path",
        "digest",
        "label_record",
        "label",
        "label_role",
        "normalized_label",
        "kind",
        "collection",
        "document",
        "snapshot",
    )
    seen: set[str] = set()
    for row in observations:
        observation_iri = value(row["iri"])
        if observation_iri in seen:
            raise ValueError(
                f"the spike requires exactly one label record per source observation; duplicate={observation_iri}"
            )
        seen.add(observation_iri)
        label_term = row["label"]
        normalized = value(row["normalized_label"])
        add_row(
            tables,
            "SourceTermObservation",
            iri=observation_iri,
            kind_iri=value(row["kind"]),
            source_collection=value(row["collection"]),
            label_record_iri=value(row["label_record"]),
            label=label_term.value,
            label_language=label_term.language,
            label_role=value(row["label_role"]),
            normalized_label=normalized,
            source_path=value(row["path"]),
            source_record_digest=value(row["digest"]),
            concept_identity_claimed=boolean(row["identity_claimed"]),
        )
        key_iri = ensure_key(normalized)
        add_row(
            tables,
            "OBSERVATION_KEY",
            from_iri=observation_iri,
            to_iri=key_iri,
        )
        if row["document"] is not None:
            add_row(
                tables,
                "TERM_ON",
                from_iri=observation_iri,
                to_iri=value(row["document"]),
            )
        if row["snapshot"] is not None:
            add_row(
                tables,
                "TERM_IN_SNAPSHOT",
                from_iri=observation_iri,
                to_iri=value(row["snapshot"]),
            )

    resolution_base = query_rows(
        store,
        graph_query(
            asserted,
            """
            ?iri a va:SourceTermResolution ; va:sourceObservation ?observation ;
                va:resolutionStatus ?status ; va:resolutionPolicyVersion ?policy ;
                va:resolutionReason ?reason ; va:conceptMinted ?concept_minted .
            """,
        ),
        "iri",
        "observation",
        "status",
        "policy",
        "reason",
        "concept_minted",
    )
    variants: dict[str, set[str]] = defaultdict(set)
    for row in query_rows(
        store,
        graph_query(asserted, "?iri a va:SourceTermResolution ; va:sourceVariantId ?variant ."),
        "iri",
        "variant",
    ):
        variants[value(row["iri"])].add(value(row["variant"]))
    for row in resolution_base:
        resolution_iri = value(row["iri"])
        add_row(
            tables,
            "SourceTermResolution",
            iri=resolution_iri,
            status=value(row["status"]),
            policy_version=value(row["policy"]),
            reason=value(row["reason"]),
            concept_minted=boolean(row["concept_minted"]),
            variant_ids_json=json.dumps(sorted(variants[resolution_iri]), separators=(",", ":")),
        )
        add_row(
            tables,
            "RESOLUTION_OF",
            from_iri=resolution_iri,
            to_iri=value(row["observation"]),
        )
    for row in query_rows(
        store,
        graph_query(asserted, "?iri a va:SourceTermResolution ; va:resolvesTo ?concept ."),
        "iri",
        "concept",
    ):
        add_row(
            tables,
            "RESOLVES_TO",
            from_iri=value(row["iri"]),
            to_iri=value(row["concept"]),
        )


def extract_assignments(
    store: Store,
    graph_iri: str,
    tables: dict[str, TableSpec],
    node_table: str,
    prefix: str,
) -> None:
    rows = query_rows(
        store,
        graph_query(
            graph_iri,
            """
            ?iri a rkaf:ConceptAssignment ; rkaf:assertsSubject ?document ;
                rkaf:assertsPredicate ?role ; rkaf:assertsObject ?concept ;
                rkaf:assignedConceptRelease ?release ; rkaf:assertionOrigin ?origin ;
                rkaf:assertionPolarity ?polarity ; rkaf:usageEligibility ?eligibility .
            OPTIONAL { ?iri va:candidateRoute ?route . }
            OPTIONAL { ?iri va:sourceObservation ?observation . }
            OPTIONAL { ?iri va:sourceTermResolution ?resolution . }
            """,
        ),
        "iri",
        "document",
        "role",
        "concept",
        "release",
        "origin",
        "polarity",
        "eligibility",
        "route",
        "observation",
        "resolution",
    )
    for row in rows:
        assignment_iri = value(row["iri"])
        add_row(
            tables,
            node_table,
            iri=assignment_iri,
            role_iri=value(row["role"]),
            origin_iri=value(row["origin"]),
            polarity_iri=value(row["polarity"]),
            eligibility_iri=value(row["eligibility"]),
            source_observation_iri=value(row["observation"]),
            resolution_iri=value(row["resolution"]),
        )
        for suffix, target in (
            ("ASSIGNS_DOCUMENT", row["document"]),
            ("ASSIGNS_CONCEPT", row["concept"]),
            ("ASSIGNED_RELEASE", row["release"]),
        ):
            add_row(
                tables,
                f"{prefix}_{suffix}",
                from_iri=assignment_iri,
                to_iri=value(target),
            )
        if prefix == "CANDIDATE" and row["route"] is not None:
            add_row(
                tables,
                "CANDIDATE_USES_ROUTE",
                from_iri=assignment_iri,
                to_iri=value(row["route"]),
            )
        if prefix == "CANDIDATE" and row["observation"] is not None:
            add_row(
                tables,
                "CANDIDATE_FROM_OBSERVATION",
                from_iri=assignment_iri,
                to_iri=value(row["observation"]),
            )
        if prefix == "CANDIDATE" and row["resolution"] is not None:
            add_row(
                tables,
                "CANDIDATE_AUTHORIZED_BY_RESOLUTION",
                from_iri=assignment_iri,
                to_iri=value(row["resolution"]),
            )
    for row in query_rows(
        store,
        graph_query(
            graph_iri,
            """
            ?binding a rkaf:EvidenceBinding ; rkaf:bindsAssertion ?assignment ;
                rkaf:bindsSourceFragment ?fragment .
            ?assignment a rkaf:ConceptAssignment .
            """,
        ),
        "binding",
        "assignment",
        "fragment",
    ):
        add_row(
            tables,
            f"{prefix}_EVIDENCED_BY",
            from_iri=value(row["assignment"]),
            to_iri=value(row["fragment"]),
            binding_iri=value(row["binding"]),
        )


def extract_analysis(
    store: Store,
    asserted: str,
    analysis: str,
    tables: dict[str, TableSpec],
) -> None:
    extract_assignments(
        store,
        analysis,
        tables,
        "CandidateAssignment",
        "CANDIDATE",
    )
    extract_assignments(
        store,
        asserted,
        tables,
        "AcceptedAssignment",
        "ACCEPTED",
    )

    for row in query_rows(
        store,
        graph_query(
            analysis,
            """
            ?iri a va:ConceptMappingCandidate ; va:sourceConcept ?source ;
                va:targetConcept ?target ; va:proposedRelation ?relation ;
                va:generationMethod ?method ; va:reviewStatus ?status .
            OPTIONAL { ?iri va:normalizedLabel ?normalized . }
            OPTIONAL { ?iri va:sourceLabel ?source_label . }
            OPTIONAL { ?iri va:targetLabel ?target_label . }
            """,
        ),
        "iri",
        "source",
        "target",
        "relation",
        "method",
        "status",
        "normalized",
        "source_label",
        "target_label",
    ):
        mapping_iri = value(row["iri"])
        add_row(
            tables,
            "ConceptMappingCandidate",
            iri=mapping_iri,
            proposed_relation_iri=value(row["relation"]),
            generation_method_iri=value(row["method"]),
            normalized_label=value(row["normalized"]),
            source_label=value(row["source_label"]),
            target_label=value(row["target_label"]),
            review_status_iri=value(row["status"]),
        )
        add_row(
            tables,
            "MAPPING_CANDIDATE_FROM",
            from_iri=mapping_iri,
            to_iri=value(row["source"]),
        )
        add_row(
            tables,
            "MAPPING_CANDIDATE_TO",
            from_iri=mapping_iri,
            to_iri=value(row["target"]),
        )

    for row in query_rows(
        store,
        graph_query(
            asserted,
            """
            ?iri a rkaf:ConceptMapping ; rkaf:assertsSubject ?source ;
                rkaf:assertsObject ?target ; rkaf:assertsPredicate ?relation ;
                va:reviewStatus ?status ; rkaf:assertionOrigin ?origin ;
                rkaf:epistemicBasis ?basis ; rkaf:usageEligibility ?eligibility ;
                rkaf:assertionPolarity ?polarity .
            """,
        ),
        "iri",
        "source",
        "target",
        "relation",
        "status",
        "origin",
        "basis",
        "eligibility",
        "polarity",
    ):
        mapping_iri = value(row["iri"])
        add_row(
            tables,
            "ReviewedConceptMapping",
            iri=mapping_iri,
            relation_iri=value(row["relation"]),
            review_status_iri=value(row["status"]),
            origin_iri=value(row["origin"]),
            basis_iri=value(row["basis"]),
            eligibility_iri=value(row["eligibility"]),
            polarity_iri=value(row["polarity"]),
        )
        add_row(
            tables,
            "REVIEWED_MAPPING_FROM",
            from_iri=mapping_iri,
            to_iri=value(row["source"]),
        )
        add_row(
            tables,
            "REVIEWED_MAPPING_TO",
            from_iri=mapping_iri,
            to_iri=value(row["target"]),
        )

    for row in query_rows(
        store,
        graph_query(
            analysis,
            """
            ?iri a va:ObservationConceptCandidate ; va:sourceObservation ?observation ;
                va:targetConcept ?concept ; va:targetExpression ?expression ;
                va:candidateRoute ?route ; va:semanticFacet ?facet ;
                va:assignmentRole ?role ; va:normalizedLabel ?normalized ;
                va:generationMethod ?method ; va:reviewStatus ?status .
            """,
        ),
        "iri",
        "observation",
        "concept",
        "expression",
        "route",
        "facet",
        "role",
        "normalized",
        "method",
        "status",
    ):
        candidate_iri = value(row["iri"])
        add_row(
            tables,
            "ObservationConceptCandidate",
            iri=candidate_iri,
            facet_iri=value(row["facet"]),
            role_iri=value(row["role"]),
            normalized_label=value(row["normalized"]),
            generation_method_iri=value(row["method"]),
            review_status_iri=value(row["status"]),
        )
        for edge, target in (
            ("OBSERVATION_CANDIDATE_FROM", row["observation"]),
            ("OBSERVATION_CANDIDATE_TO", row["concept"]),
            ("MATCHED_EXPRESSION", row["expression"]),
            ("OBSERVATION_CANDIDATE_USES_ROUTE", row["route"]),
        ):
            add_row(
                tables,
                edge,
                from_iri=candidate_iri,
                to_iri=value(target),
            )

    policy_kinds: dict[str, set[str]] = defaultdict(set)
    for row in query_rows(
        store,
        graph_query(
            analysis,
            "?policy a va:RelatednessCandidatePolicy ; va:sourceTopicObservationKind ?kind .",
        ),
        "policy",
        "kind",
    ):
        policy_kinds[value(row["policy"])].add(value(row["kind"]))
    for row in query_rows(
        store,
        graph_query(
            analysis,
            """
            ?iri a va:RelatednessCandidatePolicy ; va:policyDigest ?digest ;
                va:maxDocumentFrequencyRatio ?max_ratio ;
                va:minimumDocumentPopulation ?minimum_population ;
                va:sourceRelationUse ?source_relation_use ;
                rkaf:usageEligibility ?output_authority .
            """,
        ),
        "iri",
        "digest",
        "max_ratio",
        "minimum_population",
        "source_relation_use",
        "output_authority",
    ):
        policy_iri = value(row["iri"])
        add_row(
            tables,
            "RelatednessPolicy",
            iri=policy_iri,
            policy_digest=value(row["digest"]),
            max_document_frequency_ratio=floating(row["max_ratio"]),
            minimum_document_population=integer(row["minimum_population"]),
            source_topic_observation_kinds_json=json.dumps(sorted(policy_kinds[policy_iri]), separators=(",", ":")),
            source_relation_use_iri=value(row["source_relation_use"]),
            output_authority_iri=value(row["output_authority"]),
        )
    for row in query_rows(
        store,
        graph_query(
            analysis,
            """
            ?policy a va:RelatednessCandidatePolicy ; va:topicalDimension ?dimension .
            ?dimension a va:RelatednessTopicalDimension ; va:semanticFacet ?facet ;
                va:assignmentRole ?role .
            """,
        ),
        "policy",
        "dimension",
        "facet",
        "role",
    ):
        dimension_iri = value(row["dimension"])
        add_row(
            tables,
            "RelatednessDimension",
            iri=dimension_iri,
            facet_iri=value(row["facet"]),
            role_iri=value(row["role"]),
        )
        add_row(
            tables,
            "POLICY_ALLOWS_DIMENSION",
            from_iri=value(row["policy"]),
            to_iri=dimension_iri,
        )


def canonical_sort_key(row: dict[str, Any], columns: tuple[tuple[str, pa.DataType], ...]) -> tuple[str, ...]:
    return tuple("" if row[name] is None else str(row[name]) for name, _ in columns)


def validate_projection(
    tables: dict[str, TableSpec],
    manifest: dict[str, Any],
) -> None:
    unknown_classifications = (ANALYSIS_TABLES | DERIVED_INDEX_TABLES) - set(tables)
    if unknown_classifications:
        raise ValueError(f"authority classification names unknown tables: {sorted(unknown_classifications)}")
    expected_counts = {
        "ManagedRelease": manifest["counts"]["managedReleases"],
        "ConceptScheme": manifest["counts"]["conceptSchemes"],
        "Concept": manifest["counts"]["concepts"],
        "VocabularyExpression": manifest["counts"]["indexedExpressions"],
        "CandidateRoute": manifest["counts"]["candidateRoutes"],
        "Document": manifest["counts"]["artifacts"],
        "SourceControlObservation": manifest["counts"]["sourceControls"],
        "SourceTermObservation": manifest["counts"]["sourceObservations"],
        "SourceTermResolution": manifest["counts"]["sourceTermResolutions"],
        "CandidateAssignment": manifest["counts"]["assignmentCandidates"],
        "AcceptedAssignment": manifest["counts"]["acceptedAssignments"],
        "ObservationConceptCandidate": manifest["counts"]["observationConceptCandidates"],
        "ConceptMappingCandidate": manifest["counts"]["mappingCandidates"],
        "ReviewedConceptMapping": manifest["counts"]["reviewedMappings"],
        "EXPLICIT_LINK": manifest["counts"]["relationshipAssertions"],
    }
    for table, expected in expected_counts.items():
        actual = len(tables[table].rows)
        if actual != expected:
            raise ValueError(f"{table}: expected {expected:,} rows, found {actual:,}")

    for spec in tables.values():
        spec.rows.sort(key=lambda row: canonical_sort_key(row, spec.columns))
        if spec.kind == "node":
            ids = [row[spec.columns[0][0]] for row in spec.rows]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{spec.name} contains duplicate primary keys")

    concept_ids = {row["iri"] for row in tables["Concept"].rows}
    for table_name, spec in tables.items():
        if not spec.rows or "concept_identity_claimed" not in spec.rows[0]:
            continue
        if any(row["concept_identity_claimed"] is not False for row in spec.rows):
            raise ValueError(f"{table_name} contains a concept-identity claim")
        overlaps = concept_ids & {row["iri"] for row in spec.rows}
        if overlaps:
            raise ValueError(
                f"{table_name} nodes that disclaim concept identity also appear as managed concepts: {sorted(overlaps)}"
            )
    resolution_concept_overlap = concept_ids & {row["iri"] for row in tables["SourceTermResolution"].rows}
    if resolution_concept_overlap:
        raise ValueError(
            f"source-term resolutions also appear as managed concepts: {sorted(resolution_concept_overlap)}"
        )

    resolution_by_id = {row["iri"]: row for row in tables["SourceTermResolution"].rows}
    resolution_observations: dict[str, list[str]] = defaultdict(list)
    for edge in tables["RESOLUTION_OF"].rows:
        resolution_observations[edge["from_iri"]].append(edge["to_iri"])
    resolution_targets: dict[str, list[str]] = defaultdict(list)
    for edge in tables["RESOLVES_TO"].rows:
        resolution_targets[edge["from_iri"]].append(edge["to_iri"])
    allowed_resolution_statuses = {
        "officialTerm",
        "recognizedVariant",
        "sourceLocalOpenTerm",
        "unresolved",
    }
    resolving_statuses = {"officialTerm", "recognizedVariant"}
    observation_kind = {row["iri"]: row["kind_iri"] for row in tables["SourceTermObservation"].rows}
    for resolution_iri, resolution in resolution_by_id.items():
        status = resolution["status"]
        if status not in allowed_resolution_statuses:
            raise ValueError(f"source-term resolution {resolution_iri} has unknown status {status!r}")
        if resolution["concept_minted"] is not False:
            raise ValueError(f"source-term resolution {resolution_iri} minted a concept")
        observations = resolution_observations[resolution_iri]
        if len(observations) != 1:
            raise ValueError(f"source-term resolution {resolution_iri} has {len(observations)} source observations")
        if observation_kind.get(observations[0]) != LISTS_OF_SUBJECTS:
            raise ValueError(
                f"source-term resolution {resolution_iri} does not resolve a Lists of Subjects observation"
            )
        targets = resolution_targets[resolution_iri]
        expected_target_count = 1 if status in resolving_statuses else 0
        if len(targets) != expected_target_count:
            raise ValueError(
                f"source-term resolution {resolution_iri} with status {status} "
                f"has {len(targets)} targets; expected {expected_target_count}"
            )
        if any(target not in concept_ids for target in targets):
            raise ValueError(f"source-term resolution {resolution_iri} targets an unmanaged concept")
    if any(
        observation_kind.get(row["source_observation_iri"]) == API_TOPIC for row in tables["CandidateAssignment"].rows
    ):
        raise ValueError("an API Topic became a candidate assignment")
    if any(
        row["resolution_iri"] is not None
        and resolution_by_id.get(row["resolution_iri"], {}).get("status") not in resolving_statuses
        for row in tables["CandidateAssignment"].rows
    ):
        raise ValueError("a candidate assignment is authorized by a source-local or unresolved term")
    if {row["iri"] for row in tables["CandidateAssignment"].rows} & {
        row["iri"] for row in tables["AcceptedAssignment"].rows
    }:
        raise ValueError("candidate and accepted assignment tables overlap")
    if {row["iri"] for row in tables["ConceptMappingCandidate"].rows} & {
        row["iri"] for row in tables["ReviewedConceptMapping"].rows
    }:
        raise ValueError("candidate and reviewed mapping tables overlap")
    if tables["AcceptedAssignment"].rows:
        raise ValueError(
            "this bounded spike does not project accepted EnrichmentDecision "
            "records; add that shape before loading a generation with accepted output"
        )


def write_parquet_tables(
    tables: dict[str, TableSpec],
    directory: Path,
) -> dict[str, dict[str, Any]]:
    directory.mkdir(parents=True)
    receipts: dict[str, dict[str, Any]] = {}
    for spec in tables.values():
        path = directory / f"{spec.name}.parquet"
        table = pa.Table.from_pylist(spec.rows, schema=spec.schema)
        pq.write_table(
            table,
            path,
            compression="zstd",
            use_dictionary=False,
            write_statistics=True,
        )
        receipts[spec.name] = {
            "kind": spec.kind,
            "authorityClass": table_authority_class(spec.name),
            "rows": len(spec.rows),
            "path": str(path.name),
            "sha256": sha256_file(path),
            "byteLength": path.stat().st_size,
        }
    return receipts


def copy_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def build_ladybug(
    tables: dict[str, TableSpec],
    parquet_directory: Path,
    database_path: Path,
) -> tuple[float, dict[str, int]]:
    started = time.perf_counter()
    database = ladybug.Database(str(database_path), max_db_size=8 * 1024**3)
    connection = ladybug.Connection(database)
    try:
        for spec in tables.values():
            connection.execute(spec.ddl)
        for spec in tables.values():
            if not spec.rows:
                continue
            path = parquet_directory / f"{spec.name}.parquet"
            connection.execute(f"COPY {spec.name} FROM '{copy_path(path)}'")
        counts = {}
        for spec in tables.values():
            if spec.kind == "node":
                query = f"MATCH (n:{spec.name}) RETURN count(n)"
            else:
                query = f"MATCH ()-[r:{spec.name}]->() RETURN count(r)"
            counts[spec.name] = connection.execute(query).get_all()[0][0]
            if counts[spec.name] != len(spec.rows):
                raise ValueError(f"Ladybug count mismatch for {spec.name}: {counts[spec.name]} != {len(spec.rows)}")
    finally:
        connection.close()
        database.close()
    return (time.perf_counter() - started) * 1000, counts


def ladybug_rows(
    connection: ladybug.Connection,
    query: str,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = connection.execute(query, parameters or {})
    columns = result.get_column_names()
    return [dict(zip(columns, row, strict=True)) for row in result.get_all()]


def timed_ladybug_query(
    connection: ladybug.Connection,
    query: str,
    parameters: dict[str, Any] | None = None,
    repetitions: int = 40,
) -> tuple[list[dict[str, Any]], dict[str, float | int]]:
    expected = ladybug_rows(connection, query, parameters)
    durations: list[float] = []
    for _ in range(repetitions):
        started = time.perf_counter()
        actual = ladybug_rows(connection, query, parameters)
        durations.append((time.perf_counter() - started) * 1000)
        if actual != expected:
            raise ValueError("a repeated Ladybug query returned different rows")
    ordered = sorted(durations)
    p95_index = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)
    return expected, {
        "repetitions": repetitions,
        "medianMs": round(statistics.median(durations), 6),
        "p95Ms": round(ordered[p95_index], 6),
    }


def rdf_values(
    store: Store,
    query: str,
    *names: str,
) -> list[dict[str, Any]]:
    rows = []
    for item in store.query(PREFIXES + query):
        row: dict[str, Any] = {}
        for name in names:
            term = item[name]
            if term is None:
                row[name] = None
            elif (
                isinstance(term, Literal)
                and term.datatype is not None
                and term.datatype.value.endswith(("#integer", "#long", "#int"))
            ):
                row[name] = int(term.value)
            else:
                row[name] = term.value
        rows.append(row)
    return rows


def run_parity_checks(
    store: Store,
    manifest: dict[str, Any],
    database_path: Path,
) -> dict[str, Any]:
    asserted = manifest["graphs"]["atlas"]["id"]
    exact_rdf = rdf_values(
        store,
        f"""
        SELECT DISTINCT ?iri WHERE {{
          GRAPH <{asserted}> {{
            ?agency a va:SourceControlObservation ; va:controlSubject ?iri ;
                va:controlKind <{FR_AGENCY}> ; va:semanticFacet <urn:ref:facet:entity> ;
                va:controlValue <https://www.federalregister.gov/agencies/food-safety-and-inspection-service> .
            ?document_type a va:SourceControlObservation ; va:controlSubject ?iri ;
                va:controlKind <{FR_DOCUMENT_TYPE}> ; va:semanticFacet <urn:ref:facet:genre> ;
                va:controlValue "Proposed Rule" .
            ?cfr a va:SourceControlObservation ; va:controlSubject ?iri ;
                va:controlKind <{FR_CFR_REFERENCE}> ;
                va:semanticFacet <urn:ref:facet:legal-location> ;
                va:controlValue <urn:rkaf:us:cfr:9:381> .
          }}
        }} ORDER BY ?iri
        """,
        "iri",
    )
    topic_rdf = rdf_values(
        store,
        f"""
        SELECT DISTINCT ?iri WHERE {{
          GRAPH <{asserted}> {{
            ?observation a va:SourceTermObservation ; va:observationKind <{API_TOPIC}> ;
                va:observedOn ?iri .
            ?label_record a va:SourceObservationLabelRecord ;
                va:observation ?observation ; va:normalizedLabel "meat inspection" .
          }}
        }} ORDER BY ?iri
        """,
        "iri",
    )
    lists_rdf = rdf_values(
        store,
        f"""
        SELECT ?status (COUNT(DISTINCT ?resolution) AS ?count) WHERE {{
          GRAPH <{asserted}> {{
            ?resolution a va:SourceTermResolution ; va:sourceObservation ?observation ;
                va:resolutionStatus ?status .
            ?observation va:observationKind <{LISTS_OF_SUBJECTS}> .
          }}
        }} GROUP BY ?status ORDER BY ?status
        """,
        "status",
        "count",
    )
    explicit_rdf = rdf_values(
        store,
        f"""
        SELECT ?assertion ?predicate ?target_iri WHERE {{
          GRAPH <{asserted}> {{
            ?assertion a rkaf:RelationshipAssertion ;
                rkaf:assertsSubject <https://www.federalregister.gov/d/2026-03227> ;
                rkaf:assertsPredicate ?predicate ; rkaf:assertsObject ?target_iri .
          }}
        }} ORDER BY ?target_iri
        """,
        "assertion",
        "predicate",
        "target_iri",
    )

    database = ladybug.Database(str(database_path), read_only=True, max_db_size=8 * 1024**3)
    connection = ladybug.Connection(database)
    try:
        exact_query = """
        MATCH (agency:SourceControlObservation)-[:CONTROL_ON]->(document:Document),
              (documentType:SourceControlObservation)-[:CONTROL_ON]->(document),
              (cfr:SourceControlObservation)-[:CONTROL_ON]->(document)
        WHERE agency.kind_iri=$agencyKind
          AND agency.facet_iri='urn:ref:facet:entity'
          AND agency.value_term_kind='iri'
          AND agency.value_lexical=$agency
          AND documentType.kind_iri=$documentTypeKind
          AND documentType.facet_iri='urn:ref:facet:genre'
          AND documentType.value_term_kind='literal'
          AND documentType.value_lexical='Proposed Rule'
          AND cfr.kind_iri=$cfrKind
          AND cfr.facet_iri='urn:ref:facet:legal-location'
          AND cfr.value_term_kind='iri'
          AND cfr.value_lexical='urn:rkaf:us:cfr:9:381'
        RETURN DISTINCT document.iri AS iri ORDER BY iri
        """
        exact_parameters = {
            "agencyKind": FR_AGENCY,
            "agency": "https://www.federalregister.gov/agencies/food-safety-and-inspection-service",
            "documentTypeKind": FR_DOCUMENT_TYPE,
            "cfrKind": FR_CFR_REFERENCE,
        }
        exact_rows, exact_timing = timed_ladybug_query(connection, exact_query, exact_parameters)

        topic_query = """
        MATCH (observation:SourceTermObservation)-[:TERM_ON]->(document:Document)
        WHERE observation.kind_iri=$kind AND observation.normalized_label=$label
        RETURN DISTINCT document.iri AS iri ORDER BY iri
        """
        topic_rows, topic_timing = timed_ladybug_query(
            connection,
            topic_query,
            {"kind": API_TOPIC, "label": "meat inspection"},
        )
        lists_rows = ladybug_rows(
            connection,
            """
            MATCH (resolution:SourceTermResolution)-[:RESOLUTION_OF]->(observation:SourceTermObservation)
            WHERE observation.kind_iri=$kind
            RETURN resolution.status AS status, count(DISTINCT resolution) AS count
            ORDER BY status
            """,
            {"kind": LISTS_OF_SUBJECTS},
        )
        explicit_rows, explicit_timing = timed_ladybug_query(
            connection,
            """
            MATCH (source:Document {iri:$source})-[link:EXPLICIT_LINK]->(target:Document)
            RETURN link.assertion_iri AS assertion, link.predicate_iri AS predicate,
                   target.iri AS target_iri ORDER BY target_iri
            """,
            {"source": "https://www.federalregister.gov/d/2026-03227"},
        )

        frequency_rows, _frequency_timing = timed_ladybug_query(
            connection,
            """
            MATCH (observation:SourceTermObservation)-[:TERM_ON]->(document:Document)
            WHERE observation.kind_iri=$kind
              AND observation.normalized_label IN ['meat inspection',
                  'reporting and recordkeeping requirements']
            WITH observation.normalized_label AS label,
                 count(DISTINCT document) AS document_count
            MATCH (populationObservation:SourceTermObservation)-[:TERM_ON]->(populationDocument:Document)
            WHERE populationObservation.kind_iri=$kind
            WITH label, document_count, count(DISTINCT populationDocument) AS population
            MATCH (policy:RelatednessPolicy)
            RETURN label, document_count, population,
                   1.0*document_count/population AS ratio,
                   population>=policy.minimum_document_population AND
                     1.0*document_count/population>policy.max_document_frequency_ratio AS suppressed
            ORDER BY label
            """,
            {"kind": API_TOPIC},
        )

        relatedness_query = """
        MATCH (sourceObservation:SourceTermObservation)-[:TERM_ON]->(source:Document),
              (targetObservation:SourceTermObservation)-[:TERM_ON]->(target:Document)
        WHERE source.iri=$source AND target.iri<>source.iri
          AND sourceObservation.kind_iri=$kind
          AND targetObservation.kind_iri=sourceObservation.kind_iri
          AND sourceObservation.normalized_label=$label
          AND targetObservation.normalized_label=sourceObservation.normalized_label
        WITH DISTINCT source,target,sourceObservation.kind_iri AS kind,
             sourceObservation.normalized_label AS label
        MATCH (frequencyObservation:SourceTermObservation)-[:TERM_ON]->(frequencyDocument:Document)
        WHERE frequencyObservation.kind_iri=kind
          AND frequencyObservation.normalized_label=label
        WITH source,target,kind,label,count(DISTINCT frequencyDocument) AS document_count
        MATCH (populationObservation:SourceTermObservation)-[:TERM_ON]->(populationDocument:Document)
        WHERE populationObservation.kind_iri=kind
        WITH source,target,label,document_count,count(DISTINCT populationDocument) AS population
        MATCH (policy:RelatednessPolicy)
        WHERE NOT (population>=policy.minimum_document_population AND
                   1.0*document_count/population>policy.max_document_frequency_ratio)
        RETURN target.iri AS target_iri,label,document_count,population,
               1.0*document_count/population AS ratio ORDER BY target_iri
        """
        meat_candidates = ladybug_rows(
            connection,
            relatedness_query,
            {
                "source": "https://www.federalregister.gov/d/2026-03227",
                "kind": API_TOPIC,
                "label": "meat inspection",
            },
        )
        reporting_candidates = ladybug_rows(
            connection,
            relatedness_query,
            {
                "source": "https://www.federalregister.gov/d/2025-16409",
                "kind": API_TOPIC,
                "label": "reporting and recordkeeping requirements",
            },
        )

        statistics_cluster, cluster_timing = timed_ladybug_query(
            connection,
            """
            MATCH (key:LabelKey)<-[:EXPRESSION_KEY]-(expression:VocabularyExpression)
                  -[:EXPRESSION_OF]->(concept:Concept)-[:MEMBER_OF_RELEASE]->(release:ManagedRelease)
            WHERE key.normalized_label='statistics'
              AND expression.semantic_property_iri=$prefLabel
            RETURN DISTINCT release.iri AS release_iri, concept.iri AS concept_iri,
                   concept.label AS label ORDER BY release_iri,concept_iri
            """,
            {"prefLabel": f"{SKOS}prefLabel"},
        )
        federal_register_policy = ladybug_rows(
            connection,
            """
            MATCH (release:ManagedRelease {iri:$release})
            RETURN release.source_priority_policy AS source_priority_policy,
                   release.candidate_lookup_allowed AS candidate_lookup_allowed,
                   release.accepted_output_allowed AS accepted_output_allowed,
                   release.root_ontology AS root_ontology
            """,
            {"release": FR_2025_RELEASE},
        )
        expected_federal_register_policy = [
            {
                "source_priority_policy": "strongSourceNative",
                "candidate_lookup_allowed": True,
                "accepted_output_allowed": False,
                "root_ontology": False,
            }
        ]
        if federal_register_policy != expected_federal_register_policy:
            raise ValueError(f"Federal Register candidate policy differs: {federal_register_policy}")
        federal_register_statistics_order = ladybug_rows(
            connection,
            """
            MATCH (key:LabelKey)<-[:EXPRESSION_KEY]-(expression:VocabularyExpression)
                  -[:EXPRESSION_OF]->(concept:Concept)-[:MEMBER_OF_RELEASE]->(release:ManagedRelease)
            WHERE key.normalized_label='statistics'
              AND expression.semantic_property_iri=$prefLabel
            RETURN DISTINCT release.iri AS release_iri,concept.iri AS concept_iri,
                   concept.label AS label,
                   CASE WHEN release.source_priority_policy='strongSourceNative'
                        THEN 0 ELSE 1 END AS federal_register_priority_tier
            ORDER BY federal_register_priority_tier,release_iri,concept_iri
            """,
            {"prefLabel": f"{SKOS}prefLabel"},
        )
        if (
            not federal_register_statistics_order
            or federal_register_statistics_order[0]["release_iri"] != FR_2025_RELEASE
            or {row["release_iri"] for row in federal_register_statistics_order}
            != {row["release_iri"] for row in statistics_cluster}
        ):
            raise ValueError("Federal Register priority did not preserve and reorder the full lexical cluster")

        civil_rights = ladybug_rows(
            connection,
            """
            MATCH (key:LabelKey)<-[:EXPRESSION_KEY]-(expression:VocabularyExpression)
                  -[:EXPRESSION_OF]->(concept:Concept)-[:MEMBER_OF_RELEASE]->(release:ManagedRelease)
            WHERE key.normalized_label='civil rights'
              AND expression.semantic_property_iri=$prefLabel
            RETURN DISTINCT concept.iri AS concept_iri,concept.label AS label,
                   release.iri AS release_iri ORDER BY release_iri,concept_iri
            """,
            {"prefLabel": f"{SKOS}prefLabel"},
        )
        hierarchies = []
        for concept in civil_rights:
            ancestor_paths, _ = timed_ladybug_query(
                connection,
                """
                MATCH (leaf:Concept)-[edges:BROADER* ACYCLIC 1..30]->(ancestor:Concept)
                WHERE leaf.iri=$concept
                RETURN DISTINCT ancestor.iri AS ancestor_iri,ancestor.label AS label,
                       length(edges) AS hops ORDER BY hops,ancestor_iri
                """,
                {"concept": concept["concept_iri"]},
                repetitions=10,
            )
            ancestor_by_iri: dict[str, dict[str, Any]] = {}
            for ancestor in ancestor_paths:
                current = ancestor_by_iri.get(ancestor["ancestor_iri"])
                if current is None or ancestor["hops"] < current["hops"]:
                    ancestor_by_iri[ancestor["ancestor_iri"]] = ancestor
            ancestors = sorted(
                ancestor_by_iri.values(),
                key=lambda row: (row["hops"], row["ancestor_iri"]),
            )
            rdf_ancestors = rdf_values(
                store,
                f"""
                SELECT DISTINCT ?ancestor_iri WHERE {{
                  GRAPH <{asserted}> {{ <{concept["concept_iri"]}> skos:broader+ ?ancestor_iri . }}
                }} ORDER BY ?ancestor_iri
                """,
                "ancestor_iri",
            )
            ladybug_ancestor_ids = {row["ancestor_iri"] for row in ancestors}
            rdf_ancestor_ids = {row["ancestor_iri"] for row in rdf_ancestors}
            if ladybug_ancestor_ids != rdf_ancestor_ids:
                raise ValueError(
                    f"hierarchy parity failed for {concept['concept_iri']}; "
                    f"missing={sorted(rdf_ancestor_ids - ladybug_ancestor_ids)}; "
                    f"extra={sorted(ladybug_ancestor_ids - rdf_ancestor_ids)}"
                )
            hierarchies.append({**concept, "ancestors": ancestors})

        path_probe_concept = "https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001/terms/24602"
        acyclic_pattern_rows = ladybug_rows(
            connection,
            """
            MATCH (leaf:Concept)-[edges:BROADER* ACYCLIC 1..3]->(ancestor:Concept)
            WHERE leaf.iri=$concept
            RETURN ancestor.iri AS ancestor_iri,length(edges) AS hops
            ORDER BY hops,ancestor_iri
            """,
            {"concept": path_probe_concept},
        )
        is_acyclic_filter_rows = ladybug_rows(
            connection,
            """
            MATCH path=(leaf:Concept)-[edges:BROADER*1..3]->(ancestor:Concept)
            WHERE leaf.iri=$concept AND is_acyclic(path)
            RETURN ancestor.iri AS ancestor_iri,length(edges) AS hops
            ORDER BY hops,ancestor_iri
            """,
            {"concept": path_probe_concept},
        )

        protection_queries = {
            "apiTopicCount": (
                "MATCH (o:SourceTermObservation) WHERE o.kind_iri=$api RETURN count(o) AS count",
                {"api": API_TOPIC},
            ),
            "apiTopicResolutionCount": (
                (
                    "MATCH (:SourceTermResolution)-[:RESOLUTION_OF]->(o:SourceTermObservation) "
                    "WHERE o.kind_iri=$api RETURN count(o) AS count"
                ),
                {"api": API_TOPIC},
            ),
            "apiTopicCandidateAssignmentCount": (
                (
                    "MATCH (:CandidateAssignment)-[:CANDIDATE_FROM_OBSERVATION]->(o:SourceTermObservation) "
                    "WHERE o.kind_iri=$api RETURN count(o) AS count"
                ),
                {"api": API_TOPIC},
            ),
            "listsWithoutOneResolution": (
                (
                    "MATCH (o:SourceTermObservation) WHERE o.kind_iri=$lists "
                    "OPTIONAL MATCH (r:SourceTermResolution)-[:RESOLUTION_OF]->(o) "
                    "WITH o,count(r) AS n WHERE n<>1 RETURN count(o) AS count"
                ),
                {"lists": LISTS_OF_SUBJECTS},
            ),
            "mintedResolutionCount": (
                "MATCH (r:SourceTermResolution) WHERE r.concept_minted<>false RETURN count(r) AS count",
                {},
            ),
            "sourceLocalAssignmentCount": (
                (
                    "MATCH (:CandidateAssignment)-[:CANDIDATE_AUTHORIZED_BY_RESOLUTION]->(r:SourceTermResolution) "
                    "WHERE r.status='sourceLocalOpenTerm' RETURN count(r) AS count"
                ),
                {},
            ),
            "acceptedAssignmentCount": (
                "MATCH (a:AcceptedAssignment) RETURN count(a) AS count",
                {},
            ),
            "candidateAssignmentCount": (
                "MATCH (a:CandidateAssignment) RETURN count(a) AS count",
                {},
            ),
            "nonFederalRegisterCandidateAssignmentCount": (
                (
                    "MATCH (:CandidateAssignment)-[:CANDIDATE_ASSIGNED_RELEASE]->(r:ManagedRelease) "
                    "WHERE r.iri<>$release RETURN count(r) AS count"
                ),
                {"release": FR_2025_RELEASE},
            ),
            "assignmentIdentityOverlap": (
                "MATCH (a:AcceptedAssignment),(c:CandidateAssignment) WHERE a.iri=c.iri RETURN count(a) AS count",
                {},
            ),
            "reviewedMappingCount": (
                "MATCH (m:ReviewedConceptMapping) RETURN count(m) AS count",
                {},
            ),
            "mappingCandidateCount": (
                "MATCH (m:ConceptMappingCandidate) RETURN count(m) AS count",
                {},
            ),
            "mappingCandidateAuthorityViolations": (
                (
                    "MATCH (m:ConceptMappingCandidate) "
                    "WHERE m.review_status_iri<>$unresolved OR "
                    "m.proposed_relation_iri<>$undetermined RETURN count(m) AS count"
                ),
                {"unresolved": UNRESOLVED, "undetermined": UNDETERMINED_MAPPING},
            ),
            "mappingIdentityOverlap": (
                (
                    "MATCH (r:ReviewedConceptMapping),(c:ConceptMappingCandidate) "
                    "WHERE r.iri=c.iri RETURN count(r) AS count"
                ),
                {},
            ),
            "explicitLinkCount": (
                "MATCH ()-[link:EXPLICIT_LINK]->() RETURN count(link) AS count",
                {},
            ),
        }
        protections = {
            name: ladybug_rows(connection, query, parameters)[0]["count"]
            for name, (query, parameters) in protection_queries.items()
        }

        try:
            connection.execute("CREATE (:Document {iri:'urn:should-not-write'})")
        except RuntimeError as error:
            read_only = {"writeRejected": True, "errorType": type(error).__name__}
        else:
            raise ValueError("the read-only Ladybug connection accepted a write")
    finally:
        connection.close()
        database.close()

    parity = {
        "exactSourceControls": {
            "rdf": exact_rdf,
            "ladybug": exact_rows,
            "equal": exact_rdf == exact_rows,
            "timing": exact_timing,
        },
        "mutableApiTopic": {
            "rdf": topic_rdf,
            "ladybug": topic_rows,
            "equal": topic_rdf == topic_rows,
            "timing": topic_timing,
        },
        "listsResolutions": {
            "rdf": lists_rdf,
            "ladybug": lists_rows,
            "equal": lists_rdf == lists_rows,
        },
        "explicitLink": {
            "rdf": explicit_rdf,
            "ladybug": explicit_rows,
            "equal": explicit_rdf == explicit_rows,
            "timing": explicit_timing,
        },
    }
    failed = [name for name, result in parity.items() if not result["equal"]]
    if failed:
        raise ValueError(f"RDF/Ladybug result parity failed: {', '.join(failed)}")
    expected_protections = {
        "apiTopicCount": 107,
        "apiTopicResolutionCount": 0,
        "apiTopicCandidateAssignmentCount": 0,
        "listsWithoutOneResolution": 0,
        "mintedResolutionCount": 0,
        "sourceLocalAssignmentCount": 0,
        "acceptedAssignmentCount": 0,
        "candidateAssignmentCount": 26,
        "nonFederalRegisterCandidateAssignmentCount": 0,
        "assignmentIdentityOverlap": 0,
        "reviewedMappingCount": 0,
        "mappingCandidateCount": 1151,
        "mappingCandidateAuthorityViolations": 0,
        "mappingIdentityOverlap": 0,
        "explicitLinkCount": 24,
    }
    if protections != expected_protections:
        raise ValueError(
            "authority protections differ: " + json.dumps({"actual": protections, "expected": expected_protections})
        )
    if [row["suppressed"] for row in frequency_rows] != [False, True]:
        raise ValueError(f"unexpected frequency suppression: {frequency_rows}")
    if [row["target_iri"] for row in meat_candidates] != ["https://www.federalregister.gov/d/2026-03228"]:
        raise ValueError(f"unexpected meat-inspection candidates: {meat_candidates}")
    if reporting_candidates:
        raise ValueError(f"generic reporting term was not suppressed: {reporting_candidates}")
    return {
        "parity": parity,
        "authorityProtections": protections,
        "frequencyGate": frequency_rows,
        "candidateRelatedness": {
            "meatInspection": meat_candidates,
            "genericReporting": reporting_candidates,
        },
        "lexicalCluster": {
            "normalizedLabel": "statistics",
            "rows": statistics_cluster,
            "timing": cluster_timing,
        },
        "federalRegisterCandidatePolicy": {
            "release": FR_2025_RELEASE,
            "policy": federal_register_policy[0],
            "statisticsOrder": federal_register_statistics_order,
            "appliesOnlyTo": "Federal Register document candidate lookup",
        },
        "civilRightsHierarchies": hierarchies,
        "recursivePathSemantics": {
            "probeConcept": path_probe_concept,
            "acyclicPatternRows": acyclic_pattern_rows,
            "isAcyclicFilterRows": is_acyclic_filter_rows,
            "sameResult": acyclic_pattern_rows == is_acyclic_filter_rows,
            "requiredForm": "BROADER* ACYCLIC 1..N",
        },
        "readOnly": read_only,
    }


def directory_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--atlas-manifest",
        type=Path,
        default=Path("output/vocabulary-atlas/v5-audited/atlas-manifest.json"),
    )
    parser.add_argument(
        "--atlas-manifest-sha256",
        required=True,
        help="required sha256:<hex> pin for the exact atlas manifest",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("output/vocabulary-atlas/ladybug-spike-v1"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.atlas_manifest.resolve()
    output_directory = args.output_directory.resolve()
    if output_directory.exists():
        raise ValueError(f"refusing to replace an existing spike output: {output_directory}")
    if ladybug.__version__ != "0.19.0":
        raise ValueError(f"this evidence run is pinned to ladybug 0.19.0, found {ladybug.__version__}")
    if pyoxigraph.__version__ != "0.5.9":
        raise ValueError(f"this evidence run is pinned to pyoxigraph 0.5.9, found {pyoxigraph.__version__}")
    if pa.__version__ != "23.0.0":
        raise ValueError(f"this evidence run is pinned to pyarrow 23.0.0, found {pa.__version__}")

    actual_manifest_digest = sha256_file(manifest_path)
    if actual_manifest_digest != args.atlas_manifest_sha256:
        raise ValueError(f"atlas manifest digest mismatch: {actual_manifest_digest} != {args.atlas_manifest_sha256}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    nquads_path = (manifest_path.parent / manifest["output"]["path"]).resolve()
    actual_nquads_digest = sha256_file(nquads_path)
    if actual_nquads_digest != manifest["output"]["sha256"]:
        raise ValueError(f"N-Quads digest mismatch: {actual_nquads_digest} != {manifest['output']['sha256']}")
    if nquads_path.stat().st_size != manifest["output"]["byteLength"]:
        raise ValueError("N-Quads byte length differs from the atlas manifest")

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ladybug-rdf-store-") as rdf_store_directory:
        store = Store(rdf_store_directory)
        rdf_started = time.perf_counter()
        store.bulk_load(path=str(nquads_path), format=RdfFormat.N_QUADS)
        rdf_load_ms = (time.perf_counter() - rdf_started) * 1000
        graph_counts = {}
        for role in ("atlas", "analysis"):
            graph_iri = manifest["graphs"][role]["id"]
            result = next(
                iter(store.query(f"SELECT (COUNT(*) AS ?count) WHERE {{ GRAPH <{graph_iri}> {{ ?s ?p ?o }} }}"))
            )
            graph_counts[role] = int(result["count"].value)
            if graph_counts[role] != manifest["graphs"][role]["tripleCount"]:
                raise ValueError(
                    f"{role} graph count differs: {graph_counts[role]} != {manifest['graphs'][role]['tripleCount']}"
                )

        projection_started = time.perf_counter()
        tables = make_tables()
        extract_projection(store, manifest, tables)
        validate_projection(tables, manifest)
        extraction_ms = (time.perf_counter() - projection_started) * 1000

        with tempfile.TemporaryDirectory(
            prefix=f".{output_directory.name}-",
            dir=output_directory.parent,
        ) as staging_value:
            staging = Path(staging_value)
            parquet_directory = staging / "tables"
            parquet_started = time.perf_counter()
            table_receipts = write_parquet_tables(tables, parquet_directory)
            parquet_ms = (time.perf_counter() - parquet_started) * 1000
            database_path = staging / "atlas.lbug"
            database_build_ms, database_counts = build_ladybug(tables, parquet_directory, database_path)
            checks = run_parity_checks(store, manifest, database_path)

            projection_manifest = {
                "schemaVersion": "ladybug-vocabulary-atlas-projection/v1",
                "status": "disposable-read-model",
                "canonicalAuthority": {
                    "atlasManifest": str(args.atlas_manifest),
                    "atlasManifestSha256": actual_manifest_digest,
                    "nquads": manifest["output"],
                    "generationDigest": manifest["generationDigest"],
                    "graphs": manifest["graphs"],
                },
                "runtime": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "ladybug": ladybug.__version__,
                    "pyoxigraph": pyoxigraph.__version__,
                    "pyarrow": pa.__version__,
                },
                "tables": table_receipts,
                "database": {
                    "path": database_path.name,
                    "byteLength": directory_size(database_path),
                    "readOnlyReopenVerified": True,
                    "maxDbSizeBytes": 8 * 1024**3,
                },
                "timing": {
                    "rdfLoadMs": round(rdf_load_ms, 3),
                    "rdfExtractionMs": round(extraction_ms, 3),
                    "parquetWriteMs": round(parquet_ms, 3),
                    "ladybugSchemaAndCopyMs": round(database_build_ms, 3),
                },
                "projectionRules": {
                    "authorityByTableType": True,
                    "authorityClassRecordedPerTable": True,
                    "oneDatabasePerAtlasGeneration": True,
                    "rowLevelGraphIriOmitted": True,
                    "sourceObservationLabelFlattened": True,
                    "labelKeyClaimsConceptIdentity": False,
                    "labelKeyInput": "normalized prefLabel, altLabel, hiddenLabel, or exact source label only",
                    "inferenceEnabled": False,
                    "candidateRelatednessMaterialized": False,
                },
                "notProjected": [
                    "raw sourceRecord JSON literals",
                    "input-pin nodes already sealed by the atlas manifest",
                    "mapping review clusters",
                    "suggested open-term pattern records",
                    "document-corpus snapshot metadata",
                    "accepted EnrichmentDecision records (the current atlas count is zero)",
                    "RDF triples not needed by the demonstrated serving queries",
                ],
            }
            results = {
                "status": "pass-with-path-query-caveat",
                "atlasGenerationDigest": manifest["generationDigest"],
                "rdfGraphCounts": graph_counts,
                "ladybugTableCounts": database_counts,
                **checks,
            }
            write_json(staging / "projection-manifest.json", projection_manifest)
            write_json(staging / "spike-results.json", results)
            staging.rename(output_directory)

    print(
        json.dumps(
            {
                "status": "pass-with-path-query-caveat",
                "outputDirectory": str(output_directory),
                "generationDigest": manifest["generationDigest"],
                "nodeTables": sum(1 for spec in tables.values() if spec.kind == "node"),
                "relationshipTables": sum(1 for spec in tables.values() if spec.kind == "relationship"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
