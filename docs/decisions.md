<!-- markdownlint-disable MD013 -->

# RefSpec Decision Ledger

> **Origin:** REF-001 through REF-006 were written in the retired standalone RefSpec
> checkout and are imported here verbatim from its commit `210d671`. That line's history is
> archived in this repository under `refs/archive/refspec-standalone/*`. Decisions from
> REF-007 onward are written in this repository.

## Product ownership

The platform has four products. Each durable record has one owner even when a
different product publishes a conforming projection.

> **Superseded by [REF-008](#ref-008-count-four-products-and-five-ownership-rows):**
> the four-row table below merges Rulespec Core and Rulespec Extrapolator into a
> single Rulespec row. Ownership tables carry five rows, one per release unit;
> the product count stays four. The table is retained verbatim as design lineage.

| Product | Owns | Excludes |
| --- | --- | --- |
| SpicyRegs | Source connectors, document identity and versions, exact representations, structural passages, source observations, and acquisition coverage | Vocabulary policy, derived assertions, retrieval ranking, and legal judgment |
| RefSpec | Managed ontology and vocabulary releases, source-term resolution, cross-vocabulary mapping validation, optional review references, vocabulary coverage, and deterministic static atlas assets with lookup projections | Document acquisition, general evidence primitives, extrapolation execution, live document queries, ranking, and search serving |
| Rulespec | Portable semantic structures and the extrapolation runtime, including evidence-bound assertions and extrapolation releases | Canonical source content, managed vocabulary publication, and general document search |
| SpicySearch | Neutral document and passage retrieval, disposable indexes, ranking, explanations, search coverage, and feedback events | Canonical documents, managed vocabularies, extrapolation authority, and legal or organizational judgment |

## Decisions

### REF-001: Narrow RefSpec to managed vocabularies

- **Date:** 2026-07-31
- **Status:** Accepted for the unreleased implementation

RefSpec publishes managed ontology and vocabulary content plus deterministic,
query-ready static representations of that content. It does not own document
acquisition, document processing, live document queries, search serving, or
extrapolation. The earlier broad editor's draft remains in repository history
as design lineage.

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
the first search-only candidate slices. Model- or agent-generated crosswalk
candidates may enter a static atlas with `searchOnly` eligibility after a usable
baseline result. Later human feedback is append-only input to a new atlas; it
never rewrites a published asset.

### REF-006: Publish the vocabulary atlas as a static RefSpec asset

- **Date:** 2026-07-31
- **Status:** Accepted

RefSpec owns cross-vocabulary candidate generation, validation, canonical atlas
bytes, and the deterministic lookup projection over those bytes. A
`VocabularyAtlasAsset` pins every input `VocabularyRelease`, candidate input,
generation policy, implementation version, and output digest. RefSpec publishes
the asset as blank-node-free N-Quads plus a canonical manifest and exposes a
read-only lookup API.

The atlas is not a mutable ontology database or a search service. SpicySearch
may copy and pin the asset, then use it for document-query expansion, document
candidate generation, and ranking. It does not regenerate crosswalk candidates,
import RefSpec source code, ask RefSpec to serve a document query, or treat a
machine-qualified mapping as publisher or editorial truth.

### REF-007: Reconcile the standalone RefSpec line into this repository

- **Date:** 2026-08-01
- **Status:** Accepted

Two RefSpec checkouts diverged after commit `714866d`. This repository — the RefSpec
submodule inside `spicy-regs` — is the surviving line. It keeps the mature managed-release
implementation, adopts the standalone line's product boundary, decision ledger, managed
vocabulary specification, and static atlas design, and retires the standalone line's
duplicate release machinery. No repository consumed that duplicate machinery.

The standalone line's history is archived inside this repository as local refs:

- `refs/archive/refspec-standalone/main` pins its final commit
  `de744a3d8969bc333db0427321be81c4e4d750f3`, which descends from `210d671`; and
- `refs/archive/refspec-standalone/pre-scrub-initial` pins `67c497f`, the pre-amend initial
  commit that survives on no branch.

Neither archive ref is published by a default push. The reconciliation runbook records the
prepared commands for publishing them.

### REF-008: Count four products and five ownership rows

- **Date:** 2026-08-01
- **Status:** Accepted

This ledger's product-ownership table said "four products" over four rows, while the
authority map in [`product-boundary-and-api-disposition.md`](product-boundary-and-api-disposition.md)
and the README ownership boundary list five owners. Both were describing the same
boundary; the four-row table merged two distinct owners into one row.

The resolution follows the Rulespec decision ledger (2026-07-31, "Separate source,
vocabulary, extrapolation, and search ownership"): the platform has four products —
SpicyRegs, RefSpec, Rulespec, and SpicySearch — and Rulespec is one product with two
independent release units, **Rulespec Core** (`RulespecCoreRelease`) and **Rulespec
Extrapolator** (`ExtrapolationRelease`). Ownership and authority tables therefore carry
five rows, one per release unit, because each unit owns a distinct durable surface. A
five-row table does not introduce a fifth product.

The corrected ownership table splits only the Rulespec row:

| Owner | Owns | Excludes |
| --- | --- | --- |
| SpicyRegs | Source connectors, document identity and versions, exact representations, structural passages, source observations, and acquisition coverage | Vocabulary policy, derived assertions, retrieval ranking, and legal judgment |
| RefSpec | Managed ontology and vocabulary releases, source-term resolution, cross-vocabulary mapping validation, optional review references, vocabulary coverage, and deterministic static atlas assets with lookup projections | Document acquisition, general evidence primitives, extrapolation execution, live document queries, ranking, and search serving |
| Rulespec Core | Portable semantic structures: generic schemas, generated types, validators, and conformance fixtures | Canonical source content, managed vocabulary publication, extrapolation execution, and general document search |
| Rulespec Extrapolator | The extrapolation runtime: evidence-bound assertions, provenance and validation receipts, and extrapolation releases | Canonical source content, managed vocabulary publication, and general document search |
| SpicySearch | Neutral document and passage retrieval, disposable indexes, ranking, explanations, search coverage, and feedback events | Canonical documents, managed vocabularies, extrapolation authority, and legal or organizational judgment |

The four-row table at the top of this ledger is superseded in place and kept as design
lineage. The same four-versus-five tension exists in
`spicysearch/docs/decisions/0001-four-product-boundary.md`; that ledger belongs to the
SpicySearch repository and is referenced here without being edited by this decision.

### REF-009: Carry a development-only marker into the atlas rather than refuse it

- **Date:** 2026-08-02
- **Status:** Accepted

The ICPSR subject thesaurus release declares `operationalState: developmentOnly`,
because the public term-URI index and the pinned `subject.xml` snapshot are two source
versions joined by label rather than one publisher-versioned release. Giving it an atlas
adapter forced a choice: refuse to project a development-marked source into an atlas at
all, or carry the marker forward so a consumer sees it.

**An atlas adapter carries the marker and requires it; it never drops or overrides one.**
`PinnedIcpsrSubjectAtlasRelease.open` refuses any bundle that does not declare
`operationalState: developmentOnly` with `acceptedOutputAllowed: false` and
`candidateLookupAllowed: true`, and the projection republishes all three on the release
node in the `releaseFacts` graph.

Refusal was considered and rejected because it would have been a claim this platform does
not make. Every atlas input is already candidate-only: `ManagedReleaseView.usage_ceiling`
is `candidateUseOnly`, and the Federal Register adapter requires its own **source-complete**
2025 package to declare `candidateLookupAllowed: true` and `acceptedOutputAllowed: false`
before it will open. No atlas anywhere is accepted output, so a development marker
distinguishes one candidate-only input from another rather than separating production from
non-production. Refusing on it would have dropped 3,760 verified concepts to enforce a
boundary the format does not draw.

The marker rides in `releaseFacts` rather than the atlas manifest because
`VocabularyAtlasAsset.open` refuses any manifest whose key set differs from the closed
schema 1.0 set. A top-level field would need a binding version bump; the release node is
where the release's own declarations already live.

The rule generalizes past ICPSR: a future adapter over a source that marks its own
operational state must require that declaration at its door and republish it. Silently
projecting a development-marked source into a production-shaped bundle is refused, and so
is silently discarding a vocabulary because it was honest about its own state.

The measured basis is in [`icpsr-atlas-bridge.md`](icpsr-atlas-bridge.md).

### REF-010: Restrict ELSST to the edition the crosswalk names

- **Date:** 2026-08-02
- **Status:** Accepted

RefSpec publishes ELSST as a **managed release over an ordered edition history, and
selects the editions that history needs** — not "every edition the publisher has issued".
The current selection is R6 alone. ELSST R5 is not needed and is not being carried.

The measured basis is in
[`atlas-distribution-measurement.md`](atlas-distribution-measurement.md). All 365
crosswalk candidates and all 121 qualified mappings name
`https://elsst.cessda.eu/id/6`; R5 is named by zero candidates, zero validations and zero
mappings. Carrying it anyway costs 78.9% of the distribution's bytes and **95,497 of its
96,958 label clusters** — a two-edition bundle is the single largest cost in the whole
atlas, larger than any vocabulary.

**Proved by execution, not by citing that measurement.** A real R6-only managed release was
built (bundle manifest `sha256:e20928a6…`, 3,470 members, its own combined Rulespec
receipt) and the crosswalk-bearing atlas was rebuilt on it against the same Federal
Register package, Rulespec Core release and 2026-08-02 qualification bundle. All **365
candidates**, the same **121 `searchOnly` / 244 `notEligible`** split, all **121 qualified
mappings with an identical qualified set**, all **729 machine validations**, and unchanged
member counts — Federal Register 705, ELSST R6 3,470 — for **−82.9% of the bytes**
(263,620,491 to 45,066,321). The record is in
[`elsst-r6-only-atlas-2026-08-02`](../research/evidence/elsst-r6-only-atlas-2026-08-02/README.md).

This is a selection decision, not a capability removal. The importer takes one or more
acquired sources in publication order and selects the last; a lifecycle transition is
derived by comparing two releases, so a one-edition history states none rather than
inventing one, and each consecutive pair still contributes exactly the transitions it
proves. Adding R5 back is passing it again.

**One identity moves, by design.** R6's `rkaf:referenceReleaseDigest` changes with the
edition selection, because a distribution IRI is scoped to the set of sources the history
was built from and the closed release digest covers its distribution. A crosswalk candidate
pins release IRIs rather than release digests, so every candidate still resolves; the atlas
independently requires each named release to carry exactly one digest, and both do.

**R6's `owl:priorVersion` statements still point at R5 concepts an R6-only release does
not describe.** That is already the normal case — R5's own 3,423 point at ELSST R4, which
no RefSpec release has ever contained — and no consumer reads the predicate. An
edition-aware consumer would be reading a dangling edge under either selection; it is
recorded here so a future one is not surprised.

The two-edition identity is preserved rather than restated: the identifier-scope preimage,
the graph descriptor and the managed-release identity keep their exact published shape at
length two, so nothing already built moves.

### REF-011: Publish a consumer-shaped projection as its own distribution kind

- **Date:** 2026-08-02
- **Status:** Accepted

A **projection** — a subset of one generated atlas chosen by a named policy — is published
as `refspec-vocabulary-atlas-projection-nquads-1.0`, a sibling kind alongside
`refspec-vocabulary-atlas-nquads-1.0`. It is **not** an amendment to binding 1.0, and the
`amendments` marker in the conformance corpus gains no entry.

The defect: an atlas identifier is a digest of `{format, inputs, implementation,
policies}`, and a subset of a generation has the same inputs, the same implementation and
the same policies. So a projection and its parent carried **one asset identifier**, both
opened under RefSpec's own validator, and `reproduce_from_inputs` refused a projection
with the message reserved for a corrupted atlas.

Three reasons this is a kind rather than an amendment.

1. **The reproduction contract differs.** An atlas is a pure function of its managed
   releases, its Rulespec Core release, and its optional crosswalk. A projection is a pure
   function of its parent distribution and its keep rule. One `type` cannot carry both
   answers to "prove these bytes are what the producer made" without one of them being
   false.
2. **The atlas manifest field set is closed on both sides.** Producer and consumer each
   compare the key set for exact equality, so an *optional* `derivedFrom` does not exist.
   An amendment would have to mean "one of two field sets", which is a second kind wearing
   the first kind's name. Contrast the two amendments this binding has taken in place:
   `2026-08-02` added an artifact role and two rules, and `2026-08-02-hierarchy` widened a
   count that is present exactly when the fact is. Both describe the same artifact more
   precisely. `derivedFrom` changes what the artifact *is*.
3. **Nothing published moves.** `atlas/model.py` is pinned by digest inside every atlas's
   own `implementation` block, so amending the atlas manifest in place moves the asset id
   of all nine generator-built conformance fixtures. A new kind in a new module changes no
   atlas identifier, no fixture digest and no byte of the Federal Register example — which
   is itself evidence that these really are different artifacts.

A projection manifest states what an atlas manifest cannot: `derivedFrom` names the
parent's asset id **and both of its file digests**; `projectionPolicy` carries the named
keep rule and its version in full, so "what was dropped" is a pinned, testable statement
rather than a diff; and the identifier is derived from all three, so a projection can
never collide with its parent or with a projection of it under another policy. Its named
graphs remain the parent's, because its quads are the parent's quads. Every declared count
is re-derived from its own payload, so the file is checkable without opening the parent.

`reproduce_from_inputs` now gives a projection an honest answer by construction: a
projection is refused on its manifest shape before any rebuild comparison, so the
corrupted-atlas message is unreachable. `reproduce_distribution` dispatches on the
declared type and names which inputs each kind reproduces from. The residual is that the
atlas reader's own refusal names the shape ("atlas manifest fields differ from v1") rather
than the word "projection"; naming it inside `VocabularyAtlasAsset.open` would move those
nine fixture identifiers, which is not worth a better sentence.

The published projection of the edition-restricted atlas is **30,174,064 bytes, 1,911,890
gzipped** — 67.0% of the 45,066,321-byte atlas it came from — and every fact a consumer
reads is byte-identical to that atlas, digested predicate by predicate. It opens in 2.5
seconds and rebuilds byte-identically. The vendored SpicySearch reader opens the atlas
today and refuses the projection, because a projection is a kind it has not been taught;
that is a consumer amendment, not a defect in the file.

The projection carries `skos:broader` although no consumer accessor reads it yet.
Hierarchy is a release fact this repository spent two days admitting into the atlas, and a
projection kind that structurally could not carry it would have stranded that work behind
a second format change. `skos:narrower` is dropped, which is sound only under
[REF-006](#ref-006-publish-the-vocabulary-atlas-as-a-static-refspec-asset)'s hierarchy
amendment: an edge is projected from the broader direction alone and a source stating both
must have them agree, so the surviving half is the whole fact.

### REF-012: Do not pursue the 1995 Federal Register thesaurus edition

- **Date:** 2026-08-02
- **Status:** Accepted

The November 16, 1995 Federal Register Thesaurus edition **is not needed and is not being
pursued**. This closes a question
[REF-004](#ref-004-use-the-current-federal-register-source-without-a-root-ontology) left
half-open: REF-004 said the active implementation drops the 1995 source and any
1995-to-2025 crosswalk, but the edition stayed *recoverable but policy-withheld* — the
vocabulary policy still listed it as an input, and `make test-real-vocabulary` remained a
live networked gate that downloads it, rebuilds its development managed release, and
proves its rollback.

Nothing needs it. The Federal Register side of every published artifact is the April 1,
2025 release: the vendored atlas example, the 705-concept managed package, and all 365
candidates and 121 qualified mappings in the 2026-08-02 crosswalk name
`urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:v1`. The 1995
edition would add a second Federal Register history whose only consumer would be
vocabulary-change analysis nobody has asked for, at the cost of a second source
acquisition, a second managed release, and a networked gate in an otherwise offline suite.

**The one consequence, named.** The development bridge example
`examples/development/icpsr-federal-register-concept-bridge-v1.json` targets
`urn:ref:fr-thesaurus-1995:release:1995-11-16-preview` — a release RefSpec will now never
publish. It does not break, and it is not being changed: the file is pinned by
`ICPSR_FEDERAL_REGISTER_BRIDGE_V1_SHA256`, and its test supplies a stub target view rather
than opening a managed release, so it exercises the bridge **reader** and never depended
on a 1995 release existing. What it can no longer become is a real ICPSR-to-Federal-
Register bridge. Its seven edges are not recoverable by editing the target release either,
because 1995 concept identifiers have no 2025 counterparts to rename to; a real bridge
would be a new artifact generated against the 2025 release. It is therefore retained as a
**format example only**, and the ICPSR-to-Federal-Register path a product would use is the
atlas's qualified `searchOnly` mappings, which no ICPSR crosswalk has produced yet.

The 1995 reader, its vertical slice, and its networked gate stay in the tree as historical
regressions. They are not an integration in progress.

### REF-013: Govern atlas growth through a non-authorizing portfolio index

- **Date:** 2026-08-04
- **Status:** Accepted for the unreleased implementation

RefSpec adopts the placement and growth rules in the
[Vocabulary Atlas Final Synthesis](../research/vocabulary-atlas-final-synthesis-2026-08-03.md).
The atlas remains a static publication of exact managed-release facts and qualified mapping
evidence. It does not become a combined registry, a live database, or a second source of
product permissions.

The resource catalog gains a separately identified atlas index. Each source row records a
non-authorizing `publicationTarget`: `atlas`, `entitySpine`, `codeLedger`,
`legalIdentityGraph`, or `sourceAssignedEvidence`. Rows targeting the atlas may also record
an `atlasParticipation` planning class: `core`, `specialist`, or `bridge`. A source may have
more than one row when distinct facets have different destinations or roles. Shared models,
transports, acquisition helpers, policies, and development artifacts receive no source row.

Every row names the exact resource, facet, assignment role, intended uses, planning status,
and readiness evidence. An atlas row may identify a planned class before a managed release
exists, but it cannot claim release readiness or enter a build until it names a conforming,
complete release. Index versions are immutable and content-addressed. Later evaluations
append or supersede rows; they never erase failed or deferred history.

The index informs publication planning and build-drift checks only. It does not add fields to
an atlas manifest, authorize an enrichment candidate or accepted output, enable a mapping,
or activate search expansion. RefSpec `OutputProfile` rows remain the sole enrichment
permission source. SpicySearch's pinned retrieval policy remains the sole search-expansion
permission source. Reader-declared uses remain source evidence and fail-closed parser guards;
they do not become a third permission system.

Large bridge vocabularies enter only through a reproducible two-pass frontier build. The
selection pass pins the full observed source, exact comparison releases, algorithm, parameters,
coverage, and per-concept reasons. The release pass publishes complete membership for exactly
that selected scope before mapping candidates are regenerated and qualified. Code lists,
identifier authorities, entity registries, legal identifiers, and publisher-assigned topics
remain in their separate publication targets and never enter atlas `releaseFacts` or
`analysis` merely because they share labels with subject concepts.
