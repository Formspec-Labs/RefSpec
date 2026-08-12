# RefSpec

RefSpec turns public-sector vocabularies — EuroVoc, the Library of Congress
Subject Headings, the Federal Register Thesaurus, and ~50 other government
term lists — into **one verified, immutable data product** (the "Atlas") that
other software can trust without trusting this repository.

The idea in four verbs:

1. **Build** — adapters read each publisher's exact, digest-pinned source
   bytes (SKOS, PDFs, APIs, spreadsheets) and construct one canonical RDF
   distribution plus a Parquet view for serving.
2. **Prove** — one independent validator checks the built artifact against
   the published contract (SHACL shapes and the [rkaf](docs/decisions.md)
   ontology): every label, identifier, cross-vocabulary mapping, and piece
   of evidence, once, at build time.
3. **Sign** — the release is sealed with a detached signature that binds the
   manifest *and* the acceptance receipt, so verifying the seal proves the
   checks actually ran on these exact bytes.
4. **Serve** — consumers (chiefly SpicySearch) verify the seal in under a
   second and read the Parquet view. Nobody re-derives anything, imports
   this source tree, or queries a RefSpec service.

Everything else in the repo exists to make those four verbs trustworthy: a
sealed conformance corpus (130 fixture cases), a source-fidelity auditor that
compares the Atlas back to the publishers' own bytes, and a
[decision ledger](docs/decisions.md) recording why each piece exists.

**Status:** unpublished editor's draft; no license selected; no W3C
endorsement claimed.

## Quick start

```sh
make test        # lint + generated-artifact checks + full suite (~2 min)
make test-atlas-v3   # the sealed conformance corpus (~30 s)

# Build, validate, and verify a real bounded release (~15 s):
make release-atlas-federal-register-thesaurus
make verify-atlas-federal-register-thesaurus
```

Tests are offline and standalone — no sibling checkouts, no network, no
mutable databases.

## The artifact

An Atlas distribution is a closed set of files: an `atlas-manifest.json`
pinning every member by digest, zstd-compressed canonical N-Quads packs
(sorted, byte-reproducible — two builds of the same inputs are
byte-identical), an acceptance receipt, and a source-accounting ledger. A
Parquet view (one table per record kind) is emitted from the same build and
covered by the same seal. The
[Atlas binding](bindings/atlas/3.1/README.md) is the normative consumer
contract; its validator deliberately imports nothing from this package, so a
consumer can copy that one directory and verify a distribution offline.

## Who owns what

RefSpec owns vocabulary acquisition, release validation, crosswalk evidence,
and Atlas publication. Publishers stay authoritative for their sources.
Rulespec owns the shared semantic contract (the rkaf ontology and its
constraints, consumed here as a versioned package). SpicySearch owns search
and serving. Products exchange only published, digest-pinned files —
never source trees or live databases
([REF-024](docs/decisions.md)).

## Where things are

| | |
|---|---|
| Consumer contract | [`bindings/atlas/3.1/`](bindings/atlas/3.1/README.md) |
| Builder | `tools/generate_atlas_v3_full.py` |
| Independent validator | `bindings/atlas/3.1/tools/validate.py` |
| Seal | `src/refspec/seal.py` + [design](docs/seal-design.md) |
| Source-fidelity auditor | `tools/verify_atlas_source_fidelity.py` |
| Publisher adapters | `src/refspec/registry/` |
| Decision ledger (why) | [`docs/decisions.md`](docs/decisions.md) |
| Active plan (what's next) | [`plans/validation-cost-reset-plan.md`](plans/validation-cost-reset-plan.md) |
| US/EU landscape context | [`ATLAS_US_EU_COMPARISON.md`](ATLAS_US_EU_COMPARISON.md) |

## What the seal does and does not prove

Verifying a seal proves the distribution's bytes are exactly what passed the
independent validator's 13 acceptance gates. It does **not** prove the
captures were complete (leg 1) or that the Atlas faithfully transcribes the
publishers (leg 2) — leg 2 is the fidelity auditor's job, run on a schedule,
not at read time:

```sh
make audit-atlas-v3-source-fidelity ATLAS_V3_AUDIT_ROOT=<distribution>
```

The auditor reads the publishers' pinned bytes with stock parsers, converts
Atlas evidence back into publisher-shaped claims, and fails in both
directions — an unhandled publisher claim and an unowned Atlas claim are
each findings. Coverage is per-build, read from the receipt; uncovered units
are explicit failures, never assumed matches.

## History

Atlas 1.0/2.0 and the earlier RefSpec editor's-draft machinery are retired;
git history is the archive and the
[decision ledger](docs/decisions.md) records each retirement
(REF-015 through REF-028). Dated research lives under
[`research/`](research/README.md), nonnormative.
