# RefSpec Product Boundary and Vocabulary Atlas Reconciliation Plan

**Date:** 31 July 2026  
**Status:** Implemented and verified locally; legacy compatibility removal and
delivery remain separate work  
**Integration base:** RefSpec commit `8fdf2d2a12ae0105a515369bb7aa1f27f28b7d01`

**Verdict:** `RECONSIDER`, with high confidence. Reverse the standalone release
foundation, retain its atlas work, and reshape the mature implementation around
the current product boundary.

The full baseline comparison is preserved in
[`2026-07-31-nested-and-standalone-refspec-comparison.md`](2026-07-31-nested-and-standalone-refspec-comparison.md).

## Decision

Keep the mature managed-release implementation in this checkout. Add the
vocabulary atlas as a deterministic static output of those releases. Do not
keep the standalone branch's second `VocabularyRelease`, canonical JSON
profile, validation receipts, or Federal Register first-slice package.

This decision preserves the complete vocabulary packages, exact source
artifacts, generated conformance assets, coverage reports, and verified
`ManagedReleaseView`. It also preserves the standalone branch's useful work:
the two-graph atlas, external input and output pins, machine-qualified
`searchOnly` mappings, read-only queries, and optional later feedback.

## Why the implementations diverged

Both implementations started from commit `714866d`, but they solved different
problems.

| Concern | Mature implementation retained here | Standalone implementation |
| --- | --- | --- |
| Release unit | A closed multi-file managed bundle | One compact `VocabularyRelease` JSON object |
| Source proof | Exact source bytes, normalized records, coverage, and receipts | A five-concept Federal Register fixture |
| Vocabulary breadth | Complete Federal Register 2025 plus ELSST, ICPSR, CRS, and other resources | One checked five-concept release; synthetic second releases in tests |
| Validation | REF binding, generated schemas, Rulespec graph checks, and package-specific gates | Small source-neutral validator plus fixture-specific release validator |
| Static lookup | Verified `ManagedReleaseView`; no portable atlas | Deterministic N-Quads atlas and manifest |
| Canonical JSON | Rejects `null`, floats, and unsafe integers | Allows `null` and finite floats |
| Product boundary | Broad historical REF pipeline | Narrow managed-vocabulary product |

The standalone release foundation duplicates working code and assigns the same
package name to an incompatible wire format. The atlas does not require that
duplication. `ManagedReleaseView` already supplies the verified Rulespec graph,
release identity, complete members, labels, relations, mappings, expressions,
and permissions needed to build it.

At the comparison baseline, this checkout contains about 36,620 source lines
across 43 modules, 286 test functions, nine packaged resources, and 20,970
records or observations. The standalone checkout contains about 5,108 source
lines across 15 modules and 42 test functions. Eighteen SpicyRegs files import
the mature RefSpec package; SpicySearch already parses the standalone
`VocabularyRelease` shape. The reconciliation must therefore migrate real
consumers, not merely choose between unused prototypes.

## Baseline verification

- Standalone RefSpec at `210d671`: 44 tests passed.
- Mature RefSpec at `8fdf2d2`: 304 passed, 17 failed, 11 errored, and 10
  skipped against the current sibling Rulespec checkout.
- The inspected mature failures are fail-closed dependency-pin mismatches. The
  manifest expects Rulespec evidence revision `2c66a85`; Rulespec now points to
  `320ed37`, which publishes separate Core and Extrapolator release artifacts.

The failing pin proves that the dependency gate detects drift. It does not
authorize changing the pin blindly: RefSpec must adopt the new Core release
artifact and move Extrapolator-owned behavior before claiming a passing new
baseline.

## Product boundary

Each product owns one kind of durable truth.

| Product | Owns | Does not own |
| --- | --- | --- |
| RefSpec | Managed vocabulary acquisition, exact source packages, releases, coverage, crosswalk candidates and checks, and static atlas publication | Regulatory document observations, document retrieval, ranking, or accepted-output decisions |
| SpicyRegs | Regulatory source capture, document identity, source observations, and evidence addresses | Vocabulary release authority or search ranking |
| Rulespec Core | Shared semantic record definitions and portable validation | Product workflow or generated inference decisions |
| Rulespec Extrapolator | Derived assertions, evidence chains, and accepted-output decisions | Vocabulary acquisition or search serving |
| SpicySearch | Query processing, indexes, ranking, retrieval, and serving | Vocabulary or document source authority |

Repositories exchange immutable, digest-pinned release files. A consumer does
not import another repository's source tree or query its mutable database. A
consumer may build disposable local indexes from verified files.

