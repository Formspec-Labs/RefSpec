"""Join fixed manual candidate decisions to withheld Atlas retrieval metadata.

This experimental tool reads an immutable blind-review sample and its separately
recorded Markdown decisions. It validates both inputs, joins by one-based row
number, and reports discovery yield without calling a model or changing either
input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from refspec.storage import canonical_json

DECISION_PATTERN = re.compile(r"\|\s*(\d+)\s*\|\s*`([a-z_]+)`\s*")
ALLOWED_VERDICTS = frozenset(
    {
        "exact",
        "close",
        "related",
        "source_is_broader",
        "source_is_narrower",
        "target_is_broader",
        "target_is_narrower",
        "unrelated",
        "insufficient_evidence",
    }
)
NON_POTENTIAL_VERDICTS = frozenset({"unrelated", "insufficient_evidence"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def parse_ordered_decisions(markdown: str, *, expected_rows: int) -> tuple[str, ...]:
    """Parse one unique verdict for every one-based sample row."""

    decisions: dict[int, str] = {}
    for row_text, verdict in DECISION_PATTERN.findall(markdown):
        row = int(row_text)
        if verdict not in ALLOWED_VERDICTS:
            raise ValueError(f"unsupported verdict for row {row}: {verdict}")
        if row in decisions:
            raise ValueError(f"duplicate decision for row {row}")
        decisions[row] = verdict
    expected = set(range(1, expected_rows + 1))
    actual = set(decisions)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"decisions do not match rows 1..{expected_rows}: missing={missing}, extra={extra}")
    return tuple(decisions[row] for row in range(1, expected_rows + 1))


def _selection_digest(row: Mapping[str, Any]) -> str:
    pair = f"{row['case']}\t{row['source']['member']}\t{row['target']['member']}\n".encode()
    return "sha256:" + hashlib.sha256(pair).hexdigest()


def _rank_band_bounds(sample: Mapping[str, Any]) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for stratum in sample["strata"]:
        band = stratum["rankBand"]
        bounds = (int(stratum["minimumRank"]), int(stratum["maximumRank"]))
        if band in result and result[band] != bounds:
            raise ValueError(f"rank band has conflicting bounds: {band}")
        result[band] = bounds
    return result


def validate_sample(sample: Mapping[str, Any]) -> None:
    """Verify the sample's internal digests, rank bands, and category semantics."""

    rows = sample.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("sample rows must be a non-empty list")
    if sample.get("targetRows") != len(rows):
        raise ValueError("targetRows does not equal the emitted row count")
    expected_sample_digest = "sha256:" + hashlib.sha256(canonical_json(rows).encode()).hexdigest()
    if sample.get("sampleDigest") != expected_sample_digest:
        raise ValueError("sampleDigest does not match the ordered rows")

    band_bounds = _rank_band_bounds(sample)
    cutoff = int(sample["reviewCutoff"])
    maximum = int(sample["retainedMaximumRank"])
    for index, row in enumerate(rows, start=1):
        if row.get("selectionDigest") != _selection_digest(row):
            raise ValueError(f"selectionDigest mismatch at row {index}")
        rank = int(row["bgeRank"])
        if not 1 <= rank <= maximum:
            raise ValueError(f"BGE rank outside retained range at row {index}: {rank}")
        bounds = band_bounds.get(row["rankBand"])
        if bounds is None or not bounds[0] <= rank <= bounds[1]:
            raise ValueError(f"rank-band mismatch at row {index}")

        membership = row["membershipAtReviewDepths"]
        category = row["sampleCategory"]
        if bool(membership["bgeK20"]) != (rank <= cutoff):
            raise ValueError(f"BGE cutoff membership mismatch at row {index}")
        if bool(membership["leanTwoFamilyFloor"]) != bool(membership["lexicalK3"] or membership["sparseGraphK1"]):
            raise ValueError(f"lean-floor membership mismatch at row {index}")
        if bool(membership["allThree"]) != bool(
            membership["lexicalK3"] and membership["sparseGraphK1"] and membership["bgeK20"]
        ):
            raise ValueError(f"three-family membership mismatch at row {index}")
        if category == "bge-only" and not (
            membership["bgeK20"] and not membership["lexicalK3"] and not membership["sparseGraphK1"]
        ):
            raise ValueError(f"BGE-only category mismatch at row {index}")
        if category == "three-family-overlap" and not membership["allThree"]:
            raise ValueError(f"three-family-overlap category mismatch at row {index}")
        if category == "just-outside-bge20" and not (cutoff < rank <= 25):
            raise ValueError(f"just-outside category mismatch at row {index}")


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    verdicts = Counter(str(row["verdict"]) for row in rows)
    potential = sum(bool(row["potentialRelation"]) for row in rows)
    return {
        "rows": len(rows),
        "potentialRelations": potential,
        "potentialYield": round(potential / len(rows), 8) if rows else None,
        "verdicts": dict(sorted(verdicts.items())),
    }


