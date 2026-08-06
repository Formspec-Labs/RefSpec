"""Seal a blind audit of the orthographic variant classifier.

E-V5's classifier decides, for each ``editDistanceNearMiss`` candidate, whether
the two labels differ for a *reason* -- number agreement, diacritics, a known
US/UK spelling -- or whether they merely happen to be two edits apart.  That
decision now drives an admission rule (R4), so it is load-bearing, and it is
made by string heuristics: case folding, one English pluralisation rule, and a
ten-entry rewrite table.  Heuristics that small are exactly the kind that look
right on the examples their author checked.

The audit asks a reviewer the same question from the other direction -- from what
the labels *mean* as English rather than from what the strings do -- with the
classifier's answer withheld.  Two disagreement types matter and they matter
differently:

*False principled* is the dangerous one.  A coincidence promoted to "real
variant" enters the graph through R4 as a granularity-collapsed mapping.

*False unprincipled* is merely wasteful.  A real variant demoted to coincidence
loses a candidate the generator restriction would have kept.

The population is a census: all 165 edit-distance candidates, in an order
derived from the labels rather than from the classifier's verdict, so the
strata cannot be read off the file.

Read-only.  Reads the replay evidence for the classifier's verdicts and the
benchmark sets for the labels; writes only the audit directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SETS = ("positives", "hard-negatives", "controls", "disputed")
EDIT_DISTANCE_CLASS = "editDistanceNearMiss"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def collect(benchmarks: Path, replay: Path) -> list[dict[str, Any]]:
    """Every edit-distance candidate, joined to the classifier's verdict."""
    verdicts = {
        (entry["crosswalk"], entry["row"]): entry["variantClass"]
        for entry in json.loads(replay.read_text(encoding="utf-8"))["editDistanceHygiene"]["rows"]
    }
    rows: list[dict[str, Any]] = []
    for name in SETS:
        for line in (benchmarks / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row["generationClass"] != EDIT_DISTANCE_CLASS:
                continue
            key = (row["crosswalk"], row["row"])
            if key not in verdicts:
                raise RuntimeError(f"no classifier verdict for {key}")
            rows.append(
                {
                    "crosswalk": row["crosswalk"],
                    "sourceRow": row["row"],
                    "sourceLabel": row["sourceLabel"],
                    "targetLabel": row["targetLabel"],
                    "variantClass": verdicts[key],
                    "set": row.get("set", name),
                }
            )
    # Order by the labels themselves: reproducible, and uncorrelated with the
    # verdict being withheld.
    return sorted(rows, key=lambda entry: (entry["sourceLabel"].lower(), entry["targetLabel"].lower()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--benchmarks", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True, help="admission replay JSON carrying per-row variant classes")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = collect(args.benchmarks, args.replay)
    blind = [{"row": index, "a": row["sourceLabel"], "b": row["targetLabel"]} for index, row in enumerate(rows, start=1)]
    sealed = [
        {"row": index, "crosswalk": row["crosswalk"], "sourceRow": row["sourceRow"], "variantClass": row["variantClass"], "set": row["set"]}
        for index, row in enumerate(rows, start=1)
    ]

    blind_bytes = (_canonical({"rows": blind}) + "\n").encode("utf-8")
    key_bytes = (_canonical({"rows": sealed}) + "\n").encode("utf-8")
    (args.output / "blind").mkdir(parents=True, exist_ok=True)
    (args.output / "sealed-key").mkdir(parents=True, exist_ok=True)
    (args.output / "blind" / "pairs.json").write_bytes(blind_bytes)
    (args.output / "sealed-key" / "pairs.json").write_bytes(key_bytes)

    census: dict[str, int] = {}
    for row in sealed:
        census[row["variantClass"]] = census.get(row["variantClass"], 0) + 1
    manifest = {
        "type": "AtlasVariantClassifierAuditManifest",
        "experiment": "E-V5 classifier validation",
        "rows": len(blind),
        "blindDigest": _digest(blind_bytes),
        "keyDigest": _digest(key_bytes),
        "classifierCensus": census,
        "note": (
            "Blind rows carry the two labels and nothing else. The classifier's verdict, the "
            "candidate's admission outcome and its benchmark set are in sealed-key/ and must not be "
            "opened before the audit is recorded. Order is by label and carries no signal."
        ),
    }
    (args.output / "manifest.json").write_text(_canonical(manifest) + "\n", encoding="utf-8")
    print(f"  rows={len(blind)}  classifier census={census}")
    print(f"  blind={manifest['blindDigest'][:23]}…  key={manifest['keyDigest'][:23]}…")
    print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
