"""The alias batch accounts for every demand key once and proposes aliases only, for the owner to decide."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas import v3_registry_alignments_entity as entity_alignments
from tools import analyze_agency_roster_identifiers as census
from tools import assemble_agency_registry_alias_batch as aliases

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def releases() -> tuple[Any, ...]:
    return census.load_five_agency_rosters(ROOT)


@pytest.fixture(scope="module")
def report(releases: tuple[Any, ...]) -> dict[str, Any]:
    return aliases.assemble(ROOT, releases)


def test_committed_artifacts_follow_from_the_rosters_evidence_and_decisions(releases: tuple[Any, ...]) -> None:
    assert aliases.write_or_check(ROOT, write=False, releases=releases) == []


def test_every_demand_key_is_accounted_for_once_and_nothing_is_decided(report: dict[str, Any]) -> None:
    keys = [row["name_key"] for row in report["aliases"]]
    keys += [row["key"] for row in (*report["already_resolvable"], *report["excluded"])]
    assert len(keys) == len(set(keys)) == 130
    assert all(row["status"] == "candidate-pending-owner-adjudication" for row in report["aliases"])
    decisions = entity_alignments.load_decisions(ROOT / aliases.DECISIONS_JSON, report)
    assert not decisions.current and not decisions.stale
    assert set(entity_alignments.decision_answers(report)) == {row["alias_id"] for row in report["aliases"]}


def test_name_key_drops_qualifiers_after_collapsing_punctuation() -> None:
    assert aliases.name_key("U. S. Fish & Wildlife Service") == "fish and wildlife service"
    assert aliases.name_key("The Office of the Director of National Intelligence (ODNI)") == "office of director of national intelligence"
    assert aliases.word_order_key("Land Management Bureau") == "bureau of land management"
    assert aliases.word_order_key("Federal Reserve System") is None


def test_mechanical_rows_need_exactly_one_fr_record(report: dict[str, Any]) -> None:
    mechanical = {row["name_key"]: row for row in report["aliases"] if row["class"] == "mechanical"}
    assert mechanical["bureau of land management"]["fr"] == 275
    assert mechanical["bureau of land management"]["basis"] == ["frNameWordOrder", "reviewedIdentityPublisherName"]
    # "NCTC" is FR 334's short name (the Counterintelligence Center); the Counterterrorism Center is judged, part of ODNI.
    nctc = next(row for row in report["aliases"] if row["name_key"] == "national counterterrorism center")
    assert (nctc["class"], nctc["fr"], nctc["fr_relation"]) == ("judgment", 354, "partOf")


def test_hand_entries_are_refused_when_stale_doubled_or_missing(monkeypatch: pytest.MonkeyPatch, releases: tuple[Any, ...]) -> None:
    army = next(row for row in aliases.JUDGMENT if row.key == "army")
    monkeypatch.setattr(aliases, "JUDGMENT", (*aliases.JUDGMENT, dataclasses.replace(army, key="bureau of land management")))
    with pytest.raises(ValueError, match="is mechanical"):
        aliases.assemble(ROOT, releases)
    monkeypatch.setattr(aliases, "JUDGMENT", (*aliases.JUDGMENT[:-1], dataclasses.replace(army, key="no such key")))
    with pytest.raises(ValueError, match="not a demand key"):
        aliases.assemble(ROOT, releases)
    monkeypatch.setattr(aliases, "JUDGMENT", tuple(row for row in aliases.JUDGMENT[:-1] if row.key != "army"))
    with pytest.raises(ValueError, match="'army' is unaccounted"):
        aliases.assemble(ROOT, releases)


def test_a_decision_binds_to_its_alias_and_stales_when_it_changes(report: dict[str, Any]) -> None:
    row = next(row for row in report["aliases"] if row["alias_id"] == "alias:army")
    document = {
        "schema_version": entity_alignments.DECISIONS_SCHEMA_VERSION,
        "reviewer_iri": "urn:ref:reviewer:refspec-owner",
        "decisions": {"alias:army": {"answer": "2", "decided_on": "2026-11-09", "content_digest": row["content_digest"], "channel": "questionTool"}},
    }
    assert set(entity_alignments.decisions_from_json(document, report, label="test").current) == {"alias:army"}
    document["decisions"]["alias:army"]["answer"] = "yes"
    with pytest.raises(ValueError, match="not one of"):
        entity_alignments.decisions_from_json(document, report, label="test")
    document["decisions"]["alias:army"]["content_digest"] = "sha256:" + "0" * 64
    stale = entity_alignments.decisions_from_json(document, report, label="test")
    assert set(stale.stale) == {"alias:army"}
    assert "## Stale decisions" in aliases.render_adjudication_sheet(report, stale)
