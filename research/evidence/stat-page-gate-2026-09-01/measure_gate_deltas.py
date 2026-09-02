"""What the section oracle RECOVERS, against this fix's OWN no-oracle default.

Reads only pinned artifacts -- the 8,240-note cache and the sealed section
oracle -- and writes one JSON beside itself in this directory. It rebuilds
nothing and writes nothing outside this directory.

Two builds of the real cache: one gated by the repository's oracle (the
production default) and one with ``oracle=None`` (the conservative fallback
:class:`CfrAuthorityNotes` degrades to on a tree carrying no oracle at all).

Only ONE direction of that comparison can be non-empty, and the script used
to print both. The no-oracle read withholds EVERY Statutes-at-Large-marked
citation, so its citation set is a subset of the gated one by construction:
a "refused" column here is empty whatever the gate does. It was -- an
always-``[]`` removed_citations.json and a metric that could not fail, which
is why it is gone rather than fixed. What this fix REFUSES is a question
about HEAD, and measure_deltas_vs_head.py is the script that asks it (266
citations across 107 notes).

The other direction is real: the marked citations the oracle AFFIRMS, which
the conservative default would have withheld -- 14 CFR 121's genuine 49
U.S.C. resume among them. That is the proof the gate works in both
directions rather than only refusing. This also re-derives the two pinned
literals in tests/test_cfr_authority_notes.py, so they are measured here
rather than typed by hand.
"""
import json

from refspec.registry.cfr_authority_notes import CfrAuthorityNotes, read_note_citations

REPO = "."

notes_gated = CfrAuthorityNotes.from_repository(REPO)
assert len(notes_gated.records) == 8_240

admitted_marked = []  # identities the grammar marked and the oracle affirmed
for gated in notes_gated.records:
    # ``CfrAuthorityNotes.from_file``/``from_repository`` load the repository's
    # own oracle when none is passed (that IS the production behavior), so the
    # "no oracle" side has to call read_note_citations directly -- the one
    # layer where ``oracle=None`` really means none.
    ungated_citations = read_note_citations(gated.authority_note, oracle=None)
    before = {c.identity for c in ungated_citations if c.family == "usc"}
    after = {c.identity for c in gated.citations if c.family == "usc"}
    for identity in after - before:
        admitted_marked.append((gated.cfr_title, gated.cfr_part, identity))
    assert not before - after, (gated.cfr_title, gated.cfr_part, before - after)

print("== what the oracle recovers, against a no-oracle default ==")
print("citations ADMITTED that a conservative default would withhold:", len(admitted_marked))
print("distinct notes gaining >=1 citation:", len({(t, p) for t, p, _ in admitted_marked}))
print()

total_gated = sum(len(n.citations) for n in notes_gated.records)
total_ungated = sum(len(read_note_citations(n.authority_note, oracle=None)) for n in notes_gated.records)
sections_gated = {c.identity.split(":", 1)[1] for n in notes_gated.records for c in n.citations if c.family == "usc"} | {
    c.span_end for n in notes_gated.records for c in n.citations if c.span_end
}
print("== pins for test_cfr_authority_notes.py ==")
print("total citations (gated, i.e. from_repository's real default):", total_gated)
print("total citations (ungated -- conservative, no oracle):", total_ungated)
print("distinct usc sections (gated):", len(sections_gated))

with open("research/evidence/stat-page-gate-2026-09-01/admitted_marked_citations.json", "w") as f:
    json.dump(admitted_marked, f, indent=2, default=str)
