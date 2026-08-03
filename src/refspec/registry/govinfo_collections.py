"""Pinned GovInfo collection codes and eCFR structural values.

The GovInfo API publishes a fixed short code (``collectionCode``) and display
name for every document collection it hosts (``CFR``, ``FR``, ``USCODE``, and
so on). The eCFR Titles API publishes the current CFR title roster with
version-currency fields (``latest_amended_on``, ``latest_issue_date``,
``up_to_date_as_of``) and a ``reserved`` flag. A GovInfo package summary
publishes package identity, docket-class, and version metadata for one
document package, and that package's PREMIS record publishes per-file
SHA-256 fixity digests. None of these is a general-subject vocabulary: this
module packages collection codes, CFR title/version fields, package identity
and version fields, and package fixity digests as source-native controlled
codes and deterministic metadata. Title, chapter, part, and section NAMES
(``collectionName``/title ``name``) are retained as plain non-subject labels
and never promoted to subject candidates.

eCFR does not publish a standalone constants endpoint for the CFR structural
hierarchy's node "type" values (title, chapter, subchapter, part, subpart,
subject group, section, appendix, and heading nodes). Those level codes were
observed directly from live eCFR structure endpoint captures for CFR titles
1, 5, 12, and 26 made while authoring this module (2026-08-03) and are
recorded as a fixed, non-authoritative tuple, not a governed vocabulary.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit
from xml.etree import ElementTree

from refspec.registry.controlled_identifier import ControlledIdentifier, validate_identifier_date
from refspec.registry.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

GOVINFO_PUBLISHER = "U.S. Government Publishing Office (GovInfo)"
ECFR_PUBLISHER = "Office of the Federal Register, National Archives and Records Administration"
GOVINFO_API_BASE = "https://api.govinfo.gov"
ECFR_API_BASE = "https://www.ecfr.gov/api/versioner/v1"
GOVINFO_IDENTIFIER_AUTHORITY_URI = "https://www.govinfo.gov/developers"
ECFR_IDENTIFIER_AUTHORITY_URI = "https://www.ecfr.gov/developers/documentation/api/v1"
GOVINFO_CFR_PACKAGE_ID = "CFR-2023-title1-vol1"

# The PREMIS 2.0 namespace GovInfo uses for its per-package fixity record.
_PREMIS_NS = "info:lc/xmlns/premis-v2"
_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

ResourceName = Literal[
    "govInfoCollections",
    "ecfrCfrTitles",
    "govInfoCfrPackageSummary",
    "govInfoCfrPackagePremisFixity",
]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_GOVINFO_COLLECTION_CODE = re.compile(r"^[A-Z0-9]+$")
_GOVINFO_PACKAGE_ID = re.compile(r"^CFR-\d{4}-title\d{1,3}-vol\d{1,3}$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_HOSTS = frozenset({"api.govinfo.gov", "www.ecfr.gov"})
_ALLOWED_CONTENT_TYPES = {
    "json": frozenset({"application/json"}),
    "xml": frozenset({"application/xml", "text/xml"}),
}


class GovInfoResourceError(ValueError):
    """Base class for GovInfo/eCFR controlled-code failures."""


class GovInfoAcquisitionError(GovInfoResourceError):
    """Exact official source bytes could not be acquired safely."""


class GovInfoSourceDriftError(GovInfoResourceError):
    """A source no longer matches the reviewed structure or pin."""


class GovInfoAssignmentError(GovInfoResourceError):
    """A record references an unknown or inconsistent controlled code."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class GovInfoSourceSpec:
    """One official GovInfo or eCFR endpoint captured verbatim."""

    resource_name: ResourceName
    source_url: str
    filename: str
    content_kind: Literal["json", "xml"]

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
            raise GovInfoAcquisitionError(
                "source_url must be an official HTTPS api.govinfo.gov or www.ecfr.gov URL"
            )
        if parsed.username is not None or parsed.password is not None:
            raise GovInfoAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise GovInfoAcquisitionError("filename must be one plain path component")

    @property
    def host(self) -> str:
        return cast(str, urlsplit(self.source_url).hostname)


GOVINFO_COLLECTIONS = GovInfoSourceSpec(
    resource_name="govInfoCollections",
    source_url=f"{GOVINFO_API_BASE}/collections",
    filename="govinfo-collections.json",
    content_kind="json",
)
ECFR_CFR_TITLES = GovInfoSourceSpec(
    resource_name="ecfrCfrTitles",
    source_url=f"{ECFR_API_BASE}/titles.json",
    filename="ecfr-cfr-titles.json",
    content_kind="json",
)
GOVINFO_CFR_PACKAGE_SUMMARY = GovInfoSourceSpec(
    resource_name="govInfoCfrPackageSummary",
    source_url=f"{GOVINFO_API_BASE}/packages/{GOVINFO_CFR_PACKAGE_ID}/summary",
    filename="govinfo-cfr-package-summary.json",
    content_kind="json",
)
GOVINFO_CFR_PACKAGE_PREMIS = GovInfoSourceSpec(
    resource_name="govInfoCfrPackagePremisFixity",
    source_url=f"{GOVINFO_API_BASE}/packages/{GOVINFO_CFR_PACKAGE_ID}/premis",
    filename="govinfo-cfr-package-premis.xml",
    content_kind="xml",
)

