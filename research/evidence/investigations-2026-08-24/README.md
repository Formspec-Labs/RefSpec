# Read-only investigations of 2026-08-24

- `inv-eo/` — the Executive Order existence oracle research: corpus census
  (19,011 executive_order rows, 391 distinct numbers, 1197–23891),
  the FR API's executive-order records (from EO 12890, 1,531 numbers,
  two pages verbatim), NARA's Truman→Reagan codification numeric index
  (18 pages, 4,162 rows) and 108 per-order detail pages, the derived
  eo-roster.csv (5,693 entries, source per row), the join
  (345 of 391 cited numbers confirmed; 46 unresolved — 32 in the
  1990–1993 gap between the two sources, 9 pre-1929, 2 FDR-era outside
  the codification's blind spot, 3 already series-flagged), zero
  anachronisms, and the correction candidates (8284 → 8248 by adjacent
  transposition with the live-authority + subject tie-break; 23891 →
  13891 by leading-digit substitution, the text carrying 13891's own
  title and date; 20450 → 10450 needing one more witness; 21600 and 7419
  refused with 2 and 5 survivors). NARA's disposition-table URLs now serve
  an index stub — the codification numeric route is the working one.
  MANIFEST-sha256.csv lists every fetched file's digest.
- `inv-dropped/` — the two DROPPED classes the re-survey named, counted
  corpus-wide on rebuild #11. CLASS 1, compact slash compounds: 257
  non-date texts with `/`; 235 texts / 1,539 rows lose a second authority
  (223 texts are `USC NNN/ACT NNN` with an EPA act abbreviation — CAA, CWA,
  TSCA, RCRA, FFDCA, CERCLA, SDWA, FIFRA…; 8 spell the act out and are
  still dropped). Mechanism, read from the grammar: the whole-value
  fallback (`if not citations:` → stated_act_name/stated_section) fires
  only when the entire string yielded nothing, so once the first USC
  citation matches the remainder is discarded and never re-scanned; `/`
  has no handling at all. 14 texts / 87 rows are traps (the 9/11
  Commission Act, place names, docket prefixes, `7401/et seq`). CLASS 2,
  range endpoints lost: 401 genuine texts — in-list ranges 191 texts /
  3,880 rows (`_USC_LIST_TAIL` has no range tail), parenthesised
  endpoints 57 / 249, compound-name endpoints 43 / 491 (`range_end` uses
  the narrow token), spelled shorthand never expanded 54 / 149
  (`1817 to 19` fails where `1817-19` expands), 63 / 281 unclear or
  descending (the ordering refusal is probably right); the appendix
  pattern's 53 instances belong to #60. Trap: prose "to" between two full
  citations (19 texts / 63 rows) — failed range-end capture backtracks
  into the second citation's title digit and the WHOLE second citation
  vanishes. Five endpoints verified real at uscode.house.gov. Seeded 20s
  and full row lists as JSON.
- `inv-placeholders/` — candidate authorities for the 12,467 placeholder
  records (6,876 more-citations-follow / 5,461 not-yet-determined / 130
  none-off-form; 1:1 rows to records). Witness A, the record's own CFR
  parts' authority notes (gen 2): reaches 91.9% / 38.5% / 39.2% of records
  with ≥1 held note, yields ≥1 candidate for 87.0% / 38.4% / 39.2%
  (150,392 / 39,211 / 448 pairs; median note 3 citations, omnibus tails —
  26 CFR 1 has 322). Witness B, the same RIN's other editions stating
  more: 6.2% / 62.2% / 13.8% (2,603 / 13,171 / 78 pairs; degrades
  gracefully on omnibus parts). Either witness: 87.2% / 75.8% / 43.1%; where
  both exist they intersect 60–100% of the time and the intersection is the
  strongest signal (0960-AE79 keeps 42 U.S.C. 1382/902, drops a stray
  38 U.S.C. 1805(d) from early editions). Traps measured: multi-program
  parts (34 CFR 682+685), generic Part-1 boilerplate (17 CFR 1), omnibus
  explosion, temporal drift (a 2007 placeholder offered 2020 Public Laws
  from a 2026 note). DEFECT in the shared note reader: EO compilation date
  ranges ("E.O. 10577, 3 CFR, 1954-58 Comp., p. 218") read as U.S.C. spans
  under the preceding title — 600 notes carry a Comp. phrase, 818 citations
  / 291 identities are year-shaped (3.0% of A's pairs; also touches the
  shipped authority_in_own_cfr_note with a smaller blast radius) — the
  #46 list-tail fence, now sized in the notes. Per-record candidate lists
  for all 12,467, summary.json, specimens.json, the analysis script.
- `inv-b8/` — the two-witness rule for `NNN(x)` read as section NNN where
  `NNNx` is also real (the largest silent class in both surveys). Population
  14,740 readings / 14,073 rows / 1,340 texts / 2,641 RINs; witness 1 (the
  subsection oracle: NNN has no subsection x) fires on 1,887 readings;
  witness 2a (the part's note names NNNx, not NNN) 4,112; witness 2b (the
  RIN's other editions spell NNNx) 2,083. PUBLISH = witness 1 + (2a or
  2b): 1,171 readings / 1,166 rows / 204 texts / 238 RINs, every one
  reading `exists` today (the silent class exactly), 65 already caught by
  B1 → 1,101 net new; CANDIDATE 4,201 rows (664 witness-1-alone; 3,560
  a note/edition witness without witness 1); REFUSE 8,888 (ambiguous by
  structure or unknowable). Tail lesson holds on all 18 tail-bearing
  publish rows (1735f-14, 300v-1, 7385s-10). 15/15 seeded publish
  specimens on-subject at uscode.house.gov (15 USC 18(a) → 18a for the
  FTC's own premerger rule; 42 USC 6939(g) → 6939g e-Manifest; 31 USC
  3720(D) → 3720D Garnishment). Design: a rule layered on the existing
  B8 candidate machinery, evidence quoting both witnesses; the 147
  "note names bare NNN too" conflicts are caveats, not vetoes.
- `inv-eo-gap/` — the 1990–1993 Executive Order gap closed from NARA's
  per-YEAR disposition pages (archives.gov/federal-register/executive-
  orders/1989-bush.html, 1990.html, 1991.html, 1992.html — live, found via
  archives.gov's sitemap; the per-president aggregate pages are the stubs)
  plus NARA's 1993-bush.html and 1993-clinton.html, dead on the live site
  and recovered from the Wayback Machine (snapshots 2017-05-23 and
  2017-01-02, sha256 pinned) — NARA's own content, secondary host, stated
  as such. eo-gap.csv resolves all 32 cited numbers with signing date, FR
  citation and title; EO 12866 = "Regulatory Planning and Review",
  1993-09-30, 58 FR 51735. The 9 pre-1929 and the two FDR-era numbers
  (7419, 8284) have no keyless primary listing — NARA's tables start
  1937-01-08 — and stay `unknown`, gap named. Corroboration only: the FR
  API returns 2,486 documents citing "Executive Order 12866 of September
  30, 1993". govinfo's /metadata/pkg/{id}/mods.xml is keyless (PPP volumes
  exist) but book-level, not per-order.
- `inv-62/` — #62 preparation. Piece A, roster tier upgrades with a
  publisher quote binding the token AT the agency (FR API responses
  verbatim, sha256 in SHA256SUMS.txt, pieceA_tier_upgrades.csv): MMA@0917
  (IHS) — FR 07-2740, RIN 0917-AA02, 2007-06-04, "…section 506 of the
  Medicare Prescription Drug, Improvement, and Modernization Act of 2003
  (MMA)…" (6 rows, all `MMA, sec 506`; the briefed 8 counted a "Mammal"
  substring at prefix 1018); NDAA-17@0720 (DoD Health Affairs) — FR
  2019-02532 / 2017-20392, RIN 0720-AB70 itself, "…the National Defense
  Authorization Act for Fiscal Year 2017 (NDAA-17)" (25 rows); MIPPA@0938
  — FR E9-863 title (26 rows); NEPA@0412 (USAID, not CEQ — 0412 is AID per
  the REGINFO XML) — FR 2014-24828 (14 rows); ARRA@0412 — FR 2026-10817
  (14); UMTRCA@2060 — FR 2017-00573 (10); INA@1205 — no spelled-out
  quote found, stays candidate. Receipt today: candidate-index-match 169
  (the briefed 144 was stale). Piece B, apostrophe-years: 13 texts / 40
  rows, all listed (pieceB_apostrophe_years.csv): BBA'97 13 rows, BBRA'99
  9, BIPA'00 12 (incl. the one defect row `BIPA' 00`, 0938-AL19 200110,
  act_section='00' = the year), OBRA'87 3 (already resolved via the full
  name beside it), OBRA'93 2 (`act_key='obra'`, refused act_not_in_index —
  a year-keyed OBRA roster row would resolve it to Pub. L. 103-66),
  FY'97 1 (a fiscal-year marker, excluded). Every two-digit year is
  consistent with the roster's act year.
- `inv-universe/` — #55, a different numbering universe in the U.S.C. slot.
  (a) reg-shaped `NN USC N.NNN`: 155 rows / 36 texts / 31 RINs; the grammar
  truncates at the dot so `26 USC 1.104-1(c)` reads 26 U.S.C. §1 —
  structurally SILENT (77/155 verdict exists; 26 CFR 1's note names
  "26 U.S.C. 1(h)" for an unrelated regulation, the coincidental
  "present"); 19 rows witnessed exactly by the RIN's own structured
  CFR_LIST (cfr_section = part.section). Detector: no real U.S.C. identity
  contains a dot (checked against all 66,780 enumerated pairs). (b)
  reg-suffix `472-8`: 820-row pool, 275 real all-digit NNN-N sections are
  the trap; 190 rows / 19 texts / 10 RINs (all Treasury 1545-*) witnessed
  exactly by CFR_LIST (`26 CFR 1.472-8`, `20.2032-1`), 45 sibling rows —
  all already loud (absent) but nameless. (c) chapter-in-slot: 4,382 rows
  already typed usc_chapter excluded; 1,690 rows / 239 texts / 339 RINs
  bare-integer candidates (an appendix false-inclusion of 681 caught and
  removed); no chapter headings are pinned, so only recurrence + CFR_LIST
  subject match discriminates (`10 USC 55` ×200 with 32 CFR 199 TRICARE;
  `5 U.S.C. 89` with 5 CFR 890; `41 U.S.C. 85` ×46 with 41 CFR 51 —
  beliefs, marked); 1,244 (title, N) pairs are both a real chapter and a
  real section → `ambiguous`. (d) bare OSHA/CFR `NNNN.NNNN` with no title:
  250-row pool, 0 misread — the grammar's explicit-Code-name requirement is
  a complete fence. Witness ranking measured: structured CFR_LIST > note
  free text (2.4× on shape b; 20.2032-1 found only by CFR_LIST). Design: a
  typed usc_slot_reading column beside the untouched original with the
  referent and the witness named; the verdict column unchanged.
- `inv-2012/` — the oracle's own coverage hole, explained: the annual-archive
  extractor (research/evidence/usc-section-oracle-2026-08-22/scripts/
  extract_annual.py, `FNAME = r"(\d{4})/\1usc(\d+)…"`) is case-sensitive,
  and OLRC named twelve volumes with uppercase `USC` — 2010USC12/13/14/51,
  2012USC33/35/36/37/38/39/40/41 — so they were silently skipped; the
  publisher lists every one (2012 index: 2012USC33.htm 6,538 KB …
  2012USC41.htm 1,395 KB, dated 12/24/2013; 2010USC12.htm 16,193 KB …).
  Exactly 12 (title, year) holes exist in 1994–2024; titles 52/54 pre-2014
  and 34 pre-2017 and 6 pre-2002 are genuine (titles not yet created).
  Of the 8,258 usc rows "exists but not attested at the edition": 1,881
  (390 pairs, 538 RINs) flip to attested once the hole is filled — title
  12/2010 alone 1,367 — 30 more plausible, 36 cite editions past the
  2024 ceiling, 6,311 are genuine era mismatches. The three act-derived
  rows checked at the publisher are genuine: 42 U.S.C. 805 repealed 1975
  and reused 2021 (its own Prior Provisions note), 806 new in 2022, 20
  U.S.C. 10005 first printed 2014 (ARRA §14005 codification lag).
  Recommends unit A (case-insensitive matcher, re-extract all 31 years,
  re-pin) and unit B (reasons for structural non-attestation:
  title_not_yet_created, edition_beyond_archive_ceiling).
- `inv-47/` — the parenthesised lettered-suffix class where the stem is
  ABSENT (oracle miss-class "C3 paren-suffix-eaten"; c3_proposals exists
  with zero callers). Of 8,110 absent bare-stem rows: 209 rows / 3 pairs /
  48 texts / 36 RINs have exactly one enumerated fused reading
  ((15, 78) 158 — `15 USC 78(l)` → 78l etc., (42, 2000) 47 — `2000(d)` →
  2000d, (19, 81) 4); 10/10 seeded fused identities confirmed real and
  on-subject at uscode.house.gov, bare 15 U.S.C. 78 confirmed nonexistent
  there. Tails: 163 clean; 22 carry a genuine subsection pinpoint after
  the letter (`78(w)(a)`) that must ride along; 17 carry a hyphen tail
  that is not itself a section (`78(s)-37`); 7 (0790-AJ04 201610) carry
  a hyphen tail that IS a distinct real section — `42 U.S.C. 2000(d)-1`
  … `-7` — and today's c3_proposals precedence would publish bare 2000d
  for all seven: the 1735f-14 lesson must be applied before promotion.
  Refused with reasons: 1,186 rows with no fused witness; 1 true
  ambiguity (a row-collapse casualty); 15 rows of a NEW range-shaped
  defect — parens on both ends of the same stem (`15 USC 78(h) to
  78(i)`, `42 U.S.C. 2000(d) to 2000(d)-7`) never attempt a range at all
  (usc_section_end NULL) — distinct from inv-dropped's parenthesised
  endpoints; 0 cross-title collisions measured. ROW-COLLAPSE, a grammar
  defect: distinct parenthesised items on one stem merge into one row —
  79 lossy (title, stem) groups, 186 stated items → 79 rows, 107
  citations lost corpus-wide, 106 of them on EXISTING stems (`33 U.S.C.
  1321(b)(3), (c)(2), (d)(2), (j), (c)(1), (b)(4)` → one row; `(42, 405)`
  43 lost); the correction column cannot restore a vanished row. Proposed
  rule head `paren-eaten-lettered-suffix` (`paren` unused in the census).
- `inv-57/` — the hygiene items sized. (a) Control characters beyond the
  tracked 0x19: 11,912 C1 codepoints (cp1252-as-Latin-1 mojibake: ’ “ ” –
  — • ‘ …) across 31 of 60 editions, 200310–202004 — ABSTRACT 9,611,
  LEGAL_AUTHORITY 206 (198 boxes), CFR 0; the grammar's `_DASHES` already
  normalizes U+0096/U+0097 (its docstring names `PL 105\x96261`), and
  hand-repairing all 198 boxes changes 0 identities (`12 USC
  1735f<U+0096>14` reads 1735f-14 ok). A reader-level cp1252 repair is
  hygiene for the ABSTRACT exposure, not an identity fix. (b) HTML
  abstracts: 77,120 of 241,726 (31.9%) begin `<!DOCTYPE html>` — from
  edition 201410 (55.8% of that edition) to 99.0% by 202510, NOT "2020+";
  12 ABSTRACT elements are not CDATA-wrapped. (c) Mid-list `...`: 58 of
  6,876 (6,818 are the record's last box); every box after a mid-list
  ellipsis is a real citation; 3235-AH00 has 34 following, 3052-AB93 50.
  (d) none-off-form 130 rows / 69 RINs / 21 prefixes: 14 RINs never
  published, 30 published without CFR impact, 25 RINs / 41 rows are
  completed rules with CFR impact behind a bare "None" (EPA's 2080-AA11
  200510 is a Final Action at 70 FR 36325 amending 40 CFR 26 with
  "Not applicable" in the box). (e) OMB circulars already resolve as
  administrative_order (175 of 199 rows; admin_order_kind/number carried);
  R5 run_length-2 runs: 97, exactly 2 unabsorbed identical-shape followers
  (2506-AC44 201710 `12701-12711, 12741-12756`; 3090-AK80 202504 `541–559`).
- `inv-note-present/` — #38 cycle 2's caution sized: a `present` verdict
  produced by a damaged or coincidental note token. Note side (8,240
  notes, 30,515 U.S.C. identities): gated like the oracle's own rules
  (bare section ABSENT and no clean U.S.C.-labelled witness elsewhere in
  the note), 80 flagged identity-occasions in 62 notes — parenthesised
  suffix 54 (`78(f)`), spaced suffix 24 (`78 o`), lost hyphen 0, and a NEW
  mechanism, cross-family bleed 4 (the list-tail continuation swallowing a
  following citation's VOLUME: `19 U.S.T. 6223` → 8 U.S.C. 19, `1870
  U.N.T.S.`, `340 U.S. 462` → 50:340); 74 of the 80 are the Exchange Act
  §78 family across 20 CFR parts, an eCFR typesetting quirk (superscript
  suffixes). The Comp.-year phantom recurs as a repeated-year variant
  (`3 CFR 1987, 1987 Comp., p. 235`, 7 occurrences / 4 notes) that the
  in-progress #46 fence did not yet catch — sent to that unit. Artifact
  join: 223 rows / 54 texts / 20 parts / 53 RINs are `present` via a
  flagged token (12 CFR 19 44 rows, 46 CFR 381 30, 17 CFR 240 30, 17 CFR
  242 26); 144 of them carry the same damage in the filer's own text, 79
  are clean filer citations witnessed only by a damaged note token.
  Coincidental-stem class (present, verdict absent, a decoration dropped
  by the parse): 30 rows — 11 of them 1120-AB75's `28 U.S.C. 0.95 to
  0.99` (a mislabelled 28 CFR delegation) already drift to `absent` under
  the in-progress dotted-number fence; the rest are §78-family cases
  where both sides render the section the same broken way. Recommendation:
  a distinct value `present-by-stem` for a present verdict whose only
  supporting note citation is bare, oracle-absent and uncorroborated in
  the note (223 rows), never a silent demotion; the verbatim-token
  condition (143 of 223 would move) held as optional — two documents
  sharing a typo is closer to accident than corroboration.
