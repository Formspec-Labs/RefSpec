"""Read-only access to one immutable RefSpec managed-release bundle.

The bundle manifest is a closed JSON object with these fields:

``bundleVersion``
    The literal ``"1.0"``.
``publicationReleaseManifest``
    One relative-path and SHA-256 artifact descriptor.
``refRecords``
    One or more descriptors for individual linked REF record files.
``rulespecGraph``
    The exact JSON-LD release graph descriptor.
``rulespecGraphId``
    The external identifier for that default-graph document. The JSON-LD
    document itself has no top-level ``@id``.
``rulespecDependencyManifest``
    The exact Rulespec version, revisions, generated artifacts, and validator
    identity used by the release gate.
``combinedValidationReceipt``
    A content-digested receipt from the independent REF, Rulespec, and
    cross-boundary gates.
``normalizedTables``
    Exactly one descriptor named ``concept_labels``, ``concept_relations``,
    and ``concept_event_participants``.
``indexedExpressionCorpus``
    A JSON Lines artifact descriptor plus its exact logical snapshot,
    record count, corpus schema version, and canonical expression-identity
    digest. File order is physical; the logical digest is order-independent.
``sourceArtifacts``
    An optional mapping from each successful exact-byte
    ``Capture.storageReference`` artifact IRI to the verified source bytes'
    relative path, SHA-256 digest, and byte length.

Every descriptor is ``{"path": <relative path>, "sha256": "sha256:..."}``.
The reader verifies all bytes before parsing them and retains only immutable
in-memory values. Physical lookup indexes are consumer state and cannot be
packaged as part of a managed release.

This reader does not run, replace, or claim Rulespec conformance. It consumes
an already validated release chain: the publication manifest and the modeled
``ReleaseGraphValidationReceipt`` must pass REF JSON Binding 1.0, and the
receipt must exactly bind the packaged graph, publication and operational
records, validator, and covered identifiers. The aggregate corpus descriptor
independently binds every indexed expression. The caller supplies the trusted
bundle-manifest byte digest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq

import refspec.release_graph as release_graph_module
from refspec import binding
from refspec.generated_rulespec_dependency import (
    RULESPEC_DEPENDENCY_BYTES,
    RULESPEC_DEPENDENCY_SHA256,
)
from refspec.release_graph import (
    DEPENDENCY_MANIFEST_ID,
    RELEASE_GRAPH_GATE_COMPONENT_ID,
    RELEASE_GRAPH_GATE_VERSION,
    RULESPEC_BEHAVIOR_RUNTIME_COMPONENT_ID,
    RULESPEC_VALIDATOR_COMPONENT_ID,
    canonical_value_digest,
    defined_rulespec_identifiers,
    rulespec_graph_digest,
)
from refspec.storage import canonical_json
from refspec.vocabulary import (
    CONCEPT_EVENT_PARTICIPANT_COLUMNS,
    CONCEPT_LABEL_COLUMNS,
    CONCEPT_RELATION_COLUMNS,
    ReferenceRuntimeError,
    indexed_expression_id_set_digest,
    indexed_expression_identity_from_record,
)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
_RAW_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
_TABLE_COLUMNS = {
    "concept_labels": CONCEPT_LABEL_COLUMNS,
    "concept_relations": CONCEPT_RELATION_COLUMNS,
    "concept_event_participants": CONCEPT_EVENT_PARTICIPANT_COLUMNS,
}
_TABLE_REQUIRED_TEXT_COLUMNS = {
    "concept_labels": tuple(
        field for field in CONCEPT_LABEL_COLUMNS if field != "migration_only"
    ),
    "concept_relations": tuple(
        field for field in CONCEPT_RELATION_COLUMNS if field != "migration_only"
    ),
    "concept_event_participants": tuple(
        field
        for field in CONCEPT_EVENT_PARTICIPANT_COLUMNS
        if field not in {"complete_membership", "ordinal", "migration_only"}
    ),
}
_PUBLICATION_TYPE = "urn:ref:type:PublicationReleaseManifest"
_EXPRESSION_TYPE = "urn:ref:type:IndexedVocabularyExpression"
_IMPORT_SNAPSHOT_TYPE = "urn:ref:type:RegistryImportSnapshot"
_COMBINED_RECEIPT_TYPE = "urn:ref:type:ReleaseGraphValidationReceipt"
_SELECTED_DEPLOYMENT_TYPES = {
    "urn:ref:type:RegistryDeploymentDecision",
    "urn:ref:type:EnrichmentDeploymentDecision",
}
_RECONCILIATION_TYPE = "urn:ref:type:RegistryReconciliationReport"
_RESOLVED_RECONCILIATION_OUTCOMES = {
    "selectedInput",
    "reconciledReleaseAuthorized",
}
_AUTHORIZED_USAGE_LEVELS = {
    "rkaf:localOperationalUse",
    "rkaf:publicationAllowed",
    "rkaf:officialUse",
}
_RELEASE_TYPES = {
    "rkaf:ReferenceResourceRelease",
    "https://rulespec.org/ns/v1#ReferenceResourceRelease",
}
_LIFECYCLE_TYPES = {
    "rkaf:LifecycleEvent",
    "https://rulespec.org/ns/v1#LifecycleEvent",
}
_CONCEPT_MAPPING_TYPES = {
    "rkaf:ConceptMapping",
    "https://rulespec.org/ns/v1#ConceptMapping",
}
_LABEL_PROPERTIES = {
    "http://www.w3.org/2004/02/skos/core#prefLabel": "skos:prefLabel",
    "http://www.w3.org/2004/02/skos/core#altLabel": "skos:altLabel",
    "http://www.w3.org/2004/02/skos/core#hiddenLabel": "skos:hiddenLabel",
}
_LABEL_ROLES = {
    "http://www.w3.org/2004/02/skos/core#prefLabel": "preferred",
    "http://www.w3.org/2004/02/skos/core#altLabel": "alternate",
    "http://www.w3.org/2004/02/skos/core#hiddenLabel": "hidden",
}
_NATIVE_IDENTITY_PROPERTIES = {
    "dcterms:isVersionOf": "http://purl.org/dc/terms/isVersionOf",
    "dct:isVersionOf": "http://purl.org/dc/terms/isVersionOf",
    "http://purl.org/dc/terms/isVersionOf": "http://purl.org/dc/terms/isVersionOf",
    "owl:priorVersion": "http://www.w3.org/2002/07/owl#priorVersion",
    "http://www.w3.org/2002/07/owl#priorVersion": (
        "http://www.w3.org/2002/07/owl#priorVersion"
    ),
    "dcterms:isReplacedBy": "http://purl.org/dc/terms/isReplacedBy",
    "dct:isReplacedBy": "http://purl.org/dc/terms/isReplacedBy",
    "http://purl.org/dc/terms/isReplacedBy": ("http://purl.org/dc/terms/isReplacedBy"),
    "dcterms:replaces": "http://purl.org/dc/terms/replaces",
    "dct:replaces": "http://purl.org/dc/terms/replaces",
    "http://purl.org/dc/terms/replaces": "http://purl.org/dc/terms/replaces",
}
CANDIDATE_EXCLUDED_SOURCE_STATUSES = frozenset(
    {
        "deprecated",
        "inactive",
        "withdrawn",
    }
)
_CURRENT_ASSIGNMENT_RETIRING_OPERATIONS = frozenset(
    {
        "deprecation",
        "withdrawal",
        "replacement",
        "split",
        "merge",
    }
)
_RELATION_PROPERTIES = {
    "http://www.w3.org/2004/02/skos/core#broader": "skos:broader",
    "http://www.w3.org/2004/02/skos/core#narrower": "skos:narrower",
    "http://www.w3.org/2004/02/skos/core#related": "skos:related",
}
_ELSST_NATIVE_SKOS_IMPORT_POLICY = "urn:ref:policy:elsst-native-skos-lossless:v1"


class ManagedReleaseError(ValueError):
    """A managed-release bundle is incomplete, mutable, or inconsistent."""


class ManagedReleaseAuthorizationError(ManagedReleaseError):
    """The selected managed release does not authorize the requested use."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(child) for key, child in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze(child) for child in value)
    return value


def _table_text(
    row: Mapping[str, Any],
    field: str,
) -> str:
    value = row.get(field)
    return value if isinstance(value, str) else ""


def _required_table_text(
    row: Mapping[str, Any],
    field: str,
    *,
    table: str,
) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ManagedReleaseError(
            f"normalized table {table}.{field} must be non-empty text"
        )
    return value


def _table_bool(
    row: Mapping[str, Any],
    field: str,
) -> bool:
    value = _table_text(row, field).casefold()
    if value not in {"true", "false"}:
        raise ManagedReleaseError(
            f"normalized table field {field} must be true or false"
        )
    return value == "true"


def _table_ordinal(
    row: Mapping[str, Any],
    field: str,
) -> int:
    value = _table_text(row, field)
    if not value.isdigit():
        raise ManagedReleaseError(
            f"normalized table field {field} must be a non-negative integer"
        )
    return int(value)


@dataclass(frozen=True, slots=True)
class _NormalizedLabelRow:
    label_id: str
    concept_iri: str
    scheme_iri: str
    release_iri: str
    import_snapshot_id: str
    distribution_artifact_id: str
    source_property_iri: str
    label_role: str
    original_literal: str
    language_tag: str
    source_status: str
    expression_id: str
    migration_only: bool


@dataclass(frozen=True, slots=True)
class _NormalizedRelationRow:
    relation_id: str
    release_iri: str
    import_snapshot_id: str
    distribution_artifact_id: str
    subject_concept_iri: str
    subject_scheme_iri: str
    predicate_iri: str
    object_concept_iri: str
    object_scheme_iri: str
    migration_only: bool


@dataclass(frozen=True, slots=True)
class _NormalizedParticipantRow:
    event_id: str
    operation: str
    participant_role: str
    concept_iri: str
    concept_type_iri: str
    release_iri: str
    complete_membership: bool
    ordinal: int
    migration_only: bool


def _json_from_bytes(payload: bytes, label: str) -> Any:
    try:
        text = payload.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ManagedReleaseError(
            f"{label} is not canonical UTF-8 JSON: {error}"
        ) from error


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ManagedReleaseError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_digest_reference(
    value: object,
    label: str,
) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"id", "digest"}:
        raise ManagedReleaseError(f"{label} must be one exact id and digest reference")
    identifier = value.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ManagedReleaseError(f"{label}.id is required")
    return {
        "id": identifier,
        "digest": _require_digest(value.get("digest"), f"{label}.digest"),
    }


def _reference_key(value: Mapping[str, Any]) -> tuple[str, str]:
    return str(value.get("id", "")), str(value.get("digest", ""))


def _safe_relative_path(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ManagedReleaseError(f"{label}.path is required")
    if "\\" in value:
        raise ManagedReleaseError(f"{label}.path must use relative POSIX syntax")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in posix.parts)
        or "://" in value
    ):
        raise ManagedReleaseError(
            f"{label}.path must be a non-traversing relative file path"
        )
    return posix


