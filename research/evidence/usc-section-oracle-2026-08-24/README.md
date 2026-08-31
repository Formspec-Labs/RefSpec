# U.S.C. section-existence oracle — generation 2, 2026-08-24

Generation 2 of the six oracle tables first built on 2026-08-22
(`../usc-section-oracle-2026-08-22/`). One defect is corrected and nothing
else is changed: the annual-archive extractor's filename matcher was
case-sensitive, and OLRC named twelve annual title volumes with an uppercase
`USC`, so those twelve volumes were silently skipped.

Generation 1's directory is untouched and still the one `src/` reads; nothing
here is wired to the module, and re-pinning it is a later unit's work. The
raw source zips live under `output/usc-annual-2026-08-24/` (untracked, 2.3 GB)
and are **retained** this time — generation 1 deleted its own.

## The bug

`../usc-section-oracle-2026-08-22/scripts/extract_annual.py` selected the
title volumes out of each year's zip with

```python
FNAME = re.compile(r"(\d{4})/\1usc(\d+)([a-zA-Z]?)\.htm$")
```

`re.search` with no flags. Twelve members of the 1994–2024 archives spell
the middle literal `USC`, so `FNAME.search` returned `None` and the loop's
`continue` skipped them — no warning, no count, no failure. The consequence
is not a few missing sections: those twelve **(title, year) pairs got no
annual coverage at all**, so every citation to a section of that title filed
in that edition read `attested_at_edition = false` for the extractor's
reason rather than the law's.

The fix is `re.IGNORECASE`, plus a guard so a skip can never again be
silent: generation 2's extractor classifies **every** member of every year's
listing, writes the classification to
`output/usc-annual-2026-08-24/listing_<year>.tsv`, and raises if any member
matches neither the title-volume pattern nor the known non-title members.
The guard earned its keep on the first run: it stopped on `1994/usc.css` and
again on `2011/tbl112cd_2nd.htm`, both genuinely not title volumes, and the
allowlist now names them rather than letting a loose pattern swallow them.

### The twelve volumes, as the publisher lists them

Publisher columns are read out of OLRC's own per-year index pages (saved in
`../investigations-2026-08-24/inv-2012/`, re-read by
`scripts/publisher_index_rows.py`); member columns are the zip entries that
were actually extracted.

| publisher name | publisher size | publisher datetime | member bytes | member mtime |
|---|---:|---|---:|---|
| `2010USC12.htm` | 16,193 KB | 7/21/2011 15:46 | 16,580,678 | 2011-07-21T15:46:46 |
| `2010USC13.htm` | 349 KB | 7/21/2011 15:46 | 357,215 | 2011-07-21T15:46:52 |
| `2010USC14.htm` | 1,432 KB | 7/21/2011 15:46 | 1,466,350 | 2011-07-21T15:46:56 |
| `2010USC51.htm` | 1,196 KB | 8/1/2011 15:33 | 1,224,174 | 2011-08-01T15:33:08 |
| `2012USC33.htm` | 6,538 KB | 12/24/2013 10:19 | 6,694,674 | 2013-12-24T10:19:14 |
| `2012USC35.htm` | 1,292 KB | 12/24/2013 10:19 | 1,322,788 | 2013-12-24T10:19:30 |
| `2012USC36.htm` | 3,552 KB | 12/24/2013 10:19 | 3,636,318 | 2013-12-24T10:19:40 |
| `2012USC37.htm` | 2,349 KB | 12/24/2013 10:19 | 2,404,925 | 2013-12-24T10:19:48 |
| `2012USC38.htm` | 9,083 KB | 12/24/2013 10:19 | 9,300,152 | 2013-12-24T10:19:58 |
| `2012USC39.htm` | 1,106 KB | 12/24/2013 10:20 | 1,132,209 | 2013-12-24T10:20:04 |
| `2012USC40.htm` | 2,330 KB | 12/24/2013 10:20 | 2,384,959 | 2013-12-24T10:20:10 |
| `2012USC41.htm` | 1,395 KB | 12/24/2013 10:20 | 1,427,570 | 2013-12-24T10:20:16 |

