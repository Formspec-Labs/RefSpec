# Unit A — reg-shaped citations truncating at the dot: declared receipt deltas

Mined ledger item 3 (`research/investigations-mined-2026-08-31.md` ~lines
68–76, `inv-universe` shape (a)). Fix: `src/refspec/registry/citation_grammar.py`.

## Measurement method

`measure_baseline.py` first replayed the **current** (unfixed)
`parse_authority_citation` over every distinct `authority_text` in the
shipped artifact and flagged every usc citation whose matched
`usc_section` sits directly before a literal `".<digit>"` in the raw text —
the truncation signature — regardless of which reader produced it (not just
the hand-written `pat_a` regex the original inv-universe scratch scripts
used, which only caught the anchored `title USC part.section` shape).

`measure_deltas.py` then diffs the OLD (HEAD, pre-fix) and NEW (this fix)
`citation_grammar` module **in isolation** — not "new grammar vs. what the
artifact currently stores" — over every distinct `authority_text`, and joins
the removed `(usc_title, usc_section)` pairs back to the live artifact rows.
Diffing in isolation matters: the shipped artifact is built by
`unified_agenda_parquet.py`, which layers further correction/enlargement
rules (B8, the #46 fences, `usc_section_corrected`, …) on top of the raw
grammar read. An early pass of this script compared the new grammar directly
against the artifact's *stored* `usc_section` and found 1,404 "lost" rows —
almost all of them completely unrelated authority values (`10 U.S.C. 218`,
`31 U.S.C. 301`, …) whose value the grammar was never touching; that drift
belongs to other, already-shipped fixes built into the artifact after this
grammar's last commit, not to this change. The isolated old-vs-new diff is
the only comparison that isolates what *this* fix moves.

**Re-running `measure_deltas.py` now reports zero rows, and that is
expected.** Its second stage joins the removed pairs back to the artifact,
and the working tree's `output/` artifact was rebuilt on 2026-09-01 with
this fix already in it: checked 2026-09-01, all 41 removed
`(authority_text, usc_title, usc_section)` pairs are now absent from
`unified_agenda_legal_authorities.parquet`, while the surviving `322`/`5331`
rows of the specimen below are still there. `lost_rows.json` and
`removed_pairs.json` beside this file are the pre-rebuild join, and they are
the record of what moved.

## Measured population (trust this over the mined doc's 155/77/19)

| metric | measured |
|---|---|
| distinct `authority_text` losing a fabricated `(title, section)` pair | **41** |
| rows carrying one of those pairs | **175** |
| distinct RINs | **36** |
| of those rows, current `usc_section_verdict == "exists"` (false affirmatives) | **89** rows / 23 RINs |
| of those rows, `authority_in_own_cfr_note == "present"` (exact ground truth in the RIN's own `CFR_LIST`) | **15** rows / 7 RINs |
| `usc_section_verdict` breakdown of all 175 lost rows | `exists`: 89, `unknown`: 52, `absent`: 34 |
| unexpected NEW `(title, section)` pairs the fix adds anywhere in the 42,677-value corpus | **0** — confirmed by a full old-vs-new replay of every distinct authority value (`compare_grammar.py`, run from the scratchpad), not just the 41 affected ones |

The mined doc's 155/77/19 came from a narrower, hand-written regex
(`pat_a` in `research/evidence/investigations-2026-08-24/inv-universe/scratch/step2_shape_a.py`)
that matches only the anchored `title USC part.section` spelling. Our
measurement replays the grammar itself and so also catches truncation at
`_USC_APPENDIX`'s section slot (`46 app USC 1241.1`, 1 row) and the list
member `40 U.S.C. 102.01, 322, 5331` loses only its first member (see
below) — a different, smaller and more precisely-scoped population than a
regex written against the raw text would find. Trust this number; the query
is `measure_deltas.py`.

## One case corrects a member rather than dropping a whole citation

`('2105-AE58', '201804', '40 U.S.C. 102.01, 322, 5331')` keeps `322` and
`5331` as separate list-tail rows — only the fabricated `102` (truncated
from `102.01`) is withheld. This is exactly why `_USC_STANDARD`'s own
anchor keeps matching (see the code comment at its `section` group): a full
regex-level refusal there would have taken `usc_matches` down with it, and
`_USC_LIST_TAIL`'s scan is seeded from that match's own span — losing 322
and 5331 along with the fabricated 102.

### What the raw record says, read AROUND the match

**Corrected 2026-09-01.** An earlier draft of this file stopped at
`CFR_LIST`, concluded "`102.01` corroborates nothing — it is genuinely
fabricated", and was wrong. Reading the record around the match, and the
publisher's note for the part it names, says something more specific:

- `output/registry-real-data-sources/unified-agenda-editions/REGINFO_RIN_DATA_201804.xml`
  line ~141247: `CFR_LIST` is `49 CFR 40`, and this RIN files **two**
  authority boxes — `40 U.S.C. 102.01, 322, 5331` and, immediately beside
  it, `40 U.S.C. 31306 and 54101 et seq.`
- This repository's own pinned note for that exact part
  (`research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl`,
  `cfr_title=49`, `cfr_part="40"`) reads in full:
  `Authority: 49 U.S.C. 102, 301, 322, 5331, 20140, 31306, and 54101 et seq.`

The filer's two boxes together reproduce the publisher's list member for
member — 102 · 301 · 322 · 5331 · 31306 · 54101 et seq., with `20140` the
only one missing — under the **wrong title**, 49 written as 40. The damage
is a wrong TITLE over an entirely real title-49 list, not a section number
invented from nothing, and the `322`/`5331` this fence keeps are the real
members that stood behind the damaged one.

A second witness inside the corpus: the SAME box in this RIN's two earlier
editions is spelled with a **comma** — `40 U.S.C. 102,01, 322, 5331`
(`REGINFO_RIN_DATA_201704.xml` line 146748 and the 201710 edition, both
with the same `CFR_LIST` and the same second box). A comma there is a list
separator, which is what the publisher's note has at that position
("102, 301"); the 201804 spelling is the same token with its separator
damaged into a dot.

### The residual this fence does not reach, named

Refusing `40:102` removes a false affirmative — 40 U.S.C. 102 is a real
section, so the row read `exists`. What survives is still wrong in a way no
dot fence can see:

| surviving row | current `usc_section_verdict` | what the note grants |
|---|---|---|
| `40:322` | `exists` | a wrong-TITLE affirmative: 49 U.S.C. 322 |
| `40:5331` | `absent` | title 40 has no 5331; 49 U.S.C. 5331 is real |

That is the same residual class Unit B documents for 8 CFR 281: an oracle
answers "does this identity exist", never "did the filer mean this
identity". Repairing a stated TITLE is a different unit from refusing a
truncated SECTION, and this is the second one. Two further rows sit in the
same class by construction — the comma-spelled editions above mint `40:102`
AND `40:1` (both real title-40 sections, both reading `exists`), and a
comma is not the shape this fence guards.

Verdicts measured 2026-09-01 with `UscSectionOracle.from_repository(".")`:
`40:102` and `40:322` exist and are enumerated, `40:5331` is neither;
`49:102`, `49:301`, `49:322`, `49:5331`, `49:20140` and `49:31306` all exist
and are enumerated.

## The one measured exception: not a truncation

`5 USC 552a.45 CFR s 5b.11(b) (2)(ii)(H)` (RIN 0938-AO69, publication
200610) is the **only** value in the whole 42,677-value corpus where a
dotted number is immediately followed by an explicit CFR citation. `552a`
is the Privacy Act — a real, complete, standalone U.S.C. section — and the
filer ran a second citation (`45 CFR 5b.11(b)(2)(ii)(H)`, corroborated by
this RIN's own `CFR_LIST`, `45 CFR 5b` — see
`output/registry-real-data-sources/unified-agenda-editions/REGINFO_RIN_DATA_200610.xml`
line 82048) directly against the first with no separator. The fix carries a
named exception for exactly this shape; this row does **not** appear in the
41/175 population above (confirmed: `parse_authority_citation` still emits
`usc_title=5, usc_section='552a'` unchanged before and after).

## Declared verdict/census key movement

After the combined rebuild, `unified_agenda_parquet.py`'s by-status verdict
census and any RIN-level `usc_section_verdict` rollup should show, for the
175 rows in `lost_rows.json`:

- **89 rows** move OFF an affirmative `exists` verdict for a fabricated
  section (23 RINs). These rows either disappear entirely from the usc
  family for that authority value (40 of 41 texts) or survive under a
  correct, narrower reading (`40 U.S.C. 102.01, 322, 5331`, 1 text, keeping
  322/5331).
- **34 rows** move off `absent`, **52** off `unknown` — these were already
  non-affirmative, so no verdict-census cell they fed reported a false
  positive; removing them changes population counts in the `partial`
  `(authority_type, parse_status)` shape bucket
  (`unified_agenda_parquet.py` ~8571–8584) but not the `exists` cell.
- **15 rows** (7 RINs) had `authority_in_own_cfr_note == "present"` —
  exact corroboration in the RIN's own `CFR_LIST` that the fabricated usc
  reading was wrong and a CFR reading was right; these are the strongest
  specimens for a follow-on unit that mints the CFR identity these rows now
  correctly decline to mint as USC.
- Every row that survives (322, 5331 for RIN 2105-AE58) is unchanged in
  verdict — the fix only removed the fabricated 102 member, not the row's
  other citations.

No row's `usc_section_verdict` flips to a DIFFERENT existing section
(exists→exists on a different number) — the fix only removes rows, it never
mints a new (title, section) pair anywhere in the corpus (confirmed: 0 added
pairs in the full 42,677-value replay).

## Builder-side changes declared for the integrator

None required to ship this fix's own correctness — the grammar refusal is
self-contained and the artifact will simply carry 175 fewer fabricated `usc`
rows once rebuilt. Two things worth the integrator's attention:

1. `unified_agenda_parquet.py` ~4260–4280 carries the shape-(a) FOURTH
   comment describing the OLD (list-tail-only) dotted-fence scope as current
   fact; it needs updating once this fix lands (Lane 2 does not own that
   file).
2. The 15 rows with `authority_in_own_cfr_note == "present"` are exact,
   corroborated CFR identities the grammar now correctly declines to mint as
   USC — a natural follow-on unit (out of scope here) would read these as
   CFR citations instead of leaving them `other`/`failed`.
