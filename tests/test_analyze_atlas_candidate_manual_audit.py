"""Tests for the fixed-decision Atlas candidate audit join."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from refspec.storage import canonical_json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import analyze_atlas_candidate_manual_audit as audit


def _row(
    row: int,
    *,
    category: str,
    rank: int,
    band: str,
    lexical: bool,
    sparse: bool,
) -> dict[str, object]:
    case = "case-a" if row <= 2 else "case-b"
    source = {"member": f"urn:source:{row}", "prefLabel": f"Source {row}"}
    target = {"member": f"urn:target:{row}", "prefLabel": f"Target {row}"}
    line = f"{case}\t{source['member']}\t{target['member']}\n".encode()
    bge = rank <= 20
    return {
        "case": case,
        "sampleCategory": category,
        "rankBand": band,
        "bgeRank": rank,
        "selectionDigest": "sha256:" + hashlib.sha256(line).hexdigest(),
        "membershipAtReviewDepths": {
            "lexicalK3": lexical,
            "sparseGraphK1": sparse,
            "bgeK20": bge,
            "bgeRetainedK50": True,
            "leanTwoFamilyFloor": lexical or sparse,
            "allThree": lexical and sparse and bge,
        },
        "source": source,
        "target": target,
    }


def _sample() -> dict[str, object]:
    rows = [
        _row(1, category="bge-only", rank=1, band="rank-1", lexical=False, sparse=False),
        _row(2, category="three-family-overlap", rank=3, band="ranks-2-3", lexical=True, sparse=True),
        _row(3, category="just-outside-bge20", rank=21, band="ranks-21-25", lexical=False, sparse=False),
    ]
    return {
        "targetRows": 3,
        "reviewCutoff": 20,
        "retainedMaximumRank": 50,
        "strata": [
            {"rankBand": "rank-1", "minimumRank": 1, "maximumRank": 1},
            {"rankBand": "ranks-2-3", "minimumRank": 2, "maximumRank": 3},
            {"rankBand": "ranks-21-25", "minimumRank": 21, "maximumRank": 25},
        ],
        "rows": rows,
        "sampleDigest": "sha256:" + hashlib.sha256(canonical_json(rows).encode()).hexdigest(),
    }


def test_parse_ordered_decisions_restores_row_order_from_wide_table() -> None:
    markdown = """
| Row | Decision | Row | Decision | Row | Decision |
| ---: | --- | ---: | --- | ---: | --- |
| 1 | `related` | 3 | `unrelated` | 2 | `target_is_broader` |
"""

    assert audit.parse_ordered_decisions(markdown, expected_rows=3) == (
        "related",
        "target_is_broader",
        "unrelated",
    )


def test_analyze_joins_fixed_decisions_and_summarizes_each_requested_dimension() -> None:
    report = audit.analyze(
        _sample(),
        ("related", "unrelated", "target_is_narrower"),
        sample_file_sha256="sha256:sample",
        decisions_file_sha256="sha256:decisions",
    )

    assert report["overall"] == {
        "rows": 3,
        "potentialRelations": 2,
        "potentialYield": 0.66666667,
        "verdicts": {"related": 1, "target_is_narrower": 1, "unrelated": 1},
    }
    assert [row["potentialRelations"] for row in report["byCase"]] == [1, 1]
    assert [row["potentialRelations"] for row in report["bySampleCategory"]] == [1, 0, 1]
    assert [row["potentialRelations"] for row in report["byCutoffRegion"]] == [1, 1]
    assert [row["group"] for row in report["bgeOnlyVsThreeFamilyOverlap"]] == [
        "bge-only",
        "three-family-overlap",
    ]
    assert report["joinedRows"][2]["bgeRank"] == 21
    assert report["joinedRows"][2]["verdict"] == "target_is_narrower"
    assert report["joinedRowsDigest"].startswith("sha256:")
    assert report["analysisDigest"].startswith("sha256:")


def test_validation_rejects_changed_sample_or_missing_decision() -> None:
    sample = _sample()
    sample["rows"][0]["bgeRank"] = 2
    with pytest.raises(ValueError, match="sampleDigest"):
        audit.validate_sample(sample)

    with pytest.raises(ValueError, match=r"missing=\[3\]"):
        audit.parse_ordered_decisions("| 1 | `related` | 2 | `unrelated` |", expected_rows=3)
