<!-- markdownlint-disable MD013 -->

# Concept tagging research synthesis and testable proposal

> **Status:** Draft; not adopted
>
> **Date:** 2026-07-28
>
> **Purpose:** Convert the recovered blind research into a product decision, a
> testable architecture, and a sequenced evaluation plan
>
> **Evidence base:** [Blind external research recovery](evidence/blind-external-research-recovery-2026-07-28/README.md)
>
> **Current implementation authority:** [RefSpec implementation plan](../plans/implementation-plan.md)

## Proposed decision

Adopt a **typed mapping-and-assignment design as the next research direction**.
Do not adopt a new production vocabulary yet.

The design should:

- keep controlled concepts as stable identifiers;
- separate general subjects, specialist subjects, entities, legal locations,
  process fields, and action or genre fields;
- use a small general-subject core as an output candidate, not as a presumed
  winner;
- retain large vocabularies as typed mapping and reference sources;
- allow the tagger to abstain or retain an evidence-backed local concept;
- use source metadata as a soft ranking signal, never as a hard vocabulary
  filter; and
- require an untouched holdout and an end-to-end product result before
  adoption.

This proposal reclassifies the 513,236-row fused registry under evaluation. It
remains valuable as source data, a diagnostic baseline, and a broad mapping
resource. It should not define one flat production subject list merely because
all rows fit in one table.

This research predates the RefSpec editor's draft. The current
[implementation plan](../plans/implementation-plan.md) now governs sequencing,
including holdouts, deterministic discovery questions, attestations, and the
assignment-publication bridge.

## Practical meaning

The research does not support the simple statement that “513,236 labels are
too many.” Large label spaces can work when the labels represent the same kind
of thing, the target concepts exist, the training and evaluation labels are
consistent, and the candidate stage has enough recall.

The current registry has a different problem: it mixes resources built for
different jobs.

- Federal Register and Congressional Research Service terms describe policy
  subjects.
- Faceted Application of Subject Terminology (FAST) describes subjects used in
  library catalogs.
- Toxic Substances Control Act records identify chemical substances.
- Code of Federal Regulations citations describe legal location.
- Regulation Identifier Numbers, agency, stage, and document type describe
  regulatory identity and process.
- Federal Register `toc_subject` values mostly describe action or genre.

Putting these values in one search table can be useful. Treating every value
as an equally eligible document subject is not.

The architecture should therefore separate two questions:

1. **What may help interpret or map this document?** This mapping space may be
   broad.
2. **What may the product emit as this kind of result?** This output space
   should be typed, governed, and narrow enough to review.

That distinction reconciles the strongest disagreement in the research. Some
reports recommend removing almost all FAST and chemical rows from the subject
pool. Other evidence shows that a wider mapping space can absorb named
entities and prevent a missing concept from snapping to an unrelated subject.
Both can be right: use a broad, typed mapping space and a narrower, typed
output policy.

## Evidence rule

The recovery contains nine research reports: eight complete reports extracted
from their original transcripts and one independently reconstructed report.
The reports preserve their authors' verification flags, corrections, and
unverified leads. This synthesis does not upgrade a report-level claim into a
verified project fact.

This document uses three evidence classes:

- **Verified local evidence** comes from current repository data, code, or
  recorded experiments that can be reproduced locally.
- **Research evidence** comes from a recovered report and inherits that
  report's verification note.
- **Proposal** is the interpretation or design choice made here.

In this document, **gold** means an independently adjudicated expected result,
not a label copied from the tagger or assumed correct because a source supplied
it.

No external research result authorizes production adoption. The untouched
holdout and product queries remain the decision gates.

## What the research establishes

### 1. Approximate search is not the current decision

The bounded USearch experiment rejected approximate nearest-neighbor (ANN)
search as a direct replacement for exact dense search. The only tested setting
that preserved the small development oracle saved little memory, and
lower-memory settings lost many candidates. Exact search should remain the
baseline until measured registry growth, worker memory, or latency creates an
operating constraint.

This is a local development result, not a claim that approximate search can
never help. It removes ANN tuning from the current critical path.

### 2. The original embedding-space diagnosis was wrong

