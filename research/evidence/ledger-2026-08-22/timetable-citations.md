# The 21 timetable Federal Register citations that fail to parse

**2026-08-22.** A complete census — all 21 rows, every one read against its
full source record and against the Federal Register itself. Nothing here is
sampled.

Population: `output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_timetables.parquet`,
671,959 rows, `parse_status` distribution measured today:

| status | rows |
|---|---:|
| `absent` | 394,973 |
| `ok` | 276,792 |
| `positional` | **109** |
| `relabeled` | 64 |
| `failed` | **21** |

(The ledger row quoted 102 positional; the built parquet carries 109. The
receipt's `timetableFrCitationFailures` is 21 and matches.)

Sources read: the pinned publisher XML
(`unified-agenda-editions/REGINFO_RIN_DATA_<publication_id>.xml`, 60 editions,
whole `TIMETABLE_LIST` for each of the 16 distinct RINs, in every edition that
carries them — 141 records), the Federal Register API
(`federalregister.gov/api/v1`), and govinfo issue metadata
(`govinfo.gov/metadata/pkg/FR-<date>/mods.xml`).

## The census — all 21 rows verbatim

| # | RIN | ed | ord | action | date | `fr_citation_text` | class |
|---:|---|---|---:|---|---|---|---|
| 1 | 0648-AT97 | 200604 | 0 | Final Action | 11/07/2005 | `70 FR AT97` | RIN suffix in the page slot |
| 2 | 0648-AU91 | 200704 | 2 | Final Action | 03/12/2007 | `72 FR AU91` | RIN suffix in the page slot |
| 3 | 0790-AK07 | 201804 | 0 | Final Rule | 04/17/2018 | `83 FR AK07` | RIN suffix in the page slot |
| 4 | 2060-AN63 | 200710 | 0 | NPRM | 06/23/2006 | `71 FR` | page absent |
| 5 | 2050-AE23 | 200904 | 10 | Final CPG 5 | 09/14/2007 | `72 FR` | page absent |
| 6 | 2050-AE23 | 200910 | 10 | Final CPG 5 | 09/14/2007 | `72 FR` | page absent |
| 7 | 2050-AE23 | 201004 | 10 | Final CPG 5 | 09/14/2007 | `72 FR` | page absent |
| 8 | 3060-AK99 | 202310 | 3 | NPRM | 08/05/2020 | `85 FR` | page absent |
| 9 | 1076-AF63 | 202110 | 2 | Final Action | 08/30/2021 | `86 FR 00000` | page declared unknown |
| 10 | 2040-AF62 | 201610 | 0 | ANPRM | 09/29/2016 | `81 NFR 66900` | label damaged, page intact |
| 11 | 1625-AC52 | 202010 | 0 | NPRM | 10/05/2020 | `85 FSR 62651` | label damaged, page intact |
| 12 | 3060-AJ58 | 202304 | 20 | NPRM and Order | 06/05/2020 | `85 DR 34525` | label damaged, page intact |
| 13 | 3060-AL15 | 202204 | 1 | Final Action | 11/25/2020 | `85 FR 75770x` | stray character on the page |
| 14 | 3060-AL15 | 202210 | 1 | Final Action | 11/25/2020 | `85 FR 75770x` | stray character on the page |
| 15 | 3060-AL15 | 202304 | 1 | Final Action | 11/25/2020 | `85 FR 75770x` | stray character on the page |
| 16 | 0648-BK86 | 202504 | 2 | NPRM | 12/17/2024 | `89 FR 1022091` | digit doubled in the page |
| 17 | 0648-BK86 | 202510 | 2 | NPRM | 12/17/2024 | `89 FR 1022091` | digit doubled in the page |
| 18 | 3095-AC12 | 202410 | 0 | Direct Final Rule | 05/01/2024 | `89-85; 35007-35008` | **a different citation grammar** |
| 19 | 3095-AC17 | 202410 | 0 | Direct Final Rule | 03/28/2024 | `89-61; 21436-21437` | **a different citation grammar** |
| 20 | 3095-AC18 | 202410 | 0 | Direct Final Rule | 05/30/2024 | `89-105 ; 46803-46805` | **a different citation grammar** |
| 21 | 3301-AA03 | 202510 | 0 | Final Rule | 11/26/2025 | `90-21215` | **a different citation grammar** |

Sixteen distinct RINs, eighteen distinct values. **The population is not
closed and not unrecoverable.** Fourteen of the twenty-one are readable under
a named rule: three from the text alone under a declared convention, ten from
the pinned corpus corroborating itself, one needing the Register. Two more are
decidable only by oracle. Five carry no page at all and want a label, not a
parse. Exactly one — row 8 — should stay refused.

## Four of these are not damaged citations at all

### NARA writes `volume-issue; startpage-endpage`

Rows 18–20 are three Direct Final Rules from the National Archives, all in
edition 202410, all well-formed under a grammar the reader does not know. The
form is `<volume>-<issue number>; <first page>-<last page>`. Every field
checks out, four ways each:

| row | value | issue (govinfo `FR-<date>/mods.xml`) | FR document | pages | action |
|---|---|---|---|---|---|
| 19 | `89-61; 21436-21437` | FR-2024-03-28 = **Vol. 89, No. 61** | 2024-06406 = 89 FR 21436, RIN 3095-AC17 | **21436–21437** | "Direct final rule." |
| 18 | `89-85; 35007-35008` | FR-2024-05-01 = **Vol. 89, No. 85** | 2024-09396 = 89 FR 35007, RIN 3095-AC12 | **35007–35008** | "Direct rule." |
| 20 | `89-105 ; 46803-46805` | FR-2024-05-30 = **Vol. 89, No. 105** | 2024-11910 = 89 FR 46803, RIN 3095-AC18 | **46803–46805** | "Direct final rule." |

Three for three on volume, on issue number, on both ends of the page range,
on the RIN, and on the action label. No damage operator is involved: the
value is complete and correct, and the citation `89 FR 21436` is *derivable*
from it — volume is the number before the dash, page is the number before the
second dash. This is the strongest recovery in the census and the only one
that needs no oracle at all to justify (govinfo merely confirms that the
middle number is the issue).

### CSB writes `volume-<FR document number>`

Row 21, `90-21215`, is not a volume/page pair. **21215 is the sequence half of
Federal Register document number 2025-21215**, which is `90 FR 54242`, "Internal
Governance", a CSB Rule published **2025-11-26** — exactly the date the row
states, by exactly the agency that owns the RIN, and the only Rule the CSB
published in all of 2025 (it published three documents total). FR volume 90 is
calendar year 2025 (volume = year − 1935), so the value is the document number
with its year written as the volume it belongs to.

The positional reading is not merely unsupported, it is **refuted**: `90 FR
21215` is a real page — the *first* page of the issue of **2025-05-19** (Vol.
90, No. 95, pages 21215–21388) — six months before the row's own date, on a day
the CSB published nothing.

One honest caveat: the OFR tagged document 2025-21215 with RIN **3301-AA02**,
while the agenda row is **3301-AA03**. 3301-AA03 is the only CSB RIN in edition
202510. One of the two registers has the wrong final character; the document
itself is not in doubt.

## The pinned corpus answers ten rows by itself

Joining each failed row to other rows of the **same RIN, same action, same
date_text** — a key entirely inside RefSpec's own 60 pinned editions — yields
a reading for nine rows, and in **every one the surviving reading is unique**:

| row | value | corpus reading | editions agreeing |
|---|---|---|---:|
| 4 | `71 FR` | **71 FR 36042** | 14 |
| 5,6,7 | `72 FR` | **72 FR 52475** | 5 |
| 10 | `81 NFR 66900` | **81 FR 66900** | 16 |
| 11 | `85 FSR 62651` | **85 FR 62651** | 3 |
| 13,14,15 | `85 FR 75770x` | **85 FR 75770** | 5 |

The 2050-AE23 case is the cleanest shape in the whole census: editions 200710
and 200810 write `72 FR 52475`, editions 200904/200910/201004 write `72 FR`,
and editions 201010/201104/201110 write `72 FR 52475` again. The good value
*brackets* the damaged one in time. The publisher lost a page for three
editions and got it back.

A second join — same RIN, same edition, same date, different ordinal — adds
row 12 and nothing else:

| row | value | same-record sibling |
|---|---|---|
| 12 | `85 DR 34525` (ord 20, 06/05/2020) | **`85 FR 34525`** (ord 21, 06/05/2020, "Final Rule") |

The corrected label is sitting in the adjacent line of the same
`TIMETABLE_LIST`.

## The Federal Register confirms every one, and answers three more

The FR API indexes documents by RIN, which makes it a keyed oracle rather than
a search. Measured today:

| row | value | FR document | pub date | type | matches row's date? |
|---|---|---|---|---|---|
| 1 | `70 FR AT97` | 70 FR 67349 (05-21873) | 2005-11-07 | Rule | **yes** — sole FR doc for the RIN |
| 2 | `72 FR AU91` | 72 FR 10935 (E7-4429) | 2007-03-12 | Rule | **yes** |
| 3 | `83 FR AK07` | 83 FR 16774 (2018-08004) | 2018-04-17 | Rule | **yes** — sole FR doc for the RIN |
| 4 | `71 FR` | 71 FR 36042 (06-5620) | 2006-06-23 | Proposed Rule | **yes** |
| 5–7 | `72 FR` | 72 FR 52475 (E7-18150) | 2007-09-14 | Rule | **yes** |
| 9 | `86 FR 00000` | 86 FR 50251 (2021-18736) | 2021-09-08 | Rule | **no — 9 days later** |
| 10 | `81 NFR 66900` | 81 FR 66900 (2016-23432) | 2016-09-29 | Proposed Rule | **yes** |
| 11 | `85 FSR 62651` | 85 FR 62651 (2020-21071) | 2020-10-05 | Proposed Rule | **yes** |
| 12 | `85 DR 34525` | 85 FR 34525 (FCC 20-52) | 2020-06-05 | Rule | **yes** — dockets GN 20-32, **WT 10-208** |
| 13–15 | `85 FR 75770x` | 85 FR 75770 (FCC 20-150) | 2020-11-25 | Rule | **yes** — docket **GN 20-32** |
| 16,17 | `89 FR 1022091` | 89 FR 102091 (2024-29238) | 2024-12-17 | Proposed Rule | **yes** |
| 21 | `90-21215` | 90 FR 54242 (2025-21215) | 2025-11-26 | Rule | **yes** |

FCC documents carry no RIN in the FR index, so rows 12–15 were keyed on the
docket number **named in the row's own `RULE_TITLE`** ("Universal Service
Reform Mobility Fund (WT Docket No. 10-208)"; "Establishing a 5G Fund for
Rural America; GN Docket No. 20-32"). On each date there is exactly one FCC
Rule and it carries exactly that docket.

Corroboration worth naming: for row 2, the same record's ordinal 0 states
`71 FR 70939` and the FR has E6-20721 at 71 FR 70939 on 2006-12-07 for that
RIN — the record's other entries are accurate, so the damaged one is an
isolated slip. For rows 16/17, the same record's ordinal 3 states an NPRM
comment-period end of 02/18/2025 and the FR document's own `DATES` reads
"comments must be received on or before February 18, 2025".

## The one row where the text does not decide and the oracle does

Row 16/17, `89 FR 1022091`, is the only 7-digit FR page in all 671,959 rows.
Two named single-character operators survive on the text alone:

- **collapse the doubled digit** (`1022091` has exactly one adjacent pair,
  `22`) → `102091` → 89 FR 102091, the NOAA seafood-import NPRM, RIN
  0648-BK86, published 2024-12-17. ✅
- **drop the trailing digit** → `102209` → 89 FR 102209, which is a **real
  page in the very same issue** — inside 89 FR 102207–102211, an SEC notice
  about Nasdaq BX, no RIN, no relation to the rule. ❌

Text-only, two survivors. Keyed on (RIN, date, type), exactly one. This row
must be recorded as oracle-decided, not operator-decided — it is the census's
clearest demonstration that "a damage operator with a plausible result" is not
the same thing as "exactly one survivor".

## The safety boundary, measured

The reader's positional branch admits a value whose non-digit residue is in an
enumerated set `{"", "R", "F", "FR", "RF", "FRFR", "/FR"}`, and its comment
says `NFR`, `DR`, `FSR` "stay refused: no single named operation derives them
from FR". That claim is false — insertion and substitution are as ordinary as
the deletion and transposition already in the set — but the *boundary* it
draws turns out to be exactly right, for a reason the comment does not give.

Every value in the corpus with exactly two plausible numbers, bucketed by the
Damerau–Levenshtein distance of its residue from `FR`:

| residue | DL | in set | statuses | example |
|---|---:|---|---|---|
| `FR` | 0 | ✔ | ok 276,628 · positional 1 | `59 FR 41386` |
| `CFR` | 1 | ✘ | relabeled 64 | `70 CFR 300` |
| `R` | 1 | ✔ | positional 36 | `76 R 11462` |
| `-FR` | 1 | ✘ | ok 16 | `82-FR 22190` |
| `FR-` | 1 | ✘ | ok 5 | `88 FR- 16921` |
| **`FRX`** | **1** | ✘ | **failed 3** | `85 FR 75770x` |
| `/FR` | 1 | ✔ | positional 2 | `89 /FR 81156` |
| **`DR`** | **1** | ✘ | **failed 1** | `85 DR 34525` |
| **`FSR`** | **1** | ✘ | **failed 1** | `85 FSR 62651` |
| `RF` | 1 | ✔ | positional 1 | `74 RF 31642` |
| `F` | 1 | ✔ | positional 1 | `82 F 2010` |
| **`NFR`** | **1** | ✘ | **failed 1** | `81 NFR 66900` |
| `` (empty) | 2 | ✔ | positional 64 | `71 66120` |
| `FRFR` | 2 | ✔ | ok 1 · positional 4 | `79 FR FR 49659` |
| **`FRAT`** | **2** | ✘ | **failed 1** | `70 FR AT97` |
| **`FRAU`** | **2** | ✘ | **failed 1** | `72 FR AU91` |
| **`-`** | **2** | ✘ | **failed 1** | `90-21215` |
| **`FRAK`** | **2** | ✘ | **failed 1** | `83 FR AK07` |

Eighteen residues, and that is the entire space. Replacing the enumerated set
with **Damerau–Levenshtein ≤ 1 from `FR`** admits exactly six rows —
`FRX`×3, `DR`, `FSR`, `NFR` — every one of them independently corroborated
above, and **changes nothing else in the corpus**.

Extending to **≤ 2 would be a disaster**, and this is the census's most useful
negative result. It admits four more rows and all four answers are wrong:

| value | DL≤2 would read | truth | is the wrong page real? |
|---|---|---|---|
| `70 FR AT97` | 70 FR 97 | **70 FR 67349** | yes — opening days of vol. 70 |
| `72 FR AU91` | 72 FR 91 | **72 FR 10935** | yes — opening days of vol. 72 |
| `83 FR AK07` | 83 FR 7 | **83 FR 16774** | yes — opening days of vol. 83 |
| `90-21215` | 90 FR 21215 | **90 FR 54242** | yes — first page of FR-2025-05-19 |

Four for four wrong, and none of them wrong in a way a range check would
catch: each lands on a page that exists. The DL≤1 fence holds not because the
operators past it are unnameable but because **the second number in those four
values is not a page at all** — in three of them it is the digits inside the
RIN's own suffix, and in the fourth it is a document-number sequence.

## The RIN-suffix rows carry no page, and that is checkable from the row

Rows 1, 2 and 3 have the RIN's own suffix where the page belongs:
`0648-AT97` → `70 FR **AT97**`, `0648-AU91` → `72 FR **AU91**`, `0790-AK07` →
`83 FR **AK07**`. This is verifiable against the row's own `rin` column with
no oracle and no guessing. Measured over the whole corpus, the predicate
`page slot == upper(split_part(rin,'-',2))` matches **exactly 3 rows, all
failed** — it never touches an `ok`, `positional`, `relabeled` or `absent`
row.

These rows are not damaged citations. The page was never written. The correct
disposition is a *label*, not a parse: the same family as `absent`, reached by
a different route. Row 9 (`86 FR 00000`) and rows 4–8 (`<vol> FR` with nothing
after it) belong to the same family — nine rows in which the text carries a
volume and no page.

Row 9 deserves its own note: `00000` is five zeros, exactly the width of a
five-digit FR page — a template placeholder written before the OFR assigned
one. The record confirms it: the row's date is 08/30/2021, the FR published
that rule on **2021-09-08**, and **no** Bureau of Indian Affairs document
appeared on 2021-08-30 at all. The row is a pre-publication stub whose date is
the agency's own, not the Register's.

## What stays refused

**Row 8, `3060-AK99` / 202310 / ord 3 / NPRM / 08/05/2020 / `85 FR`.** The
only row in the census I would refuse outright even with the oracle in hand.

- No sibling: the RIN appears in two editions and 202004 has no such entry.
- The Federal Register published **no FCC document at all** on 2020-08-05.
- The only volume-85 FR document in MB Docket 19-282 is `85 FR 60720`
  (2020-17806, published **2020-09-28**, type Rule, action "Final rule.").
- The row's own date **and** its own action label both contradict that
  candidate — two refutations, not a match.
- The row's own sibling at ordinal 4 reads "R&O (release date) 08/05/2020",
  which tells us 08/05/2020 is an FCC *release* date and cannot be matched
  against an FR publication date at all.

Reaching 85 FR 60720 from this row needs two independent unnamed corrections.
That is a guess wearing evidence. Leave it failed.

## What a rule would read, and exactly which rows

| rule | derivation | rows it answers | overfire |
|---|---|---:|---|
| **A.** `<vol>-<issue>; <start>-<end>` → volume, start page | text + declared convention (NARA form); issue confirmed against govinfo | **3** (18,19,20) | 0 |
| **B.** positional residue set → Damerau–Levenshtein ≤ 1 from `FR` | one named single-character edit; all six corroborated by sibling editions and the FR | **6** (10,11,12,13,14,15) | 0 |
| **C.** same-RIN/same-action/same-date sibling edition supplies the page | the pinned corpus corroborating itself; unique reading in all 9 | **9** (4,5,6,7,10,11,13,14,15) — **4 new** beyond B (rows 4–7) | 0 |
| **D.** `<vol>-<n>` → FR document number `<vol+1935>-<n>` | volume↔year is a bijection; sole survivor, date and agency both match | **1** (21) | 0 |
| **E.** page slot == the row's own RIN suffix → label page-unstated | the row's own `rin` column; no oracle | **3** (1,2,3) | 0 |
| **F.** page is all zeros, or absent after the label → label page-unstated | text alone | **6** (4,5,6,7,8,9), of which **2 residual** (8,9) after C | 0 |

Every predicate above was run against all 671,959 rows: each matches only
rows currently `failed`, never an `ok`, `positional`, `relabeled` or `absent`
row.

Precedence matters between C and F: F is the fallback label for a volume-only
value, and C outranks it wherever a sibling edition supplies the page. Applied
in that order, F relabels only rows 8 and 9; rows 4–7 become real citations.

The census closes exactly:

- **14 rows** gain a real volume and page — A (18,19,20), B (10–15), C adds
  4–7, D adds 21.
- **2 rows** (16,17) are decided by the RIN oracle alone, not by the text;
  if taken, they must be labelled as such, distinctly from B.
- **5 rows** (1,2,3,8,9) carry no page anywhere in the text. E and F relabel
  them *the publisher stated no page* instead of *the parser failed*. Four of
  the five have a document identifiable in the Register by RIN; **row 8 has
  none**, and no page should ever be attached to any of the five.

Nothing in the 21 is left in an undiagnosed bucket.

## Anything suggesting these are not FR citations at all

Four rows, and all four *are* Federal Register references — just not
volume/page ones. Rows 18–20 name a volume, an issue, and a page range; row 21
names a document number. The reader's assumption that this column holds
exactly `<volume> FR <page>` is what failed, not the publisher.

The three RIN-suffix rows (1–3) are the opposite case: the value looks like a
citation and contains none — the digits `97`, `91`, `07` are fragments of the
RIN, and reading them as pages produces three real, wrong pages.

## Reproducing

```sh
# the 21 rows
duckdb -c "SELECT * FROM 'output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_timetables.parquet' WHERE parse_status='failed' ORDER BY publication_id, rin, ordinal;"

# sibling-edition oracle (rule C), inside the pinned corpus only
# join failed rows to (rin, action, date_text) in other editions with parse_status in ('ok','relabeled','positional')

# external oracles, no key required
curl "https://www.federalregister.gov/api/v1/documents.json?conditions%5Bregulation_id_number%5D=0648-BK86"
curl "https://www.federalregister.gov/api/v1/documents/2025-21215.json"
curl "https://www.govinfo.gov/metadata/pkg/FR-2024-05-01/mods.xml"   # <volume>89</volume><issue>85</issue>
```

The publisher XML needs the same `b"\x19"` → `’` repair
`parse_unified_agenda_edition` applies before `ElementTree` will accept
editions 200404 and 200410.
