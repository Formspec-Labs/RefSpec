"""Pinned Census TIGER GEOID structure and GNIS National File layout captures.

This module packages the *identifier grammar and file structure* published
by two related Census/USGS sources -- it never ingests bulk entity rows
(all 50 states, every county, ...):

* TIGER/Line GEOID composition -- the catalog's
  ``tiger-geo-line.html`` technical-documentation URL is a hub page that
  links out to yearly downloadable PDFs; it does not itself publish the
  GEOID composition table. That table is published on the companion
  ``census.gov/programs-surveys/geography/guidance/geo-identifiers.html``
  page under the same Census Geography Program, and this module pins one
  real span from that page: the eleven-row "GEOID Structure" table (State
  through ZCTA).

* GNIS National File layout -- the catalog's ``download-gnis-data`` page
  links to the official GNIS data-products file-format PDF, whose "File
  format for Domestic National and States, Territories, and Associated
  Areas" table documents all 21 National File fields: name, type,
  length/decimals, and the publisher's own description cell for each,
  including ``feature_id`` (see the PDF's Appendix 3 for the ANSI INCITS
  446-2008 (R2018) standard) and the ``state_numeric``/``county_numeric``
  FIPS-successor codes TIGER GEOIDs concatenate. The complete field layout
  is parsed from the pinned PDF and every description is the publisher's
  wording; where the PDF merges one description cell across several rows
  (state, county, BGN, and coordinate groups), the shared cell is carried
  verbatim on each member with the group recorded, never paraphrased.

Two earlier captures left under REF-032. The ACS variables sample -- a
curator-picked subset of a 635-row auto-generated listing -- was not a
publisher scheme, and the guidance page's three-row GEO.ID/NAME example
table published example values, not vocabulary; neither is packaged.

Every observation keeps its exact publisher-issued identifier value; none is
promoted to a Rulespec concept scheme, and ``conceptIdentityClaimed`` stays
``False`` throughout. Acquisition accepts a local exact capture or an
injected fetcher; importing this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from refspec.pdf_text import fold_pdf_text
from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

CENSUS_TIGER_GEOGRAPHY_AUTHORITY_URI = (
    "https://www.census.gov/programs-surveys/geography/technical-documentation/"
    "complete-technical-documentation/tiger-geo-line.html"
)
USGS_GNIS_AUTHORITY_URI = "https://www.usgs.gov/us-board-on-geographic-names/download-gnis-data"

CENSUS_GEOID_GUIDANCE_URL = "https://www.census.gov/programs-surveys/geography/guidance/geo-identifiers.html"
GNIS_FILE_FORMAT_PDF_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/GNIS_file_format.pdf"

CENSUS_GEO_IDENTIFIER_AUTHORITY_RESOURCE_ID = "census-geo-identifier-authority-2026-08-03"
CENSUS_GEO_IDENTIFIER_AUTHORITY_TITLE = (
    "Census TIGER GEOID structure and GNIS National File layout, captured 2026-08-03"
)

ResourceUse = Literal["deterministicMetadata"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


class CensusGeoResourceError(ValueError):
    """Base class for census/GNIS identifier-structure capture failures."""


class CensusGeoAcquisitionError(CensusGeoResourceError):
    """Exact official source bytes could not be acquired safely."""


class CensusGeoSourceDriftError(CensusGeoResourceError):
    """A pinned source no longer matches its reviewed identifier shape."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _digest_hex(value: str) -> str:
    match = _DIGEST.fullmatch(value)
    if match is None:
        raise CensusGeoAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
    return match.group(1)


