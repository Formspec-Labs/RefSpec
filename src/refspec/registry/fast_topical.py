"""Locally captured OCLC FAST topical facet CSV rows for mapping-only use.

OCLC's official FAST download page names three bulk formats for the Topical
facet: MARC, MARCXML, and RDF N-Triples. It names no CSV artifact, and the
bulk-data host (researchworks.oclc.org) returned a Cloudflare bot-block
response to an automated request during development, so no official byte
stream could be captured for this module. RefSpec's local topical extract is
therefore treated as a CSV rendering supplied by the caller from one of the
official formats through a step outside this module. Acquisition accepts only
that local file: no fetcher exists here because no official CSV endpoint is
documented, and importing this module never opens a network connection.

The catalog assigns FAST a mapping-only role: search expansion and reviewed
cross-vocabulary mappings, never a reserved classifier output slot and never
a promoted concept scheme. FAST does publish stable per-heading identifiers
(the "fst" id and its id.worldcat.org URI), so this module preserves them
exactly as observed instead of minting new identity. Every package built here
inherits the ``source_controlled_resource`` development-only usage ceiling,
which structurally forbids concept-scheme promotion and accepted-output use.

FAST (Faceted Application of Subject Terminology) Data is made available by
OCLC Online Computer Library Center, Inc. under the Open Data Commons
Attribution License (ODC-BY), which requires attribution.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from refspec.registry.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)

FAST_PUBLISHER = "OCLC Online Computer Library Center, Inc."
FAST_LANDING_PAGE_URL = "https://www.oclc.org/research/areas/data-science/fast/download.html"
FAST_LICENSE_URL = "https://www.oclc.org/research/activities/fast/odcby.html"
# The official download landing page, captured 2026-08-04 through the
# project's Zyte transport after direct fetches were Cloudflare-blocked.
# Reference-only provenance for the artifact catalog the page publishes
# (fixture ``fast-download-landing-2026-08-04.html``); never parsed at runtime.
FAST_LANDING_PAGE_CAPTURE_SHA256 = "sha256:d9a49e0ddbaffde84ac6eae124b388b6748fc261bd7281a7e386aba54df1cd79"
FAST_LANDING_PAGE_CAPTURE_BYTE_LENGTH = 56_875
FAST_LANDING_PAGE_CAPTURE_RETRIEVED_AT = "2026-08-04T00:12:00Z"
# The official Topical bulk file WAS acquired once: the sibling spicy-regs
# fused-concept-registry run ingested ``FASTTopical.nt.zip`` and recorded this
# exact pin in ``output/fused-concept-registry-v1/manifest.json`` (retrieved
# 2026-07-27; raw bytes since deleted with that session's scratchpad). A
# future re-acquisition must match it or explain the publisher's change.
# Re-fetch attempts on 2026-08-04 failed: direct curl received a Cloudflare
# 403 and the Zyte raw-HTTP transport received HTTP 520 three times.
FAST_TOPICAL_BULK_NT_ZIP_URL = "https://researchworks.oclc.org/researchdata/fast/FASTTopical.nt.zip"
FAST_TOPICAL_BULK_NT_ZIP_SHA256 = "sha256:217826c90649895bfca71e81e2ed88919b2e061646ec42a185bc12d0bd3c19db"
FAST_TOPICAL_BULK_NT_ZIP_BYTE_LENGTH = 55_099_212
FAST_TOPICAL_BULK_NT_ZIP_RETRIEVED_AT = "2026-07-27"
# NEW VERIFIED FINDING (2026-08-04): unlike the bulk-data host, OCLC's own
# Linked Data and searchFAST suggest API tier carries no bot wall and needs
# no key. Two channels were checked live and pinned below.
#
# (1) Per-term Linked Data: id.worldcat.org answers a numeric FAST id with
#     RDF/XML at the ``.rdf.xml`` path suffix and stable rdf:about URIs.
#     Only that suffix answered; ``.json``, ``.ttl``, and ``.jsonld`` all came
#     back HTTP 404 on the same live check.
FAST_TERM_RDF_URL_PATTERN = "https://id.worldcat.org/fast/{numeric_id}.rdf.xml"
FAST_TERM_RDF_CAPTURE_SHA256 = "sha256:88940a98a42dca5605f06aef661c07f3591dcc82be32dcd1fbcae2d782318553"
FAST_TERM_RDF_CAPTURE_BYTE_LENGTH = 3_806
FAST_TERM_RDF_CAPTURE_RETRIEVED_AT = "2026-08-04T00:50:00Z"

# (2) The searchFAST suggest API answers term-prefix lookups as CORS-open
#     JSON, also with no key.
FAST_SUGGEST_API_URL_PATTERN = (
    "https://fast.oclc.org/searchfast/fastsuggest?query={query}&queryIndex=suggestall&rows={rows}"
)
FAST_SUGGEST_CAPTURE_SHA256 = "sha256:309c71da16146beabb187199ce03716e7f2e5aec7a9585bc2dbcee1a5df661cd"
FAST_SUGGEST_CAPTURE_BYTE_LENGTH = 352
FAST_SUGGEST_CAPTURE_RETRIEVED_AT = "2026-08-04T00:50:00Z"

# The suggest API's response on 2026-08-04 carried an x-ratelimit-limit-day
# header value of 10,000. This was observed on that one response header, not
# published anywhere as OCLC's documented policy, so it may change without
# notice. At this ceiling a full-vocabulary crawl through the per-term
# channel would take weeks of continuous daily-capped calls rather than a
# single acquisition run.
FAST_SUGGEST_API_OBSERVED_DAILY_RATE_LIMIT = 10_000
FAST_URI_BASE = "http://id.worldcat.org/fast/"
FAST_IDENTIFIER_AUTHORITY_URI = FAST_URI_BASE
FAST_ATTRIBUTION_NOTICE = (
    "This work contains information from FAST (Faceted Application of Subject "
    "Terminology) Data which is made available by OCLC Online Computer Library "
    "Center, Inc. under the ODC Attribution License."
)

# Observed on the official download page on 2026-08-03; no CSV format is offered.
FAST_TOPICAL_OFFICIAL_BULK_FORMATS = ("marc", "marcxml", "ntriples")
# The project's documented full topical extract; individual captures pinned
# through this module are development-scale samples and will not match it.
FAST_TOPICAL_DOCUMENTED_ROW_COUNT = 440_599
FAST_TOPICAL_RESOURCE_ID = "fast-topical-facet"

ResourceUse = Literal["searchExpansion"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_HEADER = ("fast_id", "uri", "heading")
_FAST_ID = re.compile(r"^fst(\d{6,10})$")
_CHUNK_BYTES = 1 << 20


class FASTTopicalError(ValueError):
    """Base class for FAST topical extract failures."""


class FASTTopicalAcquisitionError(FASTTopicalError):
    """The local FAST topical CSV extract could not be acquired safely."""


class FASTTopicalSourceDriftError(FASTTopicalError):
    """A FAST topical CSV extract no longer matches its pin or documented shape."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _digest_hex(value: str, *, label: str) -> str:
    match = _DIGEST.fullmatch(value)
    if match is None:
        raise FASTTopicalAcquisitionError(f"{label} must be a lowercase sha256:<64 hex> digest")
    return match.group(1)


