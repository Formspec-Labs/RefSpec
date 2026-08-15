from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from refspec.atlas import v3_registry_codes as codes
from refspec.atlas.v3_registry_codes import load_registry_code_releases
from refspec.atlas.v3_source_data import RegistryRelease
from refspec.registry.infrastructure.source_identity import validate_uuid7

ROOT = Path(__file__).resolve().parents[1]
# Every code release pins bytes under this gitignored capture tree. Absent is
# not drift: a clean clone has no captures, and a missing-file error there says
# nothing about the code these tests cover.
REAL_DATA = ROOT / "output" / "registry-real-data-sources"
RESOURCE_IRI = re.compile(
    r"^urn:ref:source-concept:v2:(?P<source>[a-z][a-z0-9]*(?:-[a-z0-9]+)*):"
    r"(?P<uuid>[0-9a-f-]{36})$"
)
EXPECTED_RESOURCE_COUNTS = {
    "refspec.registry.billstatus_codes": 132,
    # 11 GEOID structure rows + the complete 21-field GNIS National File
    # layout; the ACS sample and the three example GEOIDs left (REF-032).
    "refspec.registry.census_geo_codes": 32,
    # The NASBO program-area chapter titles left (REF-032).
    "refspec.registry.census_gov_finance_codes": 49,
    "refspec.registry.fec_committee_codes": 129,
    "refspec.registry.ferc_elibrary_codes": 340,
    # Two pinned revisions of GAO Form 41217: the current revision's five
    # rule types and the retired revision's five dropped priority levels.
    "refspec.registry.gao_cra_form_codes": 10,
    "refspec.registry.govinfo_collections": 92,
    "refspec.registry.grants_gov_codes": 43,
    "refspec.registry.lda_controlled_codes": 129,
    "refspec.registry.nasa_technology_taxonomy": 17,
    "refspec.registry.nature_of_suit_codes": 93,
    "refspec.registry.oira_review_codes": 20,
    "refspec.registry.omb_a11_budget_codes": 144,
    "refspec.registry.oversight_report_types": 10,
    # 10 request types + 5 ICR statuses; the burden-range form widgets and
    # the OMB number field shape left the emission (REF-032).
    "refspec.registry.pra_icr_codes": 15,
    "refspec.registry.regulations_gov_codes": 10,
    "refspec.registry.sam_assistance_listing_codes": 134,
    "refspec.registry.sam_opportunities_codes": 34,
    # All 20 documented option lists of the pinned reginfo XSD (110 values)
    # plus the 3 RISC Preamble legal-authority citation types.
    "refspec.registry.unified_agenda_codes": 113,
    "refspec.registry.usaspending_gsdm_codes": 33,
}
PROFILE_BY_RESOURCE_KIND = {
    "classification": "codeScheme",
    "codeList": "codeScheme",
    "historicalVocabulary": "conceptScheme",
    "identifierAuthority": "identifierScheme",
    "mappingReference": "conceptScheme",
    "resourceFamily": "resourceCollection",
    "sourceAssignedVocabulary": "conceptScheme",
    "structuralSchema": "structureScheme",
    "subjectVocabulary": "conceptScheme",
}


def test_code_adapter_keeps_variant_tagged_label_and_deduplicates_twin() -> None:
    items = codes._bundle_items(
        (
            {
                "identifiers": (),
                "labels": (
                    {"language": "en", "role": "preferred", "value": "Code"},
                    {
                        "language": "en-US",
                        "role": "preferred",
                        "value": "Code",
                    },
                ),
                "sourcePath": "publisher.json#code=1",
            },
            {
                "identifiers": (),
                "labels": (
                    {
                        "language": "en-GB",
                        "role": "preferred",
                        "value": "Variant code",
                    },
                ),
                "sourcePath": "publisher.json#code=2",
            },
        ),
        key="test-codes",
    )

    assert [item.label for item in items] == ["Code", "Variant code"]


@pytest.fixture(scope="module")
def releases() -> tuple[RegistryRelease, ...]:
    if not REAL_DATA.is_dir():
        pytest.skip("pinned registry code sources are not present: output/registry-real-data-sources")
    return load_registry_code_releases(ROOT)


