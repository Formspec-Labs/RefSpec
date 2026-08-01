from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from rdflib import BNode, URIRef
from rdflib.namespace import DCAT, OWL, RDF, SKOS

from refspec.atlas import (
    ATLAS,
    ATLAS_GENERATION_POLICY,
    CROSSWALK_SELECTION_POLICY,
    RKAF,
    MappingCandidate,
    MappingFeedback,
    VerifiedCrosswalkBundle,
    VerifiedVocabularyRelease,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    VocabularyAtlasQueries,
    build_vocabulary_atlas,
)
from refspec.atlas import crosswalk as atlas_crosswalk
from refspec.atlas.cli import main as atlas_main
from refspec.atlas.model import CROSSWALK_INPUT_VERSION, sha256_bytes
from refspec.canonical import (
    canonical_digest,
    canonical_json_bytes,
    seal_vocabulary_release,
    stable_record,
)
from refspec.records import (
    AgentValidationReceipt,
    BaselineValidationReceipt,
    RecordReference,
    create_support_record,
)
from refspec.reference_resource import build_reference_resource_release

ROOT = Path(__file__).parents[1]
CURRENT_RELEASE = (
    ROOT
    / "release-records"
    / "fixtures"
    / "refspec-vocabulary-release-federal-register-2025-first-slice.json"
)
ATLAS_FIXTURE = (
    ROOT
    / "release-records"
    / "fixtures"
    / "refspec-vocabulary-atlas-federal-register-2025-first-slice"
)


def _release(name: str, preferred_label: str) -> VerifiedVocabularyRelease:
    scheme_id = f"https://example.test/vocabulary/{name}"
    concept_id = f"{scheme_id}/concept/statistics"
    version = "2026-07-31"
    concept_payload = {
        "concept_id": concept_id,
        "scheme_id": scheme_id,
        "preferred_label": preferred_label,
    }
    concept = {
        "concept_digest": canonical_digest(concept_payload),
        **concept_payload,
    }
    label = stable_record(
        {
            "concept_id": concept_id,
            "label": preferred_label,
            "language": "en",
            "label_kind": "preferred",
        },
        id_field="label_id",
        digest_field="label_digest",
        id_prefix="urn:refspec:label:",
    )
    distribution_payload = {
        "concepts": [concept],
        "labels": [label],
        "hierarchy": [],
        "mappings": [],
        "redirects": [],
    }
    payload = {
        "schema_version": "refspec-vocabulary-release-v1",
        "vocabulary": {
            "scheme_id": scheme_id,
            "version": version,
            "title": f"{name.title()} vocabulary",
        },
        "reference_resource_release": build_reference_resource_release(
            scheme_id=scheme_id,
            release_version=version,
            concept_ids=[concept_id],
            distribution_payload=distribution_payload,
        ),
        "concepts": [concept],
        "labels": [label],
        "hierarchy": [],
        "mappings": [],
        "redirects": [],
    }
    return VerifiedVocabularyRelease.from_record(seal_vocabulary_release(payload))


def _reference(record_type: str, key: str) -> RecordReference:
    record = create_support_record(record_type, {"key": key})
    return RecordReference.from_record(
        record,
        id_field="record_id",
        digest_field="record_digest",
    )


def _candidate(
    source: VerifiedVocabularyRelease,
    target: VerifiedVocabularyRelease,
) -> MappingCandidate:
    source_record = source.record()
    target_record = target.record()
    evidence = _reference("MappingEvidence", "statistics-crosswalk")
    return MappingCandidate.create(
        source_concept_id=source_record["concepts"][0]["concept_id"],
        source_release_id=source.release_id,
        target_concept_id=target_record["concepts"][0]["concept_id"],
        target_release_id=target.release_id,
        proposed_relation=str(SKOS.closeMatch),
        generator_kind="aiModel",
        generator_id="example/model-v1",
        generation_method="refspec-crosswalk-proposal-v1",
        model_id="example/model",
        model_version="v1",
        prompt_template_ref="urn:example:prompt:crosswalk-v1",
        temperature=0.0,
        input_context_hash="sha256:" + "1" * 64,
        evidence_refs=[evidence.to_dict()],
        generated_at="2026-07-31T17:00:00Z",
    )


