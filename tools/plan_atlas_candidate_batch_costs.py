"""Build exact read-only grouped Batch cost plans for Atlas candidate options.

The tool reopens the real six English Atlas concept pairs, reconstructs the
verified lexical-K3 plus sparse/graph-K1 floor, and adds candidates from the
retained BGE rank matrix.  It builds the same hierarchy-aware ``CandidateRow``
payloads and grouped requests as the qualification runner, but it never opens
a provider transport or mutates a qualification/release directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from refspec.atlas import qualification as qual
from refspec.atlas import qualification_batch as qbatch
from refspec.atlas import qualification_spend as qspend
from refspec.storage import canonical_json

try:
    from tools import benchmark_atlas_candidate_retrieval as shared_benchmark
    from tools import benchmark_atlas_sparse_lexical_frontier as two_family
    from tools import benchmark_lexical_candidate_controls as lexical_benchmark
except ImportError:  # Direct execution places tools/ on sys.path.
    import benchmark_atlas_candidate_retrieval as shared_benchmark
    import benchmark_atlas_sparse_lexical_frontier as two_family
    import benchmark_lexical_candidate_controls as lexical_benchmark


LEAN_LEXICAL_K = 3
LEAN_SPARSE_K = 1
BGE_DEPTHS = (1, 3, 5, 10, 15, 20, 25, 50)
PAIR_CODE_DTYPE = "<u8"
PROPOSAL_POLICY = "atlas-relation-candidate-proposal-cost-plan-v1"
WorkKind = Literal["validation", "scoring"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _text_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _proposal_candidate_id(case: str, source: str, target: str) -> str:
    basis = canonical_json(
        {
            "case": case,
            "policy": PROPOSAL_POLICY,
            "sourceMember": source,
            "targetMember": target,
        }
    )
    return "urn:ref:atlas-proposal-candidate:" + hashlib.sha256(basis.encode()).hexdigest()


def _pair_set_digest(codes: Iterable[int], codec: lexical_benchmark.PairCodec) -> str:
    return two_family._pair_digest(frozenset(codes), codec)


def _layout_member_digest(values: Sequence[str]) -> str:
    return "sha256:" + hashlib.sha256(("\n".join(values) + "\n").encode()).hexdigest()


def reconstruct_lean_pairs(
    cases: Sequence[Any],
    codec: lexical_benchmark.PairCodec,
    *,
    workers: int,
    block_size: int,
) -> frozenset[int]:
    """Reconstruct the exact verified lexical-K3 plus sparse/graph-K1 floor."""

    _sparse_report, sparse_string_ranks = shared_benchmark.sparse_benchmark(cases, (LEAN_SPARSE_K,))
    sparse_ranks = two_family._encode_sparse_ranks(sparse_string_ranks, codec)
    sparse_pairs = frozenset(code for code, rank in sparse_ranks.items() if rank <= LEAN_SPARSE_K)

    lexical_ranks: dict[int, int] = {}
    for name in two_family.SELECTED_ARM_NAMES:
        _report, arm_ranks, _coverage = lexical_benchmark.run_arm(
            cases,
            spec=lexical_benchmark.SCORER_BY_NAME[name],
            top_ks=(LEAN_LEXICAL_K,),
            codec=codec,
            gold=frozenset(),
            workers=workers,
            block_size=block_size,
        )
        lexical_benchmark._update_union(lexical_ranks, arm_ranks)
    lexical_pairs = frozenset(code for code, rank in lexical_ranks.items() if rank <= LEAN_LEXICAL_K)
    return lexical_pairs | sparse_pairs


def write_pair_codes(codes: frozenset[int], path: Path) -> dict[str, Any]:
    """Write a compact, canonical little-endian receipt for proposal replay."""

    import numpy as np

    values = np.asarray(sorted(codes), dtype=PAIR_CODE_DTYPE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(values.tobytes(order="C"))
    return {
        "path": str(path),
        "format": "sorted little-endian uint64 pair codes",
        "dtype": PAIR_CODE_DTYPE,
        "pairs": len(codes),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def read_pair_codes(path: Path) -> frozenset[int]:
    import numpy as np

    if path.stat().st_size % 8:
        raise ValueError("lean pair-code artifact length is not divisible by eight")
    values = np.fromfile(path, dtype=PAIR_CODE_DTYPE)
    if len(values) and not bool(np.all(values[1:] > values[:-1])):
        raise ValueError("lean pair-code artifact is not strictly sorted")
    return frozenset(int(value) for value in values)


def load_bge_ranks(
    *,
    rank_path: Path,
    manifest: Mapping[str, Any],
    codec: lexical_benchmark.PairCodec,
    maximum: int,
) -> dict[int, int]:
    """Reopen compact ranks and bind every matrix axis to the current cases."""

    import numpy as np

    if manifest.get("sha256") != _sha256(rank_path):
        raise ValueError("BGE rank bytes differ from their manifest")
    if int(manifest.get("maximumRetainedRank", 0)) < maximum:
        raise ValueError("BGE rank artifact does not retain the requested depth")
    if manifest.get("dtype") != "uint8":
        raise ValueError("BGE rank artifact has an unexpected dtype")
    layouts = manifest.get("layouts")
    if not isinstance(layouts, Sequence) or len(layouts) != len(codec.case_names):
        raise ValueError("BGE rank manifest has the wrong case count")

    ranks_by_code: dict[int, int] = {}
    for case_index, raw in enumerate(layouts):
        if not isinstance(raw, Mapping) or raw.get("case") != codec.case_names[case_index]:
            raise ValueError("BGE rank cases differ from the current Atlas cases")
        sources = codec.sources[case_index]
        targets = codec.targets[case_index]
        if raw.get("sourceMembersDigest") != _layout_member_digest(sources) or raw.get(
            "targetMembersDigest"
        ) != _layout_member_digest(targets):
            raise ValueError("BGE rank axes differ from the current Atlas concepts")
        shape = (len(sources), len(targets))
        ranks = np.memmap(
            rank_path,
            dtype=np.uint8,
            mode="r",
            offset=int(raw["offsetBytes"]),
            shape=shape,
            order="C",
        )
        source_indexes, target_indexes = np.nonzero(ranks <= maximum)
        for source_index, target_index in zip(source_indexes.tolist(), target_indexes.tolist(), strict=True):
            code = codec.code(case_index, source_index, target_index)
            ranks_by_code[code] = int(ranks[source_index, target_index])
    return ranks_by_code


@dataclass(frozen=True, slots=True)
class PlannedRows:
    code: int
    bge_rank: int | None
    scoring: qbatch.CandidateRow
    validation: qbatch.CandidateRow


def build_case_rows(
    *,
    case_index: int,
    case: Any,
    codes: Sequence[int],
    lean_pairs: frozenset[int],
    bge_ranks: Mapping[int, int],
    codec: lexical_benchmark.PairCodec,
) -> list[PlannedRows]:
    """Build full production-shaped rows once for a case's widest option."""

    source_by_member = {concept.member: concept for concept in case.sources}
    target_by_member = {concept.member: concept for concept in case.targets}
    result = []
    for code in codes:
        decoded_case, source_member, target_member = codec.decode(code)
        if decoded_case != case.name or code >> two_family.CASE_SHIFT != case_index:
            raise ValueError("pair code resolved to the wrong Atlas case")
        pair = qual.CandidatePair(
            source=source_by_member[source_member],
            target=target_by_member[target_member],
            generation_class="experimentalRelationCandidate",
            evidence={"method": PROPOSAL_POLICY},
            generation_policy=qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
        )
        candidate_id = _proposal_candidate_id(case.name, source_member, target_member)
        validation_payload = qual.model_input_payload(pair)
        scoring_payload = qual.scoring_input_payload(pair)
        result.append(
            PlannedRows(
                code=code,
                bge_rank=bge_ranks.get(code),
                scoring=qbatch.CandidateRow(
                    candidate_id,
                    pair,
                    _text_digest(canonical_json(scoring_payload)),
                ),
                validation=qbatch.CandidateRow(
                    candidate_id,
                    pair,
                    _text_digest(canonical_json(validation_payload)),
                ),
            )
        )
    return result


