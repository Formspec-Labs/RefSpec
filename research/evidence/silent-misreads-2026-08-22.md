# The silent misreads: measuring the values that parse cleanly into the wrong citation

**2026-08-22.** Measured against artifact
`unified_agenda_legal_authorities.parquet` and grammar commit `06b8d0ef`,
re-checked at `2fc3fc7b`.

Five census waves and five ledger investigations have counted
**loud refusals** — values the parser could not read, now 2,966 of 798,114
legal-authority rows (0.37%). This campaign measures the population nobody has
counted: values that parse **cleanly into the wrong citation**, where no count
surfaces the error and every consumer trusts the answer.

Artifact under measurement:
`output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet`
— 798,114 rows, 42,642 distinct `authority_text`, 46,547 RINs, 60 editions
(199510–202510). Source of truth for behaviour:
`src/refspec/registry/citation_grammar.py`. Nothing in this campaign wrote to
`src/`, `tests/`, or `output/`.

---

## Verdict up front

**About 7% of rows that produced a citation produced the wrong one**
(11/150, 95% CI 4.1%–12.7%) — roughly **twenty times** the 0.37% loud-refusal
rate, or some **57,000 rows** of the 776,470-row frame. Measured per *distinct
string* rather than per row it is **14%** (21/150, CI 9.3%–20.5%), because the
damage concentrates in the long tail. The two prior investigations guessed the
silent population was larger than the refusals. It is, by a wide margin.

Six results matter as much as that number:

1. **Naming the classes does not measure the population.** Sixteen named,
   corpus-wide-counted classes union to roughly **8,000 rows (~1%)**. The
   random audit says 7.3%. That is not a contradiction — it is the residue no
   detector could resolve: the `NNN(x)` vs `NNNx` direction problem (29,557
   rows) and the ~12,000 further rows naming a section the pinned OLRC Table III
   has never seen but which no publisher note either confirms or refutes.
   **Report the sample as the rate and the class list as a floor.**

2. **Nothing fences a U.S.C. section, and that is where the misreads live.**
   `usc_title_is_possible` fences the *title* and returns `true` for every one
   of the twelve sampled citations to sections that do not exist. Corpus-wide,
   **16,884 rows / 1,531 distinct texts carry an `ok` U.S.C. citation whose
   section Table III has never seen.** One mechanism dominates: a
   parenthesised subsection whose parentheses were lost upstream, silently
   retyped as a section suffix — `21 USC 321p` (1,713 rows) for
   21 U.S.C. 321(p), `21 USC 371a` (1,545 rows) for 371(a). The grammar's own
   behaviour is the proof: `21 USC 321(h)` yields section `321` and status
   `partial`; `21 USC 321p` yields section `321p` and status **`ok`**.

3. **One detector works, with measured precision.** Intersecting a publisher
   near-miss (eCFR part authority notes) with two independent referent oracles
   yields **4,455 rows / 202 texts, adjudicated 44/44 correct** — 95% lower
   bound ≈93%. The naive version of the same lever, without the referent
   oracles, scores **12.9%** and should be retired. A full-CFR sweep is about
   two days of polite fetching, once.

4. **The parse is a pure function of the string.** 798,114 rows collapse to
   52,565 distinct (`authority_text`, `citation_ordinal`) keys, of which only
   **8** parse differently in different rows — and all 8 are the declared
   `corroboration_rule` paths that consult context by design. A silent misread
   is therefore a property of a *string*, not of a row, and the whole risk
   surface is 42,642 strings. That is small enough to census, which is why this
   campaign could measure rather than extrapolate.

5. **Copy-forward inverts the majority rule.** A RIN's agenda entry is carried
   forward edition to edition, so a typo entered once propagates into every
   later edition and *becomes the majority reading*. RIN 2120-AH88 states
   `49 USC 100(g)` in 11 editions and the correct `49 USC 106(g)` in one.
   RIN 2060-AS74 states `40 U.S.C. 7651` in 19 editions and the correct
   `42 U.S.C. 7651` in one. **Cross-edition disagreement localises the defect
   but cannot adjudicate it**; that needs an existence oracle. Any future
   detector that resolves disagreement by vote will pick the typo.

6. **Two of the four silent series are unfenced.** `usc_title`,
   `pl_congress`, `stat_volume` and `executive_order` each carry a series-bound
   column, so out-of-series values there are already *loud* (the 298 counted in
   `ledger-2026-08-22/series-bounds.md`). **Federal Register carries no bound
   column at all**, and `FR_VOLUME_HIGHEST_KNOWN = 91` is never applied on that
   path. Volume 643 and volume 552 both sit in the artifact, typed
   `federal_register`, flagged by nothing.

---

## Method

Four independent levers, run against the pinned artifact and against
publishers. Each is reported with its yield **and its precision**, because a
detector that cannot be trusted unattended is a different asset from one that
can.

| lever | what it tests | needs an external oracle? |
|---|---|---|
| **L1 cross-edition disagreement** | same RIN, same citation slot, different reading across editions | no |
| **L2 publisher ground truth** | parsed citation vs the eCFR authority note for the rule's own CFR part | yes (eCFR) |
| **L3 internal contradiction** | the value contradicts itself, or the row's own date, or a pinned publisher index | partly |
| **L4 shape-class review** | what each reader in the grammar accepts that it should not | no |

All four were run. L2 produced the only detector with precision high enough to
trust unattended; L1 and the act-name variant of L3 produced work queues, not
verdicts; L4 produced most of the named classes.

Plus **two uniform random audits** — one over rows, one over distinct strings —
to produce a rate rather than a class count. (A stratified design was
considered and dropped: strata defined by the detectors would have been
correlated with the thing being measured.)

### Denominators

| population | rows | distinct texts |
|---|---:|---:|
| all rows | 798,114 | 42,642 |
| unstated sentinels (`...`, `Not Yet Determined`, …) | 12,464 | 12 |
| loud refusal (`other`/`failed`) | 2,966 | 1,064 |
| `act_relative`/`failed` | 6,214 | 1,184 |
| **audit frame — produced a citation** | **776,470** | **40,389** |
| &nbsp;&nbsp;of which `ok` | 562,949 | 19,540 |
| &nbsp;&nbsp;of which `partial` | 209,896 | 20,058 |
| &nbsp;&nbsp;of which `corroborated` | 3,625 | 791 |

The audit frame is the right denominator: a silent misread can only occur
where a citation was produced. `partial` is **not** by itself an error — it
means the reader did not consume the whole string, not that what it produced
is wrong.

### The artifact is not HEAD — read every count below with this caveat

I re-parsed all 42,642 distinct strings with the grammar as committed at HEAD
and diffed against the pinned parquet. **They disagree on 2,138 texts / 14,611
rows.** Most of that is benign: 1,983 texts are the builder retyping
`act_relative` from the OLRC popular-name index, which a standalone grammar
cannot do. But **140 texts / 4,680 rows carry a citation in the artifact that
HEAD no longer produces at all.**

**HEAD moved during this campaign.** A parallel line of work committed grammar
fixes while these measurements were running, so "HEAD" needs a commit, not a
name. Measured against `06b8d0ef` (HEAD when the diff was taken) and re-checked
against `2fc3fc7b`:

| class | at `06b8d0ef` | at `2fc3fc7b` |
|---|---|---|
| **B0** date-year phantom (848 rows) | **fixed** | fixed — commit `f05791de`, *"a date's comma is the date's own, so no year is a section"* |
| **B2** `NN U.S. NNN` as a case (6 rows) | live | **fixed** — commit `2fc3fc7b`, *"a volume and a page with no case and no year is a lost C"*; `40 U.S. 550` now reads `40 U.S.C. 550` |
| `Secretary's Orders 4-75 and 14-75` (drop) | live | **fixed** — commit `e6514fa7` |
| **B1, B3–B8, A1–A5** | live | **live** — re-tested individually |

That B2 fix uses the same discriminator this campaign derived independently —
*no party name and no year* — which is corroboration of the detector, not of
the count.

So:

- **The artifact is what consumers have**, and every count below describes it.
- **HEAD is what the code does now**, and it is now three classes better.
- A defect read off the grammar is a hypothesis about the artifact, and a
  defect measured in the artifact is a hypothesis about the grammar. Neither
  substitutes for the other, and this campaign found the two out of step in
  both directions.

**None of these fixes changes the measured rate**, because the rate was
measured against the pinned artifact and the artifact has not been rebuilt.
What they change is what a *rebuild* would produce — which is the point of
measuring.

---

## The measured rate

**Two independent random samples of 150 units each, 300 adjudications in
total, every one checked against publishers or against the record's own
siblings.** They measure two different things, and both are worth having.