The original `0.029` similarity-margin claim compared unlike distributions:
document-to-concept similarity and concept-to-concept similarity. The corrected
document-to-random-concept comparison produced a much larger margin. The
`43/768` effective-dimension result is also non-diagnostic; low effective
dimension can accompany useful clusters.

The verified remaining issue is narrower: repeated template text dominates
many concept embedding strings. That input deserves an A/B test. Its effect on
candidate recall remains unproved until the full ablation completes.

The correct measurements are:

- gold-concept availability in the registry;
- gold-concept rank for each document or segment;
- candidate recall at a declared depth;
- document-to-random-concept similarity as the null; and
- final assignment and product-query quality.

Geometry alone cannot authorize a registry change.

### 3. Retrieval quality depends on label quality and model choice

The large-label-space reports show wide performance differences between
embedding models on the same data. They also show that lexical retrieval can
match or beat generic dense retrieval on legal or label-heavy tasks. A hybrid
is therefore a hypothesis to test, not a default to assume.

The current development result—three of eight exact targets in the top 12—is
not evidence of catastrophic failure when compared with published zero-shot
results at similar scale. It is also too small and too contaminated by tuning
to establish readiness. The original 35 artifacts remain development data.

### 4. Candidate availability and output correctness are different problems

A candidate stage fails when the right concept never reaches the judge. An
assignment stage fails when the judge selects an unsupported, overly broad,
wrongly typed, or merely adjacent concept from an adequate candidate set.

The research repeatedly reports both failure modes:

- large pools dilute candidate recall;
- missing concepts cause forced nearest-neighbor mapping to unrelated terms;
- near-synonyms create “technically related but not actually right” outputs;
  and
- large candidate lists can reduce precision even when recall rises.

The system must measure registry availability, candidate recall, and final
assignment separately.

### 5. Federal sources supply several useful axes, not one complete taxonomy

The federal-vocabulary research identifies a strong regulatory subject seed,
but no single source covers the product:

- The Federal Register Thesaurus applies chiefly to Rules and Proposed Rules.
- `toc_subject` reaches many Notices but describes action or genre rather than
  general subject.
- The CFR List of Subjects ties terms to affected CFR parts and can supply
  ranking evidence.
- CRS Legislative Subject Terms cover legislative material and may complement
  the regulatory subject seed.
- CRS Policy Areas supply broad navigation categories.
- RIN, agency, stage, legal authority, CFR citation, and North American
  Industry Classification System (NAICS) codes are useful structured facets.
- EPA, NALT, MeSH, NASA, and similar resources are specialist modules, not one
  general vocabulary.

The current source matrix already distinguishes documents, containers,
entities, observations, participation records, and external joins. Concept
assignment should preserve those differences.

### 6. Agency and CFR metadata should guide ranking, not exclude candidates

The source-prior research found no strong published precedent for hard
metadata partitions. The closest systems use source metadata as a soft
feature, route documents rather than vocabularies, or union a restricted set
with a recall-preserving global set.

The Federal Register analysis also found that many commonly assigned terms
cross agency boundaries. A hard agency filter would remove valid general
terms. The better hypothesis is:

```text
score = text evidence
      + CFR-part prior when available
      + parent-agency prior when useful
      + global prior
```

Each prior contributes candidates or score. None may veto a globally strong
candidate. CFR part should precede agency because it is closer to the official
subject-assignment rule, but the holdout must decide whether either signal
adds value.

### 7. A new corpus-derived vocabulary remains a later option

Taxonomy-induction research shows that language models can propose useful
topics and organize supplied terms. It also shows unstable topic counts,
limited exact-label agreement, low reproducibility, and substantial human
review.

The most transferable production pattern is a two-tier registry:

- a governed registered tier with stable identifiers; and
- a staging tier for grounded local concepts, each linked to evidence and,
  when possible, to a broader registered concept.

The project should not induce a replacement vocabulary before measuring which
valid concepts the proposed core lacks. If recurring, useful gaps remain after
typed retrieval and abstention, corpus-driven induction becomes a focused
remedy rather than a speculative rewrite.

### 8. No research report proves the production architecture

