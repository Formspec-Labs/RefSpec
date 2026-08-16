"""The complete SAM.gov Federal Hierarchy organization roster.

REF-032 removed the first-page Federal Hierarchy exemplar (20 records) and
named its completion as a follow-up. This module carries the complete public
roster: every organization the FH Public API's ``/v1/orgs`` endpoint returns,
captured as five exact 200-record pages on 2026-08-15 plus two one-record
filtered responses that witness the API's own per-level totals.

The API's own numbers partition cleanly: the unfiltered endpoint reports 907
total organizations, of which 169 are ``Department/Ind. Agency`` and 738 are
``Sub-Tier`` — the two witness responses report exactly those totals. (The
REF-032 ledger recorded this follow-up against a roster of 1,645, a figure
that double-counts: the API's 907 total already includes the 738 sub-tiers
beside the 169 departments. The amendment under REF-032 records the
correction.)

``refspec.registry.federal_hierarchy_orgs`` remains the identifier-shape
module for this hierarchy and deliberately refuses bulk captures; this module
is the bulk roster it refuses to be, under its own pins. Publisher anomalies
are retained verbatim instead of being normalized away: one record carries
five CGAC codes although the publisher documents single-CGAC support, three
records carry ``{"cgac": null}`` entries, one record (``500021729``, named
``Testing DEPT`` by the publisher) carries an empty ``agencycode``, and
eleven records carry no ``fhorgparenthistory`` and therefore no
full-parent-path identifier.

The live endpoint requires a registered ``api_key`` even for a GET; the
stored source URLs and response bytes contain no credential — the key is
supplied only by the acquisition transport. Importing this module performs no
network access.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

FH_COMPLETE_PUBLISHER = "U.S. General Services Administration (SAM.gov Federal Hierarchy)"
FH_COMPLETE_DOC_URL = "https://open.gsa.gov/api/fh-public-api/"
FH_COMPLETE_ORGS_URL = "https://api.sam.gov/prod/federalorganizations/v1/orgs"
FH_COMPLETE_PAGE_LIMIT = 200
FH_COMPLETE_LICENSE_RIGHTS_STATEMENT = "US federal public domain (17 USC 105) with no explicit CC license"
FH_COMPLETE_SOURCE_VERSION_NOTE = (
    "The publisher exposes this as a rolling, unversioned API; no versioned source URL is available."
)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_FH_ORG_ID = re.compile(r"^[1-9]\d{5,9}$")
_FPDS_AGENCY_CODE = re.compile(r"^[0-9A-Z]{2,6}$")
_CGAC_CODE = re.compile(r"^\d{3}$")
_FULL_PARENT_PATH_ID = re.compile(r"^[1-9]\d{5,9}(?:\.[1-9]\d{5,9})*$")

OrgType = Literal["Department/Ind. Agency", "Sub-Tier"]
OrgStatus = Literal["ACTIVE", "INACTIVE"]
_ORG_TYPES = frozenset({"Department/Ind. Agency", "Sub-Tier"})
_STATUSES = frozenset({"ACTIVE", "INACTIVE"})

_REQUIRED_RECORD_FIELDS = frozenset(
    {
        "agencycode",
        "cgaclist",
        "fhagencyorgname",
        "fhdeptindagencyorgid",
        "fhorgid",
        "fhorgname",
        "fhorgnamehistory",
        "fhorgtype",
        "links",
        "status",
    }
)
_OPTIONAL_RECORD_FIELDS = frozenset(
    {
        "createdby",
        "createddate",
        "fhorgparenthistory",
        "lastupdateddate",
        "oldfpdsofficecode",
        "updatedby",
    }
)
_ALLOWED_RECORD_FIELDS = _REQUIRED_RECORD_FIELDS | _OPTIONAL_RECORD_FIELDS


class FederalHierarchyCompleteError(ValueError):
    """Base class for complete-roster failures."""


class FHCompleteSourceDriftError(FederalHierarchyCompleteError):
    """A captured page no longer matches the reviewed structure or pin."""


@dataclass(frozen=True, slots=True)
class FHCompletePagePin:
    """Exact identity of one captured credential-free ``/v1/orgs`` response."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    expected_returned: int
    expected_total: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "api.sam.gov":
            raise FederalHierarchyCompleteError("source_url must be an official HTTPS api.sam.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise FederalHierarchyCompleteError("source_url must not contain credentials")
        if "api_key" in parse_qs(parsed.query, keep_blank_values=True):
            raise FederalHierarchyCompleteError("source_url must not contain an api_key credential")
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise FederalHierarchyCompleteError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise FederalHierarchyCompleteError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise FederalHierarchyCompleteError("retrieved_at must not be empty")
        if not (0 < self.expected_returned <= FH_COMPLETE_PAGE_LIMIT):
            raise FederalHierarchyCompleteError("expected_returned must fit within one API page")
        if self.expected_total < self.expected_returned:
            raise FederalHierarchyCompleteError("expected_total cannot be smaller than one page")


FH_COMPLETE_PAGES_2026_08_15: tuple[FHCompletePagePin, ...] = (
    FHCompletePagePin(
        source_url=f"{FH_COMPLETE_ORGS_URL}?limit=200&offset=0",
        retrieved_at="2026-08-15T07:48:03Z",
        expected_sha256="sha256:b684a583f8775ee109cf113949fe1a1c59d1166d2db718b48583272274bca8ff",
        expected_byte_length=183_892,
        expected_returned=200,
        expected_total=907,
    ),
    FHCompletePagePin(
        source_url=f"{FH_COMPLETE_ORGS_URL}?limit=200&offset=200",
        retrieved_at="2026-08-15T07:48:03Z",
        expected_sha256="sha256:8043dd5bcc850b0036ed1c28c5f36a55d1bb44e4c0c934548c9f8086f21ad6e2",
        expected_byte_length=179_237,
        expected_returned=200,
        expected_total=907,
    ),
    FHCompletePagePin(
        source_url=f"{FH_COMPLETE_ORGS_URL}?limit=200&offset=400",
        retrieved_at="2026-08-15T07:48:03Z",
        expected_sha256="sha256:7dbb2ab10f480f08f661049cda4753d5618983d4ba0c95fca314348f53804c64",
        expected_byte_length=181_649,
        expected_returned=200,
        expected_total=907,
    ),
    FHCompletePagePin(
        source_url=f"{FH_COMPLETE_ORGS_URL}?limit=200&offset=600",
        retrieved_at="2026-08-15T07:48:03Z",
        expected_sha256="sha256:90be1eb4f7dafdea9e26e87596f2c17df8d09cdcc8b0a228758ef29a94af1e96",
        expected_byte_length=182_189,
        expected_returned=200,
        expected_total=907,
    ),
    FHCompletePagePin(
        source_url=f"{FH_COMPLETE_ORGS_URL}?limit=200&offset=800",
        retrieved_at="2026-08-15T07:48:04Z",
        expected_sha256="sha256:bb78b6c039167ef158bea672275c86961be784e269f4db41a52e4b0cd09c277e",
        expected_byte_length=100_030,
        expected_returned=107,
        expected_total=907,
    ),
)
FH_TOTAL_DEPT_WITNESS_2026_08_15 = FHCompletePagePin(
    source_url=f"{FH_COMPLETE_ORGS_URL}?fhorgtype=Department%2FInd.%20Agency&limit=1&offset=0",
    retrieved_at="2026-08-15T07:48:04Z",
    expected_sha256="sha256:e08d262428b48a2539c8db513982510e731978220461e7058c155d2a01ab35b6",
    expected_byte_length=919,
    expected_returned=1,
    expected_total=169,
)
FH_TOTAL_SUBTIER_WITNESS_2026_08_15 = FHCompletePagePin(
    source_url=f"{FH_COMPLETE_ORGS_URL}?fhorgtype=Sub-Tier&limit=1&offset=0",
    retrieved_at="2026-08-15T07:48:04Z",
    expected_sha256="sha256:9f23757566e92492e4eeb0bd272a677048a87985bba9db98930f354359431359",
    expected_byte_length=898,
    expected_returned=1,
    expected_total=738,
)


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _verified_page(payload: bytes, pin: FHCompletePagePin, *, location: str) -> Mapping[str, Any]:
    if len(payload) != pin.expected_byte_length:
        raise FHCompleteSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {len(payload)}"
        )
    actual = sha256_digest(payload)
    if actual != pin.expected_sha256:
        raise FHCompleteSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual}")
    try:
        root = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FHCompleteSourceDriftError(f"{location} is not valid JSON") from error
    if not isinstance(root, Mapping) or set(root) != {"totalrecords", "orglist"}:
        raise FHCompleteSourceDriftError(f"{location} top-level fields drifted from the documented shape")
    total = root["totalrecords"]
    orglist = root["orglist"]
    if not isinstance(total, int) or isinstance(total, bool) or total != pin.expected_total:
        raise FHCompleteSourceDriftError(
            f"{location} totalrecords drift: expected {pin.expected_total}, got {total!r}"
        )
    if not isinstance(orglist, list) or len(orglist) != pin.expected_returned:
        raise FHCompleteSourceDriftError(
            f"{location} returned-record drift: expected {pin.expected_returned} records"
        )
    return root


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FHCompleteSourceDriftError(f"{label} must be non-empty text")
    return value


