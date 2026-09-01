# FR short-tail widening (REF-056), 2026-08-31

Lane C of the atlas-v3-binding-and-relation-research widening cycle. This
runs REF-052/REF-054's exact recipe — raw-read samples, a rule, a
column-licensed production (fullmatch, disjoint by construction), a census
re-pin — on the two named-but-deferred refusals inside
`identifier_shapes.py`'s own comments: the bare-legacy shape's one- and
two-digit tail, and the modern shape's one- and two-digit tail.

## 1. Where the two populations live

Both are measured over the same pinned Federal Register `document_number`
column REF-052 measured (1,004,233 distinct values), at
`output/registry-real-data-sources/rulespec-stabilization-candidate-final/federal_register.parquet`
(the file `tests/test_iri_minting.py`'s `FEDERAL_REGISTER_PARQUET` constant
names, and the same file `identifier_shapes.py`'s module docstring cites as
"read 2026-08-22" / re-measured 2026-08-31).

Located by `scratch/classify_refused.py`, which sub-classifies everything the
minter refused BEFORE this cycle:

| shape | count | tail-length split |
|---|---|---|
| bare-legacy-shaped, refused (`\d{2}-\d{1,2}`) | 1,370 | 112 one-digit, 1,258 two-digit |
| modern-shaped, refused (`\d{4}-\d{1,2}`) | 286 | 27 one-digit, 259 two-digit |
| everything else still refused | 360 | partitioned in §4 |
| **total refused (REF-052/054 pinned)** | **2,016** | |

1,370 + 286 + 360 = 2,016, matching the pinned `"refused": 2_016` census
exactly.

**That script does not import the widened minter, and the first draft of it
did.** Which made the table above unreproducible the moment this lane
landed: re-running it against the live module reported 360 refusals, not
2,016, so the "before" column of the ruling could no longer be recovered
from the artifact the ruling changed. The pre-widening decision is now
FROZEN INSIDE the script, as literal patterns copied out of
`identifier_shapes` as committed — git blob `991d7ca4`, the state of the
module before this lane's edits, introduced by commit `908d74bf` (REF-052) —
with nothing in the baseline path importing refspec at all. The frozen
oracle was validated once, 2026-08-31, by exec'ing that committed file
straight out of `git show` and classifying all 1,004,233 values with both
readers: the two refusal sets were identical member for member, not merely
equal in count. The reference is a blob id rather than a commit id on
purpose — the branch moved under this lane mid-measurement, and
`git rev-parse HEAD:src/refspec/registry/identifier_shapes.py` still answers
`991d7ca4`, which is the content the widening actually widened.

The live module is still imported, for one thing, at the end of the script
and labelled as such: the DELTA check — that what the live minter refuses is
exactly the 360 the frozen baseline predicts, and that all 1,003,873
admitted values carry distinct IRIs. That direction is not circular; it is
the claim the ruling actually makes.

So the table above IS reproducible, from the pinned parquet, with the module
in any state:

```
.venv/bin/python research/evidence/fr-short-tails-2026-08-31/scratch/classify_refused.py
```

It asserts every count it prints and writes `scratch/refused_baseline.json`
(the 2,016, and the two admitted populations by name) and
`scratch/partition_of_360.json` beside itself. It used to write to a
`~/.claude/jobs/...` path that exists on one machine.

## 2. Method

For each specimen: fetch the Federal Register's own JSON API
(`https://www.federalregister.gov/api/v1/documents/{document_number}.json`)
for the citation, title, agency and `pdf_url`; download the linked govinfo.gov
PDF; **read the PDF itself** (the `Read` tool renders it visually, page by
page) to find the document's own printed colophon —
`[FR Doc. {document_number} Filed {date}; {time}]` — in the identical
typographic place every ordinary Federal Register document carries it. Three
of the twenty-four specimens (94-1, 94-9, 93-54 — all pre-1998, before
govinfo split per-document PDFs for this window) have no `pdf_url`; for those
the Register's own full-text extraction
(`https://www.federalregister.gov/documents/full_text/text/...txt`) was
fetched instead and read the same way — it is the publisher's own OCR/typeset
text of the identical page, carrying the identical colophon line.

Direct fetch succeeded for all 24 specimens (govinfo.gov and
federalregister.gov both answered normally); no escalation to the Zyte
adapter or Wayback was needed.

## 3. Sample (24 specimens, both populations, all tail-length strata, two
named sub-clusters)

Stratified by tail length within each population; the two sub-clusters
(a "93-"-prefixed bare-legacy value crossing a year boundary, and the sole
non-2010–2012 modern-short-tail value) are called out explicitly since they
were the specimens most likely to be damage rather than a real spelling, and
both attest.

