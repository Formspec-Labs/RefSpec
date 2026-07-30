<!-- markdownlint-disable MD013 -->

# Standards composition and graph extensibility plan

> **Status:** Deferred, trigger-based plan; not an active implementation program
>
> **Date:** 2026-07-30
>
> **Current execution roadmap:** [Managed vocabulary experiment roadmap](managed-vocabulary-experiment-roadmap.md)
>
> **Implemented ownership baseline:** [Vocabulary management and lookup separation](vocabulary-management-lookup-separation-plan.md)
>
> **Normative specifications:** [RefSpec 1.0](../spec/refspec.md) and the [RefSpec Rulespec application profile](../profiles/rulespec-application-profile.md)

## Decision

Build a standards-aware vocabulary framework without requiring every relevant
standard.

When an external standard owns a meaning, preserve and compose its identifiers,
types, predicates, and graph structure. Rulespec and RefSpec add only the
semantic qualification and operational behavior that the external standard
does not supply.

This plan does not schedule DDI, RDF Data Cube, GSIM, XKOS, or Neuchâtel
implementation. It records where those standards may become relevant and the
evidence that must trigger work.

The managed vocabulary experiment remains the priority. Standards work must not
delay independent product-value evaluation or one narrow promotion.

## 1. Intended framework

The framework must remain:

- **extensible:** a new source, vocabulary, ontology, classification, mapping
  structure, or data model can join through stable identifiers and a versioned
  profile;
- **relevant:** relevance belongs to an evidence-backed assignment between a
  resource and a concept, scoped by facet, role, release, and use;
- **graphable:** resources use stable IRIs, relationships retain their
  predicates and direction, and qualified relationships can carry evidence,
  provenance, time, and exact release references;
- **standards-aware:** the framework reuses public semantics when they fit and
  records known reuse points before contributors invent competing terms; and
- **storage-neutral:** JSON-LD and RDF supply the portable graph. Tables, search
  indexes, and property graphs remain replaceable views.

The framework is not a universal vocabulary, a graph database mandate, or a
local copy of adjacent standards.

## 2. Ownership rule

| Concern | Owner |
| --- | --- |
| Publisher-issued vocabulary or data structure | Native publisher and source standard |
| Concepts, assignments, qualified mappings, evidence, lifecycle, authority, and semantic conformance | Rulespec and adopted external standards |
| Capture, preservation, import coverage, reconciliation, managed releases, permissions, evaluation, and deployment | RefSpec |
| Indexing, retrieval, ranking, document integration, and product relevance | Spicy Regs |

Use these rules for every proposed term:

1. Preserve source-native data before projection.
2. Reuse an external type or predicate when a maintained standard already owns
   the meaning.
3. Use a Rulespec assertion to qualify an external relationship when the
   product needs evidence, provenance, authority, lifecycle, or exact release
   references.
4. Use a RefSpec record only for operational behavior that RefSpec owns.
5. Add a versioned extension profile when a source needs portable structure
   outside the core.
6. Add a new Rulespec primitive only when no suitable standard exists and two
   independent uses demonstrate the need, or one reproduced failure proves the
   missing rule necessary.

## 3. Current baseline

The present specifications already establish the main direction:

- Rulespec composes with public ontologies through direct imports, class or IRI
  alignment, projections, and informative pattern citations.
- Rulespec states that public ontologies own their established meanings.
- RefSpec forbids competing REF primitives when Rulespec or an adopted external
  standard owns the meaning.
- RefSpec extension profiles use stable absolute IRIs and require explicit
  boundaries and round-trip fixtures.
- Rulespec can attach native and Rulespec nodes in one JSON-LD graph.
- RefSpec preserves native distributions as the publisher's authority and
  treats graph and search indexes as derived views.

The baseline leaves four matters to verify or complete:

1. `rkaf:RegisteredConcept`, `rkaf:LocalConcept`, and
   `rkaf:ConceptScheme` are described as SKOS-compatible, but their
   machine-readable relationship to `skos:Concept` and
   `skos:ConceptScheme` needs an explicit, tested rule.
2. The core REF JSON Binding correctly rejects unknown fields, but the project
   has not demonstrated how a separate extension package contributes its
   schema, context, validation rules, and dispatch without weakening the core.
3. The JSON-LD projector proves its common graph shape, but broader native graph
   composition and canonical round trips need focused fixtures before a public
   graph-interoperability claim.
4. The interoperability inventories do not yet name DDI, RDF Data Cube, GSIM,
   XKOS, or Neuchâtel as known reuse points.

## 4. Sequence

### 4.1 Needed now

Only this planning decision is needed now:

- keep the managed vocabulary experiment roadmap authoritative;
- add no new standard dependency, schema, class, predicate, adapter, or runtime
  service;
- treat DDI, RDF Data Cube, GSIM, and XKOS as known external ownership
  candidates; and
- treat Neuchâtel as historical lineage carried forward by GSIM and XKOS.

No active product behavior changes in this step.

### 4.2 Triggered by a public mixed-graph interoperability claim

Complete these checks before another consumer depends on a combined native and
Rulespec graph, or before the project publishes a claim that the two graphs
interoperate:

1. Decide and document the machine-readable SKOS relationship for Rulespec
   concept and scheme types. Prefer formal composition over a second,
   independently meaningful concept model.
