"""Join independent blind verdicts to the sealed crosswalk key.

Run only after the independent decisions are written and digested.  The blind
samples withheld outcomes, verdict relations, admission status, generation class,
and provider identity precisely so this join can happen once, in one direction.

Five measurements come out, none of which exist elsewhere in the programme:

**Three-way agreement.**  The sealed crosswalks carry two independent model
families.  A third reviewer turns provider-versus-provider concordance into a
genuine inter-annotator measurement, on 1,095 cross-vocabulary rows rather than
the 108-row intra-vocabulary sample the ledger audited.

**Control calibration.**  Every crosswalk seeds 45 random negative controls and
45 sibling distractors.  The independent reviewer never knew which rows those
were, so its rejection rate on them says something about the reviewer -- but only
against the sealed judges' rate on the same rows, which is computed here rather
than assumed.  An earlier version of this tool printed a hardcoded 100% baseline;
no control was ever *admitted*, but that was a control-class exclusion applied
ahead of the relation lattice, and the judges themselves name a relation on more
than half the sibling distractors.  Sibling distractors are not clean negatives:
a sibling shares a broader concept with the true target, so ``related`` is often
the correct answer on one.

**Recoverable rejections.**  86 non-control candidates were rejected despite both
sealed judges supporting a relation; they died on incompatible relation type, not
on whether a relation exists.  A third reviewer supporting them makes them
*candidates* for recovery, not recovered mappings -- what an admission rule can
actually take back is 37 of the 86, measured by
``replay_atlas_crosswalk_admission.py``.  Do not read the number below as a
graph-size delta.

**Directness keep rate.**  What share of *admitted* mappings a reviewer applying
a traversal-oriented directness bar would actually assert.  The 65-row
intra-vocabulary re-review cut 80%; this is the first cross-vocabulary estimate.

**Per-class behaviour.**  Each generation class has a characteristic confusion --
label equality splits on ``same``/``near_same``, substring on
``related``/``narrower`` -- so agreement is reported per class, where a fix would
actually be applied.

Read-only.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any

CROSSWALKS = ("fr-elsst", "fr-icpsr", "elsst-icpsr")

#: Verdicts that assert some relation exists.
SUPPORT = frozenset({"same", "near_same", "target_is_broader", "target_is_narrower", "related"})

#: Compatible pairs under the production v2 agreement lattice: identical
#: verdicts, plus ``same``/``near_same`` which both resolve to closeMatch.
COMPATIBLE = frozenset({frozenset({"same", "near_same"})})


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _supports(verdict: str | None) -> bool:
    return verdict in SUPPORT


def _compatible(left: str, right: str) -> bool:
    return left == right or frozenset({left, right}) in COMPATIBLE


def load(directory: Path, crosswalk: str) -> tuple[list[dict], list[dict], dict[int, dict]]:
    blind = json.loads((directory / "blind" / f"{crosswalk}.json").read_text(encoding="utf-8"))["rows"]
    key = json.loads((directory / "sealed-key" / f"{crosswalk}.json").read_text(encoding="utf-8"))["rows"]
    independent: dict[int, dict] = {}
    with (directory / "independent" / f"{crosswalk}.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                independent[int(row["row"])] = row
    return blind, key, independent


def generation_classes(archive: Path, crosswalk: str) -> dict[str, str]:
    """Map candidate id to its generation class."""
    bundle = json.loads((archive / crosswalk / "crosswalk-bundle.json").read_text(encoding="utf-8"))
    evidence = {a["id"]: a["content"] for a in bundle["artifacts"] if a["role"] == "evidence"}
    result: dict[str, str] = {}
    for candidate in bundle["mappingCandidates"]:
        names = [evidence[e["id"]]["generationClass"] for e in candidate["evidence"] if e["id"] in evidence]
        result[candidate["id"]] = names[0] if names else "unknown"
    return result


def analyse(directory: Path, archive: Path, crosswalk: str) -> dict[str, Any]:
    _blind, key, independent = load(directory, crosswalk)
    classes = generation_classes(archive, crosswalk)

    agree_support = collections.Counter()
    agree_exact = collections.Counter()
    by_class = collections.defaultdict(lambda: {"rows": 0, "supportAgree": 0, "exactAgree": 0})
    # The judge baseline is measured on the same rows, never assumed.  A judge
    # verdict counts as a rejection here only if it named no relation.
    controls = {"rows": 0, "reviewerRejected": 0, "judgeVerdicts": 0, "judgeRejected": 0}
    recoverable = {"rows": 0, "reviewerSupports": 0, "examples": []}
    directness_admitted = collections.Counter()
    missing = 0

    for entry in key:
        row = independent.get(entry["row"])
        if row is None:
            missing += 1
            continue
        mine = row["verdict"]
        judges = [j["verdictRelation"] for j in entry["judges"]]
        outcomes = [j["outcome"] for j in entry["judges"]]
        cls = classes.get(entry["candidateId"], "unknown")

        for judge in judges:
            agree_support["match" if _supports(mine) == _supports(judge) else "differ"] += 1
            agree_exact["match" if mine == judge else "differ"] += 1
        by_class[cls]["rows"] += 1
        if all(_supports(mine) == _supports(j) for j in judges):
            by_class[cls]["supportAgree"] += 1
        if all(mine == j for j in judges):
            by_class[cls]["exactAgree"] += 1

        if cls in {"randomNegativeControl", "siblingDistractor"}:
            controls["rows"] += 1
            if not _supports(mine):
                controls["reviewerRejected"] += 1
            controls["judgeVerdicts"] += len(judges)
            controls["judgeRejected"] += sum(1 for judge in judges if not _supports(judge))

        both_supported = len(outcomes) == 2 and all(o == "supports" for o in outcomes)
        if both_supported and not entry["admitted"] and cls not in {"randomNegativeControl", "siblingDistractor"}:
            recoverable["rows"] += 1
            if _supports(mine):
                recoverable["reviewerSupports"] += 1
                if len(recoverable["examples"]) < 6:
                    recoverable["examples"].append({"row": entry["row"], "judges": judges, "independent": mine})

        if entry["admitted"]:
            directness_admitted[row["directness"]] += 1

    return {
        "crosswalk": crosswalk,
        "rowsMissing": missing,
        "supportAgreement": dict(agree_support),
        "exactAgreement": dict(agree_exact),
        "controls": controls,
        "recoverable": recoverable,
        "directnessOnAdmitted": dict(directness_admitted),
        "byGenerationClass": {name: dict(value) for name, value in sorted(by_class.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--crosswalk", action="append", choices=list(CROSSWALKS))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    results = []
    for crosswalk in args.crosswalk or list(CROSSWALKS):
        path = args.review / "independent" / f"{crosswalk}.jsonl"
        if not path.exists():
            print(f"  {crosswalk}: no independent decisions yet, skipping")
            continue
        entry = analyse(args.review, args.archive, crosswalk)
        entry["independentDigest"] = _digest(path)
        results.append(entry)

        support = entry["supportAgreement"]
        exact = entry["exactAgreement"]
        total = support["match"] + support["differ"]
        controls = entry["controls"]
        recoverable = entry["recoverable"]
        direct = entry["directnessOnAdmitted"]
        admitted = sum(direct.values()) or 1
        print(f"\n=== {crosswalk}   (missing rows: {entry['rowsMissing']})")
        print(f"  support agreement vs sealed judges : {support['match']}/{total} ({support['match'] / total:.1%})")
        print(f"  exact relation agreement           : {exact['match']}/{total} ({exact['match'] / total:.1%})")
        print(
            f"  controls rejected by reviewer      : {controls['reviewerRejected']}/{controls['rows']} "
            f"({controls['reviewerRejected'] / max(controls['rows'], 1):.1%})   "
            f"[sealed judges: {controls['judgeRejected']}/{controls['judgeVerdicts']} "
            f"({controls['judgeRejected'] / max(controls['judgeVerdicts'], 1):.1%})]"
        )
        print(
            f"  recoverable rejections confirmed   : {recoverable['reviewerSupports']}/{recoverable['rows']} "
            f"({recoverable['reviewerSupports'] / max(recoverable['rows'], 1):.1%})   "
            f"[reviewer support, not a recovery count — see replay_atlas_crosswalk_admission.py]"
        )
        print(
            f"  directness on admitted mappings    : "
            f"direct={direct.get('direct_candidate', 0)}/{admitted} ({direct.get('direct_candidate', 0) / admitted:.1%})"
        )
        print("  by generation class:")
        for name, value in entry["byGenerationClass"].items():
            rows = value["rows"] or 1
            print(
                f"     {name:<26} n={value['rows']:<4} support={value['supportAgree'] / rows:6.1%} "
                f"exact={value['exactAgree'] / rows:6.1%}"
            )

    if args.output and results:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"results": results}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
