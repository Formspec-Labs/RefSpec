"""Dated claims bind their effective scope without changing undated identities."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import generate_atlas_v3_full as generator

sys.path.insert(0, str(ROOT / "bindings" / "atlas" / "3.1" / "tools"))
import build_fixtures as fixtures

from refspec.atlas.v3_registry_alignments import load_unified_agenda_gao_cra_priority_mapping_release

validator = generator.ATLAS_VALIDATE
ATLAS, RKAF = validator.ATLAS, validator.RKAF


def _old_basis(graph: Graph, assertion: URIRef) -> dict[str, str]:
    """Frozen pre-fix identity oracle: only effective-period keys may diverge."""

    policy = graph.value(assertion, ATLAS.governedByPolicy)
    assertion_type = next(iter(set(graph.objects(assertion, RDF.type)) & validator.ASSERTION_TYPES))
    basis = {
        "object": str(graph.value(assertion, RDF.object)),
        "policy": str(policy),
        "policyContentDigest": validator.rdf_node_digest(graph, policy),
        "predicate": str(graph.value(assertion, RDF.predicate)),
        "sourceRelease": str(graph.value(assertion, ATLAS.sourceRelease)),
        "subject": str(graph.value(assertion, RDF.subject)),
        "targetRelease": str(graph.value(assertion, ATLAS.targetRelease)),
        "type": str(assertion_type),
    }
    if assertion_type == ATLAS.CrossRingRelationAssertion:
        basis["sourceRing"] = str(graph.value(assertion, ATLAS.sourceRing))
        basis["targetRing"] = str(graph.value(assertion, ATLAS.targetRing))
    else:
        basis["semanticRing"] = str(graph.value(assertion, ATLAS.semanticRing))
    return basis


def test_retained_ua_gao_mapping_identities_match_the_independent_reader() -> None:
    release = load_unified_agenda_gao_cra_priority_mapping_release(ROOT)
    graph = generator._expected_mapping_asserted_graph((release,))
    assertions = sorted(graph.subjects(RDF.type, ATLAS.MappingAssertion))
    assert len(assertions) == 5
    assert str(assertions[0]) == (
        "urn:ref:atlas-assertion:1e1194394e37300f243033dc782df5d58c8ec973de166d70c298b6fbf5ae73a5"
    )
    for assertion in assertions:
        basis, _ = validator._assertion_basis(graph, assertion)
        old = _old_basis(graph, assertion)
        assert basis == {**old, "effectivePeriodStart": "2026-08-15T00:00:00+00:00"}
        digest = validator.canonical_sha256(basis)
        assert str(graph.value(assertion, ATLAS.assertionIdentityDigest)) == digest
        assert str(assertion) == "urn:ref:atlas-assertion:" + digest.removeprefix("sha256:")
        assert validator.canonical_sha256(old) != digest


@pytest.fixture(scope="module")
def base():
    return fixtures._base_fixture()


def _dated_assertion(graph: Graph) -> URIRef:
    return next(
        assertion for assertion in graph.subjects(RDF.type, ATLAS.MappingAssertion)
        if graph.value(assertion, ATLAS.semanticRing) == ATLAS.value
    )


def test_fixture_identities_only_diverge_for_effective_scope(base) -> None:
    graph = base.asserted
    validator._validate_assertions(graph)
    for assertion in graph.subjects(RDF.type, ATLAS.RelationAssertion):
        old = _old_basis(graph, assertion)
        expected = dict(old)
        period = graph.value(assertion, RKAF.hasEffectivePeriod)
        if period is not None:
            expected["effectivePeriodStart"] = str(graph.value(period, RKAF.effectivePeriodStart))
            end = graph.value(period, RKAF.effectivePeriodEnd)
            if end is not None:
                expected["effectivePeriodEnd"] = str(end)
        basis, _ = validator._assertion_basis(graph, assertion)
        assert basis == expected
        assert str(graph.value(assertion, ATLAS.assertionIdentityDigest)) == validator.canonical_sha256(expected)


@pytest.mark.parametrize("change", ("start", "end", "remove-end", "old-identity"))
def test_dated_identity_refuses_changed_scope_or_the_old_hash(base, change: str) -> None:
    graph = copy.deepcopy(base.asserted)
    assertion = _dated_assertion(graph)
    period = graph.value(assertion, RKAF.hasEffectivePeriod)
    if change == "old-identity":
        old_digest = validator.canonical_sha256(_old_basis(graph, assertion))
        graph.set((assertion, ATLAS.assertionIdentityDigest, Literal(old_digest)))
    elif change == "remove-end":
        graph.remove((period, RKAF.effectivePeriodEnd, None))
    else:
        predicate, value = (
            (RKAF.effectivePeriodStart, "2026-02-01T00:00:00+00:00")
            if change == "start" else (RKAF.effectivePeriodEnd, "2026-11-30T23:59:59+00:00")
        )
        graph.set((period, predicate, Literal(value, datatype=XSD.dateTime, normalize=False)))
    with pytest.raises(validator.AtlasValidationError) as error:
        validator._validate_assertions(graph)
    assert error.value.code == "dataset.assertion-identity"


def test_assertion_time_and_evidence_remain_outside_identity(base) -> None:
    graph = copy.deepcopy(base.asserted)
    assertion = _dated_assertion(graph)
    before, _ = validator._assertion_basis(graph, assertion)
    graph.set((assertion, RKAF.assertedAt, Literal("2026-09-01T00:00:00+00:00", datatype=XSD.dateTime)))
    graph.add((URIRef("urn:test:additional-evidence"), RKAF.bindsAssertion, assertion))
    after, _ = validator._assertion_basis(graph, assertion)
    assert after == before


@pytest.mark.parametrize("case", (
    "mapping-undated-value-crosswalk",
    "mapping-undated-legal-identity",
    "mapping-entity-identity-dated",
    "mapping-subject-ring-dated",
    "mapping-period-end-before-start",
    "mapping-period-start-not-datetime",
    "mapping-period-start-not-utc-midnight",
    "mapping-period-end-not-utc-day-end",
))
def test_existing_period_shape_refusals_survive(base, case: str) -> None:
    fixture = copy.deepcopy(base)
    mutation = next(row[3] for row in fixtures._mutations() if row[0] == case)
    mutation(fixture)
    ontology, shapes = validator._parse_binding_graphs()
    graphs = {"asserted": fixture.asserted, "derived": fixture.derived, "projection": fixture.projection}
    with pytest.raises(validator.AtlasValidationError) as error:
        validator._run_shacl(graphs, ontology, shapes)
    assert error.value.code == "shacl.data"
