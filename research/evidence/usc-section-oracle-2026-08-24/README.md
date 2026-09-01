# U.S.C. section-existence oracle — generation 2, 2026-08-24

Generation 2 of the six oracle tables first built on 2026-08-22
(`../usc-section-oracle-2026-08-22/`). One defect is corrected and nothing
else is changed: the annual-archive extractor's filename matcher was
case-sensitive, and OLRC named twelve annual title volumes with an uppercase
`USC`, so those twelve volumes were silently skipped.

**These six tables are the ones `src/` reads.** `USC_SECTION_ORACLE_ARTIFACT`
and all six `_ORACLE_PINS` digests in
`src/refspec/registry/usc_section_oracle.py` name this directory as of
2026-08-31 — see "The module switch" at the foot of this file. Generation 1's
directory is untouched and still holds the corpus snapshot the tests measure
over (`agenda-legal-authorities-as-measured-797170.parquet`), which stays there
deliberately. The raw source zips live under `output/usc-annual-2026-08-24/`
(untracked, 2.1 GB on disk) and are **retained** this time — generation 1
deleted its own.

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

Re-verified independently of this table on 2026-08-31, straight out of the 31
zips with `zipfile` and the two patterns: **1,835 members, 1,769 matched
case-sensitively, 1,781 case-insensitively, exactly the twelve above in the
difference**, and no other member of any year carries an uppercase `USC`
anywhere in its name.

### The sibling extractors: audited, defect absent, deliberately unchanged

The same case-sensitive `usc` literal is in the three release-point
extractors — `extract_sections.py` (`re.fullmatch(r"usc\d+[A-Za-z]?\.xml", n)`)
and `extract_chapters.py` / `extract_subsections.py`
(`re.fullmatch(r"usc\d+\.xml", n)`). Measured against the actual input, the
defect has **zero members**: `xml_uscAll_119-102.zip` holds 58 files,
`usc01.xml` … `usc54.xml` plus `usc05A.xml` and `usc50A.xml`, and every one
spells `usc` in lower case. Both patterns match the same files with and
without `re.IGNORECASE` — **58 and 58** for the sections extractor, **53 and
53** for the two that deliberately skip the appendix titles.

So the matcher is left alone in all three. Breaking a true, checkable statement
to fix a defect with no members is a bad trade. What would change the answer
is a re-cut from a **different** release point, and that is a new generation
with its own reproduction check, not a patch to this one.

They are **not** byte-identical to generation 1's copies, and an earlier
revision of this file said they were. They differ in one respect and only one,
introduced at `797401ec`: generation 1 hard-coded `/tmp/silent` as its working
directory and these take it from `$USC_WORK` (defaulting to
`output/usc-annual-2026-08-24`), which is three added lines plus the paths in
the `zipfile.ZipFile(...)` and `COPY ... TO ...` calls and their docstrings.
`diff` them against generation 1's copies and that is the whole delta — no
change to any pattern, any parse, or any emitted column. The Derivation section
below states the claim in that form.

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
extractors generation 1 used. `extract_annual.py` differs by the matcher fix,
the guard, and (2026-08-31) a docstring that states the bracketed-stub
exclusion below; `extract_sections.py`, `extract_subsections.py` and
`extract_chapters.py` differ **only** in taking their working directory from
`$USC_WORK` instead of the hard-coded `/tmp/silent` — diff them against
generation 1's copies and every line outside that substitution is identical.

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

## Bracketed stubs: excluded on purpose, adjudicated 2026-08-31

`scripts/extract_annual.py` used to claim, without qualification, that
"repealed/omitted blocks are retained". That was true of one form and false of
another, and the review that caught it was right to call the sentence a defect.
This section is the adjudication, and the decision is **exclude, deliberately,
and say so.**

### What OLRC actually prints

Two forms, and the archives distinguish them everywhere:

| | unbracketed | bracketed |
|---|---|---|
| itempath | `/020/CHAPTER 1/Secs. 3, 4` | `/400/…/SUBCHAPTER III/[Sec. 322` |
| heading | `§§3, 4. Omitted` | `[§322. Repealed. Pub. L. 109–313, §3(h)(1), Oct. 6, 2006, 120 Stat. 1736]` |
| documentid | `2_3,_4` | `40_[322` |
| usckey | `020000000000300000000000000000000` | `400000000000000000000000000000000` |
| in these tables | **yes** | **no** |

