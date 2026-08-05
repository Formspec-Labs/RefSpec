"""Build a blind manual-audit sample from sealed Atlas judge evidence.

This experiment reads completed qualification artifacts only.  It never calls
a provider and never changes a qualification run.  The blind sample contains
the two concept records but excludes generator classes, controls, model
answers, dispositions, and admitted relations.  A separately sealed key lets a
reviewer compare an independent judgment after completing the sample.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from refspec.storage import canonical_json

DEFAULT_SEED = "refspec-atlas-judge-audit-2026-08-05"
FORBIDDEN_BLIND_FIELDS = frozenset(
    {
        "answer",
        "control",
        "disposition",
        "evidence",
        "generationClass",
        "generationPolicy",
        "judgeReceipts",
        "proposedRelation",
        "relation",
        "scoringInputDigest",
        "verdict",
    }
)


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _read_json_lines(path: Path) -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(line) for line in path.read_text().splitlines() if line.strip())


def _quantiles(values: Sequence[int]) -> dict[str, int] | None:
    if not values:
        return None
    ordered = sorted(values)

    def value_at(numerator: int, denominator: int) -> int:
        index = ((len(ordered) - 1) * numerator + denominator - 1) // denominator
        return ordered[index]

    return {
        "minimum": ordered[0],
        "p50": value_at(1, 2),
        "p95": value_at(95, 100),
        "maximum": ordered[-1],
    }


def _assert_blind(value: object) -> None:
    if isinstance(value, Mapping):
        leaked = FORBIDDEN_BLIND_FIELDS & value.keys()
        if leaked:
            raise ValueError(f"blind audit row leaks fields: {sorted(leaked)!r}")
        for child in value.values():
            _assert_blind(child)
    elif isinstance(value, list | tuple):
        for child in value:
            _assert_blind(child)


def _load_run(path: Path) -> dict[str, Any]:
    catalog = _read_json(path / "candidates.json")
    run_receipt = _read_json(path / "qualification-receipt.json")
    receipts = _read_json_lines(path / "receipts.jsonl")
    candidates = catalog.get("candidates")
    accounting = run_receipt.get("candidateAccounting")
    if not isinstance(candidates, list) or not isinstance(accounting, list):
        raise TypeError(f"{path}: candidate catalog or accounting is malformed")
    candidate_by_id = {row["candidateId"]: row for row in candidates}
    accounting_by_id = {row["candidateId"]: row for row in accounting}
    if len(candidate_by_id) != len(candidates) or len(accounting_by_id) != len(accounting):
        raise ValueError(f"{path}: duplicate candidate identifier")
    if set(candidate_by_id) != set(accounting_by_id):
        raise ValueError(f"{path}: catalog and accounting candidate sets differ")

    receipt_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for receipt in receipts:
        receipt_by_candidate[receipt["candidate_id"]].append(receipt)
    if set(receipt_by_candidate) != set(candidate_by_id):
        raise ValueError(f"{path}: receipt and candidate sets differ")

    expected_families = tuple(sorted(model["family"] for model in run_receipt["models"]))
    for candidate_id, rows in receipt_by_candidate.items():
        families = tuple(sorted(row["family"] for row in rows))
        if families != expected_families:
            raise ValueError(f"{path}: {candidate_id} does not have one receipt per family")
        if any(row.get("outcome") != "completed" for row in rows):
            raise ValueError(f"{path}: {candidate_id} has an incomplete judgment")

    return {
        "name": path.name,
        "path": str(path),
        "catalog": catalog,
        "runReceipt": run_receipt,
        "candidateById": candidate_by_id,
        "accountingById": accounting_by_id,
        "receiptByCandidate": receipt_by_candidate,
        "expectedFamilies": expected_families,
    }


def build_audit(
    run_paths: Sequence[Path],
    *,
    per_stratum: int,
    seed: str = DEFAULT_SEED,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return summary, blind sample, and answer key for sealed run paths."""

    if per_stratum < 1:
        raise ValueError("per-stratum must be positive")
    runs = tuple(_load_run(path) for path in sorted(run_paths, key=lambda item: str(item)))
    if not runs:
        raise ValueError("at least one run is required")

    strata: dict[tuple[str, str], list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for run in runs:
        for candidate_id, candidate in run["candidateById"].items():
            generation_class = candidate["generationClass"]
            strata[(run["name"], generation_class)].append((run, candidate_id))

    selected: list[tuple[dict[str, Any], str]] = []
    for stratum, members in sorted(strata.items()):
        if len(members) < per_stratum:
            raise ValueError(f"stratum {stratum!r} has only {len(members)} candidates")
        selected.extend(
            sorted(
                members,
                key=lambda item: hashlib.sha256(f"{seed}|{stratum[0]}|{stratum[1]}|{item[1]}".encode()).digest(),
            )[:per_stratum]
        )

    blind_rows = []
    key_rows = []
    for run, candidate_id in selected:
        candidate = run["candidateById"][candidate_id]
        accounting = run["accountingById"][candidate_id]
        audit_id = "audit-" + hashlib.sha256(f"{seed}|{run['name']}|{candidate_id}".encode()).hexdigest()[:20]
        blind_rows.append(
            {
                "auditId": audit_id,
                "vocabularyPair": run["name"],
                "source": candidate["source"],
                "target": candidate["target"],
            }
        )
        judgments = []
        for receipt in sorted(run["receiptByCandidate"][candidate_id], key=lambda row: row["family"]):
            judgments.append(
                {
                    "family": receipt["family"],
                    "model": receipt["model_id"],
                    "verdict": receipt["answer"]["verdict"],
                    "reason": receipt["answer"]["reason"],
                    "receiptDigest": receipt.get("content_digest") or _sha256(receipt),
                }
            )
        key_rows.append(
            {
                "auditId": audit_id,
                "candidateId": candidate_id,
                "vocabularyPair": run["name"],
                "generationClass": candidate["generationClass"],
                "control": accounting["control"],
                "disposition": accounting["disposition"],
                **({"relation": accounting["relation"]} if "relation" in accounting else {}),
                "judgments": judgments,
            }
        )

    order = {row["auditId"]: hashlib.sha256(f"{seed}|order|{row['auditId']}".encode()).digest() for row in blind_rows}
    blind_rows.sort(key=lambda row: order[row["auditId"]])
    key_rows.sort(key=lambda row: order[row["auditId"]])
    _assert_blind(blind_rows)

    verdict_pairs: Counter[tuple[str, ...]] = Counter()
    reason_lengths: dict[str, list[int]] = defaultdict(list)
    completion_tokens: dict[str, list[int]] = defaultdict(list)
    class_totals: Counter[str] = Counter()
    class_qualified: Counter[str] = Counter()
    total_candidates = 0
    total_receipts = 0
    for run in runs:
        total_candidates += len(run["candidateById"])
        total_receipts += sum(len(rows) for rows in run["receiptByCandidate"].values())
        for generation_class, row in run["runReceipt"]["candidatesByClass"].items():
            class_totals[generation_class] += row["candidates"]
            class_qualified[generation_class] += row["qualified"]
        for rows in run["receiptByCandidate"].values():
            ordered = sorted(rows, key=lambda row: row["family"])
            verdict_pairs[tuple(row["answer"]["verdict"] for row in ordered)] += 1
            for row in ordered:
                family = row["family"]
                reason_lengths[family].append(len(row["answer"]["reason"]))
                tokens = row.get("usage", {}).get("completion_tokens")
                if isinstance(tokens, int) and tokens > 0:
                    completion_tokens[family].append(tokens)

    exact_verdict_agreement = sum(count for verdicts, count in verdict_pairs.items() if len(set(verdicts)) == 1)
    blind = {
        "type": "AtlasHistoricalJudgmentBlindAuditSample",
        "schemaVersion": "1.0",
        "languageScope": "en",
        "seed": seed,
        "rows": blind_rows,
    }
    key = {
        "type": "AtlasHistoricalJudgmentAuditKey",
        "schemaVersion": "1.0",
        "blindSampleDigest": _sha256(blind),
        "rows": key_rows,
    }
    summary = {
        "type": "AtlasHistoricalJudgmentAuditSummary",
        "schemaVersion": "1.0",
        "providerCalls": False,
        "runs": [
            {
                "name": run["name"],
                "path": run["path"],
                "candidates": len(run["candidateById"]),
                "families": list(run["expectedFamilies"]),
            }
            for run in runs
        ],
        "candidateCount": total_candidates,
        "receiptCount": total_receipts,
        "allJudgmentsCompleted": True,
        "exactVerdictAgreement": exact_verdict_agreement,
        "exactVerdictAgreementRate": round(exact_verdict_agreement / total_candidates, 8),
        "classAccounting": {
            name: {"candidates": class_totals[name], "compatibleSupport": class_qualified[name]}
            for name in sorted(class_totals)
        },
        "reasonCharacterDistribution": {
            family: _quantiles(values) for family, values in sorted(reason_lengths.items())
        },
        "reportedCompletionTokenDistribution": {
            family: _quantiles(values) for family, values in sorted(completion_tokens.items())
        },
        "sample": {
            "perRunAndGenerationClass": per_stratum,
            "rows": len(blind_rows),
            "blindDigest": _sha256(blind),
            "keyDigest": _sha256(key),
        },
    }
    return summary, blind, key


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True, type=Path)
    parser.add_argument("--per-stratum", type=int, default=6)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--blind-output", required=True, type=Path)
    parser.add_argument("--key-output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary, blind, key = build_audit(args.run, per_stratum=args.per_stratum, seed=args.seed)
    _write(args.output, summary)
    _write(args.blind_output, blind)
    _write(args.key_output, key)
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
