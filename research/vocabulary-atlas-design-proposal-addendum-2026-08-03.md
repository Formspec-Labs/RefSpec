<!-- markdownlint-disable MD013 -->

# Addendum — what the atlas design proposal does not cover

> **Status:** Implemented Atlas 2.0 boundary record; product adoption remains separate
>
> **Revision (2026-08-04):** Restated with the parent proposal: rings name
> semantic kinds (subject, entity, value, and legalIdentity); the former
> ring 0/1/2 are subject-ring participation classes (`core`, `specialist`,
> and `bridge`); and useful source terms carry source-scoped concept
> identity. All four rings share one record foundation with ring-specific
> relations. Identity is not admission: a named review may admit an existing
> source identity, while staging creates only new RefSpec-authored concepts.
> For subject emission, a pinned `SubjectEmissionPolicy` records eligibility,
> and an active `OutputProfile` that names that exact policy grants permission.
>
> **Implementation (2026-08-04):** The shared foundation, initial closed
> non-subject predicates and time-context checks, subject admission and emission
> path, authoring-transition receipt path, exact ring/module views, and
> publication decision boundary are executable and tested. B1-B3 remain
> consumer responsibilities. B5's production entity, value, and legalIdentity
> models, source-specific relation generation, and proof adapters remain open.
> The evidence gaps in §A remain experiments, not features claimed by the
> implementation.
>
> **Standing:** Rules and ownership are this document's durable content.
> Counts and build references are dated snapshots of an artifact set in
> motion; `output/` is a workbench, and decision ceremony binds at
> publication boundaries, never to experimental runs.
>
> **Date:** 2026-08-03
>
> **Prior synthesis:** [Vocabulary Atlas Final Synthesis](vocabulary-atlas-final-synthesis-2026-08-03.md)
> resolves the original review findings. The parent revision supersedes its
> planning classes, CRS identity ruling, and separate-publication boundary;
> its verified evidence and unaffected decisions remain useful.
>
> **Parent proposal:** [Vocabulary Atlas Design Proposal](vocabulary-atlas-design-proposal-2026-08-03.md)
>
> **Evidence base:** [External research synthesis](large-label-space-tagging-external-research-synthesis-2026-08-03.md)

This addendum bounds the parent proposal: the commitments that remain
experiments (§A), the work assigned to consuming or ring-specific layers
(§B), one clarification that prevents a predictable mis-citation (§C), the
registry-wide target-state accounting (§D), and corrections owed outside
this document set (§E). Each open design has a named owner.

## A. Commitments that exceed the evidence

The synthesis (§14) verified that certain techniques the proposal relies on
have never been measured anywhere. The proposal treats each as an experiment
to run, not a fact to inherit. Recording them together so no later document
cites the proposal as if these were established:

