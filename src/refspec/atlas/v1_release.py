"""Build one immutable six-release Vocabulary Atlas v1 publication.

The release definition is a canonical, content-derived JSON record.  It pins
the planning index, each exact concept release, every relation bundle, and the
qualified Crosswalk proof sources needed to reopen those bundles.  The build
then creates a published scope, canonical Atlas 2.0 distribution, publication
decision, static package, acceptance record, and one summary that pins every
generated file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from refspec import binding
from refspec.atlas_index import PinnedAtlasIndex
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    require_aware_datetime_text,
)

from .atlas_scope import (
    AtlasScopeRelease,
    PinnedVocabularyAtlasScope,
    VocabularyAtlasScope,
)
from .concept_release import (
    ConceptReleaseSource,
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
    PinnedSourceConceptRelease,
)
from .federal_register import PinnedFederalRegisterManagedConceptRelease
from .icpsr import PinnedIcpsrManagedConceptRelease
from .machine_evidence import PinnedCrosswalkMachineProof
from .model import VocabularyAtlasAsset, build_vocabulary_atlas
from .publication import (
    EXPLORER_DATA,
    AtlasPublication,
    publish_vocabulary_atlas,
)
from .publication_decision import (
    build_vocabulary_atlas_publication_decision,
    read_vocabulary_atlas_publication_decision,
)
from .relation_assertion import PinnedRelationAssertionBundle
from .release_acceptance import (
    VocabularyAtlasReleaseAcceptance,
    build_vocabulary_atlas_release_acceptance,
    read_vocabulary_atlas_release_acceptance,
)

VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_TYPE = "VocabularyAtlasV1ReleaseDefinition"
VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_VERSION = "1.0"
VOCABULARY_ATLAS_V1_BUILD_RESULT_TYPE = "VocabularyAtlasV1BuildResult"
VOCABULARY_ATLAS_V1_BUILD_RESULT_VERSION = "1.0"

ReleaseKind = Literal[
    "sourceConceptRelease",
    "managedConceptRelease",
    "federalRegisterManagedConceptRelease",
    "icpsrManagedConceptRelease",
]

_DEFINITION_ID_PREFIX = "urn:ref:vocabulary-atlas-v1-release-definition:"
_BUILD_RESULT_ID_PREFIX = "urn:ref:vocabulary-atlas-v1-build-result:"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_KEY = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_RINGS = frozenset({"subject", "entity", "value", "legalIdentity"})
_RELEASE_KINDS = frozenset(
    {
        "sourceConceptRelease",
        "managedConceptRelease",
        "federalRegisterManagedConceptRelease",
        "icpsrManagedConceptRelease",
    }
)
_MANAGED_KINDS = _RELEASE_KINDS - {"sourceConceptRelease"}
_POLICY_ROLES = frozenset({"selectionPolicy", "qualificationPolicy"})
_EXCEPTION_KINDS = frozenset({"developmentOnly", "rights"})

_DEFINITION_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "releaseName",
        "scopeName",
        "scopeKind",
        "title",
        "planningIndex",
        "releases",
        "relationBundles",
        "publication",
        "expectedCounts",
    }
)
_DEFINITION_RECORD_FIELDS = _DEFINITION_BASIS_FIELDS | {"id", "recordDigest"}
_PLANNING_INDEX_FIELDS = frozenset(
    {
        "path",
        "fileDigest",
        "inputPath",
        "inputFileDigest",
        "resourceCatalogPath",
        "resourceCatalogFileDigest",
        "repositoryRoot",
    }
)
_RELEASE_BASE_FIELDS = frozenset(
    {
        "key",
        "kind",
        "label",
        "manifestPath",
        "manifestDigest",
        "releaseId",
        "semanticRing",
    }
)
_RING_ASSIGNMENT_FIELDS = frozenset({"assignedBy", "assignedAt", "evidence"})
_RELATION_FIELDS = frozenset(
    {
        "key",
        "manifestPath",
        "manifestDigest",
        "semanticRing",
        "releaseIds",
        "machineProofs",
    }
)
_PROOF_FIELDS = frozenset(
    {
        "crosswalkPath",
        "crosswalkFileDigest",
        "crosswalkBundleDigest",
        "candidateId",
        "qualificationRun",
    }
)
_QUALIFICATION_RUN_FIELDS = frozenset({"path", "fileDigest", "contentDigest"})
_PUBLICATION_FIELDS = frozenset(
    {
        "decisionActor",
        "decidedAt",
        "policies",
        "exceptions",
        "supersedes",
        "acceptanceChecks",
    }
)
_POLICY_FIELDS = frozenset({"role", "id", "version", "contentDigest"})
_EXCEPTION_FIELDS = frozenset({"kind", "appliesTo", "statement"})
_SUPERSESSION_FIELDS = frozenset({"id", "recordDigest"})
_CHECK_FIELDS = frozenset({"id", "statement", "status", "evidence"})
_EXPECTED_COUNT_FIELDS = frozenset(
    {
        "releaseCount",
        "planningRowCount",
        "includedPlanningRowCount",
        "conceptTotal",
        "conceptsByRelease",
        "nativeRelationTotal",
        "nativeRelationsByRelease",
        "mappingMinimumTotal",
        "mappingMinimumByRelation",
    }
)
_BUILD_RESULT_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "releaseName",
        "status",
        "releaseDefinition",
        "scope",
        "atlas",
        "publicationDecision",
        "publication",
        "acceptance",
        "counts",
        "reproducibility",
        "artifacts",
    }
)
_BUILD_RESULT_RECORD_FIELDS = _BUILD_RESULT_BASIS_FIELDS | {
    "id",
    "recordDigest",
}


class VocabularyAtlasV1ReleaseError(ValueError):
    """The v1 definition, an exact input, or a generated release is invalid."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise VocabularyAtlasV1ReleaseError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VocabularyAtlasV1ReleaseError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _require_array(value: object, label: str, *, nonempty: bool = False) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise VocabularyAtlasV1ReleaseError(f"{label} must be an array")
    if nonempty and not value:
        raise VocabularyAtlasV1ReleaseError(f"{label} must not be empty")
    return cast(Sequence[Any], value)


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise VocabularyAtlasV1ReleaseError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise VocabularyAtlasV1ReleaseError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise VocabularyAtlasV1ReleaseError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise VocabularyAtlasV1ReleaseError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise VocabularyAtlasV1ReleaseError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_datetime(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        return require_aware_datetime_text(text, label=label)
    except SourceIdentityError as error:
        raise VocabularyAtlasV1ReleaseError(str(error)) from error


def _require_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VocabularyAtlasV1ReleaseError(f"{label} must be a non-negative integer")
    return value


def _require_relative_path(value: object, label: str) -> str:
    text = _require_text(value, label)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != text:
        raise VocabularyAtlasV1ReleaseError(f"{label} must be a normalized artifact-root-relative path")
    return text


def _require_key(value: object, label: str) -> str:
    key = _require_text(value, label)
    if _KEY.fullmatch(key) is None:
        raise VocabularyAtlasV1ReleaseError(f"{label} must contain lowercase letters, digits, and internal hyphens")
    return key


def _normalize_unique_iris(value: object, label: str, *, nonempty: bool = True) -> list[str]:
    rows = _require_array(value, label, nonempty=nonempty)
    result = [_require_iri(item, f"{label}[{index}]") for index, item in enumerate(rows)]
    if len(result) != len(set(result)):
        raise VocabularyAtlasV1ReleaseError(f"{label} must contain unique IRIs")
    return sorted(result)


def _normalize_planning_index(value: object) -> dict[str, str]:
    label = "v1 release definition planningIndex"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _PLANNING_INDEX_FIELDS, label)
    return {
        "path": _require_relative_path(row.get("path"), f"{label}.path"),
        "fileDigest": _require_digest(row.get("fileDigest"), f"{label}.fileDigest"),
        "inputPath": _require_relative_path(row.get("inputPath"), f"{label}.inputPath"),
        "inputFileDigest": _require_digest(row.get("inputFileDigest"), f"{label}.inputFileDigest"),
        "resourceCatalogPath": _require_relative_path(row.get("resourceCatalogPath"), f"{label}.resourceCatalogPath"),
        "resourceCatalogFileDigest": _require_digest(
            row.get("resourceCatalogFileDigest"),
            f"{label}.resourceCatalogFileDigest",
        ),
        "repositoryRoot": _require_relative_path(row.get("repositoryRoot"), f"{label}.repositoryRoot"),
    }