# ---------------------------------------------------------------------------
# HTML byte-span acquisition (TIGER/GEOID guidance page).
#
# The span is located inside one already-fetched page by a begin marker that
# must occur exactly once, then the first end marker found at or after it --
# the same anchor-pair technique used for other RegInfo.gov/API HTML sources
# in this registry. Only the located span is pinned and stored; the page
# around it is never treated as source evidence.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CensusGeoHtmlSpanSource:
    """The exact anchor pair that locates one official page's markup span."""

    span_id: str
    page_url: str
    allowed_host: str
    begin_marker: bytes
    end_marker: bytes

    def __post_init__(self) -> None:
        parsed = urlsplit(self.page_url)
        if parsed.scheme != "https" or parsed.hostname != self.allowed_host:
            raise CensusGeoAcquisitionError(f"page_url must be an official HTTPS {self.allowed_host} URL")
        if parsed.username is not None or parsed.password is not None:
            raise CensusGeoAcquisitionError("page_url must not contain credentials")
        if not self.begin_marker or not self.end_marker:
            raise CensusGeoAcquisitionError("begin_marker and end_marker must not be empty")

    @property
    def source_id(self) -> str:
        """A stable, page-scoped locator for this span's captured fragment."""

        return f"{self.page_url}#{self.span_id}"


GEOID_STRUCTURE_TABLE_SPAN = CensusGeoHtmlSpanSource(
    span_id="geoid-structure-table",
    page_url=CENSUS_GEOID_GUIDANCE_URL,
    allowed_host="www.census.gov",
    begin_marker=(
        b'<table class="datatablewide" style="table-layout: fixed;">\r\n<thead>\r\n\t<tr>\r\n\t\t'
        b'<th scope="col" style="text-align: left; vertical-align: middle; width: 17%;">Area Type</th>'
    ),
    end_marker=b"</table>",
)


@dataclass(frozen=True, slots=True)
class CensusGeoHtmlSpanPin:
    """Exact identity of one official span's captured markup."""

    span: CensusGeoHtmlSpanSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        _digest_hex(self.expected_sha256)
        if self.expected_byte_length <= 0:
            raise CensusGeoAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise CensusGeoAcquisitionError("retrieved_at must not be empty")


# Real span digest captured 2026-08-03 from the live page named in the
# catalog row. The census.gov guidance page publishes no release date or
# revision identifier for this fragment; retrieval time and the exact span
# digest are the available revision pin.
GEOID_STRUCTURE_TABLE_SPAN_2026_08_03 = CensusGeoHtmlSpanPin(
    span=GEOID_STRUCTURE_TABLE_SPAN,
    retrieved_at="2026-08-03T19:20:00Z",
    expected_sha256="sha256:5886829a89ffe3381333572948a4ed6db3ee1ae0d53b6462d491186596d1aedb",
    expected_byte_length=4_432,
)


