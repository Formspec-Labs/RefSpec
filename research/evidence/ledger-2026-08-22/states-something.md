# Authorities that state a name or a section: 1,335 rows, and what the record around them knows

**Ledger row under investigation.** `authority_type = 'other'` with
`stated_act_name` or `stated_section` non-NULL, in
`output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet`
— 1,335 rows. The value names something a human can read; nothing resolved it
to an identity. Billed as the most likely to be recoverable of anything left,
on the grounds that the surrounding record has never been consulted.

**Verdict up front.** "The surrounding record has never been consulted" is
literally true, and narrower than it sounds. `ABSTRACT` and `RULE_TITLE` do
not appear anywhere in `src/` — the edition reader extracts only `CFR_LIST`,
`LEGAL_AUTHORITY_LIST` and `TIMETABLE_LIST`
([`unified_agenda_editions.py:659-661`](../../../src/refspec/registry/unified_agenda_editions.py)),
so the abstract is not merely unused, it is never parsed. But the field that
does the work here is not the abstract. It is the **authority list itself**,
read as a list rather than as a bag of independent strings.

Six of the ten specimens are one citation the publisher broke across two or
three adjacent list slots. In every one of those six the identity is sitting
one ordinal away, in the publisher's own hand. That shape, fenced and
measured, answers **312 of the 1,335** with **zero disagreements** against the
publisher's own joined spellings.

The abstract, measured, answers far less than it looks like it should — and
the reason is structural, not a tuning problem. See §5.3.

| | rows |
|---|---:|
| ledger row | **1,335** |
| distinct `(rin, authority_text)` pairs behind it | 500 |
| distinct RINs | 351 |
| editions spanned | 60 (all) |
| states a section only | 795 |
| states both a name and a section | 294 |
| states a name only | 246 |
| **answered by the split-list shapes below** | **312** |
| residual | 1,023 |

---

## Method

- **Sample.** DuckDB `setseed(0.20260822)` then `ORDER BY random() LIMIT 10`
  over the population. **Seed 0.20260822**, reproducible.
- **Artifact pinned.** `unified_agenda_legal_authorities.parquet` at
  `sha256:a301b11a542f6cc6b39f532f483bc10f8a260f3491578d5f2fcf1f21c58ec946`
  (the digest the receipt declares). Re-verified after sampling; unchanged.
- **Full source records.** For each specimen the whole `<RIN_INFO>` element
  was read out of the pinned publisher XML —  `AGENCY`, `PARENT_AGENCY`,
  `RULE_TITLE`, `ABSTRACT`, `CFR_LIST`, every sibling `LEGAL_AUTHORITY`,
  `TIMETABLE`, `RELATED_RIN_LIST`. Then the same RIN in **every other
  edition**, and where the record pointed at another RIN, that RIN too.
- **Population measurements** were run over all 1,335 rows (and, where the
  fence needed sizing, all 798,122), not over the sample.
- **External corroboration** via WebSearch against SEC, FRA, FMCSA and
  congress.gov sources, cited inline.
- **Read-only.** No parquet written, nothing rebuilt, no source file edited.
  Measurement scripts were written to `/tmp`, not to the checkout.

---

## 1. The ten specimens

| # | RIN | edition | agency | `authority_text` | reading |
|---|---|---|---|---|---|
| 1 | 3235-AL33 | 201610 | SEC | `sec. 939(e)` | **resolved in-record** — split from `PL 111-203` |
| 2 | 0348-AB69 | 201604 | OMB | `sec 872` | **resolved in-record** — split from `PL 110-417` |
| 3 | 0991-AC04 | 201610 | HHS/OS | `FOIA by the Electronic FOIA Act of 1996` | unresolvable — needs a roster the index does not carry |
| 4 | 2127-AL28 | 201410 | NHTSA | `sec 31601` | **resolved in-record, three ways** |
| 5 | 3038-AE30 | 201610 | CFTC | `as amended by title VII of the Wall Street Reform and Consumer Protection Act` | **resolved in-record** — and the same record shows the damage operator |
| 6 | 0720-AB70 | 201704 | DoD/HA | `NDAA-17 sec. 706` | abstract glosses it; the fence is empty (§5.3) |
| 7 | 2130-AC05 | 200910 | FRA | `sec 202 (uncodified)` | in-record, **blocked by a one-token grammar gap** |
| 8 | 3225-AA17 | 202110 | CSOSA | `sec. 166(a) of the Consolidated Appropriations Act, 2000` | unresolvable in-record; roster-shaped |
| 9 | 2060-AF21 | 199510 | EPA/AR | `Clean Air Act Amendments, title 1` | genuinely unresolvable — and it exposes a defect |
| 10 | 2126-AB11 | 201304 | FMCSA | `sec 4009 of TEA-21` | identity is in the corpus, outside the fence, **by design** |

