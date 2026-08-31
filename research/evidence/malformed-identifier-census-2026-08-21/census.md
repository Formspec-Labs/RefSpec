# Malformed-identifier census, and what each class became

**2026-08-21.** "Investigate all failing or malformed identifiers" — the full
anatomy of every row the Unified Agenda tables could not read, and the
disposition of each class. Before: 39,856 authority rows and 22,123 CFR rows
in undifferentiated failure buckets, plus 522 timetable citation failures.

## Authority field (755,727 publisher strings → 794,325 typed rows)

| class | rows | disposition |
|---|---:|---|
| placeholders ("Not Yet Determined", "...", "None") | 12,393 | **`unstated`** — a placeholder is not a failed parse; shared `UNSTATED_SENTINELS` |
| U.S.C. **appendix** ("50 USC app 2401") | 3,893 | `usc` + `usc_appendix=True` — the appendix is a different place from the title proper; merging them would conflate two bodies of law |
| CFR cited as authority ("49 CFR 1.95") | 6,563 | **`cfr`** — real citations in the wrong column, typed as what they are |
| act-relative ("Clean Air Act sec 112") | 4,282 | **`act_relative`** — the OLRC popular-name index is the grammar; 3,138 carry a section for `act_resolution` |
| Reorganization Plans ("No. 3 of 1970") | 693 | **`reorganization_plan`** — plans carry the force of law |
| EO plurals ("Executive Orders 13990 and 14008") | + | plural licenses a number list; one order was silently dropped before |
| case reporters ("123 F 3d 1460", "550 U.S. 544") | 72 | **`case_citation`** — a different family: locates a decision, not an enactment |
| **still `other`/failed** | **12,247** | treaties/conventions (78), Secretary's Orders, FLSA-style abbreviations the OLRC does not alias (the identity fence refuses to guess "INA"), genuine prose |

## Timetable FR citations (671,959 rows)

