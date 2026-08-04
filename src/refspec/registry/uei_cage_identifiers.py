"""SAM.gov Unique Entity ID (UEI) and DLA CAGE code identifier authorities.

The catalog entry for this source is scoped to award-entity and facility
identifier *schemes*, not entity data: capture identifier syntax, validity
vocabulary, and registration/facility/parent distinctions, and record the
public/controlled access distinction. It is explicit that no bulk entity
data may be ingested. This module therefore accepts only small, exact public
SAM.gov API responses and never accepts more than ``MAX_SAMPLE_SIZE`` records
of either kind -- that ceiling is enforced at runtime, not only documented.

Every UEI and CAGE value handled here still carries a real
``ControlledIdentifier`` naming its publisher authority; this module mints
no identifiers of its own. Illustrative fixtures remain supported for schema
tests, while ``parse_sam_entity_public_response`` builds a
``publisherApiResponse`` sample only from exact, digest-pinned public API
bytes. It rejects protected sections and bulk responses.

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

The pinned public Entity Management v4 response records one current entity's
UEI, associated CAGE code, public label, and registration status. SAM.gov did
not publish a DLA CAGE status in that response, so the CAGE association is
honestly marked ``notObserved`` rather than copying the SAM registration
status. Importing this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from refspec.registry.infrastructure.controlled_identifier import (
    ControlledIdentifier,
    ControlledIdentifierError,
    validate_identifier_date,
)
from refspec.storage import canonical_json

SAM_UEI_AUTHORITY_URI = "https://sam.gov/entity-registration"
SAM_ENTITY_API_URL = "https://api.sam.gov/entity-information/v4/entities"
SAM_ENTITY_3M_PUBLIC_SOURCE_URL = (
    f"{SAM_ENTITY_API_URL}?ueiSAM=YLQMY5SGNE55&includeSections=entityRegistration"
)
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
_CAGE_STATUSES = frozenset({"active", "inactive", "notObserved"})
# SAM.gov entities may be excluded from public search; DLA CAGE and SAM.gov
# records may also carry Controlled Unclassified Information boundaries.
# Public access to one field never authorizes protected entity data.
_ACCESS_CLASSIFICATIONS = frozenset(
    {"public", "excludedFromPublicSearch", "controlledUnclassifiedInformation"}
)

SAMPLE_CAPTURE_FORMAT = "urn:ref:registry:uei-cage-identifier-authority-sample:v1"
PARSER_VERSION = "uei-cage-identifier-authority-sample-v1"
_ILLUSTRATIVE_PROVENANCE = "illustrativeFormatExample"
_PUBLISHER_API_PROVENANCE = "publisherApiResponse"
_SAMPLE_PROVENANCES = frozenset({_ILLUSTRATIVE_PROVENANCE, _PUBLISHER_API_PROVENANCE})

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
    """A small, non-bulk sample of both identifier schemes.

    This is never a registry export: ``MAX_SAMPLE_SIZE`` caps each side and
    provenance distinguishes illustrative fixtures from exact public API
    responses.
    """

    captured_at: str
    ueis: tuple[UeiRecord, ...]
    cages: tuple[CageRecord, ...]
    sample_provenance: str = _ILLUSTRATIVE_PROVENANCE

    def __post_init__(self) -> None:
        validate_identifier_date(self.captured_at, "UeiCageAuthoritySample.captured_at")
        if self.sample_provenance not in _SAMPLE_PROVENANCES:
            raise UeiCageIdentifierError(
                f"unsupported sample_provenance: {self.sample_provenance!r}"
            )
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
            "sampleProvenance": self.sample_provenance,
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
    if value["sampleProvenance"] not in _SAMPLE_PROVENANCES:
        raise UeiCageIdentifierError(
            "capture sampleProvenance must identify an illustrative fixture or pinned public API response"
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
    return UeiCageAuthoritySample(
        captured_at=value["capturedAt"],
        ueis=ueis,
        cages=cages,
        sample_provenance=value["sampleProvenance"],
    )


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


@dataclass(frozen=True, slots=True)
class SamEntityApiPin:
    """Exact identity and expected count of one public Entity API response."""

    url: str
    sha256: str
    byte_length: int
    retrieved_at: str
    expected_count: int
    content_type: str = "application/json"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or parsed.hostname != "api.sam.gov":
            raise UeiCageIdentifierError(
                "SamEntityApiPin.url must use the official HTTPS api.sam.gov host"
            )
        if parsed.username is not None or parsed.password is not None:
            raise UeiCageIdentifierError("SamEntityApiPin.url must not contain credentials")
        if "api_key" in parse_qs(parsed.query):
            raise UeiCageIdentifierError("SamEntityApiPin.url must not preserve an API credential")
        if _SHA256.fullmatch(self.sha256) is None:
            raise UeiCageIdentifierError(
                "SamEntityApiPin.sha256 must be a lowercase sha256:<64 hex> digest"
            )
        if self.byte_length <= 0:
            raise UeiCageIdentifierError("SamEntityApiPin.byte_length must be positive")
        if not (0 < self.expected_count <= MAX_SAMPLE_SIZE):
            raise UeiCageIdentifierError(
                f"SamEntityApiPin.expected_count must be between 1 and {MAX_SAMPLE_SIZE}"
            )
        validate_identifier_date(self.retrieved_at, "SamEntityApiPin.retrieved_at")
        if self.content_type != "application/json":
            raise UeiCageIdentifierError("SamEntityApiPin.content_type must be application/json")


SAM_ENTITY_3M_PUBLIC_PIN = SamEntityApiPin(
    url=SAM_ENTITY_3M_PUBLIC_SOURCE_URL,
    sha256="sha256:3d14996c9e6954af51a183f26168f9f835891f2ec5ef11e2dc6d3180ce6550a1",
    byte_length=1_076,
    retrieved_at="2026-08-03T22:19:50Z",
    expected_count=1,
)


_SAM_ENTITY_ROOT_FIELDS = {"totalRecords", "entityData", "links"}
_SAM_ENTITY_LINK_FIELDS = {"selfLink"}
_SAM_ENTITY_REGISTRATION_FIELDS = {
    "samRegistered",
    "ueiSAM",
    "entityEFTIndicator",
    "cageCode",
    "dodaac",
    "legalBusinessName",
    "dbaName",
    "purposeOfRegistrationCode",
    "purposeOfRegistrationDesc",
    "registrationStatus",
    "evsSource",
    "registrationDate",
    "lastUpdateDate",
    "registrationExpirationDate",
    "activationDate",
    "ueiStatus",
    "ueiExpirationDate",
    "ueiCreationDate",
    "publicDisplayFlag",
    "exclusionStatusFlag",
    "exclusionURL",
    "dnbOpenData",
}


def verify_sam_entity_api_response(payload: bytes, pin: SamEntityApiPin) -> None:
    """Refuse bytes that differ from one reviewed public Entity API response."""

    if not isinstance(payload, bytes) or len(payload) != pin.byte_length or _sha256(payload) != pin.sha256:
        raise UeiCageIdentifierError(
            f"payload does not match the pinned SAM Entity API response at {pin.url}"
        )


def _require_nullable_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, label)


def _validate_public_self_link(value: object) -> None:
    self_link = _require_text(value, "links.selfLink")
    parsed = urlsplit(self_link)
    if parsed.scheme != "https" or parsed.hostname != "api.sam.gov":
        raise UeiCageIdentifierError("links.selfLink must remain on the official HTTPS api.sam.gov host")
    query = parse_qs(parsed.query, keep_blank_values=True)
    api_keys = query.get("api_key", [])
    if api_keys and api_keys != ["REPLACE_WITH_API_KEY"]:
        raise UeiCageIdentifierError("links.selfLink exposed an API credential")
    if query.get("includeSections") != ["entityRegistration"]:
        raise UeiCageIdentifierError(
            "links.selfLink must limit the response to the public entityRegistration section"
        )


def parse_sam_entity_public_response(
    payload: bytes,
    pin: SamEntityApiPin = SAM_ENTITY_3M_PUBLIC_PIN,
) -> UeiCageAuthoritySample:
    """Build a small identifier sample from exact public SAM Entity API bytes.

    Protected or additional entity sections fail closed. SAM registration
    status is retained only on the UEI record and is never reinterpreted as
    DLA CAGE status.
    """

    verify_sam_entity_api_response(payload, pin)
    try:
        root = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UeiCageIdentifierError("SAM Entity API response must be valid UTF-8 JSON") from error
    if not isinstance(root, Mapping):
        raise UeiCageIdentifierError("SAM Entity API response must contain one object")
    _exact_keys(root, _SAM_ENTITY_ROOT_FIELDS, "SAM Entity API response")

    total_records = root["totalRecords"]
    entity_data = root["entityData"]
    links = root["links"]
    if not isinstance(total_records, int) or isinstance(total_records, bool) or total_records < 0:
        raise UeiCageIdentifierError("totalRecords must be a non-negative integer")
    if not isinstance(entity_data, list):
        raise UeiCageIdentifierError("entityData must be an array")
    if len(entity_data) > MAX_SAMPLE_SIZE:
        raise UeiCageIdentifierError(
            f"entityData exceeds MAX_SAMPLE_SIZE={MAX_SAMPLE_SIZE}; refusing bulk entity data"
        )
    if total_records != pin.expected_count or len(entity_data) != pin.expected_count:
        raise UeiCageIdentifierError(
            f"SAM Entity API count drift: expected {pin.expected_count}, "
            f"reported {total_records}, returned {len(entity_data)}"
        )
    if not isinstance(links, Mapping):
        raise UeiCageIdentifierError("links must be an object")
    _exact_keys(links, _SAM_ENTITY_LINK_FIELDS, "links")
    _validate_public_self_link(links["selfLink"])

    ueis: list[UeiRecord] = []
    cages: list[CageRecord] = []
    for index, entity in enumerate(entity_data):
        label = f"entityData[{index}]"
        if not isinstance(entity, Mapping):
            raise UeiCageIdentifierError(f"{label} must be an object")
        _exact_keys(entity, {"entityRegistration"}, label)
        registration = entity["entityRegistration"]
        if not isinstance(registration, Mapping):
            raise UeiCageIdentifierError(f"{label}.entityRegistration must be an object")
        _exact_keys(registration, _SAM_ENTITY_REGISTRATION_FIELDS, f"{label}.entityRegistration")

        if registration["samRegistered"] != "Yes":
            raise UeiCageIdentifierError(f"{label}.entityRegistration.samRegistered must be 'Yes'")
        if registration["publicDisplayFlag"] != "Y":
            raise UeiCageIdentifierError(
                f"{label}.entityRegistration is not approved for public display"
            )
        uei = validate_uei_syntax(
            _require_text(registration["ueiSAM"], f"{label}.entityRegistration.ueiSAM")
        )
        cage = validate_cage_syntax(
            _require_text(registration["cageCode"], f"{label}.entityRegistration.cageCode")
        )
        legal_name = _require_text(
            registration["legalBusinessName"],
            f"{label}.entityRegistration.legalBusinessName",
        )
        registration_status = _require_text(
            registration["registrationStatus"],
            f"{label}.entityRegistration.registrationStatus",
        ).lower()
        if registration_status not in _REGISTRATION_STATUSES:
            raise UeiCageIdentifierError(
                f"{label}.entityRegistration.registrationStatus is unsupported: {registration_status!r}"
            )
        if _require_text(registration["ueiStatus"], f"{label}.entityRegistration.ueiStatus").lower() not in {
            "active",
            "inactive",
        }:
            raise UeiCageIdentifierError(f"{label}.entityRegistration.ueiStatus is unsupported")
        for field in (
            "entityEFTIndicator",
            "dodaac",
            "dbaName",
            "evsSource",
            "ueiExpirationDate",
            "exclusionURL",
            "dnbOpenData",
        ):
            _require_nullable_text(registration[field], f"{label}.entityRegistration.{field}")
        for field in (
            "purposeOfRegistrationCode",
            "purposeOfRegistrationDesc",
            "registrationDate",
            "lastUpdateDate",
            "registrationExpirationDate",
            "activationDate",
            "ueiCreationDate",
            "exclusionStatusFlag",
        ):
            _require_text(registration[field], f"{label}.entityRegistration.{field}")

        ueis.append(
            UeiRecord(
                identifier=ControlledIdentifier(
                    value=uei,
                    kind=SAM_UEI_KIND,
                    authority_uri=SAM_UEI_AUTHORITY_URI,
                    source_uri=pin.url,
                    observed_at=pin.retrieved_at,
                    effective_at=None,
                    source_digest=pin.sha256,
                ),
                legal_business_name=legal_name,
                registration_status=registration_status,
                access_classification="public",
                immediate_parent_uei=None,
                highest_level_owner_uei=None,
            )
        )
        cages.append(
            CageRecord(
                identifier=ControlledIdentifier(
                    value=cage,
                    kind=DLA_CAGE_KIND,
                    authority_uri=DLA_CAGE_AUTHORITY_URI,
                    source_uri=pin.url,
                    observed_at=pin.retrieved_at,
                    effective_at=None,
                    source_digest=pin.sha256,
                ),
                facility_name=legal_name,
                cage_status="notObserved",
                access_classification="public",
                associated_uei=uei,
            )
        )

    return UeiCageAuthoritySample(
        captured_at=pin.retrieved_at,
        ueis=tuple(ueis),
        cages=tuple(cages),
        sample_provenance=_PUBLISHER_API_PROVENANCE,
    )


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
    "SAM_ENTITY_3M_PUBLIC_PIN",
    "SAM_ENTITY_3M_PUBLIC_SOURCE_URL",
    "SAM_ENTITY_API_URL",
    "SAM_UEI_AUTHORITY_URI",
    "SAM_UEI_DOCUMENTATION_PIN",
    "SAM_UEI_KIND",
    "AuthorityDocumentFetcher",
    "AuthorityDocumentPin",
    "CageRecord",
    "FetchedAuthorityDocument",
    "SamEntityApiPin",
    "UeiCageAuthoritySample",
    "UeiCageIdentifierError",
    "UeiRecord",
    "acquire_authority_document",
    "parse_capture",
    "parse_sam_entity_public_response",
    "render_capture",
    "validate_cage_syntax",
    "validate_uei_syntax",
    "verify_authority_document",
    "verify_sam_entity_api_response",
]
