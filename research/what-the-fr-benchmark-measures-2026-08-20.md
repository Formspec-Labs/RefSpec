# What the Federal Register benchmark actually measures

**2026-08-20.** A day of measurement against the Federal Register answer key
produced a consistent and initially confusing pattern: **the more authoritative
a source, the worse it scored.** This records why, because it governs how any
tagging result from this corpus should be read.

## The pattern

Every arm measured against 114,220 Federal Register documents and their
publisher-assigned `topics`:

| arm | F1 | what it encodes |
|---|---:|---|
| agency prior | **57.3** | which agency filed the document |
| CFR part prior, witnessed from filings | **89.4** | which topics filers attach to a part |
| **CFR part prior, publisher's own index** | **75.8** | what the OFR says a part is about |
| lexical matcher on document text | 18.9 | what the document says |
| lexical oracle (perfect precision) | 23.2 | what the document *could* say |

Reading the document is worst. Knowing who filed it is far better. Knowing what
filers usually attach is best. **Knowing what the regulation is actually about
is 13.6 points worse than knowing what filers habitually write.**

## Why

The task is *"predict the topics this Federal Register document was tagged
with."* Those tags were applied by agency filers following Federal Register
convention, under 1 CFR 18.20. So the benchmark rewards reproducing **filer
behaviour**, and every arm's score is really a measure of how well it models
that behaviour.

That explains all five rows:

- The **agency prior** scores 57.3 because the same agency both files the
  document and attaches its topics. It is close to tautological — not a
  discovery about subject matter but a restatement of who was in the room.
- The **witnessed table** scores highest because it is built from filings and
  scored against filings. It has learned house style, which is exactly what is
  being tested.
- The **publisher index** scores worst *because it is right about something
  else.* Where a filer's habit diverges from the OFR's own statement of what a
  part covers, the benchmark scores the authority as wrong.

The benchmark does not penalise error. **It penalises divergence from filing
convention**, and an authoritative source has more places to diverge.

## Where the divergence lives is *not* known

An earlier version of this note offered a mechanism: that the index scores worse
exactly where filing is heaviest, because high-churn parts accumulate decades of
house style that drifts from the publisher's index. The figures were
top-383 65.8 against tail 76.5 — a 10.7-point asymmetry, read as drift.

**That was retracted the same day, and the cause was a defect in this
repository's own artifact.** 32 CFR part headings were mistyped `<dd>` rather
than `<dt>` in the publisher's HTML and were being misattributed; 17 of them sat
on title 2 alone, concentrated on high-churn titles. They dragged down precisely
the top-383 bucket and manufactured the asymmetry.

Corrected:

| source | all | top-383 parts | tail parts |
|---|---:|---:|---:|
| witnessed from filings | 89.4 | 90.3 | 86.4 |
| publisher index | **75.8** | **75.9** | **76.6** |

The index performs **uniformly** across the citation-frequency spectrum. The gap
collapsed from 10.7 to 0.7.

So the headline claim survives — witnessed still beats authoritative by 13.6
points on a benchmark that scores agreement with filers — but the mechanism does
not. Uniformity means it is **not** accumulated house style on heavily-filed
parts. It is something else: different granularity of assignment, or filers
tagging the *document* rather than the *part*. Neither has evidence.

### The mechanism, measured afterwards

The open question above was then closed by measuring granularity directly. For
parts cited by exactly one document, compare terms per *document*, terms in the
accumulated *union* of all its documents, and terms in the *publisher's index*:

| part cited | terms per document | witnessed union | publisher index |
|---|---:|---:|---:|
| <5 times | 3.65 | 4.07 | 4.12 |
| 5–19 | 4.00 | 5.68 | 5.17 |
| 20–99 | 4.11 | 7.24 | 5.81 |
| **100+** | **4.85** | **12.21** | **7.37** |

**A document carries about four terms no matter what.** It barely moves across
the range — 3.65 to 4.85 — while the part's accumulated vocabulary triples. So
filers are tagging *the document*, not *the part*: each filing names what that
action is about, and a heavily-amended part accrues a wide vocabulary that no
single document ever carries.

That is the second of the two candidates, and it is now measured rather than
guessed.

It also explains why the publisher index scores *uniformly* rather than worse on
high-churn parts. The index grows 1.8× across the range where the raw union
grows 3.0×: the OFR curates a part's subject list toward what the part covers,
which stays much closer to document granularity than an accumulation of every
term any filer ever used.

