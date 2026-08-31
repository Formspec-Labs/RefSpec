# "States nothing extractable": 1,806 rows, and the sentence they were cut out of

**Ledger row.** `authority_type = 'other'` with both `stated_act_name` and
`stated_section` NULL, in
`output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet`.
1,806 rows, **662 distinct texts**. Five census waves took the unreadable pool
from 39,856 to 3,141; this is the 1,806 inside that residue which state
nothing the grammar could name.

**The finding in one line.** A large minority of these rows are not damaged
citations. They are *fragments of a citation the publisher broke across several
`<LEGAL_AUTHORITY>` elements at comma boundaries* — and the missing half is
sitting in the same record, at an adjacent ordinal, already parsed. The parquet
row cannot show this because the parser reads one element at a time. The XML
shows it immediately.

The second finding, which cuts the other way: **the same text has different
truths in different records.** `PL 108` is Pub. L. 106-108 in one record
(corroborated by a sibling Statutes cite) and unresolvable in another. Nothing
keyed on the value alone can ever be right here.

---

## Method

Ten rows, drawn reproducibly by seeded hash rather than `setseed()` so the
sample survives a DuckDB upgrade:

```sql
SELECT rin, publication_id, ordinal, authority_text
FROM 'output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet'
WHERE authority_type='other' AND stated_act_name IS NULL AND stated_section IS NULL
ORDER BY hash(rin || '|' || publication_id || '|' || ordinal::VARCHAR || '|states-nothing-2026-08-22')
LIMIT 10;
```

Seed string: `states-nothing-2026-08-22`. DuckDB v1.5.5.

For each specimen the **whole** `<RIN_INFO>` element was read out of the pinned
publisher XML in `output/registry-real-data-sources/unified-agenda-editions/` —
agency, parent agency, rule title, abstract, `CFR_LIST`, every sibling
`LEGAL_AUTHORITY`, timetable, related RINs, contacts. Corroboration was then
sought against: the eCFR authority note for the record's own CFR part (via
Zyte, eCFR blocks direct fetch), the 2006 annual CFR on govinfo, the pinned
`usc-popular-names.parquet` and `public-law-roster.csv` already in this tree,
and open web search.

Note on the editions: **`REGINFO_RIN_DATA_200404.xml` is not well-formed XML**
(`xml.etree` fails at line 148983, col 318). Specimen 8 had to be extracted by
regex over the raw bytes. Worth a separate check of which editions strict
parsers reject.

---

## 1. The ten specimens

### S1 — `50 U.S.C. seec. 167d (d)(1)` · RIN 1004-AE93 · 202210

BLM (Interior). Rule title *Helium Contracts*. `CFR_LIST`: **43 CFR 3195**
(helium contracts). Abstract: *"On October 2, 2013, Congress enacted the Helium
Stewardship Act of 2013… required BLM to dispose of the Federal Helium
System…"*. This is the **sole** legal authority on the record.

`seec.` is `sec.` with one letter doubled. Everything else is a perfectly formed
USC citation: title 50, section 167d, subsection (d)(1). The pinned
`usc-popular-names.parquet` files *Helium Stewardship Act of 2013* → Pub. L.
113-40, USC title **50** section **167** — the same title and section family the
damaged text states.

**Conclusion: recoverable, and it does not even need the typo repaired.** The
value states "50 U.S.C. `<noise>` 167d (d)(1)". The blocking condition is that
the grammar requires the token between the code label and the section number to
be a recognised section marker. Tolerating an unrecognised token there — when
title, section and subsection are all intact — costs no inference at all.

### S2 — `PL 425` · RIN 2900-AL84 · 200910

VA. *Special and Ancillary Benefits for Veterans, Dependents, and Survivors* —
part of VA's plain-language rewrite of its compensation and pension rules.
`CFR_LIST`: 38 CFR 3, 38 CFR 5. Nineteen legal authorities. Ordinals 15-18 read:

```
15: 38 USC 5304
16: PL 425          ← specimen
17: PL 97-377
18: ...             ← literal ellipsis; VA truncated its own list
```

`PL 425` is stable across **16 editions, 200404 → 201110**, always at ordinal 16
between the same two neighbours. It is not a transient typo; it is what VA typed
into the form.

The public-law roster pinned in this tree holds **27** congresses with a law
numbered 425. The value alone is 27-ways ambiguous.

Two things narrow it to one. First, VA itself writes `PL 92-425` in full at
**RIN 2900-AI83** (editions 199710 and 199804) — the only fully-spelled
`?-425` anywhere under agency code 2900. Second, Pub. L. 92-425 is the
**Survivor Benefit Plan Act of 1972** (86 Stat. 706), which enacted 10 U.S.C.
1447–1455 — and **10 U.S.C. 1448 is ordinal 1 of this very list.**

