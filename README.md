# RefSpec

RefSpec publishes managed ontology and vocabulary releases. It captures an
external vocabulary distribution, records the managed publication decision,
resolves exact source-term keys, and exposes the complete Rulespec Core
reference release used by downstream concept assignments.

RefSpec does not acquire documents, preserve document observations, execute
extrapolation, or rank search results. Those responsibilities belong to
SpicyRegs, Rulespec, and SpicySearch.

## Implemented first slice

This repository contains a self-contained Python package that builds and
validates a sealed first-slice fixture from the April 1, 2025 Federal Register
Thesaurus. The fixture publishes five concepts for conformance testing. It does
not claim to publish the complete 705-concept source vocabulary.

The package provides:

- canonical JSON and content-derived release identifiers;
- `VocabularyRelease` and `VocabularyCoverage` records;
- an exact, complete Rulespec Core `ReferenceResourceRelease` projection;
- `SourceTermKey` and closed-state `SourceTermResolution` records;
- `AgentValidationReceipt` and `BaselineValidationReceipt` records;
- positive examples for all four Lists of Subjects resolution states; and
- fail-closed validation for digests, references, membership, and target
  cardinality.

The build uses package-local, digest-pinned fixtures. It never reads another
repository checkout or a mutable database.

The current Rulespec Core pin is an exact package-local copy of
`rulespec-core-release-m2.json`, release `5ac6ba59…`. The package also copies
the Core `ReferenceResourceRelease` schema and digest vector exactly. The Core
release's declared status is `fixture`; replace it with a published release
before publishing a production RefSpec release.

## Build and test

Python 3.11 or later is required.

```sh
pytest -q
python -m refspec.cli --output build/federal-register-2025-first-slice.json
```

When the package is not installed, add `PYTHONPATH=src` to the builder command.
Repeated builds produce identical canonical bytes and the same release digest.
The checked-in release artifact is
`release-records/fixtures/refspec-vocabulary-release-federal-register-2025-first-slice.json`.

The conformance fixture includes two independent example validator receipts.
They demonstrate receipt structure and reduction logic; they are not claims of
production validation or release promotion.

## Product boundary

The current boundary and its four-product ownership map are recorded in
[`docs/decisions.md`](docs/decisions.md). The normative RefSpec behavior is in
[`spec/refspec.md`](spec/refspec.md).

This implementation is local and unreleased.

RefSpec is an independent project draft, not a W3C standard. The repository
has no selected license; public visibility does not grant rights beyond
applicable law. Historical research and superseded design drafts remain in
`research/`, `profiles/`, and `plans/` as nonnormative lineage.
