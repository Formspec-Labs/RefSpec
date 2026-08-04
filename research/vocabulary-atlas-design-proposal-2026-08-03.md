<!-- markdownlint-disable MD013 -->

# Vocabulary Atlas Design Proposal — from three sources to the full registry

> **Status:** Proposed design; not adopted
>
> **Standing:** Rules and structure are this document's durable content.
> Counts and build references are dated snapshots of an artifact set in
> motion; `output/` is a workbench, and decision ceremony binds at
> publication boundaries — when an artifact ships to a consumer — never to
> experimental runs.
>
> **Date:** 2026-08-03
>
> **Decision synthesis:** [Vocabulary Atlas Final Synthesis](vocabulary-atlas-final-synthesis-2026-08-03.md)
> resolves the review findings and supersedes this draft for decision-making.
>
> **Builds on:** [Atlas binding 1.0](../bindings/atlas/1.0/README.md) ·
> [Source Vocabulary Catalog](source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md) ·
> [Source and Document Type Matrix](source-document-type-matrix-2026-07-28.md) ·
> [Concept Tagging Architecture Proposal](concept-tagging-architecture-proposal-2026-07-28.md) ·
> [External research synthesis](large-label-space-tagging-external-research-synthesis-2026-08-03.md) ·
> [Crosswalk qualification pilot](../docs/atlas-crosswalk-qualification-pilot.md) ·
> [Distribution measurement](../docs/atlas-distribution-measurement.md)
>
> **Addendum:** [What this proposal does not cover](vocabulary-atlas-design-proposal-addendum-2026-08-03.md) —
> evidence-exceeding commitments, demands assigned to other layers, and the
> successor proposals still to write (concept staging, entity spine, legal
> identity edges).

## 1. The problem

Atlas 1.0 works. It is a byte-reproducible two-file publication (manifest +
blank-node-free N-Quads) with a hard authority split between copied release
facts and replaceable machine analysis, a two-independent-machines gate for
`searchOnly` mappings, projections, an SSSOM export, and a static explorer.
Three vocabularies are in it (Federal Register Thesaurus 2025, ELSST, ICPSR).
As of the 2026-08-03 two-crosswalk build, the atlas held 233,999 quads, 730
mapping candidates, 1,459 machine validations, and 240 qualified
`searchOnly` mappings (121 FR×ELSST + 119 FR×ICPSR); a same-day
three-crosswalk build added an experimental ELSST×ICPSR bridge (146
qualified; 386 total); next-day v2 re-runs of all three pairs qualified
564 typed mappings into a v2 bench build (§7). Counts in this document
are dated snapshots of a moving artifact set, never a baseline — the
authoritative identity and digests for any build live in its own
manifest.

The registry now contains 72 substantive modules — 54 source readers plus
adapters, shared infrastructure, managed-release builders, and packages —
spanning six groups:
subject thesauri (LCSH topical, FAST topical, MeSH
descriptors, NALT Core, GEMET, EuroVoc, AGROVOC, NASA, DOE OSTI, EPA
Enterprise Vocabulary), code lists (NAICS/PSC, nature-of-suit, FEC, FCC,
FERC, NRC, SEC, LDA, BILLSTATUS, OMB A-11, Treasury TAS, GSDM, Census, OPM,
Grants.gov, SAM), identifier authorities (UEI/CAGE, NPPES NPI), entity and
organization sources (EPA SRS, federal hierarchy), navigation lists (CBO,
GAO topics, CRS product topics), and native controls (Regulations.gov,
Unified Agenda, OIRA, PRA, oversight report types, SCOTUS opinion types).

Extending the current atlas naively — one adapter per reader, everything
becomes release facts — fails four ways:

1. **Kind mixing.** Code lists, identifiers, and entity registries are not
   concept schemes. Putting NAICS codes or NPI prefixes into `releaseFacts`
   repeats the fused-registry category error the catalog already rejects.
2. **Scale.** In the superseded two-edition build, label clusters were 69%
   of atlas bytes with no consumer reading them; the R6-only edition
   restriction cut the artifact 82.9%, and current builds hold ~1,500
   clusters. LCSH topical is hundreds of thousands of headings; FAST
   topical is 440,599 — full ingestion would recreate the unread majority
   at far larger scale.
3. **Quadratic qualification.** Pairwise crosswalk qualification across N
   vocabularies is O(N²) pairs. Thirty sources ≈ 435 pairs. Cost is minor
   (the pilot ran a pair for $1.01) but review attention and gate weaknesses
   scale badly.
4. **Known gate and format defects.** Validator independence is evidenced,
   not enforced; the judge never sees hierarchy; the label-equality diagonal
   dominates qualified mappings (87.5% normalized equality on the
   two-crosswalk build, 97.5% counting all label-equality classes); the
   format has no honest slot for rule-based generation or operator-adopted
   review; the blind-review comparison holds eight machine-qualified pairs
   a human refused, and protocol v2 addresses refusal misses, not
   over-claims — nothing yet makes a wrong `same_or_near_same` less
   likely; the vendored consumer refuses new manifest fields; projection
   conformance fixtures do not exist.

This proposal keeps the atlas exactly what it is — a publication format, not
a second vocabulary model — and adds the structure needed to absorb the
registry: a ring model for membership, a frontier rule for oversized mapping
references, typed mapping-evidence classes, a hub-and-spoke qualification
plan, and an explicit ladder from registry reader to atlas member.

