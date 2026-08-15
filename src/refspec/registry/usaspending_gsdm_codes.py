"""Pinned USAspending award/assistance/action type codes and GSDM schema crosswalk.

The USAspending API publishes a live ``/references/award_types/`` endpoint
covering award type codes (contracts, IDVs) and assistance type codes (grants,
loans, direct payments, other financial assistance). These are deterministic
operational codes: award and assistance *descriptions* receive subjects
elsewhere in RefSpec, but these codes never do.

The Governmentwide Spending Data Model (GSDM, formerly DAIMS) Architecture
document defines the metadata-registry shape that RefSpec pins to version
1.0.1. GSDM itself carries no enumerated code list; the *online data
dictionary* it cites (also served by api.usaspending.gov) crosswalks each
GSDM/DAIMS element to USAspending download files, submission tables, and
award-category field names, and gives each element's domain values. That
data dictionary lists 457 elements. RefSpec pins the exact digest of the full
document, parses every structural row, and parses the publisher's own
``Domain Values`` and ``Domain Values Code Description`` columns across all
457 elements (``parse_gsdm_domain_values``): 203 elements enumerate their
domain values inline and every one of those enumerations is read; 86 carry
domain text that defers to an external code source instead of enumerating;
168 publish no domain text. Three elements -- ActionType, AssistanceType,
ContractAwardType -- additionally remain transcribed as reviewed typed
constants because the validation helpers below join against them. Award
Type and Assistance Type codes therefore appear twice in this module, once
from the live endpoint (short labels) and once from the data dictionary
(fuller code descriptions); RefSpec preserves both without reconciling them.

Acquisition of the live award_types endpoint accepts a local exact capture or
an injected fetcher. Importing this module never opens a network connection.
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
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode
from refspec.storage import canonical_json

USASPENDING_PUBLISHER = "U.S. Department of the Treasury, Bureau of the Fiscal Service (USAspending.gov)"
USASPENDING_IDENTIFIER_AUTHORITY_URI = "https://www.usaspending.gov/"
USASPENDING_API_BASE = "https://api.usaspending.gov/api/v2"
USASPENDING_DOCS_URL = "https://api.usaspending.gov/docs/endpoints"

GSDM_PUBLISHER = "U.S. Department of the Treasury, Bureau of the Fiscal Service"
GSDM_TITLE = "Governmentwide Spending Data Model (GSDM) Architecture"
GSDM_FORMER_NAME = "DATA Act Information Model Schema (DAIMS)"
GSDM_VERSION = "1.0.1"
GSDM_REVISION_DATE = "2024-04-11"
GSDM_DOCUMENT_URL = "https://fiscal.treasury.gov/files/data-transparency/gsdm-architecture-v1.0.1.pdf"
GSDM_DOCUMENT_SHA256 = "sha256:6901ce4004e3338e54a69abb59d81205680d63f25e8dca0f9a92815dff6ced9d"
GSDM_DOCUMENT_BYTE_LENGTH = 363_340

# Section 3 ("Metadata") of the pinned architecture document lists these as the
# GSDM metadata registry's ISO/IEC 11179-aligned data-element attributes. This
# is the crosswalk *shape*, not a code list: it names the fields every GSDM
# element publishes, including the "Enumerations/Domain Value" field that the
# online data dictionary fills in per element.
GSDM_METADATA_REGISTRY_ATTRIBUTES = (
    "Domain",
    "Data Element Label",
    "Data Type",
    "Max Element Length",
    "Documentation",
    "Element Use",
    "Element Number",
    "Enumerations/Domain Value",
    "Example Value",
    "Submission Instructions",
    "Validation Rule",
)

# Identity of the online data dictionary document RefSpec reviewed to curate
# the GSDM crosswalk elements below. Pinned like the LDA OpenAPI document:
# exact digest and length recorded, content not parsed at runtime.
GSDM_DATA_DICTIONARY_URL = f"{USASPENDING_API_BASE}/references/data_dictionary/"
GSDM_DATA_DICTIONARY_RETRIEVED_AT = "2026-08-03T19:25:21Z"
GSDM_DATA_DICTIONARY_SHA256 = "sha256:3d0f2e3a952297050db5c2a4addf40765460a49d499427da1b57ef3c7edea3c3"
GSDM_DATA_DICTIONARY_BYTE_LENGTH = 358_054
GSDM_DATA_DICTIONARY_ROW_COUNT = 457
GSDM_DATA_DICTIONARY_COLUMN_COUNT = 17
GSDM_DATA_DICTIONARY_ROW_WIDTH = 18

ResourceName = Literal["awardTypes"]
ResourceUse = Literal["deterministicMetadata"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_AWARD_CODE = re.compile(r"^-?[A-Z0-9_]{1,16}$")
_ELEMENT_NAME = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_DOMAIN_GROUP = re.compile(r"^(?:|assistance|contracts)$")
_DOMAIN_CODE = re.compile(r"^[A-Z0-9]{1,4}$")
_FILE_NAME = re.compile(r"^[A-Za-z0-9_.]+$")
_ELEMENT_FIELD = re.compile(r"^[A-Za-z0-9_]+$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# award_type_code / assistance_type_code category -> the ControlledIdentifier
# kind this catalog entry uses for it. Contracts and IDVs are procurement
# award types; the remaining four categories are assistance types.
_AWARD_TYPE_CATEGORIES: dict[str, str] = {
    "contracts": "awardTypeCode",
    "idvs": "awardTypeCode",
    "grants": "assistanceTypeCode",
    "loans": "assistanceTypeCode",
    "other_financial_assistance": "assistanceTypeCode",
    "direct_payments": "assistanceTypeCode",
}


class USASpendingResourceError(ValueError):
    """Base class for USAspending/GSDM controlled-code failures."""


class USASpendingAcquisitionError(USASpendingResourceError):
    """Exact official source bytes could not be acquired safely."""


class USASpendingSourceDriftError(USASpendingResourceError):
    """A USAspending or GSDM source no longer matches the reviewed structure or pin."""


class USASpendingAssignmentError(USASpendingResourceError):
    """A record carries an unknown or malformed USAspending/GSDM code."""


@dataclass(frozen=True, slots=True)
class USASpendingConstantSource:
    """One official USAspending reference endpoint."""

    resource_name: ResourceName
    source_url: str
    filename: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "api.usaspending.gov":
            raise USASpendingAcquisitionError("source_url must be an official HTTPS api.usaspending.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise USASpendingAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise USASpendingAcquisitionError("filename must be one plain path component")


USASPENDING_AWARD_TYPES = USASpendingConstantSource(
    resource_name="awardTypes",
    source_url=f"{USASPENDING_API_BASE}/references/award_types/",
    filename="usaspending-award-types.json",
)


@dataclass(frozen=True, slots=True)
class USASpendingSnapshotPin:
    """Exact identity of one official USAspending reference response."""

    source: USASpendingConstantSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise USASpendingAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise USASpendingAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise USASpendingAcquisitionError("retrieved_at must not be empty")


# Live sample observed 2026-08-03. The endpoint returns a small, complete,
# already-closed object (six categories); unlike the data dictionary there is
# no bulk/curation tradeoff here, so this resource is acquired and parsed in
# full like LDA's constants endpoints.
USASPENDING_AWARD_TYPES_2026_08_03 = USASpendingSnapshotPin(
    source=USASPENDING_AWARD_TYPES,
    retrieved_at="2026-08-03T19:25:21Z",
    expected_sha256="sha256:682269b46e0cf200c7002ca7d55ba3da3de8dc345958d579ec98e579fc6782e7",
    expected_byte_length=1_271,
)


@dataclass(frozen=True, slots=True)
class FetchedUSASpendingResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class USASpendingFetcher(Protocol):
    """Small transport boundary for official USAspending JSON endpoints."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedUSASpendingResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredUSASpendingSource:
    """One verified source object in the content-addressed store."""

    pin: USASpendingSnapshotPin
    path: Path
    sha256: str
    byte_length: int
    source_url: str
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


