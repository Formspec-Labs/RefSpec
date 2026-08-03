<!-- markdownlint-disable MD013 -->

# Vocabulary Atlas Design Proposal — from three sources to the full registry

> **Status:** Proposed design; not adopted
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
Three vocabularies are in it (Federal Register Thesaurus 2025, ELSST, ICPSR),
producing 929,327 quads and 121 qualified mappings.

The registry now contains roughly 75 readers spanning the catalog's five
resource kinds: subject thesauri (LCSH topical, FAST topical, MeSH
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
2. **Scale.** Label clusters are already 69% of atlas bytes and no consumer
   reads them. LCSH topical is hundreds of thousands of headings; FAST
   topical is 440,599. Full ingestion multiplies the unread majority and the
   R6-only experiment showed edition restriction alone cut bytes 82.9%.
3. **Quadratic qualification.** Pairwise crosswalk qualification across N
   vocabularies is O(N²) pairs. Thirty sources ≈ 435 pairs. Cost is minor
   (the pilot ran a pair for $1.01) but review attention and gate weaknesses
   scale badly.
4. **Known gate and format defects.** Validator independence is evidenced,
   not enforced; the judge never sees hierarchy; 85% of qualified mappings
   are label equalities; the format has no honest slot for rule-based
   generation or operator-adopted review; the vendored consumer refuses new
   manifest fields; projection conformance fixtures do not exist.

This proposal keeps the atlas exactly what it is — a publication format, not
a second vocabulary model — and adds the structure needed to absorb the
registry: a ring model for membership, a frontier rule for oversized mapping
references, typed mapping-evidence classes, a hub-and-spoke qualification
plan, and an explicit ladder from registry reader to atlas member.

## 2. Design principles (inherited, then new)

Unchanged from atlas 1.0 and the catalog:

- The atlas is a publication format. No concept identity is minted; concepts
  stay in exactly one source release.
- Two named graphs split by **authority**: copied release facts vs
  replaceable analysis. Policies checked by exact equality.
- Equal labels are discovery hints (`atlas:LabelCluster`), never mappings.
- Human feedback is append-only and non-authorizing; machine agreement is
  not human review.
- Deterministic bytes: no blank nodes, sorted lines, independent SHA-256
  pins for manifest and quads.

New, motivated by the external-research synthesis and the registry's growth:

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
portfolio catalog and republished in the atlas manifest. Rings determine
what a release's facts may authorize — they are eligibility tiers, not
storage tiers.

### Ring 0 — emit core (candidate-authorized)

The only schemes whose concepts may be proposed as subject assignments.

| Source | Reader | Basis |
| --- | --- | --- |
| Federal Register Thesaurus 2025 | `federal_register_thesaurus_2025*` (managed release, in atlas) | Purpose-built for the corpus; 1 CFR 18.20 |
| CRS Legislative Subject Terms | `crs_legislative_resources` | Purpose-built legislative subjects (~1,004) |
| CRS Policy Areas | `crs_legislative_resources` | Broad navigation (32) |

CFR List of Subjects literals do not form a scheme; they resolve against the
FR Thesaurus via `federal_register_vocabulary_policy`
(`officialTerm` / `recognizedVariant` / `sourceLocalOpenTerm` /
`unresolved`) and enter as source-assigned evidence attached to ring-0
concepts. Target core size stays in the low thousands, consistent with the
EuroVoc anchor and the catalog's 1,000–3,000 starting range.

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
| EuroVoc | `eurovoc_thesaurus` | International/EU policy register; reader already refuses any use but `mappingReference` |
| AGROVOC | `agrovoc_thesaurus` | Multilingual agriculture register; crosswalk for NALT |
| ELSST (R6) | `elsst_*` (in atlas) | European social-science register |
| ICPSR subject thesaurus | `icpsr_*` (in atlas) | US social-science research register — the public/research phrasing of policy topics; `developmentOnly` marker republished (REF-009); FR×ICPSR crosswalk qualified 2026-08-03 (119 `searchOnly`) |
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
entity spine · code ledger · legal identity graph), and its promotion
status, so "the atlas" never silently comes to mean "everything." The ring
tables in this section are illustrative; the index is the exhaustive
assignment of record.

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
reader's own eligibility declaration can never silently disagree.

## 4. Membership rule for oversized ring-2 sources: the mapping frontier

Full ingestion of LCSH or FAST is prohibited by scale and pointless by use.
Instead, a ring-2 release entering the atlas is a **frontier subset**: a
bounded capture (the `lcsh_topical` reader's `max_records` streaming model,
generalized) whose selection policy is declared in the release and whose
coverage is accounted (`source_observed_count`, `excluded_count` already
exist in the bundle model).

A ring-2 concept qualifies for the frontier when it:

1. participates in a mapping candidate against a ring-0/1 concept
   (any candidate class, including negative controls);
2. is an endpoint of a publisher-asserted mapping (§6); or
3. lies within a declared small number of `skos:broader` steps of (1) or
   (2) — hierarchy context for judges and consumers, bounded and stated.

Everything else in the source stays out of the atlas and remains reachable
through the reader for future frontier growth. Frontier releases are
re-cut, not mutated: a new capture is a new release with its own pins.

Label-cluster policy changes with the rings: clusters are computed only
between ring-0/1 schemes and the frontier — never ring-2 × ring-2 — and are
dropped from the default consumer projection (the distribution measurement
showed 69% of current bytes are clusters nothing reads; the
`consumer-read-closure` projection already excludes them).

