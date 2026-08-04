# RefSpec Product Boundary and API Disposition

**Effective date:** 31 July 2026  
**Status:** Current direction; compatibility migration in progress

## Product responsibility

RefSpec turns controlled-vocabulary sources into immutable releases and static
lookup assets.

**What goes in:** exact vocabulary source distributions, source metadata,
import policies, Rulespec Core artifacts, optional model-generated crosswalk
candidates, sealed evidence, and machine-validation receipts.

**What happens:** RefSpec preserves source bytes, imports vocabulary records,
checks coverage and identity, closes evidence references, validates releases,
and builds deterministic atlas files. Stable code performs mechanical checks.
At least two independent LLMs or agents perform the semantic check required for
a `searchOnly` mapping.

**What comes out:** digest-pinned managed-release files, a canonical crosswalk
bundle, canonical N-Quads, an atlas manifest, and validation receipts. RefSpec
does not publish a mutable query service or a physical search index.

**How consumers check it:** consumers verify the declared digests, canonical
bytes, Rulespec graph, exact `ReferenceResourceRelease` digests, release
membership, graph names, and graph counts. They then build local disposable
views.

Human feedback remains optional. People may append feedback after a mapping is
used. Feedback can inform a later release, but it does not rewrite the
historical machine decision and human approval does not gate M1, M2, or M3
`searchOnly` use.

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
| `refspec.atlas.VocabularyAtlasAsset` and atlas queries | Add | Keep the producer surface in the `refspec.atlas` namespace; consumers verify the three Atlas 2.0 files from one independently trusted manifest digest |
| `VerifiedManagedReleaseSource` and the Federal Register 2025 adapter | Add | Let complete verified package shapes publish one atlas format without translating them into a duplicate generic bundle |
| Canonical crosswalk bundle, candidates, evidence, machine receipts, deterministic checks, and feedback | Add | Keep every reference closed, bind each response to its validator and provider model, and require two distinct actors, independence groups, providers, provider model IDs, and responses; qualify `searchOnly` without human approval or a redundant aggregate receipt |
| `refspec-build-vocabulary-atlas` | Retire | Keep Atlas 2.0 construction programmatic until one pinned build-input file records the paths and trusted readers needed to reopen the complete `PinnedVocabularyAtlasScope` input set |
| Standalone `VocabularyRelease` and duplicate canonical JSON helpers | Retire | Do not add them to this implementation |
| Five-concept Federal Register release builder | Retire | Use the complete managed Federal Register package |
| Source-controlled document observations and capture records | Move | SpicyRegs owns new work; retain current RefSpec paths only for compatibility during migration |
| Enrichment evaluation and deployment records | Move | Product-local evaluation workflow; RefSpec retains vocabulary release proof |
| `authorize_accepted_assignment` | Move | Rulespec Extrapolator |
| `ReferenceRuntimeStore`, query products, ranking, and serving | Move | SpicySearch |

"Move" describes destination ownership, not completed deletion. Existing users
need a file-reader migration and a deprecation period before RefSpec removes a
compatibility API.

New atlas types are not re-exported from the broad `refspec` package root. The
`refspec.atlas` submodule is the intentional producer API; the published files
are the consumer API. RefSpec will add a producer command after it defines a
pinned build-input file.

## Consumer-reader rule

Consumers verify the selected manifest and distribution bytes, then validate
only the facts they use. Rulespec Extrapolator needs exact
`ReferenceResourceRelease` membership and digests. SpicySearch additionally
needs directed, machine-qualified mappings. Rulespec must not carry a duplicate
mapping-query implementation merely because the graph contains mappings.

This division is deliberate, not permission for formats to drift. RefSpec owns
the [manifest vocabulary and conformance fixtures](../bindings/atlas/1.0/README.md).
If repeated byte-level
verification becomes costly, publish a small versioned verifier library; do not
restore sibling source-tree imports or create another release model.

## Release rules

1. RefSpec publishes immutable files and their SHA-256 digests.
2. A changed source, policy, model request, model response, validator receipt,
   Rulespec artifact, implementation file, or output byte creates a new asset
   identity.
3. An atlas contains exactly two named graphs: authoritative copied release
   facts and replaceable analysis.
4. Equal normalized labels may create a cluster, but never create a mapping.
5. A qualified mapping remains `aiSuggested`, `statisticalInference`, and
   `searchOnly`. `machineQualifiedForSearch` describes the bounded machine
   check; it does not claim publisher endorsement or broader adoption.
6. Each mapping endpoint resolves to one exact reference-release digest in the
   copied release facts.
7. Feedback appends history; it never mutates a released decision.

## Compatibility policy

The broad REF editor's draft predates this product split. Its acquisition,
processing, enrichment, query, and accepted-output sections document existing
behavior and migration context. New RefSpec work follows this boundary.

Before removing a compatibility API, maintainers must identify every consumer,
publish the replacement file format, migrate each consumer, add a deprecation
notice, and run cross-repository tests. Removal, commit, release, and deployment
remain separate decisions.