@dataclass(frozen=True, slots=True)
class USASpendingCode:
    """One exact award/assistance type code and label retained from USAspending."""

    resource_name: ResourceName
    category: str
    use: ResourceUse
    publisher_label: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedAwardTypesResource:
    """A parsed, digest-pinned USAspending award/assistance type code list."""

    source: USASpendingConstantSource
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    codes: tuple[USASpendingCode, ...]

    def by_code(self) -> dict[str, USASpendingCode]:
        """Index every code's single published value across all six categories."""

        result: dict[str, USASpendingCode] = {}
        for entry in self.codes:
            for identifier in entry.identifiers:
                if identifier.value in result:
                    raise USASpendingSourceDriftError(f"award_types code {identifier.value!r} is not unique")
                result[identifier.value] = entry
        return result


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "api.usaspending.gov":
        raise USASpendingAcquisitionError("fetcher resolved_url must remain on official HTTPS api.usaspending.gov")
    if parsed.username is not None or parsed.password is not None:
        raise USASpendingAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: USASpendingSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise USASpendingSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise USASpendingSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    try:
        json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise USASpendingSourceDriftError(f"{location} is not valid JSON") from error
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: USASpendingSnapshotPin) -> AcquiredUSASpendingSource:
    if path.is_symlink() or not path.is_file():
        raise USASpendingAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached USAspending source",
    )
    return AcquiredUSASpendingSource(
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
    pin: USASpendingSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredUSASpendingSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} USAspending source",
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
        return AcquiredUSASpendingSource(
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


def acquire_usaspending_award_types(
    pin: USASpendingSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: USASpendingFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredUSASpendingSource:
    """Acquire one exact award_types response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise USASpendingAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise USASpendingAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise USASpendingAcquisitionError(f"local USAspending source is not a regular file: {local_path}")
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
        raise USASpendingAcquisitionError(
            "USAspending award_types is not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise USASpendingAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "application/json":
        raise USASpendingSourceDriftError(f"USAspending award_types content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def parse_award_types(acquired: AcquiredUSASpendingSource) -> ParsedAwardTypesResource:
    """Parse the exact award_types object without inventing missing categories."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed USAspending source")
    try:
        root = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise USASpendingSourceDriftError("USAspending award_types payload is not valid JSON") from error
    if not isinstance(root, Mapping) or set(root) != set(_AWARD_TYPE_CATEGORIES):
        drifted = sorted(root) if isinstance(root, Mapping) else type(root).__name__
        raise USASpendingSourceDriftError(f"USAspending award_types categories drifted: {drifted}")

    codes: list[USASpendingCode] = []
    for category, kind in _AWARD_TYPE_CATEGORIES.items():
        entries = root[category]
        if not isinstance(entries, Mapping) or not entries:
            raise USASpendingSourceDriftError(f"USAspending award_types category {category!r} must be a non-empty object")
        for code, label in entries.items():
            if not isinstance(code, str) or _AWARD_CODE.fullmatch(code) is None:
                raise USASpendingSourceDriftError(f"USAspending award_types {category} has a malformed code: {code!r}")
            if not isinstance(label, str) or not label.strip() or label != label.strip():
                raise USASpendingSourceDriftError(f"USAspending award_types {category}[{code}] has a malformed label")
            identifier = ControlledIdentifier(
                value=code,
                kind=kind,
                authority_uri=USASPENDING_IDENTIFIER_AUTHORITY_URI,
                source_uri=acquired.pin.source.source_url,
                observed_at=acquired.pin.retrieved_at,
                effective_at=None,
                source_digest=acquired.sha256,
            )
            codes.append(
                USASpendingCode(
                    resource_name="awardTypes",
                    category=category,
                    use="deterministicMetadata",
                    publisher_label=label,
                    source_url=acquired.pin.source.source_url,
                    identifiers=(identifier,),
                )
            )
    # Codes are unique across categories in the reviewed sample, but labels
    # are not (e.g. loans "07" and "F003" both publish "Direct Loan"). Only
    # code uniqueness is a safe invariant to enforce here.
    values = [identifier.value for entry in codes for identifier in entry.identifiers]
    if len(set(values)) != len(values):
        raise USASpendingSourceDriftError("USAspending award_types contain a duplicate code across categories")

    return ParsedAwardTypesResource(
        source=acquired.pin.source,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        codes=tuple(codes),
    )


@dataclass(frozen=True, slots=True)
class GSDMFileElement:
    """One published USAspending file/table column that carries a GSDM element's value."""

    file: str
    element: str

    def __post_init__(self) -> None:
        if _FILE_NAME.fullmatch(self.file) is None:
            raise USASpendingSourceDriftError(f"GSDM crosswalk file name is malformed: {self.file!r}")
        if _ELEMENT_FIELD.fullmatch(self.element) is None:
            raise USASpendingSourceDriftError(f"GSDM crosswalk element name is malformed: {self.element!r}")


@dataclass(frozen=True, slots=True)
class GSDMDomainValue:
    """One code/label pair drawn from a GSDM element's published domain values."""

    domain_group: str
    code: str
    label: str
    code_description: str | None

    def __post_init__(self) -> None:
        if _DOMAIN_GROUP.fullmatch(self.domain_group) is None:
            raise USASpendingSourceDriftError(f"GSDM domain group is unsupported: {self.domain_group!r}")
        if _DOMAIN_CODE.fullmatch(self.code) is None:
            raise USASpendingSourceDriftError(f"GSDM domain value code is malformed: {self.code!r}")
        if not self.label.strip() or self.label != self.label.strip():
            raise USASpendingSourceDriftError(f"GSDM domain value label is malformed: {self.label!r}")
        if self.code_description is not None and (
            not self.code_description.strip() or self.code_description != self.code_description.strip()
        ):
            raise USASpendingSourceDriftError("GSDM domain value code_description must not be blank when present")


@dataclass(frozen=True, slots=True)
class GSDMCrosswalkElement:
    """One GSDM/DAIMS data element: its published domain values and file crosswalk.

    ``download_files`` names the public award/transaction download columns,
    ``account_files`` the account-breakdown download columns, ``submission_tables``
    the raw agency-submission table columns, and ``award_category_fields`` the
    per-award-category application field names. These four crosswalks are what
    this catalog entry calls "GSDM schema crosswalk fields."
    """

    gsdm_element: str
    definition: str
    fpds_data_dictionary_element: str | None
    grouping: str
    download_files: tuple[GSDMFileElement, ...]
    account_files: tuple[GSDMFileElement, ...]
    submission_tables: tuple[GSDMFileElement, ...]
    award_category_fields: tuple[GSDMFileElement, ...]
    domain_values: tuple[GSDMDomainValue, ...]

    def __post_init__(self) -> None:
        if _ELEMENT_NAME.fullmatch(self.gsdm_element) is None:
            raise USASpendingSourceDriftError(f"GSDM element name is malformed: {self.gsdm_element!r}")
        if not self.definition.strip():
            raise USASpendingSourceDriftError(f"{self.gsdm_element} is missing its published definition")
        if not self.domain_values:
            raise USASpendingSourceDriftError(f"{self.gsdm_element} must retain at least one domain value")
        seen = {(value.domain_group, value.code) for value in self.domain_values}
        if len(seen) != len(self.domain_values):
            raise USASpendingSourceDriftError(f"{self.gsdm_element} domain values repeat a (group, code) pair")

    def by_code(self, domain_group: str = "") -> dict[str, GSDMDomainValue]:
        """Index this element's domain values for one published domain group."""

        return {value.code: value for value in self.domain_values if value.domain_group == domain_group}


@dataclass(frozen=True, slots=True)
class GSDMDataDictionaryRow:
    """One complete row from the pinned USAspending data dictionary."""

    ordinal: int
    element: str
    cells: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class ParsedGSDMDataDictionary:
    """All structural rows and headings from one exact dictionary response."""

    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    headers: tuple[tuple[str, str], ...]
    sections: tuple[Mapping[str, object], ...]
    metadata: Mapping[str, object]
    rows: tuple[GSDMDataDictionaryRow, ...]


def parse_gsdm_data_dictionary(
    payload: bytes,
    *,
    expected_sha256: str = GSDM_DATA_DICTIONARY_SHA256,
    expected_byte_length: int = GSDM_DATA_DICTIONARY_BYTE_LENGTH,
) -> ParsedGSDMDataDictionary:
    """Parse every row of the pinned online GSDM data dictionary.

    The publisher reports 17 named columns but supplies 18 cells in each row.
    The final unnamed cell is retained exactly instead of being discarded or
    assigned an invented meaning.
    """

    if not isinstance(payload, bytes) or not payload:
        raise USASpendingSourceDriftError("GSDM data dictionary must be non-empty bytes")
    if len(payload) != expected_byte_length:
        raise USASpendingSourceDriftError(
            "GSDM data dictionary byte length drift: "
            f"expected {expected_byte_length}, got {len(payload)}"
        )
    digest = sha256_digest(payload)
    if digest != expected_sha256:
        raise USASpendingSourceDriftError(
            f"GSDM data dictionary digest drift: expected {expected_sha256}, got {digest}"
        )
    try:
        root = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise USASpendingSourceDriftError("GSDM data dictionary is not valid UTF-8 JSON") from error
    if not isinstance(root, Mapping) or set(root) != {"document"}:
        raise USASpendingSourceDriftError("GSDM data dictionary root shape drifted")
    document = root["document"]
    if not isinstance(document, Mapping) or set(document) != {
        "headers",
        "metadata",
        "rows",
        "sections",
    }:
        raise USASpendingSourceDriftError("GSDM data dictionary document shape drifted")

    raw_headers = document["headers"]
    if not isinstance(raw_headers, list) or len(raw_headers) != GSDM_DATA_DICTIONARY_COLUMN_COUNT:
        raise USASpendingSourceDriftError("GSDM data dictionary header count drifted")
    headers: list[tuple[str, str]] = []
    for ordinal, header in enumerate(raw_headers):
        if (
            not isinstance(header, Mapping)
            or set(header) != {"display", "raw"}
            or not isinstance(header["raw"], str)
            or not header["raw"]
            or not isinstance(header["display"], str)
            or not header["display"]
        ):
            raise USASpendingSourceDriftError(
                f"GSDM data dictionary header {ordinal} shape drifted"
            )
        headers.append((header["raw"], header["display"]))

    metadata = document["metadata"]
    if not isinstance(metadata, Mapping) or metadata.get("total_rows") != GSDM_DATA_DICTIONARY_ROW_COUNT:
        raise USASpendingSourceDriftError("GSDM data dictionary metadata row count drifted")
    raw_sections = document["sections"]
    if not isinstance(raw_sections, list) or not all(isinstance(row, Mapping) for row in raw_sections):
        raise USASpendingSourceDriftError("GSDM data dictionary sections shape drifted")
    raw_rows = document["rows"]
    if not isinstance(raw_rows, list) or len(raw_rows) != GSDM_DATA_DICTIONARY_ROW_COUNT:
        raise USASpendingSourceDriftError("GSDM data dictionary row count drifted")

    rows: list[GSDMDataDictionaryRow] = []
    seen_elements: set[str] = set()
    for ordinal, row in enumerate(raw_rows):
        if not isinstance(row, list) or len(row) != GSDM_DATA_DICTIONARY_ROW_WIDTH:
            raise USASpendingSourceDriftError(
                f"GSDM data dictionary row {ordinal} width drifted"
            )
        element = row[0]
        if not isinstance(element, str) or not element.strip() or element != element.strip():
            raise USASpendingSourceDriftError(
                f"GSDM data dictionary row {ordinal} has an invalid element name"
            )
        if element in seen_elements:
            raise USASpendingSourceDriftError(
                f"GSDM data dictionary repeats element {element!r}"
            )
        seen_elements.add(element)
        if not all(
            cell is None or isinstance(cell, (str, int, float, bool))
            for cell in row
        ):
            raise USASpendingSourceDriftError(
                f"GSDM data dictionary row {ordinal} contains a non-scalar cell"
            )
        rows.append(
            GSDMDataDictionaryRow(
                ordinal=ordinal,
                element=element,
                cells=tuple(row),
            )
        )
    return ParsedGSDMDataDictionary(
        source_sha256=digest,
        source_byte_length=len(payload),
        retrieved_at=GSDM_DATA_DICTIONARY_RETRIEVED_AT,
        headers=tuple(headers),
        sections=tuple(dict(row) for row in raw_sections),
        metadata=dict(metadata),
        rows=tuple(rows),
    )


# --- Publisher domain-value enumerations ------------------------------------
#
# The data dictionary's "E:domain_values" cells mix three publisher formats:
# "CODE = LABEL" lines (optionally under "Assistance:"/"Contracts:" group
# headings), "N/A= VALUE" lines marking values that travel without a code, and
# free text deferring the domain to an external code source ("See ...",
# "Refer to ..."). The parser below reads every enumeration and accounts for
# every line it does not emit; it never rewords publisher text.

GSDM_DOMAIN_VALUES_HEADER = "E:domain_values"
GSDM_DOMAIN_VALUES_CODE_DESCRIPTION_HEADER = "F:domain_values_code_description"

# One publisher cell encodes Excel carriage returns as literal "_x000D_"
# tokens (AssistanceTypeDescriptionTag); decoding them is line-ending
# normalization, not rewording.
_DOMAIN_CR_TOKEN = "_x000D_"
_DOMAIN_PAIR_LINE = re.compile(r"^(?P<code>[^=]{1,80}?)\s*=\s*(?P<text>.+)$")
_DOMAIN_GROUP_LINE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z /()&-]{0,60}):$")
# DisasterEmergencyFundName writes two of its rows with "CODE - LABEL"
# instead of "CODE = LABEL"; the tight code shape keeps this from matching
# prose.
_DOMAIN_DASH_LINE = re.compile(r"^(?P<code>[A-Z0-9]{1,8})\s*-\s+(?P<text>.+)$")
# "[Future Code(s)] = [Future P.L.]" is a publisher placeholder for codes
# that do not exist yet, not a domain value.
_DOMAIN_PLACEHOLDER_CODE = re.compile(r"^\[.*\]$")
# "N/A= sub-contract" marks a value the publisher transmits without a code.
_DOMAIN_CODELESS_MARKER = "N/A"


