"""Pinned FERC eLibrary document class/type, docket-prefix, sector, and security fields.

FERC's eLibrary Class/Type Information page publishes several small,
FERC-specific controlled lists used to file and search Commission documents:
Document Class, Document Type (each paired with its parent Class), Docket
Prefix, Sector, and Security level. It also documents the Accession Number
format used to identify individual filed documents. None of these lists is a
general subject concept, and none of them applies to any agency other than
FERC -- they exist to interpret FERC filings, not to classify subject matter.
RefSpec must not reuse a FERC docket prefix, sector, or security level to
describe a record from another agency.

The current real-data path pins FERC's January 2025 class/type PDF, June 2025
docket-prefix PDF, general-search help, and accessibility guide. The older
single-page package below remains a constructed compatibility fixture; its
explicit ``provenance`` prevents it from being confused with the official
captures. Every real parser checks the exact publisher bytes, complete output
count, structure, and boundary samples.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection, and no scraping provider is
required for the current static HTML page.
"""

from __future__ import annotations

import hashlib
import html
import io
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

from pypdf import PdfReader

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode

FERC_PUBLISHER = "Federal Energy Regulatory Commission"
FERC_IDENTIFIER_AUTHORITY_URI = "https://www.ferc.gov/"
FERC_ELIBRARY_URL = "https://www.ferc.gov/media/elibrary-classtype-information"
FERC_CLASS_TYPE_PDF_URL = (
    "https://www.ferc.gov/sites/default/files/2025-06/"
    "Document%20Class%20Types%20January%202025.pdf"
)
FERC_CLASS_TYPE_PDF_SHA256 = "sha256:af632c9c6adbf0e7919d17e018b3a65078d0746bd1ab69a8d9fa65043720d688"
FERC_CLASS_TYPE_PDF_BYTE_LENGTH = 193_934
FERC_CLASS_TYPE_PDF_ROW_COUNT = 235
FERC_DOCKET_PREFIX_PDF_URL = "https://elibrary.ferc.gov/eLibrary/assets/docket-prefix.pdf"
FERC_DOCKET_PREFIX_PDF_SHA256 = "sha256:c32efae9f51a70b6f955821d2fb3d3025995ef0e17e57bf2d32dfa16c2508dcb"
FERC_DOCKET_PREFIX_PDF_BYTE_LENGTH = 282_729
FERC_GENERAL_SEARCH_HELP_URL = "https://elibrary.ferc.gov/eLibraryhelp/General_Search.htm"
FERC_GENERAL_SEARCH_HELP_SHA256 = "sha256:1f4b2883879602530c59095cc3d33fedbbf50a2d630e7bdf0226785259dd2b45"
FERC_GENERAL_SEARCH_HELP_BYTE_LENGTH = 7_447
FERC_ACCESSIBILITY_TIPS_URL = "https://elibrary.ferc.gov/eLibrary/assets/Accessibility_Tips.html"
FERC_ACCESSIBILITY_TIPS_SHA256 = "sha256:c9219bd08b8712e35389ff26f079a21e16d2b5fea68aaebf561bb9b203010688"
FERC_ACCESSIBILITY_TIPS_BYTE_LENGTH = 39_466

# Evidence of the acquisition attempt made while building this module. The
# publisher's edge network returned a bot-mitigation challenge rather than the
# page, so these values record the attempt itself, not a successful capture.
FERC_ELIBRARY_LIVE_FETCH_ATTEMPTED_AT = "2026-08-03T19:18:32Z"
FERC_ELIBRARY_LIVE_FETCH_HTTP_STATUS = 403
FERC_ELIBRARY_LIVE_FETCH_NOTE = (
    "Cloudflare bot-mitigation challenge response; no verified live page bytes were obtained."
)

# Exact bytes of the constructed reference fixture (not a live capture; see
# module docstring and FERC_ELIBRARY_PORTFOLIO_GAPS).
FERC_ELIBRARY_FIXTURE_SHA256 = "sha256:265f506c80143ae9ec97bcac215f7f19eeb3b5620e699d8442b84ced892e2874"
FERC_ELIBRARY_FIXTURE_BYTE_LENGTH = 2_202