def _require_org_id(value: object, label: str) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FHCompleteSourceDriftError(f"{label} must be a JSON integer")
    text = str(value)
    if _FH_ORG_ID.fullmatch(text) is None:
        raise FHCompleteSourceDriftError(f"{label} has a malformed fhorgid shape: {value!r}")
    return text


@dataclass(frozen=True, slots=True)
class FHCompleteOrgRecord:
    """One organization row exactly as one pinned roster page states it."""

    fhorgid: str
    name: str
    org_type: OrgType
    status: OrgStatus
    parent_fhorgid: str
    parent_name: str
    agency_code: str
    cgac_codes: tuple[str, ...]
    old_fpds_office_code: str | None
    null_cgac_entry_count: int
    full_parent_path_id: str | None
    full_parent_path_name: str | None
    page_index: int
    source_ordinal: int
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class FederalHierarchyCompleteRoster:
    """The parsed, digest-pinned complete organization roster."""

    records: tuple[FHCompleteOrgRecord, ...]
    total_records_reported: int
    department_count: int
    sub_tier_count: int
    dept_witness_total: int
    sub_tier_witness_total: int
    anomalies: Mapping[str, Any]

    def by_org_id(self) -> dict[str, FHCompleteOrgRecord]:
        return {record.fhorgid: record for record in self.records}


