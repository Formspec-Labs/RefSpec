"""Tests for the Atlas crosswalk admission-rule replay harness.

The harness exists to vary one rule and report the difference, so the tests that
matter are the ones proving it cannot silently vary something else:

* the baseline check **fails closed** when the reconstructed rule and the recorded
  admissions disagree -- that gate is the only thing standing between "we
  measured a lattice change" and "we measured a bug";
* control admissions are counted with the class exclusion *lifted*, because a
  rule that would let sibling distractors through is invisible if the exclusion
  is still masking them;
* ``related`` is off the granularity ladder, not a third point on it.

Fixtures are synthetic.  Binding to the real archive would couple these tests to
one release of the evidence and would never exercise the failure paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import replay_atlas_crosswalk_admission as replay

CROSSWALK = "fr-elsst"


def _row(
    row: int,
    *,
    set_name: str,
    cls: str,
    judges: tuple[str, str],
    verdict: str = "same",
    relation: str = "closeMatch",
) -> dict[str, Any]:
    """One synthetic candidate.  Only admitted rows carry ``admittedRelation``, as in the real sets."""
    return {
        "row": row,
        **({"admittedRelation": relation} if set_name == "positives" else {}),
        "crosswalk": CROSSWALK,
        "candidateId": f"urn:ref:candidate:{row:03d}",
        "generationClass": cls,
        "sourceLabel": f"source-{row}",
        "targetLabel": f"target-{row}",
        "sealedJudges": [
            {"group": "google-gemini", "outcome": "rejects" if judges[0] == "unrelated" else "supports", "verdictRelation": judges[0]},
            {"group": "openai", "outcome": "rejects" if judges[1] == "unrelated" else "supports", "verdictRelation": judges[1]},
        ],
        "independentVerdict": verdict,
        "independentDirectness": "direct_candidate",
        "set": set_name,
    }


#: A population small enough to reason about and shaped like the real one: an
#: admitted row, a genuinely rejected row, a disputed granularity row, a disputed
#: associative row, and a sibling distractor the judges both supported.
SPECS = (
    _row(1, set_name="positives", cls="normalizedLabelEquality", judges=("same", "near_same")),
    _row(2, set_name="hard-negatives", cls="editDistanceNearMiss", judges=("unrelated", "unrelated"), verdict="unrelated"),
    _row(3, set_name="disputed", cls="normalizedLabelEquality", judges=("same", "target_is_narrower")),
    _row(4, set_name="disputed", cls="substringNearMiss", judges=("related", "target_is_narrower"), verdict="related"),
    _row(5, set_name="controls", cls="siblingDistractor", judges=("related", "related"), verdict="related"),
)


@pytest.fixture
def benchmarks(tmp_path: Path) -> Path:
    directory = tmp_path / "benchmarks"
    directory.mkdir()
    for name in replay.SETS:
        rows = [dict(spec) for spec in SPECS if spec["set"] == name]
        for row in rows:
            row.pop("set")
        payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        (directory / f"{name}.jsonl").write_text(payload, encoding="utf-8")
    return directory


def test_load_reassembles_the_population_and_tags_each_row_with_its_set(benchmarks: Path) -> None:
    population = replay.load(benchmarks)
    assert len(population) == len(SPECS)
    assert {row["set"] for row in population.values()} == {"positives", "hard-negatives", "controls", "disputed"}


def test_load_rejects_a_row_appearing_in_two_sets(benchmarks: Path) -> None:
    duplicate = dict(SPECS[0])
    duplicate.pop("set")
    (benchmarks / "disputed.jsonl").write_text(json.dumps(duplicate, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="appears in both"):
        replay.load(benchmarks)


def test_baseline_reproduces_recorded_admissions_and_names_the_excluded_controls(benchmarks: Path) -> None:
    audit = replay.verify_baseline(replay.load(benchmarks))
    assert audit["recordedAdmissions"] == 1
    assert audit["mismatches"] == 0
    # The sibling distractor's judges agreed on ``related``, so the lattice alone
    # would have taken it.  Only the class exclusion keeps it out.
    assert audit["clearedLatticeButExcluded"] == 1
    assert audit["excludedByClass"] == {"siblingDistractor": 1}


def test_baseline_fails_closed_when_the_recorded_outcome_contradicts_the_rule(benchmarks: Path) -> None:
    """Move a row the lattice rejects into `positives` and the gate must fire."""
    rejected = dict(SPECS[1])
    rejected.pop("set")
    with (benchmarks / "positives.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(rejected, sort_keys=True) + "\n")
    (benchmarks / "hard-negatives.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not reproduce the recorded admissions"):
        replay.verify_baseline(replay.load(benchmarks))


def test_granularity_relaxation_recovers_the_label_equality_dispute_only(benchmarks: Path) -> None:
    results = {entry["rule"]: entry for entry in replay.replay(replay.load(benchmarks))}
    assert results["R0-v2-baseline"]["deltaVsBaseline"] == 0
    # Row 3 is same-versus-narrower on a label-equality candidate: one step.
    assert results["R1-granularity-label-equality"]["deltaVsBaseline"] == 1
    # Row 4 is related-versus-narrower on a substring candidate, which is not a
    # granularity shift and must survive every rule short of R3.
    assert results["R2-granularity-any-class"]["deltaVsBaseline"] == 1
    assert results["R4-granularity-principled-variants"]["deltaVsBaseline"] == 1
    assert results["R3-related-absorbs-direction"]["deltaVsBaseline"] == 2


def test_control_admissions_are_measured_with_the_class_exclusion_lifted(benchmarks: Path) -> None:
    results = {entry["rule"]: entry for entry in replay.replay(replay.load(benchmarks))}
    # The sibling distractor clears the baseline lattice, so it is counted at
    # baseline and no rule here should be blamed for it.
    assert results["R0-v2-baseline"]["controlsClearingLattice"] == 1
    assert all(entry["controlsAddedVsBaseline"] == 0 for entry in results.values())


def test_related_is_not_a_point_on_the_granularity_ladder() -> None:
    assert "related" not in replay.GRANULARITY
    assert not replay._one_step("related", "target_is_narrower")
    assert replay._one_step("same", "target_is_narrower")
    assert replay._one_step("near_same", "target_is_broader")
    # Broader against narrower is two steps: a contradiction, never compatible.
    assert not replay._one_step("target_is_broader", "target_is_narrower")


def test_only_r3_absorbs_an_associative_verdict_into_a_direction() -> None:
    row = _row(9, set_name="disputed", cls="normalizedLabelEquality", judges=("related", "target_is_narrower"))
    assert not replay._r2_granularity_any_class(row)
    assert not replay._r4_granularity_principled(row)
    assert replay._r3_related_absorbs_direction(row)
    contradiction = _row(10, set_name="disputed", cls="normalizedLabelEquality", judges=("target_is_broader", "target_is_narrower"))
    assert not replay._r3_related_absorbs_direction(contradiction)


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        ("SEXUAL BEHAVIOUR", "sexual behavior", "spellingVariant"),
        ("Child labor", "CHILD LABOUR", "spellingVariant"),
        ("Diseases", "disease", "numberVariant"),
        ("REFERENDUMS", "referendum", "numberVariant"),
        ("RÉGIME", "regime", "caseOrDiacriticOnly"),
        ("Fees", "FEET", "unprincipled"),
        ("Bonds", "BANKS", "unprincipled"),
        ("Medicaid", "Medicare", "unprincipled"),
    ],
)
def test_variant_class_separates_orthography_from_coincidence(source: str, target: str, expected: str) -> None:
    assert replay.variant_class(source, target) == expected


def test_r4_extends_the_collapse_to_principled_variants_only() -> None:
    principled = _row(11, set_name="disputed", cls="editDistanceNearMiss", judges=("same", "target_is_narrower"))
    principled["sourceLabel"], principled["targetLabel"] = "Child labor", "CHILD LABOUR"
    coincidence = _row(12, set_name="disputed", cls="editDistanceNearMiss", judges=("same", "target_is_narrower"))
    coincidence["sourceLabel"], coincidence["targetLabel"] = "Fees", "FEET"
    assert replay._r4_granularity_principled(principled)
    assert not replay._r4_granularity_principled(coincidence)
    # R1 reaches neither; R2 reaches both, which is why R4 exists.
    assert not replay._r1_granularity_label_equality(principled)
    assert replay._r2_granularity_any_class(coincidence)


def test_edit_distance_hygiene_scores_the_two_populations_separately(benchmarks: Path) -> None:
    rows = [dict(spec) for spec in SPECS]
    coincidence = dict(SPECS[1])  # the rejected editDistanceNearMiss row
    coincidence.pop("set")
    coincidence["sourceLabel"], coincidence["targetLabel"] = "Fees", "FEET"
    (benchmarks / "hard-negatives.jsonl").write_text(json.dumps(coincidence, sort_keys=True) + "\n", encoding="utf-8")
    hygiene = replay.edit_distance_hygiene(replay.load(benchmarks))
    assert hygiene["generated"] == 1
    assert hygiene["byVariantClass"]["unprincipled"]["admitted"] == 0
    assert hygiene["byVariantClass"]["unprincipled"]["admissionRate"] == pytest.approx(0.0)
    assert hygiene["byVariantClass"]["unprincipled"]["relatedMatchShareOfAdmissions"] is None
    assert rows  # the fixture population is unchanged on disk for other tests


def test_relation_share_reports_lift_against_the_overall_base_rate(benchmarks: Path) -> None:
    share = replay.relation_share(replay.load(benchmarks))
    assert share["admissions"] == 1
    assert share["byGenerationClass"]["normalizedLabelEquality"]["admissions"] == 1


def test_admission_does_not_depend_on_the_order_rows_are_considered(benchmarks: Path) -> None:
    order = replay.order_independence(replay.load(benchmarks), replay.RULES[-1])
    assert order["orderIndependent"] is True
    assert order["distinctAdmittedSets"] == 1


def test_calibration_reports_judge_and_reviewer_rates_on_the_same_rows(benchmarks: Path) -> None:
    cal = replay.calibration(replay.load(benchmarks))
    sibling = cal["controlSupportRates"]["siblingDistractor"]
    assert sibling["rows"] == 1
    assert sibling["google-gemini"]["rate"] == pytest.approx(1.0)
    assert sibling["openai"]["rate"] == pytest.approx(1.0)
    assert sibling["independentReviewer"]["rate"] == pytest.approx(1.0)
    assert sibling["judgeRelationsWhenSupporting"] == {"related": 2}


def test_disputed_rows_are_profiled_and_never_resolved(benchmarks: Path) -> None:
    population = replay.load(benchmarks)
    profile = replay.disputed_profile(population)
    assert profile["rows"] == 2
    assert profile["verdictPairs"] == {"related vs target_is_narrower": 1, "same vs target_is_narrower": 1}
    # No rule assigns a relation to a disputed row anywhere in the payload.
    assert all("resolvedRelation" not in row for row in population.values())