ResourceName = Literal["documentClass", "documentType", "docketPrefix", "sector", "securityLevel"]
# The catalog scopes this whole source to deterministic, source-specific
# metadata; none of these fields is filer-selected evidence or a general
# subject concept.
ResourceUse = Literal["deterministicMetadata"]
SourceProvenance = Literal["constructedFixture", "liveCapture"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_DOCKET_PREFIX_CODE = re.compile(r"^[A-Z]{2,3}$")
_TITLE_MARKER = "<title>eLibrary Class/Type Information"
_DOCTYPE_MARKER = "<!doctype html>"
_ACCEPTED_MEDIA_TYPES = frozenset({"text/html"})

_CLASS_TYPE_HEADING = "Document Class and Type"
_CLASS_TYPE_COLUMNS = ("Class", "Type")
_DOCKET_PREFIX_HEADING = "Docket Prefixes"
_DOCKET_PREFIX_COLUMNS = ("Prefix", "Description")
_SECTOR_HEADING = "Sectors"
_SECTOR_COLUMNS = ("Sector",)
_SECURITY_HEADING = "Security"
_SECURITY_COLUMNS = ("Level", "Description")
_EXPECTED_DOCUMENT_CLASS_COUNT = 3
_EXPECTED_DOCUMENT_TYPE_COUNT = 7
_EXPECTED_DOCKET_PREFIX_COUNT = 8
_EXPECTED_SECTOR_COUNT = 5
_EXPECTED_SECURITY_COUNT = 3

_ROW = re.compile(r"<tr>(?P<cells>(?:<td>[^<]*</td>)+)</tr>")
_CELL = re.compile(r"<td>([^<]*)</td>")
_ACCESSION_SENTENCE = re.compile(
    r"<h2>Accession Number</h2>\s*<p>An accession number uniquely identifies each "
    r"document filed in eLibrary\. It is assigned by eLibrary in the form "
    r"(?P<pattern>[A-Za-z0-9\-]+), where (?P<explanation>[^<]*)</p>"
)


class FercResourceError(ValueError):
    """Base class for FERC eLibrary controlled-code failures."""


class FercAcquisitionError(FercResourceError):
    """Exact official source bytes could not be acquired safely."""


class FercSourceDriftError(FercResourceError):
    """A FERC eLibrary source no longer matches the reviewed structure or pin."""


class FercAssignmentError(FercResourceError):
    """A record carries an unknown or malformed source-assigned FERC field."""


@dataclass(frozen=True, slots=True)
class FercPublishedClassTypeRow:
    """One publisher row retained from the January 2025 FERC PDF."""

    category: Literal["Issuance", "Submittal"]
    text: str


@dataclass(frozen=True, slots=True)
class FercPublishedClassTypeCapture:
    """Measured shape of FERC's complete January 2025 class/type PDF."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    page_count: int
    rows: tuple[FercPublishedClassTypeRow, ...]


@dataclass(frozen=True, slots=True)
class FercPublishedDocketPrefixRow:
    """One active or discontinued docket-prefix row from FERC's current PDF."""

    status: Literal["active", "discontinued"]
    prefix: str
    library: str
    definition: str


@dataclass(frozen=True, slots=True)
class FercPublishedDocketPrefixCapture:
    """The complete June 2025 docket-prefix PDF."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    page_count: int
    rows: tuple[FercPublishedDocketPrefixRow, ...]


@dataclass(frozen=True, slots=True)
class FercPublishedSearchFieldsCapture:
    """Sector and security-level values from FERC's official search help."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    sectors: tuple[str, ...]
    security_levels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FercPublishedReferenceFormatsCapture:
    """Accession-number examples from FERC's official accessibility guide."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    accession_formats: tuple[str, ...]


def parse_ferc_class_type_pdf(payload: bytes) -> FercPublishedClassTypeCapture:
    """Read every class/type table row from FERC's pinned January 2025 PDF."""

    if not isinstance(payload, bytes) or not payload:
        raise FercSourceDriftError("FERC class/type PDF must be non-empty bytes")
    if len(payload) != FERC_CLASS_TYPE_PDF_BYTE_LENGTH or sha256_digest(payload) != FERC_CLASS_TYPE_PDF_SHA256:
        raise FercSourceDriftError("FERC class/type PDF failed its exact byte pin")
    try:
        reader = PdfReader(io.BytesIO(payload))
    except Exception as error:
        raise FercSourceDriftError("FERC class/type PDF is unreadable") from error
    rows: list[FercPublishedClassTypeRow] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            if line.startswith("Issuance "):
                rows.append(FercPublishedClassTypeRow(category="Issuance", text=line))
            elif line.startswith("Submittal "):
                rows.append(FercPublishedClassTypeRow(category="Submittal", text=line))
    if len(reader.pages) != 7 or len(rows) != FERC_CLASS_TYPE_PDF_ROW_COUNT:
        raise FercSourceDriftError(
            f"FERC class/type PDF shape drifted: pages={len(reader.pages)}, rows={len(rows)}"
        )
    return FercPublishedClassTypeCapture(
        source_url=FERC_CLASS_TYPE_PDF_URL,
        source_sha256=FERC_CLASS_TYPE_PDF_SHA256,
        source_byte_length=len(payload),
        page_count=len(reader.pages),
        rows=tuple(rows),
    )


_DOCKET_LIBRARY = (
    r"(?:Gen(?:, RM)?|E(?:, G, O, H, Gen|, G, H, O|, G, O| or G|, G)?|"
    r"G(?:, O)?|H(?:, E, G, O)?|O)"
)
_DOCKET_ROW = re.compile(
    r"(?P<prefix>[A-Z]{1,3}-?) (?P<library>"
    + _DOCKET_LIBRARY
    + r") (?P<definition>.+?)(?= [A-Z]{1,3}-? "
    + _DOCKET_LIBRARY
    + r" |$)"
)


def parse_ferc_docket_prefix_pdf(payload: bytes) -> FercPublishedDocketPrefixCapture:
    """Read every active and discontinued prefix from FERC's June 2025 PDF."""

    if len(payload) != FERC_DOCKET_PREFIX_PDF_BYTE_LENGTH or sha256_digest(payload) != FERC_DOCKET_PREFIX_PDF_SHA256:
        raise FercSourceDriftError("FERC docket-prefix PDF failed its exact byte pin")
    try:
        reader = PdfReader(io.BytesIO(payload))
    except Exception as error:
        raise FercSourceDriftError("FERC docket-prefix PDF is unreadable") from error
    rows: list[FercPublishedDocketPrefixRow] = []
    status: Literal["active", "discontinued"] | None = None
    for page in reader.pages:
        for raw_line in (page.extract_text() or "").splitlines():
            line = " ".join(raw_line.split())
            if "Table 1" in line or "Table 2" in line:
                status = "active"
                continue
            if "Table 3" in line:
                status = "discontinued"
                continue
            matches = tuple(_DOCKET_ROW.finditer(line))
            if matches and status is not None:
                rows.extend(
                    FercPublishedDocketPrefixRow(
                        status=status,
                        prefix=match.group("prefix"),
                        library=match.group("library"),
                        definition=match.group("definition"),
                    )
                    for match in matches
                )
            elif (
                rows
                and status is not None
                and line
                and re.fullmatch(r"\d+ June 2025", line) is None
                and line != "Prefix Library Definition"
                and not line.startswith(("Federal Energy", "Docket Prefix List"))
            ):
                previous = rows[-1]
                rows[-1] = FercPublishedDocketPrefixRow(
                    status=previous.status,
                    prefix=previous.prefix,
                    library=previous.library,
                    definition=f"{previous.definition} {line}",
                )
    if len(reader.pages) != 6 or len(rows) != 95:
        raise FercSourceDriftError(f"FERC docket-prefix PDF shape drifted: pages={len(reader.pages)}, rows={len(rows)}")
    return FercPublishedDocketPrefixCapture(
        source_url=FERC_DOCKET_PREFIX_PDF_URL,
        source_sha256=FERC_DOCKET_PREFIX_PDF_SHA256,
        source_byte_length=len(payload),
        page_count=len(reader.pages),
        rows=tuple(rows),
    )


def _list_values_after_heading(source: str, heading: str) -> tuple[str, ...]:
    match = re.search(
        r"<li>" + re.escape(heading) + r"</li>\s*<ul[^>]*>(?P<items>.*?)</ul>",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        raise FercSourceDriftError(f"FERC help page omitted the {heading!r} list")
    return tuple(
        html.unescape(re.sub(r"<[^>]+>", "", item)).strip()
        for item in re.findall(r"<li>(.*?)</li>", match.group("items"), flags=re.DOTALL)
    )


def parse_ferc_general_search_help(payload: bytes) -> FercPublishedSearchFieldsCapture:
    """Read the exact sector and security options from FERC's search help page."""

    if len(payload) != FERC_GENERAL_SEARCH_HELP_BYTE_LENGTH or sha256_digest(payload) != FERC_GENERAL_SEARCH_HELP_SHA256:
        raise FercSourceDriftError("FERC general-search help failed its exact byte pin")
    source = payload.decode("ascii")
    sectors = _list_values_after_heading(source, "Industry Sector")
    security_levels = _list_values_after_heading(source, "Security Level")
    if len(sectors) != 6 or len(security_levels) != 4:
        raise FercSourceDriftError("FERC general-search field counts drifted")
    return FercPublishedSearchFieldsCapture(
        source_url=FERC_GENERAL_SEARCH_HELP_URL,
        source_sha256=FERC_GENERAL_SEARCH_HELP_SHA256,
        source_byte_length=len(payload),
        sectors=sectors,
        security_levels=security_levels,
    )


def parse_ferc_accessibility_tips(payload: bytes) -> FercPublishedReferenceFormatsCapture:
    """Read accession-number examples from FERC's official HTML guide."""

    if len(payload) != FERC_ACCESSIBILITY_TIPS_BYTE_LENGTH or sha256_digest(payload) != FERC_ACCESSIBILITY_TIPS_SHA256:
        raise FercSourceDriftError("FERC accessibility guide failed its exact byte pin")
    source = payload.decode("utf-8")
    match = re.search(
        r"<td scope=\"row\">Accession</td>\s*<td>(?P<formats>[^<]+)</td>",
        source,
    )
    if match is None:
        raise FercSourceDriftError("FERC accessibility guide omitted Accession formats")
    formats = tuple(part.strip() for part in match.group("formats").split(", or "))
    if formats != ("19940824-0052", "19940824*"):
        raise FercSourceDriftError(f"FERC accession formats drifted: {formats!r}")
    return FercPublishedReferenceFormatsCapture(
        source_url=FERC_ACCESSIBILITY_TIPS_URL,
        source_sha256=FERC_ACCESSIBILITY_TIPS_SHA256,
        source_byte_length=len(payload),
        accession_formats=formats,
    )


def _table_pattern(heading: str, columns: tuple[str, ...]) -> re.Pattern[str]:
    """Match one ``<h2>heading</h2>`` immediately followed by its exact table.

    The header row, column count, and surrounding tag order are exact because
    they are the documented structure this module packages; any drift in
    shape fails to match and is reported as source drift rather than silently
    parsed as something else.
    """

    header_row = "".join(f"<th>{re.escape(column)}</th>" for column in columns)
    row_cells = "(?:<td>[^<]*</td>){" + str(len(columns)) + "}"
    return re.compile(
        r"<h2>"
        + re.escape(heading)
        + r"</h2>\s*<table>\s*<thead>\s*<tr>"
        + header_row
        + r"</tr>\s*</thead>\s*<tbody>\s*(?P<rows>(?:<tr>"
        + row_cells
        + r"</tr>\s*)+)</tbody>\s*</table>"
    )


def _extract_rows(text: str, heading: str, columns: tuple[str, ...]) -> list[tuple[str, ...]]:
    match = _table_pattern(heading, columns).search(text)
    if match is None:
        raise FercSourceDriftError(f"{heading!r} table was not found in the expected shape")
    rows: list[tuple[str, ...]] = []
    for row_match in _ROW.finditer(match.group("rows")):
        cells = tuple(cell.strip() for cell in _CELL.findall(row_match.group("cells")))
        if len(cells) != len(columns):
            raise FercSourceDriftError(f"{heading!r} row has {len(cells)} cells, expected {len(columns)}")
        if any(not cell for cell in cells):
            raise FercSourceDriftError(f"{heading!r} row contains an empty cell")
        rows.append(cells)
    return rows


@dataclass(frozen=True, slots=True)
class FercELibrarySource:
    """The one official FERC eLibrary class/type information page."""

    source_url: str
    filename: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "www.ferc.gov":
            raise FercAcquisitionError("source_url must be an official HTTPS www.ferc.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise FercAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise FercAcquisitionError("filename must be one plain path component")


FERC_ELIBRARY_SOURCE = FercELibrarySource(
    source_url=FERC_ELIBRARY_URL,
    filename="ferc-elibrary-classtype-information.html",
)


@dataclass(frozen=True, slots=True)
class FercSnapshotPin:
    """Exact identity of one FERC eLibrary page snapshot.

    ``retrieved_at`` records when these bytes were captured or constructed;
    ``provenance`` says which one happened, so a placeholder fixture can never
    silently pass for a verified live capture.
    """

    source: FercELibrarySource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    provenance: SourceProvenance
    publisher_last_modified: str | None = None

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise FercAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise FercAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise FercAcquisitionError("retrieved_at must not be empty")


# The fixture pin below is deliberately not named after a claimed live
# retrieval date alone; ``provenance="constructedFixture"`` is load-bearing.
FERC_ELIBRARY_2026_08_03_FIXTURE = FercSnapshotPin(
    source=FERC_ELIBRARY_SOURCE,
    retrieved_at=FERC_ELIBRARY_LIVE_FETCH_ATTEMPTED_AT,
    expected_sha256=FERC_ELIBRARY_FIXTURE_SHA256,
    expected_byte_length=FERC_ELIBRARY_FIXTURE_BYTE_LENGTH,
    provenance="constructedFixture",
)


@dataclass(frozen=True, slots=True)
class FetchedFercResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class FercFetcher(Protocol):
    """Small transport boundary for the official FERC eLibrary page."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedFercResponse:
        """Fetch the response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredFercSource:
    """One verified source object in the content-addressed store."""

    pin: FercSnapshotPin
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
class FercCode:
    """One exact publisher label from the pinned eLibrary page."""

    resource_name: ResourceName
    use: ResourceUse
    publisher_label: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedFercResource:
    """One parsed, digest-pinned FERC eLibrary controlled code list."""

    resource_name: ResourceName
    use: ResourceUse
    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    provenance: SourceProvenance
    codes: tuple[FercCode, ...]

    def by_code(self) -> dict[str, FercCode]:
        """Index each row by its own resource's first (leading) identifier value."""

        result: dict[str, FercCode] = {}
        for entry in self.codes:
            key = entry.identifiers[0].value
            if key in result:
                raise FercSourceDriftError(f"{self.resource_name} contains duplicate publisher code {key!r}")
            result[key] = entry
        return result


@dataclass(frozen=True, slots=True)
class FercAccessionNumberFormat:
    """The documented Accession Number pattern, not an enumerated code list."""

    pattern: str
    explanation: str
    source_url: str


@dataclass(frozen=True, slots=True)
class FercELibraryControlPortfolio:
    """The five closed code lists, the accession format note, and known gaps."""

    document_class: ParsedFercResource
    document_type: ParsedFercResource
    docket_prefix: ParsedFercResource
    sector: ParsedFercResource
    security_level: ParsedFercResource
    accession_number_format: FercAccessionNumberFormat
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FercCodeAssignment:
    """A record field value validated against the exact pinned page."""

    source_field: str
    publisher_label: str
    use: ResourceUse
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool


@dataclass(frozen=True, slots=True)
class ValidatedFercELibraryFields:
    """FERC eLibrary code evidence retained from one document record."""

    document_type: FercCodeAssignment
    docket_prefix: FercCodeAssignment
    sector: FercCodeAssignment | None
    security_level: FercCodeAssignment
    gaps: tuple[str, ...]


FERC_ELIBRARY_PORTFOLIO_GAPS = (
    (
        f"An unauthenticated automated request for {FERC_ELIBRARY_URL} returned HTTP "
        f"{FERC_ELIBRARY_LIVE_FETCH_HTTP_STATUS} from a bot-mitigation challenge; this module packages a "
        "constructed reference fixture pinned by explicit provenance rather than a verified live capture, "
        "pending a browser-mediated re-acquisition."
    ),
    (
        "The page does not publish a list revision number or effective date for its class, type, "
        "docket-prefix, sector, or security tables; retrieval time and the exact digest are the only "
        "available revision pins once a verified live capture exists."
    ),
    (
        "Accession Number is a per-filing identifier format, not a bounded code list; RefSpec records its "
        "documented pattern only and does not enumerate accession values."
    ),
    (
        "These fields are FERC-specific deterministic metadata; RefSpec must not reuse a FERC docket "
        "prefix, sector, or security level to describe a record from another agency."
    ),
)


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "www.ferc.gov":
        raise FercAcquisitionError("fetcher resolved_url must remain on official HTTPS www.ferc.gov")
    if parsed.username is not None or parsed.password is not None:
        raise FercAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: FercSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise FercSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise FercSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FercSourceDriftError(f"{location} is not valid UTF-8 text") from error
    if not text.lstrip().lower().startswith(_DOCTYPE_MARKER):
        raise FercSourceDriftError(f"{location} is missing the expected HTML doctype")
    if _TITLE_MARKER not in text:
        raise FercSourceDriftError(f"{location} is missing the expected eLibrary title marker")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: FercSnapshotPin) -> AcquiredFercSource:
    if path.is_symlink() or not path.is_file():
        raise FercAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached FERC eLibrary source",
    )
    return AcquiredFercSource(
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
    pin: FercSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredFercSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} FERC eLibrary source",
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
        return AcquiredFercSource(
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


def acquire_ferc_elibrary_page(
    pin: FercSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: FercFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredFercSource:
    """Acquire the exact eLibrary page response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise FercAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise FercAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise FercAcquisitionError(f"local FERC eLibrary source is not a regular file: {local_path}")
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
        raise FercAcquisitionError("the FERC eLibrary page is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise FercAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in _ACCEPTED_MEDIA_TYPES:
        raise FercSourceDriftError(f"FERC eLibrary page content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _document_class_codes(
    rows: Sequence[tuple[str, ...]],
    acquired: AcquiredFercSource,
) -> tuple[FercCode, ...]:
    seen: dict[str, FercCode] = {}
    for class_label, _type_label in rows:
        if class_label in seen:
            continue
        seen[class_label] = FercCode(
            resource_name="documentClass",
            use="deterministicMetadata",
            publisher_label=class_label,
            source_url=acquired.pin.source.source_url,
            identifiers=(
                ControlledIdentifier(
                    value=class_label,
                    kind="documentClassLabel",
                    authority_uri=FERC_IDENTIFIER_AUTHORITY_URI,
                    source_uri=acquired.pin.source.source_url,
                    observed_at=acquired.pin.retrieved_at,
                    effective_at=None,
                    source_digest=acquired.sha256,
                ),
            ),
        )
    return tuple(seen.values())


def _document_type_codes(
    rows: Sequence[tuple[str, ...]],
    acquired: AcquiredFercSource,
) -> tuple[FercCode, ...]:
    codes: list[FercCode] = []
    seen_types: set[str] = set()
    for class_label, type_label in rows:
        if type_label in seen_types:
            raise FercSourceDriftError(f"document type {type_label!r} repeats under multiple classes")
        seen_types.add(type_label)
        codes.append(
            FercCode(
                resource_name="documentType",
                use="deterministicMetadata",
                publisher_label=type_label,
                source_url=acquired.pin.source.source_url,
                identifiers=(
                    ControlledIdentifier(
                        value=type_label,
                        kind="documentTypeLabel",
                        authority_uri=FERC_IDENTIFIER_AUTHORITY_URI,
                        source_uri=acquired.pin.source.source_url,
                        observed_at=acquired.pin.retrieved_at,
                        effective_at=None,
                        source_digest=acquired.sha256,
                    ),
                    # The publisher shows every Type against its parent Class in
                    # the same row; that pairing is retained as evidence, not
                    # inferred or reordered.
                    ControlledIdentifier(
                        value=class_label,
                        kind="documentClassLabel",
                        authority_uri=FERC_IDENTIFIER_AUTHORITY_URI,
                        source_uri=acquired.pin.source.source_url,
                        observed_at=acquired.pin.retrieved_at,
                        effective_at=None,
                        source_digest=acquired.sha256,
                    ),
                ),
            )
        )
    return tuple(codes)


def _docket_prefix_codes(
    rows: Sequence[tuple[str, ...]],
    acquired: AcquiredFercSource,
) -> tuple[FercCode, ...]:
    codes: list[FercCode] = []
    for prefix, description in rows:
        if _DOCKET_PREFIX_CODE.fullmatch(prefix) is None:
            raise FercSourceDriftError(f"docket prefix {prefix!r} has a malformed publisher code")
        codes.append(
            FercCode(
                resource_name="docketPrefix",
                use="deterministicMetadata",
                publisher_label=description,
                source_url=acquired.pin.source.source_url,
                identifiers=(
                    ControlledIdentifier(
                        value=prefix,
                        kind="docketPrefixCode",
                        authority_uri=FERC_IDENTIFIER_AUTHORITY_URI,
                        source_uri=acquired.pin.source.source_url,
                        observed_at=acquired.pin.retrieved_at,
                        effective_at=None,
                        source_digest=acquired.sha256,
                    ),
                ),
            )
        )
    return tuple(codes)


def _sector_codes(
    rows: Sequence[tuple[str, ...]],
    acquired: AcquiredFercSource,
) -> tuple[FercCode, ...]:
    codes: list[FercCode] = []
    for (sector_label,) in rows:
        codes.append(
            FercCode(
                resource_name="sector",
                use="deterministicMetadata",
                publisher_label=sector_label,
                source_url=acquired.pin.source.source_url,
                identifiers=(
                    ControlledIdentifier(
                        value=sector_label,
                        kind="sectorLabel",
                        authority_uri=FERC_IDENTIFIER_AUTHORITY_URI,
                        source_uri=acquired.pin.source.source_url,
                        observed_at=acquired.pin.retrieved_at,
                        effective_at=None,
                        source_digest=acquired.sha256,
                    ),
                ),
            )
        )
    return tuple(codes)


def _security_codes(
    rows: Sequence[tuple[str, ...]],
    acquired: AcquiredFercSource,
) -> tuple[FercCode, ...]:
    codes: list[FercCode] = []
    for level, _description in rows:
        # The Level column (for example "CEII") is itself the publisher's
        # readable name; Description is definitional prose, not an alternate
        # label, so only Level is retained as the code's publisher_label.
        codes.append(
            FercCode(
                resource_name="securityLevel",
                use="deterministicMetadata",
                publisher_label=level,
                source_url=acquired.pin.source.source_url,
                identifiers=(
                    ControlledIdentifier(
                        value=level,
                        kind="securityLevelCode",
                        authority_uri=FERC_IDENTIFIER_AUTHORITY_URI,
                        source_uri=acquired.pin.source.source_url,
                        observed_at=acquired.pin.retrieved_at,
                        effective_at=None,
                        source_digest=acquired.sha256,
                    ),
                ),
            )
        )
    return tuple(codes)


def parse_ferc_elibrary_resource(
    acquired: AcquiredFercSource,
    resource_name: ResourceName,
) -> ParsedFercResource:
    """Parse one exact FERC eLibrary table without converting it to concepts."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed FERC eLibrary source")
    text = payload.decode("utf-8")

    if resource_name == "documentClass":
        rows = _extract_rows(text, _CLASS_TYPE_HEADING, _CLASS_TYPE_COLUMNS)
        codes = _document_class_codes(rows, acquired)
        expected_count = _EXPECTED_DOCUMENT_CLASS_COUNT
    elif resource_name == "documentType":
        rows = _extract_rows(text, _CLASS_TYPE_HEADING, _CLASS_TYPE_COLUMNS)
        codes = _document_type_codes(rows, acquired)
        expected_count = _EXPECTED_DOCUMENT_TYPE_COUNT
    elif resource_name == "docketPrefix":
        rows = _extract_rows(text, _DOCKET_PREFIX_HEADING, _DOCKET_PREFIX_COLUMNS)
        codes = _docket_prefix_codes(rows, acquired)
        expected_count = _EXPECTED_DOCKET_PREFIX_COUNT
    elif resource_name == "sector":
        rows = _extract_rows(text, _SECTOR_HEADING, _SECTOR_COLUMNS)
        codes = _sector_codes(rows, acquired)
        expected_count = _EXPECTED_SECTOR_COUNT
    elif resource_name == "securityLevel":
        rows = _extract_rows(text, _SECURITY_HEADING, _SECURITY_COLUMNS)
        codes = _security_codes(rows, acquired)
        expected_count = _EXPECTED_SECURITY_COUNT
    else:
        raise FercResourceError(f"unsupported FERC eLibrary resource {resource_name!r}")

    if len(codes) != expected_count:
        raise FercSourceDriftError(f"{resource_name} count drift: expected {expected_count}, parsed {len(codes)}")
    code_values = [entry.identifiers[0].value for entry in codes]
    if len(set(code_values)) != len(code_values):
        raise FercSourceDriftError(f"{resource_name} contains duplicate publisher codes")
    labels = [entry.publisher_label for entry in codes]
    if len(set(labels)) != len(labels):
        raise FercSourceDriftError(f"{resource_name} contains duplicate publisher labels")

    return ParsedFercResource(
        resource_name=resource_name,
        use="deterministicMetadata",
        source_url=acquired.pin.source.source_url,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        provenance=acquired.pin.provenance,
        codes=codes,
    )


def parse_ferc_accession_number_format(acquired: AcquiredFercSource) -> FercAccessionNumberFormat:
    """Parse the documented Accession Number pattern; it is a format, not a code list."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed FERC eLibrary source")
    text = payload.decode("utf-8")

    match = _ACCESSION_SENTENCE.search(text)
    if match is None:
        raise FercSourceDriftError("accession number format paragraph was not found in the expected shape")
    return FercAccessionNumberFormat(
        pattern=match.group("pattern"),
        explanation=match.group("explanation").rstrip("."),
        source_url=acquired.pin.source.source_url,
    )


def assemble_ferc_elibrary_control_portfolio(
    resources: Sequence[ParsedFercResource],
    accession_number_format: FercAccessionNumberFormat,
) -> FercELibraryControlPortfolio:
    """Require all five distinct resources and retain the documented gaps."""

    by_name = {resource.resource_name: resource for resource in resources}
    expected_names = {"documentClass", "documentType", "docketPrefix", "sector", "securityLevel"}
    if len(resources) != 5 or set(by_name) != expected_names:
        raise FercSourceDriftError(
            "FERC eLibrary control portfolio requires exactly one documentClass, documentType, "
            "docketPrefix, sector, and securityLevel resource"
        )
    return FercELibraryControlPortfolio(
        document_class=by_name["documentClass"],
        document_type=by_name["documentType"],
        docket_prefix=by_name["docketPrefix"],
        sector=by_name["sector"],
        security_level=by_name["securityLevel"],
        accession_number_format=accession_number_format,
        gaps=FERC_ELIBRARY_PORTFOLIO_GAPS,
    )


def _assignment(code: FercCode, source_field: str) -> FercCodeAssignment:
    return FercCodeAssignment(
        source_field=source_field,
        publisher_label=code.publisher_label,
        use=code.use,
        identifiers=code.identifiers,
        is_general_subject_concept=code.is_general_subject_concept,
    )


def validate_ferc_elibrary_fields(
    record: Mapping[str, object],
    portfolio: FercELibraryControlPortfolio,
) -> ValidatedFercELibraryFields:
    """Validate the exact FERC eLibrary fields retained on one document record."""

    raw_type = record.get("document_type")
    if not isinstance(raw_type, str):
        raise FercAssignmentError("FERC eLibrary record must carry a string document_type")
    document_type = portfolio.document_type.by_code().get(raw_type)
    if document_type is None:
        raise FercAssignmentError(f"unknown FERC eLibrary document_type {raw_type!r}")

    raw_prefix = record.get("docket_prefix")
    if not isinstance(raw_prefix, str):
        raise FercAssignmentError("FERC eLibrary record must carry a string docket_prefix")
    docket_prefix = portfolio.docket_prefix.by_code().get(raw_prefix)
    if docket_prefix is None:
        raise FercAssignmentError(f"unknown FERC eLibrary docket_prefix {raw_prefix!r}")

    sector: FercCodeAssignment | None = None
    raw_sector = record.get("sector")
    if raw_sector is not None:
        if not isinstance(raw_sector, str):
            raise FercAssignmentError("FERC eLibrary record sector must be a string when present")
        sector_code = portfolio.sector.by_code().get(raw_sector)
        if sector_code is None:
            raise FercAssignmentError(f"unknown FERC eLibrary sector {raw_sector!r}")
        sector = _assignment(sector_code, "sector")

    raw_security = record.get("security_level")
    if not isinstance(raw_security, str):
        raise FercAssignmentError("FERC eLibrary record must carry a string security_level")
    security_level = portfolio.security_level.by_code().get(raw_security)
    if security_level is None:
        raise FercAssignmentError(f"unknown FERC eLibrary security_level {raw_security!r}")

    return ValidatedFercELibraryFields(
        document_type=_assignment(document_type, "document_type"),
        docket_prefix=_assignment(docket_prefix, "docket_prefix"),
        sector=sector,
        security_level=_assignment(security_level, "security_level"),
        gaps=FERC_ELIBRARY_PORTFOLIO_GAPS,
    )
