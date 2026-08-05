"""Join fixed Atlas tail-review decisions to their withheld BGE ranks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from refspec.storage import canonical_json

try:
    from tools import analyze_atlas_candidate_manual_audit as base
except ImportError:  # Direct execution places tools/ on sys.path.
    import analyze_atlas_candidate_manual_audit as base


CUTOFFS = (25, 30, 35, 40, 45, 50)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    verdicts = Counter(str(row["verdict"]) for row in rows)
    potential = sum(bool(row["potentialRelation"]) for row in rows)
    return {
        "rows": len(rows),
        "potentialRelations": potential,
        "potentialYield": round(potential / len(rows), 8) if rows else None,
        "verdicts": dict(sorted(verdicts.items())),
    }


def validate_tail_sample(sample: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Verify the tail sample's internal chain, strata, and BGE-only boundary."""

    rows = sample.get("rows")
    strata = sample.get("strata")
    if not isinstance(rows, list) or not isinstance(strata, list) or not rows or not strata:
        raise ValueError("tail sample rows and strata must be non-empty lists")
    if sample.get("targetRows") != len(rows):
        raise ValueError("targetRows does not equal the emitted tail row count")
    expected_digest = "sha256:" + hashlib.sha256(canonical_json(rows).encode()).hexdigest()
    if sample.get("sampleDigest") != expected_digest:
        raise ValueError("sampleDigest does not match the ordered tail rows")

    strata_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for stratum in strata:
        key = (str(stratum["case"]), str(stratum["rankBand"]))
        if key in strata_by_key:
            raise ValueError(f"duplicate tail stratum: {key}")
        if int(stratum["eligibleBgeOnlyPopulation"]) < int(stratum["requestedRows"]):
            raise ValueError(f"tail stratum is short: {key}")
        strata_by_key[key] = stratum

    emitted = Counter((str(row["case"]), str(row["rankBand"])) for row in rows)
    for key, stratum in strata_by_key.items():
        expected = int(stratum["sampledRows"])
        if emitted[key] != expected or expected != int(stratum["requestedRows"]):
            raise ValueError(f"tail stratum emitted the wrong row count: {key}")
    if set(emitted) != set(strata_by_key):
        raise ValueError("tail rows and declared strata differ")

    case_counts = Counter(str(row["case"]) for row in rows)
    if len(set(case_counts.values())) != 1:
        raise ValueError("tail sample is not balanced by vocabulary pair")
    for index, row in enumerate(rows, start=1):
        key = (str(row["case"]), str(row["rankBand"]))
        stratum = strata_by_key[key]
        rank = int(row["bgeRank"])
        if not int(stratum["minimumRank"]) <= rank <= int(stratum["maximumRank"]):
            raise ValueError(f"rank-band mismatch at tail row {index}")
        if row.get("selectionDigest") != base._selection_digest(row):
            raise ValueError(f"selectionDigest mismatch at tail row {index}")
        membership = row["membershipAtReviewDepths"]
        if membership != {"bgeK20": False, "bgeRetainedK50": True, "leanTwoFamilyFloor": False}:
            raise ValueError(f"tail retrieval membership mismatch at row {index}")
        if row.get("sampleCategory") != "bge-only-tail":
            raise ValueError(f"tail sample category mismatch at row {index}")
        if set(row["source"]["bgeViewTexts"]) != set(sample["views"]):
            raise ValueError(f"source views differ at tail row {index}")
        if set(row["target"]["bgeViewTexts"]) != set(sample["views"]):
            raise ValueError(f"target views differ at tail row {index}")
        forbidden = {"verdict", "typedGold", "typedRelation", "gold", "mappingRelation"}
        if forbidden & set(row):
            raise ValueError(f"answer metadata leaked into tail row {index}")
    return strata_by_key


def validate_rendering(rendering: str, rows: Sequence[Mapping[str, Any]]) -> None:
    """Check the context rendering's order and withheld-metadata boundary."""

    headings = re.findall(r"^## Row (\d+) — ([^\n]+)$", rendering, flags=re.MULTILINE)
    expected = [(str(index), str(row["case"])) for index, row in enumerate(rows, start=1)]
    if headings != expected:
        raise ValueError("rendering row headings differ from the sealed sample order")
    if len(re.findall(r"^### Source concept$", rendering, flags=re.MULTILINE)) != len(rows):
        raise ValueError("rendering does not contain one source section per row")
    if len(re.findall(r"^### Target concept$", rendering, flags=re.MULTILINE)) != len(rows):
        raise ValueError("rendering does not contain one target section per row")
    forbidden = ("bge-only-tail", "leanTwoFamilyFloor", "selectionDigest", "membershipAtReviewDepths")
    if any(value in rendering for value in forbidden):
        raise ValueError("sealed selection metadata leaked into the context rendering")


