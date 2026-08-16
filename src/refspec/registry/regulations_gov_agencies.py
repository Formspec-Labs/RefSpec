"""Digest-pinned regulations.gov agency roster.

The regulations.gov v4 agencies endpoint publishes the agency acronyms used
as docket-ID prefixes, the publisher's agency names, and publisher-asserted
parent acronyms. The endpoint is not documented in the public OpenAPI file.
REF-038 therefore requires every use of this capture to state that caveat and
to recapture and diff the full roster before a later release replaces it.

The live request requires ``REGULATIONS_GOV_API_KEY`` in the ``X-Api-Key``
header. The source URL, pin, fixture, and parsed records never contain the key.
Importing this module performs no network access.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

REGULATIONS_GOV_AGENCIES_URL = "https://api.regulations.gov/v4/agencies"
REGULATIONS_GOV_API_KEY_ENV_VAR = "REGULATIONS_GOV_API_KEY"
REGULATIONS_GOV_API_KEY_HEADER = "X-Api-Key"
REGULATIONS_GOV_LICENSE_RIGHTS_STATEMENT = (
    "US federal public domain (17 USC 105) with no explicit CC license"
)
REGULATIONS_GOV_SOURCE_VERSION_NOTE = (
    "The publisher exposes this as a rolling, unversioned endpoint; the "
    "pinned digest detects drift."
)
REGULATIONS_GOV_RECAPTURE_OBLIGATION = (
    "Before replacing this capture, recapture the complete endpoint response "
    "with a project-owned API key and diff record membership, every reviewed "
    "field, and every parent relation against this pin."
)
REGULATIONS_GOV_EXPECTED_AGENCY_COUNT = 331
REGULATIONS_GOV_EXPECTED_PARENT_RELATION_COUNT = 160
REGULATIONS_GOV_EXPECTED_DISTINCT_PARENT_COUNT = 17

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_AGENCY_ID = re.compile(r"^[A-Z0-9-]+$")
_TOP_LEVEL_FIELDS = frozenset({"data"})
_RECORD_FIELDS = frozenset({"id", "type", "attributes", "links"})
_ATTRIBUTE_FIELDS = frozenset(
    {
        "parent",
        "participate",
        "partner",
        "postingGuidelines",
        "name",
        "agencyType",
    }
)
_LINK_FIELDS = frozenset({"self"})


class RegulationsGovAgenciesError(ValueError):
    """Base class for regulations.gov agency-roster failures."""


class RegulationsGovAgenciesSourceDriftError(RegulationsGovAgenciesError):
    """A capture no longer matches the reviewed pin or source shape."""


@dataclass(frozen=True, slots=True)
class RegulationsGovAgenciesSnapshotPin:
    """Exact identity of one credential-free stored agencies response."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    expected_record_count: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.regulations.gov"
            or parsed.path != "/v4/agencies"
        ):
            raise RegulationsGovAgenciesError(
                "source_url must be the official HTTPS regulations.gov v4 agencies endpoint"
            )
        if parsed.username is not None or parsed.password is not None:
            raise RegulationsGovAgenciesError("source_url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise RegulationsGovAgenciesError(
                "source_url must not put credentials or other values in a query or fragment"
            )
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise RegulationsGovAgenciesError(
                "expected_sha256 must be a lowercase sha256:<64 hex> digest"
            )
        if self.expected_byte_length <= 0:
            raise RegulationsGovAgenciesError("expected_byte_length must be positive")
        if self.expected_record_count <= 0:
            raise RegulationsGovAgenciesError("expected_record_count must be positive")
        if not self.retrieved_at.endswith("Z"):
            raise RegulationsGovAgenciesError("retrieved_at must be a UTC timestamp")


