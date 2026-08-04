"""Immutable decisions to publish an exact atlas or atlas projection.

The decision is downstream of generation.  It binds one verified atlas scope
to one exact result and records who approved that result for a named bench or
product scope.  Keeping the decision out of the atlas inputs avoids a digest
cycle while still making publication an explicit, reviewable act.
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

from typing_extensions import Self

from refspec import binding
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
    AtlasScopeError,
    PinnedVocabularyAtlasScope,
    validate_atlas_scope_record,
)
from .model import (
    VocabularyAtlasAsset,
    VocabularyAtlasError,
)
from .projection import VocabularyAtlasProjection

PUBLICATION_DECISION_TYPE = "VocabularyAtlasPublicationDecision"
PUBLICATION_DECISION_VERSION = "1.0"

PublicationArtifactKind = Literal["atlas", "projection"]
PublicationPolicyKind = Literal[
    "selectionPolicy",
    "qualificationPolicy",
    "projectionPolicy",
]
PublicationExceptionKind = Literal["developmentOnly", "rights"]

_ARTIFACT_KINDS = frozenset({"atlas", "projection"})
_POLICY_KINDS = frozenset({"selectionPolicy", "qualificationPolicy", "projectionPolicy"})
_EXCEPTION_KINDS = frozenset({"developmentOnly", "rights"})
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")

_SCOPE_PIN_FIELDS = frozenset({"role", "id", "contentDigest", "fileDigest"})
_INDEX_PIN_FIELDS = frozenset({"role", "id", "indexDigest", "fileDigest"})
_INTENDED_SCOPE_FIELDS = frozenset({"name", "kind"})
_POLICY_PIN_FIELDS = frozenset({"role", "id", "version", "contentDigest"})
_EXCEPTION_FIELDS = frozenset({"kind", "appliesTo", "statement"})
_ATLAS_RESULT_FIELDS = frozenset({"role", "id", "manifestDigest", "distributionDigest"})
_PROJECTION_RESULT_FIELDS = _ATLAS_RESULT_FIELDS | {"parent"}
_PARENT_PIN_FIELDS = frozenset({"assetId", "manifestDigest", "distributionDigest"})
_SUPERSESSION_FIELDS = frozenset({"id", "recordDigest"})
_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "artifactKind",
        "scope",
        "planningIndex",
        "intendedScope",
        "policies",
        "exceptions",
        "decisionActor",
        "decidedAt",
        "result",
        "supersedes",
    }
)
_RECORD_FIELDS = _BASIS_FIELDS | {"id", "recordDigest"}


class PublicationDecisionError(ValueError):
    """A publication decision is incomplete, stale, or internally inconsistent."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise PublicationDecisionError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicationDecisionError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _require_array(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PublicationDecisionError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise PublicationDecisionError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise PublicationDecisionError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise PublicationDecisionError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise PublicationDecisionError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PublicationDecisionError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_datetime(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        return require_aware_datetime_text(text, label=label)
    except SourceIdentityError as error:
        raise PublicationDecisionError(str(error)) from error


def _normalize_scope_pin(value: object) -> dict[str, str]:
    label = "publication decision scope"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _SCOPE_PIN_FIELDS, label)
    if row.get("role") != "VocabularyAtlasScope":
        raise PublicationDecisionError("publication decision scope.role must be VocabularyAtlasScope")
    return {
        "role": "VocabularyAtlasScope",
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "contentDigest": _require_digest(row.get("contentDigest"), f"{label}.contentDigest"),
        "fileDigest": _require_digest(row.get("fileDigest"), f"{label}.fileDigest"),
    }


def _normalize_index_pin(value: object) -> dict[str, str]:
    label = "publication decision planningIndex"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _INDEX_PIN_FIELDS, label)
    if row.get("role") != "AtlasIndex":
        raise PublicationDecisionError("publication decision planningIndex.role must be AtlasIndex")
    return {
        "role": "AtlasIndex",
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "indexDigest": _require_digest(row.get("indexDigest"), f"{label}.indexDigest"),
        "fileDigest": _require_digest(row.get("fileDigest"), f"{label}.fileDigest"),
    }


