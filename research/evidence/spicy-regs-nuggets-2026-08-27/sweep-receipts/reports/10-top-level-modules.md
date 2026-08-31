Reviewed all 79 in-scope modules across both discarded worktrees. I treated schemas and research reports as evidence, not behavioral equivalents. `NONE` means no executable counterpart was found in DocSpec, RefSpec, rulespec, or spicysearch.

| module | what it does | surviving counterpart or NONE | on origin/main? | verdict |
|---|---|---|---|---|
| `candidate_release.py` | Reads verified Atlas releases and emits candidate-selection receipts and bridges. | RefSpec `managed_release.py`, `atlas_index.py`, candidate retrieval | No; no old command | RECREATED; local adapter format not preserved |
| `cli.py` | Adds `document_release_v3`; changes `main()` to accept arguments and return exit codes. | Document-release work excluded; no equivalent CLI change | Yes; `spicy-regs` | LOW RISK; only testability/surface change |
| `corpora/__init__.py` | Package marker. | NONE needed | No | No independent behavior |
| `corpora/artifact_retrieval_baseline.py` | Whole-artifact baseline for comparing artifact and segment retrieval. | NONE | No; new command | AT RISK |
| `corpora/body_retrieval_corpus.py` | Deterministic Federal Register body corpus, fetch cache, draw rules, secret scan, validation and measurements. | NONE; spicysearch retains reports, not the builder | No; new command | AT RISK |
| `corpora/document_acceptance_scope.py` | Builds an immutable, profile-filtered document view over a segmentation dataset. | RefSpec sealed-gold boundaries, partially | No; new command | PARTIAL; executable scope builder at risk |
| `corpora/embedding_audit.py` | Records model-native tokenization, limits and input digests for embedding experiments. | NONE exact | No; new command | AT RISK |
| `corpora/mirrulations_document_corpus.py` | Freezes exact Regulations.gov documents and attachments from Mirrulations with receipts. | DocSpec Regulations.gov catalog, partially | No; new command | PARTIAL; exact corpus-freezing method at risk |
| `corpora/mixed_real_data.py` | Builds heterogeneous positive, negative and cross-source ontology cases with receipts. | RefSpec/spicysearch retain some artifacts and rules, not builder | No; new command | AT RISK |
| `corpora/profile_evaluation.py` | Runs bounded evaluation across all declared source profiles. | NONE executable | No; new command | AT RISK |
| `corpora/relation_exclusion_evaluation.py` | Candidate-only relation diagnostic with deterministic comparisons and quality gates. | NONE | No; new command | AT RISK |
| `corpora/relation_exclusion_evaluation_v2.py` | Fair relation/change-event evaluation with temporal, attribution and conditionality fields plus blind adjudication. | NONE | No; new command | CRITICAL AT RISK |
| `corpora/segmentation_embedding_audit.py` | Adds native model token-limit evidence to segmentation results. | NONE exact | No; new command | AT RISK |
| `corpora/segmentation_evaluation.py` | Builds provenance-bound source caches, gold spans and adversarial segmentation cases. | DocSpec segmentation runtime only | No; new command | AT RISK |
| `corpora/segmentation_experiment.py` | Reproducible five-arm, multi-budget segmentation and retrieval experiment. | NONE | No; new command | CRITICAL AT RISK |
| `corpora/segmentation_rerank.py` | Reranks fixed dense candidates while preserving input audit evidence. | NONE | No; new command | AT RISK |
| `corpora/segmentation_sparse_retrieval.py` | Evaluates learned sparse retrieval and dense/sparse reciprocal-rank fusion. | NONE | No; new command | AT RISK |
| `corpora/segmentation_tagging.py` | Evaluates segmentation choices through real ontology tagging and grounding metrics. | NONE | No; new command | AT RISK |
| `data_dictionary.py` | Reconciles descriptions, in-code schemas and live published Parquet schemas. | NONE | Yes; `spicy-regs-dict` invokes new behavior | CRITICAL AT RISK |
| `document_file_pipeline.py` | Captures files, versions, extractions, segments and receipts. | DocSpec execution, extraction and segmentation | No; new command | SUPERSEDED |
| `enrichment/__init__.py` | Package marker. | NONE needed | No | No independent behavior |
| `enrichment/connected_concepts.py` | One-hop verified concept expansion without recursive ranking claims. | spicysearch `related_topics.py` | No; new callers | RECREATED under newer policy |
| `enrichment/experiment_artifacts.py` | Produces explicitly development-only candidate artifacts and refuses production-looking inputs. | spicysearch `validation/relevance_artifacts.py` | No | RECREATED |
| `enrichment/open_set.py` | Verifies open-set label/value assertions and source spans. | RefSpec binding/vocabulary, partially | No | PARTIAL; wrapper at risk |
| `evaluate_tag_quality.py` | Tag-drift alarm and basic quality measurement. | spicysearch `validation/topic_baseline.py` | No; new command | SUPERSEDED by stronger baseline |
| `evaluation_boundary.py` | Prevents identity, digest, concept and near-duplicate leakage across evaluation splits. | RefSpec sealed-gold conformance; spicysearch holdout gates | No | SUPERSEDED |
| `mcp_server.py` | Resolves atomic materialized tables and omits them on validation failure. Also removes origin’s `/` and `/icon.png`. | NONE | Yes; `spicy-regs-mcp` invokes resolver | Resolver AT RISK; route removal is a regression |
| `pipelines/materialized.py` | Restores one prior snapshot, validates schemas, runs a staged graph and publishes an atomic dataset generation. | NONE | No; new command | CRITICAL AT RISK |
| `pipelines/ontology_dataset.py` | Concrete multi-stage builder for identity and concept tables. | RefSpec owns much meaning, but no equivalent dataset assembly | No; new command | AT RISK |
| `pipelines/rollups/base.py` | Minor base-runner/logging changes. | NONE needed | Yes; old rollup commands | No unique capability |
| `pipelines/rollups/bill_subjects.py` | Thin wrapper for bill-subject acquisition/enrichment. | NONE | No; new command | Wrapper only; risk is in source/transform |
| `pipelines/rollups/court_opinion_bodies.py` | Thin wrapper for CourtListener body materialization. | NONE | No; new command | Wrapper only |
| `pipelines/rollups/court_opinion_clusters.py` | Thin wrapper for CourtListener cluster materialization. | NONE | No; new command | Wrapper only |
| `pipelines/rollups/supreme_court_opinions.py` | Thin wrapper for official Supreme Court publication. | NONE | No; new command | Wrapper only |
| `publication.py` | Local and directory write-once publication primitives. | rulespec `rulespec-artifacts` no-replace publisher | No old invocation | RECREATED; current dirty version already delegates |
| `published.py` | Fail-closed resolver for a versioned materialized pointer, manifest and complete public table set. | NONE | No file; invoked by old MCP/dictionary commands | CRITICAL AT RISK |
| `rulespec_testbed.py` | Small real-data Rulespec tagging diagnostic with source facts and gold splits. | Components exist separately; no equivalent runner | No; new command | AT RISK |
| `schemas/federal_register.py` | Stable Federal Register projection; landing variant records `topics_json` as version-dependent. | NONE exact | No file; old FR rollup imports it | AT RISK |
| `source_profile_artifacts.py` | Validates, canonicalizes and seals a complete source-profile catalog joined to exact RefSpec resource IDs. | RefSpec contains generated profile evidence, not generator | No | AT RISK |
| `source_profile_artifacts_cli.py` | CLI for the profile-artifact generator. | NONE | No; new command | Risk follows generator |
| `source_profiles.py` | Declares source profiles and their measurements. | Profile data survives in RefSpec evidence | No | PARTIAL; declarations survive, authoring checks do not |
| `sources/__init__.py` | Registers added readers and lazily imports `StagingWriter`. | NONE | Yes; import-reachable from old commands | LOW-RISK lazy-import method |
| `sources/bill_subjects.py` | Fetches bill details and CRS policy subjects, resolves carrier bills and reports coverage. | NONE | No direct old command; import-only | AT RISK |
| `sources/courtlistener.py` | Adds incremental keyless CourtListener search for cluster metadata, deliberately excluding bodies. | NONE | Yes; old CourtListener rollup | AT RISK |
| `sources/courtlistener_bulk.py` | Reads pinned CourtListener bulk listings with integrity and inclusion-state checks. | DocSpec `tools/courtlistener_bulk_source.py` | No | SUPERSEDED |
| `sources/document_populations.py` | Captures and verifies CBO feeds and GovInfo CFR package populations. | RefSpec has some resource readers, not this capture/fixity method | No | PARTIAL; acquisition method at risk |
| `sources/fcc_ecfs.py` | Derives distinct FCC proceedings from filings and fails on conflicting identity. | NONE | Yes; old FCC rollups | AT RISK |
| `sources/federal_register.py` | Uses bounded date windows, splits truncated result sets and fails on irreducible/retry exhaustion. | NONE | Yes; old FR rollup | CRITICAL AT RISK |
| `sources/iceberg.py` | Branch removes origin’s secret setup and null-safe Parquet backfill. | `origin/main` is stronger | Yes; old pipelines | REGRESSION; discard branch version |
| `sources/mirrulations.py` | Bounded streaming, exact ETag-conditioned fetches, size caps and fail-fast handling. | NONE exact | Yes; old pipeline | CRITICAL AT RISK |
| `sources/r2.py` | Adds expected-shrink publishing and correct cache/content headers, but reintroduces swallowed parallel-upload failures. | NONE for additions; origin retains failure propagation | Yes; old pipelines | MIXED; salvage only headers/`allow_shrink` |
| `sources/source_domains.py` | Compares pinned OpenAPI/XSD declarations with observed domains; fails on unrecorded or stale accepted discrepancies. | NONE | No | CRITICAL AT RISK |
| `sources/supreme_court_opinions.py` | Reads official term indexes and PDFs with page ranges and classifications. | NONE | No; new command | AT RISK |
| `sources/uscode_olrc.py` | Parses OLRC Popular Name Tool/Table III data. | RefSpec `registry/usc_act_index.py` | No | SUPERSEDED |
| `sources/uscode_uslm.py` | Scans USLM source credits using strict enactment rules and quarantine. | RefSpec consumes pinned source-credit artifacts but lacks located scanner | No | PARTIAL; scanner at risk |
| `transforms/__init__.py` | Eagerly imports new transforms into the registry. | NONE | Yes; old commands import registry | REGRESSION: unwanted dependency reachability |
| `transforms/build_authority_edges.py` | Parses Unified Agenda legal authorities, preserves range endpoints and retains failed parses. | RefSpec parses authority evidence, but lacks this materializer | No direct old command; import-only | PARTIAL; table builder/quarantine at risk |
| `transforms/build_comment_periods.py` | Builds continuous and reopened comment intervals; merges only uniquely resolved assertions. | NONE | No direct old command; import-only | CRITICAL AT RISK |
| `transforms/build_concept_assignments.py` | Materializes provenance-bound concept assignments. | RefSpec/spicysearch concept binding, partially | No direct old command; import-only | PARTIAL; ETL at risk |
| `transforms/build_concept_events.py` | Builds append-only concept lifecycle events. | RefSpec lifecycle behavior, partially | No direct old command; import-only | PARTIAL; ETL at risk |
| `transforms/build_concepts.py` | Materializes the concept registry into tables. | RefSpec Atlas builders, partially | No direct old command; import-only | PARTIAL |
| `transforms/build_congress_bills.py` | Derives Public Law numbers and backfills prior Parquet without replaying the API. | NONE | Yes; old Congress rollup | AT RISK |
| `transforms/build_court_opinion_bodies.py` | Builds full CourtListener opinion-text tables from bulk material. | NONE | No; new command | AT RISK |
| `transforms/build_court_opinion_clusters.py` | Builds CourtListener decision metadata with bounded batching/headroom. | DocSpec source captures overlap, not this table | No; new command | AT RISK |
| `transforms/build_federal_register.py` | Adds `topics_json`, stable projection and one-time backfill when prior data lacks the column. | NONE exact | Yes; old FR rollup | AT RISK |
| `transforms/build_fr_docket_links.py` | Preserves stated docket values, separates normalization from resolution and produces deterministic rows. | Identifier rules survive in RefSpec, not this materializer | Yes; old docket-link rollup | PARTIAL; executable behavior at risk |
| `transforms/build_proceedings.py` | Uses union-find to group trusted dockets only through shared FR artifacts; never broad RIN equality. | NONE | No direct old command; import-only | CRITICAL AT RISK |
| `transforms/build_regulatory_agenda.py` | Builds durable RIN agenda items and links only uniquely resolved targets. | NONE executable | No direct old command; import-only | AT RISK |
| `transforms/build_rule_targets.py` | Creates a conservative docket/CFR/RIN identity spine from bounded evidence. | NONE executable | No direct old command; import-only | CRITICAL AT RISK |
| `transforms/build_supreme_court_opinions.py` | Converts official Supreme Court PDFs into published opinion rows. | NONE | No; new command | AT RISK |
| `transforms/build_unified_agenda.py` | Fails on invalid dates; interprets day `00` as first day instead of clamping broadly. | RefSpec has related registry parsing, not confirmed equivalent | Yes; old Unified Agenda rollup | PARTIAL; exact date rule at risk |
| `transforms/court_scope.py` | Derives jurisdiction/federal scope from docket evidence with cached mapping receipts. | NONE | No | AT RISK |
| `transforms/enrich_bill_subjects.py` | Incrementally adopts per-bill subject results and records coverage. | NONE | No | AT RISK |
| `transforms/pdf_text.py` | Adds configurable whitespace/separators, per-page output and failed-page ordinals. | DocSpec extraction has pages/receipts, partially | Yes; `enrich-pdf-text` | Core safe; added failure detail PARTIAL |
| `transforms/pdf_text_pymupdf.py` | Extracts text plus per-word page coordinates using PyMuPDF. | NONE | No; new document-file command | AT RISK |
| `vectordb/embed.py` | Bulk embedding already exists; branch updates the model dimension API call. | spicysearch has vector search, not this bulk CLI | Yes; `embed` | Core safe; compatibility fix at risk |
| `manifest.py` | Bloom-filter incremental-crawl state plus streaming manifest updates. | Not needed: exact file is on origin | Yes; old pipeline | SAFE on `origin/main` |
| `enrich_pdf.py` | Drives PDF text enrichment. | Not needed: unchanged on origin | Yes; `enrich-pdf-text` | SAFE on `origin/main` |
| `backfill_derived_text.py` | Backfills derived comment text. | Not needed: unchanged on origin | Yes; `backfill-comment-text` | SAFE on `origin/main` |

