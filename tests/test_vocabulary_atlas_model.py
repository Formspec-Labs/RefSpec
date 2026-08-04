"""Canonical Atlas 2.0 construction from one exact four-ring scope."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from rdflib import Dataset, Literal, URIRef

from refspec.atlas.atlas_scope import (
    AtlasScopeRelease,
    PinnedVocabularyAtlasScope,
    VocabularyAtlasScope,
)
from refspec.atlas.model import (
    ATLAS,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    build_vocabulary_atlas,
)
from refspec.atlas.relation_assertion import (
    PinnedRelationAssertionBundle,
    RelationAssertionBundle,
)
from refspec.registry.infrastructure.artifact_serialization import sha256_digest
from refspec.registry.infrastructure.semantic_foundation import (
    VALUE_EXACT_CROSSWALK,
    EvidenceAssertion,
    MappingAssertion,
)
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseBundle,
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7

_REPO_ROOT = Path(__file__).parents[1]
_SCOPE_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "refspec_test_vocabulary_atlas_model_scope_fixture",
    Path(__file__).with_name("test_atlas_scope.py"),
)
assert _SCOPE_FIXTURE_SPEC is not None and _SCOPE_FIXTURE_SPEC.loader is not None
_SCOPE_FIXTURE = importlib.util.module_from_spec(_SCOPE_FIXTURE_SPEC)
sys.modules[_SCOPE_FIXTURE_SPEC.name] = _SCOPE_FIXTURE
_SCOPE_FIXTURE_SPEC.loader.exec_module(_SCOPE_FIXTURE)

ASSERTED_AT = "2026-08-04T16:00:00Z"


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _pinned_scope(
    tmp_path: Path,
    *,
    name: str,
    releases: tuple[AtlasScopeRelease, ...],
    specs: tuple[Any, ...],
    relations: tuple[PinnedRelationAssertionBundle, ...] = (),
) -> tuple[PinnedVocabularyAtlasScope, dict[str, Any]]:
    index, raw_index, _ = _SCOPE_FIXTURE._pinned_index(tmp_path, name, specs)
    scope = VocabularyAtlasScope.create(
        scope_name=f"urn:ref:test:vocabulary-atlas-model:{name}",
        scope_kind="bench",
        atlas_index=index,
        releases=releases,
        relation_bundles=relations,
    )
    path = scope.write_to(tmp_path / f"{name}-atlas-scope.json")
    return (
        PinnedVocabularyAtlasScope.open(
            path,
            expected_file_digest=_file_digest(path),
            atlas_index=index,
            releases=releases,
            relation_bundles=relations,
        ),
        raw_index,
    )


def _records(
    asset: VocabularyAtlasAsset,
    *,
    role: str,
) -> tuple[tuple[URIRef, dict[str, Any], tuple[str, ...]], ...]:
    dataset = Dataset(default_union=False)
    dataset.parse(data=asset.payload.decode("utf-8"), format="nquads")
    graph_row = next(
        row
        for row in asset.manifest["graphs"]
        if row["role"] == ("releaseFacts" if role in {"conceptRelease", "concept", "releaseRecord"} else "crossRelease")
    )
    graph = dataset.graph(URIRef(cast(str, graph_row["id"])))
    result: list[tuple[URIRef, dict[str, Any], tuple[str, ...]]] = []
    for node in graph.subjects(ATLAS.recordRole, ATLAS[role]):
        literal = graph.value(node, ATLAS.canonicalJson)
        assert isinstance(node, URIRef)
        assert isinstance(literal, Literal)
        containers = tuple(
            sorted(
                str(value)
                for predicate in (ATLAS.inRelease, ATLAS.inRelationBundle)
                for value in graph.objects(node, predicate)
            )
        )
        result.append((node, json.loads(str(literal)), containers))
    return tuple(sorted(result, key=lambda value: str(value[0])))


def test_four_ring_scope_build_is_input_order_independent_and_resolves_index_facts(
    tmp_path: Path,
) -> None:
    values: list[AtlasScopeRelease] = []
    specs: list[Any] = []
    for ring in ("subject", "entity", "value", "legalIdentity"):
        _, source, _ = _SCOPE_FIXTURE._source_release(
            tmp_path,
            ring,
            ring=ring,
        )
        release = AtlasScopeRelease(source)
        values.append(release)
        specs.append(
            _SCOPE_FIXTURE._IndexSpec(
                release,
                ring,
                participation=("core" if ring == "subject" else None),
            )
        )
    releases = tuple(values)
    reverse_root = tmp_path / "reverse"
    forward_root = tmp_path / "forward"
    reverse_root.mkdir()
    forward_root.mkdir()
    pinned, raw_index = _pinned_scope(
        reverse_root,
        name="four-rings",
        releases=tuple(reversed(releases)),
        specs=tuple(specs),
    )
    forward_scope, _ = _pinned_scope(
        forward_root,
        name="four-rings",
        releases=releases,
        specs=tuple(specs),
    )

    reverse = build_vocabulary_atlas(pinned)
    forward = build_vocabulary_atlas(forward_scope)

    assert reverse.scope_payload == forward.scope_payload
    assert reverse.payload == forward.payload
    assert reverse.manifest == forward.manifest
    assert [row["semanticRing"] for row in reverse.manifest["rings"]] == [
        "subject",
        "entity",
        "value",
        "legalIdentity",
    ]
    assert [row["releaseCount"] for row in reverse.manifest["rings"]] == [1, 1, 1, 1]
    assert [row["conceptCount"] for row in reverse.manifest["rings"]] == [1, 1, 1, 1]
    assert reverse.manifest["counts"]["conceptReleases"] == 4
    assert reverse.manifest["counts"]["concepts"] == 4
    assert reverse.manifest["implementation"] == forward.manifest["implementation"]

    published_rows = {
        row["rowId"]: (row, containers)
        for _, row, containers in _records(reverse, role="releaseRecord")
        if "rowId" in row
    }
    expected_rows = {row["rowId"]: row for row in raw_index["rows"]}
    assert {identifier: row for identifier, (row, _) in published_rows.items()} == expected_rows
    assert all(len(containers) == 1 for _, containers in published_rows.values())


def _source_release_version(
    tmp_path: Path,
    *,
    version: str,
    label: str,
) -> SourceConceptReleaseBundle:
    source_id = "https://publisher.example/shared-concept.json"
    scheme_id = "https://publisher.example/schemes/shared"
    local_record_id = "urn:uuid:" + derive_uuid7(
        ASSERTED_AT,
        seed=b"atlas-model-shared-concept",
    )
    observation = {
        "id": f"urn:ref:test:atlas-model:observation:{version}",
        "sourceArtifact": source_id,
        "sourcePath": "terms/shared",
        "sourceOrdinal": 0,
        "labels": [{"value": label, "language": "en", "role": "preferred"}],
        "identifiers": [],
        "uses": ["mappingReference"],
        "conceptIdentityClaimed": False,
        "localRecordId": local_record_id,
    }
    payload = f'{{"label":"{label}","version":"{version}"}}\n'.encode()
    capture = build_source_controlled_resource_bundle(
        resource_id=f"atlas-model-shared-{version}",
        title=f"Shared concept {version}",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("mappingReference",),
        captured_at=ASSERTED_AT,
        observations=(observation,),
        source_artifacts={source_id: payload},
        source_scheme={
            "id": scheme_id,
            "code": "shared",
            "label": "Shared scheme",
            "sourceArtifact": source_id,
            "sourceFetchId": derive_uuid7(
                ASSERTED_AT,
                seed=f"atlas-model-shared-fetch:{version}".encode(),
            ),
            "sourceObservedAt": ASSERTED_AT,
        },
    )
    return build_source_concept_release_bundle(
        capture,
        semantic_ring="subject",
        selected_observation_ids=(observation["id"],),
        selection_policy={
            "id": f"urn:ref:test:atlas-model:selection:{version}",
            "type": "explicitObservationSet",
        },
        rights_metadata=(
            {
                "type": "RightsMetadata",
                "rightsStatus": "notStated",
                "sourceArtifact": source_id,
                "sourceDigest": sha256_digest(payload),
            },
        ),
    )


def test_stable_concept_identity_keeps_distinct_release_scoped_records(
    tmp_path: Path,
) -> None:
    releases: list[AtlasScopeRelease] = []
    concept_ids: list[str] = []
    for version, label in (("v1", "Shared label"), ("v2", "Renamed label")):
        bundle = _source_release_version(tmp_path, version=version, label=label)
        root = bundle.write_to(tmp_path / f"shared-{version}")
        source = _SCOPE_FIXTURE.PinnedSourceConceptRelease.open(
            root,
            expected_manifest_digest=bundle.manifest_digest,
        )
        releases.append(AtlasScopeRelease(source))
        concept_ids.append(cast(str, bundle.concepts[0]["id"]))
    assert concept_ids[0] == concept_ids[1]
    pinned, _ = _pinned_scope(
        tmp_path,
        name="shared-identity",
        releases=tuple(releases),
        specs=tuple(_SCOPE_FIXTURE._IndexSpec(release, f"shared-{index}") for index, release in enumerate(releases)),
    )

    asset = build_vocabulary_atlas(pinned)
    records = _records(asset, role="concept")

    assert len(records) == 2
    assert len({str(node) for node, _, _ in records}) == 2
    assert {row["id"] for _, row, _ in records} == {concept_ids[0]}
    assert {row["sourceObservation"] for _, row, _ in records} == {
        "urn:ref:test:atlas-model:observation:v1",
        "urn:ref:test:atlas-model:observation:v2",
    }
    assert all(len(containers) == 1 for _, _, containers in records)


def test_managed_jsonld_member_identity_is_indexed_from_at_id(
    tmp_path: Path,
) -> None:
    source, _ = _SCOPE_FIXTURE._managed_release(tmp_path)
    release = AtlasScopeRelease(source)
    pinned, _ = _pinned_scope(
        tmp_path,
        name="managed-at-id",
        releases=(release,),
        specs=(
            _SCOPE_FIXTURE._IndexSpec(
                release,
                "managed-at-id",
                participation="specialist",
            ),
        ),
    )

    asset = build_vocabulary_atlas(pinned)
    members = _records(asset, role="concept")
    text = asset.payload.decode("utf-8")

    assert members
    for _, member, _ in members:
        member_id = member["@id"]
        assert f"{ATLAS.recordId.n3()} <{member_id}>" in text


def test_value_relation_context_round_trips_and_distribution_reproduces(
    tmp_path: Path,
) -> None:
    _, source, source_concept = _SCOPE_FIXTURE._source_release(
        tmp_path,
        "value-source",
        ring="value",
    )
    _, target, target_concept = _SCOPE_FIXTURE._source_release(
        tmp_path,
        "value-target",
        ring="value",
    )
    source_release = AtlasScopeRelease(source)
    target_release = AtlasScopeRelease(target)
    evidence = EvidenceAssertion(
        semantic_ring="value",
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by="https://refspec.org/actors/value-reviewer",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:atlas-model:value-evidence",),
        review_decision="urn:ref:test:atlas-model:value-review",
    )
    context = {
        "sourceEdition": "2025",
        "targetEdition": "2026",
        "effectiveFrom": "2026-01-01",
        "effectiveThrough": "2026-12-31",
    }
    mapping = MappingAssertion(
        semantic_ring="value",
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source.release_id,
        target_release=target.release_id,
        relation=VALUE_EXACT_CROSSWALK,
        evidence=(evidence.identifier,),
        asserted_at=ASSERTED_AT,
        context=context,
    )
    bundle = RelationAssertionBundle.create(
        semantic_ring="value",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    relation_root = bundle.write_to(tmp_path / "value-relation")
    relation = PinnedRelationAssertionBundle.open(
        relation_root,
        expected_manifest_digest=bundle.manifest_digest,
        release_sources=(source, target),
    )
    pinned, _ = _pinned_scope(
        tmp_path,
        name="value-relation",
        releases=(source_release, target_release),
        specs=(
            _SCOPE_FIXTURE._IndexSpec(source_release, "value-source"),
            _SCOPE_FIXTURE._IndexSpec(target_release, "value-target"),
        ),
        relations=(relation,),
    )

    asset = build_vocabulary_atlas(pinned)
    assert [row for _, row, _ in _records(asset, role="mappingAssertion")] == [mapping.as_record()]
    assert asset.manifest["counts"]["relationBundles"] == 1
    assert asset.manifest["counts"]["evidenceAssertions"] == 1
    assert asset.manifest["counts"]["mappingAssertions"] == 1

    schema = json.loads(
        (_REPO_ROOT / "bindings/atlas/2.0/schemas/vocabulary-atlas-manifest.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(cast(dict[str, Any], json.loads(asset.manifest_bytes())))
    directory = asset.write(tmp_path / "value-atlas")
    reopened = VocabularyAtlasAsset.open(
        directory,
        expected_manifest_digest=asset.manifest_digest,
    )
    reproduced = VocabularyAtlasAsset.reproduce_from_scope(
        directory,
        scope=pinned,
        expected_manifest_digest=asset.manifest_digest,
    )
    assert reopened.payload == reproduced.payload == asset.payload
    assert reopened.scope_payload == reproduced.scope_payload == asset.scope_payload


def test_three_file_distribution_fails_closed_on_output_scope_and_file_set_tampering(
    tmp_path: Path,
) -> None:
    _, source, _ = _SCOPE_FIXTURE._source_release(tmp_path, "tamper")
    release = AtlasScopeRelease(source)
    pinned, _ = _pinned_scope(
        tmp_path,
        name="tamper",
        releases=(release,),
        specs=(_SCOPE_FIXTURE._IndexSpec(release, "tamper"),),
    )
    asset = build_vocabulary_atlas(pinned)
    directory = asset.write(tmp_path / "tamper-atlas")
    assert {path.name for path in directory.iterdir()} == {
        "atlas-manifest.json",
        "atlas-scope.json",
        "atlas.nq",
    }

    atlas_path = directory / "atlas.nq"
    atlas_path.write_bytes(asset.payload + b"\n")
    with pytest.raises(VocabularyAtlasError, match="output digest differs"):
        VocabularyAtlasAsset.open(
            directory,
            expected_manifest_digest=asset.manifest_digest,
        )
    atlas_path.write_bytes(asset.payload)

    scope_path = directory / "atlas-scope.json"
    scope_path.write_bytes(asset.scope_payload + b" ")
    with pytest.raises(VocabularyAtlasError, match="scope file digest differs"):
        VocabularyAtlasAsset.open(
            directory,
            expected_manifest_digest=asset.manifest_digest,
        )
    scope_path.write_bytes(asset.scope_payload)

    (directory / "extra.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(VocabularyAtlasError, match="file set differs"):
        VocabularyAtlasAsset.open(
            directory,
            expected_manifest_digest=asset.manifest_digest,
        )


def test_public_builder_rejects_loose_release_inputs(tmp_path: Path) -> None:
    _, source, _ = _SCOPE_FIXTURE._source_release(tmp_path, "loose")

    with pytest.raises(VocabularyAtlasError, match="PinnedVocabularyAtlasScope"):
        build_vocabulary_atlas(cast(Any, (source,)))
    with pytest.raises(TypeError):
        build_vocabulary_atlas(  # type: ignore[call-arg]
            cast(Any, (source,)),
            rulespec_core=object(),
        )
