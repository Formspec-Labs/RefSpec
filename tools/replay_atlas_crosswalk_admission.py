"""Replay the cross-vocabulary admission rule and profile the generator that fed it.

This runs E-V1, E-V2 (calibration half), E-V4, E-V5 and E-V7 from
``research/vocabulary-atlas-native-relation-experiment-designs-2026-08-06.md``.
They share one property, which is why they share a tool: every one is answerable
by replaying recorded verdicts under an alternative rule.  Nothing is judged
again and no provider is called.

Note what the population is.  These 1,095 rows are *proposed* cross-vocabulary
pairs -- no source publishes a mapping to another vocabulary, so none of this is
a publisher assertion.  A label-oriented string matcher generated the candidates
and two model families judged the proposals.  The separate 16,449-row
native-relation test sets, which *are* publisher assertions, are not involved
here.  Source hierarchy enters at exactly one point: the ``siblingDistractor``
controls were seeded by ``target-sibling-of-label-equal-match``, swapping a true
target for one of its siblings under the target vocabulary's own ``broader``
links.  That makes them plausible pairs, not clean negatives -- see E-V2.

**E-V1** asks whether relaxing the relation lattice for label-equality candidates
recovers the 86 rows rejected while *both* judges supported a relation.  Those
rows died on which relation, not on whether one exists.

**E-V2** asks whether the reviewer that confirmed them is trustworthy.  The
companion documents answered "no", on the grounds that it rejected only
68.9-85.6% of controls against a sealed-judge baseline of 100%.  That baseline is
wrong, and this tool is what shows it: reconstructing the rule from the recorded
outcome proves admission applied a *control-class exclusion* before the lattice
ever ran, so 69 controls cleared the lattice on judge verdicts and none was
admitted.  Measured directly, the judges name a relation on 55.6% and 57.0% of
sibling distractors; the reviewer names one on 48.1%.

**E-V4** asks whether ``relatedMatch`` is a sink.  Measured as the SKOS relation
each admission was granted, per generation class.

**E-V5** asks whether edit distance is worth keeping.  Each ``editDistanceNearMiss``
candidate is classified as a principled variant -- number agreement, diacritic
folding, a known US/UK spelling -- or as an unprincipled coincidence, and the two
populations are scored separately.  The split is stark enough to become a rule.

**E-V7** asks whether admission is order-dependent.  It is not, and the reason
matters more than the result: the rule carries no cross-row state at all.

The reconstructed rule is checked against the recorded 582 admissions before any
variant runs.  A single mismatch aborts: a replay harness that cannot reproduce
the decision it is varying cannot say anything about the variation.

Read-only.  In particular the 86 disputed rows are scored, never resolved --
assigning them types would destroy the only adjudication benchmark in the
archive, which is the whole reason they were left unresolved.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import random
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SETS = ("positives", "hard-negatives", "controls", "disputed")

#: Generation classes that are seeded negatives rather than proposed mappings.
CONTROL_CLASSES = frozenset({"siblingDistractor", "randomNegativeControl"})

#: Classes where both labels normalise to the same string, exactly or via an alias.
LABEL_EQUALITY_CLASSES = frozenset({"normalizedLabelEquality", "alternateLabelEquality"})

#: Verdicts asserting that some relation holds.
SUPPORT = frozenset({"same", "near_same", "target_is_broader", "target_is_narrower", "related"})

#: Granularity ladder.  Equivalence sits at 0; a directional verdict is one step
#: off it; broader and narrower are two steps apart and contradict each other.
#: ``related`` is deliberately absent -- it is off the scale, not a third point on it.
GRANULARITY = {"target_is_broader": -1, "same": 0, "near_same": 0, "target_is_narrower": 1}

#: Orthographic rewrites that distinguish otherwise identical English terms.
#: Applied in both directions, so one table covers US->UK and UK->US.
SPELLING_PAIRS = (
    ("our", "or"),
    ("ise", "ize"),
    ("isa", "iza"),
    ("yse", "yze"),
    ("re", "er"),
    ("ogue", "og"),
    ("ae", "e"),
    ("oe", "e"),
    ("ll", "l"),
    ("ce", "se"),
)

#: Edit-distance variants with a linguistic reason to exist.  Everything else at
#: distance <=2 is a string coincidence.
PRINCIPLED_VARIANTS = frozenset({"caseOrDiacriticOnly", "numberVariant", "spellingVariant"})

EDIT_DISTANCE_CLASS = "editDistanceNearMiss"


# --------------------------------------------------------------------------- #
# variant classification (E-V5)
# --------------------------------------------------------------------------- #


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion.

    Wilson rather than normal-approximation because several populations here are
    tiny (5 spelling variants, 11 number variants) and at those counts the normal
    interval runs past 0 and 1 and understates the width besides.
    """
    if total <= 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z / denominator * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return max(0.0, centre - half), min(1.0, centre + half)


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for the 2x2 table [[a, b], [c, d]].

    Exact rather than chi-square: the cells this is asked about routinely hold
    single digits, where the chi-square approximation is not trustworthy.
    """

    def _hypergeom(w: int, x: int, y: int, zz: int) -> float:
        return math.exp(
            math.lgamma(w + x + 1)
            + math.lgamma(y + zz + 1)
            + math.lgamma(w + y + 1)
            + math.lgamma(x + zz + 1)
            - math.lgamma(w + x + y + zz + 1)
            - math.lgamma(w + 1)
            - math.lgamma(x + 1)
            - math.lgamma(y + 1)
            - math.lgamma(zz + 1)
        )

    observed = _hypergeom(a, b, c, d)
    total = 0.0
    for i in range(min(a + b, a + c) + 1):
        j, k, m = a + b - i, a + c - i, d - (a - i)
        if j < 0 or k < 0 or m < 0:
            continue
        probability = _hypergeom(i, j, k, m)
        if probability <= observed * (1 + 1e-9):
            total += probability
    return min(total, 1.0)


def _fold(label: str) -> str:
    """Case-fold and strip diacritics, so `RÉGIME` and `regime` compare equal."""
    decomposed = unicodedata.normalize("NFKD", label)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower().strip()


def _number_forms(word: str) -> set[str]:
    forms = {word}
    if word.endswith("ies"):
        forms.add(word[:-3] + "y")
    if word.endswith("es"):
        forms.add(word[:-2])
    if word.endswith("s"):
        forms.add(word[:-1])
    return forms


def _spelling_forms(word: str) -> set[str]:
    forms = {word}
    for left, right in SPELLING_PAIRS:
        # Rewrites compose, so each pair is applied to everything produced so far.
        forms = forms | {form.replace(left, right) for form in forms} | {form.replace(right, left) for form in forms}
    return forms


def variant_class(source: str, target: str) -> str:
    """Why two near-identical labels differ, or ``unprincipled`` if there is no reason."""
    folded_source, folded_target = _fold(source), _fold(target)
    if folded_source == folded_target:
        return "caseOrDiacriticOnly"
    if _number_forms(folded_source) & _number_forms(folded_target):
        return "numberVariant"
    if _spelling_forms(folded_source) & _spelling_forms(folded_target):
        return "spellingVariant"
    return "unprincipled"


# --------------------------------------------------------------------------- #
# admission lattices (E-V1)
# --------------------------------------------------------------------------- #


def _verdicts(row: dict[str, Any]) -> tuple[str, str]:
    left, right = (judge["verdictRelation"] for judge in row["sealedJudges"])
    return left, right


def _same_meaning(left: str, right: str) -> bool:
    """The production v2 lattice: identical verdicts, or same/near_same."""
    return left == right or {left, right} == {"same", "near_same"}


def _one_step(left: str, right: str) -> bool:
    return left in GRANULARITY and right in GRANULARITY and abs(GRANULARITY[left] - GRANULARITY[right]) <= 1


def _is_principled_edit_distance(row: dict[str, Any]) -> bool:
    return row["generationClass"] == EDIT_DISTANCE_CLASS and (
        variant_class(row["sourceLabel"], row["targetLabel"]) in PRINCIPLED_VARIANTS
    )


@dataclass(frozen=True, slots=True)
class Rule:
    """One admission lattice: are this row's two supporting verdicts compatible?"""

    name: str
    summary: str
    compatible: Callable[[dict[str, Any]], bool]


