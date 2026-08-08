"""Shared byte-exact helpers for derived Atlas Parquet artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pyarrow as pa

from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

PARQUET_MEMBER_FIELDS = frozenset(
    {
        "byteLength",
        "mediaType",
        "path",
        "role",
        "rowCount",
        "schemaDigest",
        "sha256",
    }
)


def artifact_file_paths(directory: Path) -> set[str]:
    """Return every regular-file and symlink path below an artifact root."""

    return {
        path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file() or path.is_symlink()
    }


def file_sha256(path: Path) -> str:
    """Hash one file without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonical_payload_sha256(value: object) -> str:
    """Hash canonical JSON without its transport newline."""

    return sha256_digest(canonical_json_bytes(value)[:-1])


def arrow_schema_sha256(schema: pa.Schema) -> str:
    """Hash Arrow's stable binary schema serialization."""

    return sha256_digest(schema.serialize().to_pybytes())


__all__ = [
    "PARQUET_MEMBER_FIELDS",
    "arrow_schema_sha256",
    "artifact_file_paths",
    "canonical_payload_sha256",
    "file_sha256",
]
