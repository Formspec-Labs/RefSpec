"""Canonical logical snapshots for exact four-ring atlas releases.

An :class:`AtlasReleaseSnapshot` copies the complete logical facts needed by
the canonical atlas from one path-backed :class:`AtlasScopeRelease`.  The
snapshot is content-derived and deliberately carries no admission, emission,
or use permission.  ``from_record`` verifies a snapshot from its own JSON
facts; ``verify_against`` additionally reopens the exact release files named
by an atlas scope.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from typing_extensions import Self

from refspec import binding
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    canonical_jsonl_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import (
    absolute_uri_issue,
    is_sha256_digest,
)
from refspec.registry.infrastructure.semantic_foundation import (
    SEMANTIC_RINGS,
    RightsMetadata,
    SemanticFoundationError,
    SemanticRing,
)
from refspec.registry.infrastructure.source_concept_release import (
    SOURCE_CONCEPT_ISSUER_IRI,
    SOURCE_CONCEPT_RELEASE_VERSION,
    SourceConceptReleaseError,
    SourceConceptReleaseView,
    source_scoped_concept_iri,
)

from .atlas_scope import AtlasScopeRelease
from .concept_release import (
    ConceptReleaseError,
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedSourceConceptRelease,
    normalize_concept_release_pin,
    verified_concept_release_facts,
)

ATLAS_RELEASE_SNAPSHOT_TYPE = "AtlasReleaseSnapshot"
ATLAS_RELEASE_SNAPSHOT_VERSION = "1.1"
_SUPPORTED_SNAPSHOT_VERSIONS = frozenset({"1.0", ATLAS_RELEASE_SNAPSHOT_VERSION})

_COMMON_BASIS_FIELDS = {
    "type",
    "schemaVersion",
    "releasePin",
}
_SOURCE_BASIS_FIELDS = _COMMON_BASIS_FIELDS | {
    "releaseBundleManifest",
    "releaseManifest",
    "concepts",
    "rightsMetadata",
    "lifecycleRecords",
    "sourceResourceManifest",
    "sourceCoverageReport",
    "sourceObservations",
}
_MANAGED_BASIS_FIELDS_V1 = _COMMON_BASIS_FIELDS | {
    "ringAssignment",
    "selectedReleaseGraph",
    "members",
}
_MANAGED_BASIS_FIELDS = _COMMON_BASIS_FIELDS | {
    "ringAssignment",
    "selectedReleaseGraph",
    "memberIds",
}
_IDENTITY_FIELDS = {"id", "contentDigest"}
_SOURCE_MANIFEST_FIELDS = {
    "type",
    "schemaVersion",
    "semanticRing",
    "issuer",
    "sourceScheme",
    "sourceCapture",
    "identityPolicy",
    "selectionPolicy",
    "selectedObservationSetDigest",
    "membershipMode",
    "conceptCount",
    "conceptSetDigest",
    "rightsRecordCount",
    "rightsSetDigest",
    "lifecycleRecordCount",
    "lifecycleSetDigest",
    "id",
    "releaseDigest",
}
_SOURCE_BUNDLE_MANIFEST_FIELDS = {
    "schemaVersion",
    "packageKind",
    "releaseId",
    "releaseDigest",
    "logicalDigest",
    "artifacts",
}
_SOURCE_RESOURCE_REQUIRED_FIELDS = {
    "schemaVersion",
    "id",
    "resourceId",
    "title",
    "resourceKind",
    "identityStatus",
    "conceptIdentityClaimed",
    "capturedAt",
    "uses",
    "observationCount",
    "observationSetDigest",
    "sourceArtifacts",
}
_SOURCE_RESOURCE_OPTIONAL_FIELDS = {"registrationEvent", "sourceScheme"}
_SOURCE_COVERAGE_BASE_FIELDS = {
    "schemaVersion",
    "resourceManifest",
    "reportStatus",
    "sourceObservedCount",
    "parsedCount",
    "packagedCount",
    "excludedCount",
    "failedCount",
    "observationSetDigest",
    "gaps",
}
_SOURCE_COVERAGE_OPTIONAL_FIELDS = {
    "localRecordIdSetDigest",
    "localRecordContentSetDigest",
}
_SOURCE_CONCEPT_FIELDS = {
    "id",
    "type",
    "semanticRing",
    "identityKind",
    "issuer",
    "sourceScheme",
    "sourceObservation",
    "sourceObservationDigest",
}
_LIFECYCLE_FIELDS = {
    "id",
    "eventType",
    "semanticRing",
    "effectiveAt",
    "priorConcepts",
    "resultingConcepts",
    "evidence",
    "reviewedBy",
    "reviewedAt",
}
_FORBIDDEN_POLICY_FIELDS = frozenset(
    {
        "acceptedOutputAllowed",
        "acceptedOutputUseAuthorized",
        "admission",
        "admissionReview",
        "admitted",
        "authorization",
        "authorized",
        "candidateLookupAllowed",
        "candidateUseAuthorized",
        "emissionAuthorized",
        "outputProfile",
        "permission",
        "productPolicy",
        "usageCeiling",
    }
)
_RELEASE_TYPES = frozenset(
    {
        "rkaf:ReferenceResourceRelease",
        "https://rulespec.org/ns/v1#ReferenceResourceRelease",
    }
)
_COMPLETE_MEMBERSHIP = frozenset(
    {
        "rkaf:completeMembership",
        "https://rulespec.org/ns/v1#completeMembership",
    }
)
_LIFECYCLE_TYPES = frozenset(
    {
        "rkaf:LifecycleEvent",
        "https://rulespec.org/ns/v1#LifecycleEvent",
    }
)
_RIGHTS_TYPES = frozenset(
    {
        "dcterms:LicenseDocument",
        "http://purl.org/dc/terms/LicenseDocument",
        "rkaf:RightsMetadata",
        "rkaf:RightsStatement",
        "https://rulespec.org/ns/v1#RightsMetadata",
        "https://rulespec.org/ns/v1#RightsStatement",
    }
)
_DIRECT_CLOSURE_PREDICATES = frozenset(
    {
        "dcat:accessRights",
        "dcat:distribution",
        "dcterms:accessRights",
        "dcterms:isVersionOf",
        "dcterms:license",
        "dcterms:rights",
        "rkaf:lifecycleEvent",
        "rkaf:rightsMetadata",
        "skos:inScheme",
        "http://purl.org/dc/terms/accessRights",
        "http://purl.org/dc/terms/isVersionOf",
        "http://purl.org/dc/terms/license",
        "http://purl.org/dc/terms/rights",
        "http://www.w3.org/2004/02/skos/core#inScheme",
        "https://rulespec.org/ns/v1#lifecycleEvent",
        "https://rulespec.org/ns/v1#rightsMetadata",
        "https://www.w3.org/ns/dcat#accessRights",
        "https://www.w3.org/ns/dcat#distribution",
    }
)


class AtlasReleaseSnapshotError(ValueError):
    """A logical release snapshot is incomplete or internally inconsistent."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AtlasReleaseSnapshotError(f"{label} must be an object")
    result = _plain(value)
    if not isinstance(result, dict):
        raise AtlasReleaseSnapshotError(f"{label} must be an object")
    return cast(dict[str, Any], result)


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise AtlasReleaseSnapshotError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AtlasReleaseSnapshotError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise AtlasReleaseSnapshotError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise AtlasReleaseSnapshotError(f"{label} must not contain credentials")
    return iri


