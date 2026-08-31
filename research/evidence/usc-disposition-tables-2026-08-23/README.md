# U.S.C. recodification disposition tables — 2026-08-23

The pinned source, the committed extractor, and the derived table behind
`refspec.registry.usc_disposition_tables`: **"TABLE SHOWING DISPOSITION OF
FORMER SECTIONS OF TITLE 49"**, printed in the front matter of the 1994
edition of positive-law Title 49.

## Why this table exists here

`usc_section_oracle` answers `unknown` with the reason
`title_49_appendix_not_published` for 2,551 rows of the pinned Unified Agenda
build, 2,548 of them for that one reason: **no OLRC annual archive year holds a
`usc49a.htm`**, so the pre-1996 Title 49 Appendix numbering (the Federal
Aviation Act, the Federal Transit Act, the ICC Act as they stood before Pub. L.
103-272) is outside every source that oracle reads. The reviewer's sample of
2026-08-23 (`../sample-review-2026-08-23/review.md` § F) read ten of those rows
against the publisher's own pages and found all ten answered by one closed,
authoritative, public document — this table — with Pub. L. 103-272 § 6(b)
deeming a citation to a former section to refer to its successor.

govinfo has **no appendix volume for any title in 1994**
(`USCODE-1994-title49a`, `-title11a`, `-title28a` all resolve to the error
shell). The mapping is in the *main* volume's front matter instead.

## Source

| what | value |
|---|---|
| URL | `https://www.govinfo.gov/content/pkg/USCODE-1994-title49/pdf/USCODE-1994-title49.pdf` |
| file | `USCODE-1994-title49.pdf` |
| sha256 | `66f004679e27e0d16356e14b79cb3b4f7ebf63d91307435fa8f53c95bcc2848d` |
| bytes | 5,165,242 |
| pages | 902 |
| fetched | 2026-08-23, 08:14 local, `curl -L --http1.1 --retry 3`; HTTP 200, **no redirect** |
| server `Last-Modified` | Fri, 29 Nov 2019 02:42:26 GMT |
| PDF `CreationDate` | 2010-01-06T15:52:15Z (`AFPL Ghostscript 8.14`, from `C:\LRC\WORK\^PDFMAKE\1994\USC49.94`) |

The file is 5 MB, so it is committed here rather than kept under `output/`.
`extract_disposition_table.py` re-checks both the digest and the byte length
before it reads a page, and exits rather than parsing a different PDF.

Two corrections to the review's own description, both harmless and both
recorded because a reader will otherwise think the extraction missed
something:

* The review says the table is on **pp. 6–15**. It is on **pp. 1–12**, in the
  volume's own folios and in PDF page order — the left column of page 1 from
  y=545 down, then both columns of pages 2–11, then the left column of page 12
  down to `2812 → 5714`, immediately above `ENACTING CLAUSES`.
* The review says the table gives `1502 → 40105 (+40101(e))`.
  The table prints `1502(a) → 40105`, `1502(b) → **40101**`, `1502(c), (d) →
  40105`. The pinpoint `(e)` is the reviewer's, read off 49 U.S.C. 40101's
  Historical and Revision Notes; the table itself says `40101`. The derived
  table carries what the table prints.

## The extractor, and why it is not `pdftotext -layout`

`scripts/extract_disposition_table.py`, run with **poppler `pdftotext version
26.06.0`** and **pyarrow 23.0.0**:

```
python3 scripts/extract_disposition_table.py \
    USCODE-1994-title49.pdf \
    usc-1994-title49-disposition.parquet \
    --text usc-1994-title49-disposition.txt
```

It uses `pdftotext -bbox-layout`, not `-layout`, and the difference is not
cosmetic:

* Each page carries **two table blocks side by side**, each of them two
  columns. `-layout` renders a row of the left block and an *unrelated* row of
  the right block on one text line, so no line-oriented rule can attribute a
  value to a former section.
* Inside a block, justified continuation lines put runs of three or more
  spaces inside the *former* field (`1515(e)(2)(B),         and
  Postal`; `303(a)(14) (words         after        2d`), which defeats every
  "split on the widest gap" rule. Two such lines exist, on pages 7 and 8, and
  both would have been split into a bogus (former, value) pair.

`-bbox-layout` gives every line a bounding box, and poppler already segments
each page into the four sub-columns as separate blocks. The column split is
therefore geometric: the midpoint between the `Former Sections` header's right
edge and the `New Sections` header's left edge, which is at exactly the same x
on all twelve pages (x=198.5 left, x=417.5 right). A row is one former-column
line and the new-column line **at the same baseline**; a continuation line is
one with no value at its baseline.

Every structural assumption raises rather than dropping a row: a line
straddling the column split, two values on one baseline, a value that matches
no former line, an entry that does not open with a section number, a former
field whose comma-pieces name no address, an undeclared status.

