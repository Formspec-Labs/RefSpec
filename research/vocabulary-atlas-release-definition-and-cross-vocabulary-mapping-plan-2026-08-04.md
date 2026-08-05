# Vocabulary Atlas: release definition, complete v1 scope, and mapping plan

**Date:** 2026-08-04
**Status:** Approved for implementation
**Current milestone:** `v1.0.0-rc1`
**Purpose:** Define what makes one Atlas build a citable release, what each
release must satisfy, and what RefSpec publishes for people and systems to
search, filter, download, and reuse.

**Format and rules:**
[Design proposal](vocabulary-atlas-design-proposal-2026-08-03.md) ·
[Addendum](vocabulary-atlas-design-proposal-addendum-2026-08-03.md). Those
documents define the ring model, evidence classes, proof-adapter trust, the
frontier rule, and the promotion ladder; this one defines scope, schedule, and
release lineage. Both were reconciled to this plan on 2026-08-04. Three limits
they own and this plan inherits are recorded in §16.

**Implementation checkpoint (2026-08-05):** RefSpec implements the complete
production qualification path, exact six-release opening, Atlas 2.0 assembly,
mapping-assertion lifecycle and supersession, publication decisions for all 87
planning rows, complete static access paths, executable explorer acceptance,
and content-derived release acceptance. The canonical six-release baseline now
accounts for 9,010 concepts, 32,684 native relations, and all 582 non-control
mapping assertions while preserving the 69 agreed control rows in qualification
evidence.

Six complete production candidate catalogs are prepared and pinned: 12,313
candidates in total. The production Batch API path groups up to 25 independent
rows per provider request, bounds groups and jobs by bytes and conservative
tokens, preserves exact raw provider evidence, and retries only missing or
malformed rows. The exact no-provider plan uses 1,488 provider requests across
27 queue-safe jobs. Its conservative projected cost is $109.903535. One-row
requests would use 36,939 requests across 50 jobs and cost a projected
$504.279960. Public v1 requires both scoring and judging batch evidence for
every production run and recomputes requests, results, receipts, usage, and
spend during reopening. It then rebuilds the complete Crosswalk from those
exact judge receipts and reproduces every admitted, controlled, abstained,
rejected, and incomplete candidate disposition before accepting the run.

One immutable production spend authority now governs all six directories. It
recomputes the current 25-row plans locally before provider access and assigns
non-overlapping hard limits of $1.10, $3.50, $1.00, $70.00, $20.50, and $15.90
to the six manifest jobs. Those allocations total exactly $112.00. Each Batch
sidecar, job, sealed run receipt, and public-release check reopens the same
content-addressed authority and its plan and model-policy digests. Production
accepts the exact approved model names; a later dated model requires a new
authority. The implementation is ready to seal that authority from an explicit
$112 approval and then execute the paid jobs within it.

The public-definition preparer is implemented and verified through the exact
point where production receipts become required. The remaining release actions
are to record the explicit spend approval, execute the six governed jobs, seal
every admitted non-control result, prepare and verify the canonical public
definition from those receipts, and run the guarded public-v1 builder. The
builder treats all six production run receipts as required inputs, including a
run that admits zero mappings.

## Decision

RefSpec publishes versioned vocabulary atlases. Each publication includes only
sources approved for that publication. The publication decision records that
approval and every source-specific condition. Atlas inclusion records vocabulary
facts; it does not activate document tagging or search expansion.

This document has three parts with different lifespans:

- **Part A — release lineage.** What makes a build a release rather than a
  scratch run. Stable.
- **Part B — release requirements.** The canonical Atlas, public package,
  indexes, and checks that make a release trustworthy. Stable.
- **Part C — our atlas.** The complete v1 scope and immediate build order.

An Atlas release is one build whose entire derivation is recoverable from the
build itself:

```text
declared scope stated as membership
+ every input pinned by digest
+ build identity derived from content, not time
+ reproducible where it can be, pinned where it cannot
+ event record separate from content record
= a release you can still interpret in a year
```

Tagging eligibility is not part of that. `SubjectEmissionPolicy`,
`OutputProfile`, and retrieval policy remain separate, versioned decisions.
Adding a vocabulary to the Atlas must not change tagging or document-search
behavior unless one of those policies changes.

The Atlas contains vocabulary facts. It does not contain documents, document
tags, search results, or product policy.

---

# Part A — Release lineage

## 1. What makes a build a release

Every layer is content-addressed and pins the layer beneath it by digest:

```text
sourceFetchId / sourceObservedAt
  → sourceCapture (resourceManifest, observationSetDigest, reconciliationDigest)
    → source concept release (releaseId = content digest, membershipMode,
                              selectionPolicy, identityPolicy)
      → atlas index row (rowId / rowDigest)
        → scope (contentDigest; pins the index, every release, every bundle)
          → atlas manifest (generationDigest, implementation source digests
                            and runtime versions, inputs, output)
            → decision (decidedAt, decisionActor, intendedScope, policies,
                        result, supersedes)
```

A release must carry all five facts:

**1.1 Declared scope stated as membership.** Not a completeness gate. Each
included release states whether its membership is complete or selected, and
under which selection policy. A complete publisher vocabulary, a complete
verified subset, and a policy-selected frontier are all valid — the record must
say which one applies. Development sampling limits such as `max_records` never
produce a release.

**1.2 Every input pinned by digest.** The scope pins the Atlas index and each
source concept release. The manifest pins its inputs, its scope, and its output.
No input is named without being pinned.

**1.3 Build identity derived from content, not time.** The manifest identifier
derives from `generationDigest`. `implementation` pins its own source-module
digests and its runtime versions. Which code produced a build stays answerable
after the working tree has moved on.

