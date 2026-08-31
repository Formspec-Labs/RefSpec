## FINDINGS AT RISK

1. [relation-exclusion runs](/Users/mikewolfd/Work/spicy-regs/docs/evidence/relation-exclusion-codex-cli-proof-certificate-r1-2026-07-25), [candidate keyword calls](/Users/mikewolfd/Work/spicy-regs/docs/evidence/candidate-selector-ablation-2026-07-28/keyword-calls), [gold adjudication](/Users/mikewolfd/Work/spicy-regs/docs/evidence/gold-adjudication-2026-07-27) — Exact provider requests, replies, per-case failures, blind judge votes, and disagreement resolution are irreplaceable; prompt changes moved exact F1 from 0.273 to 0.700 and polarity F1 as high as 0.900. Aggregates survive in SpicySearch, but none of the four current trees contains the underlying replies or judgments.

2. [court-data-coverage-2026-08-22.md](/Users/mikewolfd/Work/spicy-regs/docs/evidence/court-data-coverage-2026-08-22.md:238) — CourtListener’s ID join silently misses D.D.C.: 1,571 Administrative Procedure Act dockets produced zero direct matches although 46,581 D.D.C. clusters exist; at least 249 “missing” cases resolve through duplicate docket records, requiring exact `(court_id, docket_number)` reconciliation. Absent from DocSpec’s bulk adapter, RefSpec, rulespec, and SpicySearch’s court report/code.

3. [court-data-coverage-2026-08-22.md](/Users/mikewolfd/Work/spicy-regs/docs/evidence/court-data-coverage-2026-08-22.md:553) — The full docket map measured 71,677,647 rows, 4.67 GiB and 111 minutes; it placed all 10,070,727 clusters, and a dense unsigned-short court index avoids an impractical Python dictionary. No equivalent measurement or implementation constant exists in the four current trees.

4. [court-data-coverage-2026-08-22.md](/Users/mikewolfd/Work/spicy-regs/docs/evidence/court-data-coverage-2026-08-22.md:607) — CourtListener CSV uses backslash escaping: the default parser desynchronized 1,987/3,000 IDs, while `escapechar='\\'` produced zero bad IDs and retained all 3,000 joins. DocSpec enumerates CourtListener dumps but does not pin this parsing rule; it is absent elsewhere.

5. [court-data-coverage-2026-08-22.md](/Users/mikewolfd/Work/spicy-regs/docs/evidence/court-data-coverage-2026-08-22.md:76) — CourtListener’s 1,076-object, 1,598.65-GiB bulk surface is effectively client-throttled to about 1.77 MiB/s; parallel connections do not improve aggregate throughput, the 50.814-GiB opinion dump costs about 8.6 hours, and REST opinion/cluster endpoints require authentication. The current DocSpec adapter preserves listing/capture mechanics but none of these capacity measurements or the per-client conclusion.

6. [court-data-coverage-2026-08-22.md](/Users/mikewolfd/Work/spicy-regs/docs/evidence/court-data-coverage-2026-08-22.md:368) — Supreme Court acquisition has three expensive negative results: OT2017–20 is only 204/260 reachable because four upstream volume PDFs return 404; the site once returned OT2023 from an OT2021 URL; and it blocked this client after roughly 80 requests in 25 minutes, so the full 335-request capture never completed. No surviving repo records these source observations or the required term-date refusal.

7. [court-data-coverage-2026-08-22.md](/Users/mikewolfd/Work/spicy-regs/docs/evidence/court-data-coverage-2026-08-22.md:448) — RECAP has no bulk document dataset and its keyless search projected 6–9 hours for roughly 367,000 rows, while fewer than 2% of sampled rows had an available PDF; verdict: do not implement without a token or a metadata-only need. Absent from all four current docs, research, code constants, and tests.

8. [source-native-release-spec.md](/Users/mikewolfd/Work/spicy-regs/docs/superpowers/specs/2026-08-25-source-native-release-spec.md) — Federal Register completeness requires ≤90-day probes, recursive bisection whenever reported count reaches the ambiguous 10,000 cap, refusal on an ambiguous single day, preserved-but-excluded capped replies, and replay of the exact split tree. DocSpec captures generic source catalogs but does not contain this acquisition proof algorithm.

