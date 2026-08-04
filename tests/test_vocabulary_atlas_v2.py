"""Protocol v2 agreement, refusal, and shared-foundation emission."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from refspec.atlas.concept_release import PinnedSourceConceptRelease
from refspec.atlas.machine_evidence import (
    PinnedCrosswalkMachineProof,
    build_machine_evidence_from_crosswalk_proof,
)
from refspec.atlas.model import (
    CrosswalkArtifact,
    CrosswalkBundle,
    MachineValidation,
    MappingCandidate,
    VocabularyAtlasError,
)
from refspec.atlas.qualification import VERDICT_OUTCOMES_V2
from refspec.atlas.relation_assertion import RelationAssertionBundle
from refspec.registry.infrastructure.artifact_serialization import sha256_digest
from refspec.registry.infrastructure.semantic_foundation import (
    SUBJECT_BROAD_MATCH,
    SUBJECT_CLOSE_MATCH,
    SUBJECT_EXACT_MATCH,
    SUBJECT_NARROW_MATCH,
    SUBJECT_RELATED_MATCH,
    MappingAssertion,
)
from refspec.registry.infrastructure.source_concept_release import (
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7

ASSERTED_AT = "2026-08-04T20:00:00Z"
_SOURCE_CONCEPT = "https://publisher.example/concepts/source"
_SOURCE_RELEASE = "https://publisher.example/releases/source"
_TARGET_CONCEPT = "https://publisher.example/concepts/target"
_TARGET_RELEASE = "https://publisher.example/releases/target"


@dataclass(frozen=True, slots=True)
class _CrosswalkCase:
    bundle: CrosswalkBundle
    candidate: MappingCandidate
    request: CrosswalkArtifact
    responses: tuple[CrosswalkArtifact, ...]
    validations: tuple[MachineValidation, ...]


def _crosswalk_case(
    *verdicts: str,
    source_concept: str = _SOURCE_CONCEPT,
    source_release: str = _SOURCE_RELEASE,
    target_concept: str = _TARGET_CONCEPT,
    target_release: str = _TARGET_RELEASE,
    shared_provider: bool = False,
) -> _CrosswalkCase:
    input_context = CrosswalkArtifact.create(
        role="inputContext",
        media_type="application/json",
        content={
            "sourceConcept": source_concept,
            "targetConcept": target_concept,
            "protocol": "refspec-atlas-machine-validation-v2",
        },
    )
    evidence = CrosswalkArtifact.create(
        role="evidence",
        media_type="application/json",
        content={"method": "sealed-test-comparison"},
    )
    candidate = MappingCandidate.create(
        source_member=source_concept,
        source_release=source_release,
        target_member=target_concept,
        target_release=target_release,
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
    for index, verdict in enumerate(verdicts):
        suffix = chr(ord("a") + index)
        provider_suffix = "shared" if shared_provider else suffix
        actor = f"urn:ref:test:validator:{suffix}"
        provider = f"urn:ref:test:provider:{provider_suffix}"
        provider_model_id = f"provider-model-{provider_suffix}"
        outcome = VERDICT_OUTCOMES_V2[verdict]
        response = CrosswalkArtifact.create(
            role="validationResponse",
            media_type="application/json",
            content={
                "candidate": candidate.reference(),
                "inputDigest": input_context.content_digest,
                "requestArtifact": request.reference(),
                "validatorActor": actor,
                "provider": provider,
                "providerModelId": provider_model_id,
                "deterministicChecksPassed": True,
                "outcome": outcome,
                "verdict": verdict,
            },
        )
        responses.append(response)
        validations.append(
            MachineValidation.create(
                candidate=candidate.reference(),
                validator_kind="aiModel",
                validator_actor=actor,
                independence_group=f"urn:ref:test:independence-group:{suffix}",
                provider=provider,
                provider_model_id=provider_model_id,
                sealed_input_digest=input_context.content_digest,
                request_artifact=request.reference(),
                response_artifact=response.reference(),
                deterministic_checks_passed=True,
                outcome=outcome,  # type: ignore[arg-type]
                completed_at=ASSERTED_AT,
                verdict_relation=verdict,
            )
        )
    bundle = CrosswalkBundle.create(
        artifacts=(input_context, evidence, request, *responses),
        mapping_candidates=(candidate,),
        machine_validations=tuple(validations),
    )
    return _CrosswalkCase(
        bundle=bundle,
        candidate=candidate,
        request=request,
        responses=tuple(responses),
        validations=tuple(validations),
    )


@pytest.mark.parametrize(
    ("verdicts", "relation"),
    [
        (("same", "same"), SUBJECT_EXACT_MATCH),
        (("same", "near_same"), SUBJECT_CLOSE_MATCH),
        (("near_same", "near_same"), SUBJECT_CLOSE_MATCH),
        (("target_is_broader", "target_is_broader"), SUBJECT_BROAD_MATCH),
        (("target_is_narrower", "target_is_narrower"), SUBJECT_NARROW_MATCH),
    ],
)
def test_agreement_lattice_adjudicates_the_weakest_safe_relation(
    verdicts: tuple[str, str],
    relation: str,
) -> None:
    case = _crosswalk_case(*verdicts)

    qualified = case.bundle.qualified()

    assert case.bundle.to_dict()["schemaVersion"] == "2.0"
    assert tuple(row["id"] for row in qualified[case.candidate.identifier]) == tuple(
        sorted(validation.identifier for validation in case.validations)
    )
    assert case.bundle.adjudicated_relations() == {case.candidate.identifier: relation}


def test_adjudication_is_not_anchored_to_the_candidate_proposal() -> None:
    case = _crosswalk_case("target_is_broader", "target_is_broader")

    assert case.candidate.to_dict()["proposedRelation"] == SUBJECT_CLOSE_MATCH
    assert case.bundle.adjudicated_relations() == {case.candidate.identifier: SUBJECT_BROAD_MATCH}


def test_related_agreement_is_typed_but_not_qualified_for_mapping() -> None:
    case = _crosswalk_case("related", "related")

    assert case.bundle.qualified() == {}
    assert case.bundle.adjudicated_relations() == {case.candidate.identifier: SUBJECT_RELATED_MATCH}


def test_direction_disagreement_is_a_refusal() -> None:
    case = _crosswalk_case("near_same", "target_is_broader")

    assert case.bundle.qualified() == {}
    assert case.bundle.adjudicated_relations() == {}


def test_a_third_machine_cannot_outvote_direction_disagreement() -> None:
    case = _crosswalk_case("near_same", "target_is_broader", "near_same")

    assert case.bundle.qualified() == {}
    assert case.bundle.adjudicated_relations() == {}


def test_three_agreeing_machines_retain_the_full_weakest_claim_set() -> None:
    case = _crosswalk_case("same", "same", "near_same")

    qualified = case.bundle.qualified()[case.candidate.identifier]

    assert {row["id"] for row in qualified} == {validation.identifier for validation in case.validations}
    assert case.bundle.adjudicated_relations() == {case.candidate.identifier: SUBJECT_CLOSE_MATCH}


@pytest.mark.parametrize("other_verdict", ["insufficient_evidence", "unrelated"])
def test_one_supporting_machine_does_not_adjudicate(other_verdict: str) -> None:
    case = _crosswalk_case("same", other_verdict)

    assert case.bundle.qualified() == {}
    assert case.bundle.adjudicated_relations() == {}


def test_answers_from_one_provider_do_not_count_as_independent() -> None:
    case = _crosswalk_case("same", "same", shared_provider=True)

    assert case.bundle.qualified() == {}
    assert case.bundle.adjudicated_relations() == {}


def test_v2_bundle_round_trips_through_exact_bytes(tmp_path: Path) -> None:
    case = _crosswalk_case("same", "same")
    path = case.bundle.write(tmp_path / "crosswalk-v2.json")

    reopened = CrosswalkBundle.open(
        path,
        expected_file_digest=sha256_digest(path.read_bytes()),
        expected_bundle_digest=case.bundle.digest,
    )

    assert reopened.to_dict() == case.bundle.to_dict()
    assert reopened.adjudicated_relations() == {case.candidate.identifier: SUBJECT_EXACT_MATCH}


def test_outcome_must_match_the_v2_verdict_relation() -> None:
    case = _crosswalk_case("near_same")
    validation = case.validations[0].to_dict()

    with pytest.raises(VocabularyAtlasError, match="disagrees with its verdictRelation"):
        MachineValidation.create(
            candidate=validation["candidate"],
            validator_kind="aiModel",
            validator_actor=validation["validatorActor"],
            independence_group=validation["independenceGroup"],
            provider=validation["provider"],
            provider_model_id=validation["providerModelId"],
            sealed_input_digest=validation["sealedInputDigest"],
            request_artifact=case.request.reference(),
            response_artifact=case.responses[0].reference(),
            deterministic_checks_passed=True,
            outcome="rejects",
            completed_at=ASSERTED_AT,
            verdict_relation="near_same",
        )


def _source_release(
    tmp_path: Path,
    name: str,
) -> tuple[PinnedSourceConceptRelease, str, str]:
    source_id = f"https://publisher.example/source/{name}.json"
    scheme_id = f"https://publisher.example/schemes/{name}"
    concept_id = f"https://publisher.example/concepts/{name}"
    payload = (f'{{"id":"{concept_id}","label":"{name.title()}"}}\n').encode()
    payload_digest = sha256_digest(payload)
    observation = {
        "id": f"urn:ref:test:source-observation:{name}",
        "sourceArtifact": source_id,
        "sourcePath": f"terms/{name}",
        "sourceOrdinal": 0,
        "labels": [{"value": name.title(), "language": "en", "role": "preferred"}],
        "identifiers": [
            {
                "value": concept_id,
                "kind": "publisherConceptIri",
                "authorityUri": scheme_id,
                "sourceUri": source_id,
                "sourcePath": f"terms/{name}.id",
                "observedAt": ASSERTED_AT,
                "sourceDigest": payload_digest,
            }
        ],
        "uses": ["mappingReference"],
        "conceptIdentityClaimed": False,
    }
    source = build_source_controlled_resource_bundle(
        resource_id=f"v2-shared-foundation-{name}",
        title=f"{name.title()} shared-foundation source",
        resource_kind="sourceTermSnapshot",
        identity_status="publisherIdentifiersPreserved",
        uses=("mappingReference",),
        captured_at=ASSERTED_AT,
        observations=(observation,),
        source_artifacts={source_id: payload},
        source_scheme={
            "id": scheme_id,
            "code": name,
            "label": f"{name.title()} scheme",
            "sourceArtifact": source_id,
            "sourceFetchId": derive_uuid7(
                ASSERTED_AT,
                seed=f"v2-shared-foundation-fetch:{name}".encode(),
            ),
            "sourceObservedAt": ASSERTED_AT,
        },
    )
    release = build_source_concept_release_bundle(
        source,
        semantic_ring="subject",
        selected_observation_ids=(observation["id"],),
        selection_policy={
            "id": f"urn:ref:test:v2-shared-foundation-selection:{name}:v1",
            "type": "explicitObservationSet",
        },
        rights_metadata=(
            {
                "type": "RightsMetadata",
                "rightsStatus": "notStated",
                "sourceArtifact": source_id,
                "sourceDigest": payload_digest,
            },
        ),
    )
    root = release.write_to(tmp_path / f"source-release-{name}")
    pinned = PinnedSourceConceptRelease.open(
        root / "bundle-manifest.json",
        expected_manifest_digest=release.manifest_digest,
    )
    return pinned, release.release_id, concept_id


def test_adjudicated_relation_emits_through_the_shared_foundation(
    tmp_path: Path,
) -> None:
    source, source_release, source_concept = _source_release(tmp_path, "source")
    target, target_release, target_concept = _source_release(tmp_path, "target")
    case = _crosswalk_case(
        "target_is_broader",
        "target_is_broader",
        source_concept=source_concept,
        source_release=source_release,
        target_concept=target_concept,
        target_release=target_release,
    )
    crosswalk_path = case.bundle.write(tmp_path / "crosswalk-machine-proof.json")
    proof = PinnedCrosswalkMachineProof.qualified(
        crosswalk_path,
        expected_file_digest=sha256_digest(crosswalk_path.read_bytes()),
        expected_bundle_digest=case.bundle.digest,
        candidate_id=case.candidate.identifier,
    )
    evidence = build_machine_evidence_from_crosswalk_proof(
        proof,
        asserted_by="https://refspec.org/software/qualification-gate-v2",
        asserted_at=ASSERTED_AT,
    )
    mapping = MappingAssertion(
        semantic_ring="subject",
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release,
        target_release=target_release,
        relation=SUBJECT_BROAD_MATCH,
        evidence=(evidence.identifier,),
        asserted_at=ASSERTED_AT,
    )
    relation_bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        machine_proof_sources=(proof,),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    root = relation_bundle.write_to(tmp_path / "relation-bundle")
    reopened = RelationAssertionBundle.open(
        root / "bundle-manifest.json",
        expected_manifest_digest=relation_bundle.manifest_digest,
        release_sources=(source, target),
        machine_proof_sources=(proof,),
    )

    assert proof.pin()["relation"] == SUBJECT_BROAD_MATCH
    assert evidence.relation == SUBJECT_BROAD_MATCH
    assert evidence.candidate == case.candidate.identifier
    assert reopened.mapping_assertions == (mapping,)
    assert source_concept in source.member_ids()
    assert target_concept in target.member_ids()
    assert len({case.candidate.identifier, evidence.identifier, mapping.identifier}) == 3
