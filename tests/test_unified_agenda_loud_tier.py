"""Loud-tier additive work, 2026-08-31: the five items and two riders from
``research/investigations-mined-2026-08-31.md``'s "Not landed, loud" section.

Five things, each additive and each with a breaking test plus a negative
fixture, per this wave's own rule that no shape ships without a check that
breaks when it is violated:

1. Six initialism-roster retiers (``research/evidence/initialism-roster-
   2026-08-24/roster.csv``) -- a data change, tested against the live file.
2. The apostrophe-year shape (``_expand_apostrophe_years``) and the guard for
   the named "BIPA' 00" defect.
3. ``usc_slot_reading`` -- a typed, additive column naming the non-U.S.C.
   numbering universe a U.S.C. slot holds.
4. The paren-eaten-lettered-suffix promotion
   (``_promote_paren_eaten_lettered_suffix``), which publishes a
   ``c3_proposals`` answer the oracle itself only classifies.
5. Placeholder candidate authorities (``_write_placeholder_candidates``), the
   two-witness intersection over an "unstated" record.
"""

from __future__ import annotations

import csv
import json
from functools import cache
from pathlib import Path

import pytest

from refspec.registry.unified_agenda_parquet import (
    _INITIALISM_ROSTER_CSV,
    _INITIALISM_ROSTER_FIELDS,
    LEGAL_AUTHORITIES_SCHEMA,
    USC_C3_PROMOTION_OUTCOMES,
    USC_C3_PROMOTION_RULE,
    USC_SLOT_READINGS,
    _abbrev_act_reading,
    _bound_paren_suffix,
    _corroborated_act_sections,
    _initialism_roster,
    _pl_roster,
    _promote_paren_eaten_lettered_suffix,
    _SeriesCalendar,
    _usc_section_oracle,
    _write_placeholder_candidates,
    _write_usc_slot_reading,
)

#: The built table these tests pin their corpus-level counts against, the same
#: directory ``test_unified_agenda_parquet.py`` reads. Every receipt assertion
#: below skips where it is absent, so this file still runs in a checkout that
#: has never built.
ARTIFACT = Path(__file__).resolve().parents[1] / "output" / "registry-real-data-sources" / "unified-agenda-parquet"


@cache
def _oracle():
    return _usc_section_oracle()


@cache
def _calendar():
    return _SeriesCalendar.build(_pl_roster())


# --------------------------------------------------------------------------- #
# 1. Six initialism-roster retiers


def test_the_six_piece_a_tokens_are_pinned_quote_and_ina_stays_candidate() -> None:
    """MMA@0917, NDAA-17@0720, MIPPA@0938, NEPA@0412, ARRA@0412 and
    UMTRCA@2060 each have a live FR document, fetched and hashed under
    ``investigations-2026-08-24/inv-62/raw/``, binding the token to the act
    AT THIS AGENCY -- promoted from ``candidate-index-match`` to
    ``pinned-quote``. INA@1205 was checked the identical way and no quote was
    found within budget, so it is the negative fixture: it must NOT have
    moved."""

    roster = _initialism_roster()
    retiered = {
        ("MMA", "0917"): "medicare prescription drug, improvement, and modernization act of 2003",
        ("NDAA-17", "0720"): "national defense authorization act for fiscal year 2017",
        ("MIPPA", "0938"): "medicare improvements for patients and providers act of 2008",
        ("NEPA", "0412"): "national environmental policy act of 1969",
        ("ARRA", "0412"): "american recovery and reinvestment act of 2009",
        ("UMTRCA", "2060"): "uranium mill tailings radiation control act of 1978",
    }
    for (token, agency), act_name in retiered.items():
        entries = roster[(token, agency)]
        assert len(entries) == 1, (token, agency)
        entry = entries[0]
        assert entry.status == "pinned-quote", (token, agency, entry.status)
        assert entry.act_name == act_name
        assert entry.evidence_path.startswith(
            "research/evidence/investigations-2026-08-24/inv-62/raw/"
        ), entry.evidence_path

    # Negative fixture: INA@1205 was checked and found NO live quote, and
    # sibling agencies of the retiered tokens that #62 never checked (ARRA
    # travels to 1810/1855 too) must not have moved either -- a roster row is
    # keyed to the agency the evidence was gathered from, never the token
    # alone.
    assert roster[("INA", "1205")][0].status == "candidate-index-match"
    assert roster[("ARRA", "1810")][0].status == "candidate-index-match"
    assert roster[("ARRA", "1855")][0].status == "candidate-index-match"
    # MMA@0938 stays candidate-index-match too: CMS's own roster reaches
    # three Medicare acts by these initials, a refusal #62 Piece A never
    # touches.
    assert roster[("MMA", "0938")][0].status == "candidate-index-match"


def test_obra_1993_is_a_year_keyed_roster_row() -> None:
    """"Sec 13622 of OBRA '93" (CMS/0938) is the only OBRA citation this wave
    measured with a real, stated pinpoint -- OBRA is otherwise year-ambiguous
    (1986/1987/1989/1990/1993 are five different acts) and carried no roster
    row at all before this wave. One row, keyed by year like NDAA and FOIA,
    not a bare-token entry."""

    roster = _initialism_roster()
    entries = roster[("OBRA", "0938")]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.year_key == "1993"
    assert entry.act_name == "omnibus budget reconciliation act of 1993"
    assert entry.status == "candidate-index-match"
    # Negative fixture: a year OBRA's own family never resolved this wave
    # (1987, "Sec 13622 of OBRA '93" is the only pinpoint this corpus's own
    # apostrophe-year rows corroborate) has no row, and the loader's
    # year-keyed lookup for it returns nothing rather than a bare-token entry
    # standing in for it.
    assert "1987" not in {e.year_key for e in entries}


