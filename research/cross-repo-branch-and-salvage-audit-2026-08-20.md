# Cross-repo branch and salvage audit

**2026-08-19 / 2026-08-20.** A branch/worktree audit across spicysearch,
spicy-regs, RefSpec and rulespec, plus an adversarial validation pass over its
own conclusions.

## What this document is, and is not

This is the **complement** to `research/atlas-tagging-and-salvage-survey-2026-08-20.md`.
Findings that were folded into that survey during a parallel session are listed
in "Already folded in" below and are **not** repeated here. What remains is what
that document does not carry.

**Validation.** This document was put through an independent adversarial pass
(`codex exec --sandbox read-only`, 14 named claims, instructed to default to
REFUTED). Ten claims verified, one returned CANNOT-VERIFY for lack of network and
was re-checked online, and **four defects were found and are corrected inline**
— see "Corrections to my own claims". The largest: a section asserting two open
defects that had in fact been closed.

Every number here was produced by running a command. Where a claim was made and
then failed checking, it is recorded in "Corrections to my own claims" rather
than quietly dropped. Two of my findings were refuted that way, one of them by
the parallel session.

### Already folded into the tagging/salvage survey — see there, not here

- `nrc-adams-multi-artifact-v1` implemented with zero users (Part II)
- the audit-evidence reproducibility defect (`fetch_id` churn)
- git notes as the working implementation of the append-only-correction convention
- the generated-vs-hand-authored adjudication shape disjointness
- "audit the constructed object, not the source text" (conventions)
- the `commits are immutable, so it is corrected here` citation

---

## 1. Repository state as of 2026-08-20

| repo | checkout | vs origin | note |
|---|---|---|---|
| spicysearch | `main`, clean | **ahead 29**, unpushed | 3 refs total after prune |
| spicy-regs | `integrate/payload-prereqs` | in sync | `RefSpec` + `uv.lock` modified |
| spicy-regs `main` | in `spicy-regs-landing` worktree | **ahead 31, behind 23** | diverged further during the audit (was behind 11) |
| RefSpec | `atlas-v3-binding-and-relation-research` | ahead 4 | `main` fast-forwarded to `f251e3b4`, now 4 behind again |
| rulespec | `feat/rulespec-conformance-package` | — | `main` ahead 7, unpushed |

`integrate/payload-prereqs` is **246 ahead / 37 behind** spicy-regs `main`.

## 2. The RefSpec submodule pin changed shape but is still unreproducible

At the start of this audit `spicy-regs` pinned RefSpec at a commit **plus
uncommitted changes**:

```
-Subproject commit 2a6e61a2...
+Subproject commit 6fcce6e0...-dirty
```

That has since been resolved into a clean pin — but to an **unpushed** commit:

```
+Subproject commit 90047dc776cd57a76bf8050c1b00ac71de76a774
```

`git -C RefSpec branch -r --contains 90047dc7` returns **empty**. The commit is
the `atlas-v3` tip, one of 4 local-only commits. So a fresh clone of spicy-regs
at `integrate/payload-prereqs` still cannot resolve the submodule. The `-dirty`
suffix is gone; the reproducibility problem is not.

**To close:** push `atlas-v3-binding-and-relation-research`, or repin to a
commit that is on a remote.

## 3. The move-2 compiler pattern never landed upstream

`research/move2-compiler` carries a RefSpec-side integration that references a
rulespec package state that does not exist.

Pinned in `bindings/atlas/3.1/shapes/rulespec-adjudication.lock.json`:

```json
"package": "rulespec-conformance", "packageVersion": "0.2.0-pre.10",
"accessor": "rulespec_conformance.contract.resources.shacl_sparql('machine-adjudication', family='analysis')"
```

Against the real `~/Work/rulespec`:

| pinned | actual |
|---|---|
| `0.2.0-pre.10` | `VERSION` = **`0.2.0-pre.9`** |
| `resources.shacl_sparql(...)` | only `shacl()` / `shacl_names()`, `resources.py:125,130` |
| a `shacl-sparql` compile target | targets are `json-schema, rego, rust, shacl, typescript` |
| prototype commit `28b37d7be3b2…` | **not found in any ref** |
| `shacl_sparql` / `ShapeSparql` in history | **zero hits**, 178 commits |

The branch's own `REPORT.md` explains why: the rulespec git metadata was not
writable in that sandbox, so the compiler was built in a throwaway mirror and
exported as `research/move2/rulespec-compiler.patch.gz` — a real, coherent diff
that was never applied. The report says applying it "is not the same as having
landed the upstream branch."

