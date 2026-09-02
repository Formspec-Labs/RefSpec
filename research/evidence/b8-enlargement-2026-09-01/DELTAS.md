# B8 enlargement — declared receipt deltas

Lane 1 (B8 enlargement), correctness wave 2026-09-01. Mission:
`research/investigations-mined-2026-08-31.md` lines ~41-51 (`inv-b8`), plus
its two riders. This file is the DECLARED set of receipt-key moves the
integrator's next combined rebuild should attribute to this lane. Every
number below is measured against the artifact this checkout carries today
(`output/registry-real-data-sources/unified-agenda-parquet/`, current as of
2026-09-01), by calling the SHIPPED functions in-memory
(`research/evidence/b8-enlargement-2026-09-01/measure_b8_two_witness.py`),
never by copying the mined doc's numbers. Re-run that script against the
rebuilt artifact before accepting these as final — see "Caveat" at the
bottom.

## What shipped

`src/refspec/registry/unified_agenda_parquet.py`:

- `_held_parts_by_rule(references, notes)` — a new shared helper, extracted
  from the nine lines `_judge_against_cfr_notes` and
  `_write_placeholder_candidates` each carried a copy of. Both call sites
  updated; behavior unchanged (verified: existing tests for both still pass).
- `_promote_two_witness_b8(authorities, references, oracle, notes)` — the
  new builder rule. Runs after `_judge_usc_sections` and
  `_promote_paren_eaten_lettered_suffix`, gated on `usc_section_corrected is
  None`. Wired into `build_unified_agenda_parquet` right after the C3
  promotion call.
- `USC_B8_PROMOTION_RULE = "B8-two-witness-lettered-section"` — the value
  written to `usc_section_correction_evidence`. NOT a member of
  `usc_section_oracle.CORRECTION_RULES` (same separation
  `USC_C3_PROMOTION_RULE` keeps).
