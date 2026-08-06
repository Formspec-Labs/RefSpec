# Vocabulary Atlas English relation discovery and judgment proposal

**Date:** 2026-08-05  
**Status:** Proposed for review after the candidate experiment. Production
integration, paid scoring, and paid judging remain on hold.  
**Applies to:** The six Atlas v1 subject-vocabulary pairs and a successor to
the current label-oriented candidate policy.

## Recommendation

Amend the still-unpublished `v1.0.0-rc1` qualification plan with a versioned,
English-only candidate snapshot that separates discovery from judgment and
keeps the relation graph small enough to explain:

1. Seek plausible **direct, nonredundant cross-vocabulary mappings**. Do not
   seek every pair that can co-occur or connect through an existing graph path.
   A path such as `teacher -> school -> education` is preferable to an extra
   generic `teacher relatedMatch education` edge.
2. Use 3,280 preferred ICPSR descriptors as mapping endpoints. Of the 480
   nonpreferred records, fold the 478 with an unambiguous native `use`
   relation onto 387 preferred descriptors. Preserve the two exceptional
   records for source reconciliation; do not guess their alias target. None of
   the 480 becomes another mapping endpoint.
3. Build an add-only deterministic floor from practical lexical retrieval at
   K = 3 and fielded sparse retrieval plus mutual-anchor graph expansion at
   K = 1. Add the plain, symmetric five-view
   `BAAI/bge-small-en-v1.5` population through K = 50.
4. Preserve every signal and rank that found a pair. A dense model, reranker,
   or later arm may add a pair; none may remove one before judgment.
5. Send every selected semantic candidate to two blind model families in
   spreadsheet-shaped groups of at most 25 rows through the providers' Batch
   endpoints.
6. Use deterministic retrieval evidence to order work. Do not pay an LLM
   scorer to reorder a queue that both judges will process in full.
7. Admit `relatedMatch` only when the association itself is a useful direct
   vocabulary edge and the existing native plus admitted mapping graph does
   not already express it adequately. Keep stronger direct exact and hierarchy
   mappings even when a weaker path exists.
8. Add adjudication only when both blind judges support a direct relation but
   disagree on relation kind or hierarchy direction.

The proposed bounded dense configuration is **K = 50**. In the sealed
pre-access-term corpus, one directly useful hierarchy candidate appears at
exact rank 50 in the fixed tail sample; an earlier measured cutoff would
discard it. The ICPSR access-term projection changes the concept text, so the
five-view BGE vectors, ranks, K50 pair set, and cost receipt must be regenerated
before integration. That reproduction either confirms K50 or supplies the
evidence for a revised cutoff. K50 is not a claim that every thematic
association has been found. The residual sentinel and the directness rule show
why the release must define the desired graph, not chase every possible
association.

This proposal completes the experimental recommendation and defines the
remaining integration gates. Approval would authorize implementation of the
new snapshot and judgment policies plus one bounded protocol-acceptance pilot.
It would not authorize a production catalog switch or a full paid campaign.

## What the system will do

### What goes in

- the exact six English source releases already pinned by Atlas v1;
- preferred and alternate labels;
- definitions and scope notes;
- local identifiers;
- bounded native parents and children; and
- the exact language, model, tokenizer, implementation, configuration, and
  input digests for every retrieval arm.

### What happens

The local finder builds one canonical union. Lexical methods cover surface
variation and aliases. Sparse retrieval covers phrases, definitions, scope
notes, and hierarchy text. Anchor-gated graph expansion adds aligned
neighborhoods. Five separately ranked BGE views add semantic paraphrases,
institutional wording differences, compounds, and useful associations.

The finder operates on preferred descriptors rather than every lexical access
record. Source-declared access terms are folded onto their preferred concept
through the publisher's own `use` relation. This preserves `abduction` as
evidence for ICPSR `kidnapping`, for example, without creating a second mapping
endpoint. Endpoint, foldable-alias, exceptional-record, and alias-target counts
remain separate.

Controls enter only after the semantic union is complete. Judges never see
generator class, rank, control status, proposed relation, or another judge's
answer. Two blind judges first classify semantic relation and then distinguish
a useful direct association from a generic thematic connection. A deterministic
path check supplies separate redundancy evidence after the blind semantic
decision; it does not erase a stronger exact or hierarchical assertion.

### What comes out

- one immutable retrieval snapshot with complete candidate and signal
  accounting;
- two independent judgment receipts for every semantic candidate and control;
- a path-redundancy disposition for every supported candidate;
- targeted adjudication receipts for supported relation-type conflicts;
- complete admitted, rejected, abstained, controlled, and incomplete counts;
  and
