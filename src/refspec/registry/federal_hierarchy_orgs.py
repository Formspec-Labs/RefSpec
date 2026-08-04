"""Pinned SAM.gov Federal Hierarchy organization-level identifier sample.

The SAM.gov Federal Hierarchy (FH) Public API
(https://open.gsa.gov/api/fh-public-api/) exposes the operational
funding/awarding organization hierarchy behind federal procurement and
financial data: Department/Ind. Agency and Sub-Tier organization records,
each carrying a Federal-Hierarchy-assigned ``fhorgid``, an FPDS-origin
``agencycode``/``oldfpdsofficecode``, a Treasury CGAC code, and a dotted
full-parent-path identifier that encodes the hierarchy level structure.

This module captures only the entity IDENTITY layer for that hierarchy: the
level structure (Department/Ind. Agency, Sub-Tier), the identifier shapes
published for each level, and a small pinned sample of records -- never a
bulk organization dump. No general subject concept is minted from any field;
``fhorgname`` is retained only as the publisher's own organization label.

Both live FH endpoints (``/v1/orgs`` and ``/v1/org/hierarchy``) require a
registered ``api_key`` even for a GET request. RefSpec used a registered key
to capture two exact public ``/v1/orgs`` response pages on 2026-08-03: the
default Department/Independent Agency page and a page filtered to Sub-Tiers.
The stored source URLs and response bytes contain no credential; the API's
``api_key`` query parameter is supplied only by the acquisition transport.
RefSpec pins three kinds of real GSA bytes:

* the official OpenAPI parameter definitions (``fh-public.zip``, fetched
  2026-08-03), which prove the required ``api_key`` parameter and the
  documented request/filter fields -- the response schema in that file is
  declared only as ``type: object``, so it carries no field-level shape; and
* an exact 10-record default page reporting 907 Department/Independent
  Agency records in the live public service; and
* an exact 10-record filtered page reporting 738 Sub-Tier records.

Acquisition accepts a local exact capture or an injected fetcher. The parser
is strict, so a response that drifts from the reviewed public shape -- an
added field, an unfamiliar ``fhorgtype``/``status`` value, more than one CGAC
per record, or more than 25 returned records -- fails loudly instead of being
silently accepted. Importing this module never opens a network connection.
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
from urllib.parse import parse_qs, urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import (
    ResourceUse,
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

FH_ORGS_PUBLISHER = "U.S. General Services Administration (SAM.gov Federal Hierarchy)"
FH_ORGS_DOC_URL = "https://open.gsa.gov/api/fh-public-api/"
FH_ORGS_API_BASE = "https://api.sam.gov/prod/federalorganizations/v1"
FH_ORGS_SEARCH_URL = f"{FH_ORGS_API_BASE}/orgs"
FH_ORGS_HIERARCHY_URL = f"{FH_ORGS_API_BASE}/org/hierarchy"
FH_ORGS_API_VERSION = "v1.0"

# These identifier schemes are published together through the FH API but are
# not all FH-assigned: agencycode/oldfpdsofficecode originate in FPDS, and
# CGAC is a Treasury governmentwide accounting classification. Each keeps its
# own authority so a downstream reader never mistakes one scheme for another.
FH_ORGS_IDENTIFIER_AUTHORITY_FH = "https://sam.gov/"
FH_ORGS_IDENTIFIER_AUTHORITY_FPDS = "https://www.fpds.gov/"
FH_ORGS_IDENTIFIER_AUTHORITY_CGAC = "https://www.fiscal.treasury.gov/"

# A "small pinned sample" ceiling. The public API's own documented page size
# defaults to 10 and allows up to 100; this development sample never needs
# more than a handful of records to demonstrate the level structure and
# identifier shapes, and the parser refuses anything larger outright,
# independent of what any pin's own expected_count claims.
MAX_SAMPLE_ORG_COUNT = 25

# Real bytes fetched anonymously from open.gsa.gov on 2026-08-03 20:17 (curl,
# HTTP 200): the FH Public API's own OpenAPI parameter definitions
# (fh-public.zip -> fh-public-org.yml / fh-public-hierarchy.yml). These are
# genuinely captured publisher bytes, unlike the constructed sample below.
FH_ORGS_OPENAPI_ORG_SHA256 = "sha256:cde16709eae892e183324d599a7b6d50b8c6d972d49b8982ab442ab1964b6e67"
FH_ORGS_OPENAPI_ORG_BYTE_LENGTH = 3_351
FH_ORGS_OPENAPI_HIERARCHY_SHA256 = "sha256:b3305995a7b2d7566986af1d6419c949ae35db6cf5a09b7cafcd2d69e65cba44"
FH_ORGS_OPENAPI_HIERARCHY_BYTE_LENGTH = 1_403
FH_ORGS_OPENAPI_RETRIEVED_AT = "2026-08-03T19:17:18Z"

OrgType = Literal["Department/Ind. Agency", "Sub-Tier"]
OrgStatus = Literal["ACTIVE", "INACTIVE"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_FH_ORG_ID = re.compile(r"^[1-9]\d{5,9}$")
_FPDS_AGENCY_CODE = re.compile(r"^[0-9A-Z]{2,6}$")
_CGAC_CODE = re.compile(r"^\d{3}$")
_FULL_PARENT_PATH_ID = re.compile(r"^[1-9]\d{5,9}(?:\.[1-9]\d{5,9})*$")
_ORG_TYPES: frozenset[str] = frozenset({"Department/Ind. Agency", "Sub-Tier"})
_STATUSES: frozenset[str] = frozenset({"ACTIVE", "INACTIVE"})
_ACTION_TYPES: frozenset[str] = frozenset({"CREATE", "MOVE", "MERGE"})
_REQUIRED_RECORD_FIELDS = frozenset(
    {
        "fhorgid",
        "fhorgname",
        "fhorgtype",
        "status",
        "fhdeptindagencyorgid",
        "fhagencyorgname",
        "agencycode",
        "cgaclist",
        "fhorgnamehistory",
        "fhorgparenthistory",
        "links",
    }
)
_OPTIONAL_RECORD_FIELDS = frozenset({"oldfpdsofficecode", "createdby", "createddate", "updatedby", "lastupdateddate"})
_ALLOWED_RECORD_FIELDS = _REQUIRED_RECORD_FIELDS | _OPTIONAL_RECORD_FIELDS
_PARENT_HISTORY_FIELDS = frozenset(
    {"fhfullparentpathid", "fhfullparentpathname", "effectivedate", "codehierarchy", "actiontype"}
)
_NAME_HISTORY_FIELDS = frozenset({"fhorgname", "effectivedate"})
_LINK_FIELDS = frozenset({"rel", "href"})


class FederalHierarchyOrgsError(ValueError):
    """Base class for Federal Hierarchy organization-sample failures."""


class FederalHierarchyAcquisitionError(FederalHierarchyOrgsError):
    """Exact sample bytes could not be acquired safely."""


class FederalHierarchySourceDriftError(FederalHierarchyOrgsError):
    """A sample no longer matches the reviewed structure or pin."""


class FederalHierarchyBulkCaptureRefusedError(FederalHierarchyOrgsError):
    """A capture exceeded the small-sample ceiling and was refused."""


@dataclass(frozen=True, slots=True)
class FHOrgsSampleSource:
    """One pinned Federal Hierarchy sample target."""

    source_url: str
    filename: str
    expected_count: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https":
            raise FederalHierarchyAcquisitionError("source_url must be an absolute HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise FederalHierarchyAcquisitionError("source_url must not contain credentials")
        if "api_key" in parse_qs(parsed.query, keep_blank_values=True):
            raise FederalHierarchyAcquisitionError("source_url must not contain an api_key credential")
        if not self.filename or Path(self.filename).name != self.filename:
            raise FederalHierarchyAcquisitionError("filename must be one plain path component")
        if not (0 < self.expected_count <= MAX_SAMPLE_ORG_COUNT):
            raise FederalHierarchyAcquisitionError(
                f"expected_count must be a small sample size between 1 and {MAX_SAMPLE_ORG_COUNT}"
            )


FH_ORGS_SAMPLE_SOURCE = FHOrgsSampleSource(
    source_url=FH_ORGS_SEARCH_URL,
    filename="fh-orgs-sample.json",
    expected_count=3,
)

FH_ORGS_DEFAULT_PAGE_SOURCE = FHOrgsSampleSource(
    source_url=FH_ORGS_SEARCH_URL,
    filename="fh-orgs-default-page.json",
    expected_count=10,
)
FH_ORGS_SUB_TIER_PAGE_SOURCE = FHOrgsSampleSource(
    source_url=f"{FH_ORGS_SEARCH_URL}?fhorgtype=Sub-Tier",
    filename="fh-orgs-sub-tier-page.json",
    expected_count=10,
)


@dataclass(frozen=True, slots=True)
class FHOrgsSnapshotPin:
    """Exact identity of one pinned sample response."""

    source: FHOrgsSampleSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    api_version: str = FH_ORGS_API_VERSION
    publisher_release: str | None = None

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise FederalHierarchyAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise FederalHierarchyAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at or not self.api_version:
            raise FederalHierarchyAcquisitionError("retrieved_at and api_version must not be empty")


# This sample was hand-assembled on 2026-08-03 from GSA's own real (non-dummy)
# documentation examples; see the module docstring for why it is not a live
# authenticated capture. Its digest still pins the exact development bytes.
FH_ORGS_SAMPLE_2026_08_03 = FHOrgsSnapshotPin(
    source=FH_ORGS_SAMPLE_SOURCE,
    retrieved_at="2026-08-03T15:22:00Z",
    expected_sha256="sha256:1e6384c59493825d5ce2ca6949f516cf19b5a9ac834e9db4f417dc78ac4f24e4",
    expected_byte_length=3_623,
)

# Exact authenticated responses from the public API. The API credential is
# absent from both the source URL and the preserved response bytes.
FH_ORGS_DEFAULT_PAGE_2026_08_03 = FHOrgsSnapshotPin(
    source=FH_ORGS_DEFAULT_PAGE_SOURCE,
    retrieved_at="2026-08-03T22:19:03Z",
    expected_sha256="sha256:582d409dd3743646dd6ec58acfa2bc8f346168f69b044cd6dd48e06f0c9cba49",
    expected_byte_length=9_270,
)
FH_ORGS_SUB_TIER_PAGE_2026_08_03 = FHOrgsSnapshotPin(
    source=FH_ORGS_SUB_TIER_PAGE_SOURCE,
    retrieved_at="2026-08-03T22:19:12Z",
    expected_sha256="sha256:601b9e7323cd4e6b1fbde3799533cbfb5c1f88d78039df84a24b6d60533eccd7",
    expected_byte_length=9_476,
)


@dataclass(frozen=True, slots=True)
class FetchedFHOrgsResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class FHOrgsFetcher(Protocol):
    """Small transport boundary for the FH Public API's ``/orgs`` endpoint."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedFHOrgsResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredFHOrgsSource:
    """One verified source object in the content-addressed store."""

    pin: FHOrgsSnapshotPin
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
    if parsed.scheme != "https" or parsed.hostname != "api.sam.gov":
        raise FederalHierarchyAcquisitionError(
            "fetcher resolved_url must remain on the official HTTPS api.sam.gov host"
        )
    if parsed.username is not None or parsed.password is not None:
        raise FederalHierarchyAcquisitionError("fetcher resolved_url must not contain credentials")
    if "api_key" in parse_qs(parsed.query, keep_blank_values=True):
        raise FederalHierarchyAcquisitionError("fetcher resolved_url must not retain an api_key credential")


