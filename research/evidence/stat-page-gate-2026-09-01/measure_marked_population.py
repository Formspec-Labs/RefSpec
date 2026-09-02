"""Measure every usc_section_after_statute=True citation the grammar marks.

Reads the pinned note cache and the shipped artifact, and writes two JSONs
beside itself in this directory -- nothing else. Replays
refspec.registry.citation_grammar.parse_authority_citation
over (a) every one of the 8,240 pinned eCFR authority notes and (b) every
distinct authority_text value in the shipped Unified Agenda artifact, and
reports every citation the grammar marks as "reached a U.S.C. list member
after scanning past a Statutes-at-Large citation" -- the lexical fact Unit
B's fix adds (mined ledger item 4, research/investigations-mined-2026-08-31.md
~lines 77-85).

Marking is NOT gating: this script does not consult the section-existence
oracle. It measures the POPULATION the note-side gate (cfr_authority_notes.
read_note_citations) and the not-yet-built filer-side gate must judge.
"""
import collections
import json

import duckdb

from refspec.registry.citation_grammar import parse_authority_citation
from refspec.registry.cfr_authority_notes import note_body

NOTES = "research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl"
ART = "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"


def marked_citations(text):
    return [c for c in parse_authority_citation(text) if c.authority_type == "usc" and c.usc_section_after_statute]


# -- notes ------------------------------------------------------------- #
note_hits = []
with open(NOTES) as f:
    for line in f:
        rec = json.loads(line)
        body = note_body(rec["authority_note"])
        marked = marked_citations(body)
        if marked:
            note_hits.append(
                {
                    "cfr_title": rec["cfr_title"],
                    "cfr_part": rec["cfr_part"],
                    "note": rec["authority_note"],
                    "marked": [(c.usc_title, c.usc_section) for c in marked],
                }
            )

print("== notes ==")
print("notes carrying >=1 marked citation:", len(note_hits))
print("total marked citations across notes:", sum(len(h["marked"]) for h in note_hits))

with open("research/evidence/stat-page-gate-2026-09-01/marked_notes.json", "w") as f:
    json.dump(note_hits, f, indent=2, default=str)

# -- filer authority_text (the "8 filer boxes" the mined ledger names) -- #
con = duckdb.connect(":memory:")
rows = (
    con.execute(
        f"""
        select rin, publication_id, authority_text
        from '{ART}'
        where authority_text is not null
        """
    )
    .arrow()
    .read_all()
    .to_pylist()
)
distinct_texts = sorted({r["authority_text"] for r in rows})
text_hits: dict[str, list] = {}
for text in distinct_texts:
    marked = marked_citations(text)
    if marked:
        text_hits[text] = [(c.usc_title, c.usc_section) for c in marked]

print()
print("== filer authority_text ==")
print("distinct authority_text carrying >=1 marked citation:", len(text_hits))
print("total marked citations across authority_text:", sum(len(v) for v in text_hits.values()))

matching_rows = [r for r in rows if r["authority_text"] in text_hits]
print("rows carrying one of those authority_text values:", len(matching_rows))
print("distinct RINs:", len({r["rin"] for r in matching_rows}))

with open("research/evidence/stat-page-gate-2026-09-01/marked_filer_texts.json", "w") as f:
    json.dump({t: v for t, v in text_hits.items()}, f, indent=2, default=str)
