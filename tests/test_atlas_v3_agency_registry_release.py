"""REF-072's agency-registry release: exactly the owner's decisions on every batch, refused whole when one is stale."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from refspec.atlas import agency_projection
from refspec.atlas import v3_registry_alignments_entity as entity
from refspec.atlas.v3_source_data import RegistryMappingRelease, RegistryRelease
from tools import analyze_agency_roster_identifiers as census

ROOT = Path(__file__).resolve().parents[1]
OWNER = "urn:ref:reviewer:refspec-owner"
BRIDGES = {
    "same:fr118:ecfr:economic-analysis-bureau",
    "same:fr136:ecfr:energy-department",
    "same:fr186:ecfr:federal-register-office",
    "same:fr244:fh:100006936",
    "same:fr245:fh:100004455",
    "same:fr271:ecfr:labor-department",
    "same:fr277:ecfr:library-of-congress",
    "same:fr409:ecfr:postal-regulatory-commission",
    "same:fr4:ecfr:african-development-foundation",
    "same:fr503:fh:100012075",
    "same:fr587:fh:100525875",
    "same:fr603:ecfr:investment-security-office",
    "same:fr88:ecfr:copyright-royalty-board",
}
EVENTS = {
    "event:fr150": "2002-04-18",
    "event:fr259": "2008-11-21",
    "event:fr404": "2003-02-03",
    "event:fr559": "2001-06-29",
    "event:fr564": "2006-12-20",
    "event:fr96": "2003-03-01",
    "event:fr232": "2003-03-01",
    "event:fr510": "1999-10-01",
    "event:fr543": "1996-01-01",
    "event:fr200": "2026-06-24",
}
NON_EMISSIONS = {
    "same:fr151:ecfr:export-import-bank": "sameOrganizationReverseLookupCostRejected",
    "same:fr296:fh:300000070": "heldForStatutoryRenameBasis",
    "same:fr255:ecfr:international-boundary-and-water-commission-united-states-and-mexico": "withdrawn",
    "no-fr-bridge:regs:CISA": "noCounterpartInHeldFRRoster",
}


def _fr(fr_id: int) -> str:
    return f"urn:ref:federal-register-agency:{fr_id}"


@pytest.fixture(scope="module")
def rosters() -> tuple[RegistryRelease, ...]:
    return census.load_five_agency_rosters(ROOT)


@pytest.fixture(scope="module")
def release(rosters: tuple[RegistryRelease, ...]) -> RegistryMappingRelease:
    return entity.load_agency_registry_mapping_release(rosters)


@pytest.fixture(scope="module")
def plans() -> tuple[dict, dict]:
    return (
        json.loads((ROOT / entity.AGENCY_REGISTRY_CANDIDATES_PATH).read_text()),
        json.loads((ROOT / entity.AGENCY_REGISTRY_DECISIONS_PATH).read_text()),
    )


@pytest.fixture(scope="module")
def succession_plans() -> tuple[dict, dict]:
    return (
        json.loads((ROOT / entity.AGENCY_REGISTRY_SUCCESSION_CANDIDATES_PATH).read_text()),
        json.loads((ROOT / entity.AGENCY_REGISTRY_SUCCESSION_DECISIONS_PATH).read_text()),
    )


def _decided(release: RegistryMappingRelease) -> dict[str, dict]:
    return {row.get("candidateId") or row["eventId"]: row for row in release.metadata["decisions"]}


def test_the_release_emits_exactly_the_owners_decisions_with_parity(release: RegistryMappingRelease) -> None:
    """Pin 27 decided items = 13 bridges + 10 events + 4 recorded non-emissions, each item once, over both batches."""

    decided = _decided(release)
    assert release.key == "agency-registry-2026-09-26"
    assert release.key in entity.ENTITY_REGISTRY_MAPPING_RELEASE_KEYS
    assert (len(release.mappings), len(release.change_events)) == (13, 10)
    assert {key for key, row in decided.items() if row["decision"] == "adopted"} == BRIDGES
    assert {key for key, row in decided.items() if row["decision"] == "event"} == set(EVENTS)
    assert {key: row["reason"] for key, row in decided.items() if row["decision"] == "nonEmission"} == NON_EMISSIONS
    assert len(decided) == release.metadata["decidedItemCount"] == 27 == 13 + 10 + 4
    assert (release.metadata["bridgeCount"], release.metadata["eventCount"], release.metadata["nonEmissionCount"]) == (
        13,
        10,
        4,
    )
    assert release.metadata["candidatesDigests"] == {
        entity.AGENCY_REGISTRY_CANDIDATES_PATH: entity.AGENCY_REGISTRY_CANDIDATES_DIGEST,
        entity.AGENCY_REGISTRY_SUCCESSION_CANDIDATES_PATH: entity.AGENCY_REGISTRY_SUCCESSION_CANDIDATES_DIGEST,
    }
    assert release.issued == "2026-09-26"


def test_every_bridge_keeps_ref_038s_shape_and_cites_the_decisions_file(
    release: RegistryMappingRelease,
    plans: tuple[dict, dict],
) -> None:
    """Pin one way, the proposed basis, both sealed names and parents, and two owner E4 records per bridge."""

    candidates = {row["candidate_id"]: row for row in plans[0]["candidates"] if row["relation"] == "sameEntityAs"}
    decided = _decided(release)
    claims = {(mapping.subject, mapping.object) for mapping in release.mappings}
    assert not {(obj, subject) for subject, obj in claims} & claims
    for mapping in release.mappings:
        decision = next(row for row in release.metadata["decisions"] if row.get("sourceResource") == mapping.subject)
        candidate = candidates[decision["candidateId"]]
        assert mapping.predicate == entity.ATLAS_SAME_ENTITY_AS
        assert mapping.subject.startswith("urn:ref:federal-register-agency:")
        assert (mapping.subject, mapping.object) == (
            candidate["source"]["resource_iri"],
            candidate["target"]["resource_iri"],
        )
        assert decision["basis"] == candidate["proposed_basis"] in entity.AGENCY_DECISION_BASES
        assert decided[decision["candidateId"]] is decision
        assert len(mapping.evidence) == 2
        roles = set()
        for evidence in mapping.evidence:
            payload = evidence.native_payload
            assert (evidence.review_warrant, evidence.reviewer_iri, evidence.attested_at) == (
                "humanReview",
                OWNER,
                "2026-09-26T00:00:00+00:00",
            )
            assert payload["evidenceTier"] == "E4"
            assert payload["decisionRecord"] == "docs/decisions.md#ref-072"
            assert payload["ownerDecision"]["decisionsFile"] == entity.AGENCY_REGISTRY_DECISIONS_PATH
            assert payload["ownerDecision"]["channel"] == "questionTool"
            assert payload["ownerDecision"]["answer"] == "yes"
            assert payload["ownerDecision"]["contentDigest"] == candidate["content_digest"]
            assert payload["publisherNames"] == {
                "subject": candidate["source"]["publisher_name"],
                "object": candidate["target"]["publisher_name"],
            }
            for side, record in (("subject", candidate["source"]), ("object", candidate["target"])):
                parent = record["parent"]
                assert payload["parents"].get(side) == (
                    None
                    if parent is None
                    else {"publisherName": parent["publisher_name"], "resourceIri": parent["resource_iri"]}
                )
            roles.add(payload["endpointRole"])
        assert roles == {"subject", "object"}


def test_every_event_carries_its_date_results_functions_and_records(
    release: RegistryMappingRelease,
    plans: tuple[dict, dict],
    succession_plans: tuple[dict, dict],
) -> None:
    """Pin each event's originals, results, date, one owner E4 record per public record, and each result's functions."""

    events = {row["event_id"]: row for candidates in (plans[0], succession_plans[0]) for row in candidates["events"]}
    rows = {
        row["candidate_id"]: row
        for candidates in (plans[0], succession_plans[0])
        for row in candidates["candidates"]
        if "event_id" in row
    }
    decided = _decided(release)
    for change in release.change_events:
        event_id = "event:fr" + change.originals[0].rsplit(":", 1)[1]
        event = events[event_id]
        assert change.effective_date == EVENTS[event_id] == event["effective_date"]
        assert list(change.originals) == [record["resource_iri"] for record in event["originals"]]
        assert set(change.results) == {rows[row_id]["target"]["resource_iri"] for row_id in event["rows"]}
        assert len(change.evidence) == len(event["public_records"])
        assert {evidence.source_locator for evidence in change.evidence} == {
            record["url"] for record in event["public_records"]
        }
        for evidence in change.evidence:
            assert (evidence.review_warrant, evidence.reviewer_iri) == ("humanReview", OWNER)
            assert evidence.source_locator.startswith("https://")
            assert evidence.native_payload["ownerDecision"]["contentDigest"] == event["content_digest"]
        functions = {row["resourceIri"]: row.get("functionsTaken") for row in decided[event_id]["results"]}
        assert functions == {rows[row_id]["target"]["resource_iri"]: rows[row_id]["functions_taken"] for row_id in event["rows"]}
    splits = {change.originals[0]: change for change in release.change_events if len(change.results) > 1}
    assert set(splits) == {_fr(96), _fr(232), _fr(510), _fr(543)}
    assert set(splits[_fr(232)].results) == {_fr(499), _fr(501), _fr(503)}
    postal = next(change for change in release.change_events if change.originals == (_fr(564),))
    assert postal.results == (_fr(409),)


def test_the_release_metadata_carries_no_null(release: RegistryMappingRelease) -> None:
    """Pin that the metadata a generation report embeds as canonical JSON has no null anywhere."""

    def walk(value: object) -> None:
        assert value is not None
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child)

    walk(json.loads(json.dumps(release.metadata, default=lambda value: dict(value) if hasattr(value, "items") else list(value))))


def test_held_and_rejected_rows_emit_nothing_and_add_no_basis(release: RegistryMappingRelease) -> None:
    """Pin that EIB and Udall emit no bridge and that no statutory-rename basis joined the closed vocabulary."""

    emitted = {mapping.subject for mapping in release.mappings}
    assert _fr(151) not in emitted and _fr(296) not in emitted and _fr(255) not in emitted
    assert not any("statutory" in basis.lower() for basis in entity.AGENCY_DECISION_BASES)
    decided = _decided(release)
    assert decided["same:fr151:ecfr:export-import-bank"]["reasoning"].startswith("The same organization, but reject")
    assert decided["same:fr296:fh:300000070"]["reasoning"].startswith("Proposed: the same foundation, held")
    assert decided["same:fr255:ecfr:international-boundary-and-water-commission-united-states-and-mexico"][
        "closestAlternative"
    ]["relation"] == "partOf"


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda candidates, decisions: decisions["decisions"]["event:fr232"].update(content_digest="sha256:" + "0" * 64), "stale decisions"),
        (lambda candidates, decisions: decisions["decisions"].pop("same:fr88:ecfr:copyright-royalty-board"), "undecided items"),
        (lambda candidates, decisions: decisions["decisions"]["same:fr118:ecfr:economic-analysis-bureau"].update(answer="no"), "has no rule"),
        (lambda candidates, decisions: decisions["decisions"]["same:fr296:fh:300000070"].update(answer="2"), "has no rule"),
        (lambda candidates, decisions: candidates["events"][0].update(effective_date="2002-04-19"), "candidates digest"),
    ),
)
def test_a_stale_missing_or_unruled_decision_refuses_the_release(
    plans: tuple[dict, dict],
    mutate,
    message: str,
) -> None:
    """Pin the three refusals: stale or missing decisions, an answer with no rule, and candidates not the ones decided."""

    candidates, decisions = copy.deepcopy(plans[0]), copy.deepcopy(plans[1])
    mutate(candidates, decisions)
    with pytest.raises(ValueError, match=message):
        entity.agency_registry_outcomes(candidates, decisions)


def test_the_plans_are_read_by_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rosters) -> None:
    """Pin that a decisions file whose bytes differ from the pin is refused before it is parsed."""

    changed = tmp_path / "decisions.json"
    changed.write_bytes((ROOT / entity.AGENCY_REGISTRY_DECISIONS_PATH).read_bytes() + b" ")
    monkeypatch.setattr(
        entity,
        "_AGENCY_REGISTRY_DECISIONS_PIN",
        dataclasses.replace(entity._AGENCY_REGISTRY_DECISIONS_PIN, path=changed),
    )
    with pytest.raises(ValueError, match="pinned input"):
        entity.load_agency_registry_mapping_release(rosters)


def test_ref_038_is_untouched_and_its_projection_refuses_the_new_release(
    rosters: tuple[RegistryRelease, ...],
    release: RegistryMappingRelease,
) -> None:
    """Pin REF-038's release digest and that build_agency_projection still reads REF-038 only."""

    identity = entity.load_regulations_gov_agency_identity_mapping_release(rosters)
    assert identity.source_release_digest == (
        "sha256:19e644829e374f1a78287add2dc0d5827c6dde566f5e727ea4365e4480cf3b3d"
    )
    assert len(identity.mappings) + identity.metadata["abstentionCount"] == 331
    assert agency_projection.build_agency_projection(rosters, identity).digest == (
        "sha256:0dd32dd5320a0d1553f10818a7a31e95e2c3b9b6567df224dd359a8038e14db4"
    )
    with pytest.raises(ValueError, match="REF-038"):
        agency_projection.build_agency_projection(rosters, release)