522 → **28** failed, in four passes: separator-damage tolerance in the
grammar ("78FR 63152", "82-FR 22190", "83 FR32768", zero-padded "62 FR
04670"); multi-citation rows exploded instead of failed ("81 FR 45095, 81 FR
45055"); and a **positional** read for values that are exactly two plausible
numbers ("71 66120", lost-F "76 R 11462") — labelled `positional`, never
`ok`, because the reading rests on the column's semantics rather than the
text. The fourth pass answered "if CFR is in the FR column, couldn't we still
use that?" with a measurement: **all 64** CFR-shaped values in the column have
an impossible CFR title (84, 79) beside a perfect FR volume/page — the text's
own numbers refute its claimed scheme, so the C is the damage and the rows
read as FR, labelled `relabeled`. The 28 that remain are genuinely
unreadable. Resolved-RIN join surface: **36,584**.

## CFR reference field

22,123 titleless rows decompose: **20,837 are placeholders** (the same
sentinel set — declared as `cfrReferenceUnstatedRows` in the receipt without
a schema change), 19 are correctly-excised Title 3 compilation locators, and
the residue is bare sections ("25.136"), subpart references ("subpart E"),
and prose fragments. The 159 impossible-title and 42 implausible-part rows
were already labelled damage; the census adds their texts here for the
record: title-35 citations are overwhelmingly real-looking part references
to a Reserved title ("35 CFR 62"), and "00 CFR NYD" is a placeholder wearing
a citation's shape.

## The rule the census kept

Every recovery is a rule, not a repair: the value read is derivable from the
text plus a declared convention (integer value of a zero-padded token, column
semantics for a positional read, the OLRC index for an act name). Anything
requiring a guess — "which act does INA abbreviate", "was 1484-86 a range" —
stays refused, because the record already contains what guessing produces.

## Post-census correction: the impossibility verdicts were time-blind

A web check of the "impossible" samples overturned two rules:

- **Title 35 was the Panama Canal title through the 2000 CFR revision** (the
  Canal Zone was U.S.-controlled until the 1999 handover). The 115 rows
  labelled impossible cite 35 CFR 62/113/115/117/121 from 1990s editions —
  real navigation regulations. A grammar judging citations must carry the
  calendar of its data; only the *subject-index* module, which judges today's
  roster, keeps 35 reserved. Impossible-title rows: 159 → **44**.
- **Real CFR parts reach five digits**: 5 CFR 10001 and 10002 (National
  Council on Disability) exist today, so the four-digit plausibility cap was
  wrong. Only ≥6 digits is asserted damage now (42 → **7** rows), and the
  Agenda table gained `cfr_part_in_current_ofr_index` — an evidence-grade
  membership signal (386,606 present / 34,033 absent) that separates
  historical-real, fused-fake, and typo without a length heuristic. Four
  five-digit rows are in today's index; the old cap called all of them fake.

## Extension: series-bound verdicts for every identifier family

The same web-verify-the-boundary treatment, applied everywhere (all bounds
verified 2026-08-21: EO series through 14420; Stat. volume 139 = 2025;
numbered Public Laws begin with the 57th Congress, 1901; U.S.C. runs 54
titles with 53 reserved and never enacted — unlike CFR 35, 53 has no
Panama-style history, so it is impossible in any year):

| family | out of series | anatomy of the damage |
|---|---:|---|
| U.S.C. titles | 129 | transposition and prefix-fusion: "61 USC 4901-4916" is 16 U.S.C. 4901–4916 (Wild Bird Conservation Act); "347 USC 307(e)" is 47 U.S.C. 307(e) |
| Public Laws | 90 | "155-271 (October 24, 2018)" is 115-271 — the SUPPORT Act, and the date proves it |
| Stat. volumes | 19 | "188 Stat 445" sits beside "PL 108-199", which IS 118 Stat. 445 (2004) — the same string carries its own correction |
| EO numbers | 7 | 20450, 21600, 23891 — beyond any series |
| RINs | **0** of 241,726 | the one publisher field with a checksum-grade record |

Several flagged values are decodable by a human reading the cross-field
evidence. None is decodable by a safe rule: recovering "155-271 → 115-271"
requires inferring from a date, which is the guessing this census exists to
refuse. Labelled, never repaired — and the flags are columns, so a consumer
with a higher risk tolerance can do its own inferring against the preserved
text.

The remaining impossible CFR titles were then put to the machinery a reader
of this file might reach for: corroborated correction — bounded damage
operators (transposition, digit drop) generating candidates, the pinned OFR
part index as oracle, exactly-one-survivor to emit. **It refused five of
five.** "234 CFR 200.14" has three operator-reachable titles all holding a
part 200 (nineteen titles do); even the strongest rule — trust the part,
infer the title by uniqueness — recovers only "CFR 482" (title 42 alone
holds a part 482) and refuses the rest: part 679 lives under BOTH 50 and 20,
part 1560 under both 49 and 7. An earlier revision of this file confidently
"decoded" 60 CFR 679 as Alaska fisheries; the oracle showed that decoding
was underdetermined, which is precisely the overconfidence the refusal
machinery exists to catch — including in this document.

## Final ledger (post-rebuild, 2026-08-21)

The rebuild carrying every wave — six new authority families, the four
residue recoveries (zero-padded titles, inverted appendix, CFR longhand,
OMB series), year-guarded act-name similarity, and the roster-corroborated
Public Law pass — settles the accounts:

| pool | opening | closing | disposition |
|---|---|---|---|
| authority rows failing to parse | 39,856 (census opening) | **9,280** | recovered by derivable rules; remainder is damage or genuinely alien text |
| authority rows stating nothing | 12,393 | 12,393 | placeholders, never counted as failures |
| out-of-series USC titles | 129 | 130 | +1: a zero-padded title now reads as its integer and gets judged |
| out-of-series PLs | 90 | 90 → 88 effective | 2 rows corroborated-corrected (`Pub. L. 1014-410` → 101-410, unique-roster-existence); the other 88 stay labelled |
| act-relative recoveries | 4,282 | 4,858 | +576 from similarity (42 rows), trailing-parenthetical strip, and family reflow |
| timetable FR citations failing | 28 | 28 | all genuinely damaged; positional (102) and relabeled (64) recoveries hold |

Corrections carry evidence columns; originals never leave the table. Every
number above is pinned in `tests/test_unified_agenda_parquet.py` against
the rebuilt Parquet, so the ledger breaks loudly if a rebuild moves it.

## Continuation, 2026-08-21 (second pass): the 9,280 re-anatomized

The remaining failed pool, re-parsed live and clustered by shape, decomposed
into recoverable veins and named refusals. The rebuild carrying this pass
settles at **6,997 failed** (from 9,280), 12,463 unstated (from 12,393; the
delta is quoted placeholders and "Not applicable" — a placeholder in
quotation marks is still a placeholder), and 797,053 total rows (from
795,251; the growth is real citations newly typed out of strings that
already parsed partially).

### Recovered by derivable rule (grammar)

- **cp1252 mojibake dashes** (104 rows): U+0096/U+0097 are Windows-1252
  en/em dash bytes surviving a bad decode — "PL 105\x96261" is Pub. L.
  105-261, the FY1999 NDAA. The bytes appear in no other Agenda field
  (measured); the dash table absorbs them one-for-one so spans still index
  the original. A doubled dash ("105\x96-261" — en dash and hyphen side by
  side) is one separator typed twice; the Public Law separator now
  tolerates it.
- **Federal Register citations as authority** (2,049 rows, 101 distinct
  previously-failed values): "44 FR 56673" in the authority column is a
  document locator in the wrong field — typed `federal_register`
  (fr_volume, fr_page), always partial, the same posture as the CFR
  family. The count exceeds the failed pool's share because companion
  citations beside EOs and notices ("EO 12674, 54 FR 15159") are now typed
  too instead of silently dropped.
- **Revised Statutes** (118 rows): "R.S. 463" — the 1874 codification,
  still positive law where never repealed. Web-verified: R.S. 463 and 465
  are 25 U.S.C. 2 and 9 (the BIA's organic authorities); R.S. 161 is the
  housekeeping statute 5 U.S.C. 301, and the corpus itself writes
  "R.S. 161, 5 U.S.C. 301" side by side. Its own namespace and column
  (`revised_statute_section`) — never merged into a U.S.C. title.
- **D.C. Code** (232 rows): cited by the agencies administering D.C.
  functions under the Revitalization Act (web-verified: D.C. Code 24-131
  is the Parole Commission's authority over D.C. felons). Both spellings
  read to one title-section compound: "D.C. Code 24-131(a)(1)" and the
  older title-first "26 DC Code 102" (the inverted-appendix precedent).
- **Presidential directives** (46 rows): "Homeland Security Presidential
  Directive 12", "HSPD-12" — typed by kind alone like memoranda and
  notices; the number stays visible in the original text.
- **Office-named Secretary's Orders** (130 rows): "Secretary of Labor's
  Order 1-2011" (web-verified: 77 FR 1088, the EBSA delegation),
  "Secretary of the Air Force Order 111.1" — possessive or not, curly or
  straight apostrophe. The earlier spelling set ("Secretary's Order") read
  none of them.
- **Departmental Manual** (36 rows): "212 DM 13" — Interior's own
  directives system; the 200-series DM parts are the delegation chapters
  BIA rules cite (web-verified against doi.gov's ELIPS). The part-DM-chapter
  compound is kept verbatim as the admin-order number.
- **Bare titles** (63 CFR + 91 USC rows): "3 CFR" and "16 USC et seq" name
  a title wholesale — typed with the title, partial, never "ok", and the
  USC form only as a whole-value fallback so prose can never donate one.
- **Dot-separated Public Laws** (16 rows): no Public Law citation form is
  decimal, so "Pub. L 103.311" reads as 103-311; the dotted range
  "Pub. L. 205.600-205.607" is CFR-shaped and stays refused.
- **Stray period after a U.S.C. title** ("15. U.S.C. 78w(a)", 14 rows).
- **Comp-less compilation locators** (10 rows): a YEAR RANGE proves the
  shape — no CFR part is ever "1966-1970" — so "3 CFR, 1966-1970, p 939"
  diverts without the word "Comp.". This also caught a fabrication: "3 CFR
  1971 to 1975" had been minting a cfr row for part 1971. A single
  Comp-less year ("3 CFR 1990") could name a part and stays undiverted.
- **Case reporters** (35 rows): "48 Cl Ct 221" (Court of Federal Claims)
  joins the closed reporter set; "318 US 363 (1943)" reads as the U.S.
  Reports only because the decision year disambiguates — "50 US 2401 et
  seq" is 50 U.S.C. 2401 with a lost C, and the yearless form stays
  refused.

### Recovered by the index (the OLRC is still the grammar)

The spelling closure derives variant keys from the pinned index by declared
convention — no new information enters, the published key is always
canonical, and any variant reachable from two canonicals is dropped
(ambiguity refuses; 638 year-less variants died this way):

- **Year styles** ("Motor Carrier Act of 1935" → "Motor Carrier Act,
  1935"; the OLRC itself alternates styles), **ampersands**, **leading
  articles** ("The Family Smoking Prevention and Tobacco Control Act"),
  **year-less names** ("Fair Labor Standards Act" → the act of 1938;
  "Clean Air Act Amendments" reaches three canonicals and refuses).
- **Designator tails** (103 rows): "Clean Air Act title I" cites the act;
  the title designation stays visible in the original text.
- **Marker-less sections** (118 rows): "Clean Air Act 211(o)" — the
  section is the last digit token, so the split is structurally unique; a
  bare year-shaped number ("Trade Act 1974") stays refused.
- **Inverted comma citations** (25 rows): "Sec 13(a)(15), Fair Labor
  Standards Act (FLSA), as amended".
- **Truncation completion** (27 rows): "...Transportation Equity Act: A
  Legacy for U" is a PREFIX of exactly one canonical name (SAFETEA-LU,
  its "sers" lost to a field boundary); 40 characters is the measured
  floor, exactly-one-survivor refuses shared prefixes.

### Recovered by corroboration (named operators × pinned oracle × exactly-one-survivor)

- **Separator-damaged Public Laws** (24 rows): "Pub. L. 108199" fused its
  dash — inserting one at each split leaves exactly one roster-existent
  congress (10-8199 names no congress; 1081-99 is out of series) —
  evidence `unique-dash-insertion` (6 rows). "PL 95 616" kept its pair but
  lost the glyph — `space-separator-roster-existence` (18 rows). Both
  carry parse_status `corroborated` with a NULL public_law: the grammar
  read nothing, the roster did, and the reading lives only in the
  correction columns. Total corrected rows now 26 (with the two earlier
  `unique-roster-existence` rows).
- **Abbreviated acts** (339 rows): "CAA sec 112" resolves only when the
  same RIN's authority lists — in any edition — resolved exactly one act
  whose initialism is "CAA". The oracle is the publisher's own roster; the
  operator (initials of significant words, function words and years
  contributing nothing) matches how the corpus itself abbreviates (CAAA =
  Clean Air Act Amendments of 1990). Zero ambiguous survivors. The
  recovered pairs: CAA→Clean Air Act, CAAA, SDWA, CWA, TSCA, FIFRA, BBA,
  SSA. Two oracles were measured and REFUSED first: blind initialism
  against the whole OLRC index (59 candidate acts for "CAA"; "EPCRA"
  matches exactly one index name — the Environmental Policy and Conflict
  Resolution Act of 1998 — and that unique survivor is WRONG, which is the
  overconfidence exactly-one-survivor cannot catch when the operator
  misdescribes authorship); and record-level siblings (0 of 3,147
  abbreviation rows share a record with a spelled-out name).

### Timetables: 28 → 21

Three more strays joined the positional read (102 → 109), each a named
damage on the one token the column writes: the transposed label ("74 RF
31642"), the stuttered label ("79 FR FR 54588"), the slashed separator
("89 /FR 81156"). "NFR", "DR", "FSR" stay refused — no single named
operation derives them from "FR". The 21 that remain: volume-only values
("72 FR" — there is no page to recover), a placeholder page ("86 FR
00000"), pages beyond the Register's widths ("89 FR 1022091" — several
repairs reachable, none licensed), FR document numbers in the citation
column ("90-21215" — the FR Doc series shares the column's two-number
shape, two readings, refused), and letter salads ("83 FR AK07").

### CFR pools: the machinery re-run, and it refused again

The corroboration machinery was put to the 7 implausible parts and the
44 impossible titles with the pinned OFR part index as oracle:

- "42 CFR 412106" (fused dot): TWO splits survive — title 42 holds both
  part 4 and part 412 — so the repair is underdetermined. Refused.
- "47 CFR 634761471": parts 6 and 63 both exist under title 47. Refused.
- "0 CFR 150 to 189" (dropped digit): no title reachable by one-digit
  insertion holds both endpoint parts (only 14, 21 and 46 hold 150 and
  189, none reachable from "0"). Zero survivors. Refused.

The impossible-title pool stays at 44 (36 are "00 CFR NYD"-family
placeholders wearing a citation's shape), implausible parts at 7.

### The refusals, named (the 6,997)

| cluster | rows | distinct | why refused |
|---|---:|---:|---|
| abbreviated acts with no oracle testimony | 2,506 | 576 | "CWA 301" in a RIN whose editions never spell the name; the identity fence holds |
| prose/damage with no derivable scheme | 1,591 | 588 | "Pub. L. 179" (congress unstated; dash-insertion finds no survivor), "11/04/1980)", bare "Title I", "Sec 29(b), FLSA of 1974" |
| bare numbers naming no scheme | 1,402 | 525 | "31136(a)" is 49 U.S.C. 31136 to a human; "8 1252 note" could be U.S.C. or Stat. — the authority column holds many schemes, so a positional read has no license here |
| act-name prose the index cannot answer | 1,333 | 413 | "Railroad Safety Improvement Act of 2008" (the short title IS "Rail..." per PL 110-432 — a word-level rewrite no operator derives); "sec. 403 of the 2018 FAA Reauthorization Act" (year prefixed, name reordered); "Sex Offender Registration Act of 1999" (a D.C. Council act, alien to the OLRC index) |
| treaty/convention prose | 92 | 16 | CITES, the Compacts of Free Association — real instruments with no citable series token for the treaty grammar |
| appendix-paginated Stat. pages | 46 | 7 | "114 Stat. 2763A, 326 to 328": the page's identity is "2763A-326", which an int32 page column cannot state without truncating or minting; deferred until the schema grows a text page, and nothing vanishes meanwhile |
| court rules | 27 | 2 | "Fed. R. Bankr. P. 2015" — a real family (28 U.S.C. 2075), but two distinct strings citing one rule do not buy a schema family; named, kept, revisit if the corpus widens |

One new specimen joined the labelled pools: the mojibake fix made
"PL 220\x96432, Div A, 122 Stat 4848 et seq" readable, and congress 220 is
beyond the series (out-of-series PLs 90 → 91). A human reads 110-432 beside
its own "122 Stat 4848"; the congress-token operators cannot reach 110 from
220, so it stays labelled — the same cross-field refusal as "188 Stat 445".

### Ledger after the continuation

| pool | before | after |
|---|---:|---:|
| authority rows failing to parse | 9,280 | **6,997** |
| authority rows stating nothing | 12,393 | 12,463 |
| act-relative recoveries | 4,858 | 5,721 |
| corroborated rows (act + PL) | 0 | 363 |
| Public Law corrections carried | 2 | 26 |
| timetable FR failures | 28 | 21 |
| out-of-series PLs | 90 | 91 |
| new typed families | — | federal_register 2,049; dc_code 232; revised_statute 118 |

Every number is pinned in `tests/test_unified_agenda_parquet.py`; the
derivation helpers (spelling closure, initialism operator, separator
corroboration) are tested without the artifact so the rules hold even
where the build has not run.

## Third wave, 2026-08-22: the 6,997 re-anatomized

The wave-2 refusal clusters were each reopened on the working hypothesis
that prior waves twice found recoveries inside "refused" piles. They did
again: **6,997 → 4,239** (2,758 rows recovered), 797,053 → 797,837 total
rows (previously-partial strings released additional citations), and the
three questions wave 2 left open are all answered.

### The abbreviation oracle, escalated one level and no further

Wave 2's initialism corroboration used the single RIN's resolved acts as
oracle (339 rows). Wave 3 measured the next altitude: the **agency's**
roster, keyed by the RIN's leading four digits — the OMB-assigned agency
code, reginfo.gov's own definition of the RIN format ("all RINs for OSHA
have agency code 1218"). Measured before adoption:

- the agency oracle **agrees with the RIN oracle on all 339 rows** both
  answer, and answers 1,323 more failed rows with **zero ambiguous
  survivors**;
- the corpus-wide roster was measured and **refused**: "CAA" reaches both
  the Clean Air Act and the Consolidated Appropriations Act, 2014
  corpus-wide, "BBA" reaches three acts, "PPA" two — the agency fence is
  what makes uniqueness, so a row whose own agency is silent stays refused
  rather than borrowing another agency's testimony (98 rows would have
  resolved — RCRA, IIJA, ARRA among them, every one plausibly right — and
  the rule is judged by the next value, not these);
- this is the testimony the wave-1 identity fence demanded: "INA" resolves
  at DHS RINs (145 rows) because DHS spells out the Immigration and
  Nationality Act, not because anyone guessed.

The whole-value shape also grew to five measured spellings (section lists
"CWA 301, 304, 306" — one row per member, the EO-plural rule; the inverted
"212(a)(10) INA"; "sec 4312(a) of BBA of 1997"; "DRA of 2005"; designator
tails "CAA title I"), with two guards: **citation labels are never act
abbreviations** ("PL 425" cannot resolve to an act named PL), and **a year
is identity, not a section** — "MCSA 1984" names the act of 1984 and emits
no section; "CAA 1990" against the year-less Clean Air Act refuses
outright. Corroborated act rows: 339 → 2,259, every one carrying its act.

### Act prose the index CAN answer, reached by declared operators

The 1,333-row "index cannot answer" cluster held ~600 rows the index
answers once spelling conventions compose (every operator only ever
produces candidate spellings the closure already knows):

- **sections in front of the name** (≈250 rows): "205(u) and 1631(e)(7) of
  the Social Security Act", "sec 371 to 376 of the Public Health Service
  Act" (a range member stays its stated pair), the connective-less "sec 307
  FDA Food Safety Modernization Act";
- **internal parentheticals** (67): "National Technology Transfer and
  Advancement Act (NTTAA) of 1995", "John S. McCain NDAA (NDAA) for Fiscal
  Year (FY) 2019";
- **", as amended" tails** (56) and **iterated designator tails with the
  citation's own section** (39): "Consolidated Appropriations Act of 2018,
  div. L, title IV, sec. 410" → the act of 2018, section 410;
- **leading designators** (24): "Title V of the Trade and Development Act
  of 2000";
- **year-prefix reordering**: "sec. 403 of the 2018 FAA Reauthorization
  Act" — the corpus prefixes the year the index suffixes;
- **the and-dropped closure variant** (79): "Resource Conservation Recovery
  Act sec 3001" — derived over every closure variant, zero collisions in
  9,160, a collision would refuse.

### Grammar: label damage and new instruments (≈470 rows)

- **Transposed code label**: "21 UCS 374" (uppercase only; the adjacent
  transposition the corroborated corrections already name; no other label
  is one transposition away). **U.S.C.S.** joins U.S.C.A. as an annotated
  edition spelling ("38 USCS 3564").
- **EO label**: "EO. 14221" (stray period), "E0 12250" (zero-for-O
  homoglyph, one keystroke from EO and from no other label).
- **Stat label**: fused separators ("92 Stat.1660", "61Stat 1180"),
  longhand "Statute", dropped-letter "Statue" ("61 Statue 1180" is the
  Chicago Convention's 61 Stat. 1180), and the page fused to its own
  "as amended" tail ("63 Stat 390as amended" is FPASA's 63 Stat. 390).
- **Lettered Stat pages** — wave 2's open question 1, answered with a
  schema column: `statute_page_text` carries the compound identity
  ("2763A-326") verbatim-uppercased, the int column stays NULL (exactly one
  of the two is ever set, pinned), the comma spelling "114 Stat. 2763A,
  326 to 328" reads to the same page, and a consumed-but-uncarried range
  end leaves the row partial rather than "ok". 206 rows over 31 spellings
  — the failed pool held only 46; the rest were hiding inside
  previously-partial strings.
- **Compilation fragments**: "1991 Comp p 351", "Comp., p. 193" — the "3
  CFR" head lost; only Title 3 prints Comp. pages, whole-value only.
- **OMB longhand** ("Office of Management and Budget Circular No. A-25"),
  **"Fed. Reg."** as the Bluebook FR spelling, **"title 35 of the U.S.C."**
  as a bare title, case-blind **"5 USC APP"**, a tolerated **subtitle
  designator** ("46 USC subtitle II 3301, 3305…"), and the hyphenated and
  colon'd PL labels ("PL-111-134", "Pub. L. No: 114-190").
- **Four directives systems**, each web-verified: the Forest Service
  Manual ("FSM 2320" is the wilderness chapter; all 56 rows sit at
  USDA-FS RINs), DoD Directives ("DODD 5000.35"), DOJ Orders, Attorney
  General's Orders.
- **FAR self-citations**: "FAR 1.301" is 48 CFR 1.301 by the FAR's own
  declared equivalence (FAR 1.105-2); typed as the CFR citation it is.
- **Treaty instruments named without a series token** (100 rows): CITES,
  the Chicago Convention, the Compacts of Free Association — typed
  `treaty` by kind alone, the presidential-memoranda convention. The
  implementing legislation stays a statute: "… Convention Act" and
  "… Convention Implementation" are refused by name (the Atlantic Tunas
  Convention Act was one mistype away).

### Corroborated Public Laws: two more named shapes (46 rows)

"Pub. L. 111 to 203" writes the range word where the dash belongs — a bare
law-number range names no congress and recovers nothing, so
roster-existence of the pair is the only surviving reading (it is
Dodd-Frank) — evidence `to-separator-roster-existence` (35). The fused
form now tolerates the value's own section tail: "Pub. L. 10811, sec 1503"
is 108-11 by unique dash insertion (6 → 17). Corrections carried: 26 → 72.

### Court rules — wave 2's open question 2, the refusal held

Still 27 rows, still 2 distinct strings, still one rule (Fed. R. Bankr. P.
2015(a)). A schema family for one rule spelled twice remains structure
that does not earn its keep; the refusal stands, re-recorded here with its
specimens.

### The refusals, renamed (the 4,239)

| cluster | rows | distinct | why refused |
|---|---:|---:|---|
| bare numbers naming no scheme | 1,433 | 529 | unchanged posture: "31136(a)" needs a title no column semantics can donate |
| prose/damage with no derivable scheme | 1,046 | 416 | "US Cost, Art II" (named in wave 2), "12 SC 1757" (a lost U is not a named operator), "FR 114-255", date fragments, "sec 3012, 70A Stat 157" — volume 70A is REAL (the 1956 Title 10 enactment) but a lettered volume needs the same schema decision pages got, deferred at 4 rows |
| act-name prose the index cannot answer | 739 | 249 | "Railroad Safety Improvement Act of 2008" (word-level rewrite), "Consolidated Appropriations Act, 2000" (absent from the OLRC index), D.C. Council acts |
| abbreviations without agency testimony | 563 | 180 | "BBRA '99", "EPCRA", "NEPA", "HIPAA" — the citing agency never spelled the name; the corpus-wide oracle is proven untrustworthy (see above) |
| bare labels and congress-less PLs | 313 | 101 | "USC 41706" (no title), "Pub. L. 179" (no congress), "H.R. 535" (a bill names no congress), "PL 105?178" (a '?' in the dash slot with tails the whole-value shapes refuse) |
| MMA | 118 | 23 | the largest single named refusal: the corpus abbreviates the Medicare Prescription Drug, Improvement, and Modernization Act of 2003 as "MMA", the initials operator derives MPDIMA, and the OLRC publishes no "Medicare Modernization Act" alias — no pinned oracle testifies |
| court rules | 27 | 2 | held, see above |

One operator was measured and refused on yield: word-abbreviation prefix
matching ("…Development Coop. Act of 1981" → "Cooperation",
exactly-one-survivor over the variant space) recovers 15 rows — all one
distinct value. An operator whose entire measured yield is one specimen
has an unmeasured false-positive surface; the census names it instead of
adopting it.

### Ledger after the third wave

| pool | before | after |
|---|---:|---:|
| authority rows failing to parse | 6,997 | **4,239** |
| act-relative recoveries | 5,721 | 8,515 |
| corroborated act rows | 339 | 2,259 |
| Public Law corrections carried | 26 | 72 |
| treaty rows | 68 | 168 |
| administrative_order rows | — | 1,211 |
| lettered Stat pages (`statute_page_text`) | — | 206 |
| timetable FR failures | 21 | 21 |
| out-of-series (USC/EO/PL/Stat) | 130/7/91/19 | 130/7/91/19 |

## Wave 3 extension: the OTHER identifier surfaces, audited

The census had only ever looked at the Agenda's authority and citation
columns. The same at-scale treatment applied to every other pinned
identifier surface (validators from `identifier_shapes.py` run against
whole columns):

- **RINs are still checksum-grade**: `unified_agenda_actions.rin` 46,562
  distinct / 0 invalid; the native agenda's 3,954 / 0; catalog
  `dockets.rin` 285 stated, 0 invalid.
- **The FRDOC docket family** (fixed): every agency holds one
  `AGENCY_FRDOC_0001` docket on Regulations.gov for its FR documents
  (web-verified: ACF_FRDOC_0001 is navigable). The year-bearing docket
  shape refused all of them — 72,404 catalog document rows and 177 docket
  rows. `normalize_docket_reference` now admits the family on its literal
  FRDOC anchor; an arbitrary year-less compound still refuses.
- **GIPSA suffixed dockets** (refused, named): 133 document rows carry
  `-RULEMAKING`/`-NONRULEMAKING` tails ("GIPSA-2008-FGIS-0002-NONRULEMAKING").
  Admitting letter-suffixed endings would unwind the 5,214/5,506
  mutilated-reference defense; refused with specimens.
- **The FR document number space is wider than the validator** (reported,
  not fixed — the mint's lexical space is a consumer contract):
  `federal_register.document_number` (800,619 rows) decomposes into
  451,783 modern `YYYY-NNNNN` (134,292 of them zero-padded), 198,887
  numeric two-digit-year legacy ("94-31297"), 119,610 letter-legacy
  ("E9-…"), 1,190 corrections, **28,488 modern short-sequence numbers
  ("2012-7327") the modern-only validator refuses though they are the
  Register's own canonical spellings**, 585 whose sequence is itself
  year-shaped ("2016-2017" — ambiguous with a year range, refuse-worthy on
  shape alone), and 76 oddities including the `R1-` republication prefix
  the correction shape does not know. The padded/unpadded mix is also a
  raw-string join hazard. **Needs the mint owner's decision.**
- **The FR API's RIN column carries recoverable damage** (reported):
  444 of 99,552 `regulation_id_numbers_json` tokens are invalid — OMB
  control numbers in the RIN column ("3084-0098"), the zero-for-O
  homoglyph ("0648-A082" for 0648-AO82), space-for-dash ("1625 AA00").
  The homoglyph family is corroborable against the Agenda's 241,726-RIN
  roster if that artifact's builder ever wants it.
- **`federal_register.docket_ids_json` is a different universe** (named,
  unaudited): 495,330 of 716,090 tokens are not Regulations.gov dockets
  but agency-native schemes — FERC ("RM98-1-000"), Commerce ITA case
  numbers ("A-570-831"), NRC ("52-025"), NPS internal codes, plus label
  prose ("Notice 1"). Each scheme is its own grammar; none is audited.
- **`court_opinions.parquet`** (68 rows): the citation column mixes four
  real U.S.-Reports citations ("608 U.S. 219") with 64 preliminary-print
  locators ("608/2"); docket_number mixes cert ("24-43") and application
  ("25A312") forms. A consumer parsing that column must know.
- **eCFR agencies** (316): slugs carry eCFR's own parenthesized
  convention; one agency has zero CFR references. Report-only.
- **`documents.fr_doc_num`**: 42 non-conforming values among 3,798 stated —
  two-digit-year legacy numbers, FR *citations* in the number column
  ("70FR35683"), a labeled "FR Doc 2026-08656", one OMB control number.

## Fourth wave, 2026-08-22: the oracle changes, not the operators

Waves 1–3 answered "what damage does this text carry?" better each time.
Wave 4 asked a different question — **who else already knows?** — and the
answer moved **4,239 → 3,516** (723 rows) without inventing a single new
damage operator. Three oracles nobody had used, each fenced, each measured
before adoption; and two that were measured and **refused with a number**,
which is the more useful half of the result.

The probe is checked in beside this file
(`rin_history_oracle_probe.py`) so every count below is re-derivable.

### The lead the previous pass died on: a defect, not a discrepancy

`'SSA, sec 1834'` resolved under a probe and failed in the built artifact.
The builder was right and the probe was wrong — the probe never applied the
section-emission guard — but the guard itself was over-broad. Wave 3 refused
a year-SHAPED token in the section slot so that "CAA 1990" could not mint
section 1990. Social Security Act sections run 1801–1899 (Medicare) and
1901–1946 (Medicaid), so **every Medicare section number looks like a
year**.

The text already carries the discriminator: an explicit `sec`/`section`/`§`
marker is the publisher stating which slot the token fills. Measured on the
failed pool: 59 rows carry a year-shaped token in the section slot; **all 8
marked ones are real sections** ("SSA, sec 1834", "Sec 1833(h)(8) of the
MMA", "Sec 1817(i) and 1871 of the SSA"), and **51 unmarked ones are the
act's year** ("NEPA 1969", "ARRA 2009", "MMA 2003", "EPA 1992", "BIPA 2000",
"BBRA 1999"). Two unmarked rows ("SSA 1819", "SSA 1919") are real sections
wearing the ambiguous shape and **stay refused** — the text does not say
which slot they fill, and refusing to choose is the rule.

### Oracle 1: a rule's own citation history (554 + 37 + 24 + 15 + 28 rows)

Wave 3's lesson generalised. The abbreviation oracle asked an agency's
resolved-act roster to name an act; wave 4 asks the same roster, and the
single RIN's before it, to supply a **label** or a **container** the value
lost. Only rows the grammar read enter the oracle — never a corroborated
row — so corroboration never bootstraps on corroboration.

| shape | specimen | reading | rows |
|---|---|---|---:|
| bare section list | `31136(a)` at an FMCSA RIN | 49 U.S.C. 31136 | 554 |
| title-less code label | `USC 6662A` at an IRS RIN | 26 U.S.C. 6662a | 37 |
| label-less pair | `49 46105`, `8 1252 note` | 49 U.S.C. 46105 | 24 |
| volume-less Statutes page | `Stat. 782` at a HUD RIN | 130 Stat. 782 | 15 |
| unlabelled Public Law pair | `89-670 and 91-605` at DOT | Pub. L. 89-670 | 28 |

Two fences make this safe, and both were measured rather than assumed:

- **Corpus-wide uniqueness of the section number.** Held out over the
  682,267 grammar-read U.S.C. citations — each row's own text hidden, the
  corpus asked to name the title from the section alone — a bare RIN-level
  answer is right 99.38% of the time. That is not good enough. Requiring the
  section to be filed under exactly ONE title corpus-wide **and** at the
  citing RIN raises it to **99.63%**, and a hand-read of all 30 disagreeing
  texts shows the majority are the publisher's damage rather than the
  oracle's error: `17 U.S.C. 78c(b)` is the Securities Exchange Act at **15**
  U.S.C. 78c, `27 USC 5723` is **26** U.S.C. 5723, `42 USC 44707` is **49**
  U.S.C. 44707. The genuine collisions are few and named: 16 vs 46 U.S.C.
  1279, 41 vs 42 U.S.C. 6374e, 15 vs 12 U.S.C. 1638.
- **Distinctiveness.** Short bare ordinals are the numbers every title
  reuses (42, 301, 504, 509); excluding them is what moves 0.9574 to 0.9963.
  A letter suffix, a hyphenated compound or four digits makes a section
  number an identifier rather than an ordinal.

A bare number in the authority column reads as a section of a code or an
act and **never** as a CFR part, a Statutes page or a Public Law number,
because each of those requires a label the value does not carry. That is
also what protects the reading from the corpus's own contamination: the CFR
pool holds "42 CFR 6912", which is really 42 U.S.C. 6912.

Wave 2 refused `8 1252 note` because it "could be U.S.C. or Stat. — the
authority column holds many schemes". It still could: the pair must exist in
the pool under exactly one of the two, and a pair both schemes hold refuses.
The objection is answered, not overruled.

### Oracle 2: the corpus glosses its own abbreviations (144 rows)

The census's **largest single named refusal was MMA** — 118 rows, the
Medicare Prescription Drug, Improvement, and Modernization Act of 2003,
whose initials operator derives MPDIMA and for which "the OLRC publishes no
'Medicare Modernization Act' alias — no pinned oracle testifies".

One does. The corpus writes the expansion beside the abbreviation, in its
own authority column, 35 times at CMS:

> `sec 1893(i)(1) of the Social Security Act as amended by sec 935(i)(1) of Medicare Modernization Act (MMA)`

The gloss cannot *name* the act — "medicare modernization act" is not an
index name either — but its words **discriminate**. CMS's roster holds three
acts an anchored-subsequence "MMA" reaches; only one of them contains
"modernization", the other two being the Balanced Budget Refinement Act of
1999 and the Benefits Improvement and Protection Act of 2000. The gloss is
the publisher's testimony, the roster is the pinned oracle, and one survivor
stands. **44 abbreviations are glossed this way corpus-wide** (FMIA, PPIA,
HIPAA, EISA, NDAA, OCSLA, INA…). Measured before adoption: over the 99 rows
where the roster oracle already answers uniquely and a gloss exists, the
gloss **agrees 99 times and disagrees 0**; where the gloss's words reach no
survivor it empties and the row stays refused (36 rows) rather than
contradicting the roster.

The initialism operator also gained two measured refinements: an
**anchored subsequence** (MMA ⊆ MPDIMA — the first and last significant
words always survive an abbreviation, the middle ones may not), and **the
year filtering candidates before survivors are counted** rather than after,
which is what turns "MMA of 2003" from three survivors into one. Held out
over the 137 abbreviation citations whose act the grammar already resolved,
with the true act removed from the roster, the subsequence operator answered
86 times — **every answer the same act under a different published name**
(Table III key identical) and never a different act.

MMA: 118 rows → **12**, and the residue is honest — six rows at agency 0917,
whose act roster is empty, and doubled values ("MMA, sec 629 MMA, sec 811")
that name two citations in one whole-value slot.

### Oracle 3: the fence licenses the operator, not the yield (27 rows)

Wave 3 measured word-abbreviation prefix matching against the whole
13,560-name index, found it recovered 15 rows over **one** distinct value,
and refused it: "an operator whose entire measured yield is one specimen has
an unmeasured false-positive surface."

Wave 4 measured that surface. Fenced by the citing agency's own resolved-act
roster, held out over the 1,964 distinct (text, RIN) act citations the
grammar resolved with the true act removed from the roster, the operator
**invented a survivor 0 times**. The yield is still one value — but it is
the right one: the corpus writes "Railroad Safety Improvement Act of 2008",
and the short title of Pub. L. 110-432 Division A is the "**Rail** Safety
Improvement Act of 2008" (web-verified 2026-08-22 against congress.gov and
FRA's own eLibrary). 27 rows. **A one-specimen operator with a measured
zero-error fence is not the same object as a one-specimen operator without
one**, which is what wave 3 could not tell.

### Refused, with a number

- **The same-ordinal cross-edition oracle.** A RIN persists across editions,
  so the natural idea is that ordinal *k* of a RIN's authority list means the
  same citation in every edition. Held out over 214,651 answerable rows it is
  right **54.8%** of the time — an agency reorders and rewrites its authority
  list between editions, so position is not identity. `'21 USC 352'` sits
  where another edition put `'21 USC 355'`; `'51 U.S.C. 20113'` where another
  put `'10 U.S.C. ch. 137 legacy provisions'`. **Refused.** The RIN-level
  *pooled* history adopted above makes no such claim: it says only that this
  rule files this section under exactly one title, never that this slot is
  that citation.
- **The bare Public Law number.** "Pub. L. 179", "PL 425" — 260 rows in the
  residue. The agency's own PL roster answers many of them, and it is wrong
  **1.7% of the time**: held out over 29,437 answerable grammar-read PL rows
  the escalated oracle scores 0.9828, and the errors are unrecoverable
  because a law *number* names no congress — every congress has a law 296, a
  law 116, a law 174. `'PL 107-296'` sits at an agency that also cites
  103-296. **Refused**, and now numbered rather than intuited. The *pair*
  form `89-670` is different and adopted: it states both halves, so the
  roster is asked to confirm rather than to choose.
- **Court rules** — still 27 rows, still 2 spellings, still one rule
  (Fed. R. Bankr. P. 2015(a)). The refusal holds for the third census.

### Four whole-value label repairs (61 rows)

Damage to a citation's LABEL whose numbers are intact, each anchored to the
entire value so prose can never donate one. The whole-value anchor is what
licenses relaxing a guard the in-prose patterns need:

- **lowercase Statutes label** (38 rows, 16 spellings): "126 stat 11",
  "61 stat. 1180". Wave 3 asserted "lowercase `stat` is still prose" without
  measuring it. Inside a sentence it is; a value that is *nothing except*
  "126 stat 11" is a citation whatever its case, and every volume/page here
  is in series and cited elsewhere in the same corpus with the capital.
- **stray comma before the section marker** (8): "47 U.S.C., sec. 151" —
  the wave-2 precedent is the stray period inside the label ("15. U.S.C.").
- **stuttered "et"** (6): "16 USC et 1531 et seq" — the "et" of the value's
  own tail, migrated forward; licensed only when that tail is actually there.
- **dropped U** (9, 4 spellings): "49 SC 30166", "15 SC 78q(a)". Wave 3
  refused this as "a lost U is not a named operator"; by wave 3's own
  precedent for "E0 12250" it is one — "SC" is a single deletion from "USC"
  and from no other label this grammar knows.

### Every corroborated row now names its rule

`corroboration_rule` joins the schema, non-NULL exactly when `parse_status`
is `corroborated` (pinned as an invariant), drawn from a closed declared set,
and counted per rule in the receipt. A rule that silently stops firing now
breaks a pin instead of shrinking a total nobody attributes.

| rule | rows |
|---|---:|
| agency-roster-initialism | 2,278 |
| agency-gloss-narrowed-initialism | 144 |
| agency-roster-word-prefix | 27 |
| rin-history-section-list | 554 |
| rin-history-titleless-usc | 37 |
| rin-history-labelless-pair | 24 |
| rin-history-volumeless-stat | 15 |
| roster-existent-public-law-pair | 28 |
| unique-dash-insertion | 17 |
| space-separator-roster-existence | 18 |
| to-separator-roster-existence | 35 |

### The refusals, renamed (the 3,516)

| cluster | rows | distinct | why refused |
|---|---:|---:|---|
| prose/damage with no derivable scheme | 1,002 | 398 | "Sec 29(b), FLSA of 1974", bare "Title I", "11/04/1980)", "D.C. Law 18-88, sec. 56 DCR 7413" |
| bare numbers naming no scheme | 987 | 369 | the residue the history oracle cannot reach: "sec. 939(e)" (no title anywhere at that agency), "1303" and "1702" (short ordinals several titles claim), "1437f note and 3535(d)" (members disagree) |
| act-name prose the index cannot answer | 709 | 246 | "Sex Offender Registration Act of 1999" (a D.C. Council act, alien to the OLRC), "Consolidated Appropriations Act, 2000" (absent from the index), "sec 1102 of the Act" (anaphora naming nothing) |
| abbreviations without agency testimony | 519 | 167 | "IIJA sec. 30012", "MIPPA", "BBRA" — the citing agency never spelled the name and never glossed it |
| bare labels and congress-less PLs | 260 | 82 | "Pub. L. 179", "H.R. 535" — measured at 0.983 and refused, above |
| court rules | 27 | 2 | held for the third census |
| MMA | 12 | 5 | agency 0917 has an empty act roster; the rest are doubled whole values |

### Ledger after the fourth wave

| pool | before | after |
|---|---:|---:|
| authority rows failing to parse | 4,239 | **3,516** |
| corroborated rows (all rules) | 2,329 | 3,177 |
| corroborated act rows | 2,259 | 2,640 |
| act-relative rows | 8,515 | 8,896 |
| Public Law corrections carried | 72 | 100 |
| total typed authority rows | 797,837 | 798,050 |
| authority rows stating nothing | 12,463 | 12,463 |
| timetable FR failures | 21 | 21 |
| out-of-series (USC/EO/PL/Stat) | 130/7/91/19 | 130/7/91/19 |

Every number is pinned in `tests/test_unified_agenda_parquet.py` against the
rebuilt Parquet, and the derivation helpers are tested without the artifact
so the rules hold even where the build has not run.

## Fifth wave, 2026-08-22: every remaining oracle refuses

Wave 4's finding was that a better-fenced **oracle** beats better operators.
Wave 5 tested the natural next move — take each adopted oracle one altitude
higher — and **every escalation failed its own measurement**. So this wave's
recoveries come entirely from named operators feeding oracles that were
already fenced and already measured: **3,516 → 3,287** (229 rows), total
typed rows 798,050 → 798,122, corroborated 3,177 → 3,292.

The probes are checked in beside this file (`wave5_anatomy_probe.py`,
`wave5_fence_probe.py`, `wave5_escalation_probe.py`, `wave5_operator_probe.py`,
`wave5_surface_probe.py`) so every number below is re-derivable.

### The five refusals, each with a number

Wave 4 established that a bare section names its title when the section is
distinctive, corpus-unique, and filed under that title by the citing RIN or
its agency. Both halves of that conjunction were tested, and both are
load-bearing:

| escalation | held-out accuracy | answerable rows | verdict |
|---|---:|---:|---|
| corpus-unique + distinctive, **agency silent** | **0.6816** | 7,745 | refused |
| agency holds it, **corpus-uniqueness dropped** | **0.9941** | 315,231 | refused |
| the **record's own** authority list names the title | 0.9161 | 390,173 | refused |
| …with the section attested under that title | **0.9662** | 369,456 | refused |
| the rule's **CFR title** is its U.S.C. title | **0.4774** | 641,967 | refused |

The first line is the wave's most useful result. Measured over the whole
grammar-read pool the corpus-unique fence scores **0.9992**, which reads like
a licence to answer wherever the agency is silent. It is not: on the
population it would actually answer — the rows whose own rule never
successfully cited that section anywhere — it collapses to 0.6816. The 0.9992
was the easy population's number. **The agency fence was never redundant with
corpus uniqueness; it was carrying the accuracy.** That is why "sec. 939(e)"
and "1303" stay refused, and now they stay refused for a measured reason.

Dropping the other half is nearly as bad and fails more interestingly: with
the RIN or agency holding the section but corpus-uniqueness waived, the
rule scores 0.9941 with **systematic, named** collisions rather than random
ones — 42 vs 31 U.S.C. 6101 (37 rows one way, 31 the other), 20 vs 48 U.S.C.
1681, 5 vs 12 U.S.C. 1813 and 1817. Two agencies can both be right about a
section number; only the corpus can say the number belongs to one title.
Held out at the rule level with **both** fences the adopted rule scores
**0.9998**, which is the number the census now pins.

**The corpus-wide abbreviation roster, and the date fence that was supposed
to rescue it.** Wave 3 refused the corpus-wide act roster on an intuition —
"CAA reaches both the Clean Air Act and the Consolidated Appropriations Act,
2014". Wave 5 measured it the way wave 4 measured the word-prefix operator:
held out over 1,679 distinct (act, edition) citations with the **true act
removed from the roster**, the operator invents a confident wrong survivor
**277 times (16.50%)**. The obvious repair is the edition's own date — a 1998
filing cannot cite an act of 2014 — and it moves that to **256 (15.25%)**.
The surviving errors are not the ones a date can reach:

> EISA → the Employee Retirement Income **S**ecurity Act (35 rows; the true
> act is the Energy Independence and Security Act of 2007), DRA →
> Dodd-Frank, HSA → the Head Start Act, ACA → the Agricultural Credit Act of
> 1978, TA → the Telecommunications Act where the Trade Act was meant, and
> the Trade Act where the Telecommunications Act was meant.

**Refused**, and wave 3's intuition is now a measurement.

**The publication-date bound, everywhere else.** Of 41,359 grammar-read
Public Law rows, exactly **3** cite a congress that had not yet sat when the
edition was published — the corpus does not have a time-travel problem, so
the fence has nothing to fence. Applied to the 103 bare-Public-Law rows an
agency roster can answer, the date bound removes a candidate from **1** of
them. The idea is sound and the corpus does not need it.

### What the operators bought (229 rows)

Every recovery is an operator normalizing a value so an oracle that was
already measured can read it. Ten whole-value label repairs join wave 4's
four, each anchored to the entire value and each measured **inert over the
41,378 distinct authority values the grammar already reads** — an operator
that rewrites a value which already parses is changing an answer, not
recovering one:

| operator | specimen | rows |
|---|---|---:|
| stray comma after the U.S.C. label | `18 U.S.C, 1350`, `10 U.S.C., ch. 903` | 15 |
| space inside the label | `47 U.S.C . 154(j)` | 8 |
| the terminal period doubled | `19 U.S.C.. 3314` | 3 |
| the period migrated onto the label | `21 .U.S.C. 387i` | 3 |
| the label stuttered | `12 U.S.C. U.S.C. 93a` | 4 |
| one stray letter before the title | `z49 USC 47508`, `U42 U.S.C 7429` | 6 |
| the letter O for a zero | `3o USC 1201 et seq` | 1 |
| a parenthesis opened between title and label | `47 (USC 201(b)`, `12 (U.S.C. 2243)` | 13 |
| parentheses around the section | `42 USC (290dd-1)` | 2 |
| one deleted letter in the Constitution's label | `US Cost, Art II, sec 2` | 7 |

Wave 4's comma repair read a comma only before a section *marker*; the corpus
writes the same damage before a bare section, a chapter and an appendix, and
a comma in that slot is never a list separator because a list separator has a
citation on its left. The homoglyph is the mirror of wave 3's `E0 12250`, and
30 U.S.C. 1201 is SMCRA sitting at the Office of Surface Mining's own agency
code. `US Cost` is a **refusal overturned**: wave 3 called it "a guess about
which word was meant", but "Cost" is one insertion from "Const" and from no
other label this grammar knows, the two-substitution "Code" has no Article
II, and the repair is anchored to the article-and-section shape only the
Constitution has.

Six punctuation tolerances feed the citation-history oracle, each a reading
convention rather than a repair:

- **the Oxford comma is ONE separator** — `12838, and 12905(h)` is a
  two-member list, and reading it as three refuses a real citation (19 rows);
- **a subsection-only member continues the member before it** — `41102(2),
  (4) and (8)` is one section with three subsections, and reading "(4)" as a
  section 4 would mint a citation the publisher never wrote (22 rows shaped);
- **whitespace inside a subsection chain** — `1814(i) (2)`, `sec 932 (c) (2)
  MMA`, `1919 (b)(1)(A)`. The operator is anchored on a digit or a closing
  parenthesis to its left, which is exactly what separates a section's own
  subsection from `and (3)`, `to (f)` and `or (q)`, where the space belongs
  to a connective; and bounded to three characters, which keeps it off the
  year in `48 cl ct 221 (2000)`;
- **an unmatched closing parenthesis** — `2277a-10)` (8 rows);
- **`et seq.` on a title-less label** — `USC 7401 et seq` (6 rows);
- **a Public Law pair carrying its own section tail** — `111-5, sec. 13111 to
  13112`, the tolerance the fused spelling already had (12 rows).

Three families the corpus states and the grammar did not read:

- **The DFARS citing itself** (12 rows). `DFARS 201.3` is 48 CFR 201.3 by the
  same declared equivalence that licensed `FAR 1.301`: the Office of the
  Federal Register prints it in its own heading — "48 CFR Part 201 — Federal
  Acquisition Regulations System (**DFARS Part 201**)" — and the supplement is
  48 CFR chapter 2, parts 201–253 (web-verified 2026-08-22). The chapter's own
  part range is the fence.
- **Delegation orders that spell the word "Order"** (16 rows). The kind
  alternation held `Delegation` and refused `Delegation Order`, so `USIA
  Delegation Order No. 85.5` and DOE's delegation orders read as nothing; the
  number may also end in a letter (`00-004.00A`).
- **The abbreviated Executive Order label, pluralised** (5 rows). `E.O.s
  12742 and 13603` — and since the plural is what licenses the number list,
  refusing the "s" was dropping an order, not just a row.

**One relabel.** `60 CFR 15845` (10 rows) claims a title the CFR does not
have and states a volume and page the Register does. 60 FR 15845 is a real
page of the March 27, 1995 issue (web-verified 2026-08-22) and the citing rule
is NASA's own 14 CFR 1214 rulemaking. This is wave 1's timetable measurement
in the authority column — the text's own numbers refute its claimed scheme —
and it is the only CFR-shaped whole value in the failed pool with an
impossible title, so the population statement is "one of one" rather than
"64 of 64". A CFR title the CFR actually has is never second-guessed.

### The 3,287, anatomized into sub-shapes

Waves 1–4 clustered the residue at seven coarse names. A named sub-cluster is
a deliverable even where nothing is recovered from it, so here is the whole
residue split by what the text *is*:

| sub-shape | rows | distinct | specimen |
|---|---:|---:|---|
| act-name prose the index cannot answer | 720 | 249 | `Sex Offender Registration Act of 1999`, `sec. 166(a) of the Consolidated Appropriations Act, 2000` |
| abbreviation with no agency testimony | 516 | 165 | `IIJA sec. 30012`, `MIPPA`, `BBRA`, `NEPA 1969` |
| other prose | 364 | 142 | `Department of Homeland` (truncated), `sec 412 (uncodified)`, `secs 1243 and 1245 of the Defense Offsets` |
| **marked bare section** | 290 | 107 | `sec. 939(e)`, `sec 31601`, `sec 872` — the publisher says "section" and no oracle knows of what |
| residue: punctuation-damaged fragments | 253 | 131 | `1801 et seq.`, `50 U.A.S. app. 2061 to 2170`, `687(f),697(e)(c)(8), and 650.` |
| **decimal section lists** | 208 | 82 | `4.9, 4.14B, 4.25, 5.9, 5.17` — see below |
| bare Public Law label | 187 | 59 | `Pub. L. 179`, `PL 425`, `PL 480` |
| damaged U.S.C. label the operators do not reach | 159 | 70 | `U.S.C. 1806`, `47 USC (f)`, `sec 3, USC 2012` |
| bare four-digit number | 154 | 50 | `1303`, `1702`, `1707`, `3535(d)` |
| date fragment | 112 | 35 | `11/04/1980)`, `NPS System of Records (07/28/1998)` |
| designator only | 74 | 18 | `Title I`, `Division BB`, `Chapter 33` |
| anaphoric act | 48 | 17 | `sec 1102 of the Act` — the act named earlier in a field that has no earlier |
| bill number | 37 | 11 | `H.R. 535`, `H.J. Res. 43 2017` |
| damaged Statutes label | 34 | 12 | `70A Stat. 157` (a lettered VOLUME, still deferred), `112 Stat/1920(1998)` |
| court rules | 27 | 2 | decided below |
| bare 2/3/5-digit number | 57 | 29 | `78w`, `321`, `46105` |
| D.C. instrument | 12 | 1 | `D.C. Law 18-88, sec. 56 DCR 7413` |
| CFR/FR label fragments | 18 | 4 | `sec. 7(b), 3 CFR, 1987`, `FR 114-255` |
| year-shaped bare number | 10 | 4 | `1903(q)`, `1817(i)` |
| OMB-control-shaped range | 7 | 3 | `1411-1419` |

**The decimal section lists are the Farm Credit Act.** 208 rows, 82 spellings,
and **166 of the agency-3052 rows are one agency**: the Farm Credit
Administration. The Farm Credit Act of 1971 numbers its sections by title and
decimal — 1.11, 4.3A, 5.17, 8.31 — which is why they look like nothing else
in this corpus (web-verified 2026-08-22 against the Act's own compilation).
The corpus proves it too: one failed value is `8.36, 8.37, 8.41 of the Farm`,
truncated mid-name. **It stays refused, and now it is named**: FCA resolves
**zero** act citations in sixty editions, so its roster is empty, the corpus
holds **zero** dotted act sections anywhere to generalise from, and borrowing
another agency's testimony is the cross-agency move wave 3 measured and
refused. This is the largest single named refusal the census now carries, and
unlike MMA it has no oracle anywhere in reach.

### Court rules — decided, finally

Refused for four censuses on the grounds that "a schema family for one rule
spelled twice does not earn its keep". Wave 5 replaces the grounds with a
measurement, because the earlier passes had only ever looked in the failed
pool. Searched across **all 798,122 authority values** for every federal rules
set — `Fed. R. Civ./Crim./App./Bankr./Evid.`, the spelled "Rules of …", the
`FRCP`/`FRE` initialisms — the corpus holds **27 rows, 2 spellings, one rule,
one agency**:

> `Fed. R. Bankr. P. 2015 (a)(2) to (a)(3)` (16) and `Fed R Bankr P 2015
> (a)(2) to (a)(3)` (11), all at agency 1105.

Nothing is hiding inside partially-parsed strings — the wave-3 lesson that
turned 46 lettered Stat pages into 206 does not apply here, because there are
no partial rows at all. **The population is closed and the refusal is final.**
A `court_rule` type would be one enum value, one agency, one rule, and no
check that could ever break; the rows stay preserved, typed `other`, and
named here with their specimens.

### MMA — decided, and it was a shape problem

Wave 4 cut MMA from 118 rows to 12 with the gloss oracle and called the
residue "honest". Seven of those rows were not an oracle problem at all:
`sec 932 (c) (2) MMA` opens a space between a section number and its own
subsection, which no abbreviation shape admitted, and `Sec. 408 and 946 of the
MMA of 2003` put a list where one shape took a single token. Both are now
read, and the gloss oracle answers them (144 → 150 rows).

**The residue is 14 rows over 7 values, and every one is named:**

- **six at Indian Health Service** (agency 0917), whose act roster is empty in
  all sixty editions. The rule `0917-AA07` cites exactly two things: `MMA,
  sec 506` and `PL 108-173` — which *is* the Medicare Modernization Act. A
  human reads it instantly. No adopted rule may: reading a public law number
  backwards into an act name is an oracle this census has never built, and
  building it for six rows on one rule is how a fence stops being a fence.
  **Refused, and this is the specimen that shows what refusing costs.**
- **eight at CMS**, all doubled or compound values that put two citations in
  one slot: `MMA, sec 629 MMA, sec 811`, `MMA 2003, MIPPA (title XVIII of the
  Social Security Act)`, `BBA, BA, BIPA, MMA, PPACA`, `Public Law 108, MMA`.

### Ledger after the fifth wave

| pool | before | after |
|---|---:|---:|
| authority rows failing to parse | 3,516 | **3,287** |
| corroborated rows (all rules) | 3,177 | 3,292 |
| corroborated act rows | 2,640 | 2,672 |
| act-relative rows | 8,896 | 8,955 |
| Public Law corrections carried | 100 | 112 |
| administrative orders | 1,211 | 1,244 |
| federal_register rows | 2,070 | 2,080 |
| constitution rows | 14 | 21 |
| total typed authority rows | 798,050 | 798,122 |
| authority rows stating nothing | 12,463 | 12,463 |
| timetable FR failures | 21 | 21 |
| out-of-series (USC/EO/PL/Stat) | 130/7/91/19 | 130/7/91/19 |

| corroboration rule | rows |
|---|---:|
| agency-roster-initialism | 2,290 |
| rin-history-section-list | 633 |
| agency-gloss-narrowed-initialism | 150 |
| rin-history-titleless-usc | 43 |
| roster-existent-public-law-pair | 40 |
| to-separator-roster-existence | 35 |
| agency-roster-word-prefix | 27 |
| rin-history-labelless-pair | 24 |
| space-separator-roster-existence | 18 |
| unique-dash-insertion | 17 |
| rin-history-volumeless-stat | 15 |

Every number is pinned in `tests/test_unified_agenda_parquet.py` against the
rebuilt Parquet, and each new operator carries a test stating the value it
**refuses** beside the value it reads.
