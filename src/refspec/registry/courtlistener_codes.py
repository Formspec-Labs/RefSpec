"""Pinned CourtListener platform-normalized court identity codes.

CourtListener's "Available Jurisdictions" help page enumerates every court the
platform tracks in one settings-style table: a publisher-facing court Name, a
live case Count, a Jurisdiction classification (for example "Federal
Appellate" or "State Trial"), a Homepage link, an Abbreviation ("the value
used in our URLs, bulk data, etc."), a Citation Abbreviation gathered from
Blue Book/Cornell/ALWD, Start/End Date, an In Use flag, and a last-Modified
timestamp.

The Abbreviation and Jurisdiction classification are CourtListener's own
platform-normalized values. The page publishes no official identifier issued
by the court itself, so this module never treats an Abbreviation as an
official court code and always keeps the two apart: nothing here overwrites,
reconciles, or substitutes for an official court value obtained elsewhere.

The table also bakes a continuously changing case Count and last-Modified
timestamp into the same bytes as the stable identity fields. Unlike
lda.gov's static JSON constants, a whole-page digest pin here marks one dated
scrape observation, not a stable, independently re-fetchable release. A
handful of rows also carry a malformed or empty Jurisdiction cell (an
existing data-entry defect in CourtListener's own table, for example the bare
fragment "St"). This module records such values exactly as published; it
never corrects, infers, or drops a value, and it omits the jurisdiction-type
identifier only when the cell is empty.

This help page documents no opinion-type or opinion-status code list. Those
values live under a different part of CourtListener's API surface and stay
out of scope for this importer, which covers only the jurisdictions page.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection, and no scraping provider is
required to read the current help page.
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
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import (
    ResourceUse,
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

COURTLISTENER_HOSTS = frozenset({"www.courtlistener.com"})
COURTLISTENER_JURISDICTIONS_URL = "https://www.courtlistener.com/help/api/jurisdictions/"
COURTLISTENER_IDENTIFIER_AUTHORITY_URI = "https://www.courtlistener.com/"
COURTLISTENER_LANGUAGE = "en"
COURTLISTENER_JURISDICTIONS_RESOURCE_ID = "courtlistener-jurisdictions"

AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IN_USE_VALUES: Mapping[str, bool] = MappingProxyType({"Yes": True, "No": False})
_EXPECTED_COLUMN_HEADERS = (
    "Name",
    "Count",
    "Jurisdiction",
    "Homepage",
    "Abbreviation",
    "Citation Abbreviation",
    "Start Date",
    "End Date",
    "In Use",
    "Modified",
)
# Column positions within one <tr> of <td> cells, matching _EXPECTED_COLUMN_HEADERS.
_COLUMN_COUNT = len(_EXPECTED_COLUMN_HEADERS)
_NAME_COLUMN = 0
_JURISDICTION_COLUMN = 2
_ABBREVIATION_COLUMN = 4
_CITATION_ABBREVIATION_COLUMN = 5
_START_DATE_COLUMN = 6
_END_DATE_COLUMN = 7
_IN_USE_COLUMN = 8
_MODIFIED_COLUMN = 9
# Generic vendor challenge/interstitial markers. This page has never returned
# one in review, but a captured response that starts serving a bot challenge
# instead of the real table must fail closed rather than parse as empty.
_CHALLENGE_MARKERS = (
    b"cf-chl-",
    b"challenge-platform",
    b"cf-mitigated",
    b"attention required! | cloudflare",
    b"just a moment...</title>",
)
_NO_OFFICIAL_COURT_IDENTIFIER_GAP = MappingProxyType(
    {
        "kind": "officialCourtIdentifierUnavailable",
        "reason": (
            "This page publishes no identifier issued by the court itself; "
            "Abbreviation and Citation Abbreviation are CourtListener's own "
            "platform-normalized values. They must never overwrite or stand "
            "in for an official court value obtained elsewhere."
        ),
    }
)
_NO_OPINION_TYPE_LIST_GAP = MappingProxyType(
    {
        "kind": "opinionTypeListUnavailable",
        "reason": (
            "This help page documents only court/jurisdiction identity and "
            "CourtListener's jurisdiction-type classification. It publishes no "
            "opinion-type or opinion-status code list; that surface is out of "
            "scope for this importer."
        ),
    }
)
_VOLATILE_SNAPSHOT_GAP = MappingProxyType(
    {
        "kind": "volatileWholePagePin",
        "reason": (
            "The table renders a live per-court case Count and a last-Modified "
            "timestamp inside the same bytes as the stable identity fields, so "
            "a whole-page digest pin marks one dated scrape, not a stable, "
            "independently re-fetchable release."
        ),
    }
)
_MALFORMED_JURISDICTION_CELLS_GAP = MappingProxyType(
    {
        "kind": "malformedJurisdictionCellsObserved",
        "reason": (
            "A small number of rows carry a malformed or empty Jurisdiction "
            "cell, an existing data-entry defect in CourtListener's own table "
            '(for example the bare fragment "St"). This module records such '
            "values exactly as published and omits the jurisdiction-type "
            "identifier only when the cell is empty; it never corrects a value."
        ),
    }
)
COURTLISTENER_JURISDICTIONS_GAPS: tuple[Mapping[str, str], ...] = (
    _NO_OFFICIAL_COURT_IDENTIFIER_GAP,
    _NO_OPINION_TYPE_LIST_GAP,
    _VOLATILE_SNAPSHOT_GAP,
    _MALFORMED_JURISDICTION_CELLS_GAP,
)


class CourtListenerCodesError(ValueError):
    """Base class for CourtListener controlled-code failures."""


class CourtListenerAcquisitionError(CourtListenerCodesError):
    """Exact official page bytes could not be acquired safely."""


class CourtListenerSourceDriftError(CourtListenerCodesError):
    """The captured jurisdictions page no longer has the reviewed structure."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_courtlistener_url(value: str, field: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in COURTLISTENER_HOSTS:
        raise CourtListenerAcquisitionError(f"{field} must be an official HTTPS courtlistener.com URL")
    if parsed.username is not None or parsed.password is not None:
        raise CourtListenerAcquisitionError(f"{field} must not contain credentials")


