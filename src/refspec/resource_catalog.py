"""Build RefSpec's source-neutral experimental resource catalog.

The catalog distinguishes knowledge that a resource exists from proof that a
consumer can open exact bytes from this repository.  It is deliberately not a
public binding: the experimental format may change after real consumers expose
missing fields.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from refspec.binding import canonical_sha256
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseError,
    SourceConceptReleaseView,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceError,
    SourceControlledResourceView,
)

CATALOG_INPUT_FORMAT = "refspec-resource-catalog-input/experimental-v0"
DISTRIBUTION_INPUT_FORMAT = "refspec-portable-resource-distributions/experimental-v0"
CATALOG_FORMAT = "refspec-resource-catalog/experimental-v0"

RESOURCE_KINDS = {
    "classification",
    "codeList",
    "historicalVocabulary",
    "identifierAuthority",
    "mappingReference",
    "resourceFamily",
    "sourceAssignedVocabulary",
    "structuralSchema",
    "subjectVocabulary",
}

SOURCE_AVAILABILITY_STATES = {
    "available",
    "availableButUnreconciled",
    "definitionOnly",
    "historicalOnly",
    "partial",
    "plannedFamily",
    "unresolvedIdentity",
}

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE_CONCEPT_RELEASE_DISTRIBUTION_KIND = "refspec-source-concept-release-1.0"
_SOURCE_CONTROLLED_RESOURCE_DISTRIBUTION_KIND = "refspec-source-controlled-resource-2.0"


class ResourceCatalogError(ValueError):
    """Raised when a catalog input or generated catalog is not closed."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ResourceCatalogError(f"duplicate JSON object key {key!r}")
        value[key] = item
    return value


def load_json(path: Path) -> dict[str, Any]:
    """Read one JSON object and reject duplicate keys and non-finite numbers."""

    def reject_constant(value: str) -> None:
        raise ResourceCatalogError(f"non-finite JSON number {value!r}")

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ResourceCatalogError(f"{path} must contain one JSON object")
    return value


def render_json(value: Any) -> str:
    """Render deterministic checked-in JSON with one trailing newline."""

    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"


