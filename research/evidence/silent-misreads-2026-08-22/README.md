# Raw material behind `silent-misreads-2026-08-22.md`

Everything the campaign produced that is not re-derivable from the pinned
artifact, preserved beside the report it supports. Nothing here is under
`src/`, `tests/` or `output/`; nothing here was modified after measurement.

## Provenance of the two external oracles

**eCFR part authority notes.** Fetched **2026-08-20** from the eCFR versioner
API, one request per part:

```
https://www.ecfr.gov/api/versioner/v1/full/2026-08-20/title-{TITLE}.xml?part={PART}
```

299 parts requested; **288 returned XML, 287 of those carry an `<AUTH>`
element**, 11 failed. Responses were captured to a 128 KB head (the `<AUTH>`
element appears near the top of a part document), so a raw file of exactly
131,072 bytes is truncated — flagged per record as `raw_truncated_at_128k`.
The raw XML is **not committed**: it is 31 MB, re-fetchable from the URL in
each record, and each record carries the `raw_sha256` and `raw_bytes` of the
response it came from, so a re-fetch can be verified byte-for-byte.

**OLRC Table III.** Derived from this repository's own pinned bulk download,
which is already durable and therefore not copied here:

- `output/registry-real-data-sources/olrc-table3-xml-bulk-119-73.zip`
- sha256 `93e1f233e081e47fc3680c4b699151c6d66329988fe21add3b6e9e62746aeea7`
- 14,966,992 bytes

Unpacked it yields `fulldump@119-73.xml` (126 MB), from which
**69,597 distinct (U.S.C. title, section) pairs** and 136 Statutes-volume
entries were extracted. Calibrated at **99.0% recall** against 1,139 sections
cited by the publisher's own authority notes.

**The artifact under measurement — and a provenance correction.**

The pinned parquet **was rebuilt on disk while this campaign was running.** The
first version of this README recorded the digest of the file as it stood at the
end, which is *not* the file the report measured. Both are recorded here.

| | rows | sha256 | content fingerprint |
|---|---:|---|---|
| **as measured** (loaded 17:11, the report's basis) | **798,114** | not captured — the file was overwritten before it was digested | `7619860470285616645` |
| preserved copy in this directory | 798,114 | `d9b5f5da7541568e6095ec8d7c31119341856517c6db2866fcc29699ff1b3b4b` | `7619860470285616645` |
| on disk now (rebuilt 17:44) | 797,170 | `c5c4bd1f8b70fd52491f8b22e7bc72c75287cbbf3638692210fd1691731c7424` | `14405785099254785698` |

`agenda-legal-authorities-as-measured.parquet` is the report's exact basis,
recovered from the campaign's working database. It is **content-identical, not
byte-identical**, to the build that was overwritten: re-serialised by a
different writer, so its sha256 cannot match a file that no longer exists. The
fingerprint column is writer-independent —
`bit_xor(hash(rin|publication_id|ordinal|citation_ordinal|authority_text|authority_type|usc_section))`
— and it matches the working database exactly while differing from the rebuild.
Anyone re-running the report's numbers should use this file.

**What the rebuild changed:** 944 net rows, same 42,642 distinct texts. It
removed **995 rows** citing 18 U.S.C. 1987 and 18 U.S.C. 1984 — the date-year
phantom, class B0. So that class is now gone from the artifact as well as from
the grammar, and the report's framing of it as "what consumers hold" is
already historical. Every other count in the report is unaffected: the
`administrative_order` (1,244) and `case_citation` (107) populations, for
instance, are identical across both builds.

Grammar commits referenced: `06b8d0ef` (measurement baseline), `2fc3fc7b`
(re-check). Sample seed `20260822`.

## A U.S.C. subsection oracle exists, and the report says it does not

`usc-oracle-subsections.parquet` (160,209 rows) is a (title, section,
subsection) index built from the OLRC **current release point**, non-appendix
titles only — not from the annual XML, as this README first said; corrected
per `usc-section-oracle-2026-08-22.md` §10, and the limit matters: a section
transferred out of a title since (16 U.S.C. 462 → title 54, 2014) has no
subsections here, so predicate C2 cannot judge it — by a campaign leg that
**never reported its results back**. The report therefore states that the
subsection-structure predicate "needs subsection-level structure from the
U.S.C. XML, which this campaign did not have in hand". **That is wrong: it was
on disk the whole time.** Correcting it here rather than silently.

Validated 8/8 against the report's hand-checked publisher lookups (42 U.S.C.
1395 has no subsections; 42 U.S.C. 2139 does have an (a); 21 U.S.C. 346 has
none; 5 U.S.C. 552(a), 47 U.S.C. 154(i), 21 U.S.C. 371(a), 42 U.S.C. 629(b),
16 U.S.C. 620(f) all as the report describes).

Running the predicate the report names as its highest-value unexplored seam —
*flag `NNN(x)` where section `NNN` has no subsection `(x)` and section `NNNx`
exists* — gives **308 distinct texts / 1,888 rows** (`subsection-impossible-candidates.csv`).
Two cautions, both load-bearing:

1. **The status guard does 84% of the work.** Without requiring both sections
   to be `current`, the predicate returns 419 texts / 4,526 rows; **10,167
   further rows** are excluded as era-correct. The largest naive hit,
   `42 USC 2473(c)` at 1,824 rows, is **not** a misread: 42 U.S.C. 2473 was
   reclassified to 51 U.S.C. 20113 in 2010, so the current-code oracle lists no
   subsections for it, while every citation dates from editions 199510–201410
   when it was live and correct.
2. **This is a candidate population, not an adjudicated count.** It reproduces
   three classes the report proved by hand — 21 U.S.C. 346 -> 346a (B1),
   42 U.S.C. 1395 -> 1395hh (B8), 42 U.S.C. 300 -> 300f (B1) — at the top of
   its ranking, which is encouraging but is not a precision measurement.

## The U.S.C. existence oracle, and its own headline

The leg that built `usc-oracle-*.parquet` reported after the report was
committed. Its sources, both OLRC, downloaded 2026-08-22:

- current release point USLM XML,
  `https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_uscAll@119-102.zip`
  (108,610,077 bytes, 58 title files dated 2026-07-23);
- annual historical archives XHTML, every year **1994–2024**,
  `https://uscode.house.gov/download/annualhistoricalarchives/XHTML/<YEAR>.zip`
  (31 zips, ~1.9 GB).

Union used as the existence test: **66,780 distinct (title, section)** spanning
every edition in the corpus. The ~2.9 GB of source zips was deleted; the
extracted parquets in this directory are what remains.

**One extraction bug worth recording**: OLRC identifiers use U+2013 EN DASH
(`/us/usc/t42/s1395w–4`) where the corpus uses ASCII hyphen. Before that was
normalised, the entire Medicare/ACA/SDWA compound-name family read as
nonexistent. The fix was to apply the grammar's own `_DASHES` table to the
oracle.

**Headline, measured against the 797,170-row rebuild** (so not directly
comparable to the report's counts): of 685,431 rows carrying a parsed U.S.C.
title+section, **1,728 (title, section) pairs — 2,372 texts, 18,117 rows,
2,622 RINs — name a section that has never existed in any edition 1994–2026**,
and **13,612 of those rows carry `parse_status = 'ok'`**. Triaged: 7,200 rows
a derivable parser defect, 2,280 rows real-when-written but outside the oracle
window, 8,637 rows detected-but-target-unresolved.

That corroborates the report's second headline finding — nothing fences a
U.S.C. section — with a larger and independently-built oracle, and it confirms
the report's per-row rate is a floor rather than a ceiling.

## What was never written to disk

- **The 300 item-level adjudication verdicts.** Returned as agent messages,
  tallied, and used for the rates; no file was produced. See
  `adjudication-tallies.md` for what survives and what does not.
- The metamorphic harness's per-transform reasoning (only its findings survive,
  in `metamorphic-findings.csv`).
- The eCFR sharp-tier adjudication of 44 texts (the population is derivable
  from the notes plus Table III; the 44 verdicts are not on disk).

## Files

