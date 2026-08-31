"""Population B, row-level tally: roster vs abstract-alone vs neither, and
whether the ABSTRACT-glossed expansion is itself in the act index."""
from __future__ import annotations

import json
import sys
from collections import Counter

sys.path.insert(0, "/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-acts")
from common import (  # noqa: E402
    EVID,
    AbstractCache,
    abbrev_survivors,
    abstract_glosses,
    build_roster,
    candidate_initialisms,
    load_act_index,
    load_rows,
)
from refspec.registry.act_resolution import resolve_act_name  # noqa: E402

rows = load_rows()
keys_by_rin, keys_by_agency = build_roster(rows)
index, credits = load_act_index()
abscache = AbstractCache()

pop_b_rows = [
    r for r in rows
    if (r["authority_type"] == "other" and r["parse_status"] == "failed")
    or (r["authority_type"] == "act_relative" and r["parse_status"] == "failed" and r["stated_section"])
]

cat_counts = Counter()
examples = {"roster": [], "abstract_alone": [], "neither": []}
neither_token_freq = Counter()
abstract_alone_details = []

for r in pop_b_rows:
    toks = sorted(set(candidate_initialisms(r["authority_text"])))
    if not toks:
        cat_counts["no_token"] += 1
        continue
    rin_pool = keys_by_rin.get(r["rin"], set())
    agency_pool = keys_by_agency.get(r["rin"][:4], set())
    abstract_text = abscache.get(r["rin"], r["publication_id"])
    glosses = abstract_glosses(abstract_text)

    roster_hit = any(abbrev_survivors(t, rin_pool) or abbrev_survivors(t, agency_pool) for t in toks)
    abstract_hit_tokens = [t for t in toks if t in glosses]

    if roster_hit:
        cat_counts["roster"] += 1
        if len(examples["roster"]) < 5:
            examples["roster"].append((r["rin"], r["publication_id"], r["authority_text"]))
    elif abstract_hit_tokens:
        cat_counts["abstract_alone"] += 1
        for t in abstract_hit_tokens:
            name = glosses[t]
            resolved = resolve_act_name(name, index)
            abstract_alone_details.append(
                {
                    "rin": r["rin"], "publication_id": r["publication_id"],
                    "text": r["authority_text"], "token": t,
                    "abstract_name": name, "in_act_index": resolved,
                }
            )
        if len(examples["abstract_alone"]) < 5:
            examples["abstract_alone"].append((r["rin"], r["publication_id"], r["authority_text"]))
    else:
        cat_counts["neither"] += 1
        for t in toks:
            neither_token_freq[t] += 1
        if len(examples["neither"]) < 5:
            examples["neither"].append((r["rin"], r["publication_id"], r["authority_text"]))

print("POP_B_ROWS total:", len(pop_b_rows))
print("category counts:", dict(cat_counts))
print("\nexamples:")
for cat, exs in examples.items():
    print(f" {cat}:")
    for rin, pid, text in exs:
        print("   ", rin, pid, repr(text))

print("\ntop tokens driving the NEITHER bucket:")
for tok, n in neither_token_freq.most_common(25):
    print(f"  {tok:10s} {n:4d}")

print("\nabstract-alone details (token bound from record's own ABSTRACT):")
for d in abstract_alone_details:
    print(" ", d)

with (EVID / "pop_b_rowlevel.json").open("w") as fh:
    json.dump(
        {
            "pop_b_rows": len(pop_b_rows),
            "category_counts": dict(cat_counts),
            "examples": examples,
            "neither_token_freq_top25": neither_token_freq.most_common(25),
            "abstract_alone_details": abstract_alone_details,
        },
        fh,
        indent=2,
        default=str,
    )
print("\nwrote", EVID / "pop_b_rowlevel.json")
