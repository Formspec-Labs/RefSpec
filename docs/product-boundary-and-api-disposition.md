# RefSpec Product Boundary and API Disposition

**Effective date:** 4 August 2026
**Status:** Current Atlas 2.0 boundary

## Product responsibility

RefSpec turns controlled-vocabulary sources into immutable releases and static
lookup assets.

**What goes in:** exact vocabulary source distributions, source metadata,
selection policies, source-concept releases, an exact AtlasIndex, sealed
relation evidence, and machine-proof receipts.

**What happens:** RefSpec preserves source bytes, imports vocabulary records,
checks coverage and source identity, closes evidence references, validates
releases, assigns one of four semantic rings, and builds deterministic atlas
files. Stable code performs mechanical checks. A registered proof adapter
turns a sealed semantic qualification result into typed mapping evidence.

**What comes out:** digest-pinned source and managed concept releases, relation
bundles, a three-file canonical Atlas 2.0 distribution, closed ring or subject
module views, publication decisions, and static publications. RefSpec does not
publish a mutable query service or a physical search index.

**How consumers check it:** consumers verify the declared digests, canonical
bytes, exact release membership, record closure, graph names, graph counts,
typed relation rules, and content-derived identities. They then build local
disposable views. Product policy separately grants search or emission use.

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
| `VocabularyAtlasAsset`, `PinnedVocabularyAtlasScope`, and `VocabularyAtlasQueries` | Keep | Build and read one closed four-ring Atlas 2.0 distribution from exact releases and relations |
| Ring and subject-module views | Keep | Publish complete record subsets with closed relation, evidence, and proof dependencies |
| Typed relation bundles and proof adapters | Keep | Share record shapes across rings while enforcing ring-specific predicates and trust rules |
| Subject admission, emission eligibility, and concept authoring | Keep | Admit existing identities without reminting; use staging only for genuinely new RefSpec concepts; keep product permission external |
| Publication decisions and static publication | Keep | Require exact scope, result, policy, and decision pins before producing consumer files |
| `refspec-build-vocabulary-atlas` | Retire | Keep Atlas 2.0 construction programmatic until one pinned build-input file records the paths and trusted readers needed to reopen the complete `PinnedVocabularyAtlasScope` input set |
| Standalone `VocabularyRelease` and duplicate canonical JSON helpers | Retire | Do not add them to this implementation |
| Five-concept Federal Register release builder | Retire | Use the complete managed Federal Register package |
| Document observations and capture records | Exclude | SpicyRegs owns regulatory document capture; RefSpec accepts only published evidence files at this boundary |
| Enrichment evaluation and deployment records | Move | Product-local evaluation workflow; RefSpec retains vocabulary release proof |
| `authorize_accepted_assignment` | Move | Rulespec Extrapolator |
| `ReferenceRuntimeStore`, query products, ranking, and serving | Move | SpicySearch |

New atlas types are not re-exported from the broad `refspec` package root. The
`refspec.atlas` submodule is the intentional producer API; the published files
are the consumer API. RefSpec will add a producer command after it defines a
pinned build-input file.

## Consumer-reader rule

Consumers verify the selected manifest and distribution bytes, then use the
generic query API or another implementation of the Atlas 2.0 format. A
consumer that needs mapping expansion reads typed mapping assertions and their
evidence closure. A consumer that needs assignments also verifies its own
admission, emission, and product policy records.

RefSpec owns the [Atlas 2.0 file format and closed schemas](../bindings/atlas/2.0/README.md).
If repeated byte-level verification becomes costly, publish a small versioned
verifier library; do not restore sibling source-tree imports or create another
release model.

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
7. Ring, participation, evidence, rights, admission, and intended use are
   facts. A separately pinned product policy grants use.

## Greenfield rule

Atlas 2.0 is the only active distribution design. RefSpec rejects other Atlas
shapes instead of translating them or carrying compatibility aliases. Dated
specifications, measurements, and decision entries remain historical evidence;
they do not define the current runtime or file boundary.
