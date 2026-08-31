# The act index, rebuilt from the Table III bulk release: what it cost and what it answers

**Verdict: the ingestion gap named in [table3-coverage-2026-08-22.md](table3-coverage-2026-08-22.md) is
closed, and it is worth 1,969 of the 3,042 rows that report predicted.** The
sealed act index now carries **302,156 Table III classification rows over
15,189 enacting acts**, against the per-page build's 10,976 over 24 — read out
of a file that has been on disk since 2026-08-06, with **zero network
requests**. Act-relative resolution over the Unified Agenda corpus rises from
**205 pairs / 3,621 rows to 354 pairs / 5,590 rows**, with **nothing lost and
no answer changed**.

Every number below was measured on 2026-08-22 by running the production code
(`refspec.registry.usc_act_index`, `refspec.registry.act_resolution`) against
the artifacts as they sit on disk. Where a count is compared against an earlier
state, the earlier code is **copied in as an oracle rather than imported** —
importing the thing under replacement makes the comparison circular.

## 1. What was built

`src/refspec/registry/usc_act_index.py` reads
`output/registry-real-data-sources/olrc-table3-xml-bulk-119-73.zip`
(**14,966,992 bytes**, `sha256:93e1f233e081e47fc3680c4b699151c6d66329988fe21add3b6e9e62746aeea7`)
and its one member `fulldump@119-73.xml` (**126,260,704 bytes**), and writes
`output/usc-act-index-2026-08-22/` — the same three tables, the same columns,
the same types, in the same order, so `act_resolution.py` reads it with no
change to its loader. `--verify` re-hashes the sealed tables against the
receipt, re-checks the source pins, and names every failure instead of raising.

Only the Table III half is rebuilt. `usc-popular-names.parquet` is **carried
over byte-identically** from `output/usc-act-index-2026-08-02/` (digest
`sha256:603d5b07…`, unchanged): the popular names come from
`popularnames.htm`, a document this bulk file does not contain, and re-fetching
it would move the release point for no reason this work needs.

### The well-formedness defect, named exactly

The member is a bare concatenation of **48,973 sibling `<act>` elements** with
no XML declaration and no wrapping root, so the *second* `<act>` is junk after
the document element. `ElementTree.parse` **and** `ElementTree.iterparse` both
refuse the whole file with the identical error:

    xml.etree.ElementTree.ParseError: junk after document element: line 29, column 6

Line 29 is where the first `</act>` is followed, on the same line, by the
second `<act` — at column 6, which the test reads back out of the file rather
than transcribing. The reader therefore streams a split on `</act>` and hands
each fragment to `fromstring` separately; it **checks what it splits**, so a
non-whitespace byte between two fragments or after the last one fails the
build rather than being skipped.

### The two source spellings that had to be decided, and how

**`TABLE3_KEY_RULE` — the key is read, not re-derived.** OLRC states a
`search-key` on every `<act>`: already the Table III key for a modern act
(`103-414`), and date-prefixed for a pre-1957 one (`1948-06-30:758`). The build
narrows the date to its year — `1948:758` — because that is the spelling
`usc-popular-names.parquet` joins on, and touches nothing else. The obvious
alternative, deriving the key from `<num>`, is wrong on a real act: `<num>` is
`78-80` for the 1956 session-law chapter 78-80, which reads as Public Law
78-80, and only `search-key` (`1956-03-02:78-80`) says which it is. That act is
the **single** disagreement between the two rules across all 48,973.

**`PAGE_SPAN_RULE` — a span is narrowed, named, and kept.** 20,371 sealed
records state a page *span* (`3440, 3441`; `1007-1009`) where the per-page
build stored the single page its statviewer link carried. The consumer reads
that column with `int()`, so the row keeps the span's **first** page — the page
the classification begins on — and the verbatim span goes to
`quarantine.parquet` under `statutes_at_large_page_span_narrowed` and is
counted in the receipt. 0 pages were unreadable.

## 2. What the file states, measured

    <act> elements                                        48,973
    <record> elements                                    317,590
      sealed as classification rows                      302,156
      no <act-section>, so no key to file under           15,434   quarantined
    distinct Table III keys                               23,147
      stated by more than one <act> element                4,196
      reached (>=1 keyable record)                        15,189
      classifying no keyable record                        7,958
    rows carrying a Statutes at Large page               289,095