def _require_ring(value: object, label: str) -> SemanticRing:
    if not isinstance(value, str) or value not in SEMANTIC_RINGS:
        raise AtlasReleaseSnapshotError(f"{label} must be subject, entity, value, or legalIdentity")
    return cast(SemanticRing, value)


def _require_digest(value: object, label: str) -> str:
    if not is_sha256_digest(value):
        raise AtlasReleaseSnapshotError(f"{label} must be a SHA-256 digest")
    return cast(str, value)


def _validate_nullable_json(value: Any, path: str) -> None:
    """Validate exact external evidence that may itself contain JSON null."""

    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        if abs(value) > binding.SAFE_INTEGER:
            raise AtlasReleaseSnapshotError(f"{path}: integer exceeds the interoperable JSON range")
        return
    if isinstance(value, float):
        raise AtlasReleaseSnapshotError(f"{path}: floating-point numbers are not canonical")
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_nullable_json(child, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise AtlasReleaseSnapshotError(f"{path}: object keys must be strings")
            _validate_nullable_json(child, f"{path}.{key}")
        return
    raise AtlasReleaseSnapshotError(f"{path}: unsupported JSON value {type(value).__name__}")


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        canonical_json_bytes(plain)
    except (TypeError, ValueError) as error:
        raise AtlasReleaseSnapshotError(str(error)) from error
    return canonical_json_bytes(plain)


def _canonical_jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    try:
        return canonical_jsonl_bytes(rows)
    except (TypeError, ValueError) as error:
        raise AtlasReleaseSnapshotError(str(error)) from error


def _forbid_policy_fields(value: Any, *, label: str) -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(set(value) & _FORBIDDEN_POLICY_FIELDS)
        if forbidden:
            raise AtlasReleaseSnapshotError(f"{label} contains admission or permission fields {forbidden!r}")
        for key, child in value.items():
            _forbid_policy_fields(child, label=f"{label}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _forbid_policy_fields(child, label=f"{label}[{index}]")


def _require_rows(
    value: object,
    *,
    label: str,
    identity_field: str,
    allow_empty: bool,
    require_identifier_order: bool = True,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AtlasReleaseSnapshotError(f"{label} must be an array")
    rows = tuple(_require_mapping(item, f"{label}[{index}]") for index, item in enumerate(value))
    if not rows and not allow_empty:
        raise AtlasReleaseSnapshotError(f"{label} must not be empty")
    identifiers = tuple(
        _require_iri(row.get(identity_field), f"{label}[{index}].{identity_field}") for index, row in enumerate(rows)
    )
    if len(set(identifiers)) != len(identifiers):
        raise AtlasReleaseSnapshotError(f"{label} repeats {identity_field}")
    if require_identifier_order and identifiers != tuple(sorted(identifiers)):
        raise AtlasReleaseSnapshotError(f"{label} is not in canonical identifier order")
    return rows


def _release_pin(value: object) -> dict[str, Any]:
    try:
        return normalize_concept_release_pin(value)
    except ConceptReleaseError as error:
        raise AtlasReleaseSnapshotError(str(error)) from error


def _source_resource_logical_digest(
    manifest: Mapping[str, Any],
    coverage: Mapping[str, Any],
) -> str:
    return sha256_digest(
        _canonical_bytes(
            {
                "resourceManifest": manifest,
                "coverageReport": coverage,
                "observationSetDigest": coverage["observationSetDigest"],
                "sourceArtifacts": manifest["sourceArtifacts"],
            }
        )
    )


def _release_logical_digest(
    release_manifest: Mapping[str, Any],
    source_logical_digest: str,
    reconciliation: Mapping[str, Any] | None,
) -> str:
    basis: dict[str, Any] = {
        "releaseManifest": release_manifest,
        "sourceCaptureLogicalDigest": source_logical_digest,
        "conceptSetDigest": release_manifest["conceptSetDigest"],
        "rightsSetDigest": release_manifest["rightsSetDigest"],
        "lifecycleSetDigest": release_manifest["lifecycleSetDigest"],
    }
    if reconciliation is not None:
        basis["reconciliationDigest"] = sha256_digest(_canonical_bytes(reconciliation))
    return sha256_digest(_canonical_bytes(basis))


def _validate_source_bundle_manifest(
    value: object,
    *,
    release_pin: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    manifest = _require_mapping(
        value,
        "atlas release snapshot releaseBundleManifest",
    )
    _require_exact_fields(
        manifest,
        _SOURCE_BUNDLE_MANIFEST_FIELDS,
        "atlas release snapshot releaseBundleManifest",
    )
    if (
        manifest.get("schemaVersion") != SOURCE_CONCEPT_RELEASE_VERSION
        or manifest.get("packageKind") != "sourceConceptRelease"
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot source bundle manifest version is unsupported")
    if sha256_digest(_canonical_bytes(manifest)) != release_pin.get("manifestDigest"):
        raise AtlasReleaseSnapshotError("atlas release snapshot source release manifestDigest is stale")
    if (
        manifest.get("releaseId") != release_pin.get("releaseId")
        or manifest.get("releaseDigest") != release_pin.get("releaseDigest")
        or manifest.get("logicalDigest") != release_pin.get("logicalDigest")
    ):
        raise AtlasReleaseSnapshotError(
            "atlas release snapshot source bundle manifest differs from the exact release pin"
        )

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, Sequence) or isinstance(
        raw_artifacts,
        (str, bytes),
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot releaseBundleManifest.artifacts must be an array")
    artifacts: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(raw_artifacts):
        label = f"atlas release snapshot releaseBundleManifest.artifacts[{index}]"
        descriptor = _require_mapping(raw, label)
        _require_exact_fields(
            descriptor,
            {"path", "role", "sha256", "byteLength"},
            label,
        )
        path = _require_text(descriptor.get("path"), f"{label}.path")
        if path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/")):
            raise AtlasReleaseSnapshotError(f"{label}.path must be a safe relative path")
        _require_text(descriptor.get("role"), f"{label}.role")
        _require_digest(descriptor.get("sha256"), f"{label}.sha256")
        byte_length = descriptor.get("byteLength")
        if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length < 0:
            raise AtlasReleaseSnapshotError(f"{label}.byteLength must be a nonnegative integer")
        if path in artifacts:
            raise AtlasReleaseSnapshotError("atlas release snapshot releaseBundleManifest repeats an artifact path")
        artifacts[path] = descriptor
    if tuple(artifacts) != tuple(sorted(artifacts)):
        raise AtlasReleaseSnapshotError(
            "atlas release snapshot releaseBundleManifest artifacts are not in canonical path order"
        )
    return manifest, artifacts


def _require_embedded_artifact(
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    path: str,
    role: str,
    payload: bytes,
) -> None:
    descriptor = artifacts.get(path)
    if (
        descriptor is None
        or descriptor.get("role") != role
        or descriptor.get("sha256") != sha256_digest(payload)
        or descriptor.get("byteLength") != len(payload)
    ):
        raise AtlasReleaseSnapshotError(f"atlas release snapshot embedded {path} differs from its bundle descriptor")


def _validate_source_concept(
    row: dict[str, Any],
    *,
    index: int,
    semantic_ring: SemanticRing,
    source_scheme: str,
    observations: Mapping[str, Mapping[str, Any]],
) -> None:
    label = f"atlas release snapshot concepts[{index}]"
    identity_kind = row.get("identityKind")
    optional = (
        {"localRecordId"}
        if identity_kind == "refspecSourceScoped"
        else {"publisherIdentifier"}
        if identity_kind == "publisherConceptIri"
        else set()
    )
    if not optional:
        raise AtlasReleaseSnapshotError(f"{label}.identityKind is unsupported")
    _require_exact_fields(row, _SOURCE_CONCEPT_FIELDS | optional, label)
    if row.get("type") != "SourceScopedConcept":
        raise AtlasReleaseSnapshotError(f"{label}.type must be SourceScopedConcept")
    if row.get("semanticRing") != semantic_ring:
        raise AtlasReleaseSnapshotError(f"{label}.semanticRing differs from release pin")
    if row.get("sourceScheme") != source_scheme:
        raise AtlasReleaseSnapshotError(f"{label}.sourceScheme differs from release manifest")
    observation_id = _require_iri(
        row.get("sourceObservation"),
        f"{label}.sourceObservation",
    )
    observation = observations.get(observation_id)
    if observation is None:
        raise AtlasReleaseSnapshotError(f"{label}.sourceObservation is outside the exact source capture")
    if row.get("sourceObservationDigest") != sha256_digest(_canonical_bytes(observation)):
        raise AtlasReleaseSnapshotError(f"{label}.sourceObservationDigest is stale")
    concept_id = _require_iri(row.get("id"), f"{label}.id")
    if identity_kind == "refspecSourceScoped":
        local_record_id = _require_iri(
            row.get("localRecordId"),
            f"{label}.localRecordId",
        )
        try:
            expected_id = source_scoped_concept_iri(source_scheme, local_record_id)
        except SourceConceptReleaseError as error:
            raise AtlasReleaseSnapshotError(str(error)) from error
        if concept_id != expected_id or row.get("issuer") != SOURCE_CONCEPT_ISSUER_IRI:
            raise AtlasReleaseSnapshotError(f"{label} source-scoped identity is stale")
    else:
        publisher = _require_mapping(
            row.get("publisherIdentifier"),
            f"{label}.publisherIdentifier",
        )
        if (
            publisher.get("kind") != "publisherConceptIri"
            or publisher.get("value") != concept_id
            or publisher.get("authorityUri") != source_scheme
            or row.get("issuer") != source_scheme
        ):
            raise AtlasReleaseSnapshotError(f"{label} publisher identity is stale")


def _validate_source_basis(
    row: Mapping[str, Any],
    release_pin: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fields = set(_SOURCE_BASIS_FIELDS) | _IDENTITY_FIELDS
    if "reconciliationRecord" in row:
        expected_fields.add("reconciliationRecord")
    _require_exact_fields(row, expected_fields, "atlas release snapshot")

    _, bundle_artifacts = _validate_source_bundle_manifest(
        row.get("releaseBundleManifest"),
        release_pin=release_pin,
    )
    release_manifest = _require_mapping(
        row.get("releaseManifest"),
        "atlas release snapshot releaseManifest",
    )
    _require_exact_fields(
        release_manifest,
        _SOURCE_MANIFEST_FIELDS,
        "atlas release snapshot releaseManifest",
    )
    semantic_ring = _require_ring(
        release_pin.get("semanticRing"),
        "atlas release snapshot releasePin.semanticRing",
    )
    if (
        release_manifest.get("type") != "SourceConceptRelease"
        or release_manifest.get("membershipMode") != "completeMembership"
    ):
        raise AtlasReleaseSnapshotError(
            "atlas release snapshot source manifest must be one complete SourceConceptRelease"
        )
    if release_manifest.get("semanticRing") != semantic_ring:
        raise AtlasReleaseSnapshotError("atlas release snapshot release manifest semanticRing differs from release pin")

    concepts = _require_rows(
        row.get("concepts"),
        label="atlas release snapshot concepts",
        identity_field="id",
        allow_empty=False,
    )
    rights = _require_rows(
        row.get("rightsMetadata"),
        label="atlas release snapshot rightsMetadata",
        identity_field="sourceArtifact",
        allow_empty=False,
    )
    lifecycle = _require_rows(
        row.get("lifecycleRecords"),
        label="atlas release snapshot lifecycleRecords",
        identity_field="id",
        allow_empty=True,
    )
    observations = _require_rows(
        row.get("sourceObservations"),
        label="atlas release snapshot sourceObservations",
        identity_field="id",
        allow_empty=False,
        require_identifier_order=True,
    )

    source_manifest = _require_mapping(
        row.get("sourceResourceManifest"),
        "atlas release snapshot sourceResourceManifest",
    )
    if not _SOURCE_RESOURCE_REQUIRED_FIELDS.issubset(source_manifest) or (
        set(source_manifest) - _SOURCE_RESOURCE_REQUIRED_FIELDS - _SOURCE_RESOURCE_OPTIONAL_FIELDS
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot sourceResourceManifest fields differ")
    source_coverage = _require_mapping(
        row.get("sourceCoverageReport"),
        "atlas release snapshot sourceCoverageReport",
    )
    if not _SOURCE_COVERAGE_BASE_FIELDS.issubset(source_coverage) or (
        set(source_coverage) - _SOURCE_COVERAGE_BASE_FIELDS - _SOURCE_COVERAGE_OPTIONAL_FIELDS
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot sourceCoverageReport fields differ")
    local_digest_fields = set(source_coverage) & _SOURCE_COVERAGE_OPTIONAL_FIELDS
    if local_digest_fields not in (set(), _SOURCE_COVERAGE_OPTIONAL_FIELDS):
        raise AtlasReleaseSnapshotError("atlas release snapshot sourceCoverageReport local-record pins are incomplete")
    for field in local_digest_fields:
        _require_digest(
            source_coverage.get(field),
            f"atlas release snapshot sourceCoverageReport.{field}",
        )

    source_manifest_id = _require_iri(
        source_manifest.get("id"),
        "atlas release snapshot sourceResourceManifest.id",
    )
    manifest_without_id = {key: value for key, value in source_manifest.items() if key != "id"}
    resource_id = _require_text(
        source_manifest.get("resourceId"),
        "atlas release snapshot sourceResourceManifest.resourceId",
    )
    expected_manifest_id = f"urn:ref:source-controlled-resource:v2:{resource_id}:" + sha256_digest(
        _canonical_bytes(manifest_without_id)
    ).removeprefix("sha256:")
    if source_manifest_id != expected_manifest_id:
        raise AtlasReleaseSnapshotError("atlas release snapshot sourceResourceManifest.id is stale")
    full_observation_digest = _require_digest(
        source_manifest.get("observationSetDigest"),
        "atlas release snapshot sourceResourceManifest.observationSetDigest",
    )
    observation_count = source_manifest.get("observationCount")
    packaged_count = source_coverage.get("packagedCount")
    if (
        not isinstance(observation_count, int)
        or isinstance(observation_count, bool)
        or observation_count < len(observations)
        or packaged_count != observation_count
        or source_coverage.get("resourceManifest") != source_manifest_id
        or source_coverage.get("observationSetDigest") != full_observation_digest
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot full source-capture metadata is inconsistent")

    source_artifacts_value = source_manifest.get("sourceArtifacts")
    if not isinstance(source_artifacts_value, Sequence) or isinstance(
        source_artifacts_value,
        (str, bytes),
    ):
        raise AtlasReleaseSnapshotError(
            "atlas release snapshot sourceResourceManifest.sourceArtifacts must be an array"
        )
    source_artifacts: dict[str, Mapping[str, Any]] = {}
    for index, value in enumerate(source_artifacts_value):
        label = f"atlas release snapshot sourceArtifacts[{index}]"
        descriptor = _require_mapping(value, label)
        _require_exact_fields(
            descriptor,
            {"id", "path", "sha256", "byteLength"},
            label,
        )
        source_id = _require_iri(descriptor.get("id"), f"{label}.id")
        path = _require_text(descriptor.get("path"), f"{label}.path")
        digest = _require_digest(descriptor.get("sha256"), f"{label}.sha256")
        byte_length = descriptor.get("byteLength")
        if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length <= 0:
            raise AtlasReleaseSnapshotError(f"{label}.byteLength must be a positive integer")
        if source_id in source_artifacts:
            raise AtlasReleaseSnapshotError("atlas release snapshot sourceArtifacts repeats an id")
        source_artifacts[source_id] = descriptor
        outer_descriptor = bundle_artifacts.get(f"source/{path}")
        if (
            outer_descriptor is None
            or outer_descriptor.get("role") != "sourceCaptureArtifact"
            or outer_descriptor.get("sha256") != digest
            or outer_descriptor.get("byteLength") != byte_length
        ):
            raise AtlasReleaseSnapshotError(f"{label} differs from its exact source-capture bundle pin")
    if tuple(source_artifacts) != tuple(sorted(source_artifacts)):
        raise AtlasReleaseSnapshotError("atlas release snapshot sourceArtifacts is not in canonical identifier order")

    _require_embedded_artifact(
        bundle_artifacts,
        path="source/resource-manifest.json",
        role="sourceCaptureArtifact",
        payload=_canonical_bytes(source_manifest),
    )
    _require_embedded_artifact(
        bundle_artifacts,
        path="source/coverage-report.json",
        role="sourceCaptureArtifact",
        payload=_canonical_bytes(source_coverage),
    )
    observations_descriptor = bundle_artifacts.get("source/observations.jsonl")
    if (
        observations_descriptor is None
        or observations_descriptor.get("role") != "sourceCaptureArtifact"
        or observations_descriptor.get("sha256") != full_observation_digest
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot full observation-set pin is stale")

    observation_by_id = {cast(str, value["id"]): value for value in observations}
    source_scheme_value = release_manifest.get("sourceScheme")
    source_scheme = _require_mapping(
        source_scheme_value,
        "atlas release snapshot releaseManifest.sourceScheme",
    )
    source_scheme_id = _require_iri(
        source_scheme.get("id"),
        "atlas release snapshot releaseManifest.sourceScheme.id",
    )
    if source_manifest.get("sourceScheme") != source_scheme:
        raise AtlasReleaseSnapshotError("atlas release snapshot source schemes differ")
    selected_observations: list[str] = []
    for index, concept in enumerate(concepts):
        _validate_source_concept(
            concept,
            index=index,
            semantic_ring=semantic_ring,
            source_scheme=source_scheme_id,
            observations=observation_by_id,
        )
        selected_observations.append(cast(str, concept["sourceObservation"]))
    if len(set(selected_observations)) != len(selected_observations) or set(selected_observations) != set(
        observation_by_id
    ):
        raise AtlasReleaseSnapshotError(
            "atlas release snapshot observations must exactly equal those cited by selected concepts"
        )

    normalized_rights: list[dict[str, Any]] = []
    selected_source_artifacts = {
        _require_iri(
            observation.get("sourceArtifact"),
            f"atlas release snapshot sourceObservations[{index}].sourceArtifact",
        )
        for index, observation in enumerate(observations)
    }
    for index, rights_row in enumerate(rights):
        try:
            normalized = RightsMetadata.from_record(rights_row).as_record()
        except SemanticFoundationError as error:
            raise AtlasReleaseSnapshotError(str(error)) from error
        descriptor = source_artifacts.get(cast(str, normalized["sourceArtifact"]))
        if (
            normalized["sourceArtifact"] not in selected_source_artifacts
            or descriptor is None
            or descriptor.get("sha256") != normalized["sourceDigest"]
        ):
            raise AtlasReleaseSnapshotError(
                f"atlas release snapshot rightsMetadata[{index}] is outside the selected observation closure"
            )
        normalized_rights.append(normalized)
    if tuple(normalized_rights) != rights:
        raise AtlasReleaseSnapshotError("atlas release snapshot rightsMetadata does not reproduce canonically")

    for index, lifecycle_row in enumerate(lifecycle):
        _require_exact_fields(
            lifecycle_row,
            _LIFECYCLE_FIELDS,
            f"atlas release snapshot lifecycleRecords[{index}]",
        )
        if lifecycle_row.get("semanticRing") != semantic_ring:
            raise AtlasReleaseSnapshotError(
                f"atlas release snapshot lifecycleRecords[{index}].semanticRing differs from release pin"
            )

    set_checks = (
        ("conceptCount", len(concepts)),
        ("conceptSetDigest", sha256_digest(_canonical_jsonl(concepts))),
        ("rightsRecordCount", len(rights)),
        ("rightsSetDigest", sha256_digest(_canonical_jsonl(rights))),
        ("lifecycleRecordCount", len(lifecycle)),
        ("lifecycleSetDigest", sha256_digest(_canonical_jsonl(lifecycle))),
        (
            "selectedObservationSetDigest",
            sha256_digest(_canonical_bytes(sorted(selected_observations))),
        ),
    )
    for field, expected in set_checks:
        if release_manifest.get(field) != expected:
            raise AtlasReleaseSnapshotError(f"atlas release snapshot releaseManifest.{field} is stale")

    _require_embedded_artifact(
        bundle_artifacts,
        path="release-manifest.json",
        role="releaseManifest",
        payload=_canonical_bytes(release_manifest),
    )
    _require_embedded_artifact(
        bundle_artifacts,
        path="concepts.jsonl",
        role="concepts",
        payload=_canonical_jsonl(concepts),
    )
    _require_embedded_artifact(
        bundle_artifacts,
        path="rights.jsonl",
        role="rights",
        payload=_canonical_jsonl(rights),
    )
    _require_embedded_artifact(
        bundle_artifacts,
        path="lifecycle.jsonl",
        role="lifecycle",
        payload=_canonical_jsonl(lifecycle),
    )

    release_basis = {key: value for key, value in release_manifest.items() if key not in {"id", "releaseDigest"}}
    release_digest = sha256_digest(_canonical_bytes(release_basis))
    expected_release_id = f"urn:ref:source-concept-release:{semantic_ring}:" + release_digest.removeprefix("sha256:")
    if (
        release_manifest.get("releaseDigest") != release_digest
        or release_manifest.get("id") != expected_release_id
        or release_pin.get("releaseId") != expected_release_id
        or release_pin.get("releaseDigest") != release_digest
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot source release identity is stale")

    reconciliation_value = row.get("reconciliationRecord")
    reconciliation = (
        None
        if "reconciliationRecord" not in row
        else _require_mapping(
            reconciliation_value,
            "atlas release snapshot reconciliationRecord",
        )
    )
    source_capture = _require_mapping(
        release_manifest.get("sourceCapture"),
        "atlas release snapshot releaseManifest.sourceCapture",
    )
    expected_capture_fields = {
        "resourceManifest",
        "logicalDigest",
        "observationSetDigest",
    }
    if reconciliation is not None:
        expected_capture_fields.add("reconciliationDigest")
    _require_exact_fields(
        source_capture,
        expected_capture_fields,
        "atlas release snapshot releaseManifest.sourceCapture",
    )
    if (
        _require_iri(
            source_capture.get("resourceManifest"),
            "atlas release snapshot releaseManifest.sourceCapture.resourceManifest",
        )
        != source_manifest_id
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot source capture names another resource manifest")
    declared_source_logical_digest = _require_digest(
        source_capture.get("logicalDigest"),
        "atlas release snapshot releaseManifest.sourceCapture.logicalDigest",
    )
    source_logical_digest = _source_resource_logical_digest(
        source_manifest,
        source_coverage,
    )
    if declared_source_logical_digest != source_logical_digest:
        raise AtlasReleaseSnapshotError("atlas release snapshot source capture logicalDigest is stale")
    if (
        _require_digest(
            source_capture.get("observationSetDigest"),
            "atlas release snapshot releaseManifest.sourceCapture.observationSetDigest",
        )
        != full_observation_digest
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot source capture observationSetDigest is stale")
    if reconciliation is not None:
        _validate_nullable_json(reconciliation, "$.reconciliationRecord")
        if (
            reconciliation.get("currentManifestId") != source_manifest_id
            or reconciliation.get("requiresHumanReview") is not False
        ):
            raise AtlasReleaseSnapshotError(
                "atlas release snapshot reconciliationRecord is unresolved or names another capture"
            )
        reconciliation_digest = sha256_digest(_canonical_bytes(reconciliation))
        if source_capture.get("reconciliationDigest") != reconciliation_digest:
            raise AtlasReleaseSnapshotError("atlas release snapshot reconciliation digest is stale")
        _require_embedded_artifact(
            bundle_artifacts,
            path="reconciliation.json",
            role="reconciliation",
            payload=_canonical_bytes(reconciliation),
        )
    elif "reconciliation.json" in bundle_artifacts:
        raise AtlasReleaseSnapshotError("atlas release snapshot bundle describes an omitted reconciliation record")

    release_logical_digest = _release_logical_digest(
        release_manifest,
        source_logical_digest,
        reconciliation,
    )
    if release_pin.get("logicalDigest") != release_logical_digest:
        raise AtlasReleaseSnapshotError("atlas release snapshot source release logicalDigest is stale")
    return {key: _plain(value) for key, value in row.items() if key not in _IDENTITY_FIELDS}


def _record_types(record: Mapping[str, Any]) -> frozenset[str]:
    value = record.get("@type")
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return frozenset(item for item in value if isinstance(item, str))
    return frozenset()


def _iri_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        identifier = value.get("@id")
        return (identifier,) if isinstance(identifier, str) else ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(identifier for item in value for identifier in _iri_values(item))
    return ()


def _record_references(record: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(
        identifier for key, value in record.items() if key not in {"@id", "@type"} for identifier in _iri_values(value)
    )


def _managed_graph_nodes(
    value: object,
    *,
    label: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    graph = _require_mapping(value, label)
    _require_exact_fields(graph, {"@context", "@graph"}, label)
    raw_nodes = graph.get("@graph")
    if not isinstance(raw_nodes, Sequence) or isinstance(raw_nodes, (str, bytes)):
        raise AtlasReleaseSnapshotError(f"{label}.@graph must be an array")
    nodes: dict[str, dict[str, Any]] = {}
    for index, raw_node in enumerate(raw_nodes):
        node = _require_mapping(raw_node, f"{label}.@graph[{index}]")
        identifier = _require_iri(
            node.get("@id"),
            f"{label}.@graph[{index}].@id",
        )
        if identifier in nodes:
            raise AtlasReleaseSnapshotError(f"{label} repeats an identifier")
        nodes[identifier] = node
    return graph, nodes


def _selected_managed_graph(
    value: object,
    *,
    release_id: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Copy one release's semantic closure, leaving the wider graph behind."""

    graph, nodes = _managed_graph_nodes(
        value,
        label="atlas release snapshot selectedReleaseGraph",
    )
    release_node = nodes.get(release_id)
    if (
        release_node is None
        or not (_record_types(release_node) & _RELEASE_TYPES)
        or release_node.get("rkaf:membershipMode") not in _COMPLETE_MEMBERSHIP
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot selected graph lacks the selected complete release")
    member_ids = _iri_values(release_node.get("prov:hadMember"))
    if not member_ids or len(set(member_ids)) != len(member_ids):
        raise AtlasReleaseSnapshotError("atlas release snapshot selected release membership is empty or repeated")
    missing_members = sorted(set(member_ids) - set(nodes))
    if missing_members:
        raise AtlasReleaseSnapshotError(
            f"atlas release snapshot selected graph lacks release members {missing_members!r}"
        )

    selected = {release_id, *member_ids}
    release_local_predicates = {
        "dcat:distribution",
        "https://www.w3.org/ns/dcat#distribution",
    }
    member_local_predicates = {
        "skos:inScheme",
        "http://www.w3.org/2004/02/skos/core#inScheme",
    }
    for identifier, predicates in (
        (release_id, release_local_predicates),
        *((member_id, member_local_predicates) for member_id in member_ids),
    ):
        record = nodes[identifier]
        for predicate in predicates:
            referenced = _iri_values(record.get(predicate))
            missing = sorted(set(referenced) - set(nodes))
            if missing:
                raise AtlasReleaseSnapshotError(
                    f"atlas release snapshot selected graph lacks {predicate} records {missing!r}"
                )

    adjacency: dict[str, list[str]] = {identifier: [] for identifier in nodes}
    for identifier, record in nodes.items():
        for predicate in _DIRECT_CLOSURE_PREDICATES:
            adjacency[identifier].extend(
                reference for reference in _iri_values(record.get(predicate)) if reference in nodes
            )
        if _record_types(record) & (_LIFECYCLE_TYPES | _RIGHTS_TYPES):
            for reference in _record_references(record):
                if reference in nodes:
                    adjacency[reference].append(identifier)

    pending = deque(selected)
    while pending:
        identifier = pending.popleft()
        for adjacent in adjacency[identifier]:
            if adjacent in selected:
                continue
            selected.add(adjacent)
            pending.append(adjacent)

    selected_nodes = sorted(
        (_plain(nodes[identifier]) for identifier in selected),
        key=lambda record: cast(str, record["@id"]),
    )
    return {
        "@context": _plain(graph["@context"]),
        "@graph": selected_nodes,
    }, member_ids


def _validate_managed_basis(
    row: Mapping[str, Any],
    release_pin: Mapping[str, Any],
) -> dict[str, Any]:
    schema_version = row.get("schemaVersion")
    _require_exact_fields(
        row,
        (
            _MANAGED_BASIS_FIELDS_V1
            if schema_version == "1.0"
            else _MANAGED_BASIS_FIELDS
        )
        | _IDENTITY_FIELDS,
        "atlas release snapshot",
    )
    assignment_row = _require_mapping(
        row.get("ringAssignment"),
        "atlas release snapshot ringAssignment",
    )
    try:
        assignment = ManagedReleaseRingAssignment.from_record(assignment_row)
    except ConceptReleaseError as error:
        raise AtlasReleaseSnapshotError(str(error)) from error
    assignment_pin = cast(Mapping[str, Any], release_pin["ringAssignment"])
    semantic_ring = _require_ring(
        release_pin.get("semanticRing"),
        "atlas release snapshot releasePin.semanticRing",
    )
    if (
        assignment.identifier != assignment_pin.get("id")
        or assignment.content_digest != assignment_pin.get("contentDigest")
        or sha256_digest(_canonical_bytes(assignment.as_record())) != assignment_pin.get("fileDigest")
        or assignment.managed_manifest_digest != release_pin.get("manifestDigest")
        or assignment.release_id != release_pin.get("releaseId")
        or assignment.semantic_ring != semantic_ring
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot ring assignment differs from the exact release pin")

    release_id = _require_iri(
        release_pin.get("releaseId"),
        "atlas release snapshot releasePin.releaseId",
    )
    graph, expected_member_ids = _selected_managed_graph(
        row.get("selectedReleaseGraph"),
        release_id=release_id,
    )
    supplied_graph = _require_mapping(
        row.get("selectedReleaseGraph"),
        "atlas release snapshot selectedReleaseGraph",
    )
    if graph != supplied_graph:
        raise AtlasReleaseSnapshotError(
            "atlas release snapshot selectedReleaseGraph contains records outside the selected release closure or is not canonical"
        )
    _, nodes = _managed_graph_nodes(
        graph,
        label="atlas release snapshot selectedReleaseGraph",
    )
    release_node = nodes.get(release_id)
    assert release_node is not None
    if release_node.get("rkaf:referenceReleaseDigest") != release_pin.get("declaredReleaseDigest"):
        raise AtlasReleaseSnapshotError(
            "atlas release snapshot declared release digest differs from the selected release record"
        )

    members: tuple[dict[str, Any], ...] = ()
    if schema_version == "1.0":
        members = _require_rows(
            row.get("members"),
            label="atlas release snapshot members",
            identity_field="@id",
            allow_empty=False,
        )
        actual_member_ids = tuple(cast(str, value["@id"]) for value in members)
    else:
        member_values = row.get("memberIds")
        if (
            not isinstance(member_values, Sequence)
            or isinstance(member_values, (str, bytes))
            or not member_values
        ):
            raise AtlasReleaseSnapshotError(
                "atlas release snapshot memberIds must be a non-empty IRI array"
            )
        actual_member_ids = tuple(
            _require_iri(
                value,
                f"atlas release snapshot memberIds[{index}]",
            )
            for index, value in enumerate(member_values)
        )
        if actual_member_ids != tuple(sorted(set(actual_member_ids))):
            raise AtlasReleaseSnapshotError(
                "atlas release snapshot memberIds must use canonical identifier order"
            )
    if set(actual_member_ids) != set(expected_member_ids):
        raise AtlasReleaseSnapshotError(
            "atlas release snapshot member references do not exactly equal complete release membership"
        )
    for index, member_id in enumerate(actual_member_ids):
        member = nodes[member_id]
        if schema_version == "1.0" and nodes.get(member_id) != members[index]:
            raise AtlasReleaseSnapshotError(
                f"atlas release snapshot members[{index}] differs from the selected release graph"
            )
        schemes = _iri_values(member.get("skos:inScheme"))
        if len(schemes) != 1:
            raise AtlasReleaseSnapshotError(
                f"atlas release snapshot members[{index}] must name exactly one concept scheme"
            )
    return {key: _plain(value) for key, value in row.items() if key not in _IDENTITY_FIELDS}


def _normalize_record(value: Mapping[str, Any]) -> dict[str, Any]:
    row = _require_mapping(value, "atlas release snapshot")
    if (
        row.get("type") != ATLAS_RELEASE_SNAPSHOT_TYPE
        or row.get("schemaVersion") not in _SUPPORTED_SNAPSHOT_VERSIONS
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot version is unsupported")
    release_pin = _release_pin(row.get("releasePin"))
    if release_pin.get("releaseKind") == "sourceConceptRelease":
        basis = _validate_source_basis(row, release_pin)
    else:
        basis = _validate_managed_basis(row, release_pin)
    _forbid_policy_fields(basis, label="atlas release snapshot")
    basis_without_reconciliation = {key: item for key, item in basis.items() if key != "reconciliationRecord"}
    try:
        binding.validate_canonical_value(basis_without_reconciliation)
    except (TypeError, ValueError) as error:
        raise AtlasReleaseSnapshotError(str(error)) from error
    if "reconciliationRecord" in basis:
        _validate_nullable_json(
            basis["reconciliationRecord"],
            "$.reconciliationRecord",
        )
    content_digest = sha256_digest(_canonical_bytes(basis))
    expected = {
        **basis,
        "id": ("urn:ref:atlas-release-snapshot:" + content_digest.removeprefix("sha256:")),
        "contentDigest": content_digest,
    }
    if row != expected:
        raise AtlasReleaseSnapshotError("atlas release snapshot content identity or canonical order differs")
    return expected


def _seal_basis(basis: Mapping[str, Any]) -> dict[str, Any]:
    content_digest = sha256_digest(_canonical_bytes(basis))
    return {
        **_plain(basis),
        "id": ("urn:ref:atlas-release-snapshot:" + content_digest.removeprefix("sha256:")),
        "contentDigest": content_digest,
    }


@dataclass(frozen=True, slots=True)
class AtlasReleaseSnapshot:
    """One immutable, content-derived, non-authorizing release snapshot."""

    record: Mapping[str, Any]

    def __post_init__(self) -> None:
        normalized = _normalize_record(self.record)
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(normalized)),
        )

    @classmethod
    def create(cls, scope_release: AtlasScopeRelease) -> Self:
        """Copy one exact path-backed release into a logical snapshot."""

        if not isinstance(scope_release, AtlasScopeRelease):
            raise AtlasReleaseSnapshotError("atlas release snapshot requires one AtlasScopeRelease")
        source = scope_release.source
        try:
            if isinstance(source, PinnedSourceConceptRelease):
                facts = verified_concept_release_facts(source)
                release_pin = _plain(facts.pin)
                if not isinstance(facts.view, SourceConceptReleaseView):
                    raise AtlasReleaseSnapshotError(
                        "source concept release verification returned the wrong view kind"
                    )
                view = facts.view
                bundle_manifest = json.loads(view.bundle.artifact_bytes()["bundle-manifest.json"].decode("utf-8"))
                observations_by_id = {
                    cast(str, observation["id"]): observation for observation in view.source_bundle.observations
                }
                selected_observation_ids = {cast(str, concept["sourceObservation"]) for concept in view.concepts}
                basis: dict[str, Any] = {
                    "type": ATLAS_RELEASE_SNAPSHOT_TYPE,
                    "schemaVersion": ATLAS_RELEASE_SNAPSHOT_VERSION,
                    "releasePin": release_pin,
                    "releaseBundleManifest": bundle_manifest,
                    "releaseManifest": _plain(view.release_manifest),
                    "concepts": sorted(
                        (_plain(value) for value in view.concepts),
                        key=lambda value: cast(str, value["id"]),
                    ),
                    "rightsMetadata": sorted(
                        (_plain(value) for value in view.rights_metadata),
                        key=lambda value: cast(str, value["sourceArtifact"]),
                    ),
                    "lifecycleRecords": sorted(
                        (_plain(value) for value in view.lifecycle_records),
                        key=lambda value: cast(str, value["id"]),
                    ),
                    "sourceResourceManifest": _plain(view.source_bundle.resource_manifest),
                    "sourceCoverageReport": _plain(view.source_bundle.coverage_report),
                    "sourceObservations": sorted(
                        (_plain(observations_by_id[identifier]) for identifier in selected_observation_ids),
                        key=lambda value: cast(str, value["id"]),
                    ),
                }
                if view.reconciliation_record is not None:
                    basis["reconciliationRecord"] = _plain(view.reconciliation_record)
            elif isinstance(source, PinnedManagedConceptRelease):
                view, release_pin = source.verified_view_and_pin()
                assignment = source.ring_assignment.verified_assignment()
                selected_graph, _ = _selected_managed_graph(
                    view.rulespec_graph,
                    release_id=source.release_id,
                )
                basis = {
                    "type": ATLAS_RELEASE_SNAPSHOT_TYPE,
                    "schemaVersion": ATLAS_RELEASE_SNAPSHOT_VERSION,
                    "releasePin": release_pin,
                    "ringAssignment": assignment.as_record(),
                    "selectedReleaseGraph": selected_graph,
                    "memberIds": sorted(
                        member.member_iri
                        for member in view.iter_members(
                            release_iri=source.release_id
                        )
                    ),
                }
            else:  # AtlasScopeRelease closes this union; retain a hard boundary.
                raise AtlasReleaseSnapshotError("atlas release snapshot source kind is unsupported")
        except ConceptReleaseError as error:
            raise AtlasReleaseSnapshotError(str(error)) from error
        return cls(record=_seal_basis(basis))

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> Self:
        """Verify a logical snapshot using only the supplied record."""

        return cls(record=value)

    def as_record(self) -> dict[str, Any]:
        """Return a mutable JSON-plain copy of the verified snapshot."""

        return cast(dict[str, Any], _plain(self.record))

    def verify_against(self, scope_release: AtlasScopeRelease) -> None:
        """Reopen one exact scope release and require the same snapshot facts."""

        current = type(self).create(scope_release)
        if current.as_record() != self.as_record():
            raise AtlasReleaseSnapshotError("atlas release snapshot differs from the exact scope release")

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def content_digest(self) -> str:
        return cast(str, self.record["contentDigest"])

    @property
    def release_pin(self) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], self.record["releasePin"])

    @property
    def release_id(self) -> str:
        return cast(str, self.release_pin["releaseId"])

    @property
    def semantic_ring(self) -> SemanticRing:
        return cast(SemanticRing, self.release_pin["semanticRing"])

    @property
    def member_ids(self) -> frozenset[str]:
        if self.release_pin["releaseKind"] != "sourceConceptRelease":
            member_ids = self.record.get("memberIds")
            if isinstance(member_ids, Sequence) and not isinstance(
                member_ids,
                (str, bytes),
            ):
                return frozenset(cast(Sequence[str], member_ids))
        field = (
            "concepts"
            if self.release_pin["releaseKind"] == "sourceConceptRelease"
            else "members"
        )
        return frozenset(
            cast(str, record["id" if field == "concepts" else "@id"])
            for record in cast(Sequence[Mapping[str, Any]], self.record[field])
        )

    @property
    def concept_records(self) -> tuple[Mapping[str, Any], ...]:
        if self.release_pin["releaseKind"] == "sourceConceptRelease":
            return cast(
                tuple[Mapping[str, Any], ...],
                self.record["concepts"],
            )
        if "members" in self.record:  # Snapshot 1.0 compatibility.
            return cast(
                tuple[Mapping[str, Any], ...],
                self.record["members"],
            )
        graph = cast(Mapping[str, Any], self.record["selectedReleaseGraph"])
        member_ids = self.member_ids
        return tuple(
            record
            for record in cast(Sequence[Mapping[str, Any]], graph["@graph"])
            if record.get("@id") in member_ids
        )


__all__ = [
    "ATLAS_RELEASE_SNAPSHOT_TYPE",
    "ATLAS_RELEASE_SNAPSHOT_VERSION",
    "AtlasReleaseSnapshot",
    "AtlasReleaseSnapshotError",
]