def _require_keys(value: Mapping[str, Any], expected: set[str], location: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ResourceCatalogError(
            f"{location} keys differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResourceCatalogError(f"{location} must be a non-empty string")
    return value


def _digest(value: Any, location: str) -> str:
    result = _string(value, location)
    if not _SHA256.fullmatch(result):
        raise ResourceCatalogError(f"{location} must be a lowercase SHA-256 digest")
    return result


def _relative_path(value: Any, location: str) -> PurePosixPath:
    text = _string(value, location)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != text:
        raise ResourceCatalogError(f"{location} must be a normalized repository-relative path")
    return path


def _repository_file(root: Path, value: Any, location: str) -> Path:
    relative = _relative_path(value, location)
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ResourceCatalogError(f"{location} does not name a checked regular file: {relative}")
    return candidate


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_relative_file_set(
    package_root: Path,
    *,
    repository_root: Path,
    location: str,
) -> set[str]:
    """Return every regular package file and reject paths outside the repository."""

    try:
        repository = repository_root.resolve(strict=True)
        root = package_root.resolve(strict=True)
        root.relative_to(repository)
    except (FileNotFoundError, ValueError) as error:
        raise ResourceCatalogError(f"{location} package root must remain inside the repository") from error
    if package_root.is_symlink() or not root.is_dir():
        raise ResourceCatalogError(f"{location} package root must be a regular directory")

    result: set[str] = set()
    for item in root.rglob("*"):
        if item.is_symlink():
            raise ResourceCatalogError(f"{location} package contains a symlink: {item.relative_to(root)}")
        if item.is_file():
            result.add(item.relative_to(repository).as_posix())
    if not result:
        raise ResourceCatalogError(f"{location} package contains no files")
    return result


def _require_complete_file_inventory(
    inventory_paths: set[str],
    package_paths: set[str],
    *,
    location: str,
) -> None:
    if inventory_paths != package_paths:
        raise ResourceCatalogError(
            f"{location} file inventory differs from the closed package; "
            f"missing={sorted(package_paths - inventory_paths)}, extra={sorted(inventory_paths - package_paths)}"
        )


def _verify_source_controlled_resource_distribution(
    *,
    manifest_file: Path,
    inventory_paths: set[str],
    completed_row: Mapping[str, Any],
    repository_root: Path,
    location: str,
) -> None:
    if manifest_file.name != "bundle-manifest.json":
        raise ResourceCatalogError(f"{location} must name bundle-manifest.json")
    if completed_row.get("packageClass") != "sourceControlledResource":
        raise ResourceCatalogError(f"{location} completed evidence must describe a sourceControlledResource")
    try:
        view = SourceControlledResourceView.open(manifest_file.parent)
    except SourceControlledResourceError as error:
        raise ResourceCatalogError(f"{location} is not a valid closed source-controlled resource: {error}") from error
    package_paths = _repository_relative_file_set(
        manifest_file.parent,
        repository_root=repository_root,
        location=location,
    )
    _require_complete_file_inventory(
        inventory_paths,
        package_paths,
        location=location,
    )
    if view.logical_digest != completed_row.get("packageDigest"):
        raise ResourceCatalogError(f"{location} logical digest differs from completed evidence")


def _verify_source_concept_release_distribution(
    *,
    manifest_file: Path,
    inventory_paths: set[str],
    inventory_digests: Mapping[str, str],
    completed_row: Mapping[str, Any],
    repository_root: Path,
    location: str,
) -> None:
    if manifest_file.name != "bundle-manifest.json":
        raise ResourceCatalogError(f"{location} must name bundle-manifest.json")
    if completed_row.get("packageClass") != "sourceConceptRelease":
        raise ResourceCatalogError(f"{location} completed evidence must describe a sourceConceptRelease")
    package_paths = _repository_relative_file_set(
        manifest_file.parent,
        repository_root=repository_root,
        location=location,
    )
    manifest_relative = manifest_file.resolve(strict=True).relative_to(repository_root.resolve(strict=True)).as_posix()
    try:
        view = SourceConceptReleaseView.open(
            manifest_file,
            expected_manifest_digest=inventory_digests[manifest_relative],
        )
    except (KeyError, SourceConceptReleaseError) as error:
        raise ResourceCatalogError(f"{location} is not a valid closed source-concept release: {error}") from error
    _require_complete_file_inventory(
        inventory_paths,
        package_paths,
        location=location,
    )
    if view.logical_digest != completed_row.get("packageDigest"):
        raise ResourceCatalogError(f"{location} logical digest differs from completed evidence")


def _validate_inventory(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    _require_keys(value, {"format", "recordedAt", "resources"}, "resource inventory")
    if value["format"] != CATALOG_INPUT_FORMAT:
        raise ResourceCatalogError(f"unsupported resource inventory format {value['format']!r}")
    _string(value["recordedAt"], "resource inventory recordedAt")
    resources = value["resources"]
    if not isinstance(resources, list) or not resources:
        raise ResourceCatalogError("resource inventory resources must be a non-empty list")

    expected = {
        "accessOrReproducibilityGap",
        "distributionStatus",
        "identifierRepresentation",
        "officialLocator",
        "resourceId",
        "resourceKind",
        "title",
        "versionRepresentation",
    }
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(resources):
        if not isinstance(raw, Mapping):
            raise ResourceCatalogError(f"resources[{index}] must be an object")
        _require_keys(raw, expected, f"resources[{index}]")
        row = {key: _string(raw[key], f"resources[{index}].{key}") for key in expected}
        resource_id = row["resourceId"]
        if resource_id in seen:
            raise ResourceCatalogError(f"duplicate resourceId {resource_id!r}")
        seen.add(resource_id)
        if row["resourceKind"] not in RESOURCE_KINDS:
            raise ResourceCatalogError(f"unsupported resource kind {row['resourceKind']!r}")
        if row["distributionStatus"] not in SOURCE_AVAILABILITY_STATES:
            raise ResourceCatalogError(f"unsupported source availability {row['distributionStatus']!r}")
        result.append(row)
    return result


def _validate_completed_inventory(value: Mapping[str, Any], repository_root: Path) -> dict[str, dict[str, Any]]:
    _require_keys(value, {"recordedAt", "resources", "schemaVersion", "summary"}, "completed inventory")
    if value["schemaVersion"] != "2.0":
        raise ResourceCatalogError(f"unsupported completed inventory version {value['schemaVersion']!r}")
    _string(value["recordedAt"], "completed inventory recordedAt")
    resources = value["resources"]
    if not isinstance(resources, list):
        raise ResourceCatalogError("completed inventory resources must be a list")

    summary = value["summary"]
    summary_keys = {
        "managedConceptResourceCount",
        "recordOrObservationCount",
        "releaseOrSnapshotCount",
        "resourceCount",
        "sourceConceptReleaseCount",
        "sourceControlledResourceCount",
    }
    if not isinstance(summary, Mapping):
        raise ResourceCatalogError("completed inventory summary must be an object")
    _require_keys(summary, summary_keys, "completed inventory summary")
    if any(
        not isinstance(summary[key], int) or isinstance(summary[key], bool) or summary[key] < 0 for key in summary_keys
    ):
        raise ResourceCatalogError("completed inventory summary counts must be non-negative integers")

    result: dict[str, dict[str, Any]] = {}
    expected_row_keys = {
        "evidencePath",
        "identityStatus",
        "intendedUses",
        "packageClass",
        "packageDigest",
        "recordOrObservationCount",
        "releaseOrSnapshotCount",
        "resourceId",
        "title",
    }
    for index, raw in enumerate(resources):
        if not isinstance(raw, Mapping):
            raise ResourceCatalogError(f"completed resources[{index}] must be an object")
        _require_keys(raw, expected_row_keys, f"completed resources[{index}]")
        resource_id = _string(raw.get("resourceId"), f"completed resources[{index}].resourceId")
        if resource_id in result:
            raise ResourceCatalogError(f"completed inventory repeats {resource_id!r}")
        evidence_path = _relative_path(raw.get("evidencePath"), f"completed {resource_id}.evidencePath")
        _repository_file(repository_root, evidence_path.as_posix(), f"completed {resource_id}.evidencePath")
        package_class = _string(raw.get("packageClass"), f"completed {resource_id}.packageClass")
        if package_class not in {
            "managedConceptRelease",
            "sourceConceptRelease",
            "sourceControlledResource",
        }:
            raise ResourceCatalogError(f"completed {resource_id}.packageClass is unsupported")
        intended_uses = raw.get("intendedUses")
        if (
            not isinstance(intended_uses, Sequence)
            or isinstance(intended_uses, (str, bytes))
            or not intended_uses
            or len(set(intended_uses)) != len(intended_uses)
        ):
            raise ResourceCatalogError(f"completed {resource_id}.intendedUses must be a non-empty unique list")
        normalized_uses = sorted(
            _string(item, f"completed {resource_id}.intendedUses[{use_index}]")
            for use_index, item in enumerate(intended_uses)
        )
        for count_field in ("recordOrObservationCount", "releaseOrSnapshotCount"):
            count = raw.get(count_field)
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                raise ResourceCatalogError(f"completed {resource_id}.{count_field} must be a positive integer")
        result[resource_id] = {
            "evidencePath": evidence_path.as_posix(),
            "identityStatus": _string(raw.get("identityStatus"), f"completed {resource_id}.identityStatus"),
            "intendedUses": normalized_uses,
            "packageClass": package_class,
            "packageDigest": _digest(raw.get("packageDigest"), f"completed {resource_id}.packageDigest"),
        }

    expected_summary = {
        "managedConceptResourceCount": sum(row["packageClass"] == "managedConceptRelease" for row in resources),
        "recordOrObservationCount": sum(row["recordOrObservationCount"] for row in resources),
        "releaseOrSnapshotCount": sum(row["releaseOrSnapshotCount"] for row in resources),
        "resourceCount": len(resources),
        "sourceConceptReleaseCount": sum(row["packageClass"] == "sourceConceptRelease" for row in resources),
        "sourceControlledResourceCount": sum(row["packageClass"] == "sourceControlledResource" for row in resources),
    }
    if dict(summary) != expected_summary:
        raise ResourceCatalogError("completed inventory summary is stale")
    return result


def _validate_distributions(
    value: Mapping[str, Any],
    repository_root: Path,
    completed: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    _require_keys(value, {"distributions", "format"}, "portable distribution inventory")
    if value["format"] != DISTRIBUTION_INPUT_FORMAT:
        raise ResourceCatalogError(f"unsupported distribution inventory format {value['format']!r}")
    rows = value["distributions"]
    if not isinstance(rows, list):
        raise ResourceCatalogError("portable distributions must be a list")

    result: dict[str, list[dict[str, Any]]] = {}
    seen_packages: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise ResourceCatalogError(f"distributions[{index}] must be an object")
        _require_keys(
            raw,
            {"distributionKind", "files", "manifestPath", "packageResourceId", "resourceId"},
            f"distributions[{index}]",
        )
        resource_id = _string(raw["resourceId"], f"distributions[{index}].resourceId")
        package_resource_id = _string(raw["packageResourceId"], f"distributions[{index}].packageResourceId")
        if package_resource_id in seen_packages:
            raise ResourceCatalogError(f"portable distributions repeat package {package_resource_id!r}")
        seen_packages.add(package_resource_id)
        completed_row = completed.get(package_resource_id)
        if completed_row is None:
            raise ResourceCatalogError(f"portable distributions lack completed evidence: {[package_resource_id]!r}")
        manifest_path = _relative_path(raw["manifestPath"], f"distribution {resource_id}.manifestPath")
        manifest_file = _repository_file(
            repository_root, manifest_path.as_posix(), f"distribution {resource_id}.manifestPath"
        )
        files = raw["files"]
        if not isinstance(files, list) or not files:
            raise ResourceCatalogError(f"distribution {resource_id}.files must be non-empty")
        checked_files: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        checked_digests: dict[str, str] = {}
        for file_index, file_row in enumerate(files):
            if not isinstance(file_row, Mapping):
                raise ResourceCatalogError(f"distribution {resource_id}.files[{file_index}] must be an object")
            _require_keys(file_row, {"path", "sha256"}, f"distribution {resource_id}.files[{file_index}]")
            path = _relative_path(file_row["path"], f"distribution {resource_id}.files[{file_index}].path")
            if path.as_posix() in seen_paths:
                raise ResourceCatalogError(f"distribution {resource_id} repeats path {path}")
            seen_paths.add(path.as_posix())
            expected_digest = _digest(file_row["sha256"], f"distribution {resource_id}.files[{file_index}].sha256")
            actual_digest = _file_digest(
                _repository_file(
                    repository_root, path.as_posix(), f"distribution {resource_id}.files[{file_index}].path"
                )
            )
            if actual_digest != expected_digest:
                raise ResourceCatalogError(
                    f"distribution {resource_id} digest mismatch for {path}: expected {expected_digest}, got {actual_digest}"
                )
            checked_files.append({"path": path.as_posix(), "sha256": expected_digest})
            checked_digests[path.as_posix()] = expected_digest
        if manifest_path.as_posix() not in seen_paths:
            raise ResourceCatalogError(f"distribution {resource_id} files do not include its manifest")
        distribution_kind = _string(raw["distributionKind"], f"distribution {resource_id}.distributionKind")
        location = f"distribution {resource_id}/{package_resource_id}"
        if distribution_kind == _SOURCE_CONTROLLED_RESOURCE_DISTRIBUTION_KIND:
            _verify_source_controlled_resource_distribution(
                manifest_file=manifest_file,
                inventory_paths=seen_paths,
                completed_row=completed_row,
                repository_root=repository_root,
                location=location,
            )
        elif distribution_kind == _SOURCE_CONCEPT_RELEASE_DISTRIBUTION_KIND:
            _verify_source_concept_release_distribution(
                manifest_file=manifest_file,
                inventory_paths=seen_paths,
                inventory_digests=checked_digests,
                completed_row=completed_row,
                repository_root=repository_root,
                location=location,
            )
        else:
            raise ResourceCatalogError(f"distribution {resource_id}.distributionKind is unsupported")
        distribution = {
            "distributionKind": distribution_kind,
            "files": sorted(checked_files, key=lambda row: row["path"]),
            "manifestDigest": _file_digest(manifest_file),
            "manifestPath": manifest_path.as_posix(),
            "packageResourceId": package_resource_id,
        }
        result.setdefault(resource_id, []).append(distribution)
    for resource_distributions in result.values():
        resource_distributions.sort(key=lambda row: row["packageResourceId"])
    return result


def build_resource_catalog(
    inventory: Mapping[str, Any],
    completed_inventory: Mapping[str, Any],
    distribution_inventory: Mapping[str, Any],
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Join planning, evidence, and portable-byte facts into one catalog."""

    resources = _validate_inventory(inventory)
    completed = _validate_completed_inventory(completed_inventory, repository_root)
    distributions = _validate_distributions(distribution_inventory, repository_root, completed)
    resource_ids = {row["resourceId"] for row in resources}
    if unknown := set(distributions) - resource_ids:
        raise ResourceCatalogError(f"portable inventory names unknown resources: {sorted(unknown)}")
    distribution_packages = {row["packageResourceId"] for rows in distributions.values() for row in rows}
    if unknown := set(completed) - resource_ids - distribution_packages:
        raise ResourceCatalogError(f"completed inventory names unknown resources: {sorted(unknown)}")
    if unproven := distribution_packages - set(completed):
        raise ResourceCatalogError(f"portable distributions lack completed evidence: {sorted(unproven)}")

    catalog_resources: list[dict[str, Any]] = []
    for source in sorted(resources, key=lambda row: row["resourceId"]):
        resource_id = source["resourceId"]
        resource_distributions = distributions.get(resource_id, [])
        evidence_ids = {resource_id} & set(completed)
        evidence_ids.update(row["packageResourceId"] for row in resource_distributions)
        evidence = [completed[item] for item in sorted(evidence_ids)]
        catalog_resources.append(
            {
                "consumability": (
                    "verifiedDistribution"
                    if resource_distributions
                    else "evidenceOnly"
                    if evidence
                    else "inventoryOnly"
                ),
                "distributions": resource_distributions,
                "evidence": evidence,
                "gap": source["accessOrReproducibilityGap"],
                "identifierRepresentation": source["identifierRepresentation"],
                "officialLocator": source["officialLocator"],
                "resourceId": resource_id,
                "resourceKind": source["resourceKind"],
                "sourceAvailability": source["distributionStatus"],
                "title": source["title"],
                "versionRepresentation": source["versionRepresentation"],
            }
        )

    payload: dict[str, Any] = {
        "experimental": True,
        "format": CATALOG_FORMAT,
        "recordedAt": inventory["recordedAt"],
        "resources": catalog_resources,
        "summary": {
            "evidenceOnlyCount": sum(1 for row in catalog_resources if row["consumability"] == "evidenceOnly"),
            "inventoryOnlyCount": sum(1 for row in catalog_resources if row["consumability"] == "inventoryOnly"),
            "resourceCount": len(resources),
            "verifiedDistributionCount": sum(len(rows) for rows in distributions.values()),
            "verifiedResourceCount": len(distributions),
        },
    }
    digest = canonical_sha256(payload)
    return {
        **payload,
        "catalogDigest": digest,
        "catalogId": f"urn:ref:resource-catalog:{digest.removeprefix('sha256:')}",
    }


def validate_resource_catalog(
    catalog: Mapping[str, Any],
    inventory: Mapping[str, Any],
    completed_inventory: Mapping[str, Any],
    distribution_inventory: Mapping[str, Any],
    *,
    repository_root: Path,
) -> None:
    """Require exact deterministic regeneration of an experimental catalog."""

    expected = build_resource_catalog(
        inventory,
        completed_inventory,
        distribution_inventory,
        repository_root=repository_root,
    )
    if catalog != expected:
        raise ResourceCatalogError("checked resource catalog differs from deterministic generation")


def verified_distribution_ids(catalog: Mapping[str, Any]) -> frozenset[str]:
    """Return resources whose exact repository-contained bytes were verified."""

    if catalog.get("format") != CATALOG_FORMAT:
        raise ResourceCatalogError(f"unsupported resource catalog format {catalog.get('format')!r}")
    resources = catalog.get("resources")
    if not isinstance(resources, Sequence) or isinstance(resources, (str, bytes)):
        raise ResourceCatalogError("resource catalog resources must be a list")
    return frozenset(
        _string(row.get("resourceId"), "catalog resourceId")
        for row in resources
        if isinstance(row, Mapping) and row.get("consumability") == "verifiedDistribution"
    )
