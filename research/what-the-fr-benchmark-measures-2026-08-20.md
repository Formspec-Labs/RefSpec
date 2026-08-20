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

**Where the divergence comes from is an open question, and this note should not
be read as answering it.**

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