The unbracketed form is kept and always was: the 2012 volumes alone carry
**1,544 unbracketed `repealedhead` and 596 unbracketed `omittedhead`**
multi-section blocks, all of them in the output as ranges or lists. What the
old sentence omitted is the bracketed form, which the `Secs?\.` matcher's
start-anchor drops: **33,895 section rows and 4,450 range rows across
1994–2024, 33,848 of the section rows reaching no other year or form.** Their
kinds, counted over all 31 archives: 30,167 repealed, 4,939 renumbered, 569
vacant, 464 omitted, 62 reserved, 60 transferred, and ~2,000 abrogated Rules
and Forms in the appendix titles.

### The line is the publisher's, not ours

Every entry carries a `usckey` beside its `itempath`, and **for a bracketed
heading the section field of that key is zeroed.** Read straight out of
`2012/2012USC40.htm`, four lines apart:

```
<!-- documentid:40_[322  usckey:400000000000000000000000000000000 currentthrough:20130115 -->
<!-- itempath:/400/SUBTITLE I/CHAPTER 3/SUBCHAPTER III/[Sec. 322 -->
<h3 class="section-head">[&sect;322. Repealed. Pub. L. 109&ndash;313, &sect;3(h)(1), Oct. 6, 2006, 120 Stat. 1736]</h3>
...
<!-- documentid:40_323  usckey:400000000032300000000000000000000 currentthrough:20130115 -->
<!-- itempath:/400/SUBTITLE I/CHAPTER 3/SUBCHAPTER III/Sec. 323 -->
<h3 class="section-head">&sect;323. Consumer Information Center Fund</h3>
```

Cross-tabulated over all 31 archives, every non-appendix entry whose itempath
parses as a section:

| bracketed | usckey section field | entries |
|---|---|---:|
| no | set | 1,585,628 |
| no | zeroed | 1,853 |
| no | absent | 202 |
| **yes** | **zeroed** | **35,088** |
| yes | set | 0 |

**35,088 of 35,088, no exception.** (The 1,853 unbracketed-and-zeroed are one
corrupt file, `1994usc20.htm`, whose bytes carry a stray `\x1a` where `§`
belongs; the `TOKEN` pattern rejects them anyway and none reaches the tables.)
So OLRC itself declines to mint a Code identity for a bracketed heading, and
this extractor follows it: **what the annual tables attest is what the edition
printed as live law.**

### What including them would do, measured

Rebuilt with brackets admitted and re-asked of the module's own
`section_verdict` over rebuild #12:

| quantity | as shipped | with brackets |
|---|---:|---:|
| annual section rows | 1,572,225 | 1,606,073 |
| distinct annual `(title, appendix, section)` | 67,022 | 67,763 |
| distinct annual spans | 1,885 | 2,115 |
| `enumerated` (the existence union) | 66,780 | 67,105 |
| attestation movements over the 694,062 addressed rows | — | 3,085, all `false` → `true` |
| **verdict** movements | — | **19, all `absent` → `exists`** |
| `usc` rows reading exists / unattested | 6,379 | 3,313 |

Splitting the two halves is what decides it. Admitting the bracketed **section**
rows alone moves 2,280 attestations and **no** verdict. Admitting the bracketed
**ranges** moves 805 attestations and **all 19** verdicts — and all 19 are one
pair:

```
1651-AA65  200510…200810   6 USC 1                                     (7 rows)
1615-AB99  201210, 201304  PL 107-296, 116 Stat 2135 (6 USC 1 et seq)  (2 rows)
1651-AA96  201210…201704   6 USC 1 et seq / 6 U.S.C. 1 et seq.        (10 rows)
```

6 U.S.C. 1's only witness anywhere in the Code is, in `1994/1994usc06.htm`:

```
<!-- expcite:TITLE 6-SURETY BONDS [REPEALED]!@![Secs. 1 to 5 -->
<h3 class="section-head">[&sect;&sect;1 to 5. Repealed. Pub. L. 92&ndash;310, title II, &sect;203(1), June 6, 1972, 86 Stat. 202]</h3>
```

