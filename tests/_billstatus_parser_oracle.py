"""Frozen parser from RefSpec 5d71a26c; implementation under replacement is copied.

Only unchanged domain models, pin verification and identifier provenance are
imported. Sentence/table traversal and all parser decisions below are independent.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from refspec.registry.billstatus_codes import (
    BILLSTATUS_IDENTIFIER_AUTHORITY_URI,
    BILLSTATUS_PORTFOLIO_GAPS,
    BILLSTATUS_USER_GUIDE,
    AcquiredBillStatusSource,
    BillStatusCode,
    BillStatusControlPortfolio,
    BillStatusSourceDriftError,
    CompletenessStatus,
    ParsedBillStatusResource,
    ResourceName,
    _verify_payload,
)
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier

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

_CHAMBER_KIND = "billVersionChamber"

_EXPECTED_COUNTS: dict[ResourceName, int] = {
    "billTypes": 8,
    "actionCodes": 36,
    "summaryVersionCodes": 88,
}

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
