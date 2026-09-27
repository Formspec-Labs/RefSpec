"""The batch-1 agency-registry assembler proposes candidates only, in REF-038's shape, reproducibly.

The committed plans/ artifacts are checked the way CI can (``check_committed``:
rosters, pins, decisions and rendering, no replay), and a synthetic replay with a
synthetic rule-effects file exercises the measured block, the generated
adjudication sheet, the stale-measurement guard, decision persistence, and
``--check``'s drift detection.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import pytest

from refspec.atlas import v3_registry_alignments_entity as entity_alignments
from tools import analyze_agency_roster_identifiers as census
from tools import assemble_agency_registry_batch_1 as batch1

ROOT = Path(__file__).resolve().parents[1]
# Anything that would make a row an adjudicated assertion rather than a candidate.
ADJUDICATION_KEYS = {"reviewerIri", "reviewer", "evidenceTier", "evidence_tier", "decidedAt", "adjudicated_on", "warrant"}
NO_CHANGE = {
    "fr_rows_gained": 0,
    "fr_rows_lost": 0,
    "fr_rows_changed": 0,
    "docketless_gained": 0,
    "docketless_lost": 0,
    "docketless_changed": 0,
    "fr_rows_rerouted": {},
    "docketless_rerouted": {},
}


@pytest.fixture(scope="module")
def releases() -> tuple[Any, ...]:
    return census.load_five_agency_rosters(ROOT)


@pytest.fixture(scope="module")
def assembled(releases: tuple[Any, ...]) -> dict[str, Any]:
    return batch1.assemble_candidates(releases)


@pytest.fixture(autouse=True)
def _load_rosters_once(monkeypatch: pytest.MonkeyPatch, releases: tuple[Any, ...]) -> None:
    # Every assemble_report/check_committed call would otherwise re-read the five pinned rosters.
    monkeypatch.setattr(batch1.census, "load_five_agency_rosters", lambda _root: releases)


def _walk(value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_committed_artifacts_pass_the_ci_check() -> None:
    assert batch1.check_committed(ROOT) == []


def test_committed_candidates_match_the_rosters(assembled: dict[str, Any]) -> None:
    committed = json.loads((ROOT / batch1.REPORT_JSON).read_text())
    assert committed["candidates_digest"] == batch1.candidates_digest(assembled)
    assert committed["candidates_digest_covers"] == list(batch1.CANDIDATES_DIGEST_COVERS)
    for key in batch1.CANDIDATES_DIGEST_COVERS:
        assert committed[key] == assembled[key]


def test_nothing_is_adjudicated(assembled: dict[str, Any]) -> None:
    for key in batch1.CANDIDATES_DIGEST_COVERS:
        for row in assembled[key]:
            assert row["status"] == batch1.CANDIDATE_STATUS
        keys = {name for name, _ in _walk(assembled[key])}
        assert not keys & ADJUDICATION_KEYS
        assert all(value != "adopted" for name, value in _walk(assembled[key]) if name.startswith("decision"))


def test_bridges_carry_the_ref038_assertion_shape(assembled: dict[str, Any], releases: tuple[Any, ...]) -> None:
    rosters = batch1._rosters(releases)
    bridges = [row for row in assembled["candidates"] if row["relation"] == "sameEntityAs"]
    assert len(bridges) == 15
    for row in bridges:
        if row["proposed_basis"] is None:
            assert row["proposed_hold"] and row["owner_question"]
            assert row["alternative_basis"] in entity_alignments.AGENCY_DECISION_BASES
        else:
            assert row["proposed_basis"] in entity_alignments.AGENCY_DECISION_BASES
        for side in ("source", "target"):
            record = row[side]
            roster = rosters[record["release_key"]]
            field, name = entity_alignments.publisher_name(record["release_key"], roster.resources[record["resource_iri"]])
            assert (record["name_field"], record["publisher_name"]) == (field, name)
            assert "parent" in record
            assert name in row["reasoning"]
    by_id = {row["candidate_id"]: row for row in bridges}
    # The sealed eCFR `name`, not the display name the first round used.
    assert by_id["same:fr118:ecfr:economic-analysis-bureau"]["target"]["publisher_name"] == "Bureau of Economic Analysis"
    assert by_id["same:fr88:ecfr:copyright-royalty-board"]["proposed_basis"] == "exactPublisherNameEquality"
    assert by_id["same:fr151:ecfr:export-import-bank"]["codes_selecting_fr_id_after_bridge"] == ["EIB", "USEIB"]
    assert by_id["same:fr296:fh:300000070"]["proposed_basis"] is None


def test_ids_are_content_derived_and_successions_are_events(assembled: dict[str, Any]) -> None:
    rows = assembled["candidates"]
    token = {
        batch1.FR: lambda r: f"fr{r['id']}",
        batch1.ECFR: lambda r: f"ecfr:{r['slug']}",
        batch1.FH: lambda r: f"fh:{r['id']}",
    }
    for row in rows:
        source, target = row["source"], row["target"]
        prefix = "same" if row["relation"] == "sameEntityAs" else "succ"
        assert row["candidate_id"] == f"{prefix}:{token[source['release_key']](source)}:{token[target['release_key']](target)}"
    events = {event["event_id"]: event for event in assembled["events"]}
    for event_id, event in events.items():
        members = [row for row in rows if row.get("event_id") == event_id]
        assert [row["candidate_id"] for row in members] == event["rows"]
        originals = {original["id"] for original in event["originals"]}
        assert not originals & {row["target"]["id"] for row in members}
        assert (event["group"] == "D") == (len(members) > 1)
        if len(members) > 1:
            assert all(row["functions_taken"] for row in members)
    assert events["event:fr510"]["rows"] == ["succ:fr510:fr41", "succ:fr510:fr476"]
    assert [row["candidate_id"] for row in assembled["non_emissions"]] == [
        "same:fr255:ecfr:international-boundary-and-water-commission-united-states-and-mexico"
    ]
    assert set(assembled["previous_round_ids"]) == {f"batch1-{n:03d}" for n in range(1, 30)}


def test_event_ids_run_over_sorted_originals_and_stay_stable(releases: tuple[Any, ...]) -> None:
    rosters = batch1._rosters(releases)
    fr = rosters[batch1.FR]
    single = batch1.SUCCESSION_EVENTS[0]
    rows_before, events_before = batch1._succession_candidates(rosters)
    # A merger (the later batch's PPRC + ProPAC into MedPAC), written in either order.
    merger = batch1.SuccessionEvent(
        (440, 407),
        "1997-08-05",
        "test",
        (
            batch1.SuccessorRow(284, "ProPAC's duties", (), "test", single.rows[0].rejected, original_fr_id=440),
            batch1.SuccessorRow(284, "PPRC's duties", (), "test", single.rows[0].rejected, original_fr_id=407),
        ),
    )
    assert batch1.event_id(fr, (440, 407)) == batch1.event_id(fr, (407, 440)) == "event:fr407+fr440"
    assert batch1.event_id(fr, single.originals) == f"event:fr{single.originals[0]}"
    rows_after, events_after = batch1._succession_candidates(rosters, (*batch1.SUCCESSION_EVENTS, merger))
    new = [event for event in events_after if event["event_id"] == "event:fr407+fr440"]
    assert [event["rows"] for event in new] == [["succ:fr407:fr284", "succ:fr440:fr284"]]
    # Adding an event moves no existing id.
    assert [e["event_id"] for e in events_after if e["event_id"] != "event:fr407+fr440"] == [
        e["event_id"] for e in events_before
    ]
    assert {row["candidate_id"] for row in rows_before} <= {row["candidate_id"] for row in rows_after}
    with pytest.raises(ValueError, match="names no original"):
        batch1._succession_candidates(rosters, (dataclasses.replace(merger, rows=(merger.rows[0], dataclasses.replace(merger.rows[1], original_fr_id=None))),))


def _replay(root: Path, name: str = "replay", extra: str = "") -> Path:
    replay = root / name
    replay.mkdir()
    duckdb.connect().execute(
        "copy (select * from (values "
        "('A-1', '1999-01-04', '[{\"id\": 559, \"parent_id\": 221}]'), "
        "('A-2', '2002-01-07', '[{\"id\": 559, \"raw_name\": \"HCFA\"}, {\"id\": 45, \"parent_id\": 221}]'), "
        f"('A-3', '2003-05-01', '[{{\"id\": 136}}, {{\"id\": null}}]'){extra}"
        ") t(document_number, publication_date, agencies_json)) "
        f"to '{replay / batch1.FR_PARQUET}' (format parquet)"
    )
    return replay


def _effects(root: Path, assembled: dict[str, Any], replay_sha256: str, **overrides: Any) -> Path:
    keys = [row["candidate_id"] for row in assembled["candidates"] if row["relation"] == "sameEntityAs"]
    keys += [event["event_id"] for event in assembled["events"]]
    data = {
        "rule": "spicy_regs.ontology.agencies.agency_code_for_fr_agencies",
        "spicy_regs_commit": batch1.SPICY_REGS_COMMIT,
        "vendored_projection_sha256": batch1.SPICY_REGS_VENDORED_PROJECTION_SHA256,
        "spicy_regs_agencies_module_sha256": batch1.SPICY_REGS_AGENCIES_MODULE_SHA256,
        "measurement_script_sha256": batch1.MEASUREMENT_SCRIPT_SHA256,
        "replay": {"federal_register_sha256": replay_sha256, "proceedings_sha256": "sha256:" + "0" * 64},
        "refspec_candidates_digest": batch1.candidates_digest(assembled),
        "baseline": {},
        "all_batch1_adopted": {},
        "effects": {key: {"alone": NO_CHANGE, "on_top": NO_CHANGE} for key in keys},
        "split_variants": {
            event["event_id"]: dict.fromkeys(event["rows"], NO_CHANGE)
            for event in assembled["events"]
            if len(event["rows"]) > 1
        },
        "withdrawn_reference": {},
        **overrides,
    }
    data = {key: value for key, value in data.items() if value is not None}
    path = root / "effects.json"
    path.write_text(json.dumps(data))
    return path


def _decisions(root: Path, decisions: dict[str, Any]) -> Path:
    path = root / batch1.DECISIONS_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": batch1.DECISIONS_SCHEMA_VERSION,
                "reviewer_iri": batch1.OWNER_REVIEWER_IRI,
                "decisions": decisions,
            }
        )
    )
    return path


def test_replay_counts_and_rule_effects_stay_beside_the_candidates(tmp_path: Path, assembled: dict[str, Any]) -> None:
    replay = _replay(tmp_path)
    replay_sha256 = batch1._file_digest(replay / batch1.FR_PARQUET)
    report = batch1.assemble_report(ROOT, replay, _effects(tmp_path, assembled, replay_sha256))
    measured = report["measured"]
    assert report["candidates_digest"] == batch1.candidates_digest(assembled)
    assert measured["per_fr_id"]["559"] == {
        "mentions": 2,
        "documents": 2,
        "first_published": "1999-01-04",
        "last_published": "2002-01-07",
    }
    assert measured["event_periods"]["event:fr559"] == {
        "originals_on_or_after": {
            "559": [{"heading": "HCFA", "mentions": 1, "first_published": "2002-01-07", "last_published": "2002-01-07"}]
        },
        "results_before": {"45": []},
    }
    assert (measured["rows_today"], measured["rows_after_bridges"]) == (2, 1)
    assert report["inputs"]["replay"]["federal_register"]["row_count"] == 3
    assert str(tmp_path) not in json.dumps(report)

    sheet = batch1.render_adjudication_sheet(report)
    for row in assembled["candidates"]:
        if row["relation"] == "sameEntityAs":
            assert f"`{row['candidate_id']}`" in sheet
    for event in assembled["events"]:
        assert f"`{event['event_id']}`" in sheet
    assert report["candidates_digest"] in sheet
    assert "not measured" not in sheet

    assert batch1.write_or_check(tmp_path, report, batch1.NO_DECISIONS, write=True) == []
    assert batch1.write_or_check(tmp_path, report, batch1.NO_DECISIONS, write=False) == []
    target = tmp_path / batch1.ADJUDICATION_MARKDOWN
    target.write_text(target.read_text().replace("wrong-date", "wrong-day", 1))
    assert batch1.write_or_check(tmp_path, report, batch1.NO_DECISIONS, write=False) == [
        f"drifted: {batch1.ADJUDICATION_MARKDOWN}"
    ]


def test_a_stale_rule_measurement_is_refused(tmp_path: Path, assembled: dict[str, Any]) -> None:
    replay = _replay(tmp_path)
    replay_sha256 = batch1._file_digest(replay / batch1.FR_PARQUET)
    stale = _effects(tmp_path, assembled, replay_sha256, refspec_candidates_digest="sha256:" + "1" * 64)
    with pytest.raises(ValueError, match="another candidate set"):
        batch1.assemble_report(ROOT, replay, stale)
    other_replay = _effects(tmp_path, assembled, "sha256:" + "2" * 64)
    with pytest.raises(ValueError, match="another replay"):
        batch1.assemble_report(ROOT, replay, other_replay)
    unpinned = _effects(tmp_path, assembled, replay_sha256, spicy_regs_commit=None)
    with pytest.raises(ValueError, match="do not record spicy_regs_commit"):
        batch1.assemble_report(ROOT, replay, unpinned)
    other_commit = _effects(tmp_path, assembled, replay_sha256, spicy_regs_commit="1" * 40)
    with pytest.raises(ValueError, match="the design cites"):
        batch1.assemble_report(ROOT, replay, other_commit)


def _decision(digests: dict[str, str], key: str, answer: str, **extra: str) -> dict[str, str]:
    return {"answer": answer, "decided_on": "2026-10-01", "content_digest": digests[key], "channel": "decisionsFile", **extra}


def test_a_filled_decision_survives_a_write_after_the_replay_changes(tmp_path: Path, assembled: dict[str, Any]) -> None:
    key = "same:fr136:ecfr:energy-department"
    decisions_path = _decisions(tmp_path, {key: _decision(batch1.decision_digests(assembled), key, "yes")})
    before = decisions_path.read_bytes()
    for name, extra in (("replay-a", ""), ("replay-b", ", ('A-4', '2004-01-02', '[{\"id\": 136}]')")):
        replay = _replay(tmp_path, name, extra)
        report = batch1.assemble_report(
            ROOT, replay, _effects(tmp_path, assembled, batch1._file_digest(replay / batch1.FR_PARQUET))
        )
        decisions = batch1.load_decisions(decisions_path, report)
        assert set(decisions.current) == {key} and not decisions.stale
        assert batch1.write_or_check(tmp_path, report, decisions, write=True) == []
        sheet = (tmp_path / batch1.ADJUDICATION_MARKDOWN).read_text()
        assert "**yes** (2026-10-01, decisionsFile)" in sheet
    assert report["measured"]["per_fr_id"]["136"]["mentions"] == 2  # the replay count did change
    assert decisions_path.read_bytes() == before  # the tool never writes the owner's file


def test_a_decision_stales_only_when_its_own_row_changes(
    tmp_path: Path, assembled: dict[str, Any], releases: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    digests = batch1.decision_digests(assembled)
    energy, labor = "same:fr136:ecfr:energy-department", "same:fr271:ecfr:labor-department"
    path = _decisions(tmp_path, {key: _decision(digests, key, "yes") for key in (energy, labor)})
    # A text change to the Energy row only: the set digest moves, Labor's decision stays current.
    edited = tuple(
        dataclasses.replace(bridge, reasoning=bridge.reasoning + " Reworded.") if bridge.fr_agency_id == 136 else bridge
        for bridge in batch1.IDENTITY_BRIDGES
    )
    monkeypatch.setattr(batch1, "IDENTITY_BRIDGES", edited)
    changed = batch1.assemble_candidates(releases)
    assert batch1.candidates_digest(changed) != batch1.candidates_digest(assembled)
    decisions = batch1.load_decisions(path, changed)
    assert set(decisions.current) == {labor}
    assert set(decisions.stale) == {energy}
    sheet = batch1.render_adjudication_sheet({**changed, **_report_shell(tmp_path, assembled)}, decisions)
    assert "STALE: yes (2026-10-01)" in sheet
    assert f"`{energy}`" in sheet.split("## Stale decisions")[1]


def _report_shell(tmp_path: Path, assembled: dict[str, Any]) -> dict[str, Any]:
    """The measured and input blocks of a real report, to render a sheet around edited candidates."""
    report = batch1.assemble_report(ROOT, _replay(tmp_path, "shell"))
    return {key: report[key] for key in report if key not in batch1.CANDIDATES_DIGEST_COVERS}


def test_an_event_decision_stales_when_one_of_its_rows_changes(
    assembled: dict[str, Any], releases: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = "event:fr232"
    path = _decisions(tmp_path, {key: _decision(batch1.decision_digests(assembled), key, "accept-every-row")})
    edited = tuple(
        dataclasses.replace(event, rows=(dataclasses.replace(event.rows[0], functions_taken="immigration services"), *event.rows[1:]))
        if event.originals == (232,)
        else event
        for event in batch1.SUCCESSION_EVENTS
    )
    monkeypatch.setattr(batch1, "SUCCESSION_EVENTS", edited)
    assert set(batch1.load_decisions(path, batch1.assemble_candidates(releases)).stale) == {key}


def test_unknown_or_partial_decisions_are_refused(tmp_path: Path, assembled: dict[str, Any]) -> None:
    replay = _replay(tmp_path)
    report = batch1.assemble_report(ROOT, replay)
    digests = batch1.decision_digests(report)

    def load(key: str, answer: str, **extra: str) -> batch1.Decisions:
        decision = {"answer": answer, "decided_on": "2026-10-01", "content_digest": digests.get(key, "sha256:" + "4" * 64), "channel": "decisionsFile", **extra}
        return batch1.load_decisions(_decisions(tmp_path, {key: decision}), report)

    with pytest.raises(ValueError, match=r"decisions\.json: decisions for unknown ids same:fr999:ecfr:nowhere;"):
        load("same:fr999:ecfr:nowhere", "yes")
    with pytest.raises(ValueError, match=r"succ:fr232:fr499 \(a row of event:fr232; decide the event\)"):
        load("succ:fr232:fr499", "accept")  # an event row is never decided alone
    both = {key: {"answer": "yes", "decided_on": "2026-10-01", "content_digest": "sha256:" + "4" * 64, "channel": "decisionsFile"} for key in ("same:fr998:x", "same:fr999:y")}
    with pytest.raises(ValueError, match="unknown ids same:fr998:x, same:fr999:y;"):
        batch1.load_decisions(_decisions(tmp_path, both), report)
    with pytest.raises(ValueError, match="not one of"):
        load("event:fr232", "accept")
    with pytest.raises(ValueError, match="needs a note"):
        load("event:fr232", "wrong-date")
    assert set(load("event:fr232", "wrong-date", note="2003-03-02").current) == {"event:fr232"}
    assert batch1.load_decisions(tmp_path / "absent.json", report) == batch1.NO_DECISIONS
