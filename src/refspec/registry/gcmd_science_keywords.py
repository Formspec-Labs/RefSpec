"""Pinned NASA GCMD Science Keywords CSV capture and source-evidence packaging.

The NASA Global Change Master Directory (GCMD) Keyword Management System
(KMS) publishes the Earth Science Keywords concept scheme
(``27478148-b4b6-4c89-8829-08d2ee7bfe10``) as a versioned CSV export, with a
parallel RDF export for the same release. Every row carries a publisher-
issued concept UUID, so RefSpec preserves that UUID as identity and mints no
new concept identifier for it.

The Science Keywords scheme itself contains only two top-level branches,
``EARTH SCIENCE`` and ``EARTH SCIENCE SERVICES``. GCMD publishes Instruments,
Platforms, Projects, and Providers as separate KMS concept schemes; this
module treats any other category value as source drift and refuses it, so a
merged or mis-fetched export cannot smuggle instrument or platform terms
into this resource.

Per catalog guidance, this source is source evidence and crosswalks for NASA
records, captured as deterministic, versioned metadata. No RefSpec
evaluation has shown document-subject value for it, so this module packages
rows as source-controlled evidence only: it does not derive SKOS
broader/narrower relationships from the CSV hierarchy, does not assert
concept identity, and does not authorize candidate subject use.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

GCMD_PUBLISHER = "NASA Global Change Master Directory (GCMD) Keyword Management System (KMS)"
GCMD_IDENTIFIER_AUTHORITY_URI = "https://gcmd.earthdata.nasa.gov/kms/"
GCMD_SCIENCE_KEYWORDS_SCHEME_UUID = "27478148-b4b6-4c89-8829-08d2ee7bfe10"
GCMD_SCIENCE_KEYWORDS_VIEWER_URL = (
    "https://gcmd.earthdata.nasa.gov/KeywordViewer/scheme/sciencekeywords/27478148-b4b6-4c89-8829-08d2ee7bfe10/"
)
GCMD_SCIENCE_KEYWORDS_CSV_URL = "https://gcmd.earthdata.nasa.gov/kms/concepts/concept_scheme/sciencekeywords?format=csv"

# The KMS host (gcmd.earthdata.nasa.gov) redirects this export to its
# CMR-hosted API (cmr.earthdata.nasa.gov). Both are official NASA Earthdata
# infrastructure for the same release; a fetcher resolving anywhere else is
# source drift, not a mirror.
_ALLOWED_RESOLVED_HOSTS = frozenset({"gcmd.earthdata.nasa.gov", "cmr.earthdata.nasa.gov"})

# Exact CSV bytes observed 2026-08-03 for the published 24.4 release,
# confirmed against the KMS concept_versions endpoint (version 24.4,
# published 2026-07-22). This documents the full official export; the
# packaged test fixture is a small, byte-faithful excerpt of that same
# capture, not this full file, matching the repo's other "-mini" fixtures.
GCMD_SCIENCE_KEYWORDS_24_4_SHA256 = "sha256:f31d8137e860e4231ff312c89e4ffe59d12f636786a47dd2c41e28273a3f02e2"
GCMD_SCIENCE_KEYWORDS_24_4_BYTE_LENGTH = 504_190
GCMD_SCIENCE_KEYWORDS_24_4_ROW_COUNT = 3_774
GCMD_SCIENCE_KEYWORDS_24_4_RETRIEVED_AT = "2026-08-03T19:03:43Z"
GCMD_SCIENCE_KEYWORDS_24_4_REVISION = "2026-07-22T11:07:16.739Z"

_EXPECTED_CSV_COLUMNS = (
    "Category",
    "Topic",
    "Term",
    "Variable_Level_1",
    "Variable_Level_2",
    "Variable_Level_3",
    "Detailed_Variable",
    "UUID",
)
# Only the two branches the Science Keywords scheme itself publishes.
ALLOWED_CATEGORIES = frozenset({"EARTH SCIENCE", "EARTH SCIENCE SERVICES"})

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")

GCMD_SCIENCE_KEYWORDS_PACKAGE_VERSION = "gcmd-science-keywords-package-v1"
GCMD_SCIENCE_KEYWORDS_RESOURCE_ID = "gcmd-science-keywords-24-4"
GCMD_SCIENCE_KEYWORDS_TITLE = "NASA GCMD Science Keywords 24.4 source observations"

# Known, permanent limitations of this capture. They are packaged into every
# resource so a reader never has to rediscover them from the raw CSV.
GCMD_SCIENCE_KEYWORDS_GAPS: tuple[dict[str, str], ...] = (
    {
        "kind": "skosRelationshipsUnavailable",
        "reason": (
            "The CSV export carries no SKOS broader/narrower, definition, or "
            "altLabel data; only the separate RDF export publishes those "
            "relationships, and this module does not fetch or model them."
        ),
    },
    {
        "kind": "instrumentAndPlatformBranchesExcluded",
        "reason": (
            "GCMD publishes Instruments, Platforms, Projects, and Providers as "
            "separate KMS concept schemes; only EARTH SCIENCE and EARTH "
            "SCIENCE SERVICES rows from the Science Keywords scheme are "
            "accepted here."
        ),
    },
    {
        "kind": "documentSubjectValueUnevaluated",
        "reason": (
            "No RefSpec evaluation has shown document-subject value for this "
            "vocabulary; rows remain source evidence and crosswalk candidates "
            "only, per catalog guidance."
        ),
    },
)


class GCMDResourceError(ValueError):
    """Base class for GCMD Science Keywords failures."""


class GCMDAcquisitionError(GCMDResourceError):
    """Exact official source bytes could not be acquired safely."""


class GCMDSourceDriftError(GCMDResourceError):
    """A GCMD source no longer matches the reviewed structure, version, or pin."""


@dataclass(frozen=True, slots=True)
class GCMDScienceKeywordsSource:
    """The official KMS CSV export endpoint for one concept scheme."""

    source_url: str
    filename: str
    scheme_uuid: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "gcmd.earthdata.nasa.gov":
            raise GCMDAcquisitionError("source_url must be an official HTTPS gcmd.earthdata.nasa.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise GCMDAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise GCMDAcquisitionError("filename must be one plain path component")
        if _UUID.fullmatch(self.scheme_uuid) is None:
            raise GCMDAcquisitionError("scheme_uuid must be a KMS concept-scheme UUID")


GCMD_SCIENCE_KEYWORDS_SOURCE = GCMDScienceKeywordsSource(
    source_url=GCMD_SCIENCE_KEYWORDS_CSV_URL,
    filename="gcmd-science-keywords.csv",
    scheme_uuid=GCMD_SCIENCE_KEYWORDS_SCHEME_UUID,
)


@dataclass(frozen=True, slots=True)
class GCMDSnapshotPin:
    """Exact identity of one official Science Keywords CSV export."""

    source: GCMDScienceKeywordsSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    expected_keyword_version: str
    expected_revision: str
    expected_row_count: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise GCMDAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise GCMDAcquisitionError("expected_byte_length must be positive")
        if self.expected_row_count <= 0:
            raise GCMDAcquisitionError("expected_row_count must be positive")
        if not self.retrieved_at or not self.expected_keyword_version or not self.expected_revision:
            raise GCMDAcquisitionError(
                "retrieved_at, expected_keyword_version, and expected_revision must not be empty"
            )


GCMD_SCIENCE_KEYWORDS_24_4 = GCMDSnapshotPin(
    source=GCMD_SCIENCE_KEYWORDS_SOURCE,
    retrieved_at=GCMD_SCIENCE_KEYWORDS_24_4_RETRIEVED_AT,
    expected_sha256=GCMD_SCIENCE_KEYWORDS_24_4_SHA256,
    expected_byte_length=GCMD_SCIENCE_KEYWORDS_24_4_BYTE_LENGTH,
    expected_keyword_version="24.4",
    expected_revision=GCMD_SCIENCE_KEYWORDS_24_4_REVISION,
    expected_row_count=GCMD_SCIENCE_KEYWORDS_24_4_ROW_COUNT,
)


@dataclass(frozen=True, slots=True)
class FetchedGCMDResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class GCMDFetcher(Protocol):
    """Small transport boundary for the official KMS CSV export."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedGCMDResponse:
        """Fetch one response while preserving its exact body bytes."""


