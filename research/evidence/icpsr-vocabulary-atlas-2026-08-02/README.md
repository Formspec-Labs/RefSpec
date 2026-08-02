# ICPSR vocabulary-atlas bridge, 2026-08-02

The measured result of giving the ICPSR subject thesaurus the atlas adapter
ELSST and the Federal Register already had. The analysis is in
[`docs/icpsr-atlas-bridge.md`](../../../docs/icpsr-atlas-bridge.md).

Unlike the crosswalk qualification run next door, everything here **is**
reproducible: no provider was called, and every number comes from a pinned
input. This directory exists so the counts can be checked without re-running a
build that opens a 743 MB ELSST bundle three times.

| File | What it is |
|---|---|
| `evidence.json` | the structured result: measured source facts, hierarchy shape, what projected, what did not and why, the operational-state decision, and the atlas builds |

## Inputs, all pinned by file digest

| Role | File | Digest |
|---|---|---|
| ICPSR | `spicy-regs/output/refspec-vocabulary-portfolio/icpsr/2026-07-30/managed-release/managed-release.json` | `sha256:f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615999c881673ac12a` |
| Federal Register 2025 | `spicy-regs/output/refspec-vocabulary-portfolio/federal-register-thesaurus-2025/managed-release/managed-release.json` | `sha256:3491acfdb3c4b51fda6351fcc47c2ca13e63e9df99e30399e05f745c97bf9df6` |
| ELSST R5/R6 | `spicy-regs/output/elsst-r5-r6-final-gate/test_opt_in_full_r5_r6_managed0/managed-release-bundle.json` | `sha256:8dd408effe1d57109460a01a9c6620107b4662cbb95eed829ef905f3bfe8b71e` |

The ICPSR sources underneath those digests are the 2026-07-30 capture:
`subject.xml` `sha256:1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff`
and index capture
`sha256:b155705626d53cce42a746ca582c4c8ca7e546db9b704a2223cad52fac45c6c6`.

## The scratch atlases are not committed

Both builds wrote to `RefSpec/output/atlas-scratch/`, which is machine-local and
ignored. The three-vocabulary distribution is far too large to commit, and the
ICPSR-only one is 11.5 MiB with no reason to keep it — either rebuilds from the
pins above. Their identifiers are deliberately **not** recorded: an atlas id
pins the generator's source modules, so it would go stale on the next unrelated
edit to `atlas/model.py` and record nothing a reader could use. The counts and
byte lengths do not depend on it.

## The size answer, in one line

The three-vocabulary distribution is 270,130,849 bytes (16,992,570 gzipped) and
**69.5% of it is label clusters** in the replaceable analysis graph. ICPSR
accounts for 4.8% of the file and added 91 clusters. Clusters scale with the
number of *releases* sharing a label, and ELSST alone ships two.

## Headline

ICPSR states 3,760 URI-verified concepts, 3,280 preferred and 480 alternate
label roles, 730 scope notes, no definitions, 1,759 broader and 1,759 resolved
narrower that are exact inverses of one another, 14,360 fully symmetric
related, and an ISO 25964 USE/UF pair that is **not** reciprocal — 479 against
394. The hierarchy is acyclic, 64 concepts sit under more than one parent, and
the deepest branch is 5.

The release declares itself `developmentOnly`. The adapter requires that
declaration and republishes it on the release node rather than dropping it or
refusing the vocabulary; see `evidence.json` `operationalStateDecision` for why.
