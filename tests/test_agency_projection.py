"""REF-038 projection parity, abstention, and determinism checks."""

from __future__ import annotations

import dataclasses
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from refspec.atlas import agency_projection
from refspec.atlas import v3_registry_alignments_entity as entity_alignments
from refspec.atlas.parquet_tables import (
    AGENCY_PROJECTION_ROLE,
    AGENCY_PROJECTION_TABLE_NAMES,
    AGENCY_PROJECTION_TABLE_SCHEMAS,
    AGENCY_PROJECTION_UNRESOLVED_ROLE,
    write_agency_projection_tables,
)
from refspec.atlas.parquet_view import (
    AtlasParquetViewError,
    _staged_table_members,
    _verify_agency_projection_content,
)
from refspec.atlas.v3_source_data import RegistryMappingRelease, RegistryRelease
from tools import analyze_agency_roster_identifiers as census

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def releases() -> tuple[RegistryRelease, ...]:
    return census.load_five_agency_rosters(ROOT)


@pytest.fixture(scope="module")
def identity_release(
    releases: tuple[RegistryRelease, ...],
) -> RegistryMappingRelease:
    return entity_alignments.load_regulations_gov_agency_identity_mapping_release(
        releases
    )


@pytest.fixture(scope="module")
def projection(
    releases: tuple[RegistryRelease, ...],
    identity_release: RegistryMappingRelease,
) -> agency_projection.AgencyProjection:
    return agency_projection.build_agency_projection(releases, identity_release)


def test_projection_counts_every_regulations_gov_id(
    projection: agency_projection.AgencyProjection,
) -> None:
    """Pins the exact 331/321/10 coverage counts and per-basis breakdown, the two value sets disjoint."""
    assert len(projection.rows) == 321
    assert len(projection.unresolved) == 10
    assert projection.coverage.to_dict() == {
        "source_value_kind": "regulationsGovAgencyId",
        "source_value_count": 331,
        "resolved_value_count": 321,
        "unresolved_value_count": 10,
        "basis_counts": {
            "acronymExpansionWithNameAndParentContext": 3,
            "ecfrAgencyShortNameEqualsRegulationsGovAgencyId": 8,
            "exactPublisherNameEquality": 27,
            "federalRegisterShortNameEqualsRegulationsGovAgencyId": 271,
            "obviousPublisherNameVariant": 11,
            "publisherNameWithParentContext": 1,
        },
        "unresolved_reason_counts": {"noCounterpartInHeldRosters": 10},
        "rows_with_parent_org": 159,
        "evidence_record_count": 321,
    }
    assert {row.source_value for row in projection.rows}.isdisjoint(
        row.source_value for row in projection.unresolved
    )


def test_projection_is_exactly_graph_assertions_plus_metadata_abstentions(
    projection: agency_projection.AgencyProjection,
    identity_release: RegistryMappingRelease,
) -> None:
    """Pins rows equal to the mapping's graph assertions and unresolved rows equal to its metadata abstentions."""
    assertion_pairs = {
        (mapping.subject, mapping.predicate, mapping.object)
        for mapping in identity_release.mappings
    }
    projected_pairs = {
        (
            row.evidence_records[0].source_record.resource,
            row.relation,
            row.org,
        )
        for row in projection.rows
    }
    abstentions = {
        row["sourceValue"]
        for row in identity_release.metadata["candidateDecisions"]
        if row["decision"] == "abstained"
    }

    assert projected_pairs == assertion_pairs
    assert {row.source_value for row in projection.unresolved} == abstentions
    assert len(assertion_pairs) + len(abstentions) == 331


def test_every_projection_row_cites_the_mapping_release_decision(
    projection: agency_projection.AgencyProjection,
) -> None:
    """Pins each row's single E4/humanReview/approved evidence record, its REF-038 citation and no confidence field."""
    for row in projection.rows:
        assert len(row.evidence_records) == 1
        evidence = row.evidence_records[0]
        assert evidence.evidence_tier == row.evidence_tier == "E4"
        assert evidence.warrant == row.warrant == "humanReview"
        assert evidence.decision == "approved"
        assert evidence.decision_basis == row.basis
        assert evidence.decision_record == "docs/decisions.md#ref-038"
        assert evidence.name_similarity_used is False
        assert evidence.reasoning
        assert evidence.source_record.publisher_name
        assert evidence.target_record.publisher_name
        assert evidence.target_record.resource == row.org
        assert evidence.relation == row.relation == agency_projection.ATLAS_SAME_ENTITY_AS
        assert evidence.record_id.startswith("urn:ref:agency-projection-evidence:")
        assert "confidence" not in str(row.to_dict()).lower()


