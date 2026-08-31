# Visual review of the remaining malformed classes, 2026-08-23

Ten random rows per class (seed 20260823; `samples.md` holds each filer's
text verbatim), each class handed to one reviewer with one rule: judge by
reading the text and the publisher's own pages — reginfo.gov's agenda entry
for the rule, uscode.house.gov, govinfo, Cornell LII, eCFR authority notes,
federalregister.gov — never by running the grammar or the oracle. Code was
allowed only to retrieve. Verdicts below are the reviewers', lightly
condensed; hypotheses are stated as hypotheses.

## C — placeholders (12,467 rows; 10 reviewed): typing holds 10/10

All ten agenda pages fetched (1996 through 2018). On every page the Legal
Authority field is a list of hyperlinked citations; the ellipsis is a final,
**unlinked** plain-text item after a real list of 3 to 22 citations — never
mid-list, never alone — which is the shape of a submitted sentinel, not of a
display cutoff (a UI truncation would fire at a fixed count, not at 3 and at
22). Both "Not Yet Determined" rows are the field's sole content. The dots
render as `...` on all eight; `. . .` never appeared on reginfo (the spaced
spelling in the XML for RIN 0625-AA66 is the filer's).

| # | RIN · edition | text | kind | verdict |
|---|---|---|---|---|
| 1 | 3235-AG65 · 199604 | `...` after 15 citations | more-citations-follow | confirmed — and the page's *Additional Information* field reads "LEGAL AUTHORITY CONT: 15 USC 77g; 77j; 77eee; 77ggg; 77nnn; 77sss; 78d; 78ff; 80a-20; 80a-23; 80b-4; 80b-11; 78ll(d)" — the thirteen omitted citations, filer-labelled |
| 2 | 2501-AD07 · 200404 | `...` after 6 | more-citations-follow | consistent; no continuation field |
| 3 | 3133-AD06 · 200504 | `...` after 5 | more-citations-follow | consistent |
| 4 | 1120-AB28 · 200510 | `Not Yet Determined` | not-yet-determined | confirmed, sole content |
| 5 | 2900-AN81 · 201110 | `...` after 6 | more-citations-follow | consistent |
| 6 | 3060-AK16 · 201510 | `Not Yet Determined` | not-yet-determined | confirmed (the CFR Citation field says the same, separately) |
| 7 | 3052-AD14 · 201604 | `...` after 4 | more-citations-follow | consistent; Additional Information is a contact, not a continuation |
| 8 | 7100-AE44 · 201604 | `...` after 3 | more-citations-follow | consistent; shortest list in the sample |
| 9 | 1545-BM15 · 201710 | `...` after 5 | more-citations-follow | consistent |
| 10 | 3235-AM37 · 201810 | `...` after 22 | more-citations-follow | consistent; longest list |

**Hypothesis raised, then measured:** where a filer ticked "additional
citations", the omitted citations are sometimes written into the Additional
Information field under "LEGAL AUTHORITY CONT" — a field this builder never
reads. Measured over the 60 pinned editions: the phrase occurs in **52
records across 16 editions (39 RINs)**, inside `<ADDITIONAL_INFO>`; only
**one** of the 52 also carries an ellipsis row. So it is a small, separate
filer convention — a continuation written *instead of* the box — not a key
to the 6,876 incomplete lists; it is exact and cheap to read (a named
source, a pinned field, the same grammar), and is queued as such.

## D — timetable Federal Register citations refused (8 rows, all reviewed): refusals right 8/8, all recoverable with one survivor

Reviewer resolved each through federalregister.gov's documents API (RIN
field, date, title) and reginfo's own timetable page. The damage is in
OMB's record, not introduced here: six of the eight strings are still
hyperlinked *as damaged* on reginfo; the three `75770x` rows reginfo's own
linker could not resolve either. Five distinct defects; three repeat across
editions as a completed action rolls forward.

| # | RIN · edition | filer's text | the document | damage | corroboration |
|---|---|---|---|---|---|
| 1 | 2040-AF62 · 201610 | `81 NFR 66900` | 81 FR 66900, EPA ANPRM 2016-09-29 (2016-23432) | stray N | FR RIN field names 2040-AF62 |
| 2 | 1625-AC52 · 202010 | `85 FSR 62651` | 85 FR 62651, USCG NPRM 2020-10-05 (2020-21071) | stray S | FR RIN field |
| 3–5 | 3060-AL15 · 202204/10, 202304 | `85 FR 75770x` | 85 FR 75770, FCC 5G Fund final rule 2020-11-25 (2020-24486) | trailing x | page unique per volume + exact date + exact title (FCC documents carry no RIN field) |
| 6 | 3060-AJ58 · 202304 | `85 DR 34525` | 85 FR 34525, FCC 2020-06-05 (2020-09815) | D for F (adjacent keys) | the same reginfo timetable cites the clean `85 FR 34525` on the next row |
| 7–8 | 0648-BK86 · 202504/10 | `89 FR 1022091` | 89 FR 102091, NOAA NPRM 2024-12-17 (2024-29238) | a doubled 2 | FR RIN field; neither "drop a digit" guess (102209, 10220) is right |

