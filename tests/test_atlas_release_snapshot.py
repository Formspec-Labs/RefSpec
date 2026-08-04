"""Canonical atlas release snapshots retain logical facts without authority."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, cast

import pytest

import refspec.atlas as atlas_api
import refspec.atlas.release_snapshot as release_snapshot_module
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
from refspec.managed_release import ManagedReleaseGraphFactsView
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
MANAGED_SCHEME_ID = cast(str, _FIXTURE_MODULE.SCHEME_ID)
MANAGED_DISTRIBUTION_IDS = frozenset(
    {
        cast(str, _FIXTURE_MODULE.DISTRIBUTION_ID),
        cast(str, _FIXTURE_MODULE.SECOND_DISTRIBUTION_ID),
    }
)
MANAGED_LIFECYCLE_ID = cast(str, _FIXTURE_MODULE.LIFECYCLE_EVENT_ID)
MANAGED_EXCLUDED_IDS = frozenset(
    {
        cast(str, _FIXTURE_MODULE.CONFORMANCE_RESULT_ID),
        cast(str, _FIXTURE_MODULE.IMPORT_ACTIVITY_ID),
        cast(str, _FIXTURE_MODULE.MAPPING_ID),
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
    capture_count: int | None = None,
    selected_observation_indexes: tuple[int, ...] | None = None,
    reconciliation: bool = False,
) -> tuple[
    AtlasScopeRelease,
    SourceConceptReleaseBundle,
    PinnedSourceConceptRelease,
]:
    source_id = f"https://publisher.example/source/{ring}/{name}.json"
    scheme_id = f"https://publisher.example/schemes/{ring}/{name}"
    observations: list[dict[str, Any]] = []
    observation_count = concept_count if capture_count is None else capture_count
    selected_indexes = (
        tuple(range(concept_count)) if selected_observation_indexes is None else selected_observation_indexes
    )
    if len(selected_indexes) != concept_count:
        raise ValueError("selected_observation_indexes must contain concept_count indexes")
    for index in range(observation_count):
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
    payload = (f'{{"name":"{name}","count":{observation_count}}}\n').encode()
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
        selected_observation_ids=tuple(observations[index]["id"] for index in selected_indexes),
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


def _fixed_point_managed_closure_ids(
    graph: Mapping[str, Any],
    *,
    release_id: str,
) -> set[str]:
    """Model the former fixed-point closure for semantic parity tests."""

    nodes = {cast(str, record["@id"]): record for record in graph["@graph"]}
    member_ids = release_snapshot_module._iri_values(nodes[release_id].get("prov:hadMember"))
    selected = {release_id, *member_ids}
    while True:
        prior = set(selected)
        for identifier in tuple(selected):
            record = nodes[identifier]
            for predicate in release_snapshot_module._DIRECT_CLOSURE_PREDICATES:
                selected.update(
                    reference
                    for reference in release_snapshot_module._iri_values(record.get(predicate))
                    if reference in nodes
                )
        for identifier, record in nodes.items():
            if (
                release_snapshot_module._record_types(record)
                & (release_snapshot_module._LIFECYCLE_TYPES | release_snapshot_module._RIGHTS_TYPES)
                and release_snapshot_module._record_references(record) & selected
            ):
                selected.add(identifier)
        if selected == prior:
            return selected


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
    assert atlas_api.ATLAS_RELEASE_SNAPSHOT_TYPE == ATLAS_RELEASE_SNAPSHOT_TYPE
    assert atlas_api.ATLAS_RELEASE_SNAPSHOT_VERSION == ATLAS_RELEASE_SNAPSHOT_VERSION
    assert atlas_api.AtlasReleaseSnapshot is AtlasReleaseSnapshot
    assert atlas_api.AtlasReleaseSnapshotError is AtlasReleaseSnapshotError
    assert first.semantic_ring == "subject"
    assert first.member_ids == {cast(str, concept["id"]) for concept in release.concepts}
    assert first.concept_records == tuple(release.concepts)
    assert first.as_record()["releaseBundleManifest"] == json.loads(release.artifact_bytes()["bundle-manifest.json"])
    assert first.record["releaseManifest"] == release.release_manifest
    assert first.record["sourceResourceManifest"] == (release.source_bundle.resource_manifest)
    assert first.record["sourceCoverageReport"] == (release.source_bundle.coverage_report)
    assert first.record["sourceObservations"] == tuple(
        sorted(release.source_bundle.observations, key=lambda value: cast(str, value["id"]))
    )
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


def test_source_snapshots_share_capture_pins_without_cross_ring_observation_leakage(
    tmp_path: Path,
) -> None:
    subject_scope, subject_release, _ = _source_scope_release(
        tmp_path,
        "mixed-capture",
        ring="subject",
        concept_count=2,
        capture_count=4,
        selected_observation_indexes=(0, 1),
    )
    capture = subject_release.source_bundle
    entity_release = build_source_concept_release_bundle(
        capture,
        semantic_ring="entity",
        selected_observation_ids=tuple(cast(str, capture.observations[index]["id"]) for index in (2, 3)),
        selection_policy={
            "id": "urn:ref:test:atlas-snapshot-selection:entity:mixed-capture:v1",
            "type": "explicitObservationSet",
        },
        rights_metadata=subject_release.rights_metadata,
    )
    entity_root = entity_release.write_to(tmp_path / "source-release-entity-mixed-capture")
    entity_pin = PinnedSourceConceptRelease.open(
        entity_root,
        expected_manifest_digest=entity_release.manifest_digest,
    )

    subject_snapshot = AtlasReleaseSnapshot.create(subject_scope)
    entity_snapshot = AtlasReleaseSnapshot.create(AtlasScopeRelease(entity_pin))
    subject_observations = {cast(str, value["id"]) for value in subject_snapshot.record["sourceObservations"]}
    entity_observations = {cast(str, value["id"]) for value in entity_snapshot.record["sourceObservations"]}

    assert len(capture.observations) == 4
    assert len(subject_observations) == len(entity_observations) == 2
    assert subject_observations.isdisjoint(entity_observations)
    assert subject_observations | entity_observations == {cast(str, value["id"]) for value in capture.observations}
    assert (
        subject_snapshot.record["releaseManifest"]["sourceCapture"]
        == entity_snapshot.record["releaseManifest"]["sourceCapture"]
    )
    assert subject_snapshot.record["sourceResourceManifest"] == (entity_snapshot.record["sourceResourceManifest"])
    assert subject_snapshot.record["sourceCoverageReport"] == (entity_snapshot.record["sourceCoverageReport"])

    leaked = subject_snapshot.as_record()
    leaked["sourceObservations"].append(plain_json(capture.observations[2]))
    with pytest.raises(AtlasReleaseSnapshotError, match="observations must exactly"):
        AtlasReleaseSnapshot.from_record(_reseal(leaked))


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
    with pytest.raises(AtlasReleaseSnapshotError, match="observations must exactly"):
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


def test_selected_managed_graph_work_queue_preserves_fixed_point_closure() -> None:
    release_id = "urn:ref:test:closure:release"
    member_id = "urn:ref:test:closure:member"
    scheme_id = "urn:ref:test:closure:scheme"
    distribution_id = "urn:ref:test:closure:distribution"
    direct_rights_id = "urn:ref:test:closure:direct-rights"
    direct_license_id = "urn:ref:test:closure:direct-license"
    lifecycle_ids = (
        "urn:ref:test:closure:lifecycle:1",
        "urn:ref:test:closure:lifecycle:2",
    )
    reverse_rights_id = "urn:ref:test:closure:reverse-rights"
    reverse_license_id = "urn:ref:test:closure:reverse-license"
    unrelated_lifecycle_id = "urn:ref:test:closure:unrelated-lifecycle"
    unrelated_artifact_id = "urn:ref:test:closure:unrelated-artifact"
    graph = {
        "@context": {},
        "@graph": [
            {
                "@id": reverse_rights_id,
                "@type": "rkaf:RightsMetadata",
                "dcterms:subject": {"@id": lifecycle_ids[1]},
                "dcterms:license": {"@id": reverse_license_id},
            },
            {
                "@id": release_id,
                "@type": "rkaf:ReferenceResourceRelease",
                "rkaf:membershipMode": "rkaf:completeMembership",
                "prov:hadMember": {"@id": member_id},
                "dcterms:isVersionOf": {"@id": scheme_id},
                "dcat:distribution": {"@id": distribution_id},
            },
            {
                "@id": lifecycle_ids[1],
                "@type": "rkaf:LifecycleEvent",
                "rkaf:priorEvent": {"@id": lifecycle_ids[0]},
            },
            {"@id": reverse_license_id, "@type": "dcterms:LicenseDocument"},
            {
                "@id": member_id,
                "@type": "rkaf:RegisteredConcept",
                "skos:inScheme": {"@id": scheme_id},
                "rkaf:rightsMetadata": {"@id": direct_rights_id},
            },
            {"@id": scheme_id, "@type": "rkaf:ConceptScheme"},
            {"@id": distribution_id, "@type": "rkaf:Artifact"},
            {
                "@id": direct_rights_id,
                "@type": "rkaf:RightsStatement",
                "dcterms:license": {"@id": direct_license_id},
            },
            {"@id": direct_license_id, "@type": "dcterms:LicenseDocument"},
            {
                "@id": lifecycle_ids[0],
                "@type": "rkaf:LifecycleEvent",
                "rkaf:resultingConcept": {"@id": member_id},
            },
            {
                "@id": unrelated_lifecycle_id,
                "@type": "rkaf:LifecycleEvent",
                "rkaf:resultingConcept": {"@id": unrelated_artifact_id},
            },
            {
                "@id": unrelated_artifact_id,
                "@type": "rkaf:Artifact",
                "rkaf:mentions": {"@id": member_id},
            },
        ],
    }

    selected_graph, member_ids = release_snapshot_module._selected_managed_graph(
        graph,
        release_id=release_id,
    )
    selected_ids = {cast(str, record["@id"]) for record in selected_graph["@graph"]}

    assert selected_ids == _fixed_point_managed_closure_ids(graph, release_id=release_id)
    assert selected_ids == {
        release_id,
        member_id,
        scheme_id,
        distribution_id,
        direct_rights_id,
        direct_license_id,
        *lifecycle_ids,
        reverse_rights_id,
        reverse_license_id,
    }
    assert member_ids == (member_id,)


def test_selected_managed_graph_indexes_long_chain_nodes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_id = "urn:ref:test:linear-closure:release"
    member_id = "urn:ref:test:linear-closure:member"
    reverse_ids = tuple(f"urn:ref:test:linear-closure:reverse:{index:03d}" for index in range(128))
    direct_ids = tuple(f"urn:ref:test:linear-closure:direct:{index:03d}" for index in range(128))
    inert_ids = tuple(f"urn:ref:test:linear-closure:inert:{index:03d}" for index in range(128))
    reverse_records: list[dict[str, Any]] = []
    for index, identifier in enumerate(reverse_ids):
        predecessor = member_id if index == 0 else reverse_ids[index - 1]
        record: dict[str, Any] = {
            "@id": identifier,
            "@type": "rkaf:LifecycleEvent",
            "rkaf:priorEvent": {"@id": predecessor},
        }
        if index == len(reverse_ids) - 1:
            record["dcterms:rights"] = {"@id": direct_ids[0]}
        reverse_records.append(record)
    direct_records = [
        {
            "@id": identifier,
            "@type": "rkaf:Artifact",
            **({"dcterms:rights": {"@id": direct_ids[index + 1]}} if index + 1 < len(direct_ids) else {}),
        }
        for index, identifier in enumerate(direct_ids)
    ]
    graph_nodes = [
        {
            "@id": release_id,
            "@type": "rkaf:ReferenceResourceRelease",
            "rkaf:membershipMode": "rkaf:completeMembership",
            "prov:hadMember": {"@id": member_id},
        },
        {"@id": member_id, "@type": "rkaf:RegisteredConcept"},
        *reverse_records,
        *direct_records,
        *({"@id": identifier, "@type": "rkaf:Artifact"} for identifier in inert_ids),
    ]
    graph = {"@context": {}, "@graph": graph_nodes}
    type_calls: Counter[str] = Counter()
    reference_calls: Counter[str] = Counter()
    original_record_types = release_snapshot_module._record_types
    original_record_references = release_snapshot_module._record_references

    def counted_record_types(record: Mapping[str, Any]) -> frozenset[str]:
        type_calls[cast(str, record["@id"])] += 1
        return original_record_types(record)

    def counted_record_references(record: Mapping[str, Any]) -> frozenset[str]:
        reference_calls[cast(str, record["@id"])] += 1
        return original_record_references(record)

    monkeypatch.setattr(release_snapshot_module, "_record_types", counted_record_types)
    monkeypatch.setattr(release_snapshot_module, "_record_references", counted_record_references)

    selected_graph, _ = release_snapshot_module._selected_managed_graph(
        graph,
        release_id=release_id,
    )
    selected_ids = {cast(str, record["@id"]) for record in selected_graph["@graph"]}

    assert selected_ids == {release_id, member_id, *reverse_ids, *direct_ids}
    assert sum(type_calls.values()) == len(graph_nodes) + 1
    assert type_calls[release_id] == 2
    assert all(type_calls[identifier] == 1 for identifier in set(type_calls) - {release_id})
    assert reference_calls == Counter({identifier: 1 for identifier in reverse_ids})


def test_managed_snapshot_copies_only_selected_release_semantic_closure(
    tmp_path: Path,
) -> None:
    scope_release, pinned, _ = _managed_scope_release(tmp_path)

    snapshot = AtlasReleaseSnapshot.create(scope_release)
    restored = AtlasReleaseSnapshot.from_record(snapshot.as_record())

    assert restored.as_record() == snapshot.as_record()
    assert snapshot.release_pin == pinned.pin()
    assert snapshot.semantic_ring == "subject"
    assert snapshot.member_ids == MANAGED_MEMBER_IDS
    assert snapshot.record["memberIds"] == tuple(sorted(MANAGED_MEMBER_IDS))
    assert "members" not in snapshot.record
    assert tuple(record["@id"] for record in snapshot.concept_records) == tuple(sorted(MANAGED_MEMBER_IDS))
    assert snapshot.as_record()["ringAssignment"] == (pinned.ring_assignment.verified_assignment().as_record())
    full_graph = plain_json(pinned.verified_view().rulespec_graph)
    selected_graph = snapshot.record["selectedReleaseGraph"]
    selected_ids = {cast(str, record["@id"]) for record in selected_graph["@graph"]}
    assert selected_ids == {
        MANAGED_RELEASE_ID,
        MANAGED_SCHEME_ID,
        MANAGED_LIFECYCLE_ID,
        *MANAGED_MEMBER_IDS,
        *MANAGED_DISTRIBUTION_IDS,
    }
    assert selected_ids.isdisjoint(MANAGED_EXCLUDED_IDS)
    assert len(selected_graph["@graph"]) < len(full_graph["@graph"])
    assert snapshot.release_pin["rulespecGraph"]["digest"] == rulespec_graph_digest(full_graph)
    snapshot.verify_against(scope_release)


def test_managed_snapshot_reads_legacy_1_0_member_copies(
    tmp_path: Path,
) -> None:
    scope_release, _, _ = _managed_scope_release(tmp_path)
    current = AtlasReleaseSnapshot.create(scope_release)
    legacy = current.as_record()
    legacy["schemaVersion"] = "1.0"
    legacy.pop("memberIds")
    legacy["members"] = [plain_json(value) for value in current.concept_records]

    restored = AtlasReleaseSnapshot.from_record(_reseal(legacy))

    assert restored.record["schemaVersion"] == "1.0"
    assert restored.member_ids == current.member_ids
    assert restored.concept_records == current.concept_records


def test_managed_snapshot_excludes_an_unselected_release_and_accepts_jsonld_id_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_release, pinned, _ = _managed_scope_release(tmp_path)
    view = pinned.verified_view()
    full_graph = plain_json(view.rulespec_graph)
    selected_release = next(record for record in full_graph["@graph"] if record["@id"] == MANAGED_RELEASE_ID)
    selected_release["prov:hadMember"] = [{"@id": identifier} for identifier in sorted(MANAGED_MEMBER_IDS)]
    stable_release_id = "urn:ref:test:stable-release-identity"
    selected_release["dcterms:isVersionOf"] = {"@id": stable_release_id}
    selected_release["dcat:distribution"] = [{"@id": identifier} for identifier in sorted(MANAGED_DISTRIBUTION_IDS)]
    stable_member_id = "urn:ref:test:stable-member-identity"
    selected_member = next(record for record in full_graph["@graph"] if record["@id"] == min(MANAGED_MEMBER_IDS))
    selected_member["dcterms:isVersionOf"] = stable_member_id

    other_scheme = "urn:ref:test:entity-scheme"
    other_release = "urn:ref:test:entity-release"
    other_member = "urn:ref:test:entity-member"
    other_distribution = "urn:ref:test:entity-distribution"
    full_graph["@graph"].extend(
        [
            {
                "@id": other_scheme,
                "@type": "rkaf:ConceptScheme",
                "skos:prefLabel": {"en": "Unselected entities"},
            },
            {
                "@id": other_release,
                "@type": "rkaf:ReferenceResourceRelease",
                "dcterms:isVersionOf": {"@id": other_scheme},
                "rkaf:membershipMode": "rkaf:completeMembership",
                "prov:hadMember": [{"@id": other_member}],
                "dcat:distribution": {"@id": other_distribution},
                "rkaf:referenceReleaseDigest": "sha256:" + "c" * 64,
            },
            {
                "@id": other_member,
                "@type": "rkaf:RegisteredConcept",
                "skos:prefLabel": {"en": "Unselected entity"},
                "skos:inScheme": {"@id": other_scheme},
            },
            {
                "@id": other_distribution,
                "@type": "rkaf:Artifact",
                "rkaf:hasContentDigest": "sha256:" + "d" * 64,
            },
        ]
    )
    modified_members = dict(view._members)
    modified_members[selected_member["@id"]] = replace(
        modified_members[selected_member["@id"]],
        record=selected_member,
    )
    modified_view = replace(
        view,
        _rulespec_graph=full_graph,
        _members=modified_members,
    )
    modified_pin = pinned._pin_from_verified_view(
        modified_view,
        pinned.ring_assignment.verified_assignment(),
    )
    monkeypatch.setattr(
        PinnedManagedConceptRelease,
        "verified_view_and_pin",
        lambda _self: (modified_view, modified_pin),
    )

    snapshot = AtlasReleaseSnapshot.create(scope_release)
    selected_graph = snapshot.record["selectedReleaseGraph"]
    selected_ids = {cast(str, record["@id"]) for record in selected_graph["@graph"]}

    assert snapshot.member_ids == MANAGED_MEMBER_IDS
    assert selected_ids.isdisjoint({other_scheme, other_release, other_member, other_distribution})
    assert stable_release_id not in selected_ids
    assert stable_member_id not in selected_ids
    retained_release = next(record for record in selected_graph["@graph"] if record["@id"] == MANAGED_RELEASE_ID)
    assert retained_release["prov:hadMember"] == tuple({"@id": identifier} for identifier in sorted(MANAGED_MEMBER_IDS))
    snapshot.verify_against(scope_release)


def test_managed_snapshot_rejects_member_graph_and_ring_inconsistency(
    tmp_path: Path,
) -> None:
    scope_release, _, _ = _managed_scope_release(tmp_path)
    snapshot = AtlasReleaseSnapshot.create(scope_release)

    missing = snapshot.as_record()
    missing["memberIds"] = missing["memberIds"][:-1]
    with pytest.raises(AtlasReleaseSnapshotError, match="exactly equal"):
        AtlasReleaseSnapshot.from_record(_reseal(missing))

    reordered = snapshot.as_record()
    reordered["memberIds"] = list(reversed(reordered["memberIds"]))
    with pytest.raises(AtlasReleaseSnapshotError, match="canonical identifier order"):
        AtlasReleaseSnapshot.from_record(_reseal(reordered))

    missing_scheme = snapshot.as_record()
    missing_scheme["selectedReleaseGraph"]["@graph"] = [
        record for record in missing_scheme["selectedReleaseGraph"]["@graph"] if record["@id"] != MANAGED_SCHEME_ID
    ]
    with pytest.raises(AtlasReleaseSnapshotError, match="lacks .* records"):
        AtlasReleaseSnapshot.from_record(_reseal(missing_scheme))

    graph_tamper = snapshot.as_record()
    graph_tamper["selectedReleaseGraph"]["@graph"].append(
        {
            "@id": "urn:ref:test:unrelated-managed-record",
            "@type": "rkaf:Artifact",
        }
    )
    with pytest.raises(AtlasReleaseSnapshotError, match="outside the selected release closure"):
        AtlasReleaseSnapshot.from_record(_reseal(graph_tamper))

    authorizing = snapshot.as_record()
    member_id = cast(str, authorizing["memberIds"][0])
    next(record for record in authorizing["selectedReleaseGraph"]["@graph"] if record["@id"] == member_id)[
        "authorized"
    ] = True
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


def test_managed_snapshot_uses_one_graph_facts_open_per_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_release, _, _ = _managed_scope_release(tmp_path)
    original_open = ManagedReleaseGraphFactsView.open.__func__
    calls = 0

    def counted_open(
        cls: type[ManagedReleaseGraphFactsView],
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> ManagedReleaseGraphFactsView:
        nonlocal calls
        calls += 1
        return original_open(
            cls,
            manifest_path,
            expected_manifest_digest=expected_manifest_digest,
        )

    monkeypatch.setattr(
        ManagedReleaseGraphFactsView,
        "open",
        classmethod(counted_open),
    )

    snapshot = AtlasReleaseSnapshot.create(scope_release)
    assert calls == 1

    calls = 0
    snapshot.verify_against(scope_release)
    assert calls == 1