def test_loads_every_supported_small_registry_source_at_measured_counts(
    releases: tuple[RegistryRelease, ...],
) -> None:
    counts = Counter()
    for release in releases:
        counts[release.source_module] += len(release.resources)

    # 67 before REF-031, when the FCC ECFS proceedings population left for
    # SpicyRegs; 66 before REF-032, when the fourteen regulatory-native
    # inventories, the three remaining ECFS observations, and the FERC
    # "accession number formats" left as observed inventories; 48 before the
    # REF-032 repair pass removed the NASBO chapter titles, the SCOTUS
    # sidebar labels, the SEC sidenav categories, and the ACS variables
    # sample; 44 before the Unified Agenda's remaining 17 documented option
    # lists and the two GAO Form 41217 lists landed.
    assert len(releases) == 63
    assert sum(counts.values()) == 1_579
    assert dict(counts) == EXPECTED_RESOURCE_COUNTS
    assert all(not release.relations for release in releases)


def test_releases_use_catalog_resource_ids_profiles_rings_and_scheme_iris(
    releases: tuple[RegistryRelease, ...],
) -> None:
    catalog = json.loads((ROOT / "portfolio/resource-catalog-v0.json").read_text())
    catalog_by_id = {row["resourceId"]: row for row in catalog["resources"]}
    atlas_index = json.loads((ROOT / "portfolio/atlas-index-v0.json").read_text())
    allowed_rings: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in atlas_index["rows"]:
        allowed_rings[(row["sourceModule"], row["resourceId"])].add(row["semanticRing"])

    for release in releases:
        catalog_row = catalog_by_id[release.resource_id]
        assert release.profile == PROFILE_BY_RESOURCE_KIND[catalog_row["resourceKind"]]
        assert release.ring in allowed_rings[(release.source_module, release.resource_id)]
        assert release.scheme_iri == f"urn:ref:atlas-resource-scheme:{release.resource_id}"


def test_field_values_formats_and_code_domains_use_the_value_ring(
    releases: tuple[RegistryRelease, ...],
) -> None:
    by_key = {release.key: release for release in releases}
    value_release_keys = {
        "census-tiger-geoid-structure",
        "usgs-gnis-identifiers",
        "fec-committee-designation",
        "fec-committee-type",
        "fec-filing-frequency",
        "fec-organization-type",
        "fec-party",
        "ferc-docket-prefixes",
        "grants-gov-funding-categories",
        "unified-agenda-legal-authority-citation-types",
        # Repaired under the REF-032 pass: filer-selected filing codes and a
        # publisher technology-area code roster are value-ring code lists,
        # not subject concept schemes.
        "lda-general-issue-codes",
        "nasa-technology-taxonomy-8817",
    }

    assert value_release_keys <= by_key.keys()
    assert {by_key[key].ring for key in value_release_keys} == {"value"}
    assert by_key["lda-general-issue-codes"].profile == "codeScheme"
    assert by_key["nasa-technology-taxonomy-8817"].profile == "codeScheme"
    # The TX technology-area codes ride as notations on the NASA roster.
    assert any(
        notation.startswith("TX")
        for resource in by_key["nasa-technology-taxonomy-8817"].resources
        for notation in resource.notations
    )


def test_resources_have_english_labels_readable_uuid7_ids_and_exact_provenance(
    releases: tuple[RegistryRelease, ...],
) -> None:
    iris: set[str] = set()
    for release in releases:
        date.fromisoformat(release.issued)
        assert len(release.issued) == 10
        for resource in release.resources:
            match = RESOURCE_IRI.fullmatch(resource.iri)
            assert match is not None
            validate_uuid7(match.group("uuid"))
            assert resource.iri not in iris
            iris.add(resource.iri)
            assert len([label for label in resource.labels if label.role == "preferred"]) == 1
            assert {label.language for label in resource.labels} == {"en"}
            assert resource.source_locator.startswith(("https://", "urn:"))
            assert re.fullmatch(r"sha256:[0-9a-f]{64}", resource.source_digest)