| # | Commitment | Evidence status | Instrument in the proposal |
| --- | --- | --- | --- |
| A1 | Ring/facet separation improves tagging (ring-scoped candidate pools and subject participation policies) | Synthesis §14 gap 7: no facet-separated retrieval experiment exists; motivation only (GND benchmark's own admission, MeSH/EPA structural precedent) | Proposal §10: participation assignments authorize nothing; a per-source-family holdout supplies evidence for an exact product policy |
| A2 | The mapping frontier's decoy value (keeping off-domain vocabulary in the index reduces wrong-concept emissions) | Synthesis §14 gap 1: the deletion ablation has never been published; CoRECT and DNB-AI support the two halves separately, not the combination | Proposal §10: frontier ablation against a frontier-less control; result recorded either way |
| A3 | Hierarchy context in judge input improves mapping qualification | No literature either way; the pilot showed zero of 365 sealed inputs carried `broader` while the prompt asked a hierarchy question — and gate protocol v2 now emits *directional* verdicts on those same label-only inputs, so the stakes rose from experiment to prerequisite | Proposal §7.2: label-only vs ancestor-labels A/B on the same candidate slice decides it; until it runs, direction-typed emissions score as a separately validated class and stay out of frontier hierarchy context |

If any of these experiments comes back negative, the affected structure
(participation classes, frontier context depth, judge input shape) is
revisable without changing the atlas format itself.

## B. Synthesis demands assigned to other layers

The atlas is a publication format. Five things the synthesis establishes as
necessary belong to the consuming pipeline, vocabulary governance, or a
ring-specific relation design. Each entry names the owner so the demand does
not fall between documents.

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

What the atlas contributes to this layer: variant-label sets,
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

### B4. Subject admission and local concept staging — owner: vocabulary governance

The subject ring needs two governance paths because admitting an existing
source concept and authoring a new RefSpec concept are different decisions.
Both use named review, but only the second creates identity.

**Admission preserves source identity.** A named review may admit an existing
source-scoped concept to the curated emit tier. The review binds the exact
content-derived release and records the concept's definition or scope note,
hierarchy anchor or explicit unresolved placement, facet, evidence, rights,
reviewer, time, and intended product use. These facts enrich the existing
identity and support a pinned `SubjectEmissionPolicy`; they neither replace
identity nor activate product use on their own. The policy records the eligible
exact release, admission review, concept, and intended use. An active
`OutputProfile` that names that exact policy supplies the separate permission
grant.
A new source capture produces a new release and requires a new admission
decision, so a publisher rename cannot change the emit core silently.

**Staging creates genuinely new RefSpec concepts.** Use a `ConceptProposal`
when no source concept expresses the intended meaning or when RefSpec chooses
to consolidate, split, or otherwise author a meaning distinct from its source
concepts. Every proposal cites its sources and has a typed placement
(`narrowerThan`, `broaderThan`, `relatedTo`, facet-located, or explicitly
unresolved). Label similarity never supplies identity or equivalence.

The research supports the following governance rules:

- promotion is a named-human editorial decision informed by usage evidence;
  MeSH promotes roughly 100–500 records a year, and EuroVoc requires a
  definition, hierarchy placement, and reviewer consensus;
- growth often happens by splitting; roughly 44% of MeSH additions over 15
  years refined concepts already covered, so lifecycle history must preserve
  earlier assignments;
- expensive translation and crosswalk work follows creation of the new
  concept rather than proposal intake;
- staged-concept recurrence measures gaps that may justify local authoring;
  frequency informs review but never triggers it automatically.

The two paths are explicit:

```text
existing source concept → named admission review
→ curated-tier admission bound to the exact release
→ pinned SubjectEmissionPolicy eligibility → active OutputProfile permission

source evidence → ConceptProposal → named authoring decision
→ rkaf:LocalConcept → complete managed release → mapping and adoption
→ managed-local curated admission
→ deprecation / split / merge / replacement
```

Concept staging therefore blocks only new RefSpec-authored identities. It
does not block evaluation or admission of CRS or any other existing
source-scoped concept. The implemented admission and emission path accepts
both exact source-concept releases and exact complete managed releases. The
managed path requires a pinned subject-ring assignment, an actual
`rkaf:LocalConcept` member, and rights metadata bound to the exact Rulespec
graph. The named review, `SubjectEmissionPolicy`, and active `OutputProfile`
continue to carry the same identity; none remints it. A managed release,
mapping, or adoption without that named review does not place a local concept
in the curated emit tier.

### B5. Ring-specific relation designs — owners: the entity, value, and legalIdentity rings

Synthesis §1, §9, and §13.2 distinguishes entity identity from subject
classification and motivates typed outputs. The parent proposal places those
outputs on one foundation: a shared concept-identity record shape, releases,
provenance, rights, evidence classes, mapping-assertion structure, and
lifecycle. The foundation already registers an initial closed predicate set and
validation floor for every ring. Entity relations are `sameIdentityAs`,
`successorOf`, and `relatedEntity`; name equality cannot support identity.
Value relations are `exactCrosswalk`, `broadCrosswalk`, `narrowCrosswalk`, and
`replacedBy`, with source and target editions and effective dates. Legal
relations are `cites`, `amends`, `authorizes`, and `implements`, with an
`effectiveAt` date. The remaining designs add source-specific relation
generation, richer merge and lifecycle semantics, explicitly registered trusted
proof adapters, and ring-specific checks without forking the shared record
shapes.

Every proof adapter is an explicit executable trust decision. RefSpec code
registers the exact adapter class; its content-derived pin names the same
`proofAdapter`; captured data cannot register one; and a subclass does not
inherit authority. The shared shape therefore supports new ring-specific
proofs without treating any path-backed object as a trusted interpreter.

- **Entity spine and proof layer — safety floor implemented; production design
  open.** The shared predicates and evidence checks prevent name equality from
  merging entities. The production spine must model agencies, award entities,
  committees, providers, and substances with typed identifier sets; define
  merge, successor, and lifecycle rules; and register a trusted entity proof
  adapter. It cannot reuse the subject-only Crosswalk v2 proof adapter. The
  source matrix's `T3-04` already anticipates this work. Priority: immediately
  after B4, because every cross-document product feature
  (follow-the-company, follow-the-rule) runs through the spine or legal identity
  graph.
- **Legal identity graph — predicate floor implemented; source-backed edge
  design open.** CFR structure, statutes, RINs, docket identifiers, and bill
  identifiers exist as parsed fields. The next design must derive the existing
  typed predicates (*cites*, *amends*, *authorizes*, and *implements*) from
  exact sources and define point-in-time lifecycle and proof rules — the ELI
  analogue.
- **Code ledgers and value interchange — foundation implemented.**
  `source_controlled_resource` and `regulatory_native_controls` publish
  versioned value sets with preserved raw values. The shared value predicates,
  edition/effective-date checks, and subject/value SSSOM distribution exist.
  Remaining work is source-specific reviewed edition crosswalks (NAICS
  2017→2022) as they become product-relevant.

The shared package model also supports identifier-poor sources in any ring:
UUIDv7 source-fetch and package-registration events, UUIDv7 local record IDs,
and separate membership and record-content digests. CRS demonstrates the
cross-ring refresh rule: identifier-first or exact-label matches preserve
local IDs, any capture-independent content change creates a reconciliation
report, and the immutable ledger retains the packages and human review.

One composition rule crosses B3 and the parent's §3. The pipeline may search
subject and entity indexes in parallel. A strong entity result may supply
abstention evidence against a forced-choice subject error, but ring-scoped
ranking, mappings, and output keep it out of the subject candidate pool.

Every physical ring partition inherits the shared foundation. Consumers use
common artifact and document identifiers, role-qualified entity links, exact
source and release provenance, namespace and collision rules, and read-model
identities derived from input digests. Exact release pins and publication
decisions provide shared historical reconstruction. Effective-time fields and
checks remain ring-specific: value and legal-identity relations carry their
defined effective dates, subject mappings do not invent them, and the entity
design must define the time semantics of successor and identity links. A
consumer never invents joins or translates among competing identity models.

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

## D. Registry target-state check (2026-08-04)

Every module in `src/refspec/registry/` (75 substantive modules: 54 source
modules and 21 implementation modules) is
classified by semantic ring, with docstrings verified for modules the
proposal's tables do not name. A source may contribute more than one row when
its facets belong to different rings. Shared infrastructure receives no ring.

**D1 — Existing readers preserve evidence; some source-concept releases remain
implementation work.** Several readers deliberately refuse to invent publisher
concepts: `gao_topics` captures actual assignments,
`federal_register_topics_api` preserves source bytes, and
`crs_product_topics` treats labels as edition-bound evidence. Those refusals
remain correct. The target state adds an explicit source-concept release over
the verified capture, preserving publisher identifiers where available and
minting a named RefSpec source identity otherwise. The current absence of
that release is implementation work, not evidence that the source lacks
concept identity.

**D2 — Intended use is evidence, not permission — implemented.** The factual
use and permission-field split is complete. `source_controlled_resource.ResourceUse`
includes uses such as `mappingReference`, and atlas-index rows record intended
uses alongside semantic ring and subject participation. Shared models reject
`candidateUseAuthorized` and other permission-shaped fields; no compatibility
shape replaces true with false. `OutputProfile` and the pinned retrieval policy
remain the only permission sources. For subject emission, a pinned
`SubjectEmissionPolicy` is a required eligibility input rather than another
permission source; the `OutputProfile` must name that exact policy before
granting use.

**D3 — Source-assigned topic evidence is metadata, not a ring (parent §3).**
GAO topics, CBO topic labels, CRS product topics, LDA issue codes, and SAM
mission/subject fields are per-document publisher evidence. The labels are
subject-ring terms and carry source-scoped concepts (parent §3); the
assignments are document-to-concept evidence records, not concepts or
destinations. They flow through `sourceAssignedEvidence` observations to the
pipeline. A named admission review may approve the existing subject identity
for the curated emit tier. A pinned `SubjectEmissionPolicy` selects that exact
review and release, and an active `OutputProfile` naming the policy authorizes
emission. A mapping to another concept requires its own §6 evidence.

**D4 — Placement decisions.** `courtlistener_codes` (court identity) and
`census_geo_codes` (geography identifier grammar) sit in the entity ring and
belong to the entity partition, not the value partition;
`census_gov_finance_codes` is a
value-ring crosswalk reference. These physical placements all implement the
shared foundation. The parent's tables remain illustrative; the atlas index
is the exhaustive assignment of record.

**D5 — Not sources.** Eighteen non-reader modules are shared
infrastructure, adapters, managed-release builders, or packages,
organized as subpackages since the registry restructure:
`infrastructure/` (the shared models — `source_controlled_resource`,
`managed_vocabulary_bundle`, `concept_domain_bridge`,
`controlled_identifier`, `regulatory_native_controls`, `zyte_transport`,
and peers), `managed_releases/` (the ICPSR and FR Thesaurus 2025
builders), `adapters/`, and `packages/`. The Lists-of-Subjects policy
moved out of the registry to
`policies/federal_register_lists_of_subjects`; the ELSST managed-release
builder and its test were deleted outright (parent §9 carries the
undecided digest question that deletion left behind). They take no ring
assignment and appear in the atlas index only as implementation, not as
sources.

## E. Corrections outside this document set — completed

The publication-guide contradiction is resolved: `docs/atlas-publication.md`
now documents only canonical and derived Atlas 2.0 distributions, exact
publication decisions, and native four-ring explorer data. The dated
`output/atlas-qualification-fr-icpsr-2026-08-03/README.md` now preserves the
96-call interruption account and appends its completion note: all 730 calls
completed, the bundle was sealed, and 119 mappings qualified. No correction in
this section remains open.