@dataclass(frozen=True, slots=True)
class GSDMPublishedDomainValue:
    """One value a data-dictionary element's Domain Values cell enumerates."""

    element: str
    row_ordinal: int
    domain_group: str
    code: str | None
    value: str
    code_description: str | None

    def __post_init__(self) -> None:
        if not self.element.strip():
            raise USASpendingSourceDriftError("published domain value must name its element")
        if self.code is not None and not self.code.strip():
            raise USASpendingSourceDriftError(f"{self.element} publishes a blank domain value code")
        if not self.value.strip():
            raise USASpendingSourceDriftError(f"{self.element} publishes a blank domain value")

    @property
    def identity(self) -> str:
        """The publisher token identifying this value within its element and group."""

        return self.code if self.code is not None else self.value


@dataclass(frozen=True, slots=True)
class GSDMDomainValuesColumn:
    """Everything the publisher's Domain Values column enumerates, with accounting.

    ``values`` carries every publisher-enumerated domain value across all 457
    elements. The remaining fields say exactly what was not emitted and why:
    elements whose domain text only cites an external source, elements with no
    domain text, placeholder lines, and description-column entries that name a
    code the Domain Values cell does not enumerate.
    """

    source_sha256: str
    element_count: int
    enumerated_element_count: int
    reference_only_element_count: int
    empty_element_count: int
    values: tuple[GSDMPublishedDomainValue, ...]
    codeless_value_elements: tuple[str, ...]
    placeholder_lines: tuple[tuple[str, str], ...]
    unmatched_description_keys: tuple[tuple[str, str, str], ...]
    unpaired_description_elements: tuple[str, ...]
    described_value_count: int


