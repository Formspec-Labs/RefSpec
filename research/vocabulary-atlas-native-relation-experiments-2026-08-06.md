# Vocabulary Atlas native-relation test sets and E3 retrieval experiments

**Date:** 2026-08-06
**Status:** Test sets built and reproducible. E3 retrieval measured across six arm
families. Wave 1 structural experiments executed. Cross-vocabulary crosswalk
archive recovered and independently blind-reviewed. The five free replay
experiments (E-V1, E-V2, E-V4, E-V5, E-V7) executed — the recoverable-mapping
figure is corrected from 85 to 39, the reviewer calibration finding is reversed,
and the edit-distance arm splits into a working tenth and a `relatedMatch` sink.
Google hosted arms unresolved. No mapping asserted, no release artifact changed,
no qualification policy touched.
**Dataset:** `research/evidence/atlas-v3-native-relation-testsets-2026-08-06/`
**Designs:** `vocabulary-atlas-native-relation-experiment-designs-2026-08-06.md`

## Handoff — read this first

### What is durable and what is not

**Durable, committed under `research/evidence/`:**

| Directory | Contents |
| --- | --- |
| `atlas-v3-native-relation-testsets-2026-08-06/` | 3 test sets, manifest, README, E3 result, wave-1 evidence, graph report, Pareto results |
| `atlas-crosswalk-blind-review-2026-08-06/` | blind samples, sealed key, 3 independent verdict files, comparison |
| `atlas-crosswalk-benchmarks-2026-08-06/` | 5 scoped benchmark sets, manifest, README |
| `atlas-candidate-benchmark-sealed-2026-08-05/` | 34 sealed artifacts promoted off `/tmp` — blind samples, fixed decisions, audits, cost and frontier receipts |
| `atlas-variant-classifier-audit-2026-08-06/` | 165-pair sealed audit of the variant classifier, blind linguistic pass, comparison |
| `atlas-relatedmatch-blind-review-2026-08-06/` | 95-row sealed sample, two independent blind passes, comparison |
| `atlas-crosswalk-admission-replay-2026-08-06.json` | E-V1/E-V2/E-V4/E-V5/E-V7 results — five lattice variants, control calibration, relation share, variant hygiene, order independence |
| `atlas-tmp-evidence-promotion-2026-08-06.json` | Digests for **all 554** promoted files across every tier, including the ones the repo does not carry |

**Durable but git-ignored, under `output/`:**

| Directory | Contents | Size |
| --- | --- | ---: |
| `atlas-candidate-benchmark-archive-2026-08-05/` | BGE rank bytes, lean pair codes, 448 provider request/response receipts | 132 MB |
| `atlas-e3-rank-artifacts-2026-08-06/` | The 54 E3 rank artifacts (`valid/*.npz`) and the ablated corpus export | 100 MB |

The rank artifacts that back the Pareto fronts, closure-scored recall, class mix,
unmatched triage and view ablation now live at
`output/atlas-e3-rank-artifacts-2026-08-06/valid/`. Point `$R` at that directory
and the analysis steps run immediately — the ~1 hour arm sweep is only needed if
you change an arm or a corpus.

**Two caveats a 2026-08-06 peer review found, and both are real.**

*"Committed" above means "written to `research/evidence/`", not "in git."*
`git ls-files research/` returns 140 files and **none of them is from this
programme** — every artifact this document cites is untracked in the working
tree. It survives a `/tmp` sweep; it does not survive a clean checkout. Run
`git add research/evidence/` before relying on the word durable.

*Two wave-1 artifacts were cited but never written — now regenerated, and E-S5
survives intact.* `pareto-closure.json` did not exist, and `wave1-evidence.json`
contained **no ELSST block at all**: it was a stale two-source file, written
before the ELSST rank artifacts landed. The tool was never at fault — a fresh run
emits all three sources. Both artifacts have been regenerated into
`research/evidence/atlas-v3-native-relation-testsets-2026-08-06/`, and every
ELSST figure this document cites reproduces to the decimal:

| Figure | Document | Regenerated |
| --- | ---: | ---: |
| ELSST asserted / closure edges | 3,393 / 7,608 | **3,393 / 7,608** |
| `gemini-001-sim.label` closure recall | 86.4% | **86.4%** |
| `openai-3-large.label` closure recall | 78.0% | **78.0%** |
| `bge-small.label` closure recall | 76.1% | **76.1%** |
| `view-bge-small.maxOverLabels` closure recall | 76.9% | **76.9%** |
| Top-10 arm ordering preserved under closure | no | **no** |
| ELSST unmatched "neither" at K100 | 92.8% | **92.8%** (212,895 / 229,442) |

The provenance worry attached to E-S5's top row is also cleared: `valid/` holds
`gemini-001-sim` for all three sources and `gemini-001-ret` for FR, and **no
`gemini-2` batch arm at all**, so no withdrawn result leaks into the table. The
gold test sets were untouched by the regeneration — all three digests still match
the manifest.

E-S5 was right; only its evidence file was stale.

Regeneration timings, if you do need them: deterministic arms 29 s, 17 lexical
arms 47 s, five dense families ~10 min, three learned-sparse ~15 min, view
ablation ~2 min, rerankers ~13 min, frontier 30 s, analyzers seconds.

### Environment matrix

Tools run in three different environments. Getting this wrong is the first thing
that will waste your time.

| Environment | Tools |
| --- | --- |
| Project env — `uv run python` | test-set builder, relation recovery, frontier, all three analyzers, blind-review builder and comparer, benchmark builder and verifier |
| `uv run --with rapidfuzz python` | lexical recovery (17 RapidFuzz arms) |
| `uv run --no-project --with fastembed --with numpy` | dense recovery, view ablation |
| `uv run --no-project --with fastembed --with scipy --with numpy` | learned sparse (SPLADE++, MiniCOIL) |
| add `--with "sentence-transformers>=5"` | learned sparse (OpenSearch v2-distill), rerankers |
| `uv run --no-project --with google-genai --with openai --with numpy` | hosted provider arms |

`refspec` is not importable from the `--no-project` environments by design; the
corpus export exists so those tools need no `refspec` import.

### Gotchas that already cost time

- **`uv run pytest` was broken on main.** Seven test files failed collection on
  `No module named 'tools'`, five of them tracked. Fixed by adding a root
  `conftest.py` that puts the repo root on `sys.path`. Verified neutral.
- **Repo test baseline is not green.** `uv run pytest -q` reports **61 failed,
  2,513 passed, 43 skipped, 4 errors** from in-progress v3 explorer, generator,
  and bindings work unrelated to anything here. Confirmed pre-existing by
  running with and without `conftest.py`. Do not assume you broke it.
- **Google batch responses are not request-ordered.** `inlined_embed_content_responses`
  returned vectors that did not correspond to their inputs. OpenAI is safe because
  `custom_id` forces explicit keying. Use file-based batch with per-line keys.
- **Google meters `embed_content` per *text*, not per call** — 5,000/minute/model.
  Packing 100 texts into one call spends 100 units. Pace, do not just retry.
- **Google's synchronous endpoint caps at 100 inputs per call.**
- **`gemini-embedding-001` needs manual L2 normalisation** at any width below
  3072. At 768 this silently corrupts cosine ranking if skipped.
- **Crosswalk archive joins:** `inputContext` joins to a candidate on the
  `(source.member, target.member)` pair — the context digest does *not* match
  `candidate.inputContextDigest`. And `mappingAssertions` names endpoints
  `sourceConcept`/`targetConcept`, not `sourceMember`/`targetMember`. Both cost a
  silent zero-row result before being found.
- **`rerankers` is incompatible with current `transformers`** (`all_tied_weights_keys`).
- **`build_atlas_crosswalk_blind_review.py --key-only`** exists so the sealed key
  can be regenerated without touching blind samples a reviewer is mid-read on.

### Test suites added here

`test_build_atlas_native_relation_testsets.py`,
`test_benchmark_atlas_native_relation_recovery.py`,
`test_atlas_dense_relation_frontier.py`,
`test_atlas_frontier_embedding_recovery.py`,
`test_atlas_native_structure_and_sparse.py`,
`test_build_atlas_crosswalk_benchmarks.py`,
`test_verify_atlas_crosswalk_benchmarks.py` — **126 tests, all passing.** The
learned-sparse checks skip without SciPy.

### Provider spend

Roughly **$0.19** total, all embeddings. No LLM judge or scorer call was made in
this session; every judgment analysed here was either sealed in the 2026-08-05
archive or produced by local subagent review at no provider cost.

### Start-here check

```sh
uv run python tools/verify_atlas_crosswalk_benchmarks.py   # expect 10/10 pass
uv run pytest -q tests/test_build_atlas_native_relation_testsets.py   tests/test_verify_atlas_crosswalk_benchmarks.py          # expect all pass
```

## What this programme is for

**RefSpec is the core vocabulary/entity/subject/concept knowledge graph that
powers everything else.** It is one component of five:

| Component | Role | What it needs from RefSpec |
| --- | --- | --- |
| **SpicyRegs** | metadata source | stable concept and entity identifiers to attach metadata to |
| **DocSpec** | document management, segmentation, tagging | a taggable concept set with reliable identity |
| **SpicySearch** | indexing and querying | traversable relations with a *known* precision at depth |
| **RuleSpec** | structured rule extraction, core ontology | entities and legal identifiers to hang extracted rules on |
| **RefSpec** | the knowledge graph itself | — |

The core need, in the product owner's words: traverse almost any government
document to find related content, using traditional search *and* tagging over a
property graph layered on a knowledge graph — which requires **fusing terms from
many thesauri across many document types into comprehensive coverage**, and
**tracing back to identifiers, entities and other objects**.

### That requirement already has an architecture, and it is four rings

On 2026-08-04 the Atlas adopted four semantic rings, and they are implemented
consistently across `atlas_index`, `publication_decision`, `v1_release`,
`release_acceptance`, `explorer_acceptance`, `projection` and `v3_source_data`:

| Ring | What it holds | The product requirement it serves |
| --- | --- | --- |
| `subject` | what a document is *about* | fuse thesaurus terms; topical traversal |
| `entity` | agencies, bodies, organisations | "trace back to … entities" |
| `value` | controlled values — document type, status | facet filtering |
| `legalIdentity` | statutory and legal identifiers | "trace back to identifiers … and other objects" |

### Where the data actually is

| Ring | Concepts in committed evidence | **Relation assertions** | SSSOM export |
| --- | ---: | ---: | :---: |
| `subject` | 597 + 565 + 32 across releases, plus 7,985 in the E3 corpus | **582** | supported |
| `entity` | 478 (legislative entities) | **0** | **not supported** |
| `value` | — | **0** | supported |
| `legalIdentity` | — | **0** | **not supported** |

**Every relation this programme has ever measured, admitted or audited is in the
`subject` ring.** The entity ring has concepts and no edges. The legalIdentity
ring — the one that most directly answers "trace back to identifiers" — has
neither, and `relation_sssom.py` restricts distribution to `{subject, value}`, so
entity and legalIdentity relations could not be exported today even if they
existed.

That is the honest scope statement for this document: **excellent work on ring 1
of 4, and the ring that carries the stated traceability requirement is empty.**

### What this work has bought, concretely

