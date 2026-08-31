# eCFR part authority notes, generation 2 — 2026-08-24

**8,240 notes over 9,666 parts in all 49 non-reserved CFR titles**, taken from
the full title XML rather than from 299 hand-picked per-part requests. Generation
1 (`research/evidence/silent-misreads-2026-08-22/ecfr-authority-notes.jsonl`,
287 notes, 2026-08-20) is untouched and still the oracle's pin; this directory
is the candidate that replaces it, and **the switch is a separate unit**.

Every one of generation 1's 287 notes is here, and **278 of them are
byte-identical**. The nine that are not differ in a single character reference
apiece and in nothing else. **No note's words changed** between the two dates.

---

## What was fetched, and from where

Two endpoints, both public and keyless. No API key of any kind was used or
required.

```
https://www.ecfr.gov/api/versioner/v1/titles.json
https://www.ecfr.gov/api/versioner/v1/full/{issue_date}/title-{N}.xml
```

`titles.json` was saved verbatim
(`sha256:9a717a7eaae79e76e2b9a09b87e50579a5950125270522ebbccf499e43d64f8c`,
8,033 bytes, `meta.date` **2026-08-20**, `import_in_progress` false). It names
each title's **own latest issue date**, and that date — not today's — is the one
in each request, so every document is the edition the publisher currently
serves. The dates therefore range from **2024-05-17** (title 3, unamended since
2015) to **2026-08-20**.

Title 35 is reserved: `latest_issue_date` is null and no document exists. That
is the only title 1–50 not fetched, and it is a fact about the CFR rather than a
hole in this fetch.

Fetching was sequential, one title at a time, two seconds between titles, under
the User-Agent
`RefSpec-research/1.0 (Atlas regulatory-vocabulary research; contact michael.f.deeb@gmail.com)`,
with up to three attempts per title and resume-on-retry. **No retry was needed
and no request returned anything but HTTP 200.** 810,674,584 bytes arrived in
one pass.

The raw XML is **not** in this directory — it is 810 MB, and it lives untracked
at `output/ecfr-title-xml-2026-08-24/`. `manifest.json` here is the copy of
record: url, issue date, byte count, sha256, HTTP status, attempts and fetch
timestamp for all 50 titles. Every note row also carries the digest of the
document it was cut from, so any single note is checkable against a re-fetch
without re-reading the manifest.

### Holes

**None.** 49 of 49 non-reserved titles came down complete on the first attempt.
Completeness is not assumed: each document was checked for its closing `</ECFR>`
before its digest was taken, and the part count of five titles was cross-checked
against an independent whole-file regex (titles 1, 26, 40, 45, 48 — exact
agreement, 36/89/379/376/973 parts).

---

## What was extracted

`scripts/extract_notes.py`, standalone, reproducing `notes.jsonl` from the raw
XML in about 1.5 seconds. Its own docstring carries the XML structure; the short
version:

A part is `<DIV5 TYPE="PART">`. Its authority note is an `<AUTH>` element and
its source note a `<SOURCE>` element, written under the part's `<HEAD>` and
**before the part's first subdivision**. An `<AUTH>` also occurs under
`<DIV6 TYPE="SUBPART">` and `<DIV7 TYPE="SUBJGRP">`, where it states that
subdivision's authority alone — so the rule is positional, not a search.

**80 parts state no authority at part level but do state one under their first
subdivision.** 20 CFR 404 and 416, 5 CFR 550 among them — three of the most-cited
parts in the corpus. Generation 1, reading a per-part response top-down, took
that first `<AUTH>` and stored it as the part's note. Generation 2 does the same
thing and says so out loud instead of blurring it: `authority_level` is `"part"`
(8,160 rows) or `"subdivision"` (80 rows), `authority_scope` names the
subdivision, and a subdivision-sourced row carries
`subdivision_authority_notes` — every subdivision note in that part, in document
order, verbatim. Nothing is concatenated and nothing is invented.