## NUGGETS AT RISK

1. **Atomic materialized-dataset publication and resolution.** The writer restores state from one prior manifest, publishes immutable artifacts, and replaces `latest.json` only last; the reader validates version, snapshot path, complete table set and public visibility. No surviving repo implements this behavior. [materialized.py:285](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/pipelines/materialized.py:285), [materialized.py:451](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/pipelines/materialized.py:451), [materialized.py:546](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/pipelines/materialized.py:546), [published.py:66](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/published.py:66)

2. **Leak-resistant, human-adjudicated relation evaluation.** V2 keeps oracle fields out of provider payloads and requires two distinct blind reviews, bound digests and final human resolution. [relation_exclusion_evaluation_v2.py:1](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/corpora/relation_exclusion_evaluation_v2.py:1), [relation_exclusion_evaluation_v2.py:398](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/corpora/relation_exclusion_evaluation_v2.py:398), [relation_exclusion_evaluation_v2.py:1357](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/corpora/relation_exclusion_evaluation_v2.py:1357)

3. **The segmentation experiment system, not merely segmentation code.** It compares five arms over the same immutable artifact snapshot, then layers embedding audits, fixed-candidate reranking, sparse fusion and ontology-tagging outcomes. DocSpec and spicysearch reproduce runtime pieces, not this controlled method. [segmentation_experiment.py:1](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/corpora/segmentation_experiment.py:1), [segmentation_experiment.py:2757](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/corpora/segmentation_experiment.py:2757)

