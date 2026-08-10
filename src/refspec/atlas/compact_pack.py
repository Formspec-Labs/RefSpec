"""Deterministic compact JSONL packs for Atlas logical records.

The original transport API remains intentionally generic.  The record-pack API
adds the closed Atlas roles and pack-local facts needed by a future incremental
producer.  It does not assign source-specific meaning or make compact packs
authoritative ahead of the Atlas parity cutover.
"""

from __future__ import annotations

import io
import json
import os
import re
import stat
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from typing_extensions import NotRequired, TypedDict

try:  # Python 3.14+
    from compression import zstd
except ImportError:  # pragma: no cover - exercised on supported Python 3.10-3.13
    from backports import zstd

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

CONTENT_MEDIA_TYPE = "application/x-ndjson"
TRANSPORT_MEDIA_TYPE = "application/zstd"
TRANSPORT_COMPRESSION = "zstd"
PACK_ID_PREFIX = "urn:ref:atlas:compact-pack:"
HEADER_TYPE = "AtlasCompactPackHeader"
HEADER_SCHEMA_VERSION = "1.0"
RECORD_SCHEMA_VERSION = "1.0"
GLOBAL_INVARIANT_SUMMARY_VERSION = "1.0"
DEFAULT_MAX_TRANSPORT_BYTES = 1 * 1024 * 1024 * 1024
DEFAULT_MAX_CONTENT_BYTES = 4 * 1024 * 1024 * 1024
DEFAULT_MAX_RECORDS = 10_000_000
DEFAULT_MAX_LINE_BYTES = 16 * 1024 * 1024
DEFAULT_COMPRESSION_LEVEL = 9
MIN_COMPRESSION_LEVEL = 1
MAX_COMPRESSION_LEVEL = 22

_SAFE_INTEGER = 9_007_199_254_740_991
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
_ROLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+)*$")
_SAFE_RELATIVE_PATH_RE = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*//)"
    r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$"
)
_RESERVED_DEFAULT_FIELDS = frozenset(
    {"id", "contentDigest", "canonicalPayloadDigest"}
)
_INVENTORY_FIELDS = frozenset(
    {
        "packId",
        "role",
        "path",
        "partition",
        "dependencies",
        "defaults",
        "logicalRowsDigest",
        "recordSchemaVersion",
        "globalInvariantSummary",
        "content",
        "transport",
    }
)
_REQUIRED_INVENTORY_FIELDS = _INVENTORY_FIELDS - {
    "partition",
    "recordSchemaVersion",
    "globalInvariantSummary",
}
_CONTENT_FIELDS = frozenset({"mediaType", "digest", "byteLength", "recordCount"})
_TRANSPORT_FIELDS = frozenset({"compression", "mediaType", "digest", "byteLength"})
_GLOBAL_SUMMARY_FIELDS = frozenset(
    {
        "schemaVersion",
        "recordRole",
        "recordCount",
        "recordIds",
        "resourceOwnership",
        "labelClaims",
        "statementEndpoints",
        "evidenceLinks",
        "sourceRecordLinks",
        "releaseRecords",
        "identifierClaims",
        "lifecycleEvents",
        "digest",
    }
)
_GLOBAL_SUMMARY_RECEIPT_FIELDS = frozenset(
    {
        "schemaVersion",
        "recordRole",
        "recordCount",
        "fieldCounts",
        "digest",
    }
)
_GLOBAL_SUMMARY_COUNT_FIELDS = frozenset(
    {
        "recordIds",
        "resourceOwnership",
        "labelClaims",
        "statementEndpoints",
        "evidenceLinks",
        "sourceRecordLinks",
        "releaseRecords",
        "identifierClaims",
        "lifecycleEvents",
    }
)
_CANONICAL_DIGEST_FIELD = "canonicalPayloadDigest"
_COMMON_RECORD_FIELDS = frozenset(
    {"id", "contentDigest", _CANONICAL_DIGEST_FIELD}
)


class CompactRecordRole(str, Enum):
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
    assertionStatus: str
    assertionIdentityDigest: str
    semanticRing: NotRequired[str]
    sourceRing: NotRequired[str]
    targetRing: NotRequired[str]
    supersedes: NotRequired[str]
    contentDigest: NotRequired[str]
    canonicalPayloadDigest: NotRequired[str]


class EvidenceBindingRecord(TypedDict):
    id: str
    statement: str
    sourceRecord: str
    evidenceSourceDigest: str
    reviewedBy: str
    reviewMethod: str
    decisionStatus: str
    decidedAt: str
    confidence: NotRequired[str]
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
    eventSubject: str
    eventType: str
    eventAt: str
    sourceRecords: list[str]
    fromRelease: NotRequired[str]
    toRelease: NotRequired[str]
    contentDigest: NotRequired[str]
    canonicalPayloadDigest: NotRequired[str]


CompactLogicalRecord = (
    ResourceRecord
    | LabelRecord
    | StatementRecord
    | EvidenceBindingRecord
    | SourceRecordRecord
    | ReleaseRecord
    | IdentifierRecord
    | LifecycleEventRecord
)


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
                "assertionStatus",
                "assertionIdentityDigest",
            }
        ),
        optional=frozenset(
            {"semanticRing", "sourceRing", "targetRing", "supersedes"}
        ),
    ),
    CompactRecordRole.EVIDENCE_BINDING: _RecordSchema(
        required=frozenset(
            {
                "id",
                "statement",
                "sourceRecord",
                "evidenceSourceDigest",
                "reviewedBy",
                "reviewMethod",
                "decisionStatus",
                "decidedAt",
            }
        ),
        optional=frozenset({"confidence"}),
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
            {"id", "eventSubject", "eventType", "eventAt", "sourceRecords"}
        ),
        optional=frozenset({"fromRelease", "toRelease"}),
    ),
}

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
_ASSERTION_STATUSES = frozenset({"current", "superseded", "withdrawn"})
_RELEASE_TYPES = frozenset({"AtlasRelease", "SourceRelease"})


