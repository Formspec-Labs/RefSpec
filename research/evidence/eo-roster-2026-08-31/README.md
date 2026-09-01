# Executive Order existence roster — promotion (2026-08-31)

Promotes `inv-eo` / `inv-eo-gap` (`research/evidence/investigations-2026-08-2{3,4}/`)
through the digest-pin ceremony this repository requires before a research
finding becomes a reference: re-derive from raw bytes, diff against the
investigation copy to account for every difference, pin the result by sha256,
ship a reader with a receipt-worthy test suite. The reader is
`src/refspec/registry/eo_roster.py`; its tests are `tests/test_eo_roster.py`.

## Why this exists

Today the only fence on an Executive Order citation is
`citation_grammar.EO_HIGHEST_KNOWN` — a bare `1 <= n <= 14_420` range check.
It cannot tell a real order from a plausible-looking typo: 43 unresolved
numbers / 2,876 rows pass it and read as valid citations, and EO rows are the
second-largest unjudged family in the note census
(`research/investigations-mined-2026-08-31.md`, item 5).

## EO 8284 exists — and this lane said otherwise before review

An earlier draft of this promotion claimed **"8284 does not exist at all"** on
the strength of one NARA per-order detail route returning a Drupal
"Page Not Found". That was wrong, and the repository's own committed evidence
had said so all along:

* `research/evidence/silent-misreads-2026-08-22.md` (item 6): *"EO 8284 is
  'Prescribing the Duties of the Librarian Emeritus', which confers no fee
  authority"* — a real order, cited where a different one was meant.
* `research/evidence/silent-misreads-2026-08-24/adjudication/B_2.tsv`, row 2:
  verdict `MISREAD_LAUNDERED`, publisher check against NARA's 1939 table,
  and in its own words **"8284 exists and is real, but has nothing to do with
  a governmentwide regulatory authority"**.

This lane then went to the publishers and pinned both primary sources into
`raw/`:

| Capture | What its raw bytes carry |
|---|---|
| `raw/nara-eo-1939.html` (144,520 B, HTTP 200 from `archives.gov/federal-register/executive-orders/1939.html`) | `<a name="8284"></a>` between `8283` and `8285`: **"Prescribing the Duties of the Librarian Emeritus of the Library of Congress"**, `Signed: November 13, 1939`, `Federal Register page and date: 4 FR 4603, November 17, 1939` |
| `raw/govinfo-FR-1939-11-17.pdf` (2,400,332 B, HTTP 200 from GovInfo) | The Federal Register issue of Friday, November 17, 1939, Volume 4. Its front page prints the order under "The President — EXECUTIVE ORDER", over `FRANKLIN D ROOSEVELT`, `THE WHITE HOUSE, November 13, 1939`, `[No. 8284]`, `[F. R. Doc. 39-4239; Filed, November 15, 1939; 2:38 p. m.]` |

Both are read as pixels as well as text: the PDF's page-1 crop was rendered
and looked at, because a text layer of a 1939 scan is OCR and OCR misreads
(`[No. 8284]` extracts as `[No. 82841`).

**What the 404 actually was.** NARA's *per-order detail route* has no page for
8284; NARA's *1939 disposition table* publishes the order in full. The probe
recorded a fact about one route, and this lane read it as a fact about the
order. The column in `derived/nara-order-probe.csv` is now named
`route_not_found` for that reason, and `derive_roster.py`'s docstring says
what it does and does not establish.

**What this cost, and what caught it.** One number, three corpus rows, and a
false sentence in a README. What caught it was this repository's own committed
evidence, read again — the doctrine working, one review cycle late.

## Method: re-derivation from raw bytes, verified before parsing

`derive_roster.py` reads **only** raw publisher captures, and checks every one
against a committed sha256 manifest (or, for this lane's own two captures,
against a digest literal in `RAW_CAPTURES`) **before** parsing it. A file the
glob finds but the manifest does not list is a refusal, not an input. The
investigation's own derived CSVs appear in exactly one place — the comparison
oracle in `diff_against_investigation()`, which runs after the derivation is
complete and cannot influence it.

