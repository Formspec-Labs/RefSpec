# Nuggets extracted before archive — 2026-08-27

Source files copied OUT of the git lifecycle, because the branches holding them
are being abandoned and the only other copies are **local-only snapshot refs that
would not survive a re-clone**:

  spicy-regs   refs/snapshots/pre-strip-2026-08-26        -> 57d46bf
  RefSpec/DocSpec/rulespec/spicysearch
               refs/snapshots/pre-disposition-2026-08-27  -> each HEAD

Origin: `~/Work/spicy-regs`, branch `integrate/payload-prereqs` @ c00df53 plus
uncommitted working-tree edits. 26 files, 27,492 lines. Paths under `source/`
mirror their original repo paths exactly.

Each entry below was established by RUNNING both implementations against real
corpora, not by reading docstrings. Where a recreation already wins, that is
stated — those files are here for reference, not for porting back.

## Rank 1 — absent from ALL four surviving repos

| nugget | file | evidence |
|---|---|---|
| Cross-encoder reranking | `docpipeline/retrieval.py` (~:4441), `adapters/sentence_transformers.py` | `BAAI/bge-reranker-v2-m3`, pinned + checkpointed + drift-rejecting. Measured: recall@1 0.2857 -> 0.5143, nDCG@10 0.4566 -> 0.6622 (within-artifact); 0.200 -> 0.371 (corpus). 35 queries, `ir-measures:0.4.3` — indicative, not a benchmark. Receipt in `receipts/`. spicysearch's only `rerank` hit is `validation/evaluation_runner.py`, an eval path. |
| Learned-sparse (SPLADE) | `adapters/sentence_transformers.py`, `corpora/segmentation_sparse_retrieval.py` | `tomaarsen/splade-modernbert-base-miriad` + real `bm25s` (k1=1.5/b=0.75). SPLADE: **0 files** across spicysearch/RefSpec/rulespec/DocSpec. spicysearch's lexical lane uses DuckDB `match_bm25` as a boolean predicate and ranks with a term-count scorer — sealed as `"scoreOutput": "fixed-logical-match-statistics-only"`. |
| FR legacy identifier escape hatch | `ontology/citations.py:443` `federal_register_identifier` | **394,128 of 1,004,233 (39.2%)** real FR `document_number` values are the bare legacy shape (`09-19806`). spicy-regs mints `urn:spicy-regs:frdoc:09-19806`; RefSpec's `detect_identifier_shapes` returns `[]` for every one. Verified directly. |
| 6 of 7 IRI minters | `ontology/citations.py:384-604` | CFR / EO / RIN / FRDOC / partner-defined / regsgov / PL. RefSpec mints only USC (`act_resolution.py:304`). No Python in any repo mints the others; rulespec owns the *grammar* normatively but a grammar is not a minter. |
| OLRC acquisition | `sources/uscode_olrc.py`, `tools/build_usc_act_index_artifact.py`, `tools/build_usc_source_credit_artifact.py` | The only code that fetches/parses OLRC's Popular Name Tool + Table III HTML. RefSpec consumes the frozen 302,156-row artifact and has NO regeneration path — it depends on code being abandoned. |
| Loose docket join key | `ontology/citations.py:562` `normalize_docket_id` | Produces a usable key for 100% of 29,797 real docket strings; RefSpec's strict validator refuses 62% as non-regulations.gov. NOTE: RefSpec wins the head-to-head overall (7,556 joins found vs 96), so port the *concept*, not the function. |

## Rank 2 — mechanisms lost to a better replacement

The recreation is better overall; only these specific mechanisms did not travel.

