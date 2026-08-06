# Atlas crosswalk benchmark sets, 2026-08-06

Five evaluation sets derived from the 1,095 cross-vocabulary mapping candidates
in [`atlas-3-mapping-evidence-2026-08-05`](../atlas-3-mapping-evidence-2026-08-05/README.md)
and the blind independent review in
[`atlas-crosswalk-blind-review-2026-08-06`](../atlas-crosswalk-blind-review-2026-08-06/).
These sets re-project existing bytes. No new judgment was made to build them.

**Nothing here supports a recall claim.** The candidate population was not
retrieved. It was a fixed stratified quota under
`atlas-crosswalk-candidate-generation-v1`, identical in all three crosswalks,
and every candidate in it came from a shared string between the two concepts.
No semantic-only pair — no pair whose only connection is meaning — could ever
have entered the population. A model that finds every mapping in `positives.jsonl`
has demonstrated nothing about the mappings the string generator never proposed,
and the size of that unseen space is unknown. Recall, F-measure, MRR, and nDCG
computed against these files are not weak estimates; they are estimates of a
quantity the population cannot express.

That limitation is structural. It cannot be repaired by relabelling the sets,
by reweighting the strata, or by adding rows from the same generator.

## Where the population came from

1,095 candidates, 365 per crosswalk (`fr-elsst`, `fr-icpsr`, `elsst-icpsr`),
each judged by two independent model families (Google Gemini, OpenAI). 582 were
admitted, 513 rejected. The per-crosswalk quota and its admission outcome:

| Generation class | Per crosswalk | Total | Admitted | Rate |
|---|---:|---:|---:|---:|
| `normalizedLabelEquality` | 110 | 330 | 302 | 91.5% |
| `substringNearMiss` | 55 | 165 | 130 | 78.8% |
| `alternateLabelEquality` | 55 | 165 | 120 | 72.7% |
| `editDistanceNearMiss` | 55 | 165 | 30 | 18.2% |
| `siblingDistractor` | 45 | 135 | 0 | 0% |
| `randomNegativeControl` | 45 | 135 | 0 | 0% |

The admission rates are a property of the generator, not of the vocabularies.
The 91.5% at the top is what happens when two labels normalise to the same
string; the 18.2% is what happens at small edit distances. Neither rate
generalises to a candidate stream produced any other way.

The two 0% rows are a **filter, not a verdict**. Replaying the admission rule
(`tools/replay_atlas_crosswalk_admission.py`, 2026-08-06) shows the relation
lattice alone would admit 651 rows, of which 69 are controls: 64 sibling
distractors and 5 random negatives whose judges both supported a relation and
agreed on its type. Admission reproduces its recorded 582 exactly once a
**control-class exclusion is applied ahead of the lattice**. Read every control
figure below with that in mind — no control could be admitted whatever a judge
said about it.

## The five sets

### `positives.jsonl` — 582 rows

The admitted candidates, carrying the SKOS relation each was admitted under:
232 `closeMatch`, 121 `exactMatch`, 119 `narrowMatch`, 75 `broadMatch`,
35 `relatedMatch`. By crosswalk: 190 `fr-elsst`, 201 `fr-icpsr`, 191
`elsst-icpsr`.

Usable for precision measurement on lexically similar pairs, for regression
fixtures across prompt, judge-model, or admission-rule changes — the set is
fixed, so drift is visible — and for testing whether a proposed relation prior
reproduces the admitted type.

Not usable as a recall denominator, for the reason above. Also not usable as a
relation-type answer key: the type on each row is two sealed models agreeing,
and an independent blind pass reproduced the exact type only 74.4% to 78.8% of
the time. Treat the type as the majority machine opinion it is. Not usable as
editorial assertion; see the governance note.

### `hard-negatives.jsonl` — 157 rows

Non-control candidates the sealed judges genuinely rejected — at least one
judge did not support a relation at all.

Usable for precision-side stress. These are the string-similar pairs that
actually fail, so they discriminate a scorer keying on surface form from one
reading meaning, and they are the right set for setting a lexical-similarity
threshold.

Not usable as a general negative class. Every row shares a string with its
counterpart. A model tuned to reject these has learned to reject lexical
lookalikes, which says nothing about the far larger space of pairs sharing no
string — and that space is where a real system spends its rejections. Not
usable for a specificity estimate either: the negative prior here was set by
quota, not by the underlying distribution.

### `controls.jsonl` — 270 rows