The recovery found no verified organization that replaced a governed
controlled vocabulary with language-model-generated tags and published
before-and-after quality, cost, governance, and operating evidence.

The literature supports experiments and design patterns. The project must
produce its own adoption evidence.

## Resolution of the apparent contradictions

| Apparent conflict | Resolution proposed here |
| --- | --- |
| Delete most of the registry vs. add missing entities and concepts | Remove ineligible rows from the **subject output policy**; keep typed entity and reference rows in the **mapping space** |
| Small curated vocabulary vs. broad coverage | Start with a reviewable core, preserve specialist modules and local candidates, and measure abstention and coverage gaps |
| Agency-specific vocabulary vs. cross-agency subjects | Use CFR and agency as soft score components unioned with global retrieval; never hard-partition by agency |
| Label descriptions help vs. label descriptions hurt | Test labels, aliases, genuine scope notes, and cleaned definitions separately; do not generate or append descriptions by default |
| Dense retrieval works vs. lexical retrieval wins on legal text | Compare lexical, dense, and hybrid methods on identical inputs and the same target set |
| Generate-then-map improves recall vs. mapping creates plausible errors | Permit free phrase extraction, but canonicalize only with evidence and allow abstention; control output count |
| Hierarchy helps backoff vs. hierarchy can distort meaning | Preserve source relationships losslessly; test hierarchy-assisted retrieval separately from assignment correctness |
| Induce a new vocabulary vs. keep controlled identifiers | Keep stable identifiers and stage local concepts; induce only after measured recurring coverage gaps |

## Proposed product model

### Typed result layers

| Result kind | Examples | Assignment rule |
| --- | --- | --- |
| General policy subject | Air pollution control; immigration policy | Semantic assignment with exact evidence; governed core only |
| Specialist subject | Aerospace engineering; food safety; biomedical topic | Activate a versioned specialist module only when document evidence supports the domain |
| Regulated entity | Chemical substance, organization, place, program | Separate recognition and normalization; never consume a subject slot |
| Legal location | CFR title, chapter, part, or section | Deterministic citation parsing or source metadata |
| Regulatory process | RIN, stage, priority, document type, legal authority | Deterministic source fields and normalized code lists |
| Action or genre | Hearing notice, information-collection activity, airworthiness directive | Preserve source-native values such as `toc_subject`; do not score as general-subject gold |
| Broad navigation | CRS Policy Area or another small reviewed grouping | Separate coarse category with its own evaluation |
| Open local concept | Grounded concept absent from registered resources | Retain evidence, status, provenance, and review need; never force a registered match |

### What goes in

- immutable artifact text and exact source fragments;
- document type and source profile;
- agency and parent agency;
- CFR references, RIN, docket identifiers, and legal authority;
- source-assigned topics or categories, with their original meaning; and
- versioned concept resources with source identity, labels, aliases,
  relationships, rights, and retrieval date.

### What happens

1. Parse deterministic identities, citations, types, and process fields.
2. Extract grounded subject phrases and typed entities from source text.
3. Select eligible general and specialist mapping modules from document
   evidence and source metadata. Adding a specialist module must not remove
   globally eligible subject candidates.
4. Retrieve subject and entity candidates in separate pools.
5. Combine exact alias, lexical, and exact dense evidence.
6. Add CFR-part and parent-agency priors as optional score components.
7. Union candidates across channels and preserve their source vocabulary.
8. Trim the candidate list to the prompt budget only after measuring recall at
   larger depths.
9. Ask the semantic judge for zero or more assignments, each with a role and
   exact evidence.
10. Accept a registered identifier only when the evidence supports that exact
    concept and type.
11. Otherwise abstain or retain a local concept.
12. Record machine attestation separately from the assignment. Never describe
    machine review as human approval.

### What comes out

Each registered assignment should carry the Rulespec-aligned fields already
planned for the MVP, including `assignmentRole`, `assignmentDerivation`,
`inScheme`, `assignmentSubjectType`, `assertionOrigin`, and exact evidence
information. The product view should also expose:

- concept and source-vocabulary identifiers;
- concept and vocabulary versions;
- evidence text and exact location;
- method, model, prompt, and registry digests;
- confidence and abstention reason;
- machine or human attestation status; and
- supersession or correction history.

A local concept should carry the same evidence and provenance, plus
`status=candidate` and any reviewed broader or close mapping. Local concepts
must not silently become registered concepts.

### How we check it

Check four levels independently:

1. **Availability:** Does an adequate registered concept exist?
2. **Candidate selection:** Does it appear at the declared depth?
3. **Assignment:** Did the system choose the right type, concept, role, and
   evidence, or abstain correctly?
4. **Product result:** Did the final query return the expected records and
   exclude forbidden ones?

A gain at one level does not prove a gain at the next.

## Proposed registry treatment

### General-subject core candidate

Build a versioned `general-policy-core-v0` for evaluation from:

- Federal Register Thesaurus/API concepts after reconciling the unresolved
  PDF/API difference;
- CRS Legislative Subject Terms with their own identifiers; and
- reviewed cross-vocabulary mappings, without merging authority identities.

Keep CRS Policy Areas outside the detailed subject core as a broad navigation
layer. Use CFR List-of-Subjects assignments as part-and-term evidence, not as
an unlabeled duplicate vocabulary. Exclude Federal Register `ad_hoc` topics
until review establishes that each value is a real concept.

The often-cited 1,000–3,000 starting size is an experimental range, not a
quota. The core should contain the concepts justified by the pinned sources
and reviewed mappings. The holdout should decide whether its coverage is
adequate.

### Typed specialist and entity modules

- Treat TSCA and other chemical records as regulated-entity mapping modules;
  never reserve subject slots for them.
- Keep FAST data as a separately activated search-expansion and mapping source.
  Do not make it an always-on candidate pool unless measured results justify
  that role.
- Pilot specialist subject modules only on relevant source strata.
- Preserve source identifiers. An identical label from two sources remains
  two concepts until a reviewed mapping relates them.

### Relationships and mappings

Preserve source-stated `broader`, `narrower`, `related`, replacement, and
mapping relationships without forcing them into a single-parent tree.

The current `broader_id` column can support compatibility, but it cannot
represent every valid multi-parent relation or source cycle. A later
relationship table should preserve the complete source graph. Consumer views
may derive an acyclic navigation tree without deleting source relationships.
This is a post-MVP data-model change, not part of the current execution path.

Cross-vocabulary mappings must retain their meaning:

- `exactMatch` means reviewed equivalence;
- `closeMatch` means similar but unsafe to merge;
- `broader` and `narrower` stay directional;
- `related` is not hierarchy; and
- matching labels alone do not establish any mapping.

## Evaluation proposal

### Current sequencing boundary

The canonical MVP plan remains authoritative:

1. build and freeze the untouched holdout;
2. complete independent adjudication and the adoption-ready boundary;
3. validate deterministic discovery questions;
4. build the attestations table;
5. bridge docpipeline assignments into publication; and
6. achieve MVP-local acceptance.

This proposal may shape holdout fields and later experiments. It does not
unpark retrieval or authorize registry work ahead of those steps.

### Holdout requirements

The first decision-quality holdout should cover the source families intended
for the first subject-tagging release. It need not include every table merely
because the data exist.

For each item, record:

- immutable artifact and source-fragment identifiers;
- source profile and document type;
- expected subject type and assignment role;
- an adequate registered target when one exists;
- the target relationship grade: exact, close, broader, narrower, related, or
  not represented;
- acceptable local-concept or abstention behavior;
- forbidden concepts and type-confusion errors; and
- evidence spans that support each expected result.

Keep holdout items separate from development by artifact digest, concept
identifier, and every normalized alias. Pin the source, registry, selection,
prompt, schema, model, and token-budget digests before labels are exposed.
Draft gold without tagger output. Use at least two independent model families
or humans for adjudication, with disagreements resolved by a third family or
excluded.

Once the holdout informs another design change, move it to development.

### Questions the experiment must answer

