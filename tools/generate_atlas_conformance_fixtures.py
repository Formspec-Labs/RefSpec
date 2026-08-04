#!/usr/bin/env python3
"""Generate or verify the non-vacuous atlas conformance distributions.

Every other fixture in `bindings/atlas/1.0/fixtures` carries zero mapping
candidates, so the qualification path — two independent machines, a resolvable
sealed input, one `searchOnly` mapping — had no conforming example a reader
could accept. This builds that example from the producer, then derives the
invalid distributions from it by the smallest possible byte edit, so each
refusal is isolated to exactly one forged fact.

The derived cases are deliberately unbuildable by the producer: a distribution
whose input context does not resolve is precisely what the producer now
refuses to emit, so only a forgery can exercise the consumer-side check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from refspec import binding
from refspec.atlas import (
    CrosswalkArtifact,
    CrosswalkBundle,
    MachineValidation,
    MappingCandidate,
    PinnedRulespecCoreRelease,
    VocabularyAtlasError,
    build_vocabulary_atlas,
)
from refspec.managed_release import (
    ManagedReleaseExpression,
    ManagedReleaseMember,
    ManagedReleaseView,
)
from refspec.release_graph import rulespec_graph_digest
from refspec.storage import canonical_json

BINDING_ROOT = ROOT / "bindings" / "atlas" / "1.0"
FIXTURE_ROOT = BINDING_ROOT / "fixtures"
CORPUS_PATH = FIXTURE_ROOT / "corpus.json"

# Dated in-place amendments to binding 1.0, oldest first. Two landed on the
# same day, so the later one carries a name as well: a bare date could not tell
# a consumer which of the two a pinned corpus predates.
AMENDMENTS = ("2026-08-02", "2026-08-02-hierarchy", "2026-08-03-relation-adjudication")

SOURCE_PUBLICATION = "urn:ref:conformance:alpha-thesaurus:2026"
TARGET_PUBLICATION = "urn:ref:conformance:beta-thesaurus:2026"
SOURCE_RELEASE = "urn:ref:conformance:alpha-thesaurus:2026:reference-resource-release"
TARGET_RELEASE = "urn:ref:conformance:beta-thesaurus:2026:reference-resource-release"
CLOSE_MATCH = "http://www.w3.org/2004/02/skos/core#closeMatch"

# Two concepts per side: one label-equal pair that qualifies, and one
# near-miss pair that must stay ineligible with a single validation.
SOURCE_CONCEPTS = (
    ("urn:ref:conformance:alpha:energy-policy", "Energy policy"),
    ("urn:ref:conformance:alpha:water-pollution", "Water pollution"),
)
TARGET_CONCEPTS = (
    ("urn:ref:conformance:beta:energy-policy", "energy POLICY "),
    ("urn:ref:conformance:beta:water-pollution-control", "Water pollution control"),
)

# The v2 distribution is built separately for the same reason as the hierarchy
# one: the v1 qualification fixture must keep its published bytes, and a reader
# needs one distribution that exercises every relation the lattice can emit.
# One candidate per outcome, including the `related` agreement that deliberately
# emits no mapping at all.
V2_RELATIONS = (
    ("same", "same", "exactMatch"),
    # The lattice downgrade: one machine claimed identity, one refused it, and
    # the pair qualifies at the weaker claim.
    ("same", "near_same", "closeMatch"),
    ("target_is_broader", "target_is_broader", "broadMatch"),
    ("target_is_narrower", "target_is_narrower", "narrowMatch"),
    # Agreed, typed, and deliberately not a mapping.
    ("related", "related", None),
    # A real disagreement about direction safety; neither relation may be
    # emitted, because emitting either overrules a machine on its own claim.
    ("near_same", "target_is_broader", None),
)
#: One sealed reason per verdict, so every relation the corpus emits carries the
#: prose a reader would need to judge it.
V2_VERDICT_REASONS = {
    "same": "The two labels are house-style variants of one concept; treating them as one cannot mislead.",
    "near_same": "Substitution is safe both ways for search, but the two are not plainly the same concept.",
    "target_is_broader": "The target is the wider field; the source is one topic inside it.",
    "target_is_narrower": "The source is the wider concept; the target names one specific case of it.",
    "related": "An actor and the activity named by the other concept: associated, but neither contains the other.",
}
V2_SOURCE_CONCEPTS = (
    ("urn:ref:conformance:alpha:energy-policy", "Energy policy"),
    ("urn:ref:conformance:alpha:water-pollution", "Water pollution"),
    ("urn:ref:conformance:alpha:fishery-policy", "Fishery policy"),
    ("urn:ref:conformance:alpha:wind-power", "Wind power"),
    ("urn:ref:conformance:alpha:terrorism", "Terrorism"),
    ("urn:ref:conformance:alpha:drugs", "Drugs"),
)
V2_TARGET_CONCEPTS = (
    ("urn:ref:conformance:beta:energy-policy", "energy POLICY "),
    ("urn:ref:conformance:beta:water-pollution-control", "Water pollution control"),
    ("urn:ref:conformance:beta:marine-resource-policy", "Marine resource policy"),
    ("urn:ref:conformance:beta:offshore-wind-power", "Offshore wind power"),
    ("urn:ref:conformance:beta:terrorists", "Terrorists"),
    ("urn:ref:conformance:beta:controlled-drugs", "Controlled drugs"),
)

# The hierarchy distribution is built separately so the qualification fixture
# keeps proving exactly one thing. Its labels deliberately cluster with
# nothing on the target side: this case is about edges, not equal strings.
BROADER = "http://www.w3.org/2004/02/skos/core#broader"
NARROWER = "http://www.w3.org/2004/02/skos/core#narrower"
HIERARCHY_CONCEPTS = (
    ("urn:ref:conformance:alpha:environmental-policy", "Environmental policy"),
    ("urn:ref:conformance:alpha:renewable-energy-policy", "Renewable energy policy"),
    ("urn:ref:conformance:alpha:marine-policy", "Marine policy"),
    ("urn:ref:conformance:alpha:offshore-wind-policy", "Offshore wind policy"),
)
# One root, a two-step chain, and one concept under two parents. Polyhierarchy
# is not an edge case to a real thesaurus: ELSST R6 places 162 of its concepts
# under more than one broader concept.
HIERARCHY_EDGES = (
    (
        "urn:ref:conformance:alpha:renewable-energy-policy",
        "urn:ref:conformance:alpha:environmental-policy",
    ),
    (
        "urn:ref:conformance:alpha:marine-policy",
        "urn:ref:conformance:alpha:environmental-policy",
    ),
    (
        "urn:ref:conformance:alpha:offshore-wind-policy",
        "urn:ref:conformance:alpha:renewable-energy-policy",
    ),
    (
        "urn:ref:conformance:alpha:offshore-wind-policy",
        "urn:ref:conformance:alpha:marine-policy",
    ),
)
ABSENT_CONCEPT = "urn:ref:conformance:alpha:absent-concept"

_SOURCE_DIGEST = "sha256:" + "1" * 64
_TARGET_DIGEST = "sha256:" + "2" * 64
_SCHEMA_DIGEST = "sha256:" + "3" * 64
_VALIDATOR_DIGEST = "sha256:" + "4" * 64
_FIXTURE_DIGEST = "sha256:" + "5" * 64
_FOREIGN_DIGEST = "sha256:" + "f" * 64


class _ConformanceReleaseSource:
    """A verified view plus the exact pin this build records for it.

    The portable corpus cannot ship an upstream managed-release bundle, and a
    consumer of a distribution never reads one, so the fixture supplies the
    verified view directly through the producer's documented protocol.
    """

    def __init__(self, view: ManagedReleaseView, manifest_digest: str) -> None:
        self._view = view
        self._manifest_digest = manifest_digest

    def verified_view(self) -> ManagedReleaseView:
        return self._view

    def pin(self) -> dict[str, Any]:
        return {
            "role": "ManagedReleaseView",
            "manifestDigest": self._manifest_digest,
            "publicationReleaseId": self._view.release_id,
            "rulespecGraph": {
                "id": self._view.rulespec_graph_id,
                "digest": rulespec_graph_digest(_plain(self._view.rulespec_graph)),
            },
        }


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain(child) for child in value]
    return value


def _view(
    *,
    publication: str,
    release: str,
    concepts: Sequence[tuple[str, str]],
    release_digest: str,
    edges: Sequence[tuple[str, str]] = (),
) -> ManagedReleaseView:
    # A real thesaurus states both directions, so the fixture does too:
    # otherwise the happy path never exercises the inverse-agreement check.
    broader_by_child: dict[str, list[dict[str, str]]] = {}
    narrower_by_parent: dict[str, list[dict[str, str]]] = {}
    for child, parent in edges:
        broader_by_child.setdefault(child, []).append({"@id": parent})
        narrower_by_parent.setdefault(parent, []).append({"@id": child})
    member_records = tuple(
        MappingProxyType(
            {
                "@id": member,
                "@type": "https://rulespec.org/ns/v1#RegisteredConcept",
                "http://www.w3.org/2004/02/skos/core#prefLabel": label,
                **({BROADER: tuple(broader_by_child[member])} if member in broader_by_child else {}),
                **({NARROWER: tuple(narrower_by_parent[member])} if member in narrower_by_parent else {}),
            }
        )
        for member, label in concepts
    )
    release_record = MappingProxyType(
        {
            "@id": release,
            "@type": "https://rulespec.org/ns/v1#ReferenceResourceRelease",
            "http://www.w3.org/ns/prov#hadMember": tuple(
                member for member, _ in concepts
            ),
            "https://rulespec.org/ns/v1#referenceReleaseDigest": release_digest,
        }
    )
    members = {
        member: ManagedReleaseMember(
            member_iri=member,
            release_iri=release,
            scheme_iri=release + ":scheme",
            record=record,
        )
        for (member, _), record in zip(concepts, member_records, strict=True)
    }
    expressions = tuple(
        ManagedReleaseExpression(
            expression_id=member + ":expression",
            member_iri=member,
            indexed_text=label.casefold(),
            original_literal=label,
            language_tag="en",
            semantic_property_iri="http://www.w3.org/2004/02/skos/core#prefLabel",
            source_property_or_path="prefLabel",
            record=MappingProxyType({}),
            label_role="preferred",
            source_status="current",
        )
        for member, label in concepts
    )
    return ManagedReleaseView(
        _release_id=publication,
        _rulespec_graph_id=publication + ":graph",
        _rulespec_graph=MappingProxyType({"@graph": (release_record, *member_records)}),
        _expression_corpus_snapshot=MappingProxyType(
            {"id": publication + ":corpus", "digest": release_digest}
        ),
        _members=MappingProxyType(members),
        _expressions=expressions,
        _relations=(),
        _lifecycle_participants=(),
        _concept_mappings=(),
        _release_graph_validation_receipt=MappingProxyType({}),
    )


def _core_release(directory: Path) -> PinnedRulespecCoreRelease:
    preimage: dict[str, Any] = {
        "record_type": "RulespecCoreRelease",
        "release_status": "fixture",
        "version": "0.2.0-pre.9+atlas-conformance",
        "schema_artifacts": [
            {
                "artifact_digest": _SCHEMA_DIGEST,
                "media_type": "application/schema+json",
                "name": "compiled/json-schema/core/artifact.schema.json",
            }
        ],
        "validator_artifacts": [
            {
                "artifact_digest": _VALIDATOR_DIGEST,
                "media_type": "text/x-python",
                "name": "tools/ci_validate.py",
            }
        ],
        "conformance_fixture_artifacts": [
            {
                "artifact_digest": _FIXTURE_DIGEST,
                "media_type": "application/ld+json",
                "name": "fixtures/ailineage-positive.jsonld",
            }
        ],
    }
    release_digest = (
        "sha256:" + hashlib.sha256(canonical_json(preimage).encode("utf-8")).hexdigest()
    )
    release_id = "urn:rulespec:core:" + release_digest.removeprefix("sha256:")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "rulespec-core.json"
    path.write_text(
        json.dumps(
            {**preimage, "release_digest": release_digest, "release_id": release_id},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return PinnedRulespecCoreRelease.open(
        path,
        expected_file_digest="sha256:"
        + hashlib.sha256(path.read_bytes()).hexdigest(),
        expected_release_id=release_id,
        expected_release_digest=release_digest,
    )


def _input_context(source_label: str, target_label: str) -> CrosswalkArtifact:
    return CrosswalkArtifact.create(
        role="inputContext",
        media_type="application/json",
        content={
            "protocol": "refspec-atlas-model-input-v1",
            "sourceLabel": source_label,
            "sourceRelease": SOURCE_RELEASE,
            "targetLabel": target_label,
            "targetRelease": TARGET_RELEASE,
        },
    )


def _candidate(
    *,
    source_member: str,
    target_member: str,
    evidence: CrosswalkArtifact,
    input_digest: str,
    generated_at: str,
) -> MappingCandidate:
    return MappingCandidate.create(
        source_member=source_member,
        source_release=SOURCE_RELEASE,
        target_member=target_member,
        target_release=TARGET_RELEASE,
        proposed_relation=CLOSE_MATCH,
        generator_kind="aiModel",
        generator_actor="urn:ref:conformance:generator",
        generator_provider="urn:ref:conformance:provider:generator",
        model_id="conformance-crosswalk-generator",
        model_version="1",
        prompt_template="urn:ref:conformance:prompt:crosswalk:v1",
        input_context_digest=input_digest,
        temperature="0",
        evidence=(evidence.reference(),),
        generated_at=generated_at,
        seed=11,
    )


def _request(candidate: MappingCandidate, input_digest: str) -> CrosswalkArtifact:
    return CrosswalkArtifact.create(
        role="validationRequest",
        media_type="application/json",
        content={
            "candidate": candidate.reference(),
            "inputDigest": input_digest,
            "protocol": "refspec-atlas-machine-validation-v1",
        },
    )


def _response(
    candidate: MappingCandidate,
    request: CrosswalkArtifact,
    *,
    input_digest: str,
    actor: str,
    provider: str,
    provider_model_id: str,
    reason: str = "",
) -> CrosswalkArtifact:
    content: dict[str, Any] = {
        "candidate": candidate.reference(),
        "deterministicChecksPassed": True,
        "inputDigest": input_digest,
        "outcome": "supports",
        "provider": provider,
        "providerModelId": provider_model_id,
        "requestArtifact": request.reference(),
        "validatorActor": actor,
    }
    # A corpus whose responses said nothing could not tell a reader that
    # projects the sealed reason from one that drops it.
    if reason:
        content["reason"] = reason
    return CrosswalkArtifact.create(
        role="validationResponse",
        media_type="application/json",
        content=content,
    )


def _validation(
    candidate: MappingCandidate,
    request: CrosswalkArtifact,
    response: CrosswalkArtifact,
    *,
    input_digest: str,
    actor: str,
    group: str,
    provider: str,
    provider_model_id: str,
    completed_at: str,
    verdict_relation: str | None = None,
) -> MachineValidation:
    return MachineValidation.create(
        candidate=candidate.reference(),
        validator_kind="aiModel",
        validator_actor=actor,
        independence_group=group,
        provider=provider,
        provider_model_id=provider_model_id,
        sealed_input_digest=input_digest,
        request_artifact=request.reference(),
        response_artifact=response.reference(),
        deterministic_checks_passed=True,
        outcome="supports",
        completed_at=completed_at,
        verdict_relation=verdict_relation,
    )


def _qualified_bundle() -> CrosswalkBundle:
    """One candidate that qualifies and one that must not."""

    artifacts: list[CrosswalkArtifact] = []
    candidates: list[MappingCandidate] = []
    validations: list[MachineValidation] = []

    # Qualifying pair: equal normalized labels, two independent machines.
    context = _input_context("Energy policy", "energy POLICY ")
    evidence = CrosswalkArtifact.create(
        role="evidence",
        media_type="application/json",
        content={
            "method": "normalized-preferred-label-equality",
            "normalizedLabel": "energy policy",
            "version": "1",
        },
    )
    candidate = _candidate(
        source_member=SOURCE_CONCEPTS[0][0],
        target_member=TARGET_CONCEPTS[0][0],
        evidence=evidence,
        input_digest=context.content_digest,
        generated_at="2026-08-02T09:00:00Z",
    )
    request = _request(candidate, context.content_digest)
    first = _response(
        candidate,
        request,
        input_digest=context.content_digest,
        actor="urn:ref:conformance:validator:first",
        provider="urn:ref:conformance:provider:first",
        provider_model_id="provider-model-first",
        reason="Both labels name the same policy area; substitution is safe in both directions.",
    )
    second = _response(
        candidate,
        request,
        input_digest=context.content_digest,
        actor="urn:ref:conformance:validator:second",
        provider="urn:ref:conformance:provider:second",
        provider_model_id="provider-model-other",
        reason="Agreed; the two concepts index the same documents under different house style.",
    )
    validations.extend(
        (
            _validation(
                candidate,
                request,
                first,
                input_digest=context.content_digest,
                actor="urn:ref:conformance:validator:first",
                group="urn:ref:conformance:independence-group:first",
                provider="urn:ref:conformance:provider:first",
                provider_model_id="provider-model-first",
                completed_at="2026-08-02T09:05:00Z",
            ),
            _validation(
                candidate,
                request,
                second,
                input_digest=context.content_digest,
                actor="urn:ref:conformance:validator:second",
                group="urn:ref:conformance:independence-group:second",
                provider="urn:ref:conformance:provider:second",
                provider_model_id="provider-model-other",
                completed_at="2026-08-02T09:06:00Z",
            ),
        )
    )
    artifacts.extend((context, evidence, request, first, second))
    candidates.append(candidate)

    # Near miss: one machine only, so the gate must leave it ineligible.
    near_context = _input_context("Water pollution", "Water pollution control")
    near_evidence = CrosswalkArtifact.create(
        role="evidence",
        media_type="application/json",
        content={
            "method": "normalized-preferred-label-overlap",
            "normalizedOverlap": "water pollution",
            "version": "1",
        },
    )
    near_candidate = _candidate(
        source_member=SOURCE_CONCEPTS[1][0],
        target_member=TARGET_CONCEPTS[1][0],
        evidence=near_evidence,
        input_digest=near_context.content_digest,
        generated_at="2026-08-02T09:10:00Z",
    )
    near_request = _request(near_candidate, near_context.content_digest)
    near_response = _response(
        near_candidate,
        near_request,
        input_digest=near_context.content_digest,
        actor="urn:ref:conformance:validator:first",
        provider="urn:ref:conformance:provider:first",
        provider_model_id="provider-model-first",
        reason="The target names control measures, not the pollution itself; the source is wider.",
    )
    validations.append(
        _validation(
            near_candidate,
            near_request,
            near_response,
            input_digest=near_context.content_digest,
            actor="urn:ref:conformance:validator:first",
            group="urn:ref:conformance:independence-group:first",
            provider="urn:ref:conformance:provider:first",
            provider_model_id="provider-model-first",
            completed_at="2026-08-02T09:15:00Z",
        )
    )
    artifacts.extend((near_context, near_evidence, near_request, near_response))
    candidates.append(near_candidate)

    return CrosswalkBundle.create(
        artifacts=tuple(artifacts),
        mapping_candidates=tuple(candidates),
        machine_validations=tuple(validations),
    )


def _v2_bundle() -> CrosswalkBundle:
    """One candidate per lattice outcome, sealed at protocol v2.

    A corpus that only carried v1 bundles could not tell a reader that
    implements the agreement lattice from one that publishes whatever relation a
    producer wrote down.
    """

    artifacts: list[CrosswalkArtifact] = []
    candidates: list[MappingCandidate] = []
    validations: list[MachineValidation] = []

    for index, (first_verdict, second_verdict, _) in enumerate(V2_RELATIONS):
        source_member, source_label = V2_SOURCE_CONCEPTS[index]
        target_member, target_label = V2_TARGET_CONCEPTS[index]
        context = _input_context(source_label, target_label)
        evidence = CrosswalkArtifact.create(
            role="evidence",
            media_type="application/json",
            content={
                "method": "sealed-label-comparison",
                "normalizedLabel": source_label.strip().casefold(),
                "version": "1",
            },
        )
        candidate = _candidate(
            source_member=source_member,
            target_member=target_member,
            evidence=evidence,
            input_digest=context.content_digest,
            generated_at=f"2026-08-03T09:{index:02d}:00Z",
        )
        request = _request(candidate, context.content_digest)
        artifacts.extend((context, evidence, request))
        candidates.append(candidate)
        for suffix, verdict in (("first", first_verdict), ("second", second_verdict)):
            actor = f"urn:ref:conformance:validator:{suffix}"
            provider = f"urn:ref:conformance:provider:{suffix}"
            provider_model_id = f"provider-model-{suffix}"
            response = _response(
                candidate,
                request,
                input_digest=context.content_digest,
                actor=actor,
                provider=provider,
                provider_model_id=provider_model_id,
                reason=V2_VERDICT_REASONS[verdict],
            )
            artifacts.append(response)
            validations.append(
                _validation(
                    candidate,
                    request,
                    response,
                    input_digest=context.content_digest,
                    actor=actor,
                    group=f"urn:ref:conformance:independence-group:{suffix}",
                    provider=provider,
                    provider_model_id=provider_model_id,
                    completed_at=f"2026-08-03T09:{index:02d}:30Z",
                    verdict_relation=verdict,
                )
            )

    return CrosswalkBundle.create(
        artifacts=tuple(artifacts),
        mapping_candidates=tuple(candidates),
        machine_validations=tuple(validations),
    )


def _build_v2_distribution(work: Path) -> tuple[bytes, bytes]:
    releases = (
        _ConformanceReleaseSource(
            _view(
                publication=SOURCE_PUBLICATION,
                release=SOURCE_RELEASE,
                concepts=V2_SOURCE_CONCEPTS,
                release_digest=_SOURCE_DIGEST,
            ),
            _SOURCE_DIGEST,
        ),
        _ConformanceReleaseSource(
            _view(
                publication=TARGET_PUBLICATION,
                release=TARGET_RELEASE,
                concepts=V2_TARGET_CONCEPTS,
                release_digest=_TARGET_DIGEST,
            ),
            _TARGET_DIGEST,
        ),
    )
    asset = build_vocabulary_atlas(
        releases,
        rulespec_core=_core_release(work),
        crosswalks=(_v2_bundle(),),
    )
    return asset.payload, asset.manifest_bytes()


def _build_valid_distribution(work: Path) -> tuple[bytes, bytes]:
    releases = (
        _ConformanceReleaseSource(
            _view(
                publication=SOURCE_PUBLICATION,
                release=SOURCE_RELEASE,
                concepts=SOURCE_CONCEPTS,
                release_digest=_SOURCE_DIGEST,
            ),
            _SOURCE_DIGEST,
        ),
        _ConformanceReleaseSource(
            _view(
                publication=TARGET_PUBLICATION,
                release=TARGET_RELEASE,
                concepts=TARGET_CONCEPTS,
                release_digest=_TARGET_DIGEST,
            ),
            _TARGET_DIGEST,
        ),
    )
    asset = build_vocabulary_atlas(
        releases,
        rulespec_core=_core_release(work),
        crosswalks=(_qualified_bundle(),),
    )
    return asset.payload, asset.manifest_bytes()


def _build_hierarchy_distribution(work: Path) -> tuple[bytes, bytes]:
    """A two-release atlas whose source side states its own hierarchy.

    No crosswalk bundle: hierarchy is a layer-1 release fact and must publish
    without any qualification machinery. The second release exists so the
    cross-release refusal below has a real foreign member to point at.
    """

    releases = (
        _ConformanceReleaseSource(
            _view(
                publication=SOURCE_PUBLICATION,
                release=SOURCE_RELEASE,
                concepts=HIERARCHY_CONCEPTS,
                release_digest=_SOURCE_DIGEST,
                edges=HIERARCHY_EDGES,
            ),
            _SOURCE_DIGEST,
        ),
        _ConformanceReleaseSource(
            _view(
                publication=TARGET_PUBLICATION,
                release=TARGET_RELEASE,
                concepts=TARGET_CONCEPTS,
                release_digest=_TARGET_DIGEST,
            ),
            _TARGET_DIGEST,
        ),
    )
    asset = build_vocabulary_atlas(releases, rulespec_core=_core_release(work))
    return asset.payload, asset.manifest_bytes()


def _reseal(payload: bytes, manifest_bytes: bytes) -> bytes:
    """Re-derive every manifest fact that a forged line invalidates."""

    manifest = json.loads(manifest_bytes.decode("utf-8"))
    lines = payload.decode("utf-8").splitlines()
    analysis_id = next(
        graph["id"] for graph in manifest["graphs"] if graph["role"] == "analysis"
    )
    release_id = next(
        graph["id"] for graph in manifest["graphs"] if graph["role"] == "releaseFacts"
    )
    analysis_quads = sum(1 for line in lines if line.endswith(f"<{analysis_id}> ."))
    release_quads = sum(1 for line in lines if line.endswith(f"<{release_id}> ."))
    for graph in manifest["graphs"]:
        graph["quadCount"] = (
            analysis_quads if graph["role"] == "analysis" else release_quads
        )
    manifest["counts"]["analysisFacts"] = analysis_quads
    manifest["counts"]["releaseFacts"] = release_quads
    manifest["output"]["byteLength"] = len(payload)
    manifest["output"]["quadCount"] = len(lines)
    manifest["output"]["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    manifest.pop("canonicalPayloadDigest", None)
    manifest["canonicalPayloadDigest"] = binding.canonical_payload_digest(manifest)
    return binding.canonical_json_bytes(manifest) + b"\n"


def _forge(
    payload: bytes,
    manifest_bytes: bytes,
    edit: Any,
) -> tuple[bytes, bytes]:
    lines = payload.decode("utf-8").splitlines()
    forged = sorted(line for line in edit(lines) if line)
    forged_payload = ("\n".join(forged) + "\n").encode("utf-8")
    return forged_payload, _reseal(forged_payload, manifest_bytes)


_INPUT_CONTEXT_ARTIFACT = "<https://refspec.org/ns/vocabulary-atlas/v1#inputContextArtifact>"
_CONTENT_DIGEST = "<https://refspec.org/ns/vocabulary-atlas/v1#contentDigest>"
_SEARCH_ONLY = (
    "<https://rulespec.org/ns/v1#usageEligibility> <https://rulespec.org/ns/v1#searchOnly>"
)


def _qualified_input_context(lines: Sequence[str]) -> tuple[str, str]:
    """Return the qualified candidate and the input context it must resolve.

    Forging the other candidate's input context proves nothing: the consumer
    checks only mappings it is about to expose.
    """

    qualified = [
        line.split(" ", 1)[0]
        for line in lines
        if _SEARCH_ONLY in line and "MappingCandidate" not in line
    ]
    candidates = sorted(
        {
            subject
            for subject in qualified
            if any(
                line.startswith(f"{subject} {_INPUT_CONTEXT_ARTIFACT}") for line in lines
            )
        }
    )
    if len(candidates) != 1:
        raise VocabularyAtlasError("expected exactly one qualified candidate")
    candidate = candidates[0]
    artifacts = [
        line.split(" ")[2]
        for line in lines
        if line.startswith(f"{candidate} {_INPUT_CONTEXT_ARTIFACT}")
    ]
    if len(artifacts) != 1:
        raise VocabularyAtlasError("expected exactly one input context artifact")
    return candidate, artifacts[0]


def _drop_input_context_link(lines: list[str]) -> list[str]:
    candidate, _ = _qualified_input_context(lines)
    prefix = f"{candidate} {_INPUT_CONTEXT_ARTIFACT}"
    kept = [line for line in lines if not line.startswith(prefix)]
    if len(kept) != len(lines) - 1:
        raise VocabularyAtlasError("expected exactly one input-context link to drop")
    return kept


def _retarget_input_context_digest(lines: list[str]) -> list[str]:
    _, artifact = _qualified_input_context(lines)
    prefix = f"{artifact} {_CONTENT_DIGEST}"
    edited: list[str] = []
    replaced = 0
    for line in lines:
        if line.startswith(prefix):
            head, _, tail = line.partition('"')
            _, _, rest = tail.partition('"')
            edited.append(f'{head}"{_FOREIGN_DIGEST}"{rest}')
            replaced += 1
            continue
        edited.append(line)
    if replaced != 1:
        raise VocabularyAtlasError("expected one content digest to retarget")
    return edited


def _share_provider_model(lines: list[str]) -> list[str]:
    marker = "<https://refspec.org/ns/vocabulary-atlas/v1#providerModelId>"
    edited = [
        line.replace('"provider-model-other"', '"provider-model-first"')
        if marker in line
        else line
        for line in lines
    ]
    if edited == lines:
        raise VocabularyAtlasError("expected one provider model id to share")
    return edited


_ADJUDICATED = "<https://refspec.org/ns/vocabulary-atlas/v1#adjudicatedRelation>"
_VERDICT_RELATION = "<https://refspec.org/ns/vocabulary-atlas/v1#verdictRelation>"
_ASSERTS_PREDICATE = "<https://rulespec.org/ns/v1#assertsPredicate>"
_SKOS = "http://www.w3.org/2004/02/skos/core#"


def _replace_once(lines: list[str], marker: str, stated: str, forged: str) -> list[str]:
    """Rewrite the first statement carrying ``marker`` and ``stated``."""

    edited = list(lines)
    for index, line in enumerate(edited):
        if marker in line and stated in line:
            edited[index] = line.replace(stated, forged)
            return edited
    raise VocabularyAtlasError(f"expected a statement carrying {marker} and {stated}")


def _forge_mapping_relation(lines: list[str]) -> list[str]:
    """Publish a predicate the candidate's adjudicated relation does not license."""

    return _replace_once(
        lines,
        _ASSERTS_PREDICATE,
        f"<{_SKOS}broadMatch>",
        f"<{_SKOS}closeMatch>",
    )