def _digest_and_length(path: Path) -> tuple[str, int]:
    """Hash and measure a file by streaming it, never holding it fully in memory."""

    hasher = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            hasher.update(chunk)
            length += len(chunk)
    return "sha256:" + hasher.hexdigest(), length


@dataclass(frozen=True, slots=True)
class FASTTopicalExtractPin:
    """Exact identity of one locally captured FAST topical CSV extract."""

    filename: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    expected_row_count: int

    def __post_init__(self) -> None:
        _digest_hex(self.expected_sha256, label="expected_sha256")
        if not self.filename or Path(self.filename).name != self.filename:
            raise FASTTopicalAcquisitionError("filename must be one plain path component")
        if not self.retrieved_at:
            raise FASTTopicalAcquisitionError("retrieved_at must not be empty")
        if self.expected_byte_length <= 0:
            raise FASTTopicalAcquisitionError("expected_byte_length must be positive")
        if self.expected_row_count <= 0:
            raise FASTTopicalAcquisitionError("expected_row_count must be positive")


AcquisitionMode = Literal["cache", "local"]


@dataclass(frozen=True, slots=True)
class AcquiredFASTTopicalExtract:
    """One verified FAST topical CSV extract in the content-addressed store."""

    pin: FASTTopicalExtractPin
    path: Path
    sha256: str
    byte_length: int
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def _verify_existing(
    path: Path,
    pin: FASTTopicalExtractPin,
) -> AcquiredFASTTopicalExtract:
    if path.is_symlink() or not path.is_file():
        raise FASTTopicalAcquisitionError(f"content-addressed target is not a regular file: {path}")
    digest, length = _digest_and_length(path)
    if length != pin.expected_byte_length:
        raise FASTTopicalSourceDriftError(
            f"cached FAST topical extract byte length drift: expected {pin.expected_byte_length}, got {length}"
        )
    if digest != pin.expected_sha256:
        raise FASTTopicalSourceDriftError(
            f"cached FAST topical extract digest drift: expected {pin.expected_sha256}, got {digest}"
        )
    return AcquiredFASTTopicalExtract(
        pin=pin,
        path=path,
        sha256=digest,
        byte_length=length,
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def acquire_fast_topical_extract(
    pin: FASTTopicalExtractPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
) -> AcquiredFASTTopicalExtract:
    """Acquire one locally supplied FAST topical CSV extract by content address.

    OCLC publishes no CSV endpoint for this facet, so acquisition never opens
    a network connection: it only content-addresses and re-verifies bytes the
    caller already retrieved.
    """

    digest_hex = _digest_hex(pin.expected_sha256, label="pin.expected_sha256")
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is None:
        raise FASTTopicalAcquisitionError(
            "FAST topical extract is not cached; provide source_path to a local CSV capture"
        )
    local_path = Path(source_path)
    if local_path.is_symlink() or not local_path.is_file():
        raise FASTTopicalAcquisitionError(f"local FAST topical source is not a regular file: {local_path}")

    final_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".acquire-",
        suffix=".tmp",
        dir=final_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        hasher = hashlib.sha256()
        length = 0
        with local_path.open("rb") as source, os.fdopen(descriptor, "wb") as destination:
            descriptor = -1
            for chunk in iter(lambda: source.read(_CHUNK_BYTES), b""):
                hasher.update(chunk)
                length += len(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        digest = "sha256:" + hasher.hexdigest()
        if length != pin.expected_byte_length:
            raise FASTTopicalSourceDriftError(
                f"local FAST topical extract byte length drift: expected {pin.expected_byte_length}, got {length}"
            )
        if digest != pin.expected_sha256:
            raise FASTTopicalSourceDriftError(
                f"local FAST topical extract digest drift: expected {pin.expected_sha256}, got {digest}"
            )
        try:
            os.link(temporary_path, final_path)
        except FileExistsError:
            return _verify_existing(final_path, pin)
        return AcquiredFASTTopicalExtract(
            pin=pin,
            path=final_path,
            sha256=digest,
            byte_length=length,
            acquisition_mode="local",
            cache_hit=False,
            local_source_path=local_path.resolve(),
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class FASTTopicalRow:
    """One parsed, digest-provenanced FAST topical CSV row."""

    source_ordinal: int
    fast_id: str
    uri: str
    heading: str


def _parse_row(raw_row: Sequence[str], ordinal: int) -> FASTTopicalRow:
    if len(raw_row) != len(_HEADER):
        raise FASTTopicalSourceDriftError(
            f"FAST topical extract row {ordinal} has {len(raw_row)} fields, expected {len(_HEADER)}"
        )
    fast_id, uri, heading = raw_row
    match = _FAST_ID.fullmatch(fast_id)
    if match is None:
        raise FASTTopicalSourceDriftError(f"FAST topical extract row {ordinal} has malformed fast_id {fast_id!r}")
    expected_uri = f"{FAST_URI_BASE}{int(match.group(1))}"
    if uri != expected_uri:
        raise FASTTopicalSourceDriftError(
            f"FAST topical extract row {ordinal} uri {uri!r} does not match fast_id {fast_id!r}"
        )
    if not heading or heading != heading.strip():
        raise FASTTopicalSourceDriftError(f"FAST topical extract row {ordinal} has malformed heading")
    return FASTTopicalRow(source_ordinal=ordinal, fast_id=fast_id, uri=uri, heading=heading)


def iter_fast_topical_rows(path: Path) -> Iterator[FASTTopicalRow]:
    """Stream one topical row at a time; never materializes the whole file."""

    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = tuple(next(reader))
        except StopIteration as error:
            raise FASTTopicalSourceDriftError("FAST topical extract is empty; expected a header row") from error
        if header != _HEADER:
            raise FASTTopicalSourceDriftError(f"FAST topical extract header drifted: {header!r}")
        for ordinal, raw_row in enumerate(reader, start=1):
            yield _parse_row(raw_row, ordinal)


@dataclass(frozen=True, slots=True)
class ParsedFASTTopicalExtract:
    """A parsed, digest-pinned FAST topical CSV extract."""

    pin: FASTTopicalExtractPin
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    rows: tuple[FASTTopicalRow, ...]
    documented_total_row_count: int
    gaps: tuple[str, ...]


FAST_TOPICAL_GAPS = (
    (
        "OCLC's official FAST download page publishes the Topical facet only as "
        "MARC, MARCXML, and RDF N-Triples bulk files; no official CSV byte source "
        "exists to pin directly. The N-Triples bulk zip's exact digest IS known "
        "(FAST_TOPICAL_BULK_NT_ZIP_SHA256, from the sibling spicy-regs "
        "fused-concept-registry manifest, retrieved 2026-07-27), but its raw "
        "bytes are not currently on disk and re-acquisition is blocked by the "
        "host's bot wall for both direct and Zyte raw-HTTP transports."
    ),
    (
        "The bulk-data host (researchworks.oclc.org) returned a Cloudflare "
        "bot-block response to an automated request on 2026-08-03; this module "
        "accepts only a locally supplied CSV rendering. On 2026-08-04 the "
        "official download landing page itself was captured through the "
        "project's Zyte transport (pinned at "
        "FAST_LANDING_PAGE_CAPTURE_SHA256); the bulk artifacts it links "
        "remain unfetched."
    ),
    (
        "The project's documented full topical extract has "
        f"{FAST_TOPICAL_DOCUMENTED_ROW_COUNT:,} rows; a single package built by "
        "this module reflects only the rows in its own pinned capture."
    ),
    (
        "A verified bot-wall-free channel exists alongside the blocked bulk "
        "host: OCLC's per-term Linked Data at id.worldcat.org answers a "
        "numeric FAST id with RDF/XML at the .rdf.xml path suffix only "
        "(FAST_TERM_RDF_URL_PATTERN), confirmed live on 2026-08-04 with no "
        "bot wall and no key. Its one observed response header put the "
        "daily cap at "
        f"{FAST_SUGGEST_API_OBSERVED_DAILY_RATE_LIMIT:,} "
        "(FAST_SUGGEST_API_OBSERVED_DAILY_RATE_LIMIT, not published policy); "
        "at that ceiling a full "
        f"{FAST_TOPICAL_DOCUMENTED_ROW_COUNT:,}-term Topical crawl through "
        "this channel is a multi-week job, not a single acquisition run."
    ),
    (
        "Research performed on 2026-08-04 found no sunset or deprecation "
        "announcement, and no explicit continuity commitment, for FAST from "
        "OCLC across 2025-2026. FAST's maintenance status is publisher "
        "silence, not a documented guarantee in either direction."
    ),
)


def parse_fast_topical_extract(
    acquired: AcquiredFASTTopicalExtract,
) -> ParsedFASTTopicalExtract:
    """Stream-parse an acquired CSV extract and re-verify it before returning."""

    digest, length = _digest_and_length(acquired.path)
    if length != acquired.pin.expected_byte_length or digest != acquired.pin.expected_sha256:
        raise FASTTopicalSourceDriftError("FAST topical extract drifted between acquisition and parsing")

    rows: list[FASTTopicalRow] = []
    seen_ids: set[str] = set()
    for row in iter_fast_topical_rows(acquired.path):
        if row.fast_id in seen_ids:
            raise FASTTopicalSourceDriftError(f"FAST topical extract contains duplicate fast_id {row.fast_id!r}")
        seen_ids.add(row.fast_id)
        rows.append(row)

    if len(rows) != acquired.pin.expected_row_count:
        raise FASTTopicalSourceDriftError(
            f"FAST topical extract row count drift: expected {acquired.pin.expected_row_count}, parsed {len(rows)}"
        )

    return ParsedFASTTopicalExtract(
        pin=acquired.pin,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=digest,
        source_byte_length=length,
        rows=tuple(rows),
        documented_total_row_count=FAST_TOPICAL_DOCUMENTED_ROW_COUNT,
        gaps=FAST_TOPICAL_GAPS,
    )


def _source_artifact_iri(source_sha256: str) -> str:
    return f"urn:ref:fast-topical-source-artifact:{_digest_hex(source_sha256, label='source_sha256')}"


def _observation_id(source_sha256: str, fast_id: str) -> str:
    digest_hex = _digest_hex(source_sha256, label="source_sha256")
    return f"urn:ref:source-record:fast-topical:{digest_hex}:{fast_id}"


def _identifier(
    value: str,
    kind: str,
    *,
    source_path: str,
    observed_at: str,
    source_digest: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "kind": kind,
        "authorityUri": FAST_IDENTIFIER_AUTHORITY_URI,
        "sourceUri": FAST_LANDING_PAGE_URL,
        "sourcePath": source_path,
        "observedAt": observed_at,
        "sourceDigest": source_digest,
    }


def _observation(
    row: FASTTopicalRow,
    *,
    source_sha256: str,
    observed_at: str,
) -> dict[str, Any]:
    return {
        "id": _observation_id(source_sha256, row.fast_id),
        "sourceArtifact": _source_artifact_iri(source_sha256),
        "sourcePath": f"row[{row.source_ordinal}]",
        "sourceOrdinal": row.source_ordinal,
        "labels": [{"value": row.heading, "language": "en", "role": "preferred"}],
        "identifiers": [
            _identifier(
                row.fast_id,
                "fastId",
                source_path=f"row[{row.source_ordinal}].fast_id",
                observed_at=observed_at,
                source_digest=source_sha256,
            ),
            _identifier(
                row.uri,
                "fastUri",
                source_path=f"row[{row.source_ordinal}].uri",
                observed_at=observed_at,
                source_digest=source_sha256,
            ),
        ],
        # Search expansion and mapping only: FAST never occupies a reserved
        # classifier output slot.
        "eligibleUses": ["searchExpansion"],
        "conceptIdentityClaimed": False,
    }


def _package_gaps(row_count: int) -> tuple[dict[str, Any], ...]:
    return (
        {
            "code": "fastNoOfficialCsvFormat",
            "affectedObservationCount": row_count,
            "effect": (
                "OCLC's official FAST download page publishes the Topical facet "
                "as MARC, MARCXML, and RDF N-Triples bulk files only; no official "
                "CSV byte source exists to pin."
            ),
        },
        {
            "code": "fastBulkHostBlockedAutomatedFetch",
            "affectedObservationCount": row_count,
            "effect": (
                "researchworks.oclc.org returned a Cloudflare bot-block response "
                "to an automated request on 2026-08-03; acquisition accepts only "
                "a locally supplied CSV rendering."
            ),
        },
        {
            "code": "fastDevelopmentSampleNotFullExtract",
            "affectedObservationCount": row_count,
            "effect": (
                "The project's documented full topical extract has "
                f"{FAST_TOPICAL_DOCUMENTED_ROW_COUNT:,} rows; this package's row "
                "count reflects only what was captured for its pin."
            ),
        },
    )


def build_fast_topical_source_package(
    parsed: ParsedFASTTopicalExtract,
    *,
    captured_at: str,
    source_bytes: bytes,
) -> SourceControlledResourceBundle:
    """Package every parsed row as mapping-only source evidence.

    Every observation is restricted to ``searchExpansion``: it is never
    eligible as ``sourceAssignedEvidence`` and can never fill a classifier
    output slot. The shared development-only usage ceiling forbids promoting
    this package into a concept scheme or accepted output.
    """

    if len(source_bytes) != parsed.source_byte_length or sha256_digest(source_bytes) != parsed.source_sha256:
        raise FASTTopicalSourceDriftError("supplied source_bytes do not match the parsed extract's pinned digest")

    observations = tuple(
        _observation(row, source_sha256=parsed.source_sha256, observed_at=parsed.retrieved_at) for row in parsed.rows
    )
    return build_source_controlled_resource_bundle(
        resource_id=FAST_TOPICAL_RESOURCE_ID,
        title="OCLC FAST Topical facet source observations",
        resource_kind="sourceTermSnapshot",
        identity_status="publisherIdentifiersPreserved",
        uses=("searchExpansion",),
        captured_at=captured_at,
        candidate_use_authorized=True,
        observations=observations,
        source_artifacts={_source_artifact_iri(parsed.source_sha256): source_bytes},
        source_observed_count=len(parsed.rows),
        gaps=_package_gaps(len(parsed.rows)),
    )


__all__ = [
    "FAST_ATTRIBUTION_NOTICE",
    "FAST_IDENTIFIER_AUTHORITY_URI",
    "FAST_LANDING_PAGE_URL",
    "FAST_LICENSE_URL",
    "FAST_PUBLISHER",
    "FAST_TOPICAL_DOCUMENTED_ROW_COUNT",
    "FAST_TOPICAL_GAPS",
    "FAST_TOPICAL_OFFICIAL_BULK_FORMATS",
    "FAST_TOPICAL_RESOURCE_ID",
    "FAST_URI_BASE",
    "AcquiredFASTTopicalExtract",
    "FASTTopicalAcquisitionError",
    "FASTTopicalError",
    "FASTTopicalExtractPin",
    "FASTTopicalRow",
    "FASTTopicalSourceDriftError",
    "ParsedFASTTopicalExtract",
    "acquire_fast_topical_extract",
    "build_fast_topical_source_package",
    "iter_fast_topical_rows",
    "parse_fast_topical_extract",
    "sha256_digest",
]