2. Add a mixed native-SKOS and Rulespec JSON-LD fixture.
3. Prove that attach, validation, extraction, and canonical reconstruction
   preserve:
   - every node IRI;
   - external and Rulespec types;
   - external predicates and edge direction;
   - language-tagged and typed literals;
   - multiple hierarchy parents;
   - qualified assignment and mapping nodes; and
   - exact release and evidence references.
4. Keep closed core REF records closed. Do not add a generic
   `extensions` object.

These checks cover the graph boundary that the current vocabulary work already
uses. They do not require DDI, RDF Data Cube, GSIM, or XKOS.

This step does not block a narrow promotion that consumes an unchanged,
already-validated managed release and makes no mixed-graph interoperability
claim.

### 4.3 Triggered by the first independently validated extension

Define extension packaging only when a real extension must validate outside the
core REF JSON Binding.

The package must identify:

- its stable profile IRI and version;
- the external standards and exact versions it composes;
- its JSON Schema or other operational schema;
- its JSON-LD context and semantic validation shapes when applicable;
- the core RefSpec requirements it inherits;
- its canonicalization and digest rules;
- positive, negative, and lossless round-trip fixtures; and
- migration behavior.

The combined validator must dispatch to the extension package without accepting
unknown fields in core records.

### 4.4 Triggered by a statistical classification

Use this step when onboarding NAICS, SOC, or another real classification with
ordered levels, variants, or many-to-many correspondences.

- Use SKOS for concepts and ordinary semantic relations.
- Use XKOS for statistical-classification levels and correspondence structures
  when its model fits.
- Use GSIM as conceptual guidance where XKOS or the source leaves meaning
  ambiguous.
- Preserve the publisher's native classification graph.
- Use Rulespec only to add evidence, exact release pins, lifecycle,
  attestations, and permitted use.
- Do not flatten one governed correspondence into misleading independent
  pairwise mappings.

The first proof should compare two real classification releases and include a
publisher-authored correspondence.

### 4.5 Triggered by research-data ingestion

Use this step when an ICPSR or other research-data source exposes studies,
variables, universes, questions, value domains, or data structures.

- Preserve its source-native DDI representation when present.
- Project only vocabulary concepts and expressions needed for managed lookup.
- Keep study, dataset, variable, question, and value-domain identity distinct.
- Add a DDI profile only if another producer or consumer needs a validated,
  portable exchange.

Do not flatten the research-data model into a concept scheme.

### 4.6 Triggered by multidimensional observations

Use RDF Data Cube only when a source or output contains actual observations
organized by dimensions, measures, attributes, and coded values.

- Keep operational REF observation records distinct from `qb:Observation`.
- Preserve the native cube structure.
- Link coded dimensions to exact managed vocabulary members.
- Apply RefSpec release and use controls to those vocabulary references.

Do not model every number extracted from a document as an RDF Data Cube
observation.

### 4.7 No scheduled implementation

Do not schedule:

- a standalone Neuchâtel implementation;
- the full GSIM production-process model;
- local copies of DDI, RDF Data Cube, SKOS, XKOS, or other public classes and
  predicates;
- a graph database migration without a measured query need;
- arbitrary extension fields inside core REF records;
- label-based identity merging; or
- a universal cross-domain concept dictionary.

## 5. Graph requirements

A graph projection must make these paths possible without changing the
underlying authority:

```text
document
  -> qualified concept assignment
  -> exact concept member
  -> concept scheme and release
  -> native or adopted mapping
  -> concept in another scheme
```

When data standards enter the graph, the same identity chain continues:

```text
research variable --DDI relation--> concept
statistical observation --QB dimension--> classification item
classification item --XKOS correspondence--> item in another release
```

The graph must distinguish:

- a direct source assertion from a derived or reviewed assertion;
- a simple edge from a qualified relationship;
- concept identity from labels and indexed expressions;
- one release's membership from another release's membership;
- an external standard's type from a RefSpec processing route;
- a durable assertion from a query-time association; and
- a canonical graph from disposable table, property-graph, and search
  projections.

## 6. Acceptance checks

Work under this plan is complete only when the triggered use passes its
applicable checks:

1. No local class or predicate duplicates a suitable external term without a
   documented semantic difference.
2. Native identifiers, types, predicates, literals, language tags, datatypes,
   and relationship cardinality survive a round trip.
3. Qualified relationships retain evidence, provenance, time, authority, and
   release references without replacing their external predicate.
4. Core REF records remain closed and validate independently of optional
   extension packages.
5. An extension can be omitted without breaking consumers that do not claim
   that profile.
6. Spicy Regs can traverse the resulting identifiers for lookup without
   becoming the authority for the vocabulary or external graph.
7. The triggered work improves a named source integration, consumer exchange,
   or user query. A standards-only demonstration does not justify runtime
   adoption.

## 7. Stop rules

Keep a standard informative when no named source or consumer needs it.

Stop implementation when:

- the native source can be preserved and referenced without a new profile;
- an existing Rulespec or external term already covers the meaning;
- the proposed work would delay the managed-vocabulary product-value gate;
- the work cannot name a user query, source-preservation failure, or exchange
  requirement it improves; or
- implementation would make RefSpec or Rulespec authoritative for semantics
  owned elsewhere.

The framework gains value by remaining open to standards, not by implementing
them in advance.
