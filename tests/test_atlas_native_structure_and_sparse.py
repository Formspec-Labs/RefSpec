"""Focused checks for the structure diagnostic, learned-sparse, and reranker tools."""

from __future__ import annotations

import json

import numpy as np
import pytest

from tools import analyze_atlas_native_relation_structure as structure
from tools import benchmark_atlas_native_reranker_recovery as rerank

# The learned-sparse tool runs in an isolated environment; SciPy is not a
# project dependency, so its checks skip rather than fail here.
pytest.importorskip("scipy")
from tools import benchmark_atlas_native_learned_sparse_recovery as learned


def _write(path, rows) -> None:
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")


def _hierarchy_row(child: str, parent: str) -> dict[str, object]:
    return {
        "relationClass": "hierarchy",
        "subject": {"iri": f"urn:{child}", "label": child},
        "object": {"iri": f"urn:{parent}", "label": parent},
    }


def test_hierarchy_loads_broader_oriented_edges_only(tmp_path) -> None:
    _write(
        tmp_path / "s.jsonl",
        [
            _hierarchy_row("LOANS", "CREDIT"),
            {
                "relationClass": "associative",
                "subject": {"iri": "urn:A", "label": "A"},
                "object": {"iri": "urn:B", "label": "B"},
            },
        ],
    )

    edges, labels = structure.load_directed_hierarchy(tmp_path, "s")

    assert edges == {"urn:LOANS": {"urn:CREDIT"}}
    assert labels["urn:A"] == "A"  # associative endpoints still contribute labels


def test_closure_finds_the_unasserted_grandparent(tmp_path) -> None:
    edges = {"urn:a": {"urn:b"}, "urn:b": {"urn:c"}}

    report = structure.closure_report(edges, max_depth=6)

    assert report["assertedEdges"] == 2
    assert report["impliedButNotAsserted"] == 1
    assert report["transitivelyClosed"] is False
    assert report["byHopCount"]["2"] == 1


def test_closure_reports_a_fully_asserted_hierarchy_as_closed() -> None:
    edges = {"urn:a": {"urn:b", "urn:c"}, "urn:b": {"urn:c"}}

    report = structure.closure_report(edges, max_depth=6)

    assert report["transitivelyClosed"] is True
    assert report["impliedButNotAsserted"] == 0


def test_depth_bound_limits_how_far_entailment_reaches() -> None:
    edges = {"urn:a": {"urn:b"}, "urn:b": {"urn:c"}, "urn:c": {"urn:d"}}

    shallow = structure.closure_report(edges, max_depth=2)
    deep = structure.closure_report(edges, max_depth=6)

    assert shallow["impliedButNotAsserted"] < deep["impliedButNotAsserted"]


def test_cycle_detection_finds_a_loop_and_clears_a_dag() -> None:
    assert structure.find_cycle({"urn:a": {"urn:b"}, "urn:b": {"urn:a"}}) is not None
    assert structure.find_cycle({"urn:a": {"urn:b"}, "urn:b": {"urn:c"}}) is None


def test_degree_report_measures_hub_concentration() -> None:
    edges = {"urn:a": {"urn:hub"}, "urn:b": {"urn:hub"}, "urn:c": {"urn:hub"}}

    report = structure.degree_report(edges, concepts=10)

    assert report["maxDegree"] == 3
    assert report["conceptsWithAnyEdge"] == 4
    assert report["conceptsInRelease"] == 10


def test_learned_sparse_views_use_only_unablated_fields() -> None:
    concept = {"label": "Housing", "altLabels": ["Shelter"], "definition": "d", "notes": "n"}

    assert learned.view_text(concept, "label") == "Housing Shelter"
    assert learned.view_text(concept, "structured") == "label: Housing | aliases: Shelter | definition: d | notes: n"


def test_csr_packing_preserves_indices_and_values() -> None:
    class _Emb:
        def __init__(self, indices, values) -> None:
            self.indices = indices
            self.values = values

    matrix = learned.to_csr([_Emb([1, 3], [0.5, 0.25]), _Emb([0], [1.0])], width=4)

    assert matrix.shape == (2, 4)
    assert matrix[0, 1] == np.float32(0.5)
    assert matrix[1, 0] == np.float32(1.0)
    assert matrix[1, 3] == 0


def test_sparse_ranking_omits_pairs_with_no_shared_term() -> None:
    # Rows 0 and 1 share term 0; row 2 shares nothing with either.
    matrix = learned.sparse.csr_matrix(
        np.asarray([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)
    )

    ranks = learned.blockwise_min_ranks(matrix, matrix, top_k=5, block=2)

    assert set(ranks) == {0 * 3 + 1}


def test_reservoir_unions_arms_and_reports_what_the_cap_dropped(tmp_path) -> None:
    count = 4
    np.savez(
        tmp_path / "arm.s.npz",
        conceptCount=np.asarray([count], dtype=np.uint32),
        **{
            "label.codes": np.asarray([0 * count + 1, 0 * count + 2, 0 * count + 3], dtype=np.uint32),
            "label.ranks": np.asarray([1, 2, 3], dtype=np.uint8),
        },
    )

    reservoir, resolved, distinct, capped = rerank.build_reservoir(tmp_path, "s", cap=2)

    assert resolved == count
    # Concept 0 has three partners and the cap keeps two, so one slot is dropped.
    assert len(reservoir[0]) == 2
    assert capped == 1
    assert distinct >= 2


def test_reranker_ranks_are_bounded_by_the_reservoir() -> None:
    reservoir = {0: [1, 2], 1: [0], 2: [0]}
    count = 3
    scores = {0 * count + 1: 0.9, 0 * count + 2: 0.1}

    ranks = rerank.min_ranks(scores, reservoir, count, top_k=10)

    # A pair absent from the reservoir can never appear.
    assert (1 * count + 2) not in ranks
    assert ranks[0 * count + 1] == 1
    # Ranks are the best of both directions: (0, 2) is second from concept 0 but
    # first from concept 2, whose only reservoir partner is 0.
    assert ranks[0 * count + 2] == 1


def test_reranker_rank_reflects_score_order_within_one_direction() -> None:
    reservoir = {0: [1, 2]}
    count = 3
    scores = {0 * count + 1: 0.1, 0 * count + 2: 0.9}

    ranks = rerank.min_ranks(scores, reservoir, count, top_k=10)

    assert ranks[0 * count + 2] == 1
    assert ranks[0 * count + 1] == 2
