# Raw trace: DocSpec and RuleSpec research/validation surfaces

Provenance: Sonnet subagent trace, 2026-08-10 (late). HEADs measured: DocSpec `7e3d0f2` · RuleSpec `9be401b`.
Status: **verbatim tracer output, preserved unedited** (transport HTML-escapes fixed). Subagent-produced —
per workspace rule, re-derive before relying on any figure not independently verified; the figures
`../RESEARCH.md` cites from this trace were spot-verified at compile time. OBSERVED / INFERRED /
ASSERTED markers are the tracer's own.

---

## DocSpec (commit `7e3d0f2`, 2026-08-10 02:59:24 -0400)

### tools/
- `fr_mirrulations_qualification.py` · Builds and runs the smoke/intermediate/full Federal Register + Mirrulations qualification tiers (`run_tier`, gate/manifest validation) · fr_mirrulations_* family (the harness driver) · reads prior tier's `execution-manifest.json` + gate receipt, writes to `output/qualification/<campaign>/runs/<tier>/`. OBSERVED.
- `fr_mirrulations_support.py` · Shared support code for the qualification runner (S3 fetch, manifest validation, digesting) · fr_mirrulations_* family (support module, not standalone CLI) · reads/writes same run tree as above; imported by `fr_mirrulations_qualification.py`. OBSERVED.
- `export_selection_ledger.py` · One-way exporter: converts a sealed DocSpec run into a flat JSONL "selection ledger" for a downstream document-release producer · not fr_mirrulations_* (general export tool) · reads sealed run bytes under `output/`, writes a JSONL ledger file (no ledger output file found on disk — tool present but not yet run against current output). OBSERVED (code); INFERRED (never executed here — no `.jsonl` output found anywhere in repo).
- `generate_archive_manifest.py` · Regenerates `archive/legacy-2026-08-05/archive.json` as one content-addressed SHA-256 tree digest over the frozen archive · not fr_mirrulations_* · reads all files under `archive/legacy-2026-08-05/`, writes `archive.json`. OBSERVED.
- `generate_ownership_manifest.py` · Regenerates `ownership/modules.json` from `src/docspec/*.py` plus hand-authored metadata · not fr_mirrulations_* · reads `src/docspec/`, writes `ownership/modules.json`. OBSERVED.
- `generate_scale_profile_schema.py` · Regenerates `conformance/scale-profile.schema.json` from the live `docspec.domain.scale` dataclasses · not fr_mirrulations_* · reads `src/docspec/domain/scale.py`, writes `conformance/scale-profile.schema.json`. OBSERVED.
- `predecessor_code_fingerprints.py` · Builds a sealed, portable AST/token fingerprint set for predecessor Python code (provenance/plagiarism-style detection) · not fr_mirrulations_* · reads source `.py` files, writes a fingerprint JSON artifact. OBSERVED.

### The qualification campaign (`output/qualification/`)
One primary campaign tree, `fr-mirrulations-10k-v1/`, plus five `-pre-*-fix` sibling directories (`pre-direct-resume-fix`, `pre-gate-receipt-fix`, `pre-local-fd-fix`, `pre-routing-bound-fix`, `pre-runner-boundary-fix`) that read as preserved pre-fix snapshots, each with the same `runs/{smoke,intermediate}` shape (no `full` in the snapshots).