REGULATIONS_GOV_AGENCIES_2026_08_16 = RegulationsGovAgenciesSnapshotPin(
    source_url=REGULATIONS_GOV_AGENCIES_URL,
    retrieved_at="2026-08-16T04:53:51Z",
    expected_sha256="sha256:28ab9f5422dd27fc7906ddc696e8e7811b11056822f370bcee7ea18a28418fa2",
    expected_byte_length=91_408,
    expected_record_count=REGULATIONS_GOV_EXPECTED_AGENCY_COUNT,
)


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def verify_payload(
    payload: bytes,
    pin: RegulationsGovAgenciesSnapshotPin = REGULATIONS_GOV_AGENCIES_2026_08_16,
) -> str:
    """Refuse bytes that differ in length or digest from the reviewed capture."""

    if len(payload) != pin.expected_byte_length:
        raise RegulationsGovAgenciesSourceDriftError(
            "regulations.gov agencies byte length drift: "
            f"expected {pin.expected_byte_length}, got {len(payload)}"
        )
    actual = sha256_digest(payload)
    if actual != pin.expected_sha256:
        raise RegulationsGovAgenciesSourceDriftError(
            "regulations.gov agencies digest drift: "
            f"expected {pin.expected_sha256}, got {actual}"
        )
    return actual


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegulationsGovAgenciesSourceDriftError(f"{label} must be non-empty text")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RegulationsGovAgenciesSourceDriftError(f"{label} must be text or null")
    return value


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RegulationsGovAgenciesSourceDriftError(
                f"regulations.gov agencies capture repeats JSON field {key!r}"
            )
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class RegulationsGovAgencyRecord:
    """One agency record with every publisher field retained verbatim."""

    agency_id: str
    parent: str | None
    participate: bool
    partner: bool
    posting_guidelines: str | None
    name: str
    agency_type: str
    self_link: str
    source_ordinal: int
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RegulationsGovAgenciesRoster:
    """The complete reviewed regulations.gov agency roster."""

    records: tuple[RegulationsGovAgencyRecord, ...]
    parent_relation_count: int
    distinct_parent_count: int
    source_sha256: str
    source_byte_length: int

    def by_id(self) -> dict[str, RegulationsGovAgencyRecord]:
        return {record.agency_id: record for record in self.records}


