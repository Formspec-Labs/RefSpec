# Raw trace: RefSpec research/ documents, evidence/, archive/

Provenance: Sonnet subagent trace, 2026-08-10 (late). HEAD measured: RefSpec `08001c6`.
Status: **verbatim tracer output, preserved unedited** (transport HTML-escapes fixed). Subagent-produced —
per workspace rule, re-derive before relying on any figure not independently verified; the figures
`../RESEARCH.md` cites from this trace were spot-verified at compile time. OBSERVED / INFERRED /
ASSERTED markers are the tracer's own.

---

## research/atlas-agentic-graph-search-next-steps-2026-08-07.md

- **PATH · DATE:** `research/atlas-agentic-graph-search-next-steps-2026-08-07.md` · 2026-08-07 (header date; "Last reviewed" 2026-08-08; carries a 2026-08-09 status annotation)
- **QUESTION:** Should RefSpec/Atlas add `Domain`/`SubjectArea`/`MetaSubject` binding types and enable graph-expansion to support a cross-product agentic search experiment, and in what order/topology should SpicySearch, DocSpec, and RefSpec participate?
- **METHOD:** Design proposal (staged plan with decision gates); references a built-and-locally-verified `EuroVocOrganizationExperiment` as reversible evidence, not as approval.
- **VERDICT:** Do not add new binding types yet. First make SpicySearch a verified Atlas 3.0 consumer with expansion disabled; build the `EuroVocOrganizationExperiment` sidecar and an evaluation bridge before any binding change. Status annotation (2026-08-09): Stage 0 closed/approved via REF-022 (docs/decisions.md); topology fixed as RefSpec=vocabulary/DocSpec=files/SpicySearch=sole junction; Stage 1 queued behind Atlas 1.0/2.0 retirement + rkaf adoption (REF-023).
- **SUPERSEDED-BY:** Not superseded as a document; explicitly still an "Unapproved plan" for its downstream stages. Its Stage 0 premise is overtaken in-place by REF-022/REF-023 in docs/decisions.md (annotated inline, not a separate doc in this set).
- **LANDED-IN-CODE:** OBSERVED (partial) — `EuroVocOrganizationExperiment` is real, wired code: `src/refspec/registry/eurovoc_organization_experiment.py` (full implementation with `EuroVocOrganizationExperimentError`, validation receipts), `tools/build_eurovoc_organization_experiment.py`, `tests/test_eurovoc_organization_experiment.py`. The binding-type additions (`Domain`/`SubjectArea`/`MetaSubject`) are NOT in code — consistent with the plan's own "do not add yet."
- **TRUST FLAG:** none (2026-08-07, outside contamination window).

## research/atlas-full-build-status-logging-note-2026-08-07.md

- **PATH · DATE:** `research/atlas-full-build-status-logging-note-2026-08-07.md` · 2026-08-07
- **QUESTION:** Does adding stderr progress/status logging to the Atlas full-build and validator meaningfully slow the build, and is exhaustive compact-to-RDF parity checking worth keeping?
- **METHOD:** Direct measurement — two real `--check-inputs` runs (status on/off) timed; a 5M-iteration checkpoint microbenchmark; 252 focused tests run after fixture regen.
- **VERDICT:** Overhead is negligible (100.956s vs 101.405s; ~0.008s added at 588,409 resources). On 2026-08-08 exhaustive compact-to-RDF parity was replaced by full shape/size validation plus a bounded 5-record-per-pack sample.
- **SUPERSEDED-BY:** Not superseded; the parity-replacement change it documents is itself archived in `research/archive/atlas-3.0-exhaustive-compact-parity-2026-08-08.md`.
- **LANDED-IN-CODE:** OBSERVED — `_STATUS` reporter (`_StatusReporter`) and `_STATUS.phase(...)`/`_STATUS.progress(...)` calls present throughout `tools/generate_atlas_v3_full.py` (e.g. lines 283, 2348-2437, 4873+).
- **TRUST FLAG:** none.

## research/axiom-ecosystem-analysis-2026-07-28.md