def _forge_adjudicated_relation(lines: list[str]) -> list[str]:
    """State an adjudication the sealed verdicts do not support."""

    return _replace_once(
        lines,
        _ADJUDICATED,
        f"<{_SKOS}narrowMatch>",
        f"<{_SKOS}broadMatch>",
    )


def _drop_adjudication(lines: list[str], relation: str) -> list[str]:
    """Remove the adjudicated relation naming ``relation``, keeping all else."""

    kept = [line for line in lines if not (_ADJUDICATED in line and f"<{_SKOS}{relation}>" in line)]
    if len(kept) != len(lines) - 1:
        raise VocabularyAtlasError(f"expected exactly one {relation} adjudication to drop")
    return kept


def _unstate_adjudication(lines: list[str]) -> list[str]:
    """Publish a mapping whose candidate never says what was adjudicated.

    The verdicts still agree on ``target_is_broader``. Without the adjudication
    the mapping would fall back to the uniform proposal, so a reader that only
    checks a stated adjudication would accept ``broadMatch`` evidence published
    as something else.
    """

    return _drop_adjudication(lines, "broadMatch")


def _forge_verdict_disagreement(lines: list[str]) -> list[str]:
    """Rest a mapping on verdicts that adjudicate nothing.

    One machine's verdict is turned against its partner and the adjudication is
    withdrawn, so the pair claims nothing while still carrying a mapping — the
    shape a producer would reach for to keep a mapping the lattice refuses.
    """

    edited = _replace_once(lines, _VERDICT_RELATION, '"target_is_narrower"', '"related"')
    return _drop_adjudication(edited, "narrowMatch")