def test_each_roster_parent_map_is_derived_once_per_release(
    monkeypatch: pytest.MonkeyPatch,
    rosters: tuple[RegistryRelease, ...],
) -> None:
    """Pin the scaling guard: each release derives a roster's parent map once, never once per mapping.

    REF-038's release walked the regulations.gov roster 331 times, once per
    decided value, and the registry release the Register's once per bridge.
    """

    derived: list[str] = []
    original = agency_projection.parent_by_subject

    def counting(release: RegistryRelease) -> dict[str, str]:
        derived.append(release.key)
        return original(release)

    monkeypatch.setattr(agency_projection, "parent_by_subject", counting)
    entity.load_regulations_gov_agency_identity_mapping_release(rosters)
    assert derived == [agency_projection.REGULATIONS_GOV_RELEASE_KEY]
    derived.clear()
    entity.load_agency_registry_mapping_release(rosters)
    assert sorted(derived) == sorted(agency_projection.AGENCY_ROSTER_RELEASE_KEYS)


@pytest.fixture(scope="module")
def context(rosters: tuple[RegistryRelease, ...]) -> dict:
    """The re-derivation context the loader builds: releases, resources and parents by roster key."""

    by_key = entity._releases_by_key(rosters)
    keys = agency_projection.AGENCY_ROSTER_RELEASE_KEYS
    return {
        "by_key": by_key,
        "resources": {key: entity._resources_by_iri(by_key[key]) for key in keys},
        "parents": {key: agency_projection.parent_by_subject(by_key[key]) for key in keys},
    }