**1,426 parts state no authority anywhere.** They get no row. Most are
`[RESERVED]` placeholders and reserved blocks; they are counted in
`extraction-census.json` and their published heads are in `parts-seen.json`.

Two encoding decisions, both made to match generation 1:

* **The label stays on.** `authority_note` begins `"Authority: "`, because the
  `<HED>` is part of the element and `cfr_authority_notes.note_body` strips it
  itself.
* **Character references are left as the document writes them.** Generation 1's
  per-part responses escaped a section sign as `&#xA7;` and an em dash as
  `&#x2014;`; the full-title documents write both as literal UTF-8. Neither side
  is re-encoded here. `note_body`'s `html.unescape` makes the two read
  identically — which is exactly what the comparison below measures.

Markup inside a note becomes a single space and whitespace runs collapse to one,
so `<PSPACE>620 <I>et seq.</I></PSPACE>` reads `620 et seq.` and a
multi-paragraph `<AUTH>` reads as one line.

### Schema: a drop-in for the reader

`notes.jsonl` carries **every field
`refspec.registry.cfr_authority_notes.CfrAuthorityNotes.from_file` subscripts**,
with the type it coerces, on all 8,240 rows — checked, zero faults, zero
duplicate join keys:

`cfr_title`, `cfr_part`, `authority_note`, `source_note`, `api_url`, `fetched`,
`raw_sha256`, `raw_bytes`, `raw_truncated_at_128k`.

`raw_sha256`/`raw_bytes` are the **title** document the row was cut from;
`raw_truncated_at_128k` is `false` on every row, because nothing was truncated.
`fetched` is `"2026-08-24"` on every row — the day the corpus was taken, the
same fact generation 1's `fetched` carried.

Provenance rides in the same file rather than a parallel one, because the reader
ignores unknown keys: `title_issue_date` (the publisher's date, which is **not**
the fetch date and varies by title), `title_xml_sha256`, `title_xml_bytes`,
`part_api_url`, `part_head`, `authority_level`, `authority_scope`,
`subdivision_auth_count`, `subdivision_authority_notes`.

### And the reader actually reads it

`scripts/dropin_check.py` loads `CfrAuthorityNotes` **unmodified except for its
three pin constants** — digest, byte length and record count, the only things
that can still say 287 — points it at `notes.jsonl`, and asks it the specimens
`tests/test_cfr_authority_notes.py` asks. It touches no file on disk; the
repoint is unit 2's edit, and this is the evidence for it.

All 8,240 records load, 49 distinct titles, **36,325 citations** read out of the
notes by the grammar. Every behavioural specimen in the suite gives the verdict
it gives today:

| question | verdict |
| --- | --- |
| 21 CFR 310's note is the pinned string | true |
| 21 U.S.C. 361 / 321p against 21 CFR 310 | present / near-miss |
| 49 U.S.C. 60101 / 60102 / 60137 against 49 CFR 192 | present / near-miss / absent |
| 17 U.S.C. 12a against 17 CFR 1 | near-miss |
| 42 U.S.C. 6295 against 10 CFR 430 (a note range) | present |
| 16 U.S.C. 1531 against 50 CFR 17 (the elided title) | present |
| 42 U.S.C. 405 against 20 CFR 404 (a Subpart-A note) | present |
| **40 U.S.C. 550 against 45 CFR 12a** | **present** |

The last row is the campaign's own opening specimen. Generation 1 could not hold
45 CFR 12a — a tiny part the top-300 set-cover never reached — and pinned that
gap in a test so it stayed a known hole. Generation 2 holds it, and its whole
note is *"42 U.S.C. 11411; 40 U.S.C. 550."*

---

## (a) Generation 1, part by part

All 287 looked up; note text compared byte for byte, then again after
`html.unescape` on both sides.

| | |
| --- | ---: |
| generation-1 records | 287 |
| **byte-identical** | **278** |
| character-reference spelling only | 9 |
| the publisher's words drifted | **0** |
| missing from generation 2 | **0** |

