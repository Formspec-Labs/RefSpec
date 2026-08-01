# RefSpec

> **Retired line — 1 August 2026.** This standalone RefSpec checkout is retired. The
> surviving implementation is the RefSpec submodule inside `spicy-regs`
> (`Formspec-Labs/RefSpec`, branch `main`). This line's unique content — the decision ledger
> `docs/decisions.md` (REF-001 through REF-006) and the managed-vocabulary
> `spec/refspec.md` — has been imported there. This line's history is archived in that
> repository under `refs/archive/refspec-standalone/main` and
> `refs/archive/refspec-standalone/pre-scrub-initial`. This checkout may be deleted once
> `docs/reconciliation-runbook.md` in the surviving repository has been executed.

RefSpec publishes managed ontology and vocabulary releases plus static,
query-ready cross-vocabulary atlas assets. It captures an external vocabulary
distribution, records the managed publication decision, resolves exact
source-term keys, generates and validates crosswalk candidates, and exposes the
complete Rulespec Core reference release used by downstream concept
assignments.

RefSpec generates deterministic vocabulary lookup projections. It does not
acquire documents, preserve document observations, execute document
extrapolation, answer live document queries, or rank search results. Those
responsibilities belong to SpicyRegs, Rulespec, and SpicySearch.

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
- a `VocabularyAtlasAsset` builder and read-only crosswalk/label queries;
- deterministic, blank-node-free N-Quads with exactly two named graphs and a
  canonical manifest;
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
uv sync --all-groups
uv run pytest -q
uv run refspec-build-federal-register-2025 \
  --output build/federal-register-2025-first-slice.json
```

Repeated builds produce identical canonical bytes and the same release digest.
The checked-in release artifact is
`release-records/fixtures/refspec-vocabulary-release-federal-register-2025-first-slice.json`.

The conformance fixture includes two independent example validator receipts.
They demonstrate receipt structure and reduction logic; they are not claims of
production validation or release promotion.

The atlas accepts one or more exact `VocabularyRelease` files and an optional
crosswalk bundle containing generated candidates and model/agent validation
receipts. A usable pinned baseline can qualify a candidate for `searchOnly`
without human approval. Optional human feedback is recorded separately and can
only affect a later immutable asset.

The atlas command writes `atlas.nq` and `atlas-manifest.json`. Consumers verify
and copy those files; they do not import RefSpec source or read a mutable
RefSpec database. Rebuild the checked-in single-release conformance asset with:

```sh
uv run refspec-build-vocabulary-atlas \
  --release release-records/fixtures/refspec-vocabulary-release-federal-register-2025-first-slice.json=sha256:78f3937141f0a2152225a05ee4018c4ce92f49e77c1d97a6f07064754231bee8 \
  --output-directory build/vocabulary-atlas
```

Pass `--crosswalk-bundle PATH=sha256:<digest>` to add sealed model/agent
candidates, validation receipts, and optional later feedback. The checked
single-release asset proves canonical generation and reload; focused tests seal
two-release crosswalk examples and the machine-first qualification path.

## Product boundary

The current boundary and its four-product ownership map are recorded in
[`docs/decisions.md`](docs/decisions.md). The normative RefSpec behavior is in
[`spec/refspec.md`](spec/refspec.md).

This implementation is local and unreleased.

RefSpec is an independent project draft, not a W3C standard. The repository
has no selected license; public visibility does not grant rights beyond
applicable law. Historical research and superseded design drafts remain in
`research/`, `profiles/`, and `plans/` as nonnormative lineage.