**Conclusion: recoverable at the agency altitude, with a date bound.** See §5,
H5 — and see the false positive that the missing date bound produces.

### S3 — `1085` · RIN 1880-AA87 · 201304

Dept. of Education, Office of Management. *Student Assistance General
Provisions — Electronic Filing System*. `CFR_LIST`: **34 CFR 668**. The whole
authority list is four elements:

```
0: 20 USC 1001 to 1003     → parsed: usc / ok / title 20 / § 1001
1: 1070g                   → other / failed
2: 1085                    → other / failed   ← specimen
3: <empty element>
```

The eCFR authority note for 34 CFR Part 668, fetched today, reads:

> **Authority: 20 U.S.C. 1001-1003, 1070g, 1085, 1088, 1091, 1092, 1094,
> 1099c, 1099c-1, 1221e-3, and 1231a, unless otherwise noted.**

The record's list is that sentence, cut at its commas, with the code label
surviving only on the first fragment.

**Conclusion: `1085` is 20 U.S.C. 1085.** Derived from the record's own list
structure, corroborated verbatim against the CFR part named in the record's own
`CFR_LIST`.

### S4 — `1182` · RIN 1650-AA04 · 200604

DHS / Border and Transportation Security. *US-VISIT: Biometric Requirements for
Exit at Air and Sea Ports*. `CFR_LIST`: **8 CFR 215**. List:

```
0: 8 USC 1101 to 1104            → usc / ok / title 8
1: 1182                          → other / failed   ← specimen
2: 1184                          → usc / corroborated / 8 USC 1184
3: 1185 (pursuant to EO 13323)   → executive_order / partial
4: 1365a note                    → usc / corroborated / 8 USC 1365a
5: 1379                          → other / failed
6: 1731 to 1732                  → other / failed
```

The 2006 annual CFR (govinfo, `CFR-2006-title8-vol1-part215.xml`) gives the
part's authority as *"8 U.S.C. 1104; 1184; 1185 (pursuant to Executive Order
13323, published January 2, 2004), 1365a note, 1379, 1731-32."* Ordinals 2-6
map onto it one-for-one, in order. Current eCFR adds 1101, 1103, 1104 — the
"1101 to 1104" of ordinal 0.

**1182 is the one member of this list that no published authority note for 8 CFR
215 contains.** The continuation reading (8 U.S.C. 1182, INA §212,
inadmissibility — squarely on point for a rule about aliens departing the US)
is monotone in position between 1104 and 1184, and is almost certainly what DHS
meant. But it is not corroborated by the part's note.

**Conclusion: this is the specimen that shows the fence has teeth.** A rule
fenced on "the reconstructed citation appears in the part's authority note"
refuses this row. A rule fenced on "the section exists under the carried title"
admits it. The second fence is the defensible one — the agenda's authority
field is the agency's own free text, not a copy of the CFR note — but the
divergence has to be measured, not assumed.

### S5 — `1903(b)(3)` · RIN 0936-AA07 · 201604

HHS Office of Inspector General. *Medicaid, Revisions to State Medicaid Fraud
Control Unit Rules*. `CFR_LIST`: **42 CFR 1007**, 42 CFR 455.21. List:

```
0: 1007: SSA Subsection 1902 (a) (61)   → other / failed
1: 1903 (a)(6)                          → other / failed
2: 1903(b)(3)                           → other / failed   ← specimen
3: 1903(q)                              → other / failed
4: 1102                                 → other / failed
5: ...                                  → unstated / failed
```

eCFR, 42 CFR Part 1007:

> **Authority: 42 U.S.C. 1302, 1396a(a)(61), 1396b(a)(6), 1396b(b)(3), and
> 1396b(q).**

Element-by-element, in order: SSA §1902(a)(61) = 42 U.S.C. 1396a(a)(61); SSA
§1903(a)(6) = 1396b(a)(6); **SSA §1903(b)(3) = 1396b(b)(3)**; SSA §1903(q) =
1396b(q); SSA §1102 = 42 U.S.C. 1302.

The label declared once at ordinal 0 is not a USC title at all — it is an act
(`SSA`), prefixed by the CFR part number (`1007:`). Four continuations inherit
it.

**Conclusion: `1903(b)(3)` is Social Security Act §1903(b)(3).** This is the
variant of the continuation pattern where the carried label is act-relative, and
the schema already has `act_key`/`act_section` plus a pinned act→USC index
(`usc-act-sections.parquet`) to land it.

### S6 — `309(a), 309(j), 316, 332, 403, 615a–1, 615c, and 1302, unless otherwise noted` · RIN 3060-AK40 · 202304

FCC. *Amendments to Part 4… Disruptions to Communications*. `CFR_LIST`: 47 CFR
0, **47 CFR 4**, 47 CFR 63. Five elements; concatenated they are one sentence:

```
0: sec. 1, 4(i), 4(j), 4(o), 251(e)(3), 254, 301, 303(b), 303(g), 303(r), 307, 309(a), 309(j)
1: 316, 332, 403, 615a–1, and 615c of Pub. L. 73–416, 4 Stat. 1064, as amended
2: and sec. 706 of Pub. L. 104– 104, 110 Stat. 56
3: 47 U.S.C. 151, 154(i)–(j) & (o), 251(e)(3), 254, 301, 303(b), 303(g), 303(r), 307
4: 309(a), 309(j), 316, 332, 403, 615a–1, 615c, and 1302, unless otherwise noted   ← specimen
```

That is a CFR authority note verbatim, split at commas. Ordinal 4 is the tail of
ordinal 3, which states `47 U.S.C.`. eCFR's current note for 47 CFR Part 4
contains 309, 316, 332, 403, 615a-1 and 1302 — all under title 47.

Note also that ordinals 1 and 2 *did* parse (public_law 73-416, 104-104;
statute_at_large 4/1064 and 110/56) — so **four of five fragments of one
sentence produced typed rows and one produced a "states nothing" row.** The
census metric is counting sentence fragments, not citations.

Also visible: `4 Stat. 1064` is the publisher's own error for 48 Stat. 1064,
which the grammar happily accepted. Silent wrong reads live next door to loud
refusals.

**Conclusion: 47 U.S.C. 309, 316, 332, 403, 615a-1, 615c, 1302.**

### S7 — `The Global War on Terror and Tsunami Relief, 2005` · RIN 1601-AA59 · 200910

DHS Office of the Secretary. *Minimum Standards for Driver's Licenses…* (REAL
ID). `CFR_LIST`: 6 CFR 37. Four elements:

```
0: Division B-- REAL ID Act of 2005
1: The Emergency Supplemental Appropriations Act for Defense
2: The Global War on Terror and Tsunami Relief, 2005          ← specimen
3: PL 109-13, 119 Stat 231, 302 (May 11, 2005) (codified at 49 USC 30301 note)
```

Ordinals 1 and 2 are **one act name split at a comma**: the *Emergency
Supplemental Appropriations Act for Defense, the Global War on Terror, and
Tsunami Relief, 2005*. Ordinal 1 kept the word "Act" and parsed; ordinal 2 did
not and fell to `other`. Ordinal 3 states the identity outright: **Pub. L.
109-13, 119 Stat. 231**.

**Conclusion: recoverable, and the record states the answer three elements
later.** This is the purest case in the sample: no oracle needed, no damage
operator, just reading the list as a sentence.

### S8 — `15 US 1392` · RIN 2127-AJ40 · 200404

NHTSA (DOT). *Response to Petitions for Reconsideration of TREAD Child Restraint
Performance (FMVSS No. 213)*. `CFR_LIST`: **49 CFR 571.213**. Sole authority.

15 U.S.C. 1392 was §103 of the National Traffic and Motor Vehicle Safety Act of
1966 — *Federal motor vehicle safety standards*, the authority for 49 CFR Part
571. It was **repealed by Pub. L. 103-272 (5 July 1994) and recodified at 49
U.S.C. 30111.** NHTSA was citing the pre-1994 codification in 2004.

`US` for `USC` is a one-character deletion. The competing reading — 15 U.S.
1392, i.e. U.S. Reports vol. 15 — dies on the oracle: volume 15 (2 Wheaton) has
no page 1392. Exactly one survivor.

**Conclusion: 15 U.S.C. 1392, subject to a time-indexed oracle.** A
current-USC section roster kills *both* readings and the row refuses for the
wrong reason. Any section-existence fence used on this corpus must be indexed to
the publication date, or must include repealed sections.

### S9 — `(as amended)` · RIN 0412-AB01 · 202304

USAID. *Removing the Program Income Restrictions on For-Profit Entities*.
`CFR_LIST`: **2 CFR 700**. List:

```
0: Pub. L. 87–195, sec. 621(a)
1: 22 U.S.C. 2381
2: (as amended)              ← specimen
3: E.O. 12163 (44 FR 56673)
4: 75 Stat. 445
```

eCFR, 2 CFR Part 700:

> **Authority: Sec. 621, Public L. 87-195, 75 Stat 445, (22 U.S.C. 2381) as
> amended, E.O. 12163, Sept 29, 1979, 44 FR 56673; 2 CFR 1979 Comp., p. 435.**

Same sentence, same commas, same five pieces.

**Conclusion: not recoverable, and correctly so.** `as amended` is a grammatical
modifier of the preceding citation. It has no identity to recover. The only
improvement available is to *classify* it as a modifier belonging to ordinal 1
rather than to leave it looking like a failed citation. 16 rows in the
population are modifier-only (`note`, `(as amended)`, `unless otherwise noted`,
`and`).