| | Before | After |
| --- | --- | --- |
| Cross-vocabulary subject mappings | 582 admitted | 582 + **39 recoverable free** (R4) |
| Confidence in those mappings | two machine judges, unaudited | **36/36 non-`relatedMatch` admissions survive independent blind review**, under two framings |
| `relatedMatch` edges | 35, quality unknown | **25–30 of 35 survive**; failures are 8/10 unprincipled edit distance |
| Edit-distance candidate arm | 165 candidates, 18.2% admit | restrict to orthographic variants: **16 candidates, 81% admit**; blind linguistic audit confirms **0 false promotions in 16** |
| Known admission rule | undocumented | reconstructed exactly (582/582), **order-independent**, replayable against any proposed change |

In one sentence: **the subject mappings we have are good, ~6.7% more are
available for nothing, and the largest single source of bad edges is one
generator arm that can be switched off.**

### The tension nobody should paper over

The core need says **comprehensive coverage**. The one thing this archive
provably cannot measure is coverage: every candidate came from a string matcher,
so no semantically-related pair with dissimilar labels could ever enter the
population. The benchmark README says so in its own words and refuses to emit a
recall number.

So the programme is strongest exactly where the product cares least right now
(precision of what we already propose) and silent where it cares most (how much
we are missing, and everything outside the subject ring).

### What it has not touched, and why that matters more than it looks

**The rings that carry traceability hold no relations.** 478 entity concepts with
zero edges; no legalIdentity concepts at all. RuleSpec needs entities and legal
identifiers to hang extracted rules on; SpicyRegs needs stable identifiers to
attach metadata to. Neither is served by a subject graph, however good it gets.
`V-2` (citation and cross-reference extraction), `V-7` (anchoring onto
CFR/USC/NAICS/budget-function spines) and `V-9` (docket and legislative lineage)
are the designs that populate those rings — and against a requirement that says
*trace back to identifiers*, they are not "vertical approaches" filed at the back
of a catalogue. They are the requirement.

Two of the three read document text, so they belong to the document phase.
**`V-7` does not** — CFR, USC, NAICS and budget-function codes are published
vocabulary-side hierarchies. In the current phase it is the only route into
`legalIdentity`, which is why it is ranked where it is below.

**DocSpec has no gold to tag against** — deliberately out of scope for now, since
the current phase is knowledge-graph relations and documents follow. Worth
recording anyway because it bounds what the graph work can claim: every number
here is *concept-to-concept*, mostly *within* one vocabulary, and no tagging or
search figure can exist until `E-S11` runs in the document phase.

**Subject tags alone answer a minority of real queries.** `E-S20` makes it
concrete: `"EPA rules on PFAS since 2024"` is entity (EPA) + subject (PFAS) +
value (rule) + date, and only one of those four rings carries a single relation
today. Nothing measured in this document would make that query work — and it is
the canonical query for this product. The graph phase is where the entity and
legalIdentity rings have to get their edges; deferring documents does not defer
that.

And the number that should worry a product owner is not a coverage number, it is
**precision under traversal**: at rank 100, 92.8% of retrieved ELSST pairs are
explained by neither gold nor entailment nor a shared parent, and error compounds
at every hop. SpicySearch expanding a query two hops through this graph inherits
that compounded error directly. A denser graph is an asset only if its edges are
ones a user would want to follow, and that has never been measured on the
candidates a *semantic* arm proposes — only on candidates a string matcher did.
`E-S1b`/`E-V6` is the missing number and it sets the traversal budget.

## Why these test sets exist

Every typed-relation recall number in
`vocabulary-atlas-relation-candidate-matching-context-2026-08-05.md` came from
OAEI Conference or OAEI Anatomy. Conference asserts equivalence only; Anatomy is
biomedical. Neither measures typed directional relations in the policy and
social-science language the Atlas serves.

The 582 historical Atlas mappings cannot fill that gap because the retired
label-oriented generator produced them, so scoring a new finder against them is
circular.

The Atlas 3 source-native import carries **32,694 publisher-asserted
intra-vocabulary relations** against 0 mapping assertions. Those are expert
editorial decisions no RefSpec retrieval arm produced. They are the only large,
independent, typed reference material currently available.

## What was built

### Test sets

| File | Rows | Hierarchy | Associative | Equivalence |
| --- | ---: | ---: | ---: | ---: |
| `federal-register-thesaurus-2025.jsonl` | 780 | 0 | 780 | 0 |
| `elsst-r6.jsonl` | 6,241 | 3,393 | 2,848 | 0 |
| `icpsr-subject-thesaurus.jsonl` | 9,428 | 1,763 | 7,180 | 485 |

16,449 canonical rows from all 32,694 native relations in the build. The three
CRS releases contribute none.

Three properties of the source data drive the row shape:

- **ELSST and ICPSR materialise every symmetric and inverse edge in both
  directions.** Scoring against the raw relation list would double every
  hierarchy and associative edge and inflate any recall denominator. Rows
  deduplicate to one canonical edge and retain both source payloads.
- **Federal Register asserts `skos:related` one-way for part of its graph** —
  109 of 780 edges, and 95 of ICPSR's. Preserved as `oneWayInSource`, not
  repaired.
- **Hierarchy normalises to SKOS `broader` orientation**, so `subject` is always
  the narrower concept.

ICPSR publishes access terms as members whose only label carries the `alternate`
role, so endpoints expose `label` + `labelRole` rather than assuming a preferred
label. The 485 equivalence rows include acronym expansion (`ACA` → `Affordable
Care Act`) and non-lexical synonymy (`abduction` → `kidnapping`).

### Tools

| Tool | Role |
| --- | --- |
| `build_atlas_native_relation_testsets.py` | Emits the three test sets plus manifest |
| `benchmark_atlas_native_relation_recovery.py` | Sparse views, exact anchors, corpus and rank export |
| `benchmark_atlas_native_lexical_recovery.py` | The 17 sealed RapidFuzz control arms |
| `benchmark_atlas_native_learned_sparse_recovery.py` | SPLADE++, MiniCOIL, OpenSearch v2-distill |
| `benchmark_atlas_dense_relation_recovery.py` | Five local dense families, sequential |
| `benchmark_atlas_frontier_embedding_recovery.py` | Hosted OpenAI and Google arms |
| `benchmark_atlas_native_reranker_recovery.py` | Cross-encoder and late-interaction rescue |
| `benchmark_atlas_native_view_ablation.py` | Text/prompt variants incl. max-over-labels |
| `optimize_atlas_native_relation_frontier.py` | Cost-recall Pareto over all arms |
| `analyze_atlas_native_relation_structure.py` | Closure, cycles, degree concentration |
| `analyze_atlas_native_relation_evidence.py` | Closure-scored recall, class mix, unmatched triage |
| `analyze_atlas_native_relation_graph.py` | Reachability, components, cross-predicate transfer |
| `build_atlas_crosswalk_blind_review.py` | Cross-vocabulary gold + sealed blind samples |
| `compare_atlas_crosswalk_blind_review.py` | Three-way agreement, controls, recoverable rejections |
| `build_atlas_variant_classifier_audit.py` | Seals the 165-pair blind audit of the orthographic classifier |
| `compare_atlas_variant_classifier_audit.py` | Joins it; separates false-principled from false-unprincipled |
| `build_atlas_relatedmatch_blind_review.py` | Seals the 95-row `relatedMatch` sample; withholds relation, class and status |
| `compare_atlas_relatedmatch_blind_review.py` | Joins blind verdicts to the key; framing sensitivity and control calibration |
| `replay_atlas_crosswalk_admission.py` | E-V1 lattice replay, E-V2 calibration, E-V4 relation share, E-V5 variant hygiene, E-V7 order independence |
| `build_atlas_crosswalk_benchmarks.py` | Splits the archive into five scoped evaluation sets |
| `verify_atlas_crosswalk_benchmarks.py` | Independent re-derivation of every benchmark claim |
| `promote_atlas_tmp_evidence.py` | Tiered promotion of `/tmp` experiment evidence, digest-verified |

Every arm emits the same compact artifact: `uint32` pair code plus `uint8` rank
over a member-IRI-ordered index. That shared format is the integration seam —
it is a working version of the `VocabularyAtlasRetrievalSnapshot` the 2026-08-05
proposal specified but never built, and it is why adding RapidFuzz, learned
sparse, and the view variants late cost one tool each and zero rework. Any future
signal — co-assignment, citation, generation — that emits the same artifact drops
in with no integration work.

126 focused tests across seven suites. Ruff clean.

## The experimental design

Intra-vocabulary retrieval over an **ablated** corpus: for each concept, rank
every other concept in the same release and ask whether the publisher's own
partners come back. Concept text is label, alternate labels, definition, and
notes only. Hierarchy fields are empty, so the sparse context view cannot read
the parent and child labels that would otherwise hand it the answer.

Scoring is exact — full pairwise, blockwise, no approximate index. Self-pairs
excluded. A pair's rank is the better of its two directions. Pairs reaching rank
≤ 100 are retained.

## Results

### Best single arm at K100, by family

| Source / class | Lexical | Sparse | Learned sparse | Local dense | OpenAI |
| --- | ---: | ---: | ---: | ---: | ---: |
| FR associative | 52.4% | 56.3% | 89.7% | 94.1% | **96.3%** |
| ELSST hierarchy | 58.3% | 61.3% | 88.4% | 92.1% | **93.1%** |
| ELSST associative | 50.2% | 56.5% | 82.9% | 86.0% | **89.0%** |
| ICPSR hierarchy | 63.1% | 63.9% | 91.2% | 94.5% | **95.6%** |
| ICPSR equivalence | 69.3% | 70.1% | 92.6% | 95.1% | **100.0%** |
| ICPSR associative | 39.7% | 42.1% | 76.9% | 85.3% | **90.1%** |

Dense unions reach 98.3–100% on every class.

### Family findings

**`openai-3-large` recovers 485/485 ICPSR equivalence pairs.** Every publisher
`use` edge, including acronym expansions and non-lexical synonymy the
deterministic arms miss entirely.

**OpenSearch v2-distill wins every learned-sparse slot**, closing to within 3–4
points of dense on hierarchy and equivalence with no provider, no quota, and no
model-alias pinning problem. This reproduces the ledger's Anatomy result and
contradicts its Conference result, where MiniCOIL sat on both Pareto minimums.
**MiniCOIL loses every slot here, by 15–25 points.**

**BGE survives as the local dense choice** — it leads 4 of 6 classes among local
families. Nomic, which beat BGE on Conference, wins none. The Conference-based
model comparison would have selected wrongly.

**The `label` view wins nearly everywhere**, despite `structured` and `natural`
carrying definitions and notes. `contextSparseV1` returned results byte-identical
to `labelSparseV1` on Federal Register — same 59,937 pairs, same recall at every
depth — because FR carries zero definitions and zero notes. Multi-view is an
ELSST/ICPSR intervention, not a global one.

**Alias WRatio, the sealed Atlas champion, never wins here.**
`alias-token-set-ratio` and `rapidfuzz-partial-ratio` take every class. Different
task: intra-vocabulary retrieval over uniform-register labels versus
cross-vocabulary matching across institutional registers.

### Pareto — one candidate set, all classes

Cost basis: two blind judges at `$8,292.561141 / 1,578,319` candidates.

