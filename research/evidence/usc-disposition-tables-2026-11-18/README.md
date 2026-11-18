# U.S.C. recodification disposition tables (Title 31 & Title 46) and Title 49a Hold-Out Audit — 2026-11-18

Companion sealed artifact to `../usc-disposition-tables-2026-08-23/` (which
remains untouched and carries Title 49). Adds two pinned positive-law
recodification disposition tables to `refspec.registry.usc_disposition_tables`
and records the primary-source statutory audit of all **27** distinct
`not-in-table` Title 49a sections (**177** rows in `HOLD_OUT`):

1. **Title 31 (Money and Finance)** — Pub. L. 97-258, § 1, Sept. 13, 1982, 96 Stat. 877
   (deeming provision: Pub. L. 97-258, § 4(b)), extracted from born-digital GovInfo
   `USCODE-1994-title31.pdf` pp. 1–6 ("TABLE SHOWING DISPOSITION OF ALL SECTIONS
   OF FORMER TITLE 31"), cross-checked against `USCODE-1994-title31.pdf` Historical
   and Revision Notes and 1982 LoC `uscode1982-013031001.pdf` (`31 U.S.C. 483a -> 9701`).
2. **Title 46 / Title 46 Appendix (Shipping)** — consolidated across all five
   enacting acts: Pub. L. 98-89 (1983), Pub. L. 99-509 (1986), Pub. L. 100-424
   (1988), Pub. L. 100-710 (1988), and Pub. L. 109-304 (2006) (deeming provisions:
   Pub. L. 98-89 § 2(b), Pub. L. 99-509 § 5103(b), Pub. L. 100-710 § 105(a),
   Pub. L. 109-304 § 18(c)), extracted from born-digital GovInfo
   `USCODE-2006-title46.pdf` pp. 1–9 ("Disposition Table (Showing Disposition of
   Former Sections of Title 46 or Title 46 Appendix)"), cross-checked against
   `USCODE-2006-title46.pdf` Historical and Revision Notes, OLRC 1994–2005
   `usc46a.htm` (434 sections), and 1988 LoC `uscode1988-018046000.pdf`.
3. **27-Section Title 49a Hold-Out Audit** (`title49a-holdout-audit.{json,md}`) —
   every one of the 27 distinct `not-in-table` Title 49a tokens (177 rows)
   adjudicated against primary 1988 U.S. Code Title 49 Appendix PDFs from
   `tile.loc.gov` and GovInfo `USCODE-1994-title49.pdf`.

## Why GovInfo born-digital volumes are primary over 1982/1988 LoC scans

The Library of Congress `tile.loc.gov` 1982 Title 31 (`uscode1982-013031001.pdf`)
and 1988 Title 46 (`uscode1988-018046000.pdf`) front-matter PDFs are scanned OCR
volumes (`LuraDocument PDF v2.65`) exhibiting two-column OCR bleed and character
substitutions (`43bin), (o)`, `44(lst sentence)`, `628-2, 828-3`, `T.10 3 2779`).
Moreover, the 1988 Title 46 table covers only the 1983–1988 partial codification
(Subtitles I–III; `[BALANCE OF TITLE RESERVED]`), transferring uncodified
sections to Title 46 Appendix. GovInfo's `USCODE-1994-title31.pdf` and
`USCODE-2006-title46.pdf` come directly from OLRC's vector typesetting pipeline
(`ACOMP.exe` / `AFPL Ghostscript 8.14`, identical to `USCODE-1994-title49.pdf`),
and `USCODE-2006-title46.pdf` prints the complete consolidated disposition table
spanning all 1983–2006 enacting acts for both former Title 46 and former Title 46
Appendix. Raw multi-MB PDFs are retained outside Git in local cache
(`.cache/archive-release/refspec-uscode-20261118/`) and verified by SHA-256 and
byte length before extraction.

## Sources (pinned outside Git)

| what | Title 31 (`title-31-1982`) | Title 46 (`title-46-2006`) |
|---|---|---|
| URL | `https://www.govinfo.gov/content/pkg/USCODE-1994-title31/pdf/USCODE-1994-title31.pdf` | `https://www.govinfo.gov/content/pkg/USCODE-2006-title46/pdf/USCODE-2006-title46.pdf` |
| file (in cache) | `USCODE-1994-title31.pdf` | `USCODE-2006-title46.pdf` |
| sha256 | `3b319dc182915b409d01c26d5fe46326e0416f5e725aa556738d17ba60340f0a` | `6bda1578ab30e947d3f7e746bacd53048a197ef80c946f0f7300276c97a5887d` |
| bytes | 2,088,477 | 2,449,872 |
| pages (table) | 350 (pp. 1–6) | 421 (pp. 1–9) |
| fetched | 2026-11-18, `curl -fsSL --http1.1 --retry 3`, HTTP 200 | 2026-11-18, `curl -fsSL --http1.1 --retry 3`, HTTP 200 |
| server `Last-Modified` | Fri, 29 Nov 2019 17:26:23 GMT | Sat, 02 Nov 2019 13:10:31 GMT |
| PDF producer / source | `AFPL Ghostscript 8.14` (`C:\LRC\WORK\^PDFMAKE\1994\USC31.94`) | `AFPL Ghostscript 8.14` (`C:\LRC\WORK\^PDFMAKE\FOLIOS\USC46.06`) |

Secondary LoC cross-check PDFs (retained in cache):
- `uscode1982-013031001.pdf` (`sha256:646296b4c59e422b968ef236fec95af996af7ea4af54732b5acc059202aa6804`, 208,275 bytes) — confirms `31 U.S.C. 483a -> 9701` in the 1982 edition.
- `uscode1988-018046000.pdf` (`sha256:46917f78ef80ef7f0c85a0196620444e659a4ce48263cff44b2324eab74f67d5`, 155,564 bytes) — confirms 1983–1988 partial Title 46 codification and transfer of remaining former sections to Title 46 Appendix.

## Extractor & reproduction

Run with **poppler `pdftotext version 26.10.0`** and **pyarrow 25.0.1** (both
Parquet and `.txt` outputs verified byte-identical across consecutive runs):

```bash
python3 scripts/extract_disposition_tables.py --title 31 \
    <cache>/USCODE-1994-title31.pdf \
    usc-1994-title31-disposition.parquet \
    --text usc-1994-title31-disposition.txt

python3 scripts/extract_disposition_tables.py --title 46 \
    <cache>/USCODE-2006-title46.pdf \
    usc-2006-title46-disposition.parquet \
    --text usc-2006-title46-disposition.txt

python3 scripts/crosscheck_disposition_tables.py \
    --artifact-dir . \
    --cache-dir <cache> \
    --repo-root ../../.. \
    --out crosscheck-report.json
```

Geometry notes (measured from `-bbox-layout` XML across all table pages):
- Left table block: former `xMax <= 191.4`, new `xMin = 197.5` (`COLUMN_SPLIT["left"] = 194.5`).
- Right table block: former `xMax <= 410.0`, new `xMin = 416.5` (`COLUMN_SPLIT["right"] = 413.5`).
- Full-width prose following each table (`ENACTING CLAUSE` on Title 31 p. 6 left, `ENACTING CLAUSES` on Title 46 p. 9 right) crosses the column split and terminates extraction for that half.
- Hyphenated former section tokens (`52-1`..`52-7`, `82a-1`, `725q-1a`, `404-1`, `883-1`, `1126-1`, `1295c-1`, etc.) are preserved intact (distinguished from ascending section ranges because every hyphenated suffix is strictly smaller than its leading section number). Zero comma-pieces go unparsed (`prose == []`).

## Files

| file | sha256 | bytes | entries / rows |
|---|---|---:|---:|
| `usc-1994-title31-disposition.parquet` | `9b8fcb6e6d10a5a06e36ce88a5d7887c5746ff13f083cf1a1e7aab53c2cd780d` | 21,194 | 1,561 rows |
| `usc-1994-title31-disposition.txt` | `e79941a9cb0480a629bda8dc492b02ce8724f329f1b89a13b18b834cc1c1db15` | 25,848 | 965 entries |
| `usc-2006-title46-disposition.parquet` | `8d8421bdbb971a0e474626d9176e7d25fac255805855b829fc6ff38cc760066e` | 29,334 | 2,178 rows |
| `usc-2006-title46-disposition.txt` | `4b6c152c1b72b253fd18466eeb32598d560e659708ec557579c54714794e9539` | 36,881 | 1,344 entries |
| `crosscheck-report.json` | `a2eb4de6f03b8367b71b14ff6a16f7013c383024f8ba10586869293ed398c511` | 8,050 | — |
| `title49a-holdout-audit.json` | `e0531bf6e5a983354ccf91f2ade1400386cb20fa7f567a1cb4cbd5d78b2f6b38` | 40,283 | 27 sections / 177 rows |
| `title49a-holdout-audit.md` | `7d0016f88d777d93f9e834520b4394207b31d0ed35c4dee7bde252f22886215a` | 20,713 | 27 sections / 177 rows |
| `scripts/extract_disposition_tables.py` | `717dd034ba0ca76d58a3afc3b6916885720036310362a403decf54da26f6ca53` | 29,695 | — |
| `scripts/crosscheck_disposition_tables.py` | `e7f46daaed17aaa9db4565e6e2436cfce8a24c6dbc4a6282e6e364a04a7dfa51` | 15,316 | — |
| `scripts/build_title49a_holdout_audit.py` | `d612f532a68041c1f6240c2c96144626a7cffa3a4dbb4652e9cc6f1b4c45b4b2` | 38,757 | — |

## Counts

| measure | Title 31 (`title-31-1982`) | Title 46 (`title-46-2006`) |
|---|---:|---:|
| printed entries | 965 | 1,344 |
| emitted rows | 1,561 | 2,178 |
| distinct former sections | 1,156 | 1,296 |
| distinct former `(section, subsection)` | 1,456 | 1,833 |
| distinct successors `(title, section)` | 413 | 769 |
| former sections with >1 row | 103 | 204 |
| rows `restated` / `repealed` / `eliminated` / `see-reference` / `restated-as-note` | 996 / 536 / 21 / 2 / 6 | 1,469 / 652 / 2 / 6 / 49 |
| former sections with **only** repealed rows | 492 | 600 |
| former sections with both a successor and a repealed part | 23 | 32 |
| table pages | 1–6 | 1–9 |

## Independent cross-checks (`crosscheck-report.json`)

1. **Title 31 Historical and Revision Notes (`USCODE-1994-title31.pdf`)**:
   - **541** distinct `31:<sec>` tokens appear in the body notes:
     - **526** match exact keys in `usc-1994-title31-disposition.parquet`,
     - **2** (`22a`, `324b-1`) fall strictly inside printed range entries (`22-24`, `324b to 324c`),
     - **13** (`1305, 3302, 3331, 3701, 3702, 5103, 5112, 5132, 5154, 6102, 6501, 9101, 9107`) are post-1982 revised positive-law Title 31 section headings referenced by 1983/1984 improvement Act notes (Pub. L. 97-452 / Pub. L. 98-216),
     - **0** pre-1982 tokens missing.
   - `31 U.S.C. 483a -> 9701` verified in the disposition table (p. 3 left), in `USCODE-1994-title31.pdf` § 9701 Historical and Revision Notes (`31:483a`), and in 1982 LoC `uscode1982-013031001.pdf`.
2. **Title 46 Historical and Revision Notes (`USCODE-2006-title46.pdf`)**:
   - **`46 App.:<sec>`**: **283 of 283 (100.0%)** match exact keys in `usc-2006-title46-disposition.parquet` (**0** missing).
   - **Pre-codification `46:<sec>` (`< 2100`)**: **280 of 281** match exact keys; the lone discrepancy (`46:525h` in § 4103's HRN) is a verified single-digit publisher typo in OLRC's note for `46:526h` (Motorboat Act of 1940 § 9, which the disposition table maps to `4103`).
3. **OLRC 1994–2005 `usc46a.htm` annual archive cross-check**:
   - All **434** distinct Title 46 Appendix sections in `usc-oracle-annual-sections.parquet` are accounted for: **431** exact keys plus **3** (`845a`, `845b`, `1183a`) strictly inside printed range entries (`843-848 -> Rep.`, `1183-1185a -> 53101 note`). **0** missing.
4. **1988 LoC Title 46 (`uscode1988-018046000.pdf`) spot verification**:
   - Spot-checked Subtitle II–III codification mappings (`71`, `72`, `75`, `391a`) and post-1988 Title 46 Appendix codifications (`466c -> 15:1824a`, `688 -> 46:30104, 30105`, `1300 -> 46:30701 note`).

## Title 49a 27-Section Hold-Out Audit Summary

See `title49a-holdout-audit.md` and `title49a-holdout-audit.json` for full
section-by-section adjudication against eight primary 1988 Title 49a chapter
PDFs (`uscode1988-019049a{001,004,006,008,009,013,020,026}.pdf`) and GovInfo
`USCODE-1994-title49.pdf`:

- **0 / 27** hold-out tokens existed as sections of 1988 Title 49 Appendix; **0 / 27** are omissions from the 1994 Title 49 Disposition Table.
- **9 sections / 114 rows** (`411, 413, 415, 417, 419, 447, 449, 463, 465`) are current positive-law **Title 49 Subtitle VII chapter numbers** cited without `ch.`/`chapters` (correcting the earlier 14 CFR ch. III conjecture).
- **1 section / 5 rows** (`3102`) is pre-1994 positive-law `49 U.S.C. § 3102` (Pub. L. 97-449; renumbered `§ 31502` by Pub. L. 103-272), mislabelled `app`.
- **17 sections / 58 rows** are lost-parenthesis pinpoints (`322a`, `1509d`, `114l`), wrong-title citations (`5:552a(k)`, `23:217`, former `15:1392`), CFR parts in the U.S.C. slot (`49 CFR 190`, `49 CFR 29`), or filer typos/truncations/parser damage (`374, 166, 1085, 10109, 40, 134, 406, 1491, 1763`).
- Raw 1988 OCR is **not** imported into `UscSectionOracle` (it would recover 0 of 177 rows).
