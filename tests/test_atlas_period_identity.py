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


def _mint_period(graph: Graph, original: URIRef, period: tuple[str, str | None]) -> URIRef:
    """Use the real producer with the existing fixture's endpoints and policy."""
    return generator._add_assertion(
        graph,
        assertion_type=ATLAS.MappingAssertion,
        ring=ATLAS.value,
        subject=graph.value(original, RDF.subject),
        predicate=graph.value(original, RDF.predicate),
        obj=graph.value(original, RDF.object),
        source_release=graph.value(original, ATLAS.sourceRelease),
        target_release=graph.value(original, ATLAS.targetRelease),
        policy=graph.value(original, ATLAS.governedByPolicy),
        asserted_at=str(graph.value(original, RKAF.assertedAt)),
        effective_period=period,
    )


def _replace_value_mapping(fixture, period: tuple[str, str | None]) -> URIRef:
    graph = fixture.asserted
    original = _dated_assertion(graph)
    old_period = graph.value(original, RKAF.hasEffectivePeriod)
    evidence = next(graph.subjects(RKAF.bindsAssertion, original))
    record = graph.value(evidence, ATLAS.evidenceSourceRecord)
    attestor = graph.value(evidence, RKAF.attestor)
    assertion = _mint_period(graph, original, period)
    assert assertion != original
    fixtures._remove_assertion_with_evidence(graph, original)
    for node, predicate, _ in list(fixture.projection.triples((None, None, original))):
        fixture.projection.remove((node, predicate, original))
        fixture.projection.add((node, predicate, assertion))
    if not any(graph.subjects(RKAF.hasEffectivePeriod, old_period)):
        graph.remove((old_period, None, None))
    fixtures._add_evidence_binding(
        graph, bound=assertion, evidence_record=record, evidence_name="period-integration",
        attestor=attestor, review_warrant="publisherAssertion",
    )
    fixtures._account_assertions(fixture)
    return assertion


def _write_distribution(path: Path, fixture) -> None:
    fixtures._write_case(
        path, fixture, baseline_asserted=fixture.asserted,
        binding_digests=validator._binding_digests(), corpus_digest=validator.corpus_digest(),
        distribution_id="urn:ref:atlas-fixture:distribution:period-integration",
    )


def _parse_distribution(path: Path):
    import json

    manifest = json.loads((path / "atlas-manifest.json").read_bytes())
    graph_ids = validator._check_pack_manifest(manifest)
    return validator._parse_packed_dataset(path, manifest, graph_ids)[1]


@pytest.mark.parametrize("end", (None, "2027-12-31T23:59:59+00:00"))
def test_producer_period_survives_wire_and_full_validation(base, tmp_path: Path, end: str | None) -> None:
    fixture = copy.deepcopy(base)
    start = "2027-01-01T00:00:00+00:00"
    assertion = _replace_value_mapping(fixture, (start, end))
    _write_distribution(tmp_path, fixture)
    graphs = _parse_distribution(tmp_path)
    graph = graphs["asserted"]
    period = graph.value(assertion, RKAF.hasEffectivePeriod)
    assert graph.value(period, RKAF.effectivePeriodStart) == Literal(start, datatype=XSD.dateTime, normalize=False)
    assert str(graph.value(period, RKAF.effectivePeriodStart)) == start
    actual_end = graph.value(period, RKAF.effectivePeriodEnd)
    if end is None:
        assert actual_end is None
    else:
        assert str(actual_end) == end
        assert actual_end.datatype == XSD.dateTime
    basis, _ = validator._assertion_basis(graph, assertion)
    assert basis["effectivePeriodStart"] == start
    assert basis.get("effectivePeriodEnd") == end
    assert str(assertion).endswith(validator.canonical_sha256(basis).removeprefix("sha256:"))
    validator.validate_distribution(tmp_path)


