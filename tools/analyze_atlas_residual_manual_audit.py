"""Join fixed Atlas outside-BGE-K50 decisions to sealed population metadata.

This experimental tool validates the deterministic relation-blind residual
sample, its context-only rendering, and the separately recorded Markdown
decisions.  It reports exact sample observations and population boundaries;
it does not extrapolate prevalence, call a model, or change an input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from refspec.atlas.parquet_artifact import file_sha256 as _sha256
from refspec.storage import canonical_json

try:
    from tools import analyze_atlas_candidate_manual_audit as base
except ImportError:  # Direct execution places tools/ on sys.path.
    import analyze_atlas_candidate_manual_audit as base


EXPECTED_POPULATION = "outside-lean-floor-and-outside-bge-k50"
FORBIDDEN_ROW_FIELDS = frozenset(
    {
        "bgeRank",
        "gold",
        "mappingRelation",
        "membershipAtReviewDepths",
        "rank",
        "rankBand",
        "sampleCategory",
        "typedGold",
        "typedRelation",
        "verdict",
    }
)


def _selection_digest(row: Mapping[str, Any], *, seed: str) -> str:
    value = (
        seed.encode("utf-8")
        + b"\x00"
        + str(row["case"]).encode("utf-8")
        + b"\x00"
        + str(row["source"]["member"]).encode("utf-8")
        + b"\x00"
        + str(row["target"]["member"]).encode("utf-8")
        + b"\n"
    )
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _population_fields(row: Mapping[str, Any]) -> dict[str, int]:
    return {
        key: int(row[key])
        for key in (
            "sourceConcepts",
            "targetConcepts",
            "cartesianPairs",
            "leanFloorPairs",
            "bgeK50Pairs",
            "leanBgeK50Overlap",
            "outsideBgeK50Pairs",
            "leanOutsideBgeK50Pairs",
            "outsideBothPairs",
        )
    }


def _validate_population(row: Mapping[str, Any]) -> dict[str, int]:
    values = _population_fields(row)
    case = str(row["case"])
    if values["cartesianPairs"] != values["sourceConcepts"] * values["targetConcepts"]:
        raise ValueError(f"Cartesian population mismatch for {case}")
    if values["outsideBgeK50Pairs"] != values["cartesianPairs"] - values["bgeK50Pairs"]:
        raise ValueError(f"outside-BGE-K50 population mismatch for {case}")
    if values["leanOutsideBgeK50Pairs"] != values["leanFloorPairs"] - values["leanBgeK50Overlap"]:
        raise ValueError(f"lean-outside-BGE-K50 population mismatch for {case}")
    if values["outsideBothPairs"] != (values["outsideBgeK50Pairs"] - values["leanOutsideBgeK50Pairs"]):
        raise ValueError(f"outside-both population mismatch for {case}")
    if values["outsideBothPairs"] != values["cartesianPairs"] - (
        values["leanFloorPairs"] + values["bgeK50Pairs"] - values["leanBgeK50Overlap"]
    ):
        raise ValueError(f"population inclusion-exclusion mismatch for {case}")
    if any(value < 0 for value in values.values()):
        raise ValueError(f"negative population value for {case}")
    return values


def validate_sample(sample: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Verify residual populations, selection receipts, and the blind boundary."""

    if sample.get("type") != "AtlasBlindCandidateResidualReviewSample":
        raise ValueError("residual sample has the wrong type")
    rows = sample.get("rows")
    sampled_cases = sample.get("sampledCases")
    fully_covered = sample.get("fullyCoveredCases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("residual sample rows must be a non-empty list")
    if not isinstance(sampled_cases, list) or not sampled_cases:
        raise ValueError("sampledCases must be a non-empty list")
    if not isinstance(fully_covered, list):
        raise TypeError("fullyCoveredCases must be a list")
    if sample.get("targetRows") != len(rows):
        raise ValueError("targetRows does not equal the residual row count")
    expected_digest = "sha256:" + hashlib.sha256(canonical_json(rows).encode()).hexdigest()
    if sample.get("sampleDigest") != expected_digest:
        raise ValueError("sampleDigest does not match the ordered residual rows")

    population_evidence = {"fullyCoveredCases": fully_covered, "sampledCases": sampled_cases}
    expected_population_digest = "sha256:" + hashlib.sha256(canonical_json(population_evidence).encode()).hexdigest()
    if sample.get("populationEvidenceDigest") != expected_population_digest:
        raise ValueError("populationEvidenceDigest does not reproduce")

    population_by_case: dict[str, Mapping[str, Any]] = {}
    for population in (*sampled_cases, *fully_covered):
        case = str(population["case"])
        if case in population_by_case:
            raise ValueError(f"duplicate residual population case: {case}")
        values = _validate_population(population)
        sampled_rows = int(population["sampledRows"])
        if population in sampled_cases:
            requested = int(population["requestedRows"])
            if values["outsideBothPairs"] <= 0:
                raise ValueError(f"sampled residual case is empty: {case}")
            if requested != sampled_rows or requested > values["outsideBothPairs"]:
                raise ValueError(f"sampled residual case has an invalid quota: {case}")
        elif values["outsideBothPairs"] != 0 or sampled_rows != 0:
            raise ValueError(f"fully covered case has residual rows: {case}")
        population_by_case[case] = population

    rows_per_case = Counter(str(row["case"]) for row in rows)
    expected_cases = {str(row["case"]) for row in sampled_cases}
    if set(rows_per_case) != expected_cases:
        raise ValueError("residual rows and sampledCases differ")
    for population in sampled_cases:
        case = str(population["case"])
        if rows_per_case[case] != int(population["sampledRows"]):
            raise ValueError(f"residual case emitted the wrong row count: {case}")
    if len(set(rows_per_case.values())) != 1 or next(iter(rows_per_case.values())) != int(sample["rowsPerSampledCase"]):
        raise ValueError("residual sample is not balanced by nonempty vocabulary pair")

    rule = sample.get("selectionRule")
    if not isinstance(rule, Mapping) or rule.get("algorithm") != "SHA-256" or not rule.get("seed"):
        raise ValueError("residual selection rule is incomplete")
    seed = str(rule["seed"])
    views = set(sample.get("views", ()))
    emitted_order: list[str] = []
    previous_case: str | None = None
    digests_by_case: dict[str, list[str]] = {}
    identities: set[tuple[str, str, str]] = set()
    required_concept_fields = {
        "member",
        "vocabulary",
        "prefLabel",
        "altLabels",
        "definition",
        "scopeNote",
        "parents",
        "children",
        "bgeViewTexts",
    }
    for index, row in enumerate(rows, start=1):
        case = str(row["case"])
        if case != previous_case:
            emitted_order.append(case)
            previous_case = case
        if row.get("population") != EXPECTED_POPULATION:
            raise ValueError(f"residual population marker mismatch at row {index}")
        if FORBIDDEN_ROW_FIELDS & set(row):
            raise ValueError(f"answer or rank metadata leaked into residual row {index}")
        if row.get("selectionDigest") != _selection_digest(row, seed=seed):
            raise ValueError(f"selectionDigest mismatch at residual row {index}")
        digests_by_case.setdefault(case, []).append(str(row["selectionDigest"]))
        source = row["source"]
        target = row["target"]
        if set(source) != set(target) or not required_concept_fields <= set(source):
            raise ValueError(f"source and target facts are unbalanced at residual row {index}")
        if set(source["bgeViewTexts"]) != views or set(target["bgeViewTexts"]) != views:
            raise ValueError(f"five-view facts differ at residual row {index}")
        identity = (case, str(source["member"]), str(target["member"]))
        if identity in identities:
            raise ValueError(f"duplicate pair at residual row {index}")
        identities.add(identity)
    expected_order = [str(row["case"]) for row in sampled_cases]
    if emitted_order != expected_order:
        raise ValueError("residual case order differs from sampledCases")
    if any(values != sorted(values) for values in digests_by_case.values()):
        raise ValueError("residual rows are not ordered by selection digest within case")
    return population_by_case


def validate_rendering(rendering: str, rows: Sequence[Mapping[str, Any]]) -> None:
    """Check row order and ensure the human rendering withholds row metadata."""

    headings = re.findall(r"^## Row (\d+) — ([^\n]+)$", rendering, flags=re.MULTILINE)
    expected = [(str(index), str(row["case"])) for index, row in enumerate(rows, start=1)]
    if headings != expected:
        raise ValueError("rendering row headings differ from the residual sample order")
    if len(re.findall(r"^### Source concept$", rendering, flags=re.MULTILINE)) != len(rows):
        raise ValueError("rendering does not contain one source section per residual row")
    if len(re.findall(r"^### Target concept$", rendering, flags=re.MULTILINE)) != len(rows):
        raise ValueError("rendering does not contain one target section per residual row")
    forbidden = ("selectionDigest", "membershipAtReviewDepths", "sampleCategory", "bgeRank")
    if any(value in rendering for value in forbidden):
        raise ValueError("sealed selection metadata leaked into the residual rendering")


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    verdicts = Counter(str(row["verdict"]) for row in rows)
    potential = sum(bool(row["potentialRelation"]) for row in rows)
    return {
        "rows": len(rows),
        "potentialRelations": potential,
        "potentialYield": round(potential / len(rows), 8) if rows else None,
        "verdicts": dict(sorted(verdicts.items())),
    }


def analyze(
    sample: Mapping[str, Any],
    decisions: Sequence[str],
    *,
    sample_file_sha256: str,
    decisions_file_sha256: str,
    rendering_file_sha256: str,
) -> dict[str, Any]:
    """Join fixed decisions and report exact observations without extrapolation."""

    populations = validate_sample(sample)
    rows = sample["rows"]
    if len(decisions) != len(rows):
        raise ValueError("residual decision count does not equal sample row count")

    joined = []
    for row_number, (row, verdict) in enumerate(zip(rows, decisions, strict=True), start=1):
        joined.append(
            {
                "row": row_number,
                "case": row["case"],
                "population": row["population"],
                "sourcePrefLabel": row["source"]["prefLabel"],
                "targetPrefLabel": row["target"]["prefLabel"],
                "selectionDigest": row["selectionDigest"],
                "verdict": verdict,
                "potentialRelation": verdict not in base.NON_POTENTIAL_VERDICTS,
            }
        )

    sampled_cases = [str(row["case"]) for row in sample["sampledCases"]]
    outside_total = sum(int(populations[case]["outsideBothPairs"]) for case in sampled_cases)
    by_case = []
    for case in sampled_cases:
        population = populations[case]
        case_rows = [row for row in joined if row["case"] == case]
        residual = int(population["outsideBothPairs"])
        by_case.append(
            {
                "case": case,
                "residualPopulation": residual,
                "residualPopulationShare": round(residual / outside_total, 8),
                "sampleFraction": round(len(case_rows) / residual, 12),
                "sampledOneInEveryPairs": round(residual / len(case_rows), 3),
                **_summary(case_rows),
            }
        )

    cartesian_total = sum(int(row["cartesianPairs"]) for row in populations.values())
    selected_total = sum(
        int(row["leanFloorPairs"]) + int(row["bgeK50Pairs"]) - int(row["leanBgeK50Overlap"])
        for row in populations.values()
    )
    if cartesian_total - selected_total != outside_total:
        raise ValueError("aggregate residual population does not reconcile")

    decision_rows = [{"row": index, "verdict": verdict} for index, verdict in enumerate(decisions, start=1)]
    potential_cases = [row["case"] for row in by_case if row["potentialRelations"] > 0]
    potential_total = sum(row["potentialRelations"] for row in by_case)
    if potential_cases:
        existence = (
            f"the fixed review observed {potential_total} potential direct relation outside lean plus BGE "
            f"K50 in {len(potential_cases)} of {len(by_case)} residual cases: {', '.join(potential_cases)}"
        )
        k50_boundary = (
            "K50 is a reproducible bounded retrieval boundary; the observed direct residual relation "
            "prevents a semantic-saturation claim"
        )
    else:
        existence = "the fixed review observed no potential direct relation in its residual sentinel rows"
        k50_boundary = (
            "K50 is a reproducible bounded retrieval boundary; a zero-row observation would not prove "
            "semantic saturation"
        )
    report: dict[str, Any] = {
        "type": "AtlasResidualManualAuditAnalysis",
        "schemaVersion": "1.0",
        "interpretation": (
            "exact observations from a deterministic relation-blind residual sentinel after a directness "
            "and nonredundancy test; potential-relation decisions are neither mapping ground truth nor a "
            "population estimate"
        ),
        "potentialRelationRule": (
            "every verdict except unrelated or insufficient_evidence after excluding thematic associations "
            "better expressed through native or qualified graph paths"
        ),
        "inputs": {
            "sampleFileSha256": sample_file_sha256,
            "sampleDigest": sample["sampleDigest"],
            "populationEvidenceDigest": sample["populationEvidenceDigest"],
            "decisionsFileSha256": decisions_file_sha256,
            "renderingFileSha256": rendering_file_sha256,
            "decisionCount": len(decisions),
            "decisionsDigest": "sha256:" + hashlib.sha256(canonical_json(decision_rows).encode()).hexdigest(),
        },
        "population": {
            "cartesianPairs": cartesian_total,
            "selectedByLeanOrBgeK50Pairs": selected_total,
            "outsideBothPairs": outside_total,
            "selectedShare": round(selected_total / cartesian_total, 8),
            "outsideBothShare": round(outside_total / cartesian_total, 8),
            "sampledResidualCases": len(sample["sampledCases"]),
            "fullyCoveredCases": len(sample["fullyCoveredCases"]),
        },
        "samplingDesign": {
            "allocation": f"{sample['rowsPerSampledCase']} fixed-hash rows per nonempty residual case",
            "populationWeighted": False,
            "formalPopulationEstimateProvided": False,
            "rankMeaning": "all rows are outside retained BGE K50; no deeper rank is available",
        },
        "overall": _summary(joined),
        "byCase": by_case,
        "fullyCoveredCases": [
            {
                "case": row["case"],
                "cartesianPairs": row["cartesianPairs"],
                "bgeK50Pairs": row["bgeK50Pairs"],
                "outsideBothPairs": row["outsideBothPairs"],
                "reason": row["reason"],
            }
            for row in sample["fullyCoveredCases"]
        ],
        "potentialObservedCases": potential_cases,
        "potentialObservedInEveryResidualCase": len(potential_cases) == len(by_case),
        "conclusions": {
            "existence": existence,
            "k50Boundary": k50_boundary,
            "deeperCutoff": "the sentinel has no ranks above K50 and cannot select a deeper rank cutoff",
            "populationInference": (
                "equal allocation across unequal populations and 15 rows per case do not support pool "
                "prevalence, K50 recall, or missed-relation totals"
            ),
        },
        "joinedRowsDigest": "sha256:" + hashlib.sha256(canonical_json(joined).encode()).hexdigest(),
        "joinedRows": joined,
    }
    report["analysisDigest"] = "sha256:" + hashlib.sha256(canonical_json(report).encode()).hexdigest()
    return report


def _verify_embedded_artifacts(sample: Mapping[str, Any]) -> None:
    for name in ("leanFloorPairs", "rankArtifact", "rankManifest"):
        receipt = sample["sourceArtifacts"][name]
        path = Path(str(receipt["path"]))
        if not path.is_file() or _sha256(path) != receipt["sha256"]:
            raise ValueError(f"embedded source artifact does not reopen: {name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--rendering", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary-only", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    decisions_text = args.decisions.read_text(encoding="utf-8")
    rendering_text = args.rendering.read_text(encoding="utf-8")
    decisions = base.parse_ordered_decisions(decisions_text, expected_rows=len(sample["rows"]))
    validate_rendering(rendering_text, sample["rows"])
    _verify_embedded_artifacts(sample)

    sample_sha = _sha256(args.sample)
    rendering_sha = _sha256(args.rendering)
    for expected in (sample_sha.removeprefix("sha256:"), sample["sampleDigest"], rendering_sha.removeprefix("sha256:")):
        if expected not in decisions_text:
            raise ValueError("decision record does not pin every sample/rendering receipt")

    report = analyze(
        sample,
        decisions,
        sample_file_sha256=sample_sha,
        decisions_file_sha256=_sha256(args.decisions),
        rendering_file_sha256=rendering_sha,
    )
    if args.summary_only:
        report.pop("joinedRows")
    serialized = canonical_json(report) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(
            canonical_json(
                {
                    "analysisDigest": report["analysisDigest"],
                    "output": str(args.output),
                    "outputSha256": _sha256(args.output),
                    "overall": report["overall"],
                }
            )
        )
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
