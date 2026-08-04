<!-- markdownlint-disable MD013 -->

# Vocabulary Atlas Design Proposal — from three sources to the full registry

> **Status:** Revised proposed design; not adopted
>
> **Revision (2026-08-04):** The ring model is restated. Rings name
> semantic kinds — subject, entity, value, and legalIdentity — never
> eligibility. The former ring 0/1/2 become subject-ring participation
> classes (`core`, `specialist`, and `bridge`); the former ring 3 dissolves
> into the non-subject rings. All four rings share one concept, release,
> evidence, mapping-assertion, and lifecycle foundation, with ring-specific
> predicates and safety rules. Useful source terms carry source-scoped
> concept identity under §3. For subject emission, a pinned
> `SubjectEmissionPolicy` records eligibility and an active `OutputProfile`
> that names that exact policy grants product permission. This
> revision amends the synthesis's §5 planning classes, §11 CRS ruling, and
> separate-publication boundary; the evidence machinery remains.
>
> **Standing:** Rules and structure are this document's durable content.
> Counts and build references are dated snapshots of an artifact set in
> motion; `output/` is a workbench, and decision ceremony binds at
> publication boundaries — when an artifact ships to a consumer — never to
> experimental runs.
>
> **Date:** 2026-08-03
>
> **Prior synthesis:** [Vocabulary Atlas Final Synthesis](vocabulary-atlas-final-synthesis-2026-08-03.md)
> resolves the original review findings. This revision supersedes its planning
> classes, CRS identity ruling, and separate-publication boundary; its
> verified evidence and unaffected decisions remain useful.
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

The registry now contains 75 substantive modules — 54 source modules plus
21 adapters, shared infrastructure modules, managed-release builders, and
packages — spanning six groups:
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

1. **Semantic collapse.** Code values, entities, legal identities, and
   subjects need different predicates and output rules. Treating them as one
   untyped subject scheme makes a subject match look like entity identity and
   lets label equality erase distinctions the source made.
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

This proposal keeps the atlas a reproducible publication rather than a live
database. It expands the publication model to absorb the registry through
four semantic rings, a two-tier subject atlas, source-scoped concept identity,
ring-specific relations, a frontier rule for oversized mapping references,
typed mapping evidence, a hub-and-spoke qualification plan, and an explicit
ladder from registry reader to atlas member.

## 2. Design principles (inherited, then new)

Unchanged from atlas 1.0 and the catalog:

- The atlas is a publication format. Concept identity is never minted
  silently: a source-scoped concept exists only under a named minting rule
  with a pinned capture (§3), publisher identity is never fabricated, and
  every membership claim names one exact release.
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
- **Map wide, emit narrow.** The subject ring holds a wide mapping tier and
  a curated emit tier. Identity and mapping access do not authorize emitted
  subject assignments.
- **One foundation, four meanings.** Every concept belongs to exactly one
  semantic ring — subject, entity, value, or legalIdentity. All rings use the
  same source identity, release membership, provenance, evidence,
  mapping-assertion, and lifecycle shapes. Each ring defines its own relation
  vocabulary and checks: a subject `skos:exactMatch` never asserts identity,
  an entity link never follows from name equality, and a value crosswalk
  records edition and effective time. Product policy activates each use.
- **Bounded subsets are first-class.** A release fact set may be a declared,
  coverage-accounted subset of an oversized source (the LCSH reader already
  works this way). Selection policy is part of release identity.
- **Mapping evidence is typed by origin.** Machine-qualified is one origin
  among several; publisher-asserted and operator-adopted evidence get honest
  slots instead of being forced into `aiModel`/`humanAsserted`.

## 3. The ring model

Rings are semantic kinds, not eligibility tiers. Each concept belongs to
exactly one ring — **subject**, **entity**, **value**, or **legalIdentity** —
recorded in the portfolio index as a non-authorizing planning fact. A source
may contribute separate concepts or releases to more than one ring. A ring
identifies meaning; it never grants or withholds a use, and rings never become
atlas permission fields. For subject emission, a pinned
`SubjectEmissionPolicy` records the eligible exact release, admission review,
concept, and use; an active `OutputProfile` that names that exact policy grants
enrichment permission. The pinned retrieval policy separately controls search.