— a 1972 repeal stub, printed 1994–2001 only, in a title Congress abolished and
then reused. The rows citing it are 2005–2017 and one of them names its own
statute: **Pub. L. 107-296 is the Homeland Security Act of 2002**, classified
beginning at **6 U.S.C. 101**, which the release point prints as `current` and
the archives attest from 2002. Calling those rows `exists` would be the oracle
affirming a citation on the strength of an abolished title's repeal stub — the
silent misread this whole module is the fence against — and it would delete the
honest hedge they carry today: `absent` with `ABSENT_CAVEATS =
("repealed_before_1994_not_stubbed",)`, which is precisely their situation.
Nothing downstream would catch it either: `UscDispositionTables` has no table
for title 6 at all (`verdict='no-table-for-title'`).

So the bracket means the same thing in `[Sec. 322` and `[Secs. 1 to 5`, and
splitting on which half happens to produce a wrong verdict would be choosing on
convenience. Both are excluded, on the same ground.

### What it costs, named

**40 U.S.C. 322 reads `attested_at_edition = false` at edition 2012 although
the 2012 volume prints a stub for it.** The section still reads `exists` — the
release point carries it `repealed` and 1994–2005 print it unbracketed — so the
exclusion costs a year, not a section. Across rebuild #12 the exclusion holds
3,085 rows at `false` whose number does appear in the citing edition as a
withdrawn placeholder. `tests/test_usc_section_oracle.py::
test_a_bracketed_stub_is_printed_but_does_not_attest` pins exactly this,
raw bytes and all, so the exclusion cannot quietly become an accident again.

### The follow-up this defers

**REF-follow-up (unassigned): a third state for "printed as a withdrawn
placeholder at this edition."** `attested_at_edition` is a two-valued answer to
a three-valued question — printed live, printed withdrawn, not printed — and
the 3,085 rows above are the middle case reported as the last. The honest fix
is a distinct field or caveat, not a widened `attested_at_edition`, because
widening it is what produces the 19 wrong verdicts. That is schema work in
`unified_agenda_parquet`'s legal-authorities table and a new column's worth of
census, which is a unit of its own and not a line in this one.

## What it is worth to the consumer

Re-measured 2026-08-31 against **rebuild #12**
(`output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet`,
`sha256:b01ca4805a8b05fa388a317409f6e72eb887ea5995d75f5822951f15fd49374f`,
`receipt.json` `uscSectionExistsNotAtEditionRows = 8261`). The numbers below
replace the rebuild-#11 measurement this directory shipped with; the
per-(title, edition) shape is the same and two cells move, both for reasons
outside this oracle. `scripts/would_flip.py` asks the module's own
`section_verdict` twice — once against the pinned generation, once against an
oracle whose two annual tables are the other generation's — and compares.

The script reports **three** populations, and the third is new on 2026-08-31.
Until then its first query was untyped and returned 8,280 rows under the label
"usc rows", 19 of which were `act_relative` — so the same 16 CWA rows were
counted twice, once in the usc table and once in the act table. It is now
`authority_type = 'usc'`, matching the receipt's own
`uscSectionExistsNotAtEditionRows` census exactly.

Harness check first: recomputing under generation 1 returns the column the
build already wrote on **8,261 of 8,261** `usc`-typed rows, so the question
being asked is the build's own.

* **1,882 of the 8,261** `usc`-typed rows reading `exists` /
  `attested_at_edition = false` read `true` under generation 2. 6,379 stay.
  Zero rows change in any other way.
* **16 act-derived rows** (`authority_type = 'act_relative'`, RINs 2040-AE69
  and 2040-AE95, all CWA at edition `201210`) name title 33 sections the 2012
  volume prints; rebuild #12 judges them, and their answer moves from `false`
  to `true`, leaving 3 of the 19 — the genuine era mismatches.
* 390 distinct `(title, section)` pairs, 538 distinct RINs.
* **No `verdict` moves anywhere in the table, and that is now checked rather
  than argued.** Neither query above could establish it: both are restricted to
  rows already reading `exists`, and a verdict moving means an `absent`
  becoming an `exists`. So `would_flip.py` recomputes BOTH halves of the answer
  over every row of the build carrying a `(usc_title, usc_section)` —
  **694,062 rows, of any authority type and any verdict** — and prints the
  movements. Measured: **0 verdict movements, 1,898 attestation movements**
  (the 1,882 + 16 above), and generation 1's recomputation returns the build's
  own verdict on **693,928 of 693,928** rows it judged. The other 134 the build
  writes no verdict for at all — 129 name a title that cannot be the Code's
  (59, 61, 80, 94 … 41349) and 5 name titles 52 and 54 in editions before those
  titles existed — and calling `section_verdict` directly answers `absent` for
  them because it is asked. That is a difference in what gets asked, not in
  what the oracle answers, so the reconciliation excludes them by name rather
  than absorbing them into a total.