def _promote_adjudicated_related(lines: list[str]) -> list[str]:
    """Make the agreed-`related` candidate eligible without giving it a mapping.

    The verdicts still say `related` and the adjudication still reads
    `relatedMatch`, so this isolates one rule: an associative agreement is not a
    licence to use the pair for search.
    """

    subject = next(
        line.split(" ", 1)[0]
        for line in lines
        if _ADJUDICATED in line and f"<{_SKOS}relatedMatch>" in line
    )
    marker = f"{subject} <https://rulespec.org/ns/v1#usageEligibility>"
    edited: list[str] = []
    replaced = 0
    for line in lines:
        if line.startswith(marker):
            edited.append(line.replace("#notEligible>", "#searchOnly>"))
            replaced += 1
            continue
        edited.append(line)
    if replaced != 1:
        raise VocabularyAtlasError("expected one adjudicated-related eligibility to promote")
    return edited


def _substitute(lines: list[str], stated: str, forged: str) -> list[str]:
    edited = [line.replace(stated, forged) if line.startswith(stated) else line for line in lines]
    if sum(1 for line in edited if line.startswith(forged)) != 1:
        raise VocabularyAtlasError(f"expected exactly one statement to retarget: {stated}")
    return edited


def _retarget_edge(child: str, parent: str, replacement: str) -> Any:
    """Move one edge, keeping both stated directions in agreement.

    The forgery rewrites the `skos:broader` statement and its reciprocal
    `skos:narrower` statement together. Rewriting only one would trip the
    inverse-agreement check first and mask the rule under test — and adding or
    dropping an edge would move `hierarchyEdges`, failing on the count before a
    reader reached any rule at all.
    """

    def _edit(lines: list[str]) -> list[str]:
        edited = _substitute(
            lines,
            f"<{child}> <{BROADER}> <{parent}>",
            f"<{child}> <{BROADER}> <{replacement}>",
        )
        return _substitute(
            edited,
            f"<{parent}> <{NARROWER}> <{child}>",
            f"<{replacement}> <{NARROWER}> <{child}>",
        )

    return _edit


