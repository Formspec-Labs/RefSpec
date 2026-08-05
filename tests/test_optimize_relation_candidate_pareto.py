from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from optimize_relation_candidate_pareto import (
    build_signature_model,
    load_bundle,
    optimize_bundle,
    solve_configuration,
    write_bundle,
)


def _bundle(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic-pareto.npz"
    anchor_policy = "exact normalized labels plus mutual top-1 across all declared sparse views"
    arms = [
        {"id": "local-a", "family": "local", "kind": "deterministic", "depths": [1, 2]},
        {"id": "local-b", "family": "local", "kind": "deterministic", "depths": [1, 2]},
        {
            "id": "provider",
            "family": "provider",
            "kind": "provider-embedding",
            "depths": [1],
        },
        {
            "id": "reranker",
            "family": "reranker",
            "kind": "reranker",
            "depths": [1],
            "reservoirId": "wide",
        },
        {
            "id": "gated-graph",
            "family": "graph",
            "kind": "graph",
            "depths": [1],
            "anchorPolicy": anchor_policy,
            "anchorPolicyDigest": "sha256:" + "a" * 64,
        },
    ]
    # Three gold pairs are indexes 0, 1, and 2.  The graph arm is deliberately
    # empty: this checks its policy receipt without affecting the known front.
    ranks = np.asarray(
        [
            [1, 2, 0, 1, 2, 0, 0, 0],  # local-a
            [0, 1, 2, 0, 0, 1, 2, 0],  # local-b
            [1, 1, 1, 1, 1, 1, 0, 0],  # provider: one arm, six candidates
            [0, 0, 1, 0, 0, 0, 0, 0],  # reranker: one reservoir-contained rescue
            [0, 0, 0, 0, 0, 0, 0, 0],
        ],
        dtype=np.uint8,
    )
    write_bundle(
        path,
        layouts=[
            {
                "name": "case",
                "sources": ["s"],
                "targets": [f"t{index}" for index in range(8)],
                "goldFlatIndexes": [0, 1, 2],
            }
        ],
        arms=arms,
        ranks=ranks,
        reservoirs={"wide": np.asarray([0, 0, 1, 0, 0, 0, 1, 0], dtype=np.bool_)},
        challenges={"0": ["lexical"], "1": ["lexical"], "2": ["semantic"]},
    )
    return path


def test_exact_frontiers_include_no_provider_and_no_reranker(tmp_path: Path) -> None:
    bundle = load_bundle(_bundle(tmp_path))

    result = optimize_bundle(bundle, solver="brute-force")

    unrestricted = result["frontiers"]["unrestricted"]
    assert [(row["activeArmCount"], row["candidateCount"]) for row in unrestricted["pareto"]] == [
        (1, 6),
        (2, 5),
    ]
    assert unrestricted["minimumCandidateCompleteUnion"]["goldFound"] == 3
    assert result["frontiers"]["no-provider"]["minimumCandidateCompleteUnion"]["candidateCount"] == 5
    assert result["frontiers"]["no-reranker"]["minimumCandidateCompleteUnion"]["candidateCount"] == 6
    local_only = result["frontiers"]["no-provider-no-reranker"]["minimumCandidateCompleteUnion"]
    assert local_only["candidateCount"] == 6
    assert local_only["providerArmCount"] == 0
    assert local_only["rerankerArmCount"] == 0


def test_signature_solver_matches_direct_exhaustive_union(tmp_path: Path) -> None:
    bundle = load_bundle(_bundle(tmp_path))
    model = build_signature_model(bundle)

    selected_mask, candidate_count = solve_configuration(
        model,
        allow_provider=False,
        allow_reranker=True,
        active_cap=2,
        solver="brute-force",
    )

    selected_options = [index for index in range(len(model.options)) if selected_mask & (1 << index)]
    direct = np.zeros(bundle.pair_count, dtype=np.bool_)
    for option_index in selected_options:
        option = model.options[option_index]
        direct |= (bundle.ranks[option.arm_index] > 0) & (bundle.ranks[option.arm_index] <= option.depth)
    assert int(np.count_nonzero(direct)) == candidate_count == 5


def test_branch_and_bound_matches_exhaustive_frontier(tmp_path: Path) -> None:
    bundle = load_bundle(_bundle(tmp_path))

    exhaustive = optimize_bundle(bundle, solver="brute-force")
    bounded = optimize_bundle(bundle, solver="branch-and-bound")

    assert {
        name: [
            (point["candidateCount"], point["activeArmCount"], point["pairSetDigest"]) for point in frontier["pareto"]
        ]
        for name, frontier in exhaustive["frontiers"].items()
    } == {
        name: [
            (point["candidateCount"], point["activeArmCount"], point["pairSetDigest"]) for point in frontier["pareto"]
        ]
        for name, frontier in bounded["frontiers"].items()
    }


def test_repeat_has_identical_frontier_and_pair_digests(tmp_path: Path) -> None:
    bundle = load_bundle(_bundle(tmp_path))

    first = optimize_bundle(bundle, solver="brute-force")
    second = optimize_bundle(bundle, solver="brute-force")

    assert first["resultDigest"] == second["resultDigest"]
    assert (
        first["frontiers"]["unrestricted"]["minimumCandidateCompleteUnion"]["pairSetDigest"]
        == second["frontiers"]["unrestricted"]["minimumCandidateCompleteUnion"]["pairSetDigest"]
    )


def test_rejects_reranker_candidates_outside_declared_reservoir(tmp_path: Path) -> None:
    path = _bundle(tmp_path)
    with np.load(path, allow_pickle=False) as archive:
        ranks = np.asarray(archive["ranks"]).copy()
    ranks[3, 7] = 1
    # Rewriting through the supported writer preserves valid digests, so the
    # failure specifically proves the reservoir subset check.
    bad = tmp_path / "bad-reservoir.npz"
    original = load_bundle(path)
    write_args = {
        "layouts": original.metadata["layouts"],
        "arms": original.metadata["arms"],
        "ranks": ranks,
        "reservoirs": original.reservoirs,
        "challenges": original.metadata["challenges"],
    }
    with pytest.raises(ValueError, match="outside its reservoir"):
        write_bundle(bad, **write_args)


def test_rejects_graph_arm_without_anchor_policy(tmp_path: Path) -> None:
    path = tmp_path / "bad-graph.npz"
    with pytest.raises(ValueError, match="anchorPolicy"):
        write_bundle(
            path,
            layouts=[{"name": "case", "sources": ["s"], "targets": ["t"], "goldFlatIndexes": [0]}],
            arms=[{"id": "graph", "kind": "graph", "family": "graph", "depths": [1]}],
            ranks=np.asarray([[1]], dtype=np.uint8),
        )
