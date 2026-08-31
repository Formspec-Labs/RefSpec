# Graph theory relevance to RefSpec

**Date:** 2026-08-24

**Status:** Research and architecture assessment. This note is not normative.
It does not amend the Atlas binding, accept a derived rule, qualify a mapping,
authorize publication, or approve downstream graph use.

**2026-08-25 follow-up:** REF-049 accepts the sixth rule as a capability. The
current working tree adds binding prose, ten portable rule cases, four positive
topology/support cases, a stale evidence-count refusal, and a contract-covered
registry for all six admissions. Binding conformance remains open until that
JSON registry replaces the parallel Python semantic roster. The corrected
contract must then be used to rebuild, seal, and publish a full Atlas
distribution. Finding 3 remains separate and open.

## Decision

Darij Grinberg's *An introduction to graph theory* strongly supports RefSpec's
separation of asserted, projected, and derived relations. It also supplies
useful language and algorithms for validator design. It does not change
RefSpec's authority model or justify centrality, graph ranking, universal
acyclicity, materialized closure, or a graph backend.

Keep the core graph architecture. Before publishing from the local checkout
assessed here, reconcile three contract and evidence gaps described below.

## Checkout and authority boundary

This review analyzed RefSpec commit `3db57e5d9428439ba6e18f8564078b86b3adb5bb`
on the local `atlas-v3-binding-and-relation-research` branch. At review time,
that branch was 47 commits ahead of its tracked remote. The SpicyRegs parent
still pinned RefSpec at `2a6e61a2c0200230578f986fd01fe56552e95f47` and
therefore reported `M RefSpec`; its `uv.lock` also had pre-existing changes.

The findings below describe the advanced local checkout. They do not establish
the state of the parent-pinned RefSpec revision or any sealed artifact.