def _domain_cell_lines(cell: object) -> tuple[str, ...]:
    if not isinstance(cell, str):
        return ()
    return tuple(
        line for line in (raw.replace(_DOMAIN_CR_TOKEN, "").strip() for raw in cell.split("\n")) if line
    )


def _parse_domain_lines(
    element: str,
    lines: Sequence[str],
) -> tuple[list[tuple[str, str | None, str]], list[str]] | None:
    """Parse one cell's lines into (group, code, text) triples plus placeholders.

    Returns ``None`` when no line is a ``CODE = LABEL`` pair: the cell is
    publisher domain text, not an enumeration. A line that is neither a pair,
    a group heading, nor a dash pair continues the previous value's text (the
    publisher wraps one label across two lines).
    """

    if not any(_DOMAIN_PAIR_LINE.match(line) for line in lines):
        return None
    values: list[tuple[str, str | None, str]] = []
    placeholders: list[str] = []
    group = ""
    for line in lines:
        pair = _DOMAIN_PAIR_LINE.match(line)
        if pair is not None:
            code = pair.group("code").strip()
            text = pair.group("text").strip()
            if _DOMAIN_PLACEHOLDER_CODE.match(code):
                placeholders.append(line)
            elif code == _DOMAIN_CODELESS_MARKER:
                values.append((group, None, text))
            else:
                values.append((group, code, text))
            continue
        heading = _DOMAIN_GROUP_LINE.match(line)
        if heading is not None:
            group = heading.group("name")
            continue
        dash = _DOMAIN_DASH_LINE.match(line)
        if dash is not None:
            values.append((group, dash.group("code"), dash.group("text").strip()))
            continue
        if not values:
            raise USASpendingSourceDriftError(
                f"{element} domain values start with an unrecognized line: {line!r}"
            )
        previous_group, previous_code, previous_text = values[-1]
        values[-1] = (previous_group, previous_code, previous_text + " " + line)
    return values, placeholders


