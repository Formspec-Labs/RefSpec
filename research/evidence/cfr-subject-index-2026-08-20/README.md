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
| CFR parts | **8,426** |
| distinct terms | 1,043 |
| titles present | 49 *(title 35 is reserved)* |
| pages captured and pinned | 50 |

`part-subjects.csv` — `cfr_title`, `cfr_part`, `part_heading`, `term`.
`source-pins.json` — per-page source URL, SHA-256, byte length, part count.

## Against the witnessed table it supersedes

`../cfr-part-subjects-2026-08-20/` inferred nothing, but could only see parts
that Federal Register documents happened to cite alone:

| | witnessed | **publisher index** |
|---|---:|---:|
| parts | 4,256 | **8,426** |
| terms | 852 | 1,043 |
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

1 CFR 18.20 requires index terms drawn from the Federal Register Thesaurus but
permits agency-added terms, so the resolution rate against Atlas measures how
far agencies actually depart from the controlled vocabulary. Measured:

| | terms | share |
|---|---:|---:|
| resolve somewhere in Atlas | 953 | **88.7%** |
| resolve to `federal-register-api-topics` | 840 | 78.1% |
| resolve to `federal-register-thesaurus-2025` | 722 | 67.2% |
| **unresolved** | **122** | 11.3% |

But weighted by use, the departure is far smaller: the 122 unresolved terms
account for **202 of 32,200 assignments — 0.63%**.

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
  deliberate step.
