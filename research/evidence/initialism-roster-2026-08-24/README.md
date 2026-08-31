# The pinned initialism roster — what a filer's shorthand names, and on whose word

**2026-08-24.** 296 rows over 118 tokens, one row per (token, agency prefix,
year), each carrying the tier of evidence it actually stands on. Read at build
time by `src/refspec/registry/unified_agenda_parquet.py`, digest-pinned into
every receipt, and refused-without in `main()`, exactly as the Public Law
roster, the OFR subject index, the CFR authority notes and the Federal Register
document roster already are.

It exists because 610 rows of `unified_agenda_legal_authorities.parquet` say
things like `BBRA, sec 123`, `TSCA 305` and `PHS, sec 2718`, and **no record in
this corpus defines those letters**. The corpus's own `agency-roster-initialism`
oracle — the RIN's resolved acts first, then the agency's — answers when some
other filing at that agency spelled the act out. Measured against the artifact
built from `dc59a800`: for 487 of the 610 that oracle finds no survivor at
either level and this file is the only thing that can name the act; for 115 it
finds exactly one and only the row's SHAPE is in the way; and for 8 — every one
of them `MMA` at CMS — it finds three, which is a refusal this file must not
touch.

## The tiers, and why they may not be one column

The 2026-08-23 investigation
(`../investigations-2026-08-23/inv-initialisms/initialisms.csv`, the population
and the fetches this file is derived from) wrote a single `status` column in
which the word "pinned" covered both of these:

> `BBRA` → the Federal Register, CMS's own notice 00-8708:
> *"…the Medicare, Medicaid, and State Childrens Health Insurance Program
> Balanced Budget Refinement Act of 1999 (BBRA), that requires us to publish a
> notice…"*

> `ARRA` → *"the full name the investigator hypothesised resolves in the
> index"*.

Those are not the same claim. The second is the operator wave 5 measured
**inventing a wrong survivor 15.25% of the time even date-bounded** — which is
why `_ActOracles` deliberately holds no corpus-wide roster, and why this file
may not become one by the back door. Splitting the column is the whole point of
this directory:

| status | what the row stands on | rows | corpus rows |
| --- | --- | ---: | ---: |
| `pinned-quote` | a publisher's sentence, captured verbatim, digest and quote in the row | 22 | 124 |
| `reverse-pl-verified` | a Public Law number in the SAME authority text whose act's initials are the token | 15 | 7 |
| `self-glossing` | the filer's own row spells the name beside the token | 8 | 5 |
| `candidate-index-match` | the hypothesised name resolves in the pinned act index — **and nothing else** | 155 | 329 |
| `not-an-act:<type>` | the token is a directive, agency, treaty, reporter, standard, division letter or identifier | 62 | 122 |
| `ambiguous` | two readings survive; keyed by agency and still undecided | 26 | 10 |
| `belief-only` | no expansion pinned at all | 8 | 12 |

"corpus rows" is measured on the artifact built from `dc59a800`
(`legalAuthorities` = 799,126, 2,278 rows `other`/`failed`): rows whose text
carries the token, at that agency, that no grammar reads today. It is written
once per (token, agency) — a year-keyed token has several rows at one such pair
and repeating the count on each would report the same rows five times. The 609
here and the 610 above differ by one row, `16 USC dd to ee` (1018-AF64, Fall
1999), whose `ee` is a token this roster carries at two other agencies and not
at 1018: no row, no count, and no answer.

**`candidate-index-match` may not resolve a row on its own.** The builder
admits it only where the RIN's or the agency's own resolved-act roster already
holds that act — the fence that carries the accuracy — and otherwise records it
in `act_resolution_evidence` as a candidate and resolves nothing. That is the
same fence `_read_abbreviated_act` has always used, asked a different way: the
corpus roster cannot reach the act *by its initials* (`USPHSA` is not `PHSA`;
`BBRA` is not `MMSBBRA`), and the roster row supplies the letters while the
corpus still supplies the act.

## What the roster never does

**It does not break a tie.** Where the corpus's own roster reaches two or more
acts, the row stays refused and this file is not consulted — `MMA` at CMS
(0938) reaches three Medicare acts by initials alone, and `mma, sec 811`
(0938-AQ16, Fall 2010, ordinal 3) is refused on that count even though this
roster carries an `MMA`/`0938` row naming Pub. L. 108-173. A roster entry is
evidence about letters. It is not evidence about which of two acts a filer
meant, and the exactly-one-survivor rule is older and better founded than this
file.