## 2. Design principles (inherited, then new)

Unchanged from atlas 1.0 and the catalog:

- The atlas is a publication format. No concept identity is minted; concepts
  stay in exactly one source release.
- Two named graphs with policies checked by exact equality.
- Equal labels are discovery hints (`atlas:LabelCluster`), never mappings.
- Human feedback is append-only and non-authorizing; machine agreement is
  not human review.
- Deterministic bytes: no blank nodes, sorted lines, independent SHA-256
  pins for manifest and quads.

New, motivated by the external-research synthesis and the registry's growth:

- **Graphs partition by scope, not authority.** Release-local facts vs
  cross-release records (candidates, mappings, validations, attestations,
  discovery aids); authority and epistemic status are properties of each
  cross-release record — carried by its origin, basis, attestation, and
  adoption — never of the graph that holds it. Atlas 1.0 framed the
  analysis graph as replaceable machine analysis; this reinterpretation is
  the change that admits §6's evidence classes.
- **Map wide, emit narrow.** The atlas may hold a wide mapping space, but
  candidate authorization for tagging is a per-release property that most
  releases never get.
- **Resource kinds do not mix.** Only subject-bearing concept schemes enter
  `releaseFacts`. Code lists, identifiers, entities, and controls are
  published in sibling artifacts and joined by identifier, never by concept.
- **Bounded subsets are first-class.** A release fact set may be a declared,
  coverage-accounted subset of an oversized source (the LCSH reader already
  works this way). Selection policy is part of release identity.
- **Mapping evidence is typed by origin.** Machine-qualified is one origin
  among several; publisher-asserted and operator-adopted evidence get honest
  slots instead of being forced into `aiModel`/`humanAsserted`.

## 3. The ring model

Every registry source gets exactly one ring assignment, recorded in the
portfolio index as a non-authorizing planning label. Rings never become
atlas manifest fields; the manifest stays eligibility-bearing only through
the policies consumers already check. Rings determine what a release's
facts may authorize — they are eligibility tiers, not storage tiers.

### Ring 0 — emit core (candidate-authorized)

The only schemes whose concepts may be proposed as subject assignments.

| Source | Reader | Basis |
| --- | --- | --- |
| Federal Register Thesaurus 2025 | `federal_register_thesaurus_2025*` (managed release, in atlas) | Purpose-built for the corpus; 1 CFR 18.20 |

**CRS does not enter ring 0.** Congress.gov identifies CRS terms only by
`name`; publisher identifiers are absent, so a managed release is blocked
(`crs_legislative_resources` records both facts). CRS Legislative Subject
Terms and Policy Areas enter as `sourceAssignedEvidence` on the records
that carry them — like CFR List of Subjects literals, which resolve against
the FR Thesaurus via the Lists-of-Subjects policy
(`policies/federal_register_lists_of_subjects`:
`officialTerm` / `recognizedVariant` / `sourceLocalOpenTerm` /
`unresolved`). Ring-0 growth routes through the concept-staging workflow
(addendum B4; spec §12.4 concept proposals / `rkaf:LocalConcept`), which
may mint RefSpec-governed concepts citing CRS terms as sources.

The CRS packages still need stable operational handles. Each source fetch
records an RFC 9562 UUIDv7 `sourceFetchId` plus `sourceObservedAt`; the combined
package records a separate UUIDv7 `registrationEvent`. Every first-seen row gets
a UUIDv7 `localRecordId`. These are RefSpec record identities, not CRS term
identities. Each immutable ledger directory saves both complete packages, both
sorted local-ID and record-content digests, and the reconciliation or human
review. On refresh, a unique publisher identifier match wins; otherwise a
unique exact scheme/category/label match carries the local ID forward. Any
capture-independent content change writes a reconciliation report and stops
promotion for human review; similarity may suggest a match but never decides
one. A source-byte change with identical parsed records is retained as a
source-only change and does not create false term churn. Target core size stays
in the low thousands, consistent with the EuroVoc anchor and the architecture
proposal's 1,000–3,000 starting range.

### Ring 1 — specialist modules (conditionally candidate-eligible)

Activated per document from evidence, never as a hard filter. Each module
needs its own adoption gate (catalog §Adoption gates) and holdout before its
concepts are candidate-eligible anywhere.

| Source | Reader | Catalog decision |
| --- | --- | --- |
| MeSH descriptors (not SCRs) | `mesh_descriptors` | Pilot |
| NALT Core | `nalt_core` | Pilot after license reconciliation |
| GEMET | `gemet_thesaurus` | Pilot with strong abstention |
| NASA Thesaurus | `nasa_thesaurus` | Candidate after freshness check |

### Ring 2 — register bridges (searchOnly forever)

Never candidate-authorized. Ring 2 is not a junk drawer of references: each
vocabulary here bridges a different language community's **register** into
the core. The Federal Register core speaks administrative supply-side
language ("Incorporation by reference"); users and researchers speak other
registers ("food insecurity", "recidivism"). A qualified `searchOnly`
mapping lets a query phrased in one register reach documents indexed in
another — connect and expand, never tag. Ring-2 releases also absorb
off-domain matches (decoys) and carry crosswalks. Eligible uses are exactly
what their readers already declare (`searchExpansion`, `mappingReference`).

