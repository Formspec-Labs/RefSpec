"""Explicit acquisition for the pinned 1995 Federal Register thesaurus.

Importing this module never opens a network connection.  Network access occurs
only when a caller invokes :func:`acquire_content_addressed_source` or the
command-line entry point.  The downloaded bytes become visible in the store
only after their expected SHA-256 digest has been verified.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from refspec.registry.federal_register_thesaurus import (
    FEDERAL_REGISTER_THESAURUS_1995_URL,
)

FEDERAL_REGISTER_THESAURUS_1995_SHA256 = "sha256:d5e013336d4179790e8d6574d4dc9d8cfcb10ce76af202ff4db068617eb8fd30"
DEFAULT_FILENAME = "thesaurus-alpha.txt"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


class AcquisitionError(ValueError):
    """The explicit source acquisition failed closed."""


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    """One verified object in the content-addressed source store."""

    path: Path
    source_url: str
    resolved_url: str
    sha256: str
    byte_length: int
    cache_hit: bool


def _expected_hex(expected_sha256: str) -> str:
    match = _DIGEST.fullmatch(expected_sha256)
    if match is None:
        raise AcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
    return match.group(1)


def _validate_url(source_url: str) -> None:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AcquisitionError("source_url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise AcquisitionError("source_url must not contain credentials")


def _verify_existing(
    path: Path,
    *,
    source_url: str,
    expected_sha256: str,
) -> AcquiredSource:
    if path.is_symlink() or not path.is_file():
        raise AcquisitionError(f"content-addressed target is not a regular file: {path}")
    payload = path.read_bytes()
    actual = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise AcquisitionError(
            f"existing content-addressed object failed digest verification: expected {expected_sha256}, got {actual}"
        )
    return AcquiredSource(
        path=path,
        source_url=source_url,
        resolved_url=source_url,
        sha256=actual,
        byte_length=len(payload),
        cache_hit=True,
    )


def acquire_content_addressed_source(
    source_url: str,
    expected_sha256: str,
    store_dir: Path,
    *,
    filename: str = DEFAULT_FILENAME,
    timeout_seconds: float = 30.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> AcquiredSource:
    """Explicitly fetch, verify, and store one immutable source object.

    The final path is ``STORE/sha256/HEX/FILENAME``.  A digest mismatch or
    transfer failure removes the temporary file and leaves no final object.
    An already-present object is verified locally and returned without a
    network request.
    """

    _validate_url(source_url)
    digest_hex = _expected_hex(expected_sha256)
    if not filename or Path(filename).name != filename:
        raise AcquisitionError("filename must be one plain path component")
    if timeout_seconds <= 0:
        raise AcquisitionError("timeout_seconds must be positive")
    if max_bytes <= 0:
        raise AcquisitionError("max_bytes must be positive")

    store_dir = Path(store_dir)
    object_dir = store_dir / "sha256" / digest_hex
    final_path = object_dir / filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(
            final_path,
            source_url=source_url,
            expected_sha256=expected_sha256,
        )

    object_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".acquire-",
        suffix=".tmp",
        dir=object_dir,
    )
    temporary_path = Path(temporary_name)
    digest = hashlib.sha256()
    byte_length = 0
    resolved_url = source_url
    try:
        request = urllib.request.Request(
            source_url,
            headers={"User-Agent": "RefSpec explicit source resolver/1.0"},
            method="GET",
        )
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            try:
                response = urllib.request.urlopen(
                    request,
                    timeout=timeout_seconds,
                )
            except (OSError, urllib.error.URLError) as error:
                raise AcquisitionError(f"could not acquire {source_url}: {error}") from error
            with response:
                resolved_url = response.geturl()
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    byte_length += len(chunk)
                    if byte_length > max_bytes:
                        raise AcquisitionError(f"source exceeds max_bytes={max_bytes}")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())

        actual_sha256 = "sha256:" + digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise AcquisitionError(f"source digest mismatch: expected {expected_sha256}, got {actual_sha256}")
        try:
            os.link(temporary_path, final_path)
        except FileExistsError:
            return _verify_existing(
                final_path,
                source_url=source_url,
                expected_sha256=expected_sha256,
            )
        return AcquiredSource(
            path=final_path,
            source_url=source_url,
            resolved_url=resolved_url,
            sha256=actual_sha256,
            byte_length=byte_length,
            cache_hit=False,
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def acquire_federal_register_thesaurus_1995(
    store_dir: Path,
    *,
    timeout_seconds: float = 30.0,
) -> AcquiredSource:
    """Explicitly resolve the exact historical source pinned by RefSpec."""

    return acquire_content_addressed_source(
        FEDERAL_REGISTER_THESAURUS_1995_URL,
        FEDERAL_REGISTER_THESAURUS_1995_SHA256,
        store_dir,
        filename=DEFAULT_FILENAME,
        timeout_seconds=timeout_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Explicitly fetch and digest-verify the pinned 1995 Federal "
            "Register thesaurus into a content-addressed local store."
        )
    )
    parser.add_argument("store", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        acquired = acquire_federal_register_thesaurus_1995(
            args.store,
            timeout_seconds=args.timeout_seconds,
        )
    except AcquisitionError as error:
        parser.error(str(error))
    print(acquired.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
