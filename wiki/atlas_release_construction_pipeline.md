# Atlas release construction pipeline

## Purpose

`atlas_release_construction_pipeline` converts selected, digest-pinned source releases into a deterministic Atlas 3.1 candidate distribution.

Its three core components divide the work:

1. `atlas_registry_loading` verifies selected publisher inputs and converts them into normalized `RegistryRelease` values.
2. `atlas_derived_graph` computes optional, evidence-bearing relationships from asserted source facts. These relationships remain non-authoritative and opt-in.
3. `atlas_distribution_builder` validates normalized inputs, constructs asserted Resource Description Framework (RDF) records, writes canonical packs and receipts, and optionally creates an adjacent Parquet query view.

The pipeline produces a producer-checked candidate. Independent Atlas 3.1 validation, source-fidelity auditing, signing, and publication remain separate operations.

## Architecture

```mermaid
flowchart LR
    PINNED["Digest-pinned<br/>publisher inputs"]
    OTHER["Other managed and<br/>mapping releases"]

    subgraph PIPELINE["atlas_release_construction_pipeline"]
        LOAD["atlas_registry_loading<br/>select, verify, and normalize"]

        subgraph BUILDER["atlas_distribution_builder"]
            PREBUILD["Prebuild checks<br/>identity, scope, counts, and policy"]
            SPOOL["Bounded construction<br/>asserted RDF and record spools"]
            WRITE["Sort, compress, and write<br/>packs, receipts, and manifests"]
        end

        DERIVE["atlas_derived_graph<br/>replayable derived relations"]

        LOAD --> PREBUILD --> SPOOL
        SPOOL --> WRITE
        SPOOL --> DERIVE --> WRITE
    end

    PINNED --> LOAD
    OTHER --> PREBUILD
    WRITE --> DIST["Candidate Atlas 3.1<br/>distribution"]
    WRITE --> PARQUET["Optional adjacent<br/>Parquet view"]
```

The builder coordinates the runtime sequence:

```mermaid
sequenceDiagram
    actor Caller
    participant B as Distribution builder
    participant L as Registry loading
    participant D as Derived graph
    participant V as Atlas 3.1 validator

    Caller->>B: Output path and selected release keys
    B->>L: Load selected pinned inputs
    L-->>B: Normalized RegistryRelease values
    B->>B: Validate inputs and stream asserted records

    opt Required releases activate a rule
        B->>D: Canonical asserted facts and evidence digests
        D-->>B: Sorted DerivedRelationRow values and counts
    end

    B->>B: Write packs, receipts, manifests, and optional Parquet
    B-->>Caller: Producer-checked candidate
    Caller->>V: Validate serialized distribution independently
    V-->>Caller: Independent conformance verdict
```

Asserted RDF is the distribution’s authoritative content. Derived relations occupy a separate graph and table, cite their input evidence, and require consumer opt-in. The portable validator does not import producer code, preventing the builder from defining its own acceptance result.

## Core component documentation

- [Atlas registry loading](atlas_registry_loading.md) — release selection, exact-input verification, source normalization, and `RegistryRelease` construction.
- [Atlas derived graph](atlas_derived_graph.md) — derivation rules, evidence, identities, graph authority, replay, and consumer access.
- [Atlas distribution builder](atlas_distribution_builder.md) — prebuild checks, streamed RDF construction, pack writing, receipts, manifests, and Parquet generation.
- [Atlas 3.1 binding](../bindings/atlas/3.1/README.md) — normative distribution format and independent validation rules.