"""Shared canonical JSON and digest helpers for registry package artifacts.

SCR and MVB both seal package artifacts with newline-terminated canonical JSON
lines and ``sha256:<hex>`` digests. Source-artifact *paths* intentionally
differ: SCR fingerprints a newline-terminated identity document, while MVB
fingerprints the same object without the trailing newline. Callers must pick
the path helper that matches their package contract.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from refspec.storage import canonical_json

SourceArtifactPathStyle = Literal["scr", "mvb"]


def plain_json(value: Any) -> Any:
    """Return a JSON-plain copy of mappings and sequences."""

    if isinstance(value, Mapping):
        return {str(key): plain_json(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [plain_json(child) for child in value]
    return value


def canonical_json_bytes(value: object) -> bytes:
    """Encode one value as newline-terminated canonical JSON bytes."""

    return canonical_json(plain_json(value)).encode("utf-8") + b"\n"


def canonical_jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Encode rows as concatenated newline-terminated canonical JSON lines."""

    return b"".join(canonical_json_bytes(row) for row in rows)


def sha256_digest(payload: bytes) -> str:
    """Return a lowercase ``sha256:<64 hex>`` digest for exact bytes."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    """Hash one file's bytes without loading the whole file into memory.

    Imported by ``tools/build_usc_popular_names.py`` and
    ``tools/build_usc_source_credits.py`` since 2026-08-31 (the tools live in
    the repo and may depend on src/). Still restated identically -- not
    imported -- in ``bindings/atlas/3.1/tools/validate.py``, whose bytes are
    pinned by the fixtures receipt and which must run without this package.
    """

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def path_sha256_descriptor(path: str, payload: bytes) -> dict[str, str]:
    """Return the minimal ``{path, sha256}`` artifact descriptor."""

    return {"path": path, "sha256": sha256_digest(payload)}


def source_artifact_path(
    identifier: str,
    payload: bytes,
    *,
    style: SourceArtifactPathStyle,
) -> str:
    """Return the deterministic ``sources/source-<fingerprint>.bin`` path.

    ``style="scr"`` seals the identity with :func:`canonical_json_bytes`
    (trailing newline). ``style="mvb"`` seals with bare canonical JSON bytes
    (no trailing newline). The two styles must not be mixed across packages.
    """

    identity_object = {
        "id": identifier,
        "sha256": sha256_digest(payload),
        "byteLength": len(payload),
    }
    if style == "scr":
        identity = canonical_json_bytes(identity_object)
    else:
        identity = canonical_json(identity_object).encode("utf-8")
    return f"sources/source-{hashlib.sha256(identity).hexdigest()}.bin"


__all__ = [
    "SourceArtifactPathStyle",
    "canonical_json_bytes",
    "canonical_jsonl_bytes",
    "file_sha256",
    "path_sha256_descriptor",
    "plain_json",
    "sha256_digest",
    "source_artifact_path",
]