@dataclass(frozen=True, slots=True)
class FetchedCensusGeoPage:
    """Provider-independent response returned by an injected page fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class CensusGeoFetcher(Protocol):
    """Small transport boundary for the official ACS/TIGER HTML pages."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedCensusGeoPage:
        """Fetch one page response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredCensusGeoHtmlSpan:
    """One verified span in the content-addressed source store."""

    pin: CensusGeoHtmlSpanPin
    path: Path
    sha256: str
    byte_length: int
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def _extract_span(full_page: bytes, span: CensusGeoHtmlSpanSource) -> bytes:
    """Locate one span by an anchor pair whose begin marker occurs exactly once."""

    starts = [match.start() for match in re.finditer(re.escape(span.begin_marker), full_page)]
    if len(starts) != 1:
        raise CensusGeoSourceDriftError(
            f"{span.span_id} begin marker occurs {len(starts)} times in the source page; expected exactly one"
        )
    end_index = full_page.find(span.end_marker, starts[0])
    if end_index == -1:
        raise CensusGeoSourceDriftError(f"{span.span_id} end marker was not found after its begin marker")
    return full_page[starts[0] : end_index + len(span.end_marker)]


def _verify_span_payload(payload: bytes, pin: CensusGeoHtmlSpanPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise CensusGeoSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise CensusGeoSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing_span(path: Path, pin: CensusGeoHtmlSpanPin) -> AcquiredCensusGeoHtmlSpan:
    if path.is_symlink() or not path.is_file():
        raise CensusGeoAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_span_payload(path.read_bytes(), pin, location="cached census/GEOID span")
    return AcquiredCensusGeoHtmlSpan(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        resolved_url=None,
        content_type="text/html",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_span_payload(
    payload: bytes,
    pin: CensusGeoHtmlSpanPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredCensusGeoHtmlSpan:
    actual_sha256, byte_length = _verify_span_payload(payload, pin, location=f"{acquisition_mode} census/GEOID span")
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
            return _verify_existing_span(final_path, pin)
        return AcquiredCensusGeoHtmlSpan(
            pin=pin,
            path=final_path,
            sha256=actual_sha256,
            byte_length=byte_length,
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


def acquire_census_geo_html_span(
    pin: CensusGeoHtmlSpanPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: CensusGeoFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredCensusGeoHtmlSpan:
    """Acquire one exact span through a provider-neutral boundary.

    The caller supplies either ``source_path`` (a full local page capture,
    from which the span is extracted) or an injected ``fetcher``. Importing
    this module never opens a network connection.
    """

    if timeout_seconds <= 0:
        raise CensusGeoAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise CensusGeoAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = _digest_hex(pin.expected_sha256)
    final_path = Path(store_dir) / "sha256" / digest_hex / f"{pin.span.span_id}.html"
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing_span(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise CensusGeoAcquisitionError(f"local census/GEOID source is not a regular file: {local_path}")
        fragment = _extract_span(local_path.read_bytes(), pin.span)
        return _publish_span_payload(
            fragment,
            pin,
            final_path,
            content_type="text/html",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise CensusGeoAcquisitionError("span is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.span.page_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise CensusGeoAcquisitionError(f"could not acquire {pin.span.page_url}: HTTP {fetched.status_code}")
    resolved = urlsplit(fetched.resolved_url)
    if resolved.scheme != "https" or resolved.hostname != pin.span.allowed_host:
        raise CensusGeoAcquisitionError(f"fetcher resolved_url must remain on official HTTPS {pin.span.allowed_host}")
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise CensusGeoSourceDriftError(f"page content type drifted to {fetched.content_type!r}")
    fragment = _extract_span(fetched.body, pin.span)
    return _publish_span_payload(
        fragment,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


# ---------------------------------------------------------------------------
# TIGER/Line GEOID composition.
# ---------------------------------------------------------------------------

_GEOID_STRUCTURE_ROW_RE = re.compile(
    r'<tr>\r?\n\t\t<td scope="row"[^>]*>(?P<area>.*?)</td>\r?\n'
    r"\t\t<td[^>]*>(?P<structure>.*?)</td>\r?\n"
    r"\t\t<td[^>]*>(?P<digits>.*?)</td>\r?\n"
    r"\t\t<td[^>]*>(?P<example_area>.*?)</td>\r?\n"
    r"\t\t<td[^>]*>(?P<example_geoid>.*?)</td>\r?\n"
    r"\t</tr>"
)
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_STRIP_FOOTNOTE_MARKER_RE = re.compile(r"<sup>.*?</sup>")


@dataclass(frozen=True, slots=True)
class GeoidCompositionRow:
    """One published GEOID composition rule for a common TIGER/Line area type."""

    area_type: str
    structure: str
    number_of_digits: str
    example_area: str
    example_geoid: str
    source_ordinal: int


GEOID_STRUCTURE_TABLE_AREA_TYPES = (
    "State",
    "County",
    "County Subdivision",
    "Places",
    "Census Tract",
    "Block Group",
    "Block",
    "Congressional District (113th Congress)",
    "State Legislative District (Upper Chamber)",
    "State Legislative District (Lower Chamber)",
    "ZCTA",
)


def parse_geoid_structure_span(acquired: AcquiredCensusGeoHtmlSpan) -> tuple[GeoidCompositionRow, ...]:
    """Parse the eleven-row GEOID Structure table and require its known row order."""

    payload = acquired.path.read_bytes()
    _verify_span_payload(payload, acquired.pin, location="parsed GEOID structure span")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CensusGeoSourceDriftError("GEOID structure span is not valid UTF-8") from error
    rows = []
    for ordinal, match in enumerate(_GEOID_STRUCTURE_ROW_RE.finditer(text)):
        area_type = _STRIP_TAGS_RE.sub("", _STRIP_FOOTNOTE_MARKER_RE.sub("", match.group("area"))).strip()
        rows.append(
            GeoidCompositionRow(
                area_type=area_type,
                structure=match.group("structure").strip(),
                number_of_digits=match.group("digits").strip(),
                example_area=match.group("example_area").strip(),
                example_geoid=match.group("example_geoid").strip(),
                source_ordinal=ordinal,
            )
        )
    actual = tuple(row.area_type for row in rows)
    if actual != GEOID_STRUCTURE_TABLE_AREA_TYPES:
        raise CensusGeoSourceDriftError(
            f"GEOID structure table row order drifted: expected {GEOID_STRUCTURE_TABLE_AREA_TYPES}, got {actual}"
        )
    return tuple(rows)


# ---------------------------------------------------------------------------
# GNIS National File layout (whole-PDF acquisition).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GNISFileFormatPin:
    """Exact identity of the official GNIS data-products file-format PDF."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    expected_page_count: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "prd-tnm.s3.amazonaws.com":
            raise CensusGeoAcquisitionError("source_url must be the official HTTPS prd-tnm.s3.amazonaws.com PDF")
        _digest_hex(self.expected_sha256)
        if self.expected_byte_length <= 0 or self.expected_page_count <= 0:
            raise CensusGeoAcquisitionError("expected_byte_length and expected_page_count must be positive")
        if not self.retrieved_at.strip():
            raise CensusGeoAcquisitionError("retrieved_at must not be empty")