def _normalize_ring_assignment(value: object, label: str) -> dict[str, Any]:
    row = _require_mapping(value, label)
    _require_exact_fields(row, _RING_ASSIGNMENT_FIELDS, label)
    return {
        "assignedBy": _require_iri(row.get("assignedBy"), f"{label}.assignedBy"),
        "assignedAt": _require_datetime(row.get("assignedAt"), f"{label}.assignedAt"),
        "evidence": _normalize_unique_iris(row.get("evidence"), f"{label}.evidence"),
    }


def _normalize_releases(value: object) -> list[dict[str, Any]]:
    rows = _require_array(value, "v1 release definition releases", nonempty=True)
    if len(rows) != 6:
        raise VocabularyAtlasV1ReleaseError("v1 release definition must name exactly six concept releases")
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    release_ids: set[str] = set()
    kind_counts = {kind: 0 for kind in _RELEASE_KINDS}
    for index, raw in enumerate(rows):
        label = f"v1 release definition releases[{index}]"
        row = _require_mapping(raw, label)
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in _RELEASE_KINDS:
            raise VocabularyAtlasV1ReleaseError(f"{label}.kind is unsupported")
        expected = _RELEASE_BASE_FIELDS | ({"ringAssignment"} if kind in _MANAGED_KINDS else set())
        _require_exact_fields(row, frozenset(expected), label)
        key = _require_key(row.get("key"), f"{label}.key")
        release_id = _require_iri(row.get("releaseId"), f"{label}.releaseId")
        if key in keys or release_id in release_ids:
            raise VocabularyAtlasV1ReleaseError("v1 release definition repeats a release key or releaseId")
        keys.add(key)
        release_ids.add(release_id)
        ring = row.get("semanticRing")
        if not isinstance(ring, str) or ring not in _RINGS:
            raise VocabularyAtlasV1ReleaseError(f"{label}.semanticRing is unsupported")
        if (
            kind
            in {
                "federalRegisterManagedConceptRelease",
                "icpsrManagedConceptRelease",
            }
            and ring != "subject"
        ):
            raise VocabularyAtlasV1ReleaseError(f"{label}.semanticRing must be subject for this specialized release")
        normalized: dict[str, Any] = {
            "key": key,
            "kind": kind,
            "label": _require_text(row.get("label"), f"{label}.label"),
            "manifestPath": _require_relative_path(row.get("manifestPath"), f"{label}.manifestPath"),
            "manifestDigest": _require_digest(row.get("manifestDigest"), f"{label}.manifestDigest"),
            "releaseId": release_id,
            "semanticRing": ring,
        }
        if kind in _MANAGED_KINDS:
            normalized["ringAssignment"] = _normalize_ring_assignment(
                row.get("ringAssignment"), f"{label}.ringAssignment"
            )
        result.append(normalized)
        kind_counts[kind] += 1
    if kind_counts != {
        "sourceConceptRelease": 3,
        "managedConceptRelease": 1,
        "federalRegisterManagedConceptRelease": 1,
        "icpsrManagedConceptRelease": 1,
    }:
        raise VocabularyAtlasV1ReleaseError(
            "v1 requires three source releases plus one generic, one Federal Register, and one ICPSR managed release"
        )
    return sorted(result, key=lambda row: row["key"])


def _normalize_qualification_run(value: object, label: str) -> dict[str, str]:
    row = _require_mapping(value, label)
    _require_exact_fields(row, _QUALIFICATION_RUN_FIELDS, label)
    return {
        "path": _require_relative_path(row.get("path"), f"{label}.path"),
        "fileDigest": _require_digest(row.get("fileDigest"), f"{label}.fileDigest"),
        "contentDigest": _require_digest(row.get("contentDigest"), f"{label}.contentDigest"),
    }


def _normalize_machine_proofs(value: object, label: str) -> list[dict[str, Any]]:
    rows = _require_array(value, label)
    result: list[dict[str, Any]] = []
    candidates: set[tuple[str, str]] = set()
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _PROOF_FIELDS, item_label)
        normalized = {
            "crosswalkPath": _require_relative_path(row.get("crosswalkPath"), f"{item_label}.crosswalkPath"),
            "crosswalkFileDigest": _require_digest(
                row.get("crosswalkFileDigest"),
                f"{item_label}.crosswalkFileDigest",
            ),
            "crosswalkBundleDigest": _require_digest(
                row.get("crosswalkBundleDigest"),
                f"{item_label}.crosswalkBundleDigest",
            ),
            "candidateId": _require_iri(row.get("candidateId"), f"{item_label}.candidateId"),
            "qualificationRun": _normalize_qualification_run(
                row.get("qualificationRun"), f"{item_label}.qualificationRun"
            ),
        }
        key = (normalized["crosswalkPath"], normalized["candidateId"])
        if key in candidates:
            raise VocabularyAtlasV1ReleaseError(f"{label} repeats a Crosswalk candidate proof")
        candidates.add(key)
        result.append(normalized)
    return sorted(
        result,
        key=lambda row: (row["crosswalkPath"], row["candidateId"]),
    )


