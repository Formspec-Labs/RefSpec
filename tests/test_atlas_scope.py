"""The canonical four-ring atlas scope closes over exact, non-authorizing inputs."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

import refspec.atlas as atlas_api
from refspec.atlas.atlas_scope import (
    ATLAS_SCOPE_TYPE,
    ATLAS_SCOPE_VERSION,
    AtlasScopeError,
    AtlasScopeRelease,
    PinnedVocabularyAtlasScope,
    VocabularyAtlasScope,
)
from refspec.atlas.concept_release import (
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
    PinnedSourceConceptRelease,
)
from refspec.atlas.relation_assertion import (
    PinnedRelationAssertionBundle,
    RelationAssertionBundle,
)
from refspec.registry.infrastructure.artifact_serialization import sha256_digest
from refspec.registry.infrastructure.semantic_foundation import (
    SUBJECT_EXACT_MATCH,
    EvidenceAssertion,
    MappingAssertion,
    SemanticRing,
)
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseBundle,
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7

ASSERTED_AT = "2026-08-04T16:00:00Z"
SCOPE_NAME = "urn:ref:test:vocabulary-atlas-scope:four-rings"

_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "refspec_test_atlas_scope_managed_release_fixture",
    Path(__file__).with_name("test_managed_release_view.py"),
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_FIXTURE_MODULE = importlib.util.module_from_spec(_FIXTURE_SPEC)
sys.modules[_FIXTURE_SPEC.name] = _FIXTURE_MODULE
_FIXTURE_SPEC.loader.exec_module(_FIXTURE_MODULE)
build_managed_bundle = _FIXTURE_MODULE.build_bundle
MANAGED_RELEASE_ID = cast(str, _FIXTURE_MODULE.RELEASE_ID)


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _source_release(
    tmp_path: Path,
    name: str,
    *,
    ring: SemanticRing = "subject",
) -> tuple[SourceConceptReleaseBundle, PinnedSourceConceptRelease, str]:
    source_id = f"https://publisher.example/source/{ring}/{name}.json"
    scheme_id = f"https://publisher.example/schemes/{ring}/{name}"
    local_record_id = "urn:uuid:" + derive_uuid7(
        ASSERTED_AT,
        seed=f"atlas-scope:{ring}:{name}".encode(),
    )
    observation = {
        "id": f"urn:ref:test:atlas-scope-observation:{ring}:{name}",
        "sourceArtifact": source_id,
        "sourcePath": f"terms/{name}",
        "sourceOrdinal": 0,
        "labels": [
            {
                "value": name.replace("-", " ").title(),
                "language": "en",
                "role": "preferred",
            }
        ],
        "identifiers": [],
        "uses": ["mappingReference"],
        "conceptIdentityClaimed": False,
        "localRecordId": local_record_id,
    }
    source_payload = f'{{"term":"{name}","ring":"{ring}"}}\n'.encode()
    source = build_source_controlled_resource_bundle(
        resource_id=f"atlas-scope-{ring}-{name}",
        title=f"{name.replace('-', ' ').title()} atlas scope source",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("mappingReference",),
        captured_at=ASSERTED_AT,
        observations=(observation,),
        source_artifacts={source_id: source_payload},
        source_scheme={
            "id": scheme_id,
            "code": name,
            "label": f"{name.replace('-', ' ').title()} scheme",
            "sourceArtifact": source_id,
            "sourceFetchId": derive_uuid7(
                ASSERTED_AT,
                seed=f"atlas-scope-fetch:{ring}:{name}".encode(),
            ),
            "sourceObservedAt": ASSERTED_AT,
        },
    )
    release = build_source_concept_release_bundle(
        source,
        semantic_ring=ring,
        selected_observation_ids=(observation["id"],),
        selection_policy={
            "id": f"urn:ref:test:atlas-scope-selection:{ring}:{name}:v1",
            "type": "explicitObservationSet",
        },
        rights_metadata=(
            {
                "type": "RightsMetadata",
                "rightsStatus": "notStated",
                "sourceArtifact": source_id,
                "sourceDigest": sha256_digest(source_payload),
            },
        ),
    )
    root = release.write_to(tmp_path / f"source-release-{ring}-{name}")
    pinned = PinnedSourceConceptRelease.open(
        root,
        expected_manifest_digest=release.manifest_digest,
    )
    return release, pinned, cast(str, release.concepts[0]["id"])


def _managed_release(
    tmp_path: Path,
) -> tuple[PinnedManagedConceptRelease, PinnedManagedReleaseRingAssignment]:
    manifest = build_managed_bundle(tmp_path / "managed-release")
    assignment = ManagedReleaseRingAssignment(
        managed_manifest_digest=_file_digest(manifest),
        release_id=MANAGED_RELEASE_ID,
        semantic_ring="subject",
        assigned_by="https://refspec.org/actors/portfolio-reviewer-1",
        assigned_at=ASSERTED_AT,
        evidence=("urn:ref:test:atlas-scope:ring-assignment-review",),
    )
    assignment_path = assignment.write_to(tmp_path / "managed-ring-assignment.json")
    pinned_assignment = PinnedManagedReleaseRingAssignment.open(
        assignment_path,
        expected_file_digest=_file_digest(assignment_path),
    )
    return (
        PinnedManagedConceptRelease.open(
            manifest,
            expected_manifest_digest=_file_digest(manifest),
            release_id=MANAGED_RELEASE_ID,
            ring_assignment=pinned_assignment,
        ),
        pinned_assignment,
    )


def _pinned_subject_relation(
    tmp_path: Path,
    source: PinnedSourceConceptRelease,
    source_concept: str,
    target: PinnedSourceConceptRelease,
    target_concept: str,
) -> tuple[PinnedRelationAssertionBundle, Path]:
    evidence = EvidenceAssertion(
        semantic_ring="subject",
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by="https://refspec.org/actors/reviewer-1",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:atlas-scope:relation-evidence",),
        review_decision="urn:ref:test:atlas-scope:relation-review",
    )
    mapping = MappingAssertion(
        semantic_ring="subject",
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source.release_id,
        target_release=target.release_id,
        relation=SUBJECT_EXACT_MATCH,
        evidence=(evidence.identifier,),
        asserted_at=ASSERTED_AT,
    )
    bundle = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    root = bundle.write_to(tmp_path / "relation-bundle")
    return (
        PinnedRelationAssertionBundle.open(
            root,
            expected_manifest_digest=bundle.manifest_digest,
            release_sources=(source, target),
        ),
        root,
    )


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _all_keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def test_scope_is_public_deterministic_and_supports_all_four_rings(
    tmp_path: Path,
) -> None:
    _, subject, _ = _source_release(tmp_path, "subject", ring="subject")
    _, entity, _ = _source_release(tmp_path, "entity", ring="entity")
    _, value, _ = _source_release(tmp_path, "value", ring="value")
    _, legal, _ = _source_release(
        tmp_path,
        "legal-identity",
        ring="legalIdentity",
    )
    managed, assignment = _managed_release(tmp_path)
    releases = (
        AtlasScopeRelease(legal),
        AtlasScopeRelease(managed, "specialist"),
        AtlasScopeRelease(value),
        AtlasScopeRelease(subject, "core"),
        AtlasScopeRelease(entity),
    )

    first = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        releases=releases,
    )
    second = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        releases=tuple(reversed(releases)),
    )

    assert atlas_api.ATLAS_SCOPE_TYPE == ATLAS_SCOPE_TYPE
    assert atlas_api.ATLAS_SCOPE_VERSION == ATLAS_SCOPE_VERSION
    assert atlas_api.AtlasScopeError is AtlasScopeError
    assert atlas_api.AtlasScopeRelease is AtlasScopeRelease
    assert atlas_api.PinnedVocabularyAtlasScope is PinnedVocabularyAtlasScope
    assert atlas_api.VocabularyAtlasScope is VocabularyAtlasScope
    assert first.as_record() == second.as_record()
    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.identifier.startswith("urn:ref:vocabulary-atlas-scope:")
    assert first.content_digest.startswith("sha256:")
    rows = first.as_record()["releases"]
    assert [row["releaseId"] for row in rows] == sorted(row["releaseId"] for row in rows)
    assert {row["semanticRing"] for row in rows} == {
        "subject",
        "entity",
        "value",
        "legalIdentity",
    }
    assert next(row for row in rows if row["releaseId"] == subject.release_id)["subjectParticipation"] == "core"
    assert next(row for row in rows if row["releaseId"] == managed.release_id)["subjectParticipation"] == "specialist"
    assert all("subjectParticipation" not in row for row in rows if row["semanticRing"] != "subject")
    assert _all_keys(first.as_record()).isdisjoint(
        {
            "admission",
            "admitted",
            "authorization",
            "authorized",
            "emissionAuthorized",
            "outputProfile",
            "permission",
            "productPolicy",
        }
    )

    manifest_bytes = managed.manifest_path.read_bytes()
    managed.manifest_path.write_bytes(manifest_bytes + b" ")
    with pytest.raises(AtlasScopeError, match="manifest digest mismatch"):
        first.verify()
    managed.manifest_path.write_bytes(manifest_bytes)
    first.verify()

    assignment.path.write_bytes(assignment.path.read_bytes() + b" ")
    with pytest.raises(AtlasScopeError, match="ring assignment file digest differs"):
        first.verify()


def test_subject_participation_is_optional_and_subject_only(tmp_path: Path) -> None:
    _, subject, _ = _source_release(tmp_path, "unclassified-subject")
    _, entity, _ = _source_release(tmp_path, "classified-entity", ring="entity")

    unclassified = AtlasScopeRelease(subject)
    assert "subjectParticipation" not in unclassified.pin()
    assert unclassified.semantic_ring == "subject"

    for participation in ("experimental", [], 1):
        with pytest.raises(AtlasScopeError, match="core, specialist, bridge"):
            AtlasScopeRelease(
                subject,
                cast(Any, participation),
            )
    with pytest.raises(AtlasScopeError, match="only a subject release"):
        AtlasScopeRelease(entity, "core")


def test_scope_requires_path_backed_unique_exact_releases(tmp_path: Path) -> None:
    raw, pinned, _ = _source_release(tmp_path, "exact-release")

    with pytest.raises(AtlasScopeError, match="path-backed exact concept release"):
        AtlasScopeRelease(cast(Any, raw))
    with pytest.raises(AtlasScopeError, match="repeats a releaseId"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            releases=(AtlasScopeRelease(pinned), AtlasScopeRelease(pinned)),
        )
    with pytest.raises(AtlasScopeError, match="non-empty array"):
        VocabularyAtlasScope.create(scope_name=SCOPE_NAME, releases=())

    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        releases=(AtlasScopeRelease(pinned),),
    )
    pinned.manifest_path.write_bytes(pinned.manifest_path.read_bytes() + b" ")
    with pytest.raises(AtlasScopeError, match="manifest digest differs"):
        scope.verify()


def test_scope_requires_exact_relation_release_closure(tmp_path: Path) -> None:
    _, source, source_concept = _source_release(tmp_path, "relation-source")
    _, target, target_concept = _source_release(tmp_path, "relation-target")
    relation, relation_root = _pinned_subject_relation(
        tmp_path,
        source,
        source_concept,
        target,
        target_concept,
    )
    releases = (
        AtlasScopeRelease(target, "bridge"),
        AtlasScopeRelease(source, "core"),
    )

    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        releases=releases,
        relation_bundles=(relation,),
    )

    assert scope.as_record()["relationBundles"] == [relation.pin()]
    assert scope.relation_bundles == (relation,)
    with pytest.raises(AtlasScopeError, match="release closure is outside"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            releases=(AtlasScopeRelease(source),),
            relation_bundles=(relation,),
        )
    with pytest.raises(AtlasScopeError, match="repeats a relation bundle id"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            releases=releases,
            relation_bundles=(relation, relation),
        )
    with pytest.raises(AtlasScopeError, match="must be a pinned relation bundle"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            releases=releases,
            relation_bundles=(cast(Any, relation.verified_bundle()),),
        )

    assertions = relation_root / "relation-assertions.json"
    assertions.write_bytes(assertions.read_bytes() + b" ")
    with pytest.raises(AtlasScopeError, match="assertion artifact bytes differ"):
        scope.verify()


def test_scope_record_rejects_authority_fields_stale_identity_and_order(
    tmp_path: Path,
) -> None:
    _, first_release, _ = _source_release(tmp_path, "record-a")
    _, second_release, _ = _source_release(tmp_path, "record-b")
    releases = (
        AtlasScopeRelease(first_release),
        AtlasScopeRelease(second_release, "bridge"),
    )
    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        releases=releases,
    )

    authorization = scope.as_record()
    authorization["authorized"] = True
    with pytest.raises(AtlasScopeError, match="fields differ"):
        VocabularyAtlasScope.from_record(authorization, releases=releases)

    renamed = scope.as_record()
    renamed["scopeName"] = "urn:ref:test:vocabulary-atlas-scope:renamed"
    with pytest.raises(AtlasScopeError, match="content identity, inputs"):
        VocabularyAtlasScope.from_record(renamed, releases=releases)

    reordered = scope.as_record()
    reordered["releases"] = list(reversed(reordered["releases"]))
    with pytest.raises(AtlasScopeError, match="canonical order differs"):
        VocabularyAtlasScope.from_record(reordered, releases=releases)

    changed_participation = scope.as_record()
    bridge = next(row for row in changed_participation["releases"] if row.get("subjectParticipation") == "bridge")
    bridge["subjectParticipation"] = "core"
    with pytest.raises(AtlasScopeError, match="content identity, inputs"):
        VocabularyAtlasScope.from_record(
            changed_participation,
            releases=releases,
        )

    with pytest.raises(TypeError):
        scope.record["scopeName"] = SCOPE_NAME  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        scope.record = {}  # type: ignore[misc]


def test_pinned_scope_reopens_exact_canonical_bytes_and_fails_closed(
    tmp_path: Path,
) -> None:
    _, release, _ = _source_release(tmp_path, "persisted-scope")
    releases = (AtlasScopeRelease(release),)
    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        releases=releases,
    )
    path = scope.write_to(tmp_path / "atlas-scope.json")
    file_digest = _file_digest(path)
    pinned = PinnedVocabularyAtlasScope.open(
        path,
        expected_file_digest=file_digest,
        releases=releases,
    )

    assert pinned.verified_scope().as_record() == scope.as_record()
    assert pinned.pin() == {
        "role": "vocabularyAtlasScope",
        "id": scope.identifier,
        "contentDigest": scope.content_digest,
        "fileDigest": file_digest,
    }
    with pytest.raises(AtlasScopeError, match="destination already exists"):
        scope.write_to(path)

    symlink = tmp_path / "atlas-scope-link.json"
    symlink.symlink_to(path)
    with pytest.raises(AtlasScopeError, match="must not be a symlink"):
        PinnedVocabularyAtlasScope.open(
            symlink,
            expected_file_digest=file_digest,
            releases=releases,
        )

    noncanonical = tmp_path / "noncanonical-atlas-scope.json"
    noncanonical.write_bytes(scope.artifact_bytes() + b"\n")
    with pytest.raises(AtlasScopeError, match="bytes are not canonical"):
        PinnedVocabularyAtlasScope.open(
            noncanonical,
            expected_file_digest=_file_digest(noncanonical),
            releases=releases,
        )

    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(AtlasScopeError, match="file digest differs"):
        pinned.pin()
