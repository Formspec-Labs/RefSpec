"""The closed logical-record contract Atlas projects its graph through.

This module used to also hold the compact JSONL/Zstandard transport those
records shipped in.  That wire is gone: the served projection is the typed
Parquet view, and the tables carry the same records through
:mod:`refspec.atlas.parquet_tables`.  What survives is the part that was never
about the transport -- the eight closed roles, each role's exact field set, and
the one normalization every producer and every verifier must agree on before a
record is compared to anything.

The names keep the word "compact" deliberately: a compact record is the
projection of one RDF carrier into flat fields, and that is still exactly what
these are.  It no longer names a file format.
"""


from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NotRequired

from typing_extensions import TypedDict

from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)
from refspec.registry.infrastructure.semantic_foundation import (
    SEMANTIC_RINGS as _SEMANTIC_RINGS,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    LABEL_ROLES as _LABEL_ROLES,
)

_SAFE_INTEGER = 9_007_199_254_740_991


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


_ABSOLUTE_IRI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")


_CANONICAL_DIGEST_FIELD = "canonicalPayloadDigest"


_COMMON_RECORD_FIELDS = frozenset(
    {"id", "contentDigest", _CANONICAL_DIGEST_FIELD}
)


class CompactRecordRole(StrEnum):
    """Closed logical roles admitted by canonical Atlas record packs."""

    RESOURCE = "Resource"
    LABEL = "Label"
    STATEMENT = "Statement"
    EVIDENCE_BINDING = "EvidenceBinding"
    SOURCE_RECORD = "SourceRecord"
    RELEASE = "Release"
    IDENTIFIER = "Identifier"
    LIFECYCLE_EVENT = "LifecycleEvent"


class ResourceRecord(TypedDict):
    id: str
    release: str
    scheme: str
    semanticRing: str
    resourceProfile: str
    sourceRecord: str
    definition: NotRequired[str]
    notes: NotRequired[list[str]]
    notations: NotRequired[list[str]]
    recordStatus: NotRequired[str]
    contentDigest: NotRequired[str]
    canonicalPayloadDigest: NotRequired[str]


class LabelRecord(TypedDict):
    id: str
    resource: str
    labelRole: str
    value: str
    language: str
    release: str
    sourceRecord: str
    contentDigest: NotRequired[str]
    canonicalPayloadDigest: NotRequired[str]


class StatementRecord(TypedDict):
    id: str
    statementType: str
    subject: str
    predicate: str
    object: str
    sourceRelease: str
    targetRelease: str
    policy: str
    assertedAt: str
    assertionIdentityDigest: str
    semanticRing: NotRequired[str]
    sourceRing: NotRequired[str]
    targetRing: NotRequired[str]
    supersedesAssertion: NotRequired[str]
    contentDigest: NotRequired[str]
    canonicalPayloadDigest: NotRequired[str]


class EvidenceBindingRecord(TypedDict):
    id: str
    statement: str
    sourceRecord: str
    evidenceSourceDigest: str
    attestor: str
    attestorKind: str
    assertionOrigin: str
    epistemicBasis: str
    evidenceRole: str
    evidentiaryFunction: str
    decision: str
    attestedAt: str
    basedOnAttestation: NotRequired[str]
    contentDigest: NotRequired[str]
    canonicalPayloadDigest: NotRequired[str]


class SourceRecordRecord(TypedDict):
    id: str
    sourceRelease: str
    sourceDigest: str
    sourceLocator: str
    nativePayload: object
    representsResource: NotRequired[str]
    contentDigest: NotRequired[str]
    canonicalPayloadDigest: NotRequired[str]


class ReleaseRecord(TypedDict):
    id: str
    releaseType: str
    identifier: str
    issued: str
    sourceDigest: NotRequired[str]
    sourceLocator: NotRequired[str]
    resourceProfile: NotRequired[str]
    semanticRing: NotRequired[str]
    scheme: NotRequired[str]
    membershipMode: NotRequired[str]
    contentDigest: NotRequired[str]
    canonicalPayloadDigest: NotRequired[str]


class IdentifierRecord(TypedDict):
    id: str
    identifierValue: str
    identifierScheme: str
    identifies: str
    sourceRecord: str
    contentDigest: NotRequired[str]
    canonicalPayloadDigest: NotRequired[str]