def _coverage(rows: Sequence[Mapping[str, Any]], *, denominator: int) -> list[dict[str, Any]]:
    result = []
    for cutoff in CUTOFFS:
        included = [row for row in rows if int(row["bgeRank"]) <= cutoff]
        potential = sum(bool(row["potentialRelation"]) for row in included)
        result.append(
            {
                "cutoff": f"K{cutoff}",
                "reviewedRowsIncluded": len(included),
                "potentialRelationsIncluded": potential,
                "potentialCoverage": round(potential / denominator, 8) if denominator else None,
                "includedSampleYield": round(potential / len(included), 8) if included else None,
            }
        )
    return result


def validate_prefix_analysis(prefix: Mapping[str, Any]) -> None:
    """Verify the sealed ranks-1-through-25 manual-analysis receipt."""

    if prefix.get("type") != "AtlasCandidateManualAuditAnalysis":
        raise ValueError("prefix analysis has the wrong type")
    stable = dict(prefix)
    expected = stable.pop("analysisDigest")
    actual = "sha256:" + hashlib.sha256(canonical_json(stable).encode()).hexdigest()
    if actual != expected:
        raise ValueError("prefix analysis digest does not reproduce")
    if (
        prefix["joinedRowsDigest"]
        != "sha256:" + hashlib.sha256(canonical_json(prefix["joinedRows"]).encode()).hexdigest()
    ):
        raise ValueError("prefix joined-row digest does not reproduce")
    if any(int(row["bgeRank"]) > 25 for row in prefix["joinedRows"]):
        raise ValueError("prefix analysis contains a row above K25")


