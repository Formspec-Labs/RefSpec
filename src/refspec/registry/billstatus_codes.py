"""Pinned Congress.gov BILLSTATUS code-set imports.

The govinfo BILLSTATUS bulk-data readme names the ``usgpo/bill-status``
GitHub user guide as the source of code-table documentation. That guide
publishes three controlled code sets used by Bill Status XML records:
``<billType>`` values, ``<actionCode>`` values, and the Library of
Congress summary ``<versionCode>`` values. All three are source-native
deterministic metadata and transport schema, not general subject
concepts, per the catalog decision for this source; none of them is
promoted into a concept scheme here.

The action code table carries the publisher's own completeness
disclaimer -- "a complete, authoritative list of action codes does not
exist" -- so this module treats it as an open courtesy list: unmatched
action codes are preserved as raw source values rather than refused.
Bill types and summary version codes carry no such disclaimer and are
treated as closed enumerations that fail closed on an unknown value.

The Congress.gov API (https://api.congress.gov/) requires a caller-
supplied API key for every endpoint, including ``/v3/bill``, and does
not publish a separate constants endpoint for these three code sets;
this module therefore acquires the code sets from the govinfo-endorsed
GitHub user guide only.

The Bill Status XML ``<version>`` element is a per-document schema
version supplied by the Library of Congress, not an enumerated code.
Record validation here pins it by requiring callers to supply it and
threading it through unchanged -- never inferring or validating it
against a fixed set, and never inferring a subject from an XML element
name.

Acquisition accepts a local exact capture or an injected fetcher.
Importing this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode

BILLSTATUS_PUBLISHER = (
    "U.S. Government Publishing Office, Library of Congress, Clerk of the "
    "U.S. House of Representatives, and Secretary of the U.S. Senate"
)
BILLSTATUS_README_URL = "https://www.govinfo.gov/bulkdata/BILLSTATUS/resources/readme.html"
BILLSTATUS_USER_GUIDE_URL = (
    "https://raw.githubusercontent.com/usgpo/bill-status/master/BILLSTATUS-XML_User_User-Guide.md"
)
BILLSTATUS_IDENTIFIER_AUTHORITY_URI = "https://www.govinfo.gov/bulkdata/BILLSTATUS/"

# Captured for provenance only: the govinfo readme is the catalog-named entry
# point and redirects readers to the GitHub user guide for code tables. This
# module does not acquire or parse the readme; it pins the user guide below.
BILLSTATUS_README_2026_08_03_SHA256 = "sha256:e427efe065ca9742f41b8defc17a46f95b68f25e78d71c0f6f85dd4e4099b354"
BILLSTATUS_README_2026_08_03_BYTE_LENGTH = 656

ResourceName = Literal["billTypes", "actionCodes", "summaryVersionCodes"]
ResourceUse = Literal["deterministicMetadata"]
CompletenessStatus = Literal["closedEnumeration", "openCourtesyList"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_BILL_TYPE_CODE = re.compile(r"^[A-Z]{1,7}$")
_ACTION_CODE = re.compile(r"^[A-Z0-9]{4,6}$")
_VERSION_CODE = re.compile(r"^[0-9]{2}$")
_CHAMBERS = frozenset({"HOUSE", "SENATE", "BOTH"})
_SEPARATOR_CELL = re.compile(r"^:?-+:?$")
_BOLD_CELL = re.compile(r"^\*\*(.+)\*\*$")
_BILL_TYPE_SENTENCE = re.compile(r"^Bill type \(Possible values are (.+)\)\.\s*$")

_HEADER_ACTION_CODES = "# 3. Action Code Element Possible Values"
_HEADER_VERSION_CODES = "# 5. Mapping of LOC Summaries Version Codes and  Action Description Text"
_HEADER_BILL_TYPE = "### `<billType>`"

_CODE_KIND: dict[ResourceName, str] = {
    "billTypes": "billTypeCode",
    "actionCodes": "actionCode",
    "summaryVersionCodes": "billVersionCode",
}
_CHAMBER_KIND = "billVersionChamber"

_EXPECTED_COUNTS: dict[ResourceName, int] = {
    "billTypes": 8,
    "actionCodes": 36,
    "summaryVersionCodes": 88,
}


class BillStatusResourceError(ValueError):
    """Base class for BILLSTATUS controlled-code failures."""


class BillStatusAcquisitionError(BillStatusResourceError):
    """Exact official source bytes could not be acquired safely."""


class BillStatusSourceDriftError(BillStatusResourceError):
    """A BILLSTATUS source no longer matches the reviewed structure or pin."""


class BillStatusAssignmentError(BillStatusResourceError):
    """A record carries an unknown, missing, or inconsistent BILLSTATUS code."""


@dataclass(frozen=True, slots=True)
class BillStatusDocumentSource:
    """The one official document that publishes these code tables."""

    source_url: str
    filename: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
            raise BillStatusAcquisitionError("source_url must be an official HTTPS raw.githubusercontent.com URL")
        if parsed.username is not None or parsed.password is not None:
            raise BillStatusAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise BillStatusAcquisitionError("filename must be one plain path component")


BILLSTATUS_USER_GUIDE = BillStatusDocumentSource(
    source_url=BILLSTATUS_USER_GUIDE_URL,
    filename="billstatus-xml-user-guide.md",
)


@dataclass(frozen=True, slots=True)
class BillStatusSnapshotPin:
    """Exact identity of one official user-guide capture."""

    source: BillStatusDocumentSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise BillStatusAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise BillStatusAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise BillStatusAcquisitionError("retrieved_at must not be empty")


# Exact bytes observed on 2026-08-03 from the official GitHub raw endpoint.
BILLSTATUS_USER_GUIDE_2026_08_03 = BillStatusSnapshotPin(
    source=BILLSTATUS_USER_GUIDE,
    retrieved_at="2026-08-03T19:29:08Z",
    expected_sha256="sha256:a10909696b2ed2244d75c76e75fa32bc3e4eb926deab7e4e00592a6a01c3ad3a",
    expected_byte_length=38_802,
)


@dataclass(frozen=True, slots=True)
class FetchedBillStatusResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class BillStatusFetcher(Protocol):
    """Small transport boundary for the official BILLSTATUS user guide."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedBillStatusResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredBillStatusSource:
    """One verified source object in the content-addressed store."""

    pin: BillStatusSnapshotPin
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
class BillStatusCode:
    """One exact publisher code plus every identifier retained for that row."""

    resource_name: ResourceName
    use: ResourceUse
    completeness: CompletenessStatus
    publisher_label: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedBillStatusResource:
    """A parsed, digest-pinned BILLSTATUS code set."""

    resource_name: ResourceName
    use: ResourceUse
    completeness: CompletenessStatus
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    codes: tuple[BillStatusCode, ...]

    def by_code(self) -> dict[str, BillStatusCode]:
        """Index by publisher code; refuses a resource whose codes repeat."""

        code_kind = _CODE_KIND[self.resource_name]
        result: dict[str, BillStatusCode] = {}
        for entry in self.codes:
            matches = [identifier for identifier in entry.identifiers if identifier.kind == code_kind]
            if len(matches) != 1:
                raise BillStatusSourceDriftError(f"{self.resource_name} row must retain exactly one {code_kind}")
            value = matches[0].value
            if value in result:
                raise BillStatusSourceDriftError(
                    f"{self.resource_name} code {value!r} is not unique; use by_code_and_chamber()"
                )
            result[value] = entry
        return result

    def by_code_and_chamber(self) -> dict[tuple[str, str | None], BillStatusCode]:
        """Index by publisher code and chamber, the disambiguated key."""

        code_kind = _CODE_KIND[self.resource_name]
        result: dict[tuple[str, str | None], BillStatusCode] = {}
        for entry in self.codes:
            code_matches = [identifier for identifier in entry.identifiers if identifier.kind == code_kind]
            if len(code_matches) != 1:
                raise BillStatusSourceDriftError(f"{self.resource_name} row must retain exactly one {code_kind}")
            chamber_matches = [identifier for identifier in entry.identifiers if identifier.kind == _CHAMBER_KIND]
            chamber = chamber_matches[0].value if chamber_matches else None
            key = (code_matches[0].value, chamber)
            if key in result:
                raise BillStatusSourceDriftError(f"{self.resource_name} code/chamber pair is not unique: {key!r}")
            result[key] = entry
        return result