class CompactPackError(ValueError):
    """A compact pack is unsafe, malformed, or fails an integrity check."""


@dataclass(frozen=True)
class CompactPackHeader:
    """Pack-level context supplied by a producer before rows are encoded."""

    role: str
    path: str
    defaults: Mapping[str, Any] = field(default_factory=dict)
    dependencies: Sequence[str] = ()
    partition: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class CompactPackInventory:
    """One future-manifest-ready compact pack descriptor."""

    pack_id: str
    role: str
    path: str
    defaults: Mapping[str, Any]
    dependencies: tuple[str, ...]
    logical_rows_digest: str
    content: Mapping[str, Any]
    transport: Mapping[str, Any]
    partition: Mapping[str, Any] | None = None
    record_schema_version: str | None = None
    global_invariant_summary: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        descriptor: dict[str, Any] = {
            "packId": self.pack_id,
            "role": self.role,
            "path": self.path,
            "dependencies": list(self.dependencies),
            "defaults": _copy_json(self.defaults, "$.defaults"),
            "logicalRowsDigest": self.logical_rows_digest,
            "content": _copy_json(self.content, "$.content"),
            "transport": _copy_json(self.transport, "$.transport"),
        }
        if self.partition is not None:
            descriptor["partition"] = _copy_json(self.partition, "$.partition")
        if self.record_schema_version is not None:
            descriptor["recordSchemaVersion"] = self.record_schema_version
        if self.global_invariant_summary is not None:
            descriptor["globalInvariantSummary"] = _copy_json(
                self.global_invariant_summary,
                "$.globalInvariantSummary",
            )
        return descriptor

    @classmethod
    def from_dict(cls, descriptor: Mapping[str, Any]) -> CompactPackInventory:
        """Parse a descriptor without accepting unknown or ambiguous fields."""

        return _parse_inventory(descriptor)


@dataclass(frozen=True)
class CompactPackArtifact:
    """Encoded bytes plus the expanded logical rows they represent."""

    inventory: CompactPackInventory
    rows: tuple[dict[str, Any], ...]
    content: bytes
    transport: bytes
    global_invariant_summary: Mapping[str, Any] | None = None


def build_compact_pack(
    header: CompactPackHeader,
    rows: Iterable[Mapping[str, Any]],
    *,
    compression_level: int = DEFAULT_COMPRESSION_LEVEL,
) -> CompactPackArtifact:
    """Build a deterministic compact artifact without touching the filesystem.

    The writer omits values equal to pack defaults.  It expands those defaults
    before checking row IDs and calculating ``logicalRowsDigest``.
    """

    return _build_compact_pack(
        header,
        rows,
        record_schema_version=None,
        global_invariant_summary=None,
        compression_level=compression_level,
    )


def build_compact_record_pack(
    header: CompactPackHeader,
    rows: Iterable[Mapping[str, Any]],
    *,
    compression_level: int = DEFAULT_COMPRESSION_LEVEL,
) -> CompactPackArtifact:
    """Build a deterministic pack of one closed logical record role.

    Every row is normalized after pack defaults are expanded.  The resulting
    canonical row digest and global-invariant summary are bound into the pack
    content, so neither a row nor its replay summary can be re-pinned silently.
    """

    normalized_header = _normalize_header(header)
    role = _record_role(normalized_header.role, "$.role")
    unsupported_defaults = sorted(
        normalized_header.defaults.keys() - _RECORD_SCHEMAS[role].fields
    )
    if unsupported_defaults:
        raise CompactPackError(
            "$.defaults: fields are not admitted by "
            f"{role.value}: {', '.join(unsupported_defaults)}"
        )
    normalized_rows: list[dict[str, Any]] = []
    for index, raw_row in enumerate(rows):
        row = dict(normalized_header.defaults)
        row.update(_copy_compact_record_mapping(raw_row, f"$rows[{index}]"))
        normalized_rows.append(
            normalize_compact_record(role, row, path=f"$rows[{index}]")
        )
    summary = _summarize_normalized_compact_records(role, normalized_rows)
    return _build_compact_pack(
        normalized_header,
        normalized_rows,
        record_schema_version=RECORD_SCHEMA_VERSION,
        global_invariant_summary=summary,
        compression_level=compression_level,
    )


