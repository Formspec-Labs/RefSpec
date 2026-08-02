# Atlas crosswalk qualification pilot, 2026-08-02

The first real run of the offline qualification runner. Before it, every atlas
ever built carried zero qualified mappings: the data model was complete, the
five-way independence reducer was tested, and nothing anywhere had asked a
model family anything. This records what the first run cost, what it produced,
and what it says about the gate.

Run directory `output/atlas-qualification-2026-08-02/` (gitignored, machine
local). Every digest below is reproducible from those files.

## Inputs

| Role | File | Digest | Concepts |
|---|---|---|---|
| source | `spicy-regs/output/refspec-vocabulary-portfolio/federal-register-thesaurus-2025/managed-release/managed-release.json` | `sha256:3491acfdb3c4b51fda6351fcc47c2ca13e63e9df99e30399e05f745c97bf9df6` | 705 |
| target | `spicy-regs/output/elsst-r5-r6-final-gate/test_opt_in_full_r5_r6_managed0/managed-release-bundle.json` | `sha256:8dd408effe1d57109460a01a9c6620107b4662cbb95eed829ef905f3bfe8b71e` | 3,470 |

The ELSST bundle carries R5 and R6 in one managed release (6,905 members).
The run selects `https://elsst.cessda.eu/id/6` because a candidate names
exactly one reference release per endpoint and the atlas checks that it holds.

What each side actually supplies, measured rather than assumed:

- Federal Register 2025: 705 English preferred labels, 243 concepts with
  alternate labels, **no definitions, no scope notes, no hierarchy**.
- ELSST R6: 3,470 English preferred labels, 1,509 with alternate labels, 903
  with definitions, 3,221 with a broader concept.

So the model input is label-only on the Federal Register side for every
candidate. That is a property of the source, not a shortcut.

Opening the ELSST managed release takes about eight minutes, which is why the
runner is staged: `extract` pays that once and writes a concept table the
later stages read.

## Candidate generation

Policy `atlas-crosswalk-candidate-generation-v1`, seed
`refspec-atlas-crosswalk-2026-08-02`, candidate timestamp
`2026-08-02T12:00:00Z`. `candidates.json` digest
`sha256:8855a3ad8b7db86d308562e8801e2985e6ed2830de29fc0925c6788fb5049a78`;
regenerating from the same two concept tables reproduces it byte for byte.

| Class | Available | Drawn |
|---|---:|---:|
| `normalizedLabelEquality` | 141 | 110 |
| `alternateLabelEquality` | 118 | 55 |
| `substringNearMiss` | 841 | 55 |
| `editDistanceNearMiss` | 205 | 55 |
| `siblingDistractor` | 931 | 45 |
| `randomNegativeControl` | drawn | 45 |
| **total** | | **365** |

Classes are disjoint: a pair is claimed by the first class that reaches it.
`siblingDistractor` is the deliberate hard negative — the target is a sibling,
under a shared ELSST broader concept, of a concept that *did* match the source
by label. `randomNegativeControl` is a seeded draw over pairs sharing no
normalized token.

Every candidate proposes `skos:closeMatch`, uniformly. A relation chosen per
class would hand the judge the generator's hypothesis through the back door.

## Provider calls

Both models resolved against the live models endpoint by exact match, never
guessed: `models/gemini-3.6-flash` and `gpt-5.6-terra`.

| Family | Calls | Input tokens | Output tokens | Assumed cost |
|---|---:|---:|---:|---:|
| gemini (`google-gemini`) | 365 | 242,678 | 28,372 | $0.2065 |
| openai (`openai`) | 365 | 221,633 | 25,339 | $0.8075 |
| **total** | **730** | **464,311** | **53,711** | **$1.0139** |

k = 1 per family; the two families are the redundancy. Prices are pinned
assumptions (gemini 0.50/3.00, openai 2.50/10.00 USD per million tokens)
recorded next to the exact token counts the providers reported. Hard caps:
$6 gemini, $14 openai, $20 total; none was approached. The conservative
pre-flight projection was $10.48 — it assumes every call spends its whole
2,000-token output budget, and the models answered in about 70 tokens each.

