# The surfaces beyond the agenda: a measured inventory

**Date:** 2026-08-22
**Corpus:** `federal_register.parquet` (1,004,233 document rows), read where it
lives; nothing in it was modified.

Wave 3 named four surfaces it had not audited and asked for a measured
inventory rather than a grammar that pretends to cover everything. This is
that inventory, plus the three recoveries it licensed.

## Federal Register document numbers — one defect, one non-problem, one answer

**The validator was wrong, not the data.** It demanded exactly five sequence
digits. The Office of the Federal Register mints three, four, and five, and
pads some years and not others. All three spellings are real, each confirmed
against the publisher's own API:

| number | published | shape |
|---|---|---|
| `2010-5997` | 2010-03-19 | four-digit sequence |
| `2011-237` | 2011-01-11 | three-digit sequence |
| `2012-00019` | 2012-01-04 | zero-padded to five |

Widening the shape to a four-digit year and a three-to-five-digit sequence
admitted **28,862 real numbers** the validator had been refusing.

**The padded/unpadded join hazard does not exist**, which is worth more than
the fix. Across 480,852 modern-year values, **not one padded number has an
unpadded twin**. Padding is part of the identifier the publisher issues, so
the literal string is a safe join key; normalizing zeros would invent a
spelling nobody minted. Nothing rewrites it, and a test says so.

**`R1-` is republication.** The publisher states it in the documents
themselves: `R1-2010-13257` is *"Federal Property Suitable as Facilities To
Assist the Homeless; Republication"* (2010-06-04). 48 values, in both the
legacy-bodied (`R1-10679`) and modern-bodied spellings. It now joins
corrections as a family detected whole and refused for minting — real, but
outside the mintable space.

The other letter prefixes are the known electronic-filing era: E3–E9
(89,523 values), X94/X95 (2,842), C1 corrections (1,425).

## Docket references — 893,824 occurrences, 608,758 distinct

| disposition | distinct tokens |
|---|---|
| already a well-formed Regulations.gov identifier | 134,715 |
| recovered by strip-then-validate (label carries a real docket) | **100,514** |
| refused: not a Regulations.gov docket at all | 373,529 |

The recovery grew by 7,397 when the prefix stripper learned the punctuation
its own inline sibling already declared — agencies write `Docket #:`,
`Docket No.:` and `Docket -` for the same thing, and the two patterns for one
convention disagreed. Strip-then-validate still holds: `Docket #: 1` is
refused, because a label over something that is not a docket does not make it
one.

### What the 373,529 refusals actually are

They are not malformed dockets. They are **other agencies' own numbering
systems**, correctly refused, and each is its own family if anyone ever wants
one:

| leader | distinct | specimen | what it is |
|---|---|---|---|
| DOCKET… | 87,820 | `DOCKET #: RBS-X24BUSINESS-0016` | labelled, but the body is not a docket shape |
| RELEASE | 45,930 | `RELEASE NO. 33-8176` | SEC release numbers |
| FILE | 36,272 | `FILE NO. S7-08-22` | SEC file numbers |
| AMENDMENT | 13,879 | `Amendment # 1` | states nothing on its own |
| AD | 13,290 | `AD 2000-01-01` | FAA airworthiness directives |
| PUBLIC | 11,351 | `PUBLIC NOTICE #3744` | FCC/State public notices |
| I… | 9,926 | `I-017096 C, I-517 C, …` | ITA investigation lists (multi-valued in one cell) |
| PROJECT | 9,543 | `Project 0741` | FERC project numbers |
| TA | 7,901 | `TA W-58,809` | trade-adjustment petitions |
| FRL | 6,729 | `FRL #10-014` | EPA Federal Register Locator |
| NOTICE | 5,825 | `NOTICE (01-136)` | labelled notice numbers |
| AIRSPACE | 5,733 | `Airspace Dock No. 00-AGL-06` | FAA airspace dockets |
| RTID | 5,308 | `RTID 0048-XE284` | EPA regional tracking ids |
| DA | 5,297 | `DA #00-1875` | FCC daily-action numbers |
| DIRECTORATE | 5,097 | `Directorate Docket No. 2002-NM-203-AD` | FAA directorate dockets |
| OMB | 4,458 | `OMB # 0938-0534` | OMB control numbers, not dockets at all |

