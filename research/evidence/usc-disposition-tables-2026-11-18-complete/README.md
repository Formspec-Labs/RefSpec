# Complete U.S.C. recodification disposition tables (Titles 10 ROPMA, 34, 41, 51, 54 & Title 49 Positive-Law) — 2026-11-18

Companion sealed artifact completing `refspec.registry.usc_disposition_tables`
alongside `../usc-disposition-tables-2026-08-23/` (Title 49 / 49 App.) and
`../usc-disposition-tables-2026-11-18/` (Titles 31 and 46 / 46 App. + 27-section
Title 49a hold-out audit), leaving `RECODIFICATIONS_NOT_PINNED` empty (`{}`).

## Recodifications added here

1. **Title 10 Subtitle E — Reserve Officer Personnel Management Act (`title-10-1994`)**
   — Pub. L. 103-337, div. A, title XVI, Oct. 5, 1994, 108 Stat. 2924 (deeming
   provision: Pub. L. 103-337, § 1665(a), limited to §§ 1661–1664 [§ 1665(b)
   preserves regulations]; plus ROPMA technical repeal of `10 U.S.C. 5600 -> 12207`
   by Pub. L. 104-106, div. A, title XV, § 1501(c)(26), Feb. 10, 1996, 110 Stat. 499),
   extracted from GovInfo `USCODE-1996-title10.pdf` (first edition after the Oct. 1,
   1996 ROPMA effective date). Title IX repeals in the same public law (such as
   `10 U.S.C. 3040`, repealed by § 904(b)(1)) are explicitly excluded.
   - **Critical 1956-vs-1994 front-matter distinction**: Pages 1–12 of both
     `USCODE-1994-title10.pdf` and `USCODE-1996-title10.pdf` print ONLY the **1956**
     Title 10 enactment tables (`TABLE I`: pre-1956 former Title 10, where
     `593 -> 3548, 3575, 8548, 8575` and `597 -> Rep.`; `TABLE II`: pre-1956 Navy
     Title 34 -> Title 10). Reading the 1956 front-matter table for 1994 ROPMA
     citations would publish the wrong sections on `10 U.S.C. 593 -> 12203`
     (ch. 1205) and `10 U.S.C. 597 -> 12241` (ch. 1207). Instead, `USCODE-1996-title10.pdf`
     states every 1994 ROPMA disposition in two independent places that reconcile
     with **83 / 83** exact renumbering agreement (`1331a -> 12731a` and
     `2233a -> 18233a` included), **270 / 270** bidirectional section-pair
     body-note agreement, and **58 / 58** exact non-successor status agreement
     across all **39** `see-reference` and **19** `repealed` sections: Subtitles A–D
     (`pp. 14–1511`, bracketed `[§ X. Renumbered § 1xxxx]` / `[§ ... Repealed. Pub. L. 103-337, div. A, title XVI ...]`
     stubs and `Prior section(s)` notes, preserving all **39** `See section ... et seq.`
     onward pointers as `status="see-reference"` without manufacturing Cartesian
     subsection pairs) and Subtitle E (`pp. 1512–1647`, `§§ 10001–18505`
     `AMENDMENTS` and `PRIOR PROVISIONS` notes, including partial ROPMA transfers
     out of surviving sections `175`, `517(b),(c)`, `1376(a)`, `1401(a) (table formula 3)`,
     and `6389(f)`).
2. **Title 34 — Crime Control and Law Enforcement (`title-34-2017`)** — OLRC
   editorial reclassification under `2 U.S.C. 285b`, effective Sept. 1, 2017
   (cutoff after Pub. L. 115-31), extracted from `USCODE-2017-title34.pdf` pp. 1–9
   (`Former Classification` -> `New Classification or Disposition`, covering
   former provisions of **Titles 42, 18, and 28** -> Title 34; verified identical
   row counts in `USCODE-2018-title34.pdf`).