**1.4 Reproducible where it can be, pinned where it cannot.** These are
different guarantees and a release must not blur them:

| Layer | Guarantee |
| --- | --- |
| Source concept releases, scope, atlas, projections, indexes | A fresh build from the same inputs reproduces the same canonical digests. |
| Machine qualification evidence | Not reproducible. Each provider call pins its own request and response artifact digests, provider, model identifier, sealed input digest, and independence group. The bundle is pinned by digest instead of rebuilt. |

A release that claims blanket reproducibility is making a false claim the
moment it contains a single machine-qualified mapping.

**1.5 Build event separate from content record.** The manifest carries no build
timestamp, so it stays reproducible. The build decision records the wall clock,
actor, and supersession chain. Source-observation, evidence, lifecycle, and
effective-time values remain in the content because they describe vocabulary
facts rather than the act of building the Atlas.

## 2. Supersession

Three distinct relations. Record them separately or they will be conflated on
the first re-cut:

| Relation | Meaning | Where recorded |
| --- | --- | --- |
| Atlas supersedes Atlas | A later build of our Atlas replaces an earlier one. | Decision `supersedes` |
| Source release supersedes source release | A later publisher release replaces an earlier one, e.g. ELSST R6 over R5. | Source concept release lifecycle |
| Concept lifecycle | A concept is deprecated, replaced, split, or merged within a vocabulary. | Concept record status and lifecycle set |

Superseding never mutates the superseded build. Every earlier release stays
resolvable at its own digest.

## 3. Disposition of declared scope

Whatever a build declares in scope, it must record the disposition of every
declared item — included, or absent with a reason.

This is the fact that keeps an old Atlas interpretable. Without it, "this build
has no CRS mappings" is ambiguous between *not yet run*, *ran and produced
nothing admissible*, and *deliberately excluded*. Absence with no reason is
indistinguishable from an accident.

Disposition is scoped to what the build declared, not to the registry. A build
that never claimed a resource owes no record of it.

---

# Part B — Release requirements

## 4. Required release products

One release has three layers. Each layer pins the layer it derives from.

### 4.1 Canonical Atlas

The canonical Atlas remains the closed Atlas 2.0 three-file distribution:

| Member | Required contents |
| --- | --- |
| `atlas-scope.json` | Exact Atlas index, included concept releases, and relation bundles, each pinned by content digest. |
| `atlas.nq` | Complete release facts, concepts, native relations, lifecycle facts, cross-vocabulary assertions, typed cross-ring ontology links, evidence assertions, and machine-proof pins. |
| `atlas-manifest.json` | Atlas identifier, schema versions, implementation digests, runtime versions, graph and record counts, scope pin, output pin, and ring summaries. No build timestamp. |

The Atlas contains every concept and native relation in each included release.
Samples and bounded displays never replace the canonical data.

### 4.2 Public package

The public package derives from the verified canonical Atlas and contains its
exact manifest and scope, deterministic compressed data, publication decision,
checksums, explorer data, and static explorer. Its publication manifest pins
every file. The publication decision pins the exact Atlas and records source
approval, conditions, and supersession.

### 4.3 Consumer indexes and acceptance evidence

Reproducible indexes support label, identifier, ring, source, release, source
collection, relation, evidence, lifecycle, language, participation, CFR title,
and CFR part lookups. The explorer derives only from the canonical Atlas and
its pinned planning index.

The release acceptance record reports native relations per ring and in total,
then checks those counts against the included releases. This measurement remains
outside the canonical Atlas 2.0 manifest until a later binding version adds a
native-relation counter.

Each concept record must expose:

- a stable concept identifier under the exact release's declared identity
  authority: source concept releases use
  `urn:ref:policy:source-concept-identity:v1`, which prohibits label-derived
  identity, prefers the publisher concept IRI, and falls back to source scheme
  plus local record identifier; managed reference releases preserve the member
  IRI from their exact Rulespec release;
- semantic ring;
- source vocabulary and exact release;
- preferred label;
- alternate labels and recognized variants;
- definition, scope note, language, and script when supplied;
- publisher identifier and source URL when supplied;
- current, deprecated, replaced, split, or merged status;
- whatever rights the publisher stated, recorded as an uninterpreted source
  fact; and
- provenance and content digest.

Each release carries the publisher's stated rights as source facts. The
publication decision determines whether and under what conditions the public
package includes that release. Public v1 contains only approved sources.

## 5. Cross-vocabulary mapping model

Cross-vocabulary mapping is sparse and typed. An Atlas must not map every source
to every other source.

Each ring uses its own relation vocabulary:

| Ring | Permitted cross-release predicates |
| --- | --- |
| subject | `skos:exactMatch`, `skos:closeMatch`, `skos:broadMatch`, `skos:narrowMatch`, `skos:relatedMatch` |
| entity | `sameIdentityAs`, `successorOf`, `relatedEntity` |
| value | `exactCrosswalk`, `broadCrosswalk`, `narrowCrosswalk`, `replacedBy` |
| legalIdentity | `cites`, `amends`, `authorizes`, `implements` |

Cross-ring label mappings are prohibited by default. An agency entity and a
subject named after that agency are different concepts. A search product may
combine their document matches, but the Atlas must not assert
`skos:exactMatch` across those rings. Typed cross-ring ontology links are
allowed when the source directly states a meaningful relation and this
document defines its direction and proof.

Subject predicates have these retrieval meanings:

| Predicate | Meaning | Permitted default traversal |
| --- | --- | --- |
| `skos:exactMatch` | The concepts are interchangeable for the qualified retrieval purpose, but retain separate identities. | Symmetric after policy activation. |
| `skos:closeMatch` | The concepts are sufficiently similar for cautious retrieval expansion. | Symmetric with attenuation. |
| `skos:broadMatch` | The target concept is broader than the source concept. | Directional and weaker when a narrow query expands to a broad target. |
| `skos:narrowMatch` | The target concept is narrower than the source concept. | Directional and stronger when a broad query expands to a narrow target. |
| `skos:relatedMatch` | The concepts are associated but neither equivalent nor hierarchically ordered. | No default traversal. |

A unanimous non-control `related` verdict emits a typed `skos:relatedMatch`
`MappingAssertion`. It remains available for filtering and graph inspection but
grants no default traversal. The v1 implementation must extend the current
Crosswalk proof adapter to support this assertion without changing its
`searchOnly` evidence ceiling.

The Atlas records these semantics. Search policy sets hop, fan-out, and score
limits and records every path it follows.

### 5.1 Planned CFR legal-identity to subject bridge

A later regulatory-corpus release may include one explicit cross-ring relation:
a CFR title, chapter, or part in the `legalIdentity` ring may carry
`hasIndexedSubject` links to concepts in the `subject` ring. The inverse view is
`indexesCfrUnit`; the canonical Atlas stores one direction and the explorer may
show both.

```text
CFR legal identity
  -- hasIndexedSubject {source, edition, evidence} --> subject concept
```

This relation means that the cited source indexes the CFR unit under the
subject. It is not `skos:broadMatch`, does not make the CFR unit a subject, and
does not authorize tagging or query expansion by itself.

The official CFR List of Subjects is direct publisher evidence for this link.
Each assertion pins the exact CFR edition or observation date, CFR identifier,
authored term, resolved subject identity, source location, and source digest.
An exact official term or recognized publisher variant may resolve
deterministically. A source-local term remains its own subject concept until a
publisher crosswalk, named review, or admissible machine proof maps it to
another subject release.

Federal Register document JSON carries `topics` and `cfr_references` on the
same document. That co-assignment is valuable evidence and candidate input,
but it does not prove that every topic applies independently to every cited
CFR part. The Atlas does not create that Cartesian product. Document
assignments stay outside the Atlas and retain the document as their scope.

## 6. Mapping assertion requirements

Every admitted cross-release assertion must record:

- content-derived assertion identifier;
- semantic ring;
- source concept and exact source release;
- target concept and exact target release;
- directed predicate;
- evidence class;
- publisher source, validation receipts, or named human review;
- proof adapter and exact proof digest when machine evidence applies;
- pinned qualification-run identity, protocol version, and candidate-generation
  class when machine evidence applies;
- candidate-generation method as provenance, never as proof;
- qualification policy;
- row-level `mapping_source` in SSSOM exports;
- lifecycle and supersession status; and
- the maximum use supported by its evidence.

Control-arm measurements belong to the qualification run. Each machine proof
pins that run; individual assertions do not repeat its global measurements.

The canonical Atlas preserves multiple assertions for the same endpoint pair.
It does not overwrite disagreement or compute one authoritative "best" mapping.
A consumer may derive a best-mapping view if it retains links to every source
assertion.

## 7. Mapping rules that prevent false knowledge

Every build must enforce these rules:

1. Both mapping endpoints belong to exact releases that are complete within
   their declared scopes.
2. Label equality generates a candidate; it never proves identity or a mapping.
3. Document co-assignment and concept co-occurrence generate candidates only.
4. A publisher assertion, admissible machine proof, or named human review must
   support every mapping assertion. A machine proof pins a qualification run
   whose protocol, candidate classes, control results, requests, responses, and
   provider receipts are measurable and reproducible as evidence.
5. `exactMatch` means retrieval interchangeability under the assertion's
   evidence. It does not merge concept identity.
6. Directional mappings require direction-specific evidence. Label length,
   hierarchy depth, or model confidence does not prove direction.
7. Mapping chains generate candidates only. The Atlas never materializes
   `A → B → C` as an `A → C` mapping without direct qualification.
8. Cross-ring mappings are prohibited unless a ring-specific design defines a
   semantically valid predicate and proof.
9. Rejected, abstained, disagreeing, and control-arm candidates remain evidence
   records; they never become mapping assertions.
10. Product feedback never rewrites a published mapping. It may inform a new
    evaluation and a new Atlas release.

### 7.1 Default LLM scoring and judging pipeline

RefSpec uses the batch LLM pipeline for semantic mapping work whenever source
facts alone do not determine the relation. The pipeline runs beside the Atlas
build and produces sealed, digest-pinned evidence that the build consumes.

Each subject-mapping run follows six stages:

1. **Extract exact releases.** Reopen the pinned source and target releases and
   export their complete concept facts and native hierarchy.
2. **Generate candidates deterministically.** Use normalized labels, alternate
   labels, definitions, identifiers, lexical near-misses, native hierarchy, and
   graph neighborhoods to build a high-recall candidate set. Candidate rules
   and random seeds remain reproducible.
3. **Score in batch.** An LLM scorer ranks semantic plausibility, evidence
   sufficiency, and likely direction. Production reopens complete retained
   scoring Batch evidence before it plans any judging request. It orders
   candidates by descending semantic plausibility, then descending evidence
   sufficiency, with candidate identity as the deterministic tie-breaker.
   Scores prioritize judging and widen recall; they never prove a mapping.
4. **Judge in blind batches.** Two model families independently classify each
   candidate as `same`, `near_same`, `target_is_broader`,
   `target_is_narrower`, `related`, `unrelated`, or
   `insufficient_evidence`. Judges do not see the generator class, control-arm
   status, proposed relation, scorer score, or another judge's answer.
