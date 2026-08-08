# RefSpec Reconciliation Runbook

**Prepared:** 1 August 2026
**Executed:** 1 August 2026 — R1, R2, R4, and R5 are done. R3 and the optional provenance
restore remain open user decisions.

> **Execution status, 2026-08-01.** The original title said "prepared commands, NOT
> executed"; that no longer holds. What happened:
>
> - **R1 — executed.** `origin/main` was fast-forwarded in two pushes: `714866d..d05890e`,
>   then `d05890e..247a9ac`. REF-007 is published, without the provenance sentence.
> - **R2 — executed.** The retired standalone line is on `origin` as
>   `archive/standalone-2026-07-31` (`de744a3`), matching
>   `refs/archive/refspec-standalone/main`.
> - **R3 — OPEN. The user's decision.** The pre-scrub initial commit `67c497f` is still
>   unpublished and still preserved at `refs/archive/refspec-standalone/pre-scrub-initial`.
> - **Provenance sentence — OPEN. The user's decision.** REF-007 still does not name the
>   split commit. Restoring it is forward-only, but it re-publishes an identifier that was
>   deliberately scrubbed on 2026-07-28.
> - **R4 — executed.** The `spicy-regs` branch `feat/document-ai-pipeline` is published.
> - **R5 — executed.** `/Users/mikewolfd/Work/RefSpec` was deleted after its gate checks
>   passed: clean working tree, both archive refs resolving, and the archive branch listed
>   on the remote.
>
> The commands below are kept verbatim as the record of what was run. Re-running R1, R2, or
> R4 is a no-op; do not re-run R5.

**Original preparation note, superseded by the status above:** every command below was
prepared for a human to run deliberately, and the agent that wrote this file ran none of
them.

Local reconciliation is complete: the nested RefSpec line (the submodule inside `spicy-regs`)
holds the atlas distribution, the imported decision ledger REF-001…REF-007, the adopted
managed-vocabulary specification, and archive refs pinning the retired standalone line.

## Ordering constraint — read first

`spicy-regs` workflows now check out submodules. `actions/checkout` resolves the RefSpec
gitlink against `https://github.com/Formspec-Labs/RefSpec.git`. **R1 must run before the
`spicy-regs` branch is pushed**, or every CI job fails with "did not contain the requested
object" for the gitlink commit.

## R1 — Publish the nested RefSpec line (fast-forward)

**Executed 2026-08-01** as `714866d..d05890e`, then `d05890e..247a9ac`.

`origin/main` is `714866d`; the nested line descends from it, so this is a clean
fast-forward with no force.

```sh
git -C /Users/mikewolfd/Work/spicy-regs/RefSpec fetch origin
git -C /Users/mikewolfd/Work/spicy-regs/RefSpec merge-base --is-ancestor origin/main HEAD \
  && echo "fast-forward confirmed"
git -C /Users/mikewolfd/Work/spicy-regs/RefSpec push origin main
```

Publishes REF-007. **As committed, REF-007 does not name the split commit
`civictechdc/spicy-regs@70f8ce1`.** The plan's draft ended with a provenance paragraph naming
it; the executor left that paragraph out because committing it onto `main` would publish the
scrubbed identifier by default at R1, and removing it afterwards would require rewriting
history. See "Optional: restore the provenance sentence" below and R3's warning.

## Optional: restore the provenance sentence to REF-007

**Still open on 2026-08-01 — the user's decision.** REF-007 is published without it. Because
R1 has already run, this is now a new forward-only commit and a second push, not a
before-R1 edit.

Only if you want the split origin stated in the published ledger. This is a forward-only
edit — no rewriting. Append to the REF-007 section of
`/Users/mikewolfd/Work/spicy-regs/RefSpec/docs/decisions.md`, then commit, **before** R1:

```text
RefSpec's documents originate in the split of `civictechdc/spicy-regs` commit `70f8ce1`,
which created the RefSpec and Rulespec lines under Formspec Labs.
```

> **Same warning as R3 applies.** That identifier was deliberately amended out of the public
> repository on 2026-07-28. Adding it here and running R1 re-publishes it. The provenance is
> already preserved locally in `refs/archive/refspec-standalone/pre-scrub-initial`, which no
> default push touches, so restoring it is not needed for preservation.

