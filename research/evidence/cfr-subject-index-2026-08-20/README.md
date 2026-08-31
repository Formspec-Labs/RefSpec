# CFR List of Subjects — the publisher's own per-part index

**2026-08-20.** The Office of the Federal Register's `(CFR title, part) → index
terms` mapping, captured from all fifty title pages, digest-pinned and parsed
fail-closed.

## Why this exists, and the error it corrects

`src/refspec/registry/cfr_list_of_subjects.py` established — correctly, and
reverified live today — that the **eCFR** APIs publish no per-part List of
Subjects. Its drift tripwire still fires on nothing.

That true statement about eCFR was then read as a statement about the world,
and this repository built on that reading twice: the module chose
document-level Federal Register evidence as "the machine-readable source", and
`../cfr-part-subjects-2026-08-20/` states outright that "the authoritative list
does not exist as a machine-readable publisher artifact".

**It does exist.** The OFR publishes it directly:

```
https://www.archives.gov/federal-register/cfr/subject-title-01.html … -50.html
```

Its own header: *"a list of Code of Federal Regulations (CFR) Subjects arranged
by CFR Title and Part… Select a CFR title to view the indexing terms currently
assigned to individual parts."* Revised annually, public domain,
robots.txt-permitted with `Crawl-delay: 10`. It had been cited in this repo's
own research archive since 2026-07-28 and neither the module nor the earlier
artifact referenced it.

## What it contains

| | |
|---|---:|
| assignments | **32,200** |
| part entries | 8,426 |
| distinct CFR parts | **8,423** |
| distinct terms | 1,068 |
| titles present | 49 *(title 35 is reserved)* |
| pages captured and pinned | 50 |

Part entries and distinct parts differ by three because the publisher lists
7 CFR 1000, 29 CFR 4231, and 48 CFR 642 twice each.

`part-subjects.csv` — `cfr_title`, `cfr_part`, `part_heading`, `term`.
`source-pins.json` — per-page source URL, SHA-256, byte length, part count.

## Against the witnessed table it supersedes

`../cfr-part-subjects-2026-08-20/` inferred nothing, but could only see parts
that Federal Register documents happened to cite alone:

| | witnessed | **publisher index** |
|---|---:|---:|
| parts | 4,256 | **8,423** |
| terms | 852 | 1,068 |
| attribution | witnessed from single-part filings | **asserted by the publisher** |
| multi-part problem | 15.1% of documents discarded | **does not arise** |

The publisher has already done the per-part attribution — that is the entire
purpose of the page — so the problem that forced the witnessed table to throw
away 15.1% of its evidence simply does not exist here. And it sees **1.97×** as
many parts.

## Thresholding is not available on this source

The index is a **flat per-part list**: `40 CFR Part 1` carries
`["Environmental protection", "Organization and functions (Government
agencies)"]` and that is all. No counts, no dates, no weights.

This is stated rather than omitted because a consumer of the witnessed table
scored it at F1 61.0 by using it unfiltered — it was an accumulated union and
they had no lever. This source cannot be over-inclusive in that way, since it
is the publisher's current assignment rather than 26 years of accumulation.
But **if it is wrong for some part, there is no threshold to turn.** Know that
the lever is absent rather than assuming a column was forgotten.

## Self-sufficient

Unlike the witnessed table, this needs no Federal Register corpus to consume.
The mapping *is* the artifact.

## Parser posture

`parse_cfr_subject_index` is fail-closed in both directions. Every `<dt>` that
names a CFR citation must yield a title and a part, or the parse **raises** — an
unmatched entry is never skipped. A page whose entries declare a different title
than its pin raises. A reserved title may be empty; a *populated* reserved title
raises, because that would mean the title was un-reserved.

The publisher's hand-maintained HTML carries four recurring irregularities, each
handled **by name** and counted, so that a malformation of a kind not seen before
surfaces as a reject instead of joining a permissive catch-all:

| irregularity | occurrences | example |
|---|---:|---|
| missing `Part` keyword | 13 | `2 CFR 401_…` |
| `Oart` for `Part` | 1 | `48 CFR Oart 739_…` |
| em-dash for `_` | 1 | `40 CFR Part 60—…` |
| leaked `<strong>` tag | 1 | `strong>48 CFR Part 2952_…` |
| **part heading marked `<dd>` not `<dt>`** | **32** | `<dd><strong>40 CFR Part 1033_…</strong></dd>` |
| **rejects** | **0** | — |

The fifth is the consequential one and it was **not** caught by the fail-closed
posture, because a `<dd>` containing text is structurally valid. It surfaced
only when resolving terms against Atlas, where part headings appeared among the
unresolved "terms". Left alone it is doubly wrong: the mistyped part vanishes
entirely *and* its terms are attributed to the part above it. Recovering the 32
adds 35 parts and removes 32 spurious terms.

Only same-title citations are treated as mistyped headings; a `<dd>` naming a
different title is a cross-reference and stays a term.

Zero rejects from a permissive regex would mean nothing. Zero from a parser
that raises on every unmatched entry means the pattern covers the data.