| Source | Reader | Register bridged / note |
| --- | --- | --- |
| LCSH topical | `lcsh_topical` | Library and general-public register; bounded subsets only; the crosswalk hub (§5) |
| FAST topical | `fast_topical` | Same register via LCSH derivation; publisher-asserted edges (§6) |
| EuroVoc | `eurovoc_thesaurus` | International/EU policy register; reader today refuses any use but `mappingReference` — its search-expansion use waits on the §3 enum extension and index reconciliation |
| AGROVOC | `agrovoc_thesaurus` | Multilingual agriculture register; crosswalk for NALT |
| ELSST (R6) | `elsst_*` (in atlas builds) | European social-science register. Target state: **bench** — the format's proving vocabulary and the ELSST×ICPSR experiment substrate, not a product bridge; it enters a product scope only by passing the §9 ladder like any promotion |
| ICPSR subject thesaurus | `icpsr_*` (in atlas builds) | US social-science research register — the public/research phrasing of policy topics; `developmentOnly` marker republished (REF-009). Target state: re-cut as a complete verified-subset release (§9), then a product-bridge candidate **if** the §10 query-side evaluation earns it; the 119 qualified mappings are bench evidence until then |
| DOE OSTI, EPA Enterprise Vocabulary | `doe_osti_thesaurus`, `epa_enterprise_vocabulary` | Deferred until release/license verified |
| GCMD Science Keywords, NASA Technology Taxonomy | `gcmd_science_keywords`, `nasa_technology_taxonomy` | Mapping/deterministic only per catalog |

### Ring 3 — outside the atlas, inside the constellation

Code lists, identifier authorities, entity registries, navigation lists, and
native controls never enter `releaseFacts` or `analysis`. This covers
roughly half the registry: NAICS/PSC, TAS/FAST Book, OMB A-11, GSDM,
BILLSTATUS, LDA, FEC, FCC ECFS, FERC, NRC ADAMS, SEC series, nature-of-suit,
SCOTUS opinion types, oversight report types, CBO/GAO/CRS product topics,
Grants.gov, SAM, Census, OPM, NPPES NPI, UEI/CAGE, EPA SRS, federal
hierarchy orgs, Regulations.gov / Unified Agenda / OIRA / PRA controls.

"Outside the atlas" is not "outside the product." Ring-3 sources feed three
**sibling reference publications**, each with its own identity semantics and
trust model, published under the same pin-and-receipt discipline the atlas
proved out:

| Sibling publication | Contents (readers) | Identity semantics | Status |
| --- | --- | --- | --- |
| **Entity spine** | agencies (`federal_hierarchy_orgs`), award entities (`uei_cage_identifiers`), committees (`fec_committee_codes`), providers (`nppes_npi_identifiers`), substances (`epa_srs_substances`), courts (`courtlistener_codes`), geography identifier grammar (`census_geo_codes`) | Nodes carry typed identifier sets; identity links are evidence-classed exactly as §6 classes mappings — publisher-asserted crosswalks (SAM's own UEI↔CAGE), machine-suggested matches, human-reviewed merges. Never merge on name equality. | Unwritten — needs its own proposal (matrix `T3-04` anticipates it) |
| **Code ledgers** | NAICS/PSC, fiscal codes, filing types, genre and process values, all native controls, cross-state statistical crosswalks (`census_gov_finance_codes`) | Versioned value sets with effective dates; raw values preserved exactly; reviewed edition crosswalks only where needed (NAICS 2017→2022, nature-of-suit spelling canonicalization) | Essentially built (`source_controlled_resource`, `regulatory_native_controls`) |
| **Legal identity graph** | CFR structure, statutes and Public Laws, RINs, docket and bill identifiers, citations | Deterministic parsed identity; typed edges (*cites*, *amends*, *authorizes*, *implements*) with point-in-time versions — the ELI analogue | Half-built (identifiers and citations exist as fields; the typed-edge model needs design) |

A fourth category rides alongside the ledgers but deserves its own name:
**source-assigned topic evidence** — GAO topic assignments, CBO topic
labels, CRS product topics, LDA issue codes, SAM mission/subject fields.
These are per-document topical evidence from the publisher, not schemes and
not codes. They are captured as `sourceAssignedEvidence` observations
(already in the bundle model), consumed by the pipeline, and — unlike codes
— may later earn small reviewed maps into ring-0 concepts through §6's
evidence classes, letting a publisher's own assignment corroborate a
core-subject tag.

Documents compose all four publications at query time — subjects from the
atlas, entities by role from the spine, legal location from the identity
graph, facets from the ledgers — and the product graph is assembled from
these layers, never stored as one monolith. The separation is load-bearing:
each layer's trust model differs (two-validator semantic judgment vs pinned
publisher record vs deterministic parse), and one shared trust model would
either over-burden the cheap facts or under-protect the risky ones.

One boundary clarified here because it is easy to misread: the decoy
function for entity labels (DNB's lesson — entities missing from the mapping
space cause forced-choice snapping onto wrong subjects) is served by the
**pipeline's mapping index**, which may union the atlas frontier with
entity-spine labels at retrieval time. Entities still never enter the
atlas's release facts. Absorb-in-one-space / emit-on-another-facet is a
pipeline composition, not an atlas membership rule.