Two source characteristics are carried rather than smoothed, and counted so a
consumer can see them:

* **210 keys the Table III URL grammar cannot spell** (213 acts), all Public
  Resolutions — `1789:Pub. R. 3`. They are real classifications, so they are
  carried; **no popular name reaches any of them**, so carrying them costs
  nothing.
* **49 keys are stated by acts in two different Statutes at Large volumes**
  (and two Congresses) — `1813:18` is in volumes 2 and 3. A `year:chapter` key
  is not unique across sessions. The popular-name table spells keys the same
  way, so this is the source's ambiguity, not this build's.

`<united-states-code-status>` carries **5,568 distinct values**, and its
vocabulary is wider than the currency codes the per-page build saw: `Rep.`
32,989, `Elim.` 21,028, `Rev. T.` and its numbered forms 17,577, **`R.S. Sec …`
9,341**, `I.R.C. '39` 348. The R.S. and I.R.C. values are pre-codification
*citations*, not currency statuses; the consumer refuses on any non-empty
status alike, which is the same behaviour it had before and is right in both
cases (those rows state no U.S.C. title either), but the two facts are
different and this is where that is on the record.

Read but uncarryable, named with counts in `receipt.measured.stated_but_not_carried`
rather than dropped in silence: `act/@congress`, `@date`, `@id`, `@sequence`,
`@insertion`, `@format`, `@print-in-supplement`,
`@include-in-online-release-point` (48,973 each) and `record/@id`, `@sequence`,
`@usckey`, `@print-in-supplement` (317,590 each). The sealed schema is the
consumer's, and widening it was not on offer.

## 3. Reproduction of the 24 fetched acts — and the 29 rows that differ

All 24 laws the per-page build reached are in the bulk file. For those keys:

    rows in output/usc-act-index-2026-08-02          10,976
    rows here                                        10,979
    identical on all seven columns                   10,963   (99.88%)
      only in 2026-08-02                                 13
      only here                                          16

**The difference is a release point, not a defect.** The bulk file is release
point **119-73**; the popular-name table and the 2026-08-02 per-page fetch are
**119-102**, which is later. All 29 rows fall in six keys and three shapes:

* **the U.S. Code target was renumbered** — `116-260 §104` and `117-328
  §103(a)`: 2 U.S.C. **6161** (119-73) → **6154 nt** (119-102); `93-406
  §2002(a)(1)`: 26 U.S.C. **226** → **224**;
* **the act section was renumbered** — `1944:373 §§596, 596A, 596B, 596C`
  (119-73) → **§§581–584** (119-102), classifying to the same 42 U.S.C.
  290kk…290kk-3;
* **a status was removed** — `116-260 §305(a)`, `§305(b)`, `§622`, `117-328
  §547`, `1955:360 §134` carry `Rep.`/`Elim.` at 119-73 and no status at
  119-102; and three rows exist only at 119-73 (`116-260 §306A`, `§315`,
  `1935:531 §1899C`).

All 29 are frozen as a literal list in
`tests/test_usc_act_index.py::test_the_24_fetched_acts_come_back_out_of_the_bulk_file`,
so an unlisted divergence fails the suite instead of becoming a diff nobody
reads. **This is the one real cost of the swap: for the 24 laws the per-page
build reached, this artifact is one release point behind.** None of the 29
changes any resolution the Unified Agenda corpus asks for (§4).

One gap closes outright: the 2026-08-02 receipt records `119-21` as
`source_incomplete` — the single Table III page that failed to fetch. **Pub. L.
119-21 is in the bulk release**, so the new receipt's `source_incomplete` is
empty and `ActIndex.incomplete_sources` is `frozenset()`.

## 4. The measured resolution gain

Over `output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet`
as it sits on disk (797,170 rows):

    act_relative rows                                      9,065
      with a stated act_section                            7,063
      distinct (act, section) pairs                          582
      distinct act names                                     114

Resolved through the real `ActIndex` + `SourceCreditIndex`, both sources
consulted, exactly as `resolve_act_relative_citation` does it in production:

    reason                             2026-08-02 index          2026-08-22 index
    resolved                        205 pairs  3,621 rows     354 pairs  5,590 rows
    act_section_not_classified      364 pairs  3,382 rows     188 pairs  1,264 rows
    usc_section_not_expressible       8 pairs     48 rows      26 pairs    126 rows
    act_section_ambiguous             –                         5 pairs     59 rows
    classification_not_current        –                         6 pairs     15 rows
    source_incomplete                 2 pairs      3 rows       –
    act_section_outside_act           1 pair       6 rows       1 pair       6 rows
    act_not_in_index                  2 pairs      3 rows       2 pairs      3 rows