`would_flip.py` is **read-only unless `--write` is passed**; without it the
flip list goes to stdout with the rest of the report instead of overwriting
`evidence/would_flip_rows.tsv`. It used to rewrite that tracked file
unconditionally while its own docstring said it wrote nothing.

| title | edition | rows | RINs | texts |
|---:|---:|---:|---:|---:|
| 12 | 2010 | 1,368 | 216 | 338 |
| 38 | 2012 | 140 | 82 | 77 |
| 33 | 2012 | 133 | 66 | 63 |
| 35 | 2012 | 86 | 40 | 27 |
| 40 | 2012 | 72 | 69 | 10 |
| 41 | 2012 | 66 | 60 | 10 |
| 13 | 2010 | 10 | 5 | 5 |
| 14 | 2010 | 5 | 2 | 3 |
| 39 | 2012 | 2 | 2 | 2 |

One cell moved from the rebuild-#11 table, and it is not about this oracle:
**12 @2010 1,367 → 1,368**, the endpoint row the in-list range-tail unit added
to `12 USC 2018 to 12 USC 2020` (RIN 3052-AC55, edition 201004). The table is
`usc`-typed, so 33 @2012 is the 133 `usc` rows it always was; the 16
`act_relative` CWA rows are counted once, in their own section above, and are
listed row by row in `evidence/would_flip.txt`.

The full `usc` flip list — **1,882 rows** — is
`evidence/would_flip_rows.tsv`; twenty seeded rows with their RIN, edition and
citation text, the 16 act-derived rows, and the whole-table recomputation are
all in `evidence/would_flip.txt`.

**Against the investigation's hand-bucketed answer key**
(`../investigations-2026-08-24/inv-2012/exists_not_attested_8258_bucketed.csv`,
which classified all 8,258 rows of rebuild #11 by eye): generation 2 flips
every `1-case-bug-high-confidence` key (1,355 distinct keys) and **not one**
key from `2-case-bug-uncertain` (28), `3-future-edition-beyond-2024` (23) or
`4-genuine-era-mismatch` (3,869). Against rebuild #12 there is **exactly one
flip the key does not carry at all** (`evidence/answer_key_confusion.tsv` names
it): `12 USC 2020` for RIN 3052-AC55, the range endpoint the in-list
range-tail unit added after the key was hand-bucketed. It was 17 while the
script's first query was untyped and swept the 16 CWA `act_relative` rows into
the `usc` flip list — those rows are real and unchanged, they simply are not
`usc`-typed and the key never covered them. Not one is a `usc`-typed row the
key bucketed and generation 2 disagreed with.

**The projection the 2026-08-31 review carried was buckets 1+2.** It expected
"~1,912 rows / 404 pairs / 559 RINs" — that is `1-case-bug-high-confidence`
PLUS `2-case-bug-uncertain` (1,911 / 404 / 559 exactly). The measurement is
bucket 1 alone plus the one new range-endpoint row: **1,882 / 390 / 538**. The
30 rows the investigation marked uncertain are titles 40 and 41 at 2012 cited by
their **pre-recodification** numbers — 40 U.S.C. 276c, 322, 333, 484, 486 and
41 U.S.C. 46, 253, 414, 418b, 421–423, 431, 701 — and the recovered 2012
volumes do not print them (checked by eye in the raw `.htm`: title 40's 2012
volume prints §101 and §3141, not §276c). The volume existing and the section
existing are different facts, and generation 2 keeps them apart.

## The module switch — done 2026-08-31

The six tables here are what `refspec.registry.usc_section_oracle` reads.
Before re-pinning, all six were re-extracted from the retained zips in a
scratch working directory and compared to the committed copies: **`EXCEPT` in
both directions returns 0 rows on all six**, columns identical, 1,572,225 /
49,960 / 59,364 / 1,751 / 160,209 / 2,905 rows respectively. The parquet BYTES
differ between runs — DuckDB writes rows in Python set-iteration order, which
is not stable across processes — so the pins below are the digests of the
committed files, verified to be a row-for-row reproduction rather than assumed
to be one.

* `src/refspec/registry/usc_section_oracle.py`
  * `USC_SECTION_ORACLE_ARTIFACT` → `"research/evidence/usc-section-oracle-2026-08-24"`
  * all six digests in `_ORACLE_PINS` → the Files table above
  * docstring counts moved: annual rows 1,565,007 → **1,572,225**, annual
    range rows 49,823 → **49,960**. The counts that did **not** move: 66,780,
    67,022, 66,007, 1,015, 59,362, 59,364, 1,751, 160,209, 2,905, 1,885.
  * the falsified prose is corrected: "every year 1994–2024" now states what
    it is true of (every year AND every title volume in it, 1,781 of 1,835
    members matched and the other 54 named), the "32 source zips are not
    retained here" line says *not committed but retained under
    `output/usc-annual-2026-08-24/`*, and the blast radius is stated with its
    measurement.
  * two byte counts in `verify`'s docstring were still generation 1's and are
    re-derived from the files on disk: `usc-oracle-chapters` 11,713 →
    **11,668**, and the six together 8,841,601 → **9,229,092**.
  * the bracketed-stub exclusion above is stated in the module docstring, in
    `scripts/extract_annual.py`'s docstring, and at the matcher itself.
  * **`c3_proposals` reads a stated tail per OCCURRENCE, not per text**, which
    is a fix landing in the same wave and is *not* about the oracle tables. A
    tail anywhere in the string used to suppress the bare lettered reading
    everywhere in it, so `42 U.S.C. 2000(d) to 2000(d)-7` — a span named by
    both endpoints, both printed sections — came back as the single reading
    `2000d-7`. The pair's candidate count goes 8 → **9** (2000d, 2000d-1 …
    2000d-7, 2000e). Downstream, `unified_agenda_parquet`'s C3 promotion
    refuses those two rows as ambiguous instead of publishing an endpoint:
    **217 promoted / 14 ambiguous / 1,186 witnessless**, from 219 / 12 / 1,186.
    The two rows are RIN 1505-AC45 at editions 201610 and 201704.
