"""Asserted regulations.gov agency identity release checks."""

from __future__ import annotations

import dataclasses
import importlib
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rdflib.namespace import RDF

from refspec.atlas import v3_registry_alignments_entity as alignments
from refspec.atlas.v3_source_data import RegistryMappingRelease, RegistryRelease
from tools import analyze_agency_roster_identifiers as census

ROOT = Path(__file__).resolve().parents[1]


def _generator_module():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        return importlib.import_module("generate_atlas_v3_full")
    finally:
        sys.path.remove(str(ROOT / "tools"))


def _contains_confidence_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            "confidence" in str(key).lower()
            or _contains_confidence_key(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return any(_contains_confidence_key(item) for item in value)
    return False


@pytest.fixture(scope="module")
def releases() -> tuple[RegistryRelease, ...]:
    return census.load_five_agency_rosters(ROOT)


@pytest.fixture(scope="module")
def mapping_release(
    releases: tuple[RegistryRelease, ...],
) -> RegistryMappingRelease:
    return alignments.load_regulations_gov_agency_identity_mapping_release(
        releases
    )


def test_identity_release_counts_and_closed_decision_vocabulary(
    mapping_release: RegistryMappingRelease,
) -> None:
    assert mapping_release.key == (
        "regulations-gov-agency-identity-2026-08-16"
    )
    assert mapping_release.ring == "entity"
    assert len(mapping_release.mappings) == 321
    assert mapping_release.metadata["adoptedAssertionCount"] == 321
    assert mapping_release.metadata["abstentionCount"] == 10
    assert mapping_release.metadata["candidateDecisionCount"] == 331
    assert mapping_release.metadata["evidenceRecordCount"] == 642
    assert mapping_release.metadata["inverseAssertionCount"] == 0
    assert mapping_release.metadata["subunitPredicateEmitted"] is False
    decisions = mapping_release.metadata["candidateDecisions"]
    assert len({row["sourceValue"] for row in decisions}) == 331
    assert {
        row["basis"] for row in decisions if row["decision"] == "adopted"
    } <= alignments.AGENCY_DECISION_BASES
    assert {
        row["reason"] for row in decisions if row["decision"] == "abstained"
    } <= alignments.AGENCY_ABSTENTION_REASONS


def test_every_assertion_is_one_way_same_entity_e4_human_review(
    mapping_release: RegistryMappingRelease,
) -> None:
    triples = {
        (mapping.subject, mapping.predicate, mapping.object)
        for mapping in mapping_release.mappings
    }
    assert len(triples) == 321
    assert all(
        predicate == alignments.ATLAS_SAME_ENTITY_AS
        for _subject, predicate, _object in triples
    )
    assert all(
        (object_iri, predicate, subject_iri) not in triples
        for subject_iri, predicate, object_iri in triples
    )
    for mapping in mapping_release.mappings:
        assert mapping.subject.startswith("urn:ref:regulations-gov-agency:")
        assert not mapping.object.startswith("urn:ref:regulations-gov-agency:")
        assert len(mapping.evidence) == 2
        assert {row.review_warrant for row in mapping.evidence} == {"humanReview"}
        assert {row.reviewer_iri for row in mapping.evidence} == {
            alignments.REGULATIONS_GOV_AGENCY_IDENTITY_REVIEWER_IRI
        }
        assert {row.native_payload["endpointRole"] for row in mapping.evidence} == {
            "subject",
            "object",
        }
        for evidence in mapping.evidence:
            payload = evidence.native_payload
            assert payload["evidenceTier"] == "E4"
            assert payload["publisherNames"]["subject"]
            assert payload["publisherNames"]["object"]
            assert payload["reasoning"]
            assert payload["nameSimilarityUsed"] is False


def test_entity_ring_admits_only_same_entity_as_for_mappings(
    mapping_release: RegistryMappingRelease,
) -> None:
    generator = _generator_module()
    policies = generator.ATLAS_VALIDATE._relation_policies()
    assert policies[generator.ATLAS.entity][generator.ATLAS.MappingAssertion] == {
        generator.ATLAS.sameEntityAs
    }
    graph = generator._expected_mapping_asserted_graph((mapping_release,))
    assertions = set(graph.subjects(RDF.type, generator.ATLAS.MappingAssertion))
    bindings = set(graph.subjects(RDF.type, generator.RKAF.EvidenceBinding))
    assert len(assertions) == 321
    assert len(bindings) == 642


def test_release_passes_refusal_guards_and_identifier_tripwire(
    mapping_release: RegistryMappingRelease,
    releases: tuple[RegistryRelease, ...],
) -> None:
    generator = _generator_module()
    endpoint_iris = {
        endpoint
        for mapping in mapping_release.mappings
        for endpoint in (mapping.subject, mapping.object)
    }
    shaped = SimpleNamespace(
        spec=SimpleNamespace(
            key=mapping_release.key,
            logical_path=mapping_release.inputs[0].logical_path,
            input_pins=mapping_release.inputs,
        ),
        scheme_iri=f"urn:ref:atlas-mapping-endpoints:{mapping_release.key}",
        resources=tuple(SimpleNamespace(iri=iri) for iri in endpoint_iris),
    )
    generator._refuse_registrant_population_release(shaped)
    generator._refuse_document_population_release(shaped)
    generator._refuse_observed_inventory_release(shaped)

    assert all(
        not resource.identifiers
        for release in releases
        for resource in release.resources
        if resource.iri in endpoint_iris
    )
    assert all(
        "identifiers" not in evidence.native_payload
        for mapping in mapping_release.mappings
        for evidence in mapping.evidence
    )
    assert not _contains_confidence_key(mapping_release.metadata)
    assert not any(
        _contains_confidence_key(evidence.native_payload)
        for mapping in mapping_release.mappings
        for evidence in mapping.evidence
    )


def test_candidate_accounting_records_fs_and_subunit_non_emission(
    mapping_release: RegistryMappingRelease,
) -> None:
    decisions = {
        row["sourceValue"]: row
        for row in mapping_release.metadata["candidateDecisions"]
    }
    forest_service = decisions["FS"]
    assert forest_service["objectResource"] == (
        "urn:ref:federal-register-agency:209"
    )
    assert {
        row["publisherName"] for row in forest_service["nonEmittedCandidates"]
    } == {"Fiscal Service", "Forest Service"}

    udall = decisions["MKU"]
    assert udall["objectResource"] == "urn:ref:federal-hierarchy-org:300000070"
    assert list(udall["nonEmittedCandidates"]) == [
        {
            "resource": "urn:ref:federal-hierarchy-org:300000385",
            "publisherName": (
                "MORRIS K. UDALL SCHOLARSHIP AND EXCELLENCE IN NATIONAL "
                "ENVIRONMENTAL POLICY FOUNDATION"
            ),
            "reason": (
                "Federal Hierarchy marks this duplicate-name resource as a "
                "Sub-Tier under the selected entity"
            ),
        }
    ]
    assert mapping_release.metadata["subunitPredicateEmitted"] is False


def test_release_is_deterministic_under_roster_reordering(
    releases: tuple[RegistryRelease, ...],
    mapping_release: RegistryMappingRelease,
) -> None:
    reordered = tuple(
        dataclasses.replace(
            release,
            resources=tuple(reversed(release.resources)),
            relations=tuple(reversed(release.relations)),
        )
        for release in reversed(releases)
    )
    rebuilt = alignments.load_regulations_gov_agency_identity_mapping_release(
        reordered
    )
    assert rebuilt == mapping_release


def test_release_refuses_a_reviewed_publisher_name_drift(
    releases: tuple[RegistryRelease, ...],
) -> None:
    changed: list[RegistryRelease] = []
    for release in releases:
        if release.key != "regulations-gov-agencies-roster-2026-08-16":
            changed.append(release)
            continue
        resources = list(release.resources)
        index = next(
            index
            for index, resource in enumerate(resources)
            if resource.native_payload["id"] == "FS"
        )
        resource = resources[index]
        payload = dict(resource.native_payload)
        payload["name"] = "Changed Forest Name"
        resources[index] = dataclasses.replace(resource, native_payload=payload)
        changed.append(dataclasses.replace(release, resources=tuple(resources)))

    with pytest.raises(ValueError, match="source name drifted for FS"):
        alignments.load_regulations_gov_agency_identity_mapping_release(changed)
