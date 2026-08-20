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
| absent from Atlas entirely | **0** | 0% |

**Correction.** An earlier version of this table reported "absent from Atlas
entirely: 30". That was wrong and a parallel session caught it. All 852 terms
are in Atlas by construction — they come from the CFR artifact, every row of
which resolves to a `federal-register-api-topics` concept. The 30 were absent
from the FR *thesaurus* and from every general scheme, which is a much weaker
claim than the one the table made. Verified: 0 of 852 are absent from Atlas.

**Matching rule.** Reach here counts **preferred and alternate** labels. A
preferred-only reading gives 580 (68.1%) outside FR and 383 (45.0%) for LCSH —
about 4 points tighter on the headline. The permissive reading is used because
if a term matches an LCSH alternate label, the concept *is* expressible in
LCSH; but the two readings differ enough that stating which one is in force
matters.

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

## Small vocabularies: dense, but mostly not additive

Raw reach understates small vocabularies, because a 3,810-concept thesaurus is
competing with LCSH's 514,837. Per concept:

| vocabulary | concepts | reach | reach per 1,000 concepts |
|---|---:|---:|---:|
| federal-register-thesaurus-2025 | 705 | 676 | **958.9** |
| crs-legislative-subject-terms | 565 | 37 | 65.5 |
| elsst | 3,470 | 194 | 55.9 |
| **icpsr-subject-thesaurus** | 3,810 | 183 | **48.0** |
| **eurovoc** | 7,515 | 218 | **29.0** |
| gemet | 5,649 | 113 | 20.0 |
| fast-topical | 441,127 | 470 | 1.07 |
| lcsh-subjects | 514,837 | 483 | 0.94 |

ICPSR is **51× denser** than LCSH in this space and EuroVoc **31×**. LCSH earns
its 56.7% by being 137× larger, not by being better suited.

**But density is not the same as additive value.** Against a serving set that
already holds LCSH and FAST:

| | reach | unique beyond LCSH/FAST | share of its reach that is unique |
|---|---:|---:|---:|
| eurovoc | 218 | **+58** | 27% |
| icpsr-subject-thesaurus | 183 | **+19** | 10% |
| both | — | **+72** | 483 → 555 (56.7% → 65.1%) |

ICPSR overlaps LCSH almost entirely — both are anglophone library-tradition
vocabularies, so it adds 19 terms for 3,810 concepts of carrying cost.

EuroVoc looks three times better, **but inspect what it adds**:

```
nicaragua   libya   cuba   liberia   somalia   eritrea
yemen   ukraine   american samoa   central african republic
```

Its unique contribution is dominated by **country names**. EuroVoc carries
geography as concepts because EU legislation must reference countries; LCSH
treats places as *name authorities* rather than topical subjects, so they are
absent from `lcsh-subjects`.

So EuroVoc is adding **facet values, not policy depth** — and
`research/parent-domain-taxonomy-2026-08-19.md` already establishes that
jurisdiction and geography are a facet rather than a subject. The right way to
serve those is a geographic authority, not a second subject thesaurus.

**Practical read: neither ICPSR nor EuroVoc earns a place in a subject-serving
set on this evidence.** The +72 is real but it is mostly geography, and the
carrying cost is 11,325 concepts. If geography is wanted, serve it as
geography.

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
