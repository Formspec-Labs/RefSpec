"""Measure the exact Atlas lexical, sparse-graph, and local-BGE frontier.

This experimental tool reruns the sealed English lexical and sparse arms, then
reruns the already-measured five-view local BGE arm. It keeps dense ranks in
compact matrices, writes a deterministic rank receipt, and emits a small,
label-rich review sample. It never calls a hosted model provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from refspec.atlas.candidate_retrieval import AtlasConcept, AtlasConceptContext
from refspec.atlas.parquet_artifact import file_sha256 as _sha256
from refspec.storage import canonical_json

try:
    from tools import benchmark_atlas_candidate_retrieval as shared_benchmark
    from tools import benchmark_atlas_sparse_lexical_frontier as two_family
    from tools import benchmark_lexical_candidate_controls as lexical_benchmark
except ImportError:  # Direct execution places tools/ on sys.path.
    import benchmark_atlas_candidate_retrieval as shared_benchmark
    import benchmark_atlas_sparse_lexical_frontier as two_family
    import benchmark_lexical_candidate_controls as lexical_benchmark


LEXICAL_SPARSE_DEPTHS = (1, 2, 3, 5, 10)
BGE_DEPTHS = (1, 2, 3, 5, 10, 20)
RECEIPT_DEPTHS = (1, 2, 3, 5, 10, 20, 50)
BGE_RETAIN_MAXIMUM = 50
BGE_MODEL = "BAAI/bge-small-en-v1.5"
BGE_PREFIX_MODE = "symmetric"
BGE_VIEWS = shared_benchmark.VIEWS
LEAN_LEXICAL_K = 3
LEAN_SPARSE_K = 1
RELATION_TYPES = two_family.RELATION_TYPES
SELECTED_ARM_NAMES = two_family.SELECTED_ARM_NAMES
CASE_SHIFT = two_family.CASE_SHIFT
RANK_BANDS = (
    ("rank-1", 1, 1, "highest-priority BGE row"),
    ("ranks-2-3", 2, 3, "high-priority BGE rows"),
    ("ranks-4-5", 4, 5, "BGE rows through K=5"),
    ("ranks-6-10", 6, 10, "BGE rows through K=10"),
    ("ranks-11-15", 11, 15, "middle of the K=20 addition"),
    ("ranks-16-20", 16, 20, "near the inside of the K=20 cutoff"),
    ("ranks-21-25", 21, 25, "immediately outside the K=20 cutoff"),
    ("ranks-26-50", 26, 50, "farther outside the K=20 cutoff"),
)
INSIDE_REVIEW_BANDS = RANK_BANDS[:6]
JUST_OUTSIDE_REVIEW_BAND = RANK_BANDS[6]
REVIEW_CATEGORIES = ("bge-only", "three-family-overlap", "just-outside-bge20")


def _sets_from_compact(
    compact: Any,
    codec: lexical_benchmark.PairCodec,
    depths: Sequence[int],
) -> dict[int, frozenset[int]]:
    """Decode compact rank matrices into exact integer pair sets."""

    import numpy as np

    if tuple(layout.name for layout in compact.layouts) != codec.case_names:
        raise ValueError("compact ranks and pair codec use different cases")
    result: dict[int, frozenset[int]] = {}
    for depth in depths:
        if depth > compact.maximum:
            raise ValueError("requested depth exceeds retained compact ranks")
        selected: set[int] = set()
        for case_index, (layout, ranks) in enumerate(zip(compact.layouts, compact.ranks, strict=True)):
            if layout.sources != codec.sources[case_index] or layout.targets != codec.targets[case_index]:
                raise ValueError(f"compact rank layout differs for {layout.name}")
            source_indexes, target_indexes = np.nonzero(ranks <= depth)
            selected.update(
                codec.code(case_index, int(source_index), int(target_index))
                for source_index, target_index in zip(source_indexes, target_indexes, strict=True)
            )
        result[depth] = frozenset(selected)
    return result


def _rank_matrix_digest(layout: Any, ranks: Any) -> str:
    import numpy as np

    digest = hashlib.sha256()
    digest.update(f"{layout.name}\n".encode())
    digest.update("\n".join(layout.sources).encode())
    digest.update(b"\n--targets--\n")
    digest.update("\n".join(layout.targets).encode())
    digest.update(b"\n--ranks--\n")
    digest.update(np.asarray(ranks).astype(ranks.dtype.newbyteorder("<"), copy=False).tobytes(order="C"))
    return "sha256:" + digest.hexdigest()


def write_compact_rank_artifact(compact: Any, output: Path) -> dict[str, Any]:
    """Write canonical raw rank matrices and return their compact manifest."""

    import numpy as np

    chunks: list[bytes] = []
    layouts = []
    offset = 0
    for layout, ranks in zip(compact.layouts, compact.ranks, strict=True):
        canonical = np.asarray(ranks).astype(ranks.dtype.newbyteorder("<"), copy=False)
        chunk = canonical.tobytes(order="C")
        chunks.append(chunk)
        layouts.append(
            {
                "case": layout.name,
                "sourceCount": len(layout.sources),
                "targetCount": len(layout.targets),
                "offsetBytes": offset,
                "lengthBytes": len(chunk),
                "sourceMembersDigest": "sha256:"
                + hashlib.sha256(("\n".join(layout.sources) + "\n").encode()).hexdigest(),
                "targetMembersDigest": "sha256:"
                + hashlib.sha256(("\n".join(layout.targets) + "\n").encode()).hexdigest(),
                "matrixDigest": _rank_matrix_digest(layout, canonical),
            }
        )
        offset += len(chunk)
    payload = b"".join(chunks)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    if output.read_bytes() != payload:
        raise RuntimeError("compact BGE rank artifact did not reopen byte-for-byte")
    return {
        "type": "AtlasCompactBgePairRanks",
        "schemaVersion": "1.0",
        "format": "concatenated canonical C-order rank matrices",
        "dtype": str(compact.ranks[0].dtype),
        "maximumRetainedRank": compact.maximum,
        "sentinel": compact.sentinel,
        "rankMeaning": "minimum exact bidirectional rank across the declared BGE views",
        "tieBreak": "canonical member IRI",
        "path": str(output),
        "bytes": len(payload),
        "sha256": _sha256(output),
        "layouts": layouts,
    }


def _family_summary(
    pairs: frozenset[int],
    *,
    gold: frozenset[int],
    codec: lexical_benchmark.PairCodec,
) -> dict[str, Any]:
    return two_family._family_summary(pairs, gold=gold, codec=codec)


def _typed_counts(
    pairs: frozenset[int],
    *,
    gold_by_relation: Mapping[str, frozenset[int]],
) -> dict[str, dict[str, int]]:
    return {
        relation: {"gold": len(gold_by_relation[relation]), "found": len(pairs & gold_by_relation[relation])}
        for relation in RELATION_TYPES
    }


def summarize_combination(
    *,
    lexical_depth: int,
    sparse_depth: int,
    bge_depth: int,
    lexical_pairs: frozenset[int],
    sparse_pairs: frozenset[int],
    bge_pairs: frozenset[int],
    gold: frozenset[int],
    gold_by_relation: Mapping[str, frozenset[int]],
    codec: lexical_benchmark.PairCodec,
) -> dict[str, Any]:
    """Summarize one exact three-family union."""

    union = lexical_pairs | sparse_pairs | bge_pairs
    found = union & gold
    return {
        "lexicalK": lexical_depth,
        "sparseGraphK": sparse_depth,
        "bgeK": bge_depth,
        "candidates": len(union),
        "found": len(found),
        "recall": round(len(found) / len(gold), 8),
        "batchesOf25": math.ceil(len(union) / 25),
        "pairSetDigest": two_family._pair_digest(union, codec),
        "typedRelations": _typed_counts(frozenset(union), gold_by_relation=gold_by_relation),
    }


def summarize_bge_marginal(
    *,
    bge_depth: int,
    lean_pairs: frozenset[int],
    bge_pairs: frozenset[int],
    gold: frozenset[int],
    gold_by_relation: Mapping[str, frozenset[int]],
    codec: lexical_benchmark.PairCodec,
) -> dict[str, Any]:
    """Measure exact BGE additions over the 210,197-row lean floor."""

    bge_only = bge_pairs - lean_pairs
    overlap = bge_pairs & lean_pairs
    union = lean_pairs | bge_pairs
    cases = []
    for case_index, case in enumerate(codec.case_names):
        case_only = frozenset(code for code in bge_only if code >> CASE_SHIFT == case_index)
        case_gold = frozenset(code for code in gold if code >> CASE_SHIFT == case_index)
        cases.append(
            {
                "case": case,
                "bgeOnlyCandidates": len(case_only),
                "bgeOnlyGold": len(case_only & case_gold),
            }
        )
    return {
        "bgeK": bge_depth,
        "leanFloorCandidates": len(lean_pairs),
        "bgeCandidates": len(bge_pairs),
        "bgeFound": len(bge_pairs & gold),
        "overlapCandidates": len(overlap),
        "overlapGold": len(overlap & gold),
        "bgeOnlyCandidates": len(bge_only),
        "bgeOnlyGold": len(bge_only & gold),
        "bgeOnlyBatchesOf25": math.ceil(len(bge_only) / 25),
        "bgeOnlyPairSetDigest": two_family._pair_digest(bge_only, codec),
        "unionCandidates": len(union),
        "unionFound": len(union & gold),
        "unionPairSetDigest": two_family._pair_digest(union, codec),
        "typedBgeOnlyGold": {relation: len(bge_only & gold_by_relation[relation]) for relation in RELATION_TYPES},
        "cases": cases,
    }


def _context_payload(context: AtlasConceptContext) -> dict[str, Any]:
    return {
        "member": context.member,
        "prefLabel": context.pref_label,
        "altLabels": list(context.alt_labels),
        "definition": context.definition,
        "scopeNote": context.scope_note,
    }


def _concept_payload(concept: AtlasConcept) -> dict[str, Any]:
    return {
        "member": concept.member,
        "vocabulary": concept.vocabulary,
        "prefLabel": concept.pref_label,
        "altLabels": list(concept.alt_labels),
        "definition": concept.definition,
        "scopeNote": concept.scope_note,
        "parents": [_context_payload(value) for value in concept.parents],
        "children": [_context_payload(value) for value in concept.children],
        "bgeViewTexts": {view: shared_benchmark._embedding_text(concept, view) for view in BGE_VIEWS},
    }


def _band_for_rank(rank: int) -> tuple[str, int, int, str]:
    for band in RANK_BANDS:
        if band[1] <= rank <= band[2]:
            return band
    raise ValueError(f"rank {rank} is outside the retained review bands")


def build_review_sample(
    *,
    cases: Sequence[Any],
    codec: lexical_benchmark.PairCodec,
    bge_compact: Any,
    lexical_pairs: frozenset[int],
    sparse_pairs: frozenset[int],
) -> dict[str, Any]:
    """Select a balanced, deterministic, relation-blind 120-row review set."""

    import numpy as np

    case_lookup = {case.name: case for case in cases}
    strata: list[tuple[str, str, tuple[str, int, int, str], int]] = []
    for case in codec.case_names:
        for band in INSIDE_REVIEW_BANDS:
            strata.append((case, "bge-only", band, 2))
            strata.append((case, "three-family-overlap", band, 1))
        strata.append((case, "just-outside-bge20", JUST_OUTSIDE_REVIEW_BAND, 2))
    quotas = {(case, category, band[0]): quota for case, category, band, quota in strata}
    counts = {key: 0 for key in quotas}
    selected: dict[tuple[str, str, str], list[tuple[str, int, int]]] = {key: [] for key in quotas}
    for case_index, (layout, ranks) in enumerate(zip(bge_compact.layouts, bge_compact.ranks, strict=True)):
        source_indexes, target_indexes = np.nonzero(ranks <= JUST_OUTSIDE_REVIEW_BAND[2])
        for source_index, target_index in zip(source_indexes.tolist(), target_indexes.tolist(), strict=True):
            code = codec.code(case_index, source_index, target_index)
            rank = int(ranks[source_index, target_index])
            band = _band_for_rank(rank)
            lexical_member = code in lexical_pairs
            sparse_member = code in sparse_pairs
            if rank <= 20 and not lexical_member and not sparse_member:
                category = "bge-only"
            elif rank <= 20 and lexical_member and sparse_member:
                category = "three-family-overlap"
            elif JUST_OUTSIDE_REVIEW_BAND[1] <= rank <= JUST_OUTSIDE_REVIEW_BAND[2]:
                category = "just-outside-bge20"
            else:
                continue
            key = (layout.name, category, band[0])
            counts[key] += 1
            selection_digest = hashlib.sha256(lexical_benchmark._pair_line(codec, code)).hexdigest()
            candidate = (selection_digest, code, rank)
            selected[key].append(candidate)
            selected[key].sort()
            del selected[key][quotas[key] :]

    rows = []
    for case_name in codec.case_names:
        case = case_lookup[case_name]
        sources = {concept.member: concept for concept in case.sources}
        targets = {concept.member: concept for concept in case.targets}
        for category in REVIEW_CATEGORIES:
            bands = INSIDE_REVIEW_BANDS if category != "just-outside-bge20" else (JUST_OUTSIDE_REVIEW_BAND,)
            for band in bands:
                for selection_digest, code, rank in selected[(case_name, category, band[0])]:
                    _case, source, target = codec.decode(code)
                    lexical_member = code in lexical_pairs
                    sparse_member = code in sparse_pairs
                    bge_member = rank <= 20
                    rows.append(
                        {
                            "case": case_name,
                            "sampleCategory": category,
                            "rankBand": band[0],
                            "rankBandMeaning": band[3],
                            "bgeRank": rank,
                            "selectionDigest": "sha256:" + selection_digest,
                            "membershipAtReviewDepths": {
                                "lexicalK3": lexical_member,
                                "sparseGraphK1": sparse_member,
                                "bgeK20": bge_member,
                                "bgeRetainedK50": True,
                                "leanTwoFamilyFloor": lexical_member or sparse_member,
                                "allThree": lexical_member and sparse_member and bge_member,
                            },
                            "source": _concept_payload(sources[source]),
                            "target": _concept_payload(targets[target]),
                        }
                    )
    stratum_rows = [
        {
            "case": case,
            "sampleCategory": category,
            "rankBand": band[0],
            "minimumRank": band[1],
            "maximumRank": band[2],
            "meaning": band[3],
            "eligiblePopulation": counts[(case, category, band[0])],
            "requestedRows": quota,
            "sampledRows": len(selected[(case, category, band[0])]),
        }
        for case, category, band, quota in strata
    ]
    payload: dict[str, Any] = {
        "type": "AtlasBlindCandidateReviewSample",
        "schemaVersion": "1.0",
        "productionLanguageScope": "English",
        "model": BGE_MODEL,
        "prefixMode": BGE_PREFIX_MODE,
        "views": list(BGE_VIEWS),
        "leanFloor": {"lexicalK": LEAN_LEXICAL_K, "sparseGraphK": LEAN_SPARSE_K},
        "reviewCutoff": 20,
        "retainedMaximumRank": BGE_RETAIN_MAXIMUM,
        "targetRows": 120,
        "blindReview": "expert gold membership and mapping-relation labels were neither used for selection nor emitted",
        "selection": (
            "lowest canonical pair SHA-256 per case, sample category, and rank band; "
            "two BGE-only rows and one three-family-overlap row per inside band, plus two rows just outside K=20"
        ),
        "strata": stratum_rows,
        "rows": rows,
    }
    payload["sampleDigest"] = "sha256:" + hashlib.sha256(canonical_json(rows).encode()).hexdigest()
    return payload


def _depth_pareto_complete(rows: Sequence[Mapping[str, Any]], gold_count: int) -> list[dict[str, Any]]:
    complete = [row for row in rows if row["found"] == gold_count]
    result = []
    for row in complete:
        dominated = any(
            other is not row
            and other["lexicalK"] <= row["lexicalK"]
            and other["sparseGraphK"] <= row["sparseGraphK"]
            and other["bgeK"] <= row["bgeK"]
            and (
                other["lexicalK"] < row["lexicalK"]
                or other["sparseGraphK"] < row["sparseGraphK"]
                or other["bgeK"] < row["bgeK"]
            )
            for other in complete
        )
        if not dominated:
            result.append(
                {
                    "lexicalK": row["lexicalK"],
                    "sparseGraphK": row["sparseGraphK"],
                    "bgeK": row["bgeK"],
                    "candidates": row["candidates"],
                }
            )
    return sorted(result, key=lambda row: (row["candidates"], row["lexicalK"], row["sparseGraphK"], row["bgeK"]))


def _recall_cost_pareto(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        dominated = any(
            other is not row
            and other["candidates"] <= row["candidates"]
            and other["found"] >= row["found"]
            and (other["candidates"] < row["candidates"] or other["found"] > row["found"])
            for other in rows
        )
        if not dominated:
            result.append(
                {
                    "lexicalK": row["lexicalK"],
                    "sparseGraphK": row["sparseGraphK"],
                    "bgeK": row["bgeK"],
                    "candidates": row["candidates"],
                    "found": row["found"],
                }
            )
    return sorted(result, key=lambda row: (row["candidates"], -row["found"]))


def _assert_receipts(
    *,
    lexical_receipt: Mapping[str, Any],
    sparse_receipt: Mapping[str, Any],
    bge_receipt: Mapping[str, Any],
    lexical_sets: Mapping[int, frozenset[int]],
    sparse_compact: Any,
    bge_compact: Any,
    dense_report: Mapping[str, Any],
    gold: frozenset[int],
    codec: lexical_benchmark.PairCodec,
) -> None:
    lexical_rows = {
        row["topK"]: row
        for union in lexical_receipt["unions"]
        if union["name"] == "lexical-control-union"
        for row in union["results"]
    }
    for depth in LEXICAL_SPARSE_DEPTHS:
        reconstructed = _family_summary(lexical_sets[depth], gold=gold, codec=codec)
        for key in ("candidates", "found", "pairSetDigest"):
            if reconstructed[key] != lexical_rows[depth][key]:
                raise ValueError(f"lexical source receipt mismatch at K={depth}: {key}")

    sparse_rows = {row["topK"]: row for row in sparse_receipt["combinedUnion"]}
    bge_combined_rows = {row["topK"]: row for row in bge_receipt["combinedUnion"]}
    for depth in RECEIPT_DEPTHS:
        sparse_summary = shared_benchmark._compact_pair_summary([sparse_compact], top_k=depth)
        combined_summary = shared_benchmark._compact_pair_summary([sparse_compact, bge_compact], top_k=depth)
        for name, reconstructed, expected in (
            ("sparseGraph", sparse_summary, sparse_rows[depth]),
            ("sparseGraphBge", combined_summary, bge_combined_rows[depth]),
        ):
            for key in ("candidates", "found", "pairSetDigest"):
                if reconstructed[key] != expected[key]:
                    raise ValueError(f"{name} source receipt mismatch at K={depth}: {key}")

    prior_dense = bge_receipt["dense"][0]
    for key in ("model", "prefixMode", "views", "vectorDigest", "results"):
        if dense_report[key] != prior_dense[key]:
            raise ValueError(f"BGE source receipt mismatch: {key}")


def _deterministic_digest(report: Mapping[str, Any]) -> str:
    stable = json.loads(canonical_json(report))
    stable.pop("elapsedSeconds", None)
    stable.get("denseRun", {}).pop("elapsedSeconds", None)
    stable.get("sparseGraphRun", {}).pop("elapsedSeconds", None)
    for arm in stable.get("lexicalArms", ()):
        arm.pop("elapsedSeconds", None)
    return "sha256:" + hashlib.sha256(canonical_json(stable).encode()).hexdigest()


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    adapter_path = Path(shared_benchmark.__file__).resolve()
    adapter_digest_before = _sha256(adapter_path)
    cases = shared_benchmark.atlas_cases(args.root)
    codec = lexical_benchmark.PairCodec.from_cases(cases)
    gold = lexical_benchmark._gold_codes(cases, codec)
    digests = shared_benchmark._case_digest(cases)
    mapping_relations = lexical_benchmark._mapping_relations(args.root, cases, "atlas")
    relation_by_code = {code: mapping_relations[codec.decode(code)] for code in gold}
    gold_by_relation = {
        relation: frozenset(code for code, value in relation_by_code.items() if value == relation)
        for relation in RELATION_TYPES
    }

    sparse_report, sparse_string_ranks = shared_benchmark.sparse_benchmark(cases, RECEIPT_DEPTHS)
    sparse_compact = shared_benchmark._compact_ranks_from_pairs(cases, sparse_string_ranks, BGE_RETAIN_MAXIMUM)
    del sparse_string_ranks
    sparse_sets = _sets_from_compact(sparse_compact, codec, LEXICAL_SPARSE_DEPTHS)

    selected_specs = tuple(lexical_benchmark.SCORER_BY_NAME[name] for name in SELECTED_ARM_NAMES)
    lexical_ranks: dict[int, int] = {}
    lexical_arms = []
    distinct_rank_receipts: dict[str, str] = {}
    duplicate_arms: list[dict[str, str]] = []
    for spec in selected_specs:
        arm_report, arm_ranks, _coverage = lexical_benchmark.run_arm(
            cases,
            spec=spec,
            top_ks=LEXICAL_SPARSE_DEPTHS,
            codec=codec,
            gold=gold,
            workers=args.workers,
            block_size=args.score_block_rows,
        )
        rank_digest = two_family._rank_digest(arm_ranks)
        if rank_digest in distinct_rank_receipts:
            duplicate_arms.append({"arm": spec.name, "duplicates": distinct_rank_receipts[rank_digest]})
        else:
            distinct_rank_receipts[rank_digest] = spec.name
            lexical_benchmark._update_union(lexical_ranks, arm_ranks)
            lexical_arms.append({**arm_report, "pairRankDigest": rank_digest})
        del arm_ranks
    lexical_sets = two_family._sets_by_depth(lexical_ranks, LEXICAL_SPARSE_DEPTHS)

    dense_report, bge_compact = shared_benchmark.dense_benchmark(
        cases,
        model_name=BGE_MODEL,
        views=BGE_VIEWS,
        prefix_mode=BGE_PREFIX_MODE,
        top_ks=RECEIPT_DEPTHS,
        query_block_size=args.query_block_rows,
    )
    bge_sets = _sets_from_compact(bge_compact, codec, BGE_DEPTHS)

    lexical_receipt = json.loads(args.lexical_receipt.read_text())
    sparse_receipt = json.loads(args.sparse_receipt.read_text())
    bge_receipt = json.loads(args.bge_receipt.read_text())
    _assert_receipts(
        lexical_receipt=lexical_receipt,
        sparse_receipt=sparse_receipt,
        bge_receipt=bge_receipt,
        lexical_sets=lexical_sets,
        sparse_compact=sparse_compact,
        bge_compact=bge_compact,
        dense_report=dense_report,
        gold=gold,
        codec=codec,
    )

    rank_manifest = write_compact_rank_artifact(bge_compact, args.bge_rank_output)
    rank_manifest["model"] = BGE_MODEL
    rank_manifest["prefixMode"] = BGE_PREFIX_MODE
    rank_manifest["views"] = list(BGE_VIEWS)
    args.bge_rank_manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.bge_rank_manifest_output.write_text(canonical_json(rank_manifest) + "\n", encoding="utf-8")

    lean_pairs = lexical_sets[LEAN_LEXICAL_K] | sparse_sets[LEAN_SPARSE_K]
    lean_summary = _family_summary(frozenset(lean_pairs), gold=gold, codec=codec)
    if lean_summary != {
        "candidates": 210197,
        "found": 582,
        "recall": 1.0,
        "pairSetDigest": "sha256:24fc3c81f443596181b9bd0e9d2b663992052c19f383ffd2cd222e60d565ede9",
    }:
        raise ValueError("lean Atlas floor no longer matches its sealed exact receipt")

    combinations = [
        summarize_combination(
            lexical_depth=lexical_depth,
            sparse_depth=sparse_depth,
            bge_depth=bge_depth,
            lexical_pairs=lexical_sets[lexical_depth],
            sparse_pairs=sparse_sets[sparse_depth],
            bge_pairs=bge_sets[bge_depth],
            gold=gold,
            gold_by_relation=gold_by_relation,
            codec=codec,
        )
        for lexical_depth in LEXICAL_SPARSE_DEPTHS
        for sparse_depth in LEXICAL_SPARSE_DEPTHS
        for bge_depth in BGE_DEPTHS
    ]
    complete = [row for row in combinations if row["found"] == len(gold)]
    minimum_candidates = min(row["candidates"] for row in complete)
    minimum_complete = [
        {
            "lexicalK": row["lexicalK"],
            "sparseGraphK": row["sparseGraphK"],
            "bgeK": row["bgeK"],
            "candidates": row["candidates"],
            "batchesOf25": row["batchesOf25"],
            "pairSetDigest": row["pairSetDigest"],
            "typedRelations": row["typedRelations"],
        }
        for row in complete
        if row["candidates"] == minimum_candidates
    ]
    bge_marginal = [
        summarize_bge_marginal(
            bge_depth=depth,
            lean_pairs=frozenset(lean_pairs),
            bge_pairs=bge_sets[depth],
            gold=gold,
            gold_by_relation=gold_by_relation,
            codec=codec,
        )
        for depth in BGE_DEPTHS
    ]

    sample = build_review_sample(
        cases=cases,
        codec=codec,
        bge_compact=bge_compact,
        lexical_pairs=lexical_sets[LEAN_LEXICAL_K],
        sparse_pairs=sparse_sets[LEAN_SPARSE_K],
    )
    args.review_sample_output.parent.mkdir(parents=True, exist_ok=True)
    args.review_sample_output.write_text(canonical_json(sample) + "\n", encoding="utf-8")

    adapter_digest_after = _sha256(adapter_path)
    if adapter_digest_after != adapter_digest_before:
        raise RuntimeError("shared input adapter changed during the frontier run")
    report: dict[str, Any] = {
        "type": "AtlasThreeFamilyCandidateCostFrontier",
        "schemaVersion": "1.0",
        "productionLanguageScope": "English",
        "lexicalSparseDepths": list(LEXICAL_SPARSE_DEPTHS),
        "bgeDepths": list(BGE_DEPTHS),
        "bgeRetainedMaximumRank": BGE_RETAIN_MAXIMUM,
        "selectedLexicalArms": [arm["name"] for arm in lexical_arms],
        "duplicateLexicalArmsRemoved": duplicate_arms,
        "bgeArm": {"model": BGE_MODEL, "prefixMode": BGE_PREFIX_MODE, "views": list(BGE_VIEWS)},
        "execution": "exact lexical and dense blocks plus deterministic sparse and mutual-anchor graph ranks",
        "providerCalls": 0,
        "scoreBlockRows": args.score_block_rows,
        "queryBlockRows": args.query_block_rows,
        "workers": args.workers,
        "caseCount": len(cases),
        "sourceConcepts": sum(len(case.sources) for case in cases),
        "targetConcepts": sum(len(case.targets) for case in cases),
        "goldRelations": len(gold),
        "typedGoldCounts": {relation: len(gold_by_relation[relation]) for relation in RELATION_TYPES},
        "corpusDigest": digests["corpus"],
        "goldDigest": digests["gold"],
        "sharedAdapterDigest": adapter_digest_after,
        "toolDigest": _sha256(Path(__file__).resolve()),
        "lexicalToolDigest": _sha256(Path(lexical_benchmark.__file__).resolve()),
        "twoFamilyToolDigest": _sha256(Path(two_family.__file__).resolve()),
        "sourceReceipts": {
            "lexical": {"path": str(args.lexical_receipt), "sha256": _sha256(args.lexical_receipt)},
            "sparseGraph": {"path": str(args.sparse_receipt), "sha256": _sha256(args.sparse_receipt)},
            "bge": {"path": str(args.bge_receipt), "sha256": _sha256(args.bge_receipt)},
        },
        "sourceReceiptVerification": "all source counts and digests reproduced; sparse-plus-BGE pair sets reproduced through K=50",
        "compactBgeRanks": {
            **rank_manifest,
            "manifestPath": str(args.bge_rank_manifest_output),
            "manifestSha256": _sha256(args.bge_rank_manifest_output),
        },
        "reviewSample": {
            "path": str(args.review_sample_output),
            "sha256": _sha256(args.review_sample_output),
            "rows": len(sample["rows"]),
            "sampleDigest": sample["sampleDigest"],
        },
        "lexicalArms": lexical_arms,
        "sparseGraphRun": sparse_report,
        "denseRun": dense_report,
        "familyRankDigests": {
            "lexical": two_family._rank_digest(lexical_ranks),
            "sparseGraph": sparse_rows_digest(sparse_compact),
            "bge": sparse_rows_digest(bge_compact),
        },
        "leanTwoFamilyFloor": {
            "lexicalK": LEAN_LEXICAL_K,
            "sparseGraphK": LEAN_SPARSE_K,
            **lean_summary,
            "batchesOf25": math.ceil(lean_summary["candidates"] / 25),
            "typedRelations": _typed_counts(frozenset(lean_pairs), gold_by_relation=gold_by_relation),
        },
        "bgeMarginalOverLeanFloor": bge_marginal,
        "combinations": combinations,
        "completeCombinationCount": len(complete),
        "depthParetoComplete": _depth_pareto_complete(combinations, len(gold)),
        "recallCostPareto": _recall_cost_pareto(combinations),
        "minimumCandidateComplete": minimum_complete,
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    report["deterministicResultDigest"] = _deterministic_digest(report)
    return report


def sparse_rows_digest(compact: Any) -> str:
    """Digest compact layouts and rank bytes without expanding pair strings."""

    digest = hashlib.sha256()
    for layout, ranks in zip(compact.layouts, compact.ranks, strict=True):
        digest.update((_rank_matrix_digest(layout, ranks) + "\n").encode())
    return "sha256:" + digest.hexdigest()


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--lexical-receipt", type=Path, required=True)
    parser.add_argument("--sparse-receipt", type=Path, required=True)
    parser.add_argument("--bge-receipt", type=Path, required=True)
    parser.add_argument("--score-block-rows", type=int, default=128)
    parser.add_argument("--query-block-rows", type=int, default=128)
    parser.add_argument("--workers", type=int, default=-1)
    parser.add_argument("--bge-rank-output", type=Path, required=True)
    parser.add_argument("--bge-rank-manifest-output", type=Path, required=True)
    parser.add_argument("--review-sample-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.score_block_rows <= 0 or args.query_block_rows <= 0:
        parser.error("block row counts must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    print(
        canonical_json(
            {
                "completeCombinations": report["completeCombinationCount"],
                "deterministicResultDigest": report["deterministicResultDigest"],
                "elapsedSeconds": report["elapsedSeconds"],
                "minimumCandidateComplete": report["minimumCandidateComplete"],
                "output": str(args.output),
                "outputDigest": _sha256(args.output),
                "reviewSample": report["reviewSample"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