5. **Admit by typed agreement.** Compatible judgments emit the weakest relation
   both families support. Disagreement and abstention remain evidence. Control
   candidates remain evidence regardless of their verdict.
6. **Seal and measure.** The run records requests, responses, model identities,
   provider endpoints, costs, control results, relation counts, and all digests,
   then produces a `CrosswalkBundle` for the Atlas proof adapter.

Hierarchy-aware scoring and judging receive balanced context from both sides:
preferred and alternate labels, definitions, scope notes, and bounded native
parents and children. The payload never identifies a shared parent or control
class. This gives judges enough evidence to determine `broadMatch` and
`narrowMatch` without revealing the candidate generator's hypothesis.

The judge sidecar pins a content-derived priority record to the exact candidate
catalog, scoring receipt log, scoring Batch sidecar, scorer family and model,
score vector, and ordered candidate identities. The priority record contains
digests and counts rather than score values. Each judge receives only the two
concepts and the blind rubric. Public reopening reproduces the scorer readings,
priority order, 25-row judge packing, models, candidate coverage, and cost before
accepting the qualification run.

The campaign spend authority seals the exact scoring plan before provider work
begins. Because scorer readings do not exist at approval time, it also seals the
priority algorithm, complete candidate catalog, judge models, group-size limit,
and fixed run allocation. After scoring completes, the verifier derives the
exact judging plan from that governed evidence and requires the plan to fit the
same allocation. Each changed scorer log, priority order, model, grouping, or
cost therefore creates new governed evidence with an explicit lineage.

Use `tools/run_atlas_qualification.py` and its `batch-submit`, `batch-status`,
and `batch-collect` path by default. The serial path remains available for small
diagnostic smoke tests. Production recovery stays on the Batch path, including
single-row Batch requests when grouped recovery is unsuitable, because public
v1 requires every production receipt to retain raw Batch evidence. Batch and
serial execution produce the same receipt shape and qualification semantics.
After an interrupted provider create, run `batch-reconcile` (or
`score-batch-reconcile`) first. It restores sidecar state from acknowledged
immutable journal phases, resumes an uploaded input only when the create call
never began, releases definite client rejections, and keeps ambiguous creates
reserved for operator review. Official reconciliation receives the same
`--spend-authority` file as submission, derives the expected run allocation
from that local approval, and compares it with the retained sidecar. Judging
reopens complete verified scorer receipts before provider setup and again while
holding the shared run lock, so the priority record and ranked candidate rows
remain current through every upload or resumed create.

The current runner already provides sealed blind two-family batch judging for
managed releases. V1 extends that path with batch scoring,
`SourceConceptRelease` extraction for CRS, a production candidate policy,
balanced parent-and-child context, and complete `relatedMatch` proof support.
The build order makes these five additions the first v1 implementation step.

Production qualification uses the complete candidate catalog produced by the
release's deterministic blocking rules. Pilot class limits and
`--max-candidates` may validate the pipeline, but they never define release
coverage. The batch scorer may prioritize work and expand promising
neighborhoods; every candidate that meets the sealed production floor reaches
both blind judges. The run receipt reports generated, scored, judged,
abstained, rejected, controlled, and admitted counts so unprocessed candidates
cannot disappear silently.

The LLM pipeline supports semantic judgment, not source authority. Publisher
identifiers and crosswalks, native relations, lifecycle events, code editions,
rights facts, and publication decisions remain deterministic or publisher-
asserted. For entity, value, and legal-identity rings, LLM scoring may prioritize
candidates, but only ring-valid source evidence can support identity, effective
dates, replacements, or legal relations.

## 8. Contract acceptance checks

A build satisfies the contract when all these pass:

1. Every native relation resolves both endpoints or records an explicit
   external reference or truncation.
2. Every mapping assertion resolves its endpoint releases and evidence.
3. Subject, entity, value, and legal-identity records remain separately
   filterable and never compete in one concept ranking.
4. The explorer exposes every concept, release, native relation, and admitted
   mapping. A bounded visual display never truncates the downloadable release.
5. Consumers can filter by ring, source, exact release, native or
   cross-vocabulary relation, predicate, evidence class, lifecycle status,
   language, and subject participation.
6. Search covers preferred labels, alternate labels, recognized variants,
   codes, definitions, source identifiers, normalized text, and useful partial
   matches.
7. Concept pages show native parents, children, ancestors, descendants, related
   concepts, and directed cross-vocabulary mappings with source and target
   releases visible.
8. When a release includes CFR-to-subject links, CFR legal-identity pages show
   indexed subjects, subject pages show the CFR units that index them, and
   users can filter those links by CFR title, part, source, edition, and
   evidence.
9. The explorer computes multi-hop paths for inspection but never presents an
   inferred path as a direct mapping assertion.
10. Checksums verify every canonical and derived member.
11. A fresh build from the same inputs reproduces the same canonical digests
    for every layer covered by §1.4 and pins the rest.

## 9. Excluded content

An Atlas build excludes:

- documents, document versions, and passages;
- document-to-concept assignments;
- assignment evidence fragments and attestations;
- search snapshots, rankings, and query-expansion results;
- `SubjectEmissionPolicy`, `OutputProfile`, and retrieval-policy activation;
- user queries and product feedback;
- raw mapping candidates presented as assertions;
- label clusters presented as canonical concepts; and
- benchmark-only samples presented as releases.

Downstream document and search products may join their exact releases to the
Atlas through stable identifiers. That join creates a reproducible document
tagging graph without changing the Atlas oracle.

---