def test_the_roster_file_is_exactly_as_wide_as_its_header() -> None:
    """Every row of the pinned CSV has the header's field count.

    The file carried a 12-field row against an 11-field header for a day --
    an unquoted comma in a note -- and nothing broke, because
    ``csv.DictReader`` parks the surplus under the ``None`` key and every
    column the loader names still read correctly. The file is a receipt; a
    row that is silently a different row from the one its author wrote is the
    failure this asserts against."""

    with _INITIALISM_ROSTER_CSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert tuple(rows[0]) == _INITIALISM_ROSTER_FIELDS
    wrong = [number for number, row in enumerate(rows, start=1) if len(row) != len(rows[0])]
    assert wrong == [], f"roster rows are not {len(rows[0])} fields wide: {wrong}"


def test_the_loader_refuses_a_row_of_the_wrong_width(tmp_path, monkeypatch) -> None:
    """Negative fixture for the same defect, at the reader: a 12-field row is
    raised on, not absorbed. Without this the check above only proves today's
    file is clean, and says nothing about what the loader would do with a
    damaged one."""

    from refspec.registry import unified_agenda_parquet as module

    header = ",".join(_INITIALISM_ROSTER_FIELDS)
    good = 'MIPPA,0938,,pinned-quote,an act,110-275,path,sha256:x,"a quote",29,a note'
    damaged = "MIPPA,0938,,pinned-quote,an act,110-275,path,sha256:x,quote,29,a note,and a stray twelfth"

    clean = tmp_path / "clean.csv"
    clean.write_text(f"{header}\n{good}\n", encoding="utf-8")
    monkeypatch.setattr(module, "_INITIALISM_ROSTER_CSV", clean)
    assert module._initialism_roster()[("MIPPA", "0938")][0].status == "pinned-quote"

    broken = tmp_path / "broken.csv"
    broken.write_text(f"{header}\n{damaged}\n", encoding="utf-8")
    monkeypatch.setattr(module, "_INITIALISM_ROSTER_CSV", broken)
    with pytest.raises(ValueError, match="does not have 11 fields"):
        module._initialism_roster()


