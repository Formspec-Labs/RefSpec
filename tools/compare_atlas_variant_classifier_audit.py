"""Join the blind linguistic audit to the orthographic variant classifier.

The classifier decides whether two near-identical labels differ for a reason or
by coincidence, and R4 admits granularity-collapsed mappings on the strength of
that decision.  It is string heuristics: case folding, one English pluralisation
rule, a ten-entry US/UK rewrite table.  This joins its verdicts to a blind
reviewer's morphological reading of the same 165 pairs.

**The two error types are not symmetric and are never pooled here.**

*False principled* -- the classifier says number or spelling variant, the
reviewer says two different words.  These are the dangerous ones: each is a
coincidence that R4 will admit as a collapsed mapping, and a wrong edge in a
graph the product traverses costs more than a missing one.

*False unprincipled* -- the classifier says coincidence, the reviewer says real
variant.  These are merely wasteful: a candidate the generator restriction
throws away that it should have kept.

A single "accuracy" figure would average those two together and hide the only
number that matters.  Precision on the principled class is reported on its own,
with a Wilson interval, because it is small by construction -- 16 rows -- and a
point estimate over 16 rows should never travel alone.

Read-only.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any

try:  # Wilson intervals live with the replay harness.
    from tools import replay_atlas_crosswalk_admission as replay
except ImportError:  # Direct execution places tools/ on sys.path.
    import replay_atlas_crosswalk_admission as replay

#: The reviewer names diacritic/case agreement separately; the classifier folds
#: it into one bucket.  Mapped rather than treated as a disagreement.
ALIASES = {"diacriticOrCaseOnly": "caseOrDiacriticOnly"}

PRINCIPLED = replay.PRINCIPLED_VARIANTS


def _normalise(label: str) -> str:
    return ALIASES.get(label, label)


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def load(directory: Path, pass_name: str) -> tuple[list[dict], dict[int, dict]]:
    key = json.loads((directory / "sealed-key" / "pairs.json").read_text(encoding="utf-8"))["rows"]
    blind = {row["row"]: row for row in json.loads((directory / "blind" / "pairs.json").read_text(encoding="utf-8"))["rows"]}
    verdicts: dict[int, dict] = {}
    for line in (directory / "independent" / f"{pass_name}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            row["labels"] = (blind[int(row["row"])]["a"], blind[int(row["row"])]["b"])
            verdicts[int(row["row"])] = row
    return key, verdicts


def analyse(key: list[dict], verdicts: dict[int, dict]) -> dict[str, Any]:
    confusion: collections.Counter = collections.Counter()
    false_principled: list[dict[str, Any]] = []
    false_unprincipled: list[dict[str, Any]] = []
    missing = 0
    exact = 0
    binary = 0

    for entry in key:
        verdict = verdicts.get(entry["row"])
        if verdict is None:
            missing += 1
            continue
        mine, theirs = entry["variantClass"], _normalise(verdict["variantClass"])
        confusion[(mine, theirs)] += 1
        exact += int(mine == theirs)
        mine_principled, theirs_principled = mine in PRINCIPLED, theirs in PRINCIPLED
        binary += int(mine_principled == theirs_principled)
        if mine_principled and not theirs_principled:
            false_principled.append(
                {"row": entry["row"], "labels": verdict["labels"], "classifier": mine, "reviewer": theirs, "why": verdict.get("why")}
            )
        if theirs_principled and not mine_principled:
            false_unprincipled.append(
                {"row": entry["row"], "labels": verdict["labels"], "classifier": mine, "reviewer": theirs, "why": verdict.get("why")}
            )

    scored = len(key) - missing
    classifier_principled = sum(1 for entry in key if entry["variantClass"] in PRINCIPLED)
    confirmed = classifier_principled - len(false_principled)
    return {
        "rowsScored": scored,
        "rowsMissing": missing,
        "exactAgreement": exact / scored if scored else None,
        "principledBinaryAgreement": binary / scored if scored else None,
        "classifierPrincipled": classifier_principled,
        "precisionOnPrincipled": confirmed / classifier_principled if classifier_principled else None,
        "precisionOnPrincipled95": replay.wilson(confirmed, classifier_principled),
        "falsePrincipled": false_principled,
        "falseUnprincipled": false_unprincipled,
        "confusion": {f"{mine} -> {theirs}": count for (mine, theirs), count in sorted(confusion.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--pass-name", default="linguistic")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    path = args.audit / "independent" / f"{args.pass_name}.jsonl"
    if not path.exists():
        print(f"no independent audit at {path}")
        return 1

    key, verdicts = load(args.audit, args.pass_name)
    entry = analyse(key, verdicts)
    entry["digest"] = _digest(path)

    def rate(value: float | None) -> str:
        return f"{value:.1%}" if value is not None else "n/a"

    bounds = entry["precisionOnPrincipled95"]
    print(f"rows scored {entry['rowsScored']}  (missing {entry['rowsMissing']})")
    print(f"  exact four-way agreement            : {rate(entry['exactAgreement'])}")
    print(f"  principled/unprincipled agreement   : {rate(entry['principledBinaryAgreement'])}")
    print(
        f"  precision on the principled class   : {rate(entry['precisionOnPrincipled'])} "
        f"of {entry['classifierPrincipled']}"
        + (f"  [{bounds[0]:.1%}–{bounds[1]:.1%}]" if bounds else "")
    )
    print(f"\n  FALSE PRINCIPLED — coincidences R4 would admit: {len(entry['falsePrincipled'])}")
    for row in entry["falsePrincipled"]:
        print(f"     row {row['row']:>3}  {row['labels'][0]:<28} {row['labels'][1]:<28} classifier={row['classifier']}  ({row['why']})")
    print(f"\n  FALSE UNPRINCIPLED — real variants the restriction would drop: {len(entry['falseUnprincipled'])}")
    for row in entry["falseUnprincipled"][:12]:
        print(f"     row {row['row']:>3}  {row['labels'][0]:<28} {row['labels'][1]:<28} reviewer={row['reviewer']}  ({row['why']})")

    payload = {
        "type": "AtlasVariantClassifierAuditComparison",
        "experiment": "E-V5 classifier validation",
        "note": (
            "False principled and false unprincipled are reported separately and never pooled: the "
            "first admits a coincidence into a traversed graph, the second only loses a candidate."
        ),
        "result": entry,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