# Part C — Our atlas

## 10. Registry reference

The v1 release catalog declares every row in `portfolio/atlas-index-v0.json`.
Rows with exact releases contribute their complete data. Every other row remains
visible with an explicit disposition and reason, so users can distinguish
included, planned, deferred, unavailable, and deliberately excluded sources.

The index carries 87 source/ring rows produced by 54 source modules over 72
distinct resource identifiers. A resource may appear in more than one ring, and
may appear more than once within a ring under different facets or source
modules — the value ring is 40 rows over 34 resources. The row, not the
resource, is the unit a build declares.

### 10.1 Subject ring

`federal-register-thesaurus-2025`, `federal-register-api-topics`,
`cfr-list-of-subjects`, `crs-legislative-subject-terms`, `crs-policy-areas`,
`crs-native-controls`, `cbo-cost-estimate-feed`, `gao-topics`,
`grants-gov-status-codes`, `lda-general-issue-codes`, `elsst`,
`icpsr-subject-thesaurus`, `mesh-descriptors`, `nalt-core`, `gemet`,
`nasa-thesaurus`, `lcsh-topical`, `fast-topical`, `eurovoc`, `agrovoc`,
`gcmd-science-keywords`, `nasa-technology-taxonomy`,
`doe-osti-semantic-thesaurus-2020`, `epa-enterprise-vocabulary`.

`core`, `specialist`, and `bridge` describe subject participation. They do not
control inclusion and do not authorize tagging.

### 10.2 Entity ring

`federal-hierarchy`, `federal-register-native-controls`,
`regulations-gov-native-controls`, `unified-agenda-native-controls`,
`fcc-ecfs-native-controls`, `crs-legislative-subject-terms` organization and
geography records, `uei-authority`, `cage-authority`, `fec-native-controls`,
`nppes-npi-authority`, `cms-certification-number-authority`,
`epa-substance-identifiers`, `courtlistener-jurisdictions`,
`census-acs-geography-identifiers`, `census-tiger-geoid-structure`,
`usgs-gnis-identifiers`.

### 10.3 Value ring

`naics`, `psc`, `omb-a11-budget-codes`, `governmentwide-spending-data-model`,
`usaspending-award-type-codes`, `treasury-fast-book`, `fac-api-dictionary`,
`congress-billstatus-native-controls`, `federal-register-native-controls`,
`fcc-ecfs-native-controls`, `ferc-elibrary-native-controls`,
`nrc-adams-native-controls`, `regulations-gov-native-controls`,
`unified-agenda-native-controls`, `oira-review-native-controls`,
`pra-icr-native-controls`, `sam-assistance-listing-controls`,
`sam-opportunities-native-controls`, `grants-gov-status-codes`,
`govinfo-collections`, `lda-filing-types`, `nature-of-suit`,
`scotus-opinion-and-package-types`, `sec-rules-regulations-categories`,
`oversight-report-types`, `gao-cra-database-facets`, `cbo-cost-estimate-feed`,
`opm-ehri-workforce-codes`, `opm-plum-position-status-codes`,
`nppes-data-dissemination-layout`, `census-aspep-data-flags`,
`census-aspep-function-item-codes`, `nasbo-state-expenditure-program-areas`,
`crs-native-controls`.

### 10.4 Legal-identity ring

`ecfr-cfr-structure`, `govinfo-cfr-packages`,
`unified-agenda-legal-authority-citations`, `fcc-ecfs-native-controls`,
`ferc-elibrary-identifiers`, `nrc-adams-identifiers`,
`treasury-account-symbol-structure`.

## 11. Our Atlas v1

Atlas v1 replaces the isolated single-source builds. It targets every concept
and native relation from six named source releases whose current bytes are
available today. The ICPSR and ELSST release-identity decisions are closed and
their exact current bytes are pinned in `portfolio/atlas-index-v0.json`.

| Exact release | Ring | V1 contents |
| --- | --- | --- |
| Federal Register Thesaurus 2025 | subject | 705 concepts, 1,451 native concept-to-concept associative relations, and complete accounting for all 1,463 source `Related` references. The governed regulatory subject core. |
| CRS Legislative Subject Terms | subject | 565 concepts. |
| CRS Policy Areas | subject | 32 concepts. |
| CRS legislative organizations and places | entity | 478 entities. |
| ELSST R6 | subject | 3,470 concepts and 12,482 native `broader`, `narrower`, and `related` assertions. |
| ICPSR Subject Thesaurus | subject | 3,760 concepts and 18,751 native relations in the complete URI-verified subset. |

The Federal Register source's 1,463 `Related` references comprise 1,451
resolved `skos:related` concept links, 11 suggested open-term patterns, and one
unresolved target label. V1 retains the 1,451 typed native links and preserves
the other 12 source records with their status and source location; no source
fact disappears and no unresolved label is promoted into a concept link.

The two release-identity decisions are:

- **ICPSR** is the exact complete URI-verified subset named by
  `urn:ref:icpsr:release:development:8bf9bf7f6c335e3aaccd29eedd00d41d7bc153e216e7dff6ff215472368aae37`.
  Its republished `developmentOnly` marker remains a source fact, and the
  publication decision records the affirmative condition under §4.3.
- **ELSST R6** uses the publisher release IRI `https://elsst.cessda.eu/id/6` as
  release identity. The `operationalSerializationProfile` schema-set digest is
  distribution-validation metadata; changing that profile alone does not mint
  a different vocabulary release.

Current sealed evidence provides a **582-assertion non-control baseline**: 121
`exactMatch`, 232 `closeMatch`, 75 `broadMatch`, 119 `narrowMatch`, and 35
`relatedMatch`. These include every pair among Federal Register, ELSST, and
ICPSR. Of the 353 symmetric mappings, 222 connect ELSST or ICPSR directly to the
Federal Register core.

