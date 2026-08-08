from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from refspec.atlas.v3_registry_codes import load_registry_code_releases
from refspec.atlas.v3_source_data import RegistryRelease
from refspec.registry.infrastructure.source_identity import validate_uuid7

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_IRI = re.compile(
    r"^urn:ref:source-concept:v2:(?P<source>[a-z][a-z0-9]*(?:-[a-z0-9]+)*):"
    r"(?P<uuid>[0-9a-f-]{36})$"
)
EXPECTED_RESOURCE_COUNTS = {
    "refspec.registry.billstatus_codes": 132,
    "refspec.registry.census_geo_codes": 24,
    "refspec.registry.census_gov_finance_codes": 56,
    "refspec.registry.fcc_ecfs_codes": 27,
    "refspec.registry.fec_committee_codes": 129,
    "refspec.registry.ferc_elibrary_codes": 342,
    "refspec.registry.govinfo_collections": 92,
    "refspec.registry.grants_gov_codes": 43,
    "refspec.registry.lda_controlled_codes": 129,
    "refspec.registry.nasa_technology_taxonomy": 17,
    "refspec.registry.nature_of_suit_codes": 93,
    "refspec.registry.oira_review_codes": 20,
    "refspec.registry.omb_a11_budget_codes": 144,
    "refspec.registry.oversight_report_types": 10,
    "refspec.registry.pra_icr_codes": 21,
    "refspec.registry.regulations_gov_codes": 10,
    "refspec.registry.regulatory_native_controls": 1_861,
    "refspec.registry.sam_assistance_listing_codes": 134,
    "refspec.registry.sam_opportunities_codes": 34,
    "refspec.registry.scotus_opinion_types": 7,
    "refspec.registry.sec_series_categories": 19,
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


@pytest.fixture(scope="module")
def releases() -> tuple[RegistryRelease, ...]:
    return load_registry_code_releases(ROOT)


def test_loads_every_supported_small_registry_source_at_measured_counts(
    releases: tuple[RegistryRelease, ...],
) -> None:
    counts = Counter()
    for release in releases:
        counts[release.source_module] += len(release.resources)

    assert len(releases) == 67
    assert sum(counts.values()) == 3_426
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
        "census-acs-geography-identifiers",
        "census-tiger-geoid-structure",
        "usgs-gnis-identifiers",
        "fec-committee-designation",
        "fec-committee-type",
        "fec-filing-frequency",
        "fec-organization-type",
        "fec-party",
        "ferc-docket-prefixes",
        "ferc-accession-number-formats",
        "grants-gov-funding-categories",
        "unified-agenda-legal-authority-citation-types",
    }
    value_release_keys.update(
        key for key in by_key if key.startswith("regulatory-native-")
    )

    assert value_release_keys <= by_key.keys()
    assert {by_key[key].ring for key in value_release_keys} == {"value"}


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
    assert by_key["census-acs-geography-identifiers"].scope == "captureSubset"
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
    assert len(by_key["regulatory-native-federal-register-unresolved-agency-name"].resources) == 715
    assert by_key["ferc-docket-prefixes"].resources[0].status in {"active", "discontinued"}
    regulatory_resource = by_key["regulatory-native-federal-register-unresolved-agency-name"].resources[0]
    assert "values" not in regulatory_resource.native_payload["control"]
