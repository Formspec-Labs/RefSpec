"""Pinned FEC committee master file code imports for entity normalization.

The Federal Election Commission publishes the committee master file layout,
plus the committee type and party code lists it references, only as prose
HTML documentation tables. There is no machine-readable code-list endpoint
for these values. The committee designation, filing frequency, and
organization type ("interest group category") codes are printed inline on
the committee master file description page; the committee type and party
codes are printed on two pages that page links to. All three pages are
captured and pinned so committee type and party codes are not silently
dropped just because they live behind a link.

Every code here is FEC-assigned entity/structural metadata used to normalize
committee records (committee type, designation, organization type, party,
and filing frequency). None of it is a document subject or general subject
concept, and the source publishes no report type code list reachable from
these pages, so report type is recorded as an explicit gap rather than
invented. This module captures only the published code descriptions; it
never reads or stores committee contact, treasurer, or address fields, which
carry their own statutory-use restrictions the code lists do not.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import (
    ControlledIdentifier,
    ControlledIdentifierError,
    validate_identifier_date,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

FEC_PUBLISHER = "Federal Election Commission"
FEC_IDENTIFIER_AUTHORITY_URI = "https://www.fec.gov/"

DocName = Literal["committeeMasterFile", "committeeTypeCodes", "partyCodes"]
ResourceName = Literal[
    "committeeDesignation",
    "committeeType",
    "party",
    "filingFrequency",
    "organizationType",
]
FECCodeUse = Literal["deterministicMetadata"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_INLINE_CODE_LINE = re.compile(r"^([A-Z])\s*=\s*(.+)$")
_COMMITTEE_TYPE_CODE = re.compile(r"^[A-Z]$")
_PARTY_CODE = re.compile(r"^[A-Z]{1,3}$|^[A-Z]/[A-Z]$")

# The "Column name" -> "Field name" pairs this module reads inline from the
# committee master file table. Asserting the human-readable field name too
# catches a column reshuffle that a code-only check would miss.
_INLINE_FIELDS: Mapping[ResourceName, tuple[str, str]] = {
    "committeeDesignation": ("CMTE_DSGN", "Committee designation"),
    "filingFrequency": ("CMTE_FILING_FREQ", "Filing frequency"),
    "organizationType": ("ORG_TP", "Interest group category"),
}
_RESOURCE_COUNTS: Mapping[ResourceName, int] = {
    "committeeDesignation": 6,
    "filingFrequency": 6,
    "organizationType": 6,
    "committeeType": 16,
    "party": 95,
}
_IDENTIFIER_KINDS: Mapping[ResourceName, str] = {
    "committeeDesignation": "committeeDesignationCode",
    "filingFrequency": "filingFrequencyCode",
    "organizationType": "organizationTypeCode",
    "committeeType": "committeeTypeCode",
    "party": "partyCode",
}


class FECCommitteeCodeError(ValueError):
    """Base class for FEC committee-code failures."""


class FECAcquisitionError(FECCommitteeCodeError):
    """Exact official documentation bytes could not be acquired safely."""


class FECSourceDriftError(FECCommitteeCodeError):
    """An FEC documentation page no longer matches the reviewed structure or pin."""


class FECAssignmentError(FECCommitteeCodeError):
    """A committee record carries an unknown source-assigned code."""


class FECPackageError(FECCommitteeCodeError):
    """A FEC controlled-code package is incomplete or inconsistent."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_datetime(value: str, field: str) -> str:
    try:
        return validate_identifier_date(value, field)
    except ControlledIdentifierError as error:
        raise FECAcquisitionError(str(error)) from error


