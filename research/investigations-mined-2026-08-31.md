# The investigations, mined: what landed, what didn't, what's false

2026-08-31. Four parallel deep reviews walked all sixteen directories of
`research/evidence/investigations-2026-08-23/` and `-2026-08-24/` against the
shipped code and the rebuild-#12 artifact, re-measuring every population
rather than trusting the READMEs. The artifact used for measurement is
byte-verified: its receipt and both table digests reproduce all 81 lines of
`investigations-2026-08-24/units-grammar/rebuild12-delta.txt`, the unit
authors' own before/after record.

Two corrections to how these directories read from the outside, first:
`units-grammar/` is not an investigation but the implementation evidence of
three units that ARE shipped (the slash reader, the range tails, the #46
fences), and several defects the READMEs describe in present tense are
already fixed — the Title 3 compilation-locator misread, the in-list range
tails, the compound-name endpoints, the prose-"to" backtrack, cross-family
bleed. Sections below say "landed" only where a reviewer verified the fix in
the code and the artifact, with the numbers.

## How to read the file citations below

Nothing in these directories is referenced by shipped code, and under this
repository's rule that is correct until the moment it stops being true: a
reference is a promotion, and a promotion means the digest-pin ceremony the
initialism roster, the authority-notes cache and the section oracle each
went through (dated evidence home, pinned bytes, a reader, a receipt line,
a test that breaks). The ground-truth files cited per item below are the
PROMOTION CANDIDATES for that ceremony — when a fix is implemented, its set
is re-derived against the then-current build, diffed against the
investigation copy to prove the re-derivation didn't drift, and pinned
fresh. The hand-verified specimen files (checked against the publisher by a
person, so they do not go stale when a build moves) become corpus cases and
negative fixtures directly. The large derived dumps were deliberately NOT
committed: they are snapshots of tables rebuild #12 has already moved, and
their producing scripts are committed beside where they stood.

## Not landed, silent — ranked by blast radius

These publish a wrong or misleading value today with no refusal beside it.

