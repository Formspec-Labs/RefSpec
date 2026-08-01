<!-- markdownlint-disable MD013 -->

# Vocabulary management and lookup separation baseline

> **Status:** Implemented baseline and closure-verified locally; unpublished
>
> **Date:** 2026-07-29
>
> **Current execution roadmap:** [Managed vocabulary experiment roadmap](managed-vocabulary-experiment-roadmap.md)
>
> **Historical conceptual plan:** [Early RefSpec implementation plan](implementation-plan.md)
>
> **Vocabulary prerequisite:** [RefSpec and Rulespec vocabulary gap closure plan](vocabulary-gap-closure-plan.md)
>
> **Semantic dependency:** [RefSpec Rulespec application profile](../profiles/rulespec-application-profile.md)
>
> **Supersession notice (2026-07-31):** This document preserves the locally
> verified implementation baseline. The
> [product-boundary and atlas reconciliation plan](2026-07-31-refspec-product-boundary-and-atlas-reconciliation-plan.md)
> supersedes its ownership and promotion directions. RefSpec now owns managed
> vocabulary releases and static atlas publication; Rulespec Extrapolator owns
> derived assertions and accepted-output decisions; SpicySearch owns lookup,
> indexes, and ranking.

**Execution checkpoint:** All five iterations and the fifteen acceptance
criteria have executable local evidence. RefSpec owns the managed-release and
static-atlas publication paths. Product-local file readers consume those
immutable outputs; the historical accepted-output and lookup ownership below is
superseded. The Rulespec dependency remains local and unpublished. No remote
release or production deployment is authorized.

## Local closure record

Closure was verified on 29 July 2026:

- the RefSpec model generates 23 artifacts idempotently;
- REF JSON Binding accepts 5 valid fixtures and rejects 90 invalid fixtures
  with no failures; two raw parser inputs bring the embedded fixture count to
  97;
- the RefSpec package suite passes 195 tests with 8 explicit skips;
- the fresh installed wheel contains 16 byte-matching modules, 19 schemas, the
  exact Rulespec dependency, and 98 conformance assets; its installed tests
  pass 37 tests and its no-argument validator runs the full embedded fixture
  suite;
- the cross-repository gate finds all 45 pinned Rulespec inputs and verifies
  the immutable closure pin;
- the full Rulespec gate passes 497 conformance fixtures with no target
  divergence, and the Rulespec working tree remains clean at
  `2c66a85daab30a4869db08d21cea13cfc865b3a0`;
- the applicable full Spicy Regs suite passes 2,644 tests, with 20 documented
  skips, 4 deselections, and 2 expected failures; and
- the explicitly networked Federal Register regression acquires the exact
  source, builds and opens the selected development release, and rolls back to
  the exact prior empty state.

The real source is
`sha256:d5e013336d4179790e8d6574d4dc9d8cfcb10ce76af202ff4db068617eb8fd30`.
It produces release
`sha256:cd2625d687ec56a7026fdd71c172719943d4b026d3d1279b9adaa2bfa9c57e63`
with 629 concepts, 1,553 normalized labels, 1,477 relations, 2,213 indexed
expressions, and 648 Rulespec graph nodes. Rollback restores state
`sha256:1ec7b21cbc59309b4607d38bc5f1eb9d0c5cb6e048c9c8a864bbe0ba2a039e01`.
Native source bytes and built indexes remain outside Git.

The Federal Register source contains no multilingual labels, mappings,
concept lifecycle events, or replacements. Its coverage report records those
features as observed zero instead of inventing content. The pinned Rulespec
positive and negative corpus and RefSpec normalized-row round trips separately
prove multilingual labels including `zh-Hant`, typed notation, all supported
notes, multiple parents, mappings, and lifecycle participants. Together these
tests prove the interface supports every required feature while the real
adapter preserves every feature its source actually supplies.

Vocabulary licensing uncertainty is recorded as accepted project risk and
does not limit acquisition, storage, indexing, model use, display, retention,
or redistribution in this playground. The `RightsAssessment` preserves the
evidence, attribution, assumption, and residual risk and does not claim legal
clearance. Access, privacy, security, quality, and production-release controls
remain independent.