def _event_parts(plans: tuple[dict, dict], event_id: str) -> tuple[dict, list[dict], dict]:
    candidates, decisions = copy.deepcopy(plans[0]), plans[1]
    event = next(row for row in candidates["events"] if row["event_id"] == event_id)
    rows = sorted(
        (row for row in candidates["candidates"] if row.get("event_id") == event_id),
        key=lambda row: row["candidate_id"],
    )
    return event, rows, decisions["decisions"][event_id]


@pytest.mark.parametrize(
    ("event_id", "edit", "message"),
    (
        ("event:fr543", lambda event, rows: [record.update(kind="publisherRoster") for record in event["public_records"]], "rests on no dated public record"),
        ("event:fr150", lambda event, rows: event["public_records"][0].update(url="http://www.federalregister.gov/x"), "cites a non-https record"),
        ("event:fr150", lambda event, rows: rows[0]["target"].update(release_key=agency_projection.ECFR_RELEASE_KEY), "not a Federal Register roster record"),
    ),
)
def test_an_event_resting_on_no_dated_https_record_or_naming_a_non_register_organization_is_refused(
    plans: tuple[dict, dict],
    context: dict,
    event_id: str,
    edit,
    message: str,
) -> None:
    """Pin the event guards the owner's decisions never trip: a dated kind, https records, Register organizations only."""

    event, rows, decision = _event_parts(plans, event_id)
    entity._change_event(event, rows, decision, decisions_pin=entity._AGENCY_REGISTRY_DECISIONS_PIN, **context)
    edit(event, rows)
    with pytest.raises(ValueError, match=message):
        entity._change_event(event, rows, decision, decisions_pin=entity._AGENCY_REGISTRY_DECISIONS_PIN, **context)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("publisher_name", "Economic Analysis Bureau (renamed)", "sealed publisher name drifted"),
        ("parent", {"publisher_name": "Treasury Department", "resource_iri": _fr(497)}, "publisher parent drifted"),
    ),
)
def test_a_drifted_publisher_name_or_parent_is_refused(
    plans: tuple[dict, dict],
    context: dict,
    field: str,
    value: object,
    message: str,
) -> None:
    """Pin that a candidate record re-derived from the pinned roster must still carry the decided name and parent."""

    bridge = next(row for row in plans[0]["candidates"] if row["candidate_id"] == "same:fr118:ecfr:economic-analysis-bureau")
    record = copy.deepcopy(bridge["source"])
    entity._roster_record(record=record, **context)
    record[field] = value
    with pytest.raises(ValueError, match=message):
        entity._roster_record(record=record, **context)