# The GovInfo Collections service and eCFR Titles service both report a
# closed, countable array. These counts are asserted at parse time so a
# publisher addition or removal is reported as drift rather than silently
# absorbed.
EXPECTED_COLLECTIONS_COUNT = 42
EXPECTED_CFR_TITLES_COUNT = 50


@dataclass(frozen=True, slots=True)
class GovInfoSnapshotPin:
    """Exact identity of one official GovInfo or eCFR response."""

    source: GovInfoSourceSpec
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise GovInfoAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise GovInfoAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise GovInfoAcquisitionError("retrieved_at must not be empty")


GOVINFO_COLLECTIONS_2026_08_03 = GovInfoSnapshotPin(
    source=GOVINFO_COLLECTIONS,
    retrieved_at="2026-08-03T19:15:00Z",
    expected_sha256="sha256:82cd4191d6abf88c0c1443284e8466a380a7841889cfe79cf19e92864b0dc347",
    expected_byte_length=4_803,
)
ECFR_CFR_TITLES_2026_08_03 = GovInfoSnapshotPin(
    source=ECFR_CFR_TITLES,
    retrieved_at="2026-08-03T19:15:00Z",
    expected_sha256="sha256:a5985527fc0b07ac95d2cb5d7c867cfd0ddbc2712708e271edbe4ad742001781",
    expected_byte_length=8_033,
)
GOVINFO_CFR_PACKAGE_SUMMARY_2026_08_03 = GovInfoSnapshotPin(
    source=GOVINFO_CFR_PACKAGE_SUMMARY,
    retrieved_at="2026-08-03T19:15:00Z",
    expected_sha256="sha256:705a28865a4fba746e8deb4aff05a21bbd63534201e74c5320f56d505ca3d79e",
    expected_byte_length=1_532,
)
GOVINFO_CFR_PACKAGE_PREMIS_2026_08_03 = GovInfoSnapshotPin(
    source=GOVINFO_CFR_PACKAGE_PREMIS,
    retrieved_at="2026-08-03T19:15:00Z",
    expected_sha256="sha256:afeba6d9e48f502c911ef0ec1400accdbaa5cad5d7d056672dce6a54d1326417",
    expected_byte_length=4_268,
)

# eCFR's structure endpoint labels every hierarchy node with a "type" value.
# There is no discrete constants endpoint for this enum, so this tuple is
# evidence observed directly from live captures made while authoring this
# module, not a publisher-issued release. See EXPECTED_CFR_TITLES_COUNT above
# for the one resource eCFR does publish as a closed, countable array.
ECFR_CFR_HIERARCHY_LEVEL_TYPES: tuple[str, ...] = (
    "appendix",
    "chapter",
    "hed1",
    "part",
    "section",
    "subchapter",
    "subject_group",
    "subpart",
    "title",
)

GOVINFO_PORTFOLIO_GAPS: tuple[str, ...] = (
    (
        "eCFR does not publish a standalone constants endpoint for CFR structural "
        "hierarchy level types; ECFR_CFR_HIERARCHY_LEVEL_TYPES was observed from "
        "live structure endpoint captures for titles 1, 5, 12, and 26 made while "
        "authoring this module on 2026-08-03 and is not a governed vocabulary."
    ),
    (
        "GovInfo package summary field shape varies by collection; this module "
        "only certifies the shape observed for Code of Federal Regulations (CFR) "
        "annual-edition packages, not every GovInfo collection's package schema."
    ),
    (
        "Per-file SHA-256 fixity is published in a package's PREMIS record for "
        "only a subset of that package's file objects; a file object without a "
        "fixity element is skipped rather than treated as drift."
    ),
)


