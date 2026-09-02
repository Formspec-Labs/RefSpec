# Unit B — Statutes-at-Large page lists read as U.S.C. sections: declared receipt deltas

Mined ledger item 4 (`research/investigations-mined-2026-08-31.md` ~lines
77–85, a new find, in no README). Fix:
`src/refspec/registry/citation_grammar.py` (the lexical mark) +
`src/refspec/registry/cfr_authority_notes.py` (the note-side oracle gate).

## Design decision: where the gate lives

**The gate belongs in `cfr_authority_notes.py` for the note path, and the
LEXICAL FACT it gates on belongs in `citation_grammar.py`, shared.**

Verified before deciding: the resumed-list-after-Stat. reading happens
inside `citation_grammar._USC_LIST_TAIL`'s window scan, the SAME shared
mechanism `parse_authority_citation` uses for both callers —
`cfr_authority_notes.read_note_citations(note_text)` and
`unified_agenda_parquet.py`'s own read of a filer's `authority_text` box.
One shared bug, two callers, confirmed by measurement
(`measure_marked_population.py`): 129 notes / 403 marked citations, and 3
distinct filer `authority_text` values / 4 marked citations / 40 rows / 3
RINs.

Given that, the shared fact — "this list member was reached by scanning past
a Statutes-at-Large citation" — is marked once, in `citation_grammar.py`
(`AuthorityCitation.usc_section_after_statute`), so both callers can gate on
it without duplicating the scan. `citation_grammar.py` cannot decide
accept/refuse itself: it has no section-existence oracle (the oracle imports
this module, so the reverse is circular) and the shape is genuinely
ambiguous — see the trap below. So it marks, and the DECISION is made by
whichever consumer can reach the oracle:

- **`cfr_authority_notes.read_note_citations`** (mine, this lane) gates
  directly: a marked citation is offered only when
  `UscSectionOracle.section_is_enumerated(title, section)` says so — the
  EXACT-list membership check, not the broader `section_exists` (which also
  affirms membership in a printed RANGE stub; see "why the stricter check"
  below). `CfrAuthorityNotes.from_file`/`from_repository` auto-load a
  default oracle when none is passed, so the *production* builder path —
  which calls `CfrAuthorityNotes.from_file(_CFR_AUTHORITY_NOTES_JSONL)`
  with no oracle argument at all, in `unified_agenda_parquet.py`, not this
  lane's file to change — is gated without needing an edit there.