The write-ups below are grouped by outcome rather than by number — the ones
the record answers first, then the ones it does not.

### 1 — SEC 3235-AL33, `sec. 939(e)`

*Commission Guidance Regarding Definitions of Mortgage Related Security and
Small Business Related Security.* 17 CFR 241. Authority list, 201610:

```
[0] Pub. L. 111-203
[1] sec. 939(e)          <- the ledger row
```

The abstract names the substance: definitions "in sections 3(a)(41) and
3(a)(53)(A) in the Exchange Act", credit-rating references to be replaced.
That is context. The **proof** is one ordinal to the left — and better, it is
in the publisher's own earlier hand. The RIN's full history:

```
201210 [0] public_law/partial  PL 111-203 sec 939(e)     <- ONE reference
201304 [0] public_law/partial  PL 111-203 sec 939(e)
201310 [0] public_law/partial  PL 111-203 sec 939(e)
201404 [0] public_law/ok       PL 111-203                <- the publisher splits it
201404 [1] other/failed        sec 939(e)
  ... identically through 202204
```

The 201304 joined row already parses to `public_law = 111-203`,
`stated_section = 939(e)`. From Spring 2014 the publisher put the same
citation in two list slots and the second half became a failed row. **This is
not an inference about what the value means; it is the same publisher's
earlier spelling of the same citation at the same RIN.** SEC's own release
confirms the substance: "section 939(e) of the Dodd-Frank Wall Street Reform
and Consumer Protection Act" ([SEC 34-67448](https://www.sec.gov/files/rules/interp/2012/34-67448.pdf)).

### 2 — OMB 0348-AB69, `sec 872`

*Proposed Amendment to 2 CFR Subtitle A, Chapter 1, Parts 200 and 180.*

```
[0] 31 U.S.C. 503          [5] sec 872           <- the ledger row
[1] Reorg. Plan No. 2 1970 [6] Pub. L. 110-417
[2] E.O. 11541            [7] 122 Stat 4555
[3] 35 FR 10737           [8] Pub. L. 111-204
[4] 3 CFR, 19661970, p 939 [9] 124 Stat 2224
```

