"""REF-072's agency registry view and its forward successor lookup: derived, sealed, never asserted."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from refspec.atlas import agency_projection, parquet_view
from refspec.atlas import v3_registry_alignments_entity as entity
from refspec.atlas.parquet_artifact import canonical_payload_sha256, file_sha256
from refspec.atlas.parquet_tables import (
    AGENCY_REGISTRY_BRIDGE_ROLE,
    AGENCY_REGISTRY_EVENT_ROLE,
    AGENCY_REGISTRY_NON_EMISSION_ROLE,
    AGENCY_REGISTRY_TABLE_SCHEMAS,
    agency_registry_table_relative_path,
)
from refspec.atlas.parquet_view import (
    MANIFEST_FILE,
    AtlasParquetViewError,
    seal_agency_registry_view,
    verify_agency_registry_view,
)
from refspec.atlas.v3_source_data import RegistryMappingEvidence, RegistryMappingRelease, RegistryRelease
from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes
from tools import analyze_agency_roster_identifiers as census
from tools import build_agency_registry_view as view_tool

ROOT = Path(__file__).resolve().parents[1]


def _fr(fr_id: int) -> str:
    return f"urn:ref:federal-register-agency:{fr_id}"


@pytest.fixture(scope="module")
def rosters() -> tuple[RegistryRelease, ...]:
    return census.load_five_agency_rosters(ROOT)


@pytest.fixture(scope="module")
def release(rosters: tuple[RegistryRelease, ...]) -> RegistryMappingRelease:
    return entity.load_agency_registry_mapping_release(rosters)


@pytest.fixture(scope="module")
def view(release: RegistryMappingRelease) -> agency_projection.AgencyRegistryView:
    return agency_projection.build_agency_registry_view(release)


def test_the_view_rows_are_exactly_the_release(view: agency_projection.AgencyRegistryView) -> None:
    """Pin 13 bridges, one row per (event, result) -- 14 for 9 events -- and 4 non-emissions."""

    assert dict(view.coverage) == {
        "bridgeCount": 13,
        "decidedItemCount": 26,
        "eventCount": 9,
        "eventResultRowCount": 14,
        "nonEmissionCount": 4,
    }
    splits = {row["result"]: row for row in view.events if row["event_id"] == "event:fr232"}
    assert set(splits) == {_fr(499), _fr(501), _fr(503)}
    assert all(row["effective_date"] == "2003-03-01" and row["functions_taken"] for row in splits.values())
    assert all(row["public_records"] for row in view.events)
    renames = [row for row in view.events if row["event_id"] == "event:fr150"]
    assert [(row["result"], row["functions_taken"]) for row in renames] == [(_fr(241), None)]
    assert all(row["decision"]["reviewer"] == "urn:ref:reviewer:refspec-owner" for row in (*view.bridges, *view.events))
    assert view.release["key"] == "agency-registry-2026-09-26"


def test_the_view_builder_reads_the_registry_release_only(rosters: tuple[RegistryRelease, ...]) -> None:
    """Pin that REF-038's release does not feed the registry view, as the registry release does not feed REF-038's."""

    with pytest.raises(ValueError, match="agency-registry release only"):
        agency_projection.build_agency_registry_view(
            entity.load_regulations_gov_agency_identity_mapping_release(rosters)
        )


def test_the_sealed_view_is_deterministic_and_pinned(tmp_path: Path, release, view) -> None:
    """Pin the manifest digest the design note names, reproduced twice from the same release."""

    first = seal_agency_registry_view(tmp_path / "a", release)
    second = seal_agency_registry_view(tmp_path / "b", release)
    assert first == second
    assert file_sha256(tmp_path / "a" / MANIFEST_FILE) == view_tool.VIEW_MANIFEST_SHA256
    assert {member["path"]: member["rowCount"] for member in first["members"]} == {
        "tables/agency-registry-bridges.parquet": 13,
        "tables/agency-registry-events.parquet": 14,
        "tables/agency-registry-non-emissions.parquet": 4,
    }
    assert first["digest"] == view.digest


def test_a_resealed_row_edit_is_refused(tmp_path: Path, release) -> None:
    """Pin that a table rewritten and re-pinned in the manifest still fails on the rows' logical digest."""

    root = tmp_path / "view"
    seal_agency_registry_view(root, release)
    table = root / agency_registry_table_relative_path(AGENCY_REGISTRY_EVENT_ROLE)
    rows = pq.read_table(table).to_pylist()
    rows[0]["effective_date"] = "1900-01-01"
    table.unlink()
    pq.write_table(pa.Table.from_pylist(rows, schema=AGENCY_REGISTRY_TABLE_SCHEMAS[AGENCY_REGISTRY_EVENT_ROLE]), table)
    manifest = json.loads((root / MANIFEST_FILE).read_text())
    for member in manifest["members"]:
        if member["path"] == agency_registry_table_relative_path(AGENCY_REGISTRY_EVENT_ROLE):
            member["sha256"] = file_sha256(table)
            member["byteLength"] = table.stat().st_size
    manifest.pop("canonicalPayloadDigest")
    manifest["canonicalPayloadDigest"] = canonical_payload_sha256(manifest)
    (root / MANIFEST_FILE).write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(AtlasParquetViewError, match="logical-content digest differs"):
        verify_agency_registry_view(root, expected_manifest_digest=file_sha256(root / MANIFEST_FILE), release=release)


