# Raw trace: SpicySearch experiments, validation, and harness

Provenance: Sonnet subagent trace, 2026-08-10 (late). HEAD measured: SpicySearch `88ada94` (branch `main`).
Status: **verbatim tracer output, preserved unedited**. Subagent-produced — per workspace rule,
re-derive before relying on any figure not independently verified; the figures `../RESEARCH.md`
cites from this trace were spot-verified at compile time (21/9 package counts, scoped-fusion 0.8096,
`"beaten": true`). OBSERVED / INFERRED / ASSERTED markers are the tracer's own.

---

**HEAD measured against: `88ada94`** (full: `88ada94b712f328043c420b76b2f9467fa3ba296`, branch `main`) — OBSERVED via `git -C /Users/mikewolfd/Work/spicysearch rev-parse --short HEAD`.

## Count-reconciliation (read first)

**Claim:** prior census (captured at `df7acd5`) — "experiments/ 21 · validation/ 9 · ~584 MB, 515 MB of receipts."
**Today:** `evaluation/experiments/` has 9 directories; `evaluation/validation/` does not exist.

**Verdict: the prior census conflated two different things under the same leaf names — the file counts describe the *source-code packages*, the byte sizes describe the *data directories*. Nothing was deleted.**

Evidence:

1. **`evaluation/experiments/` has held exactly 9 directories the entire time.** `git ls-tree -r --name-only df7acd5 -- evaluation/` (OBSERVED) shows the same 9 dated experiment directories that exist at HEAD today, byte-for-byte the same names. `git log --oneline df7acd5..HEAD -- evaluation/experiments/` returns **zero commits** (OBSERVED) — the directory has not been touched since the census commit. There is no deletion to explain.
2. **`evaluation/validation/` never existed.** `git log --all --oneline -- 'evaluation/validation*'` returns nothing, at any point in history (OBSERVED).
3. **21 and 9 are exact file counts of the source-code packages, not data directories.** Commit `c3a2091` ("refactor: split package into search, validation, experiments") created `src/spicysearch/experiments/` and `src/spicysearch/validation/` as Python packages. `find src/spicysearch/experiments -type f` excluding `__pycache__` = **21 `.py` files** (OBSERVED, exact match). `find src/spicysearch/validation -type f` excluding `__pycache__` = **9 `.py` files** (OBSERVED, exact match). The "quick ls of evaluation/experiments/" in the prior census almost certainly actually counted (or was told about) `src/spicysearch/experiments/*.py`, and the "validation/ 9" the sibling `src/spicysearch/validation/*.py` — both trees are literally named `experiments/` and `validation/` at the leaf, which is the natural place for the counts to have gotten crossed with the `evaluation/` data trees.
4. **515 MB / ~584 MB are real, current byte counts of `evaluation/`, not a stale figure.** `ls -la evaluation/holdout-labeling/receipts/` (light, non-recursive; OBSERVED): `gemini-receipts.jsonl` = 359,983,832 bytes + `openai-receipts.jsonl` = 180,367,339 bytes = 540,351,171 bytes = **515.32 MiB**, matching "515 MB of receipts" almost exactly. Summing every file directly listed (light `ls`/`os.path.getsize`, no `du`, no hashing) across `evaluation/holdout-labeling/*`, `evaluation/experiments/*`, and `evaluation/core-query-catalog/*` totals **≈584.0 MiB** (receipts 515.32 + judging-inputs 12.66 + labels 20.17 + opus-inputs 12.4 + opus-inputs/shards+shards-out 12.55 + pooling 4.74 + gold 0.51 + seal 0.49 + verdict 3.7 + core-query-catalog quality-v1 0.74 + core-query-catalog v1/misc ≈0.16 + evaluation/experiments 0.58 ≈ 584 MiB), matching "~584 MB" almost exactly. This is INFERRED as a total (built from per-directory light listings, not a single recursive measurement — no `du` was run per instructions) but every component figure is OBSERVED.

