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

## Fast development preflight

The authenticated columnar preflight catches common whole-distribution
failures without reconstructing the 30-million-quad RDFLib graph:

```sh
uv run refspec-validate-atlas-parquet \
  --distribution output/atlas-3.0-full-2026-08-06/distribution \
  --distribution-manifest-digest 9b5d6392a993815070471734e8fea77f60e0973bdba6d05f66be11af805a1f24 \
  --view output/atlas-3.0-parquet-view-2026-08-07 \
  --view-manifest-digest 1b0839f51a80e8d66cff31905b87306127aefebe6f936107850f1e9677700197
```

It authenticates the Parquet view and verifies the supplied Atlas manifest,
supporting members, RDF transports, and pack inventory. It then confirms that
the view pins that source metadata before checking manifest counts, logical
record identities, release and source-record closure, label provenance and
uniqueness, identifier uniqueness, statement endpoints and ring context, and
immutable evidence coverage. Compact-pack bytes are authenticated while the
view is built; this preflight does not reread them. A full development view
with 3,302,340 logical records completed the columnar semantic checks in 7.8
seconds after the 2026-08-08 scan consolidation.

This command is a fast development gate, not the Atlas 3 release verdict. Its
JSON result lists the remaining release-only checks: closed JSON schemas and
binding pins; producer and acceptance receipts; normative SHACL; RDF lexical,
graph-role, dependency, and node-digest rules; assertion policy, identity, and
lifecycle semantics; projection and derived replay; transitive SKOS conflict
analysis; source-accounting reconciliation; compact-to-RDF sampling; and
reasoning isolation. Run the independent Atlas validator before calling a
distribution conformant.

The retired exhaustive compact-to-RDF parity implementation remains available
through the [dated archive note](../research/archive/atlas-3.0-exhaustive-compact-parity-2026-08-08.md).
The active release validator authenticates every compact row, reconciles exact
record counts, and compares a bounded deterministic sample with RDF.

## Compact search profile

The separately named compact search view retains compressible native text
references and removes reconstructable row-integrity fields. It retains labels,
graph facts, source digests and locators, review decisions, and methods needed
for search explanations. It omits source-native payload bodies and redundant
digests or identifiers whose values are either reconstructed from a retained
identifier or used only to authenticate the pinned full view. Those omitted
values remain in the pinned full view and canonical RDF.

Search view 1.1 carries the canonical `Label.id` in the Label table's `id`
column, copied from the pinned full view (REF-025). The manifest states
`schemaVersion: 1.1`, `Label.id` is absent from `status.omittedFields`, and
verification refuses a Label member without that column and refuses a manifest
naming another schema version.

```sh
uv run refspec-build-atlas-search-view \
  --full-view output/atlas-3.0-parquet-view-2026-08-10 \
  --expected-manifest-sha256 cd712aacc0308594e6cad77be327b482779a3fb4cc93dacd7d0c6bb04d1d5207 \
  --output output/atlas-3.0-parquet-search-view-2026-08-11
```

The 2026-08-11 compact development view contains the same 3,288,830 role rows,
984,114 of them labels, in 224,874,647 bytes across nine files (about 214 MiB).
Its manifest SHA-256 is
`cf645ad8316875b43735561ec2910cf42fd05cf90961dcde2c59c0fdce59759d` and its view
identifier is
`urn:ref:atlas-parquet-search-view:6e2489f0124ffa7e0c1f508452a449057e05de376b4e02b88778581d59786446`.
The label identifier costs 30,887,361 bytes on this data: `tables/labels.parquet`
is 74,779,216 bytes against 43,891,855 in the 1.0 view built from the same full
view, and the members total 224,869,901 bytes against 193,982,540.

## Explore the data

The reusable `refspec.atlas.duckdb_view` package verifies the compact view and
then opens named DuckDB views over its Parquet members:

- `atlas_resources`;
- `atlas_labels`;
- `atlas_statements`;
- `atlas_evidence_bindings`;
- `atlas_source_records`;
- `atlas_releases`;
- `atlas_identifiers`; and
- `atlas_lifecycle_events`.

The package exposes parameterized row and Arrow queries as well as the
`facets()`, `search()`, and `resource()` operations used by the explorer. This
keeps DuckDB independent of the user interface, so a notebook or another local
consumer can use the same verified tables without importing explorer code.

```python
from refspec.atlas import open_atlas_duckdb_view

with open_atlas_duckdb_view(
    "output/atlas-3.0-parquet-search-view-2026-08-11",
    trusted_manifest_digest="sha256:cf645ad8316875b43735561ec2910cf42fd05cf90961dcde2c59c0fdce59759d",
) as atlas:
    rows = atlas.query_rows(
        "SELECT id, definition FROM atlas_resources WHERE semantic_ring = ? LIMIT 20",
        ("subject",),
    )
```

The explorer searches labels, aliases, notations, identifiers, definitions,
and resource IRIs; filters resources and relations; and opens provenance
details without parsing the RDF packs.

```sh
uv run refspec-atlas-explorer \
  output/atlas-3.0-parquet-search-view-2026-08-11 \
  --manifest-digest cf645ad8316875b43735561ec2910cf42fd05cf90961dcde2c59c0fdce59759d
```

The command opens `http://127.0.0.1:8000/`. DuckDB reads ordinary graph queries
from Parquet. On the first nonblank search, it creates a disposable local table
and a native BM25 full-text index outside the verified directory. The measured
588,409-resource development view produced a roughly 117 MiB temporary DuckDB
file. The server removes that file when it closes; it is not a released Atlas
member or another source of truth.

DuckDB full-text search uses its official `fts` extension. DuckDB may download
that extension on first use, after which the local cache supports offline use.
The explorer reports a clear error if the extension is unavailable; it does not
silently substitute a different ranking rule.

The full RDF graph explorer can retain its asserted, projection, and derived
authority layers while delegating only ranked text search to this query package:

```sh
uv run refspec-atlas-explorer \
  output/atlas-3.0-full-2026-08-06/atlas-explorer-preview.html \
  --search-view output/atlas-3.0-parquet-search-view-2026-08-11 \
  --manifest-digest cf645ad8316875b43735561ec2910cf42fd05cf90961dcde2c59c0fdce59759d
```

The server rejects an RDF preview and compact view that pin different Atlas
distribution IDs or manifest digests. Omitting `--search-view` retains the
verified static-shard search from REF-018 and requires no database service.

Use `--no-browser` when the caller manages the browser, and use `--port 0` to
select an available port.

DuckDB is a local query implementation, not an Atlas publication format.
Canonical RDF, the verified Parquet input, and SpicySearch's product search and
ranking responsibilities remain unchanged.
