"""The succession batch proposes dated change events only, built as batch 1 builds them, for the owner to decide."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas import v3_registry_alignments_entity as entity_alignments
from tools import analyze_agency_roster_identifiers as census
from tools import assemble_agency_registry_succession_batch as succession

ROOT = Path(__file__).resolve().parents[1]
ADJUDICATION_KEYS = {"reviewerIri", "reviewer", "evidenceTier", "evidence_tier", "decidedAt", "adjudicated_on", "warrant"}


@pytest.fixture(scope="module")
def releases() -> tuple[Any, ...]:
    return census.load_five_agency_rosters(ROOT)


@pytest.fixture(scope="module")
def report(releases: tuple[Any, ...]) -> dict[str, Any]:
    return succession.assemble(ROOT, releases)


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_keys(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(child) for child in value))
    return set()


def test_committed_artifacts_follow_from_the_rosters_and_decisions(releases: tuple[Any, ...]) -> None:
    assert succession.write_or_check(ROOT, write=False, releases=releases) == []


def test_nothing_is_adjudicated(report: dict[str, Any]) -> None:
    for row in (*report["candidates"], *report["events"]):
        assert row["status"] == "candidate-pending-owner-adjudication"
    assert not _keys(report) & ADJUDICATION_KEYS
    decisions = entity_alignments.load_decisions(ROOT / succession.DECISIONS_JSON, report)
    assert decisions == entity_alignments.NO_DECISIONS


def test_fns_became_fna_as_a_dated_rename_between_two_held_register_records(report: dict[str, Any], releases: tuple[Any, ...]) -> None:
    (event,) = report["events"]
    (row,) = report["candidates"]
    assert (event["event_id"], event["rows"], event["group"]) == ("event:fr200", ["succ:fr200:fr625"], "C")
    assert event["effective_date"] == "2026-06-24"
    roster = next(release for release in releases if release.key == row["source"]["release_key"])
    resources = {resource.iri: resource for resource in roster.resources}
    for side, expected in (("source", "Food and Nutrition Service"), ("target", "Food and Nutrition Administration")):
        record = row[side]
        field, name = entity_alignments.publisher_name(record["release_key"], resources[record["resource_iri"]])
        assert (record["name_field"], record["publisher_name"]) == (field, name) == ("name", expected)
        assert record["parent"]["resource_iri"] == "urn:ref:federal-register-agency:12"
    assert {record["kind"] for record in event["public_records"]} & entity_alignments.DATED_PUBLIC_RECORD_KINDS
    assert all(record["url"].startswith("https://") for record in event["public_records"])
    manifest = json.loads((ROOT / succession.EVIDENCE_MANIFEST).read_text())
    retained = {entry["url"] for entry in manifest if entry["http_status"] == 200}
    assert "https://www.federalregister.gov/api/v1/documents/2026-12700.json" in retained


def test_an_undated_event_or_one_batch_1_holds_is_refused(monkeypatch: pytest.MonkeyPatch, releases: tuple[Any, ...]) -> None:
    (event,) = succession.SUCCESSION_EVENTS
    (row,) = event.rows
    roster_only = dataclasses.replace(row, records=tuple(r for r in row.records if r.kind == "publisherRoster"))
    monkeypatch.setattr(succession, "SUCCESSION_EVENTS", (dataclasses.replace(event, rows=(roster_only,)),))
    with pytest.raises(ValueError, match="no dated public record"):
        succession.assemble(ROOT, releases)
    # FR 559, the Health Care Financing Administration, is one of batch 1's decided originals.
    monkeypatch.setattr(succession, "SUCCESSION_EVENTS", (dataclasses.replace(event, originals=(559,)),))
    with pytest.raises(ValueError, match="batch 1's to decide"):
        succession.assemble(ROOT, releases)


def test_a_decision_binds_to_the_event_and_stales_when_it_changes(report: dict[str, Any]) -> None:
    digest = report["events"][0]["content_digest"]
    document = {
        "schema_version": entity_alignments.DECISIONS_SCHEMA_VERSION,
        "reviewer_iri": "urn:ref:reviewer:refspec-owner",
        "decisions": {"event:fr200": {"answer": "accept", "decided_on": "2026-10-04", "content_digest": digest, "channel": "questionTool"}},
    }
    current = entity_alignments.decisions_from_json(document, report, label="test")
    assert set(current.current) == {"event:fr200"}
    assert "| Owner decision / date | **accept** (2026-10-04, questionTool) |" in succession.render_adjudication_sheet(report, current)
    document["decisions"]["event:fr200"]["content_digest"] = "sha256:" + "0" * 64
    stale = entity_alignments.decisions_from_json(document, report, label="test")
    assert set(stale.stale) == {"event:fr200"} and not stale.current
    assert "## Stale decisions" in succession.render_adjudication_sheet(report, stale)
    with pytest.raises(ValueError, match="event:fr200"):
        entity_alignments.decisions_from_json(
            {**document, "decisions": {"succ:fr200:fr625": document["decisions"]["event:fr200"]}}, report, label="test"
        )