- a relation bundle containing only assertions admitted by the governed
  agreement policy.

### How we check it

The build must reproduce the same pair set and complete row bytes after input
reordering and a fresh process. It must recover every endpoint from the exact
source releases, reconcile 3,280 ICPSR descriptors, 478 foldable access terms,
387 distinct preferred alias targets, and two exceptional nonpreferred records,
cover all 582 historical typed mappings as evidence, reopen every raw provider
receipt, and reconcile every selected candidate to a final disposition before
a release can use the result.

## Candidate types and their discovery paths

Different retrieval challenges need different evidence channels. They do not
need separate production models.

| Retrieval challenge | Primary discovery path | Judgment responsibility |
| --- | --- | --- |
| Stable identity or shared code | Exact normalized identifier and publisher crosswalk | Confirm meaning; never infer identity from a code pattern alone |
| Exact lexical variation | Normalization, individual-label equality, Levenshtein, token-set and character similarity | Distinguish `same` from `near_same` and homonyms |
| Alias, synonym, regional or institutional wording | Source-governed access-term folding, individual-label comparison, sparse label retrieval, BGE views | Decide equivalence, hierarchy, association, or no relation |
| Acronym or abbreviation | Sparse and semantic views; the dedicated acronym control remains an add-only diagnostic until real-Atlas transfer is measured | Confirm the expansion in vocabulary context |
| Definition or scope paraphrase | Fielded sparse definition/scope views and BGE definition-first view | Use the supplied facts, with `insufficient_evidence` available |
| Broader, narrower, or granularity shift | Hierarchy text, anchor-gated graph expansion, semantic views | Determine direction from balanced context, then check whether a typed path already supplies the same useful navigation |
| Compound concept | Token/character methods plus contextual semantic views | Decide containment versus association |
| Associative `relatedMatch` | Semantic signals plus a post-judgment native/cross-vocabulary path check | Require a direct, useful, nonredundant association; keep it non-traversable by default |
| Sparse or ambiguous metadata | Multiple independent views and vocabulary context | Prefer abstention to invented specificity |

The finder records these as overlapping retrieval challenges. The mapping
relation remains a separate result decided by the judges.

## Verified experimental evidence

### The deterministic floor is the strongest economical baseline

After the source-governed ICPSR access-term projection, the exact lexical K3
plus sparse/mutual-graph K1 union contains 214,271 pairs and all 582 sealed
Atlas mappings:

- 121/121 `exactMatch`;
- 232/232 `closeMatch`;
- 75/75 `broadMatch`;
- 119/119 `narrowMatch`; and
- 35/35 `relatedMatch`.

Its pair-set digest is
`sha256:dd1390495706da7115f59915f496ac9e766eb928c9edf1d3d60702c9680475fd`.
Lexical retrieval contributes 195,245 rows and 561 historical mappings;
sparse/graph contributes 35,184 rows and 524 mappings. Their 16,158-row
overlap leaves 179,087 lexical-only and 19,026 sparse-only rows. The two
families remain complementary, especially for directional and associative
relations.

The pre-projection floor contained 210,197 rows at pair-set digest
`sha256:24fc3c81f443596181b9bd0e9d2b663992052c19f383ffd2cd222e60d565ede9`.
The governed projection adds 4,074 net rows (+1.94%), preserves all 582 known
mappings, and keeps exactly 3,280 ICPSR endpoints. This before/after receipt is
historical evidence; the corrected 214,271-row floor governs the next snapshot.

The prior production generator also contains the 582 historical mappings, but
it finds only 196/305 independent OAEI Conference references. That makes the
12,313 prepared catalogs a useful historical receipt, not a sufficient
candidate policy for the new campaign.

### General semantic retrieval adds candidates; directness controls noise

The pre-projection five-view BGE run evaluated labels, structured fields,
natural-language context, definitions first, and hierarchy context in both
directions. The
plain symmetric representation outperformed the tested query prefix and
relation prompt, so K50 means that exact five-view configuration rather than a
generic model name. The selected configuration must now be regenerated on the
corrected projected corpus; old ranks remain comparison evidence, not final
snapshot authority.

The first sealed 120-row real-Atlas review used the original broad rubric and
found 53 potential relations: 44 associative, four target-broader, and five
target-narrower. A separate ranks 26-50 review found 12/60: 11 associative and
one target-narrower. Its actual-rank counts were 3/24 at ranks 26-30, 3/12 at
31-35, 3/8 at 36-40, 1/8 at 41-45, and 2/8 at 46-50. The sole hierarchy row was
`STATE AID` -> `small business tax credit` at exact rank 50.

