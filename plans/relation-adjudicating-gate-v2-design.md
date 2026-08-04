<!-- markdownlint-disable MD013 -->

# Relation-adjudicating gate, protocol v2

> **Status:** Proposed design, 2026-08-03. No code or sealed format changes yet.
>
> **Evidence base:** the three sealed crosswalk runs (FR×ELSST 2026-08-02, FR×ICPSR and
> ELSST×ICPSR 2026-08-03) and the two Fable blind-review comparisons.

## Why the binary verdict is now the bottleneck

The v1 gate asks one question — is `skos:closeMatch` safe in both directions? — and its
refusals discard structure the judges demonstrably had. Across the three runs, 819
validations answered `related_but_distinct`, and the sealed reasons state the relation in
prose that the structured verdict throws away: *"the target covers only 'traditions',
making the target narrower."* The ten pairs where a single blind reviewer diverged from
both machines decompose exactly along this line — four strictly hierarchical
(`ILLEGAL DRUGS` ⊂ `controlled drugs`), six associative (`TERRORISM` ↔ `terrorists`) —
and every one of them is a publishable typed mapping the current protocol can only file
next to random-negative garbage as `notEligible`.

The formats downstream are already ready: `_MAPPING_RELATIONS` in `atlas/model.py`, the
concept-domain bridge, and the explorer's relation labels all accept the five SKOS mapping
predicates today. Only the adjudication step is binary.

## Verdict vocabulary v2

Model-facing verdict strings, chosen so direction is unambiguous in English and maps
mechanically onto SKOS (mapping predicates are asserted source → target):

| verdict | meaning | emitted predicate |
|---|---|---|
| `same` | interchangeable for indexing; transitive identity is safe | `skos:exactMatch` |
| `near_same` | substitution safe both directions, identity not claimed | `skos:closeMatch` |
| `target_is_broader` | target strictly contains source | `skos:broadMatch` |
| `target_is_narrower` | source strictly contains target | `skos:narrowMatch` |
| `related` | genuinely associated, neither contains the other | `skos:relatedMatch` |
| `unrelated` | no useful relation | — |
| `insufficient_evidence` | undecidable from the given input | — |

The v1 rubric's core survives verbatim: the search-expansion framing, "judge the
concepts, not the strings", and the both-directions substitution test now decides
*between* `near_same` and the two directional verdicts instead of collapsing them.
`same` is deliberately strict — it is the only verdict that will ever feed equivalence
clustering, so the rubric text must say "answer `same` only when treating these as one
concept could never mislead; when in doubt, `near_same`."

**What the judge sees is unchanged**: preferred and alternate labels, definition and
scope note when the release states them (already true in v1 — `_concept_payload`
includes both), vocabulary names, and nothing from the generator. Hierarchy remains
withheld: the sibling-distractor leak argument from the pilot applies to hierarchy
alone, and it stays the open experimental arm, now sharpened — v2 distractors test
whether a judge can tell `related` from `near_same` without being handed the parent.

## Agreement rule v2

Two independent machines (same independence requirements as v1: distinct actor, group,
provider, model, response) must agree on a **compatible relation**, and the mapping is
emitted at the weaker of the two claims:

- `same` + `same` → `exactMatch`
- `same` + `near_same`, or `near_same` + `near_same` → `closeMatch`
  (both affirmed symmetric substitutability; only one affirmed identity)
- `target_is_broader` + `target_is_broader` → `broadMatch` (likewise narrower)
- `related` + `related` → adjudicated-`related`, recorded but **no mapping emitted**
  (see eligibility)
- any other combination → not eligible, exactly as a v1 disagreement

No other downgrades. `near_same` + `target_is_broader` is a real disagreement about
direction-safety and must fail, because emitting either relation would overrule one
machine on the precise claim that relation makes.

## Eligibility

