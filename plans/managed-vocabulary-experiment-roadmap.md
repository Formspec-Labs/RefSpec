<!-- markdownlint-disable MD013 -->

# Managed vocabulary experiment roadmap

> **Status:** Active execution roadmap
>
> **Date:** 2026-07-29
>
> **Implemented baseline:** [Vocabulary management and lookup separation baseline](vocabulary-management-lookup-separation-plan.md)
>
> **Completed prerequisite:** [RefSpec and Rulespec vocabulary gap closure plan](vocabulary-gap-closure-plan.md)
>
> **Active portfolio expansion:** [Active Spicy Regs controlled-resource import plan](active-profile-controlled-resource-import-plan.md)
>
> **Historical reference:** [Early RefSpec implementation plan](implementation-plan.md)
>
> **Product-boundary clarification (2026-07-31):** This roadmap remains active
> for managed-vocabulary research inside RefSpec. The
> [product-boundary and atlas reconciliation plan](2026-07-31-refspec-product-boundary-and-atlas-reconciliation-plan.md)
> supersedes its older ownership and promotion language. RefSpec publishes
> managed releases and static atlas files; Rulespec Extrapolator owns derived
> assertions and accepted-output decisions; SpicySearch owns query processing,
> indexes, and ranking.

## Decision

Move quickly through complex, real-world vocabulary experiments while keeping
the few controls that protect the result.

Rulespec Core defines portable semantic meaning. RefSpec manages exact
vocabulary sources, imports, expressions, releases, crosswalk evidence, static
atlas publication, and release history. SpicyRegs owns document capture and
source observations. Rulespec Extrapolator owns evidence-bound derived
assertions and accepted-output decisions. SpicySearch consumes the published
files to build indexes, retrieve and rank candidates, and measure search value.

The early implementation plan remains useful as a capability inventory. It no
longer sets current sequence or release gates.

## 1. Two operating lanes

| | Experiment lane | Release and adoption lane |
| --- | --- | --- |
| Purpose | Learn whether an approach works | Publish a stable release or authorize use beyond machine-qualified `searchOnly` discovery |
| Data | Development data | Exact release inputs; an independently adjudicated sealed holdout only for quality or adoption claims |
| Output | Candidates only; `developmentOnly` and `candidateUseOnly` | A managed release or atlas, or output selected by Rulespec Extrapolator |
| Required record | One generated experiment manifest | Full configuration, evaluation, conformance, and release records; product-specific promotion records when applicable |
| Checks | Focused tests for the changed path and manifest reproducibility | Full RefSpec, Rulespec, package, cross-repository, rollback, and release gates |
| Qualification | Research decision by the experiment owner | Two machine validators with distinct actors, independence groups, providers, provider model IDs, and responses, plus deterministic checks for `searchOnly`; any stronger adoption gate is separate |
| Claim | Comparative development evidence | Published conformance, quality, compatibility, or readiness claim |

Most work stays in the experiment lane. Release and adoption controls apply
once, after a result earns them.

### 1.1 Controls that always apply

Every experiment must preserve:

- publisher-issued concept, scheme, and release identity;
- multilingual labels, aliases, notes, notation, hierarchy, mappings, and
  lifecycle data without silent loss;
- exact source, managed-release, expression-corpus, index, dataset, and code
  digests;
- source, parsed, indexed, excluded, and failed coverage counts;
- separation between the logical expression corpus and physical lookup index;
- candidate concept, expression, channel, score, rank, and truncation lineage;
- development and holdout separation;
- candidate-only output;
- stage-specific measures; and
- a declared baseline, hypothesis, decision threshold, and stop rule.

These controls prevent failures already reproduced in the playground. They do
not require a production release process.

### 1.2 Work deferred until release or stronger adoption

An ordinary experiment does not require:

- a separate stable-environment decision; RefSpec may generate the local `developmentOnly`
  candidate selection needed to open the managed bundle;