def _verify_payload(payload: bytes, pin: FHOrgsSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise FederalHierarchySourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise FederalHierarchySourceDriftError(
            f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}"
        )
    try:
        json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FederalHierarchySourceDriftError(f"{location} is not valid JSON") from error
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: FHOrgsSnapshotPin) -> AcquiredFHOrgsSource:
    if path.is_symlink() or not path.is_file():
        raise FederalHierarchyAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(path.read_bytes(), pin, location="cached FH orgs source")
    return AcquiredFHOrgsSource(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type="application/json",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: FHOrgsSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredFHOrgsSource:
    actual_sha256, byte_length = _verify_payload(payload, pin, location=f"{acquisition_mode} FH orgs source")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".acquire-", suffix=".tmp", dir=final_path.parent)
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
        return AcquiredFHOrgsSource(
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


def acquire_fh_orgs_sample(
    pin: FHOrgsSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: FHOrgsFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredFHOrgsSource:
    """Acquire one exact sample response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise FederalHierarchyAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise FederalHierarchyAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise FederalHierarchyAcquisitionError(f"local FH orgs source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="application/json",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise FederalHierarchyAcquisitionError(
            "FH orgs sample is not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise FederalHierarchyAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "application/json":
        raise FederalHierarchySourceDriftError(f"FH orgs sample content type drifted to {fetched.content_type!r}")
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
class FHOrgRecord:
    """One organization row's exact label plus every retained identifier."""

    fhorgid: str
    fhorgname: str
    fhorgtype: OrgType
    status: OrgStatus
    identifiers: tuple[ControlledIdentifier, ...]
    parent_fhorgid: str
    parent_org_name: str
    full_parent_path_id: str
    full_parent_path_name: str
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class ParsedFHOrgsSample:
    """A parsed, digest-pinned Federal Hierarchy organization sample."""

    source: FHOrgsSampleSource
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    api_version: str
    publisher_release: str | None
    total_records_reported: int
    records: tuple[FHOrgRecord, ...]
    gaps: tuple[Mapping[str, str], ...]

    def by_org_id(self) -> dict[str, FHOrgRecord]:
        """Index every record by its Federal-Hierarchy-assigned org ID."""

        result: dict[str, FHOrgRecord] = {}
        for record in self.records:
            if record.fhorgid in result:
                raise FederalHierarchySourceDriftError(f"duplicate fhorgid in sample: {record.fhorgid}")
            result[record.fhorgid] = record
        return result

    def hierarchy_levels(self) -> tuple[OrgType, ...]:
        """Return the distinct organization levels observed, in level order."""

        return tuple(
            cast(OrgType, org_type)
            for org_type in ("Department/Ind. Agency", "Sub-Tier")
            if any(record.fhorgtype == org_type for record in self.records)
        )

    def children_of(self, fhorgid: str) -> tuple[FHOrgRecord, ...]:
        """Return every sample record whose department parent resolves in-sample."""

        return tuple(
            record for record in self.records if record.parent_fhorgid == fhorgid and record.fhorgid != fhorgid
        )


# Known, publisher-documented scope limits. These travel with every parsed
# sample and every built package rather than being silently dropped.
FH_ORGS_KNOWN_GAPS: tuple[Mapping[str, str], ...] = (
    {
        "kind": "samplePagesOnly",
        "reason": (
            "The two authenticated public captures preserve 10 records from each reviewed hierarchy level, "
            "not all 907 Department/Independent Agency or all 738 Sub-Tier records reported by the API."
        ),
    },
    {
        "kind": "defaultHierarchyDepthLimited",
        "reason": (
            "By default the API returns organization information for only the first two Federal "
            "Hierarchy levels (Department/Ind. Agency and Sub-Tier); any deeper office-level structure "
            "in the underlying system is not exposed by this public endpoint."
        ),
    },
    {
        "kind": "moveOrMergeHistoryLargelyUnavailable",
        "reason": (
            "fhorgparenthistory and fhorgmergehistory entries for moved or merged organizations are "
            "documented by the publisher as currently unavailable in the Federal Hierarchy; only current "
            "CREATE actions are observed in this pinned sample."
        ),
    },
    {
        "kind": "singleCgacPerRecordOnly",
        "reason": (
            "cgaclist is shaped as an array, but the publisher documents that this API version supports "
            "only one CGAC value per record."
        ),
    },
)


def _require_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalHierarchySourceDriftError(f"{label} must be non-empty text")
    return value


def _require_org_id(value: object, label: str) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FederalHierarchySourceDriftError(f"{label} must be a JSON integer")
    text = str(value)
    if _FH_ORG_ID.fullmatch(text) is None:
        raise FederalHierarchySourceDriftError(f"{label} has a malformed fhorgid shape: {value!r}")
    return text


def _require_cgaclist(value: object, label: str) -> str | None:
    if not isinstance(value, list):
        raise FederalHierarchySourceDriftError(f"{label} must be an array")
    if len(value) > 1:
        raise FederalHierarchySourceDriftError(
            f"{label} carries more than one CGAC entry; the publisher documents single-CGAC support only"
        )
    if not value:
        return None
    entry = value[0]
    if not isinstance(entry, Mapping) or set(entry) != {"cgac"}:
        raise FederalHierarchySourceDriftError(f"{label}[0] must be an object with exactly one 'cgac' field")
    cgac = entry["cgac"]
    if not isinstance(cgac, str) or _CGAC_CODE.fullmatch(cgac) is None:
        raise FederalHierarchySourceDriftError(f"{label}[0].cgac has a malformed CGAC shape: {cgac!r}")
    return cgac


def _require_parent_history(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, list) or not value:
        raise FederalHierarchySourceDriftError(f"{label} must be a non-empty array")
    entry = value[0]
    if not isinstance(entry, Mapping) or set(entry) != _PARENT_HISTORY_FIELDS:
        raise FederalHierarchySourceDriftError(
            f"{label}[0] fields drifted from the documented shape: {sorted(entry) if isinstance(entry, Mapping) else type(entry)}"
        )
    path_id = _require_str(entry["fhfullparentpathid"], f"{label}[0].fhfullparentpathid")
    if _FULL_PARENT_PATH_ID.fullmatch(path_id) is None:
        raise FederalHierarchySourceDriftError(f"{label}[0].fhfullparentpathid has a malformed shape: {path_id!r}")
    _require_str(entry["fhfullparentpathname"], f"{label}[0].fhfullparentpathname")
    if entry["actiontype"] not in _ACTION_TYPES:
        raise FederalHierarchySourceDriftError(f"{label}[0].actiontype is unsupported: {entry['actiontype']!r}")
    if entry["effectivedate"] is not None and not isinstance(entry["effectivedate"], str):
        raise FederalHierarchySourceDriftError(f"{label}[0].effectivedate must be a string or null")
    return entry


def _require_name_history(value: object, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise FederalHierarchySourceDriftError(f"{label} must be a non-empty array")
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping) or set(entry) != _NAME_HISTORY_FIELDS:
            raise FederalHierarchySourceDriftError(f"{label}[{index}] fields drifted from the documented shape")
        _require_str(entry["fhorgname"], f"{label}[{index}].fhorgname")
        if entry["effectivedate"] is not None and not isinstance(entry["effectivedate"], str):
            raise FederalHierarchySourceDriftError(f"{label}[{index}].effectivedate must be a string or null")


def _require_links(value: object, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise FederalHierarchySourceDriftError(f"{label} must be a non-empty array")
    rels: set[object] = set()
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping) or set(entry) != _LINK_FIELDS:
            raise FederalHierarchySourceDriftError(f"{label}[{index}] fields drifted from the documented shape")
        _require_str(entry["href"], f"{label}[{index}].href")
        rels.add(entry["rel"])
    if "self" not in rels:
        raise FederalHierarchySourceDriftError(f"{label} must include a 'self' link")


def parse_fh_orgs_sample(acquired: AcquiredFHOrgsSource) -> ParsedFHOrgsSample:
    """Parse a small pinned FH orgs sample without minting any subject concept."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed FH orgs source")
    try:
        root = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FederalHierarchySourceDriftError("FH orgs sample payload is not valid JSON") from error
    if not isinstance(root, Mapping) or set(root) != {"totalrecords", "orglist"}:
        shape = sorted(root) if isinstance(root, Mapping) else type(root).__name__
        raise FederalHierarchySourceDriftError(
            f"FH orgs sample top-level fields drifted from the documented shape: {shape}"
        )

    total_records = root["totalrecords"]
    if not isinstance(total_records, int) or isinstance(total_records, bool) or total_records < 0:
        raise FederalHierarchySourceDriftError("totalrecords must be a non-negative integer")

    orglist = root["orglist"]
    if not isinstance(orglist, list):
        raise FederalHierarchySourceDriftError("orglist must be an array")
    # This ceiling is independent of the pin's own expected_count: even a
    # mismatched or forged pin cannot make a bulk capture parse successfully.
    if len(orglist) > MAX_SAMPLE_ORG_COUNT:
        raise FederalHierarchyBulkCaptureRefusedError(
            f"orglist carries {len(orglist)} records, exceeding the {MAX_SAMPLE_ORG_COUNT}-record small-sample "
            "ceiling; RefSpec never ingests a bulk organization dump"
        )
    if len(orglist) != acquired.pin.source.expected_count:
        raise FederalHierarchySourceDriftError(
            f"orglist count drift: expected {acquired.pin.source.expected_count}, parsed {len(orglist)}"
        )
    if total_records < len(orglist):
        raise FederalHierarchySourceDriftError("totalrecords cannot be smaller than the returned orglist")

    records: list[FHOrgRecord] = []
    for ordinal, entry in enumerate(orglist):
        label = f"orglist[{ordinal}]"
        if not isinstance(entry, Mapping):
            raise FederalHierarchySourceDriftError(f"{label} must be an object")
        present = set(entry)
        if not _REQUIRED_RECORD_FIELDS.issubset(present) or not present.issubset(_ALLOWED_RECORD_FIELDS):
            raise FederalHierarchySourceDriftError(
                f"{label} fields drifted from the documented shape: {sorted(present)}"
            )

        fhorgid = _require_org_id(entry["fhorgid"], f"{label}.fhorgid")
        fhorgname = _require_str(entry["fhorgname"], f"{label}.fhorgname")
        fhorgtype = entry["fhorgtype"]
        if fhorgtype not in _ORG_TYPES:
            raise FederalHierarchySourceDriftError(f"{label}.fhorgtype is an unsupported level: {fhorgtype!r}")
        status = entry["status"]
        if status not in _STATUSES:
            raise FederalHierarchySourceDriftError(f"{label}.status is unsupported: {status!r}")
        createddate = entry.get("createddate")
        if createddate is not None:
            _require_str(createddate, f"{label}.createddate")
        fhdeptindagencyorgid = _require_org_id(entry["fhdeptindagencyorgid"], f"{label}.fhdeptindagencyorgid")
        fhagencyorgname = _require_str(entry["fhagencyorgname"], f"{label}.fhagencyorgname")
        agencycode = _require_str(entry["agencycode"], f"{label}.agencycode")
        if _FPDS_AGENCY_CODE.fullmatch(agencycode) is None:
            raise FederalHierarchySourceDriftError(f"{label}.agencycode has a malformed shape: {agencycode!r}")
        old_office_code = entry.get("oldfpdsofficecode")
        if old_office_code is not None and (
            not isinstance(old_office_code, str) or _FPDS_AGENCY_CODE.fullmatch(old_office_code) is None
        ):
            raise FederalHierarchySourceDriftError(
                f"{label}.oldfpdsofficecode has a malformed shape: {old_office_code!r}"
            )
        cgac = _require_cgaclist(entry["cgaclist"], f"{label}.cgaclist")
        _require_name_history(entry["fhorgnamehistory"], f"{label}.fhorgnamehistory")
        parent_history = _require_parent_history(entry["fhorgparenthistory"], f"{label}.fhorgparenthistory")
        _require_links(entry["links"], f"{label}.links")

        identifiers: list[ControlledIdentifier] = [
            ControlledIdentifier(
                value=fhorgid,
                kind="fhOrgId",
                authority_uri=FH_ORGS_IDENTIFIER_AUTHORITY_FH,
                source_uri=acquired.pin.source.source_url,
                observed_at=acquired.pin.retrieved_at,
                effective_at=None,
                source_digest=acquired.sha256,
            ),
            ControlledIdentifier(
                value=agencycode,
                kind="fpdsAgencyCode",
                authority_uri=FH_ORGS_IDENTIFIER_AUTHORITY_FPDS,
                source_uri=acquired.pin.source.source_url,
                observed_at=acquired.pin.retrieved_at,
                effective_at=None,
                source_digest=acquired.sha256,
            ),
        ]
        if old_office_code is not None:
            identifiers.append(
                ControlledIdentifier(
                    value=old_office_code,
                    kind="oldFpdsOfficeCode",
                    authority_uri=FH_ORGS_IDENTIFIER_AUTHORITY_FPDS,
                    source_uri=acquired.pin.source.source_url,
                    observed_at=acquired.pin.retrieved_at,
                    effective_at=None,
                    source_digest=acquired.sha256,
                )
            )
        if cgac is not None:
            identifiers.append(
                ControlledIdentifier(
                    value=cgac,
                    kind="cgacCode",
                    authority_uri=FH_ORGS_IDENTIFIER_AUTHORITY_CGAC,
                    source_uri=acquired.pin.source.source_url,
                    observed_at=acquired.pin.retrieved_at,
                    effective_at=None,
                    source_digest=acquired.sha256,
                )
            )
        full_parent_path_id = cast(str, parent_history["fhfullparentpathid"])
        identifiers.append(
            ControlledIdentifier(
                value=full_parent_path_id,
                kind="fhFullParentPathId",
                authority_uri=FH_ORGS_IDENTIFIER_AUTHORITY_FH,
                source_uri=acquired.pin.source.source_url,
                observed_at=acquired.pin.retrieved_at,
                effective_at=None,
                source_digest=acquired.sha256,
            )
        )

        records.append(
            FHOrgRecord(
                fhorgid=fhorgid,
                fhorgname=fhorgname,
                fhorgtype=cast(OrgType, fhorgtype),
                status=cast(OrgStatus, status),
                identifiers=tuple(identifiers),
                parent_fhorgid=fhdeptindagencyorgid,
                parent_org_name=fhagencyorgname,
                full_parent_path_id=full_parent_path_id,
                full_parent_path_name=cast(str, parent_history["fhfullparentpathname"]),
                source_ordinal=ordinal,
            )
        )

    org_ids = [record.fhorgid for record in records]
    if len(org_ids) != len(set(org_ids)):
        raise FederalHierarchySourceDriftError("FH orgs sample contains duplicate fhorgid values")

    return ParsedFHOrgsSample(
        source=acquired.pin.source,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        api_version=acquired.pin.api_version,
        publisher_release=acquired.pin.publisher_release,
        total_records_reported=total_records,
        records=tuple(records),
        gaps=FH_ORGS_KNOWN_GAPS,
    )


FH_ORGS_RESOURCE_ID = "federal-hierarchy-orgs-2026-08-03"
FH_ORGS_PACKAGE_TITLE = "SAM.gov Federal Hierarchy organization sample, captured 2026-08-03"
FH_ORGS_PACKAGE_USES: tuple[ResourceUse, ...] = ("deterministicMetadata",)

_IDENTIFIER_SOURCE_PATH = {
    "fhOrgId": "fhorgid",
    "fpdsAgencyCode": "agencycode",
    "oldFpdsOfficeCode": "oldfpdsofficecode",
    "cgacCode": "cgaclist[0].cgac",
    "fhFullParentPathId": "fhorgparenthistory[0].fhfullparentpathid",
}


def _identifier_payload(*, identifier: ControlledIdentifier, source_path: str) -> dict[str, Any]:
    if identifier.kind not in _IDENTIFIER_SOURCE_PATH:
        raise FederalHierarchyOrgsError(f"unsupported FH orgs identifier kind {identifier.kind!r}")
    result: dict[str, Any] = {
        "value": identifier.value,
        "kind": identifier.kind,
        "authorityUri": identifier.authority_uri,
        "sourceUri": identifier.source_uri,
        "sourcePath": f"{source_path}.{_IDENTIFIER_SOURCE_PATH[identifier.kind]}",
        "observedAt": identifier.observed_at,
        "sourceDigest": identifier.source_digest,
    }
    if identifier.effective_at is not None:
        result["effectiveFrom"] = identifier.effective_at
    return result


def _observation_id(*, source_artifact: str, source_path: str, identifiers: Sequence[Mapping[str, Any]]) -> str:
    identity = {
        "resourceId": FH_ORGS_RESOURCE_ID,
        "sourceArtifact": source_artifact,
        "sourcePath": source_path,
        "identifiers": [
            {"value": identifier["value"], "kind": identifier["kind"], "authorityUri": identifier["authorityUri"]}
            for identifier in identifiers
        ],
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{FH_ORGS_RESOURCE_ID}:{digest}"


def _observations(sample: ParsedFHOrgsSample) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    for record in sample.records:
        source_path = f"$.orglist[{record.source_ordinal}]"
        identifiers = tuple(
            _identifier_payload(identifier=identifier, source_path=source_path) for identifier in record.identifiers
        )
        result.append(
            {
                "id": _observation_id(
                    source_artifact=sample.source.source_url,
                    source_path=source_path,
                    identifiers=identifiers,
                ),
                "sourceArtifact": sample.source.source_url,
                "sourcePath": source_path,
                # This ordinal is a source locator only. Organization identity
                # is preserved in identifiers and never derived from row order.
                "sourceOrdinal": record.source_ordinal,
                "labels": [{"value": record.fhorgname, "language": "en", "role": "preferred"}],
                "identifiers": list(identifiers),
                "uses": list(FH_ORGS_PACKAGE_USES),
                "conceptIdentityClaimed": False,
            }
        )
    return tuple(result)


def build_federal_hierarchy_orgs_package(source_path: Path) -> SourceControlledResourceBundle:
    """Build one exact, development-only ``controlledCodeList`` package."""

    path = Path(source_path)
    if path.is_symlink() or not path.is_file():
        raise FederalHierarchyOrgsError(f"FH orgs sample source is not a regular file: {path}")
    payload = path.read_bytes()
    payload_identity = (sha256_digest(payload), len(payload))
    known_pins = (FH_ORGS_DEFAULT_PAGE_2026_08_03, FH_ORGS_SUB_TIER_PAGE_2026_08_03)
    pin = next(
        (
            candidate
            for candidate in known_pins
            if (candidate.expected_sha256, candidate.expected_byte_length) == payload_identity
        ),
        None,
    )
    if pin is None:
        raise FederalHierarchySourceDriftError(
            "FH orgs package input does not match either authenticated public page pin"
        )
    with tempfile.TemporaryDirectory(prefix="refspec-fh-orgs-package-") as temporary:
        root = Path(temporary)
        staged = root / pin.source.filename
        staged.write_bytes(payload)
        acquired = acquire_fh_orgs_sample(pin, root / "store", source_path=staged)
        sample = parse_fh_orgs_sample(acquired)
    return build_source_controlled_resource_bundle(
        resource_id=FH_ORGS_RESOURCE_ID,
        title=FH_ORGS_PACKAGE_TITLE,
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=FH_ORGS_PACKAGE_USES,
        captured_at=pin.retrieved_at,
        observations=_observations(sample),
        source_artifacts={pin.source.source_url: payload},
        gaps=FH_ORGS_KNOWN_GAPS,
    )


__all__ = [
    "FH_ORGS_API_BASE",
    "FH_ORGS_API_VERSION",
    "FH_ORGS_DEFAULT_PAGE_2026_08_03",
    "FH_ORGS_DEFAULT_PAGE_SOURCE",
    "FH_ORGS_DOC_URL",
    "FH_ORGS_HIERARCHY_URL",
    "FH_ORGS_IDENTIFIER_AUTHORITY_CGAC",
    "FH_ORGS_IDENTIFIER_AUTHORITY_FH",
    "FH_ORGS_IDENTIFIER_AUTHORITY_FPDS",
    "FH_ORGS_KNOWN_GAPS",
    "FH_ORGS_OPENAPI_HIERARCHY_BYTE_LENGTH",
    "FH_ORGS_OPENAPI_HIERARCHY_SHA256",
    "FH_ORGS_OPENAPI_ORG_BYTE_LENGTH",
    "FH_ORGS_OPENAPI_ORG_SHA256",
    "FH_ORGS_OPENAPI_RETRIEVED_AT",
    "FH_ORGS_PACKAGE_TITLE",
    "FH_ORGS_PACKAGE_USES",
    "FH_ORGS_PUBLISHER",
    "FH_ORGS_RESOURCE_ID",
    "FH_ORGS_SAMPLE_2026_08_03",
    "FH_ORGS_SAMPLE_SOURCE",
    "FH_ORGS_SEARCH_URL",
    "FH_ORGS_SUB_TIER_PAGE_2026_08_03",
    "FH_ORGS_SUB_TIER_PAGE_SOURCE",
    "MAX_SAMPLE_ORG_COUNT",
    "AcquiredFHOrgsSource",
    "AcquisitionMode",
    "FHOrgRecord",
    "FHOrgsFetcher",
    "FHOrgsSampleSource",
    "FHOrgsSnapshotPin",
    "FederalHierarchyAcquisitionError",
    "FederalHierarchyBulkCaptureRefusedError",
    "FederalHierarchyOrgsError",
    "FederalHierarchySourceDriftError",
    "FetchedFHOrgsResponse",
    "OrgStatus",
    "OrgType",
    "ParsedFHOrgsSample",
    "acquire_fh_orgs_sample",
    "build_federal_hierarchy_orgs_package",
    "parse_fh_orgs_sample",
    "sha256_digest",
]
