"""Pinned OMB Circular A-11 fiscal code captures.

OMB Circular A-11 states budget functions, object classes, and apportionment
categories inside one large narrative PDF, not a machine-readable code-list
API. This module captures three closed, named tables from that PDF:

* Exhibit 79A (Functional Classification) -- 3-digit budget function codes
  and their subordinate 3-digit subfunction codes.
* Exhibit 83A (Object Classification, Schedule O) -- Schedule O object-class
  line codes, plus the Appendix ``NN.N`` form the Circular itself derives
  from each one (section 83.7: drop the direct/reimbursable placeholder
  digit, insert a decimal before the last digit). RefSpec mints neither form;
  both are read directly from the publisher's own stated rule.
* Section 120.13 -- apportionment category codes (A, B, AB, C) with their
  documented Application-of-Budgetary-Resources line ranges, and the four
  non-apportioned line codes (6180-6183).

Every page carries the publisher's own fiscal-year edition stamp ("OMB
Circular No. A-11 (YYYY)"). Record parsing requires that stamp to match the
pinned edition exactly; codes read under a different edition are a different
fact and a later, differently dated pin is required to capture them -- this
module never merges two editions into one portfolio.

The full circular is a roughly 15 MB, 900+ page PDF. RefSpec does not embed
that file as a test fixture or re-derive table text from it at import time.
Instead each pin fixes the exact plain-text extraction of the one page that
states a code family -- the smallest artifact that still carries source-
verifiable bytes -- and cites the full document's own URL, SHA-256, byte
length, and publisher Last-Modified date as reference-only provenance for
where that page extract came from. Acquisition of the page extract itself
accepts a local exact capture or an injected fetcher. Importing this module
never opens a network connection.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.controlled_identifier import ControlledIdentifier

OMB_PUBLISHER = "Office of Management and Budget"
OMB_A11_IDENTIFIER_AUTHORITY_URI = "https://www.whitehouse.gov/omb/"
OMB_A11_CIRCULARS_INDEX_URL = "https://www.whitehouse.gov/omb/information-resources/guidance/circulars/"
OMB_A11_DOCUMENT_URL = "https://www.whitehouse.gov/wp-content/uploads/2025/08/a11.pdf"
OMB_A11_EDITION_2025 = "OMB Circular No. A–11 (2025)"

# Reference-only identity of the full circular the three pinned pages below
# were extracted from. Captured 2026-08-03; the module never re-fetches or
# re-parses this full document at runtime.
OMB_A11_DOCUMENT_SHA256 = "sha256:7b0e6a3b018f6beea1c4b55ff377821fbd16def96354df5b319b2642ecd604c1"
OMB_A11_DOCUMENT_BYTE_LENGTH = 15_124_998
OMB_A11_DOCUMENT_RETRIEVED_AT = "2026-08-03T19:18:00Z"
OMB_A11_DOCUMENT_LAST_MODIFIED = "2025-09-29T18:28:49Z"

ResourceName = Literal["functionalClassification", "objectClassification", "apportionmentCategories"]
ResourceUse = Literal["deterministicMetadata"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_PAGE_HEADER_LINE = re.compile(r"^Page\s+\d+\s+of\s+Section\s+\d+\s+OMB Circular No\.\s*A.11\s*\(\d{4}\)$")
_EDITION_ANYWHERE = re.compile(r"OMB Circular No\.\s*A.11\s*\(\d{4}\)")
_FUNCTION_LINE = re.compile(r"^(\d{3})(?:[–-](\d{3}))?\s+(\S.*)$")
_OBJECT_LINE = re.compile(r"^([X9])(\d{3})\s+(\S.*)$")
_THROUGH = r"t\s*h\s*r\s*o\s*u\s*g\s*h|thru"
_CATEGORY_LINE = re.compile(
    r"Category (AB|A|B|C) apportions budgetary resources (.+?)\.\s*"
    rf".*?Lines? (\d{{4}}) (?:{_THROUGH}) (\d{{4}})"
)
_NONAPPORTIONED_START = "non-apportioned budgetary resources are shown using one of four apportionment lines"
_NONAPPORTIONED_END = "Agencies must report"
_NONAPPORTIONED_LINE = re.compile(r"(\d{4}), (.+?)(?=\s\d{4}, |$)")

_FUNCTION_NOISE = frozenset(
    {
        "EXHIBIT 79A        THE BUDGET DATA SYSTEM",
        "Functional Classification",
        "MULTIPLE FUNCTIONS",
    }
)
_OBJECT_NOISE = frozenset(
    {
        "EXHIBIT 83A OBJECT CLASSIFICATION (MAX SCHEDULE O)",
        "Standard Titles",
        "Personnel compensation and benefits",
        "Personnel compensation",
        "Contractual services and supplies",
        "Rent, communications, and utilities",
        "Other contractual services",
        "Acquisition of assets",
        "Grants and fixed charges",
        "Other",
    }
)


class OMBA11ResourceError(ValueError):
    """Base class for OMB Circular A-11 fiscal-code failures."""


class OMBA11AcquisitionError(OMBA11ResourceError):
    """Exact official page bytes could not be acquired safely."""


class OMBA11SourceDriftError(OMBA11ResourceError):
    """A pinned page no longer matches the reviewed edition, shape, or count."""


class OMBA11AssignmentError(OMBA11ResourceError):
    """A fiscal record carries an unknown, mismatched, or off-edition code."""


@dataclass(frozen=True, slots=True)
class OMBA11PageSource:
    """One official OMB Circular A-11 page that states a closed code family."""

    resource_name: ResourceName
    exhibit_citation: str
    document_url: str
    pdf_page: int
    printed_page_label: str
    filename: str
    expected_code_count: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.document_url)
        if parsed.scheme != "https" or parsed.hostname != "www.whitehouse.gov":
            raise OMBA11AcquisitionError("document_url must be an official HTTPS whitehouse.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise OMBA11AcquisitionError("document_url must not contain credentials")
        if self.pdf_page < 0:
            raise OMBA11AcquisitionError("pdf_page must be a non-negative 0-indexed page ordinal")
        if not self.exhibit_citation.strip() or not self.printed_page_label.strip():
            raise OMBA11AcquisitionError("exhibit_citation and printed_page_label must not be empty")
        if not self.filename or Path(self.filename).name != self.filename:
            raise OMBA11AcquisitionError("filename must be one plain path component")
        if self.expected_code_count <= 0:
            raise OMBA11AcquisitionError("expected_code_count must be positive")


OMB_A11_FUNCTIONAL_CLASSIFICATION_SOURCE = OMBA11PageSource(
    resource_name="functionalClassification",
    exhibit_citation="Exhibit 79A",
    document_url=OMB_A11_DOCUMENT_URL,
    pdf_page=177,
    printed_page_label="Page 10 of Section 79",
    filename="exhibit-79a-functional-classification-2025.txt",
    expected_code_count=98,
)
OMB_A11_OBJECT_CLASSIFICATION_SOURCE = OMBA11PageSource(
    resource_name="objectClassification",
    exhibit_citation="Exhibit 83A",
    document_url=OMB_A11_DOCUMENT_URL,
    pdf_page=277,
    printed_page_label="Page 32 of Section 83",
    filename="exhibit-83a-object-classification-2025.txt",
    expected_code_count=38,
)
OMB_A11_APPORTIONMENT_CATEGORIES_SOURCE = OMBA11PageSource(
    resource_name="apportionmentCategories",
    exhibit_citation="Section 120.13",
    document_url=OMB_A11_DOCUMENT_URL,
    pdf_page=407,
    printed_page_label="Page 10 of Section 120",
    filename="section-120-13-apportionment-categories-2025.txt",
    expected_code_count=8,
)


@dataclass(frozen=True, slots=True)
class OMBA11PageSnapshotPin:
    """Exact identity of one official page-extract capture."""

    source: OMBA11PageSource
    retrieved_at: str
    edition: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise OMBA11AcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise OMBA11AcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip() or not self.edition.strip():
            raise OMBA11AcquisitionError("retrieved_at and edition must not be empty")


OMB_A11_FUNCTIONAL_CLASSIFICATION_2025 = OMBA11PageSnapshotPin(
    source=OMB_A11_FUNCTIONAL_CLASSIFICATION_SOURCE,
    retrieved_at=OMB_A11_DOCUMENT_RETRIEVED_AT,
    edition=OMB_A11_EDITION_2025,
    expected_sha256="sha256:0a8f141ffbbd83b4d9de7e099249ff6eb4eed53c688b14afbde3e9a2f0e496bb",
    expected_byte_length=3_635,
)
OMB_A11_OBJECT_CLASSIFICATION_2025 = OMBA11PageSnapshotPin(
    source=OMB_A11_OBJECT_CLASSIFICATION_SOURCE,
    retrieved_at=OMB_A11_DOCUMENT_RETRIEVED_AT,
    edition=OMB_A11_EDITION_2025,
    expected_sha256="sha256:3714b8b88982f87dc491061d316bc89dbc2151a97b3aa7b3add1726738b4b325",
    expected_byte_length=1_886,
)
OMB_A11_APPORTIONMENT_CATEGORIES_2025 = OMBA11PageSnapshotPin(
    source=OMB_A11_APPORTIONMENT_CATEGORIES_SOURCE,
    retrieved_at=OMB_A11_DOCUMENT_RETRIEVED_AT,
    edition=OMB_A11_EDITION_2025,
    expected_sha256="sha256:e0e4f4d718add1b21d5106f454e45e3c30a0a5896a964032b3dc249b1aeb871a",
    expected_byte_length=3_377,
)


@dataclass(frozen=True, slots=True)
class FetchedOMBA11Page:
    """Provider-independent page-extract response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class OMBA11Fetcher(Protocol):
    """Small transport boundary for one official page-extract capture."""

    def fetch(self, document_url: str, *, timeout_seconds: float) -> FetchedOMBA11Page:
        """Fetch one page-extract response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredOMBA11Page:
    """One verified page-extract object in the content-addressed store."""

    pin: OMBA11PageSnapshotPin
    path: Path
    sha256: str
    byte_length: int
    document_url: str
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


@dataclass(frozen=True, slots=True)
class OMBA11Code:
    """One exact publisher label plus every identifier retained for that row."""

    resource_name: ResourceName
    use: ResourceUse
    category: str
    fiscal_year_edition: str
    publisher_label: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedOMBA11Resource:
    """A parsed, digest-pinned OMB Circular A-11 code table."""

    source: OMBA11PageSource
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    fiscal_year_edition: str
    codes: tuple[OMBA11Code, ...]
    gaps: tuple[str, ...]

    def by_code(self, *, kind: str | None = None) -> dict[str, OMBA11Code]:
        """Index identifiers of one kind, or each row's primary identifier."""

        result: dict[str, OMBA11Code] = {}
        for entry in self.codes:
            candidates = (
                [identifier for identifier in entry.identifiers if identifier.kind == kind]
                if kind is not None
                else entry.identifiers[:1]
            )
            for identifier in candidates:
                if identifier.value in result:
                    raise OMBA11SourceDriftError(
                        f"{self.source.resource_name} repeats publisher code {identifier.value!r}"
                    )
                result[identifier.value] = entry
        return result


