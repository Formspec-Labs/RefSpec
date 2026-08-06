"""E3 lexical half: the sealed RapidFuzz control matrix over the ablated corpus.

The first E3 pass measured three sparse views and two hash-join anchors, and
reported their ceiling as the deterministic floor.  That was incomplete.  The
candidate-retrieval ledger's strongest single deterministic control on the real
Atlas was alias WRatio (461/582 at K1, 558/582 at K100, 43 unique top-10
rescues), and no RapidFuzz arm had been run against the native-relation test
sets at all.

This tool closes that gap by importing ``SCORER_SPECS`` and the scoring and
tie-break helpers from ``benchmark_lexical_candidate_controls`` unchanged, so
every arm here is the same declared representation and metric the sealed
receipts used.  Only the task differs: intra-vocabulary retrieval over the
ablated corpus rather than cross-vocabulary candidate generation.

Two arms are expected to be inert here rather than weak, and are reported
rather than dropped.  ``identifier-qratio`` compares local identifiers that are
unique inside a single release, and ``alias-bag`` variants collapse toward the
plain label wherever a source publishes no attached alternate labels.

Results are written in the same compact ``npz`` layout as the dense and hosted
arms, so the Pareto stage consumes all three families together.

Needs RapidFuzz, which is not a project dependency:
``uv run --with rapidfuzz python tools/benchmark_atlas_native_lexical_recovery.py ...``
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import benchmark_lexical_candidate_controls as controls


class Concept:
    """Minimal surface satisfying ``controls.representation_text``."""

    __slots__ = ("alt_labels", "member", "pref_label")

    def __init__(self, member: str, pref_label: str, alt_labels: tuple[str, ...]) -> None:
        self.member = member
        self.pref_label = pref_label
        self.alt_labels = alt_labels


def load_concepts(corpus: dict[str, Any], source: str) -> list[Concept]:
    entry = next(item for item in corpus["sources"] if item["source"] == source)
    return [Concept(item["member"], item["label"], tuple(item.get("altLabels") or ())) for item in entry["concepts"]]


def arm_ranks(concepts: list[Concept], spec: Any, top_k: int, workers: int) -> dict[int, int]:
    """Best bidirectional rank per unordered pair for one declared scorer arm."""
    texts = [controls.representation_text(concept, spec.representation) for concept in concepts]
    count = len(texts)
    matrix = controls.score_matrix(texts, texts, spec=spec, workers=workers)
    best: dict[int, int] = {}
    for row_index in range(count):
        # One extra neighbour is requested because a concept always matches
        # itself perfectly; the self hit is dropped before ranks are assigned.
        ordered = controls.stable_top_indices(
            matrix[row_index], higher_is_better=spec.higher_is_better, top_k=top_k + 1
        )
        rank = 0
        for neighbour in ordered:
            if neighbour == row_index:
                continue
            rank += 1
            if rank > top_k:
                break
            low, high = (row_index, neighbour) if row_index < neighbour else (neighbour, row_index)
            code = low * count + high
            if rank < best.get(code, top_k + 1):
                best[code] = rank
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", action="append")
    parser.add_argument("--practical-only", action="store_true", help="Run only the seven-arm practical profile.")
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--workers", type=int, default=-1)
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    sources = args.source or [entry["source"] for entry in corpus["sources"]]
    specs = [
        spec for spec in controls.SCORER_SPECS if not args.practical_only or spec.name in controls.PRACTICAL_ARM_NAMES
    ]
    args.output.mkdir(parents=True, exist_ok=True)

    for source in sources:
        target = args.output / f"lexical.{source}.npz"
        if target.exists():
            print(f"  skip {source} (already present)")
            continue
        concepts = load_concepts(corpus, source)
        payload: dict[str, np.ndarray] = {"conceptCount": np.asarray([len(concepts)], dtype=np.uint32)}
        meta: dict[str, Any] = {}
        print(f"\n=== {source}  concepts={len(concepts)}  arms={len(specs)}")
        for spec in specs:
            started = time.perf_counter()
            ranks = arm_ranks(concepts, spec, args.top_k, args.workers)
            codes = np.fromiter(ranks.keys(), dtype=np.uint32, count=len(ranks))
            values = np.fromiter(ranks.values(), dtype=np.uint8, count=len(ranks))
            order = np.argsort(codes, kind="stable")
            payload[f"{spec.name}.codes"] = codes[order]
            payload[f"{spec.name}.ranks"] = values[order]
            distinct = len({controls.representation_text(concept, spec.representation) for concept in concepts})
            meta[spec.name] = {
                "representation": spec.representation,
                "metric": spec.metric,
                "family": spec.family,
                "higherIsBetter": spec.higher_is_better,
                "distinctTexts": distinct,
                "retainedPairs": len(ranks),
                "seconds": round(time.perf_counter() - started, 2),
            }
            print(
                f"  {spec.name:<30} {spec.representation:<20} distinct={distinct:<5} "
                f"pairs={len(ranks):<8} {meta[spec.name]['seconds']:>6.1f}s"
            )
        np.savez_compressed(target, **payload)
        (args.output / f"lexical.{source}.meta.json").write_text(
            json.dumps({"source": source, "topK": args.top_k, "arms": meta}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