## Historical result at local closure

At the 29 July closure, the implementation made RefSpec the source of truth for
the vocabulary releases that REF imported, normalized, reconciled, approved,
published, evaluated, deployed, and retired. It kept Spicy Regs as a read-only
consumer that built lookup indexes, retrieved and ranked candidates, and tested
the system against real regulatory work. The supersession notice above replaces
those ownership assignments while retaining this evidence.

This boundary does not make RefSpec the original authority for an external
vocabulary. A publisher's native distribution remains authoritative for what
that publisher released. RefSpec becomes authoritative for what REF received,
how REF preserved it, which exact content REF selected, and which managed
release a downstream system may use.

Rulespec continues to define portable semantic meaning and conformance.
RefSpec defines the operational records and behavior required to manage those
semantics. Spicy Regs proves that the combined specifications work in a useful
lookup product.

## How work proceeds after closure

This baseline fixes the ownership, identity, losslessness, and candidate-output
boundaries. The
[managed vocabulary experiment roadmap](managed-vocabulary-experiment-roadmap.md)
now directs the work through two lanes:

- the **experiment lane** runs ambitious, development-only lookup experiments
  with a small generated run manifest and focused checks; and
- the **release and adoption lane** applies the full RefSpec and Rulespec
  records, conformance suites, and release evidence when a result will become
  stable or support use beyond machine-qualified `searchOnly` discovery.

The experiment lane may vary retrieval, ranking, models, prompts, indexes, and
product interactions without changing RefSpec or Rulespec. A reproduced
semantic, ownership, identity, or preservation failure returns to the
appropriate specification. The release and adoption lane never converts a
research candidate into accepted output without Rulespec Extrapolator selection
and the applicable product evaluation. Two machine validators with distinct
actors, independence groups, providers, provider model IDs, and responses plus
deterministic checks can qualify `searchOnly`; human feedback is optional later
input.

## 1. Ownership boundary

| Owner | Owns | Does not own |
| --- | --- | --- |
| Native vocabulary publisher | Canonical source distributions, publisher identifiers, and publisher release history | REF import decisions, REF deployment, or Spicy lookup behavior |
| Rulespec Core | Reusable concept, scheme, mapping, release, lifecycle, assertion, attestation, adoption, provenance, and evidence semantics | RefSpec acquisition workflow, managed vocabulary content, or lookup ranking |
| RefSpec | Source catalog, capture and verification, non-lossy import, normalization policy, coverage accounting, reconciliation, managed release assembly, crosswalk evidence, and static atlas publication | Duplicate Rulespec semantic types, source-publisher authority, document extraction, accepted-output decisions, or ranking algorithms |
| SpicyRegs | Regulatory document capture, source observations, document identity, evidence addresses, and a product-local diagnostic file reader | Managed vocabulary authority, derived accepted-output decisions, or search ranking |
| Rulespec Extrapolator | Evidence-bound derived assertions, deterministic selection, and accepted-output decisions | Vocabulary acquisition, source-document authority, or search serving |
| SpicySearch | Query processing, disposable indexes, retrieval, ranking, explanations, coverage, and search feedback | Source-document authority, managed vocabulary publication, or accepted-output decisions |

The short form is:

- RefSpec answers: **What is in this managed vocabulary release, where did it
  come from, and what static atlas was published from it?**
- Rulespec Extrapolator answers: **Which evidence-bound derived assertions were
  selected for the declared use?**
- SpicySearch answers: **Which pinned release facts best answer this query, and
  why did each result rank where it did?**

## 2. Historical lookup boundary

This section records the pre-split interface that the local closure exercised.
The current file boundary and product owners are stated in section 1.

RefSpec and Spicy Regs meet at immutable, content-digested interfaces.

RefSpec owns:

- the exact release and import snapshot;
- the language-preserving expression corpus eligible for indexing;
- source properties and source paths for each expression;
- hierarchy, mapping, lifecycle, status, replacement, identifier, and
  membership preservation;
- normalization policies and derived-text digests;
- facet, role, candidate-use, and accepted-output permissions;
- coverage and reconciliation outcomes;
- the selected registry deployment; and
- the configuration, evaluation, and deployment chain that authorizes use.

Spicy Regs owns:

- the concrete lexical, sparse, dense, hybrid, or approximate-nearest-neighbor
  index;
- tokenization and retrieval-time query processing;
- candidate channels and fusion;
- ranking and reranking;
- model, prompt, and provider experiments;
- document-to-query extraction;
- assignment suggestions and product interaction; and
- lookup-quality, latency, cost, and workflow measurements.

An exact member lookup by identifier is a RefSpec release-access function.
Semantic search and ranking are Spicy Regs functions. RefSpec may ship a small
exact reference implementation to prove release behavior, but it must not
become a competing search product.

Spicy Regs may propose corrections or new concepts. It cannot change a managed
release in place. A proposal returns to the RefSpec review and release process,
and any portable semantic change uses the applicable Rulespec records.

## 3. RefSpec needs an executable schema stack

RefSpec should have schemas and generated implementation artifacts comparable
to Rulespec's, limited to REF-owned records.

### 3.1 Layers

1. **Normative Markdown**
   defines meaning, ownership, required behavior, failure behavior, and the
   requirements that implementations must satisfy.
2. **One machine-readable structural source**
   defines REF-owned record fields, cardinalities, closed objects, identifier
   formats, and local conditions. Use CUE unless implementation experience
   proves that another source serves this job better.
3. **Generated JSON Schema 2020-12**
   validates serialized REF records. Generated targets must never become an
   independent source of meaning.
4. **Generated implementation types**
   begin with Python because both RefSpec's validator and Spicy Regs use it.
   Add another language only when a real consumer needs it.
5. **A behavior validator**
   enforces rules that one record schema cannot prove, including complete
   permission-row matching, coverage accounting, reconciliation authority,
   leakage prevention, digest chains, and deployment eligibility.
6. **Positive and negative fixtures**
   prove every normative requirement and every known failure mode.
7. **A requirement-to-test manifest**
   links each requirement to its structural, behavioral, cross-repository, and
   reference-runtime tests.
8. **A versioned reference package and command-line gate**
   let consumers validate records, compute canonical digests, assemble
   releases, and invoke the exact pinned Rulespec validator.

### 3.2 Do not duplicate Rulespec

RefSpec schemas contain references to Rulespec identifiers, versions, graph
digests, records, and validation results. They do not copy the shapes of
Rulespec concepts, schemes, mappings, releases, assertions, attestations,
adoptions, artifacts, source fragments, or evidence bindings.

The combined gate must:

1. validate REF-owned records with the RefSpec validator;
2. validate Rulespec-owned records with the exact pinned Rulespec validator;
3. verify every cross-repository identifier and digest reference;
4. verify that both results cover the same intended release graph; and
5. report REF, Rulespec, and cross-boundary failures separately.

## 4. Current baseline

The work since Spicy Regs `origin/main` already contains much of the reusable
proof:

- the branch is 125 commits ahead of `origin/main`;
- the committed delta at `e1f9a1b83db76d7814fee41e4a25e8607853d058`
  changes 435 files with 204,804 insertions and 2,501
  deletions;
- `src/spicy_regs/enrichment/reference_runtime.py` implements canonical
  payload digests, vocabulary coverage, indexed expressions, reconciliation,
  complete permission rows, enrichment configuration, evaluation, and
  deployment records;
- `src/spicy_regs/evaluation_boundary.py` and its tools implement gold sealing,
  holdout drawing, and leakage controls;
- `tools/fuse_concept_registries.py` contains useful source-specific parsing
  knowledge, but its flat fused output is a failed authority model;
- the RefSpec repository already has REF JSON Binding 1.0 with 19 generated
  schema modules, 5 valid fixtures, 90 invalid fixtures, a behavior
  validator, and a requirement-to-test manifest; and