The 194 `broadMatch` and `narrowMatch` assertions provide the cross-vocabulary
hierarchy required for graph navigation and search expansion. The Atlas records
their direction and evidence. Retrieval policy decides whether and how a product
traverses them.

Before publication, v1 uses the batch LLM scoring and judging pipeline for all
high-value subject pairs among the six releases.

| Source | Target | V1 batch work |
| --- | --- | --- |
| Federal Register Thesaurus | ELSST | Preserve the current evidence and run the hierarchy-aware scorer and blind judges over the sealed production candidate catalog. |
| Federal Register Thesaurus | ICPSR | Preserve the current evidence and run the hierarchy-aware scorer and blind judges over the sealed production candidate catalog. |
| ELSST | ICPSR | Preserve the current evidence and run the hierarchy-aware scorer and blind judges over the sealed production candidate catalog. |
| CRS Legislative Subject Terms | Federal Register | Generate, score, and judge direct mappings, including hierarchy direction. |
| CRS Policy Areas | Federal Register | Generate, score, and judge direct mappings, with emphasis on `broadMatch` and `narrowMatch`. |
| CRS Legislative Subject Terms | CRS Policy Areas | Use source co-assignment and native controls to generate candidates, then score and judge every candidate that meets the production floor. |

The final v1 count equals the 582-assertion baseline plus every distinct
non-control assertion admitted by these new sealed runs. When a hierarchy-aware
run differs from the earlier label-only run, the Atlas preserves both assertions
and their evidence; it never overwrites the disagreement.

The existing `atlas-fr-elsst-icpsr-three-crosswalks-2026-08-03` artifact is not
a starting point. It is format 1.0 carrying the superseded v1 mappings under
`twoIndependentMachinesSearchOnly`. Rebuild in 2.0.

## 12. Current Crosswalk v2 baseline

Crosswalk v2 ran 365 candidates per pair across two model families
under `twoIndependentMachinesRelationAgreement`. Each run included two control
arms of 45 candidates each: random negative controls and sibling distractors.

The three runs produced these agreed relations. V1 removes every control-arm row
from the assertion set and retains it in the qualification evidence:

| Predicate | FR↔ELSST | FR↔ICPSR | ELSST↔ICPSR | Agreed | Controls retained as evidence | V1 assertions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `exactMatch` | 29 | 35 | 57 | 121 | 0 | **121** |
| `closeMatch` | 81 | 77 | 74 | 232 | 0 | **232** |
| `broadMatch` | 25 | 29 | 30 | 84 | 9 | **75** |
| `narrowMatch` | 50 | 55 | 22 | 127 | 8 | **119** |
| `relatedMatch` | 29 | 33 | 25 | 87 | 52 | **35** |
| **Total** | 214 | 229 | 208 | **651** | **69** | **582** |

Every control result occurred in a directional or associative class. Those 69
rows measure the qualification protocol; they do not describe vocabulary
knowledge. The remaining 582 assertions enter v1 with their complete evidence.

The controls exercise directional and associative discrimination more strongly
than symmetric substitution. The qualification record preserves that limit so
consumers can filter by predicate and evidence. Atlas publication never turns
the evidence class into product permission.

## 13. Expansion after v1

V1 ships the 582-assertion baseline plus every mapping admitted by the six v1
production runs. The following work adds releases and mapping pairs after v1;
it does not delay the combined release.

### 13.1 Federal source normalization and CFR bridge

The Federal Register Thesaurus is the subject core for US regulatory search.
V1 closes its CRS gap. The next mappings connect other publisher language to the
same core.

| Source | Target | Evidence requirement |
| --- | --- | --- |
| `federal-register-api-topics` | Federal Register Thesaurus | Deterministic publisher-supported resolution first; batch LLM scoring and blind two-family judging for remaining semantic candidates. |
| `cfr-list-of-subjects` | Federal Register Thesaurus and API Topics | Deterministic official-term and recognized-variant resolution first; batch LLM scoring and blind two-family judging for unresolved semantic candidates. |
| `cbo-cost-estimate-feed` (subject) | Federal Register Thesaurus | Batch LLM scoring and blind two-family judging or named review. |
| `gao-topics` | Federal Register Thesaurus | Batch LLM scoring and blind two-family judging or named review. |
| `lda-general-issue-codes` | Federal Register Thesaurus | Batch LLM scoring and blind two-family judging or named review. |
| `grants-gov-status-codes` (subject facet) | Federal Register Thesaurus | Batch LLM scoring and blind two-family judging or named review. The value-ring rows of the same resource stay outside this mapping. |

The FederalRegister.gov Topics API capture is already sealed at 7,767 rows:
1,044 `thesaurus` and 6,723 `ad_hoc`. It also carries 1,428 uniquely resolvable
`see_also` links. The follow-on release adds an explicit source scheme, rights
record, source-concept release, collection filter, native associative relation
bundle, and predecessor reconciliation for later captures. RefSpec-issued
source identities use registered UUIDv7 keys; labels and mutable slugs remain
source facts.

The CFR bridge then adds three products: a complete pinned CFR List of Subjects
release, a matching point-in-time eCFR legal-identity release, and the typed
`hasIndexedSubject` relation bundle defined in §5.1. A prior measurement found
about 8,409 parts, 37,220 part-term assignments, and 1,196 distinct terms; each
published release reports fresh counts from its sealed inputs. Publisher-stated
CFR containment and List of Subjects links enter deterministically. The batch
LLM pipeline handles only semantic mappings among the source terms, API topics,
and Federal Register Thesaurus.

