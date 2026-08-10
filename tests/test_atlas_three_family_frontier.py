"""Focused checks for the experimental Atlas three-family frontier."""

from __future__ import annotations

from pathlib import Path

from refspec.atlas.candidate_retrieval import AtlasConcept, AtlasConceptContext
from tools import benchmark_atlas_candidate_retrieval as shared
from tools import benchmark_atlas_three_family_frontier as frontier
from tools import benchmark_lexical_candidate_controls as lexical


def _concept(side: str, identifier: str) -> AtlasConcept:
    return AtlasConcept(
        member=f"https://example.test/{side}/{identifier}",
        release=f"urn:test:{side}",
        pref_label=f"Label {identifier}",
        alt_labels=(f"Alternate {identifier}",),
        definition=f"Definition for {identifier}.",
        scope_note=f"Scope for {identifier}.",
        parents=(
            AtlasConceptContext(
                member=f"https://example.test/{side}/parent-{identifier}",
                pref_label=f"Parent {identifier}",
            ),
        ),
    )


def _fixture() -> tuple[tuple[shared.AlignmentCase, ...], lexical.PairCodec, object]:
    sources = (_concept("source", "a"), _concept("source", "b"))
    targets = tuple(_concept("target", value) for value in ("a", "b", "c", "d"))
    case = shared.AlignmentCase(
        "example",
        sources,
        targets,
        frozenset({(sources[0].member, targets[0].member), (sources[1].member, targets[1].member)}),
    )
    cases = (case,)
    codec = lexical.PairCodec.from_cases(cases)
    compact = shared._CompactPairRanks.empty(cases, frontier.BGE_RETAIN_MAXIMUM)
    compact.ranks[0][:] = compact.sentinel
    compact.ranks[0][0, 0] = 1
    compact.ranks[0][0, 1] = 3
    compact.ranks[0][0, 2] = 18
    compact.ranks[0][1, 2] = 22
    compact.ranks[0][1, 3] = 37
    return cases, codec, compact


def test_compact_rank_sets_and_raw_artifact_are_exact_and_deterministic(tmp_path: Path) -> None:
    _cases, codec, compact = _fixture()

    sets = frontier._sets_from_compact(compact, codec, (1, 3, 20, 50))
    assert [len(sets[depth]) for depth in (1, 3, 20, 50)] == [1, 2, 3, 5]

    first = tmp_path / "first.ranks"
    second = tmp_path / "second.ranks"
    first_manifest = frontier.write_compact_rank_artifact(compact, first)
    second_manifest = frontier.write_compact_rank_artifact(compact, second)
    assert first.read_bytes() == second.read_bytes()
    assert first_manifest["sha256"] == second_manifest["sha256"]
    assert first_manifest["bytes"] == 8
    assert first_manifest["dtype"] == "uint8"
    assert first_manifest["sentinel"] == 51


def test_exact_union_and_bge_marginal_keep_typed_gold_and_pair_digests() -> None:
    cases, codec, compact = _fixture()
    gold = lexical._gold_codes(cases, codec)
    first_gold, second_gold = sorted(gold)
    lexical_pairs = frozenset({first_gold})
    sparse_pairs = frozenset({second_gold})
    bge_pairs = frontier._sets_from_compact(compact, codec, (3,))[3]
    gold_by_relation = {
        "exact": frozenset({first_gold}),
        "close": frozenset(),
        "broad": frozenset(),
        "narrow": frozenset(),
        "related": frozenset({second_gold}),
    }

    row = frontier.summarize_combination(
        lexical_depth=1,
        sparse_depth=1,
        bge_depth=3,
        lexical_pairs=lexical_pairs,
        sparse_pairs=sparse_pairs,
        bge_pairs=bge_pairs,
        gold=gold,
        gold_by_relation=gold_by_relation,
        codec=codec,
    )
    assert row["candidates"] == 3
    assert row["found"] == 2
    assert row["typedRelations"]["exact"] == {"gold": 1, "found": 1}
    assert row["typedRelations"]["related"] == {"gold": 1, "found": 1}
    assert row["pairSetDigest"].startswith("sha256:")

    marginal = frontier.summarize_bge_marginal(
        bge_depth=3,
        lean_pairs=lexical_pairs | sparse_pairs,
        bge_pairs=bge_pairs,
        gold=gold,
        gold_by_relation=gold_by_relation,
        codec=codec,
    )
    assert marginal["bgeOnlyCandidates"] == 1
    assert marginal["bgeOnlyGold"] == 0
    assert marginal["unionCandidates"] == 3
    assert marginal["unionFound"] == 2


def test_review_sample_is_stratified_and_includes_actual_bge_context() -> None:
    cases, codec, compact = _fixture()
    overlap = frozenset({codec.code(0, 0, 0)})

    sample = frontier.build_review_sample(
        cases=cases,
        codec=codec,
        bge_compact=compact,
        lexical_pairs=overlap,
        sparse_pairs=overlap,
    )

    assert [(row["sampleCategory"], row["rankBand"]) for row in sample["rows"]] == [
        ("bge-only", "ranks-2-3"),
        ("bge-only", "ranks-16-20"),
        ("three-family-overlap", "rank-1"),
        ("just-outside-bge20", "ranks-21-25"),
    ]
    assert sample["rows"][0]["source"]["prefLabel"] == "Label a"
    assert sample["rows"][0]["source"]["parents"][0]["prefLabel"] == "Parent a"
    assert set(sample["rows"][0]["source"]["bgeViewTexts"]) == set(frontier.BGE_VIEWS)
    assert sample["rows"][0]["membershipAtReviewDepths"]["leanTwoFamilyFloor"] is False
    assert sample["rows"][2]["membershipAtReviewDepths"]["allThree"] is True
    assert sample["rows"][3]["membershipAtReviewDepths"]["bgeK20"] is False
    assert "typedGold" not in sample["rows"][0]
    assert "typedRelation" not in sample["rows"][0]
    assert sample["sampleDigest"].startswith("sha256:")


def test_three_family_depth_pareto_retains_incomparable_complete_rows() -> None:
    rows = [
        {"lexicalK": 1, "sparseGraphK": 1, "bgeK": 1, "candidates": 10, "found": 1},
        {"lexicalK": 2, "sparseGraphK": 1, "bgeK": 1, "candidates": 15, "found": 2},
        {"lexicalK": 1, "sparseGraphK": 2, "bgeK": 1, "candidates": 14, "found": 2},
        {"lexicalK": 1, "sparseGraphK": 1, "bgeK": 2, "candidates": 13, "found": 2},
        {"lexicalK": 2, "sparseGraphK": 2, "bgeK": 2, "candidates": 20, "found": 2},
    ]

    assert frontier._depth_pareto_complete(rows, 2) == [
        {"lexicalK": 1, "sparseGraphK": 1, "bgeK": 2, "candidates": 13},
        {"lexicalK": 1, "sparseGraphK": 2, "bgeK": 1, "candidates": 14},
        {"lexicalK": 2, "sparseGraphK": 1, "bgeK": 1, "candidates": 15},
    ]