def test_a_bridge_must_run_from_the_register(plans: tuple[dict, dict], context: dict) -> None:
    """Pin the bridge direction: Federal Register subject, eCFR or Federal Hierarchy object, never reversed."""

    bridge = copy.deepcopy(
        next(row for row in plans[0]["candidates"] if row["candidate_id"] == "same:fr118:ecfr:economic-analysis-bureau")
    )
    entity._bridge_endpoints(bridge, **context)
    bridge["source"], bridge["target"] = bridge["target"], bridge["source"]
    with pytest.raises(ValueError, match="is not a Federal Register-to-eCFR or Federal Hierarchy bridge"):
        entity._bridge_endpoints(bridge, **context)


def test_decisions_come_only_from_the_owner(plans: tuple[dict, dict]) -> None:
    """Pin the reviewer-IRI rule: a decisions file in anyone else's name is refused whole."""

    decisions = copy.deepcopy(plans[1])
    decisions["reviewer_iri"] = "urn:ref:reviewer:someone-else"
    with pytest.raises(ValueError, match="decisions come only from the owner's reviewer IRI"):
        entity.agency_registry_outcomes(plans[0], decisions)


def test_a_non_emission_reason_outside_the_closed_vocabulary_is_refused(plans: tuple[dict, dict]) -> None:
    """Pin that the release refuses a non-emission reason no one defined."""

    item = next(row for row in plans[0]["no_fr_bridge"] if row["value_id"] == "no-fr-bridge:regs:CISA")
    decision = plans[1]["decisions"]["no-fr-bridge:regs:CISA"]
    outcome = entity.AgencyRegistryOutcome(item["value_id"], "nonEmission", None, decision)
    entity._non_emission(outcome, item, {})
    with pytest.raises(ValueError, match="outside the closed vocabulary"):
        entity._non_emission(outcome, {**item, "reason": "notReviewedYet"}, {})