### S10 — `114 Pub. L. 185` · RIN 1880-AA89 · 201904

Dept. of Education. *Availability of Information to the Public (Freedom of
Information Act) Amendments*. `CFR_LIST`: 34 CFR 5. Abstract: *"We are making
these amendments to align our FOIA regulations with the **FOIA Improvement Act
of 2016**."* Siblings: `5 U.S.C. 552`, `20 U.S.C. 1221e-3`, `20 U.S.C. 3474`.

The pinned `usc-popular-names.parquet` files *FOIA Improvement Act of 2016* →
**Pub. L. 114-185**, 130 Stat. 538.

The text carries the marker `Pub. L.` flanked by exactly the two integers 114
and 185, in document order, with the hyphen replaced by the marker itself.
Candidate readings: 114-185 and 185-114. The second dies immediately — there has
never been a 185th Congress, and the publication is 201904 (116th).

**Conclusion: Pub. L. 114-185.** Damage operator: the `Pub. L.` marker migrated
into the hyphen position. Oracle: the public-law roster. Exactly one survivor,
and the abstract independently names the act.

---

## 2. The pattern the parquet row cannot show

**Six of ten specimens are fragments of a sentence the publisher cut at commas.**
S3, S4, S5, S6, S7, S9. In four of them the eCFR authority note for the
record's own CFR part reconstructs the sentence verbatim.

This is a property of `<LEGAL_AUTHORITY_LIST>`, not of any single element. The
list is sometimes a set of independent citations (RIN 2900-AL84: nineteen
elements, each restating `38 USC` or `10 USC`) and sometimes one wrapped
sentence (RIN 1880-AA87: `20 USC 1001 to 1003` / `1070g` / `1085` / ∅). The
parser sees only the element.

Measured over all 1,806:

| | rows |
|---|---:|
| an **earlier element in the same list** states a USC title | **1,088** (60%) |
| the row is the sole authority on the record | 193 |
| the row is at ordinal 0 | 357 |

### The naive version of this rule is wrong, and measurably so

"Inherit the nearest preceding stated title" agrees with the element's own
stated title in only **84.2%** of the 442,298 corpus pairs where both are
present. Lists genuinely mix titles.

The counterexample is instructive. RIN 2501-AD75 (HUD, 201604):

```
0: 12 U.S.C. 1701q
1: 12 U.S.C. 4568
2: 1437a, 1437c, 1437d, 1437f, 1437n, 1437z-2, 1437z-7   ← bare
3: 42 U.S.C. 3535(d)
4: 42 U.S.C. 5301-5320
```

Every `1437*` section is **42** U.S.C. (US Housing Act of 1937). The nearest
*preceding* label is 12. The correct label is stated *after* the fragment.

### The version with a fence is much better

Take candidates from **every** code label stated anywhere in the same list, and
require **every** section token in the value to exist under exactly one of them.
Over the 494 rows in the population that carry no code label and tokenise as a
section list:

| outcome | rows |
|---|---:|
| exactly one surviving title → resolves | **347** |
| several surviving titles → refuses | 72 |
| no surviving title → refuses | 31 |
| no label stated anywhere in the list → refuses | 44 |

Of the 347, **339** agree with the nearest preceding label, **7** name a
different label the list states elsewhere (the fence is doing real work), and 1
had no preceding label at all.

Caveat, and it is not small: this measurement used a **corpus-internal** section
roster — the 11,093 distinct `(title, section)` pairs the grammar read from the
798,122 rows. That roster contains agency errors as well as facts. It reports,
for instance, that `752` exists under title 5 but not 16, which is why RIN
1018-AX21's `752` came back as 5 U.S.C. while its list-mates `725` and `715i`
came back as 16 U.S.C. **The number 347 is an upper bound until the fence is
re-run against a real OLRC section roster, time-indexed to the publication.**

---

## 3. Four more patterns that only the record shows

### 3.1 The record often states the answer in a neighbouring element

| RIN | damaged element | the sibling that resolves it |
|---|---|---|
| 1601-AA59 | `The Global War on Terror and Tsunami Relief, 2005` | ordinal 3: `PL 109-13, 119 Stat 231` |
| 0906-AB14 | `FR 114-255` | ordinal 0: `21st Century Cures Act` → popular-names → **114-255** |
| 1018-AW75 | `PL 106` + `PL 108` | ordinal 5: `113 Stat. 1491` → roster → **106-108** |
| 0710-AA94 | `Pub. L. 738` | ordinal 1: `33 U.S.C. 701a` → Flood Control Act of 1936 → **Pub. L. 74-738**, 49 Stat. 1570 |
| 2900-AL84 | `PL 425` | ordinal 1: `10 U.S.C. 1448` → Survivor Benefit Plan → **Pub. L. 92-425** |

