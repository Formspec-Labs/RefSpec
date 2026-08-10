"""Measure bounded Open English WordNet discovery on the six Atlas pairs.

The experiment rebuilds the selected English lexical-K3 plus sparse-graph-K1
floor and verifies its exact 210,197-pair receipt before measuring WordNet.
WordNet sees labels and alternate labels only.  The 582 admitted relation types
are joined after retrieval for evaluation and never influence candidate finding.

Run with pinned local inputs and RapidFuzz::

    uv run --with 'rapidfuzz==3.14.3' \
      tools/benchmark_atlas_wordnet_candidate_retrieval.py \
      --root /tmp/refspec-candidate-benchmark.ANhNrc \
      --wordnet /tmp/refspec-candidate-benchmark.ANhNrc/english-wordnet-2025.xml.gz \
      --floor-receipt \
        /tmp/refspec-candidate-benchmark.ANhNrc/atlas-sparse-lexical-exact-frontier-english.json \
      --maximum-depth 4 \
      --output /tmp/atlas-wordnet-depth0-4.json

No provider API or hosted inference service is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from refspec.atlas.parquet_artifact import file_sha256 as _sha256
from refspec.storage import canonical_json

try:
    from tools import benchmark_atlas_candidate_retrieval as shared_benchmark
    from tools import benchmark_atlas_sparse_lexical_frontier as floor_benchmark
    from tools import benchmark_beyond_equivalence_candidate_retrieval as wordnet_benchmark
    from tools import benchmark_lexical_candidate_controls as lexical_benchmark
except ImportError:  # Direct execution places tools/ on sys.path.
    import benchmark_atlas_candidate_retrieval as shared_benchmark
    import benchmark_atlas_sparse_lexical_frontier as floor_benchmark
    import benchmark_beyond_equivalence_candidate_retrieval as wordnet_benchmark
    import benchmark_lexical_candidate_controls as lexical_benchmark


EXPECTED_FLOOR_COUNT = 210_197
EXPECTED_FLOOR_DIGEST = "sha256:24fc3c81f443596181b9bd0e9d2b663992052c19f383ffd2cd222e60d565ede9"
EXPECTED_GOLD_COUNT = 582
RELATION_TYPES = ("exact", "close", "broad", "narrow", "related")
PRODUCTION_LANGUAGE_SCOPE = "English"


def _without_runtime(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _without_runtime(item) for key, item in value.items() if key != "elapsedSeconds"}
    if isinstance(value, list):
        return [_without_runtime(item) for item in value]
    return value


def _deterministic_digest(report: Mapping[str, Any]) -> str:
    stable = canonical_json(_without_runtime(report)).encode()
    return "sha256:" + hashlib.sha256(stable).hexdigest()


def _pair_digest(pairs: frozenset[int] | set[int], codec: lexical_benchmark.PairCodec) -> str:
    return floor_benchmark._pair_digest(pairs, codec)


def _typed_counts(
    pairs: frozenset[int] | set[int],
    *,
    gold_by_relation: Mapping[str, frozenset[int]],
) -> dict[str, dict[str, int | float | None]]:
    result: dict[str, dict[str, int | float | None]] = {}
    for relation in RELATION_TYPES:
        gold = gold_by_relation[relation]
        found = len(pairs & gold)
        result[relation] = {
            "gold": len(gold),
            "found": found,
            "recall": round(found / len(gold), 9) if gold else None,
        }
    return result


def _gold_rows(
    codes: frozenset[int] | set[int],
    *,
    codec: lexical_benchmark.PairCodec,
    relation_by_code: Mapping[int, str],
    label_by_member: Mapping[tuple[str, str], str],
) -> list[dict[str, str]]:
    rows = []
    for code in sorted(codes):
        case, source, target = codec.decode(code)
        rows.append(
            {
                "case": case,
                "source": source,
                "sourceLabel": label_by_member[(case, source)],
                "target": target,
                "targetLabel": label_by_member[(case, target)],
                "relation": relation_by_code[code],
            }
        )
    return rows


def _encode_sparse_ranks(
    ranks: Mapping[tuple[str, str, str], int],
    codec: lexical_benchmark.PairCodec,
) -> dict[int, int]:
    return floor_benchmark._encode_sparse_ranks(ranks, codec)


def rebuild_production_floor(
    cases: Sequence[Any],
    *,
    codec: lexical_benchmark.PairCodec,
    gold: frozenset[int],
    workers: int,
    block_size: int,
) -> tuple[frozenset[int], dict[str, Any]]:
    """Rebuild and verify the selected lexical-K3 plus sparse-graph-K1 set."""

    started = time.monotonic()
    sparse_report, sparse_string_ranks = shared_benchmark.sparse_benchmark(cases, (1,))
    sparse_ranks = _encode_sparse_ranks(sparse_string_ranks, codec)
    sparse_pairs = frozenset(code for code, rank in sparse_ranks.items() if rank <= 1)
    del sparse_string_ranks, sparse_ranks

    lexical_ranks: dict[int, int] = {}
    arm_reports = []
    distinct_rank_receipts: dict[str, str] = {}
    duplicate_arms = []
    for name in floor_benchmark.SELECTED_ARM_NAMES:
        spec = lexical_benchmark.SCORER_BY_NAME[name]
        arm_report, arm_ranks, _coverage = lexical_benchmark.run_arm(
            cases,
            spec=spec,
            top_ks=(3,),
            codec=codec,
            gold=gold,
            workers=workers,
            block_size=block_size,
        )
        rank_digest = floor_benchmark._rank_digest(arm_ranks)
        if rank_digest in distinct_rank_receipts:
            duplicate_arms.append({"arm": name, "duplicates": distinct_rank_receipts[rank_digest]})
        else:
            distinct_rank_receipts[rank_digest] = name
            lexical_benchmark._update_union(lexical_ranks, arm_ranks)
            arm_reports.append({**arm_report, "pairRankDigest": rank_digest})
        del arm_ranks
    lexical_pairs = frozenset(code for code, rank in lexical_ranks.items() if rank <= 3)
    del lexical_ranks

    floor = lexical_pairs | sparse_pairs
    digest = _pair_digest(floor, codec)
    if len(floor) != EXPECTED_FLOOR_COUNT or digest != EXPECTED_FLOOR_DIGEST:
        raise ValueError(
            f"rebuilt production floor does not match its sealed receipt: got {len(floor)} pairs and {digest}"
        )
    return floor, {
        "policy": "selected nonduplicate lexical controls at bidirectional K=3 plus sparse and mutual graph K=1",
        "candidates": len(floor),
        "found": len(floor & gold),
        "pairSetDigest": digest,
        "lexicalCandidates": len(lexical_pairs),
        "sparseGraphCandidates": len(sparse_pairs),
        "overlapCandidates": len(lexical_pairs & sparse_pairs),
        "lexicalPairSetDigest": _pair_digest(lexical_pairs, codec),
        "sparseGraphPairSetDigest": _pair_digest(sparse_pairs, codec),
        "selectedLexicalArms": [row["name"] for row in arm_reports],
        "duplicateLexicalArmsRemoved": duplicate_arms,
        "lexicalArms": arm_reports,
        "sparseGraphRun": sparse_report,
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }


def wordnet_minimum_distances(
    cases: Sequence[Any],
    *,
    codec: lexical_benchmark.PairCodec,
    index: wordnet_benchmark.WordNetIndex,
    maximum_depth: int,
) -> tuple[dict[int, int], dict[str, Any]]:
    """Find every pair whose noun senses are within the bounded taxonomy depth.

    The graph is undirected, so a source-side breadth-first search is sufficient
    to find both broader and narrower candidates.  Every OEWN noun sense stays
    active; the later semantic judge decides whether a candidate relation holds.
    """

    if maximum_depth < 0:
        raise ValueError("WordNet taxonomy depth cannot be negative")
    started = time.monotonic()
    pair_distances: dict[int, int] = {}
    feature_hasher = hashlib.sha256()
    source_with_synsets = 0
    target_with_synsets = 0
    source_sense_assignments = 0
    target_sense_assignments = 0

    for case_index, case in enumerate(sorted(cases, key=lambda item: item.name)):
        source_by_member = {concept.member: concept for concept in case.sources}
        target_by_member = {concept.member: concept for concept in case.targets}
        sources = tuple(source_by_member[member] for member in codec.sources[case_index])
        targets = tuple(target_by_member[member] for member in codec.targets[case_index])

        target_indexes_by_synset: dict[str, list[int]] = defaultdict(list)
        for target_index, concept in enumerate(targets):
            forms, synsets = wordnet_benchmark._concept_wordnet_synsets(concept, index)
            feature_hasher.update(
                f"{case.name}\ttarget\t{concept.member}\t{'|'.join(forms)}\t{'|'.join(sorted(synsets))}\n".encode()
            )
            if synsets:
                target_with_synsets += 1
                target_sense_assignments += len(synsets)
            for synset in sorted(synsets):
                target_indexes_by_synset[synset].append(target_index)

        for source_index, concept in enumerate(sources):
            forms, roots = wordnet_benchmark._concept_wordnet_synsets(concept, index)
            feature_hasher.update(
                f"{case.name}\tsource\t{concept.member}\t{'|'.join(forms)}\t{'|'.join(sorted(roots))}\n".encode()
            )
            if not roots:
                continue
            source_with_synsets += 1
            source_sense_assignments += len(roots)
            visited = set(roots)
            frontier = set(roots)
            for distance in range(maximum_depth + 1):
                for synset in sorted(frontier):
                    for target_index in target_indexes_by_synset.get(synset, ()):
                        code = codec.code(case_index, source_index, target_index)
                        previous = pair_distances.get(code)
                        if previous is None or distance < previous:
                            pair_distances[code] = distance
                if distance == maximum_depth:
                    break
                following = {
                    neighbor
                    for synset in frontier
                    for neighbor in index.adjacency.get(synset, ())
                    if neighbor not in visited
                }
                visited.update(following)
                frontier = following
                if not frontier:
                    break

    evidence_hasher = hashlib.sha256()
    for code, distance in sorted(pair_distances.items()):
        case, source, target = codec.decode(code)
        evidence_hasher.update(f"{case}\t{source}\t{target}\t{distance}\n".encode())
    return pair_distances, {
        "resource": "Open English WordNet",
        "version": wordnet_benchmark.OEWN_VERSION,
        "releaseTag": wordnet_benchmark.OEWN_RELEASE_TAG,
        "releaseCommit": wordnet_benchmark.OEWN_RELEASE_COMMIT,
        "releaseUrl": wordnet_benchmark.OEWN_RELEASE_URL,
        "license": "Princeton WordNet License for underlying data; CC-BY-4.0 for OEWN additions",
        "licenseUrl": wordnet_benchmark.OEWN_LICENSE_URL,
        "assetUrl": wordnet_benchmark.OEWN_ASSET_URL,
        "maximumTaxonomyDepth": maximum_depth,
        "method": (
            "all noun senses for normalized preferred and alternate labels plus suffix heads; "
            "shared synset or undirected hypernym/hyponym distance"
        ),
        "sourceConceptsWithNounSynsets": source_with_synsets,
        "targetConceptsWithNounSynsets": target_with_synsets,
        "sourceNounSenseAssignments": source_sense_assignments,
        "targetNounSenseAssignments": target_sense_assignments,
        "wordNetStats": dict(index.stats),
        "featureDigest": "sha256:" + feature_hasher.hexdigest(),
        "evidenceDigest": "sha256:" + evidence_hasher.hexdigest(),
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }


def _case_breakdown(
    pairs: frozenset[int],
    *,
    gold: frozenset[int],
    codec: lexical_benchmark.PairCodec,
) -> list[dict[str, int | float | str]]:
    shift = lexical_benchmark.PAIR_SOURCE_BITS * 2
    result = []
    for case_index, name in enumerate(codec.case_names):
        case_pairs = frozenset(code for code in pairs if code >> shift == case_index)
        case_gold = frozenset(code for code in gold if code >> shift == case_index)
        found = len(case_pairs & case_gold)
        result.append(
            {
                "case": name,
                "candidates": len(case_pairs),
                "gold": len(case_gold),
                "found": found,
                "recall": round(found / len(case_gold), 9) if case_gold else 0.0,
            }
        )
    return result


def summarize_depths(
    pair_distances: Mapping[int, int],
    *,
    maximum_depth: int,
    floor: frozenset[int],
    gold: frozenset[int],
    gold_by_relation: Mapping[str, frozenset[int]],
    relation_by_code: Mapping[int, str],
    label_by_member: Mapping[tuple[str, str], str],
    codec: lexical_benchmark.PairCodec,
) -> list[dict[str, Any]]:
    """Report cumulative and exact-distance WordNet effects at every depth."""

    result = []
    previous = frozenset()
    previous_union = floor
    for depth in range(maximum_depth + 1):
        pairs = frozenset(code for code, distance in pair_distances.items() if distance <= depth)
        exact = frozenset(code for code, distance in pair_distances.items() if distance == depth)
        incremental = pairs - previous
        union = floor | pairs
        unique_over_floor = pairs - floor
        incremental_union = union - previous_union
        found = pairs & gold
        new_gold = incremental & gold
        misses = gold - found
        result.append(
            {
                "depth": depth,
                "class": "sharedSynset" if depth == 0 else f"taxonomyDistanceAtMost{depth}",
                "candidates": len(pairs),
                "found": len(found),
                "recall": round(len(found) / len(gold), 9),
                "pairSetDigest": _pair_digest(pairs, codec),
                "typedRecall": _typed_counts(pairs, gold_by_relation=gold_by_relation),
                "caseBreakdown": _case_breakdown(pairs, gold=gold, codec=codec),
                "exactDistanceCandidates": len(exact),
                "exactDistancePairSetDigest": _pair_digest(exact, codec),
                "incrementalCandidatesSincePriorDepth": len(incremental),
                "incrementalGoldSincePriorDepth": len(new_gold),
                "incrementalGoldRelations": _gold_rows(
                    new_gold,
                    codec=codec,
                    relation_by_code=relation_by_code,
                    label_by_member=label_by_member,
                ),
                "missedGold": _gold_rows(
                    misses,
                    codec=codec,
                    relation_by_code=relation_by_code,
                    label_by_member=label_by_member,
                ),
                "unionWithProductionFloor": {
                    "candidates": len(union),
                    "found": len(union & gold),
                    "recall": round(len(union & gold) / len(gold), 9),
                    "pairSetDigest": _pair_digest(union, codec),
                    "overlapCandidates": len(pairs & floor),
                    "uniqueWordNetCandidates": len(unique_over_floor),
                    "uniqueWordNetGold": len(unique_over_floor & gold),
                    "incrementalCandidatesSincePriorDepth": len(incremental_union),
                    "typedRecall": _typed_counts(union, gold_by_relation=gold_by_relation),
                },
            }
        )
        previous = pairs
        previous_union = union
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    adapter_path = Path(shared_benchmark.__file__).resolve()
    adapter_digest_before = _sha256(adapter_path)
    cases = shared_benchmark.atlas_cases(args.root)
    codec = lexical_benchmark.PairCodec.from_cases(cases)
    gold = lexical_benchmark._gold_codes(cases, codec)
    if len(gold) != EXPECTED_GOLD_COUNT:
        raise ValueError(f"expected {EXPECTED_GOLD_COUNT} Atlas gold relations, found {len(gold)}")
    mapping_relations = lexical_benchmark._mapping_relations(args.root, cases, "atlas")
    relation_by_code = {code: mapping_relations[codec.decode(code)] for code in gold}
    gold_by_relation = {
        relation: frozenset(code for code, value in relation_by_code.items() if value == relation)
        for relation in RELATION_TYPES
    }
    label_by_member = {
        (case.name, concept.member): concept.pref_label for case in cases for concept in (*case.sources, *case.targets)
    }

    floor_receipt = json.loads(args.floor_receipt.read_text())
    expected_rows = floor_receipt.get("minimumCandidateComplete", ())
    if not any(
        row.get("lexicalK") == 3
        and row.get("sparseGraphK") == 1
        and row.get("candidates") == EXPECTED_FLOOR_COUNT
        and row.get("pairSetDigest") == EXPECTED_FLOOR_DIGEST
        for row in expected_rows
    ):
        raise ValueError("floor receipt does not contain the sealed lexical-K3 plus sparse-graph-K1 point")
    floor, floor_metadata = rebuild_production_floor(
        cases,
        codec=codec,
        gold=gold,
        workers=args.workers,
        block_size=args.block_size,
    )

    wordnet_digest = _sha256(args.wordnet)
    expected_wordnet = "sha256:" + wordnet_benchmark.OEWN_ARCHIVE_SHA256
    if not args.allow_unpinned_wordnet and wordnet_digest != expected_wordnet:
        raise ValueError(
            f"WordNet digest {wordnet_digest} does not match pinned OEWN 2025 {expected_wordnet}; "
            "use --allow-unpinned-wordnet only for an intentional fixture"
        )
    index = wordnet_benchmark.load_wordnet(args.wordnet)
    pair_distances, wordnet_metadata = wordnet_minimum_distances(
        cases,
        codec=codec,
        index=index,
        maximum_depth=args.maximum_depth,
    )
    depths = summarize_depths(
        pair_distances,
        maximum_depth=args.maximum_depth,
        floor=floor,
        gold=gold,
        gold_by_relation=gold_by_relation,
        relation_by_code=relation_by_code,
        label_by_member=label_by_member,
        codec=codec,
    )

    adapter_digest_after = _sha256(adapter_path)
    if adapter_digest_after != adapter_digest_before:
        raise RuntimeError("shared Atlas adapter changed during the WordNet run")
    case_digests = shared_benchmark._case_digest(cases)
    report: dict[str, Any] = {
        "type": "AtlasOpenEnglishWordNetCandidateBenchmark",
        "schemaVersion": "1.0",
        "purpose": "relation-blind candidate discovery before semantic judging",
        "providerCalls": 0,
        "productionLanguageScope": PRODUCTION_LANGUAGE_SCOPE,
        "decisionBoundary": (
            "bounded lexical-knowledge challenger only; no production integration or mapping-semantic decision"
        ),
        "caseCount": len(cases),
        "sourceConcepts": sum(len(case.sources) for case in cases),
        "targetConcepts": sum(len(case.targets) for case in cases),
        "possiblePairs": sum(len(case.sources) * len(case.targets) for case in cases),
        "goldRelations": len(gold),
        "typedGoldCounts": {relation: len(gold_by_relation[relation]) for relation in RELATION_TYPES},
        "corpusDigest": case_digests["corpus"],
        "goldDigest": case_digests["gold"],
        "sharedAdapterDigest": adapter_digest_after,
        "floorReceipt": {"path": str(args.floor_receipt), "sha256": _sha256(args.floor_receipt)},
        "productionFloor": {
            **floor_metadata,
            "typedRecall": _typed_counts(floor, gold_by_relation=gold_by_relation),
        },
        "wordNet": {"assetDigest": wordnet_digest, **wordnet_metadata},
        "depths": depths,
        "toolDigest": _sha256(Path(__file__).resolve()),
        "lexicalToolDigest": _sha256(Path(lexical_benchmark.__file__).resolve()),
        "floorToolDigest": _sha256(Path(floor_benchmark.__file__).resolve()),
        "wordNetToolDigest": _sha256(Path(wordnet_benchmark.__file__).resolve()),
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    report["deterministicResultDigest"] = _deterministic_digest(report)
    return report


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--wordnet", type=Path, required=True)
    parser.add_argument("--floor-receipt", type=Path, required=True)
    parser.add_argument("--maximum-depth", type=int, default=4)
    parser.add_argument("--workers", type=int, default=-1)
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--allow-unpinned-wordnet", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.maximum_depth < 0:
        parser.error("--maximum-depth cannot be negative")
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
                "deterministicResultDigest": report["deterministicResultDigest"],
                "elapsedSeconds": report["elapsedSeconds"],
                "maximumDepth": args.maximum_depth,
                "output": str(args.output),
                "outputDigest": _sha256(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
