# The 298 out-of-series values: every bound is right, and 61 of the rows are not citations

**2026-08-22.** Ledger row: *values flagged as outside a dated series, and
impossible CFR values — 298 rows.* Six flags across two tables:

| table | flag | rows |
|---|---|---:|
| `unified_agenda_legal_authorities.parquet` | `usc_title_is_possible = false` | 130 |
| | `pl_congress_in_series = false` | 91 |
| | `stat_volume_in_series = false` | 19 |
| | `eo_in_known_series = false` | 7 |
| `unified_agenda_cfr_references.parquet` | `cfr_title_is_possible = false` | 44 |
| | `cfr_part_is_plausible = false` | 7 |
| | **total** | **298** |

## Verdict up front

**This is not a second Panama Canal.** Every one of the 298 values really is
outside its series, in every year — checked value by value against the whole
distinct census, not just the sample. The CFR-35 mistake was a bound that
excluded a real title; here no flagged value is a real member of its series
under any calendar. Nothing should be un-flagged.

**But "out of series" is not what 61 of these rows are.** The flag is a
damage detector, and it is firing on four different phenomena that it reports
with one word:

| family | rows | what the value actually is |
|---|---:|---|
| **A. Damaged citation** | 228 | a real citation with a digit inserted, dropped, substituted or transposed. Referent recoverable. |
| **B. Composite placeholder** | 36 | `00 CFR NYD`, `00 CFR None`, `00 CFR 00`, `00 USC 00`. The publisher saying *nothing*, with a numeral glued to the front of a sentinel the codebase already knows. |
| **C. A different series entirely** | 22 | **Supreme Court reporter citations** (12), a **Statutes at Large page range** (6), an **act section range** (2), a **U.S.C. section range** (2) — each correctly formed, each wearing another series' label. |
| **D. RefSpec's own grammar** | 3 | a Statutes volume harvested out of a Public Law number's tail. Not publisher damage. |
| **E. Fused list / lost separator** | 9 | `42 CFR 412106`, `47 CFR 634761471`, `sec 41349 USC 20166`, `CFR 460 CFR 482 CFR 483`. |

**One bound is stale, with no live casualty yet:** `STAT_VOLUME_HIGHEST_KNOWN
= 139`. Volume **140** is the current Statutes at Large volume — the National
Archives lists Pub. L. 119-101 at *140 Stat. 846* (July 11, 2026) and Pub. L.
119-102 at *140 Stat. 985* (July 12, 2026). No row in the pinned capture cites
volume 140 (the capture ends at edition 202510), so nothing is mislabelled
today. The next edition will carry them.

**The flags do not carry a calendar.** All six are evaluated against
present-day constants regardless of the row's `publication_id`. The only
date-aware rule in the builder is `_act_key_within_calendar`. In this capture
that costs nothing in the *destructive* direction — but it costs one row in
the permissive direction, documented below.

## Method

- Population read from the two parquet files; **complete distinct census**
  taken first — all 298 rows resolve to **54 distinct flagged values** carried
  by **85 distinct source strings** — so the sample below sits inside a known
  whole and every value is accounted for, not just the ten.
- 10 specimens drawn **stratified across the six flags, seed `20260822`**
  (`random.Random(20260822)`, one per flag preferring an unseen value, then
  four more from the pooled remainder). Script logic reproduced in the
  appendix.
- For each specimen the **whole `<RIN_INFO>` element** was read from the
  pinned publisher XML at
  `output/registry-real-data-sources/unified-agenda-editions/REGINFO_RIN_DATA_<publication_id>.xml`
  — `AGENCY`, `PARENT_AGENCY`, `RULE_TITLE`, `ABSTRACT`, `CFR_LIST`, every
  sibling `LEGAL_AUTHORITY`, `TIMETABLE`, `FR_CITATION`.
- Every flagged string was grepped against the raw XML to confirm it is
  **verbatim publisher text** and not a RefSpec artifact. It is, in all cases
  except family D.
- A **cross-edition oracle** was run over all 298: for each flagged RIN, every
  other edition of the *same RIN* was searched for a near-identical
  (`difflib` ratio ≥ 0.80) authority or CFR string that is **not** flagged.
  The publisher corrects itself more often than expected, and those
  corrections are the strongest evidence in this report.
- Web sources: eCFR versioner API (`ecfr.gov/api/versioner/v1/full/...`),
  govinfo FR granules, federalregister.gov API, archives.gov Public Laws
  listing, congress.gov, uscode.house.gov, supreme.justia.com.

## The 10 specimens

| # | flag | value | RIN | ed | source text | verdict |
|---:|---|---|---|---|---|---|
| 1 | `usc_title_is_possible` | 115 | 3235-AK18 | 200910 | `115 USC 78o(d)` | **really impossible** — 15 U.S.C. 78o(d) |
| 2 | `eo_in_known_series` | 21600 | 2105-AC69 | 199810 | `EO 21600` | **really impossible** — E.O. 12600 |
| 3 | `pl_congress_in_series` | 155-123 | 0560-AI37 | 201804 | `Pub. L. 155-123` | **really impossible** — Pub. L. 115-123 |
| 4 | `stat_volume_in_series` | 199 | 2137-AE11 | 200704 | `199 Stat 594` | **really impossible** — volume 119 |
| 5 | `cfr_title_is_possible` | 0 | 2040-AD99 | 200604 | `00 CFR None` | **neither — a placeholder** |
| 6 | `cfr_part_is_plausible` | 412106 | 0938-AK77 | 200204 | `42 CFR 412106` | **really implausible** — 42 CFR 412.106 |
| 7 | `usc_title_is_possible` | 59 | 0694-AG08 | 202004 | `59 U.S.C. 4801-4582` | **really impossible** — 50 U.S.C. 4801-4852 |
| 8 | `pl_congress_in_series` | 11-203 | 3235-AL11 | 201110 | `PL 11-203, sec, 939A` | **really impossible** — Pub. L. 111-203 |
| 9 | `usc_title_is_possible` | 410 | 0750-AG92 | 201104 | `410 USC 421` | **really impossible** — 41 U.S.C. 421 |
| 10 | `usc_title_is_possible` | 72 | 2501-AD36 | 201004 | `72 USC 3535(d)` | **really impossible** — 42 U.S.C. 3535(d) |

### 1 — `115 USC 78o(d)` · SEC 3235-AK18 "Security Ratings" · ed 200910

The record's own authority list is nine entries and eight of them are title 15:

> `15 USC 77f | 15 USC 77g | 15 USC 77j | 15 USC 77s(a) | 15 USC 78l | 15 USC 78m | 15 USC 78n | 115 USC 78o(d) | 15 USC 78w(a)`

§ 78o(d) is Exchange Act § 15(d), which lives in title 15 and nowhere else.
Title 115 has never existed: the U.S. Code has titles 1–54.
**Really impossible.** Referent: 15 U.S.C. 78o(d).
Source: [OLRC, U.S. Code](https://uscode.house.gov/about/info.shtml) (54 titles, 53 reserved).

### 2 — `EO 21600` · DOT OST 2105-AC69 "Public Availability of Information: Electronic FOIA Amendment" · ed 199810

CFR_LIST is `49 CFR 7`; `FR_CITATION` is `63 FR 38331`. The Agenda authority
list is `5 USC 552 | 31 USC 9701 | 49 USC 322 | EO 21600`. The **1999 CFR
annual edition** of 49 CFR part 7 — the first edition to carry this
rulemaking — reads, verbatim:

> `AUTHORITY: 5 U.S.C. 552; 31 U.S.C. 9701; 49 U.S.C. 322; E.O. 12600, 3 CFR, 1987 Comp., p. 235.`
> `SOURCE: Amdt. 1, 63 FR 38331, July 16, 1998`

That `SOURCE` line is the RIN's own `FR_CITATION`. So this is not the modern
authority line but *the authority line this very rulemaking established*, and
it is four citations long where the Agenda entry is four citations long, in
the same order. The fourth is **E.O. 12600** ("Predisclosure Notification
Procedures for Confidential Commercial Information," June 23, 1987, 52 FR
23781) with its first two digits transposed. The numbered EO series reaches
14420 today and stood near 13100 in 1998; 21600 has never existed.
**Really impossible.** Referent: E.O. 12600.
Sources: [CFR-1999-title49-vol1 part 7](https://www.govinfo.gov/content/pkg/CFR-1999-title49-vol1/pdf/CFR-1999-title49-vol1-part7.pdf) ·
[E.O. 12600](https://www.archives.gov/federal-register/codification/executive-order/12600.html).
(The 1996 edition of part 7 cited no Executive Orders at all, which is why the
current eCFR line alone would have been the weaker source.)

### 3 — `Pub. L. 155-123` · USDA FSA 0560-AI37 "Margin Protection Program for Dairy; Changes" · ed 201804

The abstract names the statute in words: *"the program improvement provisions
of the **Bipartisan Budget Act of 2018**."* That is **Pub. L. 115-123**
(Feb. 9, 2018, 132 Stat. 64). The sibling authority is `Pub. L. 113-79`, the
2014 Farm Bill that created MPP-Dairy. There is no 155th Congress; the 119th
is sitting.
**Really impossible.** Referent: Pub. L. 115-123.
Source: [PLAW-115publ123](https://www.govinfo.gov/content/pkg/PLAW-115publ123/pdf/PLAW-115publ123.pdf)
The same damaged string appears at four FSA RINs (0560-AH69, -AI37, -AI39,
-AI40) in the same two editions — one boilerplate error copied across a
programme office, not four independent typos.

### 4 — `199 Stat 594` · PHMSA 2137-AE11 "Registration and Fee Assessment Program" · ed 200704

Authority list: `49 USC 5101 et seq, as amended by title VII of PL 109-59 |
199 Stat 594` (each twice). Volume 199 does not exist — the series stands at
140 (2026) and stood at 121 in 2007. The only in-series reading of the digits
is **119** (2005), the volume that carries Pub. L. 109-58 and 109-59.
**Really impossible as a volume.** Referent: volume 119.

*The page is a separate, open question, and I leave it open.* **119 Stat. 594
is the first page of Pub. L. 109-58** (Energy Policy Act of 2005, Aug. 8,
2005) — not of the Pub. L. 109-59 the same string names, which begins at
**119 Stat. 1144**. So correcting the volume to 119 yields a citation that
points at a different act from the one the row's own text names. I make no
claim about which the filer meant; the volume verdict does not depend on it.
Sources: [PLAW-109publ58](https://www.govinfo.gov/content/pkg/PLAW-109publ58/pdf/PLAW-109publ58.pdf) ·
[PLAW-109publ59](https://www.govinfo.gov/content/pkg/PLAW-109publ59/pdf/PLAW-109publ59.pdf)

### 5 — `00 CFR None` · EPA Water 2040-AD99 "Drinking Water Contaminant Candidate List 3" · ed 200604

`CFR_LIST` is the single entry `00 CFR None`. This is **not a citation and
not damage**. `UNSTATED_SENTINELS` in `citation_grammar.py` already contains
`"none"`, `"nyd"`, `"not yet determined"` — and `states_nothing("None")` is
`True`, so 4,453 bare `None` rows in this same table correctly carry a NULL
title. The check fails only because the publisher's form glued `00 CFR ` in
front of the sentinel:

```
states_nothing("None")        -> True    -> cfr_title NULL     (4,453 rows)
states_nothing("00 CFR None") -> False   -> cfr_title 0, flagged  (15 rows)
```

**Verdict: neither impossible nor real — unstated.** See "The 36 placeholders"
below.

### 6 — `42 CFR 412106` · CMS 0938-AK77 · ed 200204

`RULE_TITLE`: *"Medicare Inpatient **Disproportionate Share Hospital (DSH)
Adjustment Formula** (CMS-1171-IFC)"*. 42 CFR **412.106** is
"Special treatment: Hospitals that serve a disproportionate share of
low-income patients" — the record names its own section in its title. The
decimal point was lost. Six digits is not a CFR part (the widest real parts
are five, e.g. 5 CFR 10001).
**Really implausible as a part.** Referent: 42 CFR 412.106.

### 7 — `59 U.S.C. 4801-4582` · BIS 0694-AG08 "Revisions to Commerce Control List" · ed 202004

Authority list: `59 U.S.C. 4801-4582 | 50 U.S.C. 4601 et seq. | E.O. 13222`.
The Export Control Reform Act of 2018 is codified at **50 U.S.C. 4801–4852**;
the sibling `50 U.S.C. 4601 et seq.` is the lapsed EAA it replaced, and
E.O. 13222 is the order that continued the EAR. Two digits are wrong: `59`
for `50`, `4582` for `4852`.
**Really impossible.** Referent: 50 U.S.C. 4801–4852.
Source: [50 U.S.C. ch. 58](https://uscode.house.gov/view.xhtml?path=%2Fprelim%40title50%2Fchapter58&edition=prelim).

### 8 — `PL 11-203, sec, 939A` · SEC 3235-AL11 · ed 201110

The abstract names *"the Dodd-Frank Act"*; § 939A is Dodd-Frank's
credit-rating-reference removal. Dodd-Frank is **Pub. L. 111-203**. A leading
`1` was dropped. The 11th Congress (1809–11) existed but issued no numbered
public laws: separate Public Law numbers begin in 1901 with the 57th
Congress; before that, acts carry Statutes at Large *chapter* numbers.
**Really impossible as a Public Law designation.** Referent: Pub. L. 111-203.
Corroborated internally: RIN **1505-AC36** writes the same damaged `PL 11-203`
in ed 201110 and the clean `PL 111-203` in ed 201210.

### 9 — `410 USC 421` · DoD DARS Council 0750-AG92 "Identification of Critical Safety Items" · ed 201104

CFR_LIST is `48 CFR 209 | 48 CFR 252` — DFARS. The DFARS authority citation of
that era is 41 U.S.C. 421 (OFPP Act § 25); after the January 2011
recodification it becomes 41 U.S.C. 1303, and the same corruption appears as
`410 USC 1303` in ed 201110. **The `410 USC` string appears at 10 different
DARS RINs across editions 201104 and 201110** — 18 rows — and at no other
agency and in no other edition. That is one office's submission tooling
failing for two cycles, not scattered typing.
**Really impossible.** Referent: 41 U.S.C. 421 / 41 U.S.C. 1303.
(Unrelated second defect in the same record, outside this ledger row: the
authority says `PL 109-136` while the abstract says *"Pub. L. 108-136"* — and
109-136 is in series, so nothing flags it.)

### 10 — `72 USC 3535(d)` · HUD OSEC 2501-AD36 "HUD Debt Collection" · ed 201004

Authority list: `5 USC 5514 | 31 USC 3701 et seq | 72 USC 3535(d)`.
**42 U.S.C. 3535(d)** is HUD's general rulemaking authority and appears in
essentially every HUD rule. **Really impossible.** Referent: 42 U.S.C. 3535(d).
Corroborated internally: RIN **2577-AB96** writes `423 USC 3535(d)` in
ed 199910 and `42 USC 3535(d)` in ed 199904 — the same authority, the same
office, one edition apart.

**Sample score: 9 really impossible, 1 not a citation at all. Zero mislabelled
real values.**

## Bound audit — every constant, checked

`src/refspec/registry/citation_grammar.py`, lines 112–145.

| constant | value | verdict | evidence |
|---|---:|---|---|
| `CFR_TITLE_COUNT` | 50 | **correct** | The CFR has been 50 titles since 1938; all 50 revised annually since 1967. Title 35 correctly *inside* the bound — 115 rows in this capture cite it, and the existing comment's Panama Canal reasoning holds. |
| `USC_TITLE_COUNT` / `USC_RESERVED_TITLES` | 54 / {53} | **correct** | Titles 1–52 and 54 in use, 53 reserved and never enacted. No flagged row cites 53; the reserved set is inert here but right. |
| `EO_HIGHEST_KNOWN` | 14,420 | **correct today, at the edge** | E.O. 14420 (Aug. 10, 2026) is the highest published order; the FR API returns nothing above it. Exact as of this report. |
| `PL_FIRST_NUMBERED_CONGRESS` | 57 | **correct** | Separate Public Law numbers begin in 1901 = 57th Congress; the 56th and earlier use Statutes at Large chapter numbers. |
| `CONGRESS_CURRENT` | 119 | **correct** | The 119th is sitting; highest public law is 119-102 (July 12, 2026). |
| `STAT_VOLUME_HIGHEST_KNOWN` | 139 | **STALE — should be 140** | Archives.gov's current-session listing gives Pub. L. 119-101 = *140 Stat. 846* (July 11, 2026) and Pub. L. 119-102 = *140 Stat. 985* (July 12, 2026). The comment "volume 139 = 2025 session laws" is true and no longer the top of the series. |

### The one wrong bound, and what it does not cost

`STAT_VOLUME_HIGHEST_KNOWN = 139` is one behind the world. **No row in this
capture is affected** — the three flagged volumes are 162, 188 and 199, all
above 140 as well — and the pinned editions stop at 202510, before any 2026
session law could be cited. So this is a stale constant, not a mislabelling.

It is worth fixing anyway, and worth fixing *the way the module's own comment
predicts*: "the next Congress will outrun them." Two constants
(`STAT_VOLUME_HIGHEST_KNOWN`, `EO_HIGHEST_KNOWN`) and one
(`CONGRESS_CURRENT`) are each one event away from producing a false
"impossible" on the next capture — the 140th volume already has, the 120th
Congress will in January 2027, and the EO series moves every few days.

Sources:
[Public Laws: Numbers for the Current Session](https://www.archives.gov/federal-register/laws/current.html) ·
[FR Executive Orders API](https://www.federalregister.gov/api/v1/documents.json?conditions%5Bpresidential_document_type%5D=executive_order&order=newest) ·
[About the CFR](https://www.archives.gov/federal-register/cfr/about.html) ·
[OLRC — About the U.S. Code](https://uscode.house.gov/about/info.shtml)

## Are the flags applied with the row's own date?

**No.** Grep of `unified_agenda_parquet.py` for `publication_id` shows the
only calendar-aware rule in the builder is `_act_key_within_calendar` (act
names, line 1442). The six series flags are computed at lines 1034, 1046 and
2155–2171 from the present-day constants alone. `_cfr_title_is_possible` and
`usc_title_is_possible` take a bare integer and have no date parameter at all.

**In the destructive direction this costs nothing here.** Every flagged value
is out of series in *every* year, so no date-aware rule would un-flag any of
them. The CFR-35 case is already handled the other way — by widening the
bound to the whole 1–50 roster rather than by dating it — and that is the
right shape.

**In the permissive direction it costs at least one row, and the row is real
damage.** Calendar-blindness lets a value through because a title that did
not exist at filing exists now:

> **RIN 3206-AK49** (OPM, "Agency Reporting Requirements"), editions 200404
> and 200410. `CFR_LIST: 5 CFR 410`. `LEGAL_AUTHORITY: 54 USC 4118`.
> 5 CFR part 410 is OPM's training regulation and **5 U.S.C. 4118** is its
> rulemaking authority. Title 54 was enacted **2014-12-19** — ten years after
> this row was filed. A date-aware check would have called it impossible.
> `usc_title_is_possible` says `true`.

Three more of the same shape, all benign-looking and all unflagged: 3 rows
cite `52 U.S.C.` before its 2014 creation (eds 201110–201304) and 4 cite
`34 U.S.C.` before its 2017 creation (eds 201504–201610).

That is 9 rows total — small, and the fix is a *widening* of what gets
labelled, never a narrowing. Per doctrine I am not proposing the flags change
behaviour on it; I am recording that the question "was this title real when
the row was filed?" is currently unasked, and that the answer is available
(the OLRC publishes enactment dates for titles 51, 52, 54 and the 2017
editorial creation of 34).

## Values that are a different kind of thing entirely — 22 rows

### Supreme Court reporter citations read as U.S. Code titles — 12 rows

The two largest unexplained USC values, `318 USC 363 (1942)` (6 rows) and
`332 USC 234 (1947)` (6 rows), both at **RIN 1510-AB25** (Treasury Financial
Management Service, *Indorsement and Payment of Checks Drawn on the United
States Treasury*, 31 CFR 240, eds 200910–2012), are **not U.S. Code citations
at all**. They are volumes of the *United States Reports*:

- **318 U.S. 363 (1943)** — *Clearfield Trust Co. v. United States*, the
  foundational federal-common-law case on Treasury checks.
- **332 U.S. 234 (1947)** — *United States v. Munsey Trust Co.*

The proof is inside the dataset. The **predecessor RIN for the same
regulation**, `1510-AA45` (eds 199510–200404), writes the same two citations
as `318 US 363 (1943)` and `332 US 234 (1947)` — and RefSpec reads those
**correctly**, as `authority_type = 'case_citation'`, `case_reporter = 'U. S.'`,
`case_volume` 318 and 332. Same office, same part 240, same two authorities,
two spellings:

| RIN | editions | source text | RefSpec reads |
|---|---|---|---|
| 1510-AA45 | 199510–200404 | `318 US 363 (1943)` | `case_citation`, U. S. 318:363 |
| 1510-AA45 | 200010–200404 | `332 US 234 (1947)` | `case_citation`, U. S. 332:234 |
| 1510-AB25 | 200910–2012 | `318 USC 363 (1942)` | `usc`, **title 318**, flagged |
| 1510-AB25 | 200910–2012 | `332 USC 234 (1947)` | `usc`, **title 332**, flagged |

The publisher's later filer typed `USC` for `US` (and drifted 1943 → 1942).
RefSpec read what was written, which is correct behaviour — `USC` means the
Code. But the row's verdict, "U.S.C. title 318 is impossible", describes the
wrong universe. The table already has `case_reporter` / `case_volume` /
`case_page` columns and 21 rows in them are exactly these two cases.

**What I would propose, and would not:** I would *not* have the grammar
re-read `NNN USC NNN (YYYY)` as a case citation on the strength of a
parenthesised year — that is a guess, and `422 USC 6938`-style damage looks
similar. What is available without guessing is the *label*: this is the same
"one string, two competing readings" situation the module already handles for
`117 Stat.` after a section list, and the honest column is one that says the
reading is contested, not one that picks. Leaving behaviour alone is also
defensible; the flag does catch these, it just names them wrongly.

### A Statutes at Large page range labelled "Pub. L." — 6 rows

`Pub. L. No. 1245-46 (2021)` at **RIN 3060-AL56** (FCC, *Digital
Discrimination*, eds 202304–202510). Its own sibling authorities are
`Sec. 60506 of the Infrastructure Investment and Jobs Act`,
`Pub. L. No. 117-58, 135 stat. 429`, and `47 U.S.C. 1754`. Pub. L. 117-58
begins at **135 Stat. 429**, and its **§ 60506 ("Digital Discrimination")
is at 135 Stat. 1245** — exactly the digits in the flagged value. The standard
citation is **"Public Law 117-58, 135 Stat. 429, 1245-46 (2021)"**, which the
FCC's own orders use. The Agenda's form split that one citation across two
fields and the second fragment kept the `Pub. L. No.` label. **`1245-46` is a
page range in volume 135, not a Public Law number.**
Sources: [PLAW-117publ58](https://www.govinfo.gov/content/pkg/PLAW-117publ58/pdf/PLAW-117publ58.pdf) ·
[FCC, *Digital Discrimination of Access* R&O](https://docs.fcc.gov/public/attachments/FCC-22-98A1.txt) · 47 CFR part 16.

### An act's section range labelled "Pub. L." — 2 rows

`Pub. L. 301-305` at **RIN 3235-AM20** (SEC, *Regulation Crowdfunding
Amendments*, eds 201910, 202004), sibling `Pub. L. 112-106`. Regulation
Crowdfunding implements **Title III of the JOBS Act, Pub. L. 112-106,
§§ 301–305** (the CROWDFUND Act). `301-305` is a section range of the law
named beside it.

### A U.S.C. section range labelled "PL" — 2 rows

`31 USC PL 5311-5314` at **RIN 1506-AA87** (FinCEN, *Bank Secrecy Act
Regulations — Check Cashers*, eds 200704, 200710). The Bank Secrecy Act is
**31 U.S.C. 5311–5314**. This row loses twice: the grammar publishes a
non-existent Public Law and drops the real U.S.C. citation entirely —

```
parse_authority_citation("31 USC PL 5311-5314")
  -> public_law '5311-5314'                      (only reading)
parse_authority_citation("31 USC 5311-5314")
  -> usc title 31, sections 5311-5314            (correct)
```

The stray `PL` between the code name and the section breaks the U.S.C.
reader. The flag catches the phantom; the real citation is simply absent from
the table.

## The 36 placeholders — 82% of the CFR-title flag

| string | rows | editions |
|---|---:|---|
| `00 CFR NYD` | 16 | 200310–201710 |
| `00 CFR None` | 15 | 200310–202104 |
| `00 CFR 00` | 3 | 200504–200610 |
| `0 CFR 00` | 1 | 199510 |
| `00 USC 00` | 1 | 199604 |
| **total** | **36** | |

Each is a sentinel the codebase already recognises, with a numeric prefix the
`states_nothing` check does not strip. `NYD` = *Not Yet Determined*; the same
records write the bare form in other fields (RIN 0938-AK77's
`LEGAL_AUTHORITY` is the bare string `Not Yet Determined`; RIN 1115-AE28's
`CFR_LIST` is `Not yet determined` while its `LEGAL_AUTHORITY` is
`00 USC 00`). 22,123 CFR-reference rows already carry NULL titles from the
bare forms. These 36 are the same statement wearing a numeral.

*This overlaps the "unstated placeholders" ledger row (which fences on
`authority_type = 'unstated'` and so cannot see these). The boundary between
the two rows is exactly the `00 ` prefix.*

Note the one title-0 row that is **not** a placeholder, and how it was told
apart: `0 CFR 150 to 189` at RIN 2070-AC97, ed 199510, siblings `40 CFR 372`
and `40 CFR 700 to 799` — and **the same RIN, same ordinal, in ed 199604 and
every edition after, reads `40 CFR 150 to 189`**. A truncated real citation,
not a sentinel.

## RefSpec's own defect — 3 rows, and a reproducible boundary hole

`sec. 607, Pub. L. 109-162 Stat. 3051` at **RIN 2506-AC40** (HUD, eds 201510,
201604, 201610) emits **two** rows from one string:

```
parse_authority_citation("sec. 607, Pub. L. 109-162 Stat. 3051")
  -> public_law       '109-162'          <- correct
  -> statute_at_large volume 162, page 3051   <- manufactured
```

The Statutes reader starts **inside the Public Law number**, immediately after
the hyphen, and takes `162` as a volume. The boundary guards are

```python
_LEFT  = r"(?<![0-9A-Za-z])"
_RIGHT = r"(?![0-9A-Za-z])"
```

— a hyphen is neither a digit nor a letter, so `_LEFT` permits a match that
begins at the second half of `109-162`. This is the same class of bug the
module already documents and fixed for the Federal Register case ("5 U.S.C.
301, 117 Stat. 429" publishing a phantom section 71), but that fix lives in
`_ANOTHER_CITATION_AHEAD`, which guards *list separators* and cannot see a
hyphen. Reproduced above from the installed module; also reproduces with
`"Pub. L. 109-162 Stat 3051"` alone.

The real citation is Pub. L. 109-162 (Violence Against Women and Department of
Justice Reauthorization Act of 2005, Jan. 5, 2006, **119 Stat. 2960**), whose
**§ 607 begins at 119 Stat. 3048** — so `Stat. 3051` is a coherent page inside
the section the string names. **The volume number is simply absent from the
publisher's string**, and the grammar supplied one from the digits next door.
`stat_volume_in_series` caught it, which is the flag working exactly as
intended; but the value it flagged is RefSpec's, not the publisher's, and that
is worth distinguishing in the ledger.
Source: [PLAW-109publ162](https://www.govinfo.gov/content/pkg/PLAW-109publ162/pdf/PLAW-109publ162.pdf)

`70A Stat.` and `68A Stat.` still behave correctly (`statute_volume` NULL,
`statute_volume_text` carries the letter), so the earlier repair holds.

## The cross-edition oracle: the publisher corrects itself

Seventeen of the flagged strings have a **clean near-twin at the same RIN in
another edition**. This is the strongest evidence available and it needs no
web source at all:

| flagged | RIN | the same RIN's other edition |
|---|---|---|
| `0 CFR 150 to 189` | 2070-AC97 | `40 CFR 150 to 189` |
| `60 CFR 679` | 0648-AR46, -AR64 | `50 CFR 679` |
| `59 CFR 1560` | 1652-AA32 | `49 CFR 1560` |
| `CFR 460 CFR 482 CFR 483` | 0938-AR72 | `42 CFR 460` / `42 CFR 482` / `42 CFR 483` (ed 201304, as three entries) |
| `80 USC 811` | 1219-AB09 | `30 USC 811` |
| `423 USC 3535(d)` | 2577-AB96 | `42 USC 3535(d)` |
| `449 USC 5101 to 45105` | 2120-AI59 | `49 USC 45101 to 45105` |
| `449 USC 5102 to 45103` | 2120-AI82 | `49 USC 45102 to 45103` |
| `347 USC 307(e)` | 3060-AI92 | `47 USC 307(e)` |
| `166 U.S.C. 1531 et seq.` | 1018-AZ35 | `16 U.S.C. 1531 et seq.` |
| `412 U.S.C. 6313(a)(6)(C)(i) and (vi)` | 1904-AD34 | `42 U.S.C. 6313(a)(6)(C)(i) and (vi)` |
| `331 USC 331 and 3334` | 1510-AB25 | `31 USC 321, 3327, 3328, 3331, 3334, 3711, 3712` (ed 2012) |
| `sec 41349 USC 20166` | 2130-AC14 | `sec 413 49 USC 20166` |
| `PL 9909-499` | 2070-AD09 | `PL 99-499` |
| `PL 11-203` | 1505-AC36 | `PL 111-203` |
| `Pub. L. 12-29 sec. 37` | 0910-AI29 | `Pub. L. 112-29 sec. 37` |
| `Pub. L. 11-84` | 0790-AJ40 | `Pub. L. 111-84` |
| `E.O. 23891, Promoting the Rule of Law Through Improved Agency Guidance Documents (Oct. 9, 2019)` | 0350-AA12 | `E.O. 13891, Promoting the Rule of Law Through Improved Agency Guidance Documents (Oct. 9, 2019)` |

Three of the damage mechanisms become legible from these pairs:

- **a digit migrating left out of the section into the title**:
  `49 USC 45101` → `449 USC 5101`; `31 USC 3331` → `331 USC 331`.
- **a lost space fusing two numbers**: `sec 413 49 USC` → `sec 41349 USC`.
- **the leading `1` of a five-digit EO or three-digit Congress becoming `2`,
  or vanishing**: `13891`→`23891`, `12600`→`21600`, `10450`→`20450`,
  `111-203`→`11-203`.

**Caution — the oracle is not authoritative on its own.** `Pub. L. 1014-410`
(RIN 1010-AE06) has a clean-looking sibling: ed 202004 writes
`Pub. L. 104-410`. But **Pub. L. 104-410 does not exist** — the 104th Congress
ended at 104-333 — while `Pub. L. 101-410` (Federal Civil Penalties Inflation
Adjustment Act of 1990) does. The builder's existing
`public_law_corrected = 101-410 / unique-roster-existence` is right and the
publisher's own restatement is wrong. Existence beats testimony.
Source: [Final listing, 2nd session of the 104th Congress](https://www.archives.gov/files/federal-register/laws/past/104-second-session.txt)

## The correction machinery: why it fires once in 91

`_public_law_correction` corrected exactly **one** of the 91 flagged PL rows
(`1014-410` → `101-410`). It is deliberately fail-closed:
`_digit_variants` generates candidates by **adjacent transposition** and
**single digit drop** applied to the congress token, requires roster
existence, requires any stated date to match, and requires exactly one
survivor.

Those operators model *an extra digit in the observed token*. Most of this
population is the opposite — a **missing** digit — so no candidate is ever
generated:

| observed | operators reach | real referent |
|---|---|---|
| `11-203` | `1-203` | `111-203` (needs an insertion) |
| `11-84` | `1-84` | `111-84` |
| `12-29` | `1-29`, `21-29` | `112-29` |
| `15-325` | `1-325`, `5-325`, `51-325` | `115-325` |
| `155-123` | `515-123`, `55-123`, `15-123` | `115-123` (needs a substitution) |
| `1014-410` | `101-410`, `104-410`, `114-410`, … | `101-410` ✔ fires |

**I am not proposing to widen the operator set** — an insertion operator over
a 3-digit token generates ~30 candidates and the "exactly one survivor" fence
would start passing coincidences. What this population shows instead is that
**three kinds of in-row evidence are already present and unused**, and none of
them is a guess:

1. **A co-cited Statutes at Large volume and page in the same string.**
   `PL 220-432, Div A, 122 Stat 4848 et seq` — **122 Stat. 4848 is both the
   first page of Pub. L. 110-432 and the page where "DIVISION A—RAIL SAFETY"
   begins**, so even the row's `Div A` matches (RIN 2130-AC10, FRA).
   `PL 11-24, 123 Stat 1734` — 123 Stat. 1734 is Pub. L. **111-24** (Credit
   CARD Act of 2009, RIN 3084-AA94, FTC). The roster the builder already loads
   carries volumes; a volume+page that names exactly one law is an existence
   proof, not a digit game. This alone would reach 21 of the 91 rows.
   Sources: [PLAW-110publ432](https://www.govinfo.gov/content/pkg/PLAW-110publ432/pdf/PLAW-110publ432.pdf) ·
   [PLAW-111publ24](https://www.govinfo.gov/content/pkg/PLAW-111publ24/pdf/PLAW-111publ24.pdf)
2. **A position in a sorted sibling list.** RIN 0790-AJ40's authority list is
   a strictly ascending run of NDAAs — `106-65, 108-375, 109-163, 109-364,
   110-417, `**`11-84`**`, 111-383, 112-81, 112-239, 113-66, 113-291, 114-92,
   116-92` — and only `111-84` fits between 110-417 and 111-383.
3. **The RIN's own other editions**, subject to the roster check above.

That is a proposal for a *labelled correction column that already exists*
(`public_law_corrected` / `pl_correction_evidence`), not a change to any
flag, and not a deletion of anything.

## Complete census — all 46 distinct authority values and 12 CFR values

Every distinct flagged value, its resolution, and how it was reached.
`sib` = the same RIN in another edition; `rec` = the record's own title,
abstract or sibling authorities; `web` = external source.

### `usc_title_is_possible = false` — 130 rows

| value | text | rows | RIN(s) | resolution | how |
|---:|---|---:|---|---|---|
| 61 | `61 U.S.C. 4901 to 4916` / `61 USC …` | 23 | 1018-AW83 | 16 U.S.C. 4901–4916 (Wild Bird Conservation Act) | rec — rule title names the Act; 50 CFR 15 |
| 410 | `410 USC 421`, `410 USC 1303` | 18 | 10 DARS RINs | 41 U.S.C. 421 / 1303 | rec — DFARS, 48 CFR |
| 59 | `59 U.S.C. 4801-4582`, `59 USC 2401 et seq`, `59 USC 5101 et seq…` | 15 | 0694-AG08, -AE94, 2137-AE12 | 50 U.S.C. 4801–4852 / 50 U.S.C. app. 2401 / 49 U.S.C. 5101 | rec + web |
| 347 | `347 USC 307(e)` | 11 | 3060-AI92 | 47 U.S.C. 307(e) | sib |
| 412 | `412 USC 1480`, `412 U.S.C. 6313(a)(6)(C)…` | 10 | 0570-AA62, 1904-AD34 | 42 U.S.C. 1480 / 6313 | sib |
| 72 | `72 USC 3535(d)` | 9 | 2501-AD36 | 42 U.S.C. 3535(d) | rec |
| 166 | `166 USC 1531 et seq` | 8 | 1018-AZ35 | 16 U.S.C. 1531 (ESA) | sib |
| 115 | `115 USC 78o(d)` | 7 | 3235-AK18 | 15 U.S.C. 78o(d) | rec |
| **318** | `318 USC 363 (1942)` | 6 | 1510-AB25 | **318 U.S. 363 — *Clearfield Trust*** | sib (1510-AA45) + web |
| **332** | `332 USC 234 (1947)` | 6 | 1510-AB25 | **332 U.S. 234 — *Munsey Trust*** | sib (1510-AA45) + web |
| 94 | `94 USC 60101 to 60125` | 3 | 2137-AC79 | 49 U.S.C. 60101–60125 (pipeline safety) | rec |
| 331 | `331 USC 331 and 3334` | 2 | 1510-AB25 | 31 U.S.C. 3331 and 3334 | sib |
| 442 | `442 U.S.C. sec. 7401 et seq.`, `442 usc 402` | 2 | 2060-AU69, 0960-AF37 | 42 U.S.C. 7401 (CAA) / 42 U.S.C. 402 (SSA) | rec |
| 449 | `449 USC 5102 to 45103`, `449 USC 5101 to 45105` | 2 | 2120-AI82, -AI59 | 49 U.S.C. 45102–45103 / 45101–45105 | sib |
| 423 | `423 USC 6938`, `423 USC 3535(d)` | 2 | 2090-AA36, 2577-AB96 | 42 U.S.C. 6938 / 3535(d) | sib |
| 0 | `00 USC 00` | 1 | 1115-AE28 | **placeholder** | rec |
| 80 | `80 USC 811` | 1 | 1219-AB09 | 30 U.S.C. 811 (MSHA) | sib |
| 315 | `315 USC 1123` | 1 | 0651-AB78 | 15 U.S.C. 1123 (Lanham Act) | rec — sibling `35 USC 2`, 37 CFR 2/7 |
| 232 | `232 USC 101(a)` | 1 | 1076-AE12 | 23 U.S.C. 101(a) | rec — siblings `23 USC 202`, `23 USC 204` |
| 515 | `515 USC 717 to 717z` | 1 | 1902-AC38 | 15 U.S.C. 717–717z (Natural Gas Act) | rec — FERC |
| 41349 | `sec 41349 USC 20166` | 1 | 2130-AC14 | `sec 413` + 49 U.S.C. 20166 | sib |

### `pl_congress_in_series = false` — 91 rows

| value | rows | RIN(s) | resolution | how |
|---|---:|---|---|---|
| `220-432` | 13 | 2130-AC10 | Pub. L. 110-432, Div. A | rec — co-cited `122 Stat 4848` = first page of the law **and** of Division A |
| `155-271` | 12 | 1515-AE46 | Pub. L. 115-271 | rec — string states "(October 24, 2018)"; 115-271 was approved that day, 132 Stat. 3894, and does have a Title VIII |
| `11-24` | 11 | 3084-AA94, -AB63 | Pub. L. 111-24 | rec — co-cited `123 Stat 1734` |
| `155-123` | 8 | 4 FSA RINs | Pub. L. 115-123 (132 Stat. 64) | rec — abstract names the Act |
| `155-334` | 7 | 0560-AI43 | Pub. L. 115-334 (132 Stat. 4490) | rec — FSA, 2018 Farm Bill |
| **`1245-46`** | 6 | 3060-AL56 | **135 Stat. 1245-46 — a page range** | rec + web |
| `12-29` | 5 | 0910-AI29 | Pub. L. 112-29 § 37 (AIA, 125 Stat. 341, "Calculation of 60-Day Period for Application of Patent Term Extension") | sib + rec |
| `11-203` | 4 | 3235-AL11, 1505-AC36 | Pub. L. 111-203 | sib |
| `11-148` | 4 | 0938-AS02, -AS16 | Pub. L. 111-148 (ACA) | rec — CMS |
| `15-325` | 3 | 1076-AF47 | Pub. L. 115-325 (Dec. 18, 2018, 132 Stat. 4445) | rec — abstract names the "Indian Tribal Energy Development and Self-Determination Act Amendments" |
| `166-20` | 3 | 0560-AI55 | Pub. L. 116-20 (June 6, 2019, 133 Stat. 871) | rec — FSA disaster programme |
| `203-111` | 3 | 3235-AK85 | Pub. L. 111-203 § 1504 (halves swapped) | rec |
| `9909-499` | 2 | 2070-AD09 | Pub. L. 99-499 (SARA, 100 Stat. 1613; Title III = EPCRA) | sib + rec |
| `1014-410` | 2 | 1010-AE06 | Pub. L. 101-410 (104 Stat. 890) | roster (already corrected) |
| `4-74` | 2 | 1014-AA55 | Pub. L. 114-74 § 701 (129 Stat. 599) | rec — string names the Act, and § 701(a) carries exactly that short title |
| **`5311-5314`** | 2 | 1506-AA87 | **31 U.S.C. 5311–5314** | rec + web |
| **`301-305`** | 2 | 3235-AM20 | **JOBS Act §§ 301–305 of Pub. L. 112-106** | rec + web |
| `11-84` | 1 | 0790-AJ40 | Pub. L. 111-84 | sib + sorted-list position |
| `27-258` | 1 | 0551-AA59 | Pub. L. 97-258 | **web — eCFR 7 CFR 6 subpart B** |

The last one is worth spelling out because it looked unresolvable. RIN
0551-AA59's authority list is
`19 USC 1202 | 19 USC 3513 | 19 USC 3601 | PL 27-258 | PL 103-465, paras 103 and 104, 96 Stat 1051, as amended | Presidential Proclamation 7235 … | Additional US Note 8 to chap 17 of the HTSUS`.
The eCFR authority for 7 CFR part 6 subpart B reads, verbatim:

> "Additional U.S. Notes … to Chapter 4 and General Note 15 of the Harmonized
> Tariff Schedule of the United States (19 U.S.C. 1202), **Pub. L. 97-258, 96
> Stat. 1051, as amended (31 U.S.C. 9701)**, and secs. 103 and 404, Pub. L.
> 103-465, 108 Stat. 4819 (19 U.S.C. 3513 and 3601)."

Every element lines up in order. `27-258` is **Pub. L. 97-258**, and the
`96 Stat 1051` that the Agenda hangs on the 103-465 entry actually belongs to
97-258 — the filer split the authority line at the wrong place. Note the
calendar did real work here: the row was filed in ed 200010, which rules out
Pub. L. 107-258 (2002) as a candidate before any digit reasoning starts.

### `stat_volume_in_series = false` — 19 rows

| value | text | rows | RIN | resolution |
|---:|---|---:|---|---|
| 188 | `Pub. L. 108-199, 188 Stat 445-46` | 9 | 1090-AB05 | volume **118** — Pub. L. 108-199 begins at 118 Stat. 3, and 118 Stat. 445-446 is real text inside its Division H |
| 199 | `199 Stat 594` | 7 | 2137-AE11 | volume **119** (page open, see specimen 4) |
| 162 | `sec. 607, Pub. L. 109-162 Stat. 3051` | 3 | 2506-AC40 | **RefSpec artifact** — volume taken from the PL number. The intended citation is coherent: Pub. L. 109-162 begins at 119 Stat. 2960 and its **§ 607 begins at 119 Stat. 3048**, so page 3051 falls inside § 607. The string is missing its volume, not carrying a wrong one. |

### `eo_in_known_series = false` — 7 rows

| value | rows | RIN | resolution | how |
|---:|---:|---|---|---|
| 20450 | 3 | 2105-AC51 | **E.O. 10450** | web — see below |
| 21600 | 2 | 2105-AC69 | **E.O. 12600** | web — 1999 CFR ed. of 49 CFR 7, `SOURCE: 63 FR 38331` = the RIN's own FR citation |
| 23891 | 2 | 0350-AA12 | **E.O. 13891** | sib — same RIN ed 202104, identical title and date |

**E.O. 20450 → E.O. 10450.** RIN 2105-AC51's `FR_CITATION` is `61 FR 33886`,
the NPRM the Agenda entry describes (DOT/OST, "Classified Information;
Revision," July 1, 1996, 49 CFR parts 1 and 8). Its proposed authority line
for part 8 reads verbatim:

> `Authority: EO 10450, 18 FR 2489, 3 CFR 1949–1953, Com., p. 936; EO 12829, 58 FR 3479; EO 12458, 60 FR 19825; EO 12968, 60 FR 40245.`

The Agenda lists `49 USC 322 | EO 20450 | EO 12968` — 12968 matches exactly,
and 20450 is **E.O. 10450** ("Security Requirements for Government
Employment," Apr. 27, 1953, 18 FR 2489) with a `1 → 2` substitution. The final
rule at **62 FR 23661** (May 1, 1997) adopted `E.O. 10450, 3 CFR, 1949–1953
Comp., p. 936; E.O. 12829 …; E.O. 12958 …; E.O. 12968 …`, so 10450 is the
codified answer too. (Two side notes: the `EO 12458` in the NPRM is itself a
Federal Register misprint — 60 FR 19825 is **E.O. 12958**; and part 8's
authority as *codified through the 1996 CFR edition* was E.O. 11652, not any
of these. Neither disturbs the identification, because the Agenda row
describes the 1996 NPRM, and the NPRM prints 10450.)
Sources: [61 FR 33886](https://www.govinfo.gov/content/pkg/FR-1996-07-01/pdf/96-16524.pdf) ·
[62 FR 23661](https://www.govinfo.gov/content/pkg/FR-1997-05-01/pdf/97-9787.pdf)

Both 1996-98 cases are the same DOT office making the same `1xxxx → 2xxxx`
error two years apart.

### `cfr_title_is_possible = false` — 44 rows

| value | text | rows | RIN(s) | resolution |
|---:|---|---:|---|---|
| 0 | `00 CFR NYD` / `00 CFR None` / `00 CFR 00` / `0 CFR 00` | 35 | 30 RINs | **placeholder** |
| 0 | `0 CFR 150 to 189` | 1 | 2070-AC97 | 40 CFR 150–189 (sib) |
| 234 | `234 CFR 200.14` | 3 | 1810-AB40 | 34 CFR 200.14 — siblings are 34 CFR 200.13, .15 … .22 |
| 60 | `60 CFR 679` | 2 | 0648-AR46, -AR64 | 50 CFR 679 (sib) |
| 420 | `420CFR 412.23(b)(2)` | 1 | 0938-AN92 | 42 CFR 412.23(b)(2) |
| 460 | `CFR 460 CFR 482 CFR 483` | 1 | 0938-AR72 | 42 CFR 460, 482, 483 (sib, ed 201304) |
| 59 | `59 CFR 1560` | 1 | 1652-AA32 | 49 CFR 1560 (sib) |

### `cfr_part_is_plausible = false` — 7 rows

| value | rows | RIN | resolution |
|---:|---:|---|---|
| `412106` | 6 | 0938-AK77 | 42 CFR **412.106** — the record's own title names the DSH adjustment |
| `634761471` | 1 | 3060-AF88 | a fused **list**, not a part. FCC, "Streamlining the Section 214 International Authorizing Process and Tariff Requirements". The nine digits read cleanly as `63 47 61 47 1` — 47 CFR parts 63, 61 and 1, with the title repeated — but that is a reading, not a proof. **Open.** What is certain: no CFR part has nine digits. |

## What I would not touch

- **No flag should stop firing.** Every value is genuinely out of series;
  every flag is doing the job it was built for.
- **No bound should be narrowed.** The one change I can evidence is a
  *widening*: `STAT_VOLUME_HIGHEST_KNOWN` 139 → 140, sourced above.
- **`47 CFR 634761471`** — the part is certainly implausible; the intended
  list is a plausible reading and nothing more. Leave it flagged and
  unresolved.
- **`199 Stat 594`, page 594** — the volume is resolvable to 119; the page
  contradicts the public law cited beside it. Open.
- **The `NNN USC NNN (YYYY)` → U.S. Reports reading** — I would not have the
  grammar infer it. The evidence that these two are cases is a *sibling RIN*,
  which is data, not a rule; a rule keyed on the parenthesised year would
  start guessing.

## Appendix — reproducing the sample

```python
SEED = 20260822
rng = random.Random(SEED)
# one specimen per flag, preferring a value not yet drawn, in flag order:
#   usc_title_is_possible, eo_in_known_series, pl_congress_in_series,
#   stat_volume_in_series, cfr_title_is_possible, cfr_part_is_plausible
# then four more from the pooled remainder, same RNG, same preference.
# Rows ordered by (rin, publication_id, ordinal) before shuffling.
```

Sources consulted (govinfo `PLAW-*` / `STATUTE-*` PDFs were read for every
Public Law identification in the census; the distinctive ones are linked
inline above):
[archives.gov current public laws](https://www.archives.gov/federal-register/laws/current.html) ·
[archives.gov 104th Congress final listing](https://www.archives.gov/files/federal-register/laws/past/104-second-session.txt) ·
[archives.gov About the CFR](https://www.archives.gov/federal-register/cfr/about.html) ·
[OLRC](https://uscode.house.gov/about/info.shtml) ·
[50 U.S.C. ch. 58](https://uscode.house.gov/view.xhtml?path=%2Fprelim%40title50%2Fchapter58&edition=prelim) ·
[eCFR API, 49 CFR 7](https://www.ecfr.gov/api/versioner/v1/full/2024-01-01/title-49.xml?part=7) ·
[eCFR API, 7 CFR 6](https://www.ecfr.gov/api/versioner/v1/full/2024-01-01/title-7.xml?part=6) ·
[govinfo, 61 FR 33886](https://www.govinfo.gov/content/pkg/FR-1996-07-01/pdf/96-16524.pdf) ·
[govinfo, 62 FR 23661](https://www.govinfo.gov/content/pkg/FR-1997-05-01/pdf/97-9787.pdf) ·
[CFR-1999-title49-vol1 part 7](https://www.govinfo.gov/content/pkg/CFR-1999-title49-vol1/pdf/CFR-1999-title49-vol1-part7.pdf) ·
[Clearfield Trust Co. v. United States, 318 U.S. 363 (1943)](https://supreme.justia.com/cases/federal/us/318/363/) ·
[federalregister.gov Executive Orders API](https://www.federalregister.gov/api/v1/documents.json?conditions%5Bpresidential_document_type%5D=executive_order&order=newest) ·
[16 U.S.C. ch. 69 (Wild Bird Conservation Act)](https://uscode.house.gov/view.xhtml?path=/prelim@title16/chapter69&edition=prelim) ·
[United States v. Munsey Trust Co., 332 U.S. 234 (1947)](https://supreme.justia.com/cases/federal/us/332/234/) ·
[FCC, Digital Discrimination R&O](https://docs.fcc.gov/public/attachments/FCC-22-98A1.txt)