The nine, verbatim in `validation.json`. Each differs in exactly one character
reference and nothing else:

| part | class | gen-1 date | gen-2 issue date | the difference |
| --- | --- | --- | --- | --- |
| 5 CFR 330 | entity | 2026-08-20 | 2026-08-14 | `&#xA7;` → `§` |
| 12 CFR 324 | entity | 2026-08-20 | 2026-08-19 | `&#xA7;` → `§` |
| 17 CFR 240 | entity | 2026-08-20 | 2026-08-17 | `&#xA7;&#xA7;` → `§§` |
| 19 CFR 4 | entity | 2026-08-20 | 2026-08-12 | `&#xA7;` → `§` |
| 19 CFR 10 | entity | 2026-08-20 | 2026-08-12 | `&#xA7;` → `§` |
| 26 CFR 1 | entity | 2026-08-20 | 2026-08-10 | `&#x2014;` → `—` |
| 26 CFR 301 | entity | 2026-08-20 | 2026-08-10 | `&#xA7;` → `§` |
| 28 CFR 541 | entity | 2026-08-20 | 2026-08-20 | `&#x2014;` → `—` |
| 50 CFR 223 | entity | 2026-08-20 | 2026-08-20 | `&#xA7;` → `§` |

**This is a difference between two views of the same publisher's document, not
between two publishers' words.** Two of the nine (28 CFR 541, 50 CFR 223) were
fetched at the *same* issue date on both sides and still differ, which settles
that the cause is the API view rather than the date. The `?part=` view escapes
non-ASCII as numeric character references; the full-title view emits UTF-8.
Under `note_body` all nine are identical, and the module docstring's count of
"19 and 4 occurrences over 9 of the 287 notes" describes generation 1's
encoding, not generation 2's.

**Extractor divergence: none.** Everything that differed was traced to the
source encoding, and the two cases that first looked like divergence were not:
20 CFR 404/416 and 5 CFR 550 (authority stated under Subpart A, handled above)
and 7 CFR 457 / 50 CFR 100 (parts genuinely gone, confirmed below).

---

## (b) The two notes that misprint their own title digits

`research/evidence/false-presences-2026-08-23.md` finding 2 names them. **Both
still misprint at the new date.**

**36 CFR 251**, issue date 2026-08-12 — byte-identical to the note generation 1
read on 2026-08-20:

> Authority: 16 U.S.C. 472, 479b, 551, 1134, 3210, 6201-13; **30 U.S.C. 1740,
> 1761-1771.**

The false-presences review checked 30 U.S.C. 1761–1771 against the section
oracle and found no such sections; 43 U.S.C. 1740, 1761–1771 are FLPMA's
right-of-way sections, which is what the Forest Service's own rules cite.

**28 CFR 541**, issue date 2026-08-20 — identical to generation 1's under
`note_body`, and one of the nine whose em dash is spelled `—` here and
`&#x2014;` there:

> Authority: **15 U.S.C. 301;** 18 U.S.C. 3621, 3622, 3624, 4001, 4042, 4081,
> 4082 (Repealed in part as to offenses committed on or after November 1, 1987),
> 4161—4166 …

5 U.S.C. 301 is the departmental-regulations boilerplate every BOP rule opens
with.

Generation 2 changes neither. The false-presences review's conclusion stands:
**the notes are the record, not an infallible one**, and a shadow verdict needs
the impossible-referent oracle beside it.

---

## (c) Coverage against the corpus

The Unified Agenda's CFR references
(`output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_cfr_references.parquet`,
444,848 rows) name **8,655 distinct `(cfr_title, cfr_part)` pairs as spelled**,
which collapse to **8,652** on the reader's own join key (`normalize_part`:
leading zeros stripped, case folded). The three that collapse are pure case
variants — `8 CFR 274A`/`274a`, `15 CFR 4A`/`4a`, `32 CFR 806B`/`806b`.

