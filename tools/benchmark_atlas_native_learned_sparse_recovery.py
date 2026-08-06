"""E3 learned-sparse half: SPLADE++ and MiniCOIL over the ablated Atlas corpus.

The candidate-retrieval ledger ran three learned-sparse families and found them
genuinely complementary: MiniCOIL ``structured`` at K20 sits on both Conference
Pareto minimums, and SPLADE++ ``label`` supplied the single unique Anatomy
rescue that no dense or deterministic arm found.  Neither had ever been scored
against policy or social-science language, and neither was in the first E3
pass.

Both views the ledger declared are kept: ``label`` (preferred plus alternate
labels) and ``structured`` (field-tagged label, aliases, definition, notes).
The hierarchy fields stay ablated, as everywhere else in E3.

MiniCOIL is asymmetric.  Its query side applies collection-level BM25 inverse
document frequency while its document side does not, so queries are encoded
through ``query_embed`` and documents through ``embed`` rather than reusing one
matrix.  SPLADE++ is symmetric and uses one encoding for both sides.

Scoring is an exact sparse dot product through a CSR matrix rather than a
Python inverted index, then a blockwise dense top-K with the same stable
index tie-break the other E3 arms use.  A pair with no shared expanded term is
absent rather than given an arbitrary zero-score rank.

The ledger's third family, OpenSearch v2-distill, needs SentenceTransformers
``SparseEncoder`` rather than FastEmbed and is not covered here.

Needs FastEmbed and SciPy:
``uv run --no-project --with fastembed --with scipy --with numpy python ...``
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy import sparse

VIEWS = ("label", "structured")

MODELS: tuple[dict[str, Any], ...] = (
    {"name": "prithivida/Splade_PP_en_v1", "key": "splade", "asymmetric": False, "backend": "fastembed"},
    {"name": "Qdrant/minicoil-v1", "key": "minicoil", "asymmetric": True, "backend": "fastembed"},
    {
        "name": "opensearch-project/opensearch-neural-sparse-encoding-v2-distill",
        "key": "opensearch",
        "asymmetric": False,
        "backend": "sentence-transformers",
    },
)


def view_text(concept: dict[str, Any], view: str) -> str:
    label = str(concept.get("label") or "")
    aliases = [str(value) for value in concept.get("altLabels") or ()]
    if view == "label":
        return " ".join([label, *aliases])
    parts = [f"label: {label}"]
    if aliases:
        parts.append(f"aliases: {'; '.join(aliases)}")
    if concept.get("definition"):
        parts.append(f"definition: {concept['definition']}")
    if concept.get("notes"):
        parts.append(f"notes: {concept['notes']}")
    return " | ".join(parts)


def to_csr(embeddings: list[Any], width: int) -> sparse.csr_matrix:
    """Pack FastEmbed sparse embeddings into one CSR matrix."""
    indptr = [0]
    indices: list[int] = []
    values: list[float] = []
    for item in embeddings:
        indices.extend(int(value) for value in item.indices)
        values.extend(float(value) for value in item.values)
        indptr.append(len(indices))
    return sparse.csr_matrix(
        (np.asarray(values, dtype=np.float32), np.asarray(indices, dtype=np.int32), np.asarray(indptr, dtype=np.int64)),
        shape=(len(embeddings), width),
    )


def blockwise_min_ranks(
    queries: sparse.csr_matrix, documents: sparse.csr_matrix, top_k: int, block: int
) -> dict[int, int]:
    """Best bidirectional rank per unordered pair from exact sparse dot products."""
    count = queries.shape[0]
    depth = min(top_k, count - 1)
    best: dict[int, int] = {}
    transposed = documents.T.tocsc()
    for start in range(0, count, block):
        stop = min(start + block, count)
        scores = np.asarray((queries[start:stop] @ transposed).todense(), dtype=np.float32)
        for offset in range(stop - start):
            row_index = start + offset
            row = scores[offset]
            row[row_index] = -np.inf
            # A pair with no shared expanded term scores zero and must stay
            # absent rather than occupy a rank.
            positive = int((row > 0).sum())
            if positive == 0:
                continue
            take = min(depth, positive)
            candidates = np.argpartition(-row, kth=take - 1)[:take] if take < row.size else np.arange(row.size)
            order = np.lexsort((candidates, -row[candidates]))
            for rank, neighbour in enumerate(candidates[order], start=1):
                if row[neighbour] <= 0:
                    break
                low, high = (row_index, int(neighbour)) if row_index < neighbour else (int(neighbour), row_index)
                code = low * count + high
                if rank < best.get(code, top_k + 1):
                    best[code] = rank
    return best


def load_model(spec: dict[str, Any]) -> Any:
    """Load one learned-sparse encoder through its declared backend."""
    if spec["backend"] == "sentence-transformers":
        from sentence_transformers import SparseEncoder

        return SparseEncoder(spec["name"])
    from fastembed import SparseTextEmbedding

    return SparseTextEmbedding(model_name=spec["name"])


def encode_sentence_transformers(model: Any, texts: list[str], batch_size: int) -> sparse.csr_matrix:
    """Encode with SentenceTransformers and return one CSR matrix.

    ``SparseEncoder`` yields a torch sparse tensor rather than FastEmbed's
    index/value pairs, so it is converted rather than passed through ``to_csr``.
    """
    tensor = model.encode(texts, batch_size=batch_size, convert_to_sparse_tensor=True).coalesce()
    indices = tensor.indices().cpu().numpy()
    values = tensor.values().cpu().numpy().astype(np.float32)
    return sparse.csr_matrix((values, (indices[0], indices[1])), shape=tuple(tensor.shape))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", action="append", choices=[spec["key"] for spec in MODELS])
    parser.add_argument("--source", action="append")
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--query-block-size", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    specs = [spec for spec in MODELS if not args.model or spec["key"] in args.model]

    for spec in specs:
        print(f"\n=== {spec['name']}  asymmetric={spec['asymmetric']}  backend={spec['backend']}")
        model = load_model(spec)
        for entry in corpus["sources"]:
            source = entry["source"]
            if args.source and source not in args.source:
                continue
            target = args.output / f"{spec['key']}.{source}.npz"
            if target.exists():
                print(f"  skip {spec['key']} {source} (already present)")
                continue
            concepts = entry["concepts"]
            payload: dict[str, np.ndarray] = {"conceptCount": np.asarray([len(concepts)], dtype=np.uint32)}
            meta: dict[str, Any] = {}
            for view in VIEWS:
                started = time.perf_counter()
                texts = [view_text(concept, view) for concept in concepts]
                if spec["backend"] == "sentence-transformers":
                    doc_matrix = encode_sentence_transformers(model, texts, args.batch_size)
                    query_matrix = doc_matrix
                    width = doc_matrix.shape[1]
                else:
                    documents = list(model.embed(texts, batch_size=args.batch_size))
                    queries = (
                        list(model.query_embed(texts, batch_size=args.batch_size)) if spec["asymmetric"] else documents
                    )
                    width = 1 + max(
                        int(max(item.indices)) if len(item.indices) else 0 for item in (*documents, *queries)
                    )
                    doc_matrix = to_csr(documents, width)
                    query_matrix = to_csr(queries, width) if spec["asymmetric"] else doc_matrix
                encoded = time.perf_counter()
                ranks = blockwise_min_ranks(query_matrix, doc_matrix, args.top_k, args.query_block_size)
                codes = np.fromiter(ranks.keys(), dtype=np.uint32, count=len(ranks))
                values = np.fromiter(ranks.values(), dtype=np.uint8, count=len(ranks))
                order = np.argsort(codes, kind="stable")
                payload[f"{view}.codes"] = codes[order]
                payload[f"{view}.ranks"] = values[order]
                meta[view] = {
                    "vocabularyWidth": width,
                    "nonZeroPerConcept": round(doc_matrix.nnz / doc_matrix.shape[0], 2),
                    "retainedPairs": len(ranks),
                    "encodeSeconds": round(encoded - started, 2),
                    "rankSeconds": round(time.perf_counter() - encoded, 2),
                }
                print(
                    f"  {spec['key']:<10} {source:<34} {view:<12} width={width:<7} "
                    f"nnz/concept={meta[view]['nonZeroPerConcept']:<7} pairs={len(ranks):<8} "
                    f"{meta[view]['encodeSeconds']:>7.1f}s enc {meta[view]['rankSeconds']:>6.1f}s rank"
                )
            np.savez_compressed(target, **payload)
            (args.output / f"{spec['key']}.{source}.meta.json").write_text(
                json.dumps({"model": spec["name"], "source": source, "views": meta}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        del model
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
