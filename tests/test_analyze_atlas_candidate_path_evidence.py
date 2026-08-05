from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import analyze_atlas_candidate_path_evidence as path_audit

SKOS = "http://www.w3.org/2004/02/skos/core#"


def _concept(identifier: str, label: str, **relations: object) -> dict[str, object]:
    return {
        "@id": identifier,
        "@type": "skos:Concept",
        "skos:prefLabel": {"en": label},
        **relations,
    }


def _mapping(source: str, target: str, relation: str) -> dict[str, object]:
    return {
        "type": "MappingAssertion",
        "sourceConcept": source,
        "targetConcept": target,
        "relation": SKOS + relation,
    }


def test_build_graph_preserves_direction_and_inverse_semantics() -> None:
    graph = path_audit.build_graph(
        [
            _concept("urn:a", "A", **{"skos:broader": ["urn:b"]}),
            _concept("urn:b", "B"),
            _mapping("urn:b", "urn:c", "narrowMatch"),
            _concept("urn:c", "C"),
        ]
    )

    assert [(edge.target, edge.semantic) for edge in graph.adjacency["urn:a"]] == [("urn:b", "broader")]
    assert {(edge.target, edge.semantic) for edge in graph.adjacency["urn:b"]} == {
        ("urn:a", "narrower"),
        ("urn:c", "narrower"),
    }
    assert [(edge.target, edge.semantic) for edge in graph.adjacency["urn:c"]] == [("urn:b", "broader")]


def test_shortest_usable_path_accepts_one_close_then_directed_hierarchy() -> None:
    graph = path_audit.build_graph(
        [
            _concept("urn:source", "Water resources"),
            _concept("urn:water", "WATER RESOURCES", **{"skos:broader": ["urn:natural"]}),
            _concept("urn:natural", "NATURAL RESOURCES"),
            _mapping("urn:source", "urn:water", "closeMatch"),
        ]
    )

    found = path_audit.shortest_usable_path(graph, "urn:source", "urn:natural", max_depth=4)

    assert found is not None
    mode, edges = found
    assert mode == "broader_close"
    assert [edge.semantic for edge in edges] == ["close", "broader"]
    record = path_audit._path_record(graph, mode, edges)
    assert record["semanticClass"] == "broader"
    assert record["attenuatedByClose"] is True
    assert record["intermediates"] == [{"id": "urn:water", "label": "WATER RESOURCES"}]


def test_shortest_usable_path_rejects_noncomposable_connectivity() -> None:
    graph = path_audit.build_graph(
        [
            _concept("urn:a", "A", **{"skos:broader": ["urn:b"]}),
            _concept("urn:b", "B", **{"skos:narrower": ["urn:c"]}),
            _concept("urn:c", "C", **{"skos:related": ["urn:d"]}),
            _concept("urn:d", "D", **{"skos:related": ["urn:e"]}),
            _concept("urn:e", "E"),
        ]
    )

    assert path_audit.shortest_usable_path(graph, "urn:a", "urn:c", max_depth=4) is None
    assert path_audit.shortest_usable_path(graph, "urn:c", "urn:e", max_depth=4) is None


def test_single_associative_edge_with_neutral_links_is_inspection_only() -> None:
    graph = path_audit.build_graph(
        [
            _concept("urn:a", "A"),
            _concept("urn:b", "B", **{"skos:related": ["urn:c"]}),
            _concept("urn:c", "C"),
            _mapping("urn:a", "urn:b", "exactMatch"),
        ]
    )

    found = path_audit.shortest_usable_path(graph, "urn:a", "urn:c", max_depth=3)

    assert found is not None
    mode, edges = found
    assert mode == "related"
    record = path_audit._path_record(graph, mode, edges)
    assert record["use"] == "inspectionOnlyAssociative"
    assert [edge.semantic for edge in edges] == ["exact", "related"]