1. **The B8 two-witness rule** (`inv-b8`). `NNN(x)` read as section `NNN`
   where `NNNx` is also real: 14,740 readings / 2,641 RINs, the largest
   silent class both surveys found. PUBLISH = subsection-oracle witness AND
   (the part's authority note names `NNNx` OR a sibling edition spells it):
   1,171 readings / 1,166 rows, every one reading `exists` today, 65 already
   caught by B1 → **1,101 net new**. B8 is deliberately candidate-only in the
   oracle (`usc_section_oracle.py` `CANDIDATE_ONLY_RULES`, demoted
   2026-08-23) — the enlargement belongs in the builder, where both witness
   feeds already exist (`held_by_rule`, `_CitationHistory.usc`). Two riders:
   1,276 `LONE:B8` rows appear in neither the correction census nor the
   refusal census (survivors are only computed when there are ≥2 candidates);
   and 147 readings have the note naming bare `NNN` — 8 of those would still
   publish via the edition witness and need a deliberate decision.
2. **LANDED 2026-08-31 (wave, Lane A) — the section oracle's annual-archive extractor is case-sensitive**
   (`inv-2012`). Generation-2 oracle re-pinned: 1,882 usc rows + 16 act-relative rows
   attested (not 1,912 — the review's figure bundled a 30-row "uncertain" bucket that
   correctly does not flip), 0 verdict changes. The review of that unit found a second,
   pre-existing extractor semantic — OLRC's bracket-prefixed repealed/omitted stubs —
   and it is EXCLUDED ON PURPOSE (REF-059). Original item kept below for the record. `extract_annual.py` matches `2010usc12.htm` but not
   `2010USC12.htm`; twelve publisher volumes were never read (titles
   12/13/14/51 @2010, 33/35–41 @2012). **1,912 of the 8,261**
   `exists`-but-unattested rows (404 pairs, 559 RINs; title 12 @2010 alone is
   1,368) are extractor holes, not history. Fix = `re.IGNORECASE`,
   re-extract the 31 already-downloaded zips, re-pin the oracle tables,
   re-baseline. The caveat is recorded at the pin in
   `tests/test_unified_agenda_parquet.py` (search "CAVEAT (measured
   2026-08-31") until the unit lands.
3. **Reg-shaped citations in the U.S.C. slot truncate at the dot**
   (`inv-universe` shape a). `26 USC 1.104-1(c)` is an income-tax
   *regulation*; the grammar publishes 26 U.S.C. §1 and the oracle confirms
   it exists. 155 rows / 31 RINs, **77 with an affirmative `exists` on the
   wrong section**, 19 with exact ground truth in the RIN's own `CFR_LIST`.
   The detector is proven: no real U.S.C. identity contains a dot (checked
   against all 66,780 enumerated pairs). The shipped dotted fence is scoped
   to the list tail only, on the stated assumption that an anchored dotted
   number stays visibly `partial` — measured false.
4. **Statutes-at-Large page lists read as U.S.C. sections in the note
   reader** — a new find of this review, in no README. `"101 Stat. 1568,
   1608"` emits `usc 12:1608`: **148 fabricated citations across 80 of the
   8,240 notes**, 100 nonexistent identities. Nine corpus rows flip verdict
   when removed — eight are filer boxes carrying the *same* parser bug as
   the note, so the answer key "corroborates" a shared typo. A sibling of
   the three #46 fences, in a class they never covered; the trap is real
   (`14 CFR 121`'s note genuinely resumes a U.S.C. list after a Stat page),
   so gate on the oracle rather than on "everything after Stat.".
5. **MODULE LANDED 2026-08-31 (wave, Lane D), fence wiring pending — no Executive Order existence oracle** (`inv-eo`, `inv-eo-gap`). `eo_roster.py` ships the window-split oracle (REF-057); the `eo_in_known_series` fence upgrade is a follow-up unit with its spec at `research/evidence/eo-roster-2026-08-31/WIRING-SPEC.md`. The rider below was WRONG: EO 8284 exists (NARA's 1939 table, 4 FR 4603), and the review caught it. Original item kept for the record. The
   only fence is `EO_HIGHEST_KNOWN`; **43 unresolved numbers / 2,876 rows**
   pass it and read as valid citations, and 16,684 EO rows are the
   second-largest unjudged family in the note census. The built roster
   (5,693 numbers) plus the gap closure (all 32 numbers, 1990–93) would
   affirm 377 of 391 cited numbers / 18,951 of 19,011 rows, leaving 11
   numbers honestly `unknown`. Design constraint the README omits: the
   FR-API window (12890–14420) is fully dense and may publish `absent`; the
   NARA codification window (9–12667) is 32.9% dense and may only affirm —
   wiring without that split mints false `absent`s. Rider: EO 8284 is the
   publisher's own probe-negative (NARA `not_found`) published as a good
   citation on 3 rows; the 8284→8248 correction currently rests partly on a
   Wikipedia tie-break and should ship as a flag, not a correction.
6. **Degenerate range endpoints** (`inv-dropped` residue). `16 USC 773 to
   773(k)`: strip the pinpoint and start == end, so the ordering rule
   declines and the span vanishes with no refusal counter — 55 texts / 280
   rows. Same family: the **appendix pattern has no range tail** (a stated
   `KNOWN GAP` block in `citation_grammar.py`, 50 texts / 266 rows), and
   **compound-stem shorthand never expands** (`12 USC 1715z to 11a`, 41
   texts / 106 rows; plain-stem residue 13 texts / 48 rows).
7. **`present-by-stem` note verdicts** (`inv-note-present`). 223 rows earn
   `present` — the column's strongest signal — from a note token that is
   oracle-`absent` and uncorroborated (74/80 identities are the Exchange
   Act §78 superscript-typesetting family); 79 are clean filer citations
   witnessed only by a damaged token. Needs a fourth verdict value, never a
   silent demotion.
8. **No FR page fence on the timetable table** (`inv-frvol`). 223 timetable
   rows cite an FR page beyond the volume's real last page — 116 beyond
   even `FR_PAGE_HIGHEST_KNOWN` (`63 FR 726116`) — all `ok`, no column, no
   census. The per-volume last-page roster (91 rows, sha256-pinned) sits
   unbound; `TIMETABLES_SCHEMA` has no in-series columns at all.
9. Small and named: **`BIPA' 00`** publishes `act_section='00'` (the year) —
   1 row, named a defect in the builder's own comment, ~3-line guard
   (**LANDED 2026-08-31**, with the apostrophe-year shape);
   **Title-3 compilation PAGES** still mint 12 CFR "parts" (the #46 fence
   stopped the years, not the pages); **`attested_at_edition` has no reason
   code** — four mechanically distinct facts share one `false`; the **C3
   tail bug** (`c3_proposals` drops a stated hyphen tail exactly as B8's
   1735f-14 lesson warned) is latent — zero production callers — but primed
   to go silent the day C3 is promoted (**LANDED 2026-08-31**: tail retained
   occurrence-by-occurrence, and C3 now has a production caller — the
   paren-suffix promotion below).

## Not landed, loud — additive work, no wrong answer today

> **Wave 2026-08-31 (Lane B) landed the first five of these** — the six retiers
> (raw-verified quote by quote; MIPPA re-derived at 29 with the tie-break now
> documented), the apostrophe-year shape, `usc_slot_reading`, the paren-suffix
> promotion (bound to the row's own citation occurrence: 200 promoted, 21
> unbound, 17 stated-tail refusals, 1,179 witnessless kept refused), and the
> placeholder candidates (two-witness intersection, oracle-refuted candidates
> dropped, dated PL gate). The `none-off-form` severity split (27 / 62 / 41)
> shipped as a recorded finding, not a column: it needs a RIN-timeline
> completion classifier that is its own unit. `ABSTRACT` exposure and the
> descending-span refusal remain open. Original entries kept for the record.

- **Six initialism-roster retiers** (`inv-62` Piece A): MMA@0917,
  NDAA-17@0720, MIPPA@0938, NEPA@0412, ARRA@0412, UMTRCA@2060 each have a
  pinned FR quote binding the token at the agency, but still sit
  `candidate-index-match` in `initialism-roster-2026-08-24/roster.csv` — 95
  rows that simulate clean through the shipped fence. A data edit plus
  rebuild. INA@1205 honestly stays a candidate.
- **The apostrophe-year shape** (`inv-62` Piece B): `BBA '97`, `BBRA'99`,
  `BIPA '00` — 33 rows, all loud-failed today, all resolve with one token
  shape; the two-digit-year suppressor the corroborator needs already
  exists. **OBRA '93** needs one year-keyed roster row (machinery exists).
- **`usc_slot_reading`** (`inv-universe` design): a typed column naming the
  four non-U.S.C. numbering universes in the U.S.C. slot. Only shape (a)
  needs a *fix* (item 3 above); reg-suffix `472-8` (190 rows, all Treasury,
  witnessed exactly by `CFR_LIST`) and chapter-in-slot (1,690 candidate
  rows) need a *name*. Witness ranking measured: structured `CFR_LIST`
  beats note free text 2.4×. Bare-OSHA needs nothing — 0 misreads.
- **The paren-eaten-lettered-suffix promotion** (`inv-47`): 209 rows loudly
  `absent` where exactly one enumerated fused reading exists (`15 USC
  78(d)` → `78d`); requires the C3 tail fix first, and 1,186 witnessless
  rows must keep refusing. Parens on *both* range endpoints (15 rows) rides
  along. Row-collapse in the grammar is real but its keyable blast radius
  is 1 row, not the README's 107 — the table carries no pinpoint depth.
- **The placeholder candidates** (`inv-placeholders`): per-record candidate
  authorities for all 12,467 unstated rows (witness coverage 87.2 / 75.8 /
  43.1% by kind), consumed by nothing. A future column needs the two-witness
  intersection as its publishable tier plus a note-date-vs-edition-year gate
  (a 2007 placeholder was offered 2020 Public Laws by a 2026 note — the one
  trap direction nothing currently caveats). The `none-off-form` severity
  split (27 never published / 62 published without CFR / 41 completed with
  real CFR impact behind a bare "None") is measured and unshipped.
- **`ABSTRACT` is not exposed** by the edition reader; `inv-acts` used it as
  an anchor oracle for 250 initialism signals (46 resolve). 31.9% of
  abstracts are HTML (99% by 202510), so the reader needs an HTML path.
- A named refusal for descending/garbled spans (231 rows silently-correct
  today), and counting a lone candidate-only survivor in the correction
  refusal census (the `LONE:B8` hole above).

## Falsified prose in digest-pinned modules

> **All five corrected 2026-08-31** with the units that touched their modules:
> the 2012-gap prose (extractor holes vs genuine title-52/54 gaps), the
> mojibake claim (re-measured: 1,407 U+0096/97 occurrences across 11 elements
> INCLUDING `LEGAL_AUTHORITY`; 1,205 across the 10 others), the oracle
> docstring (generation 2 reads every volume it holds; bracketed stubs
> excluded on purpose), and MIPPA's `rows_observed` (29 stands — the
> first-recognized-token tie-break, now documented). `unified_agenda_editions.py`'s
> mojibake line is still open: no unit touched that module this wave.

Every one of these files is content-hashed into the artifact receipt's
producer block, so even a comment edit forces a rebuild: fix these WITH the
next unit that touches the module, never as a drive-by.

- `unified_agenda_parquet.py` (~3824): calls the 2012 gap "the oracle's own
  coverage hole" over "titles 33-41, 52 and 54" — merging the fixable
  extractor bug (33, 35–41) with genuine title-creation gaps (52, 54).
- `unified_agenda_editions.py` (66–70): "not systematic mojibake" — cp1252
  C1 bytes appear in 31 of 60 editions, 11,914 occurrences; the claim
  survives only for the C0 characters XML forbids.
- `citation_grammar.py` (~407–410): "the bytes appear in no other Agenda
  field" — `U+0096/97` appear in 11 elements, 1,407 occurrences (identities
  are unaffected; `_DASHES` already folds them).
- `usc_section_oracle.py` docstring: "every year 1994–2024" — untrue until
  the extractor fix re-reads the twelve uppercase volumes.
- `initialism-roster-2026-08-24/roster.csv`: MIPPA@0938 `rows_observed` says
  29; the corpus and the artifact both measure 26.

## Durability

Sixteen of the 32 EO-gap numbers — 1,173 corpus rows, EO 12866 among them —
resolve only from Wayback captures of NARA pages now dead on the live site
(every non-1989–92 year route serves one identical stub; verified by
digest). Those bytes exist nowhere but `inv-eo-gap/` and `inv-eo/`, both
committed with sha256 manifests. Treat those directories as pinned publisher
evidence, not as prunable research.

## Landed and verified — do not re-litigate

The slash unit (1,428 corroborated / 280 refused by name, all 14 traps
held), the in-list range tails (3,841 of 3,880 rows recovered),
compound-name endpoints (485 of 491), the prose-"to" atomic group, spelled
shorthand on plain stems, the endpoint-existence gate, all three #46 fences
including the repeated-year Comp. variant and cross-family bleed (1,282
citations in 806 notes stopped arriving), inv-29's continuation families
(67 records, exactly), all four inv-31 hypotheses (H1 join 219/586, H2
title-carry 111, H3, H4 one-edit 48), both inv-acts populations
(sibling-act carry 34; the roster's four evidence tiers), the full
inv-initialisms token set (118/118 in the roster, downgrades all traced to
evidence kind), mid-list ellipsis handling, and the `none-off-form` kind
itself. inv-48 is a stale full-suite capture superseded by later pins; its
one durable signal (the three `test_fast_*` tests cost ~570s of the audit
tier) stands on its own.