def _artifact_descriptor(
    value: object,
    label: str,
) -> tuple[PurePosixPath, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ManagedReleaseError(
            f"{label} must name one relative path and immutable SHA-256 digest"
        )
    return (
        _safe_relative_path(value.get("path"), label),
        _require_digest(value.get("sha256"), f"{label}.sha256"),
    )


def _source_artifact_descriptor(
    value: object,
    label: str,
) -> tuple[PurePosixPath, str, int]:
    if not isinstance(value, dict) or set(value) != {
        "path",
        "sha256",
        "byteLength",
    }:
        raise ManagedReleaseError(
            f"{label} must name one relative path, immutable SHA-256 digest, and byte length"
        )
    byte_length = value.get("byteLength")
    if (
        not isinstance(byte_length, int)
        or isinstance(byte_length, bool)
        or byte_length <= 0
    ):
        raise ManagedReleaseError(f"{label}.byteLength must be a positive integer")
    return (
        _safe_relative_path(value.get("path"), label),
        _require_digest(value.get("sha256"), f"{label}.sha256"),
        byte_length,
    )


def _read_verified_artifact(
    root: Path,
    descriptor: object,
    label: str,
    seen_paths: set[PurePosixPath],
) -> bytes:
    relative, expected = _artifact_descriptor(descriptor, label)
    if relative in seen_paths:
        raise ManagedReleaseError(f"{label}.path duplicates another bundle artifact")
    seen_paths.add(relative)
    resolved = _resolved_artifact_path(root, relative, label)
    payload = resolved.read_bytes()
    actual = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ManagedReleaseError(
            f"{label} digest mismatch: expected {expected}, got {actual}"
        )
    return payload


def _resolved_artifact_path(
    root: Path,
    relative: PurePosixPath,
    label: str,
) -> Path:
    """Resolve one already parsed bundle path without following symlinks."""

    path = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ManagedReleaseError(f"{label}.path must not traverse a symlink")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as error:
        raise ManagedReleaseError(
            f"{label}.path is missing or escapes the bundle root"
        ) from error
    if not resolved.is_file():
        raise ManagedReleaseError(f"{label}.path does not name a regular file")
    return resolved


def _verified_artifact_path(
    root: Path,
    descriptor: object,
    label: str,
    seen_paths: set[PurePosixPath],
) -> Path:
    """Verify a large artifact by streaming, then return its safe path."""

    relative, expected = _artifact_descriptor(descriptor, label)
    if relative in seen_paths:
        raise ManagedReleaseError(f"{label}.path duplicates another bundle artifact")
    seen_paths.add(relative)
    resolved = _resolved_artifact_path(root, relative, label)
    digest = hashlib.sha256()
    with resolved.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = "sha256:" + digest.hexdigest()
    if actual != expected:
        raise ManagedReleaseError(
            f"{label} digest mismatch: expected {expected}, got {actual}"
        )
    return resolved


def _read_verified_source_artifact(
    root: Path,
    descriptor: object,
    label: str,
    seen_paths: set[PurePosixPath],
) -> bytes:
    relative, expected, byte_length = _source_artifact_descriptor(
        descriptor,
        label,
    )
    payload = _read_verified_artifact(
        root,
        {
            "path": str(relative),
            "sha256": expected,
        },
        label,
        seen_paths,
    )
    if len(payload) != byte_length:
        raise ManagedReleaseError(
            f"{label} byte length mismatch: expected {byte_length}, got {len(payload)}"
        )
    return payload


def _verified_source_artifact_facts(
    root: Path,
    descriptor: object,
    label: str,
    seen_paths: set[PurePosixPath],
) -> tuple[str, int]:
    """Stream-verify source bytes without retaining them in memory."""

    relative, expected, byte_length = _source_artifact_descriptor(
        descriptor,
        label,
    )
    path = _verified_artifact_path(
        root,
        {
            "path": str(relative),
            "sha256": expected,
        },
        label,
        seen_paths,
    )
    actual_length = path.stat().st_size
    if actual_length != byte_length:
        raise ManagedReleaseError(
            f"{label} byte length mismatch: expected {byte_length}, got {actual_length}"
        )
    return expected, byte_length


def _record_digest_reference(
    record: Mapping[str, Any],
    label: str,
) -> tuple[str, str]:
    identifier = record.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ManagedReleaseError(f"{label}.id is required")
    field = binding.digest_field(dict(record))
    actual = record.get(field)
    expected = binding.canonical_payload_digest(dict(record))
    if actual != expected:
        raise ManagedReleaseError(
            f"{label}.{field} mismatch: expected {expected}, got {actual}"
        )
    return identifier, cast(str, actual)


def _require_binding_valid(
    records: list[dict[str, Any]],
    label: str,
) -> None:
    try:
        diagnostics = binding.validate(records)
    except (OSError, TypeError, ValueError) as error:
        raise ManagedReleaseError(
            f"{label} could not be checked with REF JSON Binding 1.0: {error}"
        ) from error
    if diagnostics:
        rendered = "; ".join(diagnostic.render() for diagnostic in diagnostics)
        raise ManagedReleaseError(f"{label} fails REF JSON Binding 1.0: {rendered}")


def _dependency_validator_pin(
    dependency: Mapping[str, Any],
) -> dict[str, str]:
    validator = dependency.get("validator")
    if not isinstance(validator, Mapping):
        raise ManagedReleaseError(
            "rulespecDependencyManifest.validator must be an object"
        )
    identity = validator.get("identity")
    revision = validator.get("sourceRevision")
    certification = validator.get("selfCertificationSha256")
    if not isinstance(identity, str) or not identity.strip():
        raise ManagedReleaseError(
            "rulespecDependencyManifest.validator.identity is required"
        )
    if not isinstance(revision, str) or not _GIT_REVISION.fullmatch(revision):
        raise ManagedReleaseError(
            "rulespecDependencyManifest.validator.sourceRevision is invalid"
        )
    if not isinstance(certification, str) or not _RAW_SHA256.fullmatch(certification):
        raise ManagedReleaseError(
            "rulespecDependencyManifest validator certification digest is invalid"
        )
    return {
        "id": RULESPEC_VALIDATOR_COMPONENT_ID,
        "revision": revision,
        "digest": canonical_value_digest(
            {
                "identity": identity,
                "sourceRevision": revision,
                "selfCertificationSha256": certification,
            }
        ),
    }


def _dependency_behavior_runtime_pin(
    dependency: Mapping[str, Any],
) -> dict[str, str]:
    validator = dependency.get("validator")
    if not isinstance(validator, Mapping):
        raise ManagedReleaseError(
            "rulespecDependencyManifest.validator must be an object"
        )
    revision = validator.get("sourceRevision")
    if not isinstance(revision, str) or not _GIT_REVISION.fullmatch(revision):
        raise ManagedReleaseError(
            "rulespecDependencyManifest behavior runtime revisions are invalid"
        )
    return {
        "id": RULESPEC_BEHAVIOR_RUNTIME_COMPONENT_ID,
        "revision": revision,
        "digest": canonical_value_digest(
            {
                "identity": "rkaf-behavior-validate",
                "sourceRevision": revision,
                "sourcePaths": [
                    "crates/rkaf-runtime",
                    "crates/rkaf-runtime-cli",
                ],
            }
        ),
    }


def _installed_release_graph_gate_pin() -> dict[str, str]:
    source_path = Path(cast(str, release_graph_module.__file__))
    return {
        "id": RELEASE_GRAPH_GATE_COMPONENT_ID,
        "revision": RELEASE_GRAPH_GATE_VERSION,
        "digest": "sha256:" + hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }


def _behavior_test_identifier(governance_record_id: str) -> str:
    suffix = hashlib.sha256(governance_record_id.encode("utf-8")).hexdigest()
    return f"urn:ref:behavior-test:governance-authorization:{suffix}"


def _governance_authorization_requirements(
    records: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], tuple[str, str, str]]:
    requirements: dict[tuple[str, str], tuple[str, str, str]] = {}
    for record in records:
        record_type = record.get("type")
        if (
            record_type in _SELECTED_DEPLOYMENT_TYPES
            and record.get("selectionState") == "selected"
        ):
            scope_source = record.get("environment")
            evaluation_time = record.get("effectiveAt")
        elif (
            record_type == _RECONCILIATION_TYPE
            and record.get("outcome") in _RESOLVED_RECONCILIATION_OUTCOMES
        ):
            scope_source = record.get("precedencePolicy")
            evaluation_time = record.get("recordedAt")
        else:
            continue
        identifier = record.get("id")
        digest = record.get(binding.digest_field(dict(record)))
        scope = scope_source.get("id") if isinstance(scope_source, Mapping) else None
        if not all(
            isinstance(value, str) and value
            for value in (identifier, digest, scope, evaluation_time)
        ):
            raise ManagedReleaseError(
                "authorizing REF record lacks an exact identifier, digest, scope, or evaluation time"
            )
        reference = (cast(str, identifier), cast(str, digest))
        requirements[reference] = (
            cast(str, record_type),
            cast(str, scope),
            cast(str, evaluation_time),
        )
    return requirements


def _require_authorization_evaluation_coverage(
    *,
    receipt: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    graph_reference: Mapping[str, str],
    graph_identifiers: set[str],
    expected_runtime: Mapping[str, str],
) -> None:
    requirements = _governance_authorization_requirements(records)
    values = receipt.get("authorizationEvaluations")
    if not isinstance(values, list):
        raise ManagedReleaseError(
            "combinedValidationReceipt.authorizationEvaluations must be an array"
        )
    evaluations: dict[tuple[str, str], Mapping[str, Any]] = {}
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise ManagedReleaseError(
                f"combinedValidationReceipt.authorizationEvaluations[{index}] must be an object"
            )
        governance_reference = _reference_key(
            _require_digest_reference(
                value.get("governanceRecord"),
                f"combinedValidationReceipt.authorizationEvaluations[{index}].governanceRecord",
            )
        )
        if governance_reference in evaluations:
            raise ManagedReleaseError(
                "combinedValidationReceipt.authorizationEvaluations repeats "
                f"governance record {governance_reference[0]!r}"
            )
        evaluations[governance_reference] = value

    if set(evaluations) != set(requirements):
        raise ManagedReleaseError(
            "combinedValidationReceipt.authorizationEvaluations does not "
            "exactly cover every selected deployment and resolved "
            "reconciliation"
        )

    for reference, (record_type, scope, evaluation_time) in requirements.items():
        evaluation = evaluations[reference]
        if evaluation.get("inputGraph") != dict(graph_reference):
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation does not bind the exact Rulespec graph"
            )
        if evaluation.get("runtime") != dict(expected_runtime):
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation does not bind the exact embedded Rulespec L4 runtime"
            )
        if (
            evaluation.get("behaviorContract") != "rkaf:UsageEligibilityReducer"
            or evaluation.get("minimumUsageEligibility") != "rkaf:localOperationalUse"
            or evaluation.get("result") != "pass"
        ):
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation is not a passing gate-owned usage-eligibility evaluation"
            )
        if (
            evaluation.get("evaluationScope") != scope
            or evaluation.get("evaluationTime") != evaluation_time
        ):
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation does not bind its derived scope and evaluation time"
            )
        subject = evaluation.get("subjectAssertion")
        if subject not in graph_identifiers:
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation subject is not defined in the exact Rulespec graph"
            )
        effective_level = evaluation.get("effectiveUsageEligibility")
        if effective_level not in _AUTHORIZED_USAGE_LEVELS:
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation is below the required local-operational-use level"
            )
        expected_output_digest = canonical_value_digest(
            {"byScope": {scope: effective_level}}
        )
        if evaluation.get("outputDigest") != expected_output_digest:
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation output digest does not match its exact effective result"
            )
        behavior_test = _require_digest_reference(
            evaluation.get("behaviorTest"),
            f"{record_type} authorization evaluation behaviorTest",
        )
        if behavior_test["id"] != _behavior_test_identifier(reference[0]):
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation does not name the "
                "gate-owned behavior test for its governance record"
            )


def _iter_nested_references(
    value: Any, *, top_level: bool = False
) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if not top_level and {"id", "digest"}.issubset(value):
            yield value
        for child in value.values():
            yield from _iter_nested_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_nested_references(child)


def _iter_named_values(value: Any, name: str) -> Iterator[Any]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == name:
                yield child
            yield from _iter_named_values(child, name)
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes),
    ):
        for child in value:
            yield from _iter_named_values(child, name)


