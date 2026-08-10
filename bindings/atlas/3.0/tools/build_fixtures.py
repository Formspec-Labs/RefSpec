"""Build the sealed Atlas 3.0 conformance corpus deterministically."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import validate as atlas_validate
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, SKOS, XSD

ATLAS = atlas_validate.ATLAS
RKAF = atlas_validate.RKAF
SKOSXL = atlas_validate.SKOSXL
FIXTURE_ROOT = atlas_validate.FIXTURE_ROOT
GENERATED_ROOTS = (FIXTURE_ROOT / "valid", FIXTURE_ROOT / "invalid")
REVIEWER = URIRef("urn:ref:agent:atlas-fixture-reviewer")
CREATED_AT = "2026-08-05T12:00:00+00:00"
CONSTRUCTION_PROFILE = "atlas-3-release-local-construction-v1"
CONSTRUCTION_RECEIPT_PROFILE = "atlas-3-authenticated-construction-summary-v1"
CONSTRUCTOR_PROFILE = (
    "atlas-3-source-and-evidence-backed-mapping-compiled-shacl-v1"
)
COMPACT_ROLE_ORDER = (
    "Release",
    "SourceRecord",
    "Resource",
    "Label",
    "Statement",
    "EvidenceBinding",
    "Identifier",
    "LifecycleEvent",
)
COMPACT_ROLE_COUNT_FIELDS = {
    "Resource": "resources",
    "Label": "labels",
    "Statement": "statements",
    "EvidenceBinding": "evidenceBindings",
    "SourceRecord": "sourceRecords",
    "Release": "releases",
    "Identifier": "identifiers",
    "LifecycleEvent": "lifecycleEvents",
}


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
    rdf_zstd_all: bool = False
    rdf_partition_owner: str | None = None
    # Set false by the three negatives whose whole point is a stale proof
    # digest; every other case is re-sealed after its mutation runs.
    reseal_adjudication: bool = True


@dataclass(frozen=True, slots=True)
class ConstructionUnit:
    key: str
    atlas_release: URIRef
    source_release: URIRef
    scheme: URIRef
    registry_source: URIRef
    ring: str
    resource_profile: str


def _add_registry_source(graph: Graph, scheme: URIRef, *, name: str) -> URIRef:
    source = URIRef(str(scheme) + ":source")
    graph.add((scheme, ATLAS.sourceDescriptor, source))
    if (source, RDF.type, ATLAS.RegistrySource) in graph:
        return source
    graph.add((source, RDF.type, ATLAS.RegistrySource))
    graph.add((source, DCTERMS.identifier, Literal(name)))
    graph.add((source, DCTERMS.title, Literal(f"Fixture source {name}")))
    graph.add((source, ATLAS.memberDisposition, Literal("memberRelease")))
    graph.add(
        (
            source,
            ATLAS.descriptorPayload,
            Literal(
                atlas_validate.canonical_json_bytes(
                    {"resourceId": name, "title": f"Fixture source {name}"},
                    terminal_lf=False,
                ).decode("utf-8"),
                datatype=RDF.JSON,
                normalize=False,
            ),
        )
    )
    return source


def _add_release(
    graph: Graph,
    *,
    name: str,
    profile: URIRef,
    ring: URIRef,
    resources: list[tuple[str, URIRef, str]],
    scheme: URIRef | None = None,
) -> tuple[URIRef, URIRef, URIRef, list[tuple[URIRef, URIRef]]]:
    scheme = scheme or URIRef(f"urn:ref:atlas-fixture:scheme:{name}")
    release = URIRef(f"urn:ref:atlas-fixture:release:{name}:2026")
    source_release = URIRef(f"urn:ref:atlas-fixture:source-release:{name}:2026")
    graph.add((scheme, RDF.type, ATLAS.ResourceScheme))
    _add_registry_source(graph, scheme, name=name)
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
    graph.add((release, RKAF.membershipMode, RKAF.completeMembership))
    graph.add((release, DCTERMS.identifier, Literal(name)))
    graph.add((release, DCTERMS.issued, Literal("2026-08-05", datatype=XSD.date)))
    graph.add((source_release, RDF.type, ATLAS.SourceRelease))
    graph.add((source_release, DCTERMS.identifier, Literal(f"fixture-{name}-2026")))
    graph.add((source_release, DCTERMS.issued, Literal("2026-08-05", datatype=XSD.date)))
    graph.add(
        (
            source_release,
            ATLAS.sourceDigest,
            Literal("sha256:" + hashlib.sha256(name.encode("utf-8")).hexdigest()),
        )
    )
    graph.add(
        (
            source_release,
            ATLAS.sourceLocator,
            URIRef(f"urn:ref:atlas-fixture:source-release-file:{name}"),
        )
    )

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

        native_payload_value = {"identifier": local_name, "label": label_text}
        native_payload_bytes = atlas_validate.canonical_native_json_bytes(native_payload_value)
        graph.add((source_record, RDF.type, ATLAS.SourceRecord))
        graph.add((source_record, ATLAS.inSourceRelease, source_release))
        graph.add((source_record, ATLAS.representsResource, resource))
        graph.add(
            (
                source_record,
                ATLAS.sourceDigest,
                # atlas:sourceDigest is sha256 over this record's own canonical
                # nativePayload bytes -- it must be derived from the same
                # payload emitted below, not from an unrelated fixture label.
                Literal("sha256:" + hashlib.sha256(native_payload_bytes).hexdigest()),
            )
        )
        graph.add((source_record, ATLAS.sourceLocator, URIRef(f"urn:ref:atlas-fixture:locator:{local_name}")))
        graph.add(
            (
                source_record,
                ATLAS.nativePayload,
                Literal(
                    native_payload_bytes.decode("utf-8"),
                    datatype=RDF.JSON,
                    normalize=False,
                ),
            )
        )
        result.append((resource, source_record))
    return release, scheme, source_release, result


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


def _add_effective_period(
    graph: Graph,
    *,
    start: str,
    end: str | None = None,
) -> URIRef:
    """Mint the rkaf:EffectivePeriod one dated assertion points at.

    Content-addressed on its own two facts, so two assertions stating the same
    period share one node rather than minting a second name for it. An omitted
    end is written as an absent predicate, never as an end equal to the start:
    upstream reads the omission as open-ended, and a zero-length period is a
    different claim.
    """

    basis: dict[str, str] = {"effectivePeriodStart": start}
    if end is not None:
        basis["effectivePeriodEnd"] = end
    digest = atlas_validate.canonical_sha256(basis)
    period = URIRef(
        "urn:ref:atlas-effective-period:" + digest.removeprefix("sha256:")
    )
    graph.add((period, RDF.type, RKAF.EffectivePeriod))
    graph.add(
        (
            period,
            RKAF.effectivePeriodStart,
            Literal(start, datatype=XSD.dateTime, normalize=False),
        )
    )
    if end is not None:
        graph.add(
            (
                period,
                RKAF.effectivePeriodEnd,
                Literal(end, datatype=XSD.dateTime, normalize=False),
            )
        )
    return period


def _add_assertion(
    graph: Graph,
    *,
    assertion_type: URIRef,
    ring: URIRef | None,
    subject: URIRef,
    predicate: URIRef,
    obj: URIRef,
    source_release: URIRef,
    target_release: URIRef,
    evidence_record: URIRef,
    evidence_name: str,
    policy: URIRef | None = None,
    asserted_at: str = CREATED_AT,
    supersedes: URIRef | None = None,
    review_warrant: str = "humanReview",
    source_ring: URIRef | None = None,
    target_ring: URIRef | None = None,
    adopted_evidence: URIRef | None = None,
    effective_period: tuple[str, str | None] | None = None,
) -> URIRef:
    if assertion_type == ATLAS.CrossRingRelationAssertion:
        if ring is not None or source_ring is None or target_ring is None:
            raise ValueError(
                "cross-ring assertions require source_ring and target_ring, not ring"
            )
    elif ring is None or source_ring is not None or target_ring is not None:
        raise ValueError("same-ring assertions require ring only")
    if review_warrant not in atlas_validate.EVIDENCE_WARRANTS:
        raise ValueError(f"unsupported review warrant: {review_warrant!r}")
    if review_warrant == "operatorAdoption" and adopted_evidence is None:
        raise ValueError("operatorAdoption warrant requires adopted_evidence")
    if review_warrant != "operatorAdoption" and adopted_evidence is not None:
        raise ValueError("adopted_evidence is only valid for operatorAdoption")
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
        "sourceRelease": str(source_release),
        "subject": str(subject),
        "targetRelease": str(target_release),
        "type": str(assertion_type),
    }
    if assertion_type == ATLAS.CrossRingRelationAssertion:
        basis["sourceRing"] = str(source_ring)
        basis["targetRing"] = str(target_ring)
    else:
        basis["semanticRing"] = str(ring)
    digest = atlas_validate.canonical_sha256(basis)
    assertion = URIRef("urn:ref:atlas-assertion:" + digest.removeprefix("sha256:"))
    graph.add((assertion, RDF.type, ATLAS.RelationAssertion))
    graph.add((assertion, RDF.type, assertion_type))
    if assertion_type == ATLAS.MappingAssertion and ring == ATLAS.subject:
        graph.add((assertion, RDF.type, ATLAS.SkosMappingAssertion))
    graph.add((assertion, RDF.subject, subject))
    graph.add((assertion, RDF.predicate, predicate))
    graph.add((assertion, RDF.object, obj))
    if assertion_type == ATLAS.CrossRingRelationAssertion:
        assert source_ring is not None and target_ring is not None
        graph.add((assertion, ATLAS.sourceRing, source_ring))
        graph.add((assertion, ATLAS.targetRing, target_ring))
    else:
        assert ring is not None
        graph.add((assertion, ATLAS.semanticRing, ring))
    graph.add((assertion, ATLAS.sourceRelease, source_release))
    graph.add((assertion, ATLAS.targetRelease, target_release))
    graph.add((assertion, ATLAS.governedByPolicy, policy))
    graph.add(
        (
            assertion,
            RKAF.assertedAt,
            Literal(asserted_at, datatype=XSD.dateTime, normalize=False),
        )
    )
    if supersedes is not None:
        graph.add((assertion, RKAF.supersedesAssertion, supersedes))
    if effective_period is not None:
        graph.add(
            (
                assertion,
                RKAF.hasEffectivePeriod,
                _add_effective_period(
                    graph,
                    start=effective_period[0],
                    end=effective_period[1],
                ),
            )
        )
    graph.add((assertion, ATLAS.assertionIdentityDigest, Literal(digest)))
    graph.add(
        (
            assertion,
            ATLAS.contentDigest,
            Literal(atlas_validate.rdf_node_digest(graph, assertion)),
        )
    )
    evidence = URIRef(f"urn:ref:atlas-evidence:pending:{evidence_name}")
    graph.add((evidence, RDF.type, RKAF.EvidenceBinding))
    graph.add((evidence, RKAF.bindsAssertion, assertion))
    graph.add((evidence, ATLAS.evidenceSourceRecord, evidence_record))
    graph.add((evidence, RKAF.attestor, REVIEWER))
    graph.add((evidence, RKAF.decision, RKAF.approved))
    for axis, value in zip(
        atlas_validate.EVIDENCE_WARRANT_AXES,
        atlas_validate.EVIDENCE_WARRANTS[review_warrant],
        strict=True,
    ):
        graph.add((evidence, axis, value))
    graph.add((evidence, RKAF.evidentiaryFunction, RKAF.supports))
    if adopted_evidence is not None:
        graph.add((evidence, RKAF.basedOnAttestation, adopted_evidence))
    graph.add(
        (
            evidence,
            RKAF.attestedAt,
            Literal(asserted_at, datatype=XSD.dateTime, normalize=False),
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


def _adjudication_iri(kind: str, *parts: str) -> URIRef:
    return URIRef(":".join(("urn:ref:atlas-fixture", kind, *parts)))


def _local_name(iri: URIRef) -> str:
    return str(iri).rsplit(":", 1)[-1]


def _refresh_proof_digest(graph: Graph, proof: URIRef) -> None:
    """Re-pin one proof record's own rkaf:proofRecordDigest.

    The digest excludes itself, exactly as atlas:contentDigest does on every
    other carrier; rkaf simply already had a name for it on a proof record.
    """

    _remove_subject_predicate(graph, proof, RKAF.proofRecordDigest)
    graph.add(
        (
            proof,
            RKAF.proofRecordDigest,
            Literal(atlas_validate.rdf_node_digest(graph, proof)),
        )
    )


def _add_artifact(
    graph: Graph,
    artifact: URIRef,
    *,
    identifiers: Sequence[str],
    digest: str,
) -> URIRef:
    """One immutable state, named and digest-addressed.

    This is what makes a sealed digest resolvable. Atlas 1.0 required the
    model's exact input to be present in the bundle as an artifact whose
    content digest equalled the declared one, and gave the reason: every other
    check compares the records to one another, so all of them can agree on a
    digest whose bytes exist nowhere.
    """

    if (artifact, RDF.type, RKAF.Artifact) in graph:
        return artifact
    graph.add((artifact, RDF.type, RKAF.Artifact))
    for identifier in identifiers:
        graph.add((artifact, RKAF.hasArtifactIdentifier, Literal(identifier)))
    graph.add((artifact, RKAF.artifactIdentifierScheme, RKAF["partner-defined"]))
    graph.add((artifact, RKAF.hasContentDigest, Literal(digest)))
    return artifact


def _endpoint_artifact(graph: Graph, endpoint: URIRef) -> URIRef:
    """The captured state of one compared Atlas resource.

    Identified by the resource it captures and digest-addressed to that
    resource's own atlas:contentDigest, which is the pair validate.py checks:
    a comparison cannot claim to have read an endpoint whose recorded content
    is something else.
    """

    return _add_artifact(
        graph,
        _adjudication_iri("artifact", "endpoint", _local_name(endpoint)),
        identifiers=[str(endpoint)],
        digest=str(graph.value(endpoint, ATLAS.contentDigest)),
    )


def _add_adjudication_machine(graph: Graph, key: str) -> URIRef:
    """One versioned proof issuer -- the validator actor and its provider.

    Two of the five independence axes live here rather than on the proof: the
    issuer IRI is the validator actor, and its rkaf:proofResolver is the
    provider, one hop coarser. Collapsing either is what the same-* negatives
    do. The resolver/policy version pair is upstream-required and is what makes
    two issuer records distinguishable when the resolver build is the same.
    """

    issuer = _adjudication_iri("proof-issuer", key)
    if (issuer, RDF.type, RKAF.ResolverProofIssuer) in graph:
        return issuer
    graph.add((issuer, RDF.type, RKAF.ResolverProofIssuer))
    graph.add((issuer, RKAF.proofResolver, _adjudication_iri("resolver", key)))
    graph.add((issuer, RKAF.proofResolverVersion, Literal("1.0.0")))
    graph.add((issuer, RKAF.proofPolicy, _adjudication_iri("policy", "relation-adjudication")))
    graph.add((issuer, RKAF.proofPolicyVersion, Literal("v1")))
    return issuer


def _add_adjudication_lineage(
    graph: Graph,
    lineage: URIRef,
    *,
    key: str,
    input_context_hash: str,
) -> URIRef:
    """The model derivation behind one adjudication call.

    One lineage per PROOF, not per model: rkaf:inputContextHash records the
    context this particular run read, and validate.py binds it to that proof's
    sealed request. The provider-model-id axis is rkaf:modelId, which stays
    keyed to the machine.
    """

    graph.add((lineage, RDF.type, RKAF.AILineage))
    graph.add((lineage, RKAF.modelId, Literal(f"{key}-adjudicator-2026-01")))
    graph.add((lineage, RKAF.modelVersion, Literal("2026.01.15")))
    graph.add(
        (lineage, RKAF.promptTemplateRef, _adjudication_iri("prompt-template", key, "v1"))
    )
    graph.add(
        (
            lineage,
            RKAF.temperature,
            Literal("0.0", datatype=XSD.decimal, normalize=False),
        )
    )
    graph.add((lineage, RKAF.inputContextHash, Literal(input_context_hash)))
    return lineage


def _sealed_request_digest(graph: Graph, assertion: URIRef) -> str:
    """The sealed question: which relation holds between these two endpoints.

    Equal digests mean two machines answered the IDENTICAL question, which is
    what makes them a corroborating pair rather than two answers to two
    questions. The digest is only trustworthy because a bundled rkaf:Artifact
    carries it as its own content digest.
    """

    return atlas_validate.canonical_sha256(
        {
            "object": str(graph.value(assertion, RDF.object)),
            "predicate": str(graph.value(assertion, RDF.predicate)),
            "subject": str(graph.value(assertion, RDF.subject)),
        }
    )


def _add_adjudication_proof(
    graph: Graph,
    *,
    comparison: URIRef,
    assertion: URIRef,
    name: str,
    key: str,
    verdict: URIRef,
    outcome: URIRef = None,
    request_artifact: URIRef | None = None,
) -> URIRef:
    """One machine's sealed answer to one comparison question."""

    outcome = outcome or RKAF.gatePass
    issuer = _add_adjudication_machine(graph, key)
    subject = graph.value(assertion, RDF.subject)
    obj = graph.value(assertion, RDF.object)
    baseline = _endpoint_artifact(graph, subject)
    observed = _endpoint_artifact(graph, obj)
    if request_artifact is None:
        request_artifact = _adjudication_iri("artifact", "request", name)
    request_digest = str(graph.value(request_artifact, RKAF.hasContentDigest))
    snapshot = str(graph.value(comparison, RKAF.comparisonSnapshot))

    proof = _adjudication_iri("proof", name, key)
    lineage = _add_adjudication_lineage(
        graph,
        _adjudication_iri("ai-lineage", name, key),
        key=key,
        input_context_hash=request_digest,
    )
    response = _add_artifact(
        graph,
        _adjudication_iri("artifact", "response", name, key),
        identifiers=[str(_adjudication_iri("artifact", "response", name, key))],
        digest="sha256:" + hashlib.sha256(f"{name}:{key}:response".encode("utf-8")).hexdigest(),
    )
    graph.add((proof, RDF.type, RKAF.ResolverProofRecord))
    graph.add((proof, RKAF.proofType, RKAF.machineAdjudicationProof))
    graph.add((proof, RKAF.proofIssuer, issuer))
    graph.add((proof, RKAF.proofComparisonContext, comparison))
    graph.add((proof, RKAF.proofOutcome, outcome))
    graph.add(
        (
            proof,
            RKAF.proofRationale,
            Literal(
                f"The {key} adjudicator read the sealed request and returned a "
                "deterministic verdict for the labelled concept pair."
            ),
        )
    )
    for input_artifact in sorted({baseline, observed, request_artifact}, key=str):
        graph.add((proof, RKAF.proofInput, input_artifact))
        graph.add(
            (
                proof,
                RKAF.proofInputDigest,
                Literal(str(graph.value(input_artifact, RKAF.hasContentDigest))),
            )
        )
    graph.add(
        (
            proof,
            RKAF.proofEvaluatedAt,
            Literal(CREATED_AT, datatype=XSD.dateTime, normalize=False),
        )
    )
    graph.add((proof, RKAF.proofSnapshot, Literal(snapshot)))
    graph.add((proof, RKAF.hasAILineage, lineage))
    graph.add((proof, RKAF.independenceGroup, _adjudication_iri("independence-group", key)))
    graph.add((proof, RKAF.adjudicationVerdict, verdict))
    graph.add((proof, RKAF.sealedRequestDigest, Literal(request_digest)))
    graph.add((proof, RKAF.sealedResponseArtifact, response))
    _refresh_proof_digest(graph, proof)
    graph.add((comparison, RKAF.comparisonProofRecord, proof))
    return proof