**These twelve are the whole of it.** `evidence/skipped_by_generation_1.tsv`
applies generation 1's pattern to every member of all 31 zips: **1,835
members inspected, 1,769 matched by generation 1, 1,781 by generation 2, 12
title volumes silently skipped.** The other 54 unmatched members are not
title volumes in either generation — the year `index.html`, `usc.css`,
`uscPopularNames.htm`, `uscTable1`–`uscTable6`, and the 2011 archive's
`tbl112cd_2nd.htm` / `tbl112pl_2nd.htm`.

## Sources

All 32 zips were fetched keyless from uscode.house.gov on 2026-08-24 between
16:53 and 18:08 local, one at a time (`curl --http1.1 --retry 3`, one-second
pause between fetches) by `scripts/fetch_all.sh`;
`output/usc-annual-2026-08-24/fetch_log.tsv` records URL, byte length,
sha256, start, finish and seconds for every file.

**Every one of the 32 is byte-identical to generation 1's re-fetch digest
table** (`scripts/compare_source_digests.py`: 32 identical, 0 different, 0
unlisted). That matters for the proof below: generation 1 and generation 2
read the same bytes, so every difference between the two table sets is the
matcher and nothing else.

| file | bytes | sha256 | fetched (local) |
|---|---:|---|---|
| `xml_uscAll_119-102.zip` | 108,610,077 | `55c8d19543c4a972a33e33532b592ac3984c83fdcb04de9f5a64ef1f8483d300` | 2026-08-24T16:56:57 → 2026-08-24T17:01:00 |
| `1994.zip` | 52,880,472 | `dd3ab27c04f3da31becc82d13c5f368e758bd0c49ee1159be753bf6cd669daa6` | 2026-08-24T17:01:01 → 2026-08-24T17:01:49 |
| `1995.zip` | 54,120,393 | `0e77aa5b8cc7e832a8d8aa67ad323534d414771d4fda3e567f4d6c31a2e3a988` | 2026-08-24T17:01:50 → 2026-08-24T17:03:53 |
| `1996.zip` | 56,092,613 | `65dd5e5b669eed9aa6f3da1b6afb8c73ea2087ca25acc0454412739e0de826aa` | 2026-08-24T17:03:54 → 2026-08-24T17:04:30 |
| `1997.zip` | 57,149,119 | `7191b6e9a336efc79eecb7b54bc52c54eecfc77f953127337d92ebf5031445c7` | 2026-08-24T17:04:31 → 2026-08-24T17:05:22 |
| `1998.zip` | 58,640,448 | `1580feff9b815eca2408029f1cb677e62cc5bd02fcf61c1989f678d67939b342` | 2026-08-24T17:05:23 → 2026-08-24T17:05:55 |
| `1999.zip` | 59,325,611 | `dba96315628de3e45a2f1493101cbc12530142dfdbc1e379f3975bb9a97de36e` | 2026-08-24T17:05:56 → 2026-08-24T17:07:06 |
| `2000.zip` | 60,819,175 | `e78359bf706511397a9cb3d78d04774b72a7ac88c820e6fd367db3d7f8bb9cd8` | 2026-08-24T17:07:07 → 2026-08-24T17:07:46 |
| `2001.zip` | 61,642,483 | `234c33938773a449b762a2efc5d765c464615c79fb5dd6726167a59e901e4b1e` | 2026-08-24T17:07:47 → 2026-08-24T17:08:56 |
| `2002.zip` | 63,178,387 | `17c9c37572f4256a03784cb80967180d5c97aeef028c1881668375ce1da1da24` | 2026-08-24T17:08:57 → 2026-08-24T17:10:29 |
| `2003.zip` | 64,478,530 | `4b348690a3aafebc889301df5dc6af20c4f3eb437f7799751e400c57c7556574` | 2026-08-24T17:10:30 → 2026-08-24T17:12:13 |
| `2004.zip` | 64,849,199 | `86e5c99babb1b5f3c088e1fc09733cfe967aebfa4a50aab93c39174044a897ec` | 2026-08-24T17:12:14 → 2026-08-24T17:13:01 |
| `2005.zip` | 66,091,545 | `60904282ec038a80879564cb9a9b9342e327d685a6a6c2a61cddee6bf9735f0c` | 2026-08-24T17:13:03 → 2026-08-24T17:14:44 |
| `2006.zip` | 65,627,486 | `52fcb3b4dac9aa79f58a5cda42e45f56ebb5ea0f5f6b3d31a6aceb1695e6f23c` | 2026-08-24T17:14:45 → 2026-08-24T17:18:40 |
| `2007.zip` | 66,562,775 | `af15332853888bf9e6e0720b5421b7bf1105f88ab4e9d856730e5cde8c8ad901` | 2026-08-24T17:18:42 → 2026-08-24T17:27:12 |
| `2008.zip` | 68,750,323 | `14c042c98172392b11705448cb831c9405dfd85e6105d6f7ec7c4e09769d07a1` | 2026-08-24T17:27:13 → 2026-08-24T17:31:30 |
| `2009.zip` | 69,826,348 | `4b8b89ccafca96f0ba4dbb7422cd6dd0ab59cbcbdc67327bcb87dcc865000ad1` | 2026-08-24T17:31:31 → 2026-08-24T17:38:07 |
| `2010.zip` | 75,149,015 | `17452e0cb9429eeba94939b201ccd1fce3f1568f1000c7d30a39c99494d26242` | 2026-08-24T17:38:08 → 2026-08-24T17:40:31 |
| `2011.zip` | 72,593,935 | `56e6477499486358935f5e02f04e2ec53fd39cdc28e984556e2de5e188077442` | 2026-08-24T17:40:32 → 2026-08-24T17:42:01 |
| `2012.zip` | 76,756,483 | `797999856de311c9b13bb8f4237a74b8de67d706697d03d9b68f3ada20b70cc2` | 2026-08-24T16:53:44 → 2026-08-24T16:56:36 |
| `2013.zip` | 74,064,312 | `599f4638297ab9cece465b62597dcf40001dcc3e361183ea13a3c5a4bb4a1cd9` | 2026-08-24T17:42:02 → 2026-08-24T17:43:17 |
| `2014.zip` | 75,116,133 | `a4af2ca915b7714fde67527ac7b4b30eab7a180feaf114c6f7fa8d47d28a11df` | 2026-08-24T17:43:18 → 2026-08-24T17:44:25 |
| `2015.zip` | 76,463,260 | `97a113c069d9fef82da98466372a9d26108f9c6f0919710682b1c9b242bdad3d` | 2026-08-24T17:44:27 → 2026-08-24T17:45:54 |
| `2016.zip` | 76,647,752 | `3606b44d17b470123883fc96877b571b92c81163ed39d1976dbe86a39cf274f6` | 2026-08-24T17:45:56 → 2026-08-24T17:51:43 |
| `2017.zip` | 77,385,929 | `8069815cc49a9c75a78fab90743fd1433f78fd9e6a6ba6f4b9e03131576aaf11` | 2026-08-24T17:51:44 → 2026-08-24T17:54:26 |
| `2018.zip` | 79,110,459 | `6b5973b3a01a92ff91166313838bf0931e4837b76bfe637889257a99e8e0b0b3` | 2026-08-24T17:54:27 → 2026-08-24T17:57:11 |
| `2019.zip` | 79,870,874 | `8b069680e822c9d383c2d1a4491b88683a50dc07c11883a953b2255789121a53` | 2026-08-24T17:57:12 → 2026-08-24T17:59:32 |
| `2020.zip` | 82,838,922 | `52eb494924ea9cb8bbc9e9f2b6cd7a61c227519f8ef5ceb2f3136dcdd2fb98cc` | 2026-08-24T17:59:33 → 2026-08-24T18:01:23 |
| `2021.zip` | 83,961,907 | `b51e8b8af96475c9b160a236dc1c5f0c502c4a6f377ba04fe4fa83379e85d4bc` | 2026-08-24T18:01:25 → 2026-08-24T18:03:03 |
| `2022.zip` | 86,303,884 | `c4db549f3ec65d6fe6515e62329cf0cadc46dd1084e1b3758f871b0687493f38` | 2026-08-24T18:03:04 → 2026-08-24T18:05:10 |
| `2023.zip` | 86,847,107 | `034cb2c2f076338e57c18ba1435c3a6b8dcb40809da34d3196777ba171177bbc` | 2026-08-24T18:05:11 → 2026-08-24T18:06:34 |
| `2024.zip` | 87,797,571 | `2088ef2c9b292abee613245b6ecf3e8915aa88f663da3e17ebb146cc6003fb61` | 2026-08-24T18:06:36 → 2026-08-24T18:07:52 |

