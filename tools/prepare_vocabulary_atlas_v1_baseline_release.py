#!/usr/bin/env python3
"""Prepare the exact local Vocabulary Atlas v1 baseline-evidence definition.

This command reads and closes the existing six release packages, 87-row
planning index, three preserved qualification runs, three relation bundles,
and 582 admitted Crosswalk proofs. It performs local reads and one definition
write only. It never calls a model provider or publishes a release.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from refspec import binding
from refspec.atlas.v1_release import (
    VocabularyAtlasV1ReleaseDefinition,
    read_vocabulary_atlas_v1_release_definition,
)
from refspec.registry.infrastructure.artifact_serialization import sha256_digest
from refspec.registry.infrastructure.semantic_foundation import (
    SUBJECT_BROAD_MATCH,
    SUBJECT_CLOSE_MATCH,
    SUBJECT_EXACT_MATCH,
    SUBJECT_NARROW_MATCH,
    SUBJECT_RELATED_MATCH,
)
from refspec.storage import canonical_json

DEFAULT_OUTPUT = (
    ROOT
    / "output/vocabulary-atlas-v1-rc1/control/release-definitions/"
    "vocabulary-atlas-v1-baseline-evidence-rc1.json"
)

DECISION_ACTOR = "urn:ref:actor:vocabulary-atlas-v1-release-review"
DECIDED_AT = "2026-08-04T23:00:00Z"
ASSIGNED_AT = "2026-08-04T22:00:00Z"

PLANNING_INDEX = {
    "path": "portfolio/atlas-index-v0.json",
    "fileDigest": "sha256:c84657233253289530aaf43c58ae7d8098a1887630bffa8fe79590d945b4a386",
    "inputPath": "portfolio/atlas-index-input-v0.json",
    "inputFileDigest": "sha256:aeeedc35c99bb8a7ac6185ff323b8d8306f5a359aab46288a2fa102cef9e9d5c",
    "resourceCatalogPath": "portfolio/resource-catalog-v0.json",
    "resourceCatalogFileDigest": "sha256:f0f6be90ae4017187242561af837e3642dab80bff9371082bcdcfaf0b03a94d7",
    "repositoryRoot": ".",
}

QUALIFICATION_POLICY_PATH = (
    "portfolio/vocabulary-atlas-v1-production-qualification-jobs.json"
)
QUALIFICATION_JOBS_FILE_DIGEST = (
    "sha256:139ba47726520d4ca73a14dad4e35453f1b37f9f90965e873d9386b27d748370"
)
QUALIFICATION_POLICY_DIGEST = (
    "sha256:7d7db4b86e8b0d15cce311b476f91780404188df93a9159c5cd5d3d1d8d623dd"
)


class BaselineReleasePreparationError(ValueError):
    """The exact baseline inputs do not close into one release definition."""


@dataclass(frozen=True, slots=True)
class ReleaseSpec:
    key: str
    v1_role: str
    kind: str
    label: str
    manifest_path: str
    manifest_digest: str
    release_id: str
    semantic_ring: str
    concept_count: int
    native_relation_count: int
    assignment_evidence: str | None = None


@dataclass(frozen=True, slots=True)
class BaselineJobSpec:
    job: str
    directory: str
    source_role: str
    target_role: str
    receipt_file_digest: str
    receipt_content_digest: str
    relation_manifest_digest: str
    mapping_count: int


RELEASES = (
    ReleaseSpec(
        key="crs-entities",
        v1_role="crsEntities",
        kind="sourceConceptRelease",
        label="CRS Legislative Entities",
        manifest_path=(
            "research/evidence/crs-source-concept-releases-2026-08-04/"
            "legislative-entities/bundle-manifest.json"
        ),
        manifest_digest="sha256:aa80aaf0495a5e74a5194374cac05075fe8bcc0f0046261853293521544959fd",
        release_id="urn:ref:source-concept-release:entity:79db00f21940827fdf62a0af51e1d0d9161fdc438f345700f50590439b0f5822",
        semantic_ring="entity",
        concept_count=478,
        native_relation_count=0,
    ),
    ReleaseSpec(
        key="crs-legislative-subjects",
        v1_role="crsLegislativeSubjects",
        kind="sourceConceptRelease",
        label="CRS Legislative Subject Terms",
        manifest_path=(
            "research/evidence/crs-source-concept-releases-2026-08-04/"
            "legislative-subjects/bundle-manifest.json"
        ),
        manifest_digest="sha256:f20d688f08134a8b6b1c9a6e202e84c5e051e2786c743df66708be27b55b12e7",
        release_id="urn:ref:source-concept-release:subject:d137bdbae553a0ca59fb879458703de0a0a9047b49c119cb79a0765de75f3567",
        semantic_ring="subject",
        concept_count=565,
        native_relation_count=0,
    ),
    ReleaseSpec(
        key="crs-policy-areas",
        v1_role="crsPolicyAreas",
        kind="sourceConceptRelease",
        label="CRS Policy Areas",
        manifest_path=(
            "research/evidence/crs-source-concept-releases-2026-08-04/"
            "policy-areas/bundle-manifest.json"
        ),
        manifest_digest="sha256:b5966cb93cc1a28cc87ea914538f9c2f3da0b44fb37f66385170b56954dabeb8",
        release_id="urn:ref:source-concept-release:subject:3e2d1e3d598d818c4d53e9514c05ad8a5a804a3f138e1325f1605c7eed517d7e",
        semantic_ring="subject",
        concept_count=32,
        native_relation_count=0,
    ),
    ReleaseSpec(
        key="elsst",
        v1_role="elsst",
        kind="managedConceptRelease",
        label="ELSST R6",
        manifest_path=(
            "output/elsst-r6-atlas2-bench-input-2026-08-04/managed-release/"
            "managed-release-bundle.json"
        ),
        manifest_digest="sha256:466a4464cd252bf0b0c0e872927abc430f7532610100cf01e8104eec0ee69f25",
        release_id="https://elsst.cessda.eu/id/6",
        semantic_ring="subject",
        concept_count=3_470,
        native_relation_count=12_482,
        assignment_evidence="urn:ref:evidence:vocabulary-atlas-v1:elsst-r6-release-review",
    ),
    ReleaseSpec(
        key="federal-register",
        v1_role="federalRegisterThesaurus",
        kind="federalRegisterManagedConceptRelease",
        label="Federal Register Thesaurus 2025",
        manifest_path="output/skip-test-runtime/frt25/managed-release/managed-release.json",
        manifest_digest="sha256:3491acfdb3c4b51fda6351fcc47c2ca13e63e9df99e30399e05f745c97bf9df6",
        release_id=(
            "urn:ref:federal-register-thesaurus:2025-04-01:"
            "reference-resource-release:v1"
        ),
        semantic_ring="subject",
        concept_count=705,
        native_relation_count=1_451,
        assignment_evidence=(
            "urn:ref:evidence:vocabulary-atlas-v1:federal-register-release-review"
        ),
    ),
    ReleaseSpec(
        key="icpsr",
        v1_role="icpsr",
        kind="icpsrManagedConceptRelease",
        label="ICPSR Subject Thesaurus",
        manifest_path=(
            "output/refspec-vocabulary-portfolio/icpsr/2026-07-30/"
            "managed-release/managed-release.json"
        ),
        manifest_digest="sha256:f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615999c881673ac12a",
        release_id="urn:ref:icpsr:release:development:8bf9bf7f6c335e3aaccd29eedd00d41d7bc153e216e7dff6ff215472368aae37",
        semantic_ring="subject",
        concept_count=3_760,
        native_relation_count=18_751,
        assignment_evidence="urn:ref:evidence:vocabulary-atlas-v1:icpsr-release-review",
    ),
)

BASELINE_JOBS = (
    BaselineJobSpec(
        job="elsst-icpsr",
        directory="elsst-icpsr",
        source_role="elsst",
        target_role="icpsr",
        receipt_file_digest="sha256:c45a4142a8f9eadbdac2469ba9388b4a2e4cab37f03b5a4861d3c0dbddf480a6",
        receipt_content_digest="sha256:9427c1f6594a73018774ee740ed6c2be8d5a2fd7075f4342035d557cbf9036c7",
        relation_manifest_digest="sha256:a1a9a102cfb51726c140848b76d76431480e97a8ef77403b0020e49aff20526f",
        mapping_count=191,
    ),
    BaselineJobSpec(
        job="federal-register-elsst",
        directory="fr-elsst",
        source_role="federalRegisterThesaurus",
        target_role="elsst",
        receipt_file_digest="sha256:7b5dce1a35c40dbac27365a128dd5c2fa9f4ceaab2dd0ab724ce3d4ca76be89a",
        receipt_content_digest="sha256:7fdac61f4afdbc664e29c40c3c725767779fd166ceb50eebbf46593826abcec2",
        relation_manifest_digest="sha256:690a9a9a6144364359b737dedab74e1e9401f219897fd327cde5c1c0f66b4cfe",
        mapping_count=190,
    ),
    BaselineJobSpec(
        job="federal-register-icpsr",
        directory="fr-icpsr",
        source_role="federalRegisterThesaurus",
        target_role="icpsr",
        receipt_file_digest="sha256:83203c9830857e708b34835c124182948ef12e1d07b848490957f99f087efbb0",
        receipt_content_digest="sha256:de38585b99ec063a729ec23f74874572c72e8b2237644991b346d0ea7daecf20",
        relation_manifest_digest="sha256:a23485368bb88fe8560f46ff88463635ca3cf316c7000665d74326426bd48a59",
        mapping_count=201,
    ),
)

EXPECTED_MAPPING_COUNTS = {
    SUBJECT_BROAD_MATCH: 75,
    SUBJECT_CLOSE_MATCH: 232,
    SUBJECT_EXACT_MATCH: 121,
    SUBJECT_NARROW_MATCH: 119,
    SUBJECT_RELATED_MATCH: 35,
}

ICPSR_DEVELOPMENT_STATEMENT = (
    "The exact ICPSR release is approved for this baseline evidence preview "
    "under its developmentOnly status, with accepted output use disabled."
)


def _path(root: Path, relative: str) -> Path:
    value = PurePosixPath(relative)
    if value.is_absolute() or ".." in value.parts:
        raise BaselineReleasePreparationError(
            f"artifact path must stay inside the repository: {relative}"
        )
    result = root.joinpath(*value.parts)
    if result.is_symlink():
        raise BaselineReleasePreparationError(f"artifact must not be a symlink: {relative}")
    try:
        resolved = result.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as error:
        raise BaselineReleasePreparationError(
            f"artifact is unavailable inside the repository: {relative}"
        ) from error
    if not resolved.is_file():
        raise BaselineReleasePreparationError(f"artifact is not a regular file: {relative}")
    return resolved


def _bytes(root: Path, relative: str, expected_digest: str | None = None) -> bytes:
    artifact = _path(root, relative)
    payload = artifact.read_bytes()
    digest = sha256_digest(payload)
    if expected_digest is not None and digest != expected_digest:
        raise BaselineReleasePreparationError(
            f"artifact digest differs for {relative}: expected {expected_digest}, observed {digest}"
        )
    if artifact.read_bytes() != payload:
        raise BaselineReleasePreparationError(f"artifact changed while opening: {relative}")
    return payload


def _json_object(
    root: Path,
    relative: str,
    expected_digest: str | None = None,
) -> Mapping[str, Any]:
    payload = _bytes(root, relative, expected_digest)
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise BaselineReleasePreparationError(
            f"artifact must be valid UTF-8 JSON: {relative}"
        ) from error
    if not isinstance(value, Mapping):
        raise BaselineReleasePreparationError(f"artifact must be a JSON object: {relative}")
    return cast(Mapping[str, Any], value)


def _release_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in RELEASES:
        _bytes(root, spec.manifest_path, spec.manifest_digest)
        row: dict[str, Any] = {
            "key": spec.key,
            "v1Role": spec.v1_role,
            "kind": spec.kind,
            "label": spec.label,
            "manifestPath": spec.manifest_path,
            "manifestDigest": spec.manifest_digest,
            "releaseId": spec.release_id,
            "semanticRing": spec.semantic_ring,
        }
        if spec.assignment_evidence is not None:
            row["ringAssignment"] = {
                "assignedBy": DECISION_ACTOR,
                "assignedAt": ASSIGNED_AT,
                "evidence": [spec.assignment_evidence],
            }
        rows.append(row)
    return rows


def _row_dispositions(index: Mapping[str, Any]) -> list[dict[str, str]]:
    raw_rows = index.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise BaselineReleasePreparationError("planning index rows must be an array")
    included_release_ids = {release.release_id for release in RELEASES}
    result: list[dict[str, str]] = []
    included = 0
    for position, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise BaselineReleasePreparationError(
                f"planning index row {position} must be an object"
            )
        row_id = raw.get("rowId")
        row_digest = raw.get("rowDigest")
        if not isinstance(row_id, str) or not isinstance(row_digest, str):
            raise BaselineReleasePreparationError(
                f"planning index row {position} lacks its exact identity"
            )
        release = raw.get("release")
        if isinstance(release, Mapping) and release.get("releaseId") in included_release_ids:
            disposition = "included"
            reason = "Included in the exact six-release Vocabulary Atlas v1 scope."
            included += 1
        elif release is not None:
            disposition = "deliberatelyExcluded"
            reason = "An exact release exists, and this six-release scope does not include it."
        elif raw.get("planningStatus") == "planned":
            disposition = "planned"
            reason = "Planned for a later Vocabulary Atlas release."
        elif raw.get("planningStatus") == "deferred":
            disposition = "deferred"
            reason = "Deferred until its recorded readiness work is complete."
        elif raw.get("planningStatus") == "unassessed":
            disposition = "unavailable"
            reason = "No release assessment is available for this planning row."
        else:
            disposition = "deliberatelyExcluded"
            reason = "This planning row does not apply to the six-release scope."
        result.append(
            {
                "rowId": row_id,
                "rowDigest": row_digest,
                "disposition": disposition,
                "reason": reason,
            }
        )
    if len(result) != 87 or included != 6:
        raise BaselineReleasePreparationError(
            f"planning decisions must cover 87 rows with six included; observed {len(result)} and {included}"
        )
    if len({row["rowId"] for row in result}) != len(result):
        raise BaselineReleasePreparationError("planning index repeats a row identity")
    return result


def _baseline_job(
    root: Path,
    spec: BaselineJobSpec,
    role_release_ids: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, Any], Counter[str]]:
    base = f"output/vocabulary-atlas-v1-rc1/qualification-baseline/{spec.directory}"
    receipt_path = f"{base}/qualification-receipt.json"
    receipt = _json_object(root, receipt_path, spec.receipt_file_digest)
    if (
        receipt.get("contentDigest") != spec.receipt_content_digest
        or receipt.get("coverageMode") != "pilotSlice"
        or receipt.get("productionReady") is not False
    ):
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} differs from its approved non-production receipt"
        )

    accounting = receipt.get("candidateAccounting")
    if not isinstance(accounting, Sequence) or isinstance(accounting, (str, bytes)):
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} candidate accounting must be an array"
        )
    admitted: dict[str, str] = {}
    for position, raw in enumerate(accounting):
        if not isinstance(raw, Mapping):
            raise BaselineReleasePreparationError(
                f"baseline job {spec.job} accounting row {position} must be an object"
            )
        if raw.get("disposition") != "admitted":
            continue
        candidate_id = raw.get("candidateId")
        relation = raw.get("relation")
        if (
            not isinstance(candidate_id, str)
            or not isinstance(relation, str)
            or candidate_id in admitted
            or raw.get("control") is not False
        ):
            raise BaselineReleasePreparationError(
                f"baseline job {spec.job} has an invalid admitted candidate"
            )
        admitted[candidate_id] = relation
    if len(admitted) != spec.mapping_count:
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} must admit {spec.mapping_count} candidates; observed {len(admitted)}"
        )

    bundle = receipt.get("bundle")
    if not isinstance(bundle, Mapping):
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} receipt lacks its Crosswalk bundle pin"
        )
    crosswalk_file = bundle.get("file")
    crosswalk_digest = bundle.get("fileDigest")
    crosswalk_content_digest = bundle.get("bundleDigest")
    if not all(
        isinstance(value, str)
        for value in (crosswalk_file, crosswalk_digest, crosswalk_content_digest)
    ):
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} has an incomplete Crosswalk bundle pin"
        )
    crosswalk_path = f"{base}/{crosswalk_file}"
    crosswalk = _json_object(root, crosswalk_path, cast(str, crosswalk_digest))
    if (
        crosswalk.get("id") != bundle.get("id")
        or crosswalk.get("canonicalPayloadDigest") != crosswalk_content_digest
    ):
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} Crosswalk identity differs from its receipt"
        )
    candidates = crosswalk.get("mappingCandidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} Crosswalk candidates must be an array"
        )
    expected_endpoints = {
        role_release_ids[spec.source_role],
        role_release_ids[spec.target_role],
    }
    crosswalk_ids: set[str] = set()
    for position, raw in enumerate(candidates):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str):
            raise BaselineReleasePreparationError(
                f"baseline job {spec.job} Crosswalk candidate {position} is invalid"
            )
        candidate_id = cast(str, raw["id"])
        if candidate_id in crosswalk_ids or {
            raw.get("sourceRelease"),
            raw.get("targetRelease"),
        } != expected_endpoints:
            raise BaselineReleasePreparationError(
                f"baseline job {spec.job} Crosswalk candidate identities do not close"
            )
        crosswalk_ids.add(candidate_id)
    if not set(admitted) <= crosswalk_ids:
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} admitted candidates are absent from its Crosswalk bundle"
        )

    relation_manifest_path = f"{base}/relation-assertions/bundle-manifest.json"
    relation_manifest = _json_object(
        root,
        relation_manifest_path,
        spec.relation_manifest_digest,
    )
    artifacts = relation_manifest.get("artifacts")
    if (
        not isinstance(artifacts, Sequence)
        or isinstance(artifacts, (str, bytes))
        or len(artifacts) != 1
        or not isinstance(artifacts[0], Mapping)
        or artifacts[0].get("path") != "relation-assertions.json"
        or not isinstance(artifacts[0].get("sha256"), str)
    ):
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} relation manifest is incomplete"
        )
    relation_path = f"{base}/relation-assertions/relation-assertions.json"
    relation = _json_object(
        root,
        relation_path,
        cast(str, artifacts[0]["sha256"]),
    )
    if (
        relation.get("id") != relation_manifest.get("bundleId")
        or relation.get("contentDigest") != relation_manifest.get("contentDigest")
        or relation.get("semanticRing") != "subject"
    ):
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} relation identity differs from its manifest"
        )
    proof_pins = relation.get("machineProofPins")
    mappings = relation.get("mappingAssertions")
    if (
        not isinstance(proof_pins, Sequence)
        or isinstance(proof_pins, (str, bytes))
        or not isinstance(mappings, Sequence)
        or isinstance(mappings, (str, bytes))
        or len(proof_pins) != spec.mapping_count
        or len(mappings) != spec.mapping_count
    ):
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} relation bundle must contain {spec.mapping_count} proofs and mappings"
        )

    proof_candidates: dict[str, str] = {}
    for position, raw in enumerate(proof_pins):
        if not isinstance(raw, Mapping):
            raise BaselineReleasePreparationError(
                f"baseline job {spec.job} machine proof {position} is invalid"
            )
        candidate = raw.get("candidate")
        proof_source = raw.get("proofSource")
        qualification = raw.get("proofDetails")
        if not isinstance(candidate, Mapping) or not isinstance(candidate.get("id"), str):
            raise BaselineReleasePreparationError(
                f"baseline job {spec.job} machine proof {position} lacks a candidate"
            )
        candidate_id = cast(str, candidate["id"])
        relation_value = raw.get("relation")
        run_pin = (
            qualification.get("qualificationRun")
            if isinstance(qualification, Mapping)
            else None
        )
        if (
            not isinstance(relation_value, str)
            or candidate_id in proof_candidates
            or not isinstance(proof_source, Mapping)
            or proof_source.get("fileDigest") != crosswalk_digest
            or proof_source.get("contentDigest") != crosswalk_content_digest
            or not isinstance(run_pin, Mapping)
            or run_pin.get("fileDigest") != spec.receipt_file_digest
            or run_pin.get("contentDigest") != spec.receipt_content_digest
            or {raw.get("sourceRelease"), raw.get("targetRelease")}
            != expected_endpoints
        ):
            raise BaselineReleasePreparationError(
                f"baseline job {spec.job} machine proof {position} differs from its exact inputs"
            )
        proof_candidates[candidate_id] = relation_value
    if proof_candidates != admitted:
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} machine proofs differ from admitted receipt candidates"
        )

    proof_descriptor = {
        "crosswalkPath": crosswalk_path,
        "crosswalkFileDigest": cast(str, crosswalk_digest),
        "crosswalkBundleDigest": cast(str, crosswalk_content_digest),
        "qualificationRun": {
            "path": receipt_path,
            "fileDigest": spec.receipt_file_digest,
            "contentDigest": spec.receipt_content_digest,
        },
    }
    machine_proofs = [
        {**proof_descriptor, "candidateId": candidate_id}
        for candidate_id in sorted(admitted)
    ]
    run_descriptor = {
        "job": spec.job,
        "sourceReleaseId": role_release_ids[spec.source_role],
        "targetReleaseId": role_release_ids[spec.target_role],
        "runReceiptPath": receipt_path,
        "runReceiptFileDigest": spec.receipt_file_digest,
        "runReceiptContentDigest": spec.receipt_content_digest,
    }
    relation_descriptor = {
        "key": spec.job,
        "manifestPath": relation_manifest_path,
        "manifestDigest": spec.relation_manifest_digest,
        "semanticRing": "subject",
        "releaseIds": sorted(expected_endpoints),
        "machineProofs": machine_proofs,
    }
    mapping_counts = Counter(
        cast(str, row["relation"])
        for row in mappings
        if isinstance(row, Mapping) and isinstance(row.get("relation"), str)
    )
    if sum(mapping_counts.values()) != spec.mapping_count:
        raise BaselineReleasePreparationError(
            f"baseline job {spec.job} mapping predicates are incomplete"
        )
    return run_descriptor, relation_descriptor, mapping_counts


def build_baseline_release_definition_basis(root: Path | str = ROOT) -> dict[str, Any]:
    """Close the repository's exact baseline artifacts into a definition basis."""

    repository_root = Path(root).resolve(strict=True)
    if not repository_root.is_dir():
        raise BaselineReleasePreparationError("artifact root must be a directory")
    for field in ("path", "inputPath", "resourceCatalogPath"):
        digest_field = {
            "path": "fileDigest",
            "inputPath": "inputFileDigest",
            "resourceCatalogPath": "resourceCatalogFileDigest",
        }[field]
        _bytes(repository_root, PLANNING_INDEX[field], PLANNING_INDEX[digest_field])
    index = _json_object(
        repository_root,
        PLANNING_INDEX["path"],
        PLANNING_INDEX["fileDigest"],
    )
    qualification_jobs = _json_object(
        repository_root,
        QUALIFICATION_POLICY_PATH,
        QUALIFICATION_JOBS_FILE_DIGEST,
    )
    if qualification_jobs.get("recordDigest") != QUALIFICATION_POLICY_DIGEST:
        raise BaselineReleasePreparationError(
            "qualification jobs record differs from its approved policy identity"
        )
    release_rows = _release_rows(repository_root)
    role_release_ids = {release.v1_role: release.release_id for release in RELEASES}

    run_rows: list[dict[str, str]] = []
    relation_rows: list[dict[str, Any]] = []
    relation_counts: Counter[str] = Counter()
    for job in BASELINE_JOBS:
        run, relation, counts = _baseline_job(
            repository_root,
            job,
            role_release_ids,
        )
        run_rows.append(run)
        relation_rows.append(relation)
        relation_counts.update(counts)
    if dict(sorted(relation_counts.items())) != EXPECTED_MAPPING_COUNTS:
        raise BaselineReleasePreparationError(
            "baseline relation bundles must close to the exact 582 mappings by predicate"
        )

    dispositions = _row_dispositions(index)
    exceptions = [
        {
            "kind": "developmentOnly",
            "appliesTo": role_release_ids["icpsr"],
            "statement": ICPSR_DEVELOPMENT_STATEMENT,
        }
    ]
    approvals = [
        {
            "releaseId": release.release_id,
            "manifestDigest": release.manifest_digest,
            "semanticRing": release.semantic_ring,
            "disposition": "approved",
            "conditions": (
                [
                    {
                        "kind": "developmentOnly",
                        "statement": ICPSR_DEVELOPMENT_STATEMENT,
                    }
                ]
                if release.v1_role == "icpsr"
                else []
            ),
        }
        for release in RELEASES
    ]
    concepts_by_release = {
        release.release_id: release.concept_count for release in RELEASES
    }
    native_by_release = {
        release.release_id: release.native_relation_count for release in RELEASES
    }
    return {
        "type": "VocabularyAtlasV1ReleaseDefinition",
        "schemaVersion": "1.0",
        "releaseMode": "baselineEvidenceRc",
        "releaseName": "urn:ref:vocabulary-atlas:release:v1-baseline-evidence-rc1",
        "scopeName": "urn:ref:vocabulary-atlas:scope:v1-baseline-evidence-rc1",
        "scopeKind": "bench",
        "title": "Vocabulary Atlas v1 baseline evidence preview",
        "planningIndex": dict(PLANNING_INDEX),
        "releases": release_rows,
        "relationBundles": relation_rows,
        "productionQualificationRuns": [],
        "baselineQualificationRuns": run_rows,
        "publication": {
            "decisionActor": DECISION_ACTOR,
            "decidedAt": DECIDED_AT,
            "policies": [
                {
                    "role": "selectionPolicy",
                    "id": (
                        "https://refspec.org/policies/vocabulary-atlas-selection/"
                        "v1-six-release-baseline/1.0"
                    ),
                    "version": "1.0",
                    "contentDigest": PLANNING_INDEX["inputFileDigest"],
                },
                {
                    "role": "qualificationPolicy",
                    "id": (
                        "https://refspec.org/policies/vocabulary-atlas-qualification/"
                        "v1-baseline-evidence/1.0"
                    ),
                    "version": "1.0",
                    "contentDigest": QUALIFICATION_POLICY_DIGEST,
                },
            ],
            "exceptions": exceptions,
            "supersedes": [],
            "sourceApprovals": approvals,
            "rowDispositions": dispositions,
        },
        "expectedCounts": {
            "releaseCount": 6,
            "planningRowCount": 87,
            "includedPlanningRowCount": 6,
            "conceptTotal": sum(concepts_by_release.values()),
            "conceptsByRelease": concepts_by_release,
            "nativeRelationTotal": sum(native_by_release.values()),
            "nativeRelationsByRelease": native_by_release,
            "mappingMinimumTotal": sum(EXPECTED_MAPPING_COUNTS.values()),
            "mappingMinimumByRelation": dict(EXPECTED_MAPPING_COUNTS),
        },
    }