9. [source-native-release-spec.md](/Users/mikewolfd/Work/spicy-regs/docs/superpowers/specs/2026-08-25-source-native-release-spec.md) — Mirrulations completeness requires a sealed exact object listing and deterministic ZIP packs bounded to 1,000 objects/16 MiB, with gap-free indexes and refusal on changed ETags, missing objects, duplicates, or unclassified objects; Regulations.gov comments additionally require newest-`modifyDate` selection and refusal of exact timestamp ties. These source-specific rules are absent from current DocSpec, RefSpec, rulespec, and SpicySearch behavior.

10. [scale-architecture-report-2026-08-04.md](/Users/mikewolfd/Work/spicy-regs/docs/scale-architecture-report-2026-08-04.md) — The Bloom manifest actually consumes about 240 MiB while reporting 120 MiB because `array('L')` is eight bytes locally, and a false positive permanently suppresses a changed key until full refresh. No surviving code or report records either defect.

11. [scale-architecture-report-2026-08-04.md](/Users/mikewolfd/Work/spicy-regs/docs/scale-architecture-report-2026-08-04.md) — Fifteen dropped hourly jobs left 12 agencies un-ingested and HHS roughly five days stale; Iceberg deletion left physical duplicates; finalization reread the entire artifact tree twice. The four surviving repositories retain the headline memory/scale results but not these operational failure findings.

12. [bill_subjects.md](/Users/mikewolfd/Work/spicy-regs/docs/tables/bill_subjects.md) — Congress bill-subject enrichment is bounded and resumable one bill at a time; a stored null row means “asked, no subject assigned,” while no row means acquisition failure, and prior results must merge without reinterpretation. No equivalent table semantics, code constant, or decision exists in the four current trees.

13. [source-native-release-spec.md](/Users/mikewolfd/Work/spicy-regs/docs/superpowers/specs/2026-08-25-source-native-release-spec.md) — The full Federal Register baseline measured 5,871 records with no agency and treats them as retained source facts, not droppable invalid rows. The 1,004,233-row and 890,013-empty-topic constants survive in DocSpec; the 5,871 no-agency baseline does not.

## ALREADY CAPTURED ELSEWHERE

- Court opinion text selection and topic measurements survive in [court-opinions-2026-08-22.md](/Users/mikewolfd/Work/spicysearch/research/court-opinions-2026-08-22.md): `html_with_citations` is the primary text, plain text covers only 22.1%, and dropping null plain text would discard most documents. Its plain-text count is 55,303 versus 55,335 in the discarded acquisition report, so the behavior survives but the exact counts conflict.

- CourtListener listing, immutable candidate capture, ETag checking, and dataset classification survive in DocSpec’s [courtlistener bulk tests](/Users/mikewolfd/Work/DocSpec/tests/test_courtlistener_bulk_source.py).

- Generic source catalogs, `sourceStateScope`, `sourceNativeFacts`, exact joins, topic-empty semantics, byte-reuse accounting, and deterministic partition receipts survive in DocSpec’s [standalone platform specification](/Users/mikewolfd/Work/DocSpec/docs/superpowers/specs/2026-08-05-docspec-standalone-platform-implementation-spec.md), schemas, adapters, and tests.

- The 1.47-GB release/5.36-GB RSS result and 50× documents causing 88× runtime survive in [docspec-legacy-tests-fixtures-evidence.md](/Users/mikewolfd/Work/spicysearch/research/deep-sweep-reader-reports/docspec-legacy-tests-fixtures-evidence.md).

- Extraction retention floors, Docling loss findings, PDF extractor comparisons, discovery behavior, and source-table behavior survive in [spicy-regs-transforms-and-sources.md](/Users/mikewolfd/Work/spicysearch/research/deep-sweep-reader-reports/spicy-regs-transforms-and-sources.md).

- ANN rejection, hyperbolic-subsumption failure, graph-engine measurements, corrected body-corpus arithmetic, range-citation behavior, and segmentation/reranking results survive in [RefSpec’s repository research](/Users/mikewolfd/Work/RefSpec/research/repo-traces-2026-08-08/RESEARCH.md) and [SpicySearch’s idea audit](/Users/mikewolfd/Work/spicysearch/docs/idea-audit.md).

- Aggregate candidate-ablation, relation-exclusion, gold-adjudication, graph-bakeoff, and Rulespec-projection results survive in [docspec-legacy-tests-fixtures-evidence.md](/Users/mikewolfd/Work/spicysearch/research/deep-sweep-reader-reports/docspec-legacy-tests-fixtures-evidence.md); only the raw sealed replies remain at risk.

- The holdout identity, membership digest, blindness rules, and evaluation boundary survive under [evaluation/holdout-labeling](/Users/mikewolfd/Work/spicysearch/evaluation/holdout-labeling/config-freeze.md).

