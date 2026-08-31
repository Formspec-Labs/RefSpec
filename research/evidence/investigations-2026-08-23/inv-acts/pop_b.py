"""Population B: unresolved initialisms in other/failed legal-authority rows."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-acts")
from common import (  # noqa: E402
    EVID,
    AbstractCache,
    abbrev_survivors,
    abstract_glosses,
    act_initialism,
    build_roster,
    candidate_initialisms,
    load_act_index,
    load_rows,
    resolve_one,
)
from refspec.registry.act_resolution import resolve_act_name  # noqa: E402
from refspec.registry.citation_grammar import normalize_popular_name  # noqa: E402

rows = load_rows()
keys_by_rin, keys_by_agency = build_roster(rows)
index, credits = load_act_index()

pop_b_rows = [
    r for r in rows
    if (r["authority_type"] == "other" and r["parse_status"] == "failed")
    or (r["authority_type"] == "act_relative" and r["parse_status"] == "failed" and r["stated_section"])
]
print("POP_B_ROWS:", len(pop_b_rows))

# per-row candidate tokens (deduplicated within the row)
row_tokens: list[tuple[dict, list[str]]] = []
freq = Counter()
example_by_token: dict[str, dict] = {}
rows_with_any_token = 0
for r in pop_b_rows:
    toks = sorted(set(candidate_initialisms(r["authority_text"])))
    if toks:
        rows_with_any_token += 1
    row_tokens.append((r, toks))
    for t in toks:
        freq[t] += 1
        example_by_token.setdefault(t, r)

print("rows with >=1 candidate initialism token:", rows_with_any_token)
print("distinct initialism tokens:", len(freq))

top40 = freq.most_common(40)
print("\nTOP 40 initialisms by row frequency:")
for tok, n in top40:
    ex = example_by_token[tok]
    print(f"  {tok:10s} {n:5d}  RIN {ex['rin']} / {ex['publication_id']}  {ex['authority_text']!r}")

# --- for EVERY distinct token: roster? abstract? act-index-name?
abscache = AbstractCache()

per_token: dict[str, dict] = {}
rows_by_token: dict[str, list[dict]] = defaultdict(list)
for r, toks in row_tokens:
    for t in toks:
        rows_by_token[t].append(r)

resolvable_by_roster_rows = 0
resolvable_by_abstract_rows = 0
resolvable_by_neither_rows = 0
seen_rows_resolved = set()  # row identity to avoid double counting a row matched on 2 tokens

for tok, occurrence_rows in rows_by_token.items():
    entry = {"token": tok, "row_count": len(occurrence_rows)}
    # roster check: RIN-level then agency-level, exact-initials then anchored-subsequence
    roster_hit = None
    for r in occurrence_rows:
        rin_pool = keys_by_rin.get(r["rin"], set())
        agency_pool = keys_by_agency.get(r["rin"][:4], set())
        survivors = abbrev_survivors(tok, rin_pool) or abbrev_survivors(tok, agency_pool)
        if survivors:
            roster_hit = sorted(survivors)
            break
    entry["in_roster_example_survivors"] = roster_hit
    entry["in_roster_any_row"] = roster_hit is not None

    # roster-resolvable ROWS: for each occurrence row individually (its own
    # rin/agency pool), not just "does some row's pool answer"
    roster_resolvable_rows = 0
    for r in occurrence_rows:
        rin_pool = keys_by_rin.get(r["rin"], set())
        agency_pool = keys_by_agency.get(r["rin"][:4], set())
        survivors = abbrev_survivors(tok, rin_pool) or abbrev_survivors(tok, agency_pool)
        if survivors:
            roster_resolvable_rows += 1
    entry["roster_resolvable_rows"] = roster_resolvable_rows

    # abstract-binding check: does the record's OWN abstract define this token?
    abstract_defs = []
    abstract_resolvable_rows = 0
    for r in occurrence_rows:
        abstract_text = abscache.get(r["rin"], r["publication_id"])
        glosses = abstract_glosses(abstract_text)
        if tok in glosses:
            abstract_defs.append((r["rin"], r["publication_id"], glosses[tok]))
            abstract_resolvable_rows += 1
    entry["abstract_defines_any_row"] = bool(abstract_defs)
    entry["abstract_examples"] = abstract_defs[:3]
    entry["abstract_resolvable_rows"] = abstract_resolvable_rows

    # is the expanded name (from abstract, if any) in the act index?
    in_act_index_names = set()
    for _, _, name in abstract_defs:
        resolved = resolve_act_name(name, index)
        if resolved:
            in_act_index_names.add(resolved)
    entry["abstract_name_in_act_index"] = sorted(in_act_index_names)

    per_token[tok] = entry

with (EVID / "pop_b_per_token.json").open("w") as fh:
    json.dump(
        {
            "pop_b_rows": len(pop_b_rows),
            "rows_with_any_token": rows_with_any_token,
            "distinct_tokens": len(freq),
            "top40": [{"token": t, "rows": n, "example": {"rin": example_by_token[t]["rin"], "publication_id": example_by_token[t]["publication_id"], "text": example_by_token[t]["authority_text"]}} for t, n in top40],
            "per_token": per_token,
        },
        fh,
        indent=2,
        default=str,
    )
print("\nwrote", EVID / "pop_b_per_token.json")