**The defect that guard was built for.** A first version took the *topmost*
former-column block under the header, on the evidence of page 9 where the
column is one block. Poppler splits a column wherever the print leaves a gap,
and pages 4–11 carry two or three blocks: that version silently lost **464 of
the 909 former sections**, and hid the loss, because the values under the gap
were filtered out by the same y-window and so never went unmatched. The fix
takes every block inside the column geometry — prose that follows the table
(page 12's `ENACTING CLAUSES`) is set to the full width of the half and is
excluded by crossing the column split, not by a guess about its wording — and
the value set is no longer y-filtered, so an orphaned value now raises.

## The derived table

| file | sha256 | bytes | rows |
|---|---|---:|---:|
| `usc-1994-title49-disposition.parquet` | `8403212c0193b3361accf7ff4be238420634beb5aa5740d78b9960fef5b2aedd` | 37,672 | 3,102 |
| `usc-1994-title49-disposition.txt` | `30c7aeaa3693cc343b4b843e201e3ec17a92cd86db837362aeafce95800b87cf` | 61,218 | 1,852 |
| `scripts/extract_disposition_table.py` | `4082ba71c5206b8b95b471d32df816f23141bf145b737098ca62b0ccc5cdb99a` | 27,725 | — |

Both outputs are **byte-identical on a re-run** from the same PDF with the same
poppler and pyarrow (checked 2026-08-23); the row order is print order, so
nothing depends on set iteration.

`usc-1994-title49-disposition.txt` is the 1,852 printed entries in print order,
`page  column  former-field<TAB>new-field`, for reading against the page
images. The parquet is one row per **(former section token × successor)**:

| column | what |
|---|---|
| `former_title` | 49, always — the interface is per-table and this is the Title 49 table |
| `former_section` | one section token: `1432`, `1601a` |
| `former_subsection` | the subsection path as an address: `(b)`, `(a)(2)(A)`, or a span kept whole (`(e)(5)-(7)(A)`); null when the entry names the whole section |
| `former_note` | `note` / `notes` when the entry disposes of the section's notes, else null |
| `new_title` | 49, or the title a `T. NN §` value names; null when there is no successor |
| `new_section` | the successor section token; null when there is no successor |
| `new_subsection` | set only where the printed value is a pinpoint (`308(e)`) |
| `status` | `restated`, `restated-as-note`, `repealed`, `eliminated`, `see-reference` |
| `former_text` | **the printed former field, verbatim**, including all the prose the parse drops |
| `new_text` | **the printed value, verbatim** |
| `page`, `column` | where in the PDF the entry is printed |

Nothing the print said is lost: the prose that says *which words* of a former
section moved (`(1st sentence)`, `(related to standards)`, `(less (c), (g), and
(h))`) is not parsed into a field, and stays whole in `former_text`.

### Counts

| measure | value |
|---|---:|
| printed entries | 1,852 |
| emitted rows | 3,102 |
| distinct former sections | 909 |
| distinct former `(section, subsection)` | 2,428 |
| distinct successors `(title, section)` | 804 |
| former sections with more than one row | 248 |
| rows `restated` / `repealed` / `eliminated` / `see-reference` / `restated-as-note` | 2,560 / 468 / 47 / 24 / 3 |
| former sections with **only** repealed rows | 309 |
| former sections with both a successor and a repealed part | 70 |
| successors outside title 49 | 50 (36), 43 (9), 19 (5), 15 (4), 39 (3), 2/18/28/31/40/42 (1 each) |

### Two independent checks on the extraction

**The volume's own Historical and Revision Notes.** Every section of the new
title carries a note naming its source as `49 App.:NNNN`. Those notes are a
second, independent rendering of the same mapping, printed 700 pages away from
the table. The volume names **419** distinct `49 App.:` section tokens, and
**all 419 are in the derived table** (`toks - table == set()`). The reverse
does not hold and should not: 490 of the table's 909 sections are never named
in a revision note, because they were either repealed with no successor or
restated by the *1978* codification, whose notes are in that volume.

**Page 3 left, line by line.** A naive `-layout` half-page render of that block
yields 75 value-bearing lines at the column's left edge; the extractor yields
74 entries. The single difference is the folio line `Page 3   TITLE
49—TRANSPORTATION`, and every one of the eleven wrapped entries the naive
render truncates (`22(1) (1st sentence words be-`, four of them identical after
truncation) is folded whole by the extractor.

### The ten rows of review § F, as the table answers them

| # | filer's text | table's former field | table's value | verdict |
|---|---|---|---|---|
| 1 | `49 USC 1432` | `1432(b), (c)` (+ `1432(a)` ×2, `1432(d)`) | `44706` (+ `44702`, `44701`, `44914`) | exists-as-recodified, 4 candidates |
| 2 | `49 USC 1652(e)` | `1652(e) (related to FAA)` (+ 7 more on (e)) | `106` (+ `103`, `104`, `108`) | exists-as-recodified |
| 3 | `49 USC 1421 to 1431` | 1421…1431, 30 entries | 44701–44716, 44722, 1153 | exists-as-recodified, per section |
| 4 | `49 USC 1423 to 1426` | 1423…1426, 11 entries | 44702, 44704, 44705, 44708, 44713 | exists-as-recodified |
| 5 | `49 USC 1502` | `1502(a)` / `(b)` / `(c), (d)` | `40105` / `40101` / `40105` | exists-as-recodified |
| 6 | `49 USC 1424` | `1424(b)` (+ `1424(a)` ×2) | `44705` (+ `44702`, `44701`) | exists-as-recodified |
| 7 | `49 USC 1421` | `1421(a), (b)` … `1421 notes` | `44701` … `44716, 44717, 44722` | exists-as-recodified |
| 8 | `49 USC 1374(c)` | `1374(c)` | `41705` | exists-as-recodified, one successor |
| 9 | `49 USC 1604(h)` | `1604, 1604a` | `Rep.` | **repealed-no-successor** |
| 10 | `49 USC 1510` | `1510` | `40120` | exists-as-recodified, one successor |

Row 9 is the verdict the review asked for: the table names the section and
gives it no successor, which is a different fact from "the oracle cannot see
this archive".

## What is NOT here

Only Title 49. The same shape of table exists for every other positive-law
recodification — 31 (1982), 41 (2011), 46 (1983-2006), 51 (2010), 54 (2014), 34
(2017), 10 ch. 1201 — and § E of the same review names two of them as live
misses (`31 USC 483a` → 9701, `10 U.S.C. 593` → 12203). The reader module is
built as a registry of pinned tables so that adding one is adding a directory
and a digest; nothing about Title 49 is special-cased in its interface.
