# How far Federal Register subject matter reaches into other vocabularies

**2026-08-20.** For the 852 subject terms actually used in
`../cfr-part-subjects-2026-08-20/`, which other Atlas vocabularies can express
the same concept.

## The question this answers

Under the framing that tagging is *a document's relationship to specific
vocabularies* — you would not tag a Supreme Court opinion with Federal Register
tags — the first question is which vocabulary a document should draw from at
all. A CFR citation gives a source-independent way in: a court opinion citing
42 CFR 416 inherits that part's subjects without needing an issuing agency.

But those inherited subjects are Federal Register terms. Whether they can be
*restated* in a general vocabulary decides whether the CFR route produces tags
that mean anything outside the Federal Register.

## Result

| | topics | share |
|---|---:|---:|
| expressible outside Federal Register vocabularies | **615** | **72.2%** |
| **Federal Register only** | **237** | **27.8%** |
| absent from Atlas entirely | 30 | 3.5% |

By reach:

| reach | topics | share |
|---|---:|---:|
| reaches 6+ general schemes | 206 | 24.2% |
| reaches 3–5 | 262 | 30.8% |
| reaches 1–2 | 147 | 17.3% |
| **none — Federal Register only** | **237** | **27.8%** |

Per target vocabulary:

| vocabulary | FR topics it can express | share of 852 |
|---|---:|---:|
| federal-register-thesaurus-2025 | 676 | 79.3% |
| lcsh-subjects | 483 | 56.7% |
| fast-topical | 470 | 55.2% |
| mesh-descriptors | 340 | 39.9% |
| doe-osti-semantic-thesaurus | 232 | 27.2% |
| eurovoc | 218 | 25.6% |
| nasa-thesaurus | 212 | 24.9% |
| gemet | 113 | 13.3% |

## What this means

**No single general vocabulary covers regulatory subject matter.** LCSH is the
best non-publisher option at 56.7%, and even the union of every non-Federal-
Register scheme in Atlas reaches only 72.2%.

**The 27.8% residue is not a coverage gap to close — it is a different kind of
term.** A sample of what only the Federal Register can say:

```
community development block grants   price support programs
government property management       defense communications
paving and roofing materials         military academies
nuclear power plants and reactors    indians-lands
housing standards                    graphic arts industry
```

These are not general subjects. They are the vocabulary of **US federal
administration** — programme names, statutory instruments, agency-specific
categories. LCSH does not carry "community development block grants" because it
is not a subject in the library sense; it is a funding mechanism created by an
Act of Congress.

So routing for a regulatory document is not "pick the right general vocabulary".
It is: **a general vocabulary handles roughly 72% of the subject matter, and the
domain vocabulary is required for the remaining 28% — which is exactly the
policy-programme layer that regulatory work is usually about.**

That is an argument for keeping the Federal Register thesaurus in the serving
set rather than treating it as a stepping stone to a general one, and against
any design that routes a document to exactly one vocabulary.

## Method and limits

Reach is measured by **exact case-folded label equality** against preferred and
alternate labels in the subject ring. That is a floor, not a ceiling: a concept
with a genuine equivalent under a different name is counted as unreachable here.
It is the same conservative rule the FR-thesaurus/API-topic derived rule uses,
chosen for the same reason — every additional transform widens the population on
evidence the label texts do not carry.

The 30 topics absent from Atlas entirely are a subset of the 237, not additional.

`fr-topic-reach.csv` carries one row per topic with its general-scheme count and
flags for LCSH, MeSH, EuroVoc, GEMET and the FR thesaurus.