3. **Title 41 — Public Contracts (`title-41-2011`)** — Pub. L. 111-350, Jan. 4,
   2011, 124 Stat. 3677 (deeming provision: Pub. L. 111-350, § 6(c)), extracted
   from `USCODE-2011-title41.pdf` pp. 1–3, including pre-recodification oracle
   range verification (`year < 2010` in pinned `usc-oracle-annual-sections.parquet`)
   recovering attested `41 U.S.C. 20a` and `20b` inside `17 to 21 -> (Previously repealed)`.
4. **Title 51 — National and Commercial Space Programs (`title-51-2010`)** —
   Pub. L. 111-314, Dec. 18, 2010, 124 Stat. 3326 (deeming provision:
   Pub. L. 111-314, § 5(e)), extracted from `USCODE-2010-title51.pdf` pp. 1–2
   across **Table I** (former **Title 15**, 48 rows) and **Table II** (former
   **Title 42**, 297 rows).
5. **Title 54 — National Park Service and Related Programs (`title-54-2014`)** —
   Pub. L. 113-287, Dec. 19, 2014, 128 Stat. 3094 (deeming provision:
   Pub. L. 113-287, § 6(e)), extracted from `USCODE-2014-title54.pdf` pp. 2–9
   (former **Title 16** -> Title 54, plus cross-title transfers to Title 15).
6. **Title 49 Pre-1994 Positive-Law Renumberings, Repeals & Note Transfers (`title-49-1994-positivelaw`)**
   — Pub. L. 103-272, July 5, 1994, 108 Stat. 745 (deeming provision:
   Pub. L. 103-272, § 6(b); `covers_appendix=False`), extracted across all
   `Pub. L. 103-272, § 1` Historical and Revision Notes tables, repeal stubs, and
   statutory credits in `USCODE-1994-title49.pdf` whose former section is disjoint
   from `../usc-disposition-tables-2026-08-23/usc-1994-title49-disposition.parquet`
   (`334 -> 45301`, `335 -> repealed`, `501(a)(1),(4)–(9) -> 5901(1)–(7)`, nested
   `508` subsections/note -> `5902..5907` preserving `(related to violations)` /
   `(related to effective date)` on `508(a)(3)`, `3101..3104 -> 31501..31504`,
   `10927 (note) -> 31138(a)–(e), 31139(a)–(g)` [pp. 539–540], and
   `11506 (note) -> 31701..31708` [pp. 559–561]; Subtitle I note credits under live
   `49:101`, `49:301`, and `49:308` are excluded so they never conflate with pre-1983
   `101 / 301 / 308` entries already in `usc-1994-title49-disposition.parquet`).
   Explicit `appendix=True` lookups stay gated out (`covers_appendix=False`), while
   `UscSectionOracle` narrowly resolves the 5 audited mislabelled `49 USC app 3102`
   Unified Agenda rows (`../usc-disposition-tables-2026-11-18/title49a-holdout-audit.{json,md}`),
   bringing bare-token table coverage across the 2,548 `title_49_appendix_not_published`
   Unified Agenda rows to **2,376 / 2,548** (the remaining **26** tokens / **172**
   rows are primary-source-verified non-statutory chapter numbers, CFR parts, wrong
   titles, lost-parenthesis pinpoints, or typos).

## Sources (verified by SHA-256 and byte length prior to extraction)