- The landing worktree’s dirty migration correction—retain docket/document/comment substring search until equivalent proof and do not treat document-only search as a replacement—is already stated in [platform-artifact-plan.md](/Users/mikewolfd/Work/spicysearch/docs/superpowers/plans/2026-08-24-platform-artifact-plan.md:146). Retirement remains explicitly unauthorized in [.disposition-v4.md](/Users/mikewolfd/Work/spicysearch/.disposition-v4.md:115).

## BROKEN CITATIONS

No current DocSpec file directly cites the archived documentation paths. Confirmed citations elsewhere:

- Runtime and evaluation: [query_quality_dataset.py](/Users/mikewolfd/Work/spicysearch/src/spicysearch/validation/query_quality_dataset.py:72), [quality-v1 README](/Users/mikewolfd/Work/spicysearch/evaluation/core-query-catalog/quality-v1/README.md:71), [manifest.json](/Users/mikewolfd/Work/spicysearch/evaluation/core-query-catalog/quality-v1/manifest.json:61), [filter-capability-matrix.json](/Users/mikewolfd/Work/spicysearch/evaluation/core-query-catalog/quality-v1/filter-capability-matrix.json:100), [config-freeze.md](/Users/mikewolfd/Work/spicysearch/evaluation/holdout-labeling/config-freeze.md:7), and [config-freeze.json](/Users/mikewolfd/Work/spicysearch/evaluation/holdout-labeling/config-freeze.json:13).

- SpicySearch plans/history: [platform-artifact-plan.md](/Users/mikewolfd/Work/spicysearch/docs/superpowers/plans/2026-08-24-platform-artifact-plan.md:9), [platform consolidation review](/Users/mikewolfd/Work/spicysearch/docs/history/2026-08-25-platform-artifact-consolidation-review.md:35), [cross-product recommendations](/Users/mikewolfd/Work/spicysearch/docs/history/2026-08-11-cross-product-reconciliation-recommendations.md:299), and [corpus-scale-design.md](/Users/mikewolfd/Work/spicysearch/docs/corpus-scale-design.md:185).

- SpicySearch research: [proposal-timeline.md](/Users/mikewolfd/Work/spicysearch/docs/proposal-timeline.md:314) cites dozens of archived table/evidence files; [idea-audit.md](/Users/mikewolfd/Work/spicysearch/docs/idea-audit.md:55), [cross-repo-insight-sweep](/Users/mikewolfd/Work/spicysearch/research/cross-repo-insight-sweep-2026-08-21.md:37), [nuggets report](/Users/mikewolfd/Work/spicysearch/research/nuggets-80-20-2026-08-21.md:108), [legacy evidence audit](/Users/mikewolfd/Work/spicysearch/research/deep-sweep-reader-reports/docspec-legacy-tests-fixtures-evidence.md:36), and [transforms/source audit](/Users/mikewolfd/Work/spicysearch/research/deep-sweep-reader-reports/spicy-regs-transforms-and-sources.md:51) also contain direct path citations.

- RefSpec: [docs/decisions.md](/Users/mikewolfd/Work/RefSpec/docs/decisions.md), [table3 coverage](/Users/mikewolfd/Work/RefSpec/research/evidence/table3-coverage-2026-08-22.md), [dropped-gems survey](/Users/mikewolfd/Work/RefSpec/research/dropped-gems-survey-2026-08-20.md), [remaining-work sweep](/Users/mikewolfd/Work/RefSpec/research/remaining-work-sweep-2026-08-21.md), [vocabulary matching context](/Users/mikewolfd/Work/RefSpec/research/vocabulary-atlas-relation-candidate-matching-context-2026-08-05.md), and the repository-trace files under [research/repo-traces-2026-08-08](/Users/mikewolfd/Work/RefSpec/research/repo-traces-2026-08-08/RESEARCH.md). Copies under `spicysearch/RefSpec/` repeat the same broken citations.

- Rulespec: [CHANGELOG.md](/Users/mikewolfd/Work/rulespec/CHANGELOG.md:345), [TODO.md](/Users/mikewolfd/Work/rulespec/TODO.md:74), [rulemaking adversarial review](/Users/mikewolfd/Work/rulespec/thoughts/reviews/2026-07-24-rulemaking-condition2-adversarial-review.md:70), and [US regulatory identifier specification](/Users/mikewolfd/Work/rulespec/thoughts/specs/2026-07-23-us-regulatory-identifiers-and-rulemaking-module.md).


