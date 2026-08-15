"""FAST Book workbook Intro-sheet fund-group parser coverage.

The fund groups are parsed from the exact pinned workbook bytes -- the same
capture the account release reads -- never transcribed from another page.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import treasury_tas_fast_book as treasury

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_PATH = ROOT / "tests/fixtures/treasury_tas_fast_book/fast-book-part-ii-iii-2026-07-31.xlsx"


def test_intro_sheets_state_eight_part_ii_groups_and_foreign_currency() -> None:
    parsed = treasury.parse_fast_book_fund_groups(
        WORKBOOK_PATH,
        pin=treasury.FAST_BOOK_PART_II_III_2026_07_31,
    )

    # The heading's presence, the 8-row Part II count, and the digest match
    # are parser guards (they refuse inside parse_fast_book_fund_groups);
    # this test owns the parsed content.
    assert parsed.edition == "2026-07"
    assert parsed.workbook_modified_at == "2026-07-30T19:11:58"

    assert [
        (group.part, group.name, group.symbol_range_text) for group in parsed.groups
    ] == [
        ("II", "General Fund", "0000-3899"),
        ("II", "Management and Consolidated Working Funds", "3900-3999"),
        ("II", "Public Enterprise Revolving Fund", "4000-4499"),
        ("II", "Intra-Governmental Revolving Fund", "4500-4999"),
        ("II", "Special Fund", "5000-5999"),
        ("II", "Deposit Fund", "6000-6999"),
        ("II", "Trust Revolving Fund", "8400-8499"),
        ("II", "Trust Non-Revolving Fund", "8000-8399 and 8500-8999"),
        ("III", "Foreign Currency Expenditure (No associated receipts)", "7000-7999"),
    ]

    by_name = {group.name: group for group in parsed.groups}
    # The publisher states one split range: it stays one group with two
    # contiguous ranges, stripped of surrounding whitespace, otherwise
    # verbatim (the General Fund cell reads '0000-3899 ' with a trailing
    # space in the pinned workbook).
    split = by_name["Trust Non-Revolving Fund"]
    assert [(r.first_symbol, r.last_symbol) for r in split.symbol_ranges] == [
        ("8000", "8399"),
        ("8500", "8999"),
    ]
    assert all(
        len(group.symbol_ranges) == 1 for group in parsed.groups if group.name != "Trust Non-Revolving Fund"
    )
    # Sheet provenance: the eight Part II rows sit directly under the heading.
    assert [group.row_number for group in parsed.groups if group.part == "II"] == list(range(7, 15))


def test_fund_groups_are_parsed_not_transcribed() -> None:
    # PART_FUND_GROUPS remains the hand transcription of the Description of
    # Contents *page*, whose Part II phrasing is coarser (five groups, no
    # symbol ranges). The parsed sheet is a different publisher statement
    # and must not be reconciled by extending the transcription.
    assert treasury.PART_FUND_GROUPS["II"] == ("general", "revolving", "special", "deposit", "trust")
    assert treasury.PART_FUND_GROUPS["III"] == ("foreignCurrency",)

    parsed = treasury.parse_fast_book_fund_groups(
        WORKBOOK_PATH,
        pin=treasury.FAST_BOOK_PART_II_III_2026_07_31,
    )
    sheet_names = {group.name for group in parsed.groups}
    assert len(sheet_names) == 9


def test_fund_group_parsing_fails_closed_on_drift(tmp_path: Path) -> None:
    payload = bytearray(WORKBOOK_PATH.read_bytes())
    payload[-1] ^= 0xFF
    tampered = tmp_path / "fast-book-tampered.xlsx"
    tampered.write_bytes(bytes(payload))
    with pytest.raises(treasury.TreasurySourceDriftError, match="digest drift"):
        treasury.parse_fast_book_fund_groups(
            tampered,
            pin=treasury.FAST_BOOK_PART_II_III_2026_07_31,
        )

    with pytest.raises(treasury.TreasuryAcquisitionError, match="not a regular file"):
        treasury.parse_fast_book_fund_groups(
            tmp_path / "missing.xlsx",
            pin=treasury.FAST_BOOK_PART_II_III_2026_07_31,
        )


def test_fund_group_range_and_row_shapes_fail_closed() -> None:
    with pytest.raises(treasury.TreasurySourceDriftError, match="unexpected shape"):
        treasury._parse_fund_group_ranges("0000-38", sheet="Intro Part II", row_number=7)
    with pytest.raises(treasury.TreasurySourceDriftError, match="unexpected shape"):
        treasury._parse_fund_group_ranges("0000-3899 or 4000-4499", sheet="Intro Part II", row_number=7)
    with pytest.raises(treasury.TreasurySourceDriftError, match="must not be inverted"):
        treasury.FASTBookFundGroupRange(first_symbol="3899", last_symbol="0000")
    with pytest.raises(treasury.TreasurySourceDriftError, match="at least one symbol range"):
        treasury.FASTBookFundGroup(
            part="II",
            sheet="Intro Part II",
            row_number=7,
            name="General Fund",
            symbol_range_text="0000-3899",
            symbol_ranges=(),
        )