Those measurements established that BGE finds semantic associations beyond
the lexical/sparse floor. They do **not** select a cutoff under the refined
goal: 55 of the 65 reviewed positives were broad `related` judgments, and many
are thematic shortcuts such as a profession linked directly to its field. The
sealed decisions and counts remain valid evidence for the old rubric; the
direct/nonredundant review is the governing cutoff evidence.

The strict re-review retained 12/65 as direct candidates, classified 52/65 as
generic thematic shortcuts, and found one hierarchy row already represented by
a two-edge typed path. The retained candidates occur at pre-projection BGE
ranks 1, 1, 1, 1, 1, 1, 2, 3, 5, 6, 8, and 50. Eleven therefore occur by K8;
`STATE AID` -> `small business tax credit` is the only retained tail case and
occurs at K50. These are candidates for blind judgment, not asserted mappings.

The pre-projection K50 union contains 1,578,319 pairs, 9.5198% of the
16,579,315 preferred-descriptor Cartesian space. A fixed 60-row sentinel
sampled the 15,000,996 pairs outside that union, with 15 rows from each nonempty
pair population. The
first directness pass retained one tentative association—`Critical
infrastructure` with `MANUFACTURING INDUSTRIES`—and rejected 59. That row is
useful as a design challenge, but it depends on the intermediate idea of
`critical manufacturing` rather than a direct relation between the two broad
displayed concepts. The final graph-minimal proposal therefore keeps it as a
borderline generic-thematic control, not a required edge or cutoff miss. The
sealed one-row tentative verdict remains historical evidence of the stricter
rubric's boundary.

All three samples are deterministic and blind to relation labels. Their equal
per-pair and rank-stratified allocations are deliberately diagnostic. They do
not estimate pool precision, population prevalence, or objective recall.

### Independent benchmarks support heterogeneous, add-only retrieval

- OAEI Conference: the old semantic rules find 196/305. Heterogeneous sparse,
  provider, learned-sparse, and dense arms can reach 305/305; the exact
  no-provider minimum found in that benchmark uses Nomic plus MiniCOIL and
  contains 116,909 pairs.
- Corrected OAEI Anatomy: sparse plus general BGE reaches 1,516/1,516 at K50.
  This supports source-text resolution and semantic complementarity. It does
  not justify a biomedical specialist in a policy-domain production floor.
- OAEI BeyondEquivalence: the staged deterministic and Open English WordNet
  pipeline reaches all 1,292 typed challenge relations at depth 6. On the real
  Atlas, WordNet depth 4 adds 3,208,046 unique rows and zero unique historical
  mappings over the selected floor. WordNet therefore remains a typed
  diagnostic and targeted rescue path.
- Google and OpenAI embedding arms jointly reach 305/305 Conference references
  at K20. The bounded provider experiment cost $0.046897820, including one
  successful OpenAI embedding Batch smoke request. Those saved vectors are
  valuable comparative evidence, but they have not demonstrated unique value
  on the six real Atlas pairs and model aliases are weaker release pins than a
  retained local snapshot.
- MiniLM and ColBERT can rescue hard pairs from a wide reservoir. Neither
  appears on the exact Conference Pareto frontier, and neither can recover a
  pair absent from its reservoir. They remain ordering or add-only rescue
  tools, never deleting filters.

### Two blind judgments remain useful; the rubric needs a directness revision

An independent, fixed 108-row audit of the historical judge evidence found:

- all 41 historically admitted non-control pairs remained supported;
- 37/41 retained the exact admitted relation;
- provider-pair support/no-support agreement was 102/108;
- provider-pair exact seven-way agreement was 74/108; and
- of 16 historically rejected pairs the independent reviewer still supported,
  15 arose because both providers supported a relation but disagreed on its
  type or direction.

This supports two blind provider families for the semantic-support boundary
and a targeted relation-type adjudication lane. It does not validate the new
directness boundary: the current rubric explicitly allows generally associated
or neighboring topics. Before production, a versioned successor rubric must
distinguish `directly_related`, `generic_thematic`, and
`redundant_via_existing_path`. A third judge on every row would spend broadly
while the observed uncertainty is concentrated.

## Coverage guarantee

The selected snapshot will give a strong, testable guarantee: it contains
every pair admitted by every declared lexical, sparse, graph, and BGE arm at
its declared cutoff, and it reproduces all known typed Atlas mappings plus the
independent benchmark measurements above.