Call outcomes: **729 completed, 1 unusable answer, 0 transport errors, 0
provider errors, 0 rate limits.** A six-candidate smoke run preceded the pilot
and is not counted above ($0.017, discarded).

The one unusable answer is worth naming. Gemini, on the pair
`Blood` → `ANATOMICAL SYSTEMS`, emitted the JSON *schema* and then the answer
object, concatenated — not parseable as one object. It was receipted as
`unusable_answer` and produced no validation, so that candidate carries one
validation and stays `notEligible`. Nothing was retried and nothing was
repaired. This is the refusal path firing on real data rather than on a
fixture.

## Results

Sealed bundle, 3,868,659 bytes:

- id `urn:ref:vocabulary-atlas-crosswalk-bundle:18644334888ab420340b03c79cad730ed7103f2b8ae4e3b76c1e91b4d9d99d3c`
- bundle digest `sha256:e099b26aaa47d489639f1c47874a6c3d3791e13c003e70c51d63e21b2eb3b25b`
- file digest `sha256:d95967187e804eaef8a4846237ef5d973d63ef607a4671d99c8f2a36687d8887`

Contents: 1,703 artifacts (365 `inputContext`, 244 `evidence`, 365
`validationRequest`, 729 `validationResponse`), 365 candidates, 729 machine
validations. Validation outcomes: 260 supports, 467 rejects, 2 abstains; all
729 passed their deterministic checks.

**121 candidates qualified as `searchOnly`.**

| Class | Candidates | Qualified | Rate |
|---|---:|---:|---:|
| `normalizedLabelEquality` | 110 | 103 | 94% |
| `alternateLabelEquality` | 55 | 14 | 25% |
| `editDistanceNearMiss` | 55 | 4 | 7% |
| `substringNearMiss` | 55 | 0 | 0% |
| `siblingDistractor` | 45 | 0 | 0% |
| `randomNegativeControl` | 45 | 0 | 0% |

Inter-family exact verdict agreement, over the 364 candidates both families
answered: **334/364 = 0.918**.

| Class | Agreement |
|---|---:|
| `randomNegativeControl` | 45/45 = 1.000 |
| `normalizedLabelEquality` | 106/110 = 0.964 |
| `substringNearMiss` | 52/55 = 0.945 |
| `editDistanceNearMiss` | 51/55 = 0.927 |
| `siblingDistractor` | 36/44 = 0.818 |
| `alternateLabelEquality` | 44/55 = 0.800 |

Disagreements are adjacent, not wild: the largest cells are
`related_but_distinct` against `same_or_near_same` (9 and 8, in both
directions) and `related_but_distinct` against `unrelated` (9). No pair had
one family say `same_or_near_same` while the other said `unrelated`.

## Honest negatives

**The easy diagonal dominates qualification.** 103 of 121 qualified mappings
(85%) came from normalized label equality, and every one of the three
distractor classes qualified nothing at all. A run that had generated only
label-equal pairs would have produced 103 mappings and would have looked
identical from the outside — which is exactly why the slice was not built that
way. The pilot's evidence that the gate discriminates is the 0/145 across
substring near-misses, sibling distractors, and random controls, not the 121
it passed.

**The gate is not a string comparison, and this is where it earned that.**
Seven of the 110 label-equal pairs did **not** qualify, including three where
both families independently refused:

| Pair | gemini | openai |
|---|---|---|
| `Community development` → `COMMUNITY DEVELOPMENT` | related_but_distinct | related_but_distinct |
| `Day care` → `DAY CARE` | related_but_distinct | related_but_distinct |
| `Statistics` → `STATISTICS` | related_but_distinct | related_but_distinct |
| `Laboratories` → `LABORATORIES` | same_or_near_same | related_but_distinct |
| `Advertising` → `ADVERTISING` | same_or_near_same | related_but_distinct |
| `Social security` → `SOCIAL SECURITY` | same_or_near_same | related_but_distinct |
| `Seeds` → `SEEDS` | insufficient_evidence | same_or_near_same |

