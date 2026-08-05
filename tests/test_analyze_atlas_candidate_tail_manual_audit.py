"""Tests for the fixed-decision Atlas BGE-tail audit join."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from refspec.storage import canonical_json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import analyze_atlas_candidate_tail_manual_audit as audit


def _row(number: int, *, case: str, band: str, rank: int) -> dict[str, object]:
    source = {
        "member": f"urn:source:{number}",
        "prefLabel": f"Source {number}",
        "bgeViewTexts": {view: f"source {view} {number}" for view in ("label", "structured")},
    }
    target = {
        "member": f"urn:target:{number}",
        "prefLabel": f"Target {number}",
        "bgeViewTexts": {view: f"target {view} {number}" for view in ("label", "structured")},
    }
    line = f"{case}\t{source['member']}\t{target['member']}\n".encode()
    return {
        "case": case,
        "sampleCategory": "bge-only-tail",
        "rankBand": band,
        "bgeRank": rank,
        "selectionDigest": "sha256:" + hashlib.sha256(line).hexdigest(),
        "membershipAtReviewDepths": {
            "bgeK20": False,
            "bgeRetainedK50": True,
            "leanTwoFamilyFloor": False,
        },
        "source": source,
        "target": target,
    }


def _sample() -> dict[str, object]:
    rows = [
        _row(1, case="case-a", band="ranks-26-30", rank=27),
        _row(2, case="case-a", band="ranks-31-35", rank=33),
        _row(3, case="case-b", band="ranks-26-30", rank=29),
        _row(4, case="case-b", band="ranks-31-35", rank=35),
    ]
    strata = [
        {
            "case": case,
            "rankBand": band,
            "minimumRank": minimum,
            "maximumRank": maximum,
            "eligibleBgeOnlyPopulation": 10,
            "requestedRows": 1,
            "sampledRows": 1,
        }
        for case in ("case-a", "case-b")
        for band, minimum, maximum in (("ranks-26-30", 26, 30), ("ranks-31-35", 31, 35))
    ]
    return {
        "targetRows": 4,
        "views": ["label", "structured"],
        "strata": strata,
        "rows": rows,
        "sampleDigest": "sha256:" + hashlib.sha256(canonical_json(rows).encode()).hexdigest(),
    }


def test_tail_analysis_reports_pair_band_and_cutoff_coverage() -> None:
    report = audit.analyze(
        _sample(),
        ("related", "unrelated", "target_is_narrower", "related"),
        sample_file_sha256="sha256:sample",
        decisions_file_sha256="sha256:decisions",
        rendering_file_sha256="sha256:rendering",
    )

    assert report["overall"] == {
        "rows": 4,
        "potentialRelations": 3,
        "potentialYield": 0.75,
        "verdicts": {"related": 2, "target_is_narrower": 1, "unrelated": 1},
    }
    assert [row["potentialRelations"] for row in report["byCase"]] == [1, 2]
    assert [row["potentialRelations"] for row in report["byActualRankBand"]] == [2, 1]
    assert report["tailCumulativeCoverage"][0]["potentialRelationsIncluded"] == 0
    assert report["tailCumulativeCoverage"][1]["potentialRelationsIncluded"] == 2
    assert report["tailCumulativeCoverage"][-1]["potentialCoverage"] == 1.0
    assert report["analysisDigest"].startswith("sha256:")


def test_combined_coverage_separates_bge_unique_rows_from_lean_overlap() -> None:
    prefix_rows = [
        {
            "bgeRank": 20,
            "potentialRelation": True,
            "membershipAtReviewDepths": {"leanTwoFamilyFloor": False},
        },
        {
            "bgeRank": 20,
            "potentialRelation": True,
            "membershipAtReviewDepths": {"leanTwoFamilyFloor": True},
        },
    ]
    prefix = {
        "type": "AtlasCandidateManualAuditAnalysis",
        "joinedRows": prefix_rows,
        "joinedRowsDigest": "sha256:" + hashlib.sha256(canonical_json(prefix_rows).encode()).hexdigest(),
    }
    prefix["analysisDigest"] = "sha256:" + hashlib.sha256(canonical_json(prefix).encode()).hexdigest()

    report = audit.analyze(
        _sample(),
        ("related", "unrelated", "target_is_narrower", "related"),
        sample_file_sha256="sha256:sample",
        decisions_file_sha256="sha256:decisions",
        rendering_file_sha256="sha256:rendering",
        prefix_analysis=prefix,
        prefix_analysis_file_sha256="sha256:prefix",
    )

    assert report["combinedReviewedPotentialRelations"] == 5
    assert report["bgeUniqueReviewedPotentialRelations"] == 4
    assert report["bgeUniqueCumulativeCoverage"][0]["potentialRelationsIncluded"] == 1
    assert report["bgeUniqueCumulativeCoverage"][-1]["potentialCoverage"] == 1.0


def test_tail_validation_rejects_changed_rank_or_membership() -> None:
    sample = _sample()
    sample["rows"][0]["bgeRank"] = 31
    sample["sampleDigest"] = "sha256:" + hashlib.sha256(canonical_json(sample["rows"]).encode()).hexdigest()
    with pytest.raises(ValueError, match="rank-band mismatch"):
        audit.validate_tail_sample(sample)

    sample = _sample()
    sample["rows"][0]["membershipAtReviewDepths"]["leanTwoFamilyFloor"] = True
    sample["sampleDigest"] = "sha256:" + hashlib.sha256(canonical_json(sample["rows"]).encode()).hexdigest()
    with pytest.raises(ValueError, match="retrieval membership"):
        audit.validate_tail_sample(sample)


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