- **The filer `authority_text` path** (`unified_agenda_parquet.py`) is NOT
  gated by this change. It is a separate reader from `read_note_citations`
  and this lane does not own that file. **Declared for the integrator**: the
  3 texts / 4 marked citations / 40 rows / 3 RINs in
  `marked_filer_texts.json` need the identical gate — check
  `parsed.usc_section_after_statute` on each `AuthorityCitation` the builder
  already reads via `parse_authority_citation`, and withhold or flag members
  `oracle.section_is_enumerated` (which the builder already has access to,
  per the B8 enlargement's own note that "both witness feeds already
  exist") does not affirm.

**Marking scope, checked 2026-09-01.** `usc_section_after_statute` is set on
the list-tail path only, so the question is whether another reader can stand
after a Stat. citation and read a bare number the same way. Measured over
all 42,677 authority values and all 8,240 notes: `_USC_TITLE_FORM`,
`_USC_TRANSPOSED_LABEL` and `_INTERNAL_REVENUE_CODE` never match after a
Stat. citation at all. `_USC_APPENDIX` does — 8 values, 24 notes — but every
one of them is an explicit self-naming anchor rather than a resumed member:
"5 U.S.C. app" behind "Pub. L. 95-452, 92 Stat. 1101" (the Inspector General
Act) and "(5 USC app p 534)" behind "64 Stat 1267" (Reorganization Plan No.
14 of 1950), read raw. A citation that states its own title cannot inherit a
wrong one, which is the whole shape the mark exists for. Zero exposure
outside the list tail.

## Why the stricter check (`section_is_enumerated`, not `section_exists`)

First measured with `section_exists`: 12 CFR 615's own fabricated "993"
(from "102 Stat 989, 993") was ADMITTED, because `section_exists` also
affirms membership in a broad printed RANGE stub
(`evidence=('annual-range','release-point-range')`), and low/mid-size
numbers coincidentally fall inside SOME title's range far more often than
they are individually enumerated. A wider check of the same population
(`8 CFR 280`'s note, "66 Stat. 173, 195, 197, 201, 203, 212, 219, 221-223,
226, 227, 230") showed `section_exists` admitting 7 of 9 fabricated page
numbers on range evidence alone. Switching to `section_is_enumerated`
(`UscSectionOracle`'s own "membership in the exact lists only" check,
already used elsewhere in this codebase for stricter candidate screening)
refuses every one of those 9 while still affirming every genuinely
enumerated FAA section in the 14 CFR 121 trap (`evidence=('release-point',
'annual')` for all eight checked). This raised the refused count from 228
to **266** and lowered admitted from 149 to **111** — see
`measure_deltas_vs_head.py` and `measure_gate_deltas.py`.

## The trap, held (raw source)

14 CFR 121's own authority note (`research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl`,
`cfr_title=14`, `cfr_part="121"`) reads (in full):

> Authority: 49 U.S.C. 106(f), 40103, 40113, 40119, 41706, 42301 preceding
> note added by Pub. L. 112-95, sec. 412, **126 Stat. 89**, 44101,
> 44701-44702, 44705, 44709-44711, 44713, 44716-44717, 44722, 44729, 44732;
> 46105; Pub. L. 111-216, 124 Stat. 2348 (49 U.S.C. 44701 note); …

After "126 Stat. 89" the list genuinely resumes with real 49 U.S.C. aviation
sections (44101, 44701, 44702, 44705, …), each `section_is_enumerated` ==
True with `evidence=('release-point','annual')` — the strongest evidence
class the oracle has. A blanket "refuse everything after Stat." would have
deleted these along with the fabrications. The fix admits them:
`read_note_citations` with the oracle recovers all of `49:44101, 49:44701,
49:44705, 49:44709, 49:44713, 49:44716, 49:44722, 49:44729, 49:44732`.

## The fabrication specimen, held (raw source)

12 CFR 615's own authority note (same cache) reads (excerpt):

> … (12 U.S.C. 2013, 2015, 2018, 2019, 2020, 2073, 2074, 2075, 2076, 2093,
> 2122, 2128, 2132, 2146, 2154, 2154a, 2160, 2202b, 2211, 2243, 2252,
> 2279aa, 2279aa-3, 2279aa-4, 2279aa-6, 2279aa-8, 2279aa-10, 2279aa-12); sec.
> 301(a), Pub. L. 100-233, **101 Stat. 1568, 1608**, as amended by sec.
> 301(a), Pub. L. 103-399, **102 Stat 989, 993** (12 U.S.C. 2154 note); sec.
> 939A, Pub. L. 111-203, **124 Stat. 1326, 1887** (15 U.S.C. 78o-7 note).

Three Stat. citations, three fabricated continuations, in this ONE note:
`12:1608`, `12:993`, `12:1887`. All three are refused by
`section_is_enumerated` — none is a real title-12 section by any evidence
class.

## The one documented residual: pre-existing wrong-title attribution meeting exact-enumeration coincidence

`8 CFR 281`'s own note (raw, excerpted): "8 U.S.C. 1103, 1221, …, 1330; 5
U.S.C. 301; Public Law 107-296, 116 Stat. 2135 **(6 U.S.C. 101 et seq.)**;
**66 Stat. 173, 195, 197, 201, 203, 212, 219, 221-223, 226, 227, 230**;
Pub. L. 101-410, 104 Stat. 890, …". The parenthetical "(6 U.S.C. 101 et
seq.)" is itself read as a U.S.C. anchor (title 6), and the LIST-TAIL
window that anchor seeds runs forward to whatever the NEXT anchor is —
which is nowhere nearby, so the far-away "66 Stat. 173, 195, 197, …" page
list is attributed to title 6. This particular failure mode — a list's
"governing title" being whatever U.S.C. citation happens to appear last,
however distant — **predates Unit B** and is not itself one of the #46
fences' concerns; Unit B's gate only decides whether a member reached this
way should be ADMITTED, not whether the attribution itself was sound.

Measured: `section_is_enumerated(6, "195")`, `(6, "201")`, `(6, "203")`,
`(6, "212")`, `(6, "226")` are all **True** — genuine title-6 Homeland
Security Act sections that happen to occupy that numeric neighborhood — so
these five are admitted despite being, in reality, INA page numbers under
the wrong title. `(6, "197")`, `(6, "219")`, `(6, "227")`, `(6, "230")` are
**False** and correctly refused. This is not solved here: an oracle answers
"does this identity exist," never "did the filer mean this identity,"
which is the same limit this module's own B8 two-witness rule and
near-miss bucket already carry. It is recorded, not hidden — in
`read_note_citations`'s own docstring, `CfrAuthorityNotes`'s docstring,
this file, and `test_the_statutes_at_large_gate_stops_a_pinpoint_page_from_reading_as_a_section`.

A rough characterization of scope: a manual digit-length pass over all 111
admitted-but-would-be-withheld citations found 73 with a 1–3 digit numeric
prefix (the length class most exposed to this collision) against 38 with 4+
digits (where a coincidental hit against an unrelated real section is much
rarer); the short-digit survivors concentrate in a handful of long,
multi-Act notes that name several U.S.C. titles across many Stat.
citations in one authority statement (17 CFR 240 and 249, 8 CFR 281, 22 CFR
51 among them). This was not resolved further within this unit's scope —
doing so would mean reconsidering how far a "last-stated title" is allowed
to govern a list, a broader question than the Statutes-at-Large gate.

## Measured population (trust this over the mined doc's 148/80/100/9/8)

Query: `measure_deltas_vs_head.py` — fetches HEAD's `citation_grammar.py`
AND `cfr_authority_notes.py` via `git show` (not a stored copy), builds the
real 8,240-note cache under both, and diffs every note's `usc` citation
identities.

| metric | mined doc | measured |
|---|---|---|
| total note citations, before | (unstated) | **35,043** |
| total note citations, after (oracle-gated, production default) | (unstated) | **34,777** |
| citations refused | 148 | **266**, across **107** notes |
| citations added anywhere (should be 0) | — | **0** (confirmed over the full 8,240-note cache) |
| notes affected (refused) | 80 | **107** |
| nonexistent identities among refused | 100 | not separately counted — every refused citation is `section_is_enumerated == False` by construction of the gate |
| corpus rows flipping verdict when fabrications are removed | 9 | not re-derived this session — the mined figure is about the CFR-reference answer-key comparison in `unified_agenda_parquet.py`, which this lane does not own or rebuild; the integrator should re-derive this after wiring the filer-side gate declared above |
| of those, filer boxes carrying the identical bug | 8 | **3 distinct filer `authority_text` values / 4 marked citations / 40 rows / 3 RINs** measured directly against the shared grammar (`measure_marked_population.py`) — a different basis than "corpus rows flipping," which needs the CFR-reference join this lane does not rebuild |

Our number is larger than the mined 148/80 because the marking runs the
grammar's own comprehensive list-tail scan across every note, not a
narrower hand-written detector — it also catches, for example, a note's
SECOND and THIRD Stat. citations in one value (12 CFR 615 above has three),
which a regex tuned to one occurrence per note would miss.

A further number, confirmed by `measure_gate_deltas.py`: comparing the
oracle-gated production default against this fix's OWN conservative
"no oracle" fallback (not the pre-fix baseline) shows **111 citations
across 40 notes** recovered by the oracle that the conservative default
would have withheld — proof the gate is doing real work in both directions
(refusing AND admitting), not just refusing.

## What an ABSENT oracle does, and what a DRIFTED one does

Two different facts, treated differently on purpose (added 2026-09-01 after
the lane review; `cfr_authority_notes._oracle_for_root`):

- **No sealed oracle directory in the tree**: `_default_oracle` returns
  `None`, `read_note_citations` withholds every marked citation, and the
  read is fail-CLOSED. Measured: 34,666 note citations against the gated
  34,777 — the 111 the oracle affirms are the cost, real ones included (14
  CFR 121's genuine 49 U.S.C. resume is in that 111).
- **A directory that is there but DRIFTED**: the error PROPAGATES. It used
  to be swallowed along with the absent case, which made a corrupted pinned
  artifact the one quiet failure in a repository that refuses drift out loud
  everywhere else (`_verify` for the note cache two lines earlier,
  `UscSectionOracle.verify` for the six tables).

Both are now pinned by tests rather than by this file:
`test_the_oracle_gate_is_pinned_by_the_count_it_moves` (34,777 with the
oracle, 34,666 without, difference 111) and
`test_a_drifted_section_oracle_refuses_instead_of_quietly_withholding`. The
count pin is what stops a silently oracle-less build from passing the suite
looking exactly like a gated one.

The oracle load is also memoized per repository root
(`_oracle_for_root`), so a second reader in the same process no longer
re-reads the six tables: measured 7.4 s for the first `from_repository` and
5.4 s for the second, against 7.4 s for both before.

## Declared pinned-literal updates (mine to make; done)

- `tests/test_cfr_authority_notes.py::test_the_section_order_is_the_oracles_over_every_section_the_notes_name`:
  distinct sections 5,820 → **5,755**.
- `src/refspec/registry/cfr_authority_notes.py`'s `CfrAuthorityNotes`
  docstring: 35,043 → **34,777** total citations, with the new movement
  narrated the same way the #46 fences' movement already was.

## Builder-side changes declared for the integrator

`unified_agenda_parquet.py` (not this lane's file) needs the same gate on
the FILER `authority_text` side: 3 distinct authority_text values / 4
marked citations / 40 rows / 3 RINs (`marked_filer_texts.json`). The builder
already has oracle access (per the B8 enlargement's own note that "both
witness feeds already exist" there), so wiring is a matter of checking
`AuthorityCitation.usc_section_after_statute` on whatever
`parse_authority_citation` calls it already makes and applying
`oracle.section_is_enumerated(title, section, appendix=appendix)` as the
gate — NOT `section_exists`, per the residual documented above. After that
lands, the "9 corpus rows flip verdict" / "8 filer boxes" figures from the
mined doc should be re-derived against the rebuilt artifact — this lane
could not re-derive them without rebuilding
`unified_agenda_cfr_references`, which is out of scope here.

Two further items, both in `unified_agenda_parquet.py` and so both out of
this lane's file ownership:

1. **Pass the builder's own oracle in.** The builder calls
   `CfrAuthorityNotes.from_file(_CFR_AUTHORITY_NOTES_JSONL)` with no oracle
   argument, so the reader auto-loads one — and the builder already
   constructs the same six tables for its own verdict pass. The auto-load is
   a fallback for a bare reader, not the right thing for a caller that
   already holds an oracle: `from_file(..., oracle=<the builder's own>)`
   makes the dependency explicit and drops one 2 s load per build.
2. **Record the gate in the receipt.** Nothing in the build receipt says
   whether the note gate was asked at all. On a tree with no oracle
   directory the read still succeeds, still verifies, and still produces a
   `--verify`-passing artifact — 111 citations lighter, with no key saying
   why. A "notes gate: oracle present" boolean (or the oracle's directory
   digest) beside the existing note-cache digest would make the two states
   distinguishable in the receipt as well as in the suite. The receipt keys
   belong to `unified_agenda_parquet.py`, so this is declared here rather
   than done.

## A note on this directory's own scripts

`measure_gate_deltas.py` used to print a "REFUSED" count beside the admitted
one and write a `removed_citations.json`. That half was structurally
incapable of being non-empty — the no-oracle read withholds every marked
citation, so its citation set is a subset of the gated one by construction —
and the file was always `[]`. It is deleted rather than fixed, and the
subset relation is now an assertion in that script instead of a metric that
could not fail. The refusal count against HEAD (266 across 107 notes) is
`measure_deltas_vs_head.py`'s, and always was.