**It does not travel.** Every row is keyed to the four-digit RIN agency prefix
whose filings the evidence was gathered from. `BBRA` is pinned at CMS because
CMS's own Federal Register notice glosses it; the row says nothing about `BBRA`
at some other agency, and a future filer writing those letters elsewhere gets
refused rather than answered.

**It does not resolve what is not an act.** 62 rows type their token instead:
`FSH 2709.11` is a Forest Service Handbook, `56 DCR 7413` is the *District of
Columbia Register*, `FIPS 140-2` is a standard, `Division BB, title I` is a
division letter, `NAFTA` is a trade agreement. Typing them is the answer;
resolving them would be the error. OLRC lists `DHS` as an also-known-as of the
DART Act, which is precisely why that token is typed `not-an-act:agency` and
never resolved.

**It does not pretend the index is complete.** Three names a resolving tier
carries are not listed in the pinned act index at all, and the row says so in
`notes`: the *Strengthening Medicare and Repaying Taxpayers Act of 2012* (real,
pinned by CMS's own rule 2015-04143, unlisted under any wording tried) and the
FY2009 and FY2023 National Defense Authorization Acts. A row through them
publishes the act's identity and an honest `act_not_in_index`.

## Keys that are not just a token

`NDAA` is not agency-ambiguous, it is **year**-ambiguous: every fiscal year is
a different act, so the key is (token, agency, year) over the five years #45
established, and bare `NDAA` with no year is `ambiguous` and stays refused.
`NDAA-17`, which four DoD RINs write as a single token, is its own row.
`FOIA` splits the same way — the 1966 act itself is not a listed name — and
`EPA`, `MMA`, `SAFE`, `DHS`, `USCG`, `INS`, `NPS` and `USA` are keyed by
agency because the letters mean different things at different filers: `EPA
1992` at the Forest Service (0596) is the Energy Policy Act of 1992, and `EPA
Acquisition Regulation` at 2030 is the agency naming itself.

## Provenance

`build_roster.py` derives this file from
`../investigations-2026-08-23/inv-initialisms/initialisms.csv` and nothing
else, and it will not write an act name it has not first put through
`resolve_act_name` against the pinned act index. No clock, no network:

```
uv run python research/evidence/initialism-roster-2026-08-24/build_roster.py \
    --artifact <a built unified-agenda-parquet directory>
```

The `--artifact` flag fills `rows_observed` and changes nothing else; without
it that column is empty and the 296 rows are byte-identical.

Each row cites the committed bytes its claim rests on:

| tier | `evidence_path` |
| --- | --- |
| `pinned-quote`, Federal Register | `../investigations-2026-08-23/inv-initialisms/raw/fr_*.json`, `fr_HSIA_2024-15790.xml` — the API responses as they arrived |
| `pinned-quote`, OLRC also-known-as | `../investigations-2026-08-23/inv-initialisms/raw/popularnames.headers.txt` |
| `reverse-pl-verified`, `self-glossing`, `candidate-index-match` | `output/usc-act-index-2026-08-22/usc-popular-names.parquet` |

The OLRC popular-names page itself (14 MB of HTML, `sha256:7cbacdbc…`) is **not
committed**; what is committed is the digest the investigation recorded for it
in that directory's `SHA256SUMS.txt`, the HTTP response headers of the fetch,
the quoted markup in `evidence_quote`, and — the check that actually runs — the
pinned act index artifact derived from the same publisher page, which every
`act_name` in this file is verified against on every regeneration.

## The 610 rows, by token

The largest populations this roster reaches, on the `dc59a800` artifact:
`BBRA` 40, `CAA` 36, `MIPPA` 29, `IIJA` 28, `NDAA-17` 25, `FLSA` 24, `BIPA` 23,
`TEA-21` 20, `HSIA` 18, `FSH` 18 (typed, never resolved), `DHS` 17 (typed),
`INA` 15, `BBA` 15, `NEPA` 15, `ARRA` 15, `MMA` 13, `DCR` 12 (typed).

More than half of them still need a **shape** as well as a name: the
whole-value regex `_ABBREVIATED_ACT_SHAPES` reads 286 of the 610 today and
refuses the other 324 before any oracle is asked (`42 USC BBA 4106`,
`CAA 112(d)(2) & (3)`, `NDAA-17 sec. 701`, lowercase `mma`). Widening it is
task #44's other half and is measured separately; this file answers the *name*
question and only that.