class LifecycleEventRecord(TypedDict):
    id: str
    appliesTo: str
    lifecycleEventKind: str
    effectiveDate: str
    sourceRecords: list[str]
    fromRelease: NotRequired[str]
    toRelease: NotRequired[str]
    contentDigest: NotRequired[str]
    canonicalPayloadDigest: NotRequired[str]


@dataclass(frozen=True)
class _RecordSchema:
    required: frozenset[str]
    optional: frozenset[str]

    @property
    def fields(self) -> frozenset[str]:
        return self.required | self.optional | _COMMON_RECORD_FIELDS


_RECORD_SCHEMAS = {
    CompactRecordRole.RESOURCE: _RecordSchema(
        required=frozenset(
            {"id", "release", "scheme", "semanticRing", "resourceProfile", "sourceRecord"}
        ),
        optional=frozenset({"definition", "notes", "notations", "recordStatus"}),
    ),
    CompactRecordRole.LABEL: _RecordSchema(
        required=frozenset(
            {"id", "resource", "labelRole", "value", "language", "release", "sourceRecord"}
        ),
        optional=frozenset(),
    ),
    CompactRecordRole.STATEMENT: _RecordSchema(
        required=frozenset(
            {
                "id",
                "statementType",
                "subject",
                "predicate",
                "object",
                "sourceRelease",
                "targetRelease",
                "policy",
                "assertedAt",
                "assertionIdentityDigest",
            }
        ),
        optional=frozenset(
            {"semanticRing", "sourceRing", "targetRing", "supersedesAssertion"}
        ),
    ),
    CompactRecordRole.EVIDENCE_BINDING: _RecordSchema(
        required=frozenset(
            {
                "id",
                "statement",
                "sourceRecord",
                "evidenceSourceDigest",
                "attestor",
                "attestorKind",
                "assertionOrigin",
                "epistemicBasis",
                "evidenceRole",
                "evidentiaryFunction",
                "decision",
                "attestedAt",
            }
        ),
        optional=frozenset({"basedOnAttestation"}),
    ),
    CompactRecordRole.SOURCE_RECORD: _RecordSchema(
        required=frozenset(
            {"id", "sourceRelease", "sourceDigest", "sourceLocator", "nativePayload"}
        ),
        optional=frozenset({"representsResource"}),
    ),
    CompactRecordRole.RELEASE: _RecordSchema(
        required=frozenset({"id", "releaseType", "identifier", "issued"}),
        optional=frozenset(
            {
                "sourceDigest",
                "sourceLocator",
                "resourceProfile",
                "semanticRing",
                "scheme",
                "membershipMode",
            }
        ),
    ),
    CompactRecordRole.IDENTIFIER: _RecordSchema(
        required=frozenset(
            {"id", "identifierValue", "identifierScheme", "identifies", "sourceRecord"}
        ),
        optional=frozenset(),
    ),
    CompactRecordRole.LIFECYCLE_EVENT: _RecordSchema(
        required=frozenset(
            {"id", "appliesTo", "lifecycleEventKind", "effectiveDate", "sourceRecords"}
        ),
        optional=frozenset({"fromRelease", "toRelease"}),
    ),
}


COMPACT_RECORD_TRANSPORT_FIELDS = frozenset({_CANONICAL_DIGEST_FIELD})


def compact_record_fields(role: CompactRecordRole) -> frozenset[str]:
    """Return every field one normalized compact logical record can carry.

    Required and optional together, minus the transport-only digest. This is
    the register a lossless projection of the compact layer -- the Parquet
    tables -- is measured against, so that adding a compact field without a
    column breaks a check instead of quietly narrowing the view.
    """

    return _RECORD_SCHEMAS[role].fields - COMPACT_RECORD_TRANSPORT_FIELDS


_RESOURCE_PROFILES = frozenset(
    {"conceptScheme", "codeScheme", "identifierScheme", "structureScheme", "resourceCollection"}
)


_STATEMENT_TYPES = frozenset(
    {
        "NativeRelationAssertion",
        "MappingAssertion",
        "SourceAssignment",
        "CrossRingRelationAssertion",
    }
)


