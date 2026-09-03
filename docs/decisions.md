<!-- markdownlint-disable MD013 -->

# RefSpec Decision Ledger

> **Origin:** REF-001 through REF-006 were written in the retired standalone RefSpec
> checkout and are imported here verbatim from its commit `210d671`. That line's history is
> archived in this repository under `refs/archive/refspec-standalone/*`. Decisions from
> REF-007 onward are written in this repository.

## Product ownership

The platform has four products. Each durable record has one owner even when a
different product publishes a conforming projection.

> **Ownership update (2026-08-25):** REF-048 adds DocSpec as the catalog and
> document-processing owner and narrows SpicyRegs to source-native acquisition
> and publication. The early count and tables below remain design lineage; use
> REF-048 for the current platform boundary.

<!-- -->

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

> **Repository-location update (2026-08-25):** RefSpec now lives in the
> standalone local work-directory repository. The former SpicyRegs submodule is
> retired. This decision's implementation-line and archived-history choice
> remains; its submodule-location sentence is historical.

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

> **Ownership update (2026-08-25):** REF-048 supersedes the SpicyRegs row below
> and introduces DocSpec as the separate `SourceCatalog`, capture, passage, and
> `DocumentRelease` owner. Its count describes the earlier topology.

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
- **Status:** Superseded for Atlas publication by the shared Atlas 2.0 release foundation

The source fact remains useful to the private qualification reader, but Atlas
2.0 no longer has an ICPSR-specific publication adapter. It snapshots exact
source or managed concept releases through the same four-ring record foundation.
The text below records the Atlas 1 decision that led to preserving the marker.

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
- **Status:** Superseded in format version; sibling-distribution principle retained

Atlas 2.0 implements the durable part of this decision with
`refspec-vocabulary-atlas-projection-nquads-2.0`: a projection remains a
separate, content-derived distribution that pins one canonical parent and one
registered ring or subject-module selector. The Atlas 1 details below remain
decision lineage, not current format instructions.

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

### REF-014: Separate cataloged sources from governed Atlas schemes

- **Date:** 2026-08-06
- **Status:** Accepted for the unreleased Atlas 3.0 implementation; supersedes
  REF-013 only where REF-013 excludes non-subject reference resources from Atlas
  3.0.

Atlas 3.0 keeps its four semantic rings and five resource profiles. It adds a
separate `atlas:RegistrySource` descriptor for each cataloged publisher or
reference source. A source may supply zero, one, or several
`atlas:ResourceScheme` instances. Every emitted release still selects exactly
one scheme, one resource profile, and one semantic ring.

Every source also records a closed `atlas:memberDisposition`. Seventy cataloged
sources currently have member releases. The remaining nineteen explicitly name
why they do not: their facts live in child releases, source assignments, or
mapping assertions; they are definition-only, historical-only,
review-withheld, source-empty, or a resource family. Descriptor-only no longer
means "adapter status unknown."

This corrects a category error in the first registry-wide implementation. The
catalog rows describe sources: they carry an official locator, availability,
capture limits, and versioning instructions. A `ResourceScheme` describes a
governed set of members. Treating those as the same node forced mixed sources
such as a data model with both field definitions and code domains into one
profile. Splitting catalog rows into duplicate pseudo-sources would hide the
shared publisher capture and provenance. The explicit source-to-scheme link
preserves both facts.

The change does not alter the standards boundary. Subject members remain SKOS
concepts, labels remain canonical SKOS-XL labels, and the Atlas-owned ontology
stays inside its declared OWL 2 RL-safe subset. Atlas assertions retain separate
proposition, evidence, and lifecycle records so a compatibility view can map to
a pinned Rulespec Core release. Atlas does not claim Rulespec conformance until
that exact compatibility view exists and validates.

`atlas:NativeRelationAssertion` now permits publisher-authored, same-ring facts
whose endpoints belong to different exact releases. Requiring one release made
ordinary facts such as a facility-to-organization association impossible unless
the producer misused an equivalence mapping or merged distinct schemes. The
assertion still names both endpoint releases, one semantic ring, a closed
predicate policy, immutable evidence, and lifecycle state. Cross-ring facts
continue to use `atlas:CrossRingRelationAssertion`; mappings continue to mean
cross-release semantic comparison rather than an arbitrary relationship.

### REF-015: Make compact managed records the eventual Atlas source of truth

> **Superseded by REF-028:** compact managed records are not becoming the
> Atlas source of truth. The compact JSONL/Zstandard transport this entry
> introduced as a non-authoritative sidecar was deleted from the wire in the
> 3.1 bump (`cb10a8e8`), together with the parity cutover it was staged for.
> The separation of concerns it borrowed stands and is delivered: one
> governed record set (the asserted RDF), several reproducible consumer
> views (the typed Parquet view, the search view, the explorer). What is
> retired is the specific claim that the *compact record* would become
> canonical after a parity acceptance — that acceptance never ran, no
> consumer ever read the packs as authority, and the served projection is
> now Parquet. The eight closed roles, their exact field sets, and the one
> normalization every producer and verifier must agree on survive as the
> logical-record contract in `refspec/atlas/compact_pack.py`; only the file
> format is gone. A real reversal, recorded as one: this entry's direction
> was accepted, and it is withdrawn rather than completed.

- **Date:** 2026-08-06
- **Status:** Accepted direction; canonical cutover requires parity acceptance

Atlas will borrow two publication patterns without adopting either system's
data model. [ESCO publishes one managed classification through RDF, tabular
downloads, and APIs](https://esco.ec.europa.eu/en/use-esco). [Wikibase exposes
both full statement RDF and a simpler direct or "truthy"
form](https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format). Atlas
will apply that separation to versioned United States public reference sources:
one governed record set, several reproducible consumer views.

The current [Atlas RDF binding](../bindings/atlas/3.1/README.md) remains
canonical during migration. Compact managed records become canonical only in a
deliberate binding cutover after they reproduce every authoritative RDF fact
and pass independent parity checks. Until then, compact packs are
non-authoritative sidecars. The initial
[`compact_pack.py`](../src/refspec/atlas/compact_pack.py) module supplies only
deterministic JSONL/Zstandard transport: its header seals pack defaults and
dependencies, its rows sort uniquely by `id`, and separate digests pin compact
bytes, transport bytes, and fully expanded logical rows. Role schemas and
semantic adapters remain migration work.

After cutover, the canonical release will contain compact `Resource`, `Label`,
`Statement`, evidence/reference, source-record, and release records. Four
outputs will be derived from that same release:

- **full audit RDF**, preserving statement identity, evidence, provenance, and
  lifecycle;
- **direct RDF**, containing convenient current relation and label triples but
  creating no new editorial authority;
- **search indexes**, which remain disposable consumer-owned artifacts; and
- **the explorer**, which visualizes the compact records and their derived
  relations without becoming a second source of truth.

Every canonical release remains immutable and content-addressed. Its manifest
must pin exact source inputs, binding and recipe versions, pack membership,
uncompressed content digests, transport digests, and provenance closure. Every
derived view must pin the canonical release and the exact derivation recipe.
Inference stays identifiable as derived; it never changes an asserted statement
or supplies missing editorial evidence. Any source, policy, record, or recipe
change produces a new release rather than rewriting an existing one.

Migration proceeds by evidence, not by format preference. First, publish compact
sidecars beside the existing RDF. Next, add closed role schemas and deterministic
adapters in both directions. Run fixtures and complete real releases through
both paths and require identical IDs, membership, English labels, identifiers,
relations, assertion state, evidence, provenance, source accounting, and
release closure. Rebuilds must be byte-stable; digest and tamper failures must
fail closed; full audit RDF must pass the independent Atlas validator; and the
direct view must contain only triples licensed by current authoritative
statements. Cut over only after those checks pass and complete-release
measurements confirm that compact generation and validation materially reduce
time and memory. Until then, rollback is simply omission of the sidecars.

### REF-016: Apply publisher mappings across versions through explicit adoption

- **Date:** 2026-08-06
- **Status:** Accepted

Atlas accepts versioned publisher alignment artifacts through one generic
mapping-release boundary. A source adapter pins the exact mapping bytes, release
metadata, source versions, direct triples, and any missing publisher version
facts. The core generator does not contain source-specific version or input-role
rules. This lets later or parallel alignment versions use the same build path
without weakening provenance checks.

A publisher mapping is `atlas:publisherAssertion` only for the release context
the publisher actually states. When Atlas applies the same pinned triple to a
different loaded edition, it records `atlas:operatorAdoption`, the Atlas decision
date and reviewer, and the exact normalized endpoint releases. Aggregate counts
in newer publisher metadata may corroborate that a linkset still exists; they do
not prove that every older pair was re-reviewed. Atlas therefore records that
limit and does not invent a confidence value.

Every mapping source release keeps the digest and locator of the mapping artifact
it identifies. Supporting release metadata remains separately pinned input; it
is not folded into the publisher release digest. A new source version or Atlas
adoption creates new immutable evidence against exact endpoint releases instead
of rewriting an existing evidence binding. Missing endpoints, unexpected
predicates, or unrecognized version facts fail closed.

The portable Atlas 3.0 binding continues to support the five SKOS mapping
predicates: `exactMatch`, `closeMatch`, `broadMatch`, `narrowMatch`, and
`relatedMatch`. Each source adapter admits only predicates present in its pinned
publisher profile. The EuroVoc--LCSH 20240711-0 artifact contains only
`exactMatch` and `closeMatch`; its adapter rejects an unexpected predicate rather
than silently discarding it. Subject mappings do not normalize `owl:sameAs`
because RDF individual identity is stronger than a SKOS concept mapping.

### REF-017: Reuse only verified pack transports during Atlas rebuilds

- **Date:** 2026-08-06
- **Status:** Accepted

Atlas rebuilds may reuse compressed pack bytes from a prior Atlas 3
distribution, but only after reconstructing, sorting, and receipting the current
canonical N-Quads. Reuse requires the current and prior content digest, byte
length, and quad count to match exactly. The producer copies the prior transport
into a new candidate and verifies both its stored-byte receipt and decompressed
content receipt before promotion. A missing prior distribution is a clean
build; an unsafe or internally inconsistent reuse source fails closed.