All four rings share one foundation: source-scoped concept identity,
content-derived releases, exact membership, provenance, rights, evidence
classes, mapping assertions, and lifecycle records. They do not share an
undifferentiated relation vocabulary or candidate pool. Subject mappings,
entity identity links, value-set crosswalks, and legal-identity edges retain
their own predicates and checks.

Three further rules complete the model:

- **The subject ring is a two-tier atlas.** Its wide mapping tier contains
  pinned source releases, bridges, decoys, and staged proposals. Its
  curated emit tier contains only concepts admitted by named review against
  an exact release. The `core`, `specialist`, and `bridge` participation
  classes describe how a subject release may contribute; a subject source may
  have no participation class while it remains evidence-only. Participation
  is planning metadata, not permission. For emission, a pinned
  `SubjectEmissionPolicy` establishes eligibility and a matching active
  `OutputProfile` grants permission; a retrieval policy separately activates
  search use.
- **Source identity is explicit and source-scoped.** Every useful enumerated
  source term has concept identity. Preserve a stable
  publisher concept IRI when one exists. Otherwise RefSpec mints an IRI from
  the source namespace and a durable source record key, such as a reconciled
  UUIDv7 `localRecordId`; it never mints identity from label equality. Each
  release names the exact source capture and minting rule. Renames, splits,
  and merges become reviewed lifecycle events. A RefSpec-issued source
  identity names RefSpec as issuer and the publisher scheme as source; it
  neither impersonates the publisher nor creates an `rkaf:LocalConcept`.
- **Identity, admission, and assignment are independent.** A named review may
  admit an existing source-scoped subject concept to the curated emit tier
  without minting another concept. A pinned `SubjectEmissionPolicy` must then
  select that exact review and release, and a matching active `OutputProfile`
  must grant emission. Concept staging creates genuinely new
  RefSpec-authored concepts, including deliberate consolidations or splits
  that cite source concepts. A document's use of a subject concept is
  `sourceAssignedEvidence`. Source assignment, provenance, rights, intended
  use, admission, and publication status are metadata — not rings or
  destinations.

### Subject ring — core participation

The default candidate pool for subject assignments in a named product
configuration. Product use still resolves through a pinned
`SubjectEmissionPolicy` and a matching active `OutputProfile`.

| Source | Reader | Basis |
| --- | --- | --- |
| Federal Register Thesaurus 2025 | `federal_register_thesaurus_2025*` (managed release, in atlas) | Purpose-built for the corpus; 1 CFR 18.20 |

**CRS enters the shared foundation immediately as source-scoped concepts.**
Congress.gov identifies CRS terms only by `name`; publisher identifiers are
absent, so RefSpec does not claim publisher-issued term identity
(`crs_legislative_resources` records both facts). Topical Legislative Subject
Terms and Policy Areas enter the subject ring. The Legislative Subject Terms
source also contains `geographicEntity` and `organizationName` records; those
enter the entity ring instead of competing with subjects. Every term receives
one source-scoped identity under the §3 rule. A document's use of one is
`sourceAssignedEvidence` — like CFR List of Subjects literals, which resolve
against the FR Thesaurus through the Lists-of-Subjects policy
(`policies/federal_register_lists_of_subjects`:
`officialTerm` / `recognizedVariant` / `sourceLocalOpenTerm` /
`unresolved`). A named admission review may approve an existing CRS subject
identity for the curated emit tier after its definition, hierarchy placement,
reviewer, and exact release pass the §10 gates. A pinned
`SubjectEmissionPolicy` records eligibility for that exact review and release;
a matching active `OutputProfile` grants emission permission. Concept staging
applies only when RefSpec creates a genuinely new concept rather than admitting
the source concept itself (addendum B4; spec §12.4).