**Judgment:** the reader was right to refuse every one; none is a spelling
it should accept. Recovery is exact where the Federal Register's own
document record is the oracle — one document per (volume, page) by
construction — and it must be the document, not the string's shape, that
decides (`1022091`). Queued as a corroborated correction against a pinned
copy of those five documents' metadata, not a live call.

## A — unreadable (2,960 rows; 10 reviewed): the label is wrong 10/10

Every row's agenda entry was fetched; readings were checked against the
rule's published CFR authority note, the Code's source credits, or the
enrolled statute. None of the ten is unreadable; what varies is how far one
must reach — from the string itself to one join.

| # | RIN · edition | filer's text | what it is | how it is known |
|---|---|---|---|---|
| 1 | 2126-AA63 · 200010 | `sec.206` | §206 of Pub. L. 106-159 (MCSIA) — the act sits in the NEXT box, `PL 106-159` | the record's own Legal Deadline says "See section 206 of PL 106-159"; 49 CFR 386's note: "sec. 206, Pub. L. 106-159, 113 Stat. 1763" |
| 2 | 2126-AA64 · 200410 | `113tat. 1754 (1999)` | `113 Stat. 1754` — one keystroke ate " S"; the parallel cite of the previous box `sec 211, PL 106-159` | volume 113 is 1999 and holds PL 106-159 — but §211 is at 113 Stat. 1765–66, so the recovered page is wrong: recovered ≠ correct |
| 3 | 2060-AP43 · 201004 | `Atomic Energy Act sec 275` | §275 of the Atomic Energy Act of 1954 = 42 U.S.C. 2022 — the same provision as the boxes beside it (`42 USC 2022, 2114`; `UMTRCA sec 206(a)`) | 40 CFR 192's note; 42 U.S.C. 2022's source credit. A lexicon miss (no year) wearing a parse-failure costume |
| 4 | 3072-AC38 · 201010 | `40503` | 46 U.S.C. 40503 (Shipping Act refunds and waivers); title 46 stated three boxes earlier and dropped | 46 CFR 520's note: "46 U.S.C. … 40501-40503 … 41101-41109" |
| 5 | 0970-AC50 · 201104 | `sec 1102 of the Act` | §1102 of the Social Security Act = 42 U.S.C. 1302; sole entry, "the Act" bound only by agency + CFR part | 45 CFR 302/303 notes cite 42 U.S.C. 1302. Belongs in class B (shape read, referent unknown), not A |
| 6 | 0936-AA07 · 201710 | `1102` | SSA §1102 again — the act named once as "SSA" in box 0 (`1007: SSA subsection 1902 (a) (61)`) and carried through four boxes; `1007:` is the CFR part number typed into the list | 42 CFR 1007's note: "1396b(a)(6), 1396(b)(3), 1396b(q), and 1302" maps the boxes one for one |
| 7 | 0720-AB70 · 201904 | `NDAA-17 sec. 701` | §701 of Pub. L. 114-328 (FY2017 NDAA), "TRICARE Select" | the abstract defines "NDAA-17" 200 characters away; §§706/715/718/729 in the sibling boxes all exist |
| 8 | 3052-AD44 · 202210 | `3.7, 3.11, 3.25, 4.3, 4.3A` | five tokens from the middle of 12 CFR 615's authority note ("Secs. 1.5, 1.7, 1.10 … of the Farm Credit Act (12 U.S.C. 2013 …)"); §3.7 = 12 U.S.C. 2128, §4.3A = 2154a | the note; the sibling rule (#9) chops the same string at different points, proving the boxes are manual chunks |
| 9 | 3052-AD42 · 202210 | `2.4, 2.5, 2.12, 3.1, 3.7` | the same note, different cut; §2.4 = 2075 … §3.7 = 2128 | as #8; `...` closes both lists where "of the Farm Credit Act" was cut off |
| 10 | 3072-AC96 · 202304 | `591 to 596` | 5 U.S.C. 591–596 (Administrative Conference); title 5 in the previous box | the rule's published authority note (2023-05764); its CFR Citation field holds `5 CFR 2635` — the note's tail misfiled one field over |

