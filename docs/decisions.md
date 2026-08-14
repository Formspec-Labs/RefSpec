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