RefSpec owns managed vocabulary publication, assertion qualification,
projections, and reproducible derived relations. Publishers retain authority
for their source content. SpicySearch owns retrieval, graph-use policy,
ranking, explanations, and serving. See
[`README.md:58-66`](../README.md#L58-L66) and REF-024 in the
[decision ledger](../docs/decisions.md#ref-024-assign-the-four-product-boundary-and-require-artifact-exchange).

## Research reviewed

The assessment used the complete table of contents on PDF pages 1-7, then read
these sections in full:

- section 2.4.1 and sections 2.7-2.12;
- sections 3.1-3.3;
- sections 4.1-4.6 and 4.9;
- sections 5.1-5.2, 5.4-5.6, and 5.17-5.19.6; and
- section 10.1.

Primary source:

- Darij Grinberg, *An introduction to graph theory*, Spring 2025 edition,
  arXiv:2308.04512v3, June 8, 2025.
  [Abstract](https://arxiv.org/abs/2308.04512) ·
  [PDF](https://arxiv.org/pdf/2308.04512) ·
  [DOI](https://doi.org/10.48550/arXiv.2308.04512)

## Existing architecture confirmed by the paper

Atlas already separates three kinds of graph information:

| Graph role | Meaning | Authority |
| --- | --- | --- |
| `asserted` | Identity-bearing, evidence-backed editorial assertions | Authoritative for the distribution when admissible and current |
| `projection` | Reproducible bare relations with links to supporting assertions | Non-authoritative interoperability view |
| `derived` | Reproducible rule results over exact inputs | Non-authoritative and opt-in |

The binding states this distinction explicitly
([`bindings/atlas/3.1/README.md:14-32`](../bindings/atlas/3.1/README.md#L14-L32)).
Several assertions may support one projected relation, and each projected
relation retains its supporting assertion identities
([`README.md:532-556`](../bindings/atlas/3.1/README.md#L532-L556)).

The paper reinforces three separate views that RefSpec must preserve:

1. **Semantic topology:** unique relation edges, paths, components, and cycles.
2. **Assertion topology:** identity-bearing claims, including parallel and
   reciprocal attestations over the same semantic pair.
3. **Publication authority:** which claims have exact evidence, accepted
   policy, reproducible derivation, complete membership, and valid seals.

Graph mathematics governs the first view. The Atlas binding and decisions
govern the other two.

## Section findings

| Paper sections | RefSpec relevance | Decision |
| --- | --- | --- |
| 2.4.1; 4.2 | Degree and in/out degree describe topology only after choosing a predicate, graph role, scheme, and release. | Report unique neighbors separately from assertion and evidence multiplicity. High degree is neither authority nor error. |
| 2.7-2.8; 4.3; 5.4.1 | A mathematical subgraph does not prove distribution or source-accounting closure. Narrow slices can miss corpus-wide integrity failures. | Preserve complete release membership and full-corpus checks where the decision requires them. Never call an extracted graph complete without its own closure evidence. |
| 2.9-2.10; 4.5; 5.1 | Paths, components, and cycles support exact-match components, cycle-safe hierarchy reachability, and simple derivation proofs. | Retain predicate-specific cycle rules. Do not add a universal hierarchy-DAG gate. |
| 2.12; 5.4.5; 10.1 | Bridges, articulation vertices, and disjoint paths measure structural fragility. | Use bounded diagnostics to prioritize review. Structural redundancy does not prove independent evidence or mapping validity. |
| 3.1-3.3; 4.1; 4.4 | An attributed multidigraph models distinct assertions better than bare RDF edge counts. Simplification loses identity and direction. | Keep the asserted/projection split. Assertion multiplicity must not become semantic degree or mapping strength. |
| 4.6 | Exact-match components and directed hierarchy strongly connected components answer different semantic questions. | Name the predicate, role, scheme, and direction behind every component metric. Weak connectivity is not equivalence. |
| 4.9 | Reverse traversal does not create a reverse attestation. Predicate inversion and endpoint reversal are separate transformations. | Preserve the direction of each publisher statement. Require a named, validated transformation for normalized inverse views. |
| 5.2; 5.4-5.6 | Tree and arborescence equivalences make strong rule-specific validators. They do not describe every vocabulary hierarchy. | Apply tree rules only when a source-specific decision declares a tree or forest. Preserve MeSH polyhierarchy. |
| 5.17-5.19.6 | Weighted Laplacians and stationary distributions need explicit edge-weight semantics and strong connectivity assumptions. | RefSpec has no accepted graph-weight policy. Centrality cannot license an assertion, choose a stronger predicate, or promote a derived relation. |

## Existing checks to preserve

The current validator already implements several relevant results more
precisely than the textbook:

- `ExactMatchIndex` computes undirected exact-match components without
  materializing Cartesian closure.
- SKOS S46 rejects incompatible broad, narrow, or related mappings inside an
  exact-match component.
- SKOS S27 hierarchy reachability uses cycle-safe strongly connected component
  condensation and batched directed reachability.
- Exact-match derived evidence requires one replayable simple path with no
  branches, unused inputs, duplicates, or cycles.
- Lifecycle succession remains linear and time-increasing.
- Evidence-adoption chains reject cycles.
- GCMD tree structure remains source-specific, while MeSH polyhierarchy is
  retained positively.

Relevant implementation starts at
[`validate.py:6000`](../bindings/atlas/3.1/tools/validate.py#L6000) for hierarchy
reachability, [`validate.py:6302`](../bindings/atlas/3.1/tools/validate.py#L6302)
for exact-match components, and
[`validate.py:7098`](../bindings/atlas/3.1/tools/validate.py#L7098) for proof
paths.

## Findings from the local checkout

These findings arose during the architecture trace. They are not conclusions
from the graph-theory paper.

### 1. Blocker: derived-rule semantics are outside the contract identity

The binding treats `contractDigest` as the identity of conformance, but the
executable `_DERIVED_RULE_ADMISSIONS` registry decides which rules, predicates,
directions, evidence shapes, and replays a distribution may contain
([`validate.py:7937`](../bindings/atlas/3.1/tools/validate.py#L7937)). The
validator source is not contract-covered, and the validator version remains
`3.1` ([`validate.py:118-170`](../bindings/atlas/3.1/tools/validate.py#L118-L170)).

Two validators can therefore identify themselves as the same contract while
admitting different derived graphs.

**Recommendation:** add a contract-covered `admitted-derived-rules.json` that
names each rule's identity, endpoint scope, predicate, direction or mirror,
evidence kind, and replay identity. Require exact equality between that file
and the executable registry. Change validator identity whenever replay
semantics change.

### 2. Blocker: a sixth rule lacks accepted and portable conformance authority

The binding says five rules are registered as of REF-046
([`README.md:573-579`](../bindings/atlas/3.1/README.md#L573-L579)). The local
validator admits a sixth Federal Register thesaurus/API-topic
`skos:closeMatch` rule
([`validate.py:272-295`](../bindings/atlas/3.1/tools/validate.py#L272-L295)).

Focused unit tests cover scheme scope, predicate strength, direction, and
asserted collisions. The review found no accepted decision, binding text, or
positive and negative portable conformance cases for the rule. Unit tests
prove implementation behavior, not binding authority.

**Recommendation:** do not publish this rule under the current 3.1 identity.
Either remove its admission or ratify it through an accepted decision, binding
text, the contract-covered registry, positive and negative corpus cases,
regenerated proof receipts, and a bounded real build.

### 3. Publication blocker pending full audit: transformed membership evidence

EuroVoc transforms a publisher statement from:

```text
concept skos:inScheme microthesaurus
```

to:

```text
microthesaurus atlas:hasSchemeMember concept
```

The adapter records the original triple in an in-memory `source_payload`
([`v3_registry_vocabularies.py:1030-1050`](../src/refspec/atlas/v3_registry_vocabularies.py#L1030-L1050)).
Static tracing indicates that the generic relation emitter does not retain that
relation-specific transformation evidence
([`generate_atlas_v3_full.py:5228`](../tools/generate_atlas_v3_full.py#L5228)).
The source-fidelity reconstruction supports named predicate translations but
the EuroVoc configuration does not declare the predicate and direction reversal
needed to reconstruct the publisher statement
([`verify_atlas_source_fidelity.py:22363-22382`](../tools/verify_atlas_source_fidelity.py#L22363-L22382),
[`SourceSpec:19783-19810`](../tools/verify_atlas_source_fidelity.py#L19783-L19810)).

The same seam affects GEMET's same-direction `skos:member` to
`atlas:hasSchemeMember` translation
([`v3_registry_vocabularies.py:1551-1614`](../src/refspec/atlas/v3_registry_vocabularies.py#L1551-L1614));
its current fidelity declaration still excludes the publisher's collection
layer ([`SourceSpec:19884-19915`](../tools/verify_atlas_source_fidelity.py#L19884-L19915)).

This review does not prove that published rows are wrong. It shows that current
checks do not yet prove the exact transformation.

**Recommendation:** create a validated transformation record containing the
original triple, normalized triple, transformation identity, endpoint
orientation, and digest. Configure source fidelity to reverse EuroVoc's
endpoints and predicate and to preserve GEMET's endpoints while translating
its predicate. Add negative fixtures for wrong direction, predicate, endpoints,
evidence, and publisher-relation digest.

## Bounded additions worth considering

These measurements belong in offline review reports, not authority or serving
gates:

- unique in/out-neighbor distributions by predicate, role, scheme, and release;
- assertion and evidence multiplicity per projected relation;
- component sizes and release-to-release component deltas;
- nontrivial strongly connected components, self-loops, and sink components;
- exact-match bridge impact, including newly connected pairs and newly exposed
  SKOS S46 conflicts;
- articulation vertices for review prioritization; and
- bounded, sampled minimum cuts for named high-value components.

Start with linear component, degree, bridge, articulation, and strongly
connected component passes. Avoid full cycle enumeration, all-pairs distance,
and all-pairs max-flow over the Atlas corpus.

Add portable fixtures for:

- two valid assertions supporting one projection;
- two evidence bindings supporting one assertion;
- reciprocal publisher-authored `skos:related` statements;
- cycle-safe hierarchy reachability;
- topology invariance when legitimate support multiplicity changes; and
- source-specific tree rules alongside positive polyhierarchy cases.

## Non-claims

The paper does not authorize:

- a graph database or new publication format;
- universal hierarchy acyclicity, connectivity, or one-parent rules;
- inferred relations in the asserted graph;
- materialized exact-match closure;
- assertion or evidence counts as graph weights;
- centrality as authority, confidence, or predicate strength;
- graph redundancy as evidence independence; or
- downstream search traversal or ranking.

Four meanings of closure must remain separate:

1. distribution closure: the complete manifest and member set;
2. release and source-accounting closure: complete declared membership and
   dispositions;
3. semantic closure: selected reproducible consequences, never new assertions;
4. publisher completeness: whether RefSpec captured everything the publisher
   offered, which a seal alone does not prove.

## Verification and confidence

One exact focused command passed during the initial review:

```sh
uv run pytest tests/test_fr_thesaurus_api_topic_alignment.py
```

Result at that point: 22 tests passed. The 2026-08-25 implementation follow-up
added the canonical-label refusal and now passes 23 rule tests, 25 binding
tests, four selected packed-distribution regressions, and the standalone
174-case corpus with 151 intentional refusals. These checks do not substitute
for a full Atlas build, source-fidelity audit, independent binding validator,
or seal verification.

Confidence is high for the contract-identity and sixth-rule findings. Confidence
is medium for the membership-transformation finding until the full fidelity
audit exercises the current producer and exact source bytes end to end.
