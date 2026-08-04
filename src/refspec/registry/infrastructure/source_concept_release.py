"""Closed source-concept releases shared by all four semantic rings.

Source-controlled resource (SCR) packages preserve exact publisher captures.
They deliberately do not claim concept identity.  This module is the explicit
next step: it selects named observations from one exact SCR capture and either
preserves an explicitly stated publisher concept IRI or mints a RefSpec-issued,
source-scoped IRI from the publisher scheme and a reconciled UUIDv7
``localRecordId``.  Labels never participate in that decision.

The release model is shared by the ``subject``, ``entity``, ``value``, and
``legalIdentity`` rings.  It records semantic kind, identity, exact membership,
source provenance, rights, and lifecycle facts only.  Admission and product
permission belong to separate review and product-policy records and cannot
appear here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
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
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.semantic_foundation import (
    SEMANTIC_RINGS,
    RightsMetadata,
    SemanticFoundationError,
    SemanticRing,
    validate_rights_metadata_records,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    SourceControlledResourceError,
    SourceControlledResourceView,
)
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    require_aware_datetime_text,
    validate_uuid7_urn,
)

SOURCE_CONCEPT_RELEASE_VERSION = "1.0"
SOURCE_CONCEPT_RELEASE_MEDIA_TYPE = "application/vnd.refspec.source-concept-release+json"
SOURCE_CONCEPT_IDENTITY_POLICY_ID = "urn:ref:policy:source-concept-identity:v1"
SOURCE_CONCEPT_ISSUER_IRI = "https://refspec.org/"

_IDENTITY_KINDS = frozenset({"publisherConceptIri", "refspecSourceScoped"})
_LIFECYCLE_EVENT_TYPES = frozenset({"rename", "split", "merge", "retire"})
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_PACKAGE_FILENAMES = frozenset(
    {
        "bundle-manifest.json",
        "concepts.jsonl",
        "lifecycle.jsonl",
        "release-manifest.json",
        "rights.jsonl",
    }
)
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
_IDENTITY_POLICY = {
    "id": SOURCE_CONCEPT_IDENTITY_POLICY_ID,
    "publisherIdentifierKind": "publisherConceptIri",
    "publisherIdentifierEvidence": "qualifiedObservationIdentifier",
    "fallback": "sourceSchemePlusUuid7LocalRecordId",
    "labelIdentity": "prohibited",
}


class SourceConceptReleaseError(ValueError):
    """A source-concept release is incomplete, mutable, or inconsistent."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise SourceConceptReleaseError(str(error)) from error
    return canonical_json_bytes(plain)


def _canonical_nullable_bytes(value: object) -> bytes:
    """Serialize an external review record whose schema permits JSON null.

    REF canonical values intentionally exclude null, while the persisted CRS
    reconciliation schema uses null for absent predecessor and review fields.
    The complete record remains byte-canonical and digest sealed; only the
    stricter REF-value check is inapplicable to this external evidence row.
    """

    try:
        return canonical_json_bytes(_plain(value))
    except (TypeError, ValueError) as error:
        raise SourceConceptReleaseError(str(error)) from error


def _canonical_jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    plain_rows = tuple(cast(Mapping[str, Any], _plain(row)) for row in rows)
    try:
        for row in plain_rows:
            binding.validate_canonical_value(row)
    except (TypeError, ValueError) as error:
        raise SourceConceptReleaseError(str(error)) from error
    return canonical_jsonl_bytes(plain_rows)


