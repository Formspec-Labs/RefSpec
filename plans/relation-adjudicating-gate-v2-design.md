<!-- markdownlint-disable MD013 -->

# Relation-adjudicating gate, protocol v2

> **Status:** Accepted, reshaped 2026-08-03 after review. Implemented in
> `atlas/qualification.py` and `atlas/model.py`; sealed formats amended in
> `bindings/atlas/1.0` under amendment `2026-08-03-relation-adjudication`.
>
> **Evidence base:** the three sealed crosswalk runs (FR×ELSST 2026-08-02, FR×ICPSR and
> ELSST×ICPSR 2026-08-03) and the two Fable blind-review comparisons. All three runs are
> protocol v1; no v2 run has been purchased yet, so every claim below about what v2 will
> *find* is a hypothesis, not a measurement.

## Why the binary verdict is now the bottleneck

The v1 gate asks one question — is `skos:closeMatch` safe in both directions? — and its
refusals discard structure the judges demonstrably had. Across the three runs, **752**
validations answered `related_but_distinct` (268 + 273 + 211; counted from the sealed
`receipts.jsonl`, and equal to the sum of `verdictsByFamily` in each run receipt). That is
34% of all 2,190 validations and the largest bucket after `same_or_near_same`, which
totals 817 — the number this document previously misreported as the
`related_but_distinct` count.

The sealed reasons state the relation in prose that the structured verdict throws away:
*"the target covers only 'traditions', making the target narrower."* Read honestly, about
two thirds state a clean direction, about a quarter assert an associative relation, and
**10–12% state no usable direction at all** (17% in ELSST×ICPSR) — so roughly 90 of the
752 predict nothing, and the v1→v2 seed expectation below should be read against 660-odd
reasons, not 752. A further group is confident prose that maps onto no SKOS predicate at
all (partitive and aboutness claims); those are `related` at best.

The ten pairs where a single blind reviewer diverged from both machines decompose along
this line — four strictly hierarchical (`ILLEGAL DRUGS` ⊂ `controlled drugs`), six
associative (`TERRORISM` ↔ `terrorists`) — and each is a publishable typed mapping the
current protocol can only file next to random-negative garbage as `notEligible`. Two
caveats the evidence forces: nine of the ten come from a single run, so this is not yet a
cross-run pattern; and they are only the misses. The same comparison holds eight machine
*false positives* — pairs both machines qualified and the human refused — which v2 does
not address at all.

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

Two gates, in order. The **relation** gate folds the *set* of distinct verdicts from every
supporting validation that answered one candidate's sealed question, and the mapping is
emitted at the weakest claim any of them made:

- `{same}` → `exactMatch`
- `{same, near_same}` or `{near_same}` → `closeMatch`
  (all affirmed symmetric substitutability; not all affirmed identity)
- `{target_is_broader}` → `broadMatch` (likewise narrower)
- `{related}` → adjudicated-`related`, recorded but **no mapping emitted** (see eligibility)
- any other set → not eligible, exactly as a v1 disagreement

The **independence** gate is then v1's unchanged: two of those validations must be
genuinely different machines (distinct actor, group, provider, model, response).

The relation gate is **universal, not existential** — it folds every supporting verdict
rather than looking for some compatible pair. This matters as soon as a third machine
exists: under a per-pair rule, `near_same` + `target_is_broader` + `near_same` would find
an agreeing pair and emit `closeMatch` while a machine on the record says the direction is
unsafe, and `same` + `same` + `near_same` would emit whichever relation the id sort
happened to reach first. Folding the set makes both deterministic and conservative: the
first refuses, the second yields `closeMatch`.

No other downgrades. `near_same` + `target_is_broader` is a real disagreement about
direction-safety and must fail, because emitting either relation would overrule one
machine on the precise claim that relation makes. Downgrading it to `relatedMatch` would
be worse, not safer: `relatedMatch` asserts *neither contains the other*, a third claim
neither machine made.

## Eligibility