def test_release_build_is_repeatable(releases: tuple[RegistryRelease, ...]) -> None:
    repeated = load_registry_code_releases(ROOT)
    identity = tuple(
        (
            release.key,
            release.resource_id,
            release.source_release_digest,
            tuple(resource.iri for resource in release.resources),
        )
        for release in releases
    )
    repeated_identity = tuple(
        (
            release.key,
            release.resource_id,
            release.source_release_digest,
            tuple(resource.iri for resource in release.resources),
        )
        for release in repeated
    )
    assert repeated_identity == identity


def test_input_pins_fail_closed_on_digest_drift(releases: tuple[RegistryRelease, ...]) -> None:
    source = releases[0].inputs[0]
    drifted = replace(source, sha256="sha256:" + "0" * 64)

    with pytest.raises(ValueError, match="pinned input differs"):
        drifted.verify()


def test_normalized_native_payloads_are_immutable(
    releases: tuple[RegistryRelease, ...],
) -> None:
    payload = releases[0].resources[0].native_payload

    with pytest.raises(TypeError):
        payload["unexpected"] = True  # type: ignore[index]


def test_scoped_and_non_enumerative_sources_are_not_overclaimed(
    releases: tuple[RegistryRelease, ...],
) -> None:
    by_key = {release.key: release for release in releases}

    assert by_key["billstatus-action-codes"].scope == "captureSubset"
    assert by_key["nasa-technology-taxonomy-8817"].scope == "captureSubset"
    assert by_key["census-tiger-geoid-structure"].scope == "captureSubset"
    assert by_key["usgs-gnis-identifiers"].scope == "captureSubset"
    assert by_key["omb-a11-functional-classification"].scope == "captureSubset"
    # With all 20 documented option lists emitted, the schema family claims
    # completeCapture; the hand-transcribed Preamble citation types stay a
    # captureSubset, as do the two GAO form lists (the forms carry other
    # option lists this unit deliberately does not emit).
    assert by_key["unified-agenda-rule-stage"].scope == "completeCapture"
    assert by_key["unified-agenda-legal-authority-citation-types"].scope == (
        "captureSubset"
    )
    assert by_key["gao-cra-rule-types"].scope == "captureSubset"
    assert by_key["gao-cra-priority-of-regulation"].scope == "captureSubset"
    assert {pin.role for pin in by_key["omb-a11-functional-classification"].inputs} == {
        "publisherSource",
        "publisherPdfTextExtraction",
    }
    assert {pin.role for pin in by_key["uscourts-nature-of-suit"].inputs} == {
        "publisherSource",
        "publisherPdfTextExtraction",
    }
    assert by_key["ferc-docket-prefixes"].resources[0].status in {"active", "discontinued"}


def test_ferc_class_types_emit_type_description_labels_with_recovered_columns(
    releases: tuple[RegistryRelease, ...],
) -> None:
    release = next(release for release in releases if release.key == "ferc-document-class-types")

    assert len(release.resources) == 235
    for resource in release.resources:
        payload = resource.native_payload
        # The display label is the publisher's Type Description column, and
        # the recovered Category/Library/Classification structure plus the
        # exact extracted line travel in the native payload.
        assert resource.labels[0].value == payload["type_description"]
        assert payload["category"] in {"Issuance", "Submittal"}
        assert payload["library"]
        assert payload["classification"]
        assert payload["text"].startswith(f"{payload['category']} {payload['library']} ")
        assert payload["text"].endswith(payload["type_description"])
        assert payload["sourceMedium"] == "pdf"
    labels = {resource.labels[0].value for resource in release.resources}
    assert "ALJ Initial Decision/Certification of Initial Decision and Record" in labels
    # No resource carries the flat space-joined line as its label.
    assert not any(
        resource.labels[0].value.startswith(("Issuance ", "Submittal "))
        for resource in release.resources
    )


