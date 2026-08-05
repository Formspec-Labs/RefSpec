#!/usr/bin/env python3
"""Prepare the exact public Vocabulary Atlas v1 release definition.

The command reopens the approved baseline, all six manifest-declared
production qualification runs, both provider batch evidence paths, and every
admitted relation proof.  It performs local reads and one definition write
only.  It never calls a model provider or publishes a release.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from prepare_vocabulary_atlas_v1_baseline_release import (
    PLANNING_INDEX,
    QUALIFICATION_JOBS_FILE_DIGEST,
    QUALIFICATION_POLICY_DIGEST,
    QUALIFICATION_POLICY_PATH,
    build_baseline_release_definition_basis,
)

from refspec import binding
from refspec.atlas import qualification as qual
from refspec.atlas import qualification_batch as qbatch
from refspec.atlas import qualification_spend as qspend
from refspec.atlas import v1_release as release_contract
from refspec.atlas.machine_evidence import (
    CrosswalkMachineProofError,
    PinnedCrosswalkMachineProof,
)
from refspec.atlas.model import CrosswalkBundle
from refspec.atlas.qualification_jobs import (
    VocabularyAtlasV1QualificationJobs,
    VocabularyAtlasV1QualificationJobsError,
    read_vocabulary_atlas_v1_qualification_jobs,
    verify_prepared_vocabulary_atlas_v1_qualification_jobs,
)
from refspec.atlas.relation_assertion import (
    RELATION_ASSERTION_BUNDLE_MEDIA_TYPE,
    RELATION_ASSERTION_BUNDLE_VERSION,
    EmbeddedRelationAssertionBundle,
    RelationAssertionError,
)
from refspec.atlas.v1_release import (
    VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_VERSION,
    VocabularyAtlasV1ReleaseDefinition,
    read_vocabulary_atlas_v1_release_definition,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    require_aware_datetime_text,
)
from refspec.storage import canonical_json

DEFAULT_OUTPUT = ROOT / "output/vocabulary-atlas-v1-rc1/control/release-definitions/" "vocabulary-atlas-v1-public.json"

PUBLIC_ICPSR_STATEMENT = (
    "The exact ICPSR release is approved for the public Vocabulary Atlas v1 "
    "with its developmentOnly source status preserved. The Atlas provides "
    "candidate discovery and mapping evidence, while accepted downstream "
    "outputs continue under their separately governed permissions."
)


class PublicReleasePreparationError(ValueError):
    """The exact public inputs do not close into one release definition."""


def _repository_root(value: Path | str) -> Path:
    try:
        root = Path(value).resolve(strict=True)
    except FileNotFoundError as error:
        raise PublicReleasePreparationError("artifact root does not exist") from error
    if not root.is_dir():
        raise PublicReleasePreparationError("artifact root must be a directory")
    return root


def _relative_path(value: str, *, label: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise PublicReleasePreparationError(f"{label} must be a normalized repository-relative path")
    return path


def _candidate_path(root: Path, relative: str, *, label: str) -> Path:
    path = _relative_path(relative, label=label)
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise PublicReleasePreparationError(f"{label} must not traverse a symlink")
    try:
        cursor.parent.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise PublicReleasePreparationError(f"{label} must stay inside the repository") from error
    return cursor


def _path(root: Path, relative: str, *, label: str) -> Path:
    candidate = _candidate_path(root, relative, label=label)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as error:
        raise PublicReleasePreparationError(f"{label} is unavailable") from error
    if not resolved.is_file():
        raise PublicReleasePreparationError(f"{label} must be a regular file")
    return resolved


def _bytes(
    root: Path,
    relative: str,
    *,
    label: str,
    expected_digest: str | None = None,
) -> bytes:
    artifact = _path(root, relative, label=label)
    payload = artifact.read_bytes()
    digest = sha256_digest(payload)
    if expected_digest is not None and digest != expected_digest:
        raise PublicReleasePreparationError(f"{label} digest differs: expected {expected_digest}, observed {digest}")
    if artifact.read_bytes() != payload:
        raise PublicReleasePreparationError(f"{label} changed while opening")
    return payload


def _decode_object(payload: bytes, *, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise PublicReleasePreparationError(f"{label} must be valid UTF-8 JSON") from error
    if not isinstance(value, Mapping):
        raise PublicReleasePreparationError(f"{label} must be a JSON object")
    return cast(Mapping[str, Any], value)


def _canonical_object(
    root: Path,
    relative: str,
    *,
    label: str,
    expected_digest: str | None = None,
) -> tuple[Mapping[str, Any], bytes]:
    payload = _bytes(
        root,
        relative,
        label=label,
        expected_digest=expected_digest,
    )
    value = _decode_object(payload, label=label)
    if canonical_json_bytes(value) != payload:
        raise PublicReleasePreparationError(f"{label} bytes are not canonical")
    return value, payload


def _array(value: object, *, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PublicReleasePreparationError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _object(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicReleasePreparationError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _pinned_run_file(
    root: Path,
    *,
    output_path: str,
    pin: Mapping[str, Any],
    required_name: str,
    label: str,
) -> tuple[str, bytes]:
    name = pin.get("file")
    digest = pin.get("fileDigest")
    if name != required_name or not isinstance(digest, str):
        raise PublicReleasePreparationError(f"{label} must pin {required_name} by exact file digest")
    relative = f"{output_path}/{required_name}"
    return relative, _bytes(
        root,
        relative,
        label=label,
        expected_digest=digest,
    )


def _verify_catalog(
    root: Path,
    *,
    public_job: str,
    planned_job: Mapping[str, str],
    source: Mapping[str, str],
    target: Mapping[str, str],
    policy: Mapping[str, str],
    run: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], str, str]:
    label = f"production job {public_job} candidate catalog"
    pin = _object(run.get("candidateCatalog"), label=f"{label} pin")
    expected_total, expected_digest = release_contract._PUBLIC_V1_PRODUCTION_CATALOGS[public_job]
    if pin.get("total") != expected_total or pin.get("fileDigest") != expected_digest:
        raise PublicReleasePreparationError(f"{label} differs from its exact public v1 total or digest")
    relative, _payload = _pinned_run_file(
        root,
        output_path=planned_job["outputPath"],
        pin=pin,
        required_name="candidates.json",
        label=label,
    )
    catalog, _ = _canonical_object(
        root,
        relative,
        label=label,
        expected_digest=expected_digest,
    )
    expected_fields = {
        "coverageMode": policy["coverageMode"],
        "generatedAt": planned_job["generatedAt"],
        "generationPolicy": policy["generationPolicy"],
        "productionFloor": policy["productionFloor"],
        "proposedRelation": policy["proposedRelation"],
        "protocol": policy["protocol"],
        "seed": policy["seed"],
        "sourceManifestDigest": source["manifestDigest"],
        "targetManifestDigest": target["manifestDigest"],
    }
    if (
        any(catalog.get(field) != value for field, value in expected_fields.items())
        or catalog.get("limits") is not None
        or catalog.get("total") != expected_total
    ):
        raise PublicReleasePreparationError(f"{label} differs from the complete manifest-declared production plan")
    candidates = _array(catalog.get("candidates"), label=f"{label} candidates")
    if len(candidates) != expected_total:
        raise PublicReleasePreparationError(f"{label} candidate total is incomplete")
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(candidates):
        row = _object(raw, label=f"{label} candidates[{index}]")
        candidate_id = row.get("candidateId")
        source_row = row.get("source")
        target_row = row.get("target")
        if (
            not isinstance(candidate_id, str)
            or candidate_id in by_id
            or not isinstance(source_row, Mapping)
            or not isinstance(target_row, Mapping)
            or source_row.get("release") != source["releaseId"]
            or target_row.get("release") != target["releaseId"]
        ):
            raise PublicReleasePreparationError(f"{label} candidate identities or endpoints do not close")
        by_id[candidate_id] = row
    return by_id, relative, expected_digest


def _verify_relation_bundle(
    root: Path,
    *,
    public_job: str,
    output_path: str,
    source: Mapping[str, str],
    target: Mapping[str, str],
    run_path: str,
    run_file_digest: str,
    run: Mapping[str, Any],
    crosswalk_path: str,
    crosswalk_candidates: Mapping[str, Mapping[str, Any]],
    admitted: Mapping[str, str],
) -> dict[str, Any] | None:
    relation_root = f"{output_path}/relation-assertions"
    destination = _candidate_path(
        root,
        relation_root,
        label=f"production job {public_job} relation output",
    )
    if not admitted:
        if destination.exists() or destination.is_symlink():
            raise PublicReleasePreparationError(
                f"production job {public_job} has stale relation output for zero admissions"
            )
        return None
    if destination.is_symlink() or not destination.is_dir():
        raise PublicReleasePreparationError(f"production job {public_job} admitted mappings require a relation bundle")
    entries = list(destination.iterdir())
    expected_names = {"bundle-manifest.json", "relation-assertions.json"}
    if {entry.name for entry in entries} != expected_names or any(
        entry.is_symlink() or not entry.is_file() for entry in entries
    ):
        raise PublicReleasePreparationError(
            f"production job {public_job} relation output must contain its exact two files"
        )

    manifest_path = f"{relation_root}/bundle-manifest.json"
    manifest, manifest_payload = _canonical_object(
        root,
        manifest_path,
        label=f"production job {public_job} relation manifest",
    )
    if set(manifest) != {
        "schemaVersion",
        "packageKind",
        "bundleId",
        "contentDigest",
        "artifacts",
    } or (
        manifest.get("schemaVersion") != RELATION_ASSERTION_BUNDLE_VERSION
        or manifest.get("packageKind") != "relationAssertionBundle"
    ):
        raise PublicReleasePreparationError(f"production job {public_job} relation manifest has an unsupported shape")
    artifacts = _array(
        manifest.get("artifacts"),
        label=f"production job {public_job} relation manifest artifacts",
    )
    if len(artifacts) != 1:
        raise PublicReleasePreparationError(f"production job {public_job} relation manifest must name one artifact")
    artifact = _object(
        artifacts[0],
        label=f"production job {public_job} relation artifact",
    )
    relation_path = f"{relation_root}/relation-assertions.json"
    if (
        set(artifact) != {"path", "role", "mediaType", "sha256", "byteLength"}
        or artifact.get("path") != "relation-assertions.json"
        or artifact.get("role") != "relationAssertions"
        or artifact.get("mediaType") != RELATION_ASSERTION_BUNDLE_MEDIA_TYPE
        or not isinstance(artifact.get("sha256"), str)
    ):
        raise PublicReleasePreparationError(f"production job {public_job} relation artifact descriptor is incomplete")
    relation, relation_payload = _canonical_object(
        root,
        relation_path,
        label=f"production job {public_job} relation assertions",
        expected_digest=cast(str, artifact["sha256"]),
    )
    if artifact.get("byteLength") != len(relation_payload) or (
        relation.get("id") != manifest.get("bundleId") or relation.get("contentDigest") != manifest.get("contentDigest")
    ):
        raise PublicReleasePreparationError(f"production job {public_job} relation manifest and content differ")
    try:
        verified = EmbeddedRelationAssertionBundle.from_record(relation)
    except RelationAssertionError as error:
        raise PublicReleasePreparationError(
            f"production job {public_job} relation assertions do not close: {error}"
        ) from error

    expected_releases = {
        source["releaseId"]: source["manifestDigest"],
        target["releaseId"]: target["manifestDigest"],
    }
    release_pins = {str(pin.get("releaseId")): pin for pin in verified.release_pins}
    if set(release_pins) != set(expected_releases) or any(
        release_pins[release_id].get("manifestDigest") != manifest_digest
        for release_id, manifest_digest in expected_releases.items()
    ):
        raise PublicReleasePreparationError(f"production job {public_job} relation bundle names another release pair")
    if (
        verified.semantic_ring != "subject"
        or len(verified.machine_proof_pins) != len(admitted)
        or len(verified.mapping_assertions) != len(admitted)
        or any(mapping.lifecycle_status != "current" or mapping.supersedes for mapping in verified.mapping_assertions)
    ):
        raise PublicReleasePreparationError(
            f"production job {public_job} relation mapping closure differs from its admissions"
        )

    bundle_pin = _object(
        run.get("bundle"),
        label=f"production job {public_job} Crosswalk pin",
    )
    proof_relations: dict[str, str] = {}
    for index, pin in enumerate(verified.machine_proof_pins):
        candidate = _object(
            pin.get("candidate"),
            label=f"production job {public_job} proof[{index}] candidate",
        )
        proof_source = _object(
            pin.get("proofSource"),
            label=f"production job {public_job} proof[{index}] source",
        )
        proof_details = _object(
            pin.get("proofDetails"),
            label=f"production job {public_job} proof[{index}] details",
        )
        qualification_run = _object(
            proof_details.get("qualificationRun"),
            label=f"production job {public_job} proof[{index}] qualification run",
        )
        candidate_id = candidate.get("id")
        relation_value = pin.get("relation")
        crosswalk_candidate = crosswalk_candidates.get(candidate_id) if isinstance(candidate_id, str) else None
        if (
            not isinstance(candidate_id, str)
            or not isinstance(relation_value, str)
            or candidate_id in proof_relations
            or crosswalk_candidate is None
            or candidate.get("contentDigest") != crosswalk_candidate.get("canonicalPayloadDigest")
            or proof_source.get("id") != bundle_pin.get("id")
            or proof_source.get("fileDigest") != bundle_pin.get("fileDigest")
            or proof_source.get("contentDigest") != bundle_pin.get("bundleDigest")
            or qualification_run.get("id") != run.get("id")
            or qualification_run.get("fileDigest") != run_file_digest
            or qualification_run.get("contentDigest") != run.get("contentDigest")
            or qualification_run.get("candidateDisposition") != "admitted"
            or pin.get("sourceRelease") != source["releaseId"]
            or pin.get("targetRelease") != target["releaseId"]
            or pin.get("sourceConcept") != crosswalk_candidate.get("sourceMember")
            or pin.get("targetConcept") != crosswalk_candidate.get("targetMember")
        ):
            raise PublicReleasePreparationError(
                f"production job {public_job} proof[{index}] differs from its exact run and Crosswalk candidate"
            )
        try:
            reproduced = PinnedCrosswalkMachineProof.qualified(
                _path(
                    root,
                    crosswalk_path,
                    label=f"production job {public_job} proof[{index}] Crosswalk bundle",
                ),
                expected_file_digest=cast(str, bundle_pin["fileDigest"]),
                expected_bundle_digest=cast(str, bundle_pin["bundleDigest"]),
                candidate_id=candidate_id,
                qualification_run_path=_path(
                    root,
                    run_path,
                    label=f"production job {public_job} proof[{index}] qualification run",
                ),
                expected_qualification_run_file_digest=run_file_digest,
                expected_qualification_run_content_digest=cast(
                    str,
                    run["contentDigest"],
                ),
            ).pin()
        except (CrosswalkMachineProofError, KeyError) as error:
            raise PublicReleasePreparationError(
                f"production job {public_job} proof[{index}] does not reproduce from its exact source bytes: {error}"
            ) from error
        if reproduced != plain_json(pin):
            raise PublicReleasePreparationError(
                f"production job {public_job} proof[{index}] differs from the exact reproduced machine proof"
            )
        proof_relations[candidate_id] = relation_value
    if proof_relations != dict(admitted):
        raise PublicReleasePreparationError(
            f"production job {public_job} relation proofs differ from admitted candidates"
        )

    proof_descriptor = {
        "crosswalkPath": crosswalk_path,
        "crosswalkFileDigest": cast(str, bundle_pin["fileDigest"]),
        "crosswalkBundleDigest": cast(str, bundle_pin["bundleDigest"]),
        "qualificationRun": {
            "path": run_path,
            "fileDigest": run_file_digest,
            "contentDigest": cast(str, run["contentDigest"]),
        },
    }
    return {
        "key": f"production-{public_job}",
        "manifestPath": manifest_path,
        "manifestDigest": sha256_digest(manifest_payload),
        "semanticRing": "subject",
        "releaseIds": sorted(expected_releases),
        "machineProofs": [{**proof_descriptor, "candidateId": candidate_id} for candidate_id in sorted(admitted)],
    }


def _production_job(
    root: Path,
    *,
    public_job: str,
    planned_job: Mapping[str, str],
    source: Mapping[str, str],
    target: Mapping[str, str],
    policy: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, Any] | None, int, dict[str, Any]]:
    label = f"production job {public_job}"
    run_path = f"{planned_job['outputPath']}/qualification-receipt.json"
    receipt, receipt_payload = _canonical_object(
        root,
        run_path,
        label=f"{label} run receipt",
    )
    try:
        run = qual.validate_qualification_run_receipt(receipt)
    except qual.QualificationError as error:
        raise PublicReleasePreparationError(f"{label} run receipt is invalid: {error}") from error
    if (
        run.get("coverageMode") != qual.PRODUCTION_COVERAGE_MODE
        or run.get("productionReady") is not True
        or run.get("sourceManifestDigest") != source["manifestDigest"]
        or run.get("targetManifestDigest") != target["manifestDigest"]
        or run.get("candidateGenerationPolicy") != policy["generationPolicy"]
        or run.get("productionFloor") != policy["productionFloor"]
        or run.get("protocol") != policy["protocol"]
    ):
        raise PublicReleasePreparationError(f"{label} must be a production-ready run for its exact manifest pair")
    provider_evidence = run.get("providerBatchEvidence")
    if not isinstance(provider_evidence, Mapping) or set(provider_evidence) != {
        "judging",
        "scoring",
    }:
        raise PublicReleasePreparationError(f"{label} must pin both judging and scoring batch evidence")
    try:
        provider_summaries = qbatch.verify_run_provider_batch_evidence(
            _path(root, run_path, label=f"{label} run receipt"),
            run,
        )
    except qbatch.BatchError as error:
        raise PublicReleasePreparationError(f"{label} provider batch evidence does not reopen: {error}") from error

    catalog_candidates, _catalog_path, _catalog_digest = _verify_catalog(
        root,
        public_job=public_job,
        planned_job=planned_job,
        source=source,
        target=target,
        policy=policy,
        run=run,
    )
    expected_total = release_contract._PUBLIC_V1_PRODUCTION_CATALOGS[public_job][0]
    counts = _object(run.get("counts"), label=f"{label} counts")
    accounting_rows = _array(
        run.get("candidateAccounting"),
        label=f"{label} candidate accounting",
    )
    accounting: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(accounting_rows):
        row = _object(raw, label=f"{label} candidate accounting[{index}]")
        candidate_id = row.get("candidateId")
        if not isinstance(candidate_id, str) or candidate_id in accounting:
            raise PublicReleasePreparationError(f"{label} candidate accounting identities must be unique")
        accounting[candidate_id] = row
    try:
        qual.verify_candidate_accounting_catalog_lineage(
            accounting_rows,
            tuple(catalog_candidates.values()),
        )
    except qual.QualificationError as error:
        raise PublicReleasePreparationError(
            f"{label} candidate accounting differs from its exact catalog: {error}"
        ) from error
    if (
        counts.get("generated") != expected_total
        or len(accounting) != expected_total
        or set(accounting) != set(catalog_candidates)
    ):
        raise PublicReleasePreparationError(f"{label} accounting must cover every exact catalog candidate once")

    bundle_pin = _object(run.get("bundle"), label=f"{label} Crosswalk pin")
    crosswalk_path, _crosswalk_payload = _pinned_run_file(
        root,
        output_path=planned_job["outputPath"],
        pin=bundle_pin,
        required_name="crosswalk-bundle.json",
        label=f"{label} Crosswalk bundle",
    )
    try:
        bundle = CrosswalkBundle.open(
            _path(root, crosswalk_path, label=f"{label} Crosswalk bundle"),
            expected_file_digest=cast(str, bundle_pin["fileDigest"]),
            expected_bundle_digest=cast(str, bundle_pin["bundleDigest"]),
        )
    except (OSError, ValueError) as error:
        raise PublicReleasePreparationError(f"{label} Crosswalk bundle does not reopen: {error}") from error
    if bundle.identifier != bundle_pin.get("id"):
        raise PublicReleasePreparationError(f"{label} Crosswalk identity differs")
    bundle_rows = _array(
        bundle.to_dict().get("mappingCandidates"),
        label=f"{label} Crosswalk candidates",
    )
    crosswalk_candidates: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(bundle_rows):
        row = _object(raw, label=f"{label} Crosswalk candidates[{index}]")
        candidate_id = row.get("id")
        if (
            not isinstance(candidate_id, str)
            or candidate_id in crosswalk_candidates
            or row.get("sourceRelease") != source["releaseId"]
            or row.get("targetRelease") != target["releaseId"]
        ):
            raise PublicReleasePreparationError(f"{label} Crosswalk candidate identities or endpoints do not close")
        crosswalk_candidates[candidate_id] = row
    if set(crosswalk_candidates) != set(accounting):
        raise PublicReleasePreparationError(
            f"{label} catalog, Crosswalk bundle, and accounting name different candidates"
        )

    admitted: dict[str, str] = {}
    for candidate_id, row in accounting.items():
        if row.get("disposition") != "admitted":
            continue
        relation = row.get("relation")
        if row.get("control") is not False or not isinstance(relation, str):
            raise PublicReleasePreparationError(f"{label} has an invalid admission")
        admitted[candidate_id] = relation
    relations = bundle.adjudicated_relations()
    expected_admitted = {
        candidate_id: relation
        for candidate_id, relation in relations.items()
        if accounting[candidate_id].get("control") is False
    }
    if admitted != expected_admitted:
        raise PublicReleasePreparationError(f"{label} Crosswalk adjudications differ from run admissions")

    receipt_file_digest = sha256_digest(receipt_payload)
    run_descriptor = {
        "job": public_job,
        "sourceReleaseId": source["releaseId"],
        "targetReleaseId": target["releaseId"],
        "runReceiptPath": run_path,
        "runReceiptFileDigest": receipt_file_digest,
        "runReceiptContentDigest": cast(str, run["contentDigest"]),
    }
    relation_descriptor = _verify_relation_bundle(
        root,
        public_job=public_job,
        output_path=planned_job["outputPath"],
        source=source,
        target=target,
        run_path=run_path,
        run_file_digest=receipt_file_digest,
        run=run,
        crosswalk_path=crosswalk_path,
        crosswalk_candidates=crosswalk_candidates,
        admitted=admitted,
    )
    spend_descriptor = _verify_production_spend_authority(
        root,
        planned_job=planned_job,
        run=run,
        provider_evidence=provider_evidence,
        provider_summaries=provider_summaries,
    )
    return run_descriptor, relation_descriptor, len(admitted), spend_descriptor


def _verify_production_spend_authority(
    root: Path,
    *,
    planned_job: Mapping[str, str],
    run: Mapping[str, Any],
    provider_evidence: Mapping[str, Any],
    provider_summaries: Mapping[str, Any],
) -> dict[str, Any]:
    """Reopen the one campaign approval and this run's fixed allocation."""

    descriptor = _object(
        run.get("spendAuthority"),
        label=f"production job {planned_job['key']} spend authority",
    )
    authority_relative = descriptor.get("authorityFile")
    if not isinstance(authority_relative, str):
        raise PublicReleasePreparationError("production spend authority has no repository path")
    manifest = _qualification_manifest(root)
    try:
        authority = qspend.read_vocabulary_atlas_v1_production_spend_authority(
            _path(root, authority_relative, label="production spend authority"),
            manifest=manifest,
            repository_root=root,
        )
        allocation = authority.job(str(planned_job["key"]))
    except (OSError, ValueError) as error:
        raise PublicReleasePreparationError(f"production spend authority does not reopen: {error}") from error
    expected = {
        "approvedTotalSpendCapUsd": authority.record["approvedTotalSpendCapUsd"],
        "authorityFile": authority_relative,
        "authorityFileDigest": authority.file_digest,
        "authorityId": authority.identifier,
        "authorityRecordDigest": authority.record_digest,
        "batchPlanDigest": allocation["batchPlanDigest"],
        "batchPolicyDigest": authority.batch_policy_digest,
        "jobKey": allocation["jobKey"],
        "modelsByFamily": dict(authority.record["batchPolicy"]["modelsByFamily"]),
        "runSpendCapUsd": allocation["runSpendCapUsd"],
    }
    if plain_json(descriptor) != expected or allocation["outputPath"] != planned_job["outputPath"]:
        raise PublicReleasePreparationError(
            f"production job {planned_job['key']} spend authority differs from its exact allocation"
        )
    run_cap = float(allocation["runSpendCapUsd"])
    for name in ("judging", "scoring"):
        pin = _object(
            provider_evidence.get(name),
            label=f"production job {planned_job['key']} {name} batch evidence",
        )
        sidecar_name = pin.get("file")
        if not isinstance(sidecar_name, str):
            raise PublicReleasePreparationError("production batch evidence has no sidecar path")
        sidecar, _payload = _canonical_object(
            root,
            f"{planned_job['outputPath']}/{sidecar_name}",
            label=f"production job {planned_job['key']} {name} batch sidecar",
            expected_digest=cast(str, pin.get("fileDigest")),
        )
        family_caps = _object(
            sidecar.get("spendCapsByFamily"),
            label=f"production job {planned_job['key']} {name} family caps",
        )
        if (
            plain_json(sidecar.get("spendAuthority")) != expected
            or float(sidecar.get("totalSpendCapUsd") or 0.0) != run_cap
            or not family_caps
            or any(float(value) != run_cap for value in family_caps.values())
        ):
            raise PublicReleasePreparationError(
                f"production job {planned_job['key']} {name} batch caps differ from its spend authority"
            )
        try:
            qspend.verify_vocabulary_atlas_v1_production_batch_sidecar(
                authority,
                sidecar,
                job_key=str(planned_job["key"]),
                work_kind=("validation" if name == "judging" else "scoring"),
                repository_root=root,
            )
        except ValueError as error:
            raise PublicReleasePreparationError(
                f"production job {planned_job['key']} {name} Batch plan "
                f"differs from its spend authority: {error}"
            ) from error
    committed = round(
        sum(
            float(_object(summary, label=f"production {name} batch summary").get("committedCostUsd") or 0.0)
            for name, summary in provider_summaries.items()
        ),
        6,
    )
    if committed > run_cap:
        raise PublicReleasePreparationError(
            f"production job {planned_job['key']} committed spend exceeds its allocation"
        )
    return {
        "approvedTotalSpendCapUsd": authority.record["approvedTotalSpendCapUsd"],
        "authorityFileDigest": authority.file_digest,
        "authorityId": authority.identifier,
        "authorityRecordDigest": authority.record_digest,
        "batchPlanDigest": allocation["batchPlanDigest"],
        "batchPolicyDigest": authority.batch_policy_digest,
        "committedSpendUsd": committed,
        "jobKey": allocation["jobKey"],
        "runSpendCapUsd": allocation["runSpendCapUsd"],
    }