def test_each_item_attests_the_day_the_owner_decided_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rosters: tuple[RegistryRelease, ...],
    plans: tuple[dict, dict],
) -> None:
    """Pin per-item attestation: a decision dated another day is asserted and attested on that day."""

    decisions = copy.deepcopy(plans[1])
    decisions["decisions"]["same:fr118:ecfr:economic-analysis-bureau"]["decided_on"] = "2026-09-25"
    decisions["decisions"]["event:fr232"]["decided_on"] = "2026-09-27"
    changed = tmp_path / "decisions.json"
    changed.write_text(json.dumps(decisions, indent=2) + "\n")
    payload = changed.read_bytes()
    monkeypatch.setattr(
        entity,
        "_AGENCY_REGISTRY_DECISIONS_PIN",
        dataclasses.replace(
            entity._AGENCY_REGISTRY_DECISIONS_PIN,
            path=changed,
            sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
            byte_length=len(payload),
        ),
    )
    release = entity.load_agency_registry_mapping_release(rosters)

    eab = next(mapping for mapping in release.mappings if mapping.subject == _fr(118))
    assert eab.asserted_at == "2026-09-25T00:00:00+00:00"
    assert {evidence.attested_at for evidence in eab.evidence} == {"2026-09-25T00:00:00+00:00"}
    assert {evidence.native_payload["decidedAt"] for evidence in eab.evidence} == {"2026-09-25T00:00:00+00:00"}
    energy = next(mapping for mapping in release.mappings if mapping.subject == _fr(136))
    assert energy.asserted_at == "2026-09-26T00:00:00+00:00"
    ins = next(change for change in release.change_events if change.originals == (_fr(232),))
    assert ins.asserted_at == "2026-09-27T00:00:00+00:00"
    assert {evidence.attested_at for evidence in ins.evidence} == {"2026-09-27T00:00:00+00:00"}
    assert {evidence.native_payload["ownerDecision"]["decidedOn"] for evidence in ins.evidence} == {"2026-09-27"}
    assert release.issued == "2026-09-25"


