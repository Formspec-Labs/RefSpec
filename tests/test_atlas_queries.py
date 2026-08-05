"""Queries read only the canonical Atlas 2.0 record index."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
import test_icpsr_managed_release as icpsr_fixture
import test_relation_assertion_bundle as relation_fixture
import test_vocabulary_atlas_model as model_fixture

from refspec.atlas.atlas_scope import AtlasScopeRelease
from refspec.atlas.machine_evidence import (
    build_machine_evidence_from_crosswalk_proof,
)
from refspec.atlas.model import (
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    build_vocabulary_atlas,
)
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
    monkeypatch: pytest.MonkeyPatch,
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
        (
            "Renamed label",
            next(key for key, values in labels_by_release.items() if "Renamed label" in values),
        )
    ]
    with pytest.raises(VocabularyAtlasError, match="different semantic ring"):
        queries.search_labels(
            "shared",
            semantic_ring="entity",
            release_id=history[0].release_id,
        )

    selected = history[0]

    def unexpected_scan(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("exact concept lookup must not scan all concepts")

    monkeypatch.setattr(VocabularyAtlasQueries, "concepts", unexpected_scan)
    assert (
        queries.concept(
            selected.concept_id,
            release_id=selected.release_id,
        )
        == selected
    )


def test_queries_resolve_source_release_supersession_as_its_own_relation(
    tmp_path: Path,
) -> None:
    prior = model_fixture._source_release_version(
        tmp_path,
        version="lineage-v1",
        label="Prior term",
    )
    current = model_fixture._source_release_version(
        tmp_path,
        version="lineage-v2",
        label="Current term",
        supersedes=(prior,),
    )
    releases: list[AtlasScopeRelease] = []
    for name, bundle in (("prior", prior), ("current", current)):
        root = bundle.write_to(tmp_path / f"query-source-lineage-{name}")
        pinned = model_fixture._SCOPE_FIXTURE.PinnedSourceConceptRelease.open(
            root,
            expected_manifest_digest=bundle.manifest_digest,
        )
        releases.append(AtlasScopeRelease(pinned))
    scope, _ = model_fixture._pinned_scope(
        tmp_path,
        name="query-source-release-supersession",
        releases=tuple(releases),
        specs=tuple(
            model_fixture._SCOPE_FIXTURE._IndexSpec(
                release,
                f"query-source-lineage-{index}",
            )
            for index, release in enumerate(releases)
        ),
    )

    queries = VocabularyAtlasQueries(build_vocabulary_atlas(scope))
    relations = queries.source_release_supersessions()

    assert len(relations) == 1
    relation = relations[0]
    assert relation.superseding_release_id == current.release_id
    assert relation.superseded_release_id == prior.release_id
    assert relation.semantic_ring == "subject"
    assert relation.superseded_release_pin == {
        "releaseId": prior.release_id,
        "semanticRing": prior.semantic_ring,
        "sourceScheme": "https://publisher.example/schemes/shared",
        "manifestDigest": prior.manifest_digest,
        "releaseDigest": prior.release_digest,
        "logicalDigest": prior.logical_digest,
    }
    assert queries.source_release_supersession(relation.relation_id) == relation
    assert queries.source_release_supersessions(
        superseding_release_id=current.release_id,
        superseded_release_id=prior.release_id,
    ) == (relation,)
    assert queries.source_release_supersessions(
        superseding_release_id=prior.release_id
    ) == ()
    canonical = next(
        value
        for value in queries.records(role="releaseRecord")
        if value.native_id == relation.relation_id
    )
    assert canonical.record_id == relation.record_id
    assert canonical.release_ids == (current.release_id,)
    assert canonical.record == relation.record
    with pytest.raises(VocabularyAtlasError, match="no unique"):
        queries.source_release_supersession("urn:ref:test:missing-supersession")


def test_source_release_recut_lineage_relations_coexist_without_identity_collision(
    tmp_path: Path,
) -> None:
    predecessor_p = model_fixture._source_release_version(
        tmp_path,
        version="lineage-recut-p",
        label="Predecessor P",
    )
    predecessor_q = model_fixture._source_release_version(
        tmp_path,
        version="lineage-recut-q",
        label="Predecessor Q",
    )
    successor_p = model_fixture._source_release_version(
        tmp_path,
        version="lineage-recut-successor",
        label="Re-cut successor",
        supersedes=(predecessor_p,),
    )
    successor_pq = model_fixture._source_release_version(
        tmp_path,
        version="lineage-recut-successor",
        label="Re-cut successor",
        supersedes=(predecessor_p, predecessor_q),
    )
    releases: list[AtlasScopeRelease] = []
    for name, bundle in (
        ("p", predecessor_p),
        ("q", predecessor_q),
        ("successor-p", successor_p),
        ("successor-pq", successor_pq),
    ):
        root = bundle.write_to(tmp_path / f"query-lineage-recut-{name}")
        pinned = model_fixture._SCOPE_FIXTURE.PinnedSourceConceptRelease.open(
            root,
            expected_manifest_digest=bundle.manifest_digest,
        )
        releases.append(AtlasScopeRelease(pinned))
    scope, _ = model_fixture._pinned_scope(
        tmp_path,
        name="query-source-lineage-recut",
        releases=tuple(releases),
        specs=tuple(
            model_fixture._SCOPE_FIXTURE._IndexSpec(
                release,
                f"query-source-lineage-recut-{index}",
            )
            for index, release in enumerate(releases)
        ),
    )

    queries = VocabularyAtlasQueries(build_vocabulary_atlas(scope))
    p_only = queries.source_release_supersessions(
        superseding_release_id=successor_p.release_id,
        superseded_release_id=predecessor_p.release_id,
    )
    p_with_q = queries.source_release_supersessions(
        superseding_release_id=successor_pq.release_id,
        superseded_release_id=predecessor_p.release_id,
    )
    successor_pq_relations = queries.source_release_supersessions(
        superseding_release_id=successor_pq.release_id,
    )

    assert len(p_only) == len(p_with_q) == 1
    assert len(successor_pq_relations) == 2
    assert p_only[0].relation_id != p_with_q[0].relation_id
    assert p_only[0].record["successorBasisDigest"] == (
        p_with_q[0].record["successorBasisDigest"]
    )
    assert p_only[0].record["successorLineageDigest"] != (
        p_with_q[0].record["successorLineageDigest"]
    )
    canonical_relation_ids = {
        record.native_id
        for record in queries.records(role="releaseRecord")
        if record.native_id is not None
        and record.native_id.startswith(
            "urn:ref:source-release-supersession:"
        )
    }
    assert canonical_relation_ids == {
        relation.relation_id
        for relation in queries.source_release_supersessions()
    }


def test_native_relation_query_preserves_managed_release_skos_facts(
    tmp_path: Path,
) -> None:
    source, _assignment = model_fixture._SCOPE_FIXTURE._managed_release(tmp_path)
    release = AtlasScopeRelease(source)
    scope, _ = model_fixture._pinned_scope(
        tmp_path,
        name="query-native-relations",
        releases=(release,),
        specs=(
            model_fixture._SCOPE_FIXTURE._IndexSpec(
                release,
                "query-native-relations",
                participation="bridge",
            ),
        ),
    )
    queries = VocabularyAtlasQueries(build_vocabulary_atlas(scope))
    fixture = model_fixture._SCOPE_FIXTURE._FIXTURE_MODULE
    subject_id = cast(str, fixture.MEMBER_ID)
    object_id = cast(str, fixture.ELIGIBILITY_MEMBER_ID)

    relations = queries.native_relations()

    assert len(relations) == 1
    relation = relations[0]
    assert relation.subject_concept == subject_id
    assert relation.predicate_iri == ("http://www.w3.org/2004/02/skos/core#broader")
    assert relation.object_concept == object_id
    assert relation.release_id == source.release_id
    assert relation.semantic_ring == "subject"
    assert (
        relation.source_record_id
        == queries.concept(
            subject_id,
            release_id=source.release_id,
        ).record_id
    )
    assert relation.relation_id.startswith("urn:ref:vocabulary-atlas-native-relation:")
    assert queries.native_relations(concept_id=object_id) == relations
    assert [
        value.concept_id
        for value in queries.native_ancestors(
            subject_id,
            release_id=source.release_id,
        )
    ] == [object_id]
    assert [
        value.concept_id
        for value in queries.native_descendants(
            object_id,
            release_id=source.release_id,
        )
    ] == [subject_id]
    neighborhood = queries.direct_neighborhood(
        subject_id,
        release_id=source.release_id,
    )
    assert neighborhood.concept.concept_id == subject_id
    assert neighborhood.native_relations == relations
    assert neighborhood.mapping_assertions == ()
    assert queries.native_relations(predicate_iri="http://www.w3.org/2004/02/skos/core#related") == ()
    with pytest.raises(VocabularyAtlasError, match="predicate"):
        queries.native_relations(predicate_iri="urn:test:unsupported")


def test_managed_publisher_release_lineage_remains_an_exact_release_record(
    tmp_path: Path,
) -> None:
    prior_release_iri = "https://elsst.cessda.eu/id/5/"
    source, _assignment = model_fixture._SCOPE_FIXTURE._managed_release(
        tmp_path,
        scheme_prior_version=prior_release_iri,
    )
    release = AtlasScopeRelease(source)
    scope, _ = model_fixture._pinned_scope(
        tmp_path,
        name="query-managed-native-release-lineage",
        releases=(release,),
        specs=(
            model_fixture._SCOPE_FIXTURE._IndexSpec(
                release,
                "query-managed-native-release-lineage",
                participation="bridge",
            ),
        ),
    )

    asset = build_vocabulary_atlas(scope)
    queries = VocabularyAtlasQueries(asset)
    scheme_id = cast(
        str,
        model_fixture._SCOPE_FIXTURE._FIXTURE_MODULE.SCHEME_ID,
    )
    scheme_record = next(
        record
        for record in queries.records(role="releaseRecord")
        if record.native_id == scheme_id
    )

    assert scheme_record.release_ids == (source.release_id,)
    assert scheme_record.record["owl:priorVersion"] == prior_release_iri
    snapshot_scheme_record = next(
        record
        for record in queries.release_snapshot(source.release_id).record[
            "selectedReleaseGraph"
        ]["@graph"]
        if record["@id"] == scheme_id
    )
    assert snapshot_scheme_record == scheme_record.record
    assert queries.source_release_supersessions() == ()
    publisher_relations = queries.publisher_release_prior_versions(
        managed_release_id=source.release_id,
        publisher_release_iri=scheme_id,
        prior_version_iri=prior_release_iri,
    )
    assert len(publisher_relations) == 1
    publisher_relation = publisher_relations[0]
    assert publisher_relation.publisher_release_iri == scheme_id
    assert publisher_relation.prior_version_iri == prior_release_iri
    assert publisher_relation.source_record_id == scheme_record.record_id
    assert publisher_relation.source_record_digest == scheme_record.record_digest
    assert publisher_relation.record["predecessorReferenceKind"] == (
        "publisherIriOnly"
    )
    assert "predecessorDigest" not in publisher_relation.record
    assert queries.publisher_release_prior_version(
        publisher_relation.relation_id
    ) == publisher_relation

    root = asset.write(tmp_path / "managed-native-release-lineage-atlas")
    reopened = VocabularyAtlasAsset.open(
        root,
        expected_manifest_digest=asset.manifest_digest,
    )
    reopened_queries = VocabularyAtlasQueries(reopened)
    reopened_record = next(
        record
        for record in reopened_queries.records(role="releaseRecord")
        if record.native_id == scheme_id
    )
    assert reopened_record == scheme_record
    assert reopened_queries.publisher_release_prior_version(
        publisher_relation.relation_id
    ) == publisher_relation


def test_native_relation_query_preserves_icpsr_use_and_used_for_without_hierarchy_inference(
    tmp_path: Path,
) -> None:
    managed = icpsr_fixture._build_fixture()
    manifest_path = managed.write_to(tmp_path / "query-icpsr-managed-release")
    manifest_digest = icpsr_fixture._file_digest(manifest_path)
    release_id = cast(str, managed.manifest["release"]["id"])
    assignment = icpsr_fixture.ManagedReleaseRingAssignment(
        managed_manifest_digest=manifest_digest,
        release_id=release_id,
        semantic_ring="subject",
        assigned_by="urn:test:actor:icpsr-query-reviewer",
        assigned_at=icpsr_fixture.RECORDED_AT,
        evidence=("urn:test:evidence:icpsr-query-native-relations",),
    )
    assignment_path = assignment.write_to(
        tmp_path / "query-icpsr-managed-ring-assignment.json"
    )
    pinned_assignment = icpsr_fixture.PinnedManagedReleaseRingAssignment.open(
        assignment_path,
        expected_file_digest=icpsr_fixture._file_digest(assignment_path),
    )
    source = icpsr_fixture.PinnedIcpsrManagedConceptRelease.open(
        manifest_path,
        expected_manifest_digest=manifest_digest,
        release_id=release_id,
        ring_assignment=pinned_assignment,
    )
    release = AtlasScopeRelease(source)
    scope, _ = model_fixture._pinned_scope(
        tmp_path,
        name="query-icpsr-native-relations",
        releases=(release,),
        specs=(
            model_fixture._SCOPE_FIXTURE._IndexSpec(
                release,
                "query-icpsr-native-relations",
                participation="specialist",
            ),
        ),
    )

    queries = VocabularyAtlasQueries(build_vocabulary_atlas(scope))
    relations = queries.native_relations()

    assert len(relations) == 4
    assert {value.predicate_iri for value in relations} == {
        "http://www.w3.org/2004/02/skos/core#broader",
        "http://www.w3.org/2004/02/skos/core#related",
        icpsr_fixture.ICPSR_USE_PROPERTY_IRI,
        icpsr_fixture.ICPSR_USED_FOR_PROPERTY_IRI,
    }
    for predicate in (
        icpsr_fixture.ICPSR_USE_PROPERTY_IRI,
        icpsr_fixture.ICPSR_USED_FOR_PROPERTY_IRI,
    ):
        selected = queries.native_relations(predicate_iri=predicate)
        assert len(selected) == 1
        assertion = selected[0]
        assert assertion.release_id == release_id
        assert queries.native_ancestors(
            assertion.subject_concept,
            release_id=release_id,
        ) == ()
        assert queries.native_descendants(
            assertion.subject_concept,
            release_id=release_id,
        ) == ()


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
    assert view.effective_lifecycle_status == "current"
    assert view.superseded_by_ids == ()
    assert queries.mapping_assertions(lifecycle_status="current") == result
    assert queries.mapping_assertions(lifecycle_status="superseded") == ()
    with pytest.raises(VocabularyAtlasError, match="current or superseded"):
        queries.mapping_assertions(lifecycle_status=cast(object, "withdrawn"))
    assert queries.mapping_assertion(machine_mapping.identifier) == view
    neighborhood = queries.direct_neighborhood(
        machine_mapping.source_concept,
        release_id=machine_mapping.source_release,
    )
    assert neighborhood.mapping_assertions == result
    assert queries.mapping_assertions(semantic_ring="entity") == ()


def test_mapping_supersession_resolves_across_immutable_relation_bundles(
    tmp_path: Path,
) -> None:
    source, target, evidence, prior = relation_fixture._subject_facts(tmp_path)
    successor = replace(
        prior,
        asserted_at="2026-08-04T16:01:00Z",
        supersedes=(prior.identifier,),
    )
    pinned_relations = []
    for name, mapping in (("prior", prior), ("successor", successor)):
        bundle = RelationAssertionBundle.create(
            semantic_ring="subject",
            release_sources=(source, target),
            evidence_assertions=(evidence,),
            mapping_assertions=(mapping,),
        )
        root = bundle.write_to(tmp_path / f"query-supersession-{name}")
        pinned_relations.append(
            PinnedRelationAssertionBundle.open(
                root,
                expected_manifest_digest=bundle.manifest_digest,
                release_sources=(source, target),
            )
        )
    releases = (AtlasScopeRelease(source), AtlasScopeRelease(target))
    incomplete_scope, _ = model_fixture._pinned_scope(
        tmp_path,
        name="query-supersession-incomplete",
        releases=releases,
        specs=(
            model_fixture._SCOPE_FIXTURE._IndexSpec(releases[0], "query-supersession-source"),
            model_fixture._SCOPE_FIXTURE._IndexSpec(releases[1], "query-supersession-target"),
        ),
        relations=(pinned_relations[1],),
    )
    with pytest.raises(VocabularyAtlasError, match="unknown prior assertions"):
        build_vocabulary_atlas(incomplete_scope)

    scope, _ = model_fixture._pinned_scope(
        tmp_path,
        name="query-supersession",
        releases=releases,
        specs=(
            model_fixture._SCOPE_FIXTURE._IndexSpec(releases[0], "query-supersession-source"),
            model_fixture._SCOPE_FIXTURE._IndexSpec(releases[1], "query-supersession-target"),
        ),
        relations=tuple(pinned_relations),
    )

    queries = VocabularyAtlasQueries(build_vocabulary_atlas(scope))
    prior_view = queries.mapping_assertion(prior.identifier)
    successor_view = queries.mapping_assertion(successor.identifier)

    assert prior_view.effective_lifecycle_status == "superseded"
    assert prior_view.superseded_by_ids == (successor.identifier,)
    assert successor_view.effective_lifecycle_status == "current"
    assert queries.mapping_assertions(lifecycle_status="superseded") == (prior_view,)
    assert queries.mapping_assertions(lifecycle_status="current") == (successor_view,)
