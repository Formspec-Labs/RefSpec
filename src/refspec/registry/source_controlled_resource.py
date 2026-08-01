"""Deterministic packages for source-controlled terms that are not concept releases.

Some publishers expose useful term lists or codes without stable concept
identifiers or a named vocabulary release.  This module packages those exact
source observations for development lookup without promoting them into a
Rulespec concept scheme.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from refspec.immutable import deep_freeze_json
from refspec.storage import canonical_json

SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION = "1.0"

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
        "navigation",
        "deterministicMetadata",
    }
)
_LABEL_ROLES = frozenset({"preferred", "alternate", "hidden"})
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_LANGUAGE_TAG = re.compile(r"^(?:und|[A-Za-z]{2,8})(?:-[A-Za-z0-9]{1,8})*$")
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


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain_json(child) for child in value]
    return value


def _canonical_bytes(value: object) -> bytes:
    return canonical_json(_plain_json(value)).encode("utf-8") + b"\n"


def _canonical_jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(_canonical_bytes(row) for row in rows)


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceControlledResourceError(f"{label} must be non-empty text")
    return value


def _require_absolute_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    parsed = urlsplit(iri)
    if not parsed.scheme:
        raise SourceControlledResourceError(f"{label} must be an absolute IRI")
    if parsed.username is not None or parsed.password is not None:
        raise SourceControlledResourceError(f"{label} must not contain credentials")
    return iri


def _require_datetime(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as error:
        raise SourceControlledResourceError(f"{label} must be an ISO 8601 date-time") from error
    if parsed.tzinfo is None:
        raise SourceControlledResourceError(f"{label} must include a time zone")
    return text


def _source_artifact_path(identifier: str, payload: bytes) -> str:
    identity = _canonical_bytes(
        {
            "id": identifier,
            "sha256": _sha256(payload),
            "byteLength": len(payload),
        }
    )
    return f"sources/source-{hashlib.sha256(identity).hexdigest()}.bin"


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
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
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
    required = {
        "id",
        "sourceArtifact",
        "sourcePath",
        "sourceOrdinal",
        "labels",
        "identifiers",
        "eligibleUses",
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
    uses = value["eligibleUses"]
    if (
        not isinstance(uses, Sequence)
        or isinstance(uses, (str, bytes))
        or not uses
        or len(set(uses)) != len(uses)
        or not set(uses).issubset(resource_uses)
    ):
        raise SourceControlledResourceError(f"{label}.eligibleUses must be unique declared resource uses")
    if value["conceptIdentityClaimed"] is not False:
        raise SourceControlledResourceError(f"{label}.conceptIdentityClaimed must be false")
    plain = _plain_json(value)
    plain["id"] = identifier
    plain["identifiers"] = identifier_rows
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
        required_manifest = {
            "schemaVersion",
            "id",
            "resourceId",
            "title",
            "resourceKind",
            "identityStatus",
            "usageCeiling",
            "candidateUseAuthorized",
            "acceptedOutputUseAuthorized",
            "conceptIdentityClaimed",
            "capturedAt",
            "uses",
            "observationCount",
            "sourceArtifacts",
        }
        if set(manifest) != required_manifest:
            raise SourceControlledResourceError("resource_manifest fields do not match package version 1.0")
        if manifest["schemaVersion"] != SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION:
            raise SourceControlledResourceError("resource_manifest.schemaVersion is unsupported")
        _require_absolute_iri(manifest["id"], "resource_manifest.id")
        _require_text(manifest["resourceId"], "resource_manifest.resourceId")
        _require_text(manifest["title"], "resource_manifest.title")
        if manifest["resourceKind"] not in _RESOURCE_KINDS:
            raise SourceControlledResourceError("resource_manifest.resourceKind is unsupported")
        if manifest["identityStatus"] not in _IDENTITY_STATUSES:
            raise SourceControlledResourceError("resource_manifest.identityStatus is unsupported")
        if manifest["usageCeiling"] != "developmentOnly":
            raise SourceControlledResourceError("source-controlled packages are developmentOnly")
        if not isinstance(manifest["candidateUseAuthorized"], bool):
            raise SourceControlledResourceError("resource_manifest.candidateUseAuthorized must be boolean")
        if manifest["acceptedOutputUseAuthorized"] is not False:
            raise SourceControlledResourceError("source-controlled packages cannot authorize accepted output")
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
        if coverage != expected_coverage:
            raise SourceControlledResourceError("coverage_report fields do not match package version 1.0")
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
        expected_digest = _sha256(_canonical_jsonl(validated_observations))
        if coverage["observationSetDigest"] != expected_digest:
            raise SourceControlledResourceError("coverage_report.observationSetDigest is stale")
        object.__setattr__(self, "resource_manifest", manifest)
        object.__setattr__(self, "coverage_report", coverage)
        object.__setattr__(self, "observations", validated_observations)
        object.__setattr__(
            self,
            "source_artifacts",
            {str(key): value for key, value in self.source_artifacts.items()},
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
                source_id=next(
                    (item["id"] for item in self.resource_manifest["sourceArtifacts"] if item["path"] == path),
                    None,
                ),
            )
            for path, payload in sorted(artifacts.items())
        ]
        logical_digest = _sha256(
            _canonical_bytes(
                {
                    "resourceManifest": self.resource_manifest,
                    "coverageReport": self.coverage_report,
                    "observationSetDigest": self.coverage_report["observationSetDigest"],
                    "sourceArtifacts": self.resource_manifest["sourceArtifacts"],
                }
            )
        )
        artifacts["bundle-manifest.json"] = _canonical_bytes(
            {
                "schemaVersion": SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION,
                "packageKind": "sourceControlledResource",
                "resourceManifest": self.resource_manifest["id"],
                "logicalDigest": logical_digest,
                "artifacts": descriptors,
            }
        )
        return dict(sorted(artifacts.items()))

    @property
    def logical_digest(self) -> str:
        """Return the stable package identity recorded by its bundle manifest."""

        manifest = json.loads(self.artifact_bytes()["bundle-manifest.json"])
        return str(manifest["logicalDigest"])

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
    candidate_use_authorized: bool,
    observations: Sequence[Mapping[str, Any]],
    source_artifacts: Mapping[str, bytes],
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
    observation_rows = tuple(_plain_json(value) for value in observations)
    observed = (
        len(observation_rows) + excluded_count + failed_count
        if source_observed_count is None
        else source_observed_count
    )
    manifest_id = (
        "urn:ref:source-controlled-resource:"
        f"{resource_id}:{_sha256(_canonical_bytes(source_descriptors)).removeprefix('sha256:')}"
    )
    manifest = {
        "schemaVersion": SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION,
        "id": manifest_id,
        "resourceId": resource_id,
        "title": title,
        "resourceKind": resource_kind,
        "identityStatus": identity_status,
        "usageCeiling": "developmentOnly",
        "candidateUseAuthorized": candidate_use_authorized,
        "acceptedOutputUseAuthorized": False,
        "conceptIdentityClaimed": False,
        "capturedAt": captured_at,
        "uses": list(uses),
        "observationCount": len(observation_rows),
        "sourceArtifacts": source_descriptors,
    }
    coverage = {
        "schemaVersion": SOURCE_CONTROLLED_RESOURCE_PACKAGE_VERSION,
        "resourceManifest": manifest_id,
        "reportStatus": ("gap" if excluded_count or failed_count or gaps else "pass"),
        "sourceObservedCount": observed,
        "parsedCount": len(observation_rows),
        "packagedCount": len(observation_rows),
        "excludedCount": excluded_count,
        "failedCount": failed_count,
        "observationSetDigest": _sha256(_canonical_jsonl(observation_rows)),
        "gaps": [_plain_json(value) for value in gaps],
    }
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
            bundle_manifest = json.loads(manifest_path.read_bytes())
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
            resource_manifest = json.loads((root / "resource-manifest.json").read_bytes())
            coverage_report = json.loads((root / "coverage-report.json").read_bytes())
            observations = tuple(
                json.loads(line)
                for line in (root / "observations.jsonl").read_text(encoding="utf-8").splitlines()
                if line
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SourceControlledResourceError("resource package JSON is malformed") from error
        source_artifacts = {
            source_id: (root / relative_path).read_bytes() for source_id, relative_path in source_path_by_id.items()
        }
        rebuilt = SourceControlledResourceBundle(
            resource_manifest=resource_manifest,
            coverage_report=coverage_report,
            observations=observations,
            source_artifacts=source_artifacts,
        )
        expected_artifacts = rebuilt.artifact_bytes()
        for relative_path, payload in expected_artifacts.items():
            if (root / relative_path).read_bytes() != payload:
                raise SourceControlledResourceError(f"package artifact is not canonical: {relative_path}")
        if bundle_manifest["logicalDigest"] != rebuilt.logical_digest:
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
            logical_digest=rebuilt.logical_digest,
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
]
