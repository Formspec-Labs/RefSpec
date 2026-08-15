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
    "refspec.registry.unified_agenda_codes": 49,
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
    # sample.
    assert len(releases) == 44
    assert sum(counts.values()) == 1_505
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
    assert by_key["unified-agenda-rule-stage"].scope == "captureSubset"
    assert by_key["unified-agenda-legal-authority-citation-types"].scope == (
        "captureSubset"
    )
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
