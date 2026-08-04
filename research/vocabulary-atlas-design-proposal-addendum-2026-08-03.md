<!-- markdownlint-disable MD013 -->

# Addendum — what the atlas design proposal does not cover

> **Status:** Companion record to a proposed design; not adopted
>
> **Standing:** Rules and ownership are this document's durable content.
> Counts and build references are dated snapshots of an artifact set in
> motion; `output/` is a workbench, and decision ceremony binds at
> publication boundaries, never to experimental runs.
>
> **Date:** 2026-08-03
>
> **Decision synthesis:** [Vocabulary Atlas Final Synthesis](vocabulary-atlas-final-synthesis-2026-08-03.md)
> resolves the review findings and supersedes the parent draft for decision-making.
>
> **Parent proposal:** [Vocabulary Atlas Design Proposal](vocabulary-atlas-design-proposal-2026-08-03.md)
>
> **Evidence base:** [External research synthesis](large-label-space-tagging-external-research-synthesis-2026-08-03.md)

This addendum bounds the parent proposal: the commitments that are
experiments rather than established results (§A), the demands the atlas
leaves to other layers, each with a named owner (§B), one clarification
that prevents a predictable mis-citation (§C), the registry-wide source
accounting (§D), and corrections owed to artifacts outside this document
set (§E). Items here are scope boundaries and
successor work, not defects in the parent proposal — but each needs an
owner, and three need their own design documents (B4's concept staging;
B5's entity spine and legal-identity edge model).

## A. Commitments that exceed the evidence

The synthesis (§14) verified that certain techniques the proposal relies on
have never been measured anywhere. The proposal treats each as an experiment
to run, not a fact to inherit. Recording them together so no later document
cites the proposal as if these were established:

| # | Commitment | Evidence status | Instrument in the proposal |
| --- | --- | --- | --- |
| A1 | Ring/facet separation improves tagging (typed pools, separate eligibility per ring) | Synthesis §14 gap 7: no facet-separated retrieval experiment exists; motivation only (GND benchmark's own admission, MeSH/EPA structural precedent) | Proposal §10: ring assignments authorize nothing until a per-source-family holdout passes |
| A2 | The mapping frontier's decoy value (keeping off-domain vocabulary in the index reduces wrong-concept emissions) | Synthesis §14 gap 1: the deletion ablation has never been published; CoRECT and DNB-AI support the two halves separately, not the combination | Proposal §10: frontier ablation against a frontier-less control; result recorded either way |
| A3 | Hierarchy context in judge input improves mapping qualification | No literature either way; the pilot showed zero of 365 sealed inputs carried `broader` while the prompt asked a hierarchy question — and gate protocol v2 now emits *directional* verdicts on those same label-only inputs, so the stakes rose from experiment to prerequisite | Proposal §7.2: label-only vs ancestor-labels A/B on the same candidate slice decides it; until it runs, direction-typed emissions score as a separately validated class and stay out of frontier hierarchy context |

If any of these experiments comes back negative, the affected structure
(rings as eligibility tiers, frontier context depth, judge input shape) is
revisable without changing the atlas format itself.

## B. Synthesis demands assigned to other layers

The atlas is a publication format. Five things the synthesis establishes as
necessary belong to the consuming pipeline, to vocabulary governance, or to
sibling reference publications, and their absence from the parent proposal
is scope, not omission. Each entry names the owner so the demand does not
fall between documents.

### B1. Retrieval engineering — owner: SpicySearch pipeline

Synthesis §3, §6, §13.3, §13.6. The measured levers, none of which the atlas
can supply:

- hybrid first-stage retrieval — lexical BM25/TF-IDF unioned with dense
  (TF-IDF beat every neural retriever on EURLex; removing the lexical
  channel cost 33 P@1 points);
- an embedding-encoder audit before any other tuning (132× spread between
  two sentence transformers on identical 500K-label data — the largest
  effect size in the literature);
- CSLS hubness correction (free; +2.1 to +9.3 P@1 on short-surface-form
  retrieval);
- candidate pools wider than the judge's shortlist (R@10→R@200 roughly
  doubles recall at 500K-label scale), with a cross-encoder reranker above
  the retriever — the shortlist is the binding constraint no judge quality
  can fix;
- LLM candidate reranking last, if at all (+0.009 F1@5 measured).

What the atlas contributes to this layer: variant labels as synonym rings,
qualified `searchOnly` mappings, bounded hierarchy — inputs, not the engine.

### B2. Soft metadata priors — owner: SpicySearch scoring

Synthesis §9. P(concept | CFR part) backed off to parent agency, then
global; a frequency-weighted **score component**, candidates **unioned**
with a global top-N, never intersected. Measured on the federal corpus:
recall@12 42.2% → 76.0% (CFR part) / 71.0% (agency), while 90% of topic
assignments land on cross-agency terms — the distribution is
source-conditioned, the label set is not source-separable. The atlas stays
metadata-free by design; priors live where scoring lives. Expect the
prior's value to shrink as supervision grows.

### B3. Generate-then-map serving and the free supervision — owner: SpicySearch pipeline

Synthesis §4. The zero-shot architecture three groups converged on
(generate free-text concepts → map by embedding nearest-neighbor → rerank)
requires roughly 50 labeled optimization examples — the unoptimized variant
measured *worse* than naive retrieval — plus constrained output counts
(precision 0.26 at ~3 terms/record vs 0.05 at ~15) and calibrated
abstention. The Federal Register's agency-assigned topics on Rules and
Proposed Rules supply the bootstrap set, the evaluation gold, and the
prior-estimation data at zero cost. None of this touches the atlas; all of
it consumes atlas outputs.

### B4. The concept-level staging tier — owner: **a successor proposal that does not yet exist**

This is the one genuine hole the alignment check found. Synthesis §11 and
§13.7 establish the governance machinery every long-lived vocabulary runs,
and the parent proposal's promotion ladder covers *resources* (reader →
release → ring) but not *concepts*. The emit core needs its own two-tier
machinery:

