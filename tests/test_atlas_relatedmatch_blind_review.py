"""Tests for the `relatedMatch` blind-review sample builder and its comparison.

The builder's whole job is to withhold an answer, so the tests that carry weight
are the ones proving it does: that no field the key holds ever reaches the blind
file, that presentation order carries no signal about which stratum a row is in,
and that the sample is a census of the population under test rather than a sample
of it.

The comparison's job is to join once, in one direction.  Its tests check that a
missing pass is reported rather than silently skipped, and that the discriminating
figure -- the orthographic gap between ``relatedMatch`` admissions and the matched
admissions beside them -- is computed against the right denominator.

Fixtures are synthetic.  Binding to the real archive would couple these tests to
one release of the evidence and would never exercise the failure paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import build_atlas_relatedmatch_blind_review as builder
from tools import compare_atlas_relatedmatch_blind_review as comparer

CROSSWALK = "fr-elsst"


def _benchmark_row(row: int, *, set_name: str, cls: str, relation: str | None) -> dict[str, Any]:
    return {
        "row": row,
        "crosswalk": CROSSWALK,
        "candidateId": f"urn:ref:candidate:{row:03d}",
        "generationClass": cls,
        "sourceLabel": f"source-{row}",
        "targetLabel": f"target-{row}",
        "sealedJudges": [
            {"group": "google-gemini", "outcome": "supports", "verdictRelation": "related"},
            {"group": "openai", "outcome": "supports", "verdictRelation": "related"},
        ],
        "independentVerdict": "related",
        "independentDirectness": "direct_candidate",
        **({"admittedRelation": relation} if relation else {}),
        **({"controlKind": cls} if set_name == "controls" else {}),
    }


#: Two relatedMatch admissions, two other admissions in the same classes, and one
#: control of each kind -- the real sample's shape in miniature.
BENCHMARK_ROWS = {
    "positives": [
        _benchmark_row(1, set_name="positives", cls="editDistanceNearMiss", relation="relatedMatch"),
        _benchmark_row(2, set_name="positives", cls="substringNearMiss", relation="relatedMatch"),
        _benchmark_row(3, set_name="positives", cls="editDistanceNearMiss", relation="closeMatch"),
        _benchmark_row(4, set_name="positives", cls="substringNearMiss", relation="narrowMatch"),
        _benchmark_row(5, set_name="positives", cls="normalizedLabelEquality", relation="exactMatch"),
    ],
    "hard-negatives": [_benchmark_row(6, set_name="hard-negatives", cls="editDistanceNearMiss", relation=None)],
    "controls": [
        _benchmark_row(7, set_name="controls", cls="randomNegativeControl", relation=None),
        _benchmark_row(8, set_name="controls", cls="siblingDistractor", relation=None),
    ],
    "disputed": [_benchmark_row(9, set_name="disputed", cls="alternateLabelEquality", relation=None)],
}

#: Task ids are deliberately out of row order, so a builder that sorted by row
#: instead of by task id would fail the ordering test below.
TASK_IDS = {1: "task-e", 2: "task-a", 3: "task-h", 4: "task-c", 5: "task-b", 6: "task-g", 7: "task-d", 8: "task-i", 9: "task-f"}


@pytest.fixture
def sources(tmp_path: Path) -> tuple[Path, Path]:
    benchmarks = tmp_path / "benchmarks"
    benchmarks.mkdir()
    for name, rows in BENCHMARK_ROWS.items():
        benchmarks.joinpath(f"{name}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
        )

    review = tmp_path / "review"
    (review / "blind").mkdir(parents=True)
    facts = [
        {
            "row": row["row"],
            "taskId": TASK_IDS[row["row"]],
            "source": {"prefLabel": row["sourceLabel"], "vocabulary": "ELSST R6", "member": "urn:src", "release": "r"},
            "target": {"prefLabel": row["targetLabel"], "vocabulary": "ICPSR", "member": "urn:tgt", "release": "r"},
        }
        for rows in BENCHMARK_ROWS.values()
        for row in rows
    ]
    (review / "blind" / f"{CROSSWALK}.json").write_text(json.dumps({"crosswalk": CROSSWALK, "rows": facts}), encoding="utf-8")
    for other in ("fr-icpsr", "elsst-icpsr"):
        (review / "blind" / f"{other}.json").write_text(json.dumps({"crosswalk": other, "rows": []}), encoding="utf-8")
    return benchmarks, review


def _build(sources: tuple[Path, Path], output: Path) -> tuple[list[dict], list[dict]]:
    benchmarks, review = sources
    population = builder.load_population(benchmarks, review)
    keys = builder.select(population, distractors_per_class=1, controls=2)
    blind, sealed = builder.build(population, keys)
    output.mkdir(parents=True, exist_ok=True)
    return blind, sealed


def test_every_related_match_admission_is_present(sources: tuple[Path, Path], tmp_path: Path) -> None:
    _blind, sealed = _build(sources, tmp_path / "out")
    related = [row for row in sealed if row["admittedRelation"] == "relatedMatch"]
    assert len(related) == 2, "the sample must be a census of relatedMatch, not a sample of it"


def test_distractors_are_drawn_from_the_same_generation_classes(sources: tuple[Path, Path], tmp_path: Path) -> None:
    _blind, sealed = _build(sources, tmp_path / "out")
    related_classes = {row["generationClass"] for row in sealed if row["admittedRelation"] == "relatedMatch"}
    other_classes = {row["generationClass"] for row in sealed if row["set"] == "positives" and row["admittedRelation"] != "relatedMatch"}
    # A class that contributes a relatedMatch must also contribute a distractor,
    # or the mix itself leaks which rows are under test.
    assert related_classes <= other_classes


def test_controls_ride_along_unlabelled(sources: tuple[Path, Path], tmp_path: Path) -> None:
    _blind, sealed = _build(sources, tmp_path / "out")
    kinds = {row["generationClass"] for row in sealed if row["set"] == "controls"}
    assert kinds == {"randomNegativeControl", "siblingDistractor"}


def test_blind_rows_carry_concept_facts_and_nothing_else(sources: tuple[Path, Path], tmp_path: Path) -> None:
    blind, _sealed = _build(sources, tmp_path / "out")
    leaked = {"admittedRelation", "generationClass", "set", "sealedJudges", "priorIndependentVerdict", "candidateId", "crosswalk"}
    for row in blind:
        assert set(row) == {"row", "source", "target"}
        assert not leaked & set(json.dumps(row).split('"'))
        for side in ("source", "target"):
            # `member` and `release` identify the vocabulary release and are withheld
            # with everything else; only the fields a judge reasons from survive.
            assert set(row[side]) <= set(builder.CONCEPT_FIELDS)


def test_presentation_order_follows_task_id_not_stratum(sources: tuple[Path, Path], tmp_path: Path) -> None:
    benchmarks, review = sources
    population = builder.load_population(benchmarks, review)
    keys = builder.select(population, distractors_per_class=1, controls=2)
    ordered = [TASK_IDS[key[1]] for key in keys]
    assert ordered == sorted(ordered)
    # ...and the strata are genuinely interleaved rather than blocked.
    strata = [population[key]["set"] for key in keys]
    assert len(set(strata)) > 1
    assert strata != sorted(strata)


def test_build_is_deterministic(sources: tuple[Path, Path], tmp_path: Path) -> None:
    first = _build(sources, tmp_path / "a")
    second = _build(sources, tmp_path / "b")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_missing_concept_facts_fail_closed(sources: tuple[Path, Path]) -> None:
    benchmarks, review = sources
    (review / "blind" / f"{CROSSWALK}.json").write_text(json.dumps({"crosswalk": CROSSWALK, "rows": []}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="no concept facts"):
        builder.load_population(benchmarks, review)


# --------------------------------------------------------------------------- #
# comparison
# --------------------------------------------------------------------------- #


def _verdict(row: int, *, basis: str, relation: str = "related") -> str:
    return json.dumps(
        {
            "row": row,
            "relationExists": relation != "unrelated",
            "bestRelation": relation,
            "basisOfAssociation": basis,
            "confidence": "high",
            "why": "reason",
        },
        sort_keys=True,
    )


@pytest.fixture
def review_dir(sources: tuple[Path, Path], tmp_path: Path) -> Path:
    directory = tmp_path / "relatedmatch"
    (directory / "sealed-key").mkdir(parents=True)
    (directory / "independent").mkdir(parents=True)
    benchmarks, review = sources
    population = builder.load_population(benchmarks, review)
    keys = builder.select(population, distractors_per_class=1, controls=2)
    _blind, sealed = builder.build(population, keys)
    (directory / "sealed-key" / "sample.json").write_text(json.dumps({"rows": sealed}), encoding="utf-8")
    return directory


def _related_rows(directory: Path) -> list[int]:
    sealed = json.loads((directory / "sealed-key" / "sample.json").read_text(encoding="utf-8"))["rows"]
    return [row["row"] for row in sealed if row["admittedRelation"] == "relatedMatch"]


def test_orthographic_gap_contrasts_related_against_matched_admissions(review_dir: Path) -> None:
    sealed = json.loads((review_dir / "sealed-key" / "sample.json").read_text(encoding="utf-8"))["rows"]
    related = set(_related_rows(review_dir))
    lines = [_verdict(row["row"], basis="orthographic" if row["row"] in related else "conceptual") for row in sealed]
    (review_dir / "independent" / "neutral.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    key, passes, _variants = comparer.load(review_dir, None)
    entry = comparer.analyse(key, passes["neutral"], {})
    assert entry["rowsMissing"] == 0
    assert entry["byStratum"]["relatedMatchAdmission"]["orthographicRate"] == pytest.approx(1.0)
    assert entry["byStratum"]["otherAdmission"]["orthographicRate"] == pytest.approx(0.0)
    assert entry["orthographicGapRelatedVsOther"] == pytest.approx(1.0)


def test_rows_a_pass_skipped_are_reported_not_ignored(review_dir: Path) -> None:
    sealed = json.loads((review_dir / "sealed-key" / "sample.json").read_text(encoding="utf-8"))["rows"]
    lines = [_verdict(row["row"], basis="conceptual") for row in sealed[:-2]]
    (review_dir / "independent" / "neutral.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    key, passes, _variants = comparer.load(review_dir, None)
    assert comparer.analyse(key, passes["neutral"], {})["rowsMissing"] == 2


def test_framing_sensitivity_needs_two_passes(review_dir: Path) -> None:
    sealed = json.loads((review_dir / "sealed-key" / "sample.json").read_text(encoding="utf-8"))["rows"]
    (review_dir / "independent" / "neutral.jsonl").write_text(
        "\n".join(_verdict(row["row"], basis="conceptual") for row in sealed) + "\n", encoding="utf-8"
    )
    key, passes, _variants = comparer.load(review_dir, None)
    assert comparer.agreement(key, passes) is None

    flipped = {sealed[0]["row"]}
    (review_dir / "independent" / "adversarial.jsonl").write_text(
        "\n".join(
            _verdict(row["row"], basis="orthographic" if row["row"] in flipped else "conceptual") for row in sealed
        )
        + "\n",
        encoding="utf-8",
    )
    key, passes, _variants = comparer.load(review_dir, None)
    concord = comparer.agreement(key, passes)
    assert concord is not None
    assert concord["basisFlips"] == 1
    assert concord["agreementRate"]["bestRelation"] == pytest.approx(1.0)
    assert concord["agreementRate"]["basisOfAssociation"] < 1.0


def test_variant_classes_join_by_source_row(review_dir: Path) -> None:
    sealed = json.loads((review_dir / "sealed-key" / "sample.json").read_text(encoding="utf-8"))["rows"]
    (review_dir / "independent" / "neutral.jsonl").write_text(
        "\n".join(_verdict(row["row"], basis="orthographic") for row in sealed) + "\n", encoding="utf-8"
    )
    variants = {(row["crosswalk"], row["sourceRow"]): "unprincipled" for row in sealed if row["generationClass"] == "editDistanceNearMiss"}
    key, passes, _unused = comparer.load(review_dir, None)
    entry = comparer.analyse(key, passes["neutral"], variants)
    assert entry["byVariantClass"]["unprincipled"]["rows"] == len(variants)
    assert entry["byVariantClass"]["unprincipled"]["orthographic"] == len(variants)
