"""Deterministic packages for source-controlled terms that are not concept releases.

Some publishers expose useful term lists or codes without stable concept
identifiers or a named vocabulary release.  This module packages those exact
source observations for development lookup without promoting them into a
Rulespec concept scheme. A package may also carry an explicit UUIDv7
registration event and UUIDv7 local record IDs; those identify RefSpec records,
never publisher concepts. Individual source observations retain their own
UUIDv7 fetch IDs and fetch times.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    canonical_jsonl_bytes,
    plain_json,
    sha256_digest,
    source_artifact_path,
)
from refspec.registry.infrastructure.identifier_validation import (
    absolute_uri_issue,
    is_sha256_digest,
)
from refspec.registry.infrastructure.source_identity import (
    SourceCaptureEvent,
    SourceIdentityError,
    SourceRegistrationEvent,
    require_aware_datetime_text,
    validate_uuid7_urn,
)

SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION = "2.0"

ResourceKind = Literal[
    "sourceTermSnapshot",
    "controlledCodeList",
    "navigationList",
]
IdentityStatus = Literal[
    "captureLocalObservationsOnly",
    "publisherIdentifiersPreserved",
    "mixed",
]
ResourceUse = Literal[
    "sourceAssignedEvidence",
    "searchExpansion",
    "mappingReference",
    "navigation",
    "deterministicMetadata",
]

_RESOURCE_KINDS = frozenset(
    {
        "sourceTermSnapshot",
        "controlledCodeList",
        "navigationList",
    }
)
_IDENTITY_STATUSES = frozenset(
    {
        "captureLocalObservationsOnly",
        "publisherIdentifiersPreserved",
        "mixed",
    }
)
_RESOURCE_USES = frozenset(
    {
        "sourceAssignedEvidence",
        "searchExpansion",
        "mappingReference",
        "navigation",
        "deterministicMetadata",
    }
)
_LABEL_ROLES = frozenset({"preferred", "alternate", "hidden"})
_FORBIDDEN_GOVERNANCE_FIELDS = frozenset(
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
        "publisherConceptIri",
        "usageCeiling",
    }
)
# Kept local: vocabulary.require_language_tag uses a stricter BCP 47 grammar and
# would change which observation labels SCR currently accepts.
_LANGUAGE_TAG = re.compile(r"^(?:und|[A-Za-z]{2,8})(?:-[A-Za-z0-9]{1,8})*$")
_CAPTURE_LOCAL_OBSERVATION_FIELDS = frozenset(
    {
        "id",
        "sourceArtifact",
        "sourcePath",
        "sourceOrdinal",
        "sourceUrl",
        "sourceObservedAt",
        "sourceFetchId",
    }
)
_CAPTURE_LOCAL_IDENTIFIER_FIELDS = frozenset(
    {
        "sourceUri",
        "sourcePath",
        "observedAt",
        "sourceDigest",
    }
)
_PACKAGE_FILENAMES = frozenset(
    {
        "bundle-manifest.json",
        "coverage-report.json",
        "observations.jsonl",
        "resource-manifest.json",
    }
)


class SourceControlledResourceError(ValueError):
    """A source-controlled resource package is incomplete or inconsistent."""


# Local aliases preserve monkeypatch surfaces and call-site names.
_plain_json = plain_json
_canonical_bytes = canonical_json_bytes
_canonical_jsonl = canonical_jsonl_bytes
_sha256 = sha256_digest


def _source_artifact_path(identifier: str, payload: bytes) -> str:
    return source_artifact_path(identifier, payload, style="scr")


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceControlledResourceError(f"{label} must be non-empty text")
    return value


def _require_absolute_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise SourceControlledResourceError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise SourceControlledResourceError(f"{label} must not contain credentials")
    return iri


def _require_datetime(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceControlledResourceError(f"{label} must be non-empty text")
    try:
        return require_aware_datetime_text(value, label=label)
    except SourceIdentityError as error:
        raise SourceControlledResourceError(str(error)) from error


def _forbid_governance_fields(value: Any, *, label: str) -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(set(value) & _FORBIDDEN_GOVERNANCE_FIELDS)
        if forbidden:
            raise SourceControlledResourceError(
                f"{label} contains unqualified identity or governance fields {forbidden!r}"
            )
        for key, child in value.items():
            _forbid_governance_fields(child, label=f"{label}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _forbid_governance_fields(child, label=f"{label}[{index}]")


def _validate_source_scheme(
    value: object,
    *,
    source_ids: frozenset[str],
) -> dict[str, Any]:
    label = "resource_manifest.sourceScheme"
    if not isinstance(value, Mapping):
        raise SourceControlledResourceError(f"{label} must be an object")
    _forbid_governance_fields(value, label=label)
    required = {
        "id",
        "code",
        "label",
        "sourceArtifact",
        "sourceFetchId",
        "sourceObservedAt",
    }
    if set(value) != required:
        raise SourceControlledResourceError(f"{label} fields do not match package version 2.0")
    _require_absolute_iri(value["id"], f"{label}.id")
    _require_text(value["code"], f"{label}.code")
    _require_text(value["label"], f"{label}.label")
    source_artifact = _require_absolute_iri(
        value["sourceArtifact"],
        f"{label}.sourceArtifact",
    )
    if source_artifact not in source_ids:
        raise SourceControlledResourceError(f"{label}.sourceArtifact is not in the package source set")
    try:
        SourceCaptureEvent(
            fetch_id=_require_text(value["sourceFetchId"], f"{label}.sourceFetchId"),
            fetched_at=_require_datetime(value["sourceObservedAt"], f"{label}.sourceObservedAt"),
        )
    except SourceIdentityError as error:
        raise SourceControlledResourceError(f"{label} fetch event is invalid: {error}") from error
    return _plain_json(value)


def _validate_registration_event(value: object) -> dict[str, str]:
    label = "resource_manifest.registrationEvent"
    if not isinstance(value, Mapping) or set(value) != {"registrationId", "registeredAt"}:
        raise SourceControlledResourceError(f"{label} must contain registrationId and registeredAt")
    try:
        event = SourceRegistrationEvent(
            registration_id=_require_text(value["registrationId"], f"{label}.registrationId"),
            registered_at=_require_datetime(value["registeredAt"], f"{label}.registeredAt"),
        )
    except SourceIdentityError as error:
        raise SourceControlledResourceError(f"{label} is invalid: {error}") from error
    return event.as_dict()


def capture_independent_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return exactly the observation fields used by the local content digest."""

    result = {key: child for key, child in _plain_json(value).items() if key not in _CAPTURE_LOCAL_OBSERVATION_FIELDS}
    identifiers = result.get("identifiers")
    if isinstance(identifiers, Sequence) and not isinstance(identifiers, (str, bytes)):
        result["identifiers"] = [
            (
                {key: child for key, child in identifier.items() if key not in _CAPTURE_LOCAL_IDENTIFIER_FIELDS}
                if isinstance(identifier, Mapping)
                else identifier
            )
            for identifier in identifiers
        ]
    return result


