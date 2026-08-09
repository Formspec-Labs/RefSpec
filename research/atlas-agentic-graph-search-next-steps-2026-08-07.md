# Unapproved plan: Atlas work for safe agentic graph search

**Date:** 2026-08-07
**Last reviewed:** 2026-08-08

**Status:** **Unapproved plan.** This document records a proposal for review. It
does not approve implementation, change a binding or decision ledger, qualify a
mapping, publish a release, deploy a service, or enable graph expansion.
The `EuroVocOrganizationExperiment` described in Stage 2 has since been built and
verified locally as reversible experiment evidence. That implementation does not
approve this plan or resolve its downstream adoption gates.

> **Status annotation (2026-08-09, in place — nothing above is rewritten):**
> Stage 0 is closed and the direction is approved by REF-022 in
> [docs/decisions.md](../docs/decisions.md). The topology is fixed: RefSpec
> owns vocabulary, DocSpec owns files at scale, SpicySearch is the only
> junction and executes tagging there. DocSpec participates in the pilot —
> reversing the exclusion proposed below — mediated solely through
> SpicySearch; RefSpec and DocSpec share no direct edge. The experiment is
> registered in the experiment lane of the
> [managed-vocabulary experiment roadmap](../plans/managed-vocabulary-experiment-roadmap.md).
> Stage 1 is queued after the Atlas 1.0/2.0 retirement and rkaf adoption steps
> in [plans/refspec-on-rulespec.md](../plans/refspec-on-rulespec.md), with its
> consumer seam built as RuleSpec bridge contracts. Later-stage gates — hub
> choice, meta-subjects, any binding change — remain open by design.

**Decision owner:** The portfolio architecture owner, with separate acceptance
by the owners of each affected repository and decision ledger.

**Scope:** RefSpec and Vocabulary Atlas work needed to support a controlled
cross-product search experiment. SpicySearch remains the sole authority for
query planning, graph-use policy, ranking, explanations, and serving.

## Proposed direction

Do not add `Domain`, `SubjectArea`, or `MetaSubject` to the Atlas binding yet.
First make SpicySearch a verified Atlas 3.0 consumer with expansion disabled.
Then use the separately pinned `EuroVocOrganizationExperiment` source sidecar and
build a SpicySearch-owned evaluation bridge. Compare direct source concepts,
external hubs, publisher organization, locally
generated navigation groups, and a few reviewed meta-subjects. Consider a
binding change only after a new sealed evaluation demonstrates both semantic
fidelity and product value at an affordable governance cost.

This direction keeps the central choice open:

- reuse EuroVoc, FAST, LCSH, or another external vocabulary as an organizing or
  mapping hub;
- create Atlas navigation groups without creating shared identities;
- create a sparse Atlas meta-subject registry where a shared identity produces
  measured value; or
- use different answers in different subject areas.

## Practical answer: do we have enough data now?

**Yes for development; no for adoption.**

Atlas has enough data to verify a 3.0 consumer, reproduce publisher structure,
build candidate memberships, exercise typed graph paths, and run a visible
development comparison. It does not yet have enough independent evidence to
approve a general domain model, a generated subject taxonomy, Atlas-owned
meta-subjects, or production graph traversal.

| Evidence | Available now | What it can establish | What it cannot establish |
| --- | --- | --- | --- |
| Validator-conforming local Atlas 3.0 development distribution | Yes | Binding conformance, source closure, reproducible facts | Release acceptance, publication, or product use |
| EuroVoc 4.24 source organization | Yes; local sidecar built and verified | Publisher groups and concept membership | A local Atlas taxonomy or search benefit |
| EuroVoc-LCSH bindings | 2,003 typed mapping assertions | Evidence-bearing paths between two schemes | EuroVoc as a universal hub |
| Native-relation experiments | Yes | Candidate retrieval behavior and known relation gaps | Search or tagging improvement |
| SpicySearch `quality-v1` | 78 visible development queries in three matters | Plumbing, failure analysis, development comparisons | An unopened decision holdout |
| Publisher document assignments | One bounded GAO representation; broader work pending | Record shape and handoff design | Independent GAO/CBO search quality |
| Domain, navigation, and meta-subject stewardship evidence | No accepted operating model for those layers | Candidate review can be planned | Sustainable review, release, and retirement |

## Verified current state

### Atlas 3.0 is conformant and intentionally projection-free and derivation-free

The dated local development distribution at
[`output/atlas-3.0-full-2026-08-06/distribution`](../output/atlas-3.0-full-2026-08-06/distribution)
has an `atlas-acceptance.json` verdict of `passed`; all 11 recorded gates passed.
The manifest for that exact snapshot reports:

| Measure | Count |
| --- | ---: |
| Resources | 588,409 |
| Labels | 984,114 |
| Native relation assertions | 553,540 |
| Mapping assertions | 2,003 |
| Source assignments | 4,885 |
| Cross-ring relation assertions | 1 |
| Projected relations | 0 |
| Derived relations | 0 |