def test_residue_adoptions_include_fs_disambiguation_and_parent_context(
    projection: agency_projection.AgencyProjection,
) -> None:
    """Pins the FS, USDAIG and MEXICO residue adoptions to their exact target URNs, bases and reasoning."""
    by_value = {row.source_value: row for row in projection.rows}

    forest_service = by_value["FS"]
    assert forest_service.org == "urn:ref:federal-register-agency:209"
    assert forest_service.basis == "publisherNameWithParentContext"
    assert "not Fiscal Service" in forest_service.evidence_records[0].reasoning

    usda_ig = by_value["USDAIG"]
    assert usda_ig.org == "urn:ref:federal-hierarchy-org:100006936"
    assert usda_ig.basis == "acronymExpansionWithNameAndParentContext"
    assert usda_ig.evidence_records[0].source_record.publisher_name == (
        "Inspector General Office, Agriculture Department"
    )
    assert usda_ig.evidence_records[0].target_record.publisher_name == (
        "OFFICE OF INSPECTOR GENERAL"
    )

    mexico = by_value["MEXICO"]
    assert mexico.org == (
        "urn:ref:ecfr-agency:international-boundary-and-water-commission-"
        "united-states-and-mexico"
    )


def test_true_abstentions_and_closest_candidates_project_from_metadata(
    projection: agency_projection.AgencyProjection,
) -> None:
    """Pins the ten frozen abstention values and the closest-candidate metadata projected for BSC, MMA and USC."""
    by_value = {row.source_value: row for row in projection.unresolved}
    assert set(by_value) == {
        "ARCTICGAS",
        "BSC",
        "EOA",
        "GAPFAC",
        "MMA",
        "NCRIRS",
        "OIRA",
        "PCSCOTUS",
        "PRES",
        "USC",
    }
    assert all(row.reason == "noCounterpartInHeldRosters" for row in by_value.values())
    assert by_value["BSC"].closest_non_adopted_candidate is None
    assert by_value["MMA"].closest_non_adopted_candidate == {
        "resource": "urn:ref:federal-register-agency:289",
        "publisherName": "Minerals Management Service",
        "reason": "predecessor organization, not the same roster entity",
    }
    assert by_value["USC"].candidate_resources == (
        "urn:ref:federal-register-agency:3",
    )


def test_projection_refuses_missing_mapping_basis_or_evidence(
    projection: agency_projection.AgencyProjection,
) -> None:
    """Pins that a projection row constructed without a basis or without evidence records raises ValueError."""
    row = projection.rows[0]
    with pytest.raises(ValueError, match="requires a basis"):
        dataclasses.replace(row, basis="")
    with pytest.raises(ValueError, match="requires evidence"):
        dataclasses.replace(row, evidence_records=())


def test_projection_is_input_order_independent(
    releases: tuple[RegistryRelease, ...],
) -> None:
    """Pins that reversing release, resource and relation order rebuilds an identical projection and digest."""
    reordered = tuple(
        dataclasses.replace(
            release,
            resources=tuple(reversed(release.resources)),
            relations=tuple(reversed(release.relations)),
        )
        for release in reversed(releases)
    )
    identity = entity_alignments.load_regulations_gov_agency_identity_mapping_release(
        reordered
    )
    rebuilt = agency_projection.build_agency_projection(reordered, identity)
    canonical_releases = census.load_five_agency_rosters(ROOT)
    canonical_identity = (
        entity_alignments.load_regulations_gov_agency_identity_mapping_release(
            canonical_releases
        )
    )
    canonical = agency_projection.build_agency_projection(
        canonical_releases,
        canonical_identity,
    )

    assert rebuilt == canonical
    assert rebuilt.digest == canonical.digest


def test_projection_rejects_metadata_adoption_without_graph_assertion(
    releases: tuple[RegistryRelease, ...],
    identity_release: RegistryMappingRelease,
) -> None:
    """Pins that an adopted metadata decision with no matching graph assertion raises ValueError."""
    changed = dataclasses.replace(
        identity_release,
        mappings=identity_release.mappings[:-1],
    )
    with pytest.raises(ValueError, match="without an assertion"):
        agency_projection.build_agency_projection(releases, changed)


def _projection_manifest_metadata(
    projection: agency_projection.AgencyProjection,
) -> dict[str, object]:
    """Build the emitted agencyProjection manifest block the parquet content verifier expects."""
    return {
        "status": "emitted",
        "decision": "REF-038",
        "digest": projection.digest,
        "coverage": projection.coverage.to_dict(),
    }


