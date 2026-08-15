"""Atlas 3 emission coverage for the documented-roster adapter group."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from refspec.atlas import v3_registry_rosters as adapters

ROOT = Path(__file__).resolve().parents[1]


def test_complete_roster_adapter_set_emits_1409_resources() -> None:
    releases = adapters.load_registry_roster_releases(ROOT)

    assert [release.key for release in releases] == [
        "federal-register-documented-document-types-2026-08-15",
        "federal-register-documented-presidential-document-types-2026-08-15",
        "federal-register-agencies-roster-2026-08-15",
        "fcc-bureaus-offices-roster-2026-08-15",
        "federal-hierarchy-orgs-complete-2026-08-15",
    ]
    assert sum(len(release.resources) for release in releases) == 1_409
    assert sum(len(release.relations) for release in releases) == 963
    assert all(release.scope == "completeCapture" for release in releases)
    assert all(not release.cross_ring_relations for release in releases)


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
    (release,) = adapters._federal_hierarchy_releases(ROOT)

    assert release.resource_id == "federal-hierarchy"
    assert release.scheme_iri == "urn:ref:atlas-resource-scheme:federal-hierarchy"
    assert (release.profile, release.ring) == ("codeScheme", "entity")
    assert len(release.resources) == 907
    assert len(release.relations) == 738
    assert release.metadata["departmentOrIndependentAgencyCount"] == 169
    assert release.metadata["subTierCount"] == 738
    assert release.metadata["publisherTypeTotalsWitness"] == {
        "Department/Ind. Agency": 169,
        "Sub-Tier": 738,
    }
    # Seven pinned inputs: five roster pages and two totals witnesses.
    assert len(release.inputs) == 7
    assert [pin.role for pin in release.inputs].count("publisherTotalsWitness") == 2

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

    assert all(relation.predicate == adapters.ATLAS_PARENT_ENTITY for relation in release.relations)
    subjects = {relation.subject for relation in release.relations}
    assert "urn:ref:federal-hierarchy-org:100000000" not in subjects


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