def _build_compact_pack(
    header: CompactPackHeader,
    rows: Iterable[Mapping[str, Any]],
    *,
    record_schema_version: str | None,
    global_invariant_summary: Mapping[str, Any] | None,
    compression_level: int,
) -> CompactPackArtifact:
    """Build the shared wire format for generic or closed-role records."""

    normalized_header = _normalize_header(header)
    _validate_compression_level(compression_level)
    defaults = normalized_header.defaults
    by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    for index, raw_row in enumerate(rows):
        row = (
            _copy_json_mapping(raw_row, f"$rows[{index}]")
            if record_schema_version is None
            else _copy_compact_record_mapping(raw_row, f"$rows[{index}]")
        )
        logical = dict(defaults)
        logical.update(row)
        identifier = logical.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise CompactPackError(f"$rows[{index}].id: expected a non-empty string")
        if identifier in by_id:
            raise CompactPackError(f"duplicate row id: {identifier}")
        compact = {
            key: value
            for key, value in row.items()
            if key not in defaults or value != defaults[key]
        }
        by_id[identifier] = (logical, compact)

    ordered = [by_id[identifier] for identifier in sorted(by_id)]
    logical_rows = tuple(logical for logical, _ in ordered)
    normalized_summary = (
        None
        if global_invariant_summary is None
        else _parse_full_global_invariant_summary(
            global_invariant_summary,
            expected_role=_record_role(normalized_header.role, "$.role"),
            expected_count=len(logical_rows),
        )
    )
    summary_receipt = (
        None
        if normalized_summary is None
        else _global_invariant_summary_receipt(normalized_summary)
    )
    if (record_schema_version is None) != (normalized_summary is None):
        raise CompactPackError(
            "recordSchemaVersion and globalInvariantSummary must appear together"
        )
    if record_schema_version is not None and record_schema_version != RECORD_SCHEMA_VERSION:
        raise CompactPackError(
            f"recordSchemaVersion: expected {RECORD_SCHEMA_VERSION}"
        )
    content = canonical_json_bytes(
        _wire_header(
            normalized_header,
            record_schema_version=record_schema_version,
            global_invariant_summary_digest=(
                None if summary_receipt is None else str(summary_receipt["digest"])
            ),
        )
    ) + b"".join(
        canonical_json_bytes(compact) for _, compact in ordered
    )
    logical_content = b"".join(canonical_json_bytes(row) for row in logical_rows)
    content_digest = sha256_digest(content)
    transport = zstd.compress(content, level=compression_level)
    inventory = CompactPackInventory(
        pack_id=PACK_ID_PREFIX + content_digest.removeprefix("sha256:"),
        role=normalized_header.role,
        path=normalized_header.path,
        defaults=defaults,
        dependencies=normalized_header.dependencies,
        logical_rows_digest=sha256_digest(logical_content),
        content={
            "mediaType": CONTENT_MEDIA_TYPE,
            "digest": content_digest,
            "byteLength": len(content),
            "recordCount": len(logical_rows),
        },
        transport={
            "compression": TRANSPORT_COMPRESSION,
            "mediaType": TRANSPORT_MEDIA_TYPE,
            "digest": sha256_digest(transport),
            "byteLength": len(transport),
        },
        partition=normalized_header.partition,
        record_schema_version=record_schema_version,
        global_invariant_summary=summary_receipt,
    )
    return CompactPackArtifact(
        inventory=inventory,
        rows=logical_rows,
        content=content,
        transport=transport,
        global_invariant_summary=normalized_summary,
    )


def write_compact_pack(
    directory: Path,
    header: CompactPackHeader,
    rows: Iterable[Mapping[str, Any]],
    *,
    compression_level: int = DEFAULT_COMPRESSION_LEVEL,
) -> CompactPackInventory:
    """Write one immutable compact pack and return its inventory descriptor."""

    artifact = build_compact_pack(
        header,
        rows,
        compression_level=compression_level,
    )
    return _write_compact_artifact(directory, artifact)


def write_compact_record_pack(
    directory: Path,
    header: CompactPackHeader,
    rows: Iterable[Mapping[str, Any]],
    *,
    compression_level: int = DEFAULT_COMPRESSION_LEVEL,
) -> CompactPackInventory:
    """Write one immutable closed-role record pack."""

    artifact = build_compact_record_pack(
        header,
        rows,
        compression_level=compression_level,
    )
    return _write_compact_artifact(directory, artifact)


def _write_compact_artifact(
    directory: Path,
    artifact: CompactPackArtifact,
) -> CompactPackInventory:
    """Persist an already built artifact under the shared immutability rules."""

    target = _pack_path(directory, artifact.inventory.path, create_parents=True)
    if target.is_symlink():
        raise CompactPackError(f"pack target cannot be a symlink: {target}")
    if target.exists():
        if not target.is_file():
            raise CompactPackError(f"pack target is not a regular file: {target}")
        if target.read_bytes() == artifact.transport:
            return artifact.inventory
        raise CompactPackError(f"refusing to replace existing compact pack: {target}")
    _atomic_write(target, artifact.transport)
    return artifact.inventory