def parse_gsdm_domain_values(dictionary: ParsedGSDMDataDictionary) -> GSDMDomainValuesColumn:
    """Read every publisher-enumerated domain value from the pinned dictionary."""

    positions = {raw: position for position, (raw, _display) in enumerate(dictionary.headers)}
    for header in (GSDM_DOMAIN_VALUES_HEADER, GSDM_DOMAIN_VALUES_CODE_DESCRIPTION_HEADER):
        if header not in positions:
            raise USASpendingSourceDriftError(f"GSDM data dictionary lost its {header!r} column")
    value_position = positions[GSDM_DOMAIN_VALUES_HEADER]
    description_position = positions[GSDM_DOMAIN_VALUES_CODE_DESCRIPTION_HEADER]

    enumerated: dict[str, tuple[int, list[tuple[str, str | None, str]]]] = {}
    reference_only = 0
    empty = 0
    codeless_elements: list[str] = []
    placeholder_lines: list[tuple[str, str]] = []
    for row in dictionary.rows:
        lines = _domain_cell_lines(row.cells[value_position])
        if not lines:
            empty += 1
            continue
        parsed = _parse_domain_lines(row.element, lines)
        if parsed is None:
            # A cell with no pairs is enumerable in exactly one publisher
            # shape: a bare value list whose description cell pairs every
            # listed value with its definition (PrimaryPlaceOfPerformanceScope).
            description_lines = _domain_cell_lines(row.cells[description_position])
            described = _parse_domain_lines(row.element, description_lines) if description_lines else None
            if described is not None and [code for _group, code, _text in described[0]] == list(lines):
                # Fail closed like the pair path: a bare value is its own
                # identity, so a repeated line would silently collapse two
                # publisher values into one emitted resource.
                if len(lines) != len(set(lines)):
                    raise USASpendingSourceDriftError(
                        f"{row.element} bare domain value list repeats a value"
                    )
                enumerated[row.element] = (row.ordinal, [("", None, line) for line in lines])
                codeless_elements.append(row.element)
                continue
            reference_only += 1
            continue
        values, placeholders = parsed
        placeholder_lines.extend((row.element, line) for line in placeholders)
        if any(code is None for _group, code, _text in values):
            codeless_elements.append(row.element)
        identities = [(group, code if code is not None else text) for group, code, text in values]
        if len(identities) != len(set(identities)):
            raise USASpendingSourceDriftError(
                f"{row.element} domain values repeat a (group, identity) pair"
            )
        enumerated[row.element] = (row.ordinal, values)

    descriptions: dict[str, dict[tuple[str, str], str]] = {}
    unmatched_description_keys: list[tuple[str, str, str]] = []
    unpaired_description_elements: list[str] = []
    described_value_count = 0
    for row in dictionary.rows:
        lines = _domain_cell_lines(row.cells[description_position])
        if not lines or row.element not in enumerated:
            continue
        parsed = _parse_domain_lines(row.element, lines)
        if parsed is None:
            unpaired_description_elements.append(row.element)
            continue
        emitted = {
            (group, code if code is not None else text)
            for group, code, text in enumerated[row.element][1]
        }
        element_descriptions: dict[tuple[str, str], str] = {}
        for group, code, text in parsed[0]:
            identity = code if code is not None else text
            if (group, identity) in emitted:
                element_descriptions[(group, identity)] = text
                described_value_count += 1
            else:
                unmatched_description_keys.append((row.element, group, identity))
        descriptions[row.element] = element_descriptions

    values: list[GSDMPublishedDomainValue] = []
    for element, (ordinal, triples) in sorted(enumerated.items(), key=lambda item: item[1][0]):
        element_descriptions = descriptions.get(element, {})
        for group, code, text in triples:
            identity = code if code is not None else text
            values.append(
                GSDMPublishedDomainValue(
                    element=element,
                    row_ordinal=ordinal,
                    domain_group=group,
                    code=code,
                    value=text,
                    code_description=element_descriptions.get((group, identity)),
                )
            )
    if reference_only + empty + len(enumerated) != len(dictionary.rows):
        raise USASpendingSourceDriftError("GSDM domain value accounting does not cover every row")
    return GSDMDomainValuesColumn(
        source_sha256=dictionary.source_sha256,
        element_count=len(dictionary.rows),
        enumerated_element_count=len(enumerated),
        reference_only_element_count=reference_only,
        empty_element_count=empty,
        values=tuple(values),
        codeless_value_elements=tuple(codeless_elements),
        placeholder_lines=tuple(placeholder_lines),
        unmatched_description_keys=tuple(unmatched_description_keys),
        unpaired_description_elements=tuple(unpaired_description_elements),
        described_value_count=described_value_count,
    )