**Recommendation: do not write these grammars.** The column is a mixed bag by
construction — publishers put whatever number identifies their proceeding into
it — and each family above would need its own oracle to be worth minting. The
honest contract is the one now measured: a Regulations.gov docket is
recognised, a labelled one is recovered, and everything else is preserved and
refused by name. If a consumer ever needs FERC project numbers, that is one
family with one oracle, decided on its own merits.

## The FR API's RIN column — audited 2026-08-22, and the oracle was next door

Wave 3 measured 444 invalid tokens and left them because "each needs its own
corroborating oracle". They need **one**, and this repository already builds
it: the Unified Agenda's own roster of **46,562 RINs**. Held to the census's
machinery — named damage operators, pinned oracle, exactly one survivor —
the column decomposes completely (`wave5_surface_probe.py`):

| disposition | occurrences | distinct |
|---|---:|---:|
| **corroborated**: one operator, one roster survivor | **324** | 217 |
| refused: operator reaches a well-formed RIN the roster does not hold | 43 | 34 |
| refused: no operator reaches a RIN at all | 77 | 55 |

Three operators, each a single named substitution and each applied only in
the slot whose alphabet the RIN shape fixes (two letters, then two digits):

- **homoglyph** `0`↔`O`, `1`↔`I`, `5`↔`S`, `8`↔`B`, `2`↔`Z` — `0648-A082` is
  `0648-AO82`, `2060-A079` is `2060-AO79`, `1545-B012` is `1545-BO12`;
- **space for the dash** — `1625 AA00`, `7100 AD74`, `0581 AD83`;
- **a space inside the sequence** — `7100-AF 57`.

The two refusals are different kinds of thing and must not be merged:

- **43 occurrences reach a well-formed RIN the Agenda has never carried** —
  `1820 ZA34` (Education), `0648-X100` (NOAA fishery actions). These are not
  damaged Agenda RINs; they are RINs minted outside the Agenda, and the
  roster's silence is the roster's limit, not the value's defect. The fence
  refuses them and it is right to, but a consumer should know the reason
  differs from the next line's.
- **77 occurrences are not RINs**, of which **70 (48 distinct) are OMB control
  numbers filed in the RIN column** — `3235-0695`, `0648-0508`, and the
  self-describing `1625-1625` and `0691-0691`. A publisher's filing error is
  not damage this repository should silently repair. The remaining 7 are
  structurally alien (`3090-00XX`, `2127-ZRIN`, `0648-XD990`).

**This is report-only.** The recovery is real and measured, but the fix
belongs to the mint owner: `normalize_rin` answers "is this string a RIN",
and a corroborated correction is a different question that needs its own
column to state the original, exactly as the Agenda's `public_law_corrected`
does.

## `court_opinions.parquet`'s citation column — two schemes, one column

68 rows, and the column is not malformed at all — it is **two schemes with no
discriminator**, which is worse, because a consumer that validates it as one
gets sixteen opinions at a single key.

| scheme | rows | distinct | shape | what it locates |
|---|---:|---:|---|---|
| U.S. Reports citation | 31 | 31 | `608 U.S. 219` | a volume and a first page |
| preliminary-print part | 37 | 4 | `608/2` | a volume and a PART — no page |

`608/2` is not damage and not a citation: it is the Court's own designation
for an opinion bound for Part 2 of volume 608, written where a page will
eventually go. Sixteen opinions share it.

**The discriminator is already in the row, and it separates the two
perfectly.** Every U.S.-Reports row's source file is a bound release
(`608us1r32_g3bi.pdf` — volume 608, release 32); every part-locator row's is
a docket-numbered slip opinion (`24-43_2b35.pdf`). 31/31 and 37/37, no
crossover. Whoever validates this column should split it into a citation
(volume, page) and a print locator (volume, part) on that evidence rather
than on the string's punctuation.

`docket_number` mixes the same way and needs the same treatment: 65
certiorari numbers (`24-43`) and 3 application numbers (`25A312`), which are
different dockets on the Court's own numbering, not a damaged form of each
other.

## Still open, and named

- **GIPSA `-NONRULEMAKING` docket suffixes**: real, refused, specimens kept.
- **`federal_register.docket_ids_json`**: 495,330 of 716,090 tokens are
  agency-native schemes, each its own grammar. Still unaudited, still
  deliberately so — see the recommendation above.
