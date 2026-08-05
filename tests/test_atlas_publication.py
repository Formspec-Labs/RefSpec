"""Static publication preserves and authorizes exact Atlas 2.0 bytes."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from typing import Any

import pytest
import test_atlas_publication_decision as decision_fixtures
import test_relation_assertion_bundle as relation_fixtures
import test_vocabulary_atlas_model as model_fixtures

import refspec.atlas.publication as publication_module
from refspec import binding
from refspec.atlas.atlas_scope import (
    AtlasScopeRelease,
    PinnedVocabularyAtlasScope,
    VocabularyAtlasScope,
)
from refspec.atlas.explorer import AtlasExplorerError, render_atlas_explorer
from refspec.atlas.model import ATLAS_FILE, VocabularyAtlasAsset, build_vocabulary_atlas
from refspec.atlas.projection import (
    VocabularyAtlasProjection,
    build_atlas_projection,
    ring_projection_policy,
)
from refspec.atlas.publication import (
    ATLAS_INDEX,
    ATLAS_MANIFEST,
    ATLAS_SCOPE,
    COMPRESSED_ATLAS,
    EXPLORER_DATA,
    EXPLORER_HTML,
    PUBLICATION_DECISION,
    PUBLICATION_MANIFEST,
    AtlasPublication,
    AtlasPublicationError,
    build_explorer_model,
    main,
    publish_vocabulary_atlas,
)
from refspec.atlas.publication_decision import (
    VocabularyAtlasPublicationDecision,
    build_vocabulary_atlas_publication_decision,
)
from refspec.atlas.queries import native_concept_relation_id
from refspec.atlas.relation_assertion import (
    PinnedRelationAssertionBundle,
    RelationAssertionBundle,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.semantic_foundation import (
    ENTITY_RELATED,
    ENTITY_SUCCESSOR,
    LEGAL_AMENDS,
    LEGAL_AUTHORIZES,
    LEGAL_CITES,
    LEGAL_IMPLEMENTS,
    SUBJECT_BROAD_MATCH,
    SUBJECT_EXACT_MATCH,
    SUBJECT_NARROW_MATCH,
    VALUE_BROAD_CROSSWALK,
    VALUE_EXACT_CROSSWALK,
    VALUE_NARROW_CROSSWALK,
    VALUE_REPLACED_BY,
)

DECIDED_AT = "2026-08-04T20:15:00Z"
DECISION_ACTOR = "https://refspec.org/actors/publication-test-reviewer"


def _atlas_result(asset: VocabularyAtlasAsset) -> dict[str, str]:
    return {
        "role": "VocabularyAtlas",
        "id": str(asset.manifest["id"]),
        "manifestDigest": asset.manifest_digest,
        "distributionDigest": asset.output_digest,
    }


def _projection_result(projection: VocabularyAtlasProjection) -> dict[str, Any]:
    return {
        "role": "VocabularyAtlasProjection",
        "id": str(projection.manifest["id"]),
        "manifestDigest": projection.manifest_digest,
        "distributionDigest": projection.output_digest,
        "parent": projection.parent_pin,
    }


def _atlas_decision(
    scope: PinnedVocabularyAtlasScope,
    asset: VocabularyAtlasAsset,
) -> VocabularyAtlasPublicationDecision:
    return build_vocabulary_atlas_publication_decision(
        scope,
        artifact_kind="atlas",
        policies=decision_fixtures._policies(),
        decision_actor=DECISION_ACTOR,
        decided_at=DECIDED_AT,
        result=_atlas_result(asset),
    )


def _projection_decision(
    scope: PinnedVocabularyAtlasScope,
    projection: VocabularyAtlasProjection,
) -> VocabularyAtlasPublicationDecision:
    return build_vocabulary_atlas_publication_decision(
        scope,
        artifact_kind="projection",
        policies=decision_fixtures._verified_projection_policies(projection),
        decision_actor=DECISION_ACTOR,
        decided_at=DECIDED_AT,
        result=_projection_result(projection),
    )


def _canonical_fixture(
    tmp_path: Path,
    *,
    name: str,
) -> tuple[PinnedVocabularyAtlasScope, VocabularyAtlasAsset, VocabularyAtlasPublicationDecision]:
    scope = decision_fixtures._pinned_scope(tmp_path, name=name)
    asset = build_vocabulary_atlas(scope)
    return scope, asset, _atlas_decision(scope, asset)


def _projection_fixture(
    tmp_path: Path,
    *,
    name: str,
) -> tuple[
    PinnedVocabularyAtlasScope,
    VocabularyAtlasAsset,
    VocabularyAtlasProjection,
    VocabularyAtlasPublicationDecision,
]:
    scope, parent, _ = _canonical_fixture(tmp_path, name=name)
    projection = build_atlas_projection(
        parent,
        policy=ring_projection_policy("subject"),
    )
    return scope, parent, projection, _projection_decision(scope, projection)


def _mapped_fixture(
    tmp_path: Path,
    *,
    semantic_ring: str = "subject",
    relation: str = SUBJECT_EXACT_MATCH,
    context: dict[str, str] | None = None,
) -> tuple[PinnedVocabularyAtlasScope, VocabularyAtlasAsset, VocabularyAtlasPublicationDecision, str]:
    source, source_release_id, source_concept = relation_fixtures._source_release(
        tmp_path,
        "publication-source",
        ring=semantic_ring,
    )
    target, target_release_id, target_concept = relation_fixtures._source_release(
        tmp_path,
        "publication-target",
        ring=semantic_ring,
    )
    evidence = relation_fixtures._human_evidence(
        "publication-review",
        ring=semantic_ring,
    )
    mapping = relation_fixtures._mapping(
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release_id,
        target_release=target_release_id,
        relation=relation,
        evidence=(evidence.identifier,),
        ring=semantic_ring,
        context=context,
    )
    bundle = RelationAssertionBundle.create(
        semantic_ring=semantic_ring,  # type: ignore[arg-type]
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    relation_root = bundle.write_to(tmp_path / "publication-relation")
    relation = PinnedRelationAssertionBundle.open(
        relation_root,
        expected_manifest_digest=bundle.manifest_digest,
        release_sources=(source, target),
    )
    source_release = AtlasScopeRelease(source)
    target_release = AtlasScopeRelease(target)
    scope, _ = model_fixtures._pinned_scope(
        tmp_path,
        name="publication-mapping",
        releases=(source_release, target_release),
        specs=(
            model_fixtures._SCOPE_FIXTURE._IndexSpec(
                source_release,
                "publication-source",
                participation="core" if semantic_ring == "subject" else None,
            ),
            model_fixtures._SCOPE_FIXTURE._IndexSpec(
                target_release,
                "publication-target",
                participation=(
                    "specialist" if semantic_ring == "subject" else None
                ),
            ),
        ),
        relations=(relation,),
    )
    asset = build_vocabulary_atlas(scope)
    return scope, asset, _atlas_decision(scope, asset), mapping.relation


def _manifest_digest(directory: Path) -> str:
    return sha256_digest((directory / PUBLICATION_MANIFEST).read_bytes())


def test_canonical_publication_preserves_exact_authoritative_bytes_and_reopens(
    tmp_path: Path,
) -> None:
    _, asset, decision = _canonical_fixture(tmp_path, name="canonical-publication")

    publication = publish_vocabulary_atlas(
        asset,
        tmp_path / "published",
        decision=decision,
        title="Canonical Atlas 2.0",
        max_concepts=12,
    )

    assert {path.name for path in publication.directory.iterdir()} == {
        ATLAS_MANIFEST,
        ATLAS_SCOPE,
        COMPRESSED_ATLAS,
        EXPLORER_DATA,
        EXPLORER_HTML,
        PUBLICATION_DECISION,
        PUBLICATION_MANIFEST,
    }
    assert (publication.directory / ATLAS_MANIFEST).read_bytes() == asset.manifest_bytes()
    assert (publication.directory / ATLAS_SCOPE).read_bytes() == asset.scope_payload
    assert (publication.directory / PUBLICATION_DECISION).read_bytes() == decision.artifact_bytes()
    assert gzip.decompress((publication.directory / COMPRESSED_ATLAS).read_bytes()) == asset.payload
    assert publication.manifest["distribution"] == {
        "kind": "atlas",
        "assetId": asset.manifest["id"],
        "manifestDigest": asset.manifest_digest,
        "distributionDigest": asset.output_digest,
    }

    reopened = AtlasPublication.open(
        publication.directory,
        expected_manifest_digest=publication.manifest_digest,
    )
    assert isinstance(reopened.distribution, VocabularyAtlasAsset)
    assert reopened.distribution.payload == asset.payload
    assert reopened.decision.as_record() == decision.as_record()


def test_indexed_publication_carries_exact_release_controls_and_reopens(
    tmp_path: Path,
) -> None:
    scope, asset, decision, relation = _mapped_fixture(tmp_path)
    atlas_index = scope.verified_scope().atlas_index

    publication = publish_vocabulary_atlas(
        asset,
        tmp_path / "published-with-index",
        decision=decision,
        planning_index=atlas_index,
    )

    assert (publication.directory / ATLAS_INDEX).read_bytes() == atlas_index.path.read_bytes()
    assert publication.manifest["planningIndex"] == atlas_index.pin()
    assert (
        next(row for row in publication.manifest["artifacts"] if row["path"] == ATLAS_INDEX)["fileDigest"]
        == atlas_index.file_digest
    )
    explorer = json.loads((publication.directory / EXPLORER_DATA).read_bytes())
    binding.validate_canonical_value(explorer)
    release_context = explorer["releaseContext"]
    assert release_context["planningIndex"] == atlas_index.pin()
    assert release_context["publicationDecision"] == {
        "id": decision.identifier,
        "recordDigest": decision.record_digest,
        "schemaVersion": decision.record["schemaVersion"],
    }
    assert release_context["sourceApprovals"] == json.loads(decision.artifact_bytes())["sourceApprovals"]
    assert {(row["rowId"], row["rowDigest"], row["disposition"]) for row in release_context["planningRows"]} == {
        (row["rowId"], row["rowDigest"], row["disposition"]) for row in decision.record["rowDispositions"]
    }
    assert explorer["facets"]["mappingPredicates"] == [relation]
    assert explorer["facets"]["evidenceClasses"] == ["humanReviewed"]
    assert explorer["facets"]["sourceModules"]
    assert explorer["facets"]["resourceIds"]
    assert explorer["facets"]["participations"] == ["core", "specialist"]
    html = (publication.directory / EXPLORER_HTML).read_text()
    assert 'id="release-context-section"' in html
    assert 'id="planning-rows"' in html
    assert 'id="index-download"' in html
    assert "data.releaseContext.sourceApprovals" in html
    assert "data.releaseContext.planningRows.filter(planningRowEligible)" in html

    reopened = AtlasPublication.open(
        publication.directory,
        expected_manifest_digest=publication.manifest_digest,
    )
    assert reopened.planning_index == atlas_index.verified_index()


def test_indexed_publication_rejects_a_changed_exact_planning_index(
    tmp_path: Path,
) -> None:
    scope, asset, decision, _ = _mapped_fixture(tmp_path)
    publication = publish_vocabulary_atlas(
        asset,
        tmp_path / "published-with-index",
        decision=decision,
        planning_index=scope.verified_scope().atlas_index,
    )
    trusted_digest = publication.manifest_digest
    index_path = publication.directory / ATLAS_INDEX
    index_path.write_bytes(index_path.read_bytes() + b"\n")

    with pytest.raises(AtlasPublicationError):
        AtlasPublication.open(
            publication.directory,
            expected_manifest_digest=trusted_digest,
        )


def test_indexed_publication_omits_nullable_planning_facts_from_explorer(
    tmp_path: Path,
) -> None:
    _, source, _ = decision_fixtures.scope_fixture._source_release(
        tmp_path,
        "nullable-planning-row",
    )
    release = AtlasScopeRelease(source)
    atlas_index, exact_index, _ = decision_fixtures.scope_fixture._pinned_index(
        tmp_path,
        "nullable-planning-row",
        (
            decision_fixtures.scope_fixture._IndexSpec(
                release,
                "nullable-planning-row",
                participation=None,
            ),
        ),
    )
    assert exact_index["rows"][0]["atlasParticipation"] is None
    scope_value = VocabularyAtlasScope.create(
        scope_name="urn:ref:test:vocabulary-atlas-scope:nullable-planning-row",
        scope_kind="bench",
        atlas_index=atlas_index,
        releases=(release,),
    )
    scope_path = scope_value.write_to(tmp_path / "nullable-scope.json")
    scope = PinnedVocabularyAtlasScope.open(
        scope_path,
        expected_file_digest=sha256_digest(scope_path.read_bytes()),
        atlas_index=atlas_index,
        releases=(release,),
    )
    asset = build_vocabulary_atlas(scope)
    decision = _atlas_decision(scope, asset)

    publication = publish_vocabulary_atlas(
        asset,
        tmp_path / "published-nullable-index",
        decision=decision,
        planning_index=atlas_index,
    )

    explorer = json.loads((publication.directory / EXPLORER_DATA).read_bytes())
    assert "atlasParticipation" not in explorer["releaseContext"]["planningRows"][0]
    binding.validate_canonical_value(explorer)
    assert (
        AtlasPublication.open(
            publication.directory,
            expected_manifest_digest=publication.manifest_digest,
        ).planning_index
        == atlas_index.verified_index()
    )


def test_explorer_rejects_a_decision_for_another_exact_index(
    tmp_path: Path,
) -> None:
    scope, asset, _, _ = _mapped_fixture(tmp_path / "first")
    _, _, other_decision = _canonical_fixture(tmp_path / "second", name="other-index")

    with pytest.raises(AtlasPublicationError, match="planning index differs"):
        build_explorer_model(
            asset,
            planning_index=scope.verified_scope().atlas_index,
            decision=other_decision,
        )


def test_projection_publication_requires_parent_and_carries_no_canonical_scope(
    tmp_path: Path,
) -> None:
    _, parent, projection, decision = _projection_fixture(
        tmp_path,
        name="projection-publication",
    )

    with pytest.raises(AtlasPublicationError, match="requires its verified atlas parent"):
        publish_vocabulary_atlas(
            projection,
            tmp_path / "missing-parent",
            decision=decision,
        )

    publication = publish_vocabulary_atlas(
        projection,
        tmp_path / "published-projection",
        decision=decision,
        parent=parent,
    )

    assert ATLAS_SCOPE not in {path.name for path in publication.directory.iterdir()}
    assert (publication.directory / ATLAS_MANIFEST).read_bytes() == projection.manifest_bytes()
    assert (publication.directory / PUBLICATION_DECISION).read_bytes() == decision.artifact_bytes()
    assert publication.manifest["distribution"]["parent"] == projection.parent_pin
    reopened = AtlasPublication.open(
        publication.directory,
        expected_manifest_digest=publication.manifest_digest,
        parent=parent,
    )
    assert isinstance(reopened.distribution, VocabularyAtlasProjection)
    assert reopened.distribution.parent_pin == projection.parent_pin


def test_projection_publication_refuses_internally_valid_parent_incomplete_projection(
    tmp_path: Path,
) -> None:
    scope, parent, _, _ = _mapped_fixture(tmp_path)
    complete = build_atlas_projection(
        parent,
        policy=ring_projection_policy("subject"),
    )
    manifest = json.loads(complete.manifest_bytes())
    cross_graph = next(row for row in manifest["graphs"] if row["role"] == "crossRelease")
    cross_graph_suffix = f" <{cross_graph['id']}> .\n".encode()
    payload = b"".join(
        line for line in complete.payload.splitlines(keepends=True) if not line.endswith(cross_graph_suffix)
    )
    assert payload != complete.payload
    cross_graph["quadCount"] = 0
    for field in ("relationBundles", "evidenceAssertions", "mappingAssertions", "machineProofs"):
        manifest["counts"][field] = 0
    for ring in manifest["rings"]:
        ring["relationBundleCount"] = 0
        ring["mappingAssertionCount"] = 0
    release_quad_count = next(row["quadCount"] for row in manifest["graphs"] if row["role"] == "releaseFacts")
    manifest["output"].update(
        {
            "digest": sha256_digest(payload),
            "byteLength": len(payload),
            "quadCount": release_quad_count,
        }
    )
    manifest["canonicalPayloadDigest"] = binding.canonical_payload_digest(manifest)
    manifest_bytes = canonical_json_bytes(manifest)
    incomplete_root = tmp_path / "internally-valid-incomplete-projection"
    incomplete_root.mkdir()
    (incomplete_root / ATLAS_FILE).write_bytes(payload)
    (incomplete_root / ATLAS_MANIFEST).write_bytes(manifest_bytes)
    incomplete = VocabularyAtlasProjection.open(
        incomplete_root,
        expected_manifest_digest=sha256_digest(manifest_bytes),
    )
    decision = _projection_decision(scope, incomplete)
    target = tmp_path / "nonreproducing-projection"

    with pytest.raises(AtlasPublicationError, match="does not reproduce from its verified parent"):
        publish_vocabulary_atlas(
            incomplete,
            target,
            decision=decision,
            parent=parent,
        )

    assert not target.exists()


def test_projection_publication_refuses_another_parent_or_decision_kind(
    tmp_path: Path,
) -> None:
    _, parent, projection, decision = _projection_fixture(
        tmp_path / "first",
        name="projection-gates",
    )
    _, other_parent, _ = _canonical_fixture(
        tmp_path / "other",
        name="other-parent",
    )
    atlas_decision = _atlas_decision(
        decision_fixtures._pinned_scope(tmp_path / "atlas-decision", name="atlas-decision"),
        other_parent,
    )

    with pytest.raises(AtlasPublicationError, match="parent pin differs"):
        publish_vocabulary_atlas(
            projection,
            tmp_path / "wrong-parent",
            decision=decision,
            parent=other_parent,
        )
    with pytest.raises(AtlasPublicationError, match="cannot validate a projection"):
        publish_vocabulary_atlas(
            projection,
            tmp_path / "wrong-decision",
            decision=atlas_decision,
            parent=parent,
        )


def test_publication_is_byte_deterministic(
    tmp_path: Path,
) -> None:
    _, asset, decision = _canonical_fixture(tmp_path, name="deterministic-publication")
    first = publish_vocabulary_atlas(
        asset,
        tmp_path / "first",
        decision=decision,
        title="Deterministic Atlas",
        max_concepts=7,
        max_mapping_assertions=3,
    )
    second = publish_vocabulary_atlas(
        asset,
        tmp_path / "second",
        decision=decision,
        title="Deterministic Atlas",
        max_concepts=7,
        max_mapping_assertions=3,
    )

    assert {path.name for path in first.directory.iterdir()} == {path.name for path in second.directory.iterdir()}
    assert {path.name: path.read_bytes() for path in first.directory.iterdir()} == {
        path.name: path.read_bytes() for path in second.directory.iterdir()
    }


@pytest.mark.parametrize(
    "filename",
    [
        ATLAS_MANIFEST,
        ATLAS_SCOPE,
        COMPRESSED_ATLAS,
        PUBLICATION_DECISION,
        EXPLORER_DATA,
        EXPLORER_HTML,
        PUBLICATION_MANIFEST,
    ],
)
def test_file_only_open_rejects_every_tampered_material_file(
    tmp_path: Path,
    filename: str,
) -> None:
    _, asset, decision = _canonical_fixture(tmp_path, name=f"tamper-{filename.replace('.', '-')}")
    publication = publish_vocabulary_atlas(
        asset,
        tmp_path / "published",
        decision=decision,
    )
    digest = publication.manifest_digest
    target = publication.directory / filename
    target.write_bytes(target.read_bytes() + b"tampered")

    with pytest.raises(AtlasPublicationError):
        AtlasPublication.open(
            publication.directory,
            expected_manifest_digest=digest,
        )


def test_publication_type_cannot_be_constructed_without_file_verification(
    tmp_path: Path,
) -> None:
    _, asset, decision = _canonical_fixture(tmp_path, name="verified-construction")

    with pytest.raises(TypeError, match=r"must come from AtlasPublication\.open"):
        AtlasPublication(tmp_path, {}, asset, decision)


def test_open_uses_no_follow_descriptor_when_file_becomes_a_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, asset, decision = _canonical_fixture(tmp_path, name="no-follow-race")
    publication = publish_vocabulary_atlas(
        asset,
        tmp_path / "published",
        decision=decision,
    )
    digest = publication.manifest_digest
    target = publication.directory / ATLAS_MANIFEST
    replacement = tmp_path / "replacement-manifest.json"
    replacement.write_bytes(target.read_bytes())
    real_open = os.open
    swapped = False

    def swap_then_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == ATLAS_MANIFEST and dir_fd is not None and not swapped:
            swapped = True
            target.unlink()
            target.symlink_to(replacement)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(publication_module.os, "open", swap_then_open)

    with pytest.raises(AtlasPublicationError, match="regular files and no symlinks"):
        AtlasPublication.open(
            publication.directory,
            expected_manifest_digest=digest,
        )


def test_explorer_uses_generic_typed_mapping_queries_and_stays_bounded(
    tmp_path: Path,
) -> None:
    _, asset, _, relation = _mapped_fixture(tmp_path)

    model = build_explorer_model(
        asset,
        title="Typed Atlas",
        max_concepts=2,
        max_mapping_assertions=1,
    )

    assert {concept["label"] for concept in model["concepts"]} == {
        "Publication-Source",
        "Publication-Target",
    }
    assert {concept["semanticRing"] for concept in model["concepts"]} == {"subject"}
    assert model["nativeRelations"] == []
    assert len(model["mappingAssertions"]) == 1
    mapping = model["mappingAssertions"][0]
    assert mapping["semanticRing"] == "subject"
    assert mapping["relation"] == relation
    assert mapping["evidenceClasses"] == ["humanReviewed"]
    assert mapping["lifecycleStatus"] == "current"
    assert mapping["effectiveLifecycleStatus"] == "current"
    assert mapping["supersedes"] == []
    assert mapping["supersededBy"] == []
    assert model["facets"]["mappingLifecycleStatuses"] == ["current"]
    assert model["summary"] == {
        "shownConceptCount": 2,
        "shownNativeRelationCount": 0,
        "shownMappingAssertionCount": 1,
        "availableConceptCount": 2,
        "availableNativeRelationCount": 0,
        "availableMappingAssertionCount": 1,
        "truncated": False,
    }

    bounded = build_explorer_model(
        asset,
        max_concepts=1,
        max_mapping_assertions=1,
    )
    assert len(bounded["concepts"]) == 1
    assert bounded["mappingAssertions"] == []
    assert bounded["summary"]["truncated"] is True


def test_explorer_defaults_to_a_complete_searchable_index(
    tmp_path: Path,
) -> None:
    _, asset, _, _ = _mapped_fixture(tmp_path)

    model = build_explorer_model(asset, title="Complete searchable Atlas")

    assert model["summary"] == {
        "shownConceptCount": 2,
        "shownNativeRelationCount": 0,
        "shownMappingAssertionCount": 1,
        "availableConceptCount": 2,
        "availableNativeRelationCount": 0,
        "availableMappingAssertionCount": 1,
        "truncated": False,
    }
    assert model["selectionPolicy"]["maxConcepts"] == 2
    assert model["selectionPolicy"]["maxMappingAssertions"] == 1
    assert all(concept["label"] in concept["searchLabels"] for concept in model["concepts"])
    assert model["releaseContext"] == {
        "sourceApprovals": [],
        "planningRows": [],
    }
    binding.validate_canonical_value(model)

    rendered = render_atlas_explorer(model)
    assert "Semantic rings" in rendered
    assert "Ring filters apply to concepts" in rendered
    assert "Label, alias, notation, or identifier" in rendered
    assert 'id="search-ring"' in rendered
    assert 'const defaultSearchRing = "subject";' in rendered
    assert "document.concept.semanticRing === semanticRing" in rendered
    assert "rankSearchDocuments(" in rendered
    assert 'id="mapping-filters"' in rendered
    assert "Mapping lifecycle" in rendered
    assert "mapping.effectiveLifecycleStatus" in rendered
    assert 'id="concept-facet-filters"' in rendered
    assert 'id="mapping-facet-filters"' in rendered
    assert "conceptEligibleForState(concept, state, conceptByViewId)" in rendered
    assert "mappingAssertionEligibleForState(mapping, state, conceptByViewId)" in rendered
    assert "nativeRelationEligibleForState(relation, state, conceptByViewId)" in rendered
    assert '"rowField":"evidenceClasses"' in rendered
    assert '"statePath":"activeEvidenceClass"' in rendered
    assert 'id="node-ancestor-count"' in rendered
    assert 'id="node-descendant-count"' in rendered
    assert "hierarchyClosure(concept.viewId, hierarchyParents)" in rendered
    assert "directed broad and narrow cross-release mappings" in rendered
    assert 'hierarchyParents.get(mapping.sourceViewId).push({ kind: "mapping"' in rendered
    assert 'hierarchyChildren.get(mapping.sourceViewId).push({ kind: "mapping"' in rendered
    assert 'hierarchyParents.get(mapping.targetViewId).push({ kind: "mapping"' in rendered
    assert "an inferred multi-hop route remains distinct from a direct assertion" in rendered
    assert 'id="render-limit-range"' in rendered
    assert 'id="render-limit-number"' in rendered
    assert "Maximum rendered concepts" in rendered
    assert "rendered.size < state.renderLimit" in rendered
    assert "Math.min(renderCapacity, parsed)" in rendered
    assert "groupInspectorLinks(links)" in rendered
    assert "equivalent source assertion" in rendered
    assert "nativeRelationFromSelected" in rendered
    assert "unrelated lines dim to graphite without hiding the current graph" in rendered
    assert 'const subduedEdgeColor = "#24302c";' in rendered
    assert "subdued ? subduedEdgeColor" in rendered
    assert "if (selected && isConceptEligible(selected)) add(selected.viewId);" in rendered
    assert "if (viewId === state.selected) return;" in rendered
    assert "if (selected && isConceptVisible(selected)) drawConcept(selected);" in rendered
    assert '"statePath":"activeRings"' in rendered
    assert "Possible preferred-label spelling match" in rendered


@pytest.mark.parametrize(
    ("semantic_ring", "relation", "context"),
    (
        ("subject", SUBJECT_BROAD_MATCH, None),
        ("subject", SUBJECT_NARROW_MATCH, None),
        ("entity", ENTITY_SUCCESSOR, None),
        (
            "value",
            VALUE_BROAD_CROSSWALK,
            {
                "sourceEdition": "2025",
                "targetEdition": "2026",
                "effectiveFrom": "2026-01-01",
            },
        ),
        (
            "value",
            VALUE_NARROW_CROSSWALK,
            {
                "sourceEdition": "2025",
                "targetEdition": "2026",
                "effectiveFrom": "2026-01-01",
            },
        ),
        (
            "value",
            VALUE_REPLACED_BY,
            {
                "sourceEdition": "2025",
                "targetEdition": "2026",
                "effectiveFrom": "2026-01-01",
            },
        ),
        ("legalIdentity", LEGAL_CITES, {"effectiveAt": "2026-08-04"}),
        ("legalIdentity", LEGAL_AMENDS, {"effectiveAt": "2026-08-04"}),
        ("legalIdentity", LEGAL_AUTHORIZES, {"effectiveAt": "2026-08-04"}),
        ("legalIdentity", LEGAL_IMPLEMENTS, {"effectiveAt": "2026-08-04"}),
    ),
)
def test_explorer_render_exposes_every_directional_mapping_with_valid_identity(
    tmp_path: Path,
    semantic_ring: str,
    relation: str,
    context: dict[str, str] | None,
) -> None:
    _, asset, _, _ = _mapped_fixture(
        tmp_path,
        semantic_ring=semantic_ring,
        relation=relation,
        context=context,
    )
    model = json.loads(json.dumps(build_explorer_model(asset)))
    mapping = model["mappingAssertions"][0]
    mapping["externalEvidence"] = ["https://example.test/evidence/source-record"]
    mapping["candidateIds"] = ["urn:ref:test:candidate:directed-mapping"]
    mapping["validationReceiptIds"] = ["urn:ref:test:receipt:blind-judge"]
    mapping["machineProofs"] = ["urn:ref:test:proof:crosswalk-v2"]

    rendered = render_atlas_explorer(model)

    assert mapping["relation"] == relation
    assert mapping["semanticRing"] == semantic_ring
    assert mapping["id"] in rendered
    assert "return `—${mapping.relationLabel}→`" in rendered
    assert "return `↔ ${mapping.relationLabel} ↔`" in rendered
    assert "directionalMappingRelations.has(mapping.relation)" in rendered
    assert 'mappingRelationKind(mapping).startsWith("directed")' in rendered
    assert "roleLabel.textContent = `${role} endpoint — `;" in rendered
    assert "directed source → target" in rendered
    assert "Evidence and proof references" in rendered
    assert "Direct evidence assertions" in rendered
    assert "Complete evidence closure" in rendered
    assert "View references in explorer data" in rendered
    assert "Download canonical Atlas evidence" in rendered
    assert "https://example.test/evidence/source-record" in rendered
    assert "urn:ref:test:receipt:blind-judge" in rendered
    assert "urn:ref:test:proof:crosswalk-v2" in rendered
    assert "inferred ${direction} route" in rendered
    assert 'Inspect ${formatQuantity(path.length, "direct assertion")}' in rendered


def test_explorer_hierarchy_closure_uses_only_true_broad_and_narrow_mappings(
    tmp_path: Path,
) -> None:
    _, asset, _, _ = _mapped_fixture(
        tmp_path,
        semantic_ring="entity",
        relation=ENTITY_SUCCESSOR,
    )

    rendered = render_atlas_explorer(build_explorer_model(asset))
    hierarchy_setup = rendered.split("const hierarchyParents", 1)[1].split(
        "function normalizeSearch", 1
    )[0]

    assert "broaderMappingRelations.has(mapping.relation)" in hierarchy_setup
    assert "narrowerMappingRelations.has(mapping.relation)" in hierarchy_setup
    assert "directionalMappingRelations.has(mapping.relation)" not in hierarchy_setup


def test_explorer_search_ring_default_uses_the_first_populated_ring(tmp_path: Path) -> None:
    model = _explorer_model_for_ring(
        tmp_path,
        semantic_ring="entity",
        relation=ENTITY_RELATED,
        context=None,
    )

    rendered = render_atlas_explorer(model)

    assert 'const defaultSearchRing = "entity";' in rendered
    assert "document.concept.semanticRing === semanticRing" in rendered
    assert "rankSearchDocuments(" in rendered


def test_renderer_rejects_noncanonical_search_labels(tmp_path: Path) -> None:
    _, asset, _ = _canonical_fixture(tmp_path, name="search-label-order")
    model = json.loads(json.dumps(build_explorer_model(asset)))
    model["concepts"][0]["searchLabels"] = ["zeta", "Alpha"]

    with pytest.raises(AtlasExplorerError, match="searchLabels must use canonical label order"):
        render_atlas_explorer(model)


def test_explorer_preserves_native_relations_separately_from_mappings(
    tmp_path: Path,
) -> None:
    source, _assignment = model_fixtures._SCOPE_FIXTURE._managed_release(tmp_path)
    release = AtlasScopeRelease(source)
    scope, _ = model_fixtures._pinned_scope(
        tmp_path,
        name="explorer-native-relations",
        releases=(release,),
        specs=(
            model_fixtures._SCOPE_FIXTURE._IndexSpec(
                release,
                "explorer-native-relations",
                participation="bridge",
            ),
        ),
    )

    model = build_explorer_model(
        build_vocabulary_atlas(scope),
        max_concepts=2,
    )

    assert model["schemaVersion"] == "4.0"
    assert model["mappingAssertions"] == []
    assert len(model["nativeRelations"]) == 1
    relation = model["nativeRelations"][0]
    assert relation["predicate"] == ("http://www.w3.org/2004/02/skos/core#broader")
    assert relation["predicateLabel"] == "broader"
    assert relation["releaseId"] == source.release_id
    assert {
        relation["subjectViewId"],
        relation["objectViewId"],
    } <= {concept["viewId"] for concept in model["concepts"]}
    assert render_atlas_explorer(model).startswith("<!doctype html>")


def test_explorer_ships_icpsr_use_and_used_for_as_non_hierarchy_predicates(
    tmp_path: Path,
) -> None:
    source, _assignment = model_fixtures._SCOPE_FIXTURE._managed_release(tmp_path)
    release = AtlasScopeRelease(source)
    scope, _ = model_fixtures._pinned_scope(
        tmp_path,
        name="explorer-thesaurus-use-relations",
        releases=(release,),
        specs=(
            model_fixtures._SCOPE_FIXTURE._IndexSpec(
                release,
                "explorer-thesaurus-use-relations",
                participation="bridge",
            ),
        ),
    )
    model = build_explorer_model(build_vocabulary_atlas(scope), max_concepts=2)
    template = model["nativeRelations"][0]
    predicates = {
        "https://refspec.org/ns/vocabulary-atlas/v2#thesaurusUse": "thesaurus use",
        "https://refspec.org/ns/vocabulary-atlas/v2#thesaurusUsedFor": "thesaurus used for",
    }
    for predicate, label in predicates.items():
        relation = {**template, "predicate": predicate, "predicateLabel": label}
        relation["id"] = native_concept_relation_id(
            subject_concept=relation["subjectConcept"],
            predicate_iri=predicate,
            object_concept=relation["objectConcept"],
            release_id=relation["releaseId"],
            source_record_id=relation["sourceRecordId"],
            source_record_digest=relation["sourceRecordDigest"],
        )
        model["nativeRelations"].append(relation)
    model["facets"]["nativePredicates"] = sorted(
        {row["predicate"] for row in model["nativeRelations"]}
    )
    model["summary"]["shownNativeRelationCount"] += 2
    model["summary"]["availableNativeRelationCount"] += 2

    rendered = render_atlas_explorer(model)
    hierarchy_setup = rendered.split("const hierarchyParents", 1)[1].split(
        "function normalizeSearch", 1
    )[0]

    assert all(predicate in rendered for predicate in predicates)
    assert '["thesaurus use", "thesaurus used for"]' in rendered
    assert '["thesaurus used for", "thesaurus use"]' in rendered
    assert "thesaurus use" not in hierarchy_setup
    assert "thesaurus used for" not in hierarchy_setup


def test_renderer_fails_closed_on_non_2_0_view_fields(tmp_path: Path) -> None:
    _, asset, _ = _canonical_fixture(tmp_path, name="closed-explorer-shape")
    model = build_explorer_model(asset)

    old_collections = dict(model)
    old_collections["releases"] = old_collections.pop("conceptReleases")
    with pytest.raises(AtlasExplorerError, match="fields differ from Atlas explorer 4.0"):
        render_atlas_explorer(old_collections)

    unknown_counts = json.loads(json.dumps(model))
    unknown_counts["atlas"]["counts"]["unexpectedCount"] = 1
    with pytest.raises(AtlasExplorerError, match="counts fields differ"):
        render_atlas_explorer(unknown_counts)


def _explorer_model_for_ring(
    tmp_path: Path,
    *,
    semantic_ring: str,
    relation: str,
    context: dict[str, str] | None,
) -> dict[str, Any]:
    _, asset, _, _ = _mapped_fixture(tmp_path)
    model = json.loads(json.dumps(build_explorer_model(asset)))
    for release in model["conceptReleases"]:
        release["semanticRing"] = semantic_ring
    for concept in model["concepts"]:
        concept["semanticRing"] = semantic_ring
    mapping = model["mappingAssertions"][0]
    mapping["semanticRing"] = semantic_ring
    mapping["relation"] = relation
    model["facets"]["mappingPredicates"] = [relation]
    if context is None:
        mapping.pop("context", None)
    else:
        mapping["context"] = context
    return model


@pytest.mark.parametrize(
    ("semantic_ring", "relation", "context"),
    (
        ("subject", SUBJECT_EXACT_MATCH, None),
        ("entity", ENTITY_RELATED, None),
        (
            "value",
            VALUE_EXACT_CROSSWALK,
            {"sourceEdition": "2025", "targetEdition": "2026", "effectiveFrom": "2026-01-01"},
        ),
        ("legalIdentity", LEGAL_CITES, {"effectiveAt": "2026-08-04"}),
    ),
)
def test_renderer_accepts_each_ring_relation_and_context_shape(
    tmp_path: Path,
    semantic_ring: str,
    relation: str,
    context: dict[str, str] | None,
) -> None:
    model = _explorer_model_for_ring(
        tmp_path,
        semantic_ring=semantic_ring,
        relation=relation,
        context=context,
    )

    assert render_atlas_explorer(model).startswith("<!doctype html>")


@pytest.mark.parametrize(
    ("semantic_ring", "foreign_relation"),
    (
        ("subject", ENTITY_RELATED),
        ("entity", VALUE_EXACT_CROSSWALK),
        ("value", LEGAL_CITES),
        ("legalIdentity", SUBJECT_EXACT_MATCH),
    ),
)
def test_renderer_rejects_relations_from_another_ring(
    tmp_path: Path,
    semantic_ring: str,
    foreign_relation: str,
) -> None:
    model = _explorer_model_for_ring(
        tmp_path,
        semantic_ring=semantic_ring,
        relation=foreign_relation,
        context=None,
    )

    with pytest.raises(AtlasExplorerError, match=f"not valid for the {semantic_ring} ring"):
        render_atlas_explorer(model)


@pytest.mark.parametrize(
    ("semantic_ring", "relation", "foreign_context"),
    (
        ("subject", SUBJECT_EXACT_MATCH, {"effectiveAt": "2026-08-04"}),
        (
            "entity",
            ENTITY_RELATED,
            {"sourceEdition": "2025", "targetEdition": "2026", "effectiveFrom": "2026-01-01"},
        ),
        ("value", VALUE_EXACT_CROSSWALK, {"effectiveAt": "2026-08-04"}),
        (
            "legalIdentity",
            LEGAL_CITES,
            {"sourceEdition": "2025", "targetEdition": "2026", "effectiveFrom": "2026-01-01"},
        ),
    ),
)
def test_renderer_rejects_context_from_another_ring(
    tmp_path: Path,
    semantic_ring: str,
    relation: str,
    foreign_context: dict[str, str],
) -> None:
    model = _explorer_model_for_ring(
        tmp_path,
        semantic_ring=semantic_ring,
        relation=relation,
        context=foreign_context,
    )

    with pytest.raises(AtlasExplorerError, match="violates ring relation semantics"):
        render_atlas_explorer(model)


def test_explorer_html_is_exact_and_script_safe(
    tmp_path: Path,
) -> None:
    _, asset, decision = _canonical_fixture(tmp_path, name="script-safe")
    title = "Atlas </script><script>alert('no')</script>"
    publication = publish_vocabulary_atlas(
        asset,
        tmp_path / "published",
        decision=decision,
        title=title,
    )
    explorer = json.loads((publication.directory / EXPLORER_DATA).read_text())
    html = (publication.directory / EXPLORER_HTML).read_text()

    assert explorer["title"] == title
    assert title not in html
    assert "\\u003c/script\\u003e" in html
    assert html.count('<script id="atlas-data" type="application/json">') == 1


def test_cli_auto_opens_canonical_and_projection_with_exact_decision_pins(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, asset, atlas_decision = _canonical_fixture(tmp_path / "canonical", name="cli-atlas")
    atlas_root = asset.write(tmp_path / "atlas-distribution")
    atlas_decision_path = atlas_decision.write_to(tmp_path / "atlas-decision.json")
    atlas_output = tmp_path / "atlas-publication"

    assert (
        main(
            [
                "--distribution",
                str(atlas_root),
                "--distribution-manifest-digest",
                asset.manifest_digest,
                "--decision",
                str(atlas_decision_path),
                "--decision-file-digest",
                sha256_digest(atlas_decision_path.read_bytes()),
                "--output",
                str(atlas_output),
            ]
        )
        == 0
    )
    AtlasPublication.open(
        atlas_output,
        expected_manifest_digest=_manifest_digest(atlas_output),
    )

    _, parent, projection, projection_decision = _projection_fixture(
        tmp_path / "projection",
        name="cli-projection",
    )
    parent_root = parent.write(tmp_path / "projection-parent")
    projection_root = projection.write(tmp_path / "projection-distribution")
    projection_decision_path = projection_decision.write_to(tmp_path / "projection-decision.json")
    projection_output = tmp_path / "projection-publication"
    assert (
        main(
            [
                "--distribution",
                str(projection_root),
                "--distribution-manifest-digest",
                projection.manifest_digest,
                "--decision",
                str(projection_decision_path),
                "--decision-file-digest",
                sha256_digest(projection_decision_path.read_bytes()),
                "--parent",
                str(parent_root),
                "--parent-manifest-digest",
                parent.manifest_digest,
                "--output",
                str(projection_output),
            ]
        )
        == 0
    )
    reopened = AtlasPublication.open(
        projection_output,
        expected_manifest_digest=_manifest_digest(projection_output),
    )
    assert isinstance(reopened.distribution, VocabularyAtlasProjection)
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_cli_publishes_and_reopens_the_exact_planning_index(
    tmp_path: Path,
) -> None:
    scope, asset, decision = _canonical_fixture(tmp_path, name="cli-indexed")
    atlas_index = scope.verified_scope().atlas_index
    atlas_root = asset.write(tmp_path / "atlas-distribution")
    decision_path = decision.write_to(tmp_path / "decision.json")
    input_path = tmp_path / "atlas-index-input.json"
    catalog_path = tmp_path / "resource-catalog.json"
    input_path.write_text(
        json.dumps(plain_json(atlas_index._index_input), indent=2) + "\n",
        encoding="utf-8",
    )
    catalog_path.write_text(
        json.dumps(plain_json(atlas_index._resource_catalog), indent=2) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "publication"

    assert (
        main(
            [
                "--distribution",
                str(atlas_root),
                "--distribution-manifest-digest",
                asset.manifest_digest,
                "--decision",
                str(decision_path),
                "--decision-file-digest",
                sha256_digest(decision_path.read_bytes()),
                "--planning-index",
                str(atlas_index.path),
                "--planning-index-file-digest",
                atlas_index.file_digest,
                "--planning-index-input",
                str(input_path),
                "--resource-catalog",
                str(catalog_path),
                "--repository-root",
                str(atlas_index._repository_root),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    reopened = AtlasPublication.open(
        output,
        expected_manifest_digest=_manifest_digest(output),
    )
    assert reopened.planning_index == atlas_index.verified_index()


def test_cli_rejects_projection_without_parent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, _, projection, decision = _projection_fixture(tmp_path, name="cli-refusal")
    projection_root = projection.write(tmp_path / "projection-distribution")
    decision_path = decision.write_to(tmp_path / "projection-decision.json")
    base = [
        "--distribution",
        str(projection_root),
        "--distribution-manifest-digest",
        projection.manifest_digest,
        "--decision",
        str(decision_path),
        "--decision-file-digest",
        sha256_digest(decision_path.read_bytes()),
        "--output",
        str(tmp_path / "published"),
    ]

    with pytest.raises(SystemExit, match="2"):
        main(base)
    assert "requires --parent" in capsys.readouterr().err