The six pairwise Cartesian spaces contain 16,579,315 pairs. Enumerating that
entire space is the only literal way to guarantee that no weakly signaled
association exists, but that is not the desired graph. The release seeks the
smallest sufficient set of direct mappings. A concept reached through a valid
native and cross-vocabulary path is covered without an extra generic shortcut;
an exact or directional edge still requires its own direct evidence because
those semantics cannot be inferred from arbitrary paths.

The release guarantee is therefore:

1. complete declared-arm candidate coverage over the 3,280 preferred ICPSR
   descriptors and the other five preferred-descriptor sets;
2. source-governed access terms preserved as alias evidence;
3. every case retained by the strict direct/nonredundant review present at the
   selected boundary;
4. every supported mapping receives a typed-path disposition, with a path used
   as evidence rather than an automatic veto on stronger direct semantics;
5. generic thematic and path-redundant pairs retained as evidence, not graph
   edges; and
6. a deterministic residual sentinel that triggers focused review and, when a
   direct mapping is confirmed, a new add-only arm or deeper ranked experiment.

This is a graph-sufficiency claim with explicit evidence, not a claim that all
16.6 million pairs have a meaningful direct relation.

## Exact cost options under the current protocol

The read-only planner rebuilt full hierarchy-aware candidate payloads and the
same 25-row packing, provider job limits, 50% Batch pricing factor, current
model pins, and conservative 400-output-token-per-row allowance used by the
production runner. It made zero provider calls. These are exact base-pass
comparisons for semantic candidates, not complete spend-authority ceilings or
expected invoices. They exclude controls, conditional adjudication, recovery,
and reserve. They also describe the sealed pre-access-term experiment; the
approved descriptor projection must regenerate the final K50 pair-set digest
and cost receipt before any authority is requested.

| Pre-projection candidate option | Candidates | Two judges only | Current scorer + two judges | Three-pass base requests / jobs |
| --- | ---: | ---: | ---: | ---: |
| Lean floor | 210,197 | $1,111.593521 | $1,843.745645 | 25,230 / 256 |
| Lean + BGE K10 | 474,560 | $2,499.557227 | $4,146.231540 | 56,955 / 554 |
| Lean + BGE K15 | 616,329 | $3,243.923261 | $5,381.054027 | 73,968 / 714 |
| Lean + BGE K20 | 756,866 | $3,981.617081 | $6,604.815817 | 90,834 / 872 |
| Lean + BGE K25 | 895,840 | $4,711.001624 | $7,814.797632 | 107,511 / 1,027 |
| Lean + BGE K50 | 1,578,319 | $8,292.561141 | $13,756.282989 | 189,408 / 1,793 |

The K25 pair-set digest is
`sha256:4e952b9353f6a19cd69bbe225061a6990453645a4671ed57a1c89c9ce3191b9f`.
K15 is
`sha256:8b333d186df553e362ada7913208fdc07bf2f861be26d4427cc14cca69a4e922`.
K50 is
`sha256:7170fea7d540b118f40420d687310137008148cc3ac7b63c996bce1021052275`.

The current 12,313-candidate plan and its $112 authority describe a different
candidate policy. They must remain reopenable as historical planning evidence;
they must not authorize a larger successor catalog.

## Five cost and reliability improvements

### 1. Use 25-row Batch requests

Keep the implemented spreadsheet-shaped grouping and both providers' Batch
endpoints. The old 12,313-row comparison reduced its conservative plan from
$504.279960 with single-row requests to $109.903535 with groups of 25. The
new planner proves the same packing and pricing mechanics at the larger
candidate volumes.

### 2. Remove the full-campaign paid scorer

The release policy sends every selected candidate to both judges. A scorer
changes order, not coverage or admission. Deterministic ranking by retrieval
family overlap, best BGE rank, lexical/sparse ranks, and candidate identity can
provide a reproducible queue order at zero provider cost.

At K50, removing the scorer reduces the current semantic-candidate base passes
by $5,463.721848, from $13,756.282989 to $8,292.561141. This recommendation
needs a new qualification-policy identifier because the approved plan
currently requires a paid scorer. The new accounting records `scored` as
`notApplicable`; it does not silently drop the field or imply missing work.

### 3. Validate a compact judgment schema

Output allowance dominates the conservative plan. K25 allocates 358,338,000
output tokens to each pass, or 400 per row. Historical OpenAI judge completions
had median 61, 95th percentile 185, and maximum 401 tokens. The pilot should
compare the current free-text reason with a compact reason code plus bounded
evidence fields at 200 and 400 tokens per row. Missing or truncated rows should
fall into exact Batch recovery, never silent rejection.