def _normalize_relation_bundles(
    value: object,
    *,
    release_ids: frozenset[str],
) -> list[dict[str, Any]]:
    rows = _require_array(value, "v1 release definition relationBundles", nonempty=True)
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, raw in enumerate(rows):
        label = f"v1 release definition relationBundles[{index}]"
        row = _require_mapping(raw, label)
        _require_exact_fields(row, _RELATION_FIELDS, label)
        key = _require_key(row.get("key"), f"{label}.key")
        if key in keys:
            raise VocabularyAtlasV1ReleaseError("v1 release definition repeats a relation-bundle key")
        keys.add(key)
        ring = row.get("semanticRing")
        if ring != "subject":
            raise VocabularyAtlasV1ReleaseError(f"{label}.semanticRing must be subject for the v1 mapping set")
        endpoints = _normalize_unique_iris(row.get("releaseIds"), f"{label}.releaseIds")
        if len(endpoints) < 2 or not set(endpoints) <= release_ids:
            raise VocabularyAtlasV1ReleaseError(f"{label}.releaseIds must name at least two v1 releases")
        result.append(
            {
                "key": key,
                "manifestPath": _require_relative_path(row.get("manifestPath"), f"{label}.manifestPath"),
                "manifestDigest": _require_digest(row.get("manifestDigest"), f"{label}.manifestDigest"),
                "semanticRing": "subject",
                "releaseIds": endpoints,
                "machineProofs": _normalize_machine_proofs(row.get("machineProofs"), f"{label}.machineProofs"),
            }
        )
    return sorted(result, key=lambda row: row["key"])


def _normalize_policies(value: object, label: str) -> list[dict[str, str]]:
    rows = _require_array(value, label, nonempty=True)
    result: list[dict[str, str]] = []
    roles: set[str] = set()
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _POLICY_FIELDS, item_label)
        role = row.get("role")
        if not isinstance(role, str) or role not in _POLICY_ROLES:
            raise VocabularyAtlasV1ReleaseError(f"{item_label}.role must be selectionPolicy or qualificationPolicy")
        if role in roles:
            raise VocabularyAtlasV1ReleaseError(f"{label} must contain one policy for each required role")
        roles.add(role)
        result.append(
            {
                "role": role,
                "id": _require_iri(row.get("id"), f"{item_label}.id"),
                "version": _require_text(row.get("version"), f"{item_label}.version"),
                "contentDigest": _require_digest(row.get("contentDigest"), f"{item_label}.contentDigest"),
            }
        )
    if roles != _POLICY_ROLES:
        raise VocabularyAtlasV1ReleaseError(f"{label} must contain selectionPolicy and qualificationPolicy")
    return sorted(result, key=lambda row: (row["role"], row["id"]))


def _normalize_exceptions(
    value: object,
    label: str,
    *,
    release_ids: frozenset[str],
) -> list[dict[str, str]]:
    rows = _require_array(value, label)
    result: list[dict[str, str]] = []
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _EXCEPTION_FIELDS, item_label)
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in _EXCEPTION_KINDS:
            raise VocabularyAtlasV1ReleaseError(f"{item_label}.kind is unsupported")
        applies_to = _require_iri(row.get("appliesTo"), f"{item_label}.appliesTo")
        if applies_to not in release_ids:
            raise VocabularyAtlasV1ReleaseError(f"{item_label}.appliesTo must name an included release")
        result.append(
            {
                "kind": kind,
                "appliesTo": applies_to,
                "statement": _require_text(row.get("statement"), f"{item_label}.statement"),
            }
        )
    canonical_rows = [_canonical_bytes(row) for row in result]
    if len(canonical_rows) != len(set(canonical_rows)):
        raise VocabularyAtlasV1ReleaseError(f"{label} repeats an exception")
    return sorted(
        result,
        key=lambda row: (row["kind"], row["appliesTo"], row["statement"]),
    )


def _normalize_supersedes(value: object, label: str) -> list[dict[str, str]]:
    rows = _require_array(value, label)
    result: list[dict[str, str]] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _SUPERSESSION_FIELDS, item_label)
        identifier = _require_iri(row.get("id"), f"{item_label}.id")
        if identifier in identifiers:
            raise VocabularyAtlasV1ReleaseError(f"{label} repeats an id")
        identifiers.add(identifier)
        result.append(
            {
                "id": identifier,
                "recordDigest": _require_digest(row.get("recordDigest"), f"{item_label}.recordDigest"),
            }
        )
    return sorted(result, key=lambda row: row["id"])


def _normalize_checks(value: object, label: str) -> list[dict[str, Any]]:
    rows = _require_array(value, label, nonempty=True)
    result: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _CHECK_FIELDS, item_label)
        identifier = _require_iri(row.get("id"), f"{item_label}.id")
        if identifier in identifiers:
            raise VocabularyAtlasV1ReleaseError(f"{label} repeats an id")
        identifiers.add(identifier)
        if row.get("status") != "passed":
            raise VocabularyAtlasV1ReleaseError(f"{item_label}.status must be passed")
        result.append(
            {
                "id": identifier,
                "statement": _require_text(row.get("statement"), f"{item_label}.statement"),
                "status": "passed",
                "evidence": _normalize_unique_iris(row.get("evidence"), f"{item_label}.evidence"),
            }
        )
    return sorted(result, key=lambda row: row["id"])


def _normalize_publication(
    value: object,
    *,
    release_ids: frozenset[str],
) -> dict[str, Any]:
    label = "v1 release definition publication"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _PUBLICATION_FIELDS, label)
    return {
        "decisionActor": _require_iri(row.get("decisionActor"), f"{label}.decisionActor"),
        "decidedAt": _require_datetime(row.get("decidedAt"), f"{label}.decidedAt"),
        "policies": _normalize_policies(row.get("policies"), f"{label}.policies"),
        "exceptions": _normalize_exceptions(
            row.get("exceptions"),
            f"{label}.exceptions",
            release_ids=release_ids,
        ),
        "supersedes": _normalize_supersedes(row.get("supersedes"), f"{label}.supersedes"),
        "acceptanceChecks": _normalize_checks(row.get("acceptanceChecks"), f"{label}.acceptanceChecks"),
    }