def test_tiger_geoid_structure_emits_only_the_published_composition_rows(
    releases: tuple[RegistryRelease, ...],
) -> None:
    release = next(release for release in releases if release.key == "census-tiger-geoid-structure")

    assert len(release.resources) == 11
    assert release.profile == "identifierScheme"
    # The three example GEOIDs (kind tigerGeoidExampleValue, e.g. Kent
    # County, Delaware) left under REF-032: example values, not vocabulary.
    kinds = {
        identifier["kind"]
        for resource in release.resources
        for identifier in resource.native_payload["identifiers"]
    }
    assert kinds == {"tigerGeoidComposition"}
    assert not any(
        notation.startswith("0500000US")
        for resource in release.resources
        for notation in resource.notations
    )
    # IRI stability: identity seeds on (resourceId, sourceArtifact, sourcePath,
    # identifiers), never on bundle position, so subtracting the example rows
    # must not re-mint the kept eleven. Three sampled pins hold that claim.
    kept = {resource.iri for resource in release.resources}
    assert {
        "urn:ref:source-concept:v2:census-tiger-geoid:019fc915-3c80-7312-89f4-dc856a0c4b63",
        "urn:ref:source-concept:v2:census-tiger-geoid:019fc915-3c80-7383-98cb-944083ea5dbe",
        "urn:ref:source-concept:v2:census-tiger-geoid:019fc915-3c80-74bc-a6bd-fde50d00c239",
    } <= kept


def test_gnis_release_is_the_complete_national_file_layout_in_publisher_words(
    releases: tuple[RegistryRelease, ...],
) -> None:
    release = next(release for release in releases if release.key == "usgs-gnis-identifiers")

    assert release.profile == "structureScheme"
    assert len(release.resources) == 21
    by_field = {resource.notations[0]: resource for resource in release.resources}
    assert by_field["feature_id"].labels[0].value == "feature_id"
    assert by_field["feature_id"].definition == (
        "Permanent, unique feature record identifier. See Appendix 3, number 1."
    )
    # Every field carries the publisher's description cell; merged cells are
    # shared verbatim with the group recorded, never paraphrased in
    # RefSpec's own words.
    assert all(resource.definition for resource in release.resources)
    assert by_field["state_numeric"].native_payload["descriptionSharedWithFields"] == (
        "state_name",
        "state_numeric",
    )
    assert "Two-digit code for the state" not in (by_field["state_numeric"].definition or "")
    assert "Three-digit code for the county" not in (by_field["county_numeric"].definition or "")
    assert all(resource.native_payload["sourceMedium"] == "pdf" for resource in release.resources)


def test_pra_release_emits_publisher_codes_without_form_mechanics(
    releases: tuple[RegistryRelease, ...],
) -> None:
    release = next(release for release in releases if release.key == "pra-icr-controls")

    assert len(release.resources) == 15
    kinds = {
        identifier["kind"]
        for resource in release.resources
        for identifier in resource.native_payload["identifiers"]
    }
    assert kinds == {"requestTypeCode", "icrStatusCode"}
    labels = {resource.labels[0].value for resource in release.resources}
    assert "OMB Control Number" not in labels
    assert not any(label.endswith(":") for label in labels)