| Source | Pairs | 2-judge $ | Recall | Arms |
| --- | ---: | ---: | --- | --- |
| ICPSR | 2,242 | $12 | equiv 20.8% / hier 24.2% / assoc 4.8% | `labelSparseV1@1` |
| ICPSR | 26,002 | $137 | **equiv 95.3%** / hier 61.7% / assoc 44.1% | `openai-3-small.label@10` |
| ELSST | 3,884 | $20 | hier 26.1% / assoc 19.9% | `openai-3-large.label@1 + .natural@1` |
| ELSST | 23,946 | $126 | hier 66.0% / assoc 54.3% | `openai-3-large.label@10` |
| ELSST | 147,118 | $773 | hier 77.3% / assoc 67.6% | `contextSparseV1@100 + openai-3-large.label@10` |
| FR | 6,474 | $34 | assoc 76.8% | `jina.definitionFirst@10 + .label@10` |

No deterministic-only point survives above ~40% recall on any class. At equal
cost dense is roughly 3x more efficient. The tail is steep: ELSST goes 23,946 →
147,118 pairs, 6x the candidates, for +11.3 hierarchy points.

Local models hold the cheap end; providers own the middle.

## Structural findings

| | ELSST | ICPSR |
| --- | ---: | ---: |
| Asserted hierarchy edges | 3,393 | 1,763 |
| Entailed within 6 hops | 7,608 | 2,539 |
| **Entailed but not asserted** | **4,215** | **776** |
| Closure inflation | **2.24x** | 1.44x |
| Cycles | none (DAG) | none (DAG) |

**The hierarchy gold is not transitively closed.** New pairs appear at hop 2
(2,438 for ELSST), 3 (1,216), out to hop 6. Examples: `LOANS`→`FINANCE`,
`TRUCKS`→`MOTOR VEHICLES`, `adoption leave`→`employee benefits`. All true, none
asserted.

Consequence — **corrected by E-S5 below.** The original reading here was that
recall figures are lower bounds. That is backwards: closure ⊇ asserted, and arms
recover direct edges much better than distant ancestors, so scoring against the
asserted subset **over-states** true hierarchy recall by 10–15 points. What is
under-stated is precision, because some pairs counted as noise are entailed. The
effect is not arm-neutral, and E-S5 confirms it changes arm ordering rather than
shifting every arm equally.

Degree is concentrated: median 1, max 39 in ELSST and 30 in ICPSR, top decile
carries 38–40% of edges.
**ICPSR hierarchy touches only 1,984 of 3,810 concepts** — 48% of the vocabulary
has no hierarchy at all and is unreachable by hierarchy traversal.

### Incidental data-quality findings

The exact shared-alias anchor surfaced two **duplicate ICPSR concepts** differing
only by whitespace: `'Obama Administration (2009- )'` vs `'(2009-  )'`, and
`'special elections'` vs `'special  elections'`. Independently corroborated by
`normalized-label` yielding 3,808 distinct texts across 3,810 concepts.

It also surfaced genuine ELSST near-synonymy the publisher kept separate:
`GRIEF`≡`BEREAVEMENT`, `ILL HEALTH`≡`MORBIDITY`, `OUTWORKERS`≡`HOME-BASED
WORKERS`. Caution for cross-vocabulary use: *shares an alias* ≠ *same concept*.

## Corrections and invalidated results

**Google batch arms are invalid.** `inlined_embed_content_responses` did not
return in request order. ELSST rank-1 neighbours came back as
`TRUCKS`/`NEWS ITEMS` where a synchronous call on identical text gives
`TRUCKS`/`COMPANY CARS`. All `gemini-*` batch numbers are withdrawn, including a
reported `gemini-2` 100% on equivalence. OpenAI is unaffected — it keys every
chunk by `custom_id` and sorts by explicit index, and its neighbours are coherent.

**The deterministic ceiling was initially understated.** The first pass measured
only sparse views plus anchors and reported ~69% as the dependency-free ceiling.
Adding the 17 RapidFuzz arms raises it to 59.2–92.1%. The full lexical union
costs 4.4x the candidates of sparse alone for +7 points.

**The MiniLM cross-encoder result is confounded and withdrawn.** The reservoir
cap kept `sorted(partners)[:300]` — alphabetical by IRI, not by rank quality —
dropping 3.8M of 4.8M slots at random. The 27–33% figure is not a model result.
Cap by best cross-arm rank before rerunning.

**ColBERT did not run.** `rerankers` is incompatible with current `transformers`
(`all_tied_weights_keys`).

**The embedding comparison is not dimensionality-controlled.** Models ran at 384
(BGE, MiniLM, Arctic), 512 (Jina), 768 (Nomic, OpenAI forced, Google forced), and
1536 (ada-002 fixed). Large gaps survive this; fine-grained rankings among dense
models do not.

**"85 recoverable mappings, +14.6%" was a category error.** 85 is the count of
disputed rows an independent reviewer would keep. The count an admission rule
recovers is **37 (+6.4%)** as designed, **39 (+6.7%)** under R4 — E-V1. Reaching
85 needs a rule that also admits four sibling distractors, which the design named
as disqualifying.

**"The reviewer flunked its control calibration" is withdrawn.** The 100%
sealed-judge baseline it was measured against was never measured; it was a
control-class exclusion applied ahead of the lattice. The judges name a relation
on 55.6%/57.0% of sibling distractors against the reviewer's 48.1% — E-V2. The
withdrawal stands on that mechanism; the residual gap is **not** significant
(Fisher p = 0.77 and 0.18–0.27), so "no worse" is the claim, not "better".

**"R2 admits a substring row and two coincidences" is withdrawn.** R4 ⊂ R2 by
construction and they differ by one row. The two edit-distance rows R2 adds
beyond R1 are the same principled variants R4 admits.

**"589 ICPSR concepts with no edge of any kind" is withdrawn.** That is the count
outside hierarchy ∪ associative; 510 of them carry an equivalence edge. The
edgeless count is **79 (2.1%)**. The derived "15–48% of concepts carry no edge at
all" was per-predicate orphan rates read as coverage.

**"Roughly 234 real hard negatives" is superseded** by the partition: 157 hard
negatives and 86 disputed.

**`Statistics`/`STATISTICS` was never a recoverable mapping.** One judge returned
`insufficient_evidence`, making it a genuine hard negative. It was cited as a
lost mapping in several drafts.

All six were found by an adversarial peer review on 2026-08-06 and verified
against the data before being applied here.

**E-S5 is *not* in that list.** The same review flagged its ELSST figures as
unverifiable because `wave1-evidence.json` carried no ELSST block. That was true
and the artifact has been regenerated; every cited figure reproduces exactly. A
stale evidence file, not a wrong finding.

## Open items

- **Google hosted arms.** Synchronous is proven correct but rate-limited to 5,000
  texts/minute/model and forfeits the 50% batch discount. Use file-based batch
  with per-line keys so ordering cannot drift. Currently valid:
  `gemini-001-sim` on all three sources, `gemini-001-ret` on FR only.
- **WordNet** never run against these sets.
- **`git add research/evidence/`.** Nothing in this programme is tracked.
- **E-V4 is closed on both halves.** The judged half ran as two blind passes;
  71.4% of admitted `relatedMatch` survives, and the failures are 8/10
  unprincipled edit-distance rows.
- **A three-value `basisOfAssociation` instrument** is the fix for the next blind
  sample. This one was analysed on a restricted denominator, not re-asked.
- **E-V3 is buildable now.** The 65-row intra-vocabulary re-review survives as
  `atlas-candidate-path-evidence-65.json` in the sealed archive; it needs one
  blind pass over a cross-vocabulary sample stratified to the same class mix.
- **E-V2's second half is still open.** The calibration question is answered from
  recorded bytes; the design's *other* half — a second independent pass from a
  different model family, and a third with controls flagged adversarial — has not
  been run. It is now a lower priority: the reviewer it was meant to check turned
  out to be the conservative one in the room.
- **`/tmp` promotion is done** — see the section below. The 4.6 GB
  `learned-sparse` model cache was deliberately left behind as regenerable.

## Wave 1 results (executed 2026-08-06)

Artifacts: `wave1-evidence.json`, `graph-report.json`, `pareto-closure.json`.
Tools: `analyze_atlas_native_relation_evidence.py`,
`analyze_atlas_native_relation_graph.py`,
`benchmark_atlas_native_view_ablation.py`.

### E-S5 — asserted-gold recall is an over-estimate, and the ranking is wrong

The earlier claim in this document that recall figures are *lower bounds* was
backwards. Closure ⊇ asserted, and arms recover direct edges far better than
distant ancestors, so scoring against the asserted subset asks only the easy
question.

| Arm | vs asserted (3,393) | vs closure (7,608) |
| --- | ---: | ---: |
| `gemini-001-sim.label` | 96.3% | 86.4% |
| `openai-3-large.label` | 93.1% | 78.0% |
| `bge-small.label` | 92.1% | 76.1% |

True ELSST hierarchy recall is **10–15 points lower** than reported. What *is*
understated is precision, since some retrieved-not-gold pairs are entailed.

**Arm ordering is not preserved.** Top-10 ordering *and* membership both change
on ELSST and ICPSR, with shifts to ±4 places. `openai-3-large.natural` gains
four; `minilm.label` and `openai-ada-002.label` lose two. The asserted-gold
rankings above are therefore partially wrong, not merely conservative.

The Pareto **front composition** changes too, not just the ordering:
`view-bge-small.maxOverLabels@100` sits on ELSST's closure front where
`openai-3-large.label@100` sat on the asserted front.

### E-S1a — unmatched-pair triage gives a precision floor

ELSST, `openai-3-large.label`:

| Depth | Retrieved | In gold | Entailed | Sibling | Neither |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,671 | 1,096 | 53 | 492 | **38.6%** |
| 10 | 23,946 | 3,788 | 762 | 3,066 | **68.2%** |
| 100 | 229,442 | 5,693 | 2,777 | 8,077 | **92.8%** |

At K1, 61.4% of retrieved pairs are gold, entailed, or share a parent. By K100
that falls to 7.2%. ICPSR tracks it (58.3% → 5.4%). This is the shallow-retrieval
argument on precision grounds, and it is the version that matters for a traversed
graph, because the K100 residue is what compounds across hops.

### E-S6 — class mix drifts where there is an equivalence class to lose

ICPSR shows the predicted pattern: equivalence falls from **24.5% of retrieved
gold at K1 to 5.8% at K100** while associative climbs 53.6% → 74.2%. ELSST barely
drifts (hierarchy 62.8% → 55.5%). Partial result: "deep retrieval buys
associative" holds for ICPSR, is weak for ELSST.

### E-S2 — individual predicates are fragmented; only the union is navigable

| Source / graph | Orphan | Components | Largest share | Pairs @1 / @2 / @3 |
| --- | ---: | ---: | ---: | --- |
| FR associative | 19.7% | 15 | 94.0% | 780 / 4,109 / 11,213 |
| ELSST hierarchy | 2.2% | 98 | 66.3% | 3,393 / 16,921 / 41,953 |
| ELSST associative | 36.3% | 121 | 86.0% | 2,848 / 12,766 / 36,645 |
| **ELSST union** | **1.2%** | **2** | **99.9%** | 6,241 / 41,949 / 177,092 |
| ICPSR hierarchy | **47.9%** | **242** | **9.0%** | 1,763 / 8,370 / 13,721 |
| ICPSR associative | 24.7% | 36 | 96.8% | 7,180 / 44,123 / 180,144 |
| **ICPSR union** | 15.5% | 7 | 99.6% | 8,943 / 68,530 / 323,432 |

**ICPSR hierarchy alone is unusable for navigation** — 242 components with the
largest holding 9% of covered concepts. Union with associative collapses that to
7 components at 99.6%. Traversal must cross predicates or it does not connect.

