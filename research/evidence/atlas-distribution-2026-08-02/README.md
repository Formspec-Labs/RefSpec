# Atlas distribution measurement, 2026-08-02

The structured result behind
[`docs/atlas-distribution-measurement.md`](../../../docs/atlas-distribution-measurement.md).
It answers one question — what does the SpicySearch atlas consumer read, and
what does each candidate distribution shape cost — and deliberately does not
answer the vendor / pointer / fetch question those numbers exist to inform.

| File | What it is |
|---|---|
| `evidence.json` | the consumer's read enumeration with citations, the two findings that precede the size question, every measured distribution, the read-equivalence proof, and the ELSST edition result |

## Everything here is reproducible

No provider was called. Every number comes from a build over pinned inputs or
from a scan of one of those builds.

| Role | File | Digest |
|---|---|---|
| Federal Register 2025 | `spicy-regs/output/refspec-vocabulary-portfolio/federal-register-thesaurus-2025/managed-release/managed-release.json` | `sha256:3491acfdb3c4b51fda6351fcc47c2ca13e63e9df99e30399e05f745c97bf9df6` |
| ELSST R5/R6 | `spicy-regs/output/elsst-r5-r6-final-gate/test_opt_in_full_r5_r6_managed0/managed-release-bundle.json` | `sha256:8dd408effe1d57109460a01a9c6620107b4662cbb95eed829ef905f3bfe8b71e` |
| ICPSR | `spicy-regs/output/refspec-vocabulary-portfolio/icpsr/2026-07-30/managed-release/managed-release.json` | `sha256:f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615999c881673ac12a` |
| crosswalk bundle | `RefSpec/output/atlas-qualification-2026-08-02/crosswalk-bundle.json` | file `sha256:508dd5611714ebbfb786bd87e814046ae40d072a8dd67e12c9e7f48e251c9b92`, bundle `sha256:d9a905a0d96bdf22ed829bfb7c5afc54b2084b1ebbcf3dbd88aebab0350d35d2` |
| Rulespec Core | `RefSpec/output/atlas-scratch/rulespec-core.json` | `sha256:06adfaf4d3ee8532c9ae76719d48a4844a4b012c7fea31e83e4a89f8033d1a63` |

The consumer side is pinned by digest too, because the whole enumeration is a
statement about exactly those bytes:
`spicysearch/src/spicysearch/vocabulary_atlas.py`
`sha256:5f96c2419d2bcfd4759aa6fa30ea1af088e6989621ab348146f69550c7683d22`,
plus `snapshot.py`, `engine.py` and `concept_resolution.py` (digests in
`evidence.json`). SpicySearch was read, never written.

## The builds are not committed

The full three-vocabulary distribution is 276,681,774 bytes and its consumer
projection is 61,900,562. Both live under `RefSpec/output/atlas-scratch/`,
which is gitignored and machine-local, and both rebuild from the digests above.
The three-vocabulary build takes ~12 minutes and ~6 GB.

The projection scripts are scratch tooling and are not committed either. There
is no projection format yet; writing one before Mike picks a distribution
strategy would prejudge the decision this measurement exists to inform. The
keep rule is stated in full in `evidence.json` under
`consumerProjection.keepRule`, and it is short enough to re-implement in an
afternoon.

## Headline

**The smallest distribution satisfying every consumer read is 61,900,562 bytes
(3,497,671 gzipped) — 22.4% of the full atlas — and returns byte-identical
results from every accessor.** 77.6% of the atlas is quads no consumer reads,
and 69% of it is label clusters that `open` validates and nothing consults.

Two things stand beside that number. The manifest field `hierarchyEdges` makes
today's atlas inadmissible to the vendored reader outright, and no distribution
stating hierarchy is currently valid on both sides — the projection escapes
only because it drops hierarchy, and was admitted by both readers. And a
projection carries the *same asset identifier* as the generation it came from —
both open under RefSpec's own validator — so binding 1.0 cannot express the
relationship a derived artifact needs. `reproduce_from_inputs` refuses a
projection with the message reserved for a corrupted atlas, executed.

**ELSST's second edition costs more than any vocabulary.** All 365 crosswalk
candidates and all 121 qualified mappings name ELSST R6; R5 is referenced by
none. Dropping R5 removes 95,497 of 96,958 label clusters and 78.9% of the
bytes, and is lossless for every read the consumer performs.