- complete accepted-output permission rows;
- manually authored Rulespec attestations, local adoptions, or accepted
  assignments beyond any generated records that prove the local bundle is
  candidate-use eligible;
- release validation beyond the automatically generated checks needed to open
  the local managed bundle;
- sealed gold;
- public Rulespec or RefSpec releases;
- a requirement-to-test entry for each experimental field;
- rollback proof for a disposable index;
- the full generated-target and cross-repository suites; or
- a new rights review beyond the recorded playground risk unless the proposed
  use introduces a distinct privacy, access, security, or distribution risk.

The applicable release and conformance controls become mandatory when an
experiment enters the release and adoption lane. Human feedback and manually
authored attestations remain optional later inputs unless a separately adopted
policy defines a stronger use than `searchOnly`.

### 1.3 Release and stronger-adoption triggers

Publishing a digest-pinned managed release or machine-qualified `searchOnly`
atlas to another product enters this lane for release and cross-repository
gates. It does not require prior human approval. Apply the stronger adoption
controls when any of these conditions holds:

- the team selects it for a stable environment;
- output may leave `developmentOnly`, `candidateUseOnly`, or `searchOnly`;
- an adapter becomes reusable managed-registry infrastructure;
- the team will publish an accuracy, conformance, compatibility, or readiness
  claim;
- conflicting official sources require an authority decision; or
- the result changes a managed release, permission policy, or portable semantic
  record.

## 2. Fast experiment loop

One command should run the common lookup experiment:

```text
spicy-regs vocab-experiment run <experiment-definition>
```

The command is a target interface, not a required public command name. It
should generate all bookkeeping rather than ask the researcher to author
release records.

### 2.1 Inputs

An experiment definition contains only behavior-changing choices:

- hypothesis and decision rule;
- managed release and expression corpus;
- development dataset;
- lexical, BM25, dense, hybrid, or reranking channels;
- model, prompt, provider, and budget when applicable;
- random seed; and
- approved baseline and stop rule.

### 2.2 Outputs

Each run writes one directory:

```text
experiments/<experiment-id>/
├── experiment.json
├── candidates.parquet
├── metrics.json
└── decision.md
```

`experiment.json` records the hypothesis, decision rule, code revision, exact
input and configuration digests, seed, and the fixed
`developmentOnly`/`candidateUseOnly` state.

`candidates.parquet` records every item, candidate concept IRI, release,
indexed expression, channel, score, rank, and truncation point needed to
reproduce a metric or inspect a miss.

`metrics.json` reports target availability, full-universe gold rank, Recall@K,
ranking measures, abstention, latency, cost, and comparison with the approved
baseline. It reports source and facet strata separately when they apply.

`decision.md` states `continue`, `stop`, or `investigate`, explains the
evidence, and names the next variable to change. Weak or mixed evidence
defaults to `stop` or `investigate`, not adoption.

### 2.3 Fast-loop exit

An experiment finishes when:

1. another person can reproduce its metrics from `experiment.json`;
2. the candidates retain complete release, expression, channel, and rank
   lineage;
3. the report compares the approved baseline and applies the declared stop
   rule; and
4. no output can enter an accepted release or product path.

Focused checks should finish fast enough to support repeated daily runs.

## 3. Execution gates

### Gate 1 — Run real lookup from the managed release

Use the existing 629-concept Federal Register development release. Build
verified lexical, BM25, exact-dense, and hybrid indexes from its RefSpec
expression corpus. Run them against the 35 permanent development-only items.

**Exit:** Every channel produces comparable metrics and complete candidate
lineage through the fast-loop artifacts.

### Gate 2 — Remove remaining legacy authority

Make the managed release the default input for vocabulary experiments. Derive
facets and eligible expressions from RefSpec records. Quarantine the fused
registry, label-derived concept identifiers, `broader_id`, and `replaced_by`
paths as migration readers or non-release comparators.

