# What the ledger investigation's claims measured out to

**Date:** 2026-08-22. Each claim below came from a ledger-row agent and was
re-measured here before anything was acted on.

## The anachronistic Public Law: latent, not live

The report gave RIN 2030-AA91 (EPA, Fall 2006, sole authority `PL 101`)
resolving to Pub. L. 113-101, a 2014 law, because a different EPA rule in the
2025 edition cites it — the agency-roster fence borrowing across time.

**Measured: that row is `failed` today, and no corroboration rule anywhere in
the artifact produces an anachronistic Public Law.**

    anachronistic public laws                    61
      produced by our corroboration rules         0
      read as the agency wrote them              61
      of those, already flagged out-of-series    58

So the defect is real but **latent**: it is what the citation-history fence
would do if it ever answered one of these rows, not something it does now.
The `PL 105-58, 30 November 1995` in a 1996 edition is the agency's own
error, faithfully recorded and flagged — which is the behavior we want.

The fix is still worth making, because a fence that would invent when it
fires is a loaded gun: `_pl_roster()` already loads approval dates and
`_CitationHistory` does not consult them. Named here so it is fixed
deliberately rather than discovered later by its output.

## The "unstated" bucket is three different facts

Primary sources: RISC "Instructions for Reporting Regulatory Actions in the
Unified Agenda" (RID form instructions, Fall 2025 and Fall 2008 via Wayback),
EO 12866 §4(b), and the RISC preamble.

    12,463 rows typed "unstated", 11 distinct spellings
       6,873   "..."                  the agency ticked "there are more citations"
       5,461   "Not Yet Determined"   a checkbox the form offers
         127   "None" / "N/A"         off-form free text

These are not one thing:

- **`...` is a completeness signal, not a placeholder.** The RID instructions
  say: "If you choose to list only some of the applicable citations, you may
  check the box that indicates there are more citations. In this case, the
  printed Agenda will contain an ellipsis (...) at the end of the list."
  Verified three ways: the eAgenda HTML shows the same list as the XML plus
  the ellipsis (3 of 3 RINs, so it is stored content and not display
  truncation); the Federal Register print edition renders it as a trailing
  ". . ." (HHS agenda, FR doc 2025-18328); and it appears on lists of length
  2 through 58, so it is not a display cap. **A consumer joining on legal
  authorities today believes it has the whole list for 6,873 rules whose
  agencies said otherwise.**
- **"Not Yet Determined" is a controlled value**, not free text: 163
  occurrences in edition 202510 with zero casing variants, which typing does
  not produce. Title-case from 199810 onward; lowercase before.
- **"None" in a legal-authority field is off-form.** The RID form offers a
  "None" box for CFR Citation and for Relevant Executive Order — and **not**
  for Legal Authority, which gets only "Not Yet Determined" and "additional
  citations". EO 12866 §4(b) requires "the legal authority for the action"
  for every entry. 47 of the 129 sit at Proposed or Final Rule stage; NHTSA
  RIN 2127-AL99 carries `None` beside 49 CFR 571 and a published ANPRM at
  83 FR 50872. That is a publisher defect, and typing it as a placeholder
  hides it.

## The elements are one sentence cut at commas

The parser reads one `<LEGAL_AUTHORITY>` element at a time, so it cannot see
that ordinal 4 is the tail of ordinal 3. Six of ten sampled unreadable rows
are fragments of a single authority string, and in four the eCFR authority
note for the record's own CFR part reconstructs the string verbatim.

Measured: 1,088 of 1,806 have an earlier element in the same list stating a
U.S.C. title. Naive "inherit the nearest preceding title" is **84.2%** over
442,298 pairs — not good enough, and the counter-example is instructive: HUD
2501-AD75 states the correct title *after* the fragment. A fenced version
(candidates from every label anywhere in the list, each section token
required to exist under exactly one) yields 347 one-survivor answers from
494 candidates, with 7 picking a non-preceding label — so the fence does
real work. 347 is an upper bound: the roster it used is corpus-internal and
carries agency errors.

## The unsurveyed problem

This ledger counts loud refusals. The same investigation found `4 Stat. 1064`
accepted where the truth is 48 Stat. 1064 — a silent wrong read, which no
count here would ever surface. **Silent misreads are unmeasured and are
probably the larger population.** Naming it so the next campaign starts there.

## Two operational findings

- `REGINFO_RIN_DATA_200404.xml` is not well-formed XML (fails at line 148983,
  column 318). Worth knowing which editions a strict parser rejects and
  whether the reader silently recovers.
- Spring 2012 was never published; reginfo serves that year as
  `REGINFO_RIN_DATA_2012.xml`, breaking the `{YYYYMM}` naming pattern that
  every other edition follows. An edition-identity trap for anyone
  re-acquiring the corpus.

## The two malformed editions are repaired loudly, not silently

A ledger investigation found `REGINFO_RIN_DATA_200404.xml` is not
well-formed XML and asked whether the reader silently recovers. Measured:
strict ElementTree rejects **two** editions, 200404 and 200410, both on the
same byte — `\x19` where a right single quote belongs (`Department\x19s`,
`bureau\x19s`), a control character the 2004 export wrote for an apostrophe.

The reader's recovery is declared, fenced, and pinned (`unified_agenda_editions.py`,
`parse_unified_agenda_edition`): the digest is taken over the raw bytes as
served, so the capture re-verifies against the endpoint; the byte is replaced
in memory with U+2019 before parsing; and a roster,
`UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS`, must match presence exactly —
the reader fails closed if the repair fires on an edition not in the roster
or fails to fire on one that is. All 60 editions parse; none is recovered by
a lenient parser. This is the shape every repair here should take.

## Rebuild #3 (23:43, receipt sha256:7ce79c36…) attributed value by value

A faithful build of the rebuild-2 state (grammar at a6f72afd, builder at
cc9c5cbd, both oracles reachable) reproduces its 797,170 rows exactly. Diffed
against rebuild #3 on values per list entry, ordinals ignored:

| moved | rows | cause |
|---|---:|---|
| statute_at_large partial → partial/ok (33 now ok) | 194 | lettered page ranges carry both ends (5e35bc53) |
| case_citation ok ×6 + other failed ×3 → usc ok ×9 | 9 | a lost C, settled by each rule's own eCFR authority note (2fc3fc7b) |
| cfr partial → cfr partial, part refused by name | 1 | "40 CFR parts 1500-1508": a dash behind a plural label is a range (f272d2a8) |
| administrative_order partial, new | +28 | an order list is a list (e6514fa7) |

Net +28 (797,170 → 797,198). Nothing vanished that was real; nothing arrived
unexplained. The first scratch builds of the day ran without the Public Law
roster and produced a quietly different artifact — the builder now refuses
to build without its oracles (cc9c5cbd), and every receipt names the code
that wrote it (fc0d052e).

## A receipt resolves to a commit in both directions (2026-08-23 00:40)

Rebuild #3's receipt (sha256:7ce79c36…, pinned by spicysearch) was
reproduced byte for byte by a faithful scratch build of commit 738c8224 —
the tree that carried the producer block — with the same editions and both
oracles reachable. The producer block names the code; the code, rebuilt,
names the receipt. Any receipt written from here on can be matched to its
commit by hashing blobs, and checked by rebuilding it.

## Rebuild #4 (2026-08-23 01:2x, receipt sha256:687acc4f…) attributed value by value