The CRS packages still need stable operational handles. Each source fetch
records an RFC 9562 UUIDv7 `sourceFetchId` plus `sourceObservedAt`; the combined
package records a separate UUIDv7 `registrationEvent`. Every first-seen row gets
a UUIDv7 `localRecordId`, and the row's source-scoped concept IRI derives
from it — never from a label. These are RefSpec-scoped identities, not CRS
term identities: the concept record names RefSpec as issuing authority and
the LoC scheme as source. Each immutable ledger directory saves both complete
packages, both sorted local-ID and record-content digests, and the
reconciliation or human review. On refresh, a unique publisher identifier
match wins; otherwise a unique exact scheme/category/label match carries the
local ID forward. Any capture-independent content change writes a
reconciliation report and blocks publication of the reconciled source-concept
release until human review;
similarity may suggest a match but never decides one. A source-byte change
with identical parsed records is retained as a source-only change and does not
create false term churn. Target core size stays in the low thousands,
consistent with the EuroVoc anchor and the architecture proposal's
1,000–3,000 starting range.

### Subject ring — specialist participation (conditionally candidate-eligible)

Activated per document from evidence, never as a hard filter. Each module
needs its own adoption gate (catalog §Adoption gates) and holdout before its
concepts are candidate-eligible anywhere.

| Source | Reader | Catalog decision |
| --- | --- | --- |
| MeSH descriptors (not SCRs) | `mesh_descriptors` | Pilot |
| NALT Core | `nalt_core` | Pilot after license reconciliation |
| GEMET | `gemet_thesaurus` | Pilot with strong abstention |
| NASA Thesaurus | `nasa_thesaurus` | Candidate after freshness check |

### Subject ring — bridge participation (searchOnly forever)

Never candidate-authorized. The bridge participation class is not a junk drawer of
references: each
vocabulary here bridges a different language community's **register** into
the core. The Federal Register core speaks administrative supply-side
language ("Incorporation by reference"); users and researchers speak other
registers ("food insecurity", "recidivism"). A qualified `searchOnly`
mapping lets a query phrased in one register reach documents indexed in
another — connect and expand, never tag. Bridge releases also absorb
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

### Entity, value, and legalIdentity rings

The three non-subject rings share the atlas foundation and keep ring-specific
semantics:

- **Entity** holds organizations, people, places, substances, and other
  identifiable things. Entity links require identifiers or reviewed evidence;
  name equality never merges nodes.
- **Value** holds code lists, classifications, statuses, genres, actions, and
  native controls. Crosswalks name the source edition, target edition, and
  effective time.
- **LegalIdentity** holds legal instruments, structures, citations, dockets,
  RINs, and related identifiers. Its edges use legal predicates such as
  *cites*, *amends*, *authorizes*, and *implements* with point-in-time scope.

These rings cover roughly half the registry: NAICS/PSC, TAS/FAST Book, OMB
A-11, GSDM, BILLSTATUS, FEC, FCC ECFS, FERC, NRC ADAMS, SEC series,
nature-of-suit, SCOTUS opinion types, oversight report types, Grants.gov and
SAM controls, Census, OPM, NPPES NPI, UEI/CAGE, EPA SRS, federal hierarchy
organizations, Regulations.gov, Unified Agenda, OIRA, and PRA controls.
Publisher topic labels such as CBO, GAO, CRS product topics, LDA issue codes,
and Grants.gov funding categories belong to the subject ring even when their
document assignments arrive through the same source package as value data.

Physical ring publications and projections remain useful for scale,
independent verification, and consumer-specific reads. They implement one
shared record foundation rather than creating separate identity systems:

| Ring publication | Contents (readers) | Ring-specific semantics | Status |
| --- | --- | --- | --- |
| **Entity spine** | agencies (`federal_hierarchy_orgs`), award entities (`uei_cage_identifiers`), committees (`fec_committee_codes`), providers (`nppes_npi_identifiers`), substances (`epa_srs_substances`), courts (`courtlistener_codes`), geography identifier grammar (`census_geo_codes`) | Nodes carry typed identifier sets. Identity links use the shared evidence- and mapping-assertion shapes with entity-specific predicates and merge checks — publisher-asserted crosswalks (SAM's own UEI↔CAGE), machine-suggested matches bound by an entity proof adapter, and human-reviewed merges. Name equality never merges entities. | Ring-specific relation and proof design unwritten; the shared foundation is fixed here (matrix `T3-04` anticipates it) |
| **Code ledgers** | NAICS/PSC, fiscal codes, filing types, genre and process values, all native controls, cross-state statistical crosswalks (`census_gov_finance_codes`) | Versioned value sets with effective dates; raw values preserved exactly; reviewed edition crosswalks only where needed (NAICS 2017→2022, nature-of-suit spelling canonicalization) | Essentially built (`source_controlled_resource`, `regulatory_native_controls`) |
| **Legal identity graph** | CFR structure, statutes and Public Laws, RINs, docket and bill identifiers, citations | Deterministic parsed identity; typed edges (*cites*, *amends*, *authorizes*, *implements*) with point-in-time versions — the ELI analogue | Half-built (identifiers and citations exist as fields; the typed-edge model needs design) |

A fourth category rides alongside the ledgers but is metadata, not a ring:
**source-assigned topic evidence** — GAO topic assignments, CBO topic
labels, CRS product topics, LDA issue codes, SAM mission/subject fields.
The labels are subject-ring terms and carry source-scoped concepts
(§3); the per-document assignments are captured as
`sourceAssignedEvidence` observations
(already in the bundle model), consumed by the pipeline, and — unlike codes
— may later earn small reviewed maps into core concepts through §6's
evidence classes, letting a publisher's own assignment corroborate a
core-subject tag.

The atlas identifies one four-ring scope from exact ring releases.
Consumers may read a ring projection or compose several rings without
inventing identity, provenance, evidence, or lifecycle rules. Trust remains a
property of each record's origin, basis, attestation, and adoption; it does
not require a separate foundation for each ring.

One boundary clarified here because it is easy to misread: DNB's lesson —
entities missing from consideration can force a classifier to snap onto a
wrong subject — does not justify a mixed mapping pool. The pipeline searches
ring-scoped indexes in parallel. A strong entity result may supply abstention
evidence against a subject result, but it never becomes a subject candidate or
mapping assertion. The shared foundation makes the records comparable without
collapsing their relation vocabularies.

A one-page **atlas index** (an extension of `portfolio/resource-catalog`)
names every registry source, its semantic ring, its subject participation
class where one applies, its intended uses, and its promotion status. The
index prevents "the atlas" from silently meaning "everything." Publication
destination is derivable from ring and participation, and source assignment
is an intended use, never a destination. The ring tables in this section are
illustrative; the index is the exhaustive assignment of record. Index
versions are immutable: a failed experiment
produces a new version marking the row `deferred` or `rejected` with the
evaluation attached — history is never deleted. Row status draws from a
closed, machine-validated vocabulary (`planned`, `deferred`, `rejected`,
`superseded`, `unassessed`, `notApplicable`). The ring is a semantic fact;
participation and status are planning facts. Only a product policy activates
a use.

**Ring semantics must be checkable against reader evidence.** Extend the
shared `ResourceUse` vocabulary with factual uses such as
`mappingReference`, `candidateGeneration`, and `deterministicMetadata`.
The atlas index reconciles each reader's declared facet and intended uses
against its semantic ring and subject participation class. A mismatch fails
the build.

Source packages carry no permission-shaped fields. Remove
`candidate_use_authorized` rather than making it optional or assigning false
outside the subject ring. A source capture reports what the publisher data is
and how RefSpec can process it. For subject emission, a pinned
`SubjectEmissionPolicy` records eligibility and an active `OutputProfile` that
names that exact policy grants permission; the pinned retrieval policy
separately grants search use. This leaves one permission source per product
action and one clean source-package shape.

## 4. Membership rule for oversized bridge sources: the mapping frontier

Full ingestion of LCSH or FAST is prohibited by scale and pointless by use.
Instead, a bridge release entering the atlas is a **frontier subset** whose
selection policy is declared in the release and whose coverage is accounted
(`source_observed_count` and `excluded_count` exist today in the
source-capture bundle model; the frontier compiler carries the same
accounting into the managed-release layer, where it does not yet exist).
A bridge concept belongs to the frontier when it:

1. matches a selection predicate against core and specialist concepts (lexical and
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

Label-cluster policy changes with the participation classes: clusters are
computed only
between core and specialist schemes and the frontier — never bridge ×
bridge — and are
dropped from the default consumer projection (in the superseded two-edition
build, clusters were 69% of bytes with nothing reading them; the
`consumer-read-closure` projection already excludes them).

## 5. Crosswalk topology: hub-and-spoke, not pairwise

Qualification runs are scheduled on two spokes only:

- **Emit spoke:** every specialist and bridge release × the core. This is
  the only crosswalk the tagging product consumes.
- **Hub spoke (optional, staged):** specialist and bridge releases × the
  LCSH frontier.
  LCSH is the de facto hub of the library vocabulary world — FAST is derived
  from it and published LCSH↔MeSH alignments exist — so one hub spoke buys
  transitive discovery without O(N²) direct pairs.

The product's emit spoke never requires bridge × bridge qualification, and
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

Format 1.1 therefore adds explicit origin classes, each with a safety ceiling
that limits what an exact product policy may select:

| Class | Origin / basis | Ceiling | Example |
| --- | --- | --- | --- |
| `machineQualified` | subject-only `CrosswalkBundle` v2 proof derived from one exact candidate, its selected sealed question, every supporting validation, and an independent-validator witness | `searchOnly` | current qualified subject mappings |
| `machineReviewed` (candidate provenance, not mapping support) | one deterministic supporting `CrosswalkBundle` v2 validation and its verdict-derived relation | n/a until directly adopted | ICPSR interim reviews |
| `publisherAsserted` | `rkaf:imported` / `rkaf:sourceExplicit`, pinned source bytes | `searchOnly` | FAST→LCSH derivation; MeSH↔LCSH published alignments |
| `operatorAdopted` | named operator directly adopts one `machineReviewed` fact; adoption chains are forbidden | `localOperationalUse`, never atlas-qualified | ICPSR bridge v2 |
| `humanReviewed` | named reviewer, evidence reference | may support a policy choice beyond `searchOnly` after the named governance gates pass | zero rows today; fixtures required |
| `ruleGenerated` (candidate provenance, not a mapping class) | deterministic generator, honest `generatorKind` | n/a | current lexical candidate generator |

These classes are immutable `EvidenceAssertion` record shapes. Mapping
publications still use the applicable Rulespec origin and basis values; the
classes do not mint replacement mapping-origin literals. Operator adoption
adds a separate record without rewriting machine provenance, so an operator
can adopt a single-model review without mislabeling where the judgment came
from.

All rings use the shared content-derived `MachineEvidenceProof` pin shape and
the `RelationMachineProofSource` adapter interface. RefSpec code must register
an exact adapter class as trusted executable authority; input data cannot
register an adapter, and subclasses do not inherit trust. Each proof pin names
its registered `proofAdapter`, and the bundle independently matches the pin's
file digest to the adapter's reopened source bytes. The shared fields bind the
ring, evidence class, candidate, validation receipts, endpoint concepts and
releases, relation, complete ring-specific context such as value effective
dates, qualification policy when applicable, and exact source digests.
`proofKind` and `proofDetails` remain adapter-defined so adding a ring registers
new executable proof logic without changing the relation-bundle record shape.

The current Crosswalk proof adapter is deliberately subject-only. A
path-backed `PinnedCrosswalkMachineProof` reopens one exact `CrosswalkBundle`
v2 and derives either a qualification fact or one supporting-review fact. Its
content-derived pin travels with the relation bundle. `machineQualified`
evidence repeats the exact candidate, oriented endpoints and releases,
verdict-derived relation, and every supporting validation in the selected
sealed-question group; bundle validation requires exact equality with the
reopened proof. The proof pin itself carries the derived proof kind and
qualification policy.

**The gate owns the relation.** The candidate's `atlas:proposedRelation`
stays uniformly `skos:closeMatch` — the hypothesis under test, never the
answer. Gate protocol v2's direction-pinned verdicts (`same` →
`skos:exactMatch`, `near_same` → `skos:closeMatch`, `target_is_broader` →
`skos:broadMatch`, `target_is_narrower` → `skos:narrowMatch`, `related` →
`skos:relatedMatch`) make a qualified mapping a joint
relation-plus-safety judgment. The agreement rule folds the **set**
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

**Proof kind is derived, never supplied.** The subject adapter derives
`crosswalkV2IndependentValidations` for `machineQualified` evidence and
`crosswalkV2SingleMachineReview` for a `machineReviewed` fact. Callers supply
no `proofStatus`. No signed proof kind exists until RefSpec can reopen signed
receipts and validate them against an independently pinned qualification-
authority policy. Profiles still compose rather than supersede: a mapping may
accumulate machine qualification and human review, while a separate direct
adoption can authorize the reviewed candidate for local operational use.

**The atlas preserves assertions, not one mapping truth per pair.**
Contradictory relations between the same endpoints coexist as separate
records, each with its own origin, evidence, policy, and lifecycle; no bundle
overwrites an earlier assertion. An adoption targets exactly one
`machineReviewed` assertion IRI; it never targets an endpoint pair or another
adoption. A consumer may derive a "best mapping" view, but that view is
disposable and retains links to every contributing assertion.

No evidence class authorizes emit-side use. `humanReviewed` is the only class
that may satisfy a governance gate above the `searchOnly` ceiling; an exact
product policy still activates the use.

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
   Until that verifier exists, the shared foundation accepts no signed proof
   kind.
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

One canonical atlas scope names the exact concept releases and relation
artifacts used across all four rings. The durable bytes may be partitioned by
ring, but every partition uses the shared identity, release, evidence,
mapping-assertion, and lifecycle shapes from §3. Ring-specific validators
enforce predicate semantics. Subject mapping artifacts still require both
endpoints in complete subject releases; entity, value, and legalIdentity
relations apply their own closure rules.

Consumers receive only the projections they need. The distribution
measurement showed that the full subject artifact cost 4.5–5× the bytes for
zero additional consumer reads and opened more slowly. Named projection
policies include:

- `consumer-read-closure` (exists) — the tagging consumer's contract.
- `ring:<semantic-ring>` (new) — one complete ring-specific read view.
- `module:<specialist-source>` (new) — one specialist module + the core +
  their qualified mappings, for domain-scoped deployments.
- `explorer` (exists via bounded publication view).

SSSOM export is an interoperability surface for subject mappings and value
crosswalks, not a universal serialization for all four rings. Entity identity
links and legal-identity edges use their ring-specific distributions unless a
later ring design defines a semantically valid SSSOM profile for them. Each
eligible subject or value bundle exports with row-level `mapping_source`,
edition-scoped prefixes, and no `confidence` column. Origin classes do **not**
mint nonstandard `mapping_justification` values: justifications stay standard
`semapv`.

Candidate identity and mapping-assertion identity stay distinct: every
exported closed mapping-assertion row's `see_also` resolves to exactly one
content-derived mapping-assertion IRI. A raw rejected or otherwise unasserted
candidate never exports as an SSSOM mapping row. A candidate that a named
operator directly adopts may support a closed mapping assertion; that adopted
assertion can export, while the sidecar preserves its `operatorAdopted` origin,
underlying `machineReviewed` fact, and `localOperationalUse` ceiling. For a
subject `machineQualified` row, the sidecar carries the candidate IRI, exact
Crosswalk v2 proof pin, every supporting validation receipt in the selected
sealed-question group, and use ceiling. The proof pin is the sole authority for
the derived proof kind and qualification policy. Raw candidates use a separate
candidate-evidence representation. The SSSOM file and its sidecar publish as
one digest-pinned distribution whose manifest states that SSSOM rows are
interoperability views and proof facts come from the pinned machine proof —
product use requires the sidecar and the product's own policy.

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
curated core plus whatever has passed the §9 ladder — today, nothing else.
ELSST and ICPSR enter a product scope through the same gates as any
promotion; membership in bench builds grandfathers nothing, and "in the
atlas" without a scope qualifier means the bench.

## 9. The promotion ladder

The portfolio catalog's statuses become the single ladder from "reader
exists" to "in the atlas," aligned with the catalog's adoption gates:

```text
inventoryOnly → evidenceOnly → verifiedDistribution → source concept release
→ semantic ring → relation review
→ subject participation and curated admission → product policy
```

The implemented artifacts cover evidence, verified distributions,
source-concept releases, ring placement, shared relation bundles, and
subject admission for both source-scoped concepts and RefSpec-authored
`rkaf:LocalConcept` members of exact managed releases. One discriminated
`subjectConceptRelease` pin preserves the original identity and release
authority on both paths. Managed admission requires complete membership, a
pinned subject-ring assignment, and rights metadata bound to the exact
Rulespec graph; the release or a mapping alone admits nothing. Entity and
legal-identity review designs remain unwritten. For subject emission, a pinned
`SubjectEmissionPolicy` records eligibility and an active `OutputProfile` that
names that exact policy grants permission; retrieval policy separately grants
search use.
Proposed order of the next work:

1. **CRS Legislative Subject Terms + Policy Areas → source-scoped concept
   releases by semantic kind.** Publisher identifiers are absent. RefSpec
   mints identities from the UUIDv7 capture ledger (§3): topical subjects and
   Policy Areas enter subject releases; geographic and organization terms
   enter an entity release. CRS assignments flow as evidence on the records
   that carry them.
   Operate the ledger and resolve any changed-capture reconciliation
   before use. A named review may admit the existing CRS subject identities
   to the curated emit tier. Concept staging applies only when RefSpec authors
   a new concept (addendum B4).
2. **MeSH descriptors → specialist pilot** (largest, best-governed specialist
   module; activation evidence is plentiful in health-related sources).
3. **LCSH topical frontier → bridge hub**, compiled with the §4 two-pass
   build against the core plus MeSH.
4. **FAST topical → bridge** via `publisherAsserted` derivation edges to the
   LCSH frontier — the cheapest crosswalk in the whole plan; no model calls.
   Prerequisite: the current `fast_topical` reader consumes CSV without
   `sameAs` capture, while the derivation edges live in FAST's per-term RDF
   (`schema:sameAs` → LCSH); the reader must ingest that form first.
5. **GEMET, NALT Core, NASA, EuroVoc → specialist/bridge** as their license and
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

## 10. Evaluation gates before participation or product admission

Ring and participation assignments authorize nothing by themselves. Before
a specialist module's
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
- for bridge vocabularies specifically: the native metric is
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
  revisit only after measured recurring gaps in the curated core).
- The detailed entity-link, value-crosswalk, and legal-edge vocabularies.
  Each needs its own ring-specific design, but every design must use §3's
  shared foundation rather than establish another identity system.

## 12. Open questions

1. Should the hub spoke (×LCSH) run at all before two or three specialist
   modules are in and the emit spoke is proven? Deferring it costs nothing
   today.
2. Frontier hierarchy-context depth (§4 rule 3): 1 step or 2? Decide with
   the §7 hierarchy-arm experiment rather than by taste.
3. Does `publisherAsserted` evidence require its own two-machine
   verification pass, or is pinned source bytes sufficient? (Proposed:
   pinned bytes suffice for `searchOnly`; anything stronger goes through
   `humanReviewed`.)