| Population | Raw source | This lane's extraction |
|---|---|---|
| NARA codification-numeric index | 18 raw HTML pages, `inv-eo/nara/eo-01.html`..`eo-18.html` | 4,162 numbers — exact set match with `nara-codification-index.csv` |
| NARA per-order detail probes | 109 raw HTML pages, `inv-eo/nara/orders/eo-*.html` | 108 order pages + 1 route-404 (8284) — exact per-number match with `nara-order-details.csv` |
| FR-API window | 2 raw JSON pages, `inv-eo/fr-api/fr-executive-orders-page{1,2}.json` | 1,531 numbers (1,556 records, 22 with no assigned number, 3 numbers with 2 records each) — exact set match |
| 1989–1993 gap closure | 4 live NARA year pages + 2 Wayback captures, `inv-eo-gap/nara/*.html` | **223 numbers, 12,668–12,890, contiguous** — a superset of the investigation's pinned 32, field-exact on all 32 |
| NARA 1939 disposition table | `raw/nara-eo-1939.html` (this lane's capture) | **286 numbers, 8,031–8,316, contiguous** (plus the lettered `8193-A`, excluded) |

Run `.venv/bin/python derive_roster.py` from this directory (or any cwd —
paths resolve from `__file__`). It writes `derived/*.csv` and
`diff-report.txt`. The current run:

```
nara-codification-index: mine=4162 theirs=4162 match=True
nara-order-probe route verdicts: 109 probed, 0 mismatches: []
fr-api: mine=1531 theirs=1531 match=True
gap-closure: mine=223 [12668-12890, contiguous=True] theirs=32 covers-theirs=True
gap-closure field mismatches: 0 []
merged roster: mine=6147 theirs(roster|gap)=5725 lost=[] added=422
  added, explained: 190 from the gap captures' full anchor set, 232 from the pinned NARA 1939 disposition table
  added, UNEXPLAINED (expect empty): []
  EO 8284: on the roster=True source=nara-disposition-1939 (its per-order detail route 404s; the 1939 year table publishes it)
```

**Nothing lost, every addition named.** `derived/roster.csv` (6,147 rows) is
what `src/refspec/registry/eo_roster.py` pins by sha256.

### The 32-number intersection had to go, and it was hiding a bug

An earlier draft derived gap *membership* by intersecting the raw extraction
with the investigation's own derived `eo-gap.csv`. That made "raw bytes only,
zero drift" circular — the comparison could not fail, because the thing being
compared had been cut to fit. Membership now comes from the raw pages alone.

Removing the intersection immediately exposed a parser defect it had been
hiding. The old parser matched entries by prose, requiring a well-formed
`Federal Register page and date:` line. **EO 12825's is malformed** — NARA
prints `57 FR 60973; 22, 1992`, with the month missing — so the match ran on
through EO 12826's entire entry: 12825 got a run-on title and *12826's* date
and citation, and **EO 12826 vanished from the roster**. Neither number was
among the pinned 32, so the intersection swallowed both symptoms, and the
earlier README published the consequence as a finding about the publisher:
*"222 of the 223 numbers … only 12826 is absent from the raw HTML."*

The parser is now anchored on each entry's own `<a name="NNNN"></a>`, so a
malformed line inside one entry cannot let it swallow the next. The gap run is
**223 of 223, contiguous** — 12826 ("Adjustments of certain rates of pay and
allowances", signed December 30, 1992, 57 FR 62909) was in NARA's bytes the
whole time. The anchor rule also handles NARA's two markups: the current one
puts the anchor inside the heading, the older one — preserved in both
Wayback-captured 1993 pages — puts it before a heading that is itself a PDF
link.

## Method: measurement against the corpus's own cited-EO census

`measure.py` reads the roster *through the shipped oracle* (so it measures the
verdicts a consumer gets, pin check and all) against the investigation's
`cited-eo-census.csv`, bound by the digest that investigation committed:

```
COVERED (verdict=exists): 378 numbers / 18954 rows
UNCOVERED: 13 numbers / 57 rows
  'nara_window_miss': 10 numbers / 50 rows -> [1197, 1205, 1220, 1223, 1293, 1327, 1338, 3019, 3891, 7419]
  'outside_known_windows': 3 numbers / 7 rows -> [20450, 21600, 23891]

mined expectation: {'numbers_covered': 377, 'rows_covered': 18951, 'numbers_unknown': 11}
measured (this script): {'numbers_covered': 378, 'rows_covered': 18954, 'numbers_unknown': 10}
delta: numbers_covered +1, rows_covered +3, numbers_unknown -1
```

The whole delta from the mined expectation is EO 8284. Full output in
`measure-output.txt`. The 13 uncovered numbers:

* **9 pre-1929** (`1197, 1205, 1220, 1223, 1293, 1327, 1338, 3019, 3891`, 46
  rows) — pre-Hoover, outside the NARA disposition-table era.
* **1 FDR-era** (`7419`, 4 rows) — inside the codification window's number
  range but outside both the 1945–1989 codification project the numeric index
  covers and the one calendar year this lane's disposition capture holds.
  Resolving it needs NARA's 1936 table, fetched and pinned the same way 1939
  was; that is the obvious next capture.
* **3 already flagged** (`20450, 21600, 23891`, 7 rows) — these exceed the
  roster's own measured ceiling and are *already* caught by today's
  `eo_in_known_series` fence.

`tests/test_eo_roster.py::test_measured_against_the_cited_eo_census`
reproduces this from the *shipped module*, not this script, over a
digest-bound census, so a future roster promotion that silently changes
coverage breaks a running test.

## The window split, and where absence authority comes from

A roster miss means two different things depending where the missed number
falls. Each window carries a measured density; exactly one may say `absent`.

| Window | Range | Density on the pinned roster | May say `absent`? |
|---|---|---|---|
| `nara_codification` | 9 – 12,667 | 4,394 / 12,659 = **34.7%** | no |
| `nara_disposition` | 12,668 – 12,889 | 222 / 222 | **no** — see below |
| `fr_api` | 12,890 – 14,420 | 1,531 / 1,531 | yes |
| (neither) | < 9, > 14,420 | no claim | no |

**`FR_API_DENSE_MAX` is evidence, not the grammar's ceiling.** An earlier
draft bound the dense window's top to `citation_grammar.EO_HIGHEST_KNOWN`,
and called that binding a safety feature. It was the opposite: the constant
moves when a new order is signed, the pinned roster does not, and the module
would have started publishing `absent` for numbers no capture had ever seen —
`verdict(14421)` would have answered "absent" on no evidence at all. The bound
is now the largest number the FR-API capture assigns, `EoRosterOracle` no
longer imports the grammar at all, and `_verify_density` refuses to load a
roster that does not fill the declared window. The two values coincide today
(14,420) and nothing asserts that they must.

**Why `nara_disposition` measures 222/222 and still cannot say `absent`.**
Its density is total *for the run of years those captures cover* — which is a
much weaker claim than the FR API's own record of every assigned number, and
promoting it would widen absence authority by ~220 numbers as a side effect of
a parser fix. That is exactly the kind of quiet widening this ceremony exists
to prevent. It stays affirm-only until someone measures it on purpose.

**A consequence worth stating plainly: `absent` is currently unreachable.**
The density check that licenses `absent` is the same fact that leaves the
window no misses. So `verdict()` cannot return `absent` on any roster that
loads today, and `tests/test_eo_roster.py::test_todays_dense_window_has_no_misses_at_all`
pins that as a measurement rather than leaving it implicit. The verdict is not
dead structure: it is what the oracle would say if a re-derivation ever
re-declared a dense window around a genuine hole, and a human re-pins before
it ever says it.

**Live negative fixture** (raised by a sibling lane mid-task): the
prose-harvest lane's amendment-chain walk cites **EO 9397** (1943, the order
that created Social Security numbers) as a chain endpoint. It is a real,
famous order, it falls inside the sparse NARA window, and it is **not** on the
roster. The oracle answers `unknown`, exactly as designed; asserting `absent`
here would be a straightforwardly false statement about a real order — which
is the same failure mode, in the other direction, as the 8284 claim this
review caught. See `test_eo_9397_amendment_chain_endpoint_is_unknown_not_absent`.

## Every verdict is checked against every other field

`EoVerdict.__post_init__` enforces full coherence, because the failure this
module exists to prevent is a verdict that *reads* coherent and is not:

* `window` must be the window that actually **contains** the number. An
  earlier draft labelled all 32 gap rows `nara_codification` while they sit
  above that window's top (EO 12866 among them), so a consumer could receive
  an `exists` whose authorizing window did not contain the number. The gap
  rows now carry `nara_disposition`, which does.
* `exists` must name a `source` in `SOURCE_RANGES` **whose own declared range
  contains the number** — a roster row naming a capture that never saw that
  number cannot publish an existence claim. The ranges are measured by
  `derive_roster.py` (it prints them) and re-verified at load, so one cannot
  be widened past the evidence to wave a number through.
* `absent` requires a window in `ABSENT_CAPABLE`.
* `reason` is set iff the verdict is `unknown`, and must agree with the
  window, so "inside a sparse window" and "outside every window" cannot swap.

Each rejected construction has its own negative fixture in the test suite.

## EO 8284 as a hand-validated flag

`src/refspec/registry/hand_validated_interpretations.py` carries a `flag` row
for source value `"8284"`, and `EoRosterOracle.flag_for(8284)` delegates to it
rather than keeping a second copy. That row was **rewritten in this review
pass**: it used to rest its doubt on the route-404, which established nothing.
It now records that the order exists (citing the two committed witnesses
above) and that the *citation* is doubted on **relevance** — the adjudication
found a real-but-unrelated order read as the identity, where the rule's own
quartet of authorities points at EO 8248. `interpreted_value` stays `None`:
nothing committed establishes that 8284 denotes 8248, and the survey that
raised the pair says why the shape alone cannot settle it ("a lead-generator,
not a detector"). The row's notes say outright that its founding argument was
wrong, rather than quietly dropping it.

`flag_for` is now strictly a flag API: it returns `None` when no flag is
recorded (documented and tested), and **raises** if the table's row for that
value is a correction — a substitution must never reach a caller through a
method whose name promises not to make one.

**On the mined README's Wikipedia rider.** Both committed Wikipedia captures
(`inv-eo/derived/wiki-eo-8248.html`, `wiki-eo-8284.html`, 50,565 bytes each,
manifest-verified) are MediaWiki *"Wikipedia does not have an article with
this exact name"* stubs — `wgArticleId":0`, no article body, for 8248 exactly
as much as for 8284. There is no tie-break in these two files as committed.
That finding stands; only the "probe-negative" half of the rider was wrong.

The other three correction candidates the `inv-eo` investigation README names
(`23891→13891`, `20450→10450`, `21600` and `7419` refused) are **not** in this
lane's flag registry: their evidentiary basis (matching corpus row text) is
not in the committed bytes this lane read.

## Files

| File | What it is |
|---|---|
| `derive_roster.py` | Re-derivation script; every raw input verified against a manifest or digest literal before parsing |
| `raw/nara-eo-1939.html` + `.headers.txt` | NARA's 1939 disposition table, fetched and pinned 2026-08-31 |
| `raw/govinfo-FR-1939-11-17.pdf` + `.headers.txt` | The Federal Register issue carrying EO 8284 at 4 FR 4603 |
| `derived/nara-codification-index-numbers.csv` | 4,162 numbers, re-parsed from the 18 raw index pages |
| `derived/nara-order-probe.csv` | 109 numbers, with `route_not_found` |
| `derived/fr-api-numbers.csv` | 1,531 numbers, re-parsed from the raw FR-API JSON |
| `derived/gap-numbers.csv` | 223 numbers, re-parsed from the raw NARA year/Wayback pages |
| `derived/nara-disposition-1939.csv` | 286 numbers, re-parsed from this lane's 1939 capture |
| `derived/roster.csv` | **The pinned roster** (6,147 rows) |
| `diff-report.txt` | Output of `derive_roster.py`'s drift check, including the measured source ranges |
| `measure.py` / `measure-output.txt` | Measurement through the shipped oracle, over digest-bound inputs |
| `WIRING-SPEC.md` | Proposed diffs to upgrade `unified_agenda_parquet.py`'s fence to this oracle |
| `MANIFEST-sha256.csv` | sha256 and byte length of every other file in this evidence home; `tests/test_eo_roster.py` checks it in **both** directions |

## Reader module

`src/refspec/registry/eo_roster.py` — `EoRosterOracle`, `EoVerdict`. See its
module docstring for the full design (mirrors
`refspec.registry.usc_section_oracle`'s pin-and-verify shape). Tests:
`tests/test_eo_roster.py`.

## What this promotion does NOT do

* It does not edit `citation_grammar.py` or `unified_agenda_parquet.py` — see
  `WIRING-SPEC.md` for the exact proposed diff, left for a follow-up unit.
* It does not make `nara_disposition` absent-capable (see above).
* It does not resolve EO 7419 — that wants NARA's 1936 table, captured and
  pinned the way 1939 was here.
* It does not add flag rows for the other three `inv-eo` correction
  candidates.