| recodification | URL | file | sha256 | bytes | fetched |
|---|---|---|---|---:|---|
| `title-10-1994` | `https://www.govinfo.gov/content/pkg/USCODE-1996-title10/pdf/USCODE-1996-title10.pdf` | `USCODE-1996-title10.pdf` | `d1877b5aa58f17062263fed5a04da62f3ad885b4b01a0da7f0e41d0da15e0010` | 8,971,147 | 2026-11-18 |
| `title-34-2017` | `https://www.govinfo.gov/content/pkg/USCODE-2017-title34/pdf/USCODE-2017-title34.pdf` | `USCODE-2017-title34.pdf` | `c121b7ca9147571955edbb9857da95e17292f21eb00f0a90741ae5b99c40bcd9` | 2,753,424 | 2026-11-18 |
| `title-41-2011` | `https://www.govinfo.gov/content/pkg/USCODE-2011-title41/pdf/USCODE-2011-title41.pdf` | `USCODE-2011-title41.pdf` | `3b253b255aa058d05aa4b3e6b6aa2f345ee25a1f98cff5ea19f514c2d0a417c1` | 1,037,994 | 2026-11-18 |
| `title-51-2010` | `https://www.govinfo.gov/content/pkg/USCODE-2010-title51/pdf/USCODE-2010-title51.pdf` | `USCODE-2010-title51.pdf` | `66d48661b3bae9b9e9e7a1964a64ff093dc22d94fae81eda6429a4f9551cea84` | 914,412 | 2026-11-18 |
| `title-54-2014` | `https://www.govinfo.gov/content/pkg/USCODE-2014-title54/pdf/USCODE-2014-title54.pdf` | `USCODE-2014-title54.pdf` | `548f857e19f2ce9c384211062872d422142a2b55129251d3f82e35c80eafcf21` | 1,085,260 | 2026-11-18 |
| `title-49-1994-positivelaw` | `https://www.govinfo.gov/content/pkg/USCODE-1994-title49/pdf/USCODE-1994-title49.pdf` | `../usc-disposition-tables-2026-08-23/USCODE-1994-title49.pdf` | `66f004679e27e0d16356e14b79cb3b4f7ebf63d91307435fa8f53c95bcc2848d` | 5,165,242 | 2026-08-23 |

Multi-MB PDFs fetched on 2026-11-18 are retained outside Git in local cache
(`.cache/archive-release/refspec-uscode-20261118/`, mapped to
`output/registry-real-data-sources/USCODE-*.pdf` in `sources.json`).

## Reproduction (`pdftotext version 26.10.0`)

```bash
python3 scripts/extract_disposition_tables.py --pdf-dir <cache>
python3 scripts/crosscheck_disposition_tables.py --pdf-dir <cache> --self-test
```

## Files

| file | sha256 | bytes | entries / rows |
|---|---|---:|---:|
| `usc-1996-title10-ropma-disposition.parquet` | `5a08734b3c8ea948340203e0e3c67a256a6a62c95ece863a1328a662691eace6` | 9,180 | 359 entries / 371 rows |
| `usc-1996-title10-ropma-disposition.txt` | `4902caf1a97c73f9f395f01ad08c4b49aa217281f80ac39f6c618e9aa3597d4a` | 23,541 | 359 entries |
| `usc-2017-title34-disposition.parquet` | `17e063ddd410d39c135e4d14550dceadc62707a811dc9e7bd2f63999014dd047` | 21,329 | 1,002 entries / 1,002 rows |
| `usc-2017-title34-disposition.txt` | `faf1a8ae771bfd59d36f17f11b0d8a75640bf2b0d4c1eec6a13f774d95849c01` | 52,822 | 1,002 entries |
| `usc-2011-title41-disposition.parquet` | `327de9b607eaf74679c21af8a6cf27086c7bf5aaf19c01dbcf3005959fa3a51b` | 9,706 | 320 entries / 549 rows |
| `usc-2011-title41-disposition.txt` | `0e7b60a6c8dd0b6441391899eef5aa461bd4ce2e582e8dfcdaf9c1c9dd7bffd9` | 10,058 | 320 entries |
| `usc-2010-title51-disposition.parquet` | `507bdd8da5dd9a1ff6b5f395193408e1f36120803637ee367ddfecc3792d7c0a` | 8,074 | 244 entries / 345 rows |
| `usc-2010-title51-disposition.txt` | `fd4f112682511f5e06f0d3ee0ff8b2fe5b21c1a2f747879e62d02c25b6720b7d` | 6,649 | 244 entries |
| `usc-2014-title54-disposition.parquet` | `49e79253f9240b75edd85afa3d8fe9b513e231e060434d4fea0d6bab3ac60034` | 17,061 | 493 entries / 626 rows |
| `usc-2014-title54-disposition.txt` | `e2c1b9689b76ffe96f1c556e8b1c80389e9c6d2d5a1bcbc42d53ff7d89b59432` | 37,047 | 493 entries |
| `usc-1994-title49-positivelaw-disposition.parquet` | `6387ca0487ec234ae04811e90d1490e9bf93407d1b3dd5f3fa40836e3bc21510` | 4,624 | 49 entries / 49 rows |
| `usc-1994-title49-positivelaw-disposition.txt` | `d894c4534ec4c67f7b516e3543be4a6ceb628a515c1b997be475f1721476d83b` | 2,985 | 49 entries |
| `crosscheck-report.json` | `594b35d952e4ffa96e3ec4f14e58ad3ae8de38bcf2986e71967895e0d41ca23e` | 10,592 | 6 tables / 20 planted self-tests |
| `scripts/extract_disposition_tables.py` | `5724355304d7cc883cd4ff1b032fd8f765caecbb601529d8088be8d982608548` | 69,452 | — |
| `scripts/crosscheck_disposition_tables.py` | `bcff1d412ecc9ca4bc3c0222e0e5f2973cf8588e43e0a8cda02a47ee45f75b1f` | 39,615 | — |