def _parse_record(entry: object, *, page_index: int, ordinal: int) -> FHCompleteOrgRecord:
    label = f"page[{page_index}].orglist[{ordinal}]"
    if not isinstance(entry, Mapping):
        raise FHCompleteSourceDriftError(f"{label} must be an object")
    present = set(entry)
    if not _REQUIRED_RECORD_FIELDS.issubset(present) or not present.issubset(_ALLOWED_RECORD_FIELDS):
        raise FHCompleteSourceDriftError(f"{label} fields drifted from the documented shape: {sorted(present)}")

    fhorgid = _require_org_id(entry["fhorgid"], f"{label}.fhorgid")
    org_type = entry["fhorgtype"]
    if org_type not in _ORG_TYPES:
        raise FHCompleteSourceDriftError(f"{label}.fhorgtype is an unsupported level: {org_type!r}")
    status = entry["status"]
    if status not in _STATUSES:
        raise FHCompleteSourceDriftError(f"{label}.status is unsupported: {status!r}")

    # The publisher's own capture carries one empty agencycode; the value is
    # retained verbatim and reported as an anomaly rather than repaired.
    agency_code = entry["agencycode"]
    if not isinstance(agency_code, str) or (agency_code and _FPDS_AGENCY_CODE.fullmatch(agency_code) is None):
        raise FHCompleteSourceDriftError(f"{label}.agencycode has a malformed shape: {agency_code!r}")

    # The publisher's live roster carries three ``{"cgac": null}`` entries;
    # they are retained as a counted anomaly rather than repaired or refused.
    cgaclist = entry["cgaclist"]
    if not isinstance(cgaclist, list):
        raise FHCompleteSourceDriftError(f"{label}.cgaclist must be an array")
    cgac_codes: list[str] = []
    null_cgac_entries = 0
    for position, item in enumerate(cgaclist):
        if not isinstance(item, Mapping) or set(item) != {"cgac"}:
            raise FHCompleteSourceDriftError(f"{label}.cgaclist[{position}] must be an object with one cgac field")
        cgac = item["cgac"]
        if cgac is None:
            null_cgac_entries += 1
            continue
        if not isinstance(cgac, str) or _CGAC_CODE.fullmatch(cgac) is None:
            raise FHCompleteSourceDriftError(f"{label}.cgaclist[{position}].cgac has a malformed shape: {cgac!r}")
        cgac_codes.append(cgac)
    if len(set(cgac_codes)) != len(cgac_codes):
        raise FHCompleteSourceDriftError(f"{label}.cgaclist repeats a CGAC code")

    old_office_code = entry.get("oldfpdsofficecode")
    if old_office_code is not None and (
        not isinstance(old_office_code, str) or _FPDS_AGENCY_CODE.fullmatch(old_office_code) is None
    ):
        raise FHCompleteSourceDriftError(f"{label}.oldfpdsofficecode has a malformed shape: {old_office_code!r}")

    name_history = entry["fhorgnamehistory"]
    if not isinstance(name_history, list) or not name_history:
        raise FHCompleteSourceDriftError(f"{label}.fhorgnamehistory must be a non-empty array")
    for position, item in enumerate(name_history):
        if not isinstance(item, Mapping) or set(item) != {"effectivedate", "fhorgname"}:
            raise FHCompleteSourceDriftError(f"{label}.fhorgnamehistory[{position}] fields drifted")
        _require_text(item["fhorgname"], f"{label}.fhorgnamehistory[{position}].fhorgname")
        if item["effectivedate"] is not None and not isinstance(item["effectivedate"], str):
            raise FHCompleteSourceDriftError(f"{label}.fhorgnamehistory[{position}].effectivedate drifted")

    full_parent_path_id: str | None = None
    full_parent_path_name: str | None = None
    parent_history = entry.get("fhorgparenthistory")
    if parent_history is not None:
        if not isinstance(parent_history, list) or len(parent_history) != 1:
            raise FHCompleteSourceDriftError(f"{label}.fhorgparenthistory must carry exactly one entry when present")
        item = parent_history[0]
        expected_fields = {"actiontype", "codehierarchy", "effectivedate", "fhfullparentpathid", "fhfullparentpathname"}
        if not isinstance(item, Mapping) or set(item) != expected_fields:
            raise FHCompleteSourceDriftError(f"{label}.fhorgparenthistory[0] fields drifted")
        if item["actiontype"] != "CREATE":
            raise FHCompleteSourceDriftError(f"{label}.fhorgparenthistory[0].actiontype is unsupported: {item['actiontype']!r}")
        path_id = _require_text(item["fhfullparentpathid"], f"{label}.fhorgparenthistory[0].fhfullparentpathid")
        if _FULL_PARENT_PATH_ID.fullmatch(path_id) is None:
            raise FHCompleteSourceDriftError(f"{label}.fhorgparenthistory[0].fhfullparentpathid has a malformed shape")
        full_parent_path_id = path_id
        full_parent_path_name = _require_text(
            item["fhfullparentpathname"],
            f"{label}.fhorgparenthistory[0].fhfullparentpathname",
        )

    links = entry["links"]
    if not isinstance(links, list) or not links:
        raise FHCompleteSourceDriftError(f"{label}.links must be a non-empty array")
    rels: set[object] = set()
    for position, item in enumerate(links):
        if not isinstance(item, Mapping) or set(item) != {"href", "rel"}:
            raise FHCompleteSourceDriftError(f"{label}.links[{position}] fields drifted")
        _require_text(item["href"], f"{label}.links[{position}].href")
        rels.add(item["rel"])
    if "self" not in rels:
        raise FHCompleteSourceDriftError(f"{label}.links must include a self link")

    return FHCompleteOrgRecord(
        fhorgid=fhorgid,
        name=_require_text(entry["fhorgname"], f"{label}.fhorgname"),
        org_type=org_type,
        status=status,
        parent_fhorgid=_require_org_id(entry["fhdeptindagencyorgid"], f"{label}.fhdeptindagencyorgid"),
        parent_name=_require_text(entry["fhagencyorgname"], f"{label}.fhagencyorgname"),
        agency_code=agency_code,
        cgac_codes=tuple(cgac_codes),
        old_fpds_office_code=old_office_code,
        null_cgac_entry_count=null_cgac_entries,
        full_parent_path_id=full_parent_path_id,
        full_parent_path_name=full_parent_path_name,
        page_index=page_index,
        source_ordinal=ordinal,
        raw=entry,
    )


