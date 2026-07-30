"""Development-only packages for official LDA controlled code lists.

The Lobbying Disclosure Act (LDA) API publishes General Issue Codes and Filing
Types as exact ``value``/``name`` pairs. This module packages each list as its
own source-controlled resource:

* General Issue Codes remain source-assigned filing evidence.
* Filing Types remain deterministic filing metadata.

Neither package claims concept identity or accepted-output authority. The
source JSON bytes remain in each closed package, and the package reader rebuilds
the expected observations from those exact bytes before exposing a code lookup.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from refspec.registry.controlled_identifier import ControlledIdentifier
from refspec.registry.lda_controlled_codes import (
    LDA_FILING_TYPES_2026_07_30,
    LDA_GENERAL_ISSUE_CODES_2026_07_30,
    LDASnapshotPin,
    ParsedLDAResource,
    ResourceName,
    acquire_lda_constants,
    parse_lda_constants,
)
from refspec.registry.source_controlled_resource import (
    ResourceUse,
    SourceControlledResourceBundle,
    SourceControlledResourceView,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

LDA_CONTROLLED_LIST_PACKAGE_VERSION = "lda-controlled-list-package-v1"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_OBSERVATION_FIELDS = frozenset(
    {
        "id",
        "sourceArtifact",
        "sourcePath",
        "sourceOrdinal",
        "labels",
        "identifiers",
        "eligibleUses",
        "conceptIdentityClaimed",
    }
)
_IDENTIFIER_SOURCE_FIELD = {
    "generalIssueCode": "value",
    "filingTypeCode": "value",
    "publisherRecordId": "id",
    "publisherIdentifier": "identifier",
    "publisherCode": "code",
    "publisherTermURI": "url",
}


class LDAControlledListPackageError(ValueError):
    """An LDA package differs from its exact source or declared use."""


@dataclass(frozen=True, slots=True)
class LDAControlledListPackageSpec:
    """Pinned identity and use of one LDA controlled-list package."""

    resource_name: ResourceName
    resource_id: str
    title: str
    pin: LDASnapshotPin
    code_identifier_kind: str
    uses: tuple[ResourceUse, ...]
    known_gaps: tuple[Mapping[str, str], ...]
    expected_logical_digest: str

    def __post_init__(self) -> None:
        if self.resource_name != self.pin.source.resource_name:
            raise LDAControlledListPackageError("package resource_name differs from its source pin")
        if not self.resource_id or not self.title or not self.code_identifier_kind:
            raise LDAControlledListPackageError("package identity fields must not be empty")
        if not self.uses:
            raise LDAControlledListPackageError("package must declare at least one eligible use")
        if _DIGEST.fullmatch(self.expected_logical_digest) is None:
            raise LDAControlledListPackageError("expected_logical_digest must be a SHA-256 digest")


_NO_PUBLISHER_RELEASE_GAP = MappingProxyType(
    {
        "kind": "publisherReleaseUnavailable",
        "reason": (
            "The LDA constants endpoint publishes no code-list release date or "
            "revision; the package uses retrieval time and exact source digest."
        ),
    }
)
_NO_FILING_STATUS_LIST_GAP = MappingProxyType(
    {
        "kind": "standaloneFilingStatusListUnavailable",
        "reason": (
            "The official API publishes no standalone filing-status list; "
            "status-like wording remains part of Filing Type labels."
        ),
    }
)
_NO_FILING_PERIOD_LIST_GAP = MappingProxyType(
    {
        "kind": "standaloneFilingPeriodListUnavailable",
        "reason": (
            "The official API publishes filing-period enum values in OpenAPI "
            "but no independent constants endpoint or display-label list."
        ),
    }
)

# These package digests are external pins over the deterministic logical
# package. They are updated only when the exact source or LDA packaging rules
# change.
LDA_GENERAL_ISSUE_CODE_PACKAGE = LDAControlledListPackageSpec(
    resource_name="generalIssueCodes",
    resource_id="lda-general-issue-codes-2026-07-30",
    title="LDA General Issue Codes, captured 2026-07-30",
    pin=LDA_GENERAL_ISSUE_CODES_2026_07_30,
    code_identifier_kind="generalIssueCode",
    uses=("sourceAssignedEvidence",),
    known_gaps=(_NO_PUBLISHER_RELEASE_GAP,),
    expected_logical_digest="sha256:3f3ec1e17f5503be8767d6e51142521ceba314ba555907438f8487ca1dfc04df",
)
LDA_FILING_TYPE_PACKAGE = LDAControlledListPackageSpec(
    resource_name="filingTypes",
    resource_id="lda-filing-types-2026-07-30",
    title="LDA Filing Types, captured 2026-07-30",
    pin=LDA_FILING_TYPES_2026_07_30,
    code_identifier_kind="filingTypeCode",
    uses=("deterministicMetadata",),
    known_gaps=(
        _NO_PUBLISHER_RELEASE_GAP,
        _NO_FILING_STATUS_LIST_GAP,
        _NO_FILING_PERIOD_LIST_GAP,
    ),
    expected_logical_digest="sha256:27d784d14004228b024fa82962e91df7daadb4edaf3237125e420194dafd3588",
)
LDA_CONTROLLED_LIST_PACKAGES = (
    LDA_GENERAL_ISSUE_CODE_PACKAGE,
    LDA_FILING_TYPE_PACKAGE,
)
_PACKAGE_BY_RESOURCE_ID = MappingProxyType({spec.resource_id: spec for spec in LDA_CONTROLLED_LIST_PACKAGES})


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _parse_exact_source(
    spec: LDAControlledListPackageSpec,
    payload: bytes,
) -> ParsedLDAResource:
    with tempfile.TemporaryDirectory(prefix="refspec-lda-package-") as temporary:
        root = Path(temporary)
        source_path = root / spec.pin.source.filename
        source_path.write_bytes(payload)
        acquired = acquire_lda_constants(
            spec.pin,
            root / "store",
            source_path=source_path,
        )
        return parse_lda_constants(acquired)


def _identifier_payload(
    *,
    identifier: ControlledIdentifier,
    source_path: str,
) -> dict[str, Any]:
    if identifier.kind not in _IDENTIFIER_SOURCE_FIELD:
        raise LDAControlledListPackageError(f"unsupported LDA identifier kind {identifier.kind!r}")
    result: dict[str, Any] = {
        "value": identifier.value,
        "kind": identifier.kind,
        "authorityUri": identifier.authority_uri,
        "sourceUri": identifier.source_uri,
        "sourcePath": (f"{source_path}.{_IDENTIFIER_SOURCE_FIELD[identifier.kind]}"),
        "observedAt": identifier.observed_at,
        "sourceDigest": identifier.source_digest,
    }
    if identifier.effective_at is not None:
        result["effectiveFrom"] = identifier.effective_at
    return result


def _observation_id(
    *,
    spec: LDAControlledListPackageSpec,
    source_path: str,
    identifiers: Sequence[Mapping[str, Any]],
) -> str:
    identity = {
        "packageVersion": LDA_CONTROLLED_LIST_PACKAGE_VERSION,
        "resourceId": spec.resource_id,
        "sourceArtifact": spec.pin.source.source_url,
        "sourcePath": source_path,
        "identifiers": [
            {
                "value": identifier["value"],
                "kind": identifier["kind"],
                "authorityUri": identifier["authorityUri"],
            }
            for identifier in identifiers
        ],
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{spec.resource_id}:{digest}"


def _observations(
    spec: LDAControlledListPackageSpec,
    resource: ParsedLDAResource,
) -> tuple[Mapping[str, Any], ...]:
    if resource.source != spec.pin.source:
        raise LDAControlledListPackageError("parsed resource differs from its package source")
    if resource.source_sha256 != spec.pin.expected_sha256:
        raise LDAControlledListPackageError("parsed resource digest differs from its package source")
    if len(resource.codes) != spec.pin.source.expected_count:
        raise LDAControlledListPackageError("parsed resource count differs from its package source")

    result: list[Mapping[str, Any]] = []
    for ordinal, code in enumerate(resource.codes):
        if code.resource_name != spec.resource_name or code.use not in spec.uses or code.is_general_subject_concept:
            raise LDAControlledListPackageError(f"{spec.resource_name} row {ordinal} has an incompatible type or use")
        source_path = f"$[{ordinal}]"
        identifiers = tuple(
            _identifier_payload(
                identifier=identifier,
                source_path=source_path,
            )
            for identifier in code.identifiers
        )
        code_identifiers = [identifier for identifier in identifiers if identifier["kind"] == spec.code_identifier_kind]
        if len(code_identifiers) != 1:
            raise LDAControlledListPackageError(
                f"{spec.resource_name} row {ordinal} must retain exactly one {spec.code_identifier_kind}"
            )
        result.append(
            {
                "id": _observation_id(
                    spec=spec,
                    source_path=source_path,
                    identifiers=identifiers,
                ),
                "sourceArtifact": spec.pin.source.source_url,
                "sourcePath": source_path,
                # This ordinal is a source locator only. Publisher identity is
                # preserved in identifiers and never derived from row order.
                "sourceOrdinal": ordinal,
                "labels": [
                    {
                        "value": code.publisher_label,
                        "language": "en",
                        "role": "preferred",
                    }
                ],
                "identifiers": list(identifiers),
                "eligibleUses": list(spec.uses),
                "conceptIdentityClaimed": False,
            }
        )
    return tuple(result)


def build_lda_controlled_list_package(
    spec: LDAControlledListPackageSpec,
    source_path: Path,
) -> SourceControlledResourceBundle:
    """Build one exact, development-only LDA controlled-list package."""

    path = Path(source_path)
    if path.is_symlink() or not path.is_file():
        raise LDAControlledListPackageError(f"LDA controlled-list source is not a regular file: {path}")
    payload = path.read_bytes()
    resource = _parse_exact_source(spec, payload)
    return build_source_controlled_resource_bundle(
        resource_id=spec.resource_id,
        title=spec.title,
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=spec.uses,
        captured_at=spec.pin.retrieved_at,
        candidate_use_authorized=True,
        observations=_observations(spec, resource),
        source_artifacts={spec.pin.source.source_url: payload},
        source_observed_count=spec.pin.source.expected_count,
        gaps=spec.known_gaps,
    )


def build_lda_general_issue_code_package(
    source_path: Path,
) -> SourceControlledResourceBundle:
    """Package all exact LDA General Issue Codes as source evidence."""

    return build_lda_controlled_list_package(
        LDA_GENERAL_ISSUE_CODE_PACKAGE,
        source_path,
    )


def build_lda_filing_type_package(
    source_path: Path,
) -> SourceControlledResourceBundle:
    """Package all exact LDA Filing Types as deterministic metadata."""

    return build_lda_controlled_list_package(
        LDA_FILING_TYPE_PACKAGE,
        source_path,
    )


@dataclass(frozen=True, slots=True)
class LDAControlledListView:
    """An LDA package reopened against its external pin and source rules."""

    package: SourceControlledResourceView
    spec: LDAControlledListPackageSpec
    observations_by_code: Mapping[str, Mapping[str, Any]]

    @classmethod
    def open(cls, path: Path) -> LDAControlledListView:
        """Open one known LDA package and rebuild it from retained source bytes."""

        package = SourceControlledResourceView.open(path)
        resource_id = package.resource_manifest.get("resourceId")
        if not isinstance(resource_id, str) or resource_id not in _PACKAGE_BY_RESOURCE_ID:
            raise LDAControlledListPackageError(f"unknown LDA controlled-list resource {resource_id!r}")
        spec = _PACKAGE_BY_RESOURCE_ID[resource_id]
        if package.logical_digest != spec.expected_logical_digest:
            raise LDAControlledListPackageError(f"{resource_id} logical digest differs from its external pin")
        source_bytes = package.source_artifact_bytes(spec.pin.source.source_url)
        if len(source_bytes) != spec.pin.expected_byte_length or _sha256(source_bytes) != spec.pin.expected_sha256:
            raise LDAControlledListPackageError(f"{resource_id} retained source differs from its dated pin")
        rebuilt = build_source_controlled_resource_bundle(
            resource_id=spec.resource_id,
            title=spec.title,
            resource_kind="controlledCodeList",
            identity_status="publisherIdentifiersPreserved",
            uses=spec.uses,
            captured_at=spec.pin.retrieved_at,
            candidate_use_authorized=True,
            observations=_observations(
                spec,
                _parse_exact_source(spec, source_bytes),
            ),
            source_artifacts={spec.pin.source.source_url: source_bytes},
            source_observed_count=spec.pin.source.expected_count,
            gaps=spec.known_gaps,
        )
        if rebuilt.artifact_bytes() != {
            relative_path: (Path(path) / relative_path).read_bytes() for relative_path in rebuilt.artifact_bytes()
        }:
            raise LDAControlledListPackageError(f"{resource_id} package differs from its deterministic LDA build")

        by_code: dict[str, Mapping[str, Any]] = {}
        for ordinal, observation in enumerate(package.observations):
            if set(observation) != _OBSERVATION_FIELDS:
                raise LDAControlledListPackageError(f"{resource_id} observation {ordinal} has unexpected fields")
            matches = [
                identifier
                for identifier in observation["identifiers"]
                if identifier["kind"] == spec.code_identifier_kind
            ]
            if len(matches) != 1:
                raise LDAControlledListPackageError(f"{resource_id} observation {ordinal} lacks one publisher code")
            code = matches[0]["value"]
            if code in by_code:
                raise LDAControlledListPackageError(f"{resource_id} repeats publisher code {code!r}")
            by_code[code] = observation
        return cls(
            package=package,
            spec=spec,
            observations_by_code=MappingProxyType(by_code),
        )

    def lookup_code(self, value: str) -> Mapping[str, Any] | None:
        """Return one exact source observation by publisher code."""

        return self.observations_by_code.get(value)


__all__ = [
    "LDA_CONTROLLED_LIST_PACKAGES",
    "LDA_CONTROLLED_LIST_PACKAGE_VERSION",
    "LDA_FILING_TYPE_PACKAGE",
    "LDA_GENERAL_ISSUE_CODE_PACKAGE",
    "LDAControlledListPackageError",
    "LDAControlledListPackageSpec",
    "LDAControlledListView",
    "build_lda_controlled_list_package",
    "build_lda_filing_type_package",
    "build_lda_general_issue_code_package",
]
