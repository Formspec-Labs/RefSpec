"""E3/E5: cost-recall frontier over the deterministic and dense Atlas arms.

Consumes the compact rank artifacts written by
``benchmark_atlas_native_relation_recovery.py --export-ranks`` and
``benchmark_atlas_dense_relation_recovery.py``.  Both address pairs by the same
``low * conceptCount + high`` code over the concept list sorted by member IRI,
so deterministic and dense arms combine without re-deriving either.

The Conference Pareto search could prove optimality by branch and bound because
complete gold coverage was reachable there.  It is not reachable here: the
dependency-free union tops out near 69% of publisher hierarchy.  So the
objective is different, and the honest one is the trade-off curve rather than a
proven minimum:

* every single arm at every depth;
* every pair of arm-depth options, exhaustively; and
* greedy forward selection beyond two arms, which is a bound and is reported as
  one rather than as an optimum.

Each arm-depth option becomes a packed bitmap over the pair space, so a union
is a vectorised OR and a recall is a table-driven popcount.  Combinations are
evaluated in parallel batches over forked workers, which share the bitmaps
copy-on-write instead of pickling them per task.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_DEPTHS = (1, 5, 10, 20, 50, 100)

POPCOUNT = np.array([value.bit_count() for value in range(256)], dtype=np.uint32)

#: Arms whose evidence is a hash join rather than a ranked list, so depth does
#: not apply and only one option is generated.
UNRANKED_ARMS = frozenset({"exactPreferredLabel", "exactSharedAliasAnchor"})

_STATE: dict[str, Any] = {}


@dataclass(frozen=True, slots=True)
class Option:
    """One selectable arm at one depth."""

    arm: str
    depth: int

    @property
    def label(self) -> str:
        return self.arm if self.arm in UNRANKED_ARMS else f"{self.arm}@{self.depth}"


def _bitmap(codes: np.ndarray, bits: int) -> np.ndarray:
    flags = np.zeros(bits, dtype=bool)
    if codes.size:
        flags[codes.astype(np.int64)] = True
    return np.packbits(flags)


def _count(bitmap: np.ndarray) -> int:
    return int(POPCOUNT[bitmap].sum())


def load_source(directory: Path, source: str, depths: Sequence[int]) -> dict[str, Any]:
    """Build packed bitmaps for every arm-depth option plus gold and bands."""
    sparse_path = directory / f"sparse.{source}.npz"
    if not sparse_path.exists():
        raise FileNotFoundError(f"missing deterministic ranks: {sparse_path}")
    sparse = np.load(sparse_path)
    count = int(sparse["conceptCount"][0])
    bits = count * count

    options: dict[str, np.ndarray] = {}
    arm_names: list[str] = []

    def _add(arm: str, codes: np.ndarray, ranks: np.ndarray | None) -> None:
        arm_names.append(arm)
        if ranks is None or arm in UNRANKED_ARMS:
            options[Option(arm, 1).label] = _bitmap(codes, bits)
            return
        for depth in depths:
            selected = codes[ranks <= depth]
            options[Option(arm, depth).label] = _bitmap(selected, bits)

    for key in sparse.files:
        if key.endswith(".codes"):
            arm = key[: -len(".codes")]
            _add(arm, sparse[key], sparse.get(f"{arm}.ranks"))

    for path in sorted(directory.glob(f"*.{source}.npz")):
        if path.name.startswith("sparse."):
            continue
        model = path.name[: -len(f".{source}.npz")]
        bundle = np.load(path)
        for key in bundle.files:
            if key.endswith(".codes"):
                view = key[: -len(".codes")]
                _add(f"{model}.{view}", bundle[key], bundle[f"{view}.ranks"])

    gold = {key[len("gold.") :]: _bitmap(sparse[key], bits) for key in sparse.files if key.startswith("gold.")}
    # Additional gold classes (transitive closure, siblings) ship separately so
    # the asserted sets stay untouched and both can be scored in one pass.
    extra_path = directory / f"closure.{source}.npz"
    if extra_path.exists():
        extra = np.load(extra_path)
        for key in extra.files:
            if key.startswith("gold."):
                gold[key[len("gold.") :]] = _bitmap(extra[key], bits)
    gold_sizes = {name: _count(bitmap) for name, bitmap in gold.items()}
    bands = {key[len("band.") :]: _bitmap(sparse[key], bits) for key in sparse.files if key.startswith("band.")}
    return {
        "source": source,
        "conceptCount": count,
        "options": options,
        "gold": gold,
        "goldSizes": gold_sizes,
        "bands": bands,
        "armNames": sorted(set(arm_names)),
    }


def _init_worker(state: dict[str, Any]) -> None:
    _STATE.update(state)


def _evaluate(batch: Sequence[tuple[str, ...]]) -> list[dict[str, Any]]:
    options = _STATE["options"]
    gold = _STATE["gold"]
    results = []
    for combo in batch:
        union = options[combo[0]].copy()
        for label in combo[1:]:
            np.bitwise_or(union, options[label], out=union)
        entry: dict[str, Any] = {"arms": list(combo), "pairs": _count(union)}
        for name, bitmap in gold.items():
            entry[f"gold.{name}"] = _count(np.bitwise_and(union, bitmap))
        results.append(entry)
    return results


def _run_batches(
    combos: Sequence[tuple[str, ...]], state: dict[str, Any], workers: int, batch: int
) -> list[dict[str, Any]]:
    if not combos:
        return []
    chunks = [combos[start : start + batch] for start in range(0, len(combos), batch)]
    if workers <= 1:
        _STATE.update(state)
        return [row for chunk in chunks for row in _evaluate(chunk)]
    # ``fork`` lets workers share the packed bitmaps copy-on-write; ``spawn``
    # would pickle every bitmap into every worker for each batch.
    context = mp.get_context("fork")
    with context.Pool(workers, initializer=_init_worker, initargs=(state,)) as pool:
        return [row for chunk in pool.map(_evaluate, chunks) for row in chunk]


def _pareto(rows: Sequence[dict[str, Any]], gold_key: str) -> list[dict[str, Any]]:
    """Keep rows that no other row beats on both candidate cost and gold found."""
    ordered = sorted(rows, key=lambda row: (row["pairs"], -row[gold_key]))
    front: list[dict[str, Any]] = []
    best = -1
    for row in ordered:
        if row[gold_key] > best:
            front.append(row)
            best = row[gold_key]
    return front


def _greedy(state: dict[str, Any], gold_key: str, limit: int) -> list[dict[str, Any]]:
    options = state["options"]
    gold = state["gold"][gold_key[len("gold.") :]]
    chosen: list[str] = []
    union: np.ndarray | None = None
    trail: list[dict[str, Any]] = []
    for _step in range(limit):
        best_label, best_gain, best_union = None, 0, None
        for label, bitmap in options.items():
            if label in chosen:
                continue
            merged = bitmap if union is None else np.bitwise_or(union, bitmap)
            gain = _count(np.bitwise_and(merged, gold))
            if best_label is None or gain > best_gain:
                best_label, best_gain, best_union = label, gain, merged
        if best_label is None:
            break
        chosen.append(best_label)
        union = best_union
        trail.append({"arms": list(chosen), "pairs": _count(union), gold_key: best_gain})
    return trail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ranks", type=Path, required=True)
    parser.add_argument("--source", action="append")
    parser.add_argument("--depths", type=int, nargs="+", default=list(DEFAULT_DEPTHS))
    parser.add_argument("--relation-class", default=None, help="Restrict the frontier to one gold class.")
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 2))
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--greedy-limit", type=int, default=6)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    sources = args.source or sorted(
        path.name[len("sparse.") : -len(".npz")] for path in args.ranks.glob("sparse.*.npz")
    )
    depths = tuple(sorted(set(args.depths)))
    results = []

    for source in sources:
        state = load_source(args.ranks, source, depths)
        labels = sorted(state["options"])
        singles: list[tuple[str, ...]] = [(label,) for label in labels]
        pairs: list[tuple[str, ...]] = list(combinations(labels, 2))
        print(
            f"\n=== {source}  concepts={state['conceptCount']}  arms={len(state['armNames'])} "
            f"options={len(labels)}  combos={len(singles) + len(pairs)}  workers={args.workers}"
        )

        rows = _run_batches(singles + pairs, state, args.workers, args.batch)
        classes = [args.relation_class] if args.relation_class else sorted(state["gold"])
        entry: dict[str, Any] = {
            "source": source,
            "conceptCount": state["conceptCount"],
            "goldSizes": state["goldSizes"],
            "options": len(labels),
            "byRelationClass": {},
        }
        for relation_class in classes:
            gold_key = f"gold.{relation_class}"
            total = state["goldSizes"][relation_class]
            best_single = max((row for row in rows if len(row["arms"]) == 1), key=lambda row: row[gold_key])
            front = _pareto(rows, gold_key)
            greedy = _greedy(state, gold_key, args.greedy_limit)
            entry["byRelationClass"][relation_class] = {
                "gold": total,
                "bestSingleArm": best_single,
                "paretoFront": front,
                "greedyTrail": greedy,
            }
            print(f"  -- {relation_class}: gold={total}")
            print(
                f"     best single   {best_single['arms'][0]:<34} "
                f"pairs={best_single['pairs']:>8} gold={best_single[gold_key]:>5} "
                f"({best_single[gold_key] / total:.1%})"
            )
            for step in greedy:
                print(
                    f"     greedy +{len(step['arms']):<2}     {step['arms'][-1]:<34} "
                    f"pairs={step['pairs']:>8} gold={step[gold_key]:>5} ({step[gold_key] / total:.1%})"
                )
        results.append(entry)

    payload = {
        "type": "AtlasNativeRelationFrontier",
        "experiment": "E3-E5-cost-recall-frontier",
        "depths": list(depths),
        "note": "greedy rows are an upper bound on cost for their recall, not a proven optimum",
        "results": results,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