4. **Conservative rulemaking identity and time construction.** Comment periods merge only uniquely resolved assertions; proceedings join dockets through shared FR artifacts rather than RIN equality; rule targets preserve a bounded evidence spine. [build_comment_periods.py:76](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/transforms/build_comment_periods.py:76), [build_proceedings.py:400](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/transforms/build_proceedings.py:400), [build_rule_targets.py:1](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/transforms/build_rule_targets.py:1)

5. **Acquisition correctness under changing upstream data.** Federal Register pagination recursively splits truncated windows; Mirrulations binds a frozen draw to later bytes with S3 `IfMatch`. [federal_register.py:86](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/sources/federal_register.py:86), [mirrulations.py:264](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/sources/mirrulations.py:264)

6. **Schema-versus-published drift detection.** The dictionary checks curated descriptions, expected schemas and actual Parquet `DESCRIBE` output, including tables or columns missing on either side. [data_dictionary.py:728](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/data_dictionary.py:728), [data_dictionary.py:800](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/data_dictionary.py:800), [data_dictionary.py:918](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/data_dictionary.py:918)

7. **Pinned source-domain discrepancy ledger.** Declared OpenAPI/XSD enums are compared with observed values; both new discrepancies and obsolete accepted exceptions fail the gate. [source_domains.py:1](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/sources/source_domains.py:1), [source_domains.py:602](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/sources/source_domains.py:602)