**The "union" in this table is hierarchy ∪ associative and excludes equivalence,
which was never stated and matters.** ICPSR's 8,943 union rows are 1,763 + 7,180;
the test set has 9,428, the difference being 485 equivalence rows. So the 589
concepts (15.5%) outside that union are *not* unreachable — **510 of them carry
an equivalence edge**. Counting every class, ICPSR has **79 concepts (2.1%)** with
no edge of any kind.

Corrected orphan figures, concepts with no edge in *any* class:

| Source | Outside hierarchy ∪ associative | With an equivalence edge | Genuinely edgeless |
| --- | ---: | ---: | ---: |
| ICPSR | 589 (15.5%) | 510 | **79 (2.1%)** |
| FR | 139 (19.7%) | 0 — FR publishes no equivalence | **139 (19.7%)** |

An earlier draft read this row as "589 concepts with no edge of any kind:
taggable but unreachable." That was wrong by roughly an order of magnitude, in
the direction that makes the graph look worse than it is.

Pair reachability is the traversal blast radius: ELSST union reaches 177,092
pairs within three hops. Read together with E-S1a, three-hop expansion over a
graph whose deep retrieval is 92.8% unexplained is not safe.

### E-S10 — cross-predicate transfer is real and asymmetric

Two hops through one predicate, scored against the other. Non-circular: the
predicate used to generate is never the predicate scored.

| Source | Direction | Candidates | Found | Recall | Cost/hit |
| --- | --- | ---: | ---: | ---: | ---: |
| ELSST | associative → hierarchy | 9,918 | 397/3,393 | 11.7% | 25.0 |
| ELSST | hierarchy → associative | 13,528 | 23/2,848 | 0.8% | 588.2 |
| ICPSR | associative → hierarchy | 36,943 | 512/1,763 | **29.0%** | 72.2 |
| ICPSR | hierarchy → associative | 6,607 | 340/7,180 | 4.7% | 19.4 |

**Associative structure predicts hierarchy far better than the reverse.** If
`A related B` and `B related C`, then `A` and `C` are often in a hierarchy
relation — thesaurus editors use `related` for near-sibling concepts, so two
hops lands on parent/child. At 25 candidates per hit on ELSST this is
competitive with text arms as a cheap add-only structural arm, and it needs no
model at all.

### E-T1..E-T4 — view ablation

Recall at K100, `labelOnly` baseline:

| Source / class | Model | labelOnly | maxOverLabels | lowercased | schemeQualified |
| --- | --- | ---: | ---: | ---: | ---: |
| FR associative | bge | 92.9% | **95.5%** | 92.9% | 94.4% |
| ELSST hierarchy | bge | 91.3% | **92.4%** | 91.3% | 89.7% |
| ELSST hierarchy | MiniLM | 89.8% | **91.5%** | 89.8% | 83.1% |
| ELSST associative | MiniLM | 84.3% | **86.9%** | 84.3% | 78.2% |
| ICPSR hierarchy | bge | 94.5% | 94.5% | 94.5% | 91.7% |
| ICPSR equivalence | bge | 95.1% | 95.1% | 95.1% | **95.9%** |

**`maxOverLabels` wins wherever concepts carry attached aliases** — the dense
analogue of the exact shared-alias anchor, confirming that bagging aliases into
one string dilutes them for encoders exactly as it did for RapidFuzz. Identical
on ICPSR, which attaches no alternate labels because access terms are separate
concepts. The change is free.

**Casing is not a confound for these models.** `lowercased` is byte-identical to
`labelOnly` everywhere; BGE and MiniLM use uncased tokenizers. Still open for
OpenAI and Google, which use case-sensitive BPE.

**`schemeQualified` mostly hurts** — MiniLM ELSST hierarchy 89.8% → 83.1%. It
dilutes short labels rather than disambiguating them. One exception: ICPSR
equivalence, 95.1% → 95.9%. Not worth pursuing.

## Cross-vocabulary crosswalk archive and blind review (executed 2026-08-06)

Dataset: `research/evidence/atlas-crosswalk-blind-review-2026-08-06/`.
Source: `research/evidence/atlas-3-mapping-evidence-2026-08-05/`.
Tools: `build_atlas_crosswalk_blind_review.py`,
`compare_atlas_crosswalk_blind_review.py`.

The 2026-08-05 mapping-evidence archive turned out to hold far more than the 582
admitted mappings: **1,095 cross-vocabulary candidates, each judged by two
independent model families, 582 admitted and 513 rejected.** The 513 rejections
are the only negative gold anywhere in the programme.

### How the candidate population was actually chosen

Not by retrieval. A fixed stratified quota under
`atlas-crosswalk-candidate-generation-v1`, identical in every crosswalk:

| Generation class | Per crosswalk | Total | Admitted | Rate |
| --- | ---: | ---: | ---: | ---: |
| `normalizedLabelEquality` | 110 | 330 | 302 | **91.5%** |
| `substringNearMiss` | 55 | 165 | 130 | 78.8% |
| `alternateLabelEquality` | 55 | 165 | 120 | 72.7% |
| `editDistanceNearMiss` | 55 | 165 | 30 | **18.2%** |
| `siblingDistractor` | 45 | 135 | 0 | 0% |
| `randomNegativeControl` | 45 | 135 | 0 | 0% |

Every candidate came from a shared string, so **no semantic-only pair could ever
enter this population**. That bounds the archive harder than "biased toward
lexical": it cannot speak to what dense retrieval adds, which is precisely what
E-S4's recall half still has to buy.

It also means the 513 rejections are three populations: **270 designed controls**
(worthless as negative gold — a seeded random pair is trivially rejectable),
**157 real hard negatives**, of which the edit-distance coincidences are the most
valuable, and **86 disputed** rows where both judges supported a relation and
disagreed on its type. Earlier drafts quoted "~9 lost true positives and roughly
234 real hard negatives"; that was an estimate made before the sets were
partitioned, and the partition supersedes it.

### The judging lattice is discarding correct answers — fewer than first reported

**86 of the 243 non-control rejections had both sealed judges supporting a
relation.** They died on incompatible relation type, not on whether a relation
exists. One independent Opus reviewer per crosswalk — three in total, each
covering that crosswalk's 365 rows, blind to all verdicts — supported a relation
in 85 of the 86:

| Crosswalk | Both judges supported, rejected | Third reviewer also supports |
| --- | ---: | ---: |
| fr-elsst | 34 | **33 (97.1%)** |
| fr-icpsr | 19 | **19 (100%)** |
| elsst-icpsr | 33 | **33 (100%)** |

That is 85 rows a reviewer would keep. It is **not** 85 rows an admission rule
recovers, and an earlier draft of this document conflated the two — the figure
appeared as "+14.6% on top of the 582 admitted". E-V1 replayed the lattice and
put the recoverable count at **37 (+6.4%)**; the section below carries the
measurement and what the difference is made of. Recovered mappings include
`Child labor`/`CHILD LABOUR`, `BUSINESSES`/`business`, `Health care`/`MEDICAL
CARE`, `Pets`/`HOUSEHOLD PETS`. (`Statistics`/`STATISTICS` appeared in this list
in earlier drafts and does not belong: one judge returned
`insufficient_evidence`, so it is a genuine `hard-negatives` rejection and no
lattice change reaches it.)

### Agreement localises to relation typing, not existence

| Crosswalk | Support agreement | Exact relation agreement |
| --- | ---: | ---: |
| fr-elsst | 95.2% | **74.4%** |
| fr-icpsr | 97.3% | **78.8%** |
| elsst-icpsr | 94.9% | **76.8%** |

This reproduces the ledger's 108-row shape (97.2% support, 82.4% exact) on ten
times the data and on the cross-vocabulary task.

Each generation class carries a **characteristic confusion**, which makes it
fixable rather than noise:

| Class | Support agreement | Exact agreement | Confusion |
| --- | ---: | ---: | --- |
| `normalizedLabelEquality` | 92.7–97.3% | **28.2–44.5%** | `same` vs `near_same` vs granularity |
| `alternateLabelEquality` | 96.4% | 29.1–69.1% | `near_same` vs `target_is_narrower` |
| `substringNearMiss` | 94.5–96.4% | 72.7–76.4% | `related` vs `target_is_narrower` |
| `editDistanceNearMiss` | 94.5–96.4% | 80.0–89.1% | coincidence rationalised into `related` |
| `siblingDistractor` | **73.3–86.7%** | 60.0–77.8% | siblings *can* legitimately be `related` |

The worst cell is the **easiest** candidate class. Everyone agrees `Statistics`
and `STATISTICS` are related; nobody agrees whether that is `same`, `near_same`,
or a granularity shift.

### `relatedMatch` is a sink for edit-distance noise

Edit-distance candidates produce `relatedMatch` at **seven times** the base rate
(43% of their admissions against 6% overall): `Bonds`/`BANKS`, `Fees`/`FINES`,
`Health`/`death`, `Medicaid`/`Medicare`. Each is a string coincidence with a
plausible association attached afterwards. `Radio`/`radios` was admitted as
`relatedMatch` when it is plainly close or exact.

Meanwhile pure coincidences — `Fish`/`FIRE`, `Wages`/`WALLS`, `Buses`/`FUMES`,
`Fees`/`FEET`, `Hay`/`PLAY` — were correctly rejected. Edit distance ≤2 on short
labels is noise generation; `Fees` is within two edits of `FEET`, `NEWS`, `SEEDS`
and `BEER`.

One coincidence, `Travel`/`TRADE`, had **both judges support it** and survived to
the vote. It was rejected only because they disagreed about which relation it was.

E-V4 and E-V5 have since put numbers on all of this and narrowed the diagnosis:
the 7.2× lift is real, but it belongs to the *unprincipled* portion of the arm —
`numberVariant` and `spellingVariant` candidates admit at ~81% and produce almost
no `relatedMatch`, while the 149 coincidences admit at 11.4% and return
`relatedMatch` on 70.6% of those. See the replay section below.

### Directness barely cuts anything cross-vocabulary

**547 of 582 admitted mappings (94.0%) were marked `direct_candidate`** by the
independent reviewers; only 35 were `generic_thematic`. The 65-row
intra-vocabulary re-review cut 80%.

That asymmetry matters: cross-vocabulary mappings are mostly equivalence and
hierarchy between concepts that genuinely are the same or nested, leaving little
room for generic-thematic noise. The directness problem was largely an artifact
of judging *associative intra-vocabulary* pairs. The strict rubric is expensive
to apply and may buy very little on the production task.

### Reviewer calibration — the caveat that turned out to be backwards

This section previously read: the independent reviewers rejected only 68.9% /
67.8% / 85.6% of controls against **100%** for the sealed judges, so the
corroboration above came from a reviewer that flunked a calibration the judges
passed. Every number in that sentence is real except the one it was measured
against.

The 100% was never measured. E-V2 measured it — the sealed judges name a
relation on **55.6%** and **57.0%** of sibling distractors, and the reviewer they
were used to discredit names one on **48.1%**. What the 100% actually described
is a control-class exclusion that ran *before* the lattice, so no control could
be admitted whatever a judge said about it. Detail in the section below.

One caveat does survive unchanged: each row carries exactly **one** independent
opinion — three reviewers split across three crosswalks, not three opinions per
row — so this is corroboration, not consensus.

## Benchmark sets derived from the archive (built 2026-08-06)

Dataset: `research/evidence/atlas-crosswalk-benchmarks-2026-08-06/`.

