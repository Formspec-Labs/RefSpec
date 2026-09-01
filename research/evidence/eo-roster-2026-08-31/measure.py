"""Read-only measurement: how many CITED EO numbers/rows does the roster affirm?

Re-measures what ``research/investigations-mined-2026-08-31.md`` item 5
predicted:

    "The built roster (5,693 numbers) plus the gap closure (all 32 numbers,
    1990-93) would affirm 377 of 391 cited numbers / 18,951 of 19,011 rows,
    leaving 11 numbers honestly unknown."

and reports the delta rather than asserting the prediction. This roster
affirms one more number than that: EO 8284, which the mined note's source had
wrongly doubted on a route-level 404 (see README.md).

Every input is bound by digest before it is read -- this lane's own
``derived/roster.csv`` against the pin in
``src/refspec/registry/eo_roster.py``, and the investigation's census against
the manifest that investigation committed. A measurement over unchecked bytes
measures whatever the bytes happen to say today.

An earlier draft also read ``inv-eo/derived/join-not-exists.csv`` for its
human-readable category labels. That file is NOT in the investigation's own
manifest, so this script no longer reads it: the categories it supplied are
re-derived here from the oracle's own verdicts, which are manifested all the
way down.

The ceiling that separates "already out of series" from "honestly unknown"
comes from the oracle's own measured bound (``eo_roster.FR_API_DENSE_MAX``),
never a literal 14,420 restated here.
"""

from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
INV_EO = REPO_ROOT / "research/evidence/investigations-2026-08-24/inv-eo"

sys.path.insert(0, str(REPO_ROOT / "src"))
from refspec.registry.eo_roster import (
    FR_API_DENSE_MAX,
    NARA_CODIFICATION_WINDOW,
    EoRosterOracle,
)


def manifested_rows(root: Path, relative: str, manifest: Path) -> list[dict[str, str]]:
    """Rows of one manifested CSV, refusing unless its bytes match the digest."""

    expected = {
        row["relative_path"]: (int(row["bytes"]), row["sha256"])
        for row in csv.DictReader(manifest.open(newline=""))
    }
    if relative not in expected:
        raise SystemExit(f"{relative} is not manifested under {root}; nothing to measure")
    payload = (root / relative).read_bytes()
    observed = (len(payload), hashlib.sha256(payload).hexdigest())
    if observed != expected[relative]:
        raise SystemExit(f"{relative} drifted from its manifest: {observed} != {expected[relative]}")
    return list(csv.DictReader(payload.decode("utf-8").splitlines()))


def main() -> None:
    # The roster is read THROUGH the shipped oracle, so this script measures
    # the same verdicts a consumer gets -- pin check, window coherence,
    # density verification and all -- rather than a second reading of the CSV.
    oracle = EoRosterOracle.from_repository(REPO_ROOT)

    manifest = INV_EO / "derived/MANIFEST-sha256.csv"
    census = manifested_rows(INV_EO, "derived/cited-eo-census.csv", manifest)

    row_count = {int(row["eo_number"]): int(row["row_count"]) for row in census}
    verdicts = {number: oracle.verdict(number) for number in row_count}
    covered = [n for n, v in verdicts.items() if v.verdict == "exists"]
    uncovered = [n for n, v in verdicts.items() if v.verdict != "exists"]

    print(f"cited numbers (cited-eo-census.csv): {len(row_count)}")
    print(f"total cited rows: {sum(row_count.values())}")
    print(f"roster size (this lane's re-derivation): {len(oracle._rows)}")
    print()
    print(f"COVERED (verdict=exists): {len(covered)} numbers / {sum(row_count[n] for n in covered)} rows")
    print(f"UNCOVERED: {len(uncovered)} numbers / {sum(row_count[n] for n in uncovered)} rows")
    print()
    print("Uncovered numbers, by the reason the oracle itself gives:")
    by_reason: dict[str, list[int]] = {}
    for n in uncovered:
        by_reason.setdefault(verdicts[n].reason or verdicts[n].verdict, []).append(n)
    for reason, numbers in sorted(by_reason.items()):
        rows = sum(row_count[n] for n in numbers)
        print(f"  {reason!r}: {len(numbers)} numbers / {rows} rows -> {sorted(numbers)}")

    already_out_of_series = [n for n in uncovered if n > FR_API_DENSE_MAX]
    honestly_unknown = [n for n in uncovered if n <= FR_API_DENSE_MAX]
    print()
    print(
        f"Of the {len(uncovered)} uncovered, {len(already_out_of_series)} exceed the oracle's own "
        f"measured ceiling ({FR_API_DENSE_MAX:,}) and are ALREADY flagged False by today's "
        f"eo_in_known_series fence (eoOutOfSeriesRows) -- not new "
        f"information: {sorted(already_out_of_series)}"
    )
    print(
        f"The remaining {len(honestly_unknown)} are in-range numbers the roster does not resolve -- "
        f"the 'honestly unknown' residual: {sorted(honestly_unknown)} "
        f"({sum(row_count[n] for n in honestly_unknown)} rows)"
    )

    on_roster = set(oracle._rows)
    low, high = NARA_CODIFICATION_WINDOW
    dense = sum(1 for n in range(low, high + 1) if n in on_roster)
    print()
    print(
        f"NARA codification window [{low}, {high}]: {dense} of {high - low + 1} numbers on the "
        f"roster = {100 * dense / (high - low + 1):.1f}% dense (affirm-only)"
    )
    print(
        f"EO 8284: verdict={verdicts[8284].verdict} source={verdicts[8284].source} "
        f"-- a real order (4 FR 4603) whose per-order NARA route 404s"
    )

    mined_expects = {"numbers_covered": 377, "rows_covered": 18_951, "numbers_unknown": 11}
    measured = {
        "numbers_covered": len(covered),
        "rows_covered": sum(row_count[n] for n in covered),
        "numbers_unknown": len(honestly_unknown),
    }
    print()
    print(f"mined expectation: {mined_expects}")
    print(f"measured (this script): {measured}")
    print(
        "delta: "
        + ", ".join(f"{k} {measured[k] - mined_expects[k]:+d}" for k in mined_expects)
        + " -- EO 8284 moved from unknown to exists on the pinned NARA 1939 table"
    )


if __name__ == "__main__":
    main()
