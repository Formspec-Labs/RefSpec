<!-- markdownlint-disable MD013 -->

# Concept Tagging Architecture Research Proposal

> **Status:** Consolidated historical research proposal; nonnormative
>
> **Date:** 2026-07-28
>
> **Decision gate:** A frozen, untouched holdout and representative
> end-to-end consumer tasks
>
> **Research basis:** [Recovered blind external research](evidence/blind-external-research-recovery-2026-07-28/README.md)

## Status and practical meaning

This document consolidates the original concept-tagging architecture proposal
and its longer research synthesis. It records the architecture that the
available research made worth testing. It does not define RefSpec conformance
and does not adopt a vocabulary, retrieval method, model, threshold, or
deployment profile.

The [RefSpec specification](../spec/refspec.md) and applicable
[Rulespec application profile](../profiles/rulespec-application-profile.md)
are the authorities for interoperable records and conformance. In particular,
the specification treats the concrete choices in this proposal as
[research hypotheses](../spec/refspec.md#155-research-hypotheses).

The central proposal is:

> Test a typed mapping-and-assignment design that uses stable controlled
> identifiers, keeps unlike semantic resources in separate facets, preserves a
> broad mapping space, restricts each output space by declared policy, and
> permits evidence-backed open results or abstention.

The research does not support the simpler conclusion that a large label space
is inherently defective. Large label spaces can work when labels represent
the same kind of thing, target concepts exist, training and evaluation labels
are consistent, and candidate generation has sufficient recall. The
513,236-row fused registry examined in the research instead mixed resources
built for different purposes.

## Evidence rule

The recovery contains nine reports: eight complete reports extracted from
private research transcripts and one independently reconstructed report. The
reports preserve verification flags, corrections, and unverified leads. This
proposal does not upgrade a report-level claim into a verified implementation
fact.

This document distinguishes:

- **Observed evidence:** a result recorded by the recovered research or a
  pinned source inventory, with the limitations stated there.
- **Research interpretation:** a conclusion that reconciles several observed
  results.
- **Hypothesis:** a design choice that requires evaluation before adoption.
- **Normative requirement:** a requirement stated only in the RefSpec
  specification or its pinned Rulespec profile, not in this document.

In this document, **gold** means an independently adjudicated expected result,
not a label copied from a tagger or presumed correct because a source supplied
it.

No external report or development result authorizes deployment. A frozen
holdout and end-to-end consumer evaluation remain the decision gates.

## What the research supports

### 1. Resource type matters more than raw row count

The fused registry combines resources that answer different questions:

- Federal Register and Congressional Research Service terms describe policy
  subjects.
- Faceted Application of Subject Terminology (FAST) describes subjects used in
  library catalogs.
- Toxic Substances Control Act and Chemical Abstracts Service records identify
  chemical entities.
- Code of Federal Regulations citations identify legal locations.
- Regulation Identifier Numbers, agency, stage, and document type identify
  regulatory identity and process.
- Federal Register `toc_subject` values commonly describe action or genre.

One searchable index may contain all of these resources. That does not make
every row eligible for the same output facet.

### 2. Mapping space and output space answer different questions

The proposed architecture separates:

1. **What may help interpret, retrieve, or map this item?** This mapping space
   may be broad and may include specialist, entity, and reference resources.
2. **What may be emitted for this facet and profile?** This output space is
   typed, versioned, governed, and reviewable.

This distinction resolves the apparent conflict between removing FAST and
chemical rows from a general-subject pool and retaining them to recognize
named entities or avoid unsafe nearest-subject mappings. A resource can help
candidate generation without being eligible for subject assignment.

### 3. Candidate availability and assignment correctness are separate

A candidate stage fails when an adequate concept does not reach the
adjudicator. An assignment stage fails when the adjudicator selects an
unsupported, overly broad, wrongly typed, or merely adjacent concept from an
adequate candidate set.

The research reports both failure modes:

- large pools can dilute candidate recall;
- missing concepts can force unsafe nearest-neighbor mappings;
- near-synonyms can produce plausible but incorrect outputs; and
- wider candidate lists can reduce precision even when recall rises.

Registry availability, candidate recall, and final assignment therefore need
separate measures.

### 4. Retrieval choice remains an empirical question

Large-label-space studies show wide performance differences between embedding
models on the same data. Lexical retrieval can match or beat generic dense
retrieval on legal or label-heavy tasks. A lexical-and-dense hybrid is a
hypothesis to compare with both components, not a presumed default.

An earlier bounded experiment rejected approximate nearest-neighbor search as
a direct replacement for exact dense search in that test: lower-memory
settings lost candidates, while the setting that preserved the development
oracle saved little memory. Exact dense search is the appropriate comparison
baseline until measured scale, memory, or latency establishes a need for an
approximate index. The result does not show that approximate search can never
help.

### 5. Embedding geometry did not justify a registry change

The original `0.029` similarity-margin interpretation compared unlike
distributions: document-to-concept similarity and concept-to-concept
similarity. The corrected document-to-random-concept comparison produced a
larger margin. The reported `43/768` effective-dimension result was also
non-diagnostic because low effective dimension can coexist with useful
clusters.

The narrower remaining observation is that repeated template text dominated
many concept representations. Genuine labels, aliases, scope notes, and
structurally cleaned definitions deserve separate tests. Geometry alone does
not authorize a registry or model change.

### 6. Federal sources provide several axes, not one complete taxonomy

The federal-resource research identified useful but differently scoped inputs:

- The Federal Register Thesaurus chiefly supports Rules and Proposed Rules.
- Federal Register `toc_subject` values cover many Notices but commonly
  express action or genre rather than general subject.
- The CFR List of Subjects connects terms to affected CFR parts and may supply
  ranking evidence.
- CRS Legislative Subject Terms cover legislative material.
- CRS Policy Areas provide broad navigation categories.
- RIN, agency, stage, legal authority, CFR citation, and North American
  Industry Classification System codes provide structured facets.
- EPA, National Agricultural Library Thesaurus, Medical Subject Headings,
  NASA, and similar resources are candidates for specialist modules.

No one source covers every source family, record kind, or semantic facet in
the [source and document type matrix](source-document-type-matrix-2026-07-28.md).

### 7. Metadata begins as a soft signal

The source-prior research found no strong published basis for hard
agency-based vocabulary partitions. Related systems use metadata as a feature,
route documents rather than vocabularies, or union a restricted result with a
recall-preserving global result. Common Federal Register terms also cross
agency boundaries.

The research therefore supports testing a score or candidate union such as:

```text
text evidence
+ CFR-part prior, when available
+ parent-agency prior, when useful
+ global candidate path
```

CFR part is the more direct signal, so the proposal tests it before agency.
Neither signal vetoes a globally strong candidate unless an evaluation for the
exact profile proves that the restriction preserves required recall.

### 8. Corpus-derived concepts are a later remedy

Taxonomy-induction research shows that language models can propose topics and
organize supplied terms. It also reports unstable topic counts, limited
exact-label agreement, weak reproducibility, and substantial review cost.

A safer pattern is:

- governed concepts with stable identifiers; and
- evidence-backed concept proposals that remain proposals until reviewed and
  promoted under an explicit governance process.

Induction becomes relevant only after measured, recurring, useful coverage
gaps show that typed retrieval, open labels, local proposals, and abstention
are insufficient.

## Reconciled design questions

| Apparent conflict | Reconciled research position |
| --- | --- |
| Delete most registry rows vs. retain broad coverage | Restrict the general-subject output policy; retain useful typed resources in the mapping space |
| Small curated vocabulary vs. specialist coverage | Test a reviewable general layer alongside separately activated specialist modules and open-set behavior |
| Agency-specific pools vs. cross-agency subjects | Test CFR and agency as soft signals unioned with a global path; do not begin with hard partitions |
| Label descriptions help vs. hurt | Test labels, aliases, genuine scope notes, and cleaned source definitions separately; do not append generated descriptions by default |
| Dense retrieval works vs. lexical retrieval wins | Compare exact alias, lexical, exact dense, and fused retrieval on identical targets |
| Generate-then-map improves recall vs. mapping creates plausible errors | Preserve generated phrases, require evidence for canonicalization, control output count, and permit abstention |
| Hierarchy supports backoff vs. hierarchy distorts meaning | Preserve source relationships losslessly; test hierarchy expansion separately from assignment correctness |
| Induce a vocabulary vs. retain controlled identifiers | Keep stable identifiers and stage grounded proposals; induce only after measured recurring gaps |

## Architecture hypothesis

### Typed result facets

The research proposes separate candidate and output treatment for each facet:

| Facet | Examples | Candidate treatment to evaluate |
| --- | --- | --- |
| General subject | Air pollution control; immigration policy | Governed general-subject schemes, with exact evidence |
| Specialist subject | Food safety; clinical procedure; aerospace technology | Versioned specialist modules activated from item evidence |
| Entity | Chemical, organization, place, person, facility, or program | Separate recognition and normalization; never consume a subject slot |
| Legal location | CFR, USC, Public Law, or court citation | Deterministic parsing or authoritative source metadata |
| Industry classification | NAICS industry | Typed classification mapping |
| Regulatory process | RIN, stage, priority, document type, or authority | Deterministic source fields and governed code lists |
| Action or genre | Hearing notice; directive; information-collection activity | Preserve source-native values such as `toc_subject`; do not treat them as general-subject gold |
| Broad navigation | CRS Policy Area or another reviewed grouping | Separate coarse category with its own evaluation |
| Open result | Grounded phrase or concept absent from registered resources | Preserve exact evidence and status; do not force a registered match |

This table is a research decomposition, not a closed RefSpec facet list. The
normative facet model is defined by
[RefSpec semantic enrichment](../spec/refspec.md#9-semantic-enrichment).

### Candidate general-subject layer

A low-thousands general-subject layer assembled from reconciled Federal
Register and CRS concepts is a reasonable experiment, not an adopted registry
or quota. The research mentions starting ranges of roughly 1,000–3,000 and a
possible governed range of 2,000–8,000. Those ranges express uncertainty, not
requirements.

An evaluated layer would:

- reconcile Federal Register API, PDF, and locally extracted concepts;
- preserve the distinct identities of source schemes;
- keep CRS Policy Areas separate as broad navigation;
- treat CFR List-of-Subjects assignments as part-and-term evidence;
- exclude ad hoc values until review establishes their meaning; and
- use reviewed mappings instead of merging concepts solely because their
  labels match.

The holdout decides whether the layer has adequate coverage and adds value over
serving source schemes separately.

### Specialist, entity, and reference modules

- Treat chemical authorities as entity-mapping resources, not as general
  subject slots.
- Keep FAST as a separately identifiable mapping, search-expansion, or
  reference resource unless evaluation justifies another role.
- Activate specialist subject modules only for relevant evidence strata.
- Preserve the source identifier and release for every candidate.
- Keep identically labeled concepts distinct until a reviewed mapping states
  their relationship.

### Candidate and assignment flow

1. Accept immutable text and evidence fragments plus document type, source
   profile, agency, legal citations, process identifiers, and other structured
   metadata.
2. Extract deterministic identities, citations, types, and process values.
3. Extract grounded subject phrases and typed entities in separate passes.
4. Select the general mapping resources and evidence-supported specialist
   modules.
5. Retrieve subject and entity candidates in separate pools through exact
   aliases, lexical search, and exact dense search.
6. Add CFR-part and parent-agency signals as optional score components or
   candidate channels while retaining a global path.
7. Union channels, preserve source releases and generating channels, and
   measure recall at wider depths before trimming to an adjudication budget.
8. Ask the adjudicator for zero or more results, each with a facet, role, and
   exact supporting evidence.
9. Accept a registered identifier only when the evidence supports that exact
   concept, type, and release.
10. Otherwise preserve a review candidate, grounded open result, concept
    proposal, or abstention according to the applicable profile.

No fixed source quota or shortlist size is an architecture constant in this
proposal.

### Source-sensitive behavior to test

- **Rules and Proposed Rules:** Evaluate official Federal Register subject
  assignments as source evidence within their documented scope.
- **Notices:** Preserve `toc_subject` as action or genre metadata and evaluate
  topical subjects independently.
- **CFR-linked material:** Test the CFR List of Subjects as ranking evidence,
  not automatic assignment.
- **Congressional and legislative material:** Test CRS terms when their scope
  matches the evidence.
- **Domain-heavy material:** Add the relevant specialist module without
  removing the global general-subject path.
- **Other source families:** Define a profile-specific evidence and evaluation
  policy rather than inheriting behavior from superficially similar documents.

These are hypotheses for source strata, not normative rules for all RefSpec
implementations.

### Relationships and mappings

A lossless import preserves source-stated broader, narrower, related,
replacement, and mapping relationships without forcing them into a
single-parent tree. A consumer may derive an acyclic navigation view without
deleting or rewriting the source graph.

The proposed mapping treatment retains each relationship's meaning:

- `exactMatch` means reviewed equivalence;
- `closeMatch` means similarity that is unsafe to merge;
- broader and narrower mappings remain directional; and
- `related` does not establish hierarchy.

Matching labels alone do not establish a mapping. The normative import,
release, and mapping rules appear in
[RefSpec registry operations](../spec/refspec.md#12-registry-operations-and-concept-governance).

### Output and provenance

The research requires enough information to reproduce and challenge a result:

- target and exact evidence location;
- facet and assignment role;
- concept, scheme, and source-release identifiers, when registered;
- candidate-generating channels and ranks;
- method, model, prompt, policy, and registry versions or digests;
- outcome and abstention reason;
- machine or human attestation status; and
- correction or supersession history.

This proposal adds no portable schema fields. RefSpec and Rulespec define the
normative records used to publish accepted results. Under this proposal, a
concept proposal does not silently become a registered concept, and machine
agreement is not described as human review.

## Evaluation program

### Questions to answer

| Question | Decision controlled |
| --- | --- |
| Does each output space contain an adequate target? | Whether a general or specialist scheme is viable or open-set handling is required |
| Does a broad typed mapping space improve coverage without increasing wrong-facet errors? | Whether reference and entity resources assist candidate generation |
| Which retrieval method surfaces adequate targets? | Exact alias, lexical, dense, or fused selection |
| Do CFR and agency signals improve recall without cross-agency loss? | Metadata-ranking policy |
| Which source-authored label text improves target rank? | Indexed representation policy |
| Can adjudication distinguish exact, broader, related, and unsupported candidates? | Acceptance and abstention policy |
| Does the complete consumer task improve? | Whether the tested component is worth adopting |

### Evaluation-corpus requirements

Build a time-separated development set and untouched holdout that cover the
source families, record kinds, facets, and risk levels in the intended
deployment profile. For each item, record:

- immutable artifact and evidence-fragment identifiers;
- source family and subtype;
- expected facet and assignment role;
- an adequate registered target when one exists;
- target relationship grade: exact, close, broader, narrower, related, or not
  represented;
- acceptable open-result, concept-proposal, or abstention behavior;
- forbidden concepts and wrong-facet outcomes; and
- evidence spans supporting each expected result.

Separate development and holdout items by artifact digest and keep linked
versions or renditions in the same split. Pin source, registry, mapping,
candidate-selection, prompt, model, schema, policy, and budget versions before
revealing holdout labels. Draft expected results without tagger output. Use
independent adjudication and resolve or exclude unresolved disagreements.

Once holdout results influence a design change, that holdout becomes
audit-only.

### Experiment ladder

Change one controlled variable at a time.

#### Experiment 0 — Target availability

For every expected result, inspect each registry configuration before running
retrieval:

- the fused baseline;
- the candidate general-subject layer;
- that layer plus the relevant specialist modules; and
- the same configurations with open results or concept proposals allowed.

Report target presence and relationship grade. If no adequate target exists,
stop retrieval tuning for that item and evaluate open-set behavior.

#### Experiment 1 — Output eligibility

Hold retrieval and adjudication fixed. Compare:

- all fused subject-like rows eligible for emission;
- only the candidate general-subject layer eligible; and
- broad typed resources available for mapping while output remains
  facet-restricted.

This experiment isolates the central mapping-space-versus-output-space
hypothesis.

#### Experiment 2 — Candidate retrieval

On the selected development output policy, compare:

- exact alias and lexical retrieval;
- exact dense retrieval; and
- lexical-and-dense fusion.

Report adequate-target recall at declared depths before adjudication-budget
trimming. Also report latency, memory, source composition, and repeated-hub
frequency. Reopen approximate-search work only when an operating constraint
justifies it.

#### Experiment 3 — Metadata signals

Compare the selected retriever with and without:

- CFR-part evidence;
- parent-agency evidence; and
- a recall-preserving global union.

Report losses on cross-agency subjects and broad-remit agencies separately.
Do not begin by intersecting metadata-derived and global candidate sets.

#### Experiment 4 — Indexed label text

Compare:

- preferred labels and aliases;
- labels, aliases, and genuine source scope notes;
- structurally cleaned source definitions; and
- template-heavy text as a regression baseline where it exists.

Test generated descriptions only as a distinct variant after source-authored
text proves inadequate.

#### Experiment 5 — Adjudication and cardinality

Freeze candidates and compare acceptance policies or adjudicators. Measure
whether each method:

- selects exact or explicitly acceptable concepts;
- rejects merely related or wrong-facet candidates;
- emits an appropriate number of results;
- binds exact supporting evidence; and
- abstains when no safe result exists.

Add a cross-encoder or trained classifier only if candidate recall is adequate
and adjudication remains the measured constraint.

#### Experiment 6 — End-to-end consumer task

Run the winning development configuration through representative tasks such
as search, alerts, browse, comparison, or cross-source joins. Freeze expected,
forbidden, and ambiguous records and the evidence for each.

Adopt a component only when the complete task improves without exceeding
declared evidence, reproducibility, latency, cost, rights, or safety limits.

### Measures

| Stage | Required measures | What the result establishes |
| --- | --- | --- |
| Registry | Adequate-target coverage; exact, close, broader, related, and not-represented distribution | Whether retrieval has a valid answer to find |
| Candidate generation | Recall at declared depth by facet, source, and target grade; latency and memory | Whether adjudication has a fair opportunity |
| Assignment | Facet- and role-aware precision and recall; unsupported-result rate; wrong-facet rate; evidence support; abstention; cardinality error | Whether semantic decisions are trustworthy |
| Consumer task | Expected and forbidden records; task precision and recall; stable counts; explanation coverage | Whether users receive value |
| Operations | Reproducibility; versions and digests; model calls; cost; latency; memory; failures | Whether the result can run and be audited |

A gain at one stage does not prove a gain at the next. Predeclare metric
definitions, thresholds, target universes, sample sizes, uncertainty
treatment, strata, exclusion rules, and failure consequences before examining
holdout results.

### Stop rules

- If an adequate target is absent, stop retrieval tuning and evaluate open-set
  behavior.
- If candidate recall is poor, do not tune the adjudicator.
- If candidate recall is adequate and assignments remain poor, freeze
  retrieval and investigate ranking, evidence, role, facet, and cardinality.
- If a stage measure improves but the complete consumer task does not, do not
  adopt the component on that evidence.
- If a metadata restriction removes a valid global candidate, reject the
  hard-filter design.
- If repeated development changes produce no material gain, re-examine target
  labels, registry fit, and error categories.
- Do not tune against a final holdout and continue calling it untouched.
- Do not reopen approximate search without a measured memory or latency need.
- Do not induce a replacement vocabulary until recurring, useful,
  not-represented concepts establish the need.
- Do not represent machine attestations as human review.

## Research disposition

The consolidated proposal recommends evaluating, rather than immediately
adopting:

- mapping space separated from output eligibility;
- typed facets and separate entity normalization;
- open results, concept proposals, and abstention;
- exact dense search as the comparison baseline;
- CFR and agency evidence as soft signals;
- source identity and lossless relationship preservation; and
- stage-specific and end-to-end evaluation gates.

It leaves unresolved:

- the membership and size of any general-subject layer;
- whether one cross-source layer improves on serving source schemes
  separately;
- which specialist modules belong in a given deployment profile;
- lexical, dense, or fused retrieval selection;
- approximate-search adoption;
- model, reranker, or cross-encoder selection;
- generated label descriptions;
- automated taxonomy induction; and
- thresholds, costs, and risk limits for a concrete deployment.

The research weighs against:

- one undifferentiated output list for subjects, entities, process values, and
  legal locations;
- hard agency or CFR filtering without profile-specific recall evidence;
- forced nearest-concept assignment;
- source quotas as permanent architecture;
- treating `toc_subject` as universal topical truth;
- treating development data as holdout evidence; and
- making architecture decisions from the retracted similarity-margin or
  effective-dimension interpretation.

Only the RefSpec specification can turn any of these positions into a
conformance requirement.

## Risks and open questions

1. **General-layer coverage:** A smaller output layer may omit valid subjects.
   Specialist modules and open-set behavior reduce harm but do not prove
   adequate coverage.
2. **Source-label scope:** Federal Register and CRS assignments reflect their
   indexing purposes. They are useful evidence, not universal truth.
3. **Notice semantics:** `toc_subject` reaches many Notices but often answers a
   different question from topical classification.
4. **Governance capacity:** Promotion requires named authority, review, rights
   decisions, correction, and dispute handling.
5. **Source-version discrepancies:** Federal Register API and PDF counts
   differ, and specialist resources may have unresolved freshness, coverage,
   or rights questions.
6. **Hierarchy fidelity:** A compatibility tree can erase multi-parent
   relations or cycles unless the full source graph remains available.
7. **Evaluation scale:** A bounded holdout can support a bounded decision, not
   a claim of complete domain coverage.
8. **Model drift:** Model, prompt, representation, or policy changes require
   new versions and cannot inherit a prior adoption verdict automatically.
9. **Operating cost:** Wider mapping and reranking may improve recall while
   increasing latency, memory, and model cost.
10. **Consumer value:** Better subject metrics may still fail to improve
    search, alerting, navigation, comparison, or joining.

## Research map

- [Parent ANN context](evidence/blind-external-research-recovery-2026-07-28/00-ann-parent-context-before-research-reports.md):
  exact-search comparison, source composition, retracted interpretation, and
  the pre-report boundary.
- [Industry and large-label-space tagging](evidence/blind-external-research-recovery-2026-07-28/01-industry-and-llm-era-large-label-space-tagging.md):
  large taxonomy scale, retrieve-then-adjudicate patterns, and evidence gaps.
- [Extreme multilabel classification](evidence/blind-external-research-recovery-2026-07-28/02-extreme-multilabel-classification.md):
  candidate methods, distractor effects, and typed mapping-versus-output
  reasoning.
- [Taxonomy induction](evidence/blind-external-research-recovery-2026-07-28/03-taxonomy-induction.md):
  corpus-derived vocabularies, generation and mapping, review, and
  instability.
- [Label text and embedding geometry](evidence/blind-external-research-recovery-2026-07-28/04-label-text-and-embedding-geometry.md):
  corrected geometry interpretation, boilerplate, model choice, hubness, and
  label-text experiments.
- [Controlled-vocabulary scoping](evidence/blind-external-research-recovery-2026-07-28/05-controlled-vocabulary-scoping.md):
  Federal Register coverage corrections, resource roles, metadata signals,
  and typed use.
- [Source partitioning and metadata priors](evidence/blind-external-research-recovery-2026-07-28/06-source-partitioning-and-metadata-priors.md):
  evidence against hard partitions and for recall-preserving soft signals.
- [US federal controlled vocabularies](evidence/blind-external-research-recovery-2026-07-28/07-us-federal-controlled-vocabularies.md):
  federal subject, legal, process, entity, and specialist resources.
- [Corpus-driven vocabulary development](evidence/blind-external-research-recovery-2026-07-28/08-corpus-driven-vocabulary-development.md):
  term-extraction limits, proposal governance, review cost, and promotion
  gates.
- [Controlled-vocabulary stop rules and federal inventory](evidence/blind-external-research-recovery-2026-07-28/when-to-abandon-controlled-vocabulary-and-federal-vocabulary-inventory.md):
  reconstructed hybrid recommendation, inventory, typed design, and holdout
  requirements.

## Conclusion

Treat the fused registry examined by the research as a library of typed
resources, not as one universal subject definition.

The architecture worth testing combines stable identifiers, facet-specific
output policies, broad but typed mapping resources, exact evidence, open-set
behavior, and lossless source relationships. Concrete registry membership,
retrieval methods, metadata signals, models, thresholds, and deployment
profiles remain replaceable hypotheses.

Adopt any concrete component only after a frozen evaluation shows that it
improves its own stage and a representative end-to-end consumer task.
