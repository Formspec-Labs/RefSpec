"""Frozen BILLSTATUS acquisition checks from RefSpec 6394722613873bfbbd8e68a708644e4839c38fb6.

Only public data/error types are imported. Acquisition and verification logic
remain the old independent implementation, including its named-file layout.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from refspec.registry.billstatus_codes import (
    AcquiredBillStatusSource,
    BillStatusAcquisitionError,
    BillStatusFetcher,
    BillStatusSnapshotPin,
    BillStatusSourceDriftError,
)

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
        raise BillStatusAcquisitionError("fetcher resolved_url must remain on official HTTPS raw.githubusercontent.com")
    if parsed.username is not None or parsed.password is not None:
        raise BillStatusAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: BillStatusSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise BillStatusSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise BillStatusSourceDriftError(
            f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}"
        )
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BillStatusSourceDriftError(f"{location} is not valid UTF-8 text") from error
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: BillStatusSnapshotPin) -> AcquiredBillStatusSource:
    if path.is_symlink() or not path.is_file():
        raise BillStatusAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached BILLSTATUS source",
    )
    return AcquiredBillStatusSource(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type="text/plain",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: BillStatusSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredBillStatusSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} BILLSTATUS source",
    )
    final_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".acquire-",
        suffix=".tmp",
        dir=final_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary_path, final_path)
        except FileExistsError:
            return _verify_existing(final_path, pin)
        return AcquiredBillStatusSource(
            pin=pin,
            path=final_path,
            sha256=actual_sha256,
            byte_length=byte_length,
            source_url=pin.source.source_url,
            resolved_url=resolved_url,
            content_type=content_type,
            acquisition_mode=acquisition_mode,
            cache_hit=False,
            local_source_path=local_source_path,
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def acquire_billstatus_source(
    pin: BillStatusSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: BillStatusFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredBillStatusSource:
    """Acquire the exact user-guide response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise BillStatusAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise BillStatusAcquisitionError("provide source_path or fetcher, not both")
    digest_match = _DIGEST.fullmatch(pin.expected_sha256)
    if digest_match is None:
        raise BillStatusAcquisitionError("pin.expected_sha256 must be a lowercase sha256:<64 hex> digest")
    digest_hex = digest_match.group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise BillStatusAcquisitionError(f"local BILLSTATUS source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="text/plain",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise BillStatusAcquisitionError(
            "the BILLSTATUS user guide is not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise BillStatusAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/plain", "text/markdown"}:
        raise BillStatusSourceDriftError(f"BILLSTATUS user guide content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )
