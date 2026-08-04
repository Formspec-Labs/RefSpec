"""Source-faithful capture of Census APES/ASPEP and NASBO SER classification codes.

The catalog decision for this source pair is explicit: these are cross-state
*mapping* references only. The Census Bureau's Government Finance and
Employment Classification Manual (advertised at ``Class_Manual.html``, but
delivered as a 2006 PDF) and NASBO's State Expenditure Report classify
government spending into statistical functions, objects, fund sources, and
program areas so that fifty different states' budgets can be compared on one
axis. Neither classification replaces a state's own enacted chart of
accounts or the legal identity of a state program; a RefSpec state-budget
document must keep its own native funds, accounts, agencies, programs, and
amounts, and may only *attach* one of these codes as a secondary,
independently validated cross-reference. That mapping-only role is recorded
directly in every package this module builds, not merely in code comments.

Two small, genuinely complete HTML code lists are directly pinnable:

* Census's ASPEP "Item Code (Functional Category)" list -- a closed set of
  three-digit statistical function codes.
* Census's ASPEP "Data Flags" list -- a closed set of single-letter codes
  describing how one reported number was derived, grouped under the
  publisher's own "Reported Data" / "Imputed Data" section headings.

The 2006 Classification Manual PDF also documents object-of-expenditure and
fund-source categories, but census.gov does not publish those as a small,
independently fetchable HTML code list the way it does the two lists above;
this module does not parse the PDF, and that gap is recorded explicitly
rather than silently ingested from a bulk table extraction.

NASBO's State Expenditure Report page publishes its own current program-area
breakdown as the "Chapters" list on its report landing page. NASBO assigns no
stable per-chapter code or IRI to a program area -- only its English title --
so every NASBO observation carries an empty identifier list and stays
capture-local evidence, never a minted publisher identifier.

Live retrieval is provider-independent. Callers inject a fetcher or provide
an already captured local file. Importing this module never opens a network
connection.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import (
    ResourceUse,
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

CENSUS_HOSTS = frozenset({"www.census.gov", "census.gov"})
NASBO_HOSTS = frozenset({"www.nasbo.org", "nasbo.org"})
CENSUS_IDENTIFIER_AUTHORITY_URI = "https://www.census.gov/"
LANGUAGE = "en"

ResourceName = Literal[
    "censusFunctionItemCodes",
    "censusDataFlagCodes",
    "nasboProgramAreaChapters",
]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_FUNCTION_ITEM_ROW = re.compile(r"^(?P<code>\d{3}) = (?P<label>.+)$")
_DATA_FLAG_CODE = re.compile(r"^[A-Z]$")
_DATA_FLAG_SECTIONS = ("Reported Data", "Imputed Data")
_CHAPTER_CELL = re.compile(r"^(?P<title>.+?)\s+Read \| Tables$")
# Observed generic bot-block/challenge markers; neither census.gov nor
# nasbo.org is known to serve these, but a future capture that returns one
# must fail closed rather than be cached as if it were the requested page.
_CHALLENGE_MARKERS = (
    b"<title>access denied</title>",
    b"cf-chl-",
    b"challenge-platform",
    b"cf-mitigated",
    b"attention required! | cloudflare",
    b"just a moment...</title>",
)


class CensusNasboResourceError(ValueError):
    """Base class for Census/NASBO controlled-code failures."""


class CensusNasboAcquisitionError(CensusNasboResourceError):
    """Exact official source bytes could not be acquired safely."""


class CensusNasboSourceDriftError(CensusNasboResourceError):
    """A captured page no longer matches the reviewed structure or pin."""


class CensusNasboMappingError(CensusNasboResourceError):
    """A mapping record carries an unknown or malformed classification code."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class CensusNasboSource:
    """One official Census or NASBO page pinned as a small controlled code list."""

    resource_name: ResourceName
    title: str
    source_url: str
    hosts: frozenset[str]
    filename: str
    expected_count: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname not in self.hosts:
            raise CensusNasboAcquisitionError("source_url must be an official HTTPS URL on the declared host set")
        if parsed.username is not None or parsed.password is not None:
            raise CensusNasboAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise CensusNasboAcquisitionError("filename must be one plain path component")
        if self.expected_count <= 0:
            raise CensusNasboAcquisitionError("expected_count must be positive")


CENSUS_FUNCTION_ITEM_CODES_SOURCE = CensusNasboSource(
    resource_name="censusFunctionItemCodes",
    title="Item Code (Functional Category)",
    source_url=("https://www.census.gov/programs-surveys/apes/technical-documentation/code-lists/data-function.html"),
    hosts=CENSUS_HOSTS,
    filename="census-aspep-function-item-codes.html",
    expected_count=33,
)
CENSUS_DATA_FLAG_CODES_SOURCE = CensusNasboSource(
    resource_name="censusDataFlagCodes",
    title="Data Flags",
    source_url=("https://www.census.gov/programs-surveys/apes/technical-documentation/code-lists/data-flags.html"),
    hosts=CENSUS_HOSTS,
    filename="census-aspep-data-flag-codes.html",
    expected_count=16,
)
NASBO_PROGRAM_AREA_CHAPTERS_SOURCE = CensusNasboSource(
    resource_name="nasboProgramAreaChapters",
    title="State Expenditure Report",
    source_url="https://www.nasbo.org/mainsite/reports-data/state-expenditure-report",
    hosts=NASBO_HOSTS,
    filename="nasbo-state-expenditure-report.html",
    expected_count=7,
)


@dataclass(frozen=True, slots=True)
class CensusNasboSnapshotPin:
    """Exact identity of one official captured page."""

    source: CensusNasboSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise CensusNasboAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise CensusNasboAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise CensusNasboAcquisitionError("retrieved_at must not be empty")


# These pins were established from one real capture taken 2026-08-03. Both
# census.gov pages are served by the same AEM template; the NASBO page is the
# live State Expenditure Report landing page and will be replaced by NASBO
# with each new report edition -- a future re-pin is expected, not a defect.
CENSUS_FUNCTION_ITEM_CODES_2026_08_03 = CensusNasboSnapshotPin(
    source=CENSUS_FUNCTION_ITEM_CODES_SOURCE,
    retrieved_at="2026-08-03T19:15:00Z",
    expected_sha256="sha256:77b6ddf18572165b6e4526042dacba9fcff80b79cc7f21f1193db3210730dcb3",
    expected_byte_length=321_793,
)
CENSUS_DATA_FLAG_CODES_2026_08_03 = CensusNasboSnapshotPin(
    source=CENSUS_DATA_FLAG_CODES_SOURCE,
    retrieved_at="2026-08-03T19:15:00Z",
    expected_sha256="sha256:ef47e5a56d2997b4a05f1a3d5c6d112c92735bc876990ae03038020d07b19c39",
    expected_byte_length=323_893,
)
NASBO_PROGRAM_AREA_CHAPTERS_2026_08_03 = CensusNasboSnapshotPin(
    source=NASBO_PROGRAM_AREA_CHAPTERS_SOURCE,
    retrieved_at="2026-08-03T19:15:00Z",
    expected_sha256="sha256:cff509abccd46a7bba32e5261164a430934db29004024c2b66d389d83ef9ba57",
    expected_byte_length=189_899,
)


@dataclass(frozen=True, slots=True)
class FetchedCensusNasboPage:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class CensusNasboPageFetcher(Protocol):
    """Small transport boundary for the official Census and NASBO pages."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedCensusNasboPage:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredCensusNasboPage:
    """One verified source page in the content-addressed store."""

    pin: CensusNasboSnapshotPin
    path: Path
    sha256: str
    byte_length: int
    source_url: str
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def _validate_html_payload(payload: bytes) -> None:
    lowered = payload[:64_000].lower()
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        raise CensusNasboSourceDriftError("source returned an access-denied or challenge page, not the requested page")
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise CensusNasboSourceDriftError("captured payload is not an HTML document")


def _validate_resolved_url(value: str, hosts: frozenset[str]) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in hosts:
        raise CensusNasboAcquisitionError("fetcher resolved_url must remain on the official HTTPS source host")
    if parsed.username is not None or parsed.password is not None:
        raise CensusNasboAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: CensusNasboSnapshotPin, *, location: str) -> tuple[str, int]:
    _validate_html_payload(payload)
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise CensusNasboSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise CensusNasboSourceDriftError(
            f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}"
        )
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: CensusNasboSnapshotPin) -> AcquiredCensusNasboPage:
    if path.is_symlink() or not path.is_file():
        raise CensusNasboAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached Census/NASBO source",
    )
    return AcquiredCensusNasboPage(
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
    pin: CensusNasboSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredCensusNasboPage:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} Census/NASBO source",
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
        return AcquiredCensusNasboPage(
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


def acquire_census_nasbo_page(
    pin: CensusNasboSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: CensusNasboPageFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredCensusNasboPage:
    """Acquire one exact page through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise CensusNasboAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise CensusNasboAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise CensusNasboAcquisitionError(f"local Census/NASBO source is not a regular file: {local_path}")
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
        raise CensusNasboAcquisitionError(
            "Census/NASBO source is not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise CensusNasboAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url, pin.source.hosts)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise CensusNasboSourceDriftError(
            f"{pin.source.resource_name} content type drifted to {fetched.content_type!r}"
        )
    _validate_html_payload(fetched.body)
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _normalize_text(chunks: Sequence[str]) -> str:
    return " ".join("".join(chunks).split())


class _LandmarkTableParser(HTMLParser):
    """Collect one page's single landmark heading and its one data table.

    Only the page's declared landmark elements are tracked -- an ``<h1>``
    matched by one attribute/value pair, and (for pages that need it) an
    ``<h2>`` with exact text that must appear before the table this module
    treats as data. A page with zero or more than one matching landmark, or
    zero or more than one ``<table>``, is left for the caller to reject as
    drift: this parser only reports counts and row text, it never guesses
    which element was intended.
    """

    def __init__(
        self,
        *,
        h1_attr: str,
        h1_value: str,
        required_h2_text: str | None = None,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self._h1_attr = h1_attr
        self._h1_value = h1_value
        self._required_h2_text = required_h2_text

        self.h1_match_count = 0
        self.h1_text: str | None = None
        self.h2_landmark_seen = required_h2_text is None
        self.table_open_count = 0
        self.table_open_after_landmark_count = 0
        self.rows: list[tuple[tuple[bool, str], ...]] = []

        self._h1_buf: list[str] | None = None
        self._h2_buf: list[str] | None = None
        self._in_table = False
        self._row_cells: list[tuple[bool, str]] | None = None
        self._cell_buf: list[str] | None = None
        self._cell_is_th = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs))

    def _open(self, tag: str, attr_map: dict[str, str | None]) -> None:
        if tag == "h1":
            if (attr_map.get(self._h1_attr) or "").strip() == self._h1_value:
                self.h1_match_count += 1
                self._h1_buf = []
            else:
                self._h1_buf = None
        if tag == "h2":
            self._h2_buf = []
        if tag == "table":
            self.table_open_count += 1
            self._in_table = True
            if self.h2_landmark_seen:
                self.table_open_after_landmark_count += 1
        if tag == "tr" and self._in_table:
            self._row_cells = []
        if tag in ("td", "th") and self._in_table and self._row_cells is not None:
            self._cell_buf = []
            self._cell_is_th = tag == "th"
        if tag == "br" and self._cell_buf is not None:
            self._cell_buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._h1_buf is not None:
            if self.h1_text is None:
                self.h1_text = _normalize_text(self._h1_buf)
            self._h1_buf = None
        if tag == "h2" and self._h2_buf is not None:
            text = _normalize_text(self._h2_buf)
            self._h2_buf = None
            if self._required_h2_text is not None and text == self._required_h2_text:
                self.h2_landmark_seen = True
        if tag in ("td", "th") and self._cell_buf is not None:
            text = _normalize_text(self._cell_buf)
            if self._row_cells is not None:
                self._row_cells.append((self._cell_is_th, text))
            self._cell_buf = None
        if tag == "tr" and self._row_cells is not None:
            self.rows.append(tuple(self._row_cells))
            self._row_cells = None
        if tag == "table":
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._h1_buf is not None:
            self._h1_buf.append(data)
        if self._h2_buf is not None:
            self._h2_buf.append(data)
        if self._cell_buf is not None:
            self._cell_buf.append(data)


@dataclass(frozen=True, slots=True)
class CensusNasboCode:
    """One exact publisher label plus every identifier published for that row.

    ``section`` is populated only for Census Data Flags, which the publisher
    groups under "Reported Data" / "Imputed Data" headings; every other
    resource leaves it ``None`` rather than inventing a grouping the
    publisher never assigned.
    """

    resource_name: ResourceName
    use: ResourceUse
    publisher_label: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    section: str | None = None
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedCensusNasboResource:
    """A parsed, digest-pinned Census or NASBO code list."""

    source: CensusNasboSource
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    codes: tuple[CensusNasboCode, ...]
    gaps: tuple[str, ...]

    def by_code(self) -> dict[str, CensusNasboCode]:
        """Index the publisher-issued code for resources that carry one."""

        code_kind = {
            "censusFunctionItemCodes": "censusFunctionItemCode",
            "censusDataFlagCodes": "censusDataFlagCode",
        }.get(self.source.resource_name)
        if code_kind is None:
            raise CensusNasboSourceDriftError(
                f"{self.source.resource_name} publishes no stable per-row code; use by_label()"
            )
        result: dict[str, CensusNasboCode] = {}
        for entry in self.codes:
            matches = [identifier for identifier in entry.identifiers if identifier.kind == code_kind]
            if len(matches) != 1:
                raise CensusNasboSourceDriftError(
                    f"{self.source.resource_name} row must retain exactly one {code_kind}"
                )
            result[matches[0].value] = entry
        return result

    def by_label(self) -> dict[str, CensusNasboCode]:
        """Index the exact publisher label, the only stable key NASBO offers."""

        result: dict[str, CensusNasboCode] = {}
        for entry in self.codes:
            result[entry.publisher_label] = entry
        return result


def _read_acquired_payload(page: AcquiredCensusNasboPage) -> bytes:
    payload = page.path.read_bytes()
    _verify_payload(payload, page.pin, location="parsed Census/NASBO source")
    return payload


def _decode_html(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CensusNasboSourceDriftError("captured page is not UTF-8") from error


def _feed(parser: _LandmarkTableParser, decoded: str) -> None:
    try:
        parser.feed(decoded)
        parser.close()
    except CensusNasboResourceError:
        raise
    except Exception as error:
        raise CensusNasboSourceDriftError("captured page is malformed HTML") from error


def _make_identifier(*, value: str, kind: str, page: AcquiredCensusNasboPage) -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=kind,
        authority_uri=CENSUS_IDENTIFIER_AUTHORITY_URI,
        source_uri=page.pin.source.source_url,
        observed_at=page.pin.retrieved_at,
        effective_at=None,
        source_digest=page.sha256,
    )


def parse_census_function_item_codes(page: AcquiredCensusNasboPage) -> ParsedCensusNasboResource:
    """Parse the exact ASPEP function item codes without minting subjects."""

    source = CENSUS_FUNCTION_ITEM_CODES_SOURCE
    if page.pin.source != source:
        raise CensusNasboSourceDriftError("page was not acquired against the function-item-codes source")
    decoded = _decode_html(_read_acquired_payload(page))
    parser = _LandmarkTableParser(h1_attr="class", h1_value="cmp-title__text")
    _feed(parser, decoded)

    # census.gov's AEM template renders the title landmark twice with
    # identical text (a visible heading plus a duplicate for another
    # breakpoint); require at least one match rather than exactly one.
    if parser.h1_match_count < 1 or parser.h1_text != source.title:
        raise CensusNasboSourceDriftError(f"page must contain at least one {source.title!r} heading")
    if parser.table_open_count != 1:
        raise CensusNasboSourceDriftError("page must contain exactly one function item code table")
    if len(parser.rows) != source.expected_count:
        raise CensusNasboSourceDriftError(
            f"function item code count drift: expected {source.expected_count}, parsed {len(parser.rows)}"
        )

    codes: list[CensusNasboCode] = []
    seen_codes: set[str] = set()
    for ordinal, row in enumerate(parser.rows):
        if len(row) != 1 or row[0][0]:
            raise CensusNasboSourceDriftError(f"function item code row {ordinal} must be exactly one <td> cell")
        match = _FUNCTION_ITEM_ROW.fullmatch(row[0][1])
        if match is None:
            raise CensusNasboSourceDriftError(f"function item code row {ordinal} does not match 'CODE = Label'")
        code = match.group("code")
        label = match.group("label").strip()
        if not label:
            raise CensusNasboSourceDriftError(f"function item code row {ordinal} has an empty label")
        if code in seen_codes:
            raise CensusNasboSourceDriftError(f"function item code {code!r} is duplicated")
        seen_codes.add(code)
        codes.append(
            CensusNasboCode(
                resource_name="censusFunctionItemCodes",
                use="deterministicMetadata",
                publisher_label=label,
                source_url=source.source_url,
                identifiers=(_make_identifier(value=code, kind="censusFunctionItemCode", page=page),),
            )
        )

    return ParsedCensusNasboResource(
        source=source,
        retrieved_at=page.pin.retrieved_at,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        codes=tuple(codes),
        gaps=CENSUS_NASBO_PORTFOLIO_GAPS,
    )


def parse_census_data_flag_codes(page: AcquiredCensusNasboPage) -> ParsedCensusNasboResource:
    """Parse the exact ASPEP data flag codes, keeping the publisher's sections."""

    source = CENSUS_DATA_FLAG_CODES_SOURCE
    if page.pin.source != source:
        raise CensusNasboSourceDriftError("page was not acquired against the data-flag-codes source")
    decoded = _decode_html(_read_acquired_payload(page))
    parser = _LandmarkTableParser(h1_attr="class", h1_value="cmp-title__text")
    _feed(parser, decoded)

    # census.gov's AEM template renders the title landmark twice with
    # identical text (a visible heading plus a duplicate for another
    # breakpoint); require at least one match rather than exactly one.
    if parser.h1_match_count < 1 or parser.h1_text != source.title:
        raise CensusNasboSourceDriftError(f"page must contain at least one {source.title!r} heading")
    if parser.table_open_count != 1:
        raise CensusNasboSourceDriftError("page must contain exactly one data flags table")

    codes: list[CensusNasboCode] = []
    seen_codes: set[str] = set()
    section: str | None = None
    for ordinal, row in enumerate(parser.rows):
        if len(row) == 1:
            is_th, text = row[0]
            if not is_th:
                raise CensusNasboSourceDriftError(
                    f"data flag row {ordinal} is a lone cell that is not a section header"
                )
            if text not in _DATA_FLAG_SECTIONS:
                raise CensusNasboSourceDriftError(f"data flag section header {text!r} is not a known section")
            section = text
            continue
        if len(row) != 2:
            raise CensusNasboSourceDriftError(f"data flag row {ordinal} must contain one or two cells")
        (code_is_th, code), (definition_is_th, definition) = row
        if code_is_th or definition_is_th:
            raise CensusNasboSourceDriftError(f"data flag row {ordinal} cells must not be header cells")
        if section is None:
            raise CensusNasboSourceDriftError(f"data flag row {ordinal} appears before any section header")
        if _DATA_FLAG_CODE.fullmatch(code) is None:
            raise CensusNasboSourceDriftError(f"data flag row {ordinal} has a malformed code {code!r}")
        if not definition.strip():
            raise CensusNasboSourceDriftError(f"data flag row {ordinal} has an empty definition")
        if code in seen_codes:
            raise CensusNasboSourceDriftError(f"data flag code {code!r} is duplicated")
        seen_codes.add(code)
        codes.append(
            CensusNasboCode(
                resource_name="censusDataFlagCodes",
                use="deterministicMetadata",
                publisher_label=definition,
                source_url=source.source_url,
                identifiers=(_make_identifier(value=code, kind="censusDataFlagCode", page=page),),
                section=section,
            )
        )

    if len(codes) != source.expected_count:
        raise CensusNasboSourceDriftError(
            f"data flag code count drift: expected {source.expected_count}, parsed {len(codes)}"
        )

    return ParsedCensusNasboResource(
        source=source,
        retrieved_at=page.pin.retrieved_at,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        codes=tuple(codes),
        gaps=CENSUS_NASBO_PORTFOLIO_GAPS,
    )


def parse_nasbo_program_area_chapters(page: AcquiredCensusNasboPage) -> ParsedCensusNasboResource:
    """Parse the exact NASBO SER program-area chapter titles.

    NASBO assigns no stable per-chapter code, so every returned
    :class:`CensusNasboCode` carries an empty ``identifiers`` tuple and its
    exact English title is the only stable key -- see :meth:`by_label`.
    """

    source = NASBO_PROGRAM_AREA_CHAPTERS_SOURCE
    if page.pin.source != source:
        raise CensusNasboSourceDriftError("page was not acquired against the nasbo-program-area-chapters source")
    decoded = _decode_html(_read_acquired_payload(page))
    parser = _LandmarkTableParser(h1_attr="id", h1_value="PageTitleH1", required_h2_text="Chapters")
    _feed(parser, decoded)

    # Require at least one landmark match rather than exactly one: a template
    # may legitimately render the title heading more than once.
    if parser.h1_match_count < 1 or parser.h1_text != source.title:
        raise CensusNasboSourceDriftError(f"page must contain at least one {source.title!r} heading")
    if not parser.h2_landmark_seen:
        raise CensusNasboSourceDriftError("page must contain a 'Chapters' heading before its program-area table")
    if parser.table_open_count != 1 or parser.table_open_after_landmark_count != 1:
        raise CensusNasboSourceDriftError("page must contain exactly one table, appearing after the Chapters heading")

    codes: list[CensusNasboCode] = []
    seen_titles: set[str] = set()
    for row_ordinal, row in enumerate(parser.rows):
        for cell_ordinal, (is_th, text) in enumerate(row):
            if is_th:
                raise CensusNasboSourceDriftError(
                    f"chapters table row {row_ordinal} cell {cell_ordinal} is a header cell"
                )
            if not text:
                # A trailing empty grid cell pads an odd chapter count to a
                # two-column layout; it is not a missing chapter.
                continue
            match = _CHAPTER_CELL.fullmatch(text)
            if match is None:
                raise CensusNasboSourceDriftError(f"chapters table cell does not match 'Title Read | Tables': {text!r}")
            title = match.group("title").strip()
            if not title:
                raise CensusNasboSourceDriftError("chapters table cell has an empty title")
            if title in seen_titles:
                raise CensusNasboSourceDriftError(f"NASBO program-area chapter {title!r} is duplicated")
            seen_titles.add(title)
            codes.append(
                CensusNasboCode(
                    resource_name="nasboProgramAreaChapters",
                    use="deterministicMetadata",
                    publisher_label=title,
                    source_url=source.source_url,
                    # NASBO documents no stable code or IRI for a chapter; see
                    # CENSUS_NASBO_PORTFOLIO_GAPS.
                    identifiers=(),
                )
            )

    if len(codes) != source.expected_count:
        raise CensusNasboSourceDriftError(
            f"NASBO program-area chapter count drift: expected {source.expected_count}, parsed {len(codes)}"
        )

    return ParsedCensusNasboResource(
        source=source,
        retrieved_at=page.pin.retrieved_at,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        codes=tuple(codes),
        gaps=CENSUS_NASBO_PORTFOLIO_GAPS,
    )


CENSUS_NASBO_PORTFOLIO_GAPS = (
    (
        "These classifications are mapping references only: they do not replace "
        "any state's enacted chart of accounts or the legal identity of a state "
        "program. A RefSpec state-budget document keeps its own native funds, "
        "accounts, agencies, programs, fiscal year, amounts, and status; a Census "
        "or NASBO classification may only be attached as a secondary cross-reference."
    ),
    (
        "The Census Bureau's object-of-expenditure and fund-source classification "
        "categories are documented in the 2006 Government Finance and Employment "
        "Classification Manual PDF linked from Class_Manual.html, not in a small "
        "pinned HTML code list; this module captures only the function item codes "
        "and data-quality flag codes that census.gov publishes as their own pages."
    ),
    (
        "NASBO's State Expenditure Report publishes no stable per-chapter code or "
        "IRI for a program area, only the chapter's English title on the current "
        "report's landing page; NASBO program-area observations carry no "
        "ControlledIdentifier and remain capture-local evidence."
    ),
)


@dataclass(frozen=True, slots=True)
class CensusNasboPortfolio:
    """The three imported resources and their documented mapping-only gaps."""

    census_function_item_codes: ParsedCensusNasboResource
    census_data_flag_codes: ParsedCensusNasboResource
    nasbo_program_area_chapters: ParsedCensusNasboResource
    gaps: tuple[str, ...]


def assemble_census_nasbo_portfolio(
    resources: Sequence[ParsedCensusNasboResource],
) -> CensusNasboPortfolio:
    """Require all three distinct resources and retain the mapping-only gaps."""

    by_name = {resource.source.resource_name: resource for resource in resources}
    expected_names = {"censusFunctionItemCodes", "censusDataFlagCodes", "nasboProgramAreaChapters"}
    if len(resources) != 3 or set(by_name) != expected_names:
        raise CensusNasboSourceDriftError(
            "Census/NASBO portfolio requires exactly the three census function, data flag, and NASBO chapter resources"
        )
    return CensusNasboPortfolio(
        census_function_item_codes=by_name["censusFunctionItemCodes"],
        census_data_flag_codes=by_name["censusDataFlagCodes"],
        nasbo_program_area_chapters=by_name["nasboProgramAreaChapters"],
        gaps=CENSUS_NASBO_PORTFOLIO_GAPS,
    )


@dataclass(frozen=True, slots=True)
class CensusNasboMappingAssignment:
    """One field's value validated against its exact pinned code list."""

    field: str
    publisher_label: str
    use: ResourceUse
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool


@dataclass(frozen=True, slots=True)
class ValidatedCensusNasboMapping:
    """A cross-reference from one state-native budget line item to these lists.

    ``state_native_reference`` is preserved verbatim and is never replaced;
    the Census/NASBO assignments are optional, independently validated
    secondary cross-references, matching the catalog's mapping-only decision.
    """

    state_native_reference: str
    census_function_item: CensusNasboMappingAssignment | None
    nasbo_program_area: CensusNasboMappingAssignment | None
    gaps: tuple[str, ...]


def _mapping_assignment(field: str, code: CensusNasboCode) -> CensusNasboMappingAssignment:
    return CensusNasboMappingAssignment(
        field=field,
        publisher_label=code.publisher_label,
        use=code.use,
        identifiers=code.identifiers,
        is_general_subject_concept=code.is_general_subject_concept,
    )


