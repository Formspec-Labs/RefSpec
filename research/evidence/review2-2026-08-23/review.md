# Visual review #2 — 200 links, ten classes, one tracer each (2026-08-23/24)

Seeded samples (seed 20260823, sorted (rin, publication_id, ordinal,
citation_ordinal) keys) over the rebuild-9 artifact (receipt
e88d9dca52d5c96daf7373c7348cee7ba1fb2d217ffc5ab03f725e55a2be095d,
799,126 rows). Ten Sonnet tracers, one per class, each reading every
sampled record IN FULL — all LEGAL_AUTHORITY boxes verbatim,
ADDITIONAL_INFO, ABSTRACT, every artifact row with its verdicts and
evidence — judging by eye with retrieval-only code; publisher checks
(uscode.house.gov, federalregister.gov, keyless) where truth needed them.
Samples and per-link notes are beside this file. The verdict vocabulary:
correct-as-labeled / label-overstates / wrong-value / missed-witness /
filer-error-confirmed (class H used correction-verified / plausible /
WRONG / should-have-refused).

## The table

| class | population | correct | missed-witness | wrong | other |
|---|---|---|---|---|---|
| A unstated/more-citations-follow | 6,876 | 19 | 1 (mid-list ellipsis) | 0 | — |
| B unstated/not-yet-determined | 5,461 | 16 | 4 (abstract names the act) | 0 | — |
| C unstated/none-off-form | 130 | 9 | 4 | 0 | 7 filer-error (real authority provably existed) |
| D failed/nothing-stated | 1,658 | 10 | 10 | 0 | — |
| E failed/sec-only | 624 | 2 | 16 | 0 | 2 filer-error |
| F failed/act-stated (34 rows) | 34 | 10 | 10 | 0 | — |
| G act_relative/act_not_in_index | 481 | 1 | 18 | 0 | 1 label-overstates |
| H absent WITH correction | 3,660 | 18 verified | — | **1 WRONG** | 1 plausible-unproven |
| I absent WITHOUT correction | 10,531 | 1 | 17 | 0 | 2 filer-error |
| J disposition-answered | 2,548 | 15 | 0 | 1 | 3 label-overstates, 1 filer-error |

Across 200 links: the READINGS are almost never wrong (2 wrong values,
both now tasked), the labels never hide a value, and refusals are honest
where no witness exists — but in the failed/absent classes a witness the
pipeline already holds on disk goes unused in roughly 40–90% of sampled
rows depending on class.

## The two wrong published values

**H (task #53).** A4 corrected `7 USC 8a(5)` → 8(a) on 3038-AD31 and
3038-AB50 (8 of the 11 CFTC A4 rows; 0 wrong among 3,349 FDA rows). The
token is the Commodity Exchange Act's OWN §8a, codified at 7 U.S.C. 12a —
the publisher's source credit says so verbatim — and §12a(5) is the
CFTC's general rulemaking authority the record's abstract fits. The B8
lesson recurring inside A4: a real base section with a real
matching-lettered subsection that is not the intended one. The pinned
source-credit index is the fence and the corrector.

**J (task #54).** The disposition columns are populated from usc_section
alone and never consult usc_section_end: `49 USC 1421 to 1431` stores
bare-1421's successors; `1 to 85 (app)` was queried as §1 only, and
probing §§2–27 adds successors in a different subtitle. A stated pinpoint
(`1651(b)(2)`) resolves to ONE successor in the printed table but has no
input column; and one dropped "ch" qualifier routed a current-law chapter
number into the pre-1994 table on magnitude alone, the row's own flags
contradicting each other (usc_appendix false, appendix reason).

## The systemic finding: the record carries its own answer key

Fourth review in a row to land on it, now with code-verified mechanics:

- **Shape-blindness (E; task #44 widened).** 18 of 20 sec-only rows never
  entered any carry rule's candidate population: `_BARE_SECTION_BOX` /
  `_TITLELESS_SECTION_BOX` are blind to a leading abbreviation (FLSA,
  BBRA, HSIA, MMA, IIJA, PL ####, HR ####), a trailing "of the [Act]"
  clause, a list, or a decimal. 16/20 had a nameable donor in the record.
- **The resolver's mechanics (F, G; task #56).** 18 of 20 `act_not_in_index`
  rows name real indexed acts: missing/extra year (the year rule supplies
  but never strips), dropped leading/trailing qualifiers, acronyms the
  pinned roster research already binds (PHS, FAIR, NAFTA, PPAC, Recovery,
  BBRA), one typo the record's own abstract corrects, one box-split name.
  The F year-fence conflates "Act as amended in YEAR" with "the YEAR
  amendments" (CAA §112 → 42 U.S.C. 7412 provably lost); the
  `_SECTIONS_OF_NAME` regex drops elided list members ("172(a) and (c)");
  a "(ESSA)" parenthetical breaks the trailing-year capture.
- **Witnesses on absent rows (I; #34/#36/#47 confirmed, #55 new).** 17 of
  20 uncorrected absents resolve to one verifiable referent via a sibling
  box, the pinned CFR authority note, or the RIN's own later edition. New
  wall: 4 of 20 are a WRONG UNIVERSE — Treasury regulation numbers
  (`26 USC 2032-1(c)` = 26 CFR 20.2032-1(c)) or a chapter in the section
  slot — and the schema has no namespace-correction field (task #55).
  Caution: `authority_in_own_cfr_note='present'` was once a coincidental
  artifact of the note's own rendering quirk (→ #38 cycle 2).
- **The abstract as witness (B, E, F, I; feeds #39).** Abstracts named the
  enabling act on unstated rows (4/20 in B), corrected two filer typos by
  eye, supplied years and glosses. Candidates only, never citations.

## Class-local truths worth keeping

- A: the ellipsis placeholder is honest; the one interesting case is a
  MID-LIST ellipsis (3235-AH00) and no column says where a box sits in
  its list. A third mangled-byte edition (U+0096 in 201304) is untracked;
  2020+ abstracts carry raw HTML (task #57).
- C: "none-off-form" splits — 11/20 provably mask real authority (adjacent
  editions carry the list; NHTSA's CFR_LIST still names the 49 CFR 1.95
  delegation), while EPA's guidance-only family and never-published
  withdrawals are genuine non-answers (taxonomy refinement in #57).
- D: half bookkeeping/honest dead-ends; the rest are the roster gap
  (BBRA between resolving BBA and MMA), named-subdivision joins
  ("Title V" after a PL box — R4/R5 only reattach numeric fragments),
  an OMB circular the schema has columns for, `94 Pub. L. 588` reordered,
  and R5 stopping after one box (all in #44/#56/#57).
- J: the FAA boilerplate blocks reproduce from the printed table
  row-for-row; candidates framing is honest everywhere a section splits.
- H: the FDA family (3,349 rows) is airtight — the filer's own abstract
  is a near-verbatim echo of 321(p)'s text.

## Actions taken from this review

#53 A4 fence + CEA corrections (priority: wrong published values);
#54 disposition spans/pinpoints/chapter guard; #55 wrong-universe
namespace readings; #56 act-resolver mechanics (year strip/supply,
elided members, parenthetical gloss, "Coop." walk); #57 edition/reader
hygiene (U+0096 edition, box-position context, HTML abstracts, unstated
taxonomy refinements); #44/#45 confirmed and widened by E/D/G; #34/#36/
#47 confirmed by I; #38 cycle 2 gains the note-artifact caution; #39
gains the abstract-witness cases. Verdict-level notes: notes/*.json.
