"""E3 reranker half: cross-encoder and late-interaction rescue over a reservoir.

A reranker scores pairs it is given.  It cannot propose a pair no other arm
found, so its recall is bounded above by the reservoir it reads and it is never
a discovery arm.  The candidate-retrieval ledger measured exactly this and
found neither reranker on any exact complete Conference frontier, while MiniLM
still recovered all six baseline misses at bidirectional K=25 as an add-only
rescue and took 5/5 directional property-wording cases where ColBERT took 0/5.

That directional result is the reason to run them here.  Direction is the
weakest axis in the whole programme -- the historical judge audit agreed on
support 102/108 but on exact relation only 74/108, with type and direction
dominating every dispute -- and the ledger's evidence for MiniLM came from
conference property inverses such as ``hasAuthor``/``writtenBy``, nothing like
``WOMEN``/``MARRIED WOMEN``.

The reservoir is the union of every arm already scored for a source, so these
runs measure ordering quality against the same pool the other families built.
Per-concept reservoir size is capped and the number of pairs dropped by that
cap is reported rather than left silent.

Needs SentenceTransformers, and the ``rerankers`` package for late interaction:
``uv run --no-project --with "sentence-transformers>=5" --with rerankers --with numpy python ...``
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

MODELS: tuple[dict[str, Any], ...] = (
    {"key": "minilm-ce", "name": "cross-encoder/ms-marco-MiniLM-L6-v2", "kind": "cross-encoder"},
    {"key": "colbert", "name": "answerdotai/answerai-colbert-small-v1", "kind": "late-interaction"},
)

VIEW = "label"


def build_reservoir(ranks: Path, source: str, cap: int) -> tuple[dict[int, list[int]], int, int, int]:
    """Union every scored arm into one per-concept candidate reservoir."""
    neighbours: dict[int, set[int]] = defaultdict(set)
    count = 0
    total = 0
    for path in sorted(ranks.glob(f"*.{source}.npz")):
        bundle = np.load(path)
        count = int(bundle["conceptCount"][0])
        for key in bundle.files:
            if not key.endswith(".codes"):
                continue
            for code in bundle[key]:
                value = int(code)
                low, high = divmod(value, count)
                neighbours[low].add(high)
                neighbours[high].add(low)
                total += 1
    capped = 0
    reservoir: dict[int, list[int]] = {}
    for node, partners in neighbours.items():
        ordered = sorted(partners)
        if len(ordered) > cap:
            capped += len(ordered) - cap
            ordered = ordered[:cap]
        reservoir[node] = ordered
    distinct = len({(min(a, b), max(a, b)) for a, partners in reservoir.items() for b in partners})
    return reservoir, count, distinct, capped


def score_cross_encoder(model: Any, pairs: list[tuple[str, str]], batch_size: int) -> np.ndarray:
    return np.asarray(model.predict(pairs, batch_size=batch_size, show_progress_bar=False), dtype=np.float32)


def score_late_interaction(model: Any, texts: list[str], reservoir: dict[int, list[int]]) -> dict[int, float]:
    """Score each query against its own reservoir slice, one query at a time."""
    scores: dict[int, float] = {}
    count = len(texts)
    for node, partners in reservoir.items():
        if not partners:
            continue
        results = model.rank(query=texts[node], docs=[texts[other] for other in partners])
        for result in results.results:
            other = partners[result.doc_id]
            low, high = (node, other) if node < other else (other, node)
            code = low * count + high
            scores[code] = max(scores.get(code, float("-inf")), float(result.score))
    return scores


def min_ranks(scores: dict[int, float], reservoir: dict[int, list[int]], count: int, top_k: int) -> dict[int, int]:
    """Best bidirectional rank per pair from reranker scores within the reservoir."""
    best: dict[int, int] = {}
    for node, partners in reservoir.items():
        scored = []
        for other in partners:
            low, high = (node, other) if node < other else (other, node)
            code = low * count + high
            if code in scores:
                scored.append((-scores[code], other, code))
        scored.sort()
        for rank, (_negative, _other, code) in enumerate(scored[:top_k], start=1):
            if rank < best.get(code, top_k + 1):
                best[code] = rank
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--ranks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", action="append", choices=[spec["key"] for spec in MODELS])
    parser.add_argument("--source", action="append")
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--reservoir-cap", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    specs = [spec for spec in MODELS if not args.model or spec["key"] in args.model]

    for spec in specs:
        print(f"\n=== {spec['name']}  ({spec['kind']})")
        if spec["kind"] == "cross-encoder":
            from sentence_transformers import CrossEncoder

            model = CrossEncoder(spec["name"])
        else:
            from rerankers import Reranker

            model = Reranker(spec["name"], model_type="colbert")

        for entry in corpus["sources"]:
            source = entry["source"]
            if args.source and source not in args.source:
                continue
            target = args.output / f"{spec['key']}.{source}.npz"
            if target.exists():
                print(f"  skip {spec['key']} {source} (already present)")
                continue
            texts = [" | ".join([item["label"], *(item.get("altLabels") or [])]) for item in entry["concepts"]]
            reservoir, count, distinct, capped = build_reservoir(args.ranks, source, args.reservoir_cap)
            started = time.perf_counter()
            if spec["kind"] == "cross-encoder":
                flat = [(texts[node], texts[other]) for node, partners in reservoir.items() for other in partners]
                keys = [
                    (min(node, other) * count + max(node, other))
                    for node, partners in reservoir.items()
                    for other in partners
                ]
                values = score_cross_encoder(model, flat, args.batch_size)
                scores: dict[int, float] = {}
                for code, value in zip(keys, values, strict=True):
                    scores[code] = max(scores.get(code, float("-inf")), float(value))
            else:
                scores = score_late_interaction(model, texts, reservoir)
            ranks = min_ranks(scores, reservoir, count, args.top_k)
            codes = np.fromiter(ranks.keys(), dtype=np.uint32, count=len(ranks))
            rank_values = np.fromiter(ranks.values(), dtype=np.uint8, count=len(ranks))
            order = np.argsort(codes, kind="stable")
            np.savez_compressed(
                target,
                conceptCount=np.asarray([count], dtype=np.uint32),
                **{f"{VIEW}.codes": codes[order], f"{VIEW}.ranks": rank_values[order]},
            )
            (args.output / f"{spec['key']}.{source}.meta.json").write_text(
                json.dumps(
                    {
                        "model": spec["name"],
                        "kind": spec["kind"],
                        "source": source,
                        "reservoirPairs": distinct,
                        "reservoirCapPerConcept": args.reservoir_cap,
                        "pairsDroppedByCap": capped,
                        "retainedPairs": len(ranks),
                        "seconds": round(time.perf_counter() - started, 1),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            print(
                f"  {spec['key']:<10} {source:<34} reservoir={distinct:<9,} dropped_by_cap={capped:<8,} "
                f"retained={len(ranks):<8,} {time.perf_counter() - started:>7.1f}s"
            )
        del model
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