Consumer readers stay product-shaped. Shared integrity rules come from the
RefSpec format and conformance fixtures, but each product traverses only the
facts it uses: Rulespec checks exact reference-release membership; SpicySearch
also checks directed machine-qualified mappings. Copying the complete mapping
proof traversal into Rulespec would be duplicate, unused product logic.

## Canonical target

### Inputs

The atlas builder accepts one or more `VerifiedManagedReleaseSource`
implementations. This narrow interface supplies an exact publication pin and a
verified view of release graph facts, members, and source-backed expressions.
The generic `PinnedManagedRelease` and the complete 2025 Federal Register
package adapter both implement it without translating either package into a
second release model. An optional crosswalk bundle contains candidates, sealed
model requests and responses, evidence records, machine-validation receipts,
deterministic check results, and later feedback. Every reference must close
inside the bundle or against a pinned release artifact. The two machine
receipts carry the qualification proof directly; RefSpec does not add a third
aggregation record that repeats their decision.

### Processing

The builder:

1. verifies each managed release before reading it;
2. copies authoritative release facts into the asserted graph;
3. computes replaceable label clusters and crosswalk analysis in a separate
   analysis graph;
4. treats label equality as a discovery hint, never as a mapping;
5. qualifies a candidate for `searchOnly` only after deterministic checks and
   two machine validators agree on the same sealed input and request while
   using distinct actors, independence groups, providers, provider model IDs,
   and responses; and
6. records human feedback later without changing the historical qualification
   receipt.

Human approval is not an M1, M2, or M3 prerequisite. LLMs or independent
agents perform the semantic check first. People can append feedback after use;
future releases may use that feedback as new evidence.

### Outputs

The builder writes:

- canonical N-Quads with exactly one asserted graph and one analysis graph;
- a canonical JSON manifest that pins all input release manifests, the
  crosswalk bundle when present, implementation files, runtime versions,
  policy identifiers, output bytes, and graph counts; and
- no mutable serving database.

Portable opening needs only the atlas directory and independent manifest and
N-Quads digests. It verifies canonical bytes, graph names, graph counts,
authoritative membership, and every machine proof before exposing read-only
queries. Publisher reproduction adds the exact managed release, Rulespec Core,
crosswalk, implementation, runtime, and byte-for-byte rebuild checks.

## API disposition

| Current RefSpec surface | Decision | Destination or change |
| --- | --- | --- |
| `ManagedReleaseView`, managed bundles, coverage, exact sources, registry importers | Keep | Canonical RefSpec release foundation |
| Static `VocabularyAtlasAsset`, deterministic N-Quads, read-only atlas queries | Adapt | Build from verified managed bundles in RefSpec |
| Mapping candidates, machine-validation receipts, deterministic checks, optional feedback | Adapt | Use REF canonical JSON and close all evidence references |
| Standalone `VocabularyRelease`, duplicate canonical helpers, five-concept builder | Retire | No migration into this checkout; managed bundles replace them |
| Source-controlled document observations and document capture records | Move | SpicyRegs |
| Enrichment evaluation and deployment workflow | Move | Product-local evaluation workflow; RefSpec retains vocabulary release proof only |
| `authorize_accepted_assignment` and derived assertion decisions | Move | Rulespec Extrapolator |
| Query products, runtime stores, ranking, and serving | Move | SpicySearch |

Existing out-of-boundary Python APIs remain compatibility paths until their
consumers read published files. New RefSpec features must use the boundary
above. Removing a compatibility path requires a separate migration, warning
period, and release note.

## Execution sequence

1. **Preserve the base.** Keep the existing 12 modified files and untracked
   immutable helper intact. Add reconciliation work in separate files where
   possible.
2. **Publish the atlas.** Add the managed-release atlas model, builder, reader,
   query helper, command, and adversarial tests.
3. **Enforce machine-first qualification.** Require independent machine
   validators and deterministic checks; keep feedback optional and append-only.
4. **Close evidence.** Require every candidate, request, response, and evidence
   reference to resolve to exact bytes and a digest.
5. **Narrow the documented boundary.** Mark out-of-boundary APIs as
   compatibility surfaces and name their destination products.
6. **Migrate consumers.** Replace source-tree imports with local readers for
   published files, one product at a time.
7. **Align Rulespec.** Pin the published Rulespec Core artifacts used by
   releases and move accepted-output behavior to Rulespec Extrapolator. Do not
   replace the old full-graph pin until both paths pass their gates.
8. **Retire the duplicate branch.** Preserve its research evidence, then close
   or archive the duplicate release implementation after the atlas and consumer
   migrations land.

Current progress: steps 1 through 7 are implemented locally. RefSpec publishes
the complete static atlas from the mature managed release. Rulespec
Extrapolator pins the atlas triple and its exact `ReferenceResourceRelease`.
SpicyRegs and SpicySearch use product-local file readers, and SpicySearch has
retired the compact release API. The retired combined Rulespec proof now runs
only against its exact historical checkout; current tests use Rulespec Core
and the atlas. Step 8 is complete as a product decision: no active repository
uses the standalone compact foundation. Its clean checkout remains preserved
until a separate archive or deletion decision.