**Reconciled scope:** what the census meant by "experiments/" and "validation/" (counts) is `src/spicysearch/experiments/` and `src/spicysearch/validation/` (code, 21 / 9 files). What it meant by the byte sizes is `evaluation/` (data, ~584 MB total / 515 MB in `evaluation/holdout-labeling/receipts/`). The actual data-artifact directories today are: `evaluation/experiments/` (9 dev-experiment dirs, unchanged since `df7acd5`) and `evaluation/holdout-labeling/` (the validation/adoption-gate campaign — coincidentally also **9 subdirectories**: `exam, gold, judging-inputs, labels, opus-inputs, pooling, receipts, seal, verdict`, which may be a second, independent source of the "validation/ 9" figure). No files were moved or deleted; the "quick ls of evaluation/experiments/" in the task premise is correct and always was 9.

---

## evaluation/experiments/2026-08-01-dense-dev-bge-v1

**path** · `evaluation/experiments/2026-08-01-dense-dev-bge-v1/` · **date** 2026-08-01 · **QUESTION**: does a real dense-embedding arm (bge-base-en-v1.5) beat, or help, the shipped lexical spine on the 114 engine-scored quality variants — measured alone and under global weighted-RRF fusion?

**ARMS**: `engine` (shipped lexical spine) · `dense_dev_alone` (dense-dev-retrieval-v1, bge-base-en-v1.5@a5beb1e, 240-token zero-overlap windows) · `dense_lexical_weighted_rrf` (global fusion, lexical 0.7 / dense 0.3, RRF k=60)

**HEADLINE NUMBERS** (verbatim from `metrics.json.results.arms`, OBSERVED):

| arm | nDCG@10 | g3-recall@20 | P@5 | passed/scored |
|---|---|---|---|---|
| engine (spine) | 0.7644 | 0.8061 | 0.8107 | 61/114 |
| dense_dev_alone | 0.5002 | 0.6512 | 0.3553 | 9/114 |
| dense_lexical_weighted_rrf | 0.8592 | 0.9646 | 0.7061 | 47/114 |

