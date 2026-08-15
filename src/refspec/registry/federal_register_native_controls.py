"""Documented Federal Register native controls and the agencies roster.

REF-032 removed the observed Federal Register inventories: four set-distinct
scans over a SpicyRegs Parquet snapshot that had stood in for the publisher's
own lists. This module carries the documented successors, captured from the
publisher directly:

* ``https://www.federalregister.gov/api/v1/documentation.json`` is the
  machine-readable OpenAPI 3.0.0 description that the publisher's own
  developer-documentation page renders. Its ``components.schemas.DocumentType``
  enumeration states the documented document types (``RULE``, ``PRORULE``,
  ``NOTICE``, ``PRESDOCU``), its ``PresidentialDocumentType`` enumeration
  states the documented presidential-document subtypes, and its ``Agency``
  enumeration states the documented agency slugs.
* ``https://www.federalregister.gov/api/v1/documents/facets/type`` carries the
  publisher's display names for the four document types (``Rule``,
  ``Proposed Rule``, ``Notice``, ``Presidential Document``). Its per-type
  document counts are corpus counts at capture time and are retained verbatim
  as capture metadata, never as members.
* ``https://www.federalregister.gov/api/v1/agencies`` is the publisher's
  agencies roster: every agency record with its numeric ``id``, ``slug``,
  names, description, URLs, and publisher-asserted ``parent_id`` relations.

Importing this module performs no network access. Callers provide exact
captured publisher bytes; every parse verifies them against the pinned digest
and byte length and refuses drifted bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

FR_PUBLISHER = "Office of the Federal Register, National Archives and Records Administration"
FR_API_DOCUMENTATION_URL = "https://www.federalregister.gov/api/v1/documentation.json"
FR_DOCUMENT_TYPE_FACETS_URL = "https://www.federalregister.gov/api/v1/documents/facets/type"
FR_AGENCIES_URL = "https://www.federalregister.gov/api/v1/agencies"
FR_DEVELOPER_DOCUMENTATION_PAGE_URL = "https://www.federalregister.gov/developers/documentation/api/v1"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SLUG = re.compile(r"^[a-z0-9-]+$")
_TYPE_CODE = re.compile(r"^[A-Z]+$")
_SUBTYPE_CODE = re.compile(r"^[a-z_]+$")
_FR_HOSTS = frozenset({"federalregister.gov", "www.federalregister.gov"})

# The thirteen publisher fields observed on every one of the 472 agency
# records in the pinned capture. A record with a different field set is drift.
_AGENCY_FIELDS = frozenset(
    {
        "agency_url",
        "child_ids",
        "child_slugs",
        "description",
        "id",
        "json_url",
        "logo",
        "name",
        "parent_id",
        "recent_articles_url",
        "short_name",
        "slug",
        "url",
    }
)


class FederalRegisterNativeControlsError(ValueError):
    """Base class for documented Federal Register control failures."""


class FRSourceDriftError(FederalRegisterNativeControlsError):
    """A publisher capture no longer matches the reviewed structure or pin."""


@dataclass(frozen=True, slots=True)
class FRSnapshotPin:
    """Exact identity of one captured Federal Register API response."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname not in _FR_HOSTS:
            raise FederalRegisterNativeControlsError("source_url must be an official HTTPS federalregister.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise FederalRegisterNativeControlsError("source_url must not contain credentials")
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise FederalRegisterNativeControlsError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise FederalRegisterNativeControlsError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise FederalRegisterNativeControlsError("retrieved_at must not be empty")


FR_API_DOCUMENTATION_2026_08_15 = FRSnapshotPin(
    source_url=FR_API_DOCUMENTATION_URL,
    retrieved_at="2026-08-15T07:50:47Z",
    expected_sha256="sha256:9190df715f0227e62acb57ff924635fc7115732064a5d2c1fb15a57d80879a42",
    expected_byte_length=229_776,
)
FR_DOCUMENT_TYPE_FACETS_2026_08_15 = FRSnapshotPin(
    source_url=FR_DOCUMENT_TYPE_FACETS_URL,
    retrieved_at="2026-08-15T07:50:47Z",
    expected_sha256="sha256:fb6ab236d52938e112fa5ff5f36f6b9a6a7f34a4f8009bb7cc4ad9f507ee53f2",
    expected_byte_length=187,
)
FR_AGENCIES_2026_08_15 = FRSnapshotPin(
    source_url=FR_AGENCIES_URL,
    retrieved_at="2026-08-15T07:50:47Z",
    expected_sha256="sha256:70dd0e8fa373a22d5c9577ac1f70ea736542f0e564f816c3caf28014bd05a92b",
    expected_byte_length=694_024,
)


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def verify_payload(payload: bytes, pin: FRSnapshotPin, *, location: str) -> str:
    """Verify exact capture bytes against one pin and return the digest."""

    if len(payload) != pin.expected_byte_length:
        raise FRSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {len(payload)}"
        )
    actual = sha256_digest(payload)
    if actual != pin.expected_sha256:
        raise FRSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual}")
    return actual