@dataclass(frozen=True, slots=True)
class BillStatusControlPortfolio:
    """The three imported code sets and their documented limits."""

    bill_types: ParsedBillStatusResource
    action_codes: ParsedBillStatusResource
    summary_version_codes: ParsedBillStatusResource
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BillStatusCodeAssignment:
    """One record field validated against the exact source snapshot."""

    source_field: str
    matched: bool
    raw_value: str
    publisher_label: str | None
    use: ResourceUse
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool


@dataclass(frozen=True, slots=True)
class ValidatedBillStatusRecord:
    """Code evidence retained from one BILLSTATUS-shaped record."""

    schema_version: str
    bill_type: BillStatusCodeAssignment
    action_codes: tuple[BillStatusCodeAssignment, ...]
    summary_versions: tuple[BillStatusCodeAssignment, ...]
    gaps: tuple[str, ...]


BILLSTATUS_PORTFOLIO_GAPS = (
    (
        "The publisher states in the user guide that the action code table is a courtesy excerpt and that "
        '"a complete, authoritative list of action codes does not exist"; unmatched action codes are '
        "preserved as raw source values rather than refused."
    ),
    (
        'Section 1.1 of the user guide describes House Bill with the parenthetical abbreviation "(HR)", but '
        'the <billType> element description in section 2.1 enumerates the machine value as "H"; this module '
        "pins the section 2.1 enumeration and does not reconcile the two."
    ),
    (
        "The Bill Status XML <version> element is a per-document schema/format version supplied by the "
        "Library of Congress and is not itself an enumerated code; record validation requires callers to "
        "supply it and threads it through unchanged rather than validating it against a fixed set."
    ),
    (
        "The user guide does not publish a machine-readable code-list release identifier or revision date; "
        "retrieval time and the exact document digest are the available revision pin."
    ),
)


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
        raise BillStatusAcquisitionError("fetcher resolved_url must remain on official HTTPS raw.githubusercontent.com")
    if parsed.username is not None or parsed.password is not None:
        raise BillStatusAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: BillStatusSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise BillStatusSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise BillStatusSourceDriftError(
            f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}"
        )
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BillStatusSourceDriftError(f"{location} is not valid UTF-8 text") from error
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: BillStatusSnapshotPin) -> AcquiredBillStatusSource:
    if path.is_symlink() or not path.is_file():
        raise BillStatusAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached BILLSTATUS source",
    )
    return AcquiredBillStatusSource(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type="text/plain",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: BillStatusSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredBillStatusSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} BILLSTATUS source",
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
        return AcquiredBillStatusSource(
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


def acquire_billstatus_source(
    pin: BillStatusSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: BillStatusFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredBillStatusSource:
    """Acquire the exact user-guide response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise BillStatusAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise BillStatusAcquisitionError("provide source_path or fetcher, not both")
    digest_match = _DIGEST.fullmatch(pin.expected_sha256)
    if digest_match is None:
        raise BillStatusAcquisitionError("pin.expected_sha256 must be a lowercase sha256:<64 hex> digest")
    digest_hex = digest_match.group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise BillStatusAcquisitionError(f"local BILLSTATUS source is not a regular file: {local_path}")
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
        raise BillStatusAcquisitionError(
            "the BILLSTATUS user guide is not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise BillStatusAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/plain", "text/markdown"}:
        raise BillStatusSourceDriftError(f"BILLSTATUS user guide content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _split_row(line: str, header_line: str) -> list[str]:
    stripped = line.strip()
    if len(stripped) < 2 or not (stripped.startswith("|") and stripped.endswith("|")):
        raise BillStatusSourceDriftError(f"malformed table row under {header_line!r}: {line!r}")
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _is_separator_row(line: str, column_count: int, header_line: str) -> bool:
    cells = _split_row(line, header_line)
    return len(cells) == column_count and all(_SEPARATOR_CELL.fullmatch(cell) for cell in cells)


def _strip_bold(cell: str, header_line: str) -> str:
    match = _BOLD_CELL.fullmatch(cell)
    if match is None:
        raise BillStatusSourceDriftError(f"expected a bold code cell under {header_line!r}: {cell!r}")
    value = match.group(1).strip()
    if not value:
        raise BillStatusSourceDriftError(f"empty code cell under {header_line!r}")
    return value


def _parse_pipe_table(lines: Sequence[str], header_line: str, column_count: int) -> list[list[str]]:
    try:
        start = lines.index(header_line)
    except ValueError as error:
        raise BillStatusSourceDriftError(f"expected section header not found: {header_line!r}") from error
    index = start + 1
    while index < len(lines) and not lines[index].strip().startswith("|"):
        if lines[index].startswith("# "):
            raise BillStatusSourceDriftError(f"no table found between {header_line!r} and the next section")
        index += 1
    if index >= len(lines):
        raise BillStatusSourceDriftError(f"no table found after {header_line!r}")
    header_row = _split_row(lines[index], header_line)
    if len(header_row) != column_count:
        raise BillStatusSourceDriftError(
            f"table under {header_line!r} has {len(header_row)} columns, expected {column_count}"
        )
    index += 1
    if index >= len(lines) or not _is_separator_row(lines[index], column_count, header_line):
        raise BillStatusSourceDriftError(f"malformed table separator under {header_line!r}")
    index += 1
    rows: list[list[str]] = []
    while index < len(lines) and lines[index].strip().startswith("|"):
        cells = _split_row(lines[index], header_line)
        if len(cells) != column_count:
            raise BillStatusSourceDriftError(
                f"table row under {header_line!r} has {len(cells)} cells, expected {column_count}: {lines[index]!r}"
            )
        rows.append(cells)
        index += 1
    if not rows:
        raise BillStatusSourceDriftError(f"table under {header_line!r} has no data rows")
    return rows


def _identifier(
    *,
    value: str,
    kind: str,
    acquired: AcquiredBillStatusSource,
) -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=kind,
        authority_uri=BILLSTATUS_IDENTIFIER_AUTHORITY_URI,
        source_uri=acquired.pin.source.source_url,
        observed_at=acquired.pin.retrieved_at,
        effective_at=None,
        source_digest=acquired.sha256,
    )


def _parse_bill_types(lines: Sequence[str], acquired: AcquiredBillStatusSource) -> tuple[BillStatusCode, ...]:
    try:
        header_index = lines.index(_HEADER_BILL_TYPE)
    except ValueError as error:
        raise BillStatusSourceDriftError(f"expected section header not found: {_HEADER_BILL_TYPE!r}") from error
    sentence: str | None = None
    for candidate in lines[header_index + 1 : header_index + 5]:
        if candidate.strip():
            sentence = candidate.strip()
            break
    if sentence is None:
        raise BillStatusSourceDriftError(f"no sentence found after {_HEADER_BILL_TYPE!r}")
    match = _BILL_TYPE_SENTENCE.fullmatch(sentence)
    if match is None:
        raise BillStatusSourceDriftError(f"bill type sentence drifted from the reviewed wording: {sentence!r}")
    codes: list[BillStatusCode] = []
    seen: set[str] = set()
    for token in re.split(r",\s*(?:and\s+)?", match.group(1)):
        code = token.strip()
        if not code:
            continue
        if _BILL_TYPE_CODE.fullmatch(code) is None:
            raise BillStatusSourceDriftError(f"malformed bill type code: {code!r}")
        if code in seen:
            raise BillStatusSourceDriftError(f"duplicate bill type code: {code!r}")
        seen.add(code)
        codes.append(
            BillStatusCode(
                resource_name="billTypes",
                use="deterministicMetadata",
                completeness="closedEnumeration",
                publisher_label=code,
                source_url=BILLSTATUS_USER_GUIDE.source_url,
                identifiers=(_identifier(value=code, kind="billTypeCode", acquired=acquired),),
            )
        )
    return tuple(codes)


def _parse_action_codes(lines: Sequence[str], acquired: AcquiredBillStatusSource) -> tuple[BillStatusCode, ...]:
    rows = _parse_pipe_table(lines, _HEADER_ACTION_CODES, 2)
    codes: list[BillStatusCode] = []
    seen: set[str] = set()
    for code_cell, label_cell in rows:
        code = _strip_bold(code_cell, _HEADER_ACTION_CODES)
        label = label_cell.strip()
        if _ACTION_CODE.fullmatch(code) is None:
            raise BillStatusSourceDriftError(f"malformed action code: {code!r}")
        if not label:
            raise BillStatusSourceDriftError(f"action code {code!r} has an empty label")
        if code in seen:
            raise BillStatusSourceDriftError(f"duplicate action code: {code!r}")
        seen.add(code)
        codes.append(
            BillStatusCode(
                resource_name="actionCodes",
                use="deterministicMetadata",
                completeness="openCourtesyList",
                publisher_label=label,
                source_url=BILLSTATUS_USER_GUIDE.source_url,
                identifiers=(_identifier(value=code, kind="actionCode", acquired=acquired),),
            )
        )
    return tuple(codes)


def _parse_summary_version_codes(
    lines: Sequence[str],
    acquired: AcquiredBillStatusSource,
) -> tuple[BillStatusCode, ...]:
    rows = _parse_pipe_table(lines, _HEADER_VERSION_CODES, 3)
    codes: list[BillStatusCode] = []
    seen: set[tuple[str, str]] = set()
    for code_cell, chamber_cell, label_cell in rows:
        code = _strip_bold(code_cell, _HEADER_VERSION_CODES)
        chamber = chamber_cell.strip()
        label = label_cell.strip()
        if _VERSION_CODE.fullmatch(code) is None:
            raise BillStatusSourceDriftError(f"malformed summary version code: {code!r}")
        if chamber not in _CHAMBERS:
            raise BillStatusSourceDriftError(f"unknown chamber value under {_HEADER_VERSION_CODES!r}: {chamber!r}")
        if not label:
            raise BillStatusSourceDriftError(f"summary version code {code!r}/{chamber} has an empty label")
        key = (code, chamber)
        if key in seen:
            raise BillStatusSourceDriftError(f"duplicate summary version code/chamber pair: {key!r}")
        seen.add(key)
        codes.append(
            BillStatusCode(
                resource_name="summaryVersionCodes",
                use="deterministicMetadata",
                completeness="closedEnumeration",
                publisher_label=label,
                source_url=BILLSTATUS_USER_GUIDE.source_url,
                identifiers=(
                    _identifier(value=code, kind="billVersionCode", acquired=acquired),
                    _identifier(value=chamber, kind=_CHAMBER_KIND, acquired=acquired),
                ),
            )
        )
    return tuple(codes)


def _resource(
    name: ResourceName,
    completeness: CompletenessStatus,
    codes: tuple[BillStatusCode, ...],
    acquired: AcquiredBillStatusSource,
) -> ParsedBillStatusResource:
    expected_count = _EXPECTED_COUNTS[name]
    if len(codes) != expected_count:
        raise BillStatusSourceDriftError(f"{name} count drift: expected {expected_count}, parsed {len(codes)}")
    return ParsedBillStatusResource(
        resource_name=name,
        use="deterministicMetadata",
        completeness=completeness,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        codes=codes,
    )


def parse_billstatus_code_sets(acquired: AcquiredBillStatusSource) -> BillStatusControlPortfolio:
    """Parse the three pinned code tables without converting them to concepts."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed BILLSTATUS source")
    lines = payload.decode("utf-8").split("\n")

    bill_types = _parse_bill_types(lines, acquired)
    action_codes = _parse_action_codes(lines, acquired)
    summary_version_codes = _parse_summary_version_codes(lines, acquired)

    return BillStatusControlPortfolio(
        bill_types=_resource("billTypes", "closedEnumeration", bill_types, acquired),
        action_codes=_resource("actionCodes", "openCourtesyList", action_codes, acquired),
        summary_version_codes=_resource("summaryVersionCodes", "closedEnumeration", summary_version_codes, acquired),
        gaps=BILLSTATUS_PORTFOLIO_GAPS,
    )


def _assignment(
    code: BillStatusCode,
    source_field: str,
    *,
    matched: bool,
    raw_value: str,
) -> BillStatusCodeAssignment:
    return BillStatusCodeAssignment(
        source_field=source_field,
        matched=matched,
        raw_value=raw_value,
        publisher_label=code.publisher_label,
        use=code.use,
        identifiers=code.identifiers,
        is_general_subject_concept=code.is_general_subject_concept,
    )


def validate_billstatus_record_codes(
    record: Mapping[str, object],
    portfolio: BillStatusControlPortfolio,
) -> ValidatedBillStatusRecord:
    """Validate one BILLSTATUS-shaped record against the exact source snapshot.

    The record's ``schema_version`` (the BILLSTATUS XML ``<version>`` value) is
    required and passed through unchanged; it is not validated against a fixed
    set because the source publishes no enumerated set for it.
    """

    raw_schema_version = record.get("schema_version")
    if not isinstance(raw_schema_version, str) or not raw_schema_version.strip():
        raise BillStatusAssignmentError("BILLSTATUS record must carry a non-empty string schema_version")

    raw_bill_type = record.get("bill_type")
    if not isinstance(raw_bill_type, str):
        raise BillStatusAssignmentError("BILLSTATUS record must carry a string bill_type")
    bill_type_code = portfolio.bill_types.by_code().get(raw_bill_type)
    if bill_type_code is None:
        raise BillStatusAssignmentError(f"unknown BILLSTATUS bill_type {raw_bill_type!r}")
    bill_type_assignment = _assignment(
        bill_type_code,
        "bill_type",
        matched=True,
        raw_value=raw_bill_type,
    )

    raw_actions = record.get("actions")
    if raw_actions is None:
        raw_actions = []
    if not isinstance(raw_actions, list):
        raise BillStatusAssignmentError("actions must be an array")
    action_lookup = portfolio.action_codes.by_code()
    action_assignments: list[BillStatusCodeAssignment] = []
    for ordinal, raw_action in enumerate(raw_actions, start=1):
        if not isinstance(raw_action, Mapping):
            raise BillStatusAssignmentError(f"action {ordinal} must be an object")
        raw_code = raw_action.get("action_code")
        if not isinstance(raw_code, str) or not raw_code.strip():
            raise BillStatusAssignmentError(f"action {ordinal} must carry a non-empty string action_code")
        source_field = f"actions[{ordinal - 1}].action_code"
        matched_code = action_lookup.get(raw_code)
        if matched_code is None:
            # The action code table is an open courtesy list; an unmatched
            # code is preserved raw, not refused, per the publisher's own
            # completeness disclaimer.
            action_assignments.append(
                BillStatusCodeAssignment(
                    source_field=source_field,
                    matched=False,
                    raw_value=raw_code,
                    publisher_label=None,
                    use="deterministicMetadata",
                    identifiers=(),
                    is_general_subject_concept=False,
                )
            )
            continue
        action_assignments.append(_assignment(matched_code, source_field, matched=True, raw_value=raw_code))

    raw_summaries = record.get("summaries")
    if raw_summaries is None:
        raw_summaries = []
    if not isinstance(raw_summaries, list):
        raise BillStatusAssignmentError("summaries must be an array")
    version_lookup = portfolio.summary_version_codes.by_code_and_chamber()
    summary_assignments: list[BillStatusCodeAssignment] = []
    for ordinal, raw_summary in enumerate(raw_summaries, start=1):
        if not isinstance(raw_summary, Mapping):
            raise BillStatusAssignmentError(f"summary {ordinal} must be an object")
        raw_code = raw_summary.get("version_code")
        raw_chamber = raw_summary.get("chamber")
        if not isinstance(raw_code, str) or not isinstance(raw_chamber, str):
            raise BillStatusAssignmentError(f"summary {ordinal} must carry string version_code and chamber")
        matched_code = version_lookup.get((raw_code, raw_chamber))
        if matched_code is None:
            raise BillStatusAssignmentError(
                f"unknown BILLSTATUS summary version_code/chamber {raw_code!r}/{raw_chamber!r}"
            )
        summary_assignments.append(
            _assignment(
                matched_code,
                f"summaries[{ordinal - 1}].version_code",
                matched=True,
                raw_value=raw_code,
            )
        )

    return ValidatedBillStatusRecord(
        schema_version=raw_schema_version,
        bill_type=bill_type_assignment,
        action_codes=tuple(action_assignments),
        summary_versions=tuple(summary_assignments),
        gaps=BILLSTATUS_PORTFOLIO_GAPS,
    )
