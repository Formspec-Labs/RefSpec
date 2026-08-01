# RefSpec

RefSpec manages controlled-vocabulary source packages, verified releases,
crosswalk evidence, and static vocabulary atlas assets. It preserves exact
source material and publishes digest-pinned files that other products can
verify without importing this source tree or querying a RefSpec service.

RefSpec is an unpublished editor's draft. The repository makes no W3C
endorsement claim. No license has been selected, so publication does not grant
permission beyond rights supplied by applicable law.

## Documents

- [RefSpec managed vocabulary release specification](spec/managed-vocabulary-release.md)
- [Historical RefSpec 1.0 editor's draft](spec/refspec.md)
- [Rulespec application profile](profiles/rulespec-application-profile.md)
- [Core enrichment profile](profiles/enrichment-profile.md)
- [REF JSON Binding 1.0](bindings/json/1.0/README.md)
- [Vocabulary Atlas Distribution 1.0](bindings/atlas/1.0/README.md)
- [Authoritative REF structural model](model/README.md)
- [Active managed vocabulary experiment roadmap](plans/managed-vocabulary-experiment-roadmap.md)
- [Active Spicy Regs controlled-resource import plan](plans/active-profile-controlled-resource-import-plan.md)
- [Completed controlled-resource package inventory](portfolio/completed-controlled-resource-packages-v1.json)
- [Deferred standards composition and graph extensibility plan](plans/standards-composition-and-graph-extensibility-plan.md)
- [Implemented vocabulary management and lookup separation baseline](plans/vocabulary-management-lookup-separation-plan.md)
- [Completed vocabulary gap closure plan](plans/vocabulary-gap-closure-plan.md)
- [Historical conceptual implementation plan](plans/implementation-plan.md)
- [Research-input register](docs/research-inputs.md)
- [Decision ledger](docs/decisions.md)
- [Reconciliation runbook](docs/reconciliation-runbook.md)
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

The active-profile import plan expands that roadmap across every current Spicy
Regs source profile. It builds and compares the RefSpec-managed resource
portfolio before Spicy Regs expands profile-aware lookup.

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

Published, digest-pinned files connect these products. Each consumer verifies
the files and may build a disposable local index. It does not import another
product's source tree or depend on that product's mutable database.

`refspec-build-vocabulary-atlas` builds the two-graph static asset from exact
managed-release and Rulespec Core file pins. An optional canonical crosswalk
file supplies closed evidence and machine-validation receipts. A `searchOnly`
mapping requires two validators with distinct actors, independence groups,
providers, provider model IDs, and responses; human review is not a prerequisite.
The command prints the manifest and N-Quads digests that a consumer must pin.

Consumers call `VocabularyAtlasAsset.open` with only the atlas directory and
those two external digests. Publishers may call `reproduce_from_inputs` to
reopen every exact source and rebuild both files byte for byte. The checked
Federal Register example proves that the specialized, source-complete 2025
package can publish all 705 concepts through this same file format; it does not
introduce another release model.

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

Ordinary tests do not run that retired combined proof against the current
split Rulespec checkout. They skip it with the exact required revision in the
reason. Maintainers can still run the historical proof by setting
`RULESPEC_DIR` to a clean checkout at the pinned evidence revision. The current
`test-cross-repository` target verifies the Core and static-atlas file seam;
`test-legacy-rulespec-combined` is the explicit historical gate.

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
and invalid REF fixtures, and the Python package. Run
`make test-cross-repository` to check the current Rulespec Core and static-atlas
file seam. Use `make test-legacy-rulespec-combined` only with the exact clean
historical Rulespec checkout named above.

The [Federal Register vocabulary policy](docs/federal-register-vocabulary-policy.md)
packages the exact April 1, 2025 thesaurus as the default candidate vocabulary
for Federal Register documents. The checked source extract, crosswalk, and
ordinary tests are offline. Optional gates rebuild them from the exact pinned
PDF.

`make test-real-vocabulary` remains a separate, explicitly networked
historical regression. It downloads the pinned November 16, 1995 source,
rejects any SHA-256 mismatch, exercises the former development selection path,
and proves its rollback. That edition is not candidate-authorized in the
active portfolio; it remains only for historical lookup, regression tests,
and vocabulary-change analysis.

The command removes the temporary source bytes on exit. The default
`make test` remains offline. Git contains the deterministic semantic extract
and crosswalk; the native PDF remains in the managed release output.