Against the faithful build of 738c8224 (= rebuild #3, byte for byte), on
shared columns, ordinals ignored: 1,349 values vanished and 1,344 arrived,
every one a grammar-wave-6 class — the zero pad stripped from the identity
("26 USC 0892" → 892; 963 rows), expanded spans typed partial never ok (264
rows, 66 spans), "27 USC 1087" retyped treaty (33 rows) with its five
duplicate instrument-name rows gone (the whole −5), "6002Omnibus" → 6002
(19 rows), a compilation year out of cfr into eo_compilation (10 rows),
"Sec 123BBRA 1999" → section 123. New columns: cfr_section, the section
fence (usc_section_verdict / reason / attested_at_edition / corrected /
evidence), the three carried verdicts, usc_section_span_rule. The receipt
census over every usc row closes exactly (668,575 exist / 14,142 absent /
2,551 unknown / 886 unstated / 134 title-impossible = 686,288).

## Consumer-side verification of rebuilds #3 and #4 (spicysearch, 2026-08-23)

spicysearch re-ran its Federal Register pass unchanged against rebuild #3 and
again against rebuild #4 into scratch: the tag-set parquet is byte-identical
to the shipped one (ab702088…) both times, and the cfr_references and
timetables parquets it reads are byte-identical to their pins — the pass now
digests cfr_references too, after rebuild #3's ten-citation drift reached a
receipt count through a file it had never pinned. Only the agenda receipt
digest moved in its receipt (re-pinned to 687acc4f…).

Its U.S.C. bridge is where rebuild #4 lands: 10,819 keys (rebuild #2) →
10,959 as parsed → 10,970 reading `usc_section_corrected` where present;
5,255 rows carry a correction, 3,656 of them with verdict `absent` — the
silent-misread class, reproduced by independent code. Its reading is
corrected-then-base-section, because its document grammar yields section 553
for "5 U.S.C. 553(e)", so a corrected key "553(e)" matches nothing: the
corrected column's shape (identity vs pinpoint) is an open design decision,
to be settled by their per-document exposure figures.

## Exposure figures decide the corrected-key shape (spicysearch, 2026-08-23)

Measured per document on the presidential (8,523 bodies) and court (45,214
opinions with citations) passes against rebuild #4, both readings, receipt
vendored on their side as usc-bridge-rebuild-4-exposure-2026-08-23.json:

- Corrected-then-base-section reading: 91 keys depart, 37 arrive. By our
  verdict column the departures are 68 absent + 2 unknown (the A4 class:
  371a, 553e, 303b…) and 21 exists (the B8/B1 pinpoint class). All 70
  not-affirmed departures have zero document exposure in either corpus —
  the misread class has no instances a document cites. All four cited
  departing keys are in the exists class: 15 U.S.C. 18 (27 opinions + 1
  body), 12 U.S.C. 1715 (5), 47 U.S.C. 399 (3), 25 U.S.C. 161 (1) — opinions
  printing "15 U.S.C. § 18", correct citations to real sections, lose every
  tag because their companion citations bridge to nothing. Net court −20 /
  +7 documents, presidential +2 / −0; a second channel moves RIN
  denominators of 21 surviving keys (12 U.S.C. 1735 loses 24 CFR 25).
- Narrower reading (correct only where verdict is absent): 10,643 keys,
  −68 / +4, zero cited removals — near-inert.
- **The as-parsed reading stays their default.** The split queued as task
  #24 — section identity as the key, pinpoint as data — is the reading that
  loses nothing here, and is what the next rebuild cycle implements: B8's
  proposal stays a named candidate column, never the identity.

Consumer critique of B8 worth keeping: "15 USC 18(a)" → 18a rests on §18
having no lettered subsection (a); from a consumer's seat §18 and §18a both
exist, so this is a choice between a pinpoint and a neighbour by existence
alone — high precision on the 1395 family the survey validated, not a
proof in general. Rebuild #2 → #4 as-parsed diff fully attributed on their
side: −120 / +8 (span expansion −66, zero pad −48, hyphenated re-read −5;
the 27 U.S.T. 1087 retype removed a confidently wrong key); exposure of
removed keys 0 documents, added keys 8 (all 19 U.S.C. 2411). Their shipped
presidential and court artifacts had been built on the pre-rebuild-1
capture (receipt f60703ae…, unattributable by construction) with no bridge
digest; they are being refreshed on rebuild #4.

## Rebuild #5 (2026-08-23 02:4x, receipt sha256:c206bc1a…) — nothing moved, two columns arrived

The rebuild-4 state (commit a7217bdb) reproduced its pinned receipt
687acc4f… byte for byte before this rebuild, the second such reproduction.
Against that build, on every shared column, rebuild #5 changed **zero
values** (797,193 rows both sides): the oracle's per-title span index
(329d7a87; 8.8 s → 0.26 s over 95,492 keys) is proven identical in the
artifact, not only in its test. Additive only: `usc_section_corrected_section`
(the identity a correction names) and `usc_section_corrected_pinpoint`
(the Code's pinpoint, else NULL) on the 5,255 corrected rows — 3,659
pinpoints, all A4 — with identity + pinpoint re-spelling
`usc_section_corrected` exactly (0 mismatches) and a receipt census,
`uscSectionCorrectedIdentityMovedRowsByRule`, equal to the correction
census by construction today. The consumer's four cited keys all move
under B8 (15 U.S.C. 18 → 18a, 19/19 rows; 1715 → 1715b/g/y; 399 → 399b;
161 → 161a), which is why the identity, not the proposal, is the key.
Producer block covers the lint pass's edits to identifier_shapes and
unified_agenda_editions. Builder suite 64/64; 997 sibling tests green.

Consumer-side (spicysearch, 2026-08-23 02:5x): rebuild #5 verified by
re-running, not by the attribution — the Federal Register pass gives the
same tag set byte for byte (ab702088…) with cfr_references and timetables
byte-identical to their pins; the bridge key digest under the shipped
as-parsed reading is unchanged (c87fdc6a…); the presidential and court
passes land on the tag-set digests they produced on rebuild #4 (67eceaef…,
89772f4a…; 915 and 16,106 documents). All three receipts pin c206bc1a…. When
their bridge moves to keying on `usc_section_corrected_section`, it will
be measured the way the corrected reading was, with the four cited keys as
identities that must survive.

## Rebuild #6 (2026-08-23 ~08:0x, receipt sha256:b98feed1…) — two units, 9,777 values, every one attributed

Against the faithful build of 4e772267 (= rebuild #5, c206bc1a… byte for
byte), ordinals ignored: 9,777 values vanished and 9,777 arrived, all of
them one of two units. (1) Act resolution baked in (9ac5837d, 339e3bd3,
d19df1bd): of 6,214 act-relative "failed" rows, 3,489 resolve — 5,607
rows / 356 pairs carry a section with `act_resolution_evidence`
(table3-classification 5,594, source-credit 13); the rest carry a named
reason (no_section_stated 1,635; act_section_not_classified 900; …); three
sibling carries (one Clean Water Act list across nine boxes) and four
year-less names; four Food Stamp Act rows refused by the anachronism guard
because OLRC renamed the act — invalid state revealed, queued (#39). (2) B8
withdrawn as a correction (ebcd8b1c, 53294b04, 76f851a1): the generator had
truncated hyphenated lettered sections ("1735(f)-14" → 1735f, a wrong real
section); 1,441 corrections become candidates named in the receipt; A4 and
B1 byte-identical. The agents' own scratch diffs matched the artifact's.
Builder suite 72/72 after the pins — in two passes: a4b7d801 was committed with six B8 pins still red, corrected in the next commit; 997 sibling tests green. Consumer-side (spicysearch): rebuild #6 verified by re-running — the Federal Register, presidential and court passes produce parquets byte-identical to the shipped ones; the bridge key digest under the as-parsed reading unchanged (c87fdc6a…); all three receipts pin b98feed1…. Their bridge admits filed U.S.C. rows only; resolved act-relative identities will be an explicit second reading, measured per document before adoption.

## The one non-reproduction, and what it was (2026-08-23 ~08:4x)

A faithful build of d19df1bd (= rebuild #6) first produced receipt
9b039b95… instead of b98feed1…, with 3,608 act-relative rows resolved
instead of 5,594 and `source_incomplete 3`. Not the artifact: the faithful
build script still passed `--act-index output/usc-act-index-2026-08-02`,
harmless while the builder read only act names from the index, decisive
once the bake-in (9ac5837d) resolved through it. The script now builds each
commit with its own default index (tools/faithful_agenda_build.sh), and the
rebuilt baseline reproduces b98feed1… byte for byte. The receipt's own
counts are what named the cause.

## A rule refused before it was written (2026-08-23 09:1x)

Review H predicted a false-presence population beside the absences and
review E proposed "list-coherence title repair" to catch it. Measured first
(research/evidence/false-presences-2026-08-23.md, d6158619): run coherence
as defined scores 0/7 on a seeded hand sample — dominated by numerical
coincidence (RIN 3060-AG34 alone supplies 246 of 691 rows through a
spurious title-23 match) — and two of the review's own specimens are
legitimately mixed-title lists that never qualify as runs. It is struck
from #34; a title repair needs a second witness. What held: "attested after
the citing edition" 6/6 (526 rows once 2,929 pre-1994 disposition stubs are
guarded out), and the cached-note shadow 80% precise only where the oracle
corroborates it (0% where it does not); two cached notes misprint their own
title digits. Both go to the CFR-note oracle's second cycle (#38).

## The 1994 Title 49 disposition table, pinned (2026-08-23 09:3x; 4ec1c931, cac29777)

The volume (5,165,242 bytes, sha256 66f00467…) is committed with a
geometric extractor (`pdftotext -bbox-layout`, because the table prints two
blocks per page and justified continuation lines defeat any line rule):
1,852 printed entries, 3,102 (former section × successor) rows, 909 former
sections; all 419 `49 App.:NNNN` references in the volume's own revision
notes are in the table. A first extractor took the topmost column block
per header and silently lost 464 sections; the guard that now raises on an
orphaned value caught it. Over the pinned snapshot: of the 2,548 rows
unknown for `title_49_appendix_not_published`, 2,371 (93.1%) are answered —
2,237 exists-as-recodified, 134 repealed-no-successor — and 177 are damage
in the citation, not a gap in the table (14 CFR ch. III part numbers in the
U.S.C. slot, 116 rows; two descending ranges; a Statutes page). On 62 of
146 sections the table names several successors separated only by printed
prose ("1432(a) (related to standards)" → 44701 vs "(related to issuing
certificates)" → 44702): candidates, all of them, never an identity — the
B8 lesson applied before the column exists.

## Rebuild #7 (2026-08-23 09:46, receipt sha256:17e61179…) — nothing moved, five columns arrived

Built at c99177b8 from the disposition cycle (d447f503, d478d436,
b376cc0b) on top of the CFR-note cycle (88c2bd43, 2cc574f8, ebf5ac52,
6fd787d1, 6fa941de). Value diff against the faithful build of d19df1bd
(rebuild #6, reproduced byte for byte): rows 797,193 → 797,193; VANISHED
0; ARRIVED 0 on every pre-existing column; columns only in the new table:
`authority_in_own_cfr_note`, `cfr_note_part`, `usc_disposition_verdict`,
`usc_disposition_successors`, `usc_disposition_table`. Actions, CFR
references and timetables are byte-identical to rebuild #6 (040e5445…,
fdba1bd8…, efd04084…); only the legal-authority table differs. Verify
PASS; builder tests 78/78 — the seven pins stated on scratch builds before
the rebuild (three disposition, three CFR-note, the producer block) hold on
the shared artifact unchanged; grammar/identifier/act 997/997. The
producer block names eight modules (`cfr_authority_notes`
sha256:d1da8788…, `usc_disposition_tables` sha256:059608a9…).

What arrived. CFR-note verdicts over 488,435 rows (121,731 rules, 22,788
RINs; 287 parts held, 287 named by a rule): present 326,019 / near-miss
47,285 / absent 85,988 — usc 319,973 / 47,112 / 66,411; public_law 3,428 /
72 / 14,906; cfr 2,255 / 101 / 900; act_relative 363 / 0 / 3,771; the
12,301 executive-order rows and the other non-statutory types unjudged by
design. Disposition over the 2,548 rows the oracle leaves unknown for
`title_49_appendix_not_published`: exists-as-recodified 2,237 (115
pairs), repealed-no-successor 134 (19), not-in-table 177 (27); 1,779 rows
carry more than one successor (49 U.S.C. 1655 the widest, 101) — a list
column of candidates, never an identity, and the contract now says so
(`aSuccessorIsEvidenceAndNeverAnIdentity`,
`theRulesOwnCfrPartNoteIsAWitness`). Hold-outs (seed 20260823) were listed
with the filer's text in the cycle reports before the rebuild: CFR-note
absent 0/10 misreads (blanket notes, "et seq.", multi-part rules),
near-miss 2 true misreads and the silent `40 U.S.C. 5103` now visible;
disposition 10/10 read right — `49 USC 486(c)` and `ch 451` as repeals
without successor, `49 USC 1472` with a successor in title 28.

Gates after the rebuild: `make audit-registry-real-data` regenerated the
snapshot (95 modules, e3eda78c) and its own pytest pass over the registry
is 2,555 passed / 2 skipped (23 min); `make check-generated` green. The
separate full-suite run was stopped at 10% to free the builder for the
next unit, whose cycle runs it — so the post-rebuild test evidence is the
audit's pass plus the chain's builder (78) and grammar/identifier/act
(997) runs, not a fresh full-suite line. The gate's list gained two lines
for `usc_disposition_tables.py` — "current execution did not consume
pinned real-data inputs [sha256:66f00467…]" and "not tied to a source
digest and location" — new with b376cc0b's registration (the module's
tests read the derived parquet, never the pinned volume through the audit
plugin): a lockstep defect, its own unit, not the artifact's.

Consumer-side verification of rebuild #7 (spicysearch, 2026-08-23): receipt
17e61179… on disk; cfr_references and timetables byte-identical to their
pins; the Federal Register, presidential and court passes re-run into
scratch produce parquets byte-identical to the shipped ones; bridge key
digest unchanged (c87fdc6a…); the postings index rebuilt byte-identical;
all four consumer receipts re-pinned to 17e61179…. Their verification is
now one command (spicysearch `scripts/verify_agenda_rebuild.py`) that
refuses to re-pin if anything but the agenda digest moved — a "nothing you
read changed" claim is checked there in about two minutes rather than
trusted. The two new columns are noted with their contract clauses (the
near-miss a witness, the successors candidates never keyed); the coming
ADDITIONAL_INFO rows would be admitted only as a named partial reading.

## Eight damaged FR citations name the document they meant (2026-08-23; 3757c465, cae91506)

The timetable table's only eight `failed` FR citations are five strings
damaged by one character each — `81 NFR 66900`, `85 FSR 62651`, `85 DR
34525`, `85 FR 75770x` (three editions), `89 FR 1022091` (two) — and
each now carries `fr_corrected_document_number/volume/page` and a named
operator beside its untouched text, corroborated against a pinned roster
of the five documents' own federalregister.gov metadata
(research/evidence/unified-agenda-fr-document-roster-2026-08-23, receipts
with digests, no network at build time): the repaired reading must equal
a roster document's start page AND the row's date its publication date
AND, where the document lists RINs, the row's RIN (the two FCC documents
list none — all 27 documents under either FCC RIN list none — so their
witness is date + agency prefix + shared docket, and the evidence string
says so). `1022091` has two single-edit readings in volume 89; 102209
lands inside 2024-29633, an SEC notice with no RIN, which sits in the
roster as a live row so the rule refuses it rather than never seeing it —
`page-digit-dropped` is a declared operator counted at 0. Scratch diff
against the rebuild-7 baseline: timetables 8 vanished (`failed`) / 8
arrived (`corroborated`), every other table byte-identical;
`timetableFrCitationFailures` 8 → 0. The same investigation found the
register's page bound stale (volume 89 ends at 107,261, the constant says
100,000) and the timetable table without any series verdict — task #42,
with a publisher-sourced last page now in hand for every volume 1–90.

