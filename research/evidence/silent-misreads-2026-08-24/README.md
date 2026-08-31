# Silent misreads, re-surveyed on rebuild #11 (2026-08-24)

A like-for-like re-run of `silent-misreads-2026-08-22.md`: the same frame
(`parse_status IN ('ok','partial','corroborated')`), the same seeded hash
draw (verified to re-derive the original 150 + 140 units bit for bit from
the as-measured parquet — see `samples/README.md`), the same rubric and
vocabulary, four independent reviewers who did not see each other's
batches, plus a paired re-check of the original's 13 flagged per-row
items. Artifact: rebuild #11, receipt ca8d7912…; frame 780,582 rows /
41,063 texts. New this run: every reviewer wrote the full per-item
verdict table to disk (`adjudication/*.tsv`), and every non-CORRECT item
is marked LOUD (the row carries a consumer-visible signal — an oracle
`absent`, a correction beside the original, a note near-miss, a refusal
or candidate column, a series flag) or SILENT.

## The two rates, before and after

| estimator | 2026-08-22 | 2026-08-24 | 95% CI (Wilson, today) |
|---|---|---|---|
| per row, strict misread | 11/150 = 7.3% | 10/150 = 6.7% | [3.7%, 11.8%] |
| per row, + dropped | 13/150 = 8.7% | 11/150 = 7.3% | [4.1%, 12.7%] |
| per text, strict misread | 21/150 = 14.0% | 16/150 = 10.7% | [6.7%, 16.6%] |
| per text, + dropped/unknown | 22/150 = 14.7% | 21/150 = 14.0% | [9.3%, 20.5%] |
| **per row, SILENT wrong** | 11/150 = 7.3% (no evidence columns existed) | **3/150 = 2.0%** | [0.7%, 5.7%] |
| **per text, SILENT wrong** | 21/150 = 14.0% (same) | **6/150 = 4.0%** | [1.8%, 8.5%] |

Read together: the rate at which the PARSED identity is wrong has not
moved — by design. This campaign never rewrote a parsed identity without
a witness (the reviews found what guessing costs: B8, A4's CEA edge); it
built oracles and fences that make a wrong identity LOUD, published
corrections beside originals where exactly one survivor exists, and
refused the rest by name. The number that measures that work is the
silent fraction: per row 7.3% → 2.0%, per text 14.0% → 4.0%.
Of the original 13 flagged per-row items, 3 are fixed outright, 6 are
loud, 3 still silent, 0 gone (`adjudication/paired-13.tsv`); of the
sixteen named classes, twelve are fixed or fenced, B1 has a live
correction rule, B6 is fixed narrowly, B3 and B8 stay open (B8 by design).

Per batch (units / by row weight for B): A_1: 75 units, 12 non-CORRECT · A_2: 75 units, 9 non-CORRECT · B_1: 70 units, 6 non-CORRECT (6/78 by weight) · B_2: 70 units, 5 non-CORRECT (5/72 by weight).

## What is still silent — the next targets, each measured in the sample

1. **Wrong universe in the U.S.C. slot** — `26 USC 1.104-1(c)` is a
   Treasury regulation read as 26 U.S.C. §1, and the note witness says
   "present" by coincidence (task #55). The residual failure mode the
   original's L2 lever warned about: existence checks catch nonexistent
   sections, not real-but-wrong ones.
2. **Executive Order numbers have no existence oracle** — `EO 8284` (a
   1939 Librarian Emeritus order; the rule meant EO 8248). A pinned EO
   roster (numbers, dates, titles; the Federal Register's keyless API)
   is the fence. New unit.
3. **`NNN(x)` where `NNNx` exists and no note witnesses the RIN's part**
   — `16 U.S.C. 620(f)` for 620f. B8-direction, candidate-only by design;
   the note now covers 91% of rows, so the residue is where the part is
   gone or names no note.
4. **Compact slash compounds drop their act half** — `42 USC 7401/CAA
   112`: one row, the CAA §112 authority vanishes with no row and no
   refusal, while the same RIN's later editions split it and resolve
   §112 → 42 U.S.C. 7412. New DROPPED class; count corpus-wide.
5. **"X to Y(z)" and in-list "X to Y" lose their endpoint** — three of
   75 texts: the far side of a range carrying a parenthesised subsection
   or sitting inside a longer comma list vanishes (no usc_section_end,
   no row, no flag) while bare-to-bare and hyphenated ranges keep it.
   New DROPPED class; count corpus-wide.
6. **A literal `332 USC 234 (1947)`** is a Supreme Court citation
   (the sibling `332 US 234` reads correctly); the row's
   usc_title_is_possible=false already marks it, but that flag was not in
   this survey's loud set — a consumer should read it as one.
7. **`60 CFR 15845` retyped to a Federal Register citation** because
   CFR has no title 60 — plausible, unverified, and the type change
   carries no flag. A flag column for scheme retypes.

Also recorded: the sampling script omitted `admin_order_kind/number`
from the per-citation dump (the parquet carries them; one reviewer had
to cross-check the table) — fix in the next draw; and
`statute_volume_matches_public_law` independently reproduced the
original's class A1 on `PL 89-56, 70 Stat 195` (the volume belongs to
Public Law 540 of the 84th Congress, confirmed from the govinfo PDF).

## Files

`samples/` (the draw, its README and manifest), `adjudication/A_1.tsv`,
`A_2.tsv`, `B_1.tsv`, `B_2.tsv` (every unit's verdict, loud/silent,
mechanism, decisive quote, publisher check), `adjudication/paired-13.tsv`.