- Spicy Regs already consumes normalized vocabulary releases in its document
  pipeline.

This was not a greenfield rewrite. The migration retained tested generic
logic, removed duplicate implementations, and discarded the flat storage and
authority assumptions that caused the failed registry experiment.

The implementation resolves the former mixed Rulespec prose pins through one
machine-readable dependency manifest. It distinguishes the tested source
revision from the later evidence revision and keeps the candidate explicitly
local and unpublished. The reusable REF record, validation, release,
evaluation, deployment, and accepted-output implementation now lives in the
versioned RefSpec package. Spicy Regs retains only compatibility imports and
its read-only lookup and product-evaluation interfaces.

## 5. What moved from Spicy Regs to RefSpec

Code moved only after the normative RefSpec and Rulespec meaning stabilized.

### 5.1 Moved and generalized

- canonical JSON serialization and content-digest functions;
- REF-owned record models and record parsing;
- complete output-permission row validation;
- registry import coverage accounting;
- indexed vocabulary expression construction;
- registry reconciliation checks;
- registry and enrichment deployment checks;
- sealed-gold and general partition-leakage controls;
- enrichment configuration and evaluation validation;
- generic source acquisition, checksum verification, import receipts, and
  replay support;
- source parsers that preserve labels, languages, notation, notes, hierarchy,
  mappings, status, replacements, identifiers, and membership;
- normalized vocabulary storage and export interfaces; and
- a release builder that emits immutable manifests and exact dependency
  digests.

### 5.2 Keep in Spicy Regs

- regulatory-document parsing and document-specific query construction;
- `rkaf_projection.py` and product-facing document output;
- sparse, dense, hybrid, and approximate-nearest-neighbor retrieval;
- candidate-channel logic and ranking experiments;
- model, prompt, provider, and budget experiments;
- product-specific review screens and workflows;
- the original 35 development-only items and Spicy-specific holdout
  administration; and
- lookup latency, cost, ranking, and user-value evaluation.

### 5.3 Retire after parity

- flat fused-registry output as a production authority;
- label-derived concept identifiers;
- ASCII-only normalization;
- one `broader_id` field;
- one `replaced_by` field;
- storage that collapses vocabulary identity into semantic facet;
- mutable releases or indexes without an immutable manifest;
- duplicate REF validators in both repositories; and
- code paths that let candidate availability imply accepted-output permission.

Legacy readers may migrate old local data. They must not emit legacy shapes as
conforming RefSpec releases.

## 6. Target RefSpec components

### 6.1 Repository structure

The exact names may change during implementation, but the responsibilities
must remain visible:

```text
RefSpec/
  spec/                         normative RefSpec text
  profiles/                     Rulespec and enrichment application profiles
  model/                        authoritative REF-owned structural source
  bindings/json/1.0/            generated JSON schemas and fixtures
  src/refspec/                  reference Python package
    canonical.py
    records.py
    validate.py
    registry/
      catalog.py
      acquire.py
      importers/
      coverage.py
      reconcile.py
      release.py
      deploy.py
  tests/                        unit, conformance, and cross-repository tests
  plans/                        delivery and migration plans
```

Large native distributions, materialized registries, embeddings, and lookup
indexes do not belong in Git. Store them in content-addressed artifact storage.
Keep their immutable manifests, source references, rights information,
digests, validation results, and release decisions in RefSpec records.

For the vocabulary playground, licensing uncertainty is recorded but is not a
use blocker. This project adopts a `RightsAssessment` that permits acquisition,
storage, indexing, model use, display, retention, and redistribution despite
incomplete license evidence. The assessment states the assumption and residual
risk, preserves attribution and source evidence, and avoids claiming legal
clearance. Native source bytes still remain outside Git. Access, privacy,
security, quality, and release-governance controls remain independent and may
still block a use; licensing uncertainty alone does not.

### 6.2 Normalized vocabulary interfaces

The reference storage model must preserve repeated and language-specific
values:

- `concept_labels`: one row per concept, label property, language, and value;
- `concept_relations`: one row per hierarchy or associative relation;
- `concept_event_participants`: one row per lifecycle event, concept, and
  predecessor or successor role;
- typed notation rows that retain datatype IRIs;
- note rows that retain the SKOS property and language;
- mapping rows that retain source release, target release, relation, direction,
  evidence, and review state; and
- exact release-membership rows.

The serialized RefSpec records need not expose a database design. They must
preserve enough information for conforming stores and exports to round-trip
the same meaning.

### 6.3 Managed-release path

| Question | RefSpec answer |
| --- | --- |
| What goes in? | Immutable native distributions, source metadata, rights information, exact Rulespec Core pins, import policy, and optional closed crosswalk evidence with machine-validation receipts |
| What happens? | Verify, parse without silent loss, normalize without collapsing identity, account for coverage, reconcile conflicts, validate the release, and qualify `searchOnly` mappings through deterministic checks and two independent machine validators |
| What comes out? | A managed vocabulary release, expression corpus, release manifest, validation reports, and the two-file atlas distribution: `atlas-manifest.json` and `atlas.nq` |
| How do we check it? | Positive and negative fixtures, source-to-release count and digest reconciliation, round-trip tests, exact Rulespec validation, atlas reproduction, and product-local file-reader gates |

## 7. Completed delivery sequence

### Iteration 1 — Lock the boundary

- Add normative ownership and lookup-boundary requirements to RefSpec.
- Confirm that every semantic term belongs either to Rulespec or to an external
  standard.
- Define the RefSpec records required for cataloging, acquisition, import,
  reconciliation, release, deployment, and rollback.
- Resolve the stale Rulespec pin references across RefSpec.
- Record every known failure as a normative rule and named negative fixture.

**Gate:** no field, invariant, or failure behavior has disputed ownership.

### Iteration 2 — Establish one RefSpec implementation

- Select the authoritative machine-readable source for REF-owned structures.
- Generate the existing JSON schemas from it without changing accepted
  behavior.
- Generate Python types from the same source.
- Move canonical digest and generic record logic from Spicy Regs into the
  RefSpec package;
- merge RefSpec's binding validator and the reusable Spicy Regs runtime behind
  one public validation interface; and
- prove generated-file idempotence and fixture parity.

**Gate:** a clean RefSpec checkout generates the same artifacts, passes every
current fixture, and exposes one reusable package.

### Iteration 3 — Build one real managed vocabulary release

Choose one bounded source with useful labels and hierarchy, such as the Federal
Register Thesaurus or a Congressional Research Service vocabulary. Do not
start with the 513,236-row legacy fusion.

- capture and verify one native distribution;
- import multilingual labels, notation, notes, hierarchy, mappings, lifecycle
  state, identifiers, and membership without silent loss;
- emit coverage and reconciliation reports;
- assemble and validate an immutable Rulespec release plus REF operational
  records;
- publish the indexable expression corpus; and
- exercise deployment and rollback locally.

**Gate:** the managed release round-trips every supported source feature, and
every excluded or failed source value is counted and explained.

### Iteration 4 — Make Spicy Regs a consumer (historical delivery record)

This iteration records the pre-split implementation. Its lookup, ranking, and
accepted-output ownership is superseded by the notice at the top of this
document; the preserved tests remain useful migration evidence.

- replace local REF record definitions with a pinned RefSpec package;
- obtain the selected managed release through its immutable manifest;
- build a lookup index from the RefSpec expression corpus;
- retain source concept and release identities in every candidate;
- run lexical, dense, hybrid, and reranking experiments;
- bind results to exact RefSpec configuration and evaluation digests; and
- require the RefSpec deployment chain before accepted output.

**Gate:** Spicy Regs can rebuild and evaluate lookup from a clean checkout
without owning source acquisition, registry mutation, reconciliation, or
release policy.

### Iteration 5 — Expand and remove legacy paths