_RELEASE_TYPES = frozenset({"AtlasRelease", "SourceRelease"})


class CompactPackError(ValueError):
    """A compact pack is unsafe, malformed, or fails an integrity check."""


def normalize_compact_record(
    role: CompactRecordRole | str,
    record: Mapping[str, Any],
    *,
    path: str = "$",
) -> dict[str, Any]:
    """Return one closed, canonical logical record with its row digest."""

    record_role = _record_role(role, f"{path}.role")
    schema = _RECORD_SCHEMAS[record_role]
    value = _copy_compact_record_mapping(record, path)
    supplied_digest = value.pop(_CANONICAL_DIGEST_FIELD, None)
    fields = frozenset(value)
    missing = sorted(schema.required - fields)
    unknown = sorted(fields - (schema.fields - {_CANONICAL_DIGEST_FIELD}))
    if missing:
        raise CompactPackError(
            f"{path}: {record_role.value} is missing fields: {', '.join(missing)}"
        )
    if unknown:
        raise CompactPackError(
            f"{path}: {record_role.value} has unknown fields: {', '.join(unknown)}"
        )

    _normalize_role_fields(record_role, value, path)
    if "contentDigest" in value:
        value["contentDigest"] = _digest(
            value["contentDigest"],
            f"{path}.contentDigest",
        )
    expected_digest = sha256_digest(
        canonical_json_bytes(
            {
                "recordRole": record_role.value,
                "record": value,
            }
        )
    )
    if supplied_digest is not None:
        observed_digest = _digest(
            supplied_digest,
            f"{path}.{_CANONICAL_DIGEST_FIELD}",
        )
        if observed_digest != expected_digest:
            raise CompactPackError(
                f"{path}.{_CANONICAL_DIGEST_FIELD}: digest does not match the normalized record"
            )
    value[_CANONICAL_DIGEST_FIELD] = expected_digest
    return value


def _normalize_role_fields(
    role: CompactRecordRole,
    record: dict[str, Any],
    path: str,
) -> None:
    iri_fields = {
        CompactRecordRole.RESOURCE: ("id", "release", "scheme", "sourceRecord"),
        CompactRecordRole.LABEL: ("id", "resource", "release", "sourceRecord"),
        CompactRecordRole.STATEMENT: (
            "id",
            "subject",
            "predicate",
            "object",
            "sourceRelease",
            "targetRelease",
            "policy",
            "supersedesAssertion",
        ),
        CompactRecordRole.EVIDENCE_BINDING: (
            "id",
            "statement",
            "sourceRecord",
            "attestor",
        ),
        CompactRecordRole.SOURCE_RECORD: (
            "id",
            "sourceRelease",
            "sourceLocator",
        ),
        CompactRecordRole.RELEASE: ("id",),
        CompactRecordRole.IDENTIFIER: (
            "id",
            "identifierScheme",
            "identifies",
            "sourceRecord",
        ),
        CompactRecordRole.LIFECYCLE_EVENT: (
            "id",
            "appliesTo",
            "lifecycleEventKind",
            "fromRelease",
            "toRelease",
        ),
    }[role]
    for field_name in iri_fields:
        if field_name not in record:
            continue
        record[field_name] = _absolute_iri(
            record[field_name],
            f"{path}.{field_name}",
        )
    for field_name in _RECORD_SCHEMAS[role].fields - {"id", "nativePayload"}:
        if field_name not in record or field_name in {
            "contentDigest",
            _CANONICAL_DIGEST_FIELD,
            "notes",
            "notations",
            "sourceRecords",
        }:
            continue
        record[field_name] = _nonempty_string(
            record[field_name],
            f"{path}.{field_name}",
        )

    if role == CompactRecordRole.RESOURCE:
        _closed_token(record["semanticRing"], _SEMANTIC_RINGS, f"{path}.semanticRing")
        _closed_token(
            record["resourceProfile"],
            _RESOURCE_PROFILES,
            f"{path}.resourceProfile",
        )
        for field_name in ("notes", "notations"):
            if field_name in record:
                record[field_name] = _sorted_unique_strings(
                    record[field_name],
                    f"{path}.{field_name}",
                )
    elif role == CompactRecordRole.LABEL:
        _closed_token(record["labelRole"], _LABEL_ROLES, f"{path}.labelRole")
        if record["language"] != "en":
            raise CompactPackError(f"{path}.language: Atlas labels must be English")
        if record["value"] != record["value"].strip():
            raise CompactPackError(f"{path}.value: expected trimmed text")
    elif role == CompactRecordRole.STATEMENT:
        _closed_token(
            record["statementType"],
            _STATEMENT_TYPES,
            f"{path}.statementType",
        )
        record["assertionIdentityDigest"] = _digest(
            record["assertionIdentityDigest"],
            f"{path}.assertionIdentityDigest",
        )
        _normalize_statement_rings(record, path)
    elif role == CompactRecordRole.EVIDENCE_BINDING:
        record["evidenceSourceDigest"] = _digest(
            record["evidenceSourceDigest"],
            f"{path}.evidenceSourceDigest",
        )
    elif role == CompactRecordRole.SOURCE_RECORD:
        record["sourceDigest"] = _digest(
            record["sourceDigest"],
            f"{path}.sourceDigest",
        )
        if "representsResource" in record:
            record["representsResource"] = _absolute_iri(
                record["representsResource"],
                f"{path}.representsResource",
            )
    elif role == CompactRecordRole.RELEASE:
        _normalize_release_fields(record, path)
    elif role == CompactRecordRole.LIFECYCLE_EVENT:
        record["sourceRecords"] = _sorted_unique_iris(
            record["sourceRecords"],
            f"{path}.sourceRecords",
        )
        if not record["sourceRecords"]:
            raise CompactPackError(
                f"{path}.sourceRecords: expected at least one source record"
            )