| Question | Decision it controls |
| --- | --- |
| Does the core contain an adequate target? | Whether the core is viable or needs specialist/local coverage |
| Does a broad typed mapping space improve coverage without increasing subject errors? | Whether to retain FAST and entity modules in candidate generation |
| Which retrieval method puts adequate targets in the candidate set? | Lexical, dense, or hybrid selector choice |
| Do CFR and agency priors improve recall without cross-agency loss? | Metadata score policy |
| Does cleaned label text improve gold rank? | Definition and embedding-text policy |
| Can the judge distinguish exact, broader, related, and unsupported concepts? | Judge, prompt, and abstention policy |
| Does the complete per- and polyfluoroalkyl substances (PFAS) query improve? | Product adoption |

### Experiment ladder

Change one variable at a time.

#### Experiment 0 — Target availability

For every gold item, check each registry configuration without retrieval:

- current fused registry;
- proposed general core;
- general core plus relevant specialist modules; and
- local/open concepts allowed.

Report target presence and relationship grade. If an adequate target is
absent, stop tuning retrieval for that item. Score abstention or local-concept
creation instead.

#### Experiment 1 — Output policy

Hold retrieval and judge behavior fixed. Compare:

- **Fused emit:** current eligible fused-subject behavior;
- **Core emit:** only the proposed general core may be emitted; and
- **Typed wide map/core emit:** broad typed resources may assist mapping, but
  only eligible subject concepts may be emitted as general subjects.

This experiment tests the central proposal directly. It separates the value
of broad mapping from the cost of broad output eligibility.

#### Experiment 2 — Candidate retrieval

On the winning development policy, compare:

- exact alias and lexical retrieval;
- exact dense retrieval; and
- lexical+dense fusion.

Report adequate-target recall at several useful depths, such as 12, 50, and
100, before prompt-budget trimming. Also report latency, memory, source
composition, and repeated-hub frequency.

Keep exact search as the dense baseline. Reopen ANN only if operating measures
show a real need.

#### Experiment 3 — Metadata priors

Compare the selected retriever with and without:

- CFR-part prior;
- parent-agency fallback; and
- global union.

Never intersect the metadata-derived set with global candidates. Report losses
on cross-agency subjects and broad-remit agencies separately.

#### Experiment 4 — Label text

Compare:

- preferred label plus aliases;
- preferred label, aliases, and genuine source scope notes;
- structurally cleaned definitions; and
- the current template-heavy text as a regression baseline.

Do not include generated descriptions in the default. Test them only as a
separate variant if genuine source text remains inadequate.

#### Experiment 5 — Assignment and cardinality

Here, cardinality means the number of labels emitted for one item.

Freeze candidates and compare judge behavior:

- current role-aware prompt;
- stronger evidence and abstention rules; and
- an explicit output-count policy.

Measure whether the judge selects exact or acceptable concepts, avoids merely
related terms, emits the right number of subjects, and abstains when no safe
mapping exists. Add a cross-encoder or trained model only if candidate recall
is adequate and judge ranking remains the measured constraint.

#### Experiment 6 — Product query

Run the winning development configuration through a complete subject-dependent
query, such as the existing PFAS discovery question. Freeze expected,
forbidden, and ambiguous record identifiers and the evidence for each.

Adopt a component only if the complete query improves without weakening exact
evidence, reproducibility, latency, or cost beyond the declared budget.

### Measures and gates

| Level | Required measures | Adoption meaning |
| --- | --- | --- |
| Registry | Adequate-target coverage; exact/close/broader/related/not-represented distribution | Shows whether retrieval has a valid answer to find |
| Candidate | Recall at declared depth by type, role, source, and target grade; latency and memory | Shows whether the judge has a fair opportunity |
| Assignment | Role-aware multi-label precision and recall; unsupported-label rate; type-confusion rate; evidence support; correct abstention; output-count error | Shows whether the semantic decision is trustworthy |
| Product | Query precision and recall; expected and forbidden identifiers; stable counts; explanation coverage | Shows user value |
| Operations | Reproducibility, digests, model calls, cost, latency, peak memory, and failures | Shows whether the result can run and be audited |

Use the structural `--require-adoption-ready` gate on the first MVP holdout.
That approximately 80-assignment tier can expose major failures and support
the bounded MVP decision; it cannot support a broad accuracy claim.

