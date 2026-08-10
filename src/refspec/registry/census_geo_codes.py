"""Pinned identifier-shape captures for Census ACS, TIGER, and GNIS geography.

This module packages the *identifier grammar and code structure* published
across three related Census/USGS sources -- it never ingests bulk entity
rows (all 50 states, every county, every ACS variable, ...). Per the catalog
decision for this row, the scope is deterministic observation/entity
*structure*: how an ACS variable name is composed, how a TIGER/Line GEOID is
concatenated from nested FIPS and Census Bureau codes, and how a GNIS feature
identifier and its state/county code fields relate to the same FIPS codes.

* ACS variable naming -- ``https://api.census.gov/data/2024/acs/acs1/spp/variables.html``
  enumerates 635 variables for the 2024 ACS 1-year Selected Population
  Profile. This module pins two small real byte spans from that live page
  (not the whole 635-row table) and promotes a representative subset of
  their rows to observations: the ``for``/``in`` geography predicate
  parameters, the ``GEO_ID``/``GEOCOMP`` geography-identifier variables, and
  one ``S0201`` table's ``_001E``/``_002E`` estimate variables (whose
  Attributes column also evidences the ``EA``/``M``/``MA`` sibling-suffix
  family). The remaining real rows captured incidentally in the same spans
  (``AIANHH``, ``CBSA``, ``CD``, ``CSA``, ``DIVISION``) are parsed but not
  promoted, and are counted as excluded coverage rather than silently
  dropped.

* TIGER/Line GEOID composition -- the catalog's
  ``tiger-geo-line.html`` technical-documentation URL is a hub page that
  links out to yearly downloadable PDFs; it does not itself publish the
  GEOID composition table. That table is published on the companion
  ``census.gov/programs-surveys/geography/guidance/geo-identifiers.html``
  page under the same Census Geography Program, and this module pins two
  real spans from that page: the eleven-row "GEOID Structure" table (State
  through ZCTA) and the three-row GEO.ID/NAME example table showing how a
  full ``0500000US10001``-style download key concatenates a summary level,
  geographic variant/component, and FIPS state+county code.

* GNIS feature identifiers -- the catalog's
  ``download-gnis-data`` page links to the official GNIS file format PDF,
  which documents ``feature_id`` as the ANSI INCITS 446-2008 (R2018)
  permanent unique feature identifier, and ``state_numeric``/
  ``county_numeric`` as the same ANSI INCITS 38-2009 (FIPS 5-2) and INCITS
  31-2009 (FIPS 6-4) state/county codes TIGER GEOIDs concatenate. The GNIS
  Feature ID itself superseded the FIPS 55 Place Code.

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

from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

CENSUS_ACS_VARIABLES_AUTHORITY_URI = "https://api.census.gov/data/2024/acs/acs1/spp/variables.html"
CENSUS_TIGER_GEOGRAPHY_AUTHORITY_URI = (
    "https://www.census.gov/programs-surveys/geography/technical-documentation/"
    "complete-technical-documentation/tiger-geo-line.html"
)
USGS_GNIS_AUTHORITY_URI = "https://www.usgs.gov/us-board-on-geographic-names/download-gnis-data"

CENSUS_GEOID_GUIDANCE_URL = "https://www.census.gov/programs-surveys/geography/guidance/geo-identifiers.html"
GNIS_FILE_FORMAT_PDF_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/GNIS_file_format.pdf"

CENSUS_GEO_IDENTIFIER_AUTHORITY_RESOURCE_ID = "census-geo-identifier-authority-2026-08-03"
CENSUS_GEO_IDENTIFIER_AUTHORITY_TITLE = (
    "Census ACS variable, TIGER GEOID, and GNIS feature identifier structures, captured 2026-08-03"
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
# Shared HTML byte-span acquisition (ACS and TIGER/GEOID sources).
#
# Each span is located inside one already-fetched page by a begin marker that
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


ACS_GEOGRAPHY_AND_PREDICATE_SPAN = CensusGeoHtmlSpanSource(
    span_id="geography-and-predicate-variables",
    page_url=CENSUS_ACS_VARIABLES_AUTHORITY_URI,
    allowed_host="api.census.gov",
    begin_marker=b"<table>\n<caption>Census Data API: Variables in /data/2024/acs/acs1/spp/variables</caption>",
    end_marker=(
        b'<td><a name="in" href="/data/2024/acs/acs1/spp/variables/in.json">in</a></td>'
        b"<td>Census API FIPS 'in' clause</td><td>Census API Geography Specification</td>"
        b'<td>predicate-only</td><td><a href="/data/2024/acs/acs1/spp/variables/.html"></a></td>'
        b"<td>0</td><td>fips-in</td><td>\n\t\t\t\t\t\tN/A\n\t\t\t\t\t</td>\n</tr>"
    ),
)
ACS_S0201_ESTIMATE_VARIABLES_SPAN = CensusGeoHtmlSpanSource(
    span_id="s0201-estimate-variables",
    page_url=CENSUS_ACS_VARIABLES_AUTHORITY_URI,
    allowed_host="api.census.gov",
    begin_marker=b'<tr>\n<td><a name="S0201_001E"',
    end_marker=(
        b'<td><a name="S0201_002E" href="/data/2024/acs/acs1/spp/variables/S0201_002E.json">S0201_002E</a></td>'
        b"<td>Estimate!!TOTAL NUMBER OF RACES REPORTED!!Total population!!One race</td>"
        b"<td>Selected Population Profile in the United States</td><td>not required</td>"
        b'<td><a href="/data/2024/acs/acs1/spp/variables/S0201_002EA.html">S0201_002EA</a>,\n'
        b'                <a href="/data/2024/acs/acs1/spp/variables/S0201_002M.html">S0201_002M</a>,\n'
        b'                <a href="/data/2024/acs/acs1/spp/variables/S0201_002MA.html">S0201_002MA</a></td>'
        b'<td>0</td><td>float</td><td><a href="/data/2024/acs/acs1/spp/groups/S0201.html">S0201</a></td>\n</tr>'
    ),
)
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
GEOID_DOWNLOAD_EXAMPLE_TABLE_SPAN = CensusGeoHtmlSpanSource(
    span_id="geoid-download-example-table",
    page_url=CENSUS_GEOID_GUIDANCE_URL,
    allowed_host="www.census.gov",
    begin_marker=b'<table class="datatable" style="table-layout: fixed;">',
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


# Real span digests captured 2026-08-03 from the live pages named in the
# catalog row. Neither api.census.gov nor this census.gov guidance page
# publishes a release date or revision identifier for these fragments;
# retrieval time and the exact span digest are the available revision pin.
ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03 = CensusGeoHtmlSpanPin(
    span=ACS_GEOGRAPHY_AND_PREDICATE_SPAN,
    retrieved_at="2026-08-03T19:17:10Z",
    expected_sha256="sha256:66ac97d792d55cbb0ace1d4a26305a7c0fe704db94f83f2bade342f6c743e025",
    expected_byte_length=3_608,
)
ACS_S0201_ESTIMATE_VARIABLES_SPAN_2026_08_03 = CensusGeoHtmlSpanPin(
    span=ACS_S0201_ESTIMATE_VARIABLES_SPAN,
    retrieved_at="2026-08-03T19:17:10Z",
    expected_sha256="sha256:4d386957911b76830b53b64e47df1c5e0fb98bcca6253c0e32f722ce2ae520b7",
    expected_byte_length=1_253,
)
GEOID_STRUCTURE_TABLE_SPAN_2026_08_03 = CensusGeoHtmlSpanPin(
    span=GEOID_STRUCTURE_TABLE_SPAN,
    retrieved_at="2026-08-03T19:20:00Z",
    expected_sha256="sha256:5886829a89ffe3381333572948a4ed6db3ee1ae0d53b6462d491186596d1aedb",
    expected_byte_length=4_432,
)
GEOID_DOWNLOAD_EXAMPLE_TABLE_SPAN_2026_08_03 = CensusGeoHtmlSpanPin(
    span=GEOID_DOWNLOAD_EXAMPLE_TABLE_SPAN,
    retrieved_at="2026-08-03T19:20:00Z",
    expected_sha256="sha256:2b9d6087100846298ed8aa56cc8164e8fdeb360bd5ee19d42667ce94ca88597a",
    expected_byte_length=856,
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
# ACS variable naming grammar.
# ---------------------------------------------------------------------------

_ACS_ROW_RE = re.compile(
    r'<tr>\n<td><a name="(?P<name>[^"]+)" href="(?P<href>[^"]+)">[^<]*</a></td>(?P<rest>.*?)</tr>',
    re.DOTALL,
)
_ACS_MEASURE_VARIABLE_RE = re.compile(r"^[A-Z][A-Z0-9]*_[0-9]{3}E$")


@dataclass(frozen=True, slots=True)
class ACSVariableRow:
    """One exact ACS variable-listing row and its source position."""

    name: str
    label: str
    concept: str
    required: str
    predicate_type: str
    group_raw: str
    source_ordinal: int


def _parse_acs_rows(span_bytes: bytes) -> tuple[ACSVariableRow, ...]:
    try:
        text = span_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CensusGeoSourceDriftError("ACS variable span is not valid UTF-8") from error
    rows: list[ACSVariableRow] = []
    for ordinal, match in enumerate(_ACS_ROW_RE.finditer(text)):
        cells = re.findall(r"<td>(.*?)</td>", match.group("rest"), re.DOTALL)
        if len(cells) != 7:
            raise CensusGeoSourceDriftError(f"ACS variable row {match.group('name')!r} has {len(cells)} cells, not 7")
        label, concept, required, _attributes, _limit, predicate_type, group_raw = (cell.strip() for cell in cells)
        if "<span" in predicate_type:
            predicate_type = re.sub(r"<[^>]+>", "", predicate_type).strip()
        rows.append(
            ACSVariableRow(
                name=match.group("name"),
                label=label,
                concept=concept,
                required=required,
                predicate_type=predicate_type,
                group_raw=re.sub(r"\s+", " ", group_raw),
                source_ordinal=ordinal,
            )
        )
    return tuple(rows)


def parse_acs_variable_span(
    acquired: AcquiredCensusGeoHtmlSpan,
    *,
    expected_names: Sequence[str],
) -> tuple[ACSVariableRow, ...]:
    """Parse exact variable rows from a pinned span and require its known row order."""

    payload = acquired.path.read_bytes()
    _verify_span_payload(payload, acquired.pin, location="parsed ACS span")
    rows = _parse_acs_rows(payload)
    actual_names = tuple(row.name for row in rows)
    if actual_names != tuple(expected_names):
        raise CensusGeoSourceDriftError(
            f"ACS span {acquired.pin.span.span_id} row order drifted: expected {expected_names}, got {actual_names}"
        )
    return rows


# The full alphabetized live table also asserts its own total in a caption
# row ("635 variables") -- retained verbatim in the pinned span as a
# universe/vintage fact, not parsed as a variable row.
ACS_GEOGRAPHY_AND_PREDICATE_SPAN_ROW_NAMES = (
    "AIANHH",
    "CBSA",
    "CD",
    "COUNTY",
    "CSA",
    "DIVISION",
    "for",
    "GEO_ID",
    "GEOCOMP",
    "in",
)
ACS_S0201_ESTIMATE_VARIABLES_SPAN_ROW_NAMES = ("S0201_001E", "S0201_002E")
# Rows real and parsed from the pinned spans but not promoted to individual
# observations, to keep the captured sample small per catalog scope.
ACS_EXCLUDED_ROW_NAMES = frozenset({"AIANHH", "CBSA", "CD", "CSA", "DIVISION"})


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
_GEOID_EXAMPLE_ROW_RE = re.compile(
    r'<tr>\r?\n\t\t<td scope="row"[^>]*>(?P<geoid>.*?)</td>\r?\n' r"\t\t<td[^>]*>(?P<name>.*?)</td>\r?\n" r"\t</tr>"
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
GEOID_STRUCTURE_OBSERVED_AREA_TYPES = (
    "State",
    "County",
    "Census Tract",
    "Block Group",
    "Block",
    "Congressional District (113th Congress)",
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


@dataclass(frozen=True, slots=True)
class GeoidExampleRow:
    """One published example composite GEOID download key."""

    geoid: str
    name: str
    source_ordinal: int


def parse_geoid_example_span(acquired: AcquiredCensusGeoHtmlSpan) -> tuple[GeoidExampleRow, ...]:
    """Parse the GEO.ID/NAME example table and drop its column-label row."""

    payload = acquired.path.read_bytes()
    _verify_span_payload(payload, acquired.pin, location="parsed GEOID example span")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CensusGeoSourceDriftError("GEOID example span is not valid UTF-8") from error
    raw_rows = [(m.group("geoid").strip(), m.group("name").strip()) for m in _GEOID_EXAMPLE_ROW_RE.finditer(text)]
    if len(raw_rows) != 4:
        raise CensusGeoSourceDriftError(f"GEOID example table row count drifted: expected 4, got {len(raw_rows)}")
    if raw_rows[0] != ("id", "Geographic Area Name"):
        raise CensusGeoSourceDriftError("GEOID example table column-label row drifted")
    return tuple(
        GeoidExampleRow(geoid=geoid, name=name, source_ordinal=ordinal)
        for ordinal, (geoid, name) in enumerate(raw_rows[1:], start=1)
    )


# ---------------------------------------------------------------------------
# GNIS National File field identifiers (whole-PDF acquisition).
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
    """One published GNIS National File identifier-bearing field."""

    field_name: str
    field_type: str
    length: str
    description: str
    standard_citation: str
    source_ordinal: int


# Field order and content transcribed from, and checked against, the pinned
# PDF's "File format for Domestic National and States..." field table
# (National File) and its Appendix 3 standard citations. This module does
# not attempt full-layout PDF table reconstruction (the source uses a
# two-column field/description layout that pypdf's plain text extraction
# does not linearize); instead it requires each fact below to appear
# verbatim, after whitespace normalization, on its documented page.
GNIS_NATIONAL_FILE_FIELDS = (
    GNISFieldDefinition(
        field_name="feature_id",
        field_type="Number",
        length="10",
        description="Permanent, unique feature record identifier.",
        standard_citation="ANSI INCITS 446-2008 (R2018) (Appendix 3, number 1); supersedes the FIPS 55 Place Code.",
        source_ordinal=0,
    ),
    GNISFieldDefinition(
        field_name="state_numeric",
        field_type="Number",
        length="2",
        description="Two-digit code for the state containing the feature's primary coordinates.",
        standard_citation="ANSI INCITS 38-2009, replacing FIPS 5-2 (Appendix 3, number 2).",
        source_ordinal=4,
    ),
    GNISFieldDefinition(
        field_name="county_numeric",
        field_type="Number",
        length="3",
        description="Three-digit code for the county containing the feature's primary coordinates.",
        standard_citation="ANSI INCITS 31-2009, replacing FIPS 6-4 (Appendix 3, number 3).",
        source_ordinal=6,
    ),
)
# Every other field name published in the same National File table
# (feature_name, feature_class, state_name, county_name, map_name,
# date_created, date_edited, bgn_type, bgn_authority, bgn_date, and the
# eight prim_/source_ coordinate fields) is a descriptive or coordinate
# attribute, not an identifier, and stays out of this capture's scope.
GNIS_NATIONAL_FILE_FIELD_COUNT = 21

_GNIS_REQUIRED_TEXT: Mapping[int, str] = {
    0: "feature_id Number 10 Permanent, unique feature record identiﬁer. See Appendix 3, number 1.",
    1: (
        "county_name Character 100 The name of the county containing the primary coordinates. "
        "See Appendix 3, number 3. county_numeric Number 3"
    ),
    18: (
        "Appendix 3: Sources for ANSI standards and FIPS codes 1. The Feature ID is an ANSI "
        "standard as deﬁned as INCITS 446-2008 (R2018)"
    ),
    19: "2. The unique two-number state code is deﬁned in INCITS 38-2009 (replacing FIPS 5-2)",
}
_GNIS_REQUIRED_TEXT_PAGE_19_EXTRA = (
    "3. The unique three-number county code is deﬁned in INCITS 31-2009 (replacing FIPS 6- 4)"
)


def parse_gnis_file_format(acquired: AcquiredGNISFileFormat) -> tuple[GNISFieldDefinition, ...]:
    """Verify the pinned GNIS PDF still states each field's standard citation, then return them."""

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

    def normalized_page(index: int) -> str:
        return re.sub(r"\s+", " ", reader.pages[index].extract_text()).strip()

    for page_index, required_text in _GNIS_REQUIRED_TEXT.items():
        if required_text not in normalized_page(page_index):
            raise CensusGeoSourceDriftError(
                f"GNIS file-format PDF page {page_index + 1} no longer states {required_text!r}"
            )
    if _GNIS_REQUIRED_TEXT_PAGE_19_EXTRA not in normalized_page(19):
        raise CensusGeoSourceDriftError(
            f"GNIS file-format PDF page 20 no longer states {_GNIS_REQUIRED_TEXT_PAGE_19_EXTRA!r}"
        )
    return GNIS_NATIONAL_FILE_FIELDS


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
    acs_geography_span: AcquiredCensusGeoHtmlSpan,
    acs_estimate_span: AcquiredCensusGeoHtmlSpan,
    geoid_structure_span: AcquiredCensusGeoHtmlSpan,
    geoid_example_span: AcquiredCensusGeoHtmlSpan,
    gnis_pdf: AcquiredGNISFileFormat,
) -> SourceControlledResourceBundle:
    """Package the pinned ACS/TIGER/GNIS identifier-structure captures as one closed resource."""

    acs_geography_rows = parse_acs_variable_span(
        acs_geography_span, expected_names=ACS_GEOGRAPHY_AND_PREDICATE_SPAN_ROW_NAMES
    )
    acs_estimate_rows = parse_acs_variable_span(
        acs_estimate_span, expected_names=ACS_S0201_ESTIMATE_VARIABLES_SPAN_ROW_NAMES
    )
    geoid_structure_rows = parse_geoid_structure_span(geoid_structure_span)
    geoid_example_rows = parse_geoid_example_span(geoid_example_span)
    gnis_fields = parse_gnis_file_format(gnis_pdf)

    observations: list[dict[str, Any]] = []
    excluded = 0

    acs_source = ACS_GEOGRAPHY_AND_PREDICATE_SPAN.source_id
    for row in acs_geography_rows:
        if row.name in ACS_EXCLUDED_ROW_NAMES:
            excluded += 1
            continue
        kind = "acsApiPredicateParameterName" if row.required == "predicate-only" else "acsVariableName"
        observations.append(
            _observation(
                resource_id=CENSUS_GEO_IDENTIFIER_AUTHORITY_RESOURCE_ID,
                source_artifact=acs_source,
                source_path=f"variablesTable.row.{row.name}",
                source_ordinal=row.source_ordinal,
                label=row.label,
                identifier_value=row.name,
                identifier_kind=kind,
                authority_uri=CENSUS_ACS_VARIABLES_AUTHORITY_URI,
                source_uri=acs_source,
                observed_at=acs_geography_span.pin.retrieved_at,
                source_digest=acs_geography_span.sha256,
                extra={
                    "product": "acs1",
                    "vintage": "2024",
                    "universe": row.concept or None,
                    "required": row.required,
                    "predicateType": row.predicate_type,
                    "group": row.group_raw,
                },
            )
        )

    acs_estimate_source = ACS_S0201_ESTIMATE_VARIABLES_SPAN.source_id
    for row in acs_estimate_rows:
        observations.append(
            _observation(
                resource_id=CENSUS_GEO_IDENTIFIER_AUTHORITY_RESOURCE_ID,
                source_artifact=acs_estimate_source,
                source_path=f"variablesTable.row.{row.name}",
                source_ordinal=row.source_ordinal,
                label=row.label,
                identifier_value=row.name,
                identifier_kind="acsVariableName",
                authority_uri=CENSUS_ACS_VARIABLES_AUTHORITY_URI,
                source_uri=acs_estimate_source,
                observed_at=acs_estimate_span.pin.retrieved_at,
                source_digest=acs_estimate_span.sha256,
                extra={
                    "product": "acs1",
                    "vintage": "2024",
                    "universe": row.concept,
                    "required": row.required,
                    "predicateType": row.predicate_type,
                    "group": row.group_raw,
                },
            )
        )

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

    geoid_example_source = GEOID_DOWNLOAD_EXAMPLE_TABLE_SPAN.source_id
    for row in geoid_example_rows:
        observations.append(
            _observation(
                resource_id=CENSUS_GEO_IDENTIFIER_AUTHORITY_RESOURCE_ID,
                source_artifact=geoid_example_source,
                source_path=f"geoidExampleTable.row.{row.source_ordinal}",
                source_ordinal=row.source_ordinal,
                label=row.name,
                identifier_value=row.geoid,
                identifier_kind="tigerGeoidExampleValue",
                authority_uri=CENSUS_TIGER_GEOGRAPHY_AUTHORITY_URI,
                source_uri=CENSUS_GEOID_GUIDANCE_URL,
                observed_at=geoid_example_span.pin.retrieved_at,
                source_digest=geoid_example_span.sha256,
                extra={"product": "dataCensusGovGeoId", "exampleGeographicArea": row.name},
            )
        )
    excluded += 1  # the example table's own column-label row ("id" / "Geographic Area Name")

    gnis_source = GNIS_FILE_FORMAT_PDF_URL
    for field in gnis_fields:
        observations.append(
            _observation(
                resource_id=CENSUS_GEO_IDENTIFIER_AUTHORITY_RESOURCE_ID,
                source_artifact=gnis_source,
                source_path=f"nationalFileFieldTable.field.{field.field_name}",
                source_ordinal=field.source_ordinal,
                label=field.description,
                identifier_value=field.field_name,
                identifier_kind="gnisNationalFileFieldName",
                authority_uri=USGS_GNIS_AUTHORITY_URI,
                source_uri=gnis_source,
                observed_at=gnis_pdf.pin.retrieved_at,
                source_digest=gnis_pdf.sha256,
                extra={
                    "product": "gnisNationalFile",
                    "fieldType": field.field_type,
                    "length": field.length,
                    "standardCitation": field.standard_citation,
                },
            )
        )
    excluded += GNIS_NATIONAL_FILE_FIELD_COUNT - len(gnis_fields)

    source_artifacts = {
        acs_source: acs_geography_span.path.read_bytes(),
        acs_estimate_source: acs_estimate_span.path.read_bytes(),
        geoid_structure_source: geoid_structure_span.path.read_bytes(),
        geoid_example_source: geoid_example_span.path.read_bytes(),
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
        excluded_count=excluded,
        gaps=(
            {
                "kind": "sampledNamingGrammar",
                "reason": (
                    "api.census.gov/.../variables.html enumerates 635 variables for this one ACS "
                    "1-year dataset and vintage; this capture pins two small real spans and "
                    "promotes a representative subset of their rows, per catalog scope (never "
                    "ingest bulk entity rows)."
                ),
            },
            {
                "kind": "companionGeographySource",
                "reason": (
                    "The catalog's tiger-geo-line.html URL is a hub page linking to yearly PDFs; "
                    "the GEOID Structure and GEO.ID/NAME example tables captured here are "
                    "published on the companion census.gov geography guidance page it links out "
                    "to under the same Census Geography Program."
                ),
            },
            {
                "kind": "noBoundaryMethodField",
                "reason": (
                    "These captures describe identifier composition and naming syntax, not "
                    "cartographic boundary delineation method; TIGER/Line boundary methodology "
                    "lives in the separate technical-documentation chapters the hub links to and "
                    "is out of scope for this identifier-shape capture."
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
    "ACS_EXCLUDED_ROW_NAMES",
    "ACS_GEOGRAPHY_AND_PREDICATE_SPAN",
    "ACS_GEOGRAPHY_AND_PREDICATE_SPAN_2026_08_03",
    "ACS_GEOGRAPHY_AND_PREDICATE_SPAN_ROW_NAMES",
    "ACS_S0201_ESTIMATE_VARIABLES_SPAN",
    "ACS_S0201_ESTIMATE_VARIABLES_SPAN_2026_08_03",
    "ACS_S0201_ESTIMATE_VARIABLES_SPAN_ROW_NAMES",
    "CENSUS_ACS_VARIABLES_AUTHORITY_URI",
    "CENSUS_GEOID_GUIDANCE_URL",
    "CENSUS_GEO_IDENTIFIER_AUTHORITY_RESOURCE_ID",
    "CENSUS_GEO_IDENTIFIER_AUTHORITY_TITLE",
    "CENSUS_TIGER_GEOGRAPHY_AUTHORITY_URI",
    "GEOID_DOWNLOAD_EXAMPLE_TABLE_SPAN",
    "GEOID_DOWNLOAD_EXAMPLE_TABLE_SPAN_2026_08_03",
    "GEOID_STRUCTURE_OBSERVED_AREA_TYPES",
    "GEOID_STRUCTURE_TABLE_AREA_TYPES",
    "GEOID_STRUCTURE_TABLE_SPAN",
    "GEOID_STRUCTURE_TABLE_SPAN_2026_08_03",
    "GNIS_FILE_FORMAT_PDF_URL",
    "GNIS_FILE_FORMAT_PIN_2026_08_03",
    "GNIS_NATIONAL_FILE_FIELDS",
    "GNIS_NATIONAL_FILE_FIELD_COUNT",
    "USGS_GNIS_AUTHORITY_URI",
    "ACSVariableRow",
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
    "GeoidExampleRow",
    "acquire_census_geo_html_span",
    "acquire_gnis_file_format",
    "build_census_geo_identifier_authority_package",
    "parse_acs_variable_span",
    "parse_geoid_example_span",
    "parse_geoid_structure_span",
    "parse_gnis_file_format",
    "sha256_digest",
]