| estimator | what it answers | count | rate | 95% CI (Wilson) |
|---|---|---:|---:|---|
| **per row** (sample B, uniform over rows) | *a consumer pulls one authority row — how often is it wrong?* | 11 / 150 | **7.3%** | **[4.1%, 12.7%]** |
| &nbsp;&nbsp;+ silently dropped authority | | 13 / 150 | 8.7% | [5.1%, 14.3%] |
| **per distinct string** (sample A, uniform over texts) | *the grammar meets one distinct value — how often does it misread it?* | 21 / 150 | **14.0%** | **[9.3%, 20.5%]** |
| &nbsp;&nbsp;+ silently dropped authority | | 22 / 150 | 14.7% | [9.9%, 21.2%] |
| *(for comparison)* loud refusal | | 2,966 / 798,114 | 0.37% | — |

**The silent population is roughly twenty times the loud one.** Applied to the
776,470-row frame, the per-row estimate is about **57,000 rows** carrying a
wrong citation, 95% interval roughly **32,000–98,000**.

**The per-string rate is twice the per-row rate, and that gap is a finding.**
Misreads concentrate in the long tail: the strings an agency files once or
twice are the damaged ones, while the canonical high-frequency strings
(`5 USC 301`, `42 USC 7401`, `26 USC 7805`) are almost always read correctly.
A consumer weighting by rows is therefore better off than the grammar's raw
accuracy suggests — but any workflow that deduplicates to distinct citations
before use, as a vocabulary or index build would, sees the 14% rate, not 7%.

### How the samples were drawn

Seed fixed at `20260822`. The frame for both is the 776,470 rows with
`parse_status IN ('ok','partial','corroborated')` — a silent misread can only
occur where a citation was produced.

- **Sample B (per row)**: rows ordered by a hash of (`rin`, `publication_id`,
  `ordinal`, `citation_ordinal`), first 150 taken. Resolved to 140 distinct
  strings; all 11 flagged rows had in-sample weight 1, so weighted and
  unweighted rates coincide.
- **Sample A (per string)**: the 40,389 distinct strings ordered by a salted
  hash, first 150 taken.

Each sample was split into two halves adjudicated by independent reviewers
working from the same rubric; no reviewer saw another's batch. Per-batch
results were **8.6% / 10.0%** (row samples) and **16.0% / 13.3%** (string
samples) — consistent within each estimator.

### What the samples caught, and why the class counts miss it

Grouping all 33 adjudicated misreads across both samples by mechanism:

| mechanism | count | examples |
|---|---:|---|
| **produced section does not exist** | 12 | `38 U.S.C. 7009`, `38 USC 3080`, `12 U.S.C. 1701-1`, `21 USC 371a`, `16 USC 7783`, `26 USC 1805`, `42 USC 2101`, `49 U.S.C. 301126`, `54 U.S.C. 1000751(a)`, `16 U.S.C. 4601-6a` |
| **`NNN(x)` vs `NNNx` direction** | 6 | `12 U.S.C. 1829(b)` (means 1829b), `42 USC 629(b)`, `16 U.S.C. …620(f)…`, `16 USC 460(k), … 668(dd), … 690(d), 715(i)` |
| **wrong title, right section** | 3 | `12 USC 78u-2` (is **15** U.S.C.), `35 USC 1123` (is **15** U.S.C.), `332 USC 234 (1947)` (is a *case*) |
| **separator damage** | 4 | `42 USC 247d to 6d` (means 247d-6d), `42 USC 1395i to 2a(d)(2)`, `15 USC 80a 37(a)`, `12 U.S.C. 1861-67` |
| **phantom from a date** | 3 | the class-B0 strings |
| **PL / Statutes disagreement** | 3 | `PL 11-24, 123 Stat 1734`, `PL 105-58, 30 November 1995`, `PL 89-56, 70 Stat 195` |
| **other** | 2 | `EO 8284` (means EO 8248), `26 USC 1.104-1(c)` (a Treasury *regulation* read as 26 U.S.C. §1) |

**The single dominant mechanism is section non-existence** — a third of all
misreads. Nothing in the artifact fences a U.S.C. *section*; `usc_title_is_possible`
fences only the title, and it returns `true` for every one of those twelve.

**Only a handful belong to a class I could count corpus-wide.** That is why
the named classes below sum to roughly **2,000 rows (0.26%)** while the samples
say 7.3% / 14.0% — **the class list is a floor, not the measurement.** The gap
is accounted for, not mysterious: the `NNN(x)` surface alone is 29,557 rows
(3.8% of the frame), and no section-existence check was run at corpus scale.

### Confidence, stated honestly

- n = 150 per estimator is small. The point estimates should not be quoted to
  more than one significant figure: **about 7% per row, about 14% per distinct
  string**.
- Four independent reviewers produced **8.6%, 10.0%, 16.0%, 13.3%** on their
  batches — tight within each estimator, and the between-estimator gap is real
  rather than noise. Still, several calls turn on which of two real sections an
  agency meant, so adjudication variance sits on top of sampling variance.
- Adjudication is **conservative by construction** — the doctrine forces
  `CORRECT` wherever the reading could not be disproved. Era-correct-but-stale
  citations were scored `CORRECT`, as they should be: `49 USC 1371 to 1374`
  (repealed 1994), `40 USC 486(c)` (before the 2002 recodification),
  `41 U.S.C. 418b` (before the 2011 title-41 recodification), `21 USC 134a to
  134h` (repealed 2000). So both rates are more likely under- than over-counts.
- **All four reviewers returned zero `UNKNOWN`s**, which is suspicious in a
  300-item task and is the weakest point in this measurement. Working against
  it: I re-derived the largest disputed specimen myself (`42 USC 2139(a)`,
  387 rows) and found it **is** an honest unknown. Reviewers did flag several
  verdicts as resting on inference rather than documentary proof
  (`PL 101-649` under the wrong act name; `EO 8284`'s intended target; the
  intended target of `26 USC 1805` and `42 USC 2101`) — in each of those the
  *wrongness* is proven and only the *correction* is inferred, which is the
  right side of the line to be uncertain on.
- One reviewer noted a distinction the rubric lacks: a citation that was real
  but had been **repealed or renumbered before the edition that filed it**.
  Scored `CORRECT` here, because the parser read the agency's words faithfully.
  If the question is resolvability-at-filing-date rather than parser fidelity,
  that is a separate and unmeasured class.

---

## Confirmed classes

Every class below is stated with a specimen, a count measured from the
artifact, the evidence that the reading is wrong, and the predicate that
detects it. Classes are split by *whose* defect it is, because the remedy
differs:

- **Family A — laundered source defect.** The agency's text is corrupt; the
  parser reproduced it faithfully and produced a real-looking, wrong citation
  that nothing flags.
- **Family B — grammar misread.** The agency's text is fine; the reading is
  wrong.

### B0. A date's year harvested as a U.S.C. section *(fixed at `f05791de`)*

**111 distinct texts, 848 phantom citation rows** in the artifact. The affected
values carry 4,154 rows in total. **Already fixed at HEAD** — see the artifact
caveat above; this class describes what consumers hold, not what the code does
now. Both sample-A reviewers hit it independently, which is how a class this
size stays invisible: the phantom rides along with seven correct citations.

It is the *strangest* thing the campaign found — not a wrong *reading* of a
citation, but a citation **invented out of prose**. (The largest is the
paren-loss family, 3,300+ rows; see L2 below.)

`_USC_LIST_TAIL` (`citation_grammar.py:501`) continues a U.S.C. section list
across `(?:,|\band\b|\bor\b)` **without requiring that what precedes the
separator be a list member**. A date's own comma qualifies. So:

```
18 USC 3621, 3622, 3624, 4001, 4042, 4081, 4082
   (Repealed in part as to offenses committed on or after November 1, 1987)
```

publishes **eight** citations: the seven real ones, plus **18 U.S.C. 1987**,
harvested from the year in the date. That single value carries 344 rows.

| phantom | distinct texts | rows |
|---|---:|---:|
| 18 U.S.C. **1987** (from "November 1, 1987") | 73 | 451 |
| 18 U.S.C. **1984** (from "October 12, 1984") | 52 | 359 |
| 42 U.S.C. 2020, 42 U.S.C. 1996, 5 U.S.C. 2006, 31 U.S.C. 1951, 7 U.S.C. 1935, 5 U.S.C. 1992, 49 U.S.C. 2006, 50 U.S.C. 2018 | 8 | 38 |

**18 U.S.C. 1987 does not exist.** OLRC returns *"The document you were looking
for does not exist"*
([uscode.house.gov](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title18-section1987&num=0&edition=prelim)),
where the same URL form resolves for the real 18 U.S.C. 1951 — so the 404 is a
genuine refusal, not a broken link. Same for 18 U.S.C. 1984.

