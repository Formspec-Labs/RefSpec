<!-- markdownlint-disable MD013 -->

# Vocabulary Atlas Final Synthesis — governed expansion from source evidence to search

> **Status:** Final synthesis for decision; not adopted
>
> **Date:** 2026-08-03
>
> **Resolves:** [Vocabulary Atlas Design Proposal](vocabulary-atlas-design-proposal-2026-08-03.md) ·
> [Proposal Addendum](vocabulary-atlas-design-proposal-addendum-2026-08-03.md)
>
> **Normative authority:** [RefSpec](../spec/refspec.md), the pinned
> [Rulespec Core dependency](../profiles/rulespec-core-dependency.json), and the
> [Atlas 1.0 binding](../bindings/atlas/1.0/README.md) remain authoritative.
> This synthesis directs later specification and implementation work; it does
> not amend those artifacts or activate a product feature.

## 1. Decision

Keep the Vocabulary Atlas as a static, reproducible publication of exact
vocabulary release facts and qualified mapping evidence. Expand it through
three separate controls:

1. A portfolio index records where each source belongs and how ready it is.
2. The atlas publishes exact managed releases, bounded frontier releases, and
   mapping evidence. Smaller projections serve consumers.
3. RefSpec `OutputProfile` rows govern enrichment use, while SpicySearch's
   retrieval policy governs query expansion. Portfolio classes authorize
   neither.

The earlier Ring 0–3 names remain useful planning labels: core, specialist,
bridge, and outside-atlas. They move to the portfolio index, where they are
keyed by exact use. They do not enter the atlas manifest and do not create a
second permission system.

Mapping evidence profiles remain useful, but they do not replace Rulespec's
construction origin, epistemic basis, attestation, adoption, or lifecycle
records. A profile summarizes those facts; the underlying Rulespec records
remain authoritative.

This design preserves the proposal's strongest ideas: separate resource kinds,
map wide and emit narrow, bounded large-vocabulary subsets, hub-based candidate
discovery, immutable canonical files, and measured product adoption.

## 2. Verified baseline

At RefSpec revision `13b9c92`, the current three-release artifact is
`urn:ref:vocabulary-atlas:57a69e9a68a5877cb8b4e2b225153e2674b56af128a1ab9877f1787e57fb3042`.
Its [manifest](../output/atlas-fr-elsst-icpsr-2026-08-03/atlas-manifest.json)
and N-Quads record:

| Measure | Verified value |
| --- | ---: |
| Managed releases | 3 — Federal Register 2025, ELSST R6, and ICPSR |
| N-Quads | 233,999 |
| Release facts | 177,359 |
| Analysis facts | 56,640 |
| Qualified `searchOnly` mappings | 240 — 121 FR↔ELSST and 119 FR↔ICPSR |
| Mapping candidates | 730 |
| Machine validations | 1,459 |
| Hierarchy edges | 5,152 |

These numbers identify one local artifact, not a moving “current atlas.” Future
reports must name the atlas identifier and both file digests before quoting
counts. They supersede the unpinned opening counts in the draft proposal.

Atlas 1.0 already supports multiple crosswalk bundles, deterministic
reproduction, bounded hierarchy, SSSOM export, a static explorer, and a
separate projection kind. The latest explorer code also shows lifecycle
successions, source definitions and notes, and rejected mapping candidates.
That makes evidence and refusals inspectable; it does not change mapping
eligibility. RefSpec's projection tests already reject an unrelated parent and
a resealed projection that drops a retained fact. The portable Atlas
conformance corpus does not yet publish projection cases.

SpicySearch at revision `f8bfbe8` opens hierarchy-bearing atlases but still
pins an older Federal Register-only input. It does not open the projection
kind, and production cross-vocabulary expansion remains disabled. Nothing in
this synthesis claims deployment, release, or activation.

## 3. What enters, what happens, what leaves, and how we check it

**Inputs.** The build takes immutable managed releases, a pinned Rulespec Core
release, zero or more sealed crosswalk bundles, and named build policies. The
portfolio index informs input selection and the build report, but it does not
authorize use. A frontier build also takes a pinned source distribution and a
frontier-selection receipt.

**Processing.** RefSpec verifies release membership and provenance, constructs
the two atlas graphs, checks mapping evidence, derives all counts, and writes
canonical bytes. It then cuts consumer projections from the completed atlas.

**Outputs.** RefSpec publishes one canonical atlas per named build scope,
smaller projections, SSSOM rows plus RefSpec evidence metadata, and a portfolio
index. Entity, code, legal-identity, and source-assignment publications remain
separate.