Identical labels in a US regulatory thesaurus and a European social-science
thesaurus are not automatically the same concept, and both machines said so
without being told which pairs were suspect.

**Two format limitations the pilot ran into.**

1. `MappingCandidate.generatorKind` admits only `aiModel` or `aiAgent`. The
   candidate generator here is a deterministic program, and it is declared
   `aiModel` with `modelId`
   `refspec-atlas-crosswalk-candidate-generator` and temperature `0`, following
   the conformance fixture's precedent. The format has no honest slot for
   "this proposal came from a rule, not a model".
2. A crosswalk candidate must cross releases, so a *same-vocabulary*
   distractor — the control the plan asked for — cannot be expressed as a
   candidate at all. `siblingDistractor` is the closest expressible form: a
   cross-release pair whose target is one hierarchy step from a true match.

**Evidence artifacts deduplicate by content.** 365 candidates cite only 244
distinct `evidence` artifacts, because the controls and several near-miss rows
carry the same generation-rule record. The rule is genuinely the same; the
pair is named by the candidate, not the evidence.

## Acid test: the atlas consumes it

A scratch build over the same two managed releases plus this bundle (not
committed; `output/atlas-scratch/with-crosswalk/`, 263 MB):

- asset `urn:ref:vocabulary-atlas:e15cf9d7c0242c2a5c7d2594d6dac24667bd1ab01f5ef4b046d9f213b51697f9`
- manifest digest `sha256:1d9815d55d5bae94d323ab1bb761ee0d34542127d52f0c48c23cd8f5fa5c61a2`
- output digest `sha256:6a4558177cbaa460fc1a14178fa0aa7d2aa44b9d242295a63d029a29f3ed0ee6`
- build time 715 s (a crosswalk-free build of the same two releases takes 730 s,
  so the crosswalk is free next to the ELSST release facts)

Manifest counts: `mappingCandidates` 365, `machineValidations` 729,
**`searchOnlyMappings` 121**, `hierarchyEdges` 6,754, `labelClusters` 96,867,
`releaseFacts` 270,864, `analysisFacts` 613,350. The manifest pins the bundle
by id, bundle digest, and file digest under the `CrosswalkBundle` input role.

Read back through the consumer API (`VocabularyAtlasQueries`) after verifying
both file digests: 121 `searchOnly` mappings, every one `skos:closeMatch` from
`urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:v1`
to `https://elsst.cessda.eu/id/6`, each carrying exactly two machine
validations; 120 distinct Federal Register sources, 121 distinct ELSST
targets. The expansion-consumable shape is present end to end: a mapped ELSST
target resolves through `broader` into the release's own hierarchy (three
ancestors within depth 3 for the first mapping), which is the join a
cross-vocabulary expansion needs.

## Reproducing

```
tools/run_atlas_qualification.py --output DIR extract \
  --source-manifest .../managed-release.json \
  --source-release-iri urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:v1 \
  --source-vocabulary "Federal Register Thesaurus 2025" \
  --target-manifest .../managed-release-bundle.json \
  --target-release-iri https://elsst.cessda.eu/id/6 \
  --target-vocabulary "ELSST R6"
tools/run_atlas_qualification.py --output DIR generate --generated-at 2026-08-02T12:00:00Z
tools/run_atlas_qualification.py --output DIR qualify --env .../.env
tools/run_atlas_qualification.py --output DIR bundle
```

`extract` and `generate` reproduce byte for byte. `qualify` does not and says
so: the bundle records its own digest instead, and every call carries its own
request and response digest. A credential scan over the bundle, the 730-row
receipt file, the run receipt, and the models-list receipt finds none of the
nine values in the dotenv file.
