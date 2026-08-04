"""The shared relation bundle closes evidence and exact endpoint releases."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import pytest

import refspec.atlas as atlas_api
from refspec.atlas.concept_release import (
    ConceptReleaseError,
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
    PinnedSourceConceptRelease,
)
from refspec.atlas.machine_evidence import (
    CROSSWALK_MACHINE_PROOF_ADAPTER,
    PinnedCrosswalkMachineProof,
    build_machine_evidence_from_crosswalk_proof,
)
from refspec.atlas.model import CrosswalkArtifact, CrosswalkBundle, MachineValidation, MappingCandidate
from refspec.atlas.relation_assertion import (
    EmbeddedRelationAssertionBundle,
    RelationAssertionBundle,
    RelationAssertionError,
    RelationMachineProofSource,
)
from refspec.atlas.relation_proof import (
    RelationMachineProofTrustError,
    register_trusted_relation_machine_proof_adapter,
)
from refspec.atlas.relation_sssom import RelationSssomDistribution
from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes, sha256_digest
from refspec.registry.infrastructure.semantic_foundation import (
    ENTITY_RELATED,
    ENTITY_SAME_IDENTITY,
    SUBJECT_CLOSE_MATCH,
    SUBJECT_EXACT_MATCH,
    VALUE_EXACT_CROSSWALK,
    EvidenceAssertion,
    MappingAssertion,
    validate_machine_evidence_proof_pin,
)
from refspec.registry.infrastructure.source_concept_release import (
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7

ASSERTED_AT = "2026-08-04T16:00:00Z"

_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "refspec_test_relation_managed_release_fixture",
    Path(__file__).with_name("test_managed_release_view.py"),
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_FIXTURE_MODULE = importlib.util.module_from_spec(_FIXTURE_SPEC)
sys.modules[_FIXTURE_SPEC.name] = _FIXTURE_MODULE
_FIXTURE_SPEC.loader.exec_module(_FIXTURE_MODULE)
build_managed_bundle = _FIXTURE_MODULE.build_bundle
MANAGED_RELEASE_ID = _FIXTURE_MODULE.RELEASE_ID
MANAGED_MEMBER_ID = _FIXTURE_MODULE.MEMBER_ID


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _managed_ring_assignment(
    tmp_path: Path,
    manifest: Path,
    *,
    release_id: str = MANAGED_RELEASE_ID,
    ring: str = "subject",
    name: str = "managed-ring-assignment",
) -> PinnedManagedReleaseRingAssignment:
    assignment = ManagedReleaseRingAssignment(
        managed_manifest_digest=_file_digest(manifest),
        release_id=release_id,
        semantic_ring=ring,  # type: ignore[arg-type]
        assigned_by="https://refspec.org/actors/portfolio-reviewer-1",
        assigned_at=ASSERTED_AT,
        evidence=("urn:ref:test:atlas-index:managed-release-row",),
    )
    path = assignment.write_to(tmp_path / f"{name}.json")
    return PinnedManagedReleaseRingAssignment.open(
        path,
        expected_file_digest=_file_digest(path),
    )


def test_relation_bundle_is_a_public_atlas_foundation() -> None:
    assert atlas_api.RelationAssertionBundle is RelationAssertionBundle
    assert atlas_api.PinnedManagedConceptRelease is PinnedManagedConceptRelease
    assert atlas_api.PinnedManagedReleaseRingAssignment is PinnedManagedReleaseRingAssignment
    assert atlas_api.PinnedSourceConceptRelease is PinnedSourceConceptRelease
    assert atlas_api.RelationMachineProofSource is RelationMachineProofSource
    assert atlas_api.RelationSssomDistribution is RelationSssomDistribution
    assert (
        atlas_api.registered_relation_machine_proof_adapters()[CROSSWALK_MACHINE_PROOF_ADAPTER]
        is PinnedCrosswalkMachineProof
    )
    assert callable(atlas_api.relation_sssom_text)


def test_relation_proof_registry_rejects_duplicate_authorities() -> None:
    adapter_id = "urn:ref:test:adapter:duplicate-authority:v1"

    @register_trusted_relation_machine_proof_adapter(adapter_id)
    class FirstAdapter:
        def pin(self) -> dict[str, Any]:
            return {}

    class OtherAdapter:
        def pin(self) -> dict[str, Any]:
            return {}

    with pytest.raises(RelationMachineProofTrustError, match="id is already registered"):
        register_trusted_relation_machine_proof_adapter(adapter_id)(OtherAdapter)  # type: ignore[arg-type]

    with pytest.raises(RelationMachineProofTrustError, match="class is already registered"):
        register_trusted_relation_machine_proof_adapter(
            "urn:ref:test:adapter:duplicate-class:v1"
        )(FirstAdapter)  # type: ignore[arg-type]
    with pytest.raises(RelationMachineProofTrustError, match="absolute IRI"):
        register_trusted_relation_machine_proof_adapter("relative-adapter-id")
    with pytest.raises(RelationMachineProofTrustError, match="class with pin"):
        register_trusted_relation_machine_proof_adapter(
            "urn:ref:test:adapter:missing-pin:v1"
        )(type("MissingPinAdapter", (), {}))  # type: ignore[arg-type]

    registered = atlas_api.registered_relation_machine_proof_adapters()
    assert registered[adapter_id] is FirstAdapter
    with pytest.raises(TypeError):
        registered[adapter_id] = OtherAdapter  # type: ignore[index]


def test_managed_ring_assignment_rejects_noncanonical_logical_set_order() -> None:
    assignment = ManagedReleaseRingAssignment(
        managed_manifest_digest="sha256:" + "a" * 64,
        release_id="urn:ref:test:managed-release",
        semantic_ring="subject",
        assigned_by="https://refspec.org/actors/portfolio-reviewer-1",
        assigned_at=ASSERTED_AT,
        evidence=(
            "urn:ref:test:evidence:ring-assignment-b",
            "urn:ref:test:evidence:ring-assignment-a",
        ),
    )
    record = assignment.as_record()
    record["evidence"] = list(reversed(record["evidence"]))

    with pytest.raises(ConceptReleaseError, match="does not reproduce canonically"):
        ManagedReleaseRingAssignment.from_record(record)


def _source_release(
    tmp_path: Path,
    name: str,
    *,
    ring: str = "subject",
) -> tuple[PinnedSourceConceptRelease, str, str]:
    source_id = f"https://publisher.example/source/{name}.json"
    scheme_id = f"https://publisher.example/schemes/{name}"
    local_record_id = "urn:uuid:" + derive_uuid7(
        ASSERTED_AT,
        seed=f"relation-bundle:{name}:{ring}".encode(),
    )
    observation = {
        "id": f"urn:ref:test:source-observation:{name}",
        "sourceArtifact": source_id,
        "sourcePath": f"terms/{name}",
        "sourceOrdinal": 0,
        "labels": [{"value": name.title(), "language": "en", "role": "preferred"}],
        "identifiers": [],
        "uses": ["mappingReference"],
        "conceptIdentityClaimed": False,
        "localRecordId": local_record_id,
    }
    source_payload = (f'{{"terms":["{name}"]}}\n').encode()
    source = build_source_controlled_resource_bundle(
        resource_id=f"relation-bundle-{ring}-{name}",
        title=f"{name.title()} relation source",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("mappingReference",),
        captured_at=ASSERTED_AT,
        observations=(observation,),
        source_artifacts={source_id: source_payload},
        source_scheme={
            "id": scheme_id,
            "code": name,
            "label": f"{name.title()} scheme",
            "sourceArtifact": source_id,
            "sourceFetchId": derive_uuid7(
                ASSERTED_AT,
                seed=f"relation-bundle-fetch:{name}:{ring}".encode(),
            ),
            "sourceObservedAt": ASSERTED_AT,
        },
    )
    release = build_source_concept_release_bundle(
        source,
        semantic_ring=ring,  # type: ignore[arg-type]
        selected_observation_ids=(observation["id"],),
        selection_policy={
            "id": f"urn:ref:test:relation-selection:{ring}:{name}:v1",
            "type": "explicitObservationSet",
        },
        rights_metadata=(
            {
                "type": "RightsMetadata",
                "rightsStatus": "notStated",
                "sourceArtifact": source_id,
                "sourceDigest": "sha256:" + hashlib.sha256(source_payload).hexdigest(),
            },
        ),
    )
    root = release.write_to(tmp_path / f"source-release-{ring}-{name}")
    pinned = PinnedSourceConceptRelease.open(
        root / "bundle-manifest.json",
        expected_manifest_digest=release.manifest_digest,
    )
    return pinned, release.release_id, str(release.concepts[0]["id"])


def _human_evidence(
    name: str = "relation-review",
    *,
    ring: str = "subject",
) -> EvidenceAssertion:
    return EvidenceAssertion(
        semantic_ring=ring,  # type: ignore[arg-type]
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by="https://refspec.org/actors/reviewer-1",
        asserted_at=ASSERTED_AT,
        evidence=(f"urn:ref:test:evidence:{name}:support",),
        review_decision=f"urn:ref:test:evidence:{name}:decision",
    )


def _mapping(
    *,
    source_concept: str,
    target_concept: str,
    source_release: str,
    target_release: str,
    relation: str = SUBJECT_EXACT_MATCH,
    evidence: tuple[str, ...],
    ring: str = "subject",
    context: dict[str, str] | None = None,
) -> MappingAssertion:
    return MappingAssertion(
        semantic_ring=ring,  # type: ignore[arg-type]
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=relation,
        evidence=evidence,
        asserted_at=ASSERTED_AT,
        context=context,
    )


def _subject_facts(
    tmp_path: Path,
) -> tuple[
    PinnedSourceConceptRelease,
    PinnedSourceConceptRelease,
    EvidenceAssertion,
    MappingAssertion,
]:
    source, source_release, source_concept = _source_release(tmp_path, "source")
    target, target_release, target_concept = _source_release(tmp_path, "target")
    evidence = _human_evidence()
    mapping = _mapping(
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        evidence=(evidence.identifier,),
    )
    return source, target, evidence, mapping


def _crosswalk_machine_proofs(
    tmp_path: Path,
    mapping: MappingAssertion,
    *,
    validator_suffixes: tuple[str, ...] = ("a", "b"),
) -> tuple[PinnedCrosswalkMachineProof, PinnedCrosswalkMachineProof]:
    input_context = CrosswalkArtifact.create(
        role="inputContext",
        media_type="application/json",
        content={
            "sourceConcept": mapping.source_concept,
            "targetConcept": mapping.target_concept,
            "protocol": "refspec-atlas-machine-validation-v2",
        },
    )
    evidence = CrosswalkArtifact.create(
        role="evidence",
        media_type="application/json",
        content={"method": "sealed-test-comparison"},
    )
    candidate = MappingCandidate.create(
        source_member=mapping.source_concept,
        source_release=mapping.source_release,
        target_member=mapping.target_concept,
        target_release=mapping.target_release,
        proposed_relation=SUBJECT_CLOSE_MATCH,
        generator_kind="aiAgent",
        generator_actor="urn:ref:test:generator",
        generator_provider="urn:ref:test:generator-provider",
        model_id="test-generator",
        model_version="1",
        prompt_template="urn:ref:test:prompt:v2",
        input_context_digest=input_context.content_digest,
        temperature="0",
        evidence=(evidence.reference(),),
        generated_at=ASSERTED_AT,
        seed=7,
    )
    request = CrosswalkArtifact.create(
        role="validationRequest",
        media_type="application/json",
        content={
            "candidate": candidate.reference(),
            "inputDigest": input_context.content_digest,
            "protocol": "refspec-atlas-machine-validation-v2",
        },
    )
    responses: list[CrosswalkArtifact] = []
    validations: list[MachineValidation] = []
    for suffix in validator_suffixes:
        response = CrosswalkArtifact.create(
            role="validationResponse",
            media_type="application/json",
            content={
                "candidate": candidate.reference(),
                "inputDigest": input_context.content_digest,
                "requestArtifact": request.reference(),
                "validatorActor": f"urn:ref:test:validator:{suffix}",
                "provider": f"urn:ref:test:provider:{suffix}",
                "providerModelId": f"provider-model-{suffix}",
                "deterministicChecksPassed": True,
                "outcome": "supports",
                "verdictRelation": "same",
            },
        )
        responses.append(response)
        validations.append(
            MachineValidation.create(
                candidate=candidate.reference(),
                validator_kind="aiAgent",
                validator_actor=f"urn:ref:test:validator:{suffix}",
                independence_group=f"urn:ref:test:independence-group:{suffix}",
                provider=f"urn:ref:test:provider:{suffix}",
                provider_model_id=f"provider-model-{suffix}",
                sealed_input_digest=input_context.content_digest,
                request_artifact=request.reference(),
                response_artifact=response.reference(),
                deterministic_checks_passed=True,
                outcome="supports",
                completed_at=ASSERTED_AT,
                verdict_relation="same",
            )
        )
    bundle = CrosswalkBundle.create(
        artifacts=(input_context, evidence, request, *responses),
        mapping_candidates=(candidate,),
        machine_validations=tuple(validations),
    )
    path = bundle.write(tmp_path / "crosswalk-machine-proof.json")
    qualified = PinnedCrosswalkMachineProof.qualified(
        path,
        expected_file_digest=_file_digest(path),
        expected_bundle_digest=bundle.digest,
        candidate_id=candidate.identifier,
    )
    reviewed = PinnedCrosswalkMachineProof.reviewed(
        path,
        expected_file_digest=_file_digest(path),
        expected_bundle_digest=bundle.digest,
        candidate_id=candidate.identifier,
        validation_id=validations[0].identifier,
    )
    return qualified, reviewed


def test_qualified_proof_retains_every_validation_that_determined_the_relation(
    tmp_path: Path,
) -> None:
    _, _, _, mapping = _subject_facts(tmp_path)
    qualified, _ = _crosswalk_machine_proofs(
        tmp_path,
        mapping,
        validator_suffixes=("a", "b", "c"),
    )
    pin = qualified.pin()
    evidence = build_machine_evidence_from_crosswalk_proof(
        qualified,
        asserted_by="https://refspec.org/software/qualification-gate-v2",
        asserted_at=ASSERTED_AT,
    )

    assert pin["semanticRing"] == "subject"
    assert pin["proofKind"] == "crosswalkV2IndependentValidations"
    assert pin["qualificationPolicy"].endswith("two-independent-machines-relation-agreement-v2")
    assert len(pin["validations"]) == 3
    assert evidence.validation_receipts == tuple(row["id"] for row in pin["validations"])
    assert pin["type"] == "MachineEvidenceProof"
    assert pin["proofSource"]["type"] == "CrosswalkBundle"
    assert pin["proofDetails"]["sealedQuestion"]["request"]["id"].startswith(
        "urn:ref:vocabulary-atlas-artifact:"
    )


def test_source_relation_bundle_is_content_derived_deterministic_and_reopenable(
    tmp_path: Path,
) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)

    first = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(target, source),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    second = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )

    assert first.identifier.startswith("urn:ref:relation-assertion-bundle:subject:")
    assert first.content_digest.startswith("sha256:")
    assert first.as_record() == second.as_record()
    assert first.artifact_bytes() == second.artifact_bytes()
    assert [row["releaseId"] for row in first.release_pins] == sorted(row["releaseId"] for row in first.release_pins)
    assert mapping.source_concept in source.member_ids()
    assert mapping.target_concept in target.member_ids()

    root = first.write_to(tmp_path / "relation-bundle")
    reopened = RelationAssertionBundle.open(
        root / "bundle-manifest.json",
        expected_manifest_digest=first.manifest_digest,
        release_sources=(source, target),
    )

    assert reopened.as_record() == first.as_record()
    assert reopened.artifact_bytes() == first.artifact_bytes()
    reopened.verify()


def test_embedded_relation_record_revalidates_without_producer_directories(
    tmp_path: Path,
) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    memberships = {
        source.release_id: source.member_ids(),
        target.release_id: target.member_ids(),
    }

    embedded = EmbeddedRelationAssertionBundle.from_record(
        bundle.as_record(),
        release_memberships=memberships,
    )

    assert embedded.identifier == bundle.identifier
    assert embedded.content_digest == bundle.content_digest
    assert embedded.as_record() == bundle.as_record()
    assert embedded.mapping_assertions == (mapping,)
    assert embedded.evidence_assertions == (evidence,)


def test_embedded_relation_record_requires_exact_membership_and_order(
    tmp_path: Path,
) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    memberships = {
        source.release_id: frozenset(),
        target.release_id: target.member_ids(),
    }

    with pytest.raises(RelationAssertionError, match="sourceConcept is outside"):
        EmbeddedRelationAssertionBundle.from_record(
            bundle.as_record(),
            release_memberships=memberships,
        )

    reordered = bundle.as_record()
    reordered["releasePins"] = list(reversed(reordered["releasePins"]))
    with pytest.raises(RelationAssertionError, match="canonically ordered"):
        EmbeddedRelationAssertionBundle.from_record(reordered)


def test_source_to_managed_relation_uses_the_exact_complete_release(
    tmp_path: Path,
) -> None:
    manifest = build_managed_bundle(tmp_path / "managed")
    ring_assignment = _managed_ring_assignment(tmp_path, manifest)
    managed = PinnedManagedConceptRelease.open(
        manifest,
        expected_manifest_digest=_file_digest(manifest),
        release_id=MANAGED_RELEASE_ID,
        ring_assignment=ring_assignment,
    )
    source, source_release, source_concept = _source_release(tmp_path, "source-target")
    evidence = _human_evidence("managed-source-review")
    mapping = _mapping(
        source_concept=MANAGED_MEMBER_ID,
        target_concept=source_concept,
        source_release=MANAGED_RELEASE_ID,
        target_release=source_release,
        evidence=(evidence.identifier,),
    )

    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(managed, source),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )

    managed_pin = next(row for row in bundle.release_pins if row["releaseId"] == MANAGED_RELEASE_ID)
    assert managed_pin["releaseKind"] == "managedReferenceRelease"
    assert managed_pin["rulespecGraph"]["digest"].startswith("sha256:")
    assert managed_pin["declaredReleaseDigest"].startswith("sha256:")
    assert managed_pin["ringAssignment"] == ring_assignment.pin()
    assert MANAGED_MEMBER_ID in managed.member_ids()


@pytest.mark.parametrize("endpoint", ["source", "target"])
def test_mapping_endpoint_must_belong_to_its_named_exact_release(
    tmp_path: Path,
    endpoint: str,
) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    changed = (
        replace(mapping, source_concept="urn:ref:test:concept:not-a-source-member")
        if endpoint == "source"
        else replace(mapping, target_concept="urn:ref:test:concept:not-a-target-member")
    )

    with pytest.raises(RelationAssertionError, match=f"{endpoint}Concept is not a member"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target),
            evidence_assertions=(evidence,),
            mapping_assertions=(changed,),
        )


def test_mapping_cannot_name_an_unpinned_release_or_cross_rings(tmp_path: Path) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    outside = replace(mapping, target_release="urn:ref:test:release:not-pinned")

    with pytest.raises(RelationAssertionError, match="outside the exact release pins"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target),
            evidence_assertions=(evidence,),
            mapping_assertions=(outside,),
        )

    entity, _, _ = _source_release(tmp_path, "entity", ring="entity")
    with pytest.raises(RelationAssertionError, match="semanticRing differs"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, entity),
            evidence_assertions=(evidence,),
            mapping_assertions=(mapping,),
        )


def test_relation_bundle_rejects_unused_release_sources(tmp_path: Path) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    unused, _, _ = _source_release(tmp_path, "unused-release")

    with pytest.raises(RelationAssertionError, match="exact mapping endpoint release closure"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target, unused),
            evidence_assertions=(evidence,),
            mapping_assertions=(mapping,),
        )


def test_distinct_assertions_for_the_same_endpoints_are_preserved(tmp_path: Path) -> None:
    source, target, evidence, exact = _subject_facts(tmp_path)
    close = replace(
        exact,
        relation=SUBJECT_CLOSE_MATCH,
    )

    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(close, exact),
    )

    assert {(row.identifier, row.relation) for row in bundle.mapping_assertions} == {
        (exact.identifier, SUBJECT_EXACT_MATCH),
        (close.identifier, SUBJECT_CLOSE_MATCH),
    }

    with pytest.raises(RelationAssertionError, match="repeats an id"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target),
            evidence_assertions=(evidence,),
            mapping_assertions=(exact, exact),
        )


def test_evidence_set_is_the_exact_transitive_closure(tmp_path: Path) -> None:
    source, target, _, mapping = _subject_facts(tmp_path)
    _, reviewed_proof = _crosswalk_machine_proofs(tmp_path, mapping)
    reviewed = build_machine_evidence_from_crosswalk_proof(
        reviewed_proof,
        asserted_by="https://refspec.org/software/qualification-runner-v2",
        asserted_at=ASSERTED_AT,
    )
    adopted = EvidenceAssertion(
        semantic_ring="subject",
        evidence_class="operatorAdopted",
        basis="operatorDirection",
        asserted_by="https://refspec.org/actors/operator-1",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:evidence:operator:decision",),
        adopted_evidence=reviewed.identifier,
    )
    adopted_mapping = replace(mapping, evidence=(adopted.identifier,))
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        machine_proof_sources=(reviewed_proof,),
        evidence_assertions=(adopted, reviewed),
        mapping_assertions=(adopted_mapping,),
    )

    assert {row.identifier for row in bundle.evidence_assertions} == {adopted.identifier, reviewed.identifier}
    assert bundle.as_record()["machineProofPins"] == [reviewed_proof.pin()]

    unused = _human_evidence("unused")
    with pytest.raises(RelationAssertionError, match="unreferenced evidence"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target),
            machine_proof_sources=(reviewed_proof,),
            evidence_assertions=(adopted, reviewed, unused),
            mapping_assertions=(adopted_mapping,),
        )


def test_mapping_assertion_identity_remains_distinct_from_machine_candidate(
    tmp_path: Path,
) -> None:
    source, target, _, mapping = _subject_facts(tmp_path)
    qualified_proof, _ = _crosswalk_machine_proofs(tmp_path, mapping)
    machine = build_machine_evidence_from_crosswalk_proof(
        qualified_proof,
        asserted_by="https://refspec.org/software/qualification-gate-v2",
        asserted_at=ASSERTED_AT,
    )
    qualified_mapping = replace(mapping, evidence=(machine.identifier,))

    assert len({machine.candidate, machine.identifier, qualified_mapping.identifier}) == 3
    with pytest.raises(RelationAssertionError, match="proof pins do not close"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target),
            evidence_assertions=(machine,),
            mapping_assertions=(qualified_mapping,),
        )

    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        machine_proof_sources=(qualified_proof,),
        evidence_assertions=(machine,),
        mapping_assertions=(qualified_mapping,),
    )
    assert bundle.as_record()["machineProofPins"] == [qualified_proof.pin()]

    root = bundle.write_to(tmp_path / "qualified-relation-bundle")
    reopened = RelationAssertionBundle.open(
        root / "bundle-manifest.json",
        expected_manifest_digest=bundle.manifest_digest,
        release_sources=(target, source),
        machine_proof_sources=(qualified_proof,),
    )
    assert reopened.as_record() == bundle.as_record()
    assert reopened.artifact_bytes() == bundle.artifact_bytes()
    reopened.verify()


def test_relation_bundle_reopens_machine_proof_and_rejects_later_byte_changes(
    tmp_path: Path,
) -> None:
    source, target, _, mapping = _subject_facts(tmp_path)
    qualified_proof, _ = _crosswalk_machine_proofs(tmp_path, mapping)
    machine = build_machine_evidence_from_crosswalk_proof(
        qualified_proof,
        asserted_by="https://refspec.org/software/qualification-gate-v2",
        asserted_at=ASSERTED_AT,
    )
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        machine_proof_sources=(qualified_proof,),
        evidence_assertions=(machine,),
        mapping_assertions=(replace(mapping, evidence=(machine.identifier,)),),
    )
    bundle.write_to(tmp_path / "proof-mutation-relation-bundle")

    qualified_proof.path.write_bytes(qualified_proof.path.read_bytes() + b" ")

    with pytest.raises(RelationAssertionError, match="crosswalk file digest differs"):
        bundle.verify()


def test_crosswalk_machine_proof_adapter_is_subject_only(tmp_path: Path) -> None:
    _, _, _, subject_mapping = _subject_facts(tmp_path)
    qualified_proof, _ = _crosswalk_machine_proofs(tmp_path, subject_mapping)
    source, source_release, source_concept = _source_release(tmp_path, "entity-proof-source", ring="entity")
    target, target_release, target_concept = _source_release(tmp_path, "entity-proof-target", ring="entity")
    evidence = _human_evidence("entity-proof-review", ring="entity")
    mapping = _mapping(
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=ENTITY_SAME_IDENTITY,
        evidence=(evidence.identifier,),
        ring="entity",
    )

    with pytest.raises(RelationAssertionError, match="semanticRing differs"):
        RelationAssertionBundle.create(
            semantic_ring="entity",
            release_sources=(source, target),
            machine_proof_sources=(qualified_proof,),
            evidence_assertions=(evidence,),
            mapping_assertions=(mapping,),
        )


def test_machine_proof_adapter_must_expose_reopenable_source_bytes(tmp_path: Path) -> None:
    source, target, _, mapping = _subject_facts(tmp_path)
    qualified_proof, _ = _crosswalk_machine_proofs(tmp_path, mapping)
    machine = build_machine_evidence_from_crosswalk_proof(
        qualified_proof,
        asserted_by="https://refspec.org/software/qualification-gate-v2",
        asserted_at=ASSERTED_AT,
    )

    class InMemoryProof:
        def pin(self) -> dict[str, Any]:
            return qualified_proof.pin()

    with pytest.raises(RelationAssertionError, match="path-backed proof adapter interface"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target),
            machine_proof_sources=(InMemoryProof(),),  # type: ignore[arg-type]
            evidence_assertions=(machine,),
            mapping_assertions=(replace(mapping, evidence=(machine.identifier,)),),
        )


def test_unregistered_adapter_cannot_turn_decoy_bytes_into_proof(tmp_path: Path) -> None:
    source, target, _, mapping = _subject_facts(tmp_path)
    qualified_proof, _ = _crosswalk_machine_proofs(tmp_path, mapping)
    machine = build_machine_evidence_from_crosswalk_proof(
        qualified_proof,
        asserted_by="https://refspec.org/software/qualification-gate-v2",
        asserted_at=ASSERTED_AT,
    )
    decoy_path = tmp_path / "decoy-proof-source.bin"
    decoy_path.write_bytes(b"bytes with no relation-proof semantics\n")

    class UnregisteredDecoyProof:
        path = decoy_path

        def pin(self) -> dict[str, Any]:
            trusted_pin = qualified_proof.pin()
            basis = {
                key: value
                for key, value in trusted_pin.items()
                if key not in {"id", "contentDigest"}
            }
            decoy_digest = _file_digest(self.path)
            basis["proofAdapter"] = "urn:ref:test:adapter:unregistered-decoy:v1"
            basis["proofSource"] = {
                "type": "DecoyBytes",
                "id": "urn:ref:test:decoy-proof-source",
                "contentDigest": decoy_digest,
                "fileDigest": decoy_digest,
            }
            basis["proofDetails"] = {"method": "invented-facts-unrelated-to-decoy-bytes"}
            content_digest = sha256_digest(canonical_json_bytes(basis))
            return {
                **basis,
                "id": f"urn:ref:machine-evidence-proof:subject:{content_digest.removeprefix('sha256:')}",
                "contentDigest": content_digest,
            }

    decoy = UnregisteredDecoyProof()
    assert validate_machine_evidence_proof_pin(decoy.pin(), semantic_ring="subject") == decoy.pin()

    with pytest.raises(RelationAssertionError, match="exact class is not registered"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target),
            machine_proof_sources=(decoy,),
            evidence_assertions=(machine,),
            mapping_assertions=(replace(mapping, evidence=(machine.identifier,)),),
        )


def test_trusted_adapter_registration_does_not_extend_to_subclasses(tmp_path: Path) -> None:
    source, target, _, mapping = _subject_facts(tmp_path)
    qualified_proof, _ = _crosswalk_machine_proofs(tmp_path, mapping)
    machine = build_machine_evidence_from_crosswalk_proof(
        qualified_proof,
        asserted_by="https://refspec.org/software/qualification-gate-v2",
        asserted_at=ASSERTED_AT,
    )

    class UnregisteredCrosswalkSubclass(PinnedCrosswalkMachineProof):
        pass

    subclass_proof = UnregisteredCrosswalkSubclass(
        path=qualified_proof.path,
        file_digest=qualified_proof.file_digest,
        bundle_digest=qualified_proof.bundle_digest,
        proof_kind=qualified_proof.proof_kind,
        candidate_id=qualified_proof.candidate_id,
        validation_ids=qualified_proof.validation_ids,
    )

    with pytest.raises(RelationAssertionError, match="exact class is not registered"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target),
            machine_proof_sources=(subclass_proof,),
            evidence_assertions=(machine,),
            mapping_assertions=(replace(mapping, evidence=(machine.identifier,)),),
        )


def test_registered_adapter_pin_must_name_its_registered_adapter(tmp_path: Path) -> None:
    source, target, _, mapping = _subject_facts(tmp_path)
    qualified_proof, _ = _crosswalk_machine_proofs(tmp_path, mapping)
    machine = build_machine_evidence_from_crosswalk_proof(
        qualified_proof,
        asserted_by="https://refspec.org/software/qualification-gate-v2",
        asserted_at=ASSERTED_AT,
    )

    @register_trusted_relation_machine_proof_adapter(
        "urn:ref:test:adapter:intentionally-mismatched-crosswalk:v1"
    )
    class MismatchedCrosswalkAdapter(PinnedCrosswalkMachineProof):
        pass

    mismatched = MismatchedCrosswalkAdapter(
        path=qualified_proof.path,
        file_digest=qualified_proof.file_digest,
        bundle_digest=qualified_proof.bundle_digest,
        proof_kind=qualified_proof.proof_kind,
        candidate_id=qualified_proof.candidate_id,
        validation_ids=qualified_proof.validation_ids,
    )

    with pytest.raises(RelationAssertionError, match="proofAdapter differs"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target),
            machine_proof_sources=(mismatched,),
            evidence_assertions=(machine,),
            mapping_assertions=(replace(mapping, evidence=(machine.identifier,)),),
        )


def test_relation_foundation_accepts_a_ring_scoped_machine_proof_adapter(tmp_path: Path) -> None:
    source, source_release, source_concept = _source_release(tmp_path, "entity-adapter-source", ring="entity")
    target, target_release, target_concept = _source_release(tmp_path, "entity-adapter-target", ring="entity")
    proof_path = tmp_path / "entity-proof-source.bin"
    proof_path.write_bytes(b"verified entity relation proof\n")
    expected_file_digest = _file_digest(proof_path)
    adapter_id = "urn:ref:test:adapter:entity-identifier-agreement:v1"

    @register_trusted_relation_machine_proof_adapter(adapter_id)
    class PinnedEntityProof:
        def __init__(self, path: Path) -> None:
            self.path = path

        def pin(self) -> dict[str, Any]:
            if _file_digest(proof_path) != expected_file_digest:
                raise ValueError("entity proof source digest differs")
            basis = {
                "type": "MachineEvidenceProof",
                "schemaVersion": "1.0",
                "proofAdapter": adapter_id,
                "semanticRing": "entity",
                "evidenceClass": "machineQualified",
                "proofKind": "testEntityIdentifierAgreementV1",
                "proofSource": {
                    "type": "TestEntityProof",
                    "id": "urn:ref:test:entity-proof-source",
                    "contentDigest": expected_file_digest,
                    "fileDigest": expected_file_digest,
                },
                "candidate": {
                    "id": "urn:ref:test:entity-proof-candidate",
                    "contentDigest": "sha256:" + "c" * 64,
                },
                "validations": [
                    {
                        "id": "urn:ref:test:entity-proof-validation:a",
                        "contentDigest": "sha256:" + "a" * 64,
                    },
                    {
                        "id": "urn:ref:test:entity-proof-validation:b",
                        "contentDigest": "sha256:" + "b" * 64,
                    },
                ],
                "proofDetails": {"method": "identifier-and-context-comparison"},
                "sourceConcept": source_concept,
                "targetConcept": target_concept,
                "sourceRelease": source_release,
                "targetRelease": target_release,
                "relation": ENTITY_RELATED,
                "qualificationPolicy": "urn:ref:test:policy:entity-proof-v1",
            }
            content_digest = sha256_digest(canonical_json_bytes(basis))
            return {
                **basis,
                "id": f"urn:ref:machine-evidence-proof:entity:{content_digest.removeprefix('sha256:')}",
                "contentDigest": content_digest,
            }

    adapter = PinnedEntityProof(proof_path)
    proof_pin = adapter.pin()
    machine = EvidenceAssertion(
        semantic_ring="entity",
        evidence_class="machineQualified",
        basis="statisticalInference",
        asserted_by="urn:ref:test:entity-proof-adapter",
        asserted_at=ASSERTED_AT,
        evidence=(proof_pin["id"],),
        candidate=proof_pin["candidate"]["id"],
        machine_proof=proof_pin["id"],
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=ENTITY_RELATED,
        validation_receipts=tuple(row["id"] for row in proof_pin["validations"]),
    )
    mapping = _mapping(
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=ENTITY_RELATED,
        evidence=(machine.identifier,),
        ring="entity",
    )

    bundle = RelationAssertionBundle.create(
        semantic_ring="entity",
        release_sources=(source, target),
        machine_proof_sources=(adapter,),
        evidence_assertions=(machine,),
        mapping_assertions=(mapping,),
    )

    assert bundle.as_record()["machineProofPins"] == [proof_pin]
    bundle.verify()


def test_machine_proof_binds_value_ring_effective_context(tmp_path: Path) -> None:
    source, source_release, source_concept = _source_release(tmp_path, "value-adapter-source", ring="value")
    target, target_release, target_concept = _source_release(tmp_path, "value-adapter-target", ring="value")
    proof_path = tmp_path / "value-proof-source.bin"
    proof_path.write_bytes(b"verified value crosswalk proof\n")
    expected_file_digest = _file_digest(proof_path)
    adapter_id = "urn:ref:test:adapter:value-edition-crosswalk:v1"
    proof_context = {
        "sourceEdition": "2017",
        "targetEdition": "2022",
        "effectiveFrom": "2024-01-01",
    }

    @register_trusted_relation_machine_proof_adapter(adapter_id)
    class PinnedValueProof:
        def __init__(self, path: Path) -> None:
            self.path = path

        def pin(self) -> dict[str, Any]:
            if _file_digest(self.path) != expected_file_digest:
                raise ValueError("value proof source digest differs")
            basis = {
                "type": "MachineEvidenceProof",
                "schemaVersion": "1.0",
                "proofAdapter": adapter_id,
                "semanticRing": "value",
                "evidenceClass": "machineQualified",
                "proofKind": "testValueEditionCrosswalkV1",
                "proofSource": {
                    "type": "TestValueProof",
                    "id": "urn:ref:test:value-proof-source",
                    "contentDigest": expected_file_digest,
                    "fileDigest": expected_file_digest,
                },
                "candidate": {
                    "id": "urn:ref:test:value-proof-candidate",
                    "contentDigest": "sha256:" + "c" * 64,
                },
                "validations": [
                    {
                        "id": "urn:ref:test:value-proof-validation:a",
                        "contentDigest": "sha256:" + "a" * 64,
                    },
                    {
                        "id": "urn:ref:test:value-proof-validation:b",
                        "contentDigest": "sha256:" + "b" * 64,
                    },
                ],
                "proofDetails": {"method": "edition-crosswalk-comparison"},
                "sourceConcept": source_concept,
                "targetConcept": target_concept,
                "sourceRelease": source_release,
                "targetRelease": target_release,
                "relation": VALUE_EXACT_CROSSWALK,
                "context": proof_context,
                "qualificationPolicy": "urn:ref:test:policy:value-proof-v1",
            }
            content_digest = sha256_digest(canonical_json_bytes(basis))
            return {
                **basis,
                "id": f"urn:ref:machine-evidence-proof:value:{content_digest.removeprefix('sha256:')}",
                "contentDigest": content_digest,
            }

    adapter = PinnedValueProof(proof_path)
    proof_pin = adapter.pin()
    machine = EvidenceAssertion(
        semantic_ring="value",
        evidence_class="machineQualified",
        basis="statisticalInference",
        asserted_by="urn:ref:test:value-proof-adapter",
        asserted_at=ASSERTED_AT,
        evidence=(proof_pin["id"],),
        candidate=proof_pin["candidate"]["id"],
        machine_proof=proof_pin["id"],
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=VALUE_EXACT_CROSSWALK,
        validation_receipts=tuple(row["id"] for row in proof_pin["validations"]),
    )
    mapping = _mapping(
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=VALUE_EXACT_CROSSWALK,
        evidence=(machine.identifier,),
        ring="value",
        context=proof_context,
    )

    valid = RelationAssertionBundle.create(
        semantic_ring="value",
        release_sources=(source, target),
        machine_proof_sources=(adapter,),
        evidence_assertions=(machine,),
        mapping_assertions=(mapping,),
    )
    valid.verify()

    with pytest.raises(RelationAssertionError, match="context differs from its verified machine proof"):
        RelationAssertionBundle.create(
            semantic_ring="value",
            release_sources=(source, target),
            machine_proof_sources=(adapter,),
            evidence_assertions=(machine,),
            mapping_assertions=(
                replace(
                    mapping,
                    context={
                        "sourceEdition": "2017",
                        "targetEdition": "2022",
                        "effectiveFrom": "2035-01-01",
                    },
                ),
            ),
        )


def test_machine_evidence_cannot_relabel_the_verified_relation(tmp_path: Path) -> None:
    source, target, _, mapping = _subject_facts(tmp_path)
    qualified_proof, _ = _crosswalk_machine_proofs(tmp_path, mapping)
    machine = build_machine_evidence_from_crosswalk_proof(
        qualified_proof,
        asserted_by="https://refspec.org/software/qualification-gate-v2",
        asserted_at=ASSERTED_AT,
    )
    relabeled = replace(machine, relation=SUBJECT_CLOSE_MATCH)
    relabeled_mapping = replace(
        mapping,
        relation=SUBJECT_CLOSE_MATCH,
        evidence=(relabeled.identifier,),
    )

    with pytest.raises(RelationAssertionError, match="differs from its verified proof facts"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target),
            machine_proof_sources=(qualified_proof,),
            evidence_assertions=(relabeled,),
            mapping_assertions=(relabeled_mapping,),
        )


def test_entity_identity_never_forms_from_name_equality(tmp_path: Path) -> None:
    source, source_release, source_concept = _source_release(tmp_path, "entity-source", ring="entity")
    target, target_release, target_concept = _source_release(tmp_path, "entity-target", ring="entity")
    candidate = EvidenceAssertion(
        semantic_ring="entity",
        evidence_class="ruleGenerated",
        basis="nameEquality",
        asserted_by="https://refspec.org/software/name-rule-v1",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:evidence:entity-name-equality:input",),
        generator="https://refspec.org/software/name-rule-v1",
        generator_inputs=("urn:ref:test:evidence:entity-name-equality:input",),
    )
    mapping = _mapping(
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=ENTITY_SAME_IDENTITY,
        evidence=(candidate.identifier,),
        ring="entity",
    )

    with pytest.raises(RelationAssertionError, match="cannot be supported by name equality"):
        RelationAssertionBundle.create(
            semantic_ring="entity",
            release_sources=(source, target),
            evidence_assertions=(candidate,),
            mapping_assertions=(mapping,),
        )


def test_bundle_and_nested_records_are_immutable(tmp_path: Path) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )

    with pytest.raises(TypeError):
        bundle.release_pins[0]["releaseId"] = "urn:ref:test:changed"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        bundle.semantic_ring = "entity"  # type: ignore[misc]


def test_open_rejects_tampered_assertion_bytes(tmp_path: Path) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    root = bundle.write_to(tmp_path / "tampered-relation-bundle")
    assertions = root / "relation-assertions.json"
    assertions.write_bytes(assertions.read_bytes() + b" ")

    with pytest.raises(RelationAssertionError, match="artifact bytes differ"):
        RelationAssertionBundle.open(
            root / "bundle-manifest.json",
            expected_manifest_digest=bundle.manifest_digest,
            release_sources=(source, target),
        )


def test_open_rejects_noncanonical_manifest_bytes(tmp_path: Path) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    root = bundle.write_to(tmp_path / "noncanonical-manifest-relation-bundle")
    manifest_path = root / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest_path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode())

    with pytest.raises(RelationAssertionError, match="manifest bytes are not canonical"):
        RelationAssertionBundle.open(
            manifest_path,
            expected_manifest_digest=_file_digest(manifest_path),
            release_sources=(source, target),
        )


def test_open_rechecks_the_file_set_after_constructing_the_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    root = bundle.write_to(tmp_path / "file-set-mutation-during-relation-open")
    original_post_init = RelationAssertionBundle.__post_init__
    construction_count = 0

    def add_file_during_final_construction(value: RelationAssertionBundle) -> None:
        nonlocal construction_count
        construction_count += 1
        original_post_init(value)
        if construction_count == 2:
            (root / "late-added.txt").write_text("unexpected", encoding="utf-8")

    monkeypatch.setattr(RelationAssertionBundle, "__post_init__", add_file_during_final_construction)

    with pytest.raises(RelationAssertionError, match="changed while opening"):
        RelationAssertionBundle.open(
            root / "bundle-manifest.json",
            expected_manifest_digest=bundle.manifest_digest,
            release_sources=(source, target),
        )


def test_release_source_must_be_path_backed_and_verified(tmp_path: Path) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)

    with pytest.raises(RelationAssertionError, match="path-backed verified"):
        RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, {"releaseId": target.release_id}),  # type: ignore[arg-type]
            evidence_assertions=(evidence,),
            mapping_assertions=(mapping,),
        )


def test_managed_pin_rejects_a_nonexistent_complete_release(tmp_path: Path) -> None:
    manifest = build_managed_bundle(tmp_path / "managed-missing-release")
    missing_release = "urn:ref:test:release:not-present"
    ring_assignment = _managed_ring_assignment(
        tmp_path,
        manifest,
        release_id=missing_release,
    )

    with pytest.raises(ConceptReleaseError, match="not an exact complete-membership release"):
        PinnedManagedConceptRelease.open(
            manifest,
            expected_manifest_digest=_file_digest(manifest),
            release_id=missing_release,
            ring_assignment=ring_assignment,
        )


def test_managed_release_ring_comes_only_from_a_pinned_assignment(tmp_path: Path) -> None:
    manifest = build_managed_bundle(tmp_path / "managed-ring-proof")
    subject_assignment = _managed_ring_assignment(tmp_path, manifest)
    pinned = PinnedManagedConceptRelease.open(
        manifest,
        expected_manifest_digest=_file_digest(manifest),
        release_id=MANAGED_RELEASE_ID,
        ring_assignment=subject_assignment,
    )

    assert pinned.semantic_ring == "subject"
    assert pinned.pin()["ringAssignment"] == subject_assignment.pin()

    wrong_release_assignment = _managed_ring_assignment(
        tmp_path,
        manifest,
        release_id="urn:ref:test:release:another",
        name="wrong-release-ring-assignment",
    )
    with pytest.raises(ConceptReleaseError, match="names another exact release"):
        PinnedManagedConceptRelease.open(
            manifest,
            expected_manifest_digest=_file_digest(manifest),
            release_id=MANAGED_RELEASE_ID,
            ring_assignment=wrong_release_assignment,
        )

    with pytest.raises(TypeError, match="semantic_ring"):
        PinnedManagedConceptRelease.open(
            manifest,
            expected_manifest_digest=_file_digest(manifest),
            release_id=MANAGED_RELEASE_ID,
            ring_assignment=subject_assignment,
            semantic_ring="entity",  # type: ignore[call-arg]
        )


def test_record_shape_does_not_expose_local_paths(tmp_path: Path) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )

    serialized = str(bundle.as_record())
    assert str(tmp_path) not in serialized
    assert "manifest_path" not in serialized
    assert "LocalConcept" not in serialized


def test_direct_construction_cannot_replace_verified_release_pins(tmp_path: Path) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    legitimate = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    changed_pin: dict[str, Any] = dict(legitimate.release_pins[0])
    changed_pin["releaseDigest"] = "sha256:" + "f" * 64

    with pytest.raises(RelationAssertionError, match="release pins differ"):
        RelationAssertionBundle(
            semantic_ring="subject",
            release_pins=(changed_pin, legitimate.release_pins[1]),
            machine_proof_pins=(),
            evidence_assertions=(evidence,),
            mapping_assertions=(mapping,),
            _release_sources=(source, target),
            _machine_proof_sources=(),
        )


def test_relation_record_identities_are_content_derived_and_disjoint(tmp_path: Path) -> None:
    source, target, evidence, mapping = _subject_facts(tmp_path)
    changed_evidence = _human_evidence("changed-review")
    changed_mapping = replace(mapping, evidence=(changed_evidence.identifier,))

    assert evidence.identifier != changed_evidence.identifier
    assert mapping.identifier != changed_mapping.identifier
    assert evidence.identifier.startswith("urn:ref:evidence-assertion:")
    assert mapping.identifier.startswith("urn:ref:mapping-assertion:")

    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(changed_evidence,),
        mapping_assertions=(changed_mapping,),
    )
    assert bundle.mapping_assertions == (changed_mapping,)


def test_set_valued_evidence_order_does_not_change_bundle_identity(tmp_path: Path) -> None:
    source, target, _, mapping = _subject_facts(tmp_path)
    first = _human_evidence("order-a")
    second = _human_evidence("order-b")
    forward = replace(mapping, evidence=(first.identifier, second.identifier))
    reverse = replace(mapping, evidence=(second.identifier, first.identifier))

    forward_bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(first, second),
        mapping_assertions=(forward,),
    )
    reverse_bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(target, source),
        evidence_assertions=(second, first),
        mapping_assertions=(reverse,),
    )

    assert forward.evidence == reverse.evidence == tuple(sorted(forward.evidence))
    assert forward_bundle.as_record() == reverse_bundle.as_record()
    assert forward_bundle.artifact_bytes() == reverse_bundle.artifact_bytes()
