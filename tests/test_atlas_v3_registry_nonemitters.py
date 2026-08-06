"""Atlas 3 emission coverage for previously descriptor-only sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.atlas import v3_registry_nonemitters as adapters

ROOT = Path(__file__).resolve().parents[1]
REAL_DATA = ROOT / "output" / "registry-real-data-sources"


def test_bounded_subject_sources_emit_every_pinned_concept_without_claiming_completeness() -> None:
    (agrovoc,) = adapters._agrovoc_releases(ROOT)
    (eurovoc,) = adapters._eurovoc_releases(ROOT)
    (lcsh,) = adapters._lcsh_releases(ROOT)

    assert len(agrovoc.resources) == 1
    assert len(eurovoc.resources) == 4
    assert len(lcsh.resources) == 3
    assert all(
        release.scope == "captureSubset" and release.metadata["completePublisherRelease"] is False
        for release in (agrovoc, eurovoc, lcsh)
    )


def test_epa_label_tree_emits_every_row_without_inventing_concept_identity() -> None:
    (release,) = adapters._epa_vocabulary_releases(ROOT)

    assert release.profile == "structureScheme"
    assert release.ring == "value"
    assert len(release.resources) == 3
    assert len(release.relations) == 1
    assert release.metadata["publisherConceptIdentityAvailable"] is False
    assert all(resource.status == "sourcePositionObservation" for resource in release.resources)


def test_gao_cra_emits_every_visible_priority_and_type_value() -> None:
    (release,) = adapters._gao_cra_releases(ROOT)

    assert len(release.resources) == 6
    assert release.metadata["facetNames"] == ("priority", "type")
    assert release.metadata["allVisibleFacetValuesEmitted"] is True


def test_fac_emits_every_distinct_field_as_structure() -> None:
    (release,) = adapters._fac_releases(ROOT)

    assert release.profile == "structureScheme"
    assert len(release.resources) == release.metadata["distinctFieldCount"] == 163
    assert release.metadata["endpointCount"] == 11


@pytest.mark.skipif(
    not (REAL_DATA / "comptox-DTXSID7020182.normalized.html").is_file(),
    reason="bounded public CompTox capture is not present",
)
def test_epa_substance_emits_one_entity_with_all_three_observed_identifiers() -> None:
    (release,) = adapters._epa_substance_releases(ROOT)

    assert release.ring == "entity"
    assert {identifier.value for identifier in release.resources[0].identifiers} == {
        "DTXSID7020182",
        "DTXCID30182",
        "80-05-7",
    }


@pytest.mark.skipif(
    not (REAL_DATA / "fh-orgs-default-page.json").is_file() or not (REAL_DATA / "fh-orgs-sub-tier-page.json").is_file(),
    reason="bounded public Federal Hierarchy captures are not present",
)
def test_federal_hierarchy_emits_all_twenty_organizations_and_only_fh_org_ids() -> None:
    (release,) = adapters._federal_hierarchy_releases(ROOT)

    assert len(release.resources) == 20
    assert len(release.relations) == 2
    assert all(len(resource.identifiers) == 1 for resource in release.resources)
    assert release.metadata["otherPublisherIdentifiersRetainedInNativePayload"] is True


def test_govinfo_emits_identified_package_and_retains_every_fixity_row() -> None:
    (release,) = adapters._govinfo_package_releases(ROOT)

    assert len(release.resources) == 1
    assert release.resources[0].identifiers[0].value == "CFR-2023-title1-vol1"
    assert release.metadata["premisFixityRecordCount"] == 2


def test_nalt_bounded_release_keeps_two_real_core_concepts_and_their_relations() -> None:
    (release,) = adapters._nalt_releases(ROOT)

    assert release.scope == "captureSubset"
    assert {resource.iri for resource in release.resources} == {
        "https://lod.nal.usda.gov/nalt/9084",
        "https://lod.nal.usda.gov/nalt/127295",
    }
    assert len(release.relations) == 2
    assert release.metadata["completePublisherRelease"] is False


def test_nppes_emits_every_field_and_every_bounded_provider_row() -> None:
    layout, providers = adapters._nppes_releases(ROOT)

    assert len(layout.resources) == 330
    assert len(providers.resources) == 3
    assert all(len(resource.native_payload["fields"]) == 330 for resource in providers.resources)
    assert {identifier.value for resource in providers.resources for identifier in resource.identifiers} == {
        "1851806699",
        "1699600866",
        "1669740403",
    }


def test_nrc_emits_observed_controls_and_definitions_without_promoting_examples() -> None:
    controls, shapes = adapters._nrc_releases(ROOT)

    assert len(controls.resources) == 19
    assert controls.scope == "captureSubset"
    assert len(shapes.resources) == 4
    assert shapes.profile == "structureScheme"
    assert all(not resource.identifiers for resource in shapes.resources)
    assert shapes.metadata["identifierInstancesEmitted"] == 0


def test_treasury_emits_every_unique_account_and_retains_the_duplicate_row() -> None:
    accounts, fund_types = adapters._treasury_releases(ROOT)

    assert len(accounts.resources) == 3_581
    assert sum(resource.native_payload["duplicatePublisherRowCount"] for resource in accounts.resources) == 1
    assert len(fund_types.resources) == 11
    assert accounts.metadata["publisherRows"] == 3_582
    assert accounts.metadata["partIMissing"] is True


@pytest.mark.skipif(
    not (REAL_DATA / "sam-entity-3m-public.json").is_file(),
    reason="bounded public SAM capture is not present",
)
def test_sam_emits_separate_uei_and_cage_targets_with_one_native_relation() -> None:
    uei, cage = adapters._sam_releases(ROOT)

    assert len(uei.resources) == len(cage.resources) == 1
    assert uei.resources[0].iri != cage.resources[0].iri
    assert len(cage.relations) == 1
    assert cage.relations[0].object == uei.resources[0].iri
    assert cage.metadata["dlaCageStatusObserved"] is False


@pytest.mark.skipif(
    not (REAL_DATA / "gsdm-data-dictionary-2026-08-03.json").is_file()
    or not (REAL_DATA / "gsdm-architecture-v1.0.1.pdf").is_file(),
    reason="exact GSDM publisher captures are not present",
)
def test_gsdm_emits_all_dictionary_rows_and_reviewed_domain_values() -> None:
    structures, domains = adapters._gsdm_releases(ROOT)

    assert len(structures.resources) == 457
    assert len(domains.resources) == 40
    assert structures.metadata["publisherHeaderCount"] == 17
    assert structures.metadata["publisherRowWidth"] == 18
    assert domains.metadata["allStructuralRowsEmitted"] is True


@pytest.mark.skipif(
    not (REAL_DATA / "sam-entity-3m-public.json").is_file()
    or not (REAL_DATA / "gsdm-data-dictionary-2026-08-03.json").is_file()
    or not (REAL_DATA / "gsdm-architecture-v1.0.1.pdf").is_file(),
    reason="all exact local publisher captures are required for the complete adapter set",
)
def test_complete_nonemitter_adapter_set_emits_4651_resources() -> None:
    releases = adapters.load_registry_nonemitter_releases(ROOT)

    assert len(releases) == 20
    assert sum(len(release.resources) for release in releases) == 4_651
