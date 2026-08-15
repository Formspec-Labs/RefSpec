"""FCC's published Offices & Bureaus roster: pinned capture and strict parse."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import fcc_bureaus_offices as fcc

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "tests" / "fixtures" / "fcc_bureaus_offices" / "fcc-offices-bureaus-2026-08-15.html").read_bytes()


def test_roster_carries_twelve_offices_and_seven_bureaus() -> None:
    roster = fcc.parse_fcc_bureaus_offices(PAGE)

    assert roster.office_count == 12
    assert roster.bureau_count == 7
    assert len(roster.units) == 19
    assert roster.source_sha256 == fcc.FCC_OFFICES_BUREAUS_2026_08_15.expected_sha256

    assert [unit.slug for unit in roster.units if unit.kind == "bureau"] == [
        "consumer-governmental-affairs",
        "enforcement",
        "media",
        "public-safety-and-homeland-security",
        "space",
        "wireless-telecommunications",
        "wireline-competition",
    ]


def test_sample_rows_preserve_publisher_names_and_descriptions() -> None:
    roster = fcc.parse_fcc_bureaus_offices(PAGE)
    by_slug = roster.by_slug()

    space = by_slug["space"]
    assert space.kind == "bureau"
    assert space.name == "Space"
    assert space.page_url == "https://www.fcc.gov/space"
    assert space.description.startswith("The Space Bureau promotes")

    # HTML entities in the publisher's headings are decoded, not dropped.
    engineering = by_slug["engineering-technology"]
    assert engineering.kind == "office"
    assert engineering.name == "Engineering & Technology"

    judges = by_slug["administrative-law-judges"]
    assert judges.kind == "office"
    assert judges.description.startswith("The Office of Administrative Law Judges")
    assert all(unit.description for unit in roster.units)


def test_the_abolished_common_carrier_bureau_is_not_on_the_published_roster() -> None:
    # The removed observed ECFS inventory carried the abolished Common Carrier
    # Bureau beside its successor; the publisher's own roster does not list it.
    roster = fcc.parse_fcc_bureaus_offices(PAGE)

    assert not any("Common Carrier" in unit.name for unit in roster.units)
    assert "wireline-competition" in roster.by_slug()


def test_drifted_page_bytes_are_refused() -> None:
    with pytest.raises(fcc.FccSourceDriftError, match="digest drift"):
        fcc.parse_fcc_bureaus_offices(PAGE[:-1] + bytes([PAGE[-1] ^ 0x01]))
    with pytest.raises(fcc.FccSourceDriftError, match="byte length drift"):
        fcc.parse_fcc_bureaus_offices(PAGE + b" ")