def _resealed_rows(root: Path, mutate: Callable[[dict[str, list[dict]]], None]) -> str:
    """Rewrite the view's rows and re-seal EVERYTHING around them: members, counts, coverage, digest, payload.

    What remains to refuse the edit is only the row-level rule under test, not a
    stale digest.
    """

    rows = {
        role: pq.read_table(root / agency_registry_table_relative_path(role)).to_pylist()
        for role in AGENCY_REGISTRY_TABLE_SCHEMAS
    }
    mutate(rows)
    for role, schema in AGENCY_REGISTRY_TABLE_SCHEMAS.items():
        table = root / agency_registry_table_relative_path(role)
        table.unlink()
        pq.write_table(pa.Table.from_pylist(rows[role], schema=schema), table)
    manifest = json.loads((root / MANIFEST_FILE).read_text())
    manifest["members"], manifest["counts"] = parquet_view._agency_registry_members(root)
    bridges, events, non_emissions = (rows[role] for role in AGENCY_REGISTRY_TABLE_SCHEMAS)
    manifest["digest"] = agency_projection.agency_registry_view_digest(
        bridges, events, non_emissions, manifest["coverage"]
    )
    manifest.pop("canonicalPayloadDigest")
    manifest["canonicalPayloadDigest"] = canonical_payload_sha256(manifest)
    (root / MANIFEST_FILE).write_bytes(canonical_json_bytes(manifest))
    return file_sha256(root / MANIFEST_FILE)


@pytest.mark.parametrize(
    ("role", "field", "value"),
    (
        (AGENCY_REGISTRY_BRIDGE_ROLE, "warrant", "publisherAssertion"),
        (AGENCY_REGISTRY_BRIDGE_ROLE, "evidence_tier", "E3"),
        (AGENCY_REGISTRY_EVENT_ROLE, "warrant", "publisherAssertion"),
        (AGENCY_REGISTRY_EVENT_ROLE, "originals", []),
        (AGENCY_REGISTRY_NON_EMISSION_ROLE, "decision", {"reviewer": "urn:ref:reviewer:someone-else"}),
    ),
)
def test_a_resealed_row_that_is_not_its_release_is_refused(
    tmp_path: Path,
    release: RegistryMappingRelease,
    role: str,
    field: str,
    value: object,
) -> None:
    """Pin that the verifier compares the rows with the release, with every digest re-sealed so nothing else refuses."""

    root = tmp_path / "view"
    seal_agency_registry_view(root, release)

    def edit(rows: dict[str, list[dict]]) -> None:
        rows[role][0][field] = {**rows[role][0][field], **value} if isinstance(value, dict) else value

    pin = _resealed_rows(root, edit)
    with pytest.raises(AtlasParquetViewError, match="differs from what its release states"):
        verify_agency_registry_view(root, expected_manifest_digest=pin, release=release)


