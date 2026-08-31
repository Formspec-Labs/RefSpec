# Reviewed source snapshots

These archives preserve the complete tracked source surfaces reviewed by the
twelve-agent sweep. They are preservation evidence, not current product
authority.

| archive | exact source state | purpose |
| --- | --- | --- |
| `spicy-regs-integrate-payload-prereqs-a6ab98a.tar.gz` | `spicy-regs` commit `a6ab98aa35825ce993023ad9b237a28d04bb153e` | Complete tracked tree for the source-native, document-processing, ontology, evaluation, workflow, fixture, and tool findings. |
| `spicy-regs-landing-main-31a4bfe.tar.gz` | `spicy-regs-landing` commit `31a4bfe488c16e154fd98d7303e20cb7c033c764` | Complete tracked predecessor catalog tree, including the formerly untracked metadata-complete universe and schema compatibility rule. |
| `spicy-regs-local-history-2026-08-27.bundle` | the two heads above plus `refs/snapshots/pre-strip-2026-08-26` at `57d46bf73bcc47617514ce270c2908a551e2353b` | Re-clonable complete Git history for the local-only branch and snapshot refs. |
| `spicy-regs-legacy-branches-2026-08-27.bundle` | `backup/pre-marker-fix` at `bc8f534763216eef96f490b8855f98edf9a110a3` and `feat/rkaf-boundary-freeze` at `a8938b4f8ddd34d585414bb43bdd8336676c49b5` | Re-clonable complete Git history for the two additional local branches that were not reachable from the first bundle. |

`git bundle verify` reported complete history for both bundles and all five
expected refs across them. Both omitted branches were also restored into an
empty bare repository, checked with `git fsck --full`, and resolved to the exact
commit IDs above. `SHA256SUMS` records the archive bytes. The dangling landing
`RefSpec` symlink was intentionally not recreated; its missing target is
recorded in the closure ledger.
