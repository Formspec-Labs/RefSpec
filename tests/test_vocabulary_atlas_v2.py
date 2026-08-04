"""Protocol v2: relation-adjudicating validations, the agreement lattice, emission."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import test_vocabulary_atlas as tva

from refspec.atlas import VocabularyAtlasError, build_vocabulary_atlas
from refspec.atlas.model import (
    CrosswalkArtifact,
    CrosswalkBundle,
    MachineValidation,
    MappingCandidate,
    VocabularyAtlasAsset,
)
from refspec.atlas.projection import build_atlas_projection
from refspec.atlas.qualification import VERDICT_OUTCOMES_V2
from refspec.atlas.queries import VocabularyAtlasQueries

_ADJUDICATED_RELATION = "https://refspec.org/ns/vocabulary-atlas/v1#adjudicatedRelation"
_RELATED_MATCH = "http://www.w3.org/2004/02/skos/core#relatedMatch"


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


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _round_trip(tmp_path: Path, asset) -> VocabularyAtlasAsset:
    """Write, reopen under full verification, and project for a consumer.

    Building an atlas proves only that the writer will emit it. `open` is the
    reader every consumer goes through, and the projection is what a consumer
    actually receives, so a relation that cannot survive both was never
    publishable.
    """

    directory = tmp_path / "published"
    asset.write(directory)
    manifest_digest = _file_digest(directory / "atlas-manifest.json")
    output_digest = _file_digest(directory / "atlas.nq")
    reopened = VocabularyAtlasAsset.open(
        directory,
        expected_manifest_digest=manifest_digest,
        expected_output_digest=output_digest,
    )
    build_atlas_projection(
        directory,
        expected_manifest_digest=manifest_digest,
        expected_output_digest=output_digest,
    )
    return reopened


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
    # An emitted relation that cannot survive `open` and the consumer projection
    # was never published, whatever the builder produced.
    reopened = _round_trip(tmp_path, asset)
    assert [item.relation for item in VocabularyAtlasQueries(reopened).search_only_mappings()] == [relation]
    assert f"<{_ADJUDICATED_RELATION}> <{relation}>" in reopened.payload.decode("utf-8")
    assert bundle.adjudicated_relations() == {next(iter(bundle.qualified())): relation}


def test_the_adjudicated_relation_anchors_the_mapping_not_the_proposal(tmp_path: Path) -> None:
    """`proposedRelation` is the hypothesis under test and never moves.

    v1 could anchor a mapping to the proposal because the proposal *was* the
    verdict. v2 answers a richer question, so anchoring to the proposal would
    forbid every relation except the one hypothesis the candidate holds.
    """

    bundle = _v2_bundle("target_is_broader", "target_is_broader")
    candidate = bundle.to_dict()["mappingCandidates"][0]
    assert candidate["proposedRelation"] == "http://www.w3.org/2004/02/skos/core#closeMatch"

    asset, mappings = _built_mappings(tmp_path, bundle)
    _round_trip(tmp_path, asset)

    assert [mapping.relation for mapping in mappings] == ["http://www.w3.org/2004/02/skos/core#broadMatch"]


def test_adjudicated_related_records_the_relation_but_emits_no_mapping(tmp_path: Path) -> None:
    bundle = _v2_bundle("related", "related")

    asset, mappings = _built_mappings(tmp_path, bundle)
    reopened = _round_trip(tmp_path, asset)

    assert mappings == ()
    assert asset.manifest["counts"]["searchOnlyMappings"] == 0
    assert bundle.qualified() == {}
    # Recorded as a relation like any other, so a reader of the analysis graph
    # sees a typed refusal rather than a blank one.
    assert f"<{_ADJUDICATED_RELATION}> <{_RELATED_MATCH}>" in reopened.payload.decode("utf-8")
    assert set(bundle.adjudicated_relations().values()) == {_RELATED_MATCH}


def test_adjudicated_related_is_analysis_only_and_does_not_reach_the_projection(
    tmp_path: Path,
) -> None:
    """The typed refusal is bundle- and analysis-internal, by decision.

    `CONSUMER_READ_CLOSURE_V1` roots its keep-set on qualified `searchOnly`
    mappings, and an adjudicated-`related` candidate has none, so it is dropped.
    This test states that limit rather than letting it be discovered later.
    """

    bundle = _v2_bundle("related", "related")
    asset, _ = _built_mappings(tmp_path, bundle)
    directory = tmp_path / "published"
    asset.write(directory)

    projection = build_atlas_projection(
        directory,
        expected_manifest_digest=_file_digest(directory / "atlas-manifest.json"),
        expected_output_digest=_file_digest(directory / "atlas.nq"),
    )

    assert _ADJUDICATED_RELATION not in projection.payload.decode("utf-8")
    assert _ADJUDICATED_RELATION in asset.payload.decode("utf-8")


def test_direction_disagreement_is_a_refusal(tmp_path: Path) -> None:
    bundle = _v2_bundle("near_same", "target_is_broader")

    asset, mappings = _built_mappings(tmp_path, bundle)
    _round_trip(tmp_path, asset)

    assert mappings == ()
    assert asset.manifest["counts"]["searchOnlyMappings"] == 0
    assert _ADJUDICATED_RELATION not in asset.payload.decode("utf-8")
    assert bundle.adjudicated_relations() == {}


def test_a_third_machine_cannot_outvote_a_direction_disagreement(tmp_path: Path) -> None:
    """The relation gate is universal over machines, not existential over pairs.

    Picking any compatible pair would let two agreeing machines carry a mapping
    while a third machine on the record says the direction is unsafe — emitting
    the relation would overrule it on the precise claim that relation makes.
    """

    candidate, evidence, request, response_a, response_b = tva._candidate_and_artifacts()
    response_c = tva._response(candidate, request, suffix="c")
    bundle = CrosswalkBundle.create(
        artifacts=(tva._input_context(), evidence, request, response_a, response_b, response_c),
        mapping_candidates=(candidate,),
        machine_validations=(
            _v2_validation(candidate, request, response_a, suffix="a", verdict="near_same"),
            _v2_validation(candidate, request, response_b, suffix="b", verdict="target_is_broader"),
            _v2_validation(candidate, request, response_c, suffix="c", verdict="near_same"),
        ),
    )

    asset, mappings = _built_mappings(tmp_path, bundle)
    _round_trip(tmp_path, asset)

    assert mappings == ()
    assert bundle.qualified() == {}


def test_three_agreeing_machines_still_emit_the_weakest_claim(tmp_path: Path) -> None:
    """The emitted relation folds every verdict, not whichever pair sorts first."""

    candidate, evidence, request, response_a, response_b = tva._candidate_and_artifacts()
    response_c = tva._response(candidate, request, suffix="c")
    bundle = CrosswalkBundle.create(
        artifacts=(tva._input_context(), evidence, request, response_a, response_b, response_c),
        mapping_candidates=(candidate,),
        machine_validations=(
            _v2_validation(candidate, request, response_a, suffix="a", verdict="same"),
            _v2_validation(candidate, request, response_b, suffix="b", verdict="same"),
            _v2_validation(candidate, request, response_c, suffix="c", verdict="near_same"),
        ),
    )

    _, mappings = _built_mappings(tmp_path, bundle)

    # `same` twice would be exactMatch on its own; the third machine withheld
    # identity, so the set qualifies at the weaker claim.
    assert [mapping.relation for mapping in mappings] == ["http://www.w3.org/2004/02/skos/core#closeMatch"]


def _reverify(asset) -> None:
    """Re-run the distribution checks a consumer runs, over a graph in hand."""

    from rdflib import Dataset

    from refspec.atlas.model import _validate_query_graph_semantics

    dataset = Dataset(default_union=False)
    dataset.parse(data=asset.payload.decode("utf-8"), format="nquads")
    graphs = {row["role"]: row["id"] for row in asset.manifest["graphs"]}
    _validate_query_graph_semantics(
        dataset,
        release_graph_id=graphs["releaseFacts"],
        analysis_graph_id=graphs["analysis"],
    )
    return dataset, graphs


def test_dropping_the_adjudication_does_not_escape_the_lattice(tmp_path: Path) -> None:
    """The lattice must not be opt-in for the party with a motive to skip it.

    A producer that simply omits `atlas:adjudicatedRelation` would otherwise
    fall back to the uniform proposal, so a pair two machines typed as
    `broadMatch` could be published as `closeMatch` — the exact over-claim the
    relation vocabulary exists to prevent. The refusal has to come from the
    verdicts being present, not from the adjudication being volunteered.
    """

    from rdflib import URIRef

    from refspec.atlas.model import ATLAS, _validate_query_graph_semantics

    bundle = _v2_bundle("target_is_broader", "target_is_broader")
    asset, _ = _built_mappings(tmp_path, bundle)
    dataset, graphs = _reverify(asset)

    analysis = dataset.graph(URIRef(graphs["analysis"]))
    removed = list(analysis.triples((None, ATLAS.adjudicatedRelation, None)))
    assert len(removed) == 1
    for triple in removed:
        analysis.remove(triple)

    with pytest.raises(VocabularyAtlasError, match="omits the adjudicated relation"):
        _validate_query_graph_semantics(
            dataset,
            release_graph_id=graphs["releaseFacts"],
            analysis_graph_id=graphs["analysis"],
        )


def test_dropping_a_related_adjudication_does_not_hide_the_refusal(tmp_path: Path) -> None:
    """Adjudicated-`related` is the claim with no mapping to audit it by.

    Omitting it would turn a typed refusal back into a blank one while the
    verdicts still say the pair is merely associated.
    """

    from rdflib import URIRef

    from refspec.atlas.model import ATLAS, _validate_query_graph_semantics

    bundle = _v2_bundle("related", "related")
    asset, _ = _built_mappings(tmp_path, bundle)
    dataset, graphs = _reverify(asset)

    analysis = dataset.graph(URIRef(graphs["analysis"]))
    for triple in list(analysis.triples((None, ATLAS.adjudicatedRelation, None))):
        analysis.remove(triple)

    with pytest.raises(VocabularyAtlasError, match="omits the adjudicated relation"):
        _validate_query_graph_semantics(
            dataset,
            release_graph_id=graphs["releaseFacts"],
            analysis_graph_id=graphs["analysis"],
        )


def _partially_supported_bundle(other_verdict: str) -> CrosswalkBundle:
    """One machine supports with a relation; the other does not support at all."""

    candidate, evidence, request, response_a, _ = tva._candidate_and_artifacts()
    outcome = VERDICT_OUTCOMES_V2[other_verdict]
    response_b = tva._response(candidate, request, suffix="b", outcome=outcome)
    return CrosswalkBundle.create(
        artifacts=(tva._input_context(), evidence, request, response_a, response_b),
        mapping_candidates=(candidate,),
        machine_validations=(
            _v2_validation(candidate, request, response_a, suffix="a", verdict="same"),
            _v2_validation(candidate, request, response_b, suffix="b", verdict=other_verdict),
        ),
    )


@pytest.mark.parametrize("other_verdict", ["insufficient_evidence", "unrelated"])
def test_a_lone_supporting_verdict_owes_no_adjudication(tmp_path: Path, other_verdict: str) -> None:
    """One machine's relation is a claim, not an agreement.

    Adjudication is owed exactly when the gate would emit one — an independent,
    relation-compatible *pair*. A single support has no partner to agree with, so
    there is nothing to adjudicate and nothing to state. Demanding one here would
    refuse the ordinary shape where the second machine abstained or said no: 52
    of the three real v2 runs' candidates look precisely like this.
    """

    bundle = _partially_supported_bundle(other_verdict)
    asset, mappings = _built_mappings(tmp_path, bundle)

    assert mappings == ()
    assert bundle.qualified() == {}
    assert bundle.adjudicated_relations() == {}
    assert _ADJUDICATED_RELATION not in asset.payload.decode("utf-8")
    _round_trip(tmp_path, asset)


def test_a_supporting_pair_that_is_not_independent_owes_no_adjudication(tmp_path: Path) -> None:
    """Two answers from one machine are one answer, so they adjudicate nothing."""

    candidate, evidence, request, _, _ = tva._candidate_and_artifacts()
    shared = {
        "provider": "urn:test:atlas:provider:shared",
        "provider_model_id": "shared-provider-model",
    }
    response_a = tva._response(candidate, request, suffix="a", **shared)
    response_b = tva._response(candidate, request, suffix="b", **shared)
    bundle = CrosswalkBundle.create(
        artifacts=(tva._input_context(), evidence, request, response_a, response_b),
        mapping_candidates=(candidate,),
        machine_validations=(
            MachineValidation.create(
                candidate=candidate.reference(),
                validator_kind="aiModel",
                validator_actor="urn:test:atlas:validator:a",
                independence_group="urn:test:atlas:group:a",
                sealed_input_digest=tva.INPUT_DIGEST,
                request_artifact=request.reference(),
                response_artifact=response_a.reference(),
                deterministic_checks_passed=True,
                outcome="supports",
                completed_at="2026-08-03T18:05:00Z",
                verdict_relation="same",
                **shared,
            ),
            MachineValidation.create(
                candidate=candidate.reference(),
                validator_kind="aiModel",
                validator_actor="urn:test:atlas:validator:b",
                independence_group="urn:test:atlas:group:b",
                sealed_input_digest=tva.INPUT_DIGEST,
                request_artifact=request.reference(),
                response_artifact=response_b.reference(),
                deterministic_checks_passed=True,
                outcome="supports",
                completed_at="2026-08-03T18:06:00Z",
                verdict_relation="same",
                **shared,
            ),
        ),
    )

    asset, mappings = _built_mappings(tmp_path, bundle)

    assert mappings == ()
    assert _ADJUDICATED_RELATION not in asset.payload.decode("utf-8")
    _round_trip(tmp_path, asset)


def test_a_v1_distribution_still_needs_no_adjudication(tmp_path: Path) -> None:
    """The new refusal keys on the verdicts, so v1 is untouched by it."""

    candidate, evidence, request, response_a, response_b = tva._candidate_and_artifacts()
    bundle = CrosswalkBundle.create(
        artifacts=(tva._input_context(), evidence, request, response_a, response_b),
        mapping_candidates=(candidate,),
        machine_validations=(
            tva._validation(candidate, request, response_a, suffix="a"),
            tva._validation(candidate, request, response_b, suffix="b"),
        ),
    )
    asset, mappings = _built_mappings(tmp_path, bundle)

    _reverify(asset)
    assert _ADJUDICATED_RELATION not in asset.payload.decode("utf-8")
    assert [mapping.relation for mapping in mappings] == ["http://www.w3.org/2004/02/skos/core#closeMatch"]


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