def test_unified_agenda_family_emits_every_documented_option_list(
    releases: tuple[RegistryRelease, ...],
) -> None:
    """REF-032's captureSubset claim (3 of 20 lists) is retired: the family
    now emits one completeCapture release per documented option list, and the
    reader's pinned census (exactly 20 blocks) is echoed in every release."""

    schema_releases = [
        release
        for release in releases
        if release.resource_id == "unified-agenda-native-controls"
    ]

    assert len(schema_releases) == 20
    assert {release.key for release in schema_releases} == {
        "unified-agenda-agency-relation",
        "unified-agenda-dline-action-stage",
        "unified-agenda-dline-type",
        "unified-agenda-energy-affected",
        "unified-agenda-eo13771-designation",
        "unified-agenda-federalism",
        "unified-agenda-govt-level",
        "unified-agenda-international-interest",
        "unified-agenda-major",
        "unified-agenda-print-paper",
        "unified-agenda-priority-category",
        "unified-agenda-rfa-required",
        "unified-agenda-rfa-section610-review",
        "unified-agenda-rin-relation",
        "unified-agenda-rin-status",
        "unified-agenda-rplan-entry",
        "unified-agenda-rule-stage",
        "unified-agenda-small-entity",
        "unified-agenda-timetable-action",
        "unified-agenda-unfunded-mandate",
    }
    assert sum(len(release.resources) for release in schema_releases) == 110
    for release in schema_releases:
        assert release.scope == "completeCapture"
        assert release.metadata["xsdDocumentedOptionListCount"] == 20
        assert release.metadata["familyEmitsEveryDocumentedOptionList"] is True

    by_key = {release.key: release for release in schema_releases}
    counts = {key: len(release.resources) for key, release in by_key.items()}
    assert counts == {
        "unified-agenda-agency-relation": 2,
        "unified-agenda-dline-action-stage": 5,
        "unified-agenda-dline-type": 4,
        "unified-agenda-energy-affected": 3,
        "unified-agenda-eo13771-designation": 6,
        "unified-agenda-federalism": 3,
        "unified-agenda-govt-level": 6,
        "unified-agenda-international-interest": 3,
        "unified-agenda-major": 3,
        "unified-agenda-print-paper": 3,
        "unified-agenda-priority-category": 6,
        "unified-agenda-rfa-required": 3,
        "unified-agenda-rfa-section610-review": 4,
        "unified-agenda-rin-relation": 5,
        "unified-agenda-rin-status": 2,
        "unified-agenda-rplan-entry": 2,
        "unified-agenda-rule-stage": 6,
        "unified-agenda-small-entity": 6,
        "unified-agenda-timetable-action": 34,
        "unified-agenda-unfunded-mandate": 4,
    }
    # Sampled publisher wording, exactly as documented.
    assert [r.labels[0].value for r in by_key["unified-agenda-rin-relation"].resources] == [
        "Merge with",
        "Split from",
        "Previously reported as",
        "Duplicate of",
        "Related to",
    ]
    assert [r.labels[0].value for r in by_key["unified-agenda-agency-relation"].resources] == [
        "Joint",
        "Common",
    ]
    assert [r.labels[0].value for r in by_key["unified-agenda-govt-level"].resources] == [
        "State",
        "Local",
        "Tribal",
        "Federal",
        "None",
        "Undetermined",
    ]


def test_unified_agenda_successor_releases_state_their_ref_032_provenance(
    releases: tuple[RegistryRelease, ...],
) -> None:
    """MAJOR and RIN_STATUS are the documented successors of observed twins
    deleted under REF-032; the successor statement must travel in metadata."""

    by_key = {release.key: release for release in releases}

    major = by_key["unified-agenda-major"]
    assert [resource.labels[0].value for resource in major.resources] == [
        "Yes",
        "No",
        "Undetermined",
    ]
    assert "REF-032" in major.metadata["observedTwinSuccessorNote"]
    assert "distinct-value scan" in major.metadata["observedTwinSuccessorNote"]

    rin_status = by_key["unified-agenda-rin-status"]
    # The XSD's sentence-case wording, verbatim: the live export's casing
    # drift is a known publisher-side issue recorded in SpicyRegs.
    assert [resource.labels[0].value for resource in rin_status.resources] == [
        "First time published in the Unified Agenda",
        "Previously published in the Unified Agenda",
    ]
    assert "REF-032" in rin_status.metadata["observedTwinSuccessorNote"]
    assert "casing" in rin_status.metadata["publisherCasingNote"]

    # No other schema release claims the successor note.
    claimants = {
        release.key
        for release in releases
        if "observedTwinSuccessorNote" in release.metadata
    }
    assert claimants == {"unified-agenda-major", "unified-agenda-rin-status"}


