# U.S.C. section-existence oracle — 2026-08-22

Pinned derived artifact behind `../usc-section-oracle-2026-08-22.md`: the
oracle that answers "does U.S.C. title T section S exist, and when", the
corpus side it was joined to, the per-pair verdicts, and every script that
produced them. Built 2026-08-22. Nothing here is under `src/`, `tests/` or
`output/`; nothing was modified after measurement.

## Sources

Both from the Office of the Law Revision Counsel (uscode.house.gov),
downloaded 2026-08-22 between 17:10 and 17:40 local.

| source | URL | bytes |
|---|---|---:|
| current release point 119-102, USLM XML, all titles | `https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_uscAll@119-102.zip` | 108,610,077 |
| annual historical archive, XHTML, one zip per year 1994–2024 | `https://uscode.house.gov/download/annualhistoricalarchives/XHTML/<YEAR>.zip` | see table below |

The release-point zip holds 58 files `usc01.xml … usc54.xml` (plus the
appendix files `usc05A`, `usc11a`, `usc18a`, `usc28a`, `usc50A`), each dated
2026-07-23 inside the archive. The annual zips hold `YYYY/YYYYuscNN.htm` and
`YYYY/YYYYuscNNa.htm` for the titles that had an appendix that year; **no
year has a `usc49a.htm`**, which is the Title 49 Appendix gap the report
carries as class C9.

**The source zips were deleted after extraction, before any digest was
taken.** Byte lengths of the files actually used, as logged by `curl -w` at
download time:

| year | bytes | year | bytes | year | bytes |
|---|---:|---|---:|---|---:|
| 1994 | 52,880,472 | 2005 | 66,091,545 | 2016 | 76,647,752 |
| 1995 | 54,120,393 | 2006 | 65,627,486 | 2017 | 77,385,929 |
| 1996 | 56,092,613 | 2007 | 66,562,775 | 2018 | 79,110,459 |
| 1997 | 57,149,119 | 2008 | 68,750,323 | 2019 | 79,870,874 |
| 1998 | 58,640,448 | 2009 | 69,826,348 | 2020 | 82,838,922 |
| 1999 | 59,325,611 | 2010 | 75,149,015 | 2021 | 83,961,907 |
| 2000 | 60,819,175 | 2011 | 72,593,935 | 2022 | 86,303,884 |
| 2001 | 61,642,483 | 2012 | 76,756,483 | 2023 | 86,847,107 |
| 2002 | 63,178,387 | 2013 | 74,064,312 | 2024 | 87,797,571 |
| 2003 | 64,478,530 | 2014 | 75,116,133 | | |
| 2004 | 64,849,199 | 2015 | 76,463,260 | | |

(2007 and 2017 first arrived truncated — 752,808 and 11,383,832 bytes, HTTP/2
stream cancelled — and were re-fetched with `--http1.1` before extraction;
the lengths above are the files that were extracted.)

### Re-fetch and reproduction check

See the section **"Re-fetched source digests"** at the end of this file. It
records, for each zip, the sha256 of a fresh download from the same URL made
after the coordinator asked for pinning, whether its byte length matches the
logged length above, and whether running the committed scripts on the
re-fetched zips reproduces the committed parquets row-for-row.

## The artifact under measurement

`agenda-legal-authorities-as-measured-797170.parquet` is a byte-identical
copy of
`output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet`
as it stood at 17:44 on 2026-08-22, after the mid-campaign rebuild: 797,170
rows, 42,642 distinct `authority_text`, 46,547 RINs, 60 editions. The build's
own `receipt.json` declares
`outputs.unified_agenda_legal_authorities = sha256:c5c4bd1f8b70fd52491f8b22e7bc72c75287cbbf3638692210fd1691731c7424`
— the same digest as the copy here — with `legalAuthorities = 797170` and
schema `exploded-v3`; it does not name a producing commit, and HEAD of the
checkout at 17:59 was `cc9c5cbd`. **Every count in the report is this file.** The
campaign's own report used the 798,114-row build preserved as
`../silent-misreads-2026-08-22/agenda-legal-authorities-as-measured.parquet`;
the rebuild removed 995 rows citing 18 U.S.C. 1984/1987 (the date-year
phantom) and nothing else that the U.S.C. reader sees.