Federal Register document `topics` plus `cfr_references` remain
document-scoped evidence and candidate input. They support the bridge without
creating every possible topic-by-part pair for a multi-part document.

### 13.2 Specialist and bridge spokes

Each specialist or bridge source needs a direct spoke to the Federal Register
core before a product uses it for expansion. `A → LCSH → Federal Register` is
candidate-generation evidence, not an assertion.

Specialist: `mesh-descriptors`, `nalt-core`, `gemet`, `nasa-thesaurus`.

Bridge: `lcsh-topical`, `fast-topical`, `eurovoc`, `agrovoc`,
`gcmd-science-keywords`, `nasa-technology-taxonomy`, and — after source
verification — `doe-osti-semantic-thesaurus-2020` and
`epa-enterprise-vocabulary`.

A direct spoke defaults to the §7.1 batch LLM scoring and blind two-family
judging pipeline when the publisher does not supply a crosswalk.

A source may be present in the Atlas before its spoke exists.

### 13.3 Publisher crosswalks to ingest

Publisher-provided mappings outrank machine-generated candidates and never
overwrite other assertions:

| Pair | Basis | Treatment |
| --- | --- | --- |
| FAST → LCSH | FAST `schema:sameAs` source heading | Preserve as `publisherAsserted`; ingest the RDF form carrying the link. |
| MeSH ↔ LCSH | Published alignment | Preserve source artifact, endpoint editions, and row-level mapping source. |
| NALT ↔ AGROVOC | Publisher or reviewed agricultural crosswalk | Preserve exact source editions and predicates. Do not infer from multilingual label equality. |
| NASA Thesaurus ↔ GCMD Science Keywords | Publisher link or §7.1 batch qualification | Keep source science terms separate from technology-taxonomy values. |
| NASA Thesaurus ↔ NASA Technology Taxonomy | Publisher link or §7.1 batch qualification | Assert only relations the two schemes' definitions support. |

### 13.4 Optional LCSH discovery hub

LCSH may reduce candidate-generation cost, but hub paths never become mappings.
If built, generate and qualify spokes through the §7.1 batch pipeline against
the bounded LCSH topical frontier for MeSH, NALT Core, GEMET, NASA Thesaurus,
ELSST, ICPSR, EuroVoc, AGROVOC, FAST, GCMD Science Keywords, and NASA Technology
Taxonomy. No additional bridge-to-bridge matrix is required.

### 13.5 Entity links

Entity links require identifiers or reviewed source evidence. Name equality
never establishes identity.

| Pair | Relation and purpose |
| --- | --- |
| Federal hierarchy ↔ Federal Register agency identifiers | `sameIdentityAs` for cross-source agency search. |
| Federal hierarchy ↔ Regulations.gov agency identifiers | `sameIdentityAs` for agency and docket discovery. |
| Federal hierarchy ↔ Unified Agenda and OIRA agency identifiers | `sameIdentityAs` and `successorOf` with effective dates. |
| UEI ↔ CAGE | Publisher-asserted SAM identity crosswalk. |
| Federal hierarchy ↔ UEI/CAGE | Only where an authoritative source binds the identifiers. |
| Census ACS/TIGER geography ↔ GNIS | Official identifier or published geography crosswalk. |
| NPI ↔ CMS certification number | Only through an authoritative provider crosswalk; never through organization-name similarity. |

FEC committees, EPA substances, courts, and other entity sources remain useful
without cross-source links.

### 13.6 Value crosswalks

Value mappings compare editions or code systems. They do not create subject
synonyms. Needed when codes change: NAICS, PSC, OMB A-11, Treasury account and
FAST Book, Governmentwide Spending Data Model, nature-of-suit spelling
variants, source-native control editions where the publisher replaces, splits,
or merges codes, and Census ASPEP function/item codes ↔ NASBO program areas
where a published or reviewed statistical crosswalk supports it.

Do not map NAICS to PSC, a status code to a subject, or two codes from
different schemes because their labels resemble each other. Every value
crosswalk names the source edition, target edition, effective date, and exact,
broad, narrow, or replacement predicate.

### 13.7 Legal-identity relations

These are not SKOS subject mappings. Needed: eCFR CFR units ↔ GovInfo CFR package units
through deterministic citations and exact edition or effective-time context;
citation edges among CFR units, statutes, and Public Laws where exact source
text supports `cites`, `amends`, `authorizes`, or `implements`; lifecycle records
for legal identifiers that an issuing system replaces or retires; and exact
scheme definitions for RINs, FCC ECFS dockets, FERC eLibrary identifiers, NRC
ADAMS identifiers, and Treasury account symbols. `successorOf` remains an entity
predicate unless a later legal-identity design adds and validates a distinct
legal lifecycle relation.

A document's RIN, docket number, or citation belongs in the document evidence
graph. The Atlas defines the identifier and the legal relationship; it does not
store the document occurrence.

## 14. Build order

1. **Complete the production qualification path.** Add batch LLM scoring,
   `SourceConceptRelease` extraction for CRS, a production candidate policy
   without pilot class caps, hierarchy-aware balanced judge payloads, complete
   candidate accounting, and `relatedMatch` support to the Crosswalk v2 proof
   adapter. Keep batch and serial receipts semantically identical.
2. **Run the six v1 subject-pair jobs.** Re-run Federal Register ↔ ELSST,
   Federal Register ↔ ICPSR, and ELSST ↔ ICPSR over their sealed production
   candidate catalogs. Generate and run Federal Register ↔ CRS Legislative
   Subject Terms, Federal Register ↔ CRS Policy Areas, and CRS Legislative
   Subject Terms ↔ CRS Policy Areas. Use `batch-submit`, `batch-status`, and
   `batch-collect`; use serial calls only for diagnostic smoke tests and use
   single-row Batch requests when production recovery needs them.