The archive is packaged as **five explicitly-scoped evaluation sets, not gold**.
Each carries `usableFor` and `notUsableFor` in the manifest so the constraint
travels with the data rather than living in a document nobody reads, plus a
top-level `populationBias` field.

| Set | Rows | Usable for | Not usable for |
| --- | ---: | --- | --- |
| `positives.jsonl` | 582 | does an arm surface known mappings; ranking position | **recall denominator** — the population is string-derived |
| `hard-negatives.jsonl` | 157 | precision against string-matching arms | precision against dense arms — contains nothing they uniquely propose |
| `controls.jsonl` | 270 | reviewer and judge calibration | retrieval precision of any kind |
| `disputed.jsonl` | 86 | benchmark for adjudication policy | positives — **deliberately unresolved** |
| `directness.jsonl` | 1,095 | cross-vocabulary directness calibration | ground truth — one opinion per row (the "failed calibration" caveat is retired by E-V2) |

The four decision sets are mutually exclusive and cover all 1,095 candidates.

**`disputed` stays unresolved on purpose.** It is the only benchmark for
adjudication policy: any proposed lattice change or class-conditioned prior can
be scored on whether it resolves these correctly. Resolving them now destroys
that test set, and there is no clean basis anyway — two sealed judges disagreed
on type and the third reviewer sometimes supplied a third.

An **independent verifier** re-derives every claim from the original archive
without importing the builder: partition integrity, counts, positives resolving
bidirectionally to assertions, controls never admitted, labels re-derived for all
2,190 rows, manifest digests, canonical ordering. **10/10 checks pass.** It was
itself adversarially validated by injecting four faults into a copy of the real
suite; all four were caught.

One result the verifier confirmed independently: **86/86 disputed rows carry two
different `verdictRelation` values.** Not most — all of them. Every disputed row
died on relation-type disagreement and none on anything else.

**Governance.** The source archive's README states these records "preserve
historical machine evidence" and "do not authorize a broader use ceiling or turn
derived relations into editorial assertions." Packaging as evaluation sets is
within that. Promoting any of the 86 into the graph is a release decision
requiring its own authority. E-V1 has now sized what a rule could take back —
37 of them — which is an input to that decision, not a substitute for it.

## The free replay experiments — E-V1, E-V2, E-V4, E-V5, E-V7 (run 2026-08-06)

Evidence: `research/evidence/atlas-crosswalk-admission-replay-2026-08-06.json`.
Tool: `replay_atlas_crosswalk_admission.py`. Free — replay only, no provider
call, nothing judged again. The 86 disputed rows are **scored, never resolved**.

**What population this is.** All 1,095 rows are *proposed* cross-vocabulary
pairs. No source publishes a mapping to another vocabulary, so none of this is a
publisher assertion — a label-oriented string matcher generated the candidates
and two model families judged the proposals. The 16,449-row native-relation test
sets, which *are* publisher assertions, are a separate dataset and are not
involved in anything below. Source hierarchy enters at exactly one point, and it
matters for E-V2: see the sibling-distractor note there.

E-V1 and E-V2 were named the highest-priority next work on the strength of a
finding worth "+14.6% of the graph, free and already paid for, currently resting
on one reviewer that failed its own control calibration." Both halves of that
sentence turned out to be wrong, in opposite directions. E-V4 and E-V5 then
turned the generator diagnosis into a better admission rule than either
experiment proposed on its own.

### The rule being varied had to be reconstructed first

A replay harness that cannot reproduce the decision it is varying cannot say
anything about the variation, so the first thing the tool does is derive the
admission rule from the recorded outcome and check it. The lattice alone —
both judges support, verdicts identical or `same`/`near_same` — admits **651**
of the 1,095 rows. The archive admitted 582.

The 69-row gap is entirely controls: 64 sibling distractors and 5 random
negatives that cleared the lattice on judge verdicts and were admitted by
nothing. Add a **control-class exclusion ahead of the lattice** and the rule
reproduces the recorded set exactly — 582 of 582, **zero mismatches** across all
1,095 rows. Every candidate carries its `generationClass` in its own evidence
artifact, so the exclusion had the field it needed.

That is the correct statement of the production v2 rule, and it was not written
down anywhere before this replay.

### E-V1 · The class-conditioned lattice recovers 37, not 85

Four lattices, same verdicts, same population. `ctrl+` counts controls the
lattice would newly admit **with the class exclusion lifted** — the only way to
see what a relaxation would let through:

| Rule | Admitted | Δ | `ctrl+` | Newly admitted |
| --- | ---: | ---: | ---: | --- |
| R0 · production v2 | 582 | — | — | — |
| R1 · + one granularity step, label-equality classes only | 619 | +37 | +0 | reviewer supports 37/37, names one of the two judges' relations 35/37, calls all 37 `direct_candidate` |
| R2 · + one granularity step, any non-control class | 622 | +40 | +0 | supports 40/40, names a judge relation 38/40, direct 40/40 |
| R3 · + associative compatible with directional | 667 | +85 | **+4** | supports 84/85, names a judge relation 79/85, direct **72/85** |
| R4 · **R1 + edit-distance rows that are real orthographic variants** | 621 | **+39** | **+0** | supports 39/39, names a judge relation 37/39, direct 39/39 |

R1 is the rule the design specified: treat `same`, `near_same`, and a one-step
granularity shift as compatible, for `normalizedLabelEquality` and
`alternateLabelEquality` candidates only. It recovers **37 rows, +6.4%** on the
582 — real, free, and less than half the advertised figure.

R4 is not in the design; it falls out of running E-V5 alongside E-V1. The
granularity collapse is safe wherever two labels denote the same term, and a
number or US/UK spelling variant qualifies as squarely as an alias does. Adding
that one eligibility test reaches **`BUSINESSES`/`business`** and **`Child
labor`/`CHILD LABOUR`** — both obviously correct, both left behind by R1 —
without touching any of the 149 edit-distance coincidences. **39 rows, +6.7%,
still zero controls.**

**R4 is a subset of R2, not a rival to it.** An earlier draft of this section
claimed R2 reached its 40 rows "by admitting any class, including a substring row
and two coincidences". That is false and is withdrawn. R4 ⊂ R2 by construction,
and the two rules differ by exactly **one** row — `ROAD TRAFFIC`/`traffic`, a
`substringNearMiss` pair the judges called `target_is_broader` and `near_same`.
The two edit-distance rows R2 adds beyond R1 are *the same principled variants
R4 admits*, not coincidences.

So the choice between them is not a yield question — one row in 582 is 0.17%,
well inside any noise this archive can resolve. It is whether the collapse should
be bounded by a stated reason. R4 can name why every row it admits denotes the
same term; R2 admits on "the verdicts were one step apart" and nothing else. That
is a defensible preference, not a measured advantage, and it should be recorded
as one.

Getting to 85 requires R3, which treats `related` as compatible with
`target_is_broader`/`target_is_narrower`. That is not a granularity shift; it is
a disagreement about the *kind* of link, and it costs exactly what the design
said would disqualify a rule: **four more sibling distractors**. Its recovered
rows are also visibly thinner — the reviewer calls only **72 of 85**
`direct_candidate`, against 37 of 37 under R1.

The 86 rows split by what the judges actually disagreed about:

| Disagreement | Rows | Recovered by |
| --- | ---: | --- |
| `near_same`/`same` versus a direction | 40 | R1/R2 — a granularity step |
| `related` versus a direction | 40 | R3 only — a different kind of link |
| `near_same`/`same` versus `related` | 5 | R3 only |
| `target_is_broader` versus `target_is_narrower` | 1 | nothing — the judges contradict |

Two roughly equal halves. Only the first is a lattice defect. The second is a
genuine open question about whether a pair is associative or hierarchical, and
`disputed.jsonl` keeps it open on purpose.

**Decision.** R3 fails the stated bar and is out. Among the rest, R4 is the
recommendation, and the reason is stated honestly: it is not that R4 measures
better than R2 — it cannot, at one row of difference — but that R4 can name why
every row it admits denotes the same term, and R2 cannot. Every row either
recovers is supported and called `direct_candidate` by an independent reviewer,
and all come from the disputed set by construction. Promotion into the graph
remains a release decision under its own authority; this sizes the prize, it does
not grant it.

### E-V2 · The reviewer was not worse calibrated — and the 100% baseline never existed

Support rate on seeded negatives — a relation was *named*, whatever admission
later did with the row:

| Control class | `google-gemini` | `openai` | Independent reviewer |
| --- | ---: | ---: | ---: |
| `randomNegativeControl` | 5.2% | 5.2% | **3.7%** |
| `siblingDistractor` | 55.6% | 57.0% | **48.1%** |

The reviewer is at or below both sealed judges in every per-crosswalk cell of
both classes. The "68.9% / 67.8% / 85.6% against 100%" comparison measured the
reviewer against a filter, not against a judge.

**How far to push that.** The *reversal* is a fact about mechanism and does not
depend on statistics: the 100% was a control-class exclusion, so the reviewer was
never measured against a judge at all. The *direction* of the remaining gap is
not significant. Fisher exact on the raw counts gives **p = 0.77** on random
negatives (7/135 and 7/135 against 5/135) and **p = 0.27 / 0.18** on sibling
distractors (75/135 and 77/135 against 65/135). At n=135 per class this archive
cannot resolve a difference this size. The supportable claim is that the reviewer
is **not worse** than the judges, and that the finding it was used to discredit
therefore stands — not that it is better. An earlier draft of this heading said
"better calibrated"; that overstated the evidence and is withdrawn.

Put on the same basis —
`compare_atlas_crosswalk_blind_review.py` now computes the baseline instead of
asserting it — the original table reads the other way round:

| Crosswalk | Controls rejected, reviewer | Controls rejected, sealed judges |
| --- | ---: | ---: |
| fr-elsst | **68.9%** (62/90) | 65.6% (118/180) |
| fr-icpsr | **67.8%** (61/90) | 65.6% (118/180) |
| elsst-icpsr | **85.6%** (77/90) | 76.7% (138/180) |

Sibling distractors are also not clean negatives. Every one was built by
`target-sibling-of-label-equal-match`: take a true label-equal pair, then swap the
target for one of its siblings **under the target vocabulary's own published
`broader` links** — each evidence artifact records the `sharedBroader` and
`siblingOf` IRIs it used. So the planted pair genuinely shares a parent in the
publisher's hierarchy, `related` is frequently the correct answer, and it is what
the judges said in **117 of their 152** supporting verdicts on that class. The
negative label came from the seeding script's intent, not from any source
asserting the pair unrelated.

The only clean negative class is `randomNegativeControl`, where all three
reviewers sit between 3.7% and 5.2%.

The reviewer discriminates, which is the question that actually mattered:

| Population | Reviewer supports |
| --- | ---: |
| `positives` — sealed-admitted | 99.3% |
| `disputed` — both judges supported, type disagreed | 98.8% |
| `hard-negatives` — real candidates the judges rejected | **15.9%** |
| `randomNegativeControl` | **3.7%** |

A "supports" verdict is worth **6.2×** against real rejected candidates and
**26.8×** against random pairs. This is not a reviewer that agrees with
everything.

**But it confirmed the wrong proposition.** Every one of the 86 rows already had
two judges asserting a relation exists; asking a third whether one exists was
pre-answered, and 85/86 is the expected result rather than an informative one.
The binding question was always *which* relation, and there the reviewer is a
third opinion — it names one of the two judges' relations 79/85 — not a
tiebreak. The +14.6% figure was the count of rows a reviewer would keep, read as
though it were the count a rule recovers.