def _resolve_import_snapshot(
    reference: object,
    *,
    records_by_id: Mapping[str, Mapping[str, Any]],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(reference, Mapping):
        raise ManagedReleaseError(
            f"{label} is not an exact RegistryImportSnapshot reference"
        )
    identifier = reference.get("id")
    record = records_by_id.get(identifier) if isinstance(identifier, str) else None
    if (
        record is None
        or record.get("type") != _IMPORT_SNAPSHOT_TYPE
        or not binding.references_record(dict(reference), dict(record))
    ):
        raise ManagedReleaseError(
            f"{label} does not resolve to an exact packaged RegistryImportSnapshot"
        )
    return record


def _require_import_lineage(
    *,
    import_snapshot_id: str,
    release_iri: str,
    distribution_artifact_id: str,
    records_by_id: Mapping[str, Mapping[str, Any]],
    label: str,
) -> None:
    record = records_by_id.get(import_snapshot_id)
    if record is None or record.get("type") != _IMPORT_SNAPSHOT_TYPE:
        raise ManagedReleaseError(f"{label} import snapshot is absent from the bundle")
    release = record.get("referenceResourceRelease")
    distributions = record.get("distributionArtifacts")
    if (
        not isinstance(release, Mapping)
        or release.get("id") != release_iri
        or not isinstance(distributions, Sequence)
        or isinstance(distributions, (str, bytes))
        or distribution_artifact_id
        not in {item.get("id") for item in distributions if isinstance(item, Mapping)}
    ):
        raise ManagedReleaseError(
            f"{label} import, release, and distribution lineage disagree"
        )


def _node_types(node: Mapping[str, Any]) -> set[str]:
    value = node.get("@type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return {str(item) for item in value}
    return set()


def _type_spellings(type_iri: str) -> set[str]:
    """Return the absolute type IRI and any supported compact spelling."""

    values = {type_iri}
    for namespace, prefix in (
        ("https://rulespec.org/ns/v1#", "rkaf"),
        ("http://www.w3.org/2004/02/skos/core#", "skos"),
    ):
        if type_iri.startswith(namespace):
            values.add(f"{prefix}:{type_iri.removeprefix(namespace)}")
    return values


def _iri_values(value: object) -> tuple[str, ...]:
    values: Sequence[object]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = value
    else:
        values = (value,)
    result: list[str] = []
    for item in values:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, Mapping) and isinstance(item.get("@id"), str):
            result.append(str(item["@id"]))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class _GraphPropertyIndex:
    """Operation-scoped exact graph values used by normalized-table checks."""

    language_literals: frozenset[tuple[str, str, str, str]]
    iri_targets: Mapping[tuple[str, str], frozenset[str]]
    iri_sequences: Mapping[tuple[str, str], tuple[str, ...]]


def _index_graph_property_targets(
    nodes: Mapping[str, Mapping[str, Any]],
) -> _GraphPropertyIndex:
    """Index each relevant graph property once for constant-time row checks."""

    language_literals: set[tuple[str, str, str, str]] = set()
    iri_targets: dict[tuple[str, str], frozenset[str]] = {}
    iri_sequences: dict[tuple[str, str], tuple[str, ...]] = {}
    label_properties = frozenset(_LABEL_PROPERTIES.values())
    iri_properties = frozenset(
        {
            *_RELATION_PROPERTIES.values(),
            "rkaf:predecessorConcepts",
            "rkaf:predecessorConceptRelease",
            "rkaf:successorConcepts",
            "rkaf:successorConceptRelease",
        }
    )
    for identifier, node in nodes.items():
        for property_name in label_properties:
            raw = node.get(property_name)
            if not isinstance(raw, Mapping):
                continue
            for language, values in raw.items():
                if not isinstance(language, str):
                    continue
                if isinstance(values, str):
                    literals = (values,)
                elif isinstance(values, Sequence) and not isinstance(
                    values,
                    (str, bytes),
                ):
                    literals = tuple(
                        value for value in values if isinstance(value, str)
                    )
                else:
                    literals = ()
                language_literals.update(
                    (identifier, property_name, language, literal)
                    for literal in literals
                )
        for property_name in iri_properties:
            values = _iri_values(node.get(property_name))
            key = (identifier, property_name)
            iri_sequences[key] = values
            iri_targets[key] = frozenset(values)
    return _GraphPropertyIndex(
        language_literals=frozenset(language_literals),
        iri_targets=MappingProxyType(iri_targets),
        iri_sequences=MappingProxyType(iri_sequences),
    )


def _rulespec_nodes(graph: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(graph, dict):
        raise ManagedReleaseError("rulespecGraph must be a JSON-LD object")
    raw = graph.get("@graph")
    if not isinstance(raw, list) or not raw:
        raise ManagedReleaseError("rulespecGraph must contain a non-empty @graph")
    nodes: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(raw):
        if not isinstance(node, dict):
            raise ManagedReleaseError(
                f"rulespecGraph.@graph[{index}] must be an object"
            )
        identifier = node.get("@id")
        if not isinstance(identifier, str) or not identifier:
            raise ManagedReleaseError(f"rulespecGraph.@graph[{index}] has no @id")
        if identifier in nodes:
            raise ManagedReleaseError(
                f"rulespecGraph repeats identifier {identifier!r}"
            )
        nodes[identifier] = node
    return nodes


def _release_membership(
    nodes: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, str], dict[str, str]]:
    member_release: dict[str, str] = {}
    member_scheme: dict[str, str] = {}
    for release_id, release in nodes.items():
        if not (_node_types(release) & _RELEASE_TYPES):
            continue
        if release.get("rkaf:membershipMode") not in {
            "rkaf:completeMembership",
            "https://rulespec.org/ns/v1#completeMembership",
        }:
            continue
        for member in _iri_values(release.get("prov:hadMember")):
            if member in member_release:
                raise ManagedReleaseError(
                    f"member {member!r} occurs in more than one selected release"
                )
            concept = nodes.get(member)
            if concept is None:
                raise ManagedReleaseError(
                    f"complete release {release_id!r} names missing member {member!r}"
                )
            schemes = _iri_values(concept.get("skos:inScheme"))
            if len(schemes) != 1:
                raise ManagedReleaseError(
                    f"member {member!r} must identify exactly one concept scheme"
                )
            member_release[member] = release_id
            member_scheme[member] = schemes[0]
    if not member_release:
        raise ManagedReleaseError(
            "rulespecGraph has no exact complete-membership release members"
        )
    return member_release, member_scheme


@dataclass(frozen=True, slots=True)
class _ExpressionCorpusDescriptor:
    """Validated facts that bind one indexed-expression corpus artifact."""

    path: Path
    record_count: int
    identity_digest: str
    snapshot: Mapping[str, str]


def _verified_expression_corpus_descriptor(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    publication: Mapping[str, Any],
    seen_paths: set[PurePosixPath],
) -> _ExpressionCorpusDescriptor:
    """Validate the corpus description and stream-verify its exact bytes."""

    corpus_descriptor = manifest.get("indexedExpressionCorpus")
    if not isinstance(corpus_descriptor, dict) or set(corpus_descriptor) != {
        "path",
        "sha256",
        "expressionCorpusSnapshot",
        "recordCount",
        "schemaVersion",
        "canonicalIdentityDigest",
    }:
        raise ManagedReleaseError(
            "indexedExpressionCorpus must bind its artifact, snapshot, "
            "record count, schema version, and canonical identity digest"
        )
    corpus_record_count = corpus_descriptor.get("recordCount")
    if (
        not isinstance(corpus_record_count, int)
        or isinstance(corpus_record_count, bool)
        or corpus_record_count <= 0
    ):
        raise ManagedReleaseError(
            "indexedExpressionCorpus.recordCount must be a positive integer"
        )
    if corpus_descriptor.get("schemaVersion") != "ref-indexed-expression-corpus-1.0":
        raise ManagedReleaseError(
            "indexedExpressionCorpus.schemaVersion is unsupported"
        )
    corpus_identity_digest = _require_digest(
        corpus_descriptor.get("canonicalIdentityDigest"),
        "indexedExpressionCorpus.canonicalIdentityDigest",
    )
    corpus_snapshot = _require_digest_reference(
        corpus_descriptor.get("expressionCorpusSnapshot"),
        "indexedExpressionCorpus.expressionCorpusSnapshot",
    )
    if corpus_identity_digest != corpus_snapshot["digest"]:
        raise ManagedReleaseError(
            "indexedExpressionCorpus canonical identity digest does not match its logical snapshot digest"
        )
    publication_snapshot = _require_digest_reference(
        publication.get("expressionCorpusSnapshot"),
        "PublicationReleaseManifest.expressionCorpusSnapshot",
    )
    if corpus_snapshot != publication_snapshot:
        raise ManagedReleaseError(
            "indexed expression corpus snapshot does not match PublicationReleaseManifest"
        )
    lookup_identity = manifest.get("lookupIndexManifest")
    if lookup_identity is not None:
        lookup_reference = _require_digest_reference(
            lookup_identity,
            "lookupIndexManifest",
        )
        if lookup_reference["id"] == corpus_snapshot["id"]:
            raise ManagedReleaseError(
                "bundle conflates expressionCorpusSnapshot with lookupIndexManifest"
            )
        raise ManagedReleaseError(
            "physical lookupIndexManifest belongs to a consumer configuration, not a managed-release bundle"
        )
    corpus_path = _verified_artifact_path(
        root,
        {
            "path": corpus_descriptor.get("path"),
            "sha256": corpus_descriptor.get("sha256"),
        },
        "indexedExpressionCorpus",
        seen_paths,
    )
    return _ExpressionCorpusDescriptor(
        path=corpus_path,
        record_count=corpus_record_count,
        identity_digest=corpus_identity_digest,
        snapshot=MappingProxyType(corpus_snapshot),
    )


def _validate_combined_receipt(
    *,
    combined_receipt: object,
    graph_reference: Mapping[str, str],
    dependency_digest: str,
    publication_id: str,
    publication_digest: str,
    actual_operational_refs: set[tuple[str, str]],
    expected_validator: Mapping[str, str],
    expected_behavior_runtime: Mapping[str, str],
    expected_gate: Mapping[str, str],
    graph_identifiers: set[str],
    ref_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate the one receipt shared by full and graph-facts readers."""

    if (
        not isinstance(combined_receipt, dict)
        or combined_receipt.get("type") != _COMBINED_RECEIPT_TYPE
    ):
        raise ManagedReleaseError(
            "combinedValidationReceipt must contain one ReleaseGraphValidationReceipt"
        )
    _require_binding_valid(
        [combined_receipt],
        "combined validation receipt",
    )
    if combined_receipt.get("operationalState") != "passed":
        raise ManagedReleaseError(
            "ReleaseGraphValidationReceipt operationalState must be passed"
        )
    if combined_receipt.get("rulespecGraph") != graph_reference:
        raise ManagedReleaseError(
            "combinedValidationReceipt does not bind the exact Rulespec graph"
        )
    if combined_receipt.get("rulespecDependencyManifest") != {
        "id": DEPENDENCY_MANIFEST_ID,
        "digest": dependency_digest,
    }:
        raise ManagedReleaseError(
            "combinedValidationReceipt does not bind the embedded Rulespec dependency manifest"
        )
    receipt_record_values = combined_receipt.get("refRecordDigests")
    if not isinstance(receipt_record_values, list):
        raise ManagedReleaseError(
            "combinedValidationReceipt.refRecordDigests must be an array"
        )
    receipt_record_refs = {
        _reference_key(
            _require_digest_reference(
                value,
                f"combinedValidationReceipt.refRecordDigests[{index}]",
            )
        )
        for index, value in enumerate(receipt_record_values)
    }
    if len(receipt_record_refs) != len(receipt_record_values):
        raise ManagedReleaseError(
            "combinedValidationReceipt.refRecordDigests repeats a reference"
        )
    exact_ref_records = {
        (publication_id, publication_digest),
        *actual_operational_refs,
    }
    if receipt_record_refs != exact_ref_records:
        raise ManagedReleaseError(
            "combinedValidationReceipt.refRecordDigests does not exactly "
            "cover the publication and operational REF records"
        )
    if combined_receipt.get("rulespecValidator") != dict(expected_validator):
        raise ManagedReleaseError(
            "combinedValidationReceipt Rulespec validator identity or revision does not match the dependency manifest"
        )
    if combined_receipt.get("rulespecBehaviorRuntime") != dict(
        expected_behavior_runtime
    ):
        raise ManagedReleaseError(
            "combinedValidationReceipt Rulespec behavior runtime does not match the exact embedded dependency"
        )
    if combined_receipt.get("gateImplementation") != dict(expected_gate):
        raise ManagedReleaseError(
            "combinedValidationReceipt gate implementation does not match the installed RefSpec release-graph gate"
        )
    if combined_receipt.get("verdicts") != {
        "refBinding": "pass",
        "rulespecConformance": "pass",
        "rulespecBehavior": "pass",
        "crossBoundary": "pass",
    }:
        raise ManagedReleaseError(
            "combinedValidationReceipt must carry four exact pass verdicts"
        )
    covered_values = combined_receipt.get("coveredRulespecIdentifiers")
    if (
        not isinstance(covered_values, list)
        or any(not isinstance(value, str) for value in covered_values)
        or len(covered_values) != len(set(covered_values))
        or set(covered_values) != graph_identifiers
    ):
        raise ManagedReleaseError(
            "combinedValidationReceipt covered Rulespec identifiers do not exactly match the graph"
        )
    _require_authorization_evaluation_coverage(
        receipt=combined_receipt,
        records=ref_records,
        graph_reference=graph_reference,
        graph_identifiers=graph_identifiers,
        expected_runtime=expected_behavior_runtime,
    )
    return combined_receipt


@dataclass(frozen=True, slots=True)
class ManagedReleaseMember:
    """One exact member of a complete Rulespec release."""

    member_iri: str
    release_iri: str
    scheme_iri: str
    record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ManagedReleaseGraphFactsView:
    """Verified graph facts from a managed bundle, without corpus eligibility.

    This view validates the externally pinned bundle manifest, every declared
    artifact digest, the complete Rulespec graph and membership, linked REF
    records, embedded dependency, and combined gate receipt.  It deliberately
    stream-hashes but does not parse the indexed-expression corpus or normalized
    tables.  Callers that need expressions, table rows, source bytes, or
    candidate-use authorization must use :class:`ManagedReleaseView`.
    """

    _release_id: str
    _rulespec_graph_id: str
    _rulespec_graph: Mapping[str, Any]
    _expression_corpus_snapshot: Mapping[str, str]
    _members: Mapping[str, ManagedReleaseMember]
    _release_graph_validation_receipt: Mapping[str, Any]

    eligibility_scope = "graphFactsOnly"

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> ManagedReleaseGraphFactsView:
        """Open one fresh verification boundary over exact bundle bytes."""

        view = ManagedReleaseView.open(
            manifest_path,
            expected_manifest_digest=expected_manifest_digest,
            _graph_facts_only=True,
        )
        if not isinstance(view, cls):  # pragma: no cover - internal invariant
            raise ManagedReleaseError(
                "managed graph-facts reader returned the wrong view kind"
            )
        return view

    @property
    def release_id(self) -> str:
        """Return the verified PublicationReleaseManifest identifier."""

        return self._release_id

    @property
    def rulespec_graph_id(self) -> str:
        return self._rulespec_graph_id

    @property
    def rulespec_graph(self) -> Mapping[str, Any]:
        return self._rulespec_graph

    @property
    def expression_corpus_snapshot(self) -> Mapping[str, str]:
        """Return descriptor linkage only, not corpus semantic eligibility."""

        return self._expression_corpus_snapshot

    @property
    def release_graph_validation_receipt(self) -> Mapping[str, Any]:
        return self._release_graph_validation_receipt

    def lookup_member(self, member_iri: str) -> ManagedReleaseMember | None:
        return self._members.get(member_iri)

    def iter_members(
        self,
        *,
        release_iri: str | None = None,
    ) -> Iterator[ManagedReleaseMember]:
        for member in self._members.values():
            if release_iri is None or member.release_iri == release_iri:
                yield member


@dataclass(frozen=True, slots=True)
class ManagedReleaseIdentityLink:
    """One exact native identity, version, or replacement link.

    The link comes directly from a frozen source member record.  RefSpec
    expands only the JSON-LD predicate spelling; it does not create a
    ``ConceptVersion`` record or infer an identity relation.
    """

    subject_member_iri: str
    predicate_iri: str
    object_iri: str
    subject_release_iri: str
    object_release_iri: str | None


@dataclass(frozen=True, slots=True)
class ManagedReleaseExpression:
    """One immutable indexed expression retained for evidence and lookup."""

    expression_id: str
    member_iri: str
    indexed_text: str
    original_literal: str
    language_tag: str | None
    semantic_property_iri: str
    source_property_or_path: str
    record: Mapping[str, Any]
    label_role: str | None = None
    source_status: str | None = None


@dataclass(frozen=True, slots=True)
class ManagedReleaseRelation:
    """One immutable normalized relation between exact release members."""

    relation_id: str
    subject_member_iri: str
    predicate_iri: str
    object_member_iri: str
    release_iri: str
    record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ManagedReleaseLifecycleParticipant:
    """One immutable predecessor or successor release member."""

    event_iri: str
    operation: str
    participant_role: str
    member_iri: str
    release_iri: str
    ordinal: int
    record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ManagedReleaseConceptMapping:
    """One validated Rulespec mapping; never an exact-identity lookup."""

    mapping_iri: str
    source_member_iri: str
    relation_iri: str
    target_member_iri: str
    source_release_iri: str
    target_release_iri: str
    record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ManagedReleaseCandidatePermission:
    """One exact candidate-use permission resolved by RefSpec.

    This value is an immutable view of the selected registry deployment, its
    OutputProfile row, and the matching EnrichmentProfile route.  It grants no
    accepted-output authority.
    """

    facet_iri: str
    assignment_role_iri: str
    resource_route: str
    reference_resource_release: Mapping[str, Any]
    registry_import_snapshot: Mapping[str, Any]
    required_import_features: tuple[str, ...]
    permission_row: Mapping[str, Any]
    output_profile: Mapping[str, Any]
    enrichment_profile: Mapping[str, Any]
    coverage_report: Mapping[str, Any]
    registry_deployment: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ManagedReleaseView:
    """Read-only member, expression, relation, lifecycle, and mapping access.

    Expressions retain raw evidence access separately from current-assignment
    candidate access. Relations and lifecycle participants are byte-pinned
    normalized rows that round-trip to the exact graph. Concept mappings come
    directly from that graph. Their Rulespec meaning is accepted only through
    the matching ``ReleaseGraphValidationReceipt``; this reader does not
    revalidate it.
    """

    _release_id: str
    _rulespec_graph_id: str
    _rulespec_graph: Mapping[str, Any]
    _expression_corpus_snapshot: Mapping[str, str]
    _members: Mapping[str, ManagedReleaseMember]
    _expressions: tuple[ManagedReleaseExpression, ...]
    _relations: tuple[ManagedReleaseRelation, ...]
    _lifecycle_participants: tuple[
        ManagedReleaseLifecycleParticipant,
        ...,
    ]
    _concept_mappings: tuple[ManagedReleaseConceptMapping, ...]
    _release_graph_validation_receipt: Mapping[str, Any]
    _source_artifacts: Mapping[str, bytes] = dataclass_field(
        default_factory=lambda: MappingProxyType({})
    )
    _records_by_id: Mapping[str, Mapping[str, Any]] = dataclass_field(
        default_factory=lambda: MappingProxyType({})
    )

    usage_ceiling = "candidateUseOnly"

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
        _graph_facts_only: bool = False,
    ) -> ManagedReleaseView | ManagedReleaseGraphFactsView:
        """Verify and open the exact externally selected bundle manifest."""

        expected_manifest_digest = _require_digest(
            expected_manifest_digest,
            "expected_manifest_digest",
        )
        manifest_file = Path(manifest_path)
        if manifest_file.is_symlink():
            raise ManagedReleaseError("bundle manifest must not be a symlink")
        try:
            manifest_file = manifest_file.resolve(strict=True)
        except FileNotFoundError as error:
            raise ManagedReleaseError("bundle manifest does not exist") from error
        if not manifest_file.is_file():
            raise ManagedReleaseError("bundle manifest must be a regular file")
        manifest_bytes = manifest_file.read_bytes()
        actual_manifest_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
        if actual_manifest_digest != expected_manifest_digest:
            raise ManagedReleaseError(
                f"bundle manifest digest mismatch: expected {expected_manifest_digest}, got {actual_manifest_digest}"
            )
        manifest = _json_from_bytes(
            manifest_bytes,
            "bundle manifest",
        )
        required = {
            "bundleVersion",
            "publicationReleaseManifest",
            "refRecords",
            "rulespecGraph",
            "rulespecGraphId",
            "rulespecDependencyManifest",
            "combinedValidationReceipt",
            "normalizedTables",
            "indexedExpressionCorpus",
        }
        if not isinstance(manifest, dict) or set(manifest) - {
            *required,
            "lookupIndexManifest",
            "sourceArtifacts",
        }:
            raise ManagedReleaseError("bundle manifest contains unsupported fields")
        missing = required - set(manifest)
        if missing:
            raise ManagedReleaseError(
                f"bundle manifest omits required fields {sorted(missing)!r}"
            )
        if manifest.get("bundleVersion") != "1.0":
            raise ManagedReleaseError("bundleVersion must be '1.0'")

        root = manifest_file.parent.resolve()
        seen_paths: set[PurePosixPath] = set()
        raw_source_artifacts = manifest.get("sourceArtifacts", {})
        if not isinstance(raw_source_artifacts, dict):
            raise ManagedReleaseError(
                "sourceArtifacts must map distribution artifact IRIs to verified byte descriptors"
            )
        source_artifacts: dict[str, bytes] = {}
        source_artifact_facts: dict[str, tuple[str, int]] = {}
        for artifact_iri, descriptor in sorted(raw_source_artifacts.items()):
            if (
                not isinstance(artifact_iri, str)
                or _ABSOLUTE_IRI.fullmatch(artifact_iri) is None
            ):
                raise ManagedReleaseError(
                    "sourceArtifacts keys must be absolute distribution artifact IRIs"
                )
            if _graph_facts_only:
                source_artifact_facts[artifact_iri] = _verified_source_artifact_facts(
                    root,
                    descriptor,
                    f"sourceArtifacts[{artifact_iri!r}]",
                    seen_paths,
                )
            else:
                source_artifacts[artifact_iri] = _read_verified_source_artifact(
                    root,
                    descriptor,
                    f"sourceArtifacts[{artifact_iri!r}]",
                    seen_paths,
                )
        publication_bytes = _read_verified_artifact(
            root,
            manifest["publicationReleaseManifest"],
            "publicationReleaseManifest",
            seen_paths,
        )
        publication = _json_from_bytes(
            publication_bytes,
            "publicationReleaseManifest",
        )
        if (
            not isinstance(publication, dict)
            or publication.get("type") != _PUBLICATION_TYPE
        ):
            raise ManagedReleaseError(
                "publicationReleaseManifest artifact must contain one PublicationReleaseManifest"
            )
        publication_id, publication_digest = _record_digest_reference(
            publication,
            "publicationReleaseManifest",
        )
        if (
            publication.get("releaseState") != "complete"
            or publication.get("consumerEligible") is not True
        ):
            raise ManagedReleaseError(
                "publication release is not complete and consumer eligible"
            )

        ref_descriptors = manifest.get("refRecords")
        if not isinstance(ref_descriptors, list) or not ref_descriptors:
            raise ManagedReleaseError("refRecords must name one or more record files")
        ref_records: list[dict[str, Any]] = []
        for index, descriptor in enumerate(ref_descriptors):
            payload = _read_verified_artifact(
                root,
                descriptor,
                f"refRecords[{index}]",
                seen_paths,
            )
            record = _json_from_bytes(payload, f"refRecords[{index}]")
            if not isinstance(record, dict):
                raise ManagedReleaseError(
                    f"refRecords[{index}] must contain one REF record object"
                )
            ref_records.append(record)

        _require_binding_valid(
            [publication, *ref_records],
            "publication and linked REF records",
        )

        records_by_id: dict[str, dict[str, Any]] = {publication_id: publication}
        actual_operational_refs: set[tuple[str, str]] = set()
        for index, record in enumerate(ref_records):
            identifier, digest = _record_digest_reference(
                record,
                f"refRecords[{index}]",
            )
            if identifier in records_by_id:
                raise ManagedReleaseError(
                    f"REF record identifier {identifier!r} is repeated"
                )
            records_by_id[identifier] = record
            actual_operational_refs.add((identifier, digest))

        required_source_captures = [
            record
            for record in ref_records
            if record.get("type") == "urn:ref:type:Capture"
            and record.get("acquisitionStatus") == "success"
            and record.get("contentPreservation") == "exactBytes"
        ]
        storage_reference_list: list[str] = []
        for record in required_source_captures:
            storage_reference = record.get("storageReference")
            if not isinstance(storage_reference, str):
                raise ManagedReleaseError(
                    f"Capture {record.get('id')!r} lacks an exact storageReference"
                )
            storage_reference_list.append(storage_reference)
        storage_references = set(storage_reference_list)
        if len(storage_references) != len(storage_reference_list):
            raise ManagedReleaseError(
                "multiple successful exact-byte Captures resolve the same source artifact"
            )
        packaged_source_ids = (
            set(source_artifact_facts) if _graph_facts_only else set(source_artifacts)
        )
        if storage_references != packaged_source_ids:
            raise ManagedReleaseError(
                "sourceArtifacts keys must exactly equal successful exact-byte Capture.storageReference values"
            )
        for record in required_source_captures:
            storage_reference = cast(
                str,
                record["storageReference"],
            )
            if _graph_facts_only:
                actual_digest, actual_length = source_artifact_facts[storage_reference]
            else:
                payload = source_artifacts[storage_reference]
                actual_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
                actual_length = len(payload)
            if (
                record.get("byteDigest") != actual_digest
                or record.get("byteLength") != actual_length
            ):
                raise ManagedReleaseError(
                    f"Capture {record.get('id')!r} does not match its exact packaged source artifact bytes"
                )

        declared_operational = publication.get("refOperationalRecords")
        if not isinstance(declared_operational, list):
            raise ManagedReleaseError(
                "PublicationReleaseManifest.refOperationalRecords must be an array"
            )
        declared_operational_refs = {
            _reference_key(
                _require_digest_reference(
                    value,
                    f"PublicationReleaseManifest.refOperationalRecords[{index}]",
                )
            )
            for index, value in enumerate(declared_operational)
        }
        if len(declared_operational_refs) != len(declared_operational):
            raise ManagedReleaseError(
                "PublicationReleaseManifest.refOperationalRecords repeats a reference"
            )
        if declared_operational_refs != actual_operational_refs:
            raise ManagedReleaseError(
                "linked REF records do not exactly match PublicationReleaseManifest.refOperationalRecords"
            )

        for owner in (publication, *ref_records):
            owner_id = str(owner.get("id", "<unknown>"))
            for reference in _iter_nested_references(owner, top_level=True):
                target = records_by_id.get(reference.get("id"))
                if target is None:
                    continue
                expected = target.get(binding.digest_field(target))
                if reference.get("digest") != expected:
                    raise ManagedReleaseError(
                        f"{owner_id} carries a digest-mismatched REF reference to {reference.get('id')!r}"
                    )
                if "version" in reference and reference.get("version") != target.get(
                    "version"
                ):
                    raise ManagedReleaseError(
                        f"{owner_id} carries a version-mismatched REF reference to {reference.get('id')!r}"
                    )
            for reference in _iter_named_values(
                owner,
                "registryImportSnapshot",
            ):
                _resolve_import_snapshot(
                    reference,
                    records_by_id=records_by_id,
                    label=f"{owner_id}.registryImportSnapshot",
                )

        run_receipt = _require_digest_reference(
            publication.get("runReceipt"),
            "PublicationReleaseManifest.runReceipt",
        )
        if _reference_key(run_receipt) not in actual_operational_refs:
            raise ManagedReleaseError(
                "PublicationReleaseManifest.runReceipt does not resolve to one linked REF record"
            )
        run_receipt_record = records_by_id[run_receipt["id"]]
        if run_receipt_record.get("type") != "urn:ref:type:RunReceipt":
            raise ManagedReleaseError(
                "PublicationReleaseManifest.runReceipt must resolve to a RunReceipt"
            )

        dependency_bytes = _read_verified_artifact(
            root,
            manifest["rulespecDependencyManifest"],
            "rulespecDependencyManifest",
            seen_paths,
        )
        dependency_manifest = _json_from_bytes(
            dependency_bytes,
            "rulespecDependencyManifest",
        )
        if not isinstance(dependency_manifest, dict):
            raise ManagedReleaseError(
                "rulespecDependencyManifest must contain one JSON object"
            )
        dependency_digest = "sha256:" + hashlib.sha256(dependency_bytes).hexdigest()
        if (
            dependency_digest != RULESPEC_DEPENDENCY_SHA256
            or dependency_bytes != RULESPEC_DEPENDENCY_BYTES
        ):
            raise ManagedReleaseError(
                "rulespecDependencyManifest is not the exact RefSpec-embedded Rulespec dependency"
            )
        declared_dependency = cast(
            Mapping[str, Any],
            publication["rulespecDependency"],
        )
        expected_dependency_fields = {
            "version": dependency_manifest.get("rulespecVersion"),
            "releaseAvailability": dependency_manifest.get("releaseAvailability"),
        }
        for field_name, expected in expected_dependency_fields.items():
            if declared_dependency.get(field_name) != expected:
                raise ManagedReleaseError(
                    "PublicationReleaseManifest.rulespecDependency."
                    f"{field_name} does not match the embedded dependency "
                    "manifest"
                )
        expected_validator = _dependency_validator_pin(dependency_manifest)
        expected_behavior_runtime = _dependency_behavior_runtime_pin(
            dependency_manifest
        )
        expected_gate = _installed_release_graph_gate_pin()
        if declared_dependency.get("validator") != expected_validator:
            raise ManagedReleaseError(
                "PublicationReleaseManifest.rulespecDependency.validator "
                "does not match the embedded dependency manifest"
            )

        graph_bytes = _read_verified_artifact(
            root,
            manifest["rulespecGraph"],
            "rulespecGraph",
            seen_paths,
        )
        graph = _json_from_bytes(graph_bytes, "rulespecGraph")
        combined_receipt_bytes = _read_verified_artifact(
            root,
            manifest["combinedValidationReceipt"],
            "combinedValidationReceipt",
            seen_paths,
        )
        combined_receipt = _json_from_bytes(
            combined_receipt_bytes,
            "combinedValidationReceipt",
        )
        graph_reference = _require_digest_reference(
            publication.get("rulespecReleaseGraph"),
            "PublicationReleaseManifest.rulespecReleaseGraph",
        )
        graph_id = manifest.get("rulespecGraphId")
        if not isinstance(graph_id, str) or not _ABSOLUTE_IRI.fullmatch(graph_id):
            raise ManagedReleaseError(
                "rulespecGraphId must be an external absolute graph identifier"
            )
        if graph_reference["id"] != graph_id:
            raise ManagedReleaseError(
                "external rulespecGraphId does not match PublicationReleaseManifest.rulespecReleaseGraph"
            )
        if not isinstance(graph, dict) or "@id" in graph:
            raise ManagedReleaseError(
                "rulespecGraph must remain a default-graph JSON-LD document without a top-level @id"
            )
        if rulespec_graph_digest(graph) != graph_reference["digest"]:
            raise ManagedReleaseError(
                "exact Rulespec graph digest does not match PublicationReleaseManifest.rulespecReleaseGraph"
            )
        graph_identifiers = defined_rulespec_identifiers(graph)
        if not graph_identifiers:
            raise ManagedReleaseError("exact Rulespec graph defines no identifiers")
        nodes = _rulespec_nodes(graph)
        member_release, member_scheme = _release_membership(nodes)

        raw_tables = manifest.get("normalizedTables")
        if not isinstance(raw_tables, list):
            raise ManagedReleaseError("normalizedTables must be an array")
        table_bytes: dict[str, bytes] = {}
        table_names: set[str] = set()
        for index, descriptor in enumerate(raw_tables):
            if not isinstance(descriptor, dict) or set(descriptor) != {
                "name",
                "path",
                "sha256",
            }:
                raise ManagedReleaseError(
                    f"normalizedTables[{index}] must name one table, path, and digest"
                )
            name = descriptor.get("name")
            if name not in _TABLE_COLUMNS or name in table_names:
                raise ManagedReleaseError(
                    f"normalizedTables[{index}].name is unknown or repeated"
                )
            table_names.add(str(name))
            artifact_descriptor = {
                "path": descriptor.get("path"),
                "sha256": descriptor.get("sha256"),
            }
            if _graph_facts_only:
                _verified_artifact_path(
                    root,
                    artifact_descriptor,
                    f"normalizedTables[{index}]",
                    seen_paths,
                )
            else:
                table_bytes[str(name)] = _read_verified_artifact(
                    root,
                    artifact_descriptor,
                    f"normalizedTables[{index}]",
                    seen_paths,
                )
        if table_names != set(_TABLE_COLUMNS):
            raise ManagedReleaseError(
                "normalizedTables must contain the three exact RefSpec tables"
            )

        if _graph_facts_only:
            corpus = _verified_expression_corpus_descriptor(
                root=root,
                manifest=manifest,
                publication=publication,
                seen_paths=seen_paths,
            )
            validated_receipt = _validate_combined_receipt(
                combined_receipt=combined_receipt,
                graph_reference=graph_reference,
                dependency_digest=dependency_digest,
                publication_id=publication_id,
                publication_digest=publication_digest,
                actual_operational_refs=actual_operational_refs,
                expected_validator=expected_validator,
                expected_behavior_runtime=expected_behavior_runtime,
                expected_gate=expected_gate,
                graph_identifiers=set(graph_identifiers),
                ref_records=ref_records,
            )
            frozen_graph = cast(
                Mapping[str, Any],
                _freeze(graph),
            )
            frozen_nodes = {
                cast(str, node["@id"]): cast(Mapping[str, Any], node)
                for node in cast(
                    Sequence[Mapping[str, Any]],
                    frozen_graph["@graph"],
                )
            }
            members = {
                member: ManagedReleaseMember(
                    member_iri=member,
                    release_iri=release,
                    scheme_iri=member_scheme[member],
                    record=frozen_nodes[member],
                )
                for member, release in member_release.items()
            }
            return ManagedReleaseGraphFactsView(
                _release_id=publication_id,
                _rulespec_graph_id=graph_id,
                _rulespec_graph=frozen_graph,
                _expression_corpus_snapshot=cast(
                    Mapping[str, str],
                    _freeze(corpus.snapshot),
                ),
                _members=MappingProxyType(members),
                _release_graph_validation_receipt=cast(
                    Mapping[str, Any],
                    _freeze(validated_receipt),
                ),
            )
        tables: dict[str, tuple[Mapping[str, Any], ...]] = {}
        for name, payload in table_bytes.items():
            try:
                table = pq.read_table(pa.BufferReader(payload))
            except (OSError, pa.ArrowException) as error:
                raise ManagedReleaseError(
                    f"normalized table {name!r} is not readable Parquet"
                ) from error
            expected_columns = tuple(_TABLE_COLUMNS[name])
            if tuple(table.column_names) != expected_columns:
                raise ManagedReleaseError(
                    f"normalized table {name!r} columns do not match RefSpec"
                )
            if any(not pa.types.is_string(field.type) for field in table.schema):
                raise ManagedReleaseError(
                    f"normalized table {name!r} must use the RefSpec all-string physical schema"
                )
            tables[name] = tuple(
                cast(Mapping[str, Any], _freeze(row)) for row in table.to_pylist()
            )
            for row_index, row in enumerate(tables[name]):
                for field in _TABLE_REQUIRED_TEXT_COLUMNS[name]:
                    value = row.get(field)
                    if not isinstance(value, str) or not value:
                        raise ManagedReleaseError(
                            f"normalized table {name}[{row_index}].{field} must be non-empty text"
                        )

        try:
            normalized_labels = tuple(
                _NormalizedLabelRow(
                    label_id=_required_table_text(
                        row,
                        "label_id",
                        table="concept_labels",
                    ),
                    concept_iri=_required_table_text(
                        row,
                        "concept_iri",
                        table="concept_labels",
                    ),
                    scheme_iri=_required_table_text(
                        row,
                        "scheme_iri",
                        table="concept_labels",
                    ),
                    release_iri=_required_table_text(
                        row,
                        "release_iri",
                        table="concept_labels",
                    ),
                    import_snapshot_id=_required_table_text(
                        row,
                        "import_snapshot_id",
                        table="concept_labels",
                    ),
                    distribution_artifact_id=_required_table_text(
                        row,
                        "distribution_artifact_id",
                        table="concept_labels",
                    ),
                    source_property_iri=_required_table_text(
                        row,
                        "source_property_iri",
                        table="concept_labels",
                    ),
                    label_role=_required_table_text(
                        row,
                        "label_role",
                        table="concept_labels",
                    ),
                    original_literal=_required_table_text(
                        row,
                        "original_literal",
                        table="concept_labels",
                    ),
                    language_tag=_required_table_text(
                        row,
                        "language_tag",
                        table="concept_labels",
                    ),
                    source_status=_required_table_text(
                        row,
                        "status",
                        table="concept_labels",
                    ),
                    expression_id=_required_table_text(
                        row,
                        "expression_id",
                        table="concept_labels",
                    ),
                    migration_only=_table_bool(
                        row,
                        "migration_only",
                    ),
                )
                for row in tables["concept_labels"]
            )
            normalized_relations = tuple(
                _NormalizedRelationRow(
                    relation_id=_required_table_text(
                        row,
                        "relation_id",
                        table="concept_relations",
                    ),
                    release_iri=_required_table_text(
                        row,
                        "release_iri",
                        table="concept_relations",
                    ),
                    import_snapshot_id=_required_table_text(
                        row,
                        "import_snapshot_id",
                        table="concept_relations",
                    ),
                    distribution_artifact_id=_required_table_text(
                        row,
                        "distribution_artifact_id",
                        table="concept_relations",
                    ),
                    subject_concept_iri=_required_table_text(
                        row,
                        "subject_concept_iri",
                        table="concept_relations",
                    ),
                    subject_scheme_iri=_required_table_text(
                        row,
                        "subject_scheme_iri",
                        table="concept_relations",
                    ),
                    predicate_iri=_required_table_text(
                        row,
                        "predicate_iri",
                        table="concept_relations",
                    ),
                    object_concept_iri=_required_table_text(
                        row,
                        "object_concept_iri",
                        table="concept_relations",
                    ),
                    object_scheme_iri=_required_table_text(
                        row,
                        "object_scheme_iri",
                        table="concept_relations",
                    ),
                    migration_only=_table_bool(
                        row,
                        "migration_only",
                    ),
                )
                for row in tables["concept_relations"]
            )
            normalized_participants = tuple(
                _NormalizedParticipantRow(
                    event_id=_required_table_text(
                        row,
                        "event_id",
                        table="concept_event_participants",
                    ),
                    operation=_required_table_text(
                        row,
                        "operation",
                        table="concept_event_participants",
                    ),
                    participant_role=_required_table_text(
                        row,
                        "participant_role",
                        table="concept_event_participants",
                    ),
                    concept_iri=_required_table_text(
                        row,
                        "concept_iri",
                        table="concept_event_participants",
                    ),
                    concept_type_iri=_required_table_text(
                        row,
                        "concept_type_iri",
                        table="concept_event_participants",
                    ),
                    release_iri=_required_table_text(
                        row,
                        "release_iri",
                        table="concept_event_participants",
                    ),
                    complete_membership=_table_bool(
                        row,
                        "complete_membership",
                    ),
                    ordinal=_table_ordinal(row, "ordinal"),
                    migration_only=_table_bool(
                        row,
                        "migration_only",
                    ),
                )
                for row in tables["concept_event_participants"]
            )
        except (ManagedReleaseError, TypeError) as error:
            raise ManagedReleaseError(
                f"normalized vocabulary tables are invalid: {error}"
            ) from error
        all_normalized_rows = (
            *normalized_labels,
            *normalized_relations,
            *normalized_participants,
        )
        if any(row.migration_only for row in all_normalized_rows):
            raise ManagedReleaseError(
                "managed release tables cannot contain migration-only rows"
            )
        label_ids = [row.label_id for row in normalized_labels]
        relation_ids = [row.relation_id for row in normalized_relations]
        participant_keys = [
            (row.event_id, row.participant_role, row.ordinal)
            for row in normalized_participants
        ]
        if len(label_ids) != len(set(label_ids)):
            raise ManagedReleaseError("concept_labels repeats a label row identifier")
        if len(relation_ids) != len(set(relation_ids)):
            raise ManagedReleaseError(
                "concept_relations repeats a relation row identifier"
            )
        if len(participant_keys) != len(set(participant_keys)):
            raise ManagedReleaseError(
                "concept_event_participants repeats an event role ordinal"
            )
        normalized_label_by_expression_id: dict[
            str,
            _NormalizedLabelRow,
        ] = {}
        for row in normalized_labels:
            normalized_label_by_expression_id.setdefault(
                row.expression_id,
                row,
            )

        corpus = _verified_expression_corpus_descriptor(
            root=root,
            manifest=manifest,
            publication=publication,
            seen_paths=seen_paths,
        )
        corpus_path = corpus.path
        corpus_record_count = corpus.record_count
        corpus_identity_digest = corpus.identity_digest
        corpus_snapshot = dict(corpus.snapshot)
        publication_snapshot = dict(corpus.snapshot)
        expressions: list[ManagedReleaseExpression] = []
        expression_records_by_id: dict[str, Mapping[str, Any]] = {}
        try:
            expression_validator = binding.IndexedExpressionCorpusValidator()
        except (OSError, TypeError, ValueError) as error:
            raise ManagedReleaseError(
                f"indexed expression corpus validator could not be loaded: {error}"
            ) from error
        expression_diagnostics: list[binding.Diagnostic] = []
        with corpus_path.open("rb") as corpus_stream:
            for line_number, raw_line in enumerate(
                corpus_stream,
                start=1,
            ):
                if not raw_line.strip():
                    raise ManagedReleaseError(
                        f"indexedExpressionCorpus line {line_number} is empty"
                    )
                value = _json_from_bytes(
                    raw_line,
                    f"indexedExpressionCorpus line {line_number}",
                )
                if not isinstance(value, dict) or value.get("type") != _EXPRESSION_TYPE:
                    raise ManagedReleaseError(
                        f"indexedExpressionCorpus line {line_number} is not an IndexedVocabularyExpression"
                    )
                expression_id, _ = _record_digest_reference(
                    value,
                    f"indexedExpressionCorpus line {line_number}",
                )
                if expression_id in expression_records_by_id:
                    raise ManagedReleaseError(
                        f"indexedExpressionCorpus repeats {expression_id!r}"
                    )
                expression_snapshot = _require_digest_reference(
                    value.get("expressionCorpusSnapshot"),
                    f"{expression_id}.expressionCorpusSnapshot",
                )
                if expression_snapshot != corpus_snapshot:
                    raise ManagedReleaseError(
                        f"{expression_id} belongs to a different expression corpus"
                    )
                member = value.get("member")
                if not isinstance(member, str) or member not in member_release:
                    raise ManagedReleaseError(
                        f"{expression_id} does not identify an exact release member"
                    )
                release = value.get("referenceResourceRelease")
                if (
                    not isinstance(release, dict)
                    or release.get("id") != member_release[member]
                ):
                    raise ManagedReleaseError(
                        f"{expression_id} release does not contain its member"
                    )
                release_node = nodes[member_release[member]]
                if release.get("version") != release_node.get(
                    "dcat:version"
                ) or release.get("digest") != release_node.get(
                    "rkaf:referenceReleaseDigest"
                ):
                    raise ManagedReleaseError(
                        f"{expression_id} release version or digest does not match the exact Rulespec release"
                    )
                if value.get("scheme") != member_scheme[member]:
                    raise ManagedReleaseError(
                        f"{expression_id} scheme does not match its exact member"
                    )
                import_reference = value.get("registryImportSnapshot")
                _resolve_import_snapshot(
                    import_reference,
                    records_by_id=records_by_id,
                    label=(f"{expression_id}.registryImportSnapshot"),
                )
                distribution_reference = value.get("distributionArtifact")
                if (
                    not isinstance(import_reference, Mapping)
                    or not isinstance(
                        distribution_reference,
                        Mapping,
                    )
                    or not isinstance(
                        import_reference.get("id"),
                        str,
                    )
                    or not isinstance(
                        distribution_reference.get("id"),
                        str,
                    )
                ):
                    raise ManagedReleaseError(
                        f"{expression_id} import or distribution reference is invalid"
                    )
                _require_import_lineage(
                    import_snapshot_id=str(import_reference["id"]),
                    release_iri=member_release[member],
                    distribution_artifact_id=str(distribution_reference["id"]),
                    records_by_id=records_by_id,
                    label=expression_id,
                )
                indexed_text = value.get("indexedText")
                original_literal = value.get("originalLiteral")
                if not isinstance(indexed_text, str) or not indexed_text:
                    raise ManagedReleaseError(
                        f"{expression_id}.indexedText is required"
                    )
                if value.get("indexedTextDigest") != binding.text_digest(indexed_text):
                    raise ManagedReleaseError(
                        f"{expression_id}.indexedTextDigest does not match"
                    )
                if not isinstance(original_literal, str) or not original_literal:
                    raise ManagedReleaseError(
                        f"{expression_id}.originalLiteral is required"
                    )
                source = value.get(
                    "sourceProperty",
                    value.get("sourcePath"),
                )
                if not isinstance(source, str) or not source:
                    raise ManagedReleaseError(
                        f"{expression_id} has no source property or path"
                    )
                semantic_property = value.get("semanticProperty")
                if not isinstance(semantic_property, str) or not semantic_property:
                    raise ManagedReleaseError(
                        f"{expression_id}.semanticProperty is required"
                    )
                language = value.get("language")
                if language is not None and not isinstance(language, str):
                    raise ManagedReleaseError(f"{expression_id}.language is invalid")
                normalized_label = normalized_label_by_expression_id.get(expression_id)
                frozen_record = cast(
                    Mapping[str, Any],
                    _freeze(value),
                )
                expression_diagnostics.extend(
                    expression_validator.validate_record(value)
                )
                expression_records_by_id[expression_id] = frozen_record
                expressions.append(
                    ManagedReleaseExpression(
                        expression_id=expression_id,
                        member_iri=member,
                        indexed_text=indexed_text,
                        original_literal=original_literal,
                        language_tag=language,
                        semantic_property_iri=semantic_property,
                        source_property_or_path=source,
                        record=frozen_record,
                        label_role=(
                            normalized_label.label_role
                            if normalized_label is not None
                            else None
                        ),
                        source_status=(
                            normalized_label.source_status
                            if normalized_label is not None
                            else None
                        ),
                    )
                )

        if len(expression_records_by_id) != corpus_record_count:
            raise ManagedReleaseError(
                f"indexedExpressionCorpus.recordCount does not match the {len(expression_records_by_id)} parsed records"
            )
        try:
            actual_corpus_identity_digest = indexed_expression_id_set_digest(
                expression_records_by_id
            )
            for expression_id, record in expression_records_by_id.items():
                identity = indexed_expression_identity_from_record(record)
                expected_id = (
                    "urn:ref:indexed-expression:"
                    + hashlib.sha256(
                        canonical_json(identity).encode("utf-8")
                    ).hexdigest()
                )
                if expression_id != expected_id:
                    raise ManagedReleaseError(
                        "indexed expression id does not bind its exact "
                        f"identity: expected {expected_id}, got "
                        f"{expression_id}"
                    )
        except (OSError, ReferenceRuntimeError, TypeError, ValueError) as error:
            raise ManagedReleaseError(
                f"indexed expression corpus could not be validated: {error}"
            ) from error
        if expression_diagnostics:
            rendered = "; ".join(
                diagnostic.render() for diagnostic in expression_diagnostics
            )
            raise ManagedReleaseError(
                f"indexed expression corpus fails REF JSON Binding 1.0: {rendered}"
            )
        if actual_corpus_identity_digest != corpus_identity_digest:
            raise ManagedReleaseError(
                "indexedExpressionCorpus canonical identity digest does not match its records"
            )

        combined_receipt = _validate_combined_receipt(
            combined_receipt=combined_receipt,
            graph_reference=graph_reference,
            dependency_digest=dependency_digest,
            publication_id=publication_id,
            publication_digest=publication_digest,
            actual_operational_refs=actual_operational_refs,
            expected_validator=expected_validator,
            expected_behavior_runtime=expected_behavior_runtime,
            expected_gate=expected_gate,
            graph_identifiers=set(graph_identifiers),
            ref_records=ref_records,
        )

        graph_property_index = _index_graph_property_targets(nodes)
        referenced_label_expressions: set[str] = set()
        for index, row in enumerate(normalized_labels):
            if row.concept_iri not in member_release:
                raise ManagedReleaseError(
                    f"concept_labels[{index}] does not identify an exact member"
                )
            if (
                row.release_iri != member_release[row.concept_iri]
                or row.scheme_iri != member_scheme[row.concept_iri]
            ):
                raise ManagedReleaseError(
                    f"concept_labels[{index}] release or scheme does not match the exact member"
                )
            property_name = _LABEL_PROPERTIES.get(row.source_property_iri)
            if property_name is None:
                raise ManagedReleaseError(
                    f"concept_labels[{index}] source property cannot be matched to the exact Rulespec graph"
                )
            if row.label_role != _LABEL_ROLES[row.source_property_iri]:
                raise ManagedReleaseError(
                    f"concept_labels[{index}] label role disagrees with its exact SKOS property"
                )
            _require_import_lineage(
                import_snapshot_id=row.import_snapshot_id,
                release_iri=row.release_iri,
                distribution_artifact_id=row.distribution_artifact_id,
                records_by_id=records_by_id,
                label=f"concept_labels[{index}]",
            )
            if (
                row.concept_iri,
                property_name,
                row.language_tag,
                row.original_literal,
            ) not in graph_property_index.language_literals:
                raise ManagedReleaseError(
                    f"concept_labels[{index}] does not round-trip to the exact Rulespec member graph"
                )
            expression_record = expression_records_by_id.get(row.expression_id)
            if expression_record is None:
                raise ManagedReleaseError(
                    f"concept_labels[{index}] references a missing indexed expression"
                )
            if row.expression_id in referenced_label_expressions:
                raise ManagedReleaseError(
                    f"concept_labels[{index}] reuses an indexed expression"
                )
            referenced_label_expressions.add(row.expression_id)
            import_snapshot = expression_record.get("registryImportSnapshot")
            distribution = expression_record.get("distributionArtifact")
            expression_semantic_property = expression_record.get("semanticProperty")
            if (
                expression_record.get("member") != row.concept_iri
                or expression_record.get("scheme") != row.scheme_iri
                or expression_semantic_property != row.source_property_iri
                or expression_record.get("originalLiteral") != row.original_literal
                or expression_record.get("language") != row.language_tag
                or not isinstance(import_snapshot, Mapping)
                or import_snapshot.get("id") != row.import_snapshot_id
                or not isinstance(distribution, Mapping)
                or distribution.get("id") != row.distribution_artifact_id
            ):
                raise ManagedReleaseError(
                    f"concept_labels[{index}] does not match its exact indexed expression"
                )
        for index, row in enumerate(normalized_relations):
            _require_import_lineage(
                import_snapshot_id=row.import_snapshot_id,
                release_iri=row.release_iri,
                distribution_artifact_id=row.distribution_artifact_id,
                records_by_id=records_by_id,
                label=f"concept_relations[{index}]",
            )
            for field, concept_iri in (
                ("subject_concept_iri", row.subject_concept_iri),
                ("object_concept_iri", row.object_concept_iri),
            ):
                if concept_iri not in member_release:
                    raise ManagedReleaseError(
                        f"concept_relations[{index}].{field} is not an exact member"
                    )
            if (
                member_release[row.subject_concept_iri] != row.release_iri
                or member_release[row.object_concept_iri] != row.release_iri
            ):
                raise ManagedReleaseError(
                    f"concept_relations[{index}] release does not contain both endpoints"
                )
            if (
                member_scheme[row.subject_concept_iri] != row.subject_scheme_iri
                or member_scheme[row.object_concept_iri] != row.object_scheme_iri
            ):
                raise ManagedReleaseError(
                    f"concept_relations[{index}] scheme fields do not match the exact member graph"
                )
            property_name = _RELATION_PROPERTIES.get(row.predicate_iri)
            if property_name is None:
                raise ManagedReleaseError(
                    f"concept_relations[{index}] predicate cannot be matched to the exact Rulespec graph"
                )
            if (
                row.object_concept_iri
                not in graph_property_index.iri_targets[
                    (row.subject_concept_iri, property_name)
                ]
            ):
                raise ManagedReleaseError(
                    f"concept_relations[{index}] does not round-trip to the exact Rulespec member graph"
                )

        for index, row in enumerate(normalized_participants):
            event = nodes.get(row.event_id)
            if event is None or not (_node_types(event) & _LIFECYCLE_TYPES):
                raise ManagedReleaseError(
                    f"concept_event_participants[{index}] event is absent from the exact Rulespec graph"
                )
            if (
                row.concept_iri not in member_release
                or member_release[row.concept_iri] != row.release_iri
                or row.complete_membership is not True
            ):
                raise ManagedReleaseError(
                    f"concept_event_participants[{index}] does not identify one exact complete-release member"
                )
            member_types = _node_types(nodes[row.concept_iri])
            if not (member_types & _type_spellings(row.concept_type_iri)):
                raise ManagedReleaseError(
                    f"concept_event_participants[{index}] concept type does not match the exact member graph"
                )
            operation = re.split(
                r"[:/#]",
                str(event.get("rkaf:conceptLifecycleOperation", "")),
            )[-1]
            if operation != row.operation:
                raise ManagedReleaseError(
                    f"concept_event_participants[{index}] operation does not match its Rulespec event"
                )
            if row.participant_role == "predecessor":
                concept_property = "rkaf:predecessorConcepts"
                release_property = "rkaf:predecessorConceptRelease"
            elif row.participant_role == "successor":
                concept_property = "rkaf:successorConcepts"
                release_property = "rkaf:successorConceptRelease"
            else:
                raise ManagedReleaseError(
                    f"concept_event_participants[{index}] participant role "
                    "cannot be matched to the exact Rulespec graph"
                )
            if row.concept_iri not in graph_property_index.iri_targets[
                (row.event_id, concept_property)
            ] or graph_property_index.iri_sequences[
                (row.event_id, release_property)
            ] != (
                row.release_iri,
            ):
                raise ManagedReleaseError(
                    f"concept_event_participants[{index}] does not round-trip to its exact Rulespec event"
                )

        managed_relations = tuple(
            ManagedReleaseRelation(
                relation_id=row.relation_id,
                subject_member_iri=row.subject_concept_iri,
                predicate_iri=row.predicate_iri,
                object_member_iri=row.object_concept_iri,
                release_iri=row.release_iri,
                record=raw,
            )
            for row, raw in zip(
                normalized_relations,
                tables["concept_relations"],
                strict=True,
            )
        )
        managed_participants = tuple(
            ManagedReleaseLifecycleParticipant(
                event_iri=row.event_id,
                operation=row.operation,
                participant_role=row.participant_role,
                member_iri=row.concept_iri,
                release_iri=row.release_iri,
                ordinal=row.ordinal,
                record=raw,
            )
            for row, raw in zip(
                normalized_participants,
                tables["concept_event_participants"],
                strict=True,
            )
        )
        managed_mappings: list[ManagedReleaseConceptMapping] = []
        for mapping_iri, node in nodes.items():
            if not (_node_types(node) & _CONCEPT_MAPPING_TYPES):
                continue
            exact_values = {
                field: _iri_values(node.get(field))
                for field in (
                    "rkaf:assertsSubject",
                    "rkaf:assertsPredicate",
                    "rkaf:assertsObject",
                    "rkaf:sourceConceptRelease",
                    "rkaf:targetConceptRelease",
                )
            }
            if any(len(values) != 1 for values in exact_values.values()):
                raise ManagedReleaseError(
                    f"ConceptMapping {mapping_iri!r} has an incomplete endpoint or relation"
                )
            source_member = exact_values["rkaf:assertsSubject"][0]
            target_member = exact_values["rkaf:assertsObject"][0]
            source_release = exact_values["rkaf:sourceConceptRelease"][0]
            target_release = exact_values["rkaf:targetConceptRelease"][0]
            if (
                member_release.get(source_member) != source_release
                or member_release.get(target_member) != target_release
            ):
                raise ManagedReleaseError(
                    f"ConceptMapping {mapping_iri!r} endpoint releases do not match exact complete membership"
                )
            managed_mappings.append(
                ManagedReleaseConceptMapping(
                    mapping_iri=mapping_iri,
                    source_member_iri=source_member,
                    relation_iri=exact_values["rkaf:assertsPredicate"][0],
                    target_member_iri=target_member,
                    source_release_iri=source_release,
                    target_release_iri=target_release,
                    record=cast(Mapping[str, Any], _freeze(node)),
                )
            )

        members = {
            member: ManagedReleaseMember(
                member_iri=member,
                release_iri=release,
                scheme_iri=member_scheme[member],
                record=cast(Mapping[str, Any], _freeze(nodes[member])),
            )
            for member, release in member_release.items()
        }
        return cls(
            _release_id=publication_id,
            _rulespec_graph_id=graph_id,
            _rulespec_graph=cast(
                Mapping[str, Any],
                _freeze(graph),
            ),
            _expression_corpus_snapshot=cast(
                Mapping[str, str],
                _freeze(publication_snapshot),
            ),
            _members=MappingProxyType(members),
            _expressions=tuple(expressions),
            _relations=managed_relations,
            _lifecycle_participants=managed_participants,
            _concept_mappings=tuple(managed_mappings),
            _release_graph_validation_receipt=cast(
                Mapping[str, Any],
                _freeze(combined_receipt),
            ),
            _source_artifacts=MappingProxyType(dict(source_artifacts)),
            _records_by_id=MappingProxyType(
                {
                    identifier: cast(
                        Mapping[str, Any],
                        _freeze(record),
                    )
                    for identifier, record in records_by_id.items()
                }
            ),
        )

    @property
    def release_id(self) -> str:
        return self._release_id

    @property
    def rulespec_graph_id(self) -> str:
        """Return the external identifier of the verified Rulespec graph."""

        return self._rulespec_graph_id

    @property
    def rulespec_graph(self) -> Mapping[str, Any]:
        """Return the exact immutable Rulespec JSON-LD graph."""

        return self._rulespec_graph

    @property
    def expression_corpus_snapshot(self) -> Mapping[str, str]:
        return self._expression_corpus_snapshot

    @property
    def release_graph_validation_receipt(self) -> Mapping[str, Any]:
        """Return the exact immutable receipt verified while opening the bundle."""

        return self._release_graph_validation_receipt

    def source_artifact_bytes(
        self,
        source_artifact_iri: str,
    ) -> bytes:
        """Return exact verified bytes by Capture.storageReference IRI."""

        try:
            return self._source_artifacts[source_artifact_iri]
        except KeyError as error:
            raise ManagedReleaseError(
                f"managed release has no packaged source artifact {source_artifact_iri!r}"
            ) from error

    def require_candidate_use(
        self,
        *,
        facet_iri: str,
        assignment_role_iri: str,
        resource_route: str,
    ) -> ManagedReleaseCandidatePermission:
        """Resolve one complete candidate-use row from the selected release.

        RefSpec owns this decision.  Consumers may request a tuple, but they
        cannot assemble values from separate rows or relabel release members
        with a caller-supplied facet.
        """

        for value, label in (
            (facet_iri, "facet_iri"),
            (assignment_role_iri, "assignment_role_iri"),
        ):
            if not isinstance(value, str) or not _ABSOLUTE_IRI.fullmatch(value):
                raise ManagedReleaseAuthorizationError(
                    f"{label} must be an absolute IRI"
                )
        if not isinstance(resource_route, str) or not resource_route:
            raise ManagedReleaseAuthorizationError(
                "resource_route must be non-empty text"
            )

        selected = [
            record
            for record in self._records_by_id.values()
            if record.get("type") == "urn:ref:type:RegistryDeploymentDecision"
            and record.get("selectionState") == "selected"
        ]
        if len(selected) != 1:
            raise ManagedReleaseAuthorizationError(
                "candidate use requires exactly one selected RegistryDeploymentDecision in the managed release"
            )
        deployment = selected[0]

        def resolve(
            reference: object,
            *,
            label: str,
            record_type: str,
        ) -> Mapping[str, Any]:
            if not isinstance(reference, Mapping):
                raise ManagedReleaseAuthorizationError(
                    f"{label} is not an exact record reference"
                )
            identifier = reference.get("id")
            record = (
                self._records_by_id.get(identifier)
                if isinstance(identifier, str)
                else None
            )
            if (
                record is None
                or record.get("type") != record_type
                or not binding.references_record(
                    dict(reference),
                    dict(record),
                )
            ):
                raise ManagedReleaseAuthorizationError(
                    f"{label} does not resolve to the exact selected {record_type}"
                )
            return record

        output_profile = resolve(
            deployment.get("outputProfile"),
            label="RegistryDeploymentDecision.outputProfile",
            record_type="urn:ref:type:OutputProfile",
        )
        enrichment_profile = resolve(
            output_profile.get("enrichmentProfile"),
            label="OutputProfile.enrichmentProfile",
            record_type="urn:ref:type:EnrichmentProfile",
        )
        coverage_report = resolve(
            deployment.get("coverageReport"),
            label="RegistryDeploymentDecision.coverageReport",
            record_type="urn:ref:type:RegistryImportCoverageReport",
        )

        facets = enrichment_profile.get("facets")
        facet_rows = (
            [
                row
                for row in facets
                if isinstance(row, Mapping) and row.get("iri") == facet_iri
            ]
            if isinstance(facets, Sequence)
            else []
        )
        if len(facet_rows) != 1:
            raise ManagedReleaseAuthorizationError(
                f"facet {facet_iri!r} is not defined exactly once by the selected EnrichmentProfile"
            )
        facet = facet_rows[0]
        if assignment_role_iri not in facet.get(
            "compatibleAssignmentPredicates",
            (),
        ):
            raise ManagedReleaseAuthorizationError(
                f"assignment role {assignment_role_iri!r} is incompatible with facet {facet_iri!r}"
            )
        if resource_route not in facet.get(
            "compatibleResourceRoutes",
            (),
        ):
            raise ManagedReleaseAuthorizationError(
                f"resource route {resource_route!r} is incompatible with facet {facet_iri!r}"
            )

        release_reference = deployment.get("referenceResourceRelease")
        import_reference = deployment.get("registryImportSnapshot")
        import_snapshot = resolve(
            import_reference,
            label="RegistryDeploymentDecision.registryImportSnapshot",
            record_type=_IMPORT_SNAPSHOT_TYPE,
        )
        if deployment.get("rightsAssessment") != import_snapshot.get(
            "rightsAssessment"
        ) or deployment.get("adoptedPolicyRefs") != import_snapshot.get(
            "adoptedPolicyRefs"
        ):
            raise ManagedReleaseAuthorizationError(
                "selected deployment rights and adopted policies differ from its exact import snapshot"
            )
        if import_snapshot.get("referenceResourceRelease") != release_reference:
            raise ManagedReleaseAuthorizationError(
                "selected import snapshot does not pin the deployment release"
            )
        permissions = output_profile.get("releasePermissions")
        matches = (
            [
                row
                for row in permissions
                if isinstance(row, Mapping)
                and row.get("facet") == facet_iri
                and row.get("assignmentRole") == assignment_role_iri
                and row.get("referenceResourceRelease") == release_reference
                and row.get("registryImportSnapshot") == import_reference
            ]
            if isinstance(permissions, Sequence)
            else []
        )
        if len(matches) != 1 or matches[0].get("candidateUse") is not True:
            raise ManagedReleaseAuthorizationError(
                "candidate authorization must match exactly one complete "
                "selected OutputProfile releasePermissions row with "
                "candidateUse=true"
            )
        permission = matches[0]

        if (
            coverage_report.get("reportStatus") != "pass"
            or coverage_report.get("outputProfile") != deployment.get("outputProfile")
            or coverage_report.get("referenceResourceRelease") != release_reference
            or coverage_report.get("registryImportSnapshot") != import_reference
        ):
            raise ManagedReleaseAuthorizationError(
                "candidate authorization requires the selected passing "
                "coverage report for the exact profile, release, and import"
            )
        required = permission.get("requiredImportFeatures")
        if (
            not isinstance(required, Sequence)
            or isinstance(required, (str, bytes))
            or not required
            or any(not isinstance(value, str) for value in required)
        ):
            raise ManagedReleaseAuthorizationError(
                "candidate permission has invalid requiredImportFeatures"
            )
        feature_rows = coverage_report.get("features")
        covered = (
            {
                row.get("feature"): row
                for row in feature_rows
                if isinstance(row, Mapping)
            }
            if isinstance(feature_rows, Sequence)
            else {}
        )
        missing_or_failed = [
            feature
            for feature in required
            if feature not in covered
            or covered[feature].get("requiredForCandidateOrOutput") is not True
            or covered[feature].get("failedCount") != 0
            or covered[feature].get("indexedCount")
            != covered[feature].get("parsedCount")
        ]
        if missing_or_failed:
            raise ManagedReleaseAuthorizationError(
                f"candidate permission lacks passing exact import coverage for {sorted(missing_or_failed)!r}"
            )

        return ManagedReleaseCandidatePermission(
            facet_iri=facet_iri,
            assignment_role_iri=assignment_role_iri,
            resource_route=resource_route,
            reference_resource_release=cast(
                Mapping[str, Any],
                _freeze(release_reference),
            ),
            registry_import_snapshot=cast(
                Mapping[str, Any],
                _freeze(import_reference),
            ),
            required_import_features=tuple(cast(Sequence[str], required)),
            permission_row=cast(
                Mapping[str, Any],
                _freeze(permission),
            ),
            output_profile=output_profile,
            enrichment_profile=enrichment_profile,
            coverage_report=coverage_report,
            registry_deployment=deployment,
        )

    def lookup_member(self, member_iri: str) -> ManagedReleaseMember | None:
        """Return one exact release member; no label or normalized lookup."""

        return self._members.get(member_iri)

    def iter_members(
        self,
        *,
        release_iri: str | None = None,
    ) -> Iterator[ManagedReleaseMember]:
        """Iterate exact members, optionally limited to one release."""

        for member in self._members.values():
            if release_iri is None or member.release_iri == release_iri:
                yield member

    def iter_identity_links(
        self,
        *,
        member_iri: str | None = None,
        predicate_iri: str | None = None,
    ) -> Iterator[ManagedReleaseIdentityLink]:
        """Iterate exact native identity, version, and replacement links.

        ``object_release_iri`` is present only when the object is another
        complete-release member in this managed view.  Stable source identity
        IRIs and links to releases outside the bundle remain exact, unresolved
        object IRIs.
        """

        seen: set[tuple[str, str, str]] = set()
        for member in self._members.values():
            if member_iri is not None and member.member_iri != member_iri:
                continue
            for (
                source_property,
                exact_predicate_iri,
            ) in _NATIVE_IDENTITY_PROPERTIES.items():
                if predicate_iri is not None and exact_predicate_iri != predicate_iri:
                    continue
                for object_iri in _iri_values(member.record.get(source_property)):
                    triple = (
                        member.member_iri,
                        exact_predicate_iri,
                        object_iri,
                    )
                    if triple in seen:
                        continue
                    seen.add(triple)
                    object_member = self._members.get(object_iri)
                    yield ManagedReleaseIdentityLink(
                        subject_member_iri=member.member_iri,
                        predicate_iri=exact_predicate_iri,
                        object_iri=object_iri,
                        subject_release_iri=member.release_iri,
                        object_release_iri=(
                            object_member.release_iri
                            if object_member is not None
                            else None
                        ),
                    )

    def iter_expressions(
        self,
        *,
        member_iri: str | None = None,
    ) -> Iterator[ManagedReleaseExpression]:
        """Iterate every immutable raw/evidence expression in corpus order."""

        for expression in self._expressions:
            if member_iri is None or expression.member_iri == member_iri:
                yield expression

    def iter_candidate_expressions(
        self,
        *,
        facet_iri: str,
        assignment_role_iri: str,
        resource_route: str,
        member_iri: str | None = None,
    ) -> Iterator[ManagedReleaseExpression]:
        """Iterate current-assignment expressions after exact authorization.

        Source status is opaque import data. The reference runtime applies only
        a conservative exclusion rule: canonical ``deprecated``, ``inactive``,
        and ``withdrawn`` tokens remove a concept from candidate iteration.
        More than one normalized status token for one concept is ambiguous and
        also removes that concept. An exact Rulespec lifecycle predecessor in a
        deprecation, withdrawal, replacement, split, or merge is also excluded.
        Promotion and demotion are not treated as retirement operations.
        Neither an unrecognized token nor a non-excluded token grants access;
        the exact selected candidate-use permission remains mandatory.
        Only expressions whose release and import references exactly match
        that permission are considered.
        """

        permission = self.require_candidate_use(
            facet_iri=facet_iri,
            assignment_role_iri=assignment_role_iri,
            resource_route=resource_route,
        )
        permission_expressions: list[tuple[ManagedReleaseExpression, str]] = []
        for expression in self._expressions:
            release_reference = expression.record.get("referenceResourceRelease")
            import_reference = expression.record.get("registryImportSnapshot")
            if (
                not isinstance(release_reference, Mapping)
                or not isinstance(import_reference, Mapping)
                or release_reference != permission.reference_resource_release
                or import_reference != permission.registry_import_snapshot
            ):
                continue
            release_iri = release_reference.get("id")
            if isinstance(release_iri, str):
                permission_expressions.append((expression, release_iri))
        statuses_by_member_release: dict[tuple[str, str], set[str]] = {}
        for expression, release_iri in permission_expressions:
            if expression.source_status is None:
                continue
            statuses_by_member_release.setdefault(
                (expression.member_iri, release_iri),
                set(),
            ).add(expression.source_status.strip().casefold())
        excluded_member_releases = {
            candidate_member_release
            for candidate_member_release, statuses in statuses_by_member_release.items()
            if (
                len(statuses) != 1
                or not statuses.isdisjoint(CANDIDATE_EXCLUDED_SOURCE_STATUSES)
            )
        }
        excluded_member_releases.update(
            (participant.member_iri, participant.release_iri)
            for participant in self._lifecycle_participants
            if (
                participant.participant_role == "predecessor"
                and participant.operation in _CURRENT_ASSIGNMENT_RETIRING_OPERATIONS
            )
        )
        import_snapshot_record = self._records_by_id.get(
            permission.registry_import_snapshot.get("id")
        )
        adopted_policy_refs = (
            import_snapshot_record.get("adoptedPolicyRefs")
            if isinstance(import_snapshot_record, Mapping)
            else None
        )
        if (
            isinstance(adopted_policy_refs, Sequence)
            and not isinstance(adopted_policy_refs, (str, bytes))
            and _ELSST_NATIVE_SKOS_IMPORT_POLICY in adopted_policy_refs
        ):
            selected_release_iri = permission.reference_resource_release.get("id")
            for member in self._members.values():
                if member.release_iri != selected_release_iri:
                    continue
                native_status = member.record.get(
                    "owl:deprecated",
                    member.record.get("http://www.w3.org/2002/07/owl#deprecated"),
                )
                status_values = (
                    (native_status,)
                    if isinstance(native_status, str)
                    else (
                        tuple(native_status)
                        if isinstance(native_status, Sequence)
                        and not isinstance(native_status, (str, bytes))
                        else ()
                    )
                )
                if any(value in {"true", "1"} for value in status_values):
                    excluded_member_releases.add(
                        (member.member_iri, member.release_iri)
                    )
        for expression, release_iri in permission_expressions:
            if (
                expression.member_iri,
                release_iri,
            ) not in excluded_member_releases and (
                member_iri is None or expression.member_iri == member_iri
            ):
                yield expression

    def iter_relations(
        self,
        *,
        subject_member_iri: str | None = None,
    ) -> Iterator[ManagedReleaseRelation]:
        """Iterate immutable relations, optionally from one exact member."""

        for relation in self._relations:
            if (
                subject_member_iri is None
                or relation.subject_member_iri == subject_member_iri
            ):
                yield relation

    def iter_lifecycle_participants(
        self,
        *,
        event_iri: str | None = None,
    ) -> Iterator[ManagedReleaseLifecycleParticipant]:
        """Iterate immutable participants, optionally for one exact event."""

        for participant in self._lifecycle_participants:
            if event_iri is None or participant.event_iri == event_iri:
                yield participant

    def iter_concept_mappings(
        self,
        *,
        source_member_iri: str | None = None,
    ) -> Iterator[ManagedReleaseConceptMapping]:
        """Iterate validated mappings without treating them as exact lookup."""

        for mapping in self._concept_mappings:
            if (
                source_member_iri is None
                or mapping.source_member_iri == source_member_iri
            ):
                yield mapping