@dataclass(frozen=True, slots=True)
class CourtListenerJurisdictionsSnapshotPin:
    """Exact identity of one captured jurisdictions page."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        _validate_courtlistener_url(self.source_url, "source_url")
        if self.source_url != COURTLISTENER_JURISDICTIONS_URL:
            raise CourtListenerAcquisitionError("source_url must be the official Available Jurisdictions help page")
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise CourtListenerAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise CourtListenerAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise CourtListenerAcquisitionError("retrieved_at must not be empty")


@dataclass(frozen=True, slots=True)
class FetchedCourtListenerPage:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class CourtListenerPageFetcher(Protocol):
    """Small transport boundary for the official jurisdictions help page."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedCourtListenerPage:
        """Fetch the page while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredCourtListenerJurisdictionsPage:
    """One verified source object in the content-addressed store."""

    pin: CourtListenerJurisdictionsSnapshotPin
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
        raise CourtListenerSourceDriftError(
            "courtlistener.com returned a challenge or interstitial page instead of the jurisdictions table"
        )
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise CourtListenerSourceDriftError("jurisdictions capture is not an HTML document")


def _validate_resolved_url(value: str) -> None:
    _validate_courtlistener_url(value, "fetcher resolved_url")


def _verify_payload(
    payload: bytes,
    pin: CourtListenerJurisdictionsSnapshotPin,
    *,
    location: str,
) -> tuple[str, int]:
    _validate_html_payload(payload)
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise CourtListenerSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise CourtListenerSourceDriftError(
            f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}"
        )
    return actual_sha256, byte_length


def _verify_existing(
    path: Path,
    pin: CourtListenerJurisdictionsSnapshotPin,
) -> AcquiredCourtListenerJurisdictionsPage:
    if path.is_symlink() or not path.is_file():
        raise CourtListenerAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached CourtListener jurisdictions page",
    )
    return AcquiredCourtListenerJurisdictionsPage(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source_url,
        resolved_url=None,
        content_type="text/html",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: CourtListenerJurisdictionsSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredCourtListenerJurisdictionsPage:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} CourtListener jurisdictions page",
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
        return AcquiredCourtListenerJurisdictionsPage(
            pin=pin,
            path=final_path,
            sha256=actual_sha256,
            byte_length=byte_length,
            source_url=pin.source_url,
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


def acquire_courtlistener_jurisdictions_page(
    pin: CourtListenerJurisdictionsSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: CourtListenerPageFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredCourtListenerJurisdictionsPage:
    """Acquire one exact jurisdictions page through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise CourtListenerAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise CourtListenerAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    final_path = Path(store_dir) / "sha256" / digest_hex / "courtlistener-jurisdictions.html"
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise CourtListenerAcquisitionError(f"local jurisdictions source is not a regular file: {local_path}")
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
        raise CourtListenerAcquisitionError(
            "jurisdictions page is not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise CourtListenerAcquisitionError(f"could not acquire {pin.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise CourtListenerSourceDriftError(f"jurisdictions page content type drifted to {fetched.content_type!r}")
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


class _JurisdictionsTableParser(HTMLParser):
    """Walk exactly one ``table.settings-table`` and collect its raw cell text.

    The parser never interprets any other part of the help page. It tracks a
    flat thead/tbody/tr/td state (no cell in this table nests another table),
    so any real structural change -- an added or removed column, a nested
    table, a missing ``tbody`` -- surfaces as a cell-count or header mismatch
    the caller rejects as drift rather than a silent parse.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_match_count = 0
        self.header_rows: list[list[str]] = []
        self.body_rows: list[list[str]] = []

        self._in_table = False
        self._in_thead = False
        self._in_tbody = False
        self._in_row = False
        self._in_cell = False
        self._cell_chunks: list[str] = []
        self._row_cells: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "table":
            classes = frozenset((attr_map.get("class") or "").split())
            if {"settings-table", "table"}.issubset(classes):
                self.table_match_count += 1
                self._in_table = True
            return
        if not self._in_table:
            return
        if tag == "thead":
            self._in_thead = True
        elif tag == "tbody":
            self._in_tbody = True
        elif tag == "tr" and (self._in_thead or self._in_tbody):
            self._in_row = True
            self._row_cells = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._cell_chunks = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if tag in ("td", "th") and self._in_cell:
            self._row_cells.append(_normalize_text(self._cell_chunks))
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._in_thead:
                self.header_rows.append(self._row_cells)
            elif self._in_tbody:
                self.body_rows.append(self._row_cells)
            self._in_row = False
        elif tag == "thead":
            self._in_thead = False
        elif tag == "tbody":
            self._in_tbody = False
        elif tag == "table":
            self._in_table = False


@dataclass(frozen=True, slots=True)
class CourtListenerJurisdictionRow:
    """One exact court/jurisdiction row captured verbatim from the page."""

    name: str
    jurisdiction_type: str | None
    citation_abbreviation: str | None
    start_date: str
    end_date: str
    in_use: bool
    modified: str
    source_ordinal: int
    identifiers: tuple[ControlledIdentifier, ...]


@dataclass(frozen=True, slots=True)
class ParsedCourtListenerJurisdictionsPage:
    """A parsed, digest-pinned CourtListener jurisdictions snapshot."""

    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    rows: tuple[CourtListenerJurisdictionRow, ...]
    gaps: tuple[Mapping[str, str], ...]

    def by_court_id(self) -> dict[str, CourtListenerJurisdictionRow]:
        """Index each row's platform court identifier, retaining every field."""

        result: dict[str, CourtListenerJurisdictionRow] = {}
        for row in self.rows:
            matches = [identifier for identifier in row.identifiers if identifier.kind == "courtlistenerCourtId"]
            if len(matches) != 1:
                raise CourtListenerSourceDriftError("jurisdictions row must retain exactly one courtlistenerCourtId")
            result[matches[0].value] = row
        return result


def _read_acquired_payload(page: AcquiredCourtListenerJurisdictionsPage) -> bytes:
    payload = page.path.read_bytes()
    _verify_payload(payload, page.pin, location="parsed CourtListener jurisdictions page")
    return payload


def parse_courtlistener_jurisdictions_page(
    page: AcquiredCourtListenerJurisdictionsPage,
) -> ParsedCourtListenerJurisdictionsPage:
    """Parse exact court rows without minting or correcting any value."""

    payload = _read_acquired_payload(page)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CourtListenerSourceDriftError("jurisdictions page is not UTF-8") from error

    parser = _JurisdictionsTableParser()
    try:
        parser.feed(decoded)
        parser.close()
    except CourtListenerCodesError:
        raise
    except Exception as error:
        raise CourtListenerSourceDriftError("jurisdictions page is malformed HTML") from error

    if parser.table_match_count != 1:
        raise CourtListenerSourceDriftError("jurisdictions page must contain exactly one settings-table")
    if len(parser.header_rows) != 1:
        raise CourtListenerSourceDriftError("jurisdictions table must have exactly one header row")
    if tuple(parser.header_rows[0]) != _EXPECTED_COLUMN_HEADERS:
        raise CourtListenerSourceDriftError(f"jurisdictions table columns drifted: {parser.header_rows[0]!r}")
    if not parser.body_rows:
        raise CourtListenerSourceDriftError("jurisdictions table has no court rows")

    rows: list[CourtListenerJurisdictionRow] = []
    for ordinal, cells in enumerate(parser.body_rows):
        if len(cells) != _COLUMN_COUNT:
            raise CourtListenerSourceDriftError(
                f"jurisdictions row {ordinal} has {len(cells)} cells, expected {_COLUMN_COUNT}"
            )

        name = cells[_NAME_COLUMN]
        if not name:
            raise CourtListenerSourceDriftError(f"jurisdictions row {ordinal} has an empty Name")
        abbreviation = cells[_ABBREVIATION_COLUMN]
        if not abbreviation:
            raise CourtListenerSourceDriftError(f"jurisdictions row {ordinal} has an empty Abbreviation")
        for column, label in ((_START_DATE_COLUMN, "Start Date"), (_END_DATE_COLUMN, "End Date")):
            value = cells[column]
            if value != "Unknown" and _ISO_DATE.fullmatch(value) is None:
                raise CourtListenerSourceDriftError(
                    f"jurisdictions row {ordinal} has an unrecognized {label} {value!r}"
                )
        raw_in_use = cells[_IN_USE_COLUMN]
        if raw_in_use not in _IN_USE_VALUES:
            raise CourtListenerSourceDriftError(
                f"jurisdictions row {ordinal} has an unrecognized In Use value {raw_in_use!r}"
            )
        modified = cells[_MODIFIED_COLUMN]
        if not modified:
            raise CourtListenerSourceDriftError(f"jurisdictions row {ordinal} has an empty Modified timestamp")

        # The Jurisdiction cell is captured exactly as published, including
        # known real-world defects (an empty cell, or a truncated fragment
        # such as "St"); this module never corrects or rejects that value.
        jurisdiction_type = cells[_JURISDICTION_COLUMN] or None
        citation_abbreviation = cells[_CITATION_ABBREVIATION_COLUMN] or None

        identifiers = [
            ControlledIdentifier(
                value=abbreviation,
                kind="courtlistenerCourtId",
                authority_uri=COURTLISTENER_IDENTIFIER_AUTHORITY_URI,
                source_uri=page.pin.source_url,
                observed_at=page.pin.retrieved_at,
                effective_at=None,
                source_digest=page.sha256,
            )
        ]
        if jurisdiction_type is not None:
            identifiers.append(
                ControlledIdentifier(
                    value=jurisdiction_type,
                    kind="courtlistenerJurisdictionType",
                    authority_uri=COURTLISTENER_IDENTIFIER_AUTHORITY_URI,
                    source_uri=page.pin.source_url,
                    observed_at=page.pin.retrieved_at,
                    effective_at=None,
                    source_digest=page.sha256,
                )
            )
        if citation_abbreviation is not None:
            identifiers.append(
                ControlledIdentifier(
                    value=citation_abbreviation,
                    kind="courtlistenerCitationAbbreviation",
                    authority_uri=COURTLISTENER_IDENTIFIER_AUTHORITY_URI,
                    source_uri=page.pin.source_url,
                    observed_at=page.pin.retrieved_at,
                    effective_at=None,
                    source_digest=page.sha256,
                )
            )

        rows.append(
            CourtListenerJurisdictionRow(
                name=name,
                jurisdiction_type=jurisdiction_type,
                citation_abbreviation=citation_abbreviation,
                start_date=cells[_START_DATE_COLUMN],
                end_date=cells[_END_DATE_COLUMN],
                in_use=_IN_USE_VALUES[raw_in_use],
                modified=modified,
                source_ordinal=ordinal,
                identifiers=tuple(identifiers),
            )
        )

    court_ids = {
        identifier.value for row in rows for identifier in row.identifiers if identifier.kind == "courtlistenerCourtId"
    }
    if len(court_ids) != len(rows):
        raise CourtListenerSourceDriftError("jurisdictions table contains duplicate platform court identifiers")

    return ParsedCourtListenerJurisdictionsPage(
        source_url=page.pin.source_url,
        retrieved_at=page.pin.retrieved_at,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        rows=tuple(rows),
        gaps=COURTLISTENER_JURISDICTIONS_GAPS,
    )


_IDENTIFIER_SOURCE_PATH_SUFFIX = {
    "courtlistenerCourtId": "abbreviation",
    "courtlistenerJurisdictionType": "jurisdiction",
    "courtlistenerCitationAbbreviation": "citationAbbreviation",
}


def _identifier_payload(identifier: ControlledIdentifier, *, source_path: str) -> dict[str, Any]:
    if identifier.kind not in _IDENTIFIER_SOURCE_PATH_SUFFIX:
        raise CourtListenerCodesError(f"unsupported CourtListener identifier kind {identifier.kind!r}")
    return {
        "value": identifier.value,
        "kind": identifier.kind,
        "authorityUri": identifier.authority_uri,
        "sourceUri": identifier.source_uri,
        "sourcePath": f"{source_path}.{_IDENTIFIER_SOURCE_PATH_SUFFIX[identifier.kind]}",
        "observedAt": identifier.observed_at,
        "sourceDigest": identifier.source_digest,
    }


def _observation_id(*, source_url: str, source_path: str, identifiers: Sequence[Mapping[str, Any]]) -> str:
    identity = {
        "resourceId": COURTLISTENER_JURISDICTIONS_RESOURCE_ID,
        "sourceArtifact": source_url,
        "sourcePath": source_path,
        "identifiers": [
            {"value": item["value"], "kind": item["kind"], "authorityUri": item["authorityUri"]} for item in identifiers
        ],
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{COURTLISTENER_JURISDICTIONS_RESOURCE_ID}:{digest}"


def _observation(row: CourtListenerJurisdictionRow, parsed: ParsedCourtListenerJurisdictionsPage) -> dict[str, Any]:
    source_path = f"table.tbody.tr[{row.source_ordinal}]"
    identifiers = [_identifier_payload(identifier, source_path=source_path) for identifier in row.identifiers]
    return {
        "id": _observation_id(source_url=parsed.source_url, source_path=source_path, identifiers=identifiers),
        "sourceArtifact": parsed.source_url,
        "sourcePath": source_path,
        # A source row locator only; platform identity always comes from
        # identifiers, never from this position in the table.
        "sourceOrdinal": row.source_ordinal,
        "labels": [
            {
                "value": row.name,
                "language": COURTLISTENER_LANGUAGE,
                "role": "preferred",
            }
        ],
        "identifiers": identifiers,
        "eligibleUses": ["deterministicMetadata"],
        "conceptIdentityClaimed": False,
        "inUse": row.in_use,
        "startDate": row.start_date,
        "endDate": row.end_date,
        "modified": row.modified,
    }


def build_courtlistener_jurisdictions_package(
    page: AcquiredCourtListenerJurisdictionsPage,
    parsed: ParsedCourtListenerJurisdictionsPage,
    *,
    uses: Sequence[ResourceUse] = ("deterministicMetadata",),
) -> SourceControlledResourceBundle:
    """Package the exact captured jurisdictions table as a controlled code list."""

    payload = page.path.read_bytes()
    if len(payload) != page.byte_length or sha256_digest(payload) != page.sha256:
        raise CourtListenerSourceDriftError("jurisdictions package source differs from its acquired pin")
    if parsed.source_sha256 != page.sha256:
        raise CourtListenerSourceDriftError("parsed jurisdictions page and acquired page digests differ")
    if parsed.source_url != page.pin.source_url:
        raise CourtListenerSourceDriftError("parsed jurisdictions page source_url differs from its acquired pin")

    observations = tuple(_observation(row, parsed) for row in parsed.rows)
    return build_source_controlled_resource_bundle(
        resource_id=COURTLISTENER_JURISDICTIONS_RESOURCE_ID,
        title="CourtListener platform-normalized court identity codes",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=uses,
        captured_at=parsed.retrieved_at,
        candidate_use_authorized=True,
        observations=observations,
        source_artifacts={parsed.source_url: payload},
        source_observed_count=len(parsed.rows),
        gaps=parsed.gaps,
    )


__all__ = [
    "COURTLISTENER_HOSTS",
    "COURTLISTENER_IDENTIFIER_AUTHORITY_URI",
    "COURTLISTENER_JURISDICTIONS_GAPS",
    "COURTLISTENER_JURISDICTIONS_RESOURCE_ID",
    "COURTLISTENER_JURISDICTIONS_URL",
    "COURTLISTENER_LANGUAGE",
    "AcquiredCourtListenerJurisdictionsPage",
    "AcquisitionMode",
    "CourtListenerAcquisitionError",
    "CourtListenerCodesError",
    "CourtListenerJurisdictionRow",
    "CourtListenerJurisdictionsSnapshotPin",
    "CourtListenerPageFetcher",
    "CourtListenerSourceDriftError",
    "FetchedCourtListenerPage",
    "ParsedCourtListenerJurisdictionsPage",
    "acquire_courtlistener_jurisdictions_page",
    "build_courtlistener_jurisdictions_package",
    "parse_courtlistener_jurisdictions_page",
    "sha256_digest",
]