A one-page **atlas index** (an extension of `portfolio/resource-catalog`)
names every registry source, its ring, its publication target (atlas ·
entity spine · code ledger · legal identity graph · source-assigned
evidence), and its promotion status, so "the atlas" never silently comes
to mean "everything." The ring
tables in this section are illustrative; the index is the exhaustive
assignment of record. Index versions are immutable: a failed experiment
produces a new version marking the row `deferred` or `rejected` with the
evaluation attached — history is never deleted. Row status draws from a
closed, machine-validated vocabulary (`planned`, `deferred`, `rejected`,
`superseded`, `unassessed`, `notApplicable`), and every ring value is a
statement of intent — only a product policy activates a use.

**Ring semantics must be expressible in reader code.** The registry's
readers already enforce their catalog decisions individually
(`eurovoc_thesaurus` refuses any use but mapping-reference; `lcsh_topical`
hard-codes `candidate_use_authorized=False`; `gao_topics` refuses to
reconstruct a scheme from navigation), but the shared `ResourceUse`
vocabulary lacks a `mappingReference` value — EuroVoc enforces a literal
outside the enum, and LCSH declares `searchExpansion` only despite its hub
role. Extend the enum (`mappingReference`, and `candidateGeneration` if
ring-1 activation needs it) and let the atlas index reconcile
reader-declared uses against ring assignments, so a ring claim and a
reader's own eligibility declaration can never silently disagree. The same
reconciliation defines `candidate_use_authorized`, whose semantics are
inconsistent at scale: LCSH hard-codes `False` as the mapping-only marker
while **more than twenty modules pass `True`** — ring-1
`mesh_descriptors` and roughly eighteen ring-3 readers among them —
because the shared builder makes the flag a required parameter and no
shared model documents its meaning. A ring-2 or ring-3 source declaring
`True` is a reader/ring disagreement to resolve — never a grant. Target
values follow the rings: every ring-2 reader carries `False`; ring-3
readers should carry no candidate flag at all, which requires making the
parameter optional in the shared model (the concept does not apply
outside the atlas) — until that change lands, ring-3 readers set
`False`; FAST flips to `False` with the enum extension. A reader's flag
converges to its ring — never the reverse.

## 4. Membership rule for oversized ring-2 sources: the mapping frontier

Full ingestion of LCSH or FAST is prohibited by scale and pointless by use.
Instead, a ring-2 release entering the atlas is a **frontier subset** whose
selection policy is declared in the release and whose coverage is accounted
(`source_observed_count` and `excluded_count` exist today in the
source-capture bundle model; the frontier compiler carries the same
accounting into the managed-release layer, where it does not yet exist).
A ring-2 concept belongs to the frontier when it:

1. matches a selection predicate against ring-0/1 concepts (lexical and
   label-based, the same predicate families that generate candidates);
2. is an endpoint of a publisher-asserted mapping (§6); or
3. lies within a declared small number of `skos:broader` steps of (1) or
   (2) — hierarchy context for judges and consumers, bounded and stated.

**The build is two-pass.** An atlas candidate requires both endpoints in
release facts, so candidate generation cannot itself select the release it
presupposes. Pass 1 runs the selection predicates against the full source
through its reader and emits a canonical **selection receipt** — predicates,
versions, per-concept justification. Pass 2 cuts the complete frontier
release from that receipt, seals it, and only then generates mapping
candidates against the sealed release. The `lcsh_topical` reader's
`max_records` bound is a development sampling tool, not a selection policy.

**Completeness is scoped, and the scope is declared.** Three levels are
distinct and never conflated: *source coverage* (was the full publisher
distribution observed), *release-scope completeness* (does the release
enumerate every member its declared scope selects), and *reference
closure* (is every node referenced by retained mappings and hierarchy
edges present or explicitly marked external). Every mapping endpoint
belongs to a release whose membership is closed and complete **within its
declared scope**; the release separately declares whether that scope is
the complete publisher vocabulary, a verified subset, or a policy-selected
frontier. "Not in the release" never means "not in the source vocabulary."

**Hierarchy at the frontier boundary is handled explicitly.** Cross-release
broader edges are build-fatal, so when a selected concept's broader
concept lies beyond the permitted depth, the compiler does one of three
things: includes the broader concept, retains an explicitly external
reference, or omits the edge and records the truncation in the selection
receipt. A source-stated hierarchy edge never silently disappears.

**Negative knowledge is bounded.** Absence from a frontier is not evidence
the source lacks the concept; absence from the candidate set is not
evidence no mapping exists; a rejected candidate records only that this
candidate failed under the named input, validators, and policy; a frontier
evaluation measures the selected frontier, not the vocabulary. Any display
that exposes rejected candidates states this.

Everything else in the source stays out of the atlas and remains reachable
through the reader for future frontier growth. Frontier releases are
re-cut, not mutated: a new selection receipt yields a new release with its
own pins.

Label-cluster policy changes with the rings: clusters are computed only
between ring-0/1 schemes and the frontier — never ring-2 × ring-2 — and are
dropped from the default consumer projection (in the superseded two-edition
build, clusters were 69% of bytes with nothing reading them; the
`consumer-read-closure` projection already excludes them).

## 5. Crosswalk topology: hub-and-spoke, not pairwise

