"""Cell-level accounting for the H1 join, plus the specimen lookups."""
from __future__ import annotations

import collections
import json
from pathlib import Path

S = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch")
runs_a = json.loads((S / "h1_runs_a.json").read_text(encoding="utf-8"))
runs_b = json.loads((S / "h1_runs_b.json").read_text(encoding="utf-8"))


def key(d: dict) -> tuple:
    return tuple(sorted(d.items()))


rows_baseline = 0
rows_baseline_silent = 0
rows_baseline_valued = 0
rows_survive = 0
rows_vanish = 0
rows_arrive = 0
value_cells_baseline = 0
value_cells_survive = 0
value_cells_lost = 0
lost_cell_cols = collections.Counter()
kinds = collections.Counter()

for r in runs_a:
    kinds[r["kind"]] += 1
    old, new = r["old"], r["new"]
    newk = collections.Counter(key(d) for d in new)
    for d in old:
        rows_baseline += 1
        is_silent = d.get("authority_type") == "other" or "corroborated" in d
        if is_silent:
            rows_baseline_silent += 1
        else:
            rows_baseline_valued += 1
        cells = {k: v for k, v in d.items() if k != "authority_type"}
        value_cells_baseline += len(cells)
        k = key(d)
        if newk.get(k):
            newk[k] -= 1
            rows_survive += 1
            value_cells_survive += len(cells)
        else:
            rows_vanish += 1
            # which of its cells no new row reproduces
            best = None
            for e in new:
                same = sum(1 for c, v in d.items() if e.get(c) == v)
                if best is None or same > best[0]:
                    best = (same, e)
            e = best[1] if best else {}
            for c, v in d.items():
                if e.get(c) != v:
                    lost_cell_cols[c] += 1
                    if c != "authority_type":
                        value_cells_lost += 1
    rows_arrive += sum(newk.values())

print("=== Tier A cell accounting ===")
print(f"runs:                                {len(runs_a):,}   ({dict(kinds)})")
print(f"baseline rows inside a run:          {rows_baseline:,}")
print(f"  reading as nothing today (other/failed or corroborated): {rows_baseline_silent:,}")
print(f"  carrying a reading today:                                 {rows_baseline_valued:,}")
print(f"rows whose FULL reading survives the join verbatim:         {rows_survive:,}")
print(f"rows whose reading does NOT survive verbatim:               {rows_vanish:,}")
print(f"rows the join ADDS (readings no box produced before):       {rows_arrive:,}")
print()
print(f"non-NULL value cells on baseline rows in a run (excl. authority_type): {value_cells_baseline - rows_baseline:,}")
print(f"  reproduced verbatim: {value_cells_survive - rows_survive:,}")
print(f"  NOT reproduced:      {value_cells_lost:,}")
print("columns of the non-reproduced cells:")
for c, n in lost_cell_cols.most_common(20):
    print(f"  {c:<34} {n:>6,}")
print()
print("=== Tier B ===")
print(f"runs {len(runs_b)}, boxes {sum(len(r['boxes']) for r in runs_b)}, "
      f"rows collapsed {sum(len(r['boxes']) for r in runs_b)} -> {len(runs_b)}")

# ---- specimens -------------------------------------------------------------
WANT = {("2126-AA63", "200010"), ("3052-AD44", "202210"), ("3052-AD42", "202210"),
        ("3072-AC96", "202304"), ("3072-AC38", "201010"), ("0936-AA07", "201710"),
        ("2060-AP43", "201004"), ("2126-AA64", "200404"), ("2126-AA64", "200410")}
print()
print("=== specimen membership ===")
for tier, runs in (("A", runs_a), ("B", runs_b)):
    for r in runs:
        if (r["rin"], r["pub"]) in WANT:
            print(f"  Tier {tier}  {r['rin']} {r['pub']} ord{r['first_ordinal']} "
                  f"kind={r.get('kind','-')} signals={r.get('signals','-')}")
            print(f"       boxes: {r['boxes']}")
            print(f"       new  : {r['new']}")
