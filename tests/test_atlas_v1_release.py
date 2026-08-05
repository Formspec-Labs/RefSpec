"""The v1 builder seals and assembles six exact releases from tiny fixtures."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import refspec.atlas.model as atlas_model
import refspec.atlas.v1_release as v1_module
from refspec.atlas import qualification as qual
from refspec.atlas import qualification_batch as qbatch
from refspec.atlas import release_acceptance
from refspec.atlas.concept_release import PinnedSourceConceptRelease
from refspec.atlas.model import CrosswalkBundle
from refspec.atlas.relation_assertion import RelationAssertionBundle
from refspec.atlas.v1_release import (
    VocabularyAtlasV1ReleaseDefinition,
    VocabularyAtlasV1ReleaseError,
    build_vocabulary_atlas_v1_release,
    open_vocabulary_atlas_v1_build,
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
) -> tuple[Path, Path, Path, dict[str, Any]]:
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
    return index_path, input_path, catalog_path, index


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


def _patch_managed_release_openers(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixtureFederalRegisterView:
        relations = tuple(
            {"resolutionStatus": status}
            for status, count in (
                ("resolved", 1_451),
                ("suggestedOpenTermPattern", 11),
                ("unresolved", 1),
            )
            for _ in range(count)
        )

        @classmethod
        def open(cls, _path: Path) -> FixtureFederalRegisterView:
            return cls()

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
    monkeypatch.setattr(
        v1_module,
        "FederalRegisterThesaurus2025ManagedReleaseView",
        FixtureFederalRegisterView,
    )


def _qualification_run(
    root: Path,
    *,
    job: str,
    source: PinnedSourceConceptRelease,
    target: PinnedSourceConceptRelease,
    production: bool,
) -> dict[str, str]:
    mode = "production" if production else "baseline"
    run_root = root / "qualification" / mode / job
    run_root.mkdir(parents=True)
    bundle = CrosswalkBundle.create(
        artifacts=(),
        mapping_candidates=(),
    )
    bundle_path = bundle.write(run_root / "crosswalk-v2.json")
    bundle_pin = bundle.pin()
    coverage = qual.PRODUCTION_COVERAGE_MODE if production else qual.PILOT_COVERAGE_MODE
    generation_policy = (
        qual.PRODUCTION_CANDIDATE_GENERATION_POLICY if production else qual.PILOT_CANDIDATE_GENERATION_POLICY
    )
    candidates_path = _write(
        run_root / "candidates.json",
        canonical_json_bytes(
            {
                "candidates": [],
                "coverageMode": coverage,
                "generationPolicy": generation_policy,
            }
        ),
    )
    judge_path = _write(run_root / "receipts.jsonl", b"")
    scoring_path = _write(run_root / "scoring-receipts.jsonl", b"")
    counts = {
        "generated": 0,
        "scored": 0,
        "scorerReceipts": 0,
        "judgeReceipts": 0,
        "judged": 0,
        "abstained": 0,
        "rejected": 0,
        "controlled": 0,
        "admitted": 0,
        "incomplete": 0,
    }
    receipt = qual.seal_qualification_run_receipt(
        {
            "type": qual.QUALIFICATION_RUN_RECEIPT_TYPE,
            "schemaVersion": qual.QUALIFICATION_RUN_RECEIPT_VERSION,
            "bundle": {
                "file": bundle_path.name,
                "fileDigest": bundle_pin["fileDigest"],
                "id": bundle_pin["id"],
                "bundleDigest": bundle_pin["digest"],
                "mediaType": bundle_pin["mediaType"],
            },
            "coverageMode": coverage,
            "candidateGenerationPolicy": generation_policy,
            "productionFloor": qual.PRODUCTION_FLOOR if production else None,
            "candidateCatalog": {
                "file": candidates_path.name,
                "fileDigest": sha256_digest(candidates_path.read_bytes()),
                "total": 0,
            },
            "receiptLog": {
                "file": judge_path.name,
                "fileDigest": sha256_digest(judge_path.read_bytes()),
                "total": 0,
            },
            "scoring": {
                "status": "complete" if production else "notRun",
                "protocol": qual.SCORING_PROTOCOL,
                "receiptLog": {
                    "file": scoring_path.name,
                    "fileDigest": sha256_digest(scoring_path.read_bytes()),
                    "total": 0,
                },
            },
            "candidateAccounting": [],
            "counts": counts,
            "sourceManifestDigest": source.manifest_digest,
            "targetManifestDigest": target.manifest_digest,
        }
    )
    receipt_path = _write(
        run_root / "qualification-run.json",
        canonical_json_bytes(receipt),
    )
    return {
        "job": job,
        "sourceReleaseId": source.release_id,
        "targetReleaseId": target.release_id,
        "runReceiptPath": _relative(root, receipt_path),
        "runReceiptFileDigest": sha256_digest(receipt_path.read_bytes()),
        "runReceiptContentDigest": cast(str, receipt["contentDigest"]),
    }


def _definition_fixture(
    tmp_path: Path,
) -> tuple[Path, VocabularyAtlasV1ReleaseDefinition]:
    root = tmp_path / "artifacts"
    root.mkdir()
    specs = [
        (
            "crs-subjects",
            "crsLegislativeSubjects",
            "sourceConceptRelease",
            "subject",
        ),
        ("crs-policy", "crsPolicyAreas", "sourceConceptRelease", "subject"),
        ("crs-entities", "crsEntities", "sourceConceptRelease", "entity"),
        ("elsst", "elsst", "managedConceptRelease", "subject"),
        (
            "federal-register",
            "federalRegisterThesaurus",
            "federalRegisterManagedConceptRelease",
            "subject",
        ),
        ("icpsr", "icpsr", "icpsrManagedConceptRelease", "subject"),
    ]
    release_rows: list[dict[str, Any]] = []
    pinned_rows: list[tuple[str, PinnedSourceConceptRelease]] = []
    concept_ids: dict[str, str] = {}
    for key, role, kind, ring in specs:
        release, pinned, concept_id = _source_release(
            root,
            key,
            ring=cast(SemanticRing, ring),
        )
        pinned_rows.append((key, pinned))
        concept_ids[key] = concept_id
        row: dict[str, Any] = {
            "key": key,
            "v1Role": role,
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

    index_path, index_input_path, catalog_path, index = _planning_index(root, pinned_rows)
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
    qualification_pairs = {
        "federal-register-elsst": ("federal-register", "elsst"),
        "federal-register-icpsr": ("federal-register", "icpsr"),
        "elsst-icpsr": ("elsst", "icpsr"),
        "crs-subjects-federal-register": (
            "crs-subjects",
            "federal-register",
        ),
        "crs-policy-federal-register": ("crs-policy", "federal-register"),
        "crs-subjects-crs-policy": ("crs-subjects", "crs-policy"),
    }
    baseline_runs = [
        _qualification_run(
            root,
            job=job,
            source=source[source_key],
            target=source[target_key],
            production=False,
        )
        for job, (source_key, target_key) in qualification_pairs.items()
        if job
        in {
            "federal-register-elsst",
            "federal-register-icpsr",
            "elsst-icpsr",
        }
    ]
    policy_digest = sha256_digest(b"v1-test-policy")
    development_statement = "This exact ICPSR fixture remains explicitly marked developmentOnly."
    basis = {
        "type": "VocabularyAtlasV1ReleaseDefinition",
        "schemaVersion": "2.0",
        "releaseMode": "baselineEvidenceRc",
        "releaseName": "urn:ref:test:vocabulary-atlas:v1",
        "scopeName": "urn:ref:test:vocabulary-atlas:v1:baseline-scope",
        "scopeKind": "bench",
        "title": "Tiny Vocabulary Atlas baseline evidence RC",
        "planningIndex": {
            "path": _relative(root, index_path),
            "fileDigest": sha256_digest(index_path.read_bytes()),
            "inputPath": _relative(root, index_input_path),
            "inputFileDigest": sha256_digest(index_input_path.read_bytes()),
            "resourceCatalogPath": _relative(root, catalog_path),
            "resourceCatalogFileDigest": sha256_digest(catalog_path.read_bytes()),
            "repositoryRoot": ".",
        },
        "reviewedSearchCorpus": {"status": "skippedPublicOnly"},
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
        "productionQualificationRuns": [],
        "baselineQualificationRuns": baseline_runs,
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
            "exceptions": [
                {
                    "kind": "developmentOnly",
                    "appliesTo": release_ids["icpsr"],
                    "statement": development_statement,
                }
            ],
            "supersedes": [],
            "sourceApprovals": [
                {
                    "releaseId": row["releaseId"],
                    "manifestDigest": row["manifestDigest"],
                    "semanticRing": row["semanticRing"],
                    "disposition": "approved",
                    "conditions": (
                        [
                            {
                                "kind": "developmentOnly",
                                "statement": development_statement,
                            }
                        ]
                        if row["v1Role"] == "icpsr"
                        else []
                    ),
                }
                for row in release_rows
            ],
            "rowDispositions": [
                {
                    "rowId": row["rowId"],
                    "rowDigest": row["rowDigest"],
                    "disposition": "included",
                    "reason": "Included in the exact tiny v1 scope.",
                }
                for row in cast(list[dict[str, Any]], index["rows"])
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


def _definition_basis(
    definition: VocabularyAtlasV1ReleaseDefinition,
) -> dict[str, Any]:
    record = definition.as_record()
    record.pop("id")
    record.pop("recordDigest")
    return record


def _tiny_public_basis(
    sealed: VocabularyAtlasV1ReleaseDefinition,
) -> dict[str, Any]:
    basis = _definition_basis(sealed)
    basis["releaseMode"] = "publicV1"
    basis["scopeKind"] = "published"
    basis["reviewedSearchCorpus"] = {
        "status": "required",
        "path": v1_module._PUBLIC_V1_EXPLORER_SEARCH_CORPUS_PATH,
        "fileDigest": v1_module._PUBLIC_V1_EXPLORER_SEARCH_CORPUS_FILE_DIGEST,
    }
    release_ids = {row["v1Role"]: row["releaseId"] for row in basis["releases"]}
    basis["productionQualificationRuns"] = [
        {
            "job": job,
            "sourceReleaseId": release_ids[source_role],
            "targetReleaseId": release_ids[target_role],
            "runReceiptPath": f"qualification/production/{job}/qualification-run.json",
            "runReceiptFileDigest": "sha256:" + "0" * 64,
            "runReceiptContentDigest": "sha256:" + "1" * 64,
        }
        for job, (source_role, target_role) in sorted(v1_module._PRODUCTION_JOB_ROLES.items())
    ]
    return basis


def _write_reopened_definition(
    root: Path,
    basis: dict[str, Any],
    name: str,
) -> VocabularyAtlasV1ReleaseDefinition:
    sealed = VocabularyAtlasV1ReleaseDefinition.seal(basis)
    path = sealed.write_to(root / "definitions" / name)
    return read_vocabulary_atlas_v1_release_definition(
        path,
        expected_file_digest=sha256_digest(path.read_bytes()),
    )


def test_definition_is_canonical_content_derived_and_exact(tmp_path: Path) -> None:
    definition_path, sealed = _definition_fixture(tmp_path)
    reopened = read_vocabulary_atlas_v1_release_definition(
        definition_path,
        expected_file_digest=sha256_digest(definition_path.read_bytes()),
    )

    assert reopened.identifier == sealed.identifier
    assert reopened.record_digest == sealed.record_digest
    assert len(reopened.record["releases"]) == 6
    assert reopened.record["scopeKind"] == "bench"
    assert reopened.record["reviewedSearchCorpus"] == {
        "status": "skippedPublicOnly"
    }

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


def test_definition_and_build_result_dispatch_legacy_and_current_shapes(
    tmp_path: Path,
) -> None:
    _definition_path, current = _definition_fixture(tmp_path)
    legacy_basis = _definition_basis(current)
    legacy_basis["schemaVersion"] = "1.0"
    legacy_basis.pop("reviewedSearchCorpus")
    legacy = VocabularyAtlasV1ReleaseDefinition.seal(legacy_basis)
    legacy_path = legacy.write_to(tmp_path / "definitions/legacy-v1.json")
    reopened = read_vocabulary_atlas_v1_release_definition(
        legacy_path,
        expected_file_digest=sha256_digest(legacy_path.read_bytes()),
    )

    assert reopened.record["schemaVersion"] == "1.0"
    assert "reviewedSearchCorpus" not in reopened.record
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="fields differ"):
        VocabularyAtlasV1ReleaseDefinition.seal(
            {**legacy_basis, "reviewedSearchCorpus": {"status": "skippedPublicOnly"}}
        )

    legacy_public_basis = _tiny_public_basis(current)
    legacy_public_basis["schemaVersion"] = "1.0"
    legacy_public_basis.pop("reviewedSearchCorpus")
    with pytest.raises(
        VocabularyAtlasV1ReleaseError,
        match="schemaVersion 1.0 is supported only for baselineEvidenceRc",
    ):
        VocabularyAtlasV1ReleaseDefinition.seal(legacy_public_basis)

    legacy_public_digest = sha256_digest(canonical_json_bytes(legacy_public_basis))
    legacy_public_path = _write(
        tmp_path / "definitions/fabricated-public-v1-schema.json",
        canonical_json_bytes(
            {
                **legacy_public_basis,
                "id": (v1_module._DEFINITION_ID_PREFIX + legacy_public_digest.removeprefix("sha256:")),
                "recordDigest": legacy_public_digest,
            }
        ),
    )
    with pytest.raises(
        VocabularyAtlasV1ReleaseError,
        match="schemaVersion 1.0 is supported only for baselineEvidenceRc",
    ):
        read_vocabulary_atlas_v1_release_definition(
            legacy_public_path,
            expected_file_digest=sha256_digest(legacy_public_path.read_bytes()),
        )

    current_result_basis = {
        field: {}
        for field in v1_module._BUILD_RESULT_BASIS_FIELDS
    }
    current_result_basis.update(
        {
            "type": "VocabularyAtlasV1BuildResult",
            "schemaVersion": "2.0",
            "releaseMode": "baselineEvidenceRc",
            "releaseName": "urn:ref:test:vocabulary-atlas:v1",
            "status": "baselineEvidenceOnly",
        }
    )
    current_result = v1_module._seal_build_result(current_result_basis)
    assert v1_module._validate_build_result(current_result)["schemaVersion"] == "2.0"

    legacy_result_basis = {
        field: value
        for field, value in current_result_basis.items()
        if field != "explorerAcceptance"
    }
    legacy_result_basis["schemaVersion"] = "1.0"
    legacy_result = v1_module._seal_build_result(legacy_result_basis)
    assert v1_module._validate_build_result(legacy_result)["schemaVersion"] == "1.0"
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="fields differ"):
        v1_module._validate_build_result(
            v1_module._seal_build_result(legacy_result_basis)
            | {"explorerAcceptance": {}}
        )


def test_schema_1_baseline_definition_builds_and_reopens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _definition_path, current = _definition_fixture(tmp_path)
    root = _definition_path.parents[1]
    legacy_basis = _definition_basis(current)
    legacy_basis["schemaVersion"] = "1.0"
    legacy_basis.pop("reviewedSearchCorpus")
    legacy = _write_reopened_definition(
        root,
        legacy_basis,
        "legacy-baseline-v1.json",
    )
    _patch_managed_release_openers(monkeypatch)

    output = tmp_path / "legacy-baseline-release"
    build = build_vocabulary_atlas_v1_release(
        legacy,
        artifact_root=root,
        output_directory=output,
    )
    reopened = open_vocabulary_atlas_v1_build(
        output,
        artifact_root=root,
        expected_result_file_digest=build.result_file_digest,
    )

    assert reopened.identifier == build.identifier
    assert build.result["releaseMode"] == "baselineEvidenceRc"
    assert build.result["explorerAcceptance"]["reviewedCorpus"] == {
        "status": "legacySchemaAbsent"
    }


def test_build_requires_reopened_definition_and_rechecks_source_bytes(
    tmp_path: Path,
) -> None:
    definition_path, sealed = _definition_fixture(tmp_path)
    output = tmp_path / "untrusted-definition-output"
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="path-backed definition"):
        build_vocabulary_atlas_v1_release(
            sealed,
            artifact_root=definition_path.parents[1],
            output_directory=output,
        )
    assert not output.exists()

    reopened = read_vocabulary_atlas_v1_release_definition(
        definition_path,
        expected_file_digest=sha256_digest(definition_path.read_bytes()),
    )
    definition_path.write_bytes(b"{}\n")
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="file digest differs"):
        build_vocabulary_atlas_v1_release(
            reopened,
            artifact_root=definition_path.parents[1],
            output_directory=output,
        )
    assert not output.exists()


def test_definition_requires_exact_reviewed_search_corpus_state(
    tmp_path: Path,
) -> None:
    _definition_path, sealed = _definition_fixture(tmp_path)
    missing = _definition_basis(sealed)
    missing.pop("reviewedSearchCorpus")
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="fields differ"):
        VocabularyAtlasV1ReleaseDefinition.seal(missing)

    baseline_with_public_pin = _definition_basis(sealed)
    baseline_with_public_pin["reviewedSearchCorpus"] = {
        "status": "required",
        "path": "research/search-corpus.json",
        "fileDigest": "sha256:" + "0" * 64,
    }
    with pytest.raises(
        VocabularyAtlasV1ReleaseError,
        match="reviewedSearchCorpus fields differ",
    ):
        VocabularyAtlasV1ReleaseDefinition.seal(baseline_with_public_pin)

    approved_public_pin = {
        "status": "required",
        "path": v1_module._PUBLIC_V1_EXPLORER_SEARCH_CORPUS_PATH,
        "fileDigest": v1_module._PUBLIC_V1_EXPLORER_SEARCH_CORPUS_FILE_DIGEST,
    }
    assert v1_module._normalize_reviewed_search_corpus(
        approved_public_pin,
        release_mode="publicV1",
    ) == approved_public_pin
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="fileDigest"):
        v1_module._normalize_reviewed_search_corpus(
            {**approved_public_pin, "fileDigest": "not-a-digest"},
            release_mode="publicV1",
        )
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="relative path"):
        v1_module._normalize_reviewed_search_corpus(
            {**approved_public_pin, "path": "../outside.json"},
            release_mode="publicV1",
        )


def test_reviewed_search_corpus_is_reopened_from_its_definition_pin(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path / "research/search-corpus.json",
        canonical_json_bytes({"review": "first"}),
    )
    digest = sha256_digest(path.read_bytes())
    definition = SimpleNamespace(
        record={
            "releaseMode": "publicV1",
            "reviewedSearchCorpus": {
                "status": "required",
                "path": "research/search-corpus.json",
                "fileDigest": digest,
            },
        }
    )
    corpus, descriptor = v1_module._open_reviewed_search_corpus(
        definition,
        tmp_path.resolve(),
    )
    assert corpus == {"review": "first"}
    assert descriptor["fileDigest"] == digest

    path.write_bytes(canonical_json_bytes({"review": "changed"}))
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="exact digest"):
        v1_module._open_reviewed_search_corpus(
            definition,
            tmp_path.resolve(),
        )


def test_public_builder_checks_reject_a_nonpassed_explorer_gate() -> None:
    definition = SimpleNamespace(record={"releaseMode": "publicV1"})
    explorer_acceptance = SimpleNamespace(
        record={"status": "measuredBaselineOnly"}
    )
    with pytest.raises(
        VocabularyAtlasV1ReleaseError,
        match="status differs from its release mode",
    ):
        v1_module._builder_acceptance_checks(
            definition,
            index=SimpleNamespace(),
            scope=SimpleNamespace(),
            atlas=SimpleNamespace(),
            decision=SimpleNamespace(),
            publication=SimpleNamespace(),
            explorer_acceptance=explorer_acceptance,
            qualification_runs=[],
            federal_register_reconciliation={"counts": {}},
        )


def test_exact_json_decodes_the_digest_verified_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write(tmp_path / "changed.json", canonical_json_bytes({"value": "changed"}))
    verified_payload = canonical_json_bytes({"value": "verified"})
    monkeypatch.setattr(
        v1_module,
        "_exact_file_bytes",
        lambda *args, **kwargs: (path, verified_payload),
    )

    assert v1_module._exact_json(
        tmp_path,
        "changed.json",
        sha256_digest(verified_payload),
        label="verified JSON",
    ) == {"value": "verified"}


def test_definition_requires_all_approvals_icpsr_condition_and_public_profile(
    tmp_path: Path,
) -> None:
    _definition_path, sealed = _definition_fixture(tmp_path)
    missing_approval = _definition_basis(sealed)
    missing_approval["publication"]["sourceApprovals"].pop()
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="every and only included release"):
        VocabularyAtlasV1ReleaseDefinition.seal(missing_approval)

    missing_development = _definition_basis(sealed)
    missing_development["publication"]["exceptions"] = []
    icpsr_release_id = next(
        release["releaseId"] for release in missing_development["releases"] if release["v1Role"] == "icpsr"
    )
    icpsr_approval = next(
        approval
        for approval in missing_development["publication"]["sourceApprovals"]
        if approval["releaseId"] == icpsr_release_id
    )
    icpsr_approval["conditions"] = []
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="developmentOnly"):
        VocabularyAtlasV1ReleaseDefinition.seal(missing_development)

    missing_job = _tiny_public_basis(sealed)
    missing_job["productionQualificationRuns"].pop()
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="every required job"):
        VocabularyAtlasV1ReleaseDefinition.seal(missing_job)

    tiny_public = _tiny_public_basis(sealed)
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="exact approved 87-row"):
        VocabularyAtlasV1ReleaseDefinition.seal(tiny_public)


def test_public_mapping_closure_preserves_same_pair_with_distinct_proofs() -> None:
    proof_one = "urn:ref:test:proof:one"
    proof_two = "urn:ref:test:proof:two"
    evidence = {
        "urn:ref:test:evidence:one": SimpleNamespace(
            evidence_class="machineQualified",
            machine_proof=proof_one,
        ),
        "urn:ref:test:evidence:two": SimpleNamespace(
            evidence_class="machineQualified",
            machine_proof=proof_two,
        ),
    }
    shared = {
        "source_concept": "urn:ref:test:concept:source",
        "target_concept": "urn:ref:test:concept:target",
        "source_release": "urn:ref:test:release:source",
        "target_release": "urn:ref:test:release:target",
        "relation": SUBJECT_EXACT_MATCH,
    }
    first = SimpleNamespace(
        **shared,
        evidence=("urn:ref:test:evidence:one",),
    )
    second = SimpleNamespace(
        **shared,
        evidence=("urn:ref:test:evidence:two",),
    )
    used: set[str] = set()
    for mapping in (first, second):
        v1_module._record_public_mapping_proof(
            mapping,
            evidence_by_id=evidence,
            approved_proof_ids={proof_one, proof_two},
            used_proof_ids=used,
        )
    assert used == {proof_one, proof_two}

    with pytest.raises(VocabularyAtlasV1ReleaseError, match="reuse"):
        v1_module._record_public_mapping_proof(
            first,
            evidence_by_id=evidence,
            approved_proof_ids={proof_one, proof_two},
            used_proof_ids=used,
        )


def test_build_refuses_incomplete_row_controls_and_nonproduction_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition_path, sealed = _definition_fixture(tmp_path)
    root = definition_path.parents[1]
    _patch_managed_release_openers(monkeypatch)

    missing_row_basis = _definition_basis(sealed)
    missing_row_basis["publication"]["rowDispositions"].pop()
    missing_row = _write_reopened_definition(
        root,
        missing_row_basis,
        "missing-row-disposition.json",
    )
    missing_row_output = tmp_path / "missing-row-output"
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="dispose every exact"):
        build_vocabulary_atlas_v1_release(
            missing_row,
            artifact_root=root,
            output_directory=missing_row_output,
        )
    assert not missing_row_output.exists()

    assignment_directory = tmp_path / "nonproduction-assignments"
    assignment_directory.mkdir()
    _scope_releases, release_sources, _labels = v1_module._open_releases(
        sealed,
        root,
        assignment_directory,
    )
    baseline_row = cast(list[dict[str, Any]], sealed.record["baselineQualificationRuns"])[0]
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="wrong coverage mode"):
        v1_module._verify_pair_qualification_run(
            baseline_row,
            root=root,
            releases=release_sources,
            production=True,
        )


def test_v1_qualification_reopen_recomputes_provider_batch_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _definition_path, sealed = _definition_fixture(tmp_path)
    root = _definition_path.parents[1]
    _patch_managed_release_openers(monkeypatch)
    assignment_directory = tmp_path / "batch-evidence-assignments"
    assignment_directory.mkdir()
    _scope_releases, release_sources, _labels = v1_module._open_releases(
        sealed,
        root,
        assignment_directory,
    )
    descriptor = dict(cast(list[dict[str, Any]], sealed.record["baselineQualificationRuns"])[0])
    run_path = root / cast(str, descriptor["runReceiptPath"])
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run.pop("id")
    run.pop("contentDigest")
    run["providerBatchEvidence"] = {
        "judging": {
            "file": "judging-batch-sidecar.json",
            "fileDigest": "sha256:" + "a" * 64,
            "protocol": qbatch.SIDECAR_PROTOCOL,
            "verification": {
                "candidateRequests": 0,
                "jobs": 0,
                "providerRequests": 0,
                "workKind": "validation",
            },
        }
    }
    sealed_run = qual.seal_qualification_run_receipt(run)
    run_path.write_bytes(canonical_json_bytes(sealed_run))
    descriptor["runReceiptFileDigest"] = sha256_digest(run_path.read_bytes())
    descriptor["runReceiptContentDigest"] = sealed_run["contentDigest"]

    def reject_batch_evidence(_path: Path, _run: Mapping[str, Any]) -> dict[str, Any]:
        raise qbatch.BatchError("provider batch raw artifact changed")

    monkeypatch.setattr(qbatch, "verify_run_provider_batch_evidence", reject_batch_evidence)
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="provider batch raw artifact changed"):
        v1_module._verify_pair_qualification_run(
            descriptor,
            root=root,
            releases=release_sources,
            production=False,
        )


def test_public_v1_qualification_requires_both_batch_evidence_roads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _definition_path, sealed = _definition_fixture(tmp_path)
    root = _definition_path.parents[1]
    _patch_managed_release_openers(monkeypatch)
    assignment_directory = tmp_path / "production-batch-assignments"
    assignment_directory.mkdir()
    _scope_releases, release_sources, _labels = v1_module._open_releases(
        sealed,
        root,
        assignment_directory,
    )
    baseline = cast(list[dict[str, Any]], sealed.record["baselineQualificationRuns"])[0]
    job = cast(str, baseline["job"])
    descriptor = _qualification_run(
        root,
        job=job,
        source=release_sources[cast(str, baseline["sourceReleaseId"])],
        target=release_sources[cast(str, baseline["targetReleaseId"])],
        production=True,
    )
    run_path = root / descriptor["runReceiptPath"]
    run = json.loads(run_path.read_text(encoding="utf-8"))
    catalog = cast(dict[str, Any], run["candidateCatalog"])
    monkeypatch.setattr(
        v1_module,
        "_PUBLIC_V1_PRODUCTION_CATALOGS",
        {job: (0, catalog["fileDigest"])},
    )

    with pytest.raises(
        VocabularyAtlasV1ReleaseError,
        match="must pin judging and scoring provider batch evidence",
    ):
        v1_module._verify_pair_qualification_run(
            descriptor,
            root=root,
            releases=release_sources,
            production=True,
        )


def test_public_v1_qualification_reopen_rejects_control_relabel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _definition_path, sealed = _definition_fixture(tmp_path)
    root = _definition_path.parents[1]
    _patch_managed_release_openers(monkeypatch)
    assignment_directory = tmp_path / "production-lineage-assignments"
    assignment_directory.mkdir()
    _scope_releases, release_sources, _labels = v1_module._open_releases(
        sealed,
        root,
        assignment_directory,
    )
    baseline = cast(
        list[dict[str, Any]],
        sealed.record["baselineQualificationRuns"],
    )[0]
    job = cast(str, baseline["job"])
    descriptor = _qualification_run(
        root,
        job=job,
        source=release_sources[cast(str, baseline["sourceReleaseId"])],
        target=release_sources[cast(str, baseline["targetReleaseId"])],
        production=True,
    )
    run_path = root / descriptor["runReceiptPath"]
    run = json.loads(run_path.read_text(encoding="utf-8"))
    candidate_id = "urn:ref:test:candidate:genuine"
    catalog_path = run_path.parent / run["candidateCatalog"]["file"]
    catalog = {
        "candidates": [
            {
                "candidateId": candidate_id,
                "generationClass": "normalizedLabelEquality",
            }
        ],
        "coverageMode": qual.PRODUCTION_COVERAGE_MODE,
        "generationPolicy": qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
    }
    catalog_path.write_bytes(canonical_json_bytes(catalog))
    catalog_digest = sha256_digest(catalog_path.read_bytes())
    run["candidateCatalog"] = {
        "file": catalog_path.name,
        "fileDigest": catalog_digest,
        "total": 1,
    }
    run["candidateAccounting"] = [
        {
            "candidateId": candidate_id,
            "generationClass": "randomNegativeControl",
            "control": True,
            "disposition": "controlled",
            "judgeReceipts": [],
            "judged": False,
            "scorerReceipts": [],
            "scored": False,
        }
    ]
    run["counts"] = {
        **run["counts"],
        "generated": 1,
        "controlled": 1,
    }
    run["providerBatchEvidence"] = {"judging": {}, "scoring": {}}
    run["contentDigest"] = "sha256:" + "9" * 64
    descriptor["runReceiptContentDigest"] = run["contentDigest"]
    monkeypatch.setattr(
        qual,
        "validate_qualification_run_receipt",
        lambda _record: run,
    )
    monkeypatch.setattr(
        qbatch,
        "verify_run_provider_batch_evidence",
        lambda _path, _run: {},
    )
    monkeypatch.setattr(
        v1_module,
        "_PUBLIC_V1_PRODUCTION_CATALOGS",
        {job: (1, catalog_digest)},
    )

    class CandidateBundle:
        identifier = run["bundle"]["id"]

        @staticmethod
        def to_dict() -> dict[str, Any]:
            return {
                "mappingCandidates": [
                    {
                        "id": candidate_id,
                        "sourceRelease": descriptor["sourceReleaseId"],
                        "targetRelease": descriptor["targetReleaseId"],
                    }
                ]
            }

    monkeypatch.setattr(
        v1_module.CrosswalkBundle,
        "open",
        lambda *_args, **_kwargs: CandidateBundle(),
    )
    with pytest.raises(
        VocabularyAtlasV1ReleaseError,
        match="generation class differs from its exact catalog row",
    ):
        v1_module._verify_pair_qualification_run(
            descriptor,
            root=root,
            releases=release_sources,
            production=True,
        )


def test_public_v1_qualification_reopen_rejects_erased_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _definition_path, sealed = _definition_fixture(tmp_path)
    root = _definition_path.parents[1]
    _patch_managed_release_openers(monkeypatch)
    assignment_directory = tmp_path / "production-admission-assignments"
    assignment_directory.mkdir()
    _scope_releases, release_sources, _labels = v1_module._open_releases(
        sealed,
        root,
        assignment_directory,
    )
    baseline = cast(
        list[dict[str, Any]],
        sealed.record["baselineQualificationRuns"],
    )[0]
    job = cast(str, baseline["job"])
    descriptor = _qualification_run(
        root,
        job=job,
        source=release_sources[cast(str, baseline["sourceReleaseId"])],
        target=release_sources[cast(str, baseline["targetReleaseId"])],
        production=True,
    )
    run_path = root / descriptor["runReceiptPath"]
    run = json.loads(run_path.read_text(encoding="utf-8"))
    candidate_id = "urn:ref:test:candidate:erased-admission"
    catalog_path = run_path.parent / run["candidateCatalog"]["file"]
    catalog = {
        "candidates": [
            {
                "candidateId": candidate_id,
                "generationClass": "normalizedLabelEquality",
            }
        ],
        "coverageMode": qual.PRODUCTION_COVERAGE_MODE,
        "generationPolicy": qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
    }
    catalog_path.write_bytes(canonical_json_bytes(catalog))
    catalog_digest = sha256_digest(catalog_path.read_bytes())
    run["candidateCatalog"] = {
        "file": catalog_path.name,
        "fileDigest": catalog_digest,
        "total": 1,
    }
    run["candidateAccounting"] = [
        {
            "candidateId": candidate_id,
            "generationClass": "normalizedLabelEquality",
            "control": False,
            "disposition": "rejected",
            "judgeReceipts": [],
            "judged": False,
            "scorerReceipts": [],
            "scored": False,
        }
    ]
    run["counts"] = {
        **run["counts"],
        "generated": 1,
        "rejected": 1,
    }
    run["providerBatchEvidence"] = {"judging": {}, "scoring": {}}
    monkeypatch.setattr(
        qual,
        "validate_qualification_run_receipt",
        lambda _record: run,
    )
    monkeypatch.setattr(
        qbatch,
        "verify_run_provider_batch_evidence",
        lambda _path, _run: {},
    )
    monkeypatch.setattr(
        v1_module,
        "_PUBLIC_V1_PRODUCTION_CATALOGS",
        {job: (1, catalog_digest)},
    )

    class CandidateBundle:
        identifier = run["bundle"]["id"]

        @staticmethod
        def to_dict() -> dict[str, Any]:
            return {
                "mappingCandidates": [
                    {
                        "id": candidate_id,
                        "sourceRelease": descriptor["sourceReleaseId"],
                        "targetRelease": descriptor["targetReleaseId"],
                    }
                ]
            }

        @staticmethod
        def adjudicated_relations() -> dict[str, str]:
            return {candidate_id: SUBJECT_EXACT_MATCH}

    monkeypatch.setattr(
        v1_module.CrosswalkBundle,
        "open",
        lambda *_args, **_kwargs: CandidateBundle(),
    )
    with pytest.raises(
        VocabularyAtlasV1ReleaseError,
        match="Crosswalk adjudications differ from run admissions",
    ):
        v1_module._verify_pair_qualification_run(
            descriptor,
            root=root,
            releases=release_sources,
            production=True,
        )


def test_baseline_rc_is_a_bench_preview_never_a_passed_public_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition_path, sealed = _definition_fixture(tmp_path)
    root = definition_path.parents[1]
    basis = _definition_basis(sealed)
    basis["releaseMode"] = "baselineEvidenceRc"
    basis["scopeKind"] = "bench"
    basis["title"] = "Tiny Vocabulary Atlas baseline evidence RC"
    basis["productionQualificationRuns"] = []
    definition = _write_reopened_definition(
        root,
        basis,
        "baseline-evidence-rc.json",
    )
    _patch_managed_release_openers(monkeypatch)

    output = tmp_path / "baseline-evidence-rc"
    build = build_vocabulary_atlas_v1_release(
        definition,
        artifact_root=root,
        output_directory=output,
    )

    assert build.result["releaseMode"] == "baselineEvidenceRc"
    assert build.result["status"] == "baselineEvidenceOnly"
    assert build.result["publication"]["role"] == "baselineEvidencePreview"
    assert (output / "baseline-preview/publication-manifest.json").is_file()
    assert not (output / "public").exists()
    assert all(run["runKind"] == "baselineEvidence" for run in build.result["qualificationRuns"])


def test_failed_post_placement_reopen_removes_the_new_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition_path, _sealed = _definition_fixture(tmp_path)
    definition = read_vocabulary_atlas_v1_release_definition(
        definition_path,
        expected_file_digest=sha256_digest(definition_path.read_bytes()),
    )
    _patch_managed_release_openers(monkeypatch)

    def refuse_reopen(*args: object, **kwargs: object) -> object:
        raise VocabularyAtlasV1ReleaseError("injected post-placement failure")

    monkeypatch.setattr(v1_module, "open_vocabulary_atlas_v1_build", refuse_reopen)
    output = tmp_path / "failed-after-placement"
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="post-placement"):
        build_vocabulary_atlas_v1_release(
            definition,
            artifact_root=definition_path.parents[1],
            output_directory=output,
        )
    assert not output.exists()


def test_builder_uses_three_equivalent_atlas_generations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition_path, _sealed = _definition_fixture(tmp_path)
    definition = read_vocabulary_atlas_v1_release_definition(
        definition_path,
        expected_file_digest=sha256_digest(definition_path.read_bytes()),
    )
    _patch_managed_release_openers(monkeypatch)

    generation_roles: list[str] = []
    generated_distributions: list[tuple[bytes, bytes, bytes]] = []
    original_resolved_build = atlas_model._build_resolved_atlas_v2
    original_producer_build = v1_module.build_vocabulary_atlas
    original_acceptance_build = release_acceptance.build_vocabulary_atlas

    def record_generation(resolved: Any) -> Any:
        atlas = original_resolved_build(resolved)
        generated_distributions.append(
            (atlas.payload, atlas.scope_payload, atlas.manifest_bytes())
        )
        return atlas

    def build_producer_atlas(scope: Any) -> Any:
        generation_roles.append("producer")
        return original_producer_build(scope)

    def build_acceptance_atlas(scope: Any) -> Any:
        generation_roles.append("acceptance")
        return original_acceptance_build(scope)

    monkeypatch.setattr(
        atlas_model,
        "_build_resolved_atlas_v2",
        record_generation,
    )
    monkeypatch.setattr(
        v1_module,
        "build_vocabulary_atlas",
        build_producer_atlas,
    )
    monkeypatch.setattr(
        release_acceptance,
        "build_vocabulary_atlas",
        build_acceptance_atlas,
    )

    output = tmp_path / "three-generation-release"
    build_vocabulary_atlas_v1_release(
        definition,
        artifact_root=definition_path.parents[1],
        output_directory=output,
    )

    assert generation_roles == ["producer", "acceptance", "acceptance"]
    assert len(generated_distributions) == 3
    assert generated_distributions == [generated_distributions[0]] * 3


def test_builder_dispatches_all_release_kinds_and_seals_baseline_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition_path, _ = _definition_fixture(tmp_path)
    definition = read_vocabulary_atlas_v1_release_definition(
        definition_path,
        expected_file_digest=sha256_digest(definition_path.read_bytes()),
    )
    _patch_managed_release_openers(monkeypatch)

    output = tmp_path / "baseline-release"
    build = build_vocabulary_atlas_v1_release(
        definition,
        artifact_root=definition_path.parents[1],
        output_directory=output,
    )

    assert build.output_directory == output.resolve()
    assert build.result["status"] == "baselineEvidenceOnly"
    assert build.result["counts"]["concepts"]["total"] == 6
    assert build.result["counts"]["mappingAssertions"]["total"] == 1
    assert build.result["counts"]["facets"]["rowCount"] == 6
    assert build.result["releaseMode"] == "baselineEvidenceRc"
    assert build.result["status"] == "baselineEvidenceOnly"
    assert len(build.result["qualificationRuns"]) == 3
    assert all(run["counts"]["admitted"] == 0 for run in build.result["qualificationRuns"])
    assert (output / "canonical/atlas.nq").is_file()
    assert (output / "baseline-preview/publication-manifest.json").is_file()
    assert not (output / "public").exists()
    assert (output / "control/release-definition.json").read_bytes() == definition_path.read_bytes()
    assert (output / "control/explorer-acceptance.json").is_file()
    assert (output / "control/release-acceptance.json").is_file()
    assert (output / "build-result.json").is_file()
    assert len(list((output / "control/ring-assignments").glob("*.json"))) == 3
    assert sha256_digest((output / "build-result.json").read_bytes()) == build.result_file_digest

    reopened = open_vocabulary_atlas_v1_build(
        output,
        artifact_root=definition_path.parents[1],
        expected_result_file_digest=build.result_file_digest,
    )
    assert reopened.identifier == build.identifier

    acceptance_record = json.loads((output / "control/release-acceptance.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in acceptance_record["checks"]] == [
        "urn:ref:check:vocabulary-atlas-v1:canonical-reproduction",
        "urn:ref:check:vocabulary-atlas-v1:definition-and-controls",
        "urn:ref:check:vocabulary-atlas-v1:explorer-acceptance",
        "urn:ref:check:vocabulary-atlas-v1:federal-register-related-reconciliation",
        "urn:ref:check:vocabulary-atlas-v1:publication-reopen",
        "urn:ref:check:vocabulary-atlas-v1:qualification-accounting",
    ]
    explorer_acceptance = json.loads(
        (output / "control/explorer-acceptance.json").read_text(encoding="utf-8")
    )
    assert explorer_acceptance["status"] == "measuredBaselineOnly"
    assert explorer_acceptance["search"]["status"] == "skippedPublicOnly"
    assert build.result["explorerAcceptance"] == {
        "id": explorer_acceptance["id"],
        "recordDigest": explorer_acceptance["recordDigest"],
        "fileDigest": sha256_digest(
            (output / "control/explorer-acceptance.json").read_bytes()
        ),
        "reviewedCorpus": {"status": "skippedPublicOnly"},
    }
    assert build.result["sourceReconciliations"][0]["counts"] == {
        "resolvedConceptLinks": 1_451,
        "sourceReferenceTotal": 1_463,
        "suggestedOpenTermPatterns": 11,
        "unresolvedTargets": 1,
    }

    atlas_path = output / "canonical/atlas.nq"
    atlas_payload = atlas_path.read_bytes()
    atlas_path.write_bytes(atlas_payload + b"# changed\n")
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="artifact canonical/atlas.nq differs"):
        open_vocabulary_atlas_v1_build(
            output,
            artifact_root=definition_path.parents[1],
            expected_result_file_digest=build.result_file_digest,
        )
    atlas_path.write_bytes(atlas_payload)

    (output / "unlisted.txt").write_text("not part of the release\n", encoding="utf-8")
    with pytest.raises(VocabularyAtlasV1ReleaseError, match="unlisted, or extra"):
        open_vocabulary_atlas_v1_build(
            output,
            artifact_root=definition_path.parents[1],
            expected_result_file_digest=build.result_file_digest,
        )

    with pytest.raises(VocabularyAtlasV1ReleaseError, match="already exists"):
        build_vocabulary_atlas_v1_release(
            definition,
            artifact_root=definition_path.parents[1],
            output_directory=output,
        )