| | pairs | corpus rows |
| --- | ---: | ---: |
| named by the corpus | 8,652 | 420,622 |
| **generation 2 holds a note** | **5,793 (67.0%)** | **384,451 (91.4%)** |
| generation 1 held a note | 287 (3.3%) | — |
| missed | 2,859 | 36,171 |

The row figure is the one the oracle spends: 33% of the pairs cost 8.6% of the
rows, because a missed part is usually an old one. **72.0% of the rows on missed
pairs come from Agenda publications before 2010, against 54.7% of the rows on
covered pairs** (58.3% versus 39.0% before 2005). Misses skew old; they are not
confined to the old.

### Why the 2,859 misses miss

| count | reason |
| ---: | --- |
| 1,926 | the part does not exist in this title at the current date |
| 645 | removed — the number falls inside a reserved block the title publishes (e.g. 7 CFR `PARTS 413-459[RESERVED]`) |
| 228 | the part is published as `[RESERVED]`, so it states no authority |
| 22 | title 35 is reserved: no document is published |
| 21 | the part exists and publishes no authority note anywhere in it |
| 11 | renumbered — title 41 numbers its parts *chapter-part*, and publishes `101-1`, `101-11`, … (all 11 are title 41) |
| 6 | outside titles 1–50 (the corpus names titles 0, 59, 60, 234, 420, 460) |

The corpus runs from 1995 and the notes are today's, so most of this is time
rather than gap. 31 CFR 103 (910 corpus rows) is the clearest case and the one
the spot check confirms: the versioner knows no version of it, and title 31
today publishes `1010`, `1020`, `1021`, `1022` … in its place. 12 CFR 567 (143
rows) and the 21 CFR OTC monograph parts 334, 337, 339, 342 and 345 (1,234 rows
each) are likewise absent from their titles at the current date. A note this
cache cannot hold is a silence about an era, not a claim that the citing rule
was wrong.

### Five misses checked against the live versioner

Chosen by corpus weight, one per (title, reason), asked of
`https://www.ecfr.gov/api/versioner/v1/versions/title-{N}.json?part={P}` — same
host, still keyless. **All five agree with the classification above.**

| miss | corpus rows | our reason | the versioner's answer |
| --- | ---: | --- | --- |
| 21 CFR 334 | 1,234 | does not exist at the current date | 0 version records — no such part |
| 31 CFR 103 | 910 | does not exist at the current date | 0 version records — no such part |
| 41 CFR 102 | 664 | published as `PART 102—GENERAL [RESERVED]` | 0 version records |
| 41 CFR 101 | 623 | renumbered — the title publishes `101-N` | 0 version records for a bare `101` |
| 20 CFR 405 | 499 | published as `PART 405 [RESERVED]` | 104 version records, last issue **2017-01-18**, `removed: true` |

The last one is the informative one: 20 CFR 405 *was* a part, was removed in
January 2017, and is now a reservation — so the 499 corpus rows citing it are
citing a real part of its era, and the silence against it is honest.

**Two bugs in the miss classification were found by these spot checks and
fixed.** `41 CFR 101` was first reported as falling inside a reserved range
`50-201`; that hyphen is title 41's *chapter-part* numbering, not a range, and
reading it as one swallowed every two- and three-digit part in the title. The
fix is to require `[RESERVED]` in the published head before treating a
hyphenated part number as a block. `41 CFR 102` and `20 CFR 405` were first
reported as "exists but publishes no note", when the head says `[RESERVED]`.

---

## (d) Per title

`parts` counts `<DIV5 TYPE="PART">` elements, reserved placeholders included.
Full per-title detail, including duplicate-part checks (there are none), is in
`extraction-census.json`.