def _r0_equivalence(row: dict[str, Any]) -> bool:
    return _same_meaning(*_verdicts(row))


def _r1_granularity_label_equality(row: dict[str, Any]) -> bool:
    left, right = _verdicts(row)
    if _same_meaning(left, right):
        return True
    return row["generationClass"] in LABEL_EQUALITY_CLASSES and _one_step(left, right)


def _r2_granularity_any_class(row: dict[str, Any]) -> bool:
    left, right = _verdicts(row)
    return _same_meaning(left, right) or _one_step(left, right)


def _r3_related_absorbs_direction(row: dict[str, Any]) -> bool:
    left, right = _verdicts(row)
    if _r2_granularity_any_class(row):
        return True
    # Treat an associative verdict as compatible with a directional one.  This is
    # the only way to reach the 85-row figure the documents reported, and it is a
    # much stronger claim than a granularity shift: "related" and "narrower" are
    # a genuine disagreement about the kind of link, not its degree.
    return "related" in (left, right) and {left, right} - {"related"} <= set(GRANULARITY)


def _r4_granularity_principled(row: dict[str, Any]) -> bool:
    """R1, extended to edit-distance candidates that are real orthographic variants.

    Falls out of combining E-V1 with E-V5: the granularity collapse is safe
    wherever the two labels denote the same term, and a number or US/UK spelling
    variant qualifies as squarely as an alias does.  It reaches the two obviously
    correct rows R1 leaves behind without touching the 149 coincidences.
    """
    left, right = _verdicts(row)
    if _same_meaning(left, right):
        return True
    eligible = row["generationClass"] in LABEL_EQUALITY_CLASSES or _is_principled_edit_distance(row)
    return eligible and _one_step(left, right)