@dataclass(frozen=True, slots=True)
class FECDocSource:
    """One official FEC documentation page publishing committee codes."""

    doc_name: DocName
    source_url: str
    filename: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "www.fec.gov":
            raise FECAcquisitionError("source_url must be an official HTTPS www.fec.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise FECAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise FECAcquisitionError("filename must be one plain path component")


FEC_COMMITTEE_MASTER_FILE_DOC = FECDocSource(
    doc_name="committeeMasterFile",
    source_url="https://www.fec.gov/campaign-finance-data/committee-master-file-description/",
    filename="committee-master-file-description.html",
)
FEC_COMMITTEE_TYPE_CODES_DOC = FECDocSource(
    doc_name="committeeTypeCodes",
    source_url="https://www.fec.gov/campaign-finance-data/committee-type-code-descriptions/",
    filename="committee-type-code-descriptions.html",
)
FEC_PARTY_CODES_DOC = FECDocSource(
    doc_name="partyCodes",
    source_url="https://www.fec.gov/campaign-finance-data/party-code-descriptions/",
    filename="party-code-descriptions.html",
)

# The committee master file page links to the committee type and party pages
# by relative path rather than repeating their codes; this is what a parsed
# link is compared against to catch a retargeted or broken link.
_LINKED_DOC_PATHS: Mapping[DocName, str] = {
    "committeeTypeCodes": "/campaign-finance-data/committee-type-code-descriptions",
    "partyCodes": "/campaign-finance-data/party-code-descriptions",
}


@dataclass(frozen=True, slots=True)
class FECSnapshotPin:
    """Exact identity of one official documentation response."""

    source: FECDocSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise FECAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise FECAcquisitionError("expected_byte_length must be positive")
        _require_datetime(self.retrieved_at, "retrieved_at")


FEC_COMMITTEE_MASTER_FILE_2026_08_03 = FECSnapshotPin(
    source=FEC_COMMITTEE_MASTER_FILE_DOC,
    retrieved_at="2026-08-03T19:24:00Z",
    expected_sha256="sha256:dda49be2e360d39bb1b7dcbc53239e627109a26fbaefe172688aca84abc4ff66",
    expected_byte_length=29_343,
)
FEC_COMMITTEE_TYPE_CODES_2026_08_03 = FECSnapshotPin(
    source=FEC_COMMITTEE_TYPE_CODES_DOC,
    retrieved_at="2026-08-03T19:24:00Z",
    expected_sha256="sha256:84e9f16628fd2475750cd89a3947f2c737a5f66c8ced04aea6b1118ac2aecaa4",
    expected_byte_length=28_121,
)
FEC_PARTY_CODES_2026_08_03 = FECSnapshotPin(
    source=FEC_PARTY_CODES_DOC,
    retrieved_at="2026-08-03T19:24:00Z",
    expected_sha256="sha256:e17420381df0e5709449a8c9702600fde97503ea378ef357beef4c40ed6a6b09",
    expected_byte_length=29_578,
)


@dataclass(frozen=True, slots=True)
class FetchedFECResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class FECFetcher(Protocol):
    """Small transport boundary for the official FEC documentation pages."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedFECResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredFECSource:
    """One verified source object in the content-addressed store."""

    pin: FECSnapshotPin
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
class FECCode:
    """One exact publisher-documented committee code and its description."""

    resource_name: ResourceName
    use: FECCodeUse
    publisher_label: str
    description: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedFECResource:
    """A parsed, digest-pinned FEC committee code list."""

    resource_name: ResourceName
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    source_url: str
    codes: tuple[FECCode, ...]

    def by_code(self) -> dict[str, FECCode]:
        """Index every code by its exact publisher-assigned value."""

        result: dict[str, FECCode] = {}
        for entry in self.codes:
            result[entry.identifiers[0].value] = entry
        return result


@dataclass(frozen=True, slots=True)
class FECCommitteePortfolio:
    """The five imported committee code resources and known source gaps."""

    committee_designation: ParsedFECResource
    committee_type: ParsedFECResource
    party: ParsedFECResource
    filing_frequency: ParsedFECResource
    organization_type: ParsedFECResource
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidatedFECCommitteeCodes:
    """Code evidence retained from one committee master file record."""

    committee_designation: FECCode | None
    committee_type: FECCode | None
    party: FECCode | None
    filing_frequency: FECCode | None
    organization_type: FECCode | None


FEC_PORTFOLIO_GAPS = (
    (
        "The committee master file description page and its committee type "
        "and party code links publish no report type codes; report type "
        "values are not part of the committee master file layout and no "
        "reachable page from this source documents them."
    ),
    (
        "These pages publish only the current code tables with no cycle or "
        "effective-date range per code; retrieval time and exact digest are "
        "the available revision pin, and every identifier's effective_at is "
        "recorded as explicitly unknown rather than inferred."
    ),
    (
        "Committee master file records also carry treasurer name and street "
        "address fields (Null = Y like the codes captured here) that are "
        "individual contact data subject to statutory use restrictions; this "
        "module captures only code descriptions and never those fields."
    ),
)


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "www.fec.gov":
        raise FECAcquisitionError("fetcher resolved_url must remain on official HTTPS www.fec.gov")
    if parsed.username is not None or parsed.password is not None:
        raise FECAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: FECSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise FECSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise FECSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FECSourceDriftError(f"{location} is not valid UTF-8 HTML") from error
    if not text.lstrip().lower().startswith("<!doctype html"):
        raise FECSourceDriftError(f"{location} does not open with an HTML doctype")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: FECSnapshotPin) -> AcquiredFECSource:
    if path.is_symlink() or not path.is_file():
        raise FECAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached FEC source",
    )
    return AcquiredFECSource(
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
    pin: FECSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredFECSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} FEC source",
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
        return AcquiredFECSource(
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


def acquire_fec_doc(
    pin: FECSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: FECFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredFECSource:
    """Acquire one exact documentation response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise FECAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise FECAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise FECAcquisitionError(f"local FEC source is not a regular file: {local_path}")
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
        raise FECAcquisitionError("FEC documentation is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise FECAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "text/html":
        raise FECSourceDriftError(f"FEC documentation content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _clean_cell(cell: str) -> str:
    stripped = re.sub(r"<[^>]+>", " ", cell)
    return re.sub(r"\s+", " ", html.unescape(stripped)).strip()


def _identifier(value: str, kind: str, source_url: str, acquired: AcquiredFECSource) -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=kind,
        authority_uri=FEC_IDENTIFIER_AUTHORITY_URI,
        source_uri=source_url,
        observed_at=acquired.pin.retrieved_at,
        effective_at=None,
        source_digest=acquired.sha256,
    )


def _verify_cross_reference_links(text: str) -> None:
    """The master file page must still link to the pages holding CMTE_TP and CMTE_PTY_AFFILIATION."""

    for doc_name, expected_path in _LINKED_DOC_PATHS.items():
        pattern = re.compile(r'href="(https://www\.fec\.gov[^"]*)"')
        if not any(urlsplit(href).path.rstrip("/") == expected_path for href in pattern.findall(text)):
            linked = FEC_COMMITTEE_TYPE_CODES_DOC if doc_name == "committeeTypeCodes" else FEC_PARTY_CODES_DOC
            raise FECSourceDriftError(
                f"committee master file page no longer links to {linked.source_url} "
                f"({linked.source_url.rstrip('/').rsplit('/', 1)[-1]})"
            )


def _extract_inline_description_cell(text: str, column_name: str, expected_field_label: str) -> str:
    # Column layout: Column name, Field name, Position, Null, Data type,
    # Description, Example data. Capture Field name too so a column
    # reshuffle is caught even if it happens not to change the row count.
    pattern = re.compile(
        r"<tr>\s*<td>\s*"
        + re.escape(column_name)
        + r"\s*</td>\s*<td[^>]*>(.*?)</td>\s*"
        + r"(?:<td[^>]*>.*?</td>\s*){3}"
        + r"<td[^>]*>(.*?)</td>\s*<td[^>]*>.*?</td>\s*</tr>",
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise FECSourceDriftError(f"could not locate the {column_name!r} row on the committee master file page")
    field_label = _clean_cell(match.group(1))
    if field_label != expected_field_label:
        raise FECSourceDriftError(
            f"{column_name} field name drift: expected {expected_field_label!r}, got {field_label!r}"
        )
    return match.group(2)


def _parse_inline_resource(acquired: AcquiredFECSource, resource_name: ResourceName) -> ParsedFECResource:
    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed FEC source")
    text = payload.decode("utf-8")
    _verify_cross_reference_links(text)

    column_name, expected_field_label = _INLINE_FIELDS[resource_name]
    cell = _extract_inline_description_cell(text, column_name, expected_field_label)
    lines = [_clean_cell(part) for part in re.split(r"<br\s*/?>", cell)]
    lines = [line for line in lines if line]

    codes: list[FECCode] = []
    for line in lines:
        match = _INLINE_CODE_LINE.fullmatch(line)
        if match is None:
            raise FECSourceDriftError(f"unrecognized {column_name} description line: {line!r}")
        code, label = match.group(1), match.group(2).strip()
        codes.append(
            FECCode(
                resource_name=resource_name,
                use="deterministicMetadata",
                publisher_label=label,
                description="",
                source_url=FEC_COMMITTEE_MASTER_FILE_DOC.source_url,
                identifiers=(
                    _identifier(
                        code,
                        _IDENTIFIER_KINDS[resource_name],
                        FEC_COMMITTEE_MASTER_FILE_DOC.source_url,
                        acquired,
                    ),
                ),
            )
        )

    expected_count = _RESOURCE_COUNTS[resource_name]
    if len(codes) != expected_count:
        raise FECSourceDriftError(f"{column_name} code count drift: expected {expected_count}, parsed {len(codes)}")
    if len({code.identifiers[0].value for code in codes}) != len(codes):
        raise FECSourceDriftError(f"{column_name} contains a duplicate publisher code")

    return ParsedFECResource(
        resource_name=resource_name,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        source_url=FEC_COMMITTEE_MASTER_FILE_DOC.source_url,
        codes=tuple(codes),
    )


def parse_committee_designation_codes(acquired: AcquiredFECSource) -> ParsedFECResource:
    """Parse the inline CMTE_DSGN codes from the committee master file page."""

    return _parse_inline_resource(acquired, "committeeDesignation")


def parse_filing_frequency_codes(acquired: AcquiredFECSource) -> ParsedFECResource:
    """Parse the inline CMTE_FILING_FREQ codes from the committee master file page."""

    return _parse_inline_resource(acquired, "filingFrequency")


def parse_organization_type_codes(acquired: AcquiredFECSource) -> ParsedFECResource:
    """Parse the inline ORG_TP codes from the committee master file page."""

    return _parse_inline_resource(acquired, "organizationType")


def _extract_single_table(text: str, *, location: str) -> str:
    match = re.search(r"<table[^>]*>(.*?)</table>", text, re.DOTALL)
    if match is None:
        raise FECSourceDriftError(f"could not locate the {location} table")
    return match.group(1)


def parse_committee_type_codes(acquired: AcquiredFECSource) -> ParsedFECResource:
    """Parse the CMTE_TP code table from the committee type code descriptions page."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed FEC source")
    text = payload.decode("utf-8")

    table = _extract_single_table(text, location="committee type")
    rows = re.findall(r"<tr>\s*(.*?)\s*</tr>", table, re.DOTALL)
    if len(rows) < 2:
        raise FECSourceDriftError("committee type table has no data rows")
    data_rows = rows[1:]

    codes: list[FECCode] = []
    for row in data_rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) != 3:
            raise FECSourceDriftError(f"committee type row has {len(cells)} cells, expected 3")
        code = _clean_cell(cells[0])
        label = _clean_cell(cells[1])
        description = _clean_cell(cells[2])
        if _COMMITTEE_TYPE_CODE.fullmatch(code) is None:
            raise FECSourceDriftError(f"malformed committee type code: {code!r}")
        if not label:
            raise FECSourceDriftError(f"committee type code {code!r} has an empty label")
        codes.append(
            FECCode(
                resource_name="committeeType",
                use="deterministicMetadata",
                publisher_label=label,
                description=description,
                source_url=FEC_COMMITTEE_TYPE_CODES_DOC.source_url,
                identifiers=(
                    _identifier(
                        code,
                        _IDENTIFIER_KINDS["committeeType"],
                        FEC_COMMITTEE_TYPE_CODES_DOC.source_url,
                        acquired,
                    ),
                ),
            )
        )

    expected_count = _RESOURCE_COUNTS["committeeType"]
    if len(codes) != expected_count:
        raise FECSourceDriftError(f"committee type code count drift: expected {expected_count}, got {len(codes)}")
    if len({code.identifiers[0].value for code in codes}) != len(codes):
        raise FECSourceDriftError("committee type table contains a duplicate publisher code")

    return ParsedFECResource(
        resource_name="committeeType",
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        source_url=FEC_COMMITTEE_TYPE_CODES_DOC.source_url,
        codes=tuple(codes),
    )


def parse_party_codes(acquired: AcquiredFECSource) -> ParsedFECResource:
    """Parse the CMTE_PTY_AFFILIATION code table from the party code descriptions page."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed FEC source")
    text = payload.decode("utf-8")

    table = _extract_single_table(text, location="party code")
    rows = re.findall(r"<tr>\s*(.*?)\s*</tr>", table, re.DOTALL)
    if len(rows) < 2:
        raise FECSourceDriftError("party code table has no data rows")
    data_rows = rows[1:]

    codes: list[FECCode] = []
    for row in data_rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) != 3:
            raise FECSourceDriftError(f"party code row has {len(cells)} cells, expected 3")
        code = _clean_cell(cells[0])
        label = _clean_cell(cells[1])
        notes = _clean_cell(cells[2])
        if _PARTY_CODE.fullmatch(code) is None:
            raise FECSourceDriftError(f"malformed party code: {code!r}")
        if not label:
            raise FECSourceDriftError(f"party code {code!r} has an empty description")
        codes.append(
            FECCode(
                resource_name="party",
                use="deterministicMetadata",
                publisher_label=label,
                description=notes,
                source_url=FEC_PARTY_CODES_DOC.source_url,
                identifiers=(_identifier(code, _IDENTIFIER_KINDS["party"], FEC_PARTY_CODES_DOC.source_url, acquired),),
            )
        )

    expected_count = _RESOURCE_COUNTS["party"]
    if len(codes) != expected_count:
        raise FECSourceDriftError(f"party code count drift: expected {expected_count}, got {len(codes)}")
    if len({code.identifiers[0].value for code in codes}) != len(codes):
        raise FECSourceDriftError("party code table contains a duplicate publisher code")

    return ParsedFECResource(
        resource_name="party",
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        source_url=FEC_PARTY_CODES_DOC.source_url,
        codes=tuple(codes),
    )


def assemble_fec_committee_portfolio(
    resources: Sequence[ParsedFECResource],
) -> FECCommitteePortfolio:
    """Require all five distinct resources and retain unsupported-control gaps."""

    by_name = {resource.resource_name: resource for resource in resources}
    required: frozenset[ResourceName] = frozenset(
        {"committeeDesignation", "committeeType", "party", "filingFrequency", "organizationType"}
    )
    if len(resources) != 5 or set(by_name) != required:
        raise FECSourceDriftError(
            "FEC committee code portfolio requires exactly one of each: "
            "committeeDesignation, committeeType, party, filingFrequency, organizationType"
        )
    return FECCommitteePortfolio(
        committee_designation=by_name["committeeDesignation"],
        committee_type=by_name["committeeType"],
        party=by_name["party"],
        filing_frequency=by_name["filingFrequency"],
        organization_type=by_name["organizationType"],
        gaps=FEC_PORTFOLIO_GAPS,
    )


def _validate_field(
    raw_value: object,
    resource: ParsedFECResource,
    field_label: str,
) -> FECCode | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise FECAssignmentError(f"{field_label} must be a string or null")
    code = resource.by_code().get(raw_value)
    if code is None:
        raise FECAssignmentError(f"unknown FEC {field_label} code {raw_value!r}")
    return code


def validate_committee_master_record(
    record: Mapping[str, object],
    portfolio: FECCommitteePortfolio,
) -> ValidatedFECCommitteeCodes:
    """Validate the source-assigned codes on one committee master file record."""

    return ValidatedFECCommitteeCodes(
        committee_designation=_validate_field(
            record.get("cmte_dsgn"), portfolio.committee_designation, "committee designation"
        ),
        committee_type=_validate_field(record.get("cmte_tp"), portfolio.committee_type, "committee type"),
        party=_validate_field(record.get("cmte_pty_affiliation"), portfolio.party, "party"),
        filing_frequency=_validate_field(
            record.get("cmte_filing_freq"), portfolio.filing_frequency, "filing frequency"
        ),
        organization_type=_validate_field(record.get("org_tp"), portfolio.organization_type, "organization type"),
    )


def _package_observations(
    resource: ParsedFECResource,
) -> tuple[Mapping[str, Any], ...]:
    observations: list[Mapping[str, Any]] = []
    for ordinal, code in enumerate(resource.codes):
        identifier = code.identifiers[0]
        source_path = f"$.{resource.resource_name}.{identifier.value}"
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
            "resourceName": resource.resource_name,
            "sourceArtifact": resource.source_url,
            "sourcePath": source_path,
            "value": identifier.value,
        }
        observation_id = (
            "urn:ref:source-observation:fec-committee-codes:"
            + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        )
        observations.append(
            {
                "id": observation_id,
                "sourceArtifact": resource.source_url,
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
                "description": code.description,
            }
        )
    return tuple(observations)