| title | issue date | bytes | sha256 (first 16) | parts | notes | part / subdiv | no note |
| ---: | --- | ---: | --- | ---: | ---: | --- | ---: |
| 1 | 2026-08-10 | 477,387 | `fe18aad18e3b6e8f` | 36 | 28 | 27 / 1 | 8 |
| 2 | 2026-08-18 | 2,835,348 | `88efc21e190bff04` | 181 | 106 | 106 / 0 | 75 |
| 3 | 2024-05-17 | 31,476 | `784a364ed96848dd` | 4 | 3 | 3 / 0 | 1 |
| 4 | 2024-07-18 | 409,058 | `693843eefde70392` | 21 | 18 | 18 / 0 | 3 |
| 5 | 2026-08-14 | 11,588,530 | `c80f950b58579980` | 420 | 283 | 273 / 10 | 137 |
| 6 | 2026-08-12 | 1,980,347 | `b29f3535af0edc51` | 28 | 24 | 24 / 0 | 4 |
| 7 | 2026-08-19 | 40,639,801 | `fa121dee61938c15` | 548 | 442 | 437 / 5 | 106 |
| 8 | 2026-08-12 | 5,411,821 | `c6915332eafab54c` | 132 | 126 | 126 / 0 | 6 |
| 9 | 2026-08-19 | 7,496,449 | `5248e02afe774d27` | 153 | 144 | 144 / 0 | 9 |
| 10 | 2026-08-17 | 20,679,840 | `8899d728a63dd2c4` | 201 | 175 | 175 / 0 | 26 |
| 11 | 2026-06-08 | 1,660,203 | `81c31209cc454321` | 57 | 53 | 53 / 0 | 4 |
| 12 | 2026-08-19 | 39,190,451 | `0bb24979bddc96cb` | 448 | 389 | 387 / 2 | 59 |
| 13 | 2026-08-11 | 4,016,281 | `eda033b33f1d114a` | 55 | 47 | 47 / 0 | 8 |
| 14 | 2026-08-19 | 15,999,434 | `fbbbb5301cc44152` | 226 | 198 | 193 / 5 | 28 |
| 15 | 2026-08-18 | 13,326,825 | `f7cfb411ed8cd090` | 180 | 136 | 136 / 0 | 44 |
| 16 | 2026-08-18 | 6,735,294 | `86217ac9cad88c59` | 229 | 214 | 206 / 8 | 15 |
| 17 | 2026-08-17 | 17,251,585 | `cc97dba6a531344e` | 130 | 118 | 117 / 1 | 12 |
| 18 | 2026-07-27 | 7,149,519 | `d02c6bd96a358bf6` | 137 | 121 | 120 / 1 | 16 |
| 19 | 2026-08-12 | 10,541,308 | `5e33e9206fe5440f` | 83 | 76 | 76 / 0 | 7 |
| 20 | 2026-08-20 | 14,406,263 | `e9a335d3f58b6855` | 177 | 146 | 141 / 5 | 31 |
| 21 | 2026-08-19 | 21,324,371 | `7ae92c67d7db7da7` | 275 | 263 | 262 / 1 | 12 |
| 22 | 2026-08-10 | 6,695,308 | `9e62d0291d249170` | 243 | 208 | 208 / 0 | 35 |
| 23 | 2026-07-13 | 3,222,939 | `473297903694235d` | 75 | 64 | 62 / 2 | 11 |
| 24 | 2026-08-20 | 12,385,380 | `024bed569f1da4f6` | 177 | 151 | 151 / 0 | 26 |
| 25 | 2025-12-01 | 6,010,102 | `63fb85744d8ac42f` | 185 | 152 | 152 / 0 | 33 |
| 26 | 2026-08-10 | 87,237,726 | `2bb604629752d51a` | 89 | 66 | 66 / 0 | 23 |
| 27 | 2026-08-17 | 7,225,981 | `c6041f9cdf04f338` | 48 | 42 | 41 / 1 | 6 |
| 28 | 2026-08-20 | 10,752,368 | `8b9a1456852e1bb2` | 158 | 146 | 145 / 1 | 12 |
| 29 | 2026-08-04 | 28,444,713 | `dffae01d0b7fc8ba` | 328 | 288 | 287 / 1 | 40 |
| 30 | 2026-08-14 | 10,170,208 | `351ff1849f4a2023` | 220 | 206 | 206 / 0 | 14 |
| 31 | 2026-08-14 | 9,938,094 | `a5372204f5914f39` | 211 | 183 | 183 / 0 | 28 |
| 32 | 2026-08-17 | 12,824,062 | `723c57463ed546d0` | 269 | 229 | 227 / 2 | 40 |
| 33 | 2026-08-19 | 11,888,100 | `f1107a804201b447` | 151 | 139 | 137 / 2 | 12 |
| 34 | 2026-07-24 | 9,160,779 | `0bd24078aae00dee` | 141 | 107 | 107 / 0 | 34 |
| 35 | — reserved — | — | — | — | — | — | — |
| 36 | 2026-08-12 | 7,995,754 | `fb9e0294c8c64023` | 191 | 164 | 159 / 5 | 27 |
| 37 | 2026-08-13 | 4,637,489 | `283539cb002ec329` | 73 | 63 | 63 / 0 | 10 |
| 38 | 2026-08-10 | 9,636,232 | `732dda75806f9349` | 59 | 54 | 51 / 3 | 5 |
| 39 | 2026-06-12 | 2,283,916 | `480ba76fec3e04d5` | 103 | 92 | 92 / 0 | 11 |
| 40 | 2026-08-20 | 157,031,367 | `f52bbdb5a097f686` | 379 | 351 | 349 / 2 | 28 |
| 41 | 2026-08-17 | 4,034,733 | `168b082bf28e66ec` | 209 | 171 | 170 / 1 | 38 |
| 42 | 2026-08-13 | 22,692,031 | `8dbd124096165e71` | 161 | 149 | 144 / 5 | 12 |
| 43 | 2026-08-12 | 8,822,150 | `c0deab612deed74f` | 189 | 167 | 157 / 10 | 22 |
| 44 | 2026-06-22 | 2,359,290 | `562e8a042144f1e2` | 97 | 64 | 63 / 1 | 33 |
| 45 | 2026-08-18 | 14,050,776 | `a8795710ed107c33` | 376 | 315 | 315 / 0 | 61 |
| 46 | 2026-07-30 | 15,649,947 | `b20b7c468213be3a` | 242 | 207 | 206 / 1 | 35 |
| 47 | 2026-08-13 | 19,319,326 | `3172d24f91ce8226` | 79 | 67 | 67 / 0 | 12 |
| 48 | 2026-08-07 | 20,185,496 | `94edc125c0259dfc` | 973 | 827 | 824 / 3 | 146 |
| 49 | 2026-08-19 | 33,168,573 | `9d7ad9e60318d955` | 419 | 371 | 370 / 1 | 48 |
| 50 | 2026-08-20 | 29,700,153 | `16927b62b109c5eb` | 100 | 87 | 87 / 0 | 13 |
| **total** | | **810,674,584** | | **9666** | **8240** | **8160 / 80** | **1426** |

