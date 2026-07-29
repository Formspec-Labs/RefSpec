<!-- markdownlint-disable MD013 -->

# RefSpec and Rulespec vocabulary gap closure plan

> **Status:** Approved cross-repository prerequisite
>
> **Date:** 2026-07-29
>
> **RefSpec delivery plan:** [RefSpec implementation plan](implementation-plan.md)
>
> **Rulespec companion plan:** [Rulespec concept vocabulary carriage and evolution](https://github.com/Formspec-Labs/rulespec/blob/main/thoughts/plans/2026-07-29-rkaf-concept-vocabulary-carriage-and-evolution.md)

## Result

Close the vocabulary defects that could reproduce the failed fused-registry
experiment before RefSpec implements or releases typed enrichment.

The work preserves the current ownership boundary:

- Rulespec owns portable concept meaning, SKOS carriage, semantic lifecycle,
  assertions, and reusable validation.
- RefSpec owns imports, indexed representations, facet and output policy,
  adequacy evaluation, deployment binding, and publication behavior.
- A downstream implementation may prove these requirements, but it does not
  become their source of truth.

This plan closes specification and conformance gaps first, then refactors the
reusable Spicy Regs implementation behind the locked interfaces. The broader
RefSpec implementation plan still governs product delivery beyond vocabulary
closure.

## 1. Failure lessons carried forward

The plan treats these locally reproduced failures as requirements:

1. **A flat registry erased meaning.** The old registry used one field for both
   semantic facet and source-vocabulary identity. It made only 936 of 513,236
   concepts reachable.
2. **The importer silently discarded hierarchy.** Source distributions
   contained hierarchy, but the fused index carried no broader edges.
3. **Registry coverage was mistaken for model quality.** Only 5 of 35
   development items had adequate surfaced targets. Retrieval could not recover
   concepts that the selected releases did not represent.
4. **Same labels invited false equivalence.** Concepts from different
   authorities remained distinct even when their labels matched.
5. **Nearest-neighbor output forced plausible errors.** A closed output path
   turned missing vocabulary coverage into confident but wrong assignments.
6. **The evaluation boundary leaked.** Concepts, aliases, artifacts, and
   near-duplicates crossed development and holdout partitions.
7. **Candidate access became accidental publication authority.** Mapping,
   diagnostic, and decoy resources could influence retrieval without being
   suitable for accepted output.
8. **Version and configuration drift weakened results.** An evaluated setup
   could differ from the setup later deployed.

## 2. Locked design decisions

### 2.1 Preserve vocabulary structure

- Keep every authority-issued concept IRI distinct. Equal normalized labels
  never establish identity or `skos:exactMatch`.
- Keep `rkaf:schemeFacet` separate from source-vocabulary identity and
  provenance.
- Treat `skos:broader`, `skos:narrower`, and `skos:related` as in-scheme
  concept structure.
- Treat `skos:exactMatch`, `skos:closeMatch`, `skos:broadMatch`,
  `skos:narrowMatch`, and `skos:relatedMatch` as reviewed cross-scheme mapping
  assertions.
- Never interpret SKOS hierarchy as logical subclassing, a legal conclusion,
  an automatic assignment, or output authorization.

### 2.2 Use native SKOS language maps

Rulespec will use SKOS Core RDF literals for project-authored labels,
definitions, and notes. It will not introduce SKOS-XL label resources in this
work.

- `skos:prefLabel` is a JSON-LD language map with exactly one string for each
  BCP 47 language key.
- `skos:altLabel`, `skos:hiddenLabel`, definitions, examples, and every
  supported SKOS note property are language maps with one-or-many strings for
  each language key.
- Rulespec-authored text rejects untagged values and the JSON-LD `@none` key.
  Use `und` only when the language is genuinely unknown.
- BCP 47 tags carry script subtags such as `zh-Hant`; no parallel script field
  is added.
- `skos:notation` contains one-or-more JSON-LD typed-literal objects. Every
  object has `@value` and an absolute datatype IRI in `@type`.
- Project-authored concepts may name multiple direct broader concepts.

External source distributions remain canonical for their complete native
content. The Rulespec concept shapes support portable authored concepts; they
do not replace a source vocabulary's native release.

### 2.3 Keep the enrichment path open

Every attempted facet and assignment role may produce:

- an accepted controlled-concept assignment;
- an accepted language-tagged open label;
- a review candidate;
- a local concept proposal;
- an explicit abstention;
- a rejection; or
- an unresolved result.

Zero accepted assignments is valid. Rank, similarity, or machine agreement
never creates acceptance, attestation, adoption, or publication authority.

### 2.4 Authorize use by tuple

RefSpec `OutputProfile` policy will authorize complete, non-cross-product
rows:

- `releasePermissions`: facet, assignment role, reference-resource release,
  registry import snapshot, required import features, candidate use, and
  accepted-output use;
- `mappingPermissions`: facet, assignment role, mapping import snapshot,
  source and target releases, mapping relation, direction, candidate use, and
  accepted-output use; and
- `openLabelPermissions`: facet, assignment role, open-label mode, candidate
  use, and accepted-output use.

An accepted result must match one complete row. Values from separate rows
cannot be combined. `acceptedOutputUse=true` requires
`candidateUse=true`. Candidate authorization never implies output
authorization. Mapping-only, diagnostic, and decoy releases default to
candidate use only.

### 2.5 Evaluate vocabulary adequacy before retrieval

Each sealed gold item records whether the frozen, output-authorized releases
contain an adequate target. The relationship grade is one of:

- `exact`;
- `close`;
- `targetBroaderThanGold`;
- `targetNarrowerThanGold`;
- `related`;
- `notRepresented`; or
- `wrong`.

`notRepresented` routes to open label, proposal, or abstention. It is not a
candidate-retrieval miss.

## 3. Required interface changes

### 3.1 Rulespec

The [Rulespec companion plan](https://github.com/Formspec-Labs/rulespec/blob/main/thoughts/plans/2026-07-29-rkaf-concept-vocabulary-carriage-and-evolution.md)
defines the upstream implementation. It must deliver:

- multilingual preferred, alternate, and hidden labels on
  `rkaf:ConceptScheme`, `rkaf:RegisteredConcept`, and `rkaf:LocalConcept`;
- multilingual definitions, examples, generic notes, scope notes, editorial
  notes, history notes, and change notes;
- notation and multiple direct broader concepts;
- one preferred label per language and disjoint preferred, alternate, and
  hidden label values;
- required `rkaf:registeredAt` on every `rkaf:RegisteredConcept`;
- `rkaf:conceptLifecycleOperation`,
  `rkaf:predecessorConcepts`, `rkaf:successorConcepts`,
  `rkaf:predecessorConceptRelease`, and
  `rkaf:successorConceptRelease` for deprecation, withdrawal, replacement,
  split, merge, promotion, and demotion, with exact complete-membership pins
  and the required 1-to-0, 1-to-1, 1-to-many, and many-to-1 cardinalities;
- retirement of standalone promotion and demotion lifecycle-event kinds;
- a portable `rkaf:openLabel` predicate with required
  `rkaf:openLabelFacet` and `rkaf:openLabelRole`; and
- a complete `rkaf:ConceptResolutionResult` with
  `rkaf:resolutionMethod`, `rkaf:cacheStatus`, `rkaf:usageCeiling`, and a
  conditional `rkaf:mappingAssertion` for mapping-based methods.

Rulespec must update normative prose before its CUE source and generated
artifacts. The source, context, vocabulary table, generated targets, positive
and negative fixtures, behavior where applicable, conformance report, and
changelog must agree.

### 3.2 RefSpec import fidelity

Every controlled-resource import will produce an immutable
`RegistryImportCoverageReport`. For each source distribution and imported
view, it records:

- exact source and destination release identifiers and digests;
- transformation and importer versions;
- source-observed, parsed, indexed, excluded, and failed counts for members,
  preferred, alternate, and hidden labels, language tags including script
  subtags, notation,
  definitions and notes, hierarchy, mappings, status, replacements,
  identifiers, and scheme membership;
- stage-specific occurrence digests for each required feature;
- explicit exclusions with a reason, authority, and review state; and
- the source, imported-store, and built-index stages separately.

A required feature mismatch without an approved exclusion fails the import.
Successful parsing alone cannot pass import fidelity.

Each searchable literal also produces an immutable
`IndexedVocabularyExpression`
record with:

- exact release, import snapshot, distribution, and member identifier;
- source predicate or path, original literal, and exactly one BCP 47 language
  tag, including any script subtag, or absolute datatype IRI;
- normalization-policy identifier, version, and digest;
- normalized and indexed text plus their digests;
- index snapshot and indexed-representation version; and
- generating activity and run receipt.

This record supports reproducible search and alias-leakage checks. It does not
become a semantic concept or mapping.

Conflicting official publications produce a
`RegistryReconciliationReport` naming the exact inputs, differences, mappings,
precedence, unresolved items, attestations, and outcome. An unresolved report
cannot authorize a synthesized union.

A `RegistryDeploymentDecision` binds an environment to one exact imported
release, coverage report, reconciliation result, output profile, and set of
validated Rulespec governance references. Failed coverage or unresolved
reconciliation cannot be selected. Rollback appends a new decision; it does
not rewrite the selected import.

### 3.3 RefSpec facets and output policy

An `EnrichmentProfile` will publish these twelve stable facet IRIs:

`urn:ref:facet:general-subject`,
`urn:ref:facet:specialist-subject`, `urn:ref:facet:entity`,
`urn:ref:facet:legal-location`,
`urn:ref:facet:industry-classification`,
`urn:ref:facet:affected-population`, `urn:ref:facet:genre`,
`urn:ref:facet:regulatory-action`,
`urn:ref:facet:administrative-process-stage`,
`urn:ref:facet:code-list-value`, `urn:ref:facet:ontology-class`, and
`urn:ref:facet:observation-measure`.

For each facet it declares:

- a definition, inclusion cues, and exclusions;
- compatible resource routes;
- permitted assignment-role predicates;
- positive and wrong-facet fixtures.

The profile does not assert global OWL disjointness.

`OutputProfile` will carry the complete permission rows from Section 2.4.
Acceptance validation will reject:

- an unregistered release;
- a release with incomplete membership for a controlled assignment;
- a wrong-facet scheme;
- an unauthorized assignment role;
- a mapping-only or diagnostic release without output permission; and
- a mapping relation used as assignment or inference authority.

### 3.4 RefSpec evaluation and deployment binding

Promote the following evaluation and deployment records into the normative
RefSpec model:

- `SealedGoldManifest`;
- `EnrichmentConfiguration`;
- `EnrichmentEvaluationResult`; and
- `EnrichmentDeploymentDecision`.

`EnrichmentConfiguration` identifies and digests every input that can change
behavior: source corpus, reference releases, mapping releases, candidate
channels, indexed representations, fusion and truncation logic, model and
provider, prompts, acceptance policy, output profile, budgets, and software
revision.

`SealedGoldManifest` records:

- the exact artifact or fragment under review;
- facet and assignment role;
- adequate-target presence and relationship grade;
- acceptable and forbidden targets;
- adjudicators and independent resolution state;
- source identity, concept, exact-match cluster, every current and deprecated
  alias, near-duplicate cluster, artifact digest, and text-digest partition
  keys; and
- its own content digest and sealing time.

Two independent adjudicators are required. Disagreement requires a third
independent decision or exclusion. Tagger output cannot seed the manifest.
Only `exact` and reviewed `close` targets are adequate by default.

`EnrichmentEvaluationResult` binds one configuration digest to one sealed
manifest digest and reports:

- registry and adequate-target coverage;
- full-universe gold rank;
- pre- and post-truncation Recall@K;
- strict relevance and relationship-grade results;
- open-label, proposal, and abstention behavior;
- wrong-facet and unauthorized-output errors;
- reviewer agreement and unresolved cases; and
- provider, latency, cost, and behavior-drift observations.

`EnrichmentDeploymentDecision` identifies the environment, exact
configuration/result pair, output profile, selection state, effective and
recorded times, predecessor, reason, and applicable Rulespec authorization
records. Any configuration mismatch requires a new evaluation.

## 4. Execution sequence and gates

### Phase A — Rulespec semantic prerequisites

1. Land the companion design record.
2. Implement complete SKOS carriage and fixtures.
3. Implement concept evolution and fixtures.
4. Implement the open-label predicate and RefSpec profile rules.
5. Regenerate every derived target and run the complete Rulespec suite.
6. Prepare the local `0.2.0-pre.9` metadata, digest, and self-certification.

**Gate A:** Normative prose, CUE, JSON-LD context, JSON Schema, Rust,
TypeScript, SHACL, OpenAPI, vocabulary audit, fixtures, and conformance report
agree. The full Rulespec `make test` gate passes.

### Phase B — RefSpec normative controls

1. Add import-feature reconciliation and indexed-label lineage.
2. Publish the facet vocabulary and compatibility matrix.
3. Add candidate/output authorization tuples.
4. Add adequacy-first evaluation and immutable configuration/result records.
5. Complete the open-label application-profile binding.
6. Pin the exact verified Rulespec revision, constraint digest, and profiles.

**Gate B:** Every new requirement has an identifier, one canonical owner,
positive and negative examples, a verification method, and a trace to the
implementation plan. The profile contains no local copy of a Rulespec type or
validator.

### Phase C — REF JSON Binding and reference-runtime migration

Add REF JSON Binding 1.0 JSON Schema 2020-12 modules, valid and invalid
fixtures, canonical payload digests, and a requirement-to-test manifest for
all ten closure records: `EnrichmentProfile`, `OutputProfile`,
`RegistryImportCoverageReport`, `IndexedVocabularyExpression`,
`RegistryReconciliationReport`, `RegistryDeploymentDecision`,
`SealedGoldManifest`, `EnrichmentConfiguration`,
`EnrichmentEvaluationResult`, and `EnrichmentDeploymentDecision`. Then
refactor the reusable Spicy Regs work behind those interfaces.

Replace flat vocabulary storage with:

- `concept_labels`, one row per language-preserving label expression;
- `concept_relations`, one row per hierarchy relation; and
- `concept_event_participants`, one row per predecessor or successor role.

Retire production authority for `broader_id`, `replaced_by`, ASCII-only
normalization, label-derived concept identifiers, and the fused registry.
Temporary readers may migrate those records but cannot emit conforming output.
Keep the original 35 adjudicated items permanently development-only.

**Gate C:** The focused tests prove:

- hierarchy loss fails import reconciliation;
- multilingual labels and multiple broader parents round-trip;
- equal labels in different schemes retain different concept IRIs;
- cross-scheme mappings do not create identity or hierarchy;
- every indexed alias resolves to exact source lineage;
- mapping-only and wrong-facet candidates cannot enter accepted output;
- `notRepresented` cases do not count as retrieval misses;
- holdout drawing rejects shared concepts, aliases, near-duplicates, and
  artifact digests; and
- evaluated and deployed configuration digests match exactly.

### Phase D — Closure verification

1. Record the verified Rulespec revision and digests in RefSpec.
2. Run the combined RefSpec/Rulespec profile checks.
3. Update the RefSpec requirement trace and known-limitations statement.
4. Verify the deployed configuration digest in the passing evaluation result.
5. Record baseline failures separately from regressions introduced here.

**Gate D:** A clean consumer checkout resolves the exact pinned Rulespec
artifacts and reproduces the combined result. Local-only or stale pins fail.

## 5. Change and delivery boundaries

Keep changes separable by owner and rollback story:

1. RefSpec master plan and links.
2. Rulespec companion plan.
3. Rulespec SKOS carriage.
4. Rulespec concept evolution.
5. Rulespec open-label profile.
6. Rulespec conformance and release metadata.
7. RefSpec normative import, facet, and evaluation requirements.
8. Spicy Regs import-fidelity regressions.
9. Spicy Regs adequacy and authorization regressions.
10. RefSpec Rulespec pin and combined verification.

Do not mix unrelated worktree changes into these boundaries. A local commit,
remote push, tag, package release, RefSpec publication, and parent-repository
gitlink update are separate actions.

## 6. Acceptance matrix

| Failure mode | Required proof |
| --- | --- |
| Hierarchy silently dropped | Source/import/index edge counts and digests reconcile, or an approved exclusion names the difference |
| Multilingual meaning flattened | BCP 47 label and note fixtures preserve language and script through every Rulespec target |
| Polyhierarchy rejected | A concept with two broader parents validates and round-trips |
| Same label fused across schemes | Two equal labels keep distinct IRIs; no mapping appears without a reviewed assertion |
| Mapping treated as hierarchy | Cross-scheme `broadMatch` never materializes in-scheme `broader` |
| Missing target blamed on retrieval | `notRepresented` is reported before Recall@K and excluded from reachable-target recall |
| Nearest candidate forced into output | No-fit fixture produces open label, proposal, or abstention |
| Candidate release published accidentally | Candidate-only authorization fails accepted-output validation |
| Wrong semantic facet accepted | Scheme/facet/role tuple validation rejects the assignment |
| Alias leaks into holdout | Partition audit rejects shared normalized aliases and their concept IDs |
| Evaluated setup drifts before deployment | Deployment fails when configuration digests differ |
| Machine agreement becomes review | Output remains provisional without the required independent Rulespec attestation and local adoption |

## 7. Explicit exclusions

This plan does not:

- create a universal closed facet taxonomy in Rulespec;
- fuse external vocabularies into one canonical subject scheme;
- infer `owl:sameAs` or `skos:exactMatch` from labels;
- introduce SKOS-XL;
- treat an approximate nearest-neighbor index as canonical;
- choose production storage, vector, graph, or review-service vendors beyond
  the reference-runtime interfaces required here;
- publish, tag, push, or deploy any repository; or
- claim typed enrichment is ready before all four gates pass.

## 8. Definition of done

The gap-closure program is complete only when:

1. Rulespec carries project-authored vocabulary content without losing
   language, script, notes, notation, or polyhierarchy.
2. Rulespec records concept deprecation, withdrawal, replacement, split,
   merge, promotion, and demotion with exact release-qualified predecessor and
   successor identity.
3. RefSpec proves which vocabulary features survived every import and indexed
   representation.
4. RefSpec authorizes candidates and accepted output independently by facet,
   role, and exact release.
5. Evaluation distinguishes missing vocabulary coverage from retrieval and
   adjudication failures.
6. The deployed enrichment configuration exactly matches the passing
   evaluation.
7. Failure-derived regression tests pass against the exact pinned Rulespec
   revision.
8. The broader RefSpec implementation plan records these gates as
   prerequisites for typed enrichment.
