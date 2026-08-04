"""Build the non-authorizing registry source and atlas planning index.

The resource catalog records what resources exist and which exact portable
distributions are available. This index places every registry source in one
semantic ring and records how subject sources participate in the vocabulary
atlas. Neither artifact grants a product permission.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from refspec.binding import CORE_FACETS, canonical_sha256
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseError,
    SourceConceptReleaseView,
)

ATLAS_INDEX_INPUT_FORMAT = "refspec-atlas-index-input/experimental-v0"
ATLAS_INDEX_FORMAT = "refspec-atlas-index/experimental-v0"

SEMANTIC_RINGS = frozenset({"entity", "legalIdentity", "subject", "value"})
ATLAS_PARTICIPATION = frozenset({"bridge", "core", "specialist"})
PLANNING_STATUSES = frozenset({"deferred", "notApplicable", "planned", "rejected", "superseded", "unassessed"})
INTENDED_USES = frozenset(
    {
        "candidateGeneration",
        "candidateRanking",
        "deterministicMetadata",
        "entityResolution",
        "facetedRetrieval",
        "legalIdentityResolution",
        "mappingReference",
        "navigation",
        "rankingSignal",
        "schemaInterpretation",
        "searchExpansion",
        "sourceAssignedEvidence",
    }
)
READINESS_EVIDENCE_KINDS = frozenset(
    {
        "evaluation",
        "managedReleaseValidation",
        "parserTest",
        "qualification",
        "sourceConceptReleaseValidation",
        "sourceImplementation",
        "sourceObservation",
    }
)
ASSIGNMENT_ROLES = frozenset(
    {
        "https://rulespec.org/ns/v1#assignmentContextual",
        "https://rulespec.org/ns/v1#assignmentMention",
        "https://rulespec.org/ns/v1#assignmentPrimary",
        "https://rulespec.org/ns/v1#assignmentSubstantive",
    }
)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_MODULE = re.compile(r"^[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+$")
_PERMISSION_SHAPED_FIELDS = frozenset(
    {
        "acceptedOutputUseAuthorized",
        "authorized",
        "candidateUseAuthorized",
        "eligible",
        "permission",
        "ready",
    }
)


class AtlasIndexError(ValueError):
    """Raised when the atlas index is incomplete, unsafe, or not closed."""


def _require_keys(value: Mapping[str, Any], expected: set[str], location: str) -> None:
    actual = set(value)
    if actual != expected:
        raise AtlasIndexError(
            f"{location} keys differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AtlasIndexError(f"{location} must be a non-empty trimmed string")
    return value


def _digest(value: Any, location: str) -> str:
    result = _string(value, location)
    if not _SHA256.fullmatch(result):
        raise AtlasIndexError(f"{location} must be a lowercase SHA-256 digest")
    return result


def _relative_path(value: Any, location: str) -> PurePosixPath:
    text = _string(value, location)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != text:
        raise AtlasIndexError(f"{location} must be a normalized repository-relative path")
    return path


def _repository_file(root: Path, value: Any, location: str) -> tuple[str, Path]:
    relative = _relative_path(value, location)
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise AtlasIndexError(f"{location} does not name a checked regular file: {relative}")
    return relative.as_posix(), candidate


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _closed_string(value: Any, allowed: frozenset[str], location: str) -> str:
    result = _string(value, location)
    if result not in allowed:
        raise AtlasIndexError(f"{location} is unsupported: {result!r}")
    return result


def _closed_strings(value: Any, allowed: frozenset[str], location: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value or len(set(value)) != len(value):
        raise AtlasIndexError(f"{location} must be a non-empty unique list")
    result = [_closed_string(item, allowed, f"{location}[{index}]") for index, item in enumerate(value)]
    return sorted(result)


def _contains_strings(value: Any, required: set[str]) -> bool:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, str) and item in required:
            found.add(item)
        elif isinstance(item, Mapping):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for nested in item:
                visit(nested)

    visit(value)
    return found == required


def _source_concept_release_evidence(
    evidence: Mapping[str, Any],
    *,
    evidence_file: Path,
    release_id: str,
    manifest_digest: str,
    semantic_ring: str,
    repository_root: Path,
    location: str,
) -> None:
    rows = evidence.get("releases")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise AtlasIndexError(f"{location}.evidencePath lacks structured source-concept release rows")
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("releaseId") == release_id
        and row.get("manifestDigest") == manifest_digest
    ]
    if len(matches) != 1:
        raise AtlasIndexError(f"{location}.evidencePath must name one exact source-concept release row")
    match = matches[0]
    if match.get("semanticRing") != semantic_ring:
        raise AtlasIndexError(f"{location} source-concept release semanticRing differs from the index row")
    relative = _relative_path(match.get("path"), f"{location}.evidencePath release path")
    package_manifest = evidence_file.parent.joinpath(*relative.parts, "bundle-manifest.json")
    try:
        package_manifest.resolve(strict=True).relative_to(repository_root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as error:
        raise AtlasIndexError(f"{location} source-concept release package is outside the repository") from error
    try:
        view = SourceConceptReleaseView.open(
            package_manifest,
            expected_manifest_digest=manifest_digest,
        )
    except SourceConceptReleaseError as error:
        raise AtlasIndexError(f"{location} source-concept release package is invalid: {error}") from error
    if view.release_id != release_id or view.semantic_ring != semantic_ring:
        raise AtlasIndexError(f"{location} source-concept release package differs from the index row")


def _release(
    value: Any,
    *,
    repository_root: Path,
    location: str,
    semantic_ring: str,
    require_source_concept_evidence: bool,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise AtlasIndexError(f"{location} must be null or a complete release object")
    _require_keys(value, {"evidencePath", "manifestDigest", "releaseId"}, location)
    release_id = _string(value["releaseId"], f"{location}.releaseId")
    if ":" not in release_id:
        raise AtlasIndexError(f"{location}.releaseId must be an absolute identifier")
    manifest_digest = _digest(value["manifestDigest"], f"{location}.manifestDigest")
    evidence_path, evidence_file = _repository_file(repository_root, value["evidencePath"], f"{location}.evidencePath")
    try:
        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AtlasIndexError(f"{location}.evidencePath must contain UTF-8 JSON") from error
    if not _contains_strings(evidence, {release_id, manifest_digest}):
        raise AtlasIndexError(f"{location}.evidencePath does not record both releaseId and manifestDigest")
    if require_source_concept_evidence:
        if not isinstance(evidence, Mapping):
            raise AtlasIndexError(f"{location}.evidencePath must contain one source-concept evidence object")
        _source_concept_release_evidence(
            evidence,
            evidence_file=evidence_file,
            release_id=release_id,
            manifest_digest=manifest_digest,
            semantic_ring=semantic_ring,
            repository_root=repository_root,
            location=location,
        )
    return {
        "evidencePath": evidence_path,
        "evidenceSha256": _file_digest(evidence_file),
        "manifestDigest": manifest_digest,
        "releaseId": release_id,
    }


def _readiness_evidence(value: Any, *, repository_root: Path, location: str) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise AtlasIndexError(f"{location} must be a non-empty list")
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(value):
        item_location = f"{location}[{index}]"
        if not isinstance(raw, Mapping):
            raise AtlasIndexError(f"{item_location} must be an object")
        _require_keys(raw, {"kind", "path"}, item_location)
        kind = _closed_string(raw["kind"], READINESS_EVIDENCE_KINDS, f"{item_location}.kind")
        path, file = _repository_file(repository_root, raw["path"], f"{item_location}.path")
        key = (kind, path)
        if key in seen:
            raise AtlasIndexError(f"{location} repeats {key!r}")
        seen.add(key)
        result.append({"kind": kind, "path": path, "sha256": _file_digest(file)})
    return sorted(result, key=lambda row: (row["kind"], row["path"]))


def _registry_modules(repository_root: Path, registry_root: Path | None) -> set[str]:
    root = registry_root or repository_root / "src" / "refspec" / "registry"
    if root.is_symlink() or not root.is_dir():
        raise AtlasIndexError(f"registry root is not a regular directory: {root}")
    try:
        relative_root = root.relative_to(repository_root / "src")
    except ValueError as error:
        raise AtlasIndexError("registry root must be inside repository_root/src") from error
    result: set[str] = set()
    for path in root.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        if path.is_symlink() or not path.is_file():
            raise AtlasIndexError(f"registry contains an unsafe module path: {path}")
        relative = relative_root / path.relative_to(root).with_suffix("")
        result.add(".".join(relative.parts))
    if not result:
        raise AtlasIndexError("registry contains no substantive Python modules")
    return result


def _catalog_resource_ids(resource_catalog: Mapping[str, Any]) -> set[str]:
    resources = resource_catalog.get("resources")
    if not isinstance(resources, Sequence) or isinstance(resources, (str, bytes)):
        raise AtlasIndexError("resource catalog resources must be a list")
    result: set[str] = set()
    for index, row in enumerate(resources):
        if not isinstance(row, Mapping):
            raise AtlasIndexError(f"resource catalog resources[{index}] must be an object")
        resource_id = _string(row.get("resourceId"), f"resource catalog resources[{index}].resourceId")
        if resource_id in result:
            raise AtlasIndexError(f"resource catalog repeats resourceId {resource_id!r}")
        result.add(resource_id)
    return result


def build_atlas_index(
    index_input: Mapping[str, Any],
    resource_catalog: Mapping[str, Any],
    *,
    repository_root: Path,
    registry_root: Path | None = None,
) -> dict[str, Any]:
    """Build one exhaustive, content-addressed, non-authorizing atlas index."""

    _require_keys(
        index_input,
        {"format", "implementationModules", "recordedAt", "resourceCatalogDigest", "rows"},
        "atlas index input",
    )
    if index_input["format"] != ATLAS_INDEX_INPUT_FORMAT:
        raise AtlasIndexError(f"unsupported atlas index input format {index_input['format']!r}")
    recorded_at = _string(index_input["recordedAt"], "atlas index input recordedAt")
    catalog_digest = _digest(resource_catalog.get("catalogDigest"), "resource catalog catalogDigest")
    if index_input["resourceCatalogDigest"] != catalog_digest:
        raise AtlasIndexError("atlas index input resourceCatalogDigest does not match the resource catalog")
    catalog_id = _string(resource_catalog.get("catalogId"), "resource catalog catalogId")
    catalog_resource_ids = _catalog_resource_ids(resource_catalog)

    raw_implementation_modules = index_input["implementationModules"]
    if not isinstance(raw_implementation_modules, Sequence) or isinstance(raw_implementation_modules, (str, bytes)):
        raise AtlasIndexError("implementationModules must be a list")
    implementation_modules = [
        _string(value, f"implementationModules[{index}]") for index, value in enumerate(raw_implementation_modules)
    ]
    if len(implementation_modules) != len(set(implementation_modules)):
        raise AtlasIndexError("implementationModules must be unique")
    for module in implementation_modules:
        if not _MODULE.fullmatch(module):
            raise AtlasIndexError(f"implementationModules contains an invalid module name: {module!r}")
    implementation_modules.sort()

    raw_rows = index_input["rows"]
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)) or not raw_rows:
        raise AtlasIndexError("atlas index rows must be a non-empty list")
    expected_row_keys = {
        "assignmentRole",
        "atlasParticipation",
        "facet",
        "intendedUses",
        "planningStatus",
        "semanticRing",
        "readinessEvidence",
        "release",
        "resourceId",
        "sourceModule",
    }
    rows: list[dict[str, Any]] = []
    row_payload_digests: set[str] = set()
    source_modules: set[str] = set()
    for index, raw in enumerate(raw_rows):
        location = f"rows[{index}]"
        if not isinstance(raw, Mapping):
            raise AtlasIndexError(f"{location} must be an object")
        if set(raw) & _PERMISSION_SHAPED_FIELDS:
            raise AtlasIndexError(f"{location} contains a permission-shaped field")
        _require_keys(raw, expected_row_keys, location)
        source_module = _string(raw["sourceModule"], f"{location}.sourceModule")
        if not _MODULE.fullmatch(source_module):
            raise AtlasIndexError(f"{location}.sourceModule must be a dotted Python module")
        source_modules.add(source_module)
        resource_id = _string(raw["resourceId"], f"{location}.resourceId")
        if resource_id not in catalog_resource_ids:
            raise AtlasIndexError(f"{location}.resourceId is absent from the resource catalog: {resource_id!r}")
        facet = _closed_string(raw["facet"], frozenset(CORE_FACETS), f"{location}.facet")
        assignment_role = _closed_string(raw["assignmentRole"], ASSIGNMENT_ROLES, f"{location}.assignmentRole")
        intended_uses = _closed_strings(raw["intendedUses"], INTENDED_USES, f"{location}.intendedUses")
        semantic_ring = _closed_string(raw["semanticRing"], SEMANTIC_RINGS, f"{location}.semanticRing")
        participation_raw = raw["atlasParticipation"]
        participation = (
            None
            if participation_raw is None
            else _closed_string(participation_raw, ATLAS_PARTICIPATION, f"{location}.atlasParticipation")
        )
        if semantic_ring != "subject" and participation is not None:
            raise AtlasIndexError(f"{location} non-subject rows must not claim atlasParticipation")
        if participation == "bridge" and "candidateGeneration" in intended_uses:
            raise AtlasIndexError(f"{location} bridge rows cannot claim candidateGeneration")
        planning_status = _closed_string(raw["planningStatus"], PLANNING_STATUSES, f"{location}.planningStatus")
        readiness = _readiness_evidence(
            raw["readinessEvidence"], repository_root=repository_root, location=f"{location}.readinessEvidence"
        )
        source_concept_validation = any(item["kind"] == "sourceConceptReleaseValidation" for item in readiness)
        release = _release(
            raw["release"],
            repository_root=repository_root,
            location=f"{location}.release",
            semantic_ring=semantic_ring,
            require_source_concept_evidence=source_concept_validation,
        )
        if release is None and source_concept_validation:
            raise AtlasIndexError(f"{location} sourceConceptReleaseValidation evidence requires an exact release")
        if release is not None and not any(
            item["kind"] in {"managedReleaseValidation", "sourceConceptReleaseValidation"} for item in readiness
        ):
            raise AtlasIndexError(f"{location} exact releases require release-validation evidence")
        row_payload = {
            "assignmentRole": assignment_role,
            "atlasParticipation": participation,
            "facet": facet,
            "intendedUses": intended_uses,
            "planningStatus": planning_status,
            "semanticRing": semantic_ring,
            "readinessEvidence": readiness,
            "release": release,
            "resourceId": resource_id,
            "sourceModule": source_module,
        }
        row_digest = canonical_sha256(row_payload)
        if row_digest in row_payload_digests:
            raise AtlasIndexError(f"atlas index repeats an exact row payload at {location}")
        row_payload_digests.add(row_digest)
        rows.append(
            {
                **row_payload,
                "rowDigest": row_digest,
                "rowId": f"urn:ref:atlas-index-row:{row_digest.removeprefix('sha256:')}",
            }
        )

    discovered_modules = _registry_modules(repository_root, registry_root)
    implementation_set = set(implementation_modules)
    if overlap := source_modules & implementation_set:
        raise AtlasIndexError(f"source and implementation module classifications overlap: {sorted(overlap)}")
    classified_modules = source_modules | implementation_set
    if classified_modules != discovered_modules:
        raise AtlasIndexError(
            "registry module classification differs; "
            f"missing={sorted(discovered_modules - classified_modules)}, "
            f"unknown={sorted(classified_modules - discovered_modules)}"
        )

    rows.sort(
        key=lambda row: (
            row["sourceModule"],
            row["resourceId"],
            row["facet"],
            row["assignmentRole"],
            row["semanticRing"],
            row["atlasParticipation"] or "",
            row["planningStatus"],
            row["rowDigest"],
        )
    )
    ring_counts = {ring: sum(row["semanticRing"] == ring for row in rows) for ring in sorted(SEMANTIC_RINGS)}
    participation_counts = {
        participation: sum(row["atlasParticipation"] == participation for row in rows)
        for participation in sorted(ATLAS_PARTICIPATION)
    }
    status_counts = {
        status: sum(row["planningStatus"] == status for row in rows) for status in sorted(PLANNING_STATUSES)
    }
    payload: dict[str, Any] = {
        "experimental": True,
        "format": ATLAS_INDEX_FORMAT,
        "implementationModules": implementation_modules,
        "nonAuthorizing": True,
        "recordedAt": recorded_at,
        "resourceCatalogDigest": catalog_digest,
        "resourceCatalogId": catalog_id,
        "rows": rows,
        "summary": {
            "exactReleaseCount": sum(row["release"] is not None for row in rows),
            "implementationModuleCount": len(implementation_modules),
            "participationCounts": participation_counts,
            "semanticRingCounts": ring_counts,
            "rowCount": len(rows),
            "sourceModuleCount": len(source_modules),
            "statusCounts": status_counts,
        },
    }
    index_digest = canonical_sha256(payload)
    return {
        **payload,
        "indexDigest": index_digest,
        "indexId": f"urn:ref:atlas-index:{index_digest.removeprefix('sha256:')}",
    }


def validate_atlas_index(
    index: Mapping[str, Any],
    index_input: Mapping[str, Any],
    resource_catalog: Mapping[str, Any],
    *,
    repository_root: Path,
    registry_root: Path | None = None,
) -> None:
    """Require exact deterministic regeneration of an atlas index."""

    expected = build_atlas_index(
        index_input,
        resource_catalog,
        repository_root=repository_root,
        registry_root=registry_root,
    )
    if index != expected:
        raise AtlasIndexError("checked atlas index differs from deterministic generation")


def atlas_index_rows(index: Mapping[str, Any], *, semantic_ring: str | None = None) -> tuple[Mapping[str, Any], ...]:
    """Return planning rows, optionally filtered by semantic ring; never authorize use."""

    if index.get("format") != ATLAS_INDEX_FORMAT or index.get("nonAuthorizing") is not True:
        raise AtlasIndexError("unsupported or authorizing atlas index")
    if semantic_ring is not None and semantic_ring not in SEMANTIC_RINGS:
        raise AtlasIndexError(f"unsupported semantic ring {semantic_ring!r}")
    rows = index.get("rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise AtlasIndexError("atlas index rows must be a list")
    return tuple(
        row
        for row in rows
        if isinstance(row, Mapping) and (semantic_ring is None or row.get("semanticRing") == semantic_ring)
    )


__all__ = [
    "ATLAS_INDEX_FORMAT",
    "ATLAS_INDEX_INPUT_FORMAT",
    "AtlasIndexError",
    "atlas_index_rows",
    "build_atlas_index",
    "validate_atlas_index",
]