This is `incrementalPackMaterialization`, not incremental semantic construction.
The current compiled producer proof still requires every normalized source row,
global join, complete graph, source-accounting row, and canonical pack stream to
be rebuilt and checked. The generation report records reused and rebuilt packs
and states that boundary directly. Source-level incremental construction needs a
new producer-proof profile or the independently accepted compact-record cutover
in [REF-015](#ref-015-make-compact-managed-records-the-eventual-atlas-source-of-truth);
pack reuse must not pretend that work is complete.

### REF-018: Serve full-corpus exploration as a verified static view

> **Superseded by REF-026:** the RDF explorer this describes is deleted. Its
> reader re-verified the distribution independently of the validator and had
> already drifted to 11 acceptance gates against the validator's 13 — the
> failure class REF-026 names. `explorer.py` builds the same browser from the
> compact Parquet search view, and the verified static-shard contract
> survives unchanged in `explorer_render`. The entry is retained verbatim as
> design lineage.

- **Date:** 2026-08-06
- **Status:** Accepted

The full-corpus explorer is a reproducible view beside an Atlas distribution,
not another authoritative Atlas format. Its small root index pins the exact
Atlas manifest and asserted inventory, the explorer recipe, every shard's
relative path, byte length, SHA-256 digest, role, and record count. Stable hash
prefixes route resource detail and adjacency reads; compact label pages support
English search and browsing. The browser fetches a needed shard, verifies its
digest, and only then parses or displays it.

Ordinary static HTTP hosting is the complete mode and requires no database
service. Direct `file://` viewing retains a clearly labeled, self-contained
bounded fallback because browsers do not reliably allow sibling-file fetch and
verification. Explorer shards remain disposable: they may be rebuilt from the
pinned Atlas release, transfer no authority, and never change the asserted,
projection, or derived graph roles.

### REF-019: Reuse an exact Atlas distribution before source parsing

> **Superseded by REF-027:** exact whole-distribution reuse is deleted
> (`74aaafd9`). Its recipe digest covers eleven shared modules and the
> generator's own source, so any producer edit missed the cache by
> construction; in the artifact record it hit once, on a distribution
> rebuilt from unchanged inputs. What it bought was one skipped rebuild,
> against a fail-closed comparison of the full input inventory, manifest
> closure, and every stored and decompressed pack receipt. Every build is
> now cold. The `packMaterialization` block keeps its reuse fields at their
> cold-path constants until the 3.1 wire bump. The entry is retained
> verbatim as design lineage.

- **Date:** 2026-08-06
- **Status:** Accepted for the unreleased Atlas 3.0 implementation

An Atlas build first checks whether a prior distribution is an exact reusable
result. Its producer proof authenticates the complete raw-input inventory and a
recipe digest covering the generator, registry parsers, Atlas source adapters,
shared normalization code, and relevant Python, Unicode, RDF, SHACL, and
Zstandard runtime versions. Reuse also requires the current binding, producer
identity, manifest and member closure, source accounting, acceptance proof,
every current raw input byte receipt, every stored pack receipt, and every
decompressed pack receipt to match.

When all checks pass, `exactDistributionReuse` keeps or copies the byte-identical
distribution and skips source parsing, normalized-row validation and global
joins, RDF graph construction, canonical sorting, and compression. A missing or
incompatible receipt is a cache miss and runs the complete semantic build. A
changed input or malformed artifact that claims compatibility fails closed.
Verified compressed-pack reuse remains available during that complete rebuild.

This is not incremental Atlas construction and does not claim partial per-source
reuse. The current release packs do not carry pack-local producer proofs or the
compact summaries needed to replay global resource uniqueness, endpoint-release
membership, ring and predicate policy, SKOS conflicts, and source-accounting
closure without reconstructing the full graph. Safe partial rebuilding requires
immutable per-release build keys and packs, authenticated global-invariant
summaries, a deterministic summary merge that reruns those checks, dependency
invalidation for mappings and the catalog, and cold-build byte-parity tests. The
compact-record cutover in REF-015 remains the preferred place to add that
capability rather than treating compressed RDF as an unverified cache.

### REF-020: Authenticate release-local Atlas construction for safe incremental builds

> **Superseded by REF-027:** release-local incremental construction is
> deleted (`74aaafd9`). No incremental build was ever produced — the
> acceptance it named (cold-versus-incremental byte parity) was never met,
> so the planner, clean-unit readers, and dirty/clean accounting merge
> stood as untested machinery threaded through the cold path they were
> meant to shortcut. The `atlas-construction-summary.json` member and its
> authenticated build keys survive unchanged: they are the construction
> evidence this entry correctly identified, and the manifest still pins
> them. Only the reuse arm that read them back is gone. The entry is
> retained verbatim as design lineage.

- **Date:** 2026-08-06
- **Status:** Accepted for the unreleased Atlas 3.0 implementation

Atlas distributions include a required `atlas-construction-summary.json`
member. It authenticates one construction unit per source or mapping release:
the exact raw-input pins, adapter recipe, source release and ring, endpoint
dependencies, deterministic build keys, source-accounting row, owned RDF packs,
compact logical-record packs, and role counts. The producer proof pins the
summary, and the manifest pins both files. Compact packs are transitively inside
the closed distribution even though they are indexed by the summary instead of
listed as RDF packs.

Before parsing source data, an incremental build inventories the current raw
inputs and compares their release-local build keys with a verified prior
summary. It reuses clean construction units and their authenticated RDF,
accounting, and compact records. A changed source rebuilds that source, every
mapping whose endpoint dependency changed, and the catalog. Unknown roles,
missing inputs, changed recipes, inconsistent receipts, and incomplete
dependency closure fail closed. Exact whole-distribution reuse remains the
fastest unchanged path; release-local reuse is the changed-input path.

This summary is construction evidence, not a second knowledge model. Atlas 3.0
RDF remains authoritative until REF-015's compact-record cutover passes full
cold-versus-incremental parity, tamper, fixture, and independent-validation
acceptance. A successful incremental build must produce the same authoritative
distribution as a cold build from identical inputs; reuse changes work, never
meaning.

### REF-021: Use DuckDB as a reusable local Atlas query layer

- **Date:** 2026-08-08
- **Status:** Accepted for local query and explorer use

RefSpec supplies `refspec.atlas.duckdb_view` as the reusable query boundary over
an externally digest-pinned compact Atlas Parquet view. It verifies the closed
input before opening stable SQL views for every compact record role. Consumers
may run parameterized row or Arrow queries through that session. The explorer
depends on the same small `facets`, `search`, and `resource` interface rather
than owning DuckDB setup or Atlas query rules.

Nonblank text search materializes one local resource-search table and builds a
native DuckDB BM25 index lazily. The writable DuckDB file lives in a temporary
directory outside the closed Parquet artifact, serves only the pinned immutable
input, serializes access through one local session, and is removed on close. It
is neither an Atlas release member nor a competing knowledge model. Failure to
load DuckDB's official `fts` extension is explicit; RefSpec does not silently
restore the former hand-written ranking.

The RDF explorer this paragraph deferred to is retired with REF-018; the
explorer now reads the compact Parquet view directly and no longer delegates
only ranked search to it. The static explorer remains usable without DuckDB. Canonical Atlas authority stays
with the accepted release representation, and SpicySearch continues to own
product retrieval, ranking, and agent-facing search behavior.

### REF-022: Adopt the cross-product search topology and approve the agentic graph search direction

- **Date:** 2026-08-09
- **Status:** Accepted; closes Stage 0 of the agentic graph search plan

The product topology is fixed: RefSpec owns vocabulary — sources, concepts,
related terms, and sealed Atlas releases. DocSpec owns files at scale.
SpicySearch is the only junction: it consumes Atlas releases from RefSpec and
files from DocSpec, and tagging executes there, applying RefSpec vocabulary to
DocSpec-managed files. RefSpec and DocSpec share no direct edge, and no work
may introduce one.

This closes Stage 0 of
[the agentic graph search plan](../research/atlas-agentic-graph-search-next-steps-2026-08-07.md)
and approves its direction. Three Stage 0 decisions land with it. The proposed
DocSpec exclusion is reversed: DocSpec participates in the pilot, mediated
solely through SpicySearch. The experiment is registered in the experiment lane
of [the managed-vocabulary experiment roadmap](../plans/managed-vocabulary-experiment-roadmap.md).
Ownership collapses to the single portfolio decision-maker with the
product-boundary roles above; no responsibility matrix is produced, because a
seven-role matrix for one decision-maker is structure nothing reads.

Stage 1 — SpicySearch as a verified Atlas 3.0 consumer with expansion disabled
— is queued after the Atlas 1.0/2.0 retirement and rkaf adoption steps recorded in REF-023 below. Its consumer
seam should be built as RuleSpec bridge contracts rather than a minted seam,
and its sealed input must be re-observed at start: the manifest digest recorded
in the plan on 2026-08-07 predates the retirement's digest-chain regeneration
and is stale. Later-stage gates — hub choice, meta-subjects, any binding
change — remain open by design and are not decided here.

### REF-023: Supersede the compatibility view — rkaf ships on the Atlas wire

- **Date:** 2026-08-10
- **Status:** Accepted; adoption executing. This entry absorbs and supersedes
  `plans/refspec-on-rulespec.md` and `plans/atlas-1-2-removal.md`, both
  deleted with this revision; their execution history lives in git history.

**Goal: everything in the right place, and minimal architectural debt going
forward.** Each concept lives in the one layer that owns it — rkaf for shared
semantics, `atlas:` for Atlas's own domain, the registry for source fidelity,
consumers for serving — and nothing is added, kept, or duplicated in a place
that will have to be unwound later.

The earlier boundary — Atlas keeps a private ontology and defers Rulespec
conformance to a future compatibility view — is superseded. RefSpec relies on
RuleSpec directly: for every rkaf-covered semantic, the published Atlas
record uses the rkaf term and shape on the wire, and `atlas:` mints
vocabulary only for its own domain (releases, packs, digests, rings,
resource profiles). Records are append-only events; state is a derived,
rebuildable projection, never stored authority. Adoption is one-way —
RefSpec depends on RuleSpec, never the reverse — and reads the real checkout
directly: `profiles/rulespec-dependency.json` is the pin, and
`tests/test_rulespec_vocabulary_currency.py` verifies it against the live
sibling checkout — including that the checkout actually contains the pinned
revision (`22fdad0`) — with no digest-pinning of upstream prose. An earlier
revision of this paragraph named a `make audit-rulespec-pin` target; that
target was deleted in `7975234`, which made the dependency manifest itself
the pin, and no replacement target exists.

**The governing rule** (also in [AGENTS.md](../AGENTS.md)): a structure —
term, spec section, layer, boundary — may be added or retained only with a
running validator or real consumer that breaks when it is violated,
negative fixture included. A legacy artifact may be deleted once every
capability it uniquely specifies is enforced elsewhere by a running check,
and the deletion commit names those checks.

**Executed**, each gated before or with its landing: `rkaf:membershipMode`
(`e2ca150`); evidence and review vocabulary (`e9b19c5`, `436b5cc`);
lifecycle events and supersession with derived lifecycle state (`79eaa2a`);
`atlas:confidence` deleted as a constant with no contract (`ad3e669`); a
gate refusing any `atlas:` term duplicating an rkaf local name (`637946b`,
`tests/test_atlas_rkaf_adoption.py`). The Atlas 1.0/2.0 retirement is
complete: producer path, bindings, and historical docs deleted across
`c16366d`..`5c6d889`; an audit of `5c6d889` found the machine-proof
protocol's only in-repo carrier deleted unenforced, so
`bindings/atlas/1.0/README.md` was restored byte-exact (`21b662a`) until
the P0 item below re-retires it. All other deleted carriers live at
`5c6d889^`. Typed rights and scope (item 3 below): `usageEligibility`
(closed 7-value lattice) and a `rkaf:AccessScope`-typed record (closed,
discriminated-union-validated, fidelity-checked both ways against CUE) replace
the loosely-shaped scope JSON on the REF JSON Binding wire —
`common.schema.json`, `access-scope.schema.json`, `output-profile.schema.json`'s
`permissionBase`, a `binding.py` cross-reference rule resolving
`Capture.accessScopeRefs` to a validated `rkaf:AccessScope` record (the same
type `release_graph.py`'s pre-existing `RULESPEC_ACCESS_SCOPE` resolution
already names in the Rulespec release graph — no REF-owned twin), and a
lattice-aware floor-and-ceiling accepted-output gate replacing the vestigial
`accepted_output.py` field and its bare-string comparison, mirrored in
`subject_emission.py`'s independent grant validator and the open-label
narrow-only clamp in `vocabulary.py`;
`tests/test_usage_eligibility_lattice_currency.py` keeps every RefSpec-side
usage-eligibility list an exact ordered match (rank order is normative) or
subset of rulespec's live lattice, including `release_graph.py` and
`managed_release.py`'s independent copies (this revision).

**Checks are structure too, and were made to earn their keep** (`07e9d18`
..`0b2a56a`, this revision). `make test` went from 617s to about 60s with
its refusals intact — the failure set compared test id by test id, not by
count. What the measurement found was not slow code but repeated work: 96%
of every `validate_distribution` was re-deriving whether `atlas.shacl.ttl`
is well-formed SHACL (1.880s against 0.070s of actual data conformance),
110 times per corpus run, after a dedicated `shacl-meta` gate had already
proved it once; `make test` ran the entire 110-case corpus **twice** because
a Makefile target and a pytest test issue the same argv; and the suite ran
single-process. Now the meta-proof is memoized on the shape-graph digests
(a raising call caches nothing, so a bad graph is re-refused every time),
the duplicate target is gone with a Makefile-parsing test holding it gone,
pytest fans across cores, and `check-generated` answers from a
content-addressed receipt over 21 enumerated inputs that fails closed on any
mismatch. One structural fix came with it: `bindingBundleDigest` had mixed
the semantic contract with the tools that compute it, so a one-line edit to
a program reissued 440 fixtures; `BINDING_TOOL_PATHS` now carries tool
provenance separately. That split had one defect, now closed (`8b14c82`): the
validation cache key derived from the contract bundle alone, so a
validator-only change could be served an acceptance the old validator
computed — a cache hit returns before the procedural gates run. The key now
carries a `BINDING_TOOL_PATHS` inventory and the runtime, while conformance
identity stays contract-only, and the runtime notion moved out of the fixture
builder into the validator so both read one definition. The README's claim
that the bundle covers the validator was the wrong half and was corrected:
the field is right, and its rightness is the point.

**Open work, in order.** No session's memory is required; this entry plus
the cited paths are sufficient.

1. **P0 — machine-proof closure. Done** (`e822f95`, `08001c6`, `22fdad0`,
   `99fe679`, `5c24825`). The machine-adjudication protocol is on the v3
   wire in rulespec's own vocabulary — 22 rkaf terms, no `atlas:` mint —
   shaped from `constraints/analysis/resolver-proof-record.cue` and
   `machine-adjudication.cue`, with `rkaf:Artifact` resolving every sealed
   digest to bundled bytes. `bindings/atlas/3.1/tools/validate.py` carries
   the `machine-adjudication` gate (independence, complete support, verdict
   lattice, sealed-digest and identity binding) over ~35 corpus cases, and
   `bindings/atlas/1.0/` was deleted in the same commit that landed them,
   naming the check covering each v1 normative rule.

   Three things this item predicted wrongly, recorded so the mistake is not
   repeated. The rulespec-side amendments it called for had **already
   shipped** in `791670e` before this entry was written: `#ResolverProofType`
   carried its AI-adjudication member, §3.4 was amended, and
   `spec/rkaf-refspec.md`'s "exactly two validations" was already corrected
   to "at least one independent pair." The fixture sources it named —
   `tools/refspec_atlas.py` and its vendored corpus — **no longer existed**,
   deleted whole by that same commit, along with the `REFSPEC_CHECKOUT`
   cross-repository test this item asked to make fail loud; rulespec's own
   nine native fixtures were the better porting source. And the real gap was
   not the `twoMachineAdjudication` enum, which is an unrelated `EvidenceRole`
   warrant label: the v3 binding had **no adjudication vocabulary at all**, so
   this was introducing a protocol, not porting a check.

   One genuine cross-repo defect surfaced and was fixed upstream: rulespec's
   shipped SHACL enforced only **four** independence axes while its own prose
   and RefSpec's runtime required **five**. Rulespec now checks distinct
   `sealedResponseArtifact` too (`5429465`), and the cardinality bypass that
   made the fifth axis evadable turned out to be a general compiler defect
   affecting every conditionally-required scalar field (`17eba7a`).

   Residual: five-axis independence and the verdict lattice now exist in
   **both** `src/refspec/atlas/model.py` and the binding validator. This
   entry blessed the runtime copy as surviving "meanwhile"; meanwhile is
   over, and the duplication is in scope for item 8's cluster review.

2. **P1 — ring temporal context. Done** (`8c1c3e0`, `165fcc1`, `eeb6a02`).
   Value-ring and legal-identity mappings carry `rkaf:hasEffectivePeriod` →
   `rkaf:EffectivePeriod` on the wire; SHACL and the validator reject a
   dated ring lacking one and an undated ring carrying one, over five
   negative corpus cases verified to fire on the batched fast path. Both
   orphans were retired rather than re-wired: `validate_ring_relation`
   (relation-membership survives in `MappingAssertion.__post_init__` and the
   wire's `dataset.relation` check; context in `_validated_relation_context`)
   and `validate_mapping_supersession`'s full-closure mode (closure is a
   property of a complete distribution, enforced by the `sh:class` range on
   `rkaf:supersedesAssertion` plus `validate.py`'s `dataset.supersession`).

   **This item's edition requirement was not implemented, deliberately.**
   `sourceEdition`/`targetEdition` were not minted: a v3 mapping already pins
   `atlas:sourceRelease`/`atlas:targetRelease`, real registry release IRIs are
   edition-scoped (`…:eurovoc:4.24`, `…:elsst:r6`), and SHACL already forces
   endpoint agreement — an edition literal beside the pin could only agree or
   disagree with it, the same argument that deleted `atlas:assertionStatus`.
   What was missing was the dates, and the dates landed.

   Both defects independent review found here are closed, and both closed by
   deletion rather than by adding a check. The edition strings are **gone from
   the registry** (`9b992ce`): enforcing agreement was not merely unbuilt but
   unbuildable from what the registry models — releases are content-digest
   keyed so nothing derives an edition, a release bundle declares no edition to
   compare against, and `validate_mapping_assertions` is handed assertions and
   evidence but never releases. The only verdict an edition literal could carry
   was "disagrees with the pin". And the legal-identity `effectiveAt`
   **instant** is gone (`3230081`): rkaf has no assertion-scope instant term
   (`PointInTimeException` is a consumer-evaluation anchor, `assertedAt` is
   when the assertion was made, `effectiveDate` belongs to a lifecycle event),
   so rather than widen an instant into indefinite force the source never
   stated, the registry now states `effectiveFrom` plus optional
   `effectiveThrough` for both dated rings and `effectiveAt` is refused as
   unknown. The day-to-instant convention is pinned by `sh:pattern` on
   `atlas:EffectivePeriodShape` where it is enforced — UTC because a crosswalk
   has no forum, and an inclusive end at `T23:59:59+00:00` rather than the next
   midnight, because rkaf's interval is closed and next-midnight would publish
   one instant of a day the source excluded. Seven negative corpus cases now
   cover ring temporal context.

3. **P1 — typed rights and scope. Done, this revision** — see the Executed
   paragraph above. `usage-eligibility.cue` +
   `access-scope.cue` replace loosely-shaped scope JSON; closed enums,
   schema-validated, invalid fixture required.

4. **Conflict and finding records. Done** (`2197c34`), with one half
   deliberately not built. `rkaf:RegistryConflict` is on the wire for the one
   contradiction class v3 detects and can retain: two `atlas:Identifier`
   records claiming one scheme-and-value pair for different resources. A
   distribution carrying that contradiction **and** a conforming conflict
   record naming exactly those entries is accepted — the disagreement is
   published rather than deleted — and the same contradiction without one
   still fails, so the record is load-bearing and no prior refusal weakened.

   **`rkaf:Finding` was not wired, and that is the answer, not a gap.**
   `#Finding` carries a single `rkaf:subject`, but every contradiction v3 can
   retain names two or more entries, so a Finding could only state one
   arbitrarily — the same reason rulespec's own `#RelationFinding` refuses to
   compose `#Finding`. The "refusal records in the v3 acceptance tests" this
   item imagined have no surface: `atlas-acceptance.schema.json` models only a
   passing distribution, and the validator has no warning path — every
   detection raises. The one refusal v3 does retain already speaks rkaf's
   adjudication vocabulary (`valid/adjudication-refused-comparison-record`), so
   a Finding there would be a second name for a published fact. Read this item
   as satisfied by `registry-conflict.cue` alone until a single-subject
   detection appears that something refuses to accept without a Finding.

   The five SKOS conflict classes stay whole-build refusals by design: S46 and
   S27 are integrity conditions of the SKOS Reference, not Atlas rules, and
   Atlas publishes SKOS — a record beside the offending triples would describe
   the breakage without repairing it, and every SKOS consumer would still be
   right to reject the graph.

5. **Ports owed.** SSSOM export: **the promise is deleted** (`546c494`),
   not ported. `relation_sssom.py` reads only `RelationAssertionBundle`, a
   format no production code has ever constructed, so the pinning to a
   verified distribution the README promised was a property the exporter
   could not have; and the `"mapping"` pack kind a port would target has
   never been emitted by any generator, so this was a new feature, not a
   port. No consumer asked for it. If a real mapping-pack producer and a
   real consumer appear, the writer and the promise return together.
   `relation_sssom.py` itself is reviewed with item 8's cluster.

   Explorer/search reachability gate: **the reachability half landed, the
   ranking half is deliberately not ported.** v3 renders no separate explorer
   artifact to reconcile — `explorer.py`, `duckdb_view.py` and
   `parquet_search_view.py` all build from the distribution's own compact
   packs — so v1's property restates as: the compact record identity of each
   role must equal the asserted graph's identity for that role. Nothing was
   checking that. The existing check compared per-role counts and five sampled
   rows per pack, and `recordIds` was computed only to feed a digest, so an
   omitted record, an invented one, and a record duplicated across two packs
   all passed. That is now the `explorer-reachability` gate with a negative
   case.

   The reviewed corpus does not survive contact with the v3 substrate, and the
   measurement is the reason: built against a real compact→Parquet→DuckDB FTS
   view over in-repo CRS evidence, five of seven reviewed entity queries land
   at rank 1, but the one-edit-typo case returns **zero rows** (DuckDB FTS has
   no fuzzy matching) and the prefix case ranks 12th against a reviewed maximum
   of 5 (whole-token matching only). Passing those would mean restating the
   expectations — a check that passes by construction — or adding fuzzy and
   prefix retrieval to the Atlas binding to fit a retired ranker's taxonomy,
   inside the layer SpicySearch owns per REF-022. Two further discoveries make
   the corpus weaker evidence than its name suggests: `maximumRank` carries no
   human judgment (v1 *computed* it from the category and refused any other
   value), and its entity-ring alias cases describe v1 explorer behaviour
   rather than data — v1 synthesised alias forms by splitting a parenthetical
   at render time, and the reviewed concept carries exactly one label. The
   decision is kept falsifiable instead of asserted:
   `test_search_view_matches_whole_tokens_only` fails the day prefix or fuzzy
   retrieval reaches the search view, at which point the corpus becomes
   portable again. Three of its six release identifiers re-derive exactly
   against in-repo bytes; three do not, and ICPSR names a different acquisition
   entirely, so no expectation was invented to cover the gap.

   Three v1 clauses were examined and deliberately not rebuilt: endpoint and
   filter reachability are not independently violable (the RDF-side release
   checks already force them, so no negative fixture can exist), and facet
   non-vacuity would have been wrong, since a release with zero resources is
   legitimate when it carries only mapping endpoints.

6. **Deliberately not adopted** until a running check or second consumer
   demands them: workspaces, warrants (unless P0 closure needs a node
   type), `bridge-*` contracts (SpicySearch's
   `BridgeConsumerRegistration` for `urn:spicysearch:atlas-consumer` is
   owed at agentic-search Stage 2), retention-policy.

7. **Operational.** Stage 1 of the agentic-search plan is sealed
   (REF-022; handoff pins in SpicySearch `ede33a8`); the wire-vocabulary
   waves supersede that seal, so re-seal once — build, views, preflight,
   `spicysearch atlas verify`, one pin-update commit — when the tree
   settles. **The Python floor is decided and raised, this revision:**
   `pyproject.toml` declared `requires-python ">=3.10"` while
   `src/refspec/registry/treasury_tas_fast_book.py:40` needs 3.11+
   (`datetime.UTC`), enforced nowhere — so a fresh `uv` environment resolved
   3.10 and the module failed on import. Raised to `">=3.11"` rather than
   gated: `datetime.UTC` is the one 3.11+ construct in the tree (swept for
   `tomllib`, `ExceptionGroup`/`except*`, `StrEnum`, and native `typing.Self`
   — the last is imported from `typing_extensions` everywhere), so a
   backport would have added a shim to serve a floor nothing wanted. The
   resolver is now the running check: `uv lock` refuses an interpreter below
   the floor, so the mismatch cannot silently return.

   **`ruff` is wired rather than dropped** (`31e3e9c8`, `618cc56f`). It was a
   declared dependency gating nothing — dead structure by the criterion, since
   nothing could fail when it was violated — and the tree was already written
   for it, carrying 30 `# noqa` comments with reasons aimed at a linter nobody
   ran. `make lint` now precedes everything in `make test` (~1s before ~90s).
   The rule families are stated explicitly in `pyproject.toml` and the version
   is pinned, because ruff's own default resolves to 413 rules drawn as subsets
   of ~37 families — a target that moves with each release, so an unpinned
   default would let a new version fail the build with no code change.
   `ruff format` was measured and declined: it would reformat 144 of 438 files
   for no failure class the check does not already catch. Four rules are
   ignored with written reasons, none silenced — notably `SIM300`, which reads
   any SCREAMING_CASE name as a constant and rewrote eleven assertions
   backwards. It earned its keep on the first run by finding two defects rather
   than idioms: a counter in `explorer.py` incremented on every statement row
   and never read (augmented assignment, so pyflakes cannot see it), and a
   helper in the validator regressions annotated `-> Path` that fell off its
   end returning `None`.

   One papercut this exposed twice, still open: `--repin` covers
   `bindingBundleDigest` and the self-referential implementation digest, but
   **not** `REGISTRY_DESCRIPTORS_PROOF_EXPECTED_DIGEST`, which any registry-module
   edit moves through the atlas index. It is hand-maintained, and both times it
   drifted the failure surfaced as nine unrelated-looking producer tests.

8. **Residual legacy runtime, two undecided items.** The `policyFrontier`
   selection path is still live —
   **`policyFrontier` is retired** (`4f71a1f`), the decision this item
   demanded. The evidence: across the repository's entire committed history
   the policy type appeared only in its own two modules, its own two test
   files, and this ledger — zero uses in `output/`, in `research/`, or in any
   fixture, so no published receipt relied on it and nothing outside its unit
   tests ever exercised it. `frontier.py`, `frontier_release.py` and their
   tests are deleted, `_selection_policy` collapses to `explicitObservationSet`
   with the receipt plumbing it fed removed, and a negative test now proves
   the type is refused. Separately, the experimental qualification and
   governance cluster (`qualification.py` provider/admission paths,
   `qualification_batch.py`, `qualification_jobs.py`,
   `qualification_spend.py`, `atlas_scope.py`, `release_snapshot.py`,
   `relation_assertion.py`, `relation_proof.py`, `machine_evidence.py`,
   `subject_admission.py`, `subject_emission.py`, `concept_staging.py`)
   **is retired** (`688f045`, `d3703e5`, `5ed56db`, `844bb08`) — all thirteen
   modules decided, **−34,344 lines** across `src`, `tests`, `tools`, `docs`
   and `portfolio`, `src/` alone −18,348.

   The item-1 residual is resolved by retirement, and the evidence was stronger
   than redundancy. `model.py`'s five-axis independence and verdict lattice
   were reachable only through `CrosswalkBundle`, and the full-distribution
   producer **refuses `twoMachineAdjudication` at intake** — so no verdict that
   gate produced had any route to a published distribution. It was gating a
   pipeline that terminates in a research directory, neither a live
   pre-publication gate nor re-checked downstream, while the binding enforces
   strictly more over 31 adjudication negatives. `model.py` went 1,172 → 228
   lines. `relation_sssom.py` went with it, its only promise already deleted.

   One module was kept by the deletion criterion and then retired by a
   different decision. `concept_staging.py` was the sole running carrier of
   REF-GOV-002's promotion checklist, so the criterion forbade deleting it —
   there was no check to name as successor. That made it a **spec** question,
   answered by retiring §12.4 and REF-GOV-001..007 with it (`844bb08`): only
   REF-GOV-002 had a carrier at all, and that carrier validated a record type
   with no producer, no consumer, and no instance across 67 published runs in
   `output/`; REF-GOV-001 duplicates REF-ENR-006 and REF-ASSIGN-003, which
   REF-ENR-010 already enforces through `concept-proposal.schema.json` and its
   negative fixtures; 003 through 007 had no carrier of any kind. Keeping and
   wiring would have meant building a governance workflow the product does not
   have, and splitting to save 001 would have kept a parallel identifier for a
   rule already stated elsewhere.

   The deterministic six-class candidate generator survived the retirement:
   it and the release adapters it reads moved into `candidate_retrieval.py`,
   which the research benchmarks already consumed — the consolidation this
   entry previously described as intended but unperformed.

### REF-024: Record the cross-product ownership boundary once

- **Date:** 2026-08-11
- **Status:** Accepted as the canonical cross-product boundary; supersedes the
  ownership clauses of SpicySearch
  `docs/decisions/0001-four-product-boundary.md` that assign document capture,
  renditions, text representations, and structural passages to SpicyRegs and
  topic assignments to Rulespec Extrapolator, and the older Rulespec and README
  prose carrying those same assignments. The rest of Decision 0001 stands.

The platform has five products and six ownership rows, extending
[REF-008](#ref-008-count-four-products-and-five-ownership-rows)'s counting rule
with DocSpec. Rulespec Core owns portable schemas, generated types, identity
functions, validators, diagnostics, and conformance fixtures. SpicyRegs
discovers and selects regulatory sources, then publishes `SourceCatalogRelease`.
DocSpec independently consumes that release, captures files, extracts
representations, creates structural segments and evidence coordinates, and
publishes `DocumentRelease`. RefSpec owns vocabularies and publishes Atlas
releases and search views. Rulespec Extrapolator performs Rulespec-based logical
structuring only. SpicySearch joins documents with RefSpec topics, creates
snapshot-specific topic tags, builds disposable indexes, and serves search.

Products exchange immutable releases and installed packages. They never import
sibling source trees or read sibling databases. Nothing shipped to an unowned
upstream repository names an owned product — by import, by path, or by URN — and
a test on the payload proves that before each contribution.

This complements
[REF-022](#ref-022-adopt-the-cross-product-search-topology-and-approve-the-agentic-graph-search-direction)
and changes nothing in it. REF-022 fixes the search topology, makes SpicySearch
the only junction between RefSpec and DocSpec, and already assigns topic tagging
to SpicySearch; that assignment is one row of the wider boundary stated here,
not reopened by it. REF-022 remains the entry governing the agentic graph search
direction and its stage gates.

Other decisions and plans link to this entry instead of restating it. The
duplication is the defect being removed: two independent statements of this
boundary already existed and had diverged over whether declared version bounds
suffice to prove a consumable surface. One decision, cited by identifier rather
than by checkout path, is the fix. This entry changes the day a product's
published release shape changes; another document needing one of its rows is not
that day.

### REF-025: Retain canonical Label.id in the next search view

- **Date:** 2026-08-11
- **Status:** Accepted for the next RefSpec search-view version

The next search-view version retains the canonical `Label.id`. SpicySearch uses
that identifier directly. No consumer-generated substitute identifier is
allowed.

A substitute minted downstream is a second label identity with no producer, so
two products can disagree about which label a row names while each passes its
own checks. Carrying `Label.id` on the wire removes the disagreement at its
source rather than reconciling it afterward. This entry changes the day the
search view stops carrying a canonical label identity; a consumer finding that
identifier inconvenient is not that day.

### REF-026: Build, prove once, sign, serve — the validation cost reset

- **Date:** 2026-08-12
- **Status:** Accepted; carried by
  [plans/validation-cost-reset-plan.md](../plans/validation-cost-reset-plan.md)
  (v3.5), which holds the measurements, review verdicts, and kill-list this
  entry ratifies rather than restates.

**The system is four verbs.** Build a vocabulary distribution; prove semantic
conformance once, at build; sign the result; serve it (Parquet → SpicySearch).
Structure not serving one of those verbs is guilty until a running consumer is
named. The prior regime re-derived everything everywhere: measured on the
32M-quad distribution, independent validation cost ~2h on one core (78% SHACL,
21% rdflib parse, transport integrity 0.25s), a red build spent 94 minutes
phrasing a report the fast path had already detected, and reader-side
re-verification had already drifted (11 gates in the explorer against the
validator's 13) — independent re-implementation reduces assurance over time.

**The seal.** A distribution is sealed by a detached OpenSSH signature beside
it whose payload binds the manifest digest and the acceptance-receipt digest,
so verifying the seal transitively attests that acceptance ran, with which
gates, on these bytes. `verify_seal` is normatively signature + strict
structural read + manifest digest + acceptance digest + symlink/type sweep +
pinned walk of every member, pack, and compact pack + closed-membership
comparison — measured at 0.5s over 1.141 GB. Consumers verify the seal;
they do not re-run the producer's gates. Key custody: offline ed25519 per
docs/seal-design.md §2 (Sigstore is the documented upgrade path). The
independent control in a single-maintainer topology is the scheduled
reproducible rebuild plus one full-validator run against a shipped artifact.
The seal's negative space is part of the claim: it attests that acceptance ran
on these bytes, not that those bytes faithfully transcribe the publisher
sources behind them and not that the captures were complete — source fidelity
is the auditor's separate scheduled job, never a consequence of a valid
signature. This entry is the identifier the SpicySearch plan cites to adopt
`verify_seal` at its admission seam.

**Frequency follows trust boundaries.** Full validation runs at build
acceptance (release workflow; ≥32 GB runner), audit (scheduled), and contract
change — not per read. Red builds fail fast from the batched path's own miss
detection (focused re-validation, cross-mode-equivalent over all 115 negative
cases; audit mode preserved by env var); a kind-covering `--smoke` sample
(92s at full scale) precedes any full pass. The dev suite carries a
wall-clock budget (warn >60s, runaway fail 240s; the 120s line arms when the
suite is next under 60s).

**The rulespec boundary is a package, not a checkout.** Decided package-only,
no monorepo: `rulespec-conformance` ships the compiled schemas, SHACL,
context, closed enums, and the 859-term rkaf registry as importable data;
the eligibility-lattice copies became one import, the vocabulary currency
test now scans against the packaged registry, and the checkout gate is
deleted. An unknown rkaf term is an ImportError at build —
fix-by-construction replacing detection. Guardrails: rulespec stays generic;
rkaf remains the single ontology; RefSpec keeps no local copy of anything
the package exports.

**The operatorAdoption warrant carries an optional referent** (owner
decision, 2026-08-11, after a read-only forensic packet). The obligation that
an adoption name a prior Atlas attestation was introduced with fixtures but
no producer able to satisfy it, tightened an upstream-optional rkaf field,
and canonized as invalid the only thing the real EuroVoc↔LCSH import (2,003
bindings, REF-016-mandated) can emit. `rkaf:basedOnAttestation` is now
optional on that warrant in shapes and validator alike; the adopted artifact
is named by the evidence source record and its digest — the granularity the
shape itself declares addressable. A named referent must still resolve
without cycles; the negative case was re-purposed to a dangling referent
rather than deleted. REF-016 stands unamended. The root cause — a
four-column producer/validator contract mirroring a five-condition shape —
is the standing argument for compiler-emitted checks (boundary-collapse
move 2).

**Executed, each reviewed before landing:** hygiene (`cd769d44`), the
release_model extraction and governance decoupling (`cc5adaaf`), the seal
(`48c155c8`), red-path fail-fast + smoke (`f2ae02ac`), the release workflow
(`ee89f513`), the plan record (`5741d5c2`); the warrant amendment, the
rulespec package (rulespec `0710dcd`..`c584a1d`), and the consumer cutover
land with this revision. Governance archive proceeds as a split, not
whole files — the extraction proved `managed_release.py`, `binding.py`,
`release_graph.py`, and `vocabulary.py` are majority build-path.

### REF-027: The deletion campaign — reuse, RDF explorer, governance workflow, fixture corpus

- **Date:** 2026-08-12
- **Status:** Accepted; executed. The scoping map and the unanimous
  fable+opus wire-wave decisions live in
  [plans/validation-cost-reset-plan.md](../plans/validation-cost-reset-plan.md)
  (v3.6/v3.7).

Four deletions, each verified against a running consumer (or the proven
absence of one) before landing:

**Fixture corpus un-committed** (`41f1bf70`). The generator's one-line
self-seal — hashing its own source into every receipt — made any edit a
512-file diff; it is replaced by a fixed literal, and the 8,339 generated
files (72.3 MB) leave the index. `corpus.json` and `fixtures-receipt.json`
stay committed; a cold checkout rebuilds the tree in ~9s and proves it
against the receipt.

**RDF explorer deleted** (`83bf5d01`, −8,438). `explorer.py` had already
replaced it as the shipped console script; the RDF path had no entry point
and no CI, and its reader carried the 11-vs-13 acceptance-gate drift that
REF-026 cites — resolved here by deletion. The 1,383 lines `explorer.py`
actually consumes moved byte-identical into `explorer_render.py`,
verified by AST closure.

**Candidate-use / accepted-output workflow archived** (`18d104a1`,
−1,818; recoverable in full at `83bf5d01`). `require_candidate_use`
resolved one complete candidate-use row — a selected deployment decision,
its permission row, facet route, and passing coverage report — and
`accepted_output.py` held the sole path from an authorized candidate to an
accepted output. The model was sound; it is shelved because no institution
operates it: the pre-deletion trace found zero build- or serving-path
consumers — the atlas build reads `iter_expressions` with its own
retirement rule, so the machinery was exercised only by its own tests.
`refspec.__all__` shrinks 60 → 55, deliberately. Reviving it means naming
the institution that operates it first.

**Incremental/exact-reuse subsystem deleted** (`74aaafd9`, −3,485; see
the REF-019/REF-020 supersessions). With it landed the corpus-wide
cross-mode SHACL parity sweep (46 cases, release-tier), closing the
engine-parity gap the plan's findings register named.

Net for the campaign: roughly −147,000 committed lines including the
corpus, ~−13,700 in production and test code. Carry-forwards, recorded:
`ManagedReleaseAuthorizationError` is now a public exception raised by
nothing; `IncrementalPackMaterialization` keeps its wire-tied name until
the 3.1 bump; the release workflow's acceptance job needs
`REFSPEC_RELEASE_TIER=1` and a pytest invocation for the parity sweep.

### REF-028: The 3.1 atomic replacement — the wire the campaign could not prove

- **Date:** 2026-08-12
- **Status:** Accepted; executed (`8ba8d8ea` stage A, `cb10a8e8` stage B).
  Scoping in [the plan](../plans/validation-cost-reset-plan.md) v3.6 item
  (4); the three unanimous fable+opus calls in v3.7. Continues REF-027;
  supersedes REF-015.

**3.1 replaces 3.0 atomically, in place.** Precedent `5c6d889a` — git
history is the archive. No external consumer of the distribution format
exists; SpicySearch is insulated by the search view's own pin. Both
conditions the v3.7 decision set were met before the bump: the fixtures
un-commit landed first (`41f1bf70`), so the rename is a 22-file move and
not an 8,340-file diff, and 3.1 was staged on the bounded Federal Register
Thesaurus artifact before anything larger. The re-ordering that decision
recorded held: wire cuts → fresh 3.1 build → *that* is the first sealed
artifact. Sealing a 3.0 build first would have minted the retiring
format's only external consumer.

**What the wire lost.** Node digests on eleven carriers — a triple
restating what the node's own facts already say, on every carrier that
does not derive its IRI from it (the two that do keep it; the rest are
recomputed on demand, so the retained Parquet `content_digest` column
never becomes comparand-less; the shapes are closed, so removal makes the
triple forbidden rather than optional). The compact JSONL wire (~1,250
producer lines, 839 validator lines, and the packs). False proofs:
`shaclDataProof: compiledAgainstPinnedOntologyAndShapes` passed while
those shapes rejected 2,003 evidence bindings; `shaclMetaValidation`, a
`checks` prose list, and an `implementationDigest` the producer compared
against its own constant said the same unprovable thing in three more
registers — none checkable by an independent reader. Reuse constants that
reported "no reuse happened" on every build ever produced.

**What it gained.** A seal-covered served projection: the seal payload
(`refspec-distribution-seal-2`) binds `parquetViewManifestSha256` beside
the manifest and acceptance digests, and `verify_seal` walks the view's
tables; the obvious placement — the construction summary pinning the view
manifest — is a digest cycle, and the seal, written after both artifacts
are final, is the one placement where the dependency runs one way.
Honest receipts: producer validation states which constructor ran, what it
counted, and which bytes those counts belong to; semantic conformance is
the independent validator's verdict, and only that. Two producer
self-agreements became graph comparisons: per-release record counts are
recomputed from the asserted RDF by the new `record-ownership` gate, and
record-identity equality between the served tables and the graph is
proved in both directions with the comparand stated in `validate.py`.
The producer's implementation self-pin — whose only real effect was that
every builder edit failed the next build until repinned — is gone;
`--repin` survives for the six binding-profile digests.

**Proof.** First 3.1 artifact: the bounded FR Thesaurus build,
`urn:ref:atlas:distribution:3.1-bounded-development:44ad80a2…`, manifest
`sha256:9f1f379e…`, view manifest `sha256:638fd2bd…`; independently
validated in 5.9s; byte-reproducible over distribution, generation report
and view; sealed and verified end to end — 4 members, 2 packs, 8 tables,
1,599,155 bytes walked under one signature. Corpus 127 cases / 114
invalid; full suite 2,467 passed at 96.8s.

### REF-029: Contract identity and proof identity are two different digests

- **Date:** 2026-08-13
- **Status:** Accepted; executed (`521ed20c`). Continues REF-028, which left
  `--repin` standing for the six binding-profile digests.

**What `bindingBundleDigest` meant.** One digest over a sorted
path/length/digest inventory of seven binding assets plus every schema: the
ontology, the SHACL shapes, the registry profile map, the coverage proof,
the real-registry descriptor dataset and its proof — and
`fixtures/corpus.json`, the conformance corpus. It was pinned into every
manifest, every acceptance record and every construction summary, and an
independent reader recomputed it from the binding on its own disk and
refused any artifact that disagreed. That refusal is exactly right for six
of those seven. For the seventh it was a category error: adding one
conformance case rewrote the corpus, moved the digest, and invalidated
every artifact on disk — the external manifest pins, the served view's pin,
and the signature over both — for a contract that had not moved a byte. The
corpus is not a rule. It is the proof that the program implementing the
rules behaves as they say.

**Why they separate.** `binding.contractDigest` (renamed) covers exactly
the rules, and it is *derived and checked*: a reader recomputes it and
refuses a disagreement, because a distribution validated against different
rules is a different claim. The acceptance record's new `corpusDigest` sits
beside `validator`, and it is *recorded and never re-derived*: the
acceptance record describes a validation **event**, and an event is
identified by which validator ran and which corpus that validator was
answerable to. Nothing is lost — an auditor asking "what proved this
verdict" reads the receipt; an auditor asking "what was this validated
against" reads the manifest. Two questions that were being answered by one
number, and only one of them could be answered correctly.

**What invalidates artifacts now, and what does not.** A rule change — the
ontology, the shapes, a schema, the profile map, the registry descriptors —
moves `contractDigest`, and every artifact on disk must be reissued against
the new meaning. That is the point. Test growth does not: adding
conformance cases moves `corpusDigest` in newly written receipts and leaves
every artifact already on disk valid, because nothing a new test case says
changes what those artifacts were validated against. The same reasoning
that kept the tools out of the contract in REF-028, applied to the corpus,
in the other direction.

**The fifth self-agreement, with it.** The producer's compiled table of six
binding digests is deleted along with `--repin`. The builder hashes the
binding files it reads at build start and records them; the comparison that
survives is between two readings taken ~25 minutes apart, which catches a
binding edited under a running build. The tripwire that always mattered —
the independent validator recomputing those digests from the binding on
*its* disk — is untouched.

### REF-030: Registrant populations leave the Atlas for the entity registry

- **Date:** 2026-08-14
- **Status:** Accepted; executed. Amends the four-ring adoption (2026-08-04):
  the entity ring survives, its registrant exemplars do not.

**The split that matters.** Not "entities vs. concepts" — the entity ring's
institutional rosters (Treasury FAST Book accounts, CourtListener
jurisdictions, CRS legislative entities, federal hierarchy orgs, FCC bureaus)
are finite, curated, slow-churning, published-by-an-authority reference and
they stay. What leaves is open registrant populations: SAM registrants, CAGE
facilities, NPI providers, CompTox substances. Those are referents with
registry cadence — SAM churns daily against a sealed artifact reissued on
vocabulary cadence — and their bounded exemplars (one 3M UEI record, one 3M
CAGE facility, three NPI rows, one substance) proved the ingestion pathway
during the 2026-08-03 registry audit and then had nothing further to say
inside the Atlas.

**Where they live now.** `refspec.registry.entity_registry_release` builds
the standalone entity-registry object (`tools/generate_entity_registry.py`,
first cut `output/entity-registry-2026-08-03`: 4 releases, 6 records, 8
identifiers, 1 cross-authority relation) from the same pinned captures the
Atlas adapters consumed, under the same URNs (`urn:ref:sam-entity:uei:…`,
`urn:ref:dla-cage-facility:…`, `urn:ref:nppes-provider:…`,
`urn:ref:epa-substance:…`), digest-manifested and tamper-refusing. Consumers
that need to *reference* an entity join by URN; a consumer that needs to
*enumerate* a population reads this object, never the Atlas.

**The running check.** `load_releases` in `tools/generate_atlas_v3_full.py`
refuses any release whose scheme falls under the four registrant authorities
and any release emitting records under the four registrant URN prefixes, by
name of this decision. A loader that reintroduces the authorities — or a
renamed release re-ingesting the same records — fails the build. Pinned by
`test_registrant_population_releases_are_refused`; the artifact side is
pinned by `tests/test_entity_registry_release.py`. The NPPES *layout*
release (structural field definitions) stays in the Atlas: structure is
reference even when the rows it describes are not.

### REF-031: Document populations leave the Atlas for SpicyRegs

- **Date:** 2026-08-14
- **Status:** Accepted; executed. The same criterion as REF-030, applied to
  the other kind of open population.

**The criterion, restated.** A unit belongs in the Atlas when an authority
publishes a finite, curated vocabulary and reissues it on vocabulary
cadence. What leaves is populations the world generates: CBO publishes cost
estimates continuously, FCC ECFS holds six figures of proceedings and opens
more every week, GovInfo issues hundreds of CFR volumes a year. Three
bounded exemplars — 1,058 publications from one pinned 119th-Congress feed,
15 proceedings observed in one 25-filing ECFS page, one CFR package — proved
their ingestion pathways during the 2026-08-03 registry audit and then had
nothing further to say. In the 2026-08-14 search view not one statement in
the Atlas touched any of their 1,074 resources: they were an enumeration
nobody joined against, aging from the day they were sealed.

**Where the acquisitions go.** SpicyRegs, whose README states the boundary
plainly: it "owns source acquisition and source-addressable document
structure," and RefSpec "owns vocabulary releases, concepts, labels,
mappings, redirects." Its source-profile catalog already carries
`fcc-proceeding-v1`, `gao-report-v1`, and `cfr-section-v1` — the document
shapes these three populations are instances of. A consumer that needs to
*enumerate* CBO publications, ECFS proceedings, or CFR packages reads
SpicyRegs; a consumer that needs to *reference* one joins by its publisher
IRI or package identifier, which SpicyRegs mints from the same bytes.

**What stays, and why.** The `gao-report-gao-26-108505` unit stays: it is
not a population but the witness that anchors
`gao-topics-observed-on-gao-26-108505` — the report page is where those
topics were observed, and its live `CrossRingRelationAssertion` is the
evidence for the subject ring's claim. Delete the witness and the topics
lose their provenance. The FCC bureaus, filing types, and access statuses
stay — finite publisher controls, and they share the removed proceedings'
scheme URN, which is why the guard below can only name proceedings by IRI.
`ecfr-cfr-titles`, the GovInfo *collections* list, the CBO *topic codes*,
and every subject and value vocabulary stay. So does every reader module
under `src/refspec/registry/`, every capture, and every fixture: the
parsing knowledge is audit-attested here and the registry audit still reads
those bytes. Only the Atlas unit wiring left.

**The running check.** `load_releases` in `tools/generate_atlas_v3_full.py`
refuses any release whose scheme is `cbo-publication-identifiers` or
`govinfo-cfr-packages`, and any release emitting a resource under
`https://www.cbo.gov/publication/`, `urn:ref:govinfo-cfr-package:`, or
`urn:ref:source-concept:v2:fcc-ecfs-proceedings:`, by name of this decision.
A loader that reintroduces a document authority — or a renamed release that
re-ingests the same documents — fails the build. Pinned by
`test_document_population_releases_are_refused`, which also asserts the
non-refusals that matter: the GAO product IRI and the FCC bureaus sharing
the proceedings' scheme.

**What moves.** The three units leave their adapter groups
(`v3_registry_documents`, `v3_registry_codes`, `v3_registry_nonemitters`)
and the source-fidelity audit, taking two now-unused readers with them; the
planning index marks the three authorities rejected (rejected 4 → 7, planned
33 → 30, 89 rows and 81 modules unchanged); index → descriptors → coverage
regenerate with the proof pin updated, the descriptor RDF and the coverage
summary byte-identical; the corpus receipt reissues over unchanged fixtures;
the registry audit snapshot regenerates with its one declared gap. A rebuilt
distribution loses exactly 1,074 resources, 1,074 labels, 1,059 identifiers,
1,074 source records, and 6 releases — and zero statements and zero evidence
bindings, which is the measurement that made the decision.

**Amendment (2026-08-14, REF-032).** Two claims above did not survive
inspection. First: the FCC bureaus, filing types, and access statuses were
kept here as "finite publisher controls." They are not. All three are
set-distincts over the same single 25-filing ECFS response the removed
proceedings came from — the reader's own docstring records that ECFS
"publishes no dedicated code-list or constants endpoint" — and the bureau
list carries the abolished Common Carrier Bureau beside its successor.
They leave under REF-032 as observed inventories. Second: the
`gao-report-gao-26-108505` witness was kept *because* it anchored the
observed-topics unit. That unit is itself a source observation and has now
left, so the witness leaves with it, and `gao-report-identifiers` joins the
document-population refusal above — by this decision's own criterion a
report page was always a document population. The original entry stands as
written; these two sentences record where it was wrong.

### REF-032: Observed inventories leave the Atlas

- **Date:** 2026-08-14
- **Status:** Accepted; executed. The third split in the REF-030/REF-031
  series, applied to what a unit *is* rather than to what it enumerates.

**The criterion.** The Atlas carries what a publisher wrote down. It does
not carry the distinct values someone scanned out of that publisher's
records. A documented code list, a field dictionary, a published thesaurus,
an account roster — those are reference: the authority states them, is
answerable for them, and reissues them. A `SELECT DISTINCT` over a data
snapshot is an observation *about* a data set. It is exactly as current as
the snapshot, it has no publisher behind it, and joining against it means
joining against whatever happened to be in the rows on the day of capture.
The FAC-versus-NPPES pair states the line cleanly: FAC's API field
dictionary is publisher-written structure and stays; the NPPES *rows* left
under REF-030 while the NPPES dissemination *layout* stayed. Structure the
publisher wrote is reference. Values harvested from data are not.

**The census.** Twenty-nine units leave, carrying 1,970 resources:

- *The regulatory-native family* — 14 units, 1,861 resources: distinct-value
  scans over four SpicyRegs Parquet snapshots
  (`regulatory-native-current/{dockets,documents,federal_register,unified_agenda}.parquet`,
  184 MB) executed inside RefSpec. Six of the fourteen are duplicates or
  strict subsets of documented lists the Atlas keeps — Regulations.gov's
  OpenAPI docket and document types, the Unified Agenda's priority
  categories and rule stages. The three agency-code inventories (196 + 316 +
  191 values) duplicate SpicyRegs's own `agency_stats`.
  `federal-register-unresolved-agency-name` is parse residue: 715 members
  including `"44 CFR Part 64"` and a bare `"Rule"`.
- *The FCC ECFS observed trio* — 12 resources, all set-distincts over one
  25-filing response (see the REF-031 amendment above).
- *The GAO observed pair* — 2 resources: one topic label observed on one
  report page, with RefSpec-minted UUIDv7 identity and
  `publisherConceptIdentityClaimed: False`, plus the report page that
  witnessed it. The reader's own non-Atlas packager states the position
  outright: "This never promotes the result into a concept scheme."
- *Pathway exemplars and minted-identity captures* — 26 resources: three
  rows from a session-scoped EPA browse export with no publisher identity;
  one AGROVOC concept whose declared `mappingReference` role is unreachable
  because its mapping targets are absent from the Atlas; two NALT concepts
  with no enumeration scheduled; the first alphabetical API page of the
  Federal Hierarchy roster, 20 organizations of 1,645, with duplicates.
- *Scraped widgets and false formats* — 31 resources: six GAO CRA
  radio-button widgets; two FERC "accession number formats," one of which is
  a wildcard search string; 19 NRC ADAMS controls of which 12 were regexed
  out of a minified Angular bundle; four ADAMS identifier shapes, one
  inferred from two examples and contradicting its documented sibling.
- *Observed aggregates* — 38 resources: 27 OPM PLUM values set-distincted
  from a 15,777-row personnel roster, duplicating codes the kept
  `opm-ehri-data-standards` unit carries *with definitions*; 11 Treasury
  fund types produced by a `Counter` over the kept FAST Book accounts
  release, matching none of the publisher's three documented lists.

**One split, not a removal.** `federal-register-api-topics-2026-08-03` is
kept, narrowed to the collection the publisher's own payload names. The
pinned capture carries `{thesaurus: 1044, ad_hoc: 6723}`; the thesaurus
collection holds all 1,428 relation statements and the ad-hoc collection
holds harvested document fragments like `"165 as follows:"`. The release now
emits the thesaurus collection only, records `excludedAdHocCount: 6723` and
`emittedCollection: "thesaurus"` in its metadata, and keeps
`completeCapture` scope — complete, of the collection it names.

**The SpicyRegs data-plane dependency is gone.** Removing the
regulatory-native family removes the last place RefSpec's build read
SpicyRegs's acquired records: four Parquet snapshots totalling 184 MB,
pinned as build inputs in the source-fidelity audit and in the registry
source manifest, and re-scanned on every audit run. RefSpec now reads
publisher bytes and RefSpec's own captures, nothing downstream of SpicyRegs.
The boundary the product topology asserts — no RefSpec↔DocSpec edge — is
now a fact of the build graph rather than a claim about intent.

**What stays, and why.** The *documented* twins: Regulations.gov's docket,
document, and submitter types, parsed from the pinned OpenAPI document by a
different reader; the Unified Agenda's priority categories, rule stages,
timetable actions, and legal-authority citation types. Every institutional
roster and thesaurus. The FAST Book's published account symbols, the FAC
field dictionary, the NPPES layout, the GSDM data dictionary, the FERC
docket prefixes and class types and sector and security-level lists — the
FERC readers' other four units all stay. `opm-ehri-data-standards` keeps the
PLUM values that matter, with the publisher's definitions attached.

**The running check.** `_refuse_observed_inventory_release` in
`tools/generate_atlas_v3_full.py` refuses, by name of this decision:

1. Any release whose input pins name the *observation substrate* — the four
   SpicyRegs Parquet snapshots and the capture derived from them, the PLUM
   personnel roster, the two Federal Hierarchy first-page captures, the FERC
   accessibility-tips page, and the ECFS, GAO product, GAO CRA, AGROVOC,
   NALT, EPA, and NRC ADAMS fixtures. This is the strongest of the three
   surfaces: a rename cannot evade it, and different bytes mean a different
   unit.
2. The three scheme strings that named an observation rather than a
   resource: `epa-enterprise-vocabulary:captured-label-tree`,
   `nrc-adams-identifiers:identifier-shapes`, and
   `nrc-adams-native-controls:observed-structure`. A documented successor
   uses the bare scheme and passes.
3. Ten minted namespaces no publisher-written list could occupy —
   `urn:ref:gao-cra-facet:`, `urn:ref:nrc-adams-control:`,
   `urn:ref:nrc-adams-identifier-shape:`,
   `urn:ref:treasury-fast-book:fund-type:`, and the
   `urn:ref:source-concept:v2:` namespaces of the unresolved agency names,
   the FERC accession formats, the PLUM values, and the three agency-code
   censuses.

The guard is deliberately keyed to substrate and to observation-only
namespaces, not to the resources themselves, because every one of the named
follow-ups below lands under a resource an observation just vacated. Pinned
by `test_observed_inventory_releases_are_refused`, which asserts the
refusals, the non-refusal of the documented Regulations.gov and Unified
Agenda twins, and the non-refusal of four named follow-ups.

**The un-guardable surfaces, named.** Four observed units shared *both* the
scheme resourceId and the minted-IRI namespace token with the documented
list that stays: `regulations-gov-docket-type`,
`regulations-gov-document-type`, `unified-agenda-priority-category`, and
`unified-agenda-rule-stage`. Nothing about their emitted shape distinguishes
them from their twins, so only the substrate refusal covers them: a scan of
the same four columns out of *different* bytes, under the twin's scheme and
token, would pass. `federal-register-native-controls` loses all four of its
contributors and is still not guarded by scheme, because the Federal
Register's documented document types and agencies roster belong under
exactly that resource. The same reasoning leaves `fcc-ecfs-native-controls`,
`gao-topics`, `agrovoc`, `nalt-core`, `federal-hierarchy`,
`gao-cra-database-facets`, `treasury-fast-book`, and
`opm-plum-position-status-codes` unguarded at the scheme. That is recorded
here rather than papered over with a guard that would refuse the work this
decision asks for.

**The cross-ring tripwire.** With the GAO pair gone the Atlas emits zero
`atlas:CrossRingRelationAssertion`s. The type stays on the 3.1 wire — that
is a contract, not a census — and the producer still builds one from any
release carrying a cross-ring relation. Following the precedent of the
unemittable-mapping-warrant declaration in the same file, the emptiness is
declared at the emission site and pinned by
`test_producer_emits_no_cross_ring_assertions`, which fails loudly the day a
ring crossing appears and directs whoever trips it to the intended carrier:
a genuine institutional-roster → subject edge, once the Federal Hierarchy
roster is completed and an authority publishes subject assignments against
it. The single instance that existed was never that — it was one document's
own page metadata read twice, a report pointing at a label observed on the
report. The binding's SHACL variant coverage now builds a synthetic
cross-ring pair from two real releases in two rings, so the shape is still
exercised.

**The junction, checked.** SpicyRegs's
`policies/profile-resource-applicability-v0.json` joins its profiles to
RefSpec catalog resourceIds including `federal-register-native-controls`,
whose four Atlas contributors all left. Nothing breaks:
`portfolio/resource-catalog-v0.json` is generated from
`resource-inventory-v0.json`, not from Atlas units, so it is byte-identical
to its pre-REF-032 state and still carries the resource. Running SpicyRegs's
documented check read-only confirms it: the only drift it reports is a stale
RefSpec catalog *digest* pin (`c0bcce73…` checked, `a731fef9…` current) that
predates this change and reproduces identically against RefSpec at HEAD.
`src/refspec/registry/cfr_list_of_subjects.py` was therefore not wired in,
and no capture was fetched.

**Readers: the calls.** Seven readers lost their last Atlas unit and had no
remaining consumer or named follow-up, and were deleted with their tests,
their source-fidelity rows, and their manifest entries:
`regulatory_native_controls.py` (with `tools/capture_regulatory_native_controls.py`
and the four Parquet pins), `gao_topics.py`, `gao_cra_facets.py`,
`agrovoc_thesaurus.py`, `nalt_core.py`, `epa_enterprise_vocabulary.py`, and
`nrc_adams_codes.py`; `src/refspec/atlas/v3_registry_documents.py` went with
them. Their unreferenced fixtures went too, along with both
`research/evidence/regulatory-native-controls-*` capture directories: with the
reader, the capture tool, and every pin gone, nothing could read, verify, or
regenerate them, and the guard exists to keep exactly those bytes out. Git
keeps them, and the follow-ups below re-capture from the publisher anyway.
`federal_hierarchy_orgs.py` and `fcc_ecfs_codes.py` stay, parser-tested and
attested against pinned publisher bytes in the registry audit but wired into
no Atlas unit — the same state `cfr_list_of_subjects.py` has always had.
They stay for a reason the build enforces: their planning rows are the only
entity-ring placements their profiles have, and the 3.1
`registry-coverage.schema.json` requires `codeScheme` and `structureScheme`
to be non-empty in the entity ring. Deleting them would have forced a
binding reissue to accommodate a census fact. `ferc_elibrary_codes.py`,
`opm_workforce_codes.py`, `treasury_tas_fast_book.py`, and
`federal_register_topics_api.py` keep units and stay unchanged. The
verifier's `native-control` comparison kind stays as well: it is a general
capability with its own synthetic suite, and only its SpicyRegs-sourced
declarations left.

**One false claim corrected in passing.** `opm_workforce_codes.py` stated
that the module "never ingests bulk PLUM position rows." The real-data path
parsed all 15,777 of them and then discarded everything but 27 distinct
values. The docstring now says what the code does.

**What moves.** Twenty-nine units leave `v3_registry_codes`,
`v3_registry_large`, `v3_registry_nonemitters`, and the deleted
`v3_registry_documents`, and leave the source-fidelity audit; the planning
index drops fourteen rows with their seven deleted modules and marks
`opm-plum-position-status-codes` and `treasury-fast-book` rejected (rows
89 → 75, source modules 56 → 49, rejected 7 → 9); index → descriptors →
coverage regenerate with both descriptor pins moved (the RDF itself changes
this time: 994 → 984 quads); the corpus receipt reissues; the registry audit
snapshot regenerates at 74 modules with its one declared gap. A rebuilt
distribution loses 8,693 resources, 8,708 labels, 21 identifiers, 8,693
source records, 29 releases, 6 statements, and 6 evidence bindings — of
which 6,723 resources are the Federal Register ad-hoc collection and one
statement is the last cross-ring assertion.

**Named follow-ups.** Capture FCC's published bureau roster. Capture the
Federal Register's documented document types and its agencies roster.
Complete the Federal Hierarchy roster past its first page — that one is also
the cross-ring tripwire's intended carrier. Capture GAO's published /topics
index. Schedule AGROVOC and NALT enumeration, or retire their catalog rows.

**Amendment (2026-08-15, REF-033).** The Federal Hierarchy follow-up above
was recorded against "20 organizations of 1,645." The 1,645 double-counted:
the API's own totals partition 907 total records into 169
Department/Ind. Agency and 738 Sub-Tier — the 907 already includes the
sub-tiers beside the departments. The complete roster landed under REF-033
at 907, witnessed by the API's own per-level totals.

**Amendment (2026-08-15, REF-034).** The census above was re-validated
deletion by deletion — 29 of 29 stand — and two of its justifications did
not. First: the PLUM entry claimed the 27 observed values "duplicat[e]
codes the kept `opm-ehri-data-standards` unit carries *with definitions*."
They do not. The overlap is a string collision with inverted semantics —
EHRI's `CA` is the Board of Contract Appeals; PLUM's `CA` is a Career
Appointment — so no kept unit carries those codes' meanings. The deletion
stands, but on measured irrelevance rather than redundancy: nothing in the
Atlas tags or joins against the 27 values, and the workforce codes that do
matter are carried by the kept EHRI unit with the publisher's definitions.
That the values were counted out of a roster is how they were acquired,
not why they left. Second: the Federal Register split was justified
with "the ad-hoc collection holds harvested document fragments like
'165 as follows:'" — a description true of roughly 1% of its 6,723 members
and therefore not a justification. The split is vindicated by measurement
instead: the publisher's topic facet spans 1,088 slugs; used as filter
conditions against the live API, ad-hoc slugs return zero documents or
HTTP 400 while thesaurus slugs resolve, so the kept 1,044-member thesaurus
collection covers the publisher's tagging surface. A residual of roughly 44
facet slugs is accounted for by neither collection; that open measurement
is recorded here, not membered.

### REF-033: The boundary audit's repair verdicts, and the documented successors land

- **Date:** 2026-08-15
- **Status:** Accepted; executed. Executes the repair verdicts the REF-032
  boundary audit left standing, and closes three of its five named
  follow-ups with documented publisher captures.

**Ring corrections, in the readers' own words.** Two placements contradicted
the text of the readers that produce them. The LDA reader states "None of
these values is a general subject concept merely because it has a readable
label"; the general-issue codes nevertheless sat on the subject ring as a
concept scheme. The NASA taxonomy reader states the roster "is not promoted
to a general-subject concept scheme until an evaluation proves
document-subject value"; no evaluation ever ran. Both move to the value ring
as code schemes, and the catalog kinds follow (`codeList` for both). The
GNIS unit inverts the same mistake in the other direction: three cherry-picked
fields stood in for an identifier authority, when what the publisher actually
publishes is a complete 21-field National File layout — it is now emitted
whole, as the `structureScheme` its `structuralSchema` kind implies. FERC's
class/type rows had used the raw space-joined PDF line as each label; the
parser's recovered four-column structure now supplies the publisher's Type
Description as the label, with the exact line retained in the payload as
provenance of record.

**Subtractions.** What a publisher operates is not what a publisher states.
The PRA search page's five Burden Range rows are paired low/high `<input>`
ids and its OMB Control Number entry is a field shape derived from the
documented convention — form mechanics, still parsed and pinned for drift
checks, no longer emitted (21 → 15). The Census TIGER unit drops its three
example GEOIDs — sample values, not vocabulary (14 → 11). GovInfo's
per-collection `packageCount`/`granuleCount` are live corpus totals, not
facts about the codes; they leave the emitted records for the pinned raw
bytes. The Federal Register roster's per-type document counts survive only
as capture metadata (`facetDocumentCountsAtCapture`), never as members.

**Four deletions.** The ACS geography unit (7) was a byte-span scan of a
mutable API variables listing; the NASBO unit (7) was seven chapter titles
scraped from a report-download page; the SCOTUS unit (7) was four side-nav
links plus three phrases regexed out of page prose; the SEC unit (19) was a
navigation sidebar and six subpage cards. All four are observations of page
furniture under REF-032's own criterion. The ACS and NASBO rows go
`rejected` in the planning index (their readers keep other units); the
SCOTUS and SEC readers had nothing else to say and were deleted with their
tests and fixtures (rows 75 → 78 net, source modules 49 → 50, registry
modules 74 → 75 — two deleted, three added below).

**Completions.** The GSDM domain-value unit grew from a three-element
reviewed transcription (40 values) to every enumeration the publisher's
Domain Values column states inline: 1,009 values across 203 elements, with
the accounting for the 86 elements that defer to external code sources and
the 168 that publish no domain text carried in release metadata. The
codeless bare-value path now fails closed on duplicates exactly like the
pair path (`test_domain_values_fail_closed_on_duplicates_strays_and_lost_columns`).
And the EHRI workbook's AGENCY/SUBELEMENT element — 798 current values that
are an organizational roster, not workforce codes — is split out of the
value-ring release (17,263 → 16,465) and emitted on the entity ring as
`opm-ehri-agency-subelement-2026-08-04`, its 3,004 past values attached as
lifecycle context. The split is exhaustive and digest-preserving
(`test_split_opm_ehri_element_is_exhaustive_and_keeps_the_source_digest`);
the real-count assertions now run whenever the workbook exists instead of
hiding behind an environment variable
(`test_official_ehri_export_shape_counts_and_samples`).

**The documented successors.** Three REF-032 follow-ups close, each from
the publisher's own list rather than an observation of its data:

- *Federal Register* — the machine-readable OpenAPI description's
  `DocumentType` enumeration (4, with display names from the publisher's
  type-facet endpoint), its `PresidentialDocumentType` enumeration (7), and
  the complete 472-agency roster with the publisher's own 225 `parent_id`
  relations carried as native entity relations; the documented `Agency`
  slug enum is cross-checked against the roster and pinned
  (`documentedAgencyEnumCount: 472`).
- *FCC* — the published Offices & Bureaus roster from fcc.gov: 12 offices
  and 7 bureaus. The removed observed inventory had carried the abolished
  Common Carrier Bureau; the published roster does not
  (`test_fcc_roster_replaces_the_observed_bureau_inventory`).
- *Federal Hierarchy* — all 907 organizations the public API returns, as
  five exact 200-record pages plus two one-record filtered responses that
  witness the API's own per-level totals (169 + 738), with the 738
  sub-tier → department relations carried as native entity relations
  (`test_federal_hierarchy_release_is_the_complete_entity_roster`).

They land in a new adapter group (`v3_registry_rosters`, pinned by
`test_complete_roster_adapter_set_emits_1439_resources` — the check's name
carries the census and moved with REF-034's GAO landing), with planning rows,
registry descriptors, source-fidelity specs, and manifest entries. A rebuilt
distribution gains exactly 2,347 resources, 963 relations, and 2 releases
net (75 releases; five roster releases and the EHRI roster added; the four
deleted units and the reviewed GSDM tuple removed; the counts above moved).

**What remains open, and why.** GAO's published /topics index sat behind
an Akamai challenge no pinned capture had then cleared; that note is
superseded — the index landed under REF-034 through the shared Zyte
transport, which returned the publisher's 200 response, and the capture is
pinned byte-exact. AGROVOC and NALT enumeration were never scheduled, and
REF-034 retires their rows: no pinnable publisher release remains to
schedule against. And eCFR's
agency → CFR-chapter assignments stay structurally blocked on the
cross-ring decision — with one material change: the tripwire's intended
carrier now exists in-Atlas. REF-032 pointed
`test_producer_emits_no_cross_ring_assertions` at "a genuine
institutional-roster → subject edge, once the Federal Hierarchy roster is
completed." The roster is completed. The cross-ring decision is now live
rather than hypothetical: the day an authority's subject or chapter
assignments against these 907 organizations are captured, the tripwire
fires and the decision must be made, not deferred.

**Adversarial review, two catches recorded.** First: an adapter note had
attributed the Federal Hierarchy's identifier provenance to publisher
documentation that does not state it — an invented citation. The note now
says only what the API itself publishes (`identifierAuthorityNote` in the
roster release metadata). Second: the roster wave initially emitted the 798
AGENCY/SUBELEMENT rows twice — once inside the 17,263-value EHRI release
and again as the entity-ring roster. The value-ring loader now performs the
split before emission, and its release metadata names the extraction
(`agencySubelementExtracted`); the double emission cannot recur without
failing both `test_official_ehri_export_shape_counts_and_samples` and
`test_opm_agency_subelement_roster_is_an_entity_ring_release`. The review
also retired an unfalsifiable roster claim: the EHRI roster had styled
itself the Atlas's "first complete federal-organization roster" in the same
wave that landed the complete Federal Hierarchy; its metadata now claims
completeness only over what it names — the element's own current values
(`completeCurrentValueRosterOfElement`).

**The running checks.** The nonemitter census is pinned by
`test_complete_nonemitter_adapter_set_emits_6371_resources`; the roster
group by `test_complete_roster_adapter_set_emits_1439_resources` (both
names carry their censuses and moved with REF-034's landings).
Authority-scoped identifier rows are minted only under schemes the registry
descriptors declare as identifier authorities — the roster wave first
minted per-field child schemes no catalog authority backs (the build
refused them; the publisher's ids now travel as notations and verbatim
payload fields), and
`test_emitted_identifier_schemes_are_atlas_identifier_authorities` now
validates every emitted identifier against the build's own authority set at
suite time instead of minutes into a build. The
planning index and coverage summaries by
`test_checked_atlas_index_is_exact_and_exhaustive` and
`test_checked_registry_coverage_is_exact_and_compact`; the descriptor
graph by `test_descriptor_proof_pins_exact_registry_inputs_and_output`. The
source-fidelity audit carries independent re-parses for all five roster
releases, the split EHRI pair, the completed GSDM enumeration, and the
completed 21-field GNIS layout (re-parsed from the pinned PDF with the
merged description cells reconstructed), so the next distribution build is
compared against publisher bytes, not against this entry.

### REF-034: The validation-driven wave — the census re-proved, the documented option lists completed, and the dead rows retired

- **Date:** 2026-08-15
- **Status:** Accepted; executed. Re-validates every REF-032 deletion
  against the live publishers, lands the documented successors that
  validation surfaced, and retires the inventory rows validation proved
  dead.

**The criterion, stated plainly.** Scraping is fine; the methods are fine.
What admits data to the Atlas is not how it was acquired but whether it is
relevant — does a consumer tag or join against it, measured wherever a
measurement exists — and where it belongs: which ring, which product,
which object. An API response, a scraped page, a PDF text layer, a Zyte
fetch, even an observation over data are all acceptable acquisitions for
relevant data; the pinning, verbatim wording, drift refusal, and honest
identity this registry insists on are disciplines about the *fidelity of
the capture*, never rules about the admissibility of the method. When a
documented statement and an observation of the same data both exist, the
documented one wins — a quality preference, not a rule of admission — and
observed relevant data beats a gap. Read in that light, the REF-032
deletions this wave re-validated stand because their data was irrelevant
(measured zero tagging value), duplicative of an equal-or-better source,
or misplaced — not because it was scraped.

**The validation.** All twenty-nine REF-032 deletions were re-checked
deletion by deletion and all twenty-nine stand — with two justification
corrections recorded as an amendment under REF-032: the PLUM "duplicates"
claim was a string collision with inverted semantics (the deletion rests
on measured irrelevance, not redundancy and not method), and the Federal
Register ad-hoc rationale described ~1% of the collection; the split now
rests on the measured facet surface (1,088 facet slugs, the kept 1,044
resolving as filters, ad-hoc slugs returning zero documents or HTTP 400,
~44 residual slugs recorded unaccounted).

**The successors.** Five families land. Each is relevant data placed where
it belongs, and each happens to come from a source the publisher states —
the quality preference above, exercised where a documented source exists:

- *Unified Agenda* — the reginfo XSD's documented option lists, completed
  from 3 emitted of 20 to all 20 (110 values). The reader now censuses the
  schema's "One of the following" documentation blocks and refuses any
  count but 20, which is what turns the family's `completeCapture` claim
  into a check
  (`test_schema_parse_is_a_complete_capture_of_all_twenty_documented_lists`,
  `test_documented_option_list_census_drift_is_refused`); the adapter emits
  one release per list
  (`test_unified_agenda_family_emits_every_documented_option_list`). Two of
  the twenty close REF-032 observed-twin successors: the documented MAJOR
  and RIN_STATUS lists carry `observedTwinSuccessorNote` metadata naming
  the deleted distinct-value scans they replace
  (`test_unified_agenda_successor_releases_state_their_ref_032_provenance`),
  and RIN_STATUS carries the XSD's sentence-case wording verbatim with the
  live export's casing drift noted as the publisher's.
- *GAO CRA* — the deleted search-page radio widgets were form mechanics,
  not the vocabulary; the vocabulary is the numbered form GAO publishes:
  Form 41217's current Rev. 12/24 item 6 rule
  types (five, `Other (specify)` preserved as printed), and the retired
  Rev. 11/17/23 revision's item 8 Priority of Regulation levels (five,
  status `retired`) — the last publisher statement of a list the current
  revision dropped. The dropped-item claim is measured, not asserted: the
  current form's pinned bytes ride as an input on the retired-list release,
  `priority_item_absent` is derived from the parse, and a text-level
  tripwire proves the refusal fires if the item reappears
  (`test_current_form_refuses_if_priority_of_regulation_reappears`,
  `test_gao_cra_releases_carry_both_form_revisions_honestly`). The
  publisher's own download URL misspells "Sumission" and is preserved
  exactly.
- *NRC* — the ADAMS Public Search application's own published PDFs replace
  the REF-032-deleted units, whose defect was never that they were scraped
  but that they invented: controls regexed out of a minified bundle no
  publisher statement stands behind, and an identifier shape inferred from
  two examples against its documented sibling. What lands is the User
  Manual's 22-property
  "Properties in Profile" table with every publisher description verbatim,
  and the official accession-number definition — exactly two documented
  elements, the nine-character ADAMS Item ID left undecomposed because NRC
  documents nothing finer. The 22 is counted, not assumed: the parser
  measures the table's name column from page geometry and refuses any
  added, removed, or renamed row
  (`test_property_roster_is_measured_from_the_page_not_assumed`,
  `test_nrc_releases_are_the_documented_successors_of_the_scraped_units`).
  The API guide's Appendix A (13 API document-property names) is captured,
  drift-checked, and deliberately not emitted; both releases record that
  boundary in `notEmitted` metadata and bound their `completeCaptureOf`
  claims to exactly what they name.
- *Treasury* — the FAST Book workbook's own Intro-sheet fund-group tables
  (eight Part II groups with the publisher's expenditure-account symbol
  ranges, plus Part III's foreign currency group), the documented successor
  of the deleted fund-type `Counter` over the same workbook's data rows.
  Both sheet shapes fail closed in the parser (eight rows and one row
  exactly;
  `test_treasury_fund_groups_are_the_documented_successor_of_the_fund_type_counter`).
- *GAO topics* — the publisher's complete /topics browse index: 30 terms,
  each under GAO's own `/topics/<slug>` path and numeric Drupal taxonomy
  term id, with publisher-authored scope descriptions, on the subject ring
  (`test_gao_topics_release_is_a_subject_ring_concept_scheme`). This closes
  the follow-up REF-033 recorded as Akamai-blocked: the pinned capture came
  through the shared Zyte transport. The identity ruling is
  Wayback-verified: the Internet Archive's 2022-12-31 snapshot carries the
  identical 30 slugs and 30 term ids, so both publisher identifier sets are
  stable 2022 → 2026. The REF-032-deleted unit failed for RefSpec-minted
  identity over one observed label; this one is the publisher's identity
  over the publisher's index. It is also the criterion's worked example:
  scraped HTML, fetched through a commercial anti-bot transport, admitted
  without hesitation — because the data is relevant, the identity is the
  publisher's, and the capture is pinned byte-exact. The acquisition method
  was never the problem.

**The skip, recorded.** The regulations.gov agency roster did not land. The
v4 API accepts only personally registered api.data.gov keys in the
`X-Api-Key` header: `DEMO_KEY` answers `OVER_RATE_LIMIT` before a roster
can be paged, an api.data.gov key issued for another site answers
`API_KEY_INVALID`, and a first-party key arrives only through a per-person
email signup — a credential no pinned, reproducible capture should embed.
The capture spec is written and waiting on a project-owned key; nothing
else blocks it.

**Re-admission candidates the criterion opens — recorded, not decided.**
Two REF-032 deletions carried relevant data whose loss the criterion above
does not require, and both are named here as open owner calls rather than
implemented. First: the regulations.gov agency codes. The data is relevant
— the agency acronym is the docket-ID prefix, the join key every docket
and document identifier starts with — and the documented successor
(the v4 agencies roster) is blocked only on the free API key above. Until
that key exists, the previously deleted observed inventory would be
admissible under this criterion as an honestly labeled interim — observed
relevant data beats a gap — and the owner may take either path: land the
observation now and supersede it when the documented roster arrives, or
wait for the key. Second: the Unified Agenda agency codes (the 191-value
observed inventory). The reginfo XSD documents no agency roster at all —
the twenty documented option lists above are exhaustively censused and an
agency list is not among them — so the observation is the only source
there is. It is relevant the day agenda entries are joined by agency;
whether that join is wanted is the owner's call, and this entry records
the candidacy so the deletion is not mistaken for a verdict on the data.

**A publisher-side spec defect, recorded not membered.** regulations.gov's
OpenAPI description still `$ref`s its five-value `DocumentType` enum from
the Comment schema's `documentType` field, yet the comment type "Public
Submission" is neither in the documented enum nor observable in v4. The
kept documented lists carry the publisher's stated values; the defect is
the publisher's to fix and is recorded here so the omission reads as
observed, not overlooked.

**Retirements.** Validation proved three inventory rows dead, and they
leave the catalog rather than stand as plans nobody can execute. AGROVOC:
the publisher ended versioned downloads in July 2025; only a mutable
`latestAgrovoc/` directory remains, so no pinnable publisher release
exists to schedule. NALT: frozen at a 2024 snapshot with the per-year
editions gone — same verdict. EPA's Enterprise Vocabulary closes
permanently: no distribution, session-scoped exports, and broken detail
pages. Git keeps the rows; the catalog stops carrying them (89 → 87
resources, three concept schemes leave the descriptor graph).

**Adversarial review, applied.** The wave was reviewed adversarially and
every verified finding landed with a mutation check. Two deserve naming.
The vacuous assertion: the NRC release test guarded the refused
`MLYYDDDNNNN` decomposition with `"MLYYDDDNNNN" not in
str(sorted(...))` — `sorted()` of a string is a character list, so the
assertion could never fire; it now asserts against the string itself and
was proven to bite by mutation. The tripwire negative: the GAO CRA
dropped-item refusal gained the reviewer's prescribed negative test — a
retired-form page merged into a copy of the current form's text — proving
the parse refuses rather than trusting a hardcoded flag. The review also
made the NRC property count measured (page geometry, above), stopped the
API guide's Get Document parameter regex from swallowing following bullets
(a second parameter is now roster drift,
`test_get_document_second_parameter_is_roster_drift_not_swallowed_text`),
added the Treasury Part II eight-row guard, aligned the fund-group
docstrings with the whitespace the code actually strips (the General Fund
cell reads `'0000-3899 '`), and deleted the review's listed tautological
assertions rather than letting them stand as coverage theater.

**The guards, re-run.** Every new release passes the three REF-030/031/032
refusal guards under its clean naming — same publisher resources, none of
the refused substrate paths, scheme strings, or minted namespaces
(`test_documented_successor_releases_pass_all_three_atlas_refusal_guards`,
`test_new_releases_pass_the_ref_032_guards_and_mint_no_identifier_rows`,
`test_roster_releases_pass_the_generator_refusal_guards`), and none of
them mints an authority-scoped identifier row: publisher slugs, term ids,
and symbol ranges travel as notations and payload fields only.

**What moves.** The planning index gains four rows and three source
modules (rows 78 → 82, source modules 50 → 53) and flips
`treasury-fast-book` off `rejected` (11 → 10): the rejection named the
observed fund-type Counter, and the workbook's own documented list now
ships under that row. The catalog trades three retired rows for the GAO
CRA form row (89 → 87); the descriptor graph regenerates at 964 quads
(983 before) with both proof pins moved; index → coverage → descriptors →
binding fixtures regenerate to stability. The source-fidelity audit gains
an independent re-parse for every new construction unit — seventeen more
`_unified_agenda_xml_source` rows, two GAO Form 41217 PDF comparisons
(the retired-list comparison re-verifies the dropped item on the current
revision's bytes), two NRC APS PDF comparisons, the fund-groups workbook
comparison, and the GAO topics HTML comparison — each reconstructing the
emitted rows from pinned publisher bytes with stock operations, verified
against the adapters' emissions before landing. The registry source
manifest records the three new reader modules with their pinned captures
(78 modules), and the real-data audit passes with its one declared eurovoc
gap. A rebuilt distribution gains exactly 23 releases (75 → 98), 137
resources, 138 labels, and 137 source records, and zero identifiers,
relations, statements, or evidence bindings — the whole wave is publisher
vocabulary, not graph structure.

**The running checks.** The code-adapter census moves to
`test_loads_every_supported_small_registry_source_at_measured_counts` at
63 releases and 1,579 resources; the nonemitter census to
`test_complete_nonemitter_adapter_set_emits_6371_resources`; the roster
census to `test_complete_roster_adapter_set_emits_1439_resources`. The
planning and coverage summaries are pinned by
`test_checked_atlas_index_is_exact_and_exhaustive` and
`test_checked_registry_coverage_is_exact_and_compact`, the descriptor
graph by `test_descriptor_proof_pins_exact_registry_inputs_and_output`,
and the GAO CRA catalog landing retired its own scaffold: the
`PENDING_CATALOG_RESOURCE_IDS` pin deleted itself the day the catalog row
landed, exactly as its comment directed.

### REF-035: Mapping evidence has two axes; standing governs warrant and recoverability governs default serving

- **Date:** 2026-08-15
- **Status:** Accepted; the cheap structural checks execute in the 3.1
  validator. Payload and pin fields that change the binding remain recorded
  work, not an implicit contract edit.

**The decision.** Mapping evidence has two independent axes, not one quality
rank. *Standing* asks whether the asserter owns either endpoint vocabulary. It
is computable from the graph RefSpec already ships:
`AtlasResource -> atlas:inScheme -> atlas:ResourceScheme ->
atlas:sourceDescriptor -> atlas:RegistrySource`. Standing decides which
evidence warrant tells the truth. *Recoverability* asks whether an independent
reader can derive the claim again from bytes RefSpec did not author.
Recoverability decides what RefSpec serves by default. A claim can have strong
standing and poor recovery, or no standing and excellent recovery; collapsing
the two questions hides exactly the distinction evidence is meant to preserve.

The evidence tiers are:

1. **E1 — one publisher owns both vocabularies.** Preserve the publisher's
   assertion as `publisherAssertion`; serve it by default.
2. **E2 — a publisher maps its vocabulary into another publisher's
   vocabulary.** OCLC FAST-to-LCSH is the current example. A verbatim predicate
   remains `publisherAssertion`; an admitted predicate translation is
   `operatorAdoption`. Both are default-served. The assertion describes the
   asserting publisher's record only. It never establishes bilateral
   agreement.
3. **E3 — a third party owns neither endpoint.** Wikidata and UMLS are the
   examples. Admit only a verbatim pinned claim as `operatorAdoption`, and only
   through an opt-in graph.
4. **E4 — RefSpec adjudicates the relationship.** Use `humanReview` or
   `twoMachineAdjudication`, assert the weakest predicate the evidence
   licenses, and keep it opt-in until the adjudication record is satisfied.
5. **E5 — graph closure.** An inferred edge is never an assertion. It belongs
   only in the derived graph and remains opt-in.

The non-obvious ordering is deliberate: **E3 outranks E4 by default**. A pinned
third-party artifact is checkable against bytes RefSpec did not write; RefSpec's
own adjudication has no external comparand. E3 loses that advantage when the
artifact cannot be pinned, its method is undisclosed, or either endpoint does
not resolve. This ordering does not grant a third party endpoint ownership. It
states why its recoverable claim is stronger evidence than our unrecoverable
judgment.

**Predicate rule.** RefSpec serves the weakest admitted predicate in the
semantic ring that the publisher's definition of its own predicate supports.
If no admitted predicate states the source claim without adding meaning,
RefSpec refuses the mapping and records the refusal. The three outcomes are:
verbatim preservation; explicit adoption with `operatorAdoption`, source and
target predicate IRIs, and `adoptedBy`; or refusal.

Several tempting rewrites are never honest. `owl:sameAs` merges properties as
well as identity and is not an Atlas mapping substitute. “See also” and
“derived from” do not license `skos:relatedMatch`, which is itself a positive
semantic claim. MARC `$w nnd` cannot be promoted. No weaker predicate can be
rewritten to a stronger one. The value, entity, and legal-identity rings each
admit exactly one mapping predicate, so a non-identity source claim in those
rings has no weaker fallback and must be refused.

**Direction and inverse.** Direction belongs to the attestation, not the
proposition. Assert the row once in the direction the evidence states; a
consumer may serve both directions when the predicate is symmetric by
definition. Minting a second assertion fabricates an attestation nobody made.
For E2 it also changes the speaker: turning OCLC's FAST-to-LCSH statement into
LCSH-to-FAST would attribute OCLC's unilateral claim to the Library of
Congress.

**Transitivity.** RefSpec never asserts closure: a closure row has no attestor
and no source record. RefSpec always measures it. Before FAST, the binding
measured 5,939 inferred exact-match pairs; with FAST it measures 13,001. The
FAST join has 1,605 shared LCSH targets, 1,801 components, 2,013 genuinely new
pairs, and zero cycles. RefSpec materializes selected closure rows into the
derived graph only when a named consumer states which rows it needs. Query-time
path expansion is always permitted and is not materialized closure.
`skos:closeMatch` never closes; SKOS S45 gives transitivity only to
`skos:exactMatch`.

**Default serving.** The default view is computed, never declared: the row must
be in the asserted graph; its `rkaf:evidenceRole` must be one of
`officialSourceMetadata`, `formalAdoptionEvent`, or `structuralEvidence`; and
the asserter's standing must not be `none`. Those facts already ship in the
assertion, evidence binding, resource scheme, and registry descriptors. An
extra “trusted” flag would be unfalsifiable metadata and is forbidden.

**Failures this decision legislates against.** Each failure has a running or
required check:

- silent predicate rewriting — the predicate-translation gate compares the
  publisher claim, asserted predicate, admitted translation, and `adoptedBy`;
- unfalsifiable metadata — serving is computed from graph columns rather than
  a producer-declared rank;
- invented citations — source fidelity independently reconstructs every
  evidence locator, digest, payload, and mapping triple from pinned bytes;
- unmeasurable coverage — emitted, rejected, unmatched, and inferred counts
  are pinned and recomputed;
- structure without a running check — every new rule lands with a rejecting
  conformance case;
- retroactive integrity breakage — every build runs a corpus-wide SKOS S46
  preflight, because a new `skos:exactMatch` can merge components and invalidate
  a `skos:relatedMatch` in a release nobody edited. FAST is S46-safe today only
  because the endpoint filter leaves its exact-match and related-match subject
  sets disjoint. That is an artifact of the filter, not a property of FAST.

**Contract ledger.** The current 3.1 contract already carries the complete
warrant taxonomy, E3 adoption, warrant-based serving inputs, the facts needed
to compute standing, derived materialization, and the predicate-translation
record. Four rules require only executable checks: the predicate-translation
gate, the standing gate that refuses `publisherAssertion` when the attestor
owns neither endpoint, canonical IRI direction for derived symmetric rows, and
the corpus-wide S46 preflight. The first three now have named negative
conformance cases; S46 was already global in both producer preflight and the
portable validator, with direct, reverse, and transitive conflict cases.

Four changes require a future binding revision and are **recorded only** here.
First, close the `operatorAdoption` payload: it currently carries edition,
predicate, and source adoptions distinguished only by unvalidated JSON. This is
the highest-value contract change. Second, put candidate accounting on the
wire. Third, close `decisionBasis` to a vocabulary. Fourth, add `retrievedAt`
and `license` to `RegistryInputPin`; an explicit license is a precondition for
admitting third-party crosswalks. None of those fields is smuggled into 3.1 by
this decision.

### REF-036: Public crosswalk survey — capture GEMET-to-EuroVoc; record the definitive rejects

- **Date:** 2026-08-15
- **Status:** Accepted as the REF-035 companion. Records the survey result;
  does not add a mapping release.

**Capture next.** Eionet publishes GEMET crosswalks under CC BY 4.0. The
GEMET-to-EuroVoc distribution has 1,938 assertions: 1,683 exact, 217 broad, and
38 narrow, covering 34.18% of GEMET concepts. The GEMET-to-AGROVOC distribution
has 1,199 assertions: 1,188 exact, 5 close, 4 broad, and 2 narrow, covering
21.48%. The EuroVoc set is the one usable now. AGROVOC is not in the current
corpus because REF-034 retired its exemplar.

**Do not research these again without new publisher evidence.** The survey
rejected:

- UMLS, because its license restricts redistribution and therefore also kills
  the proposed MeSH hub;
- MeSH-to-SNOMED, because it depends on UMLS plus SNOMED affiliate licensing;
- Wikidata as an authoritative mapping, because CC0 solves reuse but not
  provenance: its community asserted equivalences are E3 claims the vocabulary
  owners never made;
- VIAF and ISNI, because they reconcile names rather than subjects;
- UMTHES content, because CC BY-NC blocks commercial use, while mapping-only
  URIs remain a possible future input;
- ICPSR, because it publishes no machine crosswalk and uses CC BY-NC;
- ELSST R6, because CC BY-SA permits reuse but the release contains zero
  external mapping predicates;
- GCMD, the NASA Thesaurus, and DOE OSTI, because none publishes a crosswalk
  distribution;
- NAICS-to-PSC, because neither publisher publishes it and award co-occurrence
  is not equivalence;
- NAICS 2022-to-SIC/ISIC, because only older-edition concordances exist and
  chaining editions would be an Atlas derivation;
- CRS-to-LCSH, because no distribution exists;
- Federal Register topics-to-Federal Register thesaurus, because the common
  publisher supplies no identifier bridge;
- agency-name matching across Federal Register, SAM, OPM, and eCFR, because no
  common publisher identifier exists and inferred identity is refused; and
- GAO topics, because GAO publishes no mapping dataset.

**Consequence.** For most vocabulary pairs RefSpec holds, no publisher
crosswalk exists. E4 adjudication is therefore the only remaining path. The
adjudication record in REF-035 is not optional explanatory metadata; it is the
load-bearing evidence for most future mappings.

### REF-037: The publisher-alignment acquisition wave lands seven mapping releases and the first current cross-ring carrier

- **Date:** 2026-08-15
- **Status:** Accepted. Licensing is recorded evidence, not an admission gate;
  REF-035 standing and recoverability decide warrant and default service.

**The decision.** Admit the mappings and native relations whose exact publisher
bytes and contentful endpoints support them. Record licensing exactly as source
evidence; do not use it as an admission gate. Keep every omitted row counted,
and never replace missing publisher content with a stub. This entry executes
REF-036's GEMET capture and supersedes both its “does not add a mapping release”
state and its licensing-based UMTHES rejection. It does not reopen inferred
name matching, community equivalence, or unowned crosswalks.

**Library of Congress.** The pinned 239,565,667-byte LC external-links ZIP
contains 802,592 LCSH external-authority assertions and states **“CC0 1.0
Universal.”** LC owns the LCSH endpoint, so the mapping release is E2. The
binding's explicit adoption table translates the four LC MADS/RDF external-
authority predicates to `skos:exactMatch`, `skos:closeMatch`,
`skos:broadMatch`, or `skos:narrowMatch`. The release emits 801,992 mappings:
534,968 to FAST and 267,024 to the other captured vocabularies. It omits 600
rows only because 469 LCSH source concepts are absent from the separately
pinned current LCSH bulk file.

LC publishes 792,166 authoritative target-label statements for 792,134 target
IRIs with no language tag. The first implementation withheld those endpoints.
The owner then directed a deterministic recovery: each target authority has a
fixed recorded language convention, every resulting lowercase BCP 47 tag and
rule stays in the native payload, and an unclassified label still fails closed.
Fifteen target endpoint releases now carry the mapping-selected AGROVOC, BNCF,
BNE, FAST residue, Getty AAT and ULAN, GND, Homosaurus, NALT, NDL Names and
Subjects, PeriodO, RAMEAU, Wikidata, and YSO records. Their source capture has
792,166 labels, which resolve to German, English, Spanish, Finnish, French,
Italian, or Japanese. The releases collectively emit 353,706 resources. The
FAST endpoint release emits 96,944 resources after 11,587 resources with
stronger OCLC publisher content move to the OCLC-owned endpoint release. The
LCSH dependency release carries 359,728 additional contentful subjects.
This is a deliberate Atlas 3.1 label-contract change: labels are no longer
English-only, but remain non-empty, explicitly language-tagged, canonical
lowercase BCP 47 literals with at most one preferred label per language.
Definitions and notes remain English-only.

**OCLC and the Publications Office.** OCLC's pinned FAST bulk is licensed under
the **“Open Data Commons Attribution License (ODC-By) v1.0.”** It contains
935,540 admitted topical relations or mappings: 311,890 `schema:sameAs`,
468,479 `skos:relatedMatch`, and 155,171 topical `rdfs:seeAlso` rows. The first
two mapping predicates reconcile against the later MARC-derived FAST adoption:
64,452 held-endpoint claims occur in both sources, nine occur only in bulk, and
twelve occur only in the current release. The E2 bulk mapping release emits
only those nine bulk-only `skos:relatedMatch` claims, so it does not double-
assert a claim. The current FAST-to-LCSH release holds 64,464 OCLC claims. It
emits 40,274: all 1,683 adopted exact matches and 38,591 verbatim related
matches. The producer records but refuses 24,190 OCLC `relatedMatch` claims
whose exact pair LC independently publishes as a hierarchy claim. Emitting
both would violate SKOS S27. The canonical refused-pair list has the frozen
digest
`sha256:fc9afdc9c1da43839d133ff0efe409dd0c6c0624152bacdfb65e9bd9320653bd`;
a changed count or pair fails producer loading. The LC mapping release remains
the declared reconciliation dependency, not an OCLC evidence input. S27
filtering leaves one OCLC change archive with no admitted assertion. That
archive is also a declared reconciliation dependency rather than a mapping
evidence input; the mapping release digest covers only the four OCLC artifacts
that prove retained assertions.

The native endpoint release retains publisher content for both endpoints of
47,049 FAST-to-FAST `rdfs:seeAlso` rows. It emits none of those rows as semantic
relations: `rdfs:seeAlso` is navigational, Atlas 3.1 has no matching semantic
predicate, and the binding permits `atlas:thesaurusRelated` only when the pair
also has a hierarchy path. The producer's real hierarchy check finds zero such
pairs; the empty frozen list has digest
`sha256:37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`.
The release also counts 31,932 rows whose 668 FAST targets lack publisher
content, 76,190 Wikipedia targets for which the file supplies links but no
target records, two non-topical `rdfs:seeAlso` rows, and two `owl:sameAs` rows.
Its 45,929-resource endpoint release owns the 11,587 exact FAST IRIs that also
occur in LC's endpoint-label capture because OCLC owns and best documents FAST.
No omitted target becomes a stub.

The remaining seventeen EuroVoc alignment files contain 22,710 assertions.
The alignment pages state no license for those files; the record therefore says
**“publisher states no license”** and names Commission Decision 2011/833 as the
general reuse basis, including its third-party-rights limit. The two held pairs
are E2 Publications Office claims. EuroVoc-to-GEMET holds 2,035 publisher
assertions and emits 1,998 (1,919 exact and 79 close). It records but refuses
37 close matches that conflict with the combined GEMET/EuroVoc `exactMatch`
components under SKOS S46. EuroVoc-to-MeSH emits five exact mappings.
Every other portfolio row remains counted and unemitted because its source
release, target release, or exact endpoint is not held. The five MeSH objects
retain the publisher's HTTP identifiers in evidence and use the independently
verified HTTPS endpoint identifiers in the assertion.

**GEMET and UMTHES.** The versioned GEMET 4.2.3 RDF gzip contains 9,658 mapping
rows under **“Attribution 4.0 International (CC BY 4.0).”** GEMET owns the
source endpoint, so its mappings are E2. GEMET-to-EuroVoc holds 1,938 publisher
assertions and emits 1,936 in the publisher's direction: 1,683 exact, 215 broad,
and 38 narrow. It records but refuses two broad matches that conflict with the
same `exactMatch` components. The combined frozen refusal list contains all 39
publisher divergences, so an unlisted S46 conflict fails producer validation.

The owner separately directed capture of real UMTHES endpoint content despite
the recorded non-commercial term. The deterministic publisher-response archive
pins 3,365 of 3,378 requested concepts, 17,243 German and English publisher
label claims, and the publisher's German **“CC BY-NC 4.0 (Namensnennung –
Nicht-kommerziell)”** and attribution wording. Thirteen endpoints return HTTP
404. The endpoint release emits 17,241 normalized labels and 4,900 of 13,060
native relations whose targets are also held; it omits 8,160 relations outside
the selected subset. Fifty reciprocal `skos:related` statements form 25 pairs
that the same held release also connects through its hierarchy. The endpoint
release preserves those authored associations as `atlas:thesaurusRelated`, as
required by SKOS S27, and freezes the 25-pair list at
`sha256:47d7ff80a1ec4525cec72a723b6100182f8cc210031beef54d1d4bebfb4f732b`.
The producer refuses a changed count or pair. GEMET-to-UMTHES emits 3,470
mappings (3,469 close and one exact) and omits the thirteen unavailable
targets. AGROVOC, DBpedia, and other unheld GEMET targets remain counted and
unemitted. Licensing remains recorded, not gating.

**Northwestern/Galter MeSH-to-LCSH.** The DOI release states **“Creative
Commons Public Domain Mark 1.0.”** Its publisher page declares 13,453 records;
the exact ZIP contains 13,329. The reader finds 13,270 unique translatable
candidates and emits 13,251 mappings against 12,694 current MeSH subjects and
12,844 held active LCSH endpoints: 13,053 exact, 134 broad, 35 narrow, and 29
related. Northwestern/Galter owns neither vocabulary, so these claims are E3
`operatorAdoption` evidence and remain opt-in under REF-035.
The 12,844 active LCSH objects resolve across the already held EuroVoc endpoint
subset (642), the LC external-links endpoint release (12,186), and the
Northwestern-selected residue (16). The Northwestern endpoint release therefore
mints only 16 resources and carries two native broader relations; all 13,251
mappings remain, with 13,235 repinned to the existing LCSH owners.

The MeSH release does not change the Atlas 3.1 wire. The current binding
already requires an explicit source-predicate translation record and validates
the publisher predicate, asserted predicate, and adopting actor. Adding the
four `ad750` translations to exact, broad, narrow, and related match extends
that executable table. It does not add a field, change graph closure, or relax
endpoint checks. REF-035's future work to close the JSON adoption payload
remains future binding work; this release does not smuggle it into 3.1.

**Federal publisher relations.** The complete eCFR administrative roster adds
316 entity resources and 163 publisher nesting relations. Its 487 published
CFR references group into 446 distinct entity-to-legal-identity
`atlas:referencesLegalIdentity` assertions against held CFR title resources.
This is the institutional-roster crossing REF-032's zero-state tripwire named
as its intended successor. The tripwire therefore retires and a positive test
pins this carrier at 446. REF-032 remains the authority for the rejected
observed inventories; only its “no current cross-ring carrier” state ends.

The Federal Hierarchy-to-Treasury join also lands. The two federal publishers
share 130 CGAC Agency Identifiers across 3,544 FAST Book rows and 3,543 distinct
Treasury Account Symbols, producing 85,462 same-ring `atlas:relatedEntity`
assertions. They claim only a shared CGAC code, never identity or
administration. eCFR, the Federal Hierarchy API, and the Treasury FAST Book are
recorded as **“US federal public domain (17 USC 105) with no explicit CC
license.”** These native roster relations do not receive an REF-035 E-tier;
the tiers classify vocabulary mappings.

**The running proof.** Every new construction unit has an independent source
reader over its exact pinned bytes. The source manifest adds the LC and OCLC
archives, all seventeen EuroVoc alignment files, GEMET, the Northwestern
MARCXML ZIP, the composite UMTHES response archive, eCFR agencies, and
GAO-09-205. Catalog, index, descriptors, coverage, generator proof pins, and
binding fixtures regenerate in that order. The corpus-wide S46 check, exact
mapping-evidence comparison, cross-ring predicate gate, canonical-language
negative fixture, and source readers remain the executable boundary; the
counts above are failures, not descriptive estimates.

The producer derives candidate IRI spaces and exact resource owners from the
loaded releases before adapting acquisition endpoints. An existing exact IRI
wins. For a duplicate among new endpoint captures, target-publisher content
wins; equal-quality candidates use stable release-key order. The suite loads
the complete producer release set and fails if any resource IRI has two owners,
then verifies that every unchanged mapping names the selected endpoint release.

### REF-038: The regulations.gov agency roster lands, and reviewed identity claims govern the agency projection

- **Date:** 2026-08-16
- **Status:** Accepted and executed. The pinned reader, entity roster,
  identifier census, 321-assertion entity mapping release, pure projection
  builder, producer, portfolio chain, Atlas binding, and Parquet view are
  registered and checked together.

**The roster closes REF-034's credential barrier.** The owner supplied a
`REGULATIONS_GOV_API_KEY`, and the publisher returned 331 records from
`https://api.regulations.gov/v4/agencies`. The pinned response has digest
`sha256:28ab9f5422dd27fc7906ddc696e8e7811b11056822f370bcee7ea18a28418fa2`,
length 91,408 bytes, and retrieval time `2026-08-16T04:53:51Z`. The key travels
only in the `X-Api-Key` header; no capture, release, evidence artifact, or URL
contains its value. The reader refuses digest, length, record-count, and field-
shape drift. The release emits 331 entity resources and 160
`atlas:parentEntity` relations to 17 distinct publisher-named parents. It keeps
the regulations.gov `id` as notation and as the docket-ID prefix in native
data, never as an Atlas identifier row. It records the endpoint as
`undocumentedEndpoint: true`, requires recapture and semantic diff before an
update, and records **“US federal public domain (17 USC 105) with no explicit
CC license.”** The publisher roster now supplies the relevant inventory, so
REF-034's question about re-admitting the former observed inventory is moot.

**The identifier census is the first pass; per-value review is the second.**
Equality between identifiers issued under the same authority forms a direct
bridge by default. No such cross-roster bridge occurs in this five-roster
census. RefSpec may separately adjudicate equality between publisher-minted
agency acronyms under REF-035 E4. Each accepted identity must retain the exact
two source records, `humanReview` warrant, reviewer, decision date, decision
record, approved relation, basis, both publishers' verbatim names, and a
specific reasoning sentence. This is a RefSpec decision, not a publisher
assertion. Equal strings from different identifier authorities remain refused,
including Federal Register numeric ID versus CGAC, Federal Register slug versus
eCFR slug, and OPM EHRI code versus agency acronym.

The owner amended the earlier abstention rule: **“It's not a guess if it's
obvious.”** Abstention now means that no defensible answer exists, not that no
identifier was handy. Roster-wide fuzzy name similarity remains banned.
Per-value comparison of publisher-stated names, obvious name variants, acronym
expansion corroborated by the name and parent, and parent context is an E4
decision. A value abstains only when publisher names cannot break a genuine
collision or no held roster contains the same entity. Each abstention states
which reason applies and records the closest rejected candidate when one
exists.

**The five-roster census is reproducible.** The exact identifier inventory is:

| Roster | Identifier kind | Claims | Distinct values | Collision values |
| --- | --- | ---: | ---: | ---: |
| Federal Register, 472 resources | Numeric ID | 472 | 472 | 0 |
| Federal Register, 472 resources | Slug | 472 | 472 | 0 |
| Federal Register, 472 resources | Short name | 419 | 409 | 10 |
| Federal Hierarchy, 907 resources | Organization ID | 907 | 907 | 0 |
| Federal Hierarchy, 907 resources | FPDS agency code | 906 | 743 | 162 |
| Federal Hierarchy, 907 resources | CGAC Agency Identifier | 908 | 143 | 141 |
| Federal Hierarchy, 907 resources | Legacy FPDS office code | 472 | 463 | 9 |
| OPM EHRI, 798 resources | Agency-subelement code | 798 | 798 | 0 |
| eCFR, 316 resources | Agency slug | 316 | 316 | 0 |
| eCFR, 316 resources | Agency short name | 242 | 241 | 1 |
| regulations.gov, 331 resources | Agency ID | 331 | 331 | 0 |

The complete cross-roster equality census is:

| Left kind | Right kind | Disposition | Shared | Edges | Unambiguous | Ambiguous |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Federal Register numeric ID | CGAC | Refused: different authorities | 52 | 126 | 1 | 51 |
| Federal Register slug | eCFR slug | Refused: different authorities | 252 | 252 | 252 | 0 |
| Federal Register short name | OPM EHRI code | Refused: different authorities | 3 | 3 | 3 | 0 |
| Federal Register short name | eCFR short name | E4 acronym adjudication | 238 | 249 | 229 | 9 |
| Federal Register short name | regulations.gov ID | E4 acronym adjudication | 279 | 287 | 271 | 8 |
| OPM EHRI code | eCFR short name | Refused: different authorities | 3 | 3 | 3 | 0 |
| OPM EHRI code | regulations.gov ID | Refused: different authorities | 3 | 3 | 3 | 0 |
| eCFR short name | regulations.gov ID | E4 acronym adjudication | 200 | 201 | 199 | 1 |

The first-pass identifier paths cover 279 regulations.gov IDs. Its 52-value
residue contains one identifier collision (`FS`) and 51 values without an exact
identifier path. These are first-pass results, not final abstentions. The dated
artifact in
`research/evidence/agency-identifier-census-2026-08-16/` records every equality,
collision, endpoint, and first-pass residue value. Its identifier-census digest
remains
`sha256:98ee78e352f019a4b33090f0397fdf145c6876d7f6033508172db144912d9420`.

**The second pass adopts 42 of the 52 residue values.** Exact publisher-name
equality resolves 27; obvious publisher-name variants resolve 11; publisher
name plus parent context resolves `FS`; and acronym expansion corroborated by
publisher name and parent resolves three. The remaining ten values have no
same-entity counterpart in any held roster:
`ARCTICGAS`, `BSC`, `EOA`, `GAPFAC`, `MMA`, `NCRIRS`, `OIRA`, `PCSCOTUS`,
`PRES`, and `USC`. No genuine collision remains. The final split is
`331 = 321 + 10`. The artifact layers every decision over the unchanged census
and gives the adjudication its own digest.

**Identity claims live in the asserted entity graph; the Parquet table adds
nothing.** The mapping release
`regulations-gov-agency-identity-2026-08-16` contains 321 one-way
`atlas:sameEntityAs` assertions from regulations.gov resources to the true
Federal Register, eCFR, or Federal Hierarchy counterpart. It emits no inverse.
Each assertion has two E4 `humanReview` evidence records, for 642 records total.
Release metadata accounts for all 331 candidate decisions and carries the ten
abstentions. The entity ring admits no mapping predicate other than
`atlas:sameEntityAs`. A broader regulations.gov publisher record does not
justify identity with its subunits: those candidates remain recorded
non-emissions, and this release emits no subunit relation.

`build_agency_projection()` is a pure function of that mapping release and the
five roster releases. It joins asserted subjects and objects to publisher names,
labels, and parent relations; it projects abstentions only from release
metadata. It performs no matching and invents no claim. The builder emits 321
rows, including 159 with a target-roster parent, and ten unresolved rows. Its
parity test proves that projection rows equal graph assertions, unresolved rows
equal metadata abstentions, and `331 = 321 + 10`.

Each projection mapping row keeps the source value, selected organization,
labels, parent, relation, E4 warrant and basis, and a projection evidence record
that identifies both publisher records, both verbatim names, and the reasoning.
Each unresolved row keeps the abstention reason, reasoning, and closest rejected
candidate where one exists. The tables contain no scalar confidence. Tests fail
on an unasserted adoption, incomplete E4 evidence, an entity-ring predicate
violation, forbidden identifier emission, inverse minting, input reordering,
publisher-name drift, or any assertion/metadata/projection parity loss. Producer
and Parquet integration must preserve these assertions, rows, evidence records,
coverage counts, and digests exactly.

**Completion note, 2026-08-16.** The producer now loads the regulations.gov
roster through the entity-roster group and loads
`regulations-gov-agency-identity-2026-08-16` through the mapping-release path.
The mapping release pins the five roster input sets and the owner-adjudication
artifact. Independent fidelity readers reparse both the 331-resource roster and
the 321 asserted mappings with their 642 E4 evidence records. The portfolio
catalog has 115 resources and the planning index has 111 rows; the added
`regulations-gov-agency-identity` source is `mappingAssertionsOnly`. The binding
serializes entity-ring `atlas:sameEntityAs`, rejects a separately asserted
inverse, and the sealed Parquet view covers both projection tables in its
manifest digest. A complete load projects 321 resolved rows, ten unresolved
rows, 159 target-parent rows, and 321 projection evidence records.

This integration also strengthened the Atlas 3.1 binding. The new corpus-wide
`dataset.mapping-direction` check refuses a distribution that asserts both
directions of one entity `atlas:sameEntityAs` identity. The producer follows
the direction-of-attestation rule: it emits each mapping exactly as reviewed
and never invents an inverse. The valid producer test and the inverse negative
fixture check both sides of that invariant. Adding the required corpus case
moved `fixtures-receipt.json`'s `fixturesDigest` from
`sha256:6ffa6fc58ba290961b55bcf0428e46482c63ac41d7029f0d011063bcad05a95c`
to `sha256:6043d5867474942264cc235cde63ec30e43572cb38ecbc565c969909e7ab0938`.

### REF-039: Two retained validation structures remain acceptable only at the measured corpus scale

- **Date:** 2026-08-16
- **Status:** Accepted as a measured current-scale limit. The runtime changes
  below are deferred until either trigger fires; the tests and evidence record
  land now.

The streamed constructor bounds each RDF construction graph, but two validation
structures still grow with the complete corpus. First,
`_stream_construct_graphs` copies the source and mapping queues into
`all_source_releases` and `all_mapping_releases`. Those tuples retain every
release object while the queue's `pop`, `del`, and `gc.collect()` calls run, so
the apparent drain frees none of the normalized release data before final
source-accounting validation. Second, `_mapping_accounting_expectations` calls
`_expected_mapping_asserted_graph`, which rebuilds one resident graph over all
mapping assertions, evidence bindings, evidence source records, and policies.
Release data and expected-mapping validation therefore both remain bounded by
corpus size rather than by the construction batch size.

This is an accepted mitigation at the present scale, not a proof of constant
memory. The 2026-08-16 full-build attempt carried 1,344,511 resources and
865,264 mapping assertions. Its measured peak remained below 6 GiB RSS; live
sampling during this review observed 5,773,616 KiB, about 5.51 GiB. Either
more than 5,000,000 mapping assertions or a full-build peak above 24 GiB makes
both follow-ups mandatory before the next production build:

1. Fold each release's source-accounting expectations into a compact
   accumulator while the queue drains. Validate the final ledger against that
   accumulator and remove the two corpus-wide release tuples, so releasing one
   queue item also releases its normalized data.
2. Stream the expected mapping graph by release and construction batch. Spool
   and compare exact assertion, evidence-binding, source-record, and policy
   identities without retaining one graph for all mappings. Keep the copied
   whole-graph implementation as the test-only oracle, and require verdict
   agreement over real data plus the mutation battery before removing the
   production path it replaces.

**Real-data replacement evidence, 2026-08-16.** The env-gated
`test_bounded_real_releases_match_streamed_and_legacy_bytes` ran the same
closed subset through the legacy and streamed paths. The subset includes the
large `fast-topical-current` release, the evidence-backed Unified Agenda/GAO
value mapping, all five agency rosters, and the regulations.gov entity-identity
mapping. The paths produced byte-identical source accounting, compiled
validation, 33 distribution files including all receipts, and ten Parquet
files.

That run also exposed a separate frozen binding limit. The selected mappings
legitimately carry more than one E4 evidence binding per assertion: the entity
mapping has 642 bindings for 321 assertions, and the value mapping has 15 for
five. The construction summary therefore totals 277,511 evidence bindings for
277,180 relation assertions. The binding's
`_check_construction_summary_identity` still equates those counts, so both
unmodified writers produce the same bytes and then refuse with
`construction.counts: construction aggregate evidenceBindings count differs`.
This is verdict agreement over real data, but it is not yet a positive
real-data acceptance seal.

The binding-runtime follow-up is mandatory before claiming that seal. Add an
independent `evidenceBindings` count to the manifest and producer-validation
receipts and their schemas, compute it from the asserted RDF, and compare the
construction-summary aggregate with that count instead of
`relationAssertions`. Add multiple-evidence positive and count-mutation
negative fixtures. Then change the env-gated oracle to require both writers to
return `status: passed` while retaining the exact distribution, receipt, and
Parquet byte comparisons. The current review records the test and blocker but
does not edit the frozen binding runtime.

The conformance-fixture runtime also has an environment drift that this review
does not resolve by rewriting evidence. `fixtures-receipt.json` records
`rdflib` 7.6.0, and `bindings/atlas/3.1/requirements.txt` requires exactly
7.6.0; the workspace `uv.lock` and `.venv` currently provide 7.5.0. Running
`build_fixtures.py --check` directly in that workspace environment would
rewrite the receipt's runtime row, so this review did not run it. Resolve the
drift by upgrading the workspace lock and environment to 7.6.0, or by using the
Makefile's isolated binding-requirements environment. Then run the fixture
check under 7.6.0 and review the receipt and fixture digest before accepting any
regeneration.

### REF-040: One consolidated LCSH release replaces three; the held-to-held mappings connect at full scope

- **Date:** 2026-08-17
- **Status:** Accepted and executed. Numbered REF-040, not REF-039: that
  number was already taken by the unrelated validation-scale entry above,
  landed on this branch before this work started.

**The decision.** RefSpec held LCSH four times over: three separate,
bespoke endpoint captures (`lcsh-eurovoc-alignment-endpoints-2026-08-06`,
`lcsh-external-links-endpoints-2026-08-15`, and
`lcsh-mesh-mapping-endpoints-2026-08-15`), each scanning the same pinned
140,187,915-byte bulk file with its own narrower selection rule, plus the
shared `refspec.registry.lcsh_topical` reader that could not parse a
deprecated authority at all. One release now replaces the three:
`lcsh-subjects-consolidated-2026-08-06`
(`src/refspec/atlas/v3_registry_alignments_lcsh.py`). It mints every current
LCSH heading of every authority class the bulk file carries — Topic,
Geographic, ComplexSubject, CorporateName, and the rest, not only topical
headings — plus only the deprecated headings a held FAST, LC external-links,
MeSH-LCSH, or EuroVoc-LCSH mapping candidate actually names as an LCSH-side
IRI. A deprecated heading nothing points at is never emitted. Every retained
deprecated member keeps LC's own `madsrdf:DeprecatedAuthority` status,
`madsrdf:useInstead` successor IRIs, and `madsrdf:deletionNote` verbatim in
its native payload; RefSpec infers no successor and hides nothing at the
corpus layer. The minted `id.loc.gov` IRIs are byte-identical to what the
three retired releases emitted, so every existing mapping assertion that
named one still resolves — only the owning release changed.

`refspec.registry.lcsh_topical` gained the capability the consolidated
release needed rather than a parallel reader: `admit_deprecated`,
`permit_blank_broader`, and `tolerate_repeated_variant_labels` widen the
existing MADS/SKOS parser (each defaults to today's strict behavior, so
every prior caller is unchanged), and a new
`capture_lcsh_current_and_referenced_deprecated` streams the whole file
once. The full scan — 521,055 lines, 513,210 current authorities, 7,845
deprecated — completes in about 15 seconds; it is not the mapping-only
1,000-record ceiling this module has always enforced for the unrelated
search-expansion snapshot path, which is untouched. The consolidated
release retains 1,627 of those 7,845 deprecated headings (6,218 excluded as
unreferenced) for 514,837 total resources and 301,442 `skos:broader`
relations.

**What connected.** Three held-to-held mappings depended on LCSH endpoint
subsets narrower than what RefSpec actually held. All three now resolve
against the consolidated release; predicate policy is unchanged in every
case.

1. **FAST-to-LCSH** (`fast-lcsh-adopted-2026-08-15`,
   `v3_registry_alignments.py`). The target filter widens from the
   1,966-concept EuroVoc-alignment subset to every held LCSH concept. The
   release's own candidate count moves from 64,464 (1,683 `skos:exactMatch` +
   62,781 `skos:relatedMatch`) to 602,459 (252,527 exact + 349,932 related)
   — schema:sameAs still adopts to exactMatch under `operatorAdoption`, and
   relatedMatch is still carried verbatim under `publisherAssertion`, never
   promoted. Only 8 of 252,535 candidate exact links and 0 of 349,932
   candidate related links stay unemitted, both because the named LCSH
   subject is absent from the pinned bulk file entirely — not deprecated,
   not held under any status. REF-035 predicted the next failure mode
   exactly: widening reopened subject overlap between the exact and related
   FAST subject sets (12 subjects now carry both, where the narrow filter
   had zero). `_fast_lcsh_s46_conflicts` unions this release's own
   exactMatch edges and tests every relatedMatch pair for same-component
   membership; the measured conflict count is zero, over the full 349,932
   candidate related pairs. That is a release-scoped self-check, not a
   replacement for the corpus-wide SKOS S46 preflight, which still runs at
   build time over every release's exactMatch edges together.

   602,459 is this loader's own candidate count, not what ships. Widening the
   target scope also widens what the separate, cross-release SKOS S27
   reconciliation (`_reconcile_fast_lcsh_s27_mapping_conflicts`,
   `tools/generate_atlas_v3_full.py`) has to refuse: every OCLC
   `skos:relatedMatch` pair whose subject and object LC's independent
   hierarchy claims also connect. Under the narrow filter that reconciliation
   refused 24,190 of the 62,781 candidate related claims; every newly
   reachable LCSH target reopens the check against LC's hierarchy, and at the
   widened scope it refuses 174,766 of 349,932 — roughly seven times as many,
   because most of the newly admitted FAST-LCSH pairs land inside an LC
   `broadMatch`/`narrowMatch` path. The frozen pin
   (`FAST_LCSH_S27_REFUSAL_COUNT`, `FAST_LCSH_S27_REFUSAL_DIGEST` in
   `v3_registry_alignments.py`) moves from
   `(24_190, sha256:fc9afdc9c1da43839d133ff0efe409dd0c6c0624152bacdfb65e9bd9320653bd)`
   to
   `(174_766, sha256:2113d4079b4677c0fea40c8c11583f265b5f3cd95d2988bcb941ab5c8897c6ce)`;
   a mismatched count or digest still fails producer loading. The release's
   true emitted total after S27 reconciliation is **427,693 mappings: 252,527
   exact and 175,166 related** — not the 602,459 candidate figure above.

   **This pin moved twice.** A first measurement (174,755; digest
   `...ce7782`) reconciled `skos:relatedMatch` pairs only against
   `lcsh-external-links-mappings-2026-08-15`'s own `broadMatch`/`narrowMatch`
   hierarchy claims. That is narrower than what the binding's corpus-wide
   SKOS S27 check (`refspec_atlas_v3_validate._check_skos_integrity`) actually
   evaluates: the check runs over every hierarchy statement the whole
   distribution carries, including the 301,442 native `skos:broader`
   statements the consolidated LCSH release contributes. A full build reached
   that check 13 minutes in and failed on
   `(sh2008003833, fast/1910413)` — a pair hierarchy-connected only through a
   five-hop chain of intra-LCSH `skos:broader` edges (`sh2008003833` →
   `sh85109172` → `sh85017454` → `sh85112599` → `sh85026423`) that only then
   reaches LC's own external-links `broadMatch` from `sh85026423` to
   `fast/1910413` — a path the narrower reconciliation never saw because
   every one of those `skos:broader` edges lives in the consolidated LCSH
   release, not in `lcsh-external-links-mappings-2026-08-15`.
   `_reconcile_fast_lcsh_s27_mapping_conflicts` now takes the
   loaded source releases as a required argument and builds its hierarchy the
   same way `_check_skos_integrity` does: every `skos:broader`/`skos:narrower`
   relation from every loaded source release, plus every loaded mapping
   release's `broadMatch`/`narrowMatch` — not just the LC release's. It
   refuses to run unless the consolidated LCSH release
   (`lcsh-subjects-consolidated-2026-08-06`) is among those source releases,
   for the same reason it already refused to run with only one of
   `fast-lcsh-adopted-2026-08-15`/`lcsh-external-links-mappings-2026-08-15`
   loaded: reconciling against a hierarchy narrower than the one that will
   ship is worse than refusing outright. Widened to corpus scope, 11 more
   `relatedMatch` pairs move from admitted to refused (174,755 → 174,766);
   FAST's own internal `skos:broader`/`skos:narrower` hierarchy
   (`fast-topical-current`) and the MeSH-LCSH mapping's `broadMatch`/
   `narrowMatch` edges were checked directly against the real pinned data and
   contribute zero additional refusals beyond the consolidated release's
   hierarchy, so they do not change this count, but the reconciliation still
   consults them because a future corpus change could make them matter and
   the binding's own check would not distinguish that source from any other.

   `tests/test_producer_prebuild_validation.py`
   (`test_fast_lcsh_s27_pin_matches_the_real_widened_conflict_set`) reproduces
   this derivation against the real pinned sources on every run that has them
   cached, so a drifted pin fails in the time it takes to load three releases,
   not two and a half hours into a full distribution build
   (`test_fast_lcsh_s27_pin_drift_fails_fast_without_a_full_build` proves the
   check actually bites a stale pin, and
   `test_fast_lcsh_s27_pin_would_be_wrong_under_the_old_narrower_hierarchy_scope`
   proves the pre-widening hierarchy scope computes a different, wrong count
   against the same real data — the check that would have caught this
   failure without a build). The reconciliation itself now refuses
   to run with only one of its two required mapping releases in scope
   (`test_fast_lcsh_s27_reconciliation_refuses_one_side_without_the_other`)
   rather than silently no-opping, which is how the earlier drift went
   undetected: every bounded/scoped build that loaded one of the pair without
   the other skipped the check entirely.
2. **LCSH-to-FAST-and-others** (`lcsh-external-links-mappings-2026-08-15`,
   `v3_registry_alignments_lc.py`). This release already bootstrapped its
   own candidate-driven LCSH endpoint capture, and that capture already
   parsed deprecated authorities correctly — REF-037 already landed the
   near-full 801,992-of-802,592-assertion emission. Consolidation is a pure
   rewire here: the module's ~330-line duplicate LCSH scanner is deleted,
   the mapping loader depends on the shared consolidated release instead,
   and the emitted count does not move (801,992 mappings; 600 unemitted for
   469 LCSH subjects absent from the bulk file). LC's four MADS
   external-authority predicates still translate to
   `skos:{exact,close,broad,narrow}Match` under `operatorAdoption`, verbatim
   direction, no inverse.
3. **MeSH-to-LCSH** (`mesh-lcsh-mapping-2021-03-31`,
   `v3_registry_alignments_subject.py`). The target check widens from an
   active-only endpoint capture to consolidated-release membership. Emitted
   mappings move from 13,251 to 13,260 (exactMatch 13,053 to 13,062; broad,
   narrow, and related unchanged); the combined non-admission count (mixing
   "MeSH subject not current" and "LCSH target unavailable," as this
   release has always counted it) drops from 19 to 10. These rows remain
   E3 `operatorAdoption`, opt-in under REF-035: Northwestern owns neither
   endpoint.

**What was deliberately not done.** No new source is downloaded and no
external vocabulary gains admission. This is a connection pass over
publisher bytes RefSpec already holds, not an acquisition. Every REF-036
rejection stands unrevisited. `owl:sameAs` is still refused as an Atlas
mapping substitute; MARC `$w nnd` still cannot be promoted past
`relatedMatch`. The frozen S46 refusal list from REF-037
(`GEMET_EUROVOC_S46_REFUSALS`) is untouched, and this claim is no longer
just narrative: the widened corpus-scope exactMatch component index — GEMET's
and EuroVoc's own candidate claims plus every other mapping release's
`exactMatch` edges that touch either vocabulary (`fast-lcsh-adopted-2026-08-15`'s
252,527, `mesh-lcsh-mapping-2021-03-31`'s 13,062, `eurovoc-lcsh-alignment-20240711`'s
1,904, `gemet-umthes-alignments-4.2.3`'s 3,470) — was computed directly
against the real pinned sources and produces exactly the same 39-claim
conflict set the frozen pin already carries, neither more nor fewer. GEMET
and EuroVoc simply never gained a same-component bridge into the vastly
widened FAST-LCSH or MeSH-LCSH exactMatch edges. The S27
refusal pin (`FAST_LCSH_S27_REFUSAL_DIGEST`) is **not** untouched: widening
the FAST-LCSH target scope reopens the S27 check against far more LC
hierarchy claims, and that pin moves as described above (24,190 to 174,766).
The MeSH-LCSH mapping release's own 29 `relatedMatch` claims were checked the
same way against the corpus-scope S27 hierarchy (LC's `broadMatch`/`narrowMatch`,
the consolidated LCSH release's `skos:broader`, and MeSH-LCSH's own
`broadMatch`/`narrowMatch`) and produce zero conflicts; that release has no
S27 reconciliation step of its own because it has never needed one, not
because it was overlooked.
An earlier draft of this entry claimed both frozen lists were untouched;
that was wrong for S27 and is corrected here, not carried forward. The
`fast-lcsh-adopted-2026-08-15` inferred-pair
metadata (`FAST_LCSH_INFERRED_MAPPING_COUNT`) is recomputed the same way it
was originally measured — the Atlas 3.1 exact-match component index over
`eurovoc-lcsh-alignment-20240711`'s and this release's own exactMatch edges,
not a full-corpus rebuild — moving from 13,001 to 765,537 against an
unchanged 5,939 baseline;
`test_fast_inferred_mapping_delta_is_computed_before_build` proves the
figure directly rather than trusting a hand-computed constant.

**The referenced-IRI union is deliberately the wider, simpler one.**
`gather_referenced_lcsh_iris` takes every LCSH-side IRI any of the four held
source captures names — the EuroVoc-LCSH alignment's objects, every
candidate subject in LC's external-links archive, every LCSH target of an
active FAST record's link, and every object in the Northwestern MeSH-LCSH
mapping — not only the rows that survive their own *other*-endpoint
availability check. A deprecated heading that only such a row names costs
nothing to admit and keeps the selection auditable as one union over four
pinned artifacts; whether a given row is ultimately emitted remains each
mapping loader's own decision, unaffected by this union's slight breadth.

**The explorer's default hiding of deprecated members is a display choice,
not a corpus fact.** The consolidated release carries every deprecated
member's status, useInstead, and deletion note exactly as LC states them;
nothing at the registry or Atlas layer suppresses or resolves them. Any
default-collapsed presentation belongs to `explorer_frontend.py` and the
explorer CLI, owned separately from this change.

**The running proof.** `tests/test_lcsh_topical.py` carries mutation-battery
coverage for the three new parser flags (deprecated admission, blank-node
broader tolerance, repeated-variant tolerance) against both a synthetic
fixture and pinned real bytes. `tests/test_atlas_v3_registry_alignments*.py`
prove the consolidated release's resource, relation, and label counts and
the three mapping releases' widened counts against the live pinned sources.
`tools/verify_atlas_source_fidelity.py` carries an independent re-parse of
the consolidated release (`_read_lcsh_consolidated`,
`_lcsh_referenced_iris_independent`) that never imports
`refspec.registry.lcsh_topical` or
`refspec.atlas.v3_registry_alignments_lcsh`, plus updated independent
re-parses for the FAST-to-LCSH and MeSH-to-LCSH mapping specs; the
LCSH-to-FAST mapping spec needed no change; both readers agree with the
production loaders over the exact pinned bytes. The source-link manifest is
unchanged: this decision pins no new source file.

**The S27 reconciliation's scope gaps were build-time-only; all three are now
suite-time checks.** Three separate gaps let a stale or too-narrow refusal
list ship undetected, and each is now refused loudly instead of silently
mis-reconciling:

1. Neither of `fast-lcsh-adopted-2026-08-15` and
   `lcsh-external-links-mappings-2026-08-15` loaded without the other — a
   bounded/scoped build that loaded one without the other used to skip the
   reconciliation entirely rather than refuse.
   `test_fast_lcsh_s27_reconciliation_refuses_one_side_without_the_other`
   proves this refusal with a cheap synthetic fixture.
2. The consolidated LCSH source release (`lcsh-subjects-consolidated-2026-08-06`)
   not loaded alongside those two mapping releases — this is the gap that
   actually shipped the build failure described above, since only the
   unbounded full build ever happened to load the hierarchy-relevant source
   releases at all, and the reconciliation never asked for them.
3. The frozen pin itself drifting from what a fresh derivation computes —
   `_reconcile_fast_lcsh_s27_mapping_conflicts` derives the refused-pair list
   fresh from the loaded releases every time, so a stale pin fails loudly the
   moment both gaps above are closed.

`tests/test_producer_prebuild_validation.py` proves all three without a full
build: `test_fast_lcsh_s27_pin_matches_the_real_widened_conflict_set`
reproduces the corpus-scope derivation over the real pinned sources
(`fast-lcsh-adopted-2026-08-15`, `lcsh-external-links-mappings-2026-08-15`,
and the consolidated LCSH release) and checks it against the live pin;
`test_fast_lcsh_s27_pin_drift_fails_fast_without_a_full_build` proves the
exact pre-REF-040 pin is refused against that same real data (the
proven-biting negative for gap 3);
`test_fast_lcsh_s27_pin_would_be_wrong_under_the_old_narrower_hierarchy_scope`
proves the pre-widening *hierarchy scope* — the LC release's
`broadMatch`/`narrowMatch` alone, without the consolidated release's
`skos:broader` — computes a different, wrong count (174,755, not 174,766)
against that same real data (the proven-biting negative for gap 2, and the
check that would have caught the actual build failure without a build); and
`test_fast_lcsh_s27_reconciliation_refuses_one_side_without_the_other` proves
the gap-1 and gap-2 refusals with a cheap synthetic fixture.

### REF-041: GCMD column nesting is publisher hierarchy, but it can only ever be a derived edge; the 3.1 derived graph admits no second rule yet

- **Date:** 2026-08-18
- **Status:** Accepted. The judgment, the derivation, and its frozen pins
  land; nothing enters the asserted graph, and nothing enters the shipped
  derived graph — the binding changes that would require are recorded here,
  not made.

**The question.** `gcmd-science-keywords-24-4` holds 3,774 keywords with
zero broader/narrower. The prior author's reader
(`refspec.registry.gcmd_science_keywords`) states the CSV export "carries
no SKOS broader/narrower" and deliberately does not assert them, packaging
the hierarchy columns as descriptive context only. The question put to this
entry: does the CSV's column position constitute a publisher assertion of
hierarchy, or is turning it into SKOS relations an inference?

**The evidence, from the pinned 24.4 bytes**
(`sha256:f31d8137e860e4231ff312c89e4ffe59d12f636786a47dd2c41e28273a3f02e2`,
504,190 bytes):

1. Every row is a path (Category > Topic > Term > Variable_Level_1..3 >
   Detailed_Variable), and every strict prefix of every row exists as its
   own row carrying its own publisher UUID — zero missing ancestors across
   all 3,774 rows. Parent concepts are first-class keyword records in the
   export, not repeated cell values.
2. The columns form a strict forest: two roots, one parent per node by
   construction (the depth-1 prefix), prefix-contiguous throughout (the
   reader refuses a populated level after a blank ancestor), no repeated
   full path, no UUID collision, and no two siblings under one parent share
   a label. Nesting implies exactly 3,772 immediate-parent edges.
3. Keyword identity is path-scoped, not label-scoped: 512 (level, label)
   pairs appear under more than one parent (e.g. the Topic PRECIPITATION
   under more than one Term). Any label-keyed derivation would silently
   merge distinct publisher concepts; only the UUID-per-path structure is
   sound.
4. NASA's own machine serialization agrees. The live KMS RDF export of the
   same scheme (keywordVersion 24.5, observed 2026-08-18, **not pinned** —
   the pinned artifact is the 24.4 CSV) asserts `skos:broader` between
   exactly the UUID pairs the column nesting implies: all 3,772 edges whose
   endpoints exist in 24.4 agree with the nesting, zero mismatch, with two
   UUIDs new in 24.5 and absent from 24.4.

**The judgment.** Column position is the publisher's hierarchy — the prior
author's abstention is overruled on the facts. But it is overruled only
down to the derived-graph line, not past it: the pinned CSV carries no
relation field, the relation assertions live in the separate RDF export
RefSpec does not hold, and choosing `skos:broader` as the predicate for a
positional fact is RefSpec's act, not NASA's. Under REF-035 this is tier
E5: an inferred edge is never an assertion, belongs only in the derived
graph, and stays opt-in. The prior author's refusal stands in full for the
asserted graph; `hierarchyIsDescriptiveNotInferred` in the asserted
native payload is unchanged and remains true.

**What landed.** `refspec.registry.gcmd_science_keywords_hierarchy`
derives the edge set from the pinned parse with fail-closed premises:

- one `skos:broader` edge per row of depth ≥ 2, parent = the row keyed by
  the depth-1 prefix; rule IRI
  `urn:ref:rule:gcmd-science-keywords-csv-column-nesting`;
- every edge cites the exact CSV rows it came from (child and parent
  `csv:row[n]` source paths plus UUIDs) and carries a content-derived
  edge IRI over that citation and the source digest;
- reproducible: re-derivation over the same pinned bytes yields the
  identical edge list and set digest, and the real-data test regenerates
  the frozen pins — roots 2, edges 3,772, homonym labels 512, edge-set
  digest `sha256:9685d20fd9e10d2e12d916b4e5f543ae17b332b6d13a3a311e14db9f79fcc964`;
- refuses, never silently drops: a missing ancestor-prefix row, a repeated
  path (even with a fresh UUID), a self-edge, or a derived edge that
  duplicates an asserted relation — including its `skos:narrower`
  inverse — raises rather than emits.

`tests/test_gcmd_science_keywords_hierarchy.py` proves the happy path over
a byte-faithful complete-branch excerpt (126 rows, 125 edges,
`gcmd-science-keywords-24.4-agriculture-branch.csv`), the proven-biting
negatives (the existing mini excerpt is not prefix-closed and is refused;
a deleted parent row is refused; a duplicated path is refused; asserted
collisions in both directions are refused while an unrelated asserted
relation is not), regeneration equality, and the frozen real-data pins.
It also asserts the rule IRI differs from the shipped binding's single
allowlisted rule, so an accidental early wiring fails a test, not a build.

**Why nothing ships in the derived graph.** Adding a second derivation
rule is a binding revision, not a producer toggle. The 3.1 machinery is
strict on purpose, and a GCMD-shaped derived row fails it five ways:

1. `dataset.derived-rule` (validate.py `_check_derived`) allowlists
   exactly one (rule, engine, engineVersion) tuple —
   `urn:ref:rule:skos-exact-match-closure-path` under owlrl 7.1.4 — and
   then requires the subject ring, `skos:exactMatch`, ≥2 inputs, one
   simple path between endpoints, and canonical IRI order. A column-nesting
   row fails the allowlist outright and the shape after it.
2. The evidence model: `atlas:derivedFromAssertion` must cite active
   asserted *assertion* nodes, digested by `derived_input_digest`. GCMD's
   asserted graph carries 3,774 resources and zero assertions; the
   evidence for a nesting edge is two pinned CSV rows. The binding needs a
   derived-from-source-row (or source-payload) citation path before this
   rule can express its warrant.
3. The engine: the replay under `_check_reasoning_isolation` is OWL-RL
   closure over the cited inputs. A structural projection from CSV
   columns needs its own declared engine identity and its own replay
   semantics — regeneration from the pinned source digest, which this
   module already provides.
4. Direction: `skos:broader` is asymmetric, so the exactMatch canonical
   IRI-order convention does not transfer; an asymmetric derived predicate
   needs an explicit direction rule (child → parent, never the inverse).
5. The producer refuses nonzero derived relations
   (`generate_atlas_v3_full.py`), and per REF-035 every new rule lands with
   a rejecting conformance case: the fixtures corpus, manifest pins, and
   acceptance records must be reissued by the orchestrator's chain.

**Deliberately not done.** The reader is untouched — its gap text
("this module does not fetch or model them") remains true of the reader,
and the asserted release still emits zero relations. No binding file, no
producer path, and no fixtures were modified for this entry; the MeSH
tree-number work owns the produce-side plumbing this would eventually
consume. When the binding gains its second rule, the frozen pins above
are the acceptance bar: the shipped edge set must regenerate them exactly
or the rule is not the rule recorded here.

### REF-045: EuroVoc does not assert microthesaurus-to-domain; the link exists only as a notation prefix

- **Date:** 2026-08-19
- **Status:** Finding recorded. No release, no rule, no emission -- this
  entry exists so nobody re-litigates the question from scratch.

**The question.** The Atlas holds EuroVoc flat: `eurovoc-4.24` (7,515
concepts) and `eurovoc-domains-4.24` (21 domains), with nothing connecting
them. A months-old sidecar at `output/eurovoc-organization-experiment-4.24/`
holds the missing organization -- 148 objects (21 domains + 127
microthesauri), 7,902 publisher-asserted `concept -> microthesaurus`
memberships, and 127 operator-derived `microthesaurus -> domain`
candidates. Before promoting the derived half, the obvious question: does
the Publications Office assert that link itself? It demonstrably asserts
the level below (the 7,902 memberships are real `skos:inScheme`
statements), and a publisher that states one level of its own hierarchy
usually states the other.

**It does not, and the check was exhaustive.** Against the pinned
`eurovoc-4.24-skos-core.zip` (sha256 `91bdb24e...f1a0ca2f`, verified before
parsing), member `eurovoc_in_skos_core_concepts.rdf`, 60,691,531 bytes,
524,093 triples -- the same artifact `eurovoc-4.24` and
`eurovoc-domains-4.24` are built from:

- The complete predicate inventory on the 127 microthesauri is `rdf:type`
  (127), `skos:notation` (127), `skos:prefLabel` (3,429), `skos:altLabel`
  (1). No predicate whose object is anything but a literal.
- Zero microthesaurus-to-domain triples under any predicate; zero in the
  reverse direction; zero microthesaurus-to-microthesaurus.
- `euvoc:domain` -- the predicate the sidecar's candidates use -- appears
  nowhere in the graph at all.
- Nothing anywhere points at any of the 21 domain concept IRIs; the domains
  are only ever subjects.
- The pinned metadata TTL names none of the 148 organization IRIs.
- The only linkage that exists is notational: all 127 microthesaurus
  4-digit notations carry a 2-digit prefix naming exactly one of the 21
  domain codes.

**And the prefix rule is only valid one level up.** Measured against the
sealed corpus: EuroVoc *concept* notations are opaque sequential ids, not
hierarchical codes -- `1` is "Arhus (county)", `10` is "domestic trade",
`100` is "racial conflict". Applying a two-digit prefix rule at the concept
level produces 1,730 confident nonsense claims out of 7,506, including
"business tax" under EMPLOYMENT AND WORKING CONDITIONS and "contemporary
history" under AGRICULTURE, FORESTRY AND FISHERIES. The relationship is
real at the microthesaurus level and meaningless below it.

**What follows.** The 7,902 memberships are publisher assertions and belong
in the asserted graph whenever the organization layer is promoted. The 127
domain links are a derivation, MeSH-shaped -- structure encoded in a
notation -- and belong in the derived graph under their own registered
rule, scheme-scoped, never as publisher assertions. Neither is emitted
today; the sidecar remains non-authoritative and
`eurovoc_organization_experiment.py` remains the one entry in
`SOURCE_BLOCKERS`, which is why the real-data gate still reports a declared
gap.

### REF-042: The derived graph gets a rule registry; MeSH tree-number broader is the second entry

- **Date:** 2026-08-18
- **Status:** Accepted and executed. Numbered REF-042, not REF-041: that
  number was taken the same day by the GCMD entry above, landed on this
  branch before this work started (REF-040's own numbering note records
  the same kind of collision).

**The decision.** `bindings/atlas/3.1/tools/validate.py`'s derived-graph
gate used to allowlist exactly one `(rule, engine, engineVersion)` tuple by
direct equality, then run one undifferentiated body of exactMatch-only
checks against every derived row it saw. `_check_derived` now looks the
tuple up in `_DERIVED_RULE_ADMISSIONS`, a dict of `_DerivedRuleAdmission`
records, each naming its own admitted semantic ring(s) and predicate(s),
its evidence kind (an active `RelationAssertion`, or — new — an active
`SourceRecord`), a row-shape validator, and a replay/regeneration check
`_check_reasoning_isolation` dispatches to per rule. A second rule is a
second entry in that dict, not a second `if` branch woven through the
first rule's body. The registry, not a rewritten single rule, is what
REF-041 said this would require.

**Why a registry rather than a second hardcoded branch.** The prior shape
made "is this rule admitted" and "does this row satisfy exactMatch
transitivity" one inseparable check. Threading a second rule's shape
through that check by adding more `or` clauses would have made both rules
harder to prove correct together than apart, and would have left the
allowlist itself — the actual security-relevant boundary, "which rule/
engine/version tuples exist" — implicit in a chain of tuple comparisons
instead of enumerable. A registry makes the admitted set inspectable
(`_DERIVED_RULE_ADMISSIONS` is a literal dict a reader can enumerate) and
makes each rule's contract — ring, predicate, evidence kind, row shape,
replay — a value instead of control flow.

**The exactMatch-transitivity rule did not change behavior.** Its row-shape
body (canonical IRI ordering, the one-exact-simple-path proof over cited
`skos:exactMatch` edges, the reflexive/duplicate-edge refusals) was moved
verbatim into `_validate_exact_match_transitivity_row`; its OWL-RL replay
body was moved verbatim into `_replay_exact_match_transitivity`. Neither
function's internal logic differs from the code it replaced by one token —
only its indentation and the names of the two functions it now lives in.
The proof that this held is direct, not asserted: the full existing
conformance corpus (136 cases, committed before this work) was rerun
against the refactored validator unchanged and passed every case with the
same accept/reject verdict and the same `firstIssue` failure code, and
`tests/test_atlas_v3_binding.py` and `tests/test_atlas_v3_validator_regressions.py`
passed unchanged (184 tests, 0 failures — one fixture needed a
`derivationRule`/`engine`/`engineVersion` triple it had never needed
before, because `_check_reasoning_isolation` now has to know which rule a
node uses before it can decide how to replay it; that is new information
the dispatch itself requires, not new behavior of the exactMatch rule).
`firstIssue` pins a failure *code*, never message text, which is what let
several checks move to a different point in the function without changing
what any existing fixture proves.

**What the contract now admits.** A derived row whose rule is
`urn:ref:rule:mesh-tree-number-broader`, engine
`https://refspec.org/code/atlas-v3-derived-mesh-tree-numbers`, engine
version `"1"`; ring `atlas:subject`; predicate `skos:broader`; exactly two
cited `atlas:SourceRecord` inputs whose `atlas:representsResource` targets
are exactly the row's own subject and object; and whose subject and object
each carry an `atlas:notation` such that one of the subject's notations,
with its final dot-segment removed, equals one of the object's notations.
Evidence citation widened from "an active `RelationAssertion`" to "an
active `RelationAssertion` *or* an active `SourceRecord`, per the citing
rule's own declared evidence kind" — `atlas:derivedFromAssertion` never had
an `rdfs:range` (its comment already says the target type "is checked by
the dataset validator rather than inferred into the derived graph"), so
this widening is a validator change, not an ontology change.
`ontology/atlas.ttl`, `shapes/atlas.shacl.ttl`, and
`registry-resource-profiles.json` are byte-identical to what they were
before this work: `skos:broader` was already an admitted
`NativeRelationAssertion` predicate for the subject ring (LCSH's 301,442
native `skos:broader` statements from REF-040 already needed it), and
`atlas:generatedAt`/`atlas:derivedFromAssertion`/the rest of
`DerivedRelationShape` already had the shape a second rule needed.
**What it still refuses.** Every other rule/engine/version tuple; a
MeSH-shaped row for any ring or predicate other than
`atlas:subject`/`skos:broader`; a row citing anything other than exactly
two `SourceRecord`s representing its own endpoints; a row whose notations
do not actually resolve the claimed parent; and — generalized, not
special-cased — a row duplicating an asserted relation *or its predicate's
mirror*, where the exactMatch rule's mirror is itself (symmetric) and the
new rule's mirror is `skos:narrower` (`skos:broader`'s SKOS-defined
inverse). The duplicate-of-asserted check that used to read
`predicate == SKOS.exactMatch` now reads
`admission.mirror_predicate`, which is `SKOS.exactMatch` for the first
rule and `SKOS.narrower` for the second — the same check, parameterized,
not two checks.

**The replay asymmetry is real and intentional.** `_check_reasoning_isolation`
dispatches per rule too, but the two rules' replays are not shaped the
same way. exactMatch transitivity replays *locally*, per row, over only
that row's own cited inputs, under a pinned OWL-RL reasoner — because
REF-035 already ruled that RefSpec never asserts the full transitive
closure over an open-ended mapping graph; only specific requested rows are
ever materialized, so there is no fixed "whole closure" to regenerate and
diff against. MeSH tree-number broader is the opposite shape: it is a
closed, one-release projection with a definite total edge count, so
`_replay_mesh_tree_number_broader` recomputes the *complete* expected
`(child, parent)` pair set from the asserted graph's own `atlas:notation`
facts once, and requires the shipped MeSH-rule row set to equal it exactly
— not "each row replays," but "the set is the set." A row naming an
ambiguous or missing parent can never appear in the expected set, so it
cannot survive this check by accident; the row-level check
(`_validate_mesh_tree_number_broader_row`) proves each row locally from
only its own two cited source records, matching the exactMatch rule's "prove
it from what this row cites" discipline, and the whole-of-rule replay
proves the set has no gaps and no guesses. Both are "regenerate from the
asserted graph and require the identical result"; they differ only in
whether "the asserted graph" for that proof is the row's own cited slice or
the whole release, because one rule's admitted output is unbounded and the
other's is not.

**MeSH counts and anomalies.** Verified against the same pinned 2026
release `mesh_tree_numbers.py` already carried the frozen pins for
(`sha256:9b034cad8bbd4d8d1ef43816d6fd78d33fada52eddff2a0b4455b1fca35cc5ba`,
31,110 descriptors, 65,360 tree numbers): 115 root tree numbers (no dot,
no parent by construction); 42,519 derived `skos:broader` edges (fewer
than 65,245 non-root tree numbers because a descriptor with several tree
numbers under one parent yields one edge to it, and 9,349 descriptors are
true MeSH polyhierarchy — multiple tree numbers under distinct parents,
yielding multiple edges); zero missing-parent anomalies and zero
ambiguous-parent anomalies in this release (both counted, never guessed,
so a future annual release that is not this clean fails loudly rather than
silently mis-deriving); three tree numbers each carried by two descriptors
at once (a bacterial reclassification artifact), counted as
`duplicateTreeNumbers` and confirmed to never actually gate an edge in
this release. These are the same figures REF-041's GCMD-precedent
commentary already recorded for this module; nothing here changed them —
this entry is what let the binding admit them.

**Corpus cases.** Five new entries in `REQUIRED_CORPUS_CASES` (136 → 141;
122 → 126 invalid), each proving the registry bites where the mission asked:

1. `mesh-tree-number-broader` — the positive case. A real MeSH-shaped
   derived row (two ordinary `SubjectConcept`s, tree numbers `C14.280` and
   `C14.280.647`, no asserted relation between them) validates end to end.
2. `mesh-tree-number-unallowlisted-rule` — the exactMatch row's own
   `derivationRule` rewritten to an unregistered IRI; `dataset.derived-rule`.
3. `mesh-tree-number-wrong-predicate` — the MeSH rule, `skos:related`
   instead of `skos:broader`. `skos:related` is itself an admitted native
   relation predicate for the subject ring (other rows use it), so this
   only bites if the per-rule admitted-predicate check runs, not the
   ring-level one; `dataset.derived-rule`.
4. `mesh-tree-number-malformed-inputs` — one cited `SourceRecord` instead
   of two. Passes the common active-input-superset check (it is a real,
   active source record) and is caught only by the rule's own row-shape
   check; `dataset.derived-rule`.
5. `mesh-tree-number-duplicates-asserted` — an asserted
   `(parent, skos:narrower, child)` `NativeRelationAssertion` alongside a
   derived `(child, skos:broader, parent)` row: the mirror-predicate
   generalization, not the direct-duplicate path the exactMatch rule
   already exercised. `dataset.derived-authority`.

`_base_fixture()` gained one inert MeSH-shaped resource pair (raw
material: tree numbers, no relation, no derived row) that the 136
pre-existing cases never cite, so their own single derived node
(exactMatch) and every count a mutation depends on stayed put; only the
five new mutations add a MeSH-rule row over that pair. `all-resource-profiles`'
own counts moved as a direct consequence (`resources` 12 → 14, `labels` 12
→ 14, `sourceRecords` 12 → 14, `releases` 10 → 11, `quadCount` 1020 → 1088)
— `derivedRelations` stayed at 1, because the baseline valid case still
carries only the original exactMatch row.

**Producer.** `tools/generate_atlas_v3_full.py` stops declaring
`"derivedRelations": 0` unconditionally in two places: the prebuild
row-count receipt (`_validate_compiled_producer_rows`) and the streamed
build's aggregate-count refusal
(`_reconcile_prebuild_construction_counts`, which used to refuse outright
if either projection or derived counts were nonzero — it now refuses only
on projection, still out of scope). `_expected_derived_relation_count`
computes the real expected count straight from the loaded, in-memory
`LoadedRelease` resources — no spool exists yet at that point in the
build — by calling `resolve_tree_number_edges_from_notations`, the pure
function `src/refspec/atlas/derived_graph/mesh_tree_numbers.py` now
exposes so the prebuild receipt and the post-streaming derivation share
one algorithm instead of two that could drift apart. After all source and
mapping releases are streamed and spooled, `_derive_registered_relations`
reads `mesh-descriptors-2026`'s own already-spooled canonical N-Quads
lines back off disk — the same bytes the shipped RDF pack will be sorted
and compressed from — through the shared, package-level
`refspec.atlas.derived_graph` machinery
(`collect_asserted_fact_view`/`collect_node_digests`/
`derive_mesh_tree_number_broader_rows`), and threads the release's own
(empty, today) asserted-relations set through as the module's docstring
said real wiring would have to. The resulting rows are rendered into one
small in-memory graph and written as a standalone RDF "view" pack via
`_write_view_pack` — the same function the non-streamed `BuildGraphs` path
already used for projection and derived content — because the streaming
spool's compact/Parquet machinery
(`_StreamingGraphSpool.append_graph`, `COMPACT_ROLES`) has no
`DerivedRelation` role and was never meant to: non-authoritative rows are
deliberately absent from the compact/Parquet consumer view, visible only
in the raw RDF "derived" pack. A build that never loads
`mesh-descriptors-2026` — including every bounded `--only-release` build
that omits it — never runs this rule and emits nothing for it, which is
what keeps the derived graph opt-in at exactly the release-selection
granularity a scoped build already has, the same precedent REF-040 used
for the FAST-LCSH S27 reconciliation. `_production_relation_scope_from_counts`
no longer refuses a nonzero `derivedRelations` count: the only code path
that can ever populate one is `_derive_registered_relations`, which only
ever runs a rule the binding's own `_DERIVED_RULE_ADMISSIONS` admits, so a
count reaching that scope function is already rule-admitted by
construction. Verified end to end with a bounded `--only-release
mesh-descriptors-2026` build against the real, pinned 2026 release (74.2s
total against a 56.7s unwired baseline: the derivation pass reading back
the already-spooled ~1.27M-line pack and deriving 42,519 rows takes 8.1s,
the rest is writing the additional pack) rather than the ~3-hour full
build this task was told not to run. The independent standalone validator
then ran against that same real bounded distribution — not a synthetic
fixture — and passed every gate including `check-derived-graph` and
`check-reasoning-isolation`'s whole-set regeneration proof over the real
42,519 rows, confirming `"derivedRelations":42519` in its own count
receipt.

`tests/test_producer_prebuild_validation.py`'s
`test_default_prebuild_refuses_each_mutated_semantic_aggregate` used to
assert that mutating *any* aggregate field, `derivedRelations` included,
made `_reconcile_prebuild_construction_counts` raise. `derivedRelations`
is dropped from that parametrization here, with the reason recorded
in-line: that function's actual job is reconciling the eight logical
construction-record roles, which never included `derivedRelations` (only
its former "must be exactly zero" scope guard touched it, and only
`projectedRelations` keeps that guard now). A wrong `derivedRelations`
expected count is still caught — by `_stream_construct_graphs`'s own
`spool.counts != prebuild.compiled_rows.expected_counts` comparison, which
`test_streamed_whole_graph_refusal_probe[count-mismatch]` already proves
refuses a mismatched aggregate generically, independent of which field
carries the mismatch.

**Digests.** `contractDigest` — the hash of `ontology.ttl`,
`shapes/atlas.shacl.ttl`, `registry-resource-profiles.json`,
`tests/registry-coverage.json`, `tests/registry-descriptors.json`, and
`tests/registry-descriptors.nq` — did **not** move: none of those six
files changed, confirmed by direct byte comparison and by
`ATLAS_VALIDATE._binding_digests()["contractDigest"]` computing the
identical value before and after this work. What moved: the binding-tool
digest (`validate.py` and `build_fixtures.py` changed, so
`_binding_tool_digest()`'s hash of `BINDING_TOOL_PATHS` moved, which is
the cache-invalidation key, not conformance identity — see the commentary
at `validate.py:118-149` and REF-029 for why those are deliberately two
different digests); `corpus_digest()` (`fixtures/corpus.json`'s own hash,
now 141 cases); and `fixtures-receipt.json`'s `fixturesDigest`, rebuilt and
repinned by running `bindings/atlas/3.1/tools/build_fixtures.py` (the
house process for regenerating the gitignored fixture tree), which this
work already required for the five new corpus cases regardless of the
producer or registry changes. One more thing moved that this work did not
cause: `fixtures-receipt.json`'s recorded digests for
`tests/registry-coverage.json` and `tests/registry-descriptors.json` were
already wrong before this work started — REF-040 (`657d1b85`) changed
those two files without a fixture rebuild to match, and the stale receipt
shipped on this branch's starting commit. Rebuilding the fixtures to add
the five new corpus cases incidentally corrected that pre-existing drift;
it is called out here so it is not mistaken for something this entry's
registry or producer work moved.

**Next entries.** FR-compound and GCMD are still not registered rules.
GCMD's judgment, derivation, and frozen pins already shipped in REF-041
and are unchanged by this entry; its acceptance bar (regenerate the frozen
edge set exactly) still applies whenever it becomes the registry's third
entry. The Federal Register compound-heading rule
(`tools/atlas_v3_derived_fr_compound.py`) has WIP scaffolding in-tree but
no decisions-ledger entry of its own yet; registering either as a third
`_DERIVED_RULE_ADMISSIONS` entry is future work this entry does not do.

**Deliberately not done.** No new build mode, CLI flag, or opt-in switch
was added to the producer — the derived graph's opt-in property is
structural (a separate graph role a consumer may ignore) and, now,
release-selection-scoped (a rule only fires when its source release is
loaded), not a flag a caller has to remember to pass. Projection stays
exactly as refused as before; only derived relations were unblocked. No
existing corpus case's fixture bytes were regenerated for reasons other
than the five new cases and the pre-existing registry-coverage/descriptors
drift above — the exactMatch rule's own fixtures are the same bytes they
were, just reissued under a validator whose behavior this entry proves is
identical.

### REF-043: GCMD column nesting becomes the derived graph's third rule; the real-data audit gap it opened closes

- **Date:** 2026-08-19
- **Status:** Accepted and executed. Numbered REF-043: REF-042 is the
  highest prior entry, and its "next entries" paragraph named this exact
  registration as future work.

**The decision.** REF-041 froze the judgment (column nesting is publisher
hierarchy, but only ever a derived edge) and REF-042 built the registry it
needed. This entry registers
`urn:ref:rule:gcmd-science-keywords-csv-column-nesting` — the rule IRI
REF-041 minted, reused, not re-minted — as the third
`_DERIVED_RULE_ADMISSIONS` entry in
`bindings/atlas/3.1/tools/validate.py`, with engine
`https://refspec.org/code/atlas-v3-derived-gcmd-column-nesting`
version `"1"`, ring `atlas:subject`, predicate `skos:broader`, evidence
kind `SourceRecord`, mirror predicate `skos:narrower` (the same
parameterized duplicate-of-asserted check the first two rules run), its
own row-shape validator, and its own whole-of-rule replay. The producer
side is `src/refspec/atlas/derived_graph/gcmd_column_nesting.py`,
registered in the package's built-ins beside the MeSH rule.

**Where the premise lives.** MeSH's premise is an `atlas:notation`
literal on the descriptor. GCMD's premise — the CSV column path — is
carried by the asserted graph exactly once: as the canonical
`atlas:nativePayload` JSON on each keyword's own `SourceRecord`
(`v3_registry_vocabularies._normalize_gcmd` writes the seven path columns
there verbatim from the pinned bytes). The rule reads each keyword's path
out of its record's payload, so producer and validator read the same
asserted bytes the way the shared fact-view machinery already demands:
`AssertedFactView` gained a `payloads` field fed by a new watched
predicate (`atlas:nativePayload`), the extension its own docstring
prescribed. Each edge cites the child's and the parent's `SourceRecord`
as evidence — a source record receipts one exact CSV row (its payload is
that row's columns; its locator digest covers the row path and UUID), so
citing two records is citing the two rows the edge came from, the same
warrant REF-041's CSV-level module expresses with `csv:row[n]` paths.
UUID `atlas:notation`s stay unread: identity is path-scoped, never
label-scoped.

**Scoping, from the first line.** The MeSH rule shipped scheme-blind and
an adversarial battery caught it proving parentage from notation shape
alone. This rule requires the GCMD scheme
(`urn:ref:atlas-resource-scheme:gcmd-science-keywords`) in its producer
fact selection, in its binding row check, and in its replay. A "keyword"
is precisely a resource in that scheme that some `SourceRecord`
represents — the scheme's release node also carries `atlas:inScheme` but
represents nothing, so "in scheme AND represented" (not "in scheme"
alone) is the definition both sides share. Proven three ways: the
producer-side unit test (a foreign-scheme resource with a perfectly
GCMD-shaped payload contributes nothing), a binding-side unit test over
the real `_validate_gcmd_column_nesting_row` and
`_replay_gcmd_column_nesting` (a foreign-scheme row refused on scheme
alone; the replay ignores a foreign column-shaped pair), and the corpus
positive case itself — the base fixture's other source records carry no
GCMD columns, so an unscoped replay would fail that valid case outright.

**GCMD counts and anomalies.** Verified against the same pinned 24.4
export REF-041 froze (`sha256:f31d8137…3f02e2`, 3,774 rows): 2 roots (the
two Categories), **3,772 derived `skos:broader` edges**, 512 (level,
label) homonym pairs (`homonymLabels`, the standing refusal to ever key
this scheme by label). Zero missing ancestors, zero repeated paths, zero
self-edges — and unlike the MeSH rule's counters, which skip-and-count a
missing or ambiguous parent, this rule raises on every premise violation:
REF-041's reader refuses a missing ancestor-prefix row and a repeated
path outright, and the derived-graph path inherits that fail-closed shape
(the replay refuses the same shapes in a shipped graph). The two paths
are one judgment with two readers: `tests/test_gcmd_column_nesting.py`
proves the asserted-payload derivation and REF-041's committed CSV-level
module produce the **identical UUID pair set** over the real pinned bytes
(3,772 pairs, zero divergence) — the oracle discipline, not just an
equal count.

**Corpus cases.** Six new entries in `REQUIRED_CORPUS_CASES`
(141 → 147; 126 → 131 invalid):

1. `gcmd-column-nesting-broader` — the positive case, built in the REAL
   GCMD scheme on a prefix-closed trio of real 24.4 rows
   (EARTH SCIENCE > AGRICULTURE > AGRICULTURAL AQUATIC SCIENCES,
   csv:row[1..3] of the pinned export, real UUIDs as notations). The
   lesson applied: REF-042's MeSH positive case had first been built on
   fixture concepts its own fixed rule should never have accepted; this
   one ships the complete two-row edge set the trio implies so the
   whole-of-rule replay finds no gap and no extra.
2. `gcmd-column-nesting-unallowlisted-rule` — a GCMD row's
   `derivationRule` rewritten to an unregistered IRI;
   `dataset.derived-rule`.
3. `gcmd-column-nesting-wrong-predicate` — `skos:related` instead of
   `skos:broader` under this rule; `dataset.derived-rule`.
4. `gcmd-column-nesting-malformed-inputs` — one cited `SourceRecord`
   instead of two; `dataset.derived-rule`.
5. `gcmd-column-nesting-duplicates-asserted` — an asserted
   `(root, skos:narrower, topic)` `NativeRelationAssertion` beside the
   derived `(topic, skos:broader, root)`; `dataset.derived-authority`.
6. `gcmd-column-nesting-missing-edge` — the case class the MeSH work
   lacked: the shipped row is locally valid (its cited records' payload
   paths really nest) but the set is incomplete — the
   AGRICULTURAL-AQUATIC-SCIENCES → AGRICULTURE edge is missing, and only
   the whole-of-rule replay can refuse it; `reasoning.authority`.

The base fixture gained one inert GCMD release (three concepts, three
records, one release node) no pre-existing case cites, so only the six
mutations touch the derived graph over it; `all-resource-profiles`' own
counts moved as a direct consequence (resources 14 → 17, labels 14 → 17,
sourceRecords 14 → 17, releases 11 → 12).

**Producer.** `_derive_registered_relations` now loops the registered
rule table — (release key, evidence-node finder, derive function) —
instead of a MeSH-only branch, so a rule only fires when its source
release was loaded (the same release-selection scoping REF-042
established), rows from every rule land in one derived graph under one
duplicate-identity refusal, and the prebuild receipt's
`derivedRelations` count is the sum over the same pure resolvers the
streamed pass calls (`_expected_derived_relation_count`). Verified end
to end on real data three ways: a bounded
`--only-release gcmd-science-keywords-24-4` build derived 3,772 rows and
the independent standalone validator passed every gate over that real
distribution (`"derivedRelations":3772`, including
`check-reasoning-isolation`'s whole-set regeneration); a bounded
two-release build (`mesh-descriptors-2026` +
`gcmd-science-keywords-24-4`) derived exactly 46,291 rows
(42,519 + 3,772, both rules in one graph) and validated identically —
rather than the ~2h14m full distribution build this work deliberately
did not run.

**The audit gap closes.** REF-042 left
`tools/build_registry_source_manifest.py`'s `SOURCE_BLOCKERS` recording
that `gcmd_science_keywords_hierarchy.py` could not ship "until the
derived graph admits a GCMD rule," to be exercised "through that rule's
own reproduction check rather than a separate pin." The rule now exists
and the reader is exercised through it: the module's env-gated real-data
test re-derives the frozen edge set from the pinned bytes (the receipt
the audit's plugin captures — `derive_gcmd_science_keywords_hierarchy`
over `sha256:f31d8137…` with `edges.items: 3772`), and
`tests/test_gcmd_column_nesting.py` runs the registered rule over the
same pinned bytes and proves pair-for-pair agreement with that oracle.
The blocker entry is deleted; the module now pins the same publisher
artifact the base reader pins (`gcmdScienceKeywords244`) in
`TEST_INPUTS` — one shared pin for one shared artifact, not a second
capture — and `research/evidence/registry-real-data-audit-2026-08-03/sources.json`
regenerated: the module moved `blocked` → `publisherBytes` (76/86), the
only remaining declared gap is eurovoc, and `make audit-registry-real-data`
passes with exactly that one eurovoc failure listed.

**Digests.** `contractDigest` did not move — `ontology/atlas.ttl`,
`shapes/atlas.shacl.ttl`, `registry-resource-profiles.json`,
`tests/registry-coverage.json`, `tests/registry-descriptors.json`, and
`tests/registry-descriptors.nq` are byte-identical (the rule needed no
ontology or shape change: `skos:broader` was already an admitted subject-
ring predicate and `SourceRecord` an already-admitted evidence kind).
What moved: the binding-tool digest (`validate.py` and `build_fixtures.py`
changed, the cache-invalidation key by design), `corpus_digest()`
(`fixtures/corpus.json`, now 147 cases), and `fixtures-receipt.json`'s
`fixturesDigest`, rebuilt by running `build_fixtures.py` as the six new
cases require regardless.

**Deliberately not done.** The reader
(`refspec.registry.gcmd_science_keywords`) is untouched —
`hierarchyIsDescriptiveNotInferred` stays true in every asserted payload,
and the asserted release still emits zero relations; only its stale
"the binding does not yet admit any second derivation rule" commentary
was updated to point at this entry. FR-compound
(`tools/atlas_v3_derived_fr_compound.py`) is now the only rule REF-042
named that remains unregistered; it still has no ledger entry of its own
and registering it changes nothing here.

### REF-044: Federal Register compound headings become the derived graph's fourth entry (backfilled)

- **Date:** 2026-08-19
- **Status:** Accepted and executed, entry written after the fact. Both
  `bindings/atlas/3.1/tools/validate.py` and
  `bindings/atlas/3.1/tools/build_fixtures.py` shipped code citing "REF-044"
  for this rule (commit `ae23819d`, same day as REF-043's GCMD entry) with
  no matching ledger entry; the producer wiring landed one commit later
  (`2a6e61a2`). This entry closes that gap without re-deciding anything —
  every judgment below shipped already; nothing here changes code.

**The decision.** The Office of the Federal Register's 2025 thesaurus
(`federal-register-thesaurus-2025`, 705 official indexing terms) is
deliberately flat: it publishes 1,451 `skos:related` references and zero
`skos:broader`/`skos:narrower` statements. But 56 of its 705 preferred
labels contain a hyphen, and 48 of those have a head segment — the text
before the first hyphen — that is itself an authorized preferred term of
the same release: `Grant programs-agriculture` under `Grant programs`,
`Loan programs-veterans` under `Loan programs` (19 under `Grant programs`,
9 under `Indians`, 14 under `Loan programs`, 6 under `Public lands`).
Reading a compound heading's broader term as its head segment is a
structural projection of the publisher's own term list, not an invention —
but it is still RefSpec's act, not OFR's assertion of `skos:broader`, so
under REF-035 tier E5 it belongs only in the derived graph, registered as
`urn:ref:rule:fr-thesaurus-compound-head-broader` — the fourth entry in
`_DERIVED_RULE_ADMISSIONS`, engine
`https://refspec.org/code/atlas-v3-derived-fr-compound-headings` version
`"1"`, ring `atlas:subject`, predicate `skos:broader`, evidence kind
`SourceRecord`, mirror predicate `skos:narrower`.

**The 8 self-exclusions are the rule checking itself.** The remaining 8
hyphenated preferred labels are hyphenated *words*, not compound subjects:
`X-rays`, `Truth-in-lending`, `Truth-in-savings`, `Rights-of-way`,
`Over-the-counter drugs`, `Government-sponsored enterprises`, `Human cells
and tissue-based products`, `Old-age, Survivors and Disability Insurance`.
Their head segments (`X`, `Truth`, `Old`, ...) are not preferred terms, so
they exclude themselves — there is no hand-maintained denylist anywhere,
on either the producer or binding side.

**Where the premise lives.** Unlike MeSH (a notation literal) or GCMD (a
CSV path in `atlas:nativePayload`), this rule's premise is preferred-label
*text*, which sits behind SKOS-XL `prefLabel`/`literalForm` nodes the
shared `AssertedFactView` does not collect. `fr_compound_headings.py`
ships its own one-pass label collector
(`collect_fr_preferred_labels`) instead of widening the shared view for
one rule, and both of its entry points (`fr_compound_heading_evidence_nodes`,
`derive_fr_compound_heading_broader_rows`) take that label view as a
second argument alongside the shared `DerivationContext`.

**Scoping, from the first line.** The MeSH rule shipped scheme-blind and
an adversarial battery caught it proving parentage from notation shape
alone; this rule requires the Federal Register thesaurus scheme
(`urn:ref:atlas-resource-scheme:federal-register-thesaurus-2025`) in its
producer label collection, its binding row check, and its binding replay,
so a `Grant programs` term in any other vocabulary can never admit a
Federal Register compound.

**Verified against the real pinned 2025 release**
(`sha256:66dd28fff5defedfb151d04dc4ef255181085cce76618cb10c9372db6540810f`,
1,051,423 bytes, 705 official terms, 1,451 resolved `skos:related`
references): 48 derived `skos:broader` edges, 56 hyphenated preferred
labels, 8 self-excluded, zero ambiguous heads, zero admitted heads that
are themselves hyphenated, zero two-resource label collisions in this
release. Like the MeSH and GCMD replays, this rule's replay is
whole-of-rule, not row-local: it regenerates the *complete* expected
compound/head pair set from the asserted graph's own preferred labels and
requires the shipped row set to equal it exactly.

**Corpus cases.** Six entries in `REQUIRED_CORPUS_CASES`, the second half
of the same-day move from 141 to 153 total cases GCMD's own six opened
(REF-043's entry pins 141 → 147 for GCMD alone, so FR's six carried
147 → 153): `fr-compound-head-broader` (positive, the complete 48-edge set
so the whole-of-rule replay finds no gap or extra), `fr-compound-head-
unallowlisted-rule`, `fr-compound-head-wrong-predicate`,
`fr-compound-head-malformed-inputs`, `fr-compound-head-duplicates-
asserted`, and `fr-compound-head-replay-gap` (the `reasoning.authority`
completeness case GCMD's own sixth case established the pattern for).

**Producer.** `tools/generate_atlas_v3_full.py`'s `_derive_registered_relations`
loop gained an optional per-rule label-collector parameter for this rule
alone (MeSH and GCMD pass `None`): a rule with a collector gets its label
view built from the same spooled lines the shared fact view just read,
then passed to both of its entry points. `_expected_derived_relation_count`
gained the matching branch, calling the same
`resolve_compound_heading_edges_from_labels` resolver the streamed pass
uses, so the prebuild receipt and the emitted rows cannot independently
drift. A bounded `--only-release federal-register-thesaurus-2025` build
derives exactly 48 relations.

**Deliberately not done.** `bindings/atlas/3.1/README.md`'s derived-graph
section was never updated to document this rule (it still read "Three
rules are registered" after this rule shipped as the fourth) — closed by
the EuroVoc entry (REF-046) that follows, which updates the same section
for the fifth rule and adds the missing fourth-rule paragraph in the same
pass.

### REF-046: EuroVoc's microthesauri become a real Atlas release; the registry's fifth derived rule closes the domain gap REF-045 found

- **Date:** 2026-08-19
- **Status:** Accepted and executed.

**The decision.** REF-045 found that the Publications Office asserts the
127 EuroVoc microthesauri and the 7,902 concept-to-microthesaurus
`skos:inScheme` memberships, but never the microthesaurus-to-domain link —
that exists only as a two-digit notation prefix. This entry executes what
REF-045 said would follow: the memberships are publisher assertions and
enter the asserted graph as a real Atlas release; the notation-prefix link
is a derivation and enters the derived graph as the registry's fifth rule.

**The asserted half.** `eurovoc-microthesauri-4.24` is a new Atlas v3
source release (`src/refspec/atlas/v3_registry_vocabularies.py`,
`load_eurovoc_microthesauri_4_24_release`), independent of
`eurovoc-4.24`/`eurovoc-domains-4.24` but reading the same pinned SKOS Core
member: 127 microthesaurus resources in their own scheme
(`urn:ref:atlas-resource-scheme:eurovoc:microthesauri`), each carrying its
publisher notation and EVERY publisher label in EVERY language the source
asserts — 3,430 labels across 27 languages, never filtered to English
(unlike every other EuroVoc-derived release in this module). RefSpec
never determines a language tag here: `eurovoc_thesaurus._label_expressions`
already refuses an untagged label at parse time, so every label this
release carries was read, not guessed. All 7,902 memberships are emitted
as native relations, including every one of the 142+121+1 concepts that
belong to two, three, or four microthesauri at once — multi-membership is
a real publisher fact and none of it is collapsed.

**The predicate the memberships could not use, and the one they do.**
`skos:inScheme` is not an admitted `NativeRelationAssertion` predicate
(`SKOS_NATIVE_RELATION_PREDICATES` is exactly `{skos:broader, skos:narrower,
skos:related}`), and it could not become one for this purpose: the binding's
`SubjectConceptShape` fixes `skos:inScheme` to `sh:maxCount 1`, equal to
`atlas:inScheme` — a concept's one primary EuroVoc scheme membership,
already spent. A concept that belongs to up to four microthesauri cannot
carry four `skos:inScheme` triples under that shape. RefSpec mints a new
native predicate instead, `atlas:hasSchemeMember` (domain and range
`atlas:SubjectConcept`, declared in `ontology/atlas.ttl` beside
`atlas:thesaurusUse`/`atlas:thesaurusUsedFor`/`atlas:thesaurusRelated` —
the same family of Atlas-native predicates that preserve a publisher
relation SKOS cannot project verbatim), added to the subject ring's
`NativeRelationAssertion` list in `registry-resource-profiles.json`
(`profileDigest` recomputed to `sha256:7d7c493346bc80ba45090b2bb32ca3ecd24f2e71cc1f91a23a63fb2d29292942`;
`schemas/registry-resource-profiles.schema.json`'s `NativeRelationAssertion`
`maxItems` raised from 6 to 7 to admit the seventh predicate, the one
contract-shape edit this entry required).

**Direction is inverted from the publisher's own statement, and that is
recorded, not hidden.** The Publications Office asserts `concept
skos:inScheme microthesaurus`. RefSpec asserts `microthesaurus
atlas:hasSchemeMember concept` — the mirror direction, under a distinct
predicate, for a structural reason: the producer requires a relation's
evidence to be a `SourceRecord` native to the release that owns the
relation, and the microthesaurus's own record lives in
`eurovoc-microthesauri-4.24`, not in `eurovoc-4.24`. Keeping the concept as
subject would have required attaching the memberships to `eurovoc-4.24`
instead, coupling that release's construction (and its separate
claim-input replay path, `load_eurovoc_4_24_releases_from_claims`, which
has no way to select "all notated concept schemes" the way it selects
"all resources under `http://eurovoc.europa.eu/domains`") to a release that
did not exist before this entry. This is the SAME fact stated once, in the
other direction — not a second, additional assertion of the publisher's own
direction, which REF-035 forbids. Each relation's `source_payload` records
the transformation explicitly (`fromPredicate`/`toPredicate`/`reason`), the
same transparency `_S27_TRANSFORMATION` already gives EuroVoc's own
`skos:related`-to-`atlas:thesaurusRelated` rewrite.

**The derived half.** `src/refspec/atlas/derived_graph/eurovoc_microthesaurus_domain.py`
derives `skos:broader` edges from a microthesaurus's four-digit notation to
the domain named by its two-digit prefix, registered as
`urn:ref:rule:eurovoc-microthesaurus-domain-notation-prefix` — the fifth
`_DERIVED_RULE_ADMISSIONS` entry, engine
`https://refspec.org/code/atlas-v3-derived-eurovoc-microthesaurus-domain`
version `"1"`, ring `atlas:subject`, predicate `skos:broader`, evidence
kind `SourceRecord`, mirror predicate `skos:narrower`. `skos:broader`
is chosen over `euvoc:domain` under REF-035's predicate rule:
`euvoc:domain` appears nowhere in the publisher graph at all (REF-045), so
naming it as "the" predicate would misrepresent the publisher's own
vocabulary rather than translate it, and it is not an admitted predicate
regardless. `skos:broader` is the predicate every other structural
projection in this registry already uses for a notation-implied parent
(MeSH tree numbers, GCMD column nesting, FR compound headings, REF-042
through REF-044), so it is the honest, consistent choice: a domain is the
broader grouping a microthesaurus's own notation places it under.

**The first cross-scheme rule.** Every prior structural rule derives an
edge between two resources of the *same* scheme. This rule's subject
(microthesaurus) and object (domain) sit in two different, already-shipped
schemes, so it is scheme-scoped in BOTH directions rather than once: the
row validator and the replay each check the subject against
`urn:ref:atlas-resource-scheme:eurovoc:microthesauri` and the object
against `urn:ref:atlas-resource-scheme:eurovoc:domains` independently — a
microthesaurus-shaped four-digit notation on a foreign-scheme resource, or
a domain-shaped two-digit notation on one, can never admit an edge. The
MeSH rule shipped scheme-blind and an adversarial battery caught it; this
rule does not repeat that bug for either endpoint.

**Verified against the real pinned 4.24 release**
(`sha256:6c362f79ad03e325ba1b4818f1ca3a847bb6167c2a8f7167e2e4df91305b6620`,
the same `eurovoc_in_skos_core_concepts.rdf` member `eurovoc-4.24` and
`eurovoc-domains-4.24` are already built from): all 127 microthesauri
resolve their notation prefix to exactly one of the 21 domains — 127
derived edges, zero missing domains, zero ambiguous domains, zero
malformed notations. This is the identical pair set the
`operator-derived-domain-candidates.jsonl` sidecar layer
(`refspec.registry.eurovoc_organization_experiment`,
`generationMethod: microthesaurusNotationTwoDigitPrefix`) already carried
as a non-authoritative candidate; the derived graph now carries the same
127 edges as an admitted, replayable rule instead.

**Producer.** `_derive_registered_relations` gained an optional per-rule
second release key: this is the first rule whose premise spans two
releases at once (a microthesaurus's own notation and a domain's own
notation), so it fires only when BOTH `eurovoc-microthesauri-4.24` and
`eurovoc-domains-4.24` are loaded, reading both releases' spooled lines
combined into one `AssertedFactView`. `_expected_derived_relation_count`
gained the matching branch, calling the same `resolve_microthesaurus_domain_edges`
resolver the streamed pass uses. A bounded
`--only-release eurovoc-microthesauri-4.24 --only-release eurovoc-domains-4.24`
build derives exactly 127 relations.

**Corpus cases.** Six entries in `REQUIRED_CORPUS_CASES`:
`eurovoc-microthesaurus-domain-broader` (positive, built in the real
microthesauri and domains schemes), `eurovoc-microthesaurus-domain-
unallowlisted-rule`, `eurovoc-microthesaurus-domain-wrong-predicate`,
`eurovoc-microthesaurus-domain-malformed-inputs`,
`eurovoc-microthesaurus-domain-duplicates-asserted`, and
`eurovoc-microthesaurus-domain-replay-gap` (the `reasoning.authority`
completeness case, following GCMD's and FR's precedent rather than
MeSH's, which lacked it). Corpus 153 → 159 cases, 136 → 141 invalid. The
base fixture gained two inert releases (two microthesauri, one domain, in
their own real schemes) no pre-existing case cites, so only the six
mutations touch the derived graph over them; `all-resource-profiles`'s own
counts moved as a direct consequence (releases 13 → 15, resources 21 → 24,
labels 21 → 24, sourceRecords 21 → 24, quadCount 1289 → 1402 for the full
distribution and 1161 → 1271 for the asserted-only view).

**The audit gap closes.** `eurovoc_organization_experiment.py` was the
last entry in `tools/build_registry_source_manifest.py`'s
`SOURCE_BLOCKERS`. It is deleted; the module gains a `TEST_INPUTS` pin
reusing the exact `eurovocSkosCore`/`eurovocMetadata` pins
`claim_release_exports.py` already carries (one shared pin for one shared
artifact, not a second capture — the same discipline REF-043 established
for GCMD), and a new env-gated real-data test exercises
`build_eurovoc_organization_artifact_from_paths` over the real pinned
bytes. `make audit-registry-real-data` reports zero blocked modules for
the first time.

**Deliberately not done.** `load_eurovoc_4_24_releases_from_claims` (the
claim-input replay path for `eurovoc-4.24`/`eurovoc-domains-4.24`) is
untouched and does not gain a microthesauri or membership counterpart:
`eurovoc-microthesauri-4.24` has no claim-input replay path of its own and
is always built from the raw pinned RDF. `bindings/atlas/3.1/README.md`'s
derived-graph section, stale since REF-044's rule shipped without a
documentation update, is corrected here for both the fourth rule (FR) and
this entry's fifth.

### REF-047: The CFR's own subject index becomes the second cross-ring carrier, and the Atlas holds CFR parts for the first time

- **Date:** 2026-08-20
- **Status:** Accepted; the construction unit, the portfolio chain, and the
  generated coverage/descriptor artifacts are in. Not yet built or sealed;
  the open item below names what a full build still needs.

**The gap.** The Atlas held fifty CFR *titles* in the legal-identity ring
(`ecfr-cfr-structure`) and 316 agencies in the entity ring, and no CFR part
at all. The Office of the Federal Register publishes the per-part index
directly — fifty static pages under
`https://www.archives.gov/federal-register/cfr/subject-title-NN.html`, "a
list of Code of Federal Regulations (CFR) Subjects arranged by CFR Title and
Part", revised annually. `parse_cfr_subject_index` has read them fail-closed
since 2026-08-20, but the result lived only in
`research/evidence/cfr-subject-index-2026-08-20/` as a CSV.

**What lands.** `cfr-subject-index-parts-2026-08-20`, a `structureScheme`
release in the `legalIdentity` ring under the new `cfr-subject-index`
resource, carrying 8,423 CFR parts and 31,683
`atlas:hasIndexedSubject` cross-ring relations into the subject ring. The
parts are the same kind of thing the titles already are, one structural
level down, and they come from the publisher that writes the index.

**Which decision licenses the crossing.** REF-032 retired one cross-ring
instance and stated the bar in the same breath: the tripwire it installed
"directs whoever trips it to the intended carrier: a genuine
institutional-roster → subject edge, once the Federal Hierarchy roster is
completed **and an authority publishes subject assignments against it**. The
single instance that existed was never that — it was one document's own page
metadata read twice, a report pointing at a label observed on the report."
REF-037 then retired the tripwire itself against the entity → legalIdentity
cell and fixed that carrier at 446, ending REF-032's "no current cross-ring
carrier" state while leaving REF-032 the authority on what a crossing has to
be. REF-032 named an institutional-roster → subject edge as the shape it
expected; this is the legal-identity → subject cell instead, and it clears
the same stated bar rather than the same example. An authority publishes
subject assignments against a structural identity, annually, for every CFR
part, in a vocabulary it does not read back off the same page. It is not one
document's metadata read twice, and the roster edge REF-032 named remains
open.

**The predicate was already there.** Atlas 3.1's closed cross-ring matrix
has three cells, and `legalIdentity → subject` has carried
`atlas:hasIndexedSubject` since the binding was written — admitted, shaped,
and until now empty. Nothing in the binding, the shapes, the ontology, or
`registry-resource-profiles.json` changes: the second cell simply gets its
first publisher. A crossing that needed a new predicate would have been the
signal to stop.

**No concept identity is minted, and the residue is counted.** The publisher
writes term *strings*. Each is resolved against the held
`federal-register-api-topics` concepts by exact case-folded preferred-label
match, and an unresolved term is skipped, counted, and left verbatim on its
part's `unresolvedIndexTerms`. Of 1,068 distinct terms, 863 resolve and 205
do not; of 32,186 distinct part/term assignments, 31,683 become relations and
503 do not. 1 CFR 18.20 requires terms drawn from the Federal Register
Thesaurus but permits agency-added ones, so a residue was expected; measured
against both Federal Register vocabularies, 869 of 1,068 terms resolve and
the 199 that do not account for 412 of 32,200 publisher assignment rows.
Most of those are transcription drift, not local invention
("administrative practice and procedures" for the singular; "reporting and
recordkeeping" truncated). That is a vocabulary-governance finding, and it is
now a test rather than a paragraph.

**Publisher facts kept, not repaired.** The publisher lists 7 CFR 1000,
29 CFR 4231, and 48 CFR 642 twice each. Minting two resources would split one
legal identity; dropping the second entry would lose terms. The adapter
merges the term lists in publisher order and records
`publisherListedPartTwice` on the resource. 8,426 part entries, 8,423 parts,
both pinned — collapsing them would hide either the duplication or its
repair. Twenty parts carry no resolvable term and stay legal identities
anyway; a part is not a subject assignment.

**The bytes are tracked.** All fifty pages are pinned by sha256 and byte
length in `CFR_SUBJECT_INDEX_2026_08_20` and tracked under
`tests/fixtures/cfr_list_of_subjects/subject-index/` (4.0 MB), with per-title
part counts pinned separately so a publisher edit that adds parts to one
title and removes as many from another cannot pass as unchanged. The source
manifest describes them as one `sourceCollection`, the ICPSR precedent. The
`federal-register-api-topics` capture the resolution reads is tracked
byte-identically beside them for the same reason the ICPSR builder tracks
its two: the capture location stays named in the manifest, but the crossing
must be reproducible from a clean clone.

**Two audit accommodations, both stated rather than hidden.** The real-data
receipt gate resolves a registry module's direct tests by the module's own
name, so `tests/test_cfr_subject_index.py` -- named for the source rather than
the reader -- was invisible to it and all fifty pins read as unconsumed;
`direct_test_paths` now names both files for this module. And reserved CFR
title 35 parses correctly to zero parts, so it can never produce the
substantive counts the gate asks of a publisher input. It leaves the
collection for its own `receiptRequired: False` descriptor with the reason
attached, rather than the whole collection being exempted. The other
forty-nine pins are consumed with real parsed counts in the same execution,
and `make audit-registry-real-data` reports the gate passed.

**Open, and named.** `tools/verify_atlas_source_fidelity.py` has no
`SourceSpec` for this unit. A full-distribution
`make audit-atlas-v3-source-fidelity` will therefore fail it with "no
independent publisher comparison was performed", and that is the honest
state: the independent reader REF-037 requires has not been written, and
writing one that cannot be exercised without a release-tier build would be
worse than recording its absence. That reader, a full build, and a reseal are
what this unit still needs before it appears in a sealed distribution.

### REF-050: the distribution identity binds constructed content

- **Date:** 2026-08-21
- **Status:** Accepted and implemented (d2932a11).

Two full builds on 2026-08-21 — before and after the EuroVoc microthesauri
English-only change — produced **different content** (labels 2,310,406 vs
2,307,103; canonicalPayloadDigest, contractDigest, assertedInventoryDigest
and releaseInventoryDigest all differ) under **one distributionId**
(`…f70a7659…`), because `distribution_identity()` digests the *source
accounting*, and a normalization-policy change alters what the producer keeps
without altering what it reads or how records are dispositioned.

Consumer integrity is unaffected — the search-view asset chain pins
`manifestSha256`, which differs — but the id is the name humans and logs use,
and today it named two different artifacts. Options: fold
`canonicalPayloadDigest` (or the manifest digest) into the identity, or
rename the field to state what it binds (`sourceAccountingIdentity`).
Either changes every future id or the schema; a contract-level decision.

**Resolved the same day.** A third build (21c) reproduced the collision
exactly — different asserted graph, same id — which settled that the field
was misnamed rather than unlucky. The accounting now carries the asserted
graph's inventory digest and the identity closes over it, so two builds
differing in constructed content cannot share an id. The digest exists only
once the packs are sealed, so the ledger is assembled with a digest-shaped
sentinel and stamped at write time in both the whole-graph and streamed
paths; the producer receipt is rebound to the file as written, since
stamping adds identity to the ledger the producer already validated. A test
asserts the property directly: restamping one ledger against a different
graph moves its id.

Consumers were never exposed — the search-view asset chain pins
`manifestSha256`, and the one live consumer had already ruled the id a label
rather than a key. Distributions built before this carry the old shape and
must be rebuilt to validate.

### REF-048: DocSpec owns the platform source catalog

- **Date:** 2026-08-25
- **Status:** Accepted; implementation and package consolidation remain open.
- **Supersedes:** REF-024 only where it assigns source selection and
  `SourceCatalogRelease` publication to SpicyRegs and catalog consumption to
  DocSpec. All other REF-024 ownership rows remain in force.

> **Ownership update (2026-09-02):** the 2026-08-24 platform-allocation ruling
> moves source-native acquisition and publication out of SpicyRegs, which this
> entry assigned it to, and into the platform, with SpicyDocs as the
> incubator. SpicyDocs adopted the 2026-08-25 source-native release spec
> verbatim on 2026-08-30
> (`../spicy-docs/docs/superpowers/specs/2026-08-25-source-native-release-spec.md`)
> and its reader declares `SUPPORTED_PRODUCER_PRODUCTS = {spicy-regs,
> spicy-docs}` (`spicy_docs/source_native.py`); DocSpec's adapter
> (`src/docspec/adapters/spicyregs_source_native.py`) is moving to resolve
> `spicy_docs` first, `spicy_regs` only as fallback, and to refuse any reader
> whose producer set is narrower than the spec's. The SpicyRegs copy
> (`src/spicy_regs/{regulations_gov,federal_register}_source_native.py`,
> `source_native_cli.py` on branch `integrate/payload-prereqs`) retires by one
> small upstream PR once a SpicyDocs release verifies. See the deciding record
> (`../spicysearch/docs/history/2026-09-01-script-product-disposition.md`,
> "Decision record — 2026-09-02 addendum") rather than restating it here.

The greenfield platform has one generic artifact container and one owner for
document-catalog meaning.

- Rulespec owns only generic container mechanics: canonical bytes, identity,
  manifests, membership, bounded structural verification, diagnostics, and
  injected member access. It also owns the optional product-neutral
  `DerivationRelation` and `CompositionRelation` helpers and their validation
  after structural admission. Product `kind` and canonical `spec` values remain
  identity-bearing, but Rulespec does not validate document-domain meaning or
  run either helper unless the product semantic verifier opts into it.
- SpicyRegs owns source-specific acquisition and faithful source-native records.
  It publishes those records as immutable, versioned, digest-pinned inputs
  through the generic container using product kind
  `spicyregs-source-native-release`. It does not select a DocSpec universe,
  publish or verify `SourceCatalog`, process documents, or depend on DocSpec.
- DocSpec owns the normative `SourceCatalog` and `SourceItem` specification,
  schema, catalog policy, bounded builder, reader, semantic verifier, and
  publication. It preserves source-native facts and records normalization,
  joins, sampling, rendition preference, and selection as explicit
  identity-bound interpretations.
- RefSpec has no platform catalog task, required catalog pin, or DocSpec edge.
  Its governed reference resources and Atlas search views remain independent
  optional SpicySearch inputs. RefSpec owns the asserted agency identities,
  preferred labels, aliases, warrants, and published agency projection.
  SpicySearch owns any catalog-specific coverage and collision qualification
  before it uses that optional projection for labels or suggestions. An
  unresolved or colliding catalog value stays a bare source ID; neither product
  may convert a consumer qualification into a new RefSpec identity claim.
- SpicySearch consumes the installed DocSpec catalog surface. It owns search
  derivation, composition, ranking, evidence, coverage, exports, and serving;
  it does not construct catalogs or implement catalog validation. At admission
  it runs the installed Rulespec structural reader followed by the installed
  DocSpec bounded reader and semantic verifier, and it checks the producer's
  semantic-build receipt. Expensive semantic recomputation remains at DocSpec's
  producer gate rather than running again in SpicySearch.
- SpicySearch also owns the offline, read-only historical derivation trace over
  the finite cross-product inventory because it is the only product that joins
  these artifact families. Owner-supplied adapters verify legacy sealed roots;
  new roots use their installed readers. This operator tool has no publication,
  promotion, or serving authority. Rulespec owns no global registry, and
  discovery cannot block a product pointer. Predecessor measurement M6 must
  authorize any later durable index through a separate accepted decision.

The DocSpec specification at
`../DocSpec/docs/superpowers/specs/2026-08-05-docspec-standalone-platform-implementation-spec.md`
is the singular catalog and document-processing specification. The Rulespec
platform-artifact specification is the singular generic container
specification. The SpicyRegs specification at
`../spicy-regs/docs/superpowers/specs/2026-08-25-source-native-release-spec.md`
is the singular source-native acquisition and publication specification. No
compatibility format or dual writer is required. No
general-purpose migration reader belongs on the greenfield runtime path. A
finite owner-supplied read-only adapter remains required only when a named
transition gate needs it, including DocSpec §9.10 and the historical trace
above; it retires with that gate and cannot write a legacy format.

Existing implementations are evidence and migration inputs, not authority.
Before deletion, DocSpec must reproduce the accepted landing catalog semantics
from Git-pinned executable fixtures and one independently verified migration
result. `spicy-regs-landing`, both SpicyRegs catalog implementations, duplicate
SpicyRegs document pipelines, Rulespec document-domain schemas, and duplicate
consumer validators may then be removed only after their supported behavior is
covered by owner tests.

### REF-049: Retain and publish the Federal Register alignment as the sixth derived rule

- **Date:** 2026-08-25
- **Status:** Accepted capability; binding conformance remains open. The rule
  behavior and portable cases exist, but the parallel Python admission roster
  must be removed before implementation is accepted. A full Atlas distribution
  built under the corrected contract still requires rebuild, validation,
  sealing, and publication.

**The capability stays.** The Federal Register thesaurus/API-topic alignment
was added to solve a real join: the Office of the Federal Register publishes a
curated thesaurus and the separate topic list used to index documents, but no
cross-vocabulary relation between them. The implemented rule turns exact
case-folded preferred-label agreement into an explicit, reproducible graph
record. Removing it would restore an ambient string join in every consumer.
Atlas therefore retains
`urn:ref:rule:fr-thesaurus-api-topic-label-equality` as its sixth admitted
derived rule, with engine
`https://refspec.org/code/atlas-v3-derived-fr-thesaurus-api-topic-alignment`,
version `"1"`.

**The meaning is deliberately narrow.** The rule emits non-authoritative,
opt-in `skos:closeMatch` rows from the Federal Register thesaurus scheme to the
Federal Register API-topics scheme. Both endpoints are subject concepts. Each
row cites exactly the two endpoint `SourceRecord`s. Preferred-label comparison
uses Unicode case folding over canonical, non-empty trimmed Atlas label text,
and the rule adds no punctuation, compatibility, stemming, or lexical
normalization. Folded labels must be unique within each scheme, the result must
be a bijection, and whole-rule replay must regenerate the identical complete
pair set once any row invokes the rule. A distribution remains free to omit the
rule entirely.

`skos:closeMatch` is the positive semantic choice because it is symmetric for
retrieval use without being transitive. Label equality does not authorize
`skos:exactMatch`, an editorial assertion, a reciprocal attestation, or a
downstream serving decision. An asserted `closeMatch` in either direction or
an asserted stronger `exactMatch` over the pair makes the derived row
redundant, so both forms are refused.

**The registry is now part of contract identity.** The canonical
`bindings/atlas/3.1/admitted-derived-rules.json` file names all six rules'
identity, engine/version, ring, predicate, endpoint schemes, evidence kind,
direction, mirror and stronger-collision predicates, row-shape profile, and
replay profile. It participates in `contractDigest`, and the standalone
validator MUST parse it as the sole semantic admission roster. Python may map a
rule ID to its replay callable but MUST NOT restate endpoint schemes,
predicates, sources, selection policy, row-shape profile, or replay profile.
The current `_DERIVED_RULE_ADMISSIONS` equality check duplicates those fields
and is migration debt, not conformance. Remove it, add the static no-copy gate,
and prove every registry field through the independent mutation corpus before
claiming the binding implemented. This keeps the declared admission policy
digest-covered while keeping executable functions replaceable. Row and replay
implementations remain separately covered by the fixture receipt and
validation-cache tool digest, and the portable corpus proves their behavior. A
policy change must update its registry fields and move the contract digest; a
behavior-preserving implementation change moves the tool digest and must retain
conformance parity.

The new contract digest is
`sha256:62e50115689896d37ca95b2503e85f431a350e083b3a8b2f0881227fbacbcfcc`.
Older distributions keep their historical meaning but do not validate under
this binding identity; they must be rebuilt and resealed before publication as
current Atlas 3.1 artifacts.

**Portable proof.** Ten rule-specific cases cover the complete valid pair
set, unregistered identity, wrong predicate, malformed evidence, foreign
scheme, reversed direction, reciprocal asserted `closeMatch`, asserted
`exactMatch`, folded-label ambiguity, and incomplete replay. Together with the
four positive graph-shape cases and the evidence-count mutation below, the
sealed corpus now contains 174 cases, 151 of them invalid, at corpus digest
`sha256:4afab5c8686160e0f08a23f2f998da7b1f65ea1ae230ec4b35f54bcecd2f7f6c`.

The graph-theory assessment in
`research/graph-theory-relevance-2026-08-24.md` (arXiv:2308.04512) also led to
four positive portable proofs of existing Atlas promises:

- two distinct assertions may support one projection record;
- several evidence bindings may support one assertion when their records have
  one construction owner, while a stale evidence count is refused;
- reciprocal publisher-authored `skos:related` rows remain two directed
  assertions and two projections; and
- general hierarchy reachability crosses safely from a cyclic strongly
  connected component into the condensed directed graph, with no universal
  Atlas directed-acyclic-graph rule.

The multiple-evidence case exposed and corrected a construction checker that
still required one evidence binding even though the RDF model and binding
already allowed several. Statement construction ownership now accepts the full
evidence set when all bindings resolve to one construction unit and still
fails closed when ownership is ambiguous.

### REF-051: The fork resolves by supersession — the standalone checkout is canonical

- **Date:** 2026-08-31
- **Status:** Accepted. Ruled with measurements taken the same day; closes
  item 8 of the 2026-08-28 path-forward memo
  (`../spicysearch/docs/history/2026-08-28-path-forward-memo.md`) and the gate
  in §0 of `plans/2026-08-31-refspec-intake-ledger.md`.

RefSpec existed as two diverged lines: the spicysearch submodule at
`141fd671` (54 unique commits, authored 2026-08-21 through 2026-08-25) and
this standalone checkout (14 unique commits at ruling time), with merge-base
`2a6e61a2`. Neither contained the other, and the intake ledger correctly
refused to land any port until a side was picked on purpose.

The measurements that decide it, taken 2026-08-31 against `141fd671`:

- **Zero paths exist in the submodule tree that are absent from this tree.**
  The standalone tree is a strict path superset.
- Of the 63 code-path files whose content differs, the submodule side holds
  **579 lines this tree lacks against 40,722 lines this tree adds** — and the
  579 are the superseded early drafts of modules this line rewrote wholesale:
  the citation grammar's original docstring and regex layout (its boundary
  guards, plural-license expansion, lettered-part accounting all survive here
  in evolved form — `CFR_LETTERED_PART_SHARE = (272, 8_424)` included), and
  the Unified Agenda producer's first three-table skeleton.
- The submodule tip's five build commits (the shared artifact protocol,
  file-state receipts, the singular artifact package, the duckdb range) are
  **absorbed**: this tree's `pyproject.toml` equals the submodule's plus the
  slow-marker block added here.

So the fork is history, not content: the 2026-08-28 consolidation copied the
work faithfully, and the divergence that remained was two commit graphs
describing one tree lineage. Ruling: **this checkout is the canonical line**
(consistent with the 2026-08-21 relocation of the canonical checkout to
`~/Work/RefSpec`), and every intake-ledger port lands here. Nothing is
deleted to say so: the submodule line survives as
`refs/snapshots/pre-consolidation-2026-08-28` in the spicysearch checkout and
as `refs/snapshots/submodule-line-2026-08-31` (→ `141fd671`) in this
repository's object store, fetched and pinned as part of this ruling. The
spicysearch-side execution — repointing its submodule to this line — was
attempted the same day and correctly refused by its own safety gate: that
worktree held six files of unrelated in-progress work, and a repoint does not
land on someone's dirty tree. The measurement that makes the eventual repoint
low-risk is recorded: nothing in spicysearch's test suite imports the
`refspec` package at all (its references are filesystem paths via
`REFSPEC_CHECKOUT` plus one lazy import in a standalone script), so the pin
move is nearly inert there. It waited only for a clean worktree — and
executed the same day, once that worktree's owner landed their milestone:
spicysearch commit `5ee3d34` moves the pin `141fd671 → 99167ca1`, flips the
submodule URL from the local file path to the GitHub URL (resolvable now
that this line is pushed), and its full fast tier passed against the new
pin, 1,319 tests green. The measurement held exactly.

**Erratum (2026-08-31, later the same day — figures re-anchored, disposition
unchanged).** A six-agent branch-retention audit could not reproduce this
entry's figures and was right to complain: they were stated without naming
the commit they were measured at. Both measurements are true at their own
anchors, verified side by side: at `34ca2b67` (this entry's measurement
moment) the archive tree has **zero** paths absent from this tree and the
scoped code-path diff is 63 files / 579 archive-side lines, exactly as
recorded above; at `64a55685` (the audit's anchor, twenty commits later) one
archive-only path exists — the rc15 vendored wheel, deleted here by the rc16
bump, no content loss — and the all-paths diff reads 56 files / 2,869
archive-side lines (35 / 721 scoped; the reverse direction differs by a few
lines on three alignment-sensitive files). The rule this buys: **a diff
figure restated anywhere must name its anchor commit, its direction, and its
pathspec.** The supersession itself was independently re-confirmed at
content level by that audit, including the one absent mechanism
(`cfr_additional_parts`), which the archived branch had itself superseded
nine and a half minutes after writing it. Audit record:
`~/Work/corpora/_retained-2026-08-31-refspec-branches/`.

### REF-052: The column is the license — the Federal Register document-number recall ruling

- **Date:** 2026-08-31
- **Status:** Accepted. Makes the call `identifier_shapes.py` asked for
  (ledger §2.1) and licenses the bare-legacy mint (ledger §1.2).

`identifier_shapes.py` deliberately leaves 10,340 letter-opening Federal
Register document numbers unread in prose — three-digit-and-shorter tails,
two-digit prefixes, six-digit tails, legacy-prefix-over-modern-body hybrids,
each family with a verified live example — and states that widening is a
recall decision with its own false-positive budget, not a defect. Separately,
394,128 of 1,004,233 (39.2%) real `document_number` values are the
bare-numeric legacy shape (`09-19806`) that no reader in the module admits at
all. The decision had an evidence base and no owner. It now has both:

- **Prose detection does not widen.** Not for the four letter-form families,
  not for the bare-legacy shape. Every extra admission is a false positive
  waiting in an unrelated sentence, and nothing measured since the module's
  own accounting changes that budget. Refused.
- **Column-licensed reading admits every family with a verified live
  example.** A value arriving from a trusted `document_number` field is
  licensed by the field, per the module's own two-readers doctrine. The
  bare-legacy shape — 39.2% of the corpus, essentially every pre-2000
  document, and the identity the freshly landed pre-2000 FR body text dead-ends
  without — mints immediately through the minting layer's column-licensed
  path. The four letter-form families (10,340 values, ~1%) are admitted by
  this ruling and start reading when `identifier_shapes.py`'s column reader
  takes the bare-legacy shape natively: that module is receipt-pinned, and a
  shape move alone does not buy an artifact rebuild, so the move is batched
  with the module's next rebuild unit.

The running check this ruling arrives with: the minting layer's tests prove
the license boundary in both directions — the bare-legacy shape refused
without the column license and minted with it.

### REF-053: Open-vocabulary concept lifecycle stays unported — no owner, no consumer, no check

- **Date:** 2026-08-31
- **Status:** Accepted. Rules ledger §2.2; reopens only on the condition
  named below.

The archived lifecycle machinery — candidate minting, promotion, deprecation
with multi-source quotas, and a merge pass bounded to one facet and source
vocabulary (`~/Work/corpora/_nuggets-2026-08-27/source/src/spicy_regs/`
`ontology/concepts.py:202-224,395-419,1223`) — has no home on this platform,
and this ruling declines to invent one. RefSpec is closed-world by design:
managed vocabulary bundles, curated releases, nothing minted from corpus
behavior. SpicySearch is strictly closed-vocabulary, one scheme per build, by
its own design. No product runs open-vocabulary concept promotion today, so a
port would be machinery with no consumer and no check that breaks — exactly
the structure this repository's first rule exists to refuse.

The nugget-ledger row is the durable record of where the code and its
lessons live. Reopen when — and only when — a consumer arrives that needs
open-vocabulary minting; it brings its own ownership question and its own
breaking check, and that future decision should weigh the quota and
single-facet merge rules the archived implementation already paid for.

### REF-054: rkaf's frdoc and CFR spaces widen upstream — 28,862 documents come in from the partner hatch, and one gap is deliberately left open

Successor to REF-052, which ruled that the Federal Register `document_number`
column is its own license and recorded what rkaf could not spell. That ruling
stands; this one narrows its scope, because rulespec `0.2.0rc16` moved two of
the three lexical spaces REF-052 argued from.

**What changed upstream.** `rkaf:us-frdoc` becomes
`^urn:rkaf:us:frdoc:[0-9]{4}-[0-9]{3,5}$`, and a `rkaf:us-cfr` part becomes
`[0-9]+([a-z]|-[0-9]+)?`. `rkaf:us-rin` is unchanged. Both widenings are
strict supersets — verified by exhaustive and 4M-sample search — so no
previously valid identifier changed meaning, and this repository's vendored
wheel moved rc15 → rc16 to carry them.

**Why frdoc, measured.** 28,862 real documents (2,599 three-digit tails,
26,263 four-digit, all published 2010–2013) were refused for sequence width
alone. First-class coverage of the pinned 1,004,233-value column goes
451,704 → **480,566**, 45.0% → 47.9%; the partner hatch drops 540,282 →
**511,420**; refusals hold at **12,247**; identified coverage is unchanged at
98.8%, because the widening moves values between schemes and identifies
nothing new. The load-bearing safety proof is that it splits no identity:
across all 480,566 admitted values, no document has both a padded and an
unpadded spelling, so nothing gained a second first-class identifier. The
ceiling stays at five because zero modern values reach six digits and the
largest sequence ever issued is 33,861 (2011). The floor stays at three so
the space is exactly co-extensive with
`identifier_shapes.FEDERAL_REGISTER_DOCUMENT_NUMBER` — a **consistency**
argument, not an evidential one, and worth naming as such: `2010-99` and
`2010-100` are consecutive documents of one unpadded series, and the floor
admits the second and refuses the first. The 286 values below it are recorded
here so a future floor decision has the number.

**Why CFR, and why the minter is narrower than the space.** 272 of the OFR's
8,424 parts are not plain digits: 83 carry a single letter, 189 carry a
hyphen-number suffix, and every one of those 189 is in title 41. rulespec's
vocabulary describes the real CFR, so the space carries both branches.
`mint_cfr_iri` carries only the letter branch, folding the suffix to
lowercase — lossless, with zero case-fold collisions across the index, and
necessary because `parse_cfr_citations` emits the publisher's uppercase for
the four parts published that way (26 CFR 16A, 29 CFR 4022B, 29 CFR 4041A,
46 CFR 147A). It refuses the hyphen branch because nothing here can produce
one: no pinned column carries a hyphen part (852 distinct `cfr_part` values,
100% numeric), and the prose reader stops at the hyphen — correctly in 48 of
the 49 titles, where a hyphen means a range (`40 CFR 60-63`), a loosely
written section (`28 CFR 23-4`), or a numbered standard (`49 CFR 571-108`).

**The defect this surfaced, deferred not fixed.** Because that capture stops
at the hyphen, `parse_cfr_citations("41 CFR 101-1")` returns part `101` and
minting it yields `urn:rkaf:us:cfr:41:101` — a first-class identifier for a
part that does not exist, since not one of title 41's 16 hyphen heads is a
part in its own right. Minting the hyphen form would have replaced a named,
tested gap with a silent wrong answer, which is the same argument that kept
RIN unchanged. The fix requires a title-conditional rule in
`citation_grammar._CFR_PART_CAPTURE`, which is receipt-pinned. **Reopen
trigger**: a receipt-authorized `citation_grammar` rebuild that captures the
complete hyphenated part. The phantom is pinned as current behaviour by
`test_a_hyphen_numbered_cfr_part_is_in_the_space_and_out_of_the_minter`, so
fixing it upstream turns that test red on purpose.

**Why RIN was left alone.** It was examined in the same pass and deliberately
not widened. The authoritative roster is 46,547 RINs with **zero** outside
`[0-9]{4}-[A-Z]{2}[0-9]{2}`; the only published format statement anywhere —
the Fish and Wildlife Service handbook's "two letters followed by two
numbers" — *is* that production; the five known out-of-space RINs are
unreachable by relaxing the last two characters anyway; and this repository's
own prose reader already agrees with rkaf. Here the direction of REF-052's
framing inverts: the gap is in RefSpec's column shape, not in rkaf, and
`iri_minting`'s prose was corrected to say so. Widening would have deleted a
working tripwire for a coverage gain of provably zero.

**Reconciliation and migration.** A lexical-space widening moves values from
the partner hatch to first-class deterministically and without a lookup:
`urn:rkaf:partner:refspec:frdoc:X` becomes `urn:rkaf:us:frdoc:X` exactly when
`X` enters the widened space, because `mint_partner_iri` percent-encodes the
source value losslessly, so the partner IRI carries everything the rewrite
needs. The migration is **one-directional**: a first-class identifier never
demotes, and a future *narrowing* would strand values already published as
first-class — a breaking change requiring its own decision, not a bump. At
this widening the migration is a **no-op**, measured: the minting layer has
no production consumer at all (only its own test module imports it), and no
built artifact under `output/`, `bindings/`, `portfolio/`, or `deploy/`
carries a minted IRI. Any FUTURE widening must repeat that measurement first
and, if persisted partner IRIs exist by then, ship the rewrite alongside the
contract bump rather than after it.

**What stays open, named rather than implied.** Three refusals survive and
two of them are new asymmetries this change made visible. 394,128 bare-legacy
numbers still have no first-class space. **5,829** letter-opening values are
still refused for exactly the short tail this change fixed for the modern
family — one of two identical holes closed. And **96** official corrections of
documents that just became first-class stay refused, because
`identifier_shapes` hard-codes the correction form to a five-digit tail: after
this change `2010-1863` is first-class while its own correction
`C1-2010-1863` is not. All three live in receipt-pinned `identifier_shapes`,
so none could be fixed in this unit; they are deferred decisions, not
oversights.

The running check is the census test, which re-derives all four buckets
against the real column rather than pinning arithmetic, plus the
contract-verbatim gates that hold this repository's copies of the spaces true
against the vendored wheel. The census lost its `modern-short-tail` bucket
rather than pinning it at zero: a bucket naming an empty population is
structure that stopped earning its keep.


### REF-055: The staging ground empties — corpora was temporary, and the win is anchoring, not durability

- **Date:** 2026-08-31
- **Status:** Accepted. Supersedes the intake ledger's §4 doctrine and the
  regeneration register's original preamble, both of which stated that
  `~/Work/corpora/` is the durable home and that nothing moves into the
  repository.

The owner's ruling: corpora was only ever a temporary staging ground for the
2026-08-27/28 salvage waves, and everything RefSpec-shaped comes home. The
come-home wave of 2026-08-31 moved the million-row Federal Register metadata
corpus, the crosswalk's three intact inputs and its sealed receipt, the USC
annual archives and eCFR title XML (already resident at their top-level
`output/` convention), the FR-thesaurus-2025 managed release (previously
read out of the sibling spicy-regs checkout), and the nuggets evidence into
this repository — every byte digest-verified against its manifests before
and after the move, every code and test reference re-pointed in the same
change, and the sibling-checkout anchor (`SPICY_REGS_ROOT`) deleted with a
boundary test suite standing where it fell.

**What this ruling is careful NOT to claim.** `output/` remains gitignored,
and the destroyed-output-trees history that motivated the old doctrine is
real. Coming home therefore buys **path anchoring** — a clean checkout plus
its own `output/` tree rebuilds and re-verifies with no path outside the
repository — not durability. The durability story is unchanged: the corpora
copies were left in place as the second copy (dual-homing), and they remain
so until `output/` gains a distribution or manifest gate of its own. A
future reader quoting the old register preamble for "corpora is the durable
home" is quoting a superseded document; a future reader deleting corpora
because "everything came home" is deleting the current second copy.

**The evidence-home half of the ruling.** Evidence cited by shipped code
lives in-repo (the doctrine that committed the Wayback EO bytes). The
nuggets source tarballs, sweep receipts, and `invariants.py` are committed
at `research/evidence/spicy-regs-nuggets-2026-08-27/` — 23 MB of
incompressible archives, priced and accepted deliberately, because every
reimplemented port's docstring cites them by member path and a citation
that dangles on every other checkout is worse than the megabytes.

**Erratum to REF-052 and REF-054 (same wave, hours later).** REF-052's
staged move landed: the bare-legacy shape and all four letter-opening
column families now read natively in `identifier_shapes.py`, delivered
through exactly the rebuild unit REF-052 promised (producer hash moved,
all four agenda table digests byte-identical). The figures those entries
stated are re-anchored per REF-051's own erratum rule — anchored at the
post-move census over the same 1,004,233-value column: letter-opening
117,292 → **127,523**; refused 12,247 → **2,016**; identified coverage
98.8% → **99.8%**. The surviving deferrals, measured by resolving each
value: 1,370 bare short-tails (the standing floor decision), 286 modern
short tails below the floor, 228 collision-suffixed, 99 short-tail
corrections (96 of which point at now-first-class originals), 32
colophon-fused (9 letter-opening + 23 digit-opening), and `granule293`.

### REF-056: The FR short-tail widening cycle — 1,656 more document numbers read, and the remaining 360 named one by one

- **Date:** 2026-08-31
- **Status:** Accepted. Makes the floor decision REF-052 deferred for the
  1,370 bare-legacy and 286 modern short-tail values, by the recipe REF-052
  established: raw-read a stratified sample, rule, license the column,
  re-pin the census.

**Decision.** Both populations are column-licensed — two new productions,
`_FR_BARE_LEGACY_SHORT_TAIL` (`\d{2}-\d{1,2}`) and `_FR_MODERN_SHORT_TAIL`
(`\d{4}-\d{1,2}`), checked only under `column_licensed=True`, disjoint from
every existing production by construction (a closure-guarded test now
proves it over all eleven FR productions and names the two intentional
pre-existing overlaps the alternation order resolves). rulespec's own
mintable space (`FEDERAL_REGISTER_DOCUMENT_NUMBER`) is untouched; the
modern-shaped population mints through `rkaf:partner-defined`, a separate
unmade ruling with its own budget.

**Evidence.** 24 specimens (14 bare-legacy, 10 modern), stratified by tail
length and including the year-boundary sub-clusters (`93-54`, `2013-58`),
each read against the publisher's own PDF or full-text extraction, as pixels
and as text (`research/evidence/fr-short-tails-2026-08-31/`). All 24 carry
an ordinary printed colophon; none is damage. `2010-1` beside `2010-117` on
75 FR 1009 and `07-99` beside `07-100` on 72 FR 1551 are the comparisons
that show the short tail is the low end of one numbering series, not a
different kind of string. What the year-boundary specimens do NOT establish
is what determines the year token — both printed dates are excluded, and no
retained source records a submission timestamp — and this decision does not
need it.

**Measured effect.** `refused` falls 2,016 → **360** (0.2% → 0.036% of the
column); two buckets appear, 1,370 (112 one-digit + 1,258 two-digit tails)
and 286 (27 + 259); first-class, bare-legacy and letter-opening are unmoved
by one value; the partner hatch grows 521,651 → **523,307**; all 1,003,873
admitted values still carry distinct IRIs, now asserted over the whole
column together with the three real bare-short/padded pairs
(`96-30`/`96-00030`, `97-29`/`97-00029`, `97-63`/`97-00063`).

**What stays refused, re-measured and asserted exactly.** The 360 partition
into seven classes: 224 `-2`-suffix collisions, 99 short-tail corrections,
27 colophon-fused values, 4 extra-hyphen spellings, 4 trailing-letter
values, `94-S16142` (the API's number for a page that prints
`94-00000`), and `granule293`. That corrects the summary carried since
REF-052: only 224 of the "228" carry a `-2`, and the "32 colophon-fused"
was a catch-all holding 27 fused values plus five that are not fused — the
publisher prints `C0-6263A` (a correction of correction `00-6263`, 65 FR
18151), `C9-20022A`, `94-2050F` and `2014-04654s` with a trailing letter,
and `94-94-30552`, `95-26-82`, `95-95-22339`, `95-95-744` with an extra
hyphenated segment, each beside a well-formed control colophon on the same
page. Neither class is ruled on here; both are recorded with a count, the
posture REF-052 took toward the 1,370 this decision licenses.

### REF-057: An Executive Order existence oracle, window-split by publisher density — and its first published claim was wrong

- **Date:** 2026-08-31
- **Status:** Accepted for the module; the fence wiring is a named follow-up
  (`research/evidence/eo-roster-2026-08-31/WIRING-SPEC.md`).

`refspec.registry.eo_roster` fences Executive Order citations the way
`usc_section_oracle` fences a U.S.C. section: a 6,147-number roster
re-derived from manifest-verified publisher bytes (the committed
`inv-eo`/`inv-eo-gap` captures plus NARA's 1939 disposition table, fetched
and pinned this wave), sha256-pinned, split into three declared windows
whose densities are measured — `nara_codification` (9–12,667) 34.7%,
`nara_disposition` (12,668–12,889) 222/222, `fr_api` (12,890–14,420)
1,531/1,531 — of which exactly one, the dense FR-API window, may ever say
`absent`; a miss anywhere else is `unknown`, never `absent` (EO 9397 is the
specimen). It affirms 378 of 391 cited numbers / 18,954 of 19,011 rows,
leaving 10 honestly unknown.

**The ruling worth recording is what the review caught.** The lane read one
NARA per-order route returning "Page Not Found" and published "8284 does
not exist at all" — while this repository's own committed evidence
(`research/evidence/silent-misreads-2026-08-22.md`;
`silent-misreads-2026-08-24/adjudication/B_2.tsv`) had recorded the
order's official title and date all along. EO 8284 is *Prescribing the
Duties of the Librarian Emeritus of the Library of Congress*, signed
1939-11-13, published at 4 FR 4603, and NARA's 1939 table lists it between
8283 and 8285. **A route-level 404 is a fact about a route.** The doctrine
that caught this is the doctrine the module enforces in the other
direction: a miss in a sparse window may only ever read `unknown`. The
oracle was right about EO 9397 for the same reason it was wrong about EO
8284, and only the committed-evidence habit made the difference visible.
The mined backlog's rider that the 8284→8248 reading "rests partly on a
Wikipedia tie-break" was also false — both committed captures are
no-article stubs — so the hand-validated row for 8284 (REF-058) is a
relevance flag, not a transposition hypothesis.

**Two structural consequences.** `FR_API_DENSE_MAX` is evidence — the
largest number the FR-API capture assigns, re-verified at load — not a
restatement of `citation_grammar.EO_HIGHEST_KNOWN`; the oracle refuses
`absent` above its own measured bound rather than inheriting authority
from a constant that moves when a President signs. And removing a
derived-CSV intersection that made "zero drift" circular immediately
exposed a parser defect it had been hiding: EO 12826 had been silently
dropped because EO 12825's Federal Register line is malformed in NARA's own
HTML, and the resulting gap had been published as a finding about the
publisher. The gap run is 223 of 223, contiguous.

### REF-058: Hand-validated interpretations — human judgment on the same receipt discipline as everything else

- **Date:** 2026-08-31
- **Status:** Accepted. Answers the owner's question of 2026-08-31 ("is
  there a space for hand-validated interpretations?") with a small
  consulted-never-applied table, founded on the pilot attestation of the
  same day.

`src/refspec/registry/hand_validated_interpretations.py` holds rows a
reviewer can *correct*, *flag*, or explicitly *decline to interpret* by
reading raw bytes — the case REF-052 does not cover. REF-052 licenses a
reading by which column a value arrived in; this table licenses one by
which witnesses a reviewer actually opened, typed by disposition: a
correction needs at least two independent witnesses (distinct resolved
paths) and an `interpreted_value`; a flag or refusal needs one and may
never carry a replacement. Witnesses must be committed files — membership
and byte-exact spelling from `git ls-files`, working bytes matching `HEAD`,
resolved containment inside the work tree, no symlink escapes — and each
witness's `shows` text carries a literal anchor asserted present in its own
bytes. `lookup(value)` returns the frozen `Interpretation` with its full
provenance or raises `NotReviewed`; no public function returns a bare
string, and the table refuses to load on a duplicate `source_value`, a
short-witnessed correction, or any row whose shape is wrong. Its consumers
consult it: `eo_roster.flag_for()` surfaces the EO 8284 row beside its own
verdict and refuses to hand back anything but a flag.

**Founding rows.** Row 1 is the pilot attestation's `E5-2394Filed`
correction — GPO's own granule identifier is the fused token, the printed
page welded it (600 dpi against a spaced control colophon on the same
page), seven witnesses, summaries re-derived from their bytes (the PDF's
en dash is quoted as an en dash). Row 2 is the EO 8284 flag: the order is
real (REF-057), so what is doubted is the citation's relevance, per the
committed adjudication, and the row's notes say plainly that its founding
transposition argument collapsed.

**Deployment scope, adjudicated.** Repo tooling: the root is derived once,
must carry the evidence home and be a git work-tree top level, and fails
in one sentence otherwise. The escape hatch for a future wheel is to ship
the witnessed bytes and pin them by digest the way `eo_roster` pins its
roster — not to loosen the check. `rkaf:Attestation` alignment was
considered and deferred: that shape is a RuleSpec-owned governance warrant
referenced by IRI, and this row's value lives in the parts an IRI reference
discards; if a release graph ever needs to cite a row, mint an IRI per row
and let the row be what it dereferences to. Until a consumer needs that,
it is structure without a running check.

### REF-059: OLRC's bracketed stubs are excluded from attestation on purpose

- **Date:** 2026-08-31
- **Status:** Accepted, with a named follow-up. Adjudicated during the
  review of the generation-2 oracle re-cut (the case-insensitive extractor
  recount, mined backlog silent item 2).

The annual-archive extractor accepts only itempaths beginning `Sec.` /
`Secs.`; OLRC also prints bracket-prefixed forms — `[§322. Repealed. Pub.
L. 109–313 …]`, `[§11704. Renumbered §11703]`, `[§§1 to 5. Repealed …]`
under `TITLE 6-SURETY BONDS [REPEALED]` — and the extractor's own docstring
claimed those blocks were retained. They are not, in either generation,
and this ruling keeps it that way deliberately. The discriminator is
OLRC's, not typographic: across all 31 archives, **35,088 of 35,088
non-appendix bracketed entries carry a zeroed usckey section field**,
against 1,585,628 unbracketed entries that carry a real one — zero
exceptions. A bracketed stub asserts a section that existed and has been
repealed, omitted or renumbered, printed as a placeholder; it does not
assert an identity at that edition.

**Why inclusion fails on its own evidence.** Admitting the 33,895
bracketed rows would move 3,085 attestations and flip 19 verdicts
`absent → exists` — and all 19 are one pair, 6 U.S.C. 1, whose only
witness anywhere is the 1972 repeal stub of the abolished Surety Bonds
title (printed 1994–2001), while the citing rows are 2005–2017 and one
names its own statute: the Homeland Security Act, classified from 6 U.S.C.
101. Calling those `exists` manufactures precisely the silent misread the
module fences, and deletes the correct hedge they carry today (`absent`,
caveat `repealed_before_1994_not_stubbed`). A bracket means the same thing
in `[Sec. 322` and `[Secs. 1 to 5`; splitting on which half happens to
produce a wrong verdict would be choosing on convenience.

**Cost named.** 40 U.S.C. 322 @2012 reads unattested though the volume
prints a stub (the section itself already reads `exists` from the release
point and the unbracketed 1994–2005 volumes); 3,085 rows are held at
`attested_at_edition = false` build-wide. **Follow-up:** a third state for
"printed as a withdrawn placeholder" — not a widened
`attested_at_edition`, which is what produces the 19. The exclusion is
pinned by a test against the raw bytes
(`test_a_bracketed_stub_is_printed_but_does_not_attest`), and the
extractor's docstring now says both forms and both consequences.

### REF-060: GAO's browse page is a list, not the vocabulary boundary

- **Date:** 2026-09-01
- **Status:** Accepted. Supersedes only REF-034's claim that GAO's 30-row
  `/topics` browse page is the complete GAO topic vocabulary.

The 30-row adapter existed for a good reason. REF-032 had deleted a topic
inventory inferred from one product page under RefSpec-minted identity; the
browse page replaced it with publisher-owned slugs, numeric Drupal taxonomy
ids, names, descriptions, and a stable published list. That was not AI
momentum. It was the right refusal to turn a moving product population into a
reference vocabulary, and this decision keeps that refusal.

The completeness claim was still false. A SpicySearch fidelity pass found two
of 47 GAO products assigned to `/topics/science-and-technology`, while the
browse page continued to omit that slug. Product assignments exposed the gap
but did not authorize a concept. The missing authority now comes from GAO's
own topic page, captured byte-exact through the bounded raw transport on
2026-09-01. The capture command completed at `2026-09-01T23:33:02Z`
(whole-second precision); the earlier midnight value had no evidence and was
removed. The retained response is 148,620 bytes, SHA-256
`98391cad16eba43e48017782765088d8720116ba988e1591d85215804906d0cd`.
The page independently agrees on canonical URL
`https://www.gao.gov/topics/science-and-technology`, visible and Open Graph
name `Science and Technology`, Drupal path `taxonomy/term/276`, and article
identity `taxonomy-term-276` with class `vocabulary-topic`.

The `gao-topics` scheme therefore carries 31 concepts: the exact 30-row browse
capture plus that one exact topic-page supplement. Its scope moves from
`completeCapture` to `captureSubset`; **31 is measured coverage, not a new
claim that GAO has exactly 31 topics.** The scheme IRI stays stable, while the
construction key moves from `gao-published-topics-index-2026-08-15` to
`gao-published-topics-capture-subset-2026-09-01`: this is no longer only the
August index capture, so keeping the old dated name would hide a real behavior
change for the sake of downstream familiarity. The source-release and
Atlas-release digests also move because the inputs, members, and issued date
changed. The independent source-fidelity reader re-parses both inputs and
assigns the supplement's source digest only to the new resource.

For total captured bytes `B` and topics `T`, the registry path is
`O(B + T log T)` time and `O(B + T)` memory; the sort is only for deterministic
topic order. No product corpus is loaded. GAO **product-page** acquisition
belongs in SpicyDocs; this publisher topic page is RefSpec-owned vocabulary
evidence. The committed capture does not license SpicySearch to own a live GAO
crawler or either product to infer vocabulary membership from report rows.
### REF-061: B8 publishes only as a two-witness rule, in the builder

- **Date:** 2026-09-01
- **Status:** Accepted. Enlarges the 2026-08-23 B8 demotion (see the oracle
  module docstring) without reversing it.

The oracle's B8 reading ("NNN(x)" as lettered section NNNx) stays
candidate-only where it lives: one structural witness cannot tell the FTC
case apart from a filer citing a subsection the bare section never printed.
The builder now publishes the reading where THREE things align: the oracle
names B8 as the SOLE surviving candidate, no live counter-evidence exists
(the rule's own held CFR authority note naming the bare section present
refuses, always), and a second witness outside the oracle's inputs
corroborates — the same note naming the lettered identity present, or the
same RIN's own citation history carrying it as a parsed section. Measured at
rebuild #15: promoted 666 rows / refused 319 (note names bare) + 454
(witnessless), closing the LONE:B8 census hole (1,439 rows that previously
appeared in no census) with the dedicated `uscB8PromotionRows` key.

Two deliberate narrowings against the mined spec's 1,171, both recorded in
the evidence home (research/evidence/b8-enlargement-2026-09-01/): the
sole-survivor gate excludes 1,902 witness-corroborated multi-candidate rows
(917 note / 533 history / 452 both) — a candidate follow-up unit needing its
own review, since the one known-bad specimen lives there — and witness
corroboration is structural only, never a raw-text scan: the bounded scan
finds 0 recoverable rows among the 454 witnessless, and the mined survey's
2,061 "text-only" hits were its regex's missing hyphen boundary (both
conflict specimens: a range residue and a 615a-1 neighbour).

### REF-062: dotted numbers refuse everywhere, and Stat. pages are marked, then judged

- **Date:** 2026-09-01
- **Status:** Accepted. Extends the 2026-08-24 list-tail fence (#46 family).

Two grammar fences, one doctrine: a lexical fact is recorded where it is
seen, and existence is judged only where an oracle can be reached.

Reg-dot: the dotted-number refusal now guards every position that reads a
single section token as a complete citation (anchor, appendix, transposed
label, IRC self-name, title-form lists), not just the list tail — the
"anchored stays visibly partial" assumption was measured false (consumers
key on title/section without parse_status). 41 authority values / 175 rows
stop publishing truncated sections, 89 of them a false affirmative exists;
zero citations added anywhere (full 42,677-value replay). One measured
exception: 5 USC 552a directly abutting a CFR citation keeps the real
Privacy Act section (the only dot-into-CFR value in the corpus). Known
residual, named: wrong-title damage survives the fence by design (40 USC
"322" from a 49 U.S.C. list — a title-repair unit, not a dot fence).

Stat-page: a U.S.C. list member reached by scanning past a Statutes-at-Large
citation is a Bluebook pinpoint page as often as a genuine resumed list
(14 CFR 121 resumes a real 49 U.S.C. list the identical way), so the grammar
MARKS (`usc_section_after_statute`) and never decides — it is deliberately
oracle-free. The note reader gates marked citations on
`section_is_enumerated` (exact lists; `section_exists` admitted 7 of 9
fabricated pages on range-stub evidence): 266 fabricated citations refused
across 107 notes, ~111 genuine resumed citations kept, 0 added. A missing
oracle degrades fail-closed (withhold every marked citation) and LOUDLY on
drift; the builder passes its own oracle explicitly. The filer-box path
carries the same gate (4 marked citations / 40 rows, all fabricated pages).

### REF-063: the EO fence consults the roster, and a build cannot skip it

- **Date:** 2026-09-01
- **Status:** Accepted. Completes REF-057's second half (WIRING-SPEC.md).

`eo_in_known_series` keeps the cheap range check first — a five/six-digit
typo reads False whatever the oracle would say — and hands only in-range
numbers to the REF-057 window-split oracle: exists → True, absent → False,
unknown → an honest None that was silently True before. Measured at
rebuild #15: 378 numbers / 18,954 rows keep True, 10 numbers / 50 rows move
to the new `eoUnknownRows` receipt key, `eoOutOfSeriesRows` stays 7, zero
True→False flips. The roster directory joins the build refusal list and the
producer block (module hash + roster digest): a tree without it refuses to
build rather than writing a receipt whose `eoUnknownRows: 0` means "never
asked". The roster's two raw publisher captures became pinned manifest
inputs (`eo_roster.py` reads publisherBytes at the audit gate); the
hand-validated layer's gap is named as by-design (REF-058) rather than
dressed up.

**Corrected 2026-09-02.** The publisherBytes claim above was wrong and is
withdrawn. `eo_roster.py` is `blocked` with a named blocker again, because the
declaration claimed a runtime provenance this reader does not have: the two
raw captures are retained and digest-pinned in the evidence home, and the
module's own tests read them for content, but `EoRosterOracle.from_directory`
consumes the DERIVED roster, so no execution is ever tied to the publisher
digests. The real-data gate said so as soon as it was asked
(`current execution did not consume pinned real-data inputs`), which is the
same lesson twice in one day: the first regeneration of that gate was run
without `--require-real-data` and recorded `notEvaluated` with an empty failure
list over a summary that had honestly said `failed` with nine gaps. A gate
never asked is not a gate passed. What the capture constants do earn is the
manifest's `declaredUrls` — the acquisition URLs are stated in the module, so
they are recorded where a reader finds them — and a test now holds their
digests to the evidence manifest's own so the two copies cannot drift.

### REF-064: a legacy Federal Register identity carries its publication date

- **Date:** 2026-09-02
- **Status:** Accepted. Adds `rkaf:us-frdoc-legacy` (rulespec 0.2.0rc17) to
  the minting layer. Supersedes nothing: `rkaf:us-frdoc` is untouched and no
  previously minted identity changes.

394,128 of the 1,004,233 distinct Federal Register document numbers (39.2%)
take the pre-2010 bare-legacy form and had no space rulespec could spell, so
they took the partner hatch. rulespec's new space is DATE-QUALIFIED —
`urn:rkaf:us:frdoc-legacy:{NN-N..N}:{YYYY-MM-DD}` — and that is the whole
design rather than a convenience: `00-111` names two different documents, and
the corpus reported zero within-parquet collisions only because it had already
dropped one of them. A count taken inside a source that already de-duplicated
measures its own filter, not the world. So the publication date is part of the
identity, and this minter cannot reach the space without one: an undated
legacy number keeps the partner hatch rather than minting a half-qualified
identity.

Three deliberate refusals, each measured rather than assumed.

**The year prefix is never checked against the date.** A legacy number's
leading two digits usually restate its publication year, and fencing on the
disagreement is the obvious next thought — but 1,661 of the 395,498 values
(0.42%) genuinely disagree, systematic year-boundary spillover where a
December number is printed in January (`07-6308` on 2008-01-15). The sibling
letter families spill at larger scale (E8 puts 318 documents into 2009). The
prefix is a spelling; the date is the caller's fact; adjudicating between them
would silently refuse 1,661 real documents.

**A malformed date raises rather than downgrading.** Data gets a refusal
(`None`) throughout this module, but a caller that passes a non-date has
asserted a fact that is not one — falling back to the hatch would publish an
identity missing exactly the qualifier the caller believed it supplied, which
is the failure a date-qualified space exists to prevent. A `datetime` is
refused too rather than truncated. ISO's compact spelling (`20090819`) is
accepted and normalized, because a spelling variant of one fact must not
become a second identifier — the same doctrine as the padding rule.

**The column license still governs.** A date is not a license: a bare legacy
number arriving from prose is still refused, because unlabeled `94-12345` is
indistinguishable from a docket or a release number. Nothing about prose
detection changes.

Cost and scope. `mint_federal_register_document_iri` has no SERVING caller
anywhere on the platform — none in this repository, and SpicySearch's serving
wheel cannot import it by construction (its metadata-package boundary test
forbids the refspec distribution). It is not dead code, though: SpicySearch's
`experiments/identifier_census.py` calls it with `column_licensed=True` as
instrumentation, which is how the 39.2% figure was measured in the first
place. So this change makes legacy identity EXPRESSIBLE and closes no gap in
any served output; the gap closes at the consumer boundary, where a catalog
row carries `document_number` and `publication_date` together. That step is
SpicySearch's and is not taken here. The minting path
is `O(1)` per value.

rc17 is a PROVISIONAL PIN: it is built from an unmerged local branch
(`feat/us-frdoc-legacy-space` at `850c204`), its digest is the pin, and a moved
branch silently invalidates it — see `vendor/README.md`. The letter-opening
families (10,231 values, including the 4,400 self-dating X numbers) still have
no space and still take the hatch; that is a separate request.

### REF-065: the X family mints without a date, because it states its own

- **Date:** 2026-09-02
- **Status:** Accepted. Adds `rkaf:us-frdoc-x` (rulespec 0.2.0rc18) beside
  REF-064's legacy space. Nothing previously minted changes; the X family
  leaves `rkaf:partner-defined`.

4,400 Federal Register document numbers open with `X`. They are not a document
class — the prefix spans genres, carrying a 700-page FDA jurisdictional
determination (`X96-20828`, 61 FR 44619-45318), 637 and 638 pages of *United
States v. Microsoft* public comments, NAFTA proclamations, Semiannual
Regulatory Agenda parts, and 1,122-byte issue CONTENTS stubs alike. It reads as
an overflow/typographic prefix. So this space asserts that each was published,
not that any matters: **genre stays in `document_type`, where the corpus already
carries it**, and a scheme keyed on the prefix does not try to encode tier.

**The form is self-dating, read right-anchored.** `X{YY}-{seq}{MMDD}`: the last
four digits are the month and day and everything before them is the sequence.
Parsed that way it agrees with `publication_date` on 4,400 of 4,400 rows. That
is a stronger property than the legacy form has, and this minter makes it
load-bearing — a date is optional, and a date that CONTRADICTS the number
raises, because the number carries the answer and a disagreement is a
detectable defect rather than a spelling to choose between.

**The census that nearly shipped was filtered, and this is why the space is
`{5,7}`.** The family was first counted as 4,194 under a fixed-width
`X##-#####` shape. The live Federal Register shows 2009-12-07 carrying thirty X
documents — `X09-11207` through `X09-91207` AND `X09-101207` … `X09-301207` —
so the sequence is variable-width and the corpus holds **4,400**, not 4,194. A
five-digit tail can hold only a one-digit sequence, so the shape had been
capping its own count at nine per day across 110 dates and calling the result a
distribution. The 206 six-digit numbers it hid are real documents:
`X09-101207` is 74 FR 64213, the DHS Statement of Regulatory Priorities, on the
same day as `X09-11207` at 74 FR 64129. A space written `[0-9]{5}` would have
stranded all 206 on its first day.

**The prefix is part of the identity.** 2,382 of the 4,400 (54.1%) have a bare
twin in the corpus, and the pairs are different publications:
`X94-10503` is a 44,932-byte Semiannual Regulatory Agenda correction while
`94-10503` is the 14,678-byte GE CF6 airworthiness NPRM of the same day, read
from their own bodies. Stripping the prefix to normalize would merge two
documents into one identity.

**One boundary is deliberate, and closing it either way would be wrong.**
rulespec's space admits a seven-digit tail as capacity; this repository's
shape layer stops at six. Ruled 2026-09-02, with rulespec: the two layers have
OPPOSITE FAILURE COSTS, so they are bounded by different things on purpose. A
lexical space fails by refusing a real identifier a publisher issued — silent,
unrecoverable data loss — so it is bounded by capacity and never fitted to
observed data. A shape layer fails by FALSE POSITIVE — a wrong identity, worse
than a refusal because it propagates silently into joins — so it is bounded by
measurement, and `_FR_TWO_DIGIT_PREFIX` and `_FR_SIX_DIGIT_TAIL` serve every
letter family, so widening them on speculation would admit unseen shapes for
E, C, R and Z to buy a shape none has.

The consequence lands in the safe direction, which is what settles it: a
seven-digit X, if ever published, is spellable but not auto-detected — a
caller that knows what it holds mints it under the column license, and a
detector that does not know refuses and counts the refusal. A refusal that
appears in a census beats a wrong mint that does not. It is REF-052's
prose-reader/column-reader split, "the column is the license", applied one
layer up, and
`test_the_x_shape_layer_stops_where_the_corpus_does_and_the_space_does_not`
carries the reasoning so the next reader does not close the gap in whichever
direction they happen to be standing in.

### REF-067: a producer module refuses before a table is written, and a commit sha rides beside the digests it cannot replace

- **Date:** 2026-09-02
- **Status:** Accepted. Amends `_producer_block()` and
  `build_unified_agenda_parquet()` in
  `src/refspec/registry/unified_agenda_parquet.py`. No schema version moves:
  `contract.schemaVersion` names the artifact's table shape, and provenance is
  not table shape.

Two changes to the receipt's `producer` block, one a defect fix and one an
addition. Both were reworked on the same day after an adversarial audit
returned RECONSIDER; what the audit moved is recorded here rather than in a
second record, because the decision is one decision.

**The fail-open.** `_producer_block()`'s inner `digest()` returned `None` for
a producer module (one of `_PRODUCER_MODULES`, hashed from a `.py` file that
is supposed to live beside this one) whose file was absent, and the build
proceeded, writing a receipt with NULL provenance for the grammar that
produced the values -- indistinguishable from "there was nothing to record".
A producer module's absence is not a legitimate "nothing to hash" the way an
optional oracle's absence is (an oracle CSV genuinely may not exist in every
checkout, and several loaders already answer `None` for that, correctly, and
the build proceeds without it); a producer module missing from the package
that is running this build means the checkout is broken. `_producer_module_source()`
now refuses with the module's name when this happens, kept separate from the
oracle-facing `digest()` so the legitimate oracle-absence path is untouched.

**And it refuses before a byte moves.** The refusal above first ran only from
`_producer_block()`, which is called at RECEIPT time -- after all four Parquet
files are written. A build in a checkout missing a producer module therefore
overwrote the four tables and only then aborted, leaving new tables beside the
previous run's receipt: bytes on disk that no receipt describes, which is
worse than the null provenance the refusal replaced, because null is at least
visibly absent. `build_unified_agenda_parquet()` now proves every producer
module present on its first line, before `mkdir` and before one edition is
read; the receipt-time refusal stays as the belt to that build's braces, and
is the only guard when the block is asked for outside a build, which
`describe_producer_drift()` does on every `--verify`. The presence check is
`len(_PRODUCER_MODULES)` stat calls, free next to the read it precedes.

**The commit and clean flag.** `_producer_block()`'s dict gains two keys
beside `modules` and `oracles`: `commit` (the repository HEAD sha, or `None`)
and `workingTreeClean` (`True`/`False`, or `None`). The byte digests answer
"which code ran" and stay authoritative for that question -- the block's own
comment records the incident this repo built the digest approach to avoid:
twenty commits landed between two builds on 2026-08-22 and a consumer's
receipt matched none of them by commit. A commit sha answers a different,
narrower question, "what was checked out", and is a convenience beside the
digests, never a replacement: a wheel install carries no `.git` at all, and
correctly answers `None` for both keys rather than a stale or synthetic
commit.

**The pair is atomic.** Both keys are answered, or both are `None`. Every way
git fails to answer takes the same exit: no `git` on PATH (`OSError`), a hung
git (`subprocess.TimeoutExpired` -- which used to escape the helper entirely
and abort the build, since only `OSError` was caught), a non-zero exit from
ANY of the three git calls, no repository, or a repository that is not this
one. An earlier draft let a failed `git status` yield `(commit, None)`, a
half-answer that contradicted this record; the code now matches the record
rather than the record being widened, because a consumer that has to read two
independent conditions to learn one thing will eventually read only the first.

**The hazard, and why `git -C` is not a defence.** `git rev-parse HEAD`
answers for whatever repository git DISCOVERS, and git reads its own
environment before it reads the filesystem. `GIT_DIR` takes precedence over
`-C`: measured in this tree on 2026-09-02, with `GIT_DIR=<sibling>/.git` and
`GIT_WORK_TREE=<this repo>`, `git -C <this repo> rev-parse --show-toplevel
HEAD` printed THIS repository's root and the SIBLING's commit `2b1624ab`,
while this checkout was at `eb7e6458`. The first draft's guard compared only
the toplevel, so it validated the tree git was REPORTING ON and recorded a
commit that came from somewhere else -- exactly the stranger's-commit hazard
it was written to prevent, reached through a door it did not know about. A
build launched from a git hook, a `git rebase --exec`, or a CI runner that
exports these inherits precisely that environment. Three things close it, and
`-C` is none of them:

1. **The environment is scrubbed.** Every `GIT_*` variable is dropped before
   git runs -- `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_INDEX_FILE`,
   `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`,
   `GIT_CEILING_DIRECTORIES`, `GIT_DISCOVERY_ACROSS_FILESYSTEM` and every
   `GIT_CONFIG_*` redirect discovery or the config that governs it. Dropped as
   a class rather than enumerated, because an enumeration is what the next git
   release invalidates. The allowlist is one name, `GIT_EXEC_PATH`, which says
   where git's own subcommands live -- a relocated or wrapped install needs it
   to run at all -- and which cannot redirect which repository is discovered.
   `GIT_SSL*` is not kept: `rev-parse`, `ls-files` and `status` are local and
   never open a connection.
2. **The repository that answered HEAD must track this very file.**
   `git ls-files --error-unmatch` is asked of that same repository for this
   module's own source path. This is the belt to the scrub's braces: it
   catches the class without depending on knowing every variable worth
   stripping (under the hijack above it exits 1, measured, because the
   sibling's index has never heard of `src/refspec/registry/...`). It also
   closes the second half of the hazard, which no environment scrub reaches:
   `_REPO_ROOT` is derived structurally as `parents[3]` of this module's own
   file, so an install laid out as `<foreign>/site-packages/refspec/registry/...`
   -- what `pip install --target` produces -- puts `_REPO_ROOT` at `<foreign>`,
   and if `<foreign>` is somebody's checkout its toplevel IS `_REPO_ROOT`. The
   installed copy is not in that repository's index, so the commit is refused.
3. **The toplevel must still be `_REPO_ROOT`** (`Path.samefile`, a
   device+inode check): this module's own belief, computed once from its own
   path on disk, about which checkout it lives under.

`git rev-parse --absolute-git-dir` was considered for role 2 and rejected on
measurement, which is worth recording because it is the obvious next idea: a
legitimate LINKED WORKTREE's git directory lives inside the MAIN checkout
(`<main>/.git/worktrees/<name>`, measured), outside the worktree root
entirely, so a path-containment rule would refuse the worktree builds this
repository actually uses. The tracked-file question admits the worktree and
still refuses the hijack, and
`test_a_linked_worktree_still_answers_with_its_own_commit` is what breaks if
someone tightens it back into containment.

**Git is sampled twice, around the hashing.** Git's answer and the digests are
two reads of a worktree that can move between them: a checkout landing
mid-block would file commit A's sha beside commit B's digests, one receipt
describing two states. The block asks git the same question before and after
hashing and records the pair only when both answers agree, dropping it
otherwise -- the digests are authoritative either way, so the pair that cannot
be trusted as one snapshot is not guessed at. Six git invocations per build
(102ms measured for the whole block, 51ms of it one sample) are irrelevant
beside reading every pinned edition.

**What `workingTreeClean` covers, exactly.** It is `git status --porcelain`
over the WHOLE worktree, not over the hashed files: staged changes, unstaged
changes, and untracked paths git does not ignore, in any directory. So an
unrelated untracked scratch file reads DIRTY although every hashed byte is
committed, and -- the direction that matters -- a changed oracle under an
IGNORED path reads CLEAN, because `--porcelain` excludes ignored paths and
several hashed oracles live under the gitignored `output/`. An earlier draft
of this record said a clean tree means the hashed digests "will survive until
the next commit". That was an overclaim and is withdrawn: clean means "git saw
nothing modified or newly untracked outside its own ignore rules", the
conventional reading of the word, and is worth exactly that much. Only the
digests beside it say what was hashed.

**What this cannot see.** `_producer_module_source()`'s refusal covers absence
only: a producer module file that exists but is truncated or corrupted still
hashes and still lands in the receipt, for `describe_producer_drift` to catch
downstream against a prior receipt, not for this refusal to catch up front.
The pre-write check proves ORDER, not that a completed build's tables and
receipt are written atomically -- a crash between the last Parquet write and
the receipt leaves the same inconsistency from a cause it is not looking for.
The toplevel guard is a path-identity check, not a content check: a toplevel
that coincidentally IS `_REPO_ROOT` on disk but holds a different git history
underneath (a bind mount, a symlink farm reusing the path) would pass it, and
a FORK of this repository substituted wholesale would satisfy both the
toplevel and the tracked-file questions, since it tracks the same paths --
only the scrub closes that, and only for redirections travelling through the
environment. Nothing here survives a replaced `git` binary, and every check is
downstream of trusting git's own exit status. The double sample narrows the
sampling window rather than abolishing it: a worktree that moves to B and back
to A around the hashing is invisible, and the digests are themselves read one
file at a time, so they are not one atomic snapshot either. And
`describe_producer_drift()` was deliberately left unchanged -- it still walks
only `modules` and `oracles`, because a commit sha moving while every digest
holds is not the drift that function answers for; the digests already say
whether the code changed.

**The file-wide test skip that hid all of this.** The tests above are unit
tests of the refusal and the guard; none of them reads the built artifact. The
module's `pytestmark` skipped every test in it when the gitignored artifact
was absent, so on a fresh checkout all of this coverage skipped silently:
measured, 150 skipped and 0 run. That gate is now a per-test autouse fixture
with a `no_artifact` marker to opt out, and the same fresh checkout runs 8 and
skips 142.

One test goes red until the next rebuild and stays red on this branch for two
compounding reasons: `test_the_receipt_names_the_code_that_wrote_it` in
`tests/test_unified_agenda_parquet.py` compares a fresh `_producer_block()`
against the on-disk receipt for byte-for-byte equality, and (1) editing
`unified_agenda_parquet.py` to add this feature necessarily moves that
module's own digest, and (2) the on-disk receipt predates the `commit` and
`workingTreeClean` keys entirely. Left red on purpose, not weakened, per this
repository's rule that a replaced check keeps proving itself rather than
having its assertion loosened to match the code.

**Amended 2026-09-03: both causes above have since cleared, a third was
found, and the assertion is now a stronger check rather than a looser one.**
The rebuild landed, so the receipt carries `commit` and `workingTreeClean`
and its digests match this module. What remained red is a cause this record
did not name: the full-block equality includes `commit`, so it goes red at
any LATER commit and on any dirt at all -- one untracked scratch file is
enough -- neither of which is evidence about the artifact. On 2026-09-03 an
`identifier_shapes` change and an unrelated `evidence(...)` commit produced
the identical red, and only one of them was ever going to clear; the real
drift signal was buried under a failure everyone had learned to expect.

One mechanism stated in the first draft of that fix was wrong and is
corrected here: the red is **not** caused by "committing the artifact", which
never happens, because `output/` is gitignored. A blind review also refuted
the framing that the equality was unsatisfiable -- it verified that the
recorded commit resolves and all nine recorded module digests equal the blobs
at it, so the equality was genuinely green at that one commit on a clean
tree. The window is narrow, not absent.

The replacement keeps this record's rule rather than bending it. Digest drift
against this checkout stays a strict equality, and the recorded block's key
set is now asserted too, so an extra key cannot pass. The `commit` equality is
replaced by a **value** check: each recorded module digest must equal the
sha256 of that module's blob AT the recorded commit, guarded on
`workingTreeClean is True`.

**Two blind reviews, and each refuted the revision before it.** The first
refuted the premise -- the equality was satisfiable, green at the recorded
commit on a clean tree -- and rejected an intermediate revision that asserted
only 40 lowercase hex, which admitted git's null object id. The second found
that the value check ALONE was weaker still on one input class, because
`git show <rev>:<path>` accepts far more than a commit sha:

- the **empty string** is git's spelling for the INDEX, and since the
  preceding assertion already forces recorded == worktree, on a clean tree
  every iteration then compares the worktree to itself -- an assertion that
  cannot fail for any input, reachable because `""` is what a JSON writer
  emits for an unset string field;
- `HEAD`, `HEAD~1` and branch names resolve and move with the repository;
- a root **tree** sha resolves AND is 40 lowercase hex, so the shape check
  would have admitted it too.

The final form therefore asserts all three together -- 40-hex shape,
`cat-file -t` proving a **commit** object, and the digest value at that commit.
Recording this because the sequence is the lesson: one round of review changed
the design and a second round found the design's own hole, and the count of
rounds was what separated a stronger check from a weaker one.

Two limits are stated in the test rather than papered over. `(None, None)` for
commit and clean flag is ACCEPTED, because `_producer_block()` emits it on
purpose where git cannot be asked and a sibling test pins it as correct -- an
earlier revision failed it on `isinstance`, putting two tests in one file in
contradiction. And the check covers `modules` only: the six `oracles` are not
verified against the commit, and `public-law-roster.csv` lives under gitignored
`output/`, so an artifact built from a mutated roster still passes.

A third blind review, briefed to the NEW guards only, with the mutation
battery withheld and the defect class named without its sites, found five more
and is the reason the brief matters more than the round count. Two were
bypasses: both git reads inherited the ambient environment, so
`GIT_ALTERNATE_OBJECT_DIRECTORIES` pointed at a sibling repository let a
foreign-only commit pass a check whose whole claim is that it cannot -- the
test had re-opened the hazard `_repository_commit_and_cleanliness()` closes
and documents; and `git replace -f <tree> <commit>` made `cat-file -t` report
`commit` for a tree while every read returned substituted bytes, defeating the
type guard and the digest guard together. Three were false REJECTIONS, all of
them the class above, in code written specifically to stop producing it: a
`--object-format=sha256` repository emits a 64-char commit the 40-hex rule
refused; `core.autocrlf` makes the filesystem bytes `_producer_block()` hashes
differ from the canonical blob, so a clean tree with an accurate receipt
failed; and a tracked symlink stores link text as its blob while the producer
follows it and hashes the target, so the two legitimately disagree.

Closing the first of those extracted `_scrubbed_git_environment()` rather than
copying the rule into the test, because a security invariant with two
spellings is this package's own named recurring failure. **The test therefore
depends on a private helper deliberately: `_scrubbed_git_environment` is not
unused, and renaming it silently re-opens the bypass.** The remaining reads
run `git --no-replace-objects` through one `git_read` prefix so a later call
cannot forget it, and use `cat-file --filters` so the comparison is against
the bytes the producer actually hashes.

The clean-flag guard is a real weakening and is named as one. A build
reporting itself dirty is saying its bytes need not match any commit, so
verifying them would be wrong -- but nothing outside this test reads
`workingTreeClean`, so the flag buys silence at no announced cost, and dirty
is the normal state because one untracked file sets it. Closing that needs a
consumer of the flag, which does not exist yet.

### REF-066: a modern Federal Register document number can name two documents, and five of them do

- **Date:** 2026-09-02
- **Status:** Accepted, amended the same day after an adversarial audit.
  `mint_federal_register_document_iri` refuses five specific modern-form
  document numbers and mints the other two exactly as before;
  `rkaf:us-frdoc`'s space is untouched. Every OTHER document number's mint
  is untouched too -- a claim that was FALSE outside a source checkout in
  the first cut of this decision, and is now proved in one: see "What the
  audit changed" below.

`mint_federal_register_document_iri` has minted `rkaf:us-frdoc` from the
document number alone since REF-052, because rulespec's modern space carries
no date qualifier. A 2026-09-02 full crawl of the published Federal Register
(1,007,156 distinct numbers, brought home as
`research/evidence/fr-collision-census-2026-09-02/fr-full-collision-census.json`,
pinned by sha256) found **seven** modern-form numbers that each carry two
different publication dates -- something that premise does not survive
unexamined.

**Reading the documents, not the metadata, is what this decision rests on.**
The federalregister.gov API's own `correction_of` field -- built for exactly
the question "is this a correction of an earlier document" -- answers `null`
for all fourteen dated appearances of all seven, including the two that
genuinely are self-corrections. Fetched 2026-09-02 and preserved as bytes,
not as a paste, in that evidence home's `api/` (see "The API's own answer is
preserved" below). So the adjudication below reads the
fourteen dated full-text captures themselves
(`research/evidence/fr-collision-census-2026-09-02/specimens/`), not a
shortcut through metadata that turns out not to carry the answer.

**Five are genuinely different documents (`refusal-to-interpret`).** Four
share nothing but the accident of the publisher's own numbering: an EPA
pesticide notice and an unrelated DOT/FAA airport-safety NPRM eleven months
apart under `2010-31094`; Commerce/NTIA and DOT/FAA under `2010-31384`; EPA
and DOT/Maritime Administration under `2010-31396`; the Postal Regulatory
Commission and DOE/FERC under `2010-31415`. The fifth, `2010-517`, is the one
that took a title-and-agency read to separate from the other two: its second
appearance is captioned "Correction", the identical surface word the two
`consulted` rows below carry, and only reading WHICH document it corrects
(`E8-11863`, a Coast Guard rule -- not `2010-517` itself, a DOE/FERC gas-
pipeline notice from an unrelated department) tells the two patterns apart.
Minting one `rkaf:us-frdoc` identifier for any of these five pairs would
silently merge two unrelated regulatory actions into one identity.

**Two are one matter published twice (`consulted`).** `2015-17759` (an SEC
filing notice, corrected in place: "In notice document 2015-17759 ... make
the following correction") and `2015-25354` (a Department of Education
notice, corrected the same way) are each explicitly, textually a correction
*of their own document number*, same agency, same docket. A single
identifier for both is the CORRECT reading here, not a tolerance: it is what
a reader following either published copy would expect the number to resolve
to. These are recorded rather than left silent so the record shows they were
examined and deliberately left to mint, not overlooked -- the "consulted"
disposition, new to `hand_validated_interpretations.py` for exactly this
shape of finding (examined, and correctly NOT corrected or refused).

**Where the check lives, and why it cannot poison every other mint.** All
seven rows live in `hand_validated_interpretations._FR_COLLISION_TABLE`, a
table deliberately separate from the module's founding `_TABLE`
(E5-2394, EO 8284): `load_interpretations()` validates `_TABLE` as one
atomic unit, which is right for a couple of rarely-changing, consulted-by-
name rows and wrong for a population consulted on nearly every Federal
Register document number minted anywhere on the platform. Coupling an
ORDINARY document number's mint to the witness health of an unrelated
Executive Order flag would make one broken witness anywhere refuse every
mint everywhere. `is_a_refused_federal_register_collision(value)` checks
membership FIRST against the seven rows themselves -- one dict lookup over
Python literals that ship inside the package, no census file, no git,
`O(1)` for the overwhelming majority of values that are not one of the
seven -- and only for one of the seven does it re-read the pinned census
and witness that single row. `mint_federal_register_document_iri` calls it
before any other branch, including the `rkaf:partner-defined` escape hatch:
minting anything for a genuine collision, even losslessly, would still be
one identifier standing for two documents.

**The isolation that buys, stated as two different cases.** A witness FILE
going wrong -- deleted, edited away from HEAD, never committed, symlinked
out of the tree -- is isolated: it refuses the one row that cites it, and
an ordinary mint, EO 8284's flag and the other six collisions carry on
(verified by the audit, which broke one collision's witness and watched the
rest keep answering). A row SHAPE going wrong is NOT isolated: all seven
`Interpretation` objects are constructed eagerly at import, so `witnesses=()`
or a `consulted` row carrying an `interpreted_value` fails the module
import and takes every consumer down at once. That is deliberate and the
two are not the same fact: evidence can be momentarily unavailable in a
deployment, but a row's shape is a defect in the module's own source and
should stop everything loudly at import rather than lurk until the one
value it describes is asked about.

**What the audit changed.** An adversarial audit of the first cut simulated
an installed-wheel layout and found `mint_federal_register_document_iri("2024-00366")`
-- an ordinary, non-colliding number -- raising `HandValidatedRegistryError`,
because the predicate read the census receipt out of `research/evidence/`
before doing anything else and `_default_repository_root()` rejects a
`site-packages` layout. A pure minting function had become dependent on a
git checkout: runtime behaviour bound to a REPRESENTATION rather than to the
fact it encodes. The fix separates them by what they are. The VERDICTS
(seven `source_value` strings and their dispositions) are behavioural, tiny
and already Python literals, so they travel in the wheel and answer
anywhere. The CENSUS RECEIPT and the fourteen WITNESS files are audit data:
they exist only in a checkout, they are still checked there exactly as
before -- `_the_census_agrees_with_this_table` holds the rows true against
the receipt in both directions, `_witnessed` holds each row to its own
committed bytes -- and neither is now reachable by a value that is not one
of the seven. `_repository_root_if_present` is the whole of the split: one
`is_dir()` on the evidence anchor, no subprocess, answering `None` where
`_default_repository_root` raises. Performed proof, 2026-09-02: the package
copied into a `site-packages`-shaped directory outside any git work tree
and imported from there, with git on `PATH` and again with `PATH` emptied
-- `2024-00366`, `2010-31095`, `2015-17758` and `E8-24348` all mint, all
five collisions refuse (hatch included), both `consulted` numbers mint and
`lookup` returns their rows, while the founding `_TABLE` still refuses with
its deployment sentence, which is correct: that table is repository
tooling and says so.

The audit also found `lookup()` unable to return the new `consulted` rows
at all -- it read only `_TABLE`, so `lookup("2015-17759")` raised
`NotReviewed`, which is documented to mean "nobody examined this value" and
was the exact opposite of what two witnesses say about it. `lookup` now
reads REF-066's table first (package data, no git) and `_TABLE` second; the
two are proven disjoint, so the order changes nothing but cost. And the
collision witness check was not mutation-killed: deleting the single
`_witnessed` call left every scoped test green, because the others read
dispositions, witness counts or anchors and never make a witness fail.
`test_a_collision_row_with_a_dangling_witness_refuses_through_the_predicate`
now exercises it through the public predicate; the deletion was performed
and it is the one test that dies.

**What this cannot see.** The census describes the crawled Federal Register
from 1994 onward (its own `coverage.caveat`) and nothing about the printed
Register before that; a collision the crawl did not observe would still mint
as first-class today, and an eighth collision a future re-crawl finds ships
as a new dated evidence home, a new pin AND the rows that adjudicate it, in
one change -- never a silent edit to this one's rows.
`_verify_pinned_collision_census` refuses to load on any drift of the census
bytes, the same discipline `eo_roster._verify_pinned_roster` holds its own
roster to. Two limits follow from the split above and are worth naming.
First, the receipt-versus-rows drift check only runs where the receipt
exists: in an installed layout there is nothing to disagree with the rows,
so a re-crawl's eighth collision mints as first-class there until the new
census and its rows ship together; in a checkout it raises on the first ask
about any of the seven, and the test suite compares the two sets directly
whether or not a member is ever asked about. Second, the census counted
membership by its own `modernPattern` `^\d{4}-\d+$`, which is broader than
rulespec's `[0-9]{4}-[0-9]{3,5}` at both ends; all seven have three- or
five-digit tails and satisfy both, but a future short- or long-tailed
collision would be refused by a different space than the one these seven
live in, and the row adjudicating it has to say so (the evidence home's
README carries this in full).

**The API's own answer is preserved, not paraphrased.** The `correction_of`
claim above is the strongest single fact here, so it replays from committed
bytes: `research/evidence/fr-collision-census-2026-09-02/api/seven-numbers.correction_of.json`
is the multi-document endpoint's answer for all fourteen dated appearances
of the seven numbers (`"count":14`, every record `"correction_of":null` and
`"corrections":[]`), with its response headers beside it, plus the narrow
single-document request this record quotes. The same file corroborates the
5/2 split from metadata independently of the document bodies: each REFUSE
pair carries two different `title`s under two different `agency_names`,
while each `consulted` pair carries the identical title under the identical
agency on both dates.

Measured cost: `test_the_document_number_column_is_accounted_for_exactly`'s
pinned-column census moves exactly five values from `first-class` to
`refused` (480,566 → 480,561; 360 → 365 of 1,004,233) and zero values
anywhere else -- the two `consulted` numbers were already counted
first-class and stay there.