Qualification runs are scheduled on two spokes only:

- **Emit spoke:** every ring-1 and ring-2 release × the ring-0 core. This is
  the only crosswalk the tagging product consumes.
- **Hub spoke (optional, staged):** ring-1/2 releases × the LCSH frontier.
  LCSH is the de facto hub of the library vocabulary world — FAST is derived
  from it and published LCSH↔MeSH alignments exist — so one hub spoke buys
  transitive discovery without O(N²) direct pairs.

The product's emit spoke never requires ring-2 × ring-2 qualification, and
none is scheduled for it — but experiments may run any pair, and at pilot
economics ($1.01 and ~730 calls per 365-candidate pair) cheap ones should:
the first bridge-to-bridge run (ELSST×ICPSR, 146 qualified) is exactly that
kind of experiment, probing whether register bridges interconnect. The
binding constraint on scheduled scale-out is gate quality, not budget,
which is why §7 precedes it.

Transitive claims across the hub (`A→LCSH→B`) are never materialized as
mappings; they may generate *candidates* for direct qualification, which is
exactly the discovery-hint role label clusters already play. This
prohibition covers typed relations: no relation algebra composes chains
into assertions (`broadMatch` ∘ `broadMatch` is a candidate generator, not
a `broadMatch`), and `adjudicatedRelation` annotations (§6) are the
highest-quality hub hints precisely because they stay hints.

## 6. Typed mapping-evidence classes

The analysis graph currently admits one origin: machine-qualified
(`rkaf:aiSuggested` + `rkaf:statisticalInference`, two independent
validators, `searchOnly`). Two real cases already overflow this:

- The FR×ICPSR run completed the full two-family gate (730/730 calls, 119
  qualified; §1). During an interim operator pause at 96 calls, 122
  single-model-reviewed pairs were adopted into a development-only concept
  bridge — which the bridge schema can only mislabel as
  `humanAsserted`/`editorialAssertion`, since it has no slot for
  machine review adopted by operator direction. The sealed run supersedes
  the bridge's operational role: its target state is historical evidence,
  its 122 adoption events retained as annotations on candidates that now
  carry full two-machine adjudications.
- FAST records carry their LCSH source headings — publisher-asserted
  derivation edges that need no model calls at all — and the deterministic
  candidate generator itself is declared `aiModel` for lack of an honest
  value.

Format 1.1 therefore adds explicit origin classes, each with its own
eligibility ceiling:

| Class | Origin / basis | Ceiling | Example |
| --- | --- | --- | --- |
| `machineQualified` | `aiSuggested` / `statisticalInference`, two independent validators | `searchOnly` | current 121 FR×ELSST rows |
| `publisherAsserted` | `rkaf:imported` / `rkaf:sourceExplicit`, pinned source bytes | `searchOnly` | FAST→LCSH derivation; MeSH↔LCSH published alignments |
| `operatorAdopted` | single-machine review adopted by named operator | `localOperationalUse`, never atlas-qualified | ICPSR bridge v2 |
| `humanReviewed` | named reviewer, evidence reference | may exceed `searchOnly` per governance | zero rows today; fixtures required |
| `ruleGenerated` (candidate provenance, not a mapping class) | deterministic generator, honest `generatorKind` | n/a | current lexical candidate generator |

These classes are realized as **derived evidence profiles** — deterministic
views over existing Rulespec origin/basis pairings (`rkaf:imported` +
`rkaf:sourceExplicit` for publisher-asserted; deterministic
extraction/derivation pairings for publisher-derived) — not as new origin
literals. Operator adoption *annotates* a record without ever rewriting its
machine origin, so a single-model review adopted by operator direction is
expressible without mislabeling where the judgment came from.

**The gate owns the relation.** The candidate's `atlas:proposedRelation`
stays uniformly `skos:closeMatch` — the hypothesis under test, never the
answer. Gate protocol v2's direction-pinned verdicts (`same` →
`skos:exactMatch`, `near_same` → `skos:closeMatch`, `target_is_broader` →
`skos:broadMatch`, `target_is_narrower` → `skos:narrowMatch`, `related` →
`skos:relatedMatch`) make a qualified mapping a joint
relation-plus-eligibility judgment. The agreement rule folds the **set**
of verdicts from every supporting validation — universal, not
existential, which is what keeps a third machine deterministic — and
emits at the weakest claim any machine made: `{same}` → `exactMatch`;
`{same, near_same}` or `{near_same}` → `closeMatch`; a single directional
set → its directional predicate; any other set refuses, exactly as a v1
disagreement. No other downgrades: `near_same` + `target_is_broader` is a
real dispute about direction-safety, and downgrading it to `relatedMatch`
would assert a third claim neither machine made. Blindness has two
meanings and both hold: the generator's class never reaches the judge,
and neither does `proposedRelation` — omitted from the v2 judge payload
because a standing relation in the prompt is a prior on the one axis v2
measures. The motivating evidence: 752 of 2,190 v1 validations (34%) answered
`related_but_distinct` while their sealed prose named a relation the
binary verdict discarded — read honestly, roughly 660 state a usable
direction or association and the rest predict nothing.

