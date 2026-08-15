"""Documented Federal Register controls: pinned captures and strict parses."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import federal_register_native_controls as fr

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "federal_register_native_controls"

DOCUMENTATION = (FIXTURES / "fr-api-documentation-2026-08-15.json").read_bytes()
FACETS = (FIXTURES / "fr-documents-facets-type-2026-08-15.json").read_bytes()
AGENCIES = (FIXTURES / "fr-agencies-2026-08-15.json").read_bytes()


def _mutated(payload: bytes) -> bytes:
    """Flip one byte without changing the length."""

    return payload[:-1] + bytes([payload[-1] ^ 0x01])


def test_captures_match_their_pins() -> None:
    assert fr.verify_payload(
        DOCUMENTATION, fr.FR_API_DOCUMENTATION_2026_08_15, location="fixture"
    ) == fr.FR_API_DOCUMENTATION_2026_08_15.expected_sha256
    assert fr.verify_payload(
        FACETS, fr.FR_DOCUMENT_TYPE_FACETS_2026_08_15, location="fixture"
    ) == fr.FR_DOCUMENT_TYPE_FACETS_2026_08_15.expected_sha256
    assert fr.verify_payload(
        AGENCIES, fr.FR_AGENCIES_2026_08_15, location="fixture"
    ) == fr.FR_AGENCIES_2026_08_15.expected_sha256


def test_documented_document_types_are_the_four_published_codes() -> None:
    documented = fr.parse_documented_document_types(DOCUMENTATION, FACETS)

    assert [item.code for item in documented.types] == ["RULE", "PRORULE", "NOTICE", "PRESDOCU"]
    assert documented.by_code()["RULE"].display_name == "Rule"
    assert documented.by_code()["PRORULE"].display_name == "Proposed Rule"
    assert documented.by_code()["NOTICE"].display_name == "Notice"
    assert documented.by_code()["PRESDOCU"].display_name == "Presidential Document"
    assert documented.openapi_version == "3.0.0"
    # The publisher's own info block carries an empty version string.
    assert documented.publisher_info_version == ""
    # Facet document counts are corpus counts at capture time, retained verbatim.
    assert {item.code: item.facet_document_count_at_capture for item in documented.types} == {
        "RULE": 119_491,
        "PRORULE": 76_689,
        "NOTICE": 765_082,
        "PRESDOCU": 8_548,
    }


def test_documented_presidential_document_types_are_the_seven_published_codes() -> None:
    assert fr.parse_documented_presidential_document_types(DOCUMENTATION) == (
        "determination",
        "executive_order",
        "memorandum",
        "notice",
        "proclamation",
        "presidential_order",
        "other",
    )


def test_agencies_roster_is_complete_with_resolved_parent_relations() -> None:
    roster = fr.parse_agencies_roster(AGENCIES)

    assert len(roster.records) == 472
    assert roster.parent_relation_count == 225

    fcc = roster.by_slug()["federal-communications-commission"]
    assert fcc.agency_id == 161
    assert fcc.name == "Federal Communications Commission"
    assert fcc.short_name == "FCC"
    assert fcc.parent_id is None

    fda = roster.by_slug()["food-and-drug-administration"]
    assert fda.agency_id == 199
    assert fda.parent_id == 221
    assert roster.by_id()[221].slug == "health-and-human-services-department"

    # Publisher anomalies, verbatim counts.
    assert dict(roster.anomalies) == {
        "nullAgencyUrlCount": 67,
        "emptyAgencyUrlCount": 138,
        "nullShortNameCount": 53,
        "nullDescriptionCount": 4,
        "nullLogoCount": 263,
    }


def test_documented_agency_enum_matches_the_roster() -> None:
    roster = fr.parse_agencies_roster(AGENCIES)

    assert fr.crosscheck_documented_agency_slugs(DOCUMENTATION, roster) == 472


def test_drifted_documentation_bytes_are_refused() -> None:
    with pytest.raises(fr.FRSourceDriftError, match="digest drift"):
        fr.parse_documented_document_types(_mutated(DOCUMENTATION), FACETS)
    with pytest.raises(fr.FRSourceDriftError, match="byte length drift"):
        fr.parse_documented_presidential_document_types(DOCUMENTATION + b" ")


def test_drifted_facets_and_agencies_bytes_are_refused() -> None:
    with pytest.raises(fr.FRSourceDriftError, match="digest drift"):
        fr.parse_documented_document_types(DOCUMENTATION, _mutated(FACETS))
    with pytest.raises(fr.FRSourceDriftError, match="digest drift"):
        fr.parse_agencies_roster(_mutated(AGENCIES))
    with pytest.raises(fr.FRSourceDriftError, match="byte length drift"):
        fr.parse_agencies_roster(AGENCIES[:-1])