**Patterns:** the list is not a list (one string chopped across boxes, at
arbitrary points — P1); title/act elision within a run, forward and
backward (P2); lexicon gaps dressed as parse failures — bare act names, "the
Act", record-defined abbreviations (P3); edit-distance-1 damage on closed
connective tokens (P4); the record carries its own answer key in eight of
ten — the CFR part's authority note, the abstract, the deadline text (P5);
the terminal `...` of class C is the scar where the truncation that produced
the A-fragment happened (P6); recovered is not correct — #2's page, #10's CFR
field (P7).

**Hypotheses to test (not counts):** H1 parse the joined string per rule
with box index as provenance — the highest-leverage change and no new
grammar; H2 sibling carry of title/act, direction-agnostic, gated on the
carried section existing; H3 move shape-read rows to act_relative and widen
the lexicon (short names without a year, abbreviations harvested from the
record's abstract, "the Act" bound by agency + CFR part); H4 typo-tolerant
connectives emitted only past a corroboration gate, layered (volume↔year
passes where section↔page fails); H5 the CFR-part authority-note join as a
first-class corroboration table — it settled seven of ten here; H6
re-sample after H1–H3 and expect the strict unrecoverable bucket to be
small: on this sample it is empty, so 2,960 reads as a backlog of
unimplemented rules, not a floor of lost data.

## G — corrections with exactly one survivor (5,255 rows; 10 reviewed): A4 8/8 truth, B8 1/2 — one wrong-but-real value

| # | RIN · edition | filer's text | correction | verdict | evidence |
|---|---|---|---|---|---|
| 1 | 2040-AD08 · 199710 | `33 USC 1361a` | 1361(a) (A4) | truth | 40 CFR 136's note: "… 501(a), Pub. L. 95-217 …"; the agenda list is that note transcribed, "sec. 501(a)" in the `1361a` slot; no §1361a exists |
| 2,5,6,8 | 0910-AC96/AC98/AD43/AF36 | `21 USC 321p` | 321(p) (A4) | truth | FD&C §201(p), the "new drug" definition the OTC monograph rules hinge on; 21 CFR 310/330 cite §201(p) 27 times; §321p never existed (321a–321d do, and were checked) |
| 3,4,9 | 0910-AD59/AD19/AF82 | `21 USC 371a` | 371(a) (A4) | truth | 21 CFR part 4's note holds "371(a)" in exactly that slot; the same RIN's Fall 2016 edition prints `21 U.S.C. 371(a)` — the publisher correcting itself |
| 7 | 2501-AC95 · 200404 | `12 USC 1735(f)-14` | **1735f** (B8) | **wrong** | the rule is FHA mortgagee civil penalties = 12 U.S.C. **1735f-14** (NHA §536; 24 CFR 30's note spells it so); 24 CFR 25's own note carries the publisher's typo "1735(f)-14"; 1735f is water and sewerage facilities. The candidate generator truncated "-14", so "one survivor" was manufactured |
| 10 | 3084-AB46 · 201904 | `15 U.S.C. 18(a), Clayton Act` | 18a (B8) | truth | "Premerger Notification Rules"; the abstract says "section 7(A) of the Clayton Act, codified at 15 U.S.C. 18(a)"; 16 CFR 801/803: "Authority: 15 U.S.C. 18a(d)" — settled by the abstract and the CFR parts, which B8 cannot see |

**Judgment.** A4 stays a correction: it never relocates a citation (371a →
371(a) keeps identity 371 and adds a pinpoint), so an identity-keyed
consumer is right either way. B8 becomes a candidate, for two reasons: its
candidate generator cannot reach hyphenated lettered sections (1735f-14,
1735f-15, 1735z-11a, 1701q-1 …), precisely the family where parentheses go
astray — a repeatable bug, sized below — and its correctness on the cases
it does reach (§18 vs §18a) rests on evidence outside its inputs. A rule
whose truth depends on the abstract is a candidate generator, not a
corrector. Adjacent hazard recorded: A4's trigger is the edition's section
inventory, so `21 USC 360a` is corrected in 1999–2002 editions and left
alone from 2007, when §360a came to exist — right per row, unstable per
text.

## B — act-relative, unresolved (6,214 rows; 10 reviewed): a human resolves 7/10 to a section, 2 more to an act; 1 is correctly unresolvable

The reviewer went to the publisher only: OLRC's Popular Name Tool (13,628
entries; 12,965 with a Table III search key; 663 keyless cross-references;
8,399 distinct keys — 1,922 chapter-style `1935:531`, 6,477 Pub. L.-style),
the Table III pages, the Code, govinfo, and each rule's agenda entry.

| # | RIN · edition | filer's text | the publisher's answer | why it failed |
|---|---|---|---|---|
| 1 | 2060-AE44 · 199604 | `Clean Air Act Amendments of 1990, sec 112` | Pub. L. 101-549 has no §112; the filer cited the base act's section — CAA §112 = 42 U.S.C. 7412 (101-549 §301 rewrote it) | amending act named, base act's section cited |
| 2 | 0938-AK68 · 200110 | `Social Security Act, sec 1871` | 42 U.S.C. 1395hh — Table III `1935:531` row present | chain intact at OLRC; break downstream |
| 3 | 2060-AH63 · 200704 | `Nuclear Waste Policy Act of 1982` | act-level only: 42 U.S.C. 10101 et seq. (key 97-425) | no section stated |
| 4 | 0938-AN09 · 200710 | `sec 1923(a)(2)(D) of the Social Security Act` | 42 U.S.C. 1396r-4(a)(2)(D) — Table III row present (SSA's table runs to §1923, 587 rows) | chain intact; break downstream |
| 5 | 2060-AM44 · 201004 | `Clean Air Act sec 112` | 42 U.S.C. 7412 — `1955:360` row present | chain intact; break downstream |
| 6 | 0625-AA90 · 201210 | `Section 4(b) of the Steel Trade Liberalization Program Implementation Act` | Pub. L. 101-221 §4(b), 103 Stat. 1888, former 19 U.S.C. 2253 note, "Elim." — no live section exists | range key "2-6" + note-only + eliminated: the one true unresolvable |
| 7 | 1210-AB39 · 201804 | `ERISA sec. 505` | 29 U.S.C. 1135 (93-406); and the rule's previous box already says `29 U.S.C. 1135` | OLRC's "ERISA" entry is a keyless cross-reference to a string that is not itself an entry |
| 8 | 1014-AA56 · 202110 | `National Technology Transfer and Advancement Act of 1995` | NTTAA §12(d), 15 U.S.C. 272 note | no section stated; target is a note |
| 9 | 0945-AA15 · 202204 | `sec. 504 of the Rehabilitation Act of 1973` | 29 U.S.C. 794 — exact name, ordinary key 93-112, ordinary row; and the next box says `29 U.S.C. 794` | the cleanest control: everything intact at OLRC and it still failed |
| 10 | 0596-AD58 · 202304 | `General Mining Act of 1872, as amended` | 30 U.S.C. 22–54; Table III `1872:152` has empty U.S.C. columns — "R.S. Sec 2319 …" — one hop short; the next box says `17 Stat. 91 (30 U.S.C. 22-54)` | Revised-Statutes termination for pre-1926 acts |

**Two schema observations:** every row's parse SUCCEEDED (act_key and
act_section are right on all ten); only resolution failed, yet parse_status
says "failed". And the adjacency finding from review A recurs: in 3 of 10
the answer sits in the sibling box at ordinal ±1, in either order.

**Hypotheses:** H1 the index's name→law hop is broken for names that are
intact at OLRC (row 9 as control) — **tested below**; H2 chapter-style keys
dropped by a Pub. L.-shaped parser; H3 zero alias coverage and unfollowed
keyless cross-references; H4 amending act named, base section cited; H5
Table III section keys are not atomic (ranges, subsection-qualified keys,
duplicates); H6 "resolves to a note" and "Elim./Rep." are answers, not
failures; H7 pre-1926 acts need an R.S.→U.S.C. hop; H8 rule-scoped
adjacency recovers 3/10 here.

**Tested (code, on my side):** the 2026-08-22 index holds all four famous
cases — `93-112` §504 → 29 U.S.C. 794, `1935:531` §1871 → 42 U.S.C. 1395hh
(587 rows, to §1923), `1955:360` §112 → 42 U.S.C. 7412, `93-406` §505 →
29 U.S.C. 1135 — and the live resolver
(`resolve_act_relative_citation` with the pinned index and source credits)
answers all five probes, `ERISA` included through OLRC's alias, and refuses
`Clean Air Act Amendments of 1990, sec 112` with the reason
`act_section_not_classified`. The break is not downstream of the index: **the
builder never calls the resolver.** It uses the popular-name set only to
recognise an act-relative citation; no act-relative row carries a section
(9,065 rows: 6,214 "failed", 2,782 "corroborated" by RIN history, 69
partial), and "failed" means "not corroborated", not "resolution failed".
Three of review A's strings are not recognised at all because the name set
lacks year-less short names ("Atomic Energy Act"), record-defined
abbreviations ("NDAA-17") and "the Act". Queued as the bake-in: resolve at
build time with evidence and named reasons (task #32).

## E — U.S.C. sections judged absent (14,142 rows; 10 reviewed): "absent" right 10/10; corrections 3/3 true; 5 of the 7 uncorrected repairable from public data

| # | RIN · edition | filer's text | verdict on "absent" | what was meant | how known |
|---|---|---|---|---|---|
| 1, 5 | 0910-AD06 · 199604; 0910-AF52 · 200504 | `21 USC 371a` → 371(a) | right; correction true | 21 U.S.C. 371(a) "Authority to promulgate regulations" | the list is 21 CFR 330's note with letters appended; §371a never existed |
| 3 | 0910-AD17 · 199910 | `21 USC 321p` → 321(p) | right; correction true | the "new drug" definition, the OTC review's hinge | 321a–321d are the only lettered sections; when FDA normalised the list in 200804, "321p" survived |
| 2 | 0651-AA50 · 199710 | `35 USC 1123` | right; **no correction — a miss** | **15 U.S.C. 1123** (PTO rules for trademark proceedings) | the rule covers 37 CFR 1 and 2; the sibling `35 USC 6` is its patent twin; title 35 ends at §390 |
| 4 | 1190-AA49 · 200310 | `42 USC 794` | right; miss | **29 U.S.C. 794** (§504) | 28 CFR 42 subpart G's note: "29 U.S.C. 706, 794"; title carried over from two title-42 neighbours |
| 6 | 2137-AE60 · 201010 | `40 USC 5103, 60102 … 60137, 49 CFR 1.53` | right; miss | the whole list is **49 U.S.C.** — 49 CFR 192's note verbatim; "40" typed for "49" | and `40 U.S.C. 5103` (Capitol Grounds) exists, so that sibling passed silently |
| 7 | 0920-AA55 · 201404 | `31 USC 483a` | right as scoped; the oracle's blind spot | 31 U.S.C. 483a was real 1952–1982; now **31 U.S.C. 9701** (OLRC's revision note maps it) | the rescinded part's own note still read "31 U.S.C. 483a"; the sibling `31 USC 9701a` is probably 9701(a) — one real a-suffix and one lost parenthesis in one row |
| 8 | 2090-AA39 · 201604 | `42 U.S.C. 7000` | right; abstaining is right | no single section: the NPRM's note is "42 U.S.C. 2000d to 2000d-7 and 6101 et seq.; 29 U.S.C. 794; 33 U.S.C. 1251 nt" compressed into three slots | 7001–7011 is a repeal stub; 7000 never existed |
| 9 | 1904-AD26 · 201804 | `42 U.S.C. 6200 to 6317` | right; defensible | 6291–6317 (10 CFR 429/431 notes end exactly at 6317); 6200 is a template prefix that stayed fixed across editions while the end moved | |
| 10 | 3037-AA14 · 202010 | `41 U.S.C. 85` | right; miss | **chapter 85** of title 41 (Javits-Wagner-O'Day, §§8501–8506; §8502 creates the filing Committee) | 41 CFR ch. 51 notes: "41 U.S.C. 8501-8506" |

**Judgment.** Mechanisms: lost parenthesis 3 · wrong title 3 · chapter cited
as section 1 · range start not a section 1 · recodification 1 · block
stand-in 1 · oracle missing a real section 0. The pre-1994 caveat is
narrower than advertised: OLRC prints repeal stubs, so it bites only on
positive-law recodifications that erase the old numbering (titles 31, 41).
The schema has `usc_section_corrected` but no `usc_title_corrected`, so rows
2, 4 and 6 are unrepairable by construction. Note on the reviewer's
hypothesis 5 (edition-aware existence): the table already carries
`usc_section_attested_at_edition`, and the receipt counts 8,229 exists-rows
not attested at their edition — `21 USC 360a` in 1996 is in that count.

**Hypotheses, in the reviewer's priority:** the CFR-authority-note join
(again the highest yield: it resolved or bounded rows 4, 6, 7, 8, 9);
list-coherence title repair — when every element of a multi-element
citation exists under exactly one other title, propose it (cures row 6 and
is the only rule that catches the silent `40 U.S.C. 5103`); recodification
disposition tables as a pinned oracle ("former section, restated at X");
an A4 guard audit both directions plus a letter-position prior; round-number
block stand-ins (7000, 6200) never repaired at section level; chapter
cited as section.

## I — series fences (336 rows; 10 reviewed): fences right 10/10; five recover one candidate by roster alone, three need the record, one is a trap

| # | RIN · edition | filer's text | fence | truth | operator | one survivor? |
|---|---|---|---|---|---|---|
| 1 | 2040-AD59 · 200104 | `PL 92-500 76 Stat. 816` | Stat ≠ PL | 86 Stat. 816 (FWPCA 1972; page image) | volume tens digit 8→7 | yes, by roster: {85, 86} for C=92, one edit away |
| 2 | 2120-AI82 · 200710 | `449 USC 5102 to 45103` | title | **49 U.S.C. 45102–45103** (drug/alcohol testing; MU-2B SFAR) — not hazmat, as my brief guessed | a digit migrated across the token boundary | **no, by roster — a trap**: the minimal edit yields 49 U.S.C. 5102, real and wrong; the ascending list, the intact endpoint, 14 CFR 61's note, and the 200804 edition (`49 USC 45102 to 45103`) settle it |
| 3 | 3084-AA94 · 201104 | `PL 11-24, 123 Stat 1734` | congress | Pub. L. 111-24, 123 Stat. 1734 (CARD Act) | dropped digit | yes, by roster: volume 123 → Congress 111 uniquely (the other fence supplies the repair) |
| 4 | 0750-AH15 · 201110 | `410 USC 1303` | title | 41 U.S.C. 1303 (FAR Council; 48 CFR 216's note) | inserted digit | yes, by roster: 10 U.S.C. 1303 does not exist |
| 5 | 1505-AC36 · 201110 | `PL 11-203` | congress | Pub. L. 111-203 (Dodd-Frank) | dropped digit | **no, by roster** (110-203 is real too); yes by the record's abstract naming Dodd-Frank |
| 6, 10 | 1625-AA00 · 202004/202404 | `33 U.S.C. 70034` | magnitude | 46 U.S.C. 70034 (PWSA moved to title 46 in 2018; the filer updated the section, not the title; corrected by the filer in 202510) | stale title prefix after recodification | yes, by roster: §70034 exists only in title 46 |
| 7 | 0790-AJ40 · 202010 | `Pub. L. 11-84` | congress | Pub. L. 111-84 (FY2010 NDAA; SAPR) | dropped digit | **no, by roster** (110-84 … exist); yes by the list: a strictly ascending run of NDAAs places it between 110-417 and 111-383 |
| 8 | 3060-AL56 · 202304 | `Pub. L. No. 1245-46 (2021)` | congress | not a law: the Statutes pages 1245–46 of the previous box's `Pub. L. No. 117-58, 135 stat. 429` (IIJA §60506); the Legal Deadline field carries the intact citation | field split with label inheritance | zero under a public-law repair — the fix is a type change and a merge with the row above |
| 9 | 0694-AG08 · 202310 | `59 U.S.C. 4801 to 4582` | title | 50 U.S.C. 4801–4852 (ECRA; 15 CFR 774's note) | title 0→9; endpoint transposed 4852→4582 | title yes (§4801 only in 50); the endpoint is unfenced and unparsed — and the range is descending, a free check that nothing ran |

**Judgment.** No fence is wrong; keeping the value and saying False is right
in all ten, and three rows (2, 8, 9) would be misrepresented by any silent
"fix". Recoverable by roster alone: volume digit beside an intact PL;
congress digit dropped *with* a volume present; a title digit where the
section pins the title. Not by roster: a bare `PL NN-n` (needs the abstract
or ordered siblings), boundary migration (the trap), a split field. Three
observations beyond precision: the same operator lands silently where the
target number is plausible (`33 U.S.C. 1333` is false, unfenced, and the
filer corrected it to 43 U.S.C. 1333 in 202404); range endpoints are
neither parsed nor fenced (descending ranges are free to catch); and the
sibling row and the adjacent edition are the most under-used evidence in
the table — six of ten were settled by a neighbour, and the filer's own
later correction turns a plausible repair into a fact.

## H — absent and uncorrected (10,486 rows; 10 reviewed): all explainable; 9 resolve to one referent, 5 to one U.S.C. section; nothing invented

| # | RIN · edition | filer's text | what it is | mechanism | one survivor? |
|---|---|---|---|---|---|
| 1 | 2115-AE94 · 199510 | `31 USC 7306` | **46 U.S.C. 7306** (deck department exam requirements); the whole "31 USC" run except 9701 is title 46 | wrong title across a run | yes — but only as a run: siblings `31 USC 7101, 7107` exist in title 31 and are equally wrong (grant consolidation), marked *present* |
| 2 | 2115-AD66 · 199604 | `46 USC 4202` | **OPA 90 §4202(a)(6)** = 33 U.S.C. 1321(j)(6) (the 2016 final rule says so); title 46 has no 42xx at all | a public-law section in U.S.C. clothing | **no**: the digit repairs 4102 and 4302 are real, plausible, both wrong; refuse |
| 3 | 3206-AL44 · 200804 | `5 USC 532` | the row's own **5 CFR part 532** (statute 5 U.S.C. 5343/5346) | CFR part copied into the U.S.C. slot | one citation, a type change; not one section |
| 4 | 1120-AB48 · 200904 | `18 USC … 4942 …` | nothing: the note reads "4001, 4042, 4081, 4082"; 4942 is 4042 with 0→9, already in the list | adjacent-key digit producing a duplicate | no survivor — the repair is deletion |
| 5 | 1625-AA81 · 201004 | `46 USC 73` (list `21, 73, 75, 77`) | **46 U.S.C. chapter 73**, Merchant Mariners' Documents (ch. 21, 75, 77 likewise) | chapter in a section slot | one reading, a chapter (former §§71–77 were tonnage provisions repealed pre-1994 — excluded by subject) |
| 6 | 1545-BJ42 · 201104 | `26 USC 1014-5` (with `1001-1`) | **26 CFR §1.1014-5** (T.D. 9729 amends §1.1001-1 and §1.1014-5); statute 26 U.S.C. 1014 | Treasury regulation number with "1." dropped, twice in one list | yes, both ways |
| 7 | 1625-AC10 · 201510 | `46 U.S.C. 71` | **chapter 71**, Licenses and Certificates of Registry — 46 CFR 10's note with the word "chapter" stripped | chapter in a section slot | one reading |
| 8 | 0790-AK28 · 201810 | `10 U.S.C. 593` | **10 U.S.C. 12203** — 32 CFR 100's note was never renumbered after Pub. L. 103-337 (eff. Dec 1 1994); OLRC's prior-provisions note maps 593 → 12203, 597 → 12241 | stale numbering copied faithfully | yes, by table; and `510, 511` beside it now name 2002 recruiting programs, marked *present*, equally wrong |
| 9 | 0694-AH93 · 202004 | `50 U.S.C. 4801-4582` | the range **4801–4852** (ECRA; 15 CFR 740/744's notes) | transposed end; the range parsed as one section | mis-shaped, not absent: the start exists; same BIS template as fence row I-9 |
| 10 | 2506-AC52 · 202504 | `12 U.S.C. 1701-1` | **12 U.S.C. 1701x-1** (home inspection counseling); eCFR's own note reads "1701 x-1" with a stray space | dropped suffix, publisher typography the proximate cause | yes |

**Judgment.** Mechanisms: wrong universe 5 (chapter ×2, CFR part, Treasury
reg, public-law section); stale numbering 1 (+ the upstream "chapter 72"
defect inside #5's note); character slips 3; title run 1; invented numbers
0. "Absent" is never wrong for the value as parsed, but the word conflates
never-existed with left-the-Code (#8: renumbered one month inside the
oracle's floor) and two rows are mis-shaped rather than absent (#4, #9).
Safe operators with one survivor: renumbered-section lookup from OLRC
prior-provisions notes (verdict "renumbered"); suffix restoration guarded by
the row's CFR note; range anchor/repair; type reclassification U.S.C.→CFR
when the section equals the row's own CFR part or a 26 CFR 1.N-k exists;
chapter-in-section-slot as a granularity verdict. Must stay refused: #2
(two equidistant wrong repairs) and #4 (deletion). **The finding to flag
hardest:** the same run-shaped defects that produce a detectable absence
produce undetectable false presences beside it, and that population is
invisible to any review that samples only absent rows.

## F — U.S.C. sections judged unknown (2,551 rows; 10 reviewed): "unknown" honest about the archive, but a pinnable table answers all ten

All ten carry the reason `title_49_appendix_not_published`. The reviewer
confirmed it: govinfo's 1994 edition has **no appendix volume for any
title** (`USCODE-1994-title49a`, `-title11a`, `-title28a` all resolve to
the error shell). But `USCODE-1994-title49` — the positive-law main
volume enacted that year by Pub. L. 103-272 — carries in its front matter
(pp. 1–12 of the table, not 6–15 as first written here) the "Table Showing Disposition of Former Sections of Title 49",
plus per-section Historical and Revision Notes, and Pub. L. 103-272 §6(b)
deems an old citation to refer to its successor.

| # | RIN · edition | filer's text | former section | current home |
|---|---|---|---|---|
| 1 | 2120-AF70 · 199510 | `49 USC 1432` | FAA Act §612, airport operating certificates | 49 U.S.C. 44706 (and 44701/44702/44914 by subsection) |
| 2 | 2120-AF70 · 199510 | `49 USC 1652(e)` | DOT Act of 1966 §6(e), not an FAA Act section — a real, correctly targeted citation | 49 U.S.C. 106 |
| 3 | 2120-AF76 · 199510 | `49 USC 1421 to 1431` | FAA Act §§601–611 | 49 U.S.C. 44701–44711, 44715 |
| 4 | 2120-AF79 · 199510 | `49 USC 1423 to 1426` | §§603–606 | 44704, 44705, 44708, 44713 |
| 5 | 2120-AC84 · 199510 | `49 USC 1502` | §1102, international agreements | 40105 (+40101 — the table prints 40101, not 40101(e); the pinpoint was read off 40101's notes) |
| 6 | 2120-AD42 · 199510 | `49 USC 1424` | §604 | 44705 |
| 7 | 2120-AD88 · 199510 | `49 USC 1421` | §601, general safety powers | 44701 — the cleanest match |
| 8 | 2105-AB61 · 199610 | `49 USC 1374(c)` | §404(c), Air Carrier Access Act of 1986 | 41705 |
| 9 | 2125-AD32 · 199804 | `49 USC 1604(h)` | Federal Transit Act §1604 — the table says `1604, 1604a … Rep.` with no successor | **repealed 1994, no successor**: a distinct verdict |
| 10 | 2120-AI20 · 200404 | `49 USC 1510` | §1110 | 40120 — the same FAA boilerplate, unedited, nine years after the sections stopped being current law |

**Judgment.** All ten resolve by a closed, authoritative, public document
— nine to a current section ("exists-as-recodified, now §X"), one to
"repealed without successor", which deserves its own reason code rather
than "unknown". 2,548 of the 2,551 unknown rows carry this reason; the
table is the oracle that routes around the unpublished appendix.

## Synthesis — what the nine reviews say about "how many malformed identifiers remain"

| class | population | sample verdict on the label | what a human settles | the lever |
|---|---:|---|---|---|
| A unreadable | 2,960 | wrong 10/10 | 10/10 recoverable | join the boxes; carry the title; widen the lexicon (#31) |
| B act-relative unresolved | 6,214 | "failed" is not resolution failure — the table never asks | 7/10 to a section, 2 to an act, 1 truly unresolvable | bake Table III resolution in (#32, running) |
| C placeholders | 12,467 | right 10/10 | not malformed | read the 52 "LEGAL AUTHORITY CONT" continuations (#29) |
| D timetable FR refused | 8 | right 8/8 | 8/8 to one document | pinned FR metadata, one survivor each (#30) |
| E section absent | 14,142 | right 10/10; corrections 3/3 true | 7/10 to one section; 5 of 7 uncorrected repairable | title repair, chapter/CFR/regulation reclassification (#34); disposition tables (#35) |
| F section unknown | 2,551 | honest; answerable | 10/10 | the 1994 Title 49 disposition table (#35) |
| G corrected, one survivor | 5,255 | A4 8/8 true; B8 1/2 | — | B8 → candidate; enumerate hyphenated tails (#33, running) |
| H absent, uncorrected | 10,486 | right 10/10 as parsed | 9/10 to one referent, 5 to one section; 0 invented | namespace verdicts (#34), renumbering (#35) |
| I series fences | 336 | right 10/10 | 5 by roster alone; 3 by the record; 1 a trap; 1 a split field | roster repairs, descending ranges, the filer's later edition (#36) |

**Cross-cutting findings, each seen in at least three classes:**
1. **The filer's record carries its own answer key.** The sibling box
   (ordinal ±1), the rule's CFR part authority note, the abstract, the
   Legal Deadline text, and the same RIN in a later edition settled most
   rows in A, B, E, H and I. None of those sources is read today except
   RIN history.
2. **Wrong universe beats wrong digit.** Chapters, CFR parts, Treasury
   regulations, public-law sections and disposition-table ghosts wear
   U.S.C. clothing; the schema cannot express the fix (no title
   correction, no namespace verdict), so those rows are unrepairable by
   construction, not by evidence.
3. **The fences are loud where the damage lands loudly and silent where
   it lands on a plausible number** (`33 U.S.C. 1333`; `31 USC 7101`;
   `10 U.S.C. 510`): false presences beside detectable absences, probably
   more numerous, invisible to an absent-only sample (#37).
4. **Recovered is not correct.** A recovered page can be the wrong page
   (113 Stat. 1754 vs 1765); a minimal-edit repair can be a real wrong
   section (`49 U.S.C. 5102`; `1735f`). The doctrine held: every wrong
   value found was a guess dressed as a survivor.
5. **Nothing in 88 examined rows was invented by a filer.** Every
   malformed value is damage to a real citation — chopped, elided,
   mistyped, stale, or in the wrong namespace — which is why the labels
   ("unreadable", "unresolved", "absent") overstate what is lost.