The FWS case is worth spelling out. RIN 1018-AW75 (migratory birds, light
geese):

```
0: Migratory Bird Treaty Act, 40 Stat. 755 (16 USC 703)
1: PL 95 616                                  ← hyphen lost
2: 92 Stat. 3112 (16 USC 712(2))              ← the Stat cite for 95-616
3: PL 106                                     ← specimen family
4: PL 108                                     ← specimen family
5: 113 Stat. 1491, Note following 16 USC 703  ← the Stat cite for 106-108
```

The list alternates (public law) → (its Statutes cite). Ordinals 3 and 4 are the
two halves of **Pub. L. 106-108**, the *Arctic Tundra Habitat Emergency
Conservation Act*, 24 Nov 1999, **113 Stat. 1491**, codified as a note following
16 U.S.C. 703 — every word of which ordinal 5 states.

And the disambiguation is real work: Pub. L. **108-106** also exists (117 Stat.
1209). The sibling's Statutes volume 113 kills it. Exactly one survivor.

### 3.2 The same text has different truths in different records

`PL 108` appears in the population twice:

- RIN 1018-AW75 — resolves to 106-108, corroborated by `113 Stat. 1491`.
- RIN 2105-AD07 (DOT, governmentwide debarment, 200204) — the list is
  `EO 11738 / EO 12689 / EO 12549 / PL 103-355 / PL 108 / 31 USC 6101`. Nothing
  in the record constrains it. Refuses.

The same holds for `PL 480`, which at RIN 0560-AG49 (USDA FSA, siblings `7
U.S.C. 1431`, `7 U.S.C. 1736o`, `15 U.S.C. 714 et seq.`) is **not damage at all**
— it is the conventional short name of the *Agricultural Trade Development and
Assistance Act of 1954*, universally cited as "P.L. 480".

**Consequence: any lookup table keyed on `authority_text` is unsound here.**
Recovery has to be per-record.

### 3.3 The corpus carries its own damaged/undamaged twins

The same authority value appears in this corpus in both a broken and an intact
spelling, usually at the same RIN in different editions:

| damaged | intact | RIN |
|---|---|---|
| `687(f),697(e)(c)(8), and 650.` | `687(f),697e(c)(8), and 650` | 3245-AE14 (SBA) |
| `697(e)(c)(8)` | `15 USC 697e(c)(8)` | 3245-AE14 |
| `Fed. R. Bankr. P. 2015 (a)(2) to (a)(3)` | `Fed R Bankr P 2015 (a)(2) to (a)(3)` | 1105-AB30 |
| `PL 95 616` | `PL 95-616` | 1018-AW75 |
| `PL 425` | `PL 92-425` | agency 2900 (2900-AL84 / 2900-AI83) |

This is a ready-made hold-out set for calibrating damage operators: the intact
spelling is the answer key, and it was written by the same agency about the same
rule.

### 3.4 Mechanical damage classes, sized

Partitioning all 1,806 (single label per row, first match wins):

| bucket | rows | what it is |
|---|---:|---|
| bare section continuation (an earlier element in the list states a label) | **444** | §2 |
| out-of-schema body of law | **207** | Fed. R. Bankr. P. (27), treaties/NAFTA (27), OMB memos & circulars (38), agency handbooks FSH/FSM/Orders (25), court cases (19), bills H.R./S./H.J.Res (16), FIPS/NIST (9), policies & guidance (56) |
| name or acronym only, no digits | **153** | `MIPPA`, `BBRA`, `BIPA '00`, `PPRA`, `MMSEA`, `HIPAA`, `SAFTEA LU`, `Withdrawn`, `Department of Homeland` |
| `Pub. L.`/`PL` fragment | **149** | §5 H5 |
| damaged code label | **116** | `15 US 1392`, `31 UC 3711`, `49 SUC 45102`, `42 USO 299b-12`, `7 U.S. 6g`, `U.S.C. 201` (no title), `seec.` |
| title/division/chapter designator only | **79** | `Title I`, `title XIX`, `Division BB`, `Chapter 33` |
| bare section, but **no** label anywhere in the list | 52 | refuses |
| modifier only | 16 | `(as amended)`, `note`, `unless otherwise noted`, `and` |
| residual | 590 | mixed; includes multi-token section lists my crude tokeniser rejected |

