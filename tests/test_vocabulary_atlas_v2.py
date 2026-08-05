"""Protocol v2 agreement, refusal, and shared-foundation emission."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from refspec.atlas import qualification as qual
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
from refspec.storage import canonical_json

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "_refspec_atlas_qualification_runner_v2",
    REFSPEC_ROOT / "tools/run_atlas_qualification.py",
)
assert _RUNNER_SPEC is not None and _RUNNER_SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(_RUNNER_SPEC)
_RUNNER_SPEC.loader.exec_module(RUNNER)

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
    generation_class: str | None = None,
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
    evidence_content = {"method": "sealed-test-comparison"}
    if generation_class is not None:
        evidence_content.update(
            {
                "generationClass": generation_class,
                "generationPolicy": "atlas-crosswalk-candidate-generation-production-v1",
            }
        )
    evidence = CrosswalkArtifact.create(
        role="evidence",
        media_type="application/json",
        content=evidence_content,
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


def test_related_agreement_is_a_first_class_qualified_mapping() -> None:
    case = _crosswalk_case("related", "related")

    assert tuple(case.bundle.qualified()) == (case.candidate.identifier,)
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


@pytest.mark.parametrize(
    ("verdict", "expected_relation"),
    [
        ("target_is_broader", SUBJECT_BROAD_MATCH),
        ("related", SUBJECT_RELATED_MATCH),
    ],
)
def test_adjudicated_relation_emits_through_the_shared_foundation(
    tmp_path: Path,
    verdict: str,
    expected_relation: str,
) -> None:
    source, source_release, source_concept = _source_release(tmp_path, "source")
    target, target_release, target_concept = _source_release(tmp_path, "target")
    case = _crosswalk_case(
        verdict,
        verdict,
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
        relation=expected_relation,
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

    assert proof.pin()["relation"] == expected_relation
    assert evidence.relation == expected_relation
    assert evidence.candidate == case.candidate.identifier
    assert reopened.mapping_assertions == (mapping,)
    assert source_concept in source.member_ids()
    assert target_concept in target.member_ids()
    assert len({case.candidate.identifier, evidence.identifier, mapping.identifier}) == 3


@pytest.mark.parametrize("generation_class", ["siblingDistractor", "randomNegativeControl"])
def test_control_candidates_remain_evidence_and_cannot_become_machine_proofs(
    tmp_path: Path,
    generation_class: str,
) -> None:
    case = _crosswalk_case("near_same", "near_same", generation_class=generation_class)
    path = case.bundle.write(tmp_path / f"{generation_class}.json")
    common = {
        "expected_file_digest": sha256_digest(path.read_bytes()),
        "expected_bundle_digest": case.bundle.digest,
        "candidate_id": case.candidate.identifier,
    }

    with pytest.raises(ValueError, match="control-arm candidate"):
        PinnedCrosswalkMachineProof.qualified(path, **common)
    with pytest.raises(ValueError, match="control-arm candidate"):
        PinnedCrosswalkMachineProof.reviewed(
            path,
            **common,
            validation_id=case.validations[0].identifier,
        )


def test_seal_relations_emits_every_accounted_non_control_mapping(tmp_path: Path) -> None:
    source, source_release, source_concept = _source_release(tmp_path, "seal-source")
    target, target_release, target_concept = _source_release(tmp_path, "seal-target")
    case = _crosswalk_case(
        "near_same",
        "near_same",
        source_concept=source_concept,
        source_release=source_release,
        target_concept=target_concept,
        target_release=target_release,
        generation_class="normalizedLabelEquality",
    )
    run_dir = tmp_path / "qualification-run"
    run_dir.mkdir()
    case.bundle.write(run_dir / RUNNER.BUNDLE)
    bundle_pin = case.bundle.pin()
    catalog = {
        "candidates": [{"candidateId": case.candidate.identifier}],
        "total": 1,
    }
    catalog_path = run_dir / RUNNER.CANDIDATES
    catalog_path.write_text(canonical_json(catalog) + "\n", encoding="utf-8")
    judge_receipts = [
        {"candidate_id": case.candidate.identifier, "family": "gemini"},
        {"candidate_id": case.candidate.identifier, "family": "openai"},
    ]
    receipt_path = run_dir / RUNNER.RECEIPTS
    receipt_path.write_text(
        "".join(canonical_json(row) + "\n" for row in judge_receipts),
        encoding="utf-8",
    )
    scorer_record = {
        "candidate_id": case.candidate.identifier,
        "family": "openai",
        "kind": "crosswalk_scoring",
        "protocol": qual.SCORING_PROTOCOL,
        "model_id": "gpt-5.6-terra",
        "outcome": "completed",
        "task_id": "score-task-seal-relations",
        "request_url": "https://api.openai.com/v1/chat/completions",
        "request_sha256": "sha256:" + "4" * 64,
        "response_sha256": "sha256:" + "5" * 64,
        "finished_at": ASSERTED_AT,
        "answer": {
            "task_id": "score-task-seal-relations",
            "semantic_plausibility": 90,
            "evidence_sufficiency": 85,
            "likely_relation": "near_same",
            "reason": "the exact source facts support blind review",
        },
    }
    scoring_path = run_dir / RUNNER.SCORING_RECEIPTS
    scoring_path.write_text(canonical_json(scorer_record) + "\n", encoding="utf-8")
    scorer_pin = {
        "family": "openai",
        "outcome": "completed",
        "deterministicChecksPassed": True,
        "modelId": "gpt-5.6-terra",
        "endpoint": "api.openai.com",
        "requestSha256": "sha256:" + "4" * 64,
        "responseSha256": "sha256:" + "5" * 64,
        "receiptDigest": sha256_digest(scoring_path.read_bytes()),
    }
    accounting = {
        "candidateId": case.candidate.identifier,
        "generationClass": "normalizedLabelEquality",
        "control": False,
        "scored": True,
        "scorerReceipts": [scorer_pin],
        "judgeReceipts": [
            {
                "family": row["family"],
                "outcome": "completed",
                "receiptDigest": sha256_digest((canonical_json(row) + "\n").encode("utf-8")),
            }
            for row in judge_receipts
        ],
        "judged": True,
        "disposition": "admitted",
        "relation": SUBJECT_CLOSE_MATCH,
    }
    run = qual.seal_qualification_run_receipt(
        {
            "type": qual.QUALIFICATION_RUN_RECEIPT_TYPE,
            "schemaVersion": qual.QUALIFICATION_RUN_RECEIPT_VERSION,
            "coverageMode": qual.PRODUCTION_COVERAGE_MODE,
            "candidateGenerationPolicy": qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
            "productionFloor": qual.PRODUCTION_FLOOR,
            "protocol": qual.PROTOCOL,
            "candidateCatalog": {
                "file": RUNNER.CANDIDATES,
                "fileDigest": sha256_digest(catalog_path.read_bytes()),
                "total": 1,
            },
            "bundle": {
                "file": RUNNER.BUNDLE,
                "fileDigest": bundle_pin["fileDigest"],
                "id": bundle_pin["id"],
                "bundleDigest": bundle_pin["digest"],
            },
            "receiptLog": {
                "file": RUNNER.RECEIPTS,
                "fileDigest": sha256_digest(receipt_path.read_bytes()),
                "total": 2,
            },
            "scoring": {
                "protocol": qual.SCORING_PROTOCOL,
                "receiptLog": {
                    "file": RUNNER.SCORING_RECEIPTS,
                    "fileDigest": sha256_digest(scoring_path.read_bytes()),
                    "total": 1,
                },
            },
            "candidateAccounting": [accounting],
            "counts": {
                "generated": 1,
                "scored": 1,
                "scorerReceipts": 1,
                "judgeReceipts": 2,
                "judged": 1,
                "abstained": 0,
                "rejected": 0,
                "controlled": 0,
                "admitted": 1,
                "incomplete": 0,
            },
        }
    )
    (run_dir / RUNNER.RUN_RECEIPT).write_text(canonical_json(run) + "\n", encoding="utf-8")

    assert RUNNER.main(
        [
            "--output",
            str(run_dir),
            "seal-relations",
            "--source-release-manifest",
            str(source.manifest_path),
            "--target-release-manifest",
            str(target.manifest_path),
            "--asserted-by",
            "https://refspec.org/software/qualification-gate-v2",
            "--asserted-at",
            ASSERTED_AT,
        ]
    ) == 0
    record = json.loads((run_dir / "relation-assertions/relation-assertions.json").read_text(encoding="utf-8"))
    assert len(record["mappingAssertions"]) == 1
    assert record["mappingAssertions"][0]["relation"] == SUBJECT_CLOSE_MATCH
    proof_details = record["machineProofPins"][0]["proofDetails"]
    assert proof_details["candidateGeneration"] == {
        "class": "normalizedLabelEquality",
        "policy": qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
    }
    assert proof_details["qualificationRun"]["id"] == run["id"]
    assert proof_details["qualificationRun"]["scorerReceipts"] == [scorer_pin]