def _disagree(parent: str, child: str, replacement: str) -> Any:
    """Retarget one `skos:narrower` and leave its `skos:broader` behind.

    This is the only hierarchy forgery that touches a single direction, which
    is exactly the fact it forges. The broader count is untouched, so the
    distribution reaches the agreement check with a correct `hierarchyEdges`.
    """

    def _edit(lines: list[str]) -> list[str]:
        return _substitute(
            lines,
            f"<{parent}> <{NARROWER}> <{child}>",
            f"<{parent}> <{NARROWER}> <{replacement}>",
        )

    return _edit


_CASES: tuple[dict[str, Any], ...] = (
    {
        "directory": "valid/qualified-search-only",
        "id": "qualified-search-only-mapping-is-accepted",
        "valid": True,
    },
    {
        "base": "hierarchy",
        "directory": "valid/hierarchy",
        "id": "intra-scheme-hierarchy-is-accepted",
        "valid": True,
    },
    {
        "base": "hierarchy",
        "directory": "invalid/cross-scheme-broader",
        "errorContains": "hierarchy must stay inside one release",
        "forge": _retarget_edge(
            "urn:ref:conformance:alpha:marine-policy",
            "urn:ref:conformance:alpha:environmental-policy",
            "urn:ref:conformance:beta:energy-policy",
        ),
        "id": "hierarchy-stays-inside-one-release",
        "valid": False,
    },
    {
        "base": "hierarchy",
        "directory": "invalid/cyclic-broader",
        "errorContains": "hierarchy contains a cycle",
        "forge": _retarget_edge(
            "urn:ref:conformance:alpha:renewable-energy-policy",
            "urn:ref:conformance:alpha:environmental-policy",
            "urn:ref:conformance:alpha:offshore-wind-policy",
        ),
        "id": "hierarchy-has-no-cycle",
        "valid": False,
    },
    {
        "base": "hierarchy",
        "directory": "invalid/disagreeing-narrower",
        "errorContains": "hierarchy directions disagree",
        "forge": _disagree(
            "urn:ref:conformance:alpha:environmental-policy",
            "urn:ref:conformance:alpha:marine-policy",
            "urn:ref:conformance:alpha:offshore-wind-policy",
        ),
        "id": "hierarchy-directions-must-agree",
        "valid": False,
    },
    {
        "base": "hierarchy",
        "directory": "invalid/dangling-broader",
        "errorContains": "hierarchy endpoint is not a release member",
        "forge": _retarget_edge(
            "urn:ref:conformance:alpha:marine-policy",
            "urn:ref:conformance:alpha:environmental-policy",
            ABSENT_CONCEPT,
        ),
        "id": "hierarchy-endpoints-are-release-members",
        "valid": False,
    },
    {
        "directory": "invalid/missing-input-context",
        "errorContains": "mapping input context artifact must have exactly one IRI",
        "forge": _drop_input_context_link,
        "id": "search-only-input-context-must-resolve",
        "valid": False,
    },
    {
        "directory": "invalid/tampered-input-context",
        "errorContains": "input context does not carry the sealed input digest",
        "forge": _retarget_input_context_digest,
        "id": "search-only-input-context-must-match-the-sealed-digest",
        "valid": False,
    },
    {
        "directory": "invalid/same-provider-model",
        "errorContains": "validations are not independent",
        "forge": _share_provider_model,
        "id": "search-only-requires-distinct-provider-models",
        "valid": False,
    },
    {
        "base": "v2",
        "directory": "valid/relation-adjudication",
        "id": "adjudicated-relations-are-accepted",
        "valid": True,
    },
    {
        "base": "v2",
        "directory": "invalid/mapping-relation-not-adjudicated",
        "errorContains": "searchOnly mapping differs from its candidate",
        "forge": _forge_mapping_relation,
        "id": "mapping-relation-matches-the-adjudicated-relation",
        "valid": False,
    },
    {
        "base": "v2",
        "directory": "invalid/adjudication-without-verdicts",
        "errorContains": "does not follow from its verdicts",
        "forge": _forge_adjudicated_relation,
        "id": "adjudicated-relation-follows-from-its-verdicts",
        "valid": False,
    },
    {
        "base": "v2",
        "directory": "invalid/disagreeing-verdict-relations",
        "errorContains": "disagree about the relation",
        "forge": _forge_verdict_disagreement,
        "id": "qualifying-verdicts-must-agree-on-one-relation",
        "valid": False,
    },
    {
        "base": "v2",
        "directory": "invalid/unstated-adjudication",
        "errorContains": "omits the adjudicated relation its verdicts state",
        "forge": _unstate_adjudication,
        "id": "adjudication-is-owed-whenever-the-verdicts-state-one",
        "valid": False,
    },
    {
        "base": "v2",
        "directory": "invalid/promoted-adjudicated-related",
        "errorContains": "adjudicated related candidate must not be eligible",
        "forge": _promote_adjudicated_related,
        "id": "adjudicated-related-must-not-become-substitutable",
        "valid": False,
    },
)