The campaign may adopt the lower allowance only if the pilot preserves binary
support, compatible relation/direction, parse completeness, and recovery
behavior. Until then, the table above remains the honest ceiling.

### 4. Deduplicate concept facts within each group

Represent each request as a small concept dictionary plus 25 source-target key
pairs. Pack rows to reuse concept facts while keeping row order deterministic
and instructing the model to judge independently. Compare this columnar form
with the current repeated row objects during the pilot. Adopt it only when the
extracted per-row payload digest, blind semantics, and concordance remain
equivalent.

This primarily reduces input tokens. It complements, rather than replaces, the
larger output-token savings above.

### 5. Adjudicate only supported type/direction conflicts

Keep two blind judgments for every selected candidate. Invoke a third model or
named human review only when both first-pass judges support a direct relation
but their types or directions are incompatible. Seal the two blind answers
before the adjudicator receives them. The adjudicator may select one of the two
supported relations or abstain. It may not invent a third relation, reverse a
support/no-support split, or admit a control. A machine adjudicator produces a
new three-machine proof-policy version; a named reviewer produces human-review
evidence. The two evidence classes never share an identifier.

For every supported result, run the governed path check before admission. A
short path is evidence, not an automatic veto on a stronger direct exact,
close, or hierarchical mapping. It blocks a proposed mapping only when the
path already supplies the same useful semantics and the candidate adds no
distinct terminological meaning. For `relatedMatch`, this specifically keeps a
generic association out when the existing graph already supplies the useful
navigation.

### Operational staging

Authorize immutable rank bands separately so a restart or provider incident
cannot spend another band's allocation. A public release still requires every
candidate inside the selected cutoff to reach a final disposition. Staging
controls operational and financial risk; it does not redefine coverage after
results are seen.

## Proposed 25-row acceptance pilot

Before production integration, submit one governed sample that is balanced
across vocabulary pairs, relation kinds, rank bands, sparse/lexical-only rows,
BGE-only rows, overlaps, known positives, generic same-domain pairs, and pairs
already represented by a short graph path. Run the same rows through:

1. the current grouped schema at the current allowance;
2. the compact schema at the proposed allowance; and
3. the deduplicated concept-dictionary payload.

Both provider families remain blind and receive the same semantic facts. The
semantic verdict is recorded before the deterministic path evidence is applied
to an associative admission. The pilot passes when:

- every task identifier returns exactly once or enters explicit recovery;
- within each family, compact and dictionary forms preserve support/no-support
  on at least 24/25 rows and compatible relation/direction on at least 23/25
  rows against the current grouped form;
- all predeclared exact hierarchy controls retain the correct direction;
- every generic-thematic and path-redundant control remains out of the
  assertion set even when a judge calls it broadly `related`;
- the provider-reported token counts support a new exact campaign ceiling;
- raw requests, responses, usage, retries, and extracted answers reopen from
  retained bytes; and
- no result changes the candidate cutoff or sample membership after answers
  are visible.

This is a protocol acceptance check, not a production mapping run. Its spend
authority should be separate, small, and explicit. It begins only after this
proposal is approved.

## Versioned integration boundary after approval

1. Implement `VocabularyAtlasRetrievalSnapshot` as a manifest plus canonical
   JSON Lines rows. Pin `languageScope = en`, exact concept-input and member-set
   digests, ordered arm metadata, pair-set digest, candidate-row digest, local
   neural rank receipt, and content-derived identity.
2. Add a governed descriptor projection: 3,280 preferred ICPSR endpoints plus
   publisher-linked access-term aliases. Fail closed on ambiguous, missing, or
   unsupported access-term relations.
3. Merge arms additively by source-target identity. Preserve all distinct
   signals; reject conflicting signal evidence.
4. Generate six replacement `v1.0.0-rc1` catalogs from the approved snapshot.
   Add
   controls afterward and keep judges blind to all retrieval metadata.
5. Implement a versioned no-scorer judgment policy with deterministic queue
   priority and a strict directness/path-redundancy disposition. Keep the
   current scorer-based policy and broad-related rubric reopenable.
6. Run the 25-row acceptance pilot and recompute the exact campaign plan from
   its selected payload and output policy.
7. Request one new spend authority that pins the six catalogs, models, grouping
   rules, request bytes, job shards, recovery reserve, and non-overlapping run
   caps.
8. Run and collect the six Batch campaigns. Seal every candidate disposition
   before building the successor relation bundles and public Atlas release.

The 12,313-row catalogs and proposed $112 authority remain immutable historical
planning evidence. Record them as superseded before any provider submission;
they do not authorize the replacement catalogs. The public release remains
`v1.0.0-rc1` until its still-pending qualification work completes, so this is a
pre-publication plan amendment rather than a fictional successor release.