def _normalize_intended_scope(value: object) -> dict[str, str]:
    label = "publication decision intendedScope"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _INTENDED_SCOPE_FIELDS, label)
    kind = row.get("kind")
    if kind not in {"bench", "product"}:
        raise PublicationDecisionError("publication decision intendedScope.kind must be bench or product")
    return {
        "name": _require_iri(row.get("name"), f"{label}.name"),
        "kind": cast(str, kind),
    }


def _normalize_policy_pins(value: object) -> list[dict[str, str]]:
    rows = _require_array(value, "publication decision policies")
    result: list[dict[str, str]] = []
    keys: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(rows):
        label = f"publication decision policies[{index}]"
        row = _require_mapping(raw, label)
        _require_exact_fields(row, _POLICY_PIN_FIELDS, label)
        role = row.get("role")
        if not isinstance(role, str) or role not in _POLICY_KINDS:
            raise PublicationDecisionError(f"{label}.role is unsupported")
        normalized = {
            "role": role,
            "id": _require_iri(row.get("id"), f"{label}.id"),
            "version": _require_text(row.get("version"), f"{label}.version"),
            "contentDigest": _require_digest(row.get("contentDigest"), f"{label}.contentDigest"),
        }
        key = (normalized["role"], normalized["id"], normalized["version"])
        if key in keys:
            raise PublicationDecisionError("publication decision repeats a policy pin")
        keys.add(key)
        result.append(normalized)
    result.sort(key=lambda row: (row["role"], row["id"], row["version"]))
    return result


def _normalize_exceptions(value: object) -> list[dict[str, str]]:
    rows = _require_array(value, "publication decision exceptions")
    result: list[dict[str, str]] = []
    for index, raw in enumerate(rows):
        label = f"publication decision exceptions[{index}]"
        row = _require_mapping(raw, label)
        _require_exact_fields(row, _EXCEPTION_FIELDS, label)
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in _EXCEPTION_KINDS:
            raise PublicationDecisionError(f"{label}.kind is unsupported")
        result.append(
            {
                "kind": kind,
                "appliesTo": _require_iri(row.get("appliesTo"), f"{label}.appliesTo"),
                "statement": _require_text(row.get("statement"), f"{label}.statement"),
            }
        )
    result.sort(key=lambda row: (row["kind"], row["appliesTo"], row["statement"]))
    if len({_canonical_bytes(row) for row in result}) != len(result):
        raise PublicationDecisionError("publication decision repeats an exception")
    return result


def _normalize_parent_pin(value: object, *, label: str) -> dict[str, str]:
    row = _require_mapping(value, label)
    _require_exact_fields(row, _PARENT_PIN_FIELDS, label)
    return {
        "assetId": _require_iri(row.get("assetId"), f"{label}.assetId"),
        "manifestDigest": _require_digest(row.get("manifestDigest"), f"{label}.manifestDigest"),
        "distributionDigest": _require_digest(row.get("distributionDigest"), f"{label}.distributionDigest"),
    }


def _normalize_result(
    value: object,
    *,
    artifact_kind: PublicationArtifactKind,
) -> dict[str, Any]:
    label = "publication decision result"
    row = _require_mapping(value, label)
    if artifact_kind == "atlas":
        _require_exact_fields(row, _ATLAS_RESULT_FIELDS, label)
        if row.get("role") != "VocabularyAtlas":
            raise PublicationDecisionError("an atlas publication result.role must be VocabularyAtlas")
        return {
            "role": "VocabularyAtlas",
            "id": _require_iri(row.get("id"), f"{label}.id"),
            "manifestDigest": _require_digest(row.get("manifestDigest"), f"{label}.manifestDigest"),
            "distributionDigest": _require_digest(row.get("distributionDigest"), f"{label}.distributionDigest"),
        }
    _require_exact_fields(row, _PROJECTION_RESULT_FIELDS, label)
    if row.get("role") != "VocabularyAtlasProjection":
        raise PublicationDecisionError("a projection publication result.role must be VocabularyAtlasProjection")
    parent = _normalize_parent_pin(row.get("parent"), label=f"{label}.parent")
    identifier = _require_iri(row.get("id"), f"{label}.id")
    if identifier == parent["assetId"]:
        raise PublicationDecisionError("a projection publication result must differ from its parent")
    return {
        "role": "VocabularyAtlasProjection",
        "id": identifier,
        "manifestDigest": _require_digest(row.get("manifestDigest"), f"{label}.manifestDigest"),
        "distributionDigest": _require_digest(row.get("distributionDigest"), f"{label}.distributionDigest"),
        "parent": parent,
    }