- add source adapters one at a time;
- require the same coverage and round-trip gates for each adapter;
- add mapping sets only with exact endpoint releases and reviewed relations;
- migrate useful legacy data through temporary readers;
- compare old and new lookup behavior; and
- delete duplicate or flat management paths only after parity, regression, and
  rollback tests pass.

**Gate:** every production vocabulary follows the managed-release path, and no
Spicy Regs code can silently become registry authority.

## 8. Historical first vertical slice

Use one small, structurally rich vocabulary before scaling.

### Inputs

- one immutable source distribution;
- source version, retrieval time, media type, rights information, and byte
  digest;
- the exact Rulespec version, revision, constraint digest, and profiles;
- an import policy that names every required semantic feature; and
- reviewer and authority references.

### Processing

1. Capture and verify the distribution.
2. Parse every required feature.
3. Compare source, parsed, indexed, excluded, and failed counts.
4. Preserve concept identifiers and all repeated relationships.
5. Reconcile conflicting official inputs when present.
6. Assemble the release and expression corpus.
7. Validate RefSpec and Rulespec records together.
8. Select and deploy the managed release.
9. Build a Spicy Regs lookup index.
10. Run development evaluation without changing the holdout.

### Outputs

- immutable source and import records;
- coverage and reconciliation reports;
- exact Rulespec release records and, when RefSpec authors or projects them,
  concept, scheme, relation, and mapping records;
- RefSpec registry deployment decision;
- indexable expressions with source paths and text digests;
- Spicy Regs index manifest;
- enrichment configuration and evaluation results; and
- an enrichment deployment decision or an explicit refusal to deploy.

## 9. Historical acceptance criteria

The migration is complete when:

1. RefSpec states the authority and lookup boundaries normatively.
2. One machine-readable source generates all REF-owned structural artifacts.
3. Generated artifacts never drift from their source.
4. Every REF-owned vocabulary-management record has valid, invalid, digest,
   round-trip, and requirement-linked tests.
5. RefSpec invokes the pinned Rulespec validator and does not translate or copy
   its constraints.
6. A clean RefSpec checkout can acquire, verify, import, reconcile, release,
   validate, deploy, and roll back at least one real vocabulary.
7. The release preserves multilingual labels, typed notation, all supported
   notes, multiple hierarchy parents, mappings, lifecycle events, identifiers,
   and exact membership.
8. Coverage failure, unresolved reconciliation, stale pins, wrong permission
   rows, or failed conformance blocks deployment.
9. Spicy Regs consumes a versioned RefSpec package and immutable managed
   releases instead of maintaining duplicate REF records.
10. Spicy Regs owns lookup algorithms and experiments but cannot mutate or
    authorize a registry release.
11. Changing a lookup index, model, prompt, provider, policy, budget, or output
    tuple creates a new `EnrichmentConfiguration` and requires a passing
    evaluation.
12. Changing managed vocabulary content creates a new release; rebuilding a
    lookup index alone does not.
13. Every accepted assignment resolves to an authorized release member and an
    exact configuration, evaluation, and deployment chain.
14. Large source distributions and indexes remain outside Git and resolve by
    immutable digest.
15. The old flat fusion remains migration evidence only and cannot pass the
    production conformance gate.

## 10. Explicit exclusions

This plan does not:

- move lookup algorithms, model adapters, document processing, or product
  workflows into RefSpec;
- copy Rulespec schemas, vocabulary terms, or semantic validators into
  RefSpec;
- claim that RefSpec authored or superseded an external vocabulary;
- make Spicy Regs a registry authority;
- accept the legacy fused registry as a production baseline;
- commit large vocabulary distributions, embeddings, or indexes to Git; or
- authorize a push, tag, release, publication, deployment, or submodule update.

## Done definition

RefSpec is the single implementation and conformance authority for REF-managed
vocabulary operations. Rulespec remains the semantic authority. Spicy Regs
rebuilds lookup from immutable RefSpec-managed releases, measures whether those
interfaces work in practice, and feeds evidence-backed changes into the next
specification iteration without bypassing either authority.