AcquisitionMode = Literal["cache", "local", "fetcher"]


@dataclass(frozen=True, slots=True)
class AcquiredGCMDSource:
    """One verified source object in the content-addressed store."""

    pin: GCMDSnapshotPin
    path: Path
    sha256: str
    byte_length: int
    source_url: str
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_RESOLVED_HOSTS:
        raise GCMDAcquisitionError(
            "fetcher resolved_url must remain on official HTTPS gcmd.earthdata.nasa.gov or cmr.earthdata.nasa.gov"
        )
    if parsed.username is not None or parsed.password is not None:
        raise GCMDAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: GCMDSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise GCMDSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise GCMDSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: GCMDSnapshotPin) -> AcquiredGCMDSource:
    if path.is_symlink() or not path.is_file():
        raise GCMDAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached GCMD source",
    )
    return AcquiredGCMDSource(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type="text/csv",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: GCMDSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredGCMDSource:
    actual_sha256, byte_length = _verify_payload(payload, pin, location=f"{acquisition_mode} GCMD source")
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
        return AcquiredGCMDSource(
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


def acquire_gcmd_science_keywords(
    pin: GCMDSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: GCMDFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredGCMDSource:
    """Acquire one exact Science Keywords CSV export through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise GCMDAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise GCMDAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise GCMDAcquisitionError(f"local GCMD source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="text/csv",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise GCMDAcquisitionError("GCMD Science Keywords are not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise GCMDAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "text/csv":
        raise GCMDSourceDriftError(f"GCMD Science Keywords content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


@dataclass(frozen=True, slots=True)
class GCMDKeywordRow:
    """One exact Science Keywords row with its publisher-issued identity.

    ``is_general_subject_concept`` is always False: this module never
    promotes a row into a general subject concept on its own authority.
    """

    category: str
    topic: str | None
    term: str | None
    variable_level_1: str | None
    variable_level_2: str | None
    variable_level_3: str | None
    detailed_variable: str | None
    preferred_label: str
    identifiers: tuple[ControlledIdentifier, ...]
    source_path: str
    source_ordinal: int
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedGCMDScienceKeywords:
    """A parsed, digest- and version-pinned GCMD Science Keywords export."""

    source: GCMDScienceKeywordsSource
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    keyword_version: str
    revision: str
    rows: tuple[GCMDKeywordRow, ...]
    gaps: tuple[dict[str, str], ...]

    def by_uuid(self) -> dict[str, GCMDKeywordRow]:
        """Index rows by their publisher-issued concept UUID."""

        result: dict[str, GCMDKeywordRow] = {}
        for row in self.rows:
            matches = [identifier for identifier in row.identifiers if identifier.kind == "gcmdConceptUUID"]
            if len(matches) != 1:
                raise GCMDSourceDriftError("Science Keywords row must retain exactly one gcmdConceptUUID")
            result[matches[0].value] = row
        return result


def parse_gcmd_science_keywords_csv(acquired: AcquiredGCMDSource) -> ParsedGCMDScienceKeywords:
    """Parse the exact CSV export without deriving SKOS relationships."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed GCMD source")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GCMDSourceDriftError("GCMD Science Keywords payload is not valid UTF-8") from error

    reader = csv.reader(io.StringIO(text))
    try:
        metadata_row = next(reader)
    except StopIteration as error:
        raise GCMDSourceDriftError("GCMD Science Keywords payload has no metadata header row") from error
    try:
        header_row = next(reader)
    except StopIteration as error:
        raise GCMDSourceDriftError("GCMD Science Keywords payload has no column header row") from error

    if (
        len(metadata_row) < 2
        or not metadata_row[0].startswith("Keyword Version:")
        or not metadata_row[1].startswith("Revision:")
    ):
        raise GCMDSourceDriftError("GCMD Science Keywords metadata header drifted from Keyword Version/Revision shape")
    keyword_version = metadata_row[0].removeprefix("Keyword Version:").strip()
    revision = metadata_row[1].removeprefix("Revision:").strip()
    if keyword_version != acquired.pin.expected_keyword_version:
        raise GCMDSourceDriftError(
            f"Science Keywords version drift: expected {acquired.pin.expected_keyword_version!r}, "
            f"got {keyword_version!r}"
        )
    if revision != acquired.pin.expected_revision:
        raise GCMDSourceDriftError(
            f"Science Keywords revision drift: expected {acquired.pin.expected_revision!r}, got {revision!r}"
        )

    if tuple(header_row) != _EXPECTED_CSV_COLUMNS:
        raise GCMDSourceDriftError(f"Science Keywords column header drifted: {header_row}")

    rows: list[GCMDKeywordRow] = []
    seen_uuids: set[str] = set()
    for ordinal, record in enumerate(reader):
        if not record:
            continue
        if len(record) != 8:
            raise GCMDSourceDriftError(f"Science Keywords row {ordinal} has {len(record)} fields, expected 8")
        category, topic, term, level_1, level_2, level_3, detailed, uuid = record
        if category not in ALLOWED_CATEGORIES:
            raise GCMDSourceDriftError(
                f"Science Keywords row {ordinal} has an out-of-scope category {category!r}; "
                "only EARTH SCIENCE and EARTH SCIENCE SERVICES are accepted"
            )
        if _UUID.fullmatch(uuid) is None:
            raise GCMDSourceDriftError(f"Science Keywords row {ordinal} has a malformed UUID {uuid!r}")
        if uuid in seen_uuids:
            raise GCMDSourceDriftError(f"Science Keywords row {ordinal} repeats UUID {uuid!r}")
        seen_uuids.add(uuid)

        levels = (category, topic, term, level_1, level_2, level_3, detailed)
        seen_blank = False
        for level in levels:
            if level == "":
                seen_blank = True
            elif seen_blank:
                raise GCMDSourceDriftError(
                    f"Science Keywords row {ordinal} has a populated level after a blank ancestor level"
                )
        preferred_label = next(level for level in reversed(levels) if level)

        source_path = f"csv:row[{ordinal}]"
        identifiers = (
            ControlledIdentifier(
                value=uuid,
                kind="gcmdConceptUUID",
                authority_uri=GCMD_IDENTIFIER_AUTHORITY_URI,
                source_uri=acquired.pin.source.source_url,
                observed_at=acquired.pin.retrieved_at,
                effective_at=None,
                source_digest=acquired.sha256,
            ),
        )
        rows.append(
            GCMDKeywordRow(
                category=category,
                topic=topic or None,
                term=term or None,
                variable_level_1=level_1 or None,
                variable_level_2=level_2 or None,
                variable_level_3=level_3 or None,
                detailed_variable=detailed or None,
                preferred_label=preferred_label,
                identifiers=identifiers,
                source_path=source_path,
                source_ordinal=ordinal,
            )
        )

    if len(rows) != acquired.pin.expected_row_count:
        raise GCMDSourceDriftError(
            f"Science Keywords row count drift: expected {acquired.pin.expected_row_count}, parsed {len(rows)}"
        )

    return ParsedGCMDScienceKeywords(
        source=acquired.pin.source,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        keyword_version=keyword_version,
        revision=revision,
        rows=tuple(rows),
        gaps=GCMD_SCIENCE_KEYWORDS_GAPS,
    )


def _row_observation(
    row: GCMDKeywordRow,
    pin: GCMDSnapshotPin,
) -> dict[str, Any]:
    identifier = row.identifiers[0]
    identifier_payload = {
        "value": identifier.value,
        "kind": identifier.kind,
        "authorityUri": identifier.authority_uri,
        "sourceUri": identifier.source_uri,
        "sourcePath": f"{row.source_path}.UUID",
        "observedAt": identifier.observed_at,
        "sourceDigest": identifier.source_digest,
    }
    observation_identity = {
        "packageVersion": GCMD_SCIENCE_KEYWORDS_PACKAGE_VERSION,
        "resourceId": GCMD_SCIENCE_KEYWORDS_RESOURCE_ID,
        "sourceArtifact": pin.source.source_url,
        "sourcePath": row.source_path,
        "uuid": identifier.value,
    }
    digest = hashlib.sha256(canonical_json(observation_identity).encode("utf-8")).hexdigest()
    return {
        "id": f"urn:ref:source-observation:{GCMD_SCIENCE_KEYWORDS_RESOURCE_ID}:{digest}",
        "sourceArtifact": pin.source.source_url,
        "sourcePath": row.source_path,
        # This ordinal is a source locator only. Publisher identity is
        # preserved in identifiers and never derived from row order.
        "sourceOrdinal": row.source_ordinal,
        "labels": [
            {
                "value": row.preferred_label,
                "language": "en",
                "role": "preferred",
            }
        ],
        "identifiers": [identifier_payload],
        "eligibleUses": ["sourceAssignedEvidence"],
        "conceptIdentityClaimed": False,
        # Descriptive hierarchy context only. This is not a SKOS broader
        # relationship and must not be read as one.
        "category": row.category,
        "topic": row.topic,
        "term": row.term,
        "variableLevel1": row.variable_level_1,
        "variableLevel2": row.variable_level_2,
        "variableLevel3": row.variable_level_3,
        "detailedVariable": row.detailed_variable,
    }


def build_gcmd_science_keywords_package(
    pin: GCMDSnapshotPin,
    source_path: Path,
) -> SourceControlledResourceBundle:
    """Build one exact, development-only Science Keywords source package.

    ``candidate_use_authorized`` is always False: per catalog guidance, this
    vocabulary is mapping/deterministic metadata only until a RefSpec
    evaluation proves document-subject value.
    """

    path = Path(source_path)
    if path.is_symlink() or not path.is_file():
        raise GCMDResourceError(f"GCMD Science Keywords source is not a regular file: {path}")
    payload = path.read_bytes()
    with tempfile.TemporaryDirectory(prefix="refspec-gcmd-package-") as temporary:
        root = Path(temporary)
        staged = root / pin.source.filename
        staged.write_bytes(payload)
        acquired = acquire_gcmd_science_keywords(pin, root / "store", source_path=staged)
        resource = parse_gcmd_science_keywords_csv(acquired)

    observations = tuple(_row_observation(row, pin) for row in resource.rows)
    return build_source_controlled_resource_bundle(
        resource_id=GCMD_SCIENCE_KEYWORDS_RESOURCE_ID,
        title=GCMD_SCIENCE_KEYWORDS_TITLE,
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("sourceAssignedEvidence",),
        captured_at=pin.retrieved_at,
        candidate_use_authorized=False,
        observations=observations,
        source_artifacts={pin.source.source_url: payload},
        source_observed_count=pin.expected_row_count,
        gaps=GCMD_SCIENCE_KEYWORDS_GAPS,
    )


__all__ = [
    "ALLOWED_CATEGORIES",
    "GCMD_IDENTIFIER_AUTHORITY_URI",
    "GCMD_PUBLISHER",
    "GCMD_SCIENCE_KEYWORDS_24_4",
    "GCMD_SCIENCE_KEYWORDS_24_4_BYTE_LENGTH",
    "GCMD_SCIENCE_KEYWORDS_24_4_RETRIEVED_AT",
    "GCMD_SCIENCE_KEYWORDS_24_4_REVISION",
    "GCMD_SCIENCE_KEYWORDS_24_4_ROW_COUNT",
    "GCMD_SCIENCE_KEYWORDS_24_4_SHA256",
    "GCMD_SCIENCE_KEYWORDS_CSV_URL",
    "GCMD_SCIENCE_KEYWORDS_GAPS",
    "GCMD_SCIENCE_KEYWORDS_PACKAGE_VERSION",
    "GCMD_SCIENCE_KEYWORDS_RESOURCE_ID",
    "GCMD_SCIENCE_KEYWORDS_SCHEME_UUID",
    "GCMD_SCIENCE_KEYWORDS_SOURCE",
    "GCMD_SCIENCE_KEYWORDS_TITLE",
    "GCMD_SCIENCE_KEYWORDS_VIEWER_URL",
    "AcquiredGCMDSource",
    "AcquisitionMode",
    "FetchedGCMDResponse",
    "GCMDAcquisitionError",
    "GCMDFetcher",
    "GCMDKeywordRow",
    "GCMDResourceError",
    "GCMDScienceKeywordsSource",
    "GCMDSnapshotPin",
    "GCMDSourceDriftError",
    "ParsedGCMDScienceKeywords",
    "acquire_gcmd_science_keywords",
    "build_gcmd_science_keywords_package",
    "parse_gcmd_science_keywords_csv",
    "sha256_digest",
]