**Shipping today:** all six `rkaf-analysis` types generate to Rust, JSON Schema,
SHACL and TypeScript via `compile_all.sh`.
**Zero behavioural consumers:** exactly one crate depends on `rkaf-core` —
`rkaf-projector-json-ld` (`crates/rkaf-projector-json-ld/Cargo.toml:11`) — and it
imports only `RKAF_CONTEXT`. The six types appear elsewhere only in their own
definitions, `lib.rs` re-exports, and one round-trip fixture test.

**Left to do** — mechanical: apply the patch in a writable checkout; publish
`0.2.0-pre.10`; rebase the branch (64 behind). Decision: reconcile with the
hand-authored shapes. Blocked on data: per
`research/move2-compiler:REPORT.md:24-28`, no *measured* artifact contained real
`RelationComparisonContext` or `ResolverProofRecord` records. That is a statement
about what was measured, not proof none exists anywhere; either way the Python
oracle cannot be retired until one is produced and checked.

`feat/rulespec-conformance-package` (19 ahead / 0 behind `main`, never merged,
529 files) is **orthogonal** — it packages the validator as a wheel and adds
`SourceCatalogRelease` / `DocumentRelease` verification. None of it touches
`constraints_compile.py`.

## 4. The coverage campaign: the abstraction landed, the inventory did not

45 spec names exist on the `research/coverage-*` branches and not on `main`.
**42 of them are not reader gaps** — the underlying registry sources exist only
on those branches, so `main`'s build never constructs them:

```
scotus-opinion-types in main:src/refspec/atlas/v3_registry_codes.py            -> 0
scotus-opinion-types in research/coverage-readers5, same file                  -> 3
```

A source-fidelity auditor compares publisher bytes against what Atlas asserts.
Atlas asserts nothing from these sources, so porting the readers alone closes
nothing. (This generalises the argument already made about two readers in the
tagging/salvage survey, from 2 to ~42.)

### The 110-unit denominator is stale

"110 construction units" is `.releases[].key` from
`atlas-construction-summary.json` for build `atlas-3.1-full-2026-08-13b` — a
generated artifact, not a manifest. On-disk builds since:

| build | releaseCount |
|---|---:|
| 2026-08-15b | 99 |
| 2026-08-16 | 130 |
| 2026-08-17 | 128 |
| 2026-08-18 | 128 |
| 2026-08-19 | 128 |
| **2026-08-20** | **129** |

Against 129, **`main` covers 125**. Four uncovered:

- `eurovoc-microthesauri-4.24` — new, tied to `main`'s most recent commit
- `ferc-docket-prefixes`, `ferc-document-class-types`,
  `unified-agenda-legal-authority-citation-types` — raw-PDF blocked

Quoted blocker, `research/coverage-readers5:REPORT.md:24-27`: *"Their
construction inputs contain only raw PDF bytes. They need an independently
reviewed text or JSON extract before a stock reader can compare source rows."*

Those three exist **only** on `research/coverage-csv-pdf`. That is the reason to
keep that branch — not spec count.

`usgs-gnis-identifiers` is listed as blocked in that same report but is
**already covered on `main`** by its own `gnis-file-format-pdf-v1/1.0` reader
(`verify_atlas_source_fidelity.py:2332`), solved outside the research lineage.
`main` is further ahead than the branch reports imply.

### Reader-kind adoption on main

| kind | specs using it |
|---|---:|
| `pattern-row-v2` | 33 |
| `xml-record-selector-v1` | 20 |
| `ooxml-relational-v1` | 5 |
| `json-record-selector-v2` | 1 |
| `csv-record-selector-v2` | 1 |
| `nrc-adams-multi-artifact-v1` | **0** |

The abstraction is load-bearing. `pattern-row-v2` alone carries 33 specs.

## 5. Branch preservation has a single point of failure

`plans/validation-cost-reset-plan.md:550` states *"The branches survive worktree
cleanup"* for `spike/oxigraph-substrate` and `spike/jena-shacl`.

That is the **only** thing protecting them. Their tip `README.md` files are the
standard RefSpec README with no preservation notice. During this audit I built a
delete list from branch topology and put both on it; an adversarial pass caught
it before anything was deleted.

This repo already uses a `refs/archive/*` namespace for exactly this purpose:

```
refs/archive/refspec-standalone/main
refs/archive/refspec-standalone/pre-scrub-initial
refs/archive/atlas-3.0-exhaustive-compact-parity/2026-08-08
```

Those three are **single-copy** — verified absent from spicy-regs,
spicy-regs-landing, spicysearch and rulespec.