## Files

| file | sha256 | bytes | rows | what |
|---|---|---:|---:|---|
| `usc-oracle-sections.parquet` | `f4b11c6e4ccbaa6ccf2aa0f4940d514b3a0285c6ec1b8f1352ea25b8a9a1bf1d` | 303,380 | 59,364 | (title, section, status) from the release point; 59,362 distinct (title, section) — 10 U.S.C. 2891 and 2892 carry both `current` and `repealed`. Status: current 50,957 / repealed 4,373 / transferred 1,841 / omitted 1,793 / renumbered 365 / vacant 18 / reserved 16 / unknown 1. |
| `usc-oracle-ranges.parquet` | `0808cbbff5f456d36daa4a45f3996b911bff7a98f36130150ed7600a255883d6` | 40,723 | 1,751 | (title, lo, hi, status, raw) — release-point stubs printed as `§§ 6 to 15a`, never expanded. |
| `usc-oracle-annual-sections.parquet` | `9ab9f43c23367910662f7a31ef140f573b138430c51c3c63fe141f6a4b984370` | 7,213,598 | 1,565,007 | (year, title, appendix, section) for every annual edition 1994–2024; 67,022 distinct (title, appendix, section): 66,007 non-appendix + 1,015 appendix. |
| `usc-oracle-annual-ranges.parquet` | `caa9d3819dc6b49fdb68442c0e5be4773e84af99833437eb8f662da9aae2fde9` | 177,589 | 49,823 | (year, title, appendix, lo, hi) — the `Secs. 6 to 15a` blocks per year; 1,885 distinct spans. |
| `usc-oracle-subsections.parquet` | `c412340820bb65f957c34d24a0124f78abfce1dc30b95773767af03472096f22` | 1,094,598 | 160,209 | (title, section, sub) from the release point, non-appendix titles only; 35,133 sections have at least one. |
| `usc-oracle-chapters.parquet` | `4fbd6ba386bee9d0a55f68e5072be60e6eaa0222719974eadcb842e345212f95` | 11,713 | 2,905 | (title, chapter) from the release point, 53 titles. |
| `corpus-usc-pairs.parquet` | `e5df7a83cc7d3feac6dcdfbec0f8318976f6761d4d29efc58d540baa6e277f86` | 118,747 | 11,124 | every distinct parsed (title, section, appendix) in the artifact with rows / texts / RINs / first and last edition; sums to 685,431 rows. |
| `agenda-legal-authorities-as-measured-797170.parquet` | `c5c4bd1f8b70fd52491f8b22e7bc72c75287cbbf3638692210fd1691731c7424` | 4,929,519 | 797,170 | the build measured (see above). |
| `triage.json` | `1bb3d12e1144abfe8a64038811f0c5b7838399fc24fdce5304f88c0cff74db3e` | 546,344 | 1,728 | one record per nonexistent pair: class C0–C12, proposed fix, why, up to four verbatim specimens with row counts. |
| `sibling.json` | `835595f04b15b10014e14948ec4697cef7c3ada058dcf8987dfa1cf503d6a6c2` | 128,528 | 498 | C11/C12 pairs for which the corpus states the same string with a real section token substituted. |

The existence test used by the report is the union of
`usc-oracle-sections` ∪ `usc-oracle-annual-sections` (non-appendix) plus span
membership in either ranges file: **66,780 distinct non-appendix (title,
section)**. Dashes in every section token are normalised with the grammar's
`_DASHES` table (`‐‑‒–—―−` and `\x96\x97` → `-`) because OLRC identifiers use
U+2013; without that, `1395w-4`-style names read as nonexistent.

### Five of these files are also in `../silent-misreads-2026-08-22/`