| mechanism | file | note |
|---|---|---|
| 512-wide cross-document batching | `vectordb/embed.py:134` | spicysearch embeds one record at a time, below its own `batch_size=32`. Real throughput cost at 10^5-10^6 scale. (spicysearch is otherwise better: it pins a model revision, this does not.) |
| Content-hash crash-resume cache | `corpora/segmentation_experiment.py:2634-2740` | spicysearch's builder `rmtree`s output on any exception -> full re-embed on retry. |
| Forensic embedding audit | `corpora/embedding_audit.py` | Caught 45 silent truncations in 9,031 real inputs. spicysearch's windowing prevents the defect structurally but keeps no evidence trail. |
| ir-measures cross-check gate | `docpipeline/retrieval.py:1424-1541` | Dual computation with a hard `RuntimeError` on >1e-12 disagreement. spicysearch's harness has no external-library cross-check. |
| Sampled LLM QA re-check | `transforms/build_concept_assignments.py:450-603` | Independent second-pass validation on 10% of tags. No equivalent in spicysearch's tagging stack. |
| Open-vocabulary concept lifecycle | `ontology/concepts.py:202-224,395-419` | Candidate minting/promotion/deprecation + multi-source quotas. spicysearch is strictly closed-vocabulary, one scheme per build. |
| SKOS one-hop expansion | `enrichment/connected_concepts.py:174-361` | exact/close/broad/narrow/relatedMatch. Compare against spicysearch `related_topics.py` before discarding — not done. |

## Rank 3 — paused, not superseded

Kept because a named trigger is unmet, per spicy-regs `docs/decisions.md`.

- `corpora/relation_exclusion_evaluation.py` + `_v2.py`, `ontology/codex_cli.py`, `ontology/relation_findings.py`
  — waived until "two blind human reviews seal the oracle." Explicitly not queued, not dropped.
- `ontology/ann_index.py`, `tools/benchmark_usearch_index.py` — named revisit triggers (registry
  memory budget, worker RSS pressure, embedding change); "revisiting is cheap."
- `tools/prototype_hyperbolic_subsumption.py` — its own evidence doc has a 4-item next-step list reusing these probes.
- `evaluation_boundary.py` — `BOUNDARY_SCHEMA_VERSION` still matches the current non-superseded track.
- `tools/draw_search_holdout.py` — content-blind stratified draw over 580,738 matters; one-shot by design,
  and `TODO-RULE.md` has an open item requiring a new draw under the same contract.
- `tools/measure_extraction_retention.py` — derives `RETENTION_FLOORS`, pinned in `docpipeline/source.py:1016`.
  The constant is in production; this is the only code that can re-derive it from fresh data.

## Also preserved, elsewhere
- `~/Work/corpora/_preserved-2026-08-27/`        11 GB, spicy-regs `output/`, byte-verified
- `~/Work/corpora/_preserved-2026-08-27/landing-output/`  8.7 GB, 26 files, sha256-verified per file
- `~/Work/corpora/_preserved-2026-08-10/`        earlier rescue (body-retrieval, holdout draw + exam)

## Full archive-surface sweep

The twelve-agent sweep completed. Its raw traces, readable reports, integrity
manifest, complete source snapshots, and finding-by-finding closure ledger are
preserved under
[`sweeps/2026-08-27-archive-surface/`](sweeps/2026-08-27-archive-surface/README.md).

The ledger accounts for 272 distinct findings across catalog predecessor
behavior, source acquisition and publication, document processing, ontology
and evaluation, materialization, workflows, tests, exact datasets, and
historical pins. Complete tracked trees and local Git history are archived;
all 23,135,060,429 bytes of ignored SpicyRegs output and all 9,298,482,522
bytes of landing output are separately copied and manifested under
`_preserved-2026-08-27/`. Current code, accepted decisions, and fresh
verification remain authoritative; preservation does not approve adoption.

## Appendix — 12-agent sweep findings (2026-08-28)

Source: 12 read-only reports (r1–r12) at
`/private/tmp/claude-501/-Users-mikewolfd-Work-spicysearch/346992e7-eac1-4092-8012-86e27637a8bd/scratchpad/codex/reports/r{1..12}.md`,
mirrored (renumbered `01`–`12`) under [`sweeps/2026-08-27-archive-surface/reports/`](sweeps/2026-08-27-archive-surface/README.md),
whose `closure/dispositions.tsv` already proves physical byte-preservation for all 272 raw findings. This
appendix is a different cut: which findings are worth *acting on*, not just preserved. Every row below
was opened at its cited path/line before inclusion. Repo prefixes: `landing`=spicy-regs-landing,
`regs`=spicy-regs, `ds`=DocSpec, `rs`=RefSpec, `rl`=rulespec, `ss`=spicysearch. Items already in Rank 1–3
above are cross-referenced, not repeated.