def _with_evidence(
    release: RegistryMappingRelease,
    change: Callable[[RegistryMappingEvidence], RegistryMappingEvidence],
    *,
    claims: slice = slice(None),
) -> RegistryMappingRelease:
    """The release with ``change`` applied to every approval of the bridges and events ``claims`` selects."""

    def changed(claim):
        return dataclasses.replace(claim, evidence=tuple(change(item) for item in claim.evidence))

    mappings, events = list(release.mappings), list(release.change_events)
    mappings[claims] = [changed(mapping) for mapping in mappings[claims]]
    events[claims] = [changed(event) for event in events[claims]]
    return dataclasses.replace(release, mappings=tuple(mappings), change_events=tuple(events))


SHORT_EVIDENCE = {
    "evidence_tier": lambda item: dataclasses.replace(item, native_payload={**item.native_payload, "evidenceTier": "E3"}),
    "warrant": lambda item: dataclasses.replace(item, review_warrant="operatorAdoption"),
    "reviewer": lambda item: dataclasses.replace(item, reviewer_iri="urn:ref:reviewer:someone-else"),
}
SHORT_VALUES = {"evidence_tier": "E3", "warrant": "operatorAdoption", "reviewer": "urn:ref:reviewer:someone-else"}


@pytest.mark.parametrize("field", SHORT_EVIDENCE)
def test_the_view_states_what_its_releases_evidence_states(release: RegistryMappingRelease, field: str) -> None:
    """Pin F3: tier, warrant and reviewer are read off the release's approvals, so a short release shows as short."""

    view = agency_projection.build_agency_registry_view(_with_evidence(release, SHORT_EVIDENCE[field]))

    for row in (*view.bridges, *view.events, *(view.non_emissions if field == "reviewer" else ())):
        stated = row["decision"]["reviewer"] if field == "reviewer" else row[field]
        assert stated == SHORT_VALUES[field]


@pytest.mark.parametrize("field", SHORT_EVIDENCE)
def test_the_verifier_refuses_a_view_whose_release_states_less(
    tmp_path: Path, release: RegistryMappingRelease, field: str
) -> None:
    """Pin F3: the view sealed from the owner's E4 release is refused as the view of a release whose evidence differs."""

    root = tmp_path / "view"
    seal_agency_registry_view(root, release)

    with pytest.raises(AtlasParquetViewError, match="differs from what its release states"):
        verify_agency_registry_view(
            root,
            expected_manifest_digest=file_sha256(root / MANIFEST_FILE),
            release=_with_evidence(release, SHORT_EVIDENCE[field]),
        )


def test_the_view_refuses_approvals_that_do_not_state_one_review(release: RegistryMappingRelease) -> None:
    """Pin that one claim's approvals must agree, and that the release must name one reviewer for its non-emissions."""

    def first_approval_e3(item: RegistryMappingEvidence) -> RegistryMappingEvidence:
        if item.native_payload.get("endpointRole") != "subject":
            return item
        return SHORT_EVIDENCE["evidence_tier"](item)

    with pytest.raises(ValueError, match="approvals differ in evidence tier, warrant or reviewer"):
        agency_projection.build_agency_registry_view(_with_evidence(release, first_approval_e3, claims=slice(0, 1)))
    with pytest.raises(ValueError, match="more than one reviewer"):
        agency_projection.build_agency_registry_view(
            _with_evidence(release, SHORT_EVIDENCE["reviewer"], claims=slice(0, 1))
        )


