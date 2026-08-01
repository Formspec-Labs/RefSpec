<!-- markdownlint-disable MD013 -->

# RefSpec Decision Ledger

## Product ownership

The platform has four products. Each durable record has one owner even when a
different product publishes a conforming projection.

| Product | Owns | Excludes |
| --- | --- | --- |
| SpicyRegs | Source connectors, document identity and versions, exact representations, structural passages, source observations, and acquisition coverage | Vocabulary policy, derived assertions, retrieval ranking, and legal judgment |
| RefSpec | Managed ontology and vocabulary releases, source-term resolution, mapping validation, optional review references, and vocabulary coverage | Document acquisition, general evidence primitives, extrapolation execution, and search serving |
| Rulespec | Portable semantic structures and the extrapolation runtime, including evidence-bound assertions and extrapolation releases | Canonical source content, managed vocabulary publication, and general document search |
| SpicySearch | Neutral document and passage retrieval, disposable indexes, ranking, explanations, search coverage, and feedback events | Canonical documents, managed vocabularies, extrapolation authority, and legal or organizational judgment |

## Decisions

### REF-001: Narrow RefSpec to managed vocabularies

- **Date:** 2026-07-31
- **Status:** Accepted for the unreleased implementation

RefSpec publishes managed ontology and vocabulary content. It no longer claims
document acquisition, processing, query, search, or extrapolation ownership.
The earlier broad editor's draft remains in repository history as design
lineage.

### REF-002: Compose the Rulespec Core release shape

- **Date:** 2026-07-31
- **Status:** Accepted

Every `VocabularyRelease` exposes the exact complete Rulespec Core
`ReferenceResourceRelease` used by portable concept assignments. Rulespec Core
owns the shape. RefSpec owns the managed release that publishes the conforming
instance. RefSpec builds against exact package-local copies of the Core release,
`ReferenceResourceRelease` schema, and digest vector. It does not read a
Rulespec checkout or database. The `VocabularyRelease` also exposes the exact
Rulespec Core `release_id` and `release_digest` at its top level.

### REF-003: Resolve complete source-term keys

- **Date:** 2026-07-31
- **Status:** Accepted

RefSpec resolves `SourceTermKey` records, not document observations. Every key
has one explicit resolution with a policy version, reason, evidence, baseline
receipt, and status-specific target cardinality. Missing or ambiguous evidence
fails closed.

### REF-004: Use the current Federal Register source without a root ontology

- **Date:** 2026-07-31
- **Status:** Accepted

The April 1, 2025 Federal Register Thesaurus is the default candidate for the
Federal Register document profile. It is not a global root ontology. The active
implementation drops the 1995 source and any 1995-to-2025 crosswalk. API
Topics remain mutable source metadata and enter RefSpec only as source-term
keys.

### REF-005: Automate baseline validation without an approval gate

- **Date:** 2026-07-31
- **Status:** Accepted

Deterministic code checks schema, identity, digest, membership, cardinality,
and reference closure. Independent agents record semantic checks in immutable
`AgentValidationReceipt` records. `BaselineValidationReceipt` reduces those
attempts under a versioned policy. Human review is optional and does not gate
the first search-only candidate slices.
