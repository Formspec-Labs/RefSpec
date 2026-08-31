"""H1 accounting with the builder's stated_* post-step applied to the joined
text, and honest cell arithmetic."""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: F401,E402  (puts src on the path)

from refspec.registry.citation_grammar import stated_act_name, stated_section  # noqa: E402

S = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch")
runs_a = json.loads((S / "h1_runs_a.json").read_text(encoding="utf-8"))


def with_stated(new: list[dict], joined: str) -> list[dict]:
    """The builder writes stated_act_name/stated_section onto every emitted row
    from the box's own text, unless an act key resolved. Apply the same step to
    the joined text so the comparison is builder-to-builder."""
    an, sn = stated_act_name(joined), stated_section(joined)
    out = []
    for d in new:
        e = dict(d)
        if not e.get("act_key"):
            if e.get("stated_act_name") is None and an is not None:
                e["stated_act_name"] = an
            if e.get("stated_section") is None and sn is not None:
                e["stated_section"] = sn
        out.append(e)
    return out


def k(d: dict) -> tuple:
    return tuple(sorted(d.items()))


rows_base = rows_base_silent = rows_base_valued = 0
rows_survive = rows_vanish = rows_arrive = 0
cells_base = cells_survive = 0
lost_cols = collections.Counter()
kinds = collections.Counter()
loss_runs: list[dict] = []

for r in runs_a:
    joined = ", ".join(r["boxes"])
    new = with_stated(r["new"], joined)
    old = r["old"]
    newk = collections.Counter(k(d) for d in new)
    vanished_here = []
    for d in old:
        rows_base += 1
        silent = d.get("authority_type") == "other" or "corroborated" in d
        rows_base_silent += silent
        rows_base_valued += not silent
        cells = {c: v for c, v in d.items() if c != "authority_type"}
        cells_base += len(cells)
        if newk.get(k(d)):
            newk[k(d)] -= 1
            rows_survive += 1
            cells_survive += len(cells)
        else:
            rows_vanish += 1
            vanished_here.append(d)
            best = max(new, key=lambda e: sum(1 for c, v in d.items() if e.get(c) == v),
                       default={})
            for c, v in d.items():
                if best.get(c) != v:
                    lost_cols[c] += 1
    rows_arrive += sum(newk.values())
    real_loss = [d for d in vanished_here if d.get("authority_type") not in (None, "other")
                 and "corroborated" not in d]
    kind = "LOSS" if real_loss else ("GAIN" if sum(newk.values()) else "NEUTRAL")
    kinds[kind] += 1
    if kind == "LOSS":
        loss_runs.append({**r, "new_with_stated": new, "lost": real_loss})

print("=== Tier A, builder-level comparison (stated_* applied to the joined text) ===")
print(f"runs: {len(runs_a):,}  {dict(kinds)}")
print(f"baseline rows inside a run:                     {rows_base:,}")
print(f"  read as nothing today:                        {rows_base_silent:,}")
print(f"  carry a reading today:                        {rows_base_valued:,}")
print(f"rows whose full reading survives verbatim:      {rows_survive:,}")
print(f"rows whose reading does not survive verbatim:   {rows_vanish:,}")
print(f"rows the join adds:                             {rows_arrive:,}")
print(f"row count in these runs: {rows_base:,} -> {rows_survive + rows_arrive:,}")
print()
print(f"non-NULL value cells on baseline rows (excl. authority_type): {cells_base:,}")
print(f"  reproduced verbatim:                                        {cells_survive:,}")
print(f"  NOT reproduced (an EXISTING non-NULL value moves):           {cells_base - cells_survive:,}")
print("columns of the non-reproduced cells:")
for c, n in lost_cols.most_common(20):
    print(f"  {c:<34} {n:>6,}")
print()
print(f"runs that LOSE a real reading: {len(loss_runs)}")
(S / "h1_loss_runs.json").write_text(json.dumps(loss_runs, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
for r in loss_runs[:14]:
    print(" -", r["boxes"])
    print("    lost:", r["lost"])
    print("    new :", r["new_with_stated"])