`usc-oracle-sections`, `usc-oracle-ranges`, `usc-oracle-annual-ranges`,
`usc-oracle-chapters`, `usc-oracle-subsections` were copied there by the
campaign before this directory existed; they are byte-identical (same
sha256). `usc-oracle-annual-sections.parquet` — the 7.2 MB file that
carries most of the existence test — the corpus pairs, the verdicts and the
scripts exist only here. That README also says the subsection oracle came
from "annual U.S.C. XML"; it came from the release point, see
`scripts/extract_subsections.py`.

## Scripts

All paths inside the scripts are the `/tmp/silent/` working paths they were
run with; `scripts/reproduce.sh` lists the order. Python 3 with `duckdb`
1.4.4; DuckDB CLI 1.x at `/opt/homebrew/bin/duckdb`.

| script | sha256 | bytes | produces |
|---|---|---:|---|
| `scripts/extract_sections.py` | `39a63381d9969adf6a9541e12e05c9df4acfd27419c71768edc8465de5b82826` | 3,082 | `usc-oracle-sections`, `usc-oracle-ranges` from the release-point zip. Run twice: the second run after adding the `_DASHES` translate (the committed file is the second version). |
| `scripts/extract_annual.py` | `d010e3c85191b2c3ac8f652b7bb1b4da9dcf3c0cee679d770fe89f31224feffa` | 3,037 | `usc-oracle-annual-sections`, `usc-oracle-annual-ranges` from the 31 annual zips (`YEARS = range(1994, 2025)`). |
| `scripts/extract_subsections.py` | `6fa302ffb47a003586cc650710abcdc1bc62d519fa816cf98a95c8692644daf5` | 1,613 | `usc-oracle-subsections`. Was run as an inline heredoc; this is that heredoc verbatim, written to disk at the coordinator's request. |
| `scripts/extract_chapters.py` | `5f00c329ca2a8e89c43230a1daa4dd55551fc1017ed956e09d2150cec6ff3eb2` | 1,914 | `usc-oracle-chapters`. Likewise a heredoc, written to disk now. |
| `scripts/corpus_pairs.sql` | `6740d1dd296f2bd51f6b9a53226f824b39cd2ef41178e5c54cc735dcad63ede2` | 1,051 | `corpus-usc-pairs` from the agenda snapshot. |
| `scripts/join.sql` | `999f8c00c5e6b9e1628f0d3fff73c96c207a5b84bf65c5e6dace11fce06ab639` | 2,082 | the working DB (`verdict2`): every corpus pair with its existence verdict. |
| `scripts/rows_and_headline.sql` | `98a45ed711a21f719a329d5393f552c3f7b0dba65afdf9885ef4747162d6824b` | 2,111 | `rowsv` (row-level join) and the headline counts, with the expected numbers in comments. |
| `scripts/triage.py` | `64fe371bfc20b893cd2ffd1f40c4a634dc8c3ae26dadd9f40bdfea80eaed975c` | 10,611 | `triage.json`; the C0–C12 predicates in code. Final of several iterations — the committed file is the one that produced the committed JSON. |
| `scripts/sibling.py` | `92a999513a76419f84ebcb6d9bcdf15427776cc0d43dbc26b085a9af4ba8326a` | 3,505 | `sibling.json`. |
| `scripts/summarize_triage.py` | `07d2dc3851a106b18d9e9fa930fa83dbe4b48279c9d9c60478d2d5e2b3bec890` | 2,313 | the per-class table and the A/B/C group table in the report (two heredocs, written to disk now). |
| `scripts/reverse_test.sql` | `73f223150bea194802e2a2d3d8ea93baba5d69e46eafafa06d4960a1b55717f5` | 1,315 | the `NN U.S. XXX` reverse test. |
| `scripts/nearmiss_firstpass.py` | `fb37074ec888b5c46727d796010c7627826e4518ea423051e037987bccebc34d` | 4,722 | the first-pass near-miss scan (`usc_nearmiss.json`, not committed: it was computed against the pre-rebuild working DB and is superseded by `triage.py`). |
| `scripts/reproduce.sh` | `6566d5428c751de5f8b4d780efd65fd365853805c77b43421ce34c6be71d1f5b` | 1,804 | the run order. |

