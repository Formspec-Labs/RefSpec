"""Tests for the variant-classifier blind audit and its comparison.

The audit exists to catch one specific failure — the classifier promoting a
coincidence to a real orthographic variant, which R4 would then admit into a
graph the product traverses.  So the tests that carry weight are the ones proving
the two error directions stay separated and that the blind file leaks nothing.

Pooling the two error types into one accuracy figure would hide the only number
that matters, and a test that only checked "accuracy is computed" would not
notice.  Hence a test per direction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import build_atlas_variant_classifier_audit as builder
from tools import compare_atlas_variant_classifier_audit as comparer

CROSSWALK = "fr-elsst"

#: Two real variants and two coincidences, ordered so that label sort interleaves
#: them rather than blocking the classes together.
PAIRS = [
    (1, "Diseases", "disease", "numberVariant"),
    (2, "Bonds", "BANKS", "unprincipled"),
    (3, "LABOUR DISPUTES", "labor disputes", "spellingVariant"),
    (4, "Fees", "FEET", "unprincipled"),
]


@pytest.fixture
def sources(tmp_path: Path) -> tuple[Path, Path]:
    benchmarks = tmp_path / "benchmarks"
    benchmarks.mkdir()
    rows = [
        {
            "row": row,
            "crosswalk": CROSSWALK,
            "candidateId": f"urn:ref:candidate:{row:03d}",
            "generationClass": "editDistanceNearMiss",
            "sourceLabel": a,
            "targetLabel": b,
            "sealedJudges": [
                {"group": "google-gemini", "outcome": "supports", "verdictRelation": "same"},
                {"group": "openai", "outcome": "supports", "verdictRelation": "same"},
            ],
            "independentVerdict": "same",
            "independentDirectness": "direct_candidate",
        }
        for row, a, b, _ in PAIRS
    ]
    # One non-edit-distance row that must never reach the audit.
    other = dict(rows[0], row=99, generationClass="normalizedLabelEquality", sourceLabel="X", targetLabel="x")
    benchmarks.joinpath("positives.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in [*rows, other]), encoding="utf-8"
    )
    for name in ("hard-negatives", "controls", "disputed"):
        benchmarks.joinpath(f"{name}.jsonl").write_text("", encoding="utf-8")

    replay = tmp_path / "replay.json"
    replay.write_text(
        json.dumps(
            {
                "editDistanceHygiene": {
                    "rows": [{"crosswalk": CROSSWALK, "row": row, "variantClass": cls} for row, _, _, cls in PAIRS]
                }
            }
        ),
        encoding="utf-8",
    )
    return benchmarks, replay


def test_audit_covers_every_edit_distance_pair_and_nothing_else(sources: tuple[Path, Path]) -> None:
    rows = builder.collect(*sources)
    assert len(rows) == len(PAIRS)
    assert {row["sourceLabel"] for row in rows} == {a for _, a, _, _ in PAIRS}


def test_blind_rows_carry_only_the_two_labels(sources: tuple[Path, Path], tmp_path: Path) -> None:
    rows = builder.collect(*sources)
    blind = [{"row": i, "a": r["sourceLabel"], "b": r["targetLabel"]} for i, r in enumerate(rows, start=1)]
    for row in blind:
        assert set(row) == {"row", "a", "b"}
    serialised = json.dumps(blind)
    for leaked in ("variantClass", "numberVariant", "spellingVariant", "unprincipled", "generationClass"):
        assert leaked not in serialised


def test_presentation_order_is_by_label_not_by_class(sources: tuple[Path, Path]) -> None:
    rows = builder.collect(*sources)
    ordered = [(r["sourceLabel"].lower(), r["targetLabel"].lower()) for r in rows]
    assert ordered == sorted(ordered)
    classes = [r["variantClass"] for r in rows]
    assert classes != sorted(classes), "sorted-by-class order would let a reviewer read the strata off the file"


def test_a_missing_classifier_verdict_fails_closed(sources: tuple[Path, Path], tmp_path: Path) -> None:
    benchmarks, replay = sources
    replay.write_text(json.dumps({"editDistanceHygiene": {"rows": []}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="no classifier verdict"):
        builder.collect(benchmarks, replay)


def _audit_dir(tmp_path: Path, sources: tuple[Path, Path], verdicts: dict[int, str]) -> Path:
    rows = builder.collect(*sources)
    directory = tmp_path / "audit"
    for part in ("blind", "sealed-key", "independent"):
        (directory / part).mkdir(parents=True, exist_ok=True)
    blind = [{"row": i, "a": r["sourceLabel"], "b": r["targetLabel"]} for i, r in enumerate(rows, start=1)]
    key: list[dict[str, Any]] = [
        {"row": i, "crosswalk": r["crosswalk"], "sourceRow": r["sourceRow"], "variantClass": r["variantClass"], "set": r["set"]}
        for i, r in enumerate(rows, start=1)
    ]
    (directory / "blind" / "pairs.json").write_text(json.dumps({"rows": blind}), encoding="utf-8")
    (directory / "sealed-key" / "pairs.json").write_text(json.dumps({"rows": key}), encoding="utf-8")
    (directory / "independent" / "linguistic.jsonl").write_text(
        "".join(
            json.dumps({"row": i, "variantClass": verdicts[i], "confidence": "high", "why": "reason"}) + "\n"
            for i in range(1, len(rows) + 1)
        ),
        encoding="utf-8",
    )
    return directory


def test_perfect_agreement_reports_no_errors_in_either_direction(sources: tuple[Path, Path], tmp_path: Path) -> None:
    rows = builder.collect(*sources)
    directory = _audit_dir(tmp_path, sources, {i: r["variantClass"] for i, r in enumerate(rows, start=1)})
    result = comparer.analyse(*comparer.load(directory, "linguistic"))
    assert result["exactAgreement"] == pytest.approx(1.0)
    assert result["falsePrincipled"] == []
    assert result["falseUnprincipled"] == []
    assert result["precisionOnPrincipled"] == pytest.approx(1.0)


def test_a_promoted_coincidence_is_reported_as_false_principled(sources: tuple[Path, Path], tmp_path: Path) -> None:
    """The dangerous direction: classifier says variant, reviewer says two words."""
    rows = builder.collect(*sources)
    verdicts = {i: r["variantClass"] for i, r in enumerate(rows, start=1)}
    promoted = next(i for i, r in enumerate(rows, start=1) if r["variantClass"] != "unprincipled")
    verdicts[promoted] = "unprincipled"
    result = comparer.analyse(*comparer.load(_audit_dir(tmp_path, sources, verdicts), "linguistic"))
    assert len(result["falsePrincipled"]) == 1
    assert result["falseUnprincipled"] == []
    assert result["precisionOnPrincipled"] < 1.0


def test_a_demoted_variant_is_reported_as_false_unprincipled_and_leaves_precision_alone(
    sources: tuple[Path, Path], tmp_path: Path
) -> None:
    """The wasteful direction must not be charged against precision."""
    rows = builder.collect(*sources)
    verdicts = {i: r["variantClass"] for i, r in enumerate(rows, start=1)}
    demoted = next(i for i, r in enumerate(rows, start=1) if r["variantClass"] == "unprincipled")
    verdicts[demoted] = "numberVariant"
    result = comparer.analyse(*comparer.load(_audit_dir(tmp_path, sources, verdicts), "linguistic"))
    assert result["falsePrincipled"] == []
    assert len(result["falseUnprincipled"]) == 1
    assert result["precisionOnPrincipled"] == pytest.approx(1.0)


def test_the_reviewers_diacritic_label_is_not_counted_as_a_disagreement(sources: tuple[Path, Path], tmp_path: Path) -> None:
    assert comparer._normalise("diacriticOrCaseOnly") == "caseOrDiacriticOnly"
    assert comparer._normalise("numberVariant") == "numberVariant"
