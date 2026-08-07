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

- **Date:** 2026-08-06
- **Status:** Accepted direction; canonical cutover requires parity acceptance

Atlas will borrow two publication patterns without adopting either system's
data model. [ESCO publishes one managed classification through RDF, tabular
downloads, and APIs](https://esco.ec.europa.eu/en/use-esco). [Wikibase exposes
both full statement RDF and a simpler direct or "truthy"
form](https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format). Atlas
will apply that separation to versioned United States public reference sources:
one governed record set, several reproducible consumer views.

The current [Atlas 3.0 RDF binding](../bindings/atlas/3.0/README.md) remains
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