Slots 5-7 are the CFR authority-note grammar `Sec. N, Pub. L. X-Y, V Stat. P`
— the exact form 2 CFR part 180 itself carries ("Sec. 2455, Pub. L. 103-355,
108 Stat. 3327") — broken across three list items. Slots 8-9 are a second,
complete `Pub. L. + Stat` pair with no section. Section 872 of Pub. L. 110-417
is the FAPIIS provision, which is what the abstract is about (mandatory
disclosure of credible evidence of fraud by award recipients).

**Note the direction.** Here the section precedes its public law; in specimen
1 it follows. Both orders are real, and §5.1 measures the split.

The RIN's history never joins these; all 11 editions carry the same
three-slot split. Only the list structure answers it.

### 4 — NHTSA 2127-AL28, `sec 31601`

*New FMVSS, Lamps and Reflective Devices for Agricultural Equipment (MAP-21).*
49 CFR 571.

```
[0] PL 112-141
[1] sec 31601             <- the ledger row
[2] 126 Stat 775 and 776
```

Corroborated three ways inside one record: the sibling public law, the
Statutes pages bracketing it, and the abstract in prose — *"the congressional
directive provided through the MAP-21 Act, subtitle F, section 31601,
Rulemaking on Visibility of Agricultural Equipment."* Nine editions, the same
three-slot split every time. This is the cleanest specimen in the sample and
the list structure alone settles it without the abstract.

### 5 — CFTC 3038-AE30, `as amended by title VII of the Wall Street Reform and Consumer Protection Act`

*Amendments to Existing System Safeguards Testing Requirements.* This record
carries the same construction **three times**, which pins the reading without
any oracle outside the record:

| ordinal | text | status |
|---|---|---|
| [4] | `as amended by the Dodd-Frank Wall Street Reform and Consumer Protection Act` | `act_relative/**corroborated**` |
| [5] | `Pub. L. 111-203, 124 Stat. 1376 (for DCMs)` | ok |
| [7] | `as amended by titles VII and VIII of the Dodd Frank Wall Street Reform and Consumer Protection Act` | `other/**failed**` |
| [8] | `Pub. L. 111-203, 124 Stat. 1376 (for SEFs)` | ok |
| [10] | `as amended by title VII of the Wall Street Reform and Consumer Protection Act` | `other/**failed**` — the ledger row |
| [11] | `Pub. L. No. 111-203, 124 Stat. 1376 (2010) (for SDRs)` | ok |

One record, one act, three spellings, and the classifier splits them because
it matches on the name exactly. The two damage operators are visible side by
side: **hyphen loss** (`Dodd-Frank` → `Dodd Frank`) at [7], and **leading-word
loss** (`Dodd-Frank Wall Street…` → `Wall Street…`) at [10]. Both fragments are
immediately followed by the same public law. The record refutes its own
failure.

### 6 — DoD Health Affairs 0720-AB70, `NDAA-17 sec. 706`

*Establishment of TRICARE Select and Other TRICARE Reforms.* 32 CFR 199.

```
[0] 10 U.S.C. ch. 55
[1] NDAA-17 sec. 701   [3] NDAA-17 sec. 715   [5] NDAA-17 sec. 729
[2] NDAA-17 sec. 706   [4] NDAA-17 sec. 718
```

No public law anywhere in the list. The **abstract** glosses the shorthand
exactly: *"the National Defense Authorization Act for Fiscal Year 2017
(NDAA-17)"*. Five editions, identical. This is the specimen that looks like
the abstract should crack it, and §5.3 measures why it does not.

### 7 — FRA 2130-AC05, `sec 202 (uncodified)`

*State Action Plans; Highway-Rail Grade Crossings.* 49 CFR 234. One edition
only.

```
[0] PL 110 thru 432, Div A, 122 Stat 484   -> statute_at_large/partial, public_law = NULL
[1] Rail Safety Improvement Act of 2008    -> act_relative/failed
[2] sec 202 (uncodified)                   <- the ledger row
```

Section 202 of the Rail Safety Improvement Act of 2008 (Pub. L. 110-432, Div.
A) is *"State highway-rail grade crossing action plans"* — which is the
RULE_TITLE, verbatim ([FR 2010-15534](https://www.federalregister.gov/documents/2010/06/28/2010-15534/state-highway-rail-grade-crossing-action-plans),
[Pub. L. 110-432](https://www.congress.gov/110/plaws/publ432/PLAW-110publ432.pdf)).

**And the split-list rule cannot see it**, because slot [0] yields
`public_law = NULL`: the em-dash in `110-432` was rendered as the word
`thru`, and the grammar's separator vocabulary is `(?:to|through)` — `thru` is
absent. There is already a `to-separator-roster-existence` rule for exactly
this shape. This specimen is blocked by a missing synonym, not by a missing
oracle. See §5.4.

### 3 — HHS 0991-AC04, `FOIA by the Electronic FOIA Act of 1996`

*Freedom of Information Regulations.* `CFR_LIST` is the literal word `None`.

```
[0] FOIA by the Electronic FOIA Act of 1996   <- the ledger row
[1] OPEN Government Act
[2] FOIA Improvement Act of 2016
```

Every sibling is itself an unresolved act name. The value is a truncation of
"FOIA, as amended by the Electronic FOIA Act of 1996", so it names **two**
acts and the parser recorded the second. The identity exists — the Electronic
Freedom of Information Act Amendments of 1996 is Pub. L. 104-231 — but no
oracle inside the fence says so, and the OLRC popular name is not the string
the publisher wrote. Nothing in the record closes this.

### 8 — CSOSA 3225-AA17, `sec. 166(a) of the Consolidated Appropriations Act, 2000`

*District of Columbia Sex Offender Registration.* 28 CFR 811.

```
[0] Sex Offender Registration Act of 1999
[1] sec. 166(a) of the Consolidated Appropriations Act, 2000   <- the ledger row
```

Fifteen editions, byte-identical every time. Both slots are `other/failed`.
The value is **well-formed** — a canonical short title with a year and a
section — and the identity is Pub. L. 106-113, 113 Stat. 1530
([CSOSA's own PIA](https://www.csosa.gov/wp-content/uploads/2025/07/SOR-PIA-Final-04_26_2023ss.pdf),
[WIPO Lex on Pub. L. 106-113](https://www.wipo.int/wipolex/en/legislation/details/14913)).
Slot [0] is a **D.C. law** (D.C. Law 13-137), not a federal act at all — and
the schema already has a `dc_code` type. Nothing in the record resolves
either. This is a pure roster problem, and it is the honest shape of the
"name-only" 246.

Note a matching hazard: the text says `Consolidated Appropriations Act, 2000`
and `stated_act_name` records `Consolidated Appropriations Act of 2000`. The
comma-year form is the published short title; the `of`-year rewrite is not.

### 9 — EPA 2060-AF21, `Clean Air Act Amendments, title 1`

*New Source Review (NSR) Reform Rulemaking.* One edition, one authority, and
the timetable says: **`Deleted at Agency Request - Duplicate of RIN 2060-AE11.`**

That pointer is real and it leads somewhere remarkable. RIN 2060-AE11 carries
one authority slot across sixteen editions, and the publisher rewrites it
until it resolves:

```
199510-199704  other/failed              Clean Air Act as amended in 1990, title I
199710-199810  act_relative/failed       Clean Air Act Amendments of 1990[,] title I
199904-200210  act_relative/corroborated CAA as amended, title I
200304         usc/ok                    42 USC 7401 et seq
```

**And it still does not close specimen 9.** Three reasons, all of which the
doctrine already names:

1. The two RINs' texts differ (`title 1` vs `title I`, and AF21 states no
   year), so the match would rest on *slot position in a duplicate record*,
   not on the text.
2. `Clean Air Act Amendments` and `Clean Air Act` are **different acts** —
   Pub. L. 101-549 versus the code title at 42 U.S.C. 7401. AE11's own
   history shows the publisher sliding between them. The publisher being
   loose is not evidence that the citation is loose.
3. `Clean Air Act Amendments` without a year is ambiguous across 1970, 1977
   and 1990.

Specimen 9 is genuinely unresolvable, and §6 records the defect it exposed.

### 10 — FMCSA 2126-AB11, `sec 4009 of TEA-21`

*Carrier Safety Fitness Determination.* 49 CFR 385. Nineteen editions. The
value is stable modulo capitalisation (`sec`/`Sec`/`Section`/`sec.`); from
201510 the list also carries `49 U.S.C. 31144`, which is the section TEA-21
§ 4009 amended — a codification relationship the record never declares.

TEA-21 § 4009 is Pub. L. 105-178, 112 Stat. 107 at 405
([FR 00-21055](https://www.govinfo.gov/content/pkg/FR-2000-08-22/html/00-21055.htm)).
The corpus even contains the binding — `PL 105-178, TEA-21`, seven rows — but
at **RIN 2105-AC89, agency 2105 (FHWA)**, not at agency 2126. The oracle ladder
is `(rin, rin[:4])` by design, and wave 5 measured the corpus-wide roster
inventing a wrong survivor 15.25% of the time. **This specimen is refused
correctly, for a reason that was measured.** §5.4 records the narrower thing
that *is* in reach at FMCSA.

---

## 2. Does the surrounding record resolve what the text alone could not?

Yes — for one shape, decisively; and the answer came from the field the
builder already reads, not from the ones it does not.

| source of evidence | specimens it answered | specimens it did not |
|---|---|---|
| **sibling slot in the same authority list** | 1, 2, 4, 5, (7 — blocked) | 3, 6, 8, 9, 10 |
| **same RIN, another edition** | 1 | 2, 3, 4, 5, 6, 7, 8, 9, 10 |
| **the abstract, in prose** | 4 (redundantly), 6 (name only) | 1, 2, 3, 5, 7, 8, 9, 10 |
| **the rule's CFR parts** | none | all |
| **a pointer to another RIN** | 9 (and still refuses) | — |

Three findings worth stating plainly:

- **The authority list is a list, and the builder treats it as a bag.** Six
  of ten specimens are one citation the publisher broke across adjacent
  slots. The `ordinal` column preserves the order; nothing reads it.
- **"Another edition spells it better" is real but rare.** It fired for one
  specimen in ten. Publishers mostly repeat their own damage verbatim —
  specimen 8 is byte-identical across fifteen editions, specimen 10 across
  nineteen. Measured over the whole population, the same-RIN joined form
  reaches 89 rows (§5.2); the sibling list reaches 295 (§5.1).
- **The abstract confirms and does not identify.** In specimen 4 it says
  "MAP-21 … section 31601" — but the sibling slot already said `PL 112-141`.
  In specimen 6 it expands `NDAA-17` to a name, and a name is not an identity.
  Which is the doctrine, holding.

---

## 3. The shape behind the number

The 1,335 rows are 500 distinct `(rin, authority_text)` problems across 351
RINs. The dominant one, at **1,089 rows**, is *a bare section, or a section
list, with no law attached*. That is not prose and it is not a placeholder.
It is the tail of a citation whose head is elsewhere in the same record.

The corroboration module already has a `rin-history-*` family that resolves
bare sections — but only into two identity spaces: **U.S.C. `(title, section)`**
and **act `(act_key, act_section)`** (`_CitationHistory` holds `usc`, `act`,
`stat`, `public_law`; `section_survivors` consults only the first two). The
**Public Law `(public_law, section)`** space is absent from the pool, and
`_history_read_public_law_pairs` recovers whole public laws, never a public
law *with* a section.

That absence is the whole story of this ledger row. `sec 939(e)` cannot
survive `section_survivors` because `_history_bare` gives `939`,
`_history_distinctive("939")` is False (three digits, no letter, no dash — the
right call), and agency 3235's act pool holds no section `939`. The joined
edition that *does* bind it stores `public_law = 111-203` beside
`stated_section = 939(e)` — in a space the pool does not read.

---

## 4. Two defects found in passing

**4.1 `stated_act_name` silently drops "Amendments".** Specimen 9's text is
`Clean Air Act Amendments, title 1`; `stated_act_name` is `Clean Air Act`.
Those name different enactments. Measured corpus-wide: **99 rows across 30
distinct texts** where `authority_text` contains "Amendments" and
`stated_act_name` does not.

| `authority_text` | `stated_act_name` | rows |
|---|---|---:|
| `PL 106-245, Radiation Exposure Compensation Act Amendments of 2000` | `Radiation Exposure Compensation Act` | 22 |
| `PL 102-569, The Rehabilitation Act Amendments of 1992` | `Rehabilitation Act` | 14 |
| `31 USC 7501 Single Audit Act Amendments of 1996` | `Single Audit Act` | 5 |
| `PL 101-54, section 608 of the Clean Air Act Amendments of 1990` | `Clean Air Act` | 4 |
| `Lacey Act Amendments, 16 U.S.C. 3371 et seq.` | `Lacey Act` | 4 |

The statement column is supposed to hold what the row has *instead of* an
identity. Holding a **different act's** name there is worse than holding
nothing: it is the one thing that could license a roster to resolve the row
wrongly. Most of these rows are typed `public_law` or `usc` and already carry
a real identity, so nothing is broken today — but the column is a trap set for
the next rule that reads it. `_GLOSS_STOPWORDS` deliberately discards
"amendments" for gloss narrowing, with a stated reason; that reasoning has
leaked into a column where it does not belong.

**4.2 The receipt promises a column the schema does not have.** The receipt's
`contract.rowSemantics` says exploded rows are "distinguished by
`citation_ordinal`". There is no `citation_ordinal` column. The table holds
798,122 rows over 755,727 distinct `(rin, publication_id, ordinal)` keys, so
42,395 rows are genuinely indistinguishable on their key — e.g. CFTC
3038-AE30 ordinal 0 is seven identical rows. The contract is describing a
column that is not there.

---

## 5. Leads, each as a hypothesis and what would have to be measured

### 5.1 The split-list run — the one worth adopting

> **Hypothesis.** Within one `LEGAL_AUTHORITY_LIST`, a maximal run of
> consecutive slots that are nothing but a bare section list belongs to the
> single public law bounding that run. Where both bounds carry a public law
> and they differ, the run is ambiguous and refuses.

Not a new oracle — the publisher's own list order, which the parquet already
stores in `ordinal`. The convention to declare is the CFR/FR authority-note
grammar `Sec. N, Pub. L. X-Y, V Stat. P`, which the publisher breaks across
list items in both directions.

**Measured over all 1,335.** Donor must satisfy `pl_congress_in_series`:

| | rows |
|---|---:|
| bare-section rows in the population | 1,089 |
| bounded by exactly one public law → answered | **295** |
| bounded by two different public laws → refused | 25 |
| of the answered: single adjacent slot / longer run | 285 / 10 |

**Scored against the publisher's own joined spellings** — every corpus
reference that puts a public law and a section in *one* string (16,705 of them
across 2,623 RINs) is an answer key the rule never sees:

| answer key | scored | agree | rate |
|---|---:|---:|---|
| same RIN | 67 | **67** | **100.00%** |
| same agency | 142 | 138 | 97.18% |

**All four agency-level disagreements are one donor typo**, not a logic error:
RIN 0938-AR04 slot [0] reads `PL 111-48` where the Affordable Care Act
sections 1413/2001/2002/2201 require `111-148`. The rule faithfully
propagated a damaged neighbour. Dropping the `pl_congress_in_series` fence
adds 10 rows and two more disagreement families (`PL 11-148`, congress 11 —
anachronistic and already flagged `false`), taking the agency-level rate from
97.18% to 90.79%. **The fence is load-bearing and is already in the schema.**

**Direction is genuinely mixed** — of 357 adjacent public-law neighbours, 200
sit before the section slot and 157 after — so the rule must be stated as
*nearest and unique*, never as *preceding*. **65 of those 357 donors already
carry a section of their own**; whether that should disqualify a donor is the
open question this measurement does not settle, and it is the first thing to
measure before adopting.

**Residual risk to measure before adopting:** the rule inherits the donor's
damage. Every disagreement found was of that kind. A pre-adoption check should
score answers against `roster-existent-public-law-pair`'s congress.gov roster
and refuse a donor whose public law is not in it.

**Population answered:** 295 rows of this ledger row, and the shape is not
specific to it — the same list structure appears in the 6,214 `act_relative`
failures.

### 5.2 The same RIN's joined spelling of the same section

> **Hypothesis.** A bare section at a RIN resolves to the public law that the
> *same RIN*, in any edition, joins to *that same section string* in one
> reference. Two distinct public laws refuses.

This is the existing `rin-history-*` family extended to a third identity
space: `(public_law, section)` alongside `usc` and `act` in `_CitationHistory`.

**Measured:** 89 rows answered with a unique survivor, 5 refused as ambiguous,
across 36 RINs. Union with §5.1: **312 rows**; overlap 67 — which is exactly
the 67-row answer key that scored §5.1 at 100%.

The 89 are strikingly clean, and they double as a damage-operator census:

| population value | the same RIN's joined form | operator |
|---|---|---|
| `sec. 939(e)` | `PL 111-203 sec 939(e)` | list split |
| `PL 105?178, sec 1101(b),112 stat 107, 113` | `PL 105–178, sec 1101(b), 112 Stat 107, 113` | en-dash mojibake |
| `Pud. L. 111-216, sec. 206` | `P.L. 111-216, sec 206` | `Pub.` → `Pud.` |
| `OL 111-148, sec 3301, sec 6402` | `PL 111-148, sec 3301, sec 6402` | `P` → `O` |
| `Pub. Ll 110-314, sec 104` | `Pub. L. 110-314, sec 104` | `.` → `l` |
| `PL 112 to 141, sec 20021` | `PL 112-141, sec 20021` | dash → `to` |
| `PL 11 to 432, Div, sec 202, 205` | `PL 110-432, Div, sec 202, 205` | dash → `to`, **and** a lost `0` |

**Population answered:** 89, of which 67 are already inside §5.1.

### 5.3 The abstract — measured, and why it under-delivers

> **Hypothesis.** The same record's `ABSTRACT` glosses the shorthand its
> authority column uses ("… (NDAA-17)"), the way `_harvest_act_glosses`
> already harvests glosses from `authority_text`.

**Measured over all 1,335**, with the repo's own `_ACT_GLOSS` shape and with
one widening (allow a year-suffixed initialism, which `[A-Z]{2,8}` forbids):

| gloss shape | rows glossed uniquely | rows glossed two ways (refuse) |
|---|---:|---:|
| the repo's `_ACT_GLOSS`, applied to the abstract | 30 | 0 |
| widened to admit `NDAA-17` / `MAP-21` | 56 | 0 |

Zero ambiguity is encouraging. **The yield is not the problem. The fence is.**
`_gloss_narrowed` cannot *name* an act — by design, and the docstring says so
— it can only pick among acts the agency's roster already holds. So the
question is how big that roster is for this population:

| | |
|---|---:|
| agencies in the corpus | 291 |
| agencies holding **any** grammar-read act key | **90** |
| population RINs at an agency with an **empty** act roster | 64 of 351 |
| agency 0720 (specimen 6) act roster | **empty** |
| agency 0348 (specimen 2) act roster | **empty** |

The gloss for `NDAA-17` is exact — *"National Defense Authorization Act for
Fiscal Year 2017 (NDAA-17)"* — and there is nothing at agency 0720 for it to
narrow. **The fence and the residual are anti-correlated by construction:**
this population is precisely the rules whose authority lists never contained a
resolvable act citation, which is the same thing as saying their agency roster
is thin.

**What would have to be measured to adopt anything here.** Reading the
abstract is a *new field*, so the first measurement is not yield but
contamination: hold out the 1,964 `(text, RIN)` act citations the grammar
resolved, harvest glosses from abstracts only, and count how often an
abstract-derived gloss narrows to the *wrong* survivor. Wave 4 ran exactly
this design for the word-prefix operator. Until that number exists, the honest
statement is: **the abstract is a real source of testimony that the current
fence cannot spend.** Extracting `ABSTRACT` would also cost a re-pin of the
edition reader, which today reads three elements.

**Population it would answer:** at most 56 rows, and on today's fence, near
zero.

### 5.4 Two narrow, cheap, honestly small ones

**(a) `thru` as a dash.** `_HISTORY_SEPARATOR` and the abbreviation shapes
accept `to|through`; the corpus also writes `thru`. `PL 110 thru 432` yields
`public_law = NULL` and falls to `statute_at_large` — which is what blocks
specimen 7. `to-separator-roster-existence` already handles the identical
`PL 112 to 141` under a roster-existence fence, so the same fence covers the
synonym. Note `thru` means two different things by context: between U.S.C.
sections (`47 U.S.C. 151 thru 152`) it is a range; inside a public law number
it is the dash. The roster-existence fence is what tells them apart, and it is
already there.

**Population:** 9 rows, 4 RINs (all FRA, RINs 2130-AC05/06/07/08, all citing
the Rail Safety Improvement Act of 2008). Small, and it unblocks specimen 7
into §5.1.

**(b) The hyphenated short form as a roster key, matched exactly.** Every
abbreviation shape captures `(?P<ab>[A-Z]{2,8})` — letters only — so
`MAP-21`, `TEA-21`, `NDAA-17`, `SAFETEA-LU` cannot even be read as
abbreviations. **Population of that shape in this ledger row: 46 rows, 11
texts, 4 RINs.**

Of those 46, an *exact roster-key match* (no initials derivation) answers **2**:
`map-21` is literally an act key at agencies 2126 and 2132. The other 44
refuse, correctly:

- `TEA-21` (19 rows): FMCSA's roster holds
  `transportation equity act for the 21st century`, but
  `_act_initialism` of that key is not `TEA-21` and never will be — the `21`
  comes from "21st Century", not from initials. Exact match finds no
  `tea-21` key. Refuses.
- `NDAA-17` (25 rows): agency 0720's roster is empty. Refuses.

**Population answered: 2.** Stated here because the *shape* is 46 rows and it
would be easy to over-claim it; the honest yield under a fence that does not
guess is two.

### 5.5 The cross-RIN pointer — a real oracle level, and a small one

> **Hypothesis.** `RELATED_RIN_LIST` with relation `Previously reported as`
> or `Duplicate of` names the *same rule* under another number, and so is an
> oracle level between `rin` and `rin[:4]` in `_oracle_levels`.

Measured over the 351 population records:

| relation | occurrences | population rows behind them |
|---|---:|---:|
| `Related to` | 56 | 60 |
| `Merged with` | 22 | 28 |
| `Previously reported as` | 13 | 13 |
| `Duplicate of` | 1 | 2 |
| `TTBL_ACTION` prose naming another RIN | 3 | 3 |

Only the bottom three assert rule *identity*; `Related to` explicitly does
not, and `Merged with` means the authorities are a union rather than the same.
So the defensible level is worth **~18 rows** of this population. Specimen 9
sits in it and still refuses (§1). Worth writing down, not worth building for
this row alone — but `_oracle_levels` is the single place it would go, and it
would apply to every rule in the module at once.

---

## 6. What is genuinely unresolvable, and why

**1,023 rows** survive §5.1 and §5.2. Four of the ten specimens are in it, and
they are unresolvable for four different reasons:

| specimen | why it refuses | is the refusal right? |
|---|---|---|
| **3** HHS `FOIA by the Electronic FOIA Act of 1996` | the value names two acts; the second's OLRC popular name is not the string written; every sibling is itself unresolved | **Yes.** Choosing between the two acts the value names is a guess. |
| **8** CSOSA `sec. 166(a) of the Consolidated Appropriations Act, 2000` | well-formed, correct, and no oracle inside the fence carries it; the sibling is a **D.C.** law | **Yes, but this is the roster's gap, not the record's.** The name is canonical and the identity is public. |
| **9** EPA `Clean Air Act Amendments, title 1` | "Amendments" without a year is ambiguous across 1970/1977/1990; the duplicate RIN's text differs; the CAA and the CAAA are different enactments | **Yes**, and the strongest refusal in the sample. |
| **10** FMCSA `sec 4009 of TEA-21` | the identity is in the corpus at agency 2105; the ledger row is at agency 2126; the fence stops at the agency | **Yes** — and measured (wave 5: 15.25% invention rate corpus-wide). |

Specimens 3, 8 and 9 are the honest shape of the 246 **name-only** rows: they
state a name well enough for a person, and a stated name is not an identity.
Specimen 10 is the shape that stings — the answer exists in the pinned corpus,
one agency away, and the fence that refuses it is the fence that carries the
accuracy. Moving it to buy 19 rows would be trading a measured 15.25%
invention rate for a rounding error.

The residual splits roughly as: bare sections with no public law anywhere in
the record (the bulk), act names the OLRC index does not alias, and prose
fragments. Nothing in the surrounding record reaches them.

---

## 7. What this does not license

- **A stated name is still not an identity.** Nothing above recovers an act
  from an abstract mentioning it. §5.3 measures a gloss oracle and then
  reports that the fence cannot spend it; that is the finding, not a
  workaround.
- **Adjacency is not proximity-in-general.** The measured rule is *a maximal
  run of bare-section slots bounded by exactly one public law*. Widening it to
  "nearest public law anywhere in the list" was not measured and must not be
  assumed to inherit the 100% score.
- **The 100% is 67 rows.** It is the publisher's own joined spellings, which is
  the best answer key available, and it is small. The agency-level score
  (97.18%, n=142) is the more conservative number and its four misses are all
  donor damage.
- **Nothing here was written to the artifact.** No parquet, no rebuild, no
  source edit. The two rules in §5.1 and §5.2 are proposals with measurements
  attached, and both need the donor-roster check in §5.1 measured before
  adoption.
- **The receipt/schema mismatch in §4.2 was found, not fixed**, and belongs to
  whoever owns the exploded-row contract.

---

## Reproducing

```sql
-- the population
SELECT * FROM 'output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet'
WHERE authority_type = 'other' AND (stated_act_name IS NOT NULL OR stated_section IS NOT NULL);

-- the ten specimens
SELECT setseed(0.20260822);
SELECT rin, publication_id, ordinal, authority_text FROM ( /* population above */ )
ORDER BY random() LIMIT 10;
```

Artifact digest at time of sampling:
`sha256:a301b11a542f6cc6b39f532f483bc10f8a260f3491578d5f2fcf1f21c58ec946`.
