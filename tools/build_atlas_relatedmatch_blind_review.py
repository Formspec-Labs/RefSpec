"""Seal a blind sample for the judged half of E-V4 and the framing half of E-V2.

Every one of the 35 admitted ``relatedMatch`` mappings is included -- a census of
the population under test, not an estimate -- alongside matched distractors
stratified by generation class and unlabelled random-negative and sibling
controls, so the sample's composition cannot be read off it; rows carry only the
concept facts the sealed judges saw, with admitted relation, generation class,
variant class, admission status, set membership, and provider identity withheld
into the sealed key, and presentation order is by task id. Each row asks
``basisOfAssociation`` (conceptual connection versus label likeness) and
``bestRelation``; the planned neutral and adversarial passes share one model
family, so agreement measures framing sensitivity and inter-annotator stability,
not cross-family agreement. Read-only: no relation is asserted, no benchmark set
is modified, and in particular the 86 disputed rows are not touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

CROSSWALKS = ("fr-elsst", "fr-icpsr", "elsst-icpsr")
SETS = ("positives", "hard-negatives", "controls", "disputed")

#: Fields a reviewer may see.  Anything outside this set is withheld into the key.
CONCEPT_FIELDS = ("prefLabel", "altLabels", "definition", "scopeNote", "vocabulary")

RELATED = "relatedMatch"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def load_population(benchmarks: Path, review: Path) -> dict[tuple[str, int], dict[str, Any]]:
    """Join benchmark decisions to the concept facts the sealed judges were shown."""
    population: dict[tuple[str, int], dict[str, Any]] = {}
    for name in SETS:
        for line in (benchmarks / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row["set"] = name
                population[(row["crosswalk"], row["row"])] = row
    for crosswalk in CROSSWALKS:
        blind = json.loads((review / "blind" / f"{crosswalk}.json").read_text(encoding="utf-8"))
        for entry in blind["rows"]:
            key = (crosswalk, entry["row"])
            if key in population:
                population[key]["facts"] = entry
    missing = [key for key, row in population.items() if "facts" not in row]
    if missing:
        raise RuntimeError(f"{len(missing)} rows have no concept facts; first few: {missing[:5]}")
    return population


def select(population: dict[tuple[str, int], dict[str, Any]], *, distractors_per_class: int, controls: int) -> list[tuple[str, int]]:
    """Census of ``relatedMatch``, plus stratified distractors and unlabelled controls.

    Deterministic throughout: selection is by sorted key, never by sampling, so
    the sealed sample is reproducible from the archive alone.
    """
    chosen: list[tuple[str, int]] = []

    chosen.extend(
        sorted(key for key, row in population.items() if row["set"] == "positives" and row.get("admittedRelation") == RELATED)
    )

    # Distractors are drawn per generation class so the mix cannot be read off the
    # sample: every class that contributes a relatedMatch also contributes others.
    for cls in sorted({population[key]["generationClass"] for key in chosen}):
        others = sorted(
            key
            for key, row in population.items()
            if row["set"] == "positives" and row["generationClass"] == cls and row.get("admittedRelation") != RELATED
        )
        chosen.extend(others[:distractors_per_class])

    for kind in ("randomNegativeControl", "siblingDistractor"):
        seeded = sorted(key for key, row in population.items() if row["generationClass"] == kind)
        chosen.extend(seeded[: controls // 2])

    # Presentation order must not correlate with membership, or the reviewer can
    # read the strata off the file.  Sort by task id: stable, and unrelated to
    # every field the key withholds.
    return sorted(set(chosen), key=lambda key: population[key]["facts"]["taskId"])


def build(population: dict[tuple[str, int], dict[str, Any]], keys: list[tuple[str, int]]) -> tuple[list[dict], list[dict]]:
    blind: list[dict[str, Any]] = []
    sealed: list[dict[str, Any]] = []
    for index, key in enumerate(keys, start=1):
        row = population[key]
        facts = row["facts"]
        blind.append(
            {
                "row": index,
                "source": {field: facts["source"][field] for field in CONCEPT_FIELDS if field in facts["source"]},
                "target": {field: facts["target"][field] for field in CONCEPT_FIELDS if field in facts["target"]},
            }
        )
        sealed.append(
            {
                "row": index,
                "crosswalk": row["crosswalk"],
                "sourceRow": row["row"],
                "candidateId": row["candidateId"],
                "set": row["set"],
                "generationClass": row["generationClass"],
                "admittedRelation": row.get("admittedRelation"),
                "sealedJudges": row["sealedJudges"],
                "priorIndependentVerdict": row["independentVerdict"],
            }
        )
    return blind, sealed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--benchmarks", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True, help="atlas-crosswalk-blind-review-2026-08-06 (for concept facts)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--distractors-per-class", type=int, default=12)
    parser.add_argument("--controls", type=int, default=24)
    args = parser.parse_args()

    population = load_population(args.benchmarks, args.review)
    keys = select(population, distractors_per_class=args.distractors_per_class, controls=args.controls)
    blind, sealed = build(population, keys)

    blind_bytes = (_canonical({"rows": blind}) + "\n").encode("utf-8")
    sealed_bytes = (_canonical({"rows": sealed}) + "\n").encode("utf-8")
    (args.output / "blind").mkdir(parents=True, exist_ok=True)
    (args.output / "sealed-key").mkdir(parents=True, exist_ok=True)
    (args.output / "blind" / "sample.json").write_bytes(blind_bytes)
    (args.output / "sealed-key" / "sample.json").write_bytes(sealed_bytes)

    composition = {
        "relatedMatchAdmissions": sum(1 for row in sealed if row["admittedRelation"] == RELATED),
        "otherAdmissions": sum(1 for row in sealed if row["set"] == "positives" and row["admittedRelation"] != RELATED),
        "controls": sum(1 for row in sealed if row["set"] == "controls"),
    }
    manifest = {
        "type": "AtlasRelatedMatchBlindReviewManifest",
        "experiments": ["E-V4 (judged half)", "E-V2 (framing and agreement half)"],
        "rows": len(blind),
        "blindDigest": _digest(blind_bytes),
        "keyDigest": _digest(sealed_bytes),
        "composition": composition,
        "note": (
            "Blind rows carry only concept facts. Admitted relation, generation class, variant class, "
            "set membership and prior verdicts are in sealed-key/ and must not be opened before "
            "decisions are recorded. Presentation order is by task id and carries no signal."
        ),
        "limitation": (
            "Both planned passes use the same model family, so agreement between them measures framing "
            "sensitivity and inter-annotator stability, not cross-family agreement."
        ),
    }
    (args.output / "manifest.json").write_text(_canonical(manifest) + "\n", encoding="utf-8")
    print(f"  rows={len(blind)}  {composition}")
    print(f"  blind={manifest['blindDigest'][:23]}…  key={manifest['keyDigest'][:23]}…")
    print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