def _json_root(payload: bytes, label: str) -> Any:
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FRSourceDriftError(f"{label} is not valid UTF-8 JSON") from error


def _schema_enum(openapi_root: Mapping[str, Any], schema_name: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    components = openapi_root.get("components")
    if not isinstance(components, Mapping) or not isinstance(components.get("schemas"), Mapping):
        raise FRSourceDriftError("FR API description has no components.schemas object")
    schema = components["schemas"].get(schema_name)
    if not isinstance(schema, Mapping) or not isinstance(schema.get("items"), Mapping):
        raise FRSourceDriftError(f"FR API description schema {schema_name} is not the reviewed array schema")
    enum = schema["items"].get("enum")
    if not isinstance(enum, list) or not enum:
        raise FRSourceDriftError(f"FR API description schema {schema_name} declares no enum")
    values: list[str] = []
    for ordinal, value in enumerate(enum):
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise FRSourceDriftError(f"{schema_name} enum value {ordinal} has an unsupported shape: {value!r}")
        values.append(value)
    if len(set(values)) != len(values):
        raise FRSourceDriftError(f"{schema_name} enum repeats a value")
    return tuple(values)


@dataclass(frozen=True, slots=True)
class FRDocumentedDocumentType:
    """One documented document type with the publisher's display name."""

    code: str
    display_name: str
    facet_document_count_at_capture: int
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class FRDocumentedDocumentTypes:
    """The documented ``DocumentType`` enumeration plus display names."""

    types: tuple[FRDocumentedDocumentType, ...]
    openapi_version: str
    publisher_info_version: str
    documentation_sha256: str
    facets_sha256: str

    def by_code(self) -> dict[str, FRDocumentedDocumentType]:
        return {item.code: item for item in self.types}


def parse_documented_document_types(
    documentation_payload: bytes,
    facets_payload: bytes,
    *,
    documentation_pin: FRSnapshotPin = FR_API_DOCUMENTATION_2026_08_15,
    facets_pin: FRSnapshotPin = FR_DOCUMENT_TYPE_FACETS_2026_08_15,
) -> FRDocumentedDocumentTypes:
    """Parse the documented document-type enumeration from exact bytes."""

    documentation_sha256 = verify_payload(documentation_payload, documentation_pin, location="FR API description")
    facets_sha256 = verify_payload(facets_payload, facets_pin, location="FR type facets response")
    root = _json_root(documentation_payload, "FR API description")
    if not isinstance(root, Mapping):
        raise FRSourceDriftError("FR API description root must be an object")
    openapi_version = root.get("openapi")
    if not isinstance(openapi_version, str) or not openapi_version:
        raise FRSourceDriftError("FR API description declares no openapi version")
    info = root.get("info")
    if not isinstance(info, Mapping) or not isinstance(info.get("version"), str):
        raise FRSourceDriftError("FR API description info block drifted")
    codes = _schema_enum(root, "DocumentType", _TYPE_CODE)

    facets = _json_root(facets_payload, "FR type facets response")
    if not isinstance(facets, Mapping):
        raise FRSourceDriftError("FR type facets root must be an object")
    if set(facets) != set(codes):
        raise FRSourceDriftError(
            "FR type facets keys differ from the documented DocumentType enum: "
            f"facets={sorted(facets)}, enum={sorted(codes)}"
        )
    types: list[FRDocumentedDocumentType] = []
    for ordinal, code in enumerate(codes, start=1):
        facet = facets[code]
        if not isinstance(facet, Mapping) or set(facet) != {"count", "name"}:
            raise FRSourceDriftError(f"FR type facet {code} fields drifted")
        name = facet["name"]
        count = facet["count"]
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise FRSourceDriftError(f"FR type facet {code} has a malformed display name")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise FRSourceDriftError(f"FR type facet {code} has a malformed document count")
        types.append(
            FRDocumentedDocumentType(
                code=code,
                display_name=name,
                facet_document_count_at_capture=count,
                source_ordinal=ordinal,
            )
        )
    if len({item.display_name for item in types}) != len(types):
        raise FRSourceDriftError("FR type facets repeat a display name")
    return FRDocumentedDocumentTypes(
        types=tuple(types),
        openapi_version=openapi_version,
        publisher_info_version=info["version"],
        documentation_sha256=documentation_sha256,
        facets_sha256=facets_sha256,
    )


def parse_documented_presidential_document_types(
    documentation_payload: bytes,
    *,
    documentation_pin: FRSnapshotPin = FR_API_DOCUMENTATION_2026_08_15,
) -> tuple[str, ...]:
    """Parse the documented ``PresidentialDocumentType`` enumeration."""

    verify_payload(documentation_payload, documentation_pin, location="FR API description")
    root = _json_root(documentation_payload, "FR API description")
    if not isinstance(root, Mapping):
        raise FRSourceDriftError("FR API description root must be an object")
    return _schema_enum(root, "PresidentialDocumentType", _SUBTYPE_CODE)


@dataclass(frozen=True, slots=True)
class FRAgencyRecord:
    """One exact publisher agency record from the agencies roster."""

    agency_id: int
    slug: str
    name: str
    short_name: str | None
    description: str | None
    url: str
    json_url: str
    agency_url: str | None
    parent_id: int | None
    child_ids: tuple[int, ...]
    child_slugs: tuple[str, ...]
    logo_present: bool
    source_ordinal: int
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class FRAgenciesRoster:
    """The parsed, digest-pinned complete agencies roster."""

    records: tuple[FRAgencyRecord, ...]
    parent_relation_count: int
    source_sha256: str
    anomalies: Mapping[str, Any]

    def by_id(self) -> dict[int, FRAgencyRecord]:
        return {record.agency_id: record for record in self.records}

    def by_slug(self) -> dict[str, FRAgencyRecord]:
        return {record.slug: record for record in self.records}


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FRSourceDriftError(f"{label} must be text or null")
    return value


def _official_page_url(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise FRSourceDriftError(f"{label} must be non-empty text")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in _FR_HOSTS:
        raise FRSourceDriftError(f"{label} must remain on the official HTTPS federalregister.gov host")
    return value


def parse_agencies_roster(
    agencies_payload: bytes,
    *,
    agencies_pin: FRSnapshotPin = FR_AGENCIES_2026_08_15,
) -> FRAgenciesRoster:
    """Parse the complete publisher agencies roster from exact bytes."""

    source_sha256 = verify_payload(agencies_payload, agencies_pin, location="FR agencies response")
    root = _json_root(agencies_payload, "FR agencies response")
    if not isinstance(root, list) or not root:
        raise FRSourceDriftError("FR agencies response must be a non-empty array")

    records: list[FRAgencyRecord] = []
    for ordinal, entry in enumerate(root, start=1):
        label = f"agencies[{ordinal - 1}]"
        if not isinstance(entry, Mapping):
            raise FRSourceDriftError(f"{label} must be an object")
        if set(entry) != _AGENCY_FIELDS:
            raise FRSourceDriftError(f"{label} fields drifted from the reviewed shape: {sorted(entry)}")
        agency_id = entry["id"]
        if not isinstance(agency_id, int) or isinstance(agency_id, bool) or agency_id <= 0:
            raise FRSourceDriftError(f"{label}.id must be a positive integer")
        slug = entry["slug"]
        if not isinstance(slug, str) or _SLUG.fullmatch(slug) is None:
            raise FRSourceDriftError(f"{label}.slug has an unsupported shape: {slug!r}")
        name = entry["name"]
        if not isinstance(name, str) or not name.strip():
            raise FRSourceDriftError(f"{label}.name must be non-empty text")
        parent_id = entry["parent_id"]
        if parent_id is not None and (not isinstance(parent_id, int) or isinstance(parent_id, bool)):
            raise FRSourceDriftError(f"{label}.parent_id must be an integer or null")
        child_ids = entry["child_ids"]
        child_slugs = entry["child_slugs"]
        if not isinstance(child_ids, list) or not all(
            isinstance(item, int) and not isinstance(item, bool) for item in child_ids
        ):
            raise FRSourceDriftError(f"{label}.child_ids must be an array of integers")
        if not isinstance(child_slugs, list) or not all(isinstance(item, str) for item in child_slugs):
            raise FRSourceDriftError(f"{label}.child_slugs must be an array of text slugs")
        records.append(
            FRAgencyRecord(
                agency_id=agency_id,
                slug=slug,
                name=name,
                short_name=_optional_text(entry["short_name"], f"{label}.short_name"),
                description=_optional_text(entry["description"], f"{label}.description"),
                url=_official_page_url(entry["url"], f"{label}.url"),
                json_url=_official_page_url(entry["json_url"], f"{label}.json_url"),
                agency_url=_optional_text(entry["agency_url"], f"{label}.agency_url"),
                parent_id=parent_id,
                child_ids=tuple(child_ids),
                child_slugs=tuple(child_slugs),
                logo_present=entry["logo"] is not None,
                source_ordinal=ordinal,
                raw=entry,
            )
        )

    by_id = {record.agency_id: record for record in records}
    if len(by_id) != len(records):
        raise FRSourceDriftError("FR agencies roster repeats a publisher id")
    if len({record.slug for record in records}) != len(records):
        raise FRSourceDriftError("FR agencies roster repeats a publisher slug")

    parent_relation_count = 0
    for record in records:
        if record.parent_id is not None:
            if record.parent_id not in by_id:
                raise FRSourceDriftError(
                    f"agency {record.agency_id} names parent {record.parent_id} outside the roster"
                )
            parent_relation_count += 1
        for child_id in record.child_ids:
            if child_id not in by_id:
                raise FRSourceDriftError(f"agency {record.agency_id} names child {child_id} outside the roster")
            if by_id[child_id].parent_id != record.agency_id:
                raise FRSourceDriftError(
                    f"agency {record.agency_id} child {child_id} does not name it back as parent"
                )

    anomalies = {
        "nullAgencyUrlCount": sum(1 for record in records if record.agency_url is None),
        "emptyAgencyUrlCount": sum(1 for record in records if record.agency_url == ""),
        "nullShortNameCount": sum(1 for record in records if record.short_name is None),
        "nullDescriptionCount": sum(1 for record in records if record.description is None),
        "nullLogoCount": sum(1 for record in records if not record.logo_present),
    }
    return FRAgenciesRoster(
        records=tuple(records),
        parent_relation_count=parent_relation_count,
        source_sha256=source_sha256,
        anomalies=anomalies,
    )


def crosscheck_documented_agency_slugs(
    documentation_payload: bytes,
    roster: FRAgenciesRoster,
    *,
    documentation_pin: FRSnapshotPin = FR_API_DOCUMENTATION_2026_08_15,
) -> int:
    """Require the documented ``Agency`` slug enum to equal the roster's slugs."""

    verify_payload(documentation_payload, documentation_pin, location="FR API description")
    root = _json_root(documentation_payload, "FR API description")
    if not isinstance(root, Mapping):
        raise FRSourceDriftError("FR API description root must be an object")
    documented = _schema_enum(root, "Agency", _SLUG)
    roster_slugs = {record.slug for record in roster.records}
    if set(documented) != roster_slugs:
        missing = sorted(set(documented) - roster_slugs)
        extra = sorted(roster_slugs - set(documented))
        raise FRSourceDriftError(
            f"documented Agency enum differs from the agencies roster; missing={missing[:5]!r}, extra={extra[:5]!r}"
        )
    return len(documented)


__all__ = [
    "FR_AGENCIES_2026_08_15",
    "FR_AGENCIES_URL",
    "FR_API_DOCUMENTATION_2026_08_15",
    "FR_API_DOCUMENTATION_URL",
    "FR_DEVELOPER_DOCUMENTATION_PAGE_URL",
    "FR_DOCUMENT_TYPE_FACETS_2026_08_15",
    "FR_DOCUMENT_TYPE_FACETS_URL",
    "FR_PUBLISHER",
    "FRAgenciesRoster",
    "FRAgencyRecord",
    "FRDocumentedDocumentType",
    "FRDocumentedDocumentTypes",
    "FRSnapshotPin",
    "FRSourceDriftError",
    "FederalRegisterNativeControlsError",
    "crosscheck_documented_agency_slugs",
    "parse_agencies_roster",
    "parse_documented_document_types",
    "parse_documented_presidential_document_types",
    "sha256_digest",
    "verify_payload",
]
