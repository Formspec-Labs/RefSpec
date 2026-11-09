"""The alias batch accounts for every demand key once and proposes aliases only, for the owner to decide."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas import agency_projection
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


def test_every_demand_key_is_accounted_for_once_and_only_confirmed_aliases_are_decided(report: dict[str, Any]) -> None:
    """Pin the owner's 2026-11-08 instruction: the 12 mechanical rows approved per item, every judgment row takes its recommendation once a read record confirms it."""

    keys = [row["name_key"] for row in report["aliases"]]
    keys += [row["key"] for row in (*report["already_resolvable"], *report["excluded"])]
    assert len(keys) == len(set(keys)) == 130
    assert all(row["status"] == "candidate-pending-owner-adjudication" for row in report["aliases"])
    decisions = entity_alignments.load_decisions(ROOT / aliases.DECISIONS_JSON, report)
    assert not decisions.stale
    confirmed = {row["alias_id"]: row for row in report["aliases"] if row["source_status"] == "confirmed"}
    # 12 mechanical approved per item; 58 judgment rows, 8 of them confirmed by agency records in a second reading.
    assert set(decisions.current) == set(confirmed) == {row["alias_id"] for row in report["aliases"]} and len(confirmed) == 70
    assert all(decisions.current[key]["answer"] == row["recommended"] for key, row in confirmed.items())
    assert all(row["read"] for alias in report["aliases"] for row in alias["records"])
    assert set(entity_alignments.decision_answers(report)) == {row["alias_id"] for row in report["aliases"]}


def test_a_record_is_read_only_while_its_bytes_hold_the_passage(report: dict[str, Any], tmp_path: Path) -> None:
    """Pin alias_record_is_read: a changed passage, a changed digest, or a missing file is unread."""

    (record,) = next(row for row in report["aliases"] if row["alias_id"] == "alias:general-accounting-office")["records"]
    assert entity_alignments.alias_record_is_read(record, ROOT)
    assert not entity_alignments.alias_record_is_read({**record, "passage": "The General Accounting Office is hereby abolished."}, ROOT)
    assert not entity_alignments.alias_record_is_read({**record, "sha256": "sha256:" + "0" * 64}, ROOT)
    assert not entity_alignments.alias_record_is_read(record, tmp_path)


def test_an_unread_citation_refuses_the_release(monkeypatch: pytest.MonkeyPatch, releases: tuple[Any, ...]) -> None:
    """Pin D5: the release re-reads every adopted alias's records and refuses one that is no longer read."""

    monkeypatch.setattr(entity_alignments, "alias_record_is_read", lambda record, root=ROOT: False)
    with pytest.raises(ValueError, match="cites unread records, which refuse the release"):
        entity_alignments.load_agency_registry_mapping_release(releases)


def test_undecided_aliases_are_held_and_a_rejected_alias_is_a_non_emission(releases: tuple[Any, ...]) -> None:
    """Pin what the decided aliases become; the partial rule (undecided aliases held) is pinned on a re-pinned batch below."""

    release = entity_alignments.load_agency_registry_mapping_release(releases)
    decided = {row.get("candidateId") or row.get("eventId"): row for row in release.metadata["decisions"]}
    assert decided["alias:bureau-of-land-management"]["frResource"] == "urn:ref:federal-register-agency:275"
    nfs = decided["alias:national-forest-system"]  # confirmed by the Forest Service's own organization page, not 16 U.S.C. 1609
    assert (nfs["frResource"], nfs["frRelation"]) == ("urn:ref:federal-register-agency:209", "partOf")
    assert [record["kind"] for record in nfs["records"]] == ["agencyPage"]
    army = decided["alias:army"]
    assert (army["decision"], army["frResource"], army["frRelation"]) == ("alias", "urn:ref:federal-register-agency:32", "partOf")
    assert decided["alias:labor"]["reason"] == "aliasRejectedByOwner"
    police = decided["alias:capitol-police"]
    assert "frResource" not in police and police["targetResource"] == "urn:ref:federal-hierarchy-org:500193110"


def test_name_key_drops_qualifiers_after_collapsing_punctuation() -> None:
    assert aliases.name_key is agency_projection.name_key
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
    assert set(entity_alignments.load_decisions(ROOT / aliases.DECISIONS_JSON, report).current) >= {"alias:army"}
    document["decisions"]["alias:army"]["answer"] = "yes"
    with pytest.raises(ValueError, match="not one of"):
        entity_alignments.decisions_from_json(document, report, label="test")
    document["decisions"]["alias:army"]["content_digest"] = "sha256:" + "0" * 64
    stale = entity_alignments.decisions_from_json(document, report, label="test")
    assert set(stale.stale) == {"alias:army"}
    assert "## Stale decisions" in aliases.render_adjudication_sheet(report, stale)


def test_an_undecided_alias_is_held_not_refused(releases: tuple[Any, ...]) -> None:
    """Pin the partial rule: with one decision removed, the release still builds and that alias is simply absent."""

    candidates_pin, decisions_pin = entity_alignments._AGENCY_REGISTRY_ALIAS_CANDIDATES_PIN, entity_alignments._AGENCY_REGISTRY_ALIAS_DECISIONS_PIN
    batch = entity_alignments.agency_registry_batches()[2]
    candidates = json.loads(candidates_pin.path.read_text())
    decisions = json.loads(decisions_pin.path.read_text())
    decisions["decisions"].pop("alias:army")
    outcomes = entity_alignments.agency_registry_outcomes(
        candidates, decisions, decided_digest=batch.candidates_digest, covers=batch.covers, partial=True
    )
    assert "alias:army" not in {outcome.item_id for outcome in outcomes} and len(outcomes) == 69
    with pytest.raises(ValueError, match="undecided items refuse the release: alias:army"):
        entity_alignments.agency_registry_outcomes(candidates, decisions, decided_digest=batch.candidates_digest, covers=batch.covers)
