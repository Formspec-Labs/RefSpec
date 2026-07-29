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
    A JSON Lines artifact descriptor plus its exact
    ``expressionCorpusSnapshot`` reference.

Every descriptor is ``{"path": <relative path>, "sha256": "sha256:..."}``.
The reader verifies all bytes before parsing them and retains only immutable
in-memory values. Physical lookup indexes are consumer state and cannot be
packaged as part of a managed release.

This reader does not run, replace, or claim Rulespec conformance. It consumes
an already validated release chain: the publication manifest and the modeled
``ReleaseGraphValidationReceipt`` must pass REF JSON Binding 1.0, and the
receipt must exactly bind the packaged graph, records, validator, and covered
identifiers. The caller supplies the trusted bundle-manifest byte digest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
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
from refspec.vocabulary import (
    CONCEPT_EVENT_PARTICIPANT_COLUMNS,
    CONCEPT_LABEL_COLUMNS,
    CONCEPT_RELATION_COLUMNS,
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
        field
        for field in CONCEPT_LABEL_COLUMNS
        if field != "migration_only"
    ),
    "concept_relations": tuple(
        field
        for field in CONCEPT_RELATION_COLUMNS
        if field != "migration_only"
    ),
    "concept_event_participants": tuple(
        field
        for field in CONCEPT_EVENT_PARTICIPANT_COLUMNS
        if field
        not in {"complete_membership", "ordinal", "migration_only"}
    ),
}
_PUBLICATION_TYPE = "urn:ref:type:PublicationReleaseManifest"
_EXPRESSION_TYPE = "urn:ref:type:IndexedVocabularyExpression"
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
_RELATION_PROPERTIES = {
    "http://www.w3.org/2004/02/skos/core#broader": "skos:broader",
    "http://www.w3.org/2004/02/skos/core#narrower": "skos:narrower",
    "http://www.w3.org/2004/02/skos/core#related": "skos:related",
}


class ManagedReleaseError(ValueError):
    """A managed-release bundle is incomplete, mutable, or inconsistent."""


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
    original_literal: str
    language_tag: str
    expression_id: str
    migration_only: bool


