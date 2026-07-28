<!-- markdownlint-disable MD013 -->

# Concept Tagging Architecture Proposal

> **Status:** Historical research proposal; not adopted by RefSpec
>
> **Date:** 2026-07-28
>
> **Decision gate:** Untouched holdout results and product-level query results
>
> **Research basis:** [Recovered blind external research](evidence/blind-external-research-recovery-2026-07-28/README.md)

## Decision

Use a typed, source-aware hybrid for concept tagging.

Keep controlled concepts as stable identifiers, but stop requiring every
document to choose from one flat registry of 513,236 concepts. Use a small,
governed subject core; separate entities and structured metadata; retain large
vocabularies for optional mapping; and allow abstention or evidence-backed
local concepts.

Approve this reshaped architecture. Reject the 513,236-concept fused registry
as the production classifier.

## Target architecture

| Layer | Role | Initial treatment |
| --- | --- | --- |
| General subjects | Topics users browse, filter, and join across sources | Start with Federal Register and Congressional Research Service concepts—roughly 1,000–3,000 after mapping and review |
| Legal and process metadata | Code of Federal Regulations parts, authority citations, Regulation Identifier Numbers, agencies, document types, stages, and dates | Extract deterministically; do not turn these values into topics |
| Action and genre metadata | Federal Register `toc_subject` values | Store separately, especially for Notices; never use these values as topical gold labels |
| Regulated entities | Chemicals, organizations, places, and industries | Run separate recognition and normalization passes; Toxic Substances Control Act and Chemical Abstracts Service concepts belong here |
| Specialist subjects | Agriculture, medicine, environment, energy, and aerospace | Activate the relevant vocabulary module from document evidence |
| Reference mapping | Broad normalization and crosswalk support | Search FAST here when useful, but never reserve topical slots for it |
| Open candidates | Valid concepts missing from registered vocabularies | Preserve an evidence-backed `LocalConcept`, or abstain |

The [source and document type matrix](source-document-type-matrix-2026-07-28.md)
applies these layers to the evaluated source profiles, candidate source
families, adjacent external systems, and recommended source gaps.

The proposed 1,000–3,000-concept core is a starting hypothesis, not an adoption
claim. Before defining version 1, reconcile concepts from Federal Register
PDFs, the Federal Register API, and local extraction. A governed ceiling of
2,000–8,000 concepts remains reasonable only if measured use and evaluation
justify it.