**Checks.** Producers and consumers verify exact digests, release membership,
mapping endpoints, permission rows, evidence lineage, projection parentage,
and declared counts. Product adoption adds task-specific holdouts and an exact
configuration and evaluation record.

## 4. Invariants

The following rules govern every later design and implementation:

1. **Preserve source identity.** An atlas member keeps its publisher or
   authorized local concept identity. A capture-local observation never
   becomes a concept silently.
2. **Separate authority.** `releaseFacts` contains only verified managed-release
   facts. `analysis` contains replaceable discovery and mapping evidence.
3. **Require complete mapping endpoints.** Every mapping endpoint resolves to
   an exact `rkaf:ReferenceResourceRelease` with complete membership that lists
   the concept.
4. **Keep one permission source per product action.** RefSpec `OutputProfile`
   rows authorize enrichment candidate and accepted-output use. SpicySearch's
   pinned retrieval policy authorizes query expansion. A ring, reader flag, or
   atlas manifest field cannot substitute for either decision.
5. **Keep construction separate from review.** Rulespec origin records who or
   what constructed an assertion. Attestation, adoption, and lifecycle records
   record later decisions without rewriting that origin.
6. **Keep canonical files authoritative.** The manifest and N-Quads are the
   durable atlas. Graph databases, Parquet tables, lexical indexes, embeddings,
   and visualizations are rebuildable read models.
7. **Compose downstream without mutation.** SpicySearch and other products may
   combine atlas subjects with document evidence, entities, legal identity, and
   codes in derived outputs. They do not mutate the RefSpec atlas.

## 5. Portfolio index and atlas participation

The portfolio catalog keeps its existing availability and consumability
fields. The atlas index extends it with two independent fields:

| Field | Purpose | Authorizing? |
| --- | --- | --- |
| `publicationTarget` | `atlas`, `entitySpine`, `codeLedger`, `legalIdentityGraph`, or `sourceAssignedEvidence` | No |
| `atlasParticipation` | `core`, `specialist`, `bridge`, or absent | No |

An atlas-participation row identifies the exact `resourceId`, release when one
exists, facet, assignment role, intended use, and readiness evidence. A source
may have several rows when its facets or roles differ. A pre-release row may
state a planned class, but it cannot enter an atlas build until it names a
conforming release.

Shared models, transports, acquisition helpers, policies, and development
artifacts receive no source-participation row. They appear only as
implementation provenance when a build uses them.

The former ring labels map to these planning classes:

| Former ring | Planning class | Meaning |
| --- | --- | --- |
| Ring 0 | `core` | Default subject candidate pool for a named product configuration |
| Ring 1 | `specialist` | Evidence-activated subject candidate pool that must pass its own adoption gate |
| Ring 2 | `bridge` | Query expansion, mapping discovery, and off-domain decoys; never accepted as a subject merely because it is present |
| Ring 3 | absent | Published through another target or retained as source-assigned evidence |

The atlas manifest continues to identify its exact release and crosswalk
inputs. It does not repeat planning classes. A build report may compare the
portfolio index with the selected inputs and report drift, but runtime
authorization continues to use the exact product policy.

## 6. Current placement decisions

| Source | Placement now | Decision |
| --- | --- | --- |
| Federal Register Thesaurus 2025 | `atlas` / `core` | Keep the existing complete managed release. Exact product use still requires a matching `OutputProfile` row. |
| ELSST R6 | `atlas` / `bridge` | Keep the current release and 121 qualified mappings. Measure query expansion before deepening the bridge. |
| ICPSR | `atlas` / `bridge`, development-only | Keep the release marker and 119 qualified mappings. Do not treat the separate operator-adopted bridge as machine-qualified. |
| CRS Legislative Subject Terms | `sourceAssignedEvidence` | Keep the exact publisher labels as evidence. Congress.gov supplies no stable term identity or named vocabulary release, so these values do not enter the core yet. |
| CRS Policy Areas | `sourceAssignedEvidence` / navigation | Keep as broad navigation and publisher evidence, not subject concepts. |
| LCSH topical | planned `atlas` / `bridge` | Admit only a frontier release built by the two-pass process in §8. The current source-observation package is not that release. |
| FAST topical | planned `atlas` / `bridge` | Require an exact RDF acquisition and the predicate-conversion rule in §10 before promotion. |
| MeSH descriptors, NALT Core, GEMET, NASA Thesaurus | planned `atlas` / `specialist` | Pilot separately after source, license, freshness, identity, and holdout gates pass. |
| EuroVoc, AGROVOC, DOE OSTI, EPA EV, and other mapping references | planned `atlas` / `bridge` or deferred | Promote only exact releases that pass their documented gates. |
| Codes, identifier authorities, entities, native controls, and legal identifiers | non-atlas targets | Publish through the entity spine, code ledgers, legal identity graph, or source-evidence packages. |

