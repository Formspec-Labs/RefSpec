"""Protocol v2: relation-adjudicating validations, the agreement lattice, emission."""

from __future__ import annotations

from pathlib import Path

import pytest
import test_vocabulary_atlas as tva

from refspec.atlas import VocabularyAtlasError, build_vocabulary_atlas
from refspec.atlas.model import (
    CrosswalkArtifact,
    CrosswalkBundle,
    MachineValidation,
    MappingCandidate,
)
from refspec.atlas.qualification import VERDICT_OUTCOMES_V2
from refspec.atlas.queries import VocabularyAtlasQueries

_ADJUDICATED_RELATION = "https://refspec.org/ns/vocabulary-atlas/v1#adjudicatedRelation"


def _v2_validation(
    candidate: MappingCandidate,
    request: CrosswalkArtifact,
    response: CrosswalkArtifact,
    *,
    suffix: str,
    verdict: str,
) -> MachineValidation:
    return MachineValidation.create(
        candidate=candidate.reference(),
        validator_kind="aiModel",
        validator_actor=f"urn:test:atlas:validator:{suffix}",
        independence_group=f"urn:test:atlas:group:{suffix}",
        provider=f"urn:test:atlas:provider:{suffix}",
        provider_model_id=f"provider-model-{suffix}",
        sealed_input_digest=tva.INPUT_DIGEST,
        request_artifact=request.reference(),
        response_artifact=response.reference(),
        deterministic_checks_passed=True,
        outcome=VERDICT_OUTCOMES_V2[verdict],  # type: ignore[arg-type]
        completed_at="2026-08-03T18:05:00Z",
        verdict_relation=verdict,
    )


def _v2_bundle(verdict_a: str, verdict_b: str) -> CrosswalkBundle:
    candidate, evidence, request, response_a, response_b = tva._candidate_and_artifacts()
    return CrosswalkBundle.create(
        artifacts=(tva._input_context(), evidence, request, response_a, response_b),
        mapping_candidates=(candidate,),
        machine_validations=(
            _v2_validation(candidate, request, response_a, suffix="a", verdict=verdict_a),
            _v2_validation(candidate, request, response_b, suffix="b", verdict=verdict_b),
        ),
    )


def _built_mappings(tmp_path: Path, bundle: CrosswalkBundle):
    asset = build_vocabulary_atlas(
        tva._two_releases(tmp_path),
        rulespec_core=tva._core_release(tmp_path),
        crosswalks=(bundle,),
    )
    return asset, VocabularyAtlasQueries(asset).search_only_mappings()


@pytest.mark.parametrize(
    ("verdict_a", "verdict_b", "relation"),
    [
        ("same", "same", "http://www.w3.org/2004/02/skos/core#exactMatch"),
        ("same", "near_same", "http://www.w3.org/2004/02/skos/core#closeMatch"),
        ("near_same", "near_same", "http://www.w3.org/2004/02/skos/core#closeMatch"),
        ("target_is_broader", "target_is_broader", "http://www.w3.org/2004/02/skos/core#broadMatch"),
        ("target_is_narrower", "target_is_narrower", "http://www.w3.org/2004/02/skos/core#narrowMatch"),
    ],
)
def test_agreement_lattice_emits_the_weaker_claim(
    tmp_path: Path, verdict_a: str, verdict_b: str, relation: str
) -> None:
    bundle = _v2_bundle(verdict_a, verdict_b)
    assert bundle.to_dict()["schemaVersion"] == "2.0"

    asset, mappings = _built_mappings(tmp_path, bundle)

    assert asset.manifest["counts"]["searchOnlyMappings"] == 1
    assert [mapping.relation for mapping in mappings] == [relation]


def test_adjudicated_related_records_the_relation_but_emits_no_mapping(tmp_path: Path) -> None:
    bundle = _v2_bundle("related", "related")

    asset, mappings = _built_mappings(tmp_path, bundle)

    assert mappings == ()
    assert asset.manifest["counts"]["searchOnlyMappings"] == 0
    assert bundle.qualified() == {}
    payload = asset.payload.decode("utf-8")
    assert _ADJUDICATED_RELATION in payload
    assert '"related"' in payload or "> \"related\"" in payload


def test_direction_disagreement_is_a_refusal(tmp_path: Path) -> None:
    bundle = _v2_bundle("near_same", "target_is_broader")

    asset, mappings = _built_mappings(tmp_path, bundle)

    assert mappings == ()
    assert asset.manifest["counts"]["searchOnlyMappings"] == 0
    assert _ADJUDICATED_RELATION not in asset.payload.decode("utf-8")


def test_bundle_refuses_mixed_protocols() -> None:
    candidate, evidence, request, response_a, response_b = tva._candidate_and_artifacts()
    with pytest.raises(VocabularyAtlasError, match="mixes v1 and v2"):
        CrosswalkBundle.create(
            artifacts=(tva._input_context(), evidence, request, response_a, response_b),
            mapping_candidates=(candidate,),
            machine_validations=(
                _v2_validation(candidate, request, response_a, suffix="a", verdict="near_same"),
                tva._validation(candidate, request, response_b, suffix="b"),
            ),
        )


def test_v2_bundle_round_trips_through_write_and_open(tmp_path: Path) -> None:
    bundle = _v2_bundle("same", "same")
    path = bundle.write(tmp_path / "bundle.json")

    reopened = CrosswalkBundle.open(
        path,
        expected_file_digest=tva._file_digest(path),
        expected_bundle_digest=bundle.digest,
    )

    assert reopened.to_dict() == bundle.to_dict()
    assert reopened.to_dict()["schemaVersion"] == "2.0"


def test_outcome_must_match_verdict_relation() -> None:
    candidate, _, request, response_a, _ = tva._candidate_and_artifacts()
    with pytest.raises(VocabularyAtlasError, match="disagrees with its verdictRelation"):
        MachineValidation.create(
            candidate=candidate.reference(),
            validator_kind="aiModel",
            validator_actor="urn:test:atlas:validator:a",
            independence_group="urn:test:atlas:group:a",
            provider="urn:test:atlas:provider:a",
            provider_model_id="provider-model-a",
            sealed_input_digest=tva.INPUT_DIGEST,
            request_artifact=request.reference(),
            response_artifact=response_a.reference(),
            deterministic_checks_passed=True,
            outcome="rejects",
            completed_at="2026-08-03T18:05:00Z",
            verdict_relation="near_same",
        )