3. **Seal the v1 assertion set.** Preserve the 582-assertion baseline and its 69
   controls. Add every distinct non-control assertion admitted by the new runs,
   retain every new control, rejection, abstention, and disagreement as
   evidence, and produce Atlas 2.0 relation bundles for the final set.
4. **Build the combined Atlas from the closed release identities.** Include the
   six exact releases named in §11, every native
   relation, every lifecycle fact, and the complete sealed cross-vocabulary
   assertion set in one canonical Atlas 2.0 distribution.
5. **Build complete access paths.** Generate the indexes and explorer defined in
   §8, including full-text search, filters, native hierarchy, cross-vocabulary
   hierarchy, concept neighborhoods, and evidence inspection.
6. **Close publication decisions.** Record an affirmative publication
   disposition for every included source and an explicit disposition for all 87
   planning-index rows.
7. **Publish v1.** Build the static public package, verify every digest, reopen
   it from the external publication-manifest digest, and record the release
   acceptance evidence.

Each build and decision is immutable. A later publication decision records the
decision it supersedes. A new Atlas pins an earlier Atlas only when the earlier
Atlas is an actual data input.

## 15. Scope acceptance checks

Atlas v1 is ready for public use when the Part B checks pass and:

1. All 87 planning-index rows carry a disposition: included, planned, deferred,
   unavailable, or deliberately excluded, with a reason where applicable.
2. The six included releases are complete within their declared scopes.
3. Native-relation counts match each included release, including all 12,482
   ELSST R6 hierarchy and associative assertions. Federal Register acceptance
   separately reports 1,451 native concept links, 11 suggested open-term
   patterns, and one unresolved target, reconciling all 1,463 source `Related`
   references.
4. The Atlas contains the complete 582-assertion baseline—121 `exactMatch`,
   232 `closeMatch`, 75 `broadMatch`, 119 `narrowMatch`, and 35
   `relatedMatch`—plus every distinct non-control assertion admitted by the six
   sealed production runs. Manifest counts match the relation bundles and run
   receipts.
5. Every production run reports generated, scored, judged, abstained, rejected,
   controlled, and admitted counts; pins every scorer and judge request,
   response, model, endpoint, and receipt; and accounts for every candidate
   admitted by its production floor.
6. The assertion set contains no control-arm candidate. The 69 baseline controls
   and every new control remain resolvable in pinned qualification evidence.
7. Every `broadMatch` and `narrowMatch` carries direction-specific evidence,
   and every `relatedMatch` remains non-traversable by default.
8. The publication decision approves every included source for the public
   package and records each applicable condition.
9. Automated explorer checks reconcile displayed and filtered counts to the
   canonical Atlas for every ring, source, release, native or cross-vocabulary
   relation, predicate, evidence class, lifecycle state, language, and subject
   participation value. Every assertion remains reachable through the explorer
   and downloadable data.
10. Search ranks an exact identifier or preferred label first and returns the
    expected concept within the top five for alternate labels, recognized
    variants, normalized punctuation and spacing, useful prefixes, and the
    release's reviewed one-edit typo cases.
11. The complete explorer, indexes, filters, hierarchy views, and evidence views
    reproduce from the canonical Atlas and planning index.
12. Adding a release without changing product policy leaves downstream document
    tagging and document-search behavior unchanged. The Atlas explorer and
    indexes expose the newly published vocabulary facts.

## 16. Limits this release does not clear

A release is trustworthy partly because it states what it does not establish.
Three limits carry forward from the design proposal and addendum. None blocks
v1; each bounds what a consumer may conclude from it.

**16.1 Validator independence is evidenced, not enforced.** Each machine proof
pins provider, model identifier, endpoint, sealed input digest, and
independence group. Sealing an `endpointHost` is a record, not a guarantee: a
producer running two cosmetically distinct model families against one endpoint
still qualifies a mapping. Binding the provider identity to something the
producer cannot freely choose needs signed validator attestations under an
independently pinned authority policy, and that needs a Crosswalk schema
revision v1 does not attempt (design proposal §7 item 1). The threshold that
forces the work is registry scale — roughly 30 sources — and v1 has six. **No
check in §8 or §15 may be read as proving that two validators were
independent.** They prove the run recorded which group each call belonged to.

**16.2 Direction-typed relations remain a separately scored class.** V1's
hierarchy-aware runs supply the balanced parent-and-child context whose absence
the pilot flagged, and preserving both the label-only baseline and the new
result makes comparison possible (§11). The production reruns also change
candidate coverage, scoring, and catalogs, so they do not isolate hierarchy
context; a causal claim requires an otherwise-identical paired run over one
candidate set. Until that question is measured, `broadMatch` and `narrowMatch`
remain their own evaluation class. Control-arm evidence supports the caution:
17 of 211 directional agreements in the baseline runs were control candidates,
or 8.1%.

**16.3 `relatedMatch` is the weakest evidenced class in the Atlas.** 52 of the
87 `related` agreements in the baseline runs were control-arm rows — 60% of the
class — because a negative control or sibling distractor genuinely is
"associated but neither equivalent nor hierarchically ordered." The class
therefore discriminates far more weakly than any other. V1 publishes
`relatedMatch` as a full typed assertion with complete evidence and grants it
**no default traversal** (§5). A consumer that wants to traverse associative
links opts in through its own retrieval policy and owns that choice.