**The discovery ladder has three rungs, each with its own job.** Label
clusters are lexical hints — never mappings. `atlas:adjudicatedRelation`
annotations (sealed when two machines agree on `related` with no mapping
emitted) are *semantically adjudicated* hints — typed associative
knowledge below mapping status, and the preferred generator of hub-spoke
candidates and frontier hierarchy context, since they carry two-machine
judgment where clusters carry only string equality. Qualified mappings
are assertions. Nothing on a lower rung ever silently becomes an upper
rung. One visibility boundary holds today: adjudicated-`related`
annotations are bundle- and analysis-internal — the consumer projection's
keep-rule roots on qualified mappings and drops them, and the explorer
draws every `notEligible` candidate alike. Producer-side discovery reads
the full atlas and gets their value now; consumer visibility waits on a
versioned `CONSUMER_READ_CLOSURE_V2`, a separate and deliberate decision.

**Machine `exactMatch` is not identity.** An adjudicated `exactMatch`
keeps its eligibility ceiling, never merges concepts, and asserts nothing
beyond retrieval interchangeability. One designed exception: `same` is
the only verdict that may ever feed a **future equivalence-clustering
pass** — in-house connected components, designed separately against its
own failure modes once the first `exactMatch` edges exist — and that pass
must never route into `exactMatchCluster`, which is a sealed-gold holdout
partition key, not clustering machinery; two-machine agreement warrants a
pairwise claim, never a leakage control. Direction semantics ride on the
predicate itself — a consumer expands across `broadMatch` asymmetrically,
and no new eligibility vocabulary is minted. Relation composition across
mappings (`broadMatch` ∘ `broadMatch`, or any chain through the hub)
stays prohibited exactly as §5 prohibits untyped chains: chains may
generate candidates, never assertions.

**Evidence class is separate from proof version.** Each qualified mapping
names its qualification policy and its proof status
(`legacyIndependentValidations` for atlas 1.0 runs;
`signedIndependentValidations` once attestations ship). A mapping
qualified under 1.0 remains valid under 1.0's policy and never acquires
1.1 proof status; a profile demanding signed proof excludes it without
invalidating it. Profiles compose rather than supersede: one mapping may
be machine-qualified, later human-reviewed, and locally adopted at once —
states accumulate, and no profile erases another's history.

**The atlas preserves assertions, not one mapping truth per pair.**
Contradictory relations between the same endpoints coexist as separate
records, each with its own origin, evidence, policy, and lifecycle; no
bundle overwrites an earlier assertion; adoption targets an assertion IRI,
never an endpoint pair. A consumer may derive a "best mapping" view, but
that view is disposable and retains links to every contributing assertion.

No class other than `humanReviewed` ever authorizes emit-side use; that
boundary is the ring model restated at the mapping layer.

## 7. Qualification — protocol v2 baseline, format 1.1 ahead

The gate's protocol baseline is **v2**, sealed under binding amendment
`2026-08-03-relation-adjudication`: relation-adjudicating verdicts (§6),
each bundle version-homogeneous at `schemaVersion` 2.0 — a bundle never
mixes versions, a build may mix bundles — validations carrying
`verdictRelation` cross-checked at create and open, and v1 bundles still
openable and byte-stable. The manifest's eligibility policy string is
unchanged because that field set is closed on both sides and a value
change is a binding version bump (REF-009, REF-011) — not for asset
stability, which this change never had: `atlas/model.py` sits inside the
implementation pin, so every atlas id moved regardless. A v2 run receipt
records its `protocol` and the eligibility policy
`twoIndependentMachinesRelationAgreement`; v2 seals a different rubric
and payload, so a v2 candidate is a different candidate, generated per
protocol. All three pairs re-ran under v2 on 2026-08-04 through the
batch path (~$1.28 total): FR×ELSST qualified 185/365 (29 `exactMatch`,
81 `closeMatch`, 25 `broadMatch`, 50 `narrowMatch`, plus 29
adjudicated-`related` annotations), FR×ICPSR 196/365, ELSST×ICPSR
183/365 — a v2 bench build carries **564 typed `searchOnly` mappings**
over 1,095 candidates and 2,190 validations. Cross-version comparison
uses `qualifiedAsSubstitutable` (`exactMatch` + `closeMatch` only):
v2's `qualified` includes directional relations and is not comparable
to v1's. The redefined control floor — the sibling distractor is a
relation-discrimination probe; no distractor may earn
`same`/`near_same` — held in all three runs, with the receipts carrying
the per-class `qualifiedAsSubstitutable` counter that operationalizes
it. **One watch item the floor does not cover:** distractors now
qualify directionally (~5 per run), and a random negative control
earned a directional mapping in two of the three runs. That is evidence
the directional bar needs its own scrutiny — alongside item 2's
hierarchy arm — before directional mappings are treated as settled.
Qualification also runs through provider batch APIs at roughly half
price: request bodies and digests byte-identical to the serial path,
collected receipts replicating serial fields exactly, spend caps enforced
at submit (a batch cannot be stopped mid-flight), batch-only provenance
in a sidecar, and missing results left unreceipted so resubmission
re-asks.

The items below are the **format 1.1** workstream — ordered prerequisites,
drawn from the pilots' findings, before the emit spoke runs at registry
scale:

