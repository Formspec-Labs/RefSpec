"""Explicit, verified acquisition for pinned ELSST Turtle distributions.

Importing this module never opens a network connection. A caller must either
provide an existing local distribution or set ``allow_network=True``. In both
cases, RefSpec verifies the exact published byte length and SHA-256 digest
before making the object visible in the content-addressed store.

The ELSST attribution and CC BY-SA 4.0 license are retained as source metadata.
They describe the publication; they do not act as a runtime authorization gate.
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
from typing import BinaryIO, Literal

ELSST_LICENSE_IRI = "https://creativecommons.org/licenses/by-sa/4.0/"
ELSST_LICENSE_LABEL = "Creative Commons Attribution-ShareAlike 4.0 International"
ELSST_ATTRIBUTION = "Consortium of European Social Science Data Archives (CESSDA) and its national Service Providers"
ELSST_PUBLISHER = "CESSDA ERIC"

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")

AcquisitionMode = Literal["cache", "local", "network"]


class ElsstAcquisitionError(ValueError):
    """An ELSST source could not be acquired without weakening its pin."""


def _require_absolute_iri(value: str, label: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme:
        raise ElsstAcquisitionError(f"{label} must be an absolute IRI")


def _expected_hex(expected_sha256: str) -> str:
    match = _DIGEST.fullmatch(expected_sha256)
    if match is None:
        raise ElsstAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
    return match.group(1)


def _validate_source_url(source_url: str) -> None:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ElsstAcquisitionError("source_url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ElsstAcquisitionError("source_url must not contain credentials")


@dataclass(frozen=True, slots=True)
class ElsstReleaseSource:
    """One exact, externally published ELSST Turtle distribution."""

    version: str
    release_iri: str
    concept_scheme_iri: str
    source_url: str
    expected_sha256: str
    expected_byte_length: int
    filename: str
    publisher: str = ELSST_PUBLISHER
    attribution: str = ELSST_ATTRIBUTION
    license_iri: str = ELSST_LICENSE_IRI
    license_label: str = ELSST_LICENSE_LABEL

    def __post_init__(self) -> None:
        if not self.version:
            raise ElsstAcquisitionError("version must not be empty")
        _require_absolute_iri(self.release_iri, "release_iri")
        _require_absolute_iri(self.concept_scheme_iri, "concept_scheme_iri")
        _validate_source_url(self.source_url)
        _expected_hex(self.expected_sha256)
        if self.expected_byte_length <= 0:
            raise ElsstAcquisitionError("expected_byte_length must be positive")
        if not self.filename or Path(self.filename).name != self.filename:
            raise ElsstAcquisitionError("filename must be one plain path component")
        _require_absolute_iri(self.license_iri, "license_iri")
        if not self.publisher or not self.attribution or not self.license_label:
            raise ElsstAcquisitionError("publisher, attribution, and license_label must not be empty")


ELSST_R5 = ElsstReleaseSource(
    version="5",
    release_iri="https://elsst.cessda.eu/id/5",
    concept_scheme_iri="https://elsst.cessda.eu/id/5/",
    source_url="https://storage.googleapis.com/cessda-elsst-datadump/2024/ELSST_R5.ttl",
    expected_sha256="sha256:d0d2514d7535309b82cc6966ee6e2b5794cf6f390896a5175f41dff4a02e03b7",
    expected_byte_length=19_167_985,
    filename="ELSST_R5.ttl",
)
ELSST_R6 = ElsstReleaseSource(
    version="6",
    release_iri="https://elsst.cessda.eu/id/6",
    concept_scheme_iri="https://elsst.cessda.eu/id/6/",
    source_url="https://storage.googleapis.com/cessda-elsst-datadump/2025/ELSST_R6.ttl",
    expected_sha256="sha256:c362aec545db916ecb67af0eb9b8b4cecac1cb2118a717b69d8e6dad5591aa95",
    expected_byte_length=19_915_491,
    filename="ELSST_R6.ttl",
)
ELSST_RELEASES = {"5": ELSST_R5, "6": ELSST_R6}


@dataclass(frozen=True, slots=True)
class AcquiredElsstSource:
    """One verified ELSST object in a content-addressed local store."""

    release: ElsstReleaseSource
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    cache_hit: bool
    acquisition_mode: AcquisitionMode
    local_source_path: Path | None


def _verify_payload(
    payload: bytes,
    release: ElsstReleaseSource,
    *,
    location: str,
) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != release.expected_byte_length:
        raise ElsstAcquisitionError(
            f"{location} byte length mismatch: expected {release.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual_sha256 != release.expected_sha256:
        raise ElsstAcquisitionError(
            f"{location} digest mismatch: expected {release.expected_sha256}, got {actual_sha256}"
        )
    return actual_sha256, byte_length


def _verify_existing(path: Path, release: ElsstReleaseSource) -> AcquiredElsstSource:
    if path.is_symlink() or not path.is_file():
        raise ElsstAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        release,
        location="cached ELSST source",
    )
    return AcquiredElsstSource(
        release=release,
        path=path,
        source_url=release.source_url,
        resolved_url=None,
        sha256=actual_sha256,
        byte_length=byte_length,
        cache_hit=True,
        acquisition_mode="cache",
        local_source_path=None,
    )


def _publish_stream(
    stream: BinaryIO,
    release: ElsstReleaseSource,
    final_path: Path,
    *,
    acquisition_mode: Literal["local", "network"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredElsstSource:
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
                if byte_length > release.expected_byte_length:
                    raise ElsstAcquisitionError(
                        f"ELSST source exceeds expected byte length {release.expected_byte_length}"
                    )
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

        if byte_length != release.expected_byte_length:
            raise ElsstAcquisitionError(
                f"ELSST source byte length mismatch: expected {release.expected_byte_length}, got {byte_length}"
            )
        actual_sha256 = "sha256:" + digest.hexdigest()
        if actual_sha256 != release.expected_sha256:
            raise ElsstAcquisitionError(
                f"ELSST source digest mismatch: expected {release.expected_sha256}, got {actual_sha256}"
            )

        try:
            os.link(temporary_path, final_path)
        except FileExistsError:
            return _verify_existing(final_path, release)

        return AcquiredElsstSource(
            release=release,
            path=final_path,
            source_url=release.source_url,
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


def acquire_elsst_release(
    release: ElsstReleaseSource,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    allow_network: bool = False,
    timeout_seconds: float = 60.0,
) -> AcquiredElsstSource:
    """Resolve one pinned ELSST release from cache, a local file, or the network.

    Cache lookup is always local. A supplied ``source_path`` is read locally.
    Otherwise, a cache miss fails unless ``allow_network`` is explicitly true.
    Every path is subject to the release's exact byte-length and digest pins.
    """

    if timeout_seconds <= 0:
        raise ElsstAcquisitionError("timeout_seconds must be positive")

    digest_hex = _expected_hex(release.expected_sha256)
    final_path = Path(store_dir) / "sha256" / digest_hex / release.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, release)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise ElsstAcquisitionError(f"local ELSST source is not a regular file: {local_path}")
        with local_path.open("rb") as source:
            return _publish_stream(
                source,
                release,
                final_path,
                acquisition_mode="local",
                resolved_url=None,
                local_source_path=local_path.resolve(),
            )

    if not allow_network:
        raise ElsstAcquisitionError(
            "ELSST source is not cached; provide source_path or set allow_network=True explicitly"
        )

    request = urllib.request.Request(
        release.source_url,
        headers={"User-Agent": "RefSpec explicit ELSST source resolver/1.0"},
        method="GET",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
    except (OSError, urllib.error.URLError) as error:
        raise ElsstAcquisitionError(f"could not acquire {release.source_url}: {error}") from error
    with response:
        return _publish_stream(
            response,
            release,
            final_path,
            acquisition_mode="network",
            resolved_url=response.geturl(),
            local_source_path=None,
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Acquire one exact ELSST Turtle release into a content-addressed local store."
    )
    parser.add_argument("version", choices=tuple(ELSST_RELEASES))
    parser.add_argument("store", type=Path)
    parser.add_argument("--source-path", type=Path)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        acquired = acquire_elsst_release(
            ELSST_RELEASES[args.version],
            args.store,
            source_path=args.source_path,
            allow_network=args.allow_network,
            timeout_seconds=args.timeout_seconds,
        )
    except ElsstAcquisitionError as error:
        parser.error(str(error))
    print(acquired.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
