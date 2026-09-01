# Publisher source portfolio and adapters

## Purpose

`publisher_source_portfolio_and_adapters` is a logical documentation umbrella over `src/refspec/atlas_index.py` and source-specific code under `src/refspec/registry/`. It is not a single Python package or aggregate API.

The source readers turn reviewed publisher artifacts into typed, traceable results for later RefSpec stages. Each reader applies the checks its source supports, such as origin, byte length, SHA-256 digest, media type, structure, identifiers, and counts. It preserves publisher meaning, provenance, scope limits, ambiguity, gaps, and explicit refusals. Supporting components provide narrowly scoped acquisition, transport, bridge, coverage, crosswalk, identity-review, and packaging workflows.

The planning index runs separately. It records non-authorizing resource placement across the `subject`, `entity`, `value`, and `legalIdentity` rings, hashes repository evidence, assigns content-derived identities, and requires every live registry module to be classified before generation succeeds.

A successful parse, package reopen, or planning row does not authorize Atlas admission, publication, or product use. Explicit loaders select source results; the source-fidelity audit independently compares publisher bytes with built claims; Atlas 3.1 validation checks the completed distribution in a separate step.

## Architecture

### Component map

```mermaid
flowchart TB
    ROOT["publisher_source_portfolio_and_adapters<br/>logical documentation umbrella"]
    ROOT --> PLAN["Atlas planning index<br/>content-addressed, non-authorizing placement"]
    ROOT --> ADAPT["Managed vocabulary source adapters<br/>acquisition, bridge, transport, and coverage"]
    ROOT --> VOCAB["Registry vocabulary sources"]
    ROOT --> CODES["Registry code and classification sources"]
    ROOT --> ORGS["Registry organization sources"]
    ROOT --> LEGAL["Registry legal and identifier sources"]
    ROOT --> CROSS["Registry crosswalk and package sources"]
```

### Processing and trust boundaries

```mermaid
flowchart LR
    PUB["Publisher artifacts<br/>RDF/SKOS, JSON/XML, HTML,<br/>PDF, CSV/XLSX, and API responses"]
    PINS["Reviewed declarations,<br/>byte pins, and evidence"]
    ACCESS["Cache, local file,<br/>or injected transport"]

    READ["Source-specific reader<br/>verify supported checks<br/>and parse native structure"]
    RESULT["Typed source view,<br/>assignment, gap, or refusal"]
    PACKAGE["Optional deterministic package<br/>or verified release input"]
    OTHER["Separate artifacts or evidence<br/>such as Unified Agenda Parquet"]
    LOAD["Explicit Atlas registry loaders"]
    BUILD["Atlas distribution builder"]
    VALIDATE["Independent Atlas 3.1 validation"]

    PLANINPUT["Resource catalog + planning input<br/>repository evidence + live module inventory"]
    INDEXBUILD["build_atlas_index()"]
    INDEX["atlas-index-v0.json<br/>non-authorizing plan"]
    AUDIT["Independent source-fidelity audit"]

    PUB --> READ
    PINS --> READ
    ACCESS -. "when supported" .-> READ
    READ --> RESULT
    RESULT -->|"when package-backed"| PACKAGE
    RESULT -->|"when explicitly selected"| LOAD
    PACKAGE --> LOAD
    RESULT -->|"separate output or retained evidence"| OTHER
    LOAD --> BUILD
    BUILD -. "separate step" .-> VALIDATE

    PLANINPUT --> INDEXBUILD --> INDEX
    INDEX -. "placement and drift checks,<br/>not admission" .-> BUILD

    PUB -. "independent reread" .-> AUDIT
    BUILD -. "built claims and receipts" .-> AUDIT
```

No source must follow every branch. A reader may stop with evidence or a refusal, feed a separate artifact, build a checked package, or reach Atlas through an explicit loader. The planning index does not run source readers or grant admission; downstream construction reconciles its placements with separately loaded releases.

## Core component documentation

| Component | Responsibility | Documentation |
| --- | --- | --- |
| Atlas planning index | Builds the content-addressed, non-authorizing placement plan and enforces registry-module classification. | [Atlas planning index](atlas_planning_index.md) |
| Managed vocabulary source adapters | Covers the concept-domain bridge, ELSST acquisition and three-stage coverage, and ICPSR transport. | [Managed vocabulary source adapters](managed_vocabulary_source_adapters.md) |
| Registry vocabulary sources | Reads native vocabularies, taxonomies, publisher lists, and source-scoped topic evidence without inventing source claims. | [Registry vocabulary sources](registry_vocabulary_sources.md) |
| Registry code and classification sources | Reads publisher codes, classifications, field dictionaries, identifier structures, and record-scoped evidence. | [Registry code and classification sources](registry_code_and_classification_sources.md) |
| Registry organization sources | Reads publisher-maintained organization rosters while preserving source-specific identity and hierarchy. | [Registry organization sources](registry_organization_sources.md) |
| Registry legal and identifier sources | Provides legal-source oracles, identifier checks, publisher controls, and the Unified Agenda artifact pipeline. | [Registry legal and identifier sources](registry_legal_and_identifier_sources.md) |
| Registry crosswalk and package sources | Preserves agency crosswalk evidence and manages CRS and LDA source-package and identity-review workflows. | [Registry crosswalk and package sources](registry_crosswalk_and_package_sources.md) |

For repository-wide context, see the [RefSpec overview](../README.md), the normative [Atlas 3.1 binding](../bindings/atlas/3.1/README.md), and the [decision ledger](../docs/decisions.md). [Atlas in the United States and Europe](../ATLAS_US_EU_COMPARISON.md) supplies strategic context, not implementation authority.