**Recommended:** move the two spike branches under `refs/archive/spike/*`, or
add a `PRESERVE.md` at each tip. A policy 550 lines into a plan document is not
a control a cleanup will read. *(Not executed — awaiting the owner's decision.)*

## 6. The branch-status ledger under-reports completed work

`plans/validation-cost-reset-plan.md:516`:

```
| research/shacl-rust | in flight (round 2) | rudof_cli 0.3.8 runs the real shapes; corpus parity pending |
```

Parity is not pending. That branch completed the study and reached a verdict —
rudof passes 45/48 SHACL-owned component lists exactly, the 3 misses being a
`sh:node`/`sh:detail` granularity gap, not a capability gap. Prose elsewhere in
the same document gives the finished result.

This matters because the table is the ledger other documents cite when sizing
salvage work; a stale row makes finished work look unfinished.

## 7. Branch disposition — RefSpec

After validation. **This is a tiering of the branches assessed, not an
exhaustive inventory** — RefSpec currently has 26 local heads; the table names 12
of them plus the 11 already deleted, and omits `main` and the remaining live
research/feature branches, which were not in scope.

| tier | branches | basis |
|---|---|---|
| **never delete** | `atlas-v3…`, `spike/jena-shacl`, `spike/oxigraph-substrate` | worktree checkouts + plan doc:550 |
| **hold — unlanded work** | `coverage-readers5`, `coverage-csv-pdf`, `move2-compiler` | the 3 PDF specs; the compiler scaffolding |
| **hold — code not in main** | `parse-substrate`, `shacl-{sparql,floor,rust}`, `residual-shacl`, `fidelity-definitions` | verdicts recorded in the plan doc, harnesses are not |
| **deleted** | 11 × `worktree-agent-*` | all ancestors of `main` or content-identical; objects still recoverable, no gc run |

**On tier 3:** the plan doc records research *conclusions* but not the
*harnesses* that produced them — `probe_rudof_*.py`, `JenaBenchmark.java`,
`prove_atlas_residual_lift_equivalence.py`, `research/parse_substrate/stores.py`.
Given that this project's own record contains retracted conclusions, the ability
to re-run matters more than usual. A verdict you cannot reproduce is a claim,
not evidence.

## 8. spicysearch prune — record and verification

Deleted 2026-08-19: 7 branches, 5 `refs/backup/*` stashes, 7 `refs/codex/*`
checkpoints, 10 `refs/archive/*` refs, tag `2026.07.21`; then
`reflog expire --all` + `gc --prune=now`. **783M → 549M**, 5,384 loose objects → 0.

Verified safe **before** deletion, and re-verified after:

- the two LFS receipt files are byte-identical to the archive branch's raw
  blobs — the archive blob sha256 equals the LFS oid
  (`5fe0f915…` / `cb45140d…`), recomputed post-gc and still matching
- all 252 archive-only files existed in `main`'s history and were deleted by one
  deliberate commit, `d11c3a1`
- all 10 `refs/archive/*` SHAs were confirmed present in sibling repos before
  deletion; ref manifest retained
- `git fsck --full --strict` and `git lfs fsck` clean; 374 commits walk to root

One branch (`archive/pre-lfs-publish-main-2026-08-12`) had **no merge-base with
`main` at all** — a fully unrelated history left by the 2026-08-12 LFS-adoption
rewrite. Any claim that spicysearch "has no divergent branches" is true only
after this date.

## 9. What the git notes record — and what has since closed

The survey now covers git notes as a mechanism. What it does not carry is their
content. **Both concerns the notes raise were fixed the same day the notes were
written**, 2026-08-10, and both fixes are ancestors of `main`:

| note on | concern raised | closed by |
|---|---|---|
| `165fcc10` | legal-identity `effectiveAt → effectivePeriodStart` published as an indefinite period (REF-023 item 2) | `3230081` *"fix(atlas): stop publishing a legal-identity instant as an indefinite period"*; correction at `docs/decisions.md:903` |
| `8c1c3e02` | no `REQUIRED_CORPUS_CASES` entry exercises a **dangling** `rkaf:supersedesAssertion` | `0c0091c9` *"test(binding): give the retired supersession-closure boundary its negative"* — `supersession-dangling-predecessor` is now in `corpus.json`, `validate.py:1140`, `build_fixtures.py:4949` |

So the notes are **not** an open defect register. Their remaining value is the
part that has not been superseded: `8c1c3e02`'s commit *subject* still reads
"validate supersession at full scope" while the commit retires full-closure
supersession — the subject asserts the opposite of what the commit does, and only
the note says so.

They remain unpushed. `git ls-remote origin 'refs/notes/*'` returns empty with
**exit 0** — a genuine empty result, not a network failure (an offline validator
hit DNS failure here and correctly reported it as unverifiable; re-checked online).

---

## 10. What Atlas actually buys for tagging, per band

Measured against the sealed view
(`output/atlas-3.1-parquet-search-view-2026-08-20`, 1,497,841 resources /
2,301,982 labels) and the 571,713 assignments in the Federal Register answer key,
banded by the pinned rule in `research/evidence/fr-topic-band-2026-08-20/`.

Assignment-weighted coverage of the answer key:

| band | assignments | tier A (incl `fr-api-topics`) | tier B (excl) | FR-thesaurus alone |
|---|---:|---:|---:|---:|
| all | 571,713 | 100.0% | 93.6% | 89.9% |
| procedural | 144,718 | 100.0% | 75.9% | 75.9% |
| substantive | 426,995 | 100.0% | **99.6%** | 94.6% |

**What Atlas's independent vocabulary adds over the FR Thesaurus alone:**

| band | gain |
|---|---:|
| all | **+3.76 pts** |
| procedural | **+0.00 pts** |
| substantive | **+5.04 pts** |

The global +3.76 reproduces the figure the tagging survey reports, computed
independently here — but it is not distributed evenly, and the split is the
finding. **Atlas buys exactly nothing in the procedural band and +5.04 points in
the substantive band**, where it reaches 99.6% coverage.

That aligns with the two-track design rather than cutting across it:

- **Procedural band** (25.3% of assignments) — 3.1% textually recoverable,
  +0.00 pts from Atlas. Neither reading the document nor enriching the
  vocabulary helps. It is an agency-conditioned prior problem, and Atlas is
  simply not the lever.
- **Substantive band** (74.7%) — 16.8% textually recoverable, and Atlas takes
  coverage from 94.6% to 99.6%. This is where Atlas earns its place.

The tier A column is 100% in every band because Atlas contains
`federal-register-api-topics` in full: measured against the answer key's own
vocabulary, coverage is trivially total. That is why the two tiers must never be
pooled into one headline — the difference between 100.0% and 93.6% is entirely
which scheme was permitted, not how well anything worked.

Independent schemes carrying the substantive band, by assignments reachable:
`lcsh-subjects` 281,475, `fast-topical` 259,766, `mesh-descriptors` 186,765,
`nasa-thesaurus` 168,229, `doe-osti` 163,112, `umthes` 161,518, `gemet` 146,151,
`icpsr-subject-thesaurus` 136,929. (Sums exceed the band: one topic string
reaches several schemes — which is the cross-scheme ambiguity that makes
scheme-scoped serving load-bearing.)

---

## Corrections to my own claims

Recorded because the conclusions above are only worth as much as the failures
are.

1. **"The survey's item 10 undercounts by ~20×" — WRONG.** Its reasoning was
   right and generalises: ~42 of the 45 specs audit sources `main` never
   constructs. I counted a real thing that did not mean what I implied.
2. **"`commits are immutable, so it is corrected here` is unlocatable" — WRONG.**
   I searched RefSpec and then wrote "not anywhere in main's tree" without
   saying which `main`. It is verbatim at
   `spicysearch:evaluation/experiments/2026-08-02-within-vocab-expansion-v1/decision.md:148`.
   Careless scoping nearly put a real quotation on a fabrication list.
3. **"27 of 29 branches are safe to delete" — WRONG.** Corrected to 4 by an
   adversarial pass. I had reasoned from commit topology and greps rather than
   from files and executed code, and had put three worktree checkouts on a
   delete list.
4. A subagent reported a dropped clause in `main:docs/decisions.md` as a
   regression. **Refuted** — the file is byte-identical at both commits and
   `main`'s text is correct.

Found by the codex validation pass:

5. **"The git notes name two open defects" — WRONG.** Both were closed on
   2026-08-10 by `3230081` and `0c0091c9`, each an ancestor of `main`. I read the
   notes as a live defect register without checking whether the defects survived.
   Section 9 is rewritten.
6. **"only `rkaf-core` and `rkaf-projector-json-ld` depend on `rkaf-core`"** — as
   written this says the crate depends on itself. Exactly one crate depends on it.
7. **"no artifact anywhere contains real records" — overstated.** The source says
   no *measured* artifact did.
8. **The branch disposition table was presented as covering "26 remaining
   branches"** but tiers only the 12 assessed plus 11 already deleted. Relabelled
   as a tiering, not an inventory.

## Open decisions

1. **Move the spike branches under `refs/archive/*`?** Endorsed by both sessions;
   awaiting the owner. Not executed.
2. **Push `refs/notes/commits`**, and set `notes.displayRef` so the corrections
   are visible to `git log`.
3. **Push or repin the RefSpec submodule** so `integrate/payload-prereqs`
   resolves for anyone else.
4. **Commit the three untracked survey files** in `research/`.
5. **Reconcile the adjudication shapes** — union, not swap; `RelationFinding` is
   covered only by the hand-authored pair.
6. **Fix the audit-evidence rebuild** to reuse recorded ids, or use
   `derive_uuid7` with a stable seed as the Atlas v3 path already does.