def _qualification_manifest(root: Path) -> VocabularyAtlasV1QualificationJobs:
    path = _path(
        root,
        QUALIFICATION_POLICY_PATH,
        label="production qualification job manifest",
    )
    manifest = read_vocabulary_atlas_v1_qualification_jobs(path)
    if manifest.file_digest != QUALIFICATION_JOBS_FILE_DIGEST or manifest.record_digest != QUALIFICATION_POLICY_DIGEST:
        raise PublicReleasePreparationError("production qualification job manifest differs from the approved policy")
    return manifest


def _verify_campaign_spend_rows(
    spend_rows: Sequence[Mapping[str, Any]],
    manifest: VocabularyAtlasV1QualificationJobs,
) -> None:
    """Prove that six run-local caps are one non-overlapping campaign cap."""

    if len(spend_rows) != len(manifest.jobs):
        raise PublicReleasePreparationError(
            "public v1 production jobs must share one exact six-run spend authority"
        )
    authority_identities = {
        (
            row.get("authorityId"),
            row.get("authorityRecordDigest"),
            row.get("authorityFileDigest"),
            row.get("approvedTotalSpendCapUsd"),
            row.get("batchPolicyDigest"),
        )
        for row in spend_rows
    }
    spend_job_keys = {row.get("jobKey") for row in spend_rows}
    if len(authority_identities) != 1 or spend_job_keys != {
        str(job["key"]) for job in manifest.jobs
    }:
        raise PublicReleasePreparationError(
            "public v1 production jobs must share one exact six-run spend authority"
        )
    try:
        approved_total = Decimal(str(spend_rows[0]["approvedTotalSpendCapUsd"]))
        allocated_total = sum(
            (Decimal(str(row["runSpendCapUsd"])) for row in spend_rows),
            start=Decimal(0),
        )
        committed_total = sum(
            (Decimal(str(row["committedSpendUsd"])) for row in spend_rows),
            start=Decimal(0),
        )
    except (ArithmeticError, KeyError, ValueError) as error:
        raise PublicReleasePreparationError(
            "public v1 production spend accounting is invalid"
        ) from error
    if allocated_total != approved_total or committed_total > approved_total:
        raise PublicReleasePreparationError(
            "public v1 production qualification exceeds its approved total spend cap"
        )