## Two grammar truths and the lists that outran their boxes (2026-08-23; c31ae76d, f9d20973, 94ddfb03)

A RIN-shaped token (`3235-AE17`) is never a listed section: measured
over all 42,642 distinct authority values, no existing row's section
came from one, and the only hit is the trailing sentence of 3235-AH12's
199804 continuation, which had minted `15 U.S.C. 3235`. The sibling
shape — a Federal Register document number, `\d{2,4}-\d{3,6}` — was
measured and refused as a fence: 1,536 rows over 455 keys are real
U.S.C. ranges read by the standard form (`50 U.S.C. 4801-4852`); the two
letters are what make the RIN shape unambiguous.

A space before a lettered suffix (`15 USC 78 o-10`) is a named damage
operator, published from the oracle's correction columns with two
witnesses — the stem absent at the citing edition and the fused token
enumerated exactly — and the stated tail riding along (78o also exists;
dropping the tail is the B8 failure). Over the whole table 83 keys / 230
rows write a spaced suffix; three keys / four rows survive, all in the
15 U.S.C. 78 family (78j-1, 78k-1, 78o-10 ×2), 80 keys refuse. The
brief's premise was wrong and the oracle said so: 15 U.S.C. 77 is a
current section, attested in all 31 archive years, so `15 USC 77 eee`
stays refused with both halves of its reason rather than repaired.