def _e4_row_rule_oracle(rows: dict[str, list[dict]]) -> bool:
    """The verifier's row rule before F3, copied rather than imported: accept only E4 human-review rows with originals."""

    bridges, events = rows[AGENCY_REGISTRY_BRIDGE_ROLE], rows[AGENCY_REGISTRY_EVENT_ROLE]
    return not (
        any(
            row["evidence_tier"] != "E4" or row["warrant"] != "humanReview" or row["originals"] == []
            for row in events
        )
        or any(row["evidence_tier"] != "E4" or row["warrant"] != "humanReview" for row in bridges)
    )


# Where the release comparison and the literal rule part on purpose: the view
# must state what its release states. An E4 view of a release whose evidence
# says less is refused now and was accepted; an honest view of that release is
# accepted now and was refused; and the reviewer was never checked at all.
DELIBERATE_E4_RULE_DIVERGENCES = frozenset(
    {
        ("owner view of a short release", "evidence_tier"),
        ("owner view of a short release", "warrant"),
        ("owner view of a short release", "reviewer"),
        ("honest view of a short release", "evidence_tier"),
        ("honest view of a short release", "warrant"),
        ("resealed row edit", "non-emission reviewer"),
    }
)


def test_the_release_comparison_agrees_with_the_e4_rule_it_replaced_except_where_listed(
    tmp_path: Path, release: RegistryMappingRelease
) -> None:
    """Pin verdict agreement with the replaced literal rule over the real view and a mutation battery; list the rest."""

    def verdicts(label: str, root: Path, pin: str, against: RegistryMappingRelease) -> tuple[str, bool, bool]:
        rows = {
            role: pq.read_table(root / agency_registry_table_relative_path(role)).to_pylist()
            for role in AGENCY_REGISTRY_TABLE_SCHEMAS
        }
        try:
            verify_agency_registry_view(root, expected_manifest_digest=pin, release=against)
        except AtlasParquetViewError:
            return label, _e4_row_rule_oracle(rows), False
        return label, _e4_row_rule_oracle(rows), True

    def sealed(name: str, of: RegistryMappingRelease) -> tuple[Path, str]:
        seal_agency_registry_view(tmp_path / name, of)
        return tmp_path / name, file_sha256(tmp_path / name / MANIFEST_FILE)

    battery = [verdicts("real", *sealed("real", release), release)]
    for role, field, value, label in (
        (AGENCY_REGISTRY_BRIDGE_ROLE, "warrant", "publisherAssertion", "bridge warrant"),
        (AGENCY_REGISTRY_BRIDGE_ROLE, "evidence_tier", "E3", "bridge tier"),
        (AGENCY_REGISTRY_EVENT_ROLE, "warrant", "publisherAssertion", "event warrant"),
        (AGENCY_REGISTRY_EVENT_ROLE, "originals", [], "event originals"),
        (AGENCY_REGISTRY_NON_EMISSION_ROLE, "decision", "urn:ref:reviewer:someone-else", "non-emission reviewer"),
    ):
        root, _ = sealed(label, release)

        def edit(rows: dict[str, list[dict]], role=role, field=field, value=value) -> None:
            row = rows[role][0]
            row[field] = {**row[field], "reviewer": value} if field == "decision" else value

        battery.append(verdicts(("resealed row edit", label), root, _resealed_rows(root, edit), release))
    for field, change in SHORT_EVIDENCE.items():
        short = _with_evidence(release, change)
        battery.append(verdicts(("owner view of a short release", field), *sealed(f"owner-{field}", release), short))
        battery.append(verdicts(("honest view of a short release", field), *sealed(f"honest-{field}", short), short))

    assert battery[0] == ("real", True, True)
    divergences = {label for label, old, new in battery if old != new}
    assert divergences == DELIBERATE_E4_RULE_DIVERGENCES