So the 13.6-point gap is **not drift and not error. It is granularity.** The
witnessed table with a rate threshold learns which terms are *typical of a
part's documents* — precisely what the benchmark asks for. The index records
what the part *covers*, which is a superset of what any one document is about.
A source can be entirely correct about a regulation and still lose a benchmark
that asks what a filer wrote about one action under it.

### How much of the loss is structural, quantified

Scoring the publisher index directly against the 94,747 single-part documents
it covers:

| | |
|---|---:|
| terms the index proposes per document | 5.62 |
| terms the document actually carries | 4.63 |
| **precision ceiling from granularity alone** | **82.5%** |
| precision actually achieved | **70.8%** |
| recall achieved | 85.9% |

The ceiling is what precision would be **if the index were perfectly correct and
recall were total** — it is 4.63/5.62, purely the cost of a part-level source
proposing a part's coverage to a document that is about one action.

So of the 29.2 points of precision the index gives up:

- **17.5 points (60%) are structural** — unavoidable for *any* part-level source,
  no matter how authoritative;
- 11.7 points (40%) are genuine disagreement between the publisher's index and
  what filers wrote.

The index reaches **86% of its own structural ceiling.** That is the number that
settles it: this artifact is not substantially wrong about the CFR. It is
answering a question one level coarser than the one being asked, and most of
what looks like error is that mismatch.

### The prediction, tested: 30% right

The granularity account made a falsifiable claim — score at *part* level rather
than document level and the gap should shrink, score against the part's union
and it should vanish. Both were run:

| scoring level | source | P | R | F1 |
|---|---|---:|---:|---:|
| document | publisher index | 67.5 | 85.1 | 75.3 |
| document | witnessed @0.5 | 89.0 | 89.8 | 89.4 |
| **part (union gold)** | publisher index | **79.6** | 80.7 | 80.2 |
| **part (union gold)** | witnessed @0.5 | **98.3** | 83.0 | 90.0 |

Gap at document level **14.1**; at part level **9.8**.

**Shrinks — by 4.3 points, about 30%. Does not vanish.** And the mechanism is
visible exactly where predicted: the index's *precision* jumps 67.5 → 79.6 once
it is judged against what a part covers instead of what one document said.

So granularity is real and worth about 4.3 of the 14.1 points. The other 9.8 are
something else.

### The residual is not granularity — it is that the ground truth is filings all the way down

The witnessed table scores **98.3 precision** at part level. That is not a good
result; it is a tell. Part-level gold is the union of topics on documents citing
that part, and the witnessed table is built from documents' topics on that same
part. Train and eval documents are disjoint, but a part's vocabulary is stable
across its documents, so the table is predicting almost exactly the thing it was
derived from. **Near-perfect precision is what circularity looks like.**

Which gives the sharper statement, and it is stronger than the granularity one:

> There is no level of aggregation at which the publisher's index can win,
> because the ground truth is filings at every level. Document level asks what a
> filer wrote; part level asks what filers collectively wrote. The index is the
> only artifact in the comparison not derived from filings, and it loses at both.

That is not a property of granularity. It is a property of having only one kind
of evidence. Changing the scoring level cannot fix it, because every level of
this benchmark is made of the same material.

Any part-level prior inherits this ceiling. On a part whose index lists twelve
terms, proposing the list can be at best about 4/12 precise however correct the
list is — which is why a rate threshold that prunes toward *typical* terms
matters so much, and why a flat publisher list has no equivalent lever.

The episode is worth keeping for its own sake. A satisfying mechanism was
inferred from a 10.7-point gap that was mostly artifact, and it went
uninterrogated *because* it was satisfying.

## What the corpus is a window onto

Three further measurements bound how far any of this generalises:

- **383 of 9,320 cited parts carry 64% of all citations.** Five parts alone
  carry 22.4% — airworthiness directives, EPA state implementation plans,
  airspace designations. Anything learned from this corpus is learned mostly
  from those.
- **2,122 CFR parts — 25.3% — are never cited by any labelled document.** The
  corpus sees roughly three quarters of the CFR, most of it through a keyhole.
- **But only 59 terms appear exclusively on those invisible parts.** The missing
  quarter is invisible as *parts* and nearly transparent as *vocabulary*.

That last point is the one that limits the damage. A method trained here has
seen almost the whole term space even though it has seen only three quarters of
the parts. The bias is in *which regulations*, not in *which subjects*.

A narrow window is visibly narrow. A weighted one looks complete.

## What follows

**1. Do not report an FR-topics F1 as a tagging accuracy.** It is a
filing-convention reproduction score. Say which it is.