# The following three constants are reviewed, hardcoded transcriptions of the
# ActionType, AssistanceType, and ContractAwardType rows in the USAspending
# online data dictionary (GSDM_DATA_DICTIONARY_URL, pinned above). They are
# the only three of that document's 457 elements this catalog entry scopes
# in; every string below is copied verbatim from the publisher's JSON, not
# reworded or summarized.

GSDM_ACTION_TYPE = GSDMCrosswalkElement(
    gsdm_element='ActionType',
    definition='Code that provides information on any new (only applicable to financial assistance awards) or changes (applies to both procurement and financial assistance changes) made to the Federal prime award. There may be multiple actions for each award.',
    fpds_data_dictionary_element='Reason for Modification',
    grouping='Award Attribute',
    download_files=(
        GSDMFileElement('Contracts_PrimeTransactions.csv', 'action_type_code'),
        GSDMFileElement('Assistance_PrimeTransactions.csv', 'action_type_code'),
    ),
    account_files=(),
    submission_tables=(
        GSDMFileElement('transaction_fpds', 'action_type'),
        GSDMFileElement('transaction_fabs', 'action_type'),
    ),
    award_category_fields=(
        GSDMFileElement('Assistance', 'action_type'),
        GSDMFileElement('Contracts', 'reasonformodification'),
    ),
    domain_values=(
        GSDMDomainValue('assistance', 'A', 'New', None),
        GSDMDomainValue('assistance', 'B', 'Continuation', None),
        GSDMDomainValue('assistance', 'C', 'Revision', None),
        GSDMDomainValue('assistance', 'D', 'Adjustment to Completed Project', None),
        GSDMDomainValue('assistance', 'E', 'Aggregate Mixed', None),
        GSDMDomainValue('contracts', 'A', 'ADDITIONAL WORK (NEW AGREEMENT, JUSTIFICATION REQUIRED)', None),
        GSDMDomainValue('contracts', 'B', 'SUPPLEMENTAL AGREEMENT FOR WORK WITHIN SCOPE', None),
        GSDMDomainValue('contracts', 'C', 'FUNDING ONLY ACTION', None),
        GSDMDomainValue('contracts', 'D', 'CHANGE ORDER', None),
        GSDMDomainValue('contracts', 'E', 'TERMINATE FOR DEFAULT (COMPLETE OR PARTIAL)', None),
        GSDMDomainValue('contracts', 'F', 'TERMINATE FOR CONVENIENCE (COMPLETE OR PARTIAL)', None),
        GSDMDomainValue('contracts', 'G', 'EXERCISE AN OPTION', None),
        GSDMDomainValue('contracts', 'H', 'DEFINITIZE LETTER CONTRACT', None),
        GSDMDomainValue('contracts', 'J', 'NOVATION AGREEMENT', None),
        GSDMDomainValue('contracts', 'K', 'CLOSE OUT', None),
        GSDMDomainValue('contracts', 'L', 'DEFINITIZE CHANGE ORDER', None),
        GSDMDomainValue('contracts', 'M', 'OTHER ADMINISTRATIVE ACTION', None),
        GSDMDomainValue('contracts', 'N', 'LEGAL CONTRACT CANCELLATION', None),
        GSDMDomainValue('contracts', 'P', 'REREPRESENTATION OF NON-NOVATED MERGER/ACQUISITION', None),
        GSDMDomainValue('contracts', 'R', 'REREPRESENTATION', None),
        GSDMDomainValue('contracts', 'S', 'CHANGE PIID', None),
        GSDMDomainValue('contracts', 'T', 'TRANSFER ACTION', None),
        GSDMDomainValue('contracts', 'V', 'UNIQUE ENTITY ID (DUNS) OR LEGAL BUSINESS NAME CHANGE - NON-NOVATION', None),
        GSDMDomainValue('contracts', 'W', 'ENTITY ADDRESS CHANGE', None),
        GSDMDomainValue('contracts', 'X', 'TERMINATE FOR CAUSE', None),
        GSDMDomainValue('contracts', 'Y', 'ADD SUBCONTRACT PLAN', None),
    ),
)