def test_the_roster_file_is_what_its_generator_writes() -> None:
    """``build_roster.py`` reproduces the committed CSV byte for byte.

    Two rows of the file were hand-edited into it -- one whose note carried
    the unquoted comma above, one inserted out of the generator's own sort
    order -- and a receipt nothing can regenerate is a claim with no check
    behind it. The generator is deterministic (no clock, no network, and the
    ``rows_observed`` census pinned rather than read from whichever build is
    on disk), so this is an equality, not an approximation."""

    import importlib.util
    import sys

    script = Path(__file__).resolve().parents[1] / "research/evidence/initialism-roster-2026-08-24/build_roster.py"
    if not script.is_file():
        pytest.skip("the roster generator is not in this checkout")
    spec = importlib.util.spec_from_file_location("_build_roster_under_test", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        written = Path(module.__file__).parent / "roster.csv"
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "roster.csv"
            argv, stdout = sys.argv, sys.stdout
            sys.argv = ["build_roster.py", "--out", str(out)]
            sys.stdout = io.StringIO()
            try:
                module.main()
            finally:
                sys.argv, sys.stdout = argv, stdout
            assert out.read_bytes() == written.read_bytes(), "roster.csv is not what build_roster.py writes"
    finally:
        sys.modules.pop(spec.name, None)


# --------------------------------------------------------------------------- #
# 2. The apostrophe-year shape


def test_the_apostrophe_year_shape_reads_every_pieceb_text_variant() -> None:
    """33 rows, all loud-failed before this unit: BBA '97 (9), BBRA '99/BBRA'
    99 (9), BIPA '00 (11), and the "sec X of ABBREV 'YY" compound (4) --
    every spacing #62 Piece B measured. One new lexical step
    (``_expand_apostrophe_years``), no new shape."""

    bare = {
        "BBA '97": ("BBA", None, ("1997",), False),
        "BBA'97": ("BBA", None, ("1997",), False),
        "BBRA '99": ("BBRA", None, ("1999",), False),
        "BBRA'99": ("BBRA", None, ("1999",), False),
        "BIPA '00": ("BIPA", None, ("2000",), False),
        "BIPA'00": ("BIPA", None, ("2000",), False),
    }
    for text, expected in bare.items():
        assert _abbrev_act_reading(text) == expected, text

    compound = {
        "Sec 4701(b) of BBA '97": ("BBA", "1997", ("4701(b)",), True),
        "Sec 4741(a)(2) of BBA '97": ("BBA", "1997", ("4741(a)(2)",), True),
    }
    for text, expected in compound.items():
        assert _abbrev_act_reading(text) == expected, text

    # Every bare form corroborates to NO section (the year names the act and
    # nothing else), and the compound form keeps its real, stated section.
    bba = "balanced budget act of 1997"
    bbra = "medicare, medicaid, and schip balanced budget refinement act of 1999"
    bipa = "medicare, medicaid, and schip benefits improvement and protection act of 2000"
    assert _corroborated_act_sections(bba, None, ("1997",)) == ()
    assert _corroborated_act_sections(bbra, None, ("1999",)) == ()
    assert _corroborated_act_sections(bipa, None, ("2000",)) == ()
    assert _corroborated_act_sections(bba, "1997", ("4701(b)",), marked=True) == ("4701",)


def test_the_apostrophe_year_shape_never_publishes_the_named_defect() -> None:
    """The named defect review D found: "BIPA' 00" (apostrophe, THEN a
    space, then the digits) once reached an unrelated reading and published
    ``act_section`` "00" -- the year, misread as a section, under
    ``act_key`` "bipa". This is the guard's test: every spacing variant,
    including this exact one, must read as the bare year 2000 and
    corroborate to NO section, never "00"."""

    bipa = "medicare, medicaid, and schip benefits improvement and protection act of 2000"
    reading = _abbrev_act_reading("BIPA' 00")
    assert reading is not None
    abbreviation, year, sections, marked = reading
    assert abbreviation == "BIPA"
    assert year is None
    assert sections == ("2000",), "the year must land as a single token, not '00'"
    emitted = _corroborated_act_sections(bipa, year, sections, marked=marked)
    assert emitted == (), "act_section must be empty, never '00'"

    # Negative fixture: a genuinely SHORT real section that happens to be
    # two digits, unmarked, is still a section where the century check
    # cannot explain it -- the suppressor must not eat every short section
    # in the corpus to catch one year.
    bbra = "medicare, medicaid, and schip balanced budget refinement act of 1999"
    assert _corroborated_act_sections(bbra, None, ("42",)) == ("42",)


def test_both_curly_apostrophes_read_and_a_section_marked_year_does_not() -> None:
    """Both directions of the expansion, in one place.

    READS: U+0027, U+2019 (the two the corpus writes -- 839 and 59 rows carry
    the character) and U+2018, its mirror, which is unattested in the pinned
    corpus and folded anyway, because a reader that takes one curly quote and
    not the other is a defect waiting for its first row.

    REFUSES: an apostrophe-year immediately behind a SECTION MARKER. The
    marker is the publisher declaring the token a section, and ``marked``
    deliberately defeats the year suppression, so expanding there would mint
    ``act_section`` "1997" out of a year -- the very defect this shape exists
    to stop, one slot over. Unexpanded, no shape reads it and the row stays
    loud-failed, which is what it did before this wave."""

    for text in ("BBRA '99", "BBRA ’99", "BBRA ‘99"):
        assert _abbrev_act_reading(text) == ("BBRA", None, ("1999",), False), text

    for refused in ("SSA sec '97", "SSA section '97", "SSA secs '97", "SSA sec. '97"):
        assert _abbrev_act_reading(refused) is None, refused

    # And the marker guard is narrow: the same marker in front of a REAL
    # section is untouched, apostrophe or no apostrophe.
    assert _abbrev_act_reading("SSA, sec 1834") == ("SSA", None, ("1834",), True)
    assert _abbrev_act_reading("Sec 4701(b) of BBA '97") == ("BBA", "1997", ("4701(b)",), True)


def test_an_apostrophe_year_is_a_year_claim_and_never_a_section() -> None:
    """The adjudication, both directions: an expanded token can be dropped as
    the act's own year, or it can refuse the reading, and it can never be
    emitted as a section.

    Against the act whose name carries the year, no section. Against any other
    act, the whole reading refuses rather than falling back to "section 25" --
    which is exactly what such a row did before this wave, when no shape read
    an apostrophe at all, so the refusal regresses nothing and mints
    nothing."""

    reading = _abbrev_act_reading("FOO '25")
    assert reading == ("FOO", None, ("2025",), False)
    _, year, sections, marked = reading
    assert _corroborated_act_sections("foo act of 2025", year, sections, marked=marked) == ()
    assert _corroborated_act_sections("foo act of 1998", year, sections, marked=marked) is None

    # The suppressor stays narrow in the other direction: a short real section
    # that is not year-shaped survives, and a four-digit section the publisher
    # MARKED survives, because the marker is the publisher naming the slot.
    assert _corroborated_act_sections("foo act of 2025", None, ("42",)) == ("42",)
    assert _corroborated_act_sections("social security act", None, ("1834",), marked=True) == ("1834",)


def test_a_wrong_century_guess_refuses_rather_than_publishes() -> None:
    """The pivot-year guess (00-68 -> 20XX, 69-99 -> 19XX) is right for every
    token #62 measured, and costs nothing where it is wrong: the year check
    every shape already runs rejects a year that is not a substring of the
    resolved act's own name, so a wrong guess refuses instead of minting a
    wrong section. Negative fixture: an apostrophe-year token naming an act
    whose real year the guess does NOT reach."""

    reading = _abbrev_act_reading("BBA '97")
    assert reading is not None
    _, year, sections, _ = reading
    # A hypothetical act of a DIFFERENT year than the guess produced:
    # the four-digit check in _corroborated_act_sections must refuse.
    assert _corroborated_act_sections("some act of 1898", year, sections) is None


# --------------------------------------------------------------------------- #
# 3. usc_slot_reading


def _authority(rin: str, usc_title: int | None, usc_section: str | None, verdict: str | None) -> dict:
    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update(
        rin=rin,
        publication_id="202510",
        authority_type="usc" if usc_title is not None else "other",
        usc_title=usc_title,
        usc_section=usc_section,
        usc_section_verdict=verdict,
    )
    return row


def test_usc_slot_reading_names_reg_suffix_witnessed_by_cfr_list() -> None:
    """"26 USC 6708-1" is Treasury's own dash-suffixed regulation number (26
    CFR 301.6708-1) wearing a U.S.C. label, not a compound section --
    RIN 1545-BF39's own CFR_LIST states "26 CFR 301.6708-1" in five earlier
    editions (raw XML, ``REGINFO_RIN_DATA_200604.xml``), which is the
    structural witness this column names. usc_section_verdict is untouched:
    it is still ``absent``."""

    authorities = [_authority("1545-BF39", 26, "6708-1", "absent")]
    references = [
        {"rin": "1545-BF39", "publication_id": "200604", "cfr_title": 26, "cfr_part": "301", "cfr_section": "6708-1"},
    ]
    counts = _write_usc_slot_reading(authorities, references, _oracle())
    assert counts["reg-suffix"] == 1
    assert authorities[0]["usc_slot_reading"] == "reg-suffix"
    assert authorities[0]["usc_section_verdict"] == "absent", "the verdict must not move"


def test_usc_slot_reading_refuses_reg_suffix_without_the_cfr_list_witness() -> None:
    """Negative fixture: the identical bare digit-hyphen-digit shape with NO
    corroborating CFR_LIST entry gets no name at all -- an unwitnessed
    compound section is not this column's to call."""

    authorities = [_authority("9999-AA00", 26, "1234-5", "absent")]
    references: list[dict] = []
    counts = _write_usc_slot_reading(authorities, references, _oracle())
    assert counts["reg-suffix"] == 0
    assert authorities[0]["usc_slot_reading"] is None


def test_usc_slot_reading_names_chapter_in_slot_and_never_touches_exists() -> None:
    """"2 USC 10" is chapter 10 of title 2, not a section -- absent as a
    section in every year, named here. Negative fixture: "1 USC 1" is ALSO
    chapter 1 of title 1 AND a real, existing section (the overlap the
    oracle's own C7 rule is fenced against) -- naming it "chapter-in-slot"
    would contradict a verdict this wave leaves untouched, so it must stay
    NULL."""

    oracle = _oracle()
    assert (2, "10") in oracle.chapters
    assert oracle.section_verdict(2, "10", 2020).verdict != "exists"
    assert (1, "1") in oracle.chapters
    assert oracle.section_verdict(1, "1", 2020).verdict == "exists"

    authorities = [
        _authority("1000-AA00", 2, "10", "absent"),
        _authority("1000-AA01", 1, "1", "exists"),
    ]
    counts = _write_usc_slot_reading(authorities, [], oracle)
    assert counts["chapter-in-slot"] == 1
    assert authorities[0]["usc_slot_reading"] == "chapter-in-slot"
    assert authorities[1]["usc_slot_reading"] is None, "an 'exists' row is never named chapter-in-slot"


def test_usc_slot_reading_is_null_on_every_other_row() -> None:
    """A row this column has nothing to say about -- no title, not a U.S.C.
    row at all, or a real bare section -- gets NULL, and the two names are
    the only ones this column ever writes."""

    authorities = [
        _authority("1000-AA02", None, None, None),
        # Absent, but not a chapter number and not hyphen-shaped -- neither
        # rule has anything to name here.
        _authority("1000-AA03", 15, "12345", "absent"),
    ]
    _write_usc_slot_reading(authorities, [], _oracle())
    assert all(row["usc_slot_reading"] is None for row in authorities)
    assert set(USC_SLOT_READINGS) == {"reg-suffix", "chapter-in-slot"}


# --------------------------------------------------------------------------- #
# 4. Paren-eaten-lettered-suffix promotion


def _c3_row(rin: str, title: int, section: str, text: str, corrected: str | None = None) -> dict:
    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update(
        rin=rin,
        publication_id="199510",
        authority_type="usc",
        authority_text=text,
        usc_title=title,
        usc_section=section,
        usc_section_verdict="absent",
        usc_section_corrected=corrected,
    )
    return row


def test_c3_promotes_the_sole_enumerated_fused_reading() -> None:
    """RIN 7100-AB50, 1995 Unified Agenda (raw XML, ``REGINFO_RIN_DATA_
    199510.xml``): "15 USC 78(b)" -- a real Federal Reserve banking-law
    citation whose bare "78" is not a section at all, and whose ONE
    enumerated fused reading (15 U.S.C. 78b) is what the oracle's own
    ``c3_proposals`` already answers. Promoted here, not by the ordinary
    fence: ``correction_candidates`` proposes nothing for a bare section
    that was never real to begin with."""

    row = _c3_row("7100-AB50", 15, "78", "15 USC 78(b)")
    counts = _promote_paren_eaten_lettered_suffix([row], _oracle())
    assert counts["promoted"] == 1
    assert row["usc_section_corrected"] == "78b"
    assert row["usc_section_corrected_section"] == "78b"
    assert row["usc_section_corrected_pinpoint"] is None
    assert row["usc_section_correction_evidence"] == USC_C3_PROMOTION_RULE
    assert row["usc_section_verdict"] == "absent", "the as-filed verdict must not move"


def test_c3_keeps_refusing_a_witnessless_paren_letter() -> None:
    """BREAKING TEST for the 1,186-row witnessless population: a stem whose
    parenthesised letter names NO enumerated fused reading at all -- a
    genuine subsection, not a lost suffix -- must keep refusing. "7 USC
    1939(c)" (RIN 0570-AA08, 1995 Unified Agenda) is #47's own specimen: the
    oracle offers zero candidates, and this promotion writes nothing."""

    row = _c3_row("0570-AA08", 7, "1939", "7 USC 1939 (c)")
    counts = _promote_paren_eaten_lettered_suffix([row], _oracle())
    assert counts["witnessless"] == 1
    assert counts["promoted"] == 0
    assert row["usc_section_corrected"] is None
    assert row["usc_section_correction_evidence"] is None


def test_c3_refuses_where_two_fused_readings_survive() -> None:
    """A bound occurrence whose lettered reading is not itself a section, and
    whose hyphen-child family therefore offers many, is two or more real
    readings with nothing in the text to choose between them -- the same
    refusal ``corrected_section`` already makes for every other
    multi-survivor citation. "15 U.S.C. 80(a)": 80a is not a section, 80a-1 …
    80a-64 are, and the oracle offers all 65."""

    row = _c3_row("3235-AM45", 15, "80", "15 U.S.C. 80(a)")
    counts = _promote_paren_eaten_lettered_suffix([row], _oracle())
    assert counts["ambiguous"] == 1
    assert row["usc_section_corrected"] is None


def test_c3_never_overwrites_an_existing_correction() -> None:
    """Negative fixture: a row an earlier fence already corrected is left
    exactly as that fence wrote it -- this promotion only ever fills a NULL,
    the same discipline every correction column in this module keeps."""

    row = _c3_row("7100-AB50", 15, "78", "15 USC 78(b)", corrected="78-something-else")
    counts = _promote_paren_eaten_lettered_suffix([row], _oracle())
    assert counts["promoted"] == 0
    assert row["usc_section_corrected"] == "78-something-else"


def test_c3_refuses_a_parenthetical_belonging_to_a_SIBLING_citation() -> None:
    """BREAKING TEST, same title. ``"15 USC 78; 15 USC 78(b)"`` is two
    citations and two rows; the first states a bare stem and the second a
    parenthesised one. A pre-filter that asked whether the STRING contains
    "78(b)" promotes BOTH -- the bare citation gets a suffix it never wrote,
    read off its neighbour, and 15 U.S.C. 78b is real so nothing downstream
    can tell. The text states this stem two ways, so it binds neither and
    both rows keep the ``absent`` verdict they had."""

    text = "15 USC 78; 15 USC 78(b)"
    assert _bound_paren_suffix("78", text) is None
    rows = [_c3_row("9999-AA01", 15, "78", text), _c3_row("9999-AA01", 15, "78", text)]
    counts = _promote_paren_eaten_lettered_suffix(rows, _oracle())
    assert counts["promoted"] == 0
    assert counts["unbound"] == 2
    assert all(row["usc_section_corrected"] is None for row in rows)
    # The same string with the SAME parenthetical on both occurrences binds,
    # because then it does not matter which occurrence is this row's.
    assert _bound_paren_suffix("78", "15 USC 78(b); 15 USC 78(b)") == "78(b)"


def test_c3_refuses_a_parenthetical_belonging_to_ANOTHER_TITLE() -> None:
    """BREAKING TEST, across titles. ``"15 USC 78; 42 USC 78(b)"`` writes the
    stem twice under two different titles, and only the title-42 citation
    parenthesises it. The title-15 row was promoted to 15 U.S.C. 78b on a
    title-42 citation's letter. Nothing binds, nothing publishes."""

    text = "15 USC 78; 42 USC 78(b)"
    assert _bound_paren_suffix("78", text) is None
    row = _c3_row("9999-AA02", 15, "78", text)
    counts = _promote_paren_eaten_lettered_suffix([row], _oracle())
    assert counts["promoted"] == 0
    assert counts["unbound"] == 1
    assert row["usc_section_corrected"] is None


def test_c3_refuses_a_stated_tail_the_surviving_reading_drops() -> None:
    """BREAKING TEST for the 17 rows of RIN 3235-AI17 (editions 200104-200904,
    raw ``REGINFO_RIN_DATA_*.xml``), which state ``"15 USC 78(s)-37(a)"``.
    78s-37 is not a section, so the oracle falls back to the bare lettered
    78s -- which is one -- and publishing it drops "-37(a)", characters the
    filer wrote. The raw record forbids it outright: the SAME rule's later
    editions (200910 onward) spell the box ``"15 USC 78a-37(a)"``, letter "a",
    not "s", beside the SEC's rulemaking quintet (77s(a), 78(wa), 77sss(a)),
    which reads the box as Investment Company Act 38(a) -- 15 U.S.C.
    80a-37(a). Two spellings of one damaged token and neither is 78s."""

    row = _c3_row("3235-AI17", 15, "78", "15 USC 78(s)-37(a)")
    assert _bound_paren_suffix("78", "15 USC 78(s)-37(a)") == "78(s)-37"
    counts = _promote_paren_eaten_lettered_suffix([row], _oracle())
    assert counts["stated_tail_refused"] == 1
    assert counts["promoted"] == 0
    assert row["usc_section_corrected"] is None

    # Negative fixture: a tail the Code DOES print is honoured and published,
    # so the refusal is about dropping stated characters and not about tails.
    # "15 U.S.C. 80(a)-23" is 80a-23, a real section, on 14 rows of the
    # pinned corpus.
    honoured = _c3_row("3235-AM45", 15, "80", "15 U.S.C. 80(a)-23")
    counts = _promote_paren_eaten_lettered_suffix([honoured], _oracle())
    assert counts["promoted"] == 1
    assert honoured["usc_section_corrected"] == "80a-23"


def test_the_binding_is_the_pinpoint_rule_one_field_wider() -> None:
    """What ``_bound_paren_suffix`` reads, and what it declines to.

    Bound: one occurrence, or several that agree; occurrences differing only
    BELOW the first parenthesised group, since the first group is the whole
    of what a fused reading uses. Unbound: a bare occurrence beside a
    parenthesised one, two different letters, a stated range's two endpoints,
    and a stem that only appears under a label this row does not own."""

    assert _bound_paren_suffix("78", "15 USC 78(b)") == "78(b)"
    assert _bound_paren_suffix("1939", "7 USC 1939 (c)") == "1939(c)"
    assert _bound_paren_suffix("78", "15 USC 78(c)(b), 78(c)(3)") == "78(c)"
    assert _bound_paren_suffix("78", "15 USC 78, see also 15 USC 80a(1)") is None
    assert _bound_paren_suffix("78", "15 USC 78(d); 15 USC 78(ff)") is None
    assert _bound_paren_suffix("81", "19 U.S.C. 81(a) to 81(u)") is None
    assert _bound_paren_suffix("2000", "42 U.S.C. 2000(d) to 2000(d)-7") is None
    # A numeric group is a subsection and never a lost letter suffix.
    assert _bound_paren_suffix("300", "42 USC 300(1)") is None


# --------------------------------------------------------------------------- #
# 5. Placeholder candidate authorities


def _stated_row(rin: str, pub: str, ordinal: int, **kwargs) -> dict:
    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update(rin=rin, publication_id=pub, ordinal=ordinal, authority_type="usc")
    row.update(kwargs)
    return row


def _unstated_row(rin: str, pub: str, ordinal: int) -> dict:
    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update(rin=rin, publication_id=pub, ordinal=ordinal, authority_type="unstated", unstated_kind="none-off-form")
    return row


class _FakeNote:
    def __init__(self, citations):
        self.citations = citations


class _FakeCitation:
    def __init__(self, family, identity):
        self.family = family
        self.identity = identity


class _FakeNotes:
    """A minimal stand-in for CfrAuthorityNotes: holds exactly the parts
    given it, and answers ``note`` from a fixed table -- enough surface for
    _write_placeholder_candidates, which only calls ``holds`` and ``note``.
    """

    def __init__(self, held: set[tuple[int, str]], notes: dict[tuple[int, str], list[tuple[str, str]]]):
        self._held = held
        self._notes = {
            key: _FakeNote([_FakeCitation(f, i) for f, i in cites]) for key, cites in notes.items()
        }

    def holds(self, title, part) -> bool:
        return (int(title), part) in self._held

    def note(self, title, part):
        return self._notes.get((int(title), part))


def test_placeholder_candidates_publish_only_the_two_witness_intersection() -> None:
    """A record's own held CFR part names {A, B, C} (witness A); a sibling
    edition of the same rule, carrying no placeholder of its own, states
    more than this record does and the difference is {B, C, D} (witness B).
    Only the intersection {B, C} is publishable -- A alone and D alone are
    each a single witness's word, the price #62's own act-index tier
    measured as 15.25% wrong, and this column does not spend that here."""

    notes = _FakeNotes(
        held={(8, "215")},
        notes={(8, "215"): [("usc", "8:1101"), ("usc", "8:1103"), ("public_law", "108-458")]},
    )
    authorities = [
        # This record's own stated box, at the SAME edition as the placeholder.
        _stated_row("1650-AA00", "200510", 0, usc_title=8, usc_section="1103"),
        _unstated_row("1650-AA00", "200510", 1),
        # A sibling edition, no placeholder of its own, stating strictly more.
        _stated_row("1650-AA00", "200504", 0, usc_title=8, usc_section="1101"),
        _stated_row("1650-AA00", "200504", 1, usc_title=8, usc_section="1103"),
        _stated_row("1650-AA00", "200504", 2, usc_title=8, usc_section="9999"),
    ]
    references = [{"rin": "1650-AA00", "publication_id": "200510", "cfr_title": 8, "cfr_part": "215"}]
    calendar = _SeriesCalendar.build(None)
    counts = _write_placeholder_candidates(authorities, references, notes, calendar)
    assert counts["published"] == 1
    placeholder = authorities[1]
    published = placeholder["placeholder_candidate_authorities"]
    assert published == "usc:8:1101", (
        "1103 is already stated by the record itself; 9999 and 108-458 are single-witness only"
    )


def test_placeholder_candidates_refuse_a_single_witness() -> None:
    """Negative fixture: witness A alone (no sibling edition states more) is
    not published -- the record gets NULL, not a weaker answer."""

    notes = _FakeNotes(held={(8, "215")}, notes={(8, "215"): [("usc", "8:1101")]})
    authorities = [_unstated_row("2000-AA00", "200510", 0)]
    references = [{"rin": "2000-AA00", "publication_id": "200510", "cfr_title": 8, "cfr_part": "215"}]
    calendar = _SeriesCalendar.build(None)
    counts = _write_placeholder_candidates(authorities, references, notes, calendar)
    assert counts["published"] == 0
    assert authorities[0]["placeholder_candidate_authorities"] is None


def test_placeholder_candidates_refuse_a_public_law_dated_after_the_edition() -> None:
    """The note-date-vs-edition-year gate: a note read TODAY can name a
    Public Law enacted after the record's own edition -- a 2007 placeholder
    offered a later Congress by a currently-captured note is exactly the
    trap #47/#62's sibling investigation (``inv-placeholders``) names. The
    98th Congress (1983-84) postdating a 1980 edition is the same shape at a
    date this test can pin without a live congress.gov roster: the pinned
    calendar refuses any congress, so every apostrophe/public-law candidate
    here is gated and none is published."""

    notes = _FakeNotes(
        held={(8, "215")},
        notes={(8, "215"): [("public_law", "98-1")]},
    )
    authorities = [
        # A donor edition dated AFTER the 98th Congress (1990): it can
        # legitimately state the law itself -- only the 1980 PLACEHOLDER
        # record cannot have.
        _stated_row("3000-AA00", "199004", 0, authority_type="public_law", public_law="98-1"),
        _unstated_row("3000-AA00", "198010", 0),
    ]
    references = [{"rin": "3000-AA00", "publication_id": "198010", "cfr_title": 8, "cfr_part": "215"}]
    # A calendar whose 1980 bound is the 96th Congress: the 98th postdates it.
    calendar = _SeriesCalendar({1980: 96}, {}, {})
    counts = _write_placeholder_candidates(authorities, references, notes, calendar, _oracle())
    assert counts["published"] == 0
    assert counts["candidates_gated_by_edition"] == 1
    assert authorities[1]["placeholder_candidate_authorities"] is None
    assert authorities[1]["placeholder_candidate_refusal"] == (
        "note-names-a-later-public-law-than-the-edition-states"
    )


def test_placeholder_candidates_refuse_a_law_approved_after_the_edition() -> None:
    """The gate is the APPROVAL DATE, not the congress. Pub. L. 110-20 was
    approved 05/02/2007 and the 110th Congress had enacted laws by the end of
    2007, so the congress bound calls it in series for the Spring 2007
    edition (``200704``) -- an edition published a month before the law
    existed. The pinned roster carries the date, so the finer question is
    answerable, and the candidate is dropped."""

    calendar = _calendar()
    assert calendar.pl_congress_in_series("110-20", "200704") is True, "the coarse gate passes it"
    assert calendar.pl_approved_by_edition("110-20", "200704") is False, "the dated gate does not"
    # Same law, the NEXT edition: approved 05/2007, published 10/2007.
    assert calendar.pl_approved_by_edition("110-20", "200710") is True
    # The documented residue: a publication id with no month falls back to
    # the congress bound rather than to silence.
    assert calendar.pl_approved_by_edition("110-20", "2012") is True

    notes = _FakeNotes(held={(8, "215")}, notes={(8, "215"): [("public_law", "110-20")]})
    authorities = [
        _unstated_row("4000-AA00", "200704", 0),
        _stated_row("4000-AA00", "200810", 0, authority_type="public_law", public_law="110-20"),
    ]
    references = [{"rin": "4000-AA00", "publication_id": "200704", "cfr_title": 8, "cfr_part": "215"}]
    counts = _write_placeholder_candidates(authorities, references, notes, calendar, _oracle())
    assert counts["published"] == 0
    assert counts["candidates_gated_by_edition"] == 1
    assert authorities[0]["placeholder_candidate_refusal"] == (
        "note-names-a-later-public-law-than-the-edition-states"
    )


def test_placeholder_candidates_refuse_what_the_section_oracle_refutes() -> None:
    """Two witnesses agreeing is a CARDINALITY check: it says two readers
    produced the same string, not that the string names law. Both can carry
    one defect -- a sibling edition restates the filer's own damaged citation,
    a badly split note carries a number out of its neighbour -- so a U.S.C.
    candidate is put to the oracle that exists for its kind.

    The synthetic case first: a section number no title prints, offered by
    both witnesses, must not publish beside the real one. Then the case in
    the corpus, read raw: **36 CFR 251's own authority note says "16 U.S.C.
    472, 479b, 551, 1134, 3210, 6201-13; 30 U.S.C. 1740, 1761-1771"** -- and
    title 30 runs 1731…1736 then jumps to 1751, so 30 U.S.C. 1740 and 1761
    are not sections at all. They are the publisher's own title slip for
    FLPMA's rights-of-way sections at 43 U.S.C., which the same rule's other
    notes name correctly. Three rows of RIN 1004-AE45 published both."""

    oracle = _oracle()
    assert oracle.section_verdict(8, "1101").verdict == "exists"
    assert oracle.section_verdict(8, "999999").verdict == "absent"
    assert oracle.section_verdict(30, "1740").verdict == "absent"
    assert oracle.section_verdict(43, "1740").verdict == "exists"

    notes = _FakeNotes(
        held={(8, "215")},
        notes={(8, "215"): [("usc", "8:1101"), ("usc", "8:999999"), ("usc", "30:1740")]},
    )
    authorities = [
        _unstated_row("5000-AA00", "200510", 0),
        _stated_row("5000-AA00", "200504", 0, usc_title=8, usc_section="1101"),
        _stated_row("5000-AA00", "200504", 1, usc_title=8, usc_section="999999"),
        _stated_row("5000-AA00", "200504", 2, usc_title=30, usc_section="1740"),
    ]
    references = [{"rin": "5000-AA00", "publication_id": "200510", "cfr_title": 8, "cfr_part": "215"}]
    counts = _write_placeholder_candidates(authorities, references, notes, _calendar(), oracle)
    assert counts["candidates_refuted_by_oracle"] == 2
    assert authorities[0]["placeholder_candidate_authorities"] == "usc:8:1101"
    assert counts["published"] == 1

    # Negative fixture, and the fence's one-sidedness: the gate refuses only
    # what the oracle DENIES. A tree with no oracle refuses nothing rather
    # than everything, and the record publishes exactly as it did before.
    for row in authorities:
        row["placeholder_candidate_authorities"] = None
    unfenced = _write_placeholder_candidates(authorities, references, notes, _calendar(), None)
    assert unfenced["candidates_refuted_by_oracle"] == 0
    assert authorities[0]["placeholder_candidate_authorities"] == (
        "usc:30:1740; usc:8:1101; usc:8:999999"
    )


def test_placeholder_candidates_gate_drops_only_the_offending_candidate() -> None:
    """Where the intersection carries BOTH a too-late public law and an
    ordinary U.S.C. candidate, the gate drops the law and still publishes
    the rest -- one bad candidate does not cost the whole record."""

    notes = _FakeNotes(
        held={(8, "215")},
        notes={(8, "215"): [("usc", "8:1104"), ("public_law", "98-1")]},
    )
    authorities = [
        _unstated_row("3000-AA01", "198010", 0),
        # A sibling edition stating BOTH candidates the note offers, so the
        # intersection carries both -- "strictly more" than this (empty)
        # record either way.
        _stated_row("3000-AA01", "199004", 0, usc_title=8, usc_section="1104"),
        _stated_row("3000-AA01", "199004", 1, authority_type="public_law", public_law="98-1"),
    ]
    references = [{"rin": "3000-AA01", "publication_id": "198010", "cfr_title": 8, "cfr_part": "215"}]
    calendar = _SeriesCalendar({1980: 96}, {}, {})
    counts = _write_placeholder_candidates(authorities, references, notes, calendar, _oracle())
    assert counts["published"] == 1
    assert counts["candidates_gated_by_edition"] == 1
    assert counts["candidates_refuted_by_oracle"] == 0, "8 U.S.C. 1104 is a real section"
    assert authorities[0]["placeholder_candidate_authorities"] == "usc:8:1104"


# --------------------------------------------------------------------------- #
# 6. The corpus receipts these five units move
#
# Every unit above is proved on fixtures, which says what the code DOES and
# nothing about how much of the corpus it touches: a change that took the C3
# promotion from 219 rows to 7,851 would leave every test above green. These
# read the built table's own receipt.
#
# **The numbers are measured, not guessed, and the integrator finalises them.**
# Each was measured 2026-08-31 by running the unit itself over the artifact on
# disk at that moment; the shared rebuild is what writes them into a receipt,
# and any that moves there is a finding for the integrator to explain rather
# than a pin to quietly re-cut. Two of the three ride the pinned U.S.C.
# section oracle, whose artifact and code were being re-cut in the same wave.


@cache
def _receipt() -> dict:
    path = ARTIFACT / "receipt.json"
    if not path.is_file():
        pytest.skip("the derived Parquet artifact is not built")
    return json.loads(path.read_text(encoding="utf-8"))


def _declared(key: str):
    declared = _receipt()["contract"]["declaredClassifications"]
    if key not in declared:
        pytest.skip(f"the built artifact predates {key}; the integrator's rebuild writes it")
    return declared[key]


def test_the_c3_promotion_receipt_is_the_measured_census() -> None:
    """1,417 rows reach this fence; 200 publish and 1,217 refuse, for four
    different reasons kept apart. Measured 2026-08-31 over the then-current
    build. RIDES THE SECTION ORACLE: the same rows read 217 / 14 / 1,186
    under the oracle of a week earlier, and 217 -> 200 is this wave's
    stated-tail refusal plus the binding."""

    assert _declared("uscC3PromotionRows") == {
        "promoted": 200,
        "ambiguous": 0,
        "witnessless": 1_179,
        "unbound": 21,
        "stated_tail_refused": 17,
    }


def test_the_placeholder_candidate_receipt_is_the_measured_census() -> None:
    """1,279 placeholder rows publish a candidate; 23 candidates are refused
    by the section oracle across 15 of them, and no row loses its whole
    intersection to either gate. The approval-date gate fires on nothing in
    this corpus -- no public-law candidate reaches an intersection at all --
    which is the honest reading of a guard that is insurance rather than a
    repair."""

    assert _declared("placeholderCandidateRows") == {
        "published": 1_279,
        "rows_withheld": 0,
        "candidates_gated_by_edition": 0,
        "candidates_refuted_by_oracle": 23,
    }


def test_the_usc_slot_reading_receipt_is_the_measured_census() -> None:
    """190 reg-suffix rows, every one witnessed by its own rule's CFR_LIST,
    and 1,685 chapter-in-slot rows -- the ones the oracle does NOT also
    verdict ``exists``, which is the whole fence."""

    # Rebuild #15 (2026-09-01 wave, REF-062): chapter-in-slot 1,685 -> 1,625
    # (-60), exactly the rows whose authority_text carried a dotted number
    # and were reading a truncated section -- zero dotted-text rows remain
    # in this reading now, which is the reg-dot fence's whole effect here.
    # reg-suffix is untouched: its own witness is the CFR_LIST join, not
    # the dot.
    assert _declared("uscSlotReadingRows") == {"reg-suffix": 190, "chapter-in-slot": 1_625}


def test_the_act_derived_unattested_rider_matches_the_current_oracle() -> None:
    """The rider in ``_judge_act_derived_sections`` says 3 act-derived rows
    are not attested at their citing edition, where the 2026-08-24 wave said
    19. The 16 that moved are the CWA title-33 rows at edition 201210, which
    the annual extractor's case fix finally reads.

    The fact the prose rests on is asserted directly against the IN-TREE
    oracle, because that is what the sentence claims and it needs no build.
    The receipt is then read as a PAIR of exact numbers chosen by which
    oracle wrote the artifact -- 19 before the re-cut, 3 after -- the same
    discipline ``_act_resolution_landed`` keeps next door: both readings are
    pins, any other number still fails, and the day the rebuild lands nothing
    here has to be touched. Delete the first number once it has."""

    oracle = _oracle()
    if oracle is None:
        pytest.skip("the pinned section oracle is not in this checkout")
    # The extractor fix, at the specimen: title 33 is printed in the 2012
    # annual volume (member `2012USC33.htm`, uppercase, the twelve files the
    # lowercase-only matcher skipped) and 33 U.S.C. 1251 attests there.
    verdict = oracle.section_verdict(33, "1251", 2012)
    assert verdict.verdict == "exists"
    assert verdict.attested_at_edition is True, "the 2012 title-33 volume is read"

    assert _declared("actSectionExistsNotAtEditionRows") in {19, 3}, (
        "19 is the pre-re-cut artifact, 3 is what the in-tree oracle produces"
    )
    assert _declared("actSectionVerdictRows")["absent"] == 0
    assert _declared("actSectionVerdictRows")["unknown"] == 0
    assert _declared("actSectionVerdictRows")["exists"] in {5_657, 6_768}


def test_the_promotion_outcomes_are_a_closed_named_set() -> None:
    """The receipt's key set is the module's own tuple, so a new outcome
    cannot arrive unnamed and un-pinned."""

    assert set(_declared("uscC3PromotionRows")) == set(USC_C3_PROMOTION_OUTCOMES)