def test_projection_parquet_schema_counts_and_bytes_are_deterministic(
    tmp_path: Path,
    projection: agency_projection.AgencyProjection,
    releases: tuple[RegistryRelease, ...],
) -> None:
    """Pins arrow schemas, exact per-role row counts and byte-identical parquet across input orders."""
    first = tmp_path / "first"
    write_agency_projection_tables(first, projection)

    reordered = tuple(
        dataclasses.replace(
            release,
            resources=tuple(reversed(release.resources)),
            relations=tuple(reversed(release.relations)),
        )
        for release in reversed(releases)
    )
    mapping = entity_alignments.load_regulations_gov_agency_identity_mapping_release(
        reordered
    )
    rebuilt = agency_projection.build_agency_projection(reordered, mapping)
    second = tmp_path / "second"
    write_agency_projection_tables(second, rebuilt)

    expected_counts = {
        AGENCY_PROJECTION_ROLE: 321,
        AGENCY_PROJECTION_UNRESOLVED_ROLE: 10,
    }
    for role, expected_count in expected_counts.items():
        name = AGENCY_PROJECTION_TABLE_NAMES[role]
        first_path = first / "tables" / name
        second_path = second / "tables" / name
        parquet = pq.ParquetFile(first_path)
        assert parquet.schema_arrow == AGENCY_PROJECTION_TABLE_SCHEMAS[role]
        assert parquet.metadata.num_rows == expected_count
        assert first_path.read_bytes() == second_path.read_bytes()
    _verify_agency_projection_content(
        first,
        {"agencyProjection": _projection_manifest_metadata(projection)},
    )


def test_projection_parquet_refuses_partial_pair_and_mutated_evidence(
    tmp_path: Path,
    projection: agency_projection.AgencyProjection,
) -> None:
    """Pins refusal when only one of the resolved/unresolved tables is staged, or reasoning evidence is blanked."""
    staged = tmp_path / "staged"
    write_agency_projection_tables(staged, projection)
    unresolved = (
        staged
        / "tables"
        / AGENCY_PROJECTION_TABLE_NAMES[AGENCY_PROJECTION_UNRESOLVED_ROLE]
    )
    unresolved.unlink()
    with pytest.raises(AtlasParquetViewError, match="must be emitted together"):
        _staged_table_members(staged)

    mutated = tmp_path / "mutated"
    write_agency_projection_tables(mutated, projection)
    resolved_path = (
        mutated
        / "tables"
        / AGENCY_PROJECTION_TABLE_NAMES[AGENCY_PROJECTION_ROLE]
    )
    rows = pq.read_table(resolved_path).to_pylist()
    rows[0]["evidence_records"][0]["reasoning"] = ""
    pq.write_table(
        pa.Table.from_pylist(
            rows,
            schema=AGENCY_PROJECTION_TABLE_SCHEMAS[AGENCY_PROJECTION_ROLE],
        ),
        resolved_path,
    )
    with pytest.raises(AtlasParquetViewError, match="mapping evidence differs"):
        _verify_agency_projection_content(
            mutated,
            {"agencyProjection": _projection_manifest_metadata(projection)},
        )


@pytest.mark.parametrize("field", ["coverage", "digest"])
def test_projection_parquet_refuses_changed_manifest_metadata(
    tmp_path: Path,
    projection: agency_projection.AgencyProjection,
    field: str,
) -> None:
    """Pins refusal when the manifest coverage or its sha256 logical-content digest differs from the projection."""
    write_agency_projection_tables(tmp_path, projection)
    metadata = _projection_manifest_metadata(projection)
    if field == "coverage":
        coverage = dict(projection.coverage.to_dict())
        coverage["rows_with_parent_org"] += 1
        metadata["coverage"] = coverage
        match = "coverage differs"
    else:
        metadata["digest"] = "sha256:" + "0" * 64
        match = "logical-content digest differs"
    with pytest.raises(AtlasParquetViewError, match=match):
        _verify_agency_projection_content(
            tmp_path,
            {"agencyProjection": metadata},
        )


def _projection_of(
    rows: list[agency_projection.AgencyProjectionRow],
    unresolved: list[agency_projection.AgencyProjectionUnresolvedRow],
) -> agency_projection.AgencyProjection:
    """Assemble a valid projection, coverage and digest included, from chosen real rows."""
    coverage = agency_projection.AgencyProjectionCoverage(
        source_value_kind="regulationsGovAgencyId",
        source_value_count=len(rows) + len(unresolved),
        resolved_value_count=len(rows),
        unresolved_value_count=len(unresolved),
        basis_counts=dict(Counter(row.basis for row in rows)),
        unresolved_reason_counts=dict(Counter(row.reason for row in unresolved)),
        rows_with_parent_org=sum(row.parent_org is not None for row in rows),
        evidence_record_count=len(rows),
    )
    content = {
        "rows": [row.to_dict() for row in rows],
        "unresolved": [row.to_dict() for row in unresolved],
        "coverage": coverage.to_dict(),
    }
    return agency_projection.AgencyProjection(
        rows=tuple(rows),
        unresolved=tuple(unresolved),
        coverage=coverage,
        digest=agency_projection._digest(content),
    )


