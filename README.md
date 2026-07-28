# RefSpec

RefSpec is the standalone home of the Regulatory Evidence Framework (REF), an
evidence-first specification for acquiring, preserving, processing, enriching,
and publishing auditable regulatory information.

RefSpec is an unpublished editor's draft. The repository is private, its
publication terms have not been selected, and it makes no W3C endorsement
claim.

## Documents

- [RefSpec 1.0 editor's draft](spec/refspec.md)
- [Rulespec application profile](profiles/rulespec-application-profile.md)
- [Implementation plan](plans/implementation-plan.md)
- [Research-input register](docs/research-inputs.md)

## Ownership boundary

RefSpec owns operational acquisition, processing, portfolio accounting,
evaluation, publication, and extension behavior.

[Rulespec](https://github.com/Formspec-Labs/rulespec) owns reusable semantic
records and their portable constraints. RefSpec binds to Rulespec through an
application profile; it does not duplicate Rulespec classes or validation
rules.

Implementations and research projects remain consumers of RefSpec. Their
source inventories, controlled-resource research, and product-specific
architectures are not copied into this repository.

## Current dependency state

The editor's draft targets Rulespec `0.2.0-pre.8`, local revision
`c330aef9a7e13c59929631b7b7ba0c6869a57c22`, and constraint digest
`sha256:71250f67b81fd54af3f6e6c45f2100f9a2307da589b364593e6708e5674b7172`.
That Rulespec revision has not yet been published to its remote repository, so
RefSpec does not yet make a production conformance claim.