**Why this is the worst shape in the report.** The other seven citations in the
value are *correct*. A consumer sees a well-parsed list and has no reason to
doubt the eighth. Nothing marks it: `usc_title_is_possible` is true (title 18
is real), and there is no section fence.

**Mechanically detectable, zero false positives.** Predicate:

```
usc_section ~ '^(1[789]|20)\d\d$'
AND authority_text ~ '<Month>\.?\s+\d{1,2},\s*<that same year>'
```

This is the `Social Security` → `"urity"` defect one layer out: that bug was an
unfenced token *inside* a citation; this is an unfenced *list separator*
between one citation and the prose after it.

### B1. `NNN(x) et seq.` — the subsection is read as the section

**18 distinct texts, 146 rows, 9 distinct (title, section) pairs.**

`et seq.` follows a *section*, never a subsection: "subsection (f) and
following" is not a citation form anyone writes. So where a value says
`NNN(x) et seq.` and `NNNx` is a real section, the agency meant the **lettered
section**, and the parser's section-plus-subsection default is wrong.

| stated | parser produced | truth | rows |
|---|---|---|---:|
| `21 USC 346(a) et seq` | 21 U.S.C. **346** | 21 U.S.C. **346a** (FFDCA §408, pesticide residues) | 35 |
| `42 USC 300(f) et seq` | 42 U.S.C. **300** | 42 U.S.C. **300f** (Safe Drinking Water Act) | 32 |
| `16 USC 460(k) et seq` | 16 U.S.C. **460** | 16 U.S.C. **460k** (Refuge Recreation Act) | 31 |
| `16 USC 742(a) et seq` | 16 U.S.C. **742** | 16 U.S.C. **742a** (Fish and Wildlife Act 1956) | 22 |
| `16 USC 791(a) et seq` | 16 U.S.C. **791** | 16 U.S.C. **791a** (Federal Power Act) | 11 |
| `42 USC 2000(d) et seq` | 42 U.S.C. **2000** | 42 U.S.C. **2000d** (Civil Rights Act Title VI) | 6 |
| `7 USC 136(a) et seq` | 7 U.S.C. **136** | 7 U.S.C. **136a** (FIFRA registration) | 5 |
| `25 USC 396(A) et seq` | 25 U.S.C. **396** | 25 U.S.C. **396a** (Indian mineral leasing) | 2 |
| `16 USC 590(a) et seq` | 16 U.S.C. **590** | 16 U.S.C. **590a** (Soil Conservation) | 1 |