def _grouped_summary(
    rows: Sequence[Mapping[str, Any]],
    key: Callable[[Mapping[str, Any]], str],
    *,
    order: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    labels = list(order) if order is not None else sorted(groups)
    return [{"group": label, **_summary(groups[label])} for label in labels if label in groups]


def analyze(
    sample: Mapping[str, Any],
    decisions: Sequence[str],
    *,
    sample_file_sha256: str,
    decisions_file_sha256: str,
) -> dict[str, Any]:
    """Join decisions to sample rows and produce exact discovery-yield summaries."""

    validate_sample(sample)
    sample_rows = sample["rows"]
    if len(decisions) != len(sample_rows):
        raise ValueError("decision count does not equal sample row count")

    joined = []
    for row_number, (row, verdict) in enumerate(zip(sample_rows, decisions, strict=True), start=1):
        membership = row["membershipAtReviewDepths"]
        joined.append(
            {
                "row": row_number,
                "case": row["case"],
                "sampleCategory": row["sampleCategory"],
                "rankBand": row["rankBand"],
                "bgeRank": row["bgeRank"],
                "membershipAtReviewDepths": membership,
                "sourcePrefLabel": row["source"]["prefLabel"],
                "targetPrefLabel": row["target"]["prefLabel"],
                "selectionDigest": row["selectionDigest"],
                "verdict": verdict,
                "potentialRelation": verdict not in NON_POTENTIAL_VERDICTS,
            }
        )

    rank_order = [
        "rank-1",
        "ranks-2-3",
        "ranks-4-5",
        "ranks-6-10",
        "ranks-11-15",
        "ranks-16-20",
        "ranks-21-25",
    ]
    category_order = ["bge-only", "three-family-overlap", "just-outside-bge20"]
    cutoff_order = ["inside-bge-k20", "ranks-21-25"]
    comparison_rows = [row for row in joined if row["sampleCategory"] in {"bge-only", "three-family-overlap"}]
    decision_rows = [{"row": index, "verdict": verdict} for index, verdict in enumerate(decisions, start=1)]
    report: dict[str, Any] = {
        "type": "AtlasCandidateManualAuditAnalysis",
        "schemaVersion": "1.0",
        "interpretation": (
            "manual discovery-yield evidence from a deterministic relation-blind sample; "
            "the decisions are potential-relation judgments, not mapping ground truth"
        ),
        "potentialRelationRule": "every verdict except unrelated or insufficient_evidence",
        "inputs": {
            "sampleFileSha256": sample_file_sha256,
            "sampleDigest": sample["sampleDigest"],
            "decisionsFileSha256": decisions_file_sha256,
            "decisionCount": len(decisions),
            "decisionsDigest": "sha256:" + hashlib.sha256(canonical_json(decision_rows).encode()).hexdigest(),
        },
        "overall": _summary(joined),
        "byCase": _grouped_summary(joined, lambda row: str(row["case"])),
        "bySampleCategory": _grouped_summary(joined, lambda row: str(row["sampleCategory"]), order=category_order),
        "byRankBand": _grouped_summary(joined, lambda row: str(row["rankBand"]), order=rank_order),
        "byCutoffRegion": _grouped_summary(
            joined,
            lambda row: "inside-bge-k20" if int(row["bgeRank"]) <= int(sample["reviewCutoff"]) else "ranks-21-25",
            order=cutoff_order,
        ),
        "bgeOnlyVsThreeFamilyOverlap": _grouped_summary(
            comparison_rows,
            lambda row: str(row["sampleCategory"]),
            order=category_order[:2],
        ),
        "comparisonScope": "inside BGE K=20 only; rows just outside K=20 are summarized separately",
        "joinedRowsDigest": "sha256:" + hashlib.sha256(canonical_json(joined).encode()).hexdigest(),
        "joinedRows": joined,
    }
    stable = dict(report)
    stable.pop("analysisDigest", None)
    report["analysisDigest"] = "sha256:" + hashlib.sha256(canonical_json(stable).encode()).hexdigest()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True, help="Atlas blind-review sample JSON")
    parser.add_argument("--decisions", type=Path, required=True, help="Markdown file containing fixed row verdicts")
    parser.add_argument("--summary-only", action="store_true", help="Omit joinedRows while retaining its digest")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    decisions = parse_ordered_decisions(args.decisions.read_text(encoding="utf-8"), expected_rows=len(sample["rows"]))
    report = analyze(
        sample,
        decisions,
        sample_file_sha256=_sha256(args.sample),
        decisions_file_sha256=_sha256(args.decisions),
    )
    if args.summary_only:
        report.pop("joinedRows")
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
