# Atlas 3.0 Parquet view

The Atlas Parquet view is a derived, queryable representation of every closed
logical record in an exact Atlas 3.0 distribution. The asserted RDF remains the
canonical Atlas. The view contains no exact RDF table and grants no search or
expansion permission.

## What goes in

The builder requires:

- one closed Atlas 3.0 distribution;
- an external SHA-256 pin for `atlas-manifest.json`; and
- the authenticated compact logical-record inventory sealed by the Atlas
  construction summary.

The builder verifies the manifest pin, canonical JSON identities, asserted
graph inventory, every root member and RDF-pack transport, closed file
membership, and every compact pack before writing output.

## What comes out

The immutable output contains typed Parquet tables for:

- resources;
- labels;
- statements;
- evidence bindings;
- source records, including canonical source-native payloads;
- releases;
- identifiers; and
- lifecycle events, including an explicit zero-row table when Atlas declares
  no events.

`view-manifest.json` pins the input Atlas manifest, canonical payload, asserted
inventory, binding, ontology, construction summary, compact inventory, table
schemas, row counts, byte lengths, and file digests. It states
`expansion: not_used`, `canonicalAtlas: false`, and
`containsExactRdfTable: false`.

## Build and verify

```sh
uv run refspec-build-atlas-parquet-view \
  --distribution output/atlas-3.0-full-2026-08-06/distribution \
  --expected-manifest-sha256 9b5d6392a993815070471734e8fea77f60e0973bdba6d05f66be11af805a1f24 \
  --output output/atlas-3.0-parquet-view-2026-08-07

uv run refspec-build-atlas-parquet-view \
  --verify-only \
  --output output/atlas-3.0-parquet-view-2026-08-07 \
  --expected-manifest-sha256 1b0839f51a80e8d66cff31905b87306127aefebe6f936107850f1e9677700197
```

The measured development build contains 3,288,830 logical records in
398,406,021 bytes (about 380 MiB), compared with 1.0 GB for the complete source
distribution. This is the full
logical-record profile: source-native payloads and evidence bindings remain in
the view.

## Compact search profile

The separately named compact search view retains compressible native text
references and removes reconstructable row-integrity fields. It retains labels,
graph facts, source digests and locators, review decisions, and methods needed
for search explanations. It omits source-native payload bodies and redundant
digests or identifiers whose values are either reconstructed from a retained
identifier or used only to authenticate the pinned full view. Those omitted
values remain in the pinned full view and canonical RDF.

```sh
uv run refspec-build-atlas-search-view \
  --full-view output/atlas-3.0-parquet-view-2026-08-07 \
  --expected-manifest-sha256 1b0839f51a80e8d66cff31905b87306127aefebe6f936107850f1e9677700197 \
  --output output/atlas-3.0-parquet-search-view-2026-08-07
```

The measured compact development view contains the same 3,288,830 role rows in
175,586,262 bytes (about 167 MiB; 170 MB allocated on the build machine). Its
manifest SHA-256 is
`b2a8144a462a206ef283af44a5fdcd46449d15044a702c8dc0c77f07427f0d1c`.

## Explore the data

The Atlas explorer reads this compact view directly. It searches labels and
identifiers, filters resources and relations, and opens provenance details from
the Parquet-derived browser files. It does not reopen or parse the RDF packs.

```sh
uv run refspec-atlas-explorer \
  output/atlas-3.0-parquet-search-view-2026-08-07 \
  --manifest-digest b2a8144a462a206ef283af44a5fdcd46449d15044a702c8dc0c77f07427f0d1c
```

The command opens `http://127.0.0.1:8000/` and queries the Parquet tables in
place. It does not create another full-corpus copy. Use `--no-browser` when the
caller manages the browser, and use `--port 0` to select an available port.

The former RDF-backed implementation remains in
`refspec.atlas.explorer_rdf` for compatibility tests. It is not used by the
normal `refspec-atlas-explorer` command.
