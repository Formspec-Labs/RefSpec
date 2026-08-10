"""Closed source-concept releases shared by all four semantic rings.

Source-controlled resource (SCR) packages preserve exact publisher captures.
They deliberately do not claim concept identity.  This module is the explicit
next step: it selects named observations from one exact SCR capture and either
preserves an explicitly stated publisher concept IRI or mints a RefSpec-issued,
source-scoped IRI from the publisher scheme and a reconciled UUIDv7
``localRecordId``.  Labels never participate in that decision.

The release model is shared by the ``subject``, ``entity``, ``value``, and
``legalIdentity`` rings.  It records semantic kind, identity, exact membership,
source provenance, rights, concept lifecycle facts, and exact publisher-release
supersession. Release supersession stays separate from concept lifecycle and
from Atlas publication decisions. Admission and product permission belong to
separate review and product-policy records and cannot appear here.
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
SOURCE_CONCEPT_RELEASE_LINEAGE_VERSION = "1.1"
SOURCE_CONCEPT_RELEASE_MEDIA_TYPE = "application/vnd.refspec.source-concept-release+json"
SOURCE_CONCEPT_IDENTITY_POLICY_ID = "urn:ref:policy:source-concept-identity:v1"
SOURCE_CONCEPT_ISSUER_IRI = "https://refspec.org/"
SOURCE_RELEASE_SUPERSESSION_TYPE = "SourceReleaseSupersession"
SOURCE_RELEASE_SUPERSESSION_VERSION = "1.1"

_IDENTITY_KINDS = frozenset({"publisherConceptIri", "refspecSourceScoped"})
_SUPPORTED_SOURCE_CONCEPT_RELEASE_VERSIONS = frozenset(
    {
        SOURCE_CONCEPT_RELEASE_VERSION,
        SOURCE_CONCEPT_RELEASE_LINEAGE_VERSION,
    }
)
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
_SUPERSEDED_RELEASE_FIELDS = {
    "releaseId",
    "semanticRing",
    "sourceScheme",
    "manifestDigest",
    "releaseDigest",
    "logicalDigest",
}
_SOURCE_RELEASE_SUPERSESSION_BASIS_FIELDS = {
    "type",
    "schemaVersion",
    "successorBasisDigest",
    "successorLineageDigest",
    "supersededRelease",
}
_SOURCE_RELEASE_SUPERSESSION_FIELDS = (
    _SOURCE_RELEASE_SUPERSESSION_BASIS_FIELDS | {"id", "contentDigest"}
)


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


def _selection_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = cast(dict[str, Any], _plain(value))
    identifier = _require_iri(policy.get("id"), "selection_policy.id")
    policy_type = policy.get("type")
    if policy_type == "explicitObservationSet":
        if set(policy) != {"id", "type"}:
            raise SourceConceptReleaseError(
                "an explicitObservationSet selection_policy must contain exactly id and type"
            )
        return {"id": identifier, "type": "explicitObservationSet"}
    if policy_type != "policyFrontier":
        raise SourceConceptReleaseError("selection_policy.type must be explicitObservationSet or policyFrontier")
    if set(policy) != {"id", "type", "selectionReceipt"}:
        raise SourceConceptReleaseError(
            "a policyFrontier selection_policy must contain exactly id, type, and selectionReceipt"
        )
    pin_value = policy.get("selectionReceipt")
    if not isinstance(pin_value, Mapping) or set(pin_value) != {
        "role",
        "id",
        "scopeKind",
        "contentDigest",
        "fileDigest",
    }:
        raise SourceConceptReleaseError(
            "selection_policy.selectionReceipt must contain role, id, scopeKind, contentDigest, and fileDigest"
        )
    if pin_value.get("role") != "SelectionReceipt":
        raise SourceConceptReleaseError("selection_policy.selectionReceipt.role must be SelectionReceipt")
    if pin_value.get("scopeKind") != "policyFrontier":
        raise SourceConceptReleaseError("selection_policy.selectionReceipt.scopeKind must be policyFrontier")
    return {
        "id": identifier,
        "type": "policyFrontier",
        "selectionReceipt": {
            "role": "SelectionReceipt",
            "id": _require_iri(
                pin_value.get("id"),
                "selection_policy.selectionReceipt.id",
            ),
            "scopeKind": "policyFrontier",
            "contentDigest": _require_digest(
                pin_value.get("contentDigest"),
                "selection_policy.selectionReceipt.contentDigest",
            ),
            "fileDigest": _require_digest(
                pin_value.get("fileDigest"),
                "selection_policy.selectionReceipt.fileDigest",
            ),
        },
    }


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


def _receipt_source_capture_facts(
    source: SourceControlledResourceBundle,
) -> dict[str, Any]:
    """Return every receipt source-capture fact reconstructible from one SCR.

    ``distributionCoverage`` is intentionally absent.  It is a reader/compiler
    finding in the selection receipt; SCR 2.0 does not carry that field.  Every
    byte- and count-derived capture fact is nevertheless checked here.
    """

    artifacts = source.artifact_bytes()
    coverage = source.coverage_report
    gaps = coverage.get("gaps")
    if not isinstance(gaps, Sequence) or isinstance(gaps, (str, bytes)):
        raise SourceConceptReleaseError("source coverage gaps must be an array")
    return {
        "resourceManifest": _require_iri(
            source.resource_manifest.get("id"),
            "source resource manifest id",
        ),
        "logicalDigest": _require_digest(
            source.logical_digest,
            "source resource logical digest",
        ),
        "bundleManifestDigest": _sha256(artifacts["bundle-manifest.json"]),
        "observationSetDigest": _observation_set_digest(source),
        "coverageReportDigest": _sha256(artifacts["coverage-report.json"]),
        "coverageStatus": coverage.get("reportStatus"),
        "sourceObservedCount": coverage.get("sourceObservedCount"),
        "parsedObservationCount": coverage.get("parsedCount"),
        "packagedObservationCount": coverage.get("packagedCount"),
        "excludedObservationCount": coverage.get("excludedCount"),
        "failedObservationCount": coverage.get("failedCount"),
        "gapCount": len(gaps),
    }


def _validated_frontier_receipt(
    value: Mapping[str, Any] | None,
    *,
    policy: Mapping[str, Any],
    semantic_ring: SemanticRing,
    source: SourceControlledResourceBundle,
    concepts: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    policy_type = policy.get("type")
    if policy_type == "explicitObservationSet":
        if value is not None:
            raise SourceConceptReleaseError("an explicitObservationSet release must not contain a selection receipt")
        return None
    if semantic_ring != "subject":
        raise SourceConceptReleaseError("a policyFrontier source-concept release must use the subject ring")
    if not isinstance(value, Mapping):
        raise SourceConceptReleaseError("a policyFrontier release requires one exact selection receipt")
    record = cast(dict[str, Any], _plain(value))
    raw_selected = record.get("selectedConcepts")
    if not isinstance(raw_selected, Sequence) or isinstance(raw_selected, (str, bytes)):
        raise SourceConceptReleaseError("selection receipt selectedConcepts must be an array")
    selected_observations: set[str] = set()
    for index, raw_concept in enumerate(raw_selected):
        if not isinstance(raw_concept, Mapping):
            raise SourceConceptReleaseError(f"selection receipt selectedConcepts[{index}] must be an object")
        selected_observations.add(
            _require_iri(
                raw_concept.get("sourceObservationId"),
                f"selection receipt selectedConcepts[{index}].sourceObservationId",
            )
        )
    observations = _observation_by_id(source)
    missing_observations = sorted(selected_observations - set(observations))
    if missing_observations:
        raise SourceConceptReleaseError(
            f"selection receipt selects observations outside the exact source capture: {missing_observations!r}"
        )
    unselected_observations = tuple(sorted(set(observations) - selected_observations))

    raw_dispositions = record.get("broaderEdgeDispositions")
    if not isinstance(raw_dispositions, Sequence) or isinstance(raw_dispositions, (str, bytes)):
        raise SourceConceptReleaseError("selection receipt broaderEdgeDispositions must be an array")
    # The pass-1 receipt pins the reader's exact source-edge set.  SCR 2.0 has
    # no standard broader-edge field, so reopen can prove the sealed set and
    # its dispositions but cannot independently re-derive publisher edges.
    source_broader_edges: list[dict[str, Any]] = []
    for index, raw_edge in enumerate(raw_dispositions):
        if not isinstance(raw_edge, Mapping):
            raise SourceConceptReleaseError(f"selection receipt broaderEdgeDispositions[{index}] must be an object")
        source_broader_edges.append(
            {
                "narrowerConcept": raw_edge.get("narrowerConcept"),
                "broaderConcept": raw_edge.get("broaderConcept"),
            }
        )

    try:
        from refspec.atlas.frontier import SelectionReceipt, SelectionReceiptError
    except ImportError as error:
        raise SourceConceptReleaseError("selection receipt implementation is unavailable") from error
    try:
        receipt = SelectionReceipt.from_record(
            record,
            source_broader_edges=source_broader_edges,
            unselected_observation_ids=unselected_observations,
        )
    except SelectionReceiptError as error:
        raise SourceConceptReleaseError(f"selection receipt is invalid: {error}") from error
    if receipt.scope_kind != "policyFrontier":
        raise SourceConceptReleaseError("selection receipt scopeKind must be policyFrontier")

    receipt_record = receipt.as_record()
    receipt_capture = cast(Mapping[str, Any], receipt_record["sourceCapture"])
    if receipt_capture.get("distributionCoverage") != "complete":
        raise SourceConceptReleaseError("a policyFrontier receipt must report complete publisher-distribution coverage")
    for field, actual in _receipt_source_capture_facts(source).items():
        if receipt_capture.get(field) != actual:
            raise SourceConceptReleaseError(
                f"selection receipt sourceCapture.{field} differs from the exact nested source capture"
            )

    receipt_pairs = {
        (str(row["conceptId"]), str(row["sourceObservationId"]))
        for row in cast(Sequence[Mapping[str, Any]], receipt_record["selectedConcepts"])
    }
    release_pairs = {(str(row["id"]), str(row["sourceObservation"])) for row in concepts}
    if receipt_pairs != release_pairs:
        raise SourceConceptReleaseError(
            "selection receipt concept and source-observation pairs differ from the release members"
        )

    pin = cast(Mapping[str, Any], policy["selectionReceipt"])
    expected_pin = {
        "role": "SelectionReceipt",
        "id": receipt.identifier,
        "scopeKind": "policyFrontier",
        "contentDigest": receipt.content_digest,
        "fileDigest": _sha256(receipt.artifact_bytes()),
    }
    if dict(pin) != expected_pin:
        raise SourceConceptReleaseError("selection receipt pin differs from the embedded canonical receipt")
    if policy.get("id") != cast(Mapping[str, Any], receipt_record["selectionPolicy"]).get("id"):
        raise SourceConceptReleaseError("release selection policy id differs from the receipt selection policy")
    return receipt_record


def _frontier_scope_accounting(receipt: Mapping[str, Any]) -> dict[str, Any]:
    source = cast(Mapping[str, Any], receipt["sourceCapture"])
    counts = cast(Mapping[str, Any], receipt["counts"])
    return {
        "distributionCoverage": source["distributionCoverage"],
        "sourceCoverageStatus": source["coverageStatus"],
        "sourceObservedCount": source["sourceObservedCount"],
        "sourceParsedObservationCount": source["parsedObservationCount"],
        "sourcePackagedObservationCount": source["packagedObservationCount"],
        "sourceExcludedObservationCount": source["excludedObservationCount"],
        "sourceFailedObservationCount": source["failedObservationCount"],
        "sourceGapCount": source["gapCount"],
        "selectedObservationCount": counts["selectedConcepts"],
        "unselectedObservationCount": counts["unselectedObservations"],
        "sourceBroaderEdgeCount": counts["broaderEdges"],
        "includedBroaderEdgeCount": counts["includedBroaderEdges"],
        "externalReferenceBroaderEdgeCount": counts["externalReferenceBroaderEdges"],
        "omittedBroaderEdgeCount": counts["omittedBroaderEdges"],
    }


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


def _normalize_superseded_release_pin(
    value: object,
    *,
    label: str,
    semantic_ring: SemanticRing,
    source_scheme: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise SourceConceptReleaseError(f"{label} must be an object")
    row = cast(dict[str, Any], _plain(value))
    if set(row) != _SUPERSEDED_RELEASE_FIELDS:
        raise SourceConceptReleaseError(f"{label} fields differ from the exact source-release pin")
    prior_ring = _require_ring(row.get("semanticRing"), f"{label}.semanticRing")
    if prior_ring != semantic_ring:
        raise SourceConceptReleaseError("a source release can supersede only a release in the same semantic ring")
    prior_scheme = _require_iri(row.get("sourceScheme"), f"{label}.sourceScheme")
    if prior_scheme != source_scheme:
        raise SourceConceptReleaseError("a source release can supersede only a release from the same source scheme")
    release_digest = _require_digest(
        row.get("releaseDigest"),
        f"{label}.releaseDigest",
    )
    release_id = _require_iri(row.get("releaseId"), f"{label}.releaseId")
    expected_release_id = (
        f"urn:ref:source-concept-release:{prior_ring}:"
        f"{release_digest.removeprefix('sha256:')}"
    )
    if release_id != expected_release_id:
        raise SourceConceptReleaseError(f"{label}.releaseId differs from releaseDigest")
    return {
        "releaseId": release_id,
        "semanticRing": prior_ring,
        "sourceScheme": prior_scheme,
        "manifestDigest": _require_digest(
            row.get("manifestDigest"),
            f"{label}.manifestDigest",
        ),
        "releaseDigest": release_digest,
        "logicalDigest": _require_digest(
            row.get("logicalDigest"),
            f"{label}.logicalDigest",
        ),
    }


def _source_release_supersession_records(
    superseded_release_pins: Sequence[Mapping[str, Any]],
    *,
    semantic_ring: SemanticRing,
    source_scheme: str,
    successor_basis_digest: str,
) -> tuple[dict[str, Any], ...]:
    successor_digest = _require_digest(
        successor_basis_digest,
        "source release supersession successorBasisDigest",
    )
    pins = [
        _normalize_superseded_release_pin(
            value,
            label=f"superseded_release_pins[{index}]",
            semantic_ring=semantic_ring,
            source_scheme=source_scheme,
        )
        for index, value in enumerate(superseded_release_pins)
    ]
    release_ids = [value["releaseId"] for value in pins]
    if len(release_ids) != len(set(release_ids)):
        raise SourceConceptReleaseError("source release supersession repeats a superseded release")
    canonical_pins = sorted(pins, key=lambda value: value["releaseId"])
    lineage_digest = _sha256(_canonical_bytes(canonical_pins))
    result: list[dict[str, Any]] = []
    for pin in canonical_pins:
        basis = {
            "type": SOURCE_RELEASE_SUPERSESSION_TYPE,
            "schemaVersion": SOURCE_RELEASE_SUPERSESSION_VERSION,
            "successorBasisDigest": successor_digest,
            "successorLineageDigest": lineage_digest,
            "supersededRelease": pin,
        }
        content_digest = _sha256(_canonical_bytes(basis))
        result.append(
            {
                **basis,
                "id": (
                    "urn:ref:source-release-supersession:"
                    + content_digest.removeprefix("sha256:")
                ),
                "contentDigest": content_digest,
            }
        )
    return tuple(result)


def _superseded_release_pins_from_records(
    value: object,
    *,
    semantic_ring: SemanticRing,
    source_scheme: str,
) -> tuple[dict[str, str], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise SourceConceptReleaseError("sourceReleaseSupersessions must be a non-empty array when present")
    pins: list[dict[str, str]] = []
    records: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    lineage_digests: set[str] = set()
    for index, raw in enumerate(value):
        label = f"sourceReleaseSupersessions[{index}]"
        if not isinstance(raw, Mapping):
            raise SourceConceptReleaseError(f"{label} must be an object")
        row = cast(dict[str, Any], _plain(raw))
        if set(row) != _SOURCE_RELEASE_SUPERSESSION_FIELDS:
            raise SourceConceptReleaseError(f"{label} fields differ from the supersession schema")
        if (
            row.get("type") != SOURCE_RELEASE_SUPERSESSION_TYPE
            or row.get("schemaVersion") != SOURCE_RELEASE_SUPERSESSION_VERSION
        ):
            raise SourceConceptReleaseError(f"{label} type or version is unsupported")
        successor_basis_digest = _require_digest(
            row.get("successorBasisDigest"),
            f"{label}.successorBasisDigest",
        )
        successor_lineage_digest = _require_digest(
            row.get("successorLineageDigest"),
            f"{label}.successorLineageDigest",
        )
        pin = _normalize_superseded_release_pin(
            row.get("supersededRelease"),
            label=f"{label}.supersededRelease",
            semantic_ring=semantic_ring,
            source_scheme=source_scheme,
        )
        basis = {
            "type": SOURCE_RELEASE_SUPERSESSION_TYPE,
            "schemaVersion": SOURCE_RELEASE_SUPERSESSION_VERSION,
            "successorBasisDigest": successor_basis_digest,
            "successorLineageDigest": successor_lineage_digest,
            "supersededRelease": pin,
        }
        content_digest = _sha256(_canonical_bytes(basis))
        expected = {
            **basis,
            "id": (
                "urn:ref:source-release-supersession:"
                + content_digest.removeprefix("sha256:")
            ),
            "contentDigest": content_digest,
        }
        if row != expected:
            raise SourceConceptReleaseError(f"{label} content identity is stale")
        identifier = cast(str, expected["id"])
        if identifier in identifiers:
            raise SourceConceptReleaseError("sourceReleaseSupersessions repeats an id")
        identifiers.add(identifier)
        lineage_digests.add(successor_lineage_digest)
        pins.append(pin)
        records.append(expected)
    if records != sorted(
        records,
        key=lambda row: cast(str, cast(Mapping[str, Any], row["supersededRelease"])["releaseId"]),
    ):
        raise SourceConceptReleaseError(
            "sourceReleaseSupersessions must use canonical superseded-release order"
        )
    if len({pin["releaseId"] for pin in pins}) != len(pins):
        raise SourceConceptReleaseError("sourceReleaseSupersessions repeats a superseded release")
    expected_lineage_digest = _sha256(_canonical_bytes(pins))
    if lineage_digests != {expected_lineage_digest}:
        raise SourceConceptReleaseError(
            "sourceReleaseSupersessions do not bind the complete canonical predecessor set"
        )
    return tuple(pins)


def normalize_source_release_supersessions(
    value: object,
    *,
    semantic_ring: SemanticRing,
    source_scheme: str,
    successor_basis_digest: str,
) -> tuple[dict[str, Any], ...]:
    """Verify exact release-level supersession records from canonical facts."""

    pins = _superseded_release_pins_from_records(
        value,
        semantic_ring=semantic_ring,
        source_scheme=source_scheme,
    )
    expected = _source_release_supersession_records(
        pins,
        semantic_ring=semantic_ring,
        source_scheme=source_scheme,
        successor_basis_digest=successor_basis_digest,
    )
    if _plain(value) != list(expected):
        raise SourceConceptReleaseError(
            "sourceReleaseSupersessions differ from the successor release basis"
        )
    return expected


def _release_manifest(
    *,
    semantic_ring: SemanticRing,
    source: SourceControlledResourceBundle,
    concepts: Sequence[Mapping[str, Any]],
    selection_policy: Mapping[str, Any],
    rights_metadata: Sequence[Mapping[str, Any]],
    lifecycle_records: Sequence[Mapping[str, Any]],
    reconciliation: Mapping[str, Any] | None,
    selection_receipt: Mapping[str, Any] | None,
    superseded_release_pins: Sequence[Mapping[str, Any]],
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
        "schemaVersion": (
            SOURCE_CONCEPT_RELEASE_LINEAGE_VERSION
            if superseded_release_pins
            else SOURCE_CONCEPT_RELEASE_VERSION
        ),
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
    if selection_receipt is not None:
        basis["scopeKind"] = "policyFrontier"
        basis["scopeAccounting"] = _frontier_scope_accounting(selection_receipt)
    if superseded_release_pins:
        basis["sourceReleaseSupersessions"] = list(
            _source_release_supersession_records(
                superseded_release_pins,
                semantic_ring=semantic_ring,
                source_scheme=_require_iri(
                    scheme.get("id"),
                    "source release sourceScheme.id",
                ),
                successor_basis_digest=_sha256(_canonical_bytes(basis)),
            )
        )
    release_digest = _sha256(_canonical_bytes(basis))
    result = {
        **basis,
        "id": (f"urn:ref:source-concept-release:{semantic_ring}:{release_digest.removeprefix('sha256:')}"),
        "releaseDigest": release_digest,
    }
    if any(
        record["supersededRelease"]["releaseId"] == result["id"]
        for record in cast(
            Sequence[Mapping[str, Any]],
            result.get("sourceReleaseSupersessions", ()),
        )
    ):
        raise SourceConceptReleaseError("a source release cannot supersede itself")
    return result


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
    selection_receipt: Mapping[str, Any] | None = None

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
        superseded_release_pins = (
            _superseded_release_pins_from_records(
                manifest["sourceReleaseSupersessions"],
                semantic_ring=ring,
                source_scheme=scheme_iri,
            )
            if "sourceReleaseSupersessions" in manifest
            else ()
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
        selection_receipt = _validated_frontier_receipt(
            self.selection_receipt,
            policy=policy,
            semantic_ring=ring,
            source=self.source_bundle,
            concepts=concept_rows,
        )
        expected_manifest = _release_manifest(
            semantic_ring=ring,
            source=self.source_bundle,
            concepts=concept_rows,
            selection_policy=policy,
            rights_metadata=rights,
            lifecycle_records=lifecycle,
            reconciliation=reconciliation,
            selection_receipt=selection_receipt,
            superseded_release_pins=superseded_release_pins,
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
        object.__setattr__(
            self,
            "selection_receipt",
            (None if selection_receipt is None else cast(Mapping[str, Any], deep_freeze_json(selection_receipt))),
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
    def source_release_supersessions(self) -> tuple[Mapping[str, Any], ...]:
        """Return exact predecessor pins as distinct release-level relations."""

        value = self.release_manifest.get("sourceReleaseSupersessions", ())
        return cast(tuple[Mapping[str, Any], ...], value)

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
        if self.selection_receipt is not None:
            artifacts["selection-receipt.json"] = _canonical_bytes(self.selection_receipt)
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
                    else "selectionReceipt"
                    if path == "selection-receipt.json"
                    else "sourceCaptureArtifact"
                ),
            )
            for path, payload in sorted(artifacts.items())
        ]
        artifacts["bundle-manifest.json"] = _canonical_bytes(
            {
                "schemaVersion": self.release_manifest["schemaVersion"],
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


def _verified_superseded_release_pin(
    value: SourceConceptReleaseBundle | SourceConceptReleaseView,
) -> dict[str, str]:
    if isinstance(value, SourceConceptReleaseBundle):
        release: SourceConceptReleaseBundle | SourceConceptReleaseView = value
    elif isinstance(value, SourceConceptReleaseView):
        release = SourceConceptReleaseView.open(
            value.path,
            expected_manifest_digest=value.manifest_digest,
        )
    else:
        raise SourceConceptReleaseError(
            "supersedes must contain verified SourceConceptRelease bundles or views"
        )
    source_scheme = _require_iri(
        release.release_manifest.get("sourceScheme", {}).get("id")
        if isinstance(release.release_manifest.get("sourceScheme"), Mapping)
        else None,
        "superseded source release sourceScheme.id",
    )
    return {
        "releaseId": _require_iri(
            release.release_id,
            "superseded source release releaseId",
        ),
        "semanticRing": release.semantic_ring,
        "sourceScheme": source_scheme,
        "manifestDigest": _require_digest(
            release.manifest_digest,
            "superseded source release manifestDigest",
        ),
        "releaseDigest": _require_digest(
            release.release_digest,
            "superseded source release releaseDigest",
        ),
        "logicalDigest": _require_digest(
            release.logical_digest,
            "superseded source release logicalDigest",
        ),
    }


def build_source_concept_release_bundle(
    source: SourceControlledResourceBundle,
    *,
    semantic_ring: SemanticRing,
    selected_observation_ids: Sequence[str],
    selection_policy: Mapping[str, Any],
    rights_metadata: Sequence[RightsMetadata | Mapping[str, Any]],
    lifecycle_records: Sequence[Mapping[str, Any]] = (),
    reconciliation_record: Mapping[str, Any] | None = None,
    selection_receipt: Mapping[str, Any] | None = None,
    supersedes: Sequence[
        SourceConceptReleaseBundle | SourceConceptReleaseView
    ] = (),
) -> SourceConceptReleaseBundle:
    """Build one exact release without deriving identity from labels.

    ``supersedes`` names exact earlier publisher releases. It is separate from
    Atlas publication decisions and from lifecycle events about concepts.
    """

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
    receipt = _validated_frontier_receipt(
        selection_receipt,
        policy=policy,
        semantic_ring=ring,
        source=source,
        concepts=concepts,
    )
    superseded_release_pins = tuple(
        _verified_superseded_release_pin(value)
        for value in supersedes
    )
    manifest = _release_manifest(
        semantic_ring=ring,
        source=source,
        concepts=concepts,
        selection_policy=policy,
        rights_metadata=rights,
        lifecycle_records=lifecycle,
        reconciliation=reconciliation,
        selection_receipt=receipt,
        superseded_release_pins=superseded_release_pins,
    )
    return SourceConceptReleaseBundle(
        release_manifest=manifest,
        concepts=concepts,
        lifecycle_records=lifecycle,
        source_bundle=source,
        rights_metadata=rights,
        reconciliation_record=reconciliation,
        selection_receipt=receipt,
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
            manifest.get("schemaVersion")
            not in _SUPPORTED_SOURCE_CONCEPT_RELEASE_VERSIONS
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
                "selectionReceipt",
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
        if release_manifest.get("schemaVersion") != manifest.get("schemaVersion"):
            raise SourceConceptReleaseError(
                "source-concept release and bundle manifest versions differ"
            )
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

        receipt_payload = loaded.get("selection-receipt.json")
        if receipt_payload is None:
            selection_receipt = None
            if "selectionReceipt" in roles.values():
                raise SourceConceptReleaseError("selection receipt artifact role names the wrong path")
        else:
            if roles.get("selection-receipt.json") != "selectionReceipt":
                raise SourceConceptReleaseError("selection receipt artifact role differs")
            value = _read_json(
                receipt_payload,
                "source-concept selection receipt",
            )
            if not isinstance(value, Mapping):
                raise SourceConceptReleaseError("source-concept selection receipt must be an object")
            if _canonical_bytes(value) != receipt_payload:
                raise SourceConceptReleaseError("source-concept selection receipt bytes are not canonical")
            selection_receipt = value

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
            selection_receipt=selection_receipt,
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
    def selection_receipt(self) -> Mapping[str, Any] | None:
        return self.bundle.selection_receipt

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

    @property
    def source_release_supersessions(self) -> tuple[Mapping[str, Any], ...]:
        return self.bundle.source_release_supersessions


__all__ = [
    "SOURCE_CONCEPT_IDENTITY_POLICY_ID",
    "SOURCE_CONCEPT_ISSUER_IRI",
    "SOURCE_CONCEPT_RELEASE_LINEAGE_VERSION",
    "SOURCE_CONCEPT_RELEASE_MEDIA_TYPE",
    "SOURCE_CONCEPT_RELEASE_VERSION",
    "SOURCE_RELEASE_SUPERSESSION_TYPE",
    "SOURCE_RELEASE_SUPERSESSION_VERSION",
    "SemanticRing",
    "SourceConceptReleaseBundle",
    "SourceConceptReleaseError",
    "SourceConceptReleaseView",
    "build_source_concept_release_bundle",
    "normalize_source_release_supersessions",
    "source_scoped_concept_iri",
]
