# RefSpec

RefSpec manages controlled-vocabulary source packages, verified releases,
crosswalk evidence, and static vocabulary atlas assets. It preserves exact
source material and publishes digest-pinned files that other products can
verify without importing this source tree or querying a RefSpec service.

RefSpec is an unpublished editor's draft. The repository makes no W3C
endorsement claim. No license has been selected, so publication does not grant
permission beyond rights supplied by applicable law.

## Documents

- [Vocabulary Atlas Distribution 3.0 — normative consumer format](bindings/atlas/3.0/README.md)
- [Atlas Parquet view and explorer](docs/atlas-parquet-view.md)
- [Atlas source-fidelity issues and priorities](docs/atlas-source-fidelity-issues.md)
- [Atlas in the United States and Europe — landscape comparison](ATLAS_US_EU_COMPARISON.md)
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

Atlas 3.0 is the current, greenfield binding. It publishes exact source
releases, normalized resources, labels, identifiers, evidence, and assertions
in immutable, digest-pinned packs. The manifest keeps authoritative assertions,
reproducible projections, and non-authoritative derived relations in distinct
graph roles.

The full-development generator reads pinned publisher distributions and
versioned registry caches. It does not consume an Atlas 1.0 or 2.0 graph. See
the [Atlas 3.0 binding](bindings/atlas/3.0/README.md) for the distribution,
validation, and consumer requirements.

### Atlas source-fidelity development audit

`make audit-atlas-v3-source-fidelity` compares selected Atlas asserted packs
directly with immutable snapshots of their exact, digest-pinned publisher bytes
and writes a receipt beside the distribution. It uses stock RDF and Parquet
readers, plus the shared byte-pin checker; it does not import the producer's
semantic readers or builders. Narrow inverse rules convert recorded Atlas source
evidence back into publisher-shaped claims before direct comparison. Every
independent input and check that can still run continues after an error, so the
receipt retains all recoverable findings.

The audit compares only data attributable to publisher inputs: identifiers,
literals in every language and datatype, source-native memberships and scheme
claims, top-concept claims, relations, reified statements, provenance, and direct
native-control values. It accounts in both directions: an unhandled publisher
claim and an unowned source-shaped Atlas claim both fail. Atlas-owned release
nodes, semantic rings, resource profiles, governed schemes, class assignments,
and named-graph placement are outside its scope. Publisher defects are reported
separately and do not fail fidelity when Atlas preserves them unchanged.

The current verifier covers 23 of the default candidate's 110 construction
units. All 14 covered native-control units match exactly; all nine covered RDF
vocabulary or mapping units have differences. The remaining 87 units are
explicit failures, not assumed matches. Set `ATLAS_V3_AUDIT_ROOT` to audit
another completed build. Do not claim full Atlas source fidelity until
`uncoveredUnits` is empty, every construction unit has `"status": "exact"`,
every check passes, and the receipt records `"passed": true`.

Atlas 1.0 and 2.0 remain historical formats. New producers and consumers must
target Atlas 3.0. The
[U.S. and European landscape comparison](ATLAS_US_EU_COMPARISON.md) explains
Atlas's intended public role and the systems it complements.

The dated research snapshots used to develop the editor's draft are archived
under [`research/`](research/README.md). They are nonnormative except where the
specification explicitly identifies a portfolio baseline.

## Dependency boundary

RefSpec builds and verifies releases from pinned files. The checked
[`RulespecCoreRelease`](profiles/rulespec-core-dependency.json) is a fixture,
so it supports tests rather than a production conformance claim. Ordinary
tests are standalone: they do not read a sibling Rulespec checkout, a sibling
source tree, or a mutable external database.

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