@dataclass(frozen=True, slots=True)
class FetchedGovInfoResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class GovInfoFetcher(Protocol):
    """Small transport boundary for official GovInfo/eCFR endpoints."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedGovInfoResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredGovInfoSource:
    """One verified source object in the content-addressed store."""

    pin: GovInfoSnapshotPin
    path: Path
    sha256: str
    byte_length: int
    source_url: str
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def _validate_resolved_url(value: str, *, expected_host: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != expected_host:
        raise GovInfoAcquisitionError(f"fetcher resolved_url must remain on the official HTTPS {expected_host} host")
    if parsed.username is not None or parsed.password is not None:
        raise GovInfoAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: GovInfoSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise GovInfoSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise GovInfoSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    if pin.source.content_kind == "json":
        try:
            json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GovInfoSourceDriftError(f"{location} is not valid JSON") from error
    else:
        try:
            ElementTree.fromstring(payload)
        except ElementTree.ParseError as error:
            raise GovInfoSourceDriftError(f"{location} is not valid XML") from error
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: GovInfoSnapshotPin) -> AcquiredGovInfoSource:
    if path.is_symlink() or not path.is_file():
        raise GovInfoAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached source",
    )
    return AcquiredGovInfoSource(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type=("application/json" if pin.source.content_kind == "json" else "application/xml"),
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: GovInfoSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredGovInfoSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} source",
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
        return AcquiredGovInfoSource(
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


def acquire_govinfo_source(
    pin: GovInfoSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: GovInfoFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredGovInfoSource:
    """Acquire one exact GovInfo/eCFR response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise GovInfoAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise GovInfoAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise GovInfoAcquisitionError(f"local source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type=("application/json" if pin.source.content_kind == "json" else "application/xml"),
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise GovInfoAcquisitionError("source is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise GovInfoAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url, expected_host=pin.source.host)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in _ALLOWED_CONTENT_TYPES[pin.source.content_kind]:
        raise GovInfoSourceDriftError(f"source content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise GovInfoSourceDriftError(f"{label} must be non-empty, untrimmed text")
    return value


def _require_https_url(value: object, label: str) -> str:
    text = _require_text(value, label)
    parsed = urlsplit(text)
    if parsed.scheme != "https" or not parsed.hostname:
        raise GovInfoSourceDriftError(f"{label} must be an absolute HTTPS URL")
    return text


def _make_identifier(
    *,
    value: str,
    kind: str,
    authority_uri: str,
    source_uri: str,
    observed_at: str,
    source_digest: str,
) -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=kind,
        authority_uri=authority_uri,
        source_uri=source_uri,
        observed_at=observed_at,
        effective_at=None,
        source_digest=source_digest,
    )


# ---------------------------------------------------------------------------
# GovInfo Collections: the controlled ``collectionCode``/``collectionName``
# list every GovInfo package and granule belongs to.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GovInfoCollectionCode:
    """One official GovInfo collection code and its non-subject display name."""

    collection_code: str
    collection_name: str
    package_count: int
    granule_count: int | None
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedGovInfoCollections:
    """A parsed, digest-pinned GovInfo Collections response."""

    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    collections: tuple[GovInfoCollectionCode, ...]

    def by_code(self) -> dict[str, GovInfoCollectionCode]:
        """Index every collection by its exact publisher-issued code."""

        result: dict[str, GovInfoCollectionCode] = {}
        for entry in self.collections:
            result[entry.collection_code] = entry
        return result


def parse_govinfo_collections(acquired: AcquiredGovInfoSource) -> ParsedGovInfoCollections:
    """Parse the exact ``collectionCode``/``collectionName`` list, never as subjects."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed GovInfo Collections source")
    root = json.loads(payload)
    if not isinstance(root, Mapping) or set(root) != {"collections"}:
        raise GovInfoSourceDriftError("GovInfo Collections payload fields drifted from {'collections'}")
    rows = root["collections"]
    if not isinstance(rows, list):
        raise GovInfoSourceDriftError("GovInfo Collections payload must contain a collections array")

    allowed_fields = {"collectionCode", "collectionName", "packageCount", "granuleCount"}
    parsed: list[GovInfoCollectionCode] = []
    for ordinal, record in enumerate(rows, start=1):
        if not isinstance(record, Mapping) or set(record) != allowed_fields:
            raise GovInfoSourceDriftError(f"GovInfo Collections record {ordinal} fields drifted: {sorted(record)}")
        code = record["collectionCode"]
        name = record["collectionName"]
        package_count = record["packageCount"]
        granule_count = record["granuleCount"]
        if not isinstance(code, str) or _GOVINFO_COLLECTION_CODE.fullmatch(code) is None:
            raise GovInfoSourceDriftError(f"GovInfo Collections record {ordinal} has a malformed collection code")
        _require_text(name, f"GovInfo Collections record {ordinal} collectionName")
        if not isinstance(package_count, int) or isinstance(package_count, bool) or package_count < 0:
            raise GovInfoSourceDriftError(f"GovInfo Collections record {ordinal} packageCount must be non-negative")
        if granule_count is not None and (not isinstance(granule_count, int) or isinstance(granule_count, bool) or granule_count < 0):
            raise GovInfoSourceDriftError(
                f"GovInfo Collections record {ordinal} granuleCount must be non-negative or null"
            )
        identifier = _make_identifier(
            value=code,
            kind="govInfoCollectionCode",
            authority_uri=GOVINFO_IDENTIFIER_AUTHORITY_URI,
            source_uri=acquired.pin.source.source_url,
            observed_at=acquired.pin.retrieved_at,
            source_digest=acquired.sha256,
        )
        parsed.append(
            GovInfoCollectionCode(
                collection_code=code,
                collection_name=name,
                package_count=package_count,
                granule_count=granule_count,
                identifiers=(identifier,),
            )
        )
    codes = {entry.collection_code for entry in parsed}
    if len(codes) != len(parsed):
        raise GovInfoSourceDriftError("GovInfo Collections payload contains duplicate collection codes")
    if len(parsed) != EXPECTED_COLLECTIONS_COUNT:
        raise GovInfoSourceDriftError(
            f"GovInfo Collections count drift: expected {EXPECTED_COLLECTIONS_COUNT}, parsed {len(parsed)}"
        )

    return ParsedGovInfoCollections(
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        collections=tuple(parsed),
    )


# ---------------------------------------------------------------------------
# eCFR CFR Titles: the CFR title roster with version-currency fields. Title
# NAMES are retained as plain labels and never become subjects.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ECFRCFRTitle:
    """One CFR title's identity, non-subject name, and version-currency fields."""

    title_number: int
    name: str
    latest_amended_on: str | None
    latest_issue_date: str | None
    up_to_date_as_of: str | None
    reserved: bool
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedECFRTitles:
    """A parsed, digest-pinned eCFR Titles response."""

    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    as_of_date: str
    import_in_progress: bool
    titles: tuple[ECFRCFRTitle, ...]

    def by_number(self) -> dict[int, ECFRCFRTitle]:
        """Index every title by its exact publisher-issued title number."""

        return {entry.title_number: entry for entry in self.titles}


def _optional_iso_date(value: object, label: str) -> str | None:
    if value is None:
        return None
    text = _require_text(value, label)
    if _ISO_DATE.fullmatch(text) is None:
        raise GovInfoSourceDriftError(f"{label} must be an ISO 8601 date or null")
    return text


def parse_ecfr_cfr_titles(acquired: AcquiredGovInfoSource) -> ParsedECFRTitles:
    """Parse the exact CFR title roster and version-currency fields, never as subjects."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed eCFR Titles source")
    root = json.loads(payload)
    if not isinstance(root, Mapping) or set(root) != {"titles", "meta"}:
        raise GovInfoSourceDriftError("eCFR Titles payload fields drifted from {'titles', 'meta'}")
    meta = root["meta"]
    if not isinstance(meta, Mapping) or set(meta) != {"date", "import_in_progress"}:
        raise GovInfoSourceDriftError("eCFR Titles meta fields drifted from {'date', 'import_in_progress'}")
    as_of_date = _optional_iso_date(meta["date"], "eCFR Titles meta.date")
    if as_of_date is None:
        raise GovInfoSourceDriftError("eCFR Titles meta.date must not be null")
    import_in_progress = meta["import_in_progress"]
    if not isinstance(import_in_progress, bool):
        raise GovInfoSourceDriftError("eCFR Titles meta.import_in_progress must be a boolean")

    rows = root["titles"]
    if not isinstance(rows, list):
        raise GovInfoSourceDriftError("eCFR Titles payload must contain a titles array")
    if len(rows) != EXPECTED_CFR_TITLES_COUNT:
        raise GovInfoSourceDriftError(
            f"eCFR Titles count drift: expected {EXPECTED_CFR_TITLES_COUNT}, parsed {len(rows)}"
        )

    allowed_fields = {
        "number",
        "name",
        "latest_amended_on",
        "latest_issue_date",
        "up_to_date_as_of",
        "reserved",
    }
    parsed: list[ECFRCFRTitle] = []
    for ordinal, record in enumerate(rows, start=1):
        if not isinstance(record, Mapping) or set(record) != allowed_fields:
            raise GovInfoSourceDriftError(f"eCFR Titles record {ordinal} fields drifted: {sorted(record)}")
        number = record["number"]
        reserved = record["reserved"]
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise GovInfoSourceDriftError(f"eCFR Titles record {ordinal} number must be a positive integer")
        if not isinstance(reserved, bool):
            raise GovInfoSourceDriftError(f"eCFR Titles record {ordinal} reserved must be a boolean")
        name = _require_text(record["name"], f"eCFR Titles record {ordinal} name")
        latest_amended_on = _optional_iso_date(
            record["latest_amended_on"],
            f"eCFR Titles record {ordinal} latest_amended_on",
        )
        latest_issue_date = _optional_iso_date(
            record["latest_issue_date"],
            f"eCFR Titles record {ordinal} latest_issue_date",
        )
        up_to_date_as_of = _optional_iso_date(
            record["up_to_date_as_of"],
            f"eCFR Titles record {ordinal} up_to_date_as_of",
        )
        if reserved:
            if latest_amended_on is not None or latest_issue_date is not None or up_to_date_as_of is not None:
                raise GovInfoSourceDriftError(f"eCFR Titles record {ordinal} is reserved but carries version dates")
        else:
            if latest_amended_on is None or latest_issue_date is None or up_to_date_as_of is None:
                raise GovInfoSourceDriftError(f"eCFR Titles record {ordinal} is active but is missing a version date")
            if up_to_date_as_of != as_of_date:
                raise GovInfoSourceDriftError(
                    f"eCFR Titles record {ordinal} up_to_date_as_of does not match the response's meta.date"
                )
        identifier = _make_identifier(
            value=str(number),
            kind="ecfrCfrTitleNumber",
            authority_uri=ECFR_IDENTIFIER_AUTHORITY_URI,
            source_uri=acquired.pin.source.source_url,
            observed_at=acquired.pin.retrieved_at,
            source_digest=acquired.sha256,
        )
        parsed.append(
            ECFRCFRTitle(
                title_number=number,
                name=name,
                latest_amended_on=latest_amended_on,
                latest_issue_date=latest_issue_date,
                up_to_date_as_of=up_to_date_as_of,
                reserved=reserved,
                identifiers=(identifier,),
            )
        )
    numbers = {entry.title_number for entry in parsed}
    if len(numbers) != len(parsed):
        raise GovInfoSourceDriftError("eCFR Titles payload contains duplicate title numbers")

    return ParsedECFRTitles(
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        as_of_date=as_of_date,
        import_in_progress=import_in_progress,
        titles=tuple(parsed),
    )


# ---------------------------------------------------------------------------
# GovInfo CFR package summary: package identity, classification, and
# version/currency fields for one Code of Federal Regulations package.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GovInfoCFRPackageSummary:
    """Identity, classification, and version fields for one CFR package."""

    package_id: str
    collection_code: str
    collection_name: str
    title_number: int
    date_issued: str
    last_modified: str
    doc_class: str
    document_type: str
    category: str
    sudoc_class_number: str
    details_link: str
    granules_link: str
    download_links: Mapping[str, str]
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


_PACKAGE_SUMMARY_FIELDS = frozenset(
    {
        "dateIssued",
        "documentType",
        "partRange",
        "packageId",
        "collectionCode",
        "detailsLink",
        "title",
        "branch",
        "collectionName",
        "download",
        "pages",
        "governmentAuthor2",
        "titleNumber",
        "governmentAuthor1",
        "publisher",
        "volumeCount",
        "suDocClassNumber",
        "docClass",
        "lastModified",
        "category",
        "otherIdentifier",
        "granulesLink",
    }
)
_PACKAGE_DOWNLOAD_ROLES = frozenset({"premisLink", "xmlLink", "txtLink", "zipLink", "modsLink", "pdfLink"})


def parse_govinfo_cfr_package_summary(acquired: AcquiredGovInfoSource) -> GovInfoCFRPackageSummary:
    """Parse one CFR package summary's identity and version fields, never as subjects.

    This parser certifies only the field shape GovInfo publishes for Code of
    Federal Regulations (CFR) annual-edition packages; other GovInfo
    collections publish different package summary shapes (see
    GOVINFO_PORTFOLIO_GAPS).
    """

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed GovInfo CFR package summary source")
    root = json.loads(payload)
    if not isinstance(root, Mapping) or set(root) != _PACKAGE_SUMMARY_FIELDS:
        raise GovInfoSourceDriftError(f"GovInfo CFR package summary fields drifted: {sorted(root) if isinstance(root, Mapping) else root!r}")

    package_id = _require_text(root["packageId"], "packageId")
    if _GOVINFO_PACKAGE_ID.fullmatch(package_id) is None:
        raise GovInfoSourceDriftError("packageId is not a well-formed CFR package identifier")
    collection_code = _require_text(root["collectionCode"], "collectionCode")
    if _GOVINFO_COLLECTION_CODE.fullmatch(collection_code) is None or collection_code != "CFR":
        raise GovInfoSourceDriftError("this parser only certifies collectionCode == 'CFR'")
    collection_name = _require_text(root["collectionName"], "collectionName")
    title_number_text = _require_text(root["titleNumber"], "titleNumber")
    if not title_number_text.isdigit():
        raise GovInfoSourceDriftError("titleNumber must be a decimal digit string")
    title_number = int(title_number_text)

    part_range = root["partRange"]
    if not isinstance(part_range, Mapping) or set(part_range) != {"from", "to"}:
        raise GovInfoSourceDriftError("partRange fields drifted from {'from', 'to'}")
    _require_text(part_range["from"], "partRange.from")
    _require_text(part_range["to"], "partRange.to")

    other_identifier = root["otherIdentifier"]
    if not isinstance(other_identifier, Mapping) or not other_identifier:
        raise GovInfoSourceDriftError("otherIdentifier must be a non-empty object")
    for key, value in other_identifier.items():
        _require_text(key, "otherIdentifier key")
        _require_text(value, f"otherIdentifier[{key!r}]")

    download = root["download"]
    if not isinstance(download, Mapping) or set(download) != _PACKAGE_DOWNLOAD_ROLES:
        raise GovInfoSourceDriftError("download fields drifted from the six known GovInfo rendition roles")
    download_links: dict[str, str] = {}
    for role, value in download.items():
        link = _require_https_url(value, f"download.{role}")
        parsed_link = urlsplit(link)
        if parsed_link.hostname != "api.govinfo.gov" or package_id not in link:
            raise GovInfoSourceDriftError(f"download.{role} does not reference the official package on api.govinfo.gov")
        download_links[role] = link

    details_link = _require_https_url(root["detailsLink"], "detailsLink")
    granules_link = _require_https_url(root["granulesLink"], "granulesLink")
    date_issued = _optional_iso_date(root["dateIssued"], "dateIssued")
    if date_issued is None:
        raise GovInfoSourceDriftError("dateIssued must not be null")
    last_modified = validate_identifier_date(_require_text(root["lastModified"], "lastModified"), "lastModified")

    for field in ("pages", "volumeCount"):
        text = _require_text(root[field], field)
        if not text.isdigit():
            raise GovInfoSourceDriftError(f"{field} must be a decimal digit string")

    identifiers = (
        _make_identifier(
            value=package_id,
            kind="govInfoPackageId",
            authority_uri=GOVINFO_IDENTIFIER_AUTHORITY_URI,
            source_uri=acquired.pin.source.source_url,
            observed_at=acquired.pin.retrieved_at,
            source_digest=acquired.sha256,
        ),
        _make_identifier(
            value=_require_text(root["suDocClassNumber"], "suDocClassNumber"),
            kind="suDocClassNumber",
            authority_uri=GOVINFO_IDENTIFIER_AUTHORITY_URI,
            source_uri=acquired.pin.source.source_url,
            observed_at=acquired.pin.retrieved_at,
            source_digest=acquired.sha256,
        ),
    )

    return GovInfoCFRPackageSummary(
        package_id=package_id,
        collection_code=collection_code,
        collection_name=collection_name,
        title_number=title_number,
        date_issued=date_issued,
        last_modified=last_modified,
        doc_class=_require_text(root["docClass"], "docClass"),
        document_type=_require_text(root["documentType"], "documentType"),
        category=_require_text(root["category"], "category"),
        sudoc_class_number=_require_text(root["suDocClassNumber"], "suDocClassNumber"),
        details_link=details_link,
        granules_link=granules_link,
        download_links=download_links,
        identifiers=identifiers,
    )


# ---------------------------------------------------------------------------
# GovInfo package fixity: per-file SHA-256 digests published in a package's
# PREMIS preservation record.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GovInfoFixityRecord:
    """One PREMIS file object's official SHA-256 fixity digest."""

    object_identifier_value: str
    original_name: str
    content_location_uri: str
    algorithm: str
    digest: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedGovInfoPackageFixity:
    """A parsed, digest-pinned GovInfo PREMIS fixity record."""

    package_id: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    records: tuple[GovInfoFixityRecord, ...]


def _premis_tag(name: str) -> str:
    return f"{{{_PREMIS_NS}}}{name}"


def parse_govinfo_cfr_package_fixity(
    acquired: AcquiredGovInfoSource,
    *,
    expected_package_id: str,
) -> ParsedGovInfoPackageFixity:
    """Parse a package's PREMIS record for its SHA-256 file fixity digests.

    A ``file`` object without a ``fixity`` element is skipped: GovInfo only
    computes fixity for a subset of a package's file objects (see
    GOVINFO_PORTFOLIO_GAPS). A ``fixity`` element with an algorithm other
    than SHA-256 is treated as drift, since no non-SHA-256 digest has ever
    been observed from this source.
    """

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed GovInfo package PREMIS source")
    root = ElementTree.fromstring(payload)
    if root.tag != _premis_tag("premis"):
        raise GovInfoSourceDriftError("PREMIS payload root element is not a premis-v2 <premis> document")

    records: list[GovInfoFixityRecord] = []
    seen_object_ids: set[str] = set()
    for obj in root.findall(_premis_tag("object")):
        if obj.get(f"{{{_XSI_NS}}}type") != "file":
            continue
        fixity_el = obj.find(f"{_premis_tag('objectCharacteristics')}/{_premis_tag('fixity')}")
        if fixity_el is None:
            continue

        identifier_type_el = obj.find(f"{_premis_tag('objectIdentifier')}/{_premis_tag('objectIdentifierType')}")
        identifier_value_el = obj.find(f"{_premis_tag('objectIdentifier')}/{_premis_tag('objectIdentifierValue')}")
        if identifier_type_el is None or identifier_type_el.text != "FDsys ACP":
            raise GovInfoSourceDriftError("PREMIS file object uses an unrecognized objectIdentifierType")
        if identifier_value_el is None or not (identifier_value_el.text or "").strip():
            raise GovInfoSourceDriftError("PREMIS file object is missing an objectIdentifierValue")
        object_identifier_value = identifier_value_el.text.strip()  # type: ignore[union-attr]

        algorithm_el = fixity_el.find(_premis_tag("messageDigestAlgorithm"))
        digest_el = fixity_el.find(_premis_tag("messageDigest"))
        if algorithm_el is None or algorithm_el.text != "SHA-256":
            raise GovInfoSourceDriftError(
                f"PREMIS file object {object_identifier_value} uses an unsupported fixity algorithm"
            )
        digest = (digest_el.text or "").strip().lower() if digest_el is not None else ""
        if _HEX64.fullmatch(digest) is None:
            raise GovInfoSourceDriftError(
                f"PREMIS file object {object_identifier_value} has a malformed SHA-256 digest"
            )

        original_name_el = obj.find(_premis_tag("originalName"))
        if original_name_el is None or not (original_name_el.text or "").strip():
            raise GovInfoSourceDriftError(f"PREMIS file object {object_identifier_value} is missing originalName")
        original_name = original_name_el.text.strip()  # type: ignore[union-attr]
        if not original_name.startswith(expected_package_id):
            raise GovInfoSourceDriftError(
                f"PREMIS file object originalName {original_name!r} does not belong to {expected_package_id!r}"
            )

        location_type_el = obj.find(
            f"{_premis_tag('storage')}/{_premis_tag('contentLocation')}/{_premis_tag('contentLocationType')}"
        )
        location_value_el = obj.find(
            f"{_premis_tag('storage')}/{_premis_tag('contentLocation')}/{_premis_tag('contentLocationValue')}"
        )
        if location_type_el is None or location_type_el.text != "URI":
            raise GovInfoSourceDriftError(f"PREMIS file object {object_identifier_value} contentLocationType is not URI")
        if location_value_el is None or not (location_value_el.text or "").strip():
            raise GovInfoSourceDriftError(f"PREMIS file object {object_identifier_value} is missing contentLocationValue")
        content_location_uri = location_value_el.text.strip().rsplit(" ", 1)[-1]  # type: ignore[union-attr]
        parsed_uri = urlsplit(content_location_uri)
        if parsed_uri.scheme != "https" or parsed_uri.hostname != "www.govinfo.gov":
            raise GovInfoSourceDriftError(
                f"PREMIS file object {object_identifier_value} contentLocationValue is not a www.govinfo.gov HTTPS URI"
            )

        if object_identifier_value in seen_object_ids:
            raise GovInfoSourceDriftError(f"PREMIS payload repeats objectIdentifierValue {object_identifier_value!r}")
        seen_object_ids.add(object_identifier_value)

        identifier = _make_identifier(
            value=digest,
            kind="govInfoPremisSha256Fixity",
            authority_uri=GOVINFO_IDENTIFIER_AUTHORITY_URI,
            source_uri=acquired.pin.source.source_url,
            observed_at=acquired.pin.retrieved_at,
            source_digest=acquired.sha256,
        )
        records.append(
            GovInfoFixityRecord(
                object_identifier_value=object_identifier_value,
                original_name=original_name,
                content_location_uri=content_location_uri,
                algorithm="SHA-256",
                digest=digest,
                identifiers=(identifier,),
            )
        )

    if not records:
        raise GovInfoSourceDriftError("PREMIS payload does not contain any SHA-256 file fixity records")

    return ParsedGovInfoPackageFixity(
        package_id=expected_package_id,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        records=tuple(records),
    )


# ---------------------------------------------------------------------------
# Portfolio: the four resources assembled and cross-validated together.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GovInfoControlPortfolio:
    """The four captured resources, cross-validated, plus known unsupported controls."""

    collections: ParsedGovInfoCollections
    cfr_titles: ParsedECFRTitles
    cfr_package_summary: GovInfoCFRPackageSummary
    cfr_package_fixity: ParsedGovInfoPackageFixity
    cfr_hierarchy_level_types: tuple[str, ...]
    gaps: tuple[str, ...]


def assemble_govinfo_control_portfolio(
    collections: ParsedGovInfoCollections,
    cfr_titles: ParsedECFRTitles,
    cfr_package_summary: GovInfoCFRPackageSummary,
    cfr_package_fixity: ParsedGovInfoPackageFixity,
) -> GovInfoControlPortfolio:
    """Assemble the portfolio, refusing any cross-resource reference that fails closed."""

    if cfr_package_summary.collection_code not in collections.by_code():
        raise GovInfoAssignmentError(f"unknown GovInfo collection code {cfr_package_summary.collection_code!r}")
    if cfr_package_summary.title_number not in cfr_titles.by_number():
        raise GovInfoAssignmentError(f"unknown eCFR title number {cfr_package_summary.title_number!r}")
    if cfr_package_fixity.package_id != cfr_package_summary.package_id:
        raise GovInfoAssignmentError(
            "package identity mismatch: fixity record and package summary reference different packageIds"
        )
    return GovInfoControlPortfolio(
        collections=collections,
        cfr_titles=cfr_titles,
        cfr_package_summary=cfr_package_summary,
        cfr_package_fixity=cfr_package_fixity,
        cfr_hierarchy_level_types=ECFR_CFR_HIERARCHY_LEVEL_TYPES,
        gaps=GOVINFO_PORTFOLIO_GAPS,
    )


def validate_collection_code(value: str, portfolio: GovInfoControlPortfolio) -> GovInfoCollectionCode:
    """Resolve one GovInfo collection code, refusing to invent an unknown one."""

    match = portfolio.collections.by_code().get(value)
    if match is None:
        raise GovInfoAssignmentError(f"unknown GovInfo collection code {value!r}")
    return match


def validate_cfr_title_number(value: int, portfolio: GovInfoControlPortfolio) -> ECFRCFRTitle:
    """Resolve one eCFR CFR title number, refusing to invent an unknown one."""

    match = portfolio.cfr_titles.by_number().get(value)
    if match is None:
        raise GovInfoAssignmentError(f"unknown eCFR title number {value!r}")
    return match


# ---------------------------------------------------------------------------
# Deterministic closed package: the GovInfo Collections controlled code list
# packaged through the shared source-controlled-resource builder.
# ---------------------------------------------------------------------------

GOVINFO_COLLECTIONS_RESOURCE_ID = "govinfo-collections-2026-08-03"


def _collection_identifier_payload(
    *,
    identifier: ControlledIdentifier,
    source_path: str,
) -> dict[str, Any]:
    return {
        "value": identifier.value,
        "kind": identifier.kind,
        "authorityUri": identifier.authority_uri,
        "sourceUri": identifier.source_uri,
        "sourcePath": f"{source_path}.collectionCode",
        "observedAt": identifier.observed_at,
        "sourceDigest": identifier.source_digest,
    }


def _collection_observation_id(*, source_path: str, identifiers: Sequence[Mapping[str, Any]]) -> str:
    identity = {
        "resourceId": GOVINFO_COLLECTIONS_RESOURCE_ID,
        "sourceArtifact": GOVINFO_COLLECTIONS.source_url,
        "sourcePath": source_path,
        "identifiers": [
            {"value": item["value"], "kind": item["kind"], "authorityUri": item["authorityUri"]}
            for item in identifiers
        ],
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{GOVINFO_COLLECTIONS_RESOURCE_ID}:{digest}"


def _collections_observations(
    resource: ParsedGovInfoCollections,
) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    for ordinal, entry in enumerate(resource.collections):
        if entry.is_general_subject_concept:
            raise GovInfoAssignmentError(f"GovInfo collection row {ordinal} must not claim subject identity")
        source_path = f"$[{ordinal}]"
        identifiers = tuple(
            _collection_identifier_payload(identifier=identifier, source_path=source_path)
            for identifier in entry.identifiers
        )
        result.append(
            {
                "id": _collection_observation_id(source_path=source_path, identifiers=identifiers),
                "sourceArtifact": GOVINFO_COLLECTIONS.source_url,
                "sourcePath": source_path,
                # This ordinal is a source locator only; publisher identity is
                # preserved in identifiers and never derived from row order.
                "sourceOrdinal": ordinal,
                "labels": [
                    {
                        "value": entry.collection_name,
                        "language": "en",
                        "role": "preferred",
                    }
                ],
                "identifiers": list(identifiers),
                "eligibleUses": ["deterministicMetadata"],
                "conceptIdentityClaimed": False,
            }
        )
    return tuple(result)


def build_govinfo_collections_package(source_path: Path) -> SourceControlledResourceBundle:
    """Build the deterministic, development-only GovInfo Collections package."""

    path = Path(source_path)
    if path.is_symlink() or not path.is_file():
        raise GovInfoAcquisitionError(f"GovInfo Collections source is not a regular file: {path}")
    payload = path.read_bytes()
    with tempfile.TemporaryDirectory(prefix="refspec-govinfo-collections-") as temporary:
        acquire_root = Path(temporary)
        staged = acquire_root / GOVINFO_COLLECTIONS.filename
        staged.write_bytes(payload)
        acquired = acquire_govinfo_source(
            GOVINFO_COLLECTIONS_2026_08_03,
            acquire_root / "store",
            source_path=staged,
        )
        resource = parse_govinfo_collections(acquired)
    return build_source_controlled_resource_bundle(
        resource_id=GOVINFO_COLLECTIONS_RESOURCE_ID,
        title="GovInfo Collection Codes, captured 2026-08-03",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("deterministicMetadata",),
        captured_at=GOVINFO_COLLECTIONS_2026_08_03.retrieved_at,
        candidate_use_authorized=True,
        observations=_collections_observations(resource),
        source_artifacts={GOVINFO_COLLECTIONS.source_url: payload},
        source_observed_count=EXPECTED_COLLECTIONS_COUNT,
        gaps=[{"kind": "cfrOnlyPackageEvidence", "reason": GOVINFO_PORTFOLIO_GAPS[1]}],
    )


__all__ = [
    "ECFR_API_BASE",
    "ECFR_CFR_HIERARCHY_LEVEL_TYPES",
    "ECFR_CFR_TITLES",
    "ECFR_CFR_TITLES_2026_08_03",
    "ECFR_IDENTIFIER_AUTHORITY_URI",
    "ECFR_PUBLISHER",
    "EXPECTED_CFR_TITLES_COUNT",
    "EXPECTED_COLLECTIONS_COUNT",
    "GOVINFO_API_BASE",
    "GOVINFO_CFR_PACKAGE_ID",
    "GOVINFO_CFR_PACKAGE_PREMIS",
    "GOVINFO_CFR_PACKAGE_PREMIS_2026_08_03",
    "GOVINFO_CFR_PACKAGE_SUMMARY",
    "GOVINFO_CFR_PACKAGE_SUMMARY_2026_08_03",
    "GOVINFO_COLLECTIONS",
    "GOVINFO_COLLECTIONS_2026_08_03",
    "GOVINFO_COLLECTIONS_RESOURCE_ID",
    "GOVINFO_IDENTIFIER_AUTHORITY_URI",
    "GOVINFO_PORTFOLIO_GAPS",
    "GOVINFO_PUBLISHER",
    "AcquiredGovInfoSource",
    "ECFRCFRTitle",
    "FetchedGovInfoResponse",
    "GovInfoAcquisitionError",
    "GovInfoAssignmentError",
    "GovInfoCFRPackageSummary",
    "GovInfoCollectionCode",
    "GovInfoControlPortfolio",
    "GovInfoFetcher",
    "GovInfoFixityRecord",
    "GovInfoResourceError",
    "GovInfoSnapshotPin",
    "GovInfoSourceDriftError",
    "GovInfoSourceSpec",
    "ParsedECFRTitles",
    "ParsedGovInfoCollections",
    "ParsedGovInfoPackageFixity",
    "acquire_govinfo_source",
    "assemble_govinfo_control_portfolio",
    "build_govinfo_collections_package",
    "parse_ecfr_cfr_titles",
    "parse_govinfo_cfr_package_fixity",
    "parse_govinfo_cfr_package_summary",
    "parse_govinfo_collections",
    "sha256_digest",
    "validate_cfr_title_number",
    "validate_collection_code",
]
