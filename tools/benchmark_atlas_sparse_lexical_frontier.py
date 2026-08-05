"""Measure the exact Atlas sparse-plus-lexical candidate cost frontier.

The tool reconstructs compact candidate rank receipts for the existing
sparse-plus-mutual-graph family and the selected nonduplicate lexical family.
It writes only summaries and SHA-256 receipts, never the complete pair list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from refspec.storage import canonical_json

try:
    from tools import benchmark_atlas_candidate_retrieval as shared_benchmark
    from tools import benchmark_lexical_candidate_controls as lexical_benchmark
except ImportError:  # Direct execution places tools/ on sys.path.
    import benchmark_atlas_candidate_retrieval as shared_benchmark
    import benchmark_lexical_candidate_controls as lexical_benchmark


DEPTHS = (1, 2, 3, 5, 10)
SELECTED_ARM_NAMES = (
    "levenshtein-distance",
    "normalized-levenshtein",
    "rapidfuzz-token-set-ratio",
    "rapidfuzz-wratio",
    "compact-jaro-winkler",
    "alias-wratio",
    "identifier-qratio",
)
RELATION_TYPES = ("exact", "close", "broad", "narrow", "related")
CASE_SHIFT = lexical_benchmark.PAIR_SOURCE_BITS * 2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _pair_digest(codes: set[int] | frozenset[int], codec: lexical_benchmark.PairCodec) -> str:
    digest = hashlib.sha256()
    for code in sorted(codes):
        digest.update(lexical_benchmark._pair_line(codec, code))
    return "sha256:" + digest.hexdigest()


def _rank_digest(ranks: Mapping[int, int]) -> str:
    digest = hashlib.sha256()
    for code, rank in sorted(ranks.items()):
        digest.update(f"{code}\t{rank}\n".encode())
    return "sha256:" + digest.hexdigest()


def _code_maps(
    codec: lexical_benchmark.PairCodec,
) -> tuple[dict[str, int], tuple[dict[str, int], ...], tuple[dict[str, int], ...]]:
    return (
        {name: index for index, name in enumerate(codec.case_names)},
        tuple({member: index for index, member in enumerate(values)} for values in codec.sources),
        tuple({member: index for index, member in enumerate(values)} for values in codec.targets),
    )


def _encode_sparse_ranks(
    ranks: Mapping[tuple[str, str, str], int],
    codec: lexical_benchmark.PairCodec,
) -> dict[int, int]:
    case_indexes, source_indexes, target_indexes = _code_maps(codec)
    result: dict[int, int] = {}
    for (case, source, target), rank in ranks.items():
        case_index = case_indexes[case]
        result[codec.code(case_index, source_indexes[case_index][source], target_indexes[case_index][target])] = rank
    return result


def _sets_by_depth(ranks: Mapping[int, int], depths: Sequence[int]) -> dict[int, frozenset[int]]:
    return {depth: frozenset(code for code, rank in ranks.items() if rank <= depth) for depth in depths}


def _family_summary(
    pairs: frozenset[int],
    *,
    gold: frozenset[int],
    codec: lexical_benchmark.PairCodec,
) -> dict[str, Any]:
    found = pairs & gold
    return {
        "candidates": len(pairs),
        "found": len(found),
        "recall": round(len(found) / len(gold), 8),
        "pairSetDigest": _pair_digest(pairs, codec),
    }


def _relation_counts(
    pairs: frozenset[int],
    *,
    gold_by_relation: Mapping[str, frozenset[int]],
) -> dict[str, int]:
    return {relation: len(pairs & gold_by_relation[relation]) for relation in RELATION_TYPES}


def summarize_combination(
    *,
    lexical_depth: int,
    sparse_depth: int,
    lexical_pairs: frozenset[int],
    sparse_pairs: frozenset[int],
    gold: frozenset[int],
    gold_by_case: Sequence[frozenset[int]],
    gold_by_relation: Mapping[str, frozenset[int]],
    codec: lexical_benchmark.PairCodec,
) -> dict[str, Any]:
    """Summarize an exact family union without serializing candidate rows."""

    union = lexical_pairs | sparse_pairs
    overlap = lexical_pairs & sparse_pairs
    lexical_only = lexical_pairs - sparse_pairs
    sparse_only = sparse_pairs - lexical_pairs
    found = union & gold

    cases = []
    for case_index, case_name in enumerate(codec.case_names):
        lexical_case = frozenset(code for code in lexical_pairs if code >> CASE_SHIFT == case_index)
        sparse_case = frozenset(code for code in sparse_pairs if code >> CASE_SHIFT == case_index)
        union_case = lexical_case | sparse_case
        case_gold = gold_by_case[case_index]
        cases.append(
            {
                "case": case_name,
                "gold": len(case_gold),
                "lexicalCandidates": len(lexical_case),
                "lexicalFound": len(lexical_case & case_gold),
                "lexicalOnlyCandidates": len(lexical_case - sparse_case),
                "lexicalOnlyGold": len((lexical_case - sparse_case) & case_gold),
                "overlapCandidates": len(lexical_case & sparse_case),
                "sparseGraphCandidates": len(sparse_case),
                "sparseGraphFound": len(sparse_case & case_gold),
                "sparseGraphOnlyCandidates": len(sparse_case - lexical_case),
                "sparseGraphOnlyGold": len((sparse_case - lexical_case) & case_gold),
                "unionCandidates": len(union_case),
                "unionFound": len(union_case & case_gold),
            }
        )

    typed = {}
    for relation in RELATION_TYPES:
        relation_gold = gold_by_relation[relation]
        typed[relation] = {
            "gold": len(relation_gold),
            "lexicalFound": len(lexical_pairs & relation_gold),
            "lexicalOnlyGold": len(lexical_only & relation_gold),
            "sparseGraphFound": len(sparse_pairs & relation_gold),
            "sparseGraphOnlyGold": len(sparse_only & relation_gold),
            "unionFound": len(union & relation_gold),
        }

    return {
        "lexicalK": lexical_depth,
        "sparseGraphK": sparse_depth,
        "candidates": len(union),
        "found": len(found),
        "recall": round(len(found) / len(gold), 8),
        "pairSetDigest": _pair_digest(union, codec),
        "lexical": _family_summary(lexical_pairs, gold=gold, codec=codec),
        "sparseGraph": _family_summary(sparse_pairs, gold=gold, codec=codec),
        "overlapCandidates": len(overlap),
        "overlapGold": len(overlap & gold),
        "lexicalOnlyCandidates": len(lexical_only),
        "lexicalOnlyGold": len(lexical_only & gold),
        "lexicalOnlyPairSetDigest": _pair_digest(lexical_only, codec),
        "sparseGraphOnlyCandidates": len(sparse_only),
        "sparseGraphOnlyGold": len(sparse_only & gold),
        "sparseGraphOnlyPairSetDigest": _pair_digest(sparse_only, codec),
        "cases": cases,
        "typedRelations": typed,
    }


def _depth_pareto_complete(combinations: Sequence[Mapping[str, Any]], gold_count: int) -> list[dict[str, int]]:
    complete = [row for row in combinations if row["found"] == gold_count]
    result = []
    for row in complete:
        dominated = any(
            other is not row
            and other["lexicalK"] <= row["lexicalK"]
            and other["sparseGraphK"] <= row["sparseGraphK"]
            and (other["lexicalK"] < row["lexicalK"] or other["sparseGraphK"] < row["sparseGraphK"])
            for other in complete
        )
        if not dominated:
            result.append(
                {
                    "lexicalK": row["lexicalK"],
                    "sparseGraphK": row["sparseGraphK"],
                    "candidates": row["candidates"],
                }
            )
    return sorted(result, key=lambda row: (row["candidates"], row["lexicalK"], row["sparseGraphK"]))


def _recall_cost_pareto(combinations: Sequence[Mapping[str, Any]]) -> list[dict[str, int]]:
    result = []
    for row in combinations:
        dominated = any(
            other is not row
            and other["candidates"] <= row["candidates"]
            and other["found"] >= row["found"]
            and (other["candidates"] < row["candidates"] or other["found"] > row["found"])
            for other in combinations
        )
        if not dominated:
            result.append(
                {
                    "lexicalK": row["lexicalK"],
                    "sparseGraphK": row["sparseGraphK"],
                    "candidates": row["candidates"],
                    "found": row["found"],
                }
            )
    return sorted(result, key=lambda row: (row["candidates"], -row["found"]))


def _assert_source_receipts(
    *,
    lexical_receipt: Mapping[str, Any],
    sparse_receipt: Mapping[str, Any],
    lexical_sets: Mapping[int, frozenset[int]],
    sparse_sets: Mapping[int, frozenset[int]],
    gold: frozenset[int],
    codec: lexical_benchmark.PairCodec,
) -> None:
    lexical_rows = {
        row["topK"]: row
        for union in lexical_receipt["unions"]
        if union["name"] == "lexical-control-union"
        for row in union["results"]
    }
    sparse_rows = {row["topK"]: row for row in sparse_receipt["combinedUnion"]}
    for depth in DEPTHS:
        for name, reconstructed, expected in (
            ("lexical", _family_summary(lexical_sets[depth], gold=gold, codec=codec), lexical_rows[depth]),
            ("sparseGraph", _family_summary(sparse_sets[depth], gold=gold, codec=codec), sparse_rows[depth]),
        ):
            for key in ("candidates", "found", "pairSetDigest"):
                if reconstructed[key] != expected[key]:
                    raise ValueError(f"{name} source receipt mismatch at K={depth}: {key}")


def _deterministic_digest(report: Mapping[str, Any]) -> str:
    stable = json.loads(canonical_json(report))
    stable.pop("elapsedSeconds", None)
    for arm in stable.get("lexicalArms", ()):
        arm.pop("elapsedSeconds", None)
    stable.get("sparseGraphRun", {}).pop("elapsedSeconds", None)
    return "sha256:" + hashlib.sha256(canonical_json(stable).encode()).hexdigest()


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    adapter_path = Path(shared_benchmark.__file__).resolve()
    adapter_digest_before = _sha256(adapter_path)
    cases = shared_benchmark.atlas_cases(args.root)
    codec = lexical_benchmark.PairCodec.from_cases(cases)
    gold = lexical_benchmark._gold_codes(cases, codec)
    case_digests = shared_benchmark._case_digest(cases)

    mapping_relations = lexical_benchmark._mapping_relations(args.root, cases, "atlas")
    relation_by_code = {code: mapping_relations[codec.decode(code)] for code in gold}
    gold_by_relation = {
        relation: frozenset(code for code, value in relation_by_code.items() if value == relation)
        for relation in RELATION_TYPES
    }
    gold_by_case = tuple(
        frozenset(code for code in gold if code >> CASE_SHIFT == case_index)
        for case_index in range(len(codec.case_names))
    )

    sparse_report, sparse_string_ranks = shared_benchmark.sparse_benchmark(cases, DEPTHS)
    sparse_ranks = _encode_sparse_ranks(sparse_string_ranks, codec)
    sparse_sets = _sets_by_depth(sparse_ranks, DEPTHS)
    del sparse_string_ranks

    selected_specs = tuple(lexical_benchmark.SCORER_BY_NAME[name] for name in SELECTED_ARM_NAMES)
    lexical_ranks: dict[int, int] = {}
    lexical_arms = []
    distinct_rank_receipts: dict[str, str] = {}
    duplicate_arms: list[dict[str, str]] = []
    for spec in selected_specs:
        arm_report, arm_ranks, _coverage = lexical_benchmark.run_arm(
            cases,
            spec=spec,
            top_ks=DEPTHS,
            codec=codec,
            gold=gold,
            workers=args.workers,
            block_size=args.block_size,
        )
        rank_digest = _rank_digest(arm_ranks)
        if rank_digest in distinct_rank_receipts:
            duplicate_arms.append({"arm": spec.name, "duplicates": distinct_rank_receipts[rank_digest]})
        else:
            distinct_rank_receipts[rank_digest] = spec.name
            lexical_benchmark._update_union(lexical_ranks, arm_ranks)
            lexical_arms.append({**arm_report, "pairRankDigest": rank_digest})
        del arm_ranks
    lexical_sets = _sets_by_depth(lexical_ranks, DEPTHS)

    lexical_receipt = json.loads(args.lexical_receipt.read_text())
    sparse_receipt = json.loads(args.sparse_receipt.read_text())
    _assert_source_receipts(
        lexical_receipt=lexical_receipt,
        sparse_receipt=sparse_receipt,
        lexical_sets=lexical_sets,
        sparse_sets=sparse_sets,
        gold=gold,
        codec=codec,
    )

    combinations = [
        summarize_combination(
            lexical_depth=lexical_depth,
            sparse_depth=sparse_depth,
            lexical_pairs=lexical_sets[lexical_depth],
            sparse_pairs=sparse_sets[sparse_depth],
            gold=gold,
            gold_by_case=gold_by_case,
            gold_by_relation=gold_by_relation,
            codec=codec,
        )
        for lexical_depth in DEPTHS
        for sparse_depth in DEPTHS
    ]
    complete = [row for row in combinations if row["found"] == len(gold)]
    minimum_candidates = min(row["candidates"] for row in complete)
    minimum_complete = [
        {
            "lexicalK": row["lexicalK"],
            "sparseGraphK": row["sparseGraphK"],
            "candidates": row["candidates"],
            "pairSetDigest": row["pairSetDigest"],
        }
        for row in complete
        if row["candidates"] == minimum_candidates
    ]

    assertion_files = sorted(args.root.glob("qualification-baseline/*/relation-assertions-v2/relation-assertions.json"))
    adapter_digest_after = _sha256(adapter_path)
    if adapter_digest_after != adapter_digest_before:
        raise RuntimeError("shared input adapter changed during the frontier run")

    report: dict[str, Any] = {
        "type": "AtlasSparseLexicalCandidateCostFrontier",
        "schemaVersion": "1.0",
        "depths": list(DEPTHS),
        "selectedLexicalArms": [arm["name"] for arm in lexical_arms],
        "duplicateLexicalArmsRemoved": duplicate_arms,
        "execution": "exact bidirectional lexical blocks plus deterministic sparse and mutual-anchor graph ranks",
        "productionLanguageScope": "English",
        "scoreBlockRows": args.block_size,
        "workers": args.workers,
        "caseCount": len(cases),
        "sourceConcepts": sum(len(case.sources) for case in cases),
        "targetConcepts": sum(len(case.targets) for case in cases),
        "goldRelations": len(gold),
        "typedGoldCounts": {relation: len(gold_by_relation[relation]) for relation in RELATION_TYPES},
        "corpusDigest": case_digests["corpus"],
        "goldDigest": case_digests["gold"],
        "sharedAdapterDigest": adapter_digest_after,
        "toolDigest": _sha256(Path(__file__).resolve()),
        "lexicalToolDigest": _sha256(Path(lexical_benchmark.__file__).resolve()),
        "typedAssertionFiles": {str(path.relative_to(args.root)): _sha256(path) for path in assertion_files},
        "sourceReceipts": {
            "lexical": {"path": str(args.lexical_receipt), "sha256": _sha256(args.lexical_receipt)},
            "sparseGraph": {"path": str(args.sparse_receipt), "sha256": _sha256(args.sparse_receipt)},
        },
        "sourceReceiptVerification": "candidate counts, gold counts, and pair-set digests reproduced at every depth",
        "lexicalArms": lexical_arms,
        "sparseGraphRun": sparse_report,
        "familyRankDigests": {
            "lexical": _rank_digest(lexical_ranks),
            "sparseGraph": _rank_digest(sparse_ranks),
        },
        "combinations": combinations,
        "completeCombinationCount": len(complete),
        "depthParetoComplete": _depth_pareto_complete(combinations, len(gold)),
        "recallCostPareto": _recall_cost_pareto(combinations),
        "minimumCandidateComplete": minimum_complete,
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    report["deterministicResultDigest"] = _deterministic_digest(report)
    return report


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--lexical-receipt", type=Path, required=True)
    parser.add_argument("--sparse-receipt", type=Path, required=True)
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--workers", type=int, default=-1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.block_size <= 0:
        parser.error("--block-size must be positive")
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
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
