# Atlas distribution projection and access

## Purpose

`atlas_distribution_projection_and_access` converts Atlas records into verified, read-optimized data without changing their meaning.

- `atlas_record_projection` normalizes the eight closed Atlas record roles and writes typed Apache Parquet tables.
- View builders verify schemas, row counts, file digests, and closed directory membership.
- `atlas_serving_views` authenticates the compact Parquet view before exposing disposable DuckDB queries, graph APIs, and deterministic explorer files.

The asserted Resource Description Framework (RDF) distribution remains canonical. Agency projections stay separate, and derived relations remain optional and non-authoritative.

## Architecture

```mermaid
flowchart LR
    BUILD["Atlas distribution builder"]
    RDF["Canonical asserted RDF distribution"]

    subgraph TARGET["atlas_distribution_projection_and_access"]
        NORMALIZE["Normalize logical records<br/>compact_pack.py"]
        TABLES["Write eight typed tables<br/>parquet_tables.py"]
        FULL["Verify full Parquet view<br/>parquet_view.py"]
        COMPACT["Build and verify compact search view<br/>parquet_search_view.py"]
        DUCK["Open disposable DuckDB view<br/>duckdb_view.py"]
        SHARDS["Build deterministic explorer shards"]
    end

    QUERY["SQL, PyArrow, and graph responses"]
    BROWSER["Local Atlas explorer"]

    BUILD --> RDF
    BUILD --> NORMALIZE --> TABLES --> FULL --> COMPACT
    RDF -. "parity and manifest checks" .-> FULL
    COMPACT --> DUCK --> QUERY
    DUCK --> SHARDS --> BROWSER
```

The normal access path verifies the compact view against a trusted manifest digest before creating any query state. DuckDB databases, full-text indexes, HTTP responses, and browser shards remain replaceable views of the authenticated Parquet files.

```mermaid
flowchart TB
    subgraph PROJECTION["atlas_record_projection"]
        RECORDS["compact_pack.py<br/>roles and normalization"]
        TABLES["parquet_tables.py<br/>schemas and writers"]
        VIEW["parquet_view.py<br/>manifest and verification"]

        RECORDS --> TABLES --> VIEW
    end

    SEARCH["parquet_search_view.py<br/>compact-view builder and verifier"]

    subgraph ACCESS["atlas_serving_views"]
        DUCK["AtlasDuckDBView<br/>verified query session"]
        DATA["AtlasExplorerData<br/>storage-neutral read interface"]
        ADAPTER["explorer.py and explorer_render.py<br/>models and static shards"]
        HTTP["explorer_cli.py and explorer_frontend.py<br/>local HTTP and browser"]

        DUCK -. "implements" .-> DATA
        DUCK --> ADAPTER
        DATA --> HTTP
        ADAPTER --> HTTP
    end

    VIEW --> SEARCH --> DUCK
```

## Core component documentation

| Component | Responsibility | Documentation |
| --- | --- | --- |
| `atlas_record_projection` | Defines, normalizes, and writes the eight typed Atlas record tables. | [Atlas record projection](atlas_record_projection.md) |
| `atlas_serving_views` | Verifies compact views and provides DuckDB, graph, HTTP, and static-browser access. | [Atlas serving views](atlas_serving_views.md) |
| Parquet artifact format | Defines view manifests, schemas, integrity checks, and sealing behavior. | [Atlas 3.1 Parquet view](../docs/atlas-parquet-view.md) |
| Atlas distribution rules | Defines the normative graph roles and independent validation requirements. | [Atlas 3.1 binding](../bindings/atlas/3.1/README.md) |
| Architectural decisions | Records authority, ownership, and cross-product boundaries. | [Decision ledger](../docs/decisions.md) |