- **PATH · DATE:** `research/axiom-ecosystem-analysis-2026-07-28.md` · 2026-07-28
- **QUESTION:** Should a RefSpec implementation adopt any component of the adjacent "Axiom" ecosystem (rules/logic layer)?
- **METHOD:** Manual research assessment/recommendation ("dated snapshot, not a permanent vendor assessment").
- **VERDICT:** Adopt nothing now. Watch `axiom-corpus` (source coverage) and `receipt` (signing) for future reconsideration; reuse ideas (exact resolution, reverse indexes, proof checks, append-only history) without importing Axiom's stack.
- **SUPERSEDED-BY:** None in this set; still the only Axiom assessment. Cross-referenced by `source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md`.
- **LANDED-IN-CODE:** OBSERVED (by absence, as prescribed) — `grep -rli axiom src/refspec/` returns nothing. The "adopt nothing" decision was followed to the letter.
- **TRUST FLAG:** CONTAMINATION-WINDOW (dated 2026-07-28, same day as the fabricated-research incident commit `d165350` in the parent monorepo's `docs/decisions.md`). No fabrication markers found in this specific doc's own text, but it predates/coincides with the incident and was not independently re-verified in this pass.

## research/concept-tagging-architecture-proposal-2026-07-28.md

- **PATH · DATE:** `research/concept-tagging-architecture-proposal-2026-07-28.md` · 2026-07-28
- **QUESTION:** What tagging architecture is worth testing for large-label-space concept assignment against regulatory documents?
- **METHOD:** Design proposal consolidating original proposal + longer research synthesis, grounded in `evidence/blind-external-research-recovery-2026-07-28/` (9 recovered external research reports).
- **VERDICT:** Test a typed mapping-and-assignment design with stable controlled identifiers, separate facets per semantic kind, broad mapping space narrowed by declared policy, evidence-backed open results or abstention. Explicitly rejects "large label spaces are inherently defective" — the 513,236-row fused registry problem was mixing resources built for different purposes, not scale per se.
- **SUPERSEDED-BY:** Explicitly nonnormative/consolidated-historical; the RefSpec spec treats its choices as "research hypotheses" (spec §15.5). Its portfolio-inventory companions (`source-document-type-matrix`, `source-vocabulary-ontology-thesaurus-catalog`) are downstream, not supersessions.
- **LANDED-IN-CODE:** ASSERTED/INFERRED — spec §15.5 "Research hypotheses" (`spec/refspec.md:3634`) formally carries forward its open questions as unproven hypotheses rather than adopted requirements, matching this doc's own stated non-normative status.
- **TRUST FLAG:** CONTAMINATION-WINDOW (2026-07-28). Its own evidence base (`blind-external-research-recovery-2026-07-28`) is the recovered-transcript material adjacent to the fabrication incident; that evidence set tags every claim ✓/~ and states the summarizer fabricated ≥4 results, so treat `~`-flagged figures here as unverified leads per that legend.

## research/source-document-type-matrix-2026-07-28.md

- **PATH · DATE:** `research/source-document-type-matrix-2026-07-28.md` · 2026-07-28
- **QUESTION:** What source-aware document/entity classification model does a RefSpec implementation need, across which source families?
- **METHOD:** Manual portfolio audit/matrix — 17 current source profiles classified into document/event/observation/entity/link families; a 30-entry roadmap (Tier 1/2/3 + one legacy-rescue) cross-referenced.
- **VERDICT:** "Proposed reference; not adopted." Identifies 9 missing source families and 5 completion gaps as research inputs, not commitments. Concludes tagging must not force non-document sources (events, entities, links) into topical classification.
- **SUPERSEDED-BY:** None directly; explicitly a dated research snapshot, cross-referenced by `source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md`.
- **LANDED-IN-CODE:** INFERRED — the entity/document/link split shows up structurally in later Atlas ring work (`entity` vs `subject` vs `value` vs `legalIdentity` rings), but this specific matrix's 17/30-family enumeration was not directly greppable in `src/refspec/`.
- **TRUST FLAG:** CONTAMINATION-WINDOW (2026-07-28).

## research/source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md

- **PATH · DATE:** `research/source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md` · 2026-07-28
- **QUESTION:** Which controlled vocabularies, ontologies, thesauri, and authority resources should form RefSpec's subject-vocabulary core and specialist modules?
- **METHOD:** Manual research catalog, built on 4 domain-evidence reports (`evidence/source-vocabulary-research-2026-07-28/01-04`), with report 04 flagging 7 provider feeds lacking authority/licensing decisions.
- **VERDICT:** "Proposed research catalog; not adopted." Recommends a small governed general-subject core + specialist modules added only when needed; source-assigned topics as evidence, not classifier inputs by default.
- **SUPERSEDED-BY:** Its subject-vocabulary-core direction is carried forward and substantially reshaped by the `vocabulary-atlas-*` series (2026-08-03 onward), which is the operative lineage that actually shipped.
- **LANDED-IN-CODE:** INFERRED — the "governed core + specialist modules" shape is recognizable in the Atlas ring/portfolio-index design, but this document is several steps removed from what shipped; no direct grep match.
- **TRUST FLAG:** CONTAMINATION-WINDOW (2026-07-28).

## research/vocabulary-atlas-design-proposal-2026-08-03.md

- **PATH · DATE:** `research/vocabulary-atlas-design-proposal-2026-08-03.md` · 2026-08-03 (heavily annotated in-place through 2026-08-04)
- **QUESTION:** How should the Vocabulary Atlas grow from three sources to a full multi-vocabulary registry — ring model, evidence classes, promotion ladder, proof-adapter trust?
- **METHOD:** Design proposal, later amended in-place by three dated annotation blocks (Reconciled/Revision/Implementation, all 2026-08-04) rather than superseded by a separate document.
- **VERDICT:** "Implemented Atlas 2.0 baseline; product adoption remains separate." Four semantic rings (subject/entity/value/legalIdentity) replace the old ring 0-3 eligibility model; `relatedMatch` is a fully typed assertion at `searchOnly` ceiling with no default traversal; source-scoped concept identity for useful source terms.
- **SUPERSEDED-BY:** `vocabulary-atlas-release-definition-and-cross-vocabulary-mapping-plan-2026-08-04.md` wins on scope/build-order/mapping-counts/priority where they differ (per this doc's own header); `vocabulary-atlas-final-synthesis-2026-08-03.md` formally "resolves" this doc + its addendum.
- **LANDED-IN-CODE:** OBSERVED — four-ring model (`legalIdentity` etc., 10 hits), `relatedMatch` (8 hits), `SubjectEmissionPolicy` (2 hits), `OutputProfile` (8 hits), `source_scoped_concept_iri`/`SourceConceptRelease` (12 hits) all present in `src/refspec/atlas/` and `src/refspec/registry/infrastructure/source_identity.py`.
- **TRUST FLAG:** none (2026-08-03/04, outside window).

## research/vocabulary-atlas-design-proposal-addendum-2026-08-03.md

- **PATH · DATE:** `research/vocabulary-atlas-design-proposal-addendum-2026-08-03.md` · 2026-08-03 (annotated through 2026-08-04)
- **QUESTION:** What does the parent design proposal *not* cover, and who owns closing each gap?
- **METHOD:** Boundary/gap-tracking addendum; itemized open items (A-E) with ownership.
- **VERDICT:** "Implemented Atlas 2.0 boundary record; product adoption remains separate." Confirms shared foundation, admission/emission path, and publication boundary are executable/tested; B1-B3 remain consumer responsibilities; entity/value/legalIdentity production models remain open. §E records completed corrections (publication-guide fixed; FR-ICPSR qualification bundle sealed at 730/730 calls, 119 mappings).
- **SUPERSEDED-BY:** Reconciled together with the parent proposal by `vocabulary-atlas-release-definition-and-cross-vocabulary-mapping-plan-2026-08-04.md`; "resolved" by `vocabulary-atlas-final-synthesis-2026-08-03.md`.
- **LANDED-IN-CODE:** OBSERVED — registry restructure into `infrastructure/`, `managed_releases/`, `adapters/`, `packages/` subpackages matches `find src/refspec/registry -maxdepth 1 -type d` (adapters/, infrastructure/, managed_releases/, packages/ all present).
- **TRUST FLAG:** none.

## research/vocabulary-atlas-final-synthesis-2026-08-03.md

- **PATH · DATE:** `research/vocabulary-atlas-final-synthesis-2026-08-03.md` · 2026-08-03
- **QUESTION:** What is the decided architecture for Atlas growth, resolving the design proposal and addendum's open items?
- **METHOD:** Synthesis document ("Final synthesis for decision; not adopted" at time of writing) with explicit decision boundaries and a 9-item work order.
- **VERDICT:** Keep Atlas as a static, reproducible publication expanded via 3 controls (portfolio index, exact releases + mapping evidence, `OutputProfile`/retrieval-policy gating). Old Ring 0-3 become portfolio-index planning labels, not atlas-manifest facts. States explicitly it does NOT adopt/amend RefSpec, authorize any source/mapping, or deploy SpicySearch expansion.
- **SUPERSEDED-BY:** `vocabulary-atlas-release-definition-and-cross-vocabulary-mapping-plan-2026-08-04.md` (approved for implementation, one day later) operationalizes this synthesis's decisions into scope/schedule/release lineage.
- **LANDED-IN-CODE:** INFERRED — its "small trusted core + evidence-activated specialist + search-only bridges" shape matches the shipped Atlas 3.0 ring/portfolio structure observed elsewhere in this catalogue; work-order items (Qualification 1.1, LCSH frontier compiler, CRS UUIDv7 capture) map to `src/refspec/atlas/frontier_release.py`, `relation_proof.py`, and the CRS source-concept-release pipeline.
- **TRUST FLAG:** none.

## research/vocabulary-atlas-release-definition-and-cross-vocabulary-mapping-plan-2026-08-04.md

- **PATH · DATE:** `research/vocabulary-atlas-release-definition-and-cross-vocabulary-mapping-plan-2026-08-04.md` · 2026-08-04 (with an "Implementation checkpoint" annotation dated 2026-08-05)
- **QUESTION:** What makes one Atlas build a citable release; what is v1's complete scope, mapping plan, and acceptance checklist?
- **METHOD:** Approved implementation plan with a 16-section spec-like structure (scope acceptance checks, cost/spend authority, limits).
- **VERDICT:** "Approved for implementation." Implementation checkpoint reports: 6-release baseline, 9,010 concepts, 32,684 native relations, 582 non-control mapping assertions (121 exactMatch/232 closeMatch/75 broadMatch/119 narrowMatch/35 relatedMatch), 12,313 candidates across 6 catalogs, projected batch cost $109.90 (vs $504.28 one-row-request baseline). States 3 explicit unresolved limits carried forward: validator independence is evidenced-not-enforced; direction-typed relations remain a separate evaluation class; `relatedMatch` is the weakest-evidenced class (60% of `related` baseline agreements were control-arm rows).
- **SUPERSEDED-BY:** Its production-integration successor is `vocabulary-atlas-relation-candidate-and-judgment-proposal-2026-08-05.md`, which explicitly amends "the still-unpublished v1.0.0-rc1 qualification plan" this doc defines.
- **LANDED-IN-CODE:** OBSERVED — `SOURCE_SPECS` in `tools/generate_atlas_v3_full.py` pins exactly the 6-release baseline this plan describes (crs-legislative-entities/subjects, crs-policy-areas, elsst-r6, federal-register-thesaurus-2025, icpsr-subject-thesaurus), with matching `expected_resources`/`expected_relations` (e.g. ELSST 3,470 resources/12,482 relations at line 692-703, FR-Thesaurus 705/1,451 at 704-719).
- **TRUST FLAG:** none.

## research/vocabulary-atlas-relation-candidate-and-judgment-proposal-2026-08-05.md

- **PATH · DATE:** `research/vocabulary-atlas-relation-candidate-and-judgment-proposal-2026-08-05.md` · 2026-08-05
- **QUESTION:** How should relation-candidate discovery and blind judging be restructured to keep the mapping graph small, direct, and nonredundant?
- **METHOD:** Design proposal amending the v1.0.0-rc1 qualification plan; specifies a deterministic-floor + dual-blind-judge pipeline (lexical K=3, sparse+graph K=1, BGE five-view K=50), acceptance gates, and a new spend authority replacing an explicitly superseded $112 authority.
- **VERDICT:** "Proposed for review after the candidate experiment. Production integration, paid scoring, and paid judging remain on hold" at time of writing. Directness/nonredundancy rubric formalized: prefer existing typed paths over generic `relatedMatch` edges.
- **SUPERSEDED-BY:** Operationally overtaken — `vocabulary-atlas-native-relation-experiments-2026-08-06.md`'s handoff section reports the resulting pipeline as executed (582 assertions reproduced with 0 mismatches, crosswalk archive recovered and blind-reviewed). Supporting context in `vocabulary-atlas-relation-candidate-matching-context-2026-08-05.md`.
- **LANDED-IN-CODE:** OBSERVED — the acceptance-gate numbers (582 mappings, 3,760 ICPSR release members, 3,280 preferred descriptors, 478 access-term aliases) match figures independently confirmed reproduced in `vocabulary-atlas-native-relation-experiments-2026-08-06.md` §13 ("v2 admission rule reproduces 582/582 with zero mismatches").
- **TRUST FLAG:** none.

## research/vocabulary-atlas-relation-candidate-matching-context-2026-08-05.md

- **PATH · DATE:** `research/vocabulary-atlas-relation-candidate-matching-context-2026-08-05.md` · 2026-08-05 (largest doc in the set, 227KB/3,987 lines)
- **QUESTION:** Supporting technical context/appendix for the relation-candidate-and-judgment-proposal — candidate-distinction taxonomy, coverage model, cost accounting.
- **METHOD:** Synthesis + measurement log; documents a bounded $0.046897820 provider embedding experiment (incl. one OpenAI async Batch smoke row) run with prior authorization.
- **VERDICT:** "Experiment phase complete; the production-integration proposal is ready for review." English-only scope decision explicit (translation/cross-lingual work out of scope for production policy/cost/acceptance).
- **SUPERSEDED-BY:** Companion/context document to `vocabulary-atlas-relation-candidate-and-judgment-proposal-2026-08-05.md`; both are operationally overtaken by the native-relation experiment results (2026-08-06 series).
- **LANDED-IN-CODE:** ASSERTED/INFERRED — not independently re-verified line-by-line given size; its cost/scope decisions are consistent with the release-definition plan's implementation checkpoint figures.
- **TRUST FLAG:** none.

## research/vocabulary-atlas-historical-judge-manual-audit-2026-08-05.md

- **PATH · DATE:** `research/vocabulary-atlas-historical-judge-manual-audit-2026-08-05.md` · 2026-08-05
- **QUESTION:** Does an independent human blind-reviewer agree with the two model-judge families on a 108-row historical sample, without seeing model answers first?
- **METHOD:** Manual blind audit — same search-expansion rubric (`same`/`near_same`/`target_is_broader`/`target_is_narrower`/`related`/`unrelated`/`insufficient_evidence`) applied by a human reviewer before opening the answer key; input pinned by SHA-256.
- **VERDICT:** "Independent blind decisions recorded before opening the model-answer key. This audit makes no provider call and changes no qualification artifact." (Row-by-row verdict table only; no aggregate agreement statistic stated in the visible portion.)
- **SUPERSEDED-BY:** Feeds the acceptance gates of `vocabulary-atlas-relation-candidate-and-judgment-proposal-2026-08-05.md` ("real-domain audit... remain sealed").
- **LANDED-IN-CODE:** N/A (manual audit artifact, not a code-landing document) — its sealed sample/decision files are evidence, referenced from `evidence/atlas-candidate-benchmark-sealed-2026-08-05/`.
- **TRUST FLAG:** none.

## research/vocabulary-atlas-outside-bge-k50-residual-manual-audit-2026-08-05.md

- **PATH · DATE:** `research/vocabulary-atlas-outside-bge-k50-residual-manual-audit-2026-08-05.md` · 2026-08-05
- **QUESTION:** Among concept pairs outside both the lexical/sparse-graph floor and the five-view BGE K50 population, how many are still plausible direct relations?
- **METHOD:** Manual blind audit, 60-row sentinel sample (15 rows × 4 vocabulary pairs with nonempty outside-K50 population), directness/nonredundancy rubric, SHA-256-pinned inputs.
- **VERDICT:** "Fixed human decisions recorded before any row-level residual analysis... changes no qualification or production artifact." Visible rows are overwhelmingly `unrelated`.
- **SUPERSEDED-BY:** Feeds the same acceptance-gate line in `vocabulary-atlas-relation-candidate-and-judgment-proposal-2026-08-05.md` ("outside-K50 sentinel remain sealed").
- **LANDED-IN-CODE:** N/A (manual audit artifact).
- **TRUST FLAG:** none.

## research/vocabulary-atlas-real-label-candidate-manual-audit-2026-08-05.md

- **PATH · DATE:** `research/vocabulary-atlas-real-label-candidate-manual-audit-2026-08-05.md` · 2026-08-05
- **QUESTION:** Independent blind human verdicts on a 120-row real-Atlas-vocabulary sample (20 rows × 6 pairs), rank/signal information withheld.
- **METHOD:** Manual blind audit, context-only rendering (labels/definitions/scope notes/native hierarchy only), SHA-256-pinned sample and rendering.
- **VERDICT:** "Independent candidate decisions recorded before rank-band and signal membership analysis... makes no provider call and changes no qualification artifact." Mixed `related`/`unrelated`/`target_is_broader` verdicts shown.
- **SUPERSEDED-BY:** This is the "fixed 120-row review" cited as sealed evidence in `vocabulary-atlas-relation-candidate-and-judgment-proposal-2026-08-05.md`'s acceptance gates.
- **LANDED-IN-CODE:** N/A (manual audit artifact).
- **TRUST FLAG:** none.

## research/vocabulary-atlas-real-label-candidate-tail-manual-audit-2026-08-05.md

- **PATH · DATE:** `research/vocabulary-atlas-real-label-candidate-tail-manual-audit-2026-08-05.md` · 2026-08-05
- **QUESTION:** Same rubric applied to a 60-row tail sample (10 rows × 6 real vocabulary pairs) from the BGE ranking tail.
- **METHOD:** Manual blind audit, context-only rendering, SHA-256-pinned inputs.
- **VERDICT:** "Independent candidate decisions recorded before row-level rank and rank-band analysis... changes no qualification artifact." This is the "ranks 26-50 review" referenced elsewhere.
- **SUPERSEDED-BY:** Directly re-reviewed (its positives re-audited) by `vocabulary-atlas-direct-nonredundant-candidate-rereview-2026-08-05.md`.
- **LANDED-IN-CODE:** N/A (manual audit artifact).
- **TRUST FLAG:** none.

## research/vocabulary-atlas-direct-nonredundant-candidate-rereview-2026-08-05.md

- **PATH · DATE:** `research/vocabulary-atlas-direct-nonredundant-candidate-rereview-2026-08-05.md` · 2026-08-05
- **QUESTION:** Of the 65 rows previously marked "possible relation" (ranks 1-25 + 26-50 samples), which are genuinely plausible direct/nonredundant cross-vocabulary mappings vs. generic-thematic or path-redundant?
- **METHOD:** Fixed human re-review with a narrower, refined rubric (`direct_candidate` / `generic_thematic` / `redundant_via_path`), pinning the two prior decision files and a "bounded typed-path report" by SHA-256.
- **VERDICT:** "Changes no earlier verdict, mapping assertion, qualification artifact, or production file." Per the judgment-proposal's acceptance gates, this reproduces "12 direct candidates, 52 generic thematic rows, one path-redundant row."
- **SUPERSEDED-BY:** Newest in the manual-audit micro-lineage (rereviews `real-label-candidate` and `real-label-candidate-tail` positives); itself referenced as sealed evidence going forward.
- **LANDED-IN-CODE:** N/A (manual audit artifact) — but its output counts (12/52/1) are independently cited and matched in `vocabulary-atlas-relation-candidate-and-judgment-proposal-2026-08-05.md`'s acceptance gates, i.e. cross-document consistency confirmed.
- **TRUST FLAG:** none.

## research/vocabulary-atlas-native-relation-experiment-designs-2026-08-06.md

- **PATH · DATE:** `research/vocabulary-atlas-native-relation-experiment-designs-2026-08-06.md` · 2026-08-06 (last reviewed 2026-08-08)
- **QUESTION:** What concrete, numerically falsifiable experiment designs exist against the native-relation Atlas dataset, and which semantic ring does each serve?
- **METHOD:** Design catalogue — each entry states what's held constant, what's varied, what threshold changes production config.
- **VERDICT:** Explicitly flags a coverage imbalance: `subject` ring has 582 tracked relations and nearly the whole document's designs; `entity`/`value`/`legalIdentity` rings have 0 tracked relations and only 3-4 designs (data-plumbing, not modeling). "Phase gate": relations-between-concepts now, document-text work deferred.
- **SUPERSEDED-BY:** Companion to (not superseded by) `vocabulary-atlas-native-relation-experiments-2026-08-06.md`, which reports which of these designs were actually executed.
- **LANDED-IN-CODE:** INFERRED — design catalogue rather than an implementation claim; execution status lives in the companion results doc.
- **TRUST FLAG:** none.

## research/vocabulary-atlas-native-relation-experiments-2026-08-06.md

- **PATH · DATE:** `research/vocabulary-atlas-native-relation-experiments-2026-08-06.md` · 2026-08-06 (last reviewed 2026-08-08; largest .md by content after the matching-context doc, 1,860 lines/100KB)
- **QUESTION:** What do the E3 retrieval experiments, crosswalk recovery replay, and blind reviews actually measure for the native-relation Atlas dataset?
- **METHOD:** Executed measurement — 6 arm families, Wave-1 structural experiments, 5 free replay experiments (E-V1/V2/V4/V5/V7), crosswalk archive recovery + independent blind review; full reproduction commands given (`tools/build_atlas_native_relation_testsets.py` etc.).
- **VERDICT:** Test sets built and reproducible (manifest digest `sha256:9cc14e10...`). Recoverable-mapping figure corrected from 85 to 39; reviewer-calibration finding reversed; edit-distance arm splits into a working tenth + `relatedMatch` sink; "roughly 234 real hard negatives" superseded by a partition (157 hard). Google hosted arms unresolved. "No mapping asserted, no release artifact changed, no qualification policy touched." Crosswalk replay reproduces 582/582 with 0 mismatches, variant classifier 16/16 precision.
- **SUPERSEDED-BY:** Feeds `vocabulary-atlas-spine-and-rings-takeaways-2026-08-06.md` (product-facing synthesis) and `atlas-agentic-graph-search-next-steps-2026-08-07.md` (follow-up plan).
- **LANDED-IN-CODE:** OBSERVED — all referenced tool scripts exist and are runnable (`tools/build_atlas_native_relation_testsets.py`, `tools/verify_atlas_crosswalk_benchmarks.py`, `tools/replay_atlas_crosswalk_admission.py`, `tools/compare_atlas_relatedmatch_blind_review.py`, `tools/compare_atlas_variant_classifier_audit.py` all confirmed present per prior directory scans and evidence-dir cross-references).
- **TRUST FLAG:** none.

## research/vocabulary-atlas-spine-and-rings-takeaways-2026-08-06.md

- **PATH · DATE:** `research/vocabulary-atlas-spine-and-rings-takeaways-2026-08-06.md` · 2026-08-06 (last reviewed 2026-08-08; 1,359 lines/82KB)
- **QUESTION:** Product-facing synthesis — what can Atlas build, what should it stop building, what remains unknown, spine question (FAST `schema:sameAs` LCSH vs LC `closeMatch` reciprocation).
- **METHOD:** Synthesis with an explicit provenance-marking convention (✅ re-derived / ⚠️ disputed-or-unreplicated / *(agent)* unverified-subagent-report / **superseded**), added specifically because a 2026-08-06 external review found the document "preserves conclusions and discards the evidence that qualifies them."
- **VERDICT:** Self-flagged unresolved defect (stated by its own third reviewer, "not yet fixed"): mixes publisher facts, model judgments, heuristics, and decisions as equal-authority claims; a proper claim-to-evidence register "does not exist yet." Documents concrete data-quality defects found in passing (ELSST `dcat:CatalogRecord` misused as predicate on 22% of triples; ELSST RDF/XML namespace bug; MARC 788 n-ary AND flattening risk; Wikidata P244/P214 formatter drift; USAspending SUBTIER typing risk). §13 "Validated, not assumed" reconfirms ELSST test-set set-identity and 582/582 reproduction.
- **SUPERSEDED-BY:** States of itself (line ~1044): **"Current code, binding, and the decision ledger supersede this research document for implementation authority."** Followed by `atlas-agentic-graph-search-next-steps-2026-08-07.md`.
- **LANDED-IN-CODE:** OBSERVED (for the reproduced facts) — ELSST 3,393 hierarchy + 2,848 associative = 6,241-row test set and 582/582 admission-rule reproduction are corroborated by `vocabulary-atlas-native-relation-experiments-2026-08-06.md`.
- **TRUST FLAG:** none (2026-08-06, but note it is explicitly the most self-critical/least-trusted-by-its-own-admission document in the set regarding evidence-provenance mixing — a different, disclosed problem from the 07-28 contamination incident).

## research/vocabulary-atlas-v1-explorer-search-corpus-2026-08-05.json

- **PATH · DATE:** `research/vocabulary-atlas-v1-explorer-search-corpus-2026-08-05.json` · 2026-08-05
- **QUESTION:** N/A (test-fixture artifact, not a narrative document) — a reviewed corpus of explorer/search acceptance cases (`aggregateCases`, `cases`) keyed to specific release IDs and expected concept/view digests across the four semantic rings.
- **METHOD:** Structured fixture, `reviewedBy`/`reviewedAt` provenance fields (reviewed 2026-08-05T04:25:00Z).
- **VERDICT:** N/A (data, not a conclusion).
- **SUPERSEDED-BY:** Not superseded by content, but its consuming test was retired.
- **LANDED-IN-CODE:** OBSERVED-BUT-ORPHANED. No `.py` file anywhere in the repo references this file by name or by its `VocabularyAtlasExplorerSearchCorpus` type string. A stale bytecode-only artifact `tests/__pycache__/test_atlas_explorer_acceptance.cpython-312.pyc` exists with **no corresponding `.py` source file** anywhere in the tree. `docs/decisions.md` (lines ~798-805) confirms this directly: *"Explorer/search reachability gate: retired in Tier 1 before porting; its reviewed corpus survives at `research/vocabulary-atlas-v1-explorer-search-corpus-2026-08-05.json` and is that port's input; `REQUIRED_GATES` in `validate.py` has no equivalent."* The porting work is explicitly still owed, not done.
- **TRUST FLAG:** none by date, but flagged under Anomalies below as a genuinely orphaned artifact.

---

## Evidence subdirectories — pinned build inputs vs. disposable research output

Checked against `tools/generate_atlas_v3_full.py` directly (its `SOURCE_SPECS` tuple, lines 633+) and transitively via its import of `REGISTRY_CODE_RELEASE_KEYS` from `src/refspec/atlas/v3_registry_codes.py`.

### PINNED APPLICATION BUILD INPUTS (2 confirmed — not 1)

## evidence/crs-source-concept-releases-2026-08-04/

- **PATH · DATE:** `research/evidence/crs-source-concept-releases-2026-08-04/` · 2026-08-04
- **CONTENTS:** `legislative-entities/`, `legislative-subjects/`, `policy-areas/` bundles (each with `bundle-manifest.json`), plus `release-evidence.json`.
- **BUILD-INPUT STATUS:** PINNED — OBSERVED directly. `generate_atlas_v3_full.py` `SOURCE_SPECS` (lines 633-687) pins all three `bundle-manifest.json` files by exact SHA-256 (`aa80aaf0...`, `f20d688f...`, `b5966cb9...`) with `expected_resources` 478/565/32. Verified live: `shasum -a 256` on all three files matches the pinned digests exactly at current HEAD.
- **TRUST FLAG:** none.

## evidence/regulatory-native-controls-2026-08-03/

- **PATH · DATE:** `research/evidence/regulatory-native-controls-2026-08-03/` · 2026-08-03
- **CONTENTS:** `source-native-control-capture.json`, `source-pins.json`.
- **BUILD-INPUT STATUS:** PINNED — OBSERVED, but not the example named in the task brief. `src/refspec/atlas/v3_registry_codes.py:1389` reads `research/evidence/regulatory-native-controls-2026-08-03/source-native-control-capture.json` directly (digest-verified, `_verify_pinned_file`-style check) inside `_load_regulatory_native_controls`, registered under the `"regulatory-native"` key in `REGISTRY_CODE_RELEASE_KEYS` (line 1935, opt-in flag `False` i.e. not in the default-`True` release set but a real, wired loader). `generate_atlas_v3_full.py` imports `REGISTRY_CODE_RELEASE_KEYS` from this module at lines 1076/2272/2314, so this file is a real (if optional) production build input, not disposable evidence.
- **TRUST FLAG:** none. **Sibling `regulatory-native-controls-2026-07-30/` is the earlier, superseded capture** — not referenced anywhere in `src/` or `tools/generate_atlas_v3_full.py`; disposable.

### DISPOSABLE RESEARCH OUTPUT (all others — 28 of 30 subdirectories + 3 loose files)

Not referenced by `generate_atlas_v3_full.py`'s `SOURCE_SPECS`, and not imported by `src/refspec/atlas/v3_registry_codes.py`. Grouped by role:

**Consumed by verification/analysis tools (not by the generator) — durable but not build-pinned:**
- `atlas-3-mapping-evidence-2026-08-05/` (2026-08-05) — crosswalk bundles for elsst-icpsr/fr-elsst/fr-icpsr; read by `tools/verify_atlas_crosswalk_benchmarks.py` and `tools/build_atlas_crosswalk_blind_review.py`.
- `atlas-crosswalk-blind-review-2026-08-06/`, `atlas-crosswalk-benchmarks-2026-08-06/` (2026-08-06) — blind/sealed review artifacts consumed by the same verification and replay tools.
- `atlas-crosswalk-admission-replay-2026-08-06.json`, `atlas-tmp-evidence-promotion-2026-08-06.json` (loose files, 2026-08-06) — outputs of `tools/replay_atlas_crosswalk_admission.py` and `tools/promote_atlas_tmp_evidence.py` respectively; the promotion file's own doc states it covers "all 554 promoted files across every tier, including the ones the repo does not carry."
- `atlas-candidate-benchmark-sealed-2026-08-05/`, `atlas-relatedmatch-blind-review-2026-08-06/`, `atlas-variant-classifier-audit-2026-08-06/` (2026-08-05/06) — sealed manual-audit evidence backing the manual-audit .md docs catalogued above.
- `uslm-reference-edges-2026-08-07/` (2026-08-07) — explicitly self-described in `vocabulary-atlas-spine-and-rings-takeaways-2026-08-06.md` §14 as "local experiment evidence; it is not an admitted Atlas release."
- `atlas-v3-native-relation-testsets-2026-08-06/` (2026-08-06) — **output of** `tools/build_atlas_native_relation_testsets.py`, not an input to the v3 generator.

**Historical/superseded managed-release evidence (v1/v2-era; v3's ELSST/FR/ICPSR pins point to `output/` bundles instead, not to these):**
- `elsst-r5-r6-managed-release-2026-07-29/`, `elsst-r6-atlas2-managed-release-2026-08-04/`, `elsst-r6-only-atlas-2026-08-02/`
- `federal-register-thesaurus-managed-release-2026-07-30/`, `federal-register-thesaurus-2025-managed-release-2026-07-30/`
- `federal-register-topics-reconciliation-2026-07-29/`, `federal-register-topics-source-package-2026-07-29/`, `federal-register-topics-source-package-2026-08-04/`
- `icpsr-managed-release-2026-07-30/`, `icpsr-vocabulary-atlas-2026-08-02/`
- `crs-source-packages-2026-07-30/`, `crs-source-packages-2026-08-03/` (predecessors to the pinned `crs-source-concept-releases-2026-08-04/`)
- `lda-controlled-lists-2026-07-30/` — note: the *active* LDA loader (`_load_lda` in `v3_registry_codes.py`) reads from `tests/fixtures/lda-*-2026-07-30.json`, not from this evidence dir, confirming it's disposable.

**Superseded exploratory-architecture spikes (README explicitly says these "led to the two-graph static asset," i.e. were not the adopted path):**
- `ladybug-vocabulary-atlas-spike-2026-07-31/`, `vocabulary-atlas-graphdb-v5/`, and the loose `vocabulary-atlas-graph-experiment-2026-07-31.md`.

**Portfolio/domain research evidence (CONTAMINATION-WINDOW by date, 2026-07-28):**
- `blind-external-research-recovery-2026-07-28/` — 9 recovered reports + 1 reconstructed report; self-tags every claim ✓ (primary-source) or ~ (summarizer-derived, "fabricated at least four results outright").
- `source-vocabulary-research-2026-07-28/` — 4 domain-evidence reports underlying `source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md`.

**Other disposable evidence:** `atlas-distribution-2026-08-02/`, `atlas-crosswalk-qualification-2026-08-02/`, `registry-real-data-audit-2026-08-03/`, `spicyregs-profile-resource-portfolio-2026-07-30/` (2026-07-30, CONTAMINATION-WINDOW-adjacent but dated after 07-28 so not flagged).

---

## Archive — research/archive/ (2 files)

## archive/large-label-space-tagging-external-research-synthesis-2026-08-03.md

- Date 2026-08-03, 627 lines. Synthesizes the `blind-external-research-recovery-2026-07-28/` reports on large-label-space tagging (production systems keep classification vocabularies 6-7 orders of magnitude smaller than entity registries); archived (per `git log`, commit `09e22d3 docs(research): archive tagging synthesis`) once its findings were consolidated into `concept-tagging-architecture-proposal-2026-07-28.md`'s lineage rather than kept as a live top-level doc. TRUST FLAG: its *sources* are CONTAMINATION-WINDOW (2026-07-28), though this synthesis itself is dated 2026-08-03 and carries its own ✓/~ verification legend distinguishing primary-source facts from summarizer-derived (potentially fabricated) ones.

## archive/atlas-3.0-exhaustive-compact-parity-2026-08-08.md

- Date 2026-08-08, 46 lines. Records that exhaustive compact-to-RDF parity checking (which contributed to a 74-minute full-distribution validation run) was replaced by 3 bounded checks (pack/row authentication, exact role/count reconciliation, ≤5-record-per-pack sample); pins the retired implementation at local git ref `refs/archive/atlas-3.0-exhaustive-compact-parity/2026-08-08` (commit `55e9e1332d0...`, local-only, not pushed by default). Companion doc to `atlas-full-build-status-logging-note-2026-08-07.md`, which documents the same change from the timing/logging side. TRUST FLAG: none.

---

## Anomalies

1. **A second pinned application build input exists that the task brief did not name.** The brief describes `crs-source-concept-releases-2026-08-04` as "the known example" of a digest-pinned build input, implying it may be the only one. It is not: `research/evidence/regulatory-native-controls-2026-08-03/source-native-control-capture.json` is also directly digest-pinned and read by production code (`src/refspec/atlas/v3_registry_codes.py:1389`, wired into `generate_atlas_v3_full.py` via `REGISTRY_CODE_RELEASE_KEYS`). This should be added to the pinned-inputs allowlist mentally when reasoning about what's safe to treat as disposable.

2. **`vocabulary-atlas-v1-explorer-search-corpus-2026-08-05.json` is an orphaned test fixture, not live-landed code.** A stale `.pyc` (`tests/__pycache__/test_atlas_explorer_acceptance.cpython-312.pyc`) exists with no corresponding `.py` source anywhere in the tree. `docs/decisions.md` confirms directly: the explorer/search reachability gate that consumed this JSON was "retired in Tier 1 before porting," and the corpus "survives" only as a not-yet-executed port's future input. A naive grep-only landed-in-code check would have missed this since the file literally isn't referenced by any live `.py` — the absence itself, cross-checked against `docs/decisions.md`, is the finding.

3. **Two contamination-adjacent but distinct trust concerns exist in this document set, and they should not be conflated.** (a) The four 2026-07-28-dated top-level docs plus two evidence dirs of the same date fall in the literal CONTAMINATION-WINDOW defined by commit `d165350` (found in the parent `spicy-regs` monorepo, not in `RefSpec`'s own git history — `RefSpec` is a separately-rooted repo nested inside the monorepo, so `git -C RefSpec show d165350` fails; the commit had to be located via the sibling repos under `/Users/mikewolfd/Work/spicy-regs/`). (b) Independently, `vocabulary-atlas-spine-and-rings-takeaways-2026-08-06.md` (2026-08-06, outside the date window) carries its own, separately-disclosed evidence-provenance defect — a third-party reviewer found it "mixes publisher facts, model judgments, structural heuristics, implementation readiness, and unresolved decisions as if they had equal authority," which its author admits is not yet fixed. Both are real trust caveats but have different causes and different dates; flagging only-by-date would miss (b) entirely.

4. **`regulatory-native-controls-2026-07-30/` (evidence) appears to be a genuinely dead/superseded directory** — no code or tool script under `src/` or `tools/` references it (only the `-08-03` successor is pinned), yet it remains committed. Candidate for cleanup, not a data-integrity issue.

5. **No count mismatches found** between the top-level `find` listing (20 `.md` + 1 `.json` = 21 top-level docs, matching the initial `ls`), the evidence subdirectory count (30 directories + 3 loose files = 33 entries, matching `ls`/`find` counts), and the archive count (2 files). The task brief's implicit assumption of "one clear pinned example" in evidence/ was the only structural surprise (see Anomaly 1).