def _normalize_statement_rings(record: dict[str, Any], path: str) -> None:
    if record["statementType"] == "CrossRingRelationAssertion":
        if "semanticRing" in record or not {"sourceRing", "targetRing"} <= record.keys():
            raise CompactPackError(
                f"{path}: cross-ring statements require sourceRing and targetRing only"
            )
        _closed_token(record["sourceRing"], _SEMANTIC_RINGS, f"{path}.sourceRing")
        _closed_token(record["targetRing"], _SEMANTIC_RINGS, f"{path}.targetRing")
        if record["sourceRing"] == record["targetRing"]:
            raise CompactPackError(f"{path}: cross-ring statements require different rings")
        return
    if "semanticRing" not in record or {"sourceRing", "targetRing"} & record.keys():
        raise CompactPackError(
            f"{path}: same-ring statements require semanticRing only"
        )
    _closed_token(record["semanticRing"], _SEMANTIC_RINGS, f"{path}.semanticRing")


def _normalize_release_fields(record: dict[str, Any], path: str) -> None:
    release_type = _closed_token(
        record["releaseType"],
        _RELEASE_TYPES,
        f"{path}.releaseType",
    )
    source_fields = {"sourceDigest", "sourceLocator"}
    atlas_fields = {"resourceProfile", "semanticRing", "scheme", "membershipMode"}
    if release_type == "SourceRelease":
        missing = sorted(source_fields - record.keys())
        forbidden = sorted(atlas_fields & record.keys())
        if missing or forbidden:
            raise CompactPackError(
                f"{path}: SourceRelease field mismatch; missing={missing}, forbidden={forbidden}"
            )
        record["sourceDigest"] = _digest(
            record["sourceDigest"],
            f"{path}.sourceDigest",
        )
        record["sourceLocator"] = _absolute_iri(
            record["sourceLocator"],
            f"{path}.sourceLocator",
        )
        return
    missing = sorted(atlas_fields - record.keys())
    forbidden = sorted(source_fields & record.keys())
    if missing or forbidden:
        raise CompactPackError(
            f"{path}: AtlasRelease field mismatch; missing={missing}, forbidden={forbidden}"
        )
    _closed_token(record["semanticRing"], _SEMANTIC_RINGS, f"{path}.semanticRing")
    _closed_token(
        record["resourceProfile"],
        _RESOURCE_PROFILES,
        f"{path}.resourceProfile",
    )
    record["scheme"] = _absolute_iri(record["scheme"], f"{path}.scheme")