- **smoke tier** (`fr-mirrulations-10k-v1/runs/smoke/`) · complete — has `candidate-census.json`, `release-reference.json`, `run-reference.json`, `execution-manifest.json` · `stores/document-stores/` = 53 entries · plan doc claims "passed — 100 documents / 136 candidates." OBSERVED (file shape) + ASSERTED (doc-cited counts, not independently reverified against candidate-census.json content beyond spot-check).
- **intermediate tier** (`.../runs/intermediate/`) · complete — same file set as smoke · `stores/document-stores/` = 66 entries · plan doc claims "passed — 1,000 documents / 1,359 candidates." OBSERVED + ASSERTED.
- **full tier** (`.../runs/full/`) · NOT sealed, confirmed by directory diff: missing `candidate-census.json`, `release-reference.json`, `run-reference.json` (present in both other tiers, absent here) — these are the closest on-disk analogue to the prompt's "run-selection"/"run-store-receipts" finalization artifacts. `catalog/` is empty (0 entries). `controls/control/*` receipt dirs (`processor-results`, `processor-invocation-receipts`, `extraction-receipts`, `segmentation-receipts`) each hold 256 entries — this is the closest on-disk analogue to "execution-task-results," and it is populated, not missing. `stores/document-stores/` = 431 entries (more than either sealed tier). `reconciliation/processor-results.sqlite3-journal` is present with **mtime 2026-08-06 03:31:08** — matches the "died/killed around 03:30" claim exactly. OBSERVED.
- **Live-session activity found today**: `verification/gate-receipt.json` has been renamed to `gate-receipt.superseded-2026-08-10.json` (147 KB, evidence-file manifest with 264/264 tests passed at capture time), and a fresh resume attempt exists at `output/qualification/full-tier-resume.{log,pid,start}` (PID 68734, log mtime **2026-08-10 13:19:21**) that **failed** with `FileNotFoundError: .../verification/gate-receipt.json` — it can't find the receipt because another session already renamed/superseded it. This is a live coordination collision, not a code bug. OBSERVED.
- No exported selection ledger (`.jsonl`) was found anywhere in the repo despite `export_selection_ledger.py` existing — consistent with "only ~1,000 documents are exportable" being a claim about the intermediate tier's completeness, not an already-materialized ledger file. INFERRED.

### docs/
- `docs/plans/2026-08-06-federal-register-mirrulations-10k-real-world-sampling-plan.md` — 2026-08-06 — subject: the 10k qualification corpus design (6,408 Federal Register + Mirrulations docs) — status: "Implementation in progress; rewritten after architecture and evidence review." Not in the contamination window (dated after 2026-07-28). OBSERVED.
- `docs/plans/2026-08-09-fr-mirrulations-10k-campaign-status.md` — 2026-08-09 — subject: run-status snapshot of the campaign — status: smoke passed, intermediate passed, full "partial... intentionally killed at ~97,700 fetched files/4.8GB," commits `ae601c9`/`8333768`. OBSERVED.
- `docs/superpowers/specs/2026-08-05-docspec-standalone-platform-implementation-spec.md` — 2026-08-05 — subject: DocSpec Bulk Content Processing Platform implementation/conformance spec — status: "Editor's Draft" (5 August 2026), explicitly states it "does not prove implementation or conformance." OBSERVED.

### archive/legacy-2026-08-05/ (top-level shape only, not catalogued)
Frozen historical snapshot, 15 top-level entries: `.github/`, `archive.json` (2.4 KB manifest), `conformance/`, `docs/`, `fixtures/`, `mcp-server/`, `policies/`, `product_goals.md`, `RULESPEC_FEEDBACK_ITERATION_1.md`, `RULESPEC_FEEDBACK_ITERATION_2.md`, `sample-data/`, `src/`, `tests/`, `TODO-RULE.md`, `tools/`, `uv.lock`. Per its own generator's docstring: 13 MB, 588 tracked files (80.5% of the repo), pinned to `sourceCommit "e179e0c"`, excluded from ruff/wheel/test-discovery. OBSERVED.

---

## rulespec (commit `9be401b`, 2026-08-10 13:21:01 -0400)

### tools/ (31 Python files confirmed — matches the ~10/13/8 expectation only approximately; see below)

**TEST (8, by `def test_` + filename convention):**
- `test_atlas_membership_stub.py`, `test_constraints_compile.py`, `test_extrapolation_release_v2.py`, `test_l0_mapping_audit.py`, `test_reference_release_digest.py`, `test_rulespec_releases.py`, `test_semantic_carriers.py`, `test_studio_schemas_derive_manifest.py`. OBSERVED.

