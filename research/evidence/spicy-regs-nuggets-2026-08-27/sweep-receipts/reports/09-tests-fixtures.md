## INVARIANTS AT RISK

1. [tests/test_source_native_release.py:1004](/Users/mikewolfd/Work/spicy-regs/tests/test_source_native_release.py:1004)::`test_capped_single_day_refuses_ambiguous_source_state` — A Federal Register interval that still hits the API cap after narrowing to one day must fail, never claim completeness. **Absent** from the four survivors; checked [DocSpec acquisition tests](/Users/mikewolfd/Work/DocSpec/tests/conformance/test_acquisition.py:210), which cover transport reconciliation but not source-specific cap ambiguity.

2. [tests/test_source_native_release.py:1028](/Users/mikewolfd/Work/spicy-regs/tests/test_source_native_release.py:1028)::`test_publisher_refuses_missing_or_reordered_date_windows` — Complete publication requires the exact ordered leaf-window inventory; missing or reordered windows invalidate the snapshot. **Absent** from [DocSpec source-catalog tests](/Users/mikewolfd/Work/DocSpec/tests/test_source_catalog_snapshot.py:1337).

3. [tests/test_source_native_release.py:1059](/Users/mikewolfd/Work/spicy-regs/tests/test_source_native_release.py:1059)::`test_publisher_independently_refuses_a_false_source_count` — Publisher-side verification must recompute source counts instead of trusting acquisition claims. **Absent** from DocSpec’s generic catalog and acquisition tests.

4. [tests/test_regulations_gov_source_native.py:279](/Users/mikewolfd/Work/spicy-regs/tests/test_regulations_gov_source_native.py:279)::`test_document_pages_capture_exact_listing_metadata_and_object_bytes_once` — One enumeration must bind listing metadata to the exact object bytes without a second, potentially inconsistent listing. **Absent** from [DocSpec’s Regulations.gov adapter tests](/Users/mikewolfd/Work/DocSpec/tests/test_regulations_gov_catalog.py:414).

5. [tests/test_regulations_gov_source_native.py:412](/Users/mikewolfd/Work/spicy-regs/tests/test_regulations_gov_source_native.py:412)::`test_missing_or_changed_enumerated_object_refuses_complete_snapshot` — Every enumerated object must still exist with identical metadata when read; disappearance or replacement invalidates completeness. DocSpec tests pinned-byte mutation, but **does not assert enumeration/read consistency**; checked [test_courtlistener_bulk_source.py](/Users/mikewolfd/Work/DocSpec/tests/test_courtlistener_bulk_source.py:139).

6. [tests/test_regulations_gov_comments_source_native.py:291](/Users/mikewolfd/Work/spicy-regs/tests/test_regulations_gov_comments_source_native.py:291)::`test_repeated_normalized_comment_versions_always_refuse_a_tie` — Two comment versions normalizing to the same newest timestamp must be refused, not selected by incidental order. DocSpec only verifies that its adapter propagates an upstream tie refusal; it does not implement or test the selection rule. Checked [test_regulations_gov_catalog.py](/Users/mikewolfd/Work/DocSpec/tests/test_regulations_gov_catalog.py:961).

7. [tests/test_relation_exclusion_evaluation_v2.py:602](/Users/mikewolfd/Work/spicy-regs/tests/test_relation_exclusion_evaluation_v2.py:602)::`test_v2_eligibility_requires_two_distinct_sealed_human_reviews` — Evaluation eligibility requires two distinct, complete, content-bound human reviews. RefSpec has two-pass framing tests, but **not this sealed-review eligibility gate**; checked [test_atlas_relatedmatch_blind_review.py](/Users/mikewolfd/Work/RefSpec/tests/test_atlas_relatedmatch_blind_review.py:227).

8. [tests/test_relation_exclusion_evaluation_v2.py:725](/Users/mikewolfd/Work/spicy-regs/tests/test_relation_exclusion_evaluation_v2.py:725)::`test_v2_eligibility_rejects_future_dated_audit_records` — A digest-valid review dated after the gate cannot authorize an earlier evaluation. **Absent** from Rulespec’s analysis carriers and RefSpec’s blind-review tests.