# Real PDF digest captured 2026-08-03 from the official USGS/GNIS download.
# The PDF states its own revision as "Date: November 13, 2025".
GNIS_FILE_FORMAT_PIN_2026_08_03 = GNISFileFormatPin(
    source_url=GNIS_FILE_FORMAT_PDF_URL,
    retrieved_at="2026-08-03T19:24:00Z",
    expected_sha256="sha256:cd9dad49f8584f60ab4a68ab43cb416d06513688329463846cc1156b78cd0eea",
    expected_byte_length=283_712,
    expected_page_count=23,
)


@dataclass(frozen=True, slots=True)
class AcquiredGNISFileFormat:
    """One verified GNIS file-format PDF in the content-addressed source store."""

    pin: GNISFileFormatPin
    path: Path
    sha256: str
    byte_length: int
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def _verify_gnis_payload(payload: bytes, pin: GNISFileFormatPin, *, location: str) -> tuple[str, int]:
    if not payload.startswith(b"%PDF-"):
        raise CensusGeoSourceDriftError(f"{location} is not a PDF file")
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise CensusGeoSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise CensusGeoSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing_gnis(path: Path, pin: GNISFileFormatPin) -> AcquiredGNISFileFormat:
    if path.is_symlink() or not path.is_file():
        raise CensusGeoAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_gnis_payload(path.read_bytes(), pin, location="cached GNIS PDF")
    return AcquiredGNISFileFormat(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        resolved_url=None,
        content_type="application/pdf",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def acquire_gnis_file_format(
    pin: GNISFileFormatPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: CensusGeoFetcher | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredGNISFileFormat:
    """Acquire the exact official GNIS file-format PDF from cache, a local capture, or a fetcher."""

    if timeout_seconds <= 0:
        raise CensusGeoAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise CensusGeoAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = _digest_hex(pin.expected_sha256)
    final_path = Path(store_dir) / "sha256" / digest_hex / "GNIS_file_format.pdf"
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing_gnis(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise CensusGeoAcquisitionError(f"local GNIS source is not a regular file: {local_path}")
        payload = local_path.read_bytes()
        actual_sha256, byte_length = _verify_gnis_payload(payload, pin, location="local GNIS PDF")
        acquisition_mode: Literal["local", "fetcher"] = "local"
        resolved_url = None
        local_source_path: Path | None = local_path.resolve()
        content_type = "application/pdf"
    else:
        if fetcher is None:
            raise CensusGeoAcquisitionError("GNIS PDF is not cached; provide source_path or an injected fetcher")
        fetched = fetcher.fetch(pin.source_url, timeout_seconds=timeout_seconds)
        if fetched.status_code != 200:
            raise CensusGeoAcquisitionError(f"could not acquire {pin.source_url}: HTTP {fetched.status_code}")
        resolved = urlsplit(fetched.resolved_url)
        if resolved.scheme != "https" or resolved.hostname != "prd-tnm.s3.amazonaws.com":
            raise CensusGeoAcquisitionError(
                "fetcher resolved_url must remain on official HTTPS prd-tnm.s3.amazonaws.com"
            )
        media_type = fetched.content_type.partition(";")[0].strip().lower()
        if media_type not in {"application/pdf", "binary/octet-stream", "application/octet-stream"}:
            raise CensusGeoSourceDriftError(f"GNIS PDF content type drifted to {fetched.content_type!r}")
        payload = fetched.body
        actual_sha256, byte_length = _verify_gnis_payload(payload, pin, location="fetcher GNIS PDF")
        acquisition_mode = "fetcher"
        resolved_url = fetched.resolved_url
        local_source_path = None
        content_type = fetched.content_type

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
            return _verify_existing_gnis(final_path, pin)
        return AcquiredGNISFileFormat(
            pin=pin,
            path=final_path,
            sha256=actual_sha256,
            byte_length=byte_length,
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


@dataclass(frozen=True, slots=True)
class GNISFieldDefinition:
    """One published GNIS National File field, in the publisher's own words.

    ``description`` is the exact text of the field's description cell in the
    pinned PDF (whitespace-normalized, PDF presentation forms folded per
    ``refspec.pdf_text``). The PDF merges one description cell across several
    rows in four places -- the state, county, BGN, and coordinate groups --
    and ``description_shared_with`` names every field the cell spans (in
    table order, including this one) so a consumer never mistakes a shared
    cell for a sentence about one field alone. For a field with its own
    cell, ``description_shared_with`` is empty.
    """

    field_name: str
    field_type: str
    # The publisher's "Length / Decimals" cell, verbatim ("10", "11 / 7");
    # empty where the publisher leaves the cell blank (the Date fields).
    length_decimals: str
    description: str
    description_shared_with: tuple[str, ...]
    source_ordinal: int


# The reviewed structure of the pinned PDF's National File table: every
# field's name, type, and Length/Decimals cell, in table order. The parser
# recovers the table from the PDF text layer and refuses any drift from
# this shape; descriptions are taken from the PDF itself, never from here.
GNIS_NATIONAL_FILE_EXPECTED_ROWS = (
    ("feature_id", "Number", "10"),
    ("feature_name", "Character", "120"),
    ("feature_class", "Character", "50"),
    ("state_name", "Character", "100"),
    ("state_numeric", "Number", "2"),
    ("county_name", "Character", "100"),
    ("county_numeric", "Number", "3"),
    ("map_name", "Character", "100"),
    ("date_created", "Date", ""),
    ("date_edited", "Date", ""),
    ("bgn_type", "Character", "12"),
    ("bgn_authority", "Character", "25"),
    ("bgn_date", "Date", ""),
    ("prim_lat_dms", "Character", "7"),
    ("prim_long_dms", "Character", "8"),
    ("prim_lat_dec", "Number", "11 / 7"),
    ("prim_long_dec", "Number", "12 / 7"),
    ("source_lat_dms", "Character", "7"),
    ("source_long_dms", "Character", "8"),
    ("source_lat_dec", "Number", "11 / 7"),
    ("source_long_dec", "Number", "12 / 7"),
)
GNIS_NATIONAL_FILE_FIELD_COUNT = len(GNIS_NATIONAL_FILE_EXPECTED_ROWS)

# The National File table header as the text layer linearizes it. It appears
# once on each of the table's two pages; both occurrences are removed before
# row tokenization.
_GNIS_TABLE_HEADER = "Field Name Type Length / Decimals Description"
# One field row: a snake_case field name, its Type keyword, and an optional
# Length/Decimals cell. Every National File field name contains an
# underscore, so prose inside a description cell cannot start a false row.
_GNIS_FIELD_ROW_RE = re.compile(
    r"\b(?P<name>[a-z]+(?:_[a-z]+)+) (?P<type>Number|Character|Date)\b(?: (?P<length>\d+(?: / \d+)?))?"
)


def parse_gnis_file_format(acquired: AcquiredGNISFileFormat) -> tuple[GNISFieldDefinition, ...]:
    """Parse the complete National File field table from the pinned GNIS PDF.

    The table spans the PDF's first two pages. pypdf's text extraction
    linearizes each row as ``name type length description``, and a merged
    description cell surfaces as one description on the group's first row
    followed by rows with empty description cells; those rows share the
    publisher's cell, and the group is recorded on every member. Any drift
    from the reviewed 21-row shape fails closed.
    """

    payload = acquired.path.read_bytes()
    _verify_gnis_payload(payload, acquired.pin, location="parsed GNIS PDF")
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - dependency gate
        raise CensusGeoResourceError("pypdf is required to parse the GNIS file-format PDF") from error
    try:
        reader = PdfReader(BytesIO(payload))
    except Exception as error:
        raise CensusGeoSourceDriftError(f"GNIS file-format source is not a readable PDF: {error}") from error
    if len(reader.pages) != acquired.pin.expected_page_count:
        raise CensusGeoSourceDriftError("GNIS file-format PDF page count drifted")

    pages = [
        re.sub(r"\s+", " ", fold_pdf_text(reader.pages[index].extract_text() or "")).strip()
        for index in (0, 1)
    ]
    header_index = pages[0].find(_GNIS_TABLE_HEADER)
    if header_index == -1 or _GNIS_TABLE_HEADER not in pages[1]:
        raise CensusGeoSourceDriftError("GNIS National File table header was not found on both table pages")
    table = " ".join(
        (
            pages[0][header_index + len(_GNIS_TABLE_HEADER) :].strip(),
            pages[1].replace(_GNIS_TABLE_HEADER, " ", 1).strip(),
        )
    )
    table = re.sub(r"\s+", " ", table).strip()

    matches = tuple(_GNIS_FIELD_ROW_RE.finditer(table))
    raw_rows: list[tuple[str, str, str, str]] = []
    for index, match in enumerate(matches):
        cell_end = matches[index + 1].start() if index + 1 < len(matches) else len(table)
        description = table[match.end() : cell_end].strip()
        raw_rows.append(
            (match.group("name"), match.group("type"), match.group("length") or "", description)
        )
    actual_shape = tuple((name, field_type, length) for name, field_type, length, _ in raw_rows)
    if actual_shape != GNIS_NATIONAL_FILE_EXPECTED_ROWS:
        raise CensusGeoSourceDriftError(
            f"GNIS National File table shape drifted: expected {GNIS_NATIONAL_FILE_EXPECTED_ROWS}, got {actual_shape}"
        )

    # Group rows that share one merged description cell: an empty description
    # cell continues the previous row's group.
    groups: list[list[int]] = []
    for ordinal, (name, _field_type, _length, description) in enumerate(raw_rows):
        if description:
            groups.append([ordinal])
        else:
            if not groups:
                raise CensusGeoSourceDriftError(
                    f"GNIS National File field {name!r} has no description cell and no preceding row to share one"
                )
            groups[-1].append(ordinal)

    fields: list[GNISFieldDefinition] = []
    for group in groups:
        member_names = tuple(raw_rows[ordinal][0] for ordinal in group)
        shared = member_names if len(group) > 1 else ()
        description = raw_rows[group[0]][3]
        for ordinal in group:
            name, field_type, length, _ = raw_rows[ordinal]
            fields.append(
                GNISFieldDefinition(
                    field_name=name,
                    field_type=field_type,
                    length_decimals=length,
                    description=description,
                    description_shared_with=shared,
                    source_ordinal=ordinal,
                )
            )
    fields.sort(key=lambda field: field.source_ordinal)
    return tuple(fields)


# ---------------------------------------------------------------------------
# Package assembly.
# ---------------------------------------------------------------------------


def _identifier_payload(
    *,
    value: str,
    kind: str,
    authority_uri: str,
    source_uri: str,
    source_path: str,
    observed_at: str,
    source_digest: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "kind": kind,
        "authorityUri": authority_uri,
        "sourceUri": source_uri,
        "sourcePath": source_path,
        "observedAt": observed_at,
        "sourceDigest": source_digest,
    }


def _observation_id(
    *,
    resource_id: str,
    source_artifact: str,
    source_path: str,
    identifiers: Sequence[Mapping[str, Any]],
) -> str:
    identity = {
        "resourceId": resource_id,
        "sourceArtifact": source_artifact,
        "sourcePath": source_path,
        "identifiers": [
            {"value": item["value"], "kind": item["kind"], "authorityUri": item["authorityUri"]} for item in identifiers
        ],
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{resource_id}:{digest}"


def _observation(
    *,
    resource_id: str,
    source_artifact: str,
    source_path: str,
    source_ordinal: int,
    label: str,
    identifier_value: str,
    identifier_kind: str,
    authority_uri: str,
    source_uri: str,
    observed_at: str,
    source_digest: str,
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    identifiers = [
        _identifier_payload(
            value=identifier_value,
            kind=identifier_kind,
            authority_uri=authority_uri,
            source_uri=source_uri,
            source_path=source_path,
            observed_at=observed_at,
            source_digest=source_digest,
        )
    ]
    return {
        "id": _observation_id(
            resource_id=resource_id,
            source_artifact=source_artifact,
            source_path=source_path,
            identifiers=identifiers,
        ),
        "sourceArtifact": source_artifact,
        "sourcePath": source_path,
        "sourceOrdinal": source_ordinal,
        "labels": [{"value": label, "language": "en", "role": "preferred"}],
        "identifiers": identifiers,
        "uses": ["deterministicMetadata"],
        "conceptIdentityClaimed": False,
        **extra,
    }


def build_census_geo_identifier_authority_package(
    geoid_structure_span: AcquiredCensusGeoHtmlSpan,
    gnis_pdf: AcquiredGNISFileFormat,
) -> SourceControlledResourceBundle:
    """Package the pinned TIGER GEOID structure and GNIS layout as one closed resource."""

    geoid_structure_rows = parse_geoid_structure_span(geoid_structure_span)
    gnis_fields = parse_gnis_file_format(gnis_pdf)

    observations: list[dict[str, Any]] = []

    geoid_structure_source = GEOID_STRUCTURE_TABLE_SPAN.source_id
    for row in geoid_structure_rows:
        observations.append(
            _observation(
                resource_id=CENSUS_GEO_IDENTIFIER_AUTHORITY_RESOURCE_ID,
                source_artifact=geoid_structure_source,
                source_path=f"geoidStructureTable.row.{row.source_ordinal}",
                source_ordinal=row.source_ordinal,
                label=row.area_type,
                identifier_value=row.structure,
                identifier_kind="tigerGeoidComposition",
                authority_uri=CENSUS_TIGER_GEOGRAPHY_AUTHORITY_URI,
                source_uri=CENSUS_GEOID_GUIDANCE_URL,
                observed_at=geoid_structure_span.pin.retrieved_at,
                source_digest=geoid_structure_span.sha256,
                extra={
                    "product": "tigerLineGeoid",
                    "areaType": row.area_type,
                    "numberOfDigits": row.number_of_digits,
                    "exampleGeographicArea": row.example_area,
                    "exampleGeoid": row.example_geoid,
                },
            )
        )

    gnis_source = GNIS_FILE_FORMAT_PDF_URL
    for field in gnis_fields:
        extra: dict[str, Any] = {
            "product": "gnisNationalFile",
            "fieldType": field.field_type,
            "lengthDecimals": field.length_decimals,
            # The pinned artifact is a PDF text layer; the medium travels
            # with the record so a consumer knows to treat the text with
            # the caution that medium warrants.
            "sourceMedium": "pdf",
            # The publisher's description cell, verbatim.
            "description": field.description,
        }
        if field.description_shared_with:
            extra["descriptionSharedWithFields"] = list(field.description_shared_with)
        observations.append(
            _observation(
                resource_id=CENSUS_GEO_IDENTIFIER_AUTHORITY_RESOURCE_ID,
                source_artifact=gnis_source,
                source_path=f"nationalFileFieldTable.field.{field.field_name}",
                source_ordinal=field.source_ordinal,
                label=field.field_name,
                identifier_value=field.field_name,
                identifier_kind="gnisNationalFileFieldName",
                authority_uri=USGS_GNIS_AUTHORITY_URI,
                source_uri=gnis_source,
                observed_at=gnis_pdf.pin.retrieved_at,
                source_digest=gnis_pdf.sha256,
                extra=extra,
            )
        )

    source_artifacts = {
        geoid_structure_source: geoid_structure_span.path.read_bytes(),
        gnis_source: gnis_pdf.path.read_bytes(),
    }

    return build_source_controlled_resource_bundle(
        resource_id=CENSUS_GEO_IDENTIFIER_AUTHORITY_RESOURCE_ID,
        title=CENSUS_GEO_IDENTIFIER_AUTHORITY_TITLE,
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("deterministicMetadata",),
        captured_at=gnis_pdf.pin.retrieved_at,
        observations=observations,
        source_artifacts=source_artifacts,
        gaps=(
            {
                "kind": "companionGeographySource",
                "reason": (
                    "The catalog's tiger-geo-line.html URL is a hub page linking to yearly PDFs; "
                    "the GEOID Structure table captured here is published on the companion "
                    "census.gov geography guidance page it links out to under the same Census "
                    "Geography Program."
                ),
            },
            {
                "kind": "exampleValuesExcluded",
                "reason": (
                    "The guidance page also renders a three-row GEO.ID/NAME example table of "
                    "sample download keys (e.g. 0500000US10001); example values are not "
                    "publisher vocabulary and are not packaged (REF-032)."
                ),
            },
            {
                "kind": "noBoundaryMethodField",
                "reason": (
                    "These captures describe identifier composition and file structure, not "
                    "cartographic boundary delineation method; TIGER/Line boundary methodology "
                    "lives in the separate technical-documentation chapters the hub links to and "
                    "is out of scope for this capture."
                ),
            },
            {
                "kind": "gnisNationalFileTableOnly",
                "reason": (
                    "The GNIS file-format PDF also documents the Feature Description/History, "
                    "Government Units, Federal Codes, and Antarctica file formats and its "
                    "appendices; this capture packages the complete National File field table "
                    "only."
                ),
            },
            {
                "kind": "gnisSupersedesFips55",
                "reason": (
                    "The GNIS file-format document states that the GNIS Feature ID superseded the "
                    "FIPS 55 Place Code (now the Census Code) as the federal/national standard "
                    "geographic feature record identifier."
                ),
            },
        ),
    )


__all__ = [
    "CENSUS_GEOID_GUIDANCE_URL",
    "CENSUS_GEO_IDENTIFIER_AUTHORITY_RESOURCE_ID",
    "CENSUS_GEO_IDENTIFIER_AUTHORITY_TITLE",
    "CENSUS_TIGER_GEOGRAPHY_AUTHORITY_URI",
    "GEOID_STRUCTURE_TABLE_AREA_TYPES",
    "GEOID_STRUCTURE_TABLE_SPAN",
    "GEOID_STRUCTURE_TABLE_SPAN_2026_08_03",
    "GNIS_FILE_FORMAT_PDF_URL",
    "GNIS_FILE_FORMAT_PIN_2026_08_03",
    "GNIS_NATIONAL_FILE_EXPECTED_ROWS",
    "GNIS_NATIONAL_FILE_FIELD_COUNT",
    "USGS_GNIS_AUTHORITY_URI",
    "AcquiredCensusGeoHtmlSpan",
    "AcquiredGNISFileFormat",
    "AcquisitionMode",
    "CensusGeoAcquisitionError",
    "CensusGeoFetcher",
    "CensusGeoHtmlSpanPin",
    "CensusGeoHtmlSpanSource",
    "CensusGeoResourceError",
    "CensusGeoSourceDriftError",
    "FetchedCensusGeoPage",
    "GNISFieldDefinition",
    "GNISFileFormatPin",
    "GeoidCompositionRow",
    "acquire_census_geo_html_span",
    "acquire_gnis_file_format",
    "build_census_geo_identifier_authority_package",
    "parse_geoid_structure_span",
    "parse_gnis_file_format",
    "sha256_digest",
]