FR_OFFICE = "urn:ref:ecfr-agency:federal-register-office"
EPA_ORG = "urn:ref:federal-register-agency:145"
MMS_ORG = "urn:ref:federal-register-agency:289"


def test_reverse_projection_resolves_only_a_target_one_code_selects(
    projection: agency_projection.AgencyProjection,
) -> None:
    """Pins one-to-one reversal, many-to-one as ambiguous and absent, and unresolved rows adding nothing."""
    rows = {row.source_value: row for row in projection.rows}
    abstentions = {row.source_value: row for row in projection.unresolved}
    # MMA abstains naming MMS's organization as its closest candidate: were
    # unresolved rows counted, that organization would turn ambiguous.
    assert abstentions["MMA"].candidate_resources == (MMS_ORG,)
    chosen = [rows[code] for code in ("EPA", "FR", "MMS", "OFR")]
    unresolved = [abstentions["MMA"], abstentions["USC"]]

    reverse = agency_projection.reverse_agency_projection(_projection_of(chosen, unresolved))
    again = agency_projection.reverse_agency_projection(
        _projection_of(chosen[::-1], unresolved[::-1])
    )

    assert list(reverse.resolved.items()) == [(EPA_ORG, "EPA"), (MMS_ORG, "MMS")]
    assert list(reverse.ambiguous.items()) == [(FR_OFFICE, ("FR", "OFR"))]
    assert reverse.resolved.get(FR_OFFICE) is None
    assert list(again.resolved.items()) == list(reverse.resolved.items())
    assert list(again.ambiguous.items()) == list(reverse.ambiguous.items())
    with pytest.raises(TypeError):
        reverse.resolved[FR_OFFICE] = "FR"  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        reverse.ambiguous = {}  # type: ignore[misc]


@pytest.mark.parametrize(
    ("resolved", "ambiguous", "match"),
    [
        ({FR_OFFICE: "FR"}, {FR_OFFICE: ("FR", "OFR")}, "resolves an ambiguous"),
        ({}, {FR_OFFICE: ("FR",)}, "one code selects"),
    ],
)
def test_reverse_projection_refuses_a_contradictory_reading(
    resolved: dict[str, str],
    ambiguous: dict[str, tuple[str, ...]],
    match: str,
) -> None:
    """Pins refusal of an organization both resolved and ambiguous, or ambiguous on a single code."""
    with pytest.raises(ValueError, match=match):
        agency_projection.AgencyReverseProjection(resolved=resolved, ambiguous=ambiguous)


def test_reverse_projection_of_the_real_projection(
    projection: agency_projection.AgencyProjection,
) -> None:
    """Pins 311 of 321 codes reversible and the five organizations two codes each select."""
    reverse = agency_projection.reverse_agency_projection(projection)

    assert len(reverse.resolved) == 311
    assert dict(reverse.ambiguous) == {
        FR_OFFICE: ("FR", "OFR"),
        "urn:ref:federal-register-agency:184": ("FPPO", "OFPP"),
        "urn:ref:federal-register-agency:225": ("ACHP", "HPAC"),
        "urn:ref:federal-register-agency:78": ("CDFI", "CDFIF"),
        "urn:ref:federal-register-agency:91": ("CNCS", "CORP"),
    }
    assert len(reverse.resolved) + sum(map(len, reverse.ambiguous.values())) == 321
    assert list(reverse.resolved) == sorted(reverse.resolved)
    assert list(reverse.ambiguous) == sorted(reverse.ambiguous)


def test_every_reversible_pair_round_trips(
    projection: agency_projection.AgencyProjection,
) -> None:
    """Pins that each resolved organization's code projects back onto it and every row lands exactly once."""
    reverse = agency_projection.reverse_agency_projection(projection)
    org_by_code = {row.source_value: row.org for row in projection.rows}

    assert all(org_by_code[code] == org for org, code in reverse.resolved.items())
    for row in projection.rows:
        in_resolved = reverse.resolved.get(row.org) == row.source_value
        in_ambiguous = row.source_value in reverse.ambiguous.get(row.org, ())
        assert in_resolved != in_ambiguous, row.source_value
    reversed_codes = [*reverse.resolved.values(), *(c for cs in reverse.ambiguous.values() for c in cs)]
    assert sorted(reversed_codes) == sorted(org_by_code)
    assert {row.source_value for row in projection.unresolved}.isdisjoint(reversed_codes)
