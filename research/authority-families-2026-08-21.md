# New authority families from the failed-pool residue

**2026-08-21, worktree branch `research/authority-families`.** The 12,2xx
still-failed authority rows clustered into families; each implemented family's
grammar is licensed by a verified source, and the yield below is measured by
re-parsing every failed text against the real pinned parquet — not estimated.

## Family table

| family | rows recovered | representative form | verifying source | status |
|---|---:|---|---|---|
| administrative_order | **734** | `Secretary's Order No. 3-2007, 72 FR 15907`, `DHS Delegation No. 0170.1(75)`, `Department of Commerce Department Organization Order 10-4` | DHS Delegation 0170.1 cited as legal authority in FR rulemakings ([FR 2003-5146](https://www.federalregister.gov/documents/2003/03/06/03-5146/authority-of-the-secretary-of-homeland-security-delegations-of-authority-immigration-laws), [OMB ICR](https://omb.report/icr/201810-1625-001/doc/87051901)) | implemented |
| eo_compilation (wiring) | **593** | `3 CFR, 1949 to 1953 Comp, p 1002` | grammar already existed (Title 3 compilation locator) — it was never wired into the authority parse | implemented |
| presidential_document | **538** | `Presidential Proclamation No. 7383`, `Proc 10414, 87 FR 35067`, `Presidential Memorandum of January 31, 2014`, `Notice of August 3, 2000 (65 FR 48347)` | proclamation series past 11037 by mid-2026 ([FR proclamations](https://www.federalregister.gov/presidential-documents/proclamations/donald-trump/2026), [Proc. 10998](https://travel.state.gov/content/travel/en/News/Intercountry-Adoption-News/presidential-proclamation-10998-on-restricting-and-limiting-the-.html)); memoranda/notices are date-identified, unnumbered | implemented |
| act_relative (subsection fix) | **459** | `Sec 1886(d) of the Social Security Act` | not a new family — a bug: the parenthetical between section and "of the" severed the name; verified `social security act` IS in the pinned OLRC index and the citation still failed | implemented |
| treaty | **51** | `27 UST 1087`, `T.I.A.S. No. …`, `1870 UNTS 167`, `S. Treaty Doc. 105-51` | Bluebook rule 21.4.5 preference list: UST → TIAS → UNTS → Senate Treaty Docs ([Georgetown](https://guides.ll.georgetown.edu/c.php?g=365734&p=2471175), [Brooklyn Law rule 21.4](https://guides.brooklaw.edu/treaty)) | implemented |
| constitution | **14** | `U.S. Const., Art. II, Sec. 2` | the appointments-clause citation; Roman article numerals in every observed form | implemented |
| usc_note flag | (upgrades, not recoveries) | `8 U.S.C. 1252 note` | LLSDC, ["The Authority of Statutes Placed in Section Notes of the U.S. Code"](https://www.llsdc.org/assets/sourcebook/usc-notes.pdf): notes are law printed under a section — a distinct place, like an appendix | implemented |

**Measured total: 12,202 → 9,813 still failed (−2,389, −19.6%).**

## What stays refused, and why (measured, not assumed)

- **Act abbreviations — `CWA 301` (63), `CAA sec 112` (63), `FLSA`, `NSLA`:
  several hundred rows.** Checked against the pinned OLRC popular-names
  parquet: `caa`, `cwa`, `flsa`, `nsla` are **not in the index**, as names or
  aliases. The identity fence holds: inferring which act an abbreviation
  means is the guess that once minted the wrong statute.
- **`Motor Carrier Act of 1935` (33): not in the OLRC index at all** — the
  Popular Name Tool simply lacks it. Stays `other`, honestly.
- **`US Cost, Art II, sec 2` (7): damaged "Const"** — reading it would guess
  which word was meant.
- **Bare numbers (`5676`, `1702`… ~398 rows)**: sections with their title
  lost; unrecoverable without invention.
- **Remaining prose** (~9,813 incl. the above): dominated by named
  conventions without numeric series cites, agency mission statements, and
  fragments.

## Builder columns the parquet would need (NOT implemented here — schema churn is coordinated centrally)

`presidential_doc_kind`, `proclamation`, `admin_order_kind`,
`admin_order_number`, `treaty_series`, `treaty_volume` (int32),
`treaty_number`, `treaty_page` (int32), `constitution_article`,
`constitution_section`, `eo_compilation_start`, `eo_compilation_page`,
`usc_note` (bool). Kinds vocabulary grows by:
`presidential_document`, `administrative_order`, `treaty`, `constitution`,
`eo_compilation`.

## Contradictions with existing-grammar assumptions found

1. **`parse_eo_compilation_locators` existed but was never consulted by
   `parse_authority_citation`** — 593 failed rows were readable by grammar
   already in the module.
2. **The act-relative "of the" adjacency rule was too strict**: a subsection
   parenthetical (`1886(d)`) severed the act from its name. The skip is
   bounded (parenthetical ≤12 chars, repeatable) so a parenthesized sentence
   still blocks.
3. `NSLA`-style trailing-abbreviation parentheticals (`National School Lunch
   Act (NSLA)`) fail the builder's bare-name equality; a builder-side
   trailing-paren strip before the bare-name retry would recover them —
   noted for the central builder, not done here.

## Checked and found empty

State statutes (`Rev. Stat.`/`Code Ann.` shapes): zero rows. Interstate
compacts other than the Compacts of Free Association: zero. Case-reporter
citations in the failed pool: already recovered by the parent's family. The
`housing-act-style` bucket (2,413 rows containing "Act") is mostly bare act
names and act names with `title I`-style (not section) markers — the former
depend on OLRC membership (some absent), the latter would need a
title-marker extension to `ActRelativeCitation` that nothing yet consumes.