### 3a. Bare-legacy short tail — `\d{2}-\d{1,2}` (1,370 values: 112 one-digit, 1,258 two-digit)

| specimen | tail | raw context (quoted from the publisher's own page) | verdict |
|---|---|---|---|
| `00-1` | 1-digit | EPA, "National Emission Standards ... Amino/Phenolic Resins Production," 65 FR 3276–3330 (2000-01-20). Page 3330: `[FR Doc. 00–1 Filed 1–19–00; 8:45 am]` | REAL — publisher's own document number, ordinary colophon |
| `94-1` | 1-digit | HUD, "Federal Property Suitable as Facilities To Assist the Homeless," 59 FR 1022 (1994-01-07). Full text ends: `[FR Doc. 94-1 Filed 1-6-94; 8:45 am]` | REAL |
| `94-9` | 1-digit | FCC, "Compatibility Between Cable Systems and Consumer Electronics Equipment," 59 FR 280–281 (1994-01-04). Full text ends: `[FR Doc. 94-9 Filed 1-3-94; 8:45 am]` | REAL |
| `97-1` | 1-digit | SEC, "Anti-manipulation Rules Concerning Securities Offerings," 62 FR 520–550 (1997-01-03). Page 550: `[FR Doc. 97–1 Filed 1–2–97; 8:45 am]` | REAL |
| `99-9` | 1-digit | HHS, "Revision of HHS National Environmental Policy Act Compliance Procedures...," 64 FR 1656–1710 (1999-01-11). Page 1710: `[FR Doc. 99–9 Filed 1–8–99; 8:45 am]` | REAL |
| `08-1` | 1-digit | Treasury/IRS (VA rule shares the page), "Guidance ... Updating of Section 7216 Regulations," 73 FR 1058–1075 (2008-01-07). Page 1075: `[FR Doc. 08–1 Filed 1–3–08; 8:58 am]` | REAL |
| `00-10` | 2-digit | FAA, Airworthiness Directive, BAC 1-11 200/400, 65 FR 207–209 (2000-01-04). Page **209**: `[FR Doc. 00–10 Filed 1–3–00; 8:45 am]`. (Page 208 was this row's first reading and is wrong — 208 is the middle page of the three and carries no colophon at all; page 207 carries `[FR Doc. 00–11 Filed 1–3–00; 8:45 am]`, the sibling short tail the module's own comment names beside this one.) | REAL |
| `00-99` | 2-digit | Commerce, "Application for Duty-Free Entry of Scientific Instrument," 65 FR 284 (2000-01-04). `[FR Doc. 00–99 Filed 1–3–00; 8:45 am]` | REAL |
| `01-11` | 2-digit | DoD/GSA/NASA, FAR final rule (Cost Accounting Standards), 66 FR 2117–2136 (2001-01-10). Page 2136: `[FR Doc. 01–11 Filed 1–9–01; 8:45 am]` | REAL |
| `04-50` | 2-digit | FAA, NPRM, BAE Systems Avro 146-RJ/BAe 146, 69 FR 289–291 (2004-01-05). Page 291: `[FR Doc. 04–50 Filed 1–2–04; 8:45 am]` | REAL |
| `07-99` | 2-digit | NIH/NIEHS, Notice of Meeting, 72 FR 1550–1551 (2007-01-12). `[FR Doc. 07–99 Filed 1–11–07; 8:45 am]` | REAL |
| `08-99` | 2-digit | NIH/Fogarty International Center, Notice of Meeting, 73 FR 2513 (2008-01-15). `[FR Doc. 08–99 Filed 1–14–08; 8:45 am]` | REAL |
| `03-03` | 2-digit | HUD, "Federal Property Suitable... Homeless," 68 FR 386 (2003-01-03). `[FR Doc. 03–03 Filed 1–2–03; 8:45 am]` | REAL |
| `93-54` (sub-cluster) | 2-digit | NRC, "Virginia Electric and Power Company (North Anna Power Station)," 59 FR 333–335 (1994-01-04). Full text ends: `[FR Doc. 93-54 Filed 1-3-94; 8:45 am]` | REAL — filed 1994-01-03 for the 1994-01-04 issue, still carries the *outgoing* year's two-digit token; this is why a "93-"-prefixed value exists at all next to an era the module documents as opening 1994-01-03. The column holds 144 "93-"-prefixed values in total: this one, plus **143 further** values with a 3+-digit tail already inside the licensed bare-legacy shape — so the year-boundary spelling is routine rather than an anomaly of the short-tail slice. (An earlier reading of this row said "144 further", double-counting `93-54` itself.) |

### 3b. Modern short tail — `\d{4}-\d{1,2}` (286 values: 27 one-digit, 259 two-digit)

| specimen | tail | raw context (quoted from the publisher's own page) | verdict |
|---|---|---|---|
| `2010-1` | 1-digit | SEC, "MetLife, Inc. and MetLife Capital Trust V; Notice of Application," 75 FR 1007–1009 (2010-01-07). Page 1009: `[FR Doc. 2010–1 Filed 1–6–10; 8:45 am]` | REAL |
| `2010-9` | 1-digit | DOE, "Environmental Management Site-Specific Advisory Board, Savannah River Site," 75 FR 983 (2010-01-07). `[FR Doc. 2010–9 Filed 1–6–10; 8:45 am]` | REAL |
| `2011-1` | 1-digit | SSA, "Agency Information Collection Activities: Proposed Request," 76 FR 817–818 (2011-01-06). Page 818: `[FR Doc. 2011–1 Filed 1–5–11; 8:45 am]` | REAL |
| `2012-9` | 1-digit | DOE/FERC, "Transcontinental Gas Pipe Line Company, LLC; Notice of Application," 77 FR 787–788 (2012-01-06). `[FR Doc. 2012–9 Filed 1–5–12; 8:45 am]` | REAL |
| `2010-10` | 2-digit | DOE, "Notice of Re-Establishment of the National Petroleum Council," 75 FR 983 (2010-01-07, same page as 2010-9). `[FR Doc. 2010–10 Filed 1–6–10; 8:45 am]` | REAL |
| `2010-99` | 2-digit | NIH/Center for Scientific Review, "Notice of Closed Meetings," 75 FR 1066–1067 (2010-01-08). `[FR Doc. 2010–99 Filed 1–7–10; 8:45 am]` | REAL |
| `2011-50` | 2-digit | DOE/FERC, "Crosstex LIG, LLC; Notice of Motion for Extension of Rate Case Filing Deadline," 76 FR 1152–1153 (2011-01-07). `[FR Doc. 2011–50 Filed 1–6–11; 8:45 am]` | REAL |
| `2012-10` | 2-digit | DOE/FERC, "Southern LNG Company, L.L.C.; Notice of Application," 77 FR 788–789 (2012-01-06). `[FR Doc. 2012–10 Filed 1–5–12; 8:45 am]` | REAL |
| `2012-99` | 2-digit | SEC, "International Securities Exchange, LLC; Notice of Filing... Fees for Certain Complex Orders," 77 FR 1103–1106 (2012-01-09). Page 1106: `[FR Doc. 2012–99 Filed 1–6–12; 8:45 am]` | REAL |
| `2013-58` (sub-cluster) | 2-digit | NOAA/NMFS, "Fisheries of the Caribbean, Gulf of Mexico, and South Atlantic; ... Trip Limit Reduction," 78 FR 907–908 (2013-01-07). Page 908: `[FR Doc. 2013–58 Filed 1–2–13; 4:15 pm]` | REAL — the sole specimen outside the 2010–2012 cluster; filed 2013-01-02 at the unusual 4:15 pm timestamp. The **facing page**, 78 FR 907 of the same issue, carries `[FR Doc. 2012–31431 Filed 1–4–13; 8:45 am]`. (An earlier reading of this row put the two colophons on the identical page; they are on adjacent pages of the same issue, verified against the PDF's own page headers.) What the pair establishes is stated in §3c below, and it is narrower than "numbering rolls over per submission" |

Every specimen in both tables answered HTTP 200 from the Federal Register's
own API, carries a coherent title/agency/date/citation, and — where the PDF
exists — shows a printed colophon in the identical typographic place and
style as every ordinary document's neighbors on the same page. Two specimens
share a page with an **ordinary 3+-digit-tail** document, which is the
comparison that matters: `2010-1` sits on 75 FR 1009 beside `2010-117` and
`2010-113`, and `07-99` sits on 72 FR 1551 beside `07-100`. (An earlier
draft offered `2010-9`/`2010-10` on 75 FR 983 and `00-27`/`00-99` on 65 FR
284 as that comparison; both pairs are short-tail beside short-tail, so they
witness the density of the family but not its typographic identity with
ordinary numbering. They are still useful and still true — `2010-9` and
`2010-10` really are consecutive on one page — just not evidence of the
thing that sentence claimed.) None is a truncation, an OCR artifact, a
different identifier kind, or damage: every one is the publisher's own
spelling of a real document number, at the low-sequence end of that year's
numbering, exactly the same posture REF-052/054 already established for the
letter-opening family's own short-tail widening.

### 3c. What the two year-boundary specimens do and do not establish

`93-54` and `2013-58` were read as evidence for a mechanism — "the
Register's numbering rolls over per submission, not per publication." That
is an inference, and the sources this lane retained do not carry it: none of
them records a submission timestamp. Nothing was fetched that could have
distinguished submission from filing. What the two colophons DO establish,
read literally, is a narrower and still useful fact:

- the year token is not determined by the **publication** date — 78 FR
  907–908, one issue of 2013-01-07, carries both a 2012-token and a
  2013-token document;
- nor by the **filing** date — on that same pair, the 2012-token document
  was filed 1-4-13, two days *after* the 2013-token one was filed 1-2-13;
- `93-54` is the same fact from the other side of a boundary: filed 1-3-94,
  published 1994-01-04, carrying the outgoing year's token.

So the token is independent of both dates the page prints. What decides it
is unestablished here, and the ruling does not need it: the column doctrine
reads shape, and the shape is what §4 licenses. Both `identifier_shapes`'s
own comment and §7's decision text state it this way.

Raw fetched bytes: `raw/`. Twenty-one govinfo PDFs for the admitted
specimens, read both as pixels (the `Read` tool renders a PDF page by page)
and as text (`pdftotext -layout`, which is what pins the exact colophon
spelling and the printed page number in each row above — and what caught the
two page errors corrected below); 3 `.txt` full-text extractions and 2
accompanying `.html` pages for the three pre-1998 specimens with no
per-document PDF split. Six further raw sources cover the REFUSED side,
fetched while re-measuring the partition in §4 — the PDFs `C0-6263A.pdf`,
`C9-20022A.pdf`, `2014-04654s.pdf` and `95-95-744.pdf`, and the `.txt`
extractions `94-2050F.txt` and `94-S16142.txt` — because two classes of that
partition are asserted here for the first time and a class assertion needs a
raw witness. API responses: `metadata/` (33 JSON files, 24 admitted + 9
refused). `SHA256SUMS.txt` covers all 69 files in `raw/`, `metadata/` and
`scratch/`; regenerated this cycle and verified with `shasum -a 256 -c`.

## 4. Ruling

**Widen both populations.** Two new column-licensed-only productions in
`identifier_shapes.py`:

```python
_FR_BARE_LEGACY_SHORT_TAIL = re.compile(r"\d{2}-\d{1,2}")
_FR_MODERN_SHORT_TAIL = re.compile(r"\d{4}-\d{1,2}")
```

Both are checked only when `column_licensed=True` (the prose reader,
`detect_identifier_shapes`, is completely untouched — every specimen above
stays undetected in running text, exactly as before). Neither widens
rulespec's own mintable space: `FEDERAL_REGISTER_DOCUMENT_NUMBER`
(`\d{4}-\d{3,5}`) is unmoved, so the 286 modern-shaped values mint through
the `rkaf:partner-defined` hatch, never through `rkaf:us-frdoc`. The
bare-legacy short tail mints through the identical hatch the wider
bare-legacy shape already uses.

**Neither existing named constant was widened in place.** Both are new
sibling productions rather than edits to `BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`
or `FEDERAL_REGISTER_DOCUMENT_NUMBER` — mirroring exactly how REF-052 kept
the four letter-opening families as a new tuple (`_FR_COLUMN_LETTER_FORMS`)
rather than rewriting an existing pattern. This matters concretely here:
`BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`'s own count (394,128) is
quoted from a file this lane does not own (`iri_minting.py`); widening the
constant in place would have silently made that quoted count wrong.

**Disjointness by construction**, the way `_FR_COLUMN_LETTER_FORMS`'s own
comment argues it:

- `_FR_BARE_LEGACY_SHORT_TAIL` (`\d{2}-\d{1,2}`) vs `_FR_BARE_LEGACY`
  (`\d{2}-\d{3,6}`): under `fullmatch` the tail length is fixed by the
  pattern, and 1–2 and 3–6 do not overlap.
- `_FR_MODERN_SHORT_TAIL` (`\d{4}-\d{1,2}`) vs `_FR_MODERN`
  (`\d{4}-\d{3,5}`): same argument, one digit count fewer.
- The two new productions vs each other, and vs `_FR_BARE_LEGACY`: a
  fullmatch fixes the digit count *before* the dash too (2 vs 4), so a
  string cannot satisfy both.
- Both vs `_FR_COLUMN_LETTER_FORMS`: every one of the four letter-opening
  families opens on `[A-Za-z]`; both new productions are pure digits. No
  string can satisfy a letter-opening form and either new one.

**What stays refused, exactly.** The remaining 360 were carried into this
lane as a four-line summary inherited from REF-052's own census comment:
"228 `-2`-suffix + 99 short-tail corrections + 32 colophon-fused + 1
`granule293`". Re-measured value by value on 2026-08-31, that summary is
wrong in two of its four lines. The real partition is seven classes, each a
shape, mutually disjoint over this population (asserted, not arranged by
ordering), and the census test now pins all seven:

| class | count | shape | disposition |
|---|---|---|---|
| collision `-2` suffix | 224 | `\d{2}-\d{3,5}-2` | aggregator's disambiguation suffix; all 224 have their un-suffixed twin in this same column |
| short-tail correction | 99 | `[Cc]\d-\d{4}-\d{2,4}` | REF-054 keeps these refused by name; unchanged |
| colophon-fused | 27 | ends on a literal `Filed` / `Doc` | printed-page composition defect, per the module's research notes |
| extra-hyphen | 4 | `\d{2}-\d{2}-\d{2,5}` | **real**, not damage — see below |
| trailing letter | 4 | one letter after the digits | **real**, not damage — see below |
| not the publisher's number | 1 | `94-S16142` | the publisher numbers this document something else |
| `granule293` | 1 | literal | the one non-identifier |

224 + 99 + 27 + 4 + 4 + 1 + 1 = 360. What the old summary got wrong:

- **224, not 228, carry a literal `-2` suffix.** The other four are a
  different shape entirely — an extra hyphenated segment: `94-94-30552`,
  `95-26-82`, `95-95-22339`, `95-95-744`. And they are not damage. The
  Federal Register's API answers for each with the identical string as its
  own `document_number` (three of the four with a citation), and
  `95-95-744`'s own printed colophon reads `[FR Doc. 95–95–744 Filed
  1–11–95; 8:45 am]` on 60 FR 2992, in the ordinary place and style, one
  page after a properly formed `[FR Doc. 95–745 Filed 1–11–95; 8:45 am]` on
  60 FR 2991. Raw: `raw/95-95-744.pdf`.
- **The "32 colophon-fused" was a catch-all**, not a class: 27 values really
  are fused (a literal `Filed`/`Doc` welded onto the number by the printed
  page's own composition defect, which is the family
  `research/fr-body-signal-inventory-2026-08-31.md` attests for `E5-2394`).
  The other five are not fused at all, and one of them —`C0-6263A` — those
  same research notes already call out by name as "not damage: the publisher
  filed it with the trailing letter." Laundering it into "fused" contradicted
  the module's own notes.

**The trailing-letter family (4), read raw.** One letter after the digits,
printed by the publisher, each with a properly formed control colophon on
the same page proving the spacing was not lost in composition:

- `C0-6263A` — `[FR Doc. C0–6263A Filed 4–5–00; 8:45 am]`, 65 FR 18151,
  Corrections, 2000-04-06, beside `[FR Doc. C0–6216 Filed 4–5–00; 8:45 am]`.
  It is a correction *of a correction*: its own body reads "in the
  correction of notice document number 00-6263," which is what the trailing
  letter distinguishes.
- `C9-20022A` — `[FR Doc. C9–20022A Filed 8–23–99; 8:45 am]`, 64 FR 46228,
  beside `[FR Doc. C9–19102 Filed 8–23–99; 8:45 am]`. Same shape, same
  section, ten months earlier: a family, not a one-off.
- `2014-04654s` — `[FR Doc. 2014–04654s Filed 2–28–14; 8:45 am]`, 79 FR
  11733, beside `[FR Doc. 2014–04620 Filed 2–28–14; 8:45 am]` on 79 FR
  11732. The trailing `s` is printed with ordinary spacing before "Filed",
  so it is **not** the fusion defect; the research notes list it under the
  fused family and that listing is corrected here.
- `94-2050F` — no PDF for the window, but the publisher's own full-text
  extraction carries both `[FR Doc No: 94-2050F]` and the printed
  `[FR Doc. 94-2050F Filed 8-19-94; 8:45 am]`.

**The one value that is not the publisher's number.** `94-S16142` is the
only `\d{2}-S\d+` value in the column. federalregister.gov answers for it,
but returns `document_number` `94-00000`, and the page's own colophon reads
`[FR Doc. 94-00000 Filed 00-00-94; 8:45 am]` — a placeholder for a Federal
Reserve Sunshine Act meeting notice. `94-00000` is separately present in
this column and mints; this spelling does not. It is the one refusal whose
document already has an identity under another string.

**Nothing here is ruled on.** REF-054 keeps the 99 corrections refused by
name and this ruling does not reopen them; the fused 27 and `granule293` are
the populations the module's research notes already dispose of. The
extra-hyphen 4 and the trailing-letter 4 are newly named as *real but
unread* — refused shapes that are the publisher's own spelling, recorded
with a count so the decision can be made with one, exactly the posture
REF-052 took toward the 1,370 this lane has now licensed. Negative fixtures
for the older sub-populations already exist in the two test files (e.g.
`94-10196-2`, `C1-2012-19`); this lane adds one more boundary fixture
(`94-1234567`, a seven-digit tail) to show the *ceiling* REF-052 measured is
untouched by this *floor* widening.

## 5. Implementation summary

- `src/refspec/registry/identifier_shapes.py`: added
  `_FR_BARE_LEGACY_SHORT_TAIL` and `_FR_MODERN_SHORT_TAIL` (private,
  unexported — same posture as `_FR_COLUMN_LETTER_FORMS`'s own four members),
  each fully documented with its specimen and count; wired both into
  `is_federal_register_document_number`'s `column_licensed=True` branch;
  updated that function's docstring. No existing constant's value or
  docstring-quoted count changed. `mint_federal_register_document_iri` in
  `iri_minting.py` needed no edit — it already delegates the whole
  `column_licensed` decision to `is_federal_register_document_number`.
  Two further edits are **comment-only**, correcting prose this cycle made
  wrong or over-claimed: the note beside
  `BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER` still called the 1,370 a
  standing refusal that "stay[s] unlicensed here" while the function forty
  lines below had begun licensing them, and the note beside
  `_FR_MODERN_SHORT_TAIL` asserted a rollover mechanism no retained source
  records (§3c).
- `tests/test_identifier_shapes.py`: fixed the one now-stale assertion
  (`test_the_bare_legacy_shape_is_licensed_by_the_column` used to pin `00-10`
  refused; it now asserts admission and points at the dedicated test below);
  added `test_the_bare_legacy_short_tail_family_is_column_licensed` and
  `test_the_modern_short_tail_family_is_column_licensed`; added
  `test_no_federal_register_production_claims_another_ones_specimen`, which
  turns the disjointness argument from a comment into a check. It offers all
  eleven FR productions — the prose reader's four, REF-052's five column
  families, and this cycle's two — each of the others' own positive
  specimens, and asserts each value matches exactly the productions it
  should. The two REAL overlaps are asserted rather than hidden
  (`R1-10679`/`R1-1234` satisfy republication *and* legacy; `R1-123`
  satisfies republication *and* the letter-opening short tail), together with
  why they are safe: the alternation is ordered, republication precedes
  legacy, and both branches read the identical characters as the identical
  value. The production table is closed against the module by construction —
  a `_FR_*` pattern added without a row here fails the test immediately.
- `tests/test_iri_minting.py`: fixed three now-stale assertions/fixtures
  (`test_the_bare_legacy_form_needs_the_column_license_and_only_that` dropped
  `"94-1"` from its equivalence-with-the-unwidened-constant loop since REF-056
  moved it; `test_the_bare_legacy_shape_stops_where_the_measurement_stops`
  flipped its `"00-10"`/`"00-1"` assertions and retitled its docstring;
  `test_the_floor_under_the_widened_tail_is_where_the_shape_layer_puts_it`
  flipped its column-licensed assertion for `"2010-99"`/`"2024-36"`/`"2011-7"`
  while leaving rulespec's own space untouched); added
  `test_the_bare_legacy_short_tail_family_needs_the_column_license_too` and
  `test_the_modern_short_tail_family_needs_the_column_license_too`; extended
  `test_document_number_padding_is_never_normalized_away` to close the
  identity question its own docstring flagged ("were the floor ever lowered,
  this test is where the identity question surfaces first") — confirmed
  `"2012-19"` under `column_licensed=True` mints through the partner hatch
  and is still a different identifier from `"2012-019"`'s first-class one,
  and then extended it again past the hypothetical: `2012-19`/`2012-019` is a
  pair the column does not actually carry, so the test now also pins the
  **three real** bare-short/padded pairs the column does carry — `96-30` /
  `96-00030`, `97-29` / `97-00029`, `97-63` / `97-00063`, found by padding
  all 1,370 admitted bare-short values to every width from two to six digits
  and looking each candidate up — plus one of the 967 bare-short /
  letter-opening same-suffix pairs (`00-1` / `C0-1`), asserting distinct
  minted IRIs in every case. Re-pinned the census test
  (`test_the_document_number_column_is_accounted_for_exactly`): two separate
  short-tail buckets rather than one aggregate (1,370 and 286, each with its
  own tail-length histogram — 112/1,258 and 27/259 — so a widening that
  moved only one stratum cannot leave the totals intact), the exact
  seven-class partition of the remaining 360, and a corpus-wide mint-safety
  assertion that all 1,003,873 admitted values carry **distinct** IRIs. That
  last one is the regression test the floor-lowering most needed and did not
  have: it costs one `set()` over a column the test already walks.

## 6. Census, before and after

**Before (REF-052/REF-054, pinned):**

| bucket | count |
|---|---|
| first-class | 480,566 |
| bare-legacy | 394,128 |
| letter-opening | 127,523 |
| refused | 2,016 |
| **total** | **1,004,233** |
| partner hatch (bare-legacy + letter-opening) | 521,651 |

**After (REF-056, this cycle):**

| bucket | count |
|---|---|
| first-class | 480,566 (unchanged) |
| bare-legacy | 394,128 (unchanged — new sibling production, not a rewrite) |
| letter-opening | 127,523 (unchanged) |
| **short-tail bare-legacy (new)** | **1,370** — 112 one-digit tails, 1,258 two-digit |
| **short-tail modern (new)** | **286** — 27 one-digit tails, 259 two-digit |
| refused | 360 = 224 `-2`-suffix + 99 short-tail corrections + 27 colophon-fused + 4 extra-hyphen + 4 trailing-letter + 1 `94-S16142` + 1 `granule293` |
| **total** | **1,004,233** (480,566 + 394,128 + 127,523 + 1,370 + 286 + 360) |
| partner hatch (bare-legacy + letter-opening + both short-tail buckets) | 523,307 |
| distinct IRIs across all 1,003,873 admitted values | 1,003,873 |

The two short-tail populations are counted as **separate buckets**, not one
`short-tail` line of 1,656. An aggregate hides which of the two moved: a
change that took values from one production to the other would leave the
total standing. The four tail-length strata are pinned for the same reason —
they are what the sample in §3 was stratified on.

Arithmetic: 1,370 + 286 = 1,656; 224 + 99 + 27 + 4 + 4 + 1 + 1 = 360;
2,016 − 1,656 = 360; 521,651 + 1,656 = 523,307;
480,566 + 394,128 + 127,523 + 1,370 + 286 + 360 = 1,004,233. Every equality
here, every stratum, every one of the seven refusal classes, and the
no-duplicate-IRI property are asserted directly in the re-pinned
`test_the_document_number_column_is_accounted_for_exactly`.

## 7. Proposed decision-record text (docs/decisions.md, REF-052's shape)

*The REF-056 number below is this lane's proposal only. Another lane in the
same cycle proposed the same number; the integrator assigns the final one.
Nothing here should be renumbered locally.*

> ### REF-056: the FR short-tail widening cycle
>
> **Context.** REF-052/REF-054 licensed the bare-legacy shape and four
> letter-opening families for the `document_number` column, and named two
> further populations as deferred refusals in the same breath: 1,370
> bare-legacy-shaped values with a one- or two-digit tail, and 286
> modern-shaped values with a one- or two-digit tail — together 82% of what
> REF-052/054 left in `refused`.
>
> **Decision.** Both populations are column-licensed, the same way REF-052
> licensed the letter-opening family: two new productions,
> `_FR_BARE_LEGACY_SHORT_TAIL` (`\d{2}-\d{1,2}`) and `_FR_MODERN_SHORT_TAIL`
> (`\d{4}-\d{1,2}`), checked only under `column_licensed=True`, disjoint from
> every existing production by construction. rulespec's own mintable space
> (`FEDERAL_REGISTER_DOCUMENT_NUMBER`) is untouched — the modern-shaped
> population mints through `rkaf:partner-defined`, not `rkaf:us-frdoc`; that
> is a separate, unmade ruling with its own budget.
>
> **Evidence.** 24 specimens (14 bare-legacy, 10 modern), stratified by tail
> length and covering both a year-boundary sub-cluster (`93-54`, filed under
> the outgoing year's token) and the modern population's sole non-2010–2012
> outlier (`2013-58`, filed two days into a new year), each read against the
> publisher's own PDF or full-text extraction end to end, as pixels and as
> extracted text. All 24 carry an ordinary printed colophon; none is damage.
> Two of them share a page with an ordinary 3+-digit-tail document — `2010-1`
> beside `2010-117` on 75 FR 1009, `07-99` beside `07-100` on 72 FR 1551 —
> which is the comparison that shows the short tail is the low end of one
> numbering series rather than a different kind of string. Five further raw
> sources cover the refusal side of the partition below.
> research/evidence/fr-short-tails-2026-08-31/.
>
> **What the year-boundary specimens do NOT establish.** `93-54` and
> `2013-58` show only that the year token is independent of both dates the
> page prints: 78 FR 907–908, one issue, carries a 2012-token document filed
> 1-4-13 and a 2013-token document filed 1-2-13. What determines the token is
> not established — no retained source records a submission timestamp — and
> this decision does not need it.
>
> **Measured effect.** The census's `refused` bucket falls from 2,016 to 360
> (0.2% to 0.036% of the column); two new buckets appear, 1,370 and 286;
> `first-class`, `bare-legacy` and `letter-opening` are unmoved by one value.
> The partner hatch grows from 521,651 to 523,307. All 1,003,873 admitted
> values still carry distinct IRIs — the property a floor-lowering most
> threatens, now asserted over the whole column.
>
> **What stays refused, re-measured.** The remaining 360 partition into seven
> classes: 224 `-2`-suffix collisions, 99 short-tail corrections, 27
> colophon-fused values, 4 extra-hyphen spellings, 4 trailing-letter values,
> `94-S16142`, and `granule293`. That corrects the four-line summary this
> census carried since REF-052 — only 224 of the "228" carry a `-2` suffix,
> and the "32 colophon-fused" was a catch-all holding 27 fused values plus
> five that are not fused at all. Two of the seven classes are named here for
> the first time as **real but unread**: the publisher prints `C0-6263A`,
> `C9-20022A`, `94-2050F` and `2014-04654s` with a trailing letter, and
> `94-94-30552`, `95-26-82`, `95-95-22339` and `95-95-744` with an extra
> hyphenated segment, each in an ordinary colophon beside a properly formed
> control on the same page. Neither is ruled on here; both are recorded with
> a count, the posture REF-052 took toward the 1,370 this decision licenses.
> REF-054 already ruled on the corrections and the fused population, and this
> decision does not reopen either.

## 8. Expected receipt delta

This lane touches only `src/refspec/registry/identifier_shapes.py` (adding
two new private regex constants and two `if` branches, plus two comment-only
corrections — which move the module's content hash exactly as a code edit
would, and are already inside the single expected delta below) and the two
test files. The Unified Agenda parquet build
(`refspec.registry.unified_agenda_parquet`) was **not** run — per the
integrator's sequencing, only the `identifier_shapes.py` module hash in the
next rebuild's receipt is expected to change. Column licensing for the
Federal Register `document_number` corpus is a test-side measurement (the
census test reads the pinned parquet directly); it is not an input to the
Unified Agenda parquet build, so no column-licensing behavior changes in
that build's own output.

## 9. Test and lint results

```
.venv/bin/python -m pytest tests/test_identifier_shapes.py tests/test_iri_minting.py -q
821 passed in 31.59s
```

The slow census test alone — now also partitioning the 360 into seven
classes and proving 1,003,873 distinct IRIs, at no measurable extra cost
because it walks the column once either way:

```
.venv/bin/python -m pytest tests/test_iri_minting.py::test_the_document_number_column_is_accounted_for_exactly -q
1 passed in 8.55s
```

```
.venv/bin/ruff check src/refspec/registry/identifier_shapes.py tests/test_identifier_shapes.py tests/test_iri_minting.py research/evidence/fr-short-tails-2026-08-31/scratch/classify_refused.py
All checks passed!
```

The evidence replay, from the pinned parquet:

```
.venv/bin/python research/evidence/fr-short-tails-2026-08-31/scratch/classify_refused.py
distinct document_number values: 1,004,233
refused BEFORE REF-056 (frozen oracle): 2,016
  bare-legacy short tail: 1,370  by tail length {1: 112, 2: 1258}
  modern short tail:      286  by tail length {1: 27, 2: 259}
  still refused after REF-056: 360

  the 360, partitioned:
      224  collision -2 suffix           e.g. 94-10196-2, 94-10241-2, 94-10242-2
       99  short-tail correction         e.g. C1-2010-12, C1-2010-1863, C1-2010-2487
       27  colophon-fused                e.g. 00-23477-Filed, 00-2999Doc, 03-26993Filed
        4  extra-hyphen                  e.g. 94-94-30552, 95-26-82, 95-95-22339
        4  trailing letter               e.g. 2014-04654s, 94-2050F, C0-6263A
        1  not the publisher's number    e.g. 94-S16142
        1  granule293                    e.g. granule293
    (-2 values whose un-suffixed twin is absent from the column: 0)

  live minter refuses: 360
  admitted: 1,003,873  distinct IRIs: 1,003,873

all assertions held.
```

### Mutation check on the new disjointness test

The disjointness test is only worth its lines if it fails when disjointness
fails. Broadening `_FR_BARE_LEGACY_SHORT_TAIL` from `\d{2}-\d{1,2}` to
`\d{2,4}-\d{1,2}` — the smallest edit that makes the two new productions
overlap — and re-running it:

```
FAILED tests/test_identifier_shapes.py::test_no_federal_register_production_claims_another_ones_specimen
AssertionError: 2010-1
assert {'bare-legacy...n-short-tail'} == {'modern-short-tail'}
  Extra items in the left set:
  'bare-legacy-short-tail'
```

Reverted; the suite is green above with the production as written.
