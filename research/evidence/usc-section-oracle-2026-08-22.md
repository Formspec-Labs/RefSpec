# The U.S.C. section-existence oracle, and what the parsed corpus looks like against it

**2026-08-22.** One leg of the silent-misreads campaign
(`silent-misreads-2026-08-22.md`). Question: of the U.S.C. citations the
grammar parses *cleanly*, how many point at a section that does not exist?
Prior work counted loud refusals; nobody had an oracle to count the silent
ones. This leg built one, ran the corpus against it, triaged the misses, and
ran the near-miss test. Raw material, oracles, scripts and per-pair verdicts
are in `usc-section-oracle-2026-08-22/` beside this file.

Nothing in this leg wrote to `src/`, `tests/` or `output/`.

---

## 1. The oracle

Two primary sources, both from the Office of the Law Revision Counsel,
downloaded 2026-08-22. Digests, byte lengths and the reproduction check are
in `usc-section-oracle-2026-08-22/README.md`.

**1a. Current release point, USLM XML.**
`https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_uscAll@119-102.zip`
(108,610,077 bytes; 58 title files dated 2026-07-23). Section identity taken
from `<section … identifier="/us/usc/tNN/sXXX">`. Yields **59,362 distinct
(title, section)** — 50,957 live plus **8,405 stubs** carrying
`status="repealed|omitted|transferred|renumbered|vacant|reserved"` — across 53
titles, plus **1,751 range stubs** (`identifier="/us/usc/t42/s6...15a"`,
`"…/s3 …/s4"`). From the same file: **160,209 (title, section, subsection)**
and **2,905 (title, chapter)**.

**1b. Annual historical archives, XHTML, every year 1994–2024.**
`https://uscode.house.gov/download/annualhistoricalarchives/XHTML/<YEAR>.zip`
(31 zips, ~2.2 GB). Section identity from the
`<!-- itempath:/420/…/Sec. 7401 -->` comments; `Secs. 6 to 15a` blocks kept
as ranges rather than expanded, so the oracle never claims a number that was
never printed. Yields **66,007 distinct non-appendix (title, section)**,
**1,015 appendix (title, section)** (5/10/11/18/26/28/38/40/46/50 App), and
49,823 year-scoped range stubs.

Union used as the existence test: **66,780 distinct (title, section)**,
spanning every agenda edition in the corpus (1995-10 … 2025-10).

**Verification run, and one thing it caught.** `15 U.S.C. 77aaaa` ✓,
`42 U.S.C. 7401` ✓, `10 U.S.C. 128` ✓, `54 U.S.C. 100101` ✓, title 53 → 0 rows ✓.
But `42 U.S.C. 1395w-4` and `300gg-11` came back **missing** on the first
extraction: OLRC identifiers use U+2013 EN DASH (`/us/usc/t42/s1395w–4`)
where the corpus uses ASCII hyphen. Applying the grammar's own `_DASHES`
table to the oracle fixed it — without that, the entire Medicare/ACA/SDWA
compound-name family would have been reported as nonexistent. Post-fix all of
`1395w-4`, `300gg-11`, `300j-9`, `21 U.S.C. 360bbb-3`, `42 U.S.C. 7671q`
resolve. Appendix controls: 50 App 2401/2410 (1994–2014), 5 App 3/8g
(1994–2020), 46 App 466c (1994–2005), 46 App 688 (1994–2005).

**Declared gap.** No `usc49a.htm` exists in *any* OLRC annual archive year.
The pre-1996 Title 49 Appendix (old Federal Aviation Act / ICC Act numbering)
is not covered by any source obtained; govinfo's `USCODE-1994-title49a`
returns an error page and its API is rate-limited on `DEMO_KEY`. That gap is
carried as its own class below, not counted as misreads.

**The two thin pinned indexes are not an oracle.** Confirmed before starting:
`output/usc-act-index-2026-08-02/usc-act-sections.parquet` is 10,976 rows /
7,522 distinct (title, section) / 24 acts; `usc-source-credit-index-2026-08-02`
is 3,721 rows. Neither can answer "does 21 U.S.C. 321p exist".