## R2 — Archive the standalone line on the remote

**Executed 2026-08-01.** `archive/standalone-2026-07-31` is on `origin` at `de744a3`.

Pushes the retired line to a clearly-named branch. Not a force; the branch does not exist yet.

```sh
git -C /Users/mikewolfd/Work/RefSpec push origin \
  refs/archive/main:refs/heads/archive/standalone-2026-07-31
```

## R3 — OPTIONAL, PRIVACY-SENSITIVE: publish the pre-scrub initial commit

**Still open on 2026-08-01 — the user's decision. Not run.**

> **WARNING — this reverses a deliberate editorial scrub.** Commit `67c497f` is the original
> initial commit. Its `README.md` carries a `## History` section naming
> `civictechdc/spicy-regs` commit `70f8ce1` as the split origin. On 2026-07-28 that commit was
> amended (`f7f14b9`) and force-pushed, removing that text from the public repository.
> Publishing it re-exposes what was removed on purpose.
>
> **This is the user's call. Do not run it as part of routine execution.** The commit is
> already preserved locally and durably at
> `refs/archive/refspec-standalone/pre-scrub-initial` in the nested repo and at
> `refs/archive/pre-scrub-initial` in the standalone; publication is not needed for
> preservation.

```sh
git -C /Users/mikewolfd/Work/RefSpec push origin \
  67c497f859fab4a392014ff71401d423cc911807:refs/heads/archive/pre-scrub-initial
```

## R4 — Publish the spicy-regs surgical commit

**Executed 2026-08-01.** `feat/document-ai-pipeline` is published on the `spicy-regs` remote.

Only after R1. The branch carries 140 unpushed commits, most unrelated to this work; review
before pushing.

```sh
git -C /Users/mikewolfd/Work/spicy-regs log --oneline origin/main..HEAD | head -20
git -C /Users/mikewolfd/Work/spicy-regs push origin feat/document-ai-pipeline
```

## R5 — Delete the standalone checkout

**Executed 2026-08-01** after all three gate checks passed. `/Users/mikewolfd/Work/RefSpec`
no longer exists; do not re-run.

Only after R1 **and** R2 have succeeded and been verified on GitHub.

```sh
git -C /Users/mikewolfd/Work/RefSpec status --porcelain          # must be empty
git -C /Users/mikewolfd/Work/spicy-regs/RefSpec rev-parse \
  refs/archive/refspec-standalone/main \
  refs/archive/refspec-standalone/pre-scrub-initial              # both must resolve
git ls-remote https://github.com/Formspec-Labs/RefSpec.git \
  'refs/heads/archive/*'                                         # archive branch must be listed
rm -rf /Users/mikewolfd/Work/RefSpec
```

## Follow-on architecture work — NOT in scope of this reconciliation

1. **Promote RefSpec out of submodule-hood.** The submodule is why `spicy-regs` CI installs an
   empty `RefSpec/` and why `pyproject.toml` carries
   `[tool.uv.sources] refspec = { path = "RefSpec", editable = true }`. Replacing the gitlink
   and the path source with a published, version-pinned `refspec` distribution removes both
   the `submodules: true` workaround added here and the editable source-tree coupling. The
   `submodules: true` change is an **interim fix**, not the destination.
2. **Cut spicy-regs to published artifacts.** 18 `spicy-regs` files import the RefSpec package
   directly. The boundary decision (REF-001, REF-006) is that consumers read digest-pinned
   published files. Migrating those imports to file readers is a separate, test-covered change.
3. **Superseded: give SpicySearch a published Atlas 2.0 fixture.** The current
   replacement is a self-contained Atlas 3 fixture or generated consumer seam
   with an independently stored manifest digest. It must not resolve a RefSpec
   sibling checkout. Keep the exact fixture pin beside the consumer test.
4. **Retire the legacy Rulespec combined gate.** `profiles/rulespec-dependency.json` still pins
   evidence revision `2c66a85`; Rulespec is at `320ed37`. Migrating the last consumers to
   `RulespecCoreRelease` and Rulespec Extrapolator lets that manifest be removed.