The 98 records whose <ADDITIONAL_INFO> continues the legal-authority
field — 67 "LEGAL AUTHORITY CONT" (thirteen spellings) and 31 "Additional
Legal Authority" — yield 1,325 new rows (1,321 partial, 4 failed: a
prose delegation and two lists the raw XML cuts mid-sentence), read as
one string each (1115-AE47's list is 41 rows whole, 7 split), on ordinals
continuing the record's boxes, with `authority_source` naming the field
and `restates_box_citation` marking the 91 rows a box already carries
(1210-AA63's 200110 and 200204 restate every one). Seven records with a
bare "Legal Authority:" label and 2125-AD78's "Additional authority DOT
Order 5660.1A" (eleven editions) are excluded by name in the module. The
new rows' 49 absences are each classified: ERISA §§701-703 cited as
29 U.S.C. 1171-1173 (1181-1183 is right; twenty rows, the filer's), an EO
compilation locator's year and page read as sections (twenty rows, a
list-tail defect found nowhere in the box table — #46), `8 USC 9701` for
31 U.S.C. 9701 (three, the filer's later editions correct it — #36e),
three pre-1994 repeals the oracle does not stub, and one parenthesised
suffix collapse (`15 USC 78(d)` — #47).

## Rebuild #8 (2026-08-23 12:25, receipt sha256:84eb7203…) — four units, 1,337 values, every one attributed

Built at 94ddfb03: cae91506 (eight FR corrections), c31ae76d (RIN fence),
f9d20973 (spaced suffix), 94ddfb03 (continuation rows). Value diff against
the faithful rebuild-7 build: legal authorities 797,193 → 798,518 rows,
VANISHED 4 / ARRIVED 1,329 — the four vanished values are the spaced-suffix
rows re-read with their correction columns filled (`15 USC 78 j-1` →
78j-1, `78 k-1` → 78k-1, `78 o-10` → 78o-10 twice; section, verdict and
every other column unchanged) and the remaining 1,325 arrivals are the new
continuation rows by type: usc 1,147, public_law 49, federal_register 34,
administrative_order 26, cfr 25, statute_at_large 20, eo_compilation 13,
executive_order 7, failed 4. Timetables: VANISHED 8 (`failed`) / ARRIVED 8
(`corroborated`, five operators) and four new columns. Actions and CFR
references byte-identical. Verify PASS; grammar/identifier/act 998/998;
the builder tests red only on the pins these units moved (row total,
+26 orders, +4 failed, the refusal map, the corrected-rule list, the oracle
file set), re-pinned with each delta attributed to its unit by a subset
query in the test's own comment.

Consumer-side verification of rebuild #8 (spicysearch, 2026-08-23): the
verifier refused to re-pin on the changed timetables file, as designed;
scratch re-runs showed the eight corroborated FR citations reach no tag
(their pass joins on fr_volume/fr_page, which stay NULL on those rows), so
all three tag-set parquets came back byte-identical and the receipts were
re-pinned to 84eb7203… with the new timetables digest recorded. The
continuation rows found a gap on their side: the bridge admitted
parse_status 'partial', so 1,147 of the 1,325 new rows (21 RINs, every one
with witnessed parts) entered the key set before anyone chose a reading —
keys_digest moved from c87fdc6a… to 6a7bb8f0…. Fixed there: the default
reading admits filed rows only (authority_source absent or 'box'; a capture
without the column reads as filed, and that reading's digest preimage is
unchanged, so c87fdc6a… still means what it meant), and the continuation
rows are a second named reading, filed-plus-additional-info (on rebuild #8:
+8 keys, 90 shared keys' part rates moved; ce756a87…), shipped nowhere
until its exposure is measured. The four re-read rows change nothing under
as-parsed, since usc_section stays '78'. Lesson for the producer's notice:
a column that partitions rows must be named as the consumer's admission
filter, not only described.

## The DuckDB pin, relaxed for the consumer (2026-08-23; f06399ff)

spicysearch's served catalog snapshot was built under DuckDB 1.5.5, and
RefSpec's exact `duckdb==1.5.0` — inherited through their editable path
dependency — made their lock unsatisfiable. Checked before relaxing:
DuckDB writes no pinned artifact in RefSpec (it reads parquet in the Atlas
view, the explorer and four test modules; no COPY or EXPORT anywhere), so
no digest depends on its version. The requirement is now
`duckdb>=1.5.0,<2` with RefSpec's own lock still resolved at 1.5.0; in a
separate worktree with its own environment upgraded to 1.5.5 the full
suite ran 4,144 passed / 117 skipped / 1 failed, the one red being the
audit snapshot's known cadence (summary.json trails sources.json until the
post-rebuild chore) — the same state as on 1.5.0. A first run there showed
24 reds, all of them the rebuild-8 pins that 789f60a7 moved (the worktree
predated it); with that commit cherry-picked, 23 of the 24 passed on 1.5.5
and the 24th was the cadence red. Putting the commit on main is the
user's call; a submodule can pin this commit on the working branch.

Consumer side (spicysearch, 2026-08-23): rather than repoint their
submodule to this working branch, they carry the same one-line pyproject
change as a commit on their existing base (ae4dd650 on 3db57e5d), so
nothing else they import moved; they will repoint and drop the local
commit when the relaxation reaches a branch they track. Their lock
re-resolved duckdb 1.5.0 → 1.5.5 with refspec otherwise unchanged, and
`spicysearch metadata verify` on the served v11 snapshot returns verified
from their checkout for the first time since their lock regressed. Two of
their tests that had pinned logical snapshot ids measured under 1.5.0 were
made honest: a snapshot's logical identity (and the manifest/behaviour
digests naming its runtime selection) covers the engine the installed
provider reports and moves with it by construction; artifact digests do
not — the same property checked here before relaxing.

## Rebuild #9 (2026-08-23 16:26, receipt sha256:e88d9dca…) — four units, 1,850 values, every one attributed

Built at 07c97a17: d7d96b95 (H4 — a scheme label one edit from its
spelling), 6e9a15ae (H1 — the boxes the publisher cut, joined on a column
set, nothing rewritten), 9cab6f65 (H2 — a section-only box takes the title
beside it), 66d96462 (H3 — a row naming an act is act_relative even where
nothing resolves). Value diff against the faithful rebuild-8 build: rows
798,518 → 799,126; VANISHED 621, every one an all-NULL other/failed
reading; ARRIVED 1,229 — usc/partial 577 (H1), act_relative/failed 471
(H3, reason act_not_in_index), usc/corroborated 156 (H4 45 + H2 111),
act_relative/corroborated 13 (H3's year-fence fix: a number the row states
as its own section is not a year), statute 6+3, public_law 2, usc/ok 1.
Receipt: failed 2,937 → 2,316 (−621 exactly), corroborated 3,629 → 3,801
(+172 = 48+111+13). Actions, CFR references and timetables byte-identical.
Verify PASS; grammar/identifier/act 999/999. Twelve traps refused by name
in H4 (the FR and PL branches published zero — every candidate they
produced was a trap); H1's R2 signal dropped by measurement (165 runs of
prose, one unique arrival); H2's in-box semicolon population measured at
zero; three new fences forced by the data (`42 2000d-1` would have minted
40 U.S.C. 42; a lone `12` is a title, not 12 U.S.C. 12; `sec 1861` beside
`42 USC 1302` would have minted the NSF Act). Hold-outs 12/12, 40/40,
25/25, 20/20, listed with the filer's text in the unit reports.

## The whole register's authority notes, pinned (2026-08-24; 23116f14, 554b72a0)

User-approved corpus-scale acquisition: all 49 non-reserved eCFR titles
fetched keyless from the Versioner API at each title's own latest issue
date (810,674,584 bytes, every response 200, zero retries, sha256 per
title in the manifest), and 8,240 part authority notes extracted over
9,666 parts (80 from a part's first subdivision, flagged; 1,426 parts
publish no note; extractor committed beside the data). The re-acquisition
proves the first one: 278 of generation 1's 287 notes byte-identical, the
other 9 differing only in the publisher's entity encoding — two at the
same issue date on both sides, which rules out drift — and both notes
known to misprint their own title digits still misprint. Coverage of the
corpus's 8,652 named parts rises from 287 (62% of statutory rows judged)
to 5,793 (91.4% of rows); the 2,859 misses are classified, not assumed:
parts gone from the current register (1,926, skewing to pre-2010
editions), reserved blocks and [RESERVED] heads, title 35, title 41's
chapter-part numbering, and 21 parts that genuinely publish no note. The
switch of the oracle to generation 2 is its own cycle after the
disposition unit frees the builder; 45 CFR 12a — the hole the opening
specimen named — is now held, and 40 U.S.C. 550 reads present against it.

## Rebuild #10 (2026-08-24 09:16, receipt sha256:e1c06ebc…) — three units, 269,090 rows, three sets, nothing else

Built at 29563e1b: 084edf69 (the eight CEA corrections A4 had wrong — the
review's finding — now published as act-section-under-a-usc-label with
Table III's own credit; 12g stands with its reason), daea8d4b/f921089e/
f598e42f (the disposition columns answer the citation: 272 span rows
member-by-member from the volume's own list, 189 pinpoint-narrowed rows
including 1341(c) → repealed-no-successor — a second wrong published
value fixed on its own proof — and 17 chapter-guard refusals including
the review's 451 row), and the note oracle on generation 2 (every
authority note the register publishes: 8,240 notes, 5,793 of the
corpus's named parts, judged rows 489,969 → 713,547). Value diff against
the faithful rebuild-9 build: exactly three sets over 269,090 distinct
rows — #53's 8, #54's 478, and the note columns on 268,802 (208,007
arrivals; 21,882 verdict changes, every one an upgrade, proven revealed
data by asking the 287 generation-1 parts all 16,373 corpus questions
under both generations with zero disagreements; 38,913 same-verdict
part-only) — and nothing else; actions, CFR references and timetables
byte-identical; rows 799,126 unchanged. Verify PASS; builder tests
101/101 after one attributed re-pin (f306dccc: A4 3,659 → 3,651, the new
rule's 8, five with the stated pinpoint — a second rule now names
pinpoints and the prose says so); grammar/identifier/act 1,001/1,001.
Two publisher-note defects recorded from measurement, not repaired
(32 CFR 634 elides "Pub. L.", cost 0 rows; an unescaped "&" merges a
list on 36 CFR 230, cost 2 near-miss rows).

Consumer-side verification of rebuild #10 (release-spec-formats, formerly
spicysearch, 2026-08-24): all three passes re-run into scratch; receipts
re-pinned to e1c06ebc…. Two findings, theirs. First, the joined-box rows:
their filed reading admitted the joins as predicted — measured, 1,470
rows carry authority_join_rule, 332 fragments superseded_by_join, and
admitting joins adds exactly ten keys (52 U.S.C. 30116/30118/30120/
30121/30122/30123/30124, 46 U.S.C. 40503/41102, 42 U.S.C. 5318a) while
dropping the superseded fragments loses none, a fragment being by
construction too incomplete to key on. The join is a strict gain and is
now a NAMED reading on their side (box_join_reading: pre-join default,
joined optional, folded into the key digest by name); the default filters
authority_join_rule IS NULL and reproduces c87fdc6a exactly on the
rebuild-10 bytes, so no pinned digest is orphaned. Keeping the fragments
flagged rather than deleted is what made that a measurement instead of a
guess. Second, and more important: their key digest was an incomplete
guard — under the pre-join default the key set was byte-identical and a
court tag set still moved (three tags, additive), because rebuild #9's
621 repaired rows add RIN→key edges without adding keys, and their
per-(key, part) rate has the key's part-bearing RINs as its denominator.
They now digest every (key, part, rate) into both bridge passes'
configuration, so a run that disagrees on rates cannot share a tag
identity. The movement was #9's retypes, attributable in both directions.

## Rebuild #11 (2026-08-24 14:55, receipt sha256:ca8d7912…) — two campaigns, 454 values, one new row, nothing else

Built at ed476b09 after a first launch died with the host process before
writing (stale lock, dead pid, receipt unchanged — relaunched by the
chain's takeover). Units: #56 act-resolver mechanics (f6db3c08 … dc59a800:
year strip gated on the act's own approval date, the H3 year fence
narrowed to years that resolve to a DIFFERENT act, elided list members,
fiscal-year qualifiers read from the box's own tail, the reordered
Public Law; 282 rows, incl. 42 U.S.C. 7412 ×4 published where CAA §112
had been provably lost) and the initialism-roster campaign (#44/#45,
2c83ff33 … ed476b09: the roster pinned as a sixth file oracle with seven
evidence tiers, 92 rows resolved by tier, 329 candidates noted in a new
column, 34 bare-section boxes taking the act a box up to four back named,
69 shape keys the regex had thrown away; one existing wrong value fixed
with proof — `BBA 97`'s section was the year). Value diff against the
faithful rebuild-10 build: rows 799,126 → 799,127 (the one arrival is
`/CAA 112 & 103` yielding two citations); VANISHED 453 / ARRIVED 454 —
208 other/failed readings become act_relative/corroborated (191) or
partial, 105 public_law/partial and 91 usc/partial re-read only their
stated_act_name, 44 act_relative/failed resolve or lengthen, 5
corroborated act rows resolve; act_initialism_roster arrives on 329 rows
(candidate-index-match 182, pinned-quote 105, reverse-pl-verified 7,
self-glossing 5, ambiguous 5, belief-only 11, typed not-an-act 14).
Actions, CFR references and timetables byte-identical. Verify PASS;
grammar/identifier/act 1,002/1,002; the builder pins moved exactly where
the two unit reports said they would (row count, public_law_corrected
335 → 339, corroborated act rows 2,799 → 2,985, the oracle set gaining the
roster, the corroborated-rule census gaining five rules), re-pinned with
each delta attributed. Receipt: authorityFailedRows 2,316 → 2,108;
corroborated 3,801 → 3,991.

## Consumer question answered by measurement, and the gap it exposed (2026-08-24)

release-spec-formats verified rebuild #11 (keys and rates digests both
unchanged) and found the reason their rates did not move: their bridge
admits usc rows only at parse_status ok/partial — a closed list written
when those were the only readable statuses — so the 651 usc/corroborated
and 5,657 act_relative resolved/corroborated rows carrying a section never
reach their reading; their defect, now measured, next reading change.
Their two semantic questions, answered from the artifact: usc
'corroborated' identity columns hold the corroborated reading (never a
candidate) under five witness rules (rin-history-section-list 428,
sibling-usc-title-within-six-boxes 111, one-edit-on-a-scheme-label 45,
rin-history-titleless-usc 43, rin-history-labelless-pair 24), with the
oracle verdict separate — 631 exists, 20 absent (a filer consistently
citing a nonexistent section; the history witness affirms the reading,
not existence); act_relative 'resolved' (3,509; Table III 3,496, source
credit 13) vs 'corroborated' (2,985; 2,148 with a Table-III section, 837
with act_key only) differ in how the NAME was established, not in the
section's strength. GAP FOUND: the 5,657 act-derived sections carry no
usc_section_verdict — the oracle fences authority_type='usc' rows only —
so an act-resolved section's existence at the citing edition rests on
Table III's current classification, not the dated oracle. Its own unit:
verdict + attested-at-edition on act-resolved sections, measured first
(how many resolve to sections absent or not yet enacted at the edition —
the anachronism guard's cousin). Also recorded: on public_law rows
'corroborated' means the identity column already holds the corrected
value (public_law_corrected equals it on all 337), the filer's original
surviving only in authority_text — the reverse of usc corrections.

Consumer plan on the answer (release-spec-formats, 2026-08-24): usc
`corroborated ∧ usc_section_verdict='exists'` joins their DEFAULT reading
(what the closed status list would have said had the status existed when
it was written; the 20 absent rows stay out) — probe +2 keys (16 U.S.C.
668ee, 42 U.S.C. 1553), both bridge digests move once, exposure measured
on the presidential and court corpora before it ships with every removed
tag classified as loss or correction; act_relative resolved/corroborated
with a section and evidence becomes a NAMED reading (+33 keys) whose
exposure is receipted now but ships only when RefSpec's act-derived
section fence lands — the rebuild notice must say so, and they re-measure
under the gate. They do not key on public_law rows.

## The silent-misread rate, re-measured (2026-08-24; 52ca5fde)

Like-for-like re-run of the 2026-08-22 survey on rebuild #11: same frame,
the same seeded draw (re-derived bit for bit from the as-measured parquet
before drawing today's; 149/150 and 140/140 units recur), the same rubric,
four independent reviewers, full per-item tables on disk this time
(research/evidence/silent-misreads-2026-08-24/). The wrong-identity rate
is unchanged by design — per row strict 11/150 → 10/150 (7.3% → 6.7%),
per text 21/150 → 16/150 strict, 21/150 with dropped/unknown — because
the campaign never rewrote a parsed identity without a witness. What it
was built to move, moved: the SILENT fraction — a wrong identity a
consumer cannot see — fell from 7.3% to 2.0% per row (3/150, CI
[0.7%, 5.7%]) and from 14.0% to 4.0% per text (6/150, two of them
unknowns counted silent). Of the original 13 flagged per-row items, 3 are
fixed outright, 6 loud, 3 silent; twelve of the sixteen named classes are
fixed or fenced, B1 corrected live, B6 narrowly, B3 and B8 open (B8 by
design). Residual silent mechanisms, each with a specimen, now the
queue: the wrong universe in the U.S.C. slot masked by a coincidental
note "present" (#55); Executive Order numbers with no existence oracle
(a pinned EO roster — new unit); `NNN(x)` for `NNNx` where no note
witnesses the part; compact slash compounds dropping their act half
(`42 USC 7401/CAA 112`, a new DROPPED class); "X to Y(z)" and in-list
ranges losing their endpoint (three of 75 texts, a new DROPPED class);
usc_title_is_possible=false to be read as loud; scheme retypes
(`60 CFR 15845` → Federal Register) to carry a flag. Queue order after
the consumer-gated act-section fence: #58, #62, then these.

Rebuild #11 re-pin (02b57299): 14 reds, every delta attributed by marker
(act_initialism_roster / act_resolution_sibling_ordinal → the roster
campaign; else a rule this rebuild's census ties to #56), 194 passed,
check-generated green, unexplained list empty. One attribution to keep:
three act_relative rows' note verdicts moved (near-miss 6 → 9, RINs
0584-AE96/AF07) though no row's own data changed — #56's grammar
widening changed how 7 CFR 225's own authority note parses. The notes go
through the same grammar as the filers' text, so a grammar unit moves the
witness column as well as the rows; the diff must be read on both sides.
The audit chore for #11 folds into rebuild #12's close.

## The standard, restated by the user (2026-08-24): the silent residue is the target, not the tail

"Good enough is not sufficient when it comes to missing potential related
files." Two percent silent per row is on the order of 16,000 rows whose
wrong reading nobody can see, and a DROPPED authority is worse than a
wrong one — the file never links and nothing on the row says so. The
queue is reordered, omissions first, with a measured pass/fail: keep
working and re-surveying until the silent rate's 95% upper bound is
below 1% on both estimators. Order: (1) the two DROPPED classes the
re-survey named (slash compounds; range endpoints lost inside lists),
counted corpus-wide now, readers next; then the 6,876 "more citations
follow" placeholders gain CANDIDATE authorities from the rule's own part
authority note and the same RIN's other editions, never identities;
(2) the NNN(x)/NNNx ambiguity where no note witnesses the part — a
two-witness rule (the subsection oracle's "no such subsection" plus the
note or the RIN's other editions' spelling) publishes, one witness stays
a candidate; (3) the Executive Order existence oracle (research running)
then the fence and one-survivor corrections; (4) the wrong universe in
the U.S.C. slot (#55); (5) a larger re-survey, n≈500 per estimator, so
1% is resolvable from 2%. The act-derived section fence (consumer-gated)
lands first because it is already in flight; #58/#62 follow the list.

## The act-derived sections, dated (2026-08-24; 848e9372)

The gap the consumer's question exposed, closed. 5,657 act_relative rows
carry a U.S.C. section OLRC's Table III (5,644) or the Code's own source
credits (13) classified, and none carried a verdict, because the section
fence judges `authority_type='usc'` rows only. Measured first, read-only
over rebuild #11 through the same oracle call the usc rows get:

    act-derived rows with a section and evidence     5,657
      verdict exists                                 5,657
      verdict absent                                     0
      verdict unknown                                    0
      of the exists, attested at the citing edition  5,638
      of the exists, NOT attested                       19
    distinct texts / pairs / RINs / act sections   1,082 / 348 / 979 / 360
    by evidence   table3-classification 5,644 · source-credit 13
    by status     resolved 3,509 · corroborated 2,148
    C0 title-impossible                                    0

Zero absent is the finding, not a null result: every one of the 348 Code
addresses Table III maps these act sections to is a section the oracle
prints, so the mapping's currency is nowhere refused. The 360 act sections
judged are exactly `actRelativeResolvedPairs` — resolved and judged are the
same population.

**The label decision: no new word.** The 19 unattested rows are two
mechanisms and the existing vocabulary says both. 16 are the ORACLE's own
hole — the pinned annual archive carries no 2012 volume for titles 33-41,
52 or 54, so every title-33 section reads unattested at the 201210 edition
(133 U.S.C.-typed rows at that same edition carry it identically, and
`uscSectionExistsNotAtEditionRows` has always counted them without a
reason). 3 are the era mismatch proper: 42 U.S.C. 805 and 806 (Social
Security Act §§605, 606, RIN 0938-AK71, 200310 — printed 1994-2002 and
2021-2024, and 2022-2024 respectively) and 20 U.S.C. 10005 (ARRA 2009
§14005, RIN 1810-AB17, 201310 — first printed 2014). A reason code was
considered and refused on three grounds: `SectionVerdict` accepts a reason
only beside `unknown`, so it would need a NEW column; `exists` +
`attested_at_edition = false` already says exactly this; and the U.S.C.
rows carry the same two mechanisms in the same two columns without one, so
minting a word for act rows alone would make the same fact readable on one
population and not the other. The recodification anachronism the unit went
looking for — a section whose Code home moved into title 49 or 54 after the
filing — does not occur here at all.

The pass runs after the resolver and writes three columns; the U.S.C.
fence's own census and the magnitude ceiling are untouched, and the act
counts live in parallel `actSection*` receipt keys because the two
populations are disjoint and a consumer gating on these identities needs
its own number. Proof: scratch build of builder sha256:8c1a4b37 diffed
against the faithful rebuild-11 baseline — 799,127 rows unchanged, actions,
CFR references and timetables byte-identical, and exactly 5,657 rows of
legal_authorities differ in exactly two columns (`usc_section_verdict`,
`usc_section_attested_at_edition`; the reason stays NULL, there being no
unknowns). Every `uscSection*` and `uscDisposition*` count reproduces
rebuild #11 exactly. Seeded hold-out (random.Random(20260823)) of 20 newly
judged rows read by eye: 20/20 correct — CEA §8a → 7 U.S.C. 12a, HEA §455 →
20 U.S.C. 1087e, TSCA §601 → 15 U.S.C. 2697 (attested from 2010, cited
2014), SSA §1138 → 42 U.S.C. 1320b-8, INA §212 → 8 U.S.C. 1182, and the
Communications Act list members at their own ordinals. The draw contains no
unattested row, which is what 19 in 5,657 predicts.

Rebuild #12 re-pin: the receipt gains ten `actSection*` keys and the
contract clause `anActDerivedSectionIsJudgedAtTheCitingEdition`; two new
tests (`test_the_act_derived_sections_are_judged_at_their_edition`,
`test_the_receipt_census_covers_the_act_section_fence`) turn green;
`test_the_receipt_names_the_code_that_wrote_it` is red from 848e9372 until
it lands. No existing pin moves — the U.S.C. fence's counts and its receipt
recomputations were scoped to `authority_type='usc'`, which is the
population every `uscSection*` key has always described, and verified
unchanged on both the artifact and the scratch build.

## Two omission findings, pinned (2026-08-24; 40060e44, 5d088636)

Executive Orders: 19,011 rows cite 391 distinct orders (1197–23891); the
only fence today is an undated series bound (catches 3 numbers). Two
keyless primary sources exist — the FR API from EO 12890 (Dec 1993) and
NARA's Truman→Reagan codification numeric index to 12667 (the
disposition-table pages now serve an index stub) — confirming 345 of the
391 (84.8% of rows) with zero anachronisms; 46 are unresolved, 32 of them
in the 1990–1993 gap between the two sources (EO 12866 among them), which
the oracle must label `unknown` with the gap named, never `absent`. Two
corrections have one survivor by the roster's own witnesses: 23891 →
13891 (the text carries 13891's title and date) and 8284 → 8248 (the sole
transposition neighbour still live law and on subject); 20450 → 10450
needs a second witness; 21600 and 7419 refuse with two and five
survivors. Evidence research/evidence/investigations-2026-08-24/inv-eo/.

DROPPED authorities, the class the user's standard puts first: the
grammar's whole-value fallback fires only when nothing matched, so a
second authority behind a slash is discarded and never re-scanned — 235
texts / 1,539 rows (`42 USC 7401/CAA 112`, `15 USC 2603/TSCA 4`), plus 8
spelled-out act names dropped the same way; and range endpoints are lost
in 401 texts (in-list ranges 3,880 rows, parenthesised endpoints 249,
compound-name endpoints 491, spelled shorthand 149 — `1817 to 19` fails
where `1817-19` expands), with a prose-"to" trap that makes a whole second
citation vanish through backtracking (63 rows). Both readers are the next
grammar units after the act-section fence; the slash reader yields NEW
rows (1,539), the range reader fills usc_section_end on existing rows
and recovers the 63 vanished citations. Evidence inv-dropped/.

## The placeholders can be witnessed, and the note reader mints years (2026-08-24; 1289e3b8)

The 12,467 placeholder records (`...` 6,876, "Not Yet Determined" 5,461,
"None" 130) — the largest omission the artifact merely labels — gain
CANDIDATE authorities from two witnesses inside the pipeline's reach:
the record's own CFR parts' authority notes reach 87.0% / 38.4% / 39.2%
of them with ≥1 candidate, the same RIN's other editions 6.2% / 62.2% /
13.8%, either 87.2% / 75.8% / 43.1%; where both exist they intersect
60–100% of the time and the intersection is the strongest signal (it kept
42 U.S.C. 1382/902 and dropped a veterans citation stuck in SSA's early
editions). Design: two list columns naming the witness, the intersection
surfaced, no identity or status moved, omnibus notes (26 CFR 1: 322
citations) flagged low-specificity, note candidates dated against the
placeholder's edition. Found on the way: the shared note reader reads an
EO compilation's date range ("3 CFR, 1954-58 Comp., p. 218") as a U.S.C.
span under the preceding title — 818 phantom citations over 291
identities in 600 of the 8,240 notes, 3.0% of the note-derived candidate
pairs, and a smaller blast radius on the shipped note verdicts. That is
the #46 list-tail fence measured at scale; it moves to the front of the
grammar queue, ahead of the slash reader (1,539 new rows) and the range
reader, all after the act-section fence in flight.

Two-witness NNN(x) (2026-08-24; inv-b8): the subsection oracle's "no such
subsection" plus the part's note or the RIN's other editions spelling
`NNNx` publishes 1,166 rows (1,101 net of B1), 15/15 specimens on-subject
at the publisher, every tail kept; 4,201 stay candidates, 8,888 refused.
Queue after the act-section fence: #46 (Comp.-year and list-tail fences,
text and notes) → slash reader → range reader → two-witness NNN(x) →
rebuild #12 → EO oracle → placeholder candidates → #58, #62, #55 …

Consumer findings on rebuild #11 (release-spec-formats, 2026-08-24;
their b9fba52, ab84279): (1) the corroborated admission shipped, but the
`corroborated ∧ verdict='exists'` gate did not survive their review —
inert (0 tags either way) and mis-justified, since four of the five
corroboration rules are oracle-gated already, and 18 of the 20 rows it
would reject are `18 U.S.C. 3568/3569` on RIN 1120-AB66: the section our
contract clause uscSectionsAreFencedByTheOracle names as its specimen of
a FALSE absent (repealed 1987, cited for pre-1987 conduct, outside the
oracle's window). The default now admits corroborated rows
unconditionally; the verdict stays a fact a consumer may read, not a
gate. Ours to act on: an `absent` today carries no reason, so a consumer
cannot tell "not a real section" from "outside the oracle's window" —
the reason column should say `repealed_before_1994_not_stubbed` (or the
exact window fact) on those rows; that is #38's caveat item, now a small
unit of its own. (2) Dilution measured: 41.9% of their keys sit on one
RIN, so every repair that grows a key's population moves their per-part
rates; their thresholds are re-swept and their rates digest moved to
provenance, so a neutral rebuild no longer re-mints tag ids. (3) An
edition collision for the ledger: `49 U.S.C. 10708` is the pre-1995
"suspension of rates" section AND the post-ICCTA "rate agreements"
section — the same (title, section) naming two provisions across a
recodification in place, which put rail topics on motor-carrier
opinions. Our usc_section_attested_at_edition marks the year; their
bridge does not read it yet. A recodification-in-place oracle (ICCTA
1995 for title 49 subtitle IV, and its siblings) is the general fix —
named, unbuilt, beside the 1994 appendix table. (4) Their act-resolution
reading measured indistinguishable across 48 sweep cells and waits for
our act-section fence, as planned.

## Raw-row review, rebuild #11 (2026-08-24) — the standard restated by the user

"Make decisions only after manually and completely viewing the specific
raw inputs/outputs; code can hide signal." Applied retroactively to
rebuild #11: the 450 changed rows and 1 new row dumped with text and
old → new values, a seeded 40 read by eye. No regression in the sample:
every retype resolves to the act the text names, every lengthened
statement is the filer's own words. Three findings the tallies could not
show: (1) the name walk stops at an internal comma — "PL 104-227,
Antarctic Science, Tourism and Conserv. Act of 1996" is stated as
"Tourism and Conserv. Act of 1996", a truncated name published as a
statement; (2) an act-section pinpoint has no column — "sec. 11101(e) of
the IIJA" becomes act_section 11101 and "(e)" is dropped silently, as is
the "(d)(2) and (3)" tail on "CAA 112(d)(2) and (3)" — a schema gap
(act_section_pinpoint / act_section_end) beside #62's range item;
(3) abbreviated words keep correct names out of the index —
"International Security & Development Coop. Act of 1981" reads
act_not_in_index because "Coop." is not "Cooperation" (also "Conserv.",
"Mgmt.", "Adj.", "Comp.") — an abbreviation-expansion table as a
witnessed normalization is its own small unit. From here every unit's
changed rows are dumped and read before rebuild or pin; implementers
report rows verbatim, not counts.

Raw-row reads, retroactive (2026-08-24): rebuilds #8, #9 and #10 dumped
row by row from their snapshots and read by eye — all of #53's eight and
#54's seventeen refusals, seeded samples of #54's span and pinpoint
moves, the note-witness upgrades, #9's 621 retypes and 608 joined rows,
the superseded fragments, #8's 1,325 continuation rows and its four
spaced-suffix corrections. No regression found: title carries land on
the citing agency's own title, joined rows are the filer's own list
continued, pinpoint narrowings are the printed table's subsection
entries (`1651(b)(2)` → 49 U.S.C. 303). One thing to say in the receipt:
a pinpoint that narrows to ONE successor is a one-element candidate list
a consumer will read as an identity — it is the publisher's own
subsection-level entry, which meets the bar, but the census should name
those rows. The Executive Order gap closed (inv-eo-gap/): NARA's per-year
disposition pages resolve all 32 cited 1990–1993 numbers; the oracle
unit is fully grounded.

## The oracle's twelve missing volumes (2026-08-24; 852d31fa)

The act-section fence found 16 of its 19 "not attested at the edition"
rows on title 33 at edition 201210 and blamed the annual archive; the
probe found why: the section oracle's extractor matches archive
filenames case-sensitively and OLRC named twelve volumes with uppercase
USC (2010: titles 12, 13, 14, 51; 2012: 33, 35–41), all present at the
publisher, all silently skipped. Exactly twelve (title, year) holes exist
in 1994–2024; 52/54 before 2014, 34 before 2017 and 6 before 2002 are the
genuine ones (titles not yet created). Cost on the artifact: of the 8,258
usc rows reading exists-but-not-attested, 1,881 (390 sections, 538 RINs)
are ours — title 12 in 2010 alone 1,367 — and 6,311 are real era
mismatches; the three act-derived rows checked at the publisher are real
(42 U.S.C. 805 repealed 1975 and reused 2021 by its own prior-provisions
note; 806 new in 2022; 20 U.S.C. 10005 first printed 2014). Generation 2
of the annual tables is being derived evidence-side with the matcher
fixed and a loud failure on any unmatched file; the module switch and
the attributed re-pin follow the grammar sequence. Lesson: a pinned
archive's coverage matrix is a fact to print and test, not to assume —
an extractor that skips silently is an oracle that lies quietly.

## The queue, with every population sized (2026-08-24, evening)

Every read-only sizing is in and pinned under
research/evidence/investigations-2026-08-24/. In flight: the grammar
sequence (#46 list-tail fences — now also the repeated-year compilation
locator and the cross-family volume bleed; the slash reader, 1,539 new
rows; the range reader, ~4,700 endpoint fills + 63 recovered citations)
and generation 2 of the section oracle's annual tables (twelve skipped
volumes; 1,881 rows to re-attest). Then, in order, one builder/oracle
owner at a time, each unit's changed rows read raw before rebuild or pin:
rebuild #12 (the act-section fence + the grammar units; the consumer's
named act reading unblocks) → the oracle module switch to generation 2
and its attributed re-pin → the two-witness NNN(x) rule (1,166 rows
publish, 4,201 candidates, 8,888 refused) → #47 paren-eaten suffix (202
rows now, 7 after the tail-precedence fix) → attestation reasons
(absent's window reason; title_not_yet_created;
edition_beyond_archive_ceiling) → the Executive Order oracle (roster:
FR API + NARA codification + NARA year pages; 345+32 of 391 confirmed,
11 unknown by name, 8284→8248 and 23891→13891 corrections) → placeholder
candidates from notes and editions (87% / 76% / 43% of records, the
intersection surfaced) → #62 (five agency-bound quotes; the 40
apostrophe-year rows) → #58 (65 rows) → #55 typed usc_slot_reading (155
silent reg-shaped rows, 235 witnessed reg-suffix rows, 1,690 chapter
candidates with 1,244 ambiguous) → the list-collapse grammar fix (107
citations restored) and the paren-range defect (15 rows) → #42 per-volume
FR page bounds (225 beyond-volume rows) → #43 audit gate → #57 hygiene
(cp1252 repair for abstracts; HTML abstracts from 201410, 77,120
records; 58 mid-list ellipses; the 2 R5 stragglers) → #60 appendix range
tail (162 rows) → #34/#36 title repairs with the note and the filer's
other editions as witnesses → #39 abstract exposure (5 of 6 missing-year
act families) → the larger re-survey (n≈500 per estimator) with the
silent bound under 1% as pass/fail.