## Files

| file | sha256 | bytes | rows | what |
|---|---|---:|---:|---|
| `usc-oracle-sections.parquet` | `bbb450afb00cc7a28e2fcab7943d47207e8c1899f1e83209bd92d893fe39daac` | 303,565 | 59,364 | (title, section, status) from release point 119-102; 59,362 distinct (title, section). Unchanged from generation 1 row-for-row. |
| `usc-oracle-ranges.parquet` | `070226e36d324a15226bd84ce9f5e4a297b43ff83365dba37ed281d3186cd736` | 40,666 | 1,751 | (title, lo, hi, status, raw) — release-point stubs printed as `§§ 6 to 15a`, never expanded. Unchanged row-for-row. |
| `usc-oracle-annual-sections.parquet` | `4757327d2bbcd5258d0fc51f0658df7fc9999c21d5a40dbe0c2d466cf25e7323` | 7,594,553 | 1,572,225 | (year, title, appendix, section) for every annual edition 1994–2024; 67,022 distinct (title, appendix, section). **+7,218 rows over generation 1**, all in the twelve recovered volumes. |
| `usc-oracle-annual-ranges.parquet` | `c8cd96e1d13e4f429e1024f3a9fe25b8527036eae0adfd9ad29d9656522b43a3` | 178,394 | 49,960 | (year, title, appendix, lo, hi) — the `Secs. 6 to 15a` blocks per year; 1,885 distinct spans. **+137 rows**, all in (12, 2010) and (33, 2012). |
| `usc-oracle-subsections.parquet` | `d7502945223eed92bdeb65e6a73cf52240febefe9814180675fc4df512cd08ed` | 1,100,246 | 160,209 | (title, section, sub) from the release point, non-appendix titles only. Unchanged row-for-row. |
| `usc-oracle-chapters.parquet` | `031ae7f3435f7ba2969bdf2c94b699170a63fe3183dd289ca23fa0ce45e90cb3` | 11,668 | 2,905 | (title, chapter) from the release point, 53 titles. Unchanged row-for-row. |

