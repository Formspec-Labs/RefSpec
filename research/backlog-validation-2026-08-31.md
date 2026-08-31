# The backlog, validated against raw publisher bytes before any of it proceeds

2026-08-31, same day as the ledgers it audits. Rule of the exercise: for
every remaining backlog item, propose a concrete real-data scenario, open
the RAW source (pinned local bytes first, the publisher's live API when
absent), read the specimen whole, and only then say whether the problem
exists. Code was used only to open, extract, and print bytes. Every verdict
below names what was read. Three ledger claims died or changed shape under
this reading — which is the point of doing it.

## Wave-1 items (citation_grammar / identifier_shapes ceremony)

- **Case-sensitive annual extractor — CONFIRMED, count corrected upward.**
  Read the salvaged zips' member lists: 2010.zip holds `2010usc11.htm` then
  `2010USC12/13/14/51.htm`; 2012.zip holds eight uppercase members
  (33/35–41). Opened `2010USC12.htm`: a real 16.5 MB publisher volume —
  "TITLE 12—BANKS AND BANKING", full chapter table, §1841 present — that a
  lowercase-only match skips whole. **New find: `2024usc18A.htm` (capital
  A) — a thirteenth case-variant member the ledger's twelve missed**, so the
  2024 Federal Rules of Evidence appendix was also never extracted; the fix
  must recount, not adopt the ledger's number. (2013–2016 appendix members
  are lowercase, so the 2015 appendix-attestation cliff in the artifact is
  real history — Title 50's appendix dissolving — not a casing hole.)
- **`_CITED_DIVISION` case bug — CONFIRMED.** Raw XML:
  `<LEGAL_AUTHORITY>Div. D, title IV, sec. 416 of the Further Consolidated
  Appropriations Act 2020</LEGAL_AUTHORITY>`. Capitalized spellings dominate
  the sixty editions ~12:1 (324 "Division", 118 "Div.", 37 lowercase). The
  regex, read verbatim, has no IGNORECASE while its neighbour
  `_ACT_SECTION` does — an oversight, not doctrine. (Count nuance: 479
  occurrences here vs the review's "630 of 723 values" — different units;
  direction identical.)
- **`_STATED_SECTION` dead `§` arm — CONFIRMED.** The marker alternation
  sits behind a leading `\b`, and `\b` before the non-word `§` requires a
  word character immediately before it — so `PHS Act §§ 2791(b)(5)` and
  `Pub. L. No. 119-21, §70421(d)(1)` (both read verbatim from the pinned
  XML; 44 distinct §-bearing authority values) can never enter.
- **Title-41 hyphen-part phantom — CONFIRMED and RE-SCOPED 623×.** Filed as
  "latent, one prose case." The pinned Agenda XML is saturated with
  `41 CFR 101-6/-20/-8.3…`, and the shipped cfr-references artifact
  publishes **623 rows** of `title=41, part='101'` — a part that does not
  exist — each row's own `reference_text` (`41 CFR 101-41.304-2`) showing
  the truncation. Softener, also read: all 623 carry
  `cfr_part_in_current_ofr_index: False`, so a true warning label sits
  beside the wrong value. Belongs in wave 1, not the parking lot.
- **Dot-truncation — CONFIRMED.** Raw: `<LEGAL_AUTHORITY>26 USC
  1.104-1(c)</LEGAL_AUTHORITY>` (a Treasury *regulation* misfiled as USC).
  Shipped row (RIN 1545-BF81 @200610): `usc_section='1'`, verdict
  **exists**, attested — `parse_status='partial'` is present but does not
  stop the affirmative verdict on the wrong section.

## Sealed-lineage queue

- **B8 two-witness — CONFIRMED end to end.** Raw:
  `<LEGAL_AUTHORITY>7 USC 1736(o)</LEGAL_AUTHORITY>` (RIN 0551-AA38,
  Foreign Agricultural Service, @199510). The publisher's own 1995 title-7
  volume cross-references "the Food for Progress Act of 1985
  [7 U.S.C. 1736o]" — the letter-suffix section is the referent, and the
  filer is the Food for Progress agency. Shipped: `usc_section='1736'`,
  verdict exists, attested. Wrong section, affirmative verdict.
- **Stat-page fence — CONFIRMED, with two sharpenings.** The raw 12 CFR 611
  note reads `Pub. L. 100-233, 101 Stat. 1568, 1638` — **the mined note
  misquoted the page as 1608; it is 1638**, and 12 U.S.C. 1638 (Truth in
  Lending) EXISTS, so for this very specimen the proposed oracle-gate fix
  is insufficient: the fabricated citation lands on a real section. The
  trap's other jaw verified in 14 CFR 121's note, where the U.S.C. list
  genuinely resumes after `126 Stat. 89,` — a blanket drop-after-Stat fence
  would destroy real citations. The fix needs construction awareness.
- **Authority-note span swallow — CONFIRMED in one distribution.** The raw
  14 CFR 121 note states `44701-44702` in full; the shipped artifact judges
  49 U.S.C. 44702 `present` under every sibling part whose note names it
  plainly (25, 135, 13, 21, 36, 125, 23…) and `near-miss` ONLY under
  part 121 — the one note that states it inside the range.
- **act_resolution capital-suffix miss — CONFIRMED.** Raw Table III bulk
  XML: `<act-section>1818A</act-section>` → `42 USC 1395i-2a`. Raw agenda:
  `Sec 1818A(d)(2) of the Social Security Act`. Shipped: `act_section:
  '1818a'` (lower-cased), reason `act_section_not_classified` — a published
  NULL where the publisher holds the answer. 47 rows for 1818A alone.
