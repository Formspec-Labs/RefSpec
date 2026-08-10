# Research catalogue — every experiment, approach, and research surface across the five repos

Compiled 2026-08-10 (late) from five parallel read-only traces, one per surface, each citing the
HEAD it measured against; load-bearing counts and headline metrics were independently re-verified
by the compiling session before inclusion. Companion to `data-flow-v2-artifact.html` (the workspace
map) and `PLAN.md` (the plan). **This file is the delete-gate for P0's cut policy**: before deleting
any research surface, check what it settled here — negative results live mostly in the code and
receipts being deleted.

HEADs measured: RefSpec `08001c6` · SpicySearch `88ada94` · spicy-regs `ac9a25d` (archive branch) ·
DocSpec `7e3d0f2` · RuleSpec `9be401b`. Every repo but DocSpec moved *during* the tracing session;
treat all SHAs as timestamps.

**This file is the synthesis; the detail layer is `traces/`** — the five tracer catalogues preserved
verbatim: per-tool purpose/class/outputs for all 84 tool scripts, per-experiment arms-and-metrics
tables, per-document question/method/verdict entries for all 20 research docs, per-module importer
counts, and each tracer's own Anomalies section. When a §-entry here feels compressed, the full
entry is there: `trace-refspec-research-docs.md` · `trace-refspec-tools.md` ·
`trace-spicysearch-experiments.md` · `trace-spicyregs-surfaces.md` · `trace-docspec-rulespec.md`.

Trust legend: **CW** = contamination-window (dated ≤ 2026-07-28; untrustworthy without re-check —
commit `d165350`). **CW-corrected** = in the window but carries its own audited in-place correction;
the *corrected* figures are trustworthy, the retracted ones are struck through in the source.

---

## 1. Settled questions — do not re-run these

The single most valuable output of the trace. Each was measured, concluded, and is preserved here
precisely because the artifacts that hold the conclusion are deletion candidates.

