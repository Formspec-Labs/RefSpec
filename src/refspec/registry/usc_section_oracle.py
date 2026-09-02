"""Does U.S.C. title T section S exist, and when — asked of a pinned oracle.

Nothing in this repository fenced a U.S.C. *section*. ``usc_title_is_possible``
fences the title and returns ``true`` for every citation to a section that was
never printed, so a wrong section arrives typed ``ok`` and no count surfaces
it. The silent-misreads campaign measured what that costs: **about 7% of rows
that produced a citation produced the wrong one** (11/150, Wilson CI
4.1%–12.7%) against a 0.37% loud-refusal rate, and **section non-existence is
the single dominant mechanism** — a third of every adjudicated misread
(``research/evidence/silent-misreads-2026-08-22.md``). This module is the
fence, read from the oracle that leg built and pinned
(``research/evidence/usc-section-oracle-2026-08-22.md`` and its README) and
re-cut on 2026-08-24 with the annual extractor's case-sensitivity fixed
(``research/evidence/usc-section-oracle-2026-08-24/README.md``, the directory
:data:`USC_SECTION_ORACLE_ARTIFACT` names). Generation 1 read its archive
members with a case-SENSITIVE matcher and OLRC spells twelve of them
``2010USC12.htm`` / ``2012USC33.htm``, so twelve title volumes were skipped in
silence and twelve ``(title, year)`` pairs got no annual coverage at all.

What the oracle is
------------------
Two OLRC sources, first downloaded 2026-08-22 and re-fetched byte-identical on
2026-08-24 (32 of 32 digests match), digested in the artifact's README and
reproduced row-for-row from those sources:

* **release point 119-102, USLM XML** —
  ``https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_uscAll@119-102.zip``
  (108,610,077 bytes): 59,362 distinct ``(title, section)``, 50,957 live plus
  **8,405 stubs** carrying
  ``repealed|omitted|transferred|renumbered|vacant|reserved``, 1,751 range
  stubs, 160,209 ``(title, section, subsection)`` and 2,905 ``(title, chapter)``.
* **annual historical archives, XHTML, every year 1994–2024** —
  ``https://uscode.house.gov/download/annualhistoricalarchives/XHTML/2024.zip``
  and its thirty siblings, one per year: 66,007 distinct non-appendix
  ``(title, section)``, 1,015 appendix ones, 49,960 year-scoped range stubs.
  **Every year and every title volume in it**: 1,835 archive members
  classified, 1,781 matched as title volumes, and the other 54 named
  individually (the year index, ``usc.css``, the Popular Names table, Tables
  1–6, and the 2011 archive's two Congress cross-reference tables) — a member
  that matches neither list raises rather than being skipped. Generation 1
  matched 1,769 and skipped twelve without a word; recovering them added
  7,218 annual section rows and 137 range rows and moved the coverage matrix
  from 1,642 ``(title, appendix, year)`` pairs to **1,654** — (12, 13, 14, 51)
  at 2010 and (33, 35–41) at 2012, gained, none lost.

The 32 source zips are **not committed** — they are 2.3 GB — but generation 2
retains them on disk under ``output/usc-annual-2026-08-24/`` rather than
deleting them the way generation 1 did. The oracle report's README carries a
re-fetch digest and byte length for every one, and a row-for-row reproduction
check of all six derived tables against them. What this module
reads is those derived tables, pinned in :data:`_ORACLE_PINS` and re-checked
**all six together** by :meth:`UscSectionOracle.verify`, which
:meth:`UscSectionOracle.from_directory` calls before the first question —
because the tables load lazily and a caller who asks one of them
authenticates one of them.

**The annual half attests what OLRC printed as LIVE LAW at that edition, and
that is a narrower thing than "a heading with this number appears somewhere in
the volume."** OLRC prints a withdrawn section as a placeholder so a reader
who looks the number up finds out what happened to it, and it marks those
placeholders in two different ways that this oracle treats differently:

* an **unbracketed** stub — ``§§3, 4. Omitted``, ``§§41, 42. Repealed. Pub. L.
  104-186 …`` — is kept, as a section or a range exactly as printed. The 2012
  volumes alone carry 1,544 unbracketed ``repealedhead`` and 596
  ``omittedhead`` multi-section blocks, and every one is in the tables;
* a **bracketed** stub — ``[§322. Repealed. Pub. L. 109-313 …]``,
  ``[§§1 to 5. Repealed. …]``, ``[§11704. Renumbered §11703]`` — is **not**.
  33,895 annual rows and 4,450 range rows over 1994–2024 are bracketed, 33,848
  of the section rows reaching no other year or form.

The bracket is not this module's convention; it is the publisher's own, and
OLRC states it in metadata rather than typography alone. Every entry carries a
``usckey`` beside its ``itempath``, and for a bracketed heading the section
field of that key is **zeroed**: ``40_[322`` gets
``usckey:400000000000000000000000000000000`` where the live §323 beside it gets
``usckey:400000000032300000000000000000000``. Measured over all 31 archives,
that holds without exception — **35,088 of 35,088** non-appendix bracketed
entries carry a zeroed section field, against 1,585,628 unbracketed entries
that carry a real one. The publisher declines to mint a Code identity for a
bracketed heading, and the extractor follows it.

What the exclusion costs, named rather than hidden: **40 U.S.C. 322 at edition
2012** reads ``attested_at_edition = false`` although the 2012 volume does
print ``[§322. Repealed …]``. The section still reads ``exists`` — the release
point carries it with ``status='repealed'`` and the 1994–2005 archives print it
unbracketed — so only the year-scoped question is affected. Across the whole
rebuild-#12 build the exclusion holds 3,085 rows at ``false`` that admitting
brackets would flip to ``true`` (2,280 from the section rows, 805 from the
ranges).

What the exclusion buys is the reason it stands. Admitting bracketed **ranges**
moves 19 rows from ``absent`` to ``exists``, and all 19 are one pair: **6 U.S.C.
1**, whose only witness anywhere is ``[§§1 to 5. Repealed. Pub. L. 92-310 …
June 6, 1972]`` printed 1994–2001 under ``TITLE 6-SURETY BONDS [REPEALED]``.
The rows filing it are 2005–2017 and say what they mean —
``PL 107-296, 116 Stat 2135 (6 USC 1 et seq)`` is the Homeland Security Act,
classified from **6 U.S.C. 101** in the Title 6 that replaced Surety Bonds
entirely. Calling those ``exists`` on a 1972 repeal stub from an abolished
title would manufacture the silent misread this module is the fence against,
and would delete the honest hedge they carry today
(:data:`ABSENT_CAVEATS`, ``repealed_before_1994_not_stubbed``, which is exactly
their situation). :meth:`UscSectionOracle.disposition` does not catch it
either — title 6 has no recodification table at all
(``verdict='no-table-for-title'``). See the artifact README's
"Bracketed stubs" section for the follow-up this defers: a THIRD state for
"printed as a withdrawn placeholder at this edition", which is the honest fix
and is a column's worth of schema work in ``unified_agenda_parquet``, not a
widening of ``attested_at_edition`` — widening it is what produces the 19.

Union used as the existence test: **66,780 distinct non-appendix
(title, section)**, spanning every agenda edition in the corpus
(1995-10 … 2025-10). Admitting bracketed stubs would make it 67,105 and the
annual key count 67,763; both are consequences of the paragraph above, not
accidents of it.

**The twelve recovered volumes moved that union by nothing, and that is the
whole blast radius.** 66,780 in both generations, 67,022 distinct annual
``(title, appendix, section)`` in both, and the annual range table's DISTINCT
span set identical in both directions (only the year labels on those spans
multiply, +137) — so ``section_is_enumerated`` and ``section_exists`` cannot
have moved, and neither can a :attr:`SectionVerdict.verdict`. No section
appears only in a skipped volume. What moves is
:attr:`SectionVerdict.attested_at_edition`, the year-scoped question, on rows
whose citing edition IS one of the twelve: recomputed over all 694,062 rows of
the rebuild-#12 build that carry a ``(title, section)``, **1,898 rows move
``False`` → ``True``, none move any other way, and no verdict moves at all**
(1,882 typed ``usc``, 22.8% of that build's 8,261 ``exists`` /
``attested_at_edition = false`` rows, over 390 pairs and 538 RINs, title 12 at
edition 2010 alone 1,368; plus the 16 ``act_relative`` CWA rows of RINs
2040-AE69 and 2040-AE95 at edition 201210). The 30 rows the investigation's
hand-bucketing marked ``2-case-bug-uncertain`` do **not** move, and must not:
they are titles 40 and 41 at 2012 cited by their pre-recodification numbers
(40 U.S.C. 276c, 322, 333, 484, 486; 41 U.S.C. 46, 253, 414, 418b, 421–423,
431, 701), and the recovered 2012 volumes print §101 and §3141, not those. The
volume existing and the section existing are different facts.

The rules, and the measurement that bought each
-----------------------------------------------
**Dashes are normalised before every lookup.** OLRC identifiers spell the dash
in a compound section name as U+2013 (``/us/usc/t42/s1395w–4``); the corpus
uses ASCII hyphen. The oracle's first extraction reported ``42 U.S.C. 1395w-4``
and ``300gg-11`` MISSING — the whole Medicare/ACA/SDWA compound-name family
would have been published as nonexistent. The grammar's ``_DASHES`` table is
restated here (:data:`_DASHES`) rather than imported, the way
:mod:`refspec.registry.act_resolution` restates the rkaf lexical space, and
``test_the_dash_table_is_the_grammars_verbatim`` holds the copy true.

**Range stubs judge, they never propose.** A stub printed ``§§ 6 to 15a``
admits any token whose ``(leading digits, remainder)`` key sorts inside it,
which is right for judging a parsed section and far too loose for proposing a
candidate: it admits ``36o0`` as a title-42 section and produced a **110-pair
false-positive class** until candidate generation was restricted to the exact
sets. :meth:`UscSectionOracle.section_exists` consults ranges;
:meth:`UscSectionOracle.section_is_enumerated`, the near-miss generator and
every correction do not.

**An absence is only as wide as the oracle's window.** ``absent`` means
"printed in no edition the oracle covers, 1994–2026". It does **not** mean
"never existed": a section repealed before the 1994 edition and not stubbed in
the release point is invisible here. **18 U.S.C. 3568** is the specimen — a
real section repealed by the Sentencing Reform Act effective 1987-11-01, still
cited deliberately for pre-1987 conduct in 182 rows across 14 RINs, and
indistinguishable from a misread by this oracle alone. That gap is
undetectable per section, so making it an ``unknown`` verdict would make every
absence unknown and delete the finding; it is carried instead as
:data:`ABSENT_CAVEATS`, attached to **every** ``absent`` verdict by
``__post_init__`` so no consumer can read one without it.

**Where the oracle's coverage is structurally missing, the verdict is unknown
and names the gap** (:data:`UNKNOWN_REASONS`) — never ``absent``:

* ``title_49_appendix_not_published`` — no ``usc49a.htm`` exists in *any* OLRC
  annual archive year, so the pre-1996 Title 49 Appendix (old Federal Aviation
  Act / ICC Act numbering) is uncovered. 111 pairs / 189 texts / **1,969 rows**
  rest on the corpus's own temporal evidence — the same 113 RINs cite
  ``49 USC 1354`` in 1995-10 and switch to ``49 U.S.C. 40113`` from 1996-04 —
  not on a publisher inventory.
* ``appendix_title_not_published`` — an appendix citation in a title with no
  appendix file in any archive year (anything outside
  :data:`APPENDIX_TITLES_PUBLISHED`). 33 pairs / 269 rows.
* ``subsection_structure_not_published`` — the subsection oracle comes from
  the **current release point, non-appendix titles only**, so it cannot see
  the subsections of a section the Code has since transferred. ``16 USC 462k``
  (49 rows) is almost certainly 16 U.S.C. 462(k), but § 462 moved to title 54
  in 2014, so its subsections are not extractable and the correction refuses.
* ``edition_outside_oracle_window`` — an edition year outside 1994–2026.

**An unknown the recodification answered still says unknown, and now says what
became of the section.** The largest of those holes is closed, as a fact
*beside* the verdict and never as a change to it:
:mod:`refspec.registry.usc_disposition_tables` reads the printed "TABLE SHOWING
DISPOSITION OF FORMER SECTIONS OF TITLE 49" from the 1994 volume, and
:attr:`SectionVerdict.disposition` carries its answer on every verdict whose
reason is ``title_49_appendix_not_published`` — 2,371 of the pinned build's
2,548 such rows resolved, 177 not listed. The verdict stays ``unknown`` and the
reason stays intact, because both are still true: **no archive year publishes
that appendix**, and no rebuild of this oracle changes that. What the table adds
is a different question's answer — Pub. L. 103-272 § 6(b) deems a citation to a
former section to refer to its successor — and the two must not be confused.
Nothing is corrected from it: on 62 of the 146 sections the table names
**several** successors, separated only by printed prose, so they are candidates
and never an identity (:attr:`Disposition.successors` returns all of them). The
attachment is the same doctrine :data:`CANDIDATE_ONLY_RULES` applies to B8,
reached before a column existed to be wrong.

**The edition year narrows, it never accuses.** A citation filed in a 1996
edition is judged against what the Code printed then, which is why
``21 USC 134a to 134d`` — real animal-quarantine sections until their 2002
repeal, every citing row predating it — reads ``exists``. The reverse
direction is refused: a section the 2023 archive lacks and the 2024 archive
prints is **not** called absent at edition 2023, because the archives lag
enactment. An edition-scoped absence is published as
:attr:`SectionVerdict.attested_at_edition` ``= False`` beside a ``verdict`` of
``exists``, and the verdict itself stays window-wide.

**Two readings, and a correction only when one survives.** The ``NNN(x)`` /
``NNNx`` pair runs in *both* directions inside one corpus — ``300(f)`` means
300f (class B1) and ``371a`` means 371(a) (class A4) — so shape cannot decide
and only the oracle can. :meth:`UscSectionOracle.correction_candidates` emits
**every** reading the oracle affirms, including the parse as filed;
:meth:`UscSectionOracle.corrected_section` publishes one only when exactly one
survives. That is what keeps ``5 USC 552(a)`` (FOIA subsection (a) *and* the
Privacy Act at 552a, both real) and ``42 USC 2139(a)`` (387 rows, 115 RINs;
2139 has a subsection (a) and 2139a exists) refused rather than adjudicated —
the report's own honest unknowns, and the ~29,557-row surface behind them.

**And surviving alone is not enough: B8 is a candidate, A4 and B1 are
corrections.** A rule may publish only where its own inputs — the section
token, the authority text, the oracle — can tell a right reading from a wrong
one. The human review of 2026-08-23
(``research/evidence/sample-review-2026-08-23/review.md`` § G, ten rows read
against the publisher's own pages) measured A4 8/8 true and B8 1/2, and the
half it got right it got right for a reason B8 cannot see:

* ``15 U.S.C. 18(a)`` in the FTC premerger rule IS 18a. What says so is the
  rule's **abstract** ("section 7(A) of the Clayton Act, codified at 15 U.S.C.
  18(a)") and the **CFR parts' authority note** (16 CFR 801/803: "15 U.S.C.
  18a(d)"). 15 U.S.C. 18 and 18a are both real sections; no question this
  module can put to the oracle separates them, and a consumer measured that
  keying on the B8 result *loses* tags on correct citations of § 18.
* ``12 USC 1735(f)-14`` (RIN 2501-AC95, HUD mortgagee civil penalties) was
  published as 1735f — "Water and sewerage facilities" — because the candidate
  generator truncated the stated tail and could not reach 1735f-14 at all. The
  truncation MANUFACTURED the single survivor. That defect is fixed (the
  stated tail is enumerated first), and it is the reason the demotion is not
  merely cautious: the family where parentheses go astray is the same family
  where two real sections sit one hyphen apart.

A4 keeps publishing because it never relocates a citation: ``371a`` → 371(a)
keeps the identity 371 and adds a pinpoint, so an identity-keyed consumer is
right either way. B1 keeps publishing because "subsection (f) and following"
is not a citation form anyone writes, which is a fact about the text in front
of it. B8's truth is not in front of it, so it names its reading — with
"the lettered section exists; the bare section has no such lettered
subsection" as the evidence — and picks nothing. The flag is
:attr:`Candidate.corrects`, driven by :data:`CANDIDATE_ONLY_RULES`, and
:class:`Correction` refuses to be constructed with a B8 rule at all.

**A SECOND NUMBERING SYSTEM VOIDS A4'S LICENCE, and the 8/8 is 8/8 of ten
FDA rows.** That licence — "it never relocates" — held on every row the first
review read, and visual review #2 found the family where it is false
(``research/evidence/review2-2026-08-23/review.md`` § H, twenty class-H rows
read in full against the publisher's own pages). ``7 USC 8a(5)``, filed by the
CFTC on RIN 3038-AD31, was published as 7 U.S.C. **8(a)** — a real section
(applications for designation as a contract market) carrying a real subsection
(a), so A4's structural test was factually true and nothing downstream could
see it happen. But ``8a`` is the **Commodity Exchange Act's own section
number**. OLRC's Table III classifies act §8a to 7 U.S.C. **12a**, whose
printed source credit says so verbatim — "(Sept. 21, 1922, ch. 369, §8a, as
added June 15, 1936, ch. 545, §10, 49 Stat. 1500 …)" — and §12a(5), "to make
and promulgate such rules and regulations as, in the judgment of the
Commission, are reasonably necessary", is the general rulemaking authority a
CFTC reporting-forms rule cites. §8(a) is contract-market applications and is
not. Eight rows across two RINs (3038-AD31 ×5, 3038-AB50 ×3) were relocated
silently, which is the B8 hazard — a really-existing section that is the wrong
referent — firing inside A4's own rule.

So A4 is **fenced** where a second numbering system claims the token, and the
witness is the same pinned OLRC act index
:mod:`refspec.registry.act_resolution` already reads. A claim
(:class:`ActSectionClaim`) counts only when the act is on the row's OWN roster
— the RIN's resolved acts, then the filing agency's, never the corpus's, for
the reason wave 5 measured — and only when its Table III classification is a
DIFFERENT section of the same title that this oracle **enumerates**. Where the
fence fires, A4's reading is kept, named, and struck (:attr:`Candidate.fenced_by`);
where exactly one enumerated target survives, ``act-section-under-a-usc-label``
publishes it, pinpoint and all (``8a(5)`` → 12a, ``(5)``); where two survive it
refuses to candidates. The agency fence is load-bearing, not decoration:
corpus-wide TWO acts number a §8a into title 7 — the Commodity Exchange Act
(→ 12a) and the A.A.A. Farm Relief and Inflation Act (→ 608a) — and only the
CFTC's own roster separates them.

**The fence reaches exactly as far as A4 does, on purpose.** Measured over the
3,659 A4-corrected rows of the pinned build (75 distinct ``(title, token)``
pairs): **one** pair is an associated act's own section number pointing
elsewhere in the same title, and it is ``7 USC 8a`` — 8 rows. The FDA family
that made A4's name is untouched, and not by luck: no act in the 15,189-key
index numbers a §321p at all, and the one that numbers a §371a classifies it
into title 42, not 21 (3,349 rows, unmoved).

The whole surface an associated claim can touch, measured over rebuild #9, is
537 rows in A4's own ``digits+letters`` shape, and it splits four ways:

* **8 rows / 1 pair — fenced, and this unit.** ``7 USC 8a``.
* **416 rows / 4 pairs — the fence is silent because the parse as filed has a
  witness.** ``7 U.S.C. 6c`` is both the Code's own §6c and the Act's §6c
  (→ 13a-1); A4 and parse-as-filed already refuse each other there and a third
  reading decides nothing. Same doctrine, same words, as the lost-space rule:
  two real numbering systems, one string, and nothing here tells them apart.
* **48 rows / 2 pairs — the token is a printed section and A4 never fired.**
  ``7 U.S.C. 4a``, ``42 U.S.C. 658a``.
* **65 rows / 12 pairs — DELIBERATELY NOT REACHED.** ``7 U.S.C. 4c``, ``4f``,
  ``4g``, ``4i``, ``4m``, ``4n``, ``4r``, ``4s`` (CEA §4x → 7 U.S.C. 6x),
  ``15 U.S.C. 10b``, ``15 U.S.C. 206a``, ``21 U.S.C. 745a``, ``42 U.S.C.
  330f``. Each is an associated act's own number and the Code prints no such
  section — but each wears a token A4 never read, so this module publishes
  NOTHING for them today. Where nothing is published, a missing reading is a
  missed witness and not a wrong value; that is a different question with a
  different evidence burden, and this fence, which exists to revoke A4's
  licence, has no business answering it.

**An index of acts is not a roster of the Code.** ``citation_grammar`` refuses
to repair the lost-hyphen family (14 tokens, 75 source rows) because the only
U.S.C. roster that module can reach is an ACT INDEX: every section some named
act contributed, and *nothing at all* about the sections no indexed act
touched. Non-membership there is silence, and exactly-one-survivor against a
silence mints a real section the citation does not mean, confidently. That is
a property of what the artifact IS and no rebuild repairs it — the default
:data:`refspec.registry.act_resolution.USC_ACT_INDEX_ARTIFACT` has since moved
from a 24-act build to a 15,189-key one that *does* hold ``15 U.S.C. 80b-11``,
and the refusal is unchanged, because the next lost hyphen will land on a
section no act in the index names.

What reopens the question is a roster of the **Code**, which is what this
module reads: :meth:`UscSectionOracle.recovered_lost_hyphen_sections` closes
**2 of the 14** tokens and reaches no candidate at all for the other 12,
because a named operator with one surviving target is the whole licence.

**The range tables are sorted, not scanned.** ``annual_ranges`` holds 49,960
year-scoped stubs, unevenly split across 31 ``(title, appendix)`` buckets --
title 42 alone carries 7,979 in one bucket -- and
:meth:`UscSectionOracle.attested_years` used to
walk every span in a title's bucket on every call, whether or not any of
them mattered: 12.2M span comparisons over 95,492 distinct
``(title, section, appendix, year)`` keys the pinned corpus files, 8.8 s of
it (measured at generation 1; the twelve recovered volumes add 137 stubs to
two of the 31 buckets and move that figure by under half a percent).
:class:`_SpanIndex` sorts each bucket once, lazily, and answers "does
nothing match" (the common case) in O(log n) without touching a span, via a
running maximum of each span's high endpoint: 0.26 s over the same keys,
about 34x, with an identical result on every one
(``test_attested_years_index_matches_the_old_linear_scan_on_every_corpus_key``,
which keeps the old linear scan as a test-only reference rather than
deleting it, per this repository's rule for replacing a running check).
``section_exists`` and ``section_verdict``'s release-point-range check carry
the identical shape and read the identical index.

Every count in ``tests/test_usc_section_oracle.py`` is measured over
``agenda-legal-authorities-as-measured-797170.parquet``, the 797,170-row build
this oracle was joined to, read by digest. That snapshot stays in the
**generation 1** directory when :data:`USC_SECTION_ORACLE_ARTIFACT` moves: it
is a measurement of the corpus, not a table of the Code, and generation 2 is
not a re-measurement of the corpus. Copying it would mint a second set of
identical bytes and invite the two to drift.
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cached_property
from itertools import accumulate
from pathlib import Path
from string import ascii_lowercase

from refspec.registry.citation_grammar import _abbreviated_span, usc_title_is_possible
from refspec.registry.usc_disposition_tables import Disposition, UscDispositionTables

__all__ = [
    "ABSENT_CAVEATS",
    "ACT_ASSOCIATIONS",
    "APPENDIX_TITLES_PUBLISHED",
    "CANDIDATE_ONLY_RULES",
    "CORRECTION_RULES",
    "DISPOSITION_REASON",
    "MISS_CLASSES",
    "ORACLE_ANNUAL_YEARS",
    "ORACLE_RELEASE_POINT",
    "ORACLE_WINDOW",
    "UNKNOWN_REASONS",
    "USC_SECTION_ORACLE_ARTIFACT",
    "VERDICTS",
    "ActSectionClaim",
    "Candidate",
    "Correction",
    "MissClass",
    "NearMiss",
    "SectionVerdict",
    "SubsectionVerdict",
    "UscSectionOracle",
    "normalize_section",
]

#: The sealed artifact, relative to the repository root, with the digest of
#: every table a loader reads. Flat table -> digest, unlike
#: :mod:`refspec.registry.act_resolution`'s artifact-keyed map: two act-index
#: artifacts there state the same table names, and one map could not hold two
#: digests for one name. Here there is one artifact, so the extra level would
#: be structure with nothing to tell apart. The digests restate the artifact
#: README's Files table on purpose — reading the pin *from* the README beside
#: the tables would authenticate a swapped directory against its own paperwork.
USC_SECTION_ORACLE_ARTIFACT = "research/evidence/usc-section-oracle-2026-08-24"
_ORACLE_PINS: Mapping[str, str] = {
    "usc-oracle-sections.parquet": "sha256:bbb450afb00cc7a28e2fcab7943d47207e8c1899f1e83209bd92d893fe39daac",
    "usc-oracle-ranges.parquet": "sha256:070226e36d324a15226bd84ce9f5e4a297b43ff83365dba37ed281d3186cd736",
    "usc-oracle-annual-sections.parquet": "sha256:4757327d2bbcd5258d0fc51f0658df7fc9999c21d5a40dbe0c2d466cf25e7323",
    "usc-oracle-annual-ranges.parquet": "sha256:c8cd96e1d13e4f429e1024f3a9fe25b8527036eae0adfd9ad29d9656522b43a3",
    "usc-oracle-subsections.parquet": "sha256:d7502945223eed92bdeb65e6a73cf52240febefe9814180675fc4df512cd08ed",
    "usc-oracle-chapters.parquet": "sha256:031ae7f3435f7ba2969bdf2c94b699170a63fe3183dd289ca23fa0ce45e90cb3",
}

#: The OLRC release point the current-code half was cut from, and the years the
#: annual half covers. Nothing between them is interpolated: 2025 has no annual
#: archive, so an edition filed in 2025 is judged against the release point.
ORACLE_RELEASE_POINT = "119-102"
ORACLE_ANNUAL_YEARS = (1994, 2024)
#: The whole window an ``absent`` verdict speaks for. The upper bound is the
#: release point's own date (title files dated 2026-07-23).
ORACLE_WINDOW = (1994, 2026)

#: The ten titles with an appendix file in some annual archive year
#: (``YYYYuscNNa.htm``). **49 is not one of them** — no ``usc49a.htm`` exists
#: in any year — which is the whole of class C5 and most of class C9.
APPENDIX_TITLES_PUBLISHED = frozenset({5, 10, 11, 18, 26, 28, 38, 40, 46, 50})

VERDICTS = ("exists", "absent", "unknown")

#: Why the oracle cannot speak. Each is a coverage hole the oracle report
#: states, not a property of the section: a consumer counts these and must
#: never read one as evidence either way.
UNKNOWN_REASONS = (
    "edition_outside_oracle_window",
    "title_49_appendix_not_published",
    "appendix_title_not_published",
    "subsection_structure_not_published",
)

#: The ONE coverage hole a pinned recodification table can speak into, named
#: once so :attr:`SectionVerdict.disposition`'s writer and its invariant read
#: the same constant. The other three reasons have no such table: an appendix
#: title outside :data:`APPENDIX_TITLES_PUBLISHED` is not a recodification, a
#: missing subsection tree is a shape and not a move, and an out-of-window
#: edition asks nothing about a section at all.
DISPOSITION_REASON = "title_49_appendix_not_published"

#: What an ``absent`` verdict does NOT exclude, attached to every one of them.
#: See the module docstring: 18 U.S.C. 3568 is the specimen.
ABSENT_CAVEATS = ("repealed_before_1994_not_stubbed",)

#: The triage classes, in the report's precedence order; a pair takes the first
#: whose predicate fires. C4 is in the chain and **fires on nothing** in the
#: pinned build: the date-year phantom (``18 USC 1987`` read out of "November
#: 1, 1987") was fixed at ``f05791de`` and the 995 rows carrying it left the
#: artifact in the mid-campaign rebuild. It is kept because a regression there
#: is silent by construction, and a class measuring zero is the only thing that
#: can say so.
MISS_CLASSES = (
    "C0 title-impossible",
    "C1 zero-padded",
    "C2 subsection-as-section",
    "C3 paren-suffix-eaten",
    "C4 date-year-as-section",
    "C5 appendix-out-of-oracle",
    "C6 appendix-miss",
    "C7 chapter-as-section",
    "C8 hyphen-part-dropped",
    "C8b letter-o-as-zero",
    "C8c inverted-range-kept-whole",
    "C8d abbreviated-span-kept-whole",
    "C9 title-49-pre-1996",
    "C10 unique-near-miss",
    "C11 corroborated-near-miss",
    "C12 unresolved",
)

#: Every reading this module will publish, including the one that says the
#: parse as filed still stands. ``parse-as-filed`` is here so that "the parser
#: was right" is a *survivor* able to outvote a proposal, rather than a silence
#: that cannot. Only a reading that survives alone becomes a
#: :class:`Correction`.
CORRECTION_RULES = (
    "parse-as-filed",
    #: B1. "et seq." follows a section, never a subsection, so ``NNN(x) et
    #: seq`` names the lettered section. 18 texts / 146 rows, 18/18 on
    #: inspection. It is the one rule that *removes* the as-filed reading:
    #: "subsection (f) and following" is not a citation form anyone writes.
    "B1-et-seq-follows-a-section",
    #: B8. The lettered-section reading of ``NNN(x)``. It fires only where the
    #: release point prints NO lettered subsection on NNN at all, which makes
    #: the pinpoint impossible as written — 42 U.S.C. 1395 alone is 30 texts /
    #: 205 rows / 45 RINs. Where the text states a tail — ``12 USC
    #: 1735(f)-14`` — the reading is the hyphenated lettered section
    #: (1735f-14), not the bare one. **A CANDIDATE, NEVER A CORRECTION**
    #: (:data:`CANDIDATE_ONLY_RULES`): which of two real sections a filer meant
    #: is settled outside this rule's inputs.
    "B8-lettered-section-rather-than-a-pinpoint",
    #: A4. The mirror: a lettered section that is really a subsection.
    #: ``21 USC 371a`` for 371(a) is 1,545 rows / 138 RINs, the largest
    #: confirmed specimen in the campaign. **Fenced since 2026-08-24** where an
    #: act on the row's own roster numbers the token itself: see
    #: :class:`ActSectionClaim` and the module docstring on 7 U.S.C. 8a.
    "A4-subsection-rendered-as-a-lettered-section",
    #: The Act's own section number, written under a U.S.C. label. ``7 USC
    #: 8a(5)`` is Commodity Exchange Act §8a(5), which the Code prints at
    #: 7 U.S.C. 12a(5) — not a lost parenthesis on 7 U.S.C. 8. It fires ONLY
    #: where A4 would otherwise have published (that is where a wrong value is
    #: published today) and only on an act the row's own RIN or agency roster
    #: holds; it takes the pinpoint the text states, because Table III
    #: classifies the WHOLE act section to one Code section and the paragraph
    #: numbering carries with it. 8 rows / 2 RINs in the pinned build.
    "act-section-under-a-usc-label",
    #: The lost hyphen the grammar refuses to guess: ``80bll(a)`` for
    #: 15 U.S.C. 80b-11(a), with the digit 1 typed as l, I or i.
    "lost-hyphen-with-one-typed-as-a-letter",
    #: The lost SPACE, the hyphen rule's mirror: ``15 USC 78 o-10`` for
    #: 15 U.S.C. 78o-10. A section's name never contains a space, so a space
    #: between a section's digits and its letter suffix is a named damage
    #: operator with exactly one repair -- delete it -- and the grammar, which
    #: cannot consult this module, publishes the digits alone and leaves the
    #: letters as uncovered text. See :meth:`correction_candidates` for the two
    #: witnesses it takes and the refusal it makes legible.
    #:
    #: Named "space-lost" and not "lost-space" for a reason that is not taste.
    #: Both this module's refusal census and the builder's short-name a rule by
    #: its FIRST dash-token, so "lost-space" and "lost-hyphen" would share the
    #: key "lost" and two different readings would be counted as one. The
    #: distinctness is a test, not a convention.
    "space-lost-before-a-lettered-suffix",
)

#: Rules that NAME a reading and never publish it. A rule belongs here when its
#: truth depends on evidence outside its own inputs, so nothing it can consult
#: could tell a right answer from a wrong one.
#:
#: * ``parse-as-filed`` proposes nothing — it is the reading the grammar
#:   already published, present so that "the parser was right" can outvote a
#:   proposal instead of being a silence that cannot.
#: * ``B8`` was demoted on 2026-08-23. See the module docstring: 15 U.S.C. 18
#:   vs 18a is settled by the rule's abstract and 16 CFR parts 801/803, and
#:   both readings are real sections, so no oracle question separates them.
#:
#: :meth:`UscSectionOracle.corrected_section` publishes nothing named here, and
#: :class:`Correction` cannot be constructed with one of these rules at all, so
#: a future caller cannot re-promote B8 by accident WITHIN this module.
#:
#: **2026-09-01: a DIFFERENT module publishes a NARROWER subset, on evidence
#: this one has never seen.** ``inv-b8``
#: (``research/investigations-mined-2026-08-31.md``) measured B8's silent
#: cost -- 14,740 readings, the largest class either 2026-08-2[34] survey
#: found -- and asked for a two-witness enlargement rather than a
#: re-promotion: :func:`refspec.registry.unified_agenda_parquet._promote_two_witness_b8`
#: reads the SAME :class:`Candidate` this module names for B8 and never
#: constructs a :class:`Correction` from it -- this module's own refusal is
#: unchanged, and the guarantee above still holds inside it -- but publishes
#: ``usc_section_corrected_section`` directly where a SECOND, corpus-level
#: witness this oracle cannot ask for corroborates it: the filing rule's own
#: held CFR authority note, or the filing RIN's own other editions. Both are
#: exactly the kind of fact the FTC review above named as missing --
#: "nothing this module can put to the oracle separates them" -- read from
#: OUTSIDE it instead. See that function's docstring for the full doctrine,
#: the measured population, and the two raw-source specimens that prove its
#: witnesses do not repeat B8's own failure.
CANDIDATE_ONLY_RULES = (
    "parse-as-filed",
    "B8-lettered-section-rather-than-a-pinpoint",
)

#: The rosters an :class:`ActSectionClaim` may come from, narrowest first — the
#: same two altitudes :mod:`refspec.registry.unified_agenda_parquet`'s
#: ``_ActOracles.rosters`` already fences its initialism reader with. The
#: corpus-wide roster is deliberately absent here for the identical reason it
#: is absent there, and this fence has its own specimen of the cost: two acts
#: number a §8a into title 7, and only the filing agency's roster picks one.
ACT_ASSOCIATIONS = ("rin", "agency")

#: Every dash spelling collapses to "-" before any lookup. Restated verbatim
#: from ``citation_grammar._DASHES``; see the module docstring for the
#: measurement that makes it load-bearing.
_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))

#: A section token's sort key, as the Code orders sections: leading digits as a
#: number, the remainder as text. Comparing numeric prefixes alone reports
#: ``15 USC 717 to 717w`` as a descending range; it is not.
_LEADING_DIGITS = re.compile(r"^(\d+)(.*)$")

#: The suffix alphabet a near-miss may restore. The corpus reaches three
#: letters (``15 USC 77sss``, ``16 U.S.C. 470aaa``) and the Code reaches four
#: (``15 U.S.C. 77aaaa``), so the generator carries four.
_SUFFIXES = tuple(letter * count for count in (1, 2, 3, 4) for letter in ascii_lowercase)

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"

#: The letters a digit 1 is typed as, matched after :func:`normalize_section`
#: has folded case (so ``I`` arrives as ``i``). ``l`` is the font collision;
#: ``i`` is asserted by the grammar's own specimen list ("6bi" for
#: 7 U.S.C. 6b-1) and corroborated by the citing text, the ORDERED range
#: "7 U.S.C. 6b to 6bi", where 6b and 6b-1 are adjacent sections.
_ONE_TYPED_AS_A_LETTER = re.compile(r"[li]+$")

#: A section-shaped token whose letters the section grammar cannot read whole.
#: Bounded on both sides so it never matches the head of a longer compound
#: name: ``300ea-14`` is 42 U.S.C. 300aa-14 with a mistyped letter, not a lost
#: hyphen, and reading ``300ea`` out of it would invent a third defect.
_DAMAGED_TOKEN = re.compile(r"(?<![0-9A-Za-z.\-])(\d+[A-Za-z]{2,})(?![0-9A-Za-z\-])")

#: A section token with a SPACE where the Code has none: ``78 o-10``,
#: ``77 eee``, ``1395 hh``. Matched after :func:`normalize_section` has folded
#: case and dashes.
#:
#: The suffix is one letter REPEATED, which is the only suffix shape the Code
#: has (see ``citation_grammar._ONE_REPEATED_LETTER``: 18,136 sections across
#: the five densest titles, 898 two-letter suffixes, 102 three-letter, 2
#: four-letter, zero mixing two letters). The run reaches four because
#: :data:`_SUFFIXES` does and 15 U.S.C. 77aaaa is real; the spaced runs this
#: corpus writes reach three.
#:
#: That shape is also the whole fence against reading an English word as a
#: suffix, so there is no second list of connectives to drift from it: ``et``,
#: ``to``, ``and``, ``or``, ``sec``, ``ch``, ``note``, ``app``, ``seq``,
#: ``through``, ``of`` and ``as`` each fail it, every one for the same reason
#: -- no English word this corpus puts after a section number is one letter
#: repeated.
#:
#: The hyphenated TAIL is part of the match and part of the target, never
#: dropped: "78 o-10" names 15 U.S.C. 78o-10, and offering 78o instead would
#: mint a different real section -- the exact failure that demoted B8.
_SPACED_SUFFIX = re.compile(
    r"(?<![0-9a-z])(?P<stem>\d+)\s+(?P<suffix>(?P<letter>[a-z])(?P=letter){0,3})"
    r"(?P<tail>-[0-9]+[a-z]*)?(?![0-9a-z])"
)


def normalize_section(value: object) -> str:
    """Lowercase, trim and collapse every dash spelling. The join key."""

    return str(value or "").strip().lower().translate(_DASHES)


def _section_key(section: str) -> tuple[int, str] | None:
    match = _LEADING_DIGITS.match(section)
    return (int(match.group(1)), match.group(2)) if match else None


@dataclass(frozen=True)
class SectionVerdict:
    """What the oracle can say about one ``(title, section)`` at one edition."""

    title: int
    section: str
    appendix: bool
    edition_year: int | None
    verdict: str
    #: Named when ``verdict == "unknown"``, and only then.
    reason: str | None
    #: Which half of the oracle spoke: ``release-point``,
    #: ``release-point-range``, ``annual``, ``annual-range``. Empty when none did.
    evidence: tuple[str, ...]
    #: The release point's own status word(s). 10 U.S.C. 2891 and 2892 carry
    #: both ``current`` and ``repealed``, which is why this is not a scalar.
    status: tuple[str, ...]
    #: Annual editions that print the section, 1994-2024.
    attested_years: tuple[int, ...]
    #: Whether the edition the citation was filed in printed it. ``None`` when
    #: no edition was stated or the edition is outside the window. **A False
    #: beside an ``exists`` verdict is era mismatch, not a misread** — see the
    #: module docstring on why it never becomes ``absent``.
    attested_at_edition: bool | None
    caveats: tuple[str, ...] = ()
    #: What a pinned recodification table says became of this section, where
    #: one covers the gap the reason names. **Beside the verdict, never
    #: instead of it**: set only where ``reason`` is
    #: ``title_49_appendix_not_published``, and the verdict there is
    #: ``unknown`` whatever the table said, including where the table lists no
    #: such former section (``not-in-table``, which is an answer and not a
    #: silence). ``None`` where no table is bound, or where the gap is a
    #: different one.
    disposition: Disposition | None = None

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"undeclared verdict: {self.verdict!r}")
        if (self.verdict == "unknown") != (self.reason is not None):
            raise ValueError("an unknown verdict names its coverage gap, and no other verdict names one")
        if self.reason is not None and self.reason not in UNKNOWN_REASONS:
            raise ValueError(f"undeclared unknown reason: {self.reason!r}")
        if self.verdict == "absent" and self.caveats != ABSENT_CAVEATS:
            raise ValueError("an absence is only as wide as the oracle's window, and must say so")
        if self.verdict != "absent" and self.caveats:
            raise ValueError("only an absence carries the window caveat")
        if self.disposition is None:
            return
        if self.reason != DISPOSITION_REASON:
            raise ValueError(f"a disposition stands only beside {DISPOSITION_REASON}, not beside {self.reason!r}")
        if (self.disposition.former_title, self.disposition.former_section) != (self.title, self.section):
            raise ValueError("the disposition beside a verdict is the disposition of that section")

    @property
    def exists(self) -> bool:
        return self.verdict == "exists"


@dataclass(frozen=True)
class SubsectionVerdict:
    """Whether a section carries a lettered subsection — or whether we can know.

    Separate from :class:`SectionVerdict` because its ``absent`` rests on a
    different source (the release point's subsection tree, non-appendix titles
    only) and therefore carries a different, narrower claim.
    """

    title: int
    section: str
    sub: str
    verdict: str
    reason: str | None
    #: Every lettered subsection the release point prints on the section.
    #: Empty *and* ``verdict == "absent"`` is class B8's whole argument;
    #: empty with ``verdict == "unknown"`` says only that nobody looked.
    lettered: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"undeclared verdict: {self.verdict!r}")
        if (self.verdict == "unknown") != (self.reason is not None):
            raise ValueError("an unknown verdict names its coverage gap, and no other verdict names one")
        if self.reason is not None and self.reason not in UNKNOWN_REASONS:
            raise ValueError(f"undeclared unknown reason: {self.reason!r}")


@dataclass(frozen=True)
class ActSectionClaim:
    """An act's OWN section number, and the Code section OLRC classified it to.

    The fence's witness, supplied by the CALLER rather than derived here: which
    acts a row may be read against is a corpus fact (what the RIN's own boxes
    resolved, what its agency's boxes resolved) that this module cannot have,
    exactly as ``edition_year`` and the builder's dated title verdict already
    are. What this module owns is what to DO with one — see
    :meth:`UscSectionOracle.correction_candidates`.

    ``association`` is not decoration: the corpus-wide roster invents a wrong
    survivor (two acts number a §8a into title 7), so the level that answered
    is carried into the evidence and validated here.
    """

    #: The popular name the corpus resolved, as the act index spells it.
    act: str
    #: OLRC's Table III key for the enacting act: ``1922:369``.
    act_key: str
    #: The act's own section number, as Table III prints it: ``8a``.
    act_section: str
    #: The Code section that act section became, and its title.
    title: int
    section: str
    #: Which roster held the act. See :data:`ACT_ASSOCIATIONS`.
    association: str

    def __post_init__(self) -> None:
        if self.association not in ACT_ASSOCIATIONS:
            raise ValueError(f"undeclared act association: {self.association!r}")
        if not (self.act and self.act_key and self.act_section and self.section):
            raise ValueError("an act-section claim names an act, its key, its section and the Code's")


@dataclass(frozen=True)
class Candidate:
    """One reading of a citation whose target the oracle affirms."""

    rule: str
    title: int
    section: str
    #: Set when the reading is a pinpoint into a section: ``371`` + ``a``.
    subsection: str | None
    evidence: str
    #: Why this reading was STRUCK, where something outside the rule's own
    #: shape refuted it. ``None`` for every reading that stands. A struck
    #: reading is still named — a consumer counting readings must see it — but
    #: it is not a survivor, so it neither publishes nor blocks the one that
    #: does. Written today only by the act-numbering fence; see
    #: :class:`ActSectionClaim` and the module docstring on 7 U.S.C. 8a.
    fenced_by: str | None = None

    def __post_init__(self) -> None:
        if self.rule not in CORRECTION_RULES:
            raise ValueError(f"undeclared correction rule: {self.rule!r}")
        if self.fenced_by is not None and not self.fenced_by.strip():
            raise ValueError("a struck reading says what struck it")

    @property
    def target(self) -> tuple[int, str, str | None]:
        """What the reading points at. Two candidates agreeing here are one survivor."""

        return (self.title, self.section, self.subsection)

    @property
    def corrects(self) -> bool:
        """Whether surviving alone would make this reading a :class:`Correction`.

        ``False`` for every rule in :data:`CANDIDATE_ONLY_RULES` — B8 included
        since 2026-08-23 — which is the flag that tells a B8 candidate from an
        A4 or B1 one without a consumer parsing rule names. And ``False`` for a
        reading something struck, whatever its rule: A4 publishes in general
        and not on ``7 USC 8a``.
        """

        return self.rule not in CANDIDATE_ONLY_RULES and self.fenced_by is None


@dataclass(frozen=True)
class Correction:
    """The single surviving reading, with the original it replaces."""

    rule: str
    title: int
    #: What the parse published — or, for a recovery, the damaged token the
    #: parse dropped. Kept: a correction that loses the original cannot be
    #: audited, and the original is what a consumer already joined on.
    original_section: str
    section: str
    subsection: str | None
    evidence: str

    def __post_init__(self) -> None:
        if self.rule not in CORRECTION_RULES or self.rule in CANDIDATE_ONLY_RULES:
            raise ValueError(f"not a correction rule: {self.rule!r}")


@dataclass(frozen=True)
class NearMiss:
    """One exact-set section a single named edit away."""

    title: int
    section: str
    kinds: tuple[str, ...]


@dataclass(frozen=True)
class MissClass:
    """The first class in :data:`MISS_CLASSES` whose predicate fires."""

    code: str
    label: str
    #: The reading the class proposes, in the report's own spelling
    #: ("21 USC 371(a)"). ``None`` where the class detects but cannot propose.
    proposal: str | None
    why: str | None = None
    #: C10/C11 only: the neighbours found, best first.
    candidates: tuple[NearMiss, ...] = ()
    #: C9 only: what the pinned recodification table said became of the
    #: section. **Not** folded into :attr:`candidates`, which holds sections a
    #: named EDIT away in the current Code; a successor is a different animal
    #: — the same token, moved by an Act — and calling them one kind would let
    #: a consumer rank a typo against a statute.
    disposition: Disposition | None = None

    @property
    def name(self) -> str:
        """``"C2 subsection-as-section"`` — the report's table key."""

        return f"{self.code} {self.label}"


def _verify_pinned_parquet(directory: Path, name: str) -> Path:
    """Hash one pinned table, refusing loudly on drift. Returns its path."""

    path = directory / name
    expected = _ORACLE_PINS[name]
    digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    if digest != expected:
        raise ValueError(f"pinned U.S.C. oracle drifted: {name}; expected={expected}, observed={digest}")
    return path


def _read_pinned_parquet(directory: Path, name: str):
    """Read one pinned table, refusing loudly on drift.

    Returns the arrow Table rather than
    :func:`refspec.registry.act_resolution._read_pinned_parquet`'s row dicts:
    the annual set is 1,572,225 rows, and reading it column-wise is what keeps
    the whole oracle under a second to load.
    """

    import pyarrow.parquet as pq

    return pq.read_table(_verify_pinned_parquet(directory, name))


#: One printed range stub: ``(low, high)`` from the release point, or
#: ``(low, high, year)`` from the annual archives. :class:`_SpanIndex` sorts a
#: bucket of these once; see its docstring for what that buys.
_Span = tuple[tuple[int, str], tuple[int, str]] | tuple[tuple[int, str], tuple[int, str], int]


@dataclass(frozen=True)
class _SpanIndex:
    """One title's range stubs, sorted by low, with a running max-of-high prefix.

    ``annual_ranges`` and ``release_point_ranges`` used to be walked with
    ``any(low <= key <= high for low, high, ... in bucket)`` on every call --
    correct, and, for a title whose bucket runs to thousands of spans (title
    42's annual bucket alone holds 7,979), the reason
    :meth:`UscSectionOracle.attested_years` cost 7.9 s of a 15 s build. The
    fix is one sort, done once per bucket and cached by
    :attr:`UscSectionOracle._annual_ranges_index` and
    :attr:`UscSectionOracle._release_point_ranges_index`.

    Sorting by ``low`` turns "every span with ``low <= key``" into a prefix,
    found by :func:`bisect.bisect_right` in O(log n). A running maximum of
    ``high`` over that same sorted order then answers "does ANY span in the
    prefix reach far enough to cover ``key``" in O(1) once the prefix is
    found: if the largest ``high`` in the prefix is still below ``key``, no
    span in the WHOLE bucket can contain it, and :meth:`contains` and
    :meth:`payloads_containing` return without touching a single span. Only a
    genuine hit costs a scan, and only of the pruned prefix -- never the
    spans ``low`` already ruled out.

    Measured over the 95,492 distinct ``(title, section, appendix, year)``
    keys the pinned corpus files: 8.8 s before this index, 0.26 s after --
    about 34x -- see
    ``test_attested_years_index_matches_the_old_linear_scan_on_every_corpus_key``
    for the harness, and the module docstring for the same figures restated.
    """

    lows: tuple[tuple[int, str], ...]
    highs: tuple[tuple[int, str], ...]
    payloads: tuple[int | None, ...]
    prefix_max_high: tuple[tuple[int, str], ...]

    @classmethod
    def build(cls, spans: Iterable[_Span]) -> _SpanIndex:
        """Sort once. A 2-tuple span carries no payload; a 3-tuple's third item is one."""

        ordered = sorted(spans, key=lambda span: span[0])
        highs = tuple(span[1] for span in ordered)
        return cls(
            lows=tuple(span[0] for span in ordered),
            highs=highs,
            payloads=tuple(span[2] if len(span) > 2 else None for span in ordered),
            prefix_max_high=tuple(accumulate(highs, max)),
        )

    def contains(self, key: tuple[int, str]) -> bool:
        """Whether any span covers ``key``. Always O(log n): the prefix max alone decides."""

        prefix = bisect_right(self.lows, key)
        return prefix > 0 and self.prefix_max_high[prefix - 1] >= key

    def payloads_containing(self, key: tuple[int, str]) -> tuple[int | None, ...]:
        """Every payload (here, a year) whose span covers ``key``."""

        prefix = bisect_right(self.lows, key)
        if prefix == 0 or self.prefix_max_high[prefix - 1] < key:
            return ()
        return tuple(self.payloads[i] for i in range(prefix) if self.highs[i] >= key)


@dataclass(frozen=True)
class UscSectionOracle:
    """The section-existence oracle, loaded from one digest-verified directory."""

    directory: Path
    #: The pinned recodification tables, where the caller has them. Optional
    #: because they answer ONE of the four coverage holes and every other
    #: question this class takes is unchanged without them: an oracle bound
    #: without them returns the identical verdict with
    #: :attr:`SectionVerdict.disposition` ``None``. Held rather than
    #: constructed here so that a caller who has already verified the
    #: directory pays for it once — and so that "the tables are absent" is a
    #: state a test can build.
    dispositions: UscDispositionTables | None = None

    @classmethod
    def from_directory(
        cls, directory: Path | str, *, dispositions: UscDispositionTables | None = None
    ) -> UscSectionOracle:
        """Bind to a sealed oracle directory, verifying all six digests first."""

        oracle = cls(directory=Path(directory), dispositions=dispositions)
        oracle.verify()
        return oracle

    @classmethod
    def from_repository(cls, root: Path | str) -> UscSectionOracle:
        """Bind to the copy this repository carries — both sealed directories.

        The recodification tables are bound here rather than left to the
        caller, and their absence is LOUD: this repository carries them, and an
        oracle that answered ``unknown`` with no disposition because a pinned
        directory had gone missing would be the silent-degradation failure
        :meth:`verify` exists to refuse.
        """

        root = Path(root)
        return cls.from_directory(
            root / USC_SECTION_ORACLE_ARTIFACT,
            dispositions=UscDispositionTables.from_repository(root),
        )

    def verify(self) -> None:
        """Hash all six pinned tables, whatever this caller goes on to read.

        The tables load lazily, one :func:`cached_property` per table, which
        made "re-checked on every load" a claim about the caller rather than
        about the directory: a consumer that asked only
        :meth:`c7_chapter_as_section` authenticated ``usc-oracle-chapters``
        (11,668 bytes) and answered from five tables nothing had looked at. A
        swapped directory could therefore answer differently for as long as
        nobody happened to touch the table that was swapped.

        Verification is not worth deferring: the six are 9,229,092 bytes and
        hash in about 4 ms, against the second the annual table costs to
        *read*. So :meth:`from_directory` calls this, and the lazy readers keep
        their own check for the caller who constructed the dataclass directly.
        """

        for name in _ORACLE_PINS:
            _verify_pinned_parquet(self.directory, name)

    # -- the tables ------------------------------------------------------- #

    @cached_property
    def release_point_sections(self) -> Mapping[tuple[int, str], tuple[str, ...]]:
        """``(title, section) -> status words`` from release point 119-102."""

        table = _read_pinned_parquet(self.directory, "usc-oracle-sections.parquet")
        out: dict[tuple[int, str], tuple[str, ...]] = {}
        for title, section, status in zip(
            table.column("title").to_pylist(),
            table.column("section").to_pylist(),
            table.column("status").to_pylist(),
            strict=True,
        ):
            key = (title, normalize_section(section))
            out[key] = (*out.get(key, ()), status)
        return out

    @cached_property
    def release_point_ranges(self) -> Mapping[int, tuple[tuple[tuple[int, str], tuple[int, str]], ...]]:
        """``title -> the printed range stubs``, as ``(low key, high key)`` pairs."""

        table = _read_pinned_parquet(self.directory, "usc-oracle-ranges.parquet")
        out: dict[int, list[tuple[tuple[int, str], tuple[int, str]]]] = {}
        for title, low, high in zip(
            table.column("title").to_pylist(),
            table.column("lo").to_pylist(),
            table.column("hi").to_pylist(),
            strict=True,
        ):
            low_key, high_key = _section_key(normalize_section(low)), _section_key(normalize_section(high))
            if low_key and high_key:
                out.setdefault(title, []).append((low_key, high_key))
        return {title: tuple(spans) for title, spans in out.items()}

    @cached_property
    def _release_point_ranges_index(self) -> Mapping[int, _SpanIndex]:
        """:attr:`release_point_ranges`, sorted per title. See :class:`_SpanIndex`."""

        return {title: _SpanIndex.build(spans) for title, spans in self.release_point_ranges.items()}

    @cached_property
    def annual_sections(self) -> Mapping[tuple[int, bool, str], tuple[int, ...]]:
        """``(title, appendix, section) -> the archive years that print it``."""

        table = _read_pinned_parquet(self.directory, "usc-oracle-annual-sections.parquet")
        out: dict[tuple[int, bool, str], list[int]] = {}
        for year, title, appendix, section in zip(
            table.column("year").to_pylist(),
            table.column("title").to_pylist(),
            table.column("appendix").to_pylist(),
            table.column("section").to_pylist(),
            strict=True,
        ):
            out.setdefault((title, appendix, normalize_section(section)), []).append(year)
        return {key: tuple(sorted(years)) for key, years in out.items()}

    @cached_property
    def annual_ranges(self) -> Mapping[tuple[int, bool], tuple[tuple[tuple[int, str], tuple[int, str], int], ...]]:
        """``(title, appendix) -> the year-scoped range stubs``."""

        table = _read_pinned_parquet(self.directory, "usc-oracle-annual-ranges.parquet")
        out: dict[tuple[int, bool], list[tuple[tuple[int, str], tuple[int, str], int]]] = {}
        for year, title, appendix, low, high in zip(
            table.column("year").to_pylist(),
            table.column("title").to_pylist(),
            table.column("appendix").to_pylist(),
            table.column("lo").to_pylist(),
            table.column("hi").to_pylist(),
            strict=True,
        ):
            low_key, high_key = _section_key(normalize_section(low)), _section_key(normalize_section(high))
            if low_key and high_key:
                out.setdefault((title, appendix), []).append((low_key, high_key, year))
        return {key: tuple(spans) for key, spans in out.items()}

    @cached_property
    def _annual_ranges_index(self) -> Mapping[tuple[int, bool], _SpanIndex]:
        """:attr:`annual_ranges`, sorted per (title, appendix). See :class:`_SpanIndex`."""

        return {key: _SpanIndex.build(spans) for key, spans in self.annual_ranges.items()}

    @cached_property
    def subsections(self) -> Mapping[tuple[int, str], frozenset[str]]:
        """``(title, section) -> subsections``, release point, non-appendix only."""

        table = _read_pinned_parquet(self.directory, "usc-oracle-subsections.parquet")
        out: dict[tuple[int, str], set[str]] = {}
        for title, section, sub in zip(
            table.column("title").to_pylist(),
            table.column("section").to_pylist(),
            table.column("sub").to_pylist(),
            strict=True,
        ):
            out.setdefault((title, normalize_section(section)), set()).add(sub.lower())
        return {key: frozenset(subs) for key, subs in out.items()}

    @cached_property
    def chapters(self) -> frozenset[tuple[int, str]]:
        """``(title, chapter)`` from the release point, 53 titles."""

        table = _read_pinned_parquet(self.directory, "usc-oracle-chapters.parquet")
        return frozenset(
            (title, normalize_section(chapter))
            for title, chapter in zip(
                table.column("title").to_pylist(), table.column("chapter").to_pylist(), strict=True
            )
        )

    @cached_property
    def enumerated(self) -> frozenset[tuple[int, str]]:
        """The exact non-appendix set: release point ∪ annual. 66,780 pairs.

        The only set a candidate may be tested against — see the module
        docstring on the 110-pair false-positive class the ranges produced.
        """

        return frozenset(self.release_point_sections) | frozenset(
            (title, section) for title, appendix, section in self.annual_sections if not appendix
        )

    @cached_property
    def hyphen_children(self) -> Mapping[tuple[int, str], tuple[str, ...]]:
        """``(title, stem) -> the sections named ``stem-N``, in Code order.

        15 U.S.C. 80a is not a section; 80a-1 … 80a-64 are. That is class C8.
        """

        out: dict[tuple[int, str], list[str]] = {}
        for title, section in self.enumerated:
            if "-" in section:
                out.setdefault((title, section.split("-", 1)[0]), []).append(section)
        return {
            key: tuple(sorted(names, key=lambda name: _section_key(name.split("-", 1)[1]) or (0, "")))
            for key, names in out.items()
        }

    # -- existence -------------------------------------------------------- #

    def section_is_enumerated(self, title: int, section: str, *, appendix: bool = False) -> bool:
        """Membership in the exact lists only. What a candidate is tested against."""

        section = normalize_section(section)
        if appendix:
            return (title, True, section) in self.annual_sections
        return (title, section) in self.enumerated

    def _in_release_point_range(self, title: int, key: tuple[int, str] | None) -> bool:
        """Whether a printed release-point range stub covers ``key``. Never appendix."""

        if key is None:
            return False
        index = self._release_point_ranges_index.get(title)
        return index is not None and index.contains(key)

    def _in_annual_range(self, title: int, appendix: bool, key: tuple[int, str] | None) -> bool:
        """Whether a printed annual range stub covers ``key``, any edition 1994-2024."""

        if key is None:
            return False
        index = self._annual_ranges_index.get((title, appendix))
        return index is not None and index.contains(key)

    def section_exists(self, title: int, section: str, *, appendix: bool = False) -> bool:
        """Enumerated, or inside a printed range stub. What a parse is judged against."""

        section = normalize_section(section)
        if self.section_is_enumerated(title, section, appendix=appendix):
            return True
        key = _section_key(section)
        if not appendix and self._in_release_point_range(title, key):
            return True
        return self._in_annual_range(title, appendix, key)

    def attested_years(self, title: int, section: str, *, appendix: bool = False) -> tuple[int, ...]:
        """Every annual edition 1994-2024 that prints the section, exact or ranged.

        The ranged half used to walk every span in the title's annual bucket
        on every call -- 12.2M comparisons over 95,492 distinct
        ``(title, section, appendix, year)`` keys the pinned corpus files,
        8.8 s of it. :attr:`_annual_ranges_index` sorts each bucket once so a
        call that matches nothing (the common case) never touches a span:
        0.26 s over the same keys, identical result on every one -- about
        34x. See :class:`_SpanIndex` for the mechanism and
        ``test_attested_years_index_matches_the_old_linear_scan_on_every_corpus_key``
        for the proof.
        """

        section = normalize_section(section)
        years = set(self.annual_sections.get((title, appendix, section), ()))
        key = _section_key(section)
        if key is not None:
            index = self._annual_ranges_index.get((title, appendix))
            if index is not None:
                years |= set(index.payloads_containing(key))
        return tuple(sorted(years))

    @cached_property
    def _disposition_memo(self) -> dict[tuple[int, str, str | None, str | None, bool], Disposition | None]:
        return {}

    def disposition(
        self,
        title: int,
        section: str,
        *,
        appendix: bool = False,
        subsection: object = None,
        section_end: object = None,
    ) -> Disposition | None:
        """What a pinned recodification table says became of a former section.

        Keyed ``(title, section, subsection, section_end, appendix)`` and NOT
        by edition year, which is the whole difference from
        :meth:`section_verdict`'s memo: a citation's edition decides what the
        Code printed *then* and decides nothing about what Pub. L. 103-272 did
        in 1994. The same 146 sections are cited across thirty Agenda editions
        in the pinned build, so a year in the key would ask the same question
        of the same table thirty times over.

        The pinpoint and the far end are IN the key rather than filtered after
        it, for the reason ``_ActNumbering``'s claims are in the correction
        memo's: ``1651`` and ``1651(b)(2)`` are two questions with two answers
        (two candidates against one), and a memo keyed without them would
        publish whichever citation asked first. Over the pinned build's 2,548
        asked rows that is 161 keys without them and 226 with.

        ``None`` where no tables are bound, and ``None`` where the coverage
        hole is not the one a table speaks into — an appendix citation in a
        title that has no pinned recodification gets
        ``no-table-for-title`` if it is asked, so the gate is here rather than
        publishing a verdict about a table nobody read.
        """

        if self.dispositions is None:
            return None
        pinpoint = str(subsection).strip() if subsection else None
        end = normalize_section(section_end) or None
        key = (title, normalize_section(section), pinpoint, end, bool(appendix))
        if key not in self._disposition_memo:
            self._disposition_memo[key] = self.dispositions.disposition(
                key[0], key[1], pinpoint, section_end=end
            )
        return self._disposition_memo[key]

    def section_verdict(
        self,
        title: int,
        section: str,
        edition_year: int | None = None,
        *,
        appendix: bool = False,
    ) -> SectionVerdict:
        """exists / absent / unknown, with the coverage gap named when unknown.

        ``edition_year`` is the year the citation was filed (the Agenda's
        ``publication_id`` head). It fills
        :attr:`SectionVerdict.attested_at_edition` and refuses out-of-window
        questions; it never turns an ``exists`` into an ``absent``.

        Where the answer is ``unknown`` for :data:`DISPOSITION_REASON` and this
        oracle carries the recodification tables,
        :attr:`SectionVerdict.disposition` is filled BESIDE the verdict. Read
        the docstring above on why the verdict does not move: the appendix is
        still unpublished, and what the table adds is a different question's
        answer.
        """

        section = normalize_section(section)
        window_start, window_end = ORACLE_WINDOW
        evidence: list[str] = []
        in_release_point = not appendix and (title, section) in self.release_point_sections
        if in_release_point:
            evidence.append("release-point")
        years = self.attested_years(title, section, appendix=appendix)
        if (title, appendix, section) in self.annual_sections:
            evidence.append("annual")
        elif years:
            evidence.append("annual-range")
        key = _section_key(section)
        in_release_range = not appendix and self._in_release_point_range(title, key)
        if in_release_range:
            evidence.append("release-point-range")

        def verdict_of(name: str, reason: str | None = None) -> SectionVerdict:
            at_edition: bool | None = None
            if edition_year is not None and window_start <= edition_year <= window_end:
                at_edition = (
                    edition_year in years
                    if edition_year <= ORACLE_ANNUAL_YEARS[1]
                    else in_release_point or in_release_range
                )
            return SectionVerdict(
                title=title,
                section=section,
                appendix=appendix,
                edition_year=edition_year,
                verdict=name,
                reason=reason,
                evidence=tuple(evidence),
                status=tuple(self.release_point_sections.get((title, section), ())) if not appendix else (),
                attested_years=years,
                attested_at_edition=at_edition,
                caveats=ABSENT_CAVEATS if name == "absent" else (),
                # Written from the reason, in ONE place, so no branch below can
                # attach a disposition to a verdict that did not earn one --
                # and so adding a second answerable reason is adding it to
                # DISPOSITION_REASON's neighbourhood and nothing else.
                disposition=(
                    self.disposition(title, section, appendix=appendix)
                    if reason == DISPOSITION_REASON
                    else None
                ),
            )

        if edition_year is not None and not window_start <= edition_year <= window_end:
            return verdict_of("unknown", "edition_outside_oracle_window")
        if evidence:
            return verdict_of("exists")
        if appendix and title not in APPENDIX_TITLES_PUBLISHED:
            return verdict_of(
                "unknown", "title_49_appendix_not_published" if title == 49 else "appendix_title_not_published"
            )
        if self.c9_title_49_pre_1996(title, section):
            return verdict_of("unknown", "title_49_appendix_not_published")
        return verdict_of("absent")

    def subsection_verdict(self, title: int, section: str, sub: str) -> SubsectionVerdict:
        """Whether a section carries a lettered subsection — or whether we can know.

        The subsection oracle is the **current release point, non-appendix
        titles only**, so a section the Code has since transferred has no
        extractable structure and the answer is ``unknown``, never ``absent``.

        A **stub** is the same gap wearing a different mask. All 8,405
        ``repealed|omitted|transferred|renumbered|vacant|reserved`` sections in
        the release point carry ZERO subsection rows — measured, not assumed —
        so "no subsections" there is the stub talking, not the section's shape.
        16 U.S.C. 462 (49 rows citing ``462k``) is the specimen: it is stubbed
        ``repealed``, so whether it once had a subsection (k) is unknown here,
        and no correction may rest on it.
        """

        section, sub = normalize_section(section), str(sub or "").strip().lower()
        lettered = self.lettered_subsections(title, section)
        status = self.release_point_sections.get((title, section), ())
        if sub in self.subsections.get((title, section), frozenset()):
            verdict, reason = "exists", None
        elif "current" not in status:
            verdict, reason = "unknown", "subsection_structure_not_published"
        else:
            verdict, reason = "absent", None
        return SubsectionVerdict(
            title=title,
            section=section,
            sub=sub,
            verdict=verdict,
            reason=reason,
            lettered=tuple(sorted(lettered)),
        )

    def lettered_subsections(self, title: int, section: str) -> frozenset[str]:
        """The lettered subsections the release point prints; ``(1)`` paragraphs excluded.

        42 U.S.C. 629 has only unlettered paragraphs (1)-(4), so ``629(b)``
        cannot be a pinpoint into it while 42 U.S.C. 629b is a real section —
        the discriminator class B8 rests on.
        """

        known = self.subsections.get((title, normalize_section(section)), frozenset())
        return frozenset(sub for sub in known if sub.isalpha())

    # -- the triage predicates, in the report's precedence order ----------- #
    #
    # Each presumes the pair is a MISS -- `section_exists` already said no --
    # and answers only "is this the shape of class X". They are separate
    # functions because the report counts them separately, and a class that
    # cannot be counted on its own cannot be argued with.
    #
    # ONE SPELLING EACH, and `classify_section_miss` is the only reader.
    # Three predicates here (`c3_paren_suffix_eaten`, `c8b_letter_o_as_zero`,
    # `c12_unresolved`) had no caller anywhere in src or tests while the
    # classifier restated their conditions inline, so editing one of them
    # changed no count and nothing said so. A predicate the classifier does
    # not call is not a rule, it is a second opinion nobody asks for:
    # `test_every_triage_predicate_is_reachable_from_the_classifier` holds
    # that true in both directions.

    def c0_title_impossible(self, title: int, *, stated_possible: bool | None = None) -> bool:
        """The grammar already knows: 1-54, never the unenacted 53.

        31 pairs / 35 texts / 134 rows, **74 of them typed ``ok``** — the
        warning exists, in a column most consumers never read.

        ``stated_possible`` is the artifact's own ``usc_title_is_possible``
        column, and **what the builder states outranks what this function
        derives**, because the builder's verdict is EDITION-DATED and this one
        is not: it asks "had this title been created yet?". Measured over the
        pinned build, the two disagree on exactly 2 pairs / 5 rows —
        ``52 USC 7602(s)`` and ``54 USC 4118``, titles enacted in 2014 and
        cited in earlier editions — which is the whole gap between this
        module's 29 pairs and the report's 31.
        """

        return stated_possible is False or not usc_title_is_possible(title)

    def c1_zero_padded(self, title: int, section: str) -> bool:
        """``26 U.S.C. 0956(e)``: the pad is the agency's, the identity is ours.

        48 pairs / 101 texts / 943 rows, 941 of them in title 26.
        """

        section = normalize_section(section)
        return bool(re.match(r"^0\d", section)) and self.section_is_enumerated(title, section.lstrip("0"))

    def c2_subsection_as_section(self, title: int, section: str) -> bool:
        """``21 USC 321p`` for 321(p): the stem is a section, the tail its subsection.

        75 pairs / 91 texts / 3,659 rows / **3,614 typed ``ok``** — the largest
        defect, and not fixable from the text alone: ``360b`` is real and
        ``321p`` is not, and nothing in the characters separates them.

        The "whole token is not itself a section" half of the report's
        predicate is kept here rather than left to the caller's miss filter, so
        the predicate is safe to ask about any citation: ``5 USC 552a`` has a
        real stem and a real subsection (a) and is *also* a real section, and
        without that clause this would call the Privacy Act a misread.
        """

        section = normalize_section(section)
        match = re.fullmatch(r"(\d+)([a-z]+)", section)
        if match is None or self.section_is_enumerated(title, section):
            return False
        stem, tail = match.group(1), match.group(2)
        return self.section_is_enumerated(title, stem) and tail in self.subsections.get((title, stem), frozenset())

    def c3_proposals(self, title: int, section: str, authority_text: str) -> tuple[NearMiss, ...]:
        """``15 USC 78(a)`` -> 78: the strip-parenthetical rule ate a real suffix.

        4 pairs / 84 texts / 343 rows. 15 U.S.C. 78a is real, bare 78 is not.
        Non-empty IS the class: every section the text's parenthesised suffixes
        name — none preferred.

        The parenthesis is gone from the parse, so the TEXT is the only witness
        to which suffix it held, and a text that parenthesises several witnesses
        several. Measured over the pinned build's joined authority texts,
        **3 of the 4 C3 pairs / 303 of its 343 rows** name more than one:
        15 U.S.C. 78 reaches **18** affirmed readings over its 57 texts (78a,
        78b, 78c, 78g, 78h, 78i, 78j, 78l, 78m, 78n, 78o, 78p, 78q, 78s, 78w,
        78x, 78ll, 78mm), 42 U.S.C. 2000 reaches 2 (2000d, 2000e) and
        19 U.S.C. 81 reaches 3 (81a, 81c, 81u). Walking ``_SUFFIXES`` and
        returning the first affirmed one published "15 USC 78a" for all 245 of
        that pair's rows — alphabetical order wearing a citation's clothes,
        and the one guess this module made while
        :meth:`corrected_section` beside it refuses anything with two
        survivors. The count is the finding; the classifier proposes only where
        exactly one survives.

        **A tail the text states outranks the bare lettered section, and used
        to be dropped on the floor here.** ``12 USC 1735(f)-14`` is B8's own
        lesson: 12 U.S.C. 1735f ("Water and sewerage facilities") is a real
        section, so the enumerated-lettered branch fired, took ``1735f`` and
        skipped the tail check entirely — manufacturing exactly the single
        survivor B8 was demoted for. The stated tail is now read FIRST, from
        the same :meth:`tail_stated_sections` :meth:`correction_candidates`
        reads, so the two rules cannot drift apart: where the text spells
        ``NNN(x)-YY`` and the Code enumerates ``NNNx-YY``, that is the reading;
        the bare ``NNNx`` is the fallback for a text that states no tail, and
        the compound-name family is the fallback below that.

        **The tail outranks the bare reading per OCCURRENCE, not per text**,
        and reading it per text was a second truncation hiding inside the
        first. ``42 U.S.C. 2000(d) to 2000(d)-7`` states TWO readings — the
        bare 2000d and 2000d-7, both printed sections of the Civil Rights
        Act's Title VI — and a rule that suppressed the untailed one because
        *some* occurrence in the string carried a tail dropped a section the
        text spells out in full. Aggregated over the pair's 14 texts it dropped
        2000d for all 49 rows, 30 of which state nothing but a bare
        ``2000(d)``. Each stated occurrence is now judged on its own tail;
        an occurrence whose tail reaches nothing this oracle enumerates
        (``1735(f)-99``) falls back exactly as before, which is what keeps the
        two negative fixtures true.

        Measured over the pinned corpus the change is visible in one pair:
        42 U.S.C. 2000's count behind its refusal goes from 2 readings to
        **9** — 2000d, 2000d-1 … 2000d-7, 2000e. **Latent in this module**:
        :meth:`classify_section_miss` is this method's only caller here. It is
        NOT latent downstream — ``unified_agenda_parquet``'s C3 promotion reads
        these proposals per row, and the two rows of RIN 1505-AC45 (editions
        201610 and 201704) that file that exact span move from *promoted to
        ``42 USC 2000d-7``* to *refused as ambiguous*, which is the correct
        answer for a citation naming a span by both endpoints: 217 promoted /
        14 ambiguous / 1,186 witnessless, from 219 / 12 / 1,186.
        """

        section = normalize_section(section)
        if not re.fullmatch(r"\d+", section):
            return ()
        text = normalize_section(authority_text)
        found: dict[str, set[str]] = {}

        def offer(candidate: str, kind: str) -> None:
            if self.section_is_enumerated(title, candidate):
                found.setdefault(candidate, set()).add(kind)

        for suffix in _SUFFIXES:
            # Every occurrence of this pinpoint, each carrying its OWN tail or
            # none: the unit the precedence below is decided on.
            occurrences = re.findall(rf"\b{section}\s*\(\s*{suffix}\s*\)(?:\s*-\s*([0-9a-z]+))?", text)
            if not occurrences:
                continue
            lettered = section + suffix
            # 15 U.S.C. 80a is not a section; 80a-1 … 80a-64 are. 12 U.S.C.
            # 1735f IS a section and 1735f-14 is a different one. Either way,
            # where the text states the tail itself — "15 U.S.C. 80(a)-23",
            # "12 USC 1735(f)-14" — that names ONE section and outranks both
            # the bare lettered reading and the family, which offers 65 and
            # therefore proposes none.
            affirmed = self.tail_stated_sections(title, section, authority_text, letter=suffix)
            for one in affirmed:
                offer(one, "tail-stated")
            # **The tail outranks the bare reading per OCCURRENCE, not per
            # text.** "42 U.S.C. 2000(d) to 2000(d)-7" states both 2000d and
            # 2000d-7; suppressing the first because some other occurrence
            # carried a tail dropped a reading the text spells out in full.
            # An occurrence whose own tail reaches nothing affirmed — none
            # stated at all, or one the Code does not print ("1735(f)-99") —
            # falls back exactly the way it always did.
            served = set(affirmed)
            if all(stated and f"{lettered}-{stated}" in served for stated in occurrences):
                continue
            if self.section_is_enumerated(title, lettered):
                offer(lettered, "suffix-restored")
            else:
                for child in self.hyphen_children.get((title, lettered), ()):
                    offer(child, "compound-name-family")
        return tuple(NearMiss(title=title, section=name, kinds=tuple(sorted(kinds))) for name, kinds in found.items())

    def c4_date_year_as_section(self, section: str, authority_text: str) -> bool:
        """A calendar year harvested as a section. Fires on nothing today.

        ``18 USC 3621, …, 4082 (Repealed … November 1, 1987)`` once published
        **18 U.S.C. 1987** beside seven correct citations. Fixed at
        ``f05791de``; the 995 rows left the artifact in the rebuild this oracle
        was measured against. Kept so the regression cannot be silent.
        """

        section = normalize_section(section)
        if not re.fullmatch(r"(1[789]|20)\d\d", section):
            return False
        text = normalize_section(authority_text)
        return bool(
            re.search(rf"(?:{_MONTHS})[a-z]*\.?\s+\d{{1,2}},?\s*{section}\b|\b\d{{1,2}}/\d{{1,2}}/{section}\b", text)
        )

    def c5_appendix_out_of_oracle(self, title: int, *, appendix: bool) -> bool:
        """An appendix citation in a title no archive year publishes. 33 pairs / 269 rows."""

        return appendix and title not in APPENDIX_TITLES_PUBLISHED

    def c6_appendix_miss(self, title: int, *, appendix: bool) -> bool:
        """An appendix citation in a title the archives DO publish. 11 pairs / 42 rows."""

        return appendix and title in APPENDIX_TITLES_PUBLISHED

    def c7_chapter_as_section(self, title: int, section: str) -> bool:
        """``10 USC 55`` is chapter 55 (Medical and Dental Care), not a section.

        94 pairs / 144 texts / 1,253 rows.
        """

        section = normalize_section(section)
        return bool(re.fullmatch(r"\d+[a-z]?", section)) and (title, section) in self.chapters

    def c8_hyphen_part_dropped(self, title: int, section: str) -> bool:
        """``15 USC 80a et seq`` -> 80a: the Investment Company Act opens at 80a-1.

        3 pairs / 26 texts / 158 rows.
        """

        return bool(self.hyphen_children.get((title, normalize_section(section))))

    def c8b_proposal(self, title: int, section: str) -> str | None:
        """``15 U.S.C. 780-10`` for 78o-10. 9 pairs / 15 texts / 61 rows.

        The section a non-leading zero typed for the letter o was meant to
        name. Not-None IS the class.
        """

        section = normalize_section(section)
        for index, char in enumerate(section):
            if char == "0" and index > 0:
                candidate = section[:index] + "o" + section[index + 1 :]
                if self.section_is_enumerated(title, candidate):
                    return candidate
        return None

    def _kept_whole_pair(self, title: int, section: str) -> bool:
        """``NNN-MM``, second number below the first, stem a real section.

        The SHAPE C8c and C8d share: the ordering rule declined the pair, so
        the token stayed one NAME in the section-identity column and asserted a
        section instead of refusing. 113 pairs / 682 rows wear it. What splits
        them is the mechanism underneath, and only the grammar can say which.
        """

        match = re.fullmatch(r"(\d+)-(\d+)", normalize_section(section))
        if match is None or int(match.group(2)) >= int(match.group(1)):
            return False
        return self.section_is_enumerated(title, match.group(1))

    def c8c_inverted_range_kept_whole(self, title: int, section: str) -> bool:
        """``26 U.S.C. 2032-1(e)`` — a 26 CFR reg number wearing a U.S.C. label.

        MECHANISM: a true inversion, an abbreviation of nothing. "2032-1" has a
        one-digit leaf and "4801-4582" repeats nothing, so no reading of either
        as a span is available and the token can only be refused.
        **49 pairs / 426 rows** of the shape, before precedence.
        """

        return self._kept_whole_pair(title, section) and _abbreviated_span(normalize_section(section)) is None

    def c8d_abbreviated_span_kept_whole(self, title: int, section: str) -> bool:
        """``28 U.S.C. 2671-80`` — §§2671-2680, GPO-abbreviated and kept as a name.

        MECHANISM: the second endpoint dropped the repeated leading digits of
        the first (GPO, Bluebook 3.2(a)), which makes it sort *below* the first
        and sends the pair down the same fail-closed branch C8c takes — while
        being no inversion at all. **64 pairs / 256 rows**, before precedence:
        12 U.S.C. 1784-86, 5 U.S.C. 571-83, 7 U.S.C. 1373-74, 12 U.S.C.
        1781-90, 31 U.S.C. 3801-12 …

        The split is what keeps the count honest. HEAD's
        :func:`refspec.registry.citation_grammar._abbreviated_span` — deferred
        to here rather than restated, so the class means exactly what the
        grammar does — now reads these as RANGES, so they leave the section
        column on the next rebuild. Undivided, "C8c" would fall from 113 pairs
        to 49 and go on wearing the same name and the same docstring.
        """

        return self._kept_whole_pair(title, section) and _abbreviated_span(normalize_section(section)) is not None

    def c9_title_49_pre_1996(self, title: int, section: str) -> bool:
        """The old Federal Aviation Act / ICC numbering. 111 pairs / 1,969 rows.

        Real until the 1994 recodification and the 1995 ICC Termination Act,
        and unconfirmable: no ``usc49a.htm`` exists in any OLRC archive year.
        The corpus proves it itself — the same 113 RINs cite ``49 USC 1354`` in
        1995-10 and ``49 U.S.C. 40113`` from 1996-04 on.
        """

        section = normalize_section(section)
        if title != 49:
            return False
        if section.isdigit():
            return int(section) < 2000 or 10_000 <= int(section) <= 11_999
        return bool(re.match(r"^\d{1,4}[a-z]", section))

    def near_misses(self, title: int, section: str) -> tuple[NearMiss, ...]:
        """Every exact-set section one named edit away, unranked."""

        section = normalize_section(section)
        found: dict[tuple[int, str], set[str]] = {}

        def offer(kind: str, other_title: int, other_section: str) -> None:
            if (other_title, other_section) != (title, section) and self.section_is_enumerated(
                other_title, other_section
            ):
                found.setdefault((other_title, other_section), set()).add(kind)

        if re.match(r"^0\d", section):
            offer("zero-pad", title, section.lstrip("0"))
        if re.fullmatch(r"\d+", section):
            for suffix in _SUFFIXES:
                offer("suffix-restored", title, section + suffix)
        dropped = re.fullmatch(r"(\d+)([a-z]+)", section)
        if dropped:
            offer("suffix-dropped", title, dropped.group(1))
        split = _LEADING_DIGITS.match(section)
        if split:
            number, tail = split.group(1), split.group(2)
            for index in range(len(number) - 1):
                if number[index] != number[index + 1]:
                    offer(
                        "transposed",
                        title,
                        number[:index] + number[index + 1] + number[index] + number[index + 2 :] + tail,
                    )
            if len(number) > 1:
                for index in range(len(number)):
                    offer("digit-dropped", title, number[:index] + number[index + 1 :] + tail)
            for index in range(len(number) + 1):
                for digit in "0123456789":
                    offer("digit-added", title, number[:index] + digit + number[index:] + tail)
            for index in range(len(number)):
                for digit in "0123456789":
                    if digit != number[index]:
                        offer("digit-changed", title, number[:index] + digit + number[index + 1 :] + tail)
        for other in range(1, 55):
            if other != title:
                offer("other-title", other, section)
        return tuple(NearMiss(title=key[0], section=key[1], kinds=tuple(sorted(kinds))) for key, kinds in found.items())

    def _c9_class(self, title: int, section: str) -> MissClass:
        """C9, with the recodification table's outcome as its classification.

        C9 was the one class that detected a whole family and could say nothing
        about any member of it: "no OLRC archive year carries a Title 49
        Appendix" is a fact about the *sources*, and a triage reader got the
        same sentence for a section restated at 49 U.S.C. 44705 as for one
        repealed outright. The table separates them, and the separation is the
        classification — the class code does not move, because the coverage
        hole has not.

        **A proposal only where the table names one successor.** Where it names
        several (62 of the 146 sections in the pinned build), the printed prose
        is the only thing that tells them apart and no question this class can
        put to anything decides between them, so ``proposal`` is ``None`` and
        the successors ride in :attr:`MissClass.disposition` as what they are:
        candidates. That is :data:`CANDIDATE_ONLY_RULES`' rule, reached from
        the other direction.
        """

        answer = self.disposition(title, section)
        if answer is None:
            return MissClass("C9", "title-49-pre-1996", None, "no OLRC archive year carries a Title 49 Appendix")
        successors = answer.successors
        if len(successors) == 1:
            one = successors[0]
            return MissClass(
                "C9",
                "title-49-pre-1996",
                f"{one.title} USC {one.section}",
                f"no OLRC archive year carries a Title 49 Appendix; the {answer.recodification} disposition table "
                f"restates it as {one.title} U.S.C. {one.section} (Pub. L. 103-272, § 6(b))",
                disposition=answer,
            )
        if successors:
            named = ", ".join(f"{one.title} USC {one.section}" for one in successors)
            return MissClass(
                "C9",
                "title-49-pre-1996",
                None,
                f"no OLRC archive year carries a Title 49 Appendix; the {answer.recodification} disposition table "
                f"names {len(successors)} successors separated only by printed prose ({named}): candidates, "
                "never an identity",
                disposition=answer,
            )
        why = {
            "repealed-no-successor": "the {name} disposition table repeals it and names no successor",
            "stated-without-successor": (
                "the {name} disposition table names no successor and points at another instrument"
            ),
            "not-in-table": "the {name} disposition table does not list it ({caveats})",
            "no-table-for-title": "no disposition table is pinned for title {title}",
        }[answer.verdict]
        return MissClass(
            "C9",
            "title-49-pre-1996",
            None,
            "no OLRC archive year carries a Title 49 Appendix; "
            + why.format(name=answer.recodification, caveats=", ".join(answer.caveats), title=title),
            disposition=answer,
        )

    def c10_unique_near_miss(self, title: int, section: str) -> bool:
        """Exactly one neighbour exists. 146 pairs / 833 rows — a LEAD, not a finding.

        ``21 USC 360gg to 360ss`` is why: the generator proposes 21 U.S.C. 360,
        a valid single edit and the wrong answer (the radiation-control
        subchapter opens at 360hh).
        """

        return len(self.near_misses(title, section)) == 1

    def c11_corroborated_near_miss(
        self, title: int, section: str, same_rin_statements: Mapping[tuple[int, str], int]
    ) -> bool:
        """Several neighbours, and the citing RINs state one of them elsewhere.

        237 pairs / 2,321 rows. ``same_rin_statements`` maps a candidate to how
        many of this pair's own RINs state it somewhere in the corpus; the
        caller computes it, because it is a fact about the corpus and not about
        the Code.
        """

        near = self.near_misses(title, section)
        return len(near) > 1 and any(same_rin_statements.get((one.title, one.section), 0) > 0 for one in near)

    def classify_section_miss(
        self,
        title: int,
        section: str,
        *,
        appendix: bool = False,
        authority_text: str = "",
        same_rin_statements: Mapping[tuple[int, str], int] | None = None,
        stated_title_possible: bool | None = None,
    ) -> MissClass:
        """The first class in :data:`MISS_CLASSES` whose predicate fires."""

        section = normalize_section(section)
        statements = same_rin_statements or {}
        if self.c0_title_impossible(title, stated_possible=stated_title_possible):
            return MissClass("C0", "title-impossible", None, "usc_title_is_possible = false")
        if self.c1_zero_padded(title, section):
            return MissClass("C1", "zero-padded", f"{title} USC {section.lstrip('0')}", "leading zeros stripped")
        split = re.fullmatch(r"(\d+)([a-z]+)", section)
        if split is not None and self.c2_subsection_as_section(title, section):
            return MissClass(
                "C2",
                "subsection-as-section",
                f"{title} USC {split.group(1)}({split.group(2)})",
                "no such section; the stem is a section and the tail is one of its subsections",
            )
        eaten = self.c3_proposals(title, section, authority_text)
        if eaten:
            only = eaten[0] if len(eaten) == 1 else None
            return MissClass(
                "C3",
                "paren-suffix-eaten",
                f"{title} USC {only.section}" if only is not None else None,
                (
                    f"the text parenthesises a suffix; {title} USC {section} is not a section, {only.section} is"
                    if only is not None
                    else f"{title} USC {section} is not a section, and {len(eaten)} sections are named {section} "
                    "plus a suffix the text parenthesises"
                ),
                eaten,
            )
        if self.c4_date_year_as_section(section, authority_text):
            return MissClass("C4", "date-year-as-section", None, "the token is a calendar year")
        if self.c5_appendix_out_of_oracle(title, appendix=appendix):
            return MissClass("C5", "appendix-out-of-oracle", None, "no archive year publishes this appendix")
        if self.c6_appendix_miss(title, appendix=appendix):
            return MissClass("C6", "appendix-miss", None, "the appendix is published and does not carry it")
        if self.c7_chapter_as_section(title, section):
            return MissClass(
                "C7",
                "chapter-as-section",
                f"{title} USC ch. {section}",
                f"{title} USC has no section {section}; it has a chapter {section}",
            )
        if self.c8_hyphen_part_dropped(title, section):
            children = self.hyphen_children[(title, section)]
            return MissClass(
                "C8",
                "hyphen-part-dropped",
                f"{title} USC {children[0]} et seq.",
                f"{title} USC {section} is not a section; {len(children)} sections are named {section}-N",
            )
        letter_o = self.c8b_proposal(title, section)
        if letter_o is not None:
            return MissClass(
                "C8b",
                "letter-o-as-zero",
                f"{title} USC {letter_o}",
                "the section name's letter o was typed as a zero",
            )
        if self.c8c_inverted_range_kept_whole(title, section):
            return MissClass(
                "C8c",
                "inverted-range-kept-whole",
                f"{title} USC {section.split('-', 1)[0]} (range end unread)",
                "second endpoint sorts before the first and abbreviates nothing, so the ordering rule kept the "
                "pair as one name",
            )
        span = _abbreviated_span(section)
        if span is not None and self.c8d_abbreviated_span_kept_whole(title, section):
            low, high = span
            return MissClass(
                "C8d",
                "abbreviated-span-kept-whole",
                f"{title} USC {low} to {high}",
                f"the pair abbreviates {low} to {high} GPO-style, so its second endpoint sorts before the first "
                "and the ordering rule kept it as one name",
            )
        if self.c9_title_49_pre_1996(title, section):
            return self._c9_class(title, section)
        near = self.near_misses(title, section)
        if self.c10_unique_near_miss(title, section):
            only = near[0]
            return MissClass(
                "C10", "unique-near-miss", f"{only.title} USC {only.section}", ", ".join(only.kinds), (only,)
            )
        if self.c11_corroborated_near_miss(title, section, statements):
            corroborated = tuple(
                sorted(
                    (one for one in near if statements.get((one.title, one.section), 0) > 0),
                    key=lambda one: -statements[(one.title, one.section)],
                )
            )
            best = corroborated[0]
            return MissClass(
                "C11",
                "corroborated-near-miss",
                f"{best.title} USC {best.section}",
                f"{statements[(best.title, best.section)]} same-RIN statements among {len(near)} candidates",
                corroborated,
            )
        # C12 is the fallthrough, and has no predicate of its own: "detected,
        # unexplained" is exactly "neither C10 nor C11", and a function
        # restating that is a second place for the boundary to move.
        return MissClass("C12", "unresolved", None, f"{len(near)} candidates, none corroborated")

    # -- corrections: exactly one survivor, or nothing --------------------- #

    def tail_stated_sections(
        self, title: int, section: str, authority_text: str, *, letter: str | None = None
    ) -> tuple[str, ...]:
        """The lettered-with-tail readings the TEXT itself states, affirmed.

        ``12 USC 1735(f)-14`` states the tail ``-14``, so the reading it can
        possibly mean is 12 U.S.C. 1735f-14 and never 1735f: a family
        (1735f-14, 1735f-15, 1735z-11a, 1701q-1 ...) a truncating generator
        cannot reach at all, which is how the wrong survivor came to be
        manufactured. Enumerated EXACTLY -- ``section_is_enumerated``, never a
        printed range stub -- so a tail nothing prints returns nothing rather
        than a plausible neighbour.

        ``letter`` narrows to one parenthesised letter, which is what
        :meth:`correction_candidates` needs (it has already chosen the
        pinpoint it is reasoning about). A caller that has not chosen leaves it
        None and reads every letter the text states; more than one answer is
        an ambiguity for that caller to refuse, not for this method to break.
        """

        section = normalize_section(section)
        if not section:
            return ()
        text = normalize_section(authority_text)
        letters = re.escape(letter) if letter else r"[a-z]{1,4}"
        stated = {
            f"{section}{match.group(1)}-{match.group(2)}"
            for match in re.finditer(
                rf"(?<![0-9a-z]){re.escape(section)}\s*\(\s*({letters})\s*\)\s*-\s*([0-9a-z]+)", text
            )
        }
        return tuple(sorted(one for one in stated if self.section_is_enumerated(title, one)))

    def act_numbering_fence(
        self, title: int, section: str, act_sections: Iterable[ActSectionClaim] = ()
    ) -> tuple[ActSectionClaim, ...]:
        """The claims that make this token an ACT's section number, affirmed.

        Four tests, and all four are the fence:

        * **the parse as filed has no witness** — the Code prints no section by
          that name at all. This is the lost-space rule's first witness,
          restated for the same reason and with the same consequence: where the
          token IS a printed section, two real numbering systems spell one
          string and nothing here tells them apart, so the fence stays silent
          and the row keeps whatever refusal it already had. ``7 U.S.C. 6c`` is
          the specimen — the Code's own §6c AND the Commodity Exchange Act's
          §6c (→ 13a-1), 162 rows, untouched;
        * the act's own section number IS the filed token (``8a``);
        * it names a section of the SAME title that is **not** that token —
          where the act's numbering and the Code's agree there is no second
          system to be confused by (CEA §1a is 7 U.S.C. 1a);
        * and this oracle **enumerates** that section exactly, never through a
          printed range — which is what keeps CEA §8's second classification,
          the eliminated stub "12-1 to 12-3", from being offered as a reading.

        Returns them in a stable order so two survivors refuse the same way
        twice. A caller that passes nothing gets nothing: the association is
        the caller's fact, and an empty roster is a silence, not a licence.
        """

        section = normalize_section(section)
        if not section or self.section_exists(title, section):
            return ()
        claims = {
            (normalize_section(claim.section), claim.act_key, claim.act, claim.association): claim
            for claim in act_sections
            if claim.title == title
            and normalize_section(claim.act_section) == section
            and normalize_section(claim.section) != section
            and self.section_is_enumerated(title, claim.section)
        }
        return tuple(claims[key] for key in sorted(claims))

    def correction_candidates(
        self,
        title: int,
        section: str,
        authority_text: str,
        edition_year: int | None = None,
        act_sections: Iterable[ActSectionClaim] = (),
    ) -> tuple[Candidate, ...]:
        """Every reading of this citation the oracle affirms, each named.

        This is where a refusal becomes legible. ``5 USC 552(a)`` returns two
        candidates — FOIA subsection (a) and the Privacy Act at 5 U.S.C. 552a,
        both real — so :meth:`corrected_section` publishes neither.

        It is also where a B8 reading lives out its whole life. Since
        2026-08-23 B8 carries :attr:`Candidate.corrects` ``False``, so
        ``42 USC 1395(hh)`` names 42 U.S.C. 1395hh here, with its evidence, and
        :meth:`corrected_section` returns nothing for it however alone it
        stands. See :data:`CANDIDATE_ONLY_RULES`.

        ``act_sections`` are the acts the CALLER's own roster puts in front of
        this row (:class:`ActSectionClaim`). They are the one input here that
        is a corpus fact rather than an oracle one, and they do exactly one
        thing: strike A4's reading where the filed token is an act's own
        section number, and name the act's reading in its place. See the module
        docstring for the eight rows that bought the fence.
        """

        section = normalize_section(section)
        text = normalize_section(authority_text)
        window_start, window_end = ORACLE_WINDOW
        if edition_year is not None and not window_start <= edition_year <= window_end:
            return ()
        found: dict[tuple[int, str, str | None], Candidate] = {}

        def offer(candidate: Candidate) -> None:
            found.setdefault(candidate.target, candidate)

        pinpoint = (
            re.search(rf"(?<![0-9a-z]){re.escape(section)}\s*\(\s*([a-z]{{1,4}})\s*\)", text) if section else None
        )
        if pinpoint is not None:
            letter = pinpoint.group(1)
            lettered = section + letter
            structure = self.subsection_verdict(title, section, letter)
            follows_et_seq = re.search(
                rf"(?<![0-9a-z]){re.escape(section)}\s*\(\s*{letter}\s*\)\s*,?\s*et\.?\s*seq", text
            )
            if follows_et_seq and self.section_is_enumerated(title, lettered):
                # The one rule that removes the as-filed reading rather than
                # competing with it: "subsection (f) and following" is not a
                # citation form anyone writes.
                offer(
                    Candidate(
                        rule="B1-et-seq-follows-a-section",
                        title=title,
                        section=lettered,
                        subsection=None,
                        evidence=(
                            f"'et seq.' follows a section and never a subsection; {title} U.S.C. {lettered} is a "
                            "section the oracle prints"
                        ),
                    )
                )
            elif self.section_exists(title, section):
                # Without the "et seq." tell, both readings need the bare
                # section to be real: where it is not, the citation belongs to
                # class C3 (a real letter suffix eaten by the parenthetical
                # strip) and this module proposes nothing.
                #
                # The pinpoint survives unless the release point prints NO
                # lettered subsection on the section at all. A section whose
                # structure is unpublished keeps its pinpoint: that is the
                # coverage gap talking, not the Code.
                if not (structure.verdict == "absent" and not structure.lettered):
                    offer(
                        Candidate(
                            rule="parse-as-filed",
                            title=title,
                            section=section,
                            subsection=letter,
                            evidence=(
                                f"{title} U.S.C. {section} exists and its subsection structure does not refuse "
                                f"({letter}): {structure.verdict}"
                            ),
                        )
                    )
                # 12 U.S.C. 1735f is "Water and sewerage facilities"; the
                # mortgagee civil penalties the filer of "12 USC 1735(f)-14"
                # meant are 1735f-14. Truncating the stated tail put the
                # generator in a family it structurally could not reach
                # (1735f-14, 1735f-15, 1735z-11a, 1701q-1 ...) and manufactured
                # the single survivor that published the wrong one. So the
                # hyphenated lettered reading is enumerated FIRST, exactly --
                # never through a range stub -- and the bare lettered section
                # is the fallback for a text that states no tail. Same
                # precedence as :meth:`c3_proposals`: a tail the text states
                # outranks anything derived without it.
                affirmed = self.tail_stated_sections(title, section, authority_text, letter=letter)
                readings = list(affirmed) or (
                    [lettered] if self.section_is_enumerated(title, lettered) else []
                )
                # The doctrine, spelled out per candidate, in both directions:
                # the second clause is B8's whole argument where it holds, and
                # its own refutation where it does not (5 U.S.C. 552a is real
                # AND 552 carries a subsection (a), which is why that one is
                # two survivors).
                argument = (
                    f"the bare {title} U.S.C. {section} carries {len(structure.lettered)} lettered subsections, "
                    f"({letter}) among them"
                    if structure.verdict == "exists"
                    else f"the bare {title} U.S.C. {section} has no such lettered subsection "
                    f"(({letter}): {structure.verdict}, {len(structure.lettered)} lettered subsections printed)"
                )
                for name in readings:
                    offer(
                        Candidate(
                            rule="B8-lettered-section-rather-than-a-pinpoint",
                            title=title,
                            section=name,
                            subsection=None,
                            evidence=(
                                f"lettered section exists: {title} U.S.C. {name} is a section the oracle prints; "
                                + argument
                                + (f"; the text states the tail '-{name.split('-', 1)[1]}'" if affirmed else "")
                            ),
                        )
                    )

        split = re.fullmatch(r"(\d+)([a-z]+)", section)
        if split is not None:
            stem, tail = split.group(1), split.group(2)
            if self.section_exists(title, section):
                offer(
                    Candidate(
                        rule="parse-as-filed",
                        title=title,
                        section=section,
                        subsection=None,
                        evidence=f"{title} U.S.C. {section} is a section the oracle prints",
                    )
                )
            holds_the_letter = self.subsection_verdict(title, stem, tail).verdict == "exists"
            if self.section_is_enumerated(title, stem) and holds_the_letter:
                # A4's licence is that it never relocates -- and a token an
                # associated act numbers itself is the one place it does. The
                # claims are consulted HERE, inside A4's own branch, because
                # that is exactly where a wrong value is published today: a
                # token A4 never reads publishes nothing, and a reading that
                # ARRIVES where nothing stood is a missed witness with its own
                # evidence burden, not this fence's business. See the module
                # docstring for the 65 rows deliberately left where they are.
                struck = self.act_numbering_fence(title, section, act_sections)
                readings = {normalize_section(claim.section) for claim in struck}
                fenced_by = (
                    None
                    if not struck
                    else "; ".join(
                        f"{claim.act} numbers its own §{normalize_section(claim.act_section)} as "
                        f"{title} U.S.C. {normalize_section(claim.section)} (OLRC Table III {claim.act_key})"
                        for claim in struck
                    )
                    + f" -- {len(readings)} act reading(s) claim this token, so the lost-parenthesis reading "
                    "cannot be the identity"
                )
                offer(
                    Candidate(
                        rule="A4-subsection-rendered-as-a-lettered-section",
                        title=title,
                        section=stem,
                        subsection=tail,
                        evidence=(
                            f"{title} U.S.C. {stem} is a section and ({tail}) one of its subsections; the "
                            "parentheses were lost upstream"
                        ),
                        fenced_by=fenced_by,
                    )
                )
                # The pinpoint comes from the TEXT and not from the token: the
                # act's §8a(5) is one whole section in Table III, so the Code
                # prints its paragraphs under the same numbers at 12a, and "(5)"
                # is the filer's own. A token with no stated pinpoint ("7 USC
                # 8a", RIN 3038-AB50) publishes the identity alone.
                stated = re.search(
                    rf"(?<![0-9a-z]){re.escape(section)}\s*\(\s*([0-9]{{1,3}}|[a-z]{{1,4}})\s*\)", text
                )
                for claim in struck:
                    offer(
                        Candidate(
                            rule="act-section-under-a-usc-label",
                            title=title,
                            section=normalize_section(claim.section),
                            subsection=stated.group(1) if stated else None,
                            evidence=(
                                f"'{section}' is {claim.act}'s own section number, not the Code's: OLRC's "
                                f"Table III for {claim.act_key} classifies act §"
                                f"{normalize_section(claim.act_section)} to {title} U.S.C. "
                                f"{normalize_section(claim.section)}, which this oracle enumerates; the act is "
                                f"on this row's {claim.association} roster"
                            ),
                        )
                    )

        # The lost SPACE. Two witnesses, and both are required: the stem the
        # grammar published is ABSENT from the oracle -- no archive year and no
        # printed range prints it, so the parse as filed has no witness at all
        # -- and the fused token IS enumerated exactly. Then one reading
        # survives, and it is the one the operator names.
        #
        # Where the stem exists the rule stays SILENT rather than competing,
        # and the silence is the refusal: "15 USC 77 eee" is 15 U.S.C. 77eee
        # (Trust Indenture Act sec. 305) to any reader, and 15 U.S.C. 77 is
        # ALSO a current section of title 15 in the pinned release point -- two
        # real sections, one string, and nothing this module can consult tells
        # them apart. Measured over all 38,182 (title, section, text) keys the
        # pinned artifact files: 83 write a spaced suffix, 3 have an absent
        # stem AND an enumerated target (15 U.S.C. 78 -> 78o-10, 78j-1, 78k-1;
        # title 15 has no section 78), and the other 80 keep their as-filed
        # reading.
        if section.isdigit():
            for spaced in _SPACED_SUFFIX.finditer(text):
                if spaced.group("stem") != section or self.section_exists(title, section):
                    continue
                target = section + spaced.group("suffix") + (spaced.group("tail") or "")
                if not self.section_is_enumerated(title, target):
                    continue
                offer(
                    Candidate(
                        rule="space-lost-before-a-lettered-suffix",
                        title=title,
                        section=target,
                        subsection=None,
                        evidence=(
                            f"the text writes '{spaced.group(0)}' and a section's name never contains a space; "
                            f"{title} U.S.C. {target} is a section the oracle enumerates and "
                            f"{title} U.S.C. {section} is absent from every year it prints"
                        ),
                    )
                )

        # A recovery is offered here only when the damaged token is what the
        # parse published a prefix of -- "15 USC 80bll(a)" publishes section
        # "80". The section must be stated: an empty one is a prefix of every
        # token, and would turn "no section was parsed" into a correction of
        # nothing. Where the grammar dropped the token entirely (the list case,
        # "15 USC 80b-4, …, 80bll(a), …"), the recovery is
        # :meth:`recovered_lost_hyphen_sections`, keyed on the text alone.
        if section and not self.section_exists(title, section):
            for recovered in self.recovered_lost_hyphen_sections(title, authority_text):
                if recovered.original_section.startswith(section):
                    offer(
                        Candidate(
                            rule=recovered.rule,
                            title=title,
                            section=recovered.section,
                            subsection=None,
                            evidence=recovered.evidence,
                        )
                    )
        return tuple(found.values())

    def corrected_section(
        self,
        title: int,
        section: str,
        authority_text: str,
        edition_year: int | None = None,
        act_sections: Iterable[ActSectionClaim] = (),
    ) -> Correction | None:
        """The one surviving reading, or nothing. Never a choice among several.

        Two gates, and both must open. The reading must be the ONLY survivor,
        and its rule must be one this module will publish — see
        :data:`CANDIDATE_ONLY_RULES` for why B8 is not, and the module
        docstring for the review that demoted it. A B8 reading with no
        competitor is still only a candidate: :meth:`correction_candidates`
        names it, with its evidence, and nothing here picks it.

        A STRUCK reading is not a survivor. It is still named upstream, because
        a consumer counting readings has to see it, but it neither publishes
        nor blocks: that is how ``7 USC 8a(5)`` reaches 12a(5) with A4's 8(a)
        beside it, and how two act readings on one token refuse together.
        """

        candidates = self.correction_candidates(title, section, authority_text, edition_year, act_sections)
        survivors = tuple(one for one in candidates if one.fenced_by is None)
        if len(survivors) != 1 or not survivors[0].corrects:
            return None
        only = survivors[0]
        return Correction(
            rule=only.rule,
            title=only.title,
            original_section=normalize_section(section),
            section=only.section,
            subsection=only.subsection,
            evidence=only.evidence,
        )

    def recovered_lost_hyphen_sections(self, title: int, authority_text: str) -> tuple[Correction, ...]:
        """Sections the grammar dropped because a hyphen was lost, one survivor each.

        ``15 USC 80b-4, 80b-6(4), 80bll(a), 80b-3(c)(1)`` publishes three
        citations and drops the fourth. The operator is named — insert one
        hyphen, and read a trailing run of ``l``/``I``/``i`` as the digit 1 —
        and the recovered target must be in the **exact** set. Of the 14 tokens
        the grammar lists, this closes ``80bll`` -> 80b-11 and ``6bi`` -> 6b-1;
        the other twelve reach no candidate at all, which is the refusal an act
        index could not make honestly at any size — see the module docstring.
        """

        out: list[Correction] = []
        for match in _DAMAGED_TOKEN.finditer(str(authority_text or "")):
            token = normalize_section(match.group(1))
            if re.fullmatch(r"\d+([a-z])\1*", token) or self.section_exists(title, token):
                continue
            run = _ONE_TYPED_AS_A_LETTER.search(token)
            if run is None or run.start() == 0:
                continue
            target = f"{token[: run.start()]}-{'1' * len(run.group(0))}"
            if not self.section_is_enumerated(title, target):
                continue
            out.append(
                Correction(
                    rule="lost-hyphen-with-one-typed-as-a-letter",
                    title=title,
                    original_section=token,
                    section=target,
                    subsection=None,
                    evidence=(
                        f"'{token}' is one lost hyphen and {len(run.group(0))} digit 1 typed as a letter away from "
                        f"{title} U.S.C. {target}, which the pinned OLRC oracle enumerates"
                    ),
                )
            )
        return tuple(out)