def _sha256(payload: bytes) -> str:
    return sha256_digest(payload)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceConceptReleaseError(f"{label} must be non-empty text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise SourceConceptReleaseError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise SourceConceptReleaseError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SourceConceptReleaseError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_datetime(value: object, label: str) -> str:
    text_value = _require_text(value, label)
    try:
        return require_aware_datetime_text(text_value, label=label)
    except SourceIdentityError as error:
        raise SourceConceptReleaseError(str(error)) from error


def _require_unique_iris(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SourceConceptReleaseError(f"{label} must be an array")
    result = [_require_iri(item, f"{label}[{index}]") for index, item in enumerate(value)]
    if (not result and not allow_empty) or len(set(result)) != len(result):
        qualifier = "possibly empty " if allow_empty else "non-empty "
        raise SourceConceptReleaseError(f"{label} must be a {qualifier}unique IRI array")
    return result


def _require_ring(value: object, label: str = "semantic_ring") -> SemanticRing:
    if value not in SEMANTIC_RINGS:
        raise SourceConceptReleaseError(f"{label} must be subject, entity, value, or legalIdentity")
    return cast(SemanticRing, value)


def _forbid_policy_fields(value: Any, *, label: str) -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(set(value) & _FORBIDDEN_POLICY_FIELDS)
        if forbidden:
            raise SourceConceptReleaseError(f"{label} contains admission or permission fields {forbidden!r}")
        for key, child in value.items():
            _forbid_policy_fields(child, label=f"{label}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _forbid_policy_fields(child, label=f"{label}[{index}]")


def _source_scheme(source: SourceControlledResourceBundle) -> dict[str, Any]:
    value = source.resource_manifest.get("sourceScheme")
    if not isinstance(value, Mapping):
        raise SourceConceptReleaseError("source resource manifest must carry one explicit sourceScheme")
    result = cast(dict[str, Any], _plain(value))
    _require_iri(result.get("id"), "source resource manifest sourceScheme.id")
    return result


def _observation_set_digest(source: SourceControlledResourceBundle) -> str:
    return _require_digest(
        source.resource_manifest.get("observationSetDigest"),
        "source resource manifest observationSetDigest",
    )


def _rights_rows(
    values: Sequence[RightsMetadata | Mapping[str, Any]],
    *,
    source: SourceControlledResourceBundle,
    selected_source_artifacts: frozenset[str],
) -> tuple[dict[str, Any], ...]:
    try:
        rights = validate_rights_metadata_records(values)
    except SemanticFoundationError as error:
        raise SourceConceptReleaseError(str(error)) from error
    if not rights:
        raise SourceConceptReleaseError("source-concept release requires explicit rights metadata")
    covered_artifacts = frozenset(value.source_artifact for value in rights)
    if covered_artifacts != selected_source_artifacts:
        missing = sorted(selected_source_artifacts - covered_artifacts)
        extra = sorted(covered_artifacts - selected_source_artifacts)
        raise SourceConceptReleaseError(
            f"rights metadata must exactly cover selected source artifacts; missing {missing!r}, extra {extra!r}"
        )
    for value in rights:
        payload = source.source_artifacts.get(value.source_artifact)
        if payload is None or _sha256(payload) != value.source_digest:
            raise SourceConceptReleaseError("rights metadata sourceDigest differs from the retained source artifact")
    return tuple(value.as_record() for value in rights)


def source_scoped_concept_iri(source_namespace: str, durable_source_key: str) -> str:
    """Mint a stable RefSpec IRI from a source namespace and UUIDv7 key.

    The readable UUID remains in the identifier.  A full SHA-256 namespace
    fingerprint prevents the same UUID carried by two unrelated schemes from
    becoming one concept.  Neither a label nor capture-local observation ID is
    in the preimage.
    """

    namespace = _require_iri(source_namespace, "source_namespace")
    try:
        local_record_id = validate_uuid7_urn(
            durable_source_key,
            label="durable_source_key",
        )
    except SourceIdentityError as error:
        raise SourceConceptReleaseError(str(error)) from error
    namespace_digest = hashlib.sha256(namespace.encode("utf-8")).hexdigest()
    local_uuid = local_record_id.removeprefix("urn:uuid:")
    return f"urn:ref:source-concept:v1:{namespace_digest}:{local_uuid}"


def _selection_policy(value: Mapping[str, Any]) -> dict[str, str]:
    policy = cast(dict[str, Any], _plain(value))
    if set(policy) != {"id", "type"}:
        raise SourceConceptReleaseError("selection_policy must contain exactly id and type")
    identifier = _require_iri(policy.get("id"), "selection_policy.id")
    if policy.get("type") != "explicitObservationSet":
        raise SourceConceptReleaseError("selection_policy.type must be explicitObservationSet")
    return {"id": identifier, "type": "explicitObservationSet"}


def _observation_by_id(
    source: SourceControlledResourceBundle,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, observation in enumerate(source.observations):
        identifier = _require_iri(
            observation.get("id"),
            f"source observations[{index}].id",
        )
        if identifier in result:
            raise SourceConceptReleaseError("source resource repeats an observation identifier")
        result[identifier] = observation
    return result


def _concept_from_observation(
    observation: Mapping[str, Any],
    *,
    semantic_ring: SemanticRing,
    source_scheme_iri: str,
) -> dict[str, Any]:
    observation_id = _require_iri(
        observation.get("id"),
        "selected source observation id",
    )
    if "uses" not in observation:
        raise SourceConceptReleaseError(f"selected source observation {observation_id!r} lacks factual uses")
    uses = observation.get("uses")
    if (
        not isinstance(uses, Sequence)
        or isinstance(uses, (str, bytes))
        or not uses
        or any(not isinstance(value, str) or not value for value in uses)
        or len(set(uses)) != len(uses)
    ):
        raise SourceConceptReleaseError(f"selected source observation {observation_id!r} has invalid uses")
    labels = observation.get("labels")
    if (
        not isinstance(labels, Sequence)
        or isinstance(labels, (str, bytes))
        or not labels
        or any(not isinstance(value, Mapping) for value in labels)
    ):
        raise SourceConceptReleaseError(f"selected source observation {observation_id!r} has invalid labels")

    identifiers = observation.get("identifiers")
    if not isinstance(identifiers, Sequence) or isinstance(identifiers, (str, bytes)):
        raise SourceConceptReleaseError(f"selected source observation {observation_id!r} has invalid identifiers")
    publisher_identifiers = [
        cast(Mapping[str, Any], value)
        for value in identifiers
        if isinstance(value, Mapping) and value.get("kind") == "publisherConceptIri"
    ]
    if len(publisher_identifiers) > 1:
        raise SourceConceptReleaseError(
            f"selected source observation {observation_id!r} repeats publisher concept identity"
        )
    publisher_identifier = None if not publisher_identifiers else publisher_identifiers[0]
    if publisher_identifier is not None:
        publisher_iri = _require_iri(
            publisher_identifier.get("value"),
            f"selected source observation {observation_id!r} publisher concept identifier",
        )
        authority_iri = _require_iri(
            publisher_identifier.get("authorityUri"),
            f"selected source observation {observation_id!r} publisher concept authority",
        )
        if authority_iri != source_scheme_iri:
            raise SourceConceptReleaseError("publisher concept authority differs from the source scheme")
        source_artifact = _require_iri(
            observation.get("sourceArtifact"),
            f"selected source observation {observation_id!r} sourceArtifact",
        )
        if publisher_identifier.get("sourceUri") != source_artifact:
            raise SourceConceptReleaseError("publisher concept identifier is not tied to its retained source artifact")
        _require_text(
            publisher_identifier.get("sourcePath"),
            f"selected source observation {observation_id!r} publisher concept sourcePath",
        )
        _require_digest(
            publisher_identifier.get("sourceDigest"),
            f"selected source observation {observation_id!r} publisher concept sourceDigest",
        )
        concept_iri = _require_iri(
            publisher_iri,
            f"selected source observation {observation_id!r} publisher concept IRI",
        )
        identity_kind = "publisherConceptIri"
        issuer = authority_iri
        local_record_id = None
    else:
        try:
            local_record_id = validate_uuid7_urn(
                cast(str, observation.get("localRecordId")),
                label=(f"selected source observation {observation_id!r} localRecordId"),
            )
        except SourceIdentityError as error:
            raise SourceConceptReleaseError(str(error)) from error
        concept_iri = source_scoped_concept_iri(
            source_scheme_iri,
            local_record_id,
        )
        identity_kind = "refspecSourceScoped"
        issuer = SOURCE_CONCEPT_ISSUER_IRI

    result: dict[str, Any] = {
        "id": concept_iri,
        "type": "SourceScopedConcept",
        "semanticRing": semantic_ring,
        "identityKind": identity_kind,
        "issuer": issuer,
        "sourceScheme": source_scheme_iri,
        "sourceObservation": observation_id,
        "sourceObservationDigest": _sha256(_canonical_bytes(observation)),
    }
    if local_record_id is not None:
        result["localRecordId"] = local_record_id
    if publisher_identifier is not None:
        result["publisherIdentifier"] = _plain(publisher_identifier)
    return result


def _lifecycle_rows(
    values: Sequence[Mapping[str, Any]],
    *,
    semantic_ring: SemanticRing,
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise SourceConceptReleaseError(f"lifecycle_records[{index}] must be an object")
        row = cast(dict[str, Any], _plain(value))
        _forbid_policy_fields(row, label=f"lifecycle_records[{index}]")
        required = {
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
        if set(row) != required:
            raise SourceConceptReleaseError(f"lifecycle_records[{index}] fields do not match the lifecycle schema")
        identifier = _require_iri(
            row.get("id"),
            f"lifecycle_records[{index}].id",
        )
        if identifier in identifiers:
            raise SourceConceptReleaseError("lifecycle_records repeats an id")
        identifiers.add(identifier)
        if row.get("semanticRing") != semantic_ring:
            raise SourceConceptReleaseError("lifecycle record semanticRing differs from its release")
        event_type = row.get("eventType")
        if event_type not in _LIFECYCLE_EVENT_TYPES:
            raise SourceConceptReleaseError(f"lifecycle_records[{index}].eventType is unsupported")
        row["effectiveAt"] = _require_datetime(
            row.get("effectiveAt"),
            f"lifecycle_records[{index}].effectiveAt",
        )
        prior = _require_unique_iris(
            row.get("priorConcepts"),
            f"lifecycle_records[{index}].priorConcepts",
        )
        resulting = _require_unique_iris(
            row.get("resultingConcepts"),
            f"lifecycle_records[{index}].resultingConcepts",
            allow_empty=event_type == "retire",
        )
        valid = (
            event_type == "rename"
            and len(prior) == 1
            and prior == resulting
            or event_type == "split"
            and len(prior) == 1
            and len(resulting) >= 2
            or event_type == "merge"
            and len(prior) >= 2
            and len(resulting) == 1
            or event_type == "retire"
            and len(prior) >= 1
            and not resulting
        )
        if not valid:
            raise SourceConceptReleaseError(
                f"lifecycle_records[{index}] concept cardinality does not match {event_type}"
            )
        row["priorConcepts"] = prior
        row["resultingConcepts"] = resulting
        row["evidence"] = _require_unique_iris(
            row.get("evidence"),
            f"lifecycle_records[{index}].evidence",
        )
        row["reviewedBy"] = _require_iri(
            row.get("reviewedBy"),
            f"lifecycle_records[{index}].reviewedBy",
        )
        row["reviewedAt"] = _require_datetime(
            row.get("reviewedAt"),
            f"lifecycle_records[{index}].reviewedAt",
        )
        rows.append(row)
    return tuple(sorted(rows, key=lambda row: cast(str, row["id"])))


def _reconciliation_record(
    value: Mapping[str, Any] | None,
    *,
    source_manifest_id: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SourceConceptReleaseError("reconciliation_record must be an object")
    row = cast(dict[str, Any], _plain(value))
    if row.get("currentManifestId") != source_manifest_id:
        raise SourceConceptReleaseError("reconciliation_record currentManifestId differs from the source capture")
    if row.get("requiresHumanReview") is not False:
        raise SourceConceptReleaseError("reconciliation_record must resolve human identity review")
    _forbid_policy_fields(row, label="reconciliation_record")
    _canonical_nullable_bytes(row)
    return row


def _source_capture_pin(
    source: SourceControlledResourceBundle,
    *,
    reconciliation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "resourceManifest": _require_iri(
            source.resource_manifest.get("id"),
            "source resource manifest id",
        ),
        "logicalDigest": _require_digest(
            source.logical_digest,
            "source resource logical digest",
        ),
        "observationSetDigest": _observation_set_digest(source),
    }
    if reconciliation is not None:
        result["reconciliationDigest"] = _sha256(_canonical_nullable_bytes(reconciliation))
    return result


def _release_manifest(
    *,
    semantic_ring: SemanticRing,
    source: SourceControlledResourceBundle,
    concepts: Sequence[Mapping[str, Any]],
    selection_policy: Mapping[str, Any],
    rights_metadata: Sequence[Mapping[str, Any]],
    lifecycle_records: Sequence[Mapping[str, Any]],
    reconciliation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    scheme = _source_scheme(source)
    concept_set_digest = _sha256(_canonical_jsonl(concepts))
    rights_set_digest = _sha256(_canonical_jsonl(rights_metadata))
    lifecycle_set_digest = _sha256(_canonical_jsonl(lifecycle_records))
    selected_ids = sorted(str(value["sourceObservation"]) for value in concepts)
    selection_set_digest = _sha256(_canonical_bytes(selected_ids))
    source_capture = _source_capture_pin(
        source,
        reconciliation=reconciliation,
    )
    basis = {
        "type": "SourceConceptRelease",
        "schemaVersion": SOURCE_CONCEPT_RELEASE_VERSION,
        "semanticRing": semantic_ring,
        "issuer": SOURCE_CONCEPT_ISSUER_IRI,
        "sourceScheme": scheme,
        "sourceCapture": source_capture,
        "identityPolicy": _IDENTITY_POLICY,
        "selectionPolicy": dict(selection_policy),
        "selectedObservationSetDigest": selection_set_digest,
        "membershipMode": "completeMembership",
        "conceptCount": len(concepts),
        "conceptSetDigest": concept_set_digest,
        "rightsRecordCount": len(rights_metadata),
        "rightsSetDigest": rights_set_digest,
        "lifecycleRecordCount": len(lifecycle_records),
        "lifecycleSetDigest": lifecycle_set_digest,
    }
    release_digest = _sha256(_canonical_bytes(basis))
    return {
        **basis,
        "id": (f"urn:ref:source-concept-release:{semantic_ring}:{release_digest.removeprefix('sha256:')}"),
        "releaseDigest": release_digest,
    }


def _logical_digest(bundle: SourceConceptReleaseBundle) -> str:
    reconciliation_digest = (
        None
        if bundle.reconciliation_record is None
        else _sha256(_canonical_nullable_bytes(bundle.reconciliation_record))
    )
    basis = {
        "releaseManifest": bundle.release_manifest,
        "sourceCaptureLogicalDigest": bundle.source_bundle.logical_digest,
        "conceptSetDigest": bundle.release_manifest["conceptSetDigest"],
        "rightsSetDigest": bundle.release_manifest["rightsSetDigest"],
        "lifecycleSetDigest": bundle.release_manifest["lifecycleSetDigest"],
    }
    if reconciliation_digest is not None:
        basis["reconciliationDigest"] = reconciliation_digest
    return _sha256(_canonical_bytes(basis))


def _artifact_descriptor(path: str, payload: bytes, *, role: str) -> dict[str, Any]:
    return {
        "path": path,
        "role": role,
        "sha256": _sha256(payload),
        "byteLength": len(payload),
    }


@dataclass(frozen=True, slots=True)
class SourceConceptReleaseBundle:
    """One closed, content-derived release in exactly one semantic ring."""

    release_manifest: Mapping[str, Any]
    concepts: tuple[Mapping[str, Any], ...]
    lifecycle_records: tuple[Mapping[str, Any], ...]
    source_bundle: SourceControlledResourceBundle
    rights_metadata: tuple[Mapping[str, Any], ...]
    reconciliation_record: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_bundle, SourceControlledResourceBundle):
            raise SourceConceptReleaseError("source_bundle must be a verified SourceControlledResourceBundle")
        manifest = cast(dict[str, Any], _plain(self.release_manifest))
        ring = _require_ring(manifest.get("semanticRing"), "release_manifest.semanticRing")
        policy_value = manifest.get("selectionPolicy")
        if not isinstance(policy_value, Mapping):
            raise SourceConceptReleaseError("release_manifest.selectionPolicy must be an object")
        policy = _selection_policy(policy_value)
        reconciliation = _reconciliation_record(
            self.reconciliation_record,
            source_manifest_id=_require_iri(
                self.source_bundle.resource_manifest.get("id"),
                "source resource manifest id",
            ),
        )
        observations = _observation_by_id(self.source_bundle)
        scheme_iri = _require_iri(
            _source_scheme(self.source_bundle).get("id"),
            "source resource manifest sourceScheme.id",
        )

        concept_rows = tuple(
            sorted(
                (cast(dict[str, Any], _plain(value)) for value in self.concepts),
                key=lambda row: str(row.get("id", "")),
            )
        )
        if not concept_rows:
            raise SourceConceptReleaseError("source-concept release must contain at least one concept")
        ids: set[str] = set()
        observation_ids: set[str] = set()
        selected_source_artifacts: set[str] = set()
        for index, row in enumerate(concept_rows):
            if not isinstance(row, Mapping):
                raise SourceConceptReleaseError(f"concepts[{index}] must be an object")
            concept_id = _require_iri(row.get("id"), f"concepts[{index}].id")
            if concept_id in ids:
                raise SourceConceptReleaseError("concept release repeats a concept id")
            ids.add(concept_id)
            observation_id = _require_iri(
                row.get("sourceObservation"),
                f"concepts[{index}].sourceObservation",
            )
            if observation_id in observation_ids:
                raise SourceConceptReleaseError("concept release selects one source observation more than once")
            observation_ids.add(observation_id)
            observation = observations.get(observation_id)
            if observation is None:
                raise SourceConceptReleaseError("concept sourceObservation is outside the exact source capture")
            selected_source_artifacts.add(
                _require_iri(
                    observation.get("sourceArtifact"),
                    f"source observation {observation_id!r} sourceArtifact",
                )
            )
            expected = _concept_from_observation(
                observation,
                semantic_ring=ring,
                source_scheme_iri=scheme_iri,
            )
            if row != expected:
                raise SourceConceptReleaseError("concept identity or source-observation binding is stale")
            if row.get("identityKind") not in _IDENTITY_KINDS:
                raise SourceConceptReleaseError("concept identityKind is unsupported")
            _forbid_policy_fields(row, label=f"concepts[{index}]")

        rights = _rights_rows(
            self.rights_metadata,
            source=self.source_bundle,
            selected_source_artifacts=frozenset(selected_source_artifacts),
        )
        lifecycle = _lifecycle_rows(
            self.lifecycle_records,
            semantic_ring=ring,
        )
        expected_manifest = _release_manifest(
            semantic_ring=ring,
            source=self.source_bundle,
            concepts=concept_rows,
            selection_policy=policy,
            rights_metadata=rights,
            lifecycle_records=lifecycle,
            reconciliation=reconciliation,
        )
        if manifest != expected_manifest:
            raise SourceConceptReleaseError("release_manifest is stale or differs from the release contents")
        _forbid_policy_fields(manifest, label="release_manifest")
        object.__setattr__(
            self,
            "release_manifest",
            cast(Mapping[str, Any], deep_freeze_json(manifest)),
        )
        object.__setattr__(
            self,
            "concepts",
            tuple(cast(Mapping[str, Any], deep_freeze_json(value)) for value in concept_rows),
        )
        object.__setattr__(
            self,
            "rights_metadata",
            tuple(cast(Mapping[str, Any], deep_freeze_json(value)) for value in rights),
        )
        object.__setattr__(
            self,
            "lifecycle_records",
            tuple(cast(Mapping[str, Any], deep_freeze_json(value)) for value in lifecycle),
        )
        object.__setattr__(
            self,
            "reconciliation_record",
            (None if reconciliation is None else cast(Mapping[str, Any], deep_freeze_json(reconciliation))),
        )

    @property
    def release_id(self) -> str:
        return cast(str, self.release_manifest["id"])

    @property
    def release_digest(self) -> str:
        return cast(str, self.release_manifest["releaseDigest"])

    @property
    def semantic_ring(self) -> SemanticRing:
        return cast(SemanticRing, self.release_manifest["semanticRing"])

    @property
    def logical_digest(self) -> str:
        return _logical_digest(self)

    def artifact_bytes(self) -> dict[str, bytes]:
        """Return the complete deterministic release and nested source capture."""

        artifacts: dict[str, bytes] = {
            "release-manifest.json": _canonical_bytes(self.release_manifest),
            "concepts.jsonl": _canonical_jsonl(self.concepts),
            "rights.jsonl": _canonical_jsonl(self.rights_metadata),
            "lifecycle.jsonl": _canonical_jsonl(self.lifecycle_records),
        }
        if self.reconciliation_record is not None:
            artifacts["reconciliation.json"] = _canonical_nullable_bytes(self.reconciliation_record)
        for path, payload in self.source_bundle.artifact_bytes().items():
            artifacts[f"source/{path}"] = payload
        descriptors = [
            _artifact_descriptor(
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
            for path, payload in sorted(artifacts.items())
        ]
        artifacts["bundle-manifest.json"] = _canonical_bytes(
            {
                "schemaVersion": SOURCE_CONCEPT_RELEASE_VERSION,
                "packageKind": "sourceConceptRelease",
                "releaseId": self.release_id,
                "releaseDigest": self.release_digest,
                "logicalDigest": self.logical_digest,
                "artifacts": descriptors,
            }
        )
        return dict(sorted(artifacts.items()))

    @property
    def manifest_digest(self) -> str:
        """Return the external digest of the generated bundle manifest bytes."""

        return _sha256(self.artifact_bytes()["bundle-manifest.json"])

    def write_to(self, path: Path) -> Path:
        """Write the closed release atomically to a new directory."""

        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise SourceConceptReleaseError(f"release destination already exists: {destination}")
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
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return destination


def build_source_concept_release_bundle(
    source: SourceControlledResourceBundle,
    *,
    semantic_ring: SemanticRing,
    selected_observation_ids: Sequence[str],
    selection_policy: Mapping[str, Any],
    rights_metadata: Sequence[RightsMetadata | Mapping[str, Any]],
    lifecycle_records: Sequence[Mapping[str, Any]] = (),
    reconciliation_record: Mapping[str, Any] | None = None,
) -> SourceConceptReleaseBundle:
    """Build one exact release without deriving identity from labels."""

    ring = _require_ring(semantic_ring)
    policy = _selection_policy(selection_policy)
    observations = _observation_by_id(source)
    selected = tuple(selected_observation_ids)
    if (
        not selected
        or any(not isinstance(value, str) or not value for value in selected)
        or len(set(selected)) != len(selected)
    ):
        raise SourceConceptReleaseError("selected_observation_ids must be unique non-empty identifiers")
    missing = sorted(set(selected) - set(observations))
    if missing:
        raise SourceConceptReleaseError(f"selected observations are outside the exact source capture: {missing!r}")
    scheme_iri = _require_iri(
        _source_scheme(source).get("id"),
        "source resource manifest sourceScheme.id",
    )
    concepts = tuple(
        sorted(
            (
                _concept_from_observation(
                    observations[observation_id],
                    semantic_ring=ring,
                    source_scheme_iri=scheme_iri,
                )
                for observation_id in selected
            ),
            key=lambda row: str(row["id"]),
        )
    )
    rights = _rights_rows(
        rights_metadata,
        source=source,
        selected_source_artifacts=frozenset(
            _require_iri(
                observations[observation_id].get("sourceArtifact"),
                f"selected source observation {observation_id!r} sourceArtifact",
            )
            for observation_id in selected
        ),
    )
    lifecycle = _lifecycle_rows(lifecycle_records, semantic_ring=ring)
    reconciliation = _reconciliation_record(
        reconciliation_record,
        source_manifest_id=_require_iri(
            source.resource_manifest.get("id"),
            "source resource manifest id",
        ),
    )
    manifest = _release_manifest(
        semantic_ring=ring,
        source=source,
        concepts=concepts,
        selection_policy=policy,
        rights_metadata=rights,
        lifecycle_records=lifecycle,
        reconciliation=reconciliation,
    )
    return SourceConceptReleaseBundle(
        release_manifest=manifest,
        concepts=concepts,
        lifecycle_records=lifecycle,
        source_bundle=source,
        rights_metadata=rights,
        reconciliation_record=reconciliation,
    )


def _safe_relative_path(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip() or "\\" in value:
        raise SourceConceptReleaseError(f"{label} must use a non-empty relative POSIX path")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in posix.parts)
        or "://" in value
    ):
        raise SourceConceptReleaseError(f"{label} must use a non-traversing relative POSIX path")
    return posix


def _read_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SourceConceptReleaseError(f"{label} must be valid canonical UTF-8 JSON") from error


def _read_jsonl(payload: bytes, label: str) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for index, line in enumerate(payload.splitlines()):
        value = _read_json(line, f"{label}[{index}]")
        if not isinstance(value, Mapping):
            raise SourceConceptReleaseError(f"{label}[{index}] must be an object")
        rows.append(cast(Mapping[str, Any], value))
    if _canonical_jsonl(rows) != payload:
        raise SourceConceptReleaseError(f"{label} bytes are not canonical")
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class SourceConceptReleaseView:
    """One release reopened after its external pin and complete files verify."""

    path: Path
    bundle: SourceConceptReleaseBundle
    manifest_digest: str

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> Self:
        expected = _require_digest(
            expected_manifest_digest,
            "expected source-concept bundle manifest digest",
        )
        requested = Path(manifest_path)
        if requested.is_symlink():
            raise SourceConceptReleaseError("source-concept bundle manifest must not be a symlink")
        candidate = requested / "bundle-manifest.json" if requested.is_dir() else requested
        if candidate.name != "bundle-manifest.json" or not candidate.is_file():
            raise SourceConceptReleaseError("source-concept release requires bundle-manifest.json")
        root = candidate.parent.resolve(strict=True)
        if root.is_symlink() or not root.is_dir():
            raise SourceConceptReleaseError("source-concept release root must be a regular directory")
        manifest_bytes = candidate.read_bytes()
        if _sha256(manifest_bytes) != expected:
            raise SourceConceptReleaseError("source-concept bundle manifest digest differs")
        manifest = _read_json(manifest_bytes, "source-concept bundle manifest")
        if not isinstance(manifest, Mapping) or set(manifest) != {
            "schemaVersion",
            "packageKind",
            "releaseId",
            "releaseDigest",
            "logicalDigest",
            "artifacts",
        }:
            raise SourceConceptReleaseError("source-concept bundle manifest shape is unsupported")
        if (
            manifest.get("schemaVersion") != SOURCE_CONCEPT_RELEASE_VERSION
            or manifest.get("packageKind") != "sourceConceptRelease"
        ):
            raise SourceConceptReleaseError("source-concept bundle manifest version is unsupported")
        _require_iri(manifest.get("releaseId"), "bundle manifest releaseId")
        _require_digest(
            manifest.get("releaseDigest"),
            "bundle manifest releaseDigest",
        )
        _require_digest(
            manifest.get("logicalDigest"),
            "bundle manifest logicalDigest",
        )
        descriptors = manifest.get("artifacts")
        if not isinstance(descriptors, Sequence) or isinstance(
            descriptors,
            (str, bytes),
        ):
            raise SourceConceptReleaseError("source-concept bundle artifacts must be an array")

        actual_paths: set[str] = set()
        for item in root.rglob("*"):
            if item.is_symlink():
                raise SourceConceptReleaseError(f"source-concept release contains a symlink: {item}")
            if item.is_file():
                actual_paths.add(item.relative_to(root).as_posix())
        expected_paths = {"bundle-manifest.json"}
        loaded: dict[str, bytes] = {}
        roles: dict[str, str] = {}
        for index, descriptor in enumerate(descriptors):
            label = f"bundle manifest artifacts[{index}]"
            if not isinstance(descriptor, Mapping) or set(descriptor) != {
                "path",
                "role",
                "sha256",
                "byteLength",
            }:
                raise SourceConceptReleaseError(f"{label} must contain path, role, sha256, and byteLength")
            relative = _safe_relative_path(descriptor.get("path"), f"{label}.path")
            relative_text = relative.as_posix()
            if relative_text in expected_paths:
                raise SourceConceptReleaseError("source-concept bundle repeats an artifact path")
            expected_paths.add(relative_text)
            role = _require_text(descriptor.get("role"), f"{label}.role")
            digest = _require_digest(descriptor.get("sha256"), f"{label}.sha256")
            byte_length = descriptor.get("byteLength")
            if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length < 0:
                raise SourceConceptReleaseError(f"{label}.byteLength must be a non-negative integer")
            artifact_path = root.joinpath(*relative.parts)
            if not artifact_path.is_file() or artifact_path.is_symlink():
                raise SourceConceptReleaseError(f"{label}.path is missing or unsafe")
            payload = artifact_path.read_bytes()
            if len(payload) != byte_length or _sha256(payload) != digest:
                raise SourceConceptReleaseError(f"{label} bytes differ from their descriptor")
            loaded[relative_text] = payload
            roles[relative_text] = role
        if actual_paths != expected_paths:
            raise SourceConceptReleaseError("source-concept release file set differs from its manifest")
        required_roles = {
            "release-manifest.json": "releaseManifest",
            "concepts.jsonl": "concepts",
            "rights.jsonl": "rights",
            "lifecycle.jsonl": "lifecycle",
        }
        if any(roles.get(path) != role for path, role in required_roles.items()):
            raise SourceConceptReleaseError("source-concept release core artifact roles differ")
        source_paths = [path for path, role in roles.items() if role == "sourceCaptureArtifact"]
        if not source_paths or any(not path.startswith("source/") for path in source_paths):
            raise SourceConceptReleaseError("source-concept release lacks its exact nested source capture")
        if any(
            role
            not in {
                "releaseManifest",
                "concepts",
                "rights",
                "lifecycle",
                "reconciliation",
                "sourceCaptureArtifact",
            }
            for role in roles.values()
        ):
            raise SourceConceptReleaseError("source-concept release contains an unsupported artifact role")

        release_manifest = _read_json(
            loaded["release-manifest.json"],
            "source-concept release manifest",
        )
        if not isinstance(release_manifest, Mapping):
            raise SourceConceptReleaseError("source-concept release manifest must be an object")
        if _canonical_bytes(release_manifest) != loaded["release-manifest.json"]:
            raise SourceConceptReleaseError("source-concept release manifest bytes are not canonical")
        concepts = _read_jsonl(loaded["concepts.jsonl"], "source concepts")
        rights = _read_jsonl(loaded["rights.jsonl"], "source concept rights metadata")
        lifecycle = _read_jsonl(
            loaded["lifecycle.jsonl"],
            "source concept lifecycle records",
        )
        reconciliation_payload = loaded.get("reconciliation.json")
        if reconciliation_payload is None:
            reconciliation = None
            if "reconciliation" in roles.values():
                raise SourceConceptReleaseError("source-concept reconciliation role names the wrong path")
        else:
            if roles.get("reconciliation.json") != "reconciliation":
                raise SourceConceptReleaseError("source-concept reconciliation artifact role differs")
            value = _read_json(
                reconciliation_payload,
                "source-concept reconciliation",
            )
            if not isinstance(value, Mapping):
                raise SourceConceptReleaseError("source-concept reconciliation must be an object")
            if _canonical_nullable_bytes(value) != reconciliation_payload:
                raise SourceConceptReleaseError("source-concept reconciliation bytes are not canonical")
            reconciliation = value

        try:
            source_view = SourceControlledResourceView.open(root / "source")
            source = SourceControlledResourceBundle(
                resource_manifest=source_view.resource_manifest,
                coverage_report=source_view.coverage_report,
                observations=source_view.observations,
                source_artifacts=source_view.source_artifacts,
            )
        except SourceControlledResourceError as error:
            raise SourceConceptReleaseError(f"nested source capture is invalid: {error}") from error
        bundle = SourceConceptReleaseBundle(
            release_manifest=release_manifest,
            concepts=concepts,
            lifecycle_records=lifecycle,
            source_bundle=source,
            rights_metadata=rights,
            reconciliation_record=reconciliation,
        )
        rebuilt = bundle.artifact_bytes()
        if set(rebuilt) != expected_paths or any(
            rebuilt[path] != (manifest_bytes if path == "bundle-manifest.json" else loaded[path]) for path in rebuilt
        ):
            raise SourceConceptReleaseError("source-concept release does not reproduce from its packaged facts")
        if (
            manifest.get("releaseId") != bundle.release_id
            or manifest.get("releaseDigest") != bundle.release_digest
            or manifest.get("logicalDigest") != bundle.logical_digest
        ):
            raise SourceConceptReleaseError("source-concept bundle manifest differs from its release")
        if candidate.read_bytes() != manifest_bytes:
            raise SourceConceptReleaseError("source-concept bundle manifest changed while opening")
        return cls(
            path=root,
            bundle=bundle,
            manifest_digest=expected,
        )

    @property
    def release_manifest(self) -> Mapping[str, Any]:
        return self.bundle.release_manifest

    @property
    def concepts(self) -> tuple[Mapping[str, Any], ...]:
        return self.bundle.concepts

    @property
    def rights_metadata(self) -> tuple[Mapping[str, Any], ...]:
        return self.bundle.rights_metadata

    @property
    def lifecycle_records(self) -> tuple[Mapping[str, Any], ...]:
        return self.bundle.lifecycle_records

    @property
    def source_bundle(self) -> SourceControlledResourceBundle:
        return self.bundle.source_bundle

    @property
    def reconciliation_record(self) -> Mapping[str, Any] | None:
        return self.bundle.reconciliation_record

    @property
    def release_id(self) -> str:
        return self.bundle.release_id

    @property
    def release_digest(self) -> str:
        return self.bundle.release_digest

    @property
    def logical_digest(self) -> str:
        return self.bundle.logical_digest

    @property
    def semantic_ring(self) -> SemanticRing:
        return self.bundle.semantic_ring


__all__ = [
    "SOURCE_CONCEPT_IDENTITY_POLICY_ID",
    "SOURCE_CONCEPT_ISSUER_IRI",
    "SOURCE_CONCEPT_RELEASE_MEDIA_TYPE",
    "SOURCE_CONCEPT_RELEASE_VERSION",
    "SemanticRing",
    "SourceConceptReleaseBundle",
    "SourceConceptReleaseError",
    "SourceConceptReleaseView",
    "build_source_concept_release_bundle",
    "source_scoped_concept_iri",
]
