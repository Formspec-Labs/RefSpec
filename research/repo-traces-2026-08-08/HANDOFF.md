# Handoff prompt

Copy everything below the line into a fresh session.

---

You are picking up work on a five-repository workspace mid-migration. **Read the source of truth first**, before touching anything: `/Users/mikewolfd/Work/spicy-regs/RefSpec/research/repo-traces-2026-08-08/data-flow-v2.html`. It is a navigable map, not a narrative — D1–D6 are durable facts, V1–V5 are volatile state, M is maintenance. The change list it once carried was retired on 2026-08-11; RefSpec work is in `RefSpec/PLAN.md`. Published copy: https://claude.ai/code/artifact/09607388-410e-4813-a8b9-72b6642daea1 — **stale**; republish from the artifact source or read the local file.

**Editing rule for the map itself:** `data-flow-v2-artifact.html` is the single source; `data-flow-v2.html` is generated from it (`python3 build-standalone.py`, in this directory, asserting loudly on structural drift). Never hand-edit the generated copy.

## The situation in five lines

- **Four repos are owned** (`Formspec-Labs`): RefSpec (vocabulary/atlas authority), RuleSpec (rule + schema contract), DocSpec (ingestion engine), SpicySearch (the sink). **One is not**: `civictechdc/spicy-regs` — commit access, not ownership.
- That single fact explains most of the architecture. The original rule — nothing you own may import what you don't, and vice versa — **was amended on 2026-08-10 and is recorded as REF-024 in `RefSpec/docs/decisions.md`**: cross-boundary consumption only through **versioned, published artifacts** (packages for code, digest-named releases for data), never through a checkout; and nothing that lands upstream may depend on an owned package at all. It is still violated today.
- **`spicy-regs` `main` is to be reset to `origin/main`** (`f1fcb8c`) — **not yet executed**: `main` still sits at `adbd5a2`, ahead 223 / behind 6 (diverged, merge-base `be04ee53`). The lineage is preserved on tag `archive/pre-reset-2026-08-09` (`002d56c2`, 224 commits); the branch `archive/local-work-2026-08-09` has **drifted past the tag twice** — `721bc12` (submodule bump), then `ac9a25d` (test quarantine), 226 at tip — it is simply a working branch now. `main` is not checked out anywhere, so the reset is a pure ref move: `git branch -f main origin/main` — no `reset --hard`, no clean hazard, reversible while the archive lineage exists.
- Target architecture: **RuleSpec → RefSpec → SpicySearch** as the spine, SpicyRegs and DocSpec as independent sources, SpicySearch driving DocSpec's ingestion. Direction set 2026-08-10: **the repos become versioned packages, and the pin/digest ceremony is cut** — one recomputed digest check per data handoff stays; checks that guard code relationships die with packaging; anything unread or unfailable dies now. The cut rows moved to the owning repository plans on 2026-08-11.
- The document was verified by seven independent agents attacking every claim, then re-checked across two same-day sweeps. Its numbers are unusually trustworthy **as of late 2026-08-10**. They will rot; see *Working discipline*.

## The plan

The ten-item change list this handoff summarised was retired on 2026-08-11.
RefSpec-owned work is in `RefSpec/PLAN.md`. SpicyRegs-owned work — the URN
spelling and byte-versus-codepoint decisions, the branch reset, the
`citations.py` boundary fixes, the upstream PR train and its payload test, and
the `rkaf_projection.py` boundary freeze — is in the SpicyRegs plan. The record
that moved them is
`spicysearch/docs/history/2026-08-11-cross-product-reconciliation-recommendations.md`.
Do not create another cross-product worklist.

## Do these first

1. **The reset is a ref move — do it as one.** `main` is not checked out, so `git branch -f main origin/main` completes it without touching any worktree. Never `checkout` + `reset --hard`: the `clean -fdx` hazard (~14 GB gitignored `output/`, ~20 tools reading from under it) exists only on that path.
2. **One pre-reset check: confirm what Vercel deploys from — and decide `_published.py`'s destination**, not just its deploy source. It is live deployed code absent upstream; a redeploy from the reset tree silently regresses production. **The `.gitmodules` rescue is refuted** (V1/V4): 0 of upstream's 32 workflows mention `submodules`, upstream has no RefSpec gitlink and no `refspec` dep — post-reset **CI does not break**. `docs/evidence/` is **already safe** — 201/202 byte-identical in `DocSpec/archive/legacy-2026-08-05/`. Do not re-prioritise either.
3. **`src/spicy_regs/corpora/mirrulations_document_corpus.py` cannot move yet.** Live DocSpec re-hashes it on every manifest validation, `strict=True`, pinned `sha256:78e9c8bd…`. The owning plans delete that seal when the draw logic lands in DocSpec. Until then: leave the file exactly where it is, extract copies.
4. **The upstream PR is fully specified and ready to write** — see V2. Two one-line fixes (`build_rule_targets.py:104-105`, `build_proceedings.py:493`), six-file manifest, receipt-verified. **Lead the description with the blast radius**: `rule_targets` collapses 335,008 → 40,546, 87.9 % of rows removed, and `comment_periods` changes schema breakingly. Raise the pymupdf AGPL question yourself. A reviewer who discovers any of that halfway through will reject it.

## The one experiment that changes the product thesis — repriced

**Point the live one-hop expander at a real thesaurus and measure it — but the old "nothing needs to be built" claim is refuted by the map's own sections.** Two prerequisites: (a) D3 — the Atlas 3.0 view edge is a verifier, not a data path; nothing downstream reads a row, and Atlas 2.0 stays live until cutover, so wiring the view into the snapshot build is part of the cost; (b) D2 — the only snapshot ever built holds **0 concept assignments over 722 documents**, so expansion has nothing to land on until an assignment path exists, even a cheap lexical baseline. **Pre-register the decision rule before running** — write down what `front_door` movement keeps the atlas lane first-class and what demotes it, so the outcome cannot be read with motivated eyes. Days, not a day. Still item 1.