**+149 pairs, +1,969 rows — a 54.4% rise in resolved rows. 0 pairs lost, 0
answers changed.** The `source_incomplete` line disappearing is Pub. L. 119-21
arriving. The three new refusal codes are not regressions: they are what having
real classification data lets the module *say* — `act_section_ambiguous` where
one public law's section classified to several places, `classification_not_current`
where OLRC marks the classification `Rep.`/`Elim.`, and a wider
`usc_section_not_expressible` where the target is a note, a range or a list
that rkaf has no production for. Each was previously hidden inside
`act_section_not_classified`, which asserted an absence that was really a
build's coverage.

### What became of the population the report predicted

The report's "never fetched" population reproduces exactly: **314 pairs /
3,042 rows**. (It reports 86 distinct acts; measured today that population is
**90 distinct act names over 83 distinct Table III keys**, and neither grouping
gives 86 — the pair and row counts match to the unit, so this is a grouping
difference in the earlier count, not a corpus difference.) After the rebuild:

    resolved                          149 pairs   1,969 rows
    act_section_not_classified        136 pairs     921 rows
    usc_section_not_expressible        18 pairs      78 rows
    classification_not_current          6 pairs      15 rows
    act_section_ambiguous               5 pairs      59 rows

Of the 90 acts: **27 now answer every pair cited of them, 22 answer some, 41
still answer none.** The concentration the report predicted held —

     936 / 942 rows   clean water act  (Federal Water Pollution Control Act, 1948:758)
     262 / 268 rows   communications act of 1934
     188 / 193 rows   immigration and nationality act
     158 / 197 rows   commodity exchange act
      34 /  69 rows   energy independence and security act of 2007
      33 /  33 rows   federal insecticide, fungicide, and rodenticide act
      28 /  38 rows   fair labor standards act of 1938
      27 /  28 rows   deficit reduction act of 2005
      24 /  24 rows   rehabilitation act of 1973
      24 /  46 rows   dodd-frank wall street reform and consumer protection act

— the Clean Water Act alone supplying 936 of the 1,969 recovered rows. The
largest still unanswered are `resource conservation and recovery act of 1976`
(111 rows / 18 pairs) and `bipa` (104 / 27); both are now *fetched*, so their
refusals are `act_section_not_classified` in the sense OLRC means it, or
`usc_section_not_expressible` — statements about the source, not about a build.

### The Unified Agenda artifact itself does not move

Built twice from this checkout into scratch trees, once with each act index:

    python -m refspec.registry.unified_agenda_parquet --act-index output/usc-act-index-2026-08-22 --output-root <scratch>
    python -m refspec.registry.unified_agenda_parquet --act-index output/usc-act-index-2026-08-02 --output-root <scratch>

Both wrote **797,198 legal-authority rows, byte-identical to each other**. That
is the expected result and worth stating: the builder consults the act index
only through `resolvable_act_names`, which reads `usc-popular-names.parquet` —
the table this rebuild carries over unchanged. **The act index changes
resolution, which happens live at call time; it does not change the parquet.**
So switching the builder's default `--act-index` is safe and also buys nothing
on its own. (Both scratch builds differ from the artifact on disk by 28 rows,
which is another session's uncommitted work on `unified_agenda_parquet.py`,
not this change — the control build isolates it.)

## 5. The two small fixes

Both are worth exactly what the report said, and neither touches the corpus
above: **none of the eight names is cited in the Unified Agenda.** Over every
name the Popular Name Tool writes — 13,648 of them — refusals fall from **115
to 107**.

**A leading article the tool wrote into its own cross-reference is spelling.**
`resolve_act_name` now retries each stated chain step with `^the\s+` stripped,
after every step has been checked verbatim (so the tool's own spelling still
wins) and before a year is supplied (dropping a word the act's entry does not
use is reading the source; supplying a year is inferring past it). Measured
over every name, it moves exactly four and re-answers none:
`the vocational rehabilitation act` → `vocational rehabilitation act`
(`1920:219`), `the 911 modernization act` → `911 modernization act`
(`110-53`), and the two whose stated chains dead-end at those,
`fess-kenyon act` and `improving emergency communications act of 2007`.