def test_consistent_legacy_identity_is_refused_after_shape_validation(base, tmp_path: Path) -> None:
    fixture = copy.deepcopy(base)
    graph = fixture.asserted
    assertion = _dated_assertion(graph)
    digest = validator.canonical_sha256(_old_basis(graph, assertion))
    legacy = URIRef("urn:ref:atlas-assertion:" + digest.removeprefix("sha256:"))
    graph.set((assertion, ATLAS.assertionIdentityDigest, Literal(digest)))
    for subject, predicate, obj in list(graph.triples((None, None, None))):
        if subject == assertion or obj == assertion:
            graph.remove((subject, predicate, obj))
            graph.add((legacy if subject == assertion else subject, predicate, legacy if obj == assertion else obj))
    fixtures._reseal_evidence_to_fixed_point(graph)
    fixtures._account_assertions(fixture)
    assert validator.canonical_sha256(_old_basis(graph, legacy)) == digest
    _write_distribution(tmp_path, fixture)
    with pytest.raises(validator.AtlasValidationError) as error:
        validator.validate_distribution(tmp_path)
    assert error.value.code == "dataset.assertion-identity"


def test_same_triple_distinct_periods_and_undated_old_oracle(base) -> None:
    graph = copy.deepcopy(base.asserted)
    original = _dated_assertion(graph)
    periods = (("2027-01-01T00:00:00+00:00", None),
               ("2027-01-01T00:00:00+00:00", "2027-12-31T23:59:59+00:00"),
               ("2027-01-01T00:00:00+00:00", "2028-12-31T23:59:59+00:00"))
    assertions = {_mint_period(graph, original, period) for period in periods}
    assert len(assertions) == len(periods)
    supported = validator._validate_assertions(graph)
    triple = tuple(graph.value(original, p) for p in (RDF.subject, RDF.predicate, RDF.object))
    assert assertions <= set(supported[triple])
    for assertion in graph.subjects(RDF.type, ATLAS.RelationAssertion):
        basis, _ = validator._assertion_basis(graph, assertion)
        old = _old_basis(graph, assertion)
        period = graph.value(assertion, RKAF.hasEffectivePeriod)
        # Frozen divergence: period keys are the only intended change to the old basis.
        assert {key: value for key, value in basis.items() if key not in {"effectivePeriodStart", "effectivePeriodEnd"}} == old
        if period is None:
            assert basis == old
            assert str(graph.value(assertion, ATLAS.assertionIdentityDigest)) == validator.canonical_sha256(old)
        else:
            assert validator.canonical_sha256(basis) != validator.canonical_sha256(old)


@pytest.mark.parametrize("case", (
    "mapping-undated-value-crosswalk",
    "mapping-period-start-not-datetime",
    "mapping-period-end-before-start",
    "multiple-start",
))
def test_invalid_period_is_refused_by_shape_before_identity(base, tmp_path: Path, case: str) -> None:
    fixture = copy.deepcopy(base)
    if case == "multiple-start":
        period = fixture.asserted.value(_dated_assertion(fixture.asserted), RKAF.hasEffectivePeriod)
        fixture.asserted.add(
            (period, RKAF.effectivePeriodStart, Literal("2026-02-01T00:00:00+00:00", datatype=XSD.dateTime, normalize=False))
        )
    else:
        mutation = next(row[3] for row in fixtures._mutations() if row[0] == case)
        mutation(fixture)
    _write_distribution(tmp_path, fixture)
    with pytest.raises(validator.AtlasValidationError) as error:
        validator.validate_distribution(tmp_path)
    assert error.value.code == "shacl.data"


def test_same_triple_different_periods_validate_together(base, tmp_path: Path) -> None:
    fixture = copy.deepcopy(base)
    graph = fixture.asserted
    original = _dated_assertion(graph)
    existing_binding = next(graph.subjects(RKAF.bindsAssertion, original))
    record = graph.value(existing_binding, ATLAS.evidenceSourceRecord)
    attestor = graph.value(existing_binding, RKAF.attestor)
    new = _mint_period(graph, original, ("2026-01-01T00:00:00+00:00", None))
    assert new != original
    fixtures._add_evidence_binding(
        graph, bound=new, evidence_record=record, evidence_name="open-crosswalk",
        attestor=attestor, review_warrant="publisherAssertion",
    )
    projection = next(fixture.projection.subjects(ATLAS.supportingAssertion, original))
    fixture.projection.add((projection, ATLAS.supportingAssertion, new))
    fixtures._account_assertions(fixture)
    _write_distribution(tmp_path, fixture)
    parsed = _parse_distribution(tmp_path)["asserted"]
    supported = validator._validate_assertions(parsed)
    triple = tuple(parsed.value(original, p) for p in (RDF.subject, RDF.predicate, RDF.object))
    assert {original, new} <= set(supported[triple])
    validator.validate_distribution(tmp_path)