### E-V4 · `relatedMatch` is a sink, and it has one owner

What SKOS relation each generation class earns when it is admitted. Base rate is
35 `relatedMatch` in 582 admissions, **6.0%**:

| Class | Admissions | `relatedMatch` share | 95% CI | Lift |
| --- | ---: | ---: | :---: | ---: |
| `normalizedLabelEquality` | 302 | **0.0%** | 0.0–1.3% | 0× |
| `alternateLabelEquality` | 120 | 8.3% | 4.6–14.7% | 1.4× |
| `substringNearMiss` | 130 | 9.2% | 5.4–15.4% | 1.5× |
| `editDistanceNearMiss` | 30 | **43.3%** | 27.4–60.8% | **7.2×** |

Edit distance against every other class pooled: **Fisher exact p = 7.6 × 10⁻¹⁰**.
Thirty admissions is a small denominator and the interval is correspondingly wide,
but the *contrast* is not close. The `normalizedLabelEquality` zero is a real
zero: 0 of 302, upper bound 1.3%.

The claim holds exactly as stated. Label equality never produces `relatedMatch` —
not rarely, never. Edit distance produces it at 7.2× base, and supplies **13 of
the 35** `relatedMatch` admissions in the whole archive off 5% of the admissions.
E-V4's other half — a reviewer marking each admitted `relatedMatch` as genuine
association or post-hoc rationalisation — has not run and still needs judging.

### E-V5 · The edit-distance arm is two arms, and only one of them works

Each of the 165 `editDistanceNearMiss` candidates classified by *why* its labels
differ: case or diacritics, number agreement, a known US/UK spelling — or no
reason at all.

| Variant class | Generated | Admitted | Rate | 95% CI | `relatedMatch` share of those |
| --- | ---: | ---: | ---: | :---: | ---: |
| `numberVariant` | 11 | 9 | 81.8% | 52.3–94.9% | 1/9 (11.1%) |
| `spellingVariant` | 5 | 4 | 80.0% | 37.6–96.4% | 0/4 (0%) |
| `unprincipled` | 149 | 17 | 11.4% | 7.2–17.5% | **12/17 (70.6%)** |

**Do not quote the per-variant rows on their own.** At n=11 and n=5 those
intervals are 40 and 60 points wide; they cannot distinguish 80% from 55%. What
the data supports is the pooled contrast, and that is not marginal:

| | Generated | Admitted | Rate | 95% CI |
| --- | ---: | ---: | ---: | :---: |
| **Principled** (number, spelling, diacritic) | 16 | 13 | **81.2%** | 57.0–93.4% |
| **Unprincipled** | 149 | 17 | **11.4%** | 7.2–17.5% |

Admission rate, Fisher exact **p = 7.3 × 10⁻⁹**; the intervals do not touch.
`relatedMatch` share of admissions, principled against unprincipled, **p = 0.001**.

Sixteen candidates — under 10% of the arm — carry 13 of its 30 admissions at an
81% rate and produce almost no `relatedMatch`. The other 149 admit at 11.4%, and
**seven of every ten of those admissions come back as `relatedMatch`**.

That sharpens E-V4's finding into something actionable. `relatedMatch` is not a
sink for *edit distance*; it is a sink for the **unprincipled portion** of edit
distance, which is where a string coincidence gets a plausible association
attached after the fact. `SEXUAL BEHAVIOUR`/`sexual behavior` and
`REFERENDUMS`/`referendum` are not that; `Fees`/`FEET` and `Bonds`/`BANKS` are.

**Decision.** Replace raw Levenshtein ≤2 with the variant rule. It costs 149 of
165 candidates and 17 of 30 admissions, 12 of which were `relatedMatch` on a
string coincidence. It also earns two disputed rows back through R4.

*Caveat on the classifier:* it is orthographic, not statistical — case and
diacritic folding, an English pluralisation rule, and a ten-entry US/UK rewrite
table. It will not generalise past English, and `Traffic regulation`/`TRAFFIC
REGULATIONS` shows the judges can still reject a principled variant (that one is
in `hard-negatives`, and looks like a judge error).

### E-V7 · Admission is order-independent, for a reason worth recording

Five shuffled orders, identical admitted set every time. That is not a lucky
result — **the rule carries no cross-row state at all**. It reads one row,
inspects that row's generation class and its two verdicts, and decides.

The concern the 2026-08-05 analysis raised — that graph-minimality and redundancy
checking must be a batch or fixed-point rule rather than an incremental one — is
correct in general and simply does not apply to what shipped: this archive's
admission performed no redundancy or minimality step, which is why its 582
admitted candidates produced 582 assertions with nothing collapsed (confirmed
independently by the benchmark verifier). E-V7 is answered *for the current rule*
and stays open for any future one that adds such a step.

### What this changes

- The recoverable-mapping prize is **39 rows, +6.7%** under R4 (37 under the rule
  as designed), not 85 and +14.6%.
- The production v2 admission rule is **control-class exclusion, then lattice**,
  reproduced exactly and now written down — and it is order-independent because
  it keeps no cross-row state.
- The independent blind review is **usable as a comparison signal**, and the
  benchmark sets' "failed its own control calibration" caveat is retired. What
  remains true is that it is one opinion per row.
- Control rejection rate is **not** a judge-quality measurement on this archive
  and should not be reported as one. Sibling distractors measure willingness to
  call a shared-parent pair `related`, which is a rubric question, not an error
  rate.
- The edit-distance arm should be **restricted to orthographic variants**. That
  removes 149 of 165 candidates, 12 of the archive's 35 `relatedMatch`
  admissions, and buys two correct disputed rows back.
- `relatedMatch` is a real sink but it has one owner: the unprincipled half of
  edit distance. Label equality never produces it. Whether the surviving 35 are
  genuine associations still needs a reviewer — that half of E-V4 has not run.

## E-V4's judged half — two blind passes over a sealed sample (2026-08-06)

Sample: `research/evidence/atlas-relatedmatch-blind-review-2026-08-06/`, 95 rows.
Tools: `build_atlas_relatedmatch_blind_review.py`, `compare_atlas_relatedmatch_blind_review.py`.

Replay could count how often `relatedMatch` was *awarded*. It cannot tell you
whether the award was deserved. That needs a reviewer, blind, and the sample was
built so the answer could not be inferred from the sample: **all 35**
`relatedMatch` admissions (a census, not a sample), **36** admissions carrying
other relations drawn from the same generation classes, and **24** seeded controls
riding along unlabelled. Ordered by task id. Blind digest
`sha256:baf5c6726e0fcd5e…`, key withheld until decisions were written.

Two independent passes over identical bytes: one neutral, one told the sample
contains planted coincidences and that finding-a-relation-because-you-can is the
failure mode. **Same model family in both**, so the gap between them measures
framing sensitivity and annotator stability — not cross-family agreement.

### The answer: `relatedMatch` is mostly deserved, and the failures have one address

A row **survives** if the reviewer asserts a relation *and* says the connection
runs through meaning rather than spelling.

| Stratum | n | Neutral | Adversarial | Both |
| --- | ---: | ---: | ---: | ---: |
| `relatedMatch` admissions | 35 | 85.7% | 71.4% | **71.4%** |
| Other admissions | 36 | **100%** | **100%** | **100%** |
| `siblingDistractor` | 12 | 16.7% | 8.3% | 8.3% |
| `randomNegativeControl` | 12 | 0% | 0% | 0% |

**Every one of the 36 non-`relatedMatch` admissions survives both passes.** Not
most — all 36, under both framings. Against that floor, 10 of 35 `relatedMatch`
admissions fail at least one pass. The contrast clears significance under both
framings despite 35 rows: **Fisher exact p = 0.025** neutral, **p = 0.0004**
adversarial. So the sink is real, it is confined to
`relatedMatch`, and it is **28.6% of that class, not all of it**: the label-count
figures (43.3% of edit-distance admissions, 70.6% of unprincipled ones) counted
how often the label was applied, and roughly seven in ten of those applications
turn out to be defensible.

### The failures validate E-V5's classifier from outside

Where the 10 failing rows live:

| Generation class | Variant class | Failures |
| --- | --- | ---: |
| `editDistanceNearMiss` | **`unprincipled`** | **8** |
| `alternateLabelEquality` | — | 1 |
| `substringNearMiss` | — | 1 |
| any | `numberVariant` or `spellingVariant` | **0** |

Neither pass ever called a principled variant's connection orthographic, and
neither rejected one: **0 of 6 `numberVariant` and 0 of 3 `spellingVariant`**, in
both passes. Reviewers who never saw the classifier, judging meaning alone,
partitioned the edit-distance arm exactly where the orthographic heuristics put
the line. That is independent confirmation from a direction the classifier could
not have influenced, and it is the strongest support the E-V5 rule has.

### Control calibration, and one more nail in the E-V2 reversal

Does a pass assert a relation on a seeded negative?

| Class | Neutral | Adversarial | Prior reviewer | `gemini` | `openai` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `randomNegativeControl` | **0%** | **0%** | 3.7% | 5.2% | 5.2% |
| `siblingDistractor` | 25.0% | **8.3%** | 48.1% | 55.6% | 57.0% |

Both new passes are more conservative than the sealed judges *and* than the
reviewer the earlier draft accused of over-generosity. Three independent Opus
reviewers have now been measured against the same seeded negatives and all three
sit below both judges. The permissive party in this archive is the judge pair.

### Framing moves about a tenth of the answers

| Agreement between the two passes | Rate |
| --- | ---: |
| `relationExists` | 89.5% |
| `bestRelation` | 86.3% |
| `basisOfAssociation` | 74.7% (24 rows flipped) |

**Prompt framing alone moves ~10% of existence judgments and ~14% of relation
types, on identical bytes and the same model family.** Any single-pass judging
result in this programme carries that much slack, and none of the earlier
single-pass numbers were reported with it. Framing buys conservatism precisely
where the hard cases are: sibling-distractor support falls 25% → 8% between
passes while random negatives stay at 0% in both.

Both passes agree with the *earlier* blind reviewer on exact relation more than
that reviewer agreed with the sealed judges — **85.3%** and **80.0%** against
74.4–78.8%. The Opus reviewers cluster; the judge pair is the outlier.

### An instrument defect, stated rather than patched

`basisOfAssociation` offered two values and no third for *no association at all*.
Both passes hit that gap on rows they rejected and resolved it in opposite
directions: the neutral pass filed plain decoys under `conceptual` (whatever weak
link exists runs through meaning), the adversarial pass filed every rejection
under `orthographic` ("not conceptual" being the only home available). Both are
defensible; they are irreconcilable; and on control rows the field consequently
swings from 0% to 100% between passes on identical bytes.

The question is only well posed where a reviewer asserted a relation, so every
figure above uses that restricted denominator, and the tool now reports both.
**The sample was not re-asked.** A third pass with a fixed three-value instrument
would produce a cleaner number, and it would be a number chosen after seeing the
first two — which is how a measurement turns into a search. The fix belongs in
the *next* sample, not this one.

### One thing that did not work as designed

Told only that plants existed and roughly what kinds, the adversarial pass
identified **23 of the 24 controls** without the key — 95.8% recall at 69.7%
precision, and 13 of 13 on its "suspected random pairing" tier. Seeded controls
are not invisible to a warned reviewer, so their value as hidden calibration is
weaker than assumed anywhere they are used against a reviewer who has been told
to expect them.