- `exactMatch`, `closeMatch`, `broadMatch`, `narrowMatch` mappings carry
  `rkaf:usageEligibility rkaf:searchOnly` as today. Direction semantics ride on the
  predicate itself: a consumer expanding a query across `broadMatch` applies it
  asymmetrically (narrow → broad freely, broad → narrow penalized or not at all).
  No new eligibility vocabulary is minted; the predicate is the direction.
- Adjudicated-`related` produces **no** `ConceptMapping`. It is recorded as
  `atlas:adjudicatedRelation skos:relatedMatch` on the candidate, alongside
  `rkaf:notEligible`, so the refusal is *typed* rather than blank.

  Scope, stated plainly: this is **bundle- and analysis-internal only**. The consumer
  projection's keep-rule (`CONSUMER_READ_CLOSURE_V1`) roots its closure on qualified
  `searchOnly` mappings, so an adjudicated-`related` candidate is dropped from the
  projection entirely; and the published explorer draws every `notEligible` candidate as
  an undifferentiated "not qualified" edge. A reader of the sealed bundle or of the full
  atlas can tell an associative agreement from noise. A consumer of the published
  projection cannot. Earlier drafts of this document claimed the gain without that
  boundary; the boundary is the honest version.

  **Scoped follow-up, not taken here:** make it consumer-visible by minting
  `CONSUMER_READ_CLOSURE_V2` (adding `atlas:adjudicatedRelation` and its candidate to the
  analysis keep-set) and giving the explorer a distinct edge style for adjudicated-related.
  That versions a published projection policy and needs its own decision about who is
  asking for associative links; it is deliberately out of scope for this pass.
- `exactMatch` additionally becomes input to a (future) equivalence-clustering pass,
  designed against its own sink. It must **not** be routed into `exactMatchCluster`
  (`vocabulary.py:172`, `binding.py:106`): that is a sealed-gold *holdout partition key*
  used to keep an entity's mentions from straddling a train/test split, not reserved
  clustering machinery. Feeding machine-adjudicated identity into it would invert the
  guarantee it exists to give — an over-merge silently joins splits, an under-merge leaks.
  Two-machine agreement is sound warrant for a pairwise claim and is not warrant for a
  leakage control.

## Candidate blindness is preserved

`MappingCandidate.proposedRelation` stays uniformly `skos:closeMatch`: it is the
*hypothesis under test*, not the adjudicated answer, and keeping it uniform preserves
the v1 property that the generator's per-class expectations never reach the judge. The
adjudicated relation lives on the validation record, on the candidate as
`atlas:adjudicatedRelation`, and on the emitted mapping.

But the field is **not shown to a v2 judge**. Under v1 it was the question restated — the
verdict answered "is *this* relation safe?" — so showing it leaked nothing. Under v2 the
judge chooses among seven relations, and a standing `closeMatch` in the prompt is a prior
on the one axis v2 exists to measure; it would bias the run toward `near_same` and
contaminate the calibration comparison below. `model_input_payload` therefore omits it for
v2 while the sealed candidate still records it. Blindness now has two meanings and both
hold: the generator's *class* never reaches the judge, and under v2 its *relation guess*
does not either.

Because v2 seals a different rubric and a different payload, **v2 candidate identity moves**
— `inputContextDigest` differs, so a v2 candidate is a different candidate, not the same
one relabelled. A candidate slice is therefore generated per protocol
(`run_atlas_qualification.py generate --protocol v2`), and the catalog records which.

## Sealed-format changes (versioned, fail-closed)

- **Crosswalk bundle `schemaVersion: "2.0"`.** Validation records gain one required field,
  `verdictRelation` (one of the seven verdict strings); `outcome` is derived from it
  (`supports` for the five relation verdicts, `rejects` for `unrelated`, `abstains` for
  `insufficient_evidence`) and cross-checked at create and at open. v1 bundles remain
  openable under v1 rules unchanged and byte-stable; a bundle may not mix versions.
