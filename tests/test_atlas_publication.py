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
from refspec.atlas.atlas_scope import AtlasScopeRelease, PinnedVocabularyAtlasScope
from refspec.atlas.explorer import AtlasExplorerError, render_atlas_explorer
from refspec.atlas.model import ATLAS_FILE, VocabularyAtlasAsset, build_vocabulary_atlas
from refspec.atlas.projection import (
    VocabularyAtlasProjection,
    build_atlas_projection,
    ring_projection_policy,
)
from refspec.atlas.publication import (
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
from refspec.atlas.relation_assertion import (
    PinnedRelationAssertionBundle,
    RelationAssertionBundle,
)
from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes, sha256_digest
from refspec.registry.infrastructure.semantic_foundation import (
    ENTITY_RELATED,
    LEGAL_CITES,
    SUBJECT_EXACT_MATCH,
    VALUE_EXACT_CROSSWALK,
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
) -> tuple[PinnedVocabularyAtlasScope, VocabularyAtlasAsset, VocabularyAtlasPublicationDecision, str]:
    source, source_release_id, source_concept = relation_fixtures._source_release(
        tmp_path,
        "publication-source",
    )
    target, target_release_id, target_concept = relation_fixtures._source_release(
        tmp_path,
        "publication-target",
    )
    evidence = relation_fixtures._human_evidence("publication-review")
    mapping = relation_fixtures._mapping(
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source_release_id,
        target_release=target_release_id,
        evidence=(evidence.identifier,),
    )
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
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
                participation="core",
            ),
            model_fixtures._SCOPE_FIXTURE._IndexSpec(
                target_release,
                "publication-target",
                participation="specialist",
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

    assert model["schemaVersion"] == "2.1"
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


def test_renderer_fails_closed_on_non_2_0_view_fields(tmp_path: Path) -> None:
    _, asset, _ = _canonical_fixture(tmp_path, name="closed-explorer-shape")
    model = build_explorer_model(asset)

    old_collections = dict(model)
    old_collections["releases"] = old_collections.pop("conceptReleases")
    with pytest.raises(AtlasExplorerError, match="fields differ from Atlas explorer 2.1"):
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
