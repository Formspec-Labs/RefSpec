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
- [Implementation plan](plans/implementation-plan.md)
- [Vocabulary gap closure plan](plans/vocabulary-gap-closure-plan.md)
- [Research-input register](docs/research-inputs.md)
- [Research archive](research/README.md)

## Ownership boundary

RefSpec owns operational acquisition, processing, portfolio accounting,
evaluation, publication, and extension behavior.

[Rulespec](https://github.com/Formspec-Labs/rulespec) owns reusable semantic
records and their portable constraints. RefSpec binds to Rulespec through an
application profile; it does not duplicate Rulespec classes or validation
rules.

Implementations and research projects remain consumers of RefSpec. The dated
research snapshots used to develop this editor's draft are archived under
[`research/`](research/README.md). They are nonnormative except where the
specification explicitly identifies a portfolio baseline.

## Current dependency state

The editor's draft targets Rulespec `0.2.0-pre.8`, local revision
`c330aef9a7e13c59929631b7b7ba0c6869a57c22`, and constraint digest
`sha256:71250f67b81fd54af3f6e6c45f2100f9a2307da589b364593e6708e5674b7172`.
That Rulespec revision has not yet been published to its remote repository, so
RefSpec does not yet make a production conformance claim.