This proposal informed the
[RefSpec registry and concept-governance model](../spec/refspec.md#12-registry-operations-and-concept-governance)
and applies the
[recovered label-space research](evidence/blind-external-research-recovery-2026-07-28/when-to-abandon-controlled-vocabulary-and-federal-vocabulary-inventory.md#opinionated-label-space-design).

## Assignment flow

1. Accept document text, document type, agency, Code of Federal Regulations
   references, Regulation Identifier Numbers, and other structured metadata.
2. Extract grounded subject phrases and typed entities in separate passes.
3. Select the general subject pool and any relevant specialist pools from the
   document's source and evidence.
4. Retrieve candidates through lexical search, exact dense search, and
   metadata-based ranking signals.
5. Apply metadata signals in this order: Code of Federal Regulations part,
   parent agency, then the global core. Take the union of their results; do not
   use any signal as a hard filter.
6. Retrieve a wider pool, such as 50 or 100 candidates, then rerank it to the
   prompt budget.
7. Ask the semantic judge to assign zero or more concepts. Each assignment must
   include its role and exact supporting evidence.
8. Accept a registered identifier only when the evidence supports that exact
   mapping.
9. Otherwise, abstain or create an evidence-backed local candidate. Never force
   the nearest registered concept.

FAST and the Toxic Substances Control Act vocabulary remain available for
mapping, but they do not receive reserved positions in a fixed top-12 list.
This replaces the fixed source quotas observed in the evaluated
pre-publication implementation.

## Document-specific behavior

- **Rules and Proposed Rules:** Treat official Federal Register topics as
  source-assigned training and evaluation evidence.
- **Notices:** Store `toc_subject` as action or genre metadata. Evaluate
  topical subjects independently.
- **Code of Federal Regulations-linked documents:** Use the CFR List of
  Subjects as ranking evidence, not as automatic assignments.
- **Congressional and legislative material:** Prefer Congressional Research
  Service terms when they fit the evidence.
- **Domain-heavy documents:** Activate specialist modules without excluding
  the general subject core.
- **Public comments:** Keep them outside version 1 unless the product scope
  expands.

## Hierarchy and mappings

Store concept relationships without losing valid parents, cycles, related
links, replacements, or source history:

```text
concept_relations(
  child_id,
  predicate,
  target_id,
  source_vocabulary,
  source_reference,
  validation_status
)
```

Build a separate acyclic view for navigation when a consumer needs a tree.
Keep `broader_id` only as a compatibility value when a concept has exactly one
accepted parent.

The evaluated registry-fusion behavior is not authoritative. It selected the
lexicographically smallest parent, dropped other parents, and broke cycles.
Completing that implementation did not establish the behavior as the target
data model.

Keep cross-vocabulary mappings distinct from hierarchy:

- `exactMatch` means equivalent concepts.
- `closeMatch` means similar concepts that are unsafe to merge.
- `related` means an association, not a parent-child relationship.

## Adoption experiment

Compare four registry configurations:

- **A — Federal Register core:** General Federal Register concepts only.
- **B — Federal Register plus CFR evidence:** Add CFR List of Subjects as
  ranking evidence and metadata-based signals.
- **C — Federal Register plus CFR and CRS:** Add Congressional Research Service
  concepts.
- **D — Full fused registry:** Keep the current large registry as a diagnostic
  comparison, not as the presumed production design.

Within each configuration:

- Compare lexical, dense, and hybrid candidate retrieval.
- Measure boilerplate-heavy and substantive text separately.
- Add a cross-encoder only if candidate recall is adequate but the final
  shortlist remains poor.

The original 35 documents remain development data. They cannot authorize
adoption. Build these untouched evaluation sets:

- A chronological Federal Register holdout containing Rules and Proposed
  Rules.
- An independently labeled, cross-source holdout.
- An entity-focused set with chemicals and Chemical Abstracts Service
  identifiers.
- Product-query cases for CFR targeting, statutory authority, and
  per- and polyfluoroalkyl substance discovery.

Measure each stage separately:

1. **Registry availability:** Does the correct registered concept exist?
2. **Candidate recall:** Does retrieval include it at the chosen `K`?
3. **Final assignment:** Is the identifier, role, and evidence correct?
4. **Abstention:** Does the system reject unsupported mappings and preserve
   valid local concepts?
5. **Type separation:** Does it keep entities separate from subjects?
6. **Product result:** Does the complete query return the records a user needs?

A component wins only when the complete product query improves. Follow the
[RefSpec evaluation plan](../plans/implementation-plan.md#7-evaluation-plan): identify the
failing stage, change one variable, and use the measure that matches that
stage.

## Decisions to make now

- Keep the source data already collected.
- Replace the flat fused topical pool and fixed source quotas.
- Separate subjects, legal metadata, process metadata, action or genre
  metadata, and entities.
- Add Federal Register `toc_subject` as non-topical metadata.
- Preserve hierarchy and mappings without data loss.
- Use exact search until measured latency or memory establishes the need for an
  approximate nearest-neighbor index.
- Defer model training, cross-encoders, and taxonomy induction until evaluation
  identifies the failing stage.
- Do not publish or adopt the design before it passes an untouched holdout and
  the product-level CFR, statutory-authority, and PFAS queries.

## Confidence and remaining uncertainty

Confidence is high in the separation of subjects, entities, and structured
metadata; the lossless relationship model; and the stage-specific evaluation
plan.

Confidence is medium in the size and composition of the general subject core.
The untouched holdouts and product queries must decide that question.