## How far agencies stray from the controlled vocabulary

**State the folding, because three readings are defensible and they disagree by
3 points.** The numerator moves with the denominator, so each row below is
internally consistent — but a ratio quoted without naming its folding is
under-specified:

| folding | resolve | of | rate |
|---|---:|---:|---:|
| verbatim | 943 | 1,068 | 88.3% |
| **lowercased (used here)** | **953** | **1,043** | **91.4%** |

Mixing them — 953 lowercased resolutions over a 1,068 verbatim denominator —
gives 89.2% and means nothing. That is the same mixed-denominator error this
project's tagging survey already records against its own coverage table,
recurring in a different file.

### The spread is itself a finding about the publisher

The 1,068 → 1,043 collapse is not a modelling choice; it is transcription
drift in a controlled vocabulary. **24 keys carry case variants across 49
distinct strings:**

```
Government Procurement | government procurement | Government procurement
Authority delegations (Government agencies) | ... (government agencies)
Aid to Families with Dependent Children | Aid to families with dependent children
Grant programs-Education | Grant programs-education
Flood Plains | Flood plains
```

Separator drift compounds it — em-dash against hyphen, underscore against
hyphen, doubled hyphens — so one concept can appear three ways.

A consumer keying on verbatim strings therefore sees roughly **2.4% more
"terms" than there are concepts**, entirely from spelling. That is a fact about
how the OFR maintains the list, not about the data being wrong, and it is worth
reporting rather than silently folding away.

*(The mixed-ratio risk was raised by a parallel session and checked here; the
case-variant count is its finding, verified independently.)*

**Denominator correction, 2026-08-20.** This table first reported 88.7%. The
numerator (953) was right and the denominator was stale: it was computed over
1,075 terms, *before* the mistyped-`<dd>` fix removed 32 part headings that had
been admitted as terms. Over the corrected 1,043 the rate is **91.4%**. The
fix was applied to the artifact and not propagated to a statistic derived from
it in the same document.

Counting note: 1,043 is distinct terms **case-folded**. Verbatim it is 1,068 —
the publisher spells some terms two ways. And the index carries **8,426 part
entries** over **8,423 distinct parts**: three parts (7 CFR 1000, 29 CFR 4231,
48 CFR 642) are listed twice by the publisher.

1 CFR 18.20 requires index terms drawn from the Federal Register Thesaurus but
permits agency-added terms, so the resolution rate against Atlas measures how
far agencies actually depart from the controlled vocabulary. Measured:

| | terms | share |
|---|---:|---:|
| resolve to `federal-register-api-topics` | 863 | **80.8%** |
| resolve to `federal-register-thesaurus-2025` | 713 | 66.8% |
| resolve to either | 869 | 81.4% |
| **unresolved by both** | **199** | 18.6% |

But weighted by use, the departure is far smaller: the 199 terms neither
Federal Register vocabulary carries account for **412 of 32,200 assignments —
1.28%**.

And most are not agency inventions. They are near-misses of thesaurus terms:

```
administrative practice and procedures   (plural; thesaurus has singular)
reporting and recordkeeping              (truncated)
indian-tribal government                 (separator variant)
foreign investments in u.s               (lost terminal period)
```

So agencies comply with the controlled vocabulary closely, and the residue is
dominated by transcription drift rather than by genuine local terms. That is a
vocabulary-governance finding in its own right, independent of any consumer.

**Correction, 2026-08-20.** An earlier draft of this table reported 1,043
distinct terms, 953 resolving "somewhere in Atlas" (88.7%) and 122 unresolved.
Those figures do not reproduce against the CSV this directory ships, which
carries 1,068 distinct terms, and the wider set they were measured over was
never stated. The rows above are measured by
`tests/test_atlas_v3_registry_rosters.py` against exactly two named schemes and
fail if they move. The Atlas release built from this capture resolves against
`federal-register-api-topics` alone: 863 terms, 205 skipped and counted.

**Terms ship as publisher strings, not concept identities.** Resolving them is
a deliberate separate step; this artifact records what the publisher wrote.

## Limits

- **Annual cadence.** The pages are "current as of April 1, 2025"; the capture
  is 2026-08-20. Revalidation should follow the publisher's annual cycle.
- **Not all terms are Federal Register Thesaurus terms.** 1 CFR 18.20 permits
  agency-added terms, so resolution against the
  `federal-register-api-topics` scheme will not be total and needs an actual
  pass rather than an assumption.
- **No concept identity claimed here.** This artifact carries term *strings* as
  the publisher writes them. Resolving them to Atlas concepts is a separate,
  deliberate step -- taken in `src/refspec/atlas/v3_registry_rosters.py`, which
  turns these pages into 8,423 legal-identity CFR parts and 31,683
  `atlas:hasIndexedSubject` cross-ring relations. The fifty pages are tracked
  and digest-pinned under `tests/fixtures/cfr_list_of_subjects/subject-index/`;
  this directory keeps the derived CSV, not the source bytes.
