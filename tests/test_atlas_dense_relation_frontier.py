"""E3 dense relation runner and cost-recall frontier: views, blockwise ranks, bitmaps, and greedy selection."""

from __future__ import annotations

import numpy as np
import pytest

from tools import benchmark_atlas_dense_relation_recovery as dense
from tools import optimize_atlas_native_relation_frontier as frontier


def _concept(label: str, *, aliases=(), definition=None, notes=None) -> dict[str, object]:
    """Build a minimal concept dict for the view-shaping checks."""

    return {"label": label, "altLabels": list(aliases), "definition": definition, "notes": notes}


def test_label_view_uses_labels_only_and_ignores_definition() -> None:
    """Pins that the label view joins preferred and alternate labels and drops the definition."""

    concept = _concept("Housing", aliases=("Shelter",), definition="a definition")

    assert dense.view_text(concept, "label") == "Housing | Shelter"


def test_structured_view_tags_every_available_field() -> None:
    """Pins that the structured view tags each available field in label/aliases/definition/notes order."""

    text = dense.view_text(_concept("Housing", aliases=("Shelter",), definition="d", notes="n"), "structured")

    assert text == "label: Housing | aliases: Shelter | definition: d | notes: n"


def test_definition_first_view_leads_with_definition_then_falls_back_to_notes() -> None:
    """Pins that definitionFirst leads with the definition, falls back to notes, and ends with the label."""

    assert dense.view_text(_concept("A", definition="d"), "definitionFirst") == "d A"
    assert dense.view_text(_concept("A", notes="n"), "definitionFirst") == "n A"


def test_definition_first_view_collapses_to_the_label_without_text() -> None:
    """Pins that definitionFirst with no definition or notes collapses to the label alone."""

    # Federal Register and ICPSR carry no definitions, so this view degenerates.
    assert dense.view_text(_concept("A"), "definitionFirst") == "A"


def test_unsupported_view_fails_closed() -> None:
    """Pins that an unknown view name raises ValueError instead of falling back to a default view."""

    with pytest.raises(ValueError, match="unsupported view"):
        dense.view_text(_concept("A"), "hierarchyFirst")


def test_blockwise_ranks_exclude_self_and_match_across_block_sizes() -> None:
    """Pins that blockwise ranks exclude self and are identical at block 64 and block 3."""

    rng = np.random.default_rng(11)
    vectors = rng.normal(size=(23, 8)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    whole = dense.blockwise_min_ranks(vectors, top_k=5, block=64)
    blocked = dense.blockwise_min_ranks(vectors, top_k=5, block=3)

    assert whole == blocked
    count = vectors.shape[0]
    assert all(code // count != code % count for code in whole)


def test_blockwise_ranks_keep_the_better_of_the_two_directions() -> None:
    """Pins that keeping the better of the two scan directions ranks a near neighbor 1, never 0."""

    vectors = np.asarray([[1.0, 0.0], [0.95, 0.31], [0.0, 1.0]], dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    ranks = dense.blockwise_min_ranks(vectors, top_k=2, block=8)

    assert ranks[0 * 3 + 1] == 1
    assert all(rank >= 1 for rank in ranks.values())


def test_bitmap_and_popcount_round_trip() -> None:
    """Pins that a code bitmap counts exactly its codes, including the empty set."""

    codes = np.asarray([0, 5, 63, 64], dtype=np.uint32)

    bitmap = frontier._bitmap(codes, 100)

    assert frontier._count(bitmap) == 4
    assert frontier._count(frontier._bitmap(np.asarray([], dtype=np.uint32), 100)) == 0


def test_option_labels_drop_the_depth_for_unranked_anchor_arms() -> None:
    """Pins that anchor arms omit the @depth suffix while depth-ranked options keep it."""

    assert frontier.Option("exactSharedAliasAnchor", 50).label == "exactSharedAliasAnchor"
    assert frontier.Option("labelSparseV1", 50).label == "labelSparseV1@50"


def test_pareto_front_keeps_only_non_dominated_rows() -> None:
    """Pins that the Pareto front drops a row that costs more and finds less than another."""

    rows = [
        {"arms": ["a"], "pairs": 100, "gold.x": 10},
        {"arms": ["b"], "pairs": 200, "gold.x": 8},  # costs more, finds less
        {"arms": ["c"], "pairs": 300, "gold.x": 20},
    ]

    front = frontier._pareto(rows, "gold.x")

    assert [row["arms"][0] for row in front] == ["a", "c"]


def test_evaluate_unions_arms_and_counts_gold_intersection() -> None:
    """Pins that combining arms unions their candidate pairs and counts gold intersections per scheme."""

    state = {
        "options": {
            "a": frontier._bitmap(np.asarray([1, 2], dtype=np.uint32), 32),
            "b": frontier._bitmap(np.asarray([2, 3], dtype=np.uint32), 32),
        },
        "gold": {"h": frontier._bitmap(np.asarray([2, 3, 9], dtype=np.uint32), 32)},
    }

    (single,) = frontier._run_batches([("a",)], state, workers=1, batch=8)
    (both,) = frontier._run_batches([("a", "b")], state, workers=1, batch=8)

    assert single["pairs"] == 2
    assert single["gold.h"] == 1
    assert both["pairs"] == 3
    assert both["gold.h"] == 2


def test_evaluate_does_not_mutate_the_stored_option_bitmaps() -> None:
    """Pins that evaluating a union leaves every stored option bitmap unchanged."""

    option = frontier._bitmap(np.asarray([1], dtype=np.uint32), 32)
    state = {
        "options": {"a": option, "b": frontier._bitmap(np.asarray([5], dtype=np.uint32), 32)},
        "gold": {"h": frontier._bitmap(np.asarray([1], dtype=np.uint32), 32)},
    }

    frontier._run_batches([("a", "b")], state, workers=1, batch=8)

    assert frontier._count(state["options"]["a"]) == 1


def test_greedy_selects_the_highest_marginal_gold_first() -> None:
    """Pins that greedy selection adds the arm with the highest marginal gold first."""

    state = {
        "options": {
            "weak": frontier._bitmap(np.asarray([1], dtype=np.uint32), 64),
            "strong": frontier._bitmap(np.asarray([1, 2, 3], dtype=np.uint32), 64),
        },
        "gold": {"h": frontier._bitmap(np.asarray([1, 2, 3], dtype=np.uint32), 64)},
    }

    trail = frontier._greedy(state, "gold.h", limit=2)

    assert trail[0]["arms"] == ["strong"]
    assert trail[0]["gold.h"] == 3