def analyze(
    sample: Mapping[str, Any],
    decisions: Sequence[str],
    *,
    sample_file_sha256: str,
    decisions_file_sha256: str,
    rendering_file_sha256: str,
    prefix_analysis: Mapping[str, Any] | None = None,
    prefix_analysis_file_sha256: str | None = None,
) -> dict[str, Any]:
    strata = validate_tail_sample(sample)
    if len(decisions) != len(sample["rows"]):
        raise ValueError("tail decision count does not equal sample row count")

    joined = []
    for row_number, (row, verdict) in enumerate(zip(sample["rows"], decisions, strict=True), start=1):
        joined.append(
            {
                "row": row_number,
                "case": row["case"],
                "rankBand": row["rankBand"],
                "bgeRank": row["bgeRank"],
                "sourcePrefLabel": row["source"]["prefLabel"],
                "targetPrefLabel": row["target"]["prefLabel"],
                "selectionDigest": row["selectionDigest"],
                "verdict": verdict,
                "potentialRelation": verdict not in base.NON_POTENTIAL_VERDICTS,
            }
        )

    by_case = []
    for case in sorted({str(row["case"]) for row in joined}):
        by_case.append({"case": case, **_summary([row for row in joined if row["case"] == case])})

    by_stratum = []
    for key, stratum in sorted(
        strata.items(), key=lambda item: (int(item[1]["minimumRank"]), int(item[1]["maximumRank"]), item[0])
    ):
        rows = [row for row in joined if (row["case"], row["rankBand"]) == key]
        by_stratum.append(
            {
                "case": key[0],
                "rankBand": key[1],
                "minimumRank": stratum["minimumRank"],
                "maximumRank": stratum["maximumRank"],
                "eligibleBgeOnlyPopulation": stratum["eligibleBgeOnlyPopulation"],
                **_summary(rows),
            }
        )

    band_groups: dict[tuple[str, int, int], list[Mapping[str, Any]]] = {}
    for row in joined:
        stratum = strata[(str(row["case"]), str(row["rankBand"]))]
        key = (str(row["rankBand"]), int(stratum["minimumRank"]), int(stratum["maximumRank"]))
        band_groups.setdefault(key, []).append(row)
    by_actual_band = [
        {"rankBand": key[0], "minimumRank": key[1], "maximumRank": key[2], **_summary(rows)}
        for key, rows in sorted(band_groups.items(), key=lambda item: (item[0][1], item[0][2], item[0][0]))
    ]

    tail_potential = _summary(joined)["potentialRelations"]
    report: dict[str, Any] = {
        "type": "AtlasCandidateTailManualAuditAnalysis",
        "schemaVersion": "1.0",
        "interpretation": (
            "manual discovery-yield evidence from deterministic relation-blind strata; "
            "the decisions are potential-relation judgments, not mapping ground truth or pool precision"
        ),
        "potentialRelationRule": "every verdict except unrelated or insufficient_evidence",
        "inputs": {
            "sampleFileSha256": sample_file_sha256,
            "sampleDigest": sample["sampleDigest"],
            "decisionsFileSha256": decisions_file_sha256,
            "renderingFileSha256": rendering_file_sha256,
            "decisionCount": len(decisions),
            "decisionsDigest": "sha256:"
            + hashlib.sha256(
                canonical_json(
                    [{"row": index, "verdict": verdict} for index, verdict in enumerate(decisions, start=1)]
                ).encode()
            ).hexdigest(),
        },
        "overall": _summary(joined),
        "byCase": by_case,
        "byActualRankBand": by_actual_band,
        "byCaseAndRankStratum": by_stratum,
        "tailCumulativeCoverage": _coverage(joined, denominator=tail_potential),
        "tailCoverageMeaning": "share of the 60-row tail sample's potential relations at or below each cutoff",
        "joinedRowsDigest": "sha256:" + hashlib.sha256(canonical_json(joined).encode()).hexdigest(),
        "joinedRows": joined,
    }

    if prefix_analysis is not None:
        validate_prefix_analysis(prefix_analysis)
        prefix_rows = prefix_analysis["joinedRows"]
        combined = [*prefix_rows, *joined]
        combined_potential = sum(bool(row["potentialRelation"]) for row in combined)
        report["inputs"]["prefixAnalysisFileSha256"] = prefix_analysis_file_sha256
        report["inputs"]["prefixAnalysisDigest"] = prefix_analysis["analysisDigest"]
        report["combinedReviewedPotentialRelations"] = combined_potential
        report["combinedCumulativeCoverage"] = _coverage(combined, denominator=combined_potential)
        report["combinedCoverageMeaning"] = (
            "share of potential relations across the earlier 120-row ranks-1-through-25 review and this "
            "60-row tail review; both samples are stratified and this is not population-weighted precision"
        )
        unique_prefix = [row for row in prefix_rows if not bool(row["membershipAtReviewDepths"]["leanTwoFamilyFloor"])]
        unique_combined = [*unique_prefix, *joined]
        unique_potential = sum(bool(row["potentialRelation"]) for row in unique_combined)
        report["bgeUniqueReviewedRows"] = len(unique_combined)
        report["bgeUniqueReviewedPotentialRelations"] = unique_potential
        report["bgeUniqueCumulativeCoverage"] = _coverage(unique_combined, denominator=unique_potential)
        report["bgeUniqueCoverageMeaning"] = (
            "share of manually identified potential relations among rows outside the lean lexical-K3 plus "
            "sparse-K1 floor; this isolates the BGE arm's unique sampled discovery population and remains "
            "stratified rather than population-weighted"
        )

    report["analysisDigest"] = "sha256:" + hashlib.sha256(canonical_json(report).encode()).hexdigest()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--rendering", type=Path, required=True)
    parser.add_argument("--prefix-analysis", type=Path)
    parser.add_argument("--summary-only", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    decisions_text = args.decisions.read_text(encoding="utf-8")
    rendering_text = args.rendering.read_text(encoding="utf-8")
    decisions = base.parse_ordered_decisions(decisions_text, expected_rows=len(sample["rows"]))
    validate_rendering(rendering_text, sample["rows"])

    sample_sha = _sha256(args.sample)
    rendering_sha = _sha256(args.rendering)
    for expected in (sample_sha.removeprefix("sha256:"), sample["sampleDigest"], rendering_sha.removeprefix("sha256:")):
        if expected not in decisions_text:
            raise ValueError("decision record does not pin every sample/rendering receipt")

    prefix = json.loads(args.prefix_analysis.read_text(encoding="utf-8")) if args.prefix_analysis else None
    report = analyze(
        sample,
        decisions,
        sample_file_sha256=sample_sha,
        decisions_file_sha256=_sha256(args.decisions),
        rendering_file_sha256=rendering_sha,
        prefix_analysis=prefix,
        prefix_analysis_file_sha256=_sha256(args.prefix_analysis) if args.prefix_analysis else None,
    )
    if args.summary_only:
        report.pop("joinedRows")
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