1. **Provider binding.** `endpointHost` sealing is evidence, not
   enforcement; the executed attack (two cosmetic families, one endpoint)
   still qualifies a mapping. Bind the provider IRI to something the
   producer cannot freely choose. This is a format change; do it in 1.1,
   not after 30 sources are in. The mechanism: **signed validator
   attestations** under an authority policy — keys bound to independence
   groups, one canonical signed receipt per validation. Provider API
   responses carry no signatures, so attestation binds the runner, not the
   upstream model; that limit is stated, not hidden. The authority policy
   is a root of trust the bundle may reference but never supply: consumers
   pin it independently of any mapping bundle; a named governance
   authority adopts and signs it; key custody, independence-group
   assignment, revocation, and policy succession are part of it; and every
   receipt is evaluated against policy validity at its signing time. Two
   signatures then prove exactly this much: the receipts were issued by
   two separately trusted validator keys in distinct independence groups.
2. **Hierarchy arm — upgraded from experiment to prerequisite.** Protocol
   v2 emits *directional* verdicts (`target_is_broader`,
   `target_is_narrower`) on sealed inputs that carry no hierarchy — the
   exact input insufficiency the pilot flagged. Until the A/B runs
   (label-only input vs input carrying ancestor labels, never a stated
   shared ancestor, same candidate slice), direction-typed emissions are
   scored as a separately validated class in every evaluation and do not
   feed the frontier's hierarchy-context rule.
3. **Honest candidate classes.** Add same-vocabulary distractors (currently
   inexpressible) and `ruleGenerated` provenance; keep negative-control
   classes mandatory in every run.
4. **Un-truncate sealed reasons** (400-char loss already observed on 4/729).
5. **Consumer/format lockstep.** The vendored reader refuses unknown
   manifest count fields (`hierarchyEdges` made an atlas inadmissible; the
   projection asset-id collision triggered the corruption message). Version
   the manifest schema explicitly, teach the consumer the projection
   manifest shape, and land the two missing conformance fixtures (a
   projection dropping a consumer-read fact must refuse; one claiming an
   unrelated parent must refuse) before any new fields ship.

## 8. Topology and distribution: one canonical atlas, many projections

One canonical atlas per build scope (rings 0–2 frontier), because qualified
mappings require both endpoints in the same atlas's release facts and a
constellation of mini-atlases would fragment identity and closure. Consumers
never vendor the canonical atlas: the distribution measurement showed the
full artifact strictly dominated by its projection (4.5–5× bytes for zero
additional reads, and slower to open). Named projection policies:

- `consumer-read-closure` (exists) — the tagging consumer's contract.
- `module:<ring-1-source>` (new) — one specialist module + ring-0 core +
  their qualified mappings, for domain-scoped deployments.
- `explorer` (exists via bounded publication view).

SSSOM export continues per bundle with row-level `mapping_source`,
edition-scoped prefixes, and no `confidence` column. Origin classes do
**not** mint nonstandard `mapping_justification` values: justifications
stay standard `semapv`. Candidate identity and mapping-assertion identity
stay distinct: every exported qualified row's `see_also` resolves to
exactly one mapping-assertion IRI, and the sidecar carries the candidate
IRI, validation receipts, qualification policy, proof status, and use
ceiling. Rejected and unqualified candidates never export as SSSOM mapping
rows; they get a separate candidate-evidence representation. The SSSOM
file and its sidecar publish as one digest-pinned distribution whose
manifest states that SSSOM rows are interoperability projections — product
use requires the sidecar and the product's own policy.

**Publication is a decision, not a configuration.** Every atlas build and
projection cut is authorized by an immutable publication-decision record:
the portfolio-index snapshot used for planning, exact release and
crosswalk inputs, selection and qualification policies, intended scope,
decision actor and time, any development-only or rights exceptions, the
resulting atlas identity, and supersession history. Three control planes,
one decision each: publication (this record), enrichment (the output
profile), search traversal (the retrieval policy).

**Bench and product scopes are named, never implied.** Every build to date
is bench material. The first product-scoped canonical atlas contains the
ring-0 core plus whatever has passed the §9 ladder — today, nothing else.
ELSST and ICPSR enter a product scope through the same gates as any
promotion; membership in bench builds grandfathers nothing, and "in the
atlas" without a scope qualifier means the bench.

## 9. The promotion ladder

The portfolio catalog's statuses become the single ladder from "reader
exists" to "in the atlas," aligned with the catalog's adoption gates:

```text
inventoryOnly → evidenceOnly → verifiedDistribution → managed release / frontier capture → ring assignment in atlas
```

Each step has an existing artifact: readers produce evidence; acquisition
modules pin verified distributions; `managed_vocabulary_bundle` or a
frontier capture packages the release; the atlas build consumes it under its
ring. Proposed order of the next promotions:

1. **CRS Legislative Subject Terms + Policy Areas → `sourceAssignedEvidence`
   packages.** Publisher identifiers are absent and a managed release is
   blocked, so CRS assignments flow as evidence on the records that carry
   them. Operate the UUIDv7 capture ledger and resolve any changed-capture
   reconciliation before use; ring-0 growth still goes through concept staging
   (addendum B4).
2. **MeSH descriptors → ring 1 pilot** (largest, best-governed specialist
   module; activation evidence is plentiful in health-related sources).
3. **LCSH topical frontier → ring 2 hub**, compiled with the §4 two-pass
   build against the ring-0 core plus MeSH.