- an unbounded staging tier for source-grounded phrases that map to no
  registered concept, every staged entry **anchored** to a registered
  concept (MeSH's Heading-Mapped-To pattern) so nothing floats free —
  and every anchor **typed** (`narrowerThan`, `broaderThan`, `relatedTo`,
  facet-located, or explicitly unresolved), never equivalence by default:
  the anchor places a proposal, it does not merge one;
- promotion as a named-human editorial decision informed by usage evidence,
  run as periodic campaigns (MeSH promotes ~100–500/year; EuroVoc gates on
  a definition, a home in the hierarchy, and reviewer consensus — no
  frequency threshold anywhere in either system);
- growth by splitting: ~44% of MeSH's additions over 15 years refined
  concepts already covered, so concept identity and history must support a
  concept splitting into narrower children without breaking past
  assignments;
- the expensive steps (embedding, crosswalk qualification, translation-
  equivalents) gated behind promotion, not candidacy;
- candidate tooling: EuroVoc runs this workflow in VocBench (open source),
  which is the obvious pilot vehicle;
- evaluation hooks: staged-concept emergence is itself the "measured
  recurring gaps" signal that the architecture proposal requires before any
  vocabulary induction is considered.

The design covers the complete concept lifecycle, in order:

```text
source-grounded phrase → staged candidate → reviewed proposal
→ named promotion decision → LocalConcept / registered concept
→ complete managed-release membership → mapping and adoption
→ deprecation / split / merge / replacement
```

The promotion decision precedes the concept: a `ConceptProposal` enters
staging first, and only a named, authorized promotion decision creates the
governed concept, which then publishes through a new complete managed
release after its definition, hierarchy, evidence, rights, and attestation
gates pass.

Until that proposal exists, the atlas's ring-0 core has no governed path for
growth, and the pipeline's abstention/open-result facet has no destination
for what it catches. This is the successor document to write first: with CRS held to
`sourceAssignedEvidence` (parent §3), concept staging is the **only**
ring-0 growth path, so every core extension waits on this design.

### B5. The sibling reference publications — owners: two successor proposals plus one existing layer

Synthesis §1, §9, and §13.2: entity registries and classification spaces are
different objects; entity identity is not a subject; typed facets are
separate outputs with separate registries. The parent proposal's ring 3
(§3) now names the three sibling publications that carry this demand; their
internals remain undesigned or partially designed:

- **Entity spine — unwritten; the successor proposal after B4.** Agencies,
  award entities, committees, providers, and substances as nodes with typed
  identifier sets; identity links evidence-classed exactly as the parent's
  §6 classes mappings (publisher-asserted crosswalks vs machine-suggested
  matches vs human-reviewed merges), with "never merge on name equality" as
  the identity twin of "never map on label equality." The source matrix's
  `T3-04` already anticipates it. Priority: immediately after B4, because
  every cross-document product feature (follow-the-company,
  follow-the-rule) runs through the spine or the legal identity graph.
- **Legal identity graph — half-built; needs an edge-model design.** CFR
  structure, statutes, RINs, docket and bill identifiers exist as parsed
  fields; the typed edges (*cites*, *amends*, *authorizes*, *implements*)
  with point-in-time versions — the ELI analogue — do not.
- **Code ledgers — essentially built.** `source_controlled_resource` and
  `regulatory_native_controls` already publish versioned value sets with
  preserved raw values. For identifier-poor sources, the shared package model
  now also supports UUIDv7 source-fetch and package-registration events, UUIDv7
  local record IDs, and separate membership and record-content digests. CRS
  proves the refresh rule: identifier-first or exact-label matches preserve
  local IDs, any capture-independent content change creates a reconciliation
  report, and the immutable ledger retains the packages and human review.
  Remaining work is reviewed
  edition crosswalks (NAICS 2017→2022) as they become product-relevant.

One composition rule recorded here because it crosses B3 and the parent's
§3: the decoy function for entity labels (DNB's forced-choice snapping
lesson) is served by the pipeline's mapping index unioning the atlas
frontier with entity-spine labels at retrieval time. Entities never enter
the atlas's release facts; absorb-in-one-space / emit-on-another-facet is
pipeline composition, owned by B3's layer.

The sibling publications also share one small **composition contract**, so
the consumer never invents join semantics: common artifact and document
identifiers, role-qualified entity links, source and release provenance,
as-of-time behavior, namespace and collision rules, and read-model
identities derived from input digests — the provenance path a result
explanation follows when it references records across publications.

## C. Clarification against a predictable mis-citation

The parent proposal's **hub-and-spoke** (§5) is a crosswalk-qualification
*scheduling* topology: which release pairs get candidate generation and
two-model validation. It is not retrieval routing. Synthesis §9's finding
that "hierarchical two-stage routing is unevidenced" concerns
domain→descriptor classification cascades and does not bear on the hub
spoke. Conversely, the hub spoke must never be cited as evidence for
two-stage classification routing. Transitive hub claims (`A→LCSH→B`) are
demoted to candidate generation only — mappings are never materialized
across the hub, which is synthesis §13.5 ("nearest neighbor is not evidence
of correctness") applied at the mapping layer.

## D. Registry compatibility check (2026-08-03)

Every module in `src/refspec/registry/` (77 modules) is classified against
the parent proposal's rings and sibling publications, with docstrings
verified for the modules the proposal's tables do not name. Every module
has exactly one home. One reader/ring reconciliation is open — the
`candidate_use_authorized` flag (D2); no other module conflicts with the
design.

**D1 — Positive finding: the readers already enforce the design.** The ring
model codifies decisions the readers individually enforce in code:
`eurovoc_thesaurus` refuses any accepted use except mapping-reference;
`lcsh_topical` hard-codes `candidate_use_authorized=False`; `gao_topics`
captures only actual assignments and refuses to reconstruct a scheme from
navigation; `federal_register_topics_api` preserves byte identity but mints
no concept identifiers; `census_geo_codes` captures identifier grammar and
refuses bulk entity rows; `crs_product_topics` treats topic labels as
edition-bound evidence, not stable concepts. Nothing in the registry mints
concepts from ring-3 material. Compatibility is by construction, not by
accident.

**D2 — The eligible-use vocabulary must be extended (parent §3).**
`source_controlled_resource.ResourceUse` lacks `mappingReference`; EuroVoc
enforces a literal outside the enum and LCSH declares `searchExpansion`
only despite its hub role. Parent §3 requires the enum extension and makes
the atlas index reconcile reader-declared uses against ring assignments.
The same work defines `candidate_use_authorized`, which no shared model
documents: LCSH hard-codes `False` as the mapping-only marker while
`fast_topical`, `nasa_technology_taxonomy`, and `census_geo_codes` set
`True` — a ring-2 source declaring `True` (FAST topical today) is a
reader/ring disagreement to resolve, never a grant. `gemet_thesaurus` and
`nasa_thesaurus` declare no machine-readable use at all and enter the same
reconciliation. Owner: registry shared models, before any ring-2
promotion.

**D3 — Source-assigned topic evidence is a named category (parent §3).**
GAO topics, CBO topic labels, CRS product topics, LDA issue codes, and SAM
mission/subject fields are per-document publisher evidence — not schemes,
not codes. They stay out of the atlas, flow through
`sourceAssignedEvidence` observations to the pipeline, and may later earn
small reviewed maps into ring-0 concepts through the parent's §6 evidence
classes.

**D4 — Placement decisions.** `courtlistener_codes` (court identity) and
`census_geo_codes` (geography identifier grammar) belong to the entity
spine, not the code ledgers; `census_gov_finance_codes` is a ledger
crosswalk reference. The parent's ring tables remain illustrative; the
atlas index is the exhaustive assignment of record.

**D5 — Not sources.** Roughly two dozen modules are shared models,
transports, acquisition, policy, managed-release builders, or development
artifacts (`source_controlled_resource`, `managed_vocabulary_bundle`,
`concept_domain_bridge`, `controlled_identifier`,
`regulatory_native_controls`, `zyte_transport`, the `*_acquisition` and
`*_zyte` modules, the `*_managed_release` builders,
`federal_register_vocabulary_policy`,
`federal_register_topics_reconciliation`,
`federal_register_topics_package`, `federal_register_vertical_slice`,
`crs_source_packages`, `lda_controlled_list_resources`,
`elsst_import_coverage`, `elsst_rulespec_projection`, test helpers). They
take no ring assignment and appear in the atlas index only as
implementation, not as sources.

## E. Corrections owed outside this document set

Two artifacts contradict the pinned current build and must be corrected
where they live:

1. `output/atlas-qualification-fr-icpsr-2026-08-03/README.md` states "No
   bundle was sealed" and that nothing in the run produced a qualified
   `searchOnly` mapping. Both were true at the 96-call stop and are false
   now: the run's own `qualification-receipt.json` and 730-line
   `receipts.jsonl` record the completed two-family gate and 119 qualified
   mappings. Append a dated completion note.
2. `docs/atlas-publication.md` quotes the superseded 929,327-quad build.
   The pinned current build is 233,999 quads / 240 `searchOnly` mappings;
   per parent §1, atlas counts are cited with the atlas identifier named
   first.