Not committed: the DuckDB working database (`/tmp/silent/usc.duckdb`, 33 MB,
entirely re-derivable from the files here via `join.sql` and
`rows_and_headline.sql`).

## Re-fetched source digests

All 32 zips were fetched a second time from the same URLs on 2026-08-22
between 18:16 and 18:45 local (`curl --http1.1 --retry 3`). **Every
re-fetched file has exactly the byte length logged for the file that was
extracted** (the table above), so these digests are the best available
identity for the sources used; they are digests of the re-fetched bytes, not
of the deleted originals, and a server-side regeneration that preserved
length would not be detected by length alone. The row-for-row reproduction
check in the next section is what closes that gap.

| file | sha256 | bytes |
|---|---|---:|
| `xml_uscAll@119-102.zip` | `55c8d19543c4a972a33e33532b592ac3984c83fdcb04de9f5a64ef1f8483d300` | 108,610,077 |
| `1994.zip` | `dd3ab27c04f3da31becc82d13c5f368e758bd0c49ee1159be753bf6cd669daa6` | 52,880,472 |
| `1995.zip` | `0e77aa5b8cc7e832a8d8aa67ad323534d414771d4fda3e567f4d6c31a2e3a988` | 54,120,393 |
| `1996.zip` | `65dd5e5b669eed9aa6f3da1b6afb8c73ea2087ca25acc0454412739e0de826aa` | 56,092,613 |
| `1997.zip` | `7191b6e9a336efc79eecb7b54bc52c54eecfc77f953127337d92ebf5031445c7` | 57,149,119 |
| `1998.zip` | `1580feff9b815eca2408029f1cb677e62cc5bd02fcf61c1989f678d67939b342` | 58,640,448 |
| `1999.zip` | `dba96315628de3e45a2f1493101cbc12530142dfdbc1e379f3975bb9a97de36e` | 59,325,611 |
| `2000.zip` | `e78359bf706511397a9cb3d78d04774b72a7ac88c820e6fd367db3d7f8bb9cd8` | 60,819,175 |
| `2001.zip` | `234c33938773a449b762a2efc5d765c464615c79fb5dd6726167a59e901e4b1e` | 61,642,483 |
| `2002.zip` | `17c9c37572f4256a03784cb80967180d5c97aeef028c1881668375ce1da1da24` | 63,178,387 |
| `2003.zip` | `4b348690a3aafebc889301df5dc6af20c4f3eb437f7799751e400c57c7556574` | 64,478,530 |
| `2004.zip` | `86e5c99babb1b5f3c088e1fc09733cfe967aebfa4a50aab93c39174044a897ec` | 64,849,199 |
| `2005.zip` | `60904282ec038a80879564cb9a9b9342e327d685a6a6c2a61cddee6bf9735f0c` | 66,091,545 |
| `2006.zip` | `52fcb3b4dac9aa79f58a5cda42e45f56ebb5ea0f5f6b3d31a6aceb1695e6f23c` | 65,627,486 |
| `2007.zip` | `af15332853888bf9e6e0720b5421b7bf1105f88ab4e9d856730e5cde8c8ad901` | 66,562,775 |
| `2008.zip` | `14c042c98172392b11705448cb831c9405dfd85e6105d6f7ec7c4e09769d07a1` | 68,750,323 |
| `2009.zip` | `4b8b89ccafca96f0ba4dbb7422cd6dd0ab59cbcbdc67327bcb87dcc865000ad1` | 69,826,348 |
| `2010.zip` | `17452e0cb9429eeba94939b201ccd1fce3f1568f1000c7d30a39c99494d26242` | 75,149,015 |
| `2011.zip` | `56e6477499486358935f5e02f04e2ec53fd39cdc28e984556e2de5e188077442` | 72,593,935 |
| `2012.zip` | `797999856de311c9b13bb8f4237a74b8de67d706697d03d9b68f3ada20b70cc2` | 76,756,483 |
| `2013.zip` | `599f4638297ab9cece465b62597dcf40001dcc3e361183ea13a3c5a4bb4a1cd9` | 74,064,312 |
| `2014.zip` | `a4af2ca915b7714fde67527ac7b4b30eab7a180feaf114c6f7fa8d47d28a11df` | 75,116,133 |
| `2015.zip` | `97a113c069d9fef82da98466372a9d26108f9c6f0919710682b1c9b242bdad3d` | 76,463,260 |
| `2016.zip` | `3606b44d17b470123883fc96877b571b92c81163ed39d1976dbe86a39cf274f6` | 76,647,752 |
| `2017.zip` | `8069815cc49a9c75a78fab90743fd1433f78fd9e6a6ba6f4b9e03131576aaf11` | 77,385,929 |
| `2018.zip` | `6b5973b3a01a92ff91166313838bf0931e4837b76bfe637889257a99e8e0b0b3` | 79,110,459 |
| `2019.zip` | `8b069680e822c9d383c2d1a4491b88683a50dc07c11883a953b2255789121a53` | 79,870,874 |
| `2020.zip` | `52eb494924ea9cb8bbc9e9f2b6cd7a61c227519f8ef5ceb2f3136dcdd2fb98cc` | 82,838,922 |
| `2021.zip` | `b51e8b8af96475c9b160a236dc1c5f0c502c4a6f377ba04fe4fa83379e85d4bc` | 83,961,907 |
| `2022.zip` | `c4db549f3ec65d6fe6515e62329cf0cadc46dd1084e1b3758f871b0687493f38` | 86,303,884 |
| `2023.zip` | `034cb2c2f076338e57c18ba1435c3a6b8dcb40809da34d3196777ba171177bbc` | 86,847,107 |
| `2024.zip` | `2088ef2c9b292abee613245b6ecf3e8915aa88f663da3e17ebb146cc6003fb61` | 87,797,571 |

