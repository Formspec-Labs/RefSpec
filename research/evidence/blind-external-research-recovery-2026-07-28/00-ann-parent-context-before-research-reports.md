# ANN benchmark context before the research reports returned

> Provenance
>
> - Recovery source: Private pre-publication research transcript; not published
> - Recovery date: **2026-07-28**
> - Scope: This note summarizes the benchmark investigation and its reasoning before the external research reports became available.

This note preserves the context that led to the blind external research. It does
not summarize those reports. The nine recovered reports and their provenance
are indexed in the [research recovery README](README.md).

## Practical meaning

The investigation completed a useful ANN benchmark, rejected USearch as a direct
replacement for exact dense search, and then followed the result into a broader
question: was the fused concept registry itself making retrieval difficult?

That second investigation found real data-quality and vocabulary-scope issues,
but it also made a serious comparison error. Before the research returned, the
investigation had:

- verified that boilerplate dominates the text embedded for many concepts;
- verified that FAST and EPA TSCA account for 99.6% of the registry;
- shown that removing major sources materially changes candidate lists;
- shown that bluntly removing FAST would also remove five of eight exact-alias
  targets;
- started a full re-embedding run to test a structural boilerplate-removal rule;
- commissioned two external research efforts on vocabulary design and
  large-label-space practice.

It had **not** yet proved that boilerplate removal improves candidate recall,
validated an agency-based prior, selected a replacement vocabulary, or produced
adoption evidence.

## 1. The bounded ANN experiment

### Question

Could a USearch approximate nearest neighbor (ANN) index match the current
exact dense candidate search while materially reducing memory or latency?

The frozen development set contained 35 document segments. The dense registry
contained 513,236 concept vectors with 768 dimensions. The sealed holdout was
explicitly out of scope.

### Result

The benchmark recommended **REJECT as a direct replacement**.

The exact baseline loaded about 1,696.7 MB and answered queries in 16.32 ms on
average, with a 22.29 ms 95th percentile. The only tested USearch configuration
that preserved all three eight-target oracle scores used 1,616.5 MB when
memory-mapped, only 4.7% less than the exact baseline. It recovered 96.9% of the
exact top 12. Lower-memory configurations lost 21% to 74% of those candidates.

The experiment also found and fixed a real API handling bug: a single USearch
query returns `Matches`, while the implementation had assumed `BatchMatches`.
The implementation added regression coverage for that production path.

The evidence supported keeping exact search unless registry growth or
per-worker memory use becomes a measured operating constraint.

Source: private benchmark transcript; not published.

## 2. The ontology-table question

The design review then asked whether the fused ontology table was poorly
designed. The investigation expanded from ANN benchmarking into a registry and
embedding-text audit.

### Verified findings

The development-corpus audit found:

- all 513,236 concepts had definitions derived from only eight structural
  templates;
- repeated source boilerplate made up much of the embedded text for large
  source groups;
- the sparse channel deliberately excluded definitions while the dense channel
  included them;
- FAST contributed 440,599 concepts, or 85.8% of the registry;
- EPA TSCA contributed 70,736 concepts, or 13.8%;
- Federal Register and Congressional Research Service vocabularies together
  contributed about 1,901 concepts, or 0.37%.

These facts justified testing different concept text and examining source
scope. They did not, by themselves, show that the registry was unusable or
that a smaller vocabulary would improve final tagging.

### Retracted diagnosis

At the time, the investigation reported that the best concept for a document segment
was only `0.029` more similar than random concepts and called the dense space
near-degenerate. It also treated a low effective dimension as evidence of
retrieval failure. Those conclusions were wrong.

The investigation compared unlike quantities:

- document-to-best-concept similarity; and
- random-concept-to-random-concept similarity.

The correct null comparison is document-to-random-concept similarity. A later
calculation found:

| Measure | Mean cosine similarity |
| --- | ---: |
| Document query to random concept | 0.4262 |
| Document query to best concept | 0.6435 |
| Correct top-match margin | **+0.2173** |

Therefore, the `0.029` claim must not support any design decision. The repeated
boilerplate remains a verified input-quality issue, but its effect on candidate
quality was still unproven at this point.

This correction is included retrospectively so the note does not preserve a
known error as fact. The original interpretation remains in the private
pre-publication transcript.

## 3. The questions sent to external researchers

The research question asked how Google and recent researchers would build a controlled
vocabulary for a broad federal corpus, including whether vocabulary scope
should follow the issuing agency.

The investigation launched two blind web-research assignments:

1. **Controlled-vocabulary scoping:** partitions, agency-conditioned priors,
   corpus-driven vocabulary construction, pruning, domain fit, and the
   distinction between subject concepts and chemical entities.
2. **Industry and LLM-era practice:** how production and published systems
   handle very large label spaces, retrieve-then-judge pipelines, hierarchical
   routing, learned retrieval, metadata, and vocabulary construction.

The prompts required external sources, explicit verification flags, recent
work where available, and direct treatment of the agency-scoping hypothesis.

Source: private research-scoping transcript; not published.

## 4. Development work while the research ran

### Source-removal probe

The investigation reused the cached vectors and exact-alias development oracle to
compare four search sets:

| Search set | Concepts | `C` alone | `v2+C` | `BM25+B+C` |
| --- | ---: | ---: | ---: | ---: |
| All sources | 513,236 | 3/8 | 4/8 | 2/8 |
| Exclude EPA TSCA | 442,500 | 3/8 | 4/8 | 2/8 |
| Exclude FAST | 72,637 | 3/8 | 4/8 | 2/8 |
| Federal Register and CRS only | 1,901 | 3/8 | 4/8 | 2/8 |

The unchanged oracle scores did not mean the source filters were inert. Only
one of 35 segments retained the same top 12, and only 176 of 420 candidate
positions overlapped.

Five failing exact targets existed only in FAST:

- `immigration law`
- `judicial power`
- `poultry inspection`
- `free speech`
- `fisheries management`

The probe supported a narrow conclusion: deleting FAST would remove the only
exact registry entries for those five targets. It did not establish whether
FAST improves broader concept coverage, whether close concepts are adequate, or
whether soft metadata priors improve ranking.

Source: private benchmark transcript; not published.

### Boilerplate-removal validation

Parallel implementation work had added a versioned `ConceptEmbeddingTextRule` that detected
repeated definition templates structurally, retained genuine definitions, and
included the rule version in the dense-index cache key. The investigation avoided
editing the same file and started a full 513,236-concept re-embedding and
ablation run against that uncommitted implementation.

At that point:

- the run had started but had not produced oracle results;
- the investigation correctly described the earlier geometry sample as a reason to
  test, not evidence of improvement;
- concurrent edits could still invalidate the running result;
- no boilerplate change had been adopted.

## Evidence status before the reports

| Claim or decision | Status before reports |
| --- | --- |
| Keep exact dense search instead of replacing it with tested USearch settings | **Verified development result** |
| Repeated source boilerplate dominates many embedded concept strings | **Verified development finding** |
| FAST plus EPA TSCA supplies 99.6% of registry rows | **Verified development finding** |
| Removing major sources changes candidate lists | **Verified development result** |
| Hard-removing FAST deletes five exact-alias targets | **Verified for the eight-target development oracle** |
| The dense space has only a `0.029` useful margin | **Retracted: invalid comparison** |
| Removing boilerplate improves top-12 candidate quality | **Unproven; validation running** |
| Agency or CFR metadata should change ranking | **Open question; not tested** |
| A smaller replacement vocabulary preserves adequate coverage | **Open question** |
| Any vocabulary or retrieval change is ready for adoption | **No** |
| Sealed holdout evidence exists | **No; holdout untouched** |

## Working position immediately before the reports

The investigation was leaning toward four next steps, none yet an adoption decision:

1. Keep exact dense search because ANN did not provide a worthwhile
   memory-quality tradeoff.
2. Finish the versioned boilerplate-removal A/B test and judge it by candidate
   recall, not geometry alone.
3. Avoid hard source or agency filters until coverage loss was understood.
4. Use the external research to decide whether soft agency, source, or CFR
   priors and a smaller purpose-built vocabulary deserved controlled
   experiments.

The investigation initially treated the industry research as failed and the
vocabulary research as unfinished. Later recovery found complete reports from
both research branches and their related assignments. No report content had
become available within this note's time window.

## Why the investigation lost focus

The original ANN experiment stayed bounded and produced a defensible decision.
The investigation became unreliable after it moved from measured search performance
to a broader explanation of vocabulary quality:

- it turned a valid boilerplate observation into an invalid
  near-degeneracy diagnosis;
- it began a registry audit, source-scope probe, full re-embedding run, and two
  external research efforts in the same response chain;
- it reported interim interpretations before the external evidence or
  candidate-quality validation was available.

At this point, the sound basis for further work was narrower than the earlier
language suggested: the registry text deserved an A/B test, hard deletion
risked known coverage, and metadata-conditioned ranking remained a research
question.