**2. A high score from an authoritative source is the surprising outcome, not a
low one.** If a publisher-asserted mapping ever scores *above* a
witnessed-from-filings one on this benchmark, that is evidence the convention
has converged on the authority — a genuine finding — rather than routine
success.

**3. Separate the two questions when they matter.** "What would a Federal
Register filer tag this with" is a real and useful question — it is what
predicts existing corpus metadata. "What is this document about" is a different
one, and only the second transfers to a court opinion, a research paper or a
public comment.

**4. The procedural band should be excluded from any general-tagging metric.**
`research/evidence/fr-topic-band-2026-08-20/` separates the 25.3% of the answer
key that is filing metadata — `reporting and recordkeeping requirements`,
`incorporation by reference` — from the 74.7% that is subject matter. Only the
second is a question about the document.

## Provenance

Every figure here was measured today, most of them twice by two independent
sessions working from different sides — one from the search/eval corpus, one
from the vocabulary. The per-band, per-population and top-383/tail splits are
the other session's; the vocabulary reach, band boundary and publisher-index
figures are this one's. Where the two disagreed, the disagreements are recorded
in the artifacts rather than reconciled away.

## The route is not source-independent yet, and the gap is a missing component

Both sessions have been quoting a property of this result more confidently than
the evidence supports: that because a CFR part is a source-independent key, a
court opinion or GAO report citing a part inherits its subjects the same way a
Federal Register document does.

**The key is source-independent. The pipeline is not.** The 89.4 arm reads
`cfr_references_json` — the Federal Register API's own *structured* citation
field, publisher-supplied and already parsed into `{title, part}`. No citation
was ever extracted from prose, because the publisher had done it. A court
opinion has no such field, and neither does a GAO or CRS report.

So what is demonstrated is narrower than what was claimed: *when a publisher
hands you structured CFR citations, part-subject propagation scores 89.4.* The
step between that and "works on a court opinion" is citation extraction, and
nobody has built it.

Relatedly: the top-383/tail split (90.3 vs 86.4) shows the arm generalises
across **parts**. It says nothing about generalising across **sources**, and
the first has been allowed to stand in for the second.

### No non-FR corpus with body text exists locally

Every `.parquet` under `spicy-regs/output/*` and `corpora/*` was swept for a
populated `text_content` / `body` / `full_text` / `content` column:

| rows | file |
|---:|---|
| 357 | `mixed-real-data-corpus-v1/comments.parquet` |
| 4 | `segmented-real-data-evaluation-v*/gao_reports.parquet` |
| 2 | `segmented-real-data-evaluation-v2/documents.parquet` |

`mixed-real-data-corpus-v1/documents.parquet` has 102,078 rows **and** a
`text_content` column that is 100% null — the column exists, the extraction
never ran. Checking schemas rather than counts would have reported a corpus
that is not there.

### What the 357 comments show about the missing component

Small, but they exercise exactly the step in question. 27 of 357 (7.6%) contain
a CFR citation; 42 distinct `(title, part)` pairs come out. Two findings:

**Citations are section-level, the index is part-level.** Observed forms:
`45 CFR § 302.32(b)`, `45 CFR §§1302.90(e)`, `2 C.F.R. § 200.334 through`,
`45   CFR   Part   1370.`, `45  CFR  410`. A section→part truncation step
(`302.32` → part `302`) is required and does not exist.

**Text extraction corrupts the citation boundary.** A first-pass extractor
returned titles 1345, 1545, 1645, 1745, 1945 and 2045. These are footnote
markers fused to the citation by whatever produced the text:

```
...specific, codified    1345 CFR 1370.31(a) (2024).  14See Family Violen...
...wielded against  2045 C.F.R. § 1355.22(b)(1)(i). 21See Mirabelli...
```

Footnote 13 + `45 CFR` → `1345 CFR`. All six bogus titles are title 45 with a
footnote number welded to the front.

This is the part worth keeping. The extraction problem is not only surface-form
variation in well-formed prose, which is how both sessions had been describing
it. The source text is itself damaged, and the damage is invisible until a
parse yields a title that cannot exist. A CFR title validator (1–50, minus
reserved 35) catches all six; no improvement to citation regexes would.

### What would settle it

1. Any non-FR corpus with body text. Closed for now — none exists locally.
2. A citation extractor measured on FR documents, where `cfr_references_json`
   is free ground truth. Preferred, and now the only open path. Measure it on
   body text (`body_html_url`) rather than title+abstract: the footnote-fusion
   class above appears only in extracted bodies, so title+abstract will flatter
   it. Have it emit the span and surface form alongside `(title, part)`, so
   failures of this kind are diagnosable rather than merely wrong.