RULES = (
    Rule("R0-v2-baseline", "production lattice: identical verdicts, or same/near_same", _r0_equivalence),
    Rule("R1-granularity-label-equality", "R0 + one granularity step, label-equality classes only", _r1_granularity_label_equality),
    Rule("R2-granularity-any-class", "R0 + one granularity step, any non-control class", _r2_granularity_any_class),
    Rule("R3-related-absorbs-direction", "R2 + associative treated as compatible with directional", _r3_related_absorbs_direction),
    Rule("R4-granularity-principled-variants", "R1 + edit-distance candidates that are real orthographic variants", _r4_granularity_principled),
)


def load(benchmarks: Path) -> dict[tuple[str, int], dict[str, Any]]:
    """Reassemble the 1,095-row population from the four disjoint benchmark sets."""
    population: dict[tuple[str, int], dict[str, Any]] = {}
    for name in SETS:
        for line in (benchmarks / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            key = (row["crosswalk"], row["row"])
            if key in population:
                raise RuntimeError(f"{key} appears in both {population[key]['set']} and {name}")
            row["set"] = name
            population[key] = row
    return population


def _both_support(row: dict[str, Any]) -> bool:
    judges = row["sealedJudges"]
    return len(judges) == 2 and all(judge["outcome"] == "supports" for judge in judges)


def admitted_under(population: dict[tuple[str, int], dict[str, Any]], rule: Rule, *, controls: bool) -> set[tuple[str, int]]:
    """Rows the lattice would admit, restricted to control or non-control candidates."""
    return {
        key
        for key, row in population.items()
        if ((row["generationClass"] in CONTROL_CLASSES) == controls) and _both_support(row) and rule.compatible(row)
    }


def verify_baseline(population: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    """Reproduce the recorded admissions, and locate the gate that is not the lattice.

    Returns the audit rather than only a pass/flag, because *which* rows the
    lattice alone would have admitted is the finding: they are all controls, and
    they are why the control rejection rate was never a judge measurement.
    """
    recorded = {key for key, row in population.items() if row["set"] == "positives"}
    baseline = RULES[0]
    lattice_only = {key for key, row in population.items() if _both_support(row) and baseline.compatible(row)}
    with_exclusion = admitted_under(population, baseline, controls=False)
    if with_exclusion != recorded:
        missing = sorted(recorded - with_exclusion)
        extra = sorted(with_exclusion - recorded)
        raise RuntimeError(
            f"reconstructed rule does not reproduce the recorded admissions: "
            f"{len(missing)} recorded rows it rejects, {len(extra)} it admits. First few: {missing[:5]} / {extra[:5]}"
        )
    excluded = lattice_only - with_exclusion
    return {
        "recordedAdmissions": len(recorded),
        "reproducedBy": "control-class exclusion applied before the v2 lattice",
        "mismatches": 0,
        "clearedLatticeButExcluded": len(excluded),
        "excludedByClass": dict(collections.Counter(population[key]["generationClass"] for key in sorted(excluded))),
    }


def calibration(population: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    """Measure what the 100% sealed-judge control baseline should have been.

    Support rate, not rejection rate, because that is what the bytes record: a
    judge that names a relation on a seeded negative supported it, whatever the
    admission step later did with the row.
    """
    by_class: dict[str, dict[str, Any]] = {}
    for cls in sorted(CONTROL_CLASSES):
        rows = [row for row in population.values() if row["generationClass"] == cls]
        # A rate over no rows is not zero, it is undefined; say so rather than
        # emitting a 0.0 that reads as "nobody supported any of them".
        denominator = len(rows) or None
        entry: dict[str, Any] = {"rows": len(rows)}
        for group in ("google-gemini", "openai"):
            supports = sum(
                1 for row in rows for judge in row["sealedJudges"] if judge["group"] == group and judge["outcome"] == "supports"
            )
            entry[group] = {"supports": supports, "rate": supports / denominator if denominator else None}
        reviewer = sum(1 for row in rows if row["independentVerdict"] in SUPPORT)
        entry["independentReviewer"] = {"supports": reviewer, "rate": reviewer / denominator if denominator else None}
        entry["judgeRelationsWhenSupporting"] = dict(
            collections.Counter(
                judge["verdictRelation"] for row in rows for judge in row["sealedJudges"] if judge["outcome"] == "supports"
            )
        )
        by_class[cls] = entry

    strata = {}
    for name in SETS:
        rows = [row for row in population.values() if row["set"] == name]
        supports = sum(1 for row in rows if row["independentVerdict"] in SUPPORT)
        strata[name] = {
            "rows": len(rows),
            "reviewerSupports": supports,
            "rate": supports / len(rows) if rows else None,
        }

    # How much a reviewer "supports" verdict is worth, against the two negative
    # populations that exist: real candidates the judges rejected, and planted
    # random pairs.  A reviewer that supported everything would score 1.0 here.
    def _ratio(negative: float | None) -> float | None:
        positives = strata["positives"]["rate"]
        if positives is None or not negative:
            return None
        return positives / negative

    ratios = {
        "vsHardNegatives": _ratio(strata["hard-negatives"]["rate"]),
        "vsRandomNegativeControl": _ratio(by_class["randomNegativeControl"]["independentReviewer"]["rate"]),
    }
    return {"controlSupportRates": by_class, "reviewerSupportByStratum": strata, "supportLikelihoodRatio": ratios}


def _contrast(by_class: dict[str, collections.Counter]) -> dict[str, Any]:
    """Is edit distance really different, or is 30 admissions too few to say?"""
    edit = by_class.get(EDIT_DISTANCE_CLASS, collections.Counter())
    rest: collections.Counter = collections.Counter()
    for cls, counts in by_class.items():
        if cls != EDIT_DISTANCE_CLASS:
            rest.update(counts)
    a, b = edit["relatedMatch"], sum(edit.values()) - edit["relatedMatch"]
    c, d = rest["relatedMatch"], sum(rest.values()) - rest["relatedMatch"]
    return {
        "editDistance": {"relatedMatch": a, "other": b},
        "allOtherClasses": {"relatedMatch": c, "other": d},
        "fisherP": fisher_exact(a, b, c, d) if (a + b) and (c + d) else None,
    }


def relation_share(population: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    """E-V4 — which SKOS relation each generation class earns when it is admitted."""
    by_class: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for row in population.values():
        if row["set"] == "positives":
            by_class[row["generationClass"]][row["admittedRelation"]] += 1
    overall: collections.Counter = collections.Counter()
    for counts in by_class.values():
        overall.update(counts)
    total = sum(overall.values()) or 1
    base = overall["relatedMatch"] / total
    return {
        "admissions": total,
        "overall": dict(overall),
        "relatedMatchBaseRate": base,
        "byGenerationClass": {
            cls: {
                "admissions": sum(counts.values()),
                "relations": dict(counts),
                "relatedMatchShare": counts["relatedMatch"] / sum(counts.values()),
                "liftOverBaseRate": (counts["relatedMatch"] / sum(counts.values()) / base) if base else None,
            }
            for cls, counts in sorted(by_class.items())
        },
        # Every share above is a proportion over a small count; carrying the
        # interval with it stops the point estimate travelling alone.
        "interval95": {
            cls: wilson(counts["relatedMatch"], sum(counts.values()))
            for cls, counts in sorted(by_class.items())
        },
        "editDistanceVsRest": _contrast(by_class),
    }


def _variant_contrast(buckets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The claim E-V5 rests on: principled variants admit, coincidences do not."""
    p_gen = sum(e["generated"] for c, e in buckets.items() if c in PRINCIPLED_VARIANTS)
    p_adm = sum(e["admitted"] for c, e in buckets.items() if c in PRINCIPLED_VARIANTS)
    p_rel = sum(e["relatedMatch"] for c, e in buckets.items() if c in PRINCIPLED_VARIANTS)
    u = buckets.get("unprincipled", {"generated": 0, "admitted": 0, "relatedMatch": 0})
    return {
        "principled": {"generated": p_gen, "admitted": p_adm, "rate": p_adm / p_gen if p_gen else None, "rate95": wilson(p_adm, p_gen)},
        "unprincipled": {
            "generated": u["generated"],
            "admitted": u["admitted"],
            "rate": u["admitted"] / u["generated"] if u["generated"] else None,
            "rate95": wilson(u["admitted"], u["generated"]),
        },
        "admissionRateFisherP": fisher_exact(p_adm, p_gen - p_adm, u["admitted"], u["generated"] - u["admitted"])
        if p_gen and u["generated"]
        else None,
        "relatedMatchShareFisherP": fisher_exact(p_rel, p_adm - p_rel, u["relatedMatch"], u["admitted"] - u["relatedMatch"])
        if p_adm and u["admitted"]
        else None,
    }


def edit_distance_hygiene(population: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    """E-V5 — split the edit-distance arm into principled variants and coincidences."""
    rows = [row for row in population.values() if row["generationClass"] == EDIT_DISTANCE_CLASS]
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        cls = variant_class(row["sourceLabel"], row["targetLabel"])
        entry = buckets.setdefault(cls, {"generated": 0, "admitted": 0, "relatedMatch": 0, "disputed": 0, "examples": []})
        entry["generated"] += 1
        if row["set"] == "positives":
            entry["admitted"] += 1
            if row["admittedRelation"] == "relatedMatch":
                entry["relatedMatch"] += 1
        if row["set"] == "disputed":
            entry["disputed"] += 1
        if len(entry["examples"]) < 6:
            entry["examples"].append(
                {"source": row["sourceLabel"], "target": row["targetLabel"], "set": row["set"], "relation": row.get("admittedRelation")}
            )
    for entry in buckets.values():
        entry["admissionRate"] = entry["admitted"] / entry["generated"]
        entry["admissionRate95"] = wilson(entry["admitted"], entry["generated"])
        entry["relatedMatchShareOfAdmissions"] = entry["relatedMatch"] / entry["admitted"] if entry["admitted"] else None
        entry["relatedMatchShare95"] = wilson(entry["relatedMatch"], entry["admitted"])
    principled = {cls: entry for cls, entry in buckets.items() if cls in PRINCIPLED_VARIANTS}
    return {
        "generated": len(rows),
        "byVariantClass": dict(sorted(buckets.items())),
        "principled": {
            "generated": sum(entry["generated"] for entry in principled.values()),
            "admitted": sum(entry["admitted"] for entry in principled.values()),
            "relatedMatch": sum(entry["relatedMatch"] for entry in principled.values()),
        },
        "principledVsUnprincipled": _variant_contrast(buckets),
        # Per-row classification so downstream analyses can join on it rather than
        # reimplementing the classifier.  This is its only authoritative definition.
        "rows": sorted(
            (
                {"crosswalk": row["crosswalk"], "row": row["row"], "variantClass": variant_class(row["sourceLabel"], row["targetLabel"])}
                for row in rows
            ),
            key=lambda entry: (entry["crosswalk"], entry["row"]),
        ),
    }


def order_independence(population: dict[tuple[str, int], dict[str, Any]], rule: Rule, *, seeds: int = 5) -> dict[str, Any]:
    """E-V7 — does the admitted set depend on the order candidates are considered?

    The answer is structural: this rule reads one row at a time and keeps no
    state between rows, so it cannot depend on order.  Demonstrated rather than
    asserted, because the concern the design raised is real for any *future*
    rule that adds a redundancy or graph-minimality check -- and this archive's
    admission never had one, which is why its 582 admitted candidates produced
    582 assertions with nothing collapsed.
    """
    keys = list(population)
    outcomes = set()
    for seed in range(seeds):
        shuffled = keys[:]
        random.Random(seed).shuffle(shuffled)
        admitted = frozenset(
            key
            for key in shuffled
            if population[key]["generationClass"] not in CONTROL_CLASSES
            and _both_support(population[key])
            and rule.compatible(population[key])
        )
        outcomes.add(admitted)
    return {
        "rule": rule.name,
        "ordersTried": seeds,
        "distinctAdmittedSets": len(outcomes),
        "orderIndependent": len(outcomes) == 1,
        "reason": "the rule carries no cross-row state; no redundancy or graph-minimality check is applied",
    }


def replay(population: dict[tuple[str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = admitted_under(population, RULES[0], controls=False)
    baseline_controls = admitted_under(population, RULES[0], controls=True)
    results = []
    for rule in RULES:
        admitted = admitted_under(population, rule, controls=False)
        controls = admitted_under(population, rule, controls=True)
        new = sorted(admitted - baseline)
        results.append(
            {
                "rule": rule.name,
                "summary": rule.summary,
                "admitted": len(admitted),
                "deltaVsBaseline": len(admitted) - len(baseline),
                "shareOfBaselineGraph": (len(admitted) - len(baseline)) / len(baseline),
                "controlsClearingLattice": len(controls),
                "controlsAddedVsBaseline": len(controls) - len(baseline_controls),
                "newlyAdmitted": {
                    "rows": len(new),
                    "fromDisputedSet": sum(1 for key in new if population[key]["set"] == "disputed"),
                    "byGenerationClass": dict(collections.Counter(population[key]["generationClass"] for key in new)),
                    "reviewerSupports": sum(1 for key in new if population[key]["independentVerdict"] in SUPPORT),
                    "reviewerPicksAJudgeRelation": sum(1 for key in new if population[key]["independentVerdict"] in _verdicts(population[key])),
                    "reviewerCallsDirect": sum(1 for key in new if population[key]["independentDirectness"] == "direct_candidate"),
                },
            }
        )
    return results


def disputed_profile(population: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    """What the 86 unresolved rows actually disagree about.  Scored, not resolved."""
    rows = [row for row in population.values() if row["set"] == "disputed"]
    pairs = collections.Counter(" vs ".join(sorted(_verdicts(row))) for row in rows)
    return {
        "rows": len(rows),
        "byGenerationClass": dict(collections.Counter(row["generationClass"] for row in rows)),
        "verdictPairs": dict(sorted(pairs.items(), key=lambda item: -item[1])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--benchmarks", type=Path, required=True, help="atlas-crosswalk-benchmarks-2026-08-06 directory")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    def pct(rate: float | None) -> str:
        return f"{rate:>8.1%}" if rate is not None else f"{'n/a':>8}"

    def times(ratio: float | None) -> str:
        return f"{ratio:.1f}x" if ratio is not None else "n/a"

    population = load(args.benchmarks)
    audit = verify_baseline(population)
    print(f"population {len(population)} rows; reconstructed rule reproduces {audit['recordedAdmissions']} admissions, 0 mismatches")
    print(f"  {audit['clearedLatticeButExcluded']} rows cleared the lattice and were excluded by class: {audit['excludedByClass']}")

    cal = calibration(population)
    print("\nE-V2 · control support rate (a relation was named on a seeded negative):")
    print(f"  {'class':<24} {'gemini':>9} {'openai':>9} {'reviewer':>9}")
    for cls, entry in cal["controlSupportRates"].items():
        print(
            f"  {cls:<24} {pct(entry['google-gemini']['rate'])} {pct(entry['openai']['rate'])} "
            f"{pct(entry['independentReviewer']['rate'])}"
        )
    print("  reviewer support rate by stratum:")
    for name, entry in cal["reviewerSupportByStratum"].items():
        print(f"    {name:<16} {entry['reviewerSupports']:>4}/{entry['rows']:<5} {pct(entry['rate'])}")
    print(
        f"  support likelihood ratio: {times(cal['supportLikelihoodRatio']['vsHardNegatives'])} against rejected real "
        f"candidates, {times(cal['supportLikelihoodRatio']['vsRandomNegativeControl'])} against random pairs"
    )

    results = replay(population)
    print(f"\nE-V1 · {'rule':<38} {'admitted':>8} {'delta':>6} {'ctrl+':>6}  newly admitted")
    for entry in results:
        new = entry["newlyAdmitted"]
        detail = (
            f"reviewer supports {new['reviewerSupports']}/{new['rows']}, "
            f"names a judge relation {new['reviewerPicksAJudgeRelation']}/{new['rows']}, "
            f"direct {new['reviewerCallsDirect']}/{new['rows']}"
            if new["rows"]
            else "-"
        )
        print(
            f"       {entry['rule']:<38} {entry['admitted']:>8} {entry['deltaVsBaseline']:>+6} "
            f"{entry['controlsAddedVsBaseline']:>+6}  {detail}"
        )

    def ci(bounds: tuple[float, float] | None) -> str:
        return f"[{bounds[0]:.1%}–{bounds[1]:.1%}]" if bounds else "[n/a]"

    share = relation_share(population)
    print(f"\nE-V4 · relatedMatch share of admissions (base rate {share['relatedMatchBaseRate']:.1%}):")
    for cls, entry in share["byGenerationClass"].items():
        lift = f"{entry['liftOverBaseRate']:.1f}x" if entry["liftOverBaseRate"] is not None else "n/a"
        print(
            f"  {cls:<26} {entry['admissions']:>4} admitted   relatedMatch {entry['relatedMatchShare']:>6.1%} "
            f"{ci(share['interval95'][cls]):<17} ({lift} base)"
        )
    contrast = share["editDistanceVsRest"]
    if contrast["fisherP"] is not None:
        print(f"  edit distance vs every other class, Fisher exact p = {contrast['fisherP']:.2e}")

    hygiene = edit_distance_hygiene(population)
    print(f"\nE-V5 · the {hygiene['generated']} editDistanceNearMiss candidates:")
    print(f"  {'variant class':<24} {'gen':>5} {'adm':>5} {'rate':>7} {'95% CI':>17} {'relatedMatch of adm.':>22}")
    for cls, entry in hygiene["byVariantClass"].items():
        related = f"{entry['relatedMatchShareOfAdmissions']:.1%}" if entry["admitted"] else "n/a"
        print(
            f"  {cls:<24} {entry['generated']:>5} {entry['admitted']:>5} {entry['admissionRate']:>7.1%} "
            f"{ci(entry['admissionRate95']):>17} {entry['relatedMatch']:>10} ({related:>7}) {ci(entry['relatedMatchShare95'])}"
        )
    vc = hygiene["principledVsUnprincipled"]
    print(
        f"  principled {vc['principled']['admitted']}/{vc['principled']['generated']} "
        f"({vc['principled']['rate']:.1%} {ci(vc['principled']['rate95'])})  vs  "
        f"unprincipled {vc['unprincipled']['admitted']}/{vc['unprincipled']['generated']} "
        f"({vc['unprincipled']['rate']:.1%} {ci(vc['unprincipled']['rate95'])})"
    )
    print(
        f"  admission-rate Fisher p = {vc['admissionRateFisherP']:.2e}   "
        f"relatedMatch-share Fisher p = {vc['relatedMatchShareFisherP']:.3f}"
    )

    order = order_independence(population, RULES[-1])
    print(
        f"\nE-V7 · order independence under {order['rule']}: {order['distinctAdmittedSets']} distinct admitted set "
        f"across {order['ordersTried']} orders — {order['reason']}"
    )

    payload = {
        "type": "AtlasCrosswalkAdmissionReplay",
        "experiments": ["E-V1", "E-V2 (calibration half)", "E-V4", "E-V5", "E-V7"],
        "note": (
            "The 86 disputed rows are scored here, never resolved. Control admissions are reported "
            "against the lattice with the control-class exclusion lifted, which is the only way to see "
            "what a relaxed lattice would let through. The population is machine-proposed cross-vocabulary "
            "pairs, not publisher assertions."
        ),
        "baselineAudit": audit,
        "calibration": cal,
        "rules": results,
        "relationShare": share,
        "editDistanceHygiene": hygiene,
        "orderIndependence": order,
        "disputed": disputed_profile(population),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