- **Atlas builder** accepts v1 and v2 bundles in one build (the multi-crosswalk work
  landed the plumbing). v1 bundles emit `closeMatch` mappings exactly as today; v2
  bundles emit the agreed relation, anchored by `atlas:adjudicatedRelation` on the
  candidate. The binding's `searchOnly` proof is amended accordingly
  (`2026-08-03-relation-adjudication`): the mapping relation matches the candidate's
  *adjudicated* relation where it states one, and its proposed relation otherwise.
  Anchoring v2 to the proposal would have forbidden every relation except `closeMatch` —
  the atlas literally could not be reopened.

  The manifest's `policies.mappingEligibility` stays `twoIndependentMachinesSearchOnly`.
  The reason is REF-009 and REF-011, not asset stability: that field set is closed on both
  sides and changing a value is a binding version bump. (The stability argument would have
  been false anyway — `atlas/model.py` is inside the implementation pin, so every atlas id
  moved with this change regardless.) The two admission rules are told apart by the
  presence of the new facts and by the **run receipt**, which now records
  `protocol` and an `eligibilityPolicy` of `twoIndependentMachinesRelationAgreement`
  for a v2 run.
- **Conformance fixtures**: one valid distribution exercising every lattice outcome —
  all four emitted relations, the `same`+`near_same` downgrade, adjudicated-`related`,
  and a direction-disagreement refusal — plus four invalid distributions: a mapping
  relation the adjudication does not license, an adjudication its verdicts do not
  support, qualifying verdicts that disagree, and an adjudicated-`related` candidate
  promoted to eligible. Corpus gains the `2026-08-03-relation-adjudication` amendment
  marker because the admission rule itself changes.
- **Explorer**: no format change needed — qualified edges already carry the relation and
  `_relation_label` already names all five predicates. Distinct dash styling per
  relation is a cosmetic follow-up.

## Controls under v2

- `randomNegativeControl` floor: both machines `unrelated`. Unchanged in spirit.
- `siblingDistractor` becomes a *relation-discrimination* probe: the floor is that no
  distractor earns `same`/`near_same`; `target_is_*`/`related` are acceptable outcomes
  because siblings genuinely are related.

  This is a **different measurement**, and the receipt now says so rather than reusing one
  number for both. `candidatesByClass.<class>.qualified` keeps meaning "earned a mapping",
  which under v2 includes the directional relations and is therefore *not* comparable to a
  v1 run's `qualified`; a new `qualifiedAsSubstitutable` counts only `exactMatch` and
  `closeMatch` and *is* comparable, because it asks the narrower question v1's 0/45 floor
  actually asked. Note why the v1 floor held at all: `related_but_distinct` collapsed to
  `rejects`, and that collapse is precisely what v2 removes — reading the two `qualified`
  columns side by side would show a control collapse that is really a redefinition.
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
4. Compare v1↔v2 per pair: qualified-set stability for close/exact (compare
   `qualifiedAsSubstitutable`, not `qualified`), recovered typed mappings from the former
   refusals, control floors, and the Fable-vs-gate disagreement set re-scored under the
   richer vocabulary.

   `Drugs`↔`drugs` is worth re-scoring but it is **not** a case of the gate being forced
   into an information-free no, as this document previously claimed. The sealed record
   shows both machines answered `same_or_near_same` and the pair *qualified*; the human
   reviewer refused it. It is a v1 false positive, one of eight. The v2 hypothesis is that
   a judge offered `target_is_broader` will take it instead of over-claiming
   substitutability — that is a testable prediction about model behaviour under a new
   rubric, not a structure v2 mechanically recovers. If both machines still answer
   `near_same`, v2 changes nothing here.

## Open questions (carried, not blocking)

- Hierarchy in the judge's input: run as A/B arms on one pair before deciding.
- Whether adjudicated-`related` should ever become a consumable mapping, and for whom —
  and, separately and sooner, whether it should merely become *visible* to a consumer via
  `CONSUMER_READ_CLOSURE_V2` and a distinct explorer edge (see Eligibility above).
- The eight v1 false positives the blind comparison found. v2 addresses misses, not
  over-claims; nothing in this design makes a wrong `same_or_near_same` less likely.
- Equivalence clustering over `exactMatch` (connected components, in-house per the SeMRA
  decision) — designed separately once v2 produces its first `exactMatch` edges.