def _generate() -> dict[str, tuple[bytes, bytes]]:
    with tempfile.TemporaryDirectory() as raw:
        bases = {
            "qualified": _build_valid_distribution(Path(raw) / "qualified"),
            "hierarchy": _build_hierarchy_distribution(Path(raw) / "hierarchy"),
            "v2": _build_v2_distribution(Path(raw) / "v2"),
        }
    generated: dict[str, tuple[bytes, bytes]] = {}
    for case in _CASES:
        payload, manifest_bytes = bases[case.get("base", "qualified")]
        if case["valid"]:
            generated[case["directory"]] = (payload, manifest_bytes)
            continue
        generated[case["directory"]] = _forge(payload, manifest_bytes, case["forge"])
    return generated


def _corpus_entry(case: Mapping[str, Any], files: tuple[bytes, bytes]) -> dict[str, Any]:
    payload, manifest_bytes = files
    entry = {
        "directory": case["directory"],
        "id": case["id"],
        "manifestDigest": "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        "outputDigest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "valid": case["valid"],
    }
    if not case["valid"]:
        entry["errorContains"] = case["errorContains"]
    return entry


def _corpus(generated: Mapping[str, tuple[bytes, bytes]]) -> dict[str, Any]:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    # Binding 1.0 is amended in place, so published case digests can change
    # under an unchanged version. A consumer pinning digests from an earlier
    # 1.0 needs to tell the two apart without reading prose.
    corpus["amendments"] = sorted({*corpus.get("amendments", []), *AMENDMENTS})
    owned = {case["directory"]: case for case in _CASES}
    cases = [case for case in corpus["cases"] if case["directory"] not in owned]
    cases.extend(
        _corpus_entry(case, generated[directory])
        for directory, case in owned.items()
    )
    corpus["cases"] = sorted(cases, key=lambda case: case["directory"])
    return corpus


