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
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from refspec.registry.infrastructure.pinned_acquisition import (
    AcquiredPinnedSource,
    AcquisitionMode,
    PinnedAcquisitionError,
    PinnedAcquisitionLabels,
    acquire_pinned_source,
    expected_digest_hex,
)

ELSST_LICENSE_IRI = "https://creativecommons.org/licenses/by-sa/4.0/"
ELSST_LICENSE_LABEL = "Creative Commons Attribution-ShareAlike 4.0 International"
ELSST_ATTRIBUTION = "Consortium of European Social Science Data Archives (CESSDA) and its national Service Providers"
ELSST_PUBLISHER = "CESSDA ERIC"

_ELSST_ACQUIRE_LABELS = PinnedAcquisitionLabels(
    source_label="ELSST source",
    cached_location="cached ELSST source",
    local_file_label="local ELSST source",
    not_cached_message=(
        "ELSST source is not cached; provide source_path or set allow_network=True explicitly"
    ),
    request_headers={"User-Agent": "RefSpec explicit ELSST source resolver/1.0"},
)


class ElsstAcquisitionError(ValueError):
    """An ELSST source could not be acquired without weakening its pin."""


def _require_absolute_iri(value: str, label: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme:
        raise ElsstAcquisitionError(f"{label} must be an absolute IRI")


def _expected_hex(expected_sha256: str) -> str:
    try:
        return expected_digest_hex(expected_sha256)
    except PinnedAcquisitionError as error:
        raise ElsstAcquisitionError(str(error)) from error


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


ELSST_R6 = ElsstReleaseSource(
    version="6",
    release_iri="https://elsst.cessda.eu/id/6",
    concept_scheme_iri="https://elsst.cessda.eu/id/6/",
    source_url="https://storage.googleapis.com/cessda-elsst-datadump/2025/ELSST_R6.ttl",
    expected_sha256="sha256:c362aec545db916ecb67af0eb9b8b4cecac1cb2118a717b69d8e6dad5591aa95",
    expected_byte_length=19_915_491,
    filename="ELSST_R6.ttl",
)
ELSST_RELEASES = {"6": ELSST_R6}


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


def _as_acquired_elsst(release: ElsstReleaseSource, acquired: AcquiredPinnedSource) -> AcquiredElsstSource:
    return AcquiredElsstSource(
        release=release,
        path=acquired.path,
        source_url=acquired.source_url,
        resolved_url=acquired.resolved_url,
        sha256=acquired.sha256,
        byte_length=acquired.byte_length,
        cache_hit=acquired.cache_hit,
        acquisition_mode=acquired.acquisition_mode,
        local_source_path=acquired.local_source_path,
    )


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

    try:
        acquired = acquire_pinned_source(
            release,
            store_dir,
            labels=_ELSST_ACQUIRE_LABELS,
            source_path=source_path,
            allow_network=allow_network,
            timeout_seconds=timeout_seconds,
        )
    except PinnedAcquisitionError as error:
        raise ElsstAcquisitionError(str(error)) from error
    return _as_acquired_elsst(release, acquired)


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