The annual archives are not frozen on the publisher's side — the 2024 zip's
members carry modification dates from 2025-03-14 to 2026-04-09 — so a future
fetch of the same URL may legitimately differ; compare against this table
before trusting a re-derivation.

## Reproduction check

Done 2026-08-22 23:16–23:18 local. The four extraction scripts were run
verbatim from `scripts/` (hard links put the re-fetched zips at the
`/tmp/silent/` paths the scripts name) and their outputs compared with the
committed parquets by `EXCEPT` in both directions:

| oracle | committed rows | regenerated rows | only in committed | only in regenerated | bytes identical |
|---|---:|---:|---:|---:|---|
| `usc-oracle-sections` | 59,364 | 59,364 | 0 | 0 | no (303,380 vs 303,546) |
| `usc-oracle-ranges` | 1,751 | 1,751 | 0 | 0 | no (40,723 vs 40,553) |
| `usc-oracle-annual-sections` | 1,565,007 | 1,565,007 | 0 | 0 | no (7,213,598 vs 7,886,673) |
| `usc-oracle-annual-ranges` | 49,823 | 49,823 | 0 | 0 | no (177,589 vs 177,660) |
| `usc-oracle-subsections` | 160,209 | 160,209 | 0 | 0 | no (1,094,598 vs 953,114) |
| `usc-oracle-chapters` | 2,905 | 2,905 | 0 | 0 | no (11,713 vs 11,641) |

**Every oracle reproduces row-for-row** from the digested sources with the
committed scripts; the per-title and per-year progress counts printed by the
scripts were also identical to the original run. Byte identity is not
expected and not claimed: the scripts accumulate into Python sets and insert
in set order, so Parquet row order and therefore encoding differ between
runs. The committed files are the originals; the sha256 values in the Files
table above identify them. The regenerated copies were discarded.

Not re-run: `corpus_pairs.sql`, `join.sql`, `triage.py`, `sibling.py` — their
inputs (the oracles just verified and the byte-identical agenda snapshot)
are fixed, and their outputs are committed as produced.