---

## The files here

| file | sha256 | bytes |
| --- | --- | ---: |
| `extraction-census.json` | `3cadcb805196c934bfb4aa1a16c9a2ffdf612a68b7053b8ff24f0e878efcfd60` | 13,906 |
| `manifest.json` | `243f1f7c2abe04cc9c032ebc8101e7f0a0130e97a5c3b4d5e13a1352535489b8` | 24,775 |
| `notes.jsonl` | `ec2e57aa15c5284b2073fad53dd27a686110e398f6c6f20f6c54207e4b9386de` | 7,470,473 |
| `parts-seen.json` | `a42b6d4abe11f9e0fec47dabb47bf5cf42721d877caaa649efceac78ab5aa002` | 703,304 |
| `scripts/dropin_check.py` | `409ad3b9f4cc04fcd9260ca44a9f109903e7ff754f3237338d9548015cf63dd1` | 3,725 |
| `scripts/extract_notes.py` | `71db8ca479c3f5425f7b8f50c2e0825a4364d3dc75c3467b0bede333cf1c1eed` | 16,050 |
| `scripts/fetch_titles.py` | `8d5f41540ed4236953210bcb281f1b48385319b97a0e9d201de38eabbb5aad22` | 7,136 |
| `scripts/validate.py` | `fbab657055054085938a25d636a170c8ce91a1f2076eb082135c9caadfa4ba41` | 15,963 |
| `validation.json` | `090d3c58542b97028781efe0655513da6345027f3273216c5ba1e1e99ca730dd` | 1,084,121 |