def validate_census_nasbo_mapping(
    mapping: Mapping[str, object],
    portfolio: CensusNasboPortfolio,
) -> ValidatedCensusNasboMapping:
    """Validate an optional state-budget-line-item cross-reference, failing closed.

    ``state_budget_line_item`` must remain the state's own native identity;
    ``census_function_item_code`` and ``nasbo_program_area`` are optional and,
    when present, must match a pinned code exactly or this refuses the record.
    """

    raw_reference = mapping.get("state_budget_line_item")
    if not isinstance(raw_reference, str) or not raw_reference.strip():
        raise CensusNasboMappingError("mapping must carry a non-empty state_budget_line_item reference")

    census_assignment: CensusNasboMappingAssignment | None = None
    raw_function_code = mapping.get("census_function_item_code")
    if raw_function_code is not None:
        if not isinstance(raw_function_code, str):
            raise CensusNasboMappingError("census_function_item_code must be a string")
        code = portfolio.census_function_item_codes.by_code().get(raw_function_code)
        if code is None:
            raise CensusNasboMappingError(f"unknown Census function item code {raw_function_code!r}")
        census_assignment = _mapping_assignment("census_function_item_code", code)

    nasbo_assignment: CensusNasboMappingAssignment | None = None
    raw_program_area = mapping.get("nasbo_program_area")
    if raw_program_area is not None:
        if not isinstance(raw_program_area, str):
            raise CensusNasboMappingError("nasbo_program_area must be a string")
        chapter = portfolio.nasbo_program_area_chapters.by_label().get(raw_program_area)
        if chapter is None:
            raise CensusNasboMappingError(f"unknown NASBO program-area chapter {raw_program_area!r}")
        nasbo_assignment = _mapping_assignment("nasbo_program_area", chapter)

    return ValidatedCensusNasboMapping(
        state_native_reference=raw_reference,
        census_function_item=census_assignment,
        nasbo_program_area=nasbo_assignment,
        gaps=CENSUS_NASBO_PORTFOLIO_GAPS,
    )


_MAPPING_ONLY_ROLE_GAP = MappingProxyType(
    {
        "kind": "mappingOnlyRole",
        "reason": (
            "This classification is a cross-state mapping reference only; it does "
            "not replace a state's enacted chart of accounts or the legal identity "
            "of a state program, which a RefSpec state-budget document must keep "
            "as its own native identity."
        ),
    }
)
_OBJECT_FUND_PDF_GAP = MappingProxyType(
    {
        "kind": "objectAndFundClassificationUnavailableAsHtml",
        "reason": (
            "Census's object-of-expenditure and fund-source classification "
            "categories are documented only in the 2006 Classification Manual PDF, "
            "not a small pinned HTML code list; this package does not parse the PDF."
        ),
    }
)
_NASBO_NO_STABLE_CODE_GAP = MappingProxyType(
    {
        "kind": "publisherCodeUnavailable",
        "reason": (
            "NASBO publishes no stable per-chapter code or IRI for a program area, "
            "only the chapter's English title; every observation therefore carries "
            "an empty identifiers list."
        ),
    }
)


def _verified_page_payload(page: AcquiredCensusNasboPage) -> bytes:
    payload = page.path.read_bytes()
    if len(payload) != page.byte_length or sha256_digest(payload) != page.sha256:
        raise CensusNasboSourceDriftError("Census/NASBO package source differs from its acquired pin")
    return payload