- **Duplicate list rows — CONFIRMED.** One raw authority (`sec. 1, 4(i),
  4(j), 4(o), …`, RIN 3060-AK40) ships three byte-identical
  `act_section='4'` rows per edition at citation ordinals 1/2/3.
- **Appendix-past-2024 False — CONFIRMED, exactly 38 rows.** Specimen
  `50 U.S.C. app. 2061` @202504: verdict exists, attested **False** from
  zero evidence (structural, and accidentally right — Title 50's appendix
  was recodified). The full appendix census was read; the 2015 True-cliff
  is genuine history, not the bug.
- **Receipt counters — CONFIRMED in one grep.** The committed receipt claims
  `record/@print-in-supplement: 317,590` (one per record; every counter
  equals its element count) while the raw bulk XML holds **81,722**
  occurrences of the attribute string in total across all elements.
- **Source-credits bounded page (283z-11) — CONFIRMED against USLM bytes.**
  The publisher's credit, verbatim: `(Pub. L. 86–147, § 39, as added
  Pub. L. 109–289, div. B, title II, § 20410, as added Pub. L. 110–5, § 2,
  Feb. 15, 2007, 121 Stat. 25.)` — date and page belong to 110–5; the
  frozen artifact welds them onto 109–289.
- **185-vs-169 roster split — NOT CONFIRMED; reviewer misread.** The
  receipt's own key names say so: 185 is the refusal reason
  `the-candidate-tier-is-unfenced-here`; 169 is the noted-status
  `candidate-index-match`. Two different populations. Item dies.
- **EO oracle — CONFIRMED.** The committed NARA capture for EO 8284 is
  literally a "Page Not Found | National Archives" page; three shipped rows
  publish `executive_order: '8284'`, `parse_status: ok`,
  `eo_in_known_series: True`.
- **Degenerate range endpoints — CONFIRMED.** `16 USC 773 to 773(k)` ships
  `usc_section_end=None` (span vanished) while its honestly-spelled sibling
  `773 to 773k` ships `usc_section_end='773k'`.
- **Present-by-stem — CONFIRMED.** Specimen read whole: `46 app USC
  1241(b)` → identity `46:1241`, oracle **absent**, sole witness the
  damaged paren token, shipped judge **present**. 223 matched rows.
- **FR page fence — CONFIRMED by specimen.** `78 FR 764444` (fused digits)
  ships in the timetable with no fence column in the schema. Counting note:
  a crude `>90,000` cut over-collects (recent volumes genuinely exceed
  100k pages); the ledger's per-volume last-page measure is the right one.
- **BIPA '00 — CONFIRMED.** Two rows publish `act_section='00'` from
  `BIPA' 00`.
- **Falsified prose notes — three of four CONFIRMED, one inconclusive.**
  Mojibake: raw bytes show `WT Docket No. 12\xc2\x96357` (cp1252 en-dash
  inside the publisher's XML; 110 C1 bytes in one edition) — "not
  systematic mojibake" is false. The oracle docstring's "every year
  1994–2024" is falsified by the uppercase volumes above. The
  citation_grammar "no other Agenda field" claim was measured by the
  original review (accepted). **MIPPA roster 29-vs-26: INCONCLUSIVE** —
  roster says 29, the note says 26, a naive authority-text count says 37;
  three numbers, three population definitions; re-derive the original
  filter before believing any of them.

## Wiring, ops, and premise checks

- **Explorer redeploy — CONFIRMED by provenance.** Every committed
  pre-wave version of `data-layer.js` carries the unquoted `offset`
  (read at `99167ca1`, line 317), so whatever is deployed is broken. The
  live asset itself could not be fetched (worker subdomain unknown) —
  verify on deploy.
- **README derived-relations checklist — CONFIRMED stale**; it still
  phrases the landed toggle work as future and lacks the inspector
  `relations=` line.
- **language-scope-exclusions regeneration — CONFIRMED** via the fidelity
  resolver's real-audit run (−6,395 = exactly the non-English organization
  labels) plus a structural read of the declaration file.
- **FR-cite prose family — DEMAND CONFIRMED**: 1,936 raw authority values
  are literal FR citations (`15 FR 3174`…); the grammar has no family for
  them (header read; none found).
- **REF-049 conformance debt — CONFIRMED OPEN**: `_DERIVED_RULE_ADMISSIONS`
  is still referenced by three modules.
- **rulespec backup — MY OWN EARLIER CLAIM CORRECTED**: the repo HAS an
  origin (`Formspec-Labs/rulespec`); only the branch lacked tracking. The
  rc16 commits are one ordinary push away, not stranded.
- Validated earlier the same session, recorded in
  [`fr-body-signal-inventory-2026-08-31.md`](fr-body-signal-inventory-2026-08-31.md):
  the REF-052 column families (raw documents read per family), the refused
  census (publisher's own spellings throughout), the 228 collision pairs
  (three read in their entirety — two distinct regulatory actions each),
  and the corrects/amends edge demand (the correction documents state their
  targets in the first line).

## What this changes about the plan

1. The title-41 phantom moves from the parking lot into **wave 1** (623
   shipped rows, not one latent case).
2. The IGNORECASE re-extraction must **recount the miss set** (≥13 members,
   not 12) and re-derive the 1,912 downstream number.
3. The Stat-page fix must be **construction-aware**, not oracle-gated — the
   specimen's fabricated section exists in the Code.
4. The 185/169 item is **dead**; the MIPPA 29/26 item is **suspended**
   pending the original population definition.
5. Every other queued item proceeds with its premise verified against the
   publisher's own bytes.
