# RefSpec

RefSpec manages controlled-vocabulary source packages, verified releases,
crosswalk evidence, and static vocabulary atlas assets. It preserves exact
source material and publishes digest-pinned files that other products can
verify without importing this source tree or querying a RefSpec service.

RefSpec is an unpublished editor's draft. The repository makes no W3C
endorsement claim. No license has been selected, so publication does not grant
permission beyond rights supplied by applicable law.

## Documents

- [Vocabulary Atlas Distribution 1.0 — normative consumer contract](bindings/atlas/1.0/README.md)
- [Publish and inspect a vocabulary atlas](docs/atlas-publication.md)
- [Historical managed vocabulary release decision record](spec/managed-vocabulary-release.md)
- [Historical RefSpec 1.0 editor's draft](spec/refspec.md)
- [Rulespec application profile](profiles/rulespec-application-profile.md)
- [Core enrichment profile](profiles/enrichment-profile.md)
- [REF JSON Binding 1.0](bindings/json/1.0/README.md)
- [Authoritative REF structural model](model/README.md)
- [Active managed vocabulary experiment roadmap](plans/managed-vocabulary-experiment-roadmap.md)
- [Experimental resource catalog](portfolio/resource-catalog-v0.json)
- [Non-authorizing atlas and sibling-publication index](portfolio/atlas-index-v0.json)
- [Completed resource package inventory](portfolio/completed-resource-packages-v2.json)
- [Deferred standards composition and graph extensibility plan](plans/standards-composition-and-graph-extensibility-plan.md)
- [Implemented vocabulary management and lookup separation baseline](plans/vocabulary-management-lookup-separation-plan.md)
- [Completed vocabulary gap closure plan](plans/vocabulary-gap-closure-plan.md)
- [Historical conceptual implementation plan](plans/implementation-plan.md)
- [Research-input register](docs/research-inputs.md)
- [Decision ledger](docs/decisions.md)
- [Reconciliation runbook](docs/reconciliation-runbook.md)
- [Atlas crosswalk qualification pilot](docs/atlas-crosswalk-qualification-pilot.md)
- [ICPSR at the atlas door](docs/icpsr-atlas-bridge.md)
- [Current product boundary and API disposition](docs/product-boundary-and-api-disposition.md)
- [Nested and standalone implementation comparison](plans/2026-07-31-nested-and-standalone-refspec-comparison.md)
- [Product-boundary and atlas reconciliation plan](plans/2026-07-31-refspec-product-boundary-and-atlas-reconciliation-plan.md)
- [Research archive](research/README.md)

## Planning status

The product-boundary and atlas reconciliation plan controls current scope and
delivery. The managed vocabulary experiment roadmap remains an internal
research sequence within that boundary: it keeps daily research in a
lightweight, candidate-only lane and applies the full RefSpec and Rulespec
release process only when a result enters the promotion lane.

The former SpicyRegs profile portfolio is retained as dated research evidence.
The current experimental catalog records RefSpec-owned resource facts and
distinguishes verified repository-contained distributions from evidence-only
and planning entries. The separately identified atlas index classifies every
registry source by semantic ring and records subject-atlas participation
plans. Both artifacts are evidence for planning; neither defines product
permissions or search policy.

The vocabulary gap closure and management-separation plans record completed
local baselines. The early implementation plan and broad editor's draft remain
available as capability and migration inventories; they no longer control
delivery sequence or product scope.
The standards-composition plan records conditional work and does not change the
active roadmap's order.

## Ownership boundary

RefSpec owns managed vocabulary acquisition, exact source packages, release
validation, coverage, crosswalk evidence, and static atlas publication. Native
publishers remain authoritative for their source distributions.

SpicyRegs owns regulatory document capture, source observations, document
identity, and evidence addresses. Rulespec Core owns reusable semantic records
and their portable constraints. Rulespec Extrapolator owns derived assertions,
evidence chains, and accepted-output decisions. SpicySearch owns query
processing, indexes, ranking, retrieval, and serving.

These are five owners across four products: Rulespec Core and Rulespec
Extrapolator are two release units of one product, per
[REF-008](docs/decisions.md#ref-008-count-four-products-and-five-ownership-rows).

Published, digest-pinned files connect these products. Each consumer verifies
the files and may build a disposable local index. It does not import another
product's source tree or depend on that product's mutable database.

Atlas 2.0 construction is programmatic. A producer first opens the exact atlas
index, concept releases, relation bundles, and machine-proof sources, then
creates a `PinnedVocabularyAtlasScope` that retains those verified inputs:

```python
from refspec.atlas import build_vocabulary_atlas

asset = build_vocabulary_atlas(pinned_scope)
asset.write("build/vocabulary-atlas")
```

The producer writes `atlas-manifest.json`, `atlas-scope.json`, and `atlas.nq`.
The portable scope records content identities and digests, but it omits the
local paths and trusted reader choices needed to reopen every input. RefSpec
will add an Atlas 2.0 build command only after it defines one pinned build-input
file that records those paths and choices explicitly.

`refspec-build-vocabulary-atlas-projection` cuts a verified atlas down to a
named policy's keep rule and publishes the result as a **separate distribution
kind**, `refspec-vocabulary-atlas-projection-nquads-1.0`
([REF-011](docs/decisions.md#ref-011-publish-a-consumer-shaped-projection-as-its-own-distribution-kind)).
A projection names its parent's asset id and both of its digests in
`derivedFrom`, carries the keep rule and its version in `projectionPolicy`, and
derives its own identifier from all three, so it can never be confused with the
generation it came from. It reproduces from that parent and that policy rather
than from managed releases:

```sh
uv run refspec-build-vocabulary-atlas-projection \
  --atlas build/vocabulary-atlas \
  --atlas-manifest-digest sha256:<manifest digest> \
  --atlas-output-digest sha256:<n-quads digest> \
  --output build/vocabulary-atlas-projection
```

Atlas 2.0 consumers call `VocabularyAtlasAsset.open` with the atlas directory
and one independently trusted manifest digest. The manifest pins the scope and
N-Quads files. Producers may call `reproduce_from_scope` with
the exact `PinnedVocabularyAtlasScope` to reopen every source and rebuild all
three files byte for byte.

`refspec-publish-vocabulary-atlas` verifies those same two pins and produces a
static publication directory with a deterministic gzip download, reusable
bounded graph data, an offline explorer, and a manifest that pins every
payload. It neither acquires source files nor changes atlas semantics:

```sh
uv run refspec-publish-vocabulary-atlas \
  --atlas build/vocabulary-atlas \
  --atlas-manifest-digest sha256:<manifest digest> \
  --atlas-output-digest sha256:<n-quads digest> \
  --output build/vocabulary-atlas-publication
```

See [Publish and inspect a vocabulary atlas](docs/atlas-publication.md) for the
real Federal Register, ELSST, and ICPSR MVP command and its exact pins.

The broad REF pipeline APIs and specification sections remain compatibility
surfaces while consumers migrate. They do not define the scope for new RefSpec
features. See the
[current boundary and API disposition](docs/product-boundary-and-api-disposition.md).

The dated research snapshots used to develop the editor's draft are archived
under [`research/`](research/README.md). They are nonnormative except where the
specification explicitly identifies a portfolio baseline.

## Current dependency state

New managed-release and atlas work pins the separate
[`RulespecCoreRelease`](profiles/rulespec-core-dependency.json) introduced at
Rulespec revision `320ed37f0df13a9609490a2b43389c6be57242cc`. The checked
artifact has status `fixture`, so RefSpec makes no production conformance
claim.

The broad compatibility implementation still targets the older combined
Rulespec `0.2.0-pre.9` candidate. Its tested contract revision is
`0eb94257b70783688b55220e7a84dcc61bbd7507`; its evidence revision is
`2c66a85daab30a4869db08d21cea13cfc865b3a0`; and its constraint digest is
`sha256:8feadf8f4037a60a18667c6f7ee920ff1285ccb05a72fe5352b6cd82b38a252c`.
The legacy [dependency manifest](profiles/rulespec-dependency.json) remains in
place until its consumers move to Core or Rulespec Extrapolator. Updating or
removing that pin without migrating those consumers would hide a real
compatibility break.

Ordinary tests do not read a sibling Rulespec checkout or run the retired
combined proof. They validate dependency-manifest mutations against local test
inputs. Current source readers and ELSST do not export data to Rulespec.

## Executable package

RefSpec carries one JSON-compatible CUE source for REF-owned structures. It
generates JSON Schema 2020-12 and Python record types and fails the test gate
if either output drifts. The `refspec` package supplies canonical digest,
binding-validation, immutable vocabulary-record, and combined
RefSpec/Rulespec release-graph interfaces.
The generated package embeds the exact REF schemas, conformance fixtures, and
requirement-to-test manifest, so a wheel-installed `refspec-validate` can run
the same no-argument conformance suite without a source checkout.

Run `make test` from this repository to check generated artifacts, all valid
and invalid REF fixtures, and the Python package. The gate is standalone and
does not read a sibling Rulespec checkout.

The [Federal Register vocabulary policy](docs/federal-register-vocabulary-policy.md)
packages the exact April 1, 2025 thesaurus as the default candidate vocabulary
for Federal Register documents. The checked source extract and ordinary tests
are offline. The real-data audit rebuilds them from the exact pinned 2025 PDF.
The superseded 1995 reader, crosswalk, and historical gate have been removed.
`make test` remains offline. Git contains the deterministic semantic extract
for the current thesaurus; the native PDF remains in the managed release
output.
