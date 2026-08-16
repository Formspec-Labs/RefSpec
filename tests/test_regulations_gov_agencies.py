"""Pinned capture and fail-closed parse checks for regulations.gov agencies."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from refspec.registry import regulations_gov_agencies as regs

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "regulations_gov_agencies"
    / "regulations-gov-agencies-2026-08-16.json"
)
PAYLOAD = FIXTURE.read_bytes()


def _repin(payload: bytes) -> regs.RegulationsGovAgenciesSnapshotPin:
    return dataclasses.replace(
        regs.REGULATIONS_GOV_AGENCIES_2026_08_16,
        expected_sha256=regs.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def _encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def test_capture_matches_its_pin_and_has_no_credential_surface() -> None:
    assert regs.verify_payload(PAYLOAD) == regs.REGULATIONS_GOV_AGENCIES_2026_08_16.expected_sha256
    assert regs.REGULATIONS_GOV_AGENCIES_2026_08_16.expected_byte_length == 91_408
    assert regs.REGULATIONS_GOV_AGENCIES_2026_08_16.expected_record_count == 331
    assert regs.REGULATIONS_GOV_AGENCIES_URL == "https://api.regulations.gov/v4/agencies"
    assert regs.REGULATIONS_GOV_API_KEY_ENV_VAR == "REGULATIONS_GOV_API_KEY"
    assert regs.REGULATIONS_GOV_API_KEY_HEADER == "X-Api-Key"
    assert "key" not in regs.REGULATIONS_GOV_AGENCIES_2026_08_16.source_url.lower()


def test_roster_preserves_all_fields_and_parent_relations() -> None:
    roster = regs.parse_regulations_gov_agencies(PAYLOAD)

    assert len(roster.records) == 331
    assert roster.parent_relation_count == 160
    assert roster.distinct_parent_count == 17
    assert roster.source_byte_length == 91_408
    assert roster.source_sha256 == (
        "sha256:28ab9f5422dd27fc7906ddc696e8e7811b11056822f370bcee7ea18a28418fa2"
    )

    abmc = roster.by_id()["ABMC"]
    assert abmc.name == "American Battle Monuments Commission"
    assert abmc.parent is None
    assert abmc.participate is False
    assert abmc.partner is False
    assert abmc.posting_guidelines is None
    assert abmc.agency_type == "Federal"
    assert abmc.self_link == "https://api.regulations.gov/v4/agencies/ABMC"
    assert abmc.raw == json.loads(PAYLOAD)["data"][0]

    whd = roster.by_id()["WHD"]
    assert whd.parent == "DOL"
    assert whd.posting_guidelines is not None
    assert whd.posting_guidelines.startswith("All comments received will be posted without change")


def test_digest_and_length_drift_are_refused() -> None:
    mutated = PAYLOAD[:-1] + bytes([PAYLOAD[-1] ^ 0x01])
    with pytest.raises(regs.RegulationsGovAgenciesSourceDriftError, match="digest drift"):
        regs.parse_regulations_gov_agencies(mutated)
    with pytest.raises(regs.RegulationsGovAgenciesSourceDriftError, match="byte length drift"):
        regs.parse_regulations_gov_agencies(PAYLOAD + b" ")


@pytest.mark.parametrize("mutation", ["gain", "loss"])
def test_attribute_field_census_refuses_gains_and_losses(mutation: str) -> None:
    root = json.loads(PAYLOAD)
    attributes = root["data"][0]["attributes"]
    if mutation == "gain":
        attributes["newPublisherField"] = "drift"
    else:
        del attributes["partner"]
    payload = _encoded(root)

    with pytest.raises(
        regs.RegulationsGovAgenciesSourceDriftError,
        match=r"data\[0\]\.attributes fields drifted",
    ):
        regs.parse_regulations_gov_agencies(payload, pin=_repin(payload))


def test_record_count_is_pinned_at_331_even_when_bytes_are_repinned() -> None:
    root = json.loads(PAYLOAD)
    root["data"].pop()
    payload = _encoded(root)

    with pytest.raises(regs.RegulationsGovAgenciesSourceDriftError, match="record count drift"):
        regs.parse_regulations_gov_agencies(payload, pin=_repin(payload))


def test_duplicate_json_fields_are_refused_even_when_bytes_are_repinned() -> None:
    payload = PAYLOAD.replace(
        b'"id":"ABMC"',
        b'"id":"ABMC","id":"ABMC"',
        1,
    )

    with pytest.raises(regs.RegulationsGovAgenciesSourceDriftError, match="repeats JSON field"):
        regs.parse_regulations_gov_agencies(payload, pin=_repin(payload))


def test_pin_refuses_api_keys_in_the_url() -> None:
    with pytest.raises(regs.RegulationsGovAgenciesError, match="query or fragment"):
        dataclasses.replace(
            regs.REGULATIONS_GOV_AGENCIES_2026_08_16,
            source_url="https://api.regulations.gov/v4/agencies?unexpected=value",
        )