## Generation 2 of the annual tables, accepted on raw rows (2026-08-24; a8cac15a)

The 32 annual zips re-fetched keyless and retained (2,289,552,527 bytes),
every one byte-identical to generation 1's digest table — same bytes,
fixed matcher, which is what makes the proof real. Generation 1's
pattern, applied to all 1,835 zip members, skipped exactly the twelve
title volumes named uppercase; the new extractor stops on any member it
does not recognise (it stopped on 1994/usc.css and on the 2011 archive's
two Congress cross-reference tables until they were allowlisted by
name). Coverage 1,642 → 1,654 (title, appendix, year) pairs, +7,218
sections and +137 ranges, and all other pairs' rows identical both
directions; the other four tables and the enumerated set (66,780) do not
change at all, so the fix can move attested_at_edition and cannot move a
verdict. Would-flip against rebuild #11: 1,881 usc rows (title 12 in 2010
1,367; the 30 "uncertain" rows correctly stay — titles 40/41 cited by
pre-recodification numbers the 2012 volumes do not print) plus the 16 CWA
act-derived rows. Read raw: the seeded twenty are OCC/OTS/FDIC/NCUA/FHFA
rules citing real title-12 sections in 2010, the PTO's 35 U.S.C. 2, the
VA's 38 U.S.C. 3680, `41 USC 1502(c) (formerly 41 USC 422(g))` at 2012;
the recovered headings are the right titles' sections (12 U.S.C. 1701z-2,
33 U.S.C. 449, 35 U.S.C. 271, 38 U.S.C. 7307). The as-measured snapshot
stays anchored on generation 1, whose measurement it is. The module
switch (constants and the two moved counts 1,565,007 → 1,572,225 and
49,823 → 49,960 recorded in the unit report) follows the grammar sequence
and rides rebuild #12.