Before integration, promote every selected artifact now held under `/tmp` into
durable content-addressed evidence storage: exact benchmark inputs, BGE rank
bytes and manifest, blind samples and fixed decisions, cost receipts, and the
selected frontier result. Reopen and verify every digest after promotion.

No candidate snapshot is a mapping assertion. No accepted mapping mutates a
published predecessor or an earlier proof. The completed release candidate
pins its own evidence and leaves every earlier policy, receipt, bundle, and
planning artifact interpretable.

## Acceptance gates

The proposal is ready for production integration only when all of these are
true:

- **Input integrity:** all six exact release identities, concept counts,
  membership digests, and concept-input digests reopen; ICPSR separately
  reconciles 3,760 release members, 3,280 preferred descriptor endpoints, 478
  unambiguous access-term aliases, and two exceptional nonpreferred records.
- **English scope:** every concept input and policy record declares English;
  translation and transliteration arms are absent.
- **Determinism:** reordered input, independent process, and repeat generation
  reproduce pair counts, pair-set digest, signal rows, rank receipts, and
  snapshot identity.
- **Exact retrieval:** dense ranking uses exact, blockwise similarity. Approximate
  nearest-neighbor indexes cannot define the release floor.
- **Known relation coverage:** all 582 typed Atlas mappings remain present as
  evidence by pair and relation class. Any decision not to carry an old
  `relatedMatch` forward requires a new explicit superseding disposition; no
  historical assertion or proof is deleted.
- **Independent evidence:** Conference, corrected Anatomy, and
  BeyondEquivalence measurements reopen from pinned benchmark inputs; they
  inform coverage without replacing the real Atlas decision.
- **Real-domain audit:** the fixed 120-row review, ranks 26-50 review, and
  outside-K50 sentinel remain sealed. Their broad-rubric counts stay labeled
  historical, while the direct/nonredundant review reproduces 12 direct
  candidates, 52 generic thematic rows, one path-redundant row, and the exact
  pre-projection ranks 1, 1, 1, 1, 1, 1, 2, 3, 5, 6, 8, and 50.
- **Graph minimality:** same-domain thematic and path-redundant controls do not
  become assertions; exact and hierarchy cases are never rejected merely
  because a weaker path exists.
- **Resource bounds:** generation completes within recorded time and memory;
  every local model, tokenizer, ONNX file, runtime, normalization mode, thread
  setting, and retained rank artifact is pinned and available offline.
- **Pilot equivalence:** grouped, compact, and deduplicated requests satisfy the
  predeclared concordance, completeness, direction, and recovery checks.
- **Complete accounting:** generated, judged, controlled, admitted, rejected,
  abstained, and incomplete totals reconcile exactly; no selected candidate
  disappears.
- **Exact authority:** the production plan is recomputed after the pilot and
  adds controls, conditional adjudication, recovery, and reserve to the exact
  two-base-judge amount, then fits a newly approved immutable ceiling. The old
  $112 authority is explicitly superseded and never reused.
- **Release isolation:** old policy IDs and evidence reopen unchanged; the new
  policy and eventual relation bundle receive new content-derived identities.
- **Durable evidence:** every selected artifact now under `/tmp` has moved to
  versioned content-addressed storage and reopens at its recorded digest.

## Complete experiment inventory and disposition

The detailed ledger remains the authority for commands, model revisions,
digests, timing, memory, and per-pair tables. This matrix prevents a useful
negative or limitation from disappearing when the policy is summarized.