## State as of the second sweep, late 2026-08-10

- **RefSpec tree is GREEN at `4e169a1`** — the lifecycle-event/supersession rename wave (315 files, −1,068) satisfied the rkaf adoption gate: 6 passed, 0 failed, re-run and verified. The gate was remediated, not weakened.
- **The five SpicyRegs collection failures are quarantined, not fixed** (`ac9a25d`): module-level skips with the retirement stated, 3,179 tests collect with zero errors, deletion explicitly deferred — that deletion belongs to the owning repository's plan.
- **SpicySearch at `02dea0e`**: the holdout snapshot **still does not open** (re-reproduced — `IntegrityError`, fields differ). New commits move semantic verification to a once-at-build gate — the repo is independently converging on the cut philosophy.
- **DocSpec unchanged at `7e3d0f2`** — `formatVersion` 1.0-vs-1.1 defect and the missing discovery port both still open.
- **Uncommitted working set in this directory** (RefSpec branch `atlas-v3-binding-and-relation-research`): `data-flow-v2-artifact.html`, `data-flow-v2.html`, `RESEARCH.md`, `traces/` (five verbatim tracer catalogues — RESEARCH.md's detail layer), `build-standalone.py`, this file. Commit them together; do not clobber.
- **The research catalogue exists now**: `RESEARCH.md` — every experiment/approach across all five repos, traced 2026-08-10 by five parallel agents and spot-verified. It is the delete-gate for the cut policy (settled negative results, zero-reference delete lists, the two pinned build inputs in `research/evidence/`) and it records the adopted scoped-fusion chain the map missed. Its §2 is the **decoupled tool roster** — production vs planned-production vs experiment, classified by consumption path; **test coverage does not promote a tool to production**, and the packaging item packages the production roster only. Read it before deleting any research surface or packaging anything.

## Working discipline — earned the hard way

- **Code is authoritative. `.md` is not evidence.** The whole investigation ran under "ignore every `.md` file, trace code instead," because prose here consistently overstated what was blocked and understated what was built. (The change list and this handoff are decisions, exempt by declaration.)
- **Re-derive; never quote a stored number.** Every figure that failed verification was read out of a receipt whose input had been rebuilt underneath it. A digest not re-checked at read time is decoration.
- **Correct in place. Never append.** The predecessor page died of six append-only amendment passes until most findings existed in three contradictory states.
- **Scope every claim explicitly** — `src/` vs `tools/` vs `tests/`, live vs archive, which build. Most "wrong" numbers in this programme were right under a different scope. Three separate passes gave 0, 1 and 28 for the same byte-identical-files question; all three were measuring different trees.
- **Separate what was measured from what was concluded.** Classify claims OBSERVED / INFERRED / ASSERTED. Inferences quietly harden into facts across a rewrite.
- **Report inbound and outbound coupling separately.** A much-quoted "3 imports" figure measured outbound only; inbound was ~120 statements across ~40 files. Cheap to extract, catastrophic to delete — opposite conclusions from one number.
- **Check both directions before concluding.** "Nothing reads X" was false three times over once the nested submodule, the archive, or the test tree counted.

## Traps specific to this workspace

- **The repos move hourly — every repo but DocSpec moved during a single afternoon.** Multiple sessions edit these trees concurrently. **Cite the HEAD you measured against.** As of the second sweep: RefSpec `4e169a1` (branch `atlas-v3-binding-and-relation-research`), RuleSpec `9be401b`, DocSpec `7e3d0f2`, SpicySearch `02dea0e`, spicy-regs archive `ac9a25d` / `main` `adbd5a2`.
- **The archive branch is not frozen.** It has drifted past its tag twice (`ac9a25d` vs `002d56c2`) and is a working branch in all but name. Figures pinned to `002d56c2` name the tag, not the branch tip. Rename it — SpicyRegs-owned, recorded in the SpicyRegs plan.
- **Two builds get quoted as one.** RefSpec's parquet sizes and its `statements.parquet` ring breakdown come from different build dates, and a row moved between them. Check the build before combining figures.
- **Subagents produce confident wrong numbers.** Verify anything load-bearing yourself. Never read a subagent's `.output` file — it is the full JSONL transcript and will overflow context; resume the agent with `SendMessage` instead.
- **RefSpec has no CI.** `RefSpec/.github` does not exist, so every gate named in the document runs only when someone remembers. (`RefSpec/PLAN.md` item 5 exists for this.)
- **Evidence documents dated on or before 2026-07-28 are untrustworthy** without re-checking — see contamination notice `d165350` (it lives in `docs/decisions.md`, not `docs/evidence/`, and survives the reset on a pushed branch).

## Still open

- Whether the ~122-file local-only `src/`+`tools/` body is carried forward. **This gates most of the rescue list** — the code depending on `docs/evidence/` is itself local-only.
- Whether DocSpec's rejection of the SpicyRegs release design extends to `rkaf_projection.py` itself, or only to the release format beside it. The migration stopped because agents ran out of tokens, not because it failed.
- Whether the 893,766-row `fr_docket_links` rebuild is semantically better than the receipt-attested 715,080, or merely larger.
- All production row counts remain asserted — the R2 catalog credentials are absent and no trace made a network call.
- The published artifact copy is stale — republish from `data-flow-v2-artifact.html` or stop linking it.

Work read-only in repos you are not explicitly asked to change, and do not check out branches — other sessions share these worktrees.