def read_compact_pack(
    directory: Path,
    descriptor: CompactPackInventory | Mapping[str, Any],
    *,
    max_transport_bytes: int = DEFAULT_MAX_TRANSPORT_BYTES,
    max_content_bytes: int = DEFAULT_MAX_CONTENT_BYTES,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
) -> CompactPackArtifact:
    """Authenticate, decompress, parse, and expand one compact pack."""

    inventory = CompactPackInventory.from_dict(
        descriptor.to_dict() if isinstance(descriptor, CompactPackInventory) else descriptor
    )
    _validate_limit("max_transport_bytes", max_transport_bytes)
    _validate_limit("max_content_bytes", max_content_bytes)
    _validate_limit("max_records", max_records)
    _validate_limit("max_line_bytes", max_line_bytes)

    transport_length = _exact_int(inventory.transport["byteLength"], "$.transport.byteLength")
    content_length = _exact_int(inventory.content["byteLength"], "$.content.byteLength")
    record_count = _exact_int(inventory.content["recordCount"], "$.content.recordCount")
    if transport_length > max_transport_bytes:
        raise CompactPackError("transport byte length exceeds the configured limit")
    if content_length > max_content_bytes:
        raise CompactPackError("content byte length exceeds the configured limit")
    if record_count > max_records:
        raise CompactPackError("record count exceeds the configured limit")

    target = _pack_path(directory, inventory.path, create_parents=False)
    try:
        metadata = target.lstat()
    except FileNotFoundError as error:
        raise CompactPackError(f"compact pack is missing: {inventory.path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CompactPackError(f"compact pack is not a regular file: {inventory.path}")
    if metadata.st_size != transport_length:
        raise CompactPackError("transport byte length does not match the inventory")
    transport = target.read_bytes()
    if sha256_digest(transport) != inventory.transport["digest"]:
        raise CompactPackError("transport digest does not match the inventory")

    content = _decompress_bounded(transport, content_length)
    if sha256_digest(content) != inventory.content["digest"]:
        raise CompactPackError("content digest does not match the inventory")
    expected_pack_id = PACK_ID_PREFIX + str(inventory.content["digest"]).removeprefix("sha256:")
    if inventory.pack_id != expected_pack_id:
        raise CompactPackError("packId does not derive from the content digest")

    rows = _parse_content(
        content,
        header=CompactPackHeader(
            role=inventory.role,
            path=inventory.path,
            defaults=inventory.defaults,
            dependencies=inventory.dependencies,
            partition=inventory.partition,
        ),
        expected_count=record_count,
        max_line_bytes=max_line_bytes,
        record_schema_version=inventory.record_schema_version,
        global_invariant_summary_digest=(
            None
            if inventory.global_invariant_summary is None
            else str(inventory.global_invariant_summary["digest"])
        ),
    )
    logical_content = b"".join(canonical_json_bytes(row) for row in rows)
    if sha256_digest(logical_content) != inventory.logical_rows_digest:
        raise CompactPackError("expanded logical row digest does not match the inventory")
    observed_summary: dict[str, Any] | None = None
    if inventory.record_schema_version is not None:
        role = _record_role(inventory.role, "$.role")
        normalized_rows = tuple(
            normalize_compact_record(role, row, path=f"$rows[{index}]")
            for index, row in enumerate(rows)
        )
        if normalized_rows != rows:
            raise CompactPackError("closed-role rows are not deterministically normalized")
        observed_summary = _summarize_normalized_compact_records(
            role,
            normalized_rows,
        )
        observed_receipt = _global_invariant_summary_receipt(observed_summary)
        if observed_receipt != inventory.global_invariant_summary:
            raise CompactPackError(
                "global-invariant summary does not match the expanded logical rows"
            )
    return CompactPackArtifact(
        inventory=inventory,
        rows=rows,
        content=content,
        transport=transport,
        global_invariant_summary=observed_summary,
    )


def read_compact_record_pack(
    directory: Path,
    descriptor: CompactPackInventory | Mapping[str, Any],
    *,
    max_transport_bytes: int = DEFAULT_MAX_TRANSPORT_BYTES,
    max_content_bytes: int = DEFAULT_MAX_CONTENT_BYTES,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
) -> CompactPackArtifact:
    """Read a pack and require the closed record schema and summary receipts."""

    artifact = read_compact_pack(
        directory,
        descriptor,
        max_transport_bytes=max_transport_bytes,
        max_content_bytes=max_content_bytes,
        max_records=max_records,
        max_line_bytes=max_line_bytes,
    )
    if (
        artifact.inventory.record_schema_version != RECORD_SCHEMA_VERSION
        or artifact.inventory.global_invariant_summary is None
    ):
        raise CompactPackError("compact record pack receipts are missing")
    return artifact


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


def summarize_compact_records(
    role: CompactRecordRole | str,
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the exact pack-local facts needed to replay global checks."""

    record_role = _record_role(role, "$.recordRole")
    normalized_records = [
        normalize_compact_record(
            record_role,
            raw_record,
            path=f"$records[{index}]",
        )
        for index, raw_record in enumerate(records)
    ]
    return _summarize_normalized_compact_records(record_role, normalized_records)


def _summarize_normalized_compact_records(
    record_role: CompactRecordRole,
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized_by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw_record in enumerate(records):
        identifier = str(raw_record["id"])
        if identifier in normalized_by_id:
            raise CompactPackError(f"duplicate {record_role.value} record id: {identifier}")
        normalized_by_id[identifier] = raw_record

    ordered = [normalized_by_id[identifier] for identifier in sorted(normalized_by_id)]
    summary: dict[str, Any] = {
        "schemaVersion": GLOBAL_INVARIANT_SUMMARY_VERSION,
        "recordRole": record_role.value,
        "recordCount": len(ordered),
        "recordIds": [str(record["id"]) for record in ordered],
        "resourceOwnership": [],
        "labelClaims": [],
        "statementEndpoints": [],
        "evidenceLinks": [],
        "sourceRecordLinks": [],
        "releaseRecords": [],
        "identifierClaims": [],
        "lifecycleEvents": [],
    }
    target_field = _SUMMARY_FIELD_BY_ROLE[record_role]
    summary[target_field] = [
        _global_invariant_projection(record_role, record) for record in ordered
    ]
    summary["digest"] = sha256_digest(canonical_json_bytes(summary))
    return summary


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
            "supersedes",
        ),
        CompactRecordRole.EVIDENCE_BINDING: (
            "id",
            "statement",
            "sourceRecord",
            "reviewedBy",
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
            "eventSubject",
            "eventType",
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
        _closed_token(
            record["assertionStatus"],
            _ASSERTION_STATUSES,
            f"{path}.assertionStatus",
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


_SUMMARY_FIELD_BY_ROLE = {
    CompactRecordRole.RESOURCE: "resourceOwnership",
    CompactRecordRole.LABEL: "labelClaims",
    CompactRecordRole.STATEMENT: "statementEndpoints",
    CompactRecordRole.EVIDENCE_BINDING: "evidenceLinks",
    CompactRecordRole.SOURCE_RECORD: "sourceRecordLinks",
    CompactRecordRole.RELEASE: "releaseRecords",
    CompactRecordRole.IDENTIFIER: "identifierClaims",
    CompactRecordRole.LIFECYCLE_EVENT: "lifecycleEvents",
}

_SUMMARY_PROJECTION_FIELDS = {
    CompactRecordRole.RESOURCE: (
        "id",
        "release",
        "scheme",
        "semanticRing",
        "resourceProfile",
        "sourceRecord",
    ),
    CompactRecordRole.LABEL: (
        "id",
        "resource",
        "labelRole",
        "value",
        "language",
        "release",
        "sourceRecord",
    ),
    CompactRecordRole.STATEMENT: (
        "id",
        "statementType",
        "subject",
        "predicate",
        "object",
        "sourceRelease",
        "targetRelease",
        "policy",
        "assertionStatus",
        "semanticRing",
        "sourceRing",
        "targetRing",
        "supersedes",
    ),
    CompactRecordRole.EVIDENCE_BINDING: (
        "id",
        "statement",
        "sourceRecord",
        "evidenceSourceDigest",
        "reviewedBy",
        "reviewMethod",
        "decisionStatus",
        "decidedAt",
    ),
    CompactRecordRole.SOURCE_RECORD: (
        "id",
        "sourceRelease",
        "sourceDigest",
        "sourceLocator",
        "representsResource",
    ),
    CompactRecordRole.RELEASE: (
        "id",
        "releaseType",
        "identifier",
        "issued",
        "sourceDigest",
        "sourceLocator",
        "resourceProfile",
        "semanticRing",
        "scheme",
        "membershipMode",
    ),
    CompactRecordRole.IDENTIFIER: (
        "id",
        "identifierValue",
        "identifierScheme",
        "identifies",
        "sourceRecord",
    ),
    CompactRecordRole.LIFECYCLE_EVENT: (
        "id",
        "eventSubject",
        "eventType",
        "eventAt",
        "sourceRecords",
        "fromRelease",
        "toRelease",
    ),
}


def _global_invariant_projection(
    role: CompactRecordRole,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    fields = _SUMMARY_PROJECTION_FIELDS[role]
    return {field_name: record[field_name] for field_name in fields if field_name in record}


def _parse_full_global_invariant_summary(
    raw_summary: Mapping[str, Any],
    *,
    expected_role: CompactRecordRole,
    expected_count: int,
) -> dict[str, Any]:
    summary = _closed_object(
        raw_summary,
        "$.globalInvariantSummary",
        _GLOBAL_SUMMARY_FIELDS,
    )
    if summary["schemaVersion"] != GLOBAL_INVARIANT_SUMMARY_VERSION:
        raise CompactPackError(
            "$.globalInvariantSummary.schemaVersion: unsupported version"
        )
    role = _record_role(
        summary["recordRole"],
        "$.globalInvariantSummary.recordRole",
    )
    if role != expected_role:
        raise CompactPackError("global-invariant summary role differs from the pack")
    record_count = _exact_int(
        summary["recordCount"],
        "$.globalInvariantSummary.recordCount",
    )
    if record_count != expected_count:
        raise CompactPackError("global-invariant summary record count differs")

    record_ids = _sorted_unique_strings(
        summary["recordIds"],
        "$.globalInvariantSummary.recordIds",
        require_sorted=True,
    )
    if len(record_ids) != record_count:
        raise CompactPackError("global-invariant summary record IDs differ in count")
    summary["recordIds"] = record_ids
    active_field = _SUMMARY_FIELD_BY_ROLE[role]
    for field_name in sorted(_GLOBAL_SUMMARY_COUNT_FIELDS - {"recordIds"}):
        entries = summary[field_name]
        if not isinstance(entries, list):
            raise CompactPackError(
                f"$.globalInvariantSummary.{field_name}: expected an array"
            )
        if field_name != active_field:
            if entries:
                raise CompactPackError(
                    f"$.globalInvariantSummary.{field_name}: must be empty for {role.value}"
                )
            continue
        normalized_entries = [
            _parse_global_invariant_entry(role, entry, index)
            for index, entry in enumerate(entries)
        ]
        observed_ids = [str(entry["id"]) for entry in normalized_entries]
        if observed_ids != record_ids:
            raise CompactPackError(
                f"$.globalInvariantSummary.{field_name}: IDs differ from recordIds"
            )
        summary[field_name] = normalized_entries

    supplied_digest = _digest(
        summary["digest"],
        "$.globalInvariantSummary.digest",
    )
    digest_payload = {
        key: value for key, value in summary.items() if key != "digest"
    }
    if supplied_digest != sha256_digest(canonical_json_bytes(digest_payload)):
        raise CompactPackError("global-invariant summary digest does not match its fields")
    summary["digest"] = supplied_digest
    return summary


def _parse_global_invariant_entry(
    role: CompactRecordRole,
    raw_entry: Any,
    index: int,
) -> dict[str, Any]:
    path = f"$.globalInvariantSummary.{_SUMMARY_FIELD_BY_ROLE[role]}[{index}]"
    entry = _copy_json_mapping(raw_entry, path)
    allowed = frozenset(_SUMMARY_PROJECTION_FIELDS[role])
    required = _RECORD_SCHEMAS[role].required & allowed
    missing = sorted(required - entry.keys())
    unknown = sorted(entry.keys() - allowed)
    if missing:
        raise CompactPackError(f"{path}: missing fields: {', '.join(missing)}")
    if unknown:
        raise CompactPackError(f"{path}: unknown fields: {', '.join(unknown)}")
    entry["id"] = _absolute_iri(entry["id"], f"{path}.id")
    if role == CompactRecordRole.STATEMENT:
        _closed_token(
            entry["statementType"],
            _STATEMENT_TYPES,
            f"{path}.statementType",
        )
        if "supersedes" in entry:
            entry["supersedes"] = _absolute_iri(
                entry["supersedes"],
                f"{path}.supersedes",
            )
        _normalize_statement_rings(entry, path)
    elif role == CompactRecordRole.RELEASE:
        _normalize_release_fields(entry, path)
    elif role == CompactRecordRole.LIFECYCLE_EVENT:
        _normalize_role_fields(role, entry, path)
    return entry


def _global_invariant_summary_receipt(
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    role = _record_role(summary.get("recordRole"), "$.globalInvariantSummary.recordRole")
    count = _exact_int(
        summary.get("recordCount"),
        "$.globalInvariantSummary.recordCount",
    )
    return {
        "schemaVersion": GLOBAL_INVARIANT_SUMMARY_VERSION,
        "recordRole": role.value,
        "recordCount": count,
        "fieldCounts": {
            field_name: len(summary[field_name])
            for field_name in sorted(_GLOBAL_SUMMARY_COUNT_FIELDS)
        },
        "digest": _digest(
            summary.get("digest"),
            "$.globalInvariantSummary.digest",
        ),
    }


def _parse_global_invariant_summary_receipt(
    raw_receipt: Any,
    *,
    expected_role: CompactRecordRole,
    expected_count: int,
) -> dict[str, Any]:
    receipt = _closed_object(
        raw_receipt,
        "$.globalInvariantSummary",
        _GLOBAL_SUMMARY_RECEIPT_FIELDS,
    )
    if receipt["schemaVersion"] != GLOBAL_INVARIANT_SUMMARY_VERSION:
        raise CompactPackError(
            "$.globalInvariantSummary.schemaVersion: unsupported version"
        )
    role = _record_role(
        receipt["recordRole"],
        "$.globalInvariantSummary.recordRole",
    )
    if role != expected_role:
        raise CompactPackError("global-invariant summary role differs from the pack")
    record_count = _exact_int(
        receipt["recordCount"],
        "$.globalInvariantSummary.recordCount",
    )
    if record_count != expected_count:
        raise CompactPackError("global-invariant summary record count differs")
    field_counts = _closed_object(
        receipt["fieldCounts"],
        "$.globalInvariantSummary.fieldCounts",
        _GLOBAL_SUMMARY_COUNT_FIELDS,
    )
    for field_name in sorted(field_counts):
        field_counts[field_name] = _exact_int(
            field_counts[field_name],
            f"$.globalInvariantSummary.fieldCounts.{field_name}",
        )
    active_field = _SUMMARY_FIELD_BY_ROLE[role]
    for field_name, field_count in field_counts.items():
        expected_field_count = (
            record_count if field_name in {"recordIds", active_field} else 0
        )
        if field_count != expected_field_count:
            raise CompactPackError(
                f"$.globalInvariantSummary.fieldCounts.{field_name}: expected {expected_field_count}"
            )
    receipt["recordRole"] = role.value
    receipt["recordCount"] = record_count
    receipt["fieldCounts"] = field_counts
    receipt["digest"] = _digest(
        receipt["digest"],
        "$.globalInvariantSummary.digest",
    )
    return receipt


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


def _normalize_header(header: CompactPackHeader) -> CompactPackHeader:
    role = _nonempty_string(header.role, "$.role")
    if not _ROLE_RE.fullmatch(role):
        raise CompactPackError("$.role: expected a compact role token")
    path = _safe_relative_pack_path(header.path)
    defaults = _normalize_defaults(header.defaults)
    dependencies = _normalize_dependencies(header.dependencies)
    partition = (
        None
        if header.partition is None
        else _copy_json_mapping(header.partition, "$.partition")
    )
    return CompactPackHeader(
        role=role,
        path=path,
        defaults=defaults,
        dependencies=dependencies,
        partition=partition,
    )


def _parse_inventory(descriptor: Mapping[str, Any]) -> CompactPackInventory:
    value = _copy_json_mapping(descriptor, "$")
    fields = frozenset(value)
    missing = sorted(_REQUIRED_INVENTORY_FIELDS - fields)
    unknown = sorted(fields - _INVENTORY_FIELDS)
    if missing:
        raise CompactPackError(f"inventory is missing fields: {', '.join(missing)}")
    if unknown:
        raise CompactPackError(f"inventory has unknown fields: {', '.join(unknown)}")

    content = _closed_object(value["content"], "$.content", _CONTENT_FIELDS)
    transport = _closed_object(value["transport"], "$.transport", _TRANSPORT_FIELDS)
    if content["mediaType"] != CONTENT_MEDIA_TYPE:
        raise CompactPackError(f"$.content.mediaType: expected {CONTENT_MEDIA_TYPE}")
    if transport["mediaType"] != TRANSPORT_MEDIA_TYPE:
        raise CompactPackError(f"$.transport.mediaType: expected {TRANSPORT_MEDIA_TYPE}")
    if transport["compression"] != TRANSPORT_COMPRESSION:
        raise CompactPackError(f"$.transport.compression: expected {TRANSPORT_COMPRESSION}")
    for path in ("digest",):
        _digest(content[path], f"$.content.{path}")
        _digest(transport[path], f"$.transport.{path}")
    _exact_int(content["byteLength"], "$.content.byteLength")
    _exact_int(content["recordCount"], "$.content.recordCount")
    _exact_int(transport["byteLength"], "$.transport.byteLength")

    role = _nonempty_string(value["role"], "$.role")
    if not _ROLE_RE.fullmatch(role):
        raise CompactPackError("$.role: expected a compact role token")
    path = _safe_relative_pack_path(value["path"])
    defaults = _normalize_defaults(value["defaults"])
    dependencies = _normalize_dependencies(value["dependencies"], require_sorted=True)
    logical_rows_digest = _digest(value["logicalRowsDigest"], "$.logicalRowsDigest")
    partition = (
        None
        if "partition" not in value
        else _copy_json_mapping(value["partition"], "$.partition")
    )
    pack_id = _nonempty_string(value["packId"], "$.packId")
    expected_pack_id = PACK_ID_PREFIX + str(content["digest"]).removeprefix("sha256:")
    if pack_id != expected_pack_id:
        raise CompactPackError("$.packId: value does not derive from $.content.digest")
    has_record_schema = "recordSchemaVersion" in value
    has_global_summary = "globalInvariantSummary" in value
    if has_record_schema != has_global_summary:
        raise CompactPackError(
            "recordSchemaVersion and globalInvariantSummary must appear together"
        )
    record_schema_version: str | None = None
    global_invariant_summary: dict[str, Any] | None = None
    if has_record_schema:
        record_schema_version = _nonempty_string(
            value["recordSchemaVersion"],
            "$.recordSchemaVersion",
        )
        if record_schema_version != RECORD_SCHEMA_VERSION:
            raise CompactPackError(
                f"$.recordSchemaVersion: expected {RECORD_SCHEMA_VERSION}"
            )
        global_invariant_summary = _parse_global_invariant_summary_receipt(
            value["globalInvariantSummary"],
            expected_role=_record_role(role, "$.role"),
            expected_count=_exact_int(
                content["recordCount"],
                "$.content.recordCount",
            ),
        )
    return CompactPackInventory(
        pack_id=pack_id,
        role=role,
        path=path,
        defaults=defaults,
        dependencies=dependencies,
        logical_rows_digest=logical_rows_digest,
        content=content,
        transport=transport,
        partition=partition,
        record_schema_version=record_schema_version,
        global_invariant_summary=global_invariant_summary,
    )


def _wire_header(
    header: CompactPackHeader,
    *,
    record_schema_version: str | None = None,
    global_invariant_summary_digest: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": HEADER_TYPE,
        "schemaVersion": HEADER_SCHEMA_VERSION,
        "role": header.role,
        "dependencies": list(header.dependencies),
        "defaults": _copy_json(header.defaults, "$.defaults"),
    }
    if header.partition is not None:
        value["partition"] = _copy_json(header.partition, "$.partition")
    if (record_schema_version is None) != (global_invariant_summary_digest is None):
        raise CompactPackError(
            "record schema and global summary digest must appear together"
        )
    if record_schema_version is not None:
        value["recordSchemaVersion"] = record_schema_version
        value["globalInvariantSummaryDigest"] = _digest(
            global_invariant_summary_digest,
            "$.globalInvariantSummary.digest",
        )
    return value


def _parse_content(
    content: bytes,
    *,
    header: CompactPackHeader,
    expected_count: int,
    max_line_bytes: int,
    record_schema_version: str | None = None,
    global_invariant_summary_digest: str | None = None,
) -> tuple[dict[str, Any], ...]:
    if not content:
        raise CompactPackError("compact JSONL content is missing its header")
    if not content.endswith(b"\n"):
        raise CompactPackError("compact JSONL content must end with LF")
    lines = content.splitlines(keepends=True)
    if len(lines[0]) > max_line_bytes:
        raise CompactPackError("compact pack header exceeds the configured byte limit")
    wire_header = _strict_json_object(lines[0], 1)
    if canonical_json_bytes(wire_header) != lines[0]:
        raise CompactPackError("line 1 is not canonical JSON")
    if wire_header != _wire_header(
        header,
        record_schema_version=record_schema_version,
        global_invariant_summary_digest=global_invariant_summary_digest,
    ):
        raise CompactPackError("compact pack header does not match the inventory")

    parsed: list[dict[str, Any]] = []
    previous_id: str | None = None
    for line_number, raw_line in enumerate(lines[1:], start=2):
        if len(raw_line) > max_line_bytes:
            raise CompactPackError(f"line {line_number} exceeds the configured byte limit")
        row = _strict_json_object(
            raw_line,
            line_number,
            allow_native_payload_null=record_schema_version is not None,
        )
        if canonical_json_bytes(row) != raw_line:
            raise CompactPackError(f"line {line_number} is not canonical JSON")
        for key, default in header.defaults.items():
            if key in row and row[key] == default:
                raise CompactPackError(
                    f"line {line_number} redundantly repeats default field {key}"
                )
        logical = dict(header.defaults)
        logical.update(row)
        identifier = logical.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise CompactPackError(f"line {line_number} has no non-empty string id")
        if previous_id is not None and identifier <= previous_id:
            reason = "duplicate" if identifier == previous_id else "out-of-order"
            raise CompactPackError(f"line {line_number} has a {reason} row id")
        previous_id = identifier
        parsed.append(logical)
    if len(parsed) != expected_count:
        raise CompactPackError("record count does not match the inventory")
    return tuple(parsed)


def _strict_json_object(
    raw_line: bytes,
    line_number: int,
    *,
    allow_native_payload_null: bool = False,
) -> dict[str, Any]:
    try:
        text = raw_line.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, CompactPackError) as error:
        raise CompactPackError(f"line {line_number} is invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise CompactPackError(f"line {line_number} must contain one JSON object")
    if allow_native_payload_null:
        return _copy_compact_record_mapping(value, f"$line[{line_number}]")
    return _copy_json_mapping(value, f"$line[{line_number}]")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise CompactPackError(f"duplicate object field: {key}")
        value[key] = child
    return value


def _reject_json_number(value: str) -> Any:
    raise CompactPackError(f"unsupported JSON number: {value}")


def _copy_json_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CompactPackError(f"{path}: expected an object")
    copied = _copy_json(value, path)
    assert isinstance(copied, dict)
    return copied


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


def _normalize_defaults(value: Any) -> dict[str, Any]:
    defaults = _copy_json_mapping(value, "$.defaults")
    reserved = sorted(_RESERVED_DEFAULT_FIELDS & defaults.keys())
    if reserved:
        raise CompactPackError(
            "$.defaults: identity and row digest fields cannot be defaults: "
            + ", ".join(reserved)
        )
    return defaults


def _normalize_dependencies(
    value: Any,
    *,
    require_sorted: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CompactPackError("$.dependencies: expected an array")
    dependencies = tuple(
        _nonempty_string(dependency, f"$.dependencies[{index}]")
        for index, dependency in enumerate(value)
    )
    if len(set(dependencies)) != len(dependencies):
        raise CompactPackError("$.dependencies: duplicate pack IDs are forbidden")
    ordered = tuple(sorted(dependencies))
    if require_sorted and dependencies != ordered:
        raise CompactPackError("$.dependencies: pack IDs must be sorted")
    return ordered


def _closed_object(value: Any, path: str, fields: frozenset[str]) -> dict[str, Any]:
    record = _copy_json_mapping(value, path)
    actual = frozenset(record)
    missing = sorted(fields - actual)
    unknown = sorted(actual - fields)
    if missing:
        raise CompactPackError(f"{path}: missing fields: {', '.join(missing)}")
    if unknown:
        raise CompactPackError(f"{path}: unknown fields: {', '.join(unknown)}")
    return record


def _digest(value: Any, path: str) -> str:
    digest = _nonempty_string(value, path)
    if not _DIGEST_RE.fullmatch(digest):
        raise CompactPackError(f"{path}: expected a lowercase sha256 digest")
    return digest


def _exact_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CompactPackError(f"{path}: expected a non-negative integer")
    if value > _SAFE_INTEGER:
        raise CompactPackError(f"{path}: integer exceeds the interoperable JSON range")
    return value


def _nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise CompactPackError(f"{path}: expected a non-empty string")
    return value


def _safe_relative_pack_path(value: Any) -> str:
    path = _nonempty_string(value, "$.path")
    if not _SAFE_RELATIVE_PATH_RE.fullmatch(path):
        raise CompactPackError("$.path: expected a safe normalized POSIX-relative path")
    if not path.endswith(".jsonl.zst"):
        raise CompactPackError("$.path: compact packs must end in .jsonl.zst")
    return path


def _pack_path(directory: Path, path: str, *, create_parents: bool) -> Path:
    relative = _safe_relative_pack_path(path)
    root = Path(directory)
    if root.is_symlink():
        raise CompactPackError(f"pack directory cannot be a symlink: {root}")
    if create_parents:
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise CompactPackError(f"pack directory does not exist: {root}")
    resolved_root = root.resolve(strict=True)
    target = resolved_root.joinpath(*relative.split("/"))
    parent = target.parent
    current = resolved_root
    for part in relative.split("/")[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise CompactPackError(f"pack path traverses a symlink: {relative}")
    if create_parents:
        parent.mkdir(parents=True, exist_ok=True)
    if parent.resolve(strict=True) != parent or not parent.is_relative_to(resolved_root):
        raise CompactPackError(f"pack path escapes its directory: {relative}")
    return target


def _decompress_bounded(transport: bytes, expected_length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = expected_length + 1
    try:
        with zstd.open(io.BytesIO(transport), "rb") as reader:
            while remaining:
                chunk = reader.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
    except (OSError, EOFError, zstd.ZstdError) as error:
        raise CompactPackError(f"invalid zstd transport: {error}") from error
    content = b"".join(chunks)
    if len(content) != expected_length:
        raise CompactPackError("decompressed content byte length does not match the inventory")
    return content


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _validate_limit(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CompactPackError(f"{name} must be a non-negative integer")


def _validate_compression_level(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not MIN_COMPRESSION_LEVEL <= value <= MAX_COMPRESSION_LEVEL
    ):
        raise CompactPackError(
            "compression_level must be an integer from "
            f"{MIN_COMPRESSION_LEVEL} through {MAX_COMPRESSION_LEVEL}"
        )


__all__ = [
    "CompactLogicalRecord",
    "CompactPackArtifact",
    "CompactPackError",
    "CompactPackHeader",
    "CompactPackInventory",
    "CompactRecordRole",
    "EvidenceBindingRecord",
    "IdentifierRecord",
    "LabelRecord",
    "ReleaseRecord",
    "ResourceRecord",
    "SourceRecordRecord",
    "StatementRecord",
    "build_compact_pack",
    "build_compact_record_pack",
    "normalize_compact_record",
    "read_compact_pack",
    "read_compact_record_pack",
    "summarize_compact_records",
    "write_compact_pack",
    "write_compact_record_pack",
]