## Counts & body cross-checks (`crosscheck-report.json`)

| table | former titles | entries | rows | distinct former | statuses (`restated` / `note` / `repealed` / `eliminated` / `see`) | body-note cross-check scope |
|---|---|---:|---:|---:|---|---:|
| `title-10-1994` | `10` | 359 | 371 | 300 | `313 / 0 / 19 / 0 / 39` | `270 / 270` section-pairs (two-way) + exact `58 / 58` non-successor statuses |
| `title-34-2017` | `42` (942), `18` (31), `28` (29) | 1,002 | 1,002 | 711 | `697 / 253 / 0 / 52 / 0` | `651 / 653` section-pairs (+ 2 OLRC print typos, two-way) |
| `title-41-2011` | `41` | 320 | 549 | 344 | `351 / 2 / 194 / 2 / 0` | `275 / 276` section-pairs (+ 1 OLRC HRN divergence, two-way) |
| `title-51-2010` | `42` (297), `15` (48) | 244 | 345 | 246 | `251 / 25 / 27 / 42 / 0` | `206 / 206` section-pairs (100.0%, two-way) |
| `title-54-2014` | `16` | 493 | 626 | 350 | `486 / 0 / 107 / 0 / 33` | `361 / 362` section-pairs (+ 1 OLRC print typo, two-way) |
| `title-49-1994-positivelaw` | `49` | 49 | 49 | 10 | `48 / 0 / 1 / 0 / 0` | `22 / 22` section-pairs (two-way) + exact `49 / 49` row/pinpoint/note equality |

### Verified OLRC front-matter print typos / divergences (pinned two-way in `crosscheck_disposition_tables.py` and surfaced on `Disposition.caveats`)

1. **Title 34 p. 8 right (`42:13136f -> 34:40728`)**: Printed between `42:14136e`
   and `42:14137` in both 2017 and 2018 editions; `42:13136f` never existed, and
   body `34 U.S.C. 40728` prints `Section was formerly classified to section 14136f of Title 42`.
2. **Title 34 p. 5 left (`42:3797ee-1 -> 34:16902`)**: Printed immediately after
   `42:3797ee -> 34:10691` with digits `069` transposed to `690` (`34 U.S.C. 16902`
   does not exist); p. 169 right under `34 U.S.C. 10692` prints `Section was formerly classified to section 3797ee-1 of Title 42`.
3. **Title 41 p. 1 right (`46 to 48 -> 8502 to 8504`)**: Body `§ 8501(2)` HRN
   additionally cites parenthetical committee-name words from `41:46(a)`.
4. **Title 54 p. 4 right (`16 U.S.C. 458a -> 54 U.S.C. 104908`)**: Chapter 1049
   ends at `104907` (`104908` is absent); body `§ 104905` HRN prints `16 U.S.C. 458a`.
