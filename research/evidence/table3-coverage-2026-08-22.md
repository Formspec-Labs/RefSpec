# Table III coverage: what's pinned, what's already on disk unused, and what it costs

**Verdict: this is overwhelmingly an ingestion gap, not an acquisition gap.** The
data needed to raise Table III coverage from 24 laws to roughly 7,546 of the
8,391 the popular-name index names (89.9%) has been sitting acquired and
unused in `output/registry-real-data-sources/` since 2026-08-06 — found and
downloaded by an unrelated research pass, never wired to
`act_resolution.py`'s coverage problem. Separately, the "21 of 115" figure in
the act-resolution review is confirmed exactly, but the task's framing of the
other 94 as "a spelling the resolver did not try" overstates the fix: only 4
of 115 are a spelling-closure miss (all four via a leading-article strip that
exists elsewhere in the codebase but isn't applied here); the rest are
genuine source-side absences.

All counts below were re-measured directly against the artifacts as pinned on
disk on 2026-08-22, by importing and calling the real production code
(`refspec.registry.act_resolution`, `refspec.registry.citation_grammar`), not
by re-deriving the logic. `tests/test_act_resolution.py`'s four
artifact-marked tests that pin these numbers (`test_act_section_not_classified_
is_mostly_never_fetched`, `test_the_refusals_are_mostly_names_the_tool_does_
list`, `test_the_tool_stores_four_names_no_query_can_reach`,
`test_the_pins_restate_the_receipts_they_are_meant_to_outrank`) all pass
against the current pinned tables.

## 1. What's pinned, and what selected the 24 laws

`output/usc-act-index-2026-08-02/receipt.json` states the shape precisely:

    acts_requested        27
    acts_reached          24     (25 distinct Table III keys resolved, 1 incomplete)
    acts_incomplete        1
    popular_name_rows  20,865    (13,626 distinct names)
    act_section_rows   10,976    (8,451 carrying a Statutes-at-Large page)
    quarantine_rows         1

Both source URLs are OLRC's live site, fetched by plain HTTP GET, not
scraped from a cache someone else built:

- Popular names: `https://uscode.house.gov/popularnames/popularnames.htm`
  (11,101,679 bytes, digest-pinned).
- Table III, one page per enacting act:
  `https://uscode.house.gov/table3/{key}.htm`, where `{key}` is the Popular
  Name Tool's own Table III key with its separator (`:` or `-`) turned into
  an underscore — e.g. `1948:758` → `table3/1948_758.htm`. The one fetch
  failure recorded is `https://uscode.house.gov/table3/119_21.htm`
  (`RuntimeError: OLRC fetch failed after 4 attempts... HTTP 200, 16134
  bytes received before RemoteProtocolError, 0 classification rows`) — a
  truncated response, not a 404; a retry would likely just work.

**Selection mechanism.** `--acts-for` is a corpus-detection argument, not a
fixed list: the builder runs the same act-relative citation grammar
(`find_act_relative_citations`) over every text record in a detection
artifact and takes the union of act names it recognizes. The detection
artifact pinned here, `output/citation-bakeoff-2026-08-02/detection.json`
(digest `sha256:6a6bbfe8...`), was itself built from
`output/rin-ontology-revision-candidate/unified_agenda.parquet` — **an
earlier, much smaller Unified Agenda snapshot: 3,954 rows, 4,777 distinct
authority strings** (see `../spicy-regs/docs/evidence/citation-bakeoff-2026-
08-02.md`). That bootstrap corpus cited only 27 distinct act names the
Popular Name Tool recognized. 27 names resolved to 25 distinct Table III
keys (two pairs of names shared a key); one of those 25 failed to fetch
(119-21); 24 were reached. **The corpus now used for resolution is far
larger** — see §3 — which is the root of the mismatch: the acts-to-fetch
list was never revisited as the corpus grew.

**No builder tool exists in this repository.** `parser_version:
"uscode-olrc-parser-v2"` and every receipt field name (`acts_reached`,
`acts_with_division`, …) appear nowhere in RefSpec's `tools/` or `src/`
except as *consumers* — `src/refspec/registry/act_resolution.py`,
`src/refspec/registry/unified_agenda_parquet.py`, and
`tests/test_act_resolution.py`. `output/` is entirely `.gitignore`d
(`.gitignore:8`), so there is no git history to check here either. The
builder lives in the sibling repository, confirmed by `act_resolution.py`'s
own provenance note ("ported from `spicy_regs/ontology/act_index.py`"):

- `../spicy-regs/tools/build_usc_act_index_artifact.py` (375 lines) — fetches
  the popular names page, resolves the requested act names to Table III
  keys, fetches each key's Table III page, writes the three parquet files
  and the receipt. Last touched 2026-08-02
  (`93233bf`, "discriminate acts sharing a public law by division and Stat.
  page").
- `../spicy-regs/tools/build_usc_source_credit_artifact.py` — the companion
  builder for `output/usc-source-credit-index-2026-08-02/`, a *different*
  source entirely: it parses `sourceCredit` elements out of the full current
  U.S. Code USLM XML release (`uscAll@119-102.zip`, all 58 titles, 108.6 MB),
  not Table III. Its coverage is 109 public laws / 3,721 unambiguous credit
  rows — two orders of magnitude short of Table III's reach, which is why
  `act_resolution.py` treats it as a spot check, not a peer (`SOURCE_
  COMPOSITION_RULE`).
- `../spicy-regs/src/spicy_regs/sources/uscode_olrc.py` — the actual HTTP
  fetch/parse layer both act-index pieces sit on.

## 2. The bulk file already holds most of what full coverage needs

`output/registry-real-data-sources/olrc-table3-xml-bulk-119-73.zip` (14.97 MB
zipped, mtime 2026-08-06) contains one file, `fulldump@119-73.xml` —
**126,260,704 bytes** of un-nested `<act>` blocks with no wrapping root
element (not well-formed XML by itself; needs a streaming/regex reader or a
synthetic root, not `ET.parse`). Measured directly:

    <act> elements               48,973
    <record> elements (rows)    317,590
    congress range                1 – 119   (1789-06-01 through 2026-01-23)
    most recent <num>            119-73   (matches the filename/release point)

Each `<act>` carries `congress`, `date`, `statutes-at-large-volume`, and a
`<num>` that is either a modern `CONGRESS-NUMBER` public-law identifier
(`116-260`) or a bare chapter number for pre-1957 acts; each `<record>`
child states `<act-section>`, `<statutes-at-large-page>`, and either
`<united-states-code-status>` (pre-codification acts, R.S./chapter era) or
`<united-states-code-title>` + `<united-states-code-section>` (modern). This
is structurally Table III, not a re-derivation of USLM `sourceCredit`
elements — confirmed by a prior, unrelated investigation,
`research/vocabulary-atlas-spine-and-rings-takeaways-2026-08-06.md:469-484`,
which found and downloaded this same file on 2026-08-05 for Atlas
relation-edge work ("the one additive statutory dataset found") and
explicitly notes it "also covers provisions never classified to the Code and
classifications later superseded — neither of which appears in source
credits at all." **That note never connects back to `act_resolution.py`'s
coverage gap, and nothing in either repository's `tools/`, `src/`, or `tests/`
references `fulldump` or the zip's filename outside that one paragraph** —
confirmed by grep across both trees.

**Cross-checked against the pinned artifact**, using the key-derivation rule
the per-page URLs already imply (`{congress-number}` verbatim when the `<num>`
is already `CONGRESS-NUMBER`-shaped, else `{year of <date>}:{<num>}` —
verified exactly reproducing `1948:758` for the Federal Water Pollution
Control Act, an act the pinned index names but never fetched):

    table3 keys the popular-name index names (index.table3_key_by_name)   8,391
      present in the bulk XML                                             7,546   (89.9%)
      absent from the bulk XML                                              845   (10.1%)

    table3 keys the pinned artifact actually fetched                         24
      present in the bulk XML                                                24   (100.0%)

Every law the current artifact managed to fetch one page at a time is also in
the bulk file, plus 7,522 more it never asked for. The 845 that are absent
from *both* are not obviously a bulk-file defect: spot-checking one
(`District of Columbia Revenue Bond Act of 1989`, table3_key `101-158`, and
`Notice to Lessees Numbered 5 Gas Royalty Act of 1987`, table3_key `100-234`)
against the **live** OLRC site — `https://uscode.house.gov/table3/100_234.htm`
— returns a direct **HTTP 404** right now, not a timeout or a block. That is
consistent with (not proof of) these being genuinely absent from OLRC's own
Table III rather than an artifact of this particular bulk download; it was
not investigated further than that one primary-source check.

**This settles the acquisition-vs-ingestion question: acquisition is
essentially done.** What's missing is a reader for `fulldump@119-73.xml`
(or a rebuild of `build_usc_act_index_artifact.py` that consumes it instead
of / in addition to per-page fetches) and a re-derivation of
`usc-act-sections.parquet` and the popular-names table's `table3_key`
join — the two use different key spellings for pre-1957 acts (`search-key`
in the bulk file is full-date-based, `1948-06-30:758`; the pinned artifact
uses year-only, `1948:758`) and that transform needs to be made a real,
tested part of the build rather than a one-off reverse-engineered rule.

## 3. The population full Table III coverage would answer

`output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_
legal_authorities.parquet` — 798,114 rows total (receipt.json says
797,170; the parquet on disk is dated 2026-08-22 15:05, built from a
currently **uncommitted** local diff to `src/refspec/registry/
unified_agenda_parquet.py` and its test — worth knowing before treating this
as reproducible from `git log`, though nothing about that diff looks
Table-III-related from its `git diff --stat`).

`usc_title` and `usc_section` are present as columns but **never populated
for `authority_type = 'act_relative'` rows** (0 of 7,063 checked) — this
artifact carries parsed citations only; resolution genuinely happens live,
matching `act_resolution.py`'s own claim that "there is no checked-in lookup
of answers." So every row with a stated `act_section` needs live resolution
to answer "does this have a U.S.C. section":

    act_relative rows                                    9,065
      with a stated act_section                          7,063
      distinct (act_key, act_section) pairs                 582
      distinct act names among them                         114

Resolving all 582 pairs through the real pinned `ActIndex` +
`SourceCreditIndex` (both sources consulted, exactly as
`resolve_act_relative_citation` does it in production):

    resolved                              205 pairs   3,621 rows
    unresolved, by reason:
      act_section_not_classified          364 pairs   3,382 rows
        — never fetched (table3_key absent from
          index.classifications)          314 pairs   3,042 rows
        — fetched, genuinely not classified 50 pairs     340 rows
      usc_section_not_expressible           8 pairs      48 rows
      act_section_outside_act               1 pair        6 rows
      act_not_in_index                      2 pairs       3 rows
      source_incomplete                     2 pairs       3 rows
    total                                 582 pairs   7,063 rows

**The 3,042-row / 314-pair "never fetched" population is exactly what full
Table III coverage answers.** It concentrates hard: 86 distinct acts account
for all of it, and the top few dominate —

    rows   pairs  act                                                table3_key
     945     24   federal water pollution control act ("Clean Water Act")  1948:758
     286     14   clean air act amendments of 1990                        101-549
     268     31   communications act of 1934                              1934:652
     197     12   commodity exchange act                                  1922:369
     193     15   immigration and nationality act                         1952:477
     135     22   medicare prescription drug, improvement, and
                  modernization act of 2003                               108-173
     111     18   resource conservation and recovery act of 1976          94-580
     105     28   medicare, medicaid, and schip benefits improvement
                  and protection act of 2000 ("BIPA")                     106-554
      69      4   energy independence and security act of 2007            110-140
      46     10   dodd-frank wall street reform and consumer
                  protection act                                          111-203
      38      2   fair labor standards act of 1938                        1938:676
      36      4   patient protection and affordable care act              111-148
      33      6   federal insecticide, fungicide, and rodenticide act     1947:125
     ...     ...  (73 more acts, each under 30 rows)

The Federal Water Pollution Control Act alone — cited under its popular
alias "Clean Water Act" — is 31% of the never-fetched population by itself,
and every one of the top 8 is a workhorse environmental, health, or
telecom/financial statute of exactly the kind that dominates real
rulemaking. This is the population "extend Table III coverage" would move,
and it is concentrated enough that fetching the bulk file's classifications
for these 86 acts alone (all already inside the 7,546 the bulk file covers,
confirmed by spot check on the top 5) would resolve nearly all of it without
touching the long tail of the other ~7,500 named-but-unfetched acts.

Two small, separately-diagnosable populations, named so they aren't
conflated with the coverage story: `source_incomplete` (3 rows / 2 pairs) is
entirely the "One Big Beautiful Bill Act" — it maps to table3_key 119-21,
the *one* fetch that failed (§1); retrying that single URL likely clears it.
`act_not_in_index` (3 rows / 2 pairs) is `'obra'` alone — genuinely
ambiguous, not a coverage gap: "OBRA" without a year matches multiple
Omnibus Budget Reconciliation Acts (1986, 1987, 1989, 1990, 1993...) and
`ALIAS_YEAR_RULE` correctly refuses rather than guess, the same rule that
protects "Clean Air Act Amendments." `'obra'` also shows up independently in
§4's whole-index sweep, in the "see-also-dead-ends" bucket — the same name,
found by a completely different measurement.

*A discrepancy worth flagging, not resolving here*: `act_resolution.py`'s own
module docstring (ported from spicy-regs) states "534 of the 752 pairs the
Unified Agenda corpus produces refuse under this code
[`act_section_not_classified`]." The number measured here against the
artifact currently on disk is 364 of 582. No file in either repository
reproduces "752"/"534" as a checked-in count (only the docstring and the
test that cites it), so it cannot be re-derived from what's pinned — most
likely it was measured against an earlier build of the Unified Agenda
parquet, before today's uncommitted edit, or against a different corpus
slice (`tools/measure_act_relative_resolution.py` in spicy-regs, not audited
here). The 582/364/314 figures above are reproducible right now against
`output/usc-act-index-2026-08-02/` and the parquet as it sits on disk.

## 4. The 21-of-115 finding: confirmed exactly, but the "spelling" framing overstates the fix

`tests/test_act_resolution.py::test_the_refusals_are_mostly_names_the_tool_
does_list` already pins this — the "21 of 115" figure is not new, it is
this test's own headline, reproduced exactly:

    every name the tool writes anywhere (as an entry or as a
    cross-reference target) that resolve_act_name cannot answer       115

      cited-without-a-table3-key         63   OLRC lists the act by
                                                exactly this spelling; it
                                                simply never assigned it a
                                                Table III key (Congressional
                                                Review Act, Anti-Deficiency
                                                Act, Paperwork Reduction Act,
                                                FOIA, the Emancipation
                                                Proclamation, the Nineteenth
                                                Amendment...)
      see-also-dead-ends                 27   has its own "see also," but
                                                the whole chain never
                                                reaches a table3-keyed name
      named-only-as-a-see-also-target    21   no entry of its own anywhere
                                                — exists only inside
                                                someone else's "see also"
                                                text; this is the strict
                                                "not in index" case
      cited-but-stored-unreachably        4   OLRC lists it, WITH a
                                                table3 key, under a
                                                spelling normalize_popular_
                                                name cannot reach from any
                                                query

**The task's framing — "the others are in the index under a spelling the
resolver did not try" — was tested directly and does not hold for most of
the 94.** For every one of the 115 names, every name in its stated alias
chain was expanded through the same variant families
`_act_name_spelling_closure` already generates (trailing year style: `,
YYYY` / ` of YYYY` / ` YYYY` / year-dropped; `&` ↔ `and`; `and`-dropped) plus
a leading-article strip, and checked against `index.table3_key_by_name`:

    of 115 refused names, reachable via a spelling variant of
    itself or of a name in its stated chain                      4
      via a leading "the " strip                                 4
      via a year-style variant                                   0
      via & / and swap                                           0
    remain genuinely unreachable                                111

The 4 rescued: `'fess-kenyon act'` and `'improving emergency
communications act of 2007'` (both `see-also-dead-ends`) chain to
`'the vocational rehabilitation act'` and `'the 911 modernization act'`
respectively — both of which are themselves in the `named-only-as-a-
see-also-target` bucket, and both resolve the instant "the " is stripped
(`vocational rehabilitation act` → table3_key `1920:219`; `911
modernization act` → table3_key `110-53`). So the corrected picture, if the
one fix below were made, is 19 (not 21) genuinely-absent names and 25 (not
27) genuinely-dead-end chains — a small, precisely-scoped win, not the
"most of 94" the task's framing suggested.

**Root cause of the 4, found in the code, not guessed:** a leading-article
strip already exists — `_LEADING_ARTICLE = re.compile(r"^the\s+")` in
`src/refspec/registry/unified_agenda_parquet.py` — but it is applied only in
`_act_prose_recoveries`, to raw corpus TEXT, as one fallback inside the
Unified Agenda prose-matching layer. It is never applied inside
`act_resolution.py`'s own `stated_name_chain` / `resolve_act_name`, which
walks the Popular Name Tool's *own* "see also" cross-reference text
verbatim (through `normalize_popular_name`, which casefolds, straightens
apostrophes/dashes, and strips *edge* punctuation, but does not strip a
leading article). When OLRC's own alias text reads "see The Vocational
Rehabilitation Act," the stored `see_also_key` keeps "the " and the chain
walk never retries without it. `_act_name_spelling_closure` (the corpus-side
closure) doesn't generate a leading-article variant either — only
`_act_prose_recoveries` does, and only for query text, never for names
already inside the OLRC index.

**The other 111 are not spelling problems**, and no amount of variant
generation reaches them:

- The 63 `cited-without-a-table3-key` names are matched *exactly* — the
  resolver finds the name on the first try. The gap is that OLRC's own
  Popular Name Tool states no Table III key for that name at all. This is a
  source characteristic (these are mostly free-standing procedural statutes
  or entirely-uncodified historical instruments — proclamations, a
  constitutional amendment, resolutions), not a defect this module or a
  spelling closure can fix. `test_the_refusals_are_mostly_names_the_tool_
  does_list` already flags that these deserve their own reason code
  distinct from `act_not_in_index`, since "the tool lists it" and "the tool
  has never heard of it" are different facts a consumer needs told apart.
- Most of the 27 `see-also-dead-ends` are the same fact wearing a
  cross-reference: e.g. `'norris-la guardia act'` *and* `'norris-laguardia
  act'` — two different stored spellings of the same 1932 labor-injunction
  act — are **both** in the `named-only-as-a-see-also-target` bucket. Every
  spelling this act is known by dead-ends at "no Table III key," which is a
  statement about the act (much of it was never classified as a whole), not
  about which of its spellings got tried.

## 5. Recommendation

**Primary fix — ingest what's already acquired (no new fetches for 89.9% of
coverage):**

1. Write (or extend `build_usc_act_index_artifact.py`, ported into this
   repo or run from spicy-regs) a reader for
   `output/registry-real-data-sources/olrc-table3-xml-bulk-119-73.zip` →
   `fulldump@119-73.xml`. It is not well-formed XML on its own — a
   streaming or regex-based reader is needed, not `ElementTree.parse`
   directly (confirmed above; iterparse also fails on the "junk after
   document element" the missing root causes).
2. Formalize the key transform this report reverse-engineered:
   `CONGRESS-NUMBER` verbatim for modern `<num>` values, `{year(date)}:{num}`
   for pre-modern ones — and make it a tested part of the build, not an
   ad hoc derivation, since it has to match `usc-popular-names.parquet`'s
   existing `table3_key` join exactly.
3. Re-seal `usc-act-sections.parquet` from the bulk file for the 7,546 of
   8,391 named acts it already covers (24 already-fetched laws included,
   confirmed 100% present). Zero new network requests for that portion —
   the cost is the reader plus the join, not acquisition.
4. Retry the single failed fetch, `https://uscode.house.gov/table3/119_
   21.htm` (Pub. L. 119-21, "One Big Beautiful Bill Act") — a transient
   `RemoteProtocolError` after HTTP 200, not a 404; one page.
5. Optional, secondary: fetch the remaining ~845 keys (10.1%) individually
   through the existing per-page scraper if perfect coverage is wanted —
   small, and a live spot-check (§2) suggests some fraction of these are
   genuinely absent from OLRC's Table III rather than fetchable, so this
   tranche should be measured, not assumed to close cleanly.

This one change is what moves the §3 number: it would resolve the acts
responsible for the large majority of the 3,042-row never-fetched
population (the top 8 acts alone are 2,240 of 3,042 rows — 73.6% — and all
are confirmed present in the bulk file).

**Secondary, small, independently-scoped fix:** extend the alias-chain walk
in `act_resolution.py` (`stated_name_chain` / `resolve_act_name`) to also
try a leading-article-stripped variant of each stated cross-reference
target — mirroring `_LEADING_ARTICLE` from `unified_agenda_parquet.py` — and
fold `_NAME_EDGE`'s straightening order in `citation_grammar.py` so
curly-apostrophe/backtick conversion happens *before* edge stripping, not
after (the four `cited-but-stored-unreachably` names — `` ``Kick-Back''
Racket Act ``, `` ``SPARS'' Act ``, etc. — open with a backtick pair; the
edge-strip regex doesn't recognize a backtick as edge punctuation, the
curly/backtick-straightening pass runs after it and leaves a stray leading
`'` that no query ever reaches). Together these two fixes are worth exactly
4 + 4 = 8 of the 115 names — small, precisely bounded, and should not be
sold as closing the "94."

**What full Table III coverage would not fix**, so it isn't miscounted
against the acquisition/ingestion work above: the 63 names OLRC itself never
assigned a key to, the residual ~25 dead-end chains behind them, the 19
names with no entry of their own, the `usc_section_not_expressible` rows (a
separate rkaf lexical-space gap over notes/ranges/lists), and `act_section_
outside_act` / `sources_disagree` (genuine multi-source conflicts that
Table III and the source credits are supposed to surface, not artifacts of
missing data).