def _add_adjudication(
    graph: Graph,
    *,
    assertion: URIRef,
    name: str,
    machines: Sequence[tuple[str, URIRef]],
    outcome: URIRef = None,
    proof_outcome: URIRef = None,
) -> URIRef:
    """The comparison one mapping was run for, plus its complete support.

    ``outcome`` is rkaf:comparisonSatisfied for a comparison that LICENSES the
    mapping it names. Any other value makes this an audit record: a comparison
    that was run and did not license anything, which is the state a pinned
    outcome value made unrepresentable.
    """

    outcome = outcome or RKAF.comparisonSatisfied
    subject = graph.value(assertion, RDF.subject)
    obj = graph.value(assertion, RDF.object)
    comparison = _adjudication_iri("comparison", name)
    request_artifact = _add_artifact(
        graph,
        _adjudication_iri("artifact", "request", name),
        identifiers=[str(_adjudication_iri("artifact", "request", name))],
        digest=_sealed_request_digest(graph, assertion),
    )
    graph.add((comparison, RDF.type, RKAF.RelationComparisonContext))
    graph.add((comparison, RKAF.comparisonBaselineArtifact, _endpoint_artifact(graph, subject)))
    graph.add((comparison, RKAF.comparisonObservedArtifact, _endpoint_artifact(graph, obj)))
    graph.add((comparison, RKAF.comparisonExpectedAssertion, assertion))
    graph.add((comparison, RKAF.comparisonConsumer, _adjudication_iri("consumer", "atlas-search")))
    graph.add((comparison, RKAF.comparisonScope, _adjudication_iri("scope", "subject-ring")))
    graph.add(
        (
            comparison,
            RKAF.comparisonEvaluationTime,
            Literal(CREATED_AT, datatype=XSD.dateTime, normalize=False),
        )
    )
    graph.add((comparison, RKAF.comparisonPolicyVersion, Literal("machine-adjudication-v1")))
    graph.add(
        (comparison, RKAF.comparisonDetector, _adjudication_iri("detector", "relation-comparator"))
    )
    graph.add((comparison, RKAF.comparisonDetectorVersion, Literal("1.0.0")))
    graph.add(
        (
            comparison,
            RKAF.comparisonSnapshot,
            Literal(str(graph.value(assertion, ATLAS.targetRelease))),
        )
    )
    graph.add((comparison, RKAF.comparisonOutcome, outcome))
    for key, verdict in machines:
        _add_adjudication_proof(
            graph,
            comparison=comparison,
            assertion=assertion,
            name=name,
            key=key,
            verdict=verdict,
            outcome=proof_outcome,
            request_artifact=request_artifact,
        )
    return comparison


def _reseal_adjudication(graph: Graph) -> None:
    """Re-pin every endpoint artifact and proof digest to this graph.

    Called once per generated case so a mutation aimed at something else -- a
    relabelled resource, a re-sealed source record -- does not leave a stale
    input digest behind and turn an unrelated fixture into an adjudication
    failure. The negatives that tamper with exactly these fields opt out
    through ``Fixture.reseal_adjudication``.
    """

    for artifact in sorted(graph.subjects(RDF.type, RKAF.Artifact), key=str):
        endpoints = [
            URIRef(str(identifier))
            for identifier in graph.objects(artifact, RKAF.hasArtifactIdentifier)
            if (URIRef(str(identifier)), ATLAS.contentDigest, None) in graph
        ]
        if len(endpoints) != 1:
            continue
        _remove_subject_predicate(graph, artifact, RKAF.hasContentDigest)
        graph.add(
            (
                artifact,
                RKAF.hasContentDigest,
                Literal(str(graph.value(endpoints[0], ATLAS.contentDigest))),
            )
        )
    for proof in sorted(graph.subjects(RDF.type, RKAF.ResolverProofRecord), key=str):
        _remove_subject_predicate(graph, proof, RKAF.proofInputDigest)
        for input_artifact in sorted(graph.objects(proof, RKAF.proofInput), key=str):
            digest = graph.value(input_artifact, RKAF.hasContentDigest)
            if digest is not None:
                graph.add((proof, RKAF.proofInputDigest, Literal(str(digest))))
        _refresh_proof_digest(graph, proof)


def _assertions_by_record(asserted: Graph) -> dict[str, list[str]]:
    """Group each source record's evidence-bound assertions, sorted."""

    grouped: dict[str, set[str]] = defaultdict(set)
    for evidence in asserted.subjects(RDF.type, RKAF.EvidenceBinding):
        record = asserted.value(evidence, ATLAS.evidenceSourceRecord)
        assertion = asserted.value(evidence, RKAF.bindsAssertion)
        if record is not None and assertion is not None:
            grouped[str(record)].add(str(assertion))
    return {record: sorted(values) for record, values in grouped.items()}