## The variant classifier, blind-audited (2026-08-06)

Sample: `research/evidence/atlas-variant-classifier-audit-2026-08-06/`.
Tools: `build_atlas_variant_classifier_audit.py`, `compare_atlas_variant_classifier_audit.py`.

R4 admits mappings on the strength of a classifier that decides whether two
near-identical labels differ *for a reason*. That classifier is string
heuristics — case folding, one English pluralisation rule, a ten-entry US/UK
rewrite table — and heuristics that small are exactly the kind that look right on
the examples their author checked. So all **165** edit-distance pairs went to a
blind reviewer asked the same question from the other side: judge the morphology,
not the strings, with the classifier's verdict withheld.

| | Result |
| --- | --- |
| Exact four-way agreement | **98.8%** (163/165) |
| Principled vs unprincipled agreement | **98.8%** |
| **Precision on the principled class** | **16/16 = 100%** [80.6–100.0%] |
| **False principled** — coincidences R4 would admit | **0** |
| False unprincipled — real variants the restriction drops | 2 |

**Zero false promotions.** Every pair the classifier called a real orthographic
variant, an independent linguistic reading agreed was one. For a rule that feeds
a traversed graph, that is the error direction that matters: the classifier
under-admits and never over-admits.

The two misses are both **punctuation, not morphology** — the one thing `_fold`
does not normalise:

| Pair | Classifier | Reviewer |
| --- | --- | --- |
| `CYBERSECURITY` / `cyber security` | `unprincipled` | `spellingVariant` — closed vs open compounding |
| `STILL-BIRTH` / `stillbirths` | `unprincipled` | `numberVariant` — plural; the hyphen is incidental |

**Neither costs anything today**, and this is worth stating precisely rather than
fixing on reflex: both pairs are already in `positives`, admitted as `exactMatch`
with both judges saying `same`. The lattice never needed the variant test for
them. Folding hyphens and whitespace into `_fold` would raise the classifier's
recall from 16/18 to 18/18 and change **zero** admissions on this archive. It is
a correctness improvement with no measured yield here, so it belongs with the
generator restriction when that ships, not as a hot fix.

The reviewer also independently rejected the traps the classifier rejects —
`ADOLESCENCE`/`adolescents`, `ECONOMISTS`/`economics`, `Prisoners`/`prisons`,
`Aged`/`age` — as derivational shifts of sense rather than number variants. Both
methods agree that a plural-looking edit is not a plural.

*Bound honestly:* 16 principled rows gives a 95% interval of 80.6–100%. The
classifier could be as low as 4-in-5 on a larger population; what this rules out
is that it is careless.

## Evidence promoted out of `/tmp` (2026-08-06)

Manifest: `research/evidence/atlas-tmp-evidence-promotion-2026-08-06.json`.
Tool: `promote_atlas_tmp_evidence.py`.

The 2026-08-05 ledger closes with a requirement that was never executed:

> Before integration, promote every selected artifact now held under `/tmp` into
> durable content-addressed evidence storage: exact benchmark inputs, BGE rank
> bytes and manifest, blind samples and fixed decisions, cost receipts, and the
> selected frontier result. Reopen and verify every digest after promotion.

The working directory was still there — `/tmp/refspec-candidate-benchmark.ANhNrc`,
4.8 GB — and still held artifacts that **cannot be regenerated at any price**. A
sealed decision cannot be re-sealed once the reviewer has seen the key, so losing
those bytes destroys the evidence permanently rather than expensively.

| Tier | Files | Size | Destination | Rationale |
| --- | ---: | ---: | --- | --- |
| `sealed` | 34 | 9.0 MB | `research/evidence/` — **committed** | irreplaceable decisions and the receipts the acceptance gates cite |
| `bulk` | 450 | 132 MB | `output/` — git-ignored | rank matrices and provider receipts; regenerable for ~$0.05 |
| `session` | 70 | 100 MB | `output/` — git-ignored | E3 rank artifacts; ~1 hour of compute to rebuild |

The split is by **replaceability**, not convenience. The repository tracks 54 MB
of evidence with a 4.2 MB largest file and should not absorb 232 MB of
regenerable binaries — but digests for every file in every tier are in the
committed manifest, so the repo records what exists, where, and what it hashed
to even for bytes it does not carry.

**Verification.** Every copy was re-read and re-hashed at the destination rather
than trusted. Seven sealed artifacts hash identically to digests the 2026-08-05
ledger recorded — `judge-audit-blind-108.json`, both blind review samples, the
outside-K50 residual sentinel, the 65-row path evidence, and both manual-audit
analyses. That is byte-level proof the promoted copies are the same bytes the
sealed research chain refers to. A re-run reports 554 unchanged, 0 copied.

**Deliberately left behind:** the 4.6 GB `learned-sparse` directory — model
downloads and rank receipts, fully regenerable, and almost certainly what would
have triggered a `/tmp` cleanup in the first place.

## Convergent external analysis (2026-08-05)

A separate analysis of the same ledger, produced a day before this session,
independently reached several of the same conclusions: that a single global K is
an awkward control knob, that `relatedMatch` is where the graph turns into
"semantic kudzu," and that K50 rests on one manually retained case that happened
to land at rank 50. Its recommendation was **deterministic floor + BGE K10 +
relation-specific rescue**, with K50 kept as a diagnostic tail pool.

That shape is **better supported by this document's evidence than K50 is** — the
precision triage (61% defensible at K1, 7% at K100) and the class-mix drift both
argue for shallow-plus-targeted. Three corrections to its basis:

- Its cost figures ($1,762.95 at K5 versus $8,292.56 at K50) use the conservative
  400-token-per-row allowance against a median 61 observed, so both are
  plausibly ~3x high and the *ratio* matters more than the absolute.
- "All 582 historical mappings recovered by the deterministic floor" is circular:
  the floor recovered them because the floor generated them.
- It lists dense and lexical as co-equal discovery paths for `exactMatch`. Cross
  vocabulary, `normalizedLabelEquality` admits at **91.5%** — lexical does nearly
  all the work there and dense is close to redundant.

It also contributes a defect this document had missed:

> Newly admitted mappings must be evaluated together using a deterministic
> fixed-point or batch rule, not one at a time in arbitrary order.

**Order-dependent admission is a real bug class.** If redundancy is checked
incrementally, whether `C→D` looks redundant depends on whether `A→B` was
admitted first, so the resulting graph depends on admission order. In a system
whose entire discipline is content-addressed reproducibility, that is a defect
rather than a preference. E-V7 in the designs document tests for it.

## Experiment catalogue

Each entry: what to hold, what to vary, what to measure, what it decides.

### A. Graph quality

**S1 · Edge precision under traversal.** Hold the admitted graph fixed. Sample
retrieved-but-unasserted pairs, split into *entailed* (transitively implied) and
*not entailed*, judge only the second group. Measure per-edge error `p`, then
compound: `1-(1-p)^hops`. Decides whether to admit at high recall or high
precision. At 5% error, three hops is ~14% wrong. **Recall does not compound;
precision does.** Every number in this document is recall.

**S2 · Graph coverage and connectivity.** Hold the graph fixed. Count zero-edge
concepts, components, diameter, hub concentration. Measure orphan rate. Decides
whether traversal can reach a concept at all.

**S3 · Path explainability.** Vary traversal depth. Emit the edge path per
result. Measure the fraction a reviewer accepts. Decides the exposed depth and
gives users a channel to report bad edges.

### B. Atlas construction

**S4 · Cross-vocabulary transfer.** Hold arms fixed. Vary the task:
intra-vocabulary (done) versus cross-vocabulary (CRS Policy × FR, 22,560 pairs,
exhaustively judged, ~$150). Measure whether arm *ordering* is preserved.
Decides whether anything in this document configures production. **This is the
load-bearing untested assumption.**

**S5 · Closure-scored recall.** Hold arms and corpus fixed. Vary the gold:
asserted versus transitive closure. Measure recall under both. Decides how much
of the current miss is gold sparseness.

**S6 · Class mix by depth.** Hold the arm fixed, vary K. Measure the
equivalence / hierarchy / associative proportion of retrieved gold at each depth.
Decides the production cutoff.

**S7 · Directness calibration.** Apply the strict rubric to a stratified sample
of the 10,808 publisher-asserted `related` edges. Measure keep rate per source.
Decides whether the bar is defensibly stricter than professional practice.

**S8 · Judge direction accuracy.** Hold pairs fixed, ablate hierarchy from the
prompt, ask for relation and direction. Measure accuracy against publisher
direction on 5,156 rows. Decides whether the adjudication lane is needed.

**S9 · Text enrichment.** Vary concept text only. Ingest whatever scope notes and
hierarchy FR and CRS publish upstream. Measure recovery of FR's own 780
associative edges before and after. Decides whether input work beats model work —
the Anatomy analogue gave +13 gold with 16,416 *fewer* candidates.

**S10 · Cross-predicate structural transfer.** Expand candidates through the
*associative* graph, score against *hierarchy* gold, and vice versa. Non-circular
by construction. Decides whether publisher association predicts hierarchy.

### C. Tagging

**S11 · Document→concept gold.** Build test sets from `topicAssignments`
cross-ring relations exactly as the native-relation sets were built. Decides
whether tagging gets free gold too.

**S12 · Asymmetric retrieval.** Hold models fixed. Vary the convention:
symmetric (what ran here) versus `RETRIEVAL_QUERY` on the passage and
`RETRIEVAL_DOCUMENT` on the concept, plus Nomic and Arctic query prefixes.
Decides the encoder config for tagging and search. **The asymmetric half of these
models is entirely untested.**

**S13 · Tagging reranker.** Score `(passage, concept)` pairs with a
cross-encoder. Measure precision at 1, 3, 5 tags. Far better fit than the
reordering-only role reranking has in Atlas construction.

**S14 · Tag count calibration.** Vary tags emitted per section. Measure precision
and recall against assigned gold. Over-tagging is what makes a hyper-connected
graph noisy at the source.

### D. Search

**S15 · Query→tag triggering.** Vary query length and specificity. Measure
whether the correct tag fires. Decides the threshold for using the graph versus
falling through to text.

**S16 · Hybrid weighting.** Vary the three weights: tag filter, dense text,
BM25. Measure nDCG against relevance derived from assignments. Decides the
ranking formula rather than tuning it by feel.

**S17 · Query-time expansion depth.** Vary expansion (exact / +equivalent /
+narrower / +related). Measure precision and recall of the document set. This is
where S1's compounding error becomes user-visible.

**S18 · Emerging-topic fallback.** Vary query recency (PFAS, AI governance).
Measure tag-trigger failure rate. Decides when to bypass the graph and when the
vocabulary needs extending.

### E. Longitudinal and structural

**S19 · Vocabulary version mapping.** Map ELSST R5→R6 and FR edition→edition,
same machinery as cross-vocabulary. Measure recall of known split/merge/retire
cases. Decides whether documents tagged years ago stay findable.

**S20 · Non-subject rings.** Vary the ring: agency, statute, jurisdiction, date,
document type. Measure what fraction of realistic queries need a non-subject
facet. Decides how much of the search problem subject tagging can solve.

### F. Methodology hygiene

**S21 · Reproducibility gate.** Encode the same corpus three times in fresh
processes. Measure digest stability. The ledger records an unexplained BGE digest
change on one host.

**S22 · Dimensionality control.** Hold the model fixed, vary output width.
Decides whether the current cross-model comparison is confounded. It currently is.