GSDM_ASSISTANCE_TYPE = GSDMCrosswalkElement(
    gsdm_element='AssistanceType',
    definition='Code of the type of assistance provided by the award.',
    fpds_data_dictionary_element=None,
    grouping='Award Attribute',
    download_files=(
        GSDMFileElement('Assistance_PrimeAwardSummaries.csv', 'assistance_type_code'),
        GSDMFileElement('Assistance_PrimeTransactions.csv', 'assistance_type_code'),
    ),
    account_files=(
        GSDMFileElement('FA_AccountBreakdownByAward.csv', 'award_type_code'),
        GSDMFileElement('TAS_AccountBreakdownByAward.csv', 'award_type_code'),
    ),
    submission_tables=(
        GSDMFileElement('transaction_fabs', 'assistance_type'),
    ),
    award_category_fields=(
        GSDMFileElement('Assistance', 'assistance_type'),
    ),
    domain_values=(
        GSDMDomainValue('', '02', 'block grant (A)', 'Federal funds provided to a state or local government that the recipient may use at its discretion.'),
        GSDMDomainValue('', '03', 'formula grant (A)', 'Allocations of money to States or their subdivisions in accordance with distribution formulas prescribed by law or administrative regulation, for activities of a continuing nature not confined to a specific project.'),
        GSDMDomainValue('', '04', 'project grant (B)', 'The funding, for fixed or known periods, of specific projects. Project grants can include fellowships, scholarships, research grants, training grants, traineeships, experimental and demonstration grants, evaluation grants, planning grants, technical assistance grants, survey grants, and construction grants.'),
        GSDMDomainValue('', '05', 'cooperative agreement (B)', 'A legal instrument of financial assistance between a Federal awarding agency and a recipient or passthrough entity and a subrecipient that, consistent with 31 USC 6302-6305: (a) Is used to enter into a relationship the principal purpose of which is to …carry out a public purpose authorized by law ...; (b) Is distinguished from a grant in that it provides for substantial involvement of the Federal awarding agency ... See 2 CFR 200.1 (as adapted).'),
        GSDMDomainValue('', '06', 'direct payment for specified use, as a subsidy or other non-reimbursable direct financial aid (C)', 'Financial assistance from the Federal government provided directly to individuals, private firms, and other private institutions to encourage or subsidize a particular activity by conditioning the receipt of the assistance on a particular performance by the recipient. This does not include solicited contracts for the procurement of goods and services for the Federal government.'),
        GSDMDomainValue('', '07', 'direct loan (E)', 'Financial assistance provided through the lending of Federal monies for a specific period of time, with a reasonable expectation of repayment. Such loans may or may not require the payment of interest.'),
        GSDMDomainValue('', '08', 'guaranteed/insured loan (F)', 'Programs in which the Federal government makes an arrangement to indemnify a lender against part or all of any defaults by those responsible for repayment of loans.'),
        GSDMDomainValue('', '09', 'insurance (G)', 'Financial assistance provided to assure reimbursement for losses sustained under specified conditions. Coverage may be provided directly by the Federal government or through private carriers and may or may not involve the payment of premiums.'),
        GSDMDomainValue('', '10', 'direct payment with unrestricted use (retirement, pension, veterans benefits, etc.) (D)', 'Financial assistance from the Federal government provided directly to beneficiaries who satisfy Federal eligibility requirements with no restrictions being imposed on the recipient as to how the money is spent. Included are payments under retirement, pension, and compensatory programs.'),
        GSDMDomainValue('', '11', 'other reimbursable, contingent, intangible, or indirect financial assistance', 'Financial assistance from the Federal Government that is not described by any of the previously-defined assistance types.'),
    ),
)

GSDM_CONTRACT_AWARD_TYPE = GSDMCrosswalkElement(
    gsdm_element='ContractAwardType',
    definition='The type of award being entered by this transaction. Types of awards include Purchase Orders (PO), Delivery Orders (DO), Blanket Purchase Agreements (BPA) Calls and Definitive Contracts.',
    fpds_data_dictionary_element='Award Type',
    grouping='Award Attribute',
    download_files=(
        GSDMFileElement('Contracts_PrimeAwardSummaries.csv', 'award_type_code'),
        GSDMFileElement('Contracts_PrimeTransactions.csv', 'award_type_code'),
    ),
    account_files=(
        GSDMFileElement('FA_AccountBreakdownByAward.csv', 'award_type_code'),
        GSDMFileElement('TAS_AccountBreakdownByAward.csv', 'award_type_code'),
    ),
    submission_tables=(
        GSDMFileElement('transaction_fpds', 'contract_award_type'),
    ),
    award_category_fields=(
        GSDMFileElement('Contracts', 'contractactiontype'),
    ),
    domain_values=(
        GSDMDomainValue('', 'A', 'BPA Call', 'Enter this code for an award that is a call against a BPA.'),
        GSDMDomainValue('', 'B', 'Purchase Order', 'Enter this code for an award that is a Purchase Order (PO).'),
        GSDMDomainValue('', 'C', 'Delivery Order', 'Enter this code for an award that is a Delivery Order or Task Order under an IDV.'),
        GSDMDomainValue('', 'D', 'Definitive Contract', 'Enter this code for an award that is a Definitive Contract.'),
    ),
)

GSDM_SCHEMA_CROSSWALK_ELEMENTS = (
    GSDM_ACTION_TYPE,
    GSDM_ASSISTANCE_TYPE,
    GSDM_CONTRACT_AWARD_TYPE,
)