def _machine_validation(
    candidate: MappingCandidate,
    *,
    validators: int = 2,
    distinct_identities: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidate_ref = RecordReference(candidate.candidate_id, candidate.candidate_digest)
    input_manifest = _reference("InputManifest", "mapping-input")
    request_contract = _reference("RequestContract", "mapping-validation-v1")
    agents: list[AgentValidationReceipt] = []
    for index in range(validators):
        identity_index = index + 1 if distinct_identities else 1
        agents.append(
            AgentValidationReceipt.create(
                attempt_id=f"mapping-validator-{index + 1}",
                owner="RefSpec atlas fixture",
                target_ref_and_digest=candidate_ref,
                protocol_and_version="refspec-crosswalk-agent-validation-v1",
                input_manifest_ref_and_digest=input_manifest,
                validator_actor_ref=f"urn:example:validator:{identity_index}",
                validator_kind="aiAgent" if index else "aiModel",
                independence_group=f"provider-family-{index + 1}",
                provider_and_model_id=f"example/model-{identity_index}",
                request_contract_ref_and_digest=request_contract,
                execution_status="completed",
                check_outcomes=(
                    {
                        "check_id": "semantic-direction",
                        "outcome": "pass",
                        "rationale": "The relation and direction are supported.",
                    },
                ),
                started_at="2026-07-31T17:01:00Z",
                completed_at="2026-07-31T17:02:00Z",
                response_artifact_ref_and_digest=_reference(
                    "ValidationResponse", f"response-{index + 1}"
                ),
                overall_recommendation="supports",
            )
        )
    baseline = BaselineValidationReceipt.create(
        owner="RefSpec atlas fixture",
        target_profile_and_release_ref=candidate_ref,
        sample_manifest_ref_and_digest=_reference("SampleManifest", "mapping-sample"),
        rubric_and_version="refspec-crosswalk-rubric-v1",
        aggregation_policy_and_version="refspec-crosswalk-two-independent-v1",
        deterministic_check_receipt_refs=(
            _reference("DeterministicCheckReceipt", "mapping-integrity"),
        ),
        deterministic_check_outcomes=(
            {
                "check_id": "exact-release-endpoints",
                "outcome": "pass",
                "rationale": "Both concepts belong to the exact pinned releases.",
            },
        ),
        agent_validation_receipt_refs=tuple(item.reference() for item in agents),
        aggregate_result="usable_for_search",
        disagreements_and_flags=(),
        known_limitations=("Search expansion only; never assert equivalence.",),
        evaluated_at="2026-07-31T17:03:00Z",
    )
    return [item.to_dict() for item in agents], baseline.to_dict()


def test_current_release_is_read_directly_with_an_external_file_pin() -> None:
    payload = CURRENT_RELEASE.read_bytes()
    release = VerifiedVocabularyRelease.open(
        CURRENT_RELEASE,
        expected_file_digest=sha256_bytes(payload),
    )
    assert release.record()["schema_version"] == "refspec-vocabulary-release-v1"
    assert release.pin()["fileDigest"] == sha256_bytes(payload)


def test_wrong_external_release_digest_fails_before_parsing() -> None:
    with pytest.raises(VocabularyAtlasError, match="external digest pin"):
        VerifiedVocabularyRelease.open(
            CURRENT_RELEASE,
            expected_file_digest="sha256:" + "0" * 64,
        )


def test_programmatic_records_cannot_claim_false_file_digests() -> None:
    release = _release("source", "Statistics")
    with pytest.raises(VocabularyAtlasError, match="canonical VocabularyRelease bytes"):
        VerifiedVocabularyRelease.from_record(
            release.record(),
            file_digest="sha256:" + "0" * 64,
        )
    bundle = {
        "schema_version": CROSSWALK_INPUT_VERSION,
        "mapping_candidates": [],
        "agent_validation_receipts": [],
        "baseline_validation_receipts": [],
        "feedback": [],
    }
    with pytest.raises(VocabularyAtlasError, match="canonical crosswalk bundle bytes"):
        VerifiedCrosswalkBundle.from_record(
            bundle,
            file_digest="sha256:" + "0" * 64,
        )


def test_nested_release_record_tampering_fails_after_outer_reseal() -> None:
    record = _release("source", "Statistics").record()
    record["concepts"][0]["preferred_label"] = "Tampered"
    payload = {
        key: value
        for key, value in record.items()
        if key not in {"release_id", "release_digest"}
    }
    with pytest.raises(VocabularyAtlasError, match="concept_digest"):
        VerifiedVocabularyRelease.from_record(seal_vocabulary_release(payload))


def test_reference_release_must_be_complete_and_digest_valid() -> None:
    record = _release("source", "Statistics").record()
    record["reference_resource_release"]["@graph"][0]["rkaf:membershipMode"] = (
        "rkaf:partialMembership"
    )
    payload = {
        key: value
        for key, value in record.items()
        if key not in {"release_id", "release_digest"}
    }
    with pytest.raises(VocabularyAtlasError, match="not complete"):
        VerifiedVocabularyRelease.from_record(seal_vocabulary_release(payload))


def test_asset_is_deterministic_blank_node_free_and_has_two_named_graphs() -> None:
    source = _release("source", "Statistics")
    target = _release("target", "Statistics")
    first = build_vocabulary_atlas([source, target])
    second = build_vocabulary_atlas([target, source])
    assert first.canonical_nquads() == second.canonical_nquads()
    dataset = first.dataset
    graph_ids = {str(graph.identifier) for graph in dataset.graphs() if len(graph)}
    assert graph_ids == {first.asserted_graph_iri, first.analysis_graph_iri}
    assert not any(
        isinstance(value, BNode)
        for quad in dataset.quads((None, None, None, None))
        for value in quad
    )
    assert not tuple(dataset.quads((None, OWL.sameAs, None, None)))
    for relation in (
        SKOS.exactMatch,
        SKOS.closeMatch,
        SKOS.broadMatch,
        SKOS.narrowMatch,
        SKOS.relatedMatch,
    ):
        assert not tuple(dataset.quads((None, relation, None, None)))


def test_equal_labels_create_a_cluster_but_not_a_mapping() -> None:
    source = _release("source", "  Statistics ")
    target = _release("target", "statistics")
    asset = build_vocabulary_atlas([source, target])
    queries = VocabularyAtlasQueries(asset)
    clusters = queries.label_clusters()
    assert len(clusters) == 1
    assert clusters[0].normalized_label == "statistics"
    assert len(clusters[0].concept_ids) == 2
    assert queries.search_only_mappings() == ()


def test_model_candidate_stays_ineligible_without_baseline_validation() -> None:
    source = _release("source", "Statistics")
    target = _release("target", "Statistical data")
    candidate = _candidate(source, target)
    queries = VocabularyAtlasQueries(
        build_vocabulary_atlas(
            [source, target],
            mapping_candidates=[candidate],
        )
    )
    assert queries.search_only_mappings() == ()
    assert queries.mapping_candidates()[0].qualified_for_search is False


def test_two_independent_machine_validators_qualify_search_without_human_review() -> (
    None
):
    source = _release("source", "Statistics")
    target = _release("target", "Statistical data")
    candidate = _candidate(source, target)
    agents, baseline = _machine_validation(candidate)
    queries = VocabularyAtlasQueries(
        build_vocabulary_atlas(
            [source, target],
            mapping_candidates=[candidate],
            agent_validation_receipts=agents,
            baseline_validation_receipts=[baseline],
        )
    )
    mappings = queries.search_only_mappings()
    assert len(mappings) == 1
    assert mappings[0].candidate_id == candidate.candidate_id
    assert mappings[0].relation == str(SKOS.closeMatch)
    assert queries.mapping_candidates()[0].qualified_for_search is True
    candidate_node = URIRef(candidate.candidate_id)
    asserted_mapping = URIRef(mappings[0].mapping_id)
    assert (
        candidate_node,
        ATLAS.verificationStatus,
        ATLAS.unverified,
    ) in queries._analysis
    assert (
        candidate_node,
        ATLAS.selectionDisposition,
        ATLAS.selectedForSearchOnly,
    ) in queries._analysis
    assert (
        asserted_mapping,
        ATLAS.verificationStatus,
        ATLAS.unverified,
    ) in queries._asserted
    assert (
        asserted_mapping,
        RKAF.assertionOrigin,
        RKAF.aiSuggested,
    ) in queries._asserted
    assert (
        asserted_mapping,
        RKAF.epistemicBasis,
        RKAF.statisticalInference,
    ) in queries._asserted
    assert (
        asserted_mapping,
        RKAF.assertionPolarity,
        RKAF.affirmed,
    ) in queries._asserted
    assert (
        asserted_mapping,
        RKAF.sourceConceptRelease,
        URIRef(source.reference_release_id),
    ) in queries._asserted
    assert (
        asserted_mapping,
        RKAF.targetConceptRelease,
        URIRef(target.reference_release_id),
    ) in queries._asserted
    for release in (source, target):
        reference_node = URIRef(release.reference_release_id)
        assert (
            reference_node,
            RDF.type,
            RKAF.ReferenceResourceRelease,
        ) in queries._asserted
        distributions = tuple(
            queries._asserted.objects(reference_node, DCAT.distribution)
        )
        assert len(distributions) == 1
        assert (distributions[0], RDF.type, RKAF.Artifact) in queries._asserted
    lineage = tuple(queries._asserted.objects(asserted_mapping, RKAF.hasAILineage))
    assert len(lineage) == 1
    assert (lineage[0], RDF.type, RKAF.AILineage) in queries._analysis
    for predicate in (
        RKAF.modelId,
        RKAF.modelVersion,
        RKAF.promptTemplateRef,
        RKAF.temperature,
        RKAF.inputContextHash,
    ):
        assert len(tuple(queries._analysis.objects(lineage[0], predicate))) == 1
    evidence_bindings = tuple(
        queries._asserted.subjects(RKAF.bindsAssertion, asserted_mapping)
    )
    assert len(evidence_bindings) == 1
    assert (
        evidence_bindings[0],
        RKAF.noEvidenceReason,
        RKAF["declared-hypothesis"],
    ) in queries._asserted


def test_one_machine_validator_cannot_make_a_usable_baseline() -> None:
    source = _release("source", "Statistics")
    target = _release("target", "Statistical data")
    candidate = _candidate(source, target)
    agents, baseline = _machine_validation(candidate, validators=1)
    with pytest.raises(
        VocabularyAtlasError, match="distinct groups, actors, and providers"
    ):
        build_vocabulary_atlas(
            [source, target],
            mapping_candidates=[candidate],
            agent_validation_receipts=agents,
            baseline_validation_receipts=[baseline],
        )


def test_stable_but_incomplete_agent_receipt_cannot_qualify() -> None:
    source = _release("source", "Statistics")
    target = _release("target", "Statistical data")
    candidate = _candidate(source, target)
    agents, baseline = _machine_validation(candidate)
    incomplete_payload = {
        key: value
        for key, value in agents[0].items()
        if key not in {"receipt_id", "receipt_digest", "validator_actor_ref"}
    }
    agents[0] = stable_record(
        incomplete_payload,
        id_field="receipt_id",
        digest_field="receipt_digest",
        id_prefix="urn:refspec:agent-validation-receipt:",
    )
    with pytest.raises(VocabularyAtlasError, match="agent receipt fields differ"):
        build_vocabulary_atlas(
            [source, target],
            mapping_candidates=[candidate],
            agent_validation_receipts=agents,
            baseline_validation_receipts=[baseline],
        )


def test_distinct_group_labels_do_not_hide_same_validator_identity() -> None:
    source = _release("source", "Statistics")
    target = _release("target", "Statistical data")
    candidate = _candidate(source, target)
    agents, baseline = _machine_validation(
        candidate,
        distinct_identities=False,
    )
    with pytest.raises(
        VocabularyAtlasError, match="distinct groups, actors, and providers"
    ):
        build_vocabulary_atlas(
            [source, target],
            mapping_candidates=[candidate],
            agent_validation_receipts=agents,
            baseline_validation_receipts=[baseline],
        )


def test_candidate_must_name_concepts_in_the_exact_releases() -> None:
    source = _release("source", "Statistics")
    target = _release("target", "Statistical data")
    wrong_release = _release("wrong", "Other")
    candidate_record = _candidate(source, target).to_dict()
    candidate_record["source_release_id"] = wrong_release.release_id
    candidate_payload = {
        key: value
        for key, value in candidate_record.items()
        if key not in {"candidate_id", "candidate_digest"}
    }
    candidate = MappingCandidate.from_dict(
        stable_record(
            candidate_payload,
            id_field="candidate_id",
            digest_field="candidate_digest",
            id_prefix="urn:refspec:mapping-candidate:",
        )
    )
    with pytest.raises(VocabularyAtlasError, match="source is outside"):
        build_vocabulary_atlas(
            [source, target, wrong_release], mapping_candidates=[candidate]
        )


def test_optional_feedback_does_not_change_mapping_eligibility() -> None:
    source = _release("source", "Statistics")
    target = _release("target", "Statistical data")
    candidate = _candidate(source, target)
    agents, baseline = _machine_validation(candidate)
    without_feedback = build_vocabulary_atlas(
        [source, target],
        mapping_candidates=[candidate],
        agent_validation_receipts=agents,
        baseline_validation_receipts=[baseline],
    )
    feedback = MappingFeedback.create(
        candidate_ref=candidate.reference(),
        actor_ref="urn:example:later-reviewer",
        disposition="challenges",
        comment="This later feedback should enter the next validation cycle.",
        recorded_at="2026-08-01T12:00:00Z",
    )
    with_feedback = build_vocabulary_atlas(
        [source, target],
        mapping_candidates=[candidate],
        agent_validation_receipts=agents,
        baseline_validation_receipts=[baseline],
        feedback=[feedback],
    )
    before = VocabularyAtlasQueries(without_feedback).search_only_mappings()
    after_queries = VocabularyAtlasQueries(with_feedback)
    assert after_queries.search_only_mappings() == before
    assert after_queries.feedback(candidate.candidate_id)[0].disposition == "challenges"


def test_asset_returns_disposable_dataset_copies_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    asset = build_vocabulary_atlas([_release("source", "Statistics")])
    original = asset.canonical_nquads()
    disposable = asset.dataset
    disposable.graph(URIRef(asset.asserted_graph_iri)).add(
        (URIRef("urn:test:s"), URIRef("urn:test:p"), URIRef("urn:test:o"))
    )
    assert asset.canonical_nquads() == original
    written = asset.write_to(tmp_path)
    written["atlas.nq"].write_text("different\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        asset.write_to(tmp_path)


def test_manifest_pins_policy_implementation_runtime_and_asset_identity() -> None:
    asset = build_vocabulary_atlas([_release("source", "Statistics")])
    manifest = asset.manifest()
    assert manifest["assetId"] == asset.asserted_graph_iri
    assert manifest["policies"] == {
        "candidateSelection": CROSSWALK_SELECTION_POLICY,
        "generation": ATLAS_GENERATION_POLICY,
    }
    assert {item["path"] for item in manifest["implementation"]["sourceModules"]} == {
        "refspec/atlas/model.py",
        "refspec/atlas/crosswalk.py",
        "refspec/canonical.py",
        "refspec/reference_resource.py",
        "refspec/rulespec_core.py",
    }
    assert all(
        item["sha256"].startswith("sha256:")
        for item in manifest["implementation"]["sourceModules"]
    )
    assert manifest["implementation"]["runtime"]["rdflibVersion"]
    assert len(manifest["implementation"]["validationArtifacts"]) == 3
    assert manifest["output"]["mediaType"] == "application/n-quads"


def test_implementation_pin_changes_asset_identity(monkeypatch) -> None:
    release = _release("source", "Statistics")
    original = build_vocabulary_atlas([release])
    changed_pin = deepcopy(atlas_crosswalk.atlas_implementation_pin())
    changed_pin["runtime"]["rdflibVersion"] += "+different"
    monkeypatch.setattr(
        atlas_crosswalk,
        "atlas_implementation_pin",
        lambda: changed_pin,
    )
    changed = build_vocabulary_atlas([release])
    assert changed.generation_digest != original.generation_digest
    assert changed.asserted_graph_iri != original.asserted_graph_iri
    assert changed.canonical_nquads() != original.canonical_nquads()


def test_copied_static_asset_reopens_only_after_full_verification(
    tmp_path: Path,
) -> None:
    asset = build_vocabulary_atlas([_release("source", "Statistics")])
    asset.write_to(tmp_path)
    manifest_payload = (tmp_path / "atlas-manifest.json").read_bytes()
    reopened = VocabularyAtlasAsset.open(
        tmp_path,
        expected_manifest_digest=sha256_bytes(manifest_payload),
    )
    assert reopened.canonical_nquads() == asset.canonical_nquads()
    assert VocabularyAtlasQueries(reopened).label_clusters() == ()


def test_static_asset_reload_rejects_data_and_manifest_tampering(
    tmp_path: Path,
) -> None:
    asset = build_vocabulary_atlas([_release("source", "Statistics")])
    paths = asset.write_to(tmp_path)
    manifest_payload = paths["atlas-manifest.json"].read_bytes()
    manifest_digest = sha256_bytes(manifest_payload)

    paths["atlas.nq"].write_bytes(asset.canonical_nquads() + b"\n")
    with pytest.raises(VocabularyAtlasError, match="byte length differs"):
        VocabularyAtlasAsset.open(
            tmp_path,
            expected_manifest_digest=manifest_digest,
        )

    paths["atlas.nq"].write_bytes(asset.canonical_nquads())
    changed_manifest = asset.manifest()
    changed_manifest["graphs"]["asserted"]["tripleCount"] += 1
    changed_manifest_payload = canonical_json_bytes(changed_manifest) + b"\n"
    paths["atlas-manifest.json"].write_bytes(changed_manifest_payload)
    with pytest.raises(VocabularyAtlasError, match="triple count differs"):
        VocabularyAtlasAsset.open(
            tmp_path,
            expected_manifest_digest=sha256_bytes(changed_manifest_payload),
        )


def test_static_asset_reload_rejects_noncanonical_nquads(tmp_path: Path) -> None:
    asset = build_vocabulary_atlas([_release("source", "Statistics")])
    paths = asset.write_to(tmp_path)
    reordered = b"\n".join(reversed(asset.canonical_nquads().splitlines())) + b"\n"
    paths["atlas.nq"].write_bytes(reordered)
    changed_manifest = asset.manifest()
    changed_manifest["output"]["byteLength"] = len(reordered)
    changed_manifest["output"]["sha256"] = sha256_bytes(reordered)
    manifest_payload = canonical_json_bytes(changed_manifest) + b"\n"
    paths["atlas-manifest.json"].write_bytes(manifest_payload)
    with pytest.raises(VocabularyAtlasError, match="not canonical"):
        VocabularyAtlasAsset.open(
            tmp_path,
            expected_manifest_digest=sha256_bytes(manifest_payload),
        )


def test_static_asset_reload_recomputes_counts_and_release_pins(tmp_path: Path) -> None:
    asset = build_vocabulary_atlas([_release("source", "Statistics")])
    paths = asset.write_to(tmp_path)

    changed_counts = asset.manifest()
    changed_counts["counts"]["concepts"] += 1
    manifest_payload = canonical_json_bytes(changed_counts) + b"\n"
    paths["atlas-manifest.json"].write_bytes(manifest_payload)
    with pytest.raises(VocabularyAtlasError, match="declared counts differ"):
        VocabularyAtlasAsset.open(
            tmp_path,
            expected_manifest_digest=sha256_bytes(manifest_payload),
        )

    changed_pin = asset.manifest()
    changed_pin["inputs"][0]["releaseDigest"] = "sha256:" + "0" * 64
    manifest_payload = canonical_json_bytes(changed_pin) + b"\n"
    paths["atlas-manifest.json"].write_bytes(manifest_payload)
    with pytest.raises(VocabularyAtlasError, match="release input pin differs"):
        VocabularyAtlasAsset.open(
            tmp_path,
            expected_manifest_digest=sha256_bytes(manifest_payload),
        )


def test_cli_builds_the_two_static_files(tmp_path: Path, capsys) -> None:
    release = _release("source", "Statistics")
    release_path = tmp_path / "release.json"
    payload = canonical_json_bytes(release.record())
    release_path.write_bytes(payload)
    output = tmp_path / "atlas"
    assert (
        atlas_main(
            [
                "--release",
                f"{release_path}={sha256_bytes(payload)}",
                "--output-directory",
                str(output),
            ]
        )
        == 0
    )
    receipt = capsys.readouterr().out
    assert '"generationDigest"' in receipt
    assert (output / "atlas.nq").is_file()
    assert (output / "atlas-manifest.json").is_file()


def test_checked_atlas_fixture_matches_a_fresh_build() -> None:
    payload = CURRENT_RELEASE.read_bytes()
    release = VerifiedVocabularyRelease.open(
        CURRENT_RELEASE,
        expected_file_digest=sha256_bytes(payload),
    )
    asset = build_vocabulary_atlas([release])
    assert (ATLAS_FIXTURE / "atlas.nq").read_bytes() == asset.canonical_nquads()
    assert (ATLAS_FIXTURE / "atlas-manifest.json").read_bytes() == (
        canonical_json_bytes(asset.manifest()) + b"\n"
    )
