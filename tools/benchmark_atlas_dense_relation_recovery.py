"""E3 dense half: local embedding families over the ablated Atlas corpus.

Runs in an isolated environment with only ``fastembed`` and ``numpy``, so it
imports nothing from ``refspec``.  The companion tool
``benchmark_atlas_native_relation_recovery.py --export-corpus`` writes the exact
ablated text this reads, which keeps both halves of E3 scoring one corpus.

Two resource lessons from the candidate-retrieval ledger are built in.  Model
families run strictly one after another because a concurrent Anatomy run was
killed at exit status 137 and MiniCOIL peaked at 21.935 GB.  Similarity is
computed in fixed query blocks rather than a full concept-by-concept matrix,
matching the memory-bounded harness that cut a five-view Anatomy run from
1,203 to 691 seconds.

Only pairs reaching the deepest requested rank are retained, as compact
``uint32`` pair codes plus ``uint8`` ranks, so every model and view together
stay small enough to feed the frontier stage.  Each ``(model, source)`` result
is written as it completes and skipped on a rerun, so an interrupted sweep
resumes without recomputing.

The hierarchy-first view of the original five-view design is absent by
construction: hierarchy is ablated, so that view would duplicate the label
view.  Prefix conventions follow each model card, except that BGE runs plain
symmetric because the sealed Conference ablation measured its documented
retrieval prefix as a loss (295/305 against 297/305).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

#: Model families and the input convention each one is run under.  ``prefix``
#: is applied to both sides because the task is symmetric concept-to-concept
#: matching rather than query-to-document retrieval.
MODELS: tuple[dict[str, Any], ...] = (
    {"name": "BAAI/bge-small-en-v1.5", "key": "bge-small", "prefix": "", "convention": "plainSymmetric"},
    {"name": "sentence-transformers/all-MiniLM-L6-v2", "key": "minilm", "prefix": "", "convention": "plainSymmetric"},
    {
        "name": "nomic-ai/nomic-embed-text-v1.5-Q",
        "key": "nomic",
        "prefix": "search_document: ",
        "convention": "documentPrefixBothSides",
    },
    {
        "name": "snowflake/snowflake-arctic-embed-s",
        "key": "arctic",
        "prefix": "",
        "convention": "plainSymmetricQueryPrefixIsQueryOnly",
    },
    {
        "name": "jinaai/jina-embeddings-v2-small-en",
        "key": "jina",
        "prefix": "",
        "convention": "plainSymmetric",
    },
)

VIEWS = ("label", "structured", "natural", "definitionFirst")

DEFAULT_DEPTHS = (1, 2, 3, 5, 10, 20, 50, 100)


def view_text(concept: dict[str, Any], view: str) -> str:
    """Render one concept under one view, using only un-ablated fields."""
    label = str(concept.get("label") or "")
    aliases = [str(value) for value in concept.get("altLabels") or ()]
    definition = concept.get("definition")
    notes = concept.get("notes")

    if view == "label":
        return " | ".join([label, *aliases]) if aliases else label
    if view == "structured":
        parts = [f"label: {label}"]
        if aliases:
            parts.append(f"aliases: {'; '.join(aliases)}")
        if definition:
            parts.append(f"definition: {definition}")
        if notes:
            parts.append(f"notes: {notes}")
        return " | ".join(parts)
    if view == "natural":
        parts = [f"The concept {label}."]
        if aliases:
            parts.append(f"It is also known as {', '.join(aliases)}.")
        if definition:
            parts.append(str(definition))
        if notes:
            parts.append(str(notes))
        return " ".join(parts)
    if view == "definitionFirst":
        lead = str(definition or notes or "")
        return f"{lead} {label}".strip() if lead else label
    raise ValueError(f"unsupported view: {view!r}")


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def embed(model: Any, texts: list[str], batch_size: int) -> np.ndarray:
    """Encode in fixed batches and L2-normalise for exact cosine scoring."""
    vectors = np.asarray(list(model.embed(texts, batch_size=batch_size)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def blockwise_min_ranks(vectors: np.ndarray, top_k: int, block: int) -> dict[int, int]:
    """Best bidirectional rank per unordered pair, self-matches excluded.

    Scores one fixed query block at a time instead of allocating the full
    concept-by-concept matrix.  Concepts arrive sorted by member IRI, so index
    order is member order and a stable secondary sort on index reproduces the
    canonical tie-break used by the deterministic arms.
    """
    count = vectors.shape[0]
    best: dict[int, int] = {}
    depth = min(top_k, count - 1)
    for start in range(0, count, block):
        stop = min(start + block, count)
        scores = vectors[start:stop] @ vectors.T
        for offset in range(stop - start):
            row_index = start + offset
            row = scores[offset]
            row[row_index] = -np.inf  # never retrieve the concept itself
            candidates = np.argpartition(-row, kth=depth - 1)[:depth]
            order = np.lexsort((candidates, -row[candidates]))
            for rank, neighbour in enumerate(candidates[order], start=1):
                low, high = (row_index, int(neighbour)) if row_index < neighbour else (int(neighbour), row_index)
                code = low * count + high
                if rank < best.get(code, top_k + 1):
                    best[code] = rank
    return best


def run_model(
    spec: dict[str, Any],
    corpus: dict[str, Any],
    output: Path,
    *,
    top_k: int,
    block: int,
    batch_size: int,
) -> None:
    """Encode and rank every view of every source for one model family."""
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=spec["name"])
    for entry in corpus["sources"]:
        source = entry["source"]
        target = output / f"{spec['key']}.{source}.npz"
        if target.exists():
            print(f"  skip {spec['key']} {source} (already present)")
            continue
        concepts = entry["concepts"]
        payload: dict[str, np.ndarray] = {}
        meta: dict[str, Any] = {}
        for view in VIEWS:
            started = time.perf_counter()
            texts = [spec["prefix"] + view_text(concept, view) for concept in concepts]
            distinct = len(set(texts))
            vectors = embed(model, texts, batch_size)
            encoded = time.perf_counter()
            ranks = blockwise_min_ranks(vectors, top_k, block)
            codes = np.fromiter(ranks.keys(), dtype=np.uint32, count=len(ranks))
            values = np.fromiter(ranks.values(), dtype=np.uint8, count=len(ranks))
            order = np.argsort(codes, kind="stable")
            payload[f"{view}.codes"] = codes[order]
            payload[f"{view}.ranks"] = values[order]
            meta[view] = {
                "distinctTexts": distinct,
                "conceptCount": len(concepts),
                "retainedPairs": len(ranks),
                "vectorDigest": _digest(vectors.tobytes()),
                "encodeSeconds": round(encoded - started, 3),
                "rankSeconds": round(time.perf_counter() - encoded, 3),
            }
            print(
                f"  {spec['key']:<10} {source:<34} {view:<15} "
                f"distinct={distinct:<5} pairs={len(ranks):<8} "
                f"{meta[view]['encodeSeconds']:>7.1f}s enc {meta[view]['rankSeconds']:>6.1f}s rank"
            )
        payload["conceptCount"] = np.asarray([len(concepts)], dtype=np.uint32)
        np.savez_compressed(target, **payload)
        (output / f"{spec['key']}.{source}.meta.json").write_text(
            json.dumps(
                {
                    "model": spec["name"],
                    "modelKey": spec["key"],
                    "convention": spec["convention"],
                    "prefix": spec["prefix"],
                    "source": source,
                    "topK": top_k,
                    "queryBlockSize": block,
                    "views": meta,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    del model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", action="append", choices=[spec["key"] for spec in MODELS])
    parser.add_argument("--top-k", type=int, default=max(DEFAULT_DEPTHS))
    parser.add_argument("--query-block-size", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    if args.query_block_size <= 0:
        parser.error("--query-block-size must be positive")

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    selected = [spec for spec in MODELS if not args.model or spec["key"] in args.model]

    for spec in selected:
        print(f"\n=== {spec['name']}  ({spec['convention']})")
        started = time.perf_counter()
        run_model(
            spec,
            corpus,
            args.output,
            top_k=args.top_k,
            block=args.query_block_size,
            batch_size=args.batch_size,
        )
        print(f"  done in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
