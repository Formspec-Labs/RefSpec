# FR prose-signal harvests — 2026-08-31

Three scoped harvests of prose signal families known to exist from prior raw
reading. This is a **measurement lane**: no `src/` or `tools/` edits, no
commits, nothing built.

> **Revised 2026-08-31 after review.** A max-effort review returned
> RECONSIDER with ten confirmed findings. Every one is resolved below and the
> numbers changed. The largest corrections: the EO harvest applied one title's
> first verb to every target in it (mislabelling relations and dropping later
> ones); the "38% false-continuation rate" was a marker-hit fraction, not a
> rate; `101 Stat. 1568, 1608` was read as a page SPAN and is not one; the
> Stat. regex required a period and so missed the very no-period specimen the
> README used as proof it did not; the colophon scan walked the mutable
> working tree; and the "no bulk FR corpus exists" premise was false. See
> [What the review changed](#what-the-review-changed) for the full list.

## How to read a number in this file

Every number carries its provenance class. Nothing here is presented as
script output unless a script prints it.

| tag | class | how to check it |
|---|---|---|
| **[S]** | **Script-printed.** The named script prints it and writes it to its `receipt.json`. | Re-run the script. |
| **[A]** | **Receipt-derived arithmetic.** Computed from `[S]` fields; the derivation is written out beside it. | Do the arithmetic on the receipt. |
| **[X]** | **External-document fact.** Asserted by a document outside this directory, cited by path and line. | Open the cited file. |
| **[M]** | **Manual classification.** A human read the raw source and recorded a per-specimen verdict. | Open the per-specimen record named beside it. |

Re-run anything with `.venv/bin/python
research/evidence/fr-prose-signals-2026-08-31/<family>/scan_*.py` from the
repo root. Each script now records the sha256 and byte size of **every input
it read** in its receipt's `inputs` block, so a re-run over different bytes is
visibly a different run.

Read before scanning, per the raw-source-first rule (AGENTS.md):
`src/refspec/registry/identifier_shapes.py`'s module docstring and
research-notes comments on the `E5-2394Filed` print-welded family;
`research/investigations-mined-2026-08-31.md` silent items 4 (Stat. list →
fabricated U.S.C. bug) and 5 (no EO oracle); the `inv-eo` / `inv-eo-gap`
evidence directories a parallel lane is promoting into a module;
`research/backlog-validation-2026-08-31.md`; and
`research/fr-body-signal-inventory-2026-08-31.md`.

## Contents

```
filed-date-colophons/scan_filed_colophons.py   + input_inventory.json + receipt.json
stat-page-lists/scan_stat_lists.py             + manual_verdicts.json + receipt.json
eo-amendment-chains/scan_eo_chains.py          + receipt.json
MANIFEST-sha256.csv
```

---

## 1. Filed-date colophons — `[FR Doc. {number} Filed {date}; {time}]`

**Verdict: MEASURE THE NAMED LOCAL CORPORA NEXT.** The signal is real and
genuinely unique. The previous verdict ("not worth a reader; there is no
corpus to build against without a remote fetch") rested on a false premise
and is withdrawn.

### The scan is pinned, not a working-tree walk

The first version walked `REPO_ROOT.rglob("*")` at run time. That is not
reproducible: another evidence lane's new raw captures under
`research/evidence/fr-short-tails-2026-08-31/raw/` silently entered the
population between runs while this README quoted the count as fixed.

The scan now reads **only** the paths pinned in
`filed-date-colophons/input_inventory.json`, verifying each file's sha256
before reading it. **830 pinned scan files, 2,263,176,186 bytes, plus 61
pinned MODS comparison files** [S]. Inventory sha256
`bb201eb1b51341b3fe1da05f61961994ed02fa4d2dde5b99103a4f218a22c950` [S].

**Boundary rule — decided, not accidental: other lanes' `raw/` directories
are INCLUDED.** They are holdings of this repository, and the question this
family asks is what colophon-bearing bytes we hold. Excluding them by
accident is precisely what produced the previous overclaim. Including them
through a pinned inventory means a lane's new capture cannot silently move a
published number: it surfaces as `unpinned` drift, and someone has to run
`--repin` on purpose and re-quote the census. The run reports three drift
classes and **withholds** population numbers on the first two:

- `missing` — a pinned file is gone;
- `digest_drift` — a pinned file's bytes changed;
- `unpinned` — a file matching the walk rule is on disk but not in the
  inventory (named, counted, and **not** scanned).

Current drift: `missing=0 digest_drift=0 unpinned_on_disk=0` [S].

### Population

**14 colophon specimens across 14 files** [S] — up from the 9 the previous,
unpinned run reported [X: review report]. 7 are carried in a `<FRDOC>` XML tag (GovInfo
per-document granule XML from `inv-62` and `inv-initialisms`); 7 are raw
prose with no tag [S]: five `fr-short-tails-2026-08-31` raw text captures,
the `hand-attestations-2026-08-31` witness capture, and one that leaked into
a MODS metadata file's `<contact>` field.

Document-number shape census [S]:

| shape | count |
|---|---|
| modern (`YYYY-NNNNN`) | 5 |
| bare-legacy (`YY-NNNNN`) | 6 |
| letter-opening (`E9-21740`, `E5-2394Filed`) | 2 |
| unclassified (`94-2050F`) | 1 |

Date-text: `M-D-YY`, unpadded, in 13 of the 14 — 13 distinct strings over 14
specimens [S]. The fourteenth is the zero-filled `00-00-94` placeholder
(damage class 2 below), so "always unpadded" is not safe to assert. Time-text
census [S]: `8:45 am` **12 of 14**, `4:15 pm` 1, `12:00 pm` 1. (The previous
README said "8:45 am (6 of 9)" [X: review report]; its own receipt already
said 7 of 9. The census is now a count per value, not a list of distinct
values.)

### Damage classes

1. **Print-welded token** (already attested): `E5-2394Filed` — the number and
   the word "Filed" fused with no space, on the printed page itself. **1 of
   14** [S]. Raw specimen, read per `identifier_shapes.py`'s own research
   notes and the 2026-08-31 hand-attestation:

   ```
   [FR Doc. E5-2394Filed 5-16-05; 8:45 am]
   BILLING CODE 3510-22-S
   ```
   (`research/evidence/hand-attestations-2026-08-31/witnesses/fr-rawtext-E5-2394Filed.txt`.
   The control colophon on the same printed page,
   `[FR Doc. E5–2414 Filed 5–13–05; 8:45 am]`, has its space; only this
   document's colophon is fused, which is what rules out a template-wide
   defect and rules in a per-document composition defect, per the existing
   attestation.) [X: that attestation directory]

2. **Zero-filled placeholder colophon — new this pass, and only visible
   because the pinned inventory includes the other lane's raw directory.**
   **1 of 14** [S]:

   ```
   [FR Doc. 94-00000 Filed 00-00-94; 8:45 am]
   BILLING CODE 6210-01-P
   ```
   (`research/evidence/fr-short-tails-2026-08-31/raw/94-S16142.txt`, raw-read
   in full: a Federal Reserve Board meeting notice, "Dated: October 12,
   1994," signed Jennifer J. Johnson, Deputy Secretary of the Board. The
   aggregator's own id for the document is `94-S16142`; the *printed*
   colophon is the placeholder.) The shape vocabulary in
   `identifier_shapes.py` classifies `94-00000` as **bare-legacy**, i.e. a
   reader gated on shape alone would admit it, and `00-00-94` parses as a
   date with a zero month and a zero day. Any colophon reader needs an
   explicit placeholder refusal; shape will not supply one.

3. **Trailing-letter document number.** **1 of 14** [S]:
   `[FR Doc. 94-2050F Filed 8-19-94; 8:45 am]`
   (`research/evidence/fr-short-tails-2026-08-31/raw/94-2050F.txt`, a Forest
   Service EIS cancellation, "Dated: August 11, 1994"). No shape admits it —
   the census calls it `unclassified`. Same micro-family as the `C0-6263A`
   value already named in `research/fr-body-signal-inventory-2026-08-31.md`
   [X].

4. **The colophon leaks into "structured" metadata.**
   `research/evidence/investigations-2026-08-23/inv-frvol/raw/govinfo_mods/FR-1994-12-30_mods.xml`,
   inside a `<contact>` element:

   ```xml
   <contact>William I. Hummel, Contracts Division, National Endowment for
   the Arts, 1100 Pennsylvania Ave., N.W. Washington, D.C. 20506
   (202/682-5482). William I. Hummel, Director, Contracts and Procurement
   Division. [FR Doc. 94-32198 Filed 12-29-94; 8:45 am] BILLING CODE
   7537-01-M</contact>
   ```

   Reading the surrounding structure ruled out a schema field: `<contact>`
   holds a name and phone number in every sibling occurrence, and the
   colophon plus billing code are glued onto the end of this ONE contact
   because the publisher's own extraction did not bound the field. It is the
   only MODS file carrying the colophon string [S].

5. **Trailing whitespace inside the tag**: `fr_MMA_0917_07-2740.xml` —
   `<FRDOC>[FR Doc. 07-2740 Filed 6-1-07; 8:45 am] </FRDOC>`. **1 of 14** [S].
   Cosmetic, but a reader keying on tag-content equality rather than a
   trimmed value treats it as a different string than its siblings.

### What the MODS comparison actually establishes

The previous README claimed "none of the 61 carry a filing time as a real
field". That was a grep for the word "filed" and a clock time — it could not
support a claim about fields. The scan now reads the comparison corpus's
**names**: 61 files, **77 distinct element names, 24 distinct attribute
names** [S]. **Zero** element or attribute names match
`time|filed|filing|hour|clock` [S]. Eight date-bearing elements exist —
`commentDate`, `dateIngested`, `dateIssued`, `dates`, `effectiveDate`,
`publicMeetingDate`, `recordChangeDate`, `recordCreationDate` — and of their
values only 5, all in the free-text `dates` element, carry a clock time at
all [S], each visibly unrelated prose ("Written comments must be received by
4:00 p.m., E.S.T. …") [S, values in the receipt].

Bounded claim: **across the element and attribute names present in these 61
files, none names a filing time.** That is not a statement about the MODS
schema in general, and it is not stated as one.

### Corrected verdict: measure what is already local

The previous README asserted that building a reader "would require fetching a
real bulk FR full-text corpus … a genuine remote-fetch project". That is
false. Named holdings, verified present on this machine and probed by the
script:

- `~/Work/corpora/_preserved-2026-08-10/body-retrieval-corpus-2026-08-02/`
  (5.3 GB; an identical copy at
  `~/Work/spicy-regs/output/body-retrieval-corpus-2026-08-02/`) — the
  993-document FR corpus with full HTML **and** XML bodies described at
  `research/remaining-work-sweep-2026-08-21.md:41` [X]. The script counts
  **1,986 `.xml` and 1,986 `.htm*` files** in it [S] and probes the first 15
  XML files: **15 of 15 carry a colophon** [S], e.g.
  `[FR Doc. 04-28286 Filed 12-30-04; 8:45 am]`. This is a **bounded probe of
  15 files, explicitly not a census** — but it settles the premise.
- `~/Work/corpora/_salvage-2026-08-28/spicysearch-output/` — the salvaged
  39,789 pre-2000 rule bodies and 7,212 presidential bodies named at
  `research/fr-body-signal-inventory-2026-08-31.md:3` [X]. The script counts
  **7,212 `.xml` and 41,143 `.htm*` files** [S]; the 15-file XML probe found
  **0** colophons [S], so the presidential-body half is a different shape and
  the rule-body half needs its own probe before anyone quotes a yield.

So: the next action is **measure the named local corpora**, not fetch. The
993-document corpus alone is two orders of magnitude larger than the 14
specimens this repo holds and needs no network. What is still true is that
**this directory has not measured them**; the probe is 30 files.
`research/fr-body-signal-inventory-2026-08-31.md` independently ranks filed
timestamps as **"Document-level fact → DocSpec. Low value today."** [X] — that
ranking is unchanged by anything here.

---

## 2. Stat.-page lists — `101 Stat. 1568, 1608`

**Verdict: PROMOTION CANDIDATE for a partial fix, and a corrected diagnosis
of the known bug.** This census supplies a measured rate and, more usefully,
proves that the two gates previously proposed **do not retire** the
fabricated-U.S.C.-citation bug.

**This harvest measures a DIFFERENT thing than the known bug.** The bug
(`research/investigations-mined-2026-08-31.md:75`, silent item 4) is in the
*production* note reader, which emits U.S.C. citations from these lists: "148
fabricated citations across 80 of the" 8,240 notes [X]. This harvest does not
touch that reader. It runs an independent regex over the same corpus.

### Population

Corpus: `research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl`,
**8,240** `authority_note` strings [S], sha256 pinned in the receipt.

**The regex now accepts `Stat` without a period.** The previous pattern
required `Stat\.`, while the README claimed it caught the no-period variant
and quoted `102 Stat 989, 993` as proof — a specimen that was not in
`all_matches` at all. Widened to `Stat\.?`:

| | count |
|---|---:|
| notes containing the literal `Stat.` | 1,663 [S] |
| notes containing `Stat` with **or** without a period | 1,670 [S] |
| total `NNN Stat[.] <page-list>` matches | **2,995** [S] (was 2,973 [X: review report]) |
| of those, printed marker lacks a period | 22 [S] |
| distinct notes carrying a 2-or-more-token list | **343** [S] (was 342 [X: review report]) |

Token-length histogram [S]:

| tokens | occurrences |
|---:|---:|
| 1 | 2,479 |
| 2 | 451 |
| 3 | 38 |
| 4 | 13 |
| 5 | 5 |
| 6 | 2 |
| 9 | 2 |
| 10 | 1 |
| 11 | 4 |

### The metric is a marker-hit fraction. The rate is measured separately.

The previous README reported "171 of 448 (38%) are not real two-page lists at
all" [X: review report] as a false-continuation **rate**. It is not one. It is the fraction of
two-token matches whose *following text* opens with another citation-type
keyword — a test that is a lower bound by construction. Its own receipt
proved this: the known 14 CFR 121 false continuation has no adjacent marker
and was recorded `suspect=false`.

The field is now named for what it measures:
**`two_token_marker_adjacent` = 171 of 451 = 37.9% marker-hit fraction** [S].

The actual rate was then established by stratifying and measuring, never by
subtraction:

**Stratum 1 — marker-adjacent (n=171).** Read exhaustively in one pass on
2026-08-31; every one has the form `NNN Stat. PPPP, TT` where `TT` is the
title number of the U.S.C./CFR/Comp. citation that follows. **0 exceptions**
[M; the full 171-row list is `marker_adjacent_two_token_matches` in the
receipt]. Rate in stratum: 100%.

**Stratum 2 — the unmarked remainder (n=280).** A random sample of **60** was
drawn with seed `20260831` by
`random.Random(seed).sample(range(len(population)), 60)` over the population
sorted by key, and **each specimen was hand-read in full sentence context**
[M; per-specimen verdicts with reasons in
`stat-page-lists/manual_verdicts.json`]. The script joins that file to the
sample it redraws and refuses to report a rate if any drawn key lacks a
verdict — currently 0 missing [S].

- **8 false continuations, 52 genuine page pairs** [S]
- **sampled rate 13.3%, Wilson 95% CI 6.9% – 24.2%** [S]

All 8 hand-found false continuations in the unmarked stratum are the *same*
shape, and it is not the marker shape: the second token is the **volume
number of the next Stat. citation**. E.g. 36 CFR 10:
`"42 Stat. 1214, 45 Stat. 1644, secs. 1, 2, 52 Stat. 708"` — the captured
`45` opens `45 Stat. 1644` [M].

**Stratified two-token false-continuation rate** [A]:
`(171 × 1.0 + 280 × 0.1333) / 451` = **46.2%**, 95% CI **42.2% – 52.9%**
(interval from stratum 2 only; stratum 1 is observed, not estimated).

**False continuations that gate 1 cannot see** [A]: `280 × 0.1333` ≈ **37
matches**, 95% CI **19 – 68**.

### `101 Stat. 1568, 1608` is not a span. It is an Act-opening page and a pinpoint.

The previous README read the two-token form as "a (start page, end page) SPAN
of one Act's provision" and said sec. 301(a) "begins at 101 Stat. 1568 and
that section ends at page 1608". That is legally wrong and the corpus refutes
it without leaving the corpus.

**1568 is Public Law 100-233's OPENING page. 1608 is the sec. 301(a)
pinpoint.** [X: verified by the reviewer against the official Statutes at
Large PDF; sec. 301(b) is at 1609.] The corpus's own witnesses make it
unavoidable — every note in the corpus that cites `101 Stat. 1568` [S]:

```
12 CFR 611:  secs. 411 and 412, Pub. L. 100-233, 101 Stat. 1568, 1638
12 CFR 615:  sec. 301(a),       Pub. L. 100-233, 101 Stat. 1568, 1608
12 CFR 620:  sec. 424,          Pub. L. 100-233, 101 Stat. 1568, 1656
12 CFR 628:  sec. 301(a),       Pub. L. 100-233, 101 Stat. 1568, 1608
12 CFR 630:  sec. 424,          Pub. L. 100-233, 101 Stat. 1568, 1656
```

One Act, one first number, **three different second numbers, one per cited
section**. A span reading would give Pub. L. 100-233 three different end
pages from one start page. The pinpoint reading explains all five rows. The
same pattern repeats for Pub. L. 100-399 (`102 Stat. 989, 999` in 12 CFR 611;
`102 Stat 989, 993` in 12 CFR 615 and 628) [S].

Measured generally: among the 280 unmarked two-token matches there are **182
distinct (volume, first-token) keys, of which 20 carry more than one second
page** [S] — impossible under a span reading, ordinary under a pinpoint one.

The receipt field is renamed accordingly; a faithful reader should represent
each match as `{volume: 101, opening_page: 1568, pinpoint: 1608}` and must
**not** collapse it to "pages 1568 through 1608".

(Incidental, from the raw read: 12 CFR 615 and 628 attribute
`102 Stat 989, 993` to "Pub. L. 103-399" while 12 CFR 611 attributes
`102 Stat. 989, 999` to "Pub. L. 100-399". Volume 102 is the 1988 session, so
the 103- spelling in the eCFR text is the publisher's, not this scan's.
Recorded, not resolved.)

### Two more damage classes the raw read surfaced

- **Captured token truncated at a letter — 16 matches** [S]. The
  consolidated-appropriations appendix-page form truncates:
  `114 Stat. 2763, 2763A-638` is captured as `114 Stat. 2763, 2763`, i.e. the
  regex manufactures a second page **identical to the first**. Also
  `113 Stat. 1535, 1501A-20` → `1501` [S].
- **Malformed printed volume — 1 match** [S]. 32 CFR 175 prints
  `"Pub. L. 106-398, October 30, 2000, 1014 Stat. 1654A-350"`. The volume is
  114; `1014` is the publisher's typo, and the `\d{1,3}` bound then silently
  truncates it to `014`. Two defects stacked, one publisher's and one the
  regex's.

### The specimen the brief asked for: 14 CFR 121's U.S.C.-list resumption

```
14 CFR 121 authority note (opening; full text in the receipt):
"Authority: 49 U.S.C. 106(f), 40103, 40113, 40119, 41706, 42301 preceding
note added by Pub. L. 112-95, sec. 412, 126 Stat. 89, 44101, 44701-44702,
44705, 44709-44711, 44713, 44716-44717, 44722, 44729, 44732; 46105; ..."
```

The regex captures 10 comma-joined tokens after `126 Stat. 89`. Reading the
full sentence rules out every one as a Stat. page: the sentence opens
`49 U.S.C. 106(f), 40103, …`, and the U.S.C. section list simply **resumes**
after the `Pub. L. 112-95, sec. 412, 126 Stat. 89` parenthetical, with no
repeated "U.S.C." keyword because the original prose needs none. There is
**no adjacent marker to gate on** — `44101` is bare.

### Gate simulation: what the two proposed fixes actually catch

Both proposed fixes were run over the corpus rather than asserted.

- **Gate 1 — stop the list at the first following citation-type keyword**
  (`U.S.C.`, `CFR`, `Comp.`).
- **Gate 2 — a per-volume maximum-page table.** No such table is held
  locally, so the script simulates the ceiling as the largest *first* token
  seen for that volume anywhere in this corpus (first tokens are used because
  later tokens are exactly the ones under suspicion). That ceiling is a
  **lower bound** on the volume's true length, so the simulation is *stricter*
  than a real table would be — anything it fails to catch, a real table also
  misses.

Over the **516** multi-token (2+) matches [S]:

| | caught |
|---|---:|
| gate 1 (marker stop) | 176 [S] |
| gate 2 (volume ceiling) | 14 [S] |
| either | 190 [S] |
| neither | 326 [S] |

Gate 2 does catch the 14 CFR 121 shape: the ceiling for volume 126 is 2,456
and nine of its tokens (`44101` … `44732`) are over it [S].

**But the claim "this retires the 148-fabrication bug" is withdrawn.** The
counterexample is in the same corpus and the script runs the gates on it:

```
12 CFR 611:  "... secs. 411 and 412, Pub. L. 100-233, 101 Stat. 1568, 1638,
              as amended by secs. 403 and 404, ..."
gate 1: text after the match is ", as amended by secs. 403 and" — no marker — PASSES
gate 2: ceiling for volume 101 is 3806; 1638 is under it — PASSES
```
[S, `gate_simulation.counterexample_12_cfr_611` in the receipt]

And `12 U.S.C. 1638` (Truth in Lending) **is a real section**
(`research/backlog-validation-2026-08-31.md:60`) [X], so a U.S.C.-section
existence oracle does not catch it either. The fabricated citation lands on a
real section.

(One provenance snag worth naming, since it trips anyone who opens the two
documents side by side: `investigations-mined-2026-08-31.md:75` reports this
specimen as `101 Stat. 1568, 1608` emitting `usc 12:1608`. The raw 12 CFR 611
note reads **1638**, as printed above and as
`backlog-validation-2026-08-31.md:60` records — "the mined note misquoted the
page as 1608; it is 1638" [X]. `1608` is 12 CFR 615's and 12 CFR 628's page,
not 611's. The counterexample stands either way, and it is stronger on the
raw value.)

**Downgraded claim — what the gates actually buy:**

1. Gate 1 removes the marker-adjacent class **exhaustively**: 176 of 516
   multi-token matches [S], every one hand-confirmed for the two-token half
   [M].
2. Gate 2 removes tokens that are wildly out of range for their volume: 14
   more [S], including the 14 CFR 121 resumption that gate 1 cannot see.
3. Neither gate — nor an existence oracle — catches a Stat. page that is
   **also a plausible section number in the U.S.C. title the note cites**.
   `101 Stat. 1568, 1638` → `12 U.S.C. 1638` is that class, and it is one of
   the fabrications the bug report already counts. Roughly **37 further false
   continuations (95% CI 19–68)** sit in the unmarked two-token stratum where
   gate 1 is blind [A].

The fix silent item 4 needs is **construction awareness** — knowing that the
number after a Stat. page in a `sec. N, Pub. L. X-Y, V Stat. A, B` frame is a
pinpoint page and never a U.S.C. section — not a stop rule plus a range
check. `research/backlog-validation-2026-08-31.md:60` reaches the same
conclusion independently [X].

---

## 3. EO amendment chains — `Executive Order 13516—Amending Executive Order 13462`

**Verdict: STRONGEST MEASURED SIGNAL OF THE THREE; OWNER UNDECIDED.** The
relation census is now correct per target. Where it goes is an open ownership
decision that this lane does not get to make.

### The old extraction was wrong in both directions

The previous pass found ONE leading verb phrase per title and applied it to
every EO number after it. That both **mislabelled** relations and **dropped**
targets. All four specimens verified byte-identical against the raw FR API
capture (`inv-eo/fr-api/fr-executive-orders-page{1,2}.json`) before being
restated here:

| EO | raw title (abbreviated) | old pass | correct |
|---|---|---|---|
| 13569 | `Amendments to Executive Orders 12824, 12835, 12859, and 13532, Reestablishment Pursuant to Executive Order 13498, and Revocation of Executive Order 13507` | 2 targets | 6, across 3 verbs |
| 13672 | `Further Amendments to Executive Order 11478, …, and Executive Order 11246, …` | dropped **11478** | both |
| 13716 | `Revocation of Executive Orders 13574, 13590, 13622, and 13645 …, Amendment of Executive Order 13628 …` | 1 target, **labelled "revocation of"** | 4 revoked + 1 **amended** |
| 14306 | `… and Amending Executive Order 13694 and Executive Order 14144` | dropped **13694** | both |

The "only one compound title exists" claim was also false: **10 plural-head
titles** (`Executive Orders N, N, and N`) are in the roster [S], the earliest
being EO 13062 at `inv-eo/derived/eo-roster.csv:4336`.

### The rewritten parser: graded per-target attribution

The title is segmented into verb clauses and each number list is bound to the
clause it sits in. Every edge carries its **attribution grade** rather than
having the inference smoothed away:

- **`direct`** — the verb phrase immediately precedes the `Executive Order(s)`
  head noun.
- **`coordinated`** — the mention is not verb-led, but follows an already
  attributed mention inside the same clause joined only by a coordinator
  (`,` / `and` / `&` / `or`). This is the `… Executive Order A, <A's own
  title>, and Executive Order B …` shape.
- **`unattributed`** — anything else. The `relation` field is the literal
  string `"unattributed"`. The parser refuses rather than guesses.

The verb vocabulary is a curated closed list, written into the receipt, so
what the parser can and cannot name is auditable.

### Corrected census

The `old` column is what the superseded pass reported, as quoted in the review
report [X: review report]; that receipt has been regenerated and is no longer
on disk, so those three figures are not re-checkable here.

| | old | corrected |
|---|---:|---:|
| roster titles carrying an EO-number mention | — | **163** [S] |
| target mentions (subject excluded) | — | **190** [S] |
| self-reference mentions dropped | — | 2 [S] |
| **attributed edges** | 145 | **185** [S] |
|  … `direct` | — | 181 [S] |
|  … `coordinated` | — | 4 [S] |
| `unattributed` mentions | — | **5** [S] |
| distinct subject EOs | 144 | 158 [S] |
| distinct object EOs | 108 | 136 [S] |

Verb census, attributed edges only [S]:

| verb | count | | verb | count |
|---|---:|---|---|---:|
| amendment to | 52 | | modification of | 4 |
| amending | 38 | | amendment of | 3 |
| amendments to | 31 | | further amending | 2 |
| further amendment to | 27 | | revoking | 2 |
| further amendments to | 11 | | exemption from | 1 |
| revocation of | 10 | | further amendment of | 1 |
| | | | partial revocation of | 1 |
| | | | reestablishment pursuant to | 1 |
| | | | suspension of | 1 |

Five of the fifteen verbs name relations that an amend/revoke-only vocabulary
cannot express at all: `modification of` (4), `amendment of` (3),
`reestablishment pursuant to` (1), `exemption from` (1), `suspension of` (1)
[S]. Two more exist only because the pattern now captures the degree modifier
instead of discarding it: `further amending` (2) and `partial revocation of`
(1) [S].

**4 multi-clause titles** carry two or three distinct verbs each [S]: 13350,
13403, 13569, 13716. In every one the corrected pass gives each target its
own clause's verb.

### Where the parser refuses (5 mentions)

Emitting `relation="unattributed"` rather than guessing is the point. All
five, with the exact text the refusal rests on [S]:

- **13350 → 12722** and **13357 → 12543**: `Termination of Emergency Declared
  in Executive Order 12722 …`. The object of "termination" is the
  **emergency**, not the order. A first-verb parser would have said EO 13350
  terminates EO 12722.
- **13668 → 13303**: `Ending Immunities Granted to … Pursuant to Executive
  Order 13303, as Amended` — basis recorded as **"no clause verb"** [S]: the
  stated relation is "pursuant to", which the curated vocabulary deliberately
  does not name, so nothing in the title governs the mention.
- **13764 → 13488** and **13764 → 13467**: `Amending the Civil Service Rules,
  Executive Order 13488, and Executive Order 13467 …`. This is the rule's
  **conservative miss**: EO 13764 genuinely amends both, but the first
  mention is separated from `Amending` by a non-EO object ("the Civil Service
  Rules,"), so it cannot be bound directly, and the second cannot inherit
  from an unattributed first. Named here rather than silently recovered.

### Endpoint resolution — evidence, never a mint fence

**30 of 190 mentions** name a target not in the 5,693-number roster; adding
the parallel lane's 32-number gap-closure list leaves **23 still unresolved**
[S] (22 of them attributed edges, 1 the unattributed 13350 → 12722 [A]).
Nearly all are 1990–93 NARA-codification-gap orders, **except one outlier**:
EO **9397**, targeted by 13478 (`Amendments To Executive Order 9397 Relating
To Federal Agency Use of Social Security Numbers`) — a 1943 Roosevelt-era
order, decades before either the roster's or the gap file's window. Worth
flagging to the parallel lane: "roster + gap" is not a complete closure even
for the numbers this small sample cites.

**Correction to the previous README's promotion policy.** It proposed that a
promoted reader "refuse to mint an edge whose object isn't in
`roster ∪ gap-closure`". That contradicts doctrine.
`mint_executive_order_iri` (`src/refspec/registry/iri_minting.py:500`)
deliberately accepts every positive integer, and says why in its own
docstring: the roster bound "is a dated fact for builders judging pinned
captures … a minter that refused above it would refuse the next order the
President signs" [X]. **The roster is not a minting veto.** Resolution status
is **evidence attached to an edge**, never a fence on identity. The sketch
now emits it that way:

```
subject_iri: urn:rkaf:us:eo:13716
relation:    "amendment of"
attribution: "direct"
object_iri:  urn:rkaf:us:eo:13628
object_resolution_evidence: { in_roster: true, in_roster_plus_gap: true }
witness:     { title, source, source_url, source_sha256 }   -- roster's own columns
```

The sketch prints one edge per attribution grade, including the refusal case
(13350 → 12722, `relation="unattributed"`, `in_roster: false`) [S], so the
shape of a refusal is as concrete as the shape of an assertion.

### Fused-title damage, publisher-side, confirmed against raw JSON

**2 of 185 edges (1.1%)** [A] carry a title that glues the target's own title
onto the amending title with no separator. This is the FR API's own `title`
field, not an artifact of `eo-roster.csv` — verified against the raw capture,
including the identically fused slug:

```json
{ "executive_order_number": "13906",
  "title": "Amending Executive Order 13803Reviving the National Space Council",
  "html_url": ".../amending-executive-order-13803reviving-the-national-space-council" }
```
(`inv-eo/fr-api/fr-executive-orders-page2.json`; the other is 13974/13959.)
Unlike `E5-2394Filed`, this fusion does not corrupt number extraction (`\d+`
stops cleanly), but it corrupts any attempt to split "the stated relation"
from "the target's own name" by string position.

### Free prose: 4 witnesses, 3 distinct edges

The previous README counted "+4 free-prose edges" [X: review report]. Two of the four are
byte-identical witnesses to the **same** edge. The scan now parses actor,
relation and target out of the sentence and reports both counts [S]:

| witness | edge |
|---|---|
| 22 CFR 104 | 13333 —amends→ 13257 |
| 40 CFR 117 | 12777 —supersedes→ 11735 |
| 40 CFR 118 | 12777 —supersedes→ 11735 *(same edge)* |
| Unified Agenda `authority_text` | 13992 —revokes→ 13891 |

**4 witnesses → 3 distinct edges.** Free prose remains a low-volume second
witness source, not a primary harvest surface: 3 edges against 185 from
titles.

---

## Overall verdicts

| family | population in measured corpora | verdict |
|---|---|---|
| Filed-date colophons | 14 specimens / 14 files in the pinned 830-file inventory [S] | **Measure the named local corpora next.** The "no bulk corpus exists" premise was false: a 993-document local FR corpus with full bodies is on disk and 15 of 15 probed XML files carry the colophon [S]. Not a fetch project. |
| Stat.-page lists | 2,995 matches / 343 multi-token notes across 8,240 notes [S] | **Partial fix is promotable; the bug is NOT retired by it.** Gate 1 + gate 2 catch 190 of 516 multi-token matches [S]; `101 Stat. 1568, 1638` → `12 U.S.C. 1638` passes both, and that section exists [X]. |
| EO relation edges | 185 attributed edges (181 direct, 4 coordinated) + 5 refusals across 163 titles; 3 distinct free-prose edges [S] | **Strongest measured signal; owner undecided.** |

### The re-derived recommendation

The previous README said "promote EO amendment chains first". On the
corrected numbers the *evidence* half of that still holds and is stronger:
the yield rose from 145 [X: review report] to **185** attributed edges [S], the relations are now
correct per target rather than uniformly labelled by a title's first verb, the
refusals are explicit, both endpoints are already mintable by shipped code,
and the roster and gap-closure inputs are built by a parallel lane. Nothing in
this lane is net-new machinery.

**The placement half is withdrawn.** This lane asserted a promotion target it
has no standing to assign, and the assignment ran against two documents:

- `docs/decisions.md` REF-048 gives **DocSpec** the document catalog and
  document-processing charter, and states plainly that "RefSpec has no
  platform catalog task … or DocSpec edge" [X].
- `research/fr-body-signal-inventory-2026-08-31.md` ranks
  document-to-document edges as the highest-value uncaptured signal and names
  the owner: **"Owner: DocSpec** (document identity, versions, and exact
  document joins are its charter)", citing the EO amend/revoke chain as its
  first example [X].

So the open question is not *whether* to build this but **who owns it**, and
it is a real fork, not a formality:

- **as a DocSpec document-edge** — an assertion that document 13716 amends
  document 13628, sitting with corrections and republications, which is where
  REF-048 and the body-signal inventory both put it; or
- **as a RefSpec concept-relation** — a relation between two `rkaf:us-eo`
  concepts, which is what `mint_executive_order_iri` already produces and what
  the roster/gap evidence is shaped like.

The two are not the same claim and they do not have the same consumers. This
directory records the measurement and stops there. **The owner decision is
input for REF-048's acknowledged open half, not a finding of this lane.**

Stat.-page lists is the more urgent piece of work even though it is not the
cleanest: it now carries a *corrected diagnosis* of a bug that is already
shipped, and the correction says the previously proposed fix is insufficient.
That is worth more to whoever fixes silent item 4 than a new capability would
be.

Filed-date colophons should not get a reader built against 14 specimens — but
"there is nothing to measure" is no longer true, and the next step is a scan
of named local bytes, not a fetch.

## What the review changed

| # | finding | what changed |
|---|---|---|
| 1 | EO first-verb-applied-to-all-targets | Parser rewritten with per-target clause attribution and graded confidence; 145 → **185** attributed edges + 5 explicit refusals; "only one compound title" corrected to **10 plural-head titles**; free-prose "4 edges" corrected to **4 witnesses / 3 edges**; recommendation re-derived. |
| 2 | "38% false-continuation rate" | Renamed to `two_token_marker_hit_fraction` (37.9%). Actual rate measured by stratified sampling: 60 hand-classified specimens, per-specimen verdicts in `manual_verdicts.json`; **46.2% (CI 42.2–52.9)**. |
| 3 | §301(a) "span" reading | Corrected to Act-opening page + pinpoint page; receipt field renamed; corpus-internal proof added (`101 Stat. 1568` → 1608 / 1638 / 1656 across five notes). |
| 4 | regex required `Stat.` | Widened to `Stat\.?`; 2,973 → **2,995** matches, 342 → **343** multi-token notes, 448 → **451** two-token. |
| 5 | EO promotion policy vs doctrine | Roster-as-mint-fence removed; resolution status is now evidence on the edge; placement recast as an **open owner decision** citing REF-048 and the body-signal inventory. |
| 6 | "retires the 148-fabrication bug" | Downgraded, with the counterexample run through both gates in the script: `101 Stat. 1568, 1638` → `12 U.S.C. 1638` passes both, and that section exists. |
| 7 | filed-date scan not reproducible | Pinned `input_inventory.json` (830 files + 61 MODS, sha256 each); scan reads only the inventory; three drift classes reported; boundary rule for other lanes' raw dirs decided and written down. Population 9 → **14**; time census corrected to 12 of 14 at 8:45 am. |
| 8 | manifest bound outputs only | Every receipt now carries an `inputs` block with path, bytes and sha256 for every input read. |
| 9 | absence claims falsified | Corrected; local corpora named, counted and probed; verdict re-scoped from "fetch a bulk corpus" to "measure the named local corpora". |
| 10 | provenance classes blended | Four classes defined at the top and tagged inline; blanket "every number below is printed by the script" claim removed; MODS claim re-grounded on element/attribute names the scanner now reads. |

## What surprised me

- **The pinned inventory paid for itself immediately.** Including the other
  lane's raw directory — the thing the previous scan excluded by accident —
  surfaced a zero-filled placeholder colophon (`[FR Doc. 94-00000 Filed
  00-00-94; 8:45 am]`) that the existing shape vocabulary happily classifies
  as bare-legacy. The reproducibility fix and a new damage class were the
  same edit.
- **The corpus refutes its own misreading.** The span-versus-pinpoint
  question needed no external document to settle: five notes citing one Act
  with three different second pages make the span reading impossible. The
  external Statutes PDF confirms it; the corpus already proved it.
- **The proposed fix does not fix the bug.** Running the two gates over the
  counterexample instead of reasoning about them turned a promotion pitch
  into a corrected diagnosis. `12 U.S.C. 1638` exists, so no existence oracle
  saves this one either — the fence has to be grammatical, not numerical.
- **Refusing to attribute is more informative than attributing.** The five
  `unattributed` mentions are not parser failures; two of them
  (`Termination of Emergency Declared in Executive Order 12722`) are cases
  where the confident answer is the wrong answer.