**Exit:** No normal experiment path treats a fused registry as authoritative
or emits legacy data as conforming output.

### Gate 3 — Stress the managed-registry model

Import ELSST Versions 5 and 6 as two complete releases. Preserve all 15
languages, hierarchy, notes, release-specific and stable source identities,
deprecation, and replacement links. Project the three Version 6 deprecations
through the Rulespec lifecycle model and prove that deprecated expressions
remain inspectable without entering the current-assignment candidate view.

Then import the current Federal Register API as a distribution distinct from
the historical thesaurus and produce a real reconciliation report.

**Exit:** Real imports preserve conflicts, languages, hierarchy, authored
mappings when present, and release and cross-version identity without forming
an unreviewed union. A source with no mappings records an explicit zero-coverage
row rather than inventing them.

### Gate 4 — Test product value

Freeze the selected registry and mapping releases after development work.
Independently adjudicate and seal a holdout. Evaluate target availability,
Recall@K, ranking, abstention, grounding, latency, cost, and reviewer effort as
separate stages.

**Exit:** One frozen configuration receives an explicit pass or failure. A
drawn but unadjudicated holdout authorizes nothing.

### Gate 5 — Exercise promotion

If Gate 4 passes, promote one narrow use through exact configuration,
evaluation, Rulespec Extrapolator selection, product-specific deployment, and
rollback evidence. The team may also refuse promotion and record why. This gate
does not apply to machine-qualified `searchOnly` atlas publication.

**Exit:** Accepted output follows the complete authorization chain, or the
system proves that it can abstain safely.

### Gate 6 — Publish and expand

Publish immutable Rulespec and RefSpec prereleases only when an external
consumer needs stable resolution. Add vocabulary adapters one at a time and
repeat the experiment-to-release loop.

**Exit:** A clean consumer resolves exact versions and digests without an
editable local checkout.

### 3.1 Execution checkpoint — 2026-07-29

The first real Gate 1 run used the Federal Register thesaurus source at
`sha256:d5e013336d4179790e8d6574d4dc9d8cfcb10ce76af202ff4db068617eb8fd30`.
RefSpec produced and Spicy Regs opened:

- publication release
  `urn:ref:fr-thesaurus-1995:publication:development-v1`;
- managed-release manifest
  `sha256:c4b005040797e7cce1fd23e0682a43b17d65dd8e1b0ab3041c99042fb37c96b7`;
- expression corpus
  `sha256:b822850202b2f555791ff27721633cf59bbc76dc0507719ce71905f0ccc3c5e3`;
- 629 exact release members, 2,213 indexed expressions, and 1,477 normalized
  relations; and
- a project determination that records the source-rights uncertainty but
  permits acquisition, storage, indexing, model use, display, retention, and
  redistribution for this experiment. Rights uncertainty did not remove or
  suppress vocabulary content.

The first consumer attempt found a portable boundary defect before ranking:
`sourcePath` preserved where an expression came from but did not independently
state its SKOS meaning. RefSpec now requires `semanticProperty`, includes it in
expression identity, and tests the `sourcePath` plus semantic-property case.
The rebuilt release exposes all 629 preferred-label expressions without
discarding their source paths.

The first pass also proved why the fused-registry adjudication could not remain
the benchmark. Only 2 of 35 development labels were exact aliases in the
managed release, while all five formerly adequate answers named fused
identifiers outside that release. The runner refused to rebind them by label.

The active development set now reuses the 35 pinned source artifacts, evidence
spans, and selected segments, but no fused identifier or verdict. It contains:

- 32 represented meanings with 42 exact managed member IRIs;
- 3 explicit `notRepresented` meanings, excluded from reachable-candidate
  recall;
- 2 exact and 10 close targets adequate for this provisional development
  comparison;
- 24 `targetBroaderThanGold` and 6 `related` targets retained as directional
  diagnostics; and
- exact source-data, managed-release, reference-release, import-snapshot, and
  expression-corpus pins.

