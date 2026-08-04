"""Canonical logical snapshots for exact four-ring atlas releases.

An :class:`AtlasReleaseSnapshot` copies the complete logical facts needed by
the canonical atlas from one path-backed :class:`AtlasScopeRelease`.  The
snapshot is content-derived and deliberately carries no admission, emission,
or use permission.  ``from_record`` verifies a snapshot from its own JSON
facts; ``verify_against`` additionally reopens the exact release files named
by an atlas scope.
"""

from __future__ import annotations

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
    source_scoped_concept_iri,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION,
    SourceControlledResourceError,
    local_record_identity_digests,
)
from refspec.release_graph import rulespec_graph_digest

from .atlas_scope import AtlasScopeRelease
from .concept_release import (
    ConceptReleaseError,
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedSourceConceptRelease,
    normalize_concept_release_pin,
)

ATLAS_RELEASE_SNAPSHOT_TYPE = "AtlasReleaseSnapshot"
ATLAS_RELEASE_SNAPSHOT_VERSION = "1.0"

_COMMON_BASIS_FIELDS = {
    "type",
    "schemaVersion",
    "releasePin",
}
_SOURCE_BASIS_FIELDS = _COMMON_BASIS_FIELDS | {
    "releaseManifest",
    "concepts",
    "rightsMetadata",
    "lifecycleRecords",
    "sourceResourceManifest",
    "sourceCoverageReport",
    "sourceObservations",
}
_MANAGED_BASIS_FIELDS = _COMMON_BASIS_FIELDS | {
    "ringAssignment",
    "rulespecGraph",
    "members",
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


def _payload_descriptor(
    path: str,
    payload: bytes,
    *,
    role: str,
    source_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": path,
        "role": role,
        "sha256": sha256_digest(payload),
        "byteLength": len(payload),
    }
    if source_id is not None:
        result["sourceId"] = source_id
    return result


def _source_release_manifest_digest(
    *,
    release_manifest: Mapping[str, Any],
    concepts: Sequence[Mapping[str, Any]],
    rights: Sequence[Mapping[str, Any]],
    lifecycle: Sequence[Mapping[str, Any]],
    source_manifest: Mapping[str, Any],
    source_coverage: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    source_artifacts: Mapping[str, Mapping[str, Any]],
    reconciliation: Mapping[str, Any] | None,
    logical_digest: str,
) -> str:
    """Rebuild both package manifests from logical facts and byte descriptors."""

    source_payloads = {
        "resource-manifest.json": _canonical_bytes(source_manifest),
        "coverage-report.json": _canonical_bytes(source_coverage),
        "observations.jsonl": _canonical_jsonl(observations),
    }
    nested_descriptors = [
        _payload_descriptor(
            path,
            payload,
            role=(
                "resourceManifest"
                if path == "resource-manifest.json"
                else "coverageReport"
                if path == "coverage-report.json"
                else "observations"
            ),
        )
        for path, payload in sorted(source_payloads.items())
    ]
    for source_id, descriptor in source_artifacts.items():
        path = cast(str, descriptor["path"])
        nested_descriptors.append(
            {
                "path": path,
                "role": "sourceArtifact",
                "sha256": descriptor["sha256"],
                "byteLength": descriptor["byteLength"],
                "sourceId": source_id,
            }
        )
    nested_descriptors.sort(key=lambda value: cast(str, value["path"]))
    source_bundle_manifest = _canonical_bytes(
        {
            "schemaVersion": SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION,
            "packageKind": "sourceControlledResource",
            "resourceManifest": source_manifest["id"],
            "logicalDigest": _source_resource_logical_digest(
                source_manifest,
                source_coverage,
            ),
            "artifacts": nested_descriptors,
        }
    )

    release_payloads: dict[str, bytes] = {
        "release-manifest.json": _canonical_bytes(release_manifest),
        "concepts.jsonl": _canonical_jsonl(concepts),
        "rights.jsonl": _canonical_jsonl(rights),
        "lifecycle.jsonl": _canonical_jsonl(lifecycle),
        "source/bundle-manifest.json": source_bundle_manifest,
        "source/resource-manifest.json": source_payloads["resource-manifest.json"],
        "source/coverage-report.json": source_payloads["coverage-report.json"],
        "source/observations.jsonl": source_payloads["observations.jsonl"],
    }
    if reconciliation is not None:
        release_payloads["reconciliation.json"] = _canonical_bytes(reconciliation)
    outer_descriptors = [
        _payload_descriptor(
            path,
            payload,
            role=(
                "releaseManifest"
                if path == "release-manifest.json"
                else "concepts"
                if path == "concepts.jsonl"
                else "rights"
                if path == "rights.jsonl"
                else "lifecycle"
                if path == "lifecycle.jsonl"
                else "reconciliation"
                if path == "reconciliation.json"
                else "sourceCaptureArtifact"
            ),
        )
        for path, payload in release_payloads.items()
    ]
    for descriptor in source_artifacts.values():
        outer_descriptors.append(
            {
                "path": "source/" + cast(str, descriptor["path"]),
                "role": "sourceCaptureArtifact",
                "sha256": descriptor["sha256"],
                "byteLength": descriptor["byteLength"],
            }
        )
    outer_descriptors.sort(key=lambda value: cast(str, value["path"]))
    bundle_manifest = {
        "schemaVersion": SOURCE_CONCEPT_RELEASE_VERSION,
        "packageKind": "sourceConceptRelease",
        "releaseId": release_manifest["id"],
        "releaseDigest": release_manifest["releaseDigest"],
        "logicalDigest": logical_digest,
        "artifacts": outer_descriptors,
    }
    return sha256_digest(_canonical_bytes(bundle_manifest))


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
        require_identifier_order=False,
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
    try:
        local_digests = local_record_identity_digests(observations)
    except SourceControlledResourceError as error:
        raise AtlasReleaseSnapshotError(str(error)) from error
    _require_exact_fields(
        source_coverage,
        _SOURCE_COVERAGE_BASE_FIELDS | set(local_digests),
        "atlas release snapshot sourceCoverageReport",
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

    observation_digest = sha256_digest(_canonical_jsonl(observations))
    if (
        source_manifest.get("observationCount") != len(observations)
        or source_manifest.get("observationSetDigest") != observation_digest
        or source_coverage.get("resourceManifest") != source_manifest_id
        or source_coverage.get("packagedCount") != len(observations)
        or source_coverage.get("observationSetDigest") != observation_digest
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot source observation coverage is stale")
    for field, expected in local_digests.items():
        if source_coverage.get(field) != expected:
            raise AtlasReleaseSnapshotError(f"atlas release snapshot sourceCoverageReport.{field} is stale")

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
        descriptor = _require_mapping(
            value,
            f"atlas release snapshot sourceArtifacts[{index}]",
        )
        _require_exact_fields(
            descriptor,
            {"id", "path", "sha256", "byteLength"},
            f"atlas release snapshot sourceArtifacts[{index}]",
        )
        source_id = _require_iri(
            descriptor.get("id"),
            f"atlas release snapshot sourceArtifacts[{index}].id",
        )
        if source_id in source_artifacts:
            raise AtlasReleaseSnapshotError("atlas release snapshot sourceArtifacts repeats an id")
        _require_text(
            descriptor.get("path"),
            f"atlas release snapshot sourceArtifacts[{index}].path",
        )
        if not is_sha256_digest(descriptor.get("sha256")):
            raise AtlasReleaseSnapshotError(
                f"atlas release snapshot sourceArtifacts[{index}].sha256 must be a SHA-256 digest"
            )
        byte_length = descriptor.get("byteLength")
        if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length <= 0:
            raise AtlasReleaseSnapshotError(
                f"atlas release snapshot sourceArtifacts[{index}].byteLength must be a positive integer"
            )
        source_artifacts[source_id] = descriptor
    if tuple(source_artifacts) != tuple(sorted(source_artifacts)):
        raise AtlasReleaseSnapshotError("atlas release snapshot sourceArtifacts is not in canonical identifier order")

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
    if len(set(selected_observations)) != len(selected_observations):
        raise AtlasReleaseSnapshotError("atlas release snapshot concepts repeat a source observation")

    normalized_rights: list[dict[str, Any]] = []
    for index, rights_row in enumerate(rights):
        try:
            normalized = RightsMetadata.from_record(rights_row).as_record()
        except SemanticFoundationError as error:
            raise AtlasReleaseSnapshotError(str(error)) from error
        source_id = cast(str, normalized["sourceArtifact"])
        descriptor = source_artifacts.get(source_id)
        if descriptor is None or descriptor.get("sha256") != normalized["sourceDigest"]:
            raise AtlasReleaseSnapshotError(
                f"atlas release snapshot rightsMetadata[{index}] is outside the exact source capture"
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
    source_logical_digest = _source_resource_logical_digest(
        source_manifest,
        source_coverage,
    )
    if (
        source_capture.get("resourceManifest") != source_manifest_id
        or source_capture.get("logicalDigest") != source_logical_digest
        or source_capture.get("observationSetDigest") != observation_digest
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot source capture pin is stale")
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

    release_logical_digest = _release_logical_digest(
        release_manifest,
        source_logical_digest,
        reconciliation,
    )
    if release_pin.get("logicalDigest") != release_logical_digest:
        raise AtlasReleaseSnapshotError("atlas release snapshot source release logicalDigest is stale")
    if release_pin.get("manifestDigest") != _source_release_manifest_digest(
        release_manifest=release_manifest,
        concepts=concepts,
        rights=rights,
        lifecycle=lifecycle,
        source_manifest=source_manifest,
        source_coverage=source_coverage,
        observations=observations,
        source_artifacts=source_artifacts,
        reconciliation=reconciliation,
        logical_digest=release_logical_digest,
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot source release manifestDigest is stale")
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
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _validate_managed_basis(
    row: Mapping[str, Any],
    release_pin: Mapping[str, Any],
) -> dict[str, Any]:
    _require_exact_fields(
        row,
        _MANAGED_BASIS_FIELDS | _IDENTITY_FIELDS,
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

    graph = _require_mapping(
        row.get("rulespecGraph"),
        "atlas release snapshot rulespecGraph",
    )
    if "@id" in graph:
        raise AtlasReleaseSnapshotError("atlas release snapshot rulespecGraph must remain a default graph")
    try:
        graph_digest = rulespec_graph_digest(graph)
    except (TypeError, ValueError) as error:
        raise AtlasReleaseSnapshotError(str(error)) from error
    graph_pin = cast(Mapping[str, Any], release_pin["rulespecGraph"])
    if graph_digest != graph_pin.get("digest"):
        raise AtlasReleaseSnapshotError("atlas release snapshot Rulespec graph digest differs from release pin")
    raw_nodes = graph.get("@graph")
    if not isinstance(raw_nodes, Sequence) or isinstance(raw_nodes, (str, bytes)):
        raise AtlasReleaseSnapshotError("atlas release snapshot rulespecGraph.@graph must be an array")
    nodes: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(raw_nodes):
        node = _require_mapping(
            value,
            f"atlas release snapshot rulespecGraph.@graph[{index}]",
        )
        identifier = _require_iri(
            node.get("@id"),
            f"atlas release snapshot rulespecGraph.@graph[{index}].@id",
        )
        if identifier in nodes:
            raise AtlasReleaseSnapshotError("atlas release snapshot Rulespec graph repeats an identifier")
        nodes[identifier] = node

    release_id = _require_iri(
        release_pin.get("releaseId"),
        "atlas release snapshot releasePin.releaseId",
    )
    release_node = nodes.get(release_id)
    if (
        release_node is None
        or not (_record_types(release_node) & _RELEASE_TYPES)
        or release_node.get("rkaf:membershipMode") not in _COMPLETE_MEMBERSHIP
    ):
        raise AtlasReleaseSnapshotError("atlas release snapshot Rulespec graph lacks the selected complete release")
    expected_member_ids = _iri_values(release_node.get("prov:hadMember"))
    if not expected_member_ids or len(set(expected_member_ids)) != len(expected_member_ids):
        raise AtlasReleaseSnapshotError("atlas release snapshot selected release membership is empty or repeated")
    if release_node.get("rkaf:referenceReleaseDigest") != release_pin.get("declaredReleaseDigest"):
        raise AtlasReleaseSnapshotError(
            "atlas release snapshot declared release digest differs from the Rulespec graph"
        )

    members = _require_rows(
        row.get("members"),
        label="atlas release snapshot members",
        identity_field="@id",
        allow_empty=False,
    )
    actual_member_ids = tuple(cast(str, value["@id"]) for value in members)
    if set(actual_member_ids) != set(expected_member_ids):
        raise AtlasReleaseSnapshotError(
            "atlas release snapshot members do not exactly equal complete release membership"
        )
    for index, member in enumerate(members):
        member_id = actual_member_ids[index]
        if nodes.get(member_id) != member:
            raise AtlasReleaseSnapshotError(
                f"atlas release snapshot members[{index}] differs from the full Rulespec graph"
            )
        schemes = _iri_values(member.get("skos:inScheme"))
        if len(schemes) != 1:
            raise AtlasReleaseSnapshotError(
                f"atlas release snapshot members[{index}] must name exactly one concept scheme"
            )
    return {key: _plain(value) for key, value in row.items() if key not in _IDENTITY_FIELDS}


def _normalize_record(value: Mapping[str, Any]) -> dict[str, Any]:
    row = _require_mapping(value, "atlas release snapshot")
    if row.get("type") != ATLAS_RELEASE_SNAPSHOT_TYPE or row.get("schemaVersion") != ATLAS_RELEASE_SNAPSHOT_VERSION:
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
            release_pin = source.pin()
            if isinstance(source, PinnedSourceConceptRelease):
                view = source.verified_view()
                basis: dict[str, Any] = {
                    "type": ATLAS_RELEASE_SNAPSHOT_TYPE,
                    "schemaVersion": ATLAS_RELEASE_SNAPSHOT_VERSION,
                    "releasePin": release_pin,
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
                    # The source package's JSONL order is part of its exact
                    # observationSetDigest. It is already canonical for that
                    # capture and must not be rewritten by the atlas.
                    "sourceObservations": [_plain(value) for value in view.source_bundle.observations],
                }
                if view.reconciliation_record is not None:
                    basis["reconciliationRecord"] = _plain(view.reconciliation_record)
            elif isinstance(source, PinnedManagedConceptRelease):
                view = source.verified_view()
                assignment = source.ring_assignment.verified_assignment()
                basis = {
                    "type": ATLAS_RELEASE_SNAPSHOT_TYPE,
                    "schemaVersion": ATLAS_RELEASE_SNAPSHOT_VERSION,
                    "releasePin": release_pin,
                    "ringAssignment": assignment.as_record(),
                    "rulespecGraph": _plain(view.rulespec_graph),
                    "members": sorted(
                        (_plain(member.record) for member in view.iter_members(release_iri=source.release_id)),
                        key=lambda value: cast(str, value["@id"]),
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
        field = "concepts" if self.release_pin["releaseKind"] == "sourceConceptRelease" else "members"
        return frozenset(
            cast(str, record["id" if field == "concepts" else "@id"])
            for record in cast(Sequence[Mapping[str, Any]], self.record[field])
        )

    @property
    def concept_records(self) -> tuple[Mapping[str, Any], ...]:
        field = "concepts" if self.release_pin["releaseKind"] == "sourceConceptRelease" else "members"
        return cast(tuple[Mapping[str, Any], ...], self.record[field])


__all__ = [
    "ATLAS_RELEASE_SNAPSHOT_TYPE",
    "ATLAS_RELEASE_SNAPSHOT_VERSION",
    "AtlasReleaseSnapshot",
    "AtlasReleaseSnapshotError",
]