def test_the_succession_batch_rides_with_batch_1s_bridges_and_cites_its_own_files(
    release: RegistryMappingRelease,
    rosters: tuple[RegistryRelease, ...],
    succession_plans: tuple[dict, dict],
) -> None:
    """Pin FNS -> FNA: one event in the same release as batch 1's 13 bridges, its records citing its own batch.

    Batch 1 alone still rebuilds the release the 1.1 and 1.0 views were sealed from, digest for digest.
    """

    (fna,) = (change for change in release.change_events if change.originals == (_fr(200),))
    assert (fna.results, fna.effective_date, fna.asserted_at) == ((_fr(625),), "2026-06-24", "2026-10-03T00:00:00+00:00")
    event = succession_plans[0]["events"][0]
    assert len(fna.evidence) == len(event["public_records"]) == 3
    for evidence in fna.evidence:
        assert evidence.source_digest == entity._AGENCY_REGISTRY_SUCCESSION_CANDIDATES_PIN.sha256
        decision = evidence.native_payload["ownerDecision"]
        assert decision["decisionsFile"] == entity.AGENCY_REGISTRY_SUCCESSION_DECISIONS_PATH
        assert decision["contentDigest"] == event["content_digest"] == succession_plans[1]["decisions"]["event:fr200"]["content_digest"]
        assert (decision["answer"], decision["channel"], decision["decidedOn"]) == ("accept", "questionTool", "2026-10-03")
    roles = release.source_release_input_roles[-4:]
    assert roles == ("ownerCandidates", "ownerDecisions", "successionOwnerCandidates", "successionOwnerDecisions")
    batch_1 = entity.load_agency_registry_mapping_release(rosters, entity.agency_registry_batches()[:1])
    assert batch_1.source_release_digest == "sha256:69001a4381ddf35cdba6d44fa52f579d7dfa07627c4c74da3dde2b0d8a39f8f0"
    assert (len(batch_1.mappings), len(batch_1.change_events), batch_1.metadata["decidedItemCount"]) == (13, 9, 26)


def test_a_succession_batch_alone_or_decided_twice_is_refused(rosters: tuple[RegistryRelease, ...]) -> None:
    """Pin REF-072's limit, the per-batch parity, and that no item is decided in two batches.

    A batch of events alone is no mapping release: the succession batch is released only beside batch 1's bridges.
    """

    batch_1, succession = entity.agency_registry_batches()
    with pytest.raises(ValueError, match="has no mappings"):
        entity.load_agency_registry_mapping_release(rosters, (succession,))
    with pytest.raises(ValueError, match="parity of plans/agency-registry-succession-batch-decisions.json"):
        entity.load_agency_registry_mapping_release(rosters, (batch_1, succession._replace(parity=(0, 0, 1))))
    with pytest.raises(ValueError, match="decided in two agency registry batches"):
        entity.load_agency_registry_mapping_release(rosters, (batch_1, succession, succession))