## 5. Crosswalk topology: hub-and-spoke, not pairwise

Qualification runs are scheduled on two spokes only:

- **Emit spoke:** every ring-1 and ring-2 release × the ring-0 core. This is
  the only crosswalk the tagging product consumes.
- **Hub spoke (optional, staged):** ring-1/2 releases × the LCSH frontier.
  LCSH is the de facto hub of the library vocabulary world — FAST is derived
  from it and published LCSH↔MeSH alignments exist — so one hub spoke buys
  transitive discovery without O(N²) direct pairs.

Ring-2 × ring-2 direct qualification is not scheduled at all. At pilot
economics ($1.01 and ~730 sealed calls per 365-candidate pair) the full
emit spoke for every current ring-1/2 source costs tens of dollars; the
binding constraint is gate quality, not budget, which is why §7 precedes
any scale-out.

Transitive claims across the hub (`A→LCSH→B`) are never materialized as
mappings; they may generate *candidates* for direct qualification, which is
exactly the discovery-hint role label clusters already play.

## 6. Typed mapping-evidence classes

The analysis graph currently admits one origin: machine-qualified
(`rkaf:aiSuggested` + `rkaf:statisticalInference`, two independent
validators, `searchOnly`). Two real cases already overflow this:

- The FR×ICPSR run was stopped by operator direction after 96/730 calls and
  its 122 single-model-reviewed pairs live in a development-only concept
  bridge that the bridge schema can only mislabel as
  `humanAsserted`/`editorialAssertion`.
- FAST records carry their LCSH source headings — publisher-asserted
  derivation edges that need no model calls at all — and the deterministic
  candidate generator itself is declared `aiModel` for lack of an honest
  value.

Format 1.1 therefore adds explicit origin classes, each with its own
eligibility ceiling:

| Class | Origin / basis | Ceiling | Example |
| --- | --- | --- | --- |
| `machineQualified` | `aiSuggested` / `statisticalInference`, two independent validators | `searchOnly` | current 121 FR×ELSST rows |
| `publisherAsserted` | `sourceAsserted` / `publisherRecord`, pinned source bytes | `searchOnly` | FAST→LCSH derivation; MeSH↔LCSH published alignments |
| `operatorAdopted` | single-machine review adopted by named operator | `localOperationalUse`, never atlas-qualified | ICPSR bridge v2 |
| `humanReviewed` | named reviewer, evidence reference | may exceed `searchOnly` per governance | zero rows today; fixtures required |
| `ruleGenerated` (candidate provenance, not a mapping class) | deterministic generator, honest `generatorKind` | n/a | current lexical candidate generator |

Nothing below `humanReviewed` ever authorizes emit-side use; that boundary
is the ring model restated at the mapping layer.

## 7. Qualification 1.1 — fix the gate before scaling it

Ordered prerequisites, all drawn from the pilot's own findings, before the
emit spoke runs at registry scale:

1. **Provider binding.** `endpointHost` sealing is evidence, not
   enforcement; the executed attack (two cosmetic families, one endpoint)
   still qualifies a mapping. Bind the provider IRI to something the
   producer cannot freely choose. This is a format change; do it in 1.1,
   not after 30 sources are in.
2. **Hierarchy arm.** Run the proposed A/B on the same candidate slice:
   label-only input vs input carrying ancestor labels (never a stated
   shared ancestor). Decide with data whether judges see hierarchy; today
   zero of 365 sealed inputs contain `broader` while the prompt asks a
   hierarchy question.
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
edition-scoped prefixes, and no `confidence` column; §6's origin classes map
to distinct `mapping_justification` values so downstream tools can filter
publisher-asserted from machine-qualified rows.

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

1. **CRS Legislative Subject Terms + Policy Areas → ring 0.** The emit core
   is incomplete without them, and every emit-spoke qualification run
   against an incomplete core is a run that gets redone.
2. **MeSH descriptors → ring 1 pilot** (largest, best-governed specialist
   module; activation evidence is plentiful in health-related sources).
3. **LCSH topical frontier → ring 2 hub**, cut against the completed ring-0
   core plus MeSH.
4. **FAST topical → ring 2** via `publisherAsserted` derivation edges to the
   LCSH frontier — the cheapest crosswalk in the whole plan; no model calls.
5. **GEMET, NALT Core, NASA, EuroVoc → rings 1/2** as their license and
   freshness gates clear.
6. **DOE OSTI, EPA EV** stay deferred per catalog until verifiable releases
   exist.

Also folded into the ladder, because they block trust in what ships:
resolve the ELSST schema-set-digest defect (a managed release currently
pins a digest that moves underneath it — decide whether that pin belongs in
release identity at all), and add positive fixtures for accepted
assignments and reviewed mappings, which have zero real rows on any path.

## 10. Evaluation gates before any ring change matters

Ring assignments authorize nothing by themselves. Before a ring-1 module's
concepts become candidate-eligible in the tagging product, and before the
frontier's decoy value is claimed:

- a stratified holdout per source family (matrix rule 10), scored with
  candidate recall before reranking, concept-level vs exact-string
  agreement separated, abstention correctness, and unsupported-label rate;
- a Y/I/N human review pass over a ~100–150 document sample (the TIB
  protocol), because near-synonym crowding is invisible to every other
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
  bridge beyond the easy diagonal.

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
4. Whether ring assignments live in the atlas manifest (format 1.1 field,
   consumer change) or only in the atlas index (no format change, weaker
   guarantee). Proposed: index first, manifest field when 1.1 ships for
   §7.5 reasons anyway.