The zero projection and derivation counts are intentional. The producer check
requires "zero inferred mappings, projections, derived relations, and
supersession," and the full producer invokes graph construction with
`include_projection=False`
([producer](../tools/generate_atlas_v3_full.py),
[binding guide](../bindings/atlas/3.0/README.md)). The acceptance result proves
that these local bytes conform to Atlas 3.0. It does not prove that the
distribution is published, that SpicySearch consumes it, or that any relation
is safe for search.

This plan therefore does not try to "fix" the zero. A consumer may read the
canonical asserted RDF directly. If a compact direct view is needed, it must be
a deterministic, non-authoritative application view that pins the canonical
distribution. It must retain supporting assertion identifiers for relation,
mapping, and assignment rows, plus exact canonical RDF and source-record
provenance for resource and label rows, as required by
[REF-015](../docs/decisions.md).

### EuroVoc's organization is present in the source but incomplete in Atlas

A read-only inspection of the exact pinned EuroVoc 4.24 SKOS Core bytes found:

| Source feature | Count |
| --- | ---: |
| EuroVoc domain resources | 21 |
| Notated microthesaurus `skos:ConceptScheme` resources | 127 |
| Total concept schemes, including the main and domain schemes | 129 |
| Ordinary concepts | 7,515 |
| Concept-to-scheme `skos:inScheme` assertions for the 127 microthesauri | 7,902 |
| Microthesaurus memberships per ordinary concept | 1–4 |
| Concepts with no microthesaurus membership | 0 |

The current reader preserves the 129 concept schemes and 7,902 scheme
memberships, but `_domain_groups` recognizes only resources explicitly typed as
`eurovoc:MicroThesaurus` with an `euvoc:domain` link
([reader](../src/refspec/registry/eurovoc_thesaurus.py)). The pinned SKOS Core
file contains neither form, so the parsed `domain_groups` count is zero. The
normalizer emits the 21 domains and ordinary concepts but does not emit the 127
notated schemes or their memberships as first-class Atlas organization
([normalizer](../src/refspec/atlas/v3_registry_vocabularies.py)).

