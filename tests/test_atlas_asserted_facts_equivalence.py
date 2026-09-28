"""The removed fact index remains an oracle for graph-backed reads."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bindings/atlas/3.1/tools"))
import validate as validator
from atlas_asserted_facts_oracle import _INDEXED_ASSERTED_PREDICATES as FROZEN_PREDICATES
from atlas_asserted_facts_oracle import _INDEXED_ASSERTED_TYPES as FROZEN_TYPES
from atlas_asserted_facts_oracle import _AssertedFacts as FrozenFacts


def _verdict(facts, subject, predicate):
    try:
        return facts.one(subject, predicate, code="oracle.one")
    except validator.AtlasValidationError as error:
        return type(error), str(error)


def _compare(graph):
    old = FrozenFacts(graph.identifier, from_walk=True)
    for triple in graph:
        old.observe(*triple)
    old.align_to_graph(graph)
    new = validator._AssertedFacts.for_graph(graph)
    pairs = {(s, p) for s, p, _ in graph if p in FROZEN_PREDICATES}
    pairs.add((URIRef("urn:absent"), validator.ATLAS.inRelease))
    for subject, predicate in pairs:
        assert new.objects(subject, predicate) == old.objects(subject, predicate)
        assert new.value(subject, predicate) == old.value(subject, predicate)
        assert _verdict(new, subject, predicate) == _verdict(old, subject, predicate)
        for obj in (*old.objects(subject, predicate), URIRef("urn:absent")):
            assert new.contains(subject, predicate, obj) == old.contains(subject, predicate, obj)
    for predicate in FROZEN_PREDICATES:
        assert set(new.subject_objects(predicate)) == set(old.subject_objects(predicate))
    for subject in set(graph.subjects()):
        for kind in FROZEN_TYPES:
            assert new.has_type(subject, kind) == old.has_type(subject, kind)


@pytest.mark.parametrize("mutation", ("clean", "missing", "multiple", "many", "literal", "abstract-type", "duplicate"))
def test_fact_reads_match_frozen_index_with_mutations(mutation):
    graph = Graph(store=validator.TwoIndexStore())
    subject, other = URIRef("urn:subject"), URIRef("urn:other")
    predicate = validator.ATLAS.inRelease
    graph.add((subject, predicate, other))
    if mutation == "missing":
        graph.remove((subject, predicate, None))
    elif mutation == "multiple":
        graph.add((subject, predicate, URIRef("urn:second")))
    elif mutation == "many":
        for i in range(20):
            graph.add((subject, predicate, URIRef(f"urn:item:{i}")))
    elif mutation == "literal":
        graph.add((subject, predicate, Literal("bad-kind", lang="en")))
    elif mutation == "abstract-type":
        graph.add((subject, RDF.type, validator.ATLAS.RelationAssertion))
    elif mutation == "duplicate":
        graph.add((subject, predicate, other))
    _compare(graph)


@pytest.mark.reads_built_artifact
def test_fact_reads_match_frozen_index_on_real_bounded_packs():
    root = ROOT / "output/atlas-3.1-umthes-2026-09-27/distribution"
    assert root.is_dir(), "required retained UMTHES distribution is unavailable"
    manifest = json.loads((root / "atlas-manifest.json").read_text())
    ids = validator._check_pack_manifest(manifest)
    _, graphs = validator._parse_packed_dataset(root, manifest, ids)
    _compare(graphs["asserted"])


# The removed index rejected reads outside its private allowlist and grouped
# predicate scans by subject. Neither is a normative graph constraint. README
# "Validation order" does not promise precedence among simultaneous defects.
DELIBERATE_DIVERGENCES = frozenset({"unindexed-predicate-access", "subject-object-order"})


def test_only_declared_fact_interface_divergences():
    graph = Graph(store=validator.TwoIndexStore())
    predicate = validator.ATLAS.inRelease
    first, second = URIRef("urn:first"), URIRef("urn:second")
    for triple in ((first, predicate, second), (first, predicate, first), (second, predicate, second)):
        graph.add(triple)
    old = FrozenFacts(graph.identifier)
    for triple in graph:
        old.observe(*triple)
    new = validator._AssertedFacts.for_graph(graph)
    observed = set()
    if list(new.subject_objects(predicate)) != list(old.subject_objects(predicate)):
        observed.add("subject-object-order")
        assert set(new.subject_objects(predicate)) == set(old.subject_objects(predicate))
    graph.add((first, validator.ATLAS.nativePayload, Literal("payload")))
    with pytest.raises(AssertionError):
        old.objects(first, validator.ATLAS.nativePayload)
    assert new.objects(first, validator.ATLAS.nativePayload) == (Literal("payload"),)
    observed.add("unindexed-predicate-access")
    assert observed == DELIBERATE_DIVERGENCES


@pytest.mark.parametrize("mutation", ("clean", "missing-source", "multiple-sources", "non-iri-source"))
def test_construction_binding_verdict_matches_frozen_index(mutation):
    graph = Graph(store=validator.TwoIndexStore())
    statement, binding, source = map(URIRef, ("urn:statement", "urn:binding", "urn:source"))
    graph.add((binding, validator.RKAF.bindsAssertion, statement))
    if mutation != "missing-source":
        graph.add((binding, validator.ATLAS.evidenceSourceRecord, Literal("bad") if mutation == "non-iri-source" else source))
    if mutation == "multiple-sources":
        graph.add((binding, validator.ATLAS.evidenceSourceRecord, URIRef("urn:second-source")))
    old = FrozenFacts(graph.identifier)
    for triple in graph:
        old.observe(*triple)
    new = validator._AssertedFacts.for_graph(graph)
    def verdict(facts):
        bindings = {}
        for item, target in facts.subject_objects(validator.RKAF.bindsAssertion):
            bindings.setdefault(target, []).append(item)
        try:
            return validator._construction_statement_source_records(graph, statement, asserted_facts=facts, bindings_by_statement=bindings)
        except validator.AtlasValidationError as error:
            return type(error), str(error)
    assert verdict(new) == verdict(old)