## Stopping point (2026-08-24, evening) — out of credits; where the next session starts

ON DISK: the shared artifact is rebuild #11 (receipt ca8d7912…),
verified, consumer-pinned. NOT rebuilt: rebuild #12 has not run.

COMMITTED, UNSHIPPED (all on the branch, no push): the act-derived
section fence (848e9372 …), the grammar sequence — #46 list-tail fences
a3962c4c + d8711026 (compilation-locator numbers incl. the repeated-year
variant, dotted CFR sections, treaty/reporter volume bleed), the slash
reader 7f534962, the range reader 7cb4b7af, the one-row CFR-reference
correction 4d9ea0f9 — and generation 2 of the section oracle's annual
tables (a8cac15a, evidence only; the module still points at 2026-08-22).
Suite: make test 1 red (receipt-names-the-code, by design until the
rebuild), make test-slow 2 reds (the fence's own artifact pins, green on
its scratch). Raw changed-row files for all three grammar units are
pinned at research/evidence/investigations-2026-08-24/units-grammar/.

RAW READ, DONE: the 51 removed readings are all CFR section numbers or
locator years read as U.S.C. sections (`secs. 1.407 and 1.411`,
`51.65`, `1.51(F)`, the 31 U.S.C. 1982/166 phantoms) — right; the 14
slash traps held (9/11 Commission Act, Hermit's Peak/Calf Canyon, the
Treasury/General Government division, docket prefixes, `7401/et seq`);
the 63 refused range endpoints are right (`20000bb`, `406k-4`, descending
and typo pairs).