def _normalize_count_map(
    value: object,
    label: str,
    *,
    expected_keys: frozenset[str] | None = None,
) -> dict[str, int]:
    row = _require_mapping(value, label)
    result = {_require_iri(key, f"{label} key"): _require_count(item, f"{label}[{key!r}]") for key, item in row.items()}
    if expected_keys is not None and set(result) != expected_keys:
        raise VocabularyAtlasV1ReleaseError(f"{label} must name every and only included release")
    return {key: result[key] for key in sorted(result)}


def _normalize_expected_counts(
    value: object,
    *,
    release_ids: frozenset[str],
) -> dict[str, Any]:
    label = "v1 release definition expectedCounts"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _EXPECTED_COUNT_FIELDS, label)
    release_count = _require_count(row.get("releaseCount"), f"{label}.releaseCount")
    if release_count != 6:
        raise VocabularyAtlasV1ReleaseError(f"{label}.releaseCount must be six")
    concepts = _normalize_count_map(
        row.get("conceptsByRelease"),
        f"{label}.conceptsByRelease",
        expected_keys=release_ids,
    )
    native = _normalize_count_map(
        row.get("nativeRelationsByRelease"),
        f"{label}.nativeRelationsByRelease",
        expected_keys=release_ids,
    )
    concept_total = _require_count(row.get("conceptTotal"), f"{label}.conceptTotal")
    native_total = _require_count(row.get("nativeRelationTotal"), f"{label}.nativeRelationTotal")
    if sum(concepts.values()) != concept_total:
        raise VocabularyAtlasV1ReleaseError(f"{label}.conceptTotal differs from conceptsByRelease")
    if sum(native.values()) != native_total:
        raise VocabularyAtlasV1ReleaseError(f"{label}.nativeRelationTotal differs from nativeRelationsByRelease")
    mapping_minima = _normalize_count_map(
        row.get("mappingMinimumByRelation"),
        f"{label}.mappingMinimumByRelation",
    )
    mapping_minimum_total = _require_count(row.get("mappingMinimumTotal"), f"{label}.mappingMinimumTotal")
    if sum(mapping_minima.values()) > mapping_minimum_total:
        raise VocabularyAtlasV1ReleaseError(f"{label}.mappingMinimumTotal must cover every predicate minimum")
    return {
        "releaseCount": release_count,
        "planningRowCount": _require_count(row.get("planningRowCount"), f"{label}.planningRowCount"),
        "includedPlanningRowCount": _require_count(
            row.get("includedPlanningRowCount"),
            f"{label}.includedPlanningRowCount",
        ),
        "conceptTotal": concept_total,
        "conceptsByRelease": concepts,
        "nativeRelationTotal": native_total,
        "nativeRelationsByRelease": native,
        "mappingMinimumTotal": mapping_minimum_total,
        "mappingMinimumByRelation": mapping_minima,
    }


def _normalize_definition_basis(value: object) -> dict[str, Any]:
    label = "v1 release definition"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _DEFINITION_BASIS_FIELDS, label)
    if row.get("type") != VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_TYPE:
        raise VocabularyAtlasV1ReleaseError(f"{label}.type must be {VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_TYPE}")
    if row.get("schemaVersion") != VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_VERSION:
        raise VocabularyAtlasV1ReleaseError(
            f"{label}.schemaVersion must be {VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_VERSION}"
        )
    releases = _normalize_releases(row.get("releases"))
    release_ids = frozenset(cast(str, release["releaseId"]) for release in releases)
    return {
        "type": VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_TYPE,
        "schemaVersion": VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_VERSION,
        "releaseName": _require_iri(row.get("releaseName"), f"{label}.releaseName"),
        "scopeName": _require_iri(row.get("scopeName"), f"{label}.scopeName"),
        "scopeKind": ("published" if row.get("scopeKind") == "published" else _raise_scope_kind()),
        "title": _require_text(row.get("title"), f"{label}.title"),
        "planningIndex": _normalize_planning_index(row.get("planningIndex")),
        "releases": releases,
        "relationBundles": _normalize_relation_bundles(row.get("relationBundles"), release_ids=release_ids),
        "publication": _normalize_publication(row.get("publication"), release_ids=release_ids),
        "expectedCounts": _normalize_expected_counts(row.get("expectedCounts"), release_ids=release_ids),
    }


def _raise_scope_kind() -> str:
    raise VocabularyAtlasV1ReleaseError("v1 release definition scopeKind must be published")


@dataclass(frozen=True, slots=True)
class VocabularyAtlasV1ReleaseDefinition:
    """One canonical, content-derived definition for the six-release build."""

    record: Mapping[str, Any]
    file_digest: str | None = None

    def __post_init__(self) -> None:
        row = _require_mapping(self.record, "v1 release definition")
        _require_exact_fields(row, _DEFINITION_RECORD_FIELDS, "v1 release definition")
        basis = _normalize_definition_basis({field: row[field] for field in _DEFINITION_BASIS_FIELDS})
        digest = sha256_digest(_canonical_bytes(basis))
        expected = {
            **basis,
            "id": _DEFINITION_ID_PREFIX + digest.removeprefix("sha256:"),
            "recordDigest": digest,
        }
        if _plain(row) != expected:
            raise VocabularyAtlasV1ReleaseError("v1 release definition identity, inputs, or canonical order differs")
        if self.file_digest is not None:
            _require_digest(self.file_digest, "v1 release definition file digest")
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(expected)),
        )

    @classmethod
    def seal(cls, basis: Mapping[str, Any]) -> VocabularyAtlasV1ReleaseDefinition:
        """Normalize a definition basis and derive its immutable identity."""

        normalized = _normalize_definition_basis(basis)
        digest = sha256_digest(_canonical_bytes(normalized))
        return cls(
            {
                **normalized,
                "id": _DEFINITION_ID_PREFIX + digest.removeprefix("sha256:"),
                "recordDigest": digest,
            }
        )

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def record_digest(self) -> str:
        return cast(str, self.record["recordDigest"])

    def as_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self.record))

    def artifact_bytes(self) -> bytes:
        return _canonical_bytes(self.as_record())

    def write_to(self, path: Path | str) -> Path:
        """Write a newly sealed definition once so it can receive an external pin."""

        return _write_new_file(
            Path(path),
            self.artifact_bytes(),
            label="v1 release definition",
        )