**Straightening before edge-stripping, and the loader stops trusting the
stored key.** `normalize_popular_name` stripped edge punctuation before
straightening quotes, and `_NAME_EDGE` does not recognize a backtick — so
OLRC's four TeX-quoted names came out with a leading `''` that the same
function would have stripped. The key was `''spars'' act`; every query spelled
`spars'' act`. Reordering makes the function **idempotent**, which is what a
join key has to be; over all 20,865 rows of the popular-name table the order
changes exactly those four and nothing else.

The reorder alone is inert, because the *stored* `name_key` was written by the
builder's own copy of the normalizer and is still `''spars'' act`. So
`ActIndex.from_artifact` now normalizes `name_key` and `see_also_key` on the
way in rather than trusting them — a no-op for 20,861 of 20,865 rows, and the
repair for the other four. The three that carry a Table III key become
answerable (`''SPARS'' Act` → `1941:8`, `''Seeing-Eye'' Dogs on Railroads Act`
→ `1937:432`, `''Six Triple Eight'' Congressional Gold Medal Act of 2021` →
`117-97`) and the fourth reaches `copeland anti-kickback act` through the
tool's own cross-reference.

## 6. What this did not fix

* **846 of the popular-name index's 8,399 Table III keys (10.1%) are absent
  from the bulk release.** (Restated 2026-08-23: the earlier 845 of 8,391
  came from a private, order-dependent pick of one table3_key per name_key;
  the field now reports the order-free set of every table3_key any "cite"
  row states, which moves the count by one key in each direction.) The
  earlier report's live spot check found OLRC
  itself returning HTTP 404 for two of them, so some fraction is genuinely
  absent rather than fetchable; that tranche needs measuring, not assuming.
* **The 24 overlapping laws are one release point behind** (§3). The complete
  answer is a build that reads the bulk release *and* re-fetches the current
  release point for the acts a corpus actually cites — or OLRC publishing the
  bulk file at 119-102.
* **The 107 remaining refused names are source-side absences** — 63 the tool
  cites with no Table III key at all, 25 dead-end chains, 19 named only as
  someone's cross-reference. No spelling closure reaches them; they need a
  reason code that tells "the tool lists it and assigned no key" apart from
  "the tool has never heard of it", which the sealed receipt's vocabulary does
  not yet enumerate.
* **The publisher URL of the bulk zip is not recorded anywhere.** The
  2026-08-05 acquisition pass wrote "fetched by plain `curl`" and no address,
  and probing OLRC on 2026-08-22 — `/table3/`,
  `/download/releasepoints/us/pl/119/73/`, `/classification/`, both extensions
  — returns the site's soft-404 page for `fulldump@119-73`, while neither
  `download.shtml` nor `classification/tables.shtml` links a bulk Table III
  file at all. The bytes are digest-pinned and byte-length-pinned and the
  module re-checks both on every build and every `--verify`; the missing
  address is recorded as a blocker in the registry source manifest rather than
  guessed.

## Addendum (23:55): the bulk file's publisher URL was probed again and not found

The 2026-08-06 note records the file as "fetched by plain curl" with no
address. Probed 2026-08-22 from this checkout, all with a research
User-Agent: `/table3/fulldump@119-73.xml`, `/table3/fulldump.xml`,
`/download/table3/fulldump@119-73.xml`, `/table3/xml/fulldump@119-73.xml`
stream OLRC's 404 page slowly (16 KB in 20 s, `HTTP/2 404`);
`/table3/fulldump@119-73.xml.zip`, `/download/table3/fulldump@119-73.xml.zip`
answer 200 with the soft-404 HTML; `/table3/fulldump.zip` and
`/table3/fulldump@119-73.zip` answer 302 to `/docnotfound.xhtml`. Neither the
download index (`/download/download.shtml`), the Table III years page, nor the
classification-tables page links any bulk or machine-readable Table III file.
The web-search budget for this session was exhausted before the question
arose. The descriptor's blocker stands: the bytes are pinned (sha256, length)
and the file reproduces the per-page index, but the address it was served
from is known only to whoever ran that curl on 2026-08-05.
