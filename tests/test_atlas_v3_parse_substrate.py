from __future__ import annotations

import sys
from io import StringIO
from itertools import product
from pathlib import Path

import pytest
from rdflib import Dataset, Literal, URIRef
from rdflib.plugins.stores.memory import Memory

ROOT = Path(__file__).resolve().parents[1]
BINDING_TOOLS = ROOT / "bindings" / "atlas" / "3.1" / "tools"
sys.path.insert(0, str(BINDING_TOOLS))
import validate as atlas_validate
from parse_substrate import TermPool, TwoIndexStore


def _dataset(store: Memory | TwoIndexStore):
    dataset = Dataset(store=store)
    first = dataset.graph(URIRef("urn:graph:first"))
    second = dataset.graph(URIRef("urn:graph:second"))
    triples = (
        (URIRef("urn:s:1"), URIRef("urn:p:1"), URIRef("urn:o:1")),
        (URIRef("urn:s:1"), URIRef("urn:p:2"), Literal("value", lang="en")),
        (URIRef("urn:s:2"), URIRef("urn:p:1"), URIRef("urn:o:1")),
        (URIRef("urn:s:1"), URIRef("urn:p:1"), URIRef("urn:o:2")),
    )
    for triple in triples:
        first.add(triple)
    second.add(triples[0])
    second.add((URIRef("urn:s:3"), URIRef("urn:p:3"), Literal("3")))
    first.add(triples[0])
    return dataset, first, second


def test_two_index_matches_memory_for_every_bound_position_pattern() -> None:
    expected, expected_first, expected_second = _dataset(Memory())
    store = TwoIndexStore()
    actual, actual_first, actual_second = _dataset(store)
    terms = (
        (URIRef("urn:s:1"), URIRef("urn:p:1"), URIRef("urn:o:1")),
        (URIRef("urn:missing"), URIRef("urn:missing"), URIRef("urn:missing")),
    )

    for expected_graph, actual_graph in (
        (expected_first, actual_first),
        (expected_second, actual_second),
    ):
        for mask in product((False, True), repeat=3):
            for values in terms:
                pattern = tuple(
                    value if bound else None
                    for value, bound in zip(values, mask, strict=True)
                )
                assert set(actual_graph.triples(pattern)) == set(
                    expected_graph.triples(pattern)
                )
        assert len(actual_graph) == len(expected_graph)

    assert tuple(actual_first.objects(URIRef("urn:s:1"), URIRef("urn:p:1"))) == tuple(
        expected_first.objects(URIRef("urn:s:1"), URIRef("urn:p:1"))
    )

    assert set(actual.quads((None, None, None, None))) == set(
        expected.quads((None, None, None, None))
    )
    assert store.object_scan_count > 0


def test_two_index_contexts_namespaces_and_removal_match_memory() -> None:
    expected, expected_first, _ = _dataset(Memory())
    actual, actual_first, _ = _dataset(TwoIndexStore())
    triple = (URIRef("urn:s:1"), URIRef("urn:p:1"), URIRef("urn:o:1"))

    expected.bind("example", URIRef("urn:example:"))
    actual.bind("example", URIRef("urn:example:"))
    expected.bind("example", URIRef("urn:other:"), override=False)
    actual.bind("example", URIRef("urn:other:"), override=False)
    assert dict(actual.namespaces()) == dict(expected.namespaces())
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


def test_term_pool_preserves_values_hashes_and_reuses_objects() -> None:
    pool = TermPool()
    datatype = pool.iri("urn:datatype")
    assert datatype is pool.iri("urn:datatype")

    first = pool.literal("lexical", lang=None, datatype=datatype)
    second = pool.literal("lexical", lang=None, datatype=datatype)
    stock = Literal("lexical", datatype=URIRef("urn:datatype"), normalize=False)
    assert first is second
    assert first == stock
    assert hash(first) == hash(stock)
    assert first.datatype == stock.datatype


def test_integrated_parser_pools_terms_only_on_the_two_index_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = """\
<urn:s:1> <urn:p> \"same\"@en <urn:g> .
<urn:s:2> <urn:p> \"same\"@en <urn:g> .
"""

    monkeypatch.delenv(atlas_validate.RDF_STORE_ENV, raising=False)
    candidate = atlas_validate._new_dataset()
    atlas_validate._parse_nquads_preserving_lexical_forms(
        candidate,
        StringIO(source),
    )
    candidate_rows = list(candidate.graph(URIRef("urn:g")))
    candidate_predicates = [row[1] for row in candidate_rows]
    candidate_objects = [row[2] for row in candidate_rows]
    assert isinstance(candidate.store, TwoIndexStore)
    assert candidate_predicates[0] is candidate_predicates[1]
    assert candidate_objects[0] is candidate_objects[1]

    monkeypatch.setenv(atlas_validate.RDF_STORE_ENV, atlas_validate.MEMORY_STORE)
    stock = atlas_validate._new_dataset()
    atlas_validate._parse_nquads_preserving_lexical_forms(stock, StringIO(source))
    stock_rows = list(stock.graph(URIRef("urn:g")))
    assert isinstance(stock.store, Memory)
    assert [row[2] for row in candidate_rows] == [row[2] for row in stock_rows]


def test_store_selector_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(atlas_validate.RDF_STORE_ENV, "unknown")
    with pytest.raises(atlas_validate.AtlasValidationError) as error:
        atlas_validate._new_dataset()
    assert error.value.code == "configuration.rdf-store"