def _normalize_supersedes(value: object) -> list[dict[str, str]]:
    rows = _require_array(value, "publication decision supersedes")
    result: list[dict[str, str]] = []
    ids: set[str] = set()
    for index, raw in enumerate(rows):
        label = f"publication decision supersedes[{index}]"
        row = _require_mapping(raw, label)
        _require_exact_fields(row, _SUPERSESSION_FIELDS, label)
        identifier = _require_iri(row.get("id"), f"{label}.id")
        if identifier in ids:
            raise PublicationDecisionError("publication decision repeats a superseded decision")
        ids.add(identifier)
        result.append(
            {
                "id": identifier,
                "recordDigest": _require_digest(row.get("recordDigest"), f"{label}.recordDigest"),
            }
        )
    result.sort(key=lambda row: row["id"])
    return result


def _normalize_basis(value: Mapping[str, Any]) -> dict[str, Any]:
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, _BASIS_FIELDS, "publication decision basis")
    if row.get("type") != PUBLICATION_DECISION_TYPE:
        raise PublicationDecisionError("publication decision type is unsupported")
    if row.get("schemaVersion") != PUBLICATION_DECISION_VERSION:
        raise PublicationDecisionError("publication decision schemaVersion is unsupported")
    artifact_kind = row.get("artifactKind")
    if not isinstance(artifact_kind, str) or artifact_kind not in _ARTIFACT_KINDS:
        raise PublicationDecisionError("publication decision artifactKind must be atlas or projection")
    normalized_kind = cast(PublicationArtifactKind, artifact_kind)
    policies = _normalize_policy_pins(row.get("policies"))
    policy_roles = {policy["role"] for policy in policies}
    missing_base_policies = {
        "selectionPolicy",
        "qualificationPolicy",
    } - policy_roles
    if missing_base_policies:
        raise PublicationDecisionError("a publication decision requires selectionPolicy and qualificationPolicy pins")
    projection_policies = [policy for policy in policies if policy["role"] == "projectionPolicy"]
    if normalized_kind == "atlas" and projection_policies:
        raise PublicationDecisionError("an atlas publication decision cannot name a projection policy")
    if normalized_kind == "projection" and len(projection_policies) != 1:
        raise PublicationDecisionError("a projection publication decision requires exactly one projection policy")
    return {
        "type": PUBLICATION_DECISION_TYPE,
        "schemaVersion": PUBLICATION_DECISION_VERSION,
        "artifactKind": normalized_kind,
        "scope": _normalize_scope_pin(row.get("scope")),
        "planningIndex": _normalize_index_pin(row.get("planningIndex")),
        "intendedScope": _normalize_intended_scope(row.get("intendedScope")),
        "policies": policies,
        "exceptions": _normalize_exceptions(row.get("exceptions")),
        "decisionActor": _require_iri(row.get("decisionActor"), "publication decision decisionActor"),
        "decidedAt": _require_datetime(row.get("decidedAt"), "publication decision decidedAt"),
        "result": _normalize_result(row.get("result"), artifact_kind=normalized_kind),
        "supersedes": _normalize_supersedes(row.get("supersedes")),
    }


