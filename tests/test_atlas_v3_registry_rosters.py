"""Atlas 3 emission coverage for the documented-roster adapter group."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from refspec.atlas import v3_registry_rosters as adapters
from refspec.registry import cfr_list_of_subjects as cfr

ROOT = Path(__file__).resolve().parents[1]


def test_complete_roster_adapter_set_emits_native_relations_and_two_cross_ring_carriers() -> None:
    releases = adapters.load_registry_roster_releases(ROOT)

    assert [release.key for release in releases] == [
        "federal-register-documented-document-types-2026-08-15",
        "federal-register-documented-presidential-document-types-2026-08-15",
        "federal-register-agencies-roster-2026-08-15",
        "fcc-bureaus-offices-roster-2026-08-15",
        "federal-hierarchy-orgs-complete-2026-08-15",
        "ecfr-agencies-roster-2026-08-15",
        "cfr-subject-index-parts-2026-08-20",
        "regulations-gov-agencies-roster-2026-08-16",
        "gao-published-topics-index-2026-08-15",
    ]
    assert sum(len(release.resources) for release in releases) == 10_509
    assert sum(len(release.relations) for release in releases) == 86_748
    assert all(release.scope == "completeCapture" for release in releases)
    # Two carriers now, one per admitted cross-ring cell that a publisher
    # actually writes down: eCFR's agency -> CFR title references, and the
    # OFR's CFR part -> subject index terms.
    assert {release.key: len(release.cross_ring_relations) for release in releases if release.cross_ring_relations} == {
        "ecfr-agencies-roster-2026-08-15": 446,
        "cfr-subject-index-parts-2026-08-20": adapters.CFR_SUBJECT_INDEX_EXPECTED_CROSS_RING_RELATIONS,
    }


def test_federal_register_document_types_are_a_value_ring_code_release() -> None:
    types, subtypes, _agencies = adapters._federal_register_releases(ROOT)

    assert types.resource_id == "federal-register-native-controls"
    assert (types.profile, types.ring) == ("codeScheme", "value")
    assert types.scheme_iri == (
        "urn:ref:atlas-resource-scheme:federal-register-native-controls:documented-document-types"
    )
    assert [resource.iri for resource in types.resources] == [
        "urn:ref:federal-register-document-type:RULE",
        "urn:ref:federal-register-document-type:PRORULE",
        "urn:ref:federal-register-document-type:NOTICE",
        "urn:ref:federal-register-document-type:PRESDOCU",
    ]
    assert [resource.labels[0].value for resource in types.resources] == [
        "Rule",
        "Proposed Rule",
        "Notice",
        "Presidential Document",
    ]
    assert types.metadata["documentedTypeCount"] == 4
    assert types.metadata["facetDocumentCountsAtCapture"]["NOTICE"] == 765_082

    assert len(subtypes.resources) == 7
    assert subtypes.metadata["parentDocumentType"] == "PRESDOCU"
    assert subtypes.scheme_iri.endswith(":documented-presidential-document-types")


def test_federal_register_agencies_carry_publisher_ids_and_parent_relations() -> None:
    _types, _subtypes, agencies = adapters._federal_register_releases(ROOT)

    assert (agencies.profile, agencies.ring) == ("codeScheme", "entity")
    assert len(agencies.resources) == 472
    assert len(agencies.relations) == 225
    # The slug/enum equality is enforced by crosscheck_documented_agency_slugs
    # raising during load; the metadata records the count it verified.
    assert agencies.metadata["documentedAgencyEnumCount"] == 472

    by_iri = {resource.iri: resource for resource in agencies.resources}
    fcc = by_iri["urn:ref:federal-register-agency:161"]
    assert fcc.labels[0].value == "Federal Communications Commission"
    assert {label.value for label in fcc.labels if label.role == "alternate"} == {"FCC"}
    # The publisher's id and slug travel as notations and verbatim payload
    # fields; no authority-scoped identifier rows are minted because this
    # resource is not a declared identifier authority.
    assert fcc.notations == ("federal-communications-commission", "161")
    assert fcc.identifiers == ()
    assert fcc.native_payload["id"] == 161
    assert fcc.native_payload["slug"] == "federal-communications-commission"

    fda_parent = [
        relation
        for relation in agencies.relations
        if relation.subject == "urn:ref:federal-register-agency:199"
    ]
    assert len(fda_parent) == 1
    assert fda_parent[0].predicate == adapters.ATLAS_PARENT_ENTITY
    assert fda_parent[0].object == "urn:ref:federal-register-agency:221"


def test_fcc_roster_replaces_the_observed_bureau_inventory() -> None:
    (release,) = adapters._fcc_releases(ROOT)

    assert release.resource_id == "fcc-ecfs-native-controls"
    assert (release.profile, release.ring) == ("codeScheme", "entity")
    assert release.scheme_iri == (
        "urn:ref:atlas-resource-scheme:fcc-ecfs-native-controls:published-bureaus-offices"
    )
    assert release.metadata["officeCount"] == 12
    assert release.metadata["bureauCount"] == 7
    assert len(release.resources) == 19

    by_iri = {resource.iri: resource for resource in release.resources}
    space = by_iri["urn:ref:fcc-organizational-unit:space"]
    assert space.labels[0].value == "Space"
    # recordStatus is a lifecycle field, not a taxonomy: the office/bureau kind
    # rides in the native payload only.
    assert space.status is None
    assert space.native_payload["kind"] == "bureau"
    assert not any("Common Carrier" in resource.labels[0].value for resource in release.resources)


def test_federal_hierarchy_release_is_the_complete_entity_roster() -> None:
    from refspec.atlas import v3_registry_nonemitters as nonemitters

    (release,) = adapters._federal_hierarchy_releases(ROOT)
    treasury_accounts = nonemitters._treasury_releases(ROOT)[0]

    assert release.resource_id == "federal-hierarchy"
    assert release.scheme_iri == "urn:ref:atlas-resource-scheme:federal-hierarchy"
    assert (release.profile, release.ring) == ("codeScheme", "entity")
    assert len(release.resources) == 907
    assert len(release.relations) == 86_200
    assert release.metadata["departmentOrIndependentAgencyCount"] == 169
    assert release.metadata["subTierCount"] == 738
    assert release.metadata["publisherTypeTotalsWitness"] == {
        "Department/Ind. Agency": 169,
        "Sub-Tier": 738,
    }
    # Eight pinned inputs: five roster pages, two totals witnesses, and the
    # exact Treasury workbook used for the publisher-code join.
    assert len(release.inputs) == 8
    assert [pin.role for pin in release.inputs].count("publisherTotalsWitness") == 2
    assert release.inputs[-1].role == "publisherCgacJoinSource"

    by_iri = {resource.iri: resource for resource in release.resources}
    dod = by_iri["urn:ref:federal-hierarchy-org:100000000"]
    assert dod.labels[0].value == "DEPT OF DEFENSE"
    # The FPDS/CGAC codes the API republishes belong to authorities the
    # catalog does not carry, so they travel verbatim in the payload rather
    # than as authority-scoped identifier rows; fhorgid is the notation.
    assert dod.identifiers == ()
    assert dod.notations == ("100000000",)
    assert [item["cgac"] for item in dod.native_payload["cgaclist"]] == ["097", "096", "017", "021", "057"]

    testing_dept = by_iri["urn:ref:federal-hierarchy-org:500021729"]
    assert testing_dept.native_payload["agencycode"] == ""
    anomalies = release.metadata["publisherAnomalies"]
    assert anomalies["emptyAgencyCodeRecords"][0]["fhorgname"] == "Testing DEPT"

    parent_relations = [
        relation for relation in release.relations if relation.predicate == adapters.ATLAS_PARENT_ENTITY
    ]
    cgac_relations = [relation for relation in release.relations if relation.predicate == adapters.ATLAS_RELATED_ENTITY]
    assert len(parent_relations) == 738
    assert len(cgac_relations) == adapters.FH_TREASURY_EXPECTED_RELATED_ENTITY_RELATIONS
    assert len({(relation.subject, relation.predicate, relation.object) for relation in cgac_relations}) == len(
        cgac_relations
    )
    assert {relation.subject for relation in cgac_relations} <= {resource.iri for resource in release.resources}
    assert {relation.object for relation in cgac_relations} < {resource.iri for resource in treasury_accounts.resources}
    assert "urn:ref:federal-hierarchy-org:100000000" not in {relation.subject for relation in parent_relations}
    dod_accounts = [
        relation for relation in cgac_relations if relation.subject == "urn:ref:federal-hierarchy-org:100000000"
    ]
    assert {relation.source_payload["cgacAgencyIdentifier"] for relation in dod_accounts} == {
        "017",
        "021",
        "057",
        "096",
        "097",
    }
    assert all(relation.source_payload["identityEquivalenceClaimed"] is False for relation in dod_accounts)
    assert all(relation.source_payload["administrationClaimed"] is False for relation in dod_accounts)
    assert release.metadata["cgacJoin"] == {
        "sharedCgacAgencyIdentifierCount": 130,
        "treasuryAccountRowCount": 3_544,
        "distinctTreasuryAccountSymbolCount": 3_543,
        "federalHierarchyOrganizationCount": 874,
        "predicate": adapters.ATLAS_RELATED_ENTITY,
        "identityEquivalenceClaimed": False,
        "administrationClaimed": False,
        "relationMeaning": (
            "Each assertion states only that its endpoints share a publisher-reported CGAC Agency Identifier."
        ),
    }
    assert release.metadata["licenseRightsStatements"] == {
        "federalHierarchy": "US federal public domain (17 USC 105) with no explicit CC license",
        "treasuryFastBook": "US federal public domain (17 USC 105) with no explicit CC license",
    }
    assert len(release.metadata["sourceCaptures"]) == 8
    assert all(
        {"sourceUrl", "retrievedAt", "sha256", "byteLength", "sourceVersionNote"} == set(capture)
        for capture in release.metadata["sourceCaptures"]
    )


def test_ecfr_agencies_are_an_entity_roster_with_directed_cfr_title_relations(
    tmp_path: Path,
) -> None:
    from refspec.atlas import v3_registry_codes as code_adapters

    (release,) = adapters._ecfr_agency_releases(ROOT)
    held_titles = next(item for item in code_adapters._load_govinfo(ROOT, tmp_path) if item.key == "ecfr-cfr-titles")

    assert release.key == "ecfr-agencies-roster-2026-08-15"
    assert release.resource_id == "ecfr-agencies"
    assert release.scheme_iri == "urn:ref:atlas-resource-scheme:ecfr-agencies"
    assert (release.profile, release.ring) == ("codeScheme", "entity")
    assert len(release.resources) == 316
    assert len(release.relations) == 163
    assert len(release.cross_ring_relations) == 446
    assert (
        len({(relation.subject, relation.predicate, relation.object) for relation in release.cross_ring_relations})
        == 446
    )
    assert {relation.predicate for relation in release.cross_ring_relations} == {
        adapters.ATLAS_REFERENCES_LEGAL_IDENTITY
    }
    assert {(relation.source_ring, relation.target_ring) for relation in release.cross_ring_relations} == {
        ("entity", "legalIdentity")
    }
    assert len({relation.subject for relation in release.cross_ring_relations}) == 315
    assert all(
        relation.subject.startswith("urn:ref:ecfr-agency:")
        for relation in release.cross_ring_relations
    )
    assert len({relation.object for relation in release.cross_ring_relations}) == 49
    assert {relation.object for relation in release.cross_ring_relations} < {
        resource.iri for resource in held_titles.resources
    }
    assert sum(len(relation.source_payload["publisherReferences"]) for relation in release.cross_ring_relations) == 487
    duplicate_reference = next(
        relation
        for relation in release.cross_ring_relations
        if relation.subject == "urn:ref:ecfr-agency:foreign-service-impasse-disputes-panel"
        and relation.source_payload["cfrTitle"] == 22
    )
    assert duplicate_reference.source_payload["publisherReferences"] == (
        {"sourceOrdinal": 0, "title": 22, "chapter": "XIV", "subchapter": "B"},
        {"sourceOrdinal": 1, "title": 22, "chapter": "XIV", "subchapter": "D"},
    )
    assert all(relation.predicate == adapters.ATLAS_PARENT_ENTITY for relation in release.relations)

    by_iri = {resource.iri: resource for resource in release.resources}
    ams = by_iri["urn:ref:ecfr-agency:agricultural-marketing-service"]
    assert ams.labels[0].value == "Agricultural Marketing Service, Department of Agriculture"
    assert ams.notations == ("agricultural-marketing-service",)
    assert ams.identifiers == ()
    assert ams.native_payload["parentAgencySlug"] == "agriculture-department"

    assert release.metadata["publisherCfrReferenceCount"] == 487
    assert release.metadata["referencedAgencyCount"] == 315
    assert release.metadata["referencedTitleCount"] == 49
    assert release.metadata["crossRingPredicate"] == adapters.ATLAS_REFERENCES_LEGAL_IDENTITY
    assert release.metadata["licenseRightsStatement"] == (
        "US federal public domain (17 USC 105) with no explicit CC license"
    )
    assert "zero-cross-ring tripwire must be retired" in release.metadata["ref032CrossRingTripwireRetirement"]
    assert "unversioned" in release.metadata["sourceCaptures"][0]["sourceVersionNote"]
    assert release.metadata["nameMatchingRefused"].startswith("No eCFR agency was matched by name")


def test_cfr_subject_index_release_is_a_legal_identity_structure_release() -> None:
    """CFR parts are legal identities, one structural level below CFR titles.

    The held `ecfr-cfr-structure` release carries the fifty CFR titles. Until
    now the Atlas held no CFR part at all: the OFR's per-part index existed
    only as a research CSV. These 8,423 parts are the same kind of thing the
    titles are, sourced from the publisher that writes the index.
    """

    (release,) = adapters._cfr_subject_index_releases(ROOT)

    assert release.key == "cfr-subject-index-parts-2026-08-20"
    assert release.resource_id == "cfr-subject-index"
    assert (release.profile, release.ring) == ("structureScheme", "legalIdentity")
    assert release.scope == "completeCapture"
    assert release.scheme_iri == "urn:ref:atlas-resource-scheme:cfr-subject-index"
    assert len(release.resources) == cfr.CFR_SUBJECT_INDEX_EXPECTED_PART_COUNT
    assert release.relations == ()

    by_iri = {resource.iri: resource for resource in release.resources}
    part = by_iri["urn:ref:cfr-part:40:52"]
    assert part.labels[0].value == "Approval and promulgation of implementation plans"
    assert part.notations == ("40 CFR Part 52",)
    assert part.native_payload["cfrTitle"] == 40
    assert part.native_payload["cfrPart"] == "52"
    assert "Air pollution control" in part.native_payload["publisherIndexTerms"]


def test_cfr_subject_index_pins_every_page_it_reads() -> None:
    """Fifty publisher pages plus the target-vocabulary witness, all pinned."""

    (release,) = adapters._cfr_subject_index_releases(ROOT)

    roles = [pin.role for pin in release.inputs]
    assert roles.count("publisherSubjectIndexPage") == cfr.CFR_SUBJECT_INDEX_EXPECTED_PAGE_COUNT
    assert roles.count("targetVocabularyWitness") == 1
    assert all(pin.sha256.startswith("sha256:") and pin.byte_length > 0 for pin in release.inputs)
    assert {pin.source_iri for pin in release.inputs if pin.role == "publisherSubjectIndexPage"} == {
        cfr.CFR_SUBJECT_INDEX_URL_TEMPLATE.format(title=title) for title in range(1, 51)
    }
    for pin in release.inputs:
        pin.verify()


def test_cfr_part_subject_links_are_the_legal_identity_to_subject_crossing() -> None:
    """The second admitted cross-ring cell gets its first real carrier.

    REF-032 refused the cross-ring instance it found because it was "one
    document's own page metadata read twice". This is the opposite shape: an
    authority publishes subject assignments against a structural identity it
    does not own the vocabulary of, revised annually, for every CFR part.
    """

    (release,) = adapters._cfr_subject_index_releases(ROOT)
    relations = release.cross_ring_relations

    assert len(relations) == adapters.CFR_SUBJECT_INDEX_EXPECTED_CROSS_RING_RELATIONS
    assert {relation.predicate for relation in relations} == {adapters.ATLAS_HAS_INDEXED_SUBJECT}
    assert {(relation.source_ring, relation.target_ring) for relation in relations} == {
        ("legalIdentity", "subject")
    }
    assert all(relation.subject.startswith("urn:ref:cfr-part:") for relation in relations)
    assert all(
        relation.object.startswith("urn:ref:source-concept:v2:federal-register-api:") for relation in relations
    )
    assert len({(relation.subject, relation.object) for relation in relations}) == len(relations)


def test_cfr_subject_index_terms_resolve_to_held_concepts_and_never_mint_one() -> None:
    """The governed number: 863 terms resolve, 205 are skipped and counted.

    1 CFR 18.20 requires index terms drawn from the Federal Register Thesaurus
    but permits agency-added terms, so a residue is expected. Every unresolved
    term stays a publisher string on its part and produces no relation; none
    of them becomes a concept.
    """

    (release,) = adapters._cfr_subject_index_releases(ROOT)
    resolution = release.metadata["termResolution"]

    assert resolution["targetRelease"] == "federal-register-api-topics-2026-08-03"
    assert resolution["targetScheme"] == "urn:ref:atlas-resource-scheme:federal-register-api-topics"
    assert resolution["conceptIdentityMinted"] is False
    assert resolution["resolvedTermCount"] == adapters.CFR_SUBJECT_INDEX_EXPECTED_RESOLVED_TERMS
    assert resolution["unresolvedTermCount"] == adapters.CFR_SUBJECT_INDEX_EXPECTED_UNRESOLVED_TERMS
    assert len(resolution["unresolvedTerms"]) == adapters.CFR_SUBJECT_INDEX_EXPECTED_UNRESOLVED_TERMS
    assert (
        resolution["resolvedAssignmentCount"] + resolution["unresolvedAssignmentCount"]
        == adapters.CFR_SUBJECT_INDEX_EXPECTED_DISTINCT_ASSIGNMENTS
    )
    assert resolution["resolvedAssignmentCount"] == len(release.cross_ring_relations)

    unresolved = set(resolution["unresolvedTerms"])
    linked_terms = {relation.source_payload["publisherTerm"] for relation in release.cross_ring_relations}
    assert unresolved.isdisjoint(linked_terms)
    # A skipped term is not a dropped term: it stays on the part verbatim.
    carried = {
        term
        for resource in release.resources
        for term in resource.native_payload.get("unresolvedIndexTerms", ())
    }
    assert carried == unresolved


def test_agency_departure_from_the_controlled_vocabulary_is_measured_not_asserted() -> None:
    """1 CFR 18.20's compliance rate, as a check rather than as prose.

    The regulation requires index terms drawn from the Federal Register
    Thesaurus and permits agency-added ones, so the residue measures how far
    agencies actually depart. `research/evidence/cfr-subject-index-2026-08-20/`
    states these shares; this is what makes them fail when they move.
    """

    import json

    (release,) = adapters._cfr_subject_index_releases(ROOT)
    terms = {term for resource in release.resources for term in resource.native_payload["publisherIndexTerms"]}
    extract = json.loads(
        (ROOT / "src/refspec/resources/federal_register_thesaurus/2025-04-01/source-extract.json").read_text(
            encoding="utf-8"
        )
    )
    thesaurus = {row["label"].casefold() for row in extract["officialTerms"]}
    api_resolved = set(terms) - set(release.metadata["termResolution"]["unresolvedTerms"])
    thesaurus_resolved = {term for term in terms if term.casefold() in thesaurus}

    assert len(terms) == cfr.CFR_SUBJECT_INDEX_EXPECTED_TERM_COUNT == 1_068
    assert len(api_resolved) == 863
    assert len(thesaurus_resolved) == 713
    assert len(api_resolved | thesaurus_resolved) == 869
    assert len(terms - (api_resolved | thesaurus_resolved)) == 199


def test_cfr_parts_the_publisher_lists_twice_become_one_merged_resource() -> None:
    """Three parts appear twice in the publisher's own pages.

    Minting a second resource would split one legal identity in two; dropping
    the second entry would lose terms. The adapter merges the term lists in
    publisher order and records the duplication on the resource.
    """

    (release,) = adapters._cfr_subject_index_releases(ROOT)
    by_iri = {resource.iri: resource for resource in release.resources}

    merged = by_iri["urn:ref:cfr-part:7:1000"]
    assert merged.native_payload["publisherListedPartTwice"] is True
    assert merged.native_payload["publisherIndexTerms"] == (
        "Milk marketing orders",
        "Reporting and recordkeeping requirements",
    )
    assert [row["cfrTitle"] for row in release.metadata["duplicatePublisherPartEntries"]] == [7, 29, 48]
    assert release.metadata["publisherPartEntryCount"] - len(release.resources) == 3


def test_regulations_gov_agencies_are_an_entity_roster_with_pinned_parents() -> None:
    (release,) = adapters._regulations_gov_agency_releases(ROOT)

    assert release.key == "regulations-gov-agencies-roster-2026-08-16"
    assert release.resource_id == "regulations-gov-native-controls"
    assert release.scheme_iri == (
        "urn:ref:atlas-resource-scheme:regulations-gov-native-controls:agencies"
    )
    assert (release.profile, release.ring) == ("codeScheme", "entity")
    assert len(release.resources) == 331
    assert len(release.relations) == 160
    assert all(relation.predicate == adapters.ATLAS_PARENT_ENTITY for relation in release.relations)

    by_iri = {resource.iri: resource for resource in release.resources}
    abmc = by_iri["urn:ref:regulations-gov-agency:ABMC"]
    assert abmc.labels[0].value == "American Battle Monuments Commission"
    assert abmc.notations == ("ABMC",)
    assert abmc.identifiers == ()
    assert abmc.native_payload == {
        "id": "ABMC",
        "type": "agencies",
        "parent": None,
        "participate": False,
        "partner": False,
        "postingGuidelines": None,
        "name": "American Battle Monuments Commission",
        "agencyType": "Federal",
        "links": {"self": "https://api.regulations.gov/v4/agencies/ABMC"},
    }

    whd_parent = [
        relation
        for relation in release.relations
        if relation.subject == "urn:ref:regulations-gov-agency:WHD"
    ]
    assert len(whd_parent) == 1
    assert whd_parent[0].object == "urn:ref:regulations-gov-agency:DOL"
    assert whd_parent[0].source_payload == {
        "sourceProperty": "attributes.parent",
        "childAgencyId": "WHD",
        "parentAgencyId": "DOL",
    }

    assert release.metadata["agencyCount"] == 331
    assert release.metadata["parentRelationCount"] == 160
    assert release.metadata["distinctParentAgencyCount"] == 17
    assert release.metadata["undocumentedEndpoint"] is True
    assert "recapture" in release.metadata["recaptureObligation"].lower()
    assert release.metadata["apiKeyRequirement"] == {
        "environmentVariable": "REGULATIONS_GOV_API_KEY",
        "requestHeader": "X-Api-Key",
        "keyValueIncluded": False,
    }
    assert release.metadata["licenseRightsStatement"] == (
        "US federal public domain (17 USC 105) with no explicit CC license"
    )
    assert release.metadata["sourceCaptures"] == (
        {
            "sourceUrl": "https://api.regulations.gov/v4/agencies",
            "retrievedAt": "2026-08-16T04:53:51Z",
            "sha256": (
                "sha256:28ab9f5422dd27fc7906ddc696e8e7811b11056822f370bcee7ea18a28418fa2"
            ),
            "byteLength": 91_408,
            "sourceVersionNote": (
                "The publisher exposes this as a rolling, unversioned endpoint; "
                "the pinned digest detects drift."
            ),
        },
    )


def test_gao_topics_release_is_a_subject_ring_concept_scheme() -> None:
    (release,) = adapters._gao_releases(ROOT)

    assert release.resource_id == "gao-topics"
    # The bare scheme, exactly as REF-032's guard commentary blesses for a
    # documented successor of the removed observed unit.
    assert release.scheme_iri == "urn:ref:atlas-resource-scheme:gao-topics"
    assert (release.profile, release.ring) == ("conceptScheme", "subject")
    assert release.scope == "completeCapture"
    assert len(release.resources) == 30
    assert release.relations == ()
    assert not release.cross_ring_relations
    assert release.metadata["topicCount"] == 30
    assert release.metadata["listingTitle"] == "Browse Topics Alphabetically"
    assert release.metadata["excludedFeaturedEntryCount"] == 4
    assert "Akamai" in release.metadata["transportNote"]
    assert "zyte_transport" in release.metadata["transportNote"]

    by_iri = {resource.iri: resource for resource in release.resources}
    health = by_iri["urn:ref:gao-topic:health-care"]
    assert health.labels[0].value == "Health Care"
    assert health.definition is not None and health.definition.startswith("Health care services")
    # Publisher slug and taxonomy term id ride as notations and payload,
    # never as identifier rows: gao-topics is not a declared identifier
    # authority (the identifier-authority tripwire covers this at suite time).
    assert health.notations == ("health-care", "206")
    assert health.identifiers == ()
    assert health.native_payload["term_id"] == "206"
    assert health.native_payload["page_url"] == "https://www.gao.gov/topics/health-care"

    mission = by_iri["urn:ref:gao-topic:gao-mission-and-operations"]
    assert mission.native_payload["term_id"] == "896"


def test_roster_releases_pass_the_generator_refusal_guards() -> None:
    """Run the build's three refusal guards over the real emitted releases.

    REF-030 (registrant populations), REF-031 (document populations), and
    REF-032 (observed inventories) each install a refusal in
    tools/generate_atlas_v3_full.py. The GAO release is the sensitive one:
    its substrate must not collide with the refused
    ``tests/fixtures/gao_topics/`` observation path, its bare scheme is the
    blessed documented-successor scheme, and its IRIs must stay clear of the
    refused ``https://www.gao.gov/products/`` document-population namespace.
    This test runs the actual guard functions, not copies of their lists.
    """

    import importlib
    import sys

    sys.path.insert(0, str(ROOT / "tools"))
    try:
        generator = importlib.import_module("generate_atlas_v3_full")
    finally:
        sys.path.remove(str(ROOT / "tools"))

    for release in adapters.load_registry_roster_releases(ROOT):
        shaped = SimpleNamespace(
            spec=SimpleNamespace(
                key=release.key,
                logical_path=release.inputs[0].logical_path,
                input_pins=tuple(
                    SimpleNamespace(logical_path=pin.logical_path) for pin in release.inputs
                ),
            ),
            scheme_iri=release.scheme_iri,
            resources=tuple(SimpleNamespace(iri=resource.iri) for resource in release.resources),
        )
        generator._refuse_registrant_population_release(shaped)
        generator._refuse_document_population_release(shaped)
        generator._refuse_observed_inventory_release(shaped)


def test_roster_loader_parses_only_intersecting_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def fake_group(names: tuple[str, ...]) -> Any:
        def loader(_root: Path) -> tuple[Any, ...]:
            called.append(names[0])
            return tuple(SimpleNamespace(key=name) for name in names)

        return loader

    monkeypatch.setattr(
        adapters,
        "_federal_register_releases",
        fake_group(
            (
                "federal-register-documented-document-types-2026-08-15",
                "federal-register-documented-presidential-document-types-2026-08-15",
                "federal-register-agencies-roster-2026-08-15",
            )
        ),
    )
    monkeypatch.setattr(adapters, "_fcc_releases", fake_group(("fcc-bureaus-offices-roster-2026-08-15",)))
    monkeypatch.setattr(
        adapters,
        "_federal_hierarchy_releases",
        fake_group(("federal-hierarchy-orgs-complete-2026-08-15",)),
    )
    monkeypatch.setattr(adapters, "_gao_releases", fake_group(("gao-published-topics-index-2026-08-15",)))

    releases = adapters.load_registry_roster_releases(
        Path("/pinned"),
        only_keys={"fcc-bureaus-offices-roster-2026-08-15"},
    )

    assert [release.key for release in releases] == ["fcc-bureaus-offices-roster-2026-08-15"]
    assert called == ["fcc-bureaus-offices-roster-2026-08-15"]


def test_roster_loader_refuses_unknown_keys() -> None:
    with pytest.raises(ValueError, match="does not know release keys"):
        adapters.load_registry_roster_releases(ROOT, only_keys={"not-a-roster-release"})


def test_emitted_identifier_schemes_are_atlas_identifier_authorities() -> None:
    """Identifier rows must claim schemes the build recognizes, at suite time.

    ``_validate_compiled_producer_rows`` in tools/generate_atlas_v3_full.py
    refuses any ``RegistryIdentifier`` whose scheme is not a ResourceScheme
    the registry descriptors profile as ``identifierScheme`` -- but that
    check lives 110 seconds into a full build. This test computes the exact
    same authority set from the same descriptor graph and validates every
    identifier the roster group and the treasury nonemitter (the one adapter
    that legitimately mints identifier rows) emit, so an unregistered scheme
    fails the suite, not the build.
    """

    from rdflib import RDF, Dataset, Namespace, URIRef

    from refspec.atlas import v3_registry_nonemitters as nonemitters

    atlas = Namespace("https://refspec.org/ns/atlas/v3#")
    dataset = Dataset()
    dataset.parse(
        ROOT / "bindings" / "atlas" / "3.1" / "tests" / "registry-descriptors.nq",
        format="nquads",
    )
    graph = dataset.graph(URIRef("urn:ref:atlas-v3:registry-descriptors"))
    authorities = {
        str(subject)
        for subject in graph.subjects(atlas.resourceProfile, atlas.identifierScheme)
        if (subject, RDF.type, atlas.ResourceScheme) in graph
    }
    # The set must be real, or this test could pass vacuously against a
    # missing or renamed descriptor artifact.
    assert "urn:ref:atlas-resource-scheme:treasury-account-symbol-structure" in authorities

    releases = [
        *adapters.load_registry_roster_releases(ROOT),
        *nonemitters.load_registry_nonemitter_releases(
            ROOT,
            only_keys={"treasury-fast-book-accounts-parts-ii-iii-2026-07"},
        ),
    ]
    identifier_rows = 0
    for release in releases:
        for resource in release.resources:
            for identifier in resource.identifiers:
                identifier_rows += 1
                assert identifier.scheme_iri in authorities, (
                    f"{release.key}/{resource.iri} identifier scheme is not an "
                    f"Atlas identifier authority: {identifier.scheme_iri}"
                )
    # The treasury release keeps this check exercised on real identifier rows.
    assert identifier_rows > 0