@dataclass(frozen=True, slots=True)
class _NormalizedRelationRow:
    relation_id: str
    release_iri: str
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
    concept_kind: str
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
        raise ManagedReleaseError(f"{label} is not canonical UTF-8 JSON: {error}") from error


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
    payload = resolved.read_bytes()
    actual = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ManagedReleaseError(
            f"{label} digest mismatch: expected {expected}, got {actual}"
        )
    return payload


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
        raise ManagedReleaseError(
            f"{label} fails REF JSON Binding 1.0: {rendered}"
        )


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
    generated = dependency.get("generatedArtifacts")
    if not isinstance(identity, str) or not identity.strip():
        raise ManagedReleaseError(
            "rulespecDependencyManifest.validator.identity is required"
        )
    if (
        not isinstance(revision, str)
        or not _GIT_REVISION.fullmatch(revision)
    ):
        raise ManagedReleaseError(
            "rulespecDependencyManifest.validator.sourceRevision is invalid"
        )
    if (
        not isinstance(certification, str)
        or not _RAW_SHA256.fullmatch(certification)
    ):
        raise ManagedReleaseError(
            "rulespecDependencyManifest validator certification digest is invalid"
        )
    if not isinstance(generated, Mapping) or not generated:
        raise ManagedReleaseError(
            "rulespecDependencyManifest.generatedArtifacts must not be empty"
        )
    if any(
        not isinstance(path, str)
        or not path
        or not isinstance(digest, str)
        or not _RAW_SHA256.fullmatch(digest)
        for path, digest in generated.items()
    ):
        raise ManagedReleaseError(
            "rulespecDependencyManifest.generatedArtifacts is invalid"
        )
    return {
        "id": RULESPEC_VALIDATOR_COMPONENT_ID,
        "revision": revision,
        "digest": canonical_value_digest(
            {
                "identity": identity,
                "sourceRevision": revision,
                "selfCertificationSha256": certification,
                "generatedArtifacts": dict(generated),
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
    evidence_revision = dependency.get("evidenceRevision")
    if (
        not isinstance(revision, str)
        or not _GIT_REVISION.fullmatch(revision)
        or not isinstance(evidence_revision, str)
        or not _GIT_REVISION.fullmatch(evidence_revision)
    ):
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
                "evidenceRevision": evidence_revision,
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
        "digest": "sha256:"
        + hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }


def _behavior_test_identifier(governance_record_id: str) -> str:
    suffix = hashlib.sha256(
        governance_record_id.encode("utf-8")
    ).hexdigest()
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
            and record.get("outcome")
            in _RESOLVED_RECONCILIATION_OUTCOMES
        ):
            scope_source = record.get("precedencePolicy")
            evaluation_time = record.get("recordedAt")
        else:
            continue
        identifier = record.get("id")
        digest = record.get(binding.digest_field(dict(record)))
        scope = (
            scope_source.get("id")
            if isinstance(scope_source, Mapping)
            else None
        )
        if not all(
            isinstance(value, str) and value
            for value in (identifier, digest, scope, evaluation_time)
        ):
            raise ManagedReleaseError(
                "authorizing REF record lacks an exact identifier, digest, "
                "scope, or evaluation time"
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
                "combinedValidationReceipt.authorizationEvaluations"
                f"[{index}] must be an object"
            )
        governance_reference = _reference_key(
            _require_digest_reference(
                value.get("governanceRecord"),
                "combinedValidationReceipt.authorizationEvaluations"
                f"[{index}].governanceRecord",
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
                f"{record_type} authorization evaluation does not bind the "
                "exact Rulespec graph"
            )
        if evaluation.get("runtime") != dict(expected_runtime):
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation does not bind the "
                "exact embedded Rulespec L4 runtime"
            )
        if (
            evaluation.get("behaviorContract")
            != "rkaf:UsageEligibilityReducer"
            or evaluation.get("minimumUsageEligibility")
            != "rkaf:localOperationalUse"
            or evaluation.get("result") != "pass"
        ):
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation is not a passing "
                "gate-owned usage-eligibility evaluation"
            )
        if (
            evaluation.get("evaluationScope") != scope
            or evaluation.get("evaluationTime") != evaluation_time
        ):
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation does not bind its "
                "derived scope and evaluation time"
            )
        subject = evaluation.get("subjectAssertion")
        if subject not in graph_identifiers:
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation subject is not "
                "defined in the exact Rulespec graph"
            )
        effective_level = evaluation.get("effectiveUsageEligibility")
        if effective_level not in _AUTHORIZED_USAGE_LEVELS:
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation is below the "
                "required local-operational-use level"
            )
        expected_output_digest = canonical_value_digest(
            {"byScope": {scope: effective_level}}
        )
        if evaluation.get("outputDigest") != expected_output_digest:
            raise ManagedReleaseError(
                f"{record_type} authorization evaluation output digest does "
                "not match its exact effective result"
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


def _iter_nested_references(value: Any, *, top_level: bool = False) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if not top_level and {"id", "digest"}.issubset(value):
            yield value
        for child in value.values():
            yield from _iter_nested_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_nested_references(child)


def _node_types(node: Mapping[str, Any]) -> set[str]:
    value = node.get("@type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return {str(item) for item in value}
    return set()


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


def _language_values(value: object, language_tag: str) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    selected = value.get(language_tag)
    if isinstance(selected, str):
        return (selected,)
    if isinstance(selected, Sequence) and not isinstance(
        selected,
        (str, bytes),
    ):
        return tuple(item for item in selected if isinstance(item, str))
    return ()


def _rulespec_nodes(graph: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(graph, dict):
        raise ManagedReleaseError("rulespecGraph must be a JSON-LD object")
    raw = graph.get("@graph")
    if not isinstance(raw, list) or not raw:
        raise ManagedReleaseError("rulespecGraph must contain a non-empty @graph")
    nodes: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(raw):
        if not isinstance(node, dict):
            raise ManagedReleaseError(f"rulespecGraph.@graph[{index}] must be an object")
        identifier = node.get("@id")
        if not isinstance(identifier, str) or not identifier:
            raise ManagedReleaseError(f"rulespecGraph.@graph[{index}] has no @id")
        if identifier in nodes:
            raise ManagedReleaseError(f"rulespecGraph repeats identifier {identifier!r}")
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
class ManagedReleaseMember:
    """One exact member of a complete Rulespec release."""

    member_iri: str
    release_iri: str
    scheme_iri: str
    record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ManagedReleaseExpression:
    """One immutable indexed expression eligible for candidate lookup."""

    expression_id: str
    member_iri: str
    indexed_text: str
    original_literal: str
    language_tag: str | None
    source_property_or_path: str
    record: Mapping[str, Any]


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
class ManagedReleaseView:
    """Read-only member, expression, relation, lifecycle, and mapping access.

    Relations and lifecycle participants are byte-pinned normalized rows that
    round-trip to the exact graph. Concept mappings come directly from that
    graph. Their Rulespec meaning is accepted only through the matching
    ``ReleaseGraphValidationReceipt``; this reader does not revalidate it.
    """

    _release_id: str
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

    usage_ceiling = "candidateUseOnly"

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> ManagedReleaseView:
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
        actual_manifest_digest = (
            "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
        )
        if actual_manifest_digest != expected_manifest_digest:
            raise ManagedReleaseError(
                "bundle manifest digest mismatch: expected "
                f"{expected_manifest_digest}, got {actual_manifest_digest}"
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
        if not isinstance(publication, dict) or publication.get("type") != _PUBLICATION_TYPE:
            raise ManagedReleaseError(
                "publicationReleaseManifest artifact must contain one PublicationReleaseManifest"
            )
        publication_id, publication_digest = _record_digest_reference(
            publication,
            "publicationReleaseManifest",
        )
        if publication.get("releaseState") != "complete" or publication.get(
            "consumerEligible"
        ) is not True:
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

        records_by_id: dict[str, dict[str, Any]] = {
            publication_id: publication
        }
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
                "linked REF records do not exactly match "
                "PublicationReleaseManifest.refOperationalRecords"
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
                        f"{owner_id} carries a digest-mismatched REF reference "
                        f"to {reference.get('id')!r}"
                    )
                if (
                    "version" in reference
                    and reference.get("version") != target.get("version")
                ):
                    raise ManagedReleaseError(
                        f"{owner_id} carries a version-mismatched REF reference "
                        f"to {reference.get('id')!r}"
                    )

        run_receipt = _require_digest_reference(
            publication.get("runReceipt"),
            "PublicationReleaseManifest.runReceipt",
        )
        if _reference_key(run_receipt) not in actual_operational_refs:
            raise ManagedReleaseError(
                "PublicationReleaseManifest.runReceipt does not resolve "
                "to one linked REF record"
            )
        run_receipt_record = records_by_id[run_receipt["id"]]
        if run_receipt_record.get("type") != "urn:ref:type:RunReceipt":
            raise ManagedReleaseError(
                "PublicationReleaseManifest.runReceipt must resolve to a "
                "RunReceipt"
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
        dependency_digest = (
            "sha256:" + hashlib.sha256(dependency_bytes).hexdigest()
        )
        if (
            dependency_digest != RULESPEC_DEPENDENCY_SHA256
            or dependency_bytes != RULESPEC_DEPENDENCY_BYTES
        ):
            raise ManagedReleaseError(
                "rulespecDependencyManifest is not the exact RefSpec-embedded "
                "Rulespec dependency"
            )
        declared_dependency = cast(
            Mapping[str, Any],
            publication["rulespecDependency"],
        )
        expected_dependency_fields = {
            "version": dependency_manifest.get("rulespecVersion"),
            "contractRevision": dependency_manifest.get("contractRevision"),
            "evidenceRevision": dependency_manifest.get("evidenceRevision"),
            "constraintDigest": dependency_manifest.get("constraintDigest"),
            "conformanceCorpusDigest": dependency_manifest.get(
                "conformanceCorpusDigest"
            ),
            "releaseAvailability": dependency_manifest.get(
                "releaseAvailability"
            ),
        }
        for field_name, expected in expected_dependency_fields.items():
            if declared_dependency.get(field_name) != expected:
                raise ManagedReleaseError(
                    "PublicationReleaseManifest.rulespecDependency."
                    f"{field_name} does not match the embedded dependency "
                    "manifest"
                )
        expected_validator = _dependency_validator_pin(
            dependency_manifest
        )
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
        if (
            not isinstance(graph_id, str)
            or not _ABSOLUTE_IRI.fullmatch(graph_id)
        ):
            raise ManagedReleaseError(
                "rulespecGraphId must be an external absolute graph identifier"
            )
        if graph_reference["id"] != graph_id:
            raise ManagedReleaseError(
                "external rulespecGraphId does not match "
                "PublicationReleaseManifest.rulespecReleaseGraph"
            )
        if not isinstance(graph, dict) or "@id" in graph:
            raise ManagedReleaseError(
                "rulespecGraph must remain a default-graph JSON-LD document "
                "without a top-level @id"
            )
        if rulespec_graph_digest(graph) != graph_reference["digest"]:
            raise ManagedReleaseError(
                "exact Rulespec graph digest does not match "
                "PublicationReleaseManifest.rulespecReleaseGraph"
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
            if name not in _TABLE_COLUMNS or name in table_bytes:
                raise ManagedReleaseError(
                    f"normalizedTables[{index}].name is unknown or repeated"
                )
            table_bytes[str(name)] = _read_verified_artifact(
                root,
                {
                    "path": descriptor.get("path"),
                    "sha256": descriptor.get("sha256"),
                },
                f"normalizedTables[{index}]",
                seen_paths,
            )
        if set(table_bytes) != set(_TABLE_COLUMNS):
            raise ManagedReleaseError(
                "normalizedTables must contain the three exact RefSpec tables"
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
            if any(
                not pa.types.is_string(field.type)
                for field in table.schema
            ):
                raise ManagedReleaseError(
                    f"normalized table {name!r} must use the RefSpec "
                    "all-string physical schema"
                )
            tables[name] = tuple(
                cast(Mapping[str, Any], _freeze(row))
                for row in table.to_pylist()
            )
            for row_index, row in enumerate(tables[name]):
                for field in _TABLE_REQUIRED_TEXT_COLUMNS[name]:
                    value = row.get(field)
                    if not isinstance(value, str) or not value:
                        raise ManagedReleaseError(
                            f"normalized table {name}[{row_index}].{field} "
                            "must be non-empty text"
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
                    concept_kind=_required_table_text(
                        row,
                        "concept_kind",
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
        if len(label_ids) != len(set(label_ids)):
            raise ManagedReleaseError(
                "concept_labels repeats a label row identifier"
            )
        if len(relation_ids) != len(set(relation_ids)):
            raise ManagedReleaseError(
                "concept_relations repeats a relation row identifier"
            )

        corpus_descriptor = manifest.get("indexedExpressionCorpus")
        if not isinstance(corpus_descriptor, dict) or set(corpus_descriptor) != {
            "path",
            "sha256",
            "expressionCorpusSnapshot",
        }:
            raise ManagedReleaseError(
                "indexedExpressionCorpus must name a path, digest, and "
                "expressionCorpusSnapshot"
            )
        corpus_snapshot = _require_digest_reference(
            corpus_descriptor.get("expressionCorpusSnapshot"),
            "indexedExpressionCorpus.expressionCorpusSnapshot",
        )
        publication_snapshot = _require_digest_reference(
            publication.get("expressionCorpusSnapshot"),
            "PublicationReleaseManifest.expressionCorpusSnapshot",
        )
        if corpus_snapshot != publication_snapshot:
            raise ManagedReleaseError(
                "indexed expression corpus snapshot does not match "
                "PublicationReleaseManifest"
            )
        lookup_identity = manifest.get("lookupIndexManifest")
        if lookup_identity is not None:
            lookup_reference = _require_digest_reference(
                lookup_identity,
                "lookupIndexManifest",
            )
            if lookup_reference["id"] == corpus_snapshot["id"]:
                raise ManagedReleaseError(
                    "bundle conflates expressionCorpusSnapshot with "
                    "lookupIndexManifest"
                )
            raise ManagedReleaseError(
                "physical lookupIndexManifest belongs to a consumer "
                "configuration, not a managed-release bundle"
            )
        corpus_bytes = _read_verified_artifact(
            root,
            {
                "path": corpus_descriptor.get("path"),
                "sha256": corpus_descriptor.get("sha256"),
            },
            "indexedExpressionCorpus",
            seen_paths,
        )
        expressions: list[ManagedReleaseExpression] = []
        expression_records: list[dict[str, Any]] = []
        expression_records_by_id: dict[str, dict[str, Any]] = {}
        expression_ids: set[str] = set()
        for line_number, raw_line in enumerate(corpus_bytes.splitlines(), start=1):
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
                    f"indexedExpressionCorpus line {line_number} is not "
                    "an IndexedVocabularyExpression"
                )
            expression_id, _ = _record_digest_reference(
                value,
                f"indexedExpressionCorpus line {line_number}",
            )
            expression_records.append(value)
            if expression_id in expression_ids:
                raise ManagedReleaseError(
                    f"indexedExpressionCorpus repeats {expression_id!r}"
                )
            expression_ids.add(expression_id)
            expression_records_by_id[expression_id] = value
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
            if (
                release.get("version") != release_node.get("dcat:version")
                or release.get("digest")
                != release_node.get("rkaf:referenceReleaseDigest")
            ):
                raise ManagedReleaseError(
                    f"{expression_id} release version or digest does not "
                    "match the exact Rulespec release"
                )
            if value.get("scheme") != member_scheme[member]:
                raise ManagedReleaseError(
                    f"{expression_id} scheme does not match its exact member"
                )
            indexed_text = value.get("indexedText")
            original_literal = value.get("originalLiteral")
            if not isinstance(indexed_text, str) or not indexed_text:
                raise ManagedReleaseError(f"{expression_id}.indexedText is required")
            if value.get("indexedTextDigest") != binding.text_digest(indexed_text):
                raise ManagedReleaseError(
                    f"{expression_id}.indexedTextDigest does not match"
                )
            if not isinstance(original_literal, str) or not original_literal:
                raise ManagedReleaseError(
                    f"{expression_id}.originalLiteral is required"
                )
            source = value.get("sourceProperty", value.get("sourcePath"))
            if not isinstance(source, str) or not source:
                raise ManagedReleaseError(
                    f"{expression_id} has no source property or path"
                )
            language = value.get("language")
            if language is not None and not isinstance(language, str):
                raise ManagedReleaseError(f"{expression_id}.language is invalid")
            frozen_record = cast(Mapping[str, Any], _freeze(value))
            expressions.append(
                ManagedReleaseExpression(
                    expression_id=expression_id,
                    member_iri=member,
                    indexed_text=indexed_text,
                    original_literal=original_literal,
                    language_tag=language,
                    source_property_or_path=source,
                    record=frozen_record,
                )
            )

        _require_binding_valid(
            expression_records,
            "indexed expression corpus",
        )

        if (
            not isinstance(combined_receipt, dict)
            or combined_receipt.get("type") != _COMBINED_RECEIPT_TYPE
        ):
            raise ManagedReleaseError(
                "combinedValidationReceipt must contain one "
                "ReleaseGraphValidationReceipt"
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
                "combinedValidationReceipt does not bind the embedded "
                "Rulespec dependency manifest"
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
            *{
                (
                    str(record["id"]),
                    str(record[binding.digest_field(record)]),
                )
                for record in expression_records
            },
        }
        if receipt_record_refs != exact_ref_records:
            raise ManagedReleaseError(
                "combinedValidationReceipt.refRecordDigests does not exactly "
                "cover the bundle's REF records"
            )
        if combined_receipt.get("rulespecValidator") != expected_validator:
            raise ManagedReleaseError(
                "combinedValidationReceipt Rulespec validator identity or "
                "revision does not match the dependency manifest"
            )
        if (
            combined_receipt.get("rulespecBehaviorRuntime")
            != expected_behavior_runtime
        ):
            raise ManagedReleaseError(
                "combinedValidationReceipt Rulespec behavior runtime does not "
                "match the exact embedded dependency"
            )
        if combined_receipt.get("gateImplementation") != expected_gate:
            raise ManagedReleaseError(
                "combinedValidationReceipt gate implementation does not match "
                "the installed RefSpec release-graph gate"
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
            or set(covered_values) != set(graph_identifiers)
        ):
            raise ManagedReleaseError(
                "combinedValidationReceipt covered Rulespec identifiers do "
                "not exactly match the graph"
            )
        _require_authorization_evaluation_coverage(
            receipt=combined_receipt,
            records=ref_records,
            graph_reference=graph_reference,
            graph_identifiers=set(graph_identifiers),
            expected_runtime=expected_behavior_runtime,
        )

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
                    f"concept_labels[{index}] release or scheme does not "
                    "match the exact member"
                )
            property_name = _LABEL_PROPERTIES.get(
                row.source_property_iri
            )
            if property_name is None:
                raise ManagedReleaseError(
                    f"concept_labels[{index}] source property cannot be "
                    "matched to the exact Rulespec graph"
                )
            if row.original_literal not in _language_values(
                nodes[row.concept_iri].get(property_name),
                row.language_tag,
            ):
                raise ManagedReleaseError(
                    f"concept_labels[{index}] does not round-trip to the "
                    "exact Rulespec member graph"
                )
            expression_record = expression_records_by_id.get(
                row.expression_id
            )
            if expression_record is None:
                raise ManagedReleaseError(
                    f"concept_labels[{index}] references a missing indexed expression"
                )
            if row.expression_id in referenced_label_expressions:
                raise ManagedReleaseError(
                    f"concept_labels[{index}] reuses an indexed expression"
                )
            referenced_label_expressions.add(row.expression_id)
            import_snapshot = expression_record.get(
                "registryImportSnapshot"
            )
            distribution = expression_record.get(
                "distributionArtifact"
            )
            expression_source_property = expression_record.get(
                "sourceProperty"
            )
            expression_source_path = expression_record.get("sourcePath")
            source_matches = (
                expression_source_property == row.source_property_iri
                if expression_source_property is not None
                else (
                    isinstance(expression_source_path, str)
                    and bool(expression_source_path)
                )
            )
            if (
                expression_record.get("member") != row.concept_iri
                or expression_record.get("scheme") != row.scheme_iri
                or not source_matches
                or expression_record.get("originalLiteral")
                != row.original_literal
                or expression_record.get("language") != row.language_tag
                or not isinstance(import_snapshot, Mapping)
                or import_snapshot.get("id") != row.import_snapshot_id
                or not isinstance(distribution, Mapping)
                or distribution.get("id")
                != row.distribution_artifact_id
            ):
                raise ManagedReleaseError(
                    f"concept_labels[{index}] does not match its exact "
                    "indexed expression"
                )
        for index, row in enumerate(normalized_relations):
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
                or member_release[row.object_concept_iri]
                != row.release_iri
            ):
                raise ManagedReleaseError(
                    f"concept_relations[{index}] release does not contain "
                    "both endpoints"
                )
            if (
                member_scheme[row.subject_concept_iri]
                != row.subject_scheme_iri
                or member_scheme[row.object_concept_iri]
                != row.object_scheme_iri
            ):
                raise ManagedReleaseError(
                    f"concept_relations[{index}] scheme fields do not match "
                    "the exact member graph"
                )
            property_name = _RELATION_PROPERTIES.get(row.predicate_iri)
            if property_name is None:
                raise ManagedReleaseError(
                    f"concept_relations[{index}] predicate cannot be matched "
                    "to the exact Rulespec graph"
                )
            if row.object_concept_iri not in _iri_values(
                nodes[row.subject_concept_iri].get(property_name)
            ):
                raise ManagedReleaseError(
                    f"concept_relations[{index}] does not round-trip to the "
                    "exact Rulespec member graph"
                )

        for index, row in enumerate(normalized_participants):
            event = nodes.get(row.event_id)
            if event is None or not (
                _node_types(event) & _LIFECYCLE_TYPES
            ):
                raise ManagedReleaseError(
                    f"concept_event_participants[{index}] event is absent "
                    "from the exact Rulespec graph"
                )
            if (
                row.concept_iri not in member_release
                or member_release[row.concept_iri] != row.release_iri
                or row.complete_membership is not True
            ):
                raise ManagedReleaseError(
                    f"concept_event_participants[{index}] does not identify "
                    "one exact complete-release member"
                )
            member_types = _node_types(nodes[row.concept_iri])
            expected_member_type = {
                "local": {
                    "rkaf:LocalConcept",
                    "https://rulespec.org/ns/v1#LocalConcept",
                },
                "registered": {
                    "rkaf:RegisteredConcept",
                    "https://rulespec.org/ns/v1#RegisteredConcept",
                },
            }.get(row.concept_kind)
            if (
                expected_member_type is None
                or not (member_types & expected_member_type)
            ):
                raise ManagedReleaseError(
                    f"concept_event_participants[{index}] concept kind does "
                    "not match the exact member graph"
                )
            operation = re.split(
                r"[:/#]",
                str(event.get("rkaf:conceptLifecycleOperation", "")),
            )[-1]
            if operation != row.operation:
                raise ManagedReleaseError(
                    f"concept_event_participants[{index}] operation does not "
                    "match its Rulespec event"
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
            if (
                row.concept_iri
                not in _iri_values(event.get(concept_property))
                or _iri_values(event.get(release_property))
                != (row.release_iri,)
            ):
                raise ManagedReleaseError(
                    f"concept_event_participants[{index}] does not round-trip "
                    "to its exact Rulespec event"
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
            if any(
                len(values) != 1 for values in exact_values.values()
            ):
                raise ManagedReleaseError(
                    f"ConceptMapping {mapping_iri!r} has an incomplete "
                    "endpoint or relation"
                )
            source_member = exact_values["rkaf:assertsSubject"][0]
            target_member = exact_values["rkaf:assertsObject"][0]
            source_release = exact_values[
                "rkaf:sourceConceptRelease"
            ][0]
            target_release = exact_values[
                "rkaf:targetConceptRelease"
            ][0]
            if (
                member_release.get(source_member) != source_release
                or member_release.get(target_member) != target_release
            ):
                raise ManagedReleaseError(
                    f"ConceptMapping {mapping_iri!r} endpoint releases do "
                    "not match exact complete membership"
                )
            managed_mappings.append(
                ManagedReleaseConceptMapping(
                    mapping_iri=mapping_iri,
                    source_member_iri=source_member,
                    relation_iri=exact_values[
                        "rkaf:assertsPredicate"
                    ][0],
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
        )

    @property
    def release_id(self) -> str:
        return self._release_id

    @property
    def expression_corpus_snapshot(self) -> Mapping[str, str]:
        return self._expression_corpus_snapshot

    @property
    def release_graph_validation_receipt(self) -> Mapping[str, Any]:
        """Return the exact immutable receipt verified while opening the bundle."""

        return self._release_graph_validation_receipt

    def lookup_member(self, member_iri: str) -> ManagedReleaseMember | None:
        """Return one exact release member; no label or normalized lookup."""

        return self._members.get(member_iri)

    def iter_expressions(
        self,
        *,
        member_iri: str | None = None,
    ) -> Iterator[ManagedReleaseExpression]:
        """Iterate immutable candidate-use expressions in corpus order."""

        for expression in self._expressions:
            if member_iri is None or expression.member_iri == member_iri:
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
            if (
                event_iri is None
                or participant.event_iri == event_iri
            ):
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