8. **Federal Register additive-schema semantics from the landing worktree.** A pinned pre-backfill table may legitimately lack `topics_json`; consumers must preserve absence rather than invent a null field. This explicit rule exists only in the untracked landing schema. [federal_register.py:29](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/schemas/federal_register.py:29)

9. **PDF failure evidence and spatial text.** The branch records failed page ordinals; the PyMuPDF implementation adds per-word coordinates. DocSpec does not reproduce the coordinate output. [pdf_text.py:57](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/transforms/pdf_text.py:57), [pdf_text_pymupdf.py:1](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/transforms/pdf_text_pymupdf.py:1)

10. **R2 cache and expected-shrink rules—but not the branch uploader wholesale.** `latest.json` and Parquet use revalidation semantics, and atomic pointers can bypass the anti-shrink guard intentionally. However, the branch’s unconsumed `executor.map` again swallows worker failures; `origin/main` documents the eight-week outage that caused the fix. [r2.py:150](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/sources/r2.py:150), [r2.py:185](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/sources/r2.py:185), [r2.py:237](/Users/mikewolfd/Work/spicy-regs/src/spicy_regs/sources/r2.py:237)

`manifest.py` is explicitly **not at risk**: its Bloom-filter crawl state is unchanged on `origin/main`. Its key warning also survives there—a false positive permanently skips a new object until a full manifest refresh. Likewise, `enrich_pdf.py` and `backfill_derived_text.py` are baseline files, not new discarded work.

Unresolved parity claims:

- `candidate_release.py`: RefSpec reproduces the outcome, but I did not prove byte-for-byte receipt compatibility. Running both readers against the same sealed Atlas release would settle it.
- `source_profile_artifacts.py`: generated profile data survives in RefSpec, but no equivalent generator was found. A surviving build script outside `src/` could change the verdict.
- `sources/uscode_uslm.py`: RefSpec consumes the resulting pinned data; no surviving source-credit scanner was found. Locating the artifact-generation provenance would settle it.
- The two discarded `schemas/federal_register.py` variants encode different concerns: faithful projection versus optional-column history. Versioned published manifests and consumer tests are needed to decide the combined surviving rule.