def build_public_release_definition_basis(
    root: Path | str = ROOT,
    *,
    decided_at: str,
    check: bool = False,
) -> dict[str, Any]:
    """Close the exact baseline plus six production jobs into a public basis."""

    repository_root = _repository_root(root)
    try:
        normalized_decided_at = require_aware_datetime_text(
            decided_at,
            label="public release decision time",
        )
    except SourceIdentityError as error:
        raise PublicReleasePreparationError(str(error)) from error
    baseline = build_baseline_release_definition_basis(
        repository_root,
        check=True,
    )
    basis = cast(dict[str, Any], json.loads(canonical_json(baseline)))

    corpus_path = release_contract._PUBLIC_V1_EXPLORER_SEARCH_CORPUS_PATH
    corpus_digest = release_contract._PUBLIC_V1_EXPLORER_SEARCH_CORPUS_FILE_DIGEST
    _bytes(
        repository_root,
        corpus_path,
        label="public v1 reviewed explorer search corpus",
        expected_digest=corpus_digest,
    )
    manifest = _qualification_manifest(repository_root)
    try:
        prepared = verify_prepared_vocabulary_atlas_v1_qualification_jobs(
            manifest,
            repository_root=repository_root,
        )
    except VocabularyAtlasV1QualificationJobsError as error:
        raise PublicReleasePreparationError(f"production catalogs do not reopen: {error}") from error
    if prepared.get("jobCount") != 6:
        raise PublicReleasePreparationError("production qualification manifest must reopen exactly six jobs")

    releases = _array(basis.get("releases"), label="baseline releases")
    role_by_release_id = {
        cast(str, row["releaseId"]): cast(str, row["v1Role"]) for row in releases if isinstance(row, Mapping)
    }
    public_job_by_roles = {roles: job for job, roles in release_contract._PRODUCTION_JOB_ROLES.items()}
    sources = {source["key"]: source for source in manifest.sources}
    run_rows: list[dict[str, str]] = []
    relation_rows = cast(list[dict[str, Any]], basis["relationBundles"])
    production_relation_rows: list[dict[str, Any]] = []
    spend_rows: list[dict[str, Any]] = []
    observed_jobs: set[str] = set()
    for planned_job in manifest.jobs:
        source = sources[planned_job["sourceKey"]]
        target = sources[planned_job["targetKey"]]
        role_pair = (
            role_by_release_id.get(source["releaseId"]),
            role_by_release_id.get(target["releaseId"]),
        )
        public_job = public_job_by_roles.get(cast(tuple[str, str], role_pair))
        if public_job is None or public_job in observed_jobs:
            raise PublicReleasePreparationError(
                "production qualification manifest pairs do not map uniquely to public v1 jobs"
            )
        observed_jobs.add(public_job)
        run, relation, _admitted, spend = _production_job(
            repository_root,
            public_job=public_job,
            planned_job=planned_job,
            source=source,
            target=target,
            policy=cast(Mapping[str, str], manifest.record["qualificationPolicy"]),
        )
        run_rows.append(run)
        spend_rows.append(spend)
        if relation is not None:
            production_relation_rows.append(relation)
    expected_jobs = set(release_contract._PRODUCTION_JOB_ROLES)
    if observed_jobs != expected_jobs or len(run_rows) != 6:
        raise PublicReleasePreparationError("public v1 requires every production qualification job exactly once")
    _verify_campaign_spend_rows(spend_rows, manifest)
    relation_keys = [cast(str, row["key"]) for row in [*relation_rows, *production_relation_rows]]
    if len(relation_keys) != len(set(relation_keys)):
        raise PublicReleasePreparationError("baseline and production relation bundle keys must be unique")

    icpsr_release_id = next(
        cast(str, row["releaseId"]) for row in releases if isinstance(row, Mapping) and row.get("v1Role") == "icpsr"
    )
    publication = cast(dict[str, Any], basis["publication"])
    publication["decidedAt"] = normalized_decided_at
    publication["policies"] = [
        {
            "role": "selectionPolicy",
            "id": ("https://refspec.org/policies/vocabulary-atlas-selection/" "v1-six-release-public/1.0"),
            "version": "1.0",
            "contentDigest": PLANNING_INDEX["inputFileDigest"],
        },
        {
            "role": "qualificationPolicy",
            "id": (
                "https://refspec.org/policies/vocabulary-atlas-qualification/" "v1-complete-production-catalogs/1.0"
            ),
            "version": "1.0",
            "contentDigest": QUALIFICATION_POLICY_DIGEST,
        },
    ]
    publication["exceptions"] = [
        {
            "kind": "developmentOnly",
            "appliesTo": icpsr_release_id,
            "statement": PUBLIC_ICPSR_STATEMENT,
        }
    ]
    for approval in cast(list[dict[str, Any]], publication["sourceApprovals"]):
        approval["conditions"] = (
            [
                {
                    "kind": "developmentOnly",
                    "statement": PUBLIC_ICPSR_STATEMENT,
                }
            ]
            if approval["releaseId"] == icpsr_release_id
            else []
        )

    basis.update(
        {
            "schemaVersion": VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_VERSION,
            "releaseMode": "publicV1",
            "releaseName": "urn:ref:vocabulary-atlas:release:v1",
            "scopeName": "urn:ref:vocabulary-atlas:scope:v1",
            "scopeKind": "published",
            "title": "Vocabulary Atlas v1",
            "reviewedSearchCorpus": {
                "status": "required",
                "path": corpus_path,
                "fileDigest": corpus_digest,
            },
            "relationBundles": [*relation_rows, *production_relation_rows],
            "productionQualificationRuns": run_rows,
            "publication": publication,
        }
    )
    return basis