def _render_corpus(corpus: Mapping[str, Any]) -> str:
    return json.dumps(corpus, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="replace the generated fixtures and their corpus entries",
    )
    arguments = parser.parse_args()

    try:
        generated = _generate()
        corpus_text = _render_corpus(_corpus(generated))

        if arguments.write:
            for directory, (payload, manifest_bytes) in generated.items():
                target = FIXTURE_ROOT / directory
                if target.exists():
                    shutil.rmtree(target)
                target.mkdir(parents=True)
                (target / "atlas.nq").write_bytes(payload)
                (target / "atlas-manifest.json").write_bytes(manifest_bytes)
            CORPUS_PATH.write_text(corpus_text, encoding="utf-8")
            print(f"wrote {len(generated)} distributions and the corpus")
            return 0

        for directory, (payload, manifest_bytes) in generated.items():
            target = FIXTURE_ROOT / directory
            if (target / "atlas.nq").read_bytes() != payload:
                raise VocabularyAtlasError(f"{directory}/atlas.nq differs from generation")
            if (target / "atlas-manifest.json").read_bytes() != manifest_bytes:
                raise VocabularyAtlasError(
                    f"{directory}/atlas-manifest.json differs from generation"
                )
        if CORPUS_PATH.read_text(encoding="utf-8") != corpus_text:
            raise VocabularyAtlasError("corpus.json differs from generation")
        print(f"atlas conformance fixtures are current: {len(generated)} distributions")
        return 0
    except (OSError, VocabularyAtlasError) as error:
        print(f"atlas conformance fixture error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
