"""Query the PINNED usc-act-index-2026-08-22 artifact directly for each of the
118 initialism tokens found in pop_b_per_token.json.

Read-only / import-only: never calls usc_act_index.build() or main(); only
imports refspec.registry.act_resolution / citation_grammar and reads the
sealed parquet tables with pyarrow. Run with the repo's src on sys.path.

Three checks per token, run against output/usc-act-index-2026-08-22:
  1. paren_hit   -- the token appears as a parenthetical "(TOKEN)" inside the
                     RAW `name` or `see_also` text of some popular-name row
                     (content_type == "cite" rows only, since those are the
                     rows that carry a table3_key).
  2. name_row_hit -- normalize_popular_name(token) is itself a listed
                     name_key (a "separate name row": the initialism, alone,
                     is how OLRC titled some act's popular-name entry).
  3. resolve_hit  -- resolve_act_name(token, index) succeeds end to end
                     (exercises normalize_popular_name + alias-chasing +
                     year-supplying exactly as a real citation would).

Ambiguity: how many DISTINCT table3_keys the paren-hit / name-row-hit rows
name (not just what resolve_act_name picked, since ActIndex.from_artifact
keeps only the first via setdefault).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path("/Users/mikewolfd/Work/RefSpec")
sys.path.insert(0, str(REPO / "src"))

from refspec.registry.act_resolution import ActIndex, resolve_act_name  # noqa: E402
from refspec.registry.citation_grammar import normalize_popular_name  # noqa: E402

import pyarrow.parquet as pq  # noqa: E402

ACT_INDEX_DIR = REPO / "output/usc-act-index-2026-08-22"
EVID = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-initialisms")
POP_B = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-acts/pop_b_per_token.json")


def main() -> None:
    per_token = json.loads(POP_B.read_text())["per_token"]
    tokens = sorted(per_token.keys())
    assert len(tokens) == 118, f"expected 118 tokens, got {len(tokens)}"

    # Load via the PRODUCTION loader -- this is what resolve_act_name actually
    # queries (pin-verified, alias map built, year-supplying map built).
    index = ActIndex.from_artifact(ACT_INDEX_DIR)

    # Also load the RAW table directly, for the parenthetical scan and for
    # counting ambiguity independently of the loader's setdefault-first choice.
    raw_rows = pq.read_table(ACT_INDEX_DIR / "usc-popular-names.parquet").to_pylist()
    cite_rows = [r for r in raw_rows if r["content_type"] == "cite" and r["table3_key"]]

    results = {}
    for token in tokens:
        row_count = per_token[token]["row_count"]
        norm = normalize_popular_name(token)

        # --- 1. parenthetical scan over raw name/see_also text -------------
        paren_pat = re.compile(r"\(\s*" + re.escape(token) + r"\s*\)")
        paren_hits = []
        for r in cite_rows:
            for field in ("name", "see_also"):
                val = r.get(field) or ""
                if paren_pat.search(val):
                    paren_hits.append({"field": field, "value": val, "table3_key": r["table3_key"],
                                        "name_key": r["name_key"], "content_type": r["content_type"]})
                    break

        # --- 2. token itself, normalized, is a listed name_key --------------
        name_row_hits = [r for r in cite_rows if r["name_key"] == norm]
        # also check non-cite rows (a "see" entry with no table3_key of its own)
        any_row_same_key = [r for r in raw_rows if r["name_key"] == norm]

        # --- 3. production resolver, called with the bare token -------------
        resolved_act_key = resolve_act_name(token, index)
        resolved_table3_key = index.table3_key_by_name.get(resolved_act_key) if resolved_act_key else None

        distinct_table3_keys = sorted({h["table3_key"] for h in paren_hits} | {r["table3_key"] for r in name_row_hits})

        results[token] = {
            "token": token,
            "row_count": row_count,
            "normalized": norm,
            "paren_hits": paren_hits,
            "name_row_hits": [{"name_key": r["name_key"], "table3_key": r["table3_key"], "name": r["name"]}
                               for r in name_row_hits],
            "any_row_same_key_non_cite": [{"name_key": r["name_key"], "content_type": r["content_type"],
                                            "see_also_key": r["see_also_key"]}
                                           for r in any_row_same_key if r["content_type"] != "cite"],
            "resolved_act_key": resolved_act_key,
            "resolved_table3_key": resolved_table3_key,
            "distinct_table3_keys_from_direct_hits": distinct_table3_keys,
            "ambiguous": len(distinct_table3_keys) > 1,
            "any_index_hit": bool(paren_hits or name_row_hits or resolved_act_key),
        }

    (EVID / "act_index_query_results.json").write_text(json.dumps(results, indent=2, sort_keys=True))

    # Compact table to stdout.
    hits = [t for t in tokens if results[t]["any_index_hit"]]
    misses = [t for t in tokens if not results[t]["any_index_hit"]]
    print(f"tokens: {len(tokens)}  index-hit: {len(hits)}  no-hit: {len(misses)}")
    print()
    print(f"{'token':12} {'rows':>4} {'paren':>5} {'nameRow':>7} {'resolve':>7} {'amb':>3}  act_key")
    for t in tokens:
        r = results[t]
        print(f"{t:12} {r['row_count']:>4} {len(r['paren_hits']):>5} {len(r['name_row_hits']):>7} "
              f"{'Y' if r['resolved_act_key'] else '.':>7} {'Y' if r['ambiguous'] else '.':>3}  "
              f"{r['resolved_act_key'] or ''}")


if __name__ == "__main__":
    main()