The target set was prepared after candidate runs were visible. It is not
independently reviewed or sealed and cannot support an accuracy or adoption
claim. That is acceptable in the experiment lane.

At candidate limit 12, the release-native baseline is:

| Configuration | Represented items retrieved | Exact/close items kept | Mean best-target rank |
| --- | ---: | ---: | ---: |
| v1 | 14/32 | 6/12 | 6.07 |
| v2 | 18/32 | 7/12 | 4.17 |
| v2 without quotas | 18/32 | 7/12 | 4.17 |
| BM25 | 11/32 | 6/12 | 4.73 |
| BM25 plus char n-gram | 16/32 | 6/12 | 4.31 |
| dense | 25/32 | 10/12 | 2.84 |
| v2 plus dense | 28/32 | 11/12 | 4.11 |
| BM25 plus char n-gram plus dense | 23/32 | 9/12 | 3.09 |

Each run emitted exactly `experiment.json`, `candidates.parquet`,
`metrics.json`, and `decision.md`. Candidate rows retain the managed-release,
expression-corpus, lookup-index, expression, channel, score kind, native score
when available, rank, truncation, dataset, and code identities.

The result remains **investigate**, not adopt. Dense retrieval materially
improves development recall, and v2 plus dense has the widest represented-item
coverage. However, all 35 dense queries exceed the model's 512-token input
ceiling and are recorded as truncated.

The next controlled run kept the release, targets, model, index, candidate
limit, and fusion rule fixed. It added `Cw`, a separate dense channel that:

- restores `evidence_N` fields to numeric source order;
- covers every evidence character once with contiguous, zero-overlap source
  windows;
- verifies every window against the model's native 512-token ceiling; and
- keeps the winning window ID, source field and offsets, text digest, token
  count, native score, and candidate lineage.

The local run `gate1-dense-window-semantic-v2` produced 553 queries from 476
exact evidence fields. Its query-set digest is
`sha256:8dde29b0ddc757b4388979f910ccabfa54a01552ae40c0d1b47b0759f370a7b5`.
Thirty fields needed more than one window. The windows covered all 244,273
source characters, and none exceeded the model limit.

| Paired configuration | Whole segment | Complete windows | Change |
| --- | ---: | ---: | ---: |
| dense — represented items | 25/32 | 27/32 | +2 |
| dense — exact/close items | 10/12 | 12/12 | +2 |
| dense — mean best-target rank | 2.84 | 4.44 | worse |
| v2 plus dense — represented items | 28/32 | 24/32 | -4 |
| v2 plus dense — exact/close items | 11/12 | 10/12 | -1 |
| BM25 plus char n-gram plus dense — represented items | 23/32 | 22/32 | -1 |
| BM25 plus char n-gram plus dense — exact/close items | 9/12 | 9/12 | no change |

Complete windows recovered later evidence for PFAS and immigration and retained
all 12 development-adequate targets in the dense-only arm. They also admitted
more incidental high-scoring fragments, worsened average rank, and performed
poorly when their max-pooled ranking entered equal-weight reciprocal-rank
fusion. The query representation and the fusion rule are therefore separate
failure points.

The next representation-only run,
`gate1-dense-packed-semantic-v3`, compared `C`, `Cw`, and a new `Cp` arm
outside fusion. `Cp` packed numerically ordered evidence fields into contiguous
zero-overlap windows. It used explicit model-token budgets of 0 for metadata,
512 for evidence including special tokens, and 0 for overlap. Its 151 queries
covered all 244,273 source characters once with no truncation, compared with
553 `Cw` queries. The exact query-set digest is
`sha256:84a46e32fe1cfe9b21ad3885d21bd67ce24097b8ec1428feea9e6bfaac348051`.

The packing efficiency did not preserve retrieval quality:

| Dense representation | Represented items retrieved | Exact/close items kept | Mean best-target rank |
| --- | ---: | ---: | ---: |
| `C` whole segment | 25/32 | 10/12 | 2.84 |
| `Cw` fieldwise windows | 27/32 | 12/12 | 4.44 |
| `Cp` packed windows | 24/32 | 11/12 | 3.00 |

`Cp` is a retained failed comparator. Maximum-length cross-field packing
blended short, distinct meanings and lost PFAS, administrative burden, human
rights, judicial power, oranges and grapefruit, personal jurisdiction,
retirement plans, and true threats. Freeze `Cw` as the current complete dense
query representation. The next lookup experiment may change scoring or
reranking, but it must not also change the query representation.

Independent machine validation belongs at the publication boundary after the
development loop selects a configuration worth testing. Human feedback may be
appended later and can inform a future immutable release; it is not a
prerequisite for `searchOnly`.

Gate 1 is mechanically complete: lexical, BM25, dense, and hybrid paths run
from the managed release and emit comparable, lineage-complete artifacts
against usable managed targets. Gate 2 is substantially complete for this
runner: the normal path reads neither the fused registry nor its resolved
target files; both require separate migration flags.

The first Gate 2 audit then found a portable permission failure. Spicy Regs
could open the 629-member release and assign every member any non-empty
caller-supplied facet. It also accepted any known assignment role without
checking the selected `OutputProfile`. RefSpec now defines `REF-VOC-032` and
`REF-TEST-175`. `ManagedReleaseView.require_candidate_use` resolves one exact
selected release-permission row, compatible EnrichmentProfile facet, role and
resource route, exact release and import pins, and passing coverage before a
consumer may iterate candidates.

Spicy Regs now requests and records that RefSpec authorization. The real bundle
returns all 629 preferred-label members for
`general-subject + assignmentPrimary + document`; entity, mention, and event
requests fail before iteration. A model result that changes the authorized
role to mention is rejected before a Rulespec assignment is emitted. Spicy's
local `subject` selector route remains separately identified lookup metadata
and cannot relabel the RefSpec permission facet or release records.

Gate 3 used ELSST rather than another single-release source. CESSDA's
official complete Turtle distributions provide a useful two-release test:

| Release | Source bytes | SHA-256 | Concepts | Preferred labels | Languages |
| --- | ---: | --- | ---: | ---: | ---: |
| Version 5 | 19,167,985 | `d0d2514d7535309b82cc6966ee6e2b5794cf6f390896a5175f41dff4a02e03b7` | 3,435 | 51,413 | 15 |
| Version 6 | 19,915,491 | `c362aec545db916ecb67af0eb9b8b4cecac1cb2118a717b69d8e6dad5591aa95` | 3,470 | 51,848 | 15 |

Version 6 retains 37 deprecated concepts, nine replacement links, 3,393
broader edges, 5,696 related edges, and 3,422 `owl:priorVersion` links. Its
three new deprecations are `HOUSEHOLDERS`, `MORBIDITY`, and
`DEMOGRAPHIC STATISTICS`; the source identifies replacements for all three.
The experiment retains the complete raw releases outside Git and uses a
small source-derived fixture in ordinary tests.

This source exposed the next portable boundary before the import was built.
The managed-release reader retained status in `concept_labels`, but its public
expression view discarded that status and treated every expression as a
current candidate. `REF-VOC-033` and `REF-TEST-176` now require a complete
evidence iterator and a separate current-assignment candidate iterator.
RefSpec preserves exact label role and opaque source status, excludes retiring
Rulespec lifecycle predecessors under their exact release pin, and uses known
source deprecation tokens only to narrow eligibility. A source status cannot
grant candidate or accepted-output authority. The candidate iterator also
filters the expression corpus to the exact release and import authorized by
the selected permission row, so an R6 permission cannot expose R5 expressions
from a multi-release bundle.

ELSST also requires explicit preservation of `dct:isVersionOf` and
`owl:priorVersion`. The importer does not infer cross-version identity from
labels. The completed projection preserves both source relations directly and
uses those assertions for cross-version joins; it required no separate
normalized identity record.