| file | sha256 | bytes |
|---|---|---:|
| `adjudication-sample-b-flagged.tsv` | `55b6048968d88b3b27f29cea50957963157edea3867209e78379a03a2c6a74f5` | 1,742 |
| `adjudication-tallies.md` | `362a0709a3608733565afa692e4e9599d40ef90be8c97985904e758b8f062359` | 2,021 |
| `agenda-legal-authorities-as-measured.parquet` | `d9b5f5da7541568e6095ec8d7c31119341856517c6db2866fcc29699ff1b3b4b` | 2,849,256 |
| `ecfr-authority-notes.jsonl` | `c46cbca6e00c545924aecdffbb94ae2391b93c5116fb63567b1ad8293ab9d2f3` | 289,647 |
| `ecfr-fetch-failures.txt` | `c1b21b3ab19168d1703b8a059d424342dcbd6ef8ff7545bfecbeb2ac277e452e` | 252 |
| `ecfr-part-coverage-rank.csv.gz` | `2240f8db4465305e5f66e429d2719f2e36fee4a03b6583ef0d886336a06efafd` | 39,647 |
| `ecfr-parts-selected.json` | `101fe4dbcf360c69e48f32efa5db487851c4f120e7d5985a62b7097f32e565c6` | 19,076 |
| `headdiff-artifact-vs-06d.csv` | `333b559417b39ea2d6a319f32929cd89f39d397bfb819cdd9e7685e288de5c4f` | 224,675 |
| `l1-near-miss-pairs.csv` | `05a4e22ab26eae25a5b8b03f929ade84695a5ae3f68b44c1e8f29ee9ae9348e0` | 129,743 |
| `metamorphic-findings.csv` | `782fc3dda72db423c3218222e275dcb7dc4d57998ab3084b23349615f26359bc` | 53,444 |
| `pl-congress-to-statutes-volume.csv` | `ccb83573c5e4a23c36b12f0575d83883883dbb9e2c845d009f78715173d66a18` | 1,050 |
| `pl-volume-page.csv.gz` | `9eb8b2f6d3a8b77f30849c1ec2b8827b5780df2140607a1cd6fbeb7c8ba6f6db` | 260,915 |
| `samples/draw-samples.py` | `ca6945211818c76c180f9440a98ac66fb7748179e68b6e4c76ef6e490ce22e53` | 2,767 |
| `samples/sampleA.json` | `a1cca3899a686dd6abbbae3f537cbac3b4d31b38795bbe04c53871cada0398a3` | 57,288 |
| `samples/sampleA_1.json` | `2cc30e9b606197b25cb2e643570da5bb9e457f479429084150ec230006620316` | 25,752 |
| `samples/sampleA_2.json` | `e693799933b72146a741a066bbcdf6bc3d1d7fdefce31137eb9a6ae3150dbdee` | 31,538 |
| `samples/sampleB.json` | `c364e7f722dd2dedc2a051c27a5dc5d7cffa04249fc5a7f108fe384230ec1a48` | 56,393 |
| `samples/sampleB_1.json` | `59e34d167bfc47ed44469841fa1a44d96e49515656fbbca607b034d20121cd71` | 23,953 |
| `samples/sampleB_2.json` | `ef37dbcc23bf75cf197c74db3fa99eaa590e750424f0662cfd38c1e453fb8275` | 32,442 |
| `subsection-impossible-candidates.csv` | `202233548bed1f251feed6f97adc4f563fec7e8aac3685b7d3095e8670884d10` | 12,426 |
| `table3-statutes-volumes.csv.gz` | `96f5fbf89fa59f600d10598ccad36fd8253c94df03bb9492c0be71560fe93463` | 138,199 |
| `table3-usc-sections.csv.gz` | `ff5ca095cccf4e6e9e7ee9658cd9836c11adeb45953fa859639eabff875a2ade` | 169,124 |
| `usc-oracle-annual-ranges.parquet` | `caa9d3819dc6b49fdb68442c0e5be4773e84af99833437eb8f662da9aae2fde9` | 177,589 |
| `usc-oracle-chapters.parquet` | `4fbd6ba386bee9d0a55f68e5072be60e6eaa0222719974eadcb842e345212f95` | 11,713 |
| `usc-oracle-ranges.parquet` | `0808cbbff5f456d36daa4a45f3996b911bff7a98f36130150ed7600a255883d6` | 40,723 |
| `usc-oracle-sections.parquet` | `f4b11c6e4ccbaa6ccf2aa0f4940d514b3a0285c6ec1b8f1352ea25b8a9a1bf1d` | 303,380 |
| `usc-oracle-subsections.parquet` | `c412340820bb65f957c34d24a0124f78abfce1dc30b95773767af03472096f22` | 1,094,598 |

### What each file is

- `agenda-legal-authorities-as-measured.parquet` — the report's exact basis,
  798,114 rows, content-identical to the build that was overwritten mid-run.
- `ecfr-authority-notes.jsonl` — 287 records: CFR title/part, the publisher's
  authority note and source note as text, the API URL, fetch date, and the
  raw response's sha256/length.
- `ecfr-fetch-failures.txt` — the 11 parts that did not return.
- `ecfr-parts-selected.json`, `ecfr-part-coverage-rank.csv.gz` — the greedy
  set-cover selection and the full part ranking by agenda rows covered.
- `table3-usc-sections.csv.gz` — the 69,597 (title, section) pairs.
- `table3-statutes-volumes.csv.gz` — 136 Statutes-at-Large volume entries.
- `usc-oracle-subsections.parquet` — 160,209 (title, section, sub).
- `usc-oracle-sections.parquet` — 59,364 (title, section, status) where status
  is `current` / `repealed` / `omitted`.
- `usc-oracle-ranges.parquet`, `usc-oracle-chapters.parquet`,
  `usc-oracle-annual-ranges.parquet` — range, chapter and per-year (1994+)
  coverage from the same extraction.
- `subsection-impossible-candidates.csv` — the 308-text candidate population.
- `l1-near-miss-pairs.csv` — the cross-edition detector's 1,579 near-miss pairs
  with their blip/prefix/suffix shape classification.
- `headdiff-artifact-vs-06d.csv` — the 2,138 texts whose parse at grammar
  commit `06b8d0ef` differs from the pinned artifact.
- `metamorphic-findings.csv` — the 150 raw differences from the
  meaning-preserving rewrite harness (most are the harness's own lossiness;
  see the report).
- `pl-congress-to-statutes-volume.csv`, `pl-volume-page.csv.gz` — the Public
  Law to Statutes-volume oracle behind class A1.
- `samples/` — both audit samples verbatim, their four adjudication batches,
  and `draw-samples.py`, which reproduces them exactly from the pinned parquet.
- `adjudication-tallies.md`, `adjudication-sample-b-flagged.tsv` — the surviving
  adjudication evidence.