def _observation(
    resource_id: str,
    parsed: ParsedCensusNasboResource,
    ordinal: int,
    code: CensusNasboCode,
) -> dict[str, Any]:
    identifiers = [
        {
            "value": identifier.value,
            "kind": identifier.kind,
            "authorityUri": identifier.authority_uri,
            "sourceUri": identifier.source_uri,
            "sourcePath": f"$.rows[{ordinal}]",
            "observedAt": identifier.observed_at,
            "sourceDigest": identifier.source_digest,
        }
        for identifier in code.identifiers
    ]
    identity = {
        "resourceId": resource_id,
        "sourceArtifact": parsed.source.source_url,
        "sourceOrdinal": ordinal,
        "publisherLabel": code.publisher_label,
        "identifiers": identifiers,
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return {
        "id": f"urn:ref:source-observation:{resource_id}:{digest}",
        "sourceArtifact": parsed.source.source_url,
        "sourcePath": f"$.rows[{ordinal}]",
        "sourceOrdinal": ordinal,
        "labels": [{"value": code.publisher_label, "language": LANGUAGE, "role": "preferred"}],
        "identifiers": identifiers,
        "eligibleUses": ["deterministicMetadata"],
        "conceptIdentityClaimed": False,
    }


def _build_package(
    *,
    resource_id: str,
    title: str,
    identity_status: Literal["publisherIdentifiersPreserved", "captureLocalObservationsOnly"],
    page: AcquiredCensusNasboPage,
    parsed: ParsedCensusNasboResource,
    package_gaps: Sequence[Mapping[str, Any]],
) -> SourceControlledResourceBundle:
    if parsed.source_sha256 != page.sha256 or parsed.source.source_url != page.pin.source.source_url:
        raise CensusNasboSourceDriftError("parsed resource and acquired page describe different sources")
    payload = _verified_page_payload(page)
    observations = tuple(_observation(resource_id, parsed, ordinal, code) for ordinal, code in enumerate(parsed.codes))
    return build_source_controlled_resource_bundle(
        resource_id=resource_id,
        title=title,
        resource_kind="controlledCodeList",
        identity_status=identity_status,
        uses=("deterministicMetadata",),
        captured_at=parsed.retrieved_at,
        candidate_use_authorized=True,
        observations=observations,
        source_artifacts={parsed.source.source_url: payload},
        source_observed_count=parsed.source.expected_count,
        gaps=(_MAPPING_ONLY_ROLE_GAP, *package_gaps),
    )


def build_census_function_item_code_package(
    page: AcquiredCensusNasboPage,
    parsed: ParsedCensusNasboResource,
) -> SourceControlledResourceBundle:
    """Package all exact Census ASPEP function item codes as mapping metadata."""

    return _build_package(
        resource_id="census-aspep-function-item-codes-2026-08-03",
        title="Census ASPEP Function Item Codes (Functional Category), captured 2026-08-03",
        identity_status="publisherIdentifiersPreserved",
        page=page,
        parsed=parsed,
        package_gaps=(),
    )


def build_census_data_flag_code_package(
    page: AcquiredCensusNasboPage,
    parsed: ParsedCensusNasboResource,
) -> SourceControlledResourceBundle:
    """Package all exact Census ASPEP data flag codes as mapping metadata."""

    return _build_package(
        resource_id="census-aspep-data-flag-codes-2026-08-03",
        title="Census ASPEP Data Flags, captured 2026-08-03",
        identity_status="publisherIdentifiersPreserved",
        page=page,
        parsed=parsed,
        package_gaps=(),
    )


def build_nasbo_program_area_chapter_package(
    page: AcquiredCensusNasboPage,
    parsed: ParsedCensusNasboResource,
) -> SourceControlledResourceBundle:
    """Package the current NASBO SER program-area chapters as mapping metadata."""

    return _build_package(
        resource_id="nasbo-ser-program-area-chapters-2026-08-03",
        title="NASBO State Expenditure Report Program-Area Chapters, captured 2026-08-03",
        identity_status="captureLocalObservationsOnly",
        page=page,
        parsed=parsed,
        package_gaps=(_NASBO_NO_STABLE_CODE_GAP,),
    )


__all__ = [
    "CENSUS_DATA_FLAG_CODES_2026_08_03",
    "CENSUS_DATA_FLAG_CODES_SOURCE",
    "CENSUS_FUNCTION_ITEM_CODES_2026_08_03",
    "CENSUS_FUNCTION_ITEM_CODES_SOURCE",
    "CENSUS_HOSTS",
    "CENSUS_IDENTIFIER_AUTHORITY_URI",
    "CENSUS_NASBO_PORTFOLIO_GAPS",
    "NASBO_HOSTS",
    "NASBO_PROGRAM_AREA_CHAPTERS_2026_08_03",
    "NASBO_PROGRAM_AREA_CHAPTERS_SOURCE",
    "AcquiredCensusNasboPage",
    "AcquisitionMode",
    "CensusNasboAcquisitionError",
    "CensusNasboCode",
    "CensusNasboMappingAssignment",
    "CensusNasboMappingError",
    "CensusNasboPageFetcher",
    "CensusNasboPortfolio",
    "CensusNasboResourceError",
    "CensusNasboSnapshotPin",
    "CensusNasboSource",
    "CensusNasboSourceDriftError",
    "FetchedCensusNasboPage",
    "ParsedCensusNasboResource",
    "ValidatedCensusNasboMapping",
    "acquire_census_nasbo_page",
    "assemble_census_nasbo_portfolio",
    "build_census_data_flag_code_package",
    "build_census_function_item_code_package",
    "build_nasbo_program_area_chapter_package",
    "parse_census_data_flag_codes",
    "parse_census_function_item_codes",
    "parse_nasbo_program_area_chapters",
    "sha256_digest",
    "validate_census_nasbo_mapping",
]