def test_a_resealed_non_emission_reason_outside_the_vocabulary_is_refused(tmp_path: Path, release) -> None:
    """Pin the verifier's closed non-emission reasons, with every digest re-sealed so nothing else refuses."""

    root = tmp_path / "view"
    seal_agency_registry_view(root, release)

    def edit(rows: dict[str, list[dict]]) -> None:
        rows[AGENCY_REGISTRY_NON_EMISSION_ROLE][0]["reason"] = "notReviewedYet"

    pin = _resealed_rows(root, edit)
    with pytest.raises(AtlasParquetViewError, match="outside the closed vocabulary"):
        verify_agency_registry_view(root, expected_manifest_digest=pin, release=release)


def test_the_view_refuses_rows_that_are_not_exactly_the_release(release: RegistryMappingRelease) -> None:
    """Pin both equality checks: a bridge or an event the release does not carry is refused, not served."""

    with pytest.raises(ValueError, match="bridge rows are not exactly the release's mappings"):
        agency_projection.build_agency_registry_view(dataclasses.replace(release, mappings=release.mappings[1:]))
    with pytest.raises(ValueError, match="event rows are not exactly the release's change events"):
        agency_projection.build_agency_registry_view(
            dataclasses.replace(release, change_events=release.change_events[1:])
        )


def test_current_successors_of_a_rename_and_a_split(view) -> None:
    """Pin the forward lookup on real events: a rename yields one successor, a split every result."""

    successors = agency_projection.current_agency_successors(view.events)
    assert successors.of(_fr(150)) == {_fr(241)}
    assert successors.of(_fr(564)) == {_fr(409)}
    assert successors.of(_fr(232)) == {_fr(499), _fr(501), _fr(503)}
    assert successors.of(_fr(96)) == {_fr(501), _fr(503)}
    assert successors.of(_fr(510)) == {_fr(41), _fr(476)}


def test_current_successors_walk_a_chain_to_its_end() -> None:
    """Pin a chain -- batch 1 has none, so the rows are synthetic: a split whose one result is renamed later."""

    rows = [
        {"originals": ["urn:ref:test:a"], "result": "urn:ref:test:b"},
        {"originals": ["urn:ref:test:a"], "result": "urn:ref:test:c"},
        {"originals": ["urn:ref:test:b"], "result": "urn:ref:test:d"},
    ]
    successors = agency_projection.current_agency_successors(rows)
    assert successors.of("urn:ref:test:a") == {"urn:ref:test:c", "urn:ref:test:d"}
    assert successors.of("urn:ref:test:b") == {"urn:ref:test:d"}
    with pytest.raises(ValueError, match="cycle"):
        agency_projection.current_agency_successors([*rows, {"originals": ["urn:ref:test:d"], "result": "urn:ref:test:a"}])


def test_current_successors_walk_a_chain_longer_than_the_recursion_limit() -> None:
    """Pin the iterative walk: a 5,000-link chain resolves to its last organization without recursing."""

    rows = [{"originals": [f"urn:ref:test:{index}"], "result": f"urn:ref:test:{index + 1}"} for index in range(5_000)]
    successors = agency_projection.current_agency_successors(rows)
    assert successors.of("urn:ref:test:0") == {"urn:ref:test:5000"}
    assert successors.of("urn:ref:test:4999") == {"urn:ref:test:5000"}


def test_an_unknown_or_undefunct_organization_has_no_successors(view) -> None:
    """Pin that an id no event names as an original -- unknown, or a result still current -- has none."""

    successors = agency_projection.current_agency_successors(view.events)
    assert successors.of("urn:ref:federal-register-agency:999999") == frozenset()
    assert successors.of(_fr(409)) == frozenset()
    assert set(successors.current) == {_fr(fr_id) for fr_id in (96, 150, 232, 259, 404, 510, 543, 559, 564)}