**S23 · Inter-annotator agreement.** Second reviewer on a fixed already-judged
sample. Every human judgment in the ledger is single-reviewer.

## What all of this means

### Retrieval is not the bottleneck

Dense arms recover 85–100% of publisher relations, several families do it, and
the differences between them sit inside the noise of view choice and depth. That
question is answered; further tuning has low marginal value.

### The loss is downstream, in relation typing

86 of 243 real rejections had both judges agreeing a relation exists and were
discarded over *which* relation. Support agreement runs 95–97% while
exact-relation agreement runs 74–79%, and the worst cell is the easiest candidate
class.

**A pipeline built to find relations is losing correct answers it already paid to
find, to a mechanical tie-break rule.** E-V1 sizes that loss at **39 rows,
+6.7%**, recoverable free by collapsing `same`/`near_same`/granularity wherever
the two labels denote the same term. The other ~40 disputed rows are a real
associative-versus-hierarchical disagreement, not a rule defect, and no lattice
should silently resolve them. A third judge would not help either way — it adds a
fourth opinion on relation type, not a tiebreak on existence.

### The graph is more fragile than the product bet assumes

Precision decays from 61% defensible at K1 to 7% at K100, and compounds across
hops in a way missing edges never do. Individual predicates do not connect:
ICPSR hierarchy alone is 242 components with the largest holding 9%. Coverage is
the weakest of the three pillars: an earlier draft said "15–48% of concepts carry
no edge at all", but those are *per-predicate* orphan rates — the concepts they
count almost all carry an edge in another class. Counting every class, the
genuinely edgeless share is **2.1% for ICPSR and 19.7% for FR**, and FR's is high
only because FR publishes no hierarchy and no equivalence at all. Fragmentation
and edge precision are real problems; coverage is a much smaller one than this
document claimed.

### Every finding inherited from another setting was wrong

Nomic beat BGE on Conference — false here. MiniCOIL sat on both Conference Pareto
minimums — loses every slot here. The directness rubric cut 80% intra-vocabulary
— cuts 5–7% cross-vocabulary. This document said recall figures were lower bounds
— they are over-estimates. It said dense beats lexical by 20–40 points — that is
an intra-vocabulary artifact, because exact-label matching is structurally
impossible *within* one thesaurus and is the dominant signal *between* thesauri,
where label equality admits at 91.5%.

**Results do not survive a change of domain or task shape.** The intra-vocabulary
numbers in this document are calibration, not configuration.

### What is still unmeasured

Cross-vocabulary retrieval quality. Tagging accuracy. Search quality. Edge
precision on candidates a semantic arm found rather than a string matcher. That
is the whole product. This document measures candidate retrieval against
intra-vocabulary publisher relations — a proxy for a proxy — plus one archive
whose candidates were all string-derived.

## Priority

**Scope for this phase: knowledge-graph relations only.** Documents come after.
That line matters more than it looks, because it moves several things this
document previously ranked highly *behind* it — everything that reads document
text or topic assignments is deferred, however cheap it is.

| Deferred until the document phase | Why it is blocked |
| --- | --- |
| `E-S11` document→concept gold | needs documents |
| `V-1` co-assignment PMI | needs topic assignments |
| `V-2` citation extraction | needs document text |
| `V-3` synthesised scope notes | needs assigned documents |
| `V-9` docket and legislative lineage | needs document chains |
| `E-S12`–`E-S18`, `E-S20` | tagging, search and query facets |

That is a real loss for the traceability requirement — `V-2` was the cheapest
route into the `legalIdentity` ring and it is document-derived. **`V-7` is not**,
and it becomes the way in: CFR titles/parts, USC titles, NAICS and budget
function codes are published, already-hierarchical, vocabulary-side spines.

### Ranked, vocabulary-only

1. **Apply the fixes that are already measured.** R4 recovers **39 mappings
   (+6.7%)**; R2 recovers 40 and differs by one row, so either is defensible and
   R4 is the one that can state a reason for every admission. Both add zero
   control admissions. Restricting edit distance to orthographic variants drops
   149 of 165 candidates, blind linguistic audit confirms **0 false promotions in
   16**, and blind relation review confirms the aim — 8 of the 10 admitted
   `relatedMatch` rows that fail are unprincipled edit distance. What remains is a
   release decision. Do **not** extend the collapse to `related`.
2. **`E-S4a` — the coverage question, and now the top experiment.** "Comprehensive
   coverage" is the stated goal and it is the one thing this archive provably
   cannot measure: every candidate came from a string matcher, so no
   semantically-related pair with dissimilar labels could ever enter. CRS Policy
   Areas × Federal Register is 32 × 705 = 22,560 pairs — small enough to judge
   exhaustively, so recall is *known* rather than estimated. Everything else in
   this list is refinement inside a population of unknown completeness.
3. **`E-S1b` / `E-V6` — edge precision on candidates a *semantic* arm proposes.**
   ~$2, and it sets the traversal budget SpicySearch will inherit. 92.8% of
   retrieved pairs at K100 are unexplained and error compounds per hop; the
   per-edge rate has never been measured on the population production will use.
4. **`V-7` — authoritative hierarchy anchoring.** The vocabulary-side route into
   `legalIdentity`, and a cross-vocabulary bridge via a shared spine that needs no
   model and no judge. With `V-2` deferred, this is the only design in scope that
   touches the traceability requirement at all.
5. **`V-4` — generate-then-verify.** The only design that escapes the retrieval
   ceiling: ask for broader/narrower/related terms, then verify each against the
   closed vocabulary by exact and alias match. Hallucination is contained
   deterministically. ~$3, and it attacks the same coverage gap as `E-S4a` from
   the generation side.
6. **`E-S19` — ELSST R5→R6 as a cross-edition task.** Free, the managed release
   already exists, and it is structurally identical to cross-vocabulary matching —
   so it doubles as a second transfer check alongside `E-S4b`.
7. **`V-5` — order, box or hyperbolic embeddings.** Cosine is symmetric;
   hierarchy is antisymmetric and transitive. Bidirectional min-rank is a patch
   over that mismatch. Two concrete payoffs: direction for free, and native
   transitivity — exactly where closure scoring showed the largest losses.
8. **`E-S8` and `E-S7`** — judge direction accuracy and the directness rubric,
   ~$4 together. Both are vocabulary-only and both feed the admission rule.

**Deprioritised on purpose.** Further lattice and generator refinement — done,
remaining yield is single rows. `E-V8`'s cost basis, since depth is not the
binding constraint. Most of Part 1's text-variant grid: `maxOverLabels` won and
the remaining deltas sit inside the noise of everything above.

## Reproduction

Full sequence. `$C` is the corpus export path, `$R` the rank-artifact directory,
`$TS` the test-set directory. Steps 2–9 rebuild the ephemeral artifacts.

```sh
TS=research/evidence/atlas-v3-native-relation-testsets-2026-08-06

# The rank artifacts and corpus already exist — steps 2-8 are only needed if you
# change an arm or a corpus. To re-analyse what this document reports:
R=output/atlas-e3-rank-artifacts-2026-08-06/valid
C=output/atlas-e3-rank-artifacts-2026-08-06/e3-corpus.json
# ...then jump to step 9.

# To rebuild from scratch instead:
# C=/tmp/e3-corpus.json ; R=/tmp/e3-ranks ; mkdir -p $R

# 1. Test sets (durable; byte-identical across runs)
uv run python tools/build_atlas_native_relation_testsets.py

# 2. Dependency-free arms, corpus export, rank export
uv run python tools/benchmark_atlas_native_relation_recovery.py --output $R/e3-recovery.json
uv run python tools/benchmark_atlas_native_relation_recovery.py --export-corpus $C
uv run python tools/benchmark_atlas_native_relation_recovery.py --export-ranks $R

# 3. 17 RapidFuzz lexical arms
uv run --with rapidfuzz python tools/benchmark_atlas_native_lexical_recovery.py \
  --corpus $C --output $R

# 4. Five local dense families (sequential by design — memory)
uv run --no-project --with fastembed --with numpy \
  python tools/benchmark_atlas_dense_relation_recovery.py --corpus $C --output $R

# 5. Text/prompt variants incl. maxOverLabels
uv run --no-project --with fastembed --with numpy \
  python tools/benchmark_atlas_native_view_ablation.py --corpus $C --output $R

# 6. Learned sparse (add sentence-transformers for the OpenSearch arm)
uv run --no-project --with fastembed --with scipy --with numpy \
  python tools/benchmark_atlas_native_learned_sparse_recovery.py --corpus $C --output $R
uv run --no-project --with "sentence-transformers>=5" --with scipy --with numpy --with fastembed \
  python tools/benchmark_atlas_native_learned_sparse_recovery.py --corpus $C --output $R --model opensearch

# 7. Hosted provider arms (needs OPENAI_API_KEY / GEMINI_API_KEY in ../.env)
uv run --no-project --with google-genai --with openai --with numpy \
  python tools/benchmark_atlas_frontier_embedding_recovery.py \
  --corpus $C --output $R --state $R/jobs/state.json

# 8. Rerankers — cap by best cross-arm rank, NOT alphabetically
uv run --no-project --with "sentence-transformers>=5" --with numpy \
  python tools/benchmark_atlas_native_reranker_recovery.py \
  --corpus $C --ranks $R --output $R

# 9. Closure and sibling gold, then the frontier
uv run python tools/analyze_atlas_native_relation_evidence.py \
  --corpus $C --test-sets $TS --ranks $R --export-gold $R --output $R/wave1-evidence.json
uv run python tools/optimize_atlas_native_relation_frontier.py --ranks $R --output $R/frontier.json

# 10. Structural analyses (need only the test sets — no rank artifacts)
uv run python tools/analyze_atlas_native_relation_structure.py --test-sets $TS --output $R/structure.json
uv run python tools/analyze_atlas_native_relation_graph.py --test-sets $TS --output $R/graph.json

# 11. Crosswalk pipeline (independent of everything above)
uv run python tools/build_atlas_crosswalk_blind_review.py \
  --archive research/evidence/atlas-3-mapping-evidence-2026-08-05 \
  --output research/evidence/atlas-crosswalk-blind-review-2026-08-06
uv run python tools/build_atlas_crosswalk_benchmarks.py
uv run python tools/verify_atlas_crosswalk_benchmarks.py    # expect 10/10

# 12. E-V1/E-V2/E-V4/E-V5/E-V7 replay (expect 582 reproduced, 0 mismatches; R4 = +39, ctrl +0)
uv run python tools/replay_atlas_crosswalk_admission.py \
  --benchmarks research/evidence/atlas-crosswalk-benchmarks-2026-08-06 \
  --output research/evidence/atlas-crosswalk-admission-replay-2026-08-06.json

# 13. Blind-review joins (samples are sealed; the independent passes are committed)
uv run python tools/compare_atlas_relatedmatch_blind_review.py \
  --review research/evidence/atlas-relatedmatch-blind-review-2026-08-06 \
  --replay research/evidence/atlas-crosswalk-admission-replay-2026-08-06.json
uv run python tools/compare_atlas_variant_classifier_audit.py \
  --audit research/evidence/atlas-variant-classifier-audit-2026-08-06
```

Steps 10 to 13 need no rank artifacts and reproduce from committed data alone.

Test-set rebuild is byte-identical across independent runs; manifest digest
`sha256:9cc14e101c1303e18a86a4d36389c1e45b5bbff0532e4937b504420618404c01`.
