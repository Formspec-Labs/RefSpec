"""Queries read only the canonical Atlas 2.0 record index."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
import test_relation_assertion_bundle as relation_fixture
import test_vocabulary_atlas_model as model_fixture

from refspec.atlas.atlas_scope import AtlasScopeRelease
from refspec.atlas.machine_evidence import (
    build_machine_evidence_from_crosswalk_proof,
)
from refspec.atlas.model import VocabularyAtlasError, build_vocabulary_atlas
from refspec.atlas.projection import build_atlas_projection, ring_projection_policy
from refspec.atlas.queries import VocabularyAtlasQueries
from refspec.atlas.relation_assertion import (
    PinnedRelationAssertionBundle,
    RelationAssertionBundle,
)
from refspec.registry.infrastructure.artifact_serialization import plain_json

ASSERTED_AT = "2026-08-04T16:00:00Z"


def test_queries_expose_four_ring_releases_concepts_and_index_classifications(
    tmp_path: Path,
) -> None:
    releases: list[AtlasScopeRelease] = []
    specs: list[object] = []
    concept_ids: dict[str, str] = {}
    for ring in ("subject", "entity", "value", "legalIdentity"):
        _, source, concept_id = model_fixture._SCOPE_FIXTURE._source_release(
            tmp_path,
            f"query-{ring}",
            ring=ring,
        )
        release = AtlasScopeRelease(source)
        releases.append(release)
        concept_ids[ring] = concept_id
        specs.append(
            model_fixture._SCOPE_FIXTURE._IndexSpec(
                release,
                f"query-{ring}",
                participation=None,
            )
        )
    scope, _ = model_fixture._pinned_scope(
        tmp_path,
        name="query-four-rings",
        releases=tuple(releases),
        specs=tuple(specs),
    )

    asset = build_vocabulary_atlas(scope)
    queries = VocabularyAtlasQueries(asset)

    assert [value.semantic_ring for value in queries.release_snapshots()] == [
        "subject",
        "entity",
        "value",
        "legalIdentity",
    ]
    assert len(queries.records(role="concept")) == 4
    assert {value.semantic_ring: value.concept_id for value in queries.concepts()} == concept_ids
    classifications = queries.index_classifications()
    assert len(classifications) == 4
    assert {value.semantic_ring: value.source_module for value in classifications} == {
        ring: f"refspec.registry.query_{ring}" for ring in concept_ids
    }
    assert all(value.subject_participation is None for value in classifications)

    entity_projection = build_atlas_projection(
        asset,
        policy=ring_projection_policy("entity"),
    )
    projected = VocabularyAtlasQueries(entity_projection)
    assert [value.semantic_ring for value in projected.release_snapshots()] == ["entity"]
    assert [value.concept_id for value in projected.concepts()] == [concept_ids["entity"]]
    assert projected.index_classifications()[0].source_module == ("refspec.registry.query_entity")
    assert projected.mapping_assertions() == ()
    with pytest.raises(VocabularyAtlasError, match="semantic ring"):
        queries.concepts(semantic_ring=cast(object, "topic"))


def test_stable_identity_keeps_release_versions_and_labels_separate(
    tmp_path: Path,
) -> None:
    releases: list[AtlasScopeRelease] = []
    for version, label in (("v1", "Shared label"), ("v2", "Renamed label")):
        bundle = model_fixture._source_release_version(
            tmp_path,
            version=version,
            label=label,
        )
        root = bundle.write_to(tmp_path / f"query-shared-{version}")
        source = model_fixture._SCOPE_FIXTURE.PinnedSourceConceptRelease.open(
            root,
            expected_manifest_digest=bundle.manifest_digest,
        )
        releases.append(AtlasScopeRelease(source))
    scope, _ = model_fixture._pinned_scope(
        tmp_path,
        name="query-shared-identity",
        releases=tuple(releases),
        specs=tuple(
            model_fixture._SCOPE_FIXTURE._IndexSpec(
                release,
                f"query-shared-{position}",
            )
            for position, release in enumerate(releases)
        ),
    )

    queries = VocabularyAtlasQueries(build_vocabulary_atlas(scope))
    history = queries.concept_history(queries.concepts()[0].concept_id)

    assert len(history) == 2
    assert len({value.concept_id for value in history}) == 1
    assert len({value.release_id for value in history}) == 2
    assert len({value.record_id for value in history}) == 2
    labels_by_release = {
        value.release_id: {
            label.value
            for label in queries.concept_labels(
                value.concept_id,
                release_id=value.release_id,
            )
        }
        for value in history
    }
    assert {frozenset(value) for value in labels_by_release.values()} == {
        frozenset({"Shared label"}),
        frozenset({"Renamed label"}),
    }
    renamed = queries.search_labels("renamed", semantic_ring="subject")
    assert [(value.label.value, value.concept.release_id) for value in renamed] == [
        ("Renamed label", next(key for key, values in labels_by_release.items() if "Renamed label" in values))
    ]
    with pytest.raises(VocabularyAtlasError, match="different semantic ring"):
        queries.search_labels(
            "shared",
            semantic_ring="entity",
            release_id=history[0].release_id,
        )


def test_mapping_query_resolves_typed_evidence_and_machine_proof_closure(
    tmp_path: Path,
) -> None:
    source, target, _, mapping = relation_fixture._subject_facts(tmp_path)
    proof, _ = relation_fixture._crosswalk_machine_proofs(tmp_path, mapping)
    evidence = build_machine_evidence_from_crosswalk_proof(
        proof,
        asserted_by="https://refspec.org/software/query-test-gate",
        asserted_at=ASSERTED_AT,
    )
    machine_mapping = replace(mapping, evidence=(evidence.identifier,))
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        machine_proof_sources=(proof,),
        evidence_assertions=(evidence,),
        mapping_assertions=(machine_mapping,),
    )
    relation_root = bundle.write_to(tmp_path / "query-relation-bundle")
    relation = PinnedRelationAssertionBundle.open(
        relation_root,
        expected_manifest_digest=bundle.manifest_digest,
        release_sources=(source, target),
        machine_proof_sources=(proof,),
    )
    releases = (AtlasScopeRelease(source), AtlasScopeRelease(target))
    scope, _ = model_fixture._pinned_scope(
        tmp_path,
        name="query-machine-relation",
        releases=releases,
        specs=(
            model_fixture._SCOPE_FIXTURE._IndexSpec(
                releases[0],
                "query-machine-source",
            ),
            model_fixture._SCOPE_FIXTURE._IndexSpec(
                releases[1],
                "query-machine-target",
            ),
        ),
        relations=(relation,),
    )

    queries = VocabularyAtlasQueries(build_vocabulary_atlas(scope))
    result = queries.mapping_assertions(semantic_ring="subject")

    assert len(result) == 1
    view = result[0]
    assert view.assertion == machine_mapping
    assert [value.assertion for value in view.evidence_assertions] == [evidence]
    assert [plain_json(value.record) for value in view.machine_proofs] == [proof.pin()]
    assert view.candidate_ids == (cast(str, proof.pin()["candidate"]["id"]),)
    assert view.validation_receipt_ids == evidence.validation_receipts
    assert view.external_evidence_ids == (cast(str, proof.pin()["id"]),)
    assert queries.mapping_assertion(machine_mapping.identifier) == view
    assert queries.mapping_assertions(semantic_ring="entity") == ()
