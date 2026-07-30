# RefSpec

RefSpec is the standalone home of the Regulatory Evidence Framework (REF), an
evidence-first specification for acquiring, preserving, processing, enriching,
and publishing auditable regulatory information.

RefSpec is an unpublished editor's draft. The repository makes no W3C
endorsement claim. No license has been selected, so publication does not grant
permission beyond rights supplied by applicable law.

## Documents

- [RefSpec 1.0 editor's draft](spec/refspec.md)
- [Rulespec application profile](profiles/rulespec-application-profile.md)
- [Core enrichment profile](profiles/enrichment-profile.md)
- [REF JSON Binding 1.0](bindings/json/1.0/README.md)
- [Authoritative REF structural model](model/README.md)
- [Active managed vocabulary experiment roadmap](plans/managed-vocabulary-experiment-roadmap.md)
- [Implemented vocabulary management and lookup separation baseline](plans/vocabulary-management-lookup-separation-plan.md)
- [Completed vocabulary gap closure plan](plans/vocabulary-gap-closure-plan.md)
- [Historical conceptual implementation plan](plans/implementation-plan.md)
- [Research-input register](docs/research-inputs.md)
- [Research archive](research/README.md)

## Planning status

The managed vocabulary experiment roadmap defines current execution. It keeps
daily research in a lightweight, candidate-only experiment lane and applies
the full RefSpec and Rulespec release process only when a result enters the
promotion lane.

The vocabulary gap closure and management-separation plans record completed
local baselines. The early implementation plan remains available as a
capability inventory; it no longer controls delivery sequence or scope.

## Ownership boundary

RefSpec owns operational acquisition, processing, portfolio accounting,
vocabulary import and deployment, evaluation, publication, and extension
behavior. It is the source of truth for the managed releases that REF imports,
reconciles, selects, and serves. Native publishers remain authoritative for
their source distributions.

[Rulespec](https://github.com/Formspec-Labs/rulespec) owns reusable semantic
records and their portable constraints. RefSpec binds to Rulespec through an
application profile; it does not duplicate Rulespec classes or validation
rules.

Implementations and research projects remain consumers of RefSpec. The dated
research snapshots used to develop this editor's draft are archived under
[`research/`](research/README.md). They are nonnormative except where the
specification explicitly identifies a portfolio baseline.

## Current dependency state

The editor's draft targets the local Rulespec `0.2.0-pre.9` candidate. The
tested Rulespec source revision is
`0eb94257b70783688b55220e7a84dcc61bbd7507`; the evidence revision is
`2c66a85daab30a4869db08d21cea13cfc865b3a0`; and the constraint digest is
`sha256:8feadf8f4037a60a18667c6f7ee920ff1285ccb05a72fe5352b6cd82b38a252c`.
The machine-readable
[Rulespec dependency manifest](profiles/rulespec-dependency.json) records the
complete executable pin. That candidate has not been published to the
Rulespec remote, so RefSpec does not make a production conformance claim.

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
`make test-cross-repository` when the exact sibling Rulespec checkout is
available.

`make test-real-vocabulary` is a separate, explicitly networked regression.
It downloads the pinned 16 November 1995 Federal Register thesaurus into a
temporary content-addressed store, rejects any SHA-256 mismatch, runs the
full-source RefSpec and Rulespec tests, selects the exact managed release for
candidate lookup under project-local development authority, opens it through
the digest-verifying reference reader, and proves that a later append-only
rollback restores the explicit prior empty selection. The active bundle and
rollback history remain separate. This selection grants no accepted-output,
publisher, legal-clearance, or production authority.

The command removes the temporary source bytes on exit. The default
`make test` remains offline, and native vocabulary bytes never enter Git.
