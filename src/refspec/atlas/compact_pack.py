"""Deterministic compact JSONL packs for Atlas logical records.

This module defines transport mechanics only.  Atlas role adapters remain
responsible for deciding which fields make up a resource, label, relation, or
evidence record and for interpreting any row-level ``contentDigest``.
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
from pathlib import Path
from typing import Any

try:  # Python 3.14+
    from compression import zstd
except ImportError:  # pragma: no cover - exercised on supported Python 3.10-3.13
    from backports import zstd

from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

CONTENT_MEDIA_TYPE = "application/x-ndjson"
TRANSPORT_MEDIA_TYPE = "application/zstd"
TRANSPORT_COMPRESSION = "zstd"
PACK_ID_PREFIX = "urn:ref:atlas:compact-pack:"
HEADER_TYPE = "AtlasCompactPackHeader"
HEADER_SCHEMA_VERSION = "1.0"
DEFAULT_MAX_TRANSPORT_BYTES = 1 * 1024 * 1024 * 1024
DEFAULT_MAX_CONTENT_BYTES = 4 * 1024 * 1024 * 1024
DEFAULT_MAX_RECORDS = 10_000_000
DEFAULT_MAX_LINE_BYTES = 16 * 1024 * 1024

_SAFE_INTEGER = 9_007_199_254_740_991
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
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
        "content",
        "transport",
    }
)
_REQUIRED_INVENTORY_FIELDS = _INVENTORY_FIELDS - {"partition"}
_CONTENT_FIELDS = frozenset({"mediaType", "digest", "byteLength", "recordCount"})
_TRANSPORT_FIELDS = frozenset({"compression", "mediaType", "digest", "byteLength"})


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


def build_compact_pack(
    header: CompactPackHeader,
    rows: Iterable[Mapping[str, Any]],
) -> CompactPackArtifact:
    """Build a deterministic compact artifact without touching the filesystem.

    The writer omits values equal to pack defaults.  It expands those defaults
    before checking row IDs and calculating ``logicalRowsDigest``.
    """

    normalized_header = _normalize_header(header)
    defaults = normalized_header.defaults
    by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    for index, raw_row in enumerate(rows):
        row = _copy_json_mapping(raw_row, f"$rows[{index}]")
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
    content = canonical_json_bytes(_wire_header(normalized_header)) + b"".join(
        canonical_json_bytes(compact) for _, compact in ordered
    )
    logical_content = b"".join(canonical_json_bytes(row) for row in logical_rows)
    content_digest = sha256_digest(content)
    transport = zstd.compress(content, level=9)
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
    )
    return CompactPackArtifact(
        inventory=inventory,
        rows=logical_rows,
        content=content,
        transport=transport,
    )


def write_compact_pack(
    directory: Path,
    header: CompactPackHeader,
    rows: Iterable[Mapping[str, Any]],
) -> CompactPackInventory:
    """Write one immutable compact pack and return its inventory descriptor."""

    artifact = build_compact_pack(header, rows)
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
    )
    logical_content = b"".join(canonical_json_bytes(row) for row in rows)
    if sha256_digest(logical_content) != inventory.logical_rows_digest:
        raise CompactPackError("expanded logical row digest does not match the inventory")
    return CompactPackArtifact(
        inventory=inventory,
        rows=rows,
        content=content,
        transport=transport,
    )


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
    )


def _wire_header(header: CompactPackHeader) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": HEADER_TYPE,
        "schemaVersion": HEADER_SCHEMA_VERSION,
        "role": header.role,
        "dependencies": list(header.dependencies),
        "defaults": _copy_json(header.defaults, "$.defaults"),
    }
    if header.partition is not None:
        value["partition"] = _copy_json(header.partition, "$.partition")
    return value


def _parse_content(
    content: bytes,
    *,
    header: CompactPackHeader,
    expected_count: int,
    max_line_bytes: int,
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
    if wire_header != _wire_header(header):
        raise CompactPackError("compact pack header does not match the inventory")

    parsed: list[dict[str, Any]] = []
    previous_id: str | None = None
    for line_number, raw_line in enumerate(lines[1:], start=2):
        if len(raw_line) > max_line_bytes:
            raise CompactPackError(f"line {line_number} exceeds the configured byte limit")
        row = _strict_json_object(raw_line, line_number)
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


def _strict_json_object(raw_line: bytes, line_number: int) -> dict[str, Any]:
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


__all__ = [
    "CompactPackArtifact",
    "CompactPackError",
    "CompactPackHeader",
    "CompactPackInventory",
    "build_compact_pack",
    "read_compact_pack",
    "write_compact_pack",
]
