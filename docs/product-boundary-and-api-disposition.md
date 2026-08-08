# RefSpec Product Boundary and API Disposition

**Effective date:** 4 August 2026
**Reviewed:** 8 August 2026
**Status:** Current product boundary under Atlas 3.0

The ownership boundary in this document remains current. Atlas 3.0 supersedes
the format-specific Atlas 2.0 API disposition recorded here. Atlas 2.0 class
and command names remain below only as a legacy-removal inventory; they do not
authorize new Atlas 2.0 production work.

## Product responsibility

RefSpec turns controlled-vocabulary sources into immutable releases and static
lookup assets.

**What goes in:** exact vocabulary source distributions, source metadata,
selection policies, source-concept and registry-claim releases, sealed relation
evidence, and machine-proof receipts. An `AtlasIndex` may describe planned
placement, but it does not authorize source-unit admission.

**What happens:** RefSpec preserves source bytes, imports vocabulary records,
checks coverage and source identity, closes evidence references, validates
releases, assigns one of four semantic rings, and builds deterministic atlas
files. Stable code performs mechanical checks. A registered proof adapter
turns a sealed semantic qualification result into typed mapping evidence.

**What comes out:** digest-pinned source and managed concept releases, relation
bundles, an Atlas 3.0 manifest with authoritative RDF packs and construction
evidence, derived local views, publication decisions, and static publications.
RefSpec does not publish a mutable query service or a physical search index.

**How consumers check it:** consumers verify the binding and manifest pins,
member and pack bytes, exact release membership, record closure, graph roles
and counts, typed relation rules, and content-derived identities. The
independent Atlas 3 validator supplies the conformance verdict. Consumers may
then build disposable local views. Product policy separately grants search or
emission use.

## Authority map

Rows are release units, not products. Rulespec is one product shipping two of
them, so five rows describe four products — see
[REF-008](decisions.md#ref-008-count-four-products-and-five-ownership-rows).

| Owner | Durable authority |
| --- | --- |
| RefSpec | Controlled-vocabulary sources, imports, releases, coverage, crosswalk evidence, and static atlas assets |
| SpicyRegs | Regulatory source capture, document identity, source observations, and evidence addresses |
| Rulespec Core | Shared semantic record definitions and portable validation |
| Rulespec Extrapolator | Derived assertions, evidence chains, and accepted-output decisions |
| SpicySearch | Query processing, indexes, ranking, retrieval, and serving |

Repositories exchange immutable release files. A product must not import a
sibling repository's source tree or read its mutable database. A versioned
library may help a product verify a file, but the file remains the integration
boundary and source of truth.

## Public API disposition

| Surface | Status | Action |
| --- | --- | --- |
| `ManagedReleaseView` | Keep | Canonical read-only view of a verified managed release |
| Managed vocabulary bundles, importers, source packages, coverage, and reconciliation | Keep | Core RefSpec behavior |
| Source-controlled resources and source-concept releases | Keep | Preserve useful publisher concepts and mint explicit source-scoped identities only when the publisher supplies none |
| `VocabularyAtlasAsset`, `PinnedVocabularyAtlasScope`, and `VocabularyAtlasQueries` | Legacy | Retain for existing Atlas 2.0 readers until a caller and fixture audit permits removal; do not use for new production paths |
| Ring and subject-module views | Keep | Publish complete record subsets with closed relation, evidence, and proof dependencies |
| Typed relation bundles and proof adapters | Keep | Share record shapes across rings while enforcing ring-specific predicates and trust rules |
| Downstream product-use eligibility and concept authoring | Keep | Reuse existing identities without reminting; use staging only for genuinely new RefSpec concepts; keep product permission separate from source-unit admission |
| Publication decisions and static publication | Keep | Require exact scope, result, policy, and decision pins before producing consumer files |
| `refspec-build-vocabulary-atlas` | Retire | Keep the Atlas 2.0 command retired; Atlas 3 construction uses its own pinned inputs and binding-specific generator |
| Standalone `VocabularyRelease` and duplicate canonical JSON helpers | Retire | Do not add them to this implementation |
| Five-concept Federal Register release builder | Retire | Use the complete managed Federal Register package |
| Document observations and capture records | Exclude | SpicyRegs owns regulatory document capture; RefSpec accepts only published evidence files at this boundary |
| Enrichment evaluation and deployment records | Move | Product-local evaluation workflow; RefSpec retains vocabulary release proof |
| `authorize_accepted_assignment` | Move | Rulespec Extrapolator |
| `ReferenceRuntimeStore`, query products, ranking, and serving | Move | SpicySearch |

New atlas types are not re-exported from the broad `refspec` package root. The
`refspec.atlas` submodule is the intentional producer API; the published files
are the consumer API. The current Atlas 3 generator remains binding-specific
until one production entry point can consume a complete, validated release
inventory.

## Consumer-reader rule

Consumers verify the selected Atlas 3 manifest, binding bundle, distribution
members, and RDF packs, then run the independent validator before building a
derived query view. A consumer that needs mappings reads typed assertions and
their evidence closure. A consumer that needs assignments also verifies its
own emission and product-policy records.

RefSpec owns the
[Atlas 3.0 binding, closed schemas, and validator](../bindings/atlas/3.0/README.md).
Reuse that versioned verifier boundary; do not restore sibling source-tree
imports or create another release model.

## Release rules

1. RefSpec publishes immutable files and their SHA-256 digests.
2. A changed source, policy, model request, model response, validator receipt,
   Rulespec artifact, implementation file, or output byte creates a new asset
   identity.
3. A concept belongs to exactly one ring: `subject`, `entity`, `value`, or
   `legalIdentity`.
4. All rings share concept, release, evidence, mapping-assertion, and lifecycle
   shapes; each ring enforces its own relations and safety rules.
5. Equal normalized labels support explicit-ring discovery only. They never
   create identity or a mapping.
6. Every mapping endpoint resolves to one exact concept release included in
   the scope. Every retained relation carries its complete evidence closure
   and, when it cites machine evidence, its complete proof closure.
7. Ring, participation, evidence, rights, source-unit admission, and intended
   use are facts. A separately pinned product policy grants downstream use.

## Greenfield rule

Atlas 3.0 is the only active distribution design. Atlas 1.0 and 2.0 remain
immutable historical formats for existing consumers and regression evidence.
New producers do not translate through them or carry their compatibility
aliases into Atlas 3. Dated specifications, measurements, and decision entries
remain historical evidence; they do not define the current runtime or file
boundary.
