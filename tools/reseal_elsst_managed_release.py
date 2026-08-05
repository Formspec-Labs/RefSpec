#!/usr/bin/env python3
"""Reseal the pinned ELSST R6 bundle against current RefSpec metadata.

This migration preserves the source bytes, Rulespec graph, normalized tables,
and indexed-expression corpus. It adds the current OutputProfile admission
field, propagates linked record digests, embeds the current Rulespec dependency
pin, and issues a fresh combined validation receipt. The operational
serialization profile validates these distribution bytes; the selected
Rulespec reference-release digest remains the vocabulary release identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from refspec import binding
from refspec.managed_release import ManagedReleaseView
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    path_sha256_descriptor,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.managed_vocabulary_bundle import (
    managed_ref_record_artifact_path,
    reseal_linked_ref_records,
)
from refspec.release_graph import (
    GRAPH_DIGEST_ALGORITHM,
    RulespecValidatorPin,
    defined_rulespec_identifiers,
    issue_release_graph_validation_receipt,
    load_pinned_rulespec_validator,
    load_rulespec_dependency_manifest,
    referenced_rulespec_identifiers,
    rulespec_dependency_bytes,
    rulespec_graph_digest,
)

_OUTPUT_PROFILE_TYPE = "urn:ref:type:OutputProfile"
_PUBLICATION_TYPE = "urn:ref:type:PublicationReleaseManifest"
_RECEIPT_TYPE = "urn:ref:type:ReleaseGraphValidationReceipt"
_EXPECTED_RELATION_PREDICATES = frozenset(
    {
        "http://www.w3.org/2004/02/skos/core#broader",
        "http://www.w3.org/2004/02/skos/core#narrower",
        "http://www.w3.org/2004/02/skos/core#related",
    }
)


class ElsstManagedReleaseResealError(ValueError):
    """The pinned legacy release cannot be migrated without changing facts."""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("--expected-manifest-digest", required=True)
    parser.add_argument("--rulespec-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--recorded-at", required=True)
    parser.add_argument(
        "--recorded-by",
        default="urn:ref:agent:refspec-elsst-managed-release",
    )
    return parser.parse_args()


def _load_json_bytes(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ElsstManagedReleaseResealError(f"{label} is not strict UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise ElsstManagedReleaseResealError(f"{label} must be a JSON object")
    return value


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    return _load_json_bytes(path.read_bytes(), label=label)


def _require_digest(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ElsstManagedReleaseResealError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_artifact_path(
    root: Path,
    descriptor: Mapping[str, Any],
    *,
    label: str,
    seen_paths: set[PurePosixPath],
) -> Path:
    value = descriptor.get("path")
    if not isinstance(value, str) or not value:
        raise ElsstManagedReleaseResealError(f"{label}.path is required")
    if "\\" in value:
        raise ElsstManagedReleaseResealError(f"{label}.path must use relative POSIX syntax")
    relative = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        relative.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ElsstManagedReleaseResealError(f"{label}.path must be a normalized relative path")
    if relative in seen_paths:
        raise ElsstManagedReleaseResealError(f"bundle repeats artifact path {relative.as_posix()!r}")
    seen_paths.add(relative)

    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ElsstManagedReleaseResealError(f"{label}.path must not traverse a symlink")
    try:
        path = cursor.resolve(strict=True)
        path.relative_to(root)
    except (FileNotFoundError, ValueError) as error:
        raise ElsstManagedReleaseResealError(f"{label}.path is missing or escapes the bundle root") from error
    if not path.is_file():
        raise ElsstManagedReleaseResealError(f"{label}.path must name a regular file")
    expected = _require_digest(
        descriptor.get("sha256"),
        label=f"{label}.sha256",
    )
    actual = _digest_file(path)
    if actual != expected:
        raise ElsstManagedReleaseResealError(f"{label} digest mismatch: expected {expected}, got {actual}")
    byte_length = descriptor.get("byteLength")
    if byte_length is not None and byte_length != path.stat().st_size:
        raise ElsstManagedReleaseResealError(f"{label}.byteLength does not match the exact artifact")
    return path


def _verified_source_bundle(
    manifest_path: Path,
    *,
    expected_manifest_digest: str,
) -> tuple[dict[str, Any], dict[str, Path]]:
    expected_manifest_digest = _require_digest(
        expected_manifest_digest,
        label="expected_manifest_digest",
    )
    if manifest_path.is_symlink():
        raise ElsstManagedReleaseResealError("source manifest must not be a symlink")
    try:
        manifest_path = manifest_path.resolve(strict=True)
    except FileNotFoundError as error:
        raise ElsstManagedReleaseResealError("source manifest does not exist") from error
    if not manifest_path.is_file():
        raise ElsstManagedReleaseResealError("source manifest must be a regular file")
    actual_manifest_digest = _digest_file(manifest_path)
    if actual_manifest_digest != expected_manifest_digest:
        raise ElsstManagedReleaseResealError(
            f"source manifest digest mismatch: expected {expected_manifest_digest}, got {actual_manifest_digest}"
        )
    manifest = _load_json(manifest_path, label="source manifest")
    root = manifest_path.parent.resolve()
    seen_paths: set[PurePosixPath] = set()
    artifacts: dict[str, Path] = {}

    def add(label: str, value: object) -> None:
        if not isinstance(value, Mapping):
            raise ElsstManagedReleaseResealError(f"{label} must be an artifact descriptor")
        artifacts[label] = _safe_artifact_path(
            root,
            value,
            label=label,
            seen_paths=seen_paths,
        )

    for field in (
        "publicationReleaseManifest",
        "rulespecGraph",
        "rulespecDependencyManifest",
        "combinedValidationReceipt",
        "indexedExpressionCorpus",
    ):
        add(field, manifest.get(field))
    for field in ("refRecords", "normalizedTables"):
        values = manifest.get(field)
        if not isinstance(values, list) or not values:
            raise ElsstManagedReleaseResealError(f"{field} must be a non-empty descriptor array")
        for index, value in enumerate(values):
            add(f"{field}[{index}]", value)
    sources = manifest.get("sourceArtifacts")
    if not isinstance(sources, dict) or not sources:
        raise ElsstManagedReleaseResealError("sourceArtifacts must contain the exact ELSST distribution")
    for identifier, value in sorted(sources.items()):
        add(f"sourceArtifacts[{identifier!r}]", value)
    return manifest, artifacts


def _binding_schema_set_digest() -> str:
    paths = sorted(binding.SCHEMA_ROOT.glob("*.schema.json"))
    if not paths:
        raise ElsstManagedReleaseResealError("this migration requires an explicit RefSpec checkout schema set")
    artifacts = [
        {
            "path": path.name,
            "sha256": sha256_digest(path.read_bytes()),
        }
        for path in paths
    ]
    return binding.canonical_sha256(artifacts)


def _current_rulespec_dependency(
    publication: Mapping[str, Any],
    *,
    validator: RulespecValidatorPin,
) -> dict[str, Any]:
    manifest = load_rulespec_dependency_manifest()
    previous = publication.get("rulespecDependency")
    if not isinstance(previous, Mapping):
        raise ElsstManagedReleaseResealError("publication rulespecDependency is missing")
    conformance_result = previous.get("conformanceResult")
    adopted_profiles = previous.get("adoptedProfiles")
    if not isinstance(conformance_result, Mapping):
        raise ElsstManagedReleaseResealError("publication conformanceResult is missing")
    if not isinstance(adopted_profiles, list) or not adopted_profiles:
        raise ElsstManagedReleaseResealError("publication adoptedProfiles is missing")
    return {
        "version": str(manifest["rulespecVersion"]),
        "contractRevision": str(manifest["contractRevision"]),
        "evidenceRevision": str(manifest["evidenceRevision"]),
        "constraintDigest": str(manifest["constraintDigest"]),
        "conformanceCorpusDigest": str(manifest["conformanceCorpusDigest"]),
        "adoptedProfiles": plain_json(adopted_profiles),
        "validator": {
            "id": validator.component_id,
            "revision": validator.source_revision,
            "digest": validator.component_digest,
        },
        "conformanceResult": plain_json(conformance_result),
        "releaseAvailability": str(manifest["releaseAvailability"]),
    }


def _reseal_records(
    publication: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    validator: RulespecValidatorPin,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], str]:
    publication_copy = plain_json(publication)
    record_copies = [plain_json(record) for record in records]
    profiles = [record for record in record_copies if record.get("type") == _OUTPUT_PROFILE_TYPE]
    if len(profiles) != 1:
        raise ElsstManagedReleaseResealError("ELSST release must contain exactly one OutputProfile")
    profile = profiles[0]
    if "subjectAdmissionPermissions" in profile:
        raise ElsstManagedReleaseResealError("source OutputProfile is already on the current admission schema")
    profile["subjectAdmissionPermissions"] = []

    serialization_profile = publication_copy.get("operationalSerializationProfile")
    if not isinstance(serialization_profile, dict):
        raise ElsstManagedReleaseResealError("publication operationalSerializationProfile is missing")
    schema_digest = _binding_schema_set_digest()
    serialization_profile["digest"] = schema_digest
    publication_copy["rulespecDependency"] = _current_rulespec_dependency(
        publication_copy,
        validator=validator,
    )

    resealed = reseal_linked_ref_records((*record_copies, publication_copy))
    resealed_publication = resealed[-1]
    resealed_records = resealed[:-1]
    if resealed_publication.get("type") != _PUBLICATION_TYPE:
        raise ElsstManagedReleaseResealError("source publication has the wrong REF record type")
    diagnostics = binding.validate([resealed_publication, *resealed_records])
    if diagnostics:
        raise ElsstManagedReleaseResealError(
            "resealed records fail REF JSON Binding 1.0: " + " | ".join(item.render() for item in diagnostics)
        )
    return resealed_publication, resealed_records, schema_digest


def _gate_bundle(
    *,
    graph: Mapping[str, Any],
    graph_id: str,
    records: Sequence[Mapping[str, Any]],
    validator: RulespecValidatorPin,
) -> dict[str, Any]:
    graph_digest = rulespec_graph_digest(graph)
    graph_identifiers = defined_rulespec_identifiers(graph)
    cross_references = sorted(
        (
            {
                "refRecordId": str(record["id"]),
                "rulespecIdentifier": identifier,
            }
            for record in records
            for identifier in referenced_rulespec_identifiers(
                record,
                graph_identifiers,
            )
        ),
        key=lambda value: (
            value["refRecordId"],
            value["rulespecIdentifier"],
        ),
    )
    return {
        "bundleVersion": "1.0",
        "refRecords": [plain_json(record) for record in records],
        "rulespecGraph": plain_json(graph),
        "rulespecGraphId": graph_id,
        "rulespecGraphDigest": graph_digest,
        "graphDigestAlgorithm": GRAPH_DIGEST_ALGORITHM,
        "validatorReceipt": {
            "result": "pass",
            "validatorIdentity": validator.identity,
            "validatorSourceRevision": validator.source_revision,
            "graphId": graph_id,
            "graphDigest": graph_digest,
            "coveredIdentifiers": sorted(graph_identifiers),
        },
        "crossReferences": cross_references,
    }


def _write_exact(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _copy_exact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _descriptor_path(descriptor: object, *, label: str) -> str:
    if not isinstance(descriptor, Mapping):
        raise ElsstManagedReleaseResealError(f"{label} must be an artifact descriptor")
    path = descriptor.get("path")
    if not isinstance(path, str) or not path:
        raise ElsstManagedReleaseResealError(f"{label}.path is required")
    return path


def _write_resealed_bundle(
    destination: Path,
    *,
    source_manifest: Mapping[str, Any],
    source_artifacts: Mapping[str, Path],
    publication: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    receipt: Mapping[str, Any],
) -> tuple[Path, str]:
    manifest = plain_json(source_manifest)
    unchanged: list[tuple[str, object]] = [
        ("rulespecGraph", source_manifest["rulespecGraph"]),
        (
            "indexedExpressionCorpus",
            source_manifest["indexedExpressionCorpus"],
        ),
    ]
    unchanged.extend(
        (f"normalizedTables[{index}]", descriptor)
        for index, descriptor in enumerate(source_manifest["normalizedTables"])
    )
    unchanged.extend(
        (
            f"sourceArtifacts[{identifier!r}]",
            source_manifest["sourceArtifacts"][identifier],
        )
        for identifier in sorted(source_manifest["sourceArtifacts"])
    )
    for label, descriptor in unchanged:
        _copy_exact(
            source_artifacts[label],
            destination / _descriptor_path(descriptor, label=label),
        )

    dependency_payload = rulespec_dependency_bytes()
    dependency_path = _descriptor_path(
        source_manifest["rulespecDependencyManifest"],
        label="rulespecDependencyManifest",
    )
    _write_exact(destination / dependency_path, dependency_payload)
    manifest["rulespecDependencyManifest"] = path_sha256_descriptor(
        dependency_path,
        dependency_payload,
    )

    publication_payload = canonical_json_bytes(publication)
    publication_path = _descriptor_path(
        source_manifest["publicationReleaseManifest"],
        label="publicationReleaseManifest",
    )
    _write_exact(destination / publication_path, publication_payload)
    manifest["publicationReleaseManifest"] = path_sha256_descriptor(
        publication_path,
        publication_payload,
    )

    record_descriptors: list[dict[str, str]] = []
    for record in records:
        payload = canonical_json_bytes(record)
        relative = managed_ref_record_artifact_path(record)
        _write_exact(destination / relative, payload)
        record_descriptors.append(path_sha256_descriptor(relative, payload))
    manifest["refRecords"] = sorted(
        record_descriptors,
        key=lambda value: value["path"],
    )

    receipt_payload = canonical_json_bytes(receipt)
    receipt_path = _descriptor_path(
        source_manifest["combinedValidationReceipt"],
        label="combinedValidationReceipt",
    )
    _write_exact(destination / receipt_path, receipt_payload)
    manifest["combinedValidationReceipt"] = path_sha256_descriptor(
        receipt_path,
        receipt_payload,
    )

    manifest_payload = canonical_json_bytes(manifest)
    manifest_path = destination / "managed-release-bundle.json"
    _write_exact(manifest_path, manifest_payload)
    return manifest_path, sha256_digest(manifest_payload)


def _verified_counts(view: ManagedReleaseView) -> dict[str, Any]:
    relations = tuple(view.iter_relations())
    predicate_counts = Counter(relation.predicate_iri for relation in relations)
    if set(predicate_counts) != _EXPECTED_RELATION_PREDICATES:
        raise ElsstManagedReleaseResealError("resealed ELSST relation predicates differ from the native set")
    return {
        "members": sum(1 for _member in view.iter_members()),
        "indexedExpressions": sum(1 for _expression in view.iter_expressions()),
        "relations": len(relations),
        "relationsByPredicate": dict(sorted(predicate_counts.items())),
        "lifecycleParticipants": sum(1 for _participant in view.iter_lifecycle_participants()),
        "conceptMappings": sum(1 for _mapping in view.iter_concept_mappings()),
    }


def reseal_elsst_managed_release(
    *,
    source_manifest_path: Path,
    expected_manifest_digest: str,
    rulespec_dir: Path,
    output_dir: Path,
    report_path: Path,
    recorded_at: str,
    recorded_by: str,
) -> dict[str, Any]:
    """Migrate, gate, write, and fully reopen one exact ELSST release."""

    if output_dir.exists():
        raise FileExistsError(f"refusing existing output directory {output_dir}")
    if report_path.exists():
        raise FileExistsError(f"refusing existing report {report_path}")
    manifest, artifacts = _verified_source_bundle(
        source_manifest_path,
        expected_manifest_digest=expected_manifest_digest,
    )
    validator = load_pinned_rulespec_validator(rulespec_dir)
    publication = _load_json(
        artifacts["publicationReleaseManifest"],
        label="publicationReleaseManifest",
    )
    records = tuple(
        _load_json(path, label=label) for label, path in artifacts.items() if label.startswith("refRecords[")
    )
    graph = _load_json(
        artifacts["rulespecGraph"],
        label="rulespecGraph",
    )
    previous_receipt = _load_json(
        artifacts["combinedValidationReceipt"],
        label="combinedValidationReceipt",
    )
    if previous_receipt.get("type") != _RECEIPT_TYPE:
        raise ElsstManagedReleaseResealError("source combined receipt has the wrong REF record type")
    receipt_id = previous_receipt.get("id")
    activity = previous_receipt.get("activity")
    graph_id = manifest.get("rulespecGraphId")
    if not all(isinstance(value, str) and value for value in (receipt_id, activity, graph_id)):
        raise ElsstManagedReleaseResealError("source receipt and graph identities must be non-empty text")

    resealed_publication, resealed_records, schema_digest = _reseal_records(
        publication,
        records,
        validator=validator,
    )
    gate_records = (resealed_publication, *resealed_records)
    receipt = issue_release_graph_validation_receipt(
        _gate_bundle(
            graph=graph,
            graph_id=graph_id,
            records=gate_records,
            validator=validator,
        ),
        validator=validator,
        receipt_id=receipt_id,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        activity=activity,
    )

    output_parent = output_dir.parent.resolve()
    output_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}-",
            dir=output_parent,
        )
    )
    try:
        output_manifest, output_digest = _write_resealed_bundle(
            temporary,
            source_manifest=manifest,
            source_artifacts=artifacts,
            publication=resealed_publication,
            records=resealed_records,
            receipt=receipt,
        )
        view = ManagedReleaseView.open(
            output_manifest,
            expected_manifest_digest=output_digest,
        )
        counts = _verified_counts(view)
        os.replace(temporary, output_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    final_manifest = output_dir / "managed-release-bundle.json"
    if _digest_file(final_manifest) != output_digest:
        raise ElsstManagedReleaseResealError("output manifest changed during atomic publication")
    source_digest = _require_digest(
        expected_manifest_digest,
        label="expected_manifest_digest",
    )
    report = {
        "migration": "elsst-r6-current-ref-metadata-reseal-v1",
        "recordedAt": recorded_at,
        "recordedBy": recorded_by,
        "sourceBundleManifest": {
            "path": str(source_manifest_path),
            "digest": source_digest,
        },
        "outputBundleManifest": {
            "path": str(final_manifest),
            "digest": output_digest,
        },
        "publicationRelease": {
            "id": resealed_publication["id"],
            "digest": resealed_publication[binding.digest_field(resealed_publication)],
        },
        "combinedValidationReceipt": {
            "id": receipt["id"],
            "digest": receipt["canonicalPayloadDigest"],
        },
        "rulespecGraph": {
            "id": graph_id,
            "digest": rulespec_graph_digest(graph),
        },
        "rulespecDependencyManifestDigest": sha256_digest(rulespec_dependency_bytes()),
        "bindingSchemaSetDigest": schema_digest,
        "releaseIdentityRule": {
            "declaredVocabularyIdentity": "rulespecReferenceReleaseDigest",
            "operationalSerializationProfile": "distributionValidationProvenanceOnly",
        },
        "semanticChange": {
            "recordType": _OUTPUT_PROFILE_TYPE,
            "field": "subjectAdmissionPermissions",
            "value": [],
        },
        "preservedArtifacts": [
            "sourceArtifacts",
            "rulespecGraph",
            "normalizedTables",
            "indexedExpressionCorpus",
        ],
        "counts": counts,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(canonical_json_bytes(report))
    return report


def main() -> int:
    args = _arguments()
    report = reseal_elsst_managed_release(
        source_manifest_path=args.source_manifest,
        expected_manifest_digest=args.expected_manifest_digest,
        rulespec_dir=args.rulespec_dir,
        output_dir=args.output_dir,
        report_path=args.report,
        recorded_at=args.recorded_at,
        recorded_by=args.recorded_by,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