def _normalize_record(value: object) -> dict[str, Any]:
    row = _require_mapping(value, "publication decision")
    _require_exact_fields(row, _RECORD_FIELDS, "publication decision")
    basis = _normalize_basis({field: row[field] for field in _BASIS_FIELDS})
    record_digest = sha256_digest(_canonical_bytes(basis))
    expected = {
        **basis,
        "id": ("urn:ref:vocabulary-atlas-publication-decision:" + record_digest.removeprefix("sha256:")),
        "recordDigest": record_digest,
    }
    if _plain(row) != expected:
        raise PublicationDecisionError("publication decision identity, inputs, or canonical order differs")
    if any(item["id"] == expected["id"] for item in basis["supersedes"]):
        raise PublicationDecisionError("publication decision cannot supersede itself")
    return expected


@dataclass(frozen=True, slots=True)
class VocabularyAtlasPublicationDecision:
    """One content-derived decision to publish one exact generated result."""

    record: Mapping[str, Any]

    def __post_init__(self) -> None:
        normalized = _normalize_record(self.record)
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(normalized)),
        )

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> Self:
        return cls(record=value)

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def record_digest(self) -> str:
        return cast(str, self.record["recordDigest"])

    @property
    def artifact_kind(self) -> PublicationArtifactKind:
        return cast(PublicationArtifactKind, self.record["artifactKind"])

    @property
    def reference(self) -> Mapping[str, str]:
        return {"id": self.identifier, "recordDigest": self.record_digest}

    def as_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self.record))

    def artifact_bytes(self) -> bytes:
        return _canonical_bytes(self.as_record())

    def validate_for_scope(self, scope: PinnedVocabularyAtlasScope) -> None:
        self._validate_scope_facts(*_scope_facts(scope))

    def validate_result(self, result: Mapping[str, Any]) -> None:
        normalized = _normalize_result(result, artifact_kind=self.artifact_kind)
        if _plain(self.record["result"]) != normalized:
            raise PublicationDecisionError("publication decision names another exact result")

    def validate_distribution(
        self,
        distribution: VocabularyAtlasAsset | VocabularyAtlasProjection,
        *,
        parent: VocabularyAtlasAsset | None = None,
    ) -> None:
        """Validate this decision against one concrete verified distribution.

        Selection and qualification policies remain external decision inputs;
        Atlas 2.0 does not embed them.  A projection does embed its selector,
        so that one policy pin is checked against the exact projection bytes.
        """

        if isinstance(distribution, VocabularyAtlasAsset):
            if self.artifact_kind != "atlas":
                raise PublicationDecisionError("a projection publication decision cannot validate an atlas")
            if parent is not None:
                raise PublicationDecisionError("an atlas distribution does not accept a projection parent")
            scope, planning_index, intended_scope = _distribution_scope_facts(distribution)
            self._validate_scope_facts(
                scope,
                planning_index,
                intended_scope,
            )
            self.validate_result(_atlas_distribution_result(distribution))
            return

        if not isinstance(distribution, VocabularyAtlasProjection):
            raise PublicationDecisionError("publication decision requires a verified atlas or projection")
        if self.artifact_kind != "projection":
            raise PublicationDecisionError("an atlas publication decision cannot validate a projection")
        if not isinstance(parent, VocabularyAtlasAsset):
            raise PublicationDecisionError("a projection publication decision requires its verified atlas parent")
        _require_verified_projection(distribution)
        expected_parent = _atlas_parent_pin(parent)
        if _plain(distribution.parent_pin) != expected_parent:
            raise PublicationDecisionError("atlas projection parent pin differs from the verified parent")
        scope, planning_index, intended_scope = _distribution_scope_facts(parent)
        self._validate_scope_facts(scope, planning_index, intended_scope)
        expected_policy = _projection_policy_pin(distribution)
        decision_policy = next(
            policy
            for policy in cast(
                Sequence[Mapping[str, Any]],
                self.record["policies"],
            )
            if policy["role"] == "projectionPolicy"
        )
        if _plain(decision_policy) != expected_policy:
            raise PublicationDecisionError("publication decision projection policy differs from the distribution")
        self.validate_result(
            _projection_distribution_result(
                distribution,
                parent_pin=expected_parent,
            )
        )

    def _validate_scope_facts(
        self,
        scope: Mapping[str, Any],
        planning_index: Mapping[str, Any],
        intended_scope: Mapping[str, Any],
    ) -> None:
        if _plain(self.record["scope"]) != _plain(scope):
            raise PublicationDecisionError("publication decision names another exact atlas scope")
        if _plain(self.record["planningIndex"]) != _plain(planning_index):
            raise PublicationDecisionError("publication decision planning index differs from its exact scope")
        if _plain(self.record["intendedScope"]) != _plain(intended_scope):
            raise PublicationDecisionError("publication decision intended scope differs from its exact scope")

    def write_to(self, path: Path | str) -> Path:
        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise PublicationDecisionError(f"publication decision destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}-", dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(self.artifact_bytes())
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return destination


def _require_verified_asset(asset: VocabularyAtlasAsset) -> None:
    try:
        asset._require_verified()
    except VocabularyAtlasError as error:
        raise PublicationDecisionError(str(error)) from error


def _require_verified_projection(projection: VocabularyAtlasProjection) -> None:
    try:
        projection._require_verified()
    except VocabularyAtlasError as error:
        raise PublicationDecisionError(str(error)) from error


def _atlas_parent_pin(asset: VocabularyAtlasAsset) -> dict[str, str]:
    _require_verified_asset(asset)
    return {
        "assetId": _require_iri(
            asset.manifest.get("id"),
            "verified atlas manifest id",
        ),
        "manifestDigest": asset.manifest_digest,
        "distributionDigest": asset.output_digest,
    }


def _atlas_distribution_result(asset: VocabularyAtlasAsset) -> dict[str, str]:
    parent = _atlas_parent_pin(asset)
    return {
        "role": "VocabularyAtlas",
        "id": parent["assetId"],
        "manifestDigest": parent["manifestDigest"],
        "distributionDigest": parent["distributionDigest"],
    }


def _projection_distribution_result(
    projection: VocabularyAtlasProjection,
    *,
    parent_pin: Mapping[str, str],
) -> dict[str, Any]:
    _require_verified_projection(projection)
    return {
        "role": "VocabularyAtlasProjection",
        "id": _require_iri(
            projection.manifest.get("id"),
            "verified atlas projection manifest id",
        ),
        "manifestDigest": projection.manifest_digest,
        "distributionDigest": projection.output_digest,
        "parent": _plain(parent_pin),
    }


def _projection_policy_pin(
    projection: VocabularyAtlasProjection,
) -> dict[str, str]:
    _require_verified_projection(projection)
    policy = _require_mapping(
        projection.manifest.get("projectionPolicy"),
        "verified atlas projection policy",
    )
    return {
        "role": "projectionPolicy",
        "id": _require_iri(
            policy.get("id"),
            "verified atlas projection policy.id",
        ),
        "version": _require_text(
            policy.get("version"),
            "verified atlas projection policy.version",
        ),
        "contentDigest": sha256_digest(_canonical_bytes(policy)),
    }


def _distribution_scope_facts(
    asset: VocabularyAtlasAsset,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    _require_verified_asset(asset)
    try:
        raw_scope = json.loads(
            asset.scope_payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
        scope_record = validate_atlas_scope_record(raw_scope)
    except (
        AtlasScopeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise PublicationDecisionError("verified atlas scope bytes are invalid") from error
    descriptor = _require_mapping(
        asset.manifest.get("scope"),
        "verified atlas scope descriptor",
    )
    scope_pin = _normalize_scope_pin(
        {
            "role": descriptor.get("role"),
            "id": descriptor.get("id"),
            "contentDigest": descriptor.get("contentDigest"),
            "fileDigest": descriptor.get("fileDigest"),
        }
    )
    if (
        scope_pin["id"] != scope_record["id"]
        or scope_pin["contentDigest"] != scope_record["contentDigest"]
        or scope_pin["fileDigest"] != sha256_digest(asset.scope_payload)
    ):
        raise PublicationDecisionError("verified atlas scope descriptor differs from its scope bytes")
    planning_index = _normalize_index_pin(scope_record.get("atlasIndex"))
    intended_scope = _normalize_intended_scope(
        {
            "name": scope_record.get("scopeName"),
            "kind": scope_record.get("scopeKind"),
        }
    )
    return scope_pin, planning_index, intended_scope


def _scope_facts(
    scope: PinnedVocabularyAtlasScope,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    if not isinstance(scope, PinnedVocabularyAtlasScope):
        raise PublicationDecisionError("publication decision requires a path-backed exact atlas scope")
    try:
        verified = scope.verified_scope()
    except AtlasScopeError as error:
        raise PublicationDecisionError(str(error)) from error
    record = verified.as_record()
    return (
        {
            "role": "VocabularyAtlasScope",
            "id": verified.identifier,
            "contentDigest": verified.content_digest,
            "fileDigest": scope.file_digest,
        },
        cast(dict[str, str], _plain(record["atlasIndex"])),
        {"name": verified.scope_name, "kind": verified.scope_kind},
    )


def build_vocabulary_atlas_publication_decision(
    scope: PinnedVocabularyAtlasScope,
    *,
    artifact_kind: PublicationArtifactKind,
    policies: Sequence[Mapping[str, Any]],
    decision_actor: str,
    decided_at: str,
    result: Mapping[str, Any],
    exceptions: Sequence[Mapping[str, Any]] = (),
    supersedes: Sequence[Mapping[str, Any]] = (),
) -> VocabularyAtlasPublicationDecision:
    """Seal an approval after generation, without changing the generated id."""

    if not isinstance(artifact_kind, str) or artifact_kind not in _ARTIFACT_KINDS:
        raise PublicationDecisionError("artifact_kind must be atlas or projection")
    normalized_kind = cast(PublicationArtifactKind, artifact_kind)
    scope_pin, planning_index, intended_scope = _scope_facts(scope)
    basis = _normalize_basis(
        {
            "type": PUBLICATION_DECISION_TYPE,
            "schemaVersion": PUBLICATION_DECISION_VERSION,
            "artifactKind": normalized_kind,
            "scope": scope_pin,
            "planningIndex": planning_index,
            "intendedScope": intended_scope,
            "policies": list(policies),
            "exceptions": list(exceptions),
            "decisionActor": decision_actor,
            "decidedAt": decided_at,
            "result": dict(result),
            "supersedes": list(supersedes),
        }
    )
    record_digest = sha256_digest(_canonical_bytes(basis))
    return VocabularyAtlasPublicationDecision(
        {
            **basis,
            "id": ("urn:ref:vocabulary-atlas-publication-decision:" + record_digest.removeprefix("sha256:")),
            "recordDigest": record_digest,
        }
    )


def read_vocabulary_atlas_publication_decision(
    path: Path | str,
    *,
    expected_file_digest: str,
) -> VocabularyAtlasPublicationDecision:
    """Open one exact canonical decision file without trusting its filename."""

    digest = _require_digest(expected_file_digest, "publication decision file digest")
    candidate = Path(path)
    if candidate.is_symlink():
        raise PublicationDecisionError("publication decision must not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise PublicationDecisionError("publication decision does not exist") from error
    if not resolved.is_file():
        raise PublicationDecisionError("publication decision must be a regular file")
    payload = resolved.read_bytes()
    if sha256_digest(payload) != digest:
        raise PublicationDecisionError("publication decision file digest differs")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise PublicationDecisionError("publication decision must be valid canonical UTF-8 JSON") from error
    if not isinstance(value, Mapping) or _canonical_bytes(value) != payload:
        raise PublicationDecisionError("publication decision bytes are not canonical")
    decision = VocabularyAtlasPublicationDecision.from_record(value)
    if resolved.read_bytes() != payload:
        raise PublicationDecisionError("publication decision changed while opening")
    return decision


__all__ = [
    "PUBLICATION_DECISION_TYPE",
    "PUBLICATION_DECISION_VERSION",
    "PublicationArtifactKind",
    "PublicationDecisionError",
    "PublicationExceptionKind",
    "PublicationPolicyKind",
    "VocabularyAtlasPublicationDecision",
    "build_vocabulary_atlas_publication_decision",
    "read_vocabulary_atlas_publication_decision",
]