**VERDICT**: Continue. Dense-alone is far below the spine overall but every still-failing semantic family moves on ranked metrics (find_same_matter, find_supporting_passages, search_by_workflow_function, search_by_subject, find_possible_governing_context). Global weighted fusion lifts mean nDCG@10 and g3-recall but total pass count *drops* 61→47 — reproduces the "fusion trap" (global fusion drags a strong arm's candidates even at unequal weights). Scopes the next experiment to scoped (not global) fusion.

**ATLAS**: not used. No vocabulary/concept atlas touched — pure dense retrieval + lexical fusion; `gate_receipt.coverage_semantic_channel = "not_used"`.

**CITED-BY-MAP**: CITED — this is the source of the already-known dense-arm figures 0.5002 / 0.7644 / 0.8592.

---

## evaluation/experiments/2026-08-01-dense-dev-scoped-fusion-bge-v1

**path** · `evaluation/experiments/2026-08-01-dense-dev-scoped-fusion-bge-v1/` · **date** 2026-08-01 · **QUESTION**: does routing dense fusion only onto unanchored-ranked variants (never identifier/connection-anchored answers) beat both the spine and global fusion simultaneously?

**ARMS**: `engine` (spine) · `dense_dev_alone` · `dense_lexical_weighted_rrf` (global fusion, repeated as comparator) · `dense_lexical_scoped_rrf` (scoped-fusion-unanchored-ranked-v1 routing rule)

**HEADLINE NUMBERS** (verbatim, OBSERVED):

| arm | nDCG@10 | g3-recall@20 | P@5 | passed/scored |
|---|---|---|---|---|
| engine (spine) | 0.7644 | 0.8061 | 0.8107 | 61/114 |
| dense_dev_alone | **0.4823** (jitter vs. prior 0.5002, see below) | 0.6512 | 0.3553 | 9/114 |
| dense_lexical_weighted_rrf (global) | 0.8592 | 0.9646 | 0.7061 | 47/114 |
| **dense_lexical_scoped_rrf (scoped)** | **0.8096** | **0.8997** | **0.8120** | **62/114** |

**VERDICT**: Continue — scoped fusion is "the first arm of this campaign" to beat the spine on all three headline metrics simultaneously, keeping all 61 spine passes and converting one more. Routing fused exactly 30/114 variants (four unanchored-ranked families), left 84 byte-identical to the spine. Decision note flags a reproducibility caveat: the `dense_dev_alone` comparator read 0.4823 here vs. 0.5002 on the prior run with byte-identical input digests and the same model pin — attributed to numeric-environment jitter in near-tie cosine orderings, not a code change (verified byte-identical against the prior commit on a deterministic stub). This became the **frozen candidate configuration** for the sealed search holdout (see `config-freeze.json`).

**ATLAS**: not used (`atlas / date-event enrichment: not_used` per `config-freeze.md`).

**CITED-BY-MAP**: PARTIALLY CITED — reproduces the already-cited 0.7644/0.8592 comparator numbers, but its own headline contribution (scoped fusion 0.8096 / 62/114) is UNREAD-UNTIL-NOW.

---

## evaluation/experiments/2026-08-02-agency-priors-v1

**path** · `evaluation/experiments/2026-08-02-agency-priors-v1/` · **date** 2026-08-02 · **QUESTION**: does a CFR-part→agency prior (weight 0.05) help or harm ranking, and is the 114-variant benchmark even capable of measuring it?

**ARMS**: `spine` (no prior) vs `agency_prior` (0.05-weight CFR→agency boost), measured on a bespoke 8-document constructed corpus (the 114-variant benchmark was found unable to measure this at all: 0 of 82 records yield an agency key).

**HEADLINE NUMBERS** (verbatim, OBSERVED — this experiment does **not** use nDCG@10; primary metric is mean reciprocal rank of the target):
- `mean_reciprocal_rank_of_target`: spine **0.292177** → agency_prior **0.734694**
- `prior_helps`: 4/4 targets promoted, hits@1 0→4
- `prior_adversarial`: 1 target promoted but ranks the *wrong* agency (defense-dept over NASA) at rank 1
- `prior_must_not_override_strong_text`: 1/1 targets demoted, hits@1 1→0
- Largest spine accumulation gap overturned: 0.007164 vs. pinned budget 0.050000 (~7x)

**VERDICT**: Investigate (negative finding). The 114-variant benchmark cannot measure this feature at all (by construction, delta would be identically zero). On the constructed corpus, deep algebraic analysis shows the lexical channel's `normalized_channel_score` is a pure RRF rank transform, so within-channel signal encodes rank, never margin — any absolute-addend prior safe enough not to displace a top match is bounded at w < 0.0012887, at which point it cannot move the positive case at all. No constant is both safe and useful; retuning cannot reach a useful regime. Report includes an explicit correction of an earlier draft's false claim.

**ATLAS**: not used / not applicable — no vocabulary atlas involved.

**CITED-BY-MAP**: UNREAD-UNTIL-NOW.

---

## evaluation/experiments/2026-08-02-body-length-penalty-v1

**path** · `evaluation/experiments/2026-08-02-body-length-penalty-v1/` · **date** 2026-08-02 · **QUESTION**: does admitting full document bodies (vs. metadata-only) hurt ranking via BM25 length normalization + trigram-cosine dilution, and does chunking recover it? (First pass, small corpus.)

**ARMS**: `whole_body_one_chunk` (baseline, today's arm) · `metadata_only` · `passage_chunks` · `fixed_window_640` · `fixed_window_2048`

**HEADLINE NUMBERS** (verbatim — primary metric is P@1 / MRR, not nDCG@10; OBSERVED):

| arm | P@1 | MRR | queries answerable |
|---|---|---|---|
| whole_body_one_chunk (baseline) | 0.4375 | 0.5245 | 16/16 |
| metadata_only | 0.4375 | 0.5516 (0.7917 where answerable) | 8/16 |
| passage_chunks | 0.9375 | 0.9688 | 16/16 |
| fixed_window_640 | 0.9375 | 0.9688 | 16/16 |
| fixed_window_2048 | 0.75 | 0.7953 | 16/16 |

**VERDICT**: Investigate. Admitting bodies made ranking *worse* for the documents whose bodies were admitted (P@1 0.00/MRR 0.118 on title-answerable queries with bodies present, vs. 0.75/0.875 with bodies withheld) — "admitting the answer did not win the query." Withholding bodies is not the fix either (can't answer body-only queries at all). Chunking wins both: passage-aligned chunks and 640-char windows recover full retrievability and ranking without losing a single query. Root-caused to two independent length mechanisms: BM25 length normalization (measured: 5 of 10 longer-than-average targets move, 39 rank positions) and trigram-cosine self-normalization (only a shorter unit repays it — term frequency cannot). Corpus is 16/17 constructed, 1 real v2 distribution.

**ATLAS**: not used / not applicable.

**CITED-BY-MAP**: UNREAD-UNTIL-NOW.

---

## evaluation/experiments/2026-08-02-passage-chunking-native-v1

**path** · `evaluation/experiments/2026-08-02-passage-chunking-native-v1/` · **date** 2026-08-02 · **QUESTION**: re-measurement of body-length-penalty-v1 on the real engine (not a runner simulation) and at corpus scale (17→200 documents), leading with **recall** rather than ordering.

**ARMS**: same five as body-length-penalty-v1, plus a corpus-scale sweep at depths 10/20/50/100 documents (padded to 17/50/100/200 total).

**HEADLINE NUMBERS** (verbatim, OBSERVED):

| arm | P@1 | MRR | recall@10 (200-doc corpus) |
|---|---|---|---|
| whole_body_one_chunk (baseline) | 0.4375 | 0.5175 | 43.8% |
| passage_chunks | 0.875 | 0.938 | 81.2% |
| fixed_window_640 | 0.9375 | 0.9688 | — |
| fixed_window_2048 | 0.75 | 0.7953 | — |
| metadata_only | 0.5 (0.75 where answerable) | 0.5773 | — |

At 200 documents, baseline's absolute rank grows to 101.0 (proportional depth ~flat at 0.505) while passage_chunks stays at proportional depth 0.031 (nearly flat absolute rank). On-topic document case: baseline ranks it 7th (BM25 rank 1, trigram rank 14) despite term frequency 37; passage_chunks ranks it 1st.

**VERDICT**: Investigate, stronger version of body-length-penalty-v1's finding — "half the queries whose answer the index physically holds do not get it back at all" at realistic scale; this is a **recall** failure that only looks like an ordering failure on a small corpus. The chunked arm is now run through the real engine/production projection (`passage-aligned-chunk-v1`, `best_scoring_chunk_per_document`), not a runner simulation — "the passage arm is now the product, not a simulation of it." Nothing here turns the passage cut on in a published snapshot.

**ATLAS**: not used / not applicable.

**CITED-BY-MAP**: UNREAD-UNTIL-NOW.

---

## evaluation/experiments/2026-08-02-query-front-door-product-path-v1

**path** · `evaluation/experiments/2026-08-02-query-front-door-product-path-v1/` · **date** 2026-08-02 · **QUESTION**: what does the engine score when a request is built the way the actual product front door builds it (not the way the benchmark harness builds it), and where does the gap come from?

**ARMS**: `harness` (published spine, `search_request_for_variant` byte-for-byte) · `+exact_phrase` · `+concept_candidate` · `−connections` · `harness_planner_identifiers` · `front_door_channels` · **`front_door`** (the actual product path) — each also measured on the `resolver` lane; plus a real-corpus (520 real Federal Register docs) query-cost measurement.

**HEADLINE NUMBERS** (verbatim, OBSERVED, `off`/harness lane):

| arm | passed/114 | R@10 | P@5 | nDCG@10 | g3r@20 |
|---|---|---|---|---|---|
| harness (published spine) | 61 | 0.6918 | 0.8107 | 0.7644 | 0.8061 |
| +exact_phrase | 61 | 0.6918 | 0.8107 | 0.7644 | 0.8061 |
| +concept_candidate | 61 | 0.6918 | 0.8107 | 0.7644 | 0.8061 |
| −connections | 46 | 0.5176 | 0.6001 | 0.5691 | 0.5956 |
| planner identifiers | 52 | 0.6918 | 0.7768 | 0.7607 | 0.8061 |
| front_door_channels | 40 | 0.5176 | 0.5715 | 0.5666 | 0.5956 |
| **front_door (product path)** | **9** | **0.3240** | **0.3618** | **0.3589** | **0.4147** |

Real-corpus latency: p50 was 193,224 ms per query pre-fix (16.05M `json.loads` + 16.05M `sha256_digest` calls per query — tokenizing the whole release on every query); the fix (drop non-query tokens before passage work, parse each selector once) brought it to 11,465 ms — a 16.9x improvement, same documents returned. Synthetic benchmark reports p50=25ms — "not a ranking difference, it is a different universe."

**VERDICT**: Investigate — the headline correction of the whole campaign. "Every accuracy figure this campaign has quoted describes a request no product caller can construct." 54/114 variants need a UI affordance (seed anchors, exports, coverage panels), not a text box — 39 of the harness's 61 passes come from exactly those 54. On the 60 text-expressible variants, harness scores 22/60 vs. front_door's 6/60 (recall@10 0.5798→0.4960) — the real, smaller gap. Per-channel attribution: `exact_phrase` moves nothing (0/114); `concept_candidate` moves 2/114 and only fires when an atlas exists (none on the published spine, none in production); `connections` costs −15 passes/−17.4pt recall@10 but none of those 33 variants were text-box-reachable anyway; identifier detection has real gaps (form numbers, docket "No." forms, split-Boolean citations). Recommends quoting harness ("benchmark request shape") and front_door ("product path") numbers always paired, never harness alone. Also states the published 61/114, 63/114, 62/114 figures "need a correction note," not withdrawal.

**ATLAS**: on the `resolver` lane only, the SYNTHESISED benchmark-fixture atlas (`build_quality_vocabulary_atlas`) — same fixture as within-vocab-expansion-v1, not a real one. On the published spine and in production, `concept_assignment_candidate` is `not_used`/absent entirely — "in production this channel cannot fire at all."

**CITED-BY-MAP**: CITED — source of the already-known front_door figure 0.3589 / 9/114.

---

## evaluation/experiments/2026-08-02-semantic-serving-v1

**path** · `evaluation/experiments/2026-08-02-semantic-serving-v1/` · **date** 2026-08-02 · **QUESTION**: does the production serving path (build gate → sealed index → intent routing → fusion → receipts) reproduce, byte-for-byte in metrics, the frozen scoped-fusion candidate the sealed holdout judged? (Acceptance evidence for decision 0004, not a development experiment.) *No `metrics.json`/`candidates.parquet`/`experiment.json` — only `decision.md` and `report.json`.*

**ARMS**: `engine spine (published surface)` vs `semantic serving (this run, verdict-gated real snapshot build)` vs `frozen scoped-fusion arm (what the holdout judged)` as reference.

**HEADLINE NUMBERS** (verbatim, OBSERVED):

| arm | passed/114 | P@5 | nDCG@10 | g3-recall@20 |
|---|---|---|---|---|
| engine spine | 61 | 0.8107 | 0.7644 | 0.8061 |
| semantic serving (this run) | 62 | 0.8120 | 0.8096 | 0.8997 |
| frozen scoped-fusion arm (holdout target) | 62 | 0.8120 | 0.8096 | 0.8997 |

Deltas: **0.0000 on every headline metric, 0 on pass count**. Routing surface: 30/114 fused (four unanchored-ranked families), 84/114 spine-routed with zero item-stream mismatches.

**VERDICT**: exact reproduction confirmed. The production serving path serves exactly the configuration the sealed holdout judged and the adoption verdict authorized — "not a reimplementation drift of it." Explicitly does not re-open the holdout (sealed labels not read). Explicitly rides the fixture-permissive benchmark corpus, not production admission breadth ("task 7's territory" — separate work).

**ATLAS**: not used (`semantic_policy_version="scoped-fusion-serving-v1"` is dense-only fusion; no vocabulary/concept atlas in this arm).

**CITED-BY-MAP**: UNREAD-UNTIL-NOW (though it numerically duplicates the scoped-fusion arm's 0.8096/62 result under a different name — reproduction evidence, not a new number).

---

## evaluation/experiments/2026-08-02-v2-bodies-v1

**path** · `evaluation/experiments/2026-08-02-v2-bodies-v1/` · **date** 2026-08-02 · **QUESTION**: does indexing full v2 document bodies (vs. metadata only) make body-only-answerable queries retrievable through the actual product path? (Precursor to body-length-penalty-v1/passage-chunking-native-v1 — retrievability only, no ranking claim.)

**ARMS**: `with_bodies` vs `metadata_only`, 3-document constructed corpus; plus a "real_published_distribution_scale" reference point (1 real document, 30,484 body characters / 4 structural passages vs. 2,850 metadata characters).

**HEADLINE NUMBERS** (verbatim — this experiment uses raw retrieval counts, not nDCG@10; OBSERVED):
- `with_bodies`: 6/6 body-only-answerable queries retrieved
- `metadata_only`: 1/6 body-only-answerable queries retrieved (and that 1 hit is flagged as noise — it returned the *entire* 3-doc corpus, matching no query term)
- Both arms: 1/1 control (title-answerable) retrieved

**VERDICT**: Continue, but explicitly bounded — "a constructed body-only query is the easiest possible case for the with-bodies arm and an impossible one for the metadata-only arm... bounds nothing about real-corpus retrieval quality, ranking, or precision." Shows body text reaches the lexical index and is retrievable through the product path. Recommends drawing a v2 corpus from real captured documents next, scored by the benchmark's own families.

**ATLAS**: not used / not applicable.

**CITED-BY-MAP**: UNREAD-UNTIL-NOW.

---

## evaluation/experiments/2026-08-02-within-vocab-expansion-v1

**path** · `evaluation/experiments/2026-08-02-within-vocab-expansion-v1/` · **date** 2026-08-02 · **QUESTION**: does concept resolution (`atlas-normalized-label-v1`) and within-vocabulary related-term expansion (`within-vocabulary-related-v1`) help ranking on the 114-variant benchmark — and specifically, is the expansion's related-edge input good enough to trust?

**ARMS**: `off` (no vocabulary pinned) · `resolver` (concept resolution, no expansion) · `resolver_expansion` (resolution + co-assignment-derived related-term expansion)

**HEADLINE NUMBERS** (verbatim, OBSERVED — note this record carries a same-day adversarial-review correction; numbers below are the corrected, re-derived ones):

| arm | passed/114 | P@5 | nDCG@10 | g3r@20 |
|---|---|---|---|---|
| off | 61 | 0.8107 | 0.7644 | 0.8061 |
| resolver | 63 | 0.8212 | 0.7815 | 0.8325 |
| resolver_expansion | 63 | 0.8212 | 0.7804 (**−0.0011 vs resolver**) | 0.8325 |

Resolver's +2 passes come entirely from `search_by_subject` (0/9→2/9); grade-3 recall@20 reaches 1.000 on 9/9 concept-intent variants (corrected from an original, understated "6/9"). Expansion's sole ordering effect: one variant's nDCG@10 falls 0.7864→0.6668 (−0.1196) when two expansion-matched documents displace two others out of the top-10 window.

**VERDICT**: Investigate — not adopt, not abandon. Resolver alone is the measured win and needs no expansion for it. Expansion earns "no gain, one regression" on this corpus. Critically self-corrected (7 numbered corrections, C1–C7) via adversarial review: the true mechanism is evidence-tier promotion (5→4), not signal accumulation as originally claimed; an expansion match *can* outrank a directly-resolved anchor match *between* documents (only *within* one document does the anchor control); Boolean negation cannot suppress a concept match (a genuine regression fired). Recommends the next experiment re-run the same three arms against the real, stated Federal Register thesaurus (1,451 stated related edges) rather than the derived co-assignment edges used here.

**ATLAS**: **SYNTHESISED co-assignment atlas**, explicitly disclaimed by both the code and this record. `resolver_expansion.vocabulary_atlas.related_edge_rule` = `"derived: two concepts are related when the corpus assigns both to at least one document record; the corpus states no relatedness of its own"` (12 derived edges over 8 concepts, `vocabulary_scope: "benchmarkFixtureVocabulary"`). The decision itself states: "This measurement therefore says what within-vocabulary expansion does over co-assignment-derived edges on an 82-document synthetic corpus. It does not say what it would do over the real thesaurus, and it must not be quoted as if it did." Matches the disclaimer at `search_quality_benchmark.py:543-547`.

**CITED-BY-MAP**: CITED — this is "within-vocab-expansion," but note the already-cited framing should carry the co-assignment/synthetic caveat forward, since the record itself repeatedly warns against quoting it as if it measured the real thesaurus.

---

## VALIDATION: evaluation/holdout-labeling/ — sealed search holdout adoption gate

**path** · `evaluation/holdout-labeling/` (9 subdirectories: `exam, gold, judging-inputs, labels, opus-inputs, pooling, receipts, seal, verdict`) · **date** 2026-08-01→2026-08-02 · **QUESTION**: does the frozen scoped-fusion candidate (from `2026-08-01-dense-dev-scoped-fusion-bge-v1`) beat the shipped spine on independently LLM-judged real-holdout relevance labels, under a pre-registered, one-shot, sealed protocol?

**ARMS**: `spine` vs `scoped fusion` (candidate, `scoped-fusion-unanchored-ranked-v1`) vs `dense-alone` (context only, not a candidate — pool-biased in its favor), on 657 drawn holdout queries, judged by two independent LLM judge families (OpenAI, Gemini) plus a partial third ("fable") family, 15-deep pools.

**HEADLINE NUMBERS** (verbatim from `verdict/adoption-verdict.md` / `adoption-verdict.json`, OBSERVED):

| headline metric | spine | scoped fusion (candidate) | result |
|---|---|---|---|
| P@5 | 0.4782 | 0.5050 | strict win |
| nDCG@10 | 0.6980 | 0.7864 | strict win |
| g3-recall@20 (15-deep pools) | 0.8438 | 0.8438 | tie |

Dense-alone (context): P@5 0.5315 / nDCG 0.9088 / g3r 0.9557 (pool-biased caveat noted). Realized coverage of 11,768 labeled pairs: three-family 646 · two-family 10,577 · two-family-adjudicated 517 · single-family (flagged) 28. Sensitivity check on the 646 three-family-covered pairs: verdict agrees with vs. without the third judge family (moves no headline metric >0.007). Spend: $175.10 total (gemini $46.01, openai $129.09) against $46/$140 caps.

**VERDICT**: **BEATEN: TRUE** (terminal, sealed, one-shot). Meets pre-registered criteria: ≥ on all three headline metrics with strict wins on two. This is the adoption-gate evidence that `2026-08-02-semantic-serving-v1` reproduces in production serving.

**ATLAS**: not used (`atlas / date-event enrichment: not_used`, pinned in `config-freeze.json`, identical to the frozen candidate experiment).

**CITED-BY-MAP**: UNREAD-UNTIL-NOW as a validation artifact in its own right, though its candidate configuration is the same one behind the already-cited dense/scoped-fusion numbers.

---

## Harness

**`src/spicysearch/validation/search_quality_benchmark.py`** (1,843 lines) — the executable quality-v1 benchmark runner against the real lexical `SearchEngine`. Reads corpus/judgment JSONL directly, builds a sealed document release and optional concept-lane atlas/extrapolation, indexes a lexical snapshot, runs every thesaurus variant, scores returned ids against qrels. Entry points: `run_quality_search_benchmark`, `run_concept_lane_measurement` (line 1684), `write_report`, `concise_summary`. Contains `build_quality_vocabulary_atlas` (lines 534–547), whose docstring is the disclaimer the task cites verbatim: *"The atlas is a benchmark artifact: its concepts, labels, and (when asked) its related-term edges all come from files the corpus publishes... It is not, and cannot stand in for, a RefSpec-generated managed-vocabulary atlas."* Pinned by `tests/validation/test_search_quality_benchmark.py` and `tests/validation/test_benchmark_concept_lane.py`.

**Query-quality dataset** — `src/spicysearch/validation/query_quality_dataset.py` (2,309 lines) loads/scores it; data lives at `evaluation/core-query-catalog/quality-v1/`. Counts VERIFIED from `manifest.json.counts` (OBSERVED, exact): **queries 78, query_variants 114, qrels 867** (objective_qrels 682 + subjective_qrels 185), 13 catalog jobs, 38 query families, 143 filter interactions, 429 positive + 429 negative + 351 missing-value filter trials. `queries.jsonl` line count independently confirms 78 (OBSERVED). Pinned by `tests/validation/test_query_quality_dataset.py`.

**core query catalog (37 capability cases)** — `src/spicysearch/validation/core_query_catalog.py` (1,947 lines); data at `evaluation/core-query-catalog/v1/cases.jsonl`. Count VERIFIED: `wc -l cases.jsonl` = 37, and `manifest.json.cases.count` = 37 (OBSERVED, exact match). This is the sibling, smaller "runtime and release-conformance smoke test" — explicitly *not* used as evidence the full query catalog works (its own README says so) and marked `accuracy_verdict_eligible: false` in its manifest. It proves each of 13 query jobs applies each of 11 filters through its own execution path, verified against real fixture releases including a **real** Federal Register thesaurus atlas (`fixtures/releases/vocabulary-atlas/federal-register-thesaurus-2025/atlas.nq`, 1.47 MB) — unlike the quality-v1 benchmark, this conformance tier's atlas pin is a real one, not synthesized. Pinned by `tests/validation/test_core_query_catalog.py`.

**657 holdout queries** — `evaluation/holdout-labeling/gold/queries.jsonl`, line count VERIFIED = 657 (OBSERVED, exact). Referenced explicitly in `src/spicysearch/experiments/cli_holdout.py:335,354` and `holdout_labeling.py:725` as "657-query coverage authorized for both families" under a $140 OpenAI / correspondingly-capped Gemini budget. Pinned by the sealed draw (`draw-receipt.json`, `sealed-manifest.json`), `config-freeze.json`/`.md` (the frozen candidate config), and the one-shot rule in `verdict/adoption-verdict.md` ("the computing tool refuses to run twice"). Tested via `tests/experiments/test_holdout_labeling.py`.

**Front door / concept lane / semantic-serving harness code** — `src/spicysearch/experiments/front_door_benchmark.py` (measures the product front door vs. the internal benchmark request shape; used by `2026-08-02-query-front-door-product-path-v1`) and `src/spicysearch/experiments/semantic_serving_benchmark.py` (used by `2026-08-02-semantic-serving-v1`), both under `src/spicysearch/experiments/` (21 files total, the source of the "21" miscounted in the reconciliation above). Pinned by `tests/experiments/test_front_door_benchmark.py` and `tests/experiments/test_semantic_serving_benchmark.py`.

---

### Notes on method
- No file was edited, created, or deleted; no `git checkout`/state-changing command was run.
- Size figures came from light `ls -la` / `os.path.getsize` listings of individual files and immediate directory contents only — no `du`, no recursive hashing, no test/build/engine execution.
- All headline numbers above are transcribed verbatim from `metrics.json`/`report.json`/`decision.md`/manifest files (OBSERVED); narrative interpretation (VERDICT prose, mechanism explanations) is the experiment authors' own text, reproduced rather than reinterpreted, and is marked OBSERVED where quoted, INFERRED only for the ~584 MB total (a sum of per-directory light listings, not a single measurement).
