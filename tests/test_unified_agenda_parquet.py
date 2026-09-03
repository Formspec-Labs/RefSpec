"""The derived Unified Agenda tables consumers actually read."""

from __future__ import annotations

import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest

from refspec.registry.unified_agenda_parquet import (
    ACTIONS_SCHEMA,
    CFR_REFERENCES_SCHEMA,
    LEGAL_AUTHORITIES_SCHEMA,
)

ARTIFACT = Path(__file__).resolve().parents[1] / "output" / "registry-real-data-sources" / "unified-agenda-parquet"

@pytest.fixture(autouse=True)
def _the_built_artifact(request) -> None:
    """Skip a test that reads the gitignored built artifact when it is not
    built -- but ONLY such a test. This was a file-wide `pytestmark`, which
    also gated the producer-block unit tests below, none of which touches the
    artifact: on a fresh checkout every one of them SKIPPED, so a regression
    in the missing-module refusal or the repository guard passed that
    environment silently. `@pytest.mark.no_artifact` opts a test out.

    What this cannot see: a test that reads the artifact and forgets to say
    so is gated correctly by default (the default is to skip), but a test
    marked `no_artifact` that later grows a read of the artifact will fail
    rather than skip on a checkout without one. That is the direction to
    fail in, and it is the only way round this gate.
    """

    if ARTIFACT.is_dir() or request.node.get_closest_marker("no_artifact"):
        return
    pytest.skip("derived Parquet artifact is not built")


@pytest.fixture(scope="module")
def con():
    duckdb = pytest.importorskip("duckdb")
    return duckdb.connect()


def _one(con, sql: str):
    """The single value a query returns, with `{d}` bound to the artifact."""

    return con.execute(sql.format(d=ARTIFACT.as_posix())).fetchone()[0]


def _row(con, sql: str):
    """The single ROW a query returns, bound the same way."""

    return con.execute(sql.format(d=ARTIFACT.as_posix())).fetchone()


def _rows(con, sql: str):
    """Every row a query returns, bound the same way. Nine call sites spelled
    `.format(d=ARTIFACT.as_posix())` by hand before this existed."""

    return con.execute(sql.format(d=ARTIFACT.as_posix())).fetchall()


#: The five columns the U.S.C. section fence writes. Named once: two tests read
#: them, and they must stay contiguous where a reader meets them.
_SECTION_FENCE_COLUMNS = (
    "usc_section_verdict",
    "usc_section_verdict_reason",
    "usc_section_attested_at_edition",
    "usc_section_corrected",
    "usc_section_correction_evidence",
)

#: The correction split into the two facts a consumer keys on, beside the fence
#: that produced it.
_CORRECTED_KEY_COLUMNS = ("usc_section_corrected_section", "usc_section_corrected_pinpoint")

#: The three columns the act resolver and its sibling carry write: which OLRC
#: source classified the section filled, the reason where none was filled --
#: instead of the bare "failed" this table used to publish on 6,214 rows whose
#: parse had succeeded -- and which box supplied a carried act.
_ACT_RESOLUTION_COLUMNS = (
    "act_resolution_evidence",
    "act_resolution_reason",
    "act_resolution_sibling_ordinal",
)

#: The two columns the publisher's own CFR part authority note writes: the
#: verdict, and which part's note gave it.
_CFR_NOTE_COLUMNS = ("authority_in_own_cfr_note", "cfr_note_part")

#: The six columns a pinned recodification table writes beside the ONE
#: section-fence unknown it can answer: the verdict, every successor, which
#: former sections the verdict speaks for where the citation stated a span,
#: the pinpoint the table resolved where it stated one, which table said so,
#: and -- where no table was read at all -- why not.
_DISPOSITION_COLUMNS = (
    "usc_disposition_verdict",
    "usc_disposition_successors",
    "usc_disposition_span_members",
    "usc_disposition_pinpoint",
    "usc_disposition_refusal",
    "usc_disposition_table",
)

#: The two columns that say WHICH publisher field a citation was written in,
#: and which continuation rows repeat a box of the same record.
_CONTINUATION_COLUMNS = ("authority_source", "restates_box_citation")

#: The two columns the title carry writes: which earlier box supplied the
#: U.S.C. title, and the exact string the grammar was handed once it had one.
_TITLE_CARRY_COLUMNS = ("usc_title_carried_from_ordinal", "authority_carry_text")

#: The five columns the box-run join writes: which run of boxes one citation
#: list was cut across, the shape that made the run, the exact string handed to
#: the grammar, and which boxes the join absorbed.
_JOIN_COLUMNS = (
    "authority_box_run_start",
    "authority_box_run_length",
    "authority_join_rule",
    "authority_join_text",
    "superseded_by_join",
)

#: The two columns the scheme-label repair writes: the single edit it rests on,
#: spelled with the token it replaced, and which pinned oracle affirmed it.
_SCHEME_LABEL_COLUMNS = ("authority_label_corrected", "label_correction_evidence")

#: The three columns the recodification block gained on 2026-08-24, when the
#: table started being asked the citation's own question rather than a bare
#: section's. Named apart from the six because the other three are BUILT.
_DISPOSITION_COLUMNS_AWAITING_THE_REBUILD = (
    "usc_disposition_span_members",
    "usc_disposition_pinpoint",
    "usc_disposition_refusal",
)

#: What the pinned initialism roster said about a row, and on whose word:
#: "BBRA@0938 pinned-quote", "FSH@0596 not-an-act:directive". Added 2026-08-24
#: with the roster itself.
_INITIALISM_ROSTER_COLUMNS = ("act_initialism_roster",)

#: Every column the artifact on disk predates: the corrected-key split, the
#: act resolution's two, the CFR note join's two, the recodification's newest
#: three, the continuation's two, the scheme-label repair's two, the join's
#: five, the title carry's two and the initialism roster's one. The five fence
#: columns and the four verdicts that once waited here are BUILT, and a column
#: still listed after its rebuild is a pin excusing an absence that ended.
_COLUMNS_AWAITING_THE_REBUILD = frozenset(
    _CORRECTED_KEY_COLUMNS
    + _ACT_RESOLUTION_COLUMNS
    + _CFR_NOTE_COLUMNS
    + _DISPOSITION_COLUMNS_AWAITING_THE_REBUILD
    + _CONTINUATION_COLUMNS
    + _SCHEME_LABEL_COLUMNS
    + _JOIN_COLUMNS
    + _TITLE_CARRY_COLUMNS
    + _INITIALISM_ROSTER_COLUMNS
)





def _act_resolution_landed(con) -> bool:
    """Whether the built table carries the act resolver's columns yet.

    Three counts below move when it does -- the unreadable pool loses 27 boxes
    to the sibling-act carry and the year-less lexicon, and act-relative gains
    them. They are written as a pair of exact numbers chosen by this predicate
    rather than re-pinned to the scratch build and left red: both readings are
    pins, any OTHER movement still fails either way, and the day the rebuild
    lands nothing here has to be touched. Delete the predicate and the first
    number once it has.
    """

    return "act_resolution_evidence" in {
        row[0] for row in _rows(con, "describe select * from '{d}/unified_agenda_legal_authorities.parquet'")
    }



def test_the_schemas_name_the_publishers_text_alongside_the_parse() -> None:
    """A parse this module gets wrong must stay visible, not replace the source."""

    assert "reference_text" in CFR_REFERENCES_SCHEMA.names
    assert "authority_text" in LEGAL_AUTHORITIES_SCHEMA.names
    assert set(ACTIONS_SCHEMA.names) == {
        "rin",
        "publication_id",
        "cfr_reference_count",
        "legal_authority_count",
        "legal_authorities_declared_incomplete",
        "cfr_references_declared_incomplete",
    }

@pytest.mark.slow
def test_the_tables_carry_what_the_shared_grammar_reads(con) -> None:
    """One row per parsed citation, so a list reference is no longer head-only."""

    assert _one(con, "select count(*) from '{d}/unified_agenda_actions.parquet'") == 241_726
    # 445,064 before the Title 3 compilation diversion and the list-item
    # lookahead removed 213 fabricated rows ("3 CFR, 1977 Comp." read as part
    # 1977; a list swallowing the next citation's number).
    assert _one(con, "select count(*) from '{d}/unified_agenda_cfr_references.parquet'") == 444_847
    assert _one(
        con,
        "select count(*) from '{d}/unified_agenda_cfr_references.parquet' where cfr_section is not null",
    ) == 106_941
    # Damage is labelled, never filtered.
    assert _one(
        con,
        "select count(*) from '{d}/unified_agenda_cfr_references.parquet' "
        "where cfr_title_is_possible = false",
        # 159 before the Panama Canal correction: title 35 was real through
        # the 2000 revision, and 115 rows from 1990s editions cite it.
        # 44 -> 9 when the grammar stopped reading a stray label as a title:
        # 35 of those rows never named a title at all, and now say so.
    ) == 9


@pytest.mark.slow
def test_the_authority_field_is_no_longer_shipped_as_raw_text(con) -> None:
    """798,114 authority strings; every row typed, nothing vanishes.

    The full grammar (ranges by the ordering rule, chapters, IRC, title-form,
    lists, double-letter sections) plus five waves of corroboration leaves the
    unreadable residue pinned below. Every number in this file is measured
    from the built artifact; where a count and its prose disagree, the count
    is the fact and the prose was left behind by an earlier wave.
    """

    total = _one(con, "select count(*) from '{d}/unified_agenda_legal_authorities.parquet'")
    failed = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where authority_type = 'other'",
    )
    unstated = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where authority_type = 'unstated'",
    )
    # 12,393 -> 12,463 in the 2026-08-21 continuation: quoted placeholders
    # ('"Not Yet Determined"') and "Not applicable" state nothing too.
    # 12,464 -> 12,467: the kind table decides, so ". . ." with spaces
    # (RIN 0625-AA66, three editions) is the ellipsis it is.
    assert unstated == 12_467, "a placeholder is not a failed parse"
    # 798,114 -> 797,170, measured value-by-value against a faithful rebuild
    # of the prior code (same editions, same oracles): 1,038 ghost rows left
    # (a date's year read as a U.S.C. section, "18 U.S.C. 1987" out of
    # "November 1, 1987"), 94 appendix sections arrived once an appendix
    # citation could seed a list, and three ". . ." rows changed type. That
    # is the whole delta. Nothing real left: the "18 U.S.C. 4082" list that
    # lost its two year-ghosts kept all eight sections, 5006 included.
    #
    # 797,170 -> 797,198: an order list is a list (e6514fa7), so "Secretary's
    # Orders 4-75 and 14-75" yields two rows where it yielded one.
    #
    # 797,198 -> 797,193: grammar wave 6, attributed value by value against a
    # faithful build of the prior code — the zero pad leaves the identity
    # ("26 USC 0892" -> 892), an expanded span is partial never ok, "27 USC
    # 1087" is CITES (treaty; its five duplicate instrument-name rows are the
    # whole -5), "6002Omnibus" -> 6002, and a compilation year is not a CFR
    # part. Nothing else moved.
    #
    # 797,193 -> 798,518 at rebuild #8 (94ddfb03): +1,325, exactly the new
    # ADDITIONAL_INFO continuation rows -- count(*) where authority_source !=
    # 'box' is 1,325 (405 additional-info:additional-legal-authority + 920
    # additional-info:legal-authority-cont); every box row is untouched
    # (count(*) where authority_source = 'box' is 797,193, the prior total).
    #
    # 798,518 -> 799,126 at rebuild #9 (d7d96b95 H4, 6e9a15ae H1, 9cab6f65 H2,
    # 66d96462 H3): 621 vanished (every one authority_type='other' and
    # parse_status='failed', all-NULL) and 1,229 arrived, net +608. Verified
    # with tools/agenda_value_diff.py against the byte-identical rebuild-8
    # baseline, and independently by type+status shape count(*) deltas on
    # this artifact vs that baseline: usc/partial +577 (H1), usc/ok +1 (H1),
    # statute_at_large/partial +6 (H1), public_law/partial +2 (H1) = H1's
    # 586 (authorityJoinRows); usc/corroborated +156 split by marker into
    # corroboration_rule='one-edit-on-a-scheme-label' 45 (H4) and
    # usc_title_carried_from_ordinal is not null 111 (H2, = uscTitleCarryRows);
    # statute_at_large/corroborated +3, all corroboration_rule='one-edit-on-
    # a-scheme-label' (H4); act_relative/failed +471 and act_relative/
    # corroborated +13 (H3, 484 total, exactly the other/failed rows H3
    # retypes). 577+1+6+2+45+111+3+471+13 = 1,229; other/failed -621.
    #
    # 799,126 -> 799,127 at rebuild #11 (f3a8b319): +1, exactly the
    # "/CAA 112 & 103" box (RIN 2070-AC76, publication 199510, ordinal 3),
    # which the fixed abbreviation-list regex now reads as TWO citations
    # (CAA 112 and CAA 103, both agency-roster-initialism) where it used to
    # read as one unparsed "other" row -- verified: the row exists at
    # citation_ordinal 0 in both builds and ONLY at citation_ordinal 1 in
    # this one.
    # Rebuild #15 (2026-09-01 wave, research/evidence/rebuild15-delta-2026-09-01.txt): 800,573 -> 800,558
    # (-15) = 6 reg-dot anchor rows withheld + 9 stat-page filer members
    # refused at materialization (both REF-062).
    assert total == 800_558
    # 12,244 -> 9,280 -> 6,997 -> 4,239 across three censuses. The third
    # wave's share: the agency-level abbreviation oracle (the RIN's leading
    # four digits are the OMB agency code), five whole-value abbreviation
    # shapes, the act-prose spelling operators (sections-in-front,
    # parenthetical drops, year-prefix reordering, designator strips, the
    # and-dropped closure), label-damage tolerances (UCS, E0, Statue, Fed.
    # Reg., USCS, fused Stat separators), lettered Stat pages, compilation
    # fragments, treaty-instrument typing, four directives systems, FAR's
    # self-citation, and two more roster-corroborated Public Law shapes;
    # what remains is damage or text no pinned oracle answers.
    #
    # 4,239 -> 3,516 in the fourth wave, which changed the ORACLE rather than
    # the operators: a rule's own citation history at the RIN and then its
    # agency answers the shapes that lost a label or a container (a bare
    # section list, a title-less "USC 44101", a label-less "49 46105", a
    # volume-less "Stat. 2936", an unlabelled Public Law pair), the corpus's
    # own parenthetical gloss discriminates an abbreviation its roster
    # answers several ways ("Medicare Modernization Act (MMA)"), the
    # word-prefix operator wave 3 refused on yield is licensed by a measured
    # zero false positives once the agency roster fences it, an explicit
    # section marker defeats the year-shaped-token guard, and four
    # whole-value label repairs read a lowercased "stat", a stray comma, a
    # stuttered "et" and a dropped U.
    #
    # 3,516 -> 3,324 in the fifth wave, which measured every remaining ORACLE
    # escalation and refused all of them with a number (the corpus-wide
    # section->title read is right 0.6816 on the agency-silent rows it would
    # answer; the record's own authority list 0.9662; the corpus-wide
    # abbreviation roster invents a wrong survivor 15.25% of the time even
    # date-bounded; the rule's CFR title agrees with its U.S.C. title 0.4774
    # of the time). Every recovery below therefore comes from an OPERATOR
    # feeding an oracle already fenced and already measured.
    #
    # 2,966 -> 2,963: the three spaced ellipses above were never failures.
    # 2,963 -> 2,960: "7 U.S. 6g" is a lost C, settled by the publisher's own
    # authority note for 17 CFR part 1 (2fc3fc7b).
    # 2,960 -> 2,933: the sibling-act carry reads three boxes of EPA
    # 2040-AE95's Clean Water Act list that hold a section number and nothing
    # else ("316", "401", "and 510"), and the year-less lexicon reads 24 more
    # naming the Atomic Energy Act and the Food Stamp Act.
    #
    # 2,933 -> 2,937 at rebuild #8 (94ddfb03): +4, the continuation module's
    # own "other/failed" bucket -- a prose delegation and two lists the raw
    # XML cuts mid-sentence -- count(*) where authority_type = 'other' and
    # authority_source != 'box' is 4, matching the receipt's
    # authorityContinuationRowsByTypeAndStatus["other/failed"].
    #
    # 2,937 -> 2,316 at rebuild #9: -621, every one of the vanished rows
    # named above (count(*) where authority_type='other' and
    # parse_status='failed' on the rebuild-8 baseline is 2,937; on this
    # artifact it is 2,316; the 621-row difference is exactly the VANISHED
    # population the total-rows pin above proves).
    #
    # 2,316 -> 2,108 at rebuild #11: -208, every one of them a row that left
    # authority_type='other' -- 204 to act_relative (#56's widened act-name
    # walk and index-holds fixes, 34; #44/45's initialism roster and
    # sibling-act carry, 170) and 4 to public_law (#56's new
    # reordered-public-law-roster-existence rule). Proved by
    # tools/agenda_value_diff.py's VANISHED count against the rebuild-10
    # baseline and independently by a keyed join: count(*) where
    # authority_type='other' on the rebuild-10 baseline joined against this
    # artifact on (rin, publication_id, ordinal, citation_ordinal) shows
    # exactly 208 rows whose new authority_type is no longer 'other', none
    # of them arriving from anywhere else (zero departures the other
    # direction).
    # Rebuild #14 (2026-08-31 wave, research/evidence/rebuild14-delta-2026-08-31.txt):
    # 2,108 -> 1,980, the 95 rows the six roster retiers resolve plus the 33
    # apostrophe-year rows, all leaving 'failed' for act_relative/corroborated.
    # Rebuild #15 (2026-09-01 wave): 1,980 -> 2,148 (+168), the reg-dot anchor
    # boxes whose only citation is now withheld and which fall back to
    # other/failed (REF-062) -- 168 retyped + 1 kept usc-with-null-section
    # + 6 removed = the 175 rows the fence's own DELTAS declared.
    assert failed == (2_148 if _act_resolution_landed(con) else 2_960)
    ranges = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where usc_section_end is not null",
    )
    assert ranges > 45_000, "the ordering rule splits real ranges at scale"
    kinds = _rows(
        con,
        "select distinct authority_type from '{d}/unified_agenda_legal_authorities.parquet'",
    )
    assert {row[0] for row in kinds} == {
        "usc",
        "usc_chapter",
        "public_law",
        "executive_order",
        "statute_at_large",
        "cfr",
        "reorganization_plan",
        "act_relative",
        "case_citation",
        "presidential_document",
        "administrative_order",
        "treaty",
        "constitution",
        "eo_compilation",
        "federal_register",
        "revised_statute",
        "dc_code",
        "unstated",
        "other",
    }
    # The OLRC index is the grammar for act-relative rows: 4,858 -> 5,721 ->
    # 8,515 after the wave-3 prose operators and the agency-level
    # abbreviation oracle; 8,896 after wave 4's gloss discriminator,
    # year-first subsequence, roster-fenced word prefix, and the act sections
    # the citation-history oracle read out of bare number lists. The key is
    # always the canonical OLRC spelling.
    acts = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where authority_type = 'act_relative'",
    )
    # And act-relative gains exactly what the unreadable pool lost: 9,065 +
    # 27 = 9,092.
    # 9,092 -> 9,576 at rebuild #9 (66d96462, H3): +484, the 471 other/failed
    # rows retyped act_relative/failed (act_not_in_index) plus the 13 retyped
    # act_relative/corroborated (index-holds-the-stated-name, the year-fence
    # fix) -- count(*) where authority_type='act_relative' moves 9,092 ->
    # 9,576 on this artifact vs the rebuild-8 baseline, and no other unit
    # touches act_relative (H1/H2/H4 mint usc/statute_at_large/public_law
    # rows only).
    #
    # 9,576 -> 9,781 at rebuild #11: +205, zero departures, all arrivals from
    # 'other' (204) plus the one brand-new /CAA-112-&-103 citation. #56
    # contributes 34 (the widened act-name walk, all with
    # act_initialism_roster and act_resolution_sibling_ordinal both NULL);
    # #44/45 contributes 171 (the pinned-roster-initialism tiers, the
    # sibling-act carry, and the growth of agency-roster-initialism /
    # agency-gloss-narrowed-initialism -- every one with a roster note or a
    # sibling ordinal, or under a rule this rebuild's own census already
    # ties to #44/45 exclusively). 34 + 171 = 205.
    # Rebuild #14 (2026-08-31 wave): 11,209 -> 11,337, the 128 rows retyped act_relative.
    assert acts == (11_337 if _act_resolution_landed(con) else 9_065)
    appendix = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' where usc_appendix",
    )
    # 4,185 -> 4,194: the appendix marker now reads in any case ("5 USC APP").
    # 4,199 -> 4,293: an appendix citation seeds a section list like any
    # other, so "46 app USC 808, 839" yields 839 as an appendix section too.
    # 4,293 -> 4,314 at rebuild #9: +21, entirely H1's join -- count(*) where
    # authority_type='usc' and parse_status='partial' and usc_appendix is
    # 1,329 on the rebuild-8 baseline and 1,350 here (+21); the same shape
    # restricted to parse_status='ok' is unchanged (2,964 both builds), and
    # neither H2's title-carry rows nor H4's scheme-label rows carry
    # usc_appendix (both count 0 against this predicate).
    assert appendix == 4_314, "an appendix section is not a title-proper section"
    # Series-bound verdicts against web-verified facts (USC 1-54 minus
    # never-enacted 53; EO series through 14420; numbered PLs 57th-119th
    # Congress; Stat volumes through 140 = 2026). Every flagged row decodes
    # as explicable damage — "Pub. L. 155-271 (October 24, 2018)" is 115-271,
    # the SUPPORT Act; "188 Stat 445" sits beside "PL 108-199" which IS 118
    # Stat — but decoding needs cross-field inference, which is guessing, so
    # the rows stay labelled rather than repaired.
    # 90 -> 91 out-of-series Public Laws: the mojibake-dash fix made
    # "PL 220\x96432, Div A, 122 Stat 4848 et seq" readable, and its congress
    # 220 is beyond the series — a new specimen labelled, not repaired (the
    # named congress-token operators cannot reach 110 from 220).
    # These are the DATED verdicts: each judges the citation against the series
    # as it stood in the edition's own year, which is what
    # test_a_series_verdict_is_dated_to_the_edition_that_made_it pins.
    out_of_series = {
        "usc_title_is_possible": 134,
        "eo_in_known_series": 7,
        "pl_congress_in_series": 92,
        "stat_volume_in_series": 16,
    }
    for column, expected in out_of_series.items():
        got = _one(
            con,
            "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
            f"where {column} = false",
        )
        assert got == expected, column


@pytest.mark.slow
def test_the_timetable_table_carries_the_fr_join_surface(con) -> None:
    """36,558 RINs cite FR documents in their timetables; the join is
    (fr_volume, fr_page) -> corpus start page. Built because a consumer was
    about to re-read 981 MB of XML for exactly this.

    The last two pins are measured on the scratch build of builder
    sha256:125c291f and await the rebuild; everything above them describes the
    artifact on disk today."""

    total = _one(con, "select count(*) from '{d}/unified_agenda_timetables.parquet'")
    ok = _one(
        con,
        "select count(*) from '{d}/unified_agenda_timetables.parquet' where parse_status = 'ok'",
    )
    failed = _one(
        con,
        "select count(*) from '{d}/unified_agenda_timetables.parquet' where parse_status = 'failed'",
    )
    rins = _one(
        con,
        "select count(distinct rin) from '{d}/unified_agenda_timetables.parquet' "
        "where parse_status in ('ok', 'positional', 'relabeled')",
    )
    assert total == 671_959
    assert ok == 276_795
    # The residue is real publisher damage the grammar refuses to guess at:
    # a lost F ("76 R 11462"), CFR citations sitting in the FR column, and
    # bare "volume page" strings with no FR token to anchor on.
    positional = _one(
        con,
        "select count(*) from '{d}/unified_agenda_timetables.parquet' "
        "where parse_status = 'positional'",
    )
    # "71 66120" and "76 R 11462": two plausible numbers in a column whose
    # semantics ARE the anchor — read positionally, labelled as such, never
    # "ok". 102 -> 109 in the continuation: the stray set admits the
    # transposed label ("74 RF 31642"), the stuttered label ("79 FR FR
    # 54588") and the slashed separator ("89 /FR 81156"); "NFR", "DR" and
    # "FSR" stay refused because no single named operation derives them.
    assert positional == 109
    relabeled = _one(
        con,
        "select count(*) from '{d}/unified_agenda_timetables.parquet' "
        "where parse_status = 'relabeled'",
    )
    # "84 CFR 1402" in the FR column: a text whose own numbers refute its
    # claimed scheme (title 84 does not exist; 0 of 64 parse as valid CFR)
    # while fitting the column's scheme exactly. The C is the damage.
    assert relabeled == 64
    assert rins == 36_587
    # The eight that remained after the text-grounded grammars had their say
    # are damage to five real Federal Register documents, and no reading of the
    # TEXT reaches them: the pinned roster does. "failed" is now empty and they
    # say "corroborated" instead, with the document in the correction columns
    # and the filer's text untouched beside it.
    _awaits_the_rebuild(
        con, "fr_correction_evidence", _FR_ROSTER_SCRATCH_BUILDER, table="unified_agenda_timetables"
    )
    corroborated = _one(
        con,
        "select count(*) from '{d}/unified_agenda_timetables.parquet' "
        "where parse_status = 'corroborated'",
    )
    assert failed == 0
    assert corroborated == 8


@pytest.mark.slow
def test_projected_actions_keep_their_zero_day_dates(con) -> None:
    """"11/00/2026" is a projected month; normalizing it would invent a date."""

    zero_day = _one(
        con,
        "select count(*) from '{d}/unified_agenda_timetables.parquet' "
        "where date_text like '%/00/%'",
    )
    assert zero_day > 100_000
    absent = _one(
        con,
        "select count(*) from '{d}/unified_agenda_timetables.parquet' where parse_status = 'absent'",
    )
    assert absent > 300_000, "projected actions carry no citation, and that is not a failure"


@pytest.mark.slow
def test_public_law_corrections_are_corroborated_and_preserve_the_original(con) -> None:
    """The correction machinery relabels a damaged Public Law only when named
    damage operators yield exactly one survivor against the pinned 21,039-law
    roster (57th-119th; the 118th and 119th needed a second row grammar after
    congress.gov moved the PL cell inside a PDF anchor). Three operator
    families qualify, each with its evidence named per row:

    - unique-roster-existence (2): 'Pub. L. 1014-410' is 101-410 with a
      dropped digit; the grammar read the damaged pair, so public_law keeps
      the damaged reading beside the correction.
    - unique-dash-insertion (17): 'Pub. L. 108199' fused its separator; a
      dash inserted at each split leaves exactly one roster-existent
      congress. 6 -> 17 in wave 3: the fused form may carry the value's own
      section tail ('Pub. L. 10811, sec 1503' is 108-11).
    - space-separator-roster-existence (18): 'PL 95 616' kept its pair but
      lost the glyph.
    - to-separator-roster-existence (35, wave 3): 'Pub. L. 111 to 203'
      writes the range word where the dash belongs; a bare law-number range
      names no congress and recovers nothing, so roster-existence of the
      pair is the only surviving reading (Dodd-Frank, here).
    - reordered-public-law-roster-existence (4, rebuild #11's #56, a08b5bdb):
      '114 Pub. L. 185' writes the congress AHEAD of the label instead of
      before the dash; the two other orderings a citation could take are not
      roster-existent, so reading the pair as printed is the only survivor.
      These four rows were counted under the scheme-label rule's own
      no-single-corroborated-reading refusal before this rule intercepted
      them (test_the_scheme_label_census_is_the_receipts).

    All but the roster-existence pair parse to nothing, so they carry
    parse_status 'corroborated' and a NULL public_law — the reading exists
    only in the correction columns. Uncorroborated candidates stay labelled
    out-of-series rather than repaired."""
    rows = _rows(
        con,
        "select authority_text, public_law, public_law_corrected, pl_correction_evidence, parse_status "
        "from '{d}/unified_agenda_legal_authorities.parquet' "
        "where public_law_corrected is not null"
    )
    # 335 -> 339 at rebuild #11 (#56, a08b5bdb): +4, entirely the new
    # reordered-public-law-roster-existence evidence -- count(*) where
    # pl_correction_evidence = 'reordered-public-law-roster-existence' is 4
    # and every other evidence's own count is unchanged against the
    # rebuild-10 baseline.
    assert len(rows) == 339
    by_evidence: dict[str, int] = {}
    for text, original, corrected, evidence, status in rows:
        by_evidence[evidence] = by_evidence.get(evidence, 0) + 1
        if evidence == "unique-roster-existence":
            assert text == "Pub. L. 1014-410"
            assert original == "1014-410", "nothing vanishes: the damaged reading stays"
            assert corrected == "101-410"
        else:
            assert original is None, "the grammar read nothing; only the roster did"
            assert status == "corroborated"
    assert by_evidence == {
        "unique-roster-existence": 2,
        "unique-dash-insertion": 17,
        "space-separator-roster-existence": 18,
        "to-separator-roster-existence": 35,
        # Wave 4: "89-670 and 91-605" states both halves and no label, so the
        # competing reading is a section range rather than a damaged pair.
        # Three fences settle it — the pinned congress.gov roster holds the
        # pair, the citing rule or its agency cites that law elsewhere, and
        # the same pool knows no section by the congress number.
        "roster-existent-public-law-pair": 40,
        # A public law recovered from the sibling slots around a bare section:
        # the publisher writes one citation across several elements, and these
        # are the runs a single in-series law bounds.
        "list-run-bounding-public-law": 87,
        "rin-history-section-list": 136,
        # New at rebuild #11 (#56, a08b5bdb): '114 Pub. L. 185' and
        # '94 Pub. L. 588', two texts over four rows (RINs 1880-AA89 x2
        # editions, 0596-AD59 and 0596-AD61 x1 each).
        "reordered-public-law-roster-existence": 4,
    }


@pytest.mark.slow
def test_the_continuations_families_are_measured_not_asserted(con) -> None:
    """The 2026-08-21 residue anatomy, pinned: each new family's rows exist
    at the measured scale, and every corroborated act row names its oracle's
    survivor in act_key."""

    counts = {
        row[0]: row[1]
        for row in _rows(
            con,
            "select authority_type, count(*) from "
            "'{d}/unified_agenda_legal_authorities.parquet' "
            "where authority_type in ('federal_register', 'revised_statute', 'dc_code') "
            "group by 1"
        )
    }
    # federal_register 2,049 -> 2,070: the Bluebook "Fed. Reg." longhand.
    # 2,070 -> 2,080 in wave 5: "60 CFR 15845" claims a CFR title the CFR
    # does not have and states a real Register volume and page, so the text's
    # own numbers refute its claimed scheme (60 FR 15845 is a March 1995 page,
    # web-verified 2026-08-22).
    # 2,080 -> 2,114 at rebuild #8 (94ddfb03): +34, the continuation rows
    # typed federal_register -- count(*) where authority_type =
    # 'federal_register' and authority_source != 'box' is 34, matching
    # authorityContinuationRowsByTypeAndStatus["federal_register/partial"].
    # revised_statute and dc_code are untouched (no continuation row is
    # either type).
    assert counts == {"federal_register": 2_114, "revised_statute": 118, "dc_code": 232}
    corroborated_acts = _row(
        con,
        "select count(*), count(act_key) from "
        "'{d}/unified_agenda_legal_authorities.parquet' "
        "where parse_status = 'corroborated' and authority_type = 'act_relative'",
    )
    # 339 -> 2,259: the agency-level oracle (RIN's OMB agency-code prefix)
    # answers where the single RIN's roster was silent, with zero ambiguous
    # survivors and full agreement on every row both oracles answer.
    # 2,259 -> 2,640 in wave 4: the anchored-subsequence initialism with the
    # year filtering candidates first, the corpus's own gloss discriminating
    # a roster that answers several ways, the roster-fenced word-prefix
    # operator, the section-marker fix, and the bare-section-list rows the
    # citation-history oracle typed as act sections.
    # The sibling-act carry is a corroboration like the rest, so it lands here
    # too: the act came from the box beside this one, not from the grammar.
    # +4: three carries and one "Atomic Energy Act, Reorg Plan 3" the
    # index-holds rule can read once the year-less stem answers.
    # 2,786 -> 2,799 at rebuild #9 (66d96462, H3): +13, exactly the 13
    # other/failed rows retyped act_relative/corroborated under
    # index-holds-the-stated-name (the year-fence fix: a number a row
    # states as its own section is not a year) -- count(*), count(act_key)
    # where parse_status='corroborated' and authority_type='act_relative'
    # moves 2,786 -> 2,799 on this artifact vs the rebuild-8 baseline, and
    # every one of the 13 new rows carries an act_key (confirmed against
    # the 471 act_relative/failed siblings, which do not).
    #
    # 2,799 -> 2,985 at rebuild #11: +186, by corroboration_rule against the
    # rebuild-10 baseline -- #56 contributes +15, entirely
    # index-holds-the-stated-name (144 -> 159); #44/45 contributes +171:
    # agency-roster-initialism +24 (2,290 -> 2,314), agency-gloss-narrowed-
    # initialism +1 (150 -> 151), and four brand-new rule names totalling
    # +146 (pinned-roster-initialism:pinned-quote 87, :candidate-index-match
    # 13, :reverse-pl-verified 7, :self-glossing 5, sibling-act-from-an-
    # earlier-box 34). Every other rule's count is unchanged. 15 + 171 = 186.
    # Rebuild #14 (2026-08-31 wave, research/evidence/rebuild14-delta-2026-08-31.txt): 4,413 -> 4,541, the same 128 rows.
    carried = 4_541 if _act_resolution_landed(con) else 2_782
    assert corroborated_acts == (carried, carried), "every corroborated row names its act"
    # The RS namespace never leaks into U.S.C. columns.
    leaked = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where authority_type = 'revised_statute' and usc_title is not null",
    )
    assert leaked == 0


@pytest.mark.slow
def test_the_third_waves_families_are_measured_not_asserted(con) -> None:
    """The 2026-08-22 wave, pinned at artifact scale: lettered Stat pages
    carry their identity in exactly one page column; instrument-name treaty
    rows and the four directives systems exist at the measured scale."""

    lettered = _row(
        con,
        "select count(*), count(distinct authority_text) from "
        "'{d}/unified_agenda_legal_authorities.parquet' "
        "where statute_page_text is not null",
    )
    # 206 rows over 31 spellings — the failed pool held 46; the rest hide in
    # previously-partial strings ("sec 1505 of PL 106-554, 114 Stat
    # 2763A-326 to 2763A-328").
    assert lettered == (205, 30)
    both = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where statute_page_text is not null and statute_page is not null",
    )
    assert both == 0, "exactly one of the two page columns states the page"
    treaty = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where authority_type = 'treaty'",
    )
    # 168 -> 201: title 27 stops at 228, so "27 U.S.C. 1087" is 27 U.S.T.
    # 1087, CITES (86091be2) — 38 rows retyped, 5 duplicate name rows gone.
    assert treaty == 201, "series citations plus instrument-name rows"
    orders = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where authority_type = 'administrative_order'",
    )
    # 1,211 -> 1,244 in wave 5: "USIA Delegation Order No. 85.5" and the DOE
    # delegation orders spell the word "Order" after "Delegation", which the
    # kind alternation refused (16 rows), and a number may end in a letter
    # ("00-004.00A").
    # 1,244 -> 1,272: an order list is a list (e6514fa7) — "Secretary's Orders
    # 4-75 and 14-75", Interior 3299 + 3302, DHS 0170.1 + 5110 — and the
    # number has a right edge, so "Order No. 3-81, 46 FR 31117" no longer
    # publishes order "4".
    # 1,272 -> 1,298 at rebuild #8 (94ddfb03): +26, the continuation rows
    # typed administrative_order -- count(*) where authority_type =
    # 'administrative_order' and authority_source != 'box' is 26, matching
    # authorityContinuationRowsByTypeAndStatus["administrative_order/partial"].
    assert orders == 1_298


# --------------------------------------------------------------------------- #
# The 2026-08-21 residue continuation: derivation helpers, tested without the
# artifact so the rules hold even where the build has not run.


def test_the_spelling_closure_derives_variants_and_refuses_collisions() -> None:
    """Year styles, ampersands and the year-less spelling are derived from
    the pinned index by convention; a variant reachable from two canonicals
    is dropped, because ambiguity refuses."""

    from refspec.registry.unified_agenda_parquet import _act_name_spelling_closure

    lookup = _act_name_spelling_closure({
        "motor carrier act, 1935",
        "motor carrier act of 1980",
        "fair labor standards act of 1938",
        "clean air act amendments of 1966",
        "clean air act amendments of 1990",
        "federal property and administrative services act of 1949",
    })
    assert lookup["motor carrier act of 1935"] == "motor carrier act, 1935"
    assert lookup["fair labor standards act"] == "fair labor standards act of 1938"
    assert (
        lookup["federal property & administrative services act of 1949"]
        == "federal property and administrative services act of 1949"
    )
    # "motor carrier act" reaches 1935 and 1980; "clean air act amendments"
    # reaches 1966 and 1990: both refused.
    assert "motor carrier act" not in lookup
    assert "clean air act amendments" not in lookup


def test_two_names_the_tool_has_made_one_act_are_not_two_acts() -> None:
    """The year-less refusal counts ACTS, not names, once it can tell.

    "Atomic Energy Act" reaches the acts of 1946 and of 1954 and was refused
    for it -- but the Popular Name Tool stores the 1946 entry as RENAMED to the
    1954 one and gives the 1954 name the 1946 act's Table III key, so the two
    names are one act with one classification table. Where the tool's own
    cross-references say that, the stem answers; where they do not, it is
    refused exactly as before. The act published is the one the chain resolves
    TO, never whichever name the loop reached first, so the key cannot depend
    on iteration order.
    """

    from refspec.registry.unified_agenda_parquet import _act_name_spelling_closure

    names = {"atomic energy act of 1946", "atomic energy act of 1954",
             "clean air act amendments of 1966", "clean air act amendments of 1990"}
    renamed = {"atomic energy act of 1946": "atomic energy act of 1954"}
    resolves = lambda name: renamed.get(name, name)  # noqa: E731 - the tool's chain, in one line
    assert "atomic energy act" not in _act_name_spelling_closure(names)
    widened = _act_name_spelling_closure(names, resolves)
    assert widened["atomic energy act"] == "atomic energy act of 1954"
    # A stem two real acts claim is still refused, resolver or no resolver.
    assert "clean air act amendments" not in widened


def test_a_yearless_listed_name_answers_to_its_own_enacting_years_date() -> None:
    """The year rule supplies a missing year and never strips a superfluous one.

    Review #2's class G measured the asymmetry: "Waste Isolation Pilot Plant
    Land Withdrawal Act of 1992" is the tool's own name for Pub. L. 102-579
    plus the year that law was approved, and it failed as ``act_not_in_index``
    while the year-LESS spelling of a year-BEARING name has always answered.

    The year is admitted only where a source states it OF THAT ACT -- the
    session-law Table III key, or the pinned public-law roster's approval date
    -- which is what separates the three shapes this corpus offers from the
    four beside them.
    """

    from refspec.registry.act_resolution import ActIndex
    from refspec.registry.unified_agenda_parquet import (
        _act_enactment_years,
        _act_name_spelling_closure,
    )

    index = ActIndex(
        table3_key_by_name={
            "waste isolation pilot plant land withdrawal act": "102-579",
            "refuge recreation act": "87-714",
            "buy indian act": "1910:431",
            "clean air act": "1955:360",
            "clean air act amendments of 1990": "101-549",
            "soil conservation and domestic allotment act": "1935:85",
            "social security act": "1935:531",
            "fair labor standards act of 1938": "1938:676",
            "space act of 2015": "114-90",
            "adult education act": "89-750",
            "adult education act of 1966": "89-750",
        }
    )
    roster = (
        {
            (102, 579): "10/30/1992",
            (87, 714): "09/28/1962",
            (114, 90): "11/25/2015",
            (89, 750): "11/03/1966",
        },
        {},
    )
    years = _act_enactment_years(index, roster)
    # A name that already carries a year is never given a second one, so no
    # entry that distinguishes its family by year is reachable under another.
    assert "clean air act amendments of 1990" not in years
    assert "fair labor standards act of 1938" not in years
    assert years["waste isolation pilot plant land withdrawal act"] == "1992"
    assert years["buy indian act"] == "1910"

    names = set(index.table3_key_by_name)
    narrow = _act_name_spelling_closure(names)
    widened = _act_name_spelling_closure(names, enactment_years=years)

    # The filer's own spellings, verbatim from the corpus, in all three
    # punctuations the tool itself alternates between.
    for stated, act in (
        ("waste isolation pilot plant land withdrawal act of 1992",
         "waste isolation pilot plant land withdrawal act"),
        ("refuge recreation act of 1962", "refuge recreation act"),
        ("buy indian act 1910", "buy indian act"),
        ("buy indian act, 1910", "buy indian act"),
    ):
        assert stated not in narrow
        assert widened[stated] == act

    # The paired negatives, every one of them a real value in this corpus. The
    # year is not the act's own, so the act is not named: 1990 belongs to the
    # amendments the index lists separately, 1936 and 1886 belong to nothing,
    # and "Space Act" is not a listed name at all.
    for refused in (
        "clean air act of 1990",
        "soil conservation and domestic allotment act of 1936",
        "social security act of 1886",
        "fair labor standards act of 1939",
        "space act of 1958",
    ):
        assert refused not in widened
    # Nothing the narrow closure answered moves or is lost. A date read off a
    # public law is weaker than a year the tool itself wrote into a name, so
    # where both reach one spelling the tool's own name keeps it: "adult
    # education act of 1966" is a LISTED name and also the enacting year of the
    # listed "adult education act", and it stays pointed at the listed one.
    assert not set(narrow) - set(widened)
    assert {k: v for k, v in widened.items() if narrow.get(k, v) != v} == {}
    assert widened["adult education act of 1966"] == "adult education act of 1966"


@pytest.mark.slow
def test_the_year_less_lexicon_is_widened_by_four_names_and_refuses_634() -> None:
    """Measured against the pinned index, not asserted.

    The widening is the whole of item 4 that this checkout can honestly do:
    5,292 year-less stems already answered, 638 collided, and reading the
    tool's renames turns exactly four of those into answers. It recovers review
    A's row 3 -- "Atomic Energy Act sec 275" is 42 U.S.C. 2022, "a lexicon miss
    (no year) wearing a parse-failure costume" -- and the Food Stamp Act's
    section 12, and nothing else.
    """

    from pathlib import Path as _Path

    from refspec.registry.act_resolution import ActIndex
    from refspec.registry.citation_grammar import find_act_relative_citations
    from refspec.registry.unified_agenda_parquet import (
        _act_name_resolver,
        _act_name_spelling_closure,
        _resolve_one_act_citation,
        _usc_source_credits,
        _yearless_stems,
        resolvable_act_names,
    )

    root = _Path(__file__).resolve().parents[1]
    index = ActIndex.from_artifact(root / "output/usc-act-index-2026-08-22")
    names = resolvable_act_names(root / "output/usc-act-index-2026-08-22")
    narrow = _act_name_spelling_closure(names)
    widened = _act_name_spelling_closure(names, _act_name_resolver(index))
    # Four names arrive; NOTHING already answered moves or is lost. That is the
    # claim a widening has to make good on, and it is cheap to check.
    assert set(widened) - set(narrow) == {
        "atomic energy act",
        "federal coal leasing amendments act",
        "food stamp act",
        "newborn screening saves lives act",
    }
    assert not set(narrow) - set(widened)
    assert {key: value for key, value in widened.items() if narrow.get(key, value) != value} == {}

    # The receipt counts the same population from the other end; the two
    # readings are held together here rather than one being trusted.
    stems = _yearless_stems(names)
    assert sum(1 for acts in stems.values() if len(acts) == 1) == 5_292
    assert sum(1 for stem, acts in stems.items() if len(acts) > 1 and stem not in widened) == 634
    assert sum(1 for stem, acts in stems.items() if len(acts) > 1 and stem in widened) == 4

    credits = _usc_source_credits()

    def read(text):
        return [
            (
                citation.act_key,
                citation.section,
                *_resolve_one_act_citation(citation.act_key, citation.section, index, credits)[:2],
            )
            for citation in find_act_relative_citations(text, act_names=widened)
        ]

    assert read("Atomic Energy Act sec 275") == [("atomic energy act of 1954", "275", 42, "2022")]
    assert read("Sec 12 of the Food Stamp Act") == [("food and nutrition act of 2008", "12", 7, "2021")]
    # OLRC's keyless cross-references already answered and are pinned here so
    # they stay answered: "ERISA" is listed only as a pointer at a name that is
    # not itself an entry, and the chain plus the supplied year reaches it.
    assert read("ERISA sec. 505") == [("erisa", "505", 29, "1135")]
    # And the refusal the widening does NOT touch: three acts are called the
    # Clean Air Act Amendments, so the stem still names no act.
    assert read("Clean Air Act Amendments sec 112") == []


@pytest.mark.slow
def test_the_enacting_years_widening_is_11952_variants_and_moves_nothing_held() -> None:
    """Measured against the pinned index and the pinned public-law roster.

    3,999 of the tool's listed names carry no year and are dated by a source --
    the session-law Table III key states its own year, the roster dates a
    public law -- and each takes the three spellings the tool alternates
    between, 11,952 keys. It is added AFTER the whole closure and never over
    it: nothing already spelled moves, nothing is lost.
    """

    from pathlib import Path as _Path

    from refspec.registry.act_resolution import ActIndex
    from refspec.registry.citation_grammar import normalize_popular_name
    from refspec.registry.unified_agenda_parquet import (
        _act_enactment_years,
        _act_name_resolver,
        _act_name_spelling_closure,
        _pl_roster,
        resolvable_act_names,
    )

    root = _Path(__file__).resolve().parents[1]
    index = ActIndex.from_artifact(root / "output/usc-act-index-2026-08-22")
    names = resolvable_act_names(root / "output/usc-act-index-2026-08-22")
    years = _act_enactment_years(index, _pl_roster())
    assert len(years) == 3_999
    narrow = _act_name_spelling_closure(names, _act_name_resolver(index))
    widened = _act_name_spelling_closure(names, _act_name_resolver(index), years)
    assert len(set(widened) - set(narrow)) == 11_952
    assert not set(narrow) - set(widened)
    assert {key: value for key, value in widened.items() if narrow.get(key, value) != value} == {}

    # The filer's exact text, as the corpus writes it, through the builder's
    # own reader -- and the four year-shapes beside them that stay refused.
    for stated, act in (
        ("Waste Isolation Pilot Plant Land Withdrawal Act of 1992",
         "waste isolation pilot plant land withdrawal act"),
        ("Refuge Recreation Act of 1962", "refuge recreation act"),
        ("Buy Indian Act 1910", "buy indian act"),
    ):
        assert widened[normalize_popular_name(stated)] == act
    for refused in (
        "Clean Air Act of 1990",
        "Soil Conservation and Domestic Allotment Act of 1936",
        "Social Security Act of 1886",
        "Fair Labor Standards Act of 1939",
        "Space Act of 1958",
    ):
        assert normalize_popular_name(refused) not in widened


def test_the_initialism_operator_matches_how_the_corpus_abbreviates() -> None:
    from refspec.registry.unified_agenda_parquet import _act_initialism

    assert _act_initialism("clean air act") == "CAA"
    assert _act_initialism("clean air act amendments of 1990") == "CAAA"
    assert _act_initialism("safe drinking water act") == "SDWA"
    assert _act_initialism("medicare improvements for patients and providers act of 2008") == "MIPPA"
    assert _act_initialism("federal insecticide, fungicide, and rodenticide act") == "FIFRA"


def test_separator_damaged_public_laws_recover_only_against_the_roster() -> None:
    """Named operators (a dash inserted into the fused run; the stated pair
    for the spaced form) x pinned roster x exactly-one-survivor. A bare
    "Pub. L. 179" names no congress and stays refused."""

    from refspec.registry.unified_agenda_parquet import _corroborated_public_law_from_failed

    roster = (
        {(108, 199): "01/23/2004", (95, 616): "11/08/1978", (10, 8199): "not-a-congress"},
        {},
    )
    assert _corroborated_public_law_from_failed("Pub. L. 108199", roster) == (
        "108-199",
        "unique-dash-insertion",
    )
    assert _corroborated_public_law_from_failed("PL 95 616", roster) == (
        "95-616",
        "space-separator-roster-existence",
    )
    assert _corroborated_public_law_from_failed("Pub. L. 179", roster) is None
    assert _corroborated_public_law_from_failed("PL 95 617", roster) is None, (
        "a pair the roster does not hold is never minted"
    )


def test_the_entry_point_verifies_the_artifact_against_its_receipt(tmp_path) -> None:
    """`python -m refspec.registry.unified_agenda_parquet --verify` is the
    checked rebuild entry point's cheap half: it re-hashes the four tables
    against the receipt and fails loudly on drift. Built because the first
    rebuild after the census had to happen through a scratchpad script."""
    from refspec.registry.unified_agenda_parquet import main, verify_unified_agenda_parquet

    assert main(["--verify", "--output-root", str(ARTIFACT)]) == 0

    # Drift refuses: a receipt pinning a wrong digest names the file.
    import json
    import shutil

    fake = tmp_path / "artifact"
    fake.mkdir()
    recorded = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))
    table = min(recorded["outputs"])
    shutil.copy(ARTIFACT / f"{table}.parquet", fake / f"{table}.parquet")
    recorded["outputs"] = {table: "sha256:" + "0" * 64}
    (fake / "receipt.json").write_text(json.dumps(recorded), encoding="utf-8")
    problems = verify_unified_agenda_parquet(fake)
    assert len(problems) == 1 and "drifted" in problems[0]


@pytest.mark.slow
def test_resolvable_act_names_read_through_the_pin() -> None:
    """The builder's act vocabulary comes from the sealed act index via the
    sha256-pinned loader — 13,560 names the resolver can actually answer, the
    same set the census rebuild proved reproduces the artifact exactly."""
    from refspec.registry.unified_agenda_parquet import _DEFAULT_ACT_INDEX, resolvable_act_names

    assert len(resolvable_act_names(_DEFAULT_ACT_INDEX)) == 13_560


def test_receipt_payload_matches_the_receipt_on_disk() -> None:
    """One spelling for receipt.json, so a rebuild is byte-comparable: the
    payload function's key set is exactly what the artifact's receipt holds."""
    import json

    from refspec.registry.unified_agenda_parquet import UnifiedAgendaParquetReceipt, receipt_payload

    empty = UnifiedAgendaParquetReceipt(
        editions=0,
        actions=0,
        cfr_references=0,
        legal_authorities=0,
        timetable_rows=0,
        source_sha256_by_edition={},
        outputs={},
        schema_digests={},
        contract={},
        producer={},
    )
    recorded = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))
    assert set(receipt_payload(empty)) == set(recorded)


def test_the_receipt_names_the_code_that_wrote_it() -> None:
    """A receipt digest that names no code cannot be matched to a build:
    twenty commits landed between two builds on 2026-08-22 and a consumer's
    receipt resolved to none of them. The producer block's DIGESTS are content
    hashes of the modules and oracles a build reads — deterministic and
    clockless, computed from bytes on disk and nothing else — so a receipt
    resolves to code by hashing blobs, and that is the part this test pins.
    The block also carries live git state (`commit`, `workingTreeClean`),
    which is exactly NOT deterministic: it is a convenience beside the
    digests, sampled per build, and it is why the equality against the
    on-disk receipt at the end of this test is expected to be red between a
    rebuild and the next."""
    import hashlib
    import json
    from pathlib import Path

    from refspec.registry import unified_agenda_parquet as module

    block = module._producer_block()
    assert set(block["modules"]) == {
        "unified_agenda_parquet",
        "unified_agenda_editions",
        "citation_grammar",
        "identifier_shapes",
        "act_resolution",
        # The section oracle is named as a MODULE and that is also how its six
        # tables are pinned: their digests are literal strings inside it and
        # its loader refuses on drift, so hashing the module hashes the pins.
        "usc_section_oracle",
        # And the CFR authority-note reader, for the same reason: its cache's
        # sha256, byte length and record count are literals inside it.
        "cfr_authority_notes",
        # And the recodification tables the section oracle consults. Same
        # argument a third time, one step longer: RECODIFICATIONS carries the
        # derived table's sha256 AND the printed volume's sha256 and byte
        # length, so hashing this module pins the table and the page it was
        # cut from.
        "usc_disposition_tables",
        # The EO roster module pins its derived roster and refuses on drift;
        # hashing it makes that new build input visible in the receipt.
        "eo_roster",
    }
    package = Path(module.__file__).resolve().parent
    for name, digest in block["modules"].items():
        assert digest == "sha256:" + hashlib.sha256((package / f"{name}.py").read_bytes()).hexdigest()
    assert set(block["oracles"]) == {
        "public-law-roster.csv",
        "part-subjects.csv",
        # The 8,240 eCFR part authority notes -- every one the register
        # publishes, since the 2026-08-24 oracle switch. Listed under oracles
        # as well as under its reader module because this one IS the
        # publisher's bytes, and named by its own path because the file it
        # names moved (the 287-part set-cover was `ecfr-authority-notes.jsonl`
        # under silent-misreads-2026-08-22).
        "ecfr-authority-notes-2026-08-24/notes.jsonl",
        # The pinned Federal Register document roster, added at rebuild #8
        # (cae91506): the eight damaged-citation corroboration reads it, no
        # network at build time, so it is an oracle like the three above.
        "unified-agenda-fr-document-roster/documents.csv",
        # The pinned initialism roster, added at rebuild #11 (#44/45,
        # 2c83ff33): the 92-act, 329-row roster the pinned-roster-initialism
        # tiers and the sibling-act carry read, no network at build time, so
        # it is an oracle like the three above.
        "initialism-roster-2026-08-24/roster.csv",
        # The EO existence roster now refines the cheap range gate. Naming its
        # exact derived bytes distinguishes a range-only artifact from one
        # that can report honest unknowns.
        "eo-roster-2026-08-31/derived/roster.csv",
    }
    assert all(block["oracles"].values()), "every oracle is present in this checkout"
    # The commit and clean flag are siblings of "modules" and "oracles", not
    # members of either -- `describe_producer_drift` only walks those two
    # groups on purpose (a commit changing while every digest holds is not
    # the drift that function answers for; the digests already say "which
    # code ran"). This checkout is a real git worktree with this module's own
    # file under it, so both resolve rather than going None.
    assert set(block) == {"modules", "oracles", "commit", "workingTreeClean"}
    assert block["commit"] == subprocess.run(
        ["git", "-C", str(Path(module.__file__).parent), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert isinstance(block["workingTreeClean"], bool)
    # And the built artifact carries the block for the code that wrote it,
    # which is this code: drift here means rebuild and re-pin. It is therefore
    # RED between a change to any of these modules and the next rebuild, and
    # `describe_producer_drift` names which digests moved. It is ALSO red
    # right now, on this branch, for a second reason: the recorded receipt
    # predates the commit/workingTreeClean keys entirely, and a commit sha
    # frozen at build time can never equal HEAD read fresh on every later
    # checkout anyway -- this equality only turns green again at the next
    # rebuild, and only for as long as nothing is re-committed after it.
    recorded = json.loads((module._DEFAULT_OUTPUT_ROOT / "receipt.json").read_text(encoding="utf-8"))
    assert recorded.get("producer") == block, module.describe_producer_drift(module._DEFAULT_OUTPUT_ROOT)


def _git_or_skip() -> None:
    """The three tests below are about WHICH repository git answers for, so a
    machine with no git binary has no question to ask. Distinct from
    `test_the_commit_and_the_clean_flag_answer_none_together`, which stubs
    subprocess and therefore runs with or without one."""

    if shutil.which("git") is None:
        pytest.skip("no git on PATH")


def _a_repository(root: Path, *, tracked: Path | None = None) -> str:
    """A real git repository at ``root`` with one commit, and the HEAD sha it
    is at. ``tracked``, when given, is the one file added to its index.

    Its identity and signing are given on the command line rather than read
    from the machine, so a runner with no global git config still answers.
    """

    root.mkdir(parents=True, exist_ok=True)

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.email=lane@example.invalid", "-c", "user.name=lane", "-c", "commit.gpgsign=false", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    git("init", "-q", "-b", "main")
    if tracked is not None:
        git("add", "--", str(tracked))
    git("commit", "-q", "--allow-empty", "-m", "one commit")
    return git("rev-parse", "HEAD").strip()


@pytest.mark.no_artifact
def test_producer_block_refuses_when_a_producer_module_is_missing(monkeypatch) -> None:
    """The fail-open this replaces: a producer module absent used to yield
    None silently, and the build proceeded, writing a receipt with NULL
    provenance for the grammar that produced the values -- indistinguishable
    from "there was nothing to record". Append a name no ``.py`` file answers
    to and require ``_producer_block`` to name it and refuse, not swallow it.

    What this cannot see: a module file that EXISTS but is the wrong bytes
    (truncated, corrupted) -- only absence is refused here; wrong-but-present
    bytes still hash and still land in the receipt, for `describe_producer_drift`
    to catch downstream against a prior receipt.
    """
    from refspec.registry import unified_agenda_parquet as module

    monkeypatch.setattr(module, "_PRODUCER_MODULES", (*module._PRODUCER_MODULES, "no_such_producer_module"))
    with pytest.raises(ValueError, match="no_such_producer_module"):
        module._producer_block()


@pytest.mark.no_artifact
def test_a_missing_producer_module_refuses_before_one_table_is_written(tmp_path, monkeypatch) -> None:
    """The refusal above used to fire from ``_producer_block()`` at RECEIPT
    time, after all four Parquet files were already written. A build in a
    checkout missing a producer module therefore overwrote the tables and
    only then aborted, leaving new tables beside the PREVIOUS run's receipt:
    bytes on disk that no receipt describes, which is worse than the null
    provenance the refusal replaced, because null is at least visibly absent.

    The source root named below deliberately does not exist. That is the
    assertion, not an oversight: a refusal that reached the edition reader
    would raise about the missing source instead of the missing module, so
    an error naming ``no_such_producer_module`` is proof the check ran before
    the build read or wrote anything at all.

    What this cannot see: it proves ORDER, not that a completed build's
    tables and receipt are written atomically. A crash between the last
    Parquet write and the receipt still leaves the same inconsistency, from a
    cause this check is not looking for.
    """
    from refspec.registry import unified_agenda_parquet as module

    previous = tmp_path / "out"
    previous.mkdir()
    before = {}
    for name in ("unified_agenda_actions", "unified_agenda_cfr_references", "unified_agenda_legal_authorities", "unified_agenda_timetables"):
        path = previous / f"{name}.parquet"
        path.write_bytes(f"the previous build's {name} bytes".encode())
        before[path] = path.read_bytes()
    receipt = previous / "receipt.json"
    receipt.write_text('{"producer": "the previous build"}', encoding="utf-8")
    before[receipt] = receipt.read_bytes()

    monkeypatch.setattr(module, "_PRODUCER_MODULES", (*module._PRODUCER_MODULES, "no_such_producer_module"))
    with pytest.raises(ValueError, match="no_such_producer_module"):
        module.build_unified_agenda_parquet(tmp_path / "no-such-source", previous)
    for path, payload in before.items():
        assert path.read_bytes() == payload, f"{path.name} was rewritten by a build that refused"

    # And into a directory that does not exist yet, the refusal beats even the
    # `mkdir` on the build's first line.
    fresh = tmp_path / "fresh"
    with pytest.raises(ValueError, match="no_such_producer_module"):
        module.build_unified_agenda_parquet(tmp_path / "no-such-source", fresh)
    assert not fresh.exists(), "a refused build creates nothing"


@pytest.mark.no_artifact
def test_commit_is_none_when_the_toplevel_is_a_stranger_repository(monkeypatch, tmp_path) -> None:
    """The hazard ``_repository_commit_and_cleanliness``'s docstring names: a
    non-editable install's site-packages can sit inside some UNRELATED
    checkout, and ``git -C <site-packages dir> rev-parse HEAD`` would answer
    with that checkout's HEAD -- a stranger's commit recorded as this
    artifact's provenance, worse than recording none. Simulate exactly that:
    git SUCCEEDS and returns a real, existing directory as the toplevel that
    is not this module's own repository, and require both keys go None
    rather than trusting git's yes.

    What this cannot see: a stranger toplevel that happens to be
    `Path.samefile` with `_REPO_ROOT` (impossible for two distinct real
    directories, but worth naming: this is a device+inode check, not a
    content check).
    """
    from refspec.registry import unified_agenda_parquet as module

    real_run = subprocess.run

    def stranger_toplevel(cmd, **kwargs):
        if "--show-toplevel" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{tmp_path}\ndeadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n", stderr="")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", stranger_toplevel)
    commit, clean = module._repository_commit_and_cleanliness(Path(module.__file__))
    assert (commit, clean) == (None, None)


@pytest.mark.no_artifact
def test_gits_own_environment_cannot_redirect_which_repository_answers(monkeypatch, tmp_path) -> None:
    """The BLOCKER the 2026-09-02 audit demonstrated, kept demonstrated.
    ``GIT_DIR`` takes precedence over ``git -C``, so a leaked pair
    (``GIT_DIR=<stranger>/.git`` with ``GIT_WORK_TREE=<this repo>``) makes
    ``--show-toplevel`` print THIS repository while ``HEAD`` prints the
    stranger's -- the toplevel guard validates one repository while the
    commit comes from another. Measured before the fix, the helper returned
    SpicySearch's ``2b1624ab`` while this checkout was at ``eb7e6458``.

    A build launched from a git hook, a ``git rebase --exec`` or a CI runner
    that exports these inherits exactly that environment, so the fix is to
    scrub every ``GIT_*`` (bar ``GIT_EXEC_PATH``) rather than to refuse. The
    assertion is therefore that the poisoned environment changes NOTHING:
    the honest commit still comes back. ``GIT_INDEX_FILE`` is the second leg
    because it redirects a DIFFERENT part of the answer -- unscrubbed it makes
    ``ls-files`` exit 128 while ``rev-parse`` still succeeds (measured), the
    partial redirect that turns into a wrong or missing answer.

    What this cannot see: a redirection that does not travel through the
    environment (a ``.git`` replaced on disk, a ``git`` binary replaced on
    PATH), and a stranger that is a FORK of this repository, which tracks the
    same paths and would satisfy every check here. Scrubbing is what closes
    the environment class; nothing here closes the others.
    """
    from refspec.registry import unified_agenda_parquet as module

    _git_or_skip()
    # Asked directly rather than through the code under test, so this decides
    # whether the question APPLIES here without letting the answer to it
    # decide. A source export with no `.git` skips; a real worktree must
    # produce an honest commit, and a regression that nulled every commit
    # fails this rather than skipping past it.
    probe = subprocess.run(
        ["git", "-C", str(Path(module.__file__).parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0 or Path(probe.stdout.strip()).resolve() != Path(module._REPO_ROOT).resolve():
        pytest.skip("this package does not live in a git worktree of its own: no honest commit to protect")

    honest_commit, honest_clean = module._repository_commit_and_cleanliness(Path(module.__file__))
    assert honest_commit is not None and isinstance(honest_clean, bool), "a real worktree answers"

    stranger = tmp_path / "stranger"
    stranger_head = _a_repository(stranger)
    assert stranger_head != honest_commit

    monkeypatch.setenv("GIT_DIR", str(stranger / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(module._REPO_ROOT))
    hijacked = subprocess.run(
        ["git", "-C", str(Path(module.__file__).parent), "rev-parse", "--show-toplevel", "HEAD"],
        capture_output=True,
        text=True,
    )
    assert hijacked.stdout.splitlines() == [str(module._REPO_ROOT), stranger_head], (
        "the bypass itself must still work, or this test is proving nothing"
    )
    commit, clean = module._repository_commit_and_cleanliness(Path(module.__file__))
    assert commit == honest_commit and commit != stranger_head
    assert isinstance(clean, bool)

    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "not-an-index"))
    (tmp_path / "not-an-index").write_bytes(b"")
    commit, clean = module._repository_commit_and_cleanliness(Path(module.__file__))
    assert commit == honest_commit and isinstance(clean, bool)


@pytest.mark.no_artifact
def test_commit_is_none_when_the_repository_does_not_track_this_module(monkeypatch, tmp_path) -> None:
    """The second half of the same BLOCKER, and the reason a toplevel check
    alone is not enough. ``_REPO_ROOT`` is derived structurally
    (``parents[3]`` of this module's own file), so an install laid out as
    ``<foreign>/site-packages/refspec/registry/...`` -- what ``pip install
    --target`` produces -- puts ``_REPO_ROOT`` at ``<foreign>``. If
    ``<foreign>`` is somebody's checkout, its toplevel IS ``_REPO_ROOT`` and
    the samefile guard says yes to a stranger's commit.

    Built here for real rather than stubbed: a foreign repository whose index
    has never heard of the installed copy. The commit is refused because the
    repository that answered HEAD does not track the file whose provenance is
    being recorded. Then the same file is committed, and the same helper
    records the commit -- the positive control that proves this refuses the
    hazard rather than refusing everything.
    """
    from refspec.registry import unified_agenda_parquet as module

    _git_or_skip()
    foreign = tmp_path / "foreign"
    installed = foreign / "site-packages" / "refspec" / "registry" / "unified_agenda_parquet.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("# an installed copy, not a checkout\n", encoding="utf-8")
    _a_repository(foreign)
    assert installed.resolve().parents[3] == foreign.resolve(), "the layout that aligns _REPO_ROOT"
    monkeypatch.setattr(module, "_REPO_ROOT", foreign)

    assert module._repository_commit_and_cleanliness(installed) == (None, None)

    tracked = _a_repository(foreign, tracked=installed)
    assert module._repository_commit_and_cleanliness(installed) == (tracked, True)


@pytest.mark.no_artifact
def test_a_linked_worktree_still_answers_with_its_own_commit(monkeypatch, tmp_path) -> None:
    """The guard that must NOT tighten into a path-containment rule. A linked
    worktree's git directory lives inside the MAIN checkout
    (``<main>/.git/worktrees/<name>``, asserted below), outside the worktree
    root entirely, so a rule requiring ``rev-parse --absolute-git-dir`` to sit
    under ``_REPO_ROOT`` would refuse the worktree builds this repository
    actually uses. Asking instead whether that repository TRACKS this file
    admits the worktree and still refuses the hijack in the two tests above.

    What this cannot see: a worktree whose main checkout has since been
    deleted -- git answers about a repository that is half gone, and this
    records whatever it says.
    """
    from refspec.registry import unified_agenda_parquet as module

    _git_or_skip()
    main = tmp_path / "main"
    installed = main / "src" / "refspec" / "registry" / "unified_agenda_parquet.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("# tracked in the main checkout\n", encoding="utf-8")
    head = _a_repository(main, tracked=installed)

    linked = tmp_path / "linked"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "--detach", str(linked)], check=True, capture_output=True)
    in_worktree = linked / "src" / "refspec" / "registry" / "unified_agenda_parquet.py"
    git_dir = subprocess.run(
        ["git", "-C", str(in_worktree.parent), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert Path(git_dir) == main / ".git" / "worktrees" / "linked", git_dir
    assert not Path(git_dir).is_relative_to(linked), "which is why containment is the wrong rule"

    monkeypatch.setattr(module, "_REPO_ROOT", linked)
    assert module._repository_commit_and_cleanliness(in_worktree) == (head, True)


@pytest.mark.no_artifact
def test_the_commit_and_the_clean_flag_answer_none_together(monkeypatch) -> None:
    """Three ways git fails to answer, and one rule for all of them: the pair
    is atomic. ``OSError`` is no ``git`` on PATH at all (a minimal container
    image); ``TimeoutExpired`` is a hung git, which used to ESCAPE this
    helper entirely and abort the build, since only ``OSError`` was caught;
    a non-zero ``status`` used to yield ``(commit, None)``, a half-answer
    that contradicted REF-067's own account of the contract. All three now
    answer ``(None, None)``, so a consumer reads one condition rather than
    two. See REF-067.

    What this cannot see: a git that exits 0 and lies. Every check here is
    downstream of trusting git's own exit status.
    """
    from refspec.registry import unified_agenda_parquet as module

    real_run = subprocess.run

    def absent_git(cmd, **kwargs):
        raise OSError("git: command not found")

    monkeypatch.setattr(subprocess, "run", absent_git)
    assert module._repository_commit_and_cleanliness(Path(module.__file__)) == (None, None)

    def hung_git(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(subprocess, "run", hung_git)
    assert module._repository_commit_and_cleanliness(Path(module.__file__)) == (None, None)

    def status_fails(cmd, **kwargs):
        if "status" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="fatal: unable to read index")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", status_fails)
    assert module._repository_commit_and_cleanliness(Path(module.__file__)) == (None, None)


@pytest.mark.no_artifact
def test_a_commit_that_moves_while_the_bytes_are_hashed_is_not_recorded(monkeypatch) -> None:
    """Git and the digests are two reads of a worktree that can move between
    them: a checkout landing mid-block would file commit A's sha beside
    commit B's digests, one receipt describing two states. The block asks git
    the same question on both sides of the hashing and records the pair only
    when the two answers agree.

    What this cannot see: a worktree that moves to B and back to A around the
    hashing, and the fact that the digests themselves are read one file at a
    time, so they are not one atomic snapshot either. This narrows the
    window; it does not abolish it.
    """
    from refspec.registry import unified_agenda_parquet as module

    moved = iter([("a" * 40, True), ("b" * 40, True)])
    monkeypatch.setattr(module, "_repository_commit_and_cleanliness", lambda path: next(moved))
    block = module._producer_block()
    assert (block["commit"], block["workingTreeClean"]) == (None, None)
    assert block["modules"] and all(block["modules"].values()), "the digests are recorded either way"

    steady = iter([("c" * 40, False), ("c" * 40, False)])
    monkeypatch.setattr(module, "_repository_commit_and_cleanliness", lambda path: next(steady))
    block = module._producer_block()
    assert (block["commit"], block["workingTreeClean"]) == ("c" * 40, False)


def test_the_abbreviation_shapes_read_the_measured_spellings() -> None:
    """Five whole-value shapes, each measured on the failed pool 2026-08-22.
    A section list yields every member; a citation label ("PL", "USC") is
    never an act abbreviation, whatever any oracle holds."""

    from refspec.registry.unified_agenda_parquet import (
        _ABBREV_LABEL_TOKENS,
        _abbrev_act_reading,
    )

    assert _abbrev_act_reading("CWA 301") == ("CWA", None, ("301",), False)
    assert _abbrev_act_reading("CAA sec 112(f)(2)") == ("CAA", None, ("112(f)(2)",), True)
    assert _abbrev_act_reading("CWA 301, 304, 306") == ("CWA", None, ("301", "304", "306"), False)
    assert _abbrev_act_reading("212(a)(10) INA") == ("INA", None, ("212(a)(10)",), False)
    assert _abbrev_act_reading("Sec. 1102 of the SSA") == ("SSA", None, ("1102",), True)
    assert _abbrev_act_reading("sec 4312(a) of BBA of 1997") == ("BBA", "1997", ("4312(a)",), True)
    assert _abbrev_act_reading("DRA of 2005") == ("DRA", "2005", (), False)
    assert _abbrev_act_reading("CAA title I") == ("CAA", None, (), False)
    assert _abbrev_act_reading('"CWA 311(d)(2)"') == ("CWA", None, ("311(d)(2)",), False)
    assert _abbrev_act_reading("the Clean Water Act") is None, "prose is not a shape"
    assert "PL" in _ABBREV_LABEL_TOKENS and "USC" in _ABBREV_LABEL_TOKENS


def test_the_year_guard_is_identity_not_a_section() -> None:
    """"MCSA 1984" names the Motor Carrier Safety Act OF 1984 — the year is
    the act's identity, not section 1984 — and "CAA 1990" against the
    year-less Clean Air Act refuses outright rather than minting either."""

    from refspec.registry.unified_agenda_parquet import _corroborated_act_sections

    assert _corroborated_act_sections("motor carrier safety act of 1984", None, ("1984",)) == ()
    assert _corroborated_act_sections("clean air act", None, ("1990",)) is None
    assert _corroborated_act_sections("balanced budget act of 1997", "1997", ("4523",)) == ("4523",)
    assert _corroborated_act_sections("balanced budget act of 1997", "1996", ("4523",)) is None
    assert _corroborated_act_sections("clean water act", None, ("301", "304(h)")) == ("301", "304")


def test_an_explicit_section_marker_defeats_the_year_shaped_guard() -> None:
    """"SSA, sec 1834" is Social Security Act section 1834 (Medicare Part B
    durable medical equipment), not the year 1834 — the publisher's own "sec"
    says which slot the token fills.

    Measured 2026-08-22 on the failed pool: 59 rows carry a year-shaped token
    in the section slot. All 8 marked ones are real sections; all 51 unmarked
    ones but two are the act's year ("NEPA 1969", "ARRA 2009", "MMA 2003").
    The two exceptions ("SSA 1819", "SSA 1919") are real sections wearing the
    ambiguous shape and stay refused: the text does not say, and refusing to
    choose is the rule."""

    from refspec.registry.unified_agenda_parquet import (
        _abbrev_act_reading,
        _corroborated_act_sections,
    )

    marked = _abbrev_act_reading("SSA, sec 1834")
    assert marked == ("SSA", None, ("1834",), True)
    assert _corroborated_act_sections("social security act", None, ("1834",), marked=True) == (
        "1834",
    )
    unmarked = _abbrev_act_reading("SSA 1919")
    assert unmarked == ("SSA", None, ("1919",), False)
    assert (
        _corroborated_act_sections("social security act", None, ("1919",), marked=False) is None
    ), "an unmarked year-shaped token stays refused even when it is a real section"


def test_the_year_filters_abbreviation_candidates_before_they_are_counted() -> None:
    """CMS's roster holds three Medicare acts whose initialisms "MMA" can
    reach. Filtering the roster by the stated year BEFORE counting survivors
    is what turns that ambiguity into an answer; filtering after would
    refuse."""

    from refspec.registry.unified_agenda_parquet import _abbrev_survivors

    roster = [
        "medicare prescription drug, improvement, and modernization act of 2003",
        "medicare, medicaid, and schip balanced budget refinement act of 1999",
        "medicare, medicaid, and schip benefits improvement and protection act of 2000",
    ]
    assert len(_abbrev_survivors("MMA", None, roster)) == 3, "no year, no answer"
    assert _abbrev_survivors("MMA", "2003", roster) == [roster[0]]
    # An exact initialism always beats a subsequence: a roster holding both
    # never reaches past the act that spells the abbreviation outright.
    assert _abbrev_survivors("CAA", None, ["clean air act", "clean air act amendments"]) == [
        "clean air act"
    ]


def test_the_corpus_glosses_its_own_abbreviations() -> None:
    """The census's largest single refusal, answered by the publisher.

    The OLRC publishes no "Medicare Modernization Act" alias, so wave 3
    refused "MMA" for want of a pinned oracle. The corpus writes "Medicare
    Modernization Act (MMA)" in its own authority column; the gloss cannot
    NAME the act (it is not an index name) but its words pick exactly one of
    the three Medicare acts CMS's roster holds."""

    from refspec.registry.unified_agenda_parquet import _gloss_narrowed, _harvest_act_glosses

    harvested = _harvest_act_glosses(
        [
            {
                "rin": "0938-AN31",
                "authority_text": (
                    "sec 1893(i)(1) of the Social Security Act as amended by "
                    "sec 935(i)(1) of Medicare Modernization Act (MMA)"
                ),
            }
        ]
    )
    assert harvested["0938"]["MMA"] == {"medicare modernization act"}
    survivors = [
        "medicare prescription drug, improvement, and modernization act of 2003",
        "medicare, medicaid, and schip balanced budget refinement act of 1999",
        "medicare, medicaid, and schip benefits improvement and protection act of 2000",
    ]
    assert _gloss_narrowed(harvested["0938"]["MMA"], survivors) == [survivors[0]]
    assert _gloss_narrowed(None, survivors) is None, "no gloss, no narrowing"
    # A gloss whose words reach nothing empties rather than contradicting.
    assert _gloss_narrowed({"widget safety act"}, survivors) == []


def test_the_word_prefix_operator_is_licensed_by_its_fence_not_its_yield() -> None:
    """"Railroad Safety Improvement Act of 2008" is the corpus's spelling of
    Pub. L. 110-432 Division A, whose short title is the "Rail Safety
    Improvement Act of 2008" (web-verified 2026-08-22 against congress.gov
    and FRA's own eLibrary).

    Wave 3 measured this operator against the whole 13,560-name index, found
    one distinct value, and refused it on yield. Wave 4 fences it with the
    citing agency's own resolved-act roster and measures the surface that
    worried wave 3: held out over the 1,964 distinct (text, RIN) act
    citations the grammar resolved, with the true act removed from the
    roster, the operator invented a survivor 0 times."""

    from refspec.registry.unified_agenda_parquet import _one_word_prefix_survivors

    roster = {"rail safety improvement act of 2008", "clean air act"}
    assert _one_word_prefix_survivors("railroad safety improvement act of 2008", roster) == {
        "rail safety improvement act of 2008"
    }
    # One word may differ, and it must be a prefix relationship, not any edit.
    assert _one_word_prefix_survivors("marine safety improvement act of 2008", roster) == set()
    assert _one_word_prefix_survivors("railroad safety improvement act of 2009", roster) == set()
    # A roster that does not hold the act says nothing, whatever the index has.
    assert _one_word_prefix_survivors("railroad safety improvement act of 2008", set()) == set()


def test_the_citation_history_oracle_reads_labels_and_containers_back() -> None:
    """A rule's own resolved citations answer the shapes that lost a label or
    a container. Ambiguity refuses, a level that speaks ambiguously is never
    escalated past, and a section number several titles claim never names one
    from its digits alone."""

    from refspec.registry.unified_agenda_parquet import (
        _CitationHistory,
        _history_distinctive,
        _history_read_labelless_pair,
        _history_read_section_list,
        _history_read_titleless_usc,
        _history_read_volumeless_stat,
        _history_section_tokens,
    )

    def usc_row(rin, title, section, **extra):
        row = {
            "rin": rin, "authority_type": "usc", "parse_status": "ok",
            "usc_title": title, "usc_section": section, "usc_appendix": False,
            "usc_title_is_possible": True, "act_key": None, "act_section": None,
            "statute_volume": None, "statute_page": None, "public_law": None,
            "pl_congress_in_series": None, "authority_text": f"{title} USC {section}",
        }
        row.update(extra)
        return row

    history = _CitationHistory.build(
        [
            usc_row("2126-AB20", 49, "31136"),
            usc_row("2126-AC50", 49, "31144"),
            usc_row("9999-AA01", 42, "6921"),
        ]
    )
    failed = {"rin": "2126-AB20", "authority_type": "other", "parse_status": "failed",
              "authority_text": "31136(a)"}
    rule, emissions = _history_read_section_list(failed, history)
    assert rule == "rin-history-section-list"
    # The emission names a PLACE and carries no series verdict: a verdict
    # carries a calendar, and an emission cannot see the edition it lands in.
    # ``_apply_corroboration`` is what dates it.
    assert emissions == [
        {"authority_type": "usc", "usc_title": 49, "usc_section": "31136", "usc_note": False}
    ]
    # The agency answers where the single RIN is silent: 2126-AC50 never cites
    # 31136, but its agency does.
    sibling = dict(failed, rin="2126-AC50")
    assert _history_read_section_list(sibling, history)[1][0]["usc_title"] == 49
    # A rule whose agency never cited it stays refused.
    assert _history_read_section_list(dict(failed, rin="1111-ZZ99"), history) is None

    # A section several titles claim names none of them.
    both = _CitationHistory.build([usc_row("2126-AB20", 49, "31136"), usc_row("3333-AA01", 7, "31136")])
    assert _history_read_section_list(failed, both) is None

    # Short bare ordinals are the numbers every title reuses.
    assert _history_distinctive("31136") and _history_distinctive("1437z-5")
    assert _history_distinctive("6662a") and not _history_distinctive("509")

    # A list is one body of law: every member resolves or the row refuses.
    assert _history_section_tokens("41708 and 41709") == ["41708", "41709"]
    assert _history_section_tokens("8 1252 note") is None, "a pair is not a list"

    # The label kept, the title lost.
    titleless = {"rin": "2126-AB20", "authority_type": "other", "parse_status": "failed",
                 "authority_text": "U.S.C. 31136"}
    assert _history_read_titleless_usc(titleless, history)[1][0]["usc_title"] == 49

    # The container stated, the label lost — and a pair BOTH schemes hold
    # refuses, which is the wave-2 objection to this shape answered rather
    # than overruled.
    stat_history = _CitationHistory.build(
        [
            usc_row("1615-AA83", 8, "1252"),
            {"rin": "2501-AD71", "authority_type": "statute_at_large", "parse_status": "ok",
             "usc_title": None, "usc_section": None, "usc_appendix": False,
             "usc_title_is_possible": None, "act_key": None, "act_section": None,
             "statute_volume": 119, "statute_page": 2936, "public_law": None,
             "pl_congress_in_series": None, "authority_text": "119 Stat. 2936"},
        ]
    )
    pair = {"rin": "1615-AA83", "authority_type": "other", "parse_status": "failed",
            "authority_text": "8 1252 note"}
    emitted = _history_read_labelless_pair(pair, stat_history)[1][0]
    assert emitted["usc_title"] == 8 and emitted["usc_note"] is True

    # The Statutes label kept, the volume lost.
    volumeless = {"rin": "2501-AD71", "authority_type": "other", "parse_status": "failed",
                  "authority_text": "Stat 2936"}
    assert _history_read_volumeless_stat(volumeless, stat_history)[1][0]["statute_volume"] == 119
    assert _history_read_volumeless_stat(dict(volumeless, rin="1111-ZZ99"), stat_history) is None


def _failed_row(text, **extra):
    """A row as the corroboration sweep meets it: typed "other", read nothing.

    Every column the rules touch is present, because the builder emits every
    schema column on every row and a rule that only works on a partial dict is
    not being tested against what it actually receives.
    """

    from refspec.registry.citation_grammar import stated_act_name, stated_section
    from refspec.registry.unified_agenda_parquet import LEGAL_AUTHORITIES_SCHEMA

    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update(
        rin="0938-AA01",
        publication_id="202510",
        authority_text=text,
        authority_type="other",
        parse_status="failed",
        usc_appendix=False,
        usc_note=False,
        stated_act_name=stated_act_name(text),
        stated_section=stated_section(text),
    )
    row.update(extra)
    return row


def test_the_index_holds_rule_reads_the_packaging_off_a_name_it_already_knew() -> None:
    """The rule with the largest yield of any act rule and, until now, no test
    of its own — only an artifact count, which cannot say WHY a number moved.

    The index answers "Clean Air Act" and always did; what failed was the
    packaging. Its two fences are that an amendment is its own index entry and
    not the base act, and that a year the name itself does not carry designates
    some other member of the family.

    The third check here is the one the corpus asked for. ``stated_section``
    finds the literal "sec" inside ordinary words — "**Sec**urity" yields
    "urity", "**Sec**ure" yields "ure", "**sec**tions" yields "s" — and this
    rule used to promote that fragment straight into ``act_section``, so 22
    rows of the artifact stated Social Security Act section "urity"."""

    from refspec.registry.unified_agenda_parquet import (
        _ActOracles,
        _read_index_held_name,
        _Tally,
    )

    lookup = {
        "social security act": "social security act",
        "clean air act": "clean air act",
        "trafficking victims protection act of 2000": "trafficking victims protection act of 2000",
        "secure equipment act of 2021": "secure equipment act of 2021",
    }
    oracles = _ActOracles(lookup=lookup, keys_by_rin={}, keys_by_agency={}, glosses={})

    def read(text, **extra):
        return _read_index_held_name(_failed_row(text, **extra), oracles, _Tally())

    rule, emissions = read(
        "sec 106, paragraph (g) of the Trafficking Victims Protection Act of 2000, as amended"
    )
    assert rule == "index-holds-the-stated-name"
    assert emissions[0]["act_key"] == "trafficking victims protection act of 2000"
    assert emissions[0]["act_section"] == "106"

    # A name with no section beside it resolves the act and states no section.
    assert read("of the Social Security Act")[1][0] == {
        "authority_type": "act_relative",
        "act_key": "social security act",
        "act_section": None,
        "stated_act_name": None,
        "stated_section": None,
    }, "the 'Sec' inside 'Security' is not a section number"
    assert read("and the Secure Equipment Act of 2021")[1][0]["act_section"] is None
    assert (
        read("Other sections of FDA Food Safety Modernization Act, as appropriate") is None
    ), "a name the index does not answer recovers nothing"

    # The two fences that were already here, kept: an amendment is its own
    # entry, and a foreign year names another member of the family.
    assert read("Section 172(a) of the 1990 Clean Air Act amendments") is None
    assert read("Clean Air Act, 1990 Amendments, sec 112") is None, "1990 is not in 'clean air act'"
    # Narrowed 2026-08-24 to the vintage clause and nothing softer: "as amended
    # IN YEAR" dates the act just named, and the review priced the conflation
    # at 42 U.S.C. 7412 -- see
    # ``test_a_year_the_text_gives_as_the_acts_own_vintage_is_not_another_acts``
    # for the specimen and for the second-act shapes that still refuse.
    assert read("Clean Air Act as amended in 1990")[1][0]["act_key"] == "clean air act"
    # And the calendar: an act cannot be cited by an edition that predates it.
    assert read("of the Social Security Act", publication_id=None) is not None
    tally = _Tally()
    assert (
        _read_index_held_name(
            _failed_row("of the Secure Equipment Act of 2021", publication_id="201810"),
            oracles,
            tally,
        )
        is None
    )
    assert tally.anachronisms == 1, "a refusal is counted, not silent"


def test_the_public_law_pair_rule_needs_all_three_of_its_fences() -> None:
    """"89-670 and 91-605" states both halves of a Public Law and no label, so
    the competing reading is a section range — which is why this rule, alone
    among the twelve, carries three fences. It had no test of its own.

    The pair must exist in the pinned congress.gov roster, be cited by this
    rule or its agency elsewhere, and meet no competing section reading in the
    same pool. Any one of them missing refuses."""

    from refspec.registry.unified_agenda_parquet import (
        _CitationHistory,
        _history_read_public_law_pairs,
    )

    def pl_row(rin, congress, law, **extra):
        row = _failed_row(f"Pub. L. {congress}-{law}", rin=rin)
        row.update(
            authority_type="public_law",
            parse_status="ok",
            public_law=f"{congress}-{law}",
            pl_congress_in_series=True,
            **extra,
        )
        return row

    history = _CitationHistory.build([pl_row("2130-AA10", 89, 670), pl_row("2130-AB99", 91, 605)])
    roster = {(89, 670), (91, 605), (113, 128)}
    row = _failed_row("89-670 and 91-605", rin="2130-AA10")

    rule, emissions = _history_read_public_law_pairs(row, history, roster)
    assert rule == "roster-existent-public-law-pair"
    assert [e["public_law_corrected"] for e in emissions] == ["89-670", "91-605"]
    assert all(e["public_law"] is None for e in emissions if "public_law" in e), (
        "the grammar read nothing here; the roster did, so the reading lives in the correction column"
    )

    # Fence 1: the roster must hold the pair.
    assert _history_read_public_law_pairs(row, history, {(89, 670)}) is None
    # Fence 2: this rule or its agency must cite it elsewhere. 113-128 is in
    # the roster and cited by nobody here.
    assert (
        _history_read_public_law_pairs(_failed_row("113-128", rin="2130-AA10"), history, roster)
        is None
    )
    # Fence 3: a pool that knows a section by that number holds the competing
    # reading, and the rule refuses rather than choosing.
    competing = _CitationHistory.build(
        [
            pl_row("2130-AA10", 89, 670),
            pl_row("2130-AB99", 91, 605),
            _failed_row(
                "Clean Air Act sec 89",
                rin="2130-AC01",
                authority_type="act_relative",
                parse_status="ok",
                act_key="clean air act",
                act_section="89",
            ),
        ]
    )
    assert _history_read_public_law_pairs(row, competing, roster) is None
    # The value may carry its own section tail, the tolerance the fused
    # spelling already had.
    tailed = _failed_row("89-670, sec. 13111 to 13112", rin="2130-AA10")
    assert _history_read_public_law_pairs(tailed, history, roster)[1][0][
        "public_law_corrected"
    ] == "89-670"


def _pinned_roster_oracles(keys_by_agency=None, keys_by_rin=None):
    """``_ActOracles`` carrying the REAL pinned roster and a chosen corpus one."""

    from refspec.registry.unified_agenda_parquet import _ActOracles, _initialism_roster

    return _ActOracles(
        lookup={},
        keys_by_rin=keys_by_rin or {},
        keys_by_agency=keys_by_agency or {},
        glosses={},
        pinned=_initialism_roster(),
    )


def test_the_pinned_roster_names_the_act_no_record_in_this_corpus_defines() -> None:
    """CMS RIN 0938-AK14, Fall 2000, box 0: ``sec 212 of BBRA of 1999``.

    Nothing in this corpus says what BBRA stands for. CMS's own Federal
    Register notice 00-8708 does -- "the Medicare, Medicaid, and State
    Childrens Health Insurance Program Balanced Budget Refinement Act of 1999
    (BBRA)" -- and that sentence, its URL and its digest are the roster row
    this reading names.
    """

    from refspec.registry.unified_agenda_parquet import _read_pinned_roster_act, _Tally

    tally = _Tally()
    row = _failed_row("sec 212 of BBRA of 1999", rin="0938-AK14", publication_id="200010")
    rule, emissions = _read_pinned_roster_act(row, _pinned_roster_oracles(), tally)
    assert rule == "pinned-roster-initialism:pinned-quote"
    assert emissions == [{
        "authority_type": "act_relative",
        "act_key": "medicare, medicaid, and schip balanced budget refinement act of 1999",
        "act_section": "212",
        "stated_act_name": None,
        "stated_section": None,
        "act_initialism_roster": "BBRA@0938 pinned-quote",
    }]
    # The year the filer states is identity, not decoration: 1999 has to be in
    # the act the roster names or the whole reading refuses.
    assert _read_pinned_roster_act(
        _failed_row("sec 212 of BBRA of 2004", rin="0938-AK14"), _pinned_roster_oracles(), tally
    ) is None
    assert tally.initialism_roster_refusals["the-sections-do-not-corroborate"] == 1


def test_the_pinned_roster_does_not_break_a_tie_the_corpus_already_refused() -> None:
    """CMS RIN 0938-AQ16, Fall 2010, box 3: ``mma, sec 811``.

    CMS's own filings resolve three Medicare acts whose initials reach MMA --
    the Modernization Act of 2003, the Balanced Budget Refinement Act of 1999
    and the Benefits Improvement and Protection Act of 2000 -- and
    ``agency-roster-initialism`` refuses the row on that count. The pinned
    roster carries an MMA/0938 row naming Pub. L. 108-173 and it MUST NOT save
    it: a roster entry is evidence about letters, never about which of two
    acts one filer meant.
    """

    from refspec.registry.unified_agenda_parquet import _read_pinned_roster_act, _Tally

    cms = {"0938": {
        "medicare prescription drug, improvement, and modernization act of 2003",
        "medicare, medicaid, and schip balanced budget refinement act of 1999",
        "medicare, medicaid, and schip benefits improvement and protection act of 2000",
    }}
    tally = _Tally()
    row = _failed_row("mma, sec 811", rin="0938-AQ16", publication_id="201010")
    assert _read_pinned_roster_act(row, _pinned_roster_oracles(cms), tally) is None
    assert tally.initialism_roster_refusals["the-corpus-roster-is-already-ambiguous"] == 1
    assert row["act_initialism_roster"] is None, "a refused tie leaves no note at all"

    # WHAT DOES answer this row, in the artifact, is the corpus's own gloss:
    # CMS writes "Medicare Modernization Act (MMA)" in its own authority column
    # 35 times, which picks one of the three by testimony rather than by file,
    # and ``agency-gloss-narrowed-initialism`` publishes it. That rule is older
    # than this roster, was measured agreeing with the roster oracle 99 times
    # out of 99, and is exactly the mechanism the pinned roster may not
    # imitate: the filer said which act it meant, and a roster row did not.
    from refspec.registry.unified_agenda_parquet import _ActOracles, _read_abbreviated_act

    glossed = _ActOracles(
        lookup={}, keys_by_rin={}, keys_by_agency=cms,
        glosses={"0938": {"MMA": {"medicare modernization act"}}}, pinned=None,
    )
    rule, emissions = _read_abbreviated_act(
        _failed_row("mma, sec 811", rin="0938-AQ16"), glossed
    )
    assert rule == "agency-gloss-narrowed-initialism"
    assert emissions[0]["act_key"] == (
        "medicare prescription drug, improvement, and modernization act of 2003"
    )
    # And with no gloss, nothing answers it at all.
    assert _read_abbreviated_act(
        _failed_row("mma, sec 811", rin="0938-AQ16"),
        _ActOracles(lookup={}, keys_by_rin={}, keys_by_agency=cms, glosses={}, pinned=None),
    ) is None

    # One survivor is the other half of the same rule: agency-roster-initialism
    # has already had its turn, and a FILE does not argue with testimony.
    ihs = {"0917": {"buy indian act"}}
    lone = {"0938": {"social security act"}}
    assert _read_pinned_roster_act(
        _failed_row("SSA 1819", rin="0938-AN95"), _pinned_roster_oracles(lone), tally
    ) is None
    assert tally.initialism_roster_refusals["the-corpus-roster-already-speaks"] == 1
    # At IHS (0917-AA07, Spring 2005, box 0: "MMA, sec 506") nothing competes
    # -- and until 2026-08-31 nothing corroborated either, so the row kept its
    # "failed" with a candidate written beside it. inv-62 then raw-verified
    # IHS's own Federal Register sentence (07-2740: "...Modernization Act of
    # 2003 (MMA), (Pub. L. 108-173)") and the roster row is pinned-quote: the
    # FILER said which act it meant, in print, so it resolves without the
    # agency fence. "No competing act" was never the evidence; the quote is.
    ihs_row = _failed_row("MMA, sec 506", rin="0917-AA07", publication_id="200504")
    rule, emissions = _read_pinned_roster_act(ihs_row, _pinned_roster_oracles(ihs), tally)
    assert rule == "pinned-roster-initialism:pinned-quote"
    assert emissions[0]["act_key"] == (
        "medicare prescription drug, improvement, and modernization act of 2003"
    )
    # The weakest tier, where it still stands: ARRA at the Department of
    # Education (1810) resolves in the index and nothing more, and ED's own
    # resolved acts never include the Recovery Act, so the candidate is
    # written beside the failed row and nothing publishes.
    ed_row = _failed_row("ARRA 2009", rin="1810-AB19", publication_id="200910")
    assert _read_pinned_roster_act(
        ed_row, _pinned_roster_oracles({"1810": {"higher education act of 1965"}}), tally
    ) is None
    assert ed_row["act_initialism_roster"] == (
        "ARRA@1810 candidate-index-match (candidate: american recovery and reinvestment act of 2009)"
    )


def test_the_weakest_roster_tier_publishes_only_behind_the_agency_fence() -> None:
    """``candidate-index-match`` is "the hypothesised name resolves in the
    index" and nothing more -- the operator wave 5 measured inventing a wrong
    survivor 15.25% of the time. It publishes where the filer's own resolved
    acts hold that act and leaves a CANDIDATE where they do not."""

    from refspec.registry.unified_agenda_parquet import _read_pinned_roster_act, _Tally

    tally = _Tally()
    # An ED (1810) row, Fall 2009: "ARRA 2009". 1810's own filings never
    # resolve the Recovery Act, so nothing is published. (ARRA@0412 sat here
    # until 2026-08-31, when inv-62 raw-verified 0412's own notice 2026-10817
    # spelling the act out with "(ARRA)" after it; that row is pinned-quote
    # now and resolves without the fence -- asserted just below.)
    unfenced = _failed_row("ARRA 2009", rin="1810-AB19", publication_id="200910")
    assert _read_pinned_roster_act(unfenced, _pinned_roster_oracles(), tally) is None
    assert unfenced["authority_type"] == "other" and unfenced["parse_status"] == "failed"
    assert unfenced["act_initialism_roster"] == (
        "ARRA@1810 candidate-index-match (candidate: american recovery and reinvestment act of 2009)"
    )
    assert tally.initialism_roster_refusals["the-candidate-tier-is-unfenced-here"] == 1
    quoted = _failed_row("ARRA 2009", rin="0412-AA64", publication_id="200910")
    rule, emissions = _read_pinned_roster_act(quoted, _pinned_roster_oracles(), tally)
    assert rule == "pinned-roster-initialism:pinned-quote"
    assert emissions[0]["act_key"] == "american recovery and reinvestment act of 2009"

    # The same tier, fenced: CMS's own filings resolve the Public Health
    # Service Act, and "USPHSA" cannot reach it by initials (PHSA can, USPHSA
    # is a letter longer). The roster supplies the letters; the corpus still
    # supplies the act.
    fenced = _failed_row("USPHSA, sec 353", rin="0938-AK83", publication_id="200104")
    rule, emissions = _read_pinned_roster_act(
        fenced, _pinned_roster_oracles({"0938": {"public health service act"}}), tally
    )
    assert rule == "pinned-roster-initialism:candidate-index-match"
    assert emissions[0]["act_key"] == "public health service act"
    assert emissions[0]["act_section"] == "353"


def test_a_token_that_names_no_act_is_typed_and_never_resolved() -> None:
    """"FIPS 140-2" is a standard, "NAFTA" is a trade agreement, "56 DCR 7413"
    is a law reporter and "INS secs. 208, 241, and 274A" is either an agency or
    a mistyped INA. Typing the first three IS the answer; refusing the fourth by
    name is the answer for it. None of them resolves an act."""

    from refspec.registry.unified_agenda_parquet import _read_pinned_roster_act, _Tally

    tally = _Tally()
    for text, rin, note in (
        ("FIPS 140-2", "0790-AJ29", "FIPS@0790 not-an-act:standard"),
        ("NAFTA", "1615-AA57", "NAFTA@1615 not-an-act:treaty"),
    ):
        row = _failed_row(text, rin=rin)
        assert _read_pinned_roster_act(row, _pinned_roster_oracles(), tally) is None
        assert row["act_initialism_roster"] == note
        assert row["authority_type"] == "other" and row["parse_status"] == "failed"
    assert tally.initialism_roster_refusals["the-token-is-not-an-act"] == 2

    undecided = _failed_row("INS secs. 208, 241, and 274A", rin="1615-AC40")
    assert _read_pinned_roster_act(undecided, _pinned_roster_oracles(), tally) is None
    assert undecided["act_initialism_roster"] == "INS@1615 ambiguous"
    assert tally.initialism_roster_refusals["the-roster-row-names-no-act"] == 1

    # A token the roster holds at OTHER agencies does not travel to this one.
    travelled = _failed_row("SDWA1412(b)(1)(B)", rin="2060-AD86")
    assert _read_pinned_roster_act(travelled, _pinned_roster_oracles(), tally) is None
    assert travelled["act_initialism_roster"] is None
    assert tally.initialism_roster_refusals["no-roster-row-at-this-agency"] == 1


def test_the_whole_value_shapes_read_four_spellings_they_used_to_refuse() -> None:
    """Four shapes the roster already answers and the regex threw away first,
    each with the filer's exact text and each measured on its own.

    Purely lexical, like ``_abbrev_act_reading`` itself: whether the letters
    resolve is the oracle's question, and every one of these still meets the
    same exactly-one-survivor fence afterwards.
    """

    from refspec.registry.unified_agenda_parquet import _abbrev_act_reading as read

    # 1. A COMPOUND TAIL is a further paragraph of the section before it, not a
    #    new citation. 2060-AP70's "CAA 112(d)(2) & (3)" sits one box from
    #    "CAA 112(d)(6)", which the roster has read all along (review D).
    assert read("CAA 112(d)(2) & (3)") == ("CAA", None, ("112(d)(2)", "(3)"), False)
    assert read("CAA 112(g) or (q)") == ("CAA", None, ("112(g)", "(q)"), False)
    assert read("CWA 501(a) and (e)") == ("CWA", None, ("501(a)", "(e)"), False)
    assert read("CAA sec 112 (f) and (d)(6)") == ("CAA", None, ("112(f)", "(d)(6)"), True)
    # A bare tail may only FOLLOW a section, never open the list.
    assert read("(d)(2) & (3)") is None

    # 2. A SCHEME LABEL the filer put in front. The title is dropped: BBA
    #    section 4106 and RCRA section 3004 are act sections whatever title
    #    they land in, and "/" is the filer saying the two spellings are
    #    alternatives.
    assert read("42 USC BBA 4106") == ("BBA", None, ("4106",), False)
    assert read("42 USC /RCRA 3004(a)(q)") == ("RCRA", None, ("3004(a)(q)",), False)
    assert read("/TSCA 4") == ("TSCA", None, ("4",), False)
    assert read("/CAA 112 & 103") == ("CAA", None, ("112", "103"), False)
    # The label AFTER the initialism is a different citation and stays refused:
    # 0906-AA81's "PHSA 42, USC 247d-6d" is 42 U.S.C. 247d-6d, not PHSA sec 42.
    assert read("PHSA 42, USC 247d-6d and 247d-6e") is None
    # And two letters after a U.S.C. label are the damaged label, not an act --
    # 2501-AD30's "29 USC UC 794" belongs to the scheme-label repair.
    assert read("29 USC UC 794") is None

    # 3. THE ACT'S OWN NUMERIC SUFFIX. Four acts here carry one in their short
    #    title, and "TEA" followed by an unreadable "-21" matched nothing.
    assert read("TEA-21") == ("TEA-21", None, (), False)
    assert read("sec 4009 of TEA-21") == ("TEA-21", None, ("4009",), True)
    assert read("NDAA-17 sec. 701") == ("NDAA-17", None, ("701",), True)
    assert read("MAP-21") == ("MAP-21", None, (), False)

    # 4. LOWER CASE, with a marker, and never a connective. 0938-AQ16 writes
    #    "mma, sec 811"; the abbreviation comes back upper case because every
    #    oracle that meets it is.
    assert read("mma, sec 811") == ("MMA", None, ("811",), True)
    assert read("and sec 941") is None, "a list continuation is not an act named AND"
    assert read("and 510") is None
    assert read("see sec 5") is None

    # Nothing above disturbs what the shapes already read.
    assert read("CWA 301, 304") == ("CWA", None, ("301", "304"), False)
    assert read("CAA sec 112(f)(2)") == ("CAA", None, ("112(f)(2)",), True)
    assert read("212(a)(10) INA") == ("INA", None, ("212(a)(10)",), False)
    assert read("MCSA 1984") == ("MCSA", None, ("1984",), False)
    assert read("sec 212 of BBRA of 1999") == ("BBRA", "1999", ("212",), True)
    # And "PL-104-193" is a Public Law whatever the suffix rule now admits: the
    # label check strips the suffix before it looks.
    assert read("PL-104-193")[0].split("-")[0] == "PL"


def test_a_two_digit_year_in_the_section_slot_is_not_a_section() -> None:
    """CMS RIN 0938-AL42, Spring 2002, box 2: ``BBRA 99``.

    99 is 1999, and the first cut of the pinned roster published it as section
    99 of the Balanced Budget Refinement Act -- the same damage review D found
    already in the artifact on "BIPA' 00". The suppression is narrow on
    purpose: it fires only where the act's own name carries the year the two
    digits complete, so a genuinely short section survives.
    """

    from refspec.registry.unified_agenda_parquet import _corroborated_act_sections

    bbra = "medicare, medicaid, and schip balanced budget refinement act of 1999"
    assert _corroborated_act_sections(bbra, None, ("99",)) == ()
    # Marked, it is the publisher saying which slot the token fills.
    assert _corroborated_act_sections(bbra, None, ("99",), marked=True) == ("99",)
    # A two-digit token the act's own year does not explain is still a section.
    assert _corroborated_act_sections(bbra, None, ("42",)) == ("42",)
    # HUD RIN 2577-AC94: "Section 3(a)(2)(B) of the USHA of 1937" keeps its 3.
    assert _corroborated_act_sections(
        "united states housing act of 1937", "1937", ("3(a)(2)(B)",), marked=True
    ) == ("3",)


@pytest.mark.slow
def test_every_corroborated_row_names_the_rule_that_produced_it(con) -> None:
    """The verdict column earns its keep: a rule that silently stops firing
    breaks a pin instead of just shrinking a total, and a consumer that
    trusts one rule and not another can tell them apart."""

    from refspec.registry.unified_agenda_parquet import ACT_CARRY_RULE, CORROBORATION_RULES, SIBLING_ACT_RULE

    mismatched = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where (corroboration_rule is not null) != (parse_status = 'corroborated')",
    )
    assert mismatched == 0, "the rule column is set exactly on corroborated rows"
    by_rule = {
        row[0]: row[1]
        for row in _rows(
            con,
            "select corroboration_rule, count(*) from "
            "'{d}/unified_agenda_legal_authorities.parquet' "
            "where corroboration_rule is not null group by 1"
        )
    }
    assert set(by_rule) <= set(CORROBORATION_RULES), "no undeclared rule reaches the artifact"
    expected = {
        # Wave 2 and 3's oracle, unchanged in kind. 2,290 -> 2,314 at rebuild
        # #11 (#44/45): +24, entirely rows leaving the 'other' pool -- 22 that
        # stated nothing at all (a bare initialism like "CAA 112"), 1 that
        # stated only a section ("112"), and the second citation the
        # /CAA-112-&-103 split mints (a row with no prior key at all) --
        # confirmed against the rebuild-10 baseline by a keyed join, with
        # 2,290 rows unmoved under the same rule name.
        "agency-roster-initialism": 2_327,
        "index-holds-the-stated-name": 130,
        # The publisher writes one citation across several elements; this is
        # the run of bare sections a single in-series public law bounds.
        "list-run-bounding-public-law": 87,
        # The gloss discriminator: 144 rows, every one the Medicare
        # Prescription Drug, Improvement, and Modernization Act of 2003.
        # 150 -> 151 at rebuild #11 (#44/45): +1, one row leaving the 'other'
        # pool ("mma, sec 811", RIN 0938-AQ16 publication 201010 ordinal 3).
        "agency-gloss-narrowed-initialism": 151,
        "agency-roster-word-prefix": 27,
        # A list yields one row per member, so these exceed the 378 failed
        # rows the rule reads.
        # Wave 5's punctuation tolerances feed the same fenced oracle: the
        # Oxford comma as ONE separator, a subsection-only list member
        # continuing the member before it, whitespace inside a subsection
        # chain, an unmatched closing parenthesis, and ", as amended".
        "rin-history-section-list": 749,
        # "USC 7401 et seq" — the et-seq tail is ignorable here too.
        "rin-history-titleless-usc": 43,
        "rin-history-labelless-pair": 24,
        "rin-history-volumeless-stat": 15,
        # "111-5, sec. 13111 to 13112" — the pair may carry its own section
        # tail, the tolerance the fused spelling already had.
        "roster-existent-public-law-pair": 40,
        "unique-dash-insertion": 17,
        "space-separator-roster-existence": 18,
        "to-separator-roster-existence": 35,
        # Rebuild #9's two new corroboration rules, unconditional because the
        # columns they write (usc_title_carried_from_ordinal,
        # label_correction_evidence) have been in the artifact since rebuild
        # #9 landed: 9cab6f65 (H2) publishes 111 usc/corroborated rows, every
        # one from a box holding nothing but section numbers that took its
        # title from a sibling box within six (uscTitleCarryRows); d7d96b95
        # (H4) publishes 48 rows (45 usc + 3 statute_at_large) from a scheme
        # label one edit from its spelling, corroborated by a pinned oracle
        # (authorityCorroboratedRowsByRule in the receipt). Both counts are
        # exact row counts under the rule name, verified directly against
        # this artifact.
        "sibling-usc-title-within-six-boxes": 111,
        "one-edit-on-a-scheme-label": 48,
    }
    # What the act resolver's two later rules add, once the artifact carries
    # them: the publisher's list order read for ACTS -- three boxes of EPA
    # 2040-AE95's Clean Water Act run holding a section number and nothing
    # else, each taking its act from the box at ordinal +-1 -- and one more
    # "Atomic Energy Act, Reorg Plan 3" the index-holds rule reads once the
    # year-less stem answers.
    # 131 -> 144 at rebuild #9 (66d96462, H3): +13, the same 13
    # act_relative/corroborated rows the continuations-families test and the
    # receipt census attribute to the year-fence fix -- count(*) where
    # corroboration_rule='index-holds-the-stated-name' moves 131 -> 144 on
    # this artifact vs the rebuild-8 baseline; every other rule above is
    # unchanged between the two builds.
    #
    # 144 -> 159 at rebuild #11 (#56): +15, exactly #56's own act-name-walk
    # widening -- 9 rows leaving the 'other' pool (5 naming both a name and a
    # section, 4 naming only a name) plus 10 rows that were already
    # act_relative/failed resolving under this rule for the first time, minus
    # 4 rows this rule had already corroborated that now resolve a step
    # further to parse_status 'resolved' (act_section_not_classified ->
    # table3-classification) and so leave corroboration_rule's domain
    # entirely. 9 + 10 - 4 = 15. #44/45 never touches this rule -- none of
    # the moved rows carry act_initialism_roster or
    # act_resolution_sibling_ordinal.
    #
    # New at rebuild #11 (#44/45): the pinned initialism roster's four
    # evidence tiers (2c83ff33/7f0159d8) and the sibling-act carry
    # (1115f279), each an exact row count under its own rule name, verified
    # directly against this artifact.
    #
    # New at rebuild #11 (#56, a08b5bdb): reordered-public-law-roster-
    # existence, the same 4 rows public_law_corrected's own +4 counts (see
    # test_public_law_corrections_are_corroborated_and_preserve_the_original).
    if _act_resolution_landed(con):
        expected |= {
            SIBLING_ACT_RULE: 3,
            "index-holds-the-stated-name": 159,
            "pinned-roster-initialism:pinned-quote": 191,
            "pinned-roster-initialism:candidate-index-match": 24,
            "pinned-roster-initialism:reverse-pl-verified": 7,
            "pinned-roster-initialism:self-glossing": 5,
            ACT_CARRY_RULE: 34,
            "reordered-public-law-roster-existence": 4,
            # New at rebuild #12 (the slash unit; its population, traps and
            # changed rows are research/evidence/investigations-2026-08-24/
            # units-grammar/unit2-slash/): a second authority read from
            # behind a slash, corroborated only through a named reader.
            "second-authority-behind-a-slash:agency-roster-initialism": 1_352,
            "second-authority-behind-a-slash:index-holds-a-bare-name-and-section": 61,
            "second-authority-behind-a-slash:index-holds-the-stated-name": 15,
        }
    assert by_rule == expected


@pytest.mark.slow
def test_the_receipt_census_agrees_with_the_table_it_describes(con) -> None:
    """A declared count that nothing recomputes is not a pin, it is a claim.

    The receipt's ``declaredClassifications`` exist so a consumer's pin failure
    NAMES the change instead of just failing -- but ``verify`` only re-hashes
    the four tables, so nothing checked that the counts still described the
    rows. They had already drifted: ``authorityCorroboratedRowsByRule`` shipped
    with eleven of the twelve rules, silently missing
    ``index-holds-the-stated-name`` and the 130 rows it produced, because the
    rule was added to ``CORROBORATION_RULES`` after the last build and no test
    recomputed the census. This test is that recomputation."""

    import json

    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    R = "'{d}/unified_agenda_cfr_references.parquet'"
    T = "'{d}/unified_agenda_timetables.parquet'"
    observed = {
        "authorityFailedRows": f"select count(*) from {L} where parse_status = 'failed' and authority_type = 'other'",
        "authorityUnstatedRows": f"select count(*) from {L} where authority_type = 'unstated'",
        "authorityPartialRows": f"select count(*) from {L} where parse_status = 'partial'",
        "authorityCorroboratedRows": f"select count(*) from {L} where parse_status = 'corroborated'",
        "publicLawCorrectedRows": f"select count(*) from {L} where public_law_corrected is not null",
        "uscTitleOutOfSeriesRows": f"select count(*) from {L} where usc_title_is_possible = false",
        "eoOutOfSeriesRows": f"select count(*) from {L} where eo_in_known_series = false",
        # The `executive_order is not null` half is load-bearing, not decoration:
        # `eo_in_known_series` is null on every row that cites no EO at all, so the
        # unguarded count reads 781,606 where the declared one reads 50. Without
        # this recomputation, dropping the guard from the receipt expression moved
        # the declared number by four orders of magnitude and failed nothing.
        "eoUnknownRows": (
            f"select count(*) from {L} where eo_in_known_series is null and executive_order is not null"
        ),
        "plCongressOutOfSeriesRows": f"select count(*) from {L} where pl_congress_in_series = false",
        "statVolumeOutOfSeriesRows": f"select count(*) from {L} where stat_volume_in_series = false",
        "impossibleTitleRows": f"select count(*) from {R} where cfr_title_is_possible = false",
        "implausiblePartRows": f"select count(*) from {R} where cfr_part_is_plausible = false",
        "titlelessRows": f"select count(*) from {R} where cfr_title is null",
        "timetableRows": f"select count(*) from {T}",
        "timetableRowsWithFrCitation": f"select count(*) from {T} where parse_status = 'ok'",
        "timetableFrCitationFailures": f"select count(*) from {T} where parse_status = 'failed'",
    }
    for key, sql in observed.items():
        assert declared[key] == _one(con, sql), f"receipt {key} does not describe the table"

    by_rule = {
        row[0]: row[1]
        for row in _rows(
            con,
            "select corroboration_rule, count(*) from "
            "'{d}/unified_agenda_legal_authorities.parquet' "
            "where corroboration_rule is not null group by 1"
        )
    }
    # Rebuild #12's receipt declares the slash unit's CLOSED rule vocabulary,
    # zero-count rules included (rebuild12-delta.txt records each arriving as
    # None -> 0), so the receipt may carry zero-valued names the table has no
    # rows for -- but a zero must never hide a row, and every table rule must
    # be declared.
    assert {k: v for k, v in declared["authorityCorroboratedRowsByRule"].items() if v} == by_rule
    assert all(v == 0 for k, v in declared["authorityCorroboratedRowsByRule"].items() if k not in by_rule)
    assert declared["authorityCorroboratedRows"] == sum(by_rule.values())


@pytest.mark.slow
def test_the_pinned_oracles_are_where_the_builder_looks_for_them() -> None:
    """Both oracles are located relative to this module's own file, and both
    loaders answer None when the file is absent rather than raising. That is
    right for a caller with no roster and silently wrong for one that believes
    it has one: a copy of the builder run from another directory produces a
    complete-looking artifact with zero Public Law corrections and every
    ``cfr_part_in_current_ofr_index`` NULL. Measured while proving this
    refactor byte-identical -- the control run did exactly that."""

    from refspec.registry.unified_agenda_parquet import (
        _FR_DOCUMENT_ROSTER_CSV,
        _OFR_INDEX_CSV,
        _PL_ROSTER_CSV,
        _current_ofr_parts,
        _fr_document_roster,
        _pl_roster,
    )

    assert _PL_ROSTER_CSV.is_file(), f"the Public Law roster is not at {_PL_ROSTER_CSV}"
    assert _OFR_INDEX_CSV.is_file(), f"the OFR subject index is not at {_OFR_INDEX_CSV}"
    assert _FR_DOCUMENT_ROSTER_CSV.is_file(), (
        f"the Federal Register document roster is not at {_FR_DOCUMENT_ROSTER_CSV}"
    )
    # Six documents keyed on (volume, START page): the five the damaged
    # citations meant, plus 2024-29633, which is in the roster precisely so the
    # competing reading of "89 FR 1022091" is refused by a row that HOLDS the
    # page it lands on rather than by never being looked at.
    fr_roster = _fr_document_roster()
    assert len(fr_roster) == 6
    assert fr_roster[(89, 102_091)].document_number == "2024-29238"
    assert fr_roster[(89, 102_091)].rins == frozenset({"0648-BK86"})
    assert fr_roster[(89, 102_091)].publication_date == "12/17/2024"
    near_miss = fr_roster[(89, 102_207)]
    assert near_miss.document_number == "2024-29633"
    assert not near_miss.rins and not near_miss.rin_agency_prefixes, (
        "the SEC notice witnesses nothing about any filer, and could corroborate nothing "
        "even if a reading landed on its start page"
    )
    # The FCC files no RIN into Federal Register metadata, so its two documents
    # carry the agency witness the research note verified instead.
    assert fr_roster[(85, 75_770)].rins == frozenset()
    assert fr_roster[(85, 75_770)].rin_agency_prefixes == frozenset({"3060"})
    dates, volumes = _pl_roster()
    # 21,039 laws, 57th-119th Congress: the fence every Public Law correction
    # rule is measured against.
    assert len(dates) == 21_039 and len(volumes) == 21_039
    assert dates[(115, 271)] == "10/24/2018", "the SUPPORT Act, the correction machinery's specimen"
    # 8,424 (title, part) pairs in the OFR's own 2025 subject index -- an
    # evidence-grade signal, never a verdict: a 1995 Panama Canal part is real
    # and absent from it, and 5 CFR 10001 is real and present.
    assert len(_current_ofr_parts()) == 8_424


def test_the_pinned_initialism_roster_keeps_its_evidence_tiers_apart() -> None:
    """The sixth file oracle. What it says is only ever as good as HOW it knows
    it, so the tier travels with every row: a Federal Register sentence CMS
    itself wrote is not the same claim as "this expansion happens to resolve in
    the index", and the second is the operator wave 5 measured inventing a
    wrong survivor 15.25% of the time. A roster with one ``status`` column
    would spend the second at the first's price."""

    from refspec.registry.unified_agenda_parquet import (
        _INITIALISM_ROSTER_CSV,
        INITIALISM_ROSTER_FENCED_TIER,
        INITIALISM_ROSTER_RESOLVING_TIERS,
        _initialism_roster,
    )

    assert _INITIALISM_ROSTER_CSV.is_file(), (
        f"the pinned initialism roster is not at {_INITIALISM_ROSTER_CSV}"
    )
    roster = _initialism_roster()
    assert len(roster) == 236, "(token, agency) pairs"
    assert sum(len(entries) for entries in roster.values()) == 297

    # BBRA at CMS: the specimen the whole roster was built for. Pinned by CMS's
    # own notice 00-8708, which spells the act out and puts "(BBRA)" after it.
    bbra = roster[("BBRA", "0938")]
    assert len(bbra) == 1 and bbra[0].status == "pinned-quote"
    assert bbra[0].act_name == "medicare, medicaid, and schip balanced budget refinement act of 1999"
    assert bbra[0].evidence_path.endswith("raw/fr_BBRA_2000.json")
    assert bbra[0].status in INITIALISM_ROSTER_RESOLVING_TIERS

    # The same three letters at another agency are simply not in the roster:
    # every row is keyed to the filer whose evidence was gathered.
    assert ("BBRA", "2060") not in roster

    # Weakest tier, and it says so. "ARRA" at ED is a hypothesis that resolves
    # in the index and nothing more, which is why the builder fences it. The
    # same letters at 0412 left this tier on 2026-08-31, when inv-62
    # raw-verified the filer's own "(ARRA)" sentence: same token, two tiers,
    # because the evidence differs per agency.
    assert roster[("ARRA", "1810")][0].status == INITIALISM_ROSTER_FENCED_TIER
    assert roster[("ARRA", "0412")][0].status == "pinned-quote"
    assert "inv-62" in roster[("ARRA", "0412")][0].evidence_path

    # Typed, never resolved -- and the type is in the status so a reader cannot
    # take one for an act with a missing name.
    assert roster[("FSH", "0596")][0].not_an_act_type == "directive"
    assert roster[("DCR", "3225")][0].not_an_act_type == "reporter"
    assert roster[("BB", "1210")][0].not_an_act_type == "division-letter"
    assert roster[("NAFTA", "1615")][0].not_an_act_type == "treaty"
    assert roster[("FIPS", "0790")][0].not_an_act_type == "standard"
    assert not roster[("BBRA", "0938")][0].not_an_act_type

    # Two readings survive at this agency, so the roster refuses by name rather
    # than choosing: "INS secs. 208, 241, and 274A" are Immigration and
    # Nationality Act sections, and INS is also the pre-2003 agency.
    assert roster[("INS", "1615")][0].status == "ambiguous"
    assert roster[("PPRA", "0938")][0].status == "belief-only"

    # NDAA is keyed by FISCAL YEAR, because every year is a different act, and
    # the bare token names none of them.
    ndaa = {entry.year_key: entry for entry in roster[("NDAA", "0720")]}
    assert set(ndaa) == {"", "2009", "2013", "2017", "2021", "2023"}
    assert ndaa[""].status == "ambiguous" and not ndaa[""].act_name
    assert ndaa["2021"].act_name == "national defense authorization act for fiscal year 2021"
    # Two of the five are not listed in the pinned index under any wording, and
    # the roster records that rather than dropping them.
    assert ndaa["2023"].act_name == "national defense authorization act for fiscal year 2023"

    # Eight tokens are keyed by AGENCY because the letters mean different
    # things at different filers.
    assert roster[("EPA", "0596")][0].act_name == "energy policy act of 1992"
    assert roster[("EPA", "2030")][0].status == "ambiguous"


def test_the_initialism_roster_refuses_two_rows_at_one_key(tmp_path, monkeypatch) -> None:
    """Exactly-one-survivor starts at the file. Two rows for one token, agency
    and year would make the roster itself the ambiguity, and the loader says so
    instead of picking whichever came first."""
    import pytest

    from refspec.registry import unified_agenda_parquet as module

    clash = tmp_path / "roster.csv"
    header = module._INITIALISM_ROSTER_CSV.read_text(encoding="utf-8").splitlines()[0]
    body = ("BBRA,0938,,pinned-quote,a,106-113,p,sha256:x,q,1,\n"
            "BBRA,0938,,candidate-index-match,b,106-113,p,sha256:x,q,1,\n")
    clash.write_text(f"{header}\n{body}", encoding="utf-8")
    monkeypatch.setattr(module, "_INITIALISM_ROSTER_CSV", clash)
    with pytest.raises(ValueError, match="two rows for BBRA at 0938"):
        module._initialism_roster()


def test_whole_value_label_repairs_are_named_and_anchored() -> None:
    """Four label damages whose numbers are intact, each anchored to the
    entire value so prose can never donate one. Measured on the failed pool
    2026-08-22: 38 rows lowercase the Statutes label, 8 put a comma between
    the code label and its own section marker, 6 stutter the "et" of their
    own "et seq." tail forward, and 9 drop the U from USC."""

    from refspec.registry.citation_grammar import parse_authority_citation

    def read(text):
        citation = parse_authority_citation(text)[0]
        return (citation.authority_type, citation.usc_title, citation.usc_section,
                citation.statute_volume, citation.statute_page)

    assert read("126 stat 11") == ("statute_at_large", None, None, 126, 11)
    assert read("61 stat. 1180") == ("statute_at_large", None, None, 61, 1180)
    assert read("47 U.S.C., sec. 151") == ("usc", 47, "151", None, None)
    assert read("16 USC et 1531 et seq") == ("usc", 16, "1531", None, None)
    assert read("49 SC 30166") == ("usc", 49, "30166", None, None)
    # The whole-value anchor is the fence: inside prose a lowercase "stat" is
    # a word, and the repair never fires.
    assert read("the stat 11 report")[0] == "other"
    # An undamaged value is untouched.
    assert read("126 Stat. 11") == ("statute_at_large", None, None, 126, 11)
    assert read("5 USC 552") == ("usc", 5, "552", None, None)


def test_wave_five_label_repairs_are_inert_where_the_grammar_already_reads() -> None:
    """Ten more damages to a U.S.C. label whose numbers are intact, each
    anchored to the entire value and each measured INERT over the 41,378
    distinct authority values the grammar already reads (2026-08-22). The
    inertness is the fence: an operator that rewrites a value which already
    parses is changing an answer, not recovering one."""

    from refspec.registry.citation_grammar import parse_authority_citation

    def read(text):
        citation = parse_authority_citation(text)[0]
        return (citation.authority_type, citation.usc_title, citation.usc_section)

    assert read("18 U.S.C, 1350") == ("usc", 18, "1350")  # comma in the label's slot
    assert read("47 U.S.C . 154(j)") == ("usc", 47, "154")  # space inside the label
    assert read("19 U.S.C.. 3314") == ("usc", 19, "3314")  # the period typed twice
    assert read("21 .U.S.C. 387i") == ("usc", 21, "387i")  # the period on the label
    assert read("12 U.S.C. U.S.C. 93a") == ("usc", 12, "93a")  # the label stuttered
    assert read("z49 USC 47508") == ("usc", 49, "47508")  # one stray keystroke
    assert read("3o USC 1201 et seq") == ("usc", 30, "1201")  # O for zero
    assert read("47 (USC 201(b)") == ("usc", 47, "201")  # paren before the label
    assert read("42 USC (290dd-1)") == ("usc", 42, "290dd-1")  # paren around the section

    # Each fence, stated as the value it refuses.
    assert read("12 USC 1431(a)") == ("usc", 12, "1431"), "a subsection is not damage"
    assert read("15. U.S.C. 78w(a)") == ("usc", 15, "78w"), "the wave-2 spelling stands"
    assert read("5 USC 552, 553") == ("usc", 5, "552"), "a list comma is not label damage"


def test_a_structural_designator_names_the_title_it_sits_in() -> None:
    """"26 USC subchapter U" is a real container this grammar has no column
    for, so the row reads as the title it also states — partial, never "ok",
    the posture "16 USC et seq" already has. 29 rows, 8 spellings."""

    from refspec.registry.citation_grammar import parse_authority_citation

    for text, title in (
        ("26 USC subchapter U", 26),
        ("8 USC part 2", 8),
        ("49 U.S.C. subtitle IV", 49),
        ("5 U.S.C. part III, subpart F", 5),
        ("20 USC title IV", 20),
    ):
        row = parse_authority_citation(text)[0]
        assert (row.authority_type, row.usc_title, row.usc_section, row.parse_status) == (
            "usc",
            title,
            None,
            "partial",
        )
    # The designator WORD is required: a bare number after the label is a
    # section, and the fuller grammar reads it.
    assert parse_authority_citation("26 USC 7805")[0].usc_section == "7805"
    # A title-less designator names nothing.
    assert parse_authority_citation("U.S.C. chapter 137 legacy provisions")[0].authority_type == (
        "other"
    )


def test_an_impossible_cfr_title_beside_a_real_register_page_reads_as_the_page() -> None:
    """"60 CFR 15845" claims a title the CFR does not have and states a
    volume and page the Register does: 60 FR 15845 is a real page of the
    March 27, 1995 issue (web-verified 2026-08-22), cited by NASA as
    authority for its 14 CFR 1214 rule. The text's own numbers refute its
    claimed scheme — the measurement that relabelled 64 timetable citations
    in wave 1 — and it is the only such value in the failed pool."""

    from refspec.registry.citation_grammar import parse_authority_citation

    row = parse_authority_citation("60 CFR 15845")[0]
    assert (row.authority_type, row.fr_volume, row.fr_page) == ("federal_register", 60, 15845)
    # A title the CFR actually has is never second-guessed, whatever the part.
    assert parse_authority_citation("35 CFR 62")[0].authority_type == "cfr"
    assert parse_authority_citation("50 CFR 15845")[0].authority_type == "cfr"
    # Nor is a volume outside the Register's own series.
    assert parse_authority_citation("99 CFR 15845")[0].authority_type == "other"


def test_the_subsection_gap_is_closed_only_where_a_section_owns_the_paren() -> None:
    """"1919 (b)(1)(A)" is section 1919's subsection, and "and (3)" is a list
    member. The operator is anchored on a digit or a closing parenthesis to
    its left, which is exactly what tells the two apart."""

    from refspec.registry.unified_agenda_parquet import _SUBSECTION_GAP

    assert _SUBSECTION_GAP.sub("", "sec 932 (c) (2) MMA") == "sec 932(c)(2) MMA"
    assert _SUBSECTION_GAP.sub("", "1919 (b)(1)(A)") == "1919(b)(1)(A)"
    assert _SUBSECTION_GAP.sub("", "CAA 112(d)(2) and (3)") == "CAA 112(d)(2) and (3)"
    assert _SUBSECTION_GAP.sub("", "Sec 1819(a) to (f)") == "Sec 1819(a) to (f)"
    assert _SUBSECTION_GAP.sub("", "48 cl ct 221 (2000)") == "48 cl ct 221 (2000)"


def test_a_subsection_only_list_member_carries_no_new_place() -> None:
    """"41102(2), (4) and (8)" is one section with three subsections. Reading
    "(4)" as a section 4 would mint a citation the publisher never wrote."""

    from refspec.registry.unified_agenda_parquet import _history_section_tokens

    assert _history_section_tokens("41102(2), (4) and (8)") == ["41102(2)"]
    assert _history_section_tokens("668dd and 668ee, as amended") == ["668dd", "668ee"]
    assert _history_section_tokens("12838, and 12905(h)") == ["12838", "12905(h)"]
    assert _history_section_tokens("2277a-10)") == ["2277a-10"]
    assert _history_section_tokens("1814(i) (2)") == ["1814(i)(2)"]
    # With nothing in front of it a parenthetical is not a list at all.
    assert _history_section_tokens("(4) and (8)") is None


def test_act_prose_operators_only_reach_spellings_the_index_answers() -> None:
    """Sections-in-front, parenthetical drops, designator strips and the
    year-prefix reordering — every reading passes through the closure, one
    row per listed section, ranges kept as their stated pair."""

    from refspec.registry.unified_agenda_parquet import _act_prose_recoveries

    lookup = {
        "social security act": "social security act",
        "fair labor standards act of 1938": "fair labor standards act of 1938",
        "national technology transfer and advancement act of 1995":
            "national technology transfer and advancement act of 1995",
        "faa reauthorization act of 2018": "faa reauthorization act of 2018",
        "trade and development act of 2000": "trade and development act of 2000",
        "older americans act of 1965": "older americans act of 1965",
        "consolidated appropriations act, 2018": "consolidated appropriations act, 2018",
        # the year-style variant the closure derives; the operators read
        # through the closure, never around it
        "consolidated appropriations act of 2018": "consolidated appropriations act, 2018",
    }
    assert _act_prose_recoveries(
        "205(u) and 1631(e)(7) of the Social Security Act", lookup
    ) == (("social security act", "205"), ("social security act", "1631"))
    assert _act_prose_recoveries("sec 1154 to 1160 of the Social Security Act", lookup) == (
        ("social security act", "1154-1160"),
    )
    assert _act_prose_recoveries("Older Americans Act of 1965, as amended", lookup) == (
        ("older americans act of 1965", None),
    )
    assert _act_prose_recoveries(
        "National Technology Transfer and Advancement Act (NTTAA) of 1995", lookup
    ) == (("national technology transfer and advancement act of 1995", None),)
    assert _act_prose_recoveries("sec. 403 of the 2018 FAA Reauthorization Act", lookup) == (
        ("faa reauthorization act of 2018", "403"),
    )
    assert _act_prose_recoveries("Title V of the Trade and Development Act of 2000", lookup) == (
        ("trade and development act of 2000", None),
    )
    assert _act_prose_recoveries(
        "Consolidated Appropriations Act of 2018, div. L, title IV, sec. 410", lookup
    ) == (("consolidated appropriations act, 2018", "410"),)
    assert _act_prose_recoveries(
        "Fair Labor Standards Act of 1938 (as amended), section 4(f)", lookup
    ) == (("fair labor standards act of 1938", "4"),)
    assert _act_prose_recoveries("sec 1102 of the Act", lookup) == (), (
        "a name the index does not answer recovers nothing"
    )


def test_an_elided_list_member_joins_the_section_it_follows() -> None:
    """"Section 172(a) and (c)" is one section twice, not a section and a
    nameless second thing.

    The list splitter required every "and"-joined member to open on digits, so
    the whole match failed and the value recovered NOTHING -- not even the act.
    Review #2 traced it on 2060-AF01, whose same box's four self-contained
    siblings all resolved, and on 0938-AM02's "1883(i)(l) and (2) of the Social
    Security Act", where the unread 1883 was then taken for a year by the fence
    downstream (notes/F.json).
    """

    from refspec.registry.unified_agenda_parquet import _act_prose_recoveries

    lookup = {
        "social security act": "social security act",
        "clean water act": "clean water act",
        "clean air act amendments of 1990": "clean air act amendments of 1990",
    }

    # The two specimens, verbatim, and the marker-less spelling of the second.
    assert _act_prose_recoveries(
        "Section 172(a) and (c) of the 1990 Clean Air Act amendments", lookup
    ) == (("clean air act amendments of 1990", "172"),)
    assert _act_prose_recoveries(
        "1883(i)(l) and (2) of the Social Security Act", lookup
    ) == (("social security act", "1883"),)
    assert _act_prose_recoveries(
        "Sec 1883(i)(l) and (2) of the Social Security Act", lookup
    ) == (("social security act", "1883"),)
    # ONE reading, not two: the borrowed member designates the section its
    # neighbour does, and this reader publishes the section.
    assert _act_prose_recoveries(
        "secs 2104(e) and (f) of the Social Security Act", lookup
    ) == (("social security act", "2104"),)
    assert _act_prose_recoveries(
        "Section 405(d) and (e) of the Clean Water Act", lookup
    ) == (("clean water act", "405"),)

    # A genuinely second member still opens its own reading, elision or no
    # elision -- the list rule the widening must not swallow.
    assert _act_prose_recoveries(
        "205(u) and (v) and 1631(e)(7) of the Social Security Act", lookup
    ) == (("social security act", "205"), ("social security act", "1631"))
    # And a parenthetical with nothing in front of it is not a list at all.
    assert _act_prose_recoveries("(a) and (c) of the Social Security Act", lookup) == ()


@pytest.mark.slow
def test_a_parenthesised_gloss_between_a_name_and_its_year_costs_no_reading() -> None:
    """Measured 2026-08-24 on the whole corpus: the population is ZERO, and
    that is the finding.

    Review #2 read "Every Student Succeeds Act (ESSA) of 2015" (1810-AB62
    202104) as a gloss breaking ``stated_act_name``'s trailing-year capture,
    since the forward walk appends a year only where it immediately follows the
    word "Act" (notes/F.json). The STATEMENT is indeed short by its year -- but
    no row pays for it. Five texts in this corpus wear the shape, 30 rows, and
    every one of them already reads: the prose reader drops an internal
    parenthetical before it asks the closure, and ``find_act_relative_citations``
    matches the longest name it knows without ever seeing the tail.

    So the reader is deliberately NOT widened, and this test is why. Widening
    it would move seven Government Paperwork Elimination Act statements for no
    reading gained, and would turn one filer's WRONG year into an unmatchable
    statement: "National Organ Transplant Act (NOTA) of 1964" resolves today
    through the year-less listed name, and 'national organ transplant act of
    1964' is in no index.
    """

    from refspec.registry.citation_grammar import stated_act_name
    from refspec.registry.unified_agenda_parquet import _act_prose_recoveries

    lookup = _act_closure()

    # The specimen. No competing entry exists at either spelling: the listed
    # name carries no year, and 2015 is the year Pub. L. 114-95 was approved,
    # which is why cycle 1's enactment-year closure reaches it.
    assert lookup["every student succeeds act of 2015"] == "every student succeeds act"
    assert _act_prose_recoveries("Every Student Succeeds Act (ESSA) of 2015", lookup) == (
        ("every student succeeds act", None),
    )
    assert _act_prose_recoveries(
        "National Technology Transfer and Advancement Act (NTTAA) of 1995", lookup
    ) == (("national technology transfer and advancement act of 1995", None),)
    assert _act_prose_recoveries(
        "Government Paperwork Elimination Act (GPEA) of 1998 (PL 105-277, title XVII)", lookup
    ) == (("government paperwork elimination act", None),)

    # And the shape that says why the statement reader is left alone: the
    # filer's year is wrong, the name is right, and the name is what reads.
    assert "national organ transplant act of 1964" not in lookup
    assert stated_act_name(
        "sec 301 of the National Organ Transplant Act (NOTA) of 1964, as amended"
    ) == "National Organ Transplant Act"


def test_the_closure_derives_the_and_dropped_spelling() -> None:
    """"Resource Conservation Recovery Act" (79 rows) is the corpus's own
    and-less spelling; the variant composes with the year-less closure and a
    collision with a real index name refuses."""

    from refspec.registry.unified_agenda_parquet import _act_name_spelling_closure

    lookup = _act_name_spelling_closure({"resource conservation and recovery act of 1976"})
    assert lookup["resource conservation recovery act of 1976"] == (
        "resource conservation and recovery act of 1976"
    )
    assert lookup["resource conservation recovery act"] == (
        "resource conservation and recovery act of 1976"
    )
    # A real name is never overwritten by another act's derived variant.
    guarded = _act_name_spelling_closure({"food and security act", "food security act"})
    assert guarded["food security act"] == "food security act"


def test_separator_damaged_public_laws_grow_two_more_named_shapes() -> None:
    """"Pub. L. 111 to 203" writes the range word where the dash belongs —
    a bare law-number range names no congress and recovers nothing, so
    roster-existence of the pair is the only surviving reading — and the
    fused form may carry the value's own section tail."""

    from refspec.registry.unified_agenda_parquet import _corroborated_public_law_from_failed

    roster = ({(111, 203): "07/21/2010", (108, 11): "04/16/2003"}, {})
    assert _corroborated_public_law_from_failed("Pub. L. 111 to 203", roster) == (
        "111-203", "to-separator-roster-existence",
    )
    assert _corroborated_public_law_from_failed("title V, PL 111 to 203", roster) == (
        "111-203", "to-separator-roster-existence",
    )
    assert _corroborated_public_law_from_failed("Pub. L. 10811, sec 1503", roster) == (
        "108-11", "unique-dash-insertion",
    )
    assert _corroborated_public_law_from_failed("Pub. L. 111 to 204", roster) is None, (
        "a pair the roster does not hold is never minted"
    )


def test_a_reordered_public_law_recovers_against_the_roster() -> None:
    """"94 Pub. L. 588" writes the LABEL where the dash belongs.

    Review #2's class D found it on 0596-AD59 202504 -- the Forest Service's
    own organic statute, the National Forest Management Act -- and this corpus
    holds one more, "114 Pub. L. 185". The roster does the whole work: the
    halves read the other way name no law, because 588-94 and 185-114 are
    outside the series that ever legislated.
    """

    from refspec.registry.unified_agenda_parquet import _corroborated_public_law_from_failed

    roster = ({(94, 588): "10/22/1976", (114, 185): "06/30/2016"}, {})
    assert _corroborated_public_law_from_failed("94 Pub. L. 588", roster) == (
        "94-588", "reordered-public-law-roster-existence",
    )
    assert _corroborated_public_law_from_failed("114 Pub. L. 185", roster) == (
        "114-185", "reordered-public-law-roster-existence",
    )
    assert _corroborated_public_law_from_failed("94 PL 588.", roster) == (
        "94-588", "reordered-public-law-roster-existence",
    )
    # The negatives, each refused by a different half of the same fence.
    assert _corroborated_public_law_from_failed("94 Pub. L. 587", roster) is None, (
        "a pair the roster does not hold is never minted"
    )
    assert _corroborated_public_law_from_failed("5 PL 3", roster) is None, (
        "the 5th Congress predates numbered Public Laws"
    )
    assert _corroborated_public_law_from_failed("999 Pub. L. 1", roster) is None
    # And the ordinary spelling is not this shape: it needs no repair, so this
    # rule must not claim it and hand a consumer a correction column.
    assert _corroborated_public_law_from_failed("Pub. L. 94-588", roster) is None
    assert _corroborated_public_law_from_failed("sec 601 PL 94 588", roster) is None


@pytest.mark.slow
def test_an_unresolved_row_still_states_what_it_states(con) -> None:
    """A row nothing could resolve is not a total loss: it states an act name,
    a section, or both, so a consumer looking for section 326 of an NDAA finds
    the row even where no reader can say which year's NDAA it is.

    The per-column splits are asserted rather than described, because the
    earlier prose here ("1,465 of the 3,271 failed rows... 675 name an act,
    1,160 give a section") had gone stale against the very number below it."""
    def failing(where):
        return _one(
            con,
            "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
            f"where authority_type = 'other' and ({where})",
        )

    # The three move together when a later rule types a row act-relative: a
    # resolution supersedes the statement it replaces, so the statement leaves
    # the "other" pool with the row. 27 boxes left it for the sibling-act carry
    # and the year-less lexicon.
    #
    # All three gain at rebuild #8 (94ddfb03): the 4 new "other/failed"
    # continuation rows (a prose delegation and two mid-sentence-cut lists)
    # split 2 stating a name only, 2 stating a section only, so all 4 carry
    # one or the other -- count(*) where authority_type = 'other' and
    # authority_source != 'box' grouped by which statement column is set is
    # {name_or_section: 4, name_only: 2, section_only: 2}, and every one of
    # the 4 is source 'additional-info:legal-authority-cont'.
    #
    # All three move at rebuild #9 (66d96462, H3), every row of it the 484
    # retyped act_relative rows leaving the 'other' pool -- verified with the
    # rebuild-8 baseline's own venn: of the 518 baseline "name" rows, 253
    # name a name and no section and 265 name both; post-rebuild-9 only 24
    # name-only and 10 both remain (34 total, exactly
    # actRelativeRowsByResolutionReason's fence-refused population), so 484
    # left naming an act (229 name-only + 255 both). The "section_only"
    # category is NOT one delta: the 624 rows naming a section and NO act
    # name are untouched on both builds (H3 never touches them), and only
    # the "both" 255 leave, so 889 -> 634 is -255, not -484.
    # name_or_section: 1,142 -> 658 (-484). name_only: 518 -> 34 (-484,
    # all of it -- every retyped row named an act). section_only: 889 -> 634
    # (-255, the "both" subset of the same 484; the section-only-no-name 624
    # is the same integer on both builds).
    #
    # 658 -> 520 at rebuild #11: -138, entirely rows leaving the 'other' pool
    # (zero rows re-enter it). By corroboration_rule/status against the
    # rebuild-10 baseline, joined key-for-key: #56 takes 34 (15 to
    # act_relative/failed with no rule marker, 8 to act_relative/partial, 2
    # to act_relative/resolved, 9 to act_relative/corroborated under
    # index-holds-the-stated-name -- none of the 34 carries
    # act_initialism_roster or act_resolution_sibling_ordinal); #44/45 takes
    # 104 (70+9+3+2=84 under the four pinned-roster-initialism tiers, 18
    # under sibling-act-from-an-earlier-box, 1 under
    # agency-gloss-narrowed-initialism, 1 under agency-roster-initialism --
    # every one of the 104 carries act_initialism_roster or
    # act_resolution_sibling_ordinal, or is one of the two rules this
    # rebuild's own rule-census already ties to #44/45 exclusively).
    # 34 + 104 = 138.
    #
    # name_only: 34 -> 18 (-16), all of it #56's and none of it #44/45's (no
    # pinned-roster-initialism or sibling-act-carry row ever leaves with a
    # stated_act_name, since a resolution supersedes the statement it
    # replaces) -- the 9 index-holds rows that named an act (5 both name and
    # section, 4 name only) plus 4 act_relative/partial and 2
    # act_relative/resolved rows with no rule marker that named an act, plus
    # 1 more act_relative/partial row naming an act with no section.
    # 5 + 4 + 4 + 2 + 1 = 16.
    #
    # section_only: 634 -> 503 (-131) = #56's 27 (15 failed with no rule
    # marker + 5 index-holds naming both + 4 index-holds section-only + 4
    # act_relative/partial naming both + 3 act_relative/partial
    # section-only) plus #44/45's 104 (70 pinned-quote + 18 sibling-act-carry
    # + 9 candidate-index-match + 3 self-glossing + 2 reverse-pl-verified + 1
    # agency-roster-initialism + 1 agency-gloss-narrowed-initialism, every
    # one section-stated). 27 + 104 = 131.
    landed = _act_resolution_landed(con)
    # Rebuild #14 (2026-08-31 wave, research/evidence/rebuild14-delta-2026-08-31.txt): 520 -> 464 (-56), the
    # rows the apostrophe-year shape and the retiers resolve out of 'other'.
    # Rebuild #15 (2026-09-01 wave, research/evidence/rebuild15-delta-2026-09-01.txt): 464 -> 471 (+7),
    # reg-dot anchors retyped with their dotted stated_section kept (REF-062).
    assert failing("stated_act_name is not null or stated_section is not null") == (471 if landed else 1_162)
    assert failing("stated_act_name is not null") == (18 if landed else 540)
    # Rebuild #15 (2026-09-01 wave): 447 -> 454, the same +7 as the line above.
    assert failing("stated_section is not null") == (454 if landed else 905)


@pytest.mark.slow
def test_a_resolution_supersedes_a_statement(con) -> None:
    """These are statements, never identities. Where a later pass resolves a
    row the grammar could not read, the resolution replaces the statement
    rather than sitting beside it, so no consumer has to decide which of the
    two to believe — and nothing can mistake a stated name for an act key.

    Both statement columns, not just the name. Checking only the name let 147
    rows carry an ``act_key`` beside a ``stated_section``, and on an exploded
    list the two disagreed: "sec 3568 and 3569" resolves to two rows and put
    ``stated_section`` "3568" on the one resolving 3569.

    The fence is ``act_key``, deliberately, and not "any section column":
    "42 USC 2208 Atomic Energy Act of 1954, sec 168" reads as U.S.C. 42:2208
    AND states section 168 of the Atomic Energy Act. Those are two different
    facts and 7,400 rows carry both (7,280 until a date's comma stopped
    minting "22 U.S.C. 1979" out of "Sept 29, 1979": those 29 ghost rows
    inherited their text's stated section and counted here; 7,251 -> 7,383 at
    rebuild #8 (94ddfb03), +132, all of them new usc-type continuation rows
    whose text both parses to a section and states one in prose -- count(*)
    where usc_section is not null and stated_section is not null and
    authority_source != 'box' is 132, 124 from the legal-authority-cont
    family and 8 from additional-legal-authority; 7,383 -> 7,400 at rebuild
    #9 (6e9a15ae, H1), +17, entirely the box-run join -- count(*) where
    authority_type='usc' and parse_status='partial' and usc_section is not
    null and stated_section is not null is 6,504 on the rebuild-8 baseline
    and 6,521 here, +17, while H2's title-carry rows and H4's scheme-label
    rows carry no stated_section at all (0 against the same predicate) and
    H3 never sets usc_section on an act_relative row)."""
    for statement in ("stated_act_name", "stated_section"):
        assert (
            _one(
                con,
                "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
                f"where act_key is not null and {statement} is not null",
            )
            == 0
        ), statement
    # The other side of the same rule: a citation column and a statement DO
    # coexist, and that is not a leak.
    assert (
        _one(
            con,
            "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
            "where usc_section is not null and stated_section is not null",
        )
        # Rebuild #15 (2026-09-01 wave, research/evidence/rebuild15-delta-2026-09-01.txt): 7,376 -> 7,360,
        # the reg-dot anchors' usc_section is no longer minted (REF-062).
        == 7_360
    ), "a value states both when it carries both"


@pytest.mark.slow
def test_a_refused_resolution_leaves_the_statement_standing(con) -> None:
    """The calendar refuses a resolution; it must not also cost the row what
    the row says.

    Three rows read as act-relative and had their key refused for naming 2008
    in a 2006 or 2007 edition. They came out holding NEITHER a resolution nor
    a statement — the statement columns were guarded on the key the grammar
    PROPOSED rather than the key that survived — so a value plainly reading
    "The Emergency Supplemental Appropriations Act for Defense" published
    nothing at all."""

    orphaned = _rows(
        con,
        "select authority_text, stated_act_name from "
        "'{d}/unified_agenda_legal_authorities.parquet' "
        "where authority_type = 'act_relative' and act_key is null"
    )
    assert orphaned, "the calendar guard fires; if it stopped, this test is measuring nothing"
    for text, stated in orphaned:
        assert stated is not None, f"a refusal left {text!r} stating nothing"


@pytest.mark.slow
def test_no_corroboration_rule_relabels_a_row_the_grammar_could_read(con) -> None:
    """The most expensive fence in the module, asserted against the grammar
    itself rather than against the code path that is supposed to enforce it.

    Every corroborated row is re-read with ``parse_authority_citation``: all of
    them must come back "other". Without this fence the index-holds rule fired
    on partial rows and relabelled 7,069 real U.S.C. and CFR citations as
    act-relative, throwing the citation away to keep the name.

    Rebuild #12's slash unit is the one deliberate exception, and it is held
    to the fence's real claim rather than its old phrasing. A slash rule
    corroborates the SECOND authority of a value like ``33 USC 1328/CWA 318``
    -- a text whose U.S.C. head the grammar reads fine -- so "unreadable" is
    exactly wrong for its population. What the fence actually protects is
    that no rule ever RELABELS a reading away, so the slash half asserts
    that: every slash-corroborated text still carries its head's own
    non-corroborated rows in the table, and its head is readable. The
    non-slash rules keep the original unreadability bar unchanged.

    The control below is what gives the assertion teeth: run the same query
    over rows the grammar DID read and it fails loudly, so a green result here
    means the fence holds and not that the query cannot see anything."""

    from refspec.registry.citation_grammar import parse_authority_citation

    def unreadable(texts):
        return [t for t in texts if all(a.authority_type == "other" for a in parse_authority_citation(t))]

    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    corroborated = [
        row[0]
        for row in _rows(
            con,
            f"select distinct authority_text from {L} "
            "where parse_status = 'corroborated' and (corroboration_rule is null "
            "or corroboration_rule not like 'second-authority-behind-a-slash:%')"
        )
    ]
    assert len(corroborated) > 500, "the rules fire at scale"
    assert len(unreadable(corroborated)) == len(corroborated), (
        "a corroboration rule claimed a row the grammar could already read"
    )
    slash_texts = [
        row[0]
        for row in _rows(
            con,
            f"select distinct authority_text from {L} "
            "where corroboration_rule like 'second-authority-behind-a-slash:%'"
        )
    ]
    assert len(slash_texts) == 207, "the slash unit fires at its measured scale"
    assert not unreadable(slash_texts), (
        "a slash rule's whole point is a readable head; an unreadable text belongs to the other rules"
    )
    kept_heads = _one(
        con,
        f"select count(distinct s.authority_text) from (select distinct authority_text from {L} "
        "where corroboration_rule like 'second-authority-behind-a-slash:%') s "
        f"join {L} r on r.authority_text = s.authority_text and r.parse_status <> 'corroborated'",
    )
    assert kept_heads == len(slash_texts), (
        "a slash rule replaced a head reading instead of adding a second authority beside it"
    )

    control = [
        row[0]
        for row in _rows(
            con,
            "select distinct authority_text from "
            "'{d}/unified_agenda_legal_authorities.parquet' "
            # act_relative is excluded and the exclusion is the point: since
            # the act resolver landed, "partial" means TWO things -- a reading
            # the grammar completed only in part (a volume with no page), and
            # an act-relative citation whose act resolved and whose section did
            # not. Only the first is a row the grammar read, and this control
            # exists to prove the discriminator can see one.
            "where parse_status = 'partial' and authority_type <> 'act_relative' limit 400"
        )
    ]
    assert len(unreadable(control)) < 5, (
        "the discriminator is blind: rows the grammar reads must not look unreadable to it"
    )


@pytest.mark.slow
def test_no_section_column_names_a_place_without_a_number(con) -> None:
    """A section designation states a number. The weakest claim that separates
    a real designation from a sliced word, and the one the corpus supports:
    across every section-bearing column here, every value states a digit.

    Deliberately not a SHAPE. The Farm Credit Act numbers its sections by title
    and decimal ("4.9", "4.14B"); acts carry letter suffixes ("1860D-31"),
    hyphenated compounds ("290dd-1") and subsections ("1861(v)(1)(A)"). A shape
    test would have called all of those damage, which is how real data gets
    thrown away.

    ``stated_section`` is excluded on purpose and its residue asserted instead:
    it is the grammar's verdict, not this module's, and it currently carries
    1,323 rows sliced out of "Secretary", "Security", "Secrecy" and "sections".
    Pinned here so the number moves visibly when the grammar is fixed."""

    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    for column in ("act_section", "usc_section", "usc_chapter", "cfr_part"):
        assert (
            _one(con, f"select count(*) from {L} where {column} is not null and not regexp_matches({column}, '[0-9]')")
            == 0
        ), f"{column} names a place that states no number"
    assert (
        _one(
            con,
            f"select count(*) from {L} where stated_section is not null "
            "and not regexp_matches(stated_section, '[0-9]')",
        )
        # 1,323 when this tripwire was set, deliberately pinned so the number
        # would move visibly once the grammar stopped slicing "Sec" out of
        # "Security" and "Secretary". It did: the marker now needs a right
        # edge, and one value survives. Kept as a tripwire, not a target.
        == 1
    ), "the statement reader slices 'Sec' out of ordinary words; a resolution never inherits one"


@pytest.mark.slow
def test_the_escalation_rule_is_one_rule(con) -> None:
    """Six sites spelled this policy six ways: the first level naming exactly
    one survivor answers, a level naming SEVERAL refuses outright, and a level
    naming none is silent so the next may speak.

    The middle clause is the load-bearing one and the easiest to get wrong by
    accident. Escalating past an ambiguous level would let a wider roster break
    a tie the narrow one could not, which is how a fence stops being a fence —
    and the wider roster was measured inventing a wrong survivor 15.25% of the
    time."""

    from refspec.registry.unified_agenda_parquet import _first_level_answer, _oracle_levels

    assert _oracle_levels("2126-AB20") == ("2126-AB20", "2126")
    speaks = {"rin": {"a"}, "agency": {"b"}}
    assert _first_level_answer(["rin", "agency"], lambda k: speaks[k]) == "a"
    # silent, then speaking
    assert _first_level_answer(["rin", "agency"], lambda k: {"b"} if k == "agency" else set()) == "b"
    # ambiguous at the first level: refused, NEVER escalated
    assert (
        _first_level_answer(["rin", "agency"], lambda k: {"a", "z"} if k == "rin" else {"b"}) is None
    ), "a level that speaks ambiguously must not be escalated past"
    assert _first_level_answer(["rin", "agency"], lambda k: set()) is None


@pytest.mark.slow
def test_no_edition_cites_an_act_from_its_own_future(con) -> None:
    """Validity carries a calendar. The alias rule supplies a year when
    exactly one act supplies it, which is right in general and wrong when the
    only candidate had not been enacted yet: three rows in 2006 and 2007
    editions resolved to the Emergency Supplemental Appropriations Act for
    Defense, 2008. The date cannot reliably choose among an act family, but
    it can definitively refuse — so it does, and the row keeps its statement
    instead of a resolution it cannot have meant."""
    future = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where act_key is not null "
        "and regexp_extract(act_key, '(1[7-9][0-9][0-9]|20[0-9][0-9])$') <> '' "
        "and cast(regexp_extract(act_key, '(1[7-9][0-9][0-9]|20[0-9][0-9])$') as integer) "
        "    > cast(substr(publication_id, 1, 4) as integer)",
    )
    assert future == 0


def _authority_slot(ordinal, text, **extra):
    """One authority row as the builder emits it, BEFORE any corroboration.

    Every schema column is present for the same reason ``_failed_row`` gives:
    the split-citation index reads whole rows out of the table, and a rule
    tested against a partial dict is not being tested against what it gets.
    """

    from refspec.registry.unified_agenda_parquet import LEGAL_AUTHORITIES_SCHEMA

    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update(
        rin="2127-AL28",
        publication_id="201410",
        ordinal=ordinal,
        authority_text=text,
        authority_type="other",
        parse_status="failed",
        usc_appendix=False,
        usc_note=False,
    )
    row.update(extra)
    return row


def _donor_slot(ordinal, text, public_law, **extra):
    """A slot the grammar read as a Public Law, inside the numbered series."""

    return _authority_slot(
        ordinal,
        text,
        **{
            "authority_type": "public_law",
            "parse_status": "ok",
            "public_law": public_law,
            "pl_congress_in_series": True,
            **extra,
        },
    )


def test_the_split_citation_rule_puts_back_what_the_publisher_cut() -> None:
    """The publisher writes ONE citation across several <LEGAL_AUTHORITY>
    slots, cut at commas, and the parser reads one slot at a time — so it never
    sees that "sec 31601" is the tail of "PL 112-141" one ordinal up.

    Every fence below cost a measurement, and each is asserted by the specimen
    that flips when it is removed rather than by describing it."""

    from refspec.registry.unified_agenda_parquet import (
        _CitationHistory,
        _read_split_public_law,
        _SplitCitations,
        _Tally,
    )

    def read(rows, *, history=None):
        tally = _Tally()
        splits = _SplitCitations.build(rows)
        history = history or _CitationHistory.build([])
        bare = next(r for r in rows if r["authority_type"] == "other")
        return _read_split_public_law(bare, splits, history, tally), tally

    # Direction is genuinely mixed — measured, 112 donors sit before their
    # section slot and 49 after — so the rule is nearest-and-unique, never
    # "preceding". NHTSA 2127-AL28 states its law first; OMB 0348-AB69 states
    # it after the fragment, and both must read.
    for rows in (
        [_donor_slot(0, "PL 112-141", "112-141"), _authority_slot(1, "sec 31601")],
        [_authority_slot(0, "sec 31601"), _donor_slot(1, "PL 112-141", "112-141")],
    ):
        reading, _ = read(rows)
        assert reading is not None
        rule, emissions = reading
        assert rule == "list-run-bounding-public-law"
        assert emissions == [
            {"authority_type": "public_law", "public_law_corrected": "112-141",
             "pl_correction_evidence": "list-run-bounding-public-law",
             "stated_section": "31601"}
        ]

    # A list yields one row per member, the executive-order-plural rule, and
    # each row states its OWN section rather than inheriting the first.
    reading, _ = read(
        [_donor_slot(0, "PL 111-148", "111-148"),
         _authority_slot(1, "secs 1413, 2001 and 2201")]
    )
    assert [e["stated_section"] for e in reading[1]] == ["1413", "2001", "2201"]

    # Fence 1: a slot that already writes "sec N, PL X-Y, V Stat P" is a WHOLE
    # authority-note sentence, not the head of one that got split. Dropping
    # this fence reads 12 U.S.C. 1831n at FRB 7100-AF03 as a section of the
    # CARES Act — measured at 43 wrong rows across four agencies.
    reading, _ = read(
        [_authority_slot(0, "sec 401(b)"),
         _donor_slot(1, "sec 101(g), PL 104-191, 110 Stat 1936", "104-191",
                     stated_section="101(g)")]
    )
    assert reading is None, "a donor that states its own section donates nothing"

    # Fence 2: a donor outside its own edition's series is not a donor.
    reading, _ = read(
        [_donor_slot(0, "PL 999-141", "999-141", pl_congress_in_series=False),
         _authority_slot(1, "sec 31601")]
    )
    assert reading is None

    # Fence 3: the competing public-law-pair reading. "PL 89-564 / 89-670 /
    # 91-605" at FMCSA 0702-AA43 is a LIST OF LAWS, and every member tokenises
    # as a hyphenated section.
    reading, _ = read(
        [_donor_slot(0, "PL 89-564", "89-564"), _authority_slot(1, "89-670")]
    )
    assert reading is None, "a public-law pair is not a bare section"

    # Ambiguity refuses, and the refusal is NAMED and counted.
    reading, tally = read(
        [_donor_slot(0, "PL 111-148", "111-148"),
         _authority_slot(1, "sec 1001"),
         _donor_slot(2, "PL 111-152", "111-152")]
    )
    assert reading is None and tally.split_run_ambiguities == 1

    # Fence 4: the publisher's OWN resolved citations bind this section to a
    # different law. CMS 0938-AR04 writes "PL 111-48" where the ACA's section
    # 1413 needs 111-148, and the roster cannot refuse it — 111-48 is real.
    pool = _CitationHistory.build(
        [_donor_slot(0, "PL 111-148, sec 1413", "111-148", rin="0938-AZ99",
                     stated_section="1413")]
    )
    rows = [_donor_slot(0, "PL 111-48", "111-48", rin="0938-AR04"),
            _authority_slot(1, "secs 1413, 2001", rin="0938-AR04")]
    reading, tally = read(rows, history=pool)
    assert reading is None and tally.split_run_pool_conflicts == 1
    # ... and the same pool AGREEING is not a conflict.
    agreeing = _CitationHistory.build(
        [_donor_slot(0, "PL 111-48, sec 1413", "111-48", rin="0938-AZ99",
                     stated_section="1413")]
    )
    assert read(rows, history=agreeing)[0] is not None


def test_the_citation_history_pool_holds_a_public_law_section_space() -> None:
    """"sec. 939(e)" could not survive the pool because the pool held only
    U.S.C. and act sections — and the SAME RIN spells the whole citation
    "PL 111-203 sec 939(e)" in one string, in a space nothing read."""

    from refspec.registry.unified_agenda_parquet import (
        _CitationHistory,
        _history_read_section_list,
    )

    joined = _donor_slot(0, "PL 111-203 sec 939(e)", "111-203", rin="3235-AL33",
                         parse_status="partial", stated_section="939(e)")
    history = _CitationHistory.build([joined])
    assert history.public_law_sections["3235-AL33"] == {("111-203", "939")}

    split = _authority_slot(1, "sec. 939(e)", rin="3235-AL33")
    rule, emissions = _history_read_section_list(split, history)
    assert rule == "rin-history-section-list"
    # The reading goes to public_law_CORRECTED: the grammar read nothing on
    # this row, the publisher's other spelling did. The section keeps the
    # spelling the row states, which is how it joins back to the 16,615
    # references that write both halves in one string.
    assert emissions == [
        {"authority_type": "public_law", "public_law_corrected": "111-203",
         "pl_correction_evidence": "rin-history-section-list",
         "stated_section": "939(e)"}
    ]
    # A section the pool binds two ways is an ambiguity and refuses.
    two = _CitationHistory.build(
        [joined, _donor_slot(0, "PL 105-33 sec 939(e)", "105-33", rin="3235-AL33",
                             parse_status="partial", stated_section="939(e)")]
    )
    assert _history_read_section_list(split, two) is None


@pytest.mark.slow
def test_a_series_verdict_is_dated_to_the_edition_that_made_it() -> None:
    """Validity carries a calendar. Every series flag judged against a
    present-day constant, so OPM's "54 USC 4118" in a Spring 2004 filing read
    as possible — title 54 exists NOW and was enacted ten years later.

    The calendar is the pinned congress.gov roster read by approval date, not
    a formula, and it fails OPEN: where the roster cannot speak the verdict
    falls back to the undated bound rather than inventing a refusal."""

    from refspec.registry.unified_agenda_parquet import _pl_roster, _SeriesCalendar

    calendar = _SeriesCalendar.build(_pl_roster())

    # Title 54 was enacted by Pub. L. 113-287, approved 1994-12-19 — a date the
    # ROSTER supplies, so nothing here is a typed-in year.
    assert calendar.usc_title_from_year == {51: 2010, 52: 2014, 54: 2014}
    assert calendar.usc_title_is_possible(54, "200404") is False
    assert calendar.usc_title_is_possible(54, "201510") is True
    assert calendar.usc_title_is_possible(52, "201110") is False
    assert calendar.usc_title_is_possible(51, "201104") is True
    # The undated verdicts still hold: 53 was never enacted in any year.
    assert calendar.usc_title_is_possible(53, "202510") is False
    assert calendar.usc_title_is_possible(None, "202510") is None

    # "PL 105-58, 30 November 1995" in a Fall 1996 edition: the 105th Congress
    # first sat in 1997, and the string states its own date.
    assert calendar.pl_congress_in_series("105-58", "199610") is False
    assert calendar.pl_congress_in_series("104-1", "199610") is True
    assert calendar.pl_congress_in_series(None, "199610") is None
    # Volume 140 carries 2026 laws, so a Fall 2025 edition cannot cite it.
    assert calendar.stat_volume_in_series(140, "202510") is False
    assert calendar.stat_volume_in_series(109, "199510") is True

    # Executive orders are UNDATED on purpose: no EO date oracle is pinned in
    # this tree, and the cost was measured at zero rows before leaving it so.
    assert calendar.eo_in_known_series("12866") is True
    assert calendar.eo_in_known_series("99999") is False

    # Fail-open, not fail-closed: with no roster there is no calendar, and a
    # verdict falls back to the undated series bound.
    blind = _SeriesCalendar.build(None)
    assert blind.usc_title_is_possible(54, "200404") is True
    assert blind.pl_congress_in_series("105-58", "199610") is True


def test_eo_in_known_series_consults_the_roster_oracle_after_the_range_check() -> None:
    """The wiring spec's own shape: the range check runs FIRST and alone, and

    only a number that survives it is handed to the oracle for a finer
    answer. Three properties, each one this test breaks if it regresses:

    * a number outside [1, EO_HIGHEST_KNOWN] reads False even with a bound
      oracle -- the oracle is never even asked, so its own "unknown" verdict
      for a number outside every window can never soften a typo into None;
    * a number the oracle affirms (``exists``) still reads True, unchanged;
    * a number the oracle can neither affirm nor deny (``unknown``, EO 9397 --
      real, famous, and outside the sparse NARA codification window's
      coverage, per ``tests/test_eo_roster.py``) reads None, not the silently
      wrong True the bare range check gave before this wiring.
    """

    from refspec.registry.eo_roster import EoRosterOracle
    from refspec.registry.unified_agenda_parquet import _EO_ROSTER_DIR, _SeriesCalendar

    if not _EO_ROSTER_DIR.is_dir():
        pytest.skip("this tree does not carry the pinned EO roster")

    oracle = EoRosterOracle.from_directory(_EO_ROSTER_DIR)
    calendar = _SeriesCalendar.build(None, eo_oracle=oracle)

    # Out of range: the range check alone decides, whatever the oracle says.
    assert oracle.verdict(999_999).verdict == "unknown"
    assert calendar.eo_in_known_series("999999") is False

    # In range and the oracle affirms it: unchanged from the bare range check.
    assert oracle.verdict(12_866).verdict == "exists"
    assert calendar.eo_in_known_series("12866") is True

    # In range, real, famous -- and the sparse NARA window does not enumerate
    # it. Was silently True before this wiring; now honestly None.
    assert oracle.verdict(9397).verdict == "unknown"
    assert calendar.eo_in_known_series("9397") is None


def test_the_eo_oracle_is_asked_only_about_numbers_the_range_check_admitted() -> None:
    """A recording stub, because the real roster cannot witness two of the three

    things the wiring claims. It publishes no ``absent`` verdict anywhere --
    its one absent-capable window is measured fully dense -- so the test above
    never exercises ``absent -> False``; and no oracle can report *when* it was
    asked, so "the range check runs FIRST and alone" was inferred from the
    answers rather than observed. Both gaps hid a live mutation: making
    ``absent`` read True, and moving the lookup ahead of the range check while
    still returning the range check's answer, each survived the whole suite.

    This stub answers from a script and remembers every number handed to it:

    * a number outside [1, :data:`EO_HIGHEST_KNOWN`] reads False AND never
      reaches the oracle. A lookup whose result is discarded is still a
      lookup, and it is exactly the reordering that would let an oracle's
      ``unknown`` soften a five-digit typo into None;
    * inside the range every verdict maps once and distinctly: ``exists`` ->
      True, ``absent`` -> False, ``unknown`` -> None;
    * ``None`` in is ``None`` out, with no lookup at all.
    """

    from refspec.registry.citation_grammar import EO_HIGHEST_KNOWN
    from refspec.registry.eo_roster import EoVerdict
    from refspec.registry.unified_agenda_parquet import _SeriesCalendar

    # One number per verdict, each shaped the way EoVerdict's own invariants
    # demand: `absent` is only ever authorized by the dense fr_api window, and
    # `unknown` inside a window names that window's coverage story.
    scripted = {
        13_000: EoVerdict(13_000, "exists", "fr_api", source="fr-api"),
        14_000: EoVerdict(14_000, "absent", "fr_api"),
        9_397: EoVerdict(9_397, "unknown", "nara_codification", reason="nara_window_miss"),
    }

    class _SpyOracle:
        """Answers from the script, and records what it was asked, in order."""

        def __init__(self) -> None:
            self.asked: list[int] = []

        def verdict(self, eo_number: int) -> EoVerdict:
            self.asked.append(eo_number)
            if eo_number in scripted:
                return scripted[eo_number]
            # Every unscripted number here is out of range, so it falls outside
            # every declared window -- answered rather than raised, so a lookup
            # that should not have happened is reported by the assertion on
            # `asked` instead of arriving as a KeyError from somewhere else.
            return EoVerdict(eo_number, "unknown", None, reason="outside_known_windows")

    spy = _SpyOracle()
    calendar = _SeriesCalendar.build(None, eo_oracle=spy)

    # The three five-digit numbers this corpus actually cites (20450, 21600,
    # 23891 -- measure-output.txt's `outside_known_windows` trio), a six-digit
    # one, and both edges of the range.
    for typo in ("20450", "21600", "23891", "999999", "0", str(EO_HIGHEST_KNOWN + 1)):
        assert calendar.eo_in_known_series(typo) is False, f"EO {typo} passed the range check"
    assert calendar.eo_in_known_series(None) is None
    assert spy.asked == [], f"the oracle was consulted before the range check decided: {spy.asked}"

    # In range: one lookup apiece, and three verdicts that do not collapse.
    assert calendar.eo_in_known_series("13000") is True
    assert calendar.eo_in_known_series("14000") is False, "an oracle `absent` is a denial, not a doubt"
    assert calendar.eo_in_known_series("9397") is None
    assert spy.asked == [13_000, 14_000, 9_397]


def test_a_build_refuses_without_the_eo_roster_directory(tmp_path, monkeypatch, capsys) -> None:
    """The EO roster is the sixth directory oracle, with the same sharp edge

    as the others found relative to this file: absent, ``eo_in_known_series``
    silently falls back to the bare range check and ``eoUnknownRows`` reads 0
    on a build that never asked -- indistinguishable from "the oracle doubted
    nothing". The CLI refuses instead of writing that.
    """

    from refspec.registry import unified_agenda_parquet as module

    no_roster = tmp_path / "nowhere" / "eo-roster-2026-08-31"
    monkeypatch.setattr(module, "_EO_ROSTER_DIR", no_roster)
    with pytest.raises(SystemExit) as refusal:
        module.main(["--output-root", str(tmp_path / "out")])
    assert refusal.value.code == 2
    assert str(no_roster) in capsys.readouterr().err
    assert not (tmp_path / "out").exists(), "a refused build writes nothing"


@pytest.mark.slow
def test_no_edition_cites_a_series_from_its_own_future(con) -> None:
    """The same rule as the act calendar, on the other three flags, asserted
    against the artifact: nothing flagged possible names a place that did not
    exist when the citation was made."""

    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    # Titles 51, 52 and 54 are the three created inside the captured span.
    for title, created in ((51, 2010), (52, 2014), (54, 2014)):
        assert (
            _one(
                con,
                f"select count(*) from {L} where usc_title = {title} "
                f"and usc_title_is_possible and cast(substr(publication_id,1,4) as integer) < {created}",
            )
            == 0
        ), f"title {title} read as possible before it existed"
    # Five rows are what the calendar caught: 54 USC 4118 at OPM 3206-AK49 in
    # two 2004 editions, and 52 USC 7602(s) at EPA 2060-AO17 in three.
    assert (
        _one(
            con,
            f"select count(*) from {L} where usc_title in (51, 52, 54) "
            "and usc_title_is_possible = false",
        )
        == 5
    )
    # Three Public Laws name a Congress that had not sat: "PL 105-58,
    # 30 November 1995" (199610), "PL 109-90, sec 502" (200410) and
    # "Public Law 117-74" (202010). Each is in the numbered series, so only
    # the calendar can see them.
    assert (
        _one(
            con,
            f"select count(*) from {L} where pl_congress_in_series = false "
            "and cast(split_part(public_law, '-', 1) as integer) between 57 and 119",
        )
        == 3
    )


@pytest.mark.slow
def test_every_row_is_told_apart_by_the_key_the_receipt_declares(con) -> None:
    """The receipt has always said rows sharing (rin, publication_id, ordinal)
    are "distinguished by citation_ordinal". Two places wrote that column — the
    parse loop, and then the corroboration applicator exploding one failed row
    into several readings that all kept the base row's number — so 632 rows
    over 194 keys were indistinguishable. EPA RIN 2060-AF87's "CAA section
    202,203,247, 301(a)" came out as four rows all numbered 0.

    One writer, after every row exists, is what makes the declared key unique
    by construction. This is the check that breaks if a second one appears."""

    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    assert (
        _one(
            con,
            f"select count(*) from (select rin, publication_id, ordinal, citation_ordinal "
            f"from {L} group by all having count(*) > 1)",
        )
        == 0
    ), "the key the receipt declares does not distinguish the rows"
    # The reproducer, read back: one reference, four citations, four numbers.
    assert _rows(
        con,
        f"select citation_ordinal, act_section from {L} "
        "where rin = '2060-AF87' and publication_id = '199510' and ordinal = 0 "
        "order by citation_ordinal",
    ) == [(0, "202"), (1, "203"), (2, "247"), (3, "301")]
    # Numbering is DENSE within a reference: 0..n-1, no gaps, so a consumer can
    # count citations without a distinct-count.
    assert (
        _one(
            con,
            f"select count(*) from (select rin, publication_id, ordinal from {L} "
            "group by all having max(citation_ordinal) + 1 <> count(*))",
        )
        == 0
    )


@pytest.mark.slow
def test_the_unstated_bucket_is_three_facts_and_names_which(con) -> None:
    """One type held three different facts, and only one of them is a
    placeholder. The RID form instructions and EO 12866 4(b) separate them:

    - the ellipsis is the agency saying "there are more citations", so the
      list is truthful and INCOMPLETE. A consumer joining on legal authorities
      does not have the whole list for those rules and could not tell.
    - "Not Yet Determined" is a controlled value the form offers.
    - "None" is off-form: the form has no None box for Legal Authority, and
      EO 12866 4(b) requires the legal authority for every entry. It is a
      publisher defect, and typing it as a placeholder is what hid it."""

    from refspec.registry.unified_agenda_parquet import UNSTATED_KINDS

    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    counts = dict(_rows(con, f"select unstated_kind, count(*) from {L} "
                             "where unstated_kind is not null group by 1"))
    assert counts == {
        "more-citations-follow": 6_876,
        "not-yet-determined": 5_461,
        "none-off-form": 130,
    }
    assert set(counts) == set(UNSTATED_KINDS)
    # Set exactly on the rows it describes, and on every one of them: a
    # spelling this module does not know must fail loudly here rather than
    # become a silent fourth bucket.
    assert (
        _one(con, f"select count(*) from {L} "
                  "where (unstated_kind is not null) != (authority_type = 'unstated')")
        == 0
    )
    # The off-form ones are reportable, which is the whole point: NHTSA
    # 2127-AL99 carries "None" beside a published ANPRM at 83 FR 50872.
    assert (
        _one(
            con,
            f"select count(*) from {L} a join "
            "'{d}/unified_agenda_timetables.parquet' t using (rin, publication_id) "
            "where a.unstated_kind = 'none-off-form' and t.parse_status = 'ok'",
        )
        > 0
    ), "the defect is joinable to a published document"


@pytest.mark.slow
def test_a_recovered_public_law_section_agrees_with_the_publishers_own_spelling(con) -> None:
    """The hold-out for both Public Law section rules, and the invariant that
    would break if either stopped being fenced.

    The corpus writes a law and a section in ONE string 16,657 times. Neither
    recovery rule may contradict that spelling: the split rule never reads it
    at all, and the history rule reads it only at levels the escalation rule
    already refuses to blur. Scored before the pool fence existed, the split
    rule wrote 109 rows and disagreed on 10 of the 15 the key could judge —
    every one of them in two families the fence now names (CMS 0938-AR04's
    "PL 111-48" for the ACA's 111-148, and CMS 0938-AR64 reading an "of the
    Act" section as a section of the public law two slots down)."""

    from refspec.registry.unified_agenda_parquet import _history_bare

    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    answer_key = {"rin": {}, "agency": {}}
    for rin, section, law in _rows(
        con,
        f"select rin, stated_section, public_law from {L} "
        "where public_law is not null and stated_section is not null "
        "and corroboration_rule is null",
    ):
        for level, who in (("rin", rin), ("agency", rin[:4])):
            answer_key[level].setdefault((who, _history_bare(section)), set()).add(law)
    # 3,432 keys, down from over 5,000 when this was written: the grammar
    # stopped slicing "Sec" out of "Security", so the key no longer carries
    # junk sections like "urity". A smaller key built from real sections is a
    # better hold-out than a larger one padded with artifacts.
    assert len(answer_key["rin"]) > 3_000, "the hold-out is the corpus's own joined spellings"

    def score(rule, level):
        judged = agreed = 0
        for rin, section, reading in _rows(
            con,
            f"select rin, stated_section, public_law_corrected from {L} "
            f"where corroboration_rule = '{rule}' and authority_type = 'public_law'",
        ):
            who = rin if level == "rin" else rin[:4]
            truth = answer_key[level].get((who, _history_bare(section or "")))
            if not truth or len(truth) != 1:
                continue
            judged += 1
            agreed += next(iter(truth)) == reading
        return judged, agreed

    # list-run-bounding-public-law's OWN output is unchanged at rebuild #9
    # (87 rows total, verified in test_every_corroborated_row_names_the_rule
    # _that_produced_it) -- what moves is the HOLD-OUT itself: 6e9a15ae (H1)
    # mints 2 new public_law/partial rows (RIN 2126-AA63 "PL 106-159" stated
    # section 206, and 1545-BM81 "Pub. L. 93-406" stated section 3041), both
    # with corroboration_rule NULL, so both enter answer_key -- the raw
    # source population (public_law is not null and stated_section is not
    # null and corroboration_rule is null) moves 16,655 -> 16,657 on this
    # artifact vs the rebuild-8 baseline, growing the rin-level key set
    # 3,430 -> 3,432 and the agency-level set 2,058 -> 2,059 (one of the two
    # new sections collides at the agency level with an existing key). That
    # growth lets 2 more of list-run-bounding-public-law's already-existing
    # 87 rows find a single-answer match at each level; rin-history-
    # section-list's scored population is untouched (no new rows changed
    # its hold-out matches).
    for rule, level, scored in (
        ("list-run-bounding-public-law", "rin", 6),
        ("list-run-bounding-public-law", "agency", 7),
        ("rin-history-section-list", "agency", 132),
    ):
        judged, agreed = score(rule, level)
        assert judged == scored, f"{rule} at {level}: the hold-out changed size"
        assert judged == agreed, f"{rule} contradicts the publisher's own joined spelling"


@pytest.mark.slow
def test_a_rule_says_when_its_own_authority_list_is_incomplete(con) -> None:
    """The RID form has a box for "there are additional citations not listed
    below", printed as a trailing ellipsis. A rule that ticked it published a
    complete list of an incomplete fact, and a consumer joining on that list
    must be able to tell. The flag sits on the rule, where the join happens,
    not only on the ellipsis row buried in the authorities table — and it
    agrees with that row exactly, in both directions."""
    flagged = _one(
        con,
        "select count(*) from '{d}/unified_agenda_actions.parquet' "
        "where legal_authorities_declared_incomplete",
    )
    ellipsis_rules = _one(
        con,
        "select count(distinct (rin, publication_id)) "
        "from '{d}/unified_agenda_legal_authorities.parquet' "
        "where unstated_kind = 'more-citations-follow'",
    )
    assert flagged == ellipsis_rules == 6_876
    # Both sides read one spelling table. RIN 0625-AA66 writes its ellipsis
    # as ". . ." with spaces, which the grammar did not know and the table
    # did: the rule was flagged while its own row said "other". No row whose
    # text the table knows may be anything but unstated.
    from refspec.registry.unified_agenda_parquet import _unstated_kind

    disagreeing = [
        text
        for (text,) in _rows(
            con,
            "select authority_text from '{d}/unified_agenda_legal_authorities.parquet' "
            "where authority_type != 'unstated'",
        )
        if _unstated_kind(text) is not None
    ]
    assert disagreeing == [], disagreeing[:5]
    # The ellipsis is counted as an "authority" by legal_authority_count; a
    # consumer subtracting it needs the flag to know to.
    never_without = _one(
        con,
        "select count(*) from '{d}/unified_agenda_actions.parquet' a "
        "where legal_authorities_declared_incomplete and not exists ("
        "  select 1 from '{d}/unified_agenda_legal_authorities.parquet' l "
        "  where l.rin = a.rin and l.publication_id = a.publication_id "
        "  and l.unstated_kind = 'more-citations-follow')",
    )
    assert never_without == 0, "a rule flagged incomplete always holds the ellipsis that says so"


def test_a_build_refuses_without_its_pinned_oracles(tmp_path, monkeypatch, capsys) -> None:
    """The roster and the OFR index are read relative to this module, and
    their loaders answer None to a caller that has none. A build is a caller
    that thinks it has them: run from an unpacked old tree on 2026-08-22 it
    found neither, wrote an artifact with no Public Law corrections and no
    dated series verdicts, and passed --verify. The CLI refuses instead."""
    import pytest

    from refspec.registry import unified_agenda_parquet as module

    real_pl_roster = module._PL_ROSTER_CSV
    absent = tmp_path / "nowhere" / "public-law-roster.csv"
    monkeypatch.setattr(module, "_PL_ROSTER_CSV", absent)
    with pytest.raises(SystemExit) as refusal:
        module.main(["--output-root", str(tmp_path / "out")])
    assert refusal.value.code == 2
    assert str(absent) in capsys.readouterr().err
    assert not (tmp_path / "out").exists(), "a refused build writes nothing"

    # The Federal Register document roster is the fifth such oracle and has the
    # identical edge: absent, eight damaged citations stay "failed" and the
    # artifact looks complete. It is in the same refusal list.
    monkeypatch.setattr(module, "_PL_ROSTER_CSV", real_pl_roster)
    real_fr_roster = module._FR_DOCUMENT_ROSTER_CSV
    no_fr_roster = tmp_path / "nowhere" / "documents.csv"
    monkeypatch.setattr(module, "_FR_DOCUMENT_ROSTER_CSV", no_fr_roster)
    with pytest.raises(SystemExit) as refusal:
        module.main(["--output-root", str(tmp_path / "out")])
    assert refusal.value.code == 2
    assert str(no_fr_roster) in capsys.readouterr().err

    # The pinned initialism roster is the sixth, with the identical edge:
    # absent, 610 rows whose only defect is that no record defines their
    # letters stay "failed" and the artifact looks complete.
    monkeypatch.setattr(module, "_FR_DOCUMENT_ROSTER_CSV", real_fr_roster)
    no_initialisms = tmp_path / "nowhere" / "roster.csv"
    monkeypatch.setattr(module, "_INITIALISM_ROSTER_CSV", no_initialisms)
    with pytest.raises(SystemExit) as refusal:
        module.main(["--output-root", str(tmp_path / "out")])
    assert refusal.value.code == 2
    assert str(no_initialisms) in capsys.readouterr().err


@pytest.mark.slow
def test_the_register_carries_a_bound_too(con) -> None:
    """Four series carried a bound column and were loud; the Federal Register
    carried none, so "643FR 44121" (63 FR 44121), "610 FR 42527", "552 FR
    23781" and a page of 425527 sat typed federal_register and flagged by
    nothing. Volume 1 is 1936: an edition of year Y cannot cite above Y-1935,
    and no annual volume reaches page 100,000."""
    assert {"fr_volume_in_series", "fr_page_in_series"} <= set(LEGAL_AUTHORITIES_SCHEMA.names)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    out = _rows(
        con,
        f"select authority_text, fr_volume, fr_page, publication_id from {L} "
        "where fr_volume_in_series = false or fr_page_in_series = false order by 1",
    )
    assert len(out) == 6, out
    assert {row[0] for row in out} >= {"E.O. 12600, 552 FR 23781"}
    for text, volume, page, publication_id in out:
        assert volume > int(publication_id[:4]) - 1935 or page > 100_000, (text, volume, page)
    # Every other Register citation is inside the calendar: NULL only where
    # there is nothing to judge.
    assert _one(con, f"select count(*) from {L} where fr_volume is not null and fr_volume_in_series is null") == 0


@pytest.mark.slow
def test_the_authority_table_carries_the_cfr_section_it_read(con) -> None:
    """The parse held the section and the schema had no column for it.

    ``parse_cfr_citations("delegation of authority at 49 CFR 1.95")`` returns
    ``cfr_section="95"`` and always has; this table published "49 CFR part 1".
    Not a misread — every citation delivered is correct — but the same harm as
    one: a consumer joining on (title, part) cannot tell 49 CFR 1.95 from
    49 CFR 1.50, gets an answer that looks complete, and has no flag saying
    otherwise. The CFR reference table beside this one has carried the column
    since it existed, which is what makes this a projection loss rather than a
    reading one.

    Recovery, measured 2026-08-22 against the pinned table: 309 distinct
    authority values / 4,126 rows gain a section, and 22 (title, part) pairs
    stop collapsing — 49 CFR 1 was folding 22 distinct DOT delegation
    sections into one citation, 5 CFR 2635 eleven, 33 CFR 6 seven, 7 CFR 2
    six, 28 CFR 0 five, 48 CFR 1 four.
    """

    assert "cfr_section" in LEGAL_AUTHORITIES_SCHEMA.names
    assert "cfr_section" in CFR_REFERENCES_SCHEMA.names, "the sibling table it mirrors"
    # The column sits with the rest of the CFR triple rather than at the end,
    # so a reader meets title, part and section together.
    names = LEGAL_AUTHORITIES_SCHEMA.names
    assert names[names.index("cfr_part") + 1] == "cfr_section"
    # The emission carries it: every schema column is a key the builder writes,
    # which is what the corroboration branch's dict.fromkeys relies on.
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    built = {row[0] for row in _rows(con, f"describe select * from {L}")}
    missing = set(LEGAL_AUTHORITIES_SCHEMA.names) - built
    # The artifact on disk predates these columns. Stated rather than skipped:
    # the next rebuild closes them, and if anything ELSE is missing the pin
    # breaks instead of passing quietly.
    assert missing <= _COLUMNS_AWAITING_THE_REBUILD, missing


@cache
def _calendar():
    """The builder's own dated series calendar, read from the pinned roster."""

    from refspec.registry.unified_agenda_parquet import _pl_roster, _SeriesCalendar

    return _SeriesCalendar.build(_pl_roster())


def _usc_row(text, publication_id="201010", **extra):
    """A U.S.C. row as the section fence meets it.

    Parsed by the grammar the builder parses with and carrying the builder's
    own DATED title verdict, because both are inputs the fence reads: a row
    hand-typed with a section the grammar would never publish tests a citation
    nobody files.
    """

    from refspec.registry.citation_grammar import parse_authority_citation
    from refspec.registry.unified_agenda_parquet import LEGAL_AUTHORITIES_SCHEMA

    citation = parse_authority_citation(text)[0]
    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update(
        rin="0938-AA01",
        publication_id=publication_id,
        authority_text=text,
        authority_type=citation.authority_type,
        parse_status=citation.parse_status,
        usc_title=citation.usc_title,
        usc_section=citation.usc_section,
        usc_appendix=citation.usc_appendix,
        usc_note=citation.usc_note,
        usc_title_is_possible=_calendar().usc_title_is_possible(citation.usc_title, publication_id),
    )
    row.update(extra)
    return row


def test_the_section_fence_stands_beside_the_title_one() -> None:
    """`usc_title_is_possible` fences the TITLE, and answers true for every
    citation to a section that was never printed -- so a wrong section arrived
    typed `ok` and no count surfaced it. The silent-misreads campaign measured
    the cost: about 7% of rows that produced a citation produced the wrong one,
    twenty times the loud-refusal rate, with section non-existence the single
    dominant mechanism. These five columns are the missing fence, and they sit
    where a reader meets them beside the title verdict -- the same rule that
    puts cfr_section beside cfr_part."""

    from refspec.registry.usc_section_oracle import CORRECTION_RULES, UNKNOWN_REASONS, VERDICTS

    names = LEGAL_AUTHORITIES_SCHEMA.names
    start = names.index("usc_title_is_possible") + 1
    fence = _SECTION_FENCE_COLUMNS + _CORRECTED_KEY_COLUMNS
    assert tuple(names[start : start + len(fence)]) == fence
    # And the recodification's six sit directly after the correction they
    # must never become: a reader meets "the oracle cannot see this section"
    # and "an Act moved it, to these" together, which is the only way the
    # second is safe to read.
    assert tuple(names[start + len(fence) : start + len(fence) + len(_DISPOSITION_COLUMNS)]) == (
        _DISPOSITION_COLUMNS
    )

    # The vocabulary is the oracle's, restated nowhere here: a second spelling
    # of "absent" in this module would be a verdict with no oracle behind it.
    assert VERDICTS == ("exists", "absent", "unknown")
    assert set(UNKNOWN_REASONS) == {
        "edition_outside_oracle_window",
        "title_49_appendix_not_published",
        "appendix_title_not_published",
        "subsection_structure_not_published",
    }
    # "parse-as-filed" is a survivor able to outvote a proposal and never a
    # correction, which is why the evidence column can never carry it.
    assert "parse-as-filed" in CORRECTION_RULES
    from refspec.registry.usc_section_oracle import Correction

    with pytest.raises(ValueError, match="not a correction rule"):
        Correction(
            rule="parse-as-filed", title=21, original_section="371a", section="371", subsection="a", evidence="x"
        )


@pytest.mark.slow
def test_a_section_verdict_and_the_one_reading_that_survives() -> None:
    """The fence, over the rows the two reports name -- including the ones
    that must NOT be corrected.

    ``5 USC 552(a)`` is FOIA subsection (a) AND the Privacy Act at 5 U.S.C.
    552a, both real; ``42 USC 2139(a)`` is 387 rows of the same shape. Two
    readings survive, so neither is published and both refusals are counted by
    the names of the rules that survived. A row-count argument would have got
    both wrong.
    """

    from refspec.registry.act_resolution import USC_ACT_INDEX_ARTIFACT, ActIndex
    from refspec.registry.unified_agenda_parquet import (
        _ActNumbering,
        _judge_usc_sections,
        _usc_section_oracle,
    )

    rows = [
        _usc_row("21 USC 371a"),
        # The act-numbering fence, both ways round, on the two RINs visual
        # review #2 found wrong. Both are CFTC (agency 3038) and the roster
        # below gives that agency the Commodity Exchange Act, whose own §8a is
        # 7 U.S.C. 12a. 3038-AB50 states no pinpoint; 3038-AD31 states "(5)".
        _usc_row("7 USC 8a", publication_id="200004", rin="3038-AB50"),
        _usc_row("7 USC 8a(5)", publication_id="201110", rin="3038-AD31"),
        # And the same token filed by an agency whose roster does NOT hold the
        # Commodity Exchange Act: no association, no claim, A4 unfenced. This
        # is the row that would move if the fence ever read a corpus-wide
        # roster instead of the filer's own. (A different edition only so the
        # (text, edition) key below stays unique; nothing here is dated.)
        _usc_row("7 USC 8a(5)", publication_id="201210", rin="0938-AA01"),
        _usc_row("42 USC 1395(hh)"),
        _usc_row("42 USC 300(f) et seq"),
        _usc_row("15 U.S.C. 80bll(a)"),
        # The lost SPACE, the hyphen rule's mirror: title 15 has no section 78,
        # and 78o-10 is one the oracle enumerates.
        _usc_row("15 USC 78 o-10", publication_id="201110"),
        # The same shape REFUSED, because the stem is itself a real section:
        # 15 U.S.C. 77 and 77eee both exist.
        _usc_row("15 USC 77 eee", publication_id="199604"),
        _usc_row("5 USC 552(a)"),
        _usc_row("42 USC 2139(a)"),
        _usc_row("18 U.S.C. 3568", publication_id="202510"),
        _usc_row("42 USC 7401 et seq"),
        # C0, and the two pairs where the builder's dated verdict outranks the
        # oracle's undated one: title 54 was enacted in 2014.
        _usc_row("54 USC 4118", publication_id="200404"),
        _usc_row("54 USC 4118", publication_id="202510"),
        # Typed usc, naming no section: nothing to judge.
        _usc_row("42 USC"),
    ]
    # The rosters the builder itself builds: every act key a row resolved at
    # the RIN and at the agency. Only 3038 holds the Commodity Exchange Act
    # here, which is the whole fence.
    numbering = _ActNumbering.build(
        ActIndex.from_artifact(Path(__file__).resolve().parents[1] / USC_ACT_INDEX_ARTIFACT),
        {"3038-AB50": {"commodity exchange act"}, "3038-AD31": {"commodity exchange act"}},
        {"3038": {"commodity exchange act"}},
    )
    census = _judge_usc_sections(rows, _usc_section_oracle(), numbering)
    read = {
        (row["authority_text"], row["publication_id"]): (
            row["usc_section"],
            row["usc_section_verdict"],
            row["usc_section_corrected"],
            row["usc_section_correction_evidence"],
        )
        for row in rows
    }
    assert len(read) == len(rows), "one row per (text, edition) key, or an assertion below reads the wrong row"

    # A4: the lettered section that is really a subsection. The original stays
    # in usc_section, and the correction is spelled the way the Code spells it.
    assert read[("21 USC 371a", "201010")] == (
        "371a",
        "absent",
        "371(a)",
        "A4-subsection-rendered-as-a-lettered-section",
    )
    # A4 FENCED, and the act's own numbering published in its place. "8a" is
    # the Commodity Exchange Act's own section number -- the Code's source
    # credit for 7 U.S.C. 12a reads "(Sept. 21, 1922, ch. 369, §8a, as added
    # June 15, 1936, ch. 545, §10, 49 Stat. 1500 ...)" -- so A4's structurally
    # true reading (7 U.S.C. 8 is real and carries a subsection (a)) is the
    # wrong referent. Visual review #2, class H: 8 rows over these two RINs.
    assert read[("7 USC 8a", "200004")] == ("8a", "absent", "12a", "act-section-under-a-usc-label")
    assert read[("7 USC 8a(5)", "201110")] == ("8a", "absent", "12a(5)", "act-section-under-a-usc-label")
    # The pinpoint is the FILER's, taken from the text and not from the token:
    # Table III classifies the whole act §8a to one Code section, so §8a(5)'s
    # paragraph number is §12a(5)'s. 12a(5) is the Commission's general
    # rulemaking authority; 8(a) is contract-market designation applications.
    fenced = next(row for row in rows if row["rin"] == "3038-AD31")
    assert (fenced["usc_section_corrected_section"], fenced["usc_section_corrected_pinpoint"]) == ("12a", "(5)")
    assert fenced["usc_section"] == "8a", "the original stays where a consumer already joined on it"
    # And the identical text from an agency whose roster does not hold the act:
    # no association, no claim, A4 unfenced and publishing exactly as before.
    assert read[("7 USC 8a(5)", "201210")] == (
        "8a",
        "absent",
        "8(a)",
        "A4-subsection-rendered-as-a-lettered-section",
    )
    # B8: the pinpoint into a section that carries no lettered subsection at
    # all -- 42 U.S.C. 1395 has none, and 1395hh is a section. The bare section
    # exists, and since 53294b04 B8 is a CANDIDATE, not a correction: the
    # review of 2026-08-23 found "12 USC 1735(f)-14" corrected to 1735f, a real
    # section the rule never meant (it meant 1735f-14), and that B8's truth on
    # "15 U.S.C. 18(a)" rested on the abstract, evidence outside its inputs.
    # So the identity stays the filer's, the correction column stays NULL, and
    # 1395hh is named in the receipt's candidate census instead.
    assert read[("42 USC 1395(hh)", "201010")] == ("1395", "exists", None, None)
    # B1: "et seq." follows a section and never a subsection. 42 U.S.C. 300 is
    # itself real -- B1 does not wait for the bare section to be missing,
    # because the "et seq." tell is the whole discriminator.
    assert read[("42 USC 300(f) et seq", "201010")] == (
        "300",
        "exists",
        "300f",
        "B1-et-seq-follows-a-section",
    )
    # The lost hyphen citation_grammar refuses to guess: the 24-act index holds
    # 80b-1 and not 80b-11 and would mint the wrong section confidently; the
    # whole-Code oracle holds 80b-11 and one reading survives.
    assert read[("15 U.S.C. 80bll(a)", "201010")] == (
        "80",
        "absent",
        "80b-11",
        "lost-hyphen-with-one-typed-as-a-letter",
    )
    # The lost SPACE. A section's name never contains one, and title 15 has no
    # section 78 at all -- so the parse as filed has no witness and 78o-10,
    # which the oracle enumerates, is the only reading left. The stated tail is
    # part of the target: 15 U.S.C. 78o is also real, and reading it would mint
    # a section the citation does not name.
    assert read[("15 USC 78 o-10", "201110")] == (
        "78",
        "absent",
        "78o-10",
        "space-lost-before-a-lettered-suffix",
    )
    # And the same shape refused. 15 U.S.C. 77eee is the Trust Indenture Act's
    # section 305 -- and 15 U.S.C. 77 is a current section of title 15 in the
    # pinned release point. Two real sections, one string; the rule stays
    # silent and the filer's own reading stands.
    assert read[("15 USC 77 eee", "199604")] == ("77", "exists", None, None)
    # Two survivors: refused, and named.
    assert read[("5 USC 552(a)", "201010")] == ("552", "exists", None, None)
    assert read[("42 USC 2139(a)", "201010")] == ("2139", "exists", None, None)
    assert census.refusal_rows_by_survivors == {"B8+parse": 2}
    # An absence is only as wide as the oracle's window, and 18 U.S.C. 3568 --
    # repealed effective 1987-11-01, cited deliberately for pre-1987 conduct --
    # is the specimen it is named for. The verdict is absent; the caveat rides
    # on every absence the oracle utters, and the receipt states it once rather
    # than repeating it down a column.
    assert read[("18 U.S.C. 3568", "202510")] == ("3568", "absent", None, None)
    from refspec.registry.usc_section_oracle import ABSENT_CAVEATS

    assert _usc_section_oracle().section_verdict(18, "3568", 2025).caveats == ABSENT_CAVEATS
    assert ABSENT_CAVEATS == ("repealed_before_1994_not_stubbed",)
    assert read[("42 USC 7401 et seq", "201010")] == ("7401", "exists", None, None)

    # C0 outranks the section question, and it is the BUILDER's dated verdict
    # that decides: "54 USC 4118" filed in 2004 names a title enacted in 2014,
    # and the oracle's own undated predicate would have let it through.
    assert read[("54 USC 4118", "200404")] == ("4118", None, None, None)
    assert read[("54 USC 4118", "202510")] == ("4118", "absent", None, None)
    assert _usc_section_oracle().c0_title_impossible(54) is False, "undated, and outranked"
    assert census.title_impossible_rows == 1
    assert census.not_stated_rows == 1

    assert census.rows_by_verdict == {"exists": 6, "absent": 8, "unknown": 0}
    # B8 is a candidate since 53294b04: the specimen's "1395(hh)" row keeps its
    # identity and the rule counts zero corrections. A4 counts 2 -- "371a" and
    # the unassociated "8a(5)" -- and the act fence counts the 2 associated
    # ones, which is the split this whole test exists to fix in place.
    assert census.corrected_rows_by_rule == {
        "B1-et-seq-follows-a-section": 1,
        "B8-lettered-section-rather-than-a-pinpoint": 0,
        "A4-subsection-rendered-as-a-lettered-section": 2,
        "act-section-under-a-usc-label": 2,
        "lost-hyphen-with-one-typed-as-a-letter": 1,
        "space-lost-before-a-lettered-suffix": 1,
    }
    # A struck reading is NOT a refusal: the two fenced rows publish, so
    # nothing about the refusal census moves. That is measured on the whole
    # corpus too -- the scratch build of 2026-08-24 leaves the artifact's
    # uscSectionRefusalRowsBySurvivors byte-identical.
    assert census.refusal_rows_by_survivors == {"B8+parse": 2}


@pytest.mark.slow
def test_the_act_numbering_join_is_folded_on_both_sides() -> None:
    """Table III prints the act section; a row's token arrives folded.

    ``ActIndex.classifications`` is keyed by the spelling Table III PRINTS, and
    12,549 of its 75,596 distinct act-section spellings are not what
    ``normalize_section`` produces. A folded token looked up against a raw key
    finds nothing, so the fence would under-fire silently on every act that
    capitalises -- no error, no count, just a claim that never arrives. Both
    specimens below are real rows of the pinned build whose claim the unfolded
    lookup lost: Securities Exchange Act §10B and FD&C Act §745A.

    Nothing here moves a published value -- A4 never reads either token -- and
    that is exactly why the fold needs a test of its own: the corpus cannot
    show this defect today, and the next act that capitalises would.
    """

    from refspec.registry.act_resolution import USC_ACT_INDEX_ARTIFACT, ActIndex
    from refspec.registry.unified_agenda_parquet import _ActNumbering

    index = ActIndex.from_artifact(Path(__file__).resolve().parents[1] / USC_ACT_INDEX_ARTIFACT)
    # The publisher's own spelling, upper-case, and the folded one it is not.
    assert "10B" in index.classifications["1934:404"] and "10b" not in index.classifications["1934:404"]
    assert "745A" in index.classifications["1938:675"] and "745a" not in index.classifications["1938:675"]

    numbering = _ActNumbering.build(
        index,
        {"3235-AN18": {"securities exchange act of 1934"}},
        {"3235": {"securities exchange act of 1934"}, "0910": {"federal food, drug, and cosmetic act"}},
    )
    (sec,) = numbering.claims("3235-AN18", 15, "10b")
    assert (sec.act_key, sec.act_section, sec.section) == ("1934:404", "10b", "78j-2")
    # The RIN's roster answers before the agency's, and the agency's answers
    # for a RIN whose own boxes named nothing.
    assert sec.association == "rin"
    (fda,) = numbering.claims("0910-AH48", 21, "745a")
    assert (fda.act_key, fda.act_section, fda.section, fda.association) == (
        "1938:675",
        "745a",
        "379k-1",
        "agency",
    )
    # And an act on nobody's roster is nobody's claim, however the index spells
    # it: the association is the fence, not the spelling.
    assert numbering.claims("2040-AD00", 15, "10b") == ()


@pytest.mark.slow
def test_the_correction_splits_into_the_identity_and_the_pinpoint() -> None:
    """`usc_section_corrected` is the CODE's spelling, and so is not a key.

    "371(a)" is a pinpoint into section 371 and "1395hh" is a lettered section:
    one string, two different things, and a consumer keying on it moves the key
    off the section the citation names. spicysearch measured the cost on 8,523
    presidential bodies and 45,214 court opinions: of the 91 keys that depart
    under a corrected-then-base reading, the only four with any document
    exposure are CORRECT citations -- "15 U.S.C. § 18" in 27 opinions among
    them -- which lose every tag because a B8 proposal moves them
    (research/evidence/ledger-2026-08-22/verification-notes.md).

    So the fence publishes the identity and the pinpoint separately, from the
    same Correction, and the consumer keys on the identity. Where the rule is
    B8 that identity is a CANDIDATE and never the key: B8 rests on the release
    point printing no lettered subsection on the bare section, which is high
    precision on the 1395 family and not a proof that §18(a) is §18a.
    """

    from refspec.registry.unified_agenda_parquet import _judge_usc_sections, _usc_section_oracle

    rows = [
        # A4: a pinpoint into a real section. Identity 371, pinpoint (a).
        _usc_row("21 USC 371a"),
        # B8: a lettered SECTION, so there is no pinpoint to carry.
        _usc_row("42 USC 1395(hh)"),
        # B1: the same shape, reached by the "et seq." tell.
        _usc_row("42 USC 300(f) et seq"),
        # The recovered hyphen: the identity is the hyphenated section.
        _usc_row("15 U.S.C. 80bll(a)"),
        # The recovered space: likewise, and the stated tail rides along.
        _usc_row("15 USC 78 o-10", publication_id="201110"),
        # Refused, so nothing is published to split.
        _usc_row("5 USC 552(a)"),
        # The four keys the consumer measured, in the corpus's own spellings.
        _usc_row("15 U.S.C. 18(a), Clayton Act"),
        _usc_row("12 USC 1715(b)"),
        _usc_row("47 U.S.C. 399(b)"),
        _usc_row("25 U.S.C. 161(a)"),
    ]
    census = _judge_usc_sections(rows, _usc_section_oracle())
    split = {
        row["authority_text"]: (
            row["usc_section"],
            row["usc_section_corrected_section"],
            row["usc_section_corrected_pinpoint"],
            row["usc_section_corrected"],
        )
        for row in rows
    }

    assert split["21 USC 371a"] == ("371a", "371", "(a)", "371(a)")
    # B8 is a candidate since 53294b04, so nothing splits: see the section
    # fence test for why.
    assert split["42 USC 1395(hh)"] == ("1395", None, None, None)
    assert split["42 USC 300(f) et seq"] == ("300", "300f", None, "300f")
    assert split["15 U.S.C. 80bll(a)"] == ("80", "80b-11", None, "80b-11")
    assert split["15 USC 78 o-10"] == ("78", "78o-10", None, "78o-10")
    assert split["5 USC 552(a)"] == ("552", None, None, None)

    # The invariant that keeps the split from drifting from the Code's
    # spelling: the two columns concatenated ARE usc_section_corrected, and
    # all three are NULL together. Asserted over every row rather than the
    # corrected ones, so a split written where no correction survived breaks
    # it too.
    for row in rows:
        identity = row["usc_section_corrected_section"]
        pinpoint = row["usc_section_corrected_pinpoint"]
        assert (identity or "") + (pinpoint or "") == (row["usc_section_corrected"] or ""), row["authority_text"]
        assert (identity is None) == (row["usc_section_corrected"] is None), row["authority_text"]
        assert pinpoint is None or identity is not None, "a pinpoint into nothing"

    # The consumer's four cited keys: every one is a correct citation to a real
    # section whose B8 identity is the NEIGHBOUR, one letter along. Keying on
    # the corrected identity is what loses the 27 opinions printing
    # "15 U.S.C. § 18"; keying on usc_section keeps them and leaves 18a a
    # candidate to widen with.
    # Since 53294b04 B8 is a candidate, so none of the four carries a corrected
    # identity: the neighbour (18a, 1715b, 399b, 161a) is named in the receipt's
    # candidate census and the key a consumer reads is the filer's.
    assert [split[text][:3] for text in ("15 U.S.C. 18(a), Clayton Act", "12 USC 1715(b)")] == [
        ("18", None, None),
        ("1715", None, None),
    ]
    assert [split[text][:3] for text in ("47 U.S.C. 399(b)", "25 U.S.C. 161(a)")] == [
        ("399", None, None),
        ("161", None, None),
    ]

    # Every published correction here moves the identity, which is the census
    # the receipt carries: a rule that only ADDED a pinpoint would separate the
    # two counts, and none of the four does. The act fence is listed at ZERO
    # because these rows carry no roster -- every declared rule is listed
    # whether or not it fired, which is the only thing that can say a rule
    # stopped firing (see the section-fence test for the same rule at 2).
    assert census.identity_moved_rows_by_rule == {
        "B1-et-seq-follows-a-section": 1,
        "B8-lettered-section-rather-than-a-pinpoint": 0,
        "A4-subsection-rendered-as-a-lettered-section": 1,
        "act-section-under-a-usc-label": 0,
        "lost-hyphen-with-one-typed-as-a-letter": 1,
        "space-lost-before-a-lettered-suffix": 1,
    }
    assert census.identity_moved_rows_by_rule == census.corrected_rows_by_rule


def test_three_verdicts_the_grammar_computed_and_this_table_dropped() -> None:
    """A verdict a projection drops is a term with no consumer to break.

    `AuthorityCitation` has carried `cfr_part_is_plausible` and
    `statute_volume_matches_public_law` since the waves that measured them, and
    this table had no column for either: the IDENTICAL string was judged in the
    CFR reference table and unjudged here ("42 CFR 412106" flagged there,
    minted here with nothing said), and "PL 92-500 76 Stat. 816" -- 86 Stat.,
    not 76 -- sat inside the series bound with nothing to say it cannot be.
    """

    from refspec.registry.citation_grammar import parse_authority_citation

    names = LEGAL_AUTHORITIES_SCHEMA.names
    assert names[names.index("cfr_section") + 1] == "cfr_part_is_plausible", "the CFR triple's own verdict"
    assert names[names.index("stat_volume_in_series") + 1] == "statute_volume_matches_public_law"
    assert "cfr_part_is_plausible" in CFR_REFERENCES_SCHEMA.names, "the asymmetry this closes"

    def read(text, wanted):
        return [
            (citation.cfr_part_is_plausible, citation.statute_volume_matches_public_law)
            for citation in parse_authority_citation(text)
            if citation.authority_type == wanted
        ]

    # A digit-count verdict and nothing more: five-digit parts are real.
    assert read("42 CFR 412106", "cfr") == [(False, None)]
    assert read("42 CFR 412.106", "cfr") == [(True, None)]
    # The Statutes relation the series bound cannot reach: 76 Stat. is a real
    # volume, and it cannot be the one that printed Pub. L. 92-500.
    assert read("PL 92-500 76 Stat. 816", "statute_at_large") == [(None, False)]
    assert read("Pub. L. 104-191, 110 Stat. 1936", "statute_at_large") == [(None, True)]
    # A verdict, never a correction: which of the two numbers is damaged is
    # not decidable from the relation, so both stay as written.
    assert "statute_volume_corrected" not in names


@pytest.mark.slow
def test_the_corpus_fences_its_own_section_magnitudes() -> None:
    """The cheap fence beside the oracle: the corpus judging itself.

    `usc_title_is_possible` calls title 33 real and 33 U.S.C. 70116 is a
    section that title has never had. The 99th-percentile-times-ten ceiling
    catches the grossest of those at the cost of one pass over rows the build
    already holds -- and it is derived from THIS build's rows, never pinned,
    because a ceiling computed over one artifact and applied to the next is the
    stale oracle this module refuses everywhere else.
    """

    from refspec.registry.unified_agenda_parquet import _judge_usc_section_magnitudes

    rows = [_usc_row("33 USC 1223") for _ in range(100)]
    rows += [_usc_row("33 USC 70116"), _usc_row("42 USC 7401"), _usc_row("5 USC")]
    implausible = _judge_usc_section_magnitudes(rows)
    read = {(row["usc_title"], row["usc_section"]): row["usc_section_magnitude_is_plausible"] for row in rows}
    assert read[(33, "70116")] is False
    assert read[(33, "1223")] is True
    assert implausible == 1
    # A title the corpus cites once sets its own ceiling from that one row, so
    # the verdict is a silence dressed as a pass rather than evidence; a row
    # with no section to judge gets no verdict at all.
    assert read[(42, "7401")] is True
    assert read[(5, None)] is None


#: Every count in the three tests below was measured on a SCRATCH build of
#: commit e9aa1eef (`--output-root` under a temporary directory, same pinned
#: editions and oracles), because the artifact under output/ predates these
#: columns. They are pins awaiting that rebuild, not descriptions of the file
#: on disk today -- which is why the schema test above still lists the columns
#: the built table lacks. Every one of them reproduces unchanged on a scratch
#: build of `c782244d`, four grammar and oracle commits later, which is the
#: evidence that they measure the fence and not the day it was measured.
_SCRATCH_BUILD = "e9aa1eef"

#: The corrected-key split is later than the fence it splits, so its own counts
#: were measured on a scratch build of the commit that added it -- same pinned
#: editions and oracles, `--output-root` under a temporary directory. Nothing
#: else in the table moved: the correction the split reads is the one the fence
#: already published, so every count above reproduces on that build too.
_CORRECTED_KEY_SCRATCH_BUILD = "1118d687"


def _awaits_the_rebuild(
    con,
    column: str,
    scratch: str = _SCRATCH_BUILD,
    *,
    table: str = "unified_agenda_legal_authorities",
) -> None:
    """Say WHY the pins below are red, instead of a binder error naming a column.

    Stated rather than skipped, the same posture the schema test takes: a
    skipped pin is a pin nobody notices coming back wrong.
    """

    built = {row[0] for row in _rows(con, f"describe select * from '{{d}}/{table}.parquet'")}
    assert column in built, (
        f"the artifact under output/ predates {table}.{column}: every count in this test is measured on "
        f"the scratch build of {scratch} and turns green when the rebuild lands"
    )


def _awaits_the_oracle_switch(scratch: str) -> None:
    """The same thing to say when no new COLUMN arrives to say it.

    The 2026-08-24 authority-note switch widens an existing column's VALUES --
    the cache went from a 287-part set-cover to every note the register
    publishes -- so ``_awaits_the_rebuild``'s question, does the artifact have
    this column, cannot see it and the pins below would fail with a bare
    number. The receipt's own producer block can see it: it records the digest
    of the oracle file the build read, and the two generations are two files.
    """

    import json

    from refspec.registry.cfr_authority_notes import NOTES_SHA256

    recorded = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))
    assert NOTES_SHA256 in set(recorded.get("producer", {}).get("oracles", {}).values()), (
        "the artifact under output/ was built against the 287-part authority-note cache and this "
        f"module now pins the whole register's 8,240: every count in this test is measured on the "
        f"scratch build of {scratch} and turns green when the rebuild lands"
    )


@pytest.mark.slow
def test_the_section_fence_over_the_built_table(con) -> None:
    """The oracle's verdict on 687,435 U.S.C. rows, and what it refuses to say.

    Measured on the scratch build of commit e9aa1eef; awaits the rebuild.
    """

    _awaits_the_rebuild(con, "usc_section_verdict")
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    by_verdict = {
        row[0]: row[1:]
        for row in _rows(
            con,
            f"select usc_section_verdict, count(*), count(distinct authority_text), "
            f"count(distinct (usc_title, usc_section, usc_appendix)), count(distinct rin) from {L} "
            "where usc_section_verdict is not null and authority_type = 'usc' group by 1",
        )
    }
    # rows / texts / pairs / RINs. The pair key is the parse's own spelling
    # here and the oracle's normalised one in the builder; they agree because
    # the grammar already writes the join key's spelling, and a count that
    # moves is how this test would say they had stopped agreeing.
    #
    # Rebuild #8 (94ddfb03) adds 1,147 new usc-type continuation rows, all
    # judged: 49 absent / 1,098 exists / 0 unknown -- restricting the same
    # query to authority_source != 'box' gives exactly
    # {"absent": (49, 13, 7, 8), "exists": (1_098, 30, 116, 20)} and
    # restricting to authority_source = 'box' reproduces the prior pin
    # (668_575, 14_142, 2_551 unchanged) exactly, row for row.
    #
    # Rebuild #9 (d7d96b95 H4, 6e9a15ae H1, 9cab6f65 H2, 66d96462 H3) adds
    # 734 new usc-type rows, ALL verdict 'exists' -- absent and unknown are
    # both unchanged (14,191 and 2,551, identical to the rebuild-8 baseline).
    # 734 = H1's 577 usc/partial + 1 usc/ok, H2's 111 usc/corroborated
    # (usc_title_carried_from_ordinal is not null), H4's 45 usc/corroborated
    # (corroboration_rule='one-edit-on-a-scheme-label'); H3 mints no usc row.
    # count(*) where authority_type='usc' and parse_status in ('partial',
    # 'ok') moves 667,038 -> 667,616 (+578, H1) on this artifact vs the
    # rebuild-8 baseline; the two corroboration-rule markers add 111 (H2)
    # and 45 (H4); 578+111+45=734, matching exists' own row delta exactly
    # (669,673 -> 670,407).
    # Rebuild #15 (2026-09-01 wave, research/evidence/rebuild15-delta-2026-09-01.txt): -89 exists /
    # -42 absent / -53 unknown = reg-dot's 175 verdict losses (89/34/52,
    # REF-062) + the stat-page filer gate's 9 removed rows (0/8/1, REF-062).
    assert by_verdict == {
        "exists": (670_352, 28_891, 9_416, 41_795),
        "absent": (14_131, 1_861, 1_410, 2_113),
        "unknown": (2_493, 281, 163, 343),
    }
    # The census closes: every U.S.C. row is judged, or has no section to judge
    # (886), or names a title the edition could not have cited (134, which is
    # the whole of uscTitleOutOfSeriesRows -- C0 outranks the section).
    # 686,288 -> 687,435 at rebuild #8: +1,147, the new usc-type rows above
    # (unstated 886 and title-impossible 134 are both unchanged -- 0 of the
    # new rows land in either bucket).
    # 687,435 -> 688,169 at rebuild #9: +734, the same population as the
    # by_verdict move above; usc_section is null (886) and title-impossible
    # (134) are both unchanged (0 of the 734 new rows land in either).
    # 688,169 -> 688,180 at rebuild #12: +11, exactly the by_verdict move
    # above again (+34 exists, -18 absent, -5 unknown; rebuild12-delta.txt);
    # the unstated (886) and title-impossible (134) buckets hold still.
    # Rebuild #15 (2026-09-01 wave): 688,180 -> 687,997 (-183) = the 184 verdict
    # losses above MINUS one row that stayed usc-typed with its section
    # withheld -- the reg-dot APPENDIX refusal (REF-062): 2133-AB26@199610's
    # "46 app USC 1241.1", where the optional appendix-section group degrades
    # to a title-only appendix citation, so the row moves to the null-section
    # bucket (886 -> 887) instead of leaving the type.
    assert _one(con, f"select count(*) from {L} where authority_type = 'usc'") == 687_997
    assert 670_352 + 14_131 + 2_493 + 887 + 134 == 687_997
    assert _one(con, f"select count(*) from {L} where authority_type = 'usc' and usc_section is null") == 887
    assert (
        _one(
            con,
            f"select count(*) from {L} where usc_title_is_possible = false "
            "and authority_type = 'usc' and usc_section is not null",
        )
        == 134
    )
    # THE INVARIANT, rewritten 2026-08-24 when the fence grew a second
    # population. It used to read "no verdict outside a usc row", which stopped
    # being true when the act-derived sections were judged: a verdict now
    # stands wherever usc_section is non-null AND the row is either
    # authority_type 'usc' or an act_relative row the resolver filled (its
    # act_resolution_evidence names the source), and is NULL everywhere else.
    # This half -- nothing judged outside those two populations -- holds on both
    # sides of the rebuild and is asserted here; the other half, that every
    # act-derived section IS judged, is pinned in
    # test_the_act_derived_sections_are_judged_at_their_edition, which awaits
    # rebuild #12 because the artifact under output/ predates the fence.
    assert _one(
        con,
        f"select count(*) from {L} where usc_section_verdict is not null and authority_type <> 'usc' "
        "and not (authority_type = 'act_relative' and act_resolution_evidence is not null "
        "and usc_section is not null)",
    ) == 0
    # And the correction columns keep the ONE population they always had: a
    # correction repairs what a filer typed under a U.S.C. label, and nothing
    # on an act-relative row was typed that way.
    assert _one(
        con, f"select count(*) from {L} where usc_section_corrected is not null and authority_type <> 'usc'"
    ) == 0

    # An unknown names its hole, and 2,548 of the 2,551 are the pre-1996 Title
    # 49 Appendix no OLRC archive year carries -- the corpus's own temporal
    # evidence, not a publisher inventory. Nothing fell outside the window.
    assert _rows(
        con,
        f"select usc_section_verdict_reason, count(*) from {L} where usc_section_verdict_reason is not null "
        "and authority_type = 'usc' group by 1 order by 2 desc",
    ) == [("title_49_appendix_not_published", 2_490), ("appendix_title_not_published", 3)]
    assert _one(
        con,
        f"select count(*) from {L} where (usc_section_verdict = 'unknown') <> (usc_section_verdict_reason is not null)",
    ) == 0
    assert _row(
        con,
        f"select usc_section_verdict, usc_section_verdict_reason, count(*) from {L} "
        "where usc_title = 49 and usc_section = '1354' group by 1, 2",
    ) == ("unknown", "title_49_appendix_not_published", 117)

    # The edition year narrows and never accuses: 6,379 rows carry exists with
    # attested_at_edition = false. THE CAVEAT THAT USED TO STAND HERE IS PAID
    # OFF. It read: "the citing edition had not printed it" is the RIGHT
    # reading for only ~6,300 of 8,261, because the annual-archive extractor
    # matched archive member names case-sensitively and twelve publisher
    # volumes named like 2010USC12.htm were never read. That is fixed --
    # research/evidence/usc-section-oracle-2026-08-24 is generation 2 of the
    # oracle, extracted with re.IGNORECASE plus a guard that raises on any
    # unclassified archive member, and USC_SECTION_ORACLE_ARTIFACT now names
    # it. Re-measured against this build's own rows rather than the estimate:
    # 1,882 of the 8,261 (not the ~1,912 the review projected, which was the
    # hand-bucketed 1-high-confidence PLUS 2-uncertain buckets; the 30
    # uncertain rows are titles 40/41 at 2012 cited by pre-recodification
    # numbers the recovered volumes genuinely do not print, and they correctly
    # do NOT move) over 390 pairs and 538 RINs, title 12 @2010 alone 1,368.
    # 8,261 - 1,882 = 6,379. No verdict moves anywhere in the table: the
    # existence union is 66,780 pairs in both generations.
    # 8,229 -> 8,258 at rebuild #9: +29, split by type+status shape delta
    # against the rebuild-8 baseline -- H1 (usc/partial+ok) contributes 28
    # (8,229 -> 8,257 on that shape alone), H4 (corroboration_rule='one-edit-
    # on-a-scheme-label') contributes 1 (0 -> 1), H2 (title carry) 0; every
    # section H2 carries is gated to one the oracle prints AT the edition's
    # year, so none of its 111 rows can land here by construction.
    # 8,258 -> 8,261 at rebuild #12 (rebuild12-delta.txt).
    # 8,261 -> 6,379 at the oracle generation-2 switch. EXPECTED RECEIPT
    # DELTA: this value is only true of a build written by the generation-2
    # oracle; it fails against the rebuild-#12 artifact on disk until the
    # receipt is rebuilt.
    assert _one(
        con,
        f"select count(*) from {L} where usc_section_verdict = 'exists' "
        "and usc_section_attested_at_edition = false and authority_type = 'usc'",
    ) == 6_379
    assert _row(
        con,
        f"select usc_section_verdict, usc_section_attested_at_edition, count(*) from {L} "
        "where usc_title = 21 and usc_section = '134a' group by 1, 2",
    ) == ("exists", True, 110), "real until the 2002 repeal, and every citing row predates it"

    # 18 U.S.C. 3568: repealed effective 1987-11-01 and cited deliberately for
    # pre-1987 conduct. It reads absent because the oracle's window opens in
    # 1994, and the receipt carries the caveat that says so once rather than
    # repeating it down 14,142 rows.
    assert _row(
        con, f"select usc_section_verdict, count(*) from {L} where usc_title = 18 and usc_section = '3568' group by 1"
    ) == ("absent", 182)

    # Corrections: one survivor or nothing, the original kept, the rule named.
    # 3,814 -> 3,818 at rebuild #8 (f9d20973): the new rule
    # "space-lost-before-a-lettered-suffix" gains 4 rows on the EXISTING
    # table (78j-1, 78k-1, 78o-10 twice) -- count(*) where
    # usc_section_correction_evidence is not null and authority_source !=
    # 'box' is 0, so none of the four are continuation rows.
    # B1 155 -> 159 at rebuild #9 (9cab6f65, H2): +4, a genuine knock-on --
    # the section-fence correction system runs AFTER the box-run join and
    # title carry, over every usc row regardless of source, and 4 of H2's
    # 111 new rows (RIN 1018-AW15, editions 200810/200904/200910/201004,
    # ordinal 3, title 16, "742(a) et seq." carried from ordinal 2) parse to
    # the bare section 742 and are corrected to the lettered section 742a
    # like any other B1 match. count(*) where usc_section_correction_evidence
    # ='B1-et-seq-follows-a-section' and usc_title_carried_from_ordinal is
    # not null is exactly 4 on this artifact, and 0 for the same query
    # against H1's authority_join_rule and H4's corroboration_rule='one-
    # edit-on-a-scheme-label' markers -- no other rule or row moves.
    assert _rows(
        con,
        f"select usc_section_correction_evidence, count(*) from {L} "
        "where usc_section_correction_evidence is not null group by 1 order by 1",
    ) == [
        ("A4-subsection-rendered-as-a-lettered-section", 3_651),
        ("B1-et-seq-follows-a-section", 159),
        # Rebuild #15 (2026-09-01 wave), REF-061.
        ("B8-two-witness-lettered-section", 666),
        ("C3-paren-suffix-eaten", 200),
        ("act-section-under-a-usc-label", 8),
        ("space-lost-before-a-lettered-suffix", 4),
    ]
    # A4 3,659 -> 3,651 at rebuild #10 (084edf69): the 8 CEA rows ("7 USC
    # 8a(5)", RINs 3038-AB50/AD31) move to the new rule below -- Table III's
    # own credit says Act sec. 8a is 7 U.S.C. 12a, so A4's subsection reading
    # was a wrong real section, the review-2 class-H finding. The new rule
    # "act-section-under-a-usc-label" carries exactly those 8; the total is
    # unchanged.
    # 5,255 -> 3,814 at rebuild #6: the 1,441 B8 corrections were withdrawn
    # (53294b04) -- B8 is a candidate, named in the receipt, never the
    # identity -- after the review found one of them a wrong real section.
    # 3,814 -> 3,818 at rebuild #8: the same 4 rows as immediately above.
    # 3,818 -> 3,822 at rebuild #9: the same 4 H2 rows as the B1 move above.
    # 3,822 -> 3,822 at rebuild #10: A4 -8, act-section-under-a-usc-label +8.
    # Rebuild #14 (2026-08-31 wave, research/evidence/rebuild14-delta-2026-08-31.txt): 3,822 -> 4,022, the
    # 200 C3-paren-suffix-eaten promotions (bound to the row's own citation).
    assert _one(con, f"select count(*) from {L} where usc_section_corrected is not null") == 4_688  # Rebuild #15 (2026-09-01): +666, the B8 two-witness promotions (REF-061).
    assert _one(
        con,
        f"select count(*) from {L} where (usc_section_corrected is null) <> "
        "(usc_section_correction_evidence is null)",
    ) == 0, "every correction names its evidence"
    assert _one(
        con, f"select count(*) from {L} where lower(usc_section_corrected) = lower(usc_section)"
    ) == 0, "a correction that equals the original corrects nothing"
    assert _row(
        con,
        f"select usc_section_verdict, usc_section_corrected, count(*) from {L} "
        "where usc_title = 21 and usc_section = '371a' group by 1, 2",
    ) == ("absent", "371(a)", 1_551)
    # And the two the campaign asked to see refused: both readings are real, so
    # neither is published even though one of them is 388 rows.
    assert _row(
        con,
        f"select usc_section_verdict, usc_section_corrected, count(*) from {L} "
        "where usc_title = 5 and usc_section = '552' and authority_text ilike '%552(a)%' group by 1, 2",
    ) == ("exists", None, 765)
    assert _row(
        con,
        f"select usc_section_verdict, usc_section_corrected, count(*) from {L} "
        "where usc_title = 42 and usc_section = '2139' and authority_text ilike '%2139(a)%' group by 1, 2",
    ) == ("exists", None, 388)


@pytest.mark.slow
def test_the_corrected_key_split_over_the_built_table(con) -> None:
    """The key a consumer joins on, and the tags keying on the correction costs.

    ``usc_section_corrected`` is the Code's own spelling, where "371(a)" is a
    pinpoint into section 371 and "1395hh" is a lettered section, so it is a
    rendering and not a key: every one of the 5,255 corrections MOVES the
    identity off the section the citation names. spicysearch measured what that
    costs over 8,523 presidential bodies and 45,214 court opinions -- of the 91
    keys that depart under a corrected-then-base reading, the only four with any
    document exposure are correct citations, and they lose every tag
    (research/evidence/ledger-2026-08-22/verification-notes.md, "Exposure
    figures decide the corrected-key shape").

    So the consumer keys on the parsed ``usc_section`` and treats a B8 identity
    as a CANDIDATE to widen with, never as the key. B8 rests on the release
    point printing no lettered subsection on the bare section: high precision on
    the 1395 family the survey validated, and not a proof that 15 U.S.C. 18(a)
    is 18a rather than a pinpoint into §18. The rule is unchanged and its
    proposal is still published -- what changed is that the identity it names
    now has a column of its own, so a consumer can read the proposal without
    joining on it.

    Measured on the scratch build of commit 1118d687; awaits the rebuild.
    """

    _awaits_the_rebuild(con, "usc_section_corrected_section", _CORRECTED_KEY_SCRATCH_BUILD)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    split = (
        "usc_section_corrected_section, usc_section_corrected_pinpoint, usc_section_corrected, count(*)"
    )
    # A4 is the one rule of the three that names a pinpoint: "21 USC 371a" is
    # section 371, subsection (a).
    assert _row(
        con, f"select {split} from {L} where usc_title = 21 and usc_section = '371a' group by 1, 2, 3"
    ) == ("371", "(a)", "371(a)", 1_551)
    # B1 names a lettered SECTION, so there is no pinpoint to carry and the
    # split's second column is NULL rather than empty. B8 was candidate-only
    # since 53294b04 and the 82 "1395(hh)" rows carried no split -- until
    # rebuild #15 (2026-09-01, REF-061): the two-witness builder rule corrects
    # 72 of them to 1395hh, and the 10 left splitless are the rows whose own
    # held notes and edition history witness nothing.
    assert _rows(
        con,
        f"select {split} from {L} where usc_title = 42 and usc_section = '1395' "
        "and authority_text ilike '%1395(hh)%' group by 1, 2, 3 order by 1 nulls first",
    ) == [(None, None, None, 10), ("1395hh", None, "1395hh", 72)]
    assert _row(
        con,
        f"select {split} from {L} where usc_title = 42 and usc_section = '300' "
        "and usc_section_correction_evidence = 'B1-et-seq-follows-a-section' group by 1, 2, 3",
    ) == ("300f", None, "300f", 32)

    # The invariant that keeps the split from drifting from the Code's spelling:
    # identity || pinpoint IS usc_section_corrected, on every row of the table
    # and not only the corrected ones, and the three are NULL together.
    assert _one(
        con,
        f"select count(*) from {L} where coalesce(usc_section_corrected_section, '') || "
        "coalesce(usc_section_corrected_pinpoint, '') is distinct from coalesce(usc_section_corrected, '')",
    ) == 0
    assert _one(
        con,
        f"select count(*) from {L} where (usc_section_corrected_section is null) <> "
        "(usc_section_corrected is null)",
    ) == 0
    assert _one(
        con,
        f"select count(*) from {L} where usc_section_corrected_pinpoint is not null "
        "and usc_section_corrected_section is null",
    ) == 0, "a pinpoint into nothing"
    assert _one(
        con,
        f"select count(*) from {L} where usc_section_corrected_pinpoint is not null "
        "and usc_section_corrected_pinpoint not like '(%)'",
    ) == 0, "a pinpoint is parenthesised or it is not one"
    # Only A4 carries one, which is the shape of the three rules and not a rule
    # of its own: a lettered-section reading has nothing left to pinpoint.
    # space-lost-before-a-lettered-suffix joins B1 in naming a lettered
    # SECTION (78j-1 etc.), so its pinpoint count is 0 too -- rebuild #8
    # (f9d20973), +4 rows, all on the existing table (see the totals test).
    # B1 155 -> 159 at rebuild #9 (9cab6f65, H2): +4, the same title-carried
    # "742(a) et seq." rows the section-fence totals test attributes (RIN
    # 1018-AW15) -- a lettered SECTION reading again, so the pinpoint count
    # stays 0, not 4.
    assert _rows(
        con,
        f"select usc_section_correction_evidence, count(usc_section_corrected_pinpoint), count(*) from {L} "
        "where usc_section_corrected is not null group by 1 order by 1",
    ) == [
        ("A4-subsection-rendered-as-a-lettered-section", 3_651, 3_651),
        ("B1-et-seq-follows-a-section", 0, 159),
        # Rebuild #15 (2026-09-01 wave), REF-061: the two-witness builder rule.
        # A lettered-SECTION reading like B1's, so its pinpoint count is 0.
        ("B8-two-witness-lettered-section", 0, 666),
        ("C3-paren-suffix-eaten", 0, 200),
        ("act-section-under-a-usc-label", 5, 8),
        ("space-lost-before-a-lettered-suffix", 0, 4),
    ]
    # A4 3,659 -> 3,651 at rebuild #10 (084edf69), the 8 rows moving to
    # act-section-under-a-usc-label: five of the eight state "(5)" and carry
    # it as a pinpoint into 12a; the other three state the bare token, so a
    # SECOND rule now names pinpoints -- the sentence above ("Only A4") was
    # true until the review-2 fix and is qualified by this entry.

    # The keys a consumer keying on the correction would move: all 3,818 of
    # them (5,255 until B8 became a candidate at 53294b04 — its 1,441 would
    # have moved 15 U.S.C. 18 to 18a for a consumer, which is what the peer's
    # exposure figures measured and refused). The two censuses coincide TODAY
    # because no published rule leaves the identity alone -- a rule that only
    # added a pinpoint would separate them, and this pin is what would say so.
    # 3,814 -> 3,818 at rebuild #8: the 4 space-lost-before-a-lettered-suffix
    # rows above all move the identity too -- the space stopped the grammar
    # at the bare number ("15 USC 78 o-10" parses usc_section "78"), so the
    # closed-up correction "78o-10" is a different identity, not a pinpoint
    # on the same one.
    # 3,818 -> 3,822 at rebuild #9: the same 4 H2 title-carry rows as the B1
    # moves above -- "742" corrected to "742a" is a different identity too.
    moved = _rows(
        con,
        f"select usc_section_correction_evidence, count(*) from {L} where usc_section_corrected_section is not null "
        "and lower(usc_section_corrected_section) <> lower(usc_section) group by 1 order by 1",
    )
    assert moved == [
        ("A4-subsection-rendered-as-a-lettered-section", 3_651),
        ("B1-et-seq-follows-a-section", 159),
        # Rebuild #15 (2026-09-01 wave), REF-061: every B8 correction moves the
        # identity (bare NNN -> NNNx), so the two censuses still coincide.
        ("B8-two-witness-lettered-section", 666),
        ("C3-paren-suffix-eaten", 200),
        ("act-section-under-a-usc-label", 8),
        ("space-lost-before-a-lettered-suffix", 4),
    ]
    # 3,659 -> 3,651 + 8 at rebuild #10 (084edf69): "8a" -> "12a" moves the
    # identity on all eight, so the moved census and the evidence census stay
    # equal and the 3,822 total below is unchanged.
    # Rebuild #14 (2026-08-31 wave): 4,022, the 200 C3 promotions all move the identity (78 -> 78b).
    assert sum(rows for _, rows in moved) == 4_688  # Rebuild #15 (2026-09-01): +666, the B8 two-witness promotions (REF-061).
    assert _one(
        con,
        f"select count(*) from {L} where usc_section_corrected is not null "
        "and lower(usc_section_corrected_section) = lower(usc_section)",
    ) == 0, "no published correction leaves the identity where it was"

    # And the receipt says so, recomputed from the column rather than declared.
    import json

    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    assert declared["uscSectionCorrectedIdentityMovedRowsByRule"] == {
        rule: _one(
            con,
            f"select count(*) from {L} where usc_section_correction_evidence = '{rule}' "
            "and lower(usc_section_corrected_section) <> lower(usc_section)",
        )
        for rule in declared["uscSectionCorrectedIdentityMovedRowsByRule"]
    }
    assert declared["uscSectionCorrectedIdentityMovedRowsByRule"]["lost-hyphen-with-one-typed-as-a-letter"] == 0, (
        "declared at zero: the rule closes 15 U.S.C. 80bll and 7 U.S.C. 6bi, and this corpus files neither"
    )

    # The four keys the consumer measured, from this end. Every row that parses
    # to one of them once carried a B8 proposal moving it one letter along --
    # and the departing keys are CORRECT citations (27 court opinions print
    # "15 U.S.C. § 18"). Since 53294b04 B8 alone is a candidate, so the
    # identity a consumer joins on stays the parsed one by construction. At
    # rebuild #15 (2026-09-01, REF-061) the TWO-WITNESS builder rule corrects
    # the subset a second witness corroborates: all 19 rows of 15:18 -> 18a
    # (the FTC specimen whose held note reads "15 U.S.C. 18a(d); 15 U.S.C.
    # 18b." and never bare 18 -- the exact case that demoted one-witness B8),
    # and 28 of 39 rows of 12:1715 (25 -> 1715b, 3 -> 1715y); 25:161 and
    # 47:399 stay uncorrected (witnessless or counter-evidenced), their
    # neighbours still named only in the receipt's candidate census. The
    # consumer's choice is unchanged: usc_section keeps the filed identity,
    # and keying on usc_section_corrected_section is opt-in per the schema.
    cited = "(usc_title, usc_section) in ((15, '18'), (12, '1715'), (47, '399'), (25, '161'))"
    assert _rows(
        con,
        f"select usc_title, usc_section, usc_section_corrected_section, usc_section_corrected_pinpoint, "
        f"usc_section_correction_evidence, count(*) from {L} where {cited} group by 1, 2, 3, 4, 5 order by 1, 2, 3",
    ) == [
        (12, "1715", "1715b", None, "B8-two-witness-lettered-section", 25),
        (12, "1715", "1715y", None, "B8-two-witness-lettered-section", 3),
        (12, "1715", None, None, None, 11),
        (15, "18", "18a", None, "B8-two-witness-lettered-section", 19),
        (25, "161", None, None, None, 12),
        (47, "399", None, None, None, 24),
    ]
    assert _rows(
        con,
        f"select usc_title, usc_section, count(*), count(usc_section_corrected_section) from {L} "
        f"where {cited} group by 1, 2 order by 1, 2",
    ) == [(12, "1715", 39, 28), (15, "18", 19, 19), (25, "161", 12, 0), (47, "399", 24, 0)]
    # Every one of them is a real section the oracle prints: the candidate sits
    # beside an "exists" verdict, which is exactly why a move would be expensive
    # and why none is made.
    assert _rows(
        con, f"select distinct usc_section_verdict from {L} where {cited}"
    ) == [("exists",)]


@pytest.mark.slow
def test_the_receipt_census_covers_the_section_fence(con) -> None:
    """A declared count that nothing recomputes is a claim, not a pin.

    Every key here is recomputed from the table it describes -- and the refusal
    census, which NO column carries, is recomputed by asking the oracle again
    over the artifact's own rows. Measured on the scratch build of commit
    e9aa1eef; awaits the rebuild.
    """

    import json

    from refspec.registry.unified_agenda_parquet import _usc_section_oracle

    _awaits_the_rebuild(con, "usc_section_verdict")
    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    for key, measure in (
        ("uscSectionVerdictRows", "count(*)"),
        ("uscSectionVerdictTexts", "count(distinct authority_text)"),
        ("uscSectionVerdictPairs", "count(distinct (usc_title, usc_section, usc_appendix))"),
        ("uscSectionVerdictRins", "count(distinct rin)"),
    ):
        observed = dict(
            _rows(
                con,
                f"select usc_section_verdict, {measure} from {L} "
                "where usc_section_verdict is not null and authority_type = 'usc' group by 1",
            )
        )
        assert declared[key] == observed, key
    assert declared["uscSectionUnknownRowsByReason"] == {
        reason: _one(
            con,
            f"select count(*) from {L} where usc_section_verdict_reason = '{reason}' "
            "and authority_type = 'usc'",
        )
        for reason in declared["uscSectionUnknownRowsByReason"]
    }
    assert declared["uscSectionExistsNotAtEditionRows"] == _one(
        con,
        f"select count(*) from {L} where usc_section_verdict = 'exists' "
        "and usc_section_attested_at_edition = false and authority_type = 'usc'",
    )
    assert declared["uscSectionTitleImpossibleRows"] == _one(
        con,
        f"select count(*) from {L} where usc_title_is_possible = false and authority_type = 'usc' "
        "and usc_section is not null",
    )
    assert declared["uscSectionNotStatedRows"] == _one(
        con, f"select count(*) from {L} where authority_type = 'usc' and usc_section is null"
    )
    assert declared["uscSectionCorrectedRowsByRule"] == {
        rule: _one(con, f"select count(*) from {L} where usc_section_correction_evidence = '{rule}'")
        for rule in declared["uscSectionCorrectedRowsByRule"]
    }
    for key, column in (
        ("uscSectionMagnitudeImplausibleRows", "usc_section_magnitude_is_plausible"),
        ("authorityImplausiblePartRows", "cfr_part_is_plausible"),
        ("statVolumeMismatchesPublicLawRows", "statute_volume_matches_public_law"),
    ):
        assert declared[key] == _one(con, f"select count(*) from {L} where {column} = false"), key

    # The refusals no column carries: asked of the oracle again, over the same
    # (title, section, authority_text) triples the builder memoised on.
    oracle = _usc_section_oracle()
    refused: dict[str, int] = {}
    for title, section, text, rows in _rows(
        con,
        f"select usc_title, usc_section, authority_text, count(*) from {L} "
        "where usc_section_verdict is not null and authority_type = 'usc' group by 1, 2, 3",
    ):
        candidates = oracle.correction_candidates(title, section, text)
        if len(candidates) > 1:
            key = "+".join(sorted({candidate.rule.split("-")[0] for candidate in candidates}))
            refused[key] = refused.get(key, 0) + rows
    assert declared["uscSectionCorrectionRefusalRowsBySurvivors"] == refused
    # "parse" alone is not a refusal of anything: two readings survived and
    # both are the parse as filed, at two pinpoint depths of the same citation,
    # so there is nothing to correct. It is counted because it is the fourth
    # multi-survivor shape and dropping it would hide a population; the three
    # keys naming a proposal are the refusals proper. Every cell here is the
    # oracle report's own, reproduced from the other end.
    # B8+parse 12,589 -> 12,594 at rebuild #6: "42 U.S.C. 300(c)-22 (note)"
    # (5 rows) reached a B8 candidate once the hyphenated tail was read
    # (ebcd8b1c) where the truncated generator had none, and is refused for
    # two survivors like its kin.
    # A4+parse 26,207 -> 26,256 and parse 6,498 -> 6,507 at rebuild #8
    # (94ddfb03): +49 and +9, both entirely the new usc-type continuation
    # rows -- restricting this same loop to authority_source != 'box' gives
    # exactly {"A4+parse": 49, "parse": 9} and restricting to 'box' reproduces
    # the prior pin unchanged; B8+parse and A4+B8+parse gain nothing.
    #
    # Rebuild #9 (d7d96b95 H4, 6e9a15ae H1, 9cab6f65 H2, 66d96462 H3): all
    # three moving keys grow, A4+B8+parse does not. This same refusal loop,
    # run again restricted to each unit's row marker (H1: authority_type=
    # 'usc' and parse_status in ('partial','ok'); H2: usc_title_carried_
    # from_ordinal is not null; H4: corroboration_rule='one-edit-on-a-
    # scheme-label'), against the rebuild-8 baseline for H1 and against zero
    # for H2/H4 (new columns/values), gives:
    #   A4+parse  26,256 -> 26,297  +41 = H1 31 + H2 4 + H4 6
    #   B8+parse  12,594 -> 12,599   +5 = H1  0 + H2 5 + H4 0
    #   parse      6,507 ->  6,512   +5 = H1  0 + H2 4 + H4 1
    # H3 contributes nothing to any key: an act_relative row is not in this
    # loop's population. Until 2026-08-24 that was true because such a row
    # carried no usc_section_verdict at all; since the act-derived sections are
    # judged it is true because the loop asks only for authority_type 'usc' --
    # which is the population uscSectionCorrectionRefusalRowsBySurvivors has
    # always described, and the only one a correction can speak about, since a
    # correction repairs what a filer TYPED under a U.S.C. label.
    assert refused == {"A4+parse": 26_299, "B8+parse": 12_599, "A4+B8+parse": 11, "parse": 6_512}


#: The act-derived section fence's counts were measured on a scratch build
#: whose builder module hashes to this, `--output-root` under a temporary
#: directory and the same pinned editions, act index, source credits and
#: oracles -- the same recipe and the same reason as
#: ``_ACT_RESOLUTION_SCRATCH_BUILDER`` above. That build's value diff against
#: the faithful rebuild-11 baseline moved 5,657 rows in exactly two columns
#: (usc_section_verdict, usc_section_attested_at_edition) and nothing else in
#: any of the four tables.
_ACT_SECTION_SCRATCH_BUILDER = "sha256:8c1a4b37"


def _awaits_the_act_section_fence(con) -> None:
    """Say WHY the pins below are red, the way ``_awaits_the_rebuild`` does.

    No new COLUMN arrives with this fence -- it writes the three the U.S.C.
    rows already carry -- so the "does the artifact have this column" question
    cannot see it. What can: whether any act_relative row carries a verdict at
    all. Rebuild #12 landed the fence, so this is now a guard against a stale
    artifact rather than a standing explanation of a red pin.
    """

    judged = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where authority_type = 'act_relative' and usc_section_verdict is not null",
    )
    assert judged, (
        "the artifact under output/ predates the act-derived section fence: the counts below were "
        f"first measured on the scratch build of {_ACT_SECTION_SCRATCH_BUILDER} and are now pinned "
        "to rebuild #12; rebuild to restore them"
    )


@pytest.mark.slow
def test_an_act_derived_section_is_judged_like_any_other(tmp_path) -> None:
    """The fence itself, over hand-built rows, with no artifact in the way.

    Three specimens and one refusal, each the filer's own text. This is the
    test that is green the moment the code lands -- the artifact pins below
    await rebuild #12 -- so a regression in the pass cannot hide behind a
    stale build for a cycle.
    """

    from pathlib import Path as _Path

    from refspec.registry.act_resolution import ActIndex
    from refspec.registry.unified_agenda_parquet import (
        _judge_act_derived_sections,
        _resolve_act_citations,
        _usc_section_oracle,
        _usc_source_credits,
    )

    def act_row(rin, publication_id, text, act_key, section, ordinal=0, status="resolved"):
        row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
        row.update(
            rin=rin, publication_id=publication_id, ordinal=ordinal, authority_text=text,
            authority_type="act_relative", parse_status=status, usc_appendix=False,
            usc_note=False, act_key=act_key, act_section=section,
        )
        return row

    rows = [
        # EXISTS, ATTESTED. RIN 3038-AD81's Fall 2012 filing, and the specimen
        # the numbering fence names from the other end: the Commodity Exchange
        # Act's own section 8a is 7 U.S.C. 12a, which is why a filer writing
        # "8a" under a "7 USC" label is a misread there and a resolution here.
        act_row("3038-AD81", "201210", "sec 8a(5) of the Commodity Exchange Act", "commodity exchange act", "8a"),
        # EXISTS, NOT ATTESTED -- the era mismatch proper. ARRA 2009 section
        # 14005 is 20 U.S.C. 10005, and the first annual archive that prints
        # 20 U.S.C. 10005 is 2014: RIN 1810-AB17 cited the act section in the
        # Fall 2013 edition, a year before the Code had that home for it.
        act_row(
            "1810-AB17", "201310",
            "Sec 14005 and 14006, Division A, of the American Recovery and Reinvestment Act of 2009",
            "american recovery and reinvestment act of 2009", "14005", status="corroborated",
        ),
        # EXISTS, ATTESTED -- and this row used to read NOT attested for the
        # oracle's own hole rather than for anything about the law. 33 U.S.C.
        # 1311 is printed in every annual edition INCLUDING 2012; the 2012
        # volume is named 2012USC33.htm and generation 1's case-sensitive
        # filename matcher never opened it, so title 33 had no 2012 coverage at
        # all. Generation 2 (research/evidence/usc-section-oracle-2026-08-24)
        # reads it, and this is the act-derived path's guard on that: 16 rows
        # across RINs 2040-AE69 and 2040-AE95 move False -> True with it.
        act_row("2040-AE69", "201210", "CWA 301", "clean water act", "301", status="corroborated"),
        # NOTHING TO JUDGE: the act resolves and the section does not, so no
        # Code address exists to ask about and act_resolution_reason says why.
        act_row("2040-AE69", "201210", "CWA 999", "clean water act", "999", ordinal=1),
    ]
    index = ActIndex.from_artifact(_Path(__file__).resolve().parents[1] / "output/usc-act-index-2026-08-22")
    _resolve_act_citations(rows, index, _usc_source_credits())
    census = _judge_act_derived_sections(rows, _usc_section_oracle())

    judged = [
        (r["usc_title"], r["usc_section"], r["usc_section_verdict"], r["usc_section_verdict_reason"],
         r["usc_section_attested_at_edition"])
        for r in rows
    ]
    assert judged == [
        (7, "12a", "exists", None, True),
        (20, "10005", "exists", None, False),
        (33, "1311", "exists", None, True),
        (None, None, None, None, None),
    ]
    assert rows[3]["act_resolution_reason"] == "act_section_not_classified"
    # The identity columns are the resolver's and the filer's, untouched: a
    # verdict is a witness beside them and never a rewrite. No correction is
    # published on any of these rows -- a correction repairs what a filer
    # TYPED under a U.S.C. label, and none of this was typed that way.
    assert [(r["act_key"], r["act_section"]) for r in rows] == [
        ("commodity exchange act", "8a"),
        ("american recovery and reinvestment act of 2009", "14005"),
        ("clean water act", "301"),
        ("clean water act", "999"),
    ]
    assert {r["usc_section_corrected"] for r in rows} == {None}
    assert {r["usc_disposition_verdict"] for r in rows} == {None}
    assert census.rows_by_verdict == {"exists": 3, "absent": 0, "unknown": 0}
    # One, not two: the CWA row above stopped being an era mismatch when the
    # oracle's annual extractor was made case-insensitive, leaving only the
    # genuine one (ARRA 14005 at edition 2013, first printed at 20 U.S.C.
    # 10005 in the 2014 archive).
    assert census.exists_not_at_edition_rows == 1
    assert census.rows_by_status_and_verdict == {
        "corroborated": {"exists": 2, "absent": 0, "unknown": 0},
        "resolved": {"exists": 1, "absent": 0, "unknown": 0},
    }
    # And a row the resolver never answered is not judged, whatever else it
    # carries: the gate is act_resolution_evidence, the resolver's own witness.
    unresolved = act_row("2040-AE69", "201210", "CWA 999", "clean water act", "999")
    unresolved.update(usc_title=33, usc_section="1311")
    assert _judge_act_derived_sections([unresolved], _usc_section_oracle()).rows_by_verdict["exists"] == 0
    assert unresolved["usc_section_verdict"] is None


@pytest.mark.slow
def test_the_act_derived_sections_are_judged_at_their_edition(con) -> None:
    """6,768 act-resolved sections, dated at last -- and 3 the edition never printed.

    Until 2026-08-24 the fence judged authority_type='usc' rows only, so the
    existence of a section OLRC's Table III filled rested on that
    classification being CURRENT and nothing said whether the edition that
    filed the citation had printed it.

    19 -> 3 at the oracle generation-2 switch, and the 16 that left were never
    about an edition: they are the CWA sections of RINs 2040-AE69 and 2040-AE95
    at edition 201210, unattested only because generation 1's annual extractor
    never opened 2012USC33.htm. Nothing else here moves -- the verdict split,
    the 6,768, the evidence/status table and the two other specimens are all
    unchanged, because recovering those volumes changed no existence union.
    EXPECTED RECEIPT DELTA: true of a build written by the generation-2 oracle,
    not of the rebuild-#12 artifact these values were first measured against.

    These counts moved once before, on rebuild #12, and in one cell only.
    `table3-classification`/`corroborated` rose 2,148 -> 3,259 (+1,111) and
    nothing else did: `resolved` is unchanged at 3,496 and 13, no row changed
    verdict, and the three specimens below are identical. More corroboration
    of the same resolutions, not new ones -- the slash unit reads a second
    authority behind a slash and corroborates 1,428 rows that the rebuild-#11
    baseline never saw.

    Every value here is the "after" column of the unit authors' own receipt
    diff, `research/evidence/investigations-2026-08-24/units-grammar/
    rebuild12-delta.txt`, which records this build against the rebuild-#11
    faithful baseline. That file is the pin of record: re-measure against it,
    not against a fresh reading of whatever is under output/.
    """

    _awaits_the_act_section_fence(con)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    A = f"{L} where authority_type = 'act_relative' and act_resolution_evidence is not null"
    # Rows / texts / pairs / RINs / act sections, the four the U.S.C. census
    # keeps plus the unit OLRC actually answered. Every one of the 6,768 reads
    # "exists": Table III's classifications land on sections the oracle prints,
    # all 358 of them, and the 372 act sections behind them are exactly
    # actRelativeResolvedPairs -- resolved and judged are the same population.
    assert _rows(
        con,
        f"select usc_section_verdict, count(*), count(distinct authority_text), "
        f"count(distinct (usc_title, usc_section, usc_appendix)), count(distinct rin), "
        f"count(distinct (act_key, act_section)) from {A} group by 1",
    ) == [("exists", 6_768, 1_233, 358, 1_051, 372)]
    # No absent and no unknown. An absent here would be an honest refusal of
    # the mapping's currency -- Table III naming a Code section the oracle does
    # not print -- and there is not one; an unknown would be a coverage hole,
    # and no act-derived section reaches one, so no recodification table is
    # asked either.
    assert _one(con, f"select count(*) from {A} and usc_section_verdict_reason is not null") == 0
    assert _one(con, f"select count(*) from {A} and usc_disposition_verdict is not null") == 0
    # The census closes: every act_relative row with a section and evidence is
    # judged, and no such row is left out.
    assert _one(con, f"select count(*) from {A} and usc_section is not null") == 6_768
    assert _one(con, f"select count(*) from {A} and usc_section is not null and usc_section_verdict is null") == 0
    # The split the consumer's named reading is written in terms of.
    assert _rows(
        con, f"select act_resolution_evidence, parse_status, count(*) from {A} group by 1, 2 order by 1, 2"
    ) == [
        ("source-credit", "resolved", 13),
        ("table3-classification", "corroborated", 3_259),
        ("table3-classification", "resolved", 3_496),
    ]

    # THE THREE SPECIMENS, in the filers' own words.
    def specimen(rin, publication, text):
        return _row(
            con,
            f"select act_key, act_section, usc_title, usc_section, usc_section_verdict, "
            f"usc_section_verdict_reason, usc_section_attested_at_edition from {A} "
            f"and rin = '{rin}' and publication_id = '{publication}' and authority_text = '{text}'",
        )

    # Exists and attested: CFTC's Fall 2012 filing, the Commodity Exchange
    # Act's own section 8a, which is 7 U.S.C. 12a.
    assert specimen("3038-AD81", "201210", "sec 8a(5) of the Commodity Exchange Act") == (
        "commodity exchange act", "8a", 7, "12a", "exists", None, True
    )
    # Exists and NOT attested, era mismatch: ARRA 2009 section 14005 is 20
    # U.S.C. 10005, first printed in the 2014 annual archive, and Education
    # cited the act section in the Fall 2013 edition.
    assert specimen(
        "1810-AB17", "201310",
        "Sec 14005 and 14006, Division A, of the American Recovery and Reinvestment Act of 2009",
    ) == ("american recovery and reinvestment act of 2009", "14005", 20, "10005", "exists", None, False)
    # Exists and ATTESTED, and it used to be the oracle's own hole: the annual
    # archive's 2012 title-33 volume is named 2012USC33.htm and generation 1's
    # case-sensitive matcher never opened it, so every title-33 section read
    # unattested at that edition -- 133 U.S.C.-typed rows did too. Generation 2
    # reads it. EXPECTED RECEIPT DELTA (True was False before the switch).
    assert specimen("2040-AE69", "201210", "CWA 301") == (
        "clean water act", "301", 33, "1311", "exists", None, True
    )

    # 3 rows in all, over 3 distinct (act, act section, title, section), every
    # one the era mismatch proper. It was 19 over 14 while the 2012 volumes of
    # titles 33 and 35-41 went unread: 16 of those rows were the extractor
    # hole, and they left with it. EXPECTED RECEIPT DELTA.
    assert _one(con, f"select count(*) from {A} and usc_section_attested_at_edition = false") == 3
    assert _rows(
        con,
        f"select usc_title, count(*) from {A} and usc_section_attested_at_edition = false group by 1 order by 1",
    ) == [(20, 1), (42, 2)]
    # Social Security Act sections 605 and 606 in one Fall 2003 filing: 42
    # U.S.C. 805 is printed 1994-2002 and again 2021-2024, and 806 only from
    # 2022. Neither is a misread of the citation -- the act section is what the
    # filer named, and the Code home it has today is not the home it had then.
    assert _rows(
        con,
        f"select act_section, usc_section, usc_section_verdict, usc_section_attested_at_edition from {A} "
        "and rin = '0938-AK71' and publication_id = '200310' and usc_title = 42 "
        "and usc_section in ('805', '806') order by 1",
    ) == [("605", "805", "exists", False), ("606", "806", "exists", False)]


@pytest.mark.slow
def test_the_receipt_census_covers_the_act_section_fence(con) -> None:
    """Every act-section count in the receipt, recomputed from the table.

    The same discipline as the U.S.C. census beside it: a declared count that
    nothing recomputes is a claim. Measured on the scratch build of builder
    sha256:8c1a4b37; awaits the rebuild.
    """

    import json

    _awaits_the_act_section_fence(con)
    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    A = f"{L} where authority_type = 'act_relative' and act_resolution_evidence is not null"
    for key, measure in (
        ("actSectionVerdictRows", "count(*)"),
        ("actSectionVerdictTexts", "count(distinct authority_text)"),
        ("actSectionVerdictPairs", "count(distinct (usc_title, usc_section, usc_appendix))"),
        ("actSectionVerdictRins", "count(distinct rin)"),
        ("actSectionVerdictActSections", "count(distinct (act_key, act_section))"),
    ):
        observed = dict(
            _rows(con, f"select usc_section_verdict, {measure} from {A} and usc_section_verdict is not null group by 1")
        )
        # Declared at the full vocabulary, so a verdict that starts firing
        # breaks a pin instead of appearing in a total; the table can only
        # report the ones it has.
        assert {verdict: count for verdict, count in declared[key].items() if count} == observed, key
    assert declared["actSectionUnknownRowsByReason"] == {
        reason: _one(con, f"select count(*) from {A} and usc_section_verdict_reason = '{reason}'")
        for reason in declared["actSectionUnknownRowsByReason"]
    }
    assert declared["actSectionExistsNotAtEditionRows"] == _one(
        con,
        f"select count(*) from {A} and usc_section_verdict = 'exists' and usc_section_attested_at_edition = false",
    )
    assert declared["actSectionTitleImpossibleRows"] == 0
    for key, column in (
        ("actSectionVerdictRowsByEvidence", "act_resolution_evidence"),
        ("actSectionVerdictRowsByStatus", "parse_status"),
    ):
        observed = {}
        for group, verdict, rows in _rows(
            con, f"select {column}, usc_section_verdict, count(*) from {A} and usc_section_verdict is not null "
                 "group by 1, 2"
        ):
            observed.setdefault(group, {})[verdict] = rows
        assert {
            group: {verdict: count for verdict, count in counts.items() if count}
            for group, counts in declared[key].items()
            if any(counts.values())
        } == observed, key
    # The unit closes against the resolver's own census: the pairs OLRC
    # answered are the act sections this fence judged.
    assert declared["actRelativeResolvedPairs"] == declared["actSectionVerdictActSections"]["exists"]


@pytest.mark.slow
def test_the_three_carried_verdicts_over_the_built_table(con) -> None:
    """What each of the three fences flags, and the two that flag nothing.

    Measured on the scratch build of commit e9aa1eef; awaits the rebuild.
    """

    _awaits_the_rebuild(con, "usc_section_magnitude_is_plausible")
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    # The corpus's own magnitude ceiling: 10 (title, section) pairs / 44 rows,
    # the same population test_citation_grammar pins over the same corpus.
    assert _one(con, f"select count(*) from {L} where usc_section_magnitude_is_plausible = false") == 44
    assert _rows(
        con,
        f"select usc_title, usc_section, count(*) from {L} where usc_section_magnitude_is_plausible = false "
        "group by 1, 2 order by 3 desc, 1, 2",
    )[:2] == [(33, "70034", 9), (33, "70116", 9)]
    # Every one sits in a title usc_title_is_possible calls real: the asymmetry
    # the fence exists to close.
    assert _one(
        con,
        f"select count(*) from {L} where usc_section_magnitude_is_plausible = false "
        "and usc_title_is_possible is not true",
    ) == 0

    # The CFR part verdict fires on NOTHING in this column, and that is the
    # finding: the sibling reference table flags 7 rows, and no authority value
    # carries a part longer than five digits. The longest is "49 CFR 30166" (30
    # rows) -- plausible on a digit-count test and still a U.S.C. section
    # wearing a CFR label, which is exactly what this verdict does not claim to
    # settle. A class measuring zero is the only thing that can say so if it
    # returns.
    assert _one(con, f"select count(*) from {L} where cfr_part_is_plausible = false") == 0
    # 6,566 -> 6,591 at rebuild #8 (94ddfb03): +25, exactly the new
    # continuation rows typed cfr -- count(*) where authority_type = 'cfr'
    # and authority_source != 'box' is 25 (the column is populated for every
    # cfr-type row, and the 25 new ones are all still plausible, so the
    # false count above stays 0).
    assert _one(con, f"select count(*) from {L} where cfr_part_is_plausible is not null") == 6_591
    assert _one(
        con, "select count(*) from '{d}/unified_agenda_cfr_references.parquet' where cfr_part_is_plausible = false"
    ) == 7
    assert _row(
        con,
        f"select cfr_part, count(*) from {L} where cfr_part is not null group by 1 order by length(cfr_part) desc, 2 "
        "desc limit 1",
    ) == ("30166", 30)

    # The Statutes relation: 14 distinct values / 46 rows, every one a real
    # volume the series bound calls fine. The 14 values occupy 100 rows in
    # all -- the other 54 are the Public Law citations of the same strings,
    # which carry no Statutes volume to judge.
    #
    # 14/46/14 -> 18/66/15 at rebuild #8 (94ddfb03): +4 distinct texts, +20
    # rows, +1 RIN, exactly the 20 new statute_at_large continuation rows --
    # count(*) where statute_volume_matches_public_law = false and
    # authority_source != 'box' is 20, and restricting to 'box' reproduces
    # the prior (14, 46, 14) unchanged. The four new texts are an
    # ERISA/HIPAA passage (Secs. 107, 209, 505, 701-703 ... 52 FR 13139) none
    # of which appears in any box row (0 box occurrences each).
    assert _row(
        con,
        f"select count(distinct authority_text), count(*), count(distinct rin) from {L} "
        "where statute_volume_matches_public_law = false",
    ) == (18, 66, 15)
    # 100 -> 324: +224, the four new texts' OWN total occurrence count across
    # the whole table (22 + 24 + 154 + 24 = 224, each with 0 box
    # occurrences) -- a single continuation string reread across many
    # editions of the same recurring rule explodes into many rows sharing
    # one authority_text (rowSemantics: one row per parsed citation).
    assert _one(
        con,
        f"select count(*) from {L} where authority_text in "
        f"(select distinct authority_text from {L} where statute_volume_matches_public_law = false)",
    ) == 324
    assert _rows(
        con,
        f"select authority_text, statute_volume, count(*) from {L} "
        "where statute_volume_matches_public_law = false group by 1, 2 order by 3 desc, 1 limit 2",
    ) == [
        (
            (
                "Secs. 107, 209, 505, 701-703, 711, 712 731-734 of ERISA (29 U.S.C. 1027, 1059, 1135, "
                "1171-1173, 1181 1182, 1191-1194), as amended by HIPAA (Pub. L. 104-191, 101 Stat. 1936) "
                "and NMHPA (Pub. L. 104-204) and Secretary of Labor's Order No. 1-87, 52 FR 13139, "
                "April 21, 1987."
            ),
            101,
            14,
        ),
        ("316, 332, 403, 615a–1, and 615c of Pub. L. 73–416, 4 Stat. 1064, as amended", 4, 9),
    ]
    # A verdict, never a correction: 3,543 rows state a volume the Public Law
    # beside them confirms, and 4,064 state one with no adjacent law to ask.
    # 3,405 / 4,202 before `1480dcd2` gave the lettered-page reader the same
    # verdict as the integer one: 138 rows were judged by which reader happened
    # to match them rather than by what the citation said.
    assert _one(con, f"select count(*) from {L} where statute_volume_matches_public_law = true") == 3_543
    # 4,064 -> 4,073 at rebuild #9: +9, statute_at_large rows with a volume
    # but no adjacent Public Law to check it against -- H1's 6 new
    # statute_at_large/partial rows (count(*) where authority_type=
    # 'statute_at_large' and parse_status='partial' and this predicate is
    # 2,356 on the rebuild-8 baseline, 2,362 here, +6) and H4's 3 new
    # statute_at_large/corroborated rows (corroboration_rule='one-edit-on-a-
    # scheme-label' and this predicate: 0 -> 3). 6+3=9; H2 mints no
    # statute_at_large row and H3 mints no row of any authority_type.
    assert _one(
        con,
        f"select count(*) from {L} where statute_volume is not null and statute_volume_matches_public_law is null",
    ) == 4_073


@pytest.mark.slow
def test_an_expanded_span_says_so_and_is_never_ok(con) -> None:
    """GPO abbreviates an inclusive span by dropping repeated leading digits, so
    "2671-80" means §§2671–2680, and the grammar now expands it. Six of the
    66 expansions are ranges that are mostly not law ("16 USC 4601-31" is
    460l-31: 8 of 31 members real), and two that pass both endpoints are
    sparse inside. A consumer expanding ranges must be able to tell an
    expanded span from a stated one, so the rule is a column and an expanded
    span is never typed ok (review 2026-08-23, finding 7). Measured on the
    rebuilt artifact, receipt sha256:687acc4f…"""
    from refspec.registry.citation_grammar import USC_SPAN_ABBREVIATED, USC_SPAN_STATED

    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    rules = dict(_rows(con, f"select usc_section_span_rule, count(*) from {L} "
                            "where usc_section_span_rule is not null group by 1"))
    # 49,953 -> 49,993 at rebuild #8 (94ddfb03): +40, new usc-type
    # continuation rows that state a span outright -- count(*) where
    # usc_section_span_rule = 'stated' and authority_source != 'box' is 40;
    # USC_SPAN_ABBREVIATED is untouched (0 new abbreviated spans).
    # 49,993 -> 50,033 at rebuild #9: +40 again, this time split three ways
    # -- H1 (usc/partial+ok) 49,993 -> 50,022 on the rebuild-8 baseline
    # (+29), H2 (usc_title_carried_from_ordinal is not null) 10, H4
    # (corroboration_rule='one-edit-on-a-scheme-label') 1; 29+10+1=40.
    # USC_SPAN_ABBREVIATED and its distinct-pair/never-ok checks below are
    # both unchanged (264 rows, 66 pairs, 0 ok, on both builds).
    assert rules == {USC_SPAN_STATED: 51_814, USC_SPAN_ABBREVIATED: 299}
    assert _one(con, f"select count(distinct (usc_title, usc_section, usc_section_end)) from {L} "
                     f"where usc_section_span_rule = '{USC_SPAN_ABBREVIATED}'") == 67
    assert _one(con, f"select count(*) from {L} where usc_section_span_rule = '{USC_SPAN_ABBREVIATED}' "
                     "and parse_status = 'ok'") == 0, "an expanded span is partial, never ok"
    # The rule is set exactly where an end exists: no end without a rule, no
    # rule without an end.
    assert _one(con, f"select count(*) from {L} "
                     "where (usc_section_end is null) != (usc_section_span_rule is null)") == 0
    import json
    receipt = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["contract"]["declaredClassifications"]["uscSectionAbbreviatedSpanRows"] == 299


def _resolved_rows(rows):
    """Run the build's act-resolution pass over hand-built rows, pins verified."""

    from pathlib import Path as _Path

    from refspec.registry.act_resolution import ActIndex
    from refspec.registry.unified_agenda_parquet import _resolve_act_citations, _usc_source_credits

    index = ActIndex.from_artifact(_Path(__file__).resolve().parents[1] / "output/usc-act-index-2026-08-22")
    return _resolve_act_citations(rows, index, _usc_source_credits())


def _act_row(**overrides):
    """One act-relative row with every schema column, the way the builder emits it."""

    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update({"authority_type": "act_relative", "parse_status": "failed"})
    row.update(overrides)
    return row


@pytest.mark.slow
def test_the_builder_resolves_the_specimens_the_reviewer_resolved_by_hand() -> None:
    """Review B's ten rows, answered by the code that now runs at build time.

    The reviewer read the publisher's own pages -- OLRC's Popular Name Tool,
    the Table III pages, the Code -- and resolved seven of ten to a section
    without running any of this. Every one of those the pinned index can reach
    is pinned here as a verdict, together with the three it should REFUSE and
    the reason each refusal names, because a resolver that only ever answers is
    not a resolver.

    Read against ``research/evidence/sample-review-2026-08-23/review.md``
    section B. The three the review resolves that this does not are named in
    the refusals below: the Amendments row (the filer named the amending act
    and cited the base act's section), the Steel Trade row (Table III files
    section 4 under a range key and the target is an eliminated note) and the
    General Mining row (a pre-1926 act whose classification stops at the
    Revised Statutes).
    """

    rows = [
        _act_row(act_key="rehabilitation act of 1973", act_section="504"),
        _act_row(act_key="social security act", act_section="1871"),
        _act_row(act_key="clean air act", act_section="112"),
        # OLRC lists "ERISA" only as a keyless cross-reference to a name that
        # is not itself an entry; the chain plus the supplied year reaches it.
        _act_row(act_key="erisa", act_section="505"),
        _act_row(act_key="social security act", act_section="1923"),
        _act_row(act_key="clean air act amendments of 1990", act_section="112"),
        _act_row(act_key="steel trade liberalization program implementation act", act_section="4"),
        _act_row(act_key="general mining act of 1872", act_section=None),
        _act_row(act_key="nuclear waste policy act of 1982", act_section=None),
        # The calendar refused the key the grammar proposed, so there is no act
        # to look up -- and the row is still act-relative.
        _act_row(act_key=None, act_section=None, stated_act_name="The Emergency Supplemental Appropriations Act"),
        # Not act-relative: the pass must not touch it.
        _act_row(authority_type="usc", parse_status="ok", usc_title=42, usc_section="7401"),
    ]
    census = _resolved_rows(rows)

    def verdict(row):
        return (
            row["parse_status"],
            row["usc_title"],
            row["usc_section"],
            row["act_resolution_evidence"],
            row["act_resolution_reason"],
        )

    T = "table3-classification"
    assert verdict(rows[0]) == ("resolved", 29, "794", T, None)
    assert verdict(rows[1]) == ("resolved", 42, "1395hh", T, None)
    assert verdict(rows[2]) == ("resolved", 42, "7412", T, None)
    assert verdict(rows[3]) == ("resolved", 29, "1135", T, None)
    assert verdict(rows[4]) == ("resolved", 42, "1396r-4", T, None)
    assert verdict(rows[5]) == ("partial", None, None, None, "act_section_not_classified")
    assert verdict(rows[6]) == ("partial", None, None, None, "act_section_inside_a_range_key")
    assert verdict(rows[7]) == ("partial", None, None, None, "revised_statutes_only")
    assert verdict(rows[8]) == ("partial", None, None, None, "no_section_stated")
    assert verdict(rows[9]) == ("failed", None, None, None, "act_key_refused_by_edition_calendar")
    # Untouched, both columns and its own reading.
    assert verdict(rows[10]) == ("ok", 42, "7401", None, None)
    assert rows[9]["stated_act_name"] is not None, "a refusal must not also cost the row its statement"
    assert census.rows_by_status == {"failed": 1, "partial": 4, "resolved": 5}
    assert census.rows_by_evidence == {T: 5, "source-credit": 0, "both-sources": 0}
    assert census.pairs_resolved == 5 and census.pairs_refused == 2


@pytest.mark.slow
def test_the_act_key_and_the_section_the_filer_wrote_are_never_moved() -> None:
    """A resolution FILLS; it never rewrites what the grammar read.

    The two act columns and the publisher's text are the appeal a consumer has
    against a resolution this module got wrong, so they must come out of the
    pass byte for byte -- which is what makes "drop two columns and you have
    the old table back" a property rather than a hope.
    """

    original = [
        _act_row(act_key="clean air act", act_section="112", authority_text="Clean Air Act sec 112"),
        _act_row(act_key="social security act", act_section="1871", parse_status="corroborated",
                 corroboration_rule="agency-roster-initialism"),
    ]
    rows = [dict(row) for row in original]
    _resolved_rows(rows)
    for before, after in zip(original, rows, strict=True):
        for column in ("act_key", "act_section", "authority_text", "corroboration_rule"):
            assert after[column] == before[column], column
    # A row corroborated by RIN history keeps that word: its corroboration is a
    # different fact from this resolution, and 2,101 rows carry both.
    assert rows[1]["parse_status"] == "corroborated"
    assert rows[1]["usc_section"] == "1395hh"


def _act_carry_record(*boxes, rin="0936-AA07", publication_id="201710"):
    """One publisher reference's boxes, in the order the filer wrote them."""

    rows = []
    for ordinal, (text, extra) in enumerate(boxes):
        row = _failed_row(text, rin=rin, publication_id=publication_id)
        row.update(ordinal=ordinal, authority_source="box")
        row.update(extra)
        rows.append(row)
    return rows


def _run_act_carry(rows, keys_by_rin=None):
    """The act carry over one hand-built record, with the real act index."""

    from refspec.registry.act_resolution import ActIndex, SourceCreditIndex
    from refspec.registry.unified_agenda_parquet import (
        _DEFAULT_ACT_INDEX,
        _ActOracles,
        _carry_acts_from_an_earlier_box,
        _pl_roster,
        _SeriesCalendar,
        _Tally,
        _usc_source_credits,
    )

    index = ActIndex.from_artifact(_DEFAULT_ACT_INDEX)
    credits: SourceCreditIndex | None = _usc_source_credits()
    oracles = _ActOracles(
        lookup={}, keys_by_rin=keys_by_rin or {}, keys_by_agency={}, glosses={}, pinned=None
    )
    tally = _Tally()
    carried, census = _carry_acts_from_an_earlier_box(
        rows, index, credits, oracles, tally, _SeriesCalendar.build(_pl_roster())
    )
    return carried, census


def test_a_bare_section_box_takes_the_act_an_earlier_box_named() -> None:
    """CMS RIN 0936-AA07, Fall 2017. Five boxes:

        0  1007: SSA subsection 1902 (a) (61)
        1  1903 (a)(6)
        2  1903(b)(3)
        3  1903(q)
        4  1102

    Box 0 reads as NOTHING -- no act key, no stated act name, because
    ``stated_act_name`` needs the literal word "Act" -- and yet it is where the
    act is, written as three letters the RIN's own resolved acts turn into the
    Social Security Act. The four boxes after it are that act's sections, and
    the donor is four boxes back by the time the list ends.
    """

    rows = _act_carry_record(
        ("1007: SSA subsection 1902 (a) (61)", {}),
        ("1903 (a)(6)", {}),
        ("1903(b)(3)", {}),
        ("1903(q)", {}),
        ("1102", {}),
    )
    carried, census = _run_act_carry(rows, keys_by_rin={"0936-AA07": {"social security act"}})
    assert census.boxes == 4 and census.rows == 4 and census.max_distance == 4
    read = [
        (row["authority_text"], row["act_key"], row["act_section"],
         row["act_resolution_sibling_ordinal"], row["corroboration_rule"], row["parse_status"])
        for row in carried if row["corroboration_rule"]
    ]
    carry = "sibling-act-from-an-earlier-box"
    assert read == [
        ("1903 (a)(6)", "social security act", "1903", 0, carry, "corroborated"),
        ("1903(b)(3)", "social security act", "1903", 0, carry, "corroborated"),
        ("1903(q)", "social security act", "1903", 0, carry, "corroborated"),
        ("1102", "social security act", "1102", 0, carry, "corroborated"),
    ]
    # The U.S.C. sections are the later resolution pass's, and it answers all
    # four: 42 U.S.C. 1396b and 1302. The carry only has to have named the act
    # the resolver could answer FROM, which is why it refuses a section the
    # resolver cannot reach at all.
    _resolved_rows(carried)
    assert [(row["usc_title"], row["usc_section"]) for row in carried if row["corroboration_rule"]] == [
        (42, "1396b"), (42, "1396b"), (42, "1396b"), (42, "1302"),
    ]
    # Without the roster the donor box names nothing at all and every one of
    # the four stays refused: the letters are the whole of the evidence.
    _, silent = _run_act_carry(_act_carry_record(
        ("1007: SSA subsection 1902 (a) (61)", {}), ("1903 (a)(6)", {}),
    ))
    assert silent.boxes == 0
    assert silent.refusals["no-single-act-named-earlier-in-the-record"] == 1


def test_the_act_carry_refuses_a_donor_name_the_index_does_not_hold() -> None:
    """FCA RIN 3052-AD51, Spring 2022, box 4: ``secs 514``.

    Its donor box is ``Credit Act (12 U.S.C. 2183, 2243, ...)`` -- a name the
    filer's own text truncated to two words, which the Popular Name Tool does
    not list. "Farm Credit Act of 1971" would resolve section 514 and nothing
    in the record says that is the act. The carry refuses by name.
    """

    rows = _act_carry_record(
        ("Credit Act (12 U.S.C. 2183, 2243, 2252, 2279aa-11)",
         {"stated_act_name": "Credit Act"}),
        ("secs 514", {}),
        rin="3052-AD51", publication_id="202204",
    )
    _, census = _run_act_carry(rows)
    assert census.boxes == 0
    assert census.refusals["no-single-act-named-earlier-in-the-record"] == 1


def test_the_act_carry_refuses_a_range_a_date_and_a_dotted_number() -> None:
    """Three guards the measurement asked for, each with its own specimen."""

    from refspec.registry.act_resolution import ActIndex
    from refspec.registry.unified_agenda_parquet import _DEFAULT_ACT_INDEX, _act_naming_a_box

    aca = {"stated_act_name": "Affordable Care Act"}
    # HHS RIN 0950-AA02, Fall 2010, box 2: "secs 1401 to 1413" is a RANGE, and
    # an act citation has one section column and no end. Publishing its two
    # ends would drop 1402 to 1412.
    _, ranged = _run_act_carry(_act_carry_record(
        ("Affordable Care Act", aca), ("secs 1401 to 1413", {}), rin="0950-AA02",
    ))
    assert ranged.boxes == 0
    assert ranged.refusals["the-box-states-a-range-an-act-citation-cannot-hold"] == 1

    # DOJ RIN 1105-AB50: "11/04/1980" is a Federal Register issue DATE
    # continuing the box before it, not sections 11, 04 and 1980. "/" is in no
    # separator set here, so the shape rejects it before any fence is asked --
    # and the fence exists anyway, because a guard nobody can see is a guard
    # nobody can keep.
    from refspec.registry.unified_agenda_parquet import _TITLELESS_SECTION_BOX

    assert _TITLELESS_SECTION_BOX.fullmatch("11/04/1980") is None
    _, dated = _run_act_carry(_act_carry_record(
        ("Affordable Care Act", aca), ("11/04/1980", {}), rin="0950-AA02",
    ))
    assert dated.boxes == 0 and not any(dated.refusals.values())

    # FCA RIN 3052-AD51: the Farm Credit Act numbers its sections N.NN, and
    # "secs.4.12, 5.9" resolve perfectly under it -- but no box in that record
    # states that act, so the resolution would rest on the reader's knowledge.
    _, dotted = _run_act_carry(_act_carry_record(
        ("Affordable Care Act", aca), ("secs 4.12, 5.9", {}), rin="0950-AA02",
    ))
    assert dotted.boxes == 0

    # And the donor reader itself: a box naming TWO acts names none of them.
    index = ActIndex.from_artifact(_DEFAULT_ACT_INDEX)
    two = _failed_row("x", rin="0938-AA01")
    two["act_key"] = "clean air act"
    other = dict(two, act_key="clean water act")
    assert _act_naming_a_box([two, other], "0938-AA01", index, None) == ("act-key", None)


def _cwa_run():
    """EPA RIN 2040-AE95, Fall 2008: one Clean Water Act list cut across boxes.

    Boxes 3, 6 and 7 are the act-relative readings the builder already
    published; 4, 5 and 8 are what the same list looks like once the act stops
    being repeated. The publisher's own ordering is the evidence, so the rows
    are hand-built in that order rather than queried out of an artifact that
    predates the rule.
    """

    def box(ordinal, text, **extra):
        row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
        row.update(
            rin="2040-AE95", publication_id="200804", ordinal=ordinal, authority_text=text,
            authority_type="other", parse_status="failed", usc_appendix=False, usc_note=False,
        )
        row.update(extra)
        return row

    def act(ordinal, text, section):
        return box(ordinal, text, authority_type="act_relative", parse_status="corroborated",
                   act_key="clean water act", act_section=section)

    return [act(3, "308", "308"), box(4, "316"), box(5, "401"), act(6, "402", "402"),
            act(7, "501", "501"), box(8, "and 510")]


def _carry(rows):
    """Run the sibling-act carry, then the resolution, over hand-built rows."""

    from pathlib import Path as _Path

    from refspec.registry.act_resolution import ActIndex
    from refspec.registry.unified_agenda_parquet import (
        _carry_sibling_acts,
        _pl_roster,
        _resolve_act_citations,
        _SeriesCalendar,
        _Tally,
        _usc_source_credits,
    )

    index = ActIndex.from_artifact(_Path(__file__).resolve().parents[1] / "output/usc-act-index-2026-08-22")
    census = _carry_sibling_acts(
        rows, index, _usc_source_credits(), _Tally(), _SeriesCalendar.build(_pl_roster())
    )
    _resolve_act_citations(rows, index, _usc_source_credits())
    return census


@pytest.mark.slow
def test_a_box_holding_only_a_section_takes_the_act_from_the_box_beside_it() -> None:
    """The list is not a list: one Clean Water Act run, cut across nine boxes.

    Three of EPA 2040-AE95's boxes hold nothing but a number and came out
    unreadable; the act is written once, in box 0, and the section numbers
    carry on without it (review A, P1; reviews A and B, H8). The carry reads
    +-1 in both directions -- box 4 takes its act from 3 and box 5 from 6 --
    and every section it produces is one Table III classifies.
    """

    from refspec.registry.unified_agenda_parquet import SIBLING_ACT_RULE

    rows = _cwa_run()
    census = _carry(rows)
    assert census.rows == 3 and census.refusals == {}
    carried = {
        row["ordinal"]: (row["act_resolution_sibling_ordinal"], row["usc_title"], row["usc_section"])
        for row in rows
        if row["corroboration_rule"] == SIBLING_ACT_RULE
    }
    # CWA 316 is thermal discharge, 401 state certification, 510 state
    # authority -- and the donor ordinal says which box supplied the act, which
    # the rule's own name cannot.
    assert carried == {4: (3, 33, "1326"), 5: (6, 33, "1341"), 8: (7, 33, "1370")}
    for row in rows:
        if row["corroboration_rule"] == SIBLING_ACT_RULE:
            assert row["parse_status"] == "corroborated", "the grammar read nothing; the neighbour did"
            assert row["authority_type"] == "act_relative"
    # The boxes that already read stay exactly as they were.
    assert [row["corroboration_rule"] for row in rows if row["ordinal"] in (3, 6, 7)] == [None, None, None]


@pytest.mark.slow
def test_the_sibling_carry_refuses_what_its_four_fences_are_for() -> None:
    """Real data says only that the rule accepts what is valid.

    What it rejects is unproven until something mutates the data on purpose,
    so each fence is given a case built to defeat it. The fourth is the one
    that matters: a neighbour spelling a DIFFERENT U.S.C. section is not a
    refutation in general -- an authority list is a list of different
    provisions, and 532 of the 5,590 rows resolved elsewhere in this module
    have exactly that, correctly. It is a refutation here, because this rule's
    whole claim is that the box belongs to its neighbour's citation.
    """

    def box(ordinal, text, **extra):
        row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
        row.update(rin="2040-AE95", publication_id="200804", ordinal=ordinal, authority_text=text,
                   authority_type="other", parse_status="failed", usc_appendix=False, usc_note=False)
        row.update(extra)
        return row

    def act(ordinal, key, section="101"):
        return box(ordinal, "CWA 101", authority_type="act_relative", parse_status="corroborated",
                   act_key=key, act_section=section)

    # 1. no act in either neighbour.
    assert _carry([box(0, "316")]).refusals == {"no-act-in-either-neighbour": 1}
    # 2. the two neighbours name two different acts, so the carry would choose.
    assert _carry(
        [act(0, "clean water act"), box(1, "316"), act(2, "clean air act")]
    ).refusals == {"neighbours-name-two-acts": 1}
    # 3. the carried act resolves that section to nothing.
    assert _carry([act(0, "clean water act"), box(1, "99999")]).refusals == {
        "act_section_not_classified": 1
    }
    # 4. a neighbour spells a U.S.C. section, and it is not the one this carry
    #    produces. CWA 316 is 33 U.S.C. 1326, so 42 U.S.C. 9999 refutes it.
    assert _carry(
        [
            act(0, "clean water act"),
            box(1, "316"),
            box(2, "42 USC 9999", authority_type="usc", parse_status="ok", usc_title=42, usc_section="9999"),
        ]
    ).refusals == {"neighbour-spells-another-section": 1}
    # And the same shape AGREEING is carried, not refused: review B's rows 7
    # and 9 are exactly this -- the filer wrote one provision twice, once
    # act-relative and once as U.S.C.
    agreeing = [
        act(0, "clean water act"),
        box(1, "316"),
        box(2, "33 USC 1326", authority_type="usc", parse_status="ok", usc_title=33, usc_section="1326"),
    ]
    assert _carry(agreeing).rows == 1


#: The act resolver's counts were measured on a scratch build whose builder
#: module hashes to this, `--output-root` under a temporary directory and the
#: same pinned editions, act index, source credits and oracles. A DIGEST rather
#: than a commit, for the reason ``_producer_block`` gives: a receipt resolves
#: to code by hashing blobs, and the scratch build's own
#: ``producer.modules.unified_agenda_parquet`` is this string, so the tree that
#: produced these numbers is identified and not guessed at.
#:
#: That build also held ``usc_section_oracle.py`` at ``da46f0de`` on purpose. A
#: concurrent change turning B8 from a correction into a candidate moves 1,441
#: rows of ``usc_section_corrected``; pinning the oracle is what keeps that out
#: of these numbers, so a diff against the artifact shows only act-relative
#: rows moving.
_ACT_RESOLUTION_SCRATCH_BUILDER = "sha256:4673ba50"


@pytest.mark.slow
def test_the_act_relative_rows_carry_the_section_they_name(con) -> None:
    """9,065 rows named an act and a section and carried no U.S.C. section.

    The builder recognised act-relative citations and never asked the resolver
    what they resolved to, so every one of these rows came out with usc_title
    and usc_section NULL -- and 6,214 of them said parse_status "failed", which
    a consumer reads as "could not resolve" when the parse had succeeded and
    the resolution had simply never been attempted.

    Measured on the scratch build of builder sha256:4673ba50; awaits the
    rebuild. Every number here is also the receipt's, recomputed from the table
    by the census test below.
    """

    _awaits_the_rebuild(con, "act_resolution_evidence", _ACT_RESOLUTION_SCRATCH_BUILDER)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    A = f"{L} where authority_type = 'act_relative'"
    # 9,092 -> 9,576 at rebuild #9 (66d96462, H3): +484, the 471 other/failed
    # rows retyped act_relative/failed plus 13 retyped act_relative/
    # corroborated (see test_the_authority_field_is_no_longer_shipped_as_
    # raw_text for the subset query). Every downstream count below that does
    # NOT move is verified unchanged against the rebuild-8 baseline; only
    # act_key-is-null and the parse_status split move, both entirely H3's.
    #
    # 9,576 -> 9,781 at rebuild #11: +205, zero departures (see
    # test_the_authority_field_is_no_longer_shipped_as_raw_text's own note on
    # `acts` for the #56/#44-45 split).
    # Rebuild #14 (2026-08-31 wave, research/evidence/rebuild14-delta-2026-08-31.txt): 11,209 -> 11,337 (+128).
    assert _one(con, f"select count(*) from {A}") == 11_337
    # 5,590 rows / 354 (act, section) pairs, which is exactly what the live
    # resolver answered over this corpus when the bulk Table III index landed
    # (research/evidence/act-index-bulk-table3-2026-08-22.md, section 4). The
    # builder now publishes what that measurement showed it could.
    #
    # 5,607 -> 5,657 at rebuild #11: +50, zero departures. #56 contributes 10
    # (6 act_relative/resolved rows with no rule marker -- the same 6 the
    # parse_status split below counts -- plus 4 more index-holds-the-stated-
    # name rows that ALSO resolve a table3 section); #44/45 contributes 40
    # (18 sibling-act-from-an-earlier-box, 14 agency-roster-initialism, 3
    # pinned-roster-initialism:candidate-index-match, 3 :self-glossing, 2
    # :pinned-quote). 10 + 40 = 50, all of it table3-classification (5,594 ->
    # 5,644); source-credit is untouched at 13.
    assert _one(con, f"select count(*) from {A} and act_resolution_evidence is not null") == 6_768
    # 356 -> 360 at rebuild #11: +4 distinct (act_key, act_section) pairs,
    # all #44/45's -- (public health service act, 2718) pinned-quote,
    # (public health service act, 353) candidate-index-match, (clean air
    # act, 103) agency-roster-initialism (the second half of the
    # /CAA-112-&-103 split), (united states housing act of 1937, 3)
    # self-glossing.
    assert _one(
        con, f"select count(distinct (act_key, act_section)) from {A} and act_resolution_evidence is not null"
    ) == 372
    assert dict(
        _rows(con, f"select act_resolution_evidence, count(*) from {A} and act_resolution_evidence is not null group by 1")
    ) == {"table3-classification": 6_755, "source-credit": 13}

    # An identifier or a reason, never both and never neither -- the invariant
    # ActResolution enforces per answer, held here over the whole table.
    assert _one(
        con, f"select count(*) from {A} and (act_resolution_evidence is null) = (act_resolution_reason is null)"
    ) == 0
    assert _one(
        con,
        f"select count(*) from {L} where authority_type <> 'act_relative' "
        "and (act_resolution_evidence is not null or act_resolution_reason is not null)",
    ) == 0, "no other row carries an act resolution"
    # A section is published exactly where the evidence says one was found.
    assert _one(
        con, f"select count(*) from {A} and (usc_section is null) <> (act_resolution_evidence is null)"
    ) == 0
    assert _one(con, f"select count(*) from {A} and usc_section is not null and usc_title is null") == 0

    # The citation the filer made is kept beside the resolution, never replaced.
    # 7 -> 478 at rebuild #9: +471, exactly H3's act_relative/failed rows --
    # "the truth is narrower... this is an act-relative citation whose ACT
    # the index cannot name" carries no act_key by construction, unlike the
    # 13 act_relative/corroborated rows (index-holds-the-stated-name), which
    # all carry one ('social security act' etc.) and so do not move this
    # count: 7 (baseline) + 471 (H3 failed) + 0 (H3 corroborated) = 478.
    #
    # 478 -> 458 at rebuild #11: -20, entirely #56's -- the same net -20 that
    # shrinks the act_not_in_index/act_key-is-null population from 471 to
    # 451 (test_the_stated_acts_over_the_built_table); the 7
    # act_key_refused_by_edition_calendar rows are untouched by either unit.
    # 7 + 451 = 458.
    assert _one(con, f"select count(*) from {A} and act_key is null") == 458
    assert _one(con, f"select count(*) from {A} and act_resolution_evidence is not null and act_section is null") == 0

    # parse_status now says the outcome. "failed" survives on six rows only:
    # three whose act the index does not hold and three whose act key the
    # edition calendar refused.
    # failed 10 -> 481 (+471) and corroborated 2,786 -> 2,799 (+13) at
    # rebuild #9, both H3 (66d96462); resolved and partial are untouched --
    # H3 only ever produces "failed" or "corroborated" (index-holds-the-
    # stated-name), never "resolved" or "partial".
    #
    # 481 -> 461 (-20), 2,793 -> 2,826 (+33), 2,799 -> 2,985 (+186),
    # 3,503 -> 3,509 (+6) at rebuild #11, all attributed in
    # test_the_authority_field_is_no_longer_shipped_as_raw_text's `acts` note
    # and test_the_continuations_families_are_measured_not_asserted's
    # `carried` note: "failed" and "partial" move only under #56 (no
    # pinned-roster-initialism or sibling-act-carry row is ever "failed" or
    # "partial" -- every one of those rules always corroborates); "resolved"
    # moves +2 from arrivals and +4 from corroborated rows resolving a step
    # further, both #56; "corroborated" carries #56's +15
    # (index-holds-the-stated-name) and #44/45's +171.
    assert dict(_rows(con, f"select parse_status, count(*) from {A} group by 1")) == {
        "resolved": 3_509,
        "partial": 2_826,
        # Rebuild #14 (2026-08-31 wave): corroborated +128 (95 retiered + 33 apostrophe-year rows).
        "corroborated": 4_541,
        "failed": 461,
    }
    assert _one(
        con,
        f"select count(*) from {A} and parse_status = 'failed' "
        "and act_resolution_reason not in ('act_not_in_index', 'act_key_refused_by_edition_calendar')",
    ) == 0, "only an unknown ACT leaves an act-relative row failed"
    # 2,101 of the rows RIN history had already corroborated resolve as well.
    # They keep "corroborated": that corroboration is a different fact, and it
    # is the one their corroboration_rule names.
    #
    # 2,104 -> 2,148 at rebuild #11: +44, the parse_status='corroborated'
    # subset of the same 50-row evidence-not-null arrival above (the 6
    # act_relative/resolved arrivals are not "corroborated" and so are
    # excluded here) -- #56 contributes 4 (index-holds-the-stated-name),
    # #44/45 contributes 40 (18 sibling-act-carry + 14 agency-roster-
    # initialism + 3 candidate-index-match + 3 self-glossing + 2
    # pinned-quote).
    assert _one(
        con, f"select count(*) from {A} and parse_status = 'corroborated' and act_resolution_evidence is not null"
    ) == 3_259

    # Review B's five, resolved; and the three it says are refusals, refused.
    def resolution(text):
        return _row(
            con,
            f"select any_value(usc_title), any_value(usc_section), any_value(act_resolution_reason), count(*) "
            f"from {A} and authority_text = '{text}'",
        )

    assert resolution("sec. 504 of the Rehabilitation Act of 1973") == (29, "794", None, 10)
    assert resolution("Social Security Act, sec 1871") == (42, "1395hh", None, 50)
    assert resolution("Clean Air Act sec 112") == (42, "7412", None, 222)
    assert resolution("ERISA sec. 505") == (29, "1135", None, 36)
    assert resolution("sec 1923(a)(2)(D) of the Social Security Act") == (42, "1396r-4", None, 1)
    assert resolution("Clean Air Act Amendments of 1990, sec 112") == (
        None, None, "act_section_not_classified", 32,
    )
    assert resolution("Section 4(b) of the Steel Trade Liberalization Program Implementation Act") == (
        None, None, "act_section_inside_a_range_key", 2,
    )
    assert resolution("General Mining Act of 1872, as amended") == (None, None, "revised_statutes_only", 4)


@pytest.mark.slow
def test_the_receipt_census_covers_the_act_resolution(con) -> None:
    """A declared count that nothing recomputes is a claim, not a pin.

    Every key is recomputed from the table it describes. Measured on the
    scratch build of builder sha256:4673ba50; awaits the rebuild.
    """

    import json

    from refspec.registry.unified_agenda_parquet import (
        ACT_CARRY_RULE,
        ACT_RESOLUTION_EVIDENCE,
        ACT_RESOLUTION_REASONS,
        SIBLING_ACT_RULE,
    )

    _awaits_the_rebuild(con, "act_resolution_evidence", _ACT_RESOLUTION_SCRATCH_BUILDER)
    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    A = f"{L} where authority_type = 'act_relative'"
    assert declared["actRelativeRowsByStatus"] == dict(
        _rows(con, f"select parse_status, count(*) from {A} group by 1 order by 1")
    )
    # Every declared reason and every declared evidence, listed even at zero: a
    # refusal that stops being reported is what these columns exist to show.
    assert set(declared["actRelativeRowsByResolutionReason"]) == set(ACT_RESOLUTION_REASONS)
    assert declared["actRelativeRowsByResolutionReason"] == {
        reason: _one(con, f"select count(*) from {A} and act_resolution_reason = '{reason}'")
        for reason in ACT_RESOLUTION_REASONS
    }
    assert set(declared["actRelativeResolvedRowsByEvidence"]) == set(ACT_RESOLUTION_EVIDENCE)
    assert declared["actRelativeResolvedRowsByEvidence"] == {
        evidence: _one(con, f"select count(*) from {A} and act_resolution_evidence = '{evidence}'")
        for evidence in ACT_RESOLUTION_EVIDENCE
    }
    assert declared["actRelativeResolvedPairs"] == _one(
        con, f"select count(distinct (act_key, act_section)) from {A} and act_resolution_evidence is not null"
    )
    assert declared["actRelativeRefusedPairs"] == _one(
        con,
        f"select count(distinct (act_key, act_section)) from {A} "
        # act_key NULL is not a pair: the calendar refused the key, so there
        # was never a (act, section) to ask the resolver about.
        "and act_resolution_evidence is null and act_section is not null and act_key is not null",
    )
    # The census closes against the table's own act-relative row count.
    # 9,092 -> 9,576 at rebuild #9 (66d96462, H3): +484, the same movement
    # test_the_act_relative_rows_carry_the_section_they_name attributes (471
    # act_relative/failed + 13 act_relative/corroborated).
    #
    # 9,576 -> 9,781 at rebuild #11: +205, the same #56/#44-45 movement
    # test_the_act_relative_rows_carry_the_section_they_name's own
    # parse_status dict attributes.
    assert sum(declared["actRelativeRowsByStatus"].values()) == 11_337
    assert (
        sum(declared["actRelativeRowsByResolutionReason"].values())
        + sum(declared["actRelativeResolvedRowsByEvidence"].values())
        == 11_337
    )
    # Three narrowings of a resolver code, each carrying its measured
    # population: without them 37 rows would say "not classified" where OLRC
    # files the section under a range key, 126 would say "not expressible"
    # where the target is a note, and 4 would say "no section stated" where no
    # section of the act reaches the Code at all.
    #
    # resolves_to_note: 126 -> 142 at rebuild #11: +16, entirely #44/45's
    # sibling-act carry -- 16 bare-section boxes whose donor-carried act
    # section targets a note rather than Code text, zero departures. The
    # other two narrowings are untouched by either unit.
    assert {
        reason: declared["actRelativeRowsByResolutionReason"][reason]
        for reason in ("act_section_inside_a_range_key", "resolves_to_note", "revised_statutes_only")
    } == {"act_section_inside_a_range_key": 37, "resolves_to_note": 157, "revised_statutes_only": 4}
    # resolves_to_note 142 -> 157 at rebuild #14 (2026-08-31 wave): +15 of the 128 retyped rows.
    # corroborated: 2,104 -> 2,148 (+44), the same corroborated-with-evidence
    # movement test_the_act_relative_rows_carry_the_section_they_name
    # attributes (#56 +4, #44/45 +40). failed: 3,503 -> 3,509 (+6): every
    # "resolved" row's prior status was "failed" by construction (a
    # corroborated row keeps "corroborated" once resolved), so this equals
    # the final resolved-status total's own +6 (#56 only -- 2 arrivals + 4
    # rows resolving a step further from corroborated).
    assert declared["actRelativeResolvedRowsByPriorStatus"] == {"corroborated": 3_259, "failed": 3_509}
    # The sibling-act carry, counted with every refusal beside it.
    assert declared["siblingActCarriedRows"] == _one(
        con, f"select count(*) from {L} where corroboration_rule = '{SIBLING_ACT_RULE}'"
    ) == 3
    assert declared["siblingActRefusalsByReason"] == {
        "no-act-in-either-neighbour": 277,
        "act_section_not_classified": 17,
        "act_section_ambiguous": 1,
        "classification_not_current": 1,
    }
    # The year-less lexicon, counted from the other end by the test above.
    assert declared["actNameYearlessStemsAdmitted"] == 5_292
    assert declared["actNameYearlessStemsRefused"] == 634
    assert declared["actNameYearlessStemsMergedByRename"] == 4
    # At rebuild #11 (#44/45), a second rule -- ACT_CARRY_RULE, the box-run
    # sibling-act carry -- also writes a donor ordinal into this same column,
    # so the invariant widens from "SIBLING_ACT_RULE's own rows" to "either
    # sibling-carrying rule's own rows": 34 rows (ACT_CARRY_RULE) that used
    # to violate the narrower form now satisfy the wider one, and the column
    # still names no donor on any row neither rule touched.
    assert _one(
        con,
        f"select count(*) from {L} where (act_resolution_sibling_ordinal is null) "
        f"<> (corroboration_rule not in ('{SIBLING_ACT_RULE}', '{ACT_CARRY_RULE}'))",
    ) == 0, "the donor ordinal is stated on exactly the rows a sibling-carrying rule carried"


#: The CFR authority-note join's counts were measured on a scratch build whose
#: builder module hashes to this -- `--output-root` under a temporary
#: directory, the builder's own default act index, and the same pinned
#: editions, source credits and oracles. A DIGEST rather than a commit, for the
#: reason ``_producer_block`` gives.
#:
#: THE 2026-08-24 BUILD IS THE ORACLE SWITCH: the cache moved from the
#: 287-part set-cover (``silent-misreads-2026-08-22/ecfr-authority-notes.jsonl``,
#: 2026-08-20) to every authority note the register publishes
#: (``ecfr-authority-notes-2026-08-24/notes.jsonl``, 8,240 notes over all 49
#: non-reserved titles). Diffed against a faithful rebuild of rebuild #9
#: (799,126 rows, receipt e88d9dca), the whole legal-authorities table moves on
#: 269,090 rows and the moved columns are exactly three sets: 8 rows on
#: ``usc_section_corrected``/``_section``/``_pinpoint`` (commit 084edf69, the
#: CFTC `7 USC 8a` -> 12a corrections, exactly the 8 that commit's report
#: names), 478 rows on the disposition columns (commits daea8d4b / f921089e /
#: f598e42f -- 272 span, 189 pinpoint, 17 chapter-guard refusals, exactly that
#: unit's account), and 268,802 rows on this join's own two columns. 198 rows
#: are in two of those sets at once, which is why 8 + 478 + 268,802 exceeds
#: 269,090. NO OTHER COLUMN MOVED IN EITHER DIRECTION, and the actions,
#: CFR-reference and timetable tables came out byte-identical.
#:
#: **21,882 of this join's 268,802 rows are not arrivals**, and that is a
#: finding rather than a slip. ``CfrAuthorityNotes.judge`` returns the BEST
#: verdict over ALL the parts a rule names, because a rule amending four parts
#: is authorised by all four notes together; widening the cache widens each
#: rule's held set, so an absence recorded against the one part generation 1
#: happened to hold can be settled by a sibling part it did not. Every one of
#: the 21,882 moves UP the precedence -- 11,287 absent -> present, 8,091
#: near-miss -> present, 2,504 absent -> near-miss -- and there are ZERO
#: downgrades and zero judged rows that went back to NULL. A further 38,913
#: rows keep their verdict and name a different part, for the same reason: the
#: part an absence names is the first HELD part in citation order.
#:
#: THE NOTES THEMSELVES MOVED NOTHING. Every one of the 287 generation-1 parts
#: is in generation 2, 278 byte-identical and 9 differing only in a character
#: reference, and asking each of those 287 parts' own note all 16,373
#: (part, citation) questions any row asks of it gives the IDENTICAL verdict
#: under both generations -- 0 disagreements. So no verdict moved because a
#: note said something new; they moved because more of each rule's own parts
#: can now be read.
_CFR_NOTE_SCRATCH_BUILDER = "sha256:c08aebe7"


@pytest.mark.slow
def test_the_rules_own_cfr_part_note_judges_what_the_filer_wrote(con) -> None:
    """The publisher's answer key, on 668,894 rows, repairing nothing.

    460,887 -> 668,894 at the oracle switch: 208,007 rows become judgeable for
    the first time because the cache grew from 287 parts to every part the
    register publishes, and 21,882 already-judged rows move up the precedence
    because a sibling part of their own rule can now be read. Nothing moves
    down and nothing returns to NULL.

    Measured on the scratch build of builder sha256:c08aebe7; awaits the
    rebuild.
    """

    _awaits_the_rebuild(con, "authority_in_own_cfr_note", _CFR_NOTE_SCRATCH_BUILDER)
    _awaits_the_oracle_switch(_CFR_NOTE_SCRATCH_BUILDER)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    by_verdict = {
        row[0]: (row[1], row[2])
        for row in _rows(
            con,
            f"select authority_in_own_cfr_note, count(*), count(distinct authority_text) from {L} "
            "where authority_in_own_cfr_note is not null group by 1",
        )
    }
    # rows / distinct texts, and each row total is closed against the baseline
    # by arrivals and upgrades measured on a keyed join of the two builds:
    #   present   326,930 -> 488,758  = +142,450 new  +11,287 absent    +8,091 near-miss
    #   near-miss  47,590 ->  56,874  =  +14,871 new   +2,504 absent    -8,091 to present
    #   absent     86,367 -> 123,262  =  +50,686 new  -11,287 to present -2,504 to near-miss
    # The campaign's own loose-detector table over the 798,114-row build it
    # measured read 308,388 / 9,843 present, 49,409 / 3,510 near-miss and
    # 103,076 / 7,727 absent over 287 parts, which is the same shape from an
    # extractor written independently of the grammar.
    #
    # At rebuild #11, entirely rows leaving authority_type='other' (which
    # this join never judges) for a type it does: 174 rows newly COVERED-and-
    # JUDGED (present +1, absent +173) plus 3 already-covered act_relative/
    # failed rows whose OWN row never changed but whose CFR PART's note now
    # reads a citation it did not before -- "Secs. 9, 13 and 14, Richard B.
    # Russell National School Lunch Act" (7 CFR 225's note) now parses "13"
    # as one of the note's identities, one edit from "Richard B Russell
    # National School Lunch Act" section 13 (RIN 0584-AE96 x2 editions,
    # 0584-AF07 x1) -- #56's grammar widening (citation_grammar.py changed;
    # cfr_authority_notes.py and its pinned cache did not), so absent -> 170,
    # near-miss +3. present: 488,758 -> 488,759 (+1), #44/45's
    # agency-roster-initialism (the covered "other/failed" -> "present" row).
    # near-miss: 56,874 -> 56,877 (+3), #56's, all three explained above.
    # absent: 123,262 -> 123,432 (+170) = +173 arrivals (#56 33, #44/45 140)
    # - 3 departures to near-miss (#56).
    assert by_verdict == {
        # Rebuild #14: present +10 / absent +97 rows, all act_relative -- the
        # 107 retyped rows the note now judges (unjudged 'other' 1,724 -> 1,617).
        # Rebuild #15 (2026-09-01 wave, research/evidence/rebuild15-delta-2026-09-01.txt) (REF-062): the
        # Stat-page note gate refuses 266 fabricated note citations across 107
        # notes, moving judgments; the 15 removed filer rows leave the census.
        "present": (489_168, 20_216),
        "near-miss": (56_283, 5_795),
        "absent": (124_906, 14_115),
    }
    # The verdict and the part that gave it are one fact in two columns.
    assert _one(
        con,
        f"select count(*) from {L} where (authority_in_own_cfr_note is null) <> (cfr_note_part is null)",
    ) == 0
    # Every named part is a part the cache holds and the rule's own CFR
    # Citation field names -- the join key is the reference table beside this
    # one, never a CFR part cited as authority.
    #
    # 4,858 PARTS ANSWER, WHERE 5,793 ARE HELD AND NAMED BY SOME RULE. The
    # difference is not a hole: a present verdict stops at the first part that
    # names the citation and an absence names the first held part in citation
    # order, so 936 parts are read on every row of their rules and never
    # happen to be the one that answers.
    named = {row[0] for row in _rows(con, f"select distinct cfr_note_part from {L} where cfr_note_part is not null")}
    assert len(named) == 4_858
    assert {"21 CFR 310", "49 CFR 192", "40 CFR 122"} <= named
    assert "45 CFR 12a" in named, "the part that settles 40 U.S.C. 550 is held now"


@pytest.mark.slow
def test_the_note_verdict_is_a_verdict_and_never_a_repair(con) -> None:
    """Four specimens the human review read by hand, as the column reads them.

    Three of the four are UNCHANGED by the oracle switch, which is the point:
    their own parts' notes are byte-identical across the two fetches, and a
    wider cache does not make a note say something new. The fourth is the
    campaign's opening specimen and it is the one that was waiting on coverage.

    Measured on the scratch build of builder sha256:c08aebe7; awaits the
    rebuild.
    """

    _awaits_the_rebuild(con, "authority_in_own_cfr_note", _CFR_NOTE_SCRATCH_BUILDER)
    _awaits_the_oracle_switch(_CFR_NOTE_SCRATCH_BUILDER)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"

    def verdict(rin: str, publication: str, section: str) -> tuple:
        return _row(
            con,
            f"select authority_in_own_cfr_note, cfr_note_part, usc_section_verdict from {L} "
            f"where rin = '{rin}' and publication_id = '{publication}' and usc_section = '{section}'",
        )

    # Review E row 6 / review A: RIN 2137-AE60's whole list is title 49 typed
    # as 40. `40 USC 60137` is absent from its own part's note -- and so is the
    # corrected `49 U.S.C. 60137`, because the note enumerated the sections in
    # 2010 and says "60101 et. seq." as fetched 2026-08-24 too.
    assert verdict("2137-AE60", "201010", "60137") == ("absent", "49 CFR 192", "absent")
    # The finding the review flagged hardest, and the one no other column in
    # this table can see: `40 U.S.C. 5103` (Capitol Grounds) is a REAL section,
    # so the section fence says "exists" and nothing accuses it. The note says
    # 49 U.S.C. 5103 -- one edit away, in the rule's own part.
    assert verdict("2137-AE60", "201010", "5103") == ("near-miss", "49 CFR 192", "exists")
    # Review G row 1: "sec. 501(a)" transcribed into the `1361a` slot. Absent
    # from all four of the rule's held parts; the column names the first.
    assert verdict("2040-AD08", "199710", "1361a") == ("absent", "40 CFR 122", "absent")
    # AND THE CAMPAIGN'S OPENING SPECIMEN, WHICH THIS COLUMN COULD NOT ASK
    # BEFORE. RIN 0991-AC14 names one part, 45 CFR 12a, whose entire note is
    # "42 U.S.C. 11411; 40 U.S.C. 550." -- fetched by hand during the campaign,
    # never written into the 287, and NULL here for that reason alone. The
    # whole-register fetch holds it, and the answer is the one the campaign
    # gave by hand.
    assert verdict("0991-AC14", "202310", "550") == ("present", "45 CFR 12a", "exists")
    assert _one(con, f"select count(*) from {L} where cfr_note_part = '45 CFR 12a'") == 8
    # Nothing moved that this join does not write: the section fence's own
    # answer on these four rows is what it was before this join existed.


@pytest.mark.slow
def test_the_note_verdict_census_is_the_receipts(con) -> None:
    """Every count in the receipt, recomputed from the built column.

    Measured on the scratch build of builder sha256:c08aebe7; awaits the
    rebuild.
    """

    import json

    from refspec.registry.cfr_authority_notes import VERDICTS as CFR_NOTE_VERDICTS

    _awaits_the_rebuild(con, "authority_in_own_cfr_note", _CFR_NOTE_SCRATCH_BUILDER)
    _awaits_the_oracle_switch(_CFR_NOTE_SCRATCH_BUILDER)
    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    assert declared["cfrNoteVerdictRows"] == {
        verdict: _one(con, f"select count(*) from {L} where authority_in_own_cfr_note = '{verdict}'")
        for verdict in CFR_NOTE_VERDICTS
    }
    assert declared["cfrNoteVerdictTexts"] == {
        verdict: _one(
            con,
            f"select count(distinct authority_text) from {L} where authority_in_own_cfr_note = '{verdict}'",
        )
        for verdict in CFR_NOTE_VERDICTS
    }
    # Rows per (authority_type, verdict): "absent" means one thing for a
    # U.S.C. section and another for an act name, and the totals hide that.
    # The act family is the honest weak one -- a CFR authority note names the
    # STATUTE, not the act -- and widening the cache did not change that:
    # act_relative is still 6,842 absent against 643 present.
    #
    # Every one of these twelve closes against the baseline by arrivals and
    # upgrades, measured on a keyed join of the two builds:
    #   usc          present 320,845 -> 475,828  = +136,361 new +10,531 +8,091
    #                near-miss 47,417 -> 56,428  =  +14,698 new  +2,404 -8,091
    #                absent    66,688 -> 88,577  =  +34,824 new -10,531 -2,404
    #   public_law   present   3,444 ->  8,241   =   +4,148 new    +649
    #                near-miss    72 ->    238   =     +106 new     +60
    #                absent   14,931 -> 26,394   =  +12,172 new    -649  -60
    #   cfr          present   2,278 ->  4,046   =   +1,745 new     +23
    #                near-miss   101 ->    202   =      +65 new     +36
    #                absent      902 ->  1,449   =     +606 new     -23  -36
    #   act_relative present     363 ->    643   =     +196 new     +84
    #                near-miss     0 ->      6   =       +2 new      +4
    #                absent    3,846 ->  6,842   =   +3,084 new     -84   -4
    #
    # act_relative moves again at rebuild #11 -- present 643 -> 644 (+1),
    # near-miss 6 -> 9 (+3), absent 6,842 -> 7,012 (+170) -- the entire delta
    # test_the_rules_own_cfr_part_note_judges_what_the_filer_wrote's
    # `by_verdict` attributes, and it is the WHOLE table-wide delta: cfr,
    # public_law and usc are byte-for-byte unchanged (neither #56 nor #44/45
    # touches a cfr/public_law/usc row's CFR-note verdict).
    assert declared["cfrNoteVerdictRowsByAuthorityType"] == {
        "act_relative": {"present": 883, "near-miss": 9, "absent": 8_217},
        "cfr": {"present": 4_046, "near-miss": 202, "absent": 1_449},
        "public_law": {"present": 8_241, "near-miss": 238, "absent": 26_394},
        # Rebuild #15 (2026-09-01 wave, research/evidence/rebuild15-delta-2026-09-01.txt): the Stat-page
        # note gate (REF-062) -- only usc moves; the other three types are
        # byte-for-byte unchanged.
        "usc": {"present": 475_998, "near-miss": 55_834, "absent": 88_846},
    }
    # THE FOUR COVERAGE COUNTS ARE WHERE THE ORACLE SWITCH IS VISIBLE, and they
    # are printed beside the verdicts precisely so a coverage move and a
    # data-quality move cannot be confused. rows 489,969 -> 713,547, rins
    # 22,788 -> 40,613, rules 121,731 -> 207,463: the corpus names 8,652
    # distinct parts on the reader's join key and the cache now holds 5,793 of
    # them, against 287 before. partsHeld is the whole cache (8,240) and
    # partsNamedByARule is the part of it this corpus reaches, and the 2,447
    # held parts no rule in this corpus names are counted rather than
    # explained here.
    assert declared["cfrNoteCoverage"] == {
        # Rebuild #15 (2026-09-01 wave): 714,909 -> 714,894, the 15 removed rows
        # (REF-062); rins, rules and both part counts hold still.
        "rows": 714_894,
        "rins": 40_613,
        "rules": 207_463,
        "partsHeld": 8_240,
        "partsNamedByARule": 5_793,
    }
    # The census closes: every covered row is judged or counted as unjudged.
    # The executive-order rows are still the largest unjudged family and still
    # the deliberate one -- every in-range EO number names a real order, so a
    # note naming a different one is not evidence. 12,308 -> 16,684 is coverage
    # and nothing else: no reader is defined for the type at all, so every one
    # is unjudged by construction whichever notes are held.
    assert declared["cfrNoteUnjudgedRowsByType"]["executive_order"] == 16_684
    assert declared["cfrNoteUnjudgedRowsByType"]["usc"] == 722, "typed usc, naming no section"
    assert (
        sum(declared["cfrNoteVerdictRows"].values()) + sum(declared["cfrNoteUnjudgedRowsByType"].values())
        == declared["cfrNoteCoverage"]["rows"]
    )


#: The recodification join's counts were measured on a scratch build whose
#: builder module hashes to this -- `--output-root` under a temporary
#: directory, the builder's own default act index, and the same pinned
#: editions, source credits, notes and oracles. A DIGEST rather than a commit,
#: for the reason ``_producer_block`` gives.
#:
#: When the join first landed the diff against a faithful rebuild was EMPTY in
#: both directions: three columns arrived and nothing moved. On 2026-08-24 it
#: is not, and this is the whole account of what did. Diffed against a
#: faithful rebuild of rebuild #9 (799,126 rows, receipt e88d9dca): 486 rows
#: carry a different value, 8 of them attributed to commit 084edf69 (the
#: CFTC `7 USC 8a` -> 12a corrections, 2 RINs, exactly the 8 that commit's own
#: report names) and 478 to this change -- 272 span rows whose successors grew
#: to their members' union, 189 pinpointed rows whose successors narrowed to
#: the printed row the citation names, and 17 rows the chapter guard refused.
#: Nothing else moved in either direction, and the actions, CFR-reference and
#: timetable tables came out byte-identical.
_DISPOSITION_SCRATCH_BUILDER = "sha256:0f602120"


@pytest.mark.slow
def test_the_recodification_answers_the_one_unknown_it_can(con) -> None:
    """2,548 rows the section fence refuses, and what an Act did with them.

    The fence says ``unknown`` for ``title_49_appendix_not_published`` because
    no OLRC annual archive year holds a ``usc49a.htm`` -- and that stays true
    on every one of these rows. What arrives beside it is a different question's
    answer, from the printed 1994 disposition table: 2,238 rows restated
    somewhere in the new title, 117 repealed with no successor at all, 176 the
    table does not list, and 17 the guard refuses to read a table for at all.

    First measured on the scratch build of builder sha256:0f602120; re-pinned
    against rebuild #12, whose table digests match rebuild12-delta.txt.
    """

    _awaits_the_rebuild(con, "usc_disposition_span_members", _DISPOSITION_SCRATCH_BUILDER)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    # rows / texts / RINs / (title, section, appendix) pairs. The pair count is
    # the one that says which shortfall is real: 27 of the 146 sections are
    # missing from the table and they carry 176 of the 2,543 rows, which is
    # what a hold-out of one-off malformed tokens looks like rather than a gap
    # in the source.
    #
    # A PAIR NO LONGER DECIDES A VERDICT, and that is the 2026-08-24 change
    # showing in the pair counts: two pairs now appear under two verdicts each
    # (49:1341 and 49:201), because "49 USC 1341(c)" points at the one
    # subsection the volume prints as repealed while bare "49 USC 1341" takes
    # (a) and (b) to 106. The question is the citation's, not the pair's.
    assert {
        row[0]: row[1:]
        for row in _rows(
            con,
            f"select usc_disposition_verdict, count(*), count(distinct authority_text), count(distinct rin), "
            f"count(distinct (usc_title, usc_section, usc_appendix)) from {L} "
            "where usc_disposition_verdict is not null group by 1",
        )
    } == {
        # Rebuild #15 (2026-09-01 wave, research/evidence/rebuild15-delta-2026-09-01.txt): -53 rows,
        # the title-49-appendix dotted regulation numbers the reg-dot fence
        # now refuses at parse (REF-062).
        "exists-as-recodified": (2_181, 213, 301, 116),
        "repealed-no-successor": (117, 32, 27, 20),
        "not-in-table": (175, 32, 29, 26),
    }
    # THE GATE IS THE FENCE'S OWN REASON, and nothing else. A disposition is
    # written on exactly the rows the oracle refuses for that one hole -- never
    # on a row it could answer for itself, and never on a live section of the
    # current title -- MINUS the rows the guard refuses, which are inside that
    # population and carry a named refusal instead of a verdict.
    assert _one(
        con,
        f"select count(*) from {L} where (usc_disposition_verdict is null and usc_disposition_refusal is null) "
        "<> (usc_section_verdict_reason is distinct from 'title_49_appendix_not_published')",
    ) == 0
    assert _one(
        con,
        f"select count(*) from {L} where usc_disposition_refusal is not null "
        "and (usc_disposition_verdict is not null or usc_disposition_table is not null "
        "or usc_disposition_successors is not null)",
    ) == 0, "a refusal read no table, so it can carry no answer from one"
    assert [row[0] for row in _rows(
        con, f"select distinct usc_section_verdict from {L} where usc_disposition_verdict is not null"
    )] == ["unknown"], "the verdict beside a disposition is the verdict it always was"
    # The three columns are one fact: which table answered is stated wherever a
    # verdict is, and the successors are stated exactly where there are any.
    assert _one(
        con,
        f"select count(*) from {L} where (usc_disposition_table is null) <> (usc_disposition_verdict is null)",
    ) == 0
    assert _one(
        con,
        f"select count(*) from {L} where (usc_disposition_successors is null) "
        "<> (usc_disposition_verdict is distinct from 'exists-as-recodified')",
    ) == 0
    assert [row[0] for row in _rows(
        con, f"select distinct usc_disposition_table from {L} where usc_disposition_table is not null"
    )] == ["title-49-1994"], "one table is pinned; six recodifications are not"


#: Ten of the 2,543 rows the table was ASKED about, drawn with
#: ``random.Random(20260823).sample(population, 10)`` where the population is
#: every row of the built table whose section-fence reason is
#: ``title_49_appendix_not_published``, sorted by its own key
#: ``(rin, publication_id, ordinal, citation_ordinal)`` -- 2,543 rows, 2,543
#: distinct keys. Each is ``(RIN, edition, the filer's own text, the parsed
#: section, the verdict, EVERY successor)``, frozen so a human can read them
#: against the printed pages once and a later change has to explain itself.
#:
#: The population is the FENCE'S OWN reason and not "carries a verdict", so
#: the guard's 17 refusals stay inside it. Rebuild #12 moved the population
#: 2,548 -> 2,543 (rebuild12-delta.txt: five rows the grammar units now read
#: differently), so the same seed re-drew ONE position: row 6 is now
#: ``49 USC 121(c)`` -> 80116, which is line 330 of the publisher's own 1994
#: disposition extract, and the repealed-no-successor specimen that held row
#: 6 is asserted by key in the test instead. The other nine rows are
#: unchanged from the previous draw. Row 8 is the row the visual review of
#: 2026-08-23 called a wrong published value: its verdict is now None
#: because no table was read for it at all.
_DISPOSITION_BY_EYE = (
    # Re-drawn at rebuild #15 (2026-09-01): the population moved 2,543 ->
    # 2,490 (the reg-dot fence, REF-062), so the seeded sample moved with it
    # -- 9000-AJ79's 121(c) left the draw and 2120-AE42's "1421 to 1431"
    # range entered.
    ("2120-AF67", "199510", "49 USC 1472", "1472", "exists-as-recodified",
     ("49:46316", "49:46306", "49:46308", "49:46309", "49:46310", "49:46311", "49:46313", "49:40113", "49:46312",
      "49:46502", "49:46504", "49:46506", "49:46505", "49:46507", "49:46501", "28:538", "49:1155", "49:46315",
      "49:46314")),
    ("2105-AA84", "199910", "49 USC 1381", "1381", "exists-as-recodified", ("49:41712", "49:41707")),
    ("2120-AA49", "199510", "49 USC 1357", "1357", "exists-as-recodified",
     ("49:44903", "49:44935", "49:40119", "49:44912", "49:48107", "49:44937", "49:44936", "49:44906", "49:44938",
      "49:44904", "49:44914")),
    ("1902-AF39", "202004", "49 App. U.S.C. 1 to 85 (1988)", "1", "exists-as-recodified",
     ("49:10501", "49:10102", "49:10701", "49:10702", "49:10703", "49:11101", "49:10709", "49:10749", "49:10750",
      "49:10721", "49:10722", "49:10723", "49:10724", "49:11905", "49:10746", "49:11104", "49:11121", "49:11902",
      "49:11126", "49:11122", "49:11105", "49:11123", "49:11128", "49:11127", "49:11124", "49:11125", "49:11901",
      "49:11907", "49:10901", "49:10902", "49:10907", "49:11703", "49:11702", "49:11505", "49:10711", "49:353")),
    ("2120-AA83", "199510", "49 USC 1401", "1401", "exists-as-recodified",
     ("49:44101", "49:44102", "49:44103", "49:44105", "49:44106", "49:44111", "49:44703", "49:44713")),
    ("2120-AF84", "199510", "49 USC 1421", "1421", "exists-as-recodified",
     ("49:44701", "49:44702", "49:44712", "49:44714", "49:44716", "49:44717", "49:44722")),
    ("2105-AD66", "201010", "49 USC 106(g), ch 447 and 451", "451", None, None),
    ("2120-AA83", "199510", "49 USC 1355", "1355", "exists-as-recodified", ("49:44702", "49:45303")),
    ("2105-AA88", "199810", "49 USC 1481", "1481", "exists-as-recodified", ("49:46102",)),
    ("2120-AE42", "199510", "49 USC 1421 to 1431", "1421", "exists-as-recodified",
     ("49:44701", "49:44702", "49:44712", "49:44714", "49:44716", "49:44717", "49:44722", "49:44703", "49:44710",
      "49:44704", "49:44705", "49:44713", "49:44708", "49:44707", "49:44709", "49:1153", "49:44711", "49:44715")),
)


@pytest.mark.slow
def test_the_successor_is_evidence_and_never_an_identity(con) -> None:
    """The ten drawn rows, and the four widest lists, for a by-eye check.

    Read the pinned repealed specimen and row 7 hardest. ``49 USC 486(c),
    sec 205(c), 63 Stat 390`` filed in **1998** cites a numbering Pub. L.
    103-272 took away in 1994, and the table repeals it with no successor at
    all: there is nothing for a consumer to follow, and "repealed, no
    successor" is the finding -- rebuild #12's re-draw dropped it from the
    seeded sample, so it is asserted by key below rather than lost. Row 7,
    ``49 USC 106(g), ch 447 and 451`` filed in **2010**, published the same
    finding until 2026-08-24 and no longer publishes anything: the filer's own
    "ch" governs 451, 451 IS a current chapter, and the record cites current
    law -- so the guard refuses, and the row carries a named refusal instead of
    a true fact about a citation this filer did not make.

    Then read row 1. ``49 USC 1472`` is NINETEEN successors -- eighteen in
    title 49 and one in **title 28** (§ 538) -- separated in the print by
    prose this column does not carry. There is no such thing as "the"
    successor of 1472, which is why nothing here is written into
    ``usc_section_corrected`` and why the contract calls a successor evidence.

    Row 4 is the honest gap: ``49 App. U.S.C. 1 to 85 (1988)`` states a range
    and the APPENDIX pattern has no range tail, so ``usc_section_end`` is NULL
    and the span answer cannot fire. It keeps §1's own 36 successors while the
    same range written ``49 USC 1 to 85`` gets 84 members and 168. That is a
    grammar gap and it is stated here rather than papered over.

    First measured on the scratch build of builder sha256:0f602120; re-pinned
    against rebuild #12, whose table digests match rebuild12-delta.txt.
    """

    import random

    _awaits_the_rebuild(con, "usc_disposition_span_members", _DISPOSITION_SCRATCH_BUILDER)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    population = [
        (row[0], row[1], row[4], row[5], row[6], tuple(row[7]) if row[7] is not None else None)
        for row in _rows(
            con,
            f"select rin, publication_id, ordinal, citation_ordinal, authority_text, usc_section, "
            f"usc_disposition_verdict, usc_disposition_successors from {L} "
            "where usc_section_verdict_reason = 'title_49_appendix_not_published' "
            "order by rin, publication_id, ordinal, citation_ordinal",
        )
    ]
    assert len(population) == 2_490
    assert tuple(random.Random(20260823).sample(population, 10)) == _DISPOSITION_BY_EYE
    # The repealed-no-successor specimen, by key -- sampling no longer guards it.
    assert (
        "3090-AG59", "199804", "49 USC 486(c), sec 205(c), 63 Stat 390", "486", "repealed-no-successor", None,
    ) in population

    # The four longest successor lists, with one of the filer's own texts, its
    # RIN and how many former sections the answer covers. The top two are
    # SPANS -- one citation naming 84 and 41 former sections -- and they are
    # why the member column has to exist: read without it, "49 USC 1 to 85"
    # looks like 168 successors of section 1. 1655 is the third and is the
    # opposite lesson: ONE former section, the Department of Transportation
    # Act's transfer section, 101 successors spread over aviation, rail, motor
    # carrier and pipeline titles.
    widest = _rows(
        con,
        f"select usc_section, len(usc_disposition_successors), "
        f"coalesce(len(usc_disposition_span_members), 0), "
        f"any_value(authority_text order by rin, publication_id, ordinal), "
        f"any_value(rin order by rin, publication_id, ordinal) "
        f"from {L} where usc_disposition_successors is not null group by 1, 2, 3 order by 2 desc, 1 limit 4",
    )
    assert widest == [
        ("1", 168, 84, "49 USC 1 to 85 (app)", "1902-AB24"),
        ("1", 155, 41, "49 USC 1 to 27", "1902-AB34"),
        ("1655", 101, 0, "49 USC 1655", "1625-AA30"),
        ("1358", 97, 35, "49 USC 1358 to 1421", "2120-AE14"),
    ]
    # Rebuild #15 (2026-09-01 wave): 1,692 -> 1,640, the multi-successor share of
    # the 53 title-49-appendix rows the reg-dot fence removed (REF-062);
    # the single-successor 541 holds still.
    # 1,640 of the 2,473 answered rows carry more than one successor -- still
    # the majority -- which is the number that decides what a consumer may key
    # on. It FELL from 1,779 while the spans grew, because 189 pinpointed rows
    # narrowed at the same time; the two rules pull in opposite directions and
    # both directions are the citation's own words.
    assert _one(con, f"select count(*) from {L} where len(usc_disposition_successors) > 1") == 1_640
    assert _one(con, f"select count(*) from {L} where len(usc_disposition_successors) = 1") == 541

    # NOTHING is corrected from any of this. Nine rows carry both a correction
    # and a disposition, and on all nine the correction is the A4 reading the
    # fence already published (`114l` -> `114(l)`, `322a` -> `322(a)`) while
    # the disposition is `not-in-table` -- which agrees: those are current
    # sections of the new title wearing a lettered shape, not former appendix
    # sections, and the 1994 table rightly never lists them.
    both = _rows(
        con,
        f"select usc_section, usc_section_corrected, usc_section_correction_evidence, usc_disposition_verdict, "
        f"count(*) from {L} where usc_disposition_verdict is not null and usc_section_corrected is not null "
        "group by 1, 2, 3, 4 order by 1",
    )
    assert both == [
        ("114l", "114(l)", "A4-subsection-rendered-as-a-lettered-section", "not-in-table", 1),
        ("322a", "322(a)", "A4-subsection-rendered-as-a-lettered-section", "not-in-table", 8),
    ]


@pytest.mark.slow
def test_the_disposition_census_is_the_receipts(con) -> None:
    """Every count in the receipt, recomputed from the built columns.

    And the closure that makes the census honest: the rows a table was asked
    about ARE the rows the fence refuses for that one reason, so a shortfall
    cannot hide outside the total. ``not-in-table`` is one of the answers.

    First measured on the scratch build of builder sha256:0f602120; re-pinned
    against rebuild #12, whose table digests match rebuild12-delta.txt.
    """

    import json

    from refspec.registry.usc_disposition_tables import VERDICTS as DISPOSITION_VERDICTS

    _awaits_the_rebuild(con, "usc_disposition_span_members", _DISPOSITION_SCRATCH_BUILDER)
    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    assert declared["uscDispositionVerdictRows"] == {
        verdict: _one(con, f"select count(*) from {L} where usc_disposition_verdict = '{verdict}'")
        for verdict in DISPOSITION_VERDICTS
    }
    assert declared["uscDispositionVerdictPairs"] == {
        verdict: _one(
            con,
            f"select count(distinct (usc_title, usc_section, usc_appendix)) from {L} "
            f"where usc_disposition_verdict = '{verdict}'",
        )
        for verdict in DISPOSITION_VERDICTS
    }
    # Every declared verdict is listed even at zero. Two of the five are
    # unreachable in THIS corpus and are stated so rather than omitted:
    # "no-table-for-title" cannot fire because the gate is a title-49 reason
    # code, and "stated-without-successor" needs a section whose every matching
    # row points at another Act (`1655(a)(4)`, `(See § 2 of Pub. L. 97-449.)`)
    # with none of its siblings naming a successor, which no cited section here
    # does.
    assert declared["uscDispositionVerdictRows"]["no-table-for-title"] == 0
    assert declared["uscDispositionVerdictRows"]["stated-without-successor"] == 0
    assert declared["uscDispositionRowsBySuccessorCount"] == {
        str(row[0]): row[1]
        for row in _rows(
            con,
            f"select coalesce(len(usc_disposition_successors), 0), count(*) from {L} "
            "where usc_disposition_verdict is not null group by 1",
        )
    }
    # The rows the citation asked something wider or narrower with, and the
    # rows no table was read for at all. Each recomputed from the columns, so
    # a receipt that drifted from the artifact fails here rather than being
    # believed.
    assert declared["uscDispositionSpanRows"] == _one(
        con, f"select count(*) from {L} where usc_disposition_span_members is not null"
    ) == 296
    assert declared["uscDispositionSpans"] == _one(
        con,
        f"select count(distinct (usc_title, usc_section, usc_section_end)) from {L} "
        "where usc_disposition_span_members is not null",
    ) == 38
    assert declared["uscDispositionPinpointResolvedRows"] == _one(
        con, f"select count(*) from {L} where usc_disposition_pinpoint is not null"
    ) == 246
    # 275 rows STATE a pinpoint and 246 of them are resolved by the table; the
    # 29 between are rows where the volume knows the section and not that
    # subsection, and they come back whole on purpose.
    assert declared["uscDispositionPinpointRows"] == 275
    # An abbreviated span is never expanded here, and the count that says so
    # is kept visible at zero rather than left to be assumed.
    assert declared["uscDispositionAbbreviatedSpanRowsNotExpanded"] == 0
    assert _one(
        con,
        f"select count(*) from {L} where usc_disposition_span_members is not null "
        "and usc_section_span_rule is distinct from 'stated'",
    ) == 0
    assert declared["uscDispositionRefusalRows"] == {
        row[0]: row[1]
        for row in _rows(
            con,
            f"select usc_disposition_refusal, count(*) from {L} "
            "where usc_disposition_refusal is not null group by 1",
        )
    } == {"chapter_qualifier_governs_the_token": 17}
    assert declared["uscDispositionRefusalPairs"] == {"chapter_qualifier_governs_the_token": 2}
    # The census closes, twice over: against its own row total, and against the
    # section fence's reason code. The 17 refusals are the ONLY gap between
    # the two, and they are counted rather than dropped.
    assert sum(declared["uscDispositionRowsBySuccessorCount"].values()) == 2_473
    assert sum(declared["uscDispositionVerdictRows"].values()) == 2_473
    assert sum(declared["uscDispositionRefusalRows"].values()) == 17
    assert declared["uscSectionUnknownRowsByReason"]["title_49_appendix_not_published"] == 2_490


@pytest.mark.slow
def test_the_three_citations_visual_review_2_read_as_wrong_or_short(con) -> None:
    """The review's own § J specimens, in the built table, by their filer's text.

    Three findings, three rows, one query each -- the positive and its paired
    negative side by side, so a rule that fired too widely fails here.

    First measured on the scratch build of builder sha256:0f602120; re-pinned
    against rebuild #12, whose table digests match rebuild12-delta.txt.
    """

    _awaits_the_rebuild(con, "usc_disposition_span_members", _DISPOSITION_SCRATCH_BUILDER)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"

    def one_row(rin, publication_id, ordinal, citation_ordinal):
        return _rows(
            con,
            f"select authority_text, usc_section, usc_section_end, usc_disposition_verdict, "
            f"usc_disposition_successors, usc_disposition_span_members, usc_disposition_pinpoint, "
            f"usc_disposition_refusal from {L} where rin = '{rin}' and publication_id = '{publication_id}' "
            f"and ordinal = {ordinal} and citation_ordinal = {citation_ordinal}",
        )[0]

    # (a) THE SPAN. RIN 2120-AE42, Fall 1995, "Aging Aircraft Safety": eleven
    # former sections cited, bare 1421's seven successors published.
    text, section, end, verdict, successors, members, pinpoint, refusal = one_row(
        "2120-AE42", "199510", 6, 0
    )
    assert (text, section, end) == ("49 USC 1421 to 1431", "1421", "1431")
    assert members == [str(number) for number in range(1421, 1432)]
    assert len(successors) == 18 and successors[:7] == [
        "49:44701", "49:44702", "49:44712", "49:44714", "49:44716", "49:44717", "49:44722",
    ]
    assert (verdict, pinpoint, refusal) == ("exists-as-recodified", None, None)
    # The paired negative: the same section cited WITHOUT the range keeps the
    # seven, and states no members at all.
    text, section, end, verdict, successors, members, _, _ = one_row("2120-AF84", "199510", 3, 0)
    assert (text, section, end, members) == ("49 USC 1421", "1421", None, None)
    assert len(successors) == 7

    # And the span the parse could not read, stated honestly rather than
    # forced: "49 App. U.S.C. 1 to 85 (1988)" is matched by the APPENDIX
    # pattern, which has no range tail, so usc_section_end is NULL and the
    # answer is section 1's own 36. A grammar item, not a disposition one.
    text, section, end, _, successors, members, _, _ = one_row("1902-AF39", "202004", 4, 0)
    assert (text, section, end, members) == ("49 App. U.S.C. 1 to 85 (1988)", "1", None, None)
    assert len(successors) == 36

    # (b) THE PINPOINT. RIN 2120-AF10, Fall 1995: "(b)(2)" is a printed row of
    # the volume and answers 303 alone.
    text, section, _, verdict, successors, members, pinpoint, refusal = one_row(
        "2120-AF10", "199510", 7, 0
    )
    assert (text, section, pinpoint) == ("49 USC 1651(b)(2)", "1651", "(b)(2)")
    assert (successors, members, refusal) == (["49:303"], None, None)
    # The paired negative: the bare sibling on another RIN keeps BOTH.
    text, section, _, _, successors, _, pinpoint, _ = one_row("2125-AD88", "199704", 2, 0)
    assert (text, section, pinpoint) == ("49 USC 1651", "1651", None)
    assert successors == ["49:101", "49:303"]

    # (c) THE CHAPTER GUARD. RIN 2105-AD66, Fall 2010: no table is read.
    text, section, _, verdict, successors, members, pinpoint, refusal = one_row(
        "2105-AD66", "201010", 2, 1
    )
    assert (text, section) == ("49 USC 106(g), ch 447 and 451", "451")
    assert (verdict, successors, members, pinpoint) == (None, None, None, None)
    assert refusal == "chapter_qualifier_governs_the_token"
    # The paired negative, and it is the same RIN one edition apart: Fall 2013
    # drops the "ch" from BOTH boxes ("49 USC 401, 411, and 417" and "49 USC
    # 106(g), 447 and 451"), so the citations state no qualifier to guard on
    # and five rows of that edition are read against the pre-1994 table as
    # before. The guard reads the text it is given and never a sibling
    # edition's -- a RIN-history witness is a different rule with its own
    # exposure, and this is what it would be worth.
    text, section, _, verdict, _, _, _, refusal = one_row("2105-AD66", "201310", 2, 2)
    assert (text, section) == ("49 USC 106(g), 447 and 451", "451")
    assert (verdict, refusal) == ("repealed-no-successor", None)
    assert _rows(
        con,
        f"select usc_section, usc_disposition_verdict from {L} where rin = '2105-AD66' "
        "and publication_id = '201310' and usc_disposition_verdict is not null order by usc_section",
    ) == [
        ("401", "repealed-no-successor"),
        ("411", "not-in-table"),
        ("417", "not-in-table"),
        ("447", "not-in-table"),
        ("451", "repealed-no-successor"),
    ]
    # And the guard's whole reach, listed: two RINs, 17 rows, one section each.
    assert _rows(
        con,
        f"select rin, usc_section, count(*), count(distinct publication_id) from {L} "
        "where usc_disposition_refusal is not null group by 1, 2 order by 1",
    ) == [("2105-AD66", "451", 16, 16), ("2105-AE02", "417", 1, 1)]


#: The FR-roster corroboration's counts were measured on a scratch build whose
#: builder module hashes to this -- `--output-root` under a temporary directory,
#: the builder's own default act index, and the same pinned editions, source
#: credits, notes and oracles. A DIGEST rather than a commit, for the reason
#: ``_producer_block`` gives. Diffed against the same faithful rebuild of
#: c99177b8 the disposition join used: over every shared value column of the
#: TIMETABLE table exactly 8 values vanished and 8 arrived, nothing else moved
#: in either direction over 671,959 rows, and the actions, CFR-reference and
#: legal-authority tables came out byte-identical.
_FR_ROSTER_SCRATCH_BUILDER = "sha256:125c291f"

#: The eight rows verbatim, and what the roster says each one meant. The whole
#: unit is listed rather than summarised: these are five real Federal Register
#: documents, and a reader checking the repair by eye needs the filer's text,
#: the document and the evidence side by side. Ordered by (rin, edition,
#: ordinal), which is how the query below reads them.
_FR_CORRECTED_ROWS = (
    ("0648-BK86", "202504", 2, "89 FR 1022091", "2024-29238", 89, 102_091,
     "page-doubled-digit-witnessed-by-date-and-rin"),
    ("0648-BK86", "202510", 2, "89 FR 1022091", "2024-29238", 89, 102_091,
     "page-doubled-digit-witnessed-by-date-and-rin"),
    ("1625-AC52", "202010", 0, "85 FSR 62651", "2020-21071", 85, 62_651,
     "label-insertion-medial-letter-witnessed-by-date-and-rin"),
    ("2040-AF62", "201610", 0, "81 NFR 66900", "2016-23432", 81, 66_900,
     "label-insertion-leading-letter-witnessed-by-date-and-rin"),
    ("3060-AJ58", "202304", 20, "85 DR 34525", "2020-09815", 85, 34_525,
     "label-substitution-adjacent-key-witnessed-by-date-and-rin-agency"),
    ("3060-AL15", "202204", 1, "85 FR 75770x", "2020-24486", 85, 75_770,
     "page-trailing-character-witnessed-by-date-and-rin-agency"),
    ("3060-AL15", "202210", 1, "85 FR 75770x", "2020-24486", 85, 75_770,
     "page-trailing-character-witnessed-by-date-and-rin-agency"),
    ("3060-AL15", "202304", 1, "85 FR 75770x", "2020-24486", 85, 75_770,
     "page-trailing-character-witnessed-by-date-and-rin-agency"),
)


@pytest.mark.slow
def test_the_damaged_fr_citations_name_the_document_they_meant(con) -> None:
    """Eight rows whose citation text nothing could read, and the five real
    Federal Register documents they meant.

    Three of the five are cited more than once because a rule's timetable is
    reprinted in every later edition, so the same damage arrives two or three
    times. Nothing about the filer's row changes: fr_citation_text keeps the
    damage and fr_volume / fr_page stay NULL, because no grammar read this text
    and what is published beside it is what the ROSTER said.

    Measured on the scratch build of builder sha256:125c291f; awaits the
    rebuild.
    """

    _awaits_the_rebuild(
        con, "fr_correction_evidence", _FR_ROSTER_SCRATCH_BUILDER, table="unified_agenda_timetables"
    )
    T = "'{d}/unified_agenda_timetables.parquet'"
    rows = _rows(
        con,
        "select rin, publication_id, ordinal, fr_citation_text, fr_corrected_document_number, "
        f"fr_corrected_volume, fr_corrected_page, fr_correction_evidence from {T} "
        "where fr_correction_evidence is not null order by 1, 2, 3",
    )
    assert tuple(tuple(row) for row in rows) == _FR_CORRECTED_ROWS
    # Nothing vanishes and nothing is invented: the original text is intact and
    # the parsed columns stay empty on every corroborated row.
    assert _one(
        con,
        f"select count(*) from {T} where fr_correction_evidence is not null "
        "and (fr_volume is not null or fr_page is not null)",
    ) == 0
    # The four columns are one fact, and it is exactly the corroborated rows --
    # so a rule that stopped firing breaks a pin instead of shrinking a total.
    assert _one(
        con,
        f"select count(*) from {T} where (fr_correction_evidence is null) "
        "<> (parse_status <> 'corroborated')",
    ) == 0
    assert _one(
        con,
        f"select count(*) from {T} where (fr_corrected_document_number is null) "
        "<> (fr_correction_evidence is null)",
    ) == 0


@pytest.mark.slow
def test_the_fr_correction_census_is_the_receipts(con) -> None:
    """Every FR-roster count in the receipt, recomputed from the built columns.

    Including the operator that answers nothing. ``page-digit-dropped`` is the
    one that generates the COMPETING reading of "89 FR 1022091" -- 102209, a
    real page inside 2024-29633 -- and its zero is the measurement that says the
    tie was resolved by the roster rather than by the operator set being too
    narrow to see it.

    Measured on the scratch build of builder sha256:125c291f; awaits the
    rebuild.
    """

    import json

    from refspec.registry.unified_agenda_parquet import FR_CITATION_DAMAGE_OPERATORS

    _awaits_the_rebuild(
        con, "fr_correction_evidence", _FR_ROSTER_SCRATCH_BUILDER, table="unified_agenda_timetables"
    )
    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    T = "'{d}/unified_agenda_timetables.parquet'"
    assert declared["timetableFrCitationFailures"] == _one(
        con, f"select count(*) from {T} where parse_status = 'failed'"
    ) == 0
    assert declared["timetableFrCitationsCorroboratedByRoster"] == _one(
        con, f"select count(*) from {T} where parse_status = 'corroborated'"
    ) == 8
    assert declared["timetableFrCorrectionRowsByOperator"] == {
        operator: _one(
            con,
            f"select count(*) from {T} where starts_with(fr_correction_evidence, "
            f"'{operator}-witnessed-by-')",
        )
        for operator in FR_CITATION_DAMAGE_OPERATORS
    }
    assert declared["timetableFrCorrectionRowsByOperator"]["page-digit-dropped"] == 0
    # The census closes: every corroborated row named an operator, and no other
    # row did.
    assert sum(declared["timetableFrCorrectionRowsByOperator"].values()) == 8


@pytest.mark.slow
def test_a_damaged_fr_citation_is_corroborated_only_by_the_roster() -> None:
    """One named edit, a roster START page, the row's own date and a witness
    tying the filer to the document -- and exactly one survivor.

    The negatives are the point. Every fence is removed in turn and the repair
    refuses each time, so a rule that quietly widened would fail here rather
    than publish a plausible wrong document.
    """

    from refspec.registry.unified_agenda_parquet import (
        _corroborated_fr_citation,
        _fr_citation_candidates,
        _fr_document_roster,
    )

    roster = _fr_document_roster()

    def read(text, rin, date_text):
        got = _corroborated_fr_citation(text, rin=rin, date_text=date_text, roster=roster)
        return None if got is None else (
            got["fr_corrected_document_number"], got["fr_corrected_page"],
            got["fr_correction_evidence"],
        )

    assert read("89 FR 1022091", "0648-BK86", "12/17/2024") == (
        "2024-29238", 102_091, "page-doubled-digit-witnessed-by-date-and-rin"
    )
    assert read("81 NFR 66900", "2040-AF62", "09/29/2016") == (
        "2016-23432", 66_900, "label-insertion-leading-letter-witnessed-by-date-and-rin"
    )
    assert read("85 FSR 62651", "1625-AC52", "10/05/2020") == (
        "2020-21071", 62_651, "label-insertion-medial-letter-witnessed-by-date-and-rin"
    )
    assert read("85 DR 34525", "3060-AJ58", "06/05/2020") == (
        "2020-09815", 34_525, "label-substitution-adjacent-key-witnessed-by-date-and-rin-agency"
    )
    assert read("85 FR 75770x", "3060-AL15", "11/25/2020") == (
        "2020-24486", 75_770, "page-trailing-character-witnessed-by-date-and-rin-agency"
    )

    # THE TIE. Both readings of "89 FR 1022091" are generated, and 102209 -- a
    # real page in the same issue -- is the one the fences throw out.
    volume, candidates = _fr_citation_candidates("89 FR 1022091")
    assert volume == 89
    assert candidates[102_091] == "page-doubled-digit"
    assert candidates[102_209] == "page-digit-dropped", (
        "the competing reading must be generated, or the tie is never actually refused"
    )
    # It lands inside a roster document and still loses: 102209 is not a start
    # page, and 2024-29633 lists no RIN and no agency prefix.
    assert roster[(89, 102_207)].start_page < 102_209 <= roster[(89, 102_207)].start_page + 4

    # Fence 1, the roster: a page nothing published on that date is never minted.
    assert read("89 FR 1022071", "0648-BK86", "12/17/2024") is None
    # Fence 2, the date: the row's own date_text must be the document's.
    assert read("89 FR 1022091", "0648-BK86", "12/18/2024") is None
    # Fence 3, the witness: a RIN the document does not list refuses, and so
    # does the wrong agency where the document lists no RIN at all.
    assert read("89 FR 1022091", "0649-BK86", "12/17/2024") is None
    assert read("85 DR 34525", "2040-AJ58", "06/05/2020") is None
    # The operator names an ADJACENT key, so a substitution that is not one is
    # refused rather than quietly admitted.
    assert read("85 XR 34525", "3060-AJ58", "06/05/2020") is None
    # One edit, never two: a damaged label beside a damaged page recovers nothing.
    assert read("85 DR 34525x", "3060-AJ58", "06/05/2020") is None
    # And a roster contradicting itself refuses at load rather than choosing.
    assert roster is not None


def test_a_roster_naming_one_start_page_twice_refuses_at_load(tmp_path, monkeypatch) -> None:
    """Exactly-one-survivor rests on the key being unique. Two documents at one
    (volume, start page) would make it a lie, so the load names both and stops."""

    import pytest

    from refspec.registry import unified_agenda_parquet as module

    header = (
        "document_number,volume,start_page,end_page,publication_date,citation,type,title,"
        "regulation_id_numbers,agencies,docket_ids,rin_agency_prefixes,html_url,fetched_at,source_sha256\n"
    )
    row = "{n},89,102091,102100,2024-12-17,89 FR 102091,Proposed Rule,T,0648-BK86,NOAA,D,,U,2026-08-23,X\n"
    clash = tmp_path / "documents.csv"
    clash.write_text(header + row.format(n="2024-29238") + row.format(n="2024-99999"), encoding="utf-8")
    monkeypatch.setattr(module, "_FR_DOCUMENT_ROSTER_CSV", clash)
    with pytest.raises(ValueError, match="89 FR 102091"):
        module._fr_document_roster()

    # Absent, the loader answers None rather than raising -- right for a caller
    # with no roster, and why ``main`` refuses for a caller that thinks it has one.
    monkeypatch.setattr(module, "_FR_DOCUMENT_ROSTER_CSV", tmp_path / "nowhere.csv")
    assert module._fr_document_roster() is None


@pytest.mark.slow
def test_a_continuation_is_a_publisher_reference_like_any_other() -> None:
    """The two columns that say WHERE a citation was written, and what repeats.

    ``authority_source`` names the publisher field a row was read from, and
    ``restates_box_citation`` marks the continuation rows whose published
    identity a box of the same record already carries. Both are decided by one
    pass after every row exists -- corroboration explodes rows and the sibling
    carry fills identity columns, so a flag written at emission would describe
    a citation the published row no longer states.
    """

    from refspec.registry.unified_agenda_parquet import (
        AUTHORITY_SOURCES,
        _judge_restatements,
        _states_a_citation,
    )

    assert AUTHORITY_SOURCES == (
        "box",
        "additional-info:legal-authority-cont",
        "additional-info:additional-legal-authority",
    )

    box = _usc_row("15 USC 78m", authority_source="box")
    other_record = _usc_row("15 USC 78m", authority_source="box", rin="3235-ZZ99")
    repeat = _usc_row(
        "15 USC 78m; 15 USC 78n",
        authority_source="additional-info:legal-authority-cont",
        ordinal=15,
    )
    fresh = _usc_row(
        "15 USC 78n", authority_source="additional-info:legal-authority-cont", ordinal=15
    )
    unreadable = _usc_row(
        "from the President, April 14, 1997, Delegation of Responsibilities",
        authority_source="additional-info:legal-authority-cont",
        ordinal=15,
    )
    assert unreadable["authority_type"] == "other" and unreadable["parse_status"] == "failed"
    rows = [box, other_record, repeat, fresh, unreadable]

    assert _judge_restatements(rows) == 1
    assert [row["restates_box_citation"] for row in rows] == [None, None, True, False, None]
    # A BOX is never judged: the question is not asked of it, and False there
    # would read as "this box is not a repeat", which nothing checked.
    assert box["restates_box_citation"] is None
    # A row that states no place at all is NULL rather than True, or every
    # unreadable row would "equal" every other one and the flag would mean
    # "unreadable" instead of "repeated".
    assert _states_a_citation(unreadable) is False
    assert _states_a_citation(box) is True
    # And the comparison is per RECORD: a box of a DIFFERENT RIN is not this
    # record's box, however identical the citation.
    assert other_record["rin"] != repeat["rin"]
    assert _judge_restatements([other_record, repeat]) == 0
    assert repeat["restates_box_citation"] is False


#: The scheme-label rule's counts were measured on a scratch build whose
#: builder module hashes to this -- `--output-root` under a temporary
#: directory, the builder's own default act index, and the same pinned
#: editions, source credits and oracles. A DIGEST rather than a commit, for the
#: reason ``_producer_block`` gives. The baseline it was diffed against is a
#: scratch build of the artifact's own commit (94ddfb03), which reproduced all
#: four of the artifact's files byte for byte; the value diff over every shared
#: column showed 44 values leaving ("other"/"failed") and 48 arriving, and
#: nothing else in either direction.
_SCHEME_LABEL_SCRATCH_BUILDER = "sha256:9e78ca00"


@cache
def _label_oracles():
    from refspec.registry.unified_agenda_parquet import (
        _pl_roster,
        _SeriesCalendar,
        _usc_section_oracle,
    )

    roster = _pl_roster()
    return _usc_section_oracle(), _SeriesCalendar.build(roster), set(roster[0])


def _label_read(rin, publication_id, text, **extra):
    """(reading, refusals) for one value, through the rule's own six fences."""

    from refspec.registry.unified_agenda_parquet import _read_damaged_scheme_label, _Tally

    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update(rin=rin, publication_id=publication_id, ordinal=0, authority_text=text,
               authority_type="other", parse_status="failed", usc_appendix=False, usc_note=False)
    row.update(extra)
    oracle, calendar, pairs = _label_oracles()
    tally = _Tally()
    reading = _read_damaged_scheme_label(row, oracle, calendar, pairs, tally)
    refused = {reason: count for reason, count in tally.scheme_label_refusals.items() if count}
    if reading is None:
        return None, refused
    return (
        reading[0],
        [{k: v for k, v in emission.items() if v is not None and v is not False}
         for emission in reading[1]],
    ), refused


@pytest.mark.slow
def test_a_damaged_scheme_label_is_corroborated_only_by_a_pinned_oracle() -> None:
    """One edit on a label, a pinned oracle that prints the place it names, and
    exactly one survivor -- with the twelve traps refused, each by the fence
    that catches it.

    The negatives carry this test. 178 values in the failed pool hold a token
    one edit from a scheme label, 56 reach a corroborated reading, and TWELVE
    of those 56 are wrong -- so a rule measured only on what it publishes would
    look excellent and be a guess.
    """

    from refspec.registry.unified_agenda_parquet import SCHEME_LABEL_RULE

    oracle, calendar, _pairs = _label_oracles()

    # THE SPECIMEN. FMCSA 2126-AA64 writes "113tat." in its Spring and Fall
    # 2004 editions: one deleted 'S', welded to the volume it precedes. 113
    # Stat. is a volume the roster's series bound affirms for a 2004 filing --
    # and the PAGE is carried as the filer stated it and affirmed by nothing,
    # which is not academic: the same RIN's later editions print 1765.
    assert _label_read("2126-AA64", "200404", "113tat. 1754 (1999)") == (
        (SCHEME_LABEL_RULE, [{
            "authority_type": "statute_at_large",
            "statute_volume": 113,
            "statute_page": 1754,
            "authority_label_corrected": "113tat. -> Stat.",
            "label_correction_evidence": "statutes-volume-series",
        }]),
        {},
    )

    # THE PAIRED NEGATIVE, and the whole reason F4 exists. "Reorganization Plan
    # No. 4 or 1978" reaches "4 FR 1978" under 'or' -> 'FR', and Register
    # volume 4 really is in series for a 2006 filing -- so the witness cannot
    # be what refuses it. What refuses it is that the SAME token repairs to
    # 'of', and then the grammar types the value in full, prose and all.
    assert calendar.fr_volume_in_series(4, "200604") is True, (
        "the witness must AFFIRM here, or this negative proves nothing"
    )
    assert _label_read("1210-AA98", "200604", "Reorganization Plan No. 4 or 1978") == (
        None, {"another-repair-types-the-value-in-full": 1}
    )

    # F5, first half: the label already stands in the residue. 29 U.S.C. 794 is
    # the right answer, and "UC" -> "U.S.C." is the wrong token to reach it by.
    assert _label_read("1218-AB67", "201004", "29 USC UC 794") == (
        None, {"the-label-already-stands-in-the-residue": 1}
    )
    # F5, second half: residue the operator does not explain. Both of these
    # reach a Public Law the roster really holds, by repairing one half of a
    # label whose other half is left lying in the value.
    assert _label_read("0938-AR55", "201304", "Pu. Bl. 111-148, Sec 1251") == (
        None, {"residue-the-operator-does-not-explain": 1}
    )
    assert _label_read("2126-AA00", "200404", "Articles 12 and 29 of 61 Sta 1180") == (
        None, {"residue-the-operator-does-not-explain": 1}
    )
    # And the statement fence, which is what makes the rule additive BY
    # CONSTRUCTION: this row already says section 3301, so a reading arriving
    # beside it would leave a consumer holding two answers and no way to choose.
    assert _label_read(
        "0938-AR55", "201304", "OL 111-148, sec 3301, sec 6402", stated_section="3301"
    ) == (None, {"the-row-already-states-something": 1})

    # THE TAIL RIDES ALONG. 12 U.S.C. 1735 exists, so a rule that asked about
    # the truncated stem would corroborate the wrong section -- which is the
    # exact defect that demoted class B8 to a candidate.
    assert oracle.section_verdict(12, "1735", 2004).verdict == "exists", (
        "the wrong reading has to be affirmable, or the tail rule refuses nothing"
    )
    assert _label_read("2501-AC95", "200404", "12 UDC 1735(f)-14") == (
        (SCHEME_LABEL_RULE, [{
            "authority_type": "usc",
            "usc_title": 12,
            "usc_section": "1735f-14",
            "authority_label_corrected": "UDC -> U.S.C.",
            "label_correction_evidence": "section-oracle-on-the-stated-tail",
        }]),
        {},
    )

    # ONE LABEL, EVERY SECTION IT MAKES READABLE. A reader that stopped at the
    # first citation would publish 41102 and drop four real ones the same
    # repair produced.
    reading, refused = _label_read(
        "2105-AA00", "200404", "49 U.S 41102, 41301, 41708, 41709, and 41712"
    )
    assert refused == {}
    assert [emission["usc_section"] for emission in reading[1]] == [
        "41102", "41301", "41708", "41709", "41712"
    ]
    assert {emission["label_correction_evidence"] for emission in reading[1]} == {"section-oracle"}

    # A transposition is two edits here, deliberately: 49 U.S.C. 45102 is real
    # and "SUC" would reach it, which is exactly why the operator has to name
    # the damage rather than the answer.
    assert _label_read("2126-AA00", "201004", "49 SUC 45102") == (
        None, {"no-single-corroborated-reading": 1}
    )
    # F1 and F3: one letter is not damage, and a token in no citation shape is
    # not a label.
    assert _label_read("2126-AA00", "201004", "42 U 1983")[0] is None
    assert _label_read("2126-AA00", "201004", "the Act and the Plan")[0] is None


@pytest.mark.slow
def test_the_damaged_scheme_labels_name_the_place_they_meant(con) -> None:
    """44 boxes whose LABEL nothing could read, and the 48 citations they hold.

    Nothing about the filer's row changes: authority_text keeps the damage,
    every one of these boxes stated nothing else before the rule ran, and what
    arrives beside the text is what a PINNED ORACLE said -- named, per row, in
    label_correction_evidence.

    Measured on the scratch build of builder sha256:9e78ca00; awaits the
    rebuild.
    """

    from refspec.registry.unified_agenda_parquet import SCHEME_LABEL_RULE, SCHEME_LABEL_WITNESSES

    _awaits_the_rebuild(con, "authority_label_corrected", _SCHEME_LABEL_SCRATCH_BUILDER)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    rows, boxes = _row(
        con,
        f"select count(*), count(distinct (rin, publication_id, ordinal)) from {L} "
        f"where corroboration_rule = '{SCHEME_LABEL_RULE}'",
    )
    assert (rows, boxes) == (48, 44)
    # Every one of them names the rule, the operator AND the witness, and
    # nothing else in the table does.
    assert _one(
        con,
        f"select count(*) from {L} where (corroboration_rule = '{SCHEME_LABEL_RULE}') "
        "!= (authority_label_corrected is not null)",
    ) == 0
    assert _one(
        con,
        f"select count(*) from {L} where (authority_label_corrected is null) "
        "!= (label_correction_evidence is null)",
    ) == 0
    assert {
        row[0] for row in _rows(con, f"select distinct label_correction_evidence from {L} "
                                     "where label_correction_evidence is not null")
    } <= set(SCHEME_LABEL_WITNESSES)
    # The witnesses that spoke, and the two that did not: every FR and Public
    # Law reading this operator produced was a trap, and the fences took all of
    # them. A branch at zero is the rule's honest shape, not a missing one.
    assert dict(
        _rows(con, f"select label_correction_evidence, count(*) from {L} "
                   "where label_correction_evidence is not null group by 1 order by 1")
    ) == {"section-oracle": 42, "section-oracle-on-the-stated-tail": 3, "statutes-volume-series": 3}
    # Every corroborated U.S.C. reading is one the oracle prints -- the gate is
    # the verdict, so "exists" here is a tautology worth pinning: it breaks if
    # the gate is ever loosened.
    assert dict(
        _rows(con, f"select usc_section_verdict, count(*) from {L} "
                   f"where corroboration_rule = '{SCHEME_LABEL_RULE}' and authority_type = 'usc' "
                   "group by 1 order by 1")
    ) == {"exists": 45}
    # THE SPECIMEN and THE TAIL, in the built table.
    assert _rows(
        con,
        f"select publication_id, statute_volume, statute_page, authority_label_corrected from {L} "
        "where rin = '2126-AA64' and authority_text = '113tat. 1754 (1999)' order by 1",
    ) == [("200404", 113, 1754, "113tat. -> Stat."), ("200410", 113, 1754, "113tat. -> Stat.")]
    assert set(
        _rows(con, f"select usc_title, usc_section from {L} "
                   "where authority_text = '12 UDC 1735(f)-14'")
    ) == {(12, "1735f-14")}
    # And the paired negative is still unread, in the table, in all six editions.
    assert dict(
        _rows(con, f"select parse_status, count(*) from {L} "
                   "where authority_text = 'Reorganization Plan No. 4 or 1978' group by 1")
    ) == {"failed": 6}


@pytest.mark.slow
def test_the_scheme_label_census_is_the_receipts(con) -> None:
    """The rule's refusals outnumber its readings three to one, and the receipt
    says so by fence rather than as a total."""

    import json

    from refspec.registry.citation_grammar import (
        names_citation_structure,
        parse_authority_citation,
    )
    from refspec.registry.unified_agenda_parquet import (
        SCHEME_LABEL_REFUSALS,
        SCHEME_LABEL_RULE,
        SCHEME_LABELS,
    )

    _awaits_the_rebuild(con, "authority_label_corrected", _SCHEME_LABEL_SCRATCH_BUILDER)
    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    # no-single-corroborated-reading: 122 -> 118 at rebuild #11 (#56,
    # a08b5bdb). This rule runs LAST among the corroboration readers, so a
    # row a NEW earlier rule claims never reaches it at all. '114 Pub. L.
    # 185' and '94 Pub. L. 588' (4 rows, RINs 1880-AA89 x2 editions,
    # 0596-AD59 and 0596-AD61) are the only two texts, among every row that
    # changed authority_type away from 'other' this rebuild, that
    # `_scheme_label_candidates` ever offers a span for ('Pub.' against
    # 'Pub. L.') -- and they are exactly the four rows the new
    # reordered-public-law-roster-existence rule now resolves before this
    # one ever sees them, matching public_law_corrected's own +4
    # (test_public_law_corrections_are_corroborated_and_preserve_the_original).
    assert declared["schemeLabelRefusalsByReason"] == {
        "another-repair-types-the-value-in-full": 7,
        "no-single-corroborated-reading": 118,
        "residue-the-operator-does-not-explain": 3,
        "the-label-already-stands-in-the-residue": 1,
        "the-row-already-states-something": 1,
    }
    assert set(declared["schemeLabelRefusalsByReason"]) == set(SCHEME_LABEL_REFUSALS)
    assert declared["schemeLabelCorrectedRowsByWitness"] == {
        "federal-register-volume-series": 0,
        "public-law-roster": 0,
        "section-oracle": 42,
        "section-oracle-on-the-stated-tail": 3,
        "statutes-volume-series": 3,
    }
    assert declared["authorityCorroboratedRowsByRule"][SCHEME_LABEL_RULE] == 48
    # And every label this rule may repair to is one the grammar reads, PROBED
    # in the shape that label takes -- a Public Law label needs a Public Law
    # number and a Register label a volume and a page. A spelling the grammar
    # drops breaks a pin here instead of quietly becoming a repair target
    # nothing can parse. "sec." is the one member that is not a scheme: it is
    # the section MARKER, read by the grammar's structure census rather than
    # typed, and it is a repair target because a damaged marker beside a
    # number is the same damage as a damaged label.
    probes = {
        "Stat.": "113 Stat. 1754", "U.S.C.": "42 U.S.C. 1983", "USC": "42 USC 1983",
        "Pub. L.": "Pub. L. 106-159", "PL": "PL 106-159", "CFR": "40 CFR 51",
        "FR": "70 FR 12345",
    }
    assert set(probes) | {"sec."} == set(SCHEME_LABELS)
    for label, probe in probes.items():
        assert any(
            citation.authority_type != "other" for citation in parse_authority_citation(probe)
        ), (label, probe)
    assert names_citation_structure("sec.") is True


#: The box-run join's counts were measured on a scratch build whose builder
#: module hashes to this -- `--output-root` under a temporary directory, the
#: builder's own default act index, and the same pinned editions, source
#: credits and oracles. Diffed against the scratch build of the commit before
#: it over every shared value column: 592 values ARRIVED and ZERO left, in
#: either direction, which is what "recorded, never rewritten" means measured
#: rather than asserted.
_JOIN_SCRATCH_BUILDER = "sha256:ef4bd313"


def _join_box(ordinal, text, *, rin="9999-AA01", publication_id="201010", **extra):
    """One box as the join meets it: the row the main emit path would write."""

    from refspec.registry.citation_grammar import (
        parse_authority_citation,
        stated_act_name,
        stated_section,
    )

    citation = parse_authority_citation(text)[0]
    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update(
        rin=rin, publication_id=publication_id, ordinal=ordinal, authority_text=text,
        authority_source="box", authority_type=citation.authority_type,
        parse_status=citation.parse_status, usc_appendix=citation.usc_appendix,
        usc_note=citation.usc_note, usc_title=citation.usc_title,
        usc_section=citation.usc_section, usc_section_end=citation.usc_section_end,
        public_law=citation.public_law, statute_volume=citation.statute_volume,
        statute_page=citation.statute_page,
        stated_act_name=citation.stated_act_name or stated_act_name(text),
        stated_section=citation.stated_section or stated_section(text),
    )
    row.update(extra)
    return row


def _join(rows):
    """(rebuilt rows, census) for one record's boxes."""

    from refspec.registry.unified_agenda_parquet import _join_box_runs, _usc_section_oracle

    return _join_box_runs(rows, _usc_section_oracle(), _calendar())


@pytest.mark.slow
def test_a_cut_list_is_put_back_without_rewriting_one_byte() -> None:
    """The join RECORDS a run and adds the citations it makes readable. It
    never rewrites authority_text, never renumbers ordinal, and never drops the
    box it absorbed."""

    rows, census = _join([
        _join_box(0, "46 USC 40103(a)"),
        _join_box(1, "46 USC 40501(a)-(e) and (g)"),
        _join_box(2, "40503"),
        _join_box(3, "41102(2), (4) and (8)"),
    ])
    assert census.runs == 1 and census.boxes == 3 and census.rows == 2 and census.superseded == 2
    assert census.rules["fragment-right:R4-whole-box-is-a-bare-section"] == 1
    assert census.refusals == dict.fromkeys(census.refusals, 0)
    # The two boxes that read as nothing STILL read as nothing, still carry
    # their own text and their own ordinal, and now say which join absorbed them.
    absorbed = [row for row in rows if row["ordinal"] in (2, 3)]
    assert [row["authority_text"] for row in absorbed] == ["40503", "41102(2), (4) and (8)"]
    assert [row["authority_type"] for row in absorbed] == ["other", "other"]
    assert [row["superseded_by_join"] for row in absorbed] == [True, True]
    # The citations arrive on the DONOR's ordinal, with the donor's own text
    # beside them and the joined string in its own column.
    joined = [row for row in rows if row["ordinal"] == 1]
    assert [row["usc_section"] for row in joined] == ["40501", "40503", "41102"]
    assert {row["authority_text"] for row in joined} == {"46 USC 40501(a)-(e) and (g)"}
    assert {row["authority_join_text"] for row in joined} == {
        "46 USC 40501(a)-(e) and (g), 40503, 41102(2), (4) and (8)"
    }
    assert {row["authority_box_run_start"] for row in joined} == {1}
    assert {row["authority_box_run_length"] for row in joined} == {3}
    # The donor is not superseded by its own run, and the box outside it is
    # untouched in every column the join writes.
    assert [row["superseded_by_join"] for row in joined] == [None, None, None]
    outside = next(row for row in rows if row["ordinal"] == 0)
    assert all(outside[column] is None for column in _JOIN_COLUMNS)


@pytest.mark.slow
def test_the_box_run_join_refuses_what_its_four_fences_are_for() -> None:
    """Real data says only that the rule accepts what is valid.

    What it REFUSES is unproven until something puts each fence a case built to
    defeat it -- and the fourth fence answers zero times over 241,701 records,
    so without this it would be a comment rather than a rule.
    """

    # 1. The join adds nothing the donor already read.
    assert _join([_join_box(0, "5 U.S.C. 552"), _join_box(1, "552")])[1].refusals[
        "the-join-adds-no-citation"
    ] == 1
    # 2. A stated section welded to a citation that carries its own. 42 U.S.C.
    #    1302 and Social Security Act sec. 1861 are two authorities, and both
    #    are real, which is exactly why only the shape can refuse this.
    assert _join([_join_box(0, "42 USC 1302"), _join_box(1, "sec 1861")])[1].refusals[
        "a-statement-welded-to-a-citation-that-has-its-own-section"
    ] == 1
    # 3. The oracle does not print a section the join would mint: 1437a is a
    #    title-42 section and this donor names title 12.
    assert _join([_join_box(0, "12 U.S.C. 4568"), _join_box(1, "1437a")])[1].refusals[
        "the-oracle-does-not-print-a-section-the-join-mints"
    ] == 1
    # 4. The join may only ADD. The donor's row is mutated to carry a section
    #    the joined string cannot reproduce, which is the only way this corpus
    #    can be made to show the fence firing.
    assert _join([
        _join_box(0, "44 U.S.C. 3301", usc_section="9999"), _join_box(1, "3302"),
    ])[1].refusals["the-join-loses-what-the-donor-already-read"] == 1

    # And the two shapes that never become a run at all, so no fence is even
    # asked. A fragment must OPEN with a section: "42 2000d-1" opens with a
    # lost TITLE, and reading it as a section of title 40 mints 40 U.S.C. 42.
    empty, census = _join([_join_box(0, "40 USC 476"), _join_box(1, "42 2000d-1")])
    assert (census.runs, sum(census.refusals.values())) == (0, 0)
    assert all(row["authority_join_rule"] is None for row in empty)
    # And English prose is not a citation fragment, which is why R2 is not in
    # the vocabulary: it fires on 165 runs of this corpus and reaches one
    # citation no other shape reaches.
    assert _join([
        _join_box(0, "49 U.S.C. 31144"), _join_box(1, "sec 4009 of TEA-21"),
    ])[1].runs == 0


@pytest.mark.slow
def test_a_run_of_bare_lists_is_recorded_although_it_reads_nothing() -> None:
    """Tier B. Four boxes, one list, no citation -- and the run is still a fact
    about the record that nothing else in this table states."""

    rows, census = _join([
        _join_box(0, "secs. 1.5,1.7, 1.0, 1.11, 1.12", rin="3052-AD44", publication_id="202210"),
        _join_box(1, "2.2, 2.3, 2.4, 2.5, 2.12, 3.1", rin="3052-AD44", publication_id="202210"),
        _join_box(2, "3.7, 3.11, 3.25, 4.3, 4.3A", rin="3052-AD44", publication_id="202210"),
        _join_box(3, "4.9, 4.14B, 4.25, 5.9, 5.17", rin="3052-AD44", publication_id="202210"),
    ])
    assert (census.runs, census.rows) == (0, 0), "tier B publishes no citation"
    assert (census.list_continuation_runs, census.list_continuation_boxes) == (1, 4)
    assert len(rows) == 4, "and deletes nothing"
    assert [row["authority_join_rule"] for row in rows] == ["list-continuation"] * 4
    assert [row["authority_box_run_start"] for row in rows] == [0] * 4
    assert [row["authority_box_run_length"] for row in rows] == [4] * 4
    # Nothing supersedes them: no citation was published to supersede them WITH.
    assert [row["superseded_by_join"] for row in rows] == [None] * 4


@pytest.mark.slow
def test_the_cut_citation_lists_over_the_built_table(con) -> None:
    """219 runs of boxes one citation list was cut across, 586 citations they
    make readable, and 332 boxes recorded as absorbed rather than dropped.

    Measured on the scratch build of builder sha256:ef4bd313; awaits the
    rebuild.
    """

    from refspec.registry.unified_agenda_parquet import AUTHORITY_JOIN_RULES

    _awaits_the_rebuild(con, "authority_join_rule", _JOIN_SCRATCH_BUILDER)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    assert dict(
        _rows(con, f"select authority_join_rule, count(distinct (rin, publication_id, "
                   f"authority_box_run_start)) from {L} where authority_join_rule is not null "
                   "group by 1 order by 1")
    ) == {
        "fragment-left:L4-whole-box-is-a-bare-section": 5,
        "fragment-right:R1-opens-with-close-or-comma": 2,
        "fragment-right:R3-opens-with-connective": 2,
        "fragment-right:R4-whole-box-is-a-bare-section": 88,
        "fragment-right:R5-opens-with-digit-no-scheme": 122,
        "list-continuation": 46,
    }
    assert {
        row[0] for row in _rows(con, f"select distinct authority_join_rule from {L} "
                                     "where authority_join_rule is not null")
    } <= set(AUTHORITY_JOIN_RULES)
    # The four join columns arrive together, on every row of a run and nowhere
    # else, and superseded_by_join is only ever True.
    assert _one(
        con,
        f"select count(*) from {L} where (authority_join_rule is null) "
        "!= (authority_box_run_start is null) or (authority_join_rule is null) "
        "!= (authority_join_text is null) or (authority_join_rule is null) "
        "!= (authority_box_run_length is null)",
    ) == 0
    assert _one(con, f"select count(*) from {L} where superseded_by_join = false") == 0
    assert _one(
        con, f"select count(*) from {L} where superseded_by_join and authority_join_rule is null"
    ) == 0
    assert _one(con, f"select count(*) from {L} where superseded_by_join") == 332
    # Tier B supersedes nothing: no citation was published to supersede it with.
    assert _one(
        con,
        f"select count(*) from {L} where authority_join_rule = 'list-continuation' "
        "and superseded_by_join",
    ) == 0

    # THE SPECIMEN. 3072-AC38's boxes 2 to 4 are one list; joined they name
    # 46 U.S.C. 40501, 40503 and 41102, and the oracle prints all three at the
    # 2010 edition that filed them.
    assert _rows(
        con,
        f"select ordinal, citation_ordinal, authority_text, usc_title, usc_section, "
        f"usc_section_verdict, usc_section_attested_at_edition, superseded_by_join from {L} "
        "where rin = '3072-AC38' and publication_id = '201010' and authority_box_run_start = 2 "
        "order by 1, 2",
    ) == [
        (2, 0, "46 USC 40501(a)-(e) and (g)", 46, "40501", "exists", True, None),
        (2, 1, "46 USC 40501(a)-(e) and (g)", 46, "40503", "exists", True, None),
        (2, 2, "46 USC 40501(a)-(e) and (g)", 46, "41102", "exists", True, None),
        (3, 0, "40503", None, None, None, None, True),
        (4, 0, "41102(2), (4) and (8)", None, None, None, None, True),
    ]
    # A section belongs to a Public Law when the Public Law is what the run
    # names. The filer's sibling 2126-AA64 writes "PL 106-159, sec 211" as ONE
    # box in nine editions, which is the corroboration this shape rests on.
    assert _rows(
        con,
        f"select ordinal, citation_ordinal, public_law, stated_section, superseded_by_join from {L} "
        "where rin = '2126-AA63' and publication_id = '200010' order by 1, 2",
    ) == [(0, 0, None, "206", True), (1, 0, "106-159", None, None), (1, 1, "106-159", "206", None)]
    assert _one(
        con,
        f"select count(*) from {L} where rin = '2126-AA64' and authority_text like 'PL 106-159%sec%'",
    ) == 7
    # THE PAIRED NEGATIVE. Two Public Law sections from two acts never become
    # one citation, and the section the filer wrote stays exactly where it was.
    assert _rows(
        con,
        f"select ordinal, public_law, stated_section, authority_join_rule from {L} "
        "where rin = '0938-AR55' and publication_id = '201304' order by 1",
    ) == [
        (0, None, "153", None),
        (1, "111-148", "3401(h)", None),
        (2, None, "632(a)", None),
    ]
    # And the seven rows the donor already carried are untouched: the join
    # appended 5 U.S.C. 591 and moved nothing.
    assert _rows(
        con,
        f"select citation_ordinal, usc_section from {L} where rin = '3072-AC96' "
        "and publication_id = '202304' and ordinal = 0 order by 1",
    ) == [(0, "504"), (1, "551"), (2, "553"), (3, "556"), (4, "559"), (5, "561"), (6, "571"),
          (7, "591")]


@pytest.mark.slow
def test_the_join_census_is_the_receipts(con) -> None:
    """Every count in the receipt, recomputed from the built columns."""

    import json

    from refspec.registry.unified_agenda_parquet import (
        AUTHORITY_JOIN_REFUSALS,
        AUTHORITY_JOIN_RULES,
    )

    _awaits_the_rebuild(con, "authority_join_rule", _JOIN_SCRATCH_BUILDER)
    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    tier_a = "authority_join_rule is not null and authority_join_rule <> 'list-continuation'"
    assert declared["authorityJoinRuns"] == _one(
        con, f"select count(distinct (rin, publication_id, authority_box_run_start)) from {L} "
             f"where {tier_a}"
    ) == 219
    assert declared["authorityJoinBoxes"] == _one(
        con, f"select count(distinct (rin, publication_id, ordinal)) from {L} where {tier_a}"
    ) == 551
    # The 586 rows the joined strings YIELDED cannot be told from the donor's
    # own rows by any column -- both sit on the donor's ordinal and both are
    # real citations of that record. So both totals are pinned: 1,001
    # non-superseded rows across 219 donor boxes, of which 586 are the join's,
    # and a rule that quietly widened would move one or the other.
    assert declared["authorityJoinRows"] == 586
    assert _one(
        con, f"select count(*) from {L} where {tier_a} and superseded_by_join is null"
    ) == 1_002
    assert _one(con, f"select count(*) from {L} where {tier_a}") == 1_334
    assert declared["authorityJoinSupersededRows"] == _one(
        con, f"select count(*) from {L} where superseded_by_join"
    ) == 332
    assert declared["authorityJoinListContinuationRuns"] == _one(
        con, f"select count(distinct (rin, publication_id, authority_box_run_start)) from {L} "
             "where authority_join_rule = 'list-continuation'"
    ) == 46
    assert declared["authorityJoinListContinuationBoxes"] == _one(
        con, f"select count(distinct (rin, publication_id, ordinal)) from {L} "
             "where authority_join_rule = 'list-continuation'"
    ) == 137
    assert set(declared["authorityJoinRunsByRule"]) == set(AUTHORITY_JOIN_RULES)
    assert set(declared["authorityJoinRefusalsByReason"]) == set(AUTHORITY_JOIN_REFUSALS)
    # 54 refusals against 219 published runs, and the fence that answers ZERO
    # over 241,701 records is declared at zero rather than dropped -- its case
    # is built by hand in the fence test above.
    assert declared["authorityJoinRefusalsByReason"] == {
        "a-statement-welded-to-a-citation-that-has-its-own-section": 23,
        "the-join-adds-no-citation": 24,
        "the-join-loses-what-the-donor-already-read": 0,
        "the-oracle-does-not-print-a-section-the-join-mints": 7,
    }


#: The title carry's counts were measured on a scratch build whose builder
#: module hashes to this -- `--output-root` under a temporary directory, the
#: builder's own default act index, and the same pinned editions, source
#: credits and oracles. Diffed against the scratch build of the commit before
#: it: 93 values left ("other"/"failed", every one all-NULL) and 111 arrived,
#: and nothing else moved in either direction.
_TITLE_CARRY_SCRATCH_BUILDER = "sha256:5b91a116"


def _carry_titles(rows):
    """(rebuilt rows, census) for one record's boxes, through the title carry."""

    from refspec.registry.unified_agenda_parquet import (
        _carry_usc_titles,
        _Tally,
        _usc_section_oracle,
    )

    return _carry_usc_titles(rows, _usc_section_oracle(), _Tally(), _calendar())


@pytest.mark.slow
def test_a_titleless_section_box_takes_the_title_beside_it() -> None:
    """A U.S.C. section number says nothing about which title it belongs to, so
    the title comes from the box beside it and every section it makes has to be
    one the oracle prints."""

    from refspec.registry.unified_agenda_parquet import TITLE_CARRY_RULE

    rows, census = _carry_titles([
        _join_box(0, "46 U.S.C. 305, 40101 and 40102", rin="3072-AC83", publication_id="202104"),
        _join_box(1, "41101 to 41109", rin="3072-AC83", publication_id="202104"),
    ])
    assert (census.boxes, census.rows) == (1, 1)
    carried = next(row for row in rows if row["corroboration_rule"] == TITLE_CARRY_RULE)
    assert (carried["usc_title"], carried["usc_section"], carried["usc_section_end"]) == (
        46, "41101", "41109"
    )
    assert carried["usc_title_carried_from_ordinal"] == 0
    assert carried["authority_carry_text"] == "46 U.S.C. 41101 to 41109"
    # The filer's text is untouched and the row says the grammar did not read
    # it: the title came from the box beside it, not from these bytes.
    assert carried["authority_text"] == "41101 to 41109"
    assert carried["parse_status"] == "corroborated"


@pytest.mark.slow
def test_the_title_carry_refuses_what_its_fences_are_for() -> None:
    """Each fence, given a case built to defeat it -- and two shapes that never
    reach a fence at all."""

    from refspec.registry.unified_agenda_parquet import TITLE_CARRY_REFUSALS

    def refusals(boxes, **extra):
        return _carry_titles([_join_box(i, text, **extra) for i, text in enumerate(boxes)])[1].refusals

    # THE RANGE END IS GATED TOO. "89-670 and 91-605" under title 23 reads as
    # two spans, and 23 U.S.C. 605 is a real section -- so a rule that gated
    # only the start would have published two spans of which no endpoint but
    # one exists.
    assert refusals(["23 U.S.C. 402", "89-670 and 91-605"])[
        "the-oracle-does-not-print-a-section-the-carry-mints"
    ] == 1
    # An ACT section is not a Code section. SSA sec. 1861 is 42 U.S.C. 1395x,
    # and 42 U.S.C. 1861 is the National Science Foundation Act.
    assert refusals(["42 USC 1302", "sec 1861"])[
        "the-box-writes-sec-and-an-act-section-is-not-a-code-one"
    ] == 1
    # A box holding nothing but a number a title could be is a title.
    assert refusals(["12 USC 2073 to 2076", "12"])["the-box-is-a-lone-title"] == 1
    # "93-87" is a Public Law number wearing a section's shape.
    assert refusals(["5 U.S.C. 552", "93-87"])["the-box-is-shaped-like-a-public-law-number"] == 1
    # The title has to be ONE title. Two disagreeing neighbours refuse rather
    # than choose, and a box with no titled neighbour at all refuses too.
    assert refusals(["1234"])["no-single-title-in-the-six-boxes-before"] == 1
    # The join speaks first: a box it already read is never read again here.
    absorbed = [
        _join_box(0, "46 U.S.C. 40501(a)-(e) and (g)"),
        _join_box(1, "40503", superseded_by_join=True),
    ]
    assert _carry_titles(absorbed)[1].refusals["the-join-already-absorbed-the-box"] == 1
    assert _carry_titles(absorbed)[1].boxes == 0

    # And the shape that never becomes a candidate: two section-shaped tokens
    # with a bare space between them are not a list. "42 2000d-1" is
    # 42 U.S.C. 2000d-1 with its label gone, and carrying title 40 onto it
    # published 40 U.S.C. 42.
    empty, census = _carry_titles([_join_box(0, "40 USC 476"), _join_box(1, "42 2000d-1")])
    assert (census.boxes, census.shaped_boxes) == (0, 0)
    assert census.refusals == dict.fromkeys(TITLE_CARRY_REFUSALS, 0)
    assert all(row["usc_title_carried_from_ordinal"] is None for row in empty)


@pytest.mark.slow
def test_the_carried_titles_over_the_built_table(con) -> None:
    """93 title-less section boxes that took the title beside them, and the 111
    citations they name.

    Measured on the scratch build of builder sha256:5b91a116; awaits the
    rebuild.
    """

    from refspec.registry.unified_agenda_parquet import TITLE_CARRY_RULE

    _awaits_the_rebuild(con, "usc_title_carried_from_ordinal", _TITLE_CARRY_SCRATCH_BUILDER)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    assert _row(
        con,
        f"select count(*), count(distinct (rin, publication_id, ordinal)) from {L} "
        f"where corroboration_rule = '{TITLE_CARRY_RULE}'",
    ) == (111, 93)
    # The donor ordinal and the carried string arrive together, on exactly the
    # rows this rule wrote, and every one of them is a U.S.C. row the oracle
    # prints -- the gate is the verdict, so this is a tautology worth pinning.
    assert _one(
        con,
        f"select count(*) from {L} where (corroboration_rule = '{TITLE_CARRY_RULE}') "
        "!= (usc_title_carried_from_ordinal is not null)",
    ) == 0
    assert _one(
        con,
        f"select count(*) from {L} where (usc_title_carried_from_ordinal is null) "
        "!= (authority_carry_text is null)",
    ) == 0
    assert dict(
        _rows(con, f"select usc_section_verdict, count(*) from {L} "
                   f"where corroboration_rule = '{TITLE_CARRY_RULE}' group by 1 order by 1")
    ) == {"exists": 111}
    # The donor is always EARLIER and within six boxes.
    assert _one(
        con,
        f"select count(*) from {L} where corroboration_rule = '{TITLE_CARRY_RULE}' "
        "and (usc_title_carried_from_ordinal >= ordinal "
        "or ordinal - usc_title_carried_from_ordinal > 6)",
    ) == 0

    # THE SPECIMEN, and the precedence chain in one record: FMC 3072-AC83's box
    # 3 was absorbed by the box-run join, box 4 was already answered by the
    # RIN's own history, and box 5 -- "41101 to 41109", both endpoints printed
    # at the 2021 edition -- is this rule's.
    assert _rows(
        con,
        f"select ordinal, authority_text, usc_title, usc_section, usc_section_end, "
        f"corroboration_rule, usc_title_carried_from_ordinal, authority_carry_text from {L} "
        "where rin = '3072-AC83' and publication_id = '202104' and ordinal in (3, 4, 5) "
        "order by 1, citation_ordinal",
    ) == [
        (3, "40501 to 40503", None, None, None, None, None, None),
        (4, "40701 to 40706", 46, "40701", None, "rin-history-section-list", None, None),
        (5, "41101 to 41109", 46, "41101", "41109", "sibling-usc-title-within-six-boxes", 4,
         "46 U.S.C. 41101 to 41109"),
    ]
    # THE PAIRED NEGATIVE. "sec 13632(a)(3)" is Pub. L. 103-66 sec. 13632 AND
    # 42 U.S.C. 13632 is a real section, so the oracle cannot separate them --
    # the RIN's own history already did, and this rule leaves it alone.
    assert _rows(
        con,
        f"select authority_type, corroboration_rule, usc_title_carried_from_ordinal from {L} "
        "where rin = '0906-AB00' and publication_id = '201210' and ordinal = 2",
    ) == [("public_law", "rin-history-section-list", None)]
    # And the record where NO box states a TITLE stays unread by THIS rule:
    # "1102" after "SSA subsection 1902 (a) (61)" is an act's section and
    # this rule has no title to carry.
    #
    # At rebuild #11 (#44/45, 1115f279) boxes 1-4 are no longer "other" --
    # the sibling-act carry now reads box 0's "SSA" as the Social Security
    # Act (via the pinned initialism roster, agency-roster-initialism) and
    # carries it onto every bare-section box that follows, four back. This
    # is a DIFFERENT rule (ACT_CARRY_RULE, not TITLE_CARRY_RULE) answering a
    # different question -- an act, not a U.S.C. title -- so it does not
    # move the count(*)=111 pin above; it is 4 of the 34 total
    # sibling-act-from-an-earlier-box rows.
    assert _rows(
        con,
        f"select ordinal, authority_type, parse_status, corroboration_rule, act_key, act_section, "
        f"act_resolution_sibling_ordinal from {L} "
        "where rin = '0936-AA07' and publication_id = '201710' order by 1",
    ) == [
        (0, "other", "failed", None, None, None, None),
        (1, "act_relative", "corroborated", "sibling-act-from-an-earlier-box", "social security act", "1903", 0),
        (2, "act_relative", "corroborated", "sibling-act-from-an-earlier-box", "social security act", "1903", 0),
        (3, "act_relative", "corroborated", "sibling-act-from-an-earlier-box", "social security act", "1903", 0),
        (4, "act_relative", "corroborated", "sibling-act-from-an-earlier-box", "social security act", "1102", 0),
        (5, "unstated", "failed", None, None, None, None),
    ]


@pytest.mark.slow
def test_the_title_carry_census_is_the_receipts(con) -> None:
    """The rule refuses five times what it answers, by fence."""

    import json

    from refspec.registry.unified_agenda_parquet import TITLE_CARRY_REFUSALS, TITLE_CARRY_RULE

    _awaits_the_rebuild(con, "usc_title_carried_from_ordinal", _TITLE_CARRY_SCRATCH_BUILDER)
    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    assert declared["uscTitleCarryBoxes"] == _one(
        con, f"select count(distinct (rin, publication_id, ordinal)) from {L} "
             f"where corroboration_rule = '{TITLE_CARRY_RULE}'"
    ) == 93
    assert declared["uscTitleCarryRows"] == _one(
        con, f"select count(*) from {L} where corroboration_rule = '{TITLE_CARRY_RULE}'"
    ) == 111
    assert (declared["uscTitleCarryShapedBoxes"], declared["uscTitleCarrySilentBoxes"]) == (
        1_220, 570
    )
    assert set(declared["uscTitleCarryRefusalsByReason"]) == set(TITLE_CARRY_REFUSALS)
    assert declared["uscTitleCarryRefusalsByReason"] == {
        "no-single-title-in-the-six-boxes-before": 122,
        "the-box-is-a-lone-title": 4,
        "the-box-is-shaped-like-a-public-law-number": 1,
        "the-box-writes-sec-and-an-act-section-is-not-a-code-one": 31,
        "the-carry-does-not-read": 5,
        "the-join-already-absorbed-the-box": 306,
        "the-oracle-does-not-print-a-section-the-carry-mints": 8,
    }
    assert declared["authorityCorroboratedRowsByRule"][TITLE_CARRY_RULE] == 111


#: The stated-act labelling's counts were measured on a scratch build whose
#: builder module hashes to this -- `--output-root` under a temporary
#: directory, the builder's own default act index, and the same pinned
#: editions, source credits and oracles. Diffed against the scratch build of
#: the commit before it: 484 rows moved, 471 of them changing ONE value
#: (authority_type) and 13 of them claimed by index-holds-the-stated-name once
#: its year fence stopped reading a section number as a year.
_STATED_ACT_SCRATCH_BUILDER = "sha256:65556d93"


@cache
def _act_closure():
    """The builder's own spelling closure over the pinned OLRC name index."""

    from refspec.registry.act_resolution import ActIndex
    from refspec.registry.unified_agenda_parquet import (
        _DEFAULT_ACT_INDEX,
        _act_enactment_years,
        _act_name_resolver,
        _act_name_spelling_closure,
        _pl_roster,
        resolvable_act_names,
    )

    index = ActIndex.from_artifact(_DEFAULT_ACT_INDEX)
    return _act_name_spelling_closure(resolvable_act_names(_DEFAULT_ACT_INDEX),
                                      _act_name_resolver(index),
                                      _act_enactment_years(index, _pl_roster()))


def _stated_act_row(text, name, section=None, **extra):
    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update(rin="9999-AA01", publication_id="201010", ordinal=0, authority_text=text,
               authority_source="box", authority_type="other", parse_status="failed",
               usc_appendix=False, usc_note=False, stated_act_name=name, stated_section=section)
    row.update(extra)
    return row


@pytest.mark.slow
def test_a_row_that_names_an_act_is_act_relative_even_when_nothing_resolves_it() -> None:
    """"Land Withdrawal Act" is an act-relative citation whose ACT the OLRC
    index cannot name. That is a narrower and more useful thing to publish than
    "other"/"failed", which says only "unreadable"."""

    from refspec.registry.unified_agenda_parquet import _type_stated_acts

    unknown = _stated_act_row("Land Withdrawal Act", "Land Withdrawal Act")
    known = _stated_act_row(
        "sec 1919(a) to (g) of the Social Security Act", "Social Security Act", "1919(a)"
    )
    section_only = _stated_act_row("1102", None, "1102")
    census = _type_stated_acts([unknown, known, section_only], _act_closure())

    assert (census.states_something, census.section_only_rows, census.names_an_act_rows) == (3, 1, 2)
    assert census.rows == 1
    # ONE column changes. parse_status stays "failed" because the act is
    # unknown, which is exactly what _ACT_UNKNOWN_REASONS already means; the
    # statements stay where the filer put them, because no act key arrived to
    # supersede them; and every other column was and stays NULL.
    assert unknown["authority_type"] == "act_relative"
    assert unknown["parse_status"] == "failed"
    assert unknown["act_resolution_reason"] == "act_not_in_index"
    assert unknown["stated_act_name"] == "Land Withdrawal Act"
    assert unknown["act_key"] is None and unknown["usc_title"] is None
    # A name the closure HOLDS is not this pass's business: it belongs to
    # index-holds-the-stated-name and to the two fences that guard it.
    assert known["authority_type"] == "other"
    assert census.refusals["the-closure-holds-the-name-and-a-fence-refused-the-key"] == 1
    # A section with no act names nothing this module can type.
    assert section_only["authority_type"] == "other"
    # And a row that states more than its two statements is not a row that read
    # nothing.
    stated_more = _stated_act_row("Land Withdrawal Act", "Land Withdrawal Act", public_law="99-606")
    assert _type_stated_acts([stated_more], _act_closure()).refusals[
        "the-row-states-more-than-a-name-and-a-section"
    ] == 1
    assert stated_more["authority_type"] == "other"


@pytest.mark.slow
def test_a_year_that_is_the_rows_own_section_is_not_a_year() -> None:
    """The fence on ``index-holds-the-stated-name`` refuses a year the name
    does not carry, because an amendment is its own entry. It also refused
    "sec 1919(a) to (g) of the Social Security Act" -- the shape its own
    docstring names -- for thirteen editions, because 1919 matches a year.
    """

    from refspec.registry.unified_agenda_parquet import (
        _ActOracles,
        _read_index_held_name,
        _Tally,
    )

    oracles = _ActOracles(
        lookup=_act_closure(), keys_by_rin={}, keys_by_agency={}, glosses={}
    )

    def read(text, name, section):
        return _read_index_held_name(_stated_act_row(text, name, section), oracles, _Tally())

    # 1919, 1819, 1815 and 1833 are Social Security Act SECTIONS, and every one
    # of them matches the year pattern.
    assert read(
        "sec 1919(a) to (g) of the Social Security Act", "Social Security Act", "1919(a)"
    ) == ("index-holds-the-stated-name", [{
        "authority_type": "act_relative", "act_key": "social security act",
        "act_section": "1919(a)", "stated_act_name": None, "stated_section": None,
    }])
    assert read(
        "Sec. 1815(d) ofthe Social Security Act", "Social Security Act", "1815(d)"
    )[1][0]["act_section"] == "1815(d)"
    # And the refusal the fence was written for still stands: 172(a) is the
    # section and 1990 is a year the name does not carry, so this value names
    # the amendments and not the base act.
    assert read(
        "Section 172(a) and (c) of the 1990 Clean Air Act amendments", "Clean Air Act", "172(a)"
    ) is None


def test_a_year_the_text_gives_as_the_acts_own_vintage_is_not_another_acts() -> None:
    """"Clean Air Act as amended in 1990" is one act with a date on it.

    The fence read it as it reads "the 1990 Clean Air Act amendments" -- alike
    -- and only the second names a separately indexed entity. Review #2 priced
    the conflation: the base-act key resolves section 112 to 42 U.S.C. 7412,
    the record's own hazardous-air-pollutant subject, where the amendments key
    does not classify section 112 at all (notes/F.json, 2060-AE83).

    The narrowing is the preposition and nothing softer. Every value in this
    corpus that names a real SECOND act still refuses.
    """

    from refspec.registry.unified_agenda_parquet import (
        _ActOracles,
        _read_index_held_name,
        _Tally,
    )

    oracles = _ActOracles(
        lookup=_act_closure(), keys_by_rin={}, keys_by_agency={}, glosses={}
    )

    def read(text, name, section=None):
        return _read_index_held_name(_stated_act_row(text, name, section), oracles, _Tally())

    # The filer's exact text, all three spellings of it in this corpus.
    assert read("Clean Air Act as Amended in 1990, section 112", "Clean Air Act", "112") == (
        "index-holds-the-stated-name", [{
            "authority_type": "act_relative", "act_key": "clean air act",
            "act_section": "112", "stated_act_name": None, "stated_section": None,
        }])
    assert read("Clean Air Act as amended in 1990, title I", "Clean Air Act")[1][0] == {
        "authority_type": "act_relative", "act_key": "clean air act",
        "act_section": None, "stated_act_name": None, "stated_section": None,
    }
    assert read(
        "Clean Air Act as amended in 1990, sec 183(e)", "Clean Air Act", "183(e)"
    )[1][0]["act_section"] == "183(e)"

    # The paired negatives, verbatim from the same 33-row population. "as
    # amended BY" introduces a second act; "as amended IN" dates this one.
    assert read(
        "The Federal Civil Penalties Inflation Adjustment Act of 1990, as amended by the "
        "Federal Civil Penalties Inflation Adjustment Act Improvements Act of 2015",
        "Federal Civil Penalties Inflation Adjustment Act Improvements Act of 2015",
    ) is None
    # A comma-joined second name, and an abbreviation-plus-year for one: both
    # name acts this index holds, and neither is the captured name.
    assert read(
        "Motor Carrier Act of 1935, Omnibus Transportation Employee Testing Act of 1991",
        "Omnibus Transportation Employee Testing Act of 1991",
    ) is None
    assert read(
        "MMA 2003, MIPPA (title XVIII of the Social Security Act)", "Social Security Act"
    ) is None
    # And the amendment-word fence is untouched: this value names the
    # separately indexed 1990 amendments, whatever the year rule says.
    assert read(
        "Section 172(a) and (c) of the 1990 Clean Air Act amendments", "Clean Air Act", "172(a)"
    ) is None


def test_the_boxs_own_tail_supplies_the_qualifier_the_captured_name_dropped() -> None:
    """"National Defense Authorization Act" names no act -- there is one nearly
    every year -- and the qualifier that picks one out sits VERBATIM in the same
    box, four words after the name the statement reader captured (3206-AN96
    202410, notes/G.json). Restoring it resolves to Pub. L. 116-92.

    Read only where the captured name names nothing, so it can add a reading
    and never displace one, and taken from the position the captured name
    actually ends at, so it can neither be borrowed from a neighbouring
    citation nor assembled out of a year mentioned elsewhere in the value.
    """

    from refspec.registry.unified_agenda_parquet import (
        _ActOracles,
        _qualified_by_the_boxs_own_tail,
        _read_index_held_name,
        _Tally,
    )

    oracles = _ActOracles(
        lookup=_act_closure(), keys_by_rin={}, keys_by_agency={}, glosses={}
    )

    def read(text, name, section=None, publication_id="202410"):
        return _read_index_held_name(
            _stated_act_row(text, name, section, publication_id=publication_id), oracles, _Tally()
        )

    box = (
        "Federal Employee Paid Leave Act, subtitle A of title LXXVI of division F of the "
        "National Defense Authorization Act for Fiscal Year 2020"
    )
    assert read(box, "National Defense Authorization Act")[1][0] == {
        "authority_type": "act_relative",
        "act_key": "national defense authorization act for fiscal year 2020",
        "act_section": None, "stated_act_name": None, "stated_section": None,
    }
    # The year fence reads the QUALIFIED name, or 2020 would be extraneous to
    # the bare family name and refuse the row it just answered.
    assert _qualified_by_the_boxs_own_tail(box, "National Defense Authorization Act") == (
        "National Defense Authorization Act for Fiscal Year 2020"
    )

    # The qualifier must FOLLOW the captured name in this box, immediately.
    assert _qualified_by_the_boxs_own_tail(
        "sec 5 of the Clean Air Act; see also the Defense Act for Fiscal Year 2020",
        "Clean Air Act",
    ) is None
    # A qualified name the index does not list is still refused: OLRC's entry
    # for the FY2019 bill carries "John S. McCain" in front of it.
    assert read(
        "title XI, subtitle B of National Defense Authorization Act for Fiscal Year 2019",
        "National Defense Authorization Act",
    ) is None
    # And a captured name the closure DOES hold never reaches the tail at all,
    # which is what keeps this row on the act its own box leads with.
    assert read(
        "Fair Chance to Compete for Jobs Act of 2019 (Fair Chance Act), title XI, subtitle B "
        "of National Defense Authorization Act for Fiscal Year 2019",
        "Fair Chance to Compete for Jobs Act of 2019",
    )[1][0]["act_key"] == "fair chance to compete for jobs act of 2019"
    # And the calendar still governs: no edition cites an act it predates.
    assert read(box, "National Defense Authorization Act", publication_id="201010") is None


@pytest.mark.slow
def test_the_stated_acts_over_the_built_table(con) -> None:
    """471 rows that name an act nothing can resolve, and the one column that
    changed on each.

    Measured on the scratch build of builder sha256:65556d93; awaits the
    rebuild.
    """

    _awaits_the_rebuild(con, "authority_label_corrected", _STATED_ACT_SCRATCH_BUILDER)
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    typed = (
        "authority_type = 'act_relative' and act_resolution_reason = 'act_not_in_index' "
        "and act_key is null"
    )
    # 471 -> 451 at rebuild #11: -20, entirely #56's, net of two opposite
    # movements against the rebuild-10 baseline -- 15 rows ARRIVE (the
    # widened act-name walk now reads an act name where it read only a
    # section before, and the act still is not in the index) while 35
    # DEPART (25 resolve to act_relative/partial under
    # no_section_stated once the widened walk finds an act_key the index
    # DOES hold; 10 resolve to act_relative/corroborated under
    # index-holds-the-stated-name). 15 - 35 = -20. #44/45 never touches this
    # population: no departure or arrival carries act_initialism_roster or
    # act_resolution_sibling_ordinal.
    assert _one(con, f"select count(*) from {L} where {typed}") == 451
    # Every one of them still says "failed" -- the act is unknown -- still
    # carries the name the filer wrote, and still has no citation of any kind.
    assert _one(con, f"select count(*) from {L} where {typed} and parse_status <> 'failed'") == 0
    assert _one(con, f"select count(*) from {L} where {typed} and stated_act_name is null") == 0
    assert _one(
        con,
        f"select count(*) from {L} where {typed} and (usc_title is not null "
        "or usc_section is not null or public_law is not null or act_section is not null)",
    ) == 0
    # THE SPECIMEN. Once the year fence stops reading section 1919 as a year,
    # CMS 0938-AL18's two boxes are Social Security Act sections that Table III
    # does not classify -- which is a different and narrower thing than "the
    # act is not in the index".
    assert _rows(
        con,
        f"select ordinal, authority_type, parse_status, act_key, act_section, "
        f"act_resolution_reason, corroboration_rule from {L} "
        "where rin = '0938-AL18' and publication_id = '200204' and ordinal in (0, 1) order by 1",
    ) == [
        (0, "act_relative", "corroborated", "social security act", "1819(a)",
         "act_section_not_classified", "index-holds-the-stated-name"),
        (1, "act_relative", "corroborated", "social security act", "1919(a)",
         "act_section_not_classified", "index-holds-the-stated-name"),
    ]
    # And the value the fence exists for used to be unread -- until rebuild
    # #11's #56 widened the act-name walk enough to capture "the 1990 Clean
    # Air Act amendments" as an act name (it did not read as one before).
    # act_key resolves ('clean air act amendments of 1990') but the section
    # ('172') is not one Table III classifies, so this row is now
    # act_relative/partial with act_resolution_reason='act_section_not_
    # classified' -- still unresolved to a U.S.C. section, just no longer
    # nameless. It carries no act_initialism_roster: #44/45 does not touch
    # it.
    assert _rows(
        con,
        f"select distinct authority_type, parse_status from {L} "
        "where authority_text = 'Section 172(a) and (c) of the 1990 Clean Air Act amendments'",
    ) == [("act_relative", "partial")]


@pytest.mark.slow
def test_the_stated_act_census_is_the_receipts(con) -> None:
    """The 1,129 rows that read as nothing and state something, split three
    ways, and what the pass declined to touch."""

    import json

    from refspec.registry.unified_agenda_parquet import STATED_ACT_REFUSALS

    _awaits_the_rebuild(con, "authority_label_corrected", _STATED_ACT_SCRATCH_BUILDER)
    declared = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))["contract"][
        "declaredClassifications"
    ]
    L = "'{d}/unified_agenda_legal_authorities.parquet'"
    # 1,129 -> 971 at rebuild #11: -158. This census runs BEFORE this rule's
    # own retyping but AFTER every corroboration reader, so it is an
    # arithmetic identity over two numbers this file already pins elsewhere:
    # statedActRowsStatingSomething = (the final 'other'/failed population
    # naming something, 520 -- test_an_unresolved_row_still_states_what_it_
    # states) + (the final act_not_in_index/act_key-is-null population, 451
    # -- test_the_stated_acts_over_the_built_table), because every row this
    # rule TYPES leaves 'other' and nothing after it re-enters. 520 + 451 =
    # 971, matching #56's -34 (from the 138-row #6 delta) and -20 (the #13
    # delta) plus #44/45's -104, for -158 total.
    # Rebuild #14 (2026-08-31 wave, research/evidence/rebuild14-delta-2026-08-31.txt): 971 -> 915 (-56, the
    # same rows test_an_unresolved_row_still_states_what_it_states attributes).
    # Rebuild #15 (2026-09-01 wave, research/evidence/rebuild15-delta-2026-09-01.txt): 915 -> 922 (+7),
    # the same rows the 464 -> 471 above attributes (REF-062).
    assert declared["statedActRowsStatingSomething"] == 922
    # 624 -> 502 at rebuild #11: -122. The bare-section-no-name subset of the
    # 'other' pool is NOT immune to the corroboration readers -- the sibling-
    # act carry (#44/45) claims 18 of them outright, plus 104 more rows leave
    # this rule's "names_an_act" branch instead (their stated_section stays
    # set but they GAIN a stated_act_name from #56's widened walk, or a
    # roster/carry rule resolves them directly), joined key-for-key against
    # the rebuild-10 baseline: #44/45 takes 104 (70 pinned-quote + 18
    # sibling-act-carry + 9 candidate-index-match + 3 self-glossing + 2
    # reverse-pl-verified + 1 agency-roster-initialism + 1 agency-gloss-
    # narrowed-initialism), #56 takes 18 (15 rows resolving to act_relative/
    # failed with a newly-captured name, 3 resolving to act_relative/partial
    # with no rule marker -- confirmed against the SAME 8 rows this file's
    # `acts`/#6 notes already attribute). 104 + 18 = 122.
    # 502 -> 446 at rebuild #14 (2026-08-31 wave): -56, the same rows statedActRowsStatingSomething lost.
    # Rebuild #15 (2026-09-01 wave): 446 -> 453 (+7), the same family as
    # statedActRowsStatingSomething above (REF-062).
    assert declared["statedActSectionOnlyRows"] == 453
    # 505 -> 469 (-36) = the names_an_act branch this rule's own typed+refused
    # split closes over: 451 typed (test_the_stated_acts_over_the_built_table)
    # + 18 refused (below). 505 - 469 is not one delta on its own; it falls
    # out of the section-only and typed movements above.
    assert declared["statedActNamingAnActRows"] == 469
    assert declared["statedActTypedRows"] == 451
    assert set(declared["statedActRefusalsByReason"]) == set(STATED_ACT_REFUSALS)
    # 34 -> 18 at rebuild #11: -16, entirely #56's -- the exact same 16 rows
    # test_an_unresolved_row_still_states_what_it_states's `name_only` note
    # attributes (all under index-holds-the-stated-name, act_relative/
    # partial or act_relative/resolved with no rule marker). No row moves
    # under "the-row-states-more-than-a-name-and-a-section", which stays 0 --
    # confirmed directly: none of the 18 rows still refused this way carries
    # any non-neutral column.
    assert declared["statedActRefusalsByReason"] == {
        "the-closure-holds-the-name-and-a-fence-refused-the-key": 18,
        "the-row-states-more-than-a-name-and-a-section": 0,
    }
    # The section-only rows are NOT untouched this rebuild (see the note
    # above): 624 -> 502.
    # 502 -> 446 at rebuild #14 (2026-08-31 wave), recomputed from the column.
    assert _one(
        con,
        f"select count(*) from {L} where authority_type = 'other' and parse_status = 'failed' "
        "and stated_section is not null and stated_act_name is null",
        # Rebuild #15 (2026-09-01 wave): 446 -> 453 (+7), recomputed from the column.
    ) == 453
    # The 13 rows the year fence used to refuse are now the name index's, which
    # is where the corroborated total moved.
    #
    # 144 -> 159 at rebuild #11 (#56): see test_every_corroborated_row_names_
    # the_rule_that_produced_it's own note for the +9/+10/-4 breakdown.
    assert declared["authorityCorroboratedRowsByRule"]["index-holds-the-stated-name"] == 159
    # 474 -> 460 at rebuild #11: -14 = the act_key-is-null subset's -20
    # (test_the_stated_acts_over_the_built_table, #56 only) plus +6 from a
    # DIFFERENT population this receipt key also counts: rows whose
    # act_resolution_reason is 'act_not_in_index' even though act_key IS set
    # (the grammar/roster read a name the OLRC index still does not
    # recognise). The +6 is the "SMART, sec 203" family (RIN 0938-AR88, six
    # editions), corroborated under pinned-roster-initialism:pinned-quote --
    # #44/45's; the pre-existing "OBRA" pair (RIN 0938-AM24 x2, 0985-AA11) is
    # untouched at act_key='obra' on both builds. -20 + 6 = -14.
    assert declared["actRelativeRowsByResolutionReason"]["act_not_in_index"] == 460
    # 481 -> 461 at rebuild #11: -20, entirely #56's (test_the_act_relative_
    # rows_carry_the_section_they_name's own parse_status-dict note).
    assert declared["actRelativeRowsByStatus"]["failed"] == 461


def test_a_slash_cuts_a_value_only_where_both_sides_are_authorities() -> None:
    """"42 USC 7401/CAA 112" published one authority and dropped the other.

    THE DEFECT. ``parse_authority_citation``'s whole-value fallback fires only
    when the ENTIRE string yielded nothing, so once "42 USC 7401" matches, the
    text behind the slash is never scanned again by anything -- "/" has no
    handling in the grammar at all. Measured on rebuild #11: 260 non-date
    values carry a slash and 235 lose a second authority the filer wrote, 223
    of them spelling it with an act's initials (CAA, CWA, TSCA, RCRA, FFDCA,
    CERCLA, SDWA, FIFRA, AEA, MPRSA, EPCRA, SARA, FWPCA) and 8 spelling the
    act out.

    THE CUT. Only a slash that could separate two authorities: one flanked by
    digits on both sides is a date or the name of a day, and "PL 110-53, sec
    1413, The Implementing Recommendations of the 9/11 Commission Act of 2007"
    is 13 rows this rule must not halve. The head must read as a citation ON
    ITS OWN, which is what refuses "S/B Improving Head Start for School
    Readiness Act of 2007, PL 110-134". And the tail must be BOUND by the same
    act readers a whole value meets -- so the traps are not exceptions to the
    rule, they are pieces no reader could read.
    """

    from refspec.registry.unified_agenda_parquet import _reads_as_a_citation, _slash_pieces

    # The cut, and the two shapes that are not one.
    assert _slash_pieces("42 USC 7401/CAA 112") == ["42 USC 7401", "CAA 112"]
    assert _slash_pieces("42 USC 7414, 7601, 7671 / Clean Air Act section 612") == [
        "42 USC 7414, 7601, 7671 ",
        " Clean Air Act section 612",
    ]
    assert _slash_pieces("42 USC 2021(h)/AEA 274(h)/Reorganization Plan No. 3 of 1970") == [
        "42 USC 2021(h)",
        "AEA 274(h)",
        "Reorganization Plan No. 3 of 1970",
    ]
    # A slash between two digits is never a separator: the 9/11 Commission Act,
    # and a date.
    ninetyeleven = "PL 110-53, sec 1413, The Implementing Recommendations of the 9/11 Commission Act of 2007"
    assert _slash_pieces(ninetyeleven) == [ninetyeleven]
    assert _slash_pieces("Comment period closes 5/1/2003") == ["Comment period closes 5/1/2003"]

    # The head fence: "S" is not an authority, so the slash is inside whatever
    # this value is rather than between two things.
    assert not _reads_as_a_citation("S")
    assert not _reads_as_a_citation("HR 4577, Treasury")
    assert not _reads_as_a_citation("112 Stat")
    assert _reads_as_a_citation("42 USC 7401")
    assert _reads_as_a_citation("PL 96-354; 5 USC 601. Docket 41683, EDR 468")


def test_the_second_authority_behind_a_slash_binds_on_the_evidence_a_whole_value_would() -> None:
    """"CAA 112" behind a slash resolves exactly as "CAA 112" alone does.

    The readers are not copied, they are re-run: the piece is put on a
    synthetic row and offered to ``_read_abbreviated_act``,
    ``_read_pinned_roster_act``, ``_read_word_prefixed_act``,
    ``_read_index_held_name`` and ``_read_index_held_bare_name``, in that
    order -- the same order, over the same oracles, that a whole value meets.
    So the same RIN's own resolved acts answer before its agency's, and the
    agency fence is what refuses "CWA 309" at an agency whose filings never
    name the Clean Water Act (RIN 2020-AA23, 4 rows, measured).
    """

    from refspec.registry.unified_agenda_parquet import (
        _ActOracles,
        _SeriesCalendar,
        _slash_act_readers,
        _slash_arrivals,
        _Tally,
    )

    oracles = _ActOracles(
        lookup={"cercla": "cercla", "clean air act": "clean air act"},
        keys_by_rin={"2060-AF04": {"clean air act"}},
        keys_by_agency={"2060": {"clean air act"}, "2050": {"cercla"}},
        glosses={},
    )
    tally = _Tally()
    calendar = _SeriesCalendar.build(None)
    readers = _slash_act_readers(oracles, tally)

    def arrivals(text, rin="2060-AF04"):
        row = _failed_row(text, rin=rin, publication_id="199710")
        row.update(authority_type="usc", parse_status="partial", usc_title=42, usc_section="7401")
        return _slash_arrivals([row], readers, tally, calendar)

    # THE SPECIMEN. EPA RIN 2060-AF04 writes both halves of one authority, and
    # the same RIN's 199710 edition spells the Clean Air Act out.
    rows = arrivals("42 USC 7401/CAA 112")
    assert [(r["authority_type"], r["act_key"], r["act_section"]) for r in rows] == [
        ("act_relative", "clean air act", "112")
    ]
    assert rows[0]["corroboration_rule"] == "second-authority-behind-a-slash:agency-roster-initialism"
    assert rows[0]["parse_status"] == "corroborated"
    # The filer's whole value stays on the row: nothing here rewrites what the
    # publisher typed, and the piece is recoverable by this rule's own cut.
    assert rows[0]["authority_text"] == "42 USC 7401/CAA 112"

    # THE SPELLED-OUT HALF, read by the index rather than by an initialism.
    spelled = arrivals("42 USC 7414, 7601, 7671 / Clean Air Act section 612")
    assert [(r["act_key"], r["act_section"]) for r in spelled] == [("clean air act", "612")]

    # A NAME THE INDEX HOLDS THAT IS NOT AN INITIALISM. CERCLA is a popular
    # name in its own right, and the initialism machinery cannot reach it --
    # it compares an abbreviation to the initials of a multi-word key, and
    # "cercla" is one word whose initial is "C". 65 rows over 15 values.
    cercla = arrivals("42 USC 9602/CERCLA 102", rin="2050-AD84")
    assert [(r["act_key"], r["act_section"]) for r in cercla] == [("cercla", "102")]
    assert cercla[0]["corroboration_rule"] == (
        "second-authority-behind-a-slash:index-holds-a-bare-name-and-section"
    )

    # PAIRED NEGATIVES -- every trap the survey named, each refused by a fence
    # rather than by a list of exceptions.
    for text in (
        "42 USC 7401/et seq",
        "PL 106-554, Treasury/General Government Appropriations Act of 2001",
        "PL 110-53, sec 1413, The Implementing Recommendations of the 9/11 Commission Act of 2007",
        "PL 110-53, sec 711, 9/11 Act",
        "PL 96-354; 5 USC 601. Docket 41683, EDR 468/PSDR-81.",
        "Pub. L. 117-180, Division G - Hermit's Peak/Calf Canyon Fire Assistance Act",
        "S/B Improving Head Start for School Readiness Act of 2007, PL 110-134",
        "40 USC 390/EPAAR 205",
        "42 USC 9609/11045",
        "N/A",
    ):
        assert arrivals(text) == [], text

    # AND THE REFUSAL THAT IS THE EXISTING MACHINERY'S, not this rule's: an
    # unmarked year-shaped section token is refused wherever it stands, so
    # "RCRA 2002" recovers nothing while "RCRA 2002(a)" does. This rule adds no
    # opinion about what a section is.
    rcra = _ActOracles(
        lookup={},
        keys_by_rin={"2050-AD03": {"resource conservation and recovery act of 1976"}},
        keys_by_agency={"2050": {"resource conservation and recovery act of 1976"}},
        glosses={},
    )
    rcra_readers = _slash_act_readers(rcra, tally)

    def rcra_arrivals(text):
        row = _failed_row(text, rin="2050-AD03", publication_id="199710")
        row.update(authority_type="usc", parse_status="partial", usc_title=42, usc_section="6912")
        return _slash_arrivals([row], rcra_readers, tally, calendar)

    assert rcra_arrivals("42 USC 6912/RCRA 2002") == []
    assert [r["act_section"] for r in rcra_arrivals("42 USC 6912(a)/RCRA 2002(a)")] == ["2002"]


def test_a_slash_never_states_the_boxs_own_authority_twice() -> None:
    """"42 USC /RCRA 3004(a)(q)" is read WHOLE, and must not be read again.

    The abbreviated shapes carry a scheme-label prefix that steps over a bare
    title and a slash, so this value already resolves in the corroboration
    sweep. Without the fence the box carried the identical reading on two
    ordinals and a consumer counting citations would have counted the filer's
    one authority as two. The fence is the READING -- act and section -- not
    the rule that made it.
    """

    from refspec.registry.unified_agenda_parquet import (
        _ActOracles,
        _SeriesCalendar,
        _slash_act_readers,
        _slash_arrivals,
        _Tally,
    )

    oracles = _ActOracles(
        lookup={},
        keys_by_rin={"2050-AE01": {"resource conservation and recovery act of 1976"}},
        keys_by_agency={"2050": {"resource conservation and recovery act of 1976"}},
        glosses={},
    )
    tally = _Tally()
    readers = _slash_act_readers(oracles, tally)
    already = _failed_row("42 USC /RCRA 3004(a)(q)", rin="2050-AE01", publication_id="199510")
    already.update(
        authority_type="act_relative",
        parse_status="corroborated",
        act_key="resource conservation and recovery act of 1976",
        act_section="3004",
        corroboration_rule="agency-roster-initialism",
    )
    assert _slash_arrivals([already], readers, tally, _SeriesCalendar.build(None)) == []
    assert tally.slash_refusals["the-box-already-names-this-act-at-this-section"] == 1


def test_a_spans_far_end_is_refused_where_the_code_prints_no_such_section() -> None:
    """"16 USC 406k to 406k-4" is "460k to 460k-4" with a transposed stem.

    The grammar cannot ask whether a section is law -- the section oracle
    imports it -- so ``_abbreviated_span``'s docstring says a reader that HOLDS
    an oracle should re-type its phantoms. This is that reader, and it asks
    about exactly the two endpoint shapes the module itself supplied or
    disambiguated:

    * an end INFERRED from an abbreviation, which is this module's reading and
      not the publisher's characters, and
    * a COMPOUND end, which is the one endpoint shape indistinguishable from a
      section's NAME.

    A PLAIN STATED END IS NEVER ASKED, and that is measured rather than
    cautious: 3,048 rows over 321 distinct spans state an end this oracle does
    not enumerate, and they are overwhelmingly repealed law the filer cited on
    purpose -- 18 U.S.C. 5006 to 5024 (the Youth Corrections Act, and several
    of those values say "repealed" in their own text), 4161 to 4166, 4201 to
    4218. The oracle's coverage begins long after those left the Code. Asking
    of every end would delete 3,048 real citations to catch two phantoms.
    """

    from refspec.registry.unified_agenda_parquet import (
        SPAN_ENDPOINT_REFUSALS,
        _refuse_unprintable_span_ends,
        _Tally,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    def row(title, section, end, rule="stated", status="ok"):
        return {
            "usc_title": title, "usc_section": section, "usc_section_end": end,
            "usc_section_span_rule": rule, "usc_appendix": False, "parse_status": status,
        }

    tally = _Tally()
    kept_compound = row(16, "460k", "460k-4")
    refused_compound = row(16, "406k", "406k-4")
    kept_stated = row(18, "5006", "5024")
    refused_inferred = row(7, "77701", "77772", "abbreviated-span")
    kept_inferred = row(31, "3801", "3812", "abbreviated-span")
    rows = [kept_compound, refused_compound, kept_stated, refused_inferred, kept_inferred]
    _refuse_unprintable_span_ends(rows, oracle, tally)

    assert kept_compound["usc_section_end"] == "460k-4", "the Refuge Recreation Act entire"
    assert refused_compound["usc_section_end"] is None, "406k-4 is not a section of title 16"
    assert refused_compound["usc_section_span_rule"] is None
    assert kept_stated["usc_section_end"] == "5024", "repealed law is still law the filer cited"
    assert refused_inferred["usc_section_end"] is None, "7701 typed twice claims 72 non-sections"
    assert kept_inferred["usc_section_end"] == "3812"
    assert tally.span_endpoint_refusals == {
        "a-compound-end-the-code-does-not-print": 1,
        "an-inferred-end-the-code-does-not-print": 1,
    }
    assert set(tally.span_endpoint_refusals) == set(SPAN_ENDPOINT_REFUSALS)

    # THE STATUS COMES DOWN WITH THE END. "ok" means the module accounts for
    # the whole string, and a row whose endpoint has just been refused does
    # not -- "43 USC 270-1 to 270-3" read "ok" while carrying no end, which a
    # consumer filtering on status would have walked straight past.
    assert refused_compound["parse_status"] == "partial"
    assert kept_compound["parse_status"] == "ok", "a kept end keeps its status"


# --------------------------------------------------------------------------- #
# The B8 two-witness enlargement (`inv-b8`,
# research/investigations-mined-2026-08-31.md lines ~41-51 and ~50-51's
# "LONE:B8" rider). B8 stays candidate-only in the oracle
# (usc_section_oracle.CANDIDATE_ONLY_RULES) -- these tests are all against
# `_promote_two_witness_b8`, the builder-side enlargement that publishes a
# subset of B8's own named-but-unpublished readings once a SECOND witness
# outside the oracle's own inputs corroborates one.


def _b8_notes(*specs):
    """A synthetic, in-memory :class:`CfrAuthorityNotes` over several parts.

    Built the same way :meth:`CfrAuthorityNotes.from_file` builds a record --
    :func:`read_note_citations` reads the real citations out of the note text
    -- so a test's note behaves exactly as the pinned cache's would, without
    depending on the pinned cache's own bytes staying exactly as they are
    today. Digest fields are dummy: `_held_parts_by_rule` and `.judge` never
    read them.

    Several parts, because a cache holding ONE part cannot show that a
    witness is bound to the row's OWN part rather than to any part the cache
    happens to hold -- see
    `test_b8_two_witness_binds_the_note_witness_to_the_rows_own_held_parts`.
    """

    from refspec.registry.cfr_authority_notes import AuthorityNote, CfrAuthorityNotes, read_note_citations

    records = tuple(
        AuthorityNote(
            cfr_title=cfr_title,
            cfr_part=cfr_part,
            authority_note=authority_note_text,
            source_note=None,
            api_url="test",
            fetched="2026-09-01",
            raw_sha256="0" * 64,
            raw_bytes=0,
            raw_truncated_at_128k=False,
            citations=read_note_citations(authority_note_text),
        )
        for cfr_title, cfr_part, authority_note_text in specs
    )
    return CfrAuthorityNotes(path=Path("test"), sha256="test", byte_length=0, records=records)


def _b8_note(cfr_title, cfr_part, authority_note_text):
    """The one-part case of :func:`_b8_notes`, which most fixtures want."""

    return _b8_notes((cfr_title, cfr_part, authority_note_text))


def _b8_reference(rin, publication_id, cfr_title, cfr_part):
    """One ``unified_agenda_cfr_references`` row -- the four fields the join reads."""

    return {"rin": rin, "publication_id": publication_id, "cfr_title": cfr_title, "cfr_part": cfr_part}


def test_b8_two_witness_publishes_the_ftc_specimen_that_demoted_plain_b8() -> None:
    """"15 U.S.C. 18(a)" -> 18a, corroborated by 16 CFR Part 801's own note.

    This is the EXACT specimen the oracle module's docstring names as B8's
    demotion ("B8 is a candidate, A4 and B1 are corrections"): §18 and §18a
    are both real, so B8's own single witness cannot tell a filer who meant
    18a from one who meant subsection (a) of a section that never printed
    one. What tells them apart is outside the oracle -- RIN 3084-AB46's own
    rule, 16 CFR Part 801, states its authority as "15 U.S.C. 18a(d); 15
    U.S.C. 18b." verbatim (bare 18 never named), which is witness 2a. Proves
    the two-witness enlargement fixes the exact case that sank the
    one-witness rule, rather than repeating it.
    """

    from refspec.registry.unified_agenda_parquet import (
        USC_B8_PROMOTION_RULE,
        _promote_two_witness_b8,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    row = _authority_slot(
        0,
        "15 U.S.C. 18(a), Clayton Act",
        rin="TEST-B8-0001",
        publication_id="202501",
        authority_type="usc",
        parse_status="partial",
        usc_title=15,
        usc_section="18",
    )
    notes = _b8_note(16, "801", "Authority: 15 U.S.C. 18a(d); 15 U.S.C. 18b.")
    references = [_b8_reference("TEST-B8-0001", "202501", 16, "801")]

    counts = _promote_two_witness_b8([row], references, oracle, notes)

    assert row["usc_section_corrected_section"] == "18a"
    assert row["usc_section_corrected_pinpoint"] is None, "B8 names a SECTION, never a pinpoint into one"
    assert row["usc_section_corrected"] == "18a"
    assert row["usc_section_correction_evidence"] == USC_B8_PROMOTION_RULE
    assert counts == {"promoted": 1, "note_names_bare_section": 0, "witnessless": 0}


def test_b8_two_witness_publishes_on_a_sibling_edition_alone() -> None:
    """Witness 2b alone is enough: no CFR note held, a sibling edition parsed
    the lettered identity structurally.

    "16 USC 715(i)" is a real, LONE B8 candidate (715 prints no lettered
    subsections at all, and 715i is a real, separate section -- the Migratory
    Bird Conservation Act's advisory board). The corroboration here is a
    DIFFERENT row of the SAME RIN, a DIFFERENT edition, whose own citation
    parsed cleanly to usc_section "715i" -- exactly
    :class:`_CitationHistory`'s structural feed, never a raw-text scan.
    """

    from refspec.registry.unified_agenda_parquet import (
        USC_B8_PROMOTION_RULE,
        _promote_two_witness_b8,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    row = _authority_slot(
        0,
        "16 USC 715(i)",
        rin="TEST-B8-0002",
        publication_id="200710",
        authority_type="usc",
        parse_status="partial",
        usc_title=16,
        usc_section="715",
        usc_appendix=False,
        usc_title_is_possible=True,
    )
    sibling = _authority_slot(
        0,
        "16 USC 715i",
        rin="TEST-B8-0002",
        publication_id="200704",
        authority_type="usc",
        parse_status="ok",
        usc_title=16,
        usc_section="715i",
        usc_appendix=False,
        usc_title_is_possible=True,
    )

    counts = _promote_two_witness_b8([row, sibling], [], oracle, notes=_b8_note(1, "1", "Authority: 1 U.S.C. 1."))

    assert row["usc_section_corrected_section"] == "715i"
    assert row["usc_section_correction_evidence"] == USC_B8_PROMOTION_RULE
    assert counts["promoted"] == 1


def test_b8_two_witness_refuses_a_lone_candidate_with_no_second_witness() -> None:
    """NEGATIVE FIXTURE: the subsection-oracle witness fires alone -- no held
    CFR note, no sibling edition -- and the row must NOT publish.

    This is the shape ``inv-b8``'s own doctrine names as the reason B8 stays
    demoted in the oracle: a real lettered section existing beside a bare
    section with no such lettered subsection is not, by itself, evidence of
    which one a filer meant. Reusing the SAME "15 U.S.C. 18(a)" fact as the
    positive specimen above, with everything that made it publish removed.
    """

    from refspec.registry.unified_agenda_parquet import (
        _promote_two_witness_b8,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    row = _authority_slot(
        0,
        "15 U.S.C. 18(a), Clayton Act",
        rin="TEST-B8-0003",
        publication_id="202501",
        authority_type="usc",
        parse_status="partial",
        usc_title=15,
        usc_section="18",
    )

    counts = _promote_two_witness_b8([row], [], oracle, notes=_b8_note(1, "1", "Authority: 1 U.S.C. 1."))

    assert row["usc_section_corrected_section"] is None
    assert row["usc_section_corrected"] is None
    assert row["usc_section_correction_evidence"] is None
    assert counts == {"promoted": 0, "note_names_bare_section": 0, "witnessless": 1}


def test_b8_two_witness_refuses_where_the_notes_own_part_names_the_bare_section() -> None:
    """NEGATIVE FIXTURE, the counter-evidence rider, BOTH-NAMED shape: the
    SAME held note names the bare section AND the lettered one ``present``,
    and this refuses regardless of a firing witness 2b.

    This is the LARGER of the rider's two sub-populations -- 254 of the 319
    rows it refuses on the 2026-09-01 artifact, against 65 where the note
    names the bare section only (the sibling fixture below). A note naming
    both chooses nothing: witness 2a fires from the same document as the
    counter-evidence, and this function refuses anyway, conservatively and on
    purpose. The sibling edition here ALSO structurally spells the lettered
    identity, so a build that checked the counter-evidence anywhere but
    FIRST would publish this row on either witness.
    """

    from refspec.registry.cfr_authority_notes import usc_citation
    from refspec.registry.unified_agenda_parquet import (
        _promote_two_witness_b8,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    row = _authority_slot(
        0,
        "16 USC 715(i)",
        rin="TEST-B8-0004",
        publication_id="200710",
        authority_type="usc",
        parse_status="partial",
        usc_title=16,
        usc_section="715",
    )
    sibling = _authority_slot(
        0,
        "16 USC 715i",
        rin="TEST-B8-0004",
        publication_id="200704",
        authority_type="usc",
        parse_status="ok",
        usc_title=16,
        usc_section="715i",
        usc_title_is_possible=True,
    )
    notes = _b8_note(50, "9", "Authority: 16 U.S.C. 715, 715i.")
    references = [_b8_reference("TEST-B8-0004", "200710", 50, "9")]
    # The shape this fixture pins, asserted rather than assumed: a list
    # continuation "715, 715i" is read as TWO citations, so witness 2a and
    # the counter-evidence both fire from this one note.
    assert notes.judge(usc_citation(16, "715"), {(50, "9")}).verdict == "present"
    assert notes.judge(usc_citation(16, "715i"), {(50, "9")}).verdict == "present"

    counts = _promote_two_witness_b8([row, sibling], references, oracle, notes)

    assert row["usc_section_corrected_section"] is None, "the note's own bare-715 naming refuses this"
    assert row["usc_section_correction_evidence"] is None
    assert counts["note_names_bare_section"] == 1
    assert counts["promoted"] == 0


def test_b8_two_witness_refuses_where_the_note_names_only_the_bare_section() -> None:
    """NEGATIVE FIXTURE, the counter-evidence rider, BARE-ONLY shape: the
    held note names ``NNN`` and never ``NNNx``, and this refuses even though
    a sibling edition structurally spells the lettered identity.

    The rider's OTHER sub-population, and the one where the note genuinely
    is choosing a side: 65 of the 319 rows refused on the 2026-09-01
    artifact (the both-named fixture above carries the other 254). The two
    shapes reach the same refusal through the same branch, so pinning only
    one of them would leave the smaller population's behavior unproven --
    and this is the shape where the refusal is a READING of the note rather
    than a conservative default, so it is the one that must never loosen.
    """

    from refspec.registry.cfr_authority_notes import usc_citation
    from refspec.registry.unified_agenda_parquet import (
        _promote_two_witness_b8,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    row = _authority_slot(
        0,
        "16 USC 715(i)",
        rin="TEST-B8-0008",
        publication_id="200710",
        authority_type="usc",
        parse_status="partial",
        usc_title=16,
        usc_section="715",
    )
    sibling = _authority_slot(
        0,
        "16 USC 715i",
        rin="TEST-B8-0008",
        publication_id="200704",
        authority_type="usc",
        parse_status="ok",
        usc_title=16,
        usc_section="715i",
        usc_title_is_possible=True,
    )
    notes = _b8_note(50, "9", "Authority: 16 U.S.C. 715; 5 U.S.C. 301.")
    references = [_b8_reference("TEST-B8-0008", "200710", 50, "9")]
    # Bare-only, asserted: 715 present, 715i merely a near-miss -- so witness
    # 2a does NOT fire here, and only witness 2b would have published it.
    assert notes.judge(usc_citation(16, "715"), {(50, "9")}).verdict == "present"
    assert notes.judge(usc_citation(16, "715i"), {(50, "9")}).verdict != "present"

    counts = _promote_two_witness_b8([row, sibling], references, oracle, notes)

    assert row["usc_section_corrected_section"] is None, "a note naming bare 715 only still refuses"
    assert row["usc_section_correction_evidence"] is None
    assert counts == {"promoted": 0, "note_names_bare_section": 1, "witnessless": 0}


def test_b8_two_witness_binds_the_note_witness_to_the_rows_own_held_parts() -> None:
    """NEGATIVE FIXTURE: another rule's authority note is NOT this rule's
    witness, even when it names the lettered identity outright.

    The unbound-witness bug class this repository already fixed once, in the
    C3 placeholder promotion: a note read from ANY held part in the cache,
    rather than from the parts THIS rin+edition holds, turns one agency's
    say-so into corroboration for a filing that never cited it.
    ``FTC-HOLDER`` here holds 16 CFR Part 801, whose note names 18a; the
    filing rows hold either a different part (whose note names nothing
    relevant) or no part at all, and both must land ``witnessless``.

    Mutation-checked 2026-09-01: replacing the row-bound
    ``held_by_rule.get((row["rin"], row["publication_id"]))`` with the union
    of every held part promotes both rows here and fails this test, while
    every other B8 fixture stays green -- which is why this one exists.
    """

    from refspec.registry.unified_agenda_parquet import (
        _promote_two_witness_b8,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    def _filing(rin):
        return _authority_slot(
            0,
            "15 U.S.C. 18(a), Clayton Act",
            rin=rin,
            publication_id="202501",
            authority_type="usc",
            parse_status="partial",
            usc_title=15,
            usc_section="18",
        )

    holds_an_irrelevant_part = _filing("TEST-B8-0009")
    holds_no_part_at_all = _filing("TEST-B8-0010")
    notes = _b8_notes(
        (16, "801", "Authority: 15 U.S.C. 18a(d); 15 U.S.C. 18b."),
        (49, "1", "Authority: 49 U.S.C. 106."),
    )
    references = [
        # The rule whose note WOULD corroborate -- a different rin entirely,
        # with no authority row of its own in this fixture.
        _b8_reference("FTC-HOLDER", "202501", 16, "801"),
        _b8_reference("TEST-B8-0009", "202501", 49, "1"),
    ]

    counts = _promote_two_witness_b8([holds_an_irrelevant_part, holds_no_part_at_all], references, oracle, notes)

    assert holds_an_irrelevant_part["usc_section_corrected_section"] is None, (
        "49 CFR Part 1's note names nothing about 15 U.S.C. 18a -- and 16 CFR Part 801's, "
        "which does, belongs to a rule this row is not"
    )
    assert holds_no_part_at_all["usc_section_corrected_section"] is None
    assert counts == {"promoted": 0, "note_names_bare_section": 0, "witnessless": 2}


def test_b8_two_witness_excludes_a_range_residue_with_a_competing_candidate() -> None:
    """REGRESSION, raw-source finding (RIN 1904-AC49): "NNN to NNN(x)" is a
    RANGE whose far end a later re-typesetting parenthesised, never a bare
    NNN pinpoint -- and the oracle's own candidate list proves it without a
    dedicated range guard.

    "42 U.S.C. 8287 to 8287(d)" produces TWO candidates (``parse-as-filed``
    competes because 8287 prints THREE other real lettered subsections, (a),
    (b), (c)), so this function's own "exactly one candidate" gate excludes
    it before the note or history is ever asked -- even where a note WOULD
    otherwise corroborate the range's far end as if it were a lettered
    section.
    """

    from refspec.registry.unified_agenda_parquet import (
        _promote_two_witness_b8,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    row = _authority_slot(
        0,
        "42 U.S.C. 8287 to 8287(d)",
        rin="TEST-B8-0005",
        publication_id="201610",
        authority_type="usc",
        parse_status="partial",
        usc_title=42,
        usc_section="8287",
    )
    # A note that WOULD corroborate 8287d if this row ever reached the
    # witness gate -- proving the exclusion happens upstream of it.
    notes = _b8_note(10, "436", "Authority: 42 U.S.C. 8287d.")
    references = [_b8_reference("TEST-B8-0005", "201610", 10, "436")]

    counts = _promote_two_witness_b8([row], references, oracle, notes)

    assert row["usc_section_corrected_section"] is None
    assert counts == {"promoted": 0, "note_names_bare_section": 0, "witnessless": 0}, (
        "a row with a competing candidate is not a LONE B8 row at all -- it is not counted here, "
        "exactly as an ordinary multi-candidate row is counted in refusal_rows_by_survivors instead"
    )


def test_b8_two_witness_history_requires_an_exact_identity_not_a_hyphenated_neighbour() -> None:
    """REGRESSION, raw-source finding (RIN 3060-AK40): a sibling row parsing
    "615a-1" is NOT structural corroboration for "615a" -- a different, real,
    separate section, which the exploratory survey's own boundary-less regex
    conflated.

    :class:`_CitationHistory` keys ``usc`` by the EXACT parsed
    ``(title, section)`` pair, so a sibling edition's "615a-1" reading lives
    under the key ``(47, "615a-1")`` and never satisfies a lookup for
    ``(47, "615a")``.
    """

    from refspec.registry.unified_agenda_parquet import (
        _promote_two_witness_b8,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    row = _authority_slot(
        0,
        "47 U.S.C. 615(a)",
        rin="TEST-B8-0006",
        publication_id="202410",
        authority_type="usc",
        parse_status="partial",
        usc_title=47,
        usc_section="615",
    )
    neighbour = _authority_slot(
        0,
        "47 U.S.C. 615a-1",
        rin="TEST-B8-0006",
        publication_id="202004",
        authority_type="usc",
        parse_status="ok",
        usc_title=47,
        usc_section="615a-1",
        usc_title_is_possible=True,
    )

    counts = _promote_two_witness_b8(
        [row, neighbour], [], oracle, notes=_b8_note(1, "1", "Authority: 1 U.S.C. 1.")
    )

    assert row["usc_section_corrected_section"] is None
    assert counts == {"promoted": 0, "note_names_bare_section": 0, "witnessless": 1}


def test_b8_two_witness_never_overwrites_an_existing_correction() -> None:
    """A row a NAME earlier pass already corrected keeps its value; this
    function only ever fills a cell three earlier passes left NULL, exactly
    like :data:`USC_C3_PROMOTION_RULE`'s own NULL-gate."""

    from refspec.registry.unified_agenda_parquet import (
        _promote_two_witness_b8,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    row = _authority_slot(
        0,
        "15 U.S.C. 18(a), Clayton Act",
        rin="TEST-B8-0007",
        publication_id="202501",
        authority_type="usc",
        parse_status="partial",
        usc_title=15,
        usc_section="18",
        usc_section_corrected="18",
        usc_section_corrected_section="18",
        usc_section_correction_evidence="some-earlier-rule",
    )
    notes = _b8_note(16, "801", "Authority: 15 U.S.C. 18a(d); 15 U.S.C. 18b.")
    references = [_b8_reference("TEST-B8-0007", "202501", 16, "801")]

    counts = _promote_two_witness_b8([row], references, oracle, notes)

    assert row["usc_section_corrected_section"] == "18", "untouched -- an earlier pass already wrote here"
    assert row["usc_section_correction_evidence"] == "some-earlier-rule"
    assert counts == {"promoted": 0, "note_names_bare_section": 0, "witnessless": 0}


def test_b8_two_witness_census_accounts_for_every_lone_b8_row() -> None:
    """The fix for `inv-b8`'s "LONE:B8" census hole: every row where the
    oracle names B8 as the SOLE surviving reading lands in exactly one of
    :data:`USC_B8_PROMOTION_OUTCOMES` -- before this function existed such a
    row appeared in neither ``corrected_rows_by_rule`` nor
    ``refusal_rows_by_survivors`` (both require the oracle's OWN
    :meth:`corrected_section`/:meth:`correction_candidates`, and a lone
    candidate-only reading satisfies neither's population).

    Four LONE:B8 rows here, one per outcome plus one promoted twice over
    (both witnesses) collapsed to one outcome bucket, and the sum must equal
    the count of rows the oracle names B8-alone for.
    """

    from refspec.registry.unified_agenda_parquet import (
        USC_B8_PROMOTION_OUTCOMES,
        _promote_two_witness_b8,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    promoted_row = _authority_slot(
        0,
        "15 U.S.C. 18(a), Clayton Act",
        rin="TEST-B8-CENSUS-1",
        publication_id="202501",
        authority_type="usc",
        parse_status="partial",
        usc_title=15,
        usc_section="18",
    )
    conflicted_row = _authority_slot(
        0,
        "16 USC 715(i)",
        rin="TEST-B8-CENSUS-2",
        publication_id="200710",
        authority_type="usc",
        parse_status="partial",
        usc_title=16,
        usc_section="715",
    )
    witnessless_row = _authority_slot(
        0,
        "16 USC 715(i)",
        rin="TEST-B8-CENSUS-3",
        publication_id="200710",
        authority_type="usc",
        parse_status="partial",
        usc_title=16,
        usc_section="715",
    )
    not_lone_row = _authority_slot(
        0,
        "42 U.S.C. 8287 to 8287(d)",
        rin="TEST-B8-CENSUS-4",
        publication_id="201610",
        authority_type="usc",
        parse_status="partial",
        usc_title=42,
        usc_section="8287",
    )
    # An APPENDIX row otherwise identical to the promoted one. "15 U.S.C.
    # App. 18" is not 15 U.S.C. 18, so a lettered identity read off the main
    # corpus must never be written onto it -- and it must not be counted as a
    # refusal either, since it was never in this rule's population. Measured
    # 0 such rows in the whole B8-survivor population today
    # (`measure_b8_excluded.py`); this fixture is what keeps the guard.
    appendix_row = _authority_slot(
        0,
        "15 U.S.C. App. 18(a)",
        rin="TEST-B8-CENSUS-5",
        publication_id="202501",
        authority_type="usc",
        parse_status="partial",
        usc_title=15,
        usc_section="18",
        usc_appendix=True,
    )
    notes = _b8_note(16, "801", "Authority: 15 U.S.C. 18a(d); 15 U.S.C. 18b.; 16 U.S.C. 715, 715i.")
    references = [
        _b8_reference("TEST-B8-CENSUS-1", "202501", 16, "801"),
        _b8_reference("TEST-B8-CENSUS-2", "200710", 16, "801"),
        _b8_reference("TEST-B8-CENSUS-5", "202501", 16, "801"),
    ]

    rows = [promoted_row, conflicted_row, witnessless_row, not_lone_row, appendix_row]
    counts = _promote_two_witness_b8(rows, references, oracle, notes)

    # Three of the five rows are LONE B8: `not_lone_row` carries a competing
    # `parse-as-filed` candidate (see the range-residue regression above) and
    # is not counted here at all -- the same way an ordinary multi-candidate
    # row is counted in `refusal_rows_by_survivors` instead -- and
    # `appendix_row` is skipped before the oracle is ever asked.
    assert sum(counts.values()) == 3
    assert counts["promoted"] == 1
    assert counts["note_names_bare_section"] == 1
    assert counts["witnessless"] == 1
    assert set(counts) == set(USC_B8_PROMOTION_OUTCOMES)
    assert appendix_row["usc_section_corrected_section"] is None, (
        "an appendix section must never take a main-corpus lettered identity"
    )
    assert appendix_row["usc_section_correction_evidence"] is None


def test_b8_promotion_rule_names_stay_out_of_the_oracles_own_vocabulary() -> None:
    """The builder's rule name is namespaced apart from
    :data:`~refspec.registry.usc_section_oracle.CORRECTION_RULES` -- the same
    separation :data:`USC_C3_PROMOTION_RULE` keeps -- so a future rename on
    either side cannot silently collide the two.
    """

    from refspec.registry.unified_agenda_parquet import _USC_B8_ORACLE_RULE, USC_B8_PROMOTION_RULE
    from refspec.registry.usc_section_oracle import CANDIDATE_ONLY_RULES, CORRECTION_RULES

    assert USC_B8_PROMOTION_RULE not in CORRECTION_RULES
    assert _USC_B8_ORACLE_RULE in CANDIDATE_ONLY_RULES
    assert _USC_B8_ORACLE_RULE in CORRECTION_RULES
    assert _USC_B8_ORACLE_RULE == "B8-lettered-section-rather-than-a-pinpoint"


def test_held_parts_by_rule_matches_the_join_every_reader_shares() -> None:
    """The shared join :func:`_held_parts_by_rule` now backs three readers
    (`_judge_against_cfr_notes`, `_write_placeholder_candidates`,
    `_promote_two_witness_b8`) -- a basic behavior pin so the extraction
    cannot silently drop a part or leak an unheld one.
    """

    from refspec.registry.unified_agenda_parquet import _held_parts_by_rule

    notes = _b8_note(16, "801", "Authority: 15 U.S.C. 18a(d).")
    references = [
        _b8_reference("RIN-A", "202501", 16, "801"),  # held
        _b8_reference("RIN-A", "202501", 99, "999"),  # not held: no such note
        _b8_reference("RIN-B", "202501", 16, "801"),  # a second rule, same held part
    ]

    held = _held_parts_by_rule(references, notes)

    assert held == {
        ("RIN-A", "202501"): {(16, "801")},
        ("RIN-B", "202501"): {(16, "801")},
    }


def test_a_filers_stat_page_member_is_gated_like_the_notes() -> None:
    """The filer-box half of mined item 4 (REF-062), gated at materialization.

    The gate is condition-for-condition the one
    :func:`refspec.registry.cfr_authority_notes.read_note_citations` applies
    to the publisher's notes: a U.S.C. list member the grammar reached only by
    scanning past a Statutes-at-Large citation is admitted only where the
    oracle's EXACT lists enumerate it, and no oracle admits nothing marked
    (fail-closed). The declared population is 3 texts / 4 citations / 40 rows
    (research/evidence/stat-page-gate-2026-09-01/marked_filer_texts.json);
    the specimens below are one fabricated member from that file and the
    14 CFR 121-shaped genuine resume that must survive.
    """

    from refspec.registry.citation_grammar import parse_authority_citation
    from refspec.registry.unified_agenda_parquet import (
        _stat_page_member_is_enumerated,
        _usc_section_oracle,
    )

    oracle = _usc_section_oracle()
    if oracle is None:
        pytest.skip("the pinned U.S.C. section oracle is not present")

    fabricated = [
        c
        for c in parse_authority_citation(
            "49 USC 13908, as amended by sec 4304 of PL 109-159, 119 Stat 1144, 1763"
        )
        if c.authority_type == "usc" and c.usc_section == "1763"
    ]
    assert fabricated, "the declared specimen must still parse to a marked member"
    assert all(c.usc_section_after_statute for c in fabricated)
    assert not any(_stat_page_member_is_enumerated(c, oracle) for c in fabricated), (
        "119 Stat 1144, 1763 is the Act's own pinpoint page, not 49 U.S.C. 1763"
    )

    genuine = [
        c
        for c in parse_authority_citation(
            "49 U.S.C. 42301 preceding note added by Pub. L. 112-95, sec. 412, "
            "126 Stat. 89, 44101, 44701"
        )
        if c.authority_type == "usc" and c.usc_section in ("44101", "44701")
    ]
    assert genuine, "the genuine resume must parse to marked members"
    assert all(c.usc_section_after_statute for c in genuine)
    assert all(_stat_page_member_is_enumerated(c, oracle) for c in genuine), (
        "a genuinely resumed, enumerated section survives the gate"
    )
    # Fail-closed, like the note-side twin: no oracle admits nothing marked.
    assert not any(_stat_page_member_is_enumerated(c, None) for c in genuine)
    # An unmarked citation is not this gate's business, oracle or no oracle.
    unmarked = [
        c for c in parse_authority_citation("49 USC 13908") if c.authority_type == "usc"
    ]
    assert unmarked and all(_stat_page_member_is_enumerated(c, None) for c in unmarked)