def local_record_identity_digests(
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Hash durable local record membership and capture-independent content.

    ``observationSetDigest`` still seals the complete rows.  These additional
    digests answer two different refresh questions: whether the locally
    tracked record set changed, and whether the current content of those
    records changed after acquisition-only fields are removed.
    """

    rows = tuple(_plain_json(value) for value in observations)
    has_local_ids = tuple("localRecordId" in row for row in rows)
    if not any(has_local_ids):
        return {}
    if not all(has_local_ids):
        raise SourceControlledResourceError("either every observation or no observation must carry localRecordId")
    local_ids: list[str] = []
    content_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        try:
            local_id = validate_uuid7_urn(
                row["localRecordId"],
                label=f"observations[{index}].localRecordId",
            )
        except SourceIdentityError as error:
            raise SourceControlledResourceError(str(error)) from error
        local_ids.append(local_id)
        content_rows.append(capture_independent_observation(row))
    if len(local_ids) != len(set(local_ids)):
        raise SourceControlledResourceError("observations must have unique localRecordId values")
    content_rows.sort(key=lambda row: str(row["localRecordId"]))
    return {
        "localRecordIdSetDigest": _sha256(_canonical_bytes(sorted(local_ids))),
        "localRecordContentSetDigest": _sha256(_canonical_jsonl(content_rows)),
    }


def _artifact_descriptor(
    path: str,
    payload: bytes,
    *,
    role: str,
    source_id: str | None = None,
) -> dict[str, Any]:
    descriptor: dict[str, Any] = {
        "path": path,
        "role": role,
        "sha256": _sha256(payload),
        "byteLength": len(payload),
    }
    if source_id is not None:
        descriptor["sourceId"] = source_id
    return descriptor


def _resource_manifest_id(manifest: Mapping[str, Any]) -> str:
    """Derive capture identity from every factual manifest field."""

    payload = {key: value for key, value in _plain_json(manifest).items() if key != "id"}
    resource_id = _require_text(payload.get("resourceId"), "resource_manifest.resourceId")
    digest = _sha256(_canonical_bytes(payload)).removeprefix("sha256:")
    return f"urn:ref:source-controlled-resource:v2:{resource_id}:{digest}"


def _validate_identifier(
    value: object,
    *,
    label: str,
    expected_source_digest: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceControlledResourceError(f"{label} must be an object")
    allowed = {
        "value",
        "kind",
        "authorityUri",
        "sourceUri",
        "sourcePath",
        "observedAt",
        "effectiveFrom",
        "effectiveThrough",
        "sourceDigest",
    }
    required = {
        "value",
        "kind",
        "authorityUri",
        "sourceUri",
        "sourcePath",
        "observedAt",
        "sourceDigest",
    }
    if set(value) - allowed or not required.issubset(value):
        raise SourceControlledResourceError(f"{label} must contain the qualified identifier fields")
    _require_text(value["value"], f"{label}.value")
    _require_text(value["kind"], f"{label}.kind")
    _require_absolute_iri(value["authorityUri"], f"{label}.authorityUri")
    _require_absolute_iri(value["sourceUri"], f"{label}.sourceUri")
    _require_text(value["sourcePath"], f"{label}.sourcePath")
    _require_datetime(value["observedAt"], f"{label}.observedAt")
    digest = value["sourceDigest"]
    if not is_sha256_digest(digest):
        raise SourceControlledResourceError(f"{label}.sourceDigest must be a SHA-256 digest")
    if digest != expected_source_digest:
        raise SourceControlledResourceError(f"{label}.sourceDigest does not match its retained source artifact")
    for field in ("effectiveFrom", "effectiveThrough"):
        if field in value:
            _require_text(value[field], f"{label}.{field}")
    return _plain_json(value)


def _validate_observation(
    value: object,
    *,
    index: int,
    source_ids: frozenset[str],
    source_digests: Mapping[str, str],
    resource_uses: frozenset[str],
) -> dict[str, Any]:
    label = f"observations[{index}]"
    if not isinstance(value, Mapping):
        raise SourceControlledResourceError(f"{label} must be an object")
    _forbid_governance_fields(value, label=label)
    required = {
        "id",
        "sourceArtifact",
        "sourcePath",
        "sourceOrdinal",
        "labels",
        "identifiers",
        "uses",
        "conceptIdentityClaimed",
    }
    if not required.issubset(value):
        raise SourceControlledResourceError(f"{label} is missing {sorted(required - set(value))}")
    identifier = _require_absolute_iri(value["id"], f"{label}.id")
    source_artifact = _require_absolute_iri(
        value["sourceArtifact"],
        f"{label}.sourceArtifact",
    )
    if source_artifact not in source_ids:
        raise SourceControlledResourceError(f"{label}.sourceArtifact is not in the package source set")
    _require_text(value["sourcePath"], f"{label}.sourcePath")
    ordinal = value["sourceOrdinal"]
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
        raise SourceControlledResourceError(f"{label}.sourceOrdinal must be a non-negative integer")
    labels = value["labels"]
    if not isinstance(labels, Sequence) or isinstance(labels, (str, bytes)) or not labels:
        raise SourceControlledResourceError(f"{label}.labels must be non-empty")
    preferred_languages: set[str] = set()
    for label_index, expression in enumerate(labels):
        expression_label = f"{label}.labels[{label_index}]"
        if not isinstance(expression, Mapping):
            raise SourceControlledResourceError(f"{expression_label} must be an object")
        if set(expression) != {"value", "language", "role"}:
            raise SourceControlledResourceError(f"{expression_label} must contain value, language, and role")
        _require_text(expression["value"], f"{expression_label}.value")
        language = _require_text(
            expression["language"],
            f"{expression_label}.language",
        )
        if _LANGUAGE_TAG.fullmatch(language) is None:
            raise SourceControlledResourceError(f"{expression_label}.language must be a BCP 47 tag")
        role = expression["role"]
        if role not in _LABEL_ROLES:
            raise SourceControlledResourceError(f"{expression_label}.role is unsupported")
        if role == "preferred":
            if language in preferred_languages:
                raise SourceControlledResourceError(f"{label} repeats a preferred label language")
            preferred_languages.add(language)
    if not preferred_languages:
        raise SourceControlledResourceError(f"{label} must contain a preferred label")
    identifiers = value["identifiers"]
    if not isinstance(identifiers, Sequence) or isinstance(
        identifiers,
        (str, bytes),
    ):
        raise SourceControlledResourceError(f"{label}.identifiers must be an array")
    identifier_rows = [
        _validate_identifier(
            item,
            label=f"{label}.identifiers[{item_index}]",
            expected_source_digest=source_digests[source_artifact],
        )
        for item_index, item in enumerate(identifiers)
    ]
    if len({_canonical_bytes(item) for item in identifier_rows}) != len(identifier_rows):
        raise SourceControlledResourceError(f"{label}.identifiers repeats an exact qualified identifier")
    uses = value["uses"]
    if (
        not isinstance(uses, Sequence)
        or isinstance(uses, (str, bytes))
        or not uses
        or len(set(uses)) != len(uses)
        or not set(uses).issubset(resource_uses)
    ):
        raise SourceControlledResourceError(f"{label}.uses must be unique declared resource uses")
    if value["conceptIdentityClaimed"] is not False:
        raise SourceControlledResourceError(f"{label}.conceptIdentityClaimed must be false")
    has_source_fetch_id = "sourceFetchId" in value
    has_source_observed_at = "sourceObservedAt" in value
    if has_source_observed_at:
        _require_datetime(value["sourceObservedAt"], f"{label}.sourceObservedAt")
    if has_source_fetch_id and not has_source_observed_at:
        raise SourceControlledResourceError(f"{label}.sourceFetchId requires sourceObservedAt")
    if has_source_fetch_id:
        try:
            SourceCaptureEvent(
                fetch_id=_require_text(value["sourceFetchId"], f"{label}.sourceFetchId"),
                fetched_at=_require_datetime(value["sourceObservedAt"], f"{label}.sourceObservedAt"),
            )
        except SourceIdentityError as error:
            raise SourceControlledResourceError(f"{label} fetch event is invalid: {error}") from error
    if "localRecordId" in value:
        try:
            validate_uuid7_urn(
                value["localRecordId"],
                label=f"{label}.localRecordId",
            )
        except SourceIdentityError as error:
            raise SourceControlledResourceError(str(error)) from error
    plain = _plain_json(value)
    plain["id"] = identifier
    plain["identifiers"] = identifier_rows
    plain["uses"] = sorted(uses)
    return plain


@dataclass(frozen=True, slots=True)
class SourceControlledResourceBundle:
    """One closed, development-only package of source term observations."""

    resource_manifest: Mapping[str, Any]
    coverage_report: Mapping[str, Any]
    observations: tuple[Mapping[str, Any], ...]
    source_artifacts: Mapping[str, bytes]

    def __post_init__(self) -> None:
        manifest = _plain_json(self.resource_manifest)
        coverage = _plain_json(self.coverage_report)
        if not isinstance(manifest, dict) or not isinstance(coverage, dict):
            raise SourceControlledResourceError("resource_manifest and coverage_report must be objects")
        if manifest.get("schemaVersion") != SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION:
            raise SourceControlledResourceError("resource_manifest.schemaVersion is unsupported")
        required_manifest = {
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
        optional_manifest = {"registrationEvent", "sourceScheme"}
        if not required_manifest.issubset(manifest) or set(manifest) - required_manifest - optional_manifest:
            raise SourceControlledResourceError("resource_manifest fields do not match package version 2.0")
        _require_absolute_iri(manifest["id"], "resource_manifest.id")
        _require_text(manifest["resourceId"], "resource_manifest.resourceId")
        _require_text(manifest["title"], "resource_manifest.title")
        if manifest["resourceKind"] not in _RESOURCE_KINDS:
            raise SourceControlledResourceError("resource_manifest.resourceKind is unsupported")
        if manifest["identityStatus"] not in _IDENTITY_STATUSES:
            raise SourceControlledResourceError("resource_manifest.identityStatus is unsupported")
        if manifest["conceptIdentityClaimed"] is not False:
            raise SourceControlledResourceError("source-controlled packages cannot claim concept identity")
        _require_datetime(manifest["capturedAt"], "resource_manifest.capturedAt")
        uses = manifest["uses"]
        if (
            not isinstance(uses, Sequence)
            or isinstance(uses, (str, bytes))
            or not uses
            or len(set(uses)) != len(uses)
            or not set(uses).issubset(_RESOURCE_USES)
        ):
            raise SourceControlledResourceError("resource_manifest.uses must be unique supported uses")
        manifest["uses"] = sorted(uses)
        if manifest["observationCount"] != len(self.observations):
            raise SourceControlledResourceError("resource_manifest.observationCount does not match observations")
        if not isinstance(self.source_artifacts, Mapping) or not self.source_artifacts:
            raise SourceControlledResourceError("source_artifacts must retain at least one exact source")
        source_descriptors = manifest["sourceArtifacts"]
        if not isinstance(source_descriptors, Sequence) or isinstance(
            source_descriptors,
            (str, bytes),
        ):
            raise SourceControlledResourceError("resource_manifest.sourceArtifacts must be an array")
        expected_sources: list[dict[str, Any]] = []
        source_paths: set[str] = set()
        for source_id, payload in sorted(self.source_artifacts.items()):
            identifier = _require_absolute_iri(source_id, "source_artifacts key")
            if not isinstance(payload, bytes) or not payload:
                raise SourceControlledResourceError(f"source_artifacts[{identifier!r}] must be non-empty bytes")
            path = _source_artifact_path(identifier, payload)
            if path in source_paths:
                raise SourceControlledResourceError("source artifacts produced a duplicate package path")
            source_paths.add(path)
            expected_sources.append(
                {
                    "id": identifier,
                    "path": path,
                    "sha256": _sha256(payload),
                    "byteLength": len(payload),
                }
            )
        if source_descriptors != expected_sources:
            raise SourceControlledResourceError("resource_manifest.sourceArtifacts do not match retained bytes")
        source_ids = frozenset(self.source_artifacts)
        source_digests = {source_id: _sha256(payload) for source_id, payload in self.source_artifacts.items()}
        if "registrationEvent" in manifest:
            manifest["registrationEvent"] = _validate_registration_event(manifest["registrationEvent"])
        if "sourceScheme" in manifest:
            manifest["sourceScheme"] = _validate_source_scheme(
                manifest["sourceScheme"],
                source_ids=source_ids,
            )
        validated_observations = tuple(
            _validate_observation(
                value,
                index=index,
                source_ids=source_ids,
                source_digests=source_digests,
                resource_uses=frozenset(uses),
            )
            for index, value in enumerate(self.observations)
        )
        observation_ids = [item["id"] for item in validated_observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise SourceControlledResourceError("observations must have unique capture-local identifiers")
        expected_observation_digest = _sha256(_canonical_jsonl(validated_observations))
        if manifest["observationSetDigest"] != expected_observation_digest:
            raise SourceControlledResourceError("resource_manifest.observationSetDigest is stale")
        expected_manifest_id = _resource_manifest_id(manifest)
        if manifest["id"] != expected_manifest_id:
            raise SourceControlledResourceError("resource_manifest.id is stale")
        local_identity_digests = local_record_identity_digests(validated_observations)
        if coverage.get("schemaVersion") != SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION:
            raise SourceControlledResourceError("resource_manifest and coverage_report schemaVersion values disagree")
        expected_coverage = {
            "schemaVersion": SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION,
            "resourceManifest": manifest["id"],
            "reportStatus": coverage.get("reportStatus"),
            "sourceObservedCount": coverage.get("sourceObservedCount"),
            "parsedCount": coverage.get("parsedCount"),
            "packagedCount": coverage.get("packagedCount"),
            "excludedCount": coverage.get("excludedCount"),
            "failedCount": coverage.get("failedCount"),
            "observationSetDigest": coverage.get("observationSetDigest"),
            "gaps": coverage.get("gaps"),
        }
        expected_coverage.update({key: coverage.get(key) for key in local_identity_digests})
        if coverage != expected_coverage:
            raise SourceControlledResourceError("coverage_report fields do not match package version 2.0")
        for field in (
            "sourceObservedCount",
            "parsedCount",
            "packagedCount",
            "excludedCount",
            "failedCount",
        ):
            value = coverage[field]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SourceControlledResourceError(f"coverage_report.{field} must be a non-negative integer")
        if coverage["packagedCount"] != len(validated_observations):
            raise SourceControlledResourceError("coverage_report.packagedCount does not match observations")
        if coverage["sourceObservedCount"] != (
            coverage["parsedCount"] + coverage["excludedCount"] + coverage["failedCount"]
        ):
            raise SourceControlledResourceError("coverage_report does not account for every source observation")
        if coverage["parsedCount"] != coverage["packagedCount"]:
            raise SourceControlledResourceError("every parsed source observation must enter the package")
        gaps = coverage["gaps"]
        if not isinstance(gaps, Sequence) or isinstance(gaps, (str, bytes)):
            raise SourceControlledResourceError("coverage_report.gaps must be an array")
        if coverage["reportStatus"] not in {"pass", "gap"}:
            raise SourceControlledResourceError("coverage_report.reportStatus must be pass or gap")
        if coverage["reportStatus"] == "pass" and (coverage["excludedCount"] or coverage["failedCount"] or gaps):
            raise SourceControlledResourceError("a passing coverage report cannot hide exclusions, failures, or gaps")
        if coverage["observationSetDigest"] != expected_observation_digest:
            raise SourceControlledResourceError("coverage_report.observationSetDigest is stale")
        for field, expected_value in local_identity_digests.items():
            if coverage[field] != expected_value:
                raise SourceControlledResourceError(f"coverage_report.{field} is stale")
        object.__setattr__(
            self,
            "resource_manifest",
            cast(Mapping[str, Any], deep_freeze_json(manifest)),
        )
        object.__setattr__(
            self,
            "coverage_report",
            cast(Mapping[str, Any], deep_freeze_json(coverage)),
        )
        object.__setattr__(
            self,
            "observations",
            tuple(cast(Mapping[str, Any], deep_freeze_json(value)) for value in validated_observations),
        )
        object.__setattr__(
            self,
            "source_artifacts",
            cast(
                Mapping[str, bytes],
                deep_freeze_json({str(key): value for key, value in self.source_artifacts.items()}),
            ),
        )

    def _logical_digest(self) -> str:
        return _sha256(
            _canonical_bytes(
                {
                    "resourceManifest": self.resource_manifest,
                    "coverageReport": self.coverage_report,
                    "observationSetDigest": self.coverage_report["observationSetDigest"],
                    "sourceArtifacts": self.resource_manifest["sourceArtifacts"],
                }
            )
        )

    def artifact_bytes(self) -> dict[str, bytes]:
        """Return the complete deterministic package contents."""

        artifacts: dict[str, bytes] = {
            "resource-manifest.json": _canonical_bytes(self.resource_manifest),
            "coverage-report.json": _canonical_bytes(self.coverage_report),
            "observations.jsonl": _canonical_jsonl(self.observations),
        }
        for source_id, payload in sorted(self.source_artifacts.items()):
            artifacts[_source_artifact_path(source_id, payload)] = payload
        source_id_by_path = {item["path"]: item["id"] for item in self.resource_manifest["sourceArtifacts"]}
        descriptors = [
            _artifact_descriptor(
                path,
                payload,
                role=(
                    "resourceManifest"
                    if path == "resource-manifest.json"
                    else "coverageReport"
                    if path == "coverage-report.json"
                    else "observations"
                    if path == "observations.jsonl"
                    else "sourceArtifact"
                ),
                source_id=source_id_by_path.get(path),
            )
            for path, payload in sorted(artifacts.items())
        ]
        artifacts["bundle-manifest.json"] = _canonical_bytes(
            {
                "schemaVersion": SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION,
                "packageKind": "sourceControlledResource",
                "resourceManifest": self.resource_manifest["id"],
                "logicalDigest": self._logical_digest(),
                "artifacts": descriptors,
            }
        )
        return dict(sorted(artifacts.items()))

    @property
    def logical_digest(self) -> str:
        """Return the stable package identity recorded by its bundle manifest."""

        return self._logical_digest()

    def write_to(self, path: Path) -> Path:
        """Write the closed package atomically to a new directory."""

        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise SourceControlledResourceError(f"package destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}-",
                dir=destination.parent,
            )
        )
        try:
            for relative_path, payload in self.artifact_bytes().items():
                output = temporary / relative_path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(payload)
            os.replace(temporary, destination)
        except BaseException:
            for item in sorted(
                temporary.rglob("*"),
                key=lambda value: len(value.parts),
                reverse=True,
            ):
                if item.is_symlink() or item.is_file():
                    item.unlink(missing_ok=True)
                elif item.is_dir():
                    item.rmdir()
            temporary.rmdir()
            raise
        return destination


def build_source_controlled_resource_bundle(
    *,
    resource_id: str,
    title: str,
    resource_kind: ResourceKind,
    identity_status: IdentityStatus,
    uses: Sequence[ResourceUse],
    captured_at: str,
    observations: Sequence[Mapping[str, Any]],
    source_artifacts: Mapping[str, bytes],
    registration_event: Mapping[str, Any] | None = None,
    source_scheme: Mapping[str, Any] | None = None,
    source_observed_count: int | None = None,
    excluded_count: int = 0,
    failed_count: int = 0,
    gaps: Sequence[Mapping[str, Any]] = (),
) -> SourceControlledResourceBundle:
    """Build one source package and derive every count and digest."""

    _require_text(resource_id, "resource_id")
    source_descriptors = [
        {
            "id": source_id,
            "path": _source_artifact_path(source_id, payload),
            "sha256": _sha256(payload),
            "byteLength": len(payload),
        }
        for source_id, payload in sorted(source_artifacts.items())
    ]
    normalized_uses = tuple(sorted(uses))
    source_ids = frozenset(source_artifacts)
    source_digests = {source_id: _sha256(payload) for source_id, payload in source_artifacts.items()}
    observation_rows = tuple(
        _validate_observation(
            value,
            index=index,
            source_ids=source_ids,
            source_digests=source_digests,
            resource_uses=frozenset(normalized_uses),
        )
        for index, value in enumerate(observations)
    )
    observed = (
        len(observation_rows) + excluded_count + failed_count
        if source_observed_count is None
        else source_observed_count
    )
    registration_event_row = None if registration_event is None else _plain_json(registration_event)
    source_scheme_row = None if source_scheme is None else _plain_json(source_scheme)
    observation_set_digest = _sha256(_canonical_jsonl(observation_rows))
    manifest = {
        "schemaVersion": SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION,
        "resourceId": resource_id,
        "title": title,
        "resourceKind": resource_kind,
        "identityStatus": identity_status,
        "conceptIdentityClaimed": False,
        "capturedAt": captured_at,
        "uses": list(normalized_uses),
        "observationCount": len(observation_rows),
        "observationSetDigest": observation_set_digest,
        "sourceArtifacts": source_descriptors,
    }
    if registration_event_row is not None:
        manifest["registrationEvent"] = registration_event_row
    if source_scheme_row is not None:
        manifest["sourceScheme"] = source_scheme_row
    manifest_id = _resource_manifest_id(manifest)
    manifest["id"] = manifest_id
    coverage = {
        "schemaVersion": SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION,
        "resourceManifest": manifest_id,
        "reportStatus": ("gap" if excluded_count or failed_count or gaps else "pass"),
        "sourceObservedCount": observed,
        "parsedCount": len(observation_rows),
        "packagedCount": len(observation_rows),
        "excludedCount": excluded_count,
        "failedCount": failed_count,
        "observationSetDigest": observation_set_digest,
        "gaps": [_plain_json(value) for value in gaps],
    }
    coverage.update(local_record_identity_digests(observation_rows))
    return SourceControlledResourceBundle(
        resource_manifest=manifest,
        coverage_report=coverage,
        observations=observation_rows,
        source_artifacts=source_artifacts,
    )


@dataclass(frozen=True, slots=True)
class SourceControlledResourceView:
    """A package reopened only after its complete closed set verifies."""

    path: Path
    resource_manifest: Mapping[str, Any]
    coverage_report: Mapping[str, Any]
    observations: tuple[Mapping[str, Any], ...]
    source_artifacts: Mapping[str, bytes]
    logical_digest: str

    @classmethod
    def open(cls, path: Path) -> SourceControlledResourceView:
        """Open and verify one package directory."""

        root = Path(path)
        if root.is_symlink() or not root.is_dir():
            raise SourceControlledResourceError(f"package path is not a regular directory: {root}")
        actual_paths: set[str] = set()
        for item in root.rglob("*"):
            if item.is_symlink():
                raise SourceControlledResourceError(f"package contains a symlink: {item}")
            if item.is_file():
                actual_paths.add(item.relative_to(root).as_posix())
        manifest_path = root / "bundle-manifest.json"
        if not manifest_path.is_file():
            raise SourceControlledResourceError("package lacks bundle-manifest.json")
        try:
            bundle_manifest_bytes = manifest_path.read_bytes()
            bundle_manifest = json.loads(bundle_manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SourceControlledResourceError("bundle manifest must be valid UTF-8 JSON") from error
        required_bundle = {
            "schemaVersion",
            "packageKind",
            "resourceManifest",
            "logicalDigest",
            "artifacts",
        }
        if (
            not isinstance(bundle_manifest, Mapping)
            or set(bundle_manifest) != required_bundle
            or bundle_manifest["schemaVersion"] != SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION
            or bundle_manifest["packageKind"] != "sourceControlledResource"
            or not isinstance(bundle_manifest["artifacts"], Sequence)
        ):
            raise SourceControlledResourceError("bundle manifest shape or version is unsupported")
        expected_paths = {"bundle-manifest.json"}
        loaded_payloads: dict[str, bytes] = {
            "bundle-manifest.json": bundle_manifest_bytes,
        }
        source_path_by_id: dict[str, str] = {}
        for index, descriptor in enumerate(bundle_manifest["artifacts"]):
            label = f"bundle manifest artifacts[{index}]"
            if not isinstance(descriptor, Mapping):
                raise SourceControlledResourceError(f"{label} must be an object")
            required = {"path", "role", "sha256", "byteLength"}
            if not required.issubset(descriptor):
                raise SourceControlledResourceError(f"{label} lacks its digest descriptor")
            relative_path = _require_text(
                descriptor["path"],
                f"{label}.path",
            )
            if relative_path.startswith("/") or ".." in Path(relative_path).parts or relative_path in expected_paths:
                raise SourceControlledResourceError(f"{label}.path is unsafe or repeated")
            expected_paths.add(relative_path)
            artifact_path = root / relative_path
            if not artifact_path.is_file() or artifact_path.is_symlink():
                raise SourceControlledResourceError(f"package artifact is missing or unsafe: {relative_path}")
            payload = artifact_path.read_bytes()
            if descriptor["sha256"] != _sha256(payload) or descriptor["byteLength"] != len(payload):
                raise SourceControlledResourceError(f"package artifact pin failed: {relative_path}")
            loaded_payloads[relative_path] = payload
            if descriptor["role"] == "sourceArtifact":
                source_id = _require_absolute_iri(
                    descriptor.get("sourceId"),
                    f"{label}.sourceId",
                )
                if source_id in source_path_by_id:
                    raise SourceControlledResourceError("bundle manifest repeats a source artifact identifier")
                source_path_by_id[source_id] = relative_path
        if actual_paths != expected_paths:
            raise SourceControlledResourceError("package file set differs from its closed bundle manifest")
        if not _PACKAGE_FILENAMES.issubset(expected_paths):
            raise SourceControlledResourceError("package lacks a required resource artifact")
        try:
            resource_manifest = json.loads(loaded_payloads["resource-manifest.json"])
            coverage_report = json.loads(loaded_payloads["coverage-report.json"])
            observations = tuple(
                json.loads(line) for line in loaded_payloads["observations.jsonl"].decode("utf-8").splitlines() if line
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SourceControlledResourceError("resource package JSON is malformed") from error
        if not isinstance(resource_manifest, Mapping) or not isinstance(coverage_report, Mapping):
            raise SourceControlledResourceError("resource_manifest and coverage_report must be objects")
        bundle_schema_version = bundle_manifest["schemaVersion"]
        if (
            resource_manifest.get("schemaVersion") != bundle_schema_version
            or coverage_report.get("schemaVersion") != bundle_schema_version
        ):
            raise SourceControlledResourceError("bundle, resource, and coverage schemaVersion values disagree")
        source_artifacts = {
            source_id: loaded_payloads[relative_path] for source_id, relative_path in source_path_by_id.items()
        }
        rebuilt = SourceControlledResourceBundle(
            resource_manifest=resource_manifest,
            coverage_report=coverage_report,
            observations=observations,
            source_artifacts=source_artifacts,
        )
        expected_artifacts = rebuilt.artifact_bytes()
        for relative_path, payload in expected_artifacts.items():
            if loaded_payloads[relative_path] != payload:
                raise SourceControlledResourceError(f"package artifact is not canonical: {relative_path}")
        logical_digest = rebuilt.logical_digest
        if bundle_manifest["logicalDigest"] != logical_digest:
            raise SourceControlledResourceError("bundle manifest logicalDigest is stale")
        return cls(
            path=root,
            resource_manifest=cast(
                Mapping[str, Any],
                deep_freeze_json(rebuilt.resource_manifest),
            ),
            coverage_report=cast(
                Mapping[str, Any],
                deep_freeze_json(rebuilt.coverage_report),
            ),
            observations=cast(
                tuple[Mapping[str, Any], ...],
                deep_freeze_json(rebuilt.observations),
            ),
            source_artifacts=cast(
                Mapping[str, bytes],
                deep_freeze_json(rebuilt.source_artifacts),
            ),
            logical_digest=logical_digest,
        )

    def source_artifact_bytes(self, identifier: str) -> bytes:
        """Return one verified exact source artifact."""

        try:
            return self.source_artifacts[identifier]
        except KeyError as error:
            raise SourceControlledResourceError(f"package has no source artifact {identifier!r}") from error


__all__ = [
    "SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION",
    "IdentityStatus",
    "ResourceKind",
    "ResourceUse",
    "SourceControlledResourceBundle",
    "SourceControlledResourceError",
    "SourceControlledResourceView",
    "build_source_controlled_resource_bundle",
    "capture_independent_observation",
    "local_record_identity_digests",
]
