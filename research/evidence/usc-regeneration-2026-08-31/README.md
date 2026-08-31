# USC regeneration inputs — 2026-08-31

RefSpec consumed two U.S. Code artifacts it could not re-derive: the popular-name
half of the act index, *carried over byte-identically* by
[`usc_act_index.py`](../../../src/refspec/registry/usc_act_index.py) rather than
built (`--popular-names-from`, lines 428 and 532), and the source-credit index
[`act_resolution.py`](../../../src/refspec/registry/act_resolution.py) loads
(`USC_SOURCE_CREDIT_ARTIFACT`, line 136) with no builder anywhere in `src/` or
`tools/`. Both traced back to abandoned spicy-regs code. This directory pins the
input bytes the two new builders read, and the fragments their tests assert
against.

The builders are
[`tools/build_usc_popular_names.py`](../../../tools/build_usc_popular_names.py)
and
[`tools/build_usc_source_credits.py`](../../../tools/build_usc_source_credits.py).
Neither writes over a frozen artifact: each derives to a directory of its own and
proves the relationship by comparison (`--verify`).

---

## The verdicts

| Frozen artifact | Derived from | Verdict |
| --- | --- | --- |
| `output/usc-source-credit-index-2026-08-02/usc-source-credits.parquet` | `xml_uscAll_119-102.zip` | **byte-identical** — `sha256:d377545f…`, the digest `act_resolution.py:147` pins; all 3,721 rows and every one of the frozen receipt's 14 coverage counts reproduce |
| `output/usc-act-index-2026-08-22/usc-popular-names.parquet` | `popularnames.htm` (captured here) | **row-identical on every parsed column**, all 20,865 rows; **byte-identical after the loader's own normalization**; 4 rows differ in the derived `name_key` column alone, and the loader erases all four |

### The popular-name delta, in full

All twelve columns agree on 20,861 of 20,865 rows. The four that differ do so in
one derived column, `name_key`:

| `name` | frozen `name_key` | derived `name_key` |
| --- | --- | --- |
| ``` ``Kick-Back'' Racket Act ``` | `''kick-back'' racket act` | `kick-back'' racket act` |
| ``` ``SPARS'' Act ``` | `''spars'' act` | `spars'' act` |
| ``` ``Seeing-Eye'' Dogs on Railroads Act ``` | `''seeing-eye'' dogs on railroads act` | `seeing-eye'' dogs on railroads act` |
| ``` ``Six Triple Eight'' Congressional Gold Medal Act of 2021 ``` | `''six triple eight'' …` | `six triple eight'' …` |

This is not a parse difference. `name_key` is not read from the page; it is
`normalize_popular_name(name)`, and the normalizer that sealed the frozen table
on 2026-08-02 was spicy-regs', not
[`citation_grammar.py`](../../../src/refspec/registry/citation_grammar.py)'s.
RefSpec already knows: `act_resolution.py:495-499` says the frozen keys are "not
a fixed point of `normalize_popular_name`", re-normalizes every key on load, and
puts the population at "a no-op for 20,861 of the pinned table's 20,865 rows" —
**exactly these four**. Three digests settle it, and
`test_the_derived_table_is_the_frozen_one_after_the_loaders_own_normalization`
asserts all three:

```
sha256:603d5b07…  the frozen table
sha256:603d5b07…  the frozen ROWS rewritten by the new builder's writer
                  -> writer metadata is not a source of difference
sha256:a8777c95…  the frozen rows with normalize_popular_name applied to the
                  key columns, exactly as ActIndex.from_artifact applies it
sha256:a8777c95…  the derived table
```

The two tables are one index. No agreement was forced anywhere.

---

## What was fetched, and from where

One endpoint, public and keyless. No API key was used or required.

```
https://uscode.house.gov/popularnames/popularnames.htm
```

| | |
| --- | --- |
| Fetched | **2026-08-31T07:14:17Z** (server `date` header) |
| User-Agent | `RefSpec-research/1.0 (Atlas regulatory-vocabulary research; contact michael.f.deeb@gmail.com)` |
| Status | HTTP/2 200, `content-type: text/html;charset=UTF-8` |
| Bytes | 11,101,663 |
| sha256 | `65c5185e8e9508c8a22d8c2bf49d563808a45d053872af79d2bc95b7c2566a12` |
| Release point stated | `119-102`, on all 13,628 entries |

Stored here **gzipped** (`popularnames.htm.gz`, 1,063,266 bytes): 90% of the file
is site chrome, and the digest above is of the decompressed bytes, which is what
a receipt pins and what `read_pinned_html` returns.

### Why it was fetched at all

It does not exist locally. Searched by content, not by name, before fetching:
`grep -rl statviewer ~/Work/corpora/` (11 hits, all source code or sweep notes);
`grep -rl popular-name-table-entry ~/Work/` (**zero**); `find ~/Work -size
11101679c` (zero); `find … -iname '*popular*'` (four `usc-popular-names.parquet`
copies and this repo's `inv-initialisms/raw/popularnames.headers.txt`, which is a
six-line HTTP header capture with no body). The platform's working assumption
that the data already exists held for the USLM archive below; it did not hold
here.

### The 16 bytes, accounted for

The receipt of the artifact this reproduces
(`output/usc-act-index-2026-08-02/receipt.json`) pins its own capture at
`sha256:50687ac0…`, **11,101,679 bytes** — 16 more than this one. Those 16 bytes
are page chrome, and the proof is that the page does not render the same way
twice. A second fetch three minutes later
(`sha256:83afd34304e0e86d58c3f642e58f0ff524989481a053490b63bae6dcc6c9a5a6`,
11,101,656 bytes, **7 bytes shorter again**) differs from the first in exactly
two places, both outside every `<div class='popular-name-table-entry'>`:

* the 21 `;jsessionid=…` path parameters in the navigation chrome — a fixed
  32 hex characters, so no byte-count change; and
* a per-render server marker in the footer, `5v4` against `16v4`, with the
  enclosing `<div>`'s `width` moving `310px` → `410px` beside it.

Masking the session id leaves those two spans as the only difference between two
captures of the same release point taken minutes apart. The records themselves
are stable: **all 20,865 of them parse identically to the frozen table's rows.**
A dated-input mismatch was the expected finding here and is not what happened —
the release point is the same one the frozen artifact was sealed from.

---

## What was *not* copied here

`xml_uscAll_119-102.zip` (108,610,077 bytes,
`sha256:55c8d19543c4a972a33e33532b592ac3984c83fdcb04de9f5a64ef1f8483d300`) stays
in the corpora salvage, per the intake ledger's §4 doctrine:

```
~/Work/corpora/_salvage-2026-08-28/refspec-output/usc-annual-2026-08-24/xml_uscAll_119-102.zip
```

Verified two ways before it was trusted: its sha256 was recomputed here and
matches both the `fetch_log.tsv` beside it (fetched 2026-08-24T16:56:57 local,
243 s, HTTP 200) **and** `inputs.archive_digest` in the frozen artifact's own
receipt. It is the same bytes the 2026-08-02 artifact was built from, which is
why the rebuild is byte-identical rather than merely equivalent.

**It is not one of the annual editions.** The directory's other 2.0 GB is
`1994.zip` … `2024.zip`, fetched from
`uscode.house.gov/download/annualhistoricalarchives/XHTML/` — historical
**XHTML** editions with no USLM in them, which cannot feed this parser at all.
Reading the one release-point member takes **≈10 s**, not the "real time" the
ledger's §1.4 anticipated; no resumability was built because none is earned.

---

## The fixtures

`fixtures/` holds byte slices of the two sources, cut by
`scripts/extract_fixtures.py`, so the fast unit tests assert against what OLRC
published rather than against prose invented to make an expression pass.

`popular-name-entries.json` — seven whole `<div class='popular-name-table-entry'>`
elements:

| key | what it pins |
| --- | --- |
| `statviewer_and_stated_citation_agree` | 1921 Silver Dollar Coin Anniversary Act — the place stated twice, agreeing; also a `/table3/` link that is *not* a statviewer link |
| `stated_citation_only` | 21st Century Cures Act — two cites, the second with no statviewer query at all (one of 56) |
| `see`, `renamed` | the two kinds that state a redirect target |
| `also_known_as` | 21st Century IDEA — reads exactly like a redirect, states none |
| `usckey_accepted_and_refused` | Interstate Agreement on Detainers Act — `usckey='18:App.)'` accepted beside `usckey='18A:1'` refused |
| `ambiguous_name` | Detainee Treatment Act of 2005 — one name, Pub. L. 109-148 *and* 109-163 |

`uslm-source-credits.json` — five real `<sourceCredit>` texts with the identifier
of the section that carries each:

| key | what it pins |
| --- | --- |
| `added_enactment` | 26 U.S.C. 6038E — the enactment construction, stated plainly |
| `no_construction_2714a` | 22 U.S.C. 2714a — law, division and act section, no lead; carried by nobody |
| `no_construction_7652` | 26 U.S.C. 7652 — the measured false positive; names (116-260, div. EE, § 107) and never says "amended" |
| `enactment_then_amendment` | 5 U.S.C. 3116 — 132 Stat. 2007 then 133 Stat. 1604 in one credit |
| `en_dash_section` | 16 U.S.C. 824s–1 — a section suffix USLM spells with U+2013 |

### Two rules had no negative case in the published data, so one was made

Both builders' tests follow this repository's mutation-battery doctrine
([AGENTS.md](../../../AGENTS.md)): real data passing proves only what a check
accepts. Release point 119-102 publishes **no** credit that is both a strict
enactment match and outside a `<section>` (`credits_outside_a_section` is 0), and
**no** retained citation whose page the bound changes
(`retained_pages_the_bound_changed` is 0, pinned as
`BOUND_CHANGES_NO_ANSWER_ON_119_102`). The tests therefore mutate real fragments
and say so at the mutation:

* the 5 U.S.C. 3116 credit with its own `132 Stat. 2007` deleted — bounded, the
  row refuses; unbounded, it would publish the *amendment's* `133 Stat. 1604` as
  the enactment's page;
* the 26 U.S.C. 6038E credit re-parented under a `<chapter>` and under an
  appendix path, reaching both quarantine reasons.

Pinning the zeros is the other half: a release point where either stops being
zero fails the suite instead of arriving as a quietly changed page number.

---

## Reproducing

```
.venv/bin/python tools/build_usc_popular_names.py  --verify output/usc-act-index-2026-08-22
.venv/bin/python tools/build_usc_source_credits.py --verify output/usc-source-credit-index-2026-08-02
.venv/bin/python -m pytest tests/test_build_usc_popular_names.py tests/test_build_usc_source_credits.py
.venv/bin/python research/evidence/usc-regeneration-2026-08-31/scripts/extract_fixtures.py
```

`--verify` never writes to the artifact it reads. `--output DIR` seals a derived
copy somewhere else; nothing here regenerates a frozen artifact in place.
`MANIFEST.tsv` carries the sha256 and byte count of every file in this directory.