def prepare_baseline_release_definition(
    output: Path | str = DEFAULT_OUTPUT,
    *,
    root: Path | str = ROOT,
    check: bool = False,
) -> VocabularyAtlasV1ReleaseDefinition:
    """Write or verify one independently reopenable baseline definition."""

    definition = VocabularyAtlasV1ReleaseDefinition.seal(
        build_baseline_release_definition_basis(root)
    )
    output_path = Path(output)
    expected_payload = definition.artifact_bytes()
    expected_file_digest = sha256_digest(expected_payload)
    if check:
        if not output_path.is_file() or output_path.is_symlink():
            raise BaselineReleasePreparationError(
                f"baseline definition is unavailable for checking: {output_path}"
            )
        if output_path.read_bytes() != expected_payload:
            raise BaselineReleasePreparationError(
                "prepared baseline definition differs from the exact current inputs"
            )
    elif output_path.exists() or output_path.is_symlink():
        if not output_path.is_file() or output_path.is_symlink():
            raise BaselineReleasePreparationError(
                f"baseline definition output must be a regular file: {output_path}"
            )
        if output_path.read_bytes() != expected_payload:
            raise BaselineReleasePreparationError(
                "baseline definition output already exists with different bytes"
            )
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        definition.write_to(output_path)
    return read_vocabulary_atlas_v1_release_definition(
        output_path,
        expected_file_digest=expected_file_digest,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Close the exact local six-release baseline evidence into one path-backed "
            "Vocabulary Atlas v1 release definition."
        )
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=ROOT,
        help="repository root that contains every exact input artifact",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="new canonical baseline release-definition file",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that the existing output reproduces from the current exact inputs",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        definition = prepare_baseline_release_definition(
            args.output,
            root=args.artifact_root,
            check=args.check,
        )
    except (BaselineReleasePreparationError, OSError, ValueError) as error:
        print(f"Vocabulary Atlas v1 baseline preparation failed: {error}", file=sys.stderr)
        return 2
    record = definition.as_record()
    print(
        canonical_json(
            {
                "definitionFileDigest": definition.file_digest,
                "definitionId": definition.identifier,
                "definitionPath": str(definition.path),
                "mappingProofCount": sum(
                    len(row["machineProofs"])
                    for row in cast(list[dict[str, Any]], record["relationBundles"])
                ),
                "providerCalls": False,
                "releaseCount": len(record["releases"]),
                "status": "verified" if args.check else "prepared",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