**AUDIT-VALIDATOR (14):**
- `ci_validate.py` — CI conformance gate: validates positive fixtures against the SHACL shape suite.
- `codegen_drift_audit.py` — asserts `crates/rkaf-core/src/generated/` matches CUE source.
- `conformance_report.py` — per-fixture L1–L4 verdict reporter.
- `constraints_parity.py` — cross-compilation-target parity orchestrator.
- `l0_l3_coverage_audit.py` — audits L0–L3 conformance-surface coverage.
- `l0_mapping_audit.py` — audits L0 carrier mappings/self-certifications.
- `l4_coverage_audit.py` — audits Layer 4 behavior-fixture coverage.
- `projector_parity.py` — round-trip parity orchestrator for projectors.
- `rename_audit.py` — walks the repo for stale-name occurrences.
- `validate_negatives.py` — asserts every negative fixture is rejected.
- `vocab_audit.py` — fails build if vocabulary/CUE source diverge.
- `reference_release_digest.py` — computes/verifies a ReferenceResourceRelease digest.
- `extrapolation_release_v2.py` — portable verifier for partitioned ExtrapolationRelease v2 bundles (has a `validate` subcommand).
- `rulespec_release.py` — validates canonical Core/Extrapolator release records (subcommands: `validate`, `canonical`, `stamp` — dual validator/producer).
OBSERVED.

**PRODUCER (7):**
- `build_extrapolation_release_v2_fixtures.py`, `build_rulespec_release_fixtures.py` — build fixture corpora.
- `constraints_compile.py` — Layer 2 CUE→multi-target compiler.
- `generate_negatives.py` — mechanically generates "missing required field" negatives.
- `repin_contract_digest.py` — re-pins embedded L0 contract digests.
- `studio_schemas_derive_manifest.py` — orchestrates policy-studio `schemas-derived/`.
- `version_sync.py` — propagates `VERSION` to call sites (has `--check`/`--write` dual mode).
OBSERVED.

**OTHER (2):**
- `conformance_lib.py` — shared discovery-helper library, no CLI/tests of its own.
- `atlas_membership_stub.py` — rulespec-native stand-in implementing the `AtlasMembershipReader` protocol (support fixture-builder, not a CLI).
OBSERVED.

Scope/verdict on the 10/13/8 split: **partially confirmed.** 31 total is exact. Test count is 8, not ~10 (two fewer than expected — no other file exposes pytest `def test_` functions). Audit/validator count came to 14, one over ~13, because I counted `reference_release_digest.py`, `extrapolation_release_v2.py`, and `rulespec_release.py` as validators despite each also having a producer-shaped subcommand (`stamp`, fixture-building callers). If those three are instead counted as producers, the split becomes 8/11/10 — still not a clean 10/13/8 either way. The true count is sensitive to how dual-purpose validate+stamp/write tools are classified; no single convention reproduces the expected split exactly.

### analysis/ — ANOMALY: no top-level `analysis/` directory exists in this repo
`find`/`ls` confirm `/Users/mikewolfd/Work/rulespec/analysis` does not exist. The "(analysis)" in the cited commits (`791670e`, `5429465`, `17eba7a`) is a **conventional commit scope prefix**, not a directory. The actual surface those commits touch is `constraints/analysis/` (CUE constraint source) plus `spec/rkaf-analysis.md` (normative writeup) plus `shapes/rkaf-shapes-analysis.ttl` plus `fixtures/negatives/` (targeted negative fixtures) plus `tools/constraints_compile.py` (the SHACL emitter that had the bug). Catalogued below as the best-fit "analysis" surface:

- `constraints/analysis/machine-adjudication.cue` (147 lines) — defines `MachineAdjudicationProof` composing `ResolverProofRecord`. Research question: what makes two automated verdicts "independent" (not the same machine wearing two labels). Method: CUE schema constraint. Verdict recorded in commit history, not in-file: closed at **five** pairwise-distinct independence axes (validator actor, independence group, provider, provider model ID, sealed response artifact) — the fifth (`sealedResponseArtifact`) was added 2026-08-10 to catch up to `spec/rkaf-refspec.md`'s prose and RefSpec's own runtime enforcement (REF-023). OBSERVED.
- `constraints/analysis/resolver-proof-record.cue` (198 lines) — the composed proof-record shape backing adjudication (issuer, input digests, comparison binding). OBSERVED.
- `constraints/analysis/closure-claim.cue` (142 lines) — `rkaf:ClosureClaim`, explicitly marked **Experimental and DISABLED** in `spec/rkaf-analysis.md` §6. OBSERVED.
- `constraints/analysis/relation-change-event.cue`, `relation-comparison-context.cue`, `relation-finding.cue` (133/132/120 lines) — the relation-comparison-across-document-versions contracts the module exists for. OBSERVED.
- `constraints/analysis/semantics/l0-ranges.cue` (81 lines) — L0 range semantics for the analysis module. OBSERVED.
- Verdict trail (from commit bodies, not restated as file content): (1) `791670e` — RuleSpec cut its RefSpec dependency and now owns the adjudication protocol locally (previously vendored 1.4 MB of RefSpec's RDF and minted RefSpec's own namespace — flagged in the commit as backwards-dependency); (2) `5429465` — closed a spec/code drift where the shape enforced 4 independence axes but spec prose already said 5; (3) `17eba7a` — a reviewer found the axis-5 fix incomplete (SHACL checked inequality but nothing capped `sealedResponseArtifact` at one value per proof, so a decoy value could defeat the check) — root-caused to a compiler bug in `constraints_compile.py`'s conditional-branch SHACL emitter, fixed generally (19 compiled shape files gained `sh:maxCount 1` on recompile). OBSERVED (from commit messages) — this is a **new, actively-being-hardened surface**, consistent with the prompt's framing.

### release-records/ — 344 files, EXACT MATCH to expected count (335 under `fixtures/` + 8 under `schemas/` + 1 `README.md` = 344)
Structure:
- `fixtures/extrapolation-release-v2/` (300 files) — 14 `invalid/<scenario>/` negative-fixture bundles (assignment-pin, broken-coordinate, disposition-gap, duplicate-assignment, duplicate-disposition, extra-member, foreign-evidence, member-digest, missing-member, symlink-member, unknown-role, unknown-version, unsafe-path, wrong-identity) + 1 `valid/` bundle, each shaped `data/partition-000{0-3}/*.parquet`, `manifests/*.json`, `receipts/*.parquet`, `schemas/*.schema.json`, `release.json`. Format family: Parquet data + JSON Schema + JSON manifests, partitioned scale-format release bundles. These are **experiment/validation artifacts** (deliberately broken fixtures exercising specific verification-code failure paths).
- `fixtures/upstream/` (29 files) — a byte-for-byte, publisher-owned `DocumentRelease` v1 (single JSON) and v3 (parquet data/manifests/receipts/renditions/schemas tree) that Rulespec pins but does not own. Per README: **published/vendored release fixture**, not a Rulespec-generated experiment artifact.
- `fixtures/rulespec-atlas-membership-stub/` (2 files: `members.json`, `manifest.json`) — Rulespec-authored stub implementing `AtlasMembershipReader`, replacing the previously-vendored RefSpec atlas (per commit `791670e` above). **Validation/test artifact.**
- Loose files directly under `fixtures/`: `m2-negative-controls.json`, `m2-extrapolation-release-positive.json`, `m2-input-releases.json`, `rulespec-core-release-m2.json` — deterministic generated M2 fixtures per README, rebuilt by `tools/build_rulespec_release_fixtures.py`. **Experiment/validation artifacts.**
- `schemas/` (8 files) — closed JSON Schema documents for `extrapolation-release-v2` (5 sub-schemas + top-level) and `rulespec-core-release.schema.json`. **Published fixture/contract schemas**, not experiment output.
- `README.md` — describes the whole tree and rebuild commands.
OBSERVED throughout (arithmetic independently reconciled to 344).