**Known false claim — do not reimport:** r9 states `output/usc-act-index-2026-08-02/` and
`output/usc-source-credit-index-2026-08-02/` are "already empty." Verified false: both are symlinks
(`spicy-regs/output/... -> RefSpec/output/...`) resolving to real Parquet content (e.g.
`usc-act-sections.parquet` 103,904 bytes, `usc-popular-names.parquet` 563,299 bytes, both with receipts).
This is the third agent in this campaign's history to misread that symlink as empty — don't re-derive it.

### CODE-NUGGET — behavior worth porting

- `landing:src/spicy_regs/source_catalog/universe.py:130` — conjunctive policy-scoped universe filter (location/agency/docket/type/window/budget) with a distinct `policy.publication-date-unusable` reason — verified [r1#1]
- `landing:src/spicy_regs/source_catalog/verify.py:35` — consumer independently re-derives release identity/digests/dispositions rather than trusting the producer's claims — verified [r1#2]
- `landing:src/spicy_regs/source_catalog/mirrulations.py:205` — incomplete draws become `unavailable`/`failed` rows, never silently dropped — verified [r1#3]
- `landing:src/spicy_regs/source_catalog/published_catalog.py:477` — verified-byte-first rendition family ranking (verified Mirrulations bytes > source URL > FR fallback) — verified [r1#4]
- `landing:src/spicy_regs/source_catalog/schema_pins.py:55` — bundle carries its own validation schema bytes for offline verification — verified [r1#8]
- `landing:src/spicy_regs/schemas/federal_register.py:29` (also `regs:src/spicy_regs/schemas/federal_register.py`) — `topics_json` is an additive-migration column, omitted (not null-invented) on pre-backfill tables — verified [r2#2 + r10#8, deduped]
- `landing:src/spicy_regs/source_catalog/published_catalog.py:435` — byte-compatible old/new profile toggle bound into the policy digest — verified [r2#3]
- `regs:src/spicy_regs/docpipeline/relation_task.py:86,1355,1858` — leak-proof relation benchmark: recursive answer-field exclusion from provider payload + `evaluate_run_eligibility`/`score_candidates` binding two blind reviews — verified [r3#1]; same "two sealed blind reviews" trigger as Rank 3's relation-exclusion entry, but this is `docpipeline/`, not the `corpora/` evaluator Rank 3 names
- `regs:src/spicy_regs/docpipeline/segments.py:181,558,614,638` — pinned-tokenizer, structure-first segment packing with bounded overlap (paragraph>line>sentence>whitespace fallback) — verified [r3#2]; **note:** `ontology/segmentation.py:290` (below) is a second, independent implementation of the same idea
- `regs:src/spicy_regs/docpipeline/tag_task.py:58,223,412` — evidence-grounded LLM tagging: forbidden-gold payload construction + unique-exact evidence-offset repair — verified [r3#3]
- `regs:src/spicy_regs/docpipeline/rkaf_projection.py:643` — source-native facts (FR/proceeding/docket/RIN/CFR/authority) assembled into RKAF without prose reparsing — verified [r3#4]
- `regs:src/spicy_regs/docpipeline/document_release_segments.py:453` — sealed-release-to-model-input handoff preserving passage/fragment lineage — verified [r3#5]
- `regs:src/spicy_regs/docpipeline/runtime.py:1674` (`rebuild_run`) — whole-run provider-free forensic rebuild, refuses drift in historical requests/responses — verified [r3#6]; compare `docpipeline/extraction.py` below (same idea, per-unit layer)
- `regs:src/spicy_regs/document_release_v3*.py` (anchor `document_release_v3_verify.py:728`) — entire v3 subsystem (reversible segment↔rendition proof, closed reconciliation universe, first-failure codes, compaction trigger policy, media-type-conflict rejection at `document_release_v3_writer.py:577`) has no DocSpec counterpart; **"Can DocSpec currently read a v3 release at all? No."** — verified [r4, 8 items compressed]
- `regs:src/spicy_regs/sources/uscode_olrc.py:96` — OLRC Popular Names: Statutes-at-Large volume recovered from the `statviewer` query, cite/see/renamed/short-title-ref distinguished, ambiguous names refused — verified [r5#2]; detail beneath Rank 1's "OLRC acquisition" entry
- `regs:src/spicy_regs/sources/uscode_uslm.py:98` — strict USLM source-credit parsing: requires explicit "Added"/"as added" language, bounds Statutes-at-Large lookup at the next citation — verified [r5#3]; detail beneath Rank 1's OLRC entry
- `regs:src/spicy_regs/sources/courtlistener_bulk.py:68` — `escapechar='\\'` fix for CourtListener CSV (default parser desynced 1,987/3,000 rows) — verified [r5#1]; **DISPUTED status, see below**
- `regs:src/spicy_regs/sources/supreme_court_opinions.py:67` — shared bound-volume PDF handling (`#page=N`) + wrong-term rejection when the Court serves the wrong OT year — verified [r5#4]
- `regs:src/spicy_regs/sources/bill_subjects.py:108` — three-way outcome (404 vs. no-subject vs. transport failure); paginated failure voids the whole answer — verified [r5#5]
- `regs:tools/build_agency_crosswalk_artifact.py:10` — agency-crosswalk rules: no docket-prefix inference, decorated-ID normalization only to a unique docket, 0.05-share sub-agency preference — verified [r5#6]
- `regs:src/spicy_regs/ontology/adapters.py:251` + `subjects.py:151` + `segmentation.py:290` — 19-profile structure-preserving extraction feeding token-bounded segments with hierarchy/provenance — verified [r7#2]; second segmentation implementation, see `docpipeline/segments.py` above
- `regs:src/spicy_regs/ontology/llm.py:114` — strict evidence-grounded model execution: closed schema, `store=False`, unique-exact evidence-offset repair — verified [r7#4]
- `regs:src/spicy_regs/ontology/ann_index.py:213` — pinned USearch ANN graph over a 513,236-row dense index, memory-mapped, recall measured against exact cosine — verified [r7#5]; confirmed absent from DocSpec (`grep -r usearch src/docspec` = 0 hits)
- `regs:src/spicy_regs/ontology/candidate_channels.py:255` — independent multi-channel candidate generation (boilerplate exclusion, dense, BM25, vocab-blind keyword) reduces correlated failure modes — verified [r7#6]
- `regs:src/spicy_regs/source_native.py:879,1705,1887` — full source-release publish/admit/replay gate (byte-conservation invariant at `:1821`: reused+written each ≤ read, not `reused+written==read`) — verified [r8#1,#4]; **"Safe to abandon: No"** per r8
- `regs:src/spicy_regs/public_table.py:587` — faithful flat Parquet + DuckDB + Iceberg public-view delivery path, no DocSpec/SpicySearch counterpart — verified [r8#3]
- `regs:src/spicy_regs/pipelines/materialized.py:285` + `published.py:66` — atomic materialized-dataset publish (restore-from-manifest, `latest.json` swapped last) and fail-closed resolver — verified [r10#1]
- `regs:src/spicy_regs/data_dictionary.py:728` — schema-vs-published-Parquet drift detector (curated description vs. expected schema vs. live `DESCRIBE`) — verified [r10#6]
- `regs:src/spicy_regs/sources/source_domains.py:1` — pinned OpenAPI/XSD-vs-observed discrepancy ledger; obsolete accepted exceptions also fail the gate — verified [r10#7]
- `regs:src/spicy_regs/docpipeline/adapters/docling.py:144` — Office (DOCX/PPTX/XLSX) extraction: 5 labeled content layers, table grids w/ span+ambiguity marks, closed refusal vocabulary, sandboxed subprocess gate — verified [r11#1]
- `regs:src/spicy_regs/docpipeline/adapters/{anthropic.py:347,openai.py:258,openai_compatible.py:20,codex_cli.py:10}` — provider-independent structured-LLM safety layer: pre-call schema validity, exact token budget, retry/refusal classification — verified [r11#2]; this `codex_cli.py` is a **different file** from `ontology/codex_cli.py` in Rank 3's paused bucket
- `regs:src/spicy_regs/docpipeline/adapters/sentence_transformers.py` (SPLADE + reranker) — **already Rank 1**, not restated; r11#3 corroborates absence in all four survivors
- `regs:src/spicy_regs/docpipeline/source.py:997` — measured thin-parse retention floors (HTML/XML/PDF, per parser) with named exemptions; refuses unmeasurable parses — verified [r11#4]
- `regs:src/spicy_regs/docpipeline/extraction.py:72,883` — per-unit provider-free replay + answer-leak scanning; rebuild can never upgrade a failed/unknown check to a pass — verified [r11#5]; compare `docpipeline/runtime.py:1674` above (same idea, whole-run layer)

### INVARIANT — rules/tests worth re-asserting in a surviving repo

- `regs:tests/test_source_native_release.py:1004` `test_capped_single_day_refuses_ambiguous_source_state` — a capped single-day FR window must refuse completeness, never claim it — verified [r9#1]
- `regs:tests/test_source_native_release.py:1028` `test_publisher_refuses_missing_or_reordered_date_windows` — publication needs the exact ordered leaf-window inventory — verified [r9#2]
- `regs:tests/test_source_native_release.py:1059` `test_publisher_independently_refuses_a_false_source_count` — publisher recomputes counts, never trusts acquisition's claim — verified [r9#3]
- `regs:tests/test_regulations_gov_source_native.py:279` `test_document_pages_capture_exact_listing_metadata_and_object_bytes_once` — one enumeration binds listing metadata to object bytes; no second, possibly-inconsistent listing — verified [r9#4]
- `regs:tests/test_regulations_gov_source_native.py:412` `test_missing_or_changed_enumerated_object_refuses_complete_snapshot` — every enumerated object must still exist identically at read time — verified [r9#5]
- `regs:tests/test_regulations_gov_comments_source_native.py:291` `test_repeated_normalized_comment_versions_always_refuse_a_tie` — a normalized-timestamp tie between comment versions must be refused, not order-selected — verified [r9#6]
- `regs:tests/test_relation_exclusion_evaluation_v2.py:602,725,416,573` — eligibility needs 2 distinct sealed human reviews; a future-dated review can't authorize an earlier eval; reviewing a span doesn't authorize its enclosing span; a proposed removal stays an event — verified [r9#7–10]; executable detail beneath Rank 3's relation-exclusion prose entry
- `regs:tests/test_body_retrieval_corpus.py:381` `test_a_cloudflare_interstitial_is_quarantined_not_sealed` — an HTTP 200 challenge page must be quarantined, not sealed as content — verified [r9#11]
- `regs:tests/test_body_retrieval_corpus.py:687` `test_incomplete_cache_cannot_narrow_the_v3_reconciliation_universe` — a partial cache can't silently redefine the completeness universe — verified [r9#12]
- `regs:tests/test_body_retrieval_corpus.py:707` `test_xml_capture_without_content_type_keeps_the_xml_fallback` — missing content-type must not erase an already-identified XML rendition — verified [r9#13]
- `regs:tests/test_bill_subjects.py:198,219,365` — a failed later page voids the whole paginated answer; a 404 is a definitive answer distinct from transport failure; negative caching must re-ask when a deeper carrier is tried — verified [r9#15–17]
- `regs:tests/test_supreme_court_opinions.py:280` `test_reader_fetches_a_shared_volume_once_and_records_a_dead_link` — shared-volume opinions reuse one fetch, keep per-opinion dead-link evidence — verified [r9#19]
- `landing:src/spicy_regs/source_catalog/validate.py:214` — `sourceObservedTopics` may never use `urn:ref:`/`urn:refspec:` prefixes; publisher vocabulary can't impersonate RefSpec concepts — verified [r1#5]
- `landing:src/spicy_regs/source_catalog/published_catalog.py:98` (`SOURCE_ITEM_ID_PREFIX = "regulations.gov/"`) + `release.py:101` — source-item identity stays namespaced apart from document identity; no two selected items may claim one document — verified [r1#7]
- `regs:src/spicy_regs/ontology/invariants.py:14` `assert_acyclic` — small, general append-only + acyclicity assertions, worth re-adding as-is — verified [r7#9]
- `regs:src/spicy_regs/ontology/concepts.py:1223` `merge_pass` — automated concept merges only within the same facet and source vocabulary — verified [r7#11]; adjacent to Rank 2's open-vocabulary lifecycle entry
- `regs:src/spicy_regs/document_release_v3_writer.py:577` — identical bytes claiming conflicting media types must be rejected, not silently reused under the new type — verified [r4#8]

### EVIDENCE — receipts/measurements, already preserved

All items below are physically preserved: confirmed present under `~/Work/corpora/_preserved-2026-08-27/spicy-regs-output-complete/` or `.../landing-output/` (checked directly), or in the `source-snapshots/*.tar.gz` (confirmed for the untracked landing universe JSON, which a plain git-tracked export would have missed).

- `regs:docs/evidence/relation-exclusion-*`, `candidate-selector-ablation-*`, `gold-adjudication-*` — raw provider replies/judge votes; a prompt change moved exact F1 0.273→0.700 — [r6#1]; preserved in source-snapshots bundle (tracked docs)
- `regs:docs/evidence/court-data-coverage-2026-08-22.md:238` — CourtListener ID-join misses D.D.C. (1,571 APA dockets, 0 direct matches; ≥249 recovered via docket reconciliation) — verified [r6#2]
- `regs:docs/evidence/court-data-coverage-2026-08-22.md:553` — full docket map: 71,677,647 rows, 4.67 GiB, 111 min, dense unsigned-short court index — verified [r6#3]
- `regs:docs/evidence/court-data-coverage-2026-08-22.md:76` — CourtListener bulk capacity: 1,076 objects/1,598.65 GiB, ~1.77 MiB/s client-throttled regardless of parallelism, 8.6h for the 50.8 GiB opinion dump — verified [r6#5]
- `regs:docs/evidence/court-data-coverage-2026-08-22.md:368` — Supreme Court acquisition negatives: 204/260 reachable OT2017–20 (4 dead volume PDFs), one OT2023-served-for-OT2021 mismatch, blocked after ~80 req/25 min — verified [r6#6]
- `regs:docs/evidence/court-data-coverage-2026-08-22.md:448` — RECAP: no bulk dataset, <2% sampled rows had a PDF, do-not-implement-without-a-token verdict — [r6#7]
- `regs:docs/scale-architecture-report-2026-08-04.md` — Bloom manifest: 240 MiB actual vs. 120 MiB reported (`array('L')` is 8 bytes locally); a false positive permanently suppresses a changed key — [r6#10]
- `regs:docs/scale-architecture-report-2026-08-04.md` — 15 dropped hourly jobs left 12 agencies un-ingested, HHS ~5d stale; Iceberg physical duplicates; double full-tree reread on finalization — [r6#11]
- `regs:output/agency-crosswalk-2026-08-02/receipt.json` — tier histogram `confident:124/probable:29/ambiguous:23/unmapped:140`; 715,080 FR-docket-link rows — verified preserved [r12#3]
- `regs:output/date-event-artifact-2026-08-01/receipt.json` — 845,784 events; ECFS ingest began 2026-06-30; **0 of 21,054** FCC proceedings had a usable window — verified preserved [r12#3]
- `regs:output/citation-bakeoff-2026-08-02/*-receipt.json` — CiteURL 12.0.3 vs. current: 4,227 agree, 38/257 disagree; adjudication cost $0.245 on gemini-3.6-flash; CiteURL imports an undeclared Markdown dependency — verified preserved [r12#3]
- `landing:src/spicy_regs/universes/regulations-gov-published-catalog-2021-2025-metadata-complete.json` — untracked oracle universe (policy version, 4 source-byte pins, `U`/`S` digests); the only copy of `complete-source-records-v1`'s exact config — verified present in `source-snapshots/spicy-regs-landing-main-31a4bfe.tar.gz` [r2#1, r9]
- `landing:output/source-catalog-release-regulations-gov-2021-2025-metadata-complete*` — the 1,993,040-row metadata-complete release (documents `sha256:5b9a502…`, dockets `sha256:b14cd488…`, FR `sha256:e03c2f99…`); 3.95 GB `source-items.json` is the only exact per-item disposition record — verified preserved under `landing-output/` [r12#2, r2#4]
- `regs:output/segmentation-source-cache-v2/`, `output/segmented-real-data-evaluation-v2/` — 47 MB real HTML/XML/PDF cache + 2.7 MB sealed evaluation w/ gold spans — verified preserved [r9 fixtures]
- `regs:fixtures/releases/document-release-v3*`, `tests/fixtures/document-release-v3*-source/` — sealed v3 DocumentRelease bundles, the only fixtures a future v3 reader could conform against — [r9 fixtures]

### OPERATIONAL — schedules, limits, quirks

- `regs:.github/workflows/rollup-bill-subjects.yml` daily `21:15 UTC` (1h after bill ingest), `rollup-court-opinion-clusters.yml` Mon `04:20 UTC`, `rollup-court-opinion-bodies.yml` Mon `05:40 UTC`, `rollup-supreme-court-opinions.yml` weekdays `19:30 UTC`, `materialize-ontology.yml` Mon–Sat + Sun both `02:00 UTC` (Sunday does full convergence) — all verified by direct cron grep [r12#5]
- `regs:.github/workflows/deploy-mcp.yml:57-66` — Vercel can report "ready" while every request 500s; smoke test requires a real MCP `initialize` handshake, 5 attempts, 15s sleep between, and greps for `"serverInfo"` (not just HTTP 200) — verified exactly [r12#5]
- `regs:src/spicy_regs/sources/courtlistener_bulk.py` — `/clusters/` returns 401 without credentials, which is *why* the bulk-CSV path is mandatory, not optional — [r12#6]
- `regs:src/spicy_regs/transforms/build_comment_periods.py:76` — adjacent comment intervals merge only when the next opens ≤1 day after the current one closes — verified [r5#7]
- `regs:tools/build_date_event_artifact.py:18` — 1994–2028 window + 5-year bound is acknowledged policy generalized beyond the dataset it was validated on, not re-derived from fresh data — verified [r5#7, r6#13]

### SUPERSEDED-OK — the report itself says the survivor is equal/better

- r1: 8 landing source_catalog mechanisms (stratified sampling math, sample-before-rendition order, complete-universe accounting, exact docket/FR joins, full source-native metadata retention, explicit dispositions, pinned inputs, atomic publication) reproduced in DocSpec — **contingent**: DocSpec's successor work (~4,330 lines) is itself uncommitted.
- r2: exact joins/complete facts, SQLite dup-key refusal, pinned source-native schemas, decision-0007 metadata meaning, Rulespec closed-distribution enforcement all reproduced/stronger; RefSpec correctly owns no catalog (REF-048).
- r3: `executor.py`, `runtime.py` (except forensic rebuild), `segments.py` (except token packing), `document_release_segments.py` (except model-input handoff), `rkaf_projection.py` (schema portion), `tag_task.py` (serving/storage portion) — replaced by DocSpec/Rulespec/SpicySearch.
- r4: v3 format identity, membership/digest/atomic-visibility, rendition packs, bounded writing, cross-layer uniqueness, compaction equivalence — reproduced or improved, **but DocSpec still cannot read a v3 release at all.**
- r6: court-opinion text-selection measurements, CourtListener listing/capture (tests), 1.47 GB/5.36 GB RSS scale result, extraction-retention findings, ANN/hyperbolic/graph-bakeoff results, holdout blindness rules, and landing's "retain substring search" migration correction all survive in current docs/tests.
- r8: Rulespec's canonical JSON/artifact roots/blob verify/durable publish and DocSpec's content-addressed blob writes are real, reusable primitives — but the source-native *acquisition* publish/replay gate itself has no survivor (**"Safe to abandon: No"**).
- r9: immutable-publication/no-replace/tamper-before-first-row, exact Reg.gov joins, act-ambiguity/Table III/source-credit composition, source-domain quirks, and false-negative-not-shrunk-denominator scoring are all covered by current tests; the stricter sealed-review timing gate (see INVARIANT above) remains uncovered.
- r10: `candidate_release.py`→RefSpec managed_release, `enrichment/connected_concepts.py`→`related_topics.py`, `experiment_artifacts.py`→`relevance_artifacts.py`, `document_file_pipeline.py`→DocSpec execution/extraction/segmentation, `evaluate_tag_quality.py`→`topic_baseline.py`, `evaluation_boundary.py`→RefSpec sealed-gold + SpicySearch holdout gates, `publication.py`→rulespec-artifacts no-replace publisher — recreated, not byte-compatible.
  - **Updates Rank 2's SKOS one-hop entry:** Rank 2 said the comparison against `related_topics.py` was "not done." r10 finds it *is* done — `connected_concepts.py` is "RECREATED under newer policy."
  - `sources/courtlistener_bulk.py`→`ds:tools/courtlistener_bulk_source.py` marked SUPERSEDED — **partially disputed**, see below.
- r12: notebooks (13 `.ipynb`, untouched by either branch); DocSpec owns the catalog/document model (can't replay exact archived membership); Rulespec/RefSpec preserve current behavior, not byte-exact old releases; SpicySearch's search behavior is current but needs copied inputs to replay archived measurements.

### Verification failures / disputes

- **r9, `output/usc-act-index-2026-08-02/` "already empty"** — FALSE. See callout at top of this appendix.
- **r10 vs. r5/r6 on `sources/courtlistener_bulk.py`** — r10 marks the whole module SUPERSEDED by `ds:tools/courtlistener_bulk_source.py`. Checked directly: `grep -r escapechar DocSpec/tools/courtlistener_bulk_source.py DocSpec/tests/` returns **zero hits**. The general listing/download machinery is superseded; the specific `escapechar='\\'` parsing fix (r5#1/r6#4, prevents 1,987/3,000 row desync) is **not** ported. Treat the CSV-parsing nugget as still at risk even though the module-level verdict says superseded.
- No other citations checked (see method note above) failed verification; all resolved to the claimed file and matched the claimed content.

### Amendment 2026-08-28 (post-verification)

The disputed `escapechar` item is reclassified. Verified: DocSpec contains NO
CSV row-reading at all (zero `csv.reader`/`DictReader`/`import csv` hits in
src, tools, tests) — `tools/courtlistener_bulk_source.py` ports only the S3
LISTING half of the predecessor. `CourtListenerBulkReader.iter_records`, the
reading half where `CSV_DIALECT = {"escapechar": "\\"}` lives
(`spicy-regs src/spicy_regs/sources/courtlistener_bulk.py:81,409,463`), was
never ported anywhere. r10's "superseded" verdict is therefore falsified
twice for this module: once on behavior (the dialect), once on scope (the
reader). The capability travels with the source-native/acquisition producer
(path-forward memo item 6), not as a DocSpec fix — DocSpec's own
`spicyregs_source_native.py` adapter consumes records by delegating to the
installed SpicyRegs reader, i.e. it declined raw-dump reading by design.
A fix agent was dispatched to patch DocSpec and correctly REFUSED on these
grounds rather than shipping a new subsystem disguised as a one-line fix.