RAW READ, FOUND — FIX BEFORE REBUILD #12: of the 1,428 slash arrivals,
892 act-half readings agree with the filer's own U.S.C. half and 216
disagree (48 distinct texts; the list is in this session's notes and is
re-derivable from units-grammar/changed-rows-ALL-THREE-UNITS.tsv by
joining each ADDED slash row to its citation-0 sibling). Most
disagreements are the act half being RIGHT beside a damaged U.S.C. half
(`42 USC 300/SDWA 1412` → 300g-1 is SDWA §1412; `33 USC 1311/CWA 307` →
1317 is CWA §307; CERCLA 107 → 9607; FIFRA 3 → 136a; TSCA 5 → 2604;
EPCRA 313 → 11023; FFDCA 408 → 346a) — both halves are the filer's own
statements and both rows now exist, nothing invented. But where the
roster binds "CAA"/"CAAA" at a RIN to the 1990 AMENDMENTS act, the act
half resolves under the Amendments' own section numbering and publishes
a wrong real section: 2060-AD04 `42 USC 7411/CAA 111` → 42 U.S.C. 7408
(four editions; CAA §111 IS 7411, the filer's own half), 2060-AD77
`42 USC 7545/CAAA 211(f)` → 7542 (CAA §211 is 7545). The rule to
implement: the U.S.C. half SELECTS the act — among the candidate acts the
token can name, exactly one whose Table III classification of the stated
section equals the U.S.C. half wins; if none agrees, keep both stated
rows but mark the act row as conflicting with the filer's own U.S.C.
half (a flag column with the U.S.C. half quoted), never silently
publish. Measure the CAA/CAAA-bound population first; its specimen red
test is 2060-AD04 199510 `42 USC 7411/CAA 111` → 7411, not 7408. Read
every changed row raw again after the fix.

THEN, IN ORDER (each unit's rows read raw before rebuild or pin):
1. the slash act-selection fix above → 2. the oracle module switch to
generation 2 (constants and moved counts in a8cac15a's report; the
as-measured snapshot stays anchored on generation 1; 1,881 + 16 rows
re-attest, zero verdicts move) → 3. rebuild #12 (chain in
/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/rebuild3_chain.sh, sed
rb11→rb12; diff vs old-rebuild11-ed476b09/out read raw; re-pin from
units-grammar/rebuild12-delta.txt + the fence's and the switch's delta
lists; make audit-registry-real-data; ledger; notice to
release-spec-formats saying the act-section fence landed) → 4. the sized
queue in the entry "The queue, with every population sized".

Nothing else is half-done: every measurement is pinned, every unit is
committed whole, the tree is clean.