### spec/ (13 docs)
- `spec/README.md` — index of specs. N/A enforcement.
- `spec/rkaf-core.md` — Rulespec Core vocabulary v0.2, Pre-release/normative — `AssertionEnvelope` term referenced in 18 files across `tools/`, `constraints/`, `shapes/`. OBSERVED.
- `spec/rkaf-concept-registry.md` — Concept Registry v0.2, Pre-release/normative — `ConceptRegistry`/`concept-registry` referenced in 14 files (`shapes/rkaf-shapes-conceptregistry.ttl`, `constraints/core/registry-conflict.cue`, `tools/constraints_parity.py`, `tools/test_constraints_compile.py`, etc.). OBSERVED.
- `spec/rkaf-conformance.md` — Conformance L0–L4 levels, Editor's Draft/normative — "conformance" referenced across 21 files under `tools/`. OBSERVED.
- `spec/rkaf-behavior.md` — Layer 5 Behavioral Contracts, Normative — `fixtures/behavior/` directory exists and 29 files reference behavior-fixture/`rkaf-behavior-validate` terms in `tools/`/`crates/`. OBSERVED.
- `spec/rkaf-refspec.md` — RefSpec Application Profile v0.1, Pre-release/normative — defines the `rkaf:openLabel` predicate and the 5-axis machine-adjudication independence rule; 7 files reference `MachineAdjudicationIndependentPair`/`machineAdjudicationProof` directly (constraints/shapes/tools). OBSERVED — this is the spec doc backing the analysis-surface work above.
- `spec/rkaf-rulemaking.md` — US Rulemaking-Process Module, **Experimental** — 102 files reference "rulemaking" (large surface, but note: Experimental status per its own header). OBSERVED.
- `spec/rkaf-vocabulary.md` — Full Term Reference, "mechanically-consumable... source of truth for code generators and projectors" — directly enforced by `tools/vocab_audit.py` (fails build on vocabulary/CUE divergence), 16 files reference vocabulary terms. OBSERVED, direct tool enforcement confirmed by reading `vocab_audit.py`'s own docstring.
- `spec/rulespec-releases.md` — defines RulespecCore and Extrapolator release units — directly enforced by `tools/rulespec_release.py`, `tools/reference_release_digest.py`, `tools/extrapolation_release_v2.py` (12 files reference the release-record type names). OBSERVED.
- `spec/rkaf-analysis.md` — Document-Analysis Module v0.2, Normative except §6 (Experimental/DISABLED) — enforced by `constraints/analysis/*.cue` + `AnalysisModuleTests` (kernel-never-depends-on-analysis boundary tests cited in the spec's own §1). OBSERVED.
- `spec/projectors/json-ld.md`, `json-schema.md`, `openapi.md` — Carrier Convention v0.2 each, Pre-release/normative — enforced by dedicated crates (`crates/rkaf-projector-json-ld`, `-json-schema`, `-openapi`, each with `src/` and `tests/`) plus 7 `tools/*.py` references to "projector". OBSERVED.

## Anomalies

1. **"analysis/" does not exist as a top-level directory in rulespec.** The task brief's framing (`analysis/` as a catalogueable surface) doesn't match the repo's actual layout — the relevant work lives in `constraints/analysis/` (CUE), `spec/rkaf-analysis.md`, `shapes/rkaf-shapes-analysis.ttl`, and `fixtures/negatives/`, tied together by the git commit scope prefix `(analysis)`. Catalogued that surface instead; flagging the directory-existence mismatch explicitly.
2. **tools/ TEST count is 8, not ~10; AUDIT-VALIDATOR count is 14, not ~13** (or 11/10 under an alternate dual-purpose-tool classification) — total 31 is exact, but the internal split does not land cleanly on 10/13/8 under any single classification rule I could apply, because 3–4 tools (`rulespec_release.py`, `extrapolation_release_v2.py`, `version_sync.py`, `reference_release_digest.py`) genuinely straddle validate/produce.
3. **A live, concurrent DocSpec session is actively working the exact "full tier" question this task was asked to characterize.** `output/qualification/full-tier-resume.{log,pid,start}` show a resume attempt today (2026-08-10 13:12–13:19, PID 68734) that renamed `verification/gate-receipt.json` → `gate-receipt.superseded-2026-08-10.json` and then failed on the next attempt looking for the now-renamed file. This is filesystem state actively in flux, not settled history — a re-run of this catalogue minutes later could see a different full-tier shape.
4. **Full-tier document-stores count (431) exceeds both sealed tiers** (smoke 53, intermediate 66) despite being the *unsealed* tier — the prompt's "~1,000 documents exportable" framing appears to refer to the intermediate tier's scope/candidate-census, not a literal exported-ledger count; no `.jsonl` selection-ledger artifact was found anywhere on disk to check directly.
5. **release-records/ file count (344) and analysis-commit terminology (five independence axes, sealedResponseArtifact cap) both matched the task brief's stated expectations exactly** — no anomaly, noted as positive confirmation since most other counts required reconciliation.
