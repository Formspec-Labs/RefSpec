"""Small, transformation-free helpers for authenticating pinned input bytes."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from os import stat_result
from pathlib import Path

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _validate_expected_pin(label: str, expected_sha256: str, expected_byte_length: int) -> None:
    if _SHA256.fullmatch(expected_sha256) is None:
        raise ValueError(f"invalid expected SHA-256 for {label}: {expected_sha256!r}")
    if (
        not isinstance(expected_byte_length, int)
        or isinstance(expected_byte_length, bool)
        or expected_byte_length < 0
    ):
        raise ValueError(f"invalid expected byte length for {label}: {expected_byte_length}")


def _regular_file_identity(path: Path, label: str) -> tuple[int, int]:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError(f"pinned input is missing or unsafe: {label}") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"pinned input is missing or unsafe: {label}")
    return metadata.st_dev, metadata.st_ino


def _snapshot_identity(metadata: stat_result) -> tuple[int, int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns


def _verify_observed_pin(
    label: str,
    expected_sha256: str,
    expected_byte_length: int,
    observed_sha256: str,
    observed_byte_length: int,
) -> None:
    if observed_sha256 != expected_sha256 or observed_byte_length != expected_byte_length:
        raise ValueError(
            f"pinned input differs (input pin differs) for {label}: "
            f"expected=({expected_byte_length}, {expected_sha256}), "
            f"observed=({observed_byte_length}, {observed_sha256})"
        )


def verify_file_pin(
    path: Path,
    *,
    expected_sha256: str,
    expected_byte_length: int,
    logical_path: str | None = None,
) -> tuple[str, int]:
    """Verify one regular file without interpreting or transforming its contents."""

    label = logical_path or path.as_posix()
    _validate_expected_pin(label, expected_sha256, expected_byte_length)
    path_identity = _regular_file_identity(path, label)

    digest = hashlib.sha256()
    observed_byte_length = 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != path_identity:
            raise ValueError(f"pinned input changed before it was read: {label}")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            observed_byte_length += len(block)
        after = os.fstat(stream.fileno())
    if _snapshot_identity(before) != _snapshot_identity(after):
        raise ValueError(f"pinned input changed while it was read: {label}")
    observed_sha256 = "sha256:" + digest.hexdigest()
    _verify_observed_pin(
        label,
        expected_sha256,
        expected_byte_length,
        observed_sha256,
        observed_byte_length,
    )
    return observed_sha256, observed_byte_length


def read_verified_file_pin(
    path: Path,
    *,
    expected_sha256: str,
    expected_byte_length: int,
    logical_path: str | None = None,
) -> bytes:
    """Read and authenticate one immutable byte snapshot for immediate parsing."""

    label = logical_path or path.as_posix()
    _validate_expected_pin(label, expected_sha256, expected_byte_length)
    path_identity = _regular_file_identity(path, label)

    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != path_identity:
            raise ValueError(f"pinned input changed before it was read: {label}")
        payload = stream.read()
        after = os.fstat(stream.fileno())
    if _snapshot_identity(before) != _snapshot_identity(after):
        raise ValueError(f"pinned input changed while it was read: {label}")

    observed_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    observed_byte_length = len(payload)
    _verify_observed_pin(
        label,
        expected_sha256,
        expected_byte_length,
        observed_sha256,
        observed_byte_length,
    )
    return payload