- `USC_B8_PROMOTION_OUTCOMES = ("promoted", "note_names_bare_section",
  "witnessless")` — the new receipt census, closing the LONE:B8 hole (rider
  #1, below).
- A `usc_appendix` skip in the loop's own row filter. An appendix section is
  its own numbering — "5 U.S.C. App. 3" is not 5 U.S.C. 3 — so a lettered
  identity read off the main corpus must never be written onto one, and an
  appendix row must not be counted as a refusal either. Measured 0 appendix
  rows in the whole 13,896-row B8-survivor population (`measure_b8_excluded.py`),
  so it is a fence against a future parse rather than a live filter: adding
  it moves no number (`summary.json` reproduces byte-identically with and
  without it), and removing it fails
  `test_b8_two_witness_census_accounts_for_every_lone_b8_row`, which now
  carries a synthetic appendix row that must stay uncounted.

`src/refspec/registry/usc_section_oracle.py`: docstring-only addition to
`CANDIDATE_ONLY_RULES`, forward-referencing the enlargement so a future
reader does not conclude the two-witness publication is impossible or a
violation of B8's demotion. No executable change; `CANDIDATE_ONLY_RULES`,
`Correction.__post_init__`'s refusal, and every existing test are untouched
(`tests/test_usc_section_oracle.py`, 79/79 still green).

Tests: 12 new, additive, in `tests/test_unified_agenda_parquet.py`. None
re-pin an existing literal. Two of the twelve were added by the 2026-09-01
adversarial review's conditions and each is mutation-proven below:
`test_b8_two_witness_binds_the_note_witness_to_the_rows_own_held_parts`
(witness 2a must read the row's OWN rin+edition parts) and
`test_b8_two_witness_refuses_where_the_note_names_only_the_bare_section`
(the counter-evidence rider's smaller, bare-only sub-population).

**Mutations performed 2026-09-01** — each applied to the shipped function,
the suite run, the failure observed, the mutation reverted, and the file
verified byte-identical to its pre-mutation state:

| mutation | caught by |
| --- | --- |
| witness 2a's `parts` ← the union of every held part (unbinding it from the row's own rin+edition) | `..._binds_the_note_witness_to_the_rows_own_held_parts` (`assert '18a' is None`) and, incidentally, the census test |
| the counter-evidence short-circuit removed entirely | BOTH rider fixtures, and the census test |
| the rider narrowed to the both-named shape only | `..._refuses_where_the_note_names_only_the_bare_section` alone |
| the rider narrowed to the bare-only shape (i.e. publishing the 254) | `..._refuses_where_the_notes_own_part_names_the_bare_section` alone |
| the `usc_appendix` skip removed | `..._census_accounts_for_every_lone_b8_row` (the appendix row promotes; the census sums to 4, not 3) |

The last three lines are the point of adding a second rider fixture: before
it, one fixture covered both shapes' single code path, and either narrowing
would have shipped green.

## Receipt-key deltas

### New key: `uscB8PromotionRows`

```json
{"promoted": 666, "note_names_bare_section": 319, "witnessless": 454}
```

Measured by `measure_b8_two_witness.py`, calling the shipped
`_promote_two_witness_b8` against a fresh in-memory copy of the current
`unified_agenda_legal_authorities.parquet` + `unified_agenda_cfr_references.parquet`.
The three outcomes sum to **1,439** — see "The LONE:B8 population" below.

### Unchanged keys (verified, not merely assumed)

- `uscSectionCorrectedRowsByRule`, `uscSectionCorrectionRefusalRowsBySurvivors`
  — computed entirely inside `_judge_usc_sections`, which runs and returns
  BEFORE `_promote_two_witness_b8` is ever called. Same limitation
  `uscC3PromotionRows` already has (a builder-level promotion's rows are not
  reflected in `identity_moved_rows_by_rule` either) — not fixed by this
  lane, consciously left matching precedent.
- `uscC3PromotionRows` — disjoint population by construction: C3 requires
  `usc_section_verdict == "absent"` on the bare section; B8's own candidate
  branch requires `oracle.section_exists(title, section)` to be true. Zero
  rows can satisfy both, and the `usc_section_corrected is not None` gate on
  each stops any accidental ordering interaction regardless.
- `cfrNoteVerdictRows`, `cfrNoteVerdictTexts`, `cfrNoteCoverage`,
  `uscSlotReadingRows`, `placeholderCandidateRows`, every U.S.C. verdict
  census (`uscSectionVerdictRows` etc.) — this rule never writes
  `usc_section_verdict`/`_reason`/`_attested_at_edition`, and reads the CFR
  notes without touching the columns `_judge_against_cfr_notes` writes.

### Row-level (parquet byte) deltas

666 rows in `unified_agenda_legal_authorities.parquet` move from
`usc_section_corrected IS NULL` to non-null:

- `usc_section_corrected_section` = the B8 lettered identity (e.g. `18a`)
- `usc_section_corrected_pinpoint` = NULL on all 666 (B8 names a SECTION,
  never a pinpoint into one — confirmed: `promoted_verdicts_on_bare_section`
  is `{"exists": 666}` and no row carries a non-null pinpoint)
- `usc_section_corrected` = same as `usc_section_corrected_section` (no
  pinpoint to append)
- `usc_section_correction_evidence` = `"B8-two-witness-lettered-section"`

No other column on any row changes. Schema is unchanged (no new column) —
`LEGAL_AUTHORITIES_SCHEMA`'s `arrow_schema_sha256` does not move; the
parquet file's own `file_sha256` does, for these 666 rows' bytes.

### Producer block (expected, not new)

`receipt.json`'s `producer.modules` digests for `unified_agenda_parquet` and
`usc_section_oracle` will move (both files edited). **This was already true
before this lane started**: `citation_grammar.py`, `identifier_shapes.py`
and `managed_vocabulary_bundle.py` were already modified by concurrent
lanes at the start of this wave (see the session's initial `git status`),
so `tests/test_unified_agenda_parquet.py::test_the_receipt_names_the_code_that_wrote_it`
was measured RED before this lane touched anything. It stays red until the
integrator's combined rebuild re-pins `receipt.json`'s producer block — this
is the one pre-existing, wave-wide, pending-rebuild test failure, not a
regression this lane introduces. Full suite with this lane's 12 new tests
included: `tests/test_unified_agenda_parquet.py` — 137 passed, 1 failed (the
pre-existing producer-drift test above), 138 total. Before this lane's own
tests existed the same file measured 125 passed / 1 failed / 126 total —
the drift failure predates every change in this lane.
`tests/test_usc_section_oracle.py` — 79/79 passed, unaffected by the
docstring-only edit.

## The LONE:B8 population (rider #1 — the census hole)

Measured directly, not copied from the mined doc: **1,439 rows / 208 distinct
texts / 291 distinct RINs** have `oracle.correction_candidates(title,
section, text)` return EXACTLY ONE surviving candidate (`fenced_by is
None`), and that candidate's rule is the oracle's own
`"B8-lettered-section-rather-than-a-pinpoint"`. Before this lane, every one
of these rows appeared in NEITHER `uscSectionCorrectedRowsByRule` (B8 never
`.corrects`) NOR `uscSectionCorrectionRefusalRowsBySurvivors` (that census
only fires past one candidate) — the exact hole `inv-b8` names. The fix is
`uscB8PromotionRows`, a dedicated census (matching `uscC3PromotionRows`'s
own precedent of a separate key rather than retrofitting the two existing
ones), whose three outcomes are asserted in code
(`test_b8_two_witness_census_accounts_for_every_lone_b8_row`) and in the
measurement script (`assert sum(counts.values()) == lone_b8_rows`) to always
sum to the full LONE:B8 population.

**This number (1,439) disagrees with the mined doc's cited 1,276, and the
measurement is trusted over the citation.** Three reasons, all confirmed by
reading the oracle's own candidate list rather than re-deriving a
structure-verdict heuristic:

1. This is measured 2026-09-01 against the artifact as it stands after this
   wave's other landed units (the annual-archive case-fix, the six
   initialism retiers, the paren-suffix promotion, etc.) — a different
   corpus state than whatever the mined doc's own count was taken from.
2. The mined doc's own exploratory script (`inv-b8/measure_b8.py`) computed
   its "witness1-no-such-subsection" bucket from `subsection_verdict(...)
   .verdict == "absent"` ALONE, without checking whether the bare section
   prints ANY OTHER lettered subsection. The oracle's own
   `correction_candidates` does check that (`structure.verdict == "absent"
   and not structure.lettered`): where a bare section prints SOME lettered
   subsections but not this one — 42 U.S.C. 8287 prints (a), (b), (c) but not
   (d) — `parse-as-filed` still competes, so this is a TWO-candidate row, not
   a lone B8 one, in production. The mined doc's structure-bucket count does
   not draw this distinction and over-counts it.
3. This function's gate is exactly the oracle's own multi-candidate
   arithmetic (`len(survivors) == 1`), asked through the SAME public method
   `_judge_usc_sections` already calls — never a re-derived regex — so it
   cannot diverge from what a real rebuild's own correction/refusal census
   would show for these rows.

**One latent divergence, named at the gate rather than fixed.**
`_judge_usc_sections`'s refusal census counts at `len(candidates) > 1` with
fences IGNORED, while this gate asks what SURVIVES them. The two agree over
this whole population today, because no fence in the oracle can strike a
candidate on a bare-digit section — which is all this loop ever sees. Add a
fence that can, and a row struck down to one lone survivor would be counted
BOTH in `uscSectionCorrectionRefusalRowsBySurvivors` and in
`uscB8PromotionRows`. Survivors is the right question here (it is what
`corrected_section` itself asks); the refusal census, not this gate, is what
would then need to move. The equivalence and its divergence condition are
now a comment at the gate itself.

## The promoted population (the enlargement itself)

**666 rows / 134 RINs / 103 distinct texts / 37 distinct (title, bare
section) pairs / 59 distinct (title, corrected identity) targets.** Every
one reads `exists` on its bare section today
(`promoted_verdicts_on_bare_section: {"exists": 666}`), matching `inv-b8`'s
own claim for its (larger, differently-scoped) population. Witness
attribution: 476 by note alone, 71 by sibling edition alone, 119 by both.

**This is smaller than `inv-b8`'s cited 1,171 readings / 1,166 rows, by
design, not by accident.** Two deliberate narrowings, both explained in
`_promote_two_witness_b8`'s own docstring and proven by the two raw-source
regressions below:

- **Witness 2b is structural only** (`_CitationHistory.usc`, an exact
  `(title, section)` match against another row's own PARSED citation for
  the same RIN), never a re-derived raw-text regex. The mined survey's own
  "text-spells-NNNx" signal (2,061 of its 2,083 witness-2b-firing readings)
  is NOT reproduced here — **and measuring it properly shows there is
  nothing there to reproduce**: see "The text-scan witness is
  measured-empty" below. Both conflict specimens further down show exactly
  the kind of false corroboration a hand-rolled boundary produces where the
  parser's own structural fields do not.
- **Exactly one oracle candidate, not a structure-bucket heuristic** (see
  point 2 above) — narrows the LONE:B8 population itself, which narrows
  everything downstream of it. This is the larger of the two narrowings and
  the one that actually holds back real corroborated rows; it is quantified
  in its own section immediately below.

### What the sole-survivor gate excludes (quantified, and a follow-up unit)

The mined PUBLISH rule required only the subsection-oracle witness plus one
corroborator; the shipped rule adds "and B8 must be the oracle's SOLE
surviving candidate." That extra condition is a real narrowing, and this is
its size. Measured 2026-09-01 by
`research/evidence/b8-enlargement-2026-09-01/measure_b8_excluded.py`, which
replays the shipped rule's own three questions (`correction_candidates` with
fences applied, `_held_parts_by_rule` + `notes.judge`, `_CitationHistory`'s
`(title, section)` key) over every row where a B8 candidate survives:

| population | rows |
| --- | --- |
| B8 survives, ALONE (the shipped rule's population) | 1,439 |
| B8 survives ALONGSIDE another candidate (excluded by the gate) | 12,457 |

and the excluded 12,457, broken down by what the two witnesses WOULD have
said had the gate not fired first:

| would-be outcome | rows |
| --- | --- |
| held note names the BARE section (counter-evidence; would refuse anyway) | 6,469 |
| witnessless (would refuse anyway) | 4,086 |
| **would publish on witness 2a alone** (note names `NNNx`, never bare) | **917** |
| **would publish on witness 2b alone** (a sibling row parsed `NNNx`) | **533** |
| **would publish on both witnesses** | **452** |

**1,902 rows are witness-corroborated, conflict-free, and blocked only by
the sole-survivor gate** — 2.9× the 666 this lane publishes. So "smaller
than `inv-b8`'s 1,171" is mostly this, not the structural-witness choice.

**The gate stays.** A second surviving candidate means the oracle's own
structural witness never cleared the bare reading, which is precisely the
question B8 alone cannot answer — and the one specimen this wave read raw
and found BAD, RIN 1904-AC49's `"42 U.S.C. 8287 to 8287(d)"` range residue,
is a multi-candidate row. Publishing the 1,902 would publish that shape's
whole class on the same evidence that makes 1904-AC49 look corroborated.

**Candidate follow-up unit: "multi-candidate two-witness enlargement."** It
needs its own review, not a flag flip, because its population contains the
one known-bad specimen this wave found, and because the competing candidate
is usually `parse-as-filed` — meaning the bare section really does print
SOME lettered subsection, so "the filer meant a subsection" is a live
reading the LONE population never has. The unit's first job is a raw read of
a sample of the 1,902 against their own filings and notes, deciding whether
the competing candidate's identity (`parse-as-filed` versus something else)
changes the answer; the 1,902 is an upper bound on what it could publish,
never a forecast.

### Raw-source specimen: the positive case (why the enlargement is safe)

RIN **3084-AB46** (FTC premerger notification rules), `authority_text`
`"15 U.S.C. 18(a), Clayton Act"`, filed identically across **17** editions,
201704–202504 (measured: `measure_b8_excluded.py` step 6 lists all 17
`publication_id`s; `_promote_two_witness_b8`'s docstring said 19 until
2026-09-01 and now says 17 — the 19 was the corpus-wide bare-`15 U.S.C. 18`
row count, see the consumer-safety note below, not this RIN's editions),
`usc_title=15`, `usc_section="18"`,
`usc_section_verdict="exists"`, `parse_status="partial"` (the grammar
already refuses the `(a)` pinpoint, since §18 prints no lettered
subsections). This is the EXACT specimen the oracle module's own docstring
names as B8's demotion (module docstring, "B8 is a candidate, A4 and B1 are
corrections"): §18 and §18a are both real, so B8's one witness cannot tell
"filer meant 18a" from "filer meant a subsection §18 never printed."

The corroborating fact is outside the oracle. The rule's own held CFR part,
**16 CFR Part 801**, states its authority verbatim (read from
`research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl`, line 2255):

> `"Authority: 15 U.S.C. 18a(d); 15 U.S.C. 18b."`

18a stated with its own pinpoint, 18b beside it, bare 18 **never named at
all**. `notes.judge(usc_citation(15, "18a"), {(16, "801")})` returns
`present`; `notes.judge(usc_citation(15, "18"), {(16, "801")})` returns
`near-miss` (one edit away, correctly not `present` — no counter-evidence).
This is witness 2a firing cleanly, with no conflict, and is exactly why the
two-witness form is a different, stronger rule rather than a re-promotion:
a single witness proved wrong once here (that is the whole demotion); an
INDEPENDENT second one, read from a document the filer never wrote, is a
different claim.

**Reconciling the "19 rows" exposure figure.** `ledger-2026-08-22`'s
verification notes measured that a naive B8 promotion would move 19 rows off
bare `15 U.S.C. 18`. Measured 2026-09-01, those 19 are the whole corpus's
bare-`15 U.S.C. 18` population and split across BOTH FTC premerger RINs
filing the identical `authority_text`: 17 rows of 3084-AB46 and 2 of
predecessor 3084-AB32 (201604, 201610). This rule promotes all 19 — 17 + 2
in `promoted_rows.jsonl`. The function's docstring previously read "19
editions" for 3084-AB46 alone and "those 19 rows are RIN 3084-AB46's"; both
are now corrected to the measured split.

### Raw-source specimen 1 of 2: the range residue (RIN 1904-AC49)

`inv-b8`'s exploratory survey flagged 8 readings where the note names the
bare section (live counter-evidence, rider #2) that would nonetheless "still
publish" via its own witness-2b signal. 5 of the 8 are RIN 1904-AC49,
`authority_text` `"42 U.S.C. 8287 to 8287(d)"` (editions 201610–201810).

Reading the row's own parsed fields (not just its text) shows this is not a
B8 shape at all: the SAME RIN's 201110–201410 editions carry the identical
citation typeset as `"42 USC 8287 to 8287d"` and parse CLEANLY as a RANGE —
`usc_section="8287"`, `usc_section_end="8287d"`, `parse_status="ok"`. A
later re-typesetting added a parenthesis around the range's far-end letter
(`"8287(d)"`), which the range reader does not handle
(`usc_section_end=None`, `parse_status="partial"` on those later editions) —
but the underlying citation is still "8287 through 8287d," never a
parenthesised pinpoint on bare 8287.

`oracle.correction_candidates(42, "8287", "42 U.S.C. 8287 to 8287(d)")`
confirms it structurally without any range-specific code in this lane's own
gate: 8287 prints THREE real lettered subsections — (a), (b), (c) — so
`parse-as-filed` competes alongside B8. Two candidates survive, not one, and
this function's own "exactly one candidate" requirement excludes the row
before the note or history is ever consulted —
`test_b8_two_witness_excludes_a_range_residue_with_a_competing_candidate`
proves this even where a note WOULD otherwise corroborate the range's far
end as if it were a lettered section. The exploratory script's raw
`re.finditer` over the whole text, with no positional tie to which "8287"
in the string is the row's own parsed section, is what manufactured this
population member in the first place.

### Raw-source specimen 2 of 2: the hyphenated neighbour (RIN 3060-AK40)

The other 3 of the 8 flagged readings are RIN 3060-AK40,
`authority_text="47 U.S.C. 615(a) and 615(b)"` (editions 202410, 202504,
202510). 47 CFR Part 4's real authority note (same source file, line 6893)
reads in part:

> `"...301, 303, 307, 309, 316, 332, 403, 615, 615a-1, 615b, ..."`

Bare 615 AND 615b AND **615a-1** are named — never 615a. This alone would
already refuse the row correctly under rider #2's counter-evidence gate
(`notes.judge` on bare `615` returns `present`). But it is also worth
reading why the exploratory survey's OWN witness-2b signal fired for this
row at all: its "sibling edition spells it" check matched the bare string
`"615a"` inside a SIBLING EDITION's text `"...615a-1, and 615c..."` — its
boundary regex excluded `[0-9a-z]` after the match but never a following
HYPHEN, so `"615a"` sitting inside `"615a-1"` (a different, real, separately
enumerated section — confirmed: `oracle.section_is_enumerated(47, "615a-1")
is True`) passed as if it were a bare, standalone "615a" citation.

`_CitationHistory` cannot make this mistake: it keys `usc` by the EXACT
`(title, section)` a sibling row's OWN PARSER produced, so a sibling stating
`usc_section="615a-1"` lives at that exact key and never satisfies a lookup
for `(47, "615a")`.
`test_b8_two_witness_history_requires_an_exact_identity_not_a_hyphenated_neighbour`
proves this directly (a synthetic sibling stating `"615a-1"`, asserting the
target row still refuses).

**Both specimens refuse under this lane's shipped rule, and each for a
reason independent of the counter-evidence rider itself** — confirmed live
against the current artifact: `measure_b8_two_witness.py`'s own output
prints `usc_section_correction_evidence values across its rows = {None}`
for both RINs.

## Rider #2 — the counter-evidence decision

**Decision: conservative refuse.** Where the SAME held CFR note names the
BARE section `present`, this function refuses regardless of what witness 2b
says (`counts["note_names_bare_section"]`, checked and short-circuited
BEFORE either witness is asked). `inv-b8` measured 147 such conflicts under
its own definitions; this lane's narrower population measures **319** rows
hitting this refusal (a different denominator, the same decision).

**Those 319 are two different note shapes, and only one of them is the note
choosing a side.** Measured 2026-09-01 by `measure_b8_excluded.py`:

| shape | rows | what the note is doing |
| --- | --- | --- |
| bare-only — names `NNN`, never `NNNx` | **65** | genuinely choosing the bare reading; refusing is reading it |
| both-named — names `NNN` AND `NNNx`, each `present` | **254** | choosing nothing |

**The bare-only 65 include this wave's own raw-read specimen.** RIN
3060-AK40 (3 rows, editions 202410/202504/202510) holds 47 CFR Parts 0, 4
and 63; measured against those held parts, `notes.judge(47 U.S.C. 615)` is
`present` and `notes.judge(47 U.S.C. 615a)` is `near-miss` — Part 4's note
names 615, 615a-1 and 615b, and never 615a, exactly as the raw read below
found. So the smaller sub-population is the one holding a specimen we read
to the page and confirmed the refusal for, which is why its fixture is the
one that must never loosen. (The other specimen, RIN 1904-AC49, is not in
this population at all: `correction_candidates(42, "8287", "42 U.S.C. 8287
to 8287(d)")` returns TWO survivors, so it sits in the 12,457 the
sole-survivor gate excludes — re-confirmed 2026-09-01.)

The both-named majority is the honest correction to the rationale this file
and the function's docstring both carried until now ("the note itself is
choosing the bare reading over the lettered one"): for 254 of the 319 that
sentence is simply false. A note naming both fires witness 2a and the
counter-evidence from ONE document, and neither outranks the other. The
refusal for those 254 is a conservative default, not a reading — and
arguably over-conservative, since a LONE row's bare section prints no
lettered subsection at all, so a note that names `NNNx` is naming it for
some reason. **Both shapes stay refused in this lane**, and both are now
pinned by their own negative fixture
(`test_b8_two_witness_refuses_where_the_notes_own_part_names_the_bare_section`
is the both-named shape — its note `"Authority: 16 U.S.C. 715, 715i."`
reads as two citations, asserted in the test itself — and
`test_b8_two_witness_refuses_where_the_note_names_only_the_bare_section` is
the bare-only shape). Each catches a loosening the other misses: narrowing
the rider to the both-named shape fails the bare-only fixture, and
publishing the 254 fails the both-named one (both mutations performed
2026-09-01).

**Candidate follow-up unit: "the 254 both-named refusals."** Its first job is
a raw read of a sample of those 254 notes against their own filings —
whether a note naming both sections is a rule that genuinely amends both, or
a note whose bare-`NNN` naming is a delegation rather than an amendment.
Not a flag flip: nothing in this lane's own raw reads argued for widening it,
which is why it is refused today.

## The text-scan witness is measured-empty (correcting an earlier claim)

Earlier drafts of this file and of `_promote_two_witness_b8`'s docstring said
the structural-only witness 2b left "real signal on the table" and that a
future unit could widen it to a bounded text scan. **Measured, that is
false.** Over the 454 rows this rule refuses as witnessless, a bounded
same-RIN text scan — the mined survey's own pattern plus the boundary it
lacked, a following HYPHEN excluded alongside a following digit or letter —
matches **0 of 454** (`measure_b8_excluded.py`, step 3; the reviewer's
independent bare-token proxy also returned 0). The mined survey's 2,061
"text-only" witness-2b hits ARE that missing boundary — the same artifact
both raw-source specimens below expose — not corroboration this narrower
version declines. **No follow-up unit should be spun up to recover them.**

No row needed the REF-058 hand-validated-flag channel
(`hand_validated_interpretations.py`). Both specimens the mission named as
needing this deliberate call were read against their raw sources in full
above, and in both cases the note is NOT damaged — it is telling the truth
(RIN 1904-AC49's row is not even a real B8 candidate once its own parse
history is read; RIN 3060-AK40's note genuinely, deliberately authorizes
615a-1 and not 615a). Nothing here overrides the conservative default with
a hand-verified exception, and nothing found in this lane's own raw reads
argued for one.

## What this lane deliberately did NOT do

- **No raw-text scan for witness 2b**, and — corrected against measurement —
  nothing is lost by that. A bounded scan finds 0 of the 454 witnessless
  rows; see "The text-scan witness is measured-empty" above. This wave's own
  two false-positive specimens are why an UNBOUNDED one is not added.
- **No widening to multi-candidate rows.** 1,902 witness-corroborated,
  conflict-free rows sit behind the sole-survivor gate; quantified above and
  named there as a follow-up unit with its own review, because the one
  known-bad specimen this wave read raw lives in that population.
- **No widening to the 254 both-named counter-evidence refusals.**
  Quantified under rider #2 above and named there as a follow-up unit.
- **The LONE `parse-as-filed` rows still land in no census — a known,
  unclosed, population-shaped hole.** `parse-as-filed` is the OTHER member of
  `usc_section_oracle.CANDIDATE_ONLY_RULES`, so a row where it is the sole
  surviving candidate has exactly the same problem `inv-b8`'s rider #1 named
  for B8: `_judge_usc_sections` writes no correction (candidate-only rules
  never `.correct`) and no refusal (`refusal_rows_by_survivors` only fires
  past one candidate), so the row is counted nowhere. This lane's rider was
  scoped to LONE:B8 and `uscB8PromotionRows` closes exactly that, honestly
  and no more. The remaining hole is pre-existing, is not a regression this
  lane introduces, and is population-shaped rather than hole-shaped: closing
  it properly means one census over every candidate-only lone survivor, not
  a second bespoke key. Recorded here so it is a known gap rather than a
  silent one.
- **No `publication_id` filter on witness 2b.** A sibling row in the row's
  OWN edition is accepted, not just a cross-edition one: a rule filing two
  citations in one edition files two parsed rows, and the row can never
  witness for itself (its own `usc_section` is the bare `NNN`, never
  `NNNx`). Measured: of the 71 rows witness 2b alone promotes, 70 are
  corroborated across editions and 1 within one. Documented in the
  function's witness-2b paragraph rather than filtered out.
- **No change to `usc_section_oracle.py`'s executable code.** B8 stays
  candidate-only there; `CANDIDATE_ONLY_RULES`,
  `Candidate.corrects`/`Correction.__post_init__`'s refusal, and every
  existing oracle test are untouched. Only a forward-referencing docstring
  addition, so a future reader of that module is not misled about why a
  DIFFERENT module can publish a corroborated subset.
- **No retrofit of `uscSectionCorrectedRowsByRule` /
  `uscSectionCorrectionRefusalRowsBySurvivors`.** The LONE:B8 hole is closed
  with a dedicated census key, matching `uscC3PromotionRows`'s own
  precedent, not by reshaping the two pre-existing dicts (which are computed
  and returned before this rule ever runs).
- **No shared rebuild.** `output/` is untouched by this lane; every number
  above is a read-only, in-memory replay against the artifact this checkout
  already carries.

## Reproduction

```
.venv/bin/python research/evidence/b8-enlargement-2026-09-01/measure_b8_two_witness.py
.venv/bin/python research/evidence/b8-enlargement-2026-09-01/measure_b8_excluded.py
.venv/bin/python -m pytest tests/test_unified_agenda_parquet.py -k "b8 or held_parts_by_rule" -q
.venv/bin/python -m ruff check src/refspec/registry/unified_agenda_parquet.py src/refspec/registry/usc_section_oracle.py tests/test_unified_agenda_parquet.py
```

`measure_b8_two_witness.py` measures what the rule PUBLISHES (writes
`summary.json`, `promoted_rows.jsonl`); `measure_b8_excluded.py` measures
what it deliberately DECLINES (writes `excluded_summary.json`) — the
sole-survivor gate's excluded population, the counter-evidence rider's two
sub-populations, the bounded text-scan proxy, the appendix count, witness
2b's edition spread, and the FTC specimen's own edition list. Both call the
shipped helpers and the oracle's own public methods; neither writes anything
outside this directory. Every bolded number in this file comes from one of
the two.

## Caveat for the integrator

These numbers are measured against the artifact as this checkout carries it
today, not a fresh rebuild — forbidden for this lane. Other lanes' changes
to `citation_grammar.py`, `identifier_shapes.py` and
`managed_vocabulary_bundle.py` (already dirty at this wave's start) may move
`usc_section`, `authority_text`, or the CFR-references join upstream of this
rule before the combined rebuild runs, which would shift the exact counts
above (the LOGIC and its riders would not change). Re-run
`measure_b8_two_witness.py` against the freshly rebuilt artifact and diff
its `summary.json` against this file before treating `uscB8PromotionRows`
as final; a drift here is expected to be small and attributable to those
other lanes' own declared deltas, not to a defect in this one.