* `notes.jsonl` — the deliverable. 8,240 rows, sorted by title then part.
* `manifest.json` — every fetch, including the reserved title.
* `extraction-census.json` — parts seen, notes extracted and parts without a
  note, per title.
* `parts-seen.json` — every part number each title publishes and the head it
  publishes it under. This is what tells a coverage miss apart from a
  reservation; it is not needed to read a note.
* `validation.json` — the full output of (a) through (d), with every
  generation-1 difference and every one of the 2,859 misses named.
* `scripts/` — the four steps, runnable in order:

```
python3 scripts/fetch_titles.py  output/ecfr-title-xml-2026-08-24
python3 scripts/extract_notes.py output/ecfr-title-xml-2026-08-24 .
python3 scripts/validate.py      . <repository-root> --probe
python3 scripts/dropin_check.py  <repository-root> notes.jsonl
```

Reproduction is exact only against the pinned digests: the eCFR is a living
document, and a title amended after 2026-08-24 will have a new issue date and a
new digest.

## Reproducing

```
mkdir -p output/ecfr-title-xml-2026-08-24
curl -A 'RefSpec-research/1.0 (…)' -o output/ecfr-title-xml-2026-08-24/titles.json \
  https://www.ecfr.gov/api/versioner/v1/titles.json
python3 research/evidence/ecfr-authority-notes-2026-08-24/scripts/fetch_titles.py \
  output/ecfr-title-xml-2026-08-24
```

---

## For the oracle switch

Not this unit's work, and listed so it is not rediscovered:

* **The pin constants move.** `NOTES_SHA256`, `NOTES_BYTE_LENGTH` and
  `NOTES_EXPECTED_RECORDS` (287 → 8,240); `NOTES_FETCHED` 2026-08-20 →
  2026-08-24; `NOTES_ENDPOINT` loses its `?part=` form and gains a per-title
  date, so it can no longer be one format string with `{title}` and `{part}` —
  the date varies by title. The record's `part_api_url` is the closest analogue.
* **Five pinned test facts change**, all in `tests/test_cfr_authority_notes.py`:
  the 287 count; `record.api_url.startswith(".../full/2026-08-20/")`;
  `sum(raw_truncated_at_128k) == 211` (now 0); `len({title for title, _ in
  coverage}) == 39` (now 49); and
  `test_the_cache_does_not_hold_the_part_that_settled_the_opening_specimen`,
  which pins that **45 CFR 12a is absent** — generation 2 **holds** it, so that
  test's finding is now settled rather than a known hole.
* **The module docstring's entity paragraph** describes generation 1's encoding
  ("19 and 4 occurrences, over 9 of the 287 notes"). Generation 2 has literal
  `§` and `—` instead, and `note_body`'s `html.unescape` becomes a no-op on
  them — still correct, still needed for any note that does carry an entity, but
  the count is wrong for the new file.
* **`authority_level` is the one new judgement call.** 80 rows carry a
  subdivision's note as the part's. Including them is what keeps 20 CFR 404 and
  416 in coverage; a consumer that wants only part-level authority can filter on
  the field, and `subdivision_authority_notes` holds the rest of the part's
  authorities for anyone who wants the union.
* **The file is 7.5 MB**, 26× generation 1. `from_file` reads it whole and
  parses every note through the grammar at construction; that cost is now paid
  8,240 times rather than 287, and the reader is constructed once per build.