| Experiment | What was tried and observed | Lesson and proposal role |
| --- | --- | --- |
| Retired historical pair generator | Six label/control classes; 12,313 rows; all 582 historical assertions; only 196/305 Conference references | Test-only historical evidence and implementation baseline, not a production Atlas input or an independent recall floor |
| Fielded deterministic retrieval | Preferred/alternate labels, identifiers, definitions, scope notes, parents, children; word and character sparse views; anchor-gated graph expansion | Keep the fielded sparse and gated graph families; permissive graph expansion creates millions of noisy rows |
| Lexical controls | Levenshtein, normalized Levenshtein, RapidFuzz ratio/partial/token-sort/token-set/WRatio/QRatio, Jaro, Jaro-Winkler, compact strings, alias bags, identifiers, acronym keys, and character trigrams | Keep the seven-arm practical profile; remove duplicate/weak controls; add individual-label alias handling because one concatenated alias bag dilutes evidence |
| Exact real-Atlas deterministic frontier | Lexical K3 plus sparse/mutual-graph K1: 210,197 rows before ICPSR access-term projection and 214,271 after it; both recover 582/582 historical assertions | The corrected 214,271-row floor is selected; historical coverage is a regression check, not proof of new-relation recall |
| ICPSR preferred-endpoint projection | 3,760 release members split into 3,280 preferred descriptors and 480 access terms; 478 terms reach 387 preferred endpoints through verified `use` paths and two fail closed | Keep only preferred descriptors as mapping endpoints; inject verified access labels as retrieval evidence and preserve exceptions explicitly |
| Five-view BGE | Label, structured, natural, definition-first, and hierarchy views; plain symmetric, query-prefix, and relation-prompt variants; pre-projection real Atlas run through K50 | Plain symmetric five-view BGE is the proposed add-only configuration; regenerate its vectors, ranks, pair set, and cost on the corrected corpus before integration |
| Alternative local embeddings | MiniLM, Arctic, Jina, and Nomic on Conference; all reached the small benchmark at wide depth | Useful model-family comparison; no unique six-Atlas evidence, so none enters the v1 floor |
| Google and OpenAI embeddings | Google `gemini-embedding-001` similarity/retrieval, `gemini-embedding-2` instructed retrieval, OpenAI `text-embedding-3-small` and `-large`; five-arm Conference union 305/305 at K20; $0.046897820 including Batch smoke | Provider embeddings are proven comparative arms and Batch mechanics are verified; they lack unique real-Atlas transfer evidence and remain diagnostics for this release |
| Reranking | MiniLM cross-encoder and ColBERT over a near-Cartesian Conference reservoir; MiniLM rescued all six misses at K25, ColBERT at K50 | Rerankers may order or add rows from a wide reservoir; they can never delete another arm or find a pair absent from the reservoir |
| Learned sparse | MiniCOIL, OpenSearch sparse encoder, and SPLADE on Conference and the earlier Anatomy text | Complementary on Conference but expensive, memory-heavy, and not uniquely useful on Anatomy; SPLADE lineage needs license review; not selected |
| OAEI Conference | Multiple heterogeneous arms reached 305/305; exact no-provider minimum was Nomic K10 plus MiniCOIL K20 with 116,909 rows | Independent lexical/semantic stress test; small equality-heavy ontologies do not set the policy-domain cutoff |
| Corrected OAEI Anatomy | Resolved OBO synonym/definition nodes; sparse plus BGE reached 1,516/1,516 at K50 | Confirms text resolution and heterogeneous recall; biomedical specialization does not define the policy-domain floor |
| BeyondEquivalence and Open English WordNet | 1,292/1,292 typed benchmark rows at depth 6; WordNet depth 4 added 3,208,046 real-Atlas rows and no unique historical assertion | Keep as typed diagnostic/targeted rescue, not a default Atlas arm |
| Cross-arm Pareto search | Exact bitset search across 26 arms and 192 depths; provider and no-provider complete fronts | Useful comparative optimization; Conference optimum does not override real-Atlas evidence |
| Real-label 120-row audit | 53/120 broad-rubric possibilities; BGE-only and three-family overlap each 47.22% in balanced strata | Proves BGE adds meaningful semantic rows; broad associative counts are not direct-edge precision |
| Ranks 26-50 audit | 12/60 broad-rubric possibilities, including one directional row at exact rank 50 | K25 and K40 are unsupported as safe bounded cutoffs; directness re-review governs graph admission |
| Direct/nonredundant re-review | Of 65 earlier broad positives, 12 remain direct candidates, 52 are generic thematic, and one is redundant through a short typed path; direct ranks are 1, 1, 1, 1, 1, 1, 2, 3, 5, 6, 8, and 50 | This is the governing graph-minimality evidence; K50 remains the proposed measured boundary pending corrected-corpus BGE reproduction |
| Typed path audit | Reopened 9,010 concepts, 32,684 native relations, and 582 mappings; one of 65 earlier positives has a qualifying path of at most four edges | Apply path evidence after blind semantic judgment; no path does not prove directness, and a weak path does not erase a stronger exact or hierarchy mapping |
| Outside-K50 sentinel | 60 deterministic rows from four nonempty residual populations; its one tentative association depends on an intermediate concept and the final proposal treats it as a borderline thematic control | Tests the directness boundary without creating a cutoff miss; it cannot estimate population recall or choose K60/K100 |
| Historical judge audit | 108 fixed rows; provider support agreement 102/108, exact relation agreement 74/108; type/direction conflict dominated disputed supported rows | Retain two blind semantic judges; adjudicate only supported type/direction conflicts; revise the broad-related rubric before production |
| Exact Batch cost planner | Full hierarchy payloads, groups of 25, current models/prices, K0-K50; reproducible request and cost receipts | Batch grouping is mandatory; remove the paid scorer; recompute a complete authority only after final schema, controls, adjudication, and reserve |
| Exact-memory and reproducibility checks | Blockwise exact dense search and compact rank matrices; approximate USearch lost material top-12 recall; BGE vectors varied until runtime and ONNX pins were complete | Exact blockwise ranking and full runtime/artifact pins are release gates; model name alone is inadequate |

