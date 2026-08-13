"""Focused Graph API checks for the research-only two-index store."""

from __future__ import annotations

from itertools import product

from rdflib import Dataset, Literal, URIRef
from rdflib.plugins.stores.memory import Memory

from research.parse_substrate.stores import TwoIndexStore


def _dataset(store):
    dataset = Dataset(store=store)
    first = dataset.graph(URIRef("urn:graph:first"))
    second = dataset.graph(URIRef("urn:graph:second"))
    triples = (
        (URIRef("urn:s:1"), URIRef("urn:p:1"), URIRef("urn:o:1")),
        (URIRef("urn:s:1"), URIRef("urn:p:2"), Literal("value", lang="en")),
        (URIRef("urn:s:2"), URIRef("urn:p:1"), URIRef("urn:o:1")),
    )
    for triple in triples:
        first.add(triple)
    second.add(triples[0])
    second.add((URIRef("urn:s:3"), URIRef("urn:p:3"), Literal("3")))
    first.add(triples[0])  # Duplicate insertion preserves RDF set semantics.
    return dataset, first, second


def test_two_index_matches_memory_for_all_bound_position_patterns() -> None:
    expected, expected_first, expected_second = _dataset(Memory())
    actual, actual_first, actual_second = _dataset(TwoIndexStore())
    terms = (
        (URIRef("urn:s:1"), URIRef("urn:p:1"), URIRef("urn:o:1")),
        (URIRef("urn:missing"), URIRef("urn:missing"), URIRef("urn:missing")),
    )

    for graph_expected, graph_actual in (
        (expected_first, actual_first),
        (expected_second, actual_second),
    ):
        for mask in product((False, True), repeat=3):
            for values in terms:
                pattern = tuple(value if bound else None for value, bound in zip(values, mask))
                assert set(graph_actual.triples(pattern)) == set(graph_expected.triples(pattern))
        assert len(graph_actual) == len(graph_expected)

    assert set(actual.quads((None, None, None, None))) == set(
        expected.quads((None, None, None, None))
    )


def test_two_index_contexts_namespaces_and_removal_match_memory() -> None:
    expected, expected_first, _ = _dataset(Memory())
    actual, actual_first, _ = _dataset(TwoIndexStore())
    triple = (URIRef("urn:s:1"), URIRef("urn:p:1"), URIRef("urn:o:1"))

    expected.bind("example", URIRef("urn:example:"))
    actual.bind("example", URIRef("urn:example:"))
    assert dict(actual.namespaces())["example"] == dict(expected.namespaces())["example"]
    assert {graph.identifier for graph in actual.store.contexts(triple)} == {
        graph.identifier for graph in expected.store.contexts(triple)
    }

    expected_first.remove((URIRef("urn:s:1"), None, None))
    actual_first.remove((URIRef("urn:s:1"), None, None))
    assert set(actual_first) == set(expected_first)
    actual.remove_graph(URIRef("urn:graph:second"))
    expected.remove_graph(URIRef("urn:graph:second"))
    assert set(actual.quads((None, None, None, None))) == set(
        expected.quads((None, None, None, None))
    )