9. [tests/test_relation_exclusion_evaluation_v2.py:416](/Users/mikewolfd/Work/spicy-regs/tests/test_relation_exclusion_evaluation_v2.py:416)::`test_v2_does_not_inherit_entailment_for_unreviewed_enclosing_span` — Reviewing a smaller evidence span does not authorize a broader enclosing span. Rulespec preserves comparison shapes, but **no surviving behavioral test asserts this evidence-boundary rule**; checked `rulespec/crates/rkaf-core/tests/fixture_round_trip.rs`.

10. [tests/test_relation_exclusion_evaluation_v2.py:573](/Users/mikewolfd/Work/spicy-regs/tests/test_relation_exclusion_evaluation_v2.py:573)::`test_v2_keeps_proposed_removal_as_event_and_rejects_invalid_hybrid` — A proposed removal remains an event; it cannot be combined with a current-state assertion. Rulespec tests the individual carrier shapes but **not this cross-record incompatibility**.

11. [tests/test_body_retrieval_corpus.py:381](/Users/mikewolfd/Work/spicy-regs/tests/test_body_retrieval_corpus.py:381)::`test_a_cloudflare_interstitial_is_quarantined_not_sealed` — HTTP 200 challenge pages must be recognized as unusable bodies and quarantined. **Absent** from DocSpec content fetchers and SpicySearch tests.

12. [tests/test_body_retrieval_corpus.py:687](/Users/mikewolfd/Work/spicy-regs/tests/test_body_retrieval_corpus.py:687)::`test_incomplete_cache_cannot_narrow_the_v3_reconciliation_universe` — A partial cache may not silently redefine the universe against which completeness is measured. **Absent** from the surviving corpus tests; DocSpec’s reconciliation tests operate on declared complete inputs.

13. [tests/test_body_retrieval_corpus.py:707](/Users/mikewolfd/Work/spicy-regs/tests/test_body_retrieval_corpus.py:707)::`test_xml_capture_without_content_type_keeps_the_xml_fallback` — Missing HTTP content type must not erase a rendition already identified as XML by the source path. **Absent** from DocSpec’s media dispatch tests.

14. [tests/test_body_retrieval_corpus.py:798](/Users/mikewolfd/Work/spicy-regs/tests/test_body_retrieval_corpus.py:798)::`test_measure_counts_zero_width_entities_as_the_publisher_writes_them` — Measurement counts encoded zero-width entities, not merely decoded Unicode characters. SpicySearch retains the measurement in prose, but **has no equivalent executable test**.

15. [tests/test_bill_subjects.py:198](/Users/mikewolfd/Work/spicy-regs/tests/test_bill_subjects.py:198)::`test_a_failed_later_page_publishes_nothing_rather_than_a_truncated_list` — A later-page failure makes the entire paginated answer incomplete. **Absent** from RefSpec’s BILLSTATUS vocabulary readers and DocSpec acquisition tests.

16. [tests/test_bill_subjects.py:219](/Users/mikewolfd/Work/spicy-regs/tests/test_bill_subjects.py:219)::`test_a_404_is_an_answer_not_a_failure` — A 404 is a definitive “bill unavailable,” distinct from transport failure and from a valid bill carrying no subjects. **Absent** from all four survivors.

17. [tests/test_bill_subjects.py:365](/Users/mikewolfd/Work/spicy-regs/tests/test_bill_subjects.py:365)::`test_switching_to_a_deeper_carrier_re_asks_what_the_other_one_lacked` — Negative caching is scoped to a source’s coverage floor; moving from bulk data to the deeper API must revisit unresolved bills. **Absent** from all four survivors.

18. [tests/test_supreme_court_opinions.py:135](/Users/mikewolfd/Work/spicy-regs/tests/test_supreme_court_opinions.py:135)::`test_term_index_reads_the_volume_layout_the_pre_2021_terms_use` — Pre-2021 Supreme Court term indexes use a different bound-volume layout and require a separate parser path. Only a research-catalog mention survives in RefSpec; **no code-level test exists**.