ELSST is published under CC BY-SA 4.0. The import records the license and
CESSDA attribution, but licensing does not gate playground acquisition,
indexing, or experimental lookup.

The first ELSST iteration is complete locally. RefSpec now has an explicit
content-addressed acquisition adapter, an RDFLib Turtle reader, and two
source-derived ordinary-test fixtures. The reader preserves exact
release-specific concept IRIs, stable `dct:isVersionOf` IRIs,
`owl:priorVersion` IRIs, multilingual labels, supported notes, typed notation
when present, hierarchy and associative relations, deprecation, replacement
links, DDI identifiers, issue times, and modification times.

Both complete distributions were acquired into the ignored experiment store
and reverified against their byte-length and SHA-256 pins. The opt-in real
suite parsed 236,925 R5 triples and 239,821 R6 triples, including 51,540
identifier assertions in each release. Its identity-only comparison—without
using labels or URI-shape guesses—found:

- 3,435 retained stable concept identities;
- 35 R6 additions;
- three newly deprecated R6 concepts; and
- nine R6 replacement pairs, including the three new deprecations.

The complete Gate 3 ELSST run now passes. RefSpec projects those exact
releases and the three new transitions through the Rulespec lifecycle model.
It keeps the six older replacement links as source evidence without inventing
predecessor releases outside the two-release comparison. The resulting
managed bundle contains:

- 6,905 concepts across two exact releases;
- 308,639 indexed expressions;
- 176,664 normalized concept-label rows;
- 24,844 normalized hierarchy and associative-relation rows; and
- six lifecycle participant rows for three source-derived replacements.

The import gate independently inventories the raw Turtle, parsed vocabulary,
and indexed output. Every required feature has identical assertion counts and
digests at all three stages, with zero exclusions and failures. Version 5
contains 87,766 label, 13,916 note, 6,722 hierarchy, 5,640 associative,
34 status, 12 replacement, 58,399 identifier, and 7,363 membership
assertions. Version 6 contains 88,928 label, 15,009 note, 6,786 hierarchy,
5,696 associative, 37 status, 18 replacement, 58,399 identifier, and 7,439
membership assertions. Neither source contains notation or SKOS mapping
assertions, so those coverage rows correctly remain zero.

The first compact full-source attempt caught 15 language-tagged scheme
identifiers that the parser preserved but the Rulespec graph omitted. The
projector now carries exact scheme identifiers; omission and tampering fail
ordinary tests. The first semantically complete run then exposed an
unrealistic provisional performance limit. Removing a needless
seed-to-expression index for non-label expressions reduced peak memory by
211,091,456 bytes. The passing scale gate writes, reopens, validates, and
iterates the 308,639-expression corpus in 343.264 seconds at a peak of
2,766,995,456 bytes.

The exact logical expression-corpus digest is
`sha256:f1692767e562c9d60573b039940e269289fa6f705b8749bc6737f3a26a1fbedf`.
The real Rulespec gate authorizes only the selected local Version 6
candidate-use decision. Deprecated expressions remain inspectable but do not
enter the current candidate view. The
[scale evidence](../research/evidence/elsst-r5-r6-managed-release-2026-07-29/README.md)
records source, release, import, coverage, graph, corpus, receipt, and bundle
digests.

The current Federal Register API comparison is also complete. Its exact
capture contains 1,044 `thesaurus` and 6,723 `ad_hoc` records, including 76
slug-collision groups and three empty slugs. Only 619 preferred labels overlap
the 1995 source. The conforming reconciliation report therefore records
`unresolved`, asserts no concept mappings, selects neither input, and
authorizes no union. Capture-local source identity uses the capture digest,
collection, and source ordinal; labels and slugs cannot become identifiers.
The
[reconciliation evidence](../research/evidence/federal-register-topics-reconciliation-2026-07-29/README.md)
preserves the exact counts and report digest.

