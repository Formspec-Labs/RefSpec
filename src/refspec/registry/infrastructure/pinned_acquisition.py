"""Shared content-addressed acquisition for pinned vocabulary downloads.

Importing this module never opens a network connection. A caller must either
provide an existing local distribution or set ``allow_network=True``. In both
cases, RefSpec verifies the exact published byte length and SHA-256 digest
before making the object visible in the content-addressed store.

Domain modules keep their own error types and acquired-result dataclasses.
They call :func:`acquire_pinned_source` and remap :class:`PinnedAcquisitionError`
into the vocabulary-specific exception.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")

AcquisitionMode = Literal["cache", "local", "network"]
"""The canonical third-mode value here is ``"network"``: this module (and
callers that delegate to :func:`acquire_pinned_source`, such as the ELSST,
AGROVOC, EuroVoc, GEMET, and NASA Thesaurus adapters) opens the outbound
connection itself via ``urllib``, gated by an explicit ``allow_network``
flag. Import this type for any acquisition path that performs that network
call directly."""

FetcherAcquisitionMode = Literal["cache", "local", "fetcher"]
"""A second, deliberately distinct acquisition-mode shape used by the
per-domain code-list modules (e.g. ``federal_hierarchy_orgs.py``,
``pra_icr_codes.py``, and the rest of the ``fetcher``-pattern family). Those
modules never open a network connection themselves -- they require the
caller to inject a domain-specific ``Fetcher`` protocol object, so their
third mode is ``"fetcher"``, not ``"network"``. The two spellings are not
interchangeable: they record which side of the module boundary performed
the retrieval, which is meaningful provenance information, not incidental
naming drift. Import this type for any acquisition path built on an
injected fetcher rather than a direct ``urllib`` call."""


class PinnedAcquisitionError(ValueError):
    """A pinned source could not be acquired without weakening its pin."""


class PinnedSource(Protocol):
    """Minimum pin fields required by the content-addressed acquire pipeline."""

    @property
    def source_url(self) -> str: ...

    @property
    def expected_sha256(self) -> str: ...

    @property
    def expected_byte_length(self) -> int: ...

    @property
    def filename(self) -> str: ...


@dataclass(frozen=True, slots=True)
class PinnedAcquisitionLabels:
    """Domain-specific wording and HTTP headers for one acquire call site."""

    source_label: str
    cached_location: str
    local_file_label: str
    not_cached_message: str
    request_headers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class AcquiredPinnedSource:
    """One verified object in a content-addressed local store."""

    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    cache_hit: bool
    acquisition_mode: AcquisitionMode
    local_source_path: Path | None


def expected_digest_hex(expected_sha256: str) -> str:
    """Return the 64 lowercase hex digits from a ``sha256:<hex>`` pin."""

    match = _DIGEST.fullmatch(expected_sha256)
    if match is None:
        raise PinnedAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
    return match.group(1)


def verify_pinned_payload(
    payload: bytes,
    source: PinnedSource,
    *,
    location: str,
) -> tuple[str, int]:
    """Verify exact byte length and SHA-256 for an in-memory payload."""

    byte_length = len(payload)
    if byte_length != source.expected_byte_length:
        raise PinnedAcquisitionError(
            f"{location} byte length mismatch: expected {source.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual_sha256 != source.expected_sha256:
        raise PinnedAcquisitionError(
            f"{location} digest mismatch: expected {source.expected_sha256}, got {actual_sha256}"
        )
    return actual_sha256, byte_length


def _verify_existing(
    path: Path,
    source: PinnedSource,
    *,
    labels: PinnedAcquisitionLabels,
) -> AcquiredPinnedSource:
    if path.is_symlink() or not path.is_file():
        raise PinnedAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = verify_pinned_payload(
        path.read_bytes(),
        source,
        location=labels.cached_location,
    )
    return AcquiredPinnedSource(
        path=path,
        source_url=source.source_url,
        resolved_url=None,
        sha256=actual_sha256,
        byte_length=byte_length,
        cache_hit=True,
        acquisition_mode="cache",
        local_source_path=None,
    )


def _publish_stream(
    stream: BinaryIO,
    source: PinnedSource,
    final_path: Path,
    *,
    labels: PinnedAcquisitionLabels,
    acquisition_mode: Literal["local", "network"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredPinnedSource:
    object_dir = final_path.parent
    object_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".acquire-",
        suffix=".tmp",
        dir=object_dir,
    )
    temporary_path = Path(temporary_name)
    digest = hashlib.sha256()
    byte_length = 0
    try:
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                byte_length += len(chunk)
                if byte_length > source.expected_byte_length:
                    raise PinnedAcquisitionError(
                        f"{labels.source_label} exceeds expected byte length {source.expected_byte_length}"
                    )
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

        if byte_length != source.expected_byte_length:
            raise PinnedAcquisitionError(
                f"{labels.source_label} byte length mismatch: "
                f"expected {source.expected_byte_length}, got {byte_length}"
            )
        actual_sha256 = "sha256:" + digest.hexdigest()
        if actual_sha256 != source.expected_sha256:
            raise PinnedAcquisitionError(
                f"{labels.source_label} digest mismatch: "
                f"expected {source.expected_sha256}, got {actual_sha256}"
            )

        try:
            os.link(temporary_path, final_path)
        except FileExistsError:
            return _verify_existing(final_path, source, labels=labels)

        return AcquiredPinnedSource(
            path=final_path,
            source_url=source.source_url,
            resolved_url=resolved_url,
            sha256=actual_sha256,
            byte_length=byte_length,
            cache_hit=False,
            acquisition_mode=acquisition_mode,
            local_source_path=local_source_path,
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def acquire_pinned_source(
    source: PinnedSource,
    store_dir: Path,
    *,
    labels: PinnedAcquisitionLabels,
    source_path: Path | None = None,
    allow_network: bool = False,
    timeout_seconds: float = 60.0,
) -> AcquiredPinnedSource:
    """Resolve one pinned blob from cache, a local file, or the network.

    Cache lookup is always local. A supplied ``source_path`` is read locally.
    Otherwise, a cache miss fails unless ``allow_network`` is explicitly true.
    Every path is subject to the pin's exact byte-length and digest.
    """

    if timeout_seconds <= 0:
        raise PinnedAcquisitionError("timeout_seconds must be positive")

    digest_hex = expected_digest_hex(source.expected_sha256)
    final_path = Path(store_dir) / "sha256" / digest_hex / source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, source, labels=labels)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise PinnedAcquisitionError(
                f"{labels.local_file_label} is not a regular file: {local_path}"
            )
        with local_path.open("rb") as opened:
            return _publish_stream(
                opened,
                source,
                final_path,
                labels=labels,
                acquisition_mode="local",
                resolved_url=None,
                local_source_path=local_path.resolve(),
            )

    if not allow_network:
        raise PinnedAcquisitionError(labels.not_cached_message)

    request = urllib.request.Request(
        source.source_url,
        headers=dict(labels.request_headers),
        method="GET",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
    except (OSError, urllib.error.URLError) as error:
        raise PinnedAcquisitionError(f"could not acquire {source.source_url}: {error}") from error
    with response:
        return _publish_stream(
            response,
            source,
            final_path,
            labels=labels,
            acquisition_mode="network",
            resolved_url=response.geturl(),
            local_source_path=None,
        )