| Question | Verdict | Where it lives |
|---|---|---|
| Does an agency prior (CFR-part → agency boost) help ranking? | **Unfixable in the current score algebra.** The lexical channel score is a pure RRF rank transform — encodes rank, never margin. Any safe constant is bounded at w < 0.0012887, at which point it moves nothing. No constant is both safe and useful; retuning cannot reach a useful regime. The 114-variant benchmark cannot measure it at all (0/82 records yield an agency key). | `spicysearch/evaluation/experiments/2026-08-02-agency-priors-v1` |
| Does global dense+lexical fusion beat the spine? | **The fusion trap, reproduced**: global weighted RRF lifts mean nDCG (0.7644 → 0.8592) but *drops* pass count 61 → 47. Scoped fusion is the answer (below). | `2026-08-01-dense-dev-bge-v1` |
| Does whole-body indexing work? | **No — it is a recall disaster, not an ordering nit.** At 200 docs, recall@10 43.8% baseline vs 81.2% passage-chunked; "half the queries whose answer the index physically holds do not get it back." Root cause: BM25 length normalization + trigram-cosine self-normalization, two independent mechanisms. | `2026-08-02-body-length-penalty-v1`, `2026-08-02-passage-chunking-native-v1` |
| Does within-vocabulary expansion help (over co-assignment edges)? | **Resolver alone: +2 passes (61→63). Expansion adds nothing** (−0.0011 nDCG) and caused one −0.1196 regression. Measured over the SYNTHETIC atlas only; the record itself forbids quoting it as the real-thesaurus answer. 7 numbered self-corrections (C1–C7) from adversarial review. | `2026-08-02-within-vocab-expansion-v1` |
| Should USearch ANN replace exact dense concept search? | **REJECT** — every memory-saving config loses 21–74% of exact top-12 recall. (CW-corrected: this doc is the fabrication incident's ground zero — the "near-degenerate concept space" claim was retracted in place, margin corrected 0.029 → +0.2173.) | `spicy-regs/docs/evidence/usearch-ann-benchmark-2026-07-28.md`, `tools/benchmark_usearch_index.py` |
| Does hyperbolic subsumption (HiT lineage) beat the gold oracle? | **FAILS** — three pretrained checkpoints score below the adoption gate *and below a constant predictor*. Fine-tune step deliberately skipped. | `docs/evidence/hyperbolic-subsumption-prototype-2026-07-28.md` (CW), `tools/prototype_hyperbolic_subsumption.py` |
| Should CiteURL replace/augment the citation grammars? | **Do not wire CiteURL** — extend the two owned grammars instead. | `docs/evidence/citation-bakeoff-2026-08-02.md`, `tools/run_citation_bakeoff.py` (46 tests) |
| Should extraction tooling change (HTML/XML/PDF)? | **"Keep what we have, everywhere. Adopt nothing"** — pypdf within 2% of modern alternatives across 18 real docs; Chonkie conditionally, behind the segmentation interface, for a retrieval reason that does not currently exist. This is the literal source of the pymupdf/pypdf pin comments in `pyproject.toml`. | `docs/evidence/extraction-tooling-bakeoff-2026-08-02.md` |
| Should RefSpec adopt the Axiom ecosystem? | **Adopt nothing now**; watch axiom-corpus and receipt; reuse ideas without the stack. Followed to the letter (zero axiom refs in src). | `RefSpec/research/axiom-ecosystem-analysis-2026-07-28.md` (CW) |
| Which graph engine for the ontology graph? | Plain DuckDB stays interactive to 1M edges; DuckPGQ variable-length paths broken on that build; Kuzu fast but a second engine to sync. Self-flagged "Historical — rerun before reporting current counts." | `docs/evidence/graph-engine-bakeoff-2026-07-24/` (CW) |
| Why did the segmentation baseline break (1,302 → 1,296)? | **Environmental, not code** — identical code, interpreter-version cause; a prior commit attribution explicitly withdrawn. This is why `requires-python = ">=3.12,<3.13"` is pinned. | `docs/evidence/document-segmentation-remeasurement-2026-08-02` |
| Is the old body-retrieval corpus meaningful? | No — 34 docs / median Jaccard 0.13 made recall@50 = 1.0 "by arithmetic rather than by merit." Replaced by 993 real-body FR docs at 0.2947 median Jaccard (one program: 50 CFR 17 / ESA). | `docs/evidence/body-retrieval-corpus-2026-08-02.md`, `corpora/body_retrieval_corpus.py` |
| What makes two automated verdicts independent? | Closed at **five pairwise-distinct axes** (validator actor, independence group, provider, model ID, sealed response artifact) — the fifth added 2026-08-10 after a reviewer found a decoy-value hole, root-caused to a general CUE→SHACL compiler bug, fixed generally (19 shape files gained `sh:maxCount 1`). | `rulespec/constraints/analysis/machine-adjudication.cue`, `spec/rkaf-refspec.md` |

## 2. The decoupled roster — production vs planned-production vs experiment tooling

**Rule: classification is by consumption path, never by test coverage.** A tool is PRODUCTION iff
the build/publish path consumes its output or it gates that path *today*. PLANNED-PRODUCTION iff a
decision record or structural evidence assigns it a production destination it has not reached —
each entry names its wiring gap, and each gap is a work item. Everything else is
EXPERIMENT / VALIDATION tooling: its tests travel with it, and **tests do not promote it**. This
split exists so P0 item 4 packages the right set and the cut policy deletes from the right set.

### PRODUCTION — wired today

- **RefSpec (9 of 58 tools)**: `generate_model` · `generate_atlas_index` ·
  `generate_resource_catalog` · `generate_atlas_v3_registry_coverage` ·
  `generate_atlas_v3_registry_descriptors` · `generate_crs_source_concept_releases` ·
  `verify_atlas_source_fidelity` · `verify_registry_audit` · `registry_real_data_pytest_plugin`
  (transitively wired). Plus the `pyproject` console scripts living in `src/` (e.g.
  `refspec-build-atlas-parquet-view`).
- **RuleSpec (~19 of 31)**: the CI-wired validator set (all 14 audit-validators incl.
  `ci_validate`, `vocab_audit`, `codegen_drift_audit`, `validate_negatives`,
  `rulespec_release`, `extrapolation_release_v2`, `reference_release_digest`) plus the
  production producers `constraints_compile`, `studio_schemas_derive_manifest`, `version_sync`,
  `repin_contract_digest`, and `conformance_lib` as shared support. **RuleSpec is the healthy
  reference**: its production tools are wired and its fixture builders are unambiguously test
  infrastructure.
- **DocSpec (3 of 7)**: `generate_ownership_manifest` · `generate_scale_profile_schema` ·
  `generate_archive_manifest` — governance generators for committed artifacts.
- **SpicyRegs (0 of 26 tools)**: production lives in `src/` (rollups, transforms, releases,
  ontology); not one `tools/` script is wired.
- **SpicySearch**: production is `src/spicysearch` core (engine, snapshot, CLI, API, the three
  format readers); the experiments/validation packages are not it.

### PLANNED PRODUCTION — production-destined, wiring gap named

| Tool | Production role / evidence | The gap |
|---|---|---|
| `generate_atlas_v3_full.py` (RefSpec, 10,294 ln) | **THE Atlas 3.0 distribution builder** | no Makefile/CI invocation at all — P0 item 6's first customer |
| `build_registry_source_manifest.py` (RefSpec) | generates `sources.json`, a *required input* of wired `verify_registry_audit` | generator unwired; the committed manifest can silently drift |
| `capture_regulatory_native_controls.py` (RefSpec) | generator/verifier of pinned build input #2 | zero references anywhere |
| `package_federal_register_thesaurus_2025.py` (RefSpec) | built the pinned FR thesaurus vintage | per-vintage rebuild path undocumented |
| `reseal_elsst_managed_release.py` (RefSpec) | maintenance of the pinned ELSST production bundle | zero references — *borderline; confirm intent before wiring* |
| `build_usc_act_index_artifact.py` + `build_usc_source_credit_artifact.py` (SpicyRegs) | outputs read at runtime by `ontology/act_index.py` | unwired; digests stamped at build, never verified at read |
| `build_agency_crosswalk_artifact.py` + `build_date_event_artifact.py` (SpicyRegs) | "built locally, digest-pinned, unpublished" pending a blocked publication chain | publication blocked; `build_date_event` is the one file that compiles upstream unmodified (V2) |
| `generate_source_profile_artifacts.py` (SpicyRegs) | regenerates the two policy JSONs — including `profile-resource-applicability-v0.json`, the pin that drifted in V3 | determinism-gate framing but absent from CI/pre-commit |
| `project_document_to_rkaf.py` (SpicyRegs) | the RKAF projection CLI; manifest disposition "reimplement → Rulespec Extrapolator" | migration deliberately deferred (P0) |
| `export_selection_ledger.py` (DocSpec) | the exit half of the absent SpicySearch→DocSpec edge | never run; no reader exists on the other side |
| *(feature, not a tool)* passage-chunking enablement (SpicySearch) | recall@10 doubles, production-shaped | no published snapshot enables it |

### EXPERIMENT & VALIDATION — never packaged; tests do not promote

- **RefSpec**: the remaining ~44 `tools/` scripts (every `benchmark_*` / `analyze_*` /
  `optimize_*` / `compare_*` / blind-review builder, the `run_atlas_qualification` cluster,
  `promote_atlas_tmp_evidence`, `build_eurovoc_organization_experiment`,
  `extract_uslm_reference_edges` — self-described "local experiment evidence, not an admitted
  release" — `export_registry_claim_releases`, `fetch_registry_source_via_zyte`) plus the `src/`
  research modules (qualification cluster 13.7k ln, `candidate_retrieval`, the EuroVoc
  experiment). **The boundary is already test-enforced** (`test_atlas_index.py:490-497` fails if
  offline tooling enters the pinned index closure) — extend that pattern; don't invent one.
- **SpicyRegs**: all 15 `corpora/` modules — `pyproject` entry points notwithstanding — and 22 of
  26 tools (everything except the six planned-production rows above). The holdout/gold machinery
  (`draw_holdout`, `draw_search_holdout`, `draft_holdout_gold`, `build_gold_adjudication_input`,
  `build_search_holdout_exam_release`) is **standing validation infrastructure**: keep it, but it
  is not product path. `fuse_concept_registries` is migration-only by its own docstring — delete
  when the migration completes.
- **DocSpec**: the `fr_mirrulations_*` campaign harness — flagged in the map for bypassing
  `docspec run`; if qualification becomes a product feature it moves to planned-production *by
  decision*, not by default. `predecessor_code_fingerprints.py` is already on P0's cut list.
- **SpicySearch**: `src/spicysearch/experiments/` (21 files, per-campaign scaffolding) and
  `validation/` (9 files — standing infrastructure: the sealed-holdout machinery and benchmark
  harness).
- **Dead now** (zero refs, no destination — delete list): `build_atlas_parquet_view.py`
  (superseded wrapper), the crosswalk blind-review build/compare pair (its two sibling pipelines
  are tested; this one isn't — fix or delete), the 6 uncoupled SpicyRegs scripts (verdicts already
  harvested into §1), `regulatory-native-controls-2026-07-30/`.

**Packaging implication (P0 item 4)**: the packages expose the PRODUCTION roster only.
Planned-production entries are wiring work items — not package members until their gap closes.
Experiment tooling stays repo-local and never enters the package surface.

## 3. Adopted and serving — the chain the map missed

**Scoped dense fusion is adopted, sealed, and in production serving.** The map's SpicySearch card
does not mention this at all. The chain, fully receipted:

1. `2026-08-01-dense-dev-bge-v1` — dense arm built (bge-base-en-v1.5): alone 0.5002, global fusion
   0.8592 but −14 passes → scopes the next step.
2. `2026-08-01-dense-dev-scoped-fusion-bge-v1` — **scoped fusion** (fuse only the 30/114
   unanchored-ranked variants): nDCG 0.8096, g3r 0.8997, P@5 0.8120, **62/114** — first arm to beat
   the spine on all three metrics. Config frozen (`config-freeze.json`).
3. `evaluation/holdout-labeling/` — sealed one-shot adoption gate: 657 real holdout queries, two
   independent LLM judge families + partial third, 11,768 labeled pairs, $175.10 spend, pre-registered
   criteria. **Verdict `BEATEN: TRUE`** (strict wins on P@5 and nDCG@10, tie on g3r@20). The tool
   refuses to run twice.
4. `2026-08-02-semantic-serving-v1` — the production serving path reproduces the judged configuration
   with **0.0000 delta on every metric** (62/114, routing surface identical).

Reproducibility caveat on record: `dense_dev_alone` read 0.4823 vs 0.5002 across two runs with
byte-identical inputs — numeric-environment jitter in near-tie cosine orderings, documented, not a bug.

**Pending measured lever, not yet enabled:** passage chunking is production-shaped
(`passage-aligned-chunk-v1`, run through the real engine — "the passage arm is now the product, not a
simulation of it") but no published snapshot turns it on. Recall@10 doubles when it does. This is
plausibly a larger product win than the concept lane.

## 4. The front-door correction — governs every quality number

`2026-08-02-query-front-door-product-path-v1`: "Every accuracy figure this campaign has quoted
describes a request no product caller can construct." Harness 61/114 vs **front_door 9/114
(nDCG 0.3589)**. 54/114 variants need a UI affordance, not a text box — 39 of the harness's 61
passes come from those 54. On the 60 text-expressible variants the real gap is 22/60 vs 6/60.
`exact_phrase` moves nothing; `concept_candidate` moves 2/114 and cannot fire in production (no
atlas present); `connections` costs −15 passes but none text-reachable. Also fixed a 16.9× latency
bug found on the real corpus (p50 193s → 11.5s — the engine tokenized the whole release per query).
Rule going forward: quote harness and front_door numbers **paired, never harness alone**.

## 5. RefSpec — the vocabulary-atlas research programme (20 docs, lineage clean)

Supersession chain, oldest → operative:
`concept-tagging-architecture-proposal` + `source-document-type-matrix` +
`source-vocabulary-ontology-thesaurus-catalog` (all 2026-07-28, **CW**)
→ `vocabulary-atlas-design-proposal` + addendum (08-03; four semantic rings, relatedMatch typed at
searchOnly, source-scoped identity — **landed in code, verified**)
→ `vocabulary-atlas-final-synthesis` (08-03)
→ `vocabulary-atlas-release-definition-and-cross-vocabulary-mapping-plan` (08-04, **approved**; the
6-release baseline it defines is byte-pinned in `generate_atlas_v3_full.py` `SOURCE_SPECS` — verified)
→ relation-candidate/judgment proposal + matching context (08-05)
→ **five sealed manual blind audits** (08-05: historical-judge 108 rows, outside-K50 60 rows,
real-label 120 rows, tail 60 rows, direct/nonredundant re-review → 12 direct / 52 generic / 1
redundant) — SHA-pinned samples, human verdicts recorded before opening the model key
→ `native-relation-experiment-designs` + `native-relation-experiments` (08-06; 582/582 crosswalk
replay with 0 mismatches; recoverable-mappings corrected 85 → 39; test-set manifest digest pinned)
→ `spine-and-rings-takeaways` (08-06; carries its own admitted, unfixed defect: mixes publisher
facts, model judgments, and decisions at equal authority — a trust flag date-scanning misses)
→ `atlas-agentic-graph-search-next-steps` (08-07; Stage 0 closed via REF-022, Stage 1 queued behind
REF-023). Terminal authority statement on record: *"Current code, binding, and the decision ledger
supersede this research document for implementation authority."*

Known coverage imbalance (self-flagged in the designs doc): the `subject` ring has 582 tracked
relations and nearly all experiments; `entity`/`value`/`legalIdentity` have **zero** tracked
relations and only data-plumbing designs.

**`research/evidence/` disposal map**: 33 entries; **2 are pinned production build inputs** —
`crs-source-concept-releases-2026-08-04/` (three bundle manifests, SHA-pinned in `SOURCE_SPECS`,
digests re-verified live) and `regulatory-native-controls-2026-08-03/source-native-control-capture.json`
(pinned at `v3_registry_codes.py:1389` — **the map did not know about this one**). Everything else
is verification-tool input or disposable; `regulatory-native-controls-2026-07-30/` is dead.

**Orphan**: `vocabulary-atlas-v1-explorer-search-corpus-2026-08-05.json` — reviewed acceptance
corpus whose consuming test was retired before its replacement was ported (stale `.pyc`, no `.py`);
`docs/decisions.md` confirms the port is still owed.

## 6. RefSpec tools/ — 58 scripts, 43,969 lines, honest wiring picture

8 Makefile-wired · 14 `benchmark_*` · 17 test-support · 7 imported as library by other tools ·
5 dated one-off experiments · **only 7 of 58 (12%) have zero references anywhere**:
`build_atlas_crosswalk_blind_review.py`, `build_atlas_parquet_view.py` (dead wrapper, superseded by
the console script), `capture_regulatory_native_controls.py`, `compare_atlas_crosswalk_blind_review.py`,
`export_registry_claim_releases.py`, `fetch_registry_source_via_zyte.py`, `reseal_elsst_managed_release.py`.
The map's "~35 unwired" count reproduces (58 − 8 − 14 ≈ 36) but overstated orphaning.

Three structural findings:
- **The Atlas 3.0 builder itself is unwired.** `generate_atlas_v3_full.py` — 10,294 lines, the
  component nearest the product thesis — appears in no Makefile target. The fidelity audit consumes
  its output; nothing invokes the builder.
- **A generate/verify pair splits across the wiring boundary**: `build_registry_source_manifest.py`
  (test-support only) produces the `sources.json` that Makefile-wired `verify_registry_audit.py`
  requires — the checked-in manifest can silently drift with no make target catching it.
- **The qualification cluster (13,672 lines measured; map said 13,377 — confirmed within
  methodology) is research-only and the boundary is *enforced by a running test*:**
  `tests/test_atlas_index.py:490-497` hard-fails if any pinned index path contains "qualification",
  "benchmark", or "candidate_retrieval". A model example of a check that can fail.
- `candidate_retrieval.py` isolation confirmed on all three claims: second engine (integer cosine,
  not BM25 — production explorer uses DuckDB `match_bm25()`), research-only reachability, zero live
  sibling-repo imports.

## 7. SpicyRegs — corpora (15 modules, 23,746 lines), tools (26), evidence (202 files)

**Corpora**: `segmentation_experiment.py` (3,841 ln) is shared infrastructure for five sibling
experiment modules; `segmentation_evaluation.py` is the only module with importers outside the
package (both importers local-only, absent upstream). Version pair confirmed:
`relation_exclusion_evaluation.py` (v1, frozen diagnostic — "unsuitable for a fair model comparison")
vs `_v2.py` (live successor, **gated open** — benchmark-eligible comparison blocked until two
independent blind human reviews are recorded). 13 of 15 modules have pyproject entry points; only
`embedding_audit.py` and `mirrulations_document_corpus.py` are pure-library.

**Tools**: 26 scripts, 0 production-wired — but **20 of 26 carry dedicated hermetic tests**
(dynamically loaded via importlib). Only 6 truly uncoupled: `benchmark_usearch_index.py`,
`citation_bakeoff_citeurl_worker.py`, `generate_source_profile_artifacts.py`,
`measure_extraction_retention.py`, `prototype_hyperbolic_subsumption.py` (carries its own embedded
tests, not collected by default), `run_extraction_bakeoff.py`. "One-off" is true of wiring, false
as a proxy for untested.

**Evidence** (25 dated dirs; mtimes are a bulk-checkout artifact — trust embedded dates only):
- CW clusters: relation-exclusion bakeoff (10 receipt-only dirs, no verdict prose — conclusions
  live in `docs/decisions.md`), candidate-selector ablation (dense channel *reorders*, doesn't find
  more), gold adjudication (5/35 adequate targets → the `scheme`-collision root cause that became
  v2's facet split), **`failure-analysis-2026-07-27.md`** — the methodological keystone: six-layer
  root-cause including "contamination is the default state of a fast iteration loop," direct
  ancestor of all sealed-holdout machinery here and in SpicySearch — usearch (CW-corrected,
  fabrication ground zero), discovery-slice (Q1 PASS; Q2 FAIL 0.8125 → fixed → 1.000 on re-run,
  addendum dated inside an older-named dir), single-document RKAF projection (all gates PASS,
  "Realistic — with one operational precondition").
- Clean clusters: body-retrieval corpus rebuild, citation/USC/agency/date-event/search-holdout
  build-input records ("built locally, digest-pinned, unpublished"), extraction bakeoff,
  segmentation remeasurement.

## 8. DocSpec — the qualification campaign

Seven tools (the fr_mirrulations harness family + four manifest/fingerprint generators +
`export_selection_ledger.py`, which has **never been run** — no `.jsonl` exists on disk).
Campaign `fr-mirrulations-10k-v1`: smoke sealed (53 stores) · intermediate sealed (66) · **full
unsealed** — missing census/release/run references, journal frozen at 03:31:08, 431 document stores
(more than both sealed tiers combined), plus five preserved `-pre-*-fix` snapshots. **Live
coordination collision observed during the trace**: another session renamed
`verification/gate-receipt.json` → `.superseded-2026-08-10.json`, and a same-day resume attempt
(13:19, PID 68734) failed with FileNotFoundError on the old name.

## 9. RuleSpec — validation corpus and specs

31 tools: 8 tests / 14 audit-validators / 7 producers (the census's 10/13/8 doesn't reproduce
cleanly under any single rule — three tools genuinely straddle validate/produce).
`release-records/`: 344 files exactly — 300 of them **deliberately broken negative-fixture bundles
across 14 failure scenarios** (a validation corpus, not litter), plus the vendored upstream
DocumentRelease pair, the atlas-membership stub that replaced 1.4 MB of vendored RefSpec, and 8
schemas. All 13 specs checked for enforcement: every normative spec has named tool/test enforcement
(`vocab_audit.py` fails the build on vocabulary/CUE divergence); `rkaf-rulemaking.md` is
Experimental; `rkaf-analysis.md` §6 (ClosureClaim) is explicitly DISABLED.

## 10. Census corrections surfaced by the trace (for the map, per M)

1. SpicySearch "experiments/ 21 · validation/ 9" conflated *code-package file counts* with the
   *data directories* (9 experiment dirs, unchanged since the census; `evaluation/validation/` never
   existed). Byte figures were correct (515 MiB receipts / ~584 MiB total).
2. `research/evidence/` has **two** pinned build inputs, not one.
3. The Atlas 3.0 builder is Makefile-unwired (D2's "no CI" finding extends: the *builder* also has
   no wired invocation).
4. SpicyRegs "25 of 26 tools one-off": wiring-true, but 20/26 are test-covered.
5. The scoped-fusion adoption chain (frozen → sealed holdout → serving reproduction) is absent from
   the map's SpicySearch card.
6. The segmenter baseline break is diagnosed (environmental, interpreter) — D6's row reads as
   unexplained.
7. RuleSpec tools split is 8/14/7-ish, not 10/13/8; classification-sensitive.

## 11. What this means for PLAN.md

- **Item 1**: the baseline table and the experiment design already exist (three arms, resolver +2,
  expansion 0 over synthetic edges; the record itself prescribes the real-thesaurus re-run). The
  pre-registered decision rule should treat *resolver* as the proven lever and expansion as entering
  with a measured zero to beat. Prerequisite confirmed independently: production `concept_candidate`
  cannot fire (no atlas present).
- **Cut policy**: the zero-reference delete lists are now explicit (7 RefSpec tools, 6 SpicyRegs
  tools, 1 dead wrapper, `regulatory-native-controls-2026-07-30/`); everything else carries tests or
  feeds a wired verifier. Two `research/evidence/` dirs are build inputs — do not sweep.
- **Item 4 packages only the PRODUCTION roster (§2)**. Planned-production entries are wiring work
  items, not package members until their gap closes; experiment tooling never enters the package
  surface. Tests do not promote — classification is by consumption path.
- **Not in the plan, measured and waiting**: enabling passage chunking in a published snapshot
  (recall@10 doubles), and the owed explorer-gate port. Both are product levers, not refactor items —
  they belong to a product-plan conversation, recorded here so they are not lost.