For an accuracy claim, use the powered tier and pre-publication exit rule: the
research estimate was approximately 780 assignments.
Compare with trivial baselines on the same holdout and require improvement
beyond the baseline plus twice its bootstrap standard error, with the
predeclared paired test. Do not retrofit a threshold after seeing holdout
labels.

### Stop rules

- If the target is absent, stop retrieval tuning and evaluate local-concept or
  abstention behavior.
- If candidate recall is poor, do not tune the judge.
- If candidate recall is adequate and assignments remain poor, freeze
  retrieval and investigate ranking, evidence, role, and cardinality.
- If a component score rises but the product query does not improve, reject
  the component for adoption.
- If metadata priors exclude a valid global candidate, reject the hard-filter
  design.
- If two consecutive development changes produce no material gain, re-examine
  the target labels, registry fit, and error categories.
- Do not tune against a final holdout and continue calling it a holdout.
- Do not reopen ANN work without a measured memory or latency constraint.
- Do not induce a replacement vocabulary until recurring, useful,
  not-represented concepts establish the need.
- Do not publish machine attestations as human review.

## Delivery sequence

| Stage | Work | Result | Authority |
| --- | --- | --- | --- |
| 0 — Current MVP | Finish the holdout, attestations, assignment bridge, and local publication gates | Decision-quality measurement and reproducible Rulespec-aligned assignments | Current MVP plan |
| 1 — Registry preparation | Pin source releases; reconcile Federal Register API/PDF concepts; classify resource kinds; build read-only core and module views | Comparable registry configurations without deleting source data | Maintainer approval after MVP-local or an explicit decision entry |
| 2 — Component experiments | Run Experiments 0–5 on development data, then freeze one configuration | One eligible candidate for final evaluation | Experiment strategy and evaluation boundary |
| 3 — One-shot holdout | Evaluate the frozen configuration once | Adopt, reject, or record an inconclusive attempt | Existing holdout exit bar |
| 4 — Product evaluation | Run the subject-dependent discovery query | Evidence of user value or a diagnosed downstream failure | Product decision |
| 5 — Governance | Establish local-concept review, mappings, version updates, and correction flow | Maintainable production vocabulary and audit trail | Separate adoption decision |

## Decisions this draft recommends now

Approve:

- the separation of mapping space from output eligibility;
- typed result layers and separate entity normalization;
- abstention and evidence-backed local concepts;
- the current exact-search baseline;
- soft CFR/agency priors as experiments;
- the staged holdout and product-query gates; and
- preservation of source identities, mappings, and complete relationships.

Defer:

- the exact membership and size of the production subject core;
- deleting FAST, TSCA, or any acquired source data;
- ANN replacement;
- embedding-model replacement;
- cross-encoder or classifier training;
- generated label descriptions;
- automated taxonomy induction;
- specialist-module adoption; and
- public release.

Reject for the current proposal:

- one flat output list mixing subjects, entities, process values, and legal
  locations;
- hard agency or CFR filtering;
- forced nearest-concept assignment;
- source-vocabulary quotas as a permanent substitute for typed eligibility;
- using `toc_subject` as general-subject truth;
- treating the original 35 artifacts as holdout evidence; and
- making architecture decisions from the retracted `0.029` margin or
  effective-dimension reading.

## Risks and open questions

1. **Core coverage:** A smaller core may omit valid subjects. Typed specialist
   modules, local concepts, and abstention reduce the harm but do not prove
   adequate coverage.
2. **Source labels:** Federal Register and CRS assignments reflect their
   indexing purposes. They are strong evidence, not universal product truth.
3. **Notices:** `toc_subject` covers many Notices but answers a different
   question from topical classification.
4. **Review capacity:** The project currently has machine attestation, not
   standing human vocabulary governance. Production promotion needs a named
   owner and review process.
5. **Version discrepancies:** Federal Register API and PDF counts differ.
   Several specialist resources have unresolved freshness, count, or licensing
   questions.
6. **Hierarchy fidelity:** Current storage cannot preserve every multi-parent
   relation and source cycle. A compatibility tree must not erase the source
   graph.
