"""Treasury Account Symbol component structure and FAST Book edition capture.

The Bureau of the Fiscal Service documents the Treasury Account Symbol (TAS)
as eight named component fields ("Component TAS format") on its Central
Accounting Reporting System (CARS) page, and documents the Federal Account
Symbols and Titles (FAST) Book as three parts -- receipt accounts (Part I),
appropriation and other fund accounts (Part II), and foreign currency
accounts (Part III) -- each arranged within a documented set of fund groups,
on its "Description of Contents" page. Neither page publishes a machine
readable code list or a stable release identifier; each instead carries only
a "Last Updated" date, which this module treats as that page's edition.

This module captures the two pages' exact bytes, extracts their documented
component names, fund groups, and edition dates, and validates a TAS
component record or a FAST Book account-title record against that captured
structure. It does not fetch or ingest the FAST Book's PDF row content: the
FAST Book itself is a formatted document, not a code list, and the source
catalog forbids ingesting bulk entity rows here. It never mints a concept
identity for an account title; every identifier it builds is a RefSpec-local,
capture-anchored encoding of the publisher's own component fields, not a
Treasury-published display string.

fiscal.treasury.gov pages embed per-request Akamai/Boomerang analytics
tokens (request IDs, timestamps) directly in the page body, so two live
captures of the identical logical page do not share one stable digest. This
module therefore pins each capture's own observed digest for cache and
local-file integrity, the same way every other registry acquisition module
does, rather than asserting one eternal "the" official page hash.

Live retrieval is provider-independent. Callers inject a fetcher or provide
an already captured local file. Importing this module never opens a network
connection.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier

TREASURY_PUBLISHER = "Bureau of the Fiscal Service, U.S. Department of the Treasury"
TREASURY_IDENTIFIER_AUTHORITY_URI = "https://fiscal.treasury.gov/accounting/"

ResourceName = Literal["tasComponentFormat", "fastBookDescriptionOfContents"]
AcquisitionMode = Literal["cache", "local", "fetcher"]
FASTBookPart = Literal["I", "II", "III"]
FundGroup = Literal["general", "special", "trust", "revolving", "deposit", "foreignCurrency"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_LAST_UPDATED = re.compile(r"Last Updated:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
_AID_PATTERN = re.compile(r"^\d{3}$")
_MAIN_PATTERN = re.compile(r"^\d{4}$")
_SUB_PATTERN = re.compile(r"^\d{3}$")
_ATA_PATTERN = re.compile(r"^\d{3}$")
_SP_PATTERN = re.compile(r"^\d{2}$")
_POA_PATTERN = re.compile(r"^\d{4}$")
_AVAILABILITY_TYPE_PATTERN = re.compile(r"^[A-Z]$")
_DEFAULT_SUB_ACCOUNT = "000"

# Treasury's own "Component TAS-BETC" flyer (a Bureau of the Fiscal Service
# document distributed by GPO) states the component sizes in order -- SP (2),
# ATA (3), AID (3), BPOA (4), EPOA (4), A (1), MAIN (4), SUB (3) -- which the
# width patterns above implement exactly. The PDF is pinned as reference-only
# provenance (fixture ``component-tas-betc-flyer.pdf``) and never parsed at
# runtime; its size row reads "Size: (2) (3) (3) (4) (4) (1) (4) (3)".
TAS_COMPONENT_SIZE_AUTHORITY_URL = (
    "https://www.gpo.gov/docs/default-source/guides-and-instructions/pdf/2-component-tas-betc-flyer.pdf"
)
TAS_COMPONENT_SIZE_AUTHORITY_SHA256 = "sha256:7a43d33c291a9ab233ed76237dec3cbfb28ebd10169183328077227f6c0cf2ea"
TAS_COMPONENT_SIZE_AUTHORITY_BYTE_LENGTH = 537_393
TAS_COMPONENT_SIZE_AUTHORITY_RETRIEVED_AT = "2026-08-03T23:31:00Z"

# The exact fund-group phrases the FAST Book "Description of Contents" page
# uses for Part I and Part II. Part III's paragraph names foreign currency
# accounts without enumerating a fund-group list, so RefSpec treats Part III
# as its own single fund group rather than inferring one.
PART_FUND_GROUPS: Mapping[FASTBookPart, tuple[FundGroup, ...]] = {
    "I": ("general", "special", "trust"),
    "II": ("general", "revolving", "special", "deposit", "trust"),
    "III": ("foreignCurrency",),
}

# Fund groups that the Description of Contents page says carry a citation to
# the United States Code or United States Statutes at Large. "general" fund
# accounts are not listed for either part.
_CITED_FUND_GROUPS: Mapping[FASTBookPart, frozenset[FundGroup]] = {
    "I": frozenset({"special", "trust"}),
    "II": frozenset({"revolving", "special", "deposit", "trust"}),
    "III": frozenset(),
}

TREASURY_TAS_FAST_BOOK_GAPS = (
    (
        "The Component TAS format page names its eight component fields (SP, ATA, "
        "AID, BPOA, EPOA, A, MAIN, SUB) but does not publish their exact character "
        'widths on that page; the widths applied here are publisher-stated in Treasury\'s own "Component '
        'TAS-BETC" flyer (pinned at TAS_COMPONENT_SIZE_AUTHORITY_SHA256, size row "Size: (2) (3) (3) (4) '
        '(4) (1) (4) (3)"), which confirms the OMB Circular A-11 / Governmentwide Spending Data Model '
        "convention this module started from. The flyer is reference-only provenance, not parsed at runtime."
    ),
    (
        "The FAST Book is distributed as formatted PDF parts (Part I, Part II and "
        "III), not a machine-readable code list; RefSpec does not fetch or ingest "
        "FAST Book row-level agency/account-title bulk data and captures only the "
        "Description of Contents page's documented fund-group structure and edition."
    ),
    (
        "fiscal.treasury.gov pages embed per-request Akamai/Boomerang analytics "
        "tokens and timestamps directly in the page body, so two live captures of "
        "the identical logical page do not share one byte-stable digest."
    ),
)


class TreasuryTASFastBookError(ValueError):
    """Base class for Treasury TAS/FAST Book capture failures."""


class TreasuryAcquisitionError(TreasuryTASFastBookError):
    """Exact official source bytes could not be acquired safely."""


class TreasurySourceDriftError(TreasuryTASFastBookError):
    """A captured Treasury page no longer matches the reviewed structure."""


class TASComponentError(TreasuryTASFastBookError):
    """A Treasury Account Symbol component record is malformed or inconsistent."""


class FASTBookRecordError(TreasuryTASFastBookError):
    """A FAST Book account-title record is malformed or inconsistent with its edition."""


@dataclass(frozen=True, slots=True)
class TreasuryPageSource:
    """One official fiscal.treasury.gov "Description of Contents"-style page."""

    resource_name: ResourceName
    source_url: str
    filename: str
    structural_markers: tuple[str, ...]

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "fiscal.treasury.gov":
            raise TreasuryAcquisitionError("source_url must be an official HTTPS fiscal.treasury.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise TreasuryAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise TreasuryAcquisitionError("filename must be one plain path component")
        if not self.structural_markers:
            raise TreasuryAcquisitionError("structural_markers must not be empty")


TAS_COMPONENT_FORMAT_SOURCE = TreasuryPageSource(
    resource_name="tasComponentFormat",
    source_url=(
        "https://fiscal.treasury.gov/accounting/central-accounting-reporting-system-cars/"
        "treasury-account-symbol-reporting"
    ),
    filename="treasury-account-symbol-reporting.html",
    structural_markers=(
        "sub-level prefix (SP)",
        "allocation transfer identifier (ATA)",
        "agency identifier (AID)",
        "beginning period of availability (BPOA)",
        "ending period of availability (EPOA)",
        "availability type (A)",
        "main account (main)",
        "sub-account code (SUB)",
    ),
)
FAST_BOOK_DESCRIPTION_SOURCE = TreasuryPageSource(
    resource_name="fastBookDescriptionOfContents",
    source_url="https://fiscal.treasury.gov/accounting/fast-book/description-of-contents",
    filename="fast-book-description-of-contents.html",
    structural_markers=(
        "Part I contains receipt accounts arranged numerically within each fund group",
        "general, special and trust",
        "Part II contains appropriation and other fund accounts for each agency",
        "general, revolving, special, deposit and trust",
        "Part III contains foreign currency accounts",
    ),
)


@dataclass(frozen=True, slots=True)
class TreasuryPageSnapshotPin:
    """Exact identity of one Treasury page capture."""

    source: TreasuryPageSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise TreasuryAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise TreasuryAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise TreasuryAcquisitionError("retrieved_at must not be empty")


# Real captures made 2026-08-03. Pinned here for cache/local-file integrity
# checks, not as a claim that a future live fetch will reproduce this exact
# digest (see the Akamai/Boomerang gap recorded above).
TAS_COMPONENT_FORMAT_2026_08_03 = TreasuryPageSnapshotPin(
    source=TAS_COMPONENT_FORMAT_SOURCE,
    retrieved_at="2026-08-03T19:17:15Z",
    expected_sha256="sha256:fbd8c6794fdf10d4e1b28ece79af5c15352eb25d292069e0238c3c7513f4675d",
    expected_byte_length=112_908,
)
FAST_BOOK_DESCRIPTION_2026_08_03 = TreasuryPageSnapshotPin(
    source=FAST_BOOK_DESCRIPTION_SOURCE,
    retrieved_at="2026-08-03T19:17:43Z",
    expected_sha256="sha256:91525d80cc4bd6e8ab08075ad630b484b0f691c08516a36151589ddbd57c2a36",
    expected_byte_length=110_043,
)


@dataclass(frozen=True, slots=True)
class FetchedTreasuryPage:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class TreasuryPageFetcher(Protocol):
    """Small transport boundary for official fiscal.treasury.gov pages."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedTreasuryPage:
        """Fetch one page while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredTreasuryPage:
    """One verified Treasury page in the content-addressed store."""

    pin: TreasuryPageSnapshotPin
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
    if parsed.scheme != "https" or parsed.hostname != "fiscal.treasury.gov":
        raise TreasuryAcquisitionError("fetcher resolved_url must remain on official HTTPS fiscal.treasury.gov")
    if parsed.username is not None or parsed.password is not None:
        raise TreasuryAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: TreasuryPageSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise TreasurySourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise TreasurySourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    lowered = payload[:64_000].lower()
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise TreasurySourceDriftError(f"{location} is not an HTML document")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: TreasuryPageSnapshotPin) -> AcquiredTreasuryPage:
    if path.is_symlink() or not path.is_file():
        raise TreasuryAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(path.read_bytes(), pin, location="cached Treasury page")
    return AcquiredTreasuryPage(
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
    pin: TreasuryPageSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredTreasuryPage:
    actual_sha256, byte_length = _verify_payload(payload, pin, location=f"{acquisition_mode} Treasury page")
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
        return AcquiredTreasuryPage(
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


def acquire_treasury_page(
    pin: TreasuryPageSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: TreasuryPageFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredTreasuryPage:
    """Acquire one exact page through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise TreasuryAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise TreasuryAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise TreasuryAcquisitionError(f"local Treasury source is not a regular file: {local_path}")
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
        raise TreasuryAcquisitionError("Treasury page is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise TreasuryAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise TreasurySourceDriftError(f"Treasury page content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


class _TextCollector(HTMLParser):
    """Collect visible page text, dropping script/style contents."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.chunks.append(data)


def _extract_text(payload: bytes) -> str:
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TreasurySourceDriftError("Treasury page is not UTF-8") from error
    collector = _TextCollector()
    try:
        collector.feed(decoded)
        collector.close()
    except Exception as error:
        raise TreasurySourceDriftError("Treasury page is malformed HTML") from error
    return " ".join("".join(collector.chunks).split())


def _extract_edition_date(text: str, *, location: str) -> str:
    match = _LAST_UPDATED.search(text)
    if match is None:
        raise TreasurySourceDriftError(f"{location} is missing its 'Last Updated:' edition marker")
    try:
        parsed = datetime.strptime(match.group(1), "%B %d, %Y").replace(tzinfo=UTC).date()
    except ValueError as error:
        raise TreasurySourceDriftError(f"{location} 'Last Updated:' date is unparseable") from error
    return parsed.isoformat()


def _read_acquired_payload(page: AcquiredTreasuryPage) -> bytes:
    payload = page.path.read_bytes()
    _verify_payload(payload, page.pin, location="parsed Treasury page")
    return payload


@dataclass(frozen=True, slots=True)
class ParsedTASComponentFormat:
    """The Component TAS field list and edition read from one exact capture."""

    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    edition_date: str
    component_field_labels: tuple[str, ...]
    gaps: tuple[str, ...]


def parse_tas_component_page(page: AcquiredTreasuryPage) -> ParsedTASComponentFormat:
    """Parse the Component TAS format page's field list and edition date."""

    payload = _read_acquired_payload(page)
    text = _extract_text(payload)
    for marker in TAS_COMPONENT_FORMAT_SOURCE.structural_markers:
        if marker not in text:
            raise TreasurySourceDriftError(f"missing expected component marker {marker!r}")
    edition_date = _extract_edition_date(text, location="Component TAS format page")
    return ParsedTASComponentFormat(
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        retrieved_at=page.pin.retrieved_at,
        edition_date=edition_date,
        component_field_labels=TAS_COMPONENT_FORMAT_SOURCE.structural_markers,
        gaps=TREASURY_TAS_FAST_BOOK_GAPS,
    )


@dataclass(frozen=True, slots=True)
class ParsedFASTBookDescription:
    """The FAST Book part/fund-group structure and edition read from one capture."""

    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    edition_date: str
    part_fund_groups: Mapping[FASTBookPart, tuple[FundGroup, ...]]
    gaps: tuple[str, ...]


def parse_fast_book_description_page(page: AcquiredTreasuryPage) -> ParsedFASTBookDescription:
    """Parse the FAST Book Description of Contents page's structure and edition."""

    payload = _read_acquired_payload(page)
    text = _extract_text(payload)
    for marker in FAST_BOOK_DESCRIPTION_SOURCE.structural_markers:
        if marker not in text:
            raise TreasurySourceDriftError(f"missing expected FAST Book marker {marker!r}")
    edition_date = _extract_edition_date(text, location="FAST Book Description of Contents page")
    return ParsedFASTBookDescription(
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        retrieved_at=page.pin.retrieved_at,
        edition_date=edition_date,
        part_fund_groups=PART_FUND_GROUPS,
        gaps=TREASURY_TAS_FAST_BOOK_GAPS,
    )


# ---------------------------------------------------------------------------
# Treasury Account Symbol component identifier shape
# ---------------------------------------------------------------------------

_TAS_RECORD_FIELDS = ("SP", "ATA", "AID", "BPOA", "EPOA", "A", "MAIN", "SUB")
_TAS_REQUIRED_FIELDS = frozenset({"AID", "MAIN"})


@dataclass(frozen=True, slots=True)
class TASComponents:
    """One Treasury Account Symbol, retained as its eight named components.

    Field widths follow the published OMB Circular A-11 / Governmentwide
    Spending Data Model Component TAS convention; see
    ``TREASURY_TAS_FAST_BOOK_GAPS`` for why the captured Treasury page itself
    does not confirm them.
    """

    sub_level_prefix: str | None
    allocation_transfer_agency: str | None
    agency_identifier: str
    beginning_period_of_availability: str | None
    ending_period_of_availability: str | None
    availability_type_code: str | None
    main_account: str
    sub_account: str

    def __post_init__(self) -> None:
        if self.sub_level_prefix is not None and _SP_PATTERN.fullmatch(self.sub_level_prefix) is None:
            raise TASComponentError("sub_level_prefix must be exactly 2 digits")
        if (
            self.allocation_transfer_agency is not None
            and _ATA_PATTERN.fullmatch(self.allocation_transfer_agency) is None
        ):
            raise TASComponentError("allocation_transfer_agency must be exactly 3 digits")
        if _AID_PATTERN.fullmatch(self.agency_identifier) is None:
            raise TASComponentError("agency_identifier must be exactly 3 digits")
        if (
            self.beginning_period_of_availability is not None
            and _POA_PATTERN.fullmatch(self.beginning_period_of_availability) is None
        ):
            raise TASComponentError("beginning_period_of_availability must be exactly 4 digits")
        if (
            self.ending_period_of_availability is not None
            and _POA_PATTERN.fullmatch(self.ending_period_of_availability) is None
        ):
            raise TASComponentError("ending_period_of_availability must be exactly 4 digits")
        if (self.beginning_period_of_availability is None) != (self.ending_period_of_availability is None):
            raise TASComponentError(
                "beginning_period_of_availability and ending_period_of_availability "
                "must be given together or both left unset"
            )
        if (
            self.beginning_period_of_availability is not None
            and self.ending_period_of_availability is not None
            and self.beginning_period_of_availability > self.ending_period_of_availability
        ):
            raise TASComponentError("beginning_period_of_availability must not be after ending_period_of_availability")
        if (
            self.availability_type_code is not None
            and _AVAILABILITY_TYPE_PATTERN.fullmatch(self.availability_type_code) is None
        ):
            raise TASComponentError("availability_type_code must be exactly one uppercase letter")
        if _MAIN_PATTERN.fullmatch(self.main_account) is None:
            raise TASComponentError("main_account must be exactly 4 digits")
        if _SUB_PATTERN.fullmatch(self.sub_account) is None:
            raise TASComponentError("sub_account must be exactly 3 digits")


def parse_tas_components(record: Mapping[str, object]) -> TASComponents:
    """Parse one CARS-style Component TAS record into strict, typed fields."""

    unknown = set(record) - set(_TAS_RECORD_FIELDS)
    if unknown:
        raise TASComponentError(f"unknown Component TAS fields: {sorted(unknown)}")
    missing = _TAS_REQUIRED_FIELDS - set(record)
    if missing:
        raise TASComponentError(f"missing required Component TAS fields: {sorted(missing)}")

    def field(name: str, *, required: bool = False) -> str | None:
        value = record.get(name)
        if value is None:
            if required:
                raise TASComponentError(f"{name} must not be empty")
            return None
        if not isinstance(value, str) or not value.strip():
            raise TASComponentError(f"{name} must be non-empty text")
        return value

    sub_account = field("SUB") or _DEFAULT_SUB_ACCOUNT
    return TASComponents(
        sub_level_prefix=field("SP"),
        allocation_transfer_agency=field("ATA"),
        agency_identifier=cast(str, field("AID", required=True)),
        beginning_period_of_availability=field("BPOA"),
        ending_period_of_availability=field("EPOA"),
        availability_type_code=field("A"),
        main_account=cast(str, field("MAIN", required=True)),
        sub_account=sub_account,
    )


def _canonical_component(value: str | None) -> str:
    return value if value is not None else ""


def tas_identifier(
    components: TASComponents,
    *,
    observed_at: str | None,
    source_digest: str | None,
) -> ControlledIdentifier:
    """Build a capture-local, order-preserving identifier for one TAS.

    The returned value is a RefSpec-local dot-joined encoding of the eight
    Component TAS fields, in their documented order, with an absent field
    left blank between two dots. It is not a Treasury-published display
    string: Treasury's own systems render a TAS differently depending on the
    reporting context, and no single canonical string format was found.
    """

    value = ".".join(
        _canonical_component(component)
        for component in (
            components.sub_level_prefix,
            components.allocation_transfer_agency,
            components.agency_identifier,
            components.beginning_period_of_availability,
            components.ending_period_of_availability,
            components.availability_type_code,
            components.main_account,
            components.sub_account,
        )
    )
    return ControlledIdentifier(
        value=value,
        kind="treasuryAccountSymbolComponents",
        authority_uri=TREASURY_IDENTIFIER_AUTHORITY_URI,
        source_uri=TAS_COMPONENT_FORMAT_SOURCE.source_url,
        observed_at=observed_at,
        effective_at=None,
        source_digest=source_digest,
    )


def parse_tas_canonical_value(value: str) -> TASComponents:
    """Invert :func:`tas_identifier`'s canonical encoding back to components."""

    parts = value.split(".")
    if len(parts) != len(_TAS_RECORD_FIELDS):
        raise TASComponentError("canonical TAS value must have exactly eight dot-separated fields")
    record = {name: (part or None) for name, part in zip(_TAS_RECORD_FIELDS, parts, strict=True)}
    return parse_tas_components(record)


# ---------------------------------------------------------------------------
# FAST Book account-title record shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FASTBookAccountRecord:
    """One agency/account-title record, shaped like a FAST Book entry.

    This is an identifier-shape and code-value capture, not bulk FAST Book
    content: RefSpec does not fetch or store the FAST Book's PDF row data.
    """

    agency_identifier: str
    main_account: str
    account_title: str
    fast_book_part: FASTBookPart
    fund_group: FundGroup
    statutory_citation: str | None
    edition_date: str

    def __post_init__(self) -> None:
        if _AID_PATTERN.fullmatch(self.agency_identifier) is None:
            raise FASTBookRecordError("agency_identifier must be exactly 3 digits")
        if _MAIN_PATTERN.fullmatch(self.main_account) is None:
            raise FASTBookRecordError("main_account must be exactly 4 digits")
        if not self.account_title.strip():
            raise FASTBookRecordError("account_title must not be empty")
        if self.fast_book_part not in PART_FUND_GROUPS:
            raise FASTBookRecordError(f"fast_book_part must be one of {sorted(PART_FUND_GROUPS)}")
        if self.fund_group not in PART_FUND_GROUPS[self.fast_book_part]:
            raise FASTBookRecordError(
                f"fund_group {self.fund_group!r} is not a documented fund group for Part {self.fast_book_part}"
            )
        requires_citation = self.fund_group in _CITED_FUND_GROUPS[self.fast_book_part]
        if requires_citation and not (self.statutory_citation and self.statutory_citation.strip()):
            raise FASTBookRecordError(
                f"Part {self.fast_book_part} {self.fund_group} fund accounts requires a statutory citation"
            )
        if not requires_citation and self.statutory_citation is not None:
            raise FASTBookRecordError(
                f"Part {self.fast_book_part} {self.fund_group} fund general fund account "
                "must not carry a statutory citation"
            )
        if date.fromisoformat(self.edition_date) is None:
            raise FASTBookRecordError("edition_date must be an ISO 8601 date")  # pragma: no cover - defensive


def validate_fast_book_account_record(
    raw: Mapping[str, object],
    *,
    description: ParsedFASTBookDescription,
) -> FASTBookAccountRecord:
    """Validate one illustrative FAST Book-shaped record against its edition."""

    required = {"AID", "MAIN", "ACCOUNT_TITLE", "PART", "FUND_GROUP", "STATUTORY_CITATION"}
    if set(raw) != required:
        raise FASTBookRecordError(f"FAST Book record fields must be exactly {sorted(required)}")

    def text(name: str) -> str:
        value = raw[name]
        if not isinstance(value, str) or not value.strip():
            raise FASTBookRecordError(f"{name} must be non-empty text")
        return value

    citation = raw["STATUTORY_CITATION"]
    if citation is not None and (not isinstance(citation, str) or not citation.strip()):
        raise FASTBookRecordError("STATUTORY_CITATION must be non-empty text or null")

    return FASTBookAccountRecord(
        agency_identifier=text("AID"),
        main_account=text("MAIN"),
        account_title=text("ACCOUNT_TITLE"),
        fast_book_part=cast(FASTBookPart, text("PART")),
        fund_group=cast(FundGroup, text("FUND_GROUP")),
        statutory_citation=citation,
        edition_date=description.edition_date,
    )


def fast_book_identifier(
    record: FASTBookAccountRecord,
    *,
    observed_at: str | None,
    source_digest: str | None,
) -> ControlledIdentifier:
    """Build a capture-local identifier for one FAST Book-shaped account record."""

    return ControlledIdentifier(
        value=f"{record.agency_identifier}-{record.main_account}",
        kind="fastBookAccountIdentifier",
        authority_uri=TREASURY_IDENTIFIER_AUTHORITY_URI,
        source_uri=FAST_BOOK_DESCRIPTION_SOURCE.source_url,
        observed_at=observed_at,
        effective_at=None,
        source_digest=source_digest,
    )


# ---------------------------------------------------------------------------
# Deterministic fiscal edition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TreasuryTASFastBookEdition:
    """The recorded edition of both captured pages, plus known gaps."""

    tas_component_format_edition: str
    fast_book_description_edition: str
    gaps: tuple[str, ...]


def assemble_treasury_tas_fast_book_edition(
    tas_page: ParsedTASComponentFormat,
    fast_book_page: ParsedFASTBookDescription,
) -> TreasuryTASFastBookEdition:
    """Combine both parsed pages' edition dates into one recorded edition."""

    return TreasuryTASFastBookEdition(
        tas_component_format_edition=tas_page.edition_date,
        fast_book_description_edition=fast_book_page.edition_date,
        gaps=TREASURY_TAS_FAST_BOOK_GAPS,
    )


__all__ = [
    "FAST_BOOK_DESCRIPTION_2026_08_03",
    "FAST_BOOK_DESCRIPTION_SOURCE",
    "PART_FUND_GROUPS",
    "TAS_COMPONENT_FORMAT_2026_08_03",
    "TAS_COMPONENT_FORMAT_SOURCE",
    "TREASURY_IDENTIFIER_AUTHORITY_URI",
    "TREASURY_PUBLISHER",
    "TREASURY_TAS_FAST_BOOK_GAPS",
    "AcquiredTreasuryPage",
    "AcquisitionMode",
    "FASTBookAccountRecord",
    "FASTBookPart",
    "FASTBookRecordError",
    "FetchedTreasuryPage",
    "FundGroup",
    "ParsedFASTBookDescription",
    "ParsedTASComponentFormat",
    "TASComponentError",
    "TASComponents",
    "TreasuryAcquisitionError",
    "TreasuryPageFetcher",
    "TreasuryPageSnapshotPin",
    "TreasuryPageSource",
    "TreasurySourceDriftError",
    "TreasuryTASFastBookEdition",
    "TreasuryTASFastBookError",
    "acquire_treasury_page",
    "assemble_treasury_tas_fast_book_edition",
    "fast_book_identifier",
    "parse_fast_book_description_page",
    "parse_tas_canonical_value",
    "parse_tas_component_page",
    "parse_tas_components",
    "sha256_digest",
    "tas_identifier",
    "validate_fast_book_account_record",
]
