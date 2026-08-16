"""Offline pin and shape tests for the complete eCFR agency roster."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from refspec.registry import cfr_list_of_subjects as cfr

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/cfr_list_of_subjects/ecfr-agencies-2026-08-15.json"


def test_pinned_ecfr_agency_roster_preserves_all_publishers_references() -> None:
    payload = FIXTURE.read_bytes()
    roster = cfr.parse_ecfr_agency_roster(payload)

    assert len(payload) == 98_197
    assert cfr.sha256_digest(payload) == ("sha256:766685f466d62fa558a504cdeac23eef1d41f3ea24a2f5a3f78b38f2bcd5365e")
    assert roster.source_url == "https://www.ecfr.gov/api/admin/v1/agencies.json"
    assert roster.retrieved_at == "2026-08-15T22:51:57Z"
    assert roster.top_level_agency_count == 153
    assert len(roster.records) == 316
    assert roster.reference_count == 487
    assert roster.referenced_agency_count == 315
    assert roster.referenced_title_count == 49

    by_slug = roster.by_slug()
    agriculture = by_slug["agriculture-department"]
    assert len(agriculture.child_slugs) == 28
    ams = by_slug["agricultural-marketing-service"]
    assert ams.parent_slug == agriculture.slug
    assert ams.references[0].raw == {"title": 7, "chapter": "I"}
    assert ams.references[-1].raw == {"title": 9, "chapter": "II"}


def test_ecfr_agency_capture_records_rights_and_unversioned_source() -> None:
    pin = cfr.ECFR_AGENCIES_2026_08_15

    assert pin.license_rights_statement == ("US federal public domain (17 USC 105) with no explicit CC license")
    assert "rolling, unversioned endpoint" in pin.source_version_note
    assert pin.source_url == cfr.ECFR_AGENCIES_URL


def test_ecfr_agency_reader_refuses_length_and_digest_drift() -> None:
    payload = FIXTURE.read_bytes()

    with pytest.raises(cfr.CFRSourceDriftError, match="byte length drift"):
        cfr.parse_ecfr_agency_roster(payload[:-1])

    mutated = payload.replace(b"Administrative Conference", b"Xdministrative Conference", 1)
    assert len(mutated) == len(payload)
    with pytest.raises(cfr.CFRSourceDriftError, match="digest drift"):
        cfr.parse_ecfr_agency_roster(mutated)


def test_ecfr_agency_reader_refuses_shape_drift_after_repinning() -> None:
    value = json.loads(FIXTURE.read_bytes())
    del value["agencies"][0]["sortable_name"]
    mutated = json.dumps(value, separators=(",", ":")).encode("utf-8")
    pin = dataclasses.replace(
        cfr.ECFR_AGENCIES_2026_08_15,
        expected_sha256=cfr.sha256_digest(mutated),
        expected_byte_length=len(mutated),
    )

    with pytest.raises(cfr.CFRSourceDriftError, match="fields drifted"):
        cfr.parse_ecfr_agency_roster(mutated, pin=pin)
