"""Canonical atlas release snapshots retain logical facts without authority."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

from refspec.atlas.atlas_scope import AtlasScopeRelease
from refspec.atlas.concept_release import (
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
    PinnedSourceConceptRelease,
)
from refspec.atlas.release_snapshot import (
    ATLAS_RELEASE_SNAPSHOT_TYPE,
    ATLAS_RELEASE_SNAPSHOT_VERSION,
    AtlasReleaseSnapshot,
    AtlasReleaseSnapshotError,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.semantic_foundation import SemanticRing
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseBundle,
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7
from refspec.release_graph import rulespec_graph_digest

ASSERTED_AT = "2026-08-04T16:00:00Z"

_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "refspec_test_atlas_release_snapshot_managed_fixture",
    Path(__file__).with_name("test_managed_release_view.py"),
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_FIXTURE_MODULE = importlib.util.module_from_spec(_FIXTURE_SPEC)
sys.modules[_FIXTURE_SPEC.name] = _FIXTURE_MODULE
_FIXTURE_SPEC.loader.exec_module(_FIXTURE_MODULE)
build_managed_bundle = _FIXTURE_MODULE.build_bundle
MANAGED_RELEASE_ID = cast(str, _FIXTURE_MODULE.RELEASE_ID)
MANAGED_MEMBER_IDS = frozenset(
    {
        cast(str, _FIXTURE_MODULE.MEMBER_ID),
        cast(str, _FIXTURE_MODULE.ELIGIBILITY_MEMBER_ID),
    }
)


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _source_scope_release(
    tmp_path: Path,
    name: str,
    *,
    ring: SemanticRing = "subject",
    concept_count: int = 2,
    reconciliation: bool = False,
) -> tuple[
    AtlasScopeRelease,
    SourceConceptReleaseBundle,
    PinnedSourceConceptRelease,
]:
    source_id = f"https://publisher.example/source/{ring}/{name}.json"
    scheme_id = f"https://publisher.example/schemes/{ring}/{name}"
    observations: list[dict[str, Any]] = []
    for index in range(concept_count):
        observations.append(
            {
                "id": f"urn:ref:test:atlas-snapshot-observation:{ring}:{name}:{index:02d}",
                "sourceArtifact": source_id,
                "sourcePath": f"terms/{index:02d}",
                "sourceOrdinal": index,
                "labels": [
                    {
                        "value": f"{name.title()} {index}",
                        "language": "en",
                        "role": "preferred",
                    }
                ],
                "identifiers": [],
                "uses": ["mappingReference"],
                "conceptIdentityClaimed": False,
                "localRecordId": "urn:uuid:"
                + derive_uuid7(
                    ASSERTED_AT,
                    seed=f"atlas-snapshot:{ring}:{name}:{index}".encode(),
                ),
            }
        )
    payload = (f'{{"name":"{name}","count":{concept_count}}}\n').encode()
    source = build_source_controlled_resource_bundle(
        resource_id=f"atlas-snapshot-{ring}-{name}",
        title=f"{name.title()} atlas snapshot source",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("mappingReference",),
        captured_at=ASSERTED_AT,
        observations=observations,
        source_artifacts={source_id: payload},
        source_scheme={
            "id": scheme_id,
            "code": name,
            "label": f"{name.title()} scheme",
            "sourceArtifact": source_id,
            "sourceFetchId": derive_uuid7(
                ASSERTED_AT,
                seed=f"atlas-snapshot-fetch:{ring}:{name}".encode(),
            ),
            "sourceObservedAt": ASSERTED_AT,
        },
    )
    reconciliation_record: Mapping[str, Any] | None = None
    if reconciliation:
        reconciliation_record = {
            "currentManifestId": source.resource_manifest["id"],
            "requiresHumanReview": False,
            "previousManifestId": None,
            "review": None,
        }
    release = build_source_concept_release_bundle(
        source,
        semantic_ring=ring,
        selected_observation_ids=tuple(value["id"] for value in observations),
        selection_policy={
            "id": f"urn:ref:test:atlas-snapshot-selection:{ring}:{name}:v1",
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
        reconciliation_record=reconciliation_record,
    )
    root = release.write_to(tmp_path / f"source-release-{ring}-{name}")
    pinned = PinnedSourceConceptRelease.open(
        root,
        expected_manifest_digest=release.manifest_digest,
    )
    return AtlasScopeRelease(pinned), release, pinned


def _managed_scope_release(
    tmp_path: Path,
) -> tuple[
    AtlasScopeRelease,
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
]:
    manifest = build_managed_bundle(tmp_path / "managed-release")
    assignment = ManagedReleaseRingAssignment(
        managed_manifest_digest=_file_digest(manifest),
        release_id=MANAGED_RELEASE_ID,
        semantic_ring="subject",
        assigned_by="https://refspec.org/actors/portfolio-reviewer-1",
        assigned_at=ASSERTED_AT,
        evidence=("urn:ref:test:atlas-snapshot:ring-review",),
    )
    assignment_path = assignment.write_to(tmp_path / "ring-assignment.json")
    pinned_assignment = PinnedManagedReleaseRingAssignment.open(
        assignment_path,
        expected_file_digest=_file_digest(assignment_path),
    )
    pinned = PinnedManagedConceptRelease.open(
        manifest,
        expected_manifest_digest=_file_digest(manifest),
        release_id=MANAGED_RELEASE_ID,
        ring_assignment=pinned_assignment,
    )
    return AtlasScopeRelease(pinned), pinned, pinned_assignment


def _reseal(record: dict[str, Any]) -> dict[str, Any]:
    basis = {key: value for key, value in record.items() if key not in {"id", "contentDigest"}}
    digest = sha256_digest(canonical_json_bytes(basis))
    return {
        **basis,
        "id": "urn:ref:atlas-release-snapshot:" + digest.removeprefix("sha256:"),
        "contentDigest": digest,
    }


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {key for child in value.values() for key in _all_keys(child)}
    if isinstance(value, (list, tuple)):
        return {key for child in value for key in _all_keys(child)}
    return set()


def test_source_snapshot_copies_complete_logical_release_and_is_immutable(
    tmp_path: Path,
) -> None:
    scope_release, release, pinned = _source_scope_release(tmp_path, "source")

    first = AtlasReleaseSnapshot.create(scope_release)
    second = AtlasReleaseSnapshot.create(scope_release)
    restored = AtlasReleaseSnapshot.from_record(first.as_record())

    assert first.as_record() == second.as_record() == restored.as_record()
    assert first.record["type"] == ATLAS_RELEASE_SNAPSHOT_TYPE
    assert first.record["schemaVersion"] == ATLAS_RELEASE_SNAPSHOT_VERSION
    assert first.release_pin == pinned.pin()
    assert first.release_id == release.release_id
    assert first.semantic_ring == "subject"
    assert first.member_ids == {cast(str, concept["id"]) for concept in release.concepts}
    assert first.concept_records == tuple(release.concepts)
    assert first.record["releaseManifest"] == release.release_manifest
    assert first.record["sourceResourceManifest"] == (release.source_bundle.resource_manifest)
    assert first.record["sourceCoverageReport"] == (release.source_bundle.coverage_report)
    assert first.record["sourceObservations"] == release.source_bundle.observations
    assert "reconciliationRecord" not in first.record
    assert first.identifier.startswith("urn:ref:atlas-release-snapshot:")
    assert first.content_digest.startswith("sha256:")
    first.verify_against(scope_release)

    forbidden = {
        "admission",
        "admissionReview",
        "authorization",
        "authorized",
        "emissionAuthorized",
        "outputProfile",
        "permission",
        "productPolicy",
    }
    assert _all_keys(first.record).isdisjoint(forbidden)
    with pytest.raises(TypeError):
        first.record["type"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        first.concept_records[0]["id"] = "urn:changed"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        first.record = {}  # type: ignore[misc]
    mutable_copy = first.as_record()
    mutable_copy["concepts"][0]["id"] = "urn:changed"
    assert "urn:changed" not in first.member_ids


def test_source_snapshot_omits_absent_reconciliation_but_preserves_exact_nulls(
    tmp_path: Path,
) -> None:
    scope_release, release, _ = _source_scope_release(
        tmp_path,
        "reconciled",
        reconciliation=True,
    )

    snapshot = AtlasReleaseSnapshot.create(scope_release)

    assert snapshot.record["reconciliationRecord"] == (release.reconciliation_record)
    assert snapshot.record["reconciliationRecord"]["previousManifestId"] is None
    assert AtlasReleaseSnapshot.from_record(snapshot.as_record()).as_record() == (snapshot.as_record())


def test_source_snapshot_rejects_noncanonical_incomplete_or_authorizing_records(
    tmp_path: Path,
) -> None:
    scope_release, _, _ = _source_scope_release(tmp_path, "validation")
    snapshot = AtlasReleaseSnapshot.create(scope_release)

    reordered = snapshot.as_record()
    reordered["concepts"] = list(reversed(reordered["concepts"]))
    with pytest.raises(AtlasReleaseSnapshotError, match="canonical identifier order"):
        AtlasReleaseSnapshot.from_record(_reseal(reordered))

    incomplete = snapshot.as_record()
    incomplete["concepts"] = incomplete["concepts"][:-1]
    with pytest.raises(AtlasReleaseSnapshotError, match="conceptCount"):
        AtlasReleaseSnapshot.from_record(_reseal(incomplete))

    authorizing = snapshot.as_record()
    authorizing["sourceObservations"][0]["authorized"] = True
    with pytest.raises(AtlasReleaseSnapshotError):
        AtlasReleaseSnapshot.from_record(_reseal(authorizing))

    extra = snapshot.as_record()
    extra["publicationPolicy"] = {"id": "urn:ref:test:policy"}
    with pytest.raises(AtlasReleaseSnapshotError, match="fields differ"):
        AtlasReleaseSnapshot.from_record(_reseal(extra))

    stale = snapshot.as_record()
    stale["contentDigest"] = "sha256:" + "0" * 64
    with pytest.raises(AtlasReleaseSnapshotError, match="content identity"):
        AtlasReleaseSnapshot.from_record(stale)

    stale_manifest_pin = snapshot.as_record()
    stale_manifest_pin["releasePin"]["manifestDigest"] = "sha256:" + "0" * 64
    with pytest.raises(AtlasReleaseSnapshotError, match="manifestDigest is stale"):
        AtlasReleaseSnapshot.from_record(_reseal(stale_manifest_pin))


def test_source_snapshot_verifies_against_one_exact_scope_release(
    tmp_path: Path,
) -> None:
    first_scope, _, first_pin = _source_scope_release(tmp_path, "first")
    second_scope, _, _ = _source_scope_release(tmp_path, "second")
    snapshot = AtlasReleaseSnapshot.create(first_scope)

    with pytest.raises(AtlasReleaseSnapshotError, match="differs from the exact"):
        snapshot.verify_against(second_scope)

    first_pin.manifest_path.write_bytes(first_pin.manifest_path.read_bytes() + b" ")
    with pytest.raises(AtlasReleaseSnapshotError, match="manifest digest differs"):
        snapshot.verify_against(first_scope)


def test_managed_snapshot_copies_graph_assignment_and_exact_selected_members(
    tmp_path: Path,
) -> None:
    scope_release, pinned, _ = _managed_scope_release(tmp_path)

    snapshot = AtlasReleaseSnapshot.create(scope_release)
    restored = AtlasReleaseSnapshot.from_record(snapshot.as_record())

    assert restored.as_record() == snapshot.as_record()
    assert snapshot.release_pin == pinned.pin()
    assert snapshot.semantic_ring == "subject"
    assert snapshot.member_ids == MANAGED_MEMBER_IDS
    assert tuple(record["@id"] for record in snapshot.concept_records) == tuple(sorted(MANAGED_MEMBER_IDS))
    assert snapshot.as_record()["ringAssignment"] == (pinned.ring_assignment.verified_assignment().as_record())
    assert snapshot.as_record()["rulespecGraph"] == (plain_json(pinned.verified_view().rulespec_graph))
    assert len(snapshot.record["rulespecGraph"]["@graph"]) > len(snapshot.concept_records)
    snapshot.verify_against(scope_release)


def test_managed_snapshot_rejects_member_graph_and_ring_inconsistency(
    tmp_path: Path,
) -> None:
    scope_release, _, _ = _managed_scope_release(tmp_path)
    snapshot = AtlasReleaseSnapshot.create(scope_release)

    missing = snapshot.as_record()
    missing["members"] = missing["members"][:-1]
    with pytest.raises(AtlasReleaseSnapshotError, match="exactly equal"):
        AtlasReleaseSnapshot.from_record(_reseal(missing))

    reordered = snapshot.as_record()
    reordered["members"] = list(reversed(reordered["members"]))
    with pytest.raises(AtlasReleaseSnapshotError, match="canonical identifier order"):
        AtlasReleaseSnapshot.from_record(_reseal(reordered))

    graph_tamper = snapshot.as_record()
    graph_tamper["rulespecGraph"]["@graph"][0]["test:changed"] = True
    with pytest.raises(AtlasReleaseSnapshotError, match="graph digest differs"):
        AtlasReleaseSnapshot.from_record(_reseal(graph_tamper))

    authorizing = snapshot.as_record()
    authorizing["rulespecGraph"]["@graph"][0]["authorized"] = True
    authorizing["releasePin"]["rulespecGraph"]["digest"] = rulespec_graph_digest(authorizing["rulespecGraph"])
    with pytest.raises(AtlasReleaseSnapshotError, match="admission or permission"):
        AtlasReleaseSnapshot.from_record(_reseal(authorizing))

    ring_tamper = snapshot.as_record()
    ring_tamper["releasePin"]["semanticRing"] = "entity"
    with pytest.raises(AtlasReleaseSnapshotError, match="ring assignment differs"):
        AtlasReleaseSnapshot.from_record(_reseal(ring_tamper))

    assignment_pin_tamper = snapshot.as_record()
    assignment_pin_tamper["releasePin"]["ringAssignment"]["fileDigest"] = "sha256:" + "0" * 64
    with pytest.raises(AtlasReleaseSnapshotError, match="ring assignment differs"):
        AtlasReleaseSnapshot.from_record(_reseal(assignment_pin_tamper))


def test_managed_snapshot_verify_reopens_assignment_file(tmp_path: Path) -> None:
    scope_release, _, assignment = _managed_scope_release(tmp_path)
    snapshot = AtlasReleaseSnapshot.create(scope_release)

    assignment.path.write_bytes(assignment.path.read_bytes() + b" ")
    with pytest.raises(AtlasReleaseSnapshotError, match="file digest differs"):
        snapshot.verify_against(scope_release)
