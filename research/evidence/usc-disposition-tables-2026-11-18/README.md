# U.S.C. recodification disposition tables (Title 31 & Title 46) and Title 49a Hold-Out Audit — 2026-11-18

Companion sealed artifact to `../usc-disposition-tables-2026-08-23/` (which
remains untouched and carries Title 49). Adds two pinned positive-law
recodification disposition tables to `refspec.registry.usc_disposition_tables`
and records the primary-source statutory audit of all **27** distinct
`not-in-table` Title 49a sections (**177** rows in `HOLD_OUT`):

1. **Title 31 (Money and Finance)** — Pub. L. 97-258, § 1, Sept. 13, 1982, 96 Stat. 877,
   as supplemented by Pub. L. 97-452, § 1, Jan. 12, 1983, 96 Stat. 2467
   (deeming provisions: Pub. L. 97-258 § 4(b), Pub. L. 97-452 § 3(b)), extracted from
   born-digital GovInfo `USCODE-1994-title31.pdf` pp. 1–6 ("TABLE SHOWING DISPOSITION OF
   ALL SECTIONS OF FORMER TITLE 31"), cross-checked against `USCODE-1994-title31.pdf`
   Historical and Revision Notes and 1982 LoC `uscode1982-013031001.pdf` (`31 U.S.C. 483a -> 9701`).
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
- Respective 1-to-1 ranges: the lone multi-former x multi-new entry across both tables (`454-457 -> T. 33 §§ 1233-1236`, Title 46 p. 3 right) is zipped 1-to-1 (`454->33:1233`, `455->33:1234`, `456->33:1235`, `457->33:1236`) per the `1994usc33.htm` Codification notes for Act of Apr. 28, 1908, ch. 151, §§ 1–4, 35 Stat. 69, preserving verbatim `former_text`/`new_text` and eliminating 12 false Cartesian pairs.
- Independently attested alphanumeric range members (`31:22a` inside `22-24`, `31:324b-1` inside `324b to 324c`, `46:845a`/`46:845b` inside `843-848`, and `46:1183a` inside `1183-1185a` — each verified in the volume's HRN or OLRC 1994–2005 `usc46a.htm`) are emitted against their enclosing printed rows so direct lookups resolve rather than answering `not-in-table`. Unattested intermediate lettered sections are never invented.

## Files

| file | sha256 | bytes | entries / rows |
|---|---|---:|---:|
| `usc-1994-title31-disposition.parquet` | `febacca0f59193fc4524ce780d29ba5440d8ee47f8041f133fda161d0c765cd5` | 21,251 | 1,563 rows |
| `usc-1994-title31-disposition.txt` | `e79941a9cb0480a629bda8dc492b02ce8724f329f1b89a13b18b834cc1c1db15` | 25,848 | 965 entries |
| `usc-2006-title46-disposition.parquet` | `2b6a315482a8b8ba142360ea3303e55e6e8e07d632ebe4c3a1a24d38a9efca84` | 29,320 | 2,169 rows |
| `usc-2006-title46-disposition.txt` | `4b6c152c1b72b253fd18466eeb32598d560e659708ec557579c54714794e9539` | 36,881 | 1,344 entries |
| `crosscheck-report.json` | `201dce646ca8dd4a9ad1c70a096061742300e2fb3b7ff47687c369cdaa18f2eb` | 6,669 | — |
| `title49a-holdout-audit.json` | `970757491eb0117d7adbc2afd9c4184117fece29ccf6cd3facd2611b364dc912` | 41,898 | 27 sections / 177 rows |
| `title49a-holdout-audit.md` | `9af961814c5c7e1da1e231d97d70d30f02eb4aa55ef28d08b84f9f7e58fc67d4` | 22,379 | 27 sections / 177 rows |
| `scripts/extract_disposition_tables.py` | `3f1585b511158267b4f40a5caf3e0698a84b5e4091c04a81833b89aa2023fb08` | 34,081 | — |
| `scripts/crosscheck_disposition_tables.py` | `7152ef90d2b3ba69c902a430481ac9a28a03f8fc2b65e9c833beda50f2a36ff0` | 22,639 | — |
| `scripts/build_title49a_holdout_audit.py` | `3b2444039c2e4671a44c349f2aacb183e072525a55fcd17b3f4b91e7678cb66c` | 41,706 | — |

## Counts

| measure | Title 31 (`title-31-1982`) | Title 46 (`title-46-2006`) |
|---|---:|---:|
| printed entries | 965 | 1,344 |
| emitted rows | 1,563 | 2,169 |
| distinct former sections | 1,158 | 1,299 |
| distinct former `(section, subsection)` | 1,458 | 1,836 |
| distinct successors `(title, section)` | 413 | 769 |
| former sections with >1 row | 103 | 200 |
| rows `restated` / `repealed` / `eliminated` / `see-reference` / `restated-as-note` | 998 / 536 / 21 / 2 / 6 | 1,457 / 654 / 2 / 6 / 50 |
| former sections with **only** repealed rows | 492 | 602 |
| former sections with **only** eliminated rows | 21 | 2 |
| former sections with both a successor and a repealed part | 23 | 32 |
| table pages | 1–6 | 1–9 |

## Independent cross-checks (`crosscheck-report.json`)

The cross-checker fails loudly on missing PDF body anchors, below-threshold HRN
populations, missing tokens, or destination mismatches (verified with planted
negative mutations: empty PDF text and mutated `31:483a -> 99999`):

1. **Title 31 Historical and Revision Notes (`USCODE-1994-title31.pdf`)**:
   - **541** distinct `31:<sec>` tokens appear in the body notes:
     - **528** match exact keys in `usc-1994-title31-disposition.parquet` (including attested range members `22a` and `324b-1`),
     - **13** (`1305, 3302, 3331, 3701, 3702, 5103, 5112, 5132, 5154, 6102, 6501, 9101, 9107`) are post-1982 revised positive-law Title 31 section headings referenced by 1983/1984 improvement Act notes (Pub. L. 97-452 / Pub. L. 98-216),
     - **0** pre-1982 tokens missing.
   - **Tabular HRN `(former -> new)` pairs**: **272 of 275** match exact Parquet destinations; the remaining 3 are documented OLRC front-matter-vs-HRN divergences (`665 -> 1349/1350` where p. 4 prints `1549/1550`, and `1001 -> 321` where p. 5 prints `301`).
   - Independent exact-destination specimens verified (`483a -> 31:9701` also in § 9701 HRN and 1982 LoC `uscode1982-013031001.pdf`; `22a -> 31:1108`; `324b-1 -> 31:5112`; `725a -> Elim.`).
2. **Title 46 Historical and Revision Notes (`USCODE-2006-title46.pdf`)**:
   - **`46 App.:<sec>`**: **283 of 283 (100.0%)** match exact keys in `usc-2006-title46-disposition.parquet` (**0** missing).
   - **Pre-codification `46:<sec>` (`< 2100`)**: **280 of 281** match exact keys; the lone discrepancy (`46:525h` in § 4103's HRN) is a verified single-digit publisher typo in OLRC's note for `46:526h` (Motorboat Act of 1940 § 9, which the disposition table maps to `4103`).
   - **Tabular HRN `(46 App.:former -> new)` pairs**: **208 of 209** match exact Parquet destinations (1 documented divergence: `1244 -> 113`, where p. 7 prints `1244(a) -> 109`).
3. **OLRC 1994–2005 `usc46a.htm` annual archive cross-check**:
   - All **434 of 434 (100.0%)** distinct Title 46 Appendix sections in `usc-oracle-annual-sections.parquet` match exact keys in the Parquet (including attested range members `845a`, `845b`, `1183a`). **0** missing.
4. **Independent destination specimens & 1988 LoC confirmation**:
   - Verified 13 independent exact destination sets against the Parquet, including 1-to-1 respective pairs (`454 -> 33:1233`, `455 -> 33:1234`, `456 -> 33:1235`, `457 -> 33:1236`), editorial omission (`111 -> Elim.`, codified at `19 U.S.C. § 288`), `466c -> 15:1824a`, `688 -> 46:30104, 30105`, `1300 -> 46:30701 note`, `72 -> 46:14503`, `75 -> 46:14512`, `845a`/`845b -> Rep.`, `1183a -> 46:53101 note`, and the 1988 LoC transfer-to-Appendix note (`uscode1988-018046000.pdf`).

## Title 49a 27-Section Hold-Out Audit Summary

See `title49a-holdout-audit.md` and `title49a-holdout-audit.json` for full
section-by-section adjudication against eight primary 1988 Title 49a chapter
PDFs (`uscode1988-019049a{001,004,006,008,009,013,020,026}.pdf`) and GovInfo
`USCODE-1994-title49.pdf`:

- **0 / 27** hold-out tokens appear as sections in the examined 1988 Title 49 Appendix PDFs; **0 / 27** are omissions from the 1994 Title 49 Disposition Table.
- **9 sections / 114 rows** (`411, 413, 415, 417, 419, 447, 449, 463, 465`) are current positive-law **Title 49 Subtitle VII chapter numbers** cited without `ch.`/`chapters` (correcting the earlier 14 CFR ch. III conjecture).
- **1 section / 5 rows** (`3102`) is pre-1994 positive-law `49 U.S.C. § 3102` (Pub. L. 97-449; renumbered `§ 31502` by Pub. L. 103-272), mislabelled `app`.
- **17 sections / 58 rows** are filer typos/truncations/parser damage (**9 / 24**: `374, 166, 1085, 10109, 40, 134 [uncertain], 406, 1491, 1763`), 49 CFR citations in the U.S.C. slot (**3 / 13**: `49 CFR 190`, `49 CFR 29`, and `49 CFR 21.7(a)` damaged to `49 U.S.C. 217(a)` between 2014-10 and 2015-04), lost-parenthesis pinpoints (**3 / 12**: `322(a)`, `1509(d)`, `114(l)`), or wrong-title U.S.C. citations (**2 / 9**: `5:552a(k)`, former `15:1392`).
- Raw 1988 OCR is **not** imported into `UscSectionOracle` (it would recover 0 of 177 rows).