Spicy Regs now exercises the open-set path on the four source-grounded ELSST
`notRepresented` development rows. Each row becomes a language-tagged
`rkaf:openLabel` assertion only after one exact OutputProfile row authorizes
candidate use. Its EvidenceBinding resolves to a real Rulespec Artifact,
SourceFragment, position selector, quote selector, and ExtractionActivity
with exact source and text digests. The combined graph passes the pinned
Rulespec validator. These rows remain `developmentOnly`,
`proposedUnsealed`, and outside reachable-candidate recall; accepted-output
authorization still fails.

The following Gate 3 result records the pre-split accepted-output implementation
as migration evidence; current ownership follows the clarification at the top
of this roadmap.

The accepted-output boundary also uses the real release-graph receipt issuer.
A source-derived Federal managed release reaches the Spicy consumer only
after the exact Rulespec graph, REF record digests, test-only gold,
evaluation, deployment, permissions, and live-issued authorization
evaluations agree. Wrong tuples, cross-row assembly, candidate-only ELSST,
and every release, import, expression, index, profile, or receipt drift fail.
This proves the gate mechanics. The governance and gold remain explicitly
test-only, so it is not a production promotion claim.

Gate 3 is complete for the managed-vocabulary experiment. It proves
multilingual import, hierarchy, lifecycle history, exact source identity,
candidate selection, conflict preservation, and fail-closed reconciliation
at real scale. It does not claim product accuracy, a sealed holdout,
production deployment, or a real cross-scheme mapping: the selected native
sources contain no authored SKOS mapping assertions.

## 4. Specification feedback rule

The experiment may change SpicySearch retrieval, ranking, models, prompts,
indexes, and product interaction freely within the experiment lane. SpicyRegs
experiments remain limited to document capture, source observations, and the
diagnostic candidate seam.

Change RefSpec or Rulespec when:

- a real source exposes semantic loss or ambiguous ownership;
- identity, lifecycle, mapping, permission, or release behavior cannot be
  represented;
- two independent uses need the same stable interface; or
- a reproduced failure shows that a validation rule must apply across
  implementations.

Promote a new rule only after two real uses demonstrate its durability or one
reproduced failure proves it necessary. Add focused positive and negative
fixtures with the rule. Ranking, latency, model, prompting, and provider
failures stay in SpicySearch unless they expose a portable boundary defect.

## 5. Working terminology

Use concrete terms in new prose:

| Use | Meaning |
| --- | --- |
| Rulespec semantic rules | Portable meaning and validation owned by Rulespec |
| RefSpec schema | Structure and validation for an REF-owned record |
| Managed-release interface | The data RefSpec provides to a lookup consumer |
| Validation rule | One executable requirement |
| Experiment protocol | Inputs, outputs, measures, and decision rule for a development run |
| Configuration | Exact behavior-changing inputs for a frozen evaluation |
| Promotion gate | Checks required before stable or accepted use |

Reserve **contract** for a stable interface shared by independently versioned
producers and consumers that requires coordinated migration. Existing machine
field names remain unchanged until a breaking release gives us a reason to
rename them.

## 6. Current scope

This roadmap aims to prove a difficult approach, not a small toy:

- distinct and conflicting official distributions;
- multilingual and polyhierarchical vocabularies;
- typed facets and cross-scheme mappings;
- exact, lexical, sparse, dense, and hybrid retrieval;
- missing-target detection and open-set abstention;
- candidate and accepted-output separation; and
- measurable product value.

The current scope excludes the early implementation plan's three-matter
regulatory-history release, inferred relationships, policy threads, broad
query product, and production-service program. Those capabilities may return
through separate plans after managed vocabulary lookup proves useful.

The
[standards composition and graph extensibility plan](standards-composition-and-graph-extensibility-plan.md)
records source-triggered interoperability work. It adds no current standard
dependency and does not change this roadmap's sequence.