def test_gao_cra_releases_carry_both_form_revisions_honestly(
    releases: tuple[RegistryRelease, ...],
) -> None:
    by_key = {release.key: release for release in releases}

    rule_types = by_key["gao-cra-rule-types"]
    assert [resource.labels[0].value for resource in rule_types.resources] == [
        "Draft Rule",
        "Final Rule",
        "Draft Guideline",
        "Final Guideline",
        "Other",
    ]
    assert rule_types.resources[-1].native_payload["optionText"] == "Other (specify)"
    assert all(
        resource.native_payload["sourceMedium"] == "pdf"
        for resource in rule_types.resources
    )
    assert all(resource.status == "active" for resource in rule_types.resources)
    assert rule_types.metadata["formRevision"] == "Rev. 12/24"
    # The publisher's own URL typo is preserved, and named in metadata.
    assert "Sumission" in rule_types.inputs[0].source_iri
    assert "Sumission" in rule_types.metadata["publisherUrlTypo"]

    priority = by_key["gao-cra-priority-of-regulation"]
    assert [resource.labels[0].value for resource in priority.resources] == [
        "Economically Significant",
        "Significant",
        "Substantive, Nonsignificant",
        "Routine and Frequent",
        "Informational/Administrative/Other",
    ]
    # The retired revision is the last publisher statement of the list: every
    # member is retired, the metadata says the current form dropped the item,
    # and the current form's bytes are pinned as an input so the claim is
    # re-verified on every load.
    assert all(resource.status == "retired" for resource in priority.resources)
    assert priority.metadata["formRevision"] == "11/17/23"
    assert "Rev. 12/24" in priority.metadata["droppedByCurrentRevision"]
    assert "last publisher statement" in priority.metadata["droppedByCurrentRevision"]
    assert {pin.role for pin in priority.inputs} == {
        "publisherRetiredRevision",
        "publisherSource",
    }
    # The "; or" joiners stay in the printed option text, never in the value.
    assert priority.resources[0].native_payload["optionText"] == "Economically Significant; or"
    assert not priority.resources[0].labels[0].value.endswith("; or")


def test_new_releases_pass_the_ref_032_guards_and_mint_no_identifier_rows(
    releases: tuple[RegistryRelease, ...],
) -> None:
    """The REF-032 refusal surfaces name the deleted GAO CRA facet scheme
    (``urn:ref:gao-cra-facet:``) and fixtures path
    (``tests/fixtures/gao_cra_facets/``). The fresh units must pass all three
    refusal guards under their new naming, and -- because no declared catalog
    authority backs GAO CRA or the Unified Agenda schema fields -- must mint
    no authority-scoped identifier rows at all: publisher values travel as
    notations and payload fields only."""

    import importlib
    import sys
    from types import SimpleNamespace

    sys.path.insert(0, str(ROOT / "tools"))
    generator = importlib.import_module("generate_atlas_v3_full")

    new_keys = {
        release.key
        for release in releases
        if release.key.startswith(("gao-cra-", "unified-agenda-"))
    }
    assert len(new_keys) == 23
    for release in releases:
        if release.key not in new_keys:
            continue
        loaded = SimpleNamespace(
            spec=SimpleNamespace(
                key=release.key,
                logical_path=release.inputs[0].logical_path,
                input_pins=release.inputs,
            ),
            scheme_iri=release.scheme_iri,
            resources=release.resources,
        )
        generator._refuse_registrant_population_release(loaded)
        generator._refuse_document_population_release(loaded)
        generator._refuse_observed_inventory_release(loaded)
        # The identifier-authority tripwire, held at the source: no release in
        # this adapter mints RegistryIdentifier rows.
        assert all(not resource.identifiers for resource in release.resources)
        assert not release.scheme_iri.startswith(
            generator.OBSERVED_INVENTORY_SCHEME_PREFIXES
        )
        for pin in release.inputs:
            assert not pin.logical_path.startswith("tests/fixtures/gao_cra_facets/")


def test_govinfo_collections_emit_codes_and_names_without_holdings_counts(
    releases: tuple[RegistryRelease, ...],
) -> None:
    release = next(release for release in releases if release.key == "govinfo-collections")

    assert len(release.resources) == 42
    for resource in release.resources:
        assert "packageCount" not in resource.native_payload
        assert "granuleCount" not in resource.native_payload
        assert resource.notations
    names = {resource.labels[0].value for resource in release.resources}
    assert "Code of Federal Regulations" in names
