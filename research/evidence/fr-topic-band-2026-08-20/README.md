# Federal Register topic bands — procedural vs substantive

**2026-08-20.** A declared, reviewable split of the 900 Federal Register topics
actually used across 114,220 labelled documents, for routing a two-track tagger.

## Why this exists

Two sessions independently split these topics into "administrative boilerplate"
and "substantive", by hand-picking a member set, and got different answers
(25.9/74.1 and 23.4/76.6). Directionally identical, but the two-track tagger
*routes* on this boundary, so it cannot rest on either guess. This is the pinned
version.

## The rule

A topic is **procedural** when it satisfies both:

    agencies >= 30           AND   top_agency_share <= 70%

    where  agency          = FIRST entry of `agency_slugs` (the primary agency)
    and    top_agency_share = documents on the top agency / documents on the topic
                              (denominator is DOCUMENTS, never (doc,agency) pairs)

Measured over `(document, topic)` pairs from
`spicy-regs/output/rulespec-stabilization-candidate-final/federal_register.parquet`,
agency taken as the first entry of `agency_slugs`.

**The discriminator is agency dispersion, not textual visibility.** That was the
non-obvious finding. `navigation (water)` appears in 0.0% of its documents'
title+abstract text — but sits in 8 agencies at 84% concentration, which makes it
a subject (Coast Guard's), not boilerplate. `administrative practice and
procedure` spans **121 agencies** at 27% concentration. Dispersion separates
them; in-text rate does not.

## Result

| band | topics | assignments | share | mean agencies | in-text (weighted) | in-text (topic-mean) |
|---|---:|---:|---:|---:|---:|---:|
| procedural | 28 | 144,718 | 25.3% | 50.3 | **3.1%** | 7.3% |
| substantive | 872 | 426,995 | 74.7% | 5.4 | **16.8%** | 20.4% |

A **9× dispersion gap** between the bands. The split lands between the two
independent hand-guesses it replaces.

**Two in-text columns, because they answer different questions.** Recall is
computed over *assignments*, so the assignment-weighted figure is the one that
predicts tagger behaviour; the topic-mean treats a topic used 300 times and one
used 55,000 times equally, and rare high-in-text topics pull it up. Quote the
weighted number for anything about recall. It strengthens the conclusion: the
procedural band is **3.1%** textually recoverable, not 7.3% — less than half.

## The agency definition is load-bearing, not incidental

**This is the most important caveat in the artifact.** The rule counts the
**primary** agency — the first entry of `agency_slugs`. That choice is not a
detail; it determines the band.

Counting *every* agency in the field instead (parent department plus
sub-agencies — a document filed under
`commerce-department,foreign-trade-zones-board` becomes two agencies rather than
one) moves the result to **141 procedural topics / 216,485 assignments /
37.9%**. A parallel session reading `agencies_json` rather than `agency_slugs`
got **192 topics / 50.6%**.

So the same rule statement yields 28, 141, or 192 procedural topics depending on
how "agency" is read.

### And a second, independent choice: the share denominator

`top_agency_share` can divide by **documents** or by **(document, agency) pairs**.
Under the pinned primary-agency reading these coincide — one agency per document —
so the ambiguity is *invisible here* and only bites a reimplementer who also
changes the first choice. Worked example:

| `navigation (water)` — 7,389 docs, 14,811 (doc,agency) pairs | agencies | top-share | band |
|---|---:|---:|---|
| primary `agency_slugs` (**pinned**) | 8 | 84.1% | substantive ✓ |
| all `agency_slugs`, share over **documents** | 20 | 94.1% | substantive ✓ |
| all `agency_slugs`, share over **pairs** | 20 | **46.9%** | **procedural ✗** |

Coast Guard is on 94.1% of those documents, but every one also lists
`homeland-security-department` as parent — so over pairs Coast Guard is only 46.9%
and a Coast Guard subject flips to boilerplate. That is the failure mode this
artifact exists to prevent, produced by a denominator rather than by the topic. All three look like plausible splits; nothing in the output
signals which reading produced it.

The 9× dispersion gap is a real property of the primary-agency reading. It is
**not** a robust natural boundary that any reasonable implementation would
rediscover. Anyone reimplementing from the rule statement rather than the method
line will get a different band and will not notice.

Sub-agency counting inflates dispersion precisely where a parent department has
many sub-agencies, which is exactly where subject-specific topics concentrate —
so the failure mode is misfiling real subjects as boilerplate.

## Why it matters for the tagger

The procedural band is 25.3% of the answer key and is **3.1% textually
visible by assignment** — it cannot be recovered by reading the document. It is predictable
from *agency* instead: `Reporting and recordkeeping requirements` runs from
11.5% of Transportation documents to 85.8% of EPA's, a sevenfold spread, while
`document_type` is a coin flip (Rule+CFR 50.0%, Proposed Rule+CFR 45.9%).

So: route the procedural band to an agency-conditioned prior, and the
substantive band to retrieval. **Union, never intersect** — roughly 90% of
assignments land on terms used by two or more agencies, so a hard agency filter
is wrong even though the prior is strong.

## Edge cases that need a human

The rule is mechanical and four members are genuinely arguable. These are the
calls a reviewer should make, not the rule:

- **`privacy`** — 87 agencies, but **49.5% in-text**, by far the highest in the
  procedural band. It is discussed in the text, not merely attached. Plausibly
  substantive.
- **`civil rights`** (50 agencies, 7.7%) and **`equal employment opportunity`**
  (44 agencies, 20.8%) — real subjects that also function as cross-agency
  compliance boilerplate. The taxonomy research already flags this exact
  ambiguity for GAO `Equal Opportunity`.
- **`individuals with disabilities`** (45 agencies) and **`wages`** (41) — both
  read as substantive policy that happens to be cross-cutting.

Moving any of these changes the band share by well under a percentage point, so
the routing decision is not sensitive to them — but the list is a published
vocabulary artifact and should say what it means.

## Files

- `topic-bands.csv` — all 900 used topics with `assignments`, `agencies`,
  `in_text_pct`, `top_agency_share_pct`, `proposed_band`.


## Data-quality defect in the source agency field

`agency_slugs` is the **only sanctioned agency surface**. `agencies_json` is
untrusted for identity.

Measured corpus-wide: of **1,578,673** agency entries in `agencies_json`,
**30,405 (1.93%)** carry `slug: null`. A fallback chain to `name`/`raw_name` —
the natural way to read the field — silently ingests those. What they contain:

| kind | entries | distinct values |
|---|---:|---:|
| plausible sub-agency with no slug | 26,630 | 339 |
| other / text fragments | 3,300 | **1,728** |
| **document *type*, not an agency** (`Rule`, `Proposed Rule`, `Final Rule`, `Notice`) | 453 | 4 |
| docket-id shaped (`CGD01-01-074`, `COTP Pittsburgh-02-002`) | 22 | 22 |

**Lead with the document-type class.** 453 entries where `Rule` or `Proposed
Rule` is an agency *identity* is a category error one layer below the
facet-as-subject trap — and an agency-conditioned boilerplate prior built
without the filter trains on it directly. That is a downstream consequence, not
a hygiene note.

**The fragments are provably line-wrap splitting**, not a bad enum. The two
halves sit adjacent in the frequency table, two documents apart:

    "Office of the Assistant Secretary for Community Planning and"   189
    "Development"                                                    187

One agency name split across a line break, both halves ingested as separate
agencies.

The majority are *legitimate* sub-agencies that simply lack a slug — so
`agencies_json` is not junk, it carries real granularity that `agency_slugs`
drops (`Office of the Secretary` alone is 23,806 entries). But 1,728 distinct
fragment values and 453 document types mean it cannot be used for identity
without filtering, and `agency_slugs` is clean because these entries drop out.

**Rule: join on `agency_slugs`. If sub-agency granularity is needed, take it from
`agencies_json` only where `slug` is non-null.**

*(The null-slug problem was found by a parallel session on one topic;
characterised corpus-wide here.)*