Small, cheap sub-classes inside that: uppercase `STAT` (2 — `61 STAT 1180`),
appendix spelled `ap`/`App.` (17 — `50 USC ap 2401 et seq`, and the schema
already has `usc_appendix`), chapter-word cites (20), spaced ellipsis `. . .`
(4), slash separator (4 — `112 Stat/1920(1998)`), mojibake (1 — `Pub. L.
105¿-261`, a Latin-1/UTF-8 collision where an en-dash should be), fused range
(1 — `and 129012912` for 12901-12912, whose sibling is `12701-12711,
12741-12756`).

Note the ellipsis `...` does **not** appear in this population — it is filed
`unstated`, and belongs to the sibling ledger row.

---

## 4. Why the existing corroborators miss these

The pipeline already has a `_CitationHistory` oracle with rules named
`rin-history-section-list` (633 rows), `rin-history-titleless-usc` (43),
`rin-history-labelless-pair` (24), `rin-history-volumeless-stat` (15). They are
good rules. They miss these rows for three specific, nameable reasons.

1. **The oracle is built from the RIN's *other editions* and the agency's
   *other rules*. It never consults the adjacent element in the same list.**
   For S3, the title is stated at ordinal 0 of the very same list in the very
   same edition, and the oracle does not look there.

2. **`_history_section_tokens` → `section_survivors` requires the section to be
   corpus-wide unique across titles** (`len(usc_titles_by_section[value]) != 1`
   → silent). `1085` is used in titles 10, 20 and 42; `1182` in 8, 18 and 29.
   The uniqueness fence is right for a *titleless* citation floating free. It is
   the wrong fence for a *continuation*, where the title is not unknown — it is
   stated four elements up.

3. **A list whose head element also failed has nothing to bootstrap from.** S5's
   ordinal 0 (`1007: SSA Subsection 1902 (a) (61)`) never parsed, so it never
   entered the history, so none of its four continuations could.

And one more, for the acronym bucket: **the oracle is present in this tree; the
fence is what refuses.** `usc-popular-names.parquet` holds *Medicare Improvements
for Patients and Providers Act of 2008* → 110-275. But `_abbrev_survivors` is
fenced to acts **the agency's own grammar-read rows named**, and agency 0938
(CMS) never once spells that name out — measured: **0 rows** in the whole corpus
contain "improvements for patients". So MIPPA refuses. That is the fence working
as designed; whether it is the right fence is a measurement, not an opinion
(§5 H7).

---

## 5. Leads worth a rule

Each stated as a hypothesis, with what it rests on and what has to be measured
before adoption. None of these is proposed for adoption here.

### H1 — List continuation of a stated code label

**Hypothesis.** Within one `<LEGAL_AUTHORITY_LIST>`, an element that carries no
code label continues the code label the list itself states.

**Declared convention.** The list is the publisher's line-wrapping of one
authority sentence; the label appears once, at the head.

**Fence.** Candidates = every `(scheme, title)` any element of the same list
states. Every section token in the value must exist under **exactly one**
candidate in a pinned section roster. Zero or several survivors → refuse.

**Evidence.** S3 (verbatim against the 34 CFR 668 note), S6 (verbatim against 47
CFR 4), S5 (verbatim against 42 CFR 1007). 494 candidates in the population; 347
one-survivor under a corpus-internal roster.

**What must be measured.**
(a) Re-run against a real OLRC section roster, **time-indexed to the publication
date** — the corpus-internal roster is contaminated (§2) and a current-only
roster kills repealed sections (S8).
(b) Hold-out in the style already used for `_anchored_subsequence`: take
elements that *do* state their own label, blank it, and count how often the rule
invents a title the element did not have. The naive form is 84.2% over all
pairs; the fenced form must be measured separately and must reach the "invented
0 times" bar the existing operators meet.
(c) Decide what the row *emits*. S4 shows a correct-looking reading that no
published authority note supports. If the intended semantics is "what the record
states", 8 U.S.C. 1182 is right. If it is "a citation corroborated against the
CFR", it refuses.

### H2 — Act-relative continuation

**Hypothesis.** Same as H1, but the head label is an act, not a USC title
(`1007: SSA Subsection 1902 (a) (61)` → `1903 (a)(6)` → `1903(b)(3)`…).

**Fence.** The act must resolve at an admissible altitude, and every
continuation section must exist in `usc-act-sections.parquet` under that act.

**Evidence.** S5, corroborated element-for-element against the 42 CFR 1007 note.

**What must be measured.** How many lists open with an act label rather than a
code label; whether `SSA`-style bare initialisms clear the same agency-roster
fence that MIPPA fails (they may not, which would make this rule fire on very
few rows).

### H3 — Public-law number split across adjacent elements

**Hypothesis.** Two adjacent elements of the form `PL <a>` and `PL <b>` are one
public law `<a>-<b>`.

**Fence.** `(a,b)` must exist in the pinned roster **and** its Statutes volume
must equal a Statutes cite stated elsewhere in the same list. The reversed pair
`(b,a)` must fail that test.