- `exactMatch`, `closeMatch`, `broadMatch`, `narrowMatch` mappings carry
  `rkaf:usageEligibility rkaf:searchOnly` as today. Direction semantics ride on the
  predicate itself: a consumer expanding a query across `broadMatch` applies it
  asymmetrically (narrow → broad freely, broad → narrow penalized or not at all).
  No new eligibility vocabulary is minted; the predicate is the direction.
- Adjudicated-`related` produces **no** `ConceptMapping`. The typed refusal is sealed in
  the validations (verdicts + reasons) and distinguishable from noise in the bundle,
  which is the v2 gain; promoting associative links to consumable mappings is a separate
  decision for a consumer that actually wants them.
- `exactMatch` additionally becomes input to the (future) equivalence-clustering pass —
  the first process ever able to feed the `exactMatchCluster` machinery that
  `vocabulary.py` already reserves.

## Candidate blindness is preserved

`MappingCandidate.proposedRelation` stays uniformly `skos:closeMatch`: it is the
*hypothesis under test*, not the adjudicated answer, and keeping it uniform preserves
the v1 property that the generator's per-class expectations never reach the judge. The
adjudicated relation lives on the validation record and on the emitted mapping.

## Sealed-format changes (versioned, fail-closed)

- **Crosswalk bundle `schemaVersion: "2"`.** Validation records gain one required field,
  `verdictRelation` (one of the seven verdict strings); `outcome` is derived from it
  (`supports` for the five relation verdicts, `rejects` for `unrelated`, `abstains` for
  `insufficient_evidence`) and cross-checked at open. v1 bundles remain openable under
  v1 rules unchanged; a bundle may not mix versions.
- **Atlas builder** accepts v1 and v2 bundles in one build (the multi-crosswalk work
  landed the plumbing). v1 bundles emit `closeMatch` mappings exactly as today; v2
  bundles emit the agreed relation. `eligibilityPolicy` string for v2 bundles:
  `twoIndependentMachinesRelationAgreement`.
- **Conformance fixtures**: one new valid fixture per emitted relation outcome plus one
  lattice-downgrade case and one direction-disagreement refusal; corpus gains a v2
  amendment marker because the admission rule itself changes.
- **Explorer**: no format change needed — qualified edges already carry the relation and
  `_relation_label` already names all five predicates. Distinct dash styling per
  relation is a cosmetic follow-up.

## Controls under v2

- `randomNegativeControl` floor: both machines `unrelated`. Unchanged in spirit.
- `siblingDistractor` becomes a *relation-discrimination* probe: the floor is that no
  distractor earns `same`/`near_same`; `target_is_*`/`related` are acceptable outcomes
  because siblings genuinely are related. The 0/45 floor statistic is redefined
  accordingly and stays comparable across runs.
- The v1→v2 seed expectation: the 819 sealed `related_but_distinct` verdicts, whose
  prose reasons state directions, predict the v2 relation distribution. Divergence
  between predicted and adjudicated relations is itself a calibration measurement.

## Execution plan and cost

1. Implement v2 in `atlas/qualification.py` (verdicts, rubric, schema) and
   `atlas/model.py` (validation v2, agreement lattice, relation-aware emission),
   test-first, with fixtures regenerated. Estimate: one focused session.
2. Re-run all three pairs under v2 — same candidate slices, same blindness, full
   730 calls each so the runs stay uniform and comparable: ~**$3 total**.
3. Rebuild the atlas on the three v2 bundles; v1 bundles archive as evidence.
4. Compare v1↔v2 per pair: qualified-set stability for close/exact, recovered typed
   mappings from the former refusals, control floors, and the Fable-vs-gate
   disagreement set re-scored under the richer vocabulary (`Drugs`↔`drugs` is the
   marquee case: v2 lets both machines say `target_is_broader` instead of being forced
   to choose between a bad yes and an information-free no).

## Open questions (carried, not blocking)

- Hierarchy in the judge's input: run as A/B arms on one pair before deciding.
- Whether adjudicated-`related` should ever become a consumable mapping, and for whom.
- Equivalence clustering over `exactMatch` (connected components, in-house per the SeMRA
  decision) — designed separately once v2 produces its first `exactMatch` edges.