* `tests/test_usc_section_oracle.py` — `SNAPSHOT` is now anchored on its own
  `SNAPSHOT_DIR` constant pointing at **generation 1**, deliberately: the
  snapshot is a measurement of the CORPUS, this directory is a re-cut of the
  Code's tables and not a re-measurement of the corpus, and copying it would
  mint a second set of identical bytes with two digests to keep in step. Three
  counts moved with the switch — annual range stubs 49,823 → 49,960, the
  corpus's exists-not-attested rows 8,227 → 6,375 over 706 → 325 pairs, and
  12 U.S.C. 1831o-1's first attested year 2011 → **2010** (Dodd-Frank § 616(d),
  printed in the recovered 2010 volume). Three tests were added on 2026-08-31:
  `test_the_extractors_own_matcher_classifies_every_archive_member` runs
  `extract_annual.py`'s OWN `FNAME` and `NON_TITLE` (lifted from its source by
  AST, not restated) over all 1,835 members of all 31 zips, so reverting
  `re.IGNORECASE` fails a test rather than only changing an artifact nothing
  re-derives; `test_a_bracketed_stub_is_printed_but_does_not_attest` pins the
  exclusion above against the raw bytes; and the C3 test gained a mixed
  tailed/untailed fixture.

Still outstanding, in files this unit did not own:

* `src/refspec/registry/citation_grammar.py` — the artifact path in three
  comments (≈ lines 1866, 1951, 2659) and the two row counts. Its own
  `USC_SECTION_ORACLE` constant in `tests/test_citation_grammar.py` is
  hard-coded to generation 1 and therefore still passes.
* `src/refspec/registry/unified_agenda_parquet.py` ≈ line 3824 — calls the 2012
  gap "the oracle's own coverage hole" over "titles 33-41, 52 and 54", merging
  this fixed extractor bug (33, 35–41) with genuine title-creation gaps (52,
  54). Now false for the first half.
* `tools/build_registry_source_manifest.py` ≈ lines 1364, 1379 — the README
  path, and the "zips were deleted" wording, which is no longer true of
  generation 2: `output/usc-annual-2026-08-24/` retains all 32.
* `tests/test_citation_grammar.py` — the artifact path at lines 53 and 2954
  and the counts at 2949–2950.

Corpus-count tests that assert `attested_at_edition` totals moved by the 1,882
rows above; nothing that asserts a `verdict` moved at all, and that was checked
over the whole 694,062-row population rather than inferred.