**Evidence.** RIN 1018-AW75: `PL 106` + `PL 108` + `113 Stat. 1491`; roster gives
106-108 → vol 113, 108-106 → vol 117. Exactly one survivor. Confirmed
independently: Pub. L. 106-108, 24 Nov 1999, 113 Stat. 1491, Arctic Tundra
Habitat Emergency Conservation Act, codified as a note following 16 U.S.C. 703 —
which is what ordinal 5 says.

**What must be measured.** How many such adjacent pairs exist (small — likely
single digits); and the schema question this raises: two rows resolving to one
identity, or one row resolving and one marked as its continuation. That is a
design decision, not a measurement.

### H4 — Sibling gloss corroborates a well-formed pair under a wrong label

**Hypothesis.** When an element carries a well-formed `<congress>-<number>` pair
under a wrong or missing label, and an adjacent element names an act, the pair is
confirmed if the popular-names index maps that act to exactly that pair.

**Evidence.** RIN 0906-AB14: ordinal 0 `21st Century Cures Act`, ordinal 1 `FR
114-255`; `usc-popular-names.parquet` → 114-255. Also S10, where the *abstract*
rather than a sibling supplies the act name.

**What must be measured.** Whether the abstract may be used as testimony at all
— it is a different field with different discipline, and admitting it is a
policy change, not a rule change. If only sibling elements count, S10 still
resolves on the roster alone (185 is not a congress) and this rule is
unnecessary for it.

### H5 — Congress-less `Pub. L. <n>` at the agency altitude, with a date bound

**Hypothesis.** `PL 425` is `Pub. L. C-425` for the unique C the RIN or its
agency attests.

**Measured over the population.** 103 congress-less fragments. **Median 37
candidate congresses each** in the roster — the value alone is hopeless. Under
the existing two-altitude fence (`_oracle_levels`: RIN, then agency code):
0 resolve at RIN level, **33** resolve uniquely at agency level, 70 have no
attestation at any altitude, 0 hit multiple.

**And one of the 33 is wrong.** RIN 2030-AA91 (EPA, Fall 2006) has `PL 101` as
its **sole** authority. The agency roster resolves it to Pub. L. 113-101 —
because a *different* EPA RIN, **2030-AB05 in edition 202510**, cites Pub. L.
113-101 in full. Pub. L. 113-101 is the Water Resources Reform and Development
Act of **2014**. A Fall 2006 agenda cannot cite it.

**What must be measured.** Re-run with `roster.date <= publication date`. The
machinery exists (`_pl_roster()` already loads approval dates;
`_act_key_within_calendar` already date-bounds act names) but `_CitationHistory`
is keyed only by RIN and agency. Report the date-bounded count, and hold out the
fully-spelled pairs the grammar already read to count inventions. Until that
number is on the table this rule should not ship: it currently manufactures at
least one anachronism out of 33.

### H6 — Free grammar gaps

Cheap, no oracle, no inference — the value already states its identity and the
spelling is unrecognised:

- unrecognised token between code label and section (`seec.`) — S1
- code label with a deleted or substituted letter: `US`, `UC`, `SUC`, `USO`,
  `U.S.` — S8 and ~116 rows
- uppercase `STAT` (2), `Stat/` slash separator (4)
- appendix spelled `ap` (17) — `usc_appendix` already exists in the schema
- mojibake `¿` where an en-dash belongs (1)

**What must be measured.** For the letter-substitution class, the competing
reading has to die on an oracle in each case (S8's `15 U.S.` dies on U.S.
Reports pagination). Enumerate the substitutions actually observed rather than
allowing edit distance ≤ 1 generally.

### H7 — Widening the abbreviation roster

**Hypothesis.** The 153 name/acronym-only rows (largely CMS: MIPPA, BBRA, BIPA
'00, BBA '97, MMSEA, PPRA) are resolvable against the OLRC popular-names index
rather than the agency's own attested roster.

**Evidence for.** The oracle is already pinned in this tree and holds the
expansions. **Evidence against, already recorded in the code:** the corpus-wide
abbreviation roster "invents a wrong survivor 15.25% of the time even
date-bounded".

**What must be measured.** Whether a *narrower* widening — popular-names
filtered by publication date **and** by the USC title(s) the same RIN's other
authorities cite — keeps invention at zero on the existing hold-out of 137
abbreviation citations. If it does not, the answer is no, and the 153 rows stay
where they are.

---

## 6. Named reasons to stop

These are worth as much as the leads. Each is a class that should be marked
*not recoverable* and closed, not left as an open question.

**R1 — Modifiers (16 rows).** `(as amended)`, `note`, `unless otherwise noted`,
`and`. These are grammar, not identity. Corroborated: the 2 CFR 700 authority
note contains the literal words "as amended" as a modifier of the preceding
citation (S9). There is nothing to recover. The only improvement available is to
reclassify them as continuations of the preceding element.

