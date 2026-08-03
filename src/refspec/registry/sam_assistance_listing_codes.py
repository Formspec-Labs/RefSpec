"""Pinned SAM.gov Assistance Listings assistance-type and eligibility code imports.

The official SAM.gov Assistance Listings API documentation
(open.gsa.gov/api/assistance-listings-api/) publishes, under one Reference
Data section, Assistance Type codes (Financial and Non-Financial), Eligible
Award Applicant Type codes, and Eligible Beneficiary Type codes as prose HTML
tables, plus a flattened Response Parameters data dictionary that names the
Assistance Listing Number (ALN) identity fields. All of these are the
program's own deterministic classification and identity metadata, not
general subject concepts. The catalog guidance for this source explicitly
carves out mission and subject values (overview.functionalCodes,
overview.missionSubCategories, overview.subjectTerms) as source evidence, not
governed subjects; this module does not parse or package them.

The documentation's own Change Log records exactly one entry: "v1.0" as the
"Base Version" dated 01/27/2026. The published request/response examples on
the same page disagree with the documented schema in several ways: the
example JSON carries an undocumented top-level "programId" field and a
record-level "version" of "2.0" that the Response Parameters dictionary does
not describe; one example's live request URL misspells the assistanceTypes
filter as "assitanceTypes"; and the Request Parameters table's own "Refer to"
links for applicantTypes and beneficiaryTypes point at each other's
reference-data section. RefSpec pins the documentation's own "v1.0" Change
Log entry as api_interface_version and preserves every observed
inconsistency as an unresolved gap rather than silently correcting it.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.controlled_identifier import (
    ControlledIdentifier,
    ControlledIdentifierError,
    validate_identifier_date,
)
from refspec.registry.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

SAM_ASSISTANCE_PUBLISHER = "U.S. General Services Administration — SAM.gov Assistance Listings API"
SAM_ASSISTANCE_IDENTIFIER_AUTHORITY_URI = "https://open.gsa.gov/"
SAM_ASSISTANCE_DOC_URL = "https://open.gsa.gov/api/assistance-listings-api/"
SAM_ASSISTANCE_DOC_ASSISTANCE_TYPES_ANCHOR = f"{SAM_ASSISTANCE_DOC_URL}#assistance-types-by-code"
SAM_ASSISTANCE_DOC_APPLICANT_TYPES_ANCHOR = f"{SAM_ASSISTANCE_DOC_URL}#eligible-award-applicant-types"
SAM_ASSISTANCE_DOC_BENEFICIARY_TYPES_ANCHOR = f"{SAM_ASSISTANCE_DOC_URL}#eligible-beneficiary-types"
SAM_ASSISTANCE_DOC_RESPONSE_PARAMETERS_ANCHOR = f"{SAM_ASSISTANCE_DOC_URL}#response-parameters"
# The documented production search endpoint; its own path segment ("v1") is a
# separate version marker from both the page's Change Log version and the
# record-level "version" field observed in the page's own examples.
SAM_ASSISTANCE_API_BASE_URL = "https://api.sam.gov/assistance-listings/v1/search"

# Exact HTML observed on 2026-08-03. The response Last-Modified header on that
# request was Wed, 28 Jan 2026 02:18:10 GMT, recorded below as
# publisher_last_modified; the page's own Change Log table records one entry,
# "v1.0" ("Base Version"), dated 01/27/2026.
SAM_ASSISTANCE_DOC_RETRIEVED_AT = "2026-08-03T19:28:13Z"
SAM_ASSISTANCE_DOC_SHA256 = "sha256:6ea76d040e2190b02cad8192f50dbe00d39f01f5366f893cd24b6491dfdeeffd"
SAM_ASSISTANCE_DOC_BYTE_LENGTH = 210_611
SAM_ASSISTANCE_API_INTERFACE_VERSION = "v1.0"

ResourceName = Literal["assistanceTypes", "eligibleApplicantTypes", "eligibleBeneficiaryTypes"]
AssistanceTypeCategory = Literal["financial", "nonFinancial"]
SAMAssistanceCodeUse = Literal["deterministicMetadata"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_ASSISTANCE_TYPE_CODE = re.compile(r"^[FN]\d{3}$")
_ENTITY_TYPE_CODE = re.compile(r"^ET\d{5}$")
_ALN = re.compile(r"^\d{2}\.\d{3}$")

_RESOURCE_COUNTS: Mapping[ResourceName, int] = {
    "assistanceTypes": 17,
    "eligibleApplicantTypes": 44,
    "eligibleBeneficiaryTypes": 73,
}


class SAMAssistanceListingCodeError(ValueError):
    """Base class for SAM.gov Assistance Listings controlled-code failures."""


class SAMAssistanceAcquisitionError(SAMAssistanceListingCodeError):
    """Exact official documentation bytes could not be acquired safely."""


class SAMAssistanceSourceDriftError(SAMAssistanceListingCodeError):
    """The SAM.gov documentation no longer matches the reviewed structure or pin."""


class SAMAssistanceAssignmentError(SAMAssistanceListingCodeError):
    """A submitted listing record carries an unknown or inconsistent value."""


class SAMAssistancePackageError(SAMAssistanceListingCodeError):
    """A SAM.gov controlled-code package is incomplete or inconsistent."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_datetime(value: str, field: str) -> str:
    try:
        return validate_identifier_date(value, field)
    except ControlledIdentifierError as error:
        raise SAMAssistanceAcquisitionError(str(error)) from error