def _row_order(row: qbatch.CandidateRow, work_kind: WorkKind) -> tuple[str, str]:
    return (
        hashlib.sha256(f"{qbatch.GROUPING_SEED}|{work_kind}|{row.candidate_id}".encode()).hexdigest(),
        row.candidate_id,
    )


def _payload_lengths(rows: Sequence[qbatch.CandidateRow], work_kind: WorkKind) -> dict[str, tuple[int, int]]:
    result = {}
    for row in rows:
        rendered = canonical_json(qbatch._row_payload(row, work_kind))
        result[row.candidate_id] = (len(rendered), len(rendered.encode("utf-8")))
    return result


def deterministic_groups_fast(
    rows: Sequence[qbatch.CandidateRow],
    *,
    work_kind: WorkKind,
    group_size: int = qbatch.DEFAULT_REQUEST_GROUP_SIZE,
    payload_lengths: Mapping[str, tuple[int, int]] | None = None,
) -> tuple[tuple[qbatch.CandidateRow, ...], ...]:
    """Reproduce qbatch packing without reserializing every growing prefix."""

    if not 1 <= group_size <= qbatch.MAX_REQUEST_GROUP_SIZE:
        raise ValueError("group size is outside the qbatch bound")
    ordered = sorted(rows, key=lambda row: _row_order(row, work_kind))
    if group_size == 1:
        return tuple((row,) for row in ordered)
    lengths = dict(payload_lengths or _payload_lengths(ordered, work_kind))
    system = qbatch.grouped_instructions_text(work_kind)
    empty_user = canonical_json(
        {
            "group_id": "x" * len("group-" + "0" * 32),
            "requestProtocol": qbatch.GROUPED_REQUEST_PROTOCOL,
            "rows": [],
        }
    )
    empty_chars = len(empty_user) - 2
    empty_bytes = len(empty_user.encode("utf-8")) - 2
    system_chars = len(system)
    system_bytes = len(system.encode("utf-8"))

    groups: list[tuple[qbatch.CandidateRow, ...]] = []
    active: list[qbatch.CandidateRow] = []
    active_chars = 0
    active_bytes = 0
    for row in ordered:
        row_chars, row_bytes = lengths[row.candidate_id]
        proposed_count = len(active) + 1
        proposed_chars = active_chars + row_chars + (1 if active else 0)
        proposed_bytes = active_bytes + row_bytes + (1 if active else 0)
        user_chars = empty_chars + proposed_chars + 2
        byte_count = system_bytes + empty_bytes + proposed_bytes + 2
        token_count = max(1, system_chars // 4) + max(1, user_chars // 4)
        if active and (
            proposed_count > group_size
            or byte_count > qbatch.GROUP_INPUT_BYTE_LIMIT
            or token_count > qbatch.GROUP_INPUT_TOKEN_LIMIT
        ):
            groups.append(tuple(active))
            active = [row]
            active_chars = row_chars
            active_bytes = row_bytes
        else:
            active.append(row)
            active_chars = proposed_chars
            active_bytes = proposed_bytes
    if active:
        groups.append(tuple(active))
    return tuple(groups)


def streaming_request_plan_summary(
    family: qual.ValidatorFamily,
    model_id: str,
    rows: Sequence[qbatch.CandidateRow],
    *,
    protocol: str,
    work_kind: WorkKind,
    payload_lengths: Mapping[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Summarize exact qbatch requests while retaining only compact counters."""

    groups = deterministic_groups_fast(
        rows,
        work_kind=work_kind,
        payload_lengths=payload_lengths,
    )
    group_sizes: Counter[int] = Counter()
    request_count = 0
    input_file_bytes = 0
    input_tokens = 0
    output_tokens = 0
    job_count = 0
    active_requests = 0
    active_bytes = 0
    active_tokens = 0
    request_hasher = hashlib.sha256()
    file_limit = qbatch.provider_input_file_limit(family)

    for group in groups:
        if len(group) == 1:
            request = qbatch.build_request(
                family,
                model_id,
                group[0],
                protocol=protocol,
                work_kind=work_kind,
            )
        else:
            request = qbatch.build_grouped_request(
                family,
                model_id,
                group,
                protocol=protocol,
                work_kind=work_kind,
            )
        line = (request.line() + "\n").encode("utf-8")
        request_input_tokens = qbatch.estimated_request_input_tokens(request)
        request_output_tokens = int(request.body[family.max_output_tokens_field])
        if len(line) > file_limit or request_input_tokens > qbatch.MAX_PROVIDER_JOB_INPUT_TOKENS:
            raise ValueError("one planned request exceeds a provider-job limit")
        if active_requests and (
            active_requests + 1 > qbatch.MAX_PROVIDER_REQUESTS_PER_JOB
            or active_bytes + len(line) > file_limit
            or active_tokens + request_input_tokens > qbatch.MAX_PROVIDER_JOB_INPUT_TOKENS
        ):
            job_count += 1
            active_requests = 0
            active_bytes = 0
            active_tokens = 0
        active_requests += 1
        active_bytes += len(line)
        active_tokens += request_input_tokens
        group_sizes[len(group)] += 1
        request_count += 1
        input_file_bytes += len(line)
        input_tokens += request_input_tokens
        output_tokens += request_output_tokens
        request_hasher.update(line)
    if active_requests:
        job_count += 1

    projected_cost = qual.SpendTracker(qbatch.batch_family(family)).cost(input_tokens, output_tokens)
    return {
        "candidateCount": len(rows),
        "family": family.name,
        "groupSizeDistribution": {str(size): count for size, count in sorted(group_sizes.items())},
        "inputFileBytes": input_file_bytes,
        "modelId": model_id,
        "projectedInputTokens": input_tokens,
        "projectedOutputTokenAllowance": output_tokens,
        "projectedCostUsd": round(projected_cost, 6),
        "providerJobCount": job_count,
        "providerRequestCount": request_count,
        "requestGroupSizeLimit": qbatch.DEFAULT_REQUEST_GROUP_SIZE,
        "requestLinesDigest": "sha256:" + request_hasher.hexdigest(),
        "workKind": work_kind,
    }


def _job_plans(
    scoring_rows: Sequence[qbatch.CandidateRow],
    validation_rows: Sequence[qbatch.CandidateRow],
) -> list[dict[str, Any]]:
    scoring_lengths = _payload_lengths(scoring_rows, "scoring")
    validation_lengths = _payload_lengths(validation_rows, "validation")
    openai = qual.VALIDATOR_FAMILIES["openai"]
    gemini = qual.VALIDATOR_FAMILIES["gemini"]
    return [
        streaming_request_plan_summary(
            openai,
            qspend.PRODUCTION_MODELS_BY_FAMILY["openai"],
            scoring_rows,
            protocol=qual.SCORING_PROTOCOL,
            work_kind="scoring",
            payload_lengths=scoring_lengths,
        ),
        streaming_request_plan_summary(
            gemini,
            qspend.PRODUCTION_MODELS_BY_FAMILY["gemini"],
            validation_rows,
            protocol=qual.PROTOCOL,
            work_kind="validation",
            payload_lengths=validation_lengths,
        ),
        streaming_request_plan_summary(
            openai,
            qspend.PRODUCTION_MODELS_BY_FAMILY["openai"],
            validation_rows,
            protocol=qual.PROTOCOL,
            work_kind="validation",
            payload_lengths=validation_lengths,
        ),
    ]


def _totals(jobs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "providerJobCount": sum(int(job["providerJobCount"]) for job in jobs),
        "providerRequestCount": sum(int(job["providerRequestCount"]) for job in jobs),
        "projectedInputTokens": sum(int(job["projectedInputTokens"]) for job in jobs),
        "projectedOutputTokenAllowance": sum(int(job["projectedOutputTokenAllowance"]) for job in jobs),
        "projectedCostUsd": round(sum(float(job["projectedCostUsd"]) for job in jobs), 6),
    }


def _option_name(depth: int | None) -> str:
    return "lean-lexical-k3-sparse-graph-k1" if depth is None else f"lean-plus-bge-k{depth}"


def _expected_options(frontier: Mapping[str, Any]) -> dict[int | None, Mapping[str, Any]]:
    rows: dict[int | None, Mapping[str, Any]] = {None: frontier["leanTwoFamilyFloor"]}
    rows.update(
        {int(row["bgeK"]): row for row in frontier["bgeMarginalOverLeanFloor"] if int(row["bgeK"]) in BGE_DEPTHS}
    )
    return rows


def _stable_report_digest(report: Mapping[str, Any]) -> str:
    stable = json.loads(canonical_json(report))
    stable.pop("elapsedSeconds", None)
    stable.pop("toolDigest", None)
    stable.get("inputs", {}).get("leanPairCodes", {}).pop("mode", None)
    return _text_digest(canonical_json(stable))


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    cases = shared_benchmark.atlas_cases(args.root)
    codec = lexical_benchmark.PairCodec.from_cases(cases)
    frontier = json.loads(args.frontier_receipt.read_text())
    rank_manifest = json.loads(args.bge_rank_manifest.read_text())
    selected_bge_depths = tuple(sorted(set(args.bge_depths or BGE_DEPTHS)))
    option_depths: tuple[int | None, ...] = selected_bge_depths if args.bge_depths else (None, *selected_bge_depths)

    if args.lean_pair_codes.is_file():
        lean_pairs = read_pair_codes(args.lean_pair_codes)
        lean_receipt = {
            "mode": "reopened",
            **write_pair_codes(lean_pairs, args.lean_pair_codes),
        }
    else:
        lean_pairs = reconstruct_lean_pairs(
            cases,
            codec,
            workers=args.workers,
            block_size=args.block_size,
        )
        lean_receipt = {
            "mode": "reconstructed",
            **write_pair_codes(lean_pairs, args.lean_pair_codes),
        }
    expected_lean = frontier["leanTwoFamilyFloor"]
    lean_digest = _pair_set_digest(lean_pairs, codec)
    if len(lean_pairs) != int(expected_lean["candidates"]) or lean_digest != expected_lean["pairSetDigest"]:
        raise ValueError("reconstructed lean floor differs from the exact frontier receipt")

    bge_ranks = load_bge_ranks(
        rank_path=args.bge_rank_file,
        manifest=rank_manifest,
        codec=codec,
        maximum=max(selected_bge_depths),
    )
    expected = _expected_options(frontier)
    option_sets = {
        depth: (
            lean_pairs
            if depth is None
            else lean_pairs | frozenset(code for code, rank in bge_ranks.items() if rank <= depth)
        )
        for depth in option_depths
    }
    for depth, pairs in option_sets.items():
        if depth in {15, 25, 50}:
            continue
        row = expected[depth]
        expected_count = int(row["candidates"] if depth is None else row["unionCandidates"])
        expected_digest = row["pairSetDigest"] if depth is None else row["unionPairSetDigest"]
        if len(pairs) != expected_count or _pair_set_digest(pairs, codec) != expected_digest:
            raise ValueError(f"proposal option {depth} differs from the frontier receipt")

    widest_pairs = option_sets[max(selected_bge_depths)]
    case_masks = [
        frozenset(code for code in widest_pairs if code >> two_family.CASE_SHIFT == index)
        for index in range(len(cases))
    ]
    option_rows: dict[int | None, list[dict[str, Any]]] = {depth: [] for depth in option_depths}
    for case_index, case in enumerate(cases):
        widest_codes = sorted(case_masks[case_index])
        planned_rows = build_case_rows(
            case_index=case_index,
            case=case,
            codes=widest_codes,
            lean_pairs=lean_pairs,
            bge_ranks=bge_ranks,
            codec=codec,
        )
        for depth in option_depths:
            selected = [
                item
                for item in planned_rows
                if item.code in lean_pairs
                or (depth is not None and item.bge_rank is not None and item.bge_rank <= depth)
            ]
            scoring_rows = [item.scoring for item in selected]
            validation_rows = [item.validation for item in selected]
            jobs = _job_plans(scoring_rows, validation_rows)
            case_codes = frozenset(item.code for item in selected)
            option_rows[depth].append(
                {
                    "case": case.name,
                    "candidateCount": len(selected),
                    "pairSetDigest": _pair_set_digest(case_codes, codec),
                    "jobs": jobs,
                    "totals": _totals(jobs),
                }
            )
        print(f"planned {case.name}", file=sys.stderr, flush=True)

    options = []
    for depth in option_depths:
        pairs = option_sets[depth]
        pair_rows = option_rows[depth]
        all_jobs = [job for pair in pair_rows for job in pair["jobs"]]
        options.append(
            {
                "name": _option_name(depth),
                "bgeK": depth,
                "candidateCount": len(pairs),
                "pairSetDigest": _pair_set_digest(pairs, codec),
                "pairs": pair_rows,
                "campaign": {
                    "candidateCount": len(pairs),
                    **_totals(all_jobs),
                },
            }
        )

    report: dict[str, Any] = {
        "type": "AtlasRelationCandidateGroupedBatchCostPlan",
        "schemaVersion": "1.0",
        "status": "experimentalProposalOnly",
        "productionLanguageScope": "English",
        "providerCalls": 0,
        "pairCount": len(cases),
        "candidateIdentityPolicy": PROPOSAL_POLICY,
        "candidateIdentityMeaning": (
            "fixed proposal-only source/target identity used solely for deterministic packing"
        ),
        "candidateInput": ("full production hierarchy-aware source and target context; retrieval evidence is absent"),
        "batchPolicy": {
            "requestGroupSize": qspend.REQUEST_GROUP_SIZE,
            "batchPricingFactor": qbatch.BATCH_PRICE_FACTOR,
            "scorerFamily": qspend.SCORER_FAMILY,
            "judgeFamilies": list(qspend.JUDGE_FAMILIES),
            "modelsByFamily": dict(qspend.PRODUCTION_MODELS_BY_FAMILY),
            "groupOutputTokensPerRow": qbatch.GROUP_OUTPUT_TOKENS_PER_ROW,
        },
        "inputs": {
            "frontierReceipt": {
                "path": str(args.frontier_receipt),
                "sha256": _sha256(args.frontier_receipt),
            },
            "bgeRankManifest": {
                "path": str(args.bge_rank_manifest),
                "sha256": _sha256(args.bge_rank_manifest),
            },
            "bgeRankFile": {
                "path": str(args.bge_rank_file),
                "sha256": _sha256(args.bge_rank_file),
            },
            "leanPairCodes": lean_receipt,
        },
        "frontierVerification": (
            "lean and BGE K1/K3/K5/K10/K20 counts and pair-set digests reproduced exactly; "
            "BGE K15/K25/K50 derived from the same retained rank bytes"
        ),
        "plannedBgeDepths": list(selected_bge_depths),
        "options": options,
        "toolDigest": _sha256(Path(__file__).resolve()),
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    report["deterministicResultDigest"] = _stable_report_digest(report)
    return report


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--frontier-receipt", type=Path, required=True)
    parser.add_argument("--bge-rank-manifest", type=Path, required=True)
    parser.add_argument("--bge-rank-file", type=Path, required=True)
    parser.add_argument("--lean-pair-codes", type=Path, required=True)
    parser.add_argument(
        "--bge-depth",
        dest="bge_depths",
        type=int,
        choices=BGE_DEPTHS,
        action="append",
        help="plan only the selected retained BGE depth; repeat for several depths",
    )
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--workers", type=int, default=-1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.block_size < 1:
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
                "options": [
                    {
                        "name": option["name"],
                        "candidateCount": option["candidateCount"],
                        "pairSetDigest": option["pairSetDigest"],
                        "projectedCostUsd": option["campaign"]["projectedCostUsd"],
                    }
                    for option in report["options"]
                ],
                "output": str(args.output),
                "outputDigest": _sha256(args.output),
                "providerCalls": report["providerCalls"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
