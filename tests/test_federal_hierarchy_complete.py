"""The complete Federal Hierarchy roster: pinned pages, totals, anomalies."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import federal_hierarchy_complete as fh

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "federal_hierarchy_complete"

PAGES = tuple((FIXTURES / f"fh-orgs-all-page-{index}.json").read_bytes() for index in range(5))
DEPT_WITNESS = (FIXTURES / "fh-orgs-total-dept.json").read_bytes()
SUB_TIER_WITNESS = (FIXTURES / "fh-orgs-total-subtier.json").read_bytes()


def _roster() -> fh.FederalHierarchyCompleteRoster:
    return fh.parse_complete_roster(PAGES, DEPT_WITNESS, SUB_TIER_WITNESS)


def test_roster_is_complete_against_the_apis_own_totals() -> None:
    roster = _roster()

    assert roster.total_records_reported == 907
    assert len(roster.records) == 907
    assert roster.department_count == 169
    assert roster.sub_tier_count == 738
    # The two filtered one-record responses witness the API's per-level totals.
    assert roster.dept_witness_total == 169
    assert roster.sub_tier_witness_total == 738
    assert len(roster.by_org_id()) == 907


def test_every_sub_tier_parent_resolves_and_departments_self_parent() -> None:
    roster = _roster()
    by_id = roster.by_org_id()

    for record in roster.records:
        if record.org_type == "Department/Ind. Agency":
            assert record.parent_fhorgid == record.fhorgid
        else:
            assert by_id[record.parent_fhorgid].org_type == "Department/Ind. Agency"


def test_sample_rows_preserve_publisher_identifiers() -> None:
    roster = _roster()
    dod = roster.by_org_id()["100000000"]

    assert dod.name == "DEPT OF DEFENSE"
    assert dod.org_type == "Department/Ind. Agency"
    assert dod.agency_code == "9700"
    # The publisher documents single-CGAC support and publishes five.
    assert dod.cgac_codes == ("097", "096", "017", "021", "057")


def test_publisher_anomalies_are_recorded_verbatim() -> None:
    roster = _roster()
    anomalies = dict(roster.anomalies)

    assert anomalies["multiCgacRecords"] == [
        {
            "fhorgid": "100000000",
            "fhorgname": "DEPT OF DEFENSE",
            "cgacCodes": ["097", "096", "017", "021", "057"],
        }
    ]
    # The live public roster carries a record the publisher named Testing DEPT,
    # with an empty agencycode and a null CGAC entry.
    assert anomalies["emptyAgencyCodeRecords"] == [
        {"fhorgid": "500021729", "fhorgname": "Testing DEPT"}
    ]
    assert [entry["fhorgid"] for entry in anomalies["nullCgacEntryRecords"]] == [
        "300000746",
        "500021729",
        "300000919",
    ]
    assert len(anomalies["recordsWithoutParentHistory"]) == 11


def test_drifted_page_bytes_are_refused() -> None:
    mutated = list(PAGES)
    mutated[2] = mutated[2][:-1] + bytes([mutated[2][-1] ^ 0x01])
    with pytest.raises(fh.FHCompleteSourceDriftError, match="digest drift"):
        fh.parse_complete_roster(mutated, DEPT_WITNESS, SUB_TIER_WITNESS)

    truncated = list(PAGES)
    truncated[0] = truncated[0][:-1]
    with pytest.raises(fh.FHCompleteSourceDriftError, match="byte length drift"):
        fh.parse_complete_roster(truncated, DEPT_WITNESS, SUB_TIER_WITNESS)


def test_swapped_or_missing_witnesses_are_refused() -> None:
    with pytest.raises(fh.FHCompleteSourceDriftError):
        fh.parse_complete_roster(PAGES, SUB_TIER_WITNESS, DEPT_WITNESS)
    with pytest.raises(fh.FHCompleteSourceDriftError, match="pinned pages"):
        fh.parse_complete_roster(PAGES[:4], DEPT_WITNESS, SUB_TIER_WITNESS)


def test_source_urls_are_credential_free() -> None:
    for pin in (
        *fh.FH_COMPLETE_PAGES_2026_08_15,
        fh.FH_TOTAL_DEPT_WITNESS_2026_08_15,
        fh.FH_TOTAL_SUBTIER_WITNESS_2026_08_15,
    ):
        assert "api_key" not in pin.source_url
    for payload in (*PAGES, DEPT_WITNESS, SUB_TIER_WITNESS):
        assert b"api_key" not in payload