def parse_regulations_gov_agencies(
    payload: bytes,
    *,
    pin: RegulationsGovAgenciesSnapshotPin = REGULATIONS_GOV_AGENCIES_2026_08_16,
) -> RegulationsGovAgenciesRoster:
    """Parse the complete roster and fail closed on any source-shape drift."""

    source_sha256 = verify_payload(payload, pin)
    try:
        root = json.loads(payload, object_pairs_hook=_reject_duplicate_fields)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegulationsGovAgenciesSourceDriftError(
            "regulations.gov agencies capture is not valid UTF-8 JSON"
        ) from error
    if not isinstance(root, Mapping) or set(root) != _TOP_LEVEL_FIELDS:
        fields = sorted(root) if isinstance(root, Mapping) else type(root).__name__
        raise RegulationsGovAgenciesSourceDriftError(
            f"regulations.gov agencies top-level fields drifted: {fields}"
        )
    data = root["data"]
    if not isinstance(data, list) or len(data) != pin.expected_record_count:
        count = len(data) if isinstance(data, list) else type(data).__name__
        raise RegulationsGovAgenciesSourceDriftError(
            "regulations.gov agencies record count drift: "
            f"expected {pin.expected_record_count}, got {count}"
        )

    records: list[RegulationsGovAgencyRecord] = []
    for ordinal, value in enumerate(data):
        label = f"data[{ordinal}]"
        if not isinstance(value, Mapping) or set(value) != _RECORD_FIELDS:
            fields = sorted(value) if isinstance(value, Mapping) else type(value).__name__
            raise RegulationsGovAgenciesSourceDriftError(
                f"{label} fields drifted from the reviewed shape: {fields}"
            )
        agency_id = _required_text(value["id"], f"{label}.id")
        if _AGENCY_ID.fullmatch(agency_id) is None:
            raise RegulationsGovAgenciesSourceDriftError(
                f"{label}.id is not a reviewed docket-prefix shape: {agency_id!r}"
            )
        if value["type"] != "agencies":
            raise RegulationsGovAgenciesSourceDriftError(
                f"{label}.type must remain 'agencies'"
            )
        attributes = value["attributes"]
        if not isinstance(attributes, Mapping) or set(attributes) != _ATTRIBUTE_FIELDS:
            fields = sorted(attributes) if isinstance(attributes, Mapping) else type(attributes).__name__
            raise RegulationsGovAgenciesSourceDriftError(
                f"{label}.attributes fields drifted from the reviewed shape: {fields}"
            )
        links = value["links"]
        if not isinstance(links, Mapping) or set(links) != _LINK_FIELDS:
            fields = sorted(links) if isinstance(links, Mapping) else type(links).__name__
            raise RegulationsGovAgenciesSourceDriftError(
                f"{label}.links fields drifted from the reviewed shape: {fields}"
            )
        parent = attributes["parent"]
        if parent is not None and (
            not isinstance(parent, str) or _AGENCY_ID.fullmatch(parent) is None
        ):
            raise RegulationsGovAgenciesSourceDriftError(
                f"{label}.attributes.parent must be a docket-prefix id or null"
            )
        for field_name in ("participate", "partner"):
            if not isinstance(attributes[field_name], bool):
                raise RegulationsGovAgenciesSourceDriftError(
                    f"{label}.attributes.{field_name} must be boolean"
                )
        agency_type = _required_text(attributes["agencyType"], f"{label}.attributes.agencyType")
        if agency_type != "Federal":
            raise RegulationsGovAgenciesSourceDriftError(
                f"{label}.attributes.agencyType must remain 'Federal'"
            )
        self_link = _required_text(links["self"], f"{label}.links.self")
        expected_self_link = f"{REGULATIONS_GOV_AGENCIES_URL}/{agency_id}"
        if self_link != expected_self_link:
            raise RegulationsGovAgenciesSourceDriftError(
                f"{label}.links.self drifted: expected {expected_self_link!r}"
            )
        records.append(
            RegulationsGovAgencyRecord(
                agency_id=agency_id,
                parent=parent,
                participate=attributes["participate"],
                partner=attributes["partner"],
                posting_guidelines=_optional_text(
                    attributes["postingGuidelines"],
                    f"{label}.attributes.postingGuidelines",
                ),
                name=_required_text(attributes["name"], f"{label}.attributes.name"),
                agency_type=agency_type,
                self_link=self_link,
                source_ordinal=ordinal,
                raw=value,
            )
        )

    by_id = {record.agency_id: record for record in records}
    if len(by_id) != len(records):
        raise RegulationsGovAgenciesSourceDriftError(
            "regulations.gov agencies roster repeats a publisher id"
        )
    for record in records:
        if record.parent is not None and record.parent not in by_id:
            raise RegulationsGovAgenciesSourceDriftError(
                f"agency {record.agency_id} names parent {record.parent} outside the roster"
            )
    parent_relation_count = sum(record.parent is not None for record in records)
    if parent_relation_count != REGULATIONS_GOV_EXPECTED_PARENT_RELATION_COUNT:
        raise RegulationsGovAgenciesSourceDriftError(
            "regulations.gov agencies parent-relation count drift: "
            f"expected {REGULATIONS_GOV_EXPECTED_PARENT_RELATION_COUNT}, "
            f"got {parent_relation_count}"
        )
    distinct_parent_count = len({record.parent for record in records if record.parent is not None})
    if distinct_parent_count != REGULATIONS_GOV_EXPECTED_DISTINCT_PARENT_COUNT:
        raise RegulationsGovAgenciesSourceDriftError(
            "regulations.gov agencies distinct-parent count drift: "
            f"expected {REGULATIONS_GOV_EXPECTED_DISTINCT_PARENT_COUNT}, "
            f"got {distinct_parent_count}"
        )
    return RegulationsGovAgenciesRoster(
        records=tuple(records),
        parent_relation_count=parent_relation_count,
        distinct_parent_count=distinct_parent_count,
        source_sha256=source_sha256,
        source_byte_length=len(payload),
    )


__all__ = [
    "REGULATIONS_GOV_AGENCIES_2026_08_16",
    "REGULATIONS_GOV_AGENCIES_URL",
    "REGULATIONS_GOV_API_KEY_ENV_VAR",
    "REGULATIONS_GOV_API_KEY_HEADER",
    "REGULATIONS_GOV_EXPECTED_AGENCY_COUNT",
    "REGULATIONS_GOV_EXPECTED_DISTINCT_PARENT_COUNT",
    "REGULATIONS_GOV_EXPECTED_PARENT_RELATION_COUNT",
    "REGULATIONS_GOV_LICENSE_RIGHTS_STATEMENT",
    "REGULATIONS_GOV_RECAPTURE_OBLIGATION",
    "REGULATIONS_GOV_SOURCE_VERSION_NOTE",
    "RegulationsGovAgenciesError",
    "RegulationsGovAgenciesRoster",
    "RegulationsGovAgenciesSnapshotPin",
    "RegulationsGovAgenciesSourceDriftError",
    "RegulationsGovAgencyRecord",
    "parse_regulations_gov_agencies",
    "sha256_digest",
    "verify_payload",
]