**This is the defining shape of the whole campaign: nearly every produced
section is real, so nothing refuses it.** 42 U.S.C. 300 exists — "Project
grants and contracts for family planning services"
([Cornell LII](https://www.law.cornell.edu/uscode/text/42/300)) — so a drinking
water rule now cites a family planning grant section, and nothing anywhere
says so. 21 U.S.C. 346 exists as a food-additive tolerance section, distinct
from 346a "Tolerances and exemptions for pesticide chemical residues"
([uscode.house.gov](https://uscode.house.gov/view.xhtml?req=(title:21+section:346a+edition:prelim))).
16 U.S.C. 460 exists; 16 U.S.C. 460k is the Refuge Recreation Act
([uscode.house.gov](https://uscode.house.gov/view.xhtml?req=(title:16+section:460k+edition:prelim))).

One member of the class is *not* real-but-wrong: **42 U.S.C. 2000 does not
exist**. Title 42 chapter 21 runs 2000a, 2000b, 2000c, 2000d, 2000e … with no
bare section 2000
([subchapter V](https://www.govinfo.gov/content/pkg/USCODE-2008-title42/pdf/USCODE-2008-title42-chap21-subchapV.pdf)).
It is still silent — `usc_title_is_possible` fences the *title* and nothing
fences the *section* — but it would be caught by a section-existence check,
where the other eight would not.

**Mechanically detectable, high precision.** Predicate:

```
regexp_matches(authority_text, usc_section || '\([a-zA-Z]\)\s*,?\s*et\.?\s*seq')
AND (usc_section || letter) is a real section in usc_title
```

18/18 hits survived inspection. Two were verified at publishers; the remaining
seven (title, section) pairs are canonical act anchors.

**Bounding the wider surface.** See "The largest unresolved surface" below:
`NNN(x)` where `NNNx` is also a real section covers **~1,469 texts / ~29,557
rows**, and the `et seq.` tell is only one discriminator within it.

### B2. `NN U.S. NNN` — a U.S.C. section is read as a Supreme Court case *(fixed at `2fc3fc7b`)*

**2 distinct texts, 6 rows silent. 9 texts / 12 rows of the same family refuse
loudly.**

The whole family is one missing `C`. The period decides whether the corpus
gets a loud refusal or a silent lie:

| text | typed | rows |
|---|---|---:|
| `40 U.S. 550` | **`case_citation`, ok** | 4 |
| `43 U.S. 1763` | **`case_citation`, ok** | 2 |
| `42 US 2201`, `15 US 1392`, `30 US 820`, `7 U.S. 6g`, `42 US 1396b(q)`, `50 US 2401 et seq`, `49 US 44719`, `49 U.S 41102, …`, `42 US. 7401 et seq.` | `other`, failed | 12 |

Both silent values are settled by two independent lines of evidence.

- **`43 U.S. 1763`** — RIN 1004-AF32 (BLM). Its sibling authorities in the
  same record are `43 U.S.C. 1740` and `43 U.S.C. 1733`, both FLPMA; 43 U.S.C.
  1763 is FLPMA's rights-of-way section. And U.S. Reports **volume 43 (2 How.,
  1844) has 792 pages**
  ([LoC](https://www.loc.gov/collections/united-states-reports/about-this-collection/united-states-reports-by-volume/)),
  so page 1763 does not exist. The parser produced a **nonexistent case**.
- **`40 U.S. 550`** — RIN 0991-AC14 (HHS). Its sibling authorities are
  `45 CFR 12a` and `42 U.S.C. 11411` — use of surplus federal property to
  assist the homeless. 40 U.S.C. 550 is "Disposal of surplus real property for
  specific purposes", the exact companion authority. Here the produced case
  citation is *page-plausible* (volume 40 reaches page 550), so the page-bound
  test does not catch it; the record's own siblings do.

**Mechanically detectable.** Predicate: `authority_type = 'case_citation'` with
**no party name and no year** in the text. That predicate returns exactly these
two values and nothing else — precision 2/2 on this corpus. A second,
independent predicate — U.S. Reports page exceeding the volume's page count —
catches `43 U.S. 1763` alone.

This is the silent complement to the 12 reporter citations the ledger already
counts as loud in `series-bounds.md` family C.

### A1. Public Law cited beside the wrong Statutes at Large volume

**Population: 809 texts / 8,716 rows carry exactly one Public Law and exactly
one Statutes volume. 21 texts / 122 rows contradict.** Of those, **14 texts /
88 rows** are in the single-authority shape where the detector is sound; the
other 7 texts / 34 rows are "act A at Stat X *as amended by* act B" strings
where my pairing is not entitled to assume the two belong together.

**The oracle is derived, not assumed.** From the pinned OLRC indexes
(`usc-popular-names`, `usc-act-sections`, `usc-source-credits`) the minimum
Statutes volume observed for Congress *C* equals **2C − 99** for **all 35
congresses** with coverage (85th–119th), with volumes running {2C−99, 2C−98}.
Extrapolated to the 73rd this predicts {47, 48}, and Pub. L. 73-416 is at
48 Stat. 1064
([HeinOnline](https://heinonline.org/HOL/LandingPage?handle=hein.leghis/comuna0006&div=1),
[Cornell TOPN](https://www.law.cornell.edu/topn/communications_act_of_1934)).

Excluding the three `PL 108-199, 188 Stat 445-46` variants (18 rows), whose
volume 188 is **out of series and already flagged loud** — they belong to the
ledger's 298, not here — the silent single-shape population is **11 texts /
64 rows**:

| stated | produced volume | truth | rows | how established |
|---|---|---|---:|---|
| `PL 92-500 76 Stat. 816` (2 variants) | **76** | **86** Stat. 816 | 22 | publisher: [govinfo STATUTE-86-Pg816](https://www.govinfo.gov/content/pkg/STATUTE-86/pdf/STATUTE-86-Pg816.pdf) |
| `Pub. L. 105-115, 11 Stat. 2322 (21 U.S.C. 355 note)` | **11** | **111** Stat. 2296 ff. | 6 | publisher: [govinfo PLAW-105publ115](https://www.govinfo.gov/link/statute/111/2296) |
| `PL 104-191, 101 Stat 1936 (HIPAA)` | **101** | **110** Stat. 1936 | 4 | publisher; the value names HIPAA itself |
| `Pub. L. 98-192, Dec. 15, 1971, 85 Stat. 646` | **85** | the *volume* is right; the **PL number** is wrong — Dec. 15 1971 is the 92nd Congress | 8 | the value carries its own date |
| `PL 89-56, 70 Stat 195` (3 variants) | **70** | expect 79/80 | 14 | formula only — **not individually verified** |
| `Pub. L. 98-80, 84 Stat. 2086` | **84** | expect 97/98 | 6 | formula only — **not individually verified** |
| `PL 99-625, 10 Stat 3500` | **10** | **100** Stat. 3500 | 4 | formula + lost trailing digit |

And separately, in the "as amended" shape where my pairing is weaker but the
value is unambiguous:

| stated | produced volume | truth | rows | how established |
|---|---|---|---:|---|
| `…of Pub. L. 73–416, 4 Stat. 1064, as amended` | **4** | **48** Stat. 1064 | 18 | Statutes vol. 4 covers **1824–1835, 19th–23rd Congress** ([LoC](https://www.loc.gov/item/llsl-v4/)); Communications Act of 1934 at 48 Stat. 1064 ([Cornell TOPN](https://www.law.cornell.edu/topn/communications_act_of_1934)) |

Every produced volume here is a **real Statutes at Large volume**, which is
exactly why nothing refused it. Volume 4 is 1824–1835; volume 76 is 1962;
volume 11 is 1855–1859.

**Verification status, stated plainly:** 4 of the 11 silent texts (28 rows,
plus the 18-row `73-416` case) are confirmed against a publisher; 1 (8 rows) is
settled by the value's own internal date; the remaining 4 texts (24 rows) are
detector hits consistent with a formula validated on 35 of 35 congresses but
**not individually looked up**, because this session exhausted its web-search
budget. I do not claim them as confirmed.

**Mechanically detectable with a caveat.** Predicate: one PL + one Stat volume
in a value, and `statute_volume` outside `[2C−100, 2C−97]`. To lift precision,
require the Stat cite to be textually adjacent to the PL, which removes the
"as amended by" shape.

### B3. A U.S.C. section wearing a "CFR" label becomes a CFR part

**21 distinct texts / 126 rows** under the tight predicate; **79 texts / 445
rows** under a broader one that admits ~3 false positives (5 CFR parts 2, 5
and 6 are real Civil Service Rules).

`parse_authority_citation` calls `parse_cfr_citations`, checks
`title_is_possible`, and **discards `part_is_plausible` entirely** —
`AuthorityCitation` has no field to carry it. So an implausible part is minted
with no flag:

| stated | produced | truth | rows |
|---|---|---|---:|
| `49 CFR 30166` | 49 CFR **part 30166** | 49 **U.S.C.** 30166 (the same RINs write `49 USC 30166` in other editions) | 30 |
| `19 CFR 1202` | 19 CFR part 1202 | 19 U.S.C. 1202 (Tariff Act) | 10 |
| `42 CFR 1395r` | 42 CFR part 1395r | 42 U.S.C. 1395r — the same RIN also files `Sec 1839 of the Social Security Act`, which *is* 42 U.S.C. 1395r | 5 |
| `12 CFR 1467a` | 12 CFR part 1467a | 12 U.S.C. 1467a | 3 |
| `42 CFR 1395w-4` | 42 CFR part **1395w** | 42 U.S.C. 1395w-4 — **and the `-4` is truncated**, because `_CFR_PART_CAPTURE` is `\d+[A-Za-z]?` | 1 |

Title 49's real CFR parts top out at 3893, and none of these (title, part)
pairs appears among the 29,503 entries in
`unified_agenda_cfr_references.parquet`.

**Mechanically detectable.** `authority_type='cfr'` AND the same RIN carries a
`usc` row with `usc_title = cfr_title` AND `usc_section = cfr_part` AND the
pair is absent from the CFR reference table AND `cfr_part >= 100`.

### B4. A treaty series read as the Code

**3 texts / 38 rows.** The corpus contains the same instrument spelled both
ways, which settles it without any external oracle:

| text | produced | rows |
|---|---|---:|
| `27 U.S.T. 1087` | treaty, UST 27:1087 — **correct** | 5 |
| `27 UST 1087, Convention on International Trade in Endangered Species…` | treaty, UST 27:1087 — **correct** | 5 |
| `27 U.S.C. 1087` | **usc 27:1087**, status `ok` | 22 |
| `27 USC 1087` | **usc 27:1087**, status `ok` | 11 |
| `Convention on International Trade in Endangered Species of Wild Fauna and Flora (March 3, 1973), 27 USC 1087` | **usc 27:1087** | 5 |

CITES is at 27 U.S.T. 1087. Title 27 of the Code is Intoxicating Liquors and
has no section 1087 (OLRC returns not-found). The last row is the sharpest: the
value **names the Convention** and still yields a Code citation. `_USC_STANDARD`
wins on the label; `_TREATY_UST` never sees the value.

### B5. An abbreviated range published as one section identity

**187 texts / 1,007 rows** under the loose predicate (79 texts / 406 rows under
the tightened one below).

GPO and Bluebook 3.2(a) abbreviate an inclusive span by dropping repeated
leading digits, so `2671-80` means §§2671–2680. The grammar keeps it as one
opaque token — a documented choice — but the token then lands in the
`usc_section` **identity** column with no flag, indistinguishable from a real
compound name like `1395w-4`.

- `28 U.S.C. 509, 510 1346(b), 2671-80` → a section named `2671-80` (the FTCA,
  §§2671–2680; 28 U.S.C. 2680 "Exceptions" is real)
- `29 U.S.C. 1021, 1023-24, 1026-27, 1029-30, and 1135` → three sections named
  `1023-24`, `1026-27`, `1029-30`
- `49 U.S.C. … 20137–38, … 20701–03, 21301–02, …` → three more
- `31 U.S.C. sec. 3801-12` → `3801-12`

**Mechanically detectable, with one load-bearing guard.**
`usc_section ~ '^(\d+)-(\d{2,})$'` AND `len(leaf) < len(stem)` AND
`stem[:-len(leaf)] + leaf > stem` AND the gap ≤ 99. **The two-digit minimum on
the leaf is essential**: without it the predicate wrongly flags the real
sections 42 U.S.C. 288-1…288-6, 7 U.S.C. 1358-1 and 26 U.S.C. 460-6.

### B6. `0` for `o` in a section, and other lookalike substitutions

**14 texts / 40 rows.** `_WHOLE_VALUE_LABEL_REPAIRS` carries
`letter-o-for-zero-in-usc-title` for the *title* (`3o USC` → `30 USC`); the
mirror damage in the *section* has no reader and no flag.

`15 USC 780-5(b)` → section `780-5`, where RIN 1505-AA70 writes
`15 USC 78o-5(b)` in other editions — the Exchange Act §15O-5. Also
`15 U.S.C. 780-10(b)(6)`, `15 USC 780-11`, `16 USC 8240` for `824o`,
`15 USC 16930` for `1693o`.

**A near-miss worth recording**: the bare `15 U.S.C. 780` is **not** provably
wrong — §780 exists ("Office of Private Grievances and Redress"). Only the
*compound* forms are impossible, because that chapter has no compound-named
siblings while the Exchange Act's 78o-3/-5/-10/-11 do.

### B7. Smaller confirmed classes

| class | reader | texts | rows | specimen |
|---|---|---:|---:|---|
| E.O. compilation year → CFR part | `_EO_COMPILATION` `:356` fails to divert, `_CFR_STANDARD` mints a part | 6 | 12 | `3 CFR 1949-53 Comp., sec 2` → CFR title 3 **part 1949**. The module's own docstring says "there is no 3 CFR § 1977, and a CFR grammar that reads one fabricates a citation" |
| stated section eats a word | `_STATED_SECTION` `:2339` capture runs across a lost space | 5 | 14 | `…Sec 6002Omnibus Budget Reconciliation Act of 1993` → `stated_section='6002Omnibus'`; `Other sections of FDA Food Safety Modernization Act` → `stated_section='of'` |
| paragraph absorbed into instrument number | `_ADMINISTRATIVE_ORDER` `:644` treats a trailing `(\d+)` as a revision | 8 | 61 | `DHS Delegation No. 0170.1(92)` → number `0170.1(92)`, while the sibling `DHS Delegation No. 0170.1, para (92)` → `0170.1`. Two identities for one instrument |

### B8. A subsection on a section that has none

**30 distinct texts, 205 rows, 45 RINs** — for 42 U.S.C. 1395 alone.

42 U.S.C. **1395** is "Prohibition against any Federal interference", a single
undivided sentence with **no subsections at all**
([Cornell LII](https://www.law.cornell.edu/uscode/text/42/1395)). So every one
of these is structurally impossible as written, and each names a real Medicare
section that the parser threw away:

| stated | produced | truth | rows |
|---|---|---|---:|
| `42 USC 1395(hh)` (+ 3 variants) | 42 U.S.C. **1395** | **1395hh** "Regulations" — CMS's actual rulemaking authority | 78 |
| `42 USC 1395(fff)` (+ variant) | 1395 | **1395fff** (home health PPS) | 28 |
| `42 USC 1395(cc)` (+ variant) | 1395 | **1395cc** (provider agreements) | 29 |
| `42 U.S.C. 1395(m)`, `1395(x)`, `1395(rr)1`, `1395(bb)`, `1395(g)`, `1395(h)`, `1395(i)`, `1395(l)`, `1395(n)`, `1395(o)`, `1395(a)` | 1395 | the corresponding lettered sections | 70 |

The corpus proves its own convention: the correct `42 U.S.C. 1395hh` appears
**1,144 times** against ~78 for the parenthesized form. The result is that CMS
appears to cite the *anti-interference clause* as its rulemaking authority,
and a consumer asking which rules rest on 42 U.S.C. 1395hh misses all 205 rows.

**This is the discriminator the whole `NNN(x)` surface needs**, demonstrated on
one section: *does the bare section actually have that lettered subsection?*
Where it has none, the call is mechanical and certain.

### A4. The reverse: a subsection rendered as a lettered section

**1,545 rows across 138 RINs — the single largest confirmed specimen in the
campaign.**

`21 USC 371a` (1,494 rows) and `21USC 371a` (51 rows) parse to section `371a`
with **`parse_status: ok`**. **21 U.S.C. 371a does not exist** — OLRC returns
*"The document you were looking for does not exist"*
([uscode.house.gov](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title21-section371a&num=0&edition=prelim)).
The intended citation is 21 U.S.C. **371(a)**, FD&C Act §701(a), FDA's general
rulemaking authority — which the corpus also carries, 293 times, as
`21 U.S.C. 371(a)` / `21 USC 371(a)`.

The decisive evidence is a same-RIN in-place correction: **RIN 0910-AF82 files
the same rule at the same ordinal slot** as `21 USC 371a` from 200604 through
201410, as `21 U.S.C. 371a` in 201504, and as `21 U.S.C. 371(a)` from 201510
onward. The agency fixed its own rendering; the parser accepted both and
flagged neither.

Note this runs **opposite** to class B1: there the parenthesised letter was
really a section suffix, here a letter suffix is really a subsection. **The
direction cannot be guessed from shape — only section existence settles it**,
which is precisely why the unresolved surface below is unresolved.

### A5. A zero-padded section carried into the identity field

**101 distinct texts, 943 rows, 48 distinct (title, section) pairs — 941 rows
of them in title 26.**

`26 U.S.C. 0989(c)` publishes `usc_section = "0989"`. IRC §989 exists; §0989
does not. The pad is the agency's own convention — RIN 1545-BL12 files
`26 USC 0987` and `26 USC 0989(c)` (the §987/§989 foreign-currency pair)
alongside an unpadded `26 USC 7805` — and the grammar carries it straight into
the identity column.

The referent is recoverable, so this is the mildest class in the report, but
it is a **join-breaking** defect: any consumer matching on (title, section)
misses all 943 rows, and nothing says so.

**Mechanically detectable and exactly fixable**: `usc_section ~ '^0[0-9]'`,
precision 100% (no U.S.C. section is legitimately zero-padded).

### A2. Section magnitudes impossible for their title

**9 distinct texts, 41 rows.** No external oracle required.

`usc_title_is_possible` fences the title; **nothing fences the section**. Using
the corpus itself as its own oracle — the 99th-percentile section number
attested for each title, across 12,608 distinct citations — nine values sit
more than ten times above their title's ceiling:

| stated | produced | truth | rows |
|---|---|---|---:|
| `33 U.S.C. 70116` | 33 U.S.C. 70116 | **46** U.S.C. 70116, "Port, harbor, and coastal facility security" | 9 |
| `33 U.S.C. 70034` | 33 U.S.C. 70034 | title 46, not 33 | 9 |
| `42 USC 512651c(C)` | 42 U.S.C. 512651c | damaged beyond recovery | 8 |
| `29 USC 60129` | 29 U.S.C. 60129 | title 29 stops near 3211 | 4 |
| `21 USC 890890` | 21 U.S.C. 890890 | a doubled token | 3 |
| `47 USC 44715`, `47 USC 44712` | title 47 | **49** U.S.C. 44712/44715 (aviation, not telecom) | 4 |
| `8 USC 81611-1613` | 8 U.S.C. 81611-1613 | the title glued to `1611-1613` | 2 |
| `26 U.S.C. 7805 and 98332` | 26 U.S.C. 98332 | — | 2 |

There is no 33 U.S.C. 70116; the Ports and Waterways Safety Act provisions
were transferred into title 46
([uscode.house.gov](https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title46-section70116&num=0&edition=prelim)).

**Mechanically detectable at zero oracle cost.** A real section-existence
oracle would find these and more; this heuristic finds the grossest of them
using only the artifact, which makes it cheap enough to run in CI.

### A3. Federal Register volume and page have no series fence

**4 distinct texts, 6 rows.**

| text | produced | truth |
|---|---|---|
| `Notice of August 13, 1998 (643FR 44121)` | FR vol **643** | **63** FR 44121 (1998) |
| `Notice of August 14, 1996 (610 FR 42527)` | FR vol **610** | **61** FR 42527 (1996) |
| `E.O. 12600, 552 FR 23781` | FR vol **552** | **52** FR 23781 (1987) |
| `Notice of August 14, 1996 (61 FR 425527)R` | FR page **425527** | 61 FR **42527** |

Federal Register volume 1 is 1936, so an edition published in YYYY cannot cite
a volume above YYYY−1935. All four are impossible on that arithmetic, and all
four are typed `federal_register` with **no flag of any kind**. The grammar
declares `FR_VOLUME_HIGHEST_KNOWN = 91` and `FR_PAGE_HIGHEST_KNOWN = 100_000`
and applies neither on this path.

**Mechanically detectable, exactly.** Predicate:
`fr_volume > CAST(substr(publication_id,1,4) AS INT) - 1935` or
`fr_page > 100000`. Precision 4/4.

The asymmetry is the finding: four series carry a bound column and are
therefore loud; Federal Register carries none and is therefore silent. The
population is tiny, but the *fence* is missing, not merely unexercised.

---

## The largest unresolved surface: `NNN(x)` where `NNNx` is also a section

**~1,469 distinct texts, ~29,557 rows.** This is where most of the remaining
risk lives, and I could not settle it.

When a value says `NNN(x)`, two readings are available: section `NNN`,
subsection `(x)`; or the lettered section `NNNx`, with the parentheses being
the agency's punctuation. The grammar always takes the first. The corpus
splits into three tiers:

| tier | texts | rows | risk |
|---|---:|---:|---|
| `NNN(x) et seq.` — "et seq." follows a section, never a subsection | 18 | 146 | **confirmed misread** (class B1) |
| the **same RIN** files both `NNN(x)` and `NNNx` | 377 | 1,851 | elevated — but not automatically wrong |
| only the wider corpus attests `NNNx` | 1,092 | 27,706 | default reading is right almost always |

**The middle tier is not a defect count, and treating it as one would be the
mistake this doctrine exists to prevent.** `5 USC 552(a)` really is FOIA
subsection (a), and 5 U.S.C. 552a really is the Privacy Act — an agency citing
both is normal. `8 U.S.C. 1324(a)` and `1324a` are likewise both real and
routinely cited together.

**The 387-row case I could not settle.** `42 USC 2139(a)` (387 rows, 115 RINs)
parses to section 2139. The same community files `42 USC 2139a` 1,334 times
(396 RINs). That asymmetry looks like a smoking gun — but it is not:

- 42 U.S.C. **2139** is "Component and other parts of facilities" and **does
  have a subsection (a)**, "Licenses for domestic activities"
  ([Cornell LII](https://www.law.cornell.edu/uscode/text/42/2139)).
- 42 U.S.C. **2139a** is "Regulations implementing requirements relating to
  licensing…", and **its** subsection (a) is marked *Omitted*
  ([Cornell LII](https://www.law.cornell.edu/uscode/text/42/2139a)).

So `2139(a)` is a structurally valid citation to a real subsection of a real
section. Which one the agency meant cannot be derived from the text plus a
declared convention, and no pinned oracle settles it. **I record it as an
honest unknown, not a misread**, and note that a row-count argument alone would
have called it wrong.

**What would settle the tier.** Not section existence — *subsection* structure.
The clean predicate is:

```
flag NNN(x) where section NNN exists but has NO lettered subsection (x),
and section NNNx does exist
```

`42 USC 629(b)` is the worked example: 42 U.S.C. 629 has only unlettered
paragraphs (1)–(4), so `629(b)` cannot be a valid pinpoint into it, while
42 U.S.C. **629b** "State plans" is real — and HHS/ACF RIN 0970-AC33 filed the
identical authority list once as `42 USC 629b(a), 42 USC 652(a), …` and once as
`42 USC 629(b)(a), 42 USC 652(a), …`. Likewise 21 U.S.C. 346 today has no
subsections at all (subsec. (a) was redesignated as the whole section), so
`346(a) et seq.` is structurally impossible.

That predicate needs subsection-level structure from the U.S.C. XML, which this
campaign did not have in hand. **It is the highest-value unexplored seam, and I
am naming it rather than guessing at its yield.**

---

## Publisher ground truth (L2): the detector that works

**This is the campaign's most useful artifact: a detector with measured
precision near 100%, and a corpus-wide lead population that sizes the biggest
open question.**

287 CFR part authority notes were fetched from the eCFR versioner API at date
2026-08-20, chosen by greedy set-cover over the agenda→CFR mapping to maximise
authority rows covered per fetch. **Coverage: 489,232 of 798,114 rows (61.3%),
20,670 of 42,642 distinct texts (48.5%), 22,787 RINs, all 60 editions.** The
note extractor was written independently of `citation_grammar.py` on purpose,
so the oracle shares no code with the thing under test.

### The loose detector is nearly worthless, and that is worth knowing

Classify each parsed citation as PRESENT in the part's note / NEAR-MISS-PRESENT
(a note citation one edit away) / ABSENT:

| verdict | rows | distinct texts |
|---|---:|---:|
| PRESENT in the note | 308,388 | 9,843 |
| NEAR-MISS-PRESENT | 49,409 | 3,510 |
| ABSENT, no near miss | 103,076 | 7,727 |

Adjudicating 31 random near-miss texts (428 rows) gives **precision 12.9% by
text, 5.6% by rows**. The bucket is dominated by agencies legitimately citing a
real neighbouring section. **"A neighbouring section exists in the note" is not
evidence of anything** — which retires the most obvious form of this lever.

### The sharp detector: near-miss AND impossible referent

Add two independent referent oracles — the parsed section must be **absent from
OLRC Table III** (built from this repo's own pinned
`olrc-table3-xml-bulk-119-73.zip`, 69,597 title/section pairs, calibrated at
**99.0% recall** against 1,139 sections the publisher's own notes cite) **and**
return not-found at OLRC/Cornell today.

> **Sharp population: 4,455 rows / 202 distinct texts / 178 distinct impossible
> sections / 386 RINs, all 60 editions. Every one is `parse_status = 'ok'`.**
>
> **Adjudicated: 44 distinct texts (767 rows, 17% of the population), sampled
> systematically. 44 true misreads, 0 false. Precision 100%, 95% lower bound
> ≈ 93% by the rule of three.**

Both oracles are load-bearing. Table III alone false-positives on positive-law
codifications (26 U.S.C. 6165 is real; so is all of title 54), and the note
itself refutes 1,026 rows / 101 texts of Table III leads by listing them.
Requiring the **near miss** is what separates a mis-keyed digit from a merely
old citation form — the ABSENT-no-near-miss bucket turned out to be dominated
by *superseded but real* codifications: `10 U.S.C. 7429` (renumbered 2018),
`42 U.S.C. 1857 et seq.` (the pre-1977 Clean Air Act), `46 U.S.C. app 466c`.

### The publisher confirms this campaign's own opening specimen

`40 U.S. 550` (4 rows, `ok`) belongs to RIN 0991-AC14, whose CFR part is
45 CFR 12a. **That part's entire authority note reads:
"42 U.S.C. 11411; 40 U.S.C. 550."** The reading is settled by the publisher, in
the publisher's own words — and note the recall lesson: 45 CFR 12a is a tiny
part that the top-300 set did not include, and had to be fetched by hand.

### Specimens

| stated | produced (`ok`) | the publisher's note | rows |
|---|---|---|---:|
| `21 USC 321p` | 21 U.S.C. **321p** | 21 CFR 310: *"…351, 352, 353, 355, 360b-360f, 360j, 360hh-360ss, **361(a)**, 371…"* — the value is 21 U.S.C. **321(p)**, the FDCA "new drug" definition | **1,713** |
| `5 U.S.C. 533` | 5 U.S.C. **533** | 29 CFR 1910: *"…and **5 U.S.C. 553**, as applicable"* — the APA | 56 |
| `8 USC 552a` | 8 U.S.C. **552a** | 8 CFR 103: *"**5 U.S.C. 301, 552, 552a**; 8 U.S.C. 1101…"* — two titles collapsed into one | 28 |
| `EO 1293` | E.O. **1293** | 15 CFR 742/744/774: **E.O. 12938** — a 1910 Taft order cannot authorise a 1990s export rule | 16 |
| `Pub. L. 111-2013` | Pub. L. **111-2013** | 17 CFR 240: **Pub. L. 111-203** (Dodd-Frank); the 111th Congress ended at 111-383 | 11 |
| `17 USC 12a`, `17 USC 6f`, `17 USC 6g` | title **17** | 17 CFR 1: *"**7 U.S.C.** 1a, 2, 5, 6, 6a … 6f, 6g … 12a"* — the CFR title written where the U.S.C. title belongs | 3+ |
| `12 U.S.C. 1601 et seq.` | 12 U.S.C. 1601 | 12 CFR 1026: *"**15 U.S.C. 1601 et seq.**"* — TILA, the statute Reg Z exists to implement | 1 |
| `42 U.S.C. 4311 to 4312, sec. 701.35` | 42 U.S.C. 4311-4312 | 12 CFR 701: *"**Section 701.35** is also authorized by **12 U.S.C. 4311-4312**"* | — |

Two candidates were **rejected** on inspection, which is the oracle working:
`26 USC 6165` is a real section Table III simply does not enumerate, and
`21 USC 134a to 134d` were real animal-quarantine sections until their 2002
repeal — and every agenda row citing them predates that.

### The paren-loss family, now the largest named class

The specimens above expose one mechanism repeatedly: **a parenthesised
subsection whose parentheses were lost upstream, silently retyped as a section
suffix.** The decisive control is inside the grammar itself — `21 USC 321(h)`
yields section `321`, status `partial`, while `21 USC 321p` yields section
`321p`, status **`ok`**. Parentheses are handled; paren-less letters are not
questioned.

| specimen | rows | truth |
|---|---:|---|
| `21 USC 321p` | 1,713 | 21 U.S.C. 321(p) |
| `21 USC 371a` (+ `21USC 371a`) | 1,545 | 21 U.S.C. 371(a) |
| `47 USC 154i`, `49 USC 114l`, `42 USC 416i`, `12 USC 1828c`, `26 USC 7805A`, `21 USC 361a` | tens | the parenthesised subsection |

**Together this family exceeds 3,300 rows** — larger than any other named
class, and larger than the loud-refusal population it hides behind.

### Cost to run at corpus scale

Measured greedy curve: 300 parts → 62.8% of rows; 500 → 70.8%; 1,000 → 80.7%;
2,000 → 88.6%; all 5,968 current parts → 94.4% (the ceiling is rows whose
agenda entry names no CFR part). At a polite 4–8 streams that is ~12 hours to
2 days, **one time**, ~650 MB cached, refreshed annually. Extrapolated yield:
roughly **7,000–8,000 rows / ~330 distinct texts** in the sharp tier at ≥93%
precision — a hand-checkable answer key for thirty years of the Agenda.

One structural caveat: the detector's power comes from an **impossible-referent
oracle**, which exists for U.S.C. sections and **does not exist for E.O. or
Public Law numbers**, where every in-range number names a real instrument. The
`EO 13020` vs `EO 13026` pairs could not be settled. A date-plausibility rule
would recover the `EO 1293` / `E.O. 1205` family cheaply.

---

## Cross-edition disagreement (L1): a locator, not an adjudicator

**1,579 near-miss pairs across 1,047 RINs**, where the same RIN states two
citations of the same kind differing by one edit (one dropped/added leading or
trailing character, one substitution, or one transposition) in *disjoint* sets
of editions.

| shape | pairs | RINs | singleton minority |
|---|---:|---:|---:|
| minority is an early spelling, later changed | 853 | 590 | 474 |
| minority is a late spelling, changed and kept | 627 | 400 | 265 |
| **reverted blip** (majority, then minority, then majority again) | **94** | **73** | **55** |
| other | 5 | 5 | 0 |

The reverted blip is the highest-confidence shape — a list that goes A, A, A,
B, A, A, A is a transcription slip, not an amendment. Adjudicating all 55
singleton blips by hand yields three groups:

- **Genuine defects** — `16 U.S.C. 777U.S.C.` → section `777u` (the suffix
  reader absorbed the `U` of a duplicated label; the RIN's other 11 editions
  say `777`); `5 USC 2611, TSCA 12.` → title 5 where TSCA is title 15;
  `26 USC 60505` → the real `6050S`; `42 USC 740 to 7671q` → `7401 to 7671q`;
  `19 USC 13902` and `44 USC 44716` for `49 USC …`.
- **Legitimate amendments** that the near-miss rule cannot distinguish — an
  agency adding `21 USC 360c, 360e` beside `360j`, or restating
  `49 USC 60101 et seq.` as the enumerated list `60102, 60103, 60104 …`.
  RIN 2137-AD68 alone generates five spurious pairs this way.
- **Cases where the majority is the typo**, described in the verdict above.

**Precision is moderate and the detector cannot decide direction.** Its value
is that it is free, needs no oracle, and reduces 42,642 strings to ~100 worth
looking at. Treat its output as a work queue, never as a verdict.

---

## Measured negatives, and four "impossible" claims I had to withdraw

The doctrine says a claim that a reading is wrong needs the same evidence a
recovery needs. Holding to it killed several of my own leads, and those
retractions are results.

**Metamorphic invariance: essentially clean.** I re-parsed all 42,642 distinct
texts under 19 meaning-preserving rewrites (`U.S.C.`↔`USC`↔`U. S. C.`,
`Pub. L.`↔`PL`↔`Public Law`, `§`↔`Sec.`↔`Section`, dash normalisation,
whitespace collapse, `et seq.` spelling, CFR and E.O. label forms). **No live
value changes its citation under any rewrite that is genuinely
meaning-preserving.** The 150 raw differences were mine: my `§`→`Sec.` rewrite
silently converts a plural label to singular, which legitimately changes list
expansion, and my `U.S.C.` rewrite mangles `U.S.C.A.` into `U.S.C..A.`. The
one true fragility — 24 texts whose parse changes if a space is doubled — is
**latent, not live**: the corpus contains **zero** multi-space runs, tabs,
newlines or untrimmed values in 798,114 rows.

**Descending U.S.C. ranges: zero.** My first pass reported 409 texts / 4,464
rows by comparing the numeric prefix only. `15 USC 717 to 717w` is not
descending — 717w follows 717. Comparing on (number, suffix) as the Code
actually orders them, the count is **0**.

**The act-name loss predicted from the grammar does not occur in the
artifact.** `parse_authority_citation` computes `stated_act_name` only inside
its `if not citations:` branch, which predicts that any value yielding a
citation loses the act it also names. Measured against the artifact, the
prediction fails: of **1,144 texts / 9,109 rows** that name an Act *and*
produce a U.S.C. citation, **1,122 texts / 8,944 rows carry `stated_act_name`
anyway** — the builder populates it on a separate pass over the OLRC
popular-name index. The real loss is **22 texts / 165 rows**. A defect read
off the grammar is a hypothesis about the artifact, not a measurement of it.

**Four values I called impossible and was wrong about:**

| value | my claim | the truth |
|---|---|---|
| `1870 U.N.T.S. 167` | volume out of range | UNTS runs past 3,000; the Hague Adoption Convention is genuinely at 1870 UNTS 167 |
| `Pub. L. No. 117-338, 136 Stat. 6156` | page out of range | volume 136 (2022) really does run past 6,000 pages |
| `49 USC 1 to 85` | span absurd | the pre-1978 title 49; valid for its era, and one sibling value even says `(app)` |
| 409 "descending" ranges | ordering violation | my arithmetic, not the parser's |

**The act-name cross-check does not work.** Matching popular act names in the
text against the act's U.S.C. title from the pinned index flags 40 texts / 296
rows, but **precision is roughly 15%**. Acts span titles (Bank Secrecy Act is
title 31, not the index's title 12 anchor; Gramm-Leach-Bliley privacy is
15 U.S.C. 6801) and acts get recodified (FPASA moved 40→41, SORNA moved
42→34). Its three true positives — `42 U.S.C. 1331` for OCSLA, `7 USC 1031`
for the Egg Products Inspection Act, `49 U.S.C. 16901` for SORNA — are *all
also nonexistent sections*, i.e. found more cheaply by existence. **A
title-level act oracle is too coarse to run unattended.**

**Silent loss is mostly by design.** 44 texts / 213 rows state more U.S.C.
labels than the parser emits citations. Nearly all are subsection collapse
(`33 U.S.C. 1321(b)(3) … 1321(j)` → one citation to section 1321) or range
notation (`42 USC 405(d) to 42 USC 405(h)` → one range). The section a
consumer receives is right.

**The suffix cap is not live here.** Section suffixes in this corpus reach
three letters (`15 USC 77sss`, `21 USC 360ccc`, `16 U.S.C. 470aaa`) and all
143 such texts parse correctly. No four-letter suffix (`77aaaa`) occurs, so
that historical truncation defect has no casualty in this artifact.

**No word-fragment sections remain.** Zero parsed `usc_section` values fail to
start with a digit — the `Social Security` → `"urity"` defect is fully retired.

**The corroboration paths do not invent.** 3,625 rows / 791 texts carry a
`corroboration_rule`, i.e. the parser supplied something the string did not
say. These are the highest-risk rows by construction, and they are also the
only ones that **declare themselves** — a consumer can filter on
`corroboration_rule IS NOT NULL`. Spot-checking the rules that invent *numeric*
content vindicates them. RIN 2501-AD71 files ordinal 3 as
`sec 327, Pub. L.109-115,119` and ordinal 4 as `Stat 2936`: one authority the
publisher cut at a comma. `rin-history-volumeless-stat` restores volume **119**,
and Congress 109 maps to volumes {119, 120} on the formula above — correct.
The same record's `sec. 601, Pub. L. 11304, 127 Stat. 101` yields
`public_law = NULL`: shown a malformed Public Law, the grammar **declined
rather than guessed**, and kept the Statutes cite it could read. That is the
behaviour the doctrine asks for.

---

## A different loss: the CFR section the grammar reads and the table discards

**309 distinct texts, 4,186 rows.**

`parse_cfr_citations('delegation of authority at 49 CFR 1.95')` returns
`CfrCitation(cfr_title=49, cfr_part='1', cfr_section='95', …)`. The
`CfrCitation` dataclass has a `cfr_section` field and populates it correctly.
**`unified_agenda_legal_authorities.parquet` has no `cfr_section` column.** The
section is dropped at projection, silently.

The consequence is collapse. **22 (title, part) pairs lose more than one
distinct section**, worst of all 49 CFR part 1, where **22 distinct DOT
delegation sections** — 1.45, 1.46, 1.47, 1.48, 1.49, 1.50, 1.50a, 1.51,
1.52, 1.53 … — all arrive as the single citation "49 CFR part 1":

| (title, part) | distinct sections collapsed |
|---|---:|
| 49 CFR 1 | 22 |
| 5 CFR 2635 | 11 |
| 33 CFR 6 | 7 |
| 7 CFR 2 | 6 |
| 28 CFR 0 | 5 |
| 48 CFR 1 | 4 |

This is not a misread — every citation delivered is *correct*, just coarser
than what was read. It belongs in this report because it is the same harm: a
consumer joining on (title, part) cannot tell `49 CFR 1.95` from `49 CFR 1.50`,
gets an answer that looks complete, and has no flag telling them otherwise.
**Mechanically detectable and exactly fixable**: the information already
exists in the parse and is thrown away by the schema, so the count above is
the exact recovery yield of adding one column.

---

## What a fence is worth

`PL 11-24, 123 Stat 1734` is the campaign in miniature. The value has lost a
digit — the CARD Act is Pub. L. **111**-24, 123 Stat. 1734. The parser reads
`public_law = '11-24'` and sets **`pl_congress_in_series = false`**, because
numbered Public Laws begin at the 57th Congress. The Statutes citation beside
it parses correctly. So a consumer gets one flagged value and one right one,
and nothing silent.

Had Congress 11 been a real congress, this would have been a silent misread
indistinguishable from `PL 104-191, 101 Stat 1936`. **The difference between
the loud population and the silent one is very often just whether a fence
exists** — which is why the two unfenced series (Federal Register volume/page,
and U.S.C. *section*, as opposed to title) account for most of what this
campaign found.

---

## Detector summary

Counted corpus-wide. These sum to roughly **2,000 rows (0.26% of the frame)** —
a **floor**, not the rate. The measured rate is 7.3%; see above for why.

| # | class | texts | rows | mechanically detectable | precision |
|---|---|---:|---:|---|---|
| A4 | **paren-loss family**: subsection retyped as a lettered section (`21 USC 321p`, `21 USC 371a`, `47 USC 154i`, …) | ~10 | **3,300+** | yes — section existence | certain |
| L2 | **eCFR sharp detector**: near-miss in the part's note + section absent from Table III + OLRC not-found | 202 | **4,455** | yes — see L2 above | **44/44 adjudicated** |
| B0 | date's year harvested as a section | 111 | **848** | yes — year-shaped section + adjacent date | 0 FP |
| B5 | abbreviated range kept as a section identity | 187 | **1,007** | yes — `^(\d+)-(\d{2,})$` + digit-length guard | high |
| A5 | zero-padded section carried into the identity field | 101 | **943** | yes — `usc_section ~ '^0[0-9]'` | certain |
| B8 | subsection on a section that has none (42 U.S.C. 1395) | 30 | 205 | yes — needs subsection structure | certain |
| B1 | `NNN(x) et seq.` reads subsection as section | 18 | 146 | yes — regex + section existence | 18/18 |
| B3 | U.S.C. section wearing a "CFR" label | 21–79 | 126–445 | yes — same-RIN `usc` twin + absent from CFR refs | high |
| A1 | Public Law beside the wrong Statutes volume | 11 | 64 (+18) | yes — `vol ∉ [2C−100, 2C−97]`, PL adjacent | ~12/14 |
| B7 | paragraph absorbed into instrument number | 8 | 61 | yes — `admin_order_number ~ '\(\d+\)$'` | high |
| A2 | section magnitude impossible for its title | 9 | 41 | yes — corpus p99 per title | 9/9 |
| B6 | `0` for `o` in a section | 14 | 40 | yes — same-RIN letter twin | high |
| B4 | treaty series read as the Code | 3 | 38 | yes — corpus holds both spellings | 3/3 |
| B7 | stated section eats a word | 5 | 14 | yes — `stated_section` with no digit | high |
| B7 | E.O. compilation year → CFR part | 6 | 12 | yes — `cfr_part` year-shaped + "Comp" | 6/6 |
| B2 | `NN U.S. NNN` read as a case citation | 2 | 6 | yes — no party name, no year | 2/2 |
| A3 | Federal Register volume/page unfenced | 4 | 6 | yes — `fr_volume > year−1935` | 4/4 |

Adjacent, not misreads:

| class | texts | rows | note |
|---|---:|---:|---|
| CFR section dropped by the schema | 309 | 4,186 | the parse holds it; the table has no column |
| act name lost when a citation is found | 22 | 165 | far smaller than the grammar predicts |

Not usable as detectors:

| approach | verdict |
|---|---|
| eCFR **loose** near-miss (no referent oracle) | 12.9% precision by text, 5.6% by rows — retire it |
| cross-edition disagreement (L1) | good work queue; **cannot decide direction** — copy-forward makes typos the majority |
| act name vs U.S.C. title | ~15% precision; acts span titles and get recodified |
| metamorphic label/whitespace rewrites | no live findings; the grammar is robust here |
| `NNN(x)` general surface (1,469 texts / 29,557 rows) | **unresolved** — needs subsection structure, which decides direction |

---

## What I could not settle

Stated plainly, because an honest unknown is a result.

**1. The direction of the `NNN(x)` / `NNNx` pair, for ~29,557 rows.** Both
readings name real law often enough that shape cannot decide. The campaign
found the pair running in *both* directions — B1 (`300(f)` means `300f`) and
A4 (`371a` means `371(a)`) — inside the same corpus. The predicate that would
settle it is *subsection structure*, not section existence: flag `NNN(x)` where
section `NNN` has no lettered subsection `(x)` and section `NNNx` exists. I
demonstrated it on 42 U.S.C. 1395 (class B8, certain) but had no
subsection-level oracle to run it at scale. **This is the highest-value
unexplored seam in the artifact.**

**2. `42 USC 2139(a)` — 387 rows, 115 RINs.** The row-count argument says it is
a typo for `2139a` (filed 1,334 times). The structure says otherwise: 42 U.S.C.
2139 *has* a subsection (a), and 2139a's subsection (a) is *Omitted*. Both
readings are legal. I record it as unknown and note that a purely statistical
detector would have called it wrong.

**3. ~~Whether the U.S.C. section-existence population is large or small.~~
Now sized — and it is large.** A third of every sampled misread was a section
that does not exist. Using the pinned OLRC Table III as a referent oracle,
**16,884 rows / 1,531 distinct texts carry a `parse_status = 'ok'` U.S.C.
citation naming a section Table III has never seen.** That is a *lead*
population, not a finding — Table III does not enumerate positive-law
codifications, and old citations were real when filed. Intersecting it with a
publisher near-miss narrows to a **sharp population of 4,455 rows / 202 texts
at ~100% adjudicated precision**, within the 61% of rows the eCFR sweep
covered. What remains unmeasured is the *residue*: the ~12,000 lead rows that
are neither confirmed nor refuted, and whatever lies in the 39% of rows no
fetched CFR part covers.

**4. Which of two Statutes-at-Large readings is damaged, in 4 texts / 30 rows.**
Where a value carries one Public Law and one Statutes cite and they disagree,
the contradiction is certain but the *direction* often is not. `Pub. L. 98-192,
Dec. 15, 1971, 85 Stat. 646` is settled by its own date (the volume is right,
the PL number wrong); `PL 89-56, 70 Stat 195` and `Pub. L. 98-80, 84 Stat. 2086`
are not, and this session exhausted its web-search budget before resolving them.

**5. Two ledger-adjacent leads I could not close.** A Statutes *page* beyond a
volume's extent (20 texts / 128 rows) cannot be tested against the pinned Table
III, because Table III indexes only pages that produced U.S.C. classifications
— which is why the genuinely real `Reorganization Plan No. 4 of 1970 (84 Stat.
2090)` trips it. `112 Stat. 5044` (28 rows) and `92 Stat 3783` (5 rows) remain
open pending a govinfo volume-extent oracle. Separately, `3 CFR 1981` (6 rows)
publishes a CFR part the grammar's own docstring says it refuses to mint; I did
not check it against a 1980s CFR edition.

**6. The Executive Order transposition surface, bounded but not measured.**
`eo_in_known_series` fences numbers outside the series; a transposition *inside*
it is silent, and one such case reached the sample (`EO 8284` where OMB Circular
A-25's authority is **EO 8248** — both real orders, and EO 8284 is
"Prescribing the Duties of the Librarian Emeritus", which confers no fee
authority). Bounding the surface: **118 distinct orders are cited three times or
fewer (237 rows)**, and **94 of those pairs sit one digit or one transposition
away from an order cited 20+ times** — e.g. EO 13022 (2 rows) beside EO 13222
(1,998 rows), EO 10777 (2 rows) beside EO 10577 (331 rows). But both members of
every pair are *real orders*, so frequency alone cannot adjudicate; the `8284`
case was settled by matching the rule's other three authorities against
Circular A-25's own quartet. **A lead-generator, not a detector.**

**7. Inter-rater spread.** Two reviewers on comparable 70-row batches returned
5.7% and 10%. I did not run a reconciliation pass, so the point estimate
carries adjudication variance on top of sampling variance.

---

## Reproducing this

Everything here is derived from the pinned artifact plus publisher lookups; no
file under `src/`, `tests/` or `output/` was modified.

**A correction worth recording, because I nearly published the error.** An
early instrument check reported that re-parsing all 42,642 distinct strings
with HEAD's `parse_authority_citation` "reproduces the artifact exactly" except
for the `act_relative` retyping. **That is false.** Running the diff myself
against `git show HEAD:` — not the working tree, which carried another
session's uncommitted edits — gives **2,138 texts / 14,611 rows** of
disagreement, and 140 texts / 4,680 rows where the artifact carries a citation
HEAD does not produce. The date-year phantom class is entirely inside that gap.
A claim that two things agree needs the same evidence as a claim that they
differ.

Method notes for anyone re-running this:

- Compare against `git show HEAD:src/refspec/registry/citation_grammar.py`, not
  the working tree, if the tree may be dirty.
- Group by (`authority_text`, `citation_ordinal`), not `authority_text` — a
  single string legitimately yields several citations.
- Compare U.S.C. sections as (number, suffix) tuples. Comparing numeric
  prefixes alone reports `15 USC 717 to 717w` as a descending range; it is not.
- Sample seed `20260822`; frame `parse_status IN ('ok','partial','corroborated')`.
  Sample B ordered by
  `hash(rin||publication_id||ordinal||citation_ordinal||'saltB')`, first 150.
  Sample A ordered by `hash(authority_text||'saltA')`, first 150.

Publisher sources used: uscode.house.gov (OLRC, including the pinned
`olrc-table3-xml-bulk-119-73.zip` in this repo), law.cornell.edu, govinfo.gov,
ecfr.gov (versioner API, date 2026-08-20), loc.gov, and archives.gov.
