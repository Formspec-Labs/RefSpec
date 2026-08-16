"""REF-038 projection parity, abstention, and determinism checks."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from refspec.atlas import agency_projection
from refspec.atlas import v3_registry_alignments_entity as entity_alignments
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
    row = projection.rows[0]
    with pytest.raises(ValueError, match="requires a basis"):
        dataclasses.replace(row, basis="")
    with pytest.raises(ValueError, match="requires evidence"):
        dataclasses.replace(row, evidence_records=())


def test_projection_is_input_order_independent(
    releases: tuple[RegistryRelease, ...],
) -> None:
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
    changed = dataclasses.replace(
        identity_release,
        mappings=identity_release.mappings[:-1],
    )
    with pytest.raises(ValueError, match="without an assertion"):
        agency_projection.build_agency_projection(releases, changed)