Derived quantities, generation 2: **59,362** distinct release-point
`(title, section)` (status: current 50,957 / repealed 4,373 / transferred
1,841 / omitted 1,793 / renumbered 365 / vacant 18 / reserved 16 / unknown 1);
**67,022** distinct annual `(title, appendix, section)` = 66,007 non-appendix
+ 1,015 appendix; **1,885** distinct annual spans; **1,654** distinct
`(title, appendix, year)` pairs with annual coverage. The union used as the
existence test — release point ∪ non-appendix annual — is **66,780** pairs,
**unchanged from generation 1** (see (d) below).

## Derivation

`scripts/reproduce.sh` is the order. The six tables come from the same four
extractors generation 1 used. `extract_annual.py` differs by the matcher fix
and the guard; `extract_sections.py`, `extract_subsections.py` and
`extract_chapters.py` differ **only** in taking their working directory from
`$USC_WORK` instead of the hard-coded `/tmp/silent` (diff them against
generation 1's copies — every other line is identical).

Python 3.12.9, duckdb 1.4.4, pyarrow 21.0.0, macOS 26.6. The annual pass over
all 31 zips takes 100 s.

| script | produces |
|---|---|
| `scripts/fetch_all.sh` | the 32 source zips and `fetch_log.tsv` |
| `scripts/skipped_by_generation_1.py` | `evidence/skipped_by_generation_1.tsv` — the full listing |
| `scripts/extract_annual.py` | `usc-oracle-annual-sections`, `usc-oracle-annual-ranges` (**the fix**) |
| `scripts/extract_sections.py` | `usc-oracle-sections`, `usc-oracle-ranges` |
| `scripts/extract_subsections.py` | `usc-oracle-subsections` |
| `scripts/extract_chapters.py` | `usc-oracle-chapters` |
| `scripts/compare_source_digests.py` | this generation's sources against generation 1's table |
| `scripts/compare_generations.py` | `evidence/compare_generations.txt` — proofs (a)–(d) |
| `scripts/seeded_headings.py` | `evidence/seeded_headings.tsv` — 20 seeded sections read back out of the raw volumes |
| `scripts/would_flip.py` | `evidence/would_flip.txt`, `evidence/would_flip_rows.tsv` |
| `scripts/check_against_answer_key.py` | `evidence/answer_key_confusion.tsv` |
| `scripts/publisher_index_rows.py` | the publisher columns of the twelve-volume table above |
| `scripts/manifest.py` | `MANIFEST.tsv` |

## What changed, proved

`evidence/compare_generations.txt` is the full output.

**(a) The coverage matrix.** Annual sections: generation 1 covers 1,642
`(title, appendix, year)` pairs, generation 2 covers 1,654. **Gained: exactly
the twelve** — (12, 2010), (13, 2010), (14, 2010), (51, 2010), and (33, 35,
36, 37, 38, 39, 40, 41 at 2012), all non-appendix. **Lost: none.** Annual
ranges gain two pairs — (12, 2010) and (33, 2012) — because the other ten
recovered volumes print no `Secs. X to Y` stub at all.

**(b) What the recovered volumes print.** 7,218 new section rows and 137 new
range rows, per pair:

| title | year | sections | ranges |
|---:|---:|---:|---:|
| 12 | 2010 | 1,925 | 88 |
| 13 | 2010 | 65 | 0 |
| 14 | 2010 | 335 | 0 |
| 51 | 2010 | 234 | 0 |
| 33 | 2012 | 1,318 | 49 |
| 35 | 2012 | 167 | 0 |
| 36 | 2012 | 1,137 | 0 |
| 37 | 2012 | 202 | 0 |
| 38 | 2012 | 1,009 | 0 |
| 39 | 2012 | 166 | 0 |
| 40 | 2012 | 431 | 0 |
| 41 | 2012 | 229 | 0 |

Twenty seeded sections (`random.Random(20260824)`) read back out of the raw
`.htm` with the heading OLRC printed beside them are in
`evidence/seeded_headings.tsv` — e.g. 12 U.S.C. 1701z-2 "Advanced
technologies, methods, and materials for housing construction,
rehabilitation, and maintenance"; 33 U.S.C. 449 "Disposition of dredged
matter; persons liable; penalty"; 35 U.S.C. 271 "Infringement of patent";
38 U.S.C. 7307 "Office of Research Oversight". Every one is a real section of
the right title, and two of the twenty are the repeal stubs the extractor is
meant to keep as printed (33 U.S.C. 763c, 855).

**(c) Nothing else moved.** Every `(title, appendix, year)` pair outside the
twelve was compared both ways: **1,642 pairs of annual sections and 749 pairs
of annual ranges, md5 of the sorted row set identical on all of them, and
`EXCEPT` in both directions returning 0 rows.** Not a single row outside the
recovered volumes differs.

**(d) The release-point tables and the enumerated set do not change at all.**

| table | generation 1 rows | generation 2 rows | only in 1 | only in 2 |
|---|---:|---:|---:|---:|
| `usc-oracle-sections` | 59,364 | 59,364 | 0 | 0 |
| `usc-oracle-ranges` | 1,751 | 1,751 | 0 | 0 |
| `usc-oracle-subsections` | 160,209 | 160,209 | 0 | 0 |
| `usc-oracle-chapters` | 2,905 | 2,905 | 0 | 0 |

They are cut from the release-point zip, which the matcher never touched, and
they reproduce row-for-row. The **enumerated** set the module derives —
release point ∪ non-appendix annual, the only set a correction candidate may
be tested against — is **66,780 in both generations, delta 0**: *no section
appears only in a skipped volume.* Distinct annual `(title, appendix,
section)` is likewise 67,022 in both. **So the fix cannot change a single
`verdict`; it changes only `attested_at_edition`, the year-scoped question.**
That is the sharpest statement of the blast radius, and it is measured, not
assumed.

## What it is worth to the consumer

Read-only against the pinned build
`output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet`
(rebuild #11, 799,127 rows), `scripts/would_flip.py` asks the module's own
`section_verdict` twice — once against generation 1 as pinned, once against an
oracle whose two annual tables are generation 2's — and compares.

Harness check first: recomputing under generation 1 returns the column the
build already wrote on **8,258 of 8,258** rows, so the question being asked is
the build's own.

* **1,881 of the 8,258** `usc` rows reading `exists` /
  `attested_at_edition = false` would read `true`. 6,377 stay. **Zero rows
  change in any other way.**
* **16 act-derived rows** (`authority_type = 'act_relative'`, RINs 2040-AE69
  and 2040-AE95, all CWA at edition `201210`) name title 33 sections the 2012
  volume prints; they carry no verdict in this build, and the oracle's answer
  for them moves from `false` to `true`.

| title | edition | rows | RINs | texts |
|---:|---:|---:|---:|---:|
| 12 | 2010 | 1,367 | 216 | 338 |
| 38 | 2012 | 140 | 82 | 77 |
| 33 | 2012 | 133 | 66 | 63 |
| 35 | 2012 | 86 | 40 | 27 |
| 40 | 2012 | 72 | 69 | 10 |
| 41 | 2012 | 66 | 60 | 10 |
| 13 | 2010 | 10 | 5 | 5 |
| 14 | 2010 | 5 | 2 | 3 |
| 39 | 2012 | 2 | 2 | 2 |

The full list is `evidence/would_flip_rows.tsv`; twenty seeded rows with
their RIN, edition and citation text are in `evidence/would_flip.txt`.

**Against the investigation's hand-bucketed answer key**
(`../investigations-2026-08-24/inv-2012/exists_not_attested_8258_bucketed.csv`,
which classified all 8,258 rows by eye): generation 2 flips every
`1-case-bug-high-confidence` key (1,355 distinct keys) and **not one** key
from `2-case-bug-uncertain` (28), `3-future-edition-beyond-2024` (23) or
`4-genuine-era-mismatch` (3,869); no flip falls outside the key. The 30 rows
the investigation marked uncertain are titles 40 and 41 at 2012 cited by
their **pre-recodification** numbers — 40 U.S.C. 276c, 322, 333, 484, 486 and
41 U.S.C. 46, 253, 414, 418b, 421–423, 431, 701 — and the recovered 2012
volumes do not print them (checked by eye in the raw `.htm`: title 40's 2012
volume prints §101 and §3141, not §276c). The volume existing and the section
existing are different facts, and generation 2 keeps them apart.

## What the module switch must change (not done here)

The switch is the next unit's. What it must move:

* `src/refspec/registry/usc_section_oracle.py`
  * `USC_SECTION_ORACLE_ARTIFACT` → `"research/evidence/usc-section-oracle-2026-08-24"`
  * all six digests in `_ORACLE_PINS` → the Files table above
  * docstring counts that move: annual rows 1,565,007 → **1,572,225**,
    annual range rows 49,823 → **49,960**. The counts that do **not** move:
    66,780, 67,022, 66,007, 1,015, 59,362, 59,364, 1,751, 160,209, 2,905,
    1,885.
* `src/refspec/registry/citation_grammar.py` — the artifact path in three
  comments (≈ lines 1782–1784, 1854, 2554) and the same two row counts.
* `src/refspec/registry/unified_agenda_parquet.py` ≈ line 7487 — cites 66,780,
  which does not move.
* `tools/build_registry_source_manifest.py` ≈ lines 1343, 1358 — the README
  path, and the "zips were deleted" wording, which is no longer true of
  generation 2: `output/usc-annual-2026-08-24/` retains all 32.
* `tests/test_citation_grammar.py` — the artifact path at lines 53 and 2954
  and the counts at 2949–2950.
* `tests/test_usc_section_oracle.py` — `ORACLE_DIR` follows
  `USC_SECTION_ORACLE_ARTIFACT`, so `SNAPSHOT`
  (`agenda-legal-authorities-as-measured-797170.parquet`) and
  `SNAPSHOT_DIGEST` will point into a directory that does not carry it.
  **Decide deliberately**: either keep the snapshot lookup anchored on
  generation 1 (it is generation 1's measurement, and this directory is not a
  re-measurement of the corpus), or copy the snapshot here. This unit did
  neither.

Any corpus-count test that asserts `attested_at_edition` totals will move by
the 1,881 rows above; nothing that asserts a `verdict` should move at all.
