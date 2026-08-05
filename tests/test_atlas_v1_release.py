"""The v1 builder seals and assembles six exact releases from tiny fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

import refspec.atlas.v1_release as v1_module
from refspec.atlas.concept_release import PinnedSourceConceptRelease
from refspec.atlas.relation_assertion import RelationAssertionBundle
from refspec.atlas.v1_release import (
    VocabularyAtlasV1ReleaseDefinition,
    VocabularyAtlasV1ReleaseError,
    build_vocabulary_atlas_v1_release,
    read_vocabulary_atlas_v1_release_definition,
)
from refspec.atlas_index import build_atlas_index
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

ASSERTED_AT = "2026-08-04T18:00:00Z"
ACTOR = "https://refspec.org/actors/v1-release-test"
CONTEXTUAL = "https://rulespec.org/ns/v1#assignmentContextual"


def _relative(root: Path, path: Path) -> str:
    return path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix()


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _source_release(
    root: Path,
    key: str,
    *,
    ring: SemanticRing,
) -> tuple[SourceConceptReleaseBundle, PinnedSourceConceptRelease, str]:
    source_id = f"https://publisher.example/v1/{key}.json"
    observation_id = f"urn:ref:test:v1-observation:{key}"
    source_payload = canonical_json_bytes({"key": key, "ring": ring})
    source = build_source_controlled_resource_bundle(
        resource_id=f"v1-{key}",
        title=f"V1 {key} source",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("mappingReference",),
        captured_at=ASSERTED_AT,
        observations=(
            {
                "id": observation_id,
                "sourceArtifact": source_id,
                "sourcePath": f"terms/{key}",
                "sourceOrdinal": 0,
                "labels": [
                    {
                        "value": key.replace("-", " ").title(),
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
                    seed=f"v1-release:{key}".encode(),
                ),
            },
        ),
        source_artifacts={source_id: source_payload},
        source_scheme={
            "id": f"https://publisher.example/v1/schemes/{key}",
            "code": key,
            "label": f"V1 {key} scheme",
            "sourceArtifact": source_id,
            "sourceFetchId": derive_uuid7(
                ASSERTED_AT,
                seed=f"v1-fetch:{key}".encode(),
            ),
            "sourceObservedAt": ASSERTED_AT,
        },
    )
    release = build_source_concept_release_bundle(
        source,
        semantic_ring=ring,
        selected_observation_ids=(observation_id,),
        selection_policy={
            "id": f"urn:ref:test:v1-selection:{key}",
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
    package = release.write_to(root / "releases" / key)
    pinned = PinnedSourceConceptRelease.open(
        package,
        expected_manifest_digest=release.manifest_digest,
    )
    return release, pinned, cast(str, release.concepts[0]["id"])


def _planning_index(
    root: Path,
    releases: list[tuple[str, PinnedSourceConceptRelease]],
) -> tuple[Path, Path, Path]:
    rows: list[dict[str, Any]] = []
    resources: list[dict[str, str]] = []
    for position, (key, release) in enumerate(releases):
        module = f"refspec.registry.v1_source_{position}"
        module_path = root / "src" / Path(*module.split("."))
        _write(module_path.with_suffix(".py"), b"# tiny v1 index source\n")
        evidence_path = Path("evidence") / f"{position}-{key}.json"
        _write(
            root / evidence_path,
            canonical_json_bytes(
                {
                    "releaseId": release.release_id,
                    "manifestDigest": release.manifest_digest,
                }
            ),
        )
        resource_id = f"v1-resource-{key}"
        resources.append({"resourceId": resource_id})
        rows.append(
            {
                "assignmentRole": CONTEXTUAL,
                "atlasParticipation": ("core" if release.semantic_ring == "subject" else None),
                "facet": (
                    "urn:ref:facet:general-subject" if release.semantic_ring == "subject" else "urn:ref:facet:entity"
                ),
                "intendedUses": (["mappingReference"] if release.semantic_ring == "subject" else ["entityResolution"]),
                "planningStatus": "planned",
                "readinessEvidence": [
                    {
                        "kind": "managedReleaseValidation",
                        "path": evidence_path.as_posix(),
                    }
                ],
                "release": {
                    "evidencePath": evidence_path.as_posix(),
                    "manifestDigest": release.manifest_digest,
                    "releaseId": release.release_id,
                },
                "resourceId": resource_id,
                "semanticRing": release.semantic_ring,
                "sourceModule": module,
            }
        )
    _write(root / "src/refspec/registry/__init__.py", b"")
    catalog_digest = sha256_digest(b"tiny-v1-catalog")
    catalog = {
        "catalogDigest": catalog_digest,
        "catalogId": "urn:ref:test:v1-catalog:" + catalog_digest.removeprefix("sha256:"),
        "resources": resources,
    }
    index_input = {
        "format": "refspec-atlas-index-input/experimental-v0",
        "implementationModules": [],
        "recordedAt": ASSERTED_AT,
        "resourceCatalogDigest": catalog_digest,
        "rows": rows,
    }
    index = build_atlas_index(index_input, catalog, repository_root=root)
    index_path = _write(root / "planning/atlas-index.json", canonical_json_bytes(index))
    input_path = _write(
        root / "planning/atlas-index-input.json",
        canonical_json_bytes(index_input),
    )
    catalog_path = _write(
        root / "planning/resource-catalog.json",
        canonical_json_bytes(catalog),
    )
    return index_path, input_path, catalog_path


class _SourceBackedManagedRelease:
    """Use tiny source packages while exercising each managed dispatch branch."""

    @classmethod
    def open(
        cls,
        manifest_path: Path,
        *,
        expected_manifest_digest: str,
        release_id: str,
        ring_assignment: object,
    ) -> PinnedSourceConceptRelease:
        del ring_assignment
        release = PinnedSourceConceptRelease.open(
            manifest_path,
            expected_manifest_digest=expected_manifest_digest,
        )
        assert release.release_id == release_id
        return release


def _definition_fixture(
    tmp_path: Path,
) -> tuple[Path, VocabularyAtlasV1ReleaseDefinition]:
    root = tmp_path / "artifacts"
    root.mkdir()
    specs = [
        ("crs-subjects", "sourceConceptRelease", "subject"),
        ("crs-policy", "sourceConceptRelease", "subject"),
        ("crs-entities", "sourceConceptRelease", "entity"),
        ("elsst", "managedConceptRelease", "subject"),
        (
            "federal-register",
            "federalRegisterManagedConceptRelease",
            "subject",
        ),
        ("icpsr", "icpsrManagedConceptRelease", "subject"),
    ]
    release_rows: list[dict[str, Any]] = []
    pinned_rows: list[tuple[str, PinnedSourceConceptRelease]] = []
    concept_ids: dict[str, str] = {}
    for key, kind, ring in specs:
        release, pinned, concept_id = _source_release(
            root,
            key,
            ring=cast(SemanticRing, ring),
        )
        pinned_rows.append((key, pinned))
        concept_ids[key] = concept_id
        row: dict[str, Any] = {
            "key": key,
            "kind": kind,
            "label": key.replace("-", " ").title(),
            "manifestPath": _relative(root, pinned.manifest_path),
            "manifestDigest": release.manifest_digest,
            "releaseId": pinned.release_id,
            "semanticRing": ring,
        }
        if kind != "sourceConceptRelease":
            row["ringAssignment"] = {
                "assignedBy": ACTOR,
                "assignedAt": ASSERTED_AT,
                "evidence": [f"urn:ref:test:v1-ring-review:{key}"],
            }
        release_rows.append(row)

    index_path, index_input_path, catalog_path = _planning_index(root, pinned_rows)
    source = dict(pinned_rows)
    evidence = EvidenceAssertion(
        semantic_ring="subject",
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by=ACTOR,
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:v1-mapping-review-evidence",),
        review_decision="urn:ref:test:v1-mapping-review",
    )
    mapping = MappingAssertion(
        semantic_ring="subject",
        source_concept=concept_ids["crs-subjects"],
        target_concept=concept_ids["crs-policy"],
        source_release=source["crs-subjects"].release_id,
        target_release=source["crs-policy"].release_id,
        relation=SUBJECT_EXACT_MATCH,
        evidence=(evidence.identifier,),
        asserted_at=ASSERTED_AT,
    )
    relation = RelationAssertionBundle.create(
        semantic_ring="subject",
        release_sources=(source["crs-subjects"], source["crs-policy"]),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    relation_root = relation.write_to(root / "relations/crs-subjects-policy")

    release_ids = {key: release.release_id for key, release in pinned_rows}
    policy_digest = sha256_digest(b"v1-test-policy")
    basis = {
        "type": "VocabularyAtlasV1ReleaseDefinition",
        "schemaVersion": "1.0",
        "releaseName": "urn:ref:test:vocabulary-atlas:v1",
        "scopeName": "urn:ref:test:vocabulary-atlas:v1:published-scope",
        "scopeKind": "published",
        "title": "Tiny Vocabulary Atlas v1",
        "planningIndex": {
            "path": _relative(root, index_path),
            "fileDigest": sha256_digest(index_path.read_bytes()),
            "inputPath": _relative(root, index_input_path),
            "inputFileDigest": sha256_digest(index_input_path.read_bytes()),
            "resourceCatalogPath": _relative(root, catalog_path),
            "resourceCatalogFileDigest": sha256_digest(catalog_path.read_bytes()),
            "repositoryRoot": ".",
        },
        "releases": release_rows,
        "relationBundles": [
            {
                "key": "crs-subjects-policy",
                "manifestPath": _relative(root, relation_root / "bundle-manifest.json"),
                "manifestDigest": relation.manifest_digest,
                "semanticRing": "subject",
                "releaseIds": sorted([release_ids["crs-subjects"], release_ids["crs-policy"]]),
                "machineProofs": [],
            }
        ],
        "publication": {
            "decisionActor": ACTOR,
            "decidedAt": ASSERTED_AT,
            "policies": [
                {
                    "role": "selectionPolicy",
                    "id": "https://refspec.org/policies/test/v1-selection/1.0",
                    "version": "1.0",
                    "contentDigest": policy_digest,
                },
                {
                    "role": "qualificationPolicy",
                    "id": "https://refspec.org/policies/test/v1-qualification/1.0",
                    "version": "1.0",
                    "contentDigest": policy_digest,
                },
            ],
            "exceptions": [],
            "supersedes": [],
            "acceptanceChecks": [
                {
                    "id": "urn:ref:test:v1-acceptance:complete-release",
                    "statement": "The exact six-release build and public package passed their release gates.",
                    "status": "passed",
                    "evidence": ["urn:ref:test:v1-acceptance-evidence"],
                }
            ],
        },
        "expectedCounts": {
            "releaseCount": 6,
            "planningRowCount": 6,
            "includedPlanningRowCount": 6,
            "conceptTotal": 6,
            "conceptsByRelease": {release_id: 1 for release_id in release_ids.values()},
            "nativeRelationTotal": 0,
            "nativeRelationsByRelease": {release_id: 0 for release_id in release_ids.values()},
            "mappingMinimumTotal": 1,
            "mappingMinimumByRelation": {SUBJECT_EXACT_MATCH: 1},
        },
    }
    definition = VocabularyAtlasV1ReleaseDefinition.seal(basis)
    definition_path = definition.write_to(root / "definitions/vocabulary-atlas-v1.json")
    return definition_path, definition


def test_definition_is_canonical_content_derived_and_exact(tmp_path: Path) -> None:
    definition_path, sealed = _definition_fixture(tmp_path)
    reopened = read_vocabulary_atlas_v1_release_definition(
        definition_path,
        expected_file_digest=sha256_digest(definition_path.read_bytes()),
    )

    assert reopened.identifier == sealed.identifier
    assert reopened.record_digest == sealed.record_digest
    assert len(reopened.record["releases"]) == 6
    assert reopened.record["scopeKind"] == "published"

    with pytest.raises(VocabularyAtlasV1ReleaseError, match="file digest differs"):
        read_vocabulary_atlas_v1_release_definition(
            definition_path,
            expected_file_digest="sha256:" + "0" * 64,
        )

    noncanonical_path = tmp_path / "noncanonical-definition.json"
    noncanonical_path.write_text(
        json.dumps(sealed.as_record(), indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="not canonical"):
        read_vocabulary_atlas_v1_release_definition(
            noncanonical_path,
            expected_file_digest=sha256_digest(noncanonical_path.read_bytes()),
        )


def test_builder_dispatches_all_release_kinds_and_seals_complete_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition_path, _ = _definition_fixture(tmp_path)
    definition = read_vocabulary_atlas_v1_release_definition(
        definition_path,
        expected_file_digest=sha256_digest(definition_path.read_bytes()),
    )
    monkeypatch.setattr(
        v1_module,
        "PinnedManagedConceptRelease",
        _SourceBackedManagedRelease,
    )
    monkeypatch.setattr(
        v1_module,
        "PinnedFederalRegisterManagedConceptRelease",
        _SourceBackedManagedRelease,
    )
    monkeypatch.setattr(
        v1_module,
        "PinnedIcpsrManagedConceptRelease",
        _SourceBackedManagedRelease,
    )

    output = tmp_path / "v1-release"
    build = build_vocabulary_atlas_v1_release(
        definition,
        artifact_root=definition_path.parents[1],
        output_directory=output,
    )

    assert build.output_directory == output.resolve()
    assert build.result["status"] == "passed"
    assert build.result["counts"]["concepts"]["total"] == 6
    assert build.result["counts"]["mappingAssertions"]["total"] == 1
    assert build.result["counts"]["facets"]["rowCount"] == 6
    assert (output / "canonical/atlas.nq").is_file()
    assert (output / "public/publication-manifest.json").is_file()
    assert (output / "control/release-acceptance.json").is_file()
    assert (output / "build-result.json").is_file()
    assert len(list((output / "control/ring-assignments").glob("*.json"))) == 3
    assert sha256_digest((output / "build-result.json").read_bytes()) == build.result_file_digest

    with pytest.raises(VocabularyAtlasV1ReleaseError, match="already exists"):
        build_vocabulary_atlas_v1_release(
            definition,
            artifact_root=definition_path.parents[1],
            output_directory=output,
        )