7. **Evaluation scale:** The first MVP holdout can support a bounded decision,
   not a claim of complete federal-domain coverage.
8. **Model drift:** Model, prompt, and embedding changes require new digests
   and cannot reuse an adoption verdict automatically.
9. **Operating cost:** A wider mapping space and larger reranking depth may
   improve recall but increase latency and model cost.
10. **User value:** Better subject metrics may still fail to improve discovery,
    filtering, joining, or aggregation.

## Relationship to current repository documents

This draft complements the existing
[Concept Tagging Architecture Proposal](concept-tagging-architecture-proposal-2026-07-28.md).
It narrows two points:

1. It reclassifies the fused registry instead of deleting it: broad typed
   mapping may remain useful even when broad subject emission is harmful.
2. It separates the long-term architecture from the current MVP sequence:
   retrieval and registry changes remain parked until the existing measurement
   and publication gates are complete.

The [Source and Document Type Matrix](source-document-type-matrix-2026-07-28.md)
defines which rows are documents, containers, entities, observations, or
participation records. The
[Source Vocabulary, Ontology, and Authority Catalog](source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md)
records candidate resources, rights, and source-specific adoption gaps. The
[RefSpec evaluation plan](../plans/implementation-plan.md#7-evaluation-plan)
is the current authority for matching each product question to the failing
stage and changing one variable at a time.

## Research map

- [Parent ANN context](evidence/blind-external-research-recovery-2026-07-28/00-ann-parent-context-before-research-reports.md):
  exact-search decision, source composition, retracted comparison, and
  pre-report boundary.
- [Industry and large-label-space tagging](evidence/blind-external-research-recovery-2026-07-28/01-industry-and-llm-era-large-label-space-tagging.md):
  production taxonomy scale, retrieve-then-judge patterns, and evidence gaps.
- [Extreme multilabel classification](evidence/blind-external-research-recovery-2026-07-28/02-extreme-multilabel-classification.md):
  candidate methods, scale comparisons, distractor effects, and typed
  map-versus-emit reasoning.
- [Taxonomy induction](evidence/blind-external-research-recovery-2026-07-28/03-taxonomy-induction.md):
  corpus-derived vocabularies, generation and mapping, human review, and
  instability.
- [Label text and embedding geometry](evidence/blind-external-research-recovery-2026-07-28/04-label-text-and-embedding-geometry.md):
  corrected geometry interpretation, boilerplate, model choice, hubness, and
  label-text experiments.
- [Controlled-vocabulary scoping](evidence/blind-external-research-recovery-2026-07-28/05-controlled-vocabulary-scoping.md):
  Federal Register coverage corrections, vocabulary roles, CFR and agency
  priors, and the case for typed resource use.
- [Source partitioning and metadata priors](evidence/blind-external-research-recovery-2026-07-28/06-source-partitioning-and-metadata-priors.md):
  evidence against hard partitions and for recall-preserving soft signals.
- [US federal controlled vocabularies](evidence/blind-external-research-recovery-2026-07-28/07-us-federal-controlled-vocabularies.md):
  federal subject, legal, process, entity, and specialist resources.
- [Corpus-driven vocabulary development](evidence/blind-external-research-recovery-2026-07-28/08-corpus-driven-vocabulary-development.md):
  term extraction limits, two-tier governance, review cost, and promotion
  gates.
- [Controlled-vocabulary stop rules and federal inventory](evidence/blind-external-research-recovery-2026-07-28/when-to-abandon-controlled-vocabulary-and-federal-vocabulary-inventory.md):
  reconstructed hybrid recommendation, verified inventory, typed design, and
  holdout requirements.

## Final recommendation

Treat the fused registry under evaluation as a useful library of resources,
not as the product's subject definition.

The next production candidate should combine a governed general-subject core,
typed specialist and entity modules, exact evidence, abstention, and a broad
mapping space whose contents do not automatically become eligible outputs.
This design preserves coverage without forcing every available identifier into
the same semantic role.

Approve the proposal as an evaluation program. Adopt a production registry and
selector only after the current MVP produces an eligible holdout result and
the winning configuration improves a complete product query.
