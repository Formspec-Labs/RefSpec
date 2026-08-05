"""Tests for the fixed-decision Atlas outside-BGE-K50 residual audit."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from refspec.storage import canonical_json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import analyze_atlas_residual_manual_audit as audit

SEED = "fixed-test-seed"
VIEWS = ("label", "structured")


def _concept(member: str, label: str) -> dict[str, object]:
    return {
        "member": member,
        "vocabulary": "Test vocabulary",
        "prefLabel": label,
        "altLabels": [],
        "definition": None,
        "scopeNote": None,
        "parents": [],
        "children": [],
        "bgeViewTexts": {view: f"{view}: {label}" for view in VIEWS},
    }


def _row(number: int, case: str) -> dict[str, object]:
    row = {
        "case": case,
        "population": audit.EXPECTED_POPULATION,
        "source": _concept(f"urn:source:{number}", f"Source {number}"),
        "target": _concept(f"urn:target:{number}", f"Target {number}"),
    }
    row["selectionDigest"] = audit._selection_digest(row, seed=SEED)
    return row


def _population(
    case: str,
    *,
    sources: int,
    targets: int,
    lean: int,
    bge: int,
    overlap: int,
    sampled: int,
) -> dict[str, object]:
    cartesian = sources * targets
    outside_bge = cartesian - bge
    lean_outside = lean - overlap
    result: dict[str, object] = {
        "case": case,
        "sourceConcepts": sources,
        "targetConcepts": targets,
        "cartesianPairs": cartesian,
        "leanFloorPairs": lean,
        "bgeK50Pairs": bge,
        "leanBgeK50Overlap": overlap,
        "outsideBgeK50Pairs": outside_bge,
        "leanOutsideBgeK50Pairs": lean_outside,
        "outsideBothPairs": outside_bge - lean_outside,
        "sampledRows": sampled,
    }
    if sampled:
        result["requestedRows"] = sampled
    else:
        result["reason"] = "fully covered in fixture"
    return result


def _sample() -> dict[str, object]:
    rows = []
    for case, start in (("case-a", 1), ("case-b", 3)):
        case_rows = sorted((_row(start, case), _row(start + 1, case)), key=lambda row: row["selectionDigest"])
        rows.extend(case_rows)
    sampled = [
        _population("case-a", sources=4, targets=5, lean=4, bge=6, overlap=2, sampled=2),
        _population("case-b", sources=5, targets=6, lean=3, bge=10, overlap=1, sampled=2),
    ]
    covered = [_population("case-c", sources=2, targets=2, lean=1, bge=4, overlap=1, sampled=0)]
    evidence = {"fullyCoveredCases": covered, "sampledCases": sampled}
    return {
        "type": "AtlasBlindCandidateResidualReviewSample",
        "schemaVersion": "1.0",
        "targetRows": 4,
        "rowsPerSampledCase": 2,
        "views": list(VIEWS),
        "selectionRule": {"algorithm": "SHA-256", "seed": SEED},
        "sampledCases": sampled,
        "fullyCoveredCases": covered,
        "populationEvidenceDigest": "sha256:" + hashlib.sha256(canonical_json(evidence).encode()).hexdigest(),
        "rows": rows,
        "sampleDigest": "sha256:" + hashlib.sha256(canonical_json(rows).encode()).hexdigest(),
    }


def test_analysis_reports_exact_observations_and_population_boundary() -> None:
    report = audit.analyze(
        _sample(),
        ("related", "unrelated", "target_is_narrower", "unrelated"),
        sample_file_sha256="sha256:sample",
        decisions_file_sha256="sha256:decisions",
        rendering_file_sha256="sha256:rendering",
    )

    assert report["overall"] == {
        "rows": 4,
        "potentialRelations": 2,
        "potentialYield": 0.5,
        "verdicts": {"related": 1, "target_is_narrower": 1, "unrelated": 2},
    }
    assert report["population"] == {
        "cartesianPairs": 54,
        "selectedByLeanOrBgeK50Pairs": 24,
        "outsideBothPairs": 30,
        "selectedShare": 0.44444444,
        "outsideBothShare": 0.55555556,
        "sampledResidualCases": 2,
        "fullyCoveredCases": 1,
    }
    assert [row["residualPopulation"] for row in report["byCase"]] == [12, 18]
    assert [row["potentialRelations"] for row in report["byCase"]] == [1, 1]
    assert report["potentialObservedInEveryResidualCase"] is True
    assert report["potentialObservedCases"] == ["case-a", "case-b"]
    assert report["samplingDesign"]["formalPopulationEstimateProvided"] is False
    assert report["analysisDigest"].startswith("sha256:")


def test_conclusion_names_only_cases_with_observed_direct_relations() -> None:
    report = audit.analyze(
        _sample(),
        ("related", "unrelated", "unrelated", "unrelated"),
        sample_file_sha256="sha256:sample",
        decisions_file_sha256="sha256:decisions",
        rendering_file_sha256="sha256:rendering",
    )

    assert report["potentialObservedCases"] == ["case-a"]
    assert report["potentialObservedInEveryResidualCase"] is False
    assert "1 of 2 residual cases: case-a" in report["conclusions"]["existence"]


def test_validation_rejects_population_drift_or_answer_metadata() -> None:
    sample = _sample()
    sample["sampledCases"][0]["outsideBothPairs"] += 1
    evidence = {"fullyCoveredCases": sample["fullyCoveredCases"], "sampledCases": sample["sampledCases"]}
    sample["populationEvidenceDigest"] = "sha256:"
    sample["populationEvidenceDigest"] += hashlib.sha256(canonical_json(evidence).encode()).hexdigest()
    with pytest.raises(ValueError, match="outside-both population mismatch"):
        audit.validate_sample(sample)

    sample = _sample()
    sample["rows"][0]["verdict"] = "related"
    sample["sampleDigest"] = "sha256:" + hashlib.sha256(canonical_json(sample["rows"]).encode()).hexdigest()
    with pytest.raises(ValueError, match="answer or rank metadata leaked"):
        audit.validate_sample(sample)


def test_validation_rejects_changed_selection_or_unbalanced_facts() -> None:
    sample = _sample()
    sample["rows"][0]["selectionDigest"] = "sha256:" + "0" * 64
    sample["sampleDigest"] = "sha256:" + hashlib.sha256(canonical_json(sample["rows"]).encode()).hexdigest()
    with pytest.raises(ValueError, match="selectionDigest mismatch"):
        audit.validate_sample(sample)

    sample = _sample()
    sample["rows"][0]["source"]["extra"] = "one-sided"
    sample["sampleDigest"] = "sha256:" + hashlib.sha256(canonical_json(sample["rows"]).encode()).hexdigest()
    with pytest.raises(ValueError, match="facts are unbalanced"):
        audit.validate_sample(sample)


def test_context_rendering_requires_ordered_rows_and_hides_selection_metadata() -> None:
    sample = _sample()
    rendering = "\n".join(
        [
            *(
                f"## Row {index} — {row['case']}\n### Source concept\n### Target concept"
                for index, row in enumerate(sample["rows"], 1)
            ),
            "",
        ]
    )
    audit.validate_rendering(rendering, sample["rows"])

    with pytest.raises(ValueError, match="selection metadata"):
        audit.validate_rendering(rendering + "selectionDigest", sample["rows"])