The core is versioned, not eventually “complete.” Adding an authorized local
concept release creates a new core version and may require delta
requalification. Existing bridge evaluation need not wait for a hypothetical
final core.

## 7. Authorization

For enrichment, one complete `OutputProfile.releasePermissions` row controls
candidate use of an exact release. One complete
`OutputProfile.mappingPermissions` row controls traversal of an exact mapping
snapshot, direction, relation, facet, and role. Candidate permission does not
authorize accepted output, and permission rows cannot be assembled from parts
of different rows. These rules already exist in
[REF-ENR-011 through REF-ENR-017](../spec/refspec.md#9-semantic-enrichment).

For search, SpicySearch's immutable retrieval policy selects exact atlas or
projection pins, mapping relations, directions, ranking behavior, and fallback
rules. `rkaf:searchOnly` is a ceiling: it permits search discovery and never
becomes an accepted subject assignment through ranking strength or ring
membership.

Reader-declared uses remain useful source evidence and fail-closed parser
guards. Extend the shared `ResourceUse` vocabulary with `mappingReference`
where needed, but do not turn that enum into a second product permission
system.

## 8. Frontier compilation

Large bridge vocabularies enter through a reproducible two-pass build. A
bounded prefix produced by `max_records` remains a development sample; it is
not a frontier-selection policy.

1. **Acquire and pin the source.** Stream the exact publisher distribution and
   record its digest, release basis, licensing evidence, observed count, and
   source limitations. If the full distribution was not observed, say so; do
   not infer an excluded count.
2. **Build a selection index.** Index publisher concept identifiers, labels,
   publisher mappings, and hierarchy from the pinned source. This index is a
   disposable build aid, not an atlas release.
3. **Select the frontier.** Select concepts that match a declared discovery
   rule against exact core or specialist releases, appear in publisher-stated
   mappings, or fall within the declared hierarchy depth. Write a canonical
   selection receipt that pins every input, algorithm revision, parameter,
   selected identifier, and coverage result.
4. **Publish a complete frontier release.** Create a content-derived
   `rkaf:ReferenceResourceRelease` whose complete membership is exactly the
   selected frontier. Preserve publisher concept identifiers. Its identity
   includes the source pin and selection-policy digest.
5. **Regenerate candidates.** Generate atlas `MappingCandidate` records against
   the exact frontier release. Preliminary selection hits never become mapping
   candidates directly.
6. **Qualify and build.** Qualify the regenerated candidates, verify that every
   endpoint belongs to its complete release, and build the atlas. A changed
   source, core release, selection rule, or hierarchy depth creates a new
   frontier release.

This sequence removes the earlier cycle in which mapping candidates selected
the release that those same candidates already had to name.

## 9. Evidence profiles

An evidence profile is derived deterministically from existing Rulespec
records. It is not independently authored and is not an
`rkaf:assertionOrigin` or `rkaf:epistemicBasis` value.

| Profile | Required underlying facts | Maximum use before narrower product policy |
| --- | --- | --- |
| `machineQualified` | `aiSuggested`; `statisticalInference`; complete AI lineage; exact input; two accepted signed validations under §12.1 | `searchOnly` |
| `publisherAsserted` | `imported` + `sourceExplicit` when copied unchanged; pinned publisher evidence and claimant attribution | `searchOnly` unless separate governance establishes more |
| `publisherDerived` | `deterministicExtraction` + `deterministicDerivation`; extraction provenance; pinned publisher evidence; named conversion rule | `searchOnly` unless separate governance establishes more |
| `operatorAdopted` | Original origin and basis unchanged; named attestation and scoped `LocalAdoption` | Rulespec computes the ceiling; adoption never makes it machine-qualified |
| `humanReviewed` | Named attestation over the reviewed assertion and evidence; `humanAsserted` only when the human constructed a new assertion | Rulespec and exact product policy compute the ceiling |
| `ruleGeneratedCandidate` | Deterministic generation provenance and rule digest; no mapping assertion implied | Not applicable until later evidence supports a mapping |

The FR×ICPSR operator-adopted bridge must therefore retain its machine
construction history and add operator attestation and adoption. It does not
become `humanAsserted` merely because an operator selected it.

SSSOM export keeps standard `mapping_justification` values. A deterministic
RefSpec sidecar keys each row by the stable RefSpec record IRI carried in
SSSOM `see_also`; current model-qualified rows use the candidate IRI. The
sidecar links the resulting mapping IRI when one exists and carries the
evidence profile plus attestation, adoption, source, and validation links.
Downstream filters join on that identifier instead of assigning non-standard
meanings to `mapping_justification`.

## 10. FAST and publisher mapping conversion

The captured OCLC per-term RDF includes `schema:sameAs` links to LCSH. The
current CSV reader does not capture those links, and per-term access does not
establish full-source coverage.

Before FAST promotion:

1. Acquire and pin the official Topical RDF bulk distribution, or publish an
   explicitly partial selection process with bounded coverage.
2. Parse FAST identity, labels, hierarchy, and `schema:sameAs` objects from the
   RDF bytes.
3. Preserve the publisher's `schema:sameAs` statement as source evidence.
4. Derive `skos:exactMatch` only under a named
   `fast-schema-same-as-to-lcsh-exact-match-v1` rule when the object is an LCSH
   topical concept. Record `deterministicExtraction`,
   `deterministicDerivation`, extraction provenance, and the source statement.
5. Limit the derived mapping to `searchOnly` until product evaluation and
   separate governance justify any narrower or stronger use.

This path needs no model judgment, but it still needs exact acquisition,
deterministic conversion, endpoint releases, and verification.

## 11. CRS and local core growth

Congress.gov's Legislative Subject Terms and Policy Areas remain valuable
publisher evidence. Their pages do not supply stable concept identifiers or a
named, versioned vocabulary release. RefSpec therefore keeps them out of
`releaseFacts` and does not mint publisher identity on Congress's behalf.

If repeated product gaps justify a legislative extension, an authorized local
vocabulary publisher may create `rkaf:LocalConcept` records, review them under
the existing [concept-proposal workflow](../spec/refspec.md#124-concept-proposal-workflow),
and publish a separate managed release. CRS labels and assignments may support
that review, but they do not determine identity or approval. Splits, merges,
redirects, definitions, hierarchy, evidence, rights, and attestations follow
the existing governance rules.

The concept-staging design must exist before the first local core extension. It
does not block evaluation of the current ELSST and ICPSR search bridges.

## 12. Qualification 1.1

Format 1.1 is justified only by proof improvements. Portfolio classes remain
outside the manifest.

### 12.1 Signed validator attestations

Publish a versioned qualification-authority policy containing trusted
validator authority identifiers, public keys, independence groups, permitted
provider and model bindings, and key-validity periods. Each validator signs a
canonical receipt over:

- candidate and input-context digests;
- request and response digests;
- provider, model, and observed endpoint host;
- verdict, reason, completion time, and deterministic-check result; and
- the exact qualification-authority policy digest.

A mapping qualifies only when two valid signatures resolve to distinct trusted
validator authorities and independence groups. This proves that the bundle
producer did not invent both validators. Provider identity remains an
attested operational fact; the format must not claim that ordinary API
responses carry provider signatures when they do not.

The existing cosmetic-family attack must fail the 1.1 conformance suite.

### 12.2 Remaining gate changes

- Run the hierarchy A/B experiment before adding hierarchy to every judge
  input. Record a negative result as a decision to keep label-and-scope input.
- Add deterministic generator provenance and same-vocabulary distractors.
- Preserve full sealed reasons rather than truncating them.
- Publish portable projection conformance cases for an unrelated parent and a
  dropped retained fact. The existing RefSpec unit tests remain producer
  regressions.
- Teach SpicySearch to recognize and verify the projection kind before it
  vendors one. Keep expansion disabled during that change.
- Leave Atlas 1.0 artifacts valid and byte-identical. A 1.0 mapping does not
  gain 1.1 proof status retroactively.

## 13. Distribution and downstream composition

One canonical atlas exists per named build scope. Consumers receive named
projections:

- `consumer-read-closure` for the default search and tagging consumer;
- `module:<specialist-release>` for one specialist plus the core and required
  mapping closure; and
- `explorer` for a bounded human-readable view.

The canonical atlas remains available for audit and reproduction. Consumers
verify a projection's parent and policy, then build local indexes from the
projection. They do not vendor the larger atlas merely because it exists.

SpicySearch composes subjects from the atlas, entities from the entity spine,
legal locations from the legal identity graph, codes from ledgers, and
publisher topic assignments from source evidence. Its search database is a
rebuildable read model identified by all those input digests and the indexing
implementation.

The hub-and-spoke plan schedules which release pairs receive candidate
generation and qualification. It does not route search queries. A path such as
source→LCSH→target may suggest a new candidate, but it never creates a
transitive mapping assertion.

SpicySearch owns retrieval and ranking: lexical and dense candidate search,
candidate-pool width, reranking, optional generate-then-map behavior, metadata
priors, and abstention. Source-conditioned metadata may add a soft score, but
it must not exclude the global fallback pool. The atlas supplies exact labels,
mappings, and hierarchy as inputs; it does not choose or authorize those
product behaviors.

## 14. Evaluation and adoption

Every product evaluation pins the exact atlas projection, `OutputProfile` when
enrichment is involved, SpicySearch retrieval policy, ranking implementation,
corpus or query holdout, and metric code. RefSpec's
`EnrichmentConfiguration`, `EnrichmentEvaluationResult`, and
`EnrichmentDeploymentDecision` records remain separate; passing an evaluation
does not activate a deployment.

| Capability | Required comparison | Primary measures | Kill criterion |
| --- | --- | --- | --- |
| Register bridge | Mapped query expansion on vs off | Document recall and ranking quality; differing-surface mappings reported separately | No material recall gain, or precision and explanation quality regress beyond the preregistered threshold |
| Specialist candidate pool | Specialist enabled vs disabled on a source-family holdout | Candidate recall before reranking, precision, abstention, unsupported-label rate, and Y/I/N human review | No useful recall gain, cross-facet leakage, or unacceptable abstention/precision loss |
| Frontier decoys | Frontier present vs absent | Wrong-concept emission rate on off-domain text | Decoys do not reduce wrong emissions or cause a larger relevant-recall loss |
| Qualification 1.1 | Genuine independent validators and executed cosmetic-family attack | Conformance verdict and replay integrity | Cosmetic independence still qualifies a mapping |
| Projection consumption | Canonical atlas vs projection | Predicate-level read parity, open time, and bytes | Consumer-visible facts differ or the projection cannot reproduce from its parent |

Thresholds belong in each preregistered evaluation, not in this architecture
document. Failed experiments remove or defer the affected participation row;
they do not weaken the gate.

## 15. Work order

1. Record the architecture decision, then publish the atlas-index extension
   with non-authorizing `publicationTarget` and `atlasParticipation` rows.
2. Teach SpicySearch to open `consumer-read-closure`, vendor the current
   projection with expansion disabled, and produce an exact read-parity test.
3. Evaluate the existing ELSST and ICPSR bridges on public-register queries.
   This tests the central value claim before adding sources.
4. Specify and implement Qualification 1.1, including signed validator
   attestations and portable conformance cases.
5. Build the two-pass LCSH frontier compiler and measure its decoy value.
6. Acquire and parse FAST RDF, apply the named conversion rule, and measure the
   incremental value beyond LCSH and ordinary lexical search.
7. Pilot specialist releases one at a time under exact `OutputProfile` rows.
8. Design concept staging before publishing any project-governed extension to
   the core. Keep CRS as source evidence until then.
9. Design the entity spine and legal identity edges separately. Reuse the same
   pin, receipt, provenance, and non-name-equality principles without forcing
   them into the atlas.

## 16. Decision boundaries

This synthesis does not:

- adopt or amend RefSpec or Rulespec;
- authorize a source, mapping, candidate, or accepted output;
- deploy or activate SpicySearch expansion;
- make a live database authoritative;
- treat publisher labels as concept identity;
- design the entity spine or legal identity graph; or
- claim that unrun experiments succeeded.

Adoption requires a recorded RefSpec decision and any corresponding normative
specification changes. Implementation, publication, SpicySearch vendoring,
evaluation, deployment selection, and production activation remain separate
states.

## 17. Final synthesis

The atlas should grow, but source count is not the goal. The goal is a small,
trusted subject core; evidence-activated specialist vocabularies; search-only
bridges between public and administrative language; and separate publications
for entities, codes, legal identity, and publisher assignments. Exact releases
and mapping evidence make that system reproducible. `OutputProfile` and
retrieval policy make its use explicit. Product evaluations decide whether
each addition earns operational use.

This shape preserves the useful multi-vocabulary atlas, avoids a fused
registry, and gives SpicySearch a rebuildable path from source evidence to
measured search value.