def prepare_public_release_definition(
    output: Path | str = DEFAULT_OUTPUT,
    *,
    root: Path | str = ROOT,
    decided_at: str,
    check: bool = False,
) -> VocabularyAtlasV1ReleaseDefinition:
    """Write or verify one independently reopenable public definition."""

    definition = VocabularyAtlasV1ReleaseDefinition.seal(
        build_public_release_definition_basis(
            root,
            decided_at=decided_at,
            check=check,
        )
    )
    output_path = Path(output)
    expected_payload = definition.artifact_bytes()
    expected_file_digest = sha256_digest(expected_payload)
    if check:
        if not output_path.is_file() or output_path.is_symlink():
            raise PublicReleasePreparationError(f"public definition is unavailable for checking: {output_path}")
        if output_path.read_bytes() != expected_payload:
            raise PublicReleasePreparationError("prepared public definition differs from the exact current inputs")
    elif output_path.exists() or output_path.is_symlink():
        if not output_path.is_file() or output_path.is_symlink():
            raise PublicReleasePreparationError(f"public definition output must be a regular file: {output_path}")
        if output_path.read_bytes() != expected_payload:
            raise PublicReleasePreparationError("public definition output already exists with different bytes")
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
            "Close the exact baseline and six completed production jobs into one "
            "path-backed public Vocabulary Atlas v1 release definition."
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
        help="new canonical public release-definition file",
    )
    parser.add_argument(
        "--decided-at",
        required=True,
        help="timezone-aware public release decision time",
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
        definition = prepare_public_release_definition(
            args.output,
            root=args.artifact_root,
            decided_at=args.decided_at,
            check=args.check,
        )
    except (OSError, ValueError) as error:
        print(f"Vocabulary Atlas v1 public preparation failed: {error}", file=sys.stderr)
        return 2
    record = definition.as_record()
    print(
        canonical_json(
            {
                "baselineRunCount": len(record["baselineQualificationRuns"]),
                "definitionFileDigest": definition.file_digest,
                "definitionId": definition.identifier,
                "definitionPath": str(definition.path),
                "mappingProofCount": sum(
                    len(row["machineProofs"]) for row in cast(list[dict[str, Any]], record["relationBundles"])
                ),
                "productionRunCount": len(record["productionQualificationRuns"]),
                "providerCalls": False,
                "releaseCount": len(record["releases"]),
                "status": "verified" if args.check else "prepared",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
