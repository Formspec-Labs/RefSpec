"""The release data model the atlas build path pins against.

RefSpec's governance workflow modules — :mod:`refspec.binding`,
:mod:`refspec.release_graph`, :mod:`refspec.managed_release`, and
:mod:`refspec.vocabulary` — grew around
this model rather than the other way round, so the build path could not reach
the model without importing the workflow. This module holds the model on its
own: the canonical JSON primitives every digest is computed with, the
normalized table column orders a bundle is serialized against, and the
immutable managed-release values a reader hands back.

The dependency points one way. Governance modules import ``release_model``;
this module's own source imports nothing from ``refspec`` -- only the
standard library. Nothing here reads a schema, runs a gate, or resolves a
permission.

That one-way source dependency is necessary but was not, by itself,
sufficient for ``import refspec.release_model`` to skip loading the
governance modules: importing a submodule first imports its parent package,
and ``refspec/__init__.py`` used to import ``managed_release`` and
``vocabulary`` eagerly at module scope. Those two
(and, transitively, ``binding`` and ``release_graph``) are now resolved
lazily via a module-level ``__getattr__`` (PEP 562) on ``refspec/__init__.py``,
so ``import refspec.release_model`` no longer pulls them into
``sys.modules`` as a side effect of the package import.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SAFE_INTEGER = 9_007_199_254_740_991

CONCEPT_LABEL_COLUMNS = (
    "label_id",
    "concept_iri",
    "scheme_iri",
    "release_iri",
    "import_snapshot_id",
    "distribution_artifact_id",
    "source_property_iri",
    "label_role",
    "original_literal",
    "language_tag",
    "status",
    "expression_id",
    "migration_only",
)
CONCEPT_RELATION_COLUMNS = (
    "relation_id",
    "release_iri",
    "import_snapshot_id",
    "distribution_artifact_id",
    "subject_concept_iri",
    "subject_scheme_iri",
    "predicate_iri",
    "object_concept_iri",
    "object_scheme_iri",
    "source_property_or_path",
    "migration_only",
)
CONCEPT_EVENT_PARTICIPANT_COLUMNS = (
    "event_id",
    "operation",
    "participant_role",
    "concept_iri",
    "concept_type_iri",
    "release_iri",
    "complete_membership",
    "ordinal",
    "migration_only",
)

CORE_FACETS = {
    "urn:ref:facet:general-subject",
    "urn:ref:facet:specialist-subject",
    "urn:ref:facet:entity",
    "urn:ref:facet:legal-location",
    "urn:ref:facet:industry-classification",
    "urn:ref:facet:affected-population",
    "urn:ref:facet:genre",
    "urn:ref:facet:regulatory-action",
    "urn:ref:facet:administrative-process-stage",
    "urn:ref:facet:code-list-value",
    "urn:ref:facet:ontology-class",
    "urn:ref:facet:observation-measure",
}


class DuplicateKeyError(ValueError):
    """Raised when a JSON object repeats a key."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def reject_nonfinite_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value} is forbidden")


def validate_canonical_value(value: Any, path: str = "$") -> None:
    if value is None:
        raise ValueError(f"{path}: null is forbidden; omit an optional field")
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > SAFE_INTEGER:
            raise ValueError(f"{path}: integer exceeds the interoperable JSON range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path}: non-finite number is forbidden")
        raise TypeError(
            f"{path}: JSON floating-point numbers are forbidden; use a canonical decimal string"
        )
    if isinstance(value, str):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_canonical_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path}: object keys must be strings")
            validate_canonical_value(item, f"{path}.{key}")
        return
    raise ValueError(f"{path}: unsupported JSON value {type(value).__name__}")


def digest_field(record: dict[str, Any]) -> str:
    if record.get("type") in {
        "urn:ref:type:EnrichmentProfile",
        "urn:ref:type:OutputProfile",
    }:
        return "contentDigest"
    return "canonicalPayloadDigest"


def canonical_json_bytes(value: Any) -> bytes:
    """Return the one canonical JSON encoding the platform digests.

    The bytes never carry a trailing newline. A newline is a property of the
    file writer that stores the value, not of the value being digested, so a
    writer appends it after this function and a digest never sees it.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Digest any JSON-compatible value in the one canonical form."""

    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_payload(record: dict[str, Any]) -> bytes:
    field = digest_field(record)
    payload = {key: value for key, value in record.items() if key != field}
    validate_canonical_value(payload)
    return canonical_json_bytes(payload)


def canonical_payload_digest(record: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_payload(record)).hexdigest()


def canonical_text_digest(value: str) -> str:
    """Digest exact UTF-8 text without JSON quoting."""
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_unicode_text(value: object) -> str:
    """Normalize search text without discarding non-ASCII characters."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(normalized.split())


def rulespec_graph_digest(graph: Any) -> str:
    """Return the exact canonical-JSON digest used to bind a bundle graph."""

    validate_canonical_value(graph)
    payload = json.dumps(
        graph,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class ManagedReleaseError(ValueError):
    """A managed-release bundle is incomplete, mutable, or inconsistent."""


class ManagedReleaseAuthorizationError(ManagedReleaseError):
    """The selected managed release does not authorize the requested use."""


@dataclass(frozen=True, slots=True)
class ManagedReleaseMember:
    """One exact member of a complete Rulespec release."""

    member_iri: str
    release_iri: str
    scheme_iri: str
    record: Mapping[str, Any]


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