def parse_complete_roster(
    page_payloads: Sequence[bytes],
    dept_witness_payload: bytes,
    sub_tier_witness_payload: bytes,
    *,
    page_pins: Sequence[FHCompletePagePin] = FH_COMPLETE_PAGES_2026_08_15,
    dept_witness_pin: FHCompletePagePin = FH_TOTAL_DEPT_WITNESS_2026_08_15,
    sub_tier_witness_pin: FHCompletePagePin = FH_TOTAL_SUBTIER_WITNESS_2026_08_15,
) -> FederalHierarchyCompleteRoster:
    """Parse the complete roster and verify it against the API's own totals."""

    if len(page_payloads) != len(page_pins):
        raise FHCompleteSourceDriftError(
            f"complete roster requires {len(page_pins)} pinned pages, got {len(page_payloads)}"
        )
    records: list[FHCompleteOrgRecord] = []
    total_reported: int | None = None
    for page_index, (payload, pin) in enumerate(zip(page_payloads, page_pins, strict=True)):
        root = _verified_page(payload, pin, location=f"FH orgs page {page_index}")
        if total_reported is None:
            total_reported = root["totalrecords"]
        for ordinal, entry in enumerate(root["orglist"]):
            records.append(_parse_record(entry, page_index=page_index, ordinal=ordinal))
    if total_reported is None or len(records) != total_reported:
        raise FHCompleteSourceDriftError(
            f"complete roster is not complete: API reports {total_reported}, parsed {len(records)}"
        )

    by_id: dict[str, FHCompleteOrgRecord] = {}
    for record in records:
        if record.fhorgid in by_id:
            raise FHCompleteSourceDriftError(f"complete roster repeats fhorgid {record.fhorgid}")
        by_id[record.fhorgid] = record
    for record in records:
        if record.org_type == "Department/Ind. Agency":
            if record.parent_fhorgid != record.fhorgid:
                raise FHCompleteSourceDriftError(
                    f"department {record.fhorgid} does not name itself as its department"
                )
        elif record.parent_fhorgid not in by_id:
            raise FHCompleteSourceDriftError(
                f"sub-tier {record.fhorgid} names department {record.parent_fhorgid} outside the roster"
            )

    department_count = sum(1 for record in records if record.org_type == "Department/Ind. Agency")
    sub_tier_count = len(records) - department_count
    dept_witness = _verified_page(dept_witness_payload, dept_witness_pin, location="FH dept totals witness")
    sub_tier_witness = _verified_page(
        sub_tier_witness_payload,
        sub_tier_witness_pin,
        location="FH sub-tier totals witness",
    )
    if dept_witness["totalrecords"] != department_count:
        raise FHCompleteSourceDriftError(
            f"department count {department_count} differs from the API's own total "
            f"{dept_witness['totalrecords']}"
        )
    if sub_tier_witness["totalrecords"] != sub_tier_count:
        raise FHCompleteSourceDriftError(
            f"sub-tier count {sub_tier_count} differs from the API's own total "
            f"{sub_tier_witness['totalrecords']}"
        )

    anomalies = {
        "multiCgacRecords": [
            {"fhorgid": record.fhorgid, "fhorgname": record.name, "cgacCodes": list(record.cgac_codes)}
            for record in records
            if len(record.cgac_codes) > 1
        ],
        "emptyAgencyCodeRecords": [
            {"fhorgid": record.fhorgid, "fhorgname": record.name}
            for record in records
            if not record.agency_code
        ],
        "nullCgacEntryRecords": [
            {"fhorgid": record.fhorgid, "fhorgname": record.name, "nullEntries": record.null_cgac_entry_count}
            for record in records
            if record.null_cgac_entry_count
        ],
        "recordsWithoutParentHistory": [
            record.fhorgid for record in records if record.full_parent_path_id is None
        ],
    }
    return FederalHierarchyCompleteRoster(
        records=tuple(records),
        total_records_reported=total_reported,
        department_count=department_count,
        sub_tier_count=sub_tier_count,
        dept_witness_total=dept_witness["totalrecords"],
        sub_tier_witness_total=sub_tier_witness["totalrecords"],
        anomalies=anomalies,
    )


__all__ = [
    "FH_COMPLETE_DOC_URL",
    "FH_COMPLETE_LICENSE_RIGHTS_STATEMENT",
    "FH_COMPLETE_ORGS_URL",
    "FH_COMPLETE_PAGES_2026_08_15",
    "FH_COMPLETE_PAGE_LIMIT",
    "FH_COMPLETE_PUBLISHER",
    "FH_COMPLETE_SOURCE_VERSION_NOTE",
    "FH_TOTAL_DEPT_WITNESS_2026_08_15",
    "FH_TOTAL_SUBTIER_WITNESS_2026_08_15",
    "FHCompleteOrgRecord",
    "FHCompletePagePin",
    "FHCompleteSourceDriftError",
    "FederalHierarchyCompleteError",
    "FederalHierarchyCompleteRoster",
    "OrgStatus",
    "OrgType",
    "parse_complete_roster",
    "sha256_digest",
]