**R2 — Bodies of law the schema has no column for (207 rows).** Federal Rules of
Bankruptcy Procedure (27), treaties and international instruments (27), OMB
memoranda and circulars (38), agency handbooks, orders and delegations (25),
reported court decisions (19), unenacted bills (16), FIPS/NIST standards (9),
agency policies and plans (56). `Fed. R. Bankr. P. 2015(a)(2)` is a perfectly
well-formed citation to a body of law this table cannot express. Admitting them
is a schema decision, not a parsing decision, and it should be taken on its own
merits rather than smuggled in as "recovery".

**R3 — Bills (16 rows).** `H.R. 535`, `H.J. Res. 43 2017`. A bill number names a
legislative vehicle, not a law. Until enacted it has no public-law identity, and
which Congress's H.R. 535 is meant is not stated. Refuse permanently.

**R4 — Congress-less public-law fragments with no attestation (70 of 103).**
Median 37 candidates, nothing in the record or the agency's history to narrow
them. `PL 425` is recoverable because VA wrote `PL 92-425` elsewhere; the other
70 have no such witness. There is no operator that reaches them without
inventing a congress the text does not state.

**R5 — Designator-only values (79 rows).** `Title I`, `title XIX`, `Division
BB`, `Chapter 33`. A title designator with no act is a pointer into an unnamed
document. Where the act is named in a sibling these become H1-style
continuations; where it is not (`Title I` at RIN 1545-BQ28, sole authority),
there is no act to point into.

**R6 — Non-citations (a handful).** `Withdrawn`, `See Additional Information.`,
`Department of Homeland`, `. . .`. The agency did not answer the question.

**R7 — Value-level recovery is impossible in principle.** `PL 108` is Pub. L.
106-108 in one record and unresolvable in another; `PL 480` is damage-shaped but
is actually the correct conventional name of the Agricultural Trade Development
and Assistance Act of 1954. Any proposal that maps `authority_text` → identity
without the record is unsound regardless of how the mapping was derived.

---

## 7. What this report does not establish

- **No count of how many of the 1,806 are actually recoverable.** 347 is an
  upper bound for H1 under a contaminated roster, not a result.
- **The corpus-internal section roster is not an oracle.** It is built from
  grammar reads that include agency errors (`4 Stat. 1064` for 48 Stat.; `15 USC
  780-10` for 78o-10, an o/0 substitution that parsed *successfully* into a
  section that does not exist). Every measurement above that leans on it is
  provisional.
- **Silent wrong reads were not surveyed.** S6 contains one (`4 Stat. 1064`)
  that the grammar accepted. This ledger row counts loud refusals; it says
  nothing about how many typed rows are wrong. That is a different and probably
  larger question.
- **Time-indexing was not built.** S8 needs a 2004-vintage USC; H5 needs a
  publication-date bound. Both were reasoned about, neither was measured.
- **`REGINFO_RIN_DATA_200404.xml` is not well-formed XML.** Not investigated
  beyond noting it. Which editions strict parsers reject, and whether the
  pipeline's own reader silently recovers, is unexamined.

---

## Reproduction

```bash
# the population
duckdb -c "SELECT count(*), count(DISTINCT authority_text)
 FROM 'output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet'
 WHERE authority_type='other' AND stated_act_name IS NULL AND stated_section IS NULL;"
# -> 1806, 662

# the sample (seed string: states-nothing-2026-08-22)
duckdb -c "SELECT rin, publication_id, ordinal, authority_text
 FROM 'output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet'
 WHERE authority_type='other' AND stated_act_name IS NULL AND stated_section IS NULL
 ORDER BY hash(rin || '|' || publication_id || '|' || ordinal::VARCHAR || '|states-nothing-2026-08-22')
 LIMIT 10;"
```

Source records: `output/registry-real-data-sources/unified-agenda-editions/REGINFO_RIN_DATA_<publication_id>.xml`,
`<RIN_INFO>` element whose `<RIN>` matches.

External oracles consulted: eCFR part authority notes for 34 CFR 668, 8 CFR 215,
47 CFR 4, 42 CFR 1007, 2 CFR 700 (via Zyte; eCFR 302-redirects direct fetches);
`CFR-2006-title8-vol1-part215.xml` on govinfo. In-tree oracles:
`output/usc-act-index-2026-08-02/usc-popular-names.parquet`,
`output/usc-act-index-2026-08-02/usc-act-sections.parquet`,
`output/usc-source-credit-index-2026-08-02/usc-source-credits.parquet` (thin —
109 public laws; did not cover any candidate here),
`output/registry-real-data-sources/public-law-roster/public-law-roster.csv`.