def _record_role(value: Any, path: str) -> CompactRecordRole:
    token = _nonempty_string(value, path)
    try:
        return CompactRecordRole(token)
    except ValueError as error:
        supported = ", ".join(role.value for role in CompactRecordRole)
        raise CompactPackError(f"{path}: expected one of {supported}") from error


def _absolute_iri(value: Any, path: str) -> str:
    iri = _nonempty_string(value, path)
    if _ABSOLUTE_IRI_RE.fullmatch(iri) is None:
        raise CompactPackError(f"{path}: expected an absolute IRI")
    return iri


def _closed_token(value: Any, choices: frozenset[str], path: str) -> str:
    token = _nonempty_string(value, path)
    if token not in choices:
        raise CompactPackError(
            f"{path}: expected one of {', '.join(sorted(choices))}"
        )
    return token


def _sorted_unique_strings(
    value: Any,
    path: str,
    *,
    require_sorted: bool = False,
) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CompactPackError(f"{path}: expected an array")
    strings = [
        _nonempty_string(child, f"{path}[{index}]")
        for index, child in enumerate(value)
    ]
    if len(set(strings)) != len(strings):
        raise CompactPackError(f"{path}: duplicate values are forbidden")
    ordered = sorted(strings)
    if require_sorted and strings != ordered:
        raise CompactPackError(f"{path}: values must be sorted")
    return ordered


def _sorted_unique_iris(value: Any, path: str) -> list[str]:
    strings = _sorted_unique_strings(value, path)
    return [
        _absolute_iri(item, f"{path}[{index}]")
        for index, item in enumerate(strings)
    ]


def _copy_compact_record_mapping(value: Any, path: str) -> dict[str, Any]:
    """Copy one typed row, preserving publisher nulls only in nativePayload."""

    if not isinstance(value, Mapping):
        raise CompactPackError(f"{path}: expected an object")
    copied: dict[str, Any] = {}
    for key, child in value.items():
        if not isinstance(key, str) or not key:
            raise CompactPackError(f"{path}: object keys must be non-empty strings")
        child_path = f"{path}.{key}"
        copied[key] = (
            _copy_native_json(child, child_path)
            if key == "nativePayload"
            else _copy_json(child, child_path)
        )
    return copied


def _copy_native_json(value: Any, path: str) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > _SAFE_INTEGER:
            raise CompactPackError(f"{path}: integer exceeds the interoperable JSON range")
        return value
    if isinstance(value, float):
        raise CompactPackError(f"{path}: floating-point values are forbidden")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [
            _copy_native_json(child, f"{path}[{index}]")
            for index, child in enumerate(value)
        ]
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise CompactPackError(f"{path}: object keys must be non-empty strings")
            copied[key] = _copy_native_json(child, f"{path}.{key}")
        return copied
    raise CompactPackError(f"{path}: unsupported JSON value {type(value).__name__}")


def _copy_json(value: Any, path: str) -> Any:
    if value is None:
        raise CompactPackError(f"{path}: null is forbidden; omit optional fields")
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > _SAFE_INTEGER:
            raise CompactPackError(f"{path}: integer exceeds the interoperable JSON range")
        return value
    if isinstance(value, float):
        raise CompactPackError(f"{path}: floating-point values are forbidden")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_copy_json(child, f"{path}[{index}]") for index, child in enumerate(value)]
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise CompactPackError(f"{path}: object keys must be non-empty strings")
            copied[key] = _copy_json(child, f"{path}.{key}")
        return copied
    raise CompactPackError(f"{path}: unsupported JSON value {type(value).__name__}")


def _digest(value: Any, path: str) -> str:
    digest = _nonempty_string(value, path)
    if not _DIGEST_RE.fullmatch(digest):
        raise CompactPackError(f"{path}: expected a lowercase sha256 digest")
    return digest


def _nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise CompactPackError(f"{path}: expected a non-empty string")
    return value


__all__ = [
    "COMPACT_RECORD_TRANSPORT_FIELDS",
    "CompactPackError",
    "CompactRecordRole",
    "EvidenceBindingRecord",
    "IdentifierRecord",
    "LabelRecord",
    "LifecycleEventRecord",
    "ReleaseRecord",
    "ResourceRecord",
    "SourceRecordRecord",
    "StatementRecord",
    "compact_record_fields",
    "normalize_compact_record",
]