@dataclass(frozen=True, slots=True)
class OMBA11ControlPortfolio:
    """The three imported fiscal code tables, pinned to one shared edition."""

    functional_classification: ParsedOMBA11Resource
    object_classification: ParsedOMBA11Resource
    apportionment_categories: ParsedOMBA11Resource
    fiscal_year_edition: str
    gaps: tuple[str, ...]


OMB_A11_PORTFOLIO_GAPS = (
    (
        "OMB Circular A-11 publishes these code families only as narrative-PDF exhibits; "
        "there is no code-list release identifier beyond the printed fiscal-year edition stamp."
    ),
    (
        "This module pins one page extract per code family from the 2025 edition. A later "
        "fiscal-year edition requires its own dated pin; this module never merges editions."
    ),
)


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "www.whitehouse.gov":
        raise OMBA11AcquisitionError("fetcher resolved_url must remain on official HTTPS whitehouse.gov")
    if parsed.username is not None or parsed.password is not None:
        raise OMBA11AcquisitionError("fetcher resolved_url must not contain credentials")


def _decode_text(payload: bytes, *, location: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OMBA11SourceDriftError(f"{location} is not valid UTF-8 text") from error


def _verify_payload(payload: bytes, pin: OMBA11PageSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise OMBA11SourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise OMBA11SourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    text = _decode_text(payload, location=location)
    match = _EDITION_ANYWHERE.search(text)
    if match is None or match.group(0) != pin.edition:
        raise OMBA11SourceDriftError(
            f"{location} edition drift: expected {pin.edition!r}, found {(match.group(0) if match else None)!r}"
        )
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: OMBA11PageSnapshotPin) -> AcquiredOMBA11Page:
    if path.is_symlink() or not path.is_file():
        raise OMBA11AcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached OMB A-11 page extract",
    )
    return AcquiredOMBA11Page(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        document_url=pin.source.document_url,
        resolved_url=None,
        content_type="text/plain",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: OMBA11PageSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredOMBA11Page:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} OMB A-11 page extract",
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
        return AcquiredOMBA11Page(
            pin=pin,
            path=final_path,
            sha256=actual_sha256,
            byte_length=byte_length,
            document_url=pin.source.document_url,
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


def acquire_omb_a11_page(
    pin: OMBA11PageSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: OMBA11Fetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredOMBA11Page:
    """Acquire one exact page extract through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise OMBA11AcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise OMBA11AcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise OMBA11AcquisitionError(f"local OMB A-11 source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="text/plain",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise OMBA11AcquisitionError("OMB A-11 page extract is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.document_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise OMBA11AcquisitionError(f"could not acquire {pin.source.document_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "text/plain":
        raise OMBA11SourceDriftError(f"OMB A-11 page extract content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _identifier(
    *,
    value: str,
    kind: str,
    acquired: AcquiredOMBA11Page,
) -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=kind,
        authority_uri=OMB_A11_IDENTIFIER_AUTHORITY_URI,
        source_uri=acquired.pin.source.document_url,
        observed_at=acquired.pin.retrieved_at,
        effective_at=None,
        source_digest=acquired.sha256,
    )


def _require_resource(acquired: AcquiredOMBA11Page, expected: ResourceName) -> str:
    if acquired.pin.source.resource_name != expected:
        raise OMBA11SourceDriftError(f"page extract is not the pinned {expected} source")
    text = _decode_text(acquired.path.read_bytes(), location=acquired.pin.source.exhibit_citation)
    _verify_payload(text.encode("utf-8"), acquired.pin, location="parsed OMB A-11 page extract")
    return text


def parse_omb_a11_functional_classification(acquired: AcquiredOMBA11Page) -> ParsedOMBA11Resource:
    """Parse Exhibit 79A budget function and subfunction codes."""

    text = _require_resource(acquired, "functionalClassification")
    lines = [line.strip() for line in text.splitlines()]
    entries: list[tuple[str, str | None, list[str]]] = []
    current: tuple[str, str | None, list[str]] | None = None
    for line in lines:
        if not line or _PAGE_HEADER_LINE.match(line) or line in _FUNCTION_NOISE:
            continue
        match = _FUNCTION_LINE.match(line)
        if match:
            if current is not None:
                entries.append(current)
            current = (match.group(1), match.group(2), [match.group(3)])
            continue
        if current is None:
            raise OMBA11SourceDriftError(f"unexpected Exhibit 79A content before any code: {line!r}")
        current[2].append(line)
    if current is not None:
        entries.append(current)

    codes: list[OMBA11Code] = []
    for code_start, code_end, title_parts in entries:
        title = re.sub(r"\s+", " ", " ".join(title_parts)).strip()
        code = f"{code_start}–{code_end}" if code_end else code_start
        is_major_function = re.sub(r"[^A-Za-z]", "", title).isupper()
        identifier_kind = "budgetFunctionCode" if is_major_function else "budgetSubfunctionCode"
        codes.append(
            OMBA11Code(
                resource_name="functionalClassification",
                use="deterministicMetadata",
                category="majorFunction" if is_major_function else "subfunction",
                fiscal_year_edition=acquired.pin.edition,
                publisher_label=title,
                source_url=acquired.pin.source.document_url,
                identifiers=(_identifier(value=code, kind=identifier_kind, acquired=acquired),),
            )
        )
    if len(codes) != acquired.pin.source.expected_code_count:
        raise OMBA11SourceDriftError(
            f"functionalClassification count drift: expected {acquired.pin.source.expected_code_count}, "
            f"parsed {len(codes)}"
        )
    return ParsedOMBA11Resource(
        source=acquired.pin.source,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        fiscal_year_edition=acquired.pin.edition,
        codes=tuple(codes),
        gaps=OMB_A11_PORTFOLIO_GAPS,
    )


def parse_omb_a11_object_classification(acquired: AcquiredOMBA11Page) -> ParsedOMBA11Resource:
    """Parse Exhibit 83A Schedule O object-class codes and their Appendix form."""

    text = _require_resource(acquired, "objectClassification")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    codes: list[OMBA11Code] = []
    reached_total = False
    for line in lines:
        if reached_total:
            continue
        if _PAGE_HEADER_LINE.match(line) or line in _OBJECT_NOISE:
            continue
        match = _OBJECT_LINE.match(line)
        if not match:
            raise OMBA11SourceDriftError(f"unexpected Exhibit 83A content: {line!r}")
        prefix, digits, raw_title = match.group(1), match.group(2), match.group(3)
        title = raw_title.rstrip("*").strip()
        schedule_code = f"{prefix}{digits}"
        appendix_code = f"{digits[:2]}.{digits[2]}"
        codes.append(
            OMBA11Code(
                resource_name="objectClassification",
                use="deterministicMetadata",
                category="objectClass",
                fiscal_year_edition=acquired.pin.edition,
                publisher_label=title,
                source_url=acquired.pin.source.document_url,
                identifiers=(
                    _identifier(value=schedule_code, kind="objectClassScheduleCode", acquired=acquired),
                    _identifier(value=appendix_code, kind="objectClassAppendixCode", acquired=acquired),
                ),
            )
        )
        if prefix == "9" and digits == "999":
            reached_total = True
    if len(codes) != acquired.pin.source.expected_code_count:
        raise OMBA11SourceDriftError(
            f"objectClassification count drift: expected {acquired.pin.source.expected_code_count}, "
            f"parsed {len(codes)}"
        )
    return ParsedOMBA11Resource(
        source=acquired.pin.source,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        fiscal_year_edition=acquired.pin.edition,
        codes=tuple(codes),
        gaps=OMB_A11_PORTFOLIO_GAPS,
    )


def parse_omb_a11_apportionment_categories(acquired: AcquiredOMBA11Page) -> ParsedOMBA11Resource:
    """Parse Section 120.13 apportionment category and non-apportioned line codes."""

    text = _require_resource(acquired, "apportionmentCategories")
    normalized = re.sub(r"\s+", " ", text).strip()

    codes: list[OMBA11Code] = []
    seen_categories: set[str] = set()
    for match in _CATEGORY_LINE.finditer(normalized):
        code, description, line_start, line_end = match.groups()
        if code in seen_categories:
            raise OMBA11SourceDriftError(f"apportionment category {code!r} repeats in Section 120.13")
        seen_categories.add(code)
        codes.append(
            OMBA11Code(
                resource_name="apportionmentCategories",
                use="deterministicMetadata",
                category="apportionmentCategory",
                fiscal_year_edition=acquired.pin.edition,
                publisher_label=f"Category {code} apportions budgetary resources {description.strip()}.",
                source_url=acquired.pin.source.document_url,
                identifiers=(
                    _identifier(value=code, kind="apportionmentCategoryCode", acquired=acquired),
                    _identifier(value=f"{line_start}-{line_end}", kind="apportionmentLineRange", acquired=acquired),
                ),
            )
        )
    if {"A", "B", "AB", "C"} - seen_categories:
        raise OMBA11SourceDriftError("Section 120.13 no longer states all four apportionment categories")

    start = normalized.find(_NONAPPORTIONED_START)
    end = normalized.find(_NONAPPORTIONED_END)
    if start == -1 or end == -1 or end <= start:
        raise OMBA11SourceDriftError("Section 120.13 no longer states the non-apportioned line list")
    segment = normalized[start:end]
    seen_lines: set[str] = set()
    for match in _NONAPPORTIONED_LINE.finditer(segment):
        line, raw_title = match.groups()
        if line in seen_lines:
            raise OMBA11SourceDriftError(f"apportionment line {line!r} repeats in Section 120.13")
        seen_lines.add(line)
        title = re.sub(r",?\s+and$", "", raw_title.strip()).rstrip(",").strip()
        codes.append(
            OMBA11Code(
                resource_name="apportionmentCategories",
                use="deterministicMetadata",
                category="nonApportionedLine",
                fiscal_year_edition=acquired.pin.edition,
                publisher_label=title,
                source_url=acquired.pin.source.document_url,
                identifiers=(_identifier(value=line, kind="apportionmentLineCode", acquired=acquired),),
            )
        )
    if seen_lines != {"6180", "6181", "6182", "6183"}:
        raise OMBA11SourceDriftError("Section 120.13 non-apportioned line codes no longer match the reviewed set")

    if len(codes) != acquired.pin.source.expected_code_count:
        raise OMBA11SourceDriftError(
            f"apportionmentCategories count drift: expected {acquired.pin.source.expected_code_count}, "
            f"parsed {len(codes)}"
        )
    return ParsedOMBA11Resource(
        source=acquired.pin.source,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        fiscal_year_edition=acquired.pin.edition,
        codes=tuple(codes),
        gaps=OMB_A11_PORTFOLIO_GAPS,
    )


def assemble_omb_a11_control_portfolio(
    resources: Sequence[ParsedOMBA11Resource],
) -> OMBA11ControlPortfolio:
    """Require all three distinct resources and one shared fiscal-year edition."""

    by_name = {resource.source.resource_name: resource for resource in resources}
    expected_names = {"functionalClassification", "objectClassification", "apportionmentCategories"}
    if len(resources) != 3 or set(by_name) != expected_names:
        raise OMBA11SourceDriftError(
            "OMB A-11 control portfolio requires exactly one functional, object, and apportionment resource"
        )
    editions = {resource.fiscal_year_edition for resource in resources}
    if len(editions) != 1:
        raise OMBA11SourceDriftError(
            "OMB A-11 control portfolio cannot mix resources pinned to different fiscal-year editions"
        )
    return OMBA11ControlPortfolio(
        functional_classification=by_name["functionalClassification"],
        object_classification=by_name["objectClassification"],
        apportionment_categories=by_name["apportionmentCategories"],
        fiscal_year_edition=editions.pop(),
        gaps=OMB_A11_PORTFOLIO_GAPS,
    )


@dataclass(frozen=True, slots=True)
class OMBA11FiscalCodeAssignment:
    """A fiscal-record field validated against the exact source snapshot."""

    source_field: str
    publisher_label: str
    use: ResourceUse
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool


@dataclass(frozen=True, slots=True)
class ValidatedOMBA11FiscalCodes:
    """Code evidence retained from one budget/apportionment fiscal record."""

    fiscal_year_edition: str
    budget_function: OMBA11FiscalCodeAssignment
    budget_subfunction: OMBA11FiscalCodeAssignment | None
    object_class: OMBA11FiscalCodeAssignment
    apportionment_category: OMBA11FiscalCodeAssignment
    gaps: tuple[str, ...]


def _assignment(code: OMBA11Code, source_field: str) -> OMBA11FiscalCodeAssignment:
    return OMBA11FiscalCodeAssignment(
        source_field=source_field,
        publisher_label=code.publisher_label,
        use=code.use,
        identifiers=code.identifiers,
        is_general_subject_concept=code.is_general_subject_concept,
    )


def validate_budget_fiscal_codes(
    record: Mapping[str, object],
    portfolio: OMBA11ControlPortfolio,
) -> ValidatedOMBA11FiscalCodes:
    """Validate one fiscal record's codes against a single pinned edition."""

    raw_edition = record.get("fiscal_year_edition")
    if not isinstance(raw_edition, str) or raw_edition != portfolio.fiscal_year_edition:
        raise OMBA11AssignmentError(
            f"fiscal record edition {raw_edition!r} does not match the pinned "
            f"{portfolio.fiscal_year_edition!r} portfolio; codes from different fiscal years are "
            "different facts and are never validated against each other"
        )

    function_lookup = portfolio.functional_classification.by_code(kind="budgetFunctionCode")
    raw_function = record.get("budget_function_code")
    if not isinstance(raw_function, str) or raw_function not in function_lookup:
        raise OMBA11AssignmentError(f"unknown OMB A-11 budget_function_code {raw_function!r}")
    function_assignment = _assignment(function_lookup[raw_function], "budget_function_code")

    subfunction_assignment: OMBA11FiscalCodeAssignment | None = None
    raw_subfunction = record.get("budget_subfunction_code")
    if raw_subfunction is not None:
        subfunction_lookup = portfolio.functional_classification.by_code(kind="budgetSubfunctionCode")
        if not isinstance(raw_subfunction, str) or raw_subfunction not in subfunction_lookup:
            raise OMBA11AssignmentError(f"unknown OMB A-11 budget_subfunction_code {raw_subfunction!r}")
        subfunction_assignment = _assignment(subfunction_lookup[raw_subfunction], "budget_subfunction_code")

    object_lookup = {
        **portfolio.object_classification.by_code(kind="objectClassScheduleCode"),
        **portfolio.object_classification.by_code(kind="objectClassAppendixCode"),
    }
    raw_object = record.get("object_class_code")
    if not isinstance(raw_object, str) or raw_object not in object_lookup:
        raise OMBA11AssignmentError(f"unknown OMB A-11 object_class_code {raw_object!r}")
    object_assignment = _assignment(object_lookup[raw_object], "object_class_code")

    category_lookup = portfolio.apportionment_categories.by_code(kind="apportionmentCategoryCode")
    raw_category = record.get("apportionment_category_code")
    if not isinstance(raw_category, str) or raw_category not in category_lookup:
        raise OMBA11AssignmentError(f"unknown OMB A-11 apportionment_category_code {raw_category!r}")
    category_assignment = _assignment(category_lookup[raw_category], "apportionment_category_code")

    return ValidatedOMBA11FiscalCodes(
        fiscal_year_edition=portfolio.fiscal_year_edition,
        budget_function=function_assignment,
        budget_subfunction=subfunction_assignment,
        object_class=object_assignment,
        apportionment_category=category_assignment,
        gaps=OMB_A11_PORTFOLIO_GAPS,
    )