Seeded negatives: 135 sibling distractors (a true concept's sibling substituted
for the true target) and 135 random negatives. None was admitted — but that is
the control-class exclusion above, not a judgment. What the judges actually said:

| Class | `google-gemini` names a relation | `openai` | Independent reviewer |
|---|---:|---:|---:|
| `randomNegativeControl` | 5.2% | 5.2% | **3.7%** |
| `siblingDistractor` | 55.6% | 57.0% | **48.1%** |

Usable for calibrating a judge's willingness to name a relation — on the random
half, where a relation genuinely does not exist.

Not usable in any pooled accuracy number, and **not usable as a rejection-rate
scoreboard across the two halves.** Sibling distractors were built by
`target-sibling-of-label-equal-match`: a true label-equal pair with the target
swapped for one of its siblings under the target vocabulary's own published
`broader` links, with the `sharedBroader` and `siblingOf` IRIs recorded on each
evidence artifact. The planted pair therefore really does share a parent in the
publisher's hierarchy, `related` is frequently the correct answer on it, and
`related` is what the judges gave in 117 of their 152 supporting verdicts on the
class. Counting those as errors measures a rubric position, not competence.
Report the two halves separately, always, and keep them out of any figure that
also contains real candidates.

### `disputed.jsonl` — 86 rows, deliberately unresolved

Non-control candidates rejected despite **both** sealed judges supporting a
relation. They died on incompatible relation *type*, not on whether a relation
exists. The independent blind pass confirmed a relation in 85 of the 86.

Usable as the adjudication-policy benchmark, and it is the only one that
exists. See below.

Not usable as a pool of positives to promote, not usable as evidence that the
historical pipeline was defective — the disagreement is genuine, and the
rejection rule behaved as specified — and not usable as labelled data of any
kind, because there is no label on these rows and there is not going to be one.

### `directness.jsonl` — 1,095 rows

Every candidate, with the independent reviewer's directness verdict
(`direct_candidate` or `generic_thematic`), written blind: the reviewer saw the
concept facts the sealed judges saw and nothing else — no outcome, no verdict
relation, no admission status, no generation class, no provider identity. Of
the 582 admitted rows, 547 were called `direct_candidate` and 35
`generic_thematic`.

Usable for building or checking a genericity filter, and for testing whether
directness predicts admission independently of relation type. Coverage is
complete over this population, controls included, so the two-class distribution
has no selection gap *within the population*.

Not usable outside a lexically seeded population. Judging directness on a pair
that shares a string is a different act from judging it on a semantically
retrieved pair, and the transfer has not been measured. Not usable as ground
truth on admission either, for the ordinary reason: one opinion per row, written
once, by one model family.

## What the independent pass is worth

Three independent Opus review passes covered all 1,095 rows blind, one pass per
crosswalk, with outcomes and admission status withheld. Agreement is measured
against 730 sealed judge verdicts per crosswalk.

| Crosswalk | Support-level agreement | Exact-relation agreement | Controls rejected |
|---|---:|---:|---:|
| `fr-elsst` | 95.2% (695/730) | 74.4% (543/730) | 68.9% (62/90) |
| `fr-icpsr` | 97.3% (710/730) | 78.8% (575/730) | 67.8% (61/90) |
| `elsst-icpsr` | 94.9% (693/730) | 76.8% (561/730) | 85.6% (77/90) |

**The "controls rejected" column had no baseline, and the one it was compared
against was wrong.** An earlier version of this file said the sealed judges
rejected 100%. They did not; admission excluded controls by class before the
lattice ran. Measured directly, the reviewer is at or below both sealed judges
on both control classes in every crosswalk — see the table in
`controls.jsonl` above. Treat the column as descriptive, not as a demerit.

Read the two columns differently. Support-level agreement near 95% means the
reviewer and the sealed judges rarely disagree about whether *some* relation
holds. Exact-relation agreement in the mid-70s means they disagree about
*which* relation, roughly a quarter of the time, between models that both had
the full concept record in front of them. That gap is the real finding of the
pass, and it is the reason `disputed.jsonl` exists.

The reviewer does discriminate. It supports a relation on 99.3% of admitted
rows, 15.9% of real candidates the judges rejected, and 3.7% of random negatives
— a support verdict is worth 6.2× against the first negative population and
26.8× against the second. What keeps it a comparison signal rather than an
arbiter is simpler than a calibration failure: it is one opinion per row.

