"""The four-ring atlas scope derives every classification from one exact index."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import FrozenInstanceError, dataclass
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
    validate_atlas_scope_record,
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
from refspec.atlas_index import PinnedAtlasIndex, build_atlas_index
from refspec.managed_release import ManagedReleaseGraphFactsView
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)
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

CONTEXTUAL = "https://rulespec.org/ns/v1#assignmentContextual"
PRIMARY = "https://rulespec.org/ns/v1#assignmentPrimary"

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
    assignment_path = assignment.write_to(
        tmp_path / "managed-ring-assignment.json"
    )
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


@dataclass(frozen=True)
class _IndexSpec:
    release: AtlasScopeRelease
    name: str
    participation: str | None = None
    semantic_ring: str | None = None
    manifest_digest: str | None = None
    source_module: str | None = None
    resource_id: str | None = None
    assignment_role: str = CONTEXTUAL


def _ring_details(ring: str) -> tuple[str, str]:
    return {
        "subject": ("urn:ref:facet:general-subject", "mappingReference"),
        "entity": ("urn:ref:facet:entity", "entityResolution"),
        "value": ("urn:ref:facet:code-list-value", "deterministicMetadata"),
        "legalIdentity": (
            "urn:ref:facet:legal-location",
            "legalIdentityResolution",
        ),
    }[ring]


def _pinned_index(
    tmp_path: Path,
    name: str,
    specs: tuple[_IndexSpec, ...],
) -> tuple[PinnedAtlasIndex, dict[str, Any], Path]:
    repository = tmp_path / f"index-repository-{name}"
    repository.mkdir()
    rows: list[dict[str, Any]] = []
    resources: set[str] = set()
    modules: set[str] = set()
    for position, spec in enumerate(specs):
        pin = spec.release.pin()
        ring = spec.semantic_ring or cast(str, pin["semanticRing"])
        facet, intended_use = _ring_details(ring)
        source_module = spec.source_module or (
            "refspec.registry." + spec.name.replace("-", "_")
        )
        resource_id = spec.resource_id or f"resource-{spec.name}"
        manifest_digest = spec.manifest_digest or cast(
            str,
            pin["manifestDigest"],
        )
        modules.add(source_module)
        resources.add(resource_id)
        module_path = repository / "src" / Path(*source_module.split("."))
        module_path = module_path.with_suffix(".py")
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("# index source module\n", encoding="utf-8")
        evidence_path = Path("evidence") / f"{position}-{spec.name}.json"
        evidence_file = repository / evidence_path
        evidence_file.parent.mkdir(parents=True, exist_ok=True)
        evidence_file.write_text(
            json.dumps(
                {
                    "releaseId": pin["releaseId"],
                    "manifestDigest": manifest_digest,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        rows.append(
            {
                "assignmentRole": spec.assignment_role,
                "atlasParticipation": spec.participation,
                "facet": facet,
                "intendedUses": [intended_use],
                "planningStatus": "planned",
                "semanticRing": ring,
                "readinessEvidence": [
                    {
                        "kind": "managedReleaseValidation",
                        "path": evidence_path.as_posix(),
                    }
                ],
                "release": {
                    "evidencePath": evidence_path.as_posix(),
                    "manifestDigest": manifest_digest,
                    "releaseId": pin["releaseId"],
                },
                "resourceId": resource_id,
                "sourceModule": source_module,
            }
        )
    (repository / "src/refspec/registry/__init__.py").write_text(
        "",
        encoding="utf-8",
    )
    catalog_digest = sha256_digest(name.encode())
    catalog: dict[str, Any] = {
        "catalogDigest": catalog_digest,
        "catalogId": (
            "urn:ref:test:atlas-scope-catalog:"
            + catalog_digest.removeprefix("sha256:")
        ),
        "resources": [
            {"resourceId": resource_id} for resource_id in sorted(resources)
        ],
    }
    index_input: dict[str, Any] = {
        "format": "refspec-atlas-index-input/experimental-v0",
        "implementationModules": [],
        "recordedAt": ASSERTED_AT,
        "resourceCatalogDigest": catalog_digest,
        "rows": rows,
    }
    index = build_atlas_index(
        index_input,
        catalog,
        repository_root=repository,
    )
    path = repository / "atlas-index.json"
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    pinned = PinnedAtlasIndex.open(
        path,
        expected_file_digest=_file_digest(path),
        index_input=index_input,
        resource_catalog=catalog,
        repository_root=repository,
    )
    return pinned, index, repository


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _all_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def _closed_digest(value: int) -> str:
    return f"sha256:{value:064x}"


def _file_only_scope_record() -> dict[str, Any]:
    release_specs = (
        ("entity", "entity"),
        ("legal", "legalIdentity"),
        ("subject", "subject"),
        ("value", "value"),
    )
    releases = [
        {
            "releaseKind": "sourceConceptRelease",
            "semanticRing": ring,
            "releaseId": f"urn:ref:test:file-scope:release:{name}",
            "manifestDigest": _closed_digest(position),
            "releaseDigest": _closed_digest(position + 10),
            "logicalDigest": _closed_digest(position + 20),
            "atlasIndexRows": [
                {
                    "rowId": f"urn:ref:test:file-scope:index-row:{name}",
                    "rowDigest": _closed_digest(position + 30),
                }
            ],
        }
        for position, (name, ring) in enumerate(release_specs, start=1)
    ]
    releases.append(
        {
            "releaseKind": "managedReferenceRelease",
            "semanticRing": "subject",
            "releaseId": "urn:ref:test:file-scope:release:subject-managed",
            "manifestDigest": _closed_digest(50),
            "managedBundleReleaseId": (
                "urn:ref:test:file-scope:managed-bundle-release"
            ),
            "ringAssignment": {
                "id": "urn:ref:test:file-scope:ring-assignment",
                "contentDigest": _closed_digest(51),
                "fileDigest": _closed_digest(52),
            },
            "rulespecGraph": {
                "id": "urn:ref:test:file-scope:rulespec-graph",
                "digest": _closed_digest(53),
            },
            "declaredReleaseDigest": _closed_digest(54),
            "atlasIndexRows": [
                {
                    "rowId": (
                        "urn:ref:test:file-scope:index-row:subject-managed"
                    ),
                    "rowDigest": _closed_digest(55),
                }
            ],
        }
    )
    releases.sort(
        key=lambda value: (
            cast(str, value["semanticRing"]),
            cast(str, value["releaseId"]),
        )
    )
    subject = next(
        release
        for release in releases
        if release["releaseId"] == "urn:ref:test:file-scope:release:subject"
    )
    subject["atlasIndexRows"] = [
        {
            "rowId": "urn:ref:test:file-scope:index-row:subject-a",
            "rowDigest": _closed_digest(41),
        },
        {
            "rowId": "urn:ref:test:file-scope:index-row:subject-b",
            "rowDigest": _closed_digest(42),
        },
    ]
    relation_bundles = [
        {
            "role": "RelationAssertionBundle",
            "id": "urn:ref:test:file-scope:relations:entity",
            "semanticRing": "entity",
            "contentDigest": _closed_digest(60),
            "manifestDigest": _closed_digest(61),
        },
        {
            "role": "RelationAssertionBundle",
            "id": "urn:ref:test:file-scope:relations:subject",
            "semanticRing": "subject",
            "contentDigest": _closed_digest(62),
            "manifestDigest": _closed_digest(63),
        },
    ]
    basis = {
        "type": ATLAS_SCOPE_TYPE,
        "schemaVersion": ATLAS_SCOPE_VERSION,
        "scopeName": "urn:ref:test:file-scope",
        "scopeKind": "bench",
        "atlasIndex": {
            "role": "AtlasIndex",
            "id": "urn:ref:test:file-scope:index",
            "indexDigest": _closed_digest(70),
            "fileDigest": _closed_digest(71),
        },
        "releases": releases,
        "relationBundles": relation_bundles,
    }
    content_digest = sha256_digest(canonical_json_bytes(basis))
    return {
        **basis,
        "id": (
            "urn:ref:vocabulary-atlas-scope:"
            + content_digest.removeprefix("sha256:")
        ),
        "contentDigest": content_digest,
    }


def test_file_only_scope_validator_accepts_the_closed_index_bound_record() -> None:
    record = _file_only_scope_record()

    assert validate_atlas_scope_record(record) == record
    assert {release["semanticRing"] for release in record["releases"]} == {
        "subject",
        "entity",
        "value",
        "legalIdentity",
    }
    assert {release["releaseKind"] for release in record["releases"]} == {
        "sourceConceptRelease",
        "managedReferenceRelease",
    }


def test_file_only_scope_validator_rejects_authority_and_open_shapes() -> None:
    cases: list[dict[str, Any]] = []

    top_level = _file_only_scope_record()
    top_level["authorization"] = {"authorized": True}
    cases.append(top_level)

    release = _file_only_scope_record()
    release["releases"][0]["permission"] = "publish"
    cases.append(release)

    participation = _file_only_scope_record()
    subject = next(
        item
        for item in participation["releases"]
        if item["semanticRing"] == "subject"
    )
    subject["subjectParticipation"] = "core"
    cases.append(participation)

    index = _file_only_scope_record()
    index["atlasIndex"]["admission"] = "admit"
    cases.append(index)

    index_row = _file_only_scope_record()
    index_row["releases"][0]["atlasIndexRows"][0]["authorized"] = True
    cases.append(index_row)

    relation = _file_only_scope_record()
    relation["relationBundles"][0]["productPolicy"] = "emit"
    cases.append(relation)

    for case in cases:
        with pytest.raises(AtlasScopeError, match="fields differ"):
            validate_atlas_scope_record(case)


def test_file_only_scope_validator_requires_canonical_unique_arrays() -> None:
    releases_reversed = _file_only_scope_record()
    releases_reversed["releases"].reverse()
    with pytest.raises(
        AtlasScopeError,
        match="ordered by semanticRing and releaseId",
    ):
        validate_atlas_scope_record(releases_reversed)

    release_repeated = _file_only_scope_record()
    release_repeated["releases"].append(
        dict(release_repeated["releases"][0])
    )
    with pytest.raises(AtlasScopeError, match="repeat a releaseId"):
        validate_atlas_scope_record(release_repeated)

    index_rows_reversed = _file_only_scope_record()
    subject = next(
        item
        for item in index_rows_reversed["releases"]
        if item["releaseId"] == "urn:ref:test:file-scope:release:subject"
    )
    subject["atlasIndexRows"].reverse()
    with pytest.raises(AtlasScopeError, match="ordered by rowId"):
        validate_atlas_scope_record(index_rows_reversed)

    index_rows_empty = _file_only_scope_record()
    index_rows_empty["releases"][0]["atlasIndexRows"] = []
    with pytest.raises(AtlasScopeError, match="non-empty array"):
        validate_atlas_scope_record(index_rows_empty)

    index_row_reused = _file_only_scope_record()
    index_row_reused["releases"][1]["atlasIndexRows"][0] = dict(
        index_row_reused["releases"][0]["atlasIndexRows"][0]
    )
    with pytest.raises(AtlasScopeError, match="reuse an atlasIndex rowId"):
        validate_atlas_scope_record(index_row_reused)

    relations_reversed = _file_only_scope_record()
    relations_reversed["relationBundles"].reverse()
    with pytest.raises(AtlasScopeError, match="ordered by id"):
        validate_atlas_scope_record(relations_reversed)

    relation_repeated = _file_only_scope_record()
    relation_repeated["relationBundles"].append(
        dict(relation_repeated["relationBundles"][0])
    )
    with pytest.raises(AtlasScopeError, match="repeat an id"):
        validate_atlas_scope_record(relation_repeated)


def test_file_only_scope_validator_recomputes_type_ring_and_identity() -> None:
    bad_type = _file_only_scope_record()
    bad_type["type"] = "AtlasScope"
    with pytest.raises(AtlasScopeError, match="type must be"):
        validate_atlas_scope_record(bad_type)

    bad_version = _file_only_scope_record()
    bad_version["schemaVersion"] = "2.0"
    with pytest.raises(AtlasScopeError, match="schemaVersion must be"):
        validate_atlas_scope_record(bad_version)

    bad_scope_kind = _file_only_scope_record()
    bad_scope_kind["scopeKind"] = "publication"
    with pytest.raises(AtlasScopeError, match="bench or product"):
        validate_atlas_scope_record(bad_scope_kind)

    bad_index_role = _file_only_scope_record()
    bad_index_role["atlasIndex"]["role"] = "PlanningIndex"
    with pytest.raises(AtlasScopeError, match="role must be AtlasIndex"):
        validate_atlas_scope_record(bad_index_role)

    bad_release_ring = _file_only_scope_record()
    bad_release_ring["releases"][0]["semanticRing"] = "topic"
    with pytest.raises(AtlasScopeError, match="subject, entity, value"):
        validate_atlas_scope_record(bad_release_ring)

    bad_relation_ring = _file_only_scope_record()
    bad_relation_ring["relationBundles"][0]["semanticRing"] = "organization"
    with pytest.raises(AtlasScopeError, match="subject, entity, value"):
        validate_atlas_scope_record(bad_relation_ring)

    stale_digest = _file_only_scope_record()
    stale_digest["scopeName"] = "urn:ref:test:file-scope:renamed"
    with pytest.raises(AtlasScopeError, match="contentDigest differs"):
        validate_atlas_scope_record(stale_digest)

    stale_id = _file_only_scope_record()
    stale_id["id"] = "urn:ref:vocabulary-atlas-scope:stale"
    with pytest.raises(AtlasScopeError, match="id differs"):
        validate_atlas_scope_record(stale_id)


def test_scope_is_index_bound_deterministic_and_supports_all_four_rings(
    tmp_path: Path,
) -> None:
    _, subject_source, _ = _source_release(tmp_path, "subject", ring="subject")
    _, entity_source, _ = _source_release(tmp_path, "entity", ring="entity")
    _, value_source, _ = _source_release(tmp_path, "value", ring="value")
    _, legal_source, _ = _source_release(
        tmp_path,
        "legal-identity",
        ring="legalIdentity",
    )
    managed_source, assignment = _managed_release(tmp_path)
    subject = AtlasScopeRelease(subject_source)
    entity = AtlasScopeRelease(entity_source)
    value = AtlasScopeRelease(value_source)
    legal = AtlasScopeRelease(legal_source)
    managed = AtlasScopeRelease(managed_source)
    specs = (
        _IndexSpec(
            subject,
            "subject-primary",
            participation="core",
            source_module="refspec.registry.subject",
            resource_id="subject-resource",
            assignment_role=PRIMARY,
        ),
        _IndexSpec(
            subject,
            "subject-context",
            participation="core",
            source_module="refspec.registry.subject",
            resource_id="subject-resource",
        ),
        _IndexSpec(managed, "managed", participation="specialist"),
        _IndexSpec(entity, "entity"),
        _IndexSpec(value, "value"),
        _IndexSpec(legal, "legal"),
    )
    atlas_index, raw_index, _ = _pinned_index(tmp_path, "all-rings", specs)
    releases = (legal, managed, value, subject, entity)

    first = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="product",
        atlas_index=atlas_index,
        releases=releases,
    )
    second = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="product",
        atlas_index=atlas_index,
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
    assert first.scope_kind == "product"
    assert first.as_record()["atlasIndex"] == atlas_index.pin()
    rows = first.as_record()["releases"]
    assert [
        (row["semanticRing"], row["releaseId"])
        for row in rows
    ] == sorted(
        (row["semanticRing"], row["releaseId"])
        for row in rows
    )
    assert {row["semanticRing"] for row in rows} == {
        "subject",
        "entity",
        "value",
        "legalIdentity",
    }
    subject_row = next(
        row for row in rows if row["releaseId"] == subject.release_id
    )
    expected_subject_refs = sorted(
        (
            {"rowId": row["rowId"], "rowDigest": row["rowDigest"]}
            for row in raw_index["rows"]
            if row["release"]["releaseId"] == subject.release_id
        ),
        key=lambda value: value["rowId"],
    )
    assert subject_row["atlasIndexRows"] == expected_subject_refs
    assert len(subject_row["atlasIndexRows"]) == 2
    assert _all_keys(rows).isdisjoint(
        {"subjectParticipation", "sourceModule", "resourceId"}
    )
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

    manifest_bytes = managed_source.manifest_path.read_bytes()
    managed_source.manifest_path.write_bytes(manifest_bytes + b" ")
    with pytest.raises(AtlasScopeError, match="manifest digest mismatch"):
        first.verify()
    managed_source.manifest_path.write_bytes(manifest_bytes)
    first.verify()

    assignment.path.write_bytes(assignment.path.read_bytes() + b" ")
    with pytest.raises(AtlasScopeError, match="ring assignment file digest differs"):
        first.verify()


def test_scope_kind_is_closed_and_changes_content_identity(tmp_path: Path) -> None:
    _, source, _ = _source_release(tmp_path, "scope-kind")
    release = AtlasScopeRelease(source)
    atlas_index, raw_index, _ = _pinned_index(
        tmp_path,
        "scope-kind",
        (_IndexSpec(release, "scope-kind", participation=None),),
    )

    bench = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="bench",
        atlas_index=atlas_index,
        releases=(release,),
    )
    product = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="product",
        atlas_index=atlas_index,
        releases=(release,),
    )

    assert bench.identifier != product.identifier
    with pytest.raises(AtlasScopeError, match="path-backed exact atlas index"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            scope_kind="bench",
            atlas_index=cast(Any, raw_index),
            releases=(release,),
        )
    for value in ("release", [], 1):
        with pytest.raises(AtlasScopeError, match="bench or product"):
            VocabularyAtlasScope.create(
                scope_name=SCOPE_NAME,
                scope_kind=cast(Any, value),
                atlas_index=atlas_index,
                releases=(release,),
            )


def test_scope_create_validates_each_managed_release_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed_source, _ = _managed_release(tmp_path)
    release = AtlasScopeRelease(managed_source)
    atlas_index, _, _ = _pinned_index(
        tmp_path,
        "single-managed-validation",
        (_IndexSpec(release, "managed", participation="specialist"),),
    )
    original_pin = PinnedManagedConceptRelease.pin
    original_open = ManagedReleaseGraphFactsView.open.__func__
    calls = 0
    graph_fact_opens = 0

    def counted_pin(source: PinnedManagedConceptRelease) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return original_pin(source)

    def counted_open(
        cls: type[ManagedReleaseGraphFactsView],
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> ManagedReleaseGraphFactsView:
        nonlocal graph_fact_opens
        graph_fact_opens += 1
        return original_open(
            cls,
            manifest_path,
            expected_manifest_digest=expected_manifest_digest,
        )

    monkeypatch.setattr(PinnedManagedConceptRelease, "pin", counted_pin)
    monkeypatch.setattr(
        ManagedReleaseGraphFactsView,
        "open",
        classmethod(counted_open),
    )

    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="bench",
        atlas_index=atlas_index,
        releases=(release,),
    )

    assert calls == 1
    assert graph_fact_opens == 1
    calls = 0
    graph_fact_opens = 0
    VocabularyAtlasScope.from_record(
        scope.as_record(),
        atlas_index=atlas_index,
        releases=(release,),
    )
    assert calls == 1
    assert graph_fact_opens == 1


def test_evidence_only_subject_has_no_caller_supplied_participation(
    tmp_path: Path,
) -> None:
    _, source, _ = _source_release(tmp_path, "evidence-only")
    release = AtlasScopeRelease(source)
    atlas_index, raw_index, _ = _pinned_index(
        tmp_path,
        "evidence-only",
        (_IndexSpec(release, "evidence-only", participation=None),),
    )

    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="bench",
        atlas_index=atlas_index,
        releases=(release,),
    )

    assert set(AtlasScopeRelease.__dataclass_fields__) == {"source"}
    assert raw_index["rows"][0]["atlasParticipation"] is None
    assert scope.as_record()["releases"][0]["atlasIndexRows"] == [
        {
            "rowId": raw_index["rows"][0]["rowId"],
            "rowDigest": raw_index["rows"][0]["rowDigest"],
        }
    ]


def test_scope_rejects_release_absent_or_mismatched_in_index(
    tmp_path: Path,
) -> None:
    _, first_source, _ = _source_release(tmp_path, "indexed")
    _, absent_source, _ = _source_release(tmp_path, "absent")
    first = AtlasScopeRelease(first_source)
    absent = AtlasScopeRelease(absent_source)
    atlas_index, _, _ = _pinned_index(
        tmp_path,
        "absent-release",
        (_IndexSpec(first, "indexed", participation="core"),),
    )
    with pytest.raises(AtlasScopeError, match="releaseId is absent"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            scope_kind="bench",
            atlas_index=atlas_index,
            releases=(absent,),
        )

    wrong_digest = "sha256:" + "9" * 64
    digest_index, _, _ = _pinned_index(
        tmp_path,
        "digest-mismatch",
        (
            _IndexSpec(
                first,
                "indexed",
                participation="core",
                manifest_digest=wrong_digest,
            ),
        ),
    )
    with pytest.raises(AtlasScopeError, match="manifestDigest differs"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            scope_kind="bench",
            atlas_index=digest_index,
            releases=(first,),
        )

    ring_index, _, _ = _pinned_index(
        tmp_path,
        "ring-mismatch",
        (
            _IndexSpec(
                first,
                "indexed",
                participation=None,
                semantic_ring="entity",
            ),
        ),
    )
    with pytest.raises(AtlasScopeError, match="semanticRing differs"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            scope_kind="bench",
            atlas_index=ring_index,
            releases=(first,),
        )


@pytest.mark.parametrize("conflict", ["participation", "source"])
def test_scope_rejects_conflicting_index_classifications(
    tmp_path: Path,
    conflict: str,
) -> None:
    _, source, _ = _source_release(tmp_path, f"conflict-{conflict}")
    release = AtlasScopeRelease(source)
    second = _IndexSpec(
        release,
        "second",
        participation="bridge" if conflict == "participation" else "core",
        source_module=(
            "refspec.registry.conflict_other"
            if conflict == "source"
            else "refspec.registry.conflict"
        ),
        resource_id=(
            "conflict-other-resource"
            if conflict == "source"
            else "conflict-resource"
        ),
    )
    atlas_index, _, _ = _pinned_index(
        tmp_path,
        f"conflicting-{conflict}",
        (
            _IndexSpec(
                release,
                "first",
                participation="core",
                source_module="refspec.registry.conflict",
                resource_id="conflict-resource",
                assignment_role=PRIMARY,
            ),
            second,
        ),
    )

    with pytest.raises(AtlasScopeError, match="index rows conflict"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            scope_kind="bench",
            atlas_index=atlas_index,
            releases=(release,),
        )


def test_scope_record_rejects_omitted_or_substituted_index_rows(
    tmp_path: Path,
) -> None:
    _, first_source, _ = _source_release(tmp_path, "record-first")
    _, second_source, _ = _source_release(tmp_path, "record-second")
    first = AtlasScopeRelease(first_source)
    second = AtlasScopeRelease(second_source)
    atlas_index, _, _ = _pinned_index(
        tmp_path,
        "record-bindings",
        (
            _IndexSpec(
                first,
                "first-primary",
                participation="core",
                source_module="refspec.registry.first",
                resource_id="first-resource",
                assignment_role=PRIMARY,
            ),
            _IndexSpec(
                first,
                "first-context",
                participation="core",
                source_module="refspec.registry.first",
                resource_id="first-resource",
            ),
            _IndexSpec(second, "second", participation="bridge"),
        ),
    )
    releases = (first, second)
    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="bench",
        atlas_index=atlas_index,
        releases=releases,
    )

    omitted = scope.as_record()
    first_row = next(
        row for row in omitted["releases"] if row["releaseId"] == first.release_id
    )
    first_row["atlasIndexRows"].pop()
    with pytest.raises(AtlasScopeError, match="index bindings"):
        VocabularyAtlasScope.from_record(
            omitted,
            atlas_index=atlas_index,
            releases=releases,
        )

    substituted = scope.as_record()
    first_row = next(
        row
        for row in substituted["releases"]
        if row["releaseId"] == first.release_id
    )
    second_row = next(
        row
        for row in substituted["releases"]
        if row["releaseId"] == second.release_id
    )
    first_row["atlasIndexRows"][0] = second_row["atlasIndexRows"][0]
    with pytest.raises(AtlasScopeError, match="index bindings"):
        VocabularyAtlasScope.from_record(
            substituted,
            atlas_index=atlas_index,
            releases=releases,
        )

    changed_index = scope.as_record()
    changed_index["atlasIndex"]["fileDigest"] = "sha256:" + "0" * 64
    with pytest.raises(AtlasScopeError, match="index bindings"):
        VocabularyAtlasScope.from_record(
            changed_index,
            atlas_index=atlas_index,
            releases=releases,
        )


def test_scope_requires_path_backed_unique_exact_releases(tmp_path: Path) -> None:
    raw, pinned_source, _ = _source_release(tmp_path, "exact-release")
    release = AtlasScopeRelease(pinned_source)
    atlas_index, _, _ = _pinned_index(
        tmp_path,
        "exact-release",
        (_IndexSpec(release, "exact-release", participation="core"),),
    )

    with pytest.raises(AtlasScopeError, match="path-backed exact concept release"):
        AtlasScopeRelease(cast(Any, raw))
    with pytest.raises(AtlasScopeError, match="repeats a releaseId"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            scope_kind="bench",
            atlas_index=atlas_index,
            releases=(release, release),
        )
    with pytest.raises(AtlasScopeError, match="non-empty array"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            scope_kind="bench",
            atlas_index=atlas_index,
            releases=(),
        )

    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="bench",
        atlas_index=atlas_index,
        releases=(release,),
    )
    pinned_source.manifest_path.write_bytes(
        pinned_source.manifest_path.read_bytes() + b" "
    )
    with pytest.raises(AtlasScopeError, match="manifest digest differs"):
        scope.verify()


def test_scope_requires_exact_relation_release_closure(tmp_path: Path) -> None:
    _, source_pin, source_concept = _source_release(tmp_path, "relation-source")
    _, target_pin, target_concept = _source_release(tmp_path, "relation-target")
    relation, relation_root = _pinned_subject_relation(
        tmp_path,
        source_pin,
        source_concept,
        target_pin,
        target_concept,
    )
    source = AtlasScopeRelease(source_pin)
    target = AtlasScopeRelease(target_pin)
    atlas_index, _, _ = _pinned_index(
        tmp_path,
        "relation",
        (
            _IndexSpec(source, "relation-source", participation="core"),
            _IndexSpec(target, "relation-target", participation="bridge"),
        ),
    )
    releases = (target, source)

    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="product",
        atlas_index=atlas_index,
        releases=releases,
        relation_bundles=(relation,),
    )

    assert scope.as_record()["relationBundles"] == [relation.pin()]
    assert scope.relation_bundles == (relation,)
    with pytest.raises(AtlasScopeError, match="release closure is outside"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            scope_kind="bench",
            atlas_index=atlas_index,
            releases=(source,),
            relation_bundles=(relation,),
        )
    with pytest.raises(AtlasScopeError, match="repeats a relation bundle id"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            scope_kind="bench",
            atlas_index=atlas_index,
            releases=releases,
            relation_bundles=(relation, relation),
        )
    with pytest.raises(AtlasScopeError, match="must be a pinned relation bundle"):
        VocabularyAtlasScope.create(
            scope_name=SCOPE_NAME,
            scope_kind="bench",
            atlas_index=atlas_index,
            releases=releases,
            relation_bundles=(cast(Any, relation.verified_bundle()),),
        )

    assertions = relation_root / "relation-assertions.json"
    assertions.write_bytes(assertions.read_bytes() + b" ")
    with pytest.raises(AtlasScopeError, match="assertion artifact bytes differ"):
        scope.verify()


def test_scope_record_is_closed_content_derived_and_immutable(tmp_path: Path) -> None:
    _, source, _ = _source_release(tmp_path, "closed-record")
    release = AtlasScopeRelease(source)
    atlas_index, _, _ = _pinned_index(
        tmp_path,
        "closed-record",
        (_IndexSpec(release, "closed-record", participation="core"),),
    )
    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="product",
        atlas_index=atlas_index,
        releases=(release,),
    )

    assert validate_atlas_scope_record(scope.as_record()) == scope.as_record()
    bad_ring = scope.as_record()
    bad_ring["releases"][0]["semanticRing"] = []
    with pytest.raises(AtlasScopeError, match="semanticRing"):
        validate_atlas_scope_record(bad_ring)

    authorization = scope.as_record()
    authorization["authorized"] = True
    with pytest.raises(AtlasScopeError, match="fields differ"):
        VocabularyAtlasScope.from_record(
            authorization,
            atlas_index=atlas_index,
            releases=(release,),
        )

    renamed = scope.as_record()
    renamed["scopeName"] = "urn:ref:test:vocabulary-atlas-scope:renamed"
    with pytest.raises(AtlasScopeError, match="content identity"):
        VocabularyAtlasScope.from_record(
            renamed,
            atlas_index=atlas_index,
            releases=(release,),
        )

    with pytest.raises(TypeError):
        scope.record["scopeName"] = SCOPE_NAME  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        scope.record = {}  # type: ignore[misc]


def test_scope_fails_when_exact_index_inputs_drift(tmp_path: Path) -> None:
    _, source, _ = _source_release(tmp_path, "index-drift")
    release = AtlasScopeRelease(source)
    atlas_index, _, repository = _pinned_index(
        tmp_path,
        "index-drift",
        (_IndexSpec(release, "index-drift", participation="core"),),
    )
    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="bench",
        atlas_index=atlas_index,
        releases=(release,),
    )

    evidence = next((repository / "evidence").glob("*.json"))
    evidence.write_text('{"changed":true}\n', encoding="utf-8")
    with pytest.raises(
        AtlasScopeError,
        match="evidencePath does not record both releaseId and manifestDigest",
    ):
        scope.verify()


def test_pinned_scope_reopens_once_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, source, _ = _source_release(tmp_path, "persisted-scope")
    release = AtlasScopeRelease(source)
    atlas_index, _, _ = _pinned_index(
        tmp_path,
        "persisted-scope",
        (_IndexSpec(release, "persisted-scope", participation=None),),
    )
    releases = (release,)
    scope = VocabularyAtlasScope.create(
        scope_name=SCOPE_NAME,
        scope_kind="bench",
        atlas_index=atlas_index,
        releases=releases,
    )
    path = scope.write_to(tmp_path / "atlas-scope.json")
    file_digest = _file_digest(path)
    pinned = PinnedVocabularyAtlasScope.open(
        path,
        expected_file_digest=file_digest,
        atlas_index=atlas_index,
        releases=releases,
    )

    assert pinned.verified_scope().as_record() == scope.as_record()
    assert pinned.pin() == {
        "role": "VocabularyAtlasScope",
        "id": scope.identifier,
        "contentDigest": scope.content_digest,
        "fileDigest": file_digest,
    }
    with pytest.raises(AtlasScopeError, match="destination already exists"):
        scope.write_to(path)

    original_read_bytes = Path.read_bytes
    scope_reads = 0

    def counted_read_bytes(candidate: Path) -> bytes:
        nonlocal scope_reads
        if candidate.resolve() == path.resolve():
            scope_reads += 1
            if scope_reads > 2:
                raise AssertionError("verified_scope reread the scope after reopen")
        return original_read_bytes(candidate)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    assert pinned.verified_scope().identifier == scope.identifier
    assert scope_reads == 2
    monkeypatch.setattr(Path, "read_bytes", original_read_bytes)

    symlink = tmp_path / "atlas-scope-link.json"
    symlink.symlink_to(path)
    with pytest.raises(AtlasScopeError, match="must not be a symlink"):
        PinnedVocabularyAtlasScope.open(
            symlink,
            expected_file_digest=file_digest,
            atlas_index=atlas_index,
            releases=releases,
        )

    noncanonical = tmp_path / "noncanonical-atlas-scope.json"
    noncanonical.write_bytes(scope.artifact_bytes() + b"\n")
    with pytest.raises(AtlasScopeError, match="bytes are not canonical"):
        PinnedVocabularyAtlasScope.open(
            noncanonical,
            expected_file_digest=_file_digest(noncanonical),
            atlas_index=atlas_index,
            releases=releases,
        )

    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(AtlasScopeError, match="file digest differs"):
        pinned.pin()