@dataclass(frozen=True, slots=True)
class GSDMDocumentPin:
    """Exact identity of the pinned GSDM architecture release."""

    version: str
    former_name: str
    title: str
    revision_date: str
    document_url: str
    expected_sha256: str
    expected_byte_length: int
    metadata_registry_attributes: tuple[str, ...]

    def __post_init__(self) -> None:
        if _VERSION.fullmatch(self.version) is None:
            raise USASpendingAcquisitionError("GSDM version must be a dotted major.minor.patch number")
        parsed = urlsplit(self.document_url)
        if parsed.scheme != "https" or parsed.hostname != "fiscal.treasury.gov":
            raise USASpendingAcquisitionError("GSDM document_url must be an official HTTPS fiscal.treasury.gov URL")
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise USASpendingAcquisitionError("GSDM expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise USASpendingAcquisitionError("GSDM expected_byte_length must be positive")
        if _ISO_DATE.fullmatch(self.revision_date) is None:
            raise USASpendingAcquisitionError("GSDM revision_date must be an ISO 8601 date")
        if not self.metadata_registry_attributes:
            raise USASpendingAcquisitionError("GSDM metadata_registry_attributes must not be empty")


GSDM_DOCUMENT = GSDMDocumentPin(
    version=GSDM_VERSION,
    former_name=GSDM_FORMER_NAME,
    title=GSDM_TITLE,
    revision_date=GSDM_REVISION_DATE,
    document_url=GSDM_DOCUMENT_URL,
    expected_sha256=GSDM_DOCUMENT_SHA256,
    expected_byte_length=GSDM_DOCUMENT_BYTE_LENGTH,
    metadata_registry_attributes=GSDM_METADATA_REGISTRY_ATTRIBUTES,
)

USASPENDING_GSDM_PORTFOLIO_GAPS = (
    (
        "The USAspending online data dictionary publishes 457 GSDM/DAIMS crosswalk "
        "elements. RefSpec retains every structural row and parses the publisher's "
        "Domain Values column across all of them (parse_gsdm_domain_values); the "
        "typed constants below additionally transcribe ActionType, AssistanceType, "
        "and ContractAwardType for the validation helpers. 86 elements defer their "
        "domains to external code sources the publisher only cites, and 168 publish "
        "no domain text; those domains are not enumerable from this document."
    ),
    (
        "Award type and assistance type codes are published twice with independent "
        "labels: once by the live /references/award_types/ endpoint (short labels) "
        "and once by the data dictionary's ContractAwardType and AssistanceType rows "
        "(fuller code descriptions). RefSpec preserves both without reconciling them."
    ),
    (
        "ActionType letter codes are reused across two unrelated domains (financial "
        "assistance vs. procurement) with different meanings; a bare code is "
        "meaningless without its domain_group qualifier."
    ),
    (
        "The GSDM architecture document is pinned by version, revision date, and "
        "digest; RefSpec does not parse its narrative text into codes, only its "
        "cited metadata-registry attribute names."
    ),
)


@dataclass(frozen=True, slots=True)
class USASpendingGSDMPortfolio:
    """The acquired award-type codes plus the pinned GSDM crosswalk elements."""

    award_types: ParsedAwardTypesResource
    schema_crosswalk_elements: tuple[GSDMCrosswalkElement, ...]
    gsdm_document: GSDMDocumentPin
    gaps: tuple[str, ...]

    def crosswalk_element(self, gsdm_element: str) -> GSDMCrosswalkElement:
        """Look up one pinned crosswalk element by its published name."""

        for element in self.schema_crosswalk_elements:
            if element.gsdm_element == gsdm_element:
                return element
        raise USASpendingSourceDriftError(f"no pinned GSDM crosswalk element named {gsdm_element!r}")


def assemble_usaspending_gsdm_portfolio(award_types: ParsedAwardTypesResource) -> USASpendingGSDMPortfolio:
    """Combine one acquired award-type resource with the pinned GSDM crosswalk."""

    return USASpendingGSDMPortfolio(
        award_types=award_types,
        schema_crosswalk_elements=GSDM_SCHEMA_CROSSWALK_ELEMENTS,
        gsdm_document=GSDM_DOCUMENT,
        gaps=USASPENDING_GSDM_PORTFOLIO_GAPS,
    )


def portfolio_digest(portfolio: USASpendingGSDMPortfolio) -> str:
    """Return a stable content digest for one assembled, closed portfolio."""

    plain = {
        "awardTypes": [
            {
                "category": entry.category,
                "label": entry.publisher_label,
                "identifiers": [identifier.as_dict() for identifier in entry.identifiers],
            }
            for entry in portfolio.award_types.codes
        ],
        "schemaCrosswalkElements": [
            {
                "gsdmElement": element.gsdm_element,
                "domainValues": [
                    {"domainGroup": value.domain_group, "code": value.code, "label": value.label}
                    for value in element.domain_values
                ],
            }
            for element in portfolio.schema_crosswalk_elements
        ],
        "gsdmVersion": portfolio.gsdm_document.version,
    }
    return sha256_digest(canonical_json(plain).encode("utf-8"))


@dataclass(frozen=True, slots=True)
class USASpendingCodeAssignment:
    """Code evidence retained from validating one source record's field."""

    source_field: str
    publisher_label: str
    category: str
    use: ResourceUse
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool


def validate_usaspending_award_type(
    record: Mapping[str, object],
    portfolio: USASpendingGSDMPortfolio,
    *,
    source_field: str = "type",
) -> USASpendingCodeAssignment:
    """Validate one award/transaction record's type code against the pinned codes."""

    raw_code = record.get(source_field)
    if not isinstance(raw_code, str):
        raise USASpendingAssignmentError(f"USAspending record must carry a string {source_field!r}")
    code = portfolio.award_types.by_code().get(raw_code)
    if code is None:
        raise USASpendingAssignmentError(f"unknown USAspending award/assistance type code {raw_code!r}")
    return USASpendingCodeAssignment(
        source_field=source_field,
        publisher_label=code.publisher_label,
        category=code.category,
        use=code.use,
        identifiers=code.identifiers,
        is_general_subject_concept=False,
    )


def validate_gsdm_action_type(
    record: Mapping[str, object],
    portfolio: USASpendingGSDMPortfolio,
    *,
    domain: Literal["assistance", "contracts"],
    source_field: str = "action_type_code",
) -> GSDMDomainValue:
    """Validate one transaction's action type code against its published domain."""

    if domain not in ("assistance", "contracts"):
        raise USASpendingAssignmentError(f"unsupported GSDM ActionType domain {domain!r}")
    raw_code = record.get(source_field)
    if not isinstance(raw_code, str):
        raise USASpendingAssignmentError(f"USAspending record must carry a string {source_field!r}")
    element = portfolio.crosswalk_element("ActionType")
    value = element.by_code(domain).get(raw_code)
    if value is None:
        raise USASpendingAssignmentError(f"unknown GSDM ActionType code {raw_code!r} for domain {domain!r}")
    return value
