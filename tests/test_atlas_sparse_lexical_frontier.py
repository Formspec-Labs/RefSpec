"""Focused accounting checks for the exact Atlas candidate frontier."""

from __future__ import annotations

from refspec.atlas.candidate_retrieval import AtlasConcept
from tools import benchmark_atlas_candidate_retrieval as shared
from tools import benchmark_atlas_sparse_lexical_frontier as frontier
from tools import benchmark_lexical_candidate_controls as lexical


def _concept(side: str, identifier: str) -> AtlasConcept:
    return AtlasConcept(
        member=f"https://example.test/{side}/{identifier}",
        release=f"urn:test:{side}",
        pref_label=identifier,
    )


def test_exact_union_accounts_for_overlap_marginals_cases_and_types() -> None:
    sources = (_concept("source", "a"), _concept("source", "b"))
    targets = (_concept("target", "a"), _concept("target", "b"))
    case = shared.AlignmentCase(
        "example",
        sources,
        targets,
        frozenset({(sources[0].member, targets[0].member), (sources[1].member, targets[1].member)}),
    )
    codec = lexical.PairCodec.from_cases((case,))
    first_gold = codec.code(0, 0, 0)
    overlap_non_gold = codec.code(0, 0, 1)
    second_gold = codec.code(0, 1, 1)
    gold = frozenset({first_gold, second_gold})
    gold_by_relation = {
        "exact": frozenset({first_gold}),
        "close": frozenset(),
        "broad": frozenset(),
        "narrow": frozenset(),
        "related": frozenset({second_gold}),
    }

    result = frontier.summarize_combination(
        lexical_depth=1,
        sparse_depth=1,
        lexical_pairs=frozenset({first_gold, overlap_non_gold}),
        sparse_pairs=frozenset({overlap_non_gold, second_gold}),
        gold=gold,
        gold_by_case=(gold,),
        gold_by_relation=gold_by_relation,
        codec=codec,
    )

    assert result["candidates"] == 3
    assert result["found"] == 2
    assert result["overlapCandidates"] == 1
    assert result["overlapGold"] == 0
    assert result["lexicalOnlyCandidates"] == 1
    assert result["lexicalOnlyGold"] == 1
    assert result["sparseGraphOnlyCandidates"] == 1
    assert result["sparseGraphOnlyGold"] == 1
    assert result["cases"][0]["unionFound"] == 2
    assert result["typedRelations"]["exact"]["lexicalOnlyGold"] == 1
    assert result["typedRelations"]["related"]["sparseGraphOnlyGold"] == 1


def test_frontier_functions_keep_asymmetric_complete_tradeoffs() -> None:
    rows = [
        {"lexicalK": 1, "sparseGraphK": 1, "candidates": 10, "found": 1},
        {"lexicalK": 1, "sparseGraphK": 2, "candidates": 15, "found": 2},
        {"lexicalK": 2, "sparseGraphK": 1, "candidates": 14, "found": 2},
        {"lexicalK": 2, "sparseGraphK": 2, "candidates": 20, "found": 2},
    ]

    assert frontier._depth_pareto_complete(rows, 2) == [
        {"lexicalK": 2, "sparseGraphK": 1, "candidates": 14},
        {"lexicalK": 1, "sparseGraphK": 2, "candidates": 15},
    ]
    assert frontier._recall_cost_pareto(rows) == [
        {"lexicalK": 1, "sparseGraphK": 1, "candidates": 10, "found": 1},
        {"lexicalK": 2, "sparseGraphK": 1, "candidates": 14, "found": 2},
    ]
