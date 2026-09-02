"""Measure the reg-shaped dot-truncation population in the current build artifact.

Reads the shipped artifact and writes one JSON beside itself in this
directory, and nothing else. Replays
refspec.registry.citation_grammar.parse_authority_citation
over every distinct authority_text value in the shipped unified-agenda
parquet, and for every usc citation the grammar currently emits, checks
whether the matched section number sits directly before ".<digit>" in the
raw text -- the reg-shaped "NNN.NNN" truncation the mined ledger calls out
(item 3, research/investigations-mined-2026-08-31.md ~lines 68-76).

This is independent of the inv-universe scratch scripts (which used a
narrower hand-written regex, pat_a, matched only against the anchored
"title USC part.section" shape). Here we go straight at the grammar's own
output to find every position where a dot-followed section currently
truncate-publishes, not just the anchored one -- no pandas required, only
duckdb + pyarrow (both already vendored for this repo).
"""
import collections
import json
import re

import duckdb

from refspec.registry.citation_grammar import parse_authority_citation

ART = "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"

con = duckdb.connect(":memory:")
table = con.execute(
    f"""
    select rin, publication_id, authority_text, authority_type, parse_status,
           usc_title, usc_section, usc_section_verdict, authority_in_own_cfr_note,
           cfr_note_part
    from '{ART}'
    """
).arrow()
rows = table.read_all().to_pylist()
print("total rows:", len(rows))

distinct_texts = sorted({r["authority_text"] for r in rows if r["authority_text"]})
print("distinct authority_text:", len(distinct_texts))

# For each distinct text, replay the grammar and find usc citations whose
# matched section number sits directly before ".<digit>" in the raw text --
# the truncation signature -- regardless of which reader produced it.
dot_trunc_texts: dict[str, set[str]] = {}
for text in distinct_texts:
    try:
        citations = parse_authority_citation(text)
    except Exception as exc:  # pragma: no cover - measurement only
        print("EXC", text, exc)
        continue
    for c in citations:
        if c.authority_type != "usc" or c.usc_section is None:
            continue
        sec = c.usc_section
        for m in re.finditer(re.escape(sec) + r"\.\d", text):
            before = text[m.start() - 1] if m.start() > 0 else " "
            if before.isdigit():
                continue
            dot_trunc_texts.setdefault(text, set()).add(sec)

print("distinct authority_text with a dot-truncated usc_section:", len(dot_trunc_texts))

sub = [r for r in rows if r["authority_text"] in dot_trunc_texts and r["usc_section"] in dot_trunc_texts.get(r["authority_text"], set())]

print()
print("== rows / RINs / distinct texts (dot-truncated usc_section, whole corpus) ==")
print("rows:", len(sub))
print("distinct RINs:", len({r["rin"] for r in sub}))
print("distinct authority_text:", len({r["authority_text"] for r in sub}))
print()
print("== usc_section_verdict crosstab ==")
print(collections.Counter(r["usc_section_verdict"] for r in sub))
print()
print("== authority_in_own_cfr_note crosstab ==")
print(collections.Counter(r["authority_in_own_cfr_note"] for r in sub))
print()
print("== parse_status crosstab ==")
print(collections.Counter(r["parse_status"] for r in sub))

with open("research/evidence/reg-dot-fence-2026-09-01/baseline_dot_truncated_rows.json", "w") as f:
    json.dump(sub, f, indent=2, default=str)