def read_vocabulary_atlas_v1_release_definition(
    path: Path | str,
    *,
    expected_file_digest: str,
) -> VocabularyAtlasV1ReleaseDefinition:
    """Open one canonical tracked definition from an independent file digest."""

    digest = _require_digest(expected_file_digest, "v1 release definition file digest")
    payload = _read_regular_file(Path(path), label="v1 release definition")
    if sha256_digest(payload) != digest:
        raise VocabularyAtlasV1ReleaseError("v1 release definition file digest differs")
    value = _decode_json(payload, "v1 release definition")
    if not isinstance(value, Mapping) or _canonical_bytes(value) != payload:
        raise VocabularyAtlasV1ReleaseError("v1 release definition bytes are not canonical")
    definition = VocabularyAtlasV1ReleaseDefinition(value, file_digest=digest)
    if _read_regular_file(Path(path), label="v1 release definition") != payload:
        raise VocabularyAtlasV1ReleaseError("v1 release definition changed while opening")
    return definition


def _decode_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise VocabularyAtlasV1ReleaseError(f"{label} must be valid UTF-8 JSON") from error


def _read_regular_file(path: Path, *, label: str) -> bytes:
    if path.is_symlink():
        raise VocabularyAtlasV1ReleaseError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1ReleaseError(f"{label} does not exist") from error
    if not resolved.is_file():
        raise VocabularyAtlasV1ReleaseError(f"{label} must be a regular file")
    return resolved.read_bytes()


