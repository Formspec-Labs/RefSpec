# False presences beside detectable absences, 2026-08-23

Section H of `research/evidence/sample-review-2026-08-23/review.md` names the
hardest finding in the nine-class review: defects arrive in **runs**, and a
run that produces one detectable absent U.S.C. citation typically sits beside
siblings that are just as wrong but pass as `exists`, because the wrong
number is coincidentally real under the *stated* title too. Section E's
synthesis proposes the repair as a hypothesis ("list-coherence title
repair... catches the silent `40 U.S.C. 5103`") without measuring how often
it would fire correctly. This note measures two operationalisations of that
finding against the pinned artifacts, draws a hand-adjudicated sample from
the combined candidate population, and reports precision. Nothing here is
implemented as a check; the deliverable is counts and specimens.

**Verdict up front:** the false-presence population is real and larger than
zero, but the two predicates below are far from equally trustworthy. Run
coherence, measured exactly as stated, is dominated by numerical coincidence
(0/7 true positives in the hand sample). The stale-note shadow test is much
better once restricted to oracle-corroborated hits (4/5), and the
attested-after-edition test is the strongest predicate measured here (6/6).
Overall hand-verified precision across the combined candidate pool is **9/20
(45%)** — real, but well short of "the flagged rows are wrong."

## Data pinned

- `output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet`
  and `unified_agenda_cfr_references.parquet` — current build, receipt
  `outputs.unified_agenda_legal_authorities = sha256:4b4847e2f3e49d01e4f85ca151fd4689020b78d812a027543c416c8721b6b45a`,
  797,193 legal-authority rows across 60 editions (`receipt.json` read
  2026-08-23; this is the **current** artifact, distinct from the
  797,170-row copy measured by `usc-section-oracle-2026-08-22`).
- `research/evidence/usc-section-oracle-2026-08-22/usc-oracle-sections.parquet`
  (59,364 release-point rows, digest `f4b11c6e...`) and
  `usc-oracle-annual-sections.parquet` (1,565,007 rows spanning 1994-2024,
  digest `9ab9f43c...`) — read only, not modified. The existence set used
  throughout is their union restricted to non-appendix rows: **66,780
  distinct (title, section) pairs**, matching the oracle README's own
  headline number.
- `research/evidence/silent-misreads-2026-08-22/ecfr-authority-notes.jsonl`
  — 287 cached eCFR part authority notes, fetched 2026-08-20.
- `research/evidence/cfr-subject-index-2026-08-20/` — **not used**; see (c).

Measurement code is scratch, at `/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/`
(`run_coherence.py`, `note_extract.py`, `stale_note_shadows.py`,
`build_sample.py`); nothing was added to `src/`, `tests/`, `tools/`,
`portfolio/`, `bindings/`, or `output/`. `PYTHONDONTWRITEBYTECODE=1` for
every run. The Unified Agenda builder was not run.

## (a) Run coherence

**Definition.** A **run** is every `authority_type='usc'` row sharing one
`(rin, publication_id)`, restricted to rows with `usc_appendix` false or
null (appendix titles use a separate section space the oracle's non-appendix
union cannot judge; 72 of 33,017 rows in qualifying runs were appendix and
were dropped from run membership, not from the corpus). A run **qualifies**
if its non-null `usc_title` values are all equal (one stated title `T`) and
at least one row in it carries `usc_section_verdict = 'absent'`. For a
qualifying run, let its **sections** be the distinct `usc_section` string
values across the run (verbatim as parsed — ranges are not expanded; a row
parsed as `60108` with the text "60108 to 110" contributes only `60108`,
matching what the corpus itself stored in `usc_section_end` for that case,
which was `NULL`). The run is **coherent** if there exists **exactly one**
title `T' ≠ T` such that *every* section in the run is a member of the
66,780-pair oracle set under `T'` — exact string membership, not a
plausibility score. A **wrong-by-run row** is a row inside a coherent run
whose own `usc_section_verdict = 'exists'` (i.e. it silently passes under
the stated title `T`, while the run's own coherence says it belongs under
`T'`).

**Counts.**

| quantity | value |
|---|---:|
| non-appendix `usc` rows | 681,871 |
| qualifying runs (one title, ≥1 absent) | 6,272 |
| rows in qualifying runs | 32,940 |
| runs with **zero** titles covering every section | 4,344 |
| runs with **more than one** covering title (ambiguous, not coherent) | 1,517 |
| **coherent runs** (exactly one covering title) | **411** |
| rows inside coherent runs | 1,273 |
| **wrong-by-run rows** (verdict=exists inside a coherent run) | **691** |
| distinct RINs contributing those 691 rows | 59 |

**Top (stated → coherent other) title pairs**, by coherent runs:

| stated | other | runs | rows | wrong-by-run exists-rows |
|---:|---:|---:|---:|---:|
| 47 | 23 | 41 | 287 | 246 |
| 29 | 25 | 27 | 81 | 54 |
| 40 | 42 | 23 | 61 | 0 |
| 42 | 10 | 20 | 20 | 0 |
| 5 | 42 | 18 | 18 | 0 |
| 14 | 49 | 17 | 51 | 0 |
| 15 | 16 | 15 | 26 | 11 |
| 26 | 7 | 15 | 36 | 15 |
| 15 | 20 | 15 | 52 | 35 |
| 42 | 18 | 13 | 13 | 0 |
| 5 | 38 | 13 | 35 | 10 |
| 47 | 14 | 12 | 39 | 27 |
| 26 | 15 | 9 | 27 | 9 |
| 38 | 39 | 9 | 36 | 9 |
| 40 | 10 | 8 | 16 | 8 |

**Scope limitation found by closing the loop against the task's own named
examples.** "Spans one title" is a real restriction, not just a
convenience: it means a rule whose Legal Authority field correctly mixes
titles (cites some Title 14 sections, some Title 31, some Title 46, in one
field, all legitimately) never qualifies as a run at all, because its
non-null `usc_title` values are not all equal. Checking the task's other
two named specimens directly: **neither RIN 2115-AE94 (199510) nor RIN
0790-AK28 (201810) appears anywhere in the 691 wrong-by-run rows**, and not
because they're incoherent — they never qualify as runs. 2115-AE94's full
Legal Authority field is `31 USC 2103, 7101, 7107, 7306, 9701, 44 USC 3507,
46 USC 2103, 2110, 7301, 7302` — it spans titles 31, 44, **and** 46 in one
field (the review's own "the whole run except 9701 is title 46" is stated
against a background where the filer *also* correctly cited real Title 46
sections later in the same field), so the whole rule-edition is excluded
from this run-coherence test by construction. 0790-AK28/201810 mixes
Title 10 and Title 32 the same way. Recomputing the intersection by hand
for 2115-AE94's five Title-31-stated sections is instructive on its own:
`{2103,7101,7107,7306,9701}` are jointly covered not by Title 46 alone but
by **Title 15** (every one of the five is independently real somewhere
under Title 15 too) — a *second*, unrelated coincidental title, on top of
the mostly-Title-46 story the review already worked out by hand. This is
not a bug in the run-coherence test as specified — "spans one title" is
this note's own definition, following the task's instruction literally —
but it is a real scope gap: **4,010 rule-editions (36,757 rows) have a
mixed-title U.S.C. list with at least one absent row**, comparable in size
to the 6,272 single-title qualifying runs, and none of them were tested
here. A contiguous-same-title-sub-run variant (cluster consecutive ordinals
sharing a title, test each cluster separately, rather than requiring the
whole rule's list to be one title) would cover this population; it is not
built here.

**A known-good sanity check, and a known-bad one, both found before
sampling.** The predicate correctly reproduces review E's own seed case:
RIN 2137-AE60 (editions 201010, 201104), stated title 40, coherent other
title 49 — exactly "40 U.S.C. 5103, 60102 ... 60137" from the review. But the
single largest pair in the table, **47 → 23 (41 runs, 246 wrong-by-run
rows — 36% of the whole population)**, is one RIN: **3060-AG34**, an FCC
E911 rule, re-filed with an unchanged Legal Authority block across ~41
editions from 1996 onward. Its citations (`47 USC 151, 201, 208, 215, 303,
309`) are unambiguously correct Communications Act sections — confirmed
against the rule's own reginfo agenda pages (rows 15-17 below). Title 23 (Highways)
has been recodified enough times since 1958 that its debris of
repealed/renumbered low section numbers happens to cover the same six
integers by pure coincidence; the run only qualifies because its seventh
citation, `47 USC 134(i)`, is a genuine typo (parses as absent section
`134`; there is no §134, likely a slipped `154(i)`) unconnected to its six
correctly-cited siblings. This single RIN, repeated across decades of
biannual re-filing, is why raw row counts overstate the phenomenon; see
rows 15-17 in the sample below for how often this pattern recurs.

## (b) Stale-note shadows

**Scope.** A rule `(rin, publication_id)` is in scope if `≥1` of the CFR
parts it references (via `unified_agenda_cfr_references`, part numbers
normalised by stripping leading zeros) has a cached eCFR authority note.
121,728 rule-editions qualify; of the 665,356 non-appendix `exists` U.S.C.
rows in the corpus, **420,186** belong to an in-scope rule. Each cached
note's free text was parsed into a set of `(title, section)` pairs by a
purpose-built regex extractor (`note_extract.py`; validated against three
known notes, then patched for two real bugs found on a random sample — a
`re.sub`-with-stale-offsets corruption that mis-split hyphenated compound
sections like `77z-2`, and un-boundaried "CFR"/"Pub. L." clauses bleeding
digits into the preceding U.S.C. list — see the script's own docstring for
the residual known gap, a `sec. N(c), Pub. L. ...` forward reference the
extractor cannot scope). Where a rule cites more than one cached part, the
note pairs are unioned across parts.

**Sub-count 1 — shadow.** An `exists` row is a **shadow** if its own
`(usc_title, usc_section)` does **not** appear in the unioned note pairs,
while some **other** title `T' ≠ usc_title` with the same section string
**does**. Because a note's own text can itself be wrong (found twice below),
each shadow is additionally tagged **oracle-corroborated** when that
claimed `T'` pair is independently a real oracle pair (not just present in
the note's text).

| quantity | value |
|---:|---|
| shadow rows, raw | **726** |
| distinct RINs / distinct (rin, title, section) triples | 161 / 199 |
| of which oracle-corroborated | **558** |
| distinct RINs (corroborated) | 140 |

**Sub-count 2 — attested after edition.** For the same in-scope `exists`
rows, let `edition_year` be the first four digits of `publication_id`. Two
evidence classes:

- **dated**: the section's minimum year in `usc-oracle-annual-sections` is
  strictly after `edition_year` — **521 rows**.
- **undated / release-point-only**: the section never appears in *any*
  annual archive year (1994-2024) but does appear in the current release
  point **with `status='current'`**, and `edition_year ≤ 2024` — necessarily
  created later even though the exact year is unknown — **5 rows**.

| quantity | value |
|---:|---|
| **attested-after-edition rows, total** | **526** (521 dated + 5 undated) |
| distinct RINs | 114 |
| excluded: `edition_year = 2025`, never in annual (indeterminate direction) | 12 |
| excluded: release-point-only but **not** `status='current'` | **2,929** |

That last exclusion is load-bearing and was not obvious going in: a section
absent from every annual year is *not* proof it was created later. **18
U.S.C. 5006** (Federal Youth Corrections Act, repealed 1984, still printed
as a `status='repealed'` disposition stub in the current release point)
drove 1,138 of what would otherwise have been misread "created later" rows
— it is the opposite history, a pre-1994 repeal, not a post-2024 creation,
and the guard on `status='current'` removes it and 2,928 rows like it. This
is the same shape as the review's own "18 U.S.C. 3568... is not a misread"
caution in class H, discovered independently here by the undated bucket
being implausibly large (2,880 of 2,946 release-point-only rows, before the
status guard) before it was investigated.

## (c) Subject disjointness — out of scope

No subject oracle is pinned for this measurement. `cfr-subject-index-2026-08-20/part-subjects.csv`
maps CFR parts to subject headings, not U.S.C. sections to subject areas,
and using it to judge whether a cited section's *subject* belongs under the
rule's regulatory area would require a section-level (not part-level)
subject classification that does not exist in this tree. Not measured.

## The 20-row hand-adjudicated sample

**Pool.** The union of (a)'s 691 wrong-by-run rows, (b1)'s 726 raw shadow
rows, and (b2)'s 526 attested-after rows, deduplicated by
`(rin, publication_id, ordinal, citation_ordinal)`: **1,922 distinct rows,
329 distinct RINs** (overlap: 2 rows in both a and b1, 19 in both b1 and
b2, 0 in all three). Sorted by that same key for a deterministic order,
then `random.Random(20260823).sample(pool, 20)` — Python's Mersenne
Twister seeded exactly as specified; reproducible from the pinned parquets
and the note.

**Method.** Each row judged by its filer's verbatim `authority_text`, the
rule's reginfo.gov agenda entry at
`https://www.reginfo.gov/public/do/eAgendaViewRule?pubId={edition}&RIN={rin}`
(fetched live, 2026-08-23), the relevant cached CFR authority note where
applicable, and the Code (uscode.house.gov / Cornell LII / the oracle
parquets) — never by re-running the grammar or trusting the predicate that
selected the row.

| # | RIN · edition | predicate(s) | filer's text (verbatim) | verdict |
|---|---|---|---|---|
| 1 | 0596-AA47 · 200010 | b1 (raw) | `43 USC 1761` | **legitimate** |
| 2 | 0648-AU05 · 200810 | b1 (corroborated) | `18 USC 1801` | **wrong** |
| 3 | 0694-AB43 · 199610 | b2 | `50 USC 1710 et seq` | **wrong** |
| 4 | 0694-AB50 · 200004 | b2 | `50 USC 1710 et seq` | **wrong** |
| 5 | 1024-AC75 · 200010 | a | `16 USC 1` | **legitimate** |
| 6 | 1120-AB71 · 201704 | b1 (raw) | `5 U.S.C. 301` | **legitimate** |
| 7 | 1120-AB72 · 202010 | b1 (raw) | `5 U.S.C. 301` | **legitimate** |
| 8 | 1510-AA92 · 200404 | b1 (corroborated) | `12 USC 321` | **wrong** |
| 9 | 2070-AJ50 · 201104 | b1 (corroborated) | `15 USC 2612` | **legitimate** |
| 10 | 2105-AA78 · 200110 | b2 | `49 USC 1324` | **wrong** |
| 11 | 2120-AH41 · 200204 | b1 (corroborated) + b2 | `46 USC 106(g)` | **wrong** |
| 12 | 2120-AH46 · 200210 | b2 | `49 USC 44113` | **wrong** |
| 13 | 2127-AI76 · 200310 | a | `15 USC 1392` | **legitimate** |
| 14 | 3041-AD14 · 201304 | a | `15 USC 2063` (in `15 USC 2063, sec 3, 102 PL 110-314, 122 Stat 3016, 3017, 3022`) | **legitimate** |
| 15 | 3060-AG34 · 200410 | a | `47 USC 215` | **legitimate** |
| 16 | 3060-AG34 · 200810 | a | `47 USC 208` | **legitimate** |
| 17 | 3060-AG34 · 201004 | a | `47 USC 208` | **legitimate** |
| 18 | 3133-AC85 · 200404 | b1 (corroborated) | `42 USC 4311 to 4312` | **wrong** |
| 19 | 3170-AA99 · 202004 | a | `12 U.S.C. 5581` | **legitimate** |
| 20 | 3206-AG15 · 199510 | b2 | `5 USC 5538` | **wrong** |

### Per-row evidence

**1. 0596-AA47/200010 — legitimate.** Reginfo ("Hydropower Applications",
USDA Forest Service): Legal Authority is verbatim `16 USC 551; 43 USC
1761` — 43 U.S.C. 1761 is FLPMA's right-of-way grant section, exactly on
point. The shadow trigger was `note_says_title=[30]`, **not**
oracle-corroborated: 36 CFR 251's cached note reads "...30 U.S.C. 1740,
1761-1771," and 30 U.S.C. 1761-1771 individually **do not exist** (checked
directly: zero rows in either oracle file for e.g. `(30,'1764')`). 43
U.S.C. 1740-1771 is the real FLPMA range; the note itself almost certainly
misprints the title digit. Row is correct; the cached ground truth is the
error here.

**2. 0648-AU05/200810 — wrong, as predicted.** Reginfo (NMFS Northeast
fisheries correction): Legal Authority `18 USC 1801`. The cached note for
50 CFR 648 is `Authority: 16 U.S.C. 1801 et seq.` — the Magnuson-Stevens
Act, the universal authority for every Title 50 fisheries part. 18 U.S.C.
1801 is the Video Voyeurism Prevention Act, unrelated and coincidentally
real. Single-digit title typo (6→8), oracle-corroborated.

**3-4. 0694-AB43/199610, 0694-AB50/200004 — wrong, as predicted.** Both
reginfo pages show the identical Commerce/BIS EAR boilerplate block (`18
USC 2510 et seq; 30 USC 185; 42 USC 6212; 10 USC 7429; 10 USC 7430(e); **50
USC 1710 et seq**; 22 USC 3201 et seq; ...`), reused verbatim across many
separate export-control RINs. Every other export-control authority in this
corpus (and EAR practice generally) cites IEEPA as **50 U.S.C. 1701 et
seq**; 1710 is not part of that boilerplate anywhere else it is checked.
Section 1710 was first attested in the oracle in **2024** — a section
Congress created 28 (1996 row) and 24 (2000 row) years after these
editions. Not a coincidence limited to one filing: the same "1710" survives
across the whole EAR boilerplate family (also seen driving `0694-AB09`,
`0694-AB10`, `0694-AB41`, etc. in the top-RIN list for sub-count 2).

**5. 1024-AC75/200010 — legitimate.** Reginfo (NPS FOIA-withholding rule):
`16 USC 1; 16 USC 5397`. 16 U.S.C. 1 is the NPS Organic Act, the most
fundamental possible NPS citation. The run qualified only because its
sibling `16 USC 5397` is absent (a real but separate defect); the
"coherent other title 25" match (both `1` and `5397` happen to exist as
unrelated Title 25 sections) implicates 5397, not the correct `16 USC 1`
row that was actually flagged.

**6-7. 1120-AB71/201704, 1120-AB72/202010 — legitimate.** Both reginfo
pages (BOP inmate-discipline rules) open their Legal Authority with `5
U.S.C. 301` verbatim — the standard departmental-regulations boilerplate.
The cached 28 CFR 541 note reads `Authority: 15 U.S.C. 301; 18 U.S.C.
3621, ...` — **15**, not 5. This is the same failure mode as row 1: the
cached note appears to misprint the title digit, not the corpus. (These
same pages also carry `18 U.S.C. 4082`, `4161-4166`, `5006-5024`,
explicitly parenthesised on reginfo as "(Repealed ... as to offenses
committed on/after [date])" — filer-labelled historical citations, the
same pattern as the review's own 18 U.S.C. 3568 caution, and correctly
outside this note's scope since they are not `exists` rows misread as new.)

**8. 1510-AA92/200404 — wrong (moderate confidence).** Reginfo (Treasury
"General Revisions," 31 CFR 203 Treasury Tax & Loan depositaries): a long,
deliberate Title 12 Federal Reserve Act list — `90, 265, 266, 321, 323,
332, 391, 1452(d), 1464(k), 1767, 1789(a), 2013, 2122, 3102` — plus `31 USC
3301 to 3304`. The cached note's own Title 12 list is `90,265-266, 332,
391, 1452(d), 1464(k), 1767, 1789a, 2013, 2122, 3102` — **missing 321 and
323** — while its Title 31 clause is `31 U.S.C. 321, 323, and 3301-3304`.
The filer's `321, 323` sit exactly where the note's own `31 U.S.C. 321,
323` would slot into an otherwise-identical sequence. 12 U.S.C. 321
(Federal Reserve Districts) is real but off-topic for a depositary-
designation rule; 31 U.S.C. 321 (Secretary's general authority) is
squarely on point and independently oracle-real. Best read as the title
of a correct citation carried wrong, coincidentally real under 12 as an
unrelated Federal Reserve Act section.

**9. 2070-AJ50/201104 — legitimate.** Reginfo (EPA chemical-import ACE
reporting): `15 USC 2612` — TSCA import/export certification, exactly on
point, and CFR Citation is specifically `19 CFR 12.118 to 12.127`. The
cached 19 CFR 12 note is enormous and covers **dozens of unrelated
subsections each with its own authority**; it explicitly reads "Sections
12.118 through 12.127 also issued under **15 U.S.C. 2601 et seq**"
(TSCA — confirms the row) and, separately, "Sections 12.104 through
12.104i also issued under **19 U.S.C. 2612**" (a different subsection, an
unrelated trade-law provision). My part-level union conflates the two
subsections' authorities; the "shadow" is an artifact of flattening a
note that is really many per-subsection notes glued together, not a
defect in the row. This is a distinct, generalisable failure mode from
row 1/6/7's note-typo problem — subsection conflation rather than a bad
digit — worth its own name if this predicate is ever operationalised.

**10. 2105-AA78/200110 — wrong, as predicted.** Reginfo (DOT "Diversion of
Flights," a docket dating to 1980, `Docket 41683`): the entire Legal
Authority list — `49 USC 1301, 1302, 1305, **1324**, 1371, 1375, 1377 to
1379, 1381, 1382, 1386, 1461, 1481, 1482, 1502, 1504` — is pre-1994
Federal Aviation Act numbering (recodified into 49 U.S.C. 40101 et seq. by
Pub. L. 103-272, seven years before this edition). Current 49 U.S.C. 1324
was first attested in the oracle in **2015**, fourteen years after this
2001 filing and wholly unconnected to the 1938-vintage citation scheme
the rest of the list uses.

**11. 2120-AH41/200204 — wrong, as predicted (triple-flagged).** Reginfo
(FAA Stage-3 noise rule): `**46 USC 106(g)**; 49 USC 1155, 40103, 40113,
40120, 44101, 44111, 44701, ...` — every sibling in the list, and the
cached 14 CFR 91 note, use `49 U.S.C. 106(g)`, the FAA's universal
general-powers delegation clause repeated in nearly every FAA rule in this
corpus (see row 12's list, which opens with the correctly-spelled `49 USC
106(g)`). Clean single-digit title typo (9→6), coincidentally real under
Title 46 (Shipping) after that title's mid-2000s reorganisation, hence
also flagged by sub-count 2.

**12. 2120-AH46/200210 — wrong, as predicted.** Reginfo (FAA flight-data-
recorder exemption): the list ends `..., 44901, 44903-44904, 44912, 46105,
**44113**` — out of numeric sequence at the tail. Cornell LII: 49 U.S.C.
44113 was enacted by Pub. L. 108-297 on 2004-08-09, defining Cape Town
Treaty aircraft-registry terms — wholly unrelated to flight data
recorders, and nonexistent for two more years after this 2002 filing.

**13. 2127-AI76/200310 — legitimate.** Reginfo (NHTSA/GM FMVSS petition):
`15 USC 1392` and `15 USC 1497`. 15 U.S.C. 1392 is the pre-1994-
recodification Motor Vehicle Safety Act standard-setting section (now 49
U.S.C. 30111) — stale nine years after recodification, but genuinely what
was cited and genuinely real. The run only qualified because its sibling
`15 USC 1497` is absent (probably its own, unrelated typo); the "coherent
other title 28" hit (both numbers happen to be real, unrelated Title 28
venue/claims sections) implicates 1497, not the flagged 1392 row.

**14. 3041-AD14/201304 — legitimate.** Reginfo (CPSC testing-and-labeling
rule): `15 USC 2063` is CPSC's certification-testing section, exactly on
point; reginfo shows it separated correctly as `15 USC 2063, sec 3, 102 PL
110314, 122 Stat 3016, 3017, 3022`. The corpus's own citation grammar
parsed the trailing Public-Law-section numbers ("sec. 3, 102" of Pub. L.
110-314) and Statutes-at-Large page numbers (3016, 3017, 3022) as if they
were bare Title 15 U.S.C. sections (rows for `102` (exists), `3017`
(absent), `3022` (absent) all appear under `usc_title=15` in the corpus).
Run coherence then finds "coherent other title 38" over this
already-garbage set — noise built on a pre-existing, unrelated parsing
defect, not evidence about the correctly-cited `2063` row.

**15-17. 3060-AG34/200410, 200810, 201004 — legitimate (×3, one finding).**
Reginfo (FCC E911 rule): `47 USC 134(i); 151; 201; 208; 215; 303; 309` —
entirely and correctly Communications Act citations for an FCC wireless-
911 rule. See the §(a) discussion above: this one RIN, re-filed with an
unchanged authority block across roughly 41 editions, supplies 246 of the
691 raw wrong-by-run rows and all three of these sample draws. Title 23's
coincidental low-number overlap has no bearing on this run; its one real
defect (`47 USC 134(i)`, absent) does not implicate its siblings.

**18. 3133-AC85/200404 — wrong, as predicted.** Reginfo (NCUA loan-
participation rule): `..., 42 USC 1981; 42 USC 3601 to 3610; **42 USC 4311
to 4312**`. The cached 12 CFR 701 note is explicit and subsection-scoped:
"Section 701.35 is also authorized by **12 U.S.C. 4311-4312**" — not 42.
The filer's citation immediately follows the genuinely-Title-42 `3601 to
3610` (Fair Housing Act) entry; most likely the "42" was carried forward
by eye across the boundary (the same sibling-elision mechanism review
class A names as P2). 42 U.S.C. 4311-4312 (USERRA reemployment rights) is
real but unconnected to credit-union lending.

**19. 3170-AA99/202004 — legitimate.** Reginfo (CFPB loan-originator-
compensation rule): `12 U.S.C. 5581` and `12 U.S.C. 1604(a)`. 12 U.S.C.
5581 is the correct Dodd-Frank CFPB transfer-date authority, exactly on
point (absent sibling `12 U.S.C. 1604(a)` is very likely a title typo for
**15** U.S.C. 1604(a), TILA/Regulation Z's own rulemaking-authority
section — a real defect, but on the other row). The "coherent other title
2" match (both `5581` and `1604` happening to be real Title 2 sections)
implicates the wrong row.

**20. 3206-AG15/199510 — wrong, as predicted.** Reginfo (OPM "Incentive
Awards; Pay and Leave Administration"): among a long, plausible list of
Title 5 pay-administration sections is `5 USC 5538`. 5 U.S.C. 5538
(differential pay for reservists called to active duty) was enacted in
2009 — fourteen years after this 1995 filing, and unconnected to the
rule's general pay-and-leave subject at the time it was cited.

### Precision by predicate

| predicate | true / n | precision |
|---|---:|---:|
| **a — run coherence** | 0 / 7 | **0%** |
| **b1 — stale-note shadow, raw** | 4 / 8 | 50% |
| ↳ b1, oracle-corroborated subset | 4 / 5 | **80%** |
| ↳ b1, raw-only (not corroborated) | 0 / 3 | **0%** |
| **b2 — attested after edition** | 6 / 6 | **100%** |
| **overall (20 distinct rows, one predicate per row where they overlap)** | 9 / 20 | **45%** |

(Row 11 satisfies both b1-corroborated and b2 and is counted once in the
overall line and once in each predicate's own line, per the table above;
every other row's predicate tag is unambiguous.)

## Cross-cutting findings

1. **Run coherence, measured exactly as the review's hypothesis states it,
   is not usable as-is.** It correctly reproduces its own motivating
   example (RIN 2137-AE60) and a handful of the top-pairs table's smaller
   entries plausibly look real (e.g. `15→20`, `26→7`), but the sample's
   7-for-7 false-positive run shows the dominant failure mode: common,
   low integer section numbers recur across many titles' historical
   "general provisions" debris (Title 23's repeated highway-law
   recodifications; Title 25, 28, 2, 38 similarly), so "exactly one other
   title covers every section in the run" fires on coincidence far more
   often than on a genuine wrong-title citation. **Any future
   `usc_section_run_coherent` verdict needs a much stronger gate** —
   candidate restriction to titles independently plausible for the
   citing agency, or requiring corroboration from the rule's own CFR
   authority note (à la sub-count 1) — before it repairs anything
   automatically.
2. **The cached authority notes are not infallible ground truth.** Two of
   the 287 (36 CFR 251, 28 CFR 541) appear to misprint a title digit in
   their own published "Authority:" text (`30 U.S.C.` for what is very
   likely `43 U.S.C.`; `15 U.S.C. 301` for what is very likely `5 U.S.C.
   301`), and both drove raw-but-uncorroborated shadow hits in the
   sample. The oracle-corroboration cross-check added in this
   measurement (does the note's *claimed* alternate-title pair itself
   exist?) is what separates these from the genuine hits — raw shadow
   precision (50%) versus corroborated shadow precision (80%) in the
   sample is exactly this distinction paying for itself.
3. **A single large CFR part's authority note can cover many unrelated
   subsections**, each with its own scoped authority (row 9's 19 CFR 12,
   which individually authorises §§12.1 through 12.152 under a dozen
   different titles). Unioning a note's citations at the part level, as
   this measurement does, manufactures shadows between subsections that
   were never meant to share an authority. A section-scoped (not
   part-scoped) note join would remove this failure mode; it was not
   built here.
4. **"Never in the annual archive" has two opposite readings, and only one
   is "created later."** Of the 2,946 in-scope `exists` rows whose section
   never appears in any annual archive year, **2,929 are pre-1994
   disposition stubs** (created long before the archive window, repealed
   before it opens, kept only as a `status != 'current'` stub in the
   release point) — the same shape as review class H's own `18 U.S.C.
   3568` caution — 12 are indeterminate (`edition_year = 2025`), and only
   **5** are gated `status='current'` and belong in sub-count 2. The guard
   matters by two orders of magnitude.
5. **Parsing defects upstream of both predicates can manufacture their own
   noise.** Row 14's run mixes genuine U.S.C. sections with a Public-Law
   section number and Statutes-at-Large page numbers that the citation
   grammar read as bare U.S.C. sections; run coherence then finds
   spurious title agreement over that already-wrong set. This is a
   distinct defect class from either predicate, and neither was built
   to catch it.

## Hypotheses for a verdict column (not implemented)

Stated as hypotheses only, per instructions — nothing below is built:

- `usc_section_run_coherent` (boolean/title) — **not recommended as
  measured**; 0/7 precision in-sample, and (see the scope-limitation note
  above) the "spans one title" qualification misses the task's own richest
  named examples because real Legal Authority fields legitimately mix
  titles. If pursued, (i) test contiguous same-title sub-runs within a
  mixed-title field rather than requiring the whole field to be one
  title, and (ii) gate candidate titles on independent plausibility
  (agency/subject match, or corroboration from the rule's own CFR note)
  rather than bare oracle membership — 2115-AE94's own run is jointly
  "coherent" with *two* unrelated titles (46 and 15) by bare membership,
  which is the same coincidence-prone shape the sample found repeatedly.
- `usc_section_note_shadow_corroborated` (boolean, title) — the
  oracle-corroborated subset of sub-count 1; 4/5 in-sample. Best framed
  as a **candidate generator for human/further review**, not an
  auto-verdict — row 9 shows even the corroborated subset can be wrong
  when a note's citations span multiple unrelated subsections. A
  subsection-scoped note join (see finding 3) would likely raise this
  further.
- `usc_section_attested_before_edition` (boolean, with the
  `status='current'`-vs-repealed-stub guard from finding 4 built in from
  the start) — the strongest candidate measured here, 6/6 in-sample. The
  guard is not optional: without it, the naive version is dominated
  two-orders-of-magnitude by the opposite phenomenon (pre-1994 repeal
  stubs, not post-2024 creation).

## Reproducibility

Seed `20260823`, Python `random.Random(20260823).sample(sorted_pool, 20)`
over the 1,922-row deduplicated union described above. Every count in this
note is reproducible from the pinned parquets and the cached eCFR notes
already committed to this tree; the scratch scripts that produced them are
not (per instructions) part of this commit.