4. **FAST topical → ring 2** via `publisherAsserted` derivation edges to the
   LCSH frontier — the cheapest crosswalk in the whole plan; no model calls.
   Prerequisite: the current `fast_topical` reader consumes CSV without
   `sameAs` capture, while the derivation edges live in FAST's per-term RDF
   (`schema:sameAs` → LCSH); the reader must ingest that form first.
5. **GEMET, NALT Core, NASA, EuroVoc → rings 1/2** as their license and
   freshness gates clear.
6. **DOE OSTI, EPA EV** stay deferred per catalog until verifiable releases
   exist.

Also folded into the ladder, because they block trust in what ships:
decide the ELSST schema-set-digest question — the defective pin's
in-tree carrier (builder and test) was deleted in the registry
restructure *without the decision being made*, the stored bundle now
opens through the generic managed-release reader, and only the evidence
record still carries the defect; rule on whether an
`operationalSerializationProfile` digest ever belongs in release
identity before any new builder repeats the pin; re-cut the ICPSR release as a **complete release
whose declared scope is the verified subset** — the bundle already records
`membershipCompleteForVerifiedSubset: true`, but the projection collapses
it to partial membership, which the Rulespec profile bars from backing
`ConceptMapping` endpoint pins (the 119 existing mappings remain
conforming atlas `searchOnly` output meanwhile); and add positive
fixtures for accepted assignments and reviewed mappings, which have zero
real rows on any path.

Promotion obeys one invalidation chain, stated once:

```text
source distribution → managed release → frontier → candidates →
qualification → atlas identity → projections → evaluation → deployment
```

A change at any link invalidates everything downstream. Qualification is
rerun or explicitly carried forward, never silently inherited, and a
changed atlas requires a new publication decision before any redeployment.

## 10. Evaluation gates before any ring change matters

Ring assignments authorize nothing by themselves. Before a ring-1 module's
concepts become candidate-eligible in the tagging product, and before the
frontier's decoy value is claimed:

- a per-source-family holdout (matrix rule 10), stratified by document
  type, scored with candidate recall before reranking, concept-level vs
  exact-string agreement separated, abstention correctness, and
  unsupported-label rate;
- a Y/I/N human review pass over a stratified document sample — each
  predicted concept graded correct / technically-valid-but-irrelevant /
  incorrect, the LLMs4Subjects librarian protocol (122 records in the
  original) — because near-synonym crowding is invisible to every other
  metric;
- for the frontier specifically: measure whether decoy presence reduces
  wrong-concept emissions on off-domain text against a frontier-less
  control. No published system has run this ablation; it is one of the
  synthesis's verified gaps, so the result is worth recording either way;
- for ring-2 register bridges specifically: the native metric is
  query-side, not tagging-side — document recall on public-register
  queries with mapped expansion on vs off. Label-equality mappings expand
  little that a lexical index lacks, so report the differing-surface-form
  mapping classes separately: that is where the bridging value
  concentrates, and it is the evidence that would justify deepening a
  bridge beyond the easy diagonal. Protocol v2's typed relations widen
  that evidence class: hierarchical and associative adjudications
  (`broadMatch`, `narrowMatch`, `adjudicatedRelation` annotations) are
  precisely the non-equality structure a register bridge exists to carry.

Seven competency questions serve as standing cross-repository acceptance
tests:

1. **Traceability** — a query-expanded result identifies its source and
   target releases, mapping assertion, candidate, validator receipts,
   retrieval policy, projection, and index build.
2. **Non-escalation** — a `searchOnly` mapping provably influenced
   retrieval without ever becoming an accepted subject assignment.
3. **Scoped completeness** — a frontier concept states its selection
   reason, source-coverage status, and any hierarchy omitted at the
   boundary.
4. **Conflict preservation** — two bundles asserting different relations
   for one pair coexist without consolidation.
5. **Historical reconstruction** — an as-of date plus a deployment
   identifier reconstructs the complete knowledge and policy state
   byte-for-byte.
6. **Projection conservativity** — the declared consumer query set returns
   identical answers from a projection and its parent.
7. **Concept evolution** — split, merged, or deprecated concepts keep
   historical assignments on their original identity while current
   retrieval follows the lifecycle policy.

## 11. Explicitly out of scope

- Document-side observations, routes, and tagging decisions (moved to
  SpicySearch at the product split; the v5 document layer stays retired).
- Any live database as the artifact of record (Oxigraph/Ladybug remain
  disposable read models behind their unmet adoption gates).
- Vocabulary induction (per the synthesis: unstable, lexically disjoint;
  revisit only after measured recurring gaps in the ring-0 core).
- The sibling reference publications' internals (§3 ring 3): the entity
  spine and the legal identity graph's typed-edge model each need their own
  proposal; the atlas only promises never to absorb them, and the addendum
  (B5) records their owners and priority.

## 12. Open questions

1. Should the hub spoke (×LCSH) run at all before two or three ring-1
   modules are in and the emit spoke is proven? Deferring it costs nothing
   today.
2. Frontier hierarchy-context depth (§4 rule 3): 1 step or 2? Decide with
   the §7 hierarchy-arm experiment rather than by taste.
3. Does `publisherAsserted` evidence require its own two-machine
   verification pass, or is pinned source bytes sufficient? (Proposed:
   pinned bytes suffice for `searchOnly`; anything stronger goes through
   `humanReviewed`.)