## Acceptance gates

The decisive user-value test is one complete vocabulary release built once and
independently consumed by SpicyRegs, Rulespec Extrapolator, and SpicySearch
without importing RefSpec source. Until that passes, the product split remains
incomplete.

- [x] One mature RefSpec managed-release model and one atlas format underpin
  every consumer; no compact release foundation remains.
- [x] The atlas accepts only digest-pinned, successfully opened managed
  releases.
- [x] Repeated builds from the same inputs produce byte-identical N-Quads and
  manifest output.
- [x] The atlas contains exactly two named graphs and never converts equal
  labels into mappings.
- [x] A `searchOnly` mapping requires deterministic checks plus two machine
  validators with distinct actors, independence groups, providers, provider
  model IDs, and responses; no human approval is required.
- [x] Human feedback is optional, append-only, and cannot rewrite the original
  machine qualification.
- [x] Every candidate, request, response, evidence item, receipt, and release
  reference closes against included or externally pinned bytes.
- [x] SpicySearch and Rulespec can verify the asset without importing RefSpec
  source or using a mutable RefSpec service.
- [x] The SpicyRegs model-facing command consumes the same published files
  without importing RefSpec source.
- [x] Existing complete vocabulary packages and their tests remain available.
- [x] RefSpec, SpicyRegs, Rulespec, and SpicySearch focused tests pass against
  their declared pins.

## Verification and delivery record

Local verification on 31 July 2026:

- RefSpec `make test`: 335 passed and 41 intentionally skipped historical
  combined-pin checks. `make test-cross-repository` passes the 98-case REF
  binding corpus and six current Rulespec Core and atlas checks. Whole-repo
  Ruff and `git diff --check` pass.
- SpicyRegs full suite with its declared `embed` extra: 2,799 passed, 74
  skipped, four deselected, and two expected failures. The file-only candidate
  reader adds adversarial checks for external pin drift, Boolean count
  confusion, noncanonical N-Quads, and blocked RefSpec imports.
- Rulespec's complete gate passes: 157 Rust tests; 236 isolated Python tests
  with both live RefSpec cross-repository checks intentionally skipped; those
  two live checks pass separately; 275 expected negative-fixture rejections;
  and 497 conformance fixtures with no divergence. Changed Python files also
  pass Ruff, Black, isort, compileall, and tabnanny; repository whitespace
  checks pass.
- SpicySearch full suite: 224 passed with no skips. Ruff and
  `git diff --check` pass. Its production and test trees contain no compact
  release API identifier or RefSpec Python import.
- Independent processes opened the same complete files. RefSpec produced 705
  members and 5,426 quads; Rulespec proved exact membership; SpicyRegs loaded
  705 candidates; and SpicySearch loaded 705 members. None of the three
  consumer processes imported RefSpec.
- RefSpec and Rulespec hold byte-identical atlas files. Rulespec and
  SpicySearch hold byte-identical `ExtrapolationRelease` files.
- Adversarial regressions reject reused or contradictory validator responses,
  non-independent validator actors, independence groups, providers, provider
  model IDs, or response artifacts, mismatched managed-release pins and views,
  forged resealed mappings, same-release label clusters, output tampering, and
  valid receipts applied to different endpoints.

The complete atlas has these external pins:

- asset: `urn:ref:vocabulary-atlas:9069a26d36c2695a02edb501dc51011f48aee382d96a0e200cd2c1d3574d7dec`;
- manifest: `sha256:956cab4f20477933ef015c2c87647ebb9cc40c4c68247a93b10dab8b113f60f1`;
- N-Quads: `sha256:8e1eaf2265874863981fe9322e0a0e286c01c43e598b091736b556ea424e830a`;
  and
- reference release: `sha256:30742a82b3e268942aec713a02c5ae4264eadea36aa61b564ffc93eeecfd5fe6`.

The final Rulespec `ExtrapolationRelease` is
`urn:rulespec:extrapolation:8991fb9140866dceea7b9539da2f5a4b9295e039dc6dd333a75c217de0c443d4`.

Remaining compatibility work is deliberately outside this cutover. Existing
SpicyRegs accepted-output, open-set, evaluation, and legacy managed-release
modules still import mature RefSpec APIs. They remain explicit compatibility
paths until Rulespec Extrapolator supplies their replacement behavior and each
caller migrates. Removing those APIs now would discard working behavior rather
than complete the file boundary.

Local changes do not count as committed, pushed, released, or deployed work.