It is also worth being precise about *what* it corroborates. On the 86 disputed
rows both sealed judges had already asserted a relation exists, so a third
opinion on existence was pre-answered and the 85/86 agreement is the expected
result rather than an informative one. The open question on those rows is type,
and there the reviewer supplies a third opinion, not a tiebreak.

## Why `disputed` stays unresolved

The 86 rows are the only benchmark for adjudication policy in the archive.
Every other set scores whether a relation was found. These score what a system
does when a relation is found and two competent judges name it differently — a
proposed change to the relation lattice, a class-conditioned relation prior, a
confidence-weighted tie-break, or a merge rule can each be scored on whether it
resolves these 86 the way a later authority would. Assign types now and there
is nothing left to test against; the answers become whatever policy happened to
be in force the day they were written.

There is also no clean basis on which to resolve them. Two sealed judges from
different model families each supported a relation and disagreed on its type.
The independent reviewer sometimes supplied a *third* type, and one more machine
opinion does not break a tie between two. Any resolution today would be recorded
as though it were an answer, in the file whose whole value is that it contains
no answers.

Per crosswalk: 34 disputed in `fr-elsst` (33 with reviewer support for a
relation), 19 in `fr-icpsr` (19), 33 in `elsst-icpsr` (33).

### What a scored policy looks like

The first proposal has been run (`replay_atlas_crosswalk_admission.py`,
2026-08-06), and it is the model for any that follow: score the rule, record the
score, leave the rows alone. Collapsing `same`/`near_same`/one-step-granularity
for the two label-equality classes admits **37** of the 86 and adds zero
controls. Extending it so `related` is compatible with a direction reaches 85 —
and admits four sibling distractors, so it fails.

The 86 are two populations, which is why no single rule takes all of them:

| Disagreement | Rows |
|---|---:|
| `near_same`/`same` versus a direction — a granularity dispute | 40 |
| `related` versus a direction — associative or hierarchical | 40 |
| `near_same`/`same` versus `related` | 5 |
| `target_is_broader` versus `target_is_narrower` — flatly opposed | 1 |

Only the first group is a lattice defect. The second is the question the file
exists to keep open.

## Governance

The source archive's README states that its records "preserve historical
machine evidence" and "do not authorize a broader use ceiling or turn derived
relations into editorial assertions." Packaging those records as evaluation
sets does not change what they are; these five files inherit that ceiling
unchanged.

Using `positives.jsonl` to score a scorer is inside the ceiling. Promoting the
86 disputed rows — or any other row here — into the graph as an asserted
mapping is a release decision under its own authority, and needs the evidence,
review, and sign-off that a release decision needs. The convenience of having
the rows already assembled is not that authority.

## What real gold would require

An unbiased recall denominator requires exhaustive enumeration of a complete
population: every source concept crossed with every target concept, each pair
judged, nothing sampled and nothing filtered by a generator first. Only then is
the denominator the true set of mappings rather than the set some heuristic
proposed.

CRS Policy Areas against the Federal Register Thesaurus is small enough to do
exactly that: 32 × 705 = 22,560 pairs. Every pair judged, no candidate
generation step anywhere in the loop.

These five sets make that build cheaper without replacing it. The six
generation classes above already cover the shared-string region of some of that
space, so pairs the old generator reached and a judge already ruled on can be
carried across rather than re-judged, leaving the semantic-only remainder as
the work that actually has to be paid for. That is a cost saving on the real
benchmark. It is not a substitute for it, and a saving on the numerator does
not fix a denominator.

## If you are about to...

**...compute recall, F1, MRR, or nDCG against `positives.jsonl`** — stop. The
denominator is a shared-string quota. Whatever number comes out will look like
a recall figure and will not be one. Build the 22,560-pair exhaustive
enumeration instead; that is what the measurement requires.

**...pool `controls.jsonl` into a single accuracy or specificity number** —
stop. 270 of the 1,095 rows are planted negatives that the sealed judges
rejected unanimously, and their share of the population is an arbitrary quota.
Report control rejection separately, split by sibling and random, and report
performance on real candidates on its own.

**...resolve the 86 disputed rows, or promote them into the graph** — stop, on
both counts and for different reasons. Resolving destroys the only adjudication
test set in the archive and substitutes a fresh machine opinion for the
uncertainty that is the point of the file. Promoting is a release decision that
this archive has no authority to make. If a policy change needs testing, score
it against these rows and record the score; leave the rows alone.