The four-digit microthesaurus notation begins with a two-digit domain code, but
the current pinned file does not assert that domain link. RefSpec must not call
a prefix-derived link a publisher assertion. The experiment should either pin a
richer official EuroVoc representation that carries the link or record the
notation rule as an operator-derived candidate and validate it against the
official 21-domain, 127-subdomain navigation. The [official EuroVoc service](https://op.europa.eu/en/web/eu-vocabularies/eurovoc)
and [EUR-Lex browser](https://eur-lex.europa.eu/browse/eurovoc.html) provide the
external comparison, but exact pinned source bytes remain the implementation
evidence.

### The product seam is not ready

SpicySearch's current plan still identifies Atlas 2.0 as its active intake,
keeps Atlas expansion `not_used`, and requires ranking-v4 provenance plus a
preregistered real-data improvement before activation
([SpicySearch plan](../../../spicysearch/PLAN.md),
[ranking-v4 design](../../../spicysearch/docs/ranking-v4-design.md)). The Atlas
3.0 consumer seam and per-result graph provenance therefore precede any useful
organization or meta-subject comparison.

## The four semantic objects

The proposal distinguishes four kinds of thing. Mappings and memberships are
evidence-bearing assertions between things; they are not a fifth kind of
concept.

| Object | Meaning | Authority | Examples |
| --- | --- | --- | --- |
| Publisher organizational object | A group exactly as a source publishes it | Publisher | EuroVoc domain `52 ENVIRONMENT`; EuroVoc microthesaurus `5216 deterioration of the environment` |
| Atlas navigation collection | An optional local grouping for browsing or planning; membership does not assert identity | Atlas, after review | Candidate `Chemical pollution`; candidate `Work arrangements` |
| Publisher source concept | A source-owned unit of meaning with its own identifier and history | Publisher | EuroVoc `chemical pollution`; EuroVoc `teleworking`; the corresponding FAST or LCSH records remain separate nodes |
| Atlas meta-subject | An optional shared Atlas identity with one reviewed scope | Atlas, after semantic and product gates | Candidate `Atlas PFAS`; candidate `Atlas Telework` |

The examples in both Atlas-created rows are hypothetical. They are not current
Atlas resources and this document does not authorize them.

[SKOS](https://www.w3.org/TR/skos-reference/) supports this separation: concepts,
concept schemes, collections, and mapping assertions have different meanings.
In particular, `skos:closeMatch` is not transitive, and broad, narrow, and
related mappings do not establish identity.

## Source roles: EuroVoc, LCSH, and FAST

FAST is derived from LCSH and reorganizes headings into facets, but it is not
merely a lossless "broken-down LCSH." OCLC publishes FAST as a distinct,
faceted authority with its own identifiers and maintenance
([OCLC FAST](https://www.oclc.org/research/areas/data-science/fast.html)).

| Source | Proposed Atlas role | What it does not replace |
| --- | --- | --- |
| EuroVoc | Preserve its concepts, organization, and direct versioned LCSH bindings; test its organization as one external anchor | US-specific vocabularies or Atlas identity |
| LCSH | Preserve a major library subject authority, publisher mappings, historic identifiers, and compound-heading provenance | FAST's faceted assignments or runtime convenience |
| FAST | Preserve a separate faceted source useful for retrieval and published links to LCSH | LCSH source identity, semantics, or provenance |
| Atlas meta-subject | Create only a few shared identities that pass independent semantic and product gates | Any publisher concept |

Adopting all of FAST would not remove Atlas's need for LCSH when documents,
publishers, or mappings use LCSH identifiers or heading semantics. Retaining all
of LCSH would not remove FAST's distinct faceted retrieval value. Atlas should
preserve both source boundaries; SpicySearch may choose a smaller indexed subset
under its own measured policy.

The current 2,003 EuroVoc-LCSH `skos:exactMatch` and `skos:closeMatch`
assertions provide typed, versioned paths between those schemes. They do not
show that EuroVoc is a global identity spine, and their predicate distinctions
must survive every view and evaluation.

## Atlas-specific work if this plan is approved

The immediate Atlas backlog is smaller than the full cross-product experiment:

1. Designate a sealed copy of the validator-conforming local 3.0 distribution as
   the exact experiment input. Record its manifest, canonical payload, binding,
   ontology, and asserted inventory digests in an out-of-band consumer input
   lock. This is an internal handoff, not release acceptance or publication.
2. Document and test that the current producer is intentionally projection-free
   and derivation-free so consumers do not treat zero projection as a failed
   build.
3. **Implemented locally:** preserve EuroVoc's 127 notated schemes and 7,902
   exact `skos:inScheme` assertions in a source-faithful
   `EuroVocOrganizationExperiment` sidecar. The artifact keeps 127
   notation-derived domain links in a separate candidate layer and preserves the
   unresolved publisher/acquisition date discrepancy.
4. Give a consumer either canonical RDF access or a deterministic view recipe
   with supporting identifiers for relation-like rows, exact canonical
   provenance for resource and label rows, and parity checks. Do this only after
   SpicySearch confirms the view solves a measured intake problem.
5. Complete relation-family precision and source-fidelity work, including
   `E-S1b`, before offering any non-identifier path for search evaluation.
6. Produce mapping, navigation-membership, and possible meta-subject candidates
   only in the experiment lane, with receipts and reviewer dispositions.

Atlas should not add more vocabulary volume, change the 3.0 binding, publish
benchmark fixtures, acquire document corpora, select search weights, or enable
traversal during this slice.

## Cross-product authority

The experiment must follow the existing ownership decisions in the
[RefSpec overview](../README.md), [RefSpec decision ledger](../docs/decisions.md),
[SpicyRegs overview](../../README.md), [Rulespec overview](../../../rulespec/README.md),
and [SpicySearch guidance](../../../spicysearch/AGENTS.md).

| Product | Owns in this experiment | Does not gain |
| --- | --- | --- |
| RefSpec / Atlas | Vocabulary capture, source-faithful normalization, mapping and organization candidates, qualifications, immutable Atlas releases, and view recipes | Search permission, document acquisition, query planning, or ranking |
| SpicyRegs | Publisher document capture, document identity, passages, and publisher topic observations in immutable `DocumentRelease` artifacts | Vocabulary identity or search policy |
| Rulespec Extrapolator | Evidence-bound derived `ConceptAssignment` candidates when interpretation or tagging is required | Publisher authority or runtime search permission |
| SpicySearch | Atlas 3.0 intake, the fixture bridge, agent planning, deterministic plan validation, runtime indexes, traversal policy, ranking, explanations, and evaluation | Authority to edit or promote Atlas facts |
| DocSpec | Excluded from the first pilot; a later accepted decision may use it as implementation infrastructure beneath the same owners | Semantic or source authority merely because it executes processing |

DocSpec's current platform specification is a draft, not an accepted transfer of
portfolio authority
([DocSpec draft](../../../DocSpec/docs/superpowers/specs/2026-08-05-docspec-standalone-platform-implementation-spec.md)).
If the pilot later uses DocSpec, it must distinguish a DocSpec processing or
catalog snapshot from the authoritative SpicyRegs `DocumentRelease` and record
that dependency in an accepted cross-product decision.

## Proposed execution sequence

Each stage has an explicit input, output, check, and stop condition. A failed
stage does not silently widen the next one.

### Stage 0 — Accept authority and experiment decisions

**Input:** Current repository ledgers, this proposal, and named stewards.

**Work:** Assign owners for source capture, vocabulary facts, derived tagging,
search evaluation, privacy, rights, and final acceptance. Decide whether the
first pilot excludes DocSpec, as proposed. Register the experiment under the
two-lane rules in the
[managed-vocabulary experiment roadmap](../plans/managed-vocabulary-experiment-roadmap.md).

**Output:** Accepted decisions in every affected authoritative ledger and one
responsibility matrix.

**Check:** No repository is assigned work outside its accepted boundary.

**Stop:** Do not start cross-product implementation without these decisions.

> **Resolution (2026-08-09):** Closed by REF-022. Ownership collapses to the
> single portfolio decision-maker with product-boundary roles: RefSpec owns
> vocabulary, DocSpec owns files at scale, SpicySearch owns indexing, tagging,
> and evaluation. The proposed DocSpec exclusion is reversed — DocSpec is in
> the pilot, used only through SpicySearch. The experiment is registered in the
> experiment lane. No responsibility matrix is produced: a seven-role matrix
> for one decision-maker is structure nothing reads (AGENTS.md rule). No
> Stage 0 questions remain open.

### Stage 1 — Build the Atlas 3.0 consumer seam with expansion off

**Input:** A sealed copy of the exact validator-conforming local Atlas 3.0
distribution. The current observed manifest-file SHA-256 is
`9b5d6392a993815070471734e8fea77f60e0973bdba6d05f66be11af805a1f24`;
it becomes trusted only when an approved handoff records it outside the copied
distribution.

> **Input annotation (2026-08-09):** That observed digest predates the Atlas
> 1.0/2.0 retirement and the digest-chain regeneration in `bd57d1f`; treat it
> as stale. Re-observe and re-seal the distribution when Stage 1 starts. Do
> not record the 2026-08-07 value as the trusted handoff.

**Work:** Add an independent SpicySearch Atlas 3.0 reader. Prefer direct reading
of canonical RDF. Add a compact `AtlasSearchView` only if measured consumer cost
justifies it.

`AtlasSearchView` is a working artifact label, not a proposed RDF class or an
accepted product name.

**Output:** A SpicySearch intake receipt, or a non-authoritative view manifest,
that pins:

- the Atlas root manifest and canonical payload digest;
- the asserted graph inventory digest;
- the binding and ontology digests;
- the derivation recipe and implementation version;
- every view member and digest;
- supporting Atlas assertion identifiers for relation, mapping, and assignment
  rows; and
- exact canonical RDF and source-record provenance for resource and label rows.

**Check:** Closed membership, tamper refusal, endpoint-release closure,
assertion-to-view parity, and byte-stable rebuild. Expansion remains disabled.
No JSONL view becomes a second canonical Atlas. SpicySearch must vendor or copy
the sealed input and verify it against its input lock; it must not consume the
mutable sibling `output/` path.

**Stop:** A parity failure blocks all graph arms but not the existing text
baseline.

### Stage 2 — Preserve publisher organization in a separate experiment

**Implementation status:** Built and verified locally. The validation receipt
passes ten checks and reconciles 21 domains, 127 microthesauri, 7,515 concepts,
and 7,902 memberships. The sidecar remains local, the `20260708`/`20260709`
lineage difference remains explicit, and no SpicySearch evaluation has run.

**Input:** One exact EuroVoc release plus a source-specific rights record.

**Work (implemented locally):** Emit a source sidecar named
`EuroVocOrganizationExperiment` that
preserves source objects and exact source assertions. Keep publisher facts
separate from Atlas-created candidates. This is not an `AtlasSearchView` because
the 127 schemes and memberships are not canonical Atlas 3.0 assertions.

A publisher object row must preserve at least:

```json
{
  "recordType": "publisherOrganizationObject",
  "sourceIri": "http://eurovoc.europa.eu/100244",
  "sourceTypes": ["http://www.w3.org/2004/02/skos/core#ConceptScheme"],
  "notation": "5216",
  "labels": [{"value": "5216 deterioration of the environment", "language": "en"}],
  "publisherDatasetIri": "http://eurovoc.europa.eu/void.ttl#dataset_eurovoc-20260709",
  "publisherVersion": "4.24",
  "publisherIssued": "2026-07-09",
  "publisherMetadataSourceIri": "http://eurovoc.europa.eu/void.ttl",
  "publisherMetadataArtifactDigest": "sha256:2c58402422f8588aada476f3516051e7fc980182130557a0d8c67497ffd8731d",
  "skosInputArtifactDigest": "sha256:91bdb24e833ba431707f3980a19f475434ea8dcddb2b4d5e32e79e9fc1a0ca2f",
  "normalizedPartitionIri": "http://publications.europa.eu/resource/dataset/eurovoc/20260708-0#thesaurus-concepts",
  "experimentRecord": "urn:ref:eurovoc-organization-experiment:source-record:..."
}
```

A publisher assertion row must preserve direction exactly:

```json
{
  "recordType": "publisherOrganizationAssertion",
  "sourceSubject": "http://eurovoc.europa.eu/2528",
  "sourcePredicate": "http://www.w3.org/2004/02/skos/core#inScheme",
  "sourceObject": "http://eurovoc.europa.eu/100244",
  "publisherDatasetIri": "http://eurovoc.europa.eu/void.ttl#dataset_eurovoc-20260709",
  "publisherMetadataSourceIri": "http://eurovoc.europa.eu/void.ttl",
  "publisherMetadataArtifactDigest": "sha256:2c58402422f8588aada476f3516051e7fc980182130557a0d8c67497ffd8731d",
  "skosInputArtifactDigest": "sha256:91bdb24e833ba431707f3980a19f475434ea8dcddb2b4d5e32e79e9fc1a0ca2f",
  "normalizedPartitionIri": "http://publications.europa.eu/resource/dataset/eurovoc/20260708-0#thesaurus-concepts",
  "experimentRecord": "urn:ref:eurovoc-organization-experiment:source-record:..."
}
```

The two identities above deliberately expose an unresolved provenance
discrepancy. RefSpec's pinned SKOS Core acquisition URL and normalized partition
use `20260708`, while the independently pinned publisher metadata identifies
EuroVoc 4.24 as `dataset_eurovoc-20260709`, issued 2026-07-09, and names
`20260709` distributions. Stage 2 must reconcile and test those identities. It
must not relabel the RefSpec partition as the publisher dataset or hide the
difference behind one `sourceRelease` field.

The experiment manifest must keep four identities separate: the publisher
dataset, the publisher distribution records named by its metadata, the exact
SKOS Core acquisition and digest, and RefSpec's normalized partition. Both the
metadata artifact and SKOS input are required evidence; neither digest can stand
in for the other.

An Atlas-generated group uses a separate record family with an Atlas identifier,
generation receipt, review disposition, validity, and change-event reference.
It never claims `authority: publisher`.

**Output:** A separately identified experiment manifest that pins the EuroVoc
metadata source and digest, SKOS input source and digest, parser and recipe
versions, every sidecar member and digest, publisher objects, exact publisher
assertions, source accounting, change events, and any separately named
operator-derived domain candidates.

**Check:** Reconcile 21 domains, 127 notated microthesauri, 7,515 concepts, and
7,902 microthesaurus memberships. Prove exact predicate direction and source
closure. Verify both input pins and reconcile the `20260708` acquisition with
the `20260709` publisher metadata before handoff. Compare two EuroVoc releases
before claiming lifecycle support. Record add, remove, replace, split, merge,
relabel, and reparent as events rather than states.

**Stop:** If a publisher relation is absent, preserve the absence. Do not
manufacture publisher confidence or silently infer a domain link from notation.
Do not mix this sidecar into an `AtlasSearchView` unless a later binding and
canonical Atlas release represent the source facts.

### Stage 3 — Build the evaluation bridge downstream

**Input:** The SpicySearch `quality-v1` manifest and the exact Atlas or view
digest.

**Work:** SpicySearch reviews every fixture concept identifier, including the
eight `terminology_entries`, against pinned Atlas source concepts. RefSpec may
provide candidates and assertion identifiers but does not publish product test
fixtures as Atlas facts.

**Output:** A SpicySearch-owned evaluation bridge pinned to both inputs. Each
fixture identifier has one resolution status: `resolved`, `ambiguous`,
`unmatched`, or `unresolved`. It also retains zero to many typed mapping
assertions, their directions and evidence, any selected evaluation target, and
the selection method. Exact, close, broader, narrower, related, and unusable
mappings remain assertions or reviewed candidates; they are not resolution
statuses and do not force a one-to-one target.

**Check:** Every mapping preserves predicate, direction, source release,
evidence, reviewer, method, and use disposition. Ambiguity and unselected or
unusable mappings remain visible; no meta-subject is minted to force coverage.

**Stop:** Unresolved rows remain unresolved and cannot be traversed.

The visible dataset contains 78 queries, 114 traditional-search variants, and
867 judgments. It is useful for development only
([dataset](../../../spicysearch/evaluation/core-query-catalog/quality-v1/README.md),
[manifest](../../../spicysearch/evaluation/core-query-catalog/quality-v1/manifest.json)).

### Stage 4 — Make ranking and explanations graph-ready

**Input:** Direct and expanded concept assignments, with Atlas assertion and
policy evidence.

**Work:** Complete ranking-v4 provenance before measuring a mapping arm. Direct
and expanded evidence must remain distinguishable at rank time.

**Output:** Search rows and explanations that retain, per result:

- the resolved user span or identifier and ambiguity outcome;
- the proposed and executed query plans;
- Atlas distribution/view, every contributing organization sidecar or external
  hub release and manifest digest, and the SpicySearch policy digest;
- the ordered path, including predicate, direction, assertion identifier,
  authority, qualification, semantic ring, cross-ring status, endpoint
  releases, and attenuation;
- the document assignment and supporting passage evidence;
- the graph-score contribution;
- eligible, visited, and truncated edge counts; and
- fallback, abstention, and missing-coverage status.

**Check:** Every top-ten graph explanation replays against pinned artifacts.
Removing a claimed hop removes or lowers its graph contribution. A result has no
graph explanation when traversal did not contribute to it. Graph evidence may
not move a result across a hard admission boundary.

**Stop:** Global run-level hop lists cannot substitute for per-result paths.

### Stage 5 — Obtain real publisher document evidence through the right owners

**Input:** Publisher-defined GAO and CBO source slices.

**Work:**

1. SpicyRegs captures complete declared slices and emits immutable document
   identities, passages, and publisher topic observations.
2. RefSpec resolves the publisher topic identifiers against pinned vocabulary
   releases and supplies qualified vocabulary evidence.
3. A Rulespec Extrapolator branch may emit evidence-bound assignments only when
   the task requires interpretation beyond a publisher observation. This branch
   remains stopped until an accepted decision assigns its baseline, selection,
   and profile-governance owners and a real, non-fixture
   `ExtrapolationRelease` producer exists.
4. SpicySearch joins the pinned releases and creates queries and relevance
   judgments independently of candidate generation.

**Output:** Separate, immutable releases with explicit dependency digests rather
than an Atlas-owned copy of GAO or CBO documents.

**Check:** Complete publisher-slice accounting, source identity, observation
dates, assignment provenance, concept coverage, and no inferred claim presented
as publisher-authored.

**Stop:** Sparse assignment frequencies block co-assignment claims. Document
co-occurrence remains candidate evidence, never publisher semantics.

An independent custodian must partition whole publishers, matters, or time
slices before navigation or mapping candidate generation. Candidate generation
may see only its declared development partition. Publisher assignments,
documents, queries, and judgments reserved for evaluation remain sealed and
cannot later score tagging or group quality if they helped induce the group.
The publisher-observation branch may proceed even if the optional inferred
tagging branch remains stopped.

This stage executes the intent of `E-S11`
([design](vocabulary-atlas-native-relation-experiment-designs-2026-08-06.md))
without moving document acquisition into RefSpec.

### Stage 6 — Generate bounded navigation candidates

**Input:** Publisher organization, qualified mappings, source hierarchies, the
declared development partition of publisher document assignments, and
development-only query evidence.

**Work:** Generate no more than 12 subject-area candidates across four declared
pilot families: environment, employment, public health, and government
operations. Cap each source's contribution within a family and allow
many-to-many membership and `noSuitableGroup`.

Keep each signal inspectable:

- publisher organizational membership;
- native `skos:broader`, `skos:narrower`, and `skos:related`;
- cross-scheme `skos:exactMatch`, `skos:closeMatch`, `skos:broadMatch`,
  `skos:narrowMatch`, and `skos:relatedMatch`;
- document co-assignment when adequately supported;
- source-balanced text embeddings;
- graph-community evidence; and
- development query terminology and judgments.

**Output:** Evidence cards with label, definition, inclusions, exclusions,
candidate parents, representative concepts by source, negative examples,
outliers, source coverage, supporting documents and queries, competing groups,
generation methods, and review disposition.

**Check:** Pin the embedding model, model digest, input profile, source weights,
neighbor limits, random seeds, clustering parameters, and software versions.
Rebuild across at least two seeds, two reasonable model choices, a source
release change, and a vocabulary withheld from generation. Report membership
stability and forced/unassigned rates. Cosine similarity may nominate
membership; it cannot determine identity or broader/narrower direction.

**Stop:** Instability, source dominance, or weak negative separation keeps a
candidate out of evaluation.

### Stage 7 — Compare designs without presuming a spine

Run a staged comparison so each additional layer must beat the simplest viable
alternative:

1. Current adopted SpicySearch `scoped-fusion-serving-v1` baseline.
2. Baseline plus direct publisher document assignments.
3. Direct Atlas source concepts with expansion disabled.
4. Qualified direct mappings and native hierarchy, one relation family at a
   time and evaluation-only.
5. EuroVoc publisher organization unchanged.
6. One external hub at a time: EuroVoc, FAST, LCSH, or Wikidata where supported.
7. Atlas-generated navigation candidates.
8. Three to five sparse Atlas meta-subject candidates, only after arm 7 passes.

Also run `always_abstain`, `constant_majority`, a shuffled-edge placebo, and
oracle concept resolution and document assignments as diagnostics. The external
hub arms preserve every source node; using a hub for routing does not turn it
into Atlas identity.

All non-identifier traversal starts disabled. `E-S1b` relation-family precision
is a prerequisite for `skos:relatedMatch` or multi-hop experiments. Search depth
is an experimental variable, not an architectural default. `skos:closeMatch`
remains non-transitive; related mappings remain disabled unless a registered
experiment tests them.

Freeze a complete recipe and one comparator for every claim:

| Claim | Primary comparator |
| --- | --- |
| EuroVoc publisher organization helps | Direct concepts plus qualified mappings |
| A named external hub helps | The same direct-concept and mapping arm |
| Local navigation helps | The development-selected, frozen nonidentity arm among direct mapping, publisher organization, and external hubs |
| Sparse meta-subjects help | The development-selected, frozen nonidentity arm |

A win by one layer cannot authorize another layer.

Select and freeze the nonidentity comparator from development evidence before
the sealed test. If more than one candidate advances, preregister a closed or
max-statistic multiplicity procedure for the complete family. Selecting a
"winner" from the same sealed outcomes and then making an unadjusted comparison
is prohibited. A later meta-subject claim uses the same adjustment or a fresh
holdout.

### Stage 8 — Test the agentic path, not only retrieval components

Use two separately scored lanes:

1. **Oracle component lane:** A reviewed structured query plan is supplied. This
   isolates Atlas resolution, traversal, ranking, and explanations.
2. **Agentic end-to-end lane:** User request plus caller state and allowed tools
   goes to an agent, which proposes a typed `QueryPlanCandidate`. A deterministic
   SpicySearch compiler resolves ambiguity, intersects the proposal with the
   pinned policy and budgets, records any refusal or change, and executes the
   accepted plan.

The agent never executes arbitrary SPARQL, Cypher, or an unrestricted graph
query. Pin the agent model revision, prompt, tool schema, decoding settings,
retry policy, replay-safe caller context, Atlas digest, and retrieval-policy
digest. Caller context must be synthetic or minimized; otherwise pin a digest
and a replayable authorization decision. Never capture credentials, raw
personally identifiable information, or production user state. Repeat stochastic
cases and report first-run success and consistency. Score planner accuracy,
policy adherence, result ranking, and explanation replay separately.

The end-to-end comparator is the current deterministic `query-front-door-v1`
through the actual caller affordances, not only a benchmark-built request. The
existing evidence reports 9 of 114 tasks passing through the front door versus
61 of 114 through the harness, so the experiment must report expressible and
action-required tasks separately
([product-path result](../../../spicysearch/evaluation/experiments/2026-08-02-query-front-door-product-path-v1/decision.md)).
Give the agent only tools and caller state that the product can deploy. Before
scoring, register first-run success, repeat-run consistency, latency, and cost
gates; require zero policy violations. An oracle-component win without an
end-to-end pass cannot authorize agentic use.

Predeclare a paired matter-level end-to-end success comparison. Agentic use
requires either superiority by a registered minimum worthwhile effect or
noninferiority plus a separately registered capability gain on action-required
tasks. Run exactly the preregistered number of repeats and aggregate them with a
fixed estimator, such as the mean across all runs. Never select or report a
best-of-k result as the agent's performance.

### Stage 9 — Run leakage-safe development and independent evaluation

`quality-v1` is a visible development and plumbing dataset, not a holdout.
Leave-one-matter-out runs are development resampling only. For each run, rebuild
candidate groups, labels, embeddings, bridge decisions, thresholds, and policy
parameters without the excluded matter's documents, concepts, terminology,
queries, variants, judgments, or derived statistics. Independently published
vocabulary facts may remain available. With only three matter clusters, report
results descriptively; do not issue a decision-grade confidence interval.

Promotion requires newly drawn, unopened whole matters and independent GAO/CBO
queries and judgments. An independent evaluation custodian selects and seals
them. Before their identifiers, documents, queries, or judgments are exposed to
the system designers, freeze:

- Atlas distribution and any view;
- organization or meta-subject candidates;
- SpicySearch bridge and retrieval policy;
- ranking implementation;
- agent model, prompt, tools, and retry settings;
- primary endpoint, safety gates, minimum worthwhile effect, and analysis code;
- matter as the independent resampling unit; and
- the treatment of secondary comparisons.

After that freeze, only the fixed production-equivalent ingestion and indexing
pipeline may process test documents. No person may add or change a mapping,
membership, bridge row, prompt, model, policy, or parameter using sealed-test
content. Judgments remain sealed until every frozen run is complete.

Use a preregistered simulation to obtain at least 80 percent power at a two-sided
5 percent error rate for the minimum worthwhile matter-level effect. If the
available number of independent matters is smaller, report descriptive results
and stop before promotion. Use cluster-aware paired inference or a paired
randomization test; queries within one matter are not independent.

Pool top results from every frozen arm before blind relevance judgment so a new
graph arm is not penalized for retrieving documents absent from an older pool.
Include unique results from every registered stochastic agent repetition in that
pool. Repetitions measure consistency within one matter; they do not create new
independent matter samples.
[TREC guidance](https://trec.nist.gov/howto.html) provides the relevant training,
test-topic, run-freeze, and pooled-judgment precedent.

## Decision gates

Numeric effects below are planning hypotheses until Stage 9 establishes a
powered design. They are not accepted thresholds and cannot authorize change.

### Nonidentity organization, hub, and navigation gates

The primary endpoint for each frozen comparison above is paired matter-level
`nDCG@10`. A provisional minimum worthwhile improvement is `0.03`. Precision at
5, forbidden results, and unqualified top-ten results are safety gates, not
alternate ways to declare a win. Test publisher organization and each external
hub against the direct-mapping arm; test local navigation against the best
nonidentity comparator selected from development evidence and frozen before the
sealed test. Predeclare each decision and use hierarchical testing or the
registered multiplicity procedure before any meta-subject comparison.

The arm must also:

- beat the applicable trivial comparators and current adopted search baseline;
- lose no more than a preregistered noninferiority margin on precision at 5;
- produce zero forbidden or unqualified top-ten results;
- replay 100 percent of all graph-derived top-ten explanations;
- show useful results across at least two independent matter families;
- retain source identity and exact mapping predicates;
- pass independent membership review; and
- remain within accepted stewardship cost and backlog limits.

### Meta-subject gate

Retrieval gain cannot prove shared identity. A proposed meta-subject must pass
two independent gates:

1. **Semantic gate:** Compatible definitions and scope notes; independent
   identity review; explicit conflict and negative checks; exact and non-exact
   mappings kept separate; complete recovery of every constituent source
   concept and original assertion; a named steward; and split, merge,
   replacement, and retirement procedures.
2. **Product gate:** A powered, preregistered improvement over the nonidentity
   comparator selected from development evidence and frozen before the sealed
   test, on at least two intent families, with no material pooled regression or
   safety failure.

The [UMLS Metathesaurus](https://www.nlm.nih.gov/research/umls/knowledge_sources/metathesaurus/index.html)
shows that a source-preserving shared-concept layer is possible. Its official
[reference manual](https://www.ncbi.nlm.nih.gov/books/NBK9684/) documents source
atoms, source identifiers, relationships, and concept history, which also show
the governance burden such a layer creates. Atlas should build only the
junctions that earn that burden.

### Binding gate

An experimental pass only permits a separate binding proposal. It does not
approve one. A future proposal may add organization classes or a sparse
meta-subject scheme only when:

- two real consumers need the distinction, or one reproduced failure proves it;
- canonical RDF and any compact view have verified semantic parity;
- publisher objects, Atlas collections, source concepts, and Atlas identities
  remain distinct;
- review disposition, validity, and change event are separate axes;
- source licensing, privacy, stewardship, and requalification are funded; and
- the independent semantic and product gates pass.

If an external hub performs as well, reuse it. If organization adds no material
value, keep direct source concepts and mappings. If results vary by subject
family, propose bounded local policies rather than one global spine.

## Runtime safety requirements

A SpicySearch graph policy must pin predicate, direction, source authority,
qualification, endpoint releases, allowed semantic rings, explicit cross-ring
permission, and permitted purpose. Cross-ring traversal is off by default. The
policy must also bound:

- per-node fan-out and total visited concepts;
- maximum hops and total traversed edges;
- total candidate documents;
- wall-clock time and memory;
- cycle and duplicate-path handling;
- deterministic best-path selection;
- attenuation and fallback;
- truncation reporting; and
- abstention when identity, coverage, or permission is unresolved.

When the policy authorizes no graph use, ranked document identifiers and scores
must be byte-for-byte identical to the expansion-off baseline; only a
disabled-state receipt may differ.

Domains and subject areas are navigation or ranking evidence by default. They
become hard filters only after explicit user selection and demonstrated complete
coverage. Runtime policy may use a qualified fact; it may not change the fact's
review state.

## Governance, privacy, and rights

The bounded pilot has one Atlas steward, two independent reviewers, and an
adjudicator. Before review, publish the sampling frame, decision guide,
inclusion and exclusion examples, disagreement procedure, release cadence,
backlog ceiling, requalification trigger, and retirement rule. Double-review
all meta-subject identity decisions and a stratified membership sample. Report
raw agreement, class-specific precision, and a chance-corrected measure; do not
rely on Cohen's kappa alone.

Keep three lifecycle dimensions separate:

- **Review disposition:** proposed, accepted, rejected, unresolved;
- **Validity:** current, superseded, withdrawn;
- **Change event:** add, remove, replace, split, merge, relabel, reparent.

Publisher state and Atlas state also remain separate. A faithful publisher fact
can be current while product use is disabled.

Raw search queries, names, organizations, and stable user identifiers must not
enter RefSpec. SpicySearch may provide only time-bucketed aggregate nomination
signals keyed to Atlas assertion or group identifiers, pinned to a source
snapshot, and meeting an accepted minimum cell size. Before collection, the
privacy owner must approve access, retention, deletion, and incident handling.
Feedback may nominate review; it is neither relevance gold nor promotion
authority.

Every experimental manifest must record source-specific rights, attribution,
and redistribution conditions. Internal evaluation and public redistribution
are separate approvals. RefSpec currently has no repository-wide license
selection, so no public sidecar or view may be inferred from this plan.

Use [SSSOM](https://mapping-commons.github.io/sssom/dev/) fields where they fit
mapping provenance, [PROV-O](https://www.w3.org/TR/prov-o/) for general activity
and agent provenance, and [SHACL](https://www.w3.org/TR/shacl/) for required
fields and relation constraints. These standards guide the experiment; they do
not override Atlas's accepted binding.

## First work if approved

The first useful implementation slice is intentionally narrow:

1. Record the cross-product authority and experiment decisions.
2. Make SpicySearch independently verify and consume a sealed, externally
   digest-pinned copy of the validator-conforming Atlas 3.0 distribution with
   expansion off.
3. Preserve ranking-v4 direct-versus-expanded provenance and replayable
   per-result paths.
4. Independently verify the existing source-faithful
   `EuroVocOrganizationExperiment` sidecar, then build the SpicySearch-owned
   fixture bridge.
5. Run only plumbing, safety, and descriptive development comparisons.
6. Acquire independent document evidence through SpicyRegs and create new
   sealed whole matters before any adoption decision.

Completion of those steps would make the experiment ready to answer the design
question. It would not approve a taxonomy, meta-subject registry, binding,
release, deployment, or activated graph search.
