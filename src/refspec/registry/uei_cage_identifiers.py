"""SAM.gov Unique Entity ID (UEI) and DLA CAGE code identifier authorities.

The catalog entry for this source is scoped to award-entity and facility
identifier *schemes*, not entity data: capture identifier syntax, validity
vocabulary, and registration/facility/parent distinctions, and record the
public/controlled access distinction. It is explicit that no bulk entity
data may be ingested. This module therefore never queries a live SAM.gov or
DLA CAGE registry and never accepts more than ``MAX_SAMPLE_SIZE`` records of
either kind -- that ceiling is enforced at runtime, not only documented.

Every UEI and CAGE value handled here still carries a real
``ControlledIdentifier`` naming its publisher authority; this module mints
no identifiers of its own. The small identifier sample this module can
build and round-trip is always an illustrative, documented-format example
(``sampleProvenance: "illustrativeFormatExample"``) rather than a capture of
real registrants -- this project holds no license or authorization to
redistribute SAM.gov or DLA entity records, bulk or otherwise.

Two source facts are worth recording plainly. First, the SAM.gov
entity-registration page (https://sam.gov/entity-registration) is served
with ``Cache-Control: s-maxage=300`` from a shared CDN edge, so it is a
legitimate byte-stable document; this module pins its exact SHA-256 as
``SAM_UEI_DOCUMENTATION_PIN``. Second, the DLA CAGE documentation URL given
for this source (dla.mil's "cage-code-commercial-and-government-entity-code"
article) returned HTTP 403 ("Access Denied") when fetched directly, and
DLA's reachable operational CAGE site (cage.dla.mil) serves
``Cache-Control: private, no-store`` and embeds a fresh per-request
anti-forgery token in every response body -- no fetch of it can ever be
pinned as a stable byte capture. The documented CAGE format below is
therefore recorded as an informational fact, citing ``DLA_CAGE_AUTHORITY_URI``,
without a reproducible document pin.

Acquisition of the one pinnable authority document accepts a local exact
capture or an injected fetcher. Importing this module never opens a network
connection.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from refspec.registry.controlled_identifier import (
    ControlledIdentifier,
    ControlledIdentifierError,
    validate_identifier_date,
)
from refspec.storage import canonical_json

SAM_UEI_AUTHORITY_URI = "https://sam.gov/entity-registration"
DLA_CAGE_AUTHORITY_URI = (
    "https://www.dla.mil/Working-With-DLA/Applications/Details/Article/2920893/"
    "cage-code-commercial-and-government-entity-code/"
)
SAM_UEI_KIND = "samUniqueEntityId"
DLA_CAGE_KIND = "dlaCageCode"

# Hard ceiling enforced at runtime by UeiCageAuthoritySample and
# parse_capture. This module captures identifier-shape samples only; it must
# never become a path for bulk entity data.
MAX_SAMPLE_SIZE = 25

# Per SAM.gov's published Unique Entity ID format: exactly 12 uppercase
# alphanumeric characters, never containing the letters I or O (reserved to
# avoid confusion with the digits 1 and 0).
_UEI_PATTERN = re.compile(r"^[A-HJ-NP-Z0-9]{12}$")
# Per DLA's published CAGE code format: exactly 5 uppercase alphanumeric
# characters, never containing the letters I or O, for the same reason.
_CAGE_PATTERN = re.compile(r"^[A-HJ-NP-Z0-9]{5}$")

# SAM.gov registration and DLA CAGE status vocabularies are recorded from
# publisher documentation. An unrecognized status value is refused rather
# than silently accepted, so undocumented source drift fails loudly instead
# of being coerced into a known bucket.
_REGISTRATION_STATUSES = frozenset({"active", "inactive"})
_CAGE_STATUSES = frozenset({"active", "inactive"})
# SAM.gov entities may be excluded from public search; DLA CAGE and SAM.gov
# records may also carry Controlled Unclassified Information boundaries.
# Public access to one field never authorizes protected entity data.
_ACCESS_CLASSIFICATIONS = frozenset(
    {"public", "excludedFromPublicSearch", "controlledUnclassifiedInformation"}
)

SAMPLE_CAPTURE_FORMAT = "urn:ref:registry:uei-cage-identifier-authority-sample:v1"
PARSER_VERSION = "uei-cage-identifier-authority-sample-v1"
_SAMPLE_PROVENANCE = "illustrativeFormatExample"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class UeiCageIdentifierError(ValueError):
    """A UEI/CAGE identifier, status, or sample capture could not be preserved."""


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UeiCageIdentifierError(f"{label} must be non-empty text")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise UeiCageIdentifierError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise UeiCageIdentifierError(
            f"{label} fields changed; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def validate_uei_syntax(value: str) -> str:
    """Refuse anything that is not a well-formed 12-character SAM.gov UEI."""

    if not isinstance(value, str) or _UEI_PATTERN.fullmatch(value) is None:
        raise UeiCageIdentifierError(
            f"{value!r} is not a well-formed SAM.gov UEI: expected 12 uppercase "
            "alphanumeric characters excluding I and O"
        )
    return value


def validate_cage_syntax(value: str) -> str:
    """Refuse anything that is not a well-formed 5-character DLA CAGE code."""

    if not isinstance(value, str) or _CAGE_PATTERN.fullmatch(value) is None:
        raise UeiCageIdentifierError(
            f"{value!r} is not a well-formed DLA CAGE code: expected 5 uppercase "
            "alphanumeric characters excluding I and O"
        )
    return value


@dataclass(frozen=True, slots=True)
class UeiRecord:
    """One SAM.gov registrant identifier plus its documented registration facts.

    A UEI identifies a *registrant* entity, not a physical facility.
    Corporate ownership is tracked separately through SAM.gov's documented
    immediate-parent and highest-level-owner UEI references.
    """

    identifier: ControlledIdentifier
    legal_business_name: str
    registration_status: str
    access_classification: str
    immediate_parent_uei: str | None = None
    highest_level_owner_uei: str | None = None

    def __post_init__(self) -> None:
        if self.identifier.kind != SAM_UEI_KIND:
            raise UeiCageIdentifierError(f"UeiRecord.identifier.kind must be {SAM_UEI_KIND!r}")
        validate_uei_syntax(self.identifier.value)
        _require_text(self.legal_business_name, "UeiRecord.legal_business_name")
        if self.registration_status not in _REGISTRATION_STATUSES:
            raise UeiCageIdentifierError(
                f"UeiRecord.registration_status is unsupported: {self.registration_status!r}"
            )
        if self.access_classification not in _ACCESS_CLASSIFICATIONS:
            raise UeiCageIdentifierError(
                f"UeiRecord.access_classification is unsupported: {self.access_classification!r}"
            )
        for field_name, parent in (
            ("immediate_parent_uei", self.immediate_parent_uei),
            ("highest_level_owner_uei", self.highest_level_owner_uei),
        ):
            if parent is not None:
                try:
                    validate_uei_syntax(parent)
                except UeiCageIdentifierError as error:
                    raise UeiCageIdentifierError(f"UeiRecord.{field_name}: {error}") from error

    def native_payload(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier.as_dict(),
            "legalBusinessName": self.legal_business_name,
            "registrationStatus": self.registration_status,
            "accessClassification": self.access_classification,
            "immediateParentUei": self.immediate_parent_uei,
            "highestLevelOwnerUei": self.highest_level_owner_uei,
        }


@dataclass(frozen=True, slots=True)
class CageRecord:
    """One DLA CAGE facility/location identifier plus its documented facts.

    A CAGE code identifies a specific commercial or government facility, not
    a registrant as a whole; ``associated_uei`` records which SAM.gov
    registrant, if any, this facility is filed under.
    """

    identifier: ControlledIdentifier
    facility_name: str
    cage_status: str
    access_classification: str
    associated_uei: str | None = None

    def __post_init__(self) -> None:
        if self.identifier.kind != DLA_CAGE_KIND:
            raise UeiCageIdentifierError(f"CageRecord.identifier.kind must be {DLA_CAGE_KIND!r}")
        validate_cage_syntax(self.identifier.value)
        _require_text(self.facility_name, "CageRecord.facility_name")
        if self.cage_status not in _CAGE_STATUSES:
            raise UeiCageIdentifierError(f"CageRecord.cage_status is unsupported: {self.cage_status!r}")
        if self.access_classification not in _ACCESS_CLASSIFICATIONS:
            raise UeiCageIdentifierError(
                f"CageRecord.access_classification is unsupported: {self.access_classification!r}"
            )
        if self.associated_uei is not None:
            try:
                validate_uei_syntax(self.associated_uei)
            except UeiCageIdentifierError as error:
                raise UeiCageIdentifierError(f"CageRecord.associated_uei: {error}") from error

    def native_payload(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier.as_dict(),
            "facilityName": self.facility_name,
            "cageStatus": self.cage_status,
            "accessClassification": self.access_classification,
            "associatedUei": self.associated_uei,
        }


@dataclass(frozen=True, slots=True)
class UeiCageAuthoritySample:
    """A small, non-bulk illustrative sample of both identifier schemes.

    This is never a registry export: ``MAX_SAMPLE_SIZE`` caps each side, and
    every record is a documented-format example, not a live SAM.gov or DLA
    lookup (see ``_SAMPLE_PROVENANCE``).
    """

    captured_at: str
    ueis: tuple[UeiRecord, ...]
    cages: tuple[CageRecord, ...]

    def __post_init__(self) -> None:
        validate_identifier_date(self.captured_at, "UeiCageAuthoritySample.captured_at")
        for label, records in (("ueis", self.ueis), ("cages", self.cages)):
            if len(records) > MAX_SAMPLE_SIZE:
                raise UeiCageIdentifierError(
                    f"UeiCageAuthoritySample.{label} exceeds MAX_SAMPLE_SIZE={MAX_SAMPLE_SIZE}; "
                    "this module captures identifier-shape samples only, never bulk entity data"
                )
            values = [record.identifier.value for record in records]
            if len(values) != len(set(values)):
                raise UeiCageIdentifierError(f"UeiCageAuthoritySample.{label} repeats an identifier value")

    def native_payload(self) -> dict[str, Any]:
        return {
            "format": SAMPLE_CAPTURE_FORMAT,
            "parserVersion": PARSER_VERSION,
            "capturedAt": self.captured_at,
            "sampleProvenance": _SAMPLE_PROVENANCE,
            "maxSampleSize": MAX_SAMPLE_SIZE,
            "ueis": [record.native_payload() for record in self.ueis],
            "cages": [record.native_payload() for record in self.cages],
        }

    @property
    def digest(self) -> str:
        return _sha256(canonical_json(self.native_payload()).encode("utf-8"))


def render_capture(sample: UeiCageAuthoritySample) -> bytes:
    """Render one stable, reviewable capture document."""

    return (
        json.dumps(
            sample.native_payload(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _parse_identifier(value: object, label: str) -> ControlledIdentifier:
    if not isinstance(value, Mapping):
        raise UeiCageIdentifierError(f"{label} must be an object")
    _exact_keys(
        value,
        {"value", "kind", "authorityUri", "sourceUri", "observedAt", "effectiveAt", "sourceDigest"},
        label,
    )
    try:
        return ControlledIdentifier(
            value=value["value"],
            kind=value["kind"],
            authority_uri=value["authorityUri"],
            source_uri=value["sourceUri"],
            observed_at=value["observedAt"],
            effective_at=value["effectiveAt"],
            source_digest=value["sourceDigest"],
        )
    except ControlledIdentifierError as error:
        raise UeiCageIdentifierError(f"{label}: {error}") from error


def _parse_uei_record(value: object, index: int) -> UeiRecord:
    label = f"ueis[{index}]"
    if not isinstance(value, Mapping):
        raise UeiCageIdentifierError(f"{label} must be an object")
    _exact_keys(
        value,
        {
            "identifier",
            "legalBusinessName",
            "registrationStatus",
            "accessClassification",
            "immediateParentUei",
            "highestLevelOwnerUei",
        },
        label,
    )
    return UeiRecord(
        identifier=_parse_identifier(value["identifier"], f"{label}.identifier"),
        legal_business_name=value["legalBusinessName"],
        registration_status=value["registrationStatus"],
        access_classification=value["accessClassification"],
        immediate_parent_uei=value["immediateParentUei"],
        highest_level_owner_uei=value["highestLevelOwnerUei"],
    )


def _parse_cage_record(value: object, index: int) -> CageRecord:
    label = f"cages[{index}]"
    if not isinstance(value, Mapping):
        raise UeiCageIdentifierError(f"{label} must be an object")
    _exact_keys(
        value,
        {"identifier", "facilityName", "cageStatus", "accessClassification", "associatedUei"},
        label,
    )
    return CageRecord(
        identifier=_parse_identifier(value["identifier"], f"{label}.identifier"),
        facility_name=value["facilityName"],
        cage_status=value["cageStatus"],
        access_classification=value["accessClassification"],
        associated_uei=value["associatedUei"],
    )


def parse_capture(payload: bytes) -> UeiCageAuthoritySample:
    """Parse and strictly verify one exact UEI/CAGE sample capture document."""

    if not isinstance(payload, bytes) or not payload:
        raise UeiCageIdentifierError("capture payload must be non-empty bytes")
    try:
        value = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UeiCageIdentifierError("capture payload must be valid UTF-8 JSON") from error
    if not isinstance(value, Mapping):
        raise UeiCageIdentifierError("capture payload must contain one object")
    _exact_keys(
        value,
        {"format", "parserVersion", "capturedAt", "sampleProvenance", "maxSampleSize", "ueis", "cages"},
        "capture",
    )
    if value["format"] != SAMPLE_CAPTURE_FORMAT:
        raise UeiCageIdentifierError("unknown capture format")
    if value["parserVersion"] != PARSER_VERSION:
        raise UeiCageIdentifierError("unknown capture parser version")
    if value["sampleProvenance"] != _SAMPLE_PROVENANCE:
        raise UeiCageIdentifierError(
            "capture sampleProvenance must be illustrativeFormatExample; "
            "this module never packages live registry data"
        )
    if value["maxSampleSize"] != MAX_SAMPLE_SIZE:
        raise UeiCageIdentifierError("capture maxSampleSize does not match this module's MAX_SAMPLE_SIZE ceiling")
    ueis_value = value["ueis"]
    cages_value = value["cages"]
    if not isinstance(ueis_value, list) or not isinstance(cages_value, list):
        raise UeiCageIdentifierError("capture ueis and cages must be arrays")
    if len(ueis_value) > MAX_SAMPLE_SIZE or len(cages_value) > MAX_SAMPLE_SIZE:
        raise UeiCageIdentifierError(
            f"capture exceeds MAX_SAMPLE_SIZE={MAX_SAMPLE_SIZE}; refusing to parse bulk entity data"
        )
    ueis = tuple(_parse_uei_record(item, index) for index, item in enumerate(ueis_value))
    cages = tuple(_parse_cage_record(item, index) for index, item in enumerate(cages_value))
    return UeiCageAuthoritySample(captured_at=value["capturedAt"], ueis=ueis, cages=cages)


@dataclass(frozen=True, slots=True)
class AuthorityDocumentPin:
    """Exact identity of one publisher-hosted identifier-authority document."""

    url: str
    sha256: str
    byte_length: int
    retrieved_at: str
    content_type: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise UeiCageIdentifierError("AuthorityDocumentPin.url must be an absolute HTTPS URL")
        if _SHA256.fullmatch(self.sha256) is None:
            raise UeiCageIdentifierError("AuthorityDocumentPin.sha256 must be a lowercase sha256:<64 hex> digest")
        if self.byte_length <= 0:
            raise UeiCageIdentifierError("AuthorityDocumentPin.byte_length must be positive")
        validate_identifier_date(self.retrieved_at, "AuthorityDocumentPin.retrieved_at")
        _require_text(self.content_type, "AuthorityDocumentPin.content_type")


# Real capture, retrieved directly from sam.gov on 2026-08-03 (HTTP 200,
# content-length 61315, `Cache-Control: s-maxage=300` at a shared CDN edge --
# see the module docstring for why that makes it a legitimate byte-stable
# pin target). This module never parses this HTML; it exists only as pinned
# provenance alongside the documented UEI format encoded above.
SAM_UEI_DOCUMENTATION_PIN = AuthorityDocumentPin(
    url=SAM_UEI_AUTHORITY_URI,
    sha256="sha256:af69548c8461ecb09da9aaa024afbfb2f5ee1831880062916ceb1e2c9527a4cc",
    byte_length=61_315,
    retrieved_at="2026-08-03T19:21:13Z",
    content_type="text/html",
)


@dataclass(frozen=True, slots=True)
class FetchedAuthorityDocument:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class AuthorityDocumentFetcher(Protocol):
    """Small transport boundary for re-verifying a pinned authority document."""

    def fetch(self, url: str, *, timeout_seconds: float) -> FetchedAuthorityDocument:
        """Fetch one response while preserving its exact body bytes."""


def verify_authority_document(payload: bytes, pin: AuthorityDocumentPin) -> None:
    """Refuse any payload that does not match one pinned authority document exactly."""

    if not isinstance(payload, bytes) or len(payload) != pin.byte_length or _sha256(payload) != pin.sha256:
        raise UeiCageIdentifierError(f"payload does not match the pinned authority document at {pin.url}")


def acquire_authority_document(
    pin: AuthorityDocumentPin,
    *,
    source_path: Path | None = None,
    fetcher: AuthorityDocumentFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> bytes:
    """Acquire and verify one exact authority document through an injected boundary.

    Importing this module never opens a network connection; a caller must
    supply either a local ``source_path`` or an injected ``fetcher``.
    """

    if source_path is not None and fetcher is not None:
        raise UeiCageIdentifierError("provide source_path or fetcher, not both")
    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise UeiCageIdentifierError(f"authority document source is not a regular file: {local_path}")
        payload = local_path.read_bytes()
    elif fetcher is not None:
        if timeout_seconds <= 0:
            raise UeiCageIdentifierError("timeout_seconds must be positive")
        response = fetcher.fetch(pin.url, timeout_seconds=timeout_seconds)
        if response.status_code != 200:
            raise UeiCageIdentifierError(f"could not acquire {pin.url}: HTTP {response.status_code}")
        payload = response.body
    else:
        raise UeiCageIdentifierError("provide source_path or an injected fetcher")
    verify_authority_document(payload, pin)
    return payload


__all__ = [
    "DLA_CAGE_AUTHORITY_URI",
    "DLA_CAGE_KIND",
    "MAX_SAMPLE_SIZE",
    "PARSER_VERSION",
    "SAMPLE_CAPTURE_FORMAT",
    "SAM_UEI_AUTHORITY_URI",
    "SAM_UEI_DOCUMENTATION_PIN",
    "SAM_UEI_KIND",
    "AuthorityDocumentFetcher",
    "AuthorityDocumentPin",
    "CageRecord",
    "FetchedAuthorityDocument",
    "UeiCageAuthoritySample",
    "UeiCageIdentifierError",
    "UeiRecord",
    "acquire_authority_document",
    "parse_capture",
    "render_capture",
    "validate_cage_syntax",
    "validate_uei_syntax",
    "verify_authority_document",
]