def _artifact_root(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise VocabularyAtlasV1ReleaseError("artifact root must not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1ReleaseError("artifact root does not exist") from error
    if not resolved.is_dir():
        raise VocabularyAtlasV1ReleaseError("artifact root must be a directory")
    return resolved


def _resolve_inside(
    root: Path,
    relative: str,
    *,
    label: str,
    directory: bool = False,
) -> Path:
    path = PurePosixPath(_require_relative_path(relative, label))
    candidate = root.joinpath(*path.parts)
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise VocabularyAtlasV1ReleaseError(f"{label} must not traverse a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1ReleaseError(f"{label} does not exist") from error
    except ValueError as error:
        raise VocabularyAtlasV1ReleaseError(f"{label} must stay inside the artifact root") from error
    if directory and not resolved.is_dir():
        raise VocabularyAtlasV1ReleaseError(f"{label} must be a directory")
    if not directory and not resolved.is_file():
        raise VocabularyAtlasV1ReleaseError(f"{label} must be a regular file")
    return resolved


def _exact_file(
    root: Path,
    relative: str,
    digest: str,
    *,
    label: str,
) -> Path:
    path = _resolve_inside(root, relative, label=label)
    payload = path.read_bytes()
    if sha256_digest(payload) != digest:
        raise VocabularyAtlasV1ReleaseError(f"{label} differs from its exact digest")
    if path.read_bytes() != payload:
        raise VocabularyAtlasV1ReleaseError(f"{label} changed while opening")
    return path


def _exact_json(
    root: Path,
    relative: str,
    digest: str,
    *,
    label: str,
) -> Mapping[str, Any]:
    path = _exact_file(root, relative, digest, label=label)
    value = _decode_json(path.read_bytes(), label)
    if not isinstance(value, Mapping):
        raise VocabularyAtlasV1ReleaseError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _open_planning_index(
    definition: VocabularyAtlasV1ReleaseDefinition,
    root: Path,
) -> PinnedAtlasIndex:
    descriptor = cast(Mapping[str, Any], definition.record["planningIndex"])
    index_path = _exact_file(
        root,
        cast(str, descriptor["path"]),
        cast(str, descriptor["fileDigest"]),
        label="v1 planning index",
    )
    index_input = _exact_json(
        root,
        cast(str, descriptor["inputPath"]),
        cast(str, descriptor["inputFileDigest"]),
        label="v1 planning index input",
    )
    resource_catalog = _exact_json(
        root,
        cast(str, descriptor["resourceCatalogPath"]),
        cast(str, descriptor["resourceCatalogFileDigest"]),
        label="v1 resource catalog",
    )
    repository_root = _resolve_inside(
        root,
        cast(str, descriptor["repositoryRoot"]),
        label="v1 planning-index repository root",
        directory=True,
    )
    return PinnedAtlasIndex.open(
        index_path,
        expected_file_digest=cast(str, descriptor["fileDigest"]),
        index_input=index_input,
        resource_catalog=resource_catalog,
        repository_root=repository_root,
    )


def _write_new_file(path: Path, payload: bytes, *, label: str) -> Path:
    if path.exists() or path.is_symlink():
        raise VocabularyAtlasV1ReleaseError(f"{label} already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


def _open_releases(
    definition: VocabularyAtlasV1ReleaseDefinition,
    root: Path,
    assignment_directory: Path,
) -> tuple[
    tuple[AtlasScopeRelease, ...],
    Mapping[str, ConceptReleaseSource],
    Mapping[str, str],
]:
    scope_releases: list[AtlasScopeRelease] = []
    sources: dict[str, ConceptReleaseSource] = {}
    labels: dict[str, str] = {}
    for raw in cast(Sequence[Mapping[str, Any]], definition.record["releases"]):
        key = cast(str, raw["key"])
        kind = cast(ReleaseKind, raw["kind"])
        release_id = cast(str, raw["releaseId"])
        manifest_digest = cast(str, raw["manifestDigest"])
        manifest_path = _exact_file(
            root,
            cast(str, raw["manifestPath"]),
            manifest_digest,
            label=f"v1 release {key} manifest",
        )
        if kind == "sourceConceptRelease":
            source: ConceptReleaseSource = PinnedSourceConceptRelease.open(
                manifest_path,
                expected_manifest_digest=manifest_digest,
            )
        else:
            assignment_values = cast(Mapping[str, Any], raw["ringAssignment"])
            assignment = ManagedReleaseRingAssignment(
                managed_manifest_digest=manifest_digest,
                release_id=release_id,
                semantic_ring=cast(Any, raw["semanticRing"]),
                assigned_by=cast(str, assignment_values["assignedBy"]),
                assigned_at=cast(str, assignment_values["assignedAt"]),
                evidence=tuple(cast(Sequence[str], assignment_values["evidence"])),
            )
            assignment_path = assignment_directory / f"{key}.json"
            assignment.write_to(assignment_path)
            pinned_assignment = PinnedManagedReleaseRingAssignment.open(
                assignment_path,
                expected_file_digest=sha256_digest(assignment.artifact_bytes()),
            )
            release_class = {
                "managedConceptRelease": PinnedManagedConceptRelease,
                "federalRegisterManagedConceptRelease": PinnedFederalRegisterManagedConceptRelease,
                "icpsrManagedConceptRelease": PinnedIcpsrManagedConceptRelease,
            }[kind]
            source = release_class.open(
                manifest_path,
                expected_manifest_digest=manifest_digest,
                release_id=release_id,
                ring_assignment=pinned_assignment,
            )
        pin = source.pin()
        if (
            pin.get("releaseId") != release_id
            or pin.get("manifestDigest") != manifest_digest
            or pin.get("semanticRing") != raw["semanticRing"]
        ):
            raise VocabularyAtlasV1ReleaseError(f"v1 release {key} differs from its definition")
        scope_releases.append(AtlasScopeRelease(source))
        sources[release_id] = source
        labels[release_id] = cast(str, raw["label"])
    return tuple(scope_releases), sources, labels


def _open_relation_bundles(
    definition: VocabularyAtlasV1ReleaseDefinition,
    root: Path,
    release_sources: Mapping[str, ConceptReleaseSource],
) -> tuple[PinnedRelationAssertionBundle, ...]:
    result: list[PinnedRelationAssertionBundle] = []
    for raw in cast(Sequence[Mapping[str, Any]], definition.record["relationBundles"]):
        key = cast(str, raw["key"])
        proofs: list[PinnedCrosswalkMachineProof] = []
        for proof_row in cast(Sequence[Mapping[str, Any]], raw["machineProofs"]):
            crosswalk_path = _exact_file(
                root,
                cast(str, proof_row["crosswalkPath"]),
                cast(str, proof_row["crosswalkFileDigest"]),
                label=f"v1 relation {key} CrosswalkBundle",
            )
            run = cast(Mapping[str, Any], proof_row["qualificationRun"])
            run_path = _exact_file(
                root,
                cast(str, run["path"]),
                cast(str, run["fileDigest"]),
                label=f"v1 relation {key} qualification run",
            )
            proof = PinnedCrosswalkMachineProof.qualified(
                crosswalk_path,
                expected_file_digest=cast(str, proof_row["crosswalkFileDigest"]),
                expected_bundle_digest=cast(str, proof_row["crosswalkBundleDigest"]),
                candidate_id=cast(str, proof_row["candidateId"]),
                qualification_run_path=run_path,
                expected_qualification_run_file_digest=cast(str, run["fileDigest"]),
                expected_qualification_run_content_digest=cast(str, run["contentDigest"]),
            )
            facts = proof.verified_facts()
            if not {facts.source_release, facts.target_release} <= set(raw["releaseIds"]):
                raise VocabularyAtlasV1ReleaseError(f"v1 relation {key} proof endpoints are outside its descriptor")
            proofs.append(proof)
        manifest_path = _exact_file(
            root,
            cast(str, raw["manifestPath"]),
            cast(str, raw["manifestDigest"]),
            label=f"v1 relation {key} manifest",
        )
        release_ids = cast(Sequence[str], raw["releaseIds"])
        bundle = PinnedRelationAssertionBundle.open(
            manifest_path,
            expected_manifest_digest=cast(str, raw["manifestDigest"]),
            release_sources=tuple(release_sources[release_id] for release_id in release_ids),
            machine_proof_sources=tuple(proofs),
        )
        if bundle.semantic_ring != raw["semanticRing"]:
            raise VocabularyAtlasV1ReleaseError(f"v1 relation {key} semantic ring differs from its descriptor")
        result.append(bundle)
    return tuple(result)


def _rows_by_key(
    rows: object,
    *,
    key: str,
    label: str,
) -> dict[str, int]:
    values = _require_array(rows, label)
    result: dict[str, int] = {}
    for index, raw in enumerate(values):
        row = _require_mapping(raw, f"{label}[{index}]")
        name = _require_text(row.get(key), f"{label}[{index}].{key}")
        if name in result:
            raise VocabularyAtlasV1ReleaseError(f"{label} repeats {name!r}")
        result[name] = _require_count(row.get("count"), f"{label}[{index}].count")
    return result


def validate_vocabulary_atlas_v1_acceptance(
    definition: VocabularyAtlasV1ReleaseDefinition,
    acceptance: VocabularyAtlasReleaseAcceptance,
) -> None:
    """Check v1's exact release counts, mapping floors, and reproducibility."""

    expected = cast(Mapping[str, Any], definition.record["expectedCounts"])
    counts = _require_mapping(acceptance.record.get("counts"), "v1 acceptance counts")
    concepts = _require_mapping(counts.get("concepts"), "v1 acceptance concepts")
    native = _require_mapping(counts.get("nativeRelations"), "v1 acceptance nativeRelations")
    mappings = _require_mapping(counts.get("mappingAssertions"), "v1 acceptance mappingAssertions")
    facets = _require_mapping(counts.get("facets"), "v1 acceptance facets")
    concept_by_release = _rows_by_key(
        concepts.get("byRelease"),
        key="releaseId",
        label="v1 acceptance concepts.byRelease",
    )
    native_by_release = _rows_by_key(
        native.get("byRelease"),
        key="releaseId",
        label="v1 acceptance nativeRelations.byRelease",
    )
    mapping_by_relation = _rows_by_key(
        mappings.get("byRelation"),
        key="value",
        label="v1 acceptance mappingAssertions.byRelation",
    )
    exact_pairs = (
        (concepts.get("total"), expected["conceptTotal"], "concept total"),
        (
            native.get("total"),
            expected["nativeRelationTotal"],
            "native-relation total",
        ),
        (
            facets.get("rowCount"),
            expected["planningRowCount"],
            "planning-row total",
        ),
        (
            facets.get("includedReleaseRowCount"),
            expected["includedPlanningRowCount"],
            "included planning-row total",
        ),
    )
    for observed, wanted, label in exact_pairs:
        if observed != wanted:
            raise VocabularyAtlasV1ReleaseError(f"v1 {label} is {observed!r}; expected {wanted!r}")
    if concept_by_release != _plain(expected["conceptsByRelease"]):
        raise VocabularyAtlasV1ReleaseError("v1 concept counts by release differ from the release definition")
    if native_by_release != _plain(expected["nativeRelationsByRelease"]):
        raise VocabularyAtlasV1ReleaseError("v1 native-relation counts by release differ from the release definition")
    if len(concept_by_release) != expected["releaseCount"]:
        raise VocabularyAtlasV1ReleaseError("v1 acceptance does not contain exactly six release snapshots")
    mapping_total = _require_count(mappings.get("total"), "v1 acceptance mappingAssertions.total")
    if mapping_total < expected["mappingMinimumTotal"]:
        raise VocabularyAtlasV1ReleaseError("v1 mapping count is below its declared release floor")
    for relation, minimum in cast(Mapping[str, int], expected["mappingMinimumByRelation"]).items():
        if mapping_by_relation.get(relation, 0) < minimum:
            raise VocabularyAtlasV1ReleaseError(f"v1 mapping count for {relation} is below its declared floor")

    evidence = _require_mapping(counts.get("evidence"), "v1 acceptance evidence")
    machine_proof_total = _require_count(
        evidence.get("machineProofTotal"),
        "v1 acceptance evidence.machineProofTotal",
    )
    reproducibility_rows = _require_array(
        acceptance.record.get("reproducibility"),
        "v1 acceptance reproducibility",
    )
    statuses = {
        cast(str, _require_mapping(row, "v1 acceptance reproducibility row")["layer"]): cast(
            str, _require_mapping(row, "v1 acceptance reproducibility row")["status"]
        )
        for row in reproducibility_rows
    }
    for layer in (
        "planningIndex",
        "sourceConceptReleases",
        "scope",
        "atlas",
        "explorer",
    ):
        if statuses.get(layer) != "reproduced":
            raise VocabularyAtlasV1ReleaseError(f"v1 deterministic layer {layer} was not reproduced")
    expected_machine_status = "pinnedNonReproducible" if machine_proof_total else "notApplicable"
    if statuses.get("machineQualificationEvidence") != expected_machine_status:
        raise VocabularyAtlasV1ReleaseError("v1 machine-evidence reproducibility status differs from its contents")


def _artifact_role(path: str) -> str:
    name = PurePosixPath(path).name
    if path.startswith("control/ring-assignments/"):
        return "managedReleaseRingAssignment"
    return {
        "atlas-scope.json": "vocabularyAtlasScope",
        "atlas-manifest.json": "vocabularyAtlasManifest",
        "atlas.nq": "vocabularyAtlasData",
        "publication-decision.json": "publicationDecision",
        "publication-manifest.json": "publicationManifest",
        "release-acceptance.json": "releaseAcceptance",
    }.get(name, "publicationMember")


def _generated_artifacts(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise VocabularyAtlasV1ReleaseError("generated v1 release must not contain symlinks")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        result.append(
            {
                "path": relative,
                "role": _artifact_role(relative),
                "fileDigest": sha256_digest(payload),
                "byteLength": len(payload),
            }
        )
    return result


def _seal_build_result(basis: Mapping[str, Any]) -> dict[str, Any]:
    _require_exact_fields(
        basis,
        _BUILD_RESULT_BASIS_FIELDS,
        "v1 build result basis",
    )
    digest = sha256_digest(_canonical_bytes(basis))
    return {
        **_plain(basis),
        "id": _BUILD_RESULT_ID_PREFIX + digest.removeprefix("sha256:"),
        "recordDigest": digest,
    }


def _validate_build_result(value: object) -> dict[str, Any]:
    row = _require_mapping(value, "v1 build result")
    _require_exact_fields(row, _BUILD_RESULT_RECORD_FIELDS, "v1 build result")
    if row.get("type") != VOCABULARY_ATLAS_V1_BUILD_RESULT_TYPE:
        raise VocabularyAtlasV1ReleaseError("v1 build result type is unsupported")
    if row.get("schemaVersion") != VOCABULARY_ATLAS_V1_BUILD_RESULT_VERSION:
        raise VocabularyAtlasV1ReleaseError("v1 build result schemaVersion is unsupported")
    if row.get("status") != "passed":
        raise VocabularyAtlasV1ReleaseError("v1 build result status must be passed")
    basis = {field: _plain(row[field]) for field in _BUILD_RESULT_BASIS_FIELDS}
    expected = _seal_build_result(basis)
    if _plain(row) != expected:
        raise VocabularyAtlasV1ReleaseError("v1 build result identity or content digest differs")
    return expected


@dataclass(frozen=True, slots=True)
class VocabularyAtlasV1Build:
    """The reopened result of one successful atomic v1 build."""

    output_directory: Path
    result: Mapping[str, Any]
    result_file_digest: str

    @property
    def identifier(self) -> str:
        return cast(str, self.result["id"])


def _build_in_staging(
    definition: VocabularyAtlasV1ReleaseDefinition,
    root: Path,
    staging: Path,
) -> dict[str, Any]:
    index = _open_planning_index(definition, root)
    assignment_directory = staging / "control" / "ring-assignments"
    assignment_directory.mkdir(parents=True)
    scope_releases, release_sources, release_labels = _open_releases(
        definition,
        root,
        assignment_directory,
    )
    relation_bundles = _open_relation_bundles(
        definition,
        root,
        release_sources,
    )
    scope = VocabularyAtlasScope.create(
        scope_name=cast(str, definition.record["scopeName"]),
        scope_kind="published",
        atlas_index=index,
        releases=scope_releases,
        relation_bundles=relation_bundles,
    )
    scope_path = scope.write_to(staging / "control" / "atlas-scope.json")
    pinned_scope = PinnedVocabularyAtlasScope.open(
        scope_path,
        expected_file_digest=sha256_digest(scope.artifact_bytes()),
        atlas_index=index,
        releases=scope_releases,
        relation_bundles=relation_bundles,
    )

    built_atlas = build_vocabulary_atlas(pinned_scope)
    canonical_directory = built_atlas.write(staging / "canonical")
    atlas = VocabularyAtlasAsset.reproduce_from_scope(
        canonical_directory,
        scope=pinned_scope,
        expected_manifest_digest=built_atlas.manifest_digest,
    )
    if atlas.manifest_bytes() != built_atlas.manifest_bytes():
        raise VocabularyAtlasV1ReleaseError("reopened v1 Atlas differs from its deterministic build")

    publication_values = cast(Mapping[str, Any], definition.record["publication"])
    decision = build_vocabulary_atlas_publication_decision(
        pinned_scope,
        artifact_kind="atlas",
        policies=cast(Sequence[Mapping[str, Any]], publication_values["policies"]),
        decision_actor=cast(str, publication_values["decisionActor"]),
        decided_at=cast(str, publication_values["decidedAt"]),
        result={
            "role": "VocabularyAtlas",
            "id": cast(str, atlas.manifest["id"]),
            "manifestDigest": atlas.manifest_digest,
            "distributionDigest": atlas.output_digest,
        },
        exceptions=cast(Sequence[Mapping[str, Any]], publication_values["exceptions"]),
        supersedes=cast(Sequence[Mapping[str, Any]], publication_values["supersedes"]),
    )
    decision_path = decision.write_to(staging / "control" / "publication-decision.json")
    decision_file_digest = sha256_digest(decision.artifact_bytes())
    decision = read_vocabulary_atlas_publication_decision(
        decision_path,
        expected_file_digest=decision_file_digest,
    )

    publication = publish_vocabulary_atlas(
        atlas,
        staging / "public",
        decision=decision,
        planning_index=index,
        title=cast(str, definition.record["title"]),
        release_labels=release_labels,
    )
    publication = AtlasPublication.open(
        publication.directory,
        expected_manifest_digest=publication.manifest_digest,
    )
    if (
        publication.distribution.manifest_digest != atlas.manifest_digest
        or publication.distribution.output_digest != atlas.output_digest
    ):
        raise VocabularyAtlasV1ReleaseError("reopened v1 publication names another canonical Atlas")
    explorer_payload = _read_regular_file(
        publication.directory / EXPLORER_DATA,
        label="v1 publication explorer",
    )
    explorer = _decode_json(explorer_payload, "v1 publication explorer")
    if not isinstance(explorer, Mapping) or _canonical_bytes(explorer) != explorer_payload:
        raise VocabularyAtlasV1ReleaseError("v1 publication explorer bytes are not canonical")

    acceptance = build_vocabulary_atlas_release_acceptance(
        atlas,
        scope=pinned_scope,
        planning_index=index,
        publication_decision=decision,
        explorer=explorer,
        checks=cast(Sequence[Mapping[str, Any]], publication_values["acceptanceChecks"]),
    )
    validate_vocabulary_atlas_v1_acceptance(definition, acceptance)
    acceptance_path = acceptance.write_to(staging / "control" / "release-acceptance.json")
    acceptance_file_digest = sha256_digest(acceptance.artifact_bytes())
    reopened_acceptance = read_vocabulary_atlas_release_acceptance(
        acceptance_path,
        expected_file_digest=acceptance_file_digest,
    )
    reopened_acceptance.validate_inputs(
        atlas,
        scope=pinned_scope,
        planning_index=index,
        publication_decision=decision,
        explorer=explorer,
    )

    definition_file_digest = definition.file_digest or sha256_digest(definition.artifact_bytes())
    basis = {
        "type": VOCABULARY_ATLAS_V1_BUILD_RESULT_TYPE,
        "schemaVersion": VOCABULARY_ATLAS_V1_BUILD_RESULT_VERSION,
        "releaseName": definition.record["releaseName"],
        "status": "passed",
        "releaseDefinition": {
            "id": definition.identifier,
            "recordDigest": definition.record_digest,
            "fileDigest": definition_file_digest,
        },
        "scope": pinned_scope.pin(),
        "atlas": {
            "role": "VocabularyAtlas",
            "id": atlas.manifest["id"],
            "manifestDigest": atlas.manifest_digest,
            "distributionDigest": atlas.output_digest,
        },
        "publicationDecision": {
            "id": decision.identifier,
            "recordDigest": decision.record_digest,
            "fileDigest": decision_file_digest,
        },
        "publication": {
            "id": publication.manifest["id"],
            "manifestDigest": publication.manifest_digest,
        },
        "acceptance": {
            "id": reopened_acceptance.identifier,
            "recordDigest": reopened_acceptance.record_digest,
            "fileDigest": acceptance_file_digest,
        },
        "counts": _plain(reopened_acceptance.record["counts"]),
        "reproducibility": _plain(reopened_acceptance.record["reproducibility"]),
        "artifacts": _generated_artifacts(staging),
    }
    result = _seal_build_result(basis)
    _write_new_file(
        staging / "build-result.json",
        _canonical_bytes(result),
        label="v1 build result",
    )
    return result


def build_vocabulary_atlas_v1_release(
    definition: VocabularyAtlasV1ReleaseDefinition,
    *,
    artifact_root: Path | str,
    output_directory: Path | str,
) -> VocabularyAtlasV1Build:
    """Build, verify, and atomically place one six-release Atlas v1."""

    if not isinstance(definition, VocabularyAtlasV1ReleaseDefinition):
        raise VocabularyAtlasV1ReleaseError("v1 build requires an exact VocabularyAtlasV1ReleaseDefinition")
    root = _artifact_root(artifact_root)
    destination = Path(output_directory)
    if destination.exists() or destination.is_symlink():
        raise VocabularyAtlasV1ReleaseError(f"v1 output destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    parent = destination.parent.resolve(strict=True)
    if parent.is_symlink():
        raise VocabularyAtlasV1ReleaseError("v1 output parent must not be a symlink")
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=parent))
    try:
        result = _build_in_staging(definition, root, staging)
        if destination.exists() or destination.is_symlink():
            raise VocabularyAtlasV1ReleaseError(f"v1 output destination appeared during the build: {destination}")
        os.rename(staging, destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    result_path = destination / "build-result.json"
    payload = _read_regular_file(result_path, label="v1 build result")
    reopened = _decode_json(payload, "v1 build result")
    if not isinstance(reopened, Mapping) or _canonical_bytes(reopened) != payload:
        raise VocabularyAtlasV1ReleaseError("v1 build result bytes are not canonical")
    normalized_result = _validate_build_result(reopened)
    if normalized_result != result:
        raise VocabularyAtlasV1ReleaseError("placed v1 build result differs from the verified staging result")
    return VocabularyAtlasV1Build(
        output_directory=destination.resolve(strict=True),
        result=cast(Mapping[str, Any], deep_freeze_json(normalized_result)),
        result_file_digest=sha256_digest(payload),
    )


__all__ = [
    "VOCABULARY_ATLAS_V1_BUILD_RESULT_TYPE",
    "VOCABULARY_ATLAS_V1_BUILD_RESULT_VERSION",
    "VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_TYPE",
    "VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_VERSION",
    "ReleaseKind",
    "VocabularyAtlasV1Build",
    "VocabularyAtlasV1ReleaseDefinition",
    "VocabularyAtlasV1ReleaseError",
    "build_vocabulary_atlas_v1_release",
    "read_vocabulary_atlas_v1_release_definition",
    "validate_vocabulary_atlas_v1_acceptance",
]
