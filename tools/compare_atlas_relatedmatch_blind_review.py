"""Join the blind `relatedMatch` verdicts to the sealed key.

Run only after both independent passes are written and digested.  The sample
withheld admitted relation, generation class, variant class, set membership and
prior verdicts precisely so this join can happen once, in one direction.

Three things come out.

**E-V4, the half replay cannot answer.**  ``relatedMatch`` is admitted at 7.2x
the base rate by edit-distance candidates, and the unprincipled portion of that
arm returns it on 70.6% of its admissions.  Those are counts of a *label*, not of
a fact.  What a blind reviewer calling each pair ``conceptual`` or ``orthographic``
adds is whether the label is deserved -- and the discriminating comparison is not
the raw rate but the gap between ``relatedMatch`` admissions and the matched
non-``relatedMatch`` admissions sitting beside them in the same sample.

**Framing sensitivity.**  Two passes ran over identical bytes, one neutral and
one told to expect planted coincidences.  The difference between them is a direct
measurement of how much a judging result depends on how the question was asked --
which is worth knowing before any single-pass verdict configures production.
Same model family in both, so this is not a cross-family agreement figure.

**Control calibration, done properly this time.**  Seeded negatives ride along
unlabelled.  Their rejection rate is reported per pass and split by kind, against
the sealed judges' *measured* rate rather than an assumed one -- the mistake that
produced the withdrawn "the reviewer failed its calibration" finding.  Sibling
distractors are reported separately and are not treated as clean negatives: a
sibling shares a broader concept with the true target by construction, so
``related`` is often the correct answer on one.

A DEFECT IN THE INSTRUMENT, AND WHY THE HEADLINE USES A RESTRICTED DENOMINATOR

``basisOfAssociation`` offered two values, ``conceptual`` and ``orthographic``,
and no third for *no association at all*.  Both passes hit that gap on rows they
rejected, and resolved it in opposite directions: the neutral pass filed plain
decoys under ``conceptual``, reasoning that whatever weak link exists runs
through meaning; the adversarial pass filed every rejection under
``orthographic``, reasoning that "not conceptual" was the only honest home.  Both
readings are defensible and they are irreconcilable, so on rejected rows the
field carries convention rather than signal -- on control rows it swings from 0%
to 100% between passes on identical bytes.

The question is only well posed where a reviewer asserted a relation: *given that
you would publish this link, is the link carried by meaning or by spelling?*  So
every basis figure is reported twice -- over all rows, and over the rows that
pass asserted a relation on.  The second is the one to quote.  A future sample
should offer three values and the defect disappears; this one is analysed
around it rather than re-asked, because re-asking a sealed sample after seeing
its answers is how a measurement becomes a search for the number you wanted.

Read-only.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any

try:  # Wilson intervals and Fisher exact live with the replay harness.
    from tools import replay_atlas_crosswalk_admission as replay
except ImportError:  # Direct execution places tools/ on sys.path.
    import replay_atlas_crosswalk_admission as replay

PASSES = ("neutral", "adversarial")

#: Taken from the replay harness rather than restated, so the two tools cannot
#: drift apart on what counts as asserting a relation.
SUPPORT = replay.SUPPORT

RELATED = "relatedMatch"


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def load(directory: Path, replay_json: Path | None) -> tuple[list[dict], dict[str, dict[int, dict]], dict[tuple[str, int], str]]:
    key = json.loads((directory / "sealed-key" / "sample.json").read_text(encoding="utf-8"))["rows"]
    passes: dict[str, dict[int, dict]] = {}
    for name in PASSES:
        path = directory / "independent" / f"{name}.jsonl"
        if not path.exists():
            continue
        rows: dict[int, dict] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[int(row["row"])] = row
        passes[name] = rows
    variants: dict[tuple[str, int], str] = {}
    if replay_json and replay_json.exists():
        hygiene = json.loads(replay_json.read_text(encoding="utf-8"))["editDistanceHygiene"]
        variants = {(entry["crosswalk"], entry["row"]): entry["variantClass"] for entry in hygiene["rows"]}
    return key, passes, variants


def _stratum(entry: dict[str, Any]) -> str:
    if entry["set"] == "controls":
        return entry["generationClass"]
    if entry["set"] == "positives":
        return "relatedMatchAdmission" if entry["admittedRelation"] == RELATED else "otherAdmission"
    return entry["set"]


def analyse(key: list[dict], verdicts: dict[int, dict], variants: dict[tuple[str, int], str]) -> dict[str, Any]:
    strata: dict[str, dict[str, Any]] = collections.defaultdict(
        lambda: {
            "rows": 0,
            "orthographic": 0,
            "supportsRelation": 0,
            "highConfidence": 0,
            "asserted": 0,
            "assertedOrthographic": 0,
            "survives": 0,
        }
    )
    by_variant: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: {"rows": 0, "orthographic": 0, "asserted": 0, "assertedOrthographic": 0}
    )
    missing = 0
    examples: list[dict[str, Any]] = []

    for entry in key:
        verdict = verdicts.get(entry["row"])
        if verdict is None:
            missing += 1
            continue
        bucket = strata[_stratum(entry)]
        bucket["rows"] += 1
        orthographic = verdict["basisOfAssociation"] == "orthographic"
        asserted = verdict["bestRelation"] in SUPPORT
        bucket["orthographic"] += int(orthographic)
        bucket["supportsRelation"] += int(asserted)
        bucket["highConfidence"] += int(verdict.get("confidence") == "high")
        # The basis question is only well posed where a relation was asserted;
        # see the instrument note in the module docstring.
        bucket["asserted"] += int(asserted)
        bucket["assertedOrthographic"] += int(asserted and orthographic)
        # A row survives when the reviewer both asserts a relation and says the
        # connection runs through meaning rather than spelling.
        bucket["survives"] += int(asserted and not orthographic)

        variant = variants.get((entry["crosswalk"], entry["sourceRow"]))
        if variant is not None:
            slot = by_variant[variant]
            slot["rows"] += 1
            slot["orthographic"] += int(orthographic)
            slot["asserted"] += int(asserted)
            slot["assertedOrthographic"] += int(asserted and orthographic)

        if entry["admittedRelation"] == RELATED and orthographic and len(examples) < 8:
            examples.append(
                {
                    "row": entry["row"],
                    "generationClass": entry["generationClass"],
                    "assertedRelation": verdict["bestRelation"],
                    "why": verdict.get("why"),
                }
            )

    for bucket in (*strata.values(), *by_variant.values()):
        bucket["orthographicRate"] = bucket["orthographic"] / bucket["rows"] if bucket["rows"] else None
        bucket["assertedOrthographicRate"] = bucket["assertedOrthographic"] / bucket["asserted"] if bucket["asserted"] else None
    for bucket in strata.values():
        bucket["supportRate"] = bucket["supportsRelation"] / bucket["rows"] if bucket["rows"] else None

    def _gap(field: str) -> float | None:
        related, other = strata.get("relatedMatchAdmission", {}), strata.get("otherAdmission", {})
        if related.get(field) is None or other.get(field) is None:
            return None
        return related[field] - other[field]

    # Survival is the figure the documents quote, so it carries its interval and
    # the exact test against the matched admissions sitting beside it.
    for bucket in strata.values():
        bucket["survivalRate"] = bucket["survives"] / bucket["rows"] if bucket["rows"] else None
        bucket["survivalRate95"] = replay.wilson(bucket["survives"], bucket["rows"])
    rel, oth = strata.get("relatedMatchAdmission"), strata.get("otherAdmission")
    survival_test = None
    if rel and oth:
        survival_test = {
            "relatedMatch": {"survives": rel["survives"], "rows": rel["rows"]},
            "otherAdmissions": {"survives": oth["survives"], "rows": oth["rows"]},
            "fisherP": replay.fisher_exact(
                rel["survives"], rel["rows"] - rel["survives"], oth["survives"], oth["rows"] - oth["survives"]
            ),
        }

    return {
        "survivalTest": survival_test,
        "rowsMissing": missing,
        "byStratum": {name: dict(value) for name, value in sorted(strata.items())},
        "byVariantClass": {name: dict(value) for name, value in sorted(by_variant.items())},
        "orthographicGapRelatedVsOther": _gap("orthographicRate"),
        "assertedOrthographicGapRelatedVsOther": _gap("assertedOrthographicRate"),
        "orthographicRelatedMatchExamples": examples,
    }


def agreement(key: list[dict], passes: dict[str, dict[int, dict]]) -> dict[str, Any] | None:
    """How much the two framings move, on identical bytes."""
    if len(passes) < 2:
        return None
    neutral, adversarial = passes["neutral"], passes["adversarial"]
    shared = sorted(set(neutral) & set(adversarial))
    fields = ("relationExists", "bestRelation", "basisOfAssociation")
    counts = {field: sum(1 for row in shared if neutral[row][field] == adversarial[row][field]) for field in fields}
    prior = {entry["row"]: entry["priorIndependentVerdict"] for entry in key}
    prior_agreement = {
        name: sum(1 for row in shared if rows[row]["bestRelation"] == prior.get(row)) for name, rows in passes.items()
    }
    flips = [
        {"row": row, "neutral": neutral[row]["basisOfAssociation"], "adversarial": adversarial[row]["basisOfAssociation"]}
        for row in shared
        if neutral[row]["basisOfAssociation"] != adversarial[row]["basisOfAssociation"]
    ]
    return {
        "rowsCompared": len(shared),
        "agreementRate": {field: value / len(shared) for field, value in counts.items()},
        "exactRelationAgreementWithPriorReviewer": {
            name: value / len(shared) for name, value in prior_agreement.items()
        },
        "basisFlips": len(flips),
        "basisFlipExamples": flips[:8],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review", type=Path, required=True, help="atlas-relatedmatch-blind-review-2026-08-06 directory")
    parser.add_argument("--replay", type=Path, default=None, help="admission replay JSON, for per-row variant classes")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    key, passes, variants = load(args.review, args.replay)
    if not passes:
        print("no independent decisions yet")
        return 1

    results: dict[str, Any] = {}
    for name, verdicts in passes.items():
        entry = analyse(key, verdicts, variants)
        entry["digest"] = _digest(args.review / "independent" / f"{name}.jsonl")
        results[name] = entry

        def rate(value: float | None) -> str:
            return f"{value:.1%}" if value is not None else "n/a"

        print(f"\n=== {name}   (missing rows: {entry['rowsMissing']})")
        print(f"  {'stratum':<24} {'rows':>5} {'asserts a relation':>19} {'orthographic (all)':>19} {'orthographic (asserted)':>24}")
        for stratum, value in entry["byStratum"].items():
            print(
                f"  {stratum:<24} {value['rows']:>5} {value['supportsRelation']:>9} ({rate(value['supportRate']):>6}) "
                f"{value['orthographic']:>9} ({rate(value['orthographicRate']):>6}) "
                f"{value['assertedOrthographic']:>13}/{value['asserted']:<3} ({rate(value['assertedOrthographicRate']):>6})"
                f"  survives {value['survives']:>3}/{value['rows']:<3} ({rate(value['survivalRate']):>6})"
            )
        test = entry.get("survivalTest")
        if test:
            print(
                f"  survival: relatedMatch {test['relatedMatch']['survives']}/{test['relatedMatch']['rows']}"
                f"  vs other admissions {test['otherAdmissions']['survives']}/{test['otherAdmissions']['rows']}"
                f"   Fisher exact p = {test['fisherP']:.2e}"
            )
        if entry["assertedOrthographicGapRelatedVsOther"] is not None:
            print(
                f"  orthographic gap on asserted rows, relatedMatch minus other admissions: "
                f"{entry['assertedOrthographicGapRelatedVsOther']:+.1%}   [quote this one]"
            )
        if entry["byVariantClass"]:
            print("  edit-distance rows by variant class (orthographic among asserted):")
            for variant, value in entry["byVariantClass"].items():
                print(
                    f"     {variant:<22} n={value['rows']:<4} asserted={value['asserted']:<4} "
                    f"orthographic={value['assertedOrthographic']} ({rate(value['assertedOrthographicRate'])})"
                )

    concord = agreement(key, passes)
    if concord:
        print(f"\n=== framing sensitivity   ({concord['rowsCompared']} rows in both passes)")
        for field, rate in concord["agreementRate"].items():
            print(f"  {field:<22} {rate:>7.1%}")
        print(f"  basis verdict flipped on {concord['basisFlips']} rows")
        for name, rate in concord["exactRelationAgreementWithPriorReviewer"].items():
            print(f"  exact-relation agreement with the earlier blind reviewer, {name:<12} {rate:>6.1%}")

    payload = {
        "type": "AtlasRelatedMatchBlindReviewComparison",
        "experiments": ["E-V4 (judged half)", "E-V2 (framing and agreement half)"],
        "limitation": (
            "Both passes use the same model family. Agreement here measures framing sensitivity and "
            "annotator stability, not cross-family agreement. Sibling distractors are not clean "
            "negatives and their rejection rate is not an error rate."
        ),
        "passes": results,
        "framingSensitivity": concord,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