def build_fec_committee_code_package(
    resource_name: ResourceName,
    resource: ParsedFECResource,
    acquired: AcquiredFECSource,
) -> SourceControlledResourceBundle:
    """Build one development-only, deterministic closed package for one code family."""

    if resource_name not in _RESOURCE_COUNTS or resource.resource_name != resource_name:
        raise FECPackageError(f"unknown FEC committee resource family {resource_name!r}")
    payload = acquired.path.read_bytes()
    captured_date = resource.retrieved_at[:10]
    return build_source_controlled_resource_bundle(
        resource_id=f"fec-committee-{resource_name}-{captured_date}",
        title=f"FEC committee {resource_name} codes, captured {captured_date}",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("deterministicMetadata",),
        captured_at=resource.retrieved_at,
        candidate_use_authorized=True,
        observations=_package_observations(resource),
        source_artifacts={resource.source_url: payload},
        source_observed_count=len(resource.codes),
        gaps=[{"kind": "sourceProseOnly", "reason": gap} for gap in FEC_PORTFOLIO_GAPS],
    )


__all__ = [
    "FEC_COMMITTEE_MASTER_FILE_2026_08_03",
    "FEC_COMMITTEE_MASTER_FILE_DOC",
    "FEC_COMMITTEE_TYPE_CODES_2026_08_03",
    "FEC_COMMITTEE_TYPE_CODES_DOC",
    "FEC_IDENTIFIER_AUTHORITY_URI",
    "FEC_PARTY_CODES_2026_08_03",
    "FEC_PARTY_CODES_DOC",
    "FEC_PORTFOLIO_GAPS",
    "FEC_PUBLISHER",
    "AcquiredFECSource",
    "DocName",
    "FECAcquisitionError",
    "FECAssignmentError",
    "FECCode",
    "FECCommitteeCodeError",
    "FECCommitteePortfolio",
    "FECDocSource",
    "FECFetcher",
    "FECPackageError",
    "FECSnapshotPin",
    "FECSourceDriftError",
    "FetchedFECResponse",
    "ParsedFECResource",
    "ResourceName",
    "ValidatedFECCommitteeCodes",
    "acquire_fec_doc",
    "assemble_fec_committee_portfolio",
    "build_fec_committee_code_package",
    "parse_committee_designation_codes",
    "parse_committee_type_codes",
    "parse_filing_frequency_codes",
    "parse_organization_type_codes",
    "parse_party_codes",
    "sha256_digest",
    "validate_committee_master_record",
]
