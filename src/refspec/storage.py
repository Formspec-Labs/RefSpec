"""Provider-neutral storage helpers for the RefSpec reference package."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def stable_id(prefix: str, *parts: object, length: int = 24) -> str:
    """Return a stable opaque identifier derived from exact identity parts."""
    encoded = "\x1f".join("" if part is None else str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:length]
    return f"{prefix}_{digest}"


def canonical_json(value: object) -> str:
    """Serialize JSON deterministically for identifiers and comparisons."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def parse_json_list(value: object) -> list[object] | None:
    """Parse a legacy JSON array without treating malformed input as empty."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, list) else None


def _normalize_row(
    row: dict[str, object],
    columns: Sequence[str],
) -> dict[str, str | None]:
    normalized: dict[str, str | None] = {}
    for column in columns:
        value = row.get(column)
        if value is None or isinstance(value, str):
            normalized[column] = value
        elif isinstance(value, (dict, list, tuple)):
            normalized[column] = canonical_json(value)
        else:
            normalized[column] = str(value)
    return normalized


def write_parquet_rows(
    path: Path,
    *,
    columns: Sequence[str],
    rows: Iterable[dict[str, object]],
    row_group_size: int = 50_000,
) -> Path:
    """Write normalized rows to an all-string Parquet table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([(column, pa.string()) for column in columns])
    writer = pq.ParquetWriter(path, schema, compression="zstd")
    batch: list[dict[str, str | None]] = []
    written = 0
    try:
        for row in rows:
            batch.append(_normalize_row(row, columns))
            if len(batch) >= row_group_size:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                written += len(batch)
                batch.clear()
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
            written += len(batch)
        if written == 0:
            writer.write_table(schema.empty_table())
    finally:
        writer.close()
    return path


def read_parquet_rows(path: Path) -> list[dict[str, object]]:
    """Read a small RefSpec reference table into dictionaries."""
    if not path.exists():
        return []
    return pq.read_table(path).to_pylist()
