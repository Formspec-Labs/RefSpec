"""Build the sealed Atlas 3.0 conformance corpus deterministically."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import validate as atlas_validate
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, SKOS, XSD

ATLAS = atlas_validate.ATLAS
SKOSXL = atlas_validate.SKOSXL
FIXTURE_ROOT = atlas_validate.FIXTURE_ROOT
GENERATED_ROOTS = (FIXTURE_ROOT / "valid", FIXTURE_ROOT / "invalid")
SOURCE_RELEASE = URIRef("urn:ref:atlas-fixture:source-release:2026")
REVIEWER = URIRef("urn:ref:agent:atlas-fixture-reviewer")
CREATED_AT = "2026-08-05T12:00:00+00:00"


@dataclass(slots=True)
class Fixture:
    asserted: Graph
    projection: Graph
    derived: Graph
    accounting: dict[str, Any]
    acceptance: dict[str, Any]
    manifest_patch: dict[str, Any]
    omitted_gate: str | None = None
    post_write: Callable[[Path], None] | None = None


def _add_release(
    graph: Graph,
    *,
    name: str,
    profile: URIRef,
    ring: URIRef,
    resources: list[tuple[str, URIRef, str]],
    scheme: URIRef | None = None,
) -> tuple[URIRef, URIRef, list[tuple[URIRef, URIRef]]]:
    scheme = scheme or URIRef(f"urn:ref:atlas-fixture:scheme:{name}")
    release = URIRef(f"urn:ref:atlas-fixture:release:{name}:2026")
    graph.add((scheme, RDF.type, ATLAS.ResourceScheme))
    if profile == ATLAS.conceptScheme or any(
        resource_type == ATLAS.SubjectConcept for _, resource_type, _ in resources
    ):
        graph.add((scheme, RDF.type, SKOS.ConceptScheme))
    graph.add((scheme, ATLAS.resourceProfile, profile))
    graph.add((scheme, ATLAS.supportedRing, ring))
    graph.add((release, RDF.type, ATLAS.AtlasRelease))
    graph.add((release, ATLAS.resourceProfile, profile))
    graph.add((release, ATLAS.semanticRing, ring))
    graph.add((release, ATLAS.inScheme, scheme))
    graph.add((release, ATLAS.membershipMode, ATLAS.completeMembership))
    graph.add((release, DCTERMS.identifier, Literal(name)))
    graph.add((release, DCTERMS.issued, Literal("2026-08-05", datatype=XSD.date)))

    result: list[tuple[URIRef, URIRef]] = []
    for local_name, resource_type, label_text in resources:
        resource = URIRef(f"urn:ref:atlas-fixture:resource:{local_name}")
        source_record = URIRef(f"urn:ref:atlas-fixture:source-record:{local_name}")
        label = URIRef(f"urn:ref:atlas-fixture:label:{local_name}:en")
        graph.add((resource, RDF.type, ATLAS.AtlasResource))
        graph.add((resource, RDF.type, resource_type))
        if resource_type == ATLAS.SubjectConcept:
            graph.add((resource, RDF.type, SKOS.Concept))
            graph.add((resource, SKOS.inScheme, scheme))
        graph.add((resource, ATLAS.inRelease, release))
        graph.add((resource, ATLAS.inScheme, scheme))
        graph.add((resource, ATLAS.semanticRing, ring))
        graph.add((resource, ATLAS.resourceProfile, profile))
        graph.add((resource, ATLAS.sourceRecord, source_record))
        graph.add((release, PROV.hadMember, resource))
        graph.add((resource, SKOSXL.prefLabel, label))

        graph.add((label, RDF.type, SKOSXL.Label))
        graph.add((label, SKOSXL.literalForm, Literal(label_text, lang="en")))
        graph.add((label, ATLAS.inRelease, release))
        graph.add((label, ATLAS.sourceRecord, source_record))

        graph.add((source_record, RDF.type, ATLAS.SourceRecord))
        graph.add((source_record, ATLAS.inSourceRelease, SOURCE_RELEASE))
        graph.add((source_record, ATLAS.representsResource, resource))
        graph.add(
            (
                source_record,
                ATLAS.sourceDigest,
                Literal("sha256:" + hashlib.sha256(local_name.encode("utf-8")).hexdigest()),
            )
        )
        graph.add((source_record, ATLAS.sourceLocator, URIRef(f"urn:ref:atlas-fixture:locator:{local_name}")))
        graph.add(
            (
                source_record,
                ATLAS.nativePayload,
                Literal(
                    atlas_validate.canonical_json_bytes(
                        {"identifier": local_name, "label": label_text},
                        terminal_lf=False,
                    ).decode("utf-8"),
                    datatype=RDF.JSON,
                    normalize=False,
                ),
            )
        )
        result.append((resource, source_record))
    return release, scheme, result


def _add_policy(graph: Graph, *, version: str) -> URIRef:
    pending = URIRef(f"urn:ref:atlas-policy:pending:{version}")
    payload = atlas_validate.canonical_json_bytes(
        {
            "admission": "approved evidence required",
            "minimumEvidenceBindings": 1,
            "version": version,
        },
        terminal_lf=False,
    ).decode("utf-8")
    graph.add((pending, RDF.type, ATLAS.EditorialPolicy))
    graph.add(
        (
            pending,
            ATLAS.policyPayload,
            Literal(payload, datatype=RDF.JSON, normalize=False),
        )
    )
    digest = atlas_validate.rdf_node_digest(graph, pending)
    policy = URIRef("urn:ref:atlas-policy:" + digest.removeprefix("sha256:"))
    for _, predicate, obj in list(graph.triples((pending, None, None))):
        graph.remove((pending, predicate, obj))
        graph.add((policy, predicate, obj))
    graph.add((policy, ATLAS.contentDigest, Literal(digest)))
    return policy


def _add_assertion(
    graph: Graph,
    *,
    assertion_type: URIRef,
    ring: URIRef,
    subject: URIRef,
    predicate: URIRef,
    obj: URIRef,
    source_release: URIRef,
    target_release: URIRef,
    evidence_record: URIRef,
    evidence_name: str,
    policy: URIRef | None = None,
    asserted_at: str = CREATED_AT,
    status: URIRef = ATLAS.current,
    supersedes: URIRef | None = None,
) -> URIRef:
    if policy is None:
        policies = list(graph.subjects(RDF.type, ATLAS.EditorialPolicy))
        if len(policies) != 1:
            raise ValueError("_add_assertion needs an explicit policy when the graph has != 1 policy")
        policy = policies[0]
    policy_digest = graph.value(policy, ATLAS.contentDigest)
    if not isinstance(policy_digest, Literal):
        raise TypeError("_add_assertion policy has no contentDigest")
    basis = {
        "object": str(obj),
        "policy": str(policy),
        "policyContentDigest": str(policy_digest),
        "predicate": str(predicate),
        "semanticRing": str(ring),
        "sourceRelease": str(source_release),
        "subject": str(subject),
        "targetRelease": str(target_release),
        "type": str(assertion_type),
    }
    digest = atlas_validate.canonical_sha256(basis)
    assertion = URIRef("urn:ref:atlas-assertion:" + digest.removeprefix("sha256:"))
    graph.add((assertion, RDF.type, ATLAS.RelationAssertion))
    graph.add((assertion, RDF.type, assertion_type))
    if assertion_type == ATLAS.MappingAssertion and ring == ATLAS.subject:
        graph.add((assertion, RDF.type, ATLAS.SkosMappingAssertion))
    graph.add((assertion, RDF.subject, subject))
    graph.add((assertion, RDF.predicate, predicate))
    graph.add((assertion, RDF.object, obj))
    graph.add((assertion, ATLAS.semanticRing, ring))
    graph.add((assertion, ATLAS.sourceRelease, source_release))
    graph.add((assertion, ATLAS.targetRelease, target_release))
    graph.add((assertion, ATLAS.governedByPolicy, policy))
    graph.add(
        (
            assertion,
            ATLAS.assertedAt,
            Literal(asserted_at, datatype=XSD.dateTime, normalize=False),
        )
    )
    graph.add((assertion, ATLAS.assertionStatus, status))
    if supersedes is not None:
        graph.add((assertion, ATLAS.supersedes, supersedes))
    graph.add((assertion, ATLAS.assertionIdentityDigest, Literal(digest)))
    graph.add(
        (
            assertion,
            ATLAS.contentDigest,
            Literal(atlas_validate.rdf_node_digest(graph, assertion)),
        )
    )
    evidence = URIRef(f"urn:ref:atlas-evidence:pending:{evidence_name}")
    graph.add((evidence, RDF.type, ATLAS.EvidenceBinding))
    graph.add((evidence, ATLAS.bindsAssertion, assertion))
    graph.add((evidence, ATLAS.evidenceSourceRecord, evidence_record))
    graph.add((evidence, ATLAS.reviewedBy, REVIEWER))
    graph.add((evidence, ATLAS.decisionStatus, ATLAS.approved))
    graph.add((evidence, ATLAS.reviewMethod, ATLAS.humanReview))
    graph.add(
        (
            evidence,
            ATLAS.decidedAt,
            Literal(asserted_at, datatype=XSD.dateTime, normalize=False),
        )
    )
    graph.add(
        (
            evidence,
            ATLAS.confidence,
            Literal("0.98", datatype=XSD.decimal, normalize=False),
        )
    )
    graph.add(
        (
            evidence,
            ATLAS.evidenceSourceDigest,
            Literal(atlas_validate.rdf_node_digest(graph, evidence_record)),
        )
    )
    evidence_digest = atlas_validate.rdf_node_digest(graph, evidence)
    evidence_id = URIRef("urn:ref:atlas-evidence:" + evidence_digest.removeprefix("sha256:"))
    evidence_triples = list(graph.triples((evidence, None, None)))
    for _, evidence_predicate, evidence_object in evidence_triples:
        graph.remove((evidence, evidence_predicate, evidence_object))
        graph.add((evidence_id, evidence_predicate, evidence_object))
    graph.add((evidence_id, ATLAS.contentDigest, Literal(evidence_digest)))
    return assertion


def _base_fixture() -> Fixture:
    asserted = Graph()
    derived = Graph()
    _add_policy(asserted, version="1")
    asserted.add((SOURCE_RELEASE, RDF.type, ATLAS.SourceRelease))
    asserted.add((SOURCE_RELEASE, DCTERMS.identifier, Literal("fixture-source-2026")))
    asserted.add((SOURCE_RELEASE, DCTERMS.issued, Literal("2026-08-05", datatype=XSD.date)))
    asserted.add((SOURCE_RELEASE, ATLAS.sourceDigest, Literal("sha256:" + "0" * 64)))
    asserted.add((SOURCE_RELEASE, ATLAS.sourceLocator, URIRef("urn:ref:atlas-fixture:source-release-file")))

    subject_a_release, subject_a_scheme, subject_a_rows = _add_release(
        asserted,
        name="subject-a",
        profile=ATLAS.conceptScheme,
        ring=ATLAS.subject,
        resources=[
            ("subject-a", ATLAS.SubjectConcept, "Administrative law"),
            ("subject-a-child", ATLAS.SubjectConcept, "Agency procedure"),
        ],
    )
    subject_b_release, subject_b_scheme, subject_b_rows = _add_release(
        asserted,
        name="subject-b",
        profile=ATLAS.conceptScheme,
        ring=ATLAS.subject,
        resources=[("subject-b", ATLAS.SubjectConcept, "Administrative law")],
    )
    subject_c_release, subject_c_scheme, subject_c_rows = _add_release(
        asserted,
        name="subject-c",
        profile=ATLAS.conceptScheme,
        ring=ATLAS.subject,
        resources=[("subject-c", ATLAS.SubjectConcept, "Administrative law")],
    )
    value_release, value_scheme, value_rows = _add_release(
        asserted,
        name="values",
        profile=ATLAS.codeScheme,
        ring=ATLAS.value,
        resources=[
            ("value-parent", ATLAS.ValueResource, "Rulemaking"),
            ("value-child", ATLAS.ValueResource, "Proposed rule"),
        ],
    )
    entity_release, entity_scheme, entity_rows = _add_release(
        asserted,
        name="entities",
        profile=ATLAS.identifierScheme,
        ring=ATLAS.entity,
        resources=[("entity-agency", ATLAS.EntityResource, "Example Agency")],
    )
    legal_release, legal_scheme, legal_rows = _add_release(
        asserted,
        name="legal-structure",
        profile=ATLAS.structureScheme,
        ring=ATLAS.legalIdentity,
        resources=[("legal-title", ATLAS.LegalIdentityResource, "Example Code title")],
    )
    mixed_code_scheme = URIRef("urn:ref:atlas-fixture:scheme:mixed-code")
    _add_release(
        asserted,
        name="mixed-code-subject",
        profile=ATLAS.codeScheme,
        ring=ATLAS.subject,
        resources=[
            ("mixed-code-subject", ATLAS.SubjectConcept, "Mixed code topic")
        ],
        scheme=mixed_code_scheme,
    )
    _add_release(
        asserted,
        name="mixed-code-value",
        profile=ATLAS.codeScheme,
        ring=ATLAS.value,
        resources=[
            ("mixed-code-value", ATLAS.ValueResource, "Mixed code value")
        ],
        scheme=mixed_code_scheme,
    )
    collection_scheme = URIRef("urn:ref:atlas-fixture:scheme:collection")
    asserted.add((collection_scheme, RDF.type, ATLAS.ResourceScheme))
    asserted.add((collection_scheme, ATLAS.resourceProfile, ATLAS.resourceCollection))
    asserted.add((collection_scheme, DCTERMS.identifier, Literal("fixture-collection")))
    asserted.add((collection_scheme, DCTERMS.title, Literal("Fixture resource collection")))
    asserted.add(
        (
            collection_scheme,
            ATLAS.descriptorPayload,
            Literal(
                atlas_validate.canonical_json_bytes(
                    {"resourceId": "fixture-collection", "title": "Fixture resource collection"},
                    terminal_lf=False,
                ).decode("utf-8"),
                datatype=RDF.JSON,
            ),
        )
    )
    for member_scheme in (
        subject_a_scheme,
        subject_b_scheme,
        subject_c_scheme,
        value_scheme,
        entity_scheme,
        legal_scheme,
        mixed_code_scheme,
    ):
        asserted.add((collection_scheme, ATLAS.collectionMember, member_scheme))

    entity, _ = entity_rows[0]
    identifier = URIRef("urn:ref:atlas-fixture:identifier:agency")
    asserted.add((identifier, RDF.type, ATLAS.Identifier))
    asserted.add((identifier, ATLAS.identifierValue, Literal("AGENCY-001")))
    asserted.add((identifier, ATLAS.identifierScheme, entity_scheme))
    asserted.add((identifier, ATLAS.identifies, entity))
    asserted.add((identifier, ATLAS.sourceRecord, entity_rows[0][1]))

    subject_a, source_a = subject_a_rows[0]
    subject_a_child, source_a_child = subject_a_rows[1]
    subject_b, source_b = subject_b_rows[0]
    subject_c, source_c = subject_c_rows[0]
    value_parent, _source_value_parent = value_rows[0]
    value_child, source_value_child = value_rows[1]
    legal, source_legal = legal_rows[0]

    asserted.add((subject_a, ATLAS.definition, Literal("Administrative agency law", lang="en")))
    asserted.add(
        (
            subject_a,
            ATLAS.note,
            Literal(
                'Synthetic line one\nline\ttwo "quoted" — café _:not-a-node',
                lang="en",
            ),
        )
    )
    asserted.add((value_child, ATLAS.notation, Literal("PROPOSED")))
    asserted.add((value_child, ATLAS.recordStatus, Literal("current")))
    asserted.add(
        (
            value_child,
            ATLAS.validFrom,
            Literal("2026-01-01T00:00:00+00:00", datatype=XSD.dateTime, normalize=False),
        )
    )
    asserted.add(
        (
            value_child,
            ATLAS.validUntil,
            Literal("2026-12-31T23:59:59+00:00", datatype=XSD.dateTime, normalize=False),
        )
    )
    asserted.add((entity_scheme, ATLAS.validationRule, Literal("^[A-Z]+-[0-9]+$")))
    asserted.add((legal_scheme, ATLAS.validationRule, Literal("ordered legal structure")))
    asserted.add((legal, ATLAS.componentPosition, Literal(1, datatype=XSD.integer)))

    _add_assertion(
        asserted,
        assertion_type=ATLAS.NativeRelationAssertion,
        ring=ATLAS.subject,
        subject=subject_a_child,
        predicate=SKOS.broader,
        obj=subject_a,
        source_release=subject_a_release,
        target_release=subject_a_release,
        evidence_record=source_a_child,
        evidence_name="native-subject",
    )
    exact_ab = _add_assertion(
        asserted,
        assertion_type=ATLAS.MappingAssertion,
        ring=ATLAS.subject,
        subject=subject_a,
        predicate=SKOS.exactMatch,
        obj=subject_b,
        source_release=subject_a_release,
        target_release=subject_b_release,
        evidence_record=source_a,
        evidence_name="exact-ab",
    )
    exact_bc = _add_assertion(
        asserted,
        assertion_type=ATLAS.MappingAssertion,
        ring=ATLAS.subject,
        subject=subject_b,
        predicate=SKOS.exactMatch,
        obj=subject_c,
        source_release=subject_b_release,
        target_release=subject_c_release,
        evidence_record=source_b,
        evidence_name="exact-bc",
    )
    _add_assertion(
        asserted,
        assertion_type=ATLAS.NativeRelationAssertion,
        ring=ATLAS.value,
        subject=value_child,
        predicate=ATLAS.broaderValue,
        obj=value_parent,
        source_release=value_release,
        target_release=value_release,
        evidence_record=source_value_child,
        evidence_name="native-value",
    )
    _add_assertion(
        asserted,
        assertion_type=ATLAS.SourceAssignment,
        ring=ATLAS.subject,
        subject=source_c,
        predicate=ATLAS.assignedSubject,
        obj=subject_c,
        source_release=SOURCE_RELEASE,
        target_release=subject_c_release,
        evidence_record=source_c,
        evidence_name="assignment-subject",
    )
    _add_assertion(
        asserted,
        assertion_type=ATLAS.SourceAssignment,
        ring=ATLAS.entity,
        subject=entity_rows[0][1],
        predicate=ATLAS.assignedEntity,
        obj=entity,
        source_release=SOURCE_RELEASE,
        target_release=entity_release,
        evidence_record=entity_rows[0][1],
        evidence_name="assignment-entity",
    )
    _add_assertion(
        asserted,
        assertion_type=ATLAS.SourceAssignment,
        ring=ATLAS.legalIdentity,
        subject=source_legal,
        predicate=ATLAS.assignedLegalIdentity,
        obj=legal,
        source_release=SOURCE_RELEASE,
        target_release=legal_release,
        evidence_record=source_legal,
        evidence_name="assignment-legal",
    )

    derived_id = URIRef("urn:ref:atlas-derived:pending")
    derived.add((derived_id, RDF.type, ATLAS.DerivedRelation))
    derived.add((derived_id, ATLAS.relationSubject, subject_a))
    derived.add((derived_id, ATLAS.relationPredicate, SKOS.exactMatch))
    derived.add((derived_id, ATLAS.relationObject, subject_c))
    derived.add((derived_id, ATLAS.derivedFromAssertion, exact_ab))
    derived.add((derived_id, ATLAS.derivedFromAssertion, exact_bc))
    derived.add((derived_id, ATLAS.semanticRing, ATLAS.subject))
    derived.add((derived_id, ATLAS.derivationRule, atlas_validate.EXACT_MATCH_TRANSITIVITY_RULE))
    derived.add((derived_id, ATLAS.engine, atlas_validate.DERIVATION_ENGINE))
    derived.add((derived_id, ATLAS.engineVersion, Literal(atlas_validate.DERIVATION_ENGINE_VERSION)))
    derived.add(
        (
            derived_id,
            ATLAS.inputDigest,
            Literal(atlas_validate.derived_input_digest(asserted, [exact_ab, exact_bc])),
        )
    )
    derived.add(
        (
            derived_id,
            ATLAS.generatedAt,
            Literal(CREATED_AT, datatype=XSD.dateTime, normalize=False),
        )
    )
    derived.add((derived_id, ATLAS.authorityStatus, ATLAS.nonAuthoritative))

    lifecycle = URIRef("urn:ref:atlas-fixture:lifecycle:exact-ab-admitted")
    asserted.add((lifecycle, RDF.type, ATLAS.LifecycleEvent))
    asserted.add((lifecycle, ATLAS.eventSubject, exact_ab))
    asserted.add((lifecycle, ATLAS.eventType, URIRef("urn:ref:atlas-event:admitted")))
    asserted.add(
        (
            lifecycle,
            ATLAS.eventAt,
            Literal(CREATED_AT, datatype=XSD.dateTime, normalize=False),
        )
    )
    asserted.add((lifecycle, ATLAS.toRelease, subject_b_release))
    asserted.add((lifecycle, ATLAS.sourceRecord, source_a))

    digest_classes = {
        ATLAS.ResourceScheme,
        ATLAS.AtlasRelease,
        ATLAS.SourceRelease,
        ATLAS.AtlasResource,
        ATLAS.SubjectConcept,
        ATLAS.EntityResource,
        ATLAS.ValueResource,
        ATLAS.LegalIdentityResource,
        ATLAS.Identifier,
        ATLAS.SourceRecord,
        ATLAS.EvidenceBinding,
        ATLAS.EditorialPolicy,
        ATLAS.LifecycleEvent,
        SKOSXL.Label,
    }
    digest_nodes = {
        node
        for class_iri in digest_classes
        for node in asserted.subjects(RDF.type, class_iri)
        if isinstance(node, URIRef)
    }
    for node in sorted(digest_nodes, key=str):
        asserted.add((node, ATLAS.contentDigest, Literal(atlas_validate.rdf_node_digest(asserted, node))))
    derived_digest = atlas_validate.rdf_node_digest(derived, derived_id)
    final_derived_id = URIRef("urn:ref:atlas-derived:" + derived_digest.removeprefix("sha256:"))
    for _, predicate, obj in list(derived.triples((derived_id, None, None))):
        derived.remove((derived_id, predicate, obj))
        derived.add((final_derived_id, predicate, obj))
    derived.add((final_derived_id, ATLAS.contentDigest, Literal(derived_digest)))

    projection = atlas_validate._expected_projection(asserted)
    resource_by_record: dict[str, list[str]] = defaultdict(list)
    for resource_type in atlas_validate.RESOURCE_TYPES:
        for resource in asserted.subjects(RDF.type, resource_type):
            for label in asserted.objects(resource, SKOSXL.prefLabel):
                for record in asserted.objects(label, ATLAS.sourceRecord):
                    resource_by_record[str(record)].append(str(resource))
    source_records = sorted(str(row) for row in asserted.subjects(RDF.type, ATLAS.SourceRecord))
    dispositions = [
        {
            "atlasResources": sorted(resource_by_record[record]),
            "sourceRecord": record,
            "status": "represented",
        }
        for record in source_records
    ]
    accounting = {
        "distributionId": "urn:ref:atlas-fixture:distribution:all-resource-profiles",
        "inputs": [
            {
                "declaredMemberCount": len(dispositions),
                "dispositions": dispositions,
                "membershipMode": "complete",
                "sourceRelease": str(SOURCE_RELEASE),
            }
        ],
        "totals": {
            "excluded": 0,
            "represented": len(dispositions),
            "sourceRecords": len(dispositions),
            "sourceReleases": 1,
            "unresolved": 0,
        },
        "type": "AtlasSourceAccounting",
        "version": "3.0",
    }
    return Fixture(
        asserted=asserted,
        projection=projection,
        derived=derived,
        accounting=accounting,
        acceptance={},
        manifest_patch={},
    )


def _nquad_line(triple: tuple[Any, Any, Any], graph_id: URIRef) -> str:
    subject, predicate, obj = triple
    if any(isinstance(term, BNode) for term in triple):
        rendered = [
            term.n3() if isinstance(term, BNode) else atlas_validate.ntriples_term(term)
            for term in (subject, predicate, obj, graph_id)
        ]
        return " ".join((*rendered, "."))
    return atlas_validate.nquads_line(subject, predicate, obj, graph_id)


def _dataset_bytes(fixture: Fixture, distribution_id: str) -> tuple[bytes, list[dict[str, Any]]]:
    graph_ids = {
        "asserted": URIRef(distribution_id + ":asserted"),
        "projection": URIRef(distribution_id + ":projection"),
        "derived": URIRef(distribution_id + ":derived"),
    }
    graphs = {
        "asserted": fixture.asserted,
        "projection": fixture.projection,
        "derived": fixture.derived,
    }
    lines = sorted(
        _nquad_line(triple, graph_ids[role])
        for role, graph in graphs.items()
        for triple in graph
    )
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    descriptors = [
        {"id": str(graph_ids[role]), "quadCount": len(graphs[role]), "role": role}
        for role in ("asserted", "projection", "derived")
    ]
    return payload, descriptors


def _counts(fixture: Fixture) -> dict[str, int]:
    asserted = fixture.asserted
    return {
        "derivedRelations": len(set(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))),
        "labels": len(set(asserted.subjects(RDF.type, SKOSXL.Label))),
        "mappingAssertions": len(set(asserted.subjects(RDF.type, ATLAS.MappingAssertion))),
        "nativeRelationAssertions": len(set(asserted.subjects(RDF.type, ATLAS.NativeRelationAssertion))),
        "projectedRelations": len(set(fixture.projection.subjects(RDF.type, ATLAS.ProjectedRelation))),
        "relationAssertions": sum(
            len(set(asserted.subjects(RDF.type, assertion_type)))
            for assertion_type in atlas_validate.ASSERTION_TYPES
        ),
        "releases": len(set(asserted.subjects(RDF.type, ATLAS.AtlasRelease))),
        "resources": len(
            {
                subject
                for resource_type in atlas_validate.RESOURCE_TYPES
                for subject in asserted.subjects(RDF.type, resource_type)
            }
        ),
        "sourceAssignments": len(set(asserted.subjects(RDF.type, ATLAS.SourceAssignment))),
        "sourceRecords": len(set(asserted.subjects(RDF.type, ATLAS.SourceRecord))),
    }


def _write_case(
    path: Path,
    fixture: Fixture,
    *,
    binding_digests: dict[str, str],
    distribution_id: str,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    fixture.accounting["distributionId"] = distribution_id
    dataset_bytes, graph_rows = _dataset_bytes(fixture, distribution_id)
    accounting_bytes = atlas_validate.canonical_json_bytes(fixture.accounting)
    acceptance_inputs = {
        "atlasDigest": "sha256:" + hashlib.sha256(dataset_bytes).hexdigest(),
        **binding_digests,
        "sourceAccountingDigest": "sha256:" + hashlib.sha256(accounting_bytes).hexdigest(),
    }
    validator_identity = {"name": "refspec-atlas-conformance", "version": "3.0"}
    acceptance = {
        "distributionId": distribution_id,
        "evaluatedAt": CREATED_AT,
        "gates": [
            {
                "evidenceDigest": atlas_validate.acceptance_gate_evidence_digest(
                    gate,
                    inputs=acceptance_inputs,
                    validator=validator_identity,
                ),
                "name": gate,
                "status": "passed",
            }
            for gate in sorted(atlas_validate.REQUIRED_GATES)
            if gate != fixture.omitted_gate
        ],
        "inputs": acceptance_inputs,
        "type": "AtlasAcceptance",
        "validator": validator_identity,
        "verdict": "passed",
        "version": "3.0",
    }
    acceptance.update(fixture.acceptance)
    acceptance_bytes = atlas_validate.canonical_json_bytes(acceptance)
    manifest = {
        "binding": {"validatorVersion": "3.0", "version": "3.0", **binding_digests},
        "counts": _counts(fixture),
        "createdAt": CREATED_AT,
        "distributionId": distribution_id,
        "format": "refspec-atlas-nquads-3.0",
        "graphs": graph_rows,
        "members": [
            {
                "byteLength": len(dataset_bytes),
                "digest": "sha256:" + hashlib.sha256(dataset_bytes).hexdigest(),
                "mediaType": "application/n-quads",
                "path": "atlas.nq",
                "role": "atlasDataset",
            },
            {
                "byteLength": len(accounting_bytes),
                "digest": "sha256:" + hashlib.sha256(accounting_bytes).hexdigest(),
                "mediaType": "application/json",
                "path": "atlas-source-accounting.json",
                "role": "sourceAccounting",
            },
            {
                "byteLength": len(acceptance_bytes),
                "digest": "sha256:" + hashlib.sha256(acceptance_bytes).hexdigest(),
                "mediaType": "application/json",
                "path": "atlas-acceptance.json",
                "role": "acceptance",
            },
        ],
        "schemaVersion": "3.0",
        "type": "AtlasManifest",
    }
    manifest.update(fixture.manifest_patch)
    manifest["canonicalPayloadDigest"] = atlas_validate.canonical_sha256(
        manifest, terminal_lf=False
    )
    (path / "atlas.nq").write_bytes(dataset_bytes)
    (path / "atlas-source-accounting.json").write_bytes(accounting_bytes)
    (path / "atlas-acceptance.json").write_bytes(acceptance_bytes)
    (path / "atlas-manifest.json").write_bytes(atlas_validate.canonical_json_bytes(manifest))
    if fixture.post_write is not None:
        fixture.post_write(path)


def _remove_subject_predicate(graph: Graph, subject: Any, predicate: Any) -> None:
    for triple in list(graph.triples((subject, predicate, None))):
        graph.remove(triple)


def _refresh_node_digest(graph: Graph, node: URIRef) -> None:
    _remove_subject_predicate(graph, node, ATLAS.contentDigest)
    graph.add((node, ATLAS.contentDigest, Literal(atlas_validate.rdf_node_digest(graph, node))))


def _refresh_evidence_for_source(graph: Graph, source_record: URIRef) -> None:
    source_digest = graph.value(source_record, ATLAS.contentDigest)
    if not isinstance(source_digest, Literal):
        raise TypeError("source record has no contentDigest")
    for evidence in list(graph.subjects(ATLAS.evidenceSourceRecord, source_record)):
        _remove_subject_predicate(graph, evidence, ATLAS.evidenceSourceDigest)
        _remove_subject_predicate(graph, evidence, ATLAS.contentDigest)
        graph.add((evidence, ATLAS.evidenceSourceDigest, source_digest))
        digest = atlas_validate.rdf_node_digest(graph, evidence)
        replacement = URIRef("urn:ref:atlas-evidence:" + digest.removeprefix("sha256:"))
        for _, predicate, obj in list(graph.triples((evidence, None, None))):
            graph.remove((evidence, predicate, obj))
            graph.add((replacement, predicate, obj))
        graph.add((replacement, ATLAS.contentDigest, Literal(digest)))


def _reidentify_derived(graph: Graph, node: URIRef) -> URIRef:
    _remove_subject_predicate(graph, node, ATLAS.contentDigest)
    digest = atlas_validate.rdf_node_digest(graph, node)
    replacement = URIRef("urn:ref:atlas-derived:" + digest.removeprefix("sha256:"))
    for _, predicate, obj in list(graph.triples((node, None, None))):
        graph.remove((node, predicate, obj))
        graph.add((replacement, predicate, obj))
    graph.add((replacement, ATLAS.contentDigest, Literal(digest)))
    return replacement


def _mutations() -> list[tuple[str, list[str], str, Callable[[Fixture], None]]]:
    def no_derived(fixture: Fixture) -> None:
        fixture.derived.remove((None, None, None))

    def rdf_literal_escaping(_fixture: Fixture) -> None:
        return

    def valid_supersession(fixture: Fixture) -> None:
        old = next(
            assertion
            for assertion in fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion)
            if fixture.asserted.value(assertion, RDF.subject)
            == URIRef("urn:ref:atlas-fixture:resource:subject-a")
        )
        _, (subject, predicate, obj) = atlas_validate._assertion_basis(
            fixture.asserted, old
        )
        source_release = next(fixture.asserted.objects(old, ATLAS.sourceRelease))
        target_release = next(fixture.asserted.objects(old, ATLAS.targetRelease))
        evidence = next(fixture.asserted.subjects(ATLAS.bindsAssertion, old))
        evidence_record = next(
            fixture.asserted.objects(evidence, ATLAS.evidenceSourceRecord)
        )
        _remove_subject_predicate(fixture.asserted, old, ATLAS.assertionStatus)
        fixture.asserted.add((old, ATLAS.assertionStatus, ATLAS.superseded))
        _refresh_node_digest(fixture.asserted, old)
        policy = _add_policy(fixture.asserted, version="2")
        _add_assertion(
            fixture.asserted,
            assertion_type=ATLAS.MappingAssertion,
            ring=ATLAS.subject,
            subject=subject,
            predicate=predicate,
            obj=obj,
            source_release=source_release,
            target_release=target_release,
            evidence_record=evidence_record,
            evidence_name="superseding-policy-v2",
            policy=policy,
            asserted_at="2026-08-06T12:00:00+00:00",
            supersedes=old,
        )
        fixture.derived.remove((None, None, None))
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def invalid_supersession_keeps_old_current(fixture: Fixture) -> None:
        old = next(
            assertion
            for assertion in fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion)
            if fixture.asserted.value(assertion, RDF.subject)
            == URIRef("urn:ref:atlas-fixture:resource:subject-a")
        )
        _, (subject, predicate, obj) = atlas_validate._assertion_basis(
            fixture.asserted, old
        )
        source_release = next(fixture.asserted.objects(old, ATLAS.sourceRelease))
        target_release = next(fixture.asserted.objects(old, ATLAS.targetRelease))
        evidence = next(fixture.asserted.subjects(ATLAS.bindsAssertion, old))
        evidence_record = next(
            fixture.asserted.objects(evidence, ATLAS.evidenceSourceRecord)
        )
        policy = _add_policy(fixture.asserted, version="2")
        _add_assertion(
            fixture.asserted,
            assertion_type=ATLAS.MappingAssertion,
            ring=ATLAS.subject,
            subject=subject,
            predicate=predicate,
            obj=obj,
            source_release=source_release,
            target_release=target_release,
            evidence_record=evidence_record,
            evidence_name="invalid-superseding-policy-v2",
            policy=policy,
            asserted_at="2026-08-06T12:00:00+00:00",
            supersedes=old,
        )

    def unknown_manifest_field(fixture: Fixture) -> None:
        fixture.manifest_patch["unexpected"] = "closed schema"

    def digest_mismatch(fixture: Fixture) -> None:
        def mutate(path: Path) -> None:
            dataset = path / "atlas.nq"
            payload = dataset.read_bytes()
            dataset.write_bytes(payload.replace(b"fixture", b"fixturf", 1))

        fixture.post_write = mutate

    def blank_node(fixture: Fixture) -> None:
        fixture.asserted.add((BNode("forbidden"), RDF.type, ATLAS.ResourceScheme))

    def label_missing_literal(fixture: Fixture) -> None:
        label = next(fixture.asserted.subjects(RDF.type, SKOSXL.Label))
        _remove_subject_predicate(fixture.asserted, label, SKOSXL.literalForm)
        _refresh_node_digest(fixture.asserted, label)

    def duplicate_preferred_language(fixture: Fixture) -> None:
        resource = next(fixture.asserted.subjects(RDF.type, ATLAS.SubjectConcept))
        release = next(fixture.asserted.objects(resource, ATLAS.inRelease))
        source = next(fixture.asserted.subjects(RDF.type, ATLAS.SourceRecord))
        label = URIRef("urn:ref:atlas-fixture:label:duplicate:en")
        fixture.asserted.add((resource, SKOSXL.prefLabel, label))
        fixture.asserted.add((label, RDF.type, SKOSXL.Label))
        fixture.asserted.add((label, SKOSXL.literalForm, Literal("Duplicate", lang="en")))
        fixture.asserted.add((label, ATLAS.inRelease, release))
        fixture.asserted.add((label, ATLAS.sourceRecord, source))
        _refresh_node_digest(fixture.asserted, label)
        _refresh_node_digest(fixture.asserted, resource)

    def missing_evidence(fixture: Fixture) -> None:
        assertion = next(fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion))
        for evidence in list(fixture.asserted.subjects(ATLAS.bindsAssertion, assertion)):
            fixture.asserted.remove((evidence, None, None))

    def wrong_ring_relation(fixture: Fixture) -> None:
        assertion = next(
            row
            for row in fixture.asserted.subjects(RDF.type, ATLAS.NativeRelationAssertion)
            if fixture.asserted.value(row, ATLAS.semanticRing) == ATLAS.value
        )
        _, (subject, _, obj) = atlas_validate._assertion_basis(fixture.asserted, assertion)
        source_release = next(fixture.asserted.objects(assertion, ATLAS.sourceRelease))
        target_release = next(fixture.asserted.objects(assertion, ATLAS.targetRelease))
        evidence = next(fixture.asserted.subjects(ATLAS.bindsAssertion, assertion))
        evidence_record = next(fixture.asserted.objects(evidence, ATLAS.evidenceSourceRecord))
        fixture.asserted.remove((assertion, None, None))
        fixture.asserted.remove((evidence, None, None))
        _add_assertion(
            fixture.asserted,
            assertion_type=ATLAS.NativeRelationAssertion,
            ring=ATLAS.value,
            subject=subject,
            predicate=ATLAS.sameEntityAs,
            obj=obj,
            source_release=source_release,
            target_release=target_release,
            evidence_record=evidence_record,
            evidence_name="wrong-ring-relation",
        )

    def naked_projection(fixture: Fixture) -> None:
        resources = list(fixture.asserted.subjects(RDF.type, ATLAS.SubjectConcept))
        fixture.projection.add((resources[0], SKOS.closeMatch, resources[-1]))

    def derived_authoritative(fixture: Fixture) -> None:
        node = next(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))
        fixture.derived.add((node, RDF.type, ATLAS.MappingAssertion))

    def derived_extra_type(fixture: Fixture) -> None:
        node = next(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))
        _remove_subject_predicate(fixture.derived, node, ATLAS.contentDigest)
        fixture.derived.add((node, RDF.type, SKOS.Concept))
        digest = atlas_validate.rdf_node_digest(fixture.derived, node)
        replacement = URIRef("urn:ref:atlas-derived:" + digest.removeprefix("sha256:"))
        for _, predicate, obj in list(fixture.derived.triples((node, None, None))):
            fixture.derived.remove((node, predicate, obj))
            fixture.derived.add((replacement, predicate, obj))
        fixture.derived.add((replacement, ATLAS.contentDigest, Literal(digest)))

    def derived_reflexive_output(fixture: Fixture) -> None:
        node = next(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))
        endpoint = URIRef("urn:ref:atlas-fixture:resource:subject-a")
        _remove_subject_predicate(fixture.derived, node, ATLAS.relationSubject)
        _remove_subject_predicate(fixture.derived, node, ATLAS.relationObject)
        fixture.derived.add((node, ATLAS.relationSubject, endpoint))
        fixture.derived.add((node, ATLAS.relationObject, endpoint))
        _reidentify_derived(fixture.derived, node)

    def derived_extra_branch(fixture: Fixture) -> None:
        node = next(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))
        subject = URIRef("urn:ref:atlas-fixture:resource:subject-a-child")
        obj = URIRef("urn:ref:atlas-fixture:resource:subject-c")
        source_release = next(fixture.asserted.objects(subject, ATLAS.inRelease))
        target_release = next(fixture.asserted.objects(obj, ATLAS.inRelease))
        evidence_record = next(fixture.asserted.objects(subject, ATLAS.sourceRecord))
        branch = _add_assertion(
            fixture.asserted,
            assertion_type=ATLAS.MappingAssertion,
            ring=ATLAS.subject,
            subject=subject,
            predicate=SKOS.exactMatch,
            obj=obj,
            source_release=source_release,
            target_release=target_release,
            evidence_record=evidence_record,
            evidence_name="derived-extra-branch",
        )
        fixture.derived.add((node, ATLAS.derivedFromAssertion, branch))
        inputs = list(fixture.derived.objects(node, ATLAS.derivedFromAssertion))
        _remove_subject_predicate(fixture.derived, node, ATLAS.inputDigest)
        fixture.derived.add(
            (
                node,
                ATLAS.inputDigest,
                Literal(atlas_validate.derived_input_digest(fixture.asserted, inputs)),
            )
        )
        _reidentify_derived(fixture.derived, node)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def derived_withdrawn_input(fixture: Fixture) -> None:
        assertion = next(
            row
            for row in fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion)
            if fixture.asserted.value(row, RDF.subject)
            == URIRef("urn:ref:atlas-fixture:resource:subject-a")
        )
        _remove_subject_predicate(fixture.asserted, assertion, ATLAS.assertionStatus)
        fixture.asserted.add((assertion, ATLAS.assertionStatus, ATLAS.withdrawn))
        _refresh_node_digest(fixture.asserted, assertion)
        node = next(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))
        inputs = list(fixture.derived.objects(node, ATLAS.derivedFromAssertion))
        _remove_subject_predicate(fixture.derived, node, ATLAS.inputDigest)
        fixture.derived.add(
            (
                node,
                ATLAS.inputDigest,
                Literal(atlas_validate.derived_input_digest(fixture.asserted, inputs)),
            )
        )
        _reidentify_derived(fixture.derived, node)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def missing_disposition(fixture: Fixture) -> None:
        source = fixture.accounting["inputs"][0]
        source["dispositions"].pop()
        source["declaredMemberCount"] -= 1
        fixture.accounting["totals"]["sourceRecords"] -= 1
        fixture.accounting["totals"]["represented"] -= 1

    def count_mismatch(fixture: Fixture) -> None:
        fixture.manifest_patch["counts"] = {**_counts(fixture), "resources": _counts(fixture)["resources"] + 1}

    def missing_acceptance_gate(fixture: Fixture) -> None:
        fixture.omitted_gate = "reasoning-isolation"

    def identifier_missing_value(fixture: Fixture) -> None:
        identifier = next(fixture.asserted.subjects(RDF.type, ATLAS.Identifier))
        _remove_subject_predicate(fixture.asserted, identifier, ATLAS.identifierValue)
        _refresh_node_digest(fixture.asserted, identifier)

    def wrong_endpoint_release(fixture: Fixture) -> None:
        assertion = next(fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion))
        wrong = next(fixture.asserted.subjects(RDF.type, ATLAS.AtlasRelease))
        _remove_subject_predicate(fixture.asserted, assertion, ATLAS.targetRelease)
        fixture.asserted.add((assertion, ATLAS.targetRelease, wrong))

    def naked_asserted_mapping(fixture: Fixture) -> None:
        resources = list(fixture.asserted.subjects(RDF.type, ATLAS.SubjectConcept))
        fixture.asserted.add((resources[0], SKOS.closeMatch, resources[-1]))

    def naked_derived_mapping(fixture: Fixture) -> None:
        resources = list(fixture.asserted.subjects(RDF.type, ATLAS.SubjectConcept))
        fixture.derived.add((resources[0], SKOS.closeMatch, resources[-1]))

    def untyped_asserted_statement(fixture: Fixture) -> None:
        fixture.asserted.add(
            (
                URIRef("urn:ref:atlas-fixture:untyped"),
                DCTERMS.description,
                Literal("unclassified asserted statement"),
            )
        )

    def auxiliary_type_only(fixture: Fixture) -> None:
        fixture.asserted.add(
            (URIRef("urn:ref:atlas-fixture:auxiliary-only"), RDF.type, SKOS.Concept)
        )

    def evidence_retargeted(fixture: Fixture) -> None:
        evidence = next(fixture.asserted.subjects(RDF.type, ATLAS.EvidenceBinding))
        current = next(fixture.asserted.objects(evidence, ATLAS.evidenceSourceRecord))
        replacement = next(
            record
            for record in fixture.asserted.subjects(RDF.type, ATLAS.SourceRecord)
            if record != current
        )
        _remove_subject_predicate(fixture.asserted, evidence, ATLAS.evidenceSourceRecord)
        fixture.asserted.add((evidence, ATLAS.evidenceSourceRecord, replacement))

    def evidence_reviewer_retargeted(fixture: Fixture) -> None:
        evidence = next(fixture.asserted.subjects(RDF.type, ATLAS.EvidenceBinding))
        _remove_subject_predicate(fixture.asserted, evidence, ATLAS.reviewedBy)
        fixture.asserted.add(
            (evidence, ATLAS.reviewedBy, URIRef("urn:ref:agent:unreviewed-replacement"))
        )

    def policy_payload_changed(fixture: Fixture) -> None:
        policy = next(fixture.asserted.subjects(RDF.type, ATLAS.EditorialPolicy))
        _remove_subject_predicate(fixture.asserted, policy, ATLAS.policyPayload)
        fixture.asserted.add(
            (
                policy,
                ATLAS.policyPayload,
                Literal(
                    atlas_validate.canonical_json_bytes(
                        {
                            "admission": "changed without new assertion identity",
                            "minimumEvidenceBindings": 1,
                            "version": "changed",
                        },
                        terminal_lf=False,
                    ).decode("utf-8"),
                    datatype=RDF.JSON,
                    normalize=False,
                ),
            )
        )
        _refresh_node_digest(fixture.asserted, policy)

    def source_accounting_swap(fixture: Fixture) -> None:
        dispositions = fixture.accounting["inputs"][0]["dispositions"]
        dispositions[0]["atlasResources"], dispositions[1]["atlasResources"] = (
            dispositions[1]["atlasResources"],
            dispositions[0]["atlasResources"],
        )

    def source_accounting_false_inverse(fixture: Fixture) -> None:
        record = next(
            candidate
            for candidate in fixture.asserted.subjects(RDF.type, ATLAS.SourceRecord)
            if not list(fixture.asserted.subjects(ATLAS.evidenceSourceRecord, candidate))
        )
        resource = next(
            candidate
            for candidate in fixture.asserted.subjects(RDF.type, ATLAS.AtlasResource)
            if (record, ATLAS.representsResource, candidate) not in fixture.asserted
        )
        fixture.asserted.add((record, ATLAS.representsResource, resource))
        _refresh_node_digest(fixture.asserted, record)
        disposition = next(
            row
            for source in fixture.accounting["inputs"]
            for row in source["dispositions"]
            if row["sourceRecord"] == str(record)
        )
        disposition["atlasResources"] = sorted(
            [*disposition["atlasResources"], str(resource)]
        )

    def cross_role_identity(fixture: Fixture) -> None:
        derived = next(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))
        assertion = next(fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion))
        for _, predicate, obj in list(fixture.derived.triples((derived, None, None))):
            fixture.derived.remove((derived, predicate, obj))
            fixture.derived.add((assertion, predicate, obj))

    def derived_asserted_scheme_collision(fixture: Fixture) -> None:
        derived = next(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))
        fixture.asserted.add((derived, RDF.type, ATLAS.ResourceScheme))
        fixture.asserted.add((derived, ATLAS.resourceProfile, ATLAS.resourceCollection))
        fixture.asserted.add(
            (derived, ATLAS.contentDigest, Literal(atlas_validate.rdf_node_digest(fixture.asserted, derived)))
        )

    def label_extra_skos_type(fixture: Fixture) -> None:
        label = next(fixture.asserted.subjects(RDF.type, SKOSXL.Label))
        fixture.asserted.add((label, RDF.type, SKOS.Concept))

    def scheme_assertion_property(fixture: Fixture) -> None:
        scheme = next(fixture.asserted.subjects(RDF.type, ATLAS.ResourceScheme))
        fixture.asserted.add((scheme, RDF.predicate, SKOS.exactMatch))

    def wrong_derived_input_digest(fixture: Fixture) -> None:
        derived = next(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))
        _remove_subject_predicate(fixture.derived, derived, ATLAS.inputDigest)
        fixture.derived.add((derived, ATLAS.inputDigest, Literal("sha256:" + "4" * 64)))

    def wrong_derived_endpoint(fixture: Fixture) -> None:
        derived = next(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))
        _remove_subject_predicate(fixture.derived, derived, ATLAS.relationSubject)
        fixture.derived.add((derived, ATLAS.relationSubject, SOURCE_RELEASE))

    def wrong_profile_ring(fixture: Fixture) -> None:
        resource = next(fixture.asserted.subjects(RDF.type, ATLAS.SubjectConcept))
        release = next(fixture.asserted.objects(resource, ATLAS.inRelease))
        scheme = next(fixture.asserted.objects(resource, ATLAS.inScheme))
        members = list(fixture.asserted.objects(release, PROV.hadMember))
        for node in (release, scheme, *members):
            _remove_subject_predicate(fixture.asserted, node, ATLAS.resourceProfile)
            fixture.asserted.add((node, ATLAS.resourceProfile, ATLAS.identifierScheme))

    def label_role_overlap(fixture: Fixture) -> None:
        resource = next(fixture.asserted.subjects(RDF.type, ATLAS.SubjectConcept))
        label = next(fixture.asserted.objects(resource, SKOSXL.prefLabel))
        fixture.asserted.add((resource, SKOSXL.altLabel, label))

    def skos_mapping_conflict(fixture: Fixture) -> None:
        assertion = next(fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion))
        _, (subject, _, obj) = atlas_validate._assertion_basis(fixture.asserted, assertion)
        source_release = next(fixture.asserted.objects(assertion, ATLAS.sourceRelease))
        target_release = next(fixture.asserted.objects(assertion, ATLAS.targetRelease))
        evidence_record = next(fixture.asserted.subjects(RDF.type, ATLAS.SourceRecord))
        _add_assertion(
            fixture.asserted,
            assertion_type=ATLAS.MappingAssertion,
            ring=ATLAS.subject,
            subject=subject,
            predicate=SKOS.broadMatch,
            obj=obj,
            source_release=source_release,
            target_release=target_release,
            evidence_record=evidence_record,
            evidence_name="skos-conflict",
        )

    def skos_mapping_reverse_conflict(fixture: Fixture) -> None:
        assertion = next(fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion))
        _, (subject, _, obj) = atlas_validate._assertion_basis(
            fixture.asserted, assertion
        )
        source_release = next(fixture.asserted.objects(obj, ATLAS.inRelease))
        target_release = next(fixture.asserted.objects(subject, ATLAS.inRelease))
        evidence_record = next(fixture.asserted.objects(obj, ATLAS.sourceRecord))
        _add_assertion(
            fixture.asserted,
            assertion_type=ATLAS.MappingAssertion,
            ring=ATLAS.subject,
            subject=obj,
            predicate=SKOS.broadMatch,
            obj=subject,
            source_release=source_release,
            target_release=target_release,
            evidence_record=evidence_record,
            evidence_name="skos-reverse-conflict",
        )

    def skos_mapping_transitive_conflict(fixture: Fixture) -> None:
        subject = URIRef("urn:ref:atlas-fixture:resource:subject-a")
        obj = URIRef("urn:ref:atlas-fixture:resource:subject-c")
        _add_assertion(
            fixture.asserted,
            assertion_type=ATLAS.MappingAssertion,
            ring=ATLAS.subject,
            subject=subject,
            predicate=SKOS.broadMatch,
            obj=obj,
            source_release=next(fixture.asserted.objects(subject, ATLAS.inRelease)),
            target_release=next(fixture.asserted.objects(obj, ATLAS.inRelease)),
            evidence_record=next(fixture.asserted.objects(subject, ATLAS.sourceRecord)),
            evidence_name="skos-transitive-conflict",
        )

    def skos_mapping_hierarchy_conflict(fixture: Fixture) -> None:
        subject = URIRef("urn:ref:atlas-fixture:resource:subject-a-child")
        obj = URIRef("urn:ref:atlas-fixture:resource:subject-b")
        source_release = next(fixture.asserted.objects(subject, ATLAS.inRelease))
        target_release = next(fixture.asserted.objects(obj, ATLAS.inRelease))
        evidence_record = next(fixture.asserted.objects(subject, ATLAS.sourceRecord))
        for predicate, name in (
            (SKOS.broadMatch, "skos-cross-broad"),
            (SKOS.relatedMatch, "skos-cross-related"),
        ):
            _add_assertion(
                fixture.asserted,
                assertion_type=ATLAS.MappingAssertion,
                ring=ATLAS.subject,
                subject=subject,
                predicate=predicate,
                obj=obj,
                source_release=source_release,
                target_release=target_release,
                evidence_record=evidence_record,
                evidence_name=name,
            )

    def skos_hierarchy_conflict(fixture: Fixture) -> None:
        assertion = next(
            row
            for row in fixture.asserted.subjects(RDF.type, ATLAS.NativeRelationAssertion)
            if fixture.asserted.value(row, ATLAS.semanticRing) == ATLAS.subject
        )
        _, (subject, _, obj) = atlas_validate._assertion_basis(fixture.asserted, assertion)
        release = next(fixture.asserted.objects(assertion, ATLAS.sourceRelease))
        evidence_record = next(fixture.asserted.subjects(RDF.type, ATLAS.SourceRecord))
        _add_assertion(
            fixture.asserted,
            assertion_type=ATLAS.NativeRelationAssertion,
            ring=ATLAS.subject,
            subject=subject,
            predicate=SKOS.related,
            obj=obj,
            source_release=release,
            target_release=release,
            evidence_record=evidence_record,
            evidence_name="skos-hierarchy-conflict",
        )

    def assertion_extra_property(fixture: Fixture) -> None:
        assertion = next(fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion))
        fixture.asserted.add((assertion, DCTERMS.description, Literal("mutable annotation")))

    def wrong_validator_identity(fixture: Fixture) -> None:
        fixture.acceptance["validator"] = {"name": "other-validator", "version": "99"}

    def subject_scheme_disagreement(fixture: Fixture) -> None:
        resource = next(fixture.asserted.subjects(RDF.type, ATLAS.SubjectConcept))
        wrong_scheme = next(
            scheme
            for scheme in fixture.asserted.subjects(RDF.type, ATLAS.ResourceScheme)
            if scheme not in fixture.asserted.objects(resource, ATLAS.inScheme)
        )
        _remove_subject_predicate(fixture.asserted, resource, SKOS.inScheme)
        fixture.asserted.add((resource, SKOS.inScheme, wrong_scheme))
        _refresh_node_digest(fixture.asserted, resource)

    def noncanonical_native_payload(fixture: Fixture) -> None:
        record = next(fixture.asserted.subjects(RDF.type, ATLAS.SourceRecord))
        current = next(fixture.asserted.objects(record, ATLAS.nativePayload))
        value = json.loads(str(current))
        _remove_subject_predicate(fixture.asserted, record, ATLAS.nativePayload)
        fixture.asserted.add(
            (
                record,
                ATLAS.nativePayload,
                Literal(
                    json.dumps(value, sort_keys=True, separators=(", ", ": ")),
                    datatype=RDF.JSON,
                    normalize=False,
                ),
            )
        )
        _refresh_node_digest(fixture.asserted, record)
        _refresh_evidence_for_source(fixture.asserted, record)

    return [
        ("no-derived", ["rdf", "dataset", "reasoning"], "valid", no_derived),
        ("rdf-literal-escaping", ["rdf", "dataset"], "valid", rdf_literal_escaping),
        (
            "superseded-policy-revision",
            ["rdf", "dataset", "lifecycle"],
            "valid",
            valid_supersession,
        ),
        ("manifest-unknown-field", ["json"], "json.schema", unknown_manifest_field),
        ("dataset-digest-mismatch", ["dataset"], "distribution.digest", digest_mismatch),
        ("blank-node", ["rdf"], "rdf.blank-node", blank_node),
        ("label-missing-literal", ["shacl"], "shacl.data", label_missing_literal),
        ("duplicate-preferred-language", ["shacl"], "shacl.data", duplicate_preferred_language),
        ("mapping-missing-evidence", ["shacl", "dataset"], "shacl.data", missing_evidence),
        ("wrong-ring-relation", ["dataset"], "dataset.relation", wrong_ring_relation),
        ("naked-projected-mapping", ["dataset"], "dataset.projection", naked_projection),
        ("derived-is-authoritative", ["shacl", "reasoning"], "shacl.data", derived_authoritative),
        ("derived-extra-type", ["dataset", "reasoning"], "dataset.graph-placement", derived_extra_type),
        ("derived-reflexive-output", ["dataset", "reasoning"], "dataset.derived-rule", derived_reflexive_output),
        ("derived-extra-branch", ["dataset", "reasoning"], "dataset.derived-rule", derived_extra_branch),
        ("derived-withdrawn-input", ["dataset", "reasoning", "lifecycle"], "dataset.derived", derived_withdrawn_input),
        ("source-accounting-missing-disposition", ["json", "dataset"], "source.accounting", missing_disposition),
        ("manifest-count-mismatch", ["dataset"], "dataset.counts", count_mismatch),
        ("acceptance-missing-gate", ["json", "dataset"], "acceptance.gates", missing_acceptance_gate),
        ("identifier-missing-value", ["shacl"], "shacl.data", identifier_missing_value),
        ("mapping-wrong-endpoint-release", ["shacl", "dataset"], "shacl.data", wrong_endpoint_release),
        ("asserted-naked-mapping", ["shacl", "dataset", "reasoning"], "shacl.data", naked_asserted_mapping),
        ("derived-naked-mapping", ["dataset", "reasoning"], "dataset.graph-placement", naked_derived_mapping),
        ("asserted-auxiliary-type-only", ["dataset"], "dataset.graph-placement", auxiliary_type_only),
        ("asserted-untyped-statement", ["dataset"], "dataset.graph-placement", untyped_asserted_statement),
        ("evidence-retargeted", ["rdf", "dataset"], "dataset.evidence-identity", evidence_retargeted),
        ("evidence-reviewer-retargeted", ["rdf", "dataset"], "dataset.evidence-identity", evidence_reviewer_retargeted),
        ("policy-payload-changed", ["rdf", "dataset"], "dataset.assertion-identity", policy_payload_changed),
        ("supersession-old-still-current", ["dataset", "lifecycle"], "dataset.supersession", invalid_supersession_keeps_old_current),
        ("source-accounting-resource-swap", ["json", "dataset"], "source.accounting", source_accounting_swap),
        (
            "source-accounting-false-inverse",
            ["json", "rdf", "dataset"],
            "source.accounting",
            source_accounting_false_inverse,
        ),
        ("cross-role-identity", ["dataset", "reasoning"], "dataset.graph-placement", cross_role_identity),
        (
            "derived-asserted-scheme-collision",
            ["dataset", "reasoning"],
            "dataset.graph-placement",
            derived_asserted_scheme_collision,
        ),
        ("label-extra-skos-type", ["dataset", "rdf"], "dataset.graph-placement", label_extra_skos_type),
        ("scheme-assertion-property", ["shacl", "dataset"], "shacl.data", scheme_assertion_property),
        ("derived-input-digest", ["dataset", "reasoning"], "dataset.derived-input", wrong_derived_input_digest),
        ("derived-nonresource-endpoint", ["dataset", "reasoning"], "dataset.derived", wrong_derived_endpoint),
        ("profile-ring-mismatch", ["shacl", "dataset", "registry"], "profile.conformance", wrong_profile_ring),
        ("skosxl-label-role-overlap", ["shacl", "rdf"], "shacl.data", label_role_overlap),
        ("skos-mapping-conflict", ["shacl", "dataset", "reasoning"], "dataset.skos-integrity", skos_mapping_conflict),
        ("skos-mapping-reverse-conflict", ["dataset", "reasoning"], "dataset.skos-integrity", skos_mapping_reverse_conflict),
        ("skos-mapping-transitive-conflict", ["dataset", "reasoning"], "dataset.skos-integrity", skos_mapping_transitive_conflict),
        ("skos-mapping-hierarchy-conflict", ["dataset", "reasoning"], "dataset.skos-integrity", skos_mapping_hierarchy_conflict),
        ("skos-hierarchy-conflict", ["shacl", "dataset", "reasoning"], "dataset.skos-integrity", skos_hierarchy_conflict),
        ("assertion-extra-property", ["shacl", "dataset"], "shacl.data", assertion_extra_property),
        ("validator-identity-mismatch", ["json", "dataset"], "json.schema", wrong_validator_identity),
        ("subject-scheme-disagreement", ["shacl", "rdf"], "shacl.data", subject_scheme_disagreement),
        ("native-payload-noncanonical", ["rdf", "dataset"], "dataset.native-payload", noncanonical_native_payload),
    ]


def build(*, check: bool) -> None:
    output_root = FIXTURE_ROOT
    temporary_root = output_root.parent / ".atlas-3.0-fixtures.tmp"
    if temporary_root.exists():
        shutil.rmtree(temporary_root)
    (temporary_root / "valid").mkdir(parents=True)
    (temporary_root / "invalid").mkdir(parents=True)

    mutations = _mutations()
    corpus_cases: list[dict[str, Any]] = [
        {
            "expected": "valid",
            "id": "all-resource-profiles",
            "layers": ["json", "rdf", "shacl", "dataset", "reasoning", "registry"],
            "path": "valid/all-resource-profiles",
        }
    ]
    for name, layers, expected_or_issue, _ in mutations:
        expected = "valid" if expected_or_issue == "valid" else "invalid"
        row: dict[str, Any] = {
            "expected": expected,
            "id": name,
            "layers": layers,
            "path": f"{expected}/{name}",
        }
        if expected == "invalid":
            row["firstIssue"] = expected_or_issue
        corpus_cases.append(row)
    corpus = {
        "cases": sorted(corpus_cases, key=lambda row: row["id"]),
        "type": "AtlasConformanceCorpus",
        "version": "3.0",
    }
    corpus_bytes = atlas_validate.canonical_json_bytes(corpus)
    (temporary_root / "corpus.json").write_bytes(corpus_bytes)
    binding_digests = atlas_validate._binding_digests(
        content_overrides={Path("fixtures/corpus.json"): corpus_bytes}
    )

    base = _base_fixture()
    _write_case(
        temporary_root / "valid" / "all-resource-profiles",
        copy.deepcopy(base),
        binding_digests=binding_digests,
        distribution_id="urn:ref:atlas-fixture:distribution:all-resource-profiles",
    )
    for name, _, expected_or_issue, mutation in mutations:
        fixture = copy.deepcopy(base)
        mutation(fixture)
        if expected_or_issue == "valid":
            case_root = temporary_root / "valid" / name
            expected = "valid"
        else:
            case_root = temporary_root / "invalid" / name
            expected = "invalid"
        _write_case(
            case_root,
            fixture,
            binding_digests=binding_digests,
            distribution_id=f"urn:ref:atlas-fixture:distribution:{name}",
        )

    expected_files = {
        path.relative_to(temporary_root): path.read_bytes()
        for path in temporary_root.rglob("*")
        if path.is_file()
    }
    current_files = {
        path.relative_to(output_root): path.read_bytes()
        for path in output_root.rglob("*")
        if path.is_file()
    } if output_root.exists() else {}
    if check:
        shutil.rmtree(temporary_root)
        if current_files != expected_files:
            missing = sorted(str(path) for path in expected_files.keys() - current_files.keys())
            extra = sorted(str(path) for path in current_files.keys() - expected_files.keys())
            changed = sorted(
                str(path)
                for path in expected_files.keys() & current_files.keys()
                if expected_files[path] != current_files[path]
            )
            raise SystemExit(f"Atlas 3.0 fixtures differ; missing={missing}, extra={extra}, changed={changed}")
        return

    output_root.mkdir(parents=True, exist_ok=True)
    for generated_root in GENERATED_ROOTS:
        if generated_root.exists():
            shutil.rmtree(generated_root)
    for path in list(output_root.glob("corpus.json")):
        path.unlink()
    for source in sorted(temporary_root.rglob("*")):
        relative = source.relative_to(temporary_root)
        target = output_root / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.write_bytes(source.read_bytes())
    shutil.rmtree(temporary_root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    build(check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