Research also covered BGE-M3, SapBERT, BioSyn, LogMap, AgreementMakerLight,
MELT, Similarity Flooding, fastText, ConceptNet, and other candidate systems.
They were not executed in this experiment and are not presented as measured
evidence.

## Reconciliation with the approved release plan

Unless this section says otherwise, the 2026-08-04 plan remains in force:
content-addressed release lineage, the closed Atlas 2.0 three-file
distribution, all 87 planning-row dispositions, exact six-release scope,
ring-specific predicates, cross-ring safeguards, complete evidence and
candidate accounting, immutable predecessors, explorer and public-package
acceptance, and separation of Atlas publication from product search policy.

This proposal amends four points before the first provider call:

| Approved-plan point | Disposition | Replacement |
| --- | --- | --- |
| 12,313-row production catalogs | Superseded as unexecuted planning evidence | Six catalogs derived from the approved K50 retrieval snapshot and governed descriptor projection |
| $112 spend authority | Superseded before use | New authority after pilot, including controls, adjudication, recovery, and reserve |
| Paid LLM scorer for every row | Superseded | Deterministic priority from retained retrieval signals; accounting records scoring as not applicable |
| Broad `related` judgment | Superseded for new admissions | Direct, useful, nonredundant association plus explicit path disposition |

The 582 historical assertions and 69 controls remain immutable evidence. The
new policy does not delete them. Before public release, the 35 historical
`relatedMatch` assertions receive the strict directness review. A row that does
not carry forward receives a new superseding disposition while the old
assertion, proof, and policy remain resolvable.

Deferred work stays deferred: the CFR bridge, federal-source normalization,
specialist spokes, publisher crosswalk ingestion, optional LCSH hub, entity
identity, value crosswalks, and legal-identity relations. English-only
candidate generation for these six subject pairs does not narrow the global
Atlas schema or remove language metadata.

## Research basis

The proposal follows the distinction in the
[W3C SKOS reference](https://www.w3.org/TR/skos-reference/) between exact,
close, hierarchical, and associative mapping relations. It uses the
[OAEI Conference](https://oaei.ontologymatching.org/2024/conference/index.html),
[OAEI Anatomy](https://oaei.ontologymatching.org/2024/results/anatomy/index.html),
and
[OAEI BeyondEquivalence](https://oaei.ontologymatching.org/2025/beyondequivalence/index.html)
tracks as independent stress tests. The multi-view dense arm follows the
[BGE model and instruction evidence](https://aclanthology.org/2024.findings-acl.137/),
while the add-only reranking boundary matches the
[Sentence Transformers retrieve-and-rerank pattern](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html).

The lexical-resource experiment uses
[Open English WordNet](https://github.com/globalwordnet/english-wordnet).
Provider experiments follow the official
[Google embeddings guide](https://ai.google.dev/gemini-api/docs/embeddings)
and
[OpenAI Batch API reference](https://platform.openai.com/docs/api-reference/batch/object?api-mode=responses).
The heterogeneous design is also consistent with established ontology-matching
systems and techniques such as
[LogMap](https://www.cs.ox.ac.uk/files/4540/paper.pdf),
[AgreementMakerLight](https://journals.sagepub.com/doi/pdf/10.3233/SW-233304),
and
[Similarity Flooding](https://dbs.uni-leipzig.de/files/research/publications/2002-1/pdf/icde2002-sf.pdf):
combine lexical, structural, and semantic evidence, then preserve explicit
evidence and validation boundaries.

## Decision requested

Approve the proposed architecture and K50 configuration for implementation,
subject to corrected-corpus BGE reproduction, plus one
separately governed 25-row protocol acceptance pilot. Approval should not yet
authorize the full provider campaign. After implementing the descriptor
projection, regenerating corrected-corpus BGE evidence, promoting durable
evidence, and passing the snapshot and pilot gates, RefSpec will present the
final exact six catalogs, two-pass request and shard counts, control and
adjudication caps, recovery reserve, and all-in spend ceiling for a separate
production decision.