19. [tests/test_supreme_court_opinions.py:280](/Users/mikewolfd/Work/spicy-regs/tests/test_supreme_court_opinions.py:280)::`test_reader_fetches_a_shared_volume_once_and_records_a_dead_link` — Opinions sharing a bound volume reuse one fetch while preserving individual dead-link evidence. **Absent** from all four survivors.

## IRREPLACEABLE FIXTURES

- Ignored, local-only real corpus: [`output/segmentation-source-cache-v2/`](/Users/mikewolfd/Work/spicy-regs/output/segmentation-source-cache-v2) — 47 MB of captured HTML, XML, and PDF bytes plus `source-lock.json`.
- Ignored, local-only sealed evaluation: [`output/segmented-real-data-evaluation-v2/`](/Users/mikewolfd/Work/spicy-regs/output/segmented-real-data-evaluation-v2) — 2.7 MB of Parquet members, membership, gold spans, source provenance, manifest, receipt, and lock.
- Frozen migration oracles:
  - [`tests/fixtures/docpipeline_segments_migration_v1.json`](/Users/mikewolfd/Work/spicy-regs/tests/fixtures/docpipeline_segments_migration_v1.json)
  - [`tests/fixtures/docpipeline_retrieval_migration_v1.json`](/Users/mikewolfd/Work/spicy-regs/tests/fixtures/docpipeline_retrieval_migration_v1.json)
  - [`tests/fixtures/docpipeline_step4_expected_differences_v1.json`](/Users/mikewolfd/Work/spicy-regs/tests/fixtures/docpipeline_step4_expected_differences_v1.json)
  - [`tests/fixtures/docpipeline_step5_expected_differences_v1.json`](/Users/mikewolfd/Work/spicy-regs/tests/fixtures/docpipeline_step5_expected_differences_v1.json)
- Relation corpora and provisional oracle:
  - [`tests/fixtures/relation_exclusion_explicit_denial_v1.json`](/Users/mikewolfd/Work/spicy-regs/tests/fixtures/relation_exclusion_explicit_denial_v1.json)
  - [`tests/fixtures/relation_exclusion_explicit_denial_v2_corpus.json`](/Users/mikewolfd/Work/spicy-regs/tests/fixtures/relation_exclusion_explicit_denial_v2_corpus.json)
  - [`tests/fixtures/relation_exclusion_explicit_denial_v2_oracle.provisional.json`](/Users/mikewolfd/Work/spicy-regs/tests/fixtures/relation_exclusion_explicit_denial_v2_oracle.provisional.json)
  - [`docs/evidence/relation-exclusion-openai-v2-focused-five-2026-07-25/`](/Users/mikewolfd/Work/spicy-regs/docs/evidence/relation-exclusion-openai-v2-focused-five-2026-07-25)
- Sealed DocumentRelease bundles:
  - [`fixtures/releases/document-release-v3/`](/Users/mikewolfd/Work/spicy-regs/fixtures/releases/document-release-v3)
  - [`fixtures/releases/document-release-v3-incremental-mixed/`](/Users/mikewolfd/Work/spicy-regs/fixtures/releases/document-release-v3-incremental-mixed)
  - [`tests/fixtures/document-release-v3-source/`](/Users/mikewolfd/Work/spicy-regs/tests/fixtures/document-release-v3-source)
  - [`tests/fixtures/document-release-v3-incremental-mixed-source/`](/Users/mikewolfd/Work/spicy-regs/tests/fixtures/document-release-v3-incremental-mixed-source)
- Captured document bytes absent from every survivor:
  - [`sample-data/mirrulations/`](/Users/mikewolfd/Work/spicy-regs/sample-data/mirrulations)
  - [`sample-data/document-files/`](/Users/mikewolfd/Work/spicy-regs/sample-data/document-files)