@dataclass(frozen=True, slots=True)
class SAMAssistanceListingDocSource:
    """The one official documentation page publishing these controlled codes."""

    source_url: str = SAM_ASSISTANCE_DOC_URL
    filename: str = "assistance-listings-api.html"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "open.gsa.gov":
            raise SAMAssistanceAcquisitionError("source_url must be an official HTTPS open.gsa.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise SAMAssistanceAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise SAMAssistanceAcquisitionError("filename must be one plain path component")


SAM_ASSISTANCE_DOC_SOURCE = SAMAssistanceListingDocSource()


@dataclass(frozen=True, slots=True)
class SAMAssistanceSnapshotPin:
    """Exact identity of one official documentation response."""

    source: SAMAssistanceListingDocSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    publisher_last_modified: str | None = None
    api_interface_version: str = SAM_ASSISTANCE_API_INTERFACE_VERSION

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise SAMAssistanceAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise SAMAssistanceAcquisitionError("expected_byte_length must be positive")
        if not self.api_interface_version:
            raise SAMAssistanceAcquisitionError("api_interface_version must not be empty")
        _require_datetime(self.retrieved_at, "retrieved_at")
        if self.publisher_last_modified is not None:
            _require_datetime(self.publisher_last_modified, "publisher_last_modified")


SAM_ASSISTANCE_DOC_2026_08_03 = SAMAssistanceSnapshotPin(
    source=SAM_ASSISTANCE_DOC_SOURCE,
    retrieved_at=SAM_ASSISTANCE_DOC_RETRIEVED_AT,
    expected_sha256=SAM_ASSISTANCE_DOC_SHA256,
    expected_byte_length=SAM_ASSISTANCE_DOC_BYTE_LENGTH,
    publisher_last_modified="2026-01-28T02:18:10Z",
)


@dataclass(frozen=True, slots=True)
class FetchedSAMAssistanceResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class SAMAssistanceFetcher(Protocol):
    """Small transport boundary for the official SAM.gov documentation page."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedSAMAssistanceResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredSAMAssistanceSource:
    """One verified source object in the content-addressed store."""

    pin: SAMAssistanceSnapshotPin
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
class SAMAssistanceCode:
    """One exact publisher-documented code and label from one reference table."""

    resource_name: ResourceName
    use: SAMAssistanceCodeUse
    publisher_label: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    category: AssistanceTypeCategory | None = None
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class SAMAssistanceListingIdentityField:
    """One documented ALN identity field name from the Response Parameters dictionary."""

    field_path: str
    description: str
    data_type: str
    data_specification_version: str


@dataclass(frozen=True, slots=True)
class SAMAssistanceListingCodePortfolio:
    """A parsed, digest-pinned SAM.gov Assistance Listings controlled-code capture."""

    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    source_url: str
    publisher_last_modified: str | None
    api_interface_version: str
    assistance_types: tuple[SAMAssistanceCode, ...]
    eligible_applicant_types: tuple[SAMAssistanceCode, ...]
    eligible_beneficiary_types: tuple[SAMAssistanceCode, ...]
    identity_fields: tuple[SAMAssistanceListingIdentityField, ...]
    gaps: tuple[str, ...]

    def assistance_types_by_code(self) -> dict[str, SAMAssistanceCode]:
        """Index every Assistance Type code across both Financial and Non-Financial tables."""

        return _index_by_code(self.assistance_types)

    def eligible_applicant_types_by_code(self) -> dict[str, SAMAssistanceCode]:
        """Index every documented Eligible Award Applicant Type code."""

        return _index_by_code(self.eligible_applicant_types)

    def eligible_beneficiary_types_by_code(self) -> dict[str, SAMAssistanceCode]:
        """Index every documented Eligible Beneficiary Type code."""

        return _index_by_code(self.eligible_beneficiary_types)


SAM_ASSISTANCE_PORTFOLIO_GAPS = (
    (
        "Example response payloads on this page carry an undocumented top-level "
        "'programId' field and a record-level 'version' of '2.0'; neither appears "
        "in the Response Parameters data dictionary, whose own 'Versions' key "
        "states values are 'All' unless explicitly marked (e.g., v1.0). This "
        "capture pins the Change Log's single documented 'v1.0' Base Version as "
        "api_interface_version and does not resolve the discrepancy with the "
        "live '2.0' record version or the undocumented field."
    ),
    (
        "Example 2's live request URL misspells the assistanceTypes filter as "
        "'assitanceTypes' and capitalizes the status parameter as "
        "'Status=ACTIVE'; the Request Parameters table documents 'assistanceTypes' "
        "and a status value of 'Active'. This capture preserves the documented "
        "spelling only."
    ),
    (
        "The Request Parameters table's own descriptions state that "
        "'beneficiaryTypes' refers to 'Eligible Award Applicant Types' and "
        "'applicantTypes' refers to 'Eligible Beneficiary Types' -- the reverse "
        "of the binding shown in the Response Parameters schema, where "
        "criteriaForApplying.applicant.types[].code is Eligible Award Applicant "
        "Types and criteriaForApplying.beneficiary.types[].code is Eligible "
        "Beneficiary Types. This capture follows the Response Parameters "
        "schema binding and preserves the Request Parameters wording as-is in "
        "documentation only."
    ),
    (
        "criteriaForApplying.assistanceRestriction.types[].code and "
        "criteriaForApplying.assistanceUsage.types[].code are documented "
        "response fields with no corresponding code list published anywhere on "
        "this page; RefSpec does not capture a controlled list for either field."
    ),
    (
        "overview.functionalCodes, overview.missionSubCategories, and "
        "overview.subjectTerms are source evidence per catalog guidance, not "
        "governed subjects; this module does not parse or package them."
    ),
)


def _index_by_code(codes: tuple[SAMAssistanceCode, ...]) -> dict[str, SAMAssistanceCode]:
    result: dict[str, SAMAssistanceCode] = {}
    for entry in codes:
        result[entry.identifiers[0].value] = entry
    return result


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "open.gsa.gov":
        raise SAMAssistanceAcquisitionError("fetcher resolved_url must remain on official HTTPS open.gsa.gov")
    if parsed.username is not None or parsed.password is not None:
        raise SAMAssistanceAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: SAMAssistanceSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise SAMAssistanceSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise SAMAssistanceSourceDriftError(
            f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SAMAssistanceSourceDriftError(f"{location} is not valid UTF-8 HTML") from error
    if not text.lstrip().lower().startswith("<!doctype html"):
        raise SAMAssistanceSourceDriftError(f"{location} does not open with an HTML doctype")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: SAMAssistanceSnapshotPin) -> AcquiredSAMAssistanceSource:
    if path.is_symlink() or not path.is_file():
        raise SAMAssistanceAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached SAM.gov source",
    )
    return AcquiredSAMAssistanceSource(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type="text/html",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: SAMAssistanceSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredSAMAssistanceSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} SAM.gov source",
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
        return AcquiredSAMAssistanceSource(
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


def acquire_sam_assistance_listing_doc(
    pin: SAMAssistanceSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: SAMAssistanceFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredSAMAssistanceSource:
    """Acquire the exact documentation response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise SAMAssistanceAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise SAMAssistanceAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise SAMAssistanceAcquisitionError(f"local SAM.gov source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="text/html",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise SAMAssistanceAcquisitionError(
            "SAM.gov documentation is not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise SAMAssistanceAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "text/html":
        raise SAMAssistanceSourceDriftError(f"SAM.gov documentation content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _section_after_heading(text: str, heading_id: str) -> str:
    """Return the HTML between one heading (any level) and the next heading of any level."""

    match = re.search(rf'<h[1-6][^>]*id="{re.escape(heading_id)}"[^>]*>', text)
    if match is None:
        raise SAMAssistanceSourceDriftError(f"could not locate the {heading_id!r} section")
    rest = text[match.end() :]
    next_heading = re.search(r'<h[1-6][^>]*id="', rest)
    return rest[: next_heading.start()] if next_heading else rest


def _table_rows(section: str) -> list[tuple[str, str]]:
    match = re.search(r"<table>(.*?)</table>", section, re.DOTALL)
    if match is None:
        raise SAMAssistanceSourceDriftError("expected section did not contain a code table")
    raw_rows = re.findall(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", match.group(1), re.DOTALL)
    return [(html.unescape(code).strip(), html.unescape(label).strip()) for code, label in raw_rows]


def _identifier(
    value: str,
    kind: str,
    source_uri: str,
    acquired: AcquiredSAMAssistanceSource,
) -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=kind,
        authority_uri=SAM_ASSISTANCE_IDENTIFIER_AUTHORITY_URI,
        source_uri=source_uri,
        observed_at=acquired.pin.retrieved_at,
        effective_at=None,
        source_digest=acquired.sha256,
    )


def _parse_assistance_type_table(
    text: str,
    heading_id: str,
    category: AssistanceTypeCategory,
    acquired: AcquiredSAMAssistanceSource,
) -> tuple[SAMAssistanceCode, ...]:
    rows = _table_rows(_section_after_heading(text, heading_id))
    codes: list[SAMAssistanceCode] = []
    for code, label in rows:
        if _ASSISTANCE_TYPE_CODE.fullmatch(code) is None:
            raise SAMAssistanceSourceDriftError(f"malformed assistance type code in {heading_id!r}: {code!r}")
        if not label:
            raise SAMAssistanceSourceDriftError(f"assistance type code {code!r} has an empty label")
        codes.append(
            SAMAssistanceCode(
                resource_name="assistanceTypes",
                use="deterministicMetadata",
                publisher_label=label,
                source_url=SAM_ASSISTANCE_DOC_ASSISTANCE_TYPES_ANCHOR,
                category=category,
                identifiers=(_identifier(code, "assistanceTypeCode", SAM_ASSISTANCE_DOC_ASSISTANCE_TYPES_ANCHOR, acquired),),
            )
        )
    return tuple(codes)


def _parse_entity_type_table(
    text: str,
    heading_id: str,
    resource_name: ResourceName,
    source_url: str,
    identifier_kind: str,
    acquired: AcquiredSAMAssistanceSource,
) -> tuple[SAMAssistanceCode, ...]:
    rows = _table_rows(_section_after_heading(text, heading_id))
    codes: list[SAMAssistanceCode] = []
    for code, label in rows:
        if _ENTITY_TYPE_CODE.fullmatch(code) is None:
            raise SAMAssistanceSourceDriftError(f"malformed entity type code in {heading_id!r}: {code!r}")
        if not label:
            raise SAMAssistanceSourceDriftError(f"entity type code {code!r} has an empty label")
        codes.append(
            SAMAssistanceCode(
                resource_name=resource_name,
                use="deterministicMetadata",
                publisher_label=label,
                source_url=source_url,
                identifiers=(_identifier(code, identifier_kind, source_url, acquired),),
            )
        )
    if len({code.identifiers[0].value for code in codes}) != len(codes):
        raise SAMAssistanceSourceDriftError(f"{heading_id!r} table contains a duplicate publisher code")
    return tuple(codes)


def _parse_identity_fields(text: str) -> tuple[SAMAssistanceListingIdentityField, ...]:
    section = _section_after_heading(text, "assistancelistingsdata-root")
    match = re.search(r"<table>(.*?)</table>", section, re.DOTALL)
    if match is None:
        raise SAMAssistanceSourceDriftError("could not locate the assistanceListingsData (Root) field table")
    raw_rows = re.findall(
        r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>",
        match.group(1),
        re.DOTALL,
    )
    fields = tuple(
        SAMAssistanceListingIdentityField(
            field_path=html.unescape(path).strip(),
            description=html.unescape(description).strip(),
            data_type=html.unescape(data_type).strip(),
            data_specification_version=html.unescape(version).strip(),
        )
        for path, description, data_type, version in raw_rows
    )
    required_fields = {
        "assistanceListingsData[].assistanceListingId",
        "assistanceListingsData[].title",
        "assistanceListingsData[].version",
        "assistanceListingsData[].status",
        "assistanceListingsData[].fiscalYear",
        "assistanceListingsData[].publishedDate",
    }
    observed_paths = {field.field_path for field in fields}
    if not required_fields.issubset(observed_paths):
        raise SAMAssistanceSourceDriftError(
            f"assistanceListingsData (Root) field table lost required identity fields: "
            f"{sorted(required_fields - observed_paths)}"
        )
    return fields


def parse_sam_assistance_listing_codes(acquired: AcquiredSAMAssistanceSource) -> SAMAssistanceListingCodePortfolio:
    """Parse exact publisher prose into three controlled code families plus identity fields."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed SAM.gov source")
    text = payload.decode("utf-8")

    financial = _parse_assistance_type_table(text, "financial-assistance", "financial", acquired)
    non_financial = _parse_assistance_type_table(text, "non-financial-assistance", "nonFinancial", acquired)
    assistance_types = financial + non_financial
    if len(assistance_types) != _RESOURCE_COUNTS["assistanceTypes"]:
        raise SAMAssistanceSourceDriftError(
            f"assistance type count drift: expected {_RESOURCE_COUNTS['assistanceTypes']}, "
            f"parsed {len(assistance_types)}"
        )
    if len({code.identifiers[0].value for code in assistance_types}) != len(assistance_types):
        raise SAMAssistanceSourceDriftError("assistance type tables contain a duplicate publisher code")

    applicant_types = _parse_entity_type_table(
        text,
        "eligible-award-applicant-types",
        "eligibleApplicantTypes",
        SAM_ASSISTANCE_DOC_APPLICANT_TYPES_ANCHOR,
        "applicantEntityTypeCode",
        acquired,
    )
    if len(applicant_types) != _RESOURCE_COUNTS["eligibleApplicantTypes"]:
        raise SAMAssistanceSourceDriftError(
            f"eligible applicant type count drift: expected {_RESOURCE_COUNTS['eligibleApplicantTypes']}, "
            f"parsed {len(applicant_types)}"
        )

    beneficiary_types = _parse_entity_type_table(
        text,
        "eligible-beneficiary-types",
        "eligibleBeneficiaryTypes",
        SAM_ASSISTANCE_DOC_BENEFICIARY_TYPES_ANCHOR,
        "beneficiaryEntityTypeCode",
        acquired,
    )
    if len(beneficiary_types) != _RESOURCE_COUNTS["eligibleBeneficiaryTypes"]:
        raise SAMAssistanceSourceDriftError(
            f"eligible beneficiary type count drift: expected {_RESOURCE_COUNTS['eligibleBeneficiaryTypes']}, "
            f"parsed {len(beneficiary_types)}"
        )

    identity_fields = _parse_identity_fields(text)

    return SAMAssistanceListingCodePortfolio(
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        source_url=acquired.pin.source.source_url,
        publisher_last_modified=acquired.pin.publisher_last_modified,
        api_interface_version=acquired.pin.api_interface_version,
        assistance_types=assistance_types,
        eligible_applicant_types=applicant_types,
        eligible_beneficiary_types=beneficiary_types,
        identity_fields=identity_fields,
        gaps=SAM_ASSISTANCE_PORTFOLIO_GAPS,
    )


@dataclass(frozen=True, slots=True)
class ValidatedAssistanceListingRecord:
    """Identity and code evidence retained from one submitted assistance-listing record."""

    assistance_listing_id: str
    title: str
    status: str
    assistance_types: tuple[SAMAssistanceCode, ...]
    applicant_types: tuple[SAMAssistanceCode, ...]
    beneficiary_types: tuple[SAMAssistanceCode, ...]
    gaps: tuple[str, ...]


def _require_non_empty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SAMAssistanceAssignmentError(f"assistance listing record must carry a non-empty string {field}")
    return value


def _validate_type_assignments(
    raw_entries: object,
    *,
    field: str,
    portfolio_by_code: Mapping[str, SAMAssistanceCode],
) -> tuple[SAMAssistanceCode, ...]:
    if raw_entries is None:
        return ()
    if not isinstance(raw_entries, list):
        raise SAMAssistanceAssignmentError(f"{field} must be an array")
    resolved: list[SAMAssistanceCode] = []
    for ordinal, entry in enumerate(raw_entries):
        if not isinstance(entry, Mapping):
            raise SAMAssistanceAssignmentError(f"{field}[{ordinal}] must be an object")
        raw_code = entry.get("code")
        raw_name = entry.get("name")
        if not isinstance(raw_code, str):
            raise SAMAssistanceAssignmentError(f"{field}[{ordinal}] must carry a string code")
        source_code = portfolio_by_code.get(raw_code)
        if source_code is None:
            raise SAMAssistanceAssignmentError(f"{field}[{ordinal}] has unknown code {raw_code!r}")
        if raw_name is not None and raw_name != source_code.publisher_label:
            raise SAMAssistanceAssignmentError(
                f"{field}[{ordinal}] display mismatch for {raw_code}: "
                f"expected {source_code.publisher_label!r}, got {raw_name!r}"
            )
        resolved.append(source_code)
    return tuple(resolved)


def validate_assistance_listing_record(
    record: Mapping[str, object],
    portfolio: SAMAssistanceListingCodePortfolio,
) -> ValidatedAssistanceListingRecord:
    """Validate one submitted listing's ALN identity and every embedded code assignment.

    The Assistance Listing ID (ALN) is the publisher's own program key; it is
    not drawn from a bounded code list, so this only validates its documented
    NN.NNN shape and does not mint or look up an identifier for it.
    """

    raw_aln = record.get("assistanceListingId")
    if not isinstance(raw_aln, str) or _ALN.fullmatch(raw_aln) is None:
        raise SAMAssistanceAssignmentError(
            f"assistanceListingId must match the documented NN.NNN ALN shape, got {raw_aln!r}"
        )
    title = _require_non_empty_str(record.get("title"), "title")
    status = _require_non_empty_str(record.get("status"), "status")
    if status not in {"Active", "Inactive"}:
        raise SAMAssistanceAssignmentError(f"status must be 'Active' or 'Inactive', got {status!r}")

    financial_information = record.get("financialInformation")
    obligations = financial_information.get("obligations") if isinstance(financial_information, Mapping) else None
    assistance_type_entries = (
        [entry.get("assistanceType") for entry in obligations if isinstance(entry, Mapping)]
        if isinstance(obligations, list)
        else None
    )
    assistance_types = _validate_type_assignments(
        assistance_type_entries,
        field="financialInformation.obligations[].assistanceType",
        portfolio_by_code=portfolio.assistance_types_by_code(),
    )

    criteria = record.get("criteriaForApplying")
    applicant = criteria.get("applicant") if isinstance(criteria, Mapping) else None
    beneficiary = criteria.get("beneficiary") if isinstance(criteria, Mapping) else None
    applicant_types = _validate_type_assignments(
        applicant.get("types") if isinstance(applicant, Mapping) else None,
        field="criteriaForApplying.applicant.types",
        portfolio_by_code=portfolio.eligible_applicant_types_by_code(),
    )
    beneficiary_types = _validate_type_assignments(
        beneficiary.get("types") if isinstance(beneficiary, Mapping) else None,
        field="criteriaForApplying.beneficiary.types",
        portfolio_by_code=portfolio.eligible_beneficiary_types_by_code(),
    )

    return ValidatedAssistanceListingRecord(
        assistance_listing_id=raw_aln,
        title=title,
        status=status,
        assistance_types=assistance_types,
        applicant_types=applicant_types,
        beneficiary_types=beneficiary_types,
        gaps=portfolio.gaps,
    )


def _package_observations(
    resource_name: ResourceName,
    codes: tuple[SAMAssistanceCode, ...],
    acquired: AcquiredSAMAssistanceSource,
) -> tuple[Mapping[str, Any], ...]:
    observations: list[Mapping[str, Any]] = []
    for ordinal, code in enumerate(codes):
        identifier = code.identifiers[0]
        source_path = f"$.{resource_name}.{identifier.value}"
        identifier_payload = {
            "value": identifier.value,
            "kind": identifier.kind,
            "authorityUri": identifier.authority_uri,
            "sourceUri": identifier.source_uri,
            "sourcePath": source_path,
            "observedAt": identifier.observed_at,
            "sourceDigest": identifier.source_digest,
        }
        identity = {
            "resourceName": resource_name,
            "sourceArtifact": acquired.pin.source.source_url,
            "sourcePath": source_path,
            "value": identifier.value,
        }
        observation_id = (
            "urn:ref:source-observation:sam-assistance-listings:"
            + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        )
        observations.append(
            {
                "id": observation_id,
                "sourceArtifact": acquired.pin.source.source_url,
                "sourcePath": source_path,
                # This ordinal is a source locator only; publisher identity is
                # preserved in identifiers and never derived from row order.
                "sourceOrdinal": ordinal,
                "labels": [
                    {
                        "value": code.publisher_label,
                        "language": "en",
                        "role": "preferred",
                    }
                ],
                "identifiers": [identifier_payload],
                "eligibleUses": [code.use],
                "conceptIdentityClaimed": False,
                "category": code.category,
            }
        )
    return tuple(observations)


def build_sam_assistance_listing_code_package(
    resource_name: ResourceName,
    portfolio: SAMAssistanceListingCodePortfolio,
    acquired: AcquiredSAMAssistanceSource,
) -> SourceControlledResourceBundle:
    """Build one development-only, deterministic closed package for one code family."""

    codes_by_resource: Mapping[ResourceName, tuple[SAMAssistanceCode, ...]] = {
        "assistanceTypes": portfolio.assistance_types,
        "eligibleApplicantTypes": portfolio.eligible_applicant_types,
        "eligibleBeneficiaryTypes": portfolio.eligible_beneficiary_types,
    }
    if resource_name not in codes_by_resource:
        raise SAMAssistancePackageError(f"unknown SAM.gov Assistance Listings resource family {resource_name!r}")
    codes = codes_by_resource[resource_name]
    payload = acquired.path.read_bytes()
    captured_date = portfolio.retrieved_at[:10]
    return build_source_controlled_resource_bundle(
        resource_id=f"sam-assistance-listings-{resource_name}-{captured_date}",
        title=f"SAM.gov Assistance Listings {resource_name}, captured {captured_date}",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("deterministicMetadata",),
        captured_at=portfolio.retrieved_at,
        candidate_use_authorized=True,
        observations=_package_observations(resource_name, codes, acquired),
        source_artifacts={acquired.pin.source.source_url: payload},
        source_observed_count=len(codes),
        gaps=[{"kind": "sourceProseOnly", "reason": gap} for gap in portfolio.gaps],
    )


__all__ = [
    "SAM_ASSISTANCE_DOC_2026_08_03",
    "SAM_ASSISTANCE_DOC_SOURCE",
    "SAM_ASSISTANCE_IDENTIFIER_AUTHORITY_URI",
    "SAM_ASSISTANCE_PORTFOLIO_GAPS",
    "SAM_ASSISTANCE_PUBLISHER",
    "AcquiredSAMAssistanceSource",
    "AssistanceTypeCategory",
    "FetchedSAMAssistanceResponse",
    "ResourceName",
    "SAMAssistanceAcquisitionError",
    "SAMAssistanceAssignmentError",
    "SAMAssistanceCode",
    "SAMAssistanceFetcher",
    "SAMAssistanceListingCodeError",
    "SAMAssistanceListingCodePortfolio",
    "SAMAssistanceListingDocSource",
    "SAMAssistanceListingIdentityField",
    "SAMAssistancePackageError",
    "SAMAssistanceSnapshotPin",
    "SAMAssistanceSourceDriftError",
    "ValidatedAssistanceListingRecord",
    "acquire_sam_assistance_listing_doc",
    "build_sam_assistance_listing_code_package",
    "parse_sam_assistance_listing_codes",
    "sha256_digest",
    "validate_assistance_listing_record",
]