## 2. The artifact changed under the measurement

`unified_agenda_legal_authorities.parquet` was **rebuilt on disk mid-run**: at
17:10 it was 4,944,231 bytes / 798,114 rows; at 17:44 it was 4,929,519 bytes /
797,170 rows (HEAD of the checkout had moved to `cc9c5cbd` by 17:59; the
build's own `receipt.json` does not name the producing commit). The 17:44
build was snapshotted — sha256
`c5c4bd1f8b70fd52491f8b22e7bc72c75287cbbf3638692210fd1691731c7424`,
797,170 rows, 42,642 distinct texts, 46,547 RINs — and is preserved in the
artifact directory as `agenda-legal-authorities-as-measured-797170.parquet`.
**Every number below is that build.** The campaign report's own numbers are
the 798,114-row build (`silent-misreads-2026-08-22/agenda-legal-authorities-as-measured.parquet`);
the two are not directly comparable, and §9 records what the rebuild removed.

## 3. Headline

Of **685,431 rows / 30,858 distinct texts** carrying a parsed U.S.C.
title+section (11,124 distinct (title, section, appendix) pairs):

**1,728 pairs — 2,372 distinct texts (7.7%), 18,117 rows (2.6%), 2,622 RINs —
name a section that has never existed in any edition of the U.S. Code
1994–2026.**

**13,612 of those rows (75%), across 1,508 distinct texts, carry
`parse_status = 'ok'`.** The parse declared itself clean and the citation
points at nothing. A further 20 rows / 4 texts are `parse_status =
'corroborated'` — the grammar's own `rin-history-section-list` rule blessed a
citation to nowhere (`1833(i)(2)(D)(iii)` → 42 U.S.C. 1833; `4519g` → 12
U.S.C. 4519g; `3568 and 3569` → 18 U.S.C. 3568/3569).

After triage the 18,117 rows split three ways:

| group | pairs | texts | rows | of which `ok` | RINs |
|---|---:|---:|---:|---:|---:|
| **A — derivable parser defect** | 373 | 633 | **7,200** | 5,918 | 819 |
| **B — real when written, outside the oracle window** | 155 | 259 | 2,280 | 1,779 | 311 |
| **C — detected; intended target is a lead, not a finding** | 1,200 | 1,483 | 8,637 | 5,915 | 1,617 |

Per class (distinct texts are counted per class; a text can carry pairs in
more than one class, so class texts sum to 2,526 against a union of 2,372):

| class | pairs | texts | rows | `ok` rows |
|---|---:|---:|---:|---:|
| C0 title-impossible | 31 | 35 | 134 | 74 |
| C1 zero-padded | 48 | 101 | 943 | 569 |
| C2 subsection-as-section | 75 | 91 | 3,659 | 3,614 |
| C3 paren-suffix-eaten | 4 | 84 | 343 | 50 |
| C5 appendix-out-of-oracle | 33 | 55 | 269 | 80 |
| C6 appendix-miss | 11 | 15 | 42 | 25 |
| C7 chapter-as-section | 94 | 144 | 1,253 | 1,031 |
| C8 hyphen-part-dropped | 3 | 26 | 158 | 98 |
| C8b letter-o-as-zero | 9 | 15 | 61 | 51 |
| C8c inverted-range-kept-whole | 109 | 137 | 649 | 431 |
| C9 title-49-pre-1996 | 111 | 189 | 1,969 | 1,674 |
| C10 unique-near-miss | 146 | 167 | 833 | 573 |
| C11 corroborated-near-miss | 237 | 358 | 2,321 | 1,686 |
| C12 unresolved | 817 | 973 | 5,483 | 3,656 |
| **total** | **1,728** | **2,372** | **18,117** | **13,612** |

(There is no C4 in the final table: the date-year class it was reserved for
had already vanished from the artifact by the 17:44 build — see §9.)

## 4. Group A — mechanically detectable, and the right reading is derivable

**C2 subsection-as-section — 75 pairs / 91 texts / 3,659 rows / 3,614 `ok`.**
Predicate: `section` matches `^(\d+)([a-z]+)$`, the stem is a real section,
and the tail is a real subsection of it, while the whole token is not a
section.

- `21 USC 321p` → 21 U.S.C. 321p — **1,764 rows, 139 RINs, 1995-10→2020-10**.
  Truth: 21 U.S.C. 321(p), the FD&C Act definition of "new drug" (verified at
  law.cornell.edu: title 21 has 321, 321a–321d only; § 321 has subsections
  (a)–(ss) including (p)).
- `21 USC 371a` → 21 U.S.C. 371a — **1,551 rows, 140 RINs**. Truth: 21 U.S.C.
  371(a), FDA rulemaking authority (verified: no § 371a exists).
- `21 USC 361a` → 21 U.S.C. 361a (39 rows). Truth: 361(a).
- `12 U.S.C. 1828o` → 12 U.S.C. 1828o (38 rows). Truth: 1828(o).
- `42 USC 7414a` → 42 U.S.C. 7414a (17 rows). Truth: 7414(a).

This is the single largest defect and it is *not* fixable from the text
alone — `360b` is a real section and `321p` is not, and nothing in the
characters separates them. The oracle is what makes it decidable.

**C7 chapter-as-section — 94 pairs / 144 texts / 1,253 rows / 1,031 `ok`.**
Predicate: no section of that number, but a chapter of that number exists in
the title.

- `10 USC 55` → 10 U.S.C. 55 — 202 rows, 36 RINs. Verified: 10 U.S.C. ch. 55
  is "Medical and Dental Care", §§ 1071–1110b; there is no § 55.
- `46 USC 701` → 46 U.S.C. 701 — 82 rows, 9 RINs. Verified: ch. 701 is "Port
  Security", §§ 70101–70132; no § 701.
- `5 U.S.C. 89` → 5 U.S.C. 89 (59 rows) — ch. 89 is FEHB, §§ 8901–8914.
- `41 U.S.C. 85` → 41 U.S.C. 85 (48 rows); `49 USC 401` (40 rows);
  `Delegation of authority at 49 USC 1.95` → 49 U.S.C. 1 (103 rows).

**C8c inverted-range kept whole — 109 pairs / 137 texts / 649 rows.**
Predicate: `^(\d+)-(\d+)$` with second endpoint < first.
`_usc_section_range` fail-closes here and keeps the pair as one *name* —
which then asserts a section that doesn't exist, instead of refusing.

- `26 U.S.C. 2032-1(e)` → 26 U.S.C. 2032-1 (90 rows) — the source is a
  **26 CFR** reg number (20.2032-1) mislabelled U.S.C.
- `26 U.S.C. 460-6`, `472-8`, `436-1`, `472-1` (116 rows combined) — same shape.
- `50 U.S.C. 4801-4582` → 50 U.S.C. 4801-4582 (28 rows, 12 RINs).

**C1 zero-padded — 48 pairs / 101 texts / 943 rows / 569 `ok`.** Predicate:
`^0\d`, and the pad-stripped token is a real section.

- `26 U.S.C. 0956(e)` → 0956 (78 rows); `26 USC 0367` (71); `26 USC 0864`
  (55); `26 USC 0901` (55); `26 U.S.C. 0904(d)` (52). All are Treasury
  citations zero-padded to four digits; `_usc_section` never strips the pad.

**C0 impossible title — 31 pairs / 35 texts / 134 rows / 74 `ok`.** The
grammar *already* sets `usc_title_is_possible = false` here, but
`parse_status` still says `ok`, so the warning lives in a column most
consumers won't read.

- `61 U.S.C. 4901 to 4916` — `ok`, 23 rows; `410 USC 421` — `ok`, 11 rows,
  10 RINs; `347 USC 307(e)`; `166 U.S.C. 1531 et seq.` — `ok`;
  `72 USC 3535(d)`.

**C3 paren-suffix eaten — 4 pairs / 84 texts / 343 rows.** The
`_usc_section` strip of `(...)` destroys a real letter-suffixed section.
`15 USC 78(a)` → 78 (245 rows, 53 RINs; 15 U.S.C. 78a is real, bare 78 is
not); `42 U.S.C. 2000(d)` → 2000 (49 rows; truth 2000d); `15 U.S.C. 80(a)-23`
→ 80 (40 rows; truth 80a-23); `19 U.S.C. 81(c)` → 81 (9 rows; truth 81c).

**C8 hyphen-part dropped — 3 pairs / 26 texts / 158 rows.** `15 USC 80a et
seq` → 80a (84 rows, 25 RINs; the Investment Company Act starts at 80a-1);
`42 USC 300aa` → 300aa (40 rows; Vaccine Act starts at 300aa-1);
`15 U.S.C. 80b-(4)` → 80b (34 rows).

**C8b letter-o typed as zero — 9 pairs / 15 texts / 61 rows.** e.g.
`15 U.S.C. 780-10` for 78o-10.

## 5. Group B — real when written; NOT a misread

**C9 pre-1996 Title 49 — 111 pairs / 189 texts / 1,969 rows / 113 RINs.**
`49 USC 1421`, `49 USC 1354(a)`, `49 USC 1371`, `49 USC 1381`, `49 USC 1386`,
`49 USC 1502` — the old Federal Aviation Act / ICC numbering, real until the
1994 recodification (Pub. L. 103-272) and the 1995 ICC Termination Act. The
corpus proves it itself: the *same 113 RINs* cite `49 USC 1354` in the 1995-10
edition and switch to `49 U.S.C. 40113` / `44701` from 1996-04 on. The oracle
cannot confirm them only because no OLRC archive carries a Title 49 Appendix.

**C5/C6 appendix — 44 pairs / 70 texts / 311 rows.** `49 USC app 1 to 85
(1988)` (134 rows, 66 RINs) and `49 USC app 2505`, `49 USC App 1804` are the
same Title 49 App gap. `50 USC app 24091 et seq`, `46 USC app 841(a)`,
`46 App USC 12102` are genuine source defects.

Separately, **18 U.S.C. 3568** (182 rows, 14 RINs, still cited in 2025-10)
sits in group C but belongs here: it was a real section, repealed by the
Sentencing Reform Act of 1984 effective 1987-11-01, and agencies cite it
deliberately for pre-1987 conduct. The oracle window starts at the 1994
edition, so it cannot be confirmed. **Sections repealed before 1994 and not
stubbed in the current release point are an oracle blind spot this leg could
not close.**

## 6. Group C — pointing at nothing; the target is evidence-graded

Detection is solid (the parsed section does not exist). The *intended*
citation is a lead. Of the 817 unresolved pairs, **351 (2,684 rows) have a
corpus-stated string sibling** — another distinct `authority_text` in the
corpus identical except for the section token, where that token *is* a real
section; **189 (1,578 rows) have exactly one such sibling.** (`sibling.json`.)

Strongest, publisher- or corpus-verified:

- `46 USC 466(c)` — **289 rows, 68 RINs**, plus `40 USC 466(c)` (146 rows, 56
  RINs) and `45 USC 466(c)`. No title 40/45/46 has a § 466 in any edition. The
  same RINs' clean 1999 authority block reads `46 USC app 466c`, and the
  1994–2005 archives show **46 U.S.C. App. § 466c "Export of horses"** — the
  BIS export-control authority. The "app." marker is lost and the parenthesis
  invented.
- `18 USC 2501 et seq` — **186 rows, 61 RINs** (all BIS `0694-*`). No 18
  U.S.C. 2501. The corpus states `18 USC 2510 et seq` 289 times in the same
  boilerplate family — one transposition; 18 U.S.C. 2510 (Wiretap Act) is the
  EAR's encryption-controls authority.
- `42 USC 794` — 91 rows, 14 RINs. Title 42 has no § 794. **29 U.S.C. 794 is
  § 504 of the Rehabilitation Act** (verified) — a title error, which the
  section-only sibling test mis-ranks (it proposed 42 U.S.C. 294).
- `5 U.S.C. 533` / `5 USC 533` — 106 rows, 16 RINs, 1995-10→2025-10, `ok`.
  No 5 U.S.C. 533; `5 U.S.C. 553` (APA rulemaking) appears 783 times in the
  corpus. Likewise `5 USC 522` → 552 (50 rows, FOIA).
- `21 USC 360gg to 360ss` — 120 rows, 15 RINs. Verified at Cornell: 21 U.S.C.
  360gg does not exist; the radiation-control subchapter opens at **360hh**.
  The near-miss generator proposed `21 U.S.C. 360` here — a valid single edit
  and the wrong answer. That is exactly why these are not called findings.
- `40 USC 466(c)` also has a clean single-edit sibling `40 U.S.C. 486`
  (present 1994–2001, the Federal Property Act § 205 authority). **Whether
  the 54 RINs writing both `46 USC 466(c)` and `40 USC 466(c)` meant one
  authority twice-garbled or two different ones could not be settled.**

## 7. The reverse test — `NN U.S. XXX`

12 distinct texts / 22 rows match `^\d{1,2}\s*U\.?\s?S\.?\s+\d`. **All 12
name a real U.S.C. section (12/12).**

- **2 texts / 6 rows parse as `case_citation` / `ok`** — the silent misread:
  `40 U.S. 550` (4 rows, 2023-10→2025-04) and `43 U.S. 1763` (2 rows,
  2025-04→2025-10). Verified: 40 U.S.C. 550 is "Disposal of real property for
  certain purposes" (surplus property for education/health/parks) and 43
  U.S.C. 1763 is FLPMA rights-of-way — both current, both exactly the kind of
  thing an agency cites as authority. `43 U.S. 1763` is additionally
  impossible as a case: no U.S. Reports volume runs to page 1763.
- **1 text / 4 rows** parses `usc`/`partial` and silently drops the head:
  `49 US 106(g), 49 USC 40113, …` emits 40113/40119/41706/44101 but never
  106, though 49 U.S.C. 106 is real.
- **9 texts / 12 rows** fail loudly as `other`/`failed` (`7 U.S. 6g`,
  `42 US 1396b(q)`, `42 US 2201`, `15 US 1392`, `30 US 820`, `49 US 44719`,
  `50 US 2401 et seq`, `42 US. 7401 et seq.`, `49 U.S 41102, …`). Every one
  names a real section — recoverable, currently refused.

## 8. Exact predicates

All runnable against the pinned parquet plus the oracle parquets in
`usc-section-oracle-2026-08-22/`; the implementation is `scripts/triage.py`.

- **existence**: `(usc_title, usc_section) NOT IN oracle_exact ∪ oracle_annual`
  AND not inside any `oracle_ranges` / `oracle_annual_rng` span, where the
  span test compares `(leading-digits, remainder)` tuples. **Candidate
  proposals must use the exact sets only** — range membership admits `36o0`
  as a title-42 section and produced a 110-pair false-positive class until it
  was restricted.
- **C0**: `usc_title_is_possible = false` OR `usc_title NOT BETWEEN 1 AND 54`
  OR `usc_title = 53`.
- **C1**: `usc_section ~ '^0\d'` AND `ltrim(usc_section,'0')` ∈ oracle.
- **C2**: `usc_section ~ '^(\d+)([a-z]+)$'` AND stem ∈ oracle AND
  (title, stem, tail) ∈ subsection oracle AND whole ∉ oracle.
- **C3**: `authority_text ~ '\b<sec>\s*\(\s*<suf>\s*\)'` AND `<sec>` ∉ oracle
  AND `<sec><suf>` ∈ oracle (or a section named `<sec><suf>-N` exists).
- **C5/C6**: `usc_appendix = true` and the (title, section) is absent from
  the appendix oracle; C5 when the title has no appendix file in any archive
  year (49, and any title outside {5, 10, 11, 18, 26, 28, 38, 40, 46, 50}),
  C6 otherwise.
- **C7**: `(usc_title, usc_section)` ∈ chapter oracle AND ∉ section oracle,
  with `usc_section ~ '^\d+[a-z]?$'`.
- **C8**: some oracle section in the title is named `<sec>-N`.
- **C8b**: replacing one non-leading `0` in `usc_section` with `o` yields a
  section ∈ oracle (exact set).
- **C8c**: `usc_section ~ '^(\d+)-(\d+)$'` with `int(hi) < int(lo)` and `lo`
  ∈ oracle.
- **C9**: `usc_title = 49` AND (`usc_section` all digits with value < 2000 or
  in 10000–11999, OR `^\d{1,4}[a-z]`), once C0–C8c have not fired.
- **C10**: exactly one single-edit neighbour (zero-pad strip, suffix
  restored/dropped, one digit transposed/dropped/added/changed, or the same
  section under another title) exists in the exact set.
- **C11**: more than one neighbour exists and at least one is stated by the
  same RIN elsewhere in the corpus; the neighbour with most same-RIN
  statements is reported, runners-up kept.
- **C12**: neither.

Precedence is the order above: a pair takes the first class whose predicate
fires.

## 9. What could not be settled

- **Sections repealed before the 1994 edition** that the current release
  point does not stub (18 U.S.C. 3568 is the clear case). No published
  machine-readable source reachable in this leg covers 1988–1993. These are
  indistinguishable from misreads by the oracle alone.
- **The pre-1996 Title 49 Appendix.** Absent from every OLRC annual archive;
  govinfo's `USCODE-1994-title49a` package is unreachable and the API
  rate-limited. 1,969 rows rest on the corpus's own temporal evidence, not on
  a publisher inventory.
- **Whether `40 USC 466(c)` means 46 U.S.C. App. 466c or 40 U.S.C. 486(c).**
  Both are defensible; 54 RINs write both strings.
- **The intended target of 817 unresolved pairs / 5,483 rows.** Detection is
  certain; the fix is not. `21 USC 360gg` shows the failure mode — a unique
  small edit that is confidently wrong.
- **C2 only works for sections still live today**, because the subsection
  oracle comes from the current release point. `16 USC 462k` (49 rows) is
  almost certainly 16 U.S.C. 462(k), but § 462 was transferred to title 54 in
  2014, so its subsections aren't extractable and it fell to "unresolved".
- **Sequencing.** The pinned artifact and the parser both changed during the
  run. In the 17:10 build, `18 USC 1987` (557 rows / 86 texts / 48 RINs) and
  `18 USC 1984` (438 rows / 60 texts / 46 RINs) — the *year of a repeal date
  read as a section*, from strings like `4082 (Repealed in part as to
  offenses committed on or after November 1, 1987)` — were live misreads.
  Both are **absent from the 17:44 build**: the parser now stops at 4082.
  Whether that was a sibling leg's fix or one of
  `d3302db9`/`11b7fbdb`/`cc9c5cbd` was not chased; the class was real and is
  now gone, and no number in this report includes it. The campaign README
  records the same removal from its side (995 rows, class B0).
- **Source-zip digests.** The ~2.2 GB of zips was deleted after extraction
  before any sha256 was taken. They were re-fetched from the same URLs after
  the coordinator asked for pinning; `usc-section-oracle-2026-08-22/README.md`
  records which re-fetched files reproduce the committed parquets and their
  digests.

## 10. One correction to the campaign README

`silent-misreads-2026-08-22/README.md` says the subsection oracle was "built
from OLRC annual U.S.C. XML". It was not: `usc-oracle-subsections.parquet`
(and the chapter oracle) come from the **current release point USLM XML**
(`xml_uscAll@119-102.zip`), non-appendix titles only, via
`scripts/extract_subsections.py`. That is why it is current-code only and why
C2 cannot see subsections of transferred sections (§9). The five
`usc-oracle-*.parquet` files in that directory are byte-identical (sha256)
to the ones here; the annual-sections set that carries most of the existence
test (`usc-oracle-annual-sections.parquet`, 7.2 MB) exists only here.