- Domain evidence unique to this branch: [`sample-data/source-domains/observed-domain-snapshot-2026-08-03.json`](/Users/mikewolfd/Work/spicy-regs/sample-data/source-domains/observed-domain-snapshot-2026-08-03.json) and its capture manifest. The source XSD and OpenAPI bytes do survive in RefSpec.
- Provisional ELSST cases: [`docs/evidence/elsst-r6-forward-development-dataset-2026-07-29/`](/Users/mikewolfd/Work/spicy-regs/docs/evidence/elsst-r6-forward-development-dataset-2026-07-29). The exact 19 grounded rows do not survive elsewhere.
- Gold and projection evidence read directly by tests:
  - [`docs/evidence/gold-adjudication-2026-07-27/`](/Users/mikewolfd/Work/spicy-regs/docs/evidence/gold-adjudication-2026-07-27)
  - [`docs/evidence/single-document-rulespec-projection-2026-07-28/`](/Users/mikewolfd/Work/spicy-regs/docs/evidence/single-document-rulespec-projection-2026-07-28)
- Landing-only, untracked pinned universe: [`regulations-gov-published-catalog-2021-2025-metadata-complete.json`](/Users/mikewolfd/Work/spicy-regs-landing/src/spicy_regs/universes/regulations-gov-published-catalog-2021-2025-metadata-complete.json). No copy exists in the four survivors.
- `output/usc-act-index-2026-08-02/` and `output/usc-source-credit-index-2026-08-02/` are already empty, so the real sealed artifacts those tests expect are already unavailable.

## ALREADY COVERED ELSEWHERE

- Immutable publication, concurrent winner, no replacement, symlink/root-swap refusal, partial-publication refusal, and tamper-before-first-row are covered more thoroughly in [DocSpec source-catalog snapshot tests](/Users/mikewolfd/Work/DocSpec/tests/test_source_catalog_snapshot.py:1337), [S3/blob tests](/Users/mikewolfd/Work/DocSpec/tests/test_s3_blob_adapter.py:212), and [Rulespec artifact tests](/Users/mikewolfd/Work/rulespec/packages/rulespec-artifacts/tests/test_artifact.py:538).
- Exact Regulations.gov document/docket/Federal Register joins, unmatched related rows, comment null-date policy, and source-fact preservation are covered in [DocSpec’s catalog tests](/Users/mikewolfd/Work/DocSpec/tests/test_regulations_gov_catalog.py:414).
- The landing metadata assertions—source-scoped native facts, exact joins, no invented context, and consumer labeling of related Federal Register text—are covered by DocSpec plus [SpicySearch source-catalog metadata tests](/Users/mikewolfd/Work/spicysearch/tests/search/test_source_catalog_metadata.py:240). The untracked universe file itself does not survive.
- Act ambiguity, alias cycles, division fencing, Table III/source-credit composition, and amendment-versus-enactment handling are covered by RefSpec’s `test_act_resolution.py`, `test_usc_act_index.py`, `test_usc_section_oracle.py`, and `test_unified_agenda_parquet.py`.
- Source-domain quirks such as duplicated `Not Major`, published-versus-observed Unified Agenda values, and Regulations.gov controlled values are covered in `RefSpec/tests/test_unified_agenda_schema_divergence.py`, `test_unified_agenda_codes.py`, and `test_regulations_gov_codes.py`.
- Counting an arm that does not fire as false negatives, rather than shrinking its denominator, is covered by [SpicySearch’s scoring test](/Users/mikewolfd/Work/spicysearch/tests/test_score_inferred_against_recovered.py:98).
- Blind inputs excluding answer-key fields and requiring two framing passes are covered in [RefSpec’s blind-review tests](/Users/mikewolfd/Work/RefSpec/tests/test_atlas_relatedmatch_blind_review.py:131). The stricter sealed-review timing and completeness gate remains at risk.
- Deliberately absent, therefore scope evidence rather than current capability loss:
  - `test_docpipeline_*_migration.py`: exact legacy parity is intentionally not a surviving objective.
  - `test_docpipeline_adapter_{docling,openai,anthropic,codex_cli,...}.py`: DocSpec injects processors but deliberately does not own these provider-specific adapters.
  - `test_transforms_pdf_text_pymupdf.py`: the recorded adoption decision was reversed; survivors intentionally retain the incumbent PDF path.
  - `test_elsst_r6_forward_development_dataset.py`: explicitly `developmentOnly`, unsealed, holdout-exposed, and blocked from adoption.
  - Candidate-selector ablations, ANN experiments, sparse/rerank/tagging runs, and relation-extraction paid-run machinery remain experiment/testbed evidence; they do not authorize a surviving production lane.


