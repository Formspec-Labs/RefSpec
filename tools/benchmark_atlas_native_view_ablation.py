"""E-T1..E-T4: text and prompt-structure ablation over the ablated Atlas corpus.

Text rendering is the cheapest lever available and the least examined.  Every
dense arm so far used one of four renderings, all of which concatenate a
concept's alternate labels into a single string.  Four variants test whether
that is the right default.

``V1 labelOnly``       the preferred label alone.
``V3 maxOverLabels``   every label embedded separately; a pair scores as the
                       maximum similarity over all label-pair combinations.
                       This is the dense analogue of the exact shared-alias
                       anchor.  The lexical run lost ``Family planning``/
                       ``BIRTH CONTROL`` at K100 because bagging aliases into
                       one string dilutes an exact shared alias, and every
                       dense arm here bags them the same way.
``V4 lowercased``      the preferred label, casefolded.  ELSST publishes
                       uppercase, ICPSR lowercase, Federal Register sentence
                       case.  If encoders are casing-sensitive at all, then
                       cross-vocabulary matching carries a systematic penalty
                       unrelated to meaning -- a live confound in the
                       production task that no experiment has isolated.
``V5 schemeQualified`` the label prefixed with its vocabulary's name.  Expected
                       to trade a little recall for precision against polysemy
                       of the ``U.S. Government Manual``/``MANUAL WORKERS``
                       kind.  For a graph that is traversed rather than merely
                       ranked, that trade is usually worth taking.

Scoring matches every other E3 arm exactly: exact similarity, self-pairs
excluded, bidirectional minimum rank, stable tie-break on concept index.
``maxOverLabels`` reduces a label-by-label matrix to concepts with a two-stage
segment maximum, so its ranks remain comparable with the single-vector arms.

Needs FastEmbed:
``uv run --no-project --with fastembed --with numpy python ...``
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

SCHEME_NAMES = {
    "federal-register-thesaurus-2025": "Federal Register regulatory thesaurus",
    "elsst-r6": "ELSST social science thesaurus",
    "icpsr-subject-thesaurus": "ICPSR social science subject thesaurus",
}

VARIANTS = ("labelOnly", "maxOverLabels", "lowercased", "schemeQualified")

DEFAULT_MODELS = ("BAAI/bge-small-en-v1.5", "sentence-transformers/all-MiniLM-L6-v2")


def concept_texts(concept: dict[str, Any], variant: str, scheme: str) -> list[str]:
    """Render one concept as one or more strings, depending on the variant."""
    label = str(concept.get("label") or "")
    aliases = [str(value) for value in concept.get("altLabels") or ()]
    if variant == "labelOnly":
        return [label]
    if variant == "lowercased":
        return [label.casefold()]
    if variant == "schemeQualified":
        return [f"{scheme} — {label}"]
    if variant == "maxOverLabels":
        return [label, *aliases]
    raise ValueError(f"unsupported variant: {variant!r}")


def encode(model: Any, texts: list[str], batch_size: int) -> np.ndarray:
    vectors = np.asarray(list(model.embed(texts, batch_size=batch_size)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def _ranks_from_scores(scores: np.ndarray, row_index: int, top_k: int, count: int, best: dict[int, int]) -> None:
    scores[row_index] = -np.inf
    depth = min(top_k, count - 1)
    candidates = np.argpartition(-scores, kth=depth - 1)[:depth]
    order = np.lexsort((candidates, -scores[candidates]))
    for rank, neighbour in enumerate(candidates[order], start=1):
        low, high = (row_index, int(neighbour)) if row_index < neighbour else (int(neighbour), row_index)
        code = low * count + high
        if rank < best.get(code, top_k + 1):
            best[code] = rank


def single_vector_ranks(vectors: np.ndarray, top_k: int, block: int) -> dict[int, int]:
    count = vectors.shape[0]
    best: dict[int, int] = {}
    for start in range(0, count, block):
        stop = min(start + block, count)
        scores = vectors[start:stop] @ vectors.T
        for offset in range(stop - start):
            _ranks_from_scores(scores[offset], start + offset, top_k, count, best)
    return best


def max_over_labels_ranks(
    vectors: np.ndarray, boundaries: np.ndarray, count: int, top_k: int, block: int
) -> dict[int, int]:
    """Concept similarity is the maximum over every label pair.

    ``boundaries`` marks where each concept's labels begin in ``vectors``, so a
    label-by-label score block reduces to concepts with one segment maximum on
    the document axis and a second on the query axis.
    """
    best: dict[int, int] = {}
    for concept in range(0, count, block):
        stop = min(concept + block, count)
        lo, hi = int(boundaries[concept]), int(boundaries[stop])
        label_scores = vectors[lo:hi] @ vectors.T
        # Document axis: labels -> concepts.
        by_concept = np.maximum.reduceat(label_scores, boundaries[:count], axis=1)
        # Query axis: this block's labels -> its concepts.
        block_bounds = boundaries[concept:stop] - lo
        reduced = np.maximum.reduceat(by_concept, block_bounds, axis=0)
        for offset in range(stop - concept):
            _ranks_from_scores(reduced[offset], concept + offset, top_k, count, best)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", action="append", default=None)
    parser.add_argument("--variant", action="append", choices=list(VARIANTS))
    parser.add_argument("--source", action="append")
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--query-block-size", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    from fastembed import TextEmbedding

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    models = args.model or list(DEFAULT_MODELS)
    variants = args.variant or list(VARIANTS)

    for name in models:
        key = name.split("/")[-1].replace("-en-v1.5", "").replace("all-", "")
        print(f"\n=== {name}")
        model = TextEmbedding(model_name=name)
        for entry in corpus["sources"]:
            source = entry["source"]
            if args.source and source not in args.source:
                continue
            concepts = entry["concepts"]
            count = len(concepts)
            scheme = SCHEME_NAMES.get(source, source)
            target = args.output / f"view-{key}.{source}.npz"
            if target.exists():
                print(f"  skip {key} {source} (already present)")
                continue
            payload: dict[str, np.ndarray] = {"conceptCount": np.asarray([count], dtype=np.uint32)}
            meta: dict[str, Any] = {}
            for variant in variants:
                started = time.perf_counter()
                rendered = [concept_texts(concept, variant, scheme) for concept in concepts]
                flat = [text for group in rendered for text in group]
                boundaries = np.zeros(count + 1, dtype=np.int64)
                for position, group in enumerate(rendered):
                    boundaries[position + 1] = boundaries[position] + len(group)
                vectors = encode(model, flat, args.batch_size)
                encoded = time.perf_counter()
                if variant == "maxOverLabels":
                    ranks = max_over_labels_ranks(vectors, boundaries, count, args.top_k, args.query_block_size)
                else:
                    ranks = single_vector_ranks(vectors, args.top_k, args.query_block_size)
                codes = np.fromiter(ranks.keys(), dtype=np.uint32, count=len(ranks))
                values = np.fromiter(ranks.values(), dtype=np.uint8, count=len(ranks))
                order = np.argsort(codes, kind="stable")
                payload[f"{variant}.codes"] = codes[order]
                payload[f"{variant}.ranks"] = values[order]
                meta[variant] = {
                    "renderedStrings": len(flat),
                    "conceptCount": count,
                    "retainedPairs": len(ranks),
                    "encodeSeconds": round(encoded - started, 2),
                    "rankSeconds": round(time.perf_counter() - encoded, 2),
                }
                print(
                    f"  {key:<12} {source:<34} {variant:<16} strings={len(flat):<6} "
                    f"pairs={len(ranks):<8} {meta[variant]['encodeSeconds']:>6.1f}s enc "
                    f"{meta[variant]['rankSeconds']:>6.1f}s rank"
                )
            np.savez_compressed(target, **payload)
            (args.output / f"view-{key}.{source}.meta.json").write_text(
                json.dumps({"model": name, "source": source, "variants": meta}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        del model
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
