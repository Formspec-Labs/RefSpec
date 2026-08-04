"""Atlas 2.0 projections are closed ring or subject-module record views."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
import test_relation_assertion_bundle as relation_fixtures
from jsonschema import Draft202012Validator
from rdflib import Dataset, URIRef

from refspec import binding
from refspec.atlas.atlas_scope import AtlasScopeRelease
from refspec.atlas.machine_evidence import (
    build_machine_evidence_from_crosswalk_proof,
)
from refspec.atlas.model import (
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    _atlas_record_identifier,
    _canonical_bytes,
    _CanonicalRecordSet,
    _decode_record_dataset,
    _digest_bytes,
    _plain,
    _record_dataset,
    _snapshot_release_records,
)
from refspec.atlas.projection import (
    MANIFEST_TYPE,
    VocabularyAtlasProjection,
    build_atlas_projection,
    distribution_kind,
    module_projection_policy,
    ring_projection_policy,
)
from refspec.atlas.relation_assertion import RelationAssertionBundle
from refspec.atlas.release_snapshot import AtlasReleaseSnapshot

ASSERTED_AT = "2026-08-04T19:00:00Z"
_SCHEMA_PATH = (
    Path(__file__).parents[1]
    / "bindings"
    / "atlas"
    / "2.0"
    / "schemas"
    / "vocabulary-atlas-projection-manifest.schema.json"
)


def _index_row(
    snapshot: AtlasReleaseSnapshot,
    *,
    source_module: str,
    participation: str | None,
) -> dict[str, Any]:
    basis: dict[str, Any] = {
        "assignmentRole": "https://rulespec.org/ns/v1#assignmentContextual",
        "atlasParticipation": participation,
        "facet": (
            "urn:ref:facet:specialist-subject"
            if participation == "specialist"
            else "urn:ref:facet:general-subject"
            if snapshot.semantic_ring == "subject"
            else "urn:ref:facet:entity"
        ),
        "intendedUses": ["mappingReference"],
        "planningStatus": "planned",
        "readinessEvidence": [],
        "release": {
            "evidencePath": "research/evidence/projection-fixture.json",
            "evidenceSha256": "sha256:" + "9" * 64,
            "manifestDigest": snapshot.release_pin["manifestDigest"],
            "releaseId": snapshot.release_id,
        },
        "resourceId": source_module.rsplit(".", 1)[-1],
        "semanticRing": snapshot.semantic_ring,
        "sourceModule": source_module,
    }
    digest = binding.canonical_sha256(basis)
    published = {key: value for key, value in basis.items() if not (key == "atlasParticipation" and value is None)}
    return {
        **published,
        "rowDigest": digest,
        "rowId": "urn:ref:atlas-index-row:" + digest.removeprefix("sha256:"),
    }


def _add_release(
    records: _CanonicalRecordSet,
    snapshot: AtlasReleaseSnapshot,
    *,
    source_module: str,
    participation: str | None,
) -> None:
    records.add(snapshot.as_record(), role="conceptRelease")
    for concept in snapshot.concept_records:
        records.add(concept, role="concept", in_release=snapshot.release_id)
    for row in _snapshot_release_records(snapshot):
        records.add(row, role="releaseRecord", in_release=snapshot.release_id)
    records.add(
        _index_row(
            snapshot,
            source_module=source_module,
            participation=participation,
        ),
        role="releaseRecord",
        in_release=snapshot.release_id,
    )


def _add_relation(
    records: _CanonicalRecordSet,
    bundle: RelationAssertionBundle,
) -> None:
    records.add(bundle.as_record(), role="relationBundle")
    for evidence in bundle.evidence_assertions:
        records.add(
            evidence.as_record(),
            role="evidenceAssertion",
            in_relation_bundle=bundle.identifier,
        )
    for mapping in bundle.mapping_assertions:
        records.add(
            mapping.as_record(),
            role="mappingAssertion",
            in_relation_bundle=bundle.identifier,
        )
    for proof in bundle.machine_proof_pins:
        records.add(
            proof,
            role="machineProof",
            in_relation_bundle=bundle.identifier,
        )


def _asset_from_records(
    records: _CanonicalRecordSet,
    *,
    suffix: str = "1",
) -> VocabularyAtlasAsset:
    asset_id = "urn:ref:vocabulary-atlas:" + suffix * 64
    payload, _ = _record_dataset(records.values(), asset_id=asset_id)
    return VocabularyAtlasAsset._verified(
        payload=payload,
        scope_payload=b'{"fixture":"projection-parent"}\n',
        manifest={"id": asset_id},
    )


def _parent(
    tmp_path: Path,
    *,
    suffix: str = "1",
) -> tuple[VocabularyAtlasAsset, dict[str, Any]]:
    core, core_release, core_concept = relation_fixtures._source_release(
        tmp_path,
        "projection-core",
    )
    specialist_a, a_release, a_concept = relation_fixtures._source_release(
        tmp_path,
        "projection-specialist-a",
    )
    specialist_b, b_release, b_concept = relation_fixtures._source_release(
        tmp_path,
        "projection-specialist-b",
    )
    entity, entity_release, entity_concept = relation_fixtures._source_release(
        tmp_path,
        "projection-entity",
        ring="entity",
    )

    releases = (
        (
            core,
            "refspec.registry.projection_core",
            "core",
        ),
        (
            specialist_a,
            "refspec.registry.projection_specialist_a",
            "specialist",
        ),
        (
            specialist_b,
            "refspec.registry.projection_specialist_b",
            "specialist",
        ),
        (
            entity,
            "refspec.registry.projection_entity",
            None,
        ),
    )
    records = _CanonicalRecordSet()
    for release, source_module, participation in releases:
        _add_release(
            records,
            AtlasReleaseSnapshot.create(AtlasScopeRelease(release)),
            source_module=source_module,
            participation=participation,
        )

    draft_evidence = relation_fixtures._human_evidence("projection-machine-draft")
    draft_mapping = relation_fixtures._mapping(
        source_concept=core_concept,
        target_concept=a_concept,
        source_release=core_release,
        target_release=a_release,
        evidence=(draft_evidence.identifier,),
    )
    qualified_proof, _ = relation_fixtures._crosswalk_machine_proofs(
        tmp_path,
        draft_mapping,
    )
    machine_evidence = build_machine_evidence_from_crosswalk_proof(
        qualified_proof,
        asserted_by="https://refspec.org/software/projection-fixture-gate",
        asserted_at=ASSERTED_AT,
    )
    core_a = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(core, specialist_a),
        machine_proof_sources=(qualified_proof,),
        evidence_assertions=(machine_evidence,),
        mapping_assertions=(replace(draft_mapping, evidence=(machine_evidence.identifier,)),),
    )

    core_b_evidence = relation_fixtures._human_evidence("projection-core-b")
    core_b = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(core, specialist_b),
        evidence_assertions=(core_b_evidence,),
        mapping_assertions=(
            relation_fixtures._mapping(
                source_concept=core_concept,
                target_concept=b_concept,
                source_release=core_release,
                target_release=b_release,
                evidence=(core_b_evidence.identifier,),
            ),
        ),
    )

    a_b_evidence = relation_fixtures._human_evidence("projection-a-b")
    a_b = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(specialist_a, specialist_b),
        evidence_assertions=(a_b_evidence,),
        mapping_assertions=(
            relation_fixtures._mapping(
                source_concept=a_concept,
                target_concept=b_concept,
                source_release=a_release,
                target_release=b_release,
                evidence=(a_b_evidence.identifier,),
            ),
        ),
    )
    for bundle in (core_a, core_b, a_b):
        _add_relation(records, bundle)

    return _asset_from_records(records, suffix=suffix), {
        "releases": {
            "core": core_release,
            "specialistA": a_release,
            "specialistB": b_release,
            "entity": entity_release,
        },
        "concepts": {
            "core": core_concept,
            "specialistA": a_concept,
            "specialistB": b_concept,
            "entity": entity_concept,
        },
        "bundles": {
            "coreA": core_a.identifier,
            "coreB": core_b.identifier,
            "aB": a_b.identifier,
        },
    }


def _records(projection: VocabularyAtlasProjection):
    return _decode_record_dataset(
        projection.payload,
        asset_id=cast(str, projection.manifest["id"]),
    )


def _release_ids(projection: VocabularyAtlasProjection) -> set[str]:
    return {
        AtlasReleaseSnapshot.from_record(record.record).release_id
        for record in _records(projection)
        if record.role == "conceptRelease"
    }


def _relation_ids(projection: VocabularyAtlasProjection) -> set[str]:
    return {cast(str, record.record["id"]) for record in _records(projection) if record.role == "relationBundle"}


def test_ring_projection_keeps_one_complete_semantic_ring(tmp_path: Path) -> None:
    parent, facts = _parent(tmp_path)

    projection = build_atlas_projection(
        parent,
        policy=ring_projection_policy("subject"),
    )

    assert _release_ids(projection) == {
        facts["releases"]["core"],
        facts["releases"]["specialistA"],
        facts["releases"]["specialistB"],
    }
    assert _relation_ids(projection) == set(facts["bundles"].values())
    assert facts["concepts"]["entity"] not in projection.payload.decode("utf-8")
    assert _plain(projection.manifest["rings"]) == [
        {
            "semanticRing": "subject",
            "releaseCount": 3,
            "conceptCount": 3,
            "relationBundleCount": 3,
            "mappingAssertionCount": 3,
        },
        {
            "semanticRing": "entity",
            "releaseCount": 0,
            "conceptCount": 0,
            "relationBundleCount": 0,
            "mappingAssertionCount": 0,
        },
        {
            "semanticRing": "value",
            "releaseCount": 0,
            "conceptCount": 0,
            "relationBundleCount": 0,
            "mappingAssertionCount": 0,
        },
        {
            "semanticRing": "legalIdentity",
            "releaseCount": 0,
            "conceptCount": 0,
            "relationBundleCount": 0,
            "mappingAssertionCount": 0,
        },
    ]


def test_module_projection_keeps_core_and_one_specialist_with_closed_proof(
    tmp_path: Path,
) -> None:
    parent, facts = _parent(tmp_path)

    projection = build_atlas_projection(
        parent,
        policy=module_projection_policy("refspec.registry.projection_specialist_a"),
    )

    assert _release_ids(projection) == {
        facts["releases"]["core"],
        facts["releases"]["specialistA"],
    }
    assert _relation_ids(projection) == {facts["bundles"]["coreA"]}
    assert projection.manifest["counts"]["relationBundles"] == 1
    assert projection.manifest["counts"]["mappingAssertions"] == 1
    assert projection.manifest["counts"]["evidenceAssertions"] == 1
    assert projection.manifest["counts"]["machineProofs"] == 1
    assert facts["bundles"]["coreB"] not in projection.payload.decode("utf-8")
    assert facts["bundles"]["aB"] not in projection.payload.decode("utf-8")

    selected_releases = _release_ids(projection)
    for record in _records(projection):
        if record.role == "mappingAssertion":
            assert record.record["sourceRelease"] in selected_releases
            assert record.record["targetRelease"] in selected_releases


def test_module_projection_never_keeps_a_one_ended_mapping(tmp_path: Path) -> None:
    parent, facts = _parent(tmp_path)

    projection = build_atlas_projection(
        parent,
        policy=module_projection_policy("refspec.registry.projection_specialist_b"),
    )

    assert _relation_ids(projection) == {facts["bundles"]["coreB"]}
    assert facts["bundles"]["aB"] not in _relation_ids(projection)
    selected_releases = _release_ids(projection)
    relation_release_ids = {
        cast(str, pin["releaseId"])
        for record in _records(projection)
        if record.role == "relationBundle"
        for pin in cast(list[dict[str, Any]], record.record["releasePins"])
    }
    assert relation_release_ids <= selected_releases


def test_projection_policy_is_stable_and_never_embeds_its_resolution() -> None:
    ring = ring_projection_policy("legalIdentity")
    module = module_projection_policy("refspec.registry.crs_product_topics")

    assert cast(str, ring["id"]).startswith("urn:ref:policy:")
    assert cast(str, module["id"]).startswith("urn:ref:policy:")
    assert ring["selectors"] == {"semanticRing": "legalIdentity"}
    assert module["selectors"] == {"sourceModule": "refspec.registry.crs_product_topics"}
    serialized = json.dumps((ring, module), sort_keys=True)
    assert "releaseId" not in serialized
    assert "sha256:" not in serialized
    assert "output" not in serialized


def test_projection_refuses_operator_supplied_resolved_release_ids(
    tmp_path: Path,
) -> None:
    parent, facts = _parent(tmp_path)
    policy = module_projection_policy("refspec.registry.projection_specialist_a")
    policy["selectors"]["releaseIds"] = [facts["releases"]["specialistA"]]

    with pytest.raises(VocabularyAtlasError, match="selectors differ"):
        build_atlas_projection(parent, policy=policy)


def test_module_policy_must_name_a_subject_specialist_in_the_parent(
    tmp_path: Path,
) -> None:
    parent, _ = _parent(tmp_path)

    with pytest.raises(VocabularyAtlasError, match="subject specialist"):
        build_atlas_projection(
            parent,
            policy=module_projection_policy("refspec.registry.projection_entity"),
        )


def test_projection_round_trips_and_reproduces_from_verified_parent_alone(
    tmp_path: Path,
) -> None:
    parent, _ = _parent(tmp_path)
    projection = build_atlas_projection(
        parent,
        policy=ring_projection_policy("subject"),
    )
    written = projection.write(tmp_path / "projection")

    opened = VocabularyAtlasProjection.open(
        written,
        expected_manifest_digest=projection.manifest_digest,
    )
    reproduced = VocabularyAtlasProjection.reproduce_from_parent(
        written,
        parent=parent,
        expected_manifest_digest=projection.manifest_digest,
    )

    assert opened.payload == reproduced.payload == projection.payload
    assert opened.manifest == reproduced.manifest == projection.manifest
    assert opened.manifest["type"] == MANIFEST_TYPE
    assert distribution_kind(written) == "vocabularyAtlasProjection"


@pytest.mark.parametrize(
    "policy",
    [
        ring_projection_policy("subject"),
        module_projection_policy("refspec.registry.projection_specialist_a"),
    ],
)
def test_generated_projection_manifest_validates_against_draft_2020_12(
    tmp_path: Path,
    policy: dict[str, Any],
) -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    parent, _ = _parent(tmp_path)
    projection = build_atlas_projection(parent, policy=policy)

    Draft202012Validator(schema).validate(_plain(projection.manifest))


def test_projection_refuses_another_verified_parent(tmp_path: Path) -> None:
    parent, _ = _parent(tmp_path / "first")
    projection = build_atlas_projection(
        parent,
        policy=ring_projection_policy("subject"),
    )
    written = projection.write(tmp_path / "projection")
    other, _ = _parent(tmp_path / "second", suffix="2")

    with pytest.raises(VocabularyAtlasError, match="another verified parent"):
        VocabularyAtlasProjection.reproduce_from_parent(
            written,
            parent=other,
            expected_manifest_digest=projection.manifest_digest,
        )


def test_file_only_verification_rejects_a_dropped_evidence_record(
    tmp_path: Path,
) -> None:
    parent, _ = _parent(tmp_path)
    projection = build_atlas_projection(
        parent,
        policy=module_projection_policy("refspec.registry.projection_specialist_a"),
    )
    written = projection.write(tmp_path / "projection")
    records = _records(projection)
    evidence_node = next(record.identifier for record in records if record.role == "evidenceAssertion")
    kept_lines = [
        line for line in projection.payload.decode("utf-8").splitlines() if not line.startswith(f"<{evidence_node}> ")
    ]
    payload = ("\n".join(kept_lines) + "\n").encode("utf-8")
    (written / "atlas.nq").write_bytes(payload)

    manifest = cast(
        dict[str, Any],
        json.loads(projection.manifest_bytes().decode("utf-8")),
    )
    dataset = Dataset(default_union=False)
    dataset.parse(data=payload.decode("utf-8"), format="nquads")
    graph_ids = {row["role"]: row["id"] for row in manifest["graphs"]}
    for row in manifest["graphs"]:
        row["quadCount"] = len(dataset.graph(URIRef(row["id"])))
    manifest["output"] = {
        **manifest["output"],
        "digest": _digest_bytes(payload),
        "byteLength": len(payload),
        "quadCount": sum(len(dataset.graph(URIRef(identifier))) for identifier in graph_ids.values()),
    }
    manifest["counts"]["evidenceAssertions"] = 0
    manifest["canonicalPayloadDigest"] = binding.canonical_payload_digest(manifest)
    manifest_payload = _canonical_bytes(manifest)
    (written / "atlas-manifest.json").write_bytes(manifest_payload)

    with pytest.raises(VocabularyAtlasError, match="evidenceAssertion closure"):
        VocabularyAtlasProjection.open(
            written,
            expected_manifest_digest=_digest_bytes(manifest_payload),
        )


def test_projection_of_an_empty_ring_is_refused(tmp_path: Path) -> None:
    parent, _ = _parent(tmp_path)

    with pytest.raises(VocabularyAtlasError, match="selects no release"):
        build_atlas_projection(
            parent,
            policy=ring_projection_policy("value"),
        )


def test_projection_identity_changes_with_parent_and_selector(tmp_path: Path) -> None:
    parent, _ = _parent(tmp_path / "first")
    subject = build_atlas_projection(
        parent,
        policy=ring_projection_policy("subject"),
    )
    entity = build_atlas_projection(
        parent,
        policy=ring_projection_policy("entity"),
    )
    other, _ = _parent(tmp_path / "second", suffix="2")
    other_subject = build_atlas_projection(
        other,
        policy=ring_projection_policy("subject"),
    )

    assert (
        len(
            {
                subject.manifest["id"],
                entity.manifest["id"],
                other_subject.manifest["id"],
            }
        )
        == 3
    )
    assert subject.manifest["id"] != parent.manifest["id"]


def test_projection_records_preserve_parent_record_bytes(tmp_path: Path) -> None:
    parent, _ = _parent(tmp_path)
    projection = build_atlas_projection(
        parent,
        policy=module_projection_policy("refspec.registry.projection_specialist_a"),
    )
    parent_records = {
        record.identifier: record.record
        for record in _decode_record_dataset(
            parent.payload,
            asset_id=cast(str, parent.manifest["id"]),
        )
    }

    for record in _records(projection):
        assert record.identifier == _atlas_record_identifier(record.record)
        assert record.record == parent_records[record.identifier]