def _base_fixture() -> Fixture:
    asserted = Graph()
    derived = Graph()
    _add_policy(asserted, version="1")

    subject_a_release, subject_a_scheme, _subject_a_source_release, subject_a_rows = _add_release(
        asserted,
        name="subject-a",
        profile=ATLAS.conceptScheme,
        ring=ATLAS.subject,
        resources=[
            ("subject-a", ATLAS.SubjectConcept, "Administrative law"),
            ("subject-a-child", ATLAS.SubjectConcept, "Agency procedure"),
        ],
    )
    subject_b_release, subject_b_scheme, _subject_b_source_release, subject_b_rows = _add_release(
        asserted,
        name="subject-b",
        profile=ATLAS.conceptScheme,
        ring=ATLAS.subject,
        resources=[("subject-b", ATLAS.SubjectConcept, "Administrative law")],
    )
    subject_c_release, subject_c_scheme, subject_c_source_release, subject_c_rows = _add_release(
        asserted,
        name="subject-c",
        profile=ATLAS.conceptScheme,
        ring=ATLAS.subject,
        resources=[("subject-c", ATLAS.SubjectConcept, "Administrative law")],
    )
    value_release, value_scheme, _value_source_release, value_rows = _add_release(
        asserted,
        name="values",
        profile=ATLAS.codeScheme,
        ring=ATLAS.value,
        resources=[
            ("value-parent", ATLAS.ValueResource, "Rulemaking"),
            ("value-child", ATLAS.ValueResource, "Proposed rule"),
        ],
    )
    entity_release, entity_scheme, entity_source_release, entity_rows = _add_release(
        asserted,
        name="entities",
        profile=ATLAS.identifierScheme,
        ring=ATLAS.entity,
        resources=[("entity-agency", ATLAS.EntityResource, "Example Agency")],
    )
    legal_release, legal_scheme, legal_source_release, legal_rows = _add_release(
        asserted,
        name="legal-structure",
        profile=ATLAS.structureScheme,
        ring=ATLAS.legalIdentity,
        resources=[("legal-title", ATLAS.LegalIdentityResource, "Example Code title")],
    )
    # The recodification the legal-identity mapping below spans. A legal
    # identity equivalence needs two codifications to hold between, and it is
    # the pair -- not the concept -- that the effective instant dates.
    (
        legal_b_release,
        legal_b_scheme,
        _legal_b_source_release,
        legal_b_rows,
    ) = _add_release(
        asserted,
        name="legal-structure-recodified",
        profile=ATLAS.structureScheme,
        ring=ATLAS.legalIdentity,
        resources=[
            (
                "legal-title-recodified",
                ATLAS.LegalIdentityResource,
                "Example Code title (recodified)",
            )
        ],
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
    (
        mixed_code_value_release,
        _mixed_code_value_scheme,
        _mixed_code_value_source_release,
        mixed_code_value_rows,
    ) = _add_release(
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
    _add_registry_source(asserted, collection_scheme, name="fixture-collection")
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
        legal_b_scheme,
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
    mixed_code_value, _source_mixed_code_value = mixed_code_value_rows[0]
    legal, source_legal = legal_rows[0]
    legal_recodified, _source_legal_recodified = legal_b_rows[0]

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
        review_warrant="publisherAssertion",
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
        review_warrant="twoMachineAdjudication",
    )
    exact_ab_evidence = next(asserted.subjects(RKAF.bindsAssertion, exact_ab))
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
        review_warrant="operatorAdoption",
        adopted_evidence=exact_ab_evidence,
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
        review_warrant="deterministicTransformation",
    )
    # The two rings whose mappings are claims about a period, one with each
    # shape rkaf:EffectivePeriod admits. The value crosswalk closes its period,
    # because a code edition stops being current; the legal-identity equivalence
    # leaves the end off, because the recodification took effect and nothing
    # says it ever stops. Both endpoint pairs also pin two distinct releases,
    # which is where the edition each side of the crosswalk belongs -- see the
    # ring-temporal block in ontology/atlas.ttl for why no edition literal
    # rides beside them.
    _add_assertion(
        asserted,
        assertion_type=ATLAS.MappingAssertion,
        ring=ATLAS.value,
        subject=value_child,
        predicate=ATLAS.equivalentValue,
        obj=mixed_code_value,
        source_release=value_release,
        target_release=mixed_code_value_release,
        evidence_record=source_value_child,
        evidence_name="value-crosswalk",
        review_warrant="publisherAssertion",
        effective_period=("2026-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00"),
    )
    _add_assertion(
        asserted,
        assertion_type=ATLAS.MappingAssertion,
        ring=ATLAS.legalIdentity,
        subject=legal,
        predicate=ATLAS.sameLegalIdentityAs,
        obj=legal_recodified,
        source_release=legal_release,
        target_release=legal_b_release,
        evidence_record=source_legal,
        evidence_name="legal-identity-recodification",
        review_warrant="publisherAssertion",
        effective_period=("2026-07-01T00:00:00+00:00", None),
    )
    _add_assertion(
        asserted,
        assertion_type=ATLAS.SourceAssignment,
        ring=ATLAS.subject,
        subject=source_c,
        predicate=ATLAS.assignedSubject,
        obj=subject_c,
        source_release=subject_c_source_release,
        target_release=subject_c_release,
        evidence_record=source_c,
        evidence_name="assignment-subject",
        review_warrant="trustedPipelineReview",
    )
    _add_assertion(
        asserted,
        assertion_type=ATLAS.SourceAssignment,
        ring=ATLAS.entity,
        subject=entity_rows[0][1],
        predicate=ATLAS.assignedEntity,
        obj=entity,
        source_release=entity_source_release,
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
        source_release=legal_source_release,
        target_release=legal_release,
        evidence_record=source_legal,
        evidence_name="assignment-legal",
    )
    _add_assertion(
        asserted,
        assertion_type=ATLAS.CrossRingRelationAssertion,
        ring=None,
        source_ring=ATLAS.entity,
        target_ring=ATLAS.subject,
        subject=entity,
        predicate=ATLAS.hasIndexedSubject,
        obj=subject_a,
        source_release=entity_release,
        target_release=subject_a_release,
        evidence_record=entity_rows[0][1],
        evidence_name="entity-indexed-subject",
        review_warrant="publisherAssertion",
    )
    _add_assertion(
        asserted,
        assertion_type=ATLAS.CrossRingRelationAssertion,
        ring=None,
        source_ring=ATLAS.legalIdentity,
        target_ring=ATLAS.subject,
        subject=legal,
        predicate=ATLAS.hasIndexedSubject,
        obj=subject_a,
        source_release=legal_release,
        target_release=subject_a_release,
        evidence_record=source_legal,
        evidence_name="legal-indexed-subject",
        review_warrant="publisherAssertion",
    )
    _add_assertion(
        asserted,
        assertion_type=ATLAS.CrossRingRelationAssertion,
        ring=None,
        source_ring=ATLAS.entity,
        target_ring=ATLAS.legalIdentity,
        subject=entity,
        predicate=ATLAS.referencesLegalIdentity,
        obj=legal,
        source_release=entity_release,
        target_release=legal_release,
        evidence_record=entity_rows[0][1],
        evidence_name="entity-references-legal",
        review_warrant="publisherAssertion",
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
            RKAF.inputDigest,
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

    # The base graph carries no lifecycle event. It used to carry an
    # "urn:ref:atlas-event:admitted" one, and nothing in the binding could
    # reject any IRI a producer put there: atlas:eventType had no rdfs:range
    # and no sh:in. rkaf:lifecycleEventKind is closed to the two kinds Atlas
    # acts on, and "admitted" is neither, so the event is gone rather than
    # relabelled. Lifecycle events now appear exactly where they change what a
    # consumer sees -- rescission-lifecycle and superseded-policy-revision.

    digest_classes = {
        ATLAS.RegistrySource,
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
        RKAF.EvidenceBinding,
        ATLAS.EditorialPolicy,
        RKAF.LifecycleEvent,
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

    # The machine-adjudication proof set for the one mapping whose evidence
    # declares the twoMachineAdjudication warrant. It is built here, after every
    # resource digest exists, because each proof pins the exact content of the
    # two endpoints it read. Two machines is the minimum an independent pair
    # needs; valid/qualified-three-machine-support adds a third and keeps all
    # three, which is the rule this binding corrected from "exactly two".
    _add_adjudication(
        asserted,
        assertion=exact_ab,
        name="exact-ab",
        machines=(("alpha", RKAF.verdictSame), ("beta", RKAF.verdictSame)),
    )

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
    assertions_by_record = _assertions_by_record(asserted)
    source_records = sorted(str(row) for row in asserted.subjects(RDF.type, ATLAS.SourceRecord))
    records_by_release: dict[str, list[str]] = defaultdict(list)
    for record in source_records:
        source_release = asserted.value(URIRef(record), ATLAS.inSourceRelease)
        if not isinstance(source_release, URIRef):
            raise TypeError(f"fixture source record {record} has no source release")
        records_by_release[str(source_release)].append(record)

    def _disposition(record: str) -> dict[str, Any]:
        row: dict[str, Any] = {
            "atlasResources": sorted(resource_by_record[record]),
            "sourceRecord": record,
            "status": "represented",
        }
        assertions = assertions_by_record.get(record, [])
        if assertions:
            row["atlasAssertions"] = assertions
        return row

    accounting_inputs = []
    for source_release, release_records in sorted(records_by_release.items()):
        dispositions = [_disposition(record) for record in sorted(release_records)]
        accounting_inputs.append(
            {
                "declaredMemberCount": len(dispositions),
                "dispositions": dispositions,
                "membershipMode": "complete",
                "sourceRelease": source_release,
            }
        )
    accounting = {
        "distributionId": "urn:ref:atlas-fixture:distribution:all-resource-profiles",
        "inputs": accounting_inputs,
        "totals": {
            "excluded": 0,
            "represented": len(source_records),
            "sourceRecords": len(source_records),
            "sourceReleases": len(accounting_inputs),
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


def _validator_rejects(term: Any) -> bool:
    """Return whether the strict validator would refuse to render this term.

    Used only so a deliberately invalid conformance fixture (a forbidden blank
    node, a credential-bearing IRI) can reach disk in its intended
    non-conforming form for the validator to independently discover and
    reject. Every term in an unmutated fixture passes cleanly and takes the
    canonical `nquads_line` path below.
    """

    try:
        atlas_validate.ntriples_term(term)
    except atlas_validate.AtlasValidationError:
        return True
    return False


def _nquad_line(triple: tuple[Any, Any, Any], graph_id: URIRef) -> str:
    subject, predicate, obj = triple
    try:
        return atlas_validate.nquads_line(subject, predicate, obj, graph_id)
    except atlas_validate.AtlasValidationError:
        # Only a case built to be refused gets here, and only its own invalid
        # terms fall back to rdflib's rendering; every other term in the line
        # is still written in the canonical form.
        rendered = [
            term.n3() if _validator_rejects(term) else atlas_validate.ntriples_term(term)
            for term in (subject, predicate, obj, graph_id)
        ]
        return " ".join((*rendered, "."))


def _counts(fixture: Fixture) -> dict[str, int]:
    asserted = fixture.asserted
    return {
        "crossRingRelationAssertions": len(
            set(asserted.subjects(RDF.type, ATLAS.CrossRingRelationAssertion))
        ),
        "derivedRelations": len(set(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))),
        "identifiers": len(set(asserted.subjects(RDF.type, ATLAS.Identifier))),
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


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _atlas_name(value: URIRef) -> str:
    iri = str(value)
    namespace = str(ATLAS)
    if not iri.startswith(namespace) or len(iri) == len(namespace):
        raise ValueError(f"fixture value is not an Atlas term: {value}")
    return iri[len(namespace) :]


def _construction_units(graph: Graph) -> tuple[ConstructionUnit, ...]:
    units: list[ConstructionUnit] = []
    for atlas_release in sorted(
        graph.subjects(RDF.type, ATLAS.AtlasRelease), key=str
    ):
        identifier = graph.value(atlas_release, DCTERMS.identifier)
        scheme = graph.value(atlas_release, ATLAS.inScheme)
        ring = graph.value(atlas_release, ATLAS.semanticRing)
        profile = graph.value(atlas_release, ATLAS.resourceProfile)
        if (
            not isinstance(identifier, Literal)
            or not isinstance(scheme, URIRef)
            or not isinstance(ring, URIRef)
            or not isinstance(profile, URIRef)
        ):
            raise TypeError(f"fixture Atlas release is incomplete: {atlas_release}")
        source_releases = {
            source_release
            for resource in graph.objects(atlas_release, PROV.hadMember)
            for source_record in graph.objects(resource, ATLAS.sourceRecord)
            for source_release in graph.objects(source_record, ATLAS.inSourceRelease)
            if isinstance(source_release, URIRef)
        }
        registry_sources = {
            source
            for source in graph.objects(scheme, ATLAS.sourceDescriptor)
            if isinstance(source, URIRef)
        }
        if len(source_releases) != 1 or len(registry_sources) != 1:
            raise ValueError(
                f"fixture release {atlas_release} does not resolve to one source release and registry source"
            )
        units.append(
            ConstructionUnit(
                key=f"source-{identifier}",
                atlas_release=atlas_release,
                source_release=next(iter(source_releases)),
                scheme=scheme,
                registry_source=next(iter(registry_sources)),
                ring=_atlas_name(ring),
                resource_profile=_atlas_name(profile),
            )
        )
    units.sort(key=lambda unit: unit.key)
    if len({unit.key for unit in units}) != len(units):
        raise ValueError("fixture construction unit keys are not unique")
    return tuple(units)


def _unit_owner_maps(
    units: Sequence[ConstructionUnit],
) -> tuple[dict[URIRef, str], dict[URIRef, str]]:
    return (
        {unit.atlas_release: unit.key for unit in units},
        {unit.source_release: unit.key for unit in units},
    )


def _record_role(graph: Graph, subject: URIRef) -> str | None:
    return atlas_validate._construction_record_role_or_none(graph, subject)


def _logical_owner(
    graph: Graph,
    subject: URIRef,
    role: str,
    *,
    atlas_owner: Mapping[URIRef, str],
    source_owner: Mapping[URIRef, str],
) -> str | None:
    def iri(predicate: URIRef) -> URIRef | None:
        value = graph.value(subject, predicate)
        return value if isinstance(value, URIRef) else None

    if role in {"Resource", "Label"}:
        return atlas_owner.get(iri(ATLAS.inRelease))
    if role == "SourceRecord":
        return source_owner.get(iri(ATLAS.inSourceRelease))
    if role == "Release":
        if (subject, RDF.type, ATLAS.SourceRelease) in graph:
            return source_owner.get(subject)
        return atlas_owner.get(subject)
    if role == "Identifier":
        resource = iri(ATLAS.identifies)
        release = graph.value(resource, ATLAS.inRelease) if resource is not None else None
        return atlas_owner.get(release) if isinstance(release, URIRef) else None
    if role == "EvidenceBinding":
        source_record = iri(ATLAS.evidenceSourceRecord)
        source_release = (
            graph.value(source_record, ATLAS.inSourceRelease)
            if source_record is not None
            else None
        )
        return source_owner.get(source_release) if isinstance(source_release, URIRef) else None
    if role == "Statement":
        bindings = [
            binding
            for binding in graph.subjects(RKAF.bindsAssertion, subject)
            if isinstance(binding, URIRef)
        ]
        if len(bindings) == 1:
            source_record = graph.value(bindings[0], ATLAS.evidenceSourceRecord)
            if isinstance(source_record, URIRef):
                source_release = graph.value(source_record, ATLAS.inSourceRelease)
                if isinstance(source_release, URIRef) and source_release in source_owner:
                    return source_owner[source_release]
        endpoint_release = iri(ATLAS.sourceRelease)
        if endpoint_release is not None:
            return atlas_owner.get(endpoint_release) or source_owner.get(endpoint_release)
        return None
    if role == "LifecycleEvent":
        owners = {
            source_owner[source_release]
            for source_record in graph.objects(subject, ATLAS.sourceRecord)
            for source_release in graph.objects(source_record, ATLAS.inSourceRelease)
            if isinstance(source_release, URIRef) and source_release in source_owner
        }
        return next(iter(owners)) if len(owners) == 1 else None
    return None


def _rdf_pack(
    *,
    path: str,
    kind: str,
    lines: Sequence[str],
    graph_counts: Mapping[str, int],
    source_releases: Sequence[str] = (),
    rings: Sequence[str] = (),
    compression: str = "none",
    partition: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], bytes]:
    payload = ("\n".join(sorted(lines)) + "\n").encode("utf-8")
    digest = _sha256(payload)
    if compression == "none":
        transport_bytes = payload
        transport = {
            "byteLength": len(payload),
            "compression": "none",
            "digest": digest,
            "mediaType": "application/n-quads",
        }
    elif compression == "zstd":
        transport_bytes = atlas_validate.zstd.compress(payload)
        transport = {
            "byteLength": len(transport_bytes),
            "compression": "zstd",
            "digest": _sha256(transport_bytes),
            "mediaType": "application/zstd",
        }
        path = path + ".zst"
    else:
        raise ValueError(f"unsupported rdf pack compression: {compression!r}")
    pack = {
        "content": {
            "byteLength": len(payload),
            "digest": digest,
            "mediaType": "application/n-quads",
            "quadCount": len(lines),
        },
        "dependencies": [],
        "graphCounts": dict(graph_counts),
        "kind": kind,
        "packId": "urn:ref:atlas:pack:" + digest.removeprefix("sha256:"),
        "path": path,
        "rings": sorted(rings),
        "sourceReleases": sorted(source_releases),
        "transport": transport,
    }
    if partition is not None:
        pack["partition"] = dict(partition)
    return pack, transport_bytes


def _partition_triples_by_subject(
    triples: Sequence[tuple[Any, Any, Any]],
) -> list[tuple[str, list[tuple[Any, Any, Any]]]]:
    """Split one pack's triples into >=2 buckets keyed by a real, shared
    sha256(subject IRI) hex prefix -- long enough that every subject in a
    bucket actually starts with that prefix (never a synthetic label)."""

    subjects = sorted({subject for subject, _, _ in triples}, key=str)
    if len(subjects) < 2:
        raise ValueError("cannot partition an RDF pack with fewer than two subjects")
    digests = {
        subject: hashlib.sha256(str(subject).encode("utf-8")).hexdigest()
        for subject in subjects
    }
    prefix_len = 1
    buckets: dict[str, list[Any]] = defaultdict(list)
    while prefix_len <= 8:
        buckets = defaultdict(list)
        for subject in subjects:
            buckets[digests[subject][:prefix_len]].append(subject)
        if len(buckets) > 1:
            break
        prefix_len += 1
    else:
        raise ValueError("subjects share a sha256 prefix through 8 hex characters")
    subject_bucket = {
        subject: prefix
        for prefix, bucket_subjects in buckets.items()
        for subject in bucket_subjects
    }
    grouped: dict[str, list[tuple[Any, Any, Any]]] = defaultdict(list)
    for triple in triples:
        grouped[subject_bucket[triple[0]]].append(triple)
    return sorted(grouped.items())


def _write_rdf_packs(
    root: Path,
    fixture: Fixture,
    units: Sequence[ConstructionUnit],
    *,
    distribution_id: str,
    zstd_all: bool = False,
    partition_owner: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    graph_ids = {
        "asserted": URIRef(distribution_id + ":asserted"),
        "projection": URIRef(distribution_id + ":projection"),
        "derived": URIRef(distribution_id + ":derived"),
    }
    atlas_owner, source_owner = _unit_owner_maps(units)
    asserted_subject_owner: dict[Any, str] = {}
    asserted_groups: dict[str, list[tuple[Any, Any, Any]]] = defaultdict(list)
    for subject in set(fixture.asserted.subjects()):
        owner = "catalog"
        if isinstance(subject, URIRef):
            role = _record_role(fixture.asserted, subject)
            if role is not None:
                owner = _logical_owner(
                    fixture.asserted,
                    subject,
                    role,
                    atlas_owner=atlas_owner,
                    source_owner=source_owner,
                ) or "catalog"
        asserted_subject_owner[subject] = owner
        asserted_groups[owner].extend(fixture.asserted.triples((subject, None, None)))

    unit_by_key = {unit.key: unit for unit in units}
    compression = "zstd" if zstd_all else "none"
    # (pack, payload, owner, triples) -- "triples" is the exact set of
    # asserted triples physically written into this pack, which is what lets
    # dependency computation below work uniformly whether or not an owner's
    # facts were split across more than one partitioned pack.
    packs_with_payloads: list[
        tuple[dict[str, Any], bytes, str, list[tuple[Any, Any, Any]]]
    ] = []
    for owner in sorted(asserted_groups):
        triples = asserted_groups[owner]
        if owner == "catalog":
            base_path = "packs/rdf/catalog.nq"
            kind = "catalog"
            source_releases: list[str] = []
            rings: list[str] = []
        else:
            unit = unit_by_key[owner]
            base_path = f"packs/rdf/{owner}.nq"
            kind = "sourceRelease"
            source_releases = [str(unit.source_release)]
            rings = [unit.ring]

        if owner == partition_owner:
            for bucket_prefix, bucket_triples in _partition_triples_by_subject(triples):
                lines = [_nquad_line(triple, graph_ids["asserted"]) for triple in bucket_triples]
                pack, payload = _rdf_pack(
                    path=f"packs/rdf/{owner}.{bucket_prefix}.nq",
                    kind=kind,
                    lines=lines,
                    graph_counts={"asserted": len(lines), "projection": 0, "derived": 0},
                    source_releases=source_releases,
                    rings=rings,
                    compression=compression,
                    partition={"strategy": "sha256-subject-iri-prefix", "prefix": bucket_prefix},
                )
                packs_with_payloads.append((pack, payload, owner, bucket_triples))
        else:
            lines = [_nquad_line(triple, graph_ids["asserted"]) for triple in triples]
            pack, payload = _rdf_pack(
                path=base_path,
                kind=kind,
                lines=lines,
                graph_counts={"asserted": len(lines), "projection": 0, "derived": 0},
                source_releases=source_releases,
                rings=rings,
                compression=compression,
            )
            packs_with_payloads.append((pack, payload, owner, triples))

    view_lines = [
        *(_nquad_line(triple, graph_ids["projection"]) for triple in fixture.projection),
        *(_nquad_line(triple, graph_ids["derived"]) for triple in fixture.derived),
    ]
    if view_lines:
        view_pack, view_payload = _rdf_pack(
            path="packs/rdf/view.nq",
            kind="view",
            lines=view_lines,
            graph_counts={
                "asserted": 0,
                "projection": len(fixture.projection),
                "derived": len(fixture.derived),
            },
            compression=compression,
        )
        packs_with_payloads.append((view_pack, view_payload, "view", []))

    subject_pack_id: dict[Any, str] = {}
    for pack, _, owner, triples in packs_with_payloads:
        if owner == "view":
            continue
        for subject, _, _ in triples:
            subject_pack_id[subject] = pack["packId"]
    missing = sorted(
        (str(subject) for subject in asserted_subject_owner if subject not in subject_pack_id),
    )
    if missing:
        raise ValueError(f"fixture subjects have no RDF pack: {missing}")

    for pack, _, owner, triples in packs_with_payloads:
        if owner == "view":
            continue
        dependencies = {
            subject_pack_id[obj]
            for _, _, obj in triples
            if isinstance(obj, URIRef)
            and subject_pack_id.get(obj) is not None
            and subject_pack_id[obj] != pack["packId"]
        }
        pack["dependencies"] = sorted(dependencies)

    packs = [pack for pack, _, _, _ in packs_with_payloads]
    asserted_inventory = atlas_validate._graph_inventory_digest(packs, "asserted")
    asserted_pack_ids = sorted(
        pack["packId"] for pack in packs if pack["graphCounts"]["asserted"]
    )
    for pack in packs:
        if pack["kind"] == "view":
            pack["dependencies"] = asserted_pack_ids
            pack["inputAssertedDigest"] = asserted_inventory
    packs.sort(key=lambda pack: pack["packId"])
    graph_rows = [
        {
            "id": str(graph_ids[role]),
            "inventoryDigest": atlas_validate._graph_inventory_digest(packs, role),
            "packCount": sum(bool(pack["graphCounts"][role]) for pack in packs),
            "quadCount": sum(pack["graphCounts"][role] for pack in packs),
            "role": role,
        }
        for role in ("asserted", "projection", "derived")
    ]
    for pack, payload, _, _ in packs_with_payloads:
        target = root / pack["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    rdf_by_unit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pack, _, owner, _ in packs_with_payloads:
        if owner in {"catalog", "view"}:
            continue
        rdf_by_unit[owner].append(pack)
    for owner_packs in rdf_by_unit.values():
        owner_packs.sort(key=lambda pack: pack["path"])
    return packs, graph_rows, dict(rdf_by_unit)


def _compact_logical_rows(
    fixture: Fixture,
    baseline: Graph,
    units: Sequence[ConstructionUnit],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    atlas_owner, source_owner = _unit_owner_maps(units)
    baseline_units = _construction_units(baseline)
    baseline_atlas_owner, baseline_source_owner = _unit_owner_maps(baseline_units)
    markers = {
        "Resource": ATLAS.AtlasResource,
        "Label": SKOSXL.Label,
        "Statement": ATLAS.RelationAssertion,
        "EvidenceBinding": RKAF.EvidenceBinding,
        "SourceRecord": ATLAS.SourceRecord,
        "Release": (ATLAS.AtlasRelease, ATLAS.SourceRelease),
        "Identifier": ATLAS.Identifier,
        "LifecycleEvent": RKAF.LifecycleEvent,
    }
    expected = {
        "Resource": len(set(fixture.asserted.subjects(RDF.type, ATLAS.AtlasResource))),
        "Label": len(set(fixture.asserted.subjects(RDF.type, SKOSXL.Label))),
        "Statement": _counts(fixture)["relationAssertions"],
        "EvidenceBinding": _counts(fixture)["relationAssertions"],
        "SourceRecord": _counts(fixture)["sourceRecords"],
        "Release": len(set(fixture.asserted.subjects(RDF.type, ATLAS.AtlasRelease)))
        + len(set(fixture.asserted.subjects(RDF.type, ATLAS.SourceRelease))),
        "Identifier": _counts(fixture)["identifiers"],
        "LifecycleEvent": len(set(fixture.asserted.subjects(RDF.type, RKAF.LifecycleEvent))),
    }
    rows_by_owner_role: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen_by_role: dict[str, set[URIRef]] = defaultdict(set)

    def subjects(graph: Graph, role: str) -> set[URIRef]:
        marker = markers[role]
        values = (
            {subject for item in marker for subject in graph.subjects(RDF.type, item)}
            if isinstance(marker, tuple)
            else set(graph.subjects(RDF.type, marker))
        )
        return {subject for subject in values if isinstance(subject, URIRef)}

    def append_row(graph: Graph, subject: URIRef, role: str, *, fallback: bool) -> bool:
        try:
            row = atlas_validate._construction_record_from_rdf(graph, subject, role)
        except atlas_validate.AtlasValidationError:
            return False
        owner = _logical_owner(
            graph,
            subject,
            role,
            atlas_owner=baseline_atlas_owner if fallback else atlas_owner,
            source_owner=baseline_source_owner if fallback else source_owner,
        )
        if owner is None:
            return False
        rows_by_owner_role[(owner, role)].append(row)
        seen_by_role[role].add(subject)
        return True

    for role in COMPACT_ROLE_ORDER:
        for subject in sorted(subjects(fixture.asserted, role), key=str):
            if append_row(fixture.asserted, subject, role, fallback=False):
                continue
            if subject in subjects(baseline, role):
                append_row(baseline, subject, role, fallback=True)
        if len(seen_by_role[role]) < expected[role]:
            for subject in sorted(subjects(baseline, role) - seen_by_role[role], key=str):
                if append_row(baseline, subject, role, fallback=True) and len(
                    seen_by_role[role]
                ) == expected[role]:
                    break
        if len(seen_by_role[role]) != expected[role]:
            raise ValueError(
                f"fixture compact {role} rows differ: expected {expected[role]}, found {len(seen_by_role[role])}"
            )
    for rows in rows_by_owner_role.values():
        rows.sort(key=lambda row: row["id"])
    return dict(rows_by_owner_role)


def _write_compact_packs(
    root: Path,
    rows_by_owner_role: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    descriptors: list[dict[str, Any]] = []
    path_owners: dict[str, str] = {}
    subject_pack_ids: dict[str, str] = {}
    all_subjects = {
        row["id"]
        for rows in rows_by_owner_role.values()
        for row in rows
    }
    for role in COMPACT_ROLE_ORDER:
        for owner in sorted(
            key_owner
            for key_owner, key_role in rows_by_owner_role
            if key_role == role
        ):
            rows = [dict(row) for row in rows_by_owner_role[(owner, role)]]
            row_ids = {row["id"] for row in rows}
            dependency_ids: set[str] = set()
            for row in rows:
                for dependency_subject in atlas_validate._compact_direct_dependency_subjects(
                    role, row
                ):
                    if dependency_subject in row_ids or dependency_subject not in all_subjects:
                        continue
                    dependency_pack_id = subject_pack_ids.get(dependency_subject)
                    if dependency_pack_id is None:
                        raise ValueError(
                            f"compact fixture build order missed {dependency_subject} for {role}"
                        )
                    dependency_ids.add(dependency_pack_id)
            dependencies = sorted(dependency_ids)
            summary = atlas_validate._compact_full_summary(role, rows)
            summary_receipt = atlas_validate._compact_summary_receipt(summary)
            header = {
                "defaults": {},
                "dependencies": dependencies,
                "globalInvariantSummaryDigest": summary_receipt["digest"],
                "recordSchemaVersion": "1.0",
                "role": role,
                "schemaVersion": "1.0",
                "type": "AtlasCompactPackHeader",
            }
            row_bytes = [atlas_validate._compact_canonical_json_bytes(row) for row in rows]
            content = atlas_validate._compact_canonical_json_bytes(header) + b"".join(row_bytes)
            content_digest = _sha256(content)
            transport = atlas_validate.zstd.compress(content)
            path = f"packs/compact/{owner}/{role.lower()}.jsonl.zst"
            descriptor = {
                "content": {
                    "byteLength": len(content),
                    "digest": content_digest,
                    "mediaType": "application/x-ndjson",
                    "recordCount": len(rows),
                },
                "defaults": {},
                "dependencies": dependencies,
                "globalInvariantSummary": summary_receipt,
                "logicalRowsDigest": _sha256(b"".join(row_bytes)),
                "packId": "urn:ref:atlas:compact-pack:"
                + content_digest.removeprefix("sha256:"),
                "path": path,
                "recordSchemaVersion": "1.0",
                "role": role,
                "transport": {
                    "byteLength": len(transport),
                    "compression": "zstd",
                    "digest": _sha256(transport),
                    "mediaType": "application/zstd",
                },
            }
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(transport)
            descriptors.append(descriptor)
            path_owners[path] = owner
            for row in rows:
                subject_pack_ids[row["id"]] = descriptor["packId"]
    descriptors.sort(key=lambda descriptor: descriptor["path"])
    return descriptors, path_owners


def _file_pin(path: Path, *, logical_path: str, role: str, source_iri: str) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "byteLength": len(payload),
        "path": logical_path,
        "role": role,
        "sha256": _sha256(payload),
        "sourceIri": source_iri,
    }


def _construction_summary(
    *,
    fixture: Fixture,
    units: Sequence[ConstructionUnit],
    binding: Mapping[str, Any],
    counts: Mapping[str, int],
    distribution_id: str,
    accounting_digest: str,
    graph_rows: Sequence[Mapping[str, Any]],
    rdf_packs: Sequence[Mapping[str, Any]],
    rdf_by_unit: Mapping[str, Sequence[Mapping[str, Any]]],
    compact_packs: Sequence[Mapping[str, Any]],
    compact_path_owners: Mapping[str, str],
    compact_rows: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    del counts
    builder_path = Path(__file__).resolve()
    recipe_digest = atlas_validate.canonical_sha256(
        {
            "builderDigest": _sha256(builder_path.read_bytes()),
            "constructionProfile": CONSTRUCTION_PROFILE,
        }
    )
    adapter_path = atlas_validate.REPOSITORY_ROOT / "src/refspec/atlas/v3_source_data.py"
    adapter_pin = {
        "byteLength": adapter_path.stat().st_size,
        "path": "src/refspec/atlas/v3_source_data.py",
        "sha256": atlas_validate.file_sha256(adapter_path),
    }
    accounting_rows = {row["sourceRelease"]: row for row in fixture.accounting["inputs"]}
    compact_by_path = {pack["path"]: pack for pack in compact_packs}
    atlas_owner, source_owner = _unit_owner_maps(units)
    base_rows: dict[str, dict[str, Any]] = {}
    for unit in units:
        input_payload = atlas_validate.canonical_json_bytes(
            {"key": unit.key, "sourceRelease": str(unit.source_release)}
        )
        inputs = [
            {
                "byteLength": len(input_payload),
                "path": f"fixture-inputs/{unit.key}.json",
                "role": "fixtureSource",
                "sha256": _sha256(input_payload),
                "sourceIri": f"urn:ref:atlas-fixture:input:{unit.key}",
            }
        ]
        adapter_inputs = [dict(adapter_pin)]
        adapter_digest = atlas_validate.canonical_sha256(
            {
                "constructionProfile": CONSTRUCTION_PROFILE,
                "inputs": adapter_inputs,
                "kind": "sourceRelease",
                "sharedRecipeDigest": recipe_digest,
            }
        )
        base_payload = {
            "adapterRecipeDigest": adapter_digest,
            "atlasRelease": str(unit.atlas_release),
            "bindingBundleDigest": binding["bindingBundleDigest"],
            "constructionProfile": CONSTRUCTION_PROFILE,
            "inputInventoryDigest": atlas_validate.canonical_sha256(inputs),
            "key": unit.key,
            "kind": "sourceRelease",
            "registrySource": str(unit.registry_source),
            "resourceProfile": unit.resource_profile,
            "scheme": str(unit.scheme),
            "semanticRing": unit.ring,
            "sourceRelease": str(unit.source_release),
        }
        base_rows[unit.key] = {
            "adapterRecipeDigest": adapter_digest,
            "adapterRecipeInputCount": 1,
            "adapterRecipeInputs": adapter_inputs,
            "baseBuildKey": atlas_validate.canonical_sha256(base_payload),
            "inputFileCount": 1,
            "inputInventoryDigest": atlas_validate.canonical_sha256(inputs),
            "inputs": inputs,
        }

    unit_by_key = {unit.key: unit for unit in units}
    release_rows: list[dict[str, Any]] = []
    for unit in units:
        dependency_keys: set[str] = set()
        for statement in compact_rows.get((unit.key, "Statement"), ()):
            for field in ("sourceRelease", "targetRelease"):
                endpoint = URIRef(statement[field])
                endpoint_owner = atlas_owner.get(endpoint) or source_owner.get(endpoint)
                if endpoint_owner is not None and endpoint_owner != unit.key:
                    dependency_keys.add(endpoint_owner)
        endpoint_dependencies = [
            {
                "baseBuildKey": base_rows[key]["baseBuildKey"],
                "releaseKey": key,
                "sourceRelease": str(unit_by_key[key].source_release),
            }
            for key in sorted(dependency_keys)
        ]
        compact_paths = sorted(
            path for path, owner in compact_path_owners.items() if owner == unit.key
        )
        record_counts = {field: 0 for field in COMPACT_ROLE_COUNT_FIELDS.values()}
        logical_inventory = []
        for path in compact_paths:
            descriptor = compact_by_path[path]
            record_counts[COMPACT_ROLE_COUNT_FIELDS[descriptor["role"]]] += descriptor[
                "content"
            ]["recordCount"]
            logical_inventory.append(
                {
                    "logicalRowsDigest": descriptor["logicalRowsDigest"],
                    "packId": descriptor["packId"],
                    "path": path,
                    "recordCount": descriptor["content"]["recordCount"],
                    "role": descriptor["role"],
                }
            )
        unit_rdf_packs = sorted(rdf_by_unit[unit.key], key=lambda pack: pack["path"])
        release_rows.append(
            {
                "accountingRowDigest": atlas_validate.canonical_sha256(
                    accounting_rows[str(unit.source_release)]
                ),
                **base_rows[unit.key],
                "atlasRelease": str(unit.atlas_release),
                "buildKey": atlas_validate.canonical_sha256(
                    {
                        "baseBuildKey": base_rows[unit.key]["baseBuildKey"],
                        "constructionProfile": CONSTRUCTION_PROFILE,
                        "endpointDependencies": endpoint_dependencies,
                    }
                ),
                "compactPackPaths": compact_paths,
                "endpointDependencies": endpoint_dependencies,
                "key": unit.key,
                "kind": "sourceRelease",
                "logicalRecordInventoryDigest": atlas_validate.canonical_sha256(
                    logical_inventory
                ),
                "rdfPacks": [
                    {
                        "contentDigest": rdf_pack["content"]["digest"],
                        "packId": rdf_pack["packId"],
                        "path": rdf_pack["path"],
                    }
                    for rdf_pack in unit_rdf_packs
                ],
                "recordCounts": record_counts,
                "registrySource": str(unit.registry_source),
                "resourceProfile": unit.resource_profile,
                "scheme": str(unit.scheme),
                "semanticRing": unit.ring,
                "sourceRelease": str(unit.source_release),
            }
        )
    release_rows.sort(key=lambda row: row["key"])

    catalog_pack = next(pack for pack in rdf_packs if pack["kind"] == "catalog")
    descriptor_dataset = atlas_validate.REGISTRY_DESCRIPTOR_DATASET_PATH
    descriptor_proof = atlas_validate.REGISTRY_DESCRIPTOR_PROOF_PATH
    catalog_inputs = sorted(
        [
            _file_pin(
                descriptor_dataset,
                logical_path="bindings/atlas/3.0/tests/registry-descriptors.nq",
                role="registryDescriptors",
                source_iri="urn:ref:atlas:registry-descriptors:3.0",
            ),
            _file_pin(
                descriptor_proof,
                logical_path="bindings/atlas/3.0/tests/registry-descriptors.json",
                role="registryDescriptorProof",
                source_iri="urn:ref:atlas:registry-descriptor-proof:3.0",
            ),
        ],
        key=lambda pin: (pin["path"], pin["role"], pin["sha256"]),
    )
    catalog_input_digest = atlas_validate.canonical_sha256(catalog_inputs)
    scheme_inventory = [
        {
            "atlasRelease": row["atlasRelease"],
            "key": row["key"],
            "registrySource": row["registrySource"],
            "resourceProfile": row["resourceProfile"],
            "semanticRing": row["semanticRing"],
            "scheme": row["scheme"],
        }
        for row in release_rows
    ]
    scheme_digest = atlas_validate.canonical_sha256(scheme_inventory)
    catalog = {
        "buildKey": atlas_validate.canonical_sha256(
            {
                "bindingBundleDigest": binding["bindingBundleDigest"],
                "catalogInputInventoryDigest": catalog_input_digest,
                "constructionProfile": CONSTRUCTION_PROFILE,
                "releaseSchemeInventoryDigest": scheme_digest,
                "recipeDigest": recipe_digest,
            }
        ),
        "inputInventoryDigest": catalog_input_digest,
        "inputs": catalog_inputs,
        "releaseSchemeInventoryDigest": scheme_digest,
        "rdfPack": {
            "contentDigest": catalog_pack["content"]["digest"],
            "packId": catalog_pack["packId"],
            "path": catalog_pack["path"],
        },
    }
    compact_inventory = sorted(
        (dict(pack) for pack in compact_packs), key=lambda pack: pack["path"]
    )
    asserted_inventory = next(
        row["inventoryDigest"] for row in graph_rows if row["role"] == "asserted"
    )
    summary = {
        "assertedInventoryDigest": asserted_inventory,
        "bindingBundleDigest": binding["bindingBundleDigest"],
        "catalog": catalog,
        "compactPackCount": len(compact_inventory),
        "compactPackInventoryDigest": atlas_validate.canonical_sha256(
            compact_inventory
        ),
        "compactPacks": compact_inventory,
        "distributionId": distribution_id,
        "profile": CONSTRUCTION_PROFILE,
        "recipeDigest": recipe_digest,
        "releaseCount": len(release_rows),
        "releaseInventoryDigest": atlas_validate.canonical_sha256(release_rows),
        "releases": release_rows,
        "sourceAccountingDigest": accounting_digest,
        "type": "AtlasConstructionSummary",
        "version": "3.0",
    }
    summary["canonicalPayloadDigest"] = atlas_validate.canonical_sha256(
        summary, terminal_lf=False
    )
    return summary


def _json_member(payload: bytes, *, path: str, role: str) -> dict[str, Any]:
    return {
        "byteLength": len(payload),
        "digest": _sha256(payload),
        "mediaType": "application/json",
        "path": path,
        "role": role,
    }


def _write_case(
    path: Path,
    fixture: Fixture,
    *,
    baseline_asserted: Graph,
    binding_digests: dict[str, str],
    distribution_id: str,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    fixture.accounting["distributionId"] = distribution_id
    units = _construction_units(fixture.asserted)
    packs, graph_rows, rdf_by_unit = _write_rdf_packs(
        path,
        fixture,
        units,
        distribution_id=distribution_id,
        zstd_all=fixture.rdf_zstd_all,
        partition_owner=fixture.rdf_partition_owner,
    )
    compact_rows = _compact_logical_rows(fixture, baseline_asserted, units)
    compact_packs, compact_path_owners = _write_compact_packs(path, compact_rows)
    accounting_bytes = atlas_validate.canonical_json_bytes(fixture.accounting)
    accounting_digest = _sha256(accounting_bytes)
    binding = {
        "validatorVersion": "3.0",
        "version": "3.0",
        **binding_digests,
    }
    counts = dict(fixture.manifest_patch.get("counts", _counts(fixture)))
    construction = _construction_summary(
        fixture=fixture,
        units=units,
        binding=binding,
        counts=counts,
        distribution_id=distribution_id,
        accounting_digest=accounting_digest,
        graph_rows=graph_rows,
        rdf_packs=packs,
        rdf_by_unit=rdf_by_unit,
        compact_packs=compact_packs,
        compact_path_owners=compact_path_owners,
        compact_rows=compact_rows,
    )
    construction_bytes = atlas_validate.canonical_json_bytes(construction)
    construction_digest = _sha256(construction_bytes)
    asserted_inventory = next(
        row["inventoryDigest"] for row in graph_rows if row["role"] == "asserted"
    )
    producer = {
        "assertedInventoryDigest": asserted_inventory,
        "binding": binding,
        "checks": ["deterministic authenticated fixture construction"],
        "constructionSummary": {
            "compactPackCount": construction["compactPackCount"],
            "compactPackInventoryDigest": construction["compactPackInventoryDigest"],
            "digest": construction_digest,
            "path": "atlas-construction-summary.json",
            "profile": CONSTRUCTION_RECEIPT_PROFILE,
            "releaseCount": construction["releaseCount"],
            "releaseInventoryDigest": construction["releaseInventoryDigest"],
        },
        "constructorProfile": CONSTRUCTOR_PROFILE,
        "counts": counts,
        "implementationDigest": _sha256(Path(__file__).resolve().read_bytes()),
        "mode": "compiledSourceAndEvidenceBackedMappingProducerValidation",
        "shaclDataProof": "compiledAgainstPinnedOntologyAndShapes",
        "shaclMetaValidation": "pySHACL",
        "sourceAccountingDigest": accounting_digest,
        "sourceReleaseCount": fixture.accounting["totals"]["sourceReleases"],
        "status": "passed",
        "type": "AtlasProducerValidation",
        "version": "3.0",
    }
    producer_bytes = atlas_validate.canonical_json_bytes(producer)
    producer_digest = _sha256(producer_bytes)
    acceptance_inputs = {
        "atlasDigest": asserted_inventory,
        **binding_digests,
        "producerValidationDigest": producer_digest,
        "sourceAccountingDigest": accounting_digest,
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
        "binding": binding,
        "counts": counts,
        "createdAt": CREATED_AT,
        "distributionId": distribution_id,
        "format": "refspec-atlas-packed-nquads-3.0",
        "graphs": graph_rows,
        "members": [
            _json_member(
                accounting_bytes,
                path="atlas-source-accounting.json",
                role="sourceAccounting",
            ),
            _json_member(
                acceptance_bytes,
                path="atlas-acceptance.json",
                role="acceptance",
            ),
            _json_member(
                producer_bytes,
                path="atlas-producer-validation.json",
                role="producerValidation",
            ),
            _json_member(
                construction_bytes,
                path="atlas-construction-summary.json",
                role="constructionSummary",
            ),
        ],
        "packs": packs,
        "schemaVersion": "3.0",
        "type": "AtlasManifest",
    }
    manifest.update(fixture.manifest_patch)
    manifest["canonicalPayloadDigest"] = atlas_validate.canonical_sha256(
        manifest, terminal_lf=False
    )
    (path / "atlas-source-accounting.json").write_bytes(accounting_bytes)
    (path / "atlas-acceptance.json").write_bytes(acceptance_bytes)
    (path / "atlas-producer-validation.json").write_bytes(producer_bytes)
    (path / "atlas-construction-summary.json").write_bytes(construction_bytes)
    (path / "atlas-manifest.json").write_bytes(atlas_validate.canonical_json_bytes(manifest))
    if fixture.post_write is not None:
        fixture.post_write(path)


def _account_assertions(fixture: Fixture) -> None:
    """Restate every disposition's atlasAssertions from the mutated graph.

    A mutation that adds, moves, or drops an evidence binding changes which
    assertions each source record accounts for. The ledger is a claim about
    the graph, so a case that means to stay valid restates the claim here
    rather than shipping the baseline's copy of it.
    """

    assertions_by_record = _assertions_by_record(fixture.asserted)
    for source in fixture.accounting["inputs"]:
        for disposition in source["dispositions"]:
            assertions = assertions_by_record.get(disposition["sourceRecord"], [])
            if assertions:
                disposition["atlasAssertions"] = assertions
            else:
                disposition.pop("atlasAssertions", None)


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
        # Re-minting the binding IRI orphans anything pointing AT it -- an
        # atlas:adoptedEvidence chain link, for one -- so redirect inbound
        # references too rather than leaving a dangling subject.
        for subject, predicate, _ in list(graph.triples((None, None, evidence))):
            graph.remove((subject, predicate, evidence))
            graph.add((subject, predicate, replacement))
        graph.add((replacement, ATLAS.contentDigest, Literal(digest)))
    _reseal_evidence_to_fixed_point(graph)


def _reseal_evidence_to_fixed_point(graph: Graph) -> None:
    """Re-mint evidence bindings until every contentDigest matches its content.

    Redirecting an inbound reference changes the referring binding's content, so
    resealing one binding can stale another that adopts it. An acyclic chain
    settles by resealing terminals first and working outward; iterate rather
    than assume a depth. A cycle cannot settle -- two bindings would each need
    to contain the other's digest -- so bound the passes and leave any residue
    for the validator's adoption-cycle check to report as what it is.
    """

    for _ in range(16):
        stale = [
            evidence
            for evidence in set(graph.subjects(RDF.type, RKAF.EvidenceBinding))
            if isinstance(evidence, URIRef)
            and str(graph.value(evidence, ATLAS.contentDigest) or "")
            != _evidence_digest_without_pin(graph, evidence)
        ]
        if not stale:
            return
        for evidence in stale:
            _remove_subject_predicate(graph, evidence, ATLAS.contentDigest)
            digest = atlas_validate.rdf_node_digest(graph, evidence)
            replacement = URIRef("urn:ref:atlas-evidence:" + digest.removeprefix("sha256:"))
            for _, predicate, obj in list(graph.triples((evidence, None, None))):
                graph.remove((evidence, predicate, obj))
                graph.add((replacement, predicate, obj))
            for subject, predicate, _ in list(graph.triples((None, None, evidence))):
                graph.remove((subject, predicate, evidence))
                graph.add((subject, predicate, replacement))
            graph.add((replacement, ATLAS.contentDigest, Literal(digest)))


def _evidence_digest_without_pin(graph: Graph, evidence: URIRef) -> str:
    pinned = graph.value(evidence, ATLAS.contentDigest)
    if pinned is not None:
        graph.remove((evidence, ATLAS.contentDigest, pinned))
    try:
        return atlas_validate.rdf_node_digest(graph, evidence)
    finally:
        if pinned is not None:
            graph.add((evidence, ATLAS.contentDigest, pinned))


def _remove_assertion_with_evidence(graph: Graph, assertion: URIRef) -> None:
    for evidence in list(graph.subjects(RKAF.bindsAssertion, assertion)):
        graph.remove((evidence, None, None))
    graph.remove((assertion, None, None))


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
    def cross_assertion(
        fixture: Fixture,
        source_ring: URIRef,
        target_ring: URIRef,
    ) -> URIRef:
        return next(
            assertion
            for assertion in fixture.asserted.subjects(
                RDF.type, ATLAS.CrossRingRelationAssertion
            )
            if fixture.asserted.value(assertion, ATLAS.sourceRing) == source_ring
            and fixture.asserted.value(assertion, ATLAS.targetRing) == target_ring
        )

    def add_lifecycle_event(
        fixture: Fixture,
        *,
        name: str,
        assertion: URIRef,
        kind: URIRef,
        release: URIRef,
        source_record: URIRef,
    ) -> URIRef:
        """Announce one assertion lifecycle transition as an rkaf event."""

        event = URIRef(f"urn:ref:atlas-fixture:lifecycle:{name}")
        fixture.asserted.add((event, RDF.type, RKAF.LifecycleEvent))
        fixture.asserted.add((event, RKAF.appliesTo, assertion))
        fixture.asserted.add((event, RKAF.lifecycleEventKind, kind))
        fixture.asserted.add(
            (
                event,
                RKAF.effectiveDate,
                Literal(CREATED_AT, datatype=XSD.dateTime, normalize=False),
            )
        )
        release_predicate = (
            ATLAS.fromRelease if kind == RKAF.rescission else ATLAS.toRelease
        )
        fixture.asserted.add((event, release_predicate, release))
        fixture.asserted.add((event, ATLAS.sourceRecord, source_record))
        _refresh_node_digest(fixture.asserted, event)
        return event

    def rescind_inert_cross_ring_assertion(fixture: Fixture) -> URIRef:
        """Rescind the otherwise-inert entity -> legal-identity assertion.

        Terminal, so it is legitimately excluded from the projection, and no
        other fixture record depends on it.
        """

        assertion = cross_assertion(fixture, ATLAS.entity, ATLAS.legalIdentity)
        entity = URIRef("urn:ref:atlas-fixture:resource:entity-agency")
        return add_lifecycle_event(
            fixture,
            name="entity-references-legal-rescinded",
            assertion=assertion,
            kind=RKAF.rescission,
            release=next(fixture.asserted.objects(entity, ATLAS.inRelease)),
            source_record=next(fixture.asserted.objects(entity, ATLAS.sourceRecord)),
        )

    def no_derived(fixture: Fixture) -> None:
        fixture.derived.remove((None, None, None))

    def rdf_literal_escaping(_fixture: Fixture) -> None:
        return

    def source_native_thesaurus(fixture: Fixture) -> None:
        resource = URIRef("urn:ref:atlas-fixture:resource:subject-a-child")
        parent = URIRef("urn:ref:atlas-fixture:resource:subject-a")
        label = next(fixture.asserted.objects(resource, SKOSXL.prefLabel))
        source_record = next(fixture.asserted.objects(resource, ATLAS.sourceRecord))
        release = next(fixture.asserted.objects(resource, ATLAS.inRelease))

        fixture.asserted.remove((resource, SKOSXL.prefLabel, label))
        fixture.asserted.add((resource, SKOSXL.altLabel, label))
        native_payload_bytes = atlas_validate.canonical_native_json_bytes(
            {
                "identifier": "subject-a-child",
                "label": "Agency procedure",
                "publisherOptionalValue": None,
            }
        )
        _remove_subject_predicate(fixture.asserted, source_record, ATLAS.nativePayload)
        fixture.asserted.add(
            (
                source_record,
                ATLAS.nativePayload,
                Literal(
                    native_payload_bytes.decode("utf-8"),
                    datatype=RDF.JSON,
                    normalize=False,
                ),
            )
        )
        _remove_subject_predicate(fixture.asserted, source_record, ATLAS.sourceDigest)
        fixture.asserted.add(
            (
                source_record,
                ATLAS.sourceDigest,
                Literal("sha256:" + hashlib.sha256(native_payload_bytes).hexdigest()),
            )
        )
        _refresh_node_digest(fixture.asserted, source_record)
        _refresh_evidence_for_source(fixture.asserted, source_record)
        _refresh_node_digest(fixture.asserted, resource)

        for predicate, subject, obj, name in (
            (ATLAS.thesaurusUse, resource, parent, "thesaurus-use"),
            (ATLAS.thesaurusUsedFor, parent, resource, "thesaurus-used-for"),
            (ATLAS.thesaurusRelated, resource, parent, "thesaurus-related"),
        ):
            _add_assertion(
                fixture.asserted,
                assertion_type=ATLAS.NativeRelationAssertion,
                ring=ATLAS.subject,
                subject=subject,
                predicate=predicate,
                obj=obj,
                source_release=release,
                target_release=release,
                evidence_record=source_record,
                evidence_name=name,
            )
        _account_assertions(fixture)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

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
        evidence = next(fixture.asserted.subjects(RKAF.bindsAssertion, old))
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
            evidence_name="superseding-policy-v2",
            policy=policy,
            asserted_at="2026-08-06T12:00:00+00:00",
            supersedes=old,
        )
        add_lifecycle_event(
            fixture,
            name="subject-a-mapping-superseded",
            assertion=old,
            kind=RKAF.supersession,
            release=target_release,
            source_record=evidence_record,
        )
        fixture.derived.remove((None, None, None))
        _account_assertions(fixture)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def supersession_without_event(fixture: Fixture) -> None:
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
        evidence = next(fixture.asserted.subjects(RKAF.bindsAssertion, old))
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
            for dataset in sorted((path / "packs" / "rdf").glob("*.nq")):
                lines = dataset.read_bytes().splitlines()
                for index, line in enumerate(lines):
                    subject, separator, remainder = line.partition(b" ")
                    changed = subject.replace(b"fixture", b"fixturf", 1)
                    if changed == subject:
                        continue
                    # One subject IRI, never the graph name in the fourth
                    # position: the payload stays valid canonical N-Quads
                    # belonging to a declared graph, so the fixture isolates the
                    # authenticated-pack digest check instead of tripping the
                    # graph-membership check first.
                    lines[index] = changed + separator + remainder
                    dataset.write_bytes(b"\n".join(sorted(lines)) + b"\n")
                    return
            raise ValueError("fixture digest mutation found no RDF payload to change")

        fixture.post_write = mutate

    def blank_node(fixture: Fixture) -> None:
        fixture.asserted.add((BNode("forbidden"), RDF.type, ATLAS.ResourceScheme))

    def label_missing_literal(fixture: Fixture) -> None:
        label = next(fixture.asserted.subjects(RDF.type, SKOSXL.Label))
        _remove_subject_predicate(fixture.asserted, label, SKOSXL.literalForm)
        _refresh_node_digest(fixture.asserted, label)

    def non_english_label(fixture: Fixture) -> None:
        label = next(fixture.asserted.subjects(RDF.type, SKOSXL.Label))
        _remove_subject_predicate(fixture.asserted, label, SKOSXL.literalForm)
        fixture.asserted.add(
            (label, SKOSXL.literalForm, Literal("Agence exemplaire", lang="fr"))
        )
        _refresh_node_digest(fixture.asserted, label)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

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
        for evidence in list(fixture.asserted.subjects(RKAF.bindsAssertion, assertion)):
            fixture.asserted.remove((evidence, None, None))

    def cross_ring_missing_evidence(fixture: Fixture) -> None:
        assertion = cross_assertion(fixture, ATLAS.entity, ATLAS.subject)
        for evidence in list(fixture.asserted.subjects(RKAF.bindsAssertion, assertion)):
            fixture.asserted.remove((evidence, None, None))

    def cross_ring_endpoint_reversal(fixture: Fixture) -> None:
        assertion = cross_assertion(fixture, ATLAS.entity, ATLAS.subject)
        _remove_subject_predicate(fixture.asserted, assertion, ATLAS.sourceRing)
        _remove_subject_predicate(fixture.asserted, assertion, ATLAS.targetRing)
        fixture.asserted.add((assertion, ATLAS.sourceRing, ATLAS.subject))
        fixture.asserted.add((assertion, ATLAS.targetRing, ATLAS.entity))

    def cross_ring_disallowed_predicate(fixture: Fixture) -> None:
        assertion = cross_assertion(fixture, ATLAS.entity, ATLAS.legalIdentity)
        _, (subject, _, obj) = atlas_validate._assertion_basis(
            fixture.asserted, assertion
        )
        source_release = next(
            fixture.asserted.objects(assertion, ATLAS.sourceRelease)
        )
        target_release = next(
            fixture.asserted.objects(assertion, ATLAS.targetRelease)
        )
        evidence = next(fixture.asserted.subjects(RKAF.bindsAssertion, assertion))
        evidence_record = next(
            fixture.asserted.objects(evidence, ATLAS.evidenceSourceRecord)
        )
        _remove_assertion_with_evidence(fixture.asserted, assertion)
        _add_assertion(
            fixture.asserted,
            assertion_type=ATLAS.CrossRingRelationAssertion,
            ring=None,
            source_ring=ATLAS.entity,
            target_ring=ATLAS.legalIdentity,
            subject=subject,
            predicate=ATLAS.hasIndexedSubject,
            obj=obj,
            source_release=source_release,
            target_release=target_release,
            evidence_record=evidence_record,
            evidence_name="cross-ring-disallowed-predicate",
        )

    def cross_ring_disallowed_pair(fixture: Fixture) -> None:
        subject = URIRef("urn:ref:atlas-fixture:resource:entity-agency")
        obj = URIRef("urn:ref:atlas-fixture:resource:value-child")
        source_release = next(fixture.asserted.objects(subject, ATLAS.inRelease))
        target_release = next(fixture.asserted.objects(obj, ATLAS.inRelease))
        evidence_record = next(fixture.asserted.objects(subject, ATLAS.sourceRecord))
        _add_assertion(
            fixture.asserted,
            assertion_type=ATLAS.CrossRingRelationAssertion,
            ring=None,
            source_ring=ATLAS.entity,
            target_ring=ATLAS.value,
            subject=subject,
            predicate=ATLAS.hasIndexedSubject,
            obj=obj,
            source_release=source_release,
            target_release=target_release,
            evidence_record=evidence_record,
            evidence_name="cross-ring-disallowed-pair",
        )

    def wrong_ring_relation(fixture: Fixture) -> None:
        assertion = next(
            row
            for row in fixture.asserted.subjects(RDF.type, ATLAS.NativeRelationAssertion)
            if fixture.asserted.value(row, ATLAS.semanticRing) == ATLAS.value
        )
        _, (subject, _, obj) = atlas_validate._assertion_basis(fixture.asserted, assertion)
        source_release = next(fixture.asserted.objects(assertion, ATLAS.sourceRelease))
        target_release = next(fixture.asserted.objects(assertion, ATLAS.targetRelease))
        evidence = next(fixture.asserted.subjects(RKAF.bindsAssertion, assertion))
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
        _remove_subject_predicate(fixture.derived, node, RKAF.inputDigest)
        fixture.derived.add(
            (
                node,
                RKAF.inputDigest,
                Literal(atlas_validate.derived_input_digest(fixture.asserted, inputs)),
            )
        )
        _reidentify_derived(fixture.derived, node)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def derived_rescinded_input(fixture: Fixture) -> None:
        # A rescinded assertion leaves the projection, so a derived relation
        # that still names it as an input no longer has active inputs. The
        # assertion node itself is untouched, so its content digest and the
        # derived inputDigest both stay correct: the only thing that changed
        # is that a lifecycle event now says the assertion was rescinded.
        assertion = next(
            row
            for row in fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion)
            if fixture.asserted.value(row, RDF.subject)
            == URIRef("urn:ref:atlas-fixture:resource:subject-a")
        )
        evidence = next(fixture.asserted.subjects(RKAF.bindsAssertion, assertion))
        add_lifecycle_event(
            fixture,
            name="subject-a-mapping-rescinded",
            assertion=assertion,
            kind=RKAF.rescission,
            release=next(fixture.asserted.objects(assertion, ATLAS.sourceRelease)),
            source_record=next(
                fixture.asserted.objects(evidence, ATLAS.evidenceSourceRecord)
            ),
        )
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def missing_disposition(fixture: Fixture) -> None:
        source = fixture.accounting["inputs"][0]
        source["dispositions"].pop()
        source["declaredMemberCount"] -= 1
        fixture.accounting["totals"]["sourceRecords"] -= 1
        fixture.accounting["totals"]["represented"] -= 1

    def count_mismatch(fixture: Fixture) -> None:
        counts = _counts(fixture)
        fixture.manifest_patch["counts"] = {
            **counts,
            "projectedRelations": counts["projectedRelations"] + 1,
        }

    def missing_acceptance_gate(fixture: Fixture) -> None:
        fixture.omitted_gate = "reasoning-isolation"

    def identifier_missing_value(fixture: Fixture) -> None:
        identifier = next(fixture.asserted.subjects(RDF.type, ATLAS.Identifier))
        _remove_subject_predicate(fixture.asserted, identifier, ATLAS.identifierValue)
        _refresh_node_digest(fixture.asserted, identifier)

    def _add_identifier(
        fixture: Fixture,
        name: str,
        *,
        resource: URIRef,
        value: Literal,
    ) -> URIRef:
        """Mint one more atlas:Identifier in the base fixture's own scheme."""

        original = next(fixture.asserted.subjects(RDF.type, ATLAS.Identifier))
        identifier = URIRef(f"urn:ref:atlas-fixture:identifier:{name}")
        fixture.asserted.add((identifier, RDF.type, ATLAS.Identifier))
        fixture.asserted.add((identifier, ATLAS.identifierValue, value))
        fixture.asserted.add(
            (
                identifier,
                ATLAS.identifierScheme,
                next(fixture.asserted.objects(original, ATLAS.identifierScheme)),
            )
        )
        fixture.asserted.add((identifier, ATLAS.identifies, resource))
        fixture.asserted.add(
            (
                identifier,
                ATLAS.sourceRecord,
                next(fixture.asserted.objects(resource, ATLAS.sourceRecord)),
            )
        )
        _refresh_node_digest(fixture.asserted, identifier)
        return identifier

    def _disagreeing_identifiers(fixture: Fixture) -> tuple[URIRef, URIRef]:
        """The contradiction itself: one (scheme, value) pair, two resources."""

        original = next(fixture.asserted.subjects(RDF.type, ATLAS.Identifier))
        original_resource = next(fixture.asserted.objects(original, ATLAS.identifies))
        conflicting_resource = next(
            resource
            for resource in fixture.asserted.subjects(RDF.type, ATLAS.AtlasResource)
            if resource != original_resource
        )
        conflicting = _add_identifier(
            fixture,
            "agency-conflict",
            resource=conflicting_resource,
            value=next(fixture.asserted.objects(original, ATLAS.identifierValue)),
        )
        return original, conflicting

    def identifier_pair_conflict(fixture: Fixture) -> None:
        # The refusal that predates the conflict record and outlives it: a
        # contradiction nothing declares still fails the build.
        _disagreeing_identifiers(fixture)

    # ---- registry conflict -------------------------------------------------
    #
    # The other half of the same rule. A distribution MAY publish the
    # contradiction above instead of being refused, but only by carrying an
    # rkaf:RegistryConflict that names exactly the atlas:Identifier records that
    # disagree. The valid case is the whole point -- the disagreement survives
    # as a record a consumer can read -- and each negative forges exactly one
    # fact about that record: it names too few entries, it names the wrong ones,
    # its severity is outside rkaf's closed set, its severity is one a published
    # artifact cannot honestly claim, or its detection time is not a dateTime.

    def _record_conflict(
        fixture: Fixture,
        entries: Iterable[URIRef],
        *,
        severity: URIRef = RKAF.operationalConflict,
        detected_at: Literal | None = None,
    ) -> URIRef:
        record = URIRef("urn:ref:atlas-fixture:registry-conflict:agency-001")
        fixture.asserted.add((record, RDF.type, RKAF.RegistryConflict))
        for entry in entries:
            fixture.asserted.add((record, RKAF.conflictingEntries, entry))
        fixture.asserted.add((record, RKAF.severity, severity))
        fixture.asserted.add(
            (
                record,
                RKAF.detectedAt,
                detected_at
                if detected_at is not None
                else Literal(CREATED_AT, datatype=XSD.dateTime, normalize=False),
            )
        )
        return record

    def identifier_conflict_recorded(fixture: Fixture) -> None:
        _record_conflict(fixture, _disagreeing_identifiers(fixture))

    def registry_conflict_single_entry(fixture: Fixture) -> None:
        original, _conflicting = _disagreeing_identifiers(fixture)
        _record_conflict(fixture, (original,))

    def registry_conflict_entries_mismatch(fixture: Fixture) -> None:
        # A well-formed record that names a real Identifier which is not in the
        # disagreement, and omits the one that is. Both halves must fail: the
        # record licenses nothing, and the contradiction stays unrecorded.
        original, _conflicting = _disagreeing_identifiers(fixture)
        bystander = _add_identifier(
            fixture,
            "agency-second",
            resource=next(fixture.asserted.objects(original, ATLAS.identifies)),
            value=Literal("AGENCY-002"),
        )
        _record_conflict(fixture, (original, bystander))

    def registry_conflict_severity_unknown(fixture: Fixture) -> None:
        # Outside rkaf's #ConflictSeverity altogether, not merely outside the
        # two values this wire narrows to -- that forgery is the case below.
        _record_conflict(
            fixture,
            _disagreeing_identifiers(fixture),
            severity=URIRef("urn:ref:conflict-severity:invented"),
        )

    def registry_conflict_publication_blocking(fixture: Fixture) -> None:
        # One of rkaf's four #ConflictSeverity values, and one this wire refuses:
        # a distribution that passed acceptance cannot also declare that its own
        # conflict blocked publication.
        _record_conflict(
            fixture,
            _disagreeing_identifiers(fixture),
            severity=RKAF.publicationBlocking,
        )

    def registry_conflict_detected_at_not_datetime(fixture: Fixture) -> None:
        _record_conflict(
            fixture,
            _disagreeing_identifiers(fixture),
            detected_at=Literal("2026-08-05"),
        )

    def wrong_endpoint_release(fixture: Fixture) -> None:
        assertion = next(fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion))
        wrong = next(fixture.asserted.subjects(RDF.type, ATLAS.AtlasRelease))
        _remove_subject_predicate(fixture.asserted, assertion, ATLAS.targetRelease)
        fixture.asserted.add((assertion, ATLAS.targetRelease, wrong))

    # ---- ring temporal context ------------------------------------------
    #
    # The base fixture dates exactly the two mappings whose rings make them
    # claims about a period: the value crosswalk, with a closed period, and the
    # legal-identity recodification, with an open-ended one. Each mutation below
    # forges exactly one fact about that -- the period is missing, the period is
    # on a ring that must not carry one, the period runs backwards, or its start
    # is not a dateTime.

    def dated_mapping(fixture: Fixture, ring: URIRef) -> URIRef:
        return next(
            assertion
            for assertion in fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion)
            if fixture.asserted.value(assertion, ATLAS.semanticRing) == ring
        )

    def strip_period(fixture: Fixture, assertion: URIRef) -> URIRef:
        period = next(fixture.asserted.objects(assertion, RKAF.hasEffectivePeriod))
        _remove_subject_predicate(fixture.asserted, assertion, RKAF.hasEffectivePeriod)
        for triple in list(fixture.asserted.triples((period, None, None))):
            fixture.asserted.remove(triple)
        _refresh_node_digest(fixture.asserted, assertion)
        return period

    def mapping_undated_value_crosswalk(fixture: Fixture) -> None:
        # The registry has refused this since it had rings; until now the wire
        # took it. A crosswalk with no period cannot be applied to a dated
        # question, and nothing on the published record said so.
        strip_period(fixture, dated_mapping(fixture, ATLAS.value))

    def mapping_undated_legal_identity(fixture: Fixture) -> None:
        strip_period(fixture, dated_mapping(fixture, ATLAS.legalIdentity))

    def mapping_subject_ring_dated(fixture: Fixture) -> None:
        # The other half of the ring rule, and the half a "period is optional
        # everywhere" shape would silently admit: a subject-ring equivalence
        # holds of the concepts, so a period on one is a fact no source states.
        period = next(
            fixture.asserted.objects(
                dated_mapping(fixture, ATLAS.value),
                RKAF.hasEffectivePeriod,
            )
        )
        subject_mapping = dated_mapping(fixture, ATLAS.subject)
        fixture.asserted.add((subject_mapping, RKAF.hasEffectivePeriod, period))
        _refresh_node_digest(fixture.asserted, subject_mapping)

    def mapping_period_end_before_start(fixture: Fixture) -> None:
        assertion = dated_mapping(fixture, ATLAS.value)
        period = next(fixture.asserted.objects(assertion, RKAF.hasEffectivePeriod))
        start = next(fixture.asserted.objects(period, RKAF.effectivePeriodStart))
        _remove_subject_predicate(fixture.asserted, period, RKAF.effectivePeriodEnd)
        fixture.asserted.add(
            (
                period,
                RKAF.effectivePeriodEnd,
                Literal(
                    "2025-06-30T00:00:00+00:00",
                    datatype=XSD.dateTime,
                    normalize=False,
                ),
            )
        )
        if str(start) <= "2025-06-30T00:00:00+00:00":
            raise ValueError("the backwards period fixture no longer runs backwards")

    def mapping_period_start_not_datetime(fixture: Fixture) -> None:
        period = next(
            fixture.asserted.objects(
                dated_mapping(fixture, ATLAS.legalIdentity),
                RKAF.hasEffectivePeriod,
            )
        )
        _remove_subject_predicate(fixture.asserted, period, RKAF.effectivePeriodStart)
        fixture.asserted.add(
            (period, RKAF.effectivePeriodStart, Literal("2026-07-01"))
        )

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
        evidence = next(fixture.asserted.subjects(RDF.type, RKAF.EvidenceBinding))
        current = next(fixture.asserted.objects(evidence, ATLAS.evidenceSourceRecord))
        replacement = next(
            record
            for record in fixture.asserted.subjects(RDF.type, ATLAS.SourceRecord)
            if record != current
        )
        _remove_subject_predicate(fixture.asserted, evidence, ATLAS.evidenceSourceRecord)
        fixture.asserted.add((evidence, ATLAS.evidenceSourceRecord, replacement))

    def evidence_reviewer_retargeted(fixture: Fixture) -> None:
        evidence = next(fixture.asserted.subjects(RDF.type, RKAF.EvidenceBinding))
        _remove_subject_predicate(fixture.asserted, evidence, RKAF.attestor)
        fixture.asserted.add(
            (evidence, RKAF.attestor, URIRef("urn:ref:agent:unreviewed-replacement"))
        )

    def _some_evidence(fixture: Fixture) -> URIRef:
        return next(fixture.asserted.subjects(RDF.type, RKAF.EvidenceBinding))

    def _replace_evidence_fact(
        fixture: Fixture, predicate: URIRef, obj: object
    ) -> None:
        evidence = _some_evidence(fixture)
        _remove_subject_predicate(fixture.asserted, evidence, predicate)
        fixture.asserted.add((evidence, predicate, obj))

    def evidence_decision_not_approved(fixture: Fixture) -> None:
        # Atlas publishes approved evidence only. Nothing else in the binding
        # states that invariant, so this is the fixture that proves it holds.
        _replace_evidence_fact(fixture, RKAF.decision, RKAF.rejected)

    def evidence_attestor_kind_unknown(fixture: Fixture) -> None:
        _replace_evidence_fact(
            fixture, RKAF.attestorKind, URIRef("urn:ref:attestor-kind:invented")
        )

    def evidence_attested_at_not_datetime(fixture: Fixture) -> None:
        _replace_evidence_fact(
            fixture, RKAF.attestedAt, Literal("2026-08-09", datatype=XSD.string)
        )

    def evidence_function_unknown(fixture: Fixture) -> None:
        _replace_evidence_fact(
            fixture,
            RKAF.evidentiaryFunction,
            URIRef("urn:ref:evidentiary-function:invented"),
        )

    def evidence_warrant_unsanctioned(fixture: Fixture) -> None:
        # Each axis value stays inside its own upstream enum; only the
        # COMBINATION is one no review warrant sanctions. This is the case a
        # decomposition into independent axes would otherwise let through, and
        # the reason the sh:xone enumerates combinations rather than trusting
        # the per-axis sh:in constraints.
        _replace_evidence_fact(fixture, RKAF.evidenceRole, RKAF.retrievalSignal)

    def assertion_asserted_at_not_datetime(fixture: Fixture) -> None:
        assertion = next(fixture.asserted.subjects(RDF.type, ATLAS.RelationAssertion))
        _remove_subject_predicate(fixture.asserted, assertion, RKAF.assertedAt)
        fixture.asserted.add(
            (assertion, RKAF.assertedAt, Literal("2026-08-09", datatype=XSD.string))
        )

    def release_membership_mode_unknown(fixture: Fixture) -> None:
        release = next(fixture.asserted.subjects(RDF.type, ATLAS.AtlasRelease))
        _remove_subject_predicate(fixture.asserted, release, RKAF.membershipMode)
        fixture.asserted.add(
            (release, RKAF.membershipMode, URIRef("urn:ref:membership-mode:invented"))
        )

    def _declares_adoption(fixture: Fixture, binding: URIRef) -> bool:
        return (
            tuple(
                fixture.asserted.value(binding, axis)
                for axis in atlas_validate.EVIDENCE_WARRANT_AXES
            )
            == atlas_validate.EVIDENCE_WARRANTS["operatorAdoption"]
        )

    def _operator_adopted_evidence(fixture: Fixture) -> URIRef:
        return next(
            subject
            for subject in fixture.asserted.subjects(RDF.type, RKAF.EvidenceBinding)
            if _declares_adoption(fixture, subject)
        )

    def adoption_without_referent(fixture: Fixture) -> None:
        # operatorAdoption evidence that names nothing it adopted: the exact
        # regression this shape and check exist to reject. Reidentify the
        # binding after the removal so this fixture's only defect is the
        # missing adoptedEvidence, not an incidentally stale contentDigest.
        evidence = _operator_adopted_evidence(fixture)
        _remove_subject_predicate(fixture.asserted, evidence, RKAF.basedOnAttestation)
        _remove_subject_predicate(fixture.asserted, evidence, ATLAS.contentDigest)
        digest = atlas_validate.rdf_node_digest(fixture.asserted, evidence)
        replacement = URIRef("urn:ref:atlas-evidence:" + digest.removeprefix("sha256:"))
        for _, predicate, obj in list(fixture.asserted.triples((evidence, None, None))):
            fixture.asserted.remove((evidence, predicate, obj))
            fixture.asserted.add((replacement, predicate, obj))
        fixture.asserted.add((replacement, ATLAS.contentDigest, Literal(digest)))

    def adoption_chain_cycle(fixture: Fixture) -> None:
        # Two operatorAdoption bindings adopt each other. Each binding's own
        # content-derived identity is left untouched (a real mutual reference
        # cycle can never itself be content-addressed consistently), because
        # the adoption chain resolver runs before identity checks and must
        # reject the cycle on its own terms.
        later_evidence = _operator_adopted_evidence(fixture)
        earlier_evidence = next(
            fixture.asserted.objects(later_evidence, RKAF.basedOnAttestation)
        )
        for axis, value in zip(
            atlas_validate.EVIDENCE_WARRANT_AXES,
            atlas_validate.EVIDENCE_WARRANTS["operatorAdoption"],
            strict=True,
        ):
            _remove_subject_predicate(fixture.asserted, earlier_evidence, axis)
            fixture.asserted.add((earlier_evidence, axis, value))
        fixture.asserted.add((earlier_evidence, RKAF.basedOnAttestation, later_evidence))

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
        dispositions = next(
            source["dispositions"]
            for source in fixture.accounting["inputs"]
            if len(source["dispositions"]) >= 2
        )
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
        source = next(fixture.asserted.subjects(RDF.type, ATLAS.RegistrySource))
        fixture.asserted.add((derived, RDF.type, ATLAS.ResourceScheme))
        fixture.asserted.add((derived, ATLAS.resourceProfile, ATLAS.resourceCollection))
        fixture.asserted.add((derived, ATLAS.sourceDescriptor, source))
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
        _remove_subject_predicate(fixture.derived, derived, RKAF.inputDigest)
        fixture.derived.add((derived, RKAF.inputDigest, Literal("sha256:" + "4" * 64)))

    def wrong_derived_endpoint(fixture: Fixture) -> None:
        derived = next(fixture.derived.subjects(RDF.type, ATLAS.DerivedRelation))
        source_release = next(
            fixture.asserted.subjects(RDF.type, ATLAS.SourceRelease)
        )
        _remove_subject_predicate(fixture.derived, derived, ATLAS.relationSubject)
        fixture.derived.add((derived, ATLAS.relationSubject, source_release))

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

    def unjustified_thesaurus_related(fixture: Fixture) -> None:
        assertion = next(
            row
            for row in fixture.asserted.subjects(
                RDF.type, ATLAS.NativeRelationAssertion
            )
            if fixture.asserted.value(row, RDF.predicate) == SKOS.broader
        )
        _, (subject, _, obj) = atlas_validate._assertion_basis(
            fixture.asserted, assertion
        )
        release = next(fixture.asserted.objects(assertion, ATLAS.sourceRelease))
        evidence = next(fixture.asserted.subjects(RKAF.bindsAssertion, assertion))
        evidence_record = next(
            fixture.asserted.objects(evidence, ATLAS.evidenceSourceRecord)
        )
        fixture.asserted.remove((assertion, None, None))
        fixture.asserted.remove((evidence, None, None))
        _add_assertion(
            fixture.asserted,
            assertion_type=ATLAS.NativeRelationAssertion,
            ring=ATLAS.subject,
            subject=subject,
            predicate=ATLAS.thesaurusRelated,
            obj=obj,
            source_release=release,
            target_release=release,
            evidence_record=evidence_record,
            evidence_name="unjustified-thesaurus-related",
        )
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

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

    def zstd_packs(fixture: Fixture) -> None:
        # Content is identical to the base fixture; only the RDF pack
        # transport changes, so every pack -- catalog, each source-release
        # pack, and the view pack -- is written zstd-compressed instead of
        # raw. This is the only path that exercises validate.py's
        # `compression == "zstd"` branch (~2199-2206) with a passing case.
        fixture.rdf_zstd_all = True

    def partitioned_packs(fixture: Fixture) -> None:
        # Split the (self-contained, unreferenced-elsewhere) mixed-code-value
        # release across more than one RDF pack, bucketed by a real
        # sha256(subject IRI) prefix, so the partition-bucket check
        # (~2190-2193) and the co-location/overlap check (~1492-1515) both
        # run against a passing case instead of only ever seeing one pack
        # per source release.
        fixture.rdf_partition_owner = "source-mixed-code-value"

    def rescission_lifecycle(fixture: Fixture) -> None:
        # The assertion carries no status to change. The rescission event IS
        # the withdrawal, and the projection drops the assertion because of it.
        rescind_inert_cross_ring_assertion(fixture)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def lifecycle_event_kind_unknown(fixture: Fixture) -> None:
        # atlas:eventType admitted any IRI. rkaf:lifecycleEventKind does not.
        event = rescind_inert_cross_ring_assertion(fixture)
        _remove_subject_predicate(fixture.asserted, event, RKAF.lifecycleEventKind)
        fixture.asserted.add(
            (event, RKAF.lifecycleEventKind, URIRef("urn:ref:atlas-event:admitted"))
        )
        _refresh_node_digest(fixture.asserted, event)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def lifecycle_effective_date_not_datetime(fixture: Fixture) -> None:
        event = rescind_inert_cross_ring_assertion(fixture)
        _remove_subject_predicate(fixture.asserted, event, RKAF.effectiveDate)
        fixture.asserted.add((event, RKAF.effectiveDate, Literal(CREATED_AT)))
        _refresh_node_digest(fixture.asserted, event)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def lifecycle_applies_to_nonassertion(fixture: Fixture) -> None:
        # atlas:eventSubject was a bare sh:nodeKind sh:IRI, so an event could
        # name a resource, a release, or anything else and still conform.
        event = rescind_inert_cross_ring_assertion(fixture)
        _remove_subject_predicate(fixture.asserted, event, RKAF.appliesTo)
        fixture.asserted.add(
            (
                event,
                RKAF.appliesTo,
                URIRef("urn:ref:atlas-fixture:resource:entity-agency"),
            )
        )
        _refresh_node_digest(fixture.asserted, event)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def lifecycle_rescission_names_target_release(fixture: Fixture) -> None:
        # A rescission leaves a release; it does not admit the assertion into
        # one. Before the kind was closed, either pointer was legal on either
        # event and nothing distinguished them.
        event = rescind_inert_cross_ring_assertion(fixture)
        release = next(fixture.asserted.objects(event, ATLAS.fromRelease))
        _remove_subject_predicate(fixture.asserted, event, ATLAS.fromRelease)
        fixture.asserted.add((event, ATLAS.toRelease, release))
        _refresh_node_digest(fixture.asserted, event)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def skosxl_hidden_label(fixture: Fixture) -> None:
        # Add a genuine skosxl:hiddenLabel to an existing resource, disjoint
        # in both node and literal text from its prefLabel, so the
        # projection's skosxl:hiddenLabel -> skos:hiddenLabel path and the
        # compact "hidden" labelRole (~5392) both run against a passing case.
        resource = URIRef("urn:ref:atlas-fixture:resource:subject-c")
        release = next(fixture.asserted.objects(resource, ATLAS.inRelease))
        source_record = next(fixture.asserted.objects(resource, ATLAS.sourceRecord))
        label = URIRef("urn:ref:atlas-fixture:label:subject-c:hidden:en")
        fixture.asserted.add((resource, SKOSXL.hiddenLabel, label))
        fixture.asserted.add((label, RDF.type, SKOSXL.Label))
        fixture.asserted.add(
            (label, SKOSXL.literalForm, Literal("Admin law (deprecated term)", lang="en"))
        )
        fixture.asserted.add((label, ATLAS.inRelease, release))
        fixture.asserted.add((label, ATLAS.sourceRecord, source_record))
        _refresh_node_digest(fixture.asserted, label)
        _refresh_node_digest(fixture.asserted, resource)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def native_payload_digest_mismatch(fixture: Fixture) -> None:
        record = next(fixture.asserted.subjects(RDF.type, ATLAS.SourceRecord))
        _remove_subject_predicate(fixture.asserted, record, ATLAS.sourceDigest)
        fixture.asserted.add(
            (record, ATLAS.sourceDigest, Literal("sha256:" + "9" * 64))
        )
        _refresh_node_digest(fixture.asserted, record)
        _refresh_evidence_for_source(fixture.asserted, record)

    # ---- machine adjudication -------------------------------------------
    #
    # The base fixture licenses one mapping (subject-a exactMatch subject-b,
    # the only assertion whose evidence declares the twoMachineAdjudication
    # warrant) with two independent proofs. Every mutation below forges exactly
    # one fact of that proof, which is the structure Atlas 1.0's README
    # demanded of this corpus and never got: "a reader that accepts any of them
    # has not implemented the binding and has a locatable defect."

    ADJUDICATED = "exact-ab"

    def comparison_node() -> URIRef:
        return _adjudication_iri("comparison", ADJUDICATED)

    def proof_node(key: str) -> URIRef:
        return _adjudication_iri("proof", ADJUDICATED, key)

    def adjudicated_assertion(fixture: Fixture) -> URIRef:
        return next(
            fixture.asserted.objects(comparison_node(), RKAF.comparisonExpectedAssertion)
        )

    def restate(fixture: Fixture, subject: URIRef, predicate: URIRef, value: Any) -> None:
        _remove_subject_predicate(fixture.asserted, subject, predicate)
        fixture.asserted.add((subject, predicate, value))

    def lineage_node(key: str) -> URIRef:
        return _adjudication_iri("ai-lineage", ADJUDICATED, key)

    def request_artifact() -> URIRef:
        return _adjudication_iri("artifact", "request", ADJUDICATED)

    def response_artifact(key: str) -> URIRef:
        return _adjudication_iri("artifact", "response", ADJUDICATED, key)

    def drop_node(fixture: Fixture, node: URIRef) -> None:
        for triple in list(fixture.asserted.triples((node, None, None))):
            fixture.asserted.remove(triple)

    def other_mapping(fixture: Fixture, subject_local: str) -> URIRef:
        return next(
            assertion
            for assertion in fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion)
            if fixture.asserted.value(assertion, RDF.subject)
            == URIRef(f"urn:ref:atlas-fixture:resource:{subject_local}")
        )

    def add_third_machine(fixture: Fixture) -> URIRef:
        return _add_adjudication_proof(
            fixture.asserted,
            comparison=comparison_node(),
            assertion=adjudicated_assertion(fixture),
            name=ADJUDICATED,
            key="gamma",
            verdict=RKAF.verdictSame,
        )

    def qualified_three_machine_support(fixture: Fixture) -> None:
        """Three same-question supports, all retained. The regression case.

        Qualification requires at least one independent PAIR, never exactly
        two validations: a third corroborating machine is evidence that helped
        establish the relation, and the rule that rejected it was wrong on its
        own terms.
        """

        add_third_machine(fixture)

    def adjudication_discarded_support(fixture: Fixture) -> None:
        proof = add_third_machine(fixture)
        fixture.asserted.remove((comparison_node(), RKAF.comparisonProofRecord, proof))

    def adjudication_single_proof(fixture: Fixture) -> None:
        beta = proof_node("beta")
        fixture.asserted.remove((comparison_node(), RKAF.comparisonProofRecord, beta))
        for triple in list(fixture.asserted.triples((beta, None, None))):
            fixture.asserted.remove(triple)

    def adjudication_same_validator_actor(fixture: Fixture) -> None:
        """Collapses the actor AND provider axes together, unavoidably.

        The validator-actor axis is the issuer IRI and the provider axis is
        that issuer's rkaf:proofResolver, so two proofs naming one issuer
        record share both by construction; no fixture can collapse the actor
        axis alone, which is why rulespec's own fixture set has no
        actor-isolating negative either. The provider axis IS isolated, by
        adjudication-same-provider: two DISTINCT issuer records that dereference
        to one rkaf:proofResolver.
        """

        restate(
            fixture,
            proof_node("beta"),
            RKAF.proofIssuer,
            _adjudication_iri("proof-issuer", "alpha"),
        )

    def adjudication_same_independence_group(fixture: Fixture) -> None:
        restate(
            fixture,
            proof_node("beta"),
            RKAF.independenceGroup,
            _adjudication_iri("independence-group", "alpha"),
        )

    def adjudication_same_provider(fixture: Fixture) -> None:
        restate(
            fixture,
            _adjudication_iri("proof-issuer", "beta"),
            RKAF.proofResolver,
            _adjudication_iri("resolver", "alpha"),
        )

    def adjudication_same_provider_model(fixture: Fixture) -> None:
        restate(
            fixture,
            lineage_node("beta"),
            RKAF.modelId,
            Literal("alpha-adjudicator-2026-01"),
        )

    def adjudication_same_response_artifact(fixture: Fixture) -> None:
        restate(
            fixture,
            proof_node("beta"),
            RKAF.sealedResponseArtifact,
            response_artifact("alpha"),
        )

    def adjudication_mismatched_sealed_request(fixture: Fixture) -> None:
        """Two machines, two bundled questions -- each resolvable, neither shared.

        Both proofs still resolve their sealed request to real bundled bytes, so
        nothing about either record in isolation is wrong. What fails is the
        corroboration claim: two answers to two questions are not two answers to
        one.
        """

        beta = proof_node("beta")
        second = _add_artifact(
            fixture.asserted,
            _adjudication_iri("artifact", "request", ADJUDICATED, "second"),
            identifiers=[
                str(_adjudication_iri("artifact", "request", ADJUDICATED, "second"))
            ],
            digest="sha256:" + "3" * 64,
        )
        fixture.asserted.remove((beta, RKAF.proofInput, request_artifact()))
        fixture.asserted.add((beta, RKAF.proofInput, second))
        restate(fixture, beta, RKAF.sealedRequestDigest, Literal("sha256:" + "3" * 64))
        restate(
            fixture, lineage_node("beta"), RKAF.inputContextHash, Literal("sha256:" + "3" * 64)
        )

    def adjudication_foreign_comparison(fixture: Fixture) -> None:
        """A stale pass, replayed to license a comparison it was not run for.

        The proof record itself is untouched, so its own digest is no help --
        it is the CITATION that is false, which is why this rule cannot live on
        one node.
        """

        alpha = proof_node("alpha")
        replay = _add_adjudication(
            fixture.asserted,
            assertion=adjudicated_assertion(fixture),
            name=ADJUDICATED + "-replay",
            machines=(),
            outcome=RKAF.comparisonUnknown,
        )
        fixture.asserted.add((replay, RKAF.comparisonProofRecord, alpha))
        restate(fixture, alpha, RKAF.proofComparisonContext, replay)

    def adjudication_relation_not_licensed(fixture: Fixture) -> None:
        for key in ("alpha", "beta"):
            restate(
                fixture, proof_node(key), RKAF.adjudicationVerdict, RKAF.verdictTargetBroader
            )

    def adjudication_verdicts_disagree(fixture: Fixture) -> None:
        restate(
            fixture, proof_node("beta"), RKAF.adjudicationVerdict, RKAF.verdictTargetBroader
        )

    def adjudication_response_artifact_cardinality(fixture: Fixture) -> None:
        """The bypass a reviewer found upstream: a shared artifact plus a decoy.

        Both proofs would still be pairwise-distinct on the decoy value while
        sharing one sealed response, so one value per proof is what makes
        artifact-IRI inequality mean run inequality.
        """

        fixture.asserted.add(
            (
                proof_node("alpha"),
                RKAF.sealedResponseArtifact,
                response_artifact("beta"),
            )
        )

    def adjudication_proof_input_digest(fixture: Fixture) -> None:
        fixture.reseal_adjudication = False
        alpha = proof_node("alpha")
        stale = sorted(fixture.asserted.objects(alpha, RKAF.proofInputDigest), key=str)[0]
        fixture.asserted.remove((alpha, RKAF.proofInputDigest, stale))
        fixture.asserted.add((alpha, RKAF.proofInputDigest, Literal("sha256:" + "4" * 64)))
        _refresh_proof_digest(fixture.asserted, alpha)

    def adjudication_licensing_proof_refused(fixture: Fixture) -> None:
        """A refused gate is a legal wire value -- it just licenses nothing."""

        restate(fixture, proof_node("alpha"), RKAF.proofOutcome, RKAF.gateFail)

    def adjudication_proof_record_digest(fixture: Fixture) -> None:
        fixture.reseal_adjudication = False
        restate(
            fixture,
            proof_node("alpha"),
            RKAF.proofRecordDigest,
            Literal("sha256:" + "5" * 64),
        )

    def adjudication_evaluated_at_not_datetime(fixture: Fixture) -> None:
        restate(fixture, proof_node("alpha"), RKAF.proofEvaluatedAt, Literal(CREATED_AT))

    def adjudication_proof_type_not_machine(fixture: Fixture) -> None:
        restate(fixture, proof_node("alpha"), RKAF.proofType, RKAF.scopeComparisonProof)

    def adjudication_licensed_by_conflicted_comparison(fixture: Fixture) -> None:
        """The comparison record stays legal; what it cannot do is license.

        A conflicted comparison is exactly the audit record the widened outcome
        enum exists to publish. The defect is that the mapping is still on the
        wire claiming two machines adjudicated it.
        """

        restate(fixture, comparison_node(), RKAF.comparisonOutcome, RKAF.comparisonConflict)

    def adjudication_comparison_retargeted(fixture: Fixture) -> None:
        """Point the proof set at a mapping no machine adjudicated.

        Both halves of the pairing break at once: the named assertion carries
        an operatorAdoption warrant, and the mapping that DOES claim two
        machines is left citing nothing.
        """

        other = next(
            assertion
            for assertion in fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion)
            if fixture.asserted.value(assertion, RDF.subject)
            == URIRef("urn:ref:atlas-fixture:resource:subject-b")
        )
        restate(fixture, comparison_node(), RKAF.comparisonExpectedAssertion, other)

    def adjudication_warrant_without_comparison(fixture: Fixture) -> None:
        """The warrant with nothing behind it -- the claim, unaccompanied."""

        comparison = comparison_node()
        for proof in list(
            fixture.asserted.subjects(RKAF.proofComparisonContext, comparison)
        ):
            drop_node(fixture, proof)
        drop_node(fixture, comparison)

    def adjudication_issuer_incomplete(fixture: Fixture) -> None:
        _remove_subject_predicate(
            fixture.asserted, _adjudication_iri("proof-issuer", "beta"), RKAF.proofPolicyVersion
        )

    def adjudication_lineage_incomplete(fixture: Fixture) -> None:
        _remove_subject_predicate(
            fixture.asserted, lineage_node("beta"), RKAF.promptTemplateRef
        )

    def adjudication_comparison_incomplete(fixture: Fixture) -> None:
        _remove_subject_predicate(
            fixture.asserted, comparison_node(), RKAF.comparisonDetectorVersion
        )

    def adjudication_proof_rationale_empty(fixture: Fixture) -> None:
        restate(fixture, proof_node("alpha"), RKAF.proofRationale, Literal(""))

    def adjudication_artifact_scheme_unknown(fixture: Fixture) -> None:
        restate(fixture, request_artifact(), RKAF.artifactIdentifierScheme, RKAF.doi)

    def adjudication_request_artifact_unbundled(fixture: Fixture) -> None:
        """The sealed question names bytes the distribution does not carry."""

        drop_node(fixture, request_artifact())

    def adjudication_request_digest_mismatch(fixture: Fixture) -> None:
        restate(
            fixture, request_artifact(), RKAF.hasContentDigest, Literal("sha256:" + "7" * 64)
        )

    def adjudication_response_artifact_unbundled(fixture: Fixture) -> None:
        drop_node(fixture, response_artifact("alpha"))

    def adjudication_endpoint_artifact_drift(fixture: Fixture) -> None:
        fixture.reseal_adjudication = False
        restate(
            fixture,
            _adjudication_iri("artifact", "endpoint", "subject-a"),
            RKAF.hasContentDigest,
            Literal("sha256:" + "8" * 64),
        )

    def adjudication_input_context_hash(fixture: Fixture) -> None:
        restate(
            fixture, lineage_node("alpha"), RKAF.inputContextHash, Literal("sha256:" + "9" * 64)
        )

    def adjudication_foreign_snapshot(fixture: Fixture) -> None:
        restate(
            fixture,
            comparison_node(),
            RKAF.comparisonSnapshot,
            Literal("urn:ref:atlas-fixture:release:subject-a:2026"),
        )

    def adjudication_proof_snapshot_drift(fixture: Fixture) -> None:
        restate(
            fixture,
            proof_node("beta"),
            RKAF.proofSnapshot,
            Literal("urn:ref:atlas-fixture:release:subject-a:2026"),
        )

    def adjudication_refused_comparison_record(fixture: Fixture) -> None:
        """Valid: a comparison that was run, conflicted, and licensed nothing.

        This is the record a pinned outcome value made unrepresentable. It names
        a mapping established by operator adoption, carries two proofs whose
        gates returned rkaf:gateUnknown, and is published as
        rkaf:comparisonConflict -- so an auditor can tell "we asked and the
        machines disagreed" from "nobody ever asked". Nothing licenses anything,
        so neither the independence rule nor the lattice is asked of it.
        """

        _add_adjudication(
            fixture.asserted,
            assertion=other_mapping(fixture, "subject-b"),
            name="exact-bc",
            machines=(("alpha", RKAF.verdictSame), ("beta", RKAF.verdictTargetBroader)),
            outcome=RKAF.comparisonConflict,
            proof_outcome=RKAF.gateUnknown,
        )

    def qualified_lattice_branches(fixture: Fixture) -> None:
        """Valid: the three lattice branches the base fixture never reaches.

        The base corpus only ever folds {verdictSame} onto skos:exactMatch, so
        the closeMatch, narrowMatch and relatedMatch branches could be deleted
        from the lattice without a single case failing. Each mapping below is
        adjudicated by two independent machines whose verdicts license exactly
        the relation it states:

          {same, nearSame}   -> skos:closeMatch    (the weakest claim wins)
          {targetNarrower}   -> skos:narrowMatch
          {related}          -> skos:relatedMatch

        The endpoint pairs are chosen to stay clear of the exactMatch component
        {subject-a, subject-b, subject-c}, so SKOS S46 and S27 are untouched.
        """

        resource = URIRef("urn:ref:atlas-fixture:resource:subject-a-child")
        mixed = URIRef("urn:ref:atlas-fixture:resource:mixed-code-subject")
        subject_c = URIRef("urn:ref:atlas-fixture:resource:subject-c")
        branches = (
            ("close", resource, SKOS.closeMatch, mixed,
             (("alpha", RKAF.verdictSame), ("beta", RKAF.verdictNearSame))),
            ("narrow", mixed, SKOS.narrowMatch, subject_c,
             (("alpha", RKAF.verdictTargetNarrower), ("beta", RKAF.verdictTargetNarrower))),
            ("related", resource, SKOS.relatedMatch, subject_c,
             (("alpha", RKAF.verdictRelated), ("beta", RKAF.verdictRelated))),
        )
        for name, subject, predicate, obj, machines in branches:
            assertion = _add_assertion(
                fixture.asserted,
                assertion_type=ATLAS.MappingAssertion,
                ring=ATLAS.subject,
                subject=subject,
                predicate=predicate,
                obj=obj,
                source_release=next(fixture.asserted.objects(subject, ATLAS.inRelease)),
                target_release=next(fixture.asserted.objects(obj, ATLAS.inRelease)),
                evidence_record=next(fixture.asserted.objects(subject, ATLAS.sourceRecord)),
                evidence_name=f"lattice-{name}",
                review_warrant="twoMachineAdjudication",
            )
            _add_adjudication(
                fixture.asserted,
                assertion=assertion,
                name=f"lattice-{name}",
                machines=machines,
            )
        _account_assertions(fixture)
        fixture.projection = atlas_validate._expected_projection(fixture.asserted)

    def rdf_pack_over_limit(fixture: Fixture) -> None:
        """Declare more decompressed content than one RDF pack may authorize.

        Only the declaration moves, so the case stays a few kilobytes: the
        validator has to refuse the manifest's own number before trusting it,
        which is what bounds the bytes a real pack can be made to produce.
        """

        def mutate(path: Path) -> None:
            manifest_path = path / "atlas-manifest.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest["packs"][0]["content"]["byteLength"] = (
                atlas_validate.NQUADS_MAX_CONTENT_BYTES + 1
            )
            payload = dict(manifest)
            payload.pop("canonicalPayloadDigest", None)
            manifest["canonicalPayloadDigest"] = atlas_validate.canonical_sha256(
                payload, terminal_lf=False
            )
            manifest_path.write_bytes(atlas_validate.canonical_json_bytes(manifest))

        fixture.post_write = mutate

    def source_accounting_unaccounted_assertion(fixture: Fixture) -> None:
        """Stop accounting for the assertions one record's evidence binds.

        The record keeps its represented resources, so the ledger still looks
        complete on the resource side and the mapping rule -- which only fires
        for a record naming no resource -- stays silent. Nothing but the
        unconditional ledger-versus-evidence comparison notices that a mapping
        assertion is now accounted for by no source record at all.
        """

        accounted = {
            str(record)
            for assertion in fixture.asserted.subjects(RDF.type, ATLAS.MappingAssertion)
            for evidence in fixture.asserted.subjects(RKAF.bindsAssertion, assertion)
            for record in fixture.asserted.objects(evidence, ATLAS.evidenceSourceRecord)
        }
        disposition = next(
            row
            for source in fixture.accounting["inputs"]
            for row in source["dispositions"]
            if row.get("atlasAssertions") and row["sourceRecord"] in accounted
        )
        del disposition["atlasAssertions"]

    def iri_credentials(fixture: Fixture) -> None:
        record = next(fixture.asserted.subjects(RDF.type, ATLAS.SourceRecord))
        _remove_subject_predicate(fixture.asserted, record, ATLAS.sourceLocator)
        fixture.asserted.add(
            (record, ATLAS.sourceLocator, URIRef("https://user:pass@example.org/x"))
        )

    return [
        ("no-derived", ["rdf", "dataset", "reasoning"], "valid", no_derived),
        ("rdf-literal-escaping", ["rdf", "dataset"], "valid", rdf_literal_escaping),
        (
            "source-native-thesaurus",
            ["rdf", "shacl", "dataset", "reasoning"],
            "valid",
            source_native_thesaurus,
        ),
        (
            "superseded-policy-revision",
            ["rdf", "dataset", "lifecycle"],
            "valid",
            valid_supersession,
        ),
        ("manifest-unknown-field", ["json"], "json.schema", unknown_manifest_field),
        ("dataset-digest-mismatch", ["dataset"], "pack.content", digest_mismatch),
        ("blank-node", ["rdf"], "rdf.blank-node", blank_node),
        ("label-missing-literal", ["shacl"], "shacl.data", label_missing_literal),
        ("non-english-label", ["shacl"], "shacl.data", non_english_label),
        ("duplicate-preferred-language", ["shacl"], "shacl.data", duplicate_preferred_language),
        ("mapping-missing-evidence", ["shacl", "dataset"], "shacl.data", missing_evidence),
        (
            "cross-ring-missing-evidence",
            ["shacl", "dataset"],
            "shacl.data",
            cross_ring_missing_evidence,
        ),
        (
            "cross-ring-endpoint-ring-reversal",
            ["shacl", "dataset"],
            "shacl.data",
            cross_ring_endpoint_reversal,
        ),
        (
            "cross-ring-disallowed-predicate",
            ["dataset"],
            "dataset.relation",
            cross_ring_disallowed_predicate,
        ),
        (
            "cross-ring-disallowed-pair",
            ["dataset"],
            "dataset.relation",
            cross_ring_disallowed_pair,
        ),
        ("wrong-ring-relation", ["dataset"], "dataset.relation", wrong_ring_relation),
        ("naked-projected-mapping", ["dataset"], "dataset.projection", naked_projection),
        ("derived-is-authoritative", ["shacl", "reasoning"], "shacl.data", derived_authoritative),
        ("derived-extra-type", ["dataset", "reasoning"], "dataset.graph-placement", derived_extra_type),
        ("derived-reflexive-output", ["dataset", "reasoning"], "dataset.derived-rule", derived_reflexive_output),
        ("derived-extra-branch", ["dataset", "reasoning"], "dataset.derived-rule", derived_extra_branch),
        ("derived-rescinded-input", ["dataset", "reasoning", "lifecycle"], "dataset.derived", derived_rescinded_input),
        (
            "lifecycle-event-kind-unknown",
            ["shacl", "dataset", "lifecycle"],
            "shacl.data",
            lifecycle_event_kind_unknown,
        ),
        (
            "lifecycle-effective-date-not-datetime",
            ["shacl", "dataset", "lifecycle"],
            "shacl.data",
            lifecycle_effective_date_not_datetime,
        ),
        (
            "lifecycle-applies-to-nonassertion",
            ["shacl", "dataset", "lifecycle"],
            "shacl.data",
            lifecycle_applies_to_nonassertion,
        ),
        (
            "lifecycle-rescission-names-target-release",
            ["shacl", "dataset", "lifecycle"],
            "shacl.data",
            lifecycle_rescission_names_target_release,
        ),
        ("source-accounting-missing-disposition", ["json", "dataset"], "source.accounting", missing_disposition),
        ("manifest-count-mismatch", ["dataset"], "dataset.counts", count_mismatch),
        ("acceptance-missing-gate", ["json", "dataset"], "acceptance.gates", missing_acceptance_gate),
        ("identifier-missing-value", ["shacl"], "shacl.data", identifier_missing_value),
        (
            "identifier-pair-conflict",
            ["dataset"],
            "dataset.identifier-uniqueness",
            identifier_pair_conflict,
        ),
        (
            "identifier-conflict-recorded",
            ["shacl", "dataset"],
            "valid",
            identifier_conflict_recorded,
        ),
        (
            "registry-conflict-single-entry",
            ["shacl", "dataset"],
            "shacl.data",
            registry_conflict_single_entry,
        ),
        (
            "registry-conflict-entries-mismatch",
            ["shacl", "dataset"],
            "dataset.identifier-uniqueness",
            registry_conflict_entries_mismatch,
        ),
        (
            "registry-conflict-severity-unknown",
            ["shacl", "dataset"],
            "shacl.data",
            registry_conflict_severity_unknown,
        ),
        (
            "registry-conflict-publication-blocking",
            ["shacl", "dataset"],
            "shacl.data",
            registry_conflict_publication_blocking,
        ),
        (
            "registry-conflict-detected-at-not-datetime",
            ["shacl", "dataset"],
            "shacl.data",
            registry_conflict_detected_at_not_datetime,
        ),
        ("mapping-wrong-endpoint-release", ["shacl", "dataset"], "shacl.data", wrong_endpoint_release),
        (
            "mapping-undated-value-crosswalk",
            ["shacl", "dataset"],
            "shacl.data",
            mapping_undated_value_crosswalk,
        ),
        (
            "mapping-undated-legal-identity",
            ["shacl", "dataset"],
            "shacl.data",
            mapping_undated_legal_identity,
        ),
        (
            "mapping-subject-ring-dated",
            ["shacl", "dataset"],
            "shacl.data",
            mapping_subject_ring_dated,
        ),
        (
            "mapping-period-end-before-start",
            ["shacl", "dataset"],
            "shacl.data",
            mapping_period_end_before_start,
        ),
        (
            "mapping-period-start-not-datetime",
            ["shacl", "dataset"],
            "shacl.data",
            mapping_period_start_not_datetime,
        ),
        ("asserted-naked-mapping", ["shacl", "dataset", "reasoning"], "shacl.data", naked_asserted_mapping),
        ("derived-naked-mapping", ["dataset", "reasoning"], "dataset.graph-placement", naked_derived_mapping),
        ("asserted-auxiliary-type-only", ["dataset"], "dataset.graph-placement", auxiliary_type_only),
        ("asserted-untyped-statement", ["dataset"], "dataset.graph-placement", untyped_asserted_statement),
        ("evidence-retargeted", ["rdf", "dataset"], "dataset.evidence-identity", evidence_retargeted),
        ("evidence-reviewer-retargeted", ["rdf", "dataset"], "dataset.evidence-identity", evidence_reviewer_retargeted),
        ("evidence-decision-not-approved", ["shacl", "dataset"], "shacl.data", evidence_decision_not_approved),
        ("evidence-attestor-kind-unknown", ["shacl", "dataset"], "shacl.data", evidence_attestor_kind_unknown),
        ("evidence-attested-at-not-datetime", ["shacl", "dataset"], "shacl.data", evidence_attested_at_not_datetime),
        ("evidence-function-unknown", ["shacl", "dataset"], "shacl.data", evidence_function_unknown),
        ("evidence-warrant-unsanctioned", ["shacl", "dataset"], "shacl.data", evidence_warrant_unsanctioned),
        ("assertion-asserted-at-not-datetime", ["shacl", "dataset"], "shacl.data", assertion_asserted_at_not_datetime),
        ("release-membership-mode-unknown", ["shacl", "dataset"], "shacl.data", release_membership_mode_unknown),
        ("adoption-without-referent", ["shacl", "dataset"], "shacl.data", adoption_without_referent),
        ("adoption-chain-cycle", ["rdf", "dataset"], "dataset.evidence-adoption", adoption_chain_cycle),
        ("policy-payload-changed", ["rdf", "dataset"], "dataset.assertion-identity", policy_payload_changed),
        ("supersession-without-event", ["dataset", "lifecycle"], "dataset.supersession", supersession_without_event),
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
        (
            "skosxl-label-role-overlap",
            ["shacl", "dataset", "rdf"],
            "shacl.data",
            label_role_overlap,
        ),
        ("skos-mapping-conflict", ["shacl", "dataset", "reasoning"], "dataset.skos-integrity", skos_mapping_conflict),
        ("skos-mapping-reverse-conflict", ["dataset", "reasoning"], "dataset.skos-integrity", skos_mapping_reverse_conflict),
        ("skos-mapping-transitive-conflict", ["dataset", "reasoning"], "dataset.skos-integrity", skos_mapping_transitive_conflict),
        ("skos-mapping-hierarchy-conflict", ["dataset", "reasoning"], "dataset.skos-integrity", skos_mapping_hierarchy_conflict),
        ("skos-hierarchy-conflict", ["shacl", "dataset", "reasoning"], "dataset.skos-integrity", skos_hierarchy_conflict),
        (
            "unjustified-thesaurus-related",
            ["dataset", "reasoning"],
            "dataset.skos-integrity",
            unjustified_thesaurus_related,
        ),
        ("assertion-extra-property", ["shacl", "dataset"], "shacl.data", assertion_extra_property),
        ("validator-identity-mismatch", ["json", "dataset"], "json.schema", wrong_validator_identity),
        ("subject-scheme-disagreement", ["shacl", "rdf"], "shacl.data", subject_scheme_disagreement),
        ("native-payload-noncanonical", ["rdf", "dataset"], "dataset.native-payload", noncanonical_native_payload),
        (
            "native-payload-digest-mismatch",
            ["rdf", "dataset"],
            "dataset.native-payload-digest",
            native_payload_digest_mismatch,
        ),
        ("zstd-packs", ["dataset"], "valid", zstd_packs),
        ("partitioned-packs", ["dataset"], "valid", partitioned_packs),
        ("rescission-lifecycle", ["dataset", "lifecycle"], "valid", rescission_lifecycle),
        ("skosxl-hidden-label", ["shacl", "dataset"], "valid", skosxl_hidden_label),
        (
            "qualified-three-machine-support",
            ["rdf", "dataset"],
            "valid",
            qualified_three_machine_support,
        ),
        (
            "adjudication-single-proof",
            ["dataset"],
            "dataset.adjudication-independence",
            adjudication_single_proof,
        ),
        (
            "adjudication-same-validator-actor",
            ["dataset"],
            "dataset.adjudication-independence",
            adjudication_same_validator_actor,
        ),
        (
            "adjudication-same-independence-group",
            ["dataset"],
            "dataset.adjudication-independence",
            adjudication_same_independence_group,
        ),
        (
            "adjudication-same-provider",
            ["dataset"],
            "dataset.adjudication-independence",
            adjudication_same_provider,
        ),
        (
            "adjudication-same-provider-model",
            ["dataset"],
            "dataset.adjudication-independence",
            adjudication_same_provider_model,
        ),
        (
            "adjudication-same-response-artifact",
            ["dataset"],
            "dataset.adjudication-independence",
            adjudication_same_response_artifact,
        ),
        (
            "adjudication-mismatched-sealed-request",
            ["dataset"],
            "dataset.adjudication-independence",
            adjudication_mismatched_sealed_request,
        ),
        (
            "adjudication-discarded-support",
            ["dataset"],
            "dataset.adjudication-support",
            adjudication_discarded_support,
        ),
        (
            "adjudication-foreign-comparison",
            ["dataset"],
            "dataset.adjudication-support",
            adjudication_foreign_comparison,
        ),
        (
            "adjudication-relation-not-licensed",
            ["dataset"],
            "dataset.adjudication-lattice",
            adjudication_relation_not_licensed,
        ),
        (
            "adjudication-verdicts-disagree",
            ["dataset"],
            "dataset.adjudication-lattice",
            adjudication_verdicts_disagree,
        ),
        (
            "adjudication-proof-input-digest",
            ["dataset"],
            "dataset.adjudication-input",
            adjudication_proof_input_digest,
        ),
        (
            "adjudication-proof-record-digest",
            ["dataset"],
            "dataset.adjudication-identity",
            adjudication_proof_record_digest,
        ),
        (
            "adjudication-comparison-retargeted",
            ["dataset"],
            "dataset.adjudication",
            adjudication_comparison_retargeted,
        ),
        (
            "adjudication-response-artifact-cardinality",
            ["shacl", "dataset"],
            "shacl.data",
            adjudication_response_artifact_cardinality,
        ),
        (
            "adjudication-licensing-proof-refused",
            ["dataset"],
            "dataset.adjudication",
            adjudication_licensing_proof_refused,
        ),
        (
            "adjudication-proof-type-not-machine",
            ["shacl", "dataset"],
            "shacl.data",
            adjudication_proof_type_not_machine,
        ),
        (
            "adjudication-evaluated-at-not-datetime",
            ["shacl", "dataset"],
            "shacl.data",
            adjudication_evaluated_at_not_datetime,
        ),
        (
            "adjudication-licensed-by-conflicted-comparison",
            ["dataset"],
            "dataset.adjudication",
            adjudication_licensed_by_conflicted_comparison,
        ),
        (
            "adjudication-warrant-without-comparison",
            ["dataset"],
            "dataset.adjudication",
            adjudication_warrant_without_comparison,
        ),
        (
            "adjudication-foreign-snapshot",
            ["dataset"],
            "dataset.adjudication",
            adjudication_foreign_snapshot,
        ),
        (
            "adjudication-proof-snapshot-drift",
            ["dataset"],
            "dataset.adjudication",
            adjudication_proof_snapshot_drift,
        ),
        (
            "adjudication-issuer-incomplete",
            ["shacl", "dataset"],
            "shacl.data",
            adjudication_issuer_incomplete,
        ),
        (
            "adjudication-lineage-incomplete",
            ["shacl", "dataset"],
            "shacl.data",
            adjudication_lineage_incomplete,
        ),
        (
            "adjudication-comparison-incomplete",
            ["shacl", "dataset"],
            "shacl.data",
            adjudication_comparison_incomplete,
        ),
        (
            "adjudication-proof-rationale-empty",
            ["shacl", "dataset"],
            "shacl.data",
            adjudication_proof_rationale_empty,
        ),
        (
            "adjudication-artifact-scheme-unknown",
            ["shacl", "dataset"],
            "shacl.data",
            adjudication_artifact_scheme_unknown,
        ),
        (
            "adjudication-request-artifact-unbundled",
            ["dataset"],
            "dataset.adjudication-input",
            adjudication_request_artifact_unbundled,
        ),
        (
            "adjudication-request-digest-mismatch",
            ["dataset"],
            "dataset.adjudication-input",
            adjudication_request_digest_mismatch,
        ),
        (
            "adjudication-response-artifact-unbundled",
            ["dataset"],
            "dataset.adjudication-input",
            adjudication_response_artifact_unbundled,
        ),
        (
            "adjudication-endpoint-artifact-drift",
            ["dataset"],
            "dataset.adjudication-input",
            adjudication_endpoint_artifact_drift,
        ),
        (
            "adjudication-input-context-hash",
            ["dataset"],
            "dataset.adjudication-input",
            adjudication_input_context_hash,
        ),
        (
            "adjudication-refused-comparison-record",
            ["rdf", "dataset"],
            "valid",
            adjudication_refused_comparison_record,
        ),
        (
            "qualified-lattice-branches",
            ["rdf", "dataset", "reasoning"],
            "valid",
            qualified_lattice_branches,
        ),
        ("rdf-pack-over-limit", ["rdf"], "rdf.resource-limit", rdf_pack_over_limit),
        (
            "source-accounting-unaccounted-assertion",
            ["json", "dataset"],
            "source.accounting",
            source_accounting_unaccounted_assertion,
        ),
        ("iri-credentials", ["rdf"], "rdf.term", iri_credentials),
    ]


# REF-019's `exactDistributionReuse` philosophy, applied to this builder's own
# corpus: record what the output was made from, and skip remaking it when
# nothing that determines it has moved.
#
# Beside the corpus, never inside it. `build()` compares the committed
# `fixtures/` tree against a freshly built one as a whole-directory equality,
# so a receipt written into that tree would report itself as an unexpected
# extra file and fail the very check it exists to speed up.
RECEIPT_PATH = atlas_validate.BINDING_ROOT / "fixtures-receipt.json"
RECEIPT_TYPE = "AtlasFixtureBuildReceipt"
RECEIPT_VERSION = "1.0"

# Everything read to produce the corpus. The binding already maintains these
# lists for its own pinning, so the receipt reuses them rather than minting a
# second, driftable inventory: `BINDING_BUNDLE_PATHS` is the semantic contract
# and `BINDING_TOOL_PATHS` is the programs that read it. The receipt needs
# both, because its question is narrower than the manifest's -- not "what does
# conformance mean here" but "what determines these exact bytes", and a
# builder edit or a library bump changes the bytes without touching the
# contract. Two adjustments: `fixtures/corpus.json` is dropped because it is an
# *output* (the builder passes freshly computed bytes to `_binding_digests` as
# an override rather than reading the committed file), and the adapter under
# `src/` is added because `_write_case` pins its digest into every case.
RECEIPT_OUTPUT_RELATIVE = Path("fixtures/corpus.json")
RECEIPT_EXTERNAL_INPUTS = (Path("src/refspec/atlas/v3_source_data.py"),)
def _receipt_runtime_distributions() -> list[str]:
    """The binding's declared dependencies, read from the file that declares them.

    The corpus bytes depend on these implementations and not merely on the
    version pins beside them: rdflib serializes the N-Quads, and the zstd
    transports come from `backports.zstd` below 3.14 and the standard library
    at and above it. Requirements are parsed rather than restated so the
    receipt cannot list a stale set -- adding a dependency to requirements.txt
    is enough, with nothing here to remember to update.
    """

    names = []
    for line in (atlas_validate.BINDING_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        requirement = line.split("#", 1)[0].split(";", 1)[0].strip()
        if requirement:
            names.append(re.split(r"[=<>!~\[]", requirement, maxsplit=1)[0].strip())
    return sorted(names)


def _receipt_input_paths() -> list[Path]:
    paths = [
        atlas_validate.BINDING_ROOT / relative
        for relative in (*atlas_validate.BINDING_BUNDLE_PATHS, *atlas_validate.BINDING_TOOL_PATHS)
        if relative != RECEIPT_OUTPUT_RELATIVE
    ]
    paths.extend(sorted(atlas_validate.SCHEMA_ROOT.glob("*.schema.json")))
    paths.extend(atlas_validate.REPOSITORY_ROOT / relative for relative in RECEIPT_EXTERNAL_INPUTS)
    return paths


def _receipt_inputs() -> dict[str, str]:
    return {
        path.relative_to(atlas_validate.REPOSITORY_ROOT).as_posix(): atlas_validate.file_sha256(path)
        for path in _receipt_input_paths()
    }


def _receipt_runtime() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    runtime = {"python": f"{sys.version_info.major}.{sys.version_info.minor}"}
    for name in _receipt_runtime_distributions():
        try:
            runtime[name] = version(name)
        except PackageNotFoundError:
            runtime[name] = "absent"
    return runtime


def _fixtures_tree_digest(root: Path) -> str:
    rows = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": atlas_validate.file_sha256(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    return atlas_validate.canonical_sha256(rows, terminal_lf=False)


def _current_receipt() -> dict[str, Any]:
    return {
        "fixturesDigest": _fixtures_tree_digest(FIXTURE_ROOT),
        "inputs": _receipt_inputs(),
        "runtime": _receipt_runtime(),
        "type": RECEIPT_TYPE,
        "version": RECEIPT_VERSION,
    }


def _receipt_is_current() -> bool:
    """Fail closed: any doubt at all returns False and the full rebuild runs."""

    try:
        recorded = json.loads(RECEIPT_PATH.read_bytes())
        if recorded.get("type") != RECEIPT_TYPE or recorded.get("version") != RECEIPT_VERSION:
            return False
        if recorded.get("inputs") != _receipt_inputs():
            return False
        if recorded.get("runtime") != _receipt_runtime():
            return False
        return recorded.get("fixturesDigest") == _fixtures_tree_digest(FIXTURE_ROOT)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def build(*, check: bool) -> None:
    if check and _receipt_is_current():
        print(
            f"Atlas 3.0 fixtures are current: receipt matches {len(_receipt_inputs())} "
            "inputs and the committed corpus"
        )
        return
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
        baseline_asserted=base.asserted,
        binding_digests=binding_digests,
        distribution_id="urn:ref:atlas-fixture:distribution:all-resource-profiles",
    )
    for name, _, expected_or_issue, mutation in mutations:
        fixture = copy.deepcopy(base)
        mutation(fixture)
        if fixture.reseal_adjudication:
            _reseal_adjudication(fixture.asserted)
        if expected_or_issue == "valid":
            case_root = temporary_root / "valid" / name
            expected = "valid"
        else:
            case_root = temporary_root / "invalid" / name
            expected = "invalid"
        _write_case(
            case_root,
            fixture,
            baseline_asserted=base.asserted,
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
        # The slow path just proved the committed tree is exactly what this
        # builder produces from these inputs. Record that so the next check can
        # answer from the receipt.
        RECEIPT_PATH.write_bytes(atlas_validate.canonical_json_bytes(_current_receipt()))
        print(f"Atlas 3.0 fixtures rebuilt and compared: {len(expected_files)} files identical")
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
    RECEIPT_PATH.write_bytes(atlas_validate.canonical_json_bytes(_current_receipt()))
    print(f"Atlas 3.0 fixtures written: {len(expected_files)} files, receipt over {len(_receipt_inputs())} inputs")


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
