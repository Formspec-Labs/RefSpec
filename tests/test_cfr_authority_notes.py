"""The publisher's authority note for a rule's own CFR part, read from the pin."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from refspec.registry.cfr_authority_notes import (
    CFR_AUTHORITY_NOTES_ARTIFACT,
    FAMILIES,
    NEAR_MISS_MAX_EDITS,
    NOTES_BYTE_LENGTH,
    NOTES_ENDPOINT,
    NOTES_EXPECTED_RECORDS,
    NOTES_FETCHED,
    NOTES_SHA256,
    VERDICTS,
    CfrAuthorityNotes,
    Citation,
    _section_order,
    act_citation,
    cfr_citation,
    normalize_part,
    note_body,
    public_law_citation,
    read_note_citations,
    usc_citation,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CACHE = REPOSITORY_ROOT / CFR_AUTHORITY_NOTES_ARTIFACT

pytestmark = pytest.mark.skipif(not CACHE.is_file(), reason="the pinned eCFR authority-note cache is not present")


@pytest.fixture(scope="module")
def notes() -> CfrAuthorityNotes:
    return CfrAuthorityNotes.from_repository(REPOSITORY_ROOT)


def test_the_cache_is_the_bytes_this_module_pins(notes: CfrAuthorityNotes) -> None:
    """Digest, byte length and record count, all three, on every load."""

    assert notes.sha256 == NOTES_SHA256
    assert notes.byte_length == NOTES_BYTE_LENGTH
    assert len(notes.records) == NOTES_EXPECTED_RECORDS == 8_240
    # The provenance a consumer needs is in every record, not just the module
    # docstring: when, and from which request.
    assert {record.fetched for record in notes.records} == {NOTES_FETCHED} == {"2026-08-24"}
    # ONE FETCH DAY, 49 ISSUE DATES. The endpoint template cannot be filled in
    # by this module because the date belongs to the document, so what is held
    # true is the template against every record's own concrete URL: 49 distinct
    # URLs, one per title, each one the template with that title's issue date.
    urls = {record.api_url for record in notes.records}
    assert len(urls) == 49
    head, rest = NOTES_ENDPOINT.split("{issue_date}")
    middle, tail = rest.split("{title}")
    pattern = re.compile(
        re.escape(head) + r"(\d{4}-\d{2}-\d{2})" + re.escape(middle) + r"(\d{1,2})" + re.escape(tail)
    )
    matched = [pattern.fullmatch(url) for url in sorted(urls)]
    assert all(matched), "every record's URL is the endpoint this module states"
    assert {int(m.group(2)) for m in matched} == set(range(1, 51)) - {35}, "title 35 is reserved"
    # The dates run from an unamended 2015 title to the fetch week, and none of
    # them is the fetch date on every row.
    assert min(m.group(1) for m in matched) == "2024-05-17"
    assert max(m.group(1) for m in matched) == "2026-08-20"
    assert NOTES_ENDPOINT.format(issue_date="2026-08-19", title=21) == notes.note(21, "310").api_url
    # NOTHING WAS TRUNCATED. Generation 1 captured 211 of its 287 responses to
    # a 128 KB head; the full-title documents were read whole, so the flag is
    # false on every row -- carried rather than dropped, because a re-fetch
    # that started truncating again would say so here.
    assert sum(record.raw_truncated_at_128k for record in notes.records) == 0
    assert all(len(record.raw_sha256) == 64 for record in notes.records)
    # One digest per title, not per part: the row names the document it was cut
    # from, and 49 documents answered.
    assert len({record.raw_sha256 for record in notes.records}) == 49


def test_a_drifted_cache_refuses_instead_of_answering(tmp_path: Path) -> None:
    """One file, so there is no way to authenticate part of it."""

    drifted = tmp_path / "ecfr-authority-notes.jsonl"
    drifted.write_bytes(CACHE.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="pinned eCFR authority-note cache drifted"):
        CfrAuthorityNotes.from_file(drifted)


def test_the_reader_reads_the_publishers_own_words_on_21_cfr_310(notes: CfrAuthorityNotes) -> None:
    """The note quoted verbatim, and every citation the grammar takes out of it."""

    note = notes.note(21, "310")
    assert note.authority_note == (
        "Authority: 21 U.S.C. 321, 331, 351, 352, 353, 355, 360b-360f, 360j, 360hh-360ss, "
        "361(a), 371, 374, 375, 379e, 379k-l; 42 U.S.C. 216, 241, 242(a), 262."
    )
    assert {(citation.family, citation.identity) for citation in note.citations} == {
        ("usc", "21:321"),
        ("usc", "21:331"),
        ("usc", "21:351"),
        ("usc", "21:352"),
        ("usc", "21:353"),
        ("usc", "21:355"),
        ("usc", "21:360b"),
        ("usc", "21:360j"),
        ("usc", "21:360hh"),
        ("usc", "21:361"),
        ("usc", "21:371"),
        ("usc", "21:374"),
        ("usc", "21:375"),
        ("usc", "21:379e"),
        ("usc", "21:379k"),
        ("usc", "42:216"),
        ("usc", "42:241"),
        ("usc", "42:242"),
        ("usc", "42:262"),
    }
    # A pinpoint is not identity: "361(a)" is section 361, and "242(a)" is 242.
    # The section fence beside this join says the same thing, so a citation to
    # 21 U.S.C. 361 reads present rather than one edit away from something.
    assert notes.judge(usc_citation(21, "361"), [(21, "310")]).verdict == "present"
    # And the two the campaign named: 321p for 321(p) and 371a for 371(a), each
    # one edit from a section this very note lists.
    assert notes.judge(usc_citation(21, "321p"), [(21, "310")]).verdict == "near-miss"
    assert notes.judge(usc_citation(21, "371a"), [(21, "310")]).verdict == "near-miss"


def test_the_reader_reads_49_cfr_192_as_the_publisher_writes_it_today(notes: CfrAuthorityNotes) -> None:
    """The note review A quotes is not the note the publisher prints now.

    Review A's row 6 reads the whole of RIN 2137-AE60's list -- "40 USC 5103,
    60102 ... 60137" -- as 49 CFR 192's note verbatim, with "40" typed for
    "49". The note as fetched 2026-08-20 no longer enumerates those sections;
    it says "60101 et. seq." So the corrected reading is absent from the note
    too, and this test states that rather than pretending the join confirms
    what the reviewer confirmed by hand from the 2010 edition.
    """

    note = notes.note(49, "192")
    assert note.authority_note == "Authority: 30 U.S.C. 185(w)(3), 49 U.S.C. 5103, 60101 et. seq., and 49 CFR 1.97."
    assert {(citation.family, citation.identity) for citation in note.citations} == {
        ("usc", "30:185"),
        ("usc", "49:5103"),
        ("usc", "49:60101"),
        ("cfr", "49:1"),
    }
    part = [(49, "192")]
    assert notes.judge(usc_citation(49, "5103"), part).verdict == "present"
    assert notes.judge(usc_citation(49, "60101"), part).verdict == "present"
    # "et seq." is NOT a range: reading it as one would make every section
    # above 60101 present and delete the finding.
    assert notes.judge(usc_citation(49, "60137"), part).verdict == "absent"
    # 60102 is the one exception in that list, and it is an accident of
    # arithmetic rather than evidence: it sits one edit from the 60101 the note
    # DOES name. The near-miss bucket is like this everywhere -- 12.9% precise
    # by text on the campaign's own adjudication -- which is why it is a lead.
    assert notes.judge(usc_citation(49, "60102"), part).verdict == "near-miss"


def test_the_cache_now_holds_the_part_that_settled_the_opening_specimen(notes: CfrAuthorityNotes) -> None:
    """45 CFR 12a is the campaign's own headline, and the hole is closed.

    The greedy set-cover selected the parts covering the most agenda rows; 45
    CFR 12a is a tiny part it never reached, so the campaign fetched that one
    note by hand and generation 1 never carried it. The predecessor of this
    test asserted `not notes.holds(45, "12a")` and pinned the gap so it stayed
    a known hole rather than an unexplained NULL. **Generation 2 reads every
    part the register publishes, so the hole is now the finding**: the note is
    here, in the publisher's own words, and RIN 0991-AC14 -- which names no
    other part, and whose verdict column was NULL for that reason alone -- is
    answered.
    """

    assert notes.holds(45, "12a")
    note = notes.note(45, "12a")
    assert note.authority_note == "Authority: 42 U.S.C. 11411; 40 U.S.C. 550."
    assert note.authority_level == "part"
    assert {(citation.family, citation.identity) for citation in note.citations} == {
        ("usc", "42:11411"),
        ("usc", "40:550"),
    }
    # The verdict the whole campaign opened on, asked of the cache rather than
    # of a note transcribed into a test.
    assert notes.judge(usc_citation(40, "550"), [(45, "12a")]).verdict == "present"
    assert notes.judge(usc_citation(42, "11411"), [(45, "12a")]).verdict == "present"
    # And it is still a verdict and not a repair: a section the note does not
    # name reads absent from the same note.
    assert notes.judge(usc_citation(40, "551"), [(45, "12a")]).verdict == "near-miss"
    assert notes.judge(usc_citation(41, "550"), [(45, "12a")]).verdict == "near-miss", "the title is a character"
    assert notes.judge(usc_citation(12, "550"), [(45, "12a")]).verdict == "absent", "two edits is not one"
    assert notes.judge(usc_citation(40, "3141"), [(45, "12a")]).verdict == "absent"


def test_a_note_range_covers_the_sections_between_its_endpoints(notes: CfrAuthorityNotes) -> None:
    """10 CFR 430 says "6291-6309", so the 6295 a rule cites is named by it."""

    assert notes.note(10, "430").authority_note == "Authority: 42 U.S.C. 6291-6309; 28 U.S.C. 2461 note."
    part = [(10, "430")]
    assert notes.judge(usc_citation(42, "6291"), part).verdict == "present"
    assert notes.judge(usc_citation(42, "6295"), part).verdict == "present"
    assert notes.judge(usc_citation(42, "6309"), part).verdict == "present"
    # Past the endpoint is past the claim. 10 CFR 431's note runs to 6317 and
    # says so; 430's does not, which is review E's row 9 in the publisher's own
    # words.
    assert notes.judge(usc_citation(42, "6317"), part).verdict == "absent"
    assert notes.judge(usc_citation(42, "6317"), [(10, "431")]).verdict == "present"


def test_near_miss_is_one_edit_on_the_identity_including_the_title(notes: CfrAuthorityNotes) -> None:
    """The survey's definition, and the title counts as a character.

    17 CFR part 1's note is a list of title SEVEN sections, and the corpus
    writes "17 USC 12a" -- the CFR title typed where the U.S.C. title belongs.
    Spelling the identity "title:section" is what makes that one edit.
    """

    assert NEAR_MISS_MAX_EDITS == 1
    part = [(17, "1")]
    assert notes.judge(usc_citation(7, "12a"), part).verdict == "present"
    assert notes.judge(usc_citation(17, "12a"), part).verdict == "near-miss"
    # Two edits is not a near miss, and neither is a section nothing in the
    # note resembles.
    assert notes.judge(usc_citation(17, "12ab"), part).verdict == "absent"
    assert notes.judge(usc_citation(7, "5555"), part).verdict == "absent"


def test_a_rule_amending_several_parts_is_authorised_by_all_of_their_notes(notes: CfrAuthorityNotes) -> None:
    """Present anywhere settles it; an absence names the first part in citation order.

    RIN 2040-AD08 amends 40 CFR 122, 123, 136 and 141, and the cache holds all
    four. `33 USC 1361a` -- review G's row 1, where the filer transcribed
    "sec. 501(a)" into the `1361a` slot -- is in none of them.
    """

    parts = [(40, "122"), (40, "123"), (40, "136"), (40, "141")]
    absent = notes.judge(usc_citation(33, "1361a"), parts)
    assert (absent.verdict, absent.cited_as) == ("absent", "40 CFR 122")
    # 40 CFR 136's note is where the review's evidence is, and it names the act
    # and the Public Law rather than the section the filer wrote.
    note = notes.note(40, "136")
    assert "501(a), Pub. L. 95-217, 91 Stat. 1566" in note.authority_note
    assert notes.judge(public_law_citation("95-217"), [(40, "136")]).verdict == "present"
    assert notes.judge(act_citation("Federal Water Pollution Control Act Amendments of 1972"), parts).verdict == "present"
    # Present outranks absent whichever part carries it: 33 U.S.C. 1251 is in
    # 136's note and the verdict names 136, not the first part in the list.
    present = notes.judge(usc_citation(33, "1251"), parts)
    assert present.verdict == "present"
    assert present.cited_as in {"40 CFR 122", "40 CFR 123", "40 CFR 136", "40 CFR 141"}


def test_the_review_specimen_the_note_catches_is_the_one_that_passed_silently(notes: CfrAuthorityNotes) -> None:
    """`40 U.S.C. 5103` exists, so no section fence flags it. The note does.

    Review E's row 6: RIN 2137-AE60's whole list is title 49 typed as 40, and
    the sibling `40 U.S.C. 5103` (Capitol Grounds) is a REAL section, so the
    U.S.C. section oracle answers "exists" and nothing accuses it. Its own
    part's note names 49 U.S.C. 5103, one edit away -- which is the class of
    silent false presence the review flagged hardest and no other column here
    can see.
    """

    part = [(49, "192")]
    assert notes.judge(usc_citation(40, "5103"), part).verdict == "near-miss"
    assert notes.judge(usc_citation(40, "60137"), part).verdict == "absent"


def test_coverage_is_every_part_the_register_publishes_a_note_for(notes: CfrAuthorityNotes) -> None:
    """8,240 parts across all 49 non-reserved titles, where the set-cover reached 287."""

    coverage = notes.coverage()
    assert len(coverage) == NOTES_EXPECTED_RECORDS
    assert len(set(coverage)) == len(coverage)
    assert (21, "310") in coverage and (49, "192") in coverage and (40, "136") in coverage
    assert (45, "12a") in coverage, "generation 1's own named hole"
    # All 49 non-reserved titles are represented, where generation 1 reached 39;
    # a lettered part is one of them, which is why a part is a string and never
    # an int.
    assert len({title for title, _part in coverage}) == 49
    assert {title for title, _part in coverage} == set(range(1, 51)) - {35}
    assert (8, "274a") in coverage


def test_the_section_order_is_the_oracles_over_every_section_the_notes_name() -> None:
    """The ordering rule is restated here; this holds the copy true.

    ``usc_section_oracle._section_key`` is private, so the three-line rule is
    written out again rather than imported -- the same arrangement that module
    makes with the grammar's dash table. Run over every section the 8,240 notes
    name, in both directions -- 5,820 of them, where generation 1's 287 notes
    named 2,241.

    It moved twice on 2026-08-24 and in both directions. The #46 list-tail
    fences took it from 5,847 to 5,802: 45 sections that were never sections --
    compilation years and pages ("3 CFR, 1980 Comp., p. 277"), the bare part of
    a dotted CFR reference ("7 CFR 2.22, 2.80, and 371.4"), and the VOLUME of a
    treaty or a case reporter behind a comma ("340 U.S. 462", "19 U.S.T.
    6223"); 1,282 note citations went with them, in 806 notes, and none
    arrived. The range reader then took it to 5,820, and those 18 are ENDS:
    a note's own spans reach their far endpoint now, so a section a note
    covers is found where it was one edit away before. The citation COUNT does
    not move with them -- a span is one citation whichever end it reaches --
    and stands at 35,043; ``CfrAuthorityNotes``'s own docstring carries it.
    """

    from refspec.registry.usc_section_oracle import _section_key

    notes = CfrAuthorityNotes.from_repository(REPOSITORY_ROOT)
    sections = {
        citation.identity.split(":", 1)[1]
        for note in notes.records
        for citation in note.citations
        if citation.family == "usc"
    } | {citation.span_end for note in notes.records for citation in note.citations if citation.span_end}
    assert len(sections) == 5_820
    assert all(_section_order(section) == _section_key(section) for section in sections)


def test_a_citation_states_a_family_this_module_declares() -> None:
    assert set(FAMILIES) == {"usc", "public_law", "cfr", "act"}
    assert VERDICTS == ("present", "near-miss", "absent")
    with pytest.raises(ValueError, match="undeclared citation family"):
        Citation(family="executive_order", identity="12866")
    with pytest.raises(ValueError, match="not a citation"):
        Citation(family="usc", identity="")
    with pytest.raises(ValueError, match="only a U.S.C. citation carries a span"):
        Citation(family="public_law", identity="95-217", span_end="99")


def test_an_identity_is_None_where_the_row_states_no_identity() -> None:
    """Half a citation is not a citation, and the builder must be able to tell."""

    assert usc_citation(21, None) is None
    assert usc_citation(None, "371") is None
    assert public_law_citation(None) is None
    assert cfr_citation(49, None) is None
    assert act_citation("") is None
    # A part is a join key: leading zeros are spelling, a letter is identity.
    assert normalize_part("0718") == "718"
    assert normalize_part("12a") == "12a"
    assert normalize_part("0") == "0"
    assert normalize_part(None) is None
    assert cfr_citation(49, "0001").identity == "49:1"


def test_the_publishers_elided_title_carries_across_its_own_semicolon(notes: CfrAuthorityNotes) -> None:
    """50 CFR 17's note lists the Endangered Species Act, and it read absent.

    The whole note is "16 U.S.C. 1361-1407; 1531-1544; and 4201-4245". The
    grammar carries a title across a COMMA and not across a semicolon -- write
    the same list with commas and it reads three ranges -- so the separator the
    publisher happened to choose decided whether 16 U.S.C. 1531 was in its own
    part's note. It was not: 8,126 rows citing the ESA read "absent" against a
    note that lists it in plain sight, the largest single block in that bucket.
    """

    note = notes.note(50, "17")
    assert note.authority_note == (
        "Authority: 16 U.S.C. 1361-1407; 1531-1544; and 4201-4245, unless otherwise noted."
    )
    assert {citation.identity for citation in note.citations if citation.family == "usc"} == {
        "16:1361",
        "16:1531",
        "16:4201",
    }
    part = [(50, "17")]
    assert notes.judge(usc_citation(16, "1531"), part).verdict == "present"
    assert notes.judge(usc_citation(16, "1544"), part).verdict == "present", "the carried range's far end"
    assert notes.judge(usc_citation(16, "1545"), part).verdict == "absent", "and one past it is not"


def test_the_title_carry_fires_on_these_segments_and_nothing_else(notes: CfrAuthorityNotes) -> None:
    """The guard is what keeps a carry from inventing a note citation.

    A segment must state no citation of any kind on its own AND be nothing but
    section tokens and separators. Over the whole register that is 124 segments
    in 58 parts, enumerated here so a widened guard has to say so. All 18 that
    generation 1's 287 notes carried are in this set unchanged; the other 106
    are what reading every part rather than a set-cover of 287 turned up.

    Computed the way :func:`read_note_citations` computes it -- the FULL guard,
    not just the section-list shape. The two differ on exactly two segments
    (45 CFR 1616's "1006(b)(4)" and "1006(b)(6)", where no title has been
    stated yet), which is why the shape alone is not what this test asks.
    """

    from refspec.registry.cfr_authority_notes import (
        _SECTION_LIST_ONLY,
        parse_authority_citation,
    )

    def carried_segments(note) -> list[str]:
        title = None
        out = []
        for segment in note_body(note.authority_note).split(";"):
            parsed = parse_authority_citation(segment)
            stated = [one for one in parsed if one.authority_type == "usc" and one.usc_title is not None]
            if stated:
                title = stated[-1].usc_title
            elif (
                title is not None
                and all(one.authority_type in {"other", "unstated"} for one in parsed)
                and _SECTION_LIST_ONLY.match(segment.strip())
            ):
                out.append(segment.strip())
        return out

    carried = {(note.cited_as, segment) for note in notes.records for segment in carried_segments(note)}
    assert carried == {
        ('10 CFR 435', '6834-6836'),
        ('10 CFR 733', '7254'),
        ('10 CFR 733', '7256'),
        ('10 CFR 820', '2282(a)'),
        ('10 CFR 820', '7191'),
        ('12 CFR 1238', '4513'),
        ('12 CFR 1238', '4526'),
        ('12 CFR 1238', '4612'),
        ('12 CFR 1238', '5365(i).'),
        ('12 CFR 1248', '1716'),
        ('12 CFR 1248', '4511'),
        ('12 CFR 1248', 'and 4526.'),
        ('12 CFR 263', '1639e(K)'),
        ('12 CFR 307', '1818(q)'),
        ('12 CFR 324', '5371'),
        ('12 CFR 324', '5412'),
        ('12 CFR 333', '1817(i)'),
        ('12 CFR 333', '1818'),
        ('12 CFR 351', 'and 5412.'),
        ('12 CFR 371', '1820(g)'),
        ('12 CFR 371', '1831g'),
        ('12 CFR 371', '1831i'),
        ('12 CFR 371', 'and 1831s.'),
        ('12 CFR 390', '1462a'),
        ('12 CFR 390', '1463'),
        ('12 CFR 390', '1464'),
        ('12 CFR 390', '78l'),
        ('12 CFR 390', '78m'),
        ('12 CFR 390', '78n'),
        ('12 CFR 390', '78p'),
        ('12 CFR 390', '78w.'),
        ('12 CFR 46', '1463(a)(2)'),
        ('12 CFR 46', '5365(i)(2)'),
        ('12 CFR 46', 'and 5412(b)(2)(B).'),
        ('14 CFR 121', '46105'),
        ('14 CFR 73', '40103, 40113, 40120'),
        ('19 CFR 18', '1646a'),
        ('22 CFR 41', '1102'),
        ('22 CFR 41', '1103, 1104'),
        ('22 CFR 41', '1182'),
        ('22 CFR 41', '1184'),
        ('22 CFR 41', '1201'),
        ('22 CFR 41', '1258'),
        ('22 CFR 41', '1323'),
        ('22 CFR 41', '1361'),
        ('22 CFR 41', '2651a.'),
        ('25 CFR 163', 'and 3101-3120.'),
        ('28 CFR 540', '551, 552a'),
        ('28 CFR 58', '1302, 1328(g)'),
        ('29 CFR 2578', '1103(d)(1).'),
        ('29 CFR 2578', '1104(a)'),
        ('30 CFR 553', '2716a'),
        ('32 CFR 634', '89-670'),
        ('32 CFR 634', '91-605'),
        ('32 CFR 634', 'and 93-87.'),
        ('33 CFR 155', '70034'),
        ('34 CFR 674', '1087dd(h)(1)(D).'),
        ('39 CFR 3007', '3661.'),
        ('39 CFR 3007', '503'),
        ('39 CFR 3007', '504'),
        ('39 CFR 3010', '3661.'),
        ('39 CFR 3010', '503'),
        ('39 CFR 3010', '504'),
        ('39 CFR 3012', '3661(c)'),
        ('39 CFR 3012', '3662.'),
        ('39 CFR 3012', '503'),
        ('39 CFR 3012', '504'),
        ('39 CFR 3013', '3651(c)'),
        ('39 CFR 3013', '3652(d).'),
        ('39 CFR 3013', '504'),
        ('39 CFR 3020', '3661.'),
        ('39 CFR 3020', '503'),
        ('39 CFR 3020', '504'),
        ('39 CFR 3022', '3662.'),
        ('39 CFR 3024', '3662.'),
        ('39 CFR 3025', '503.'),
        ('39 CFR 3030', '3622.'),
        ('39 CFR 3035', '3633.'),
        ('39 CFR 3040', '3622'),
        ('39 CFR 3040', '3631'),
        ('39 CFR 3040', '3642'),
        ('39 CFR 3040', '3682.'),
        ('39 CFR 3045', '3641.'),
        ('39 CFR 959', '601-606'),
        ('40 CFR 423', '1311'),
        ('40 CFR 423', '1316'),
        ('40 CFR 423', '1317'),
        ('40 CFR 423', '1318 and 1361.'),
        ('41 CFR 303-70', '5741-5742'),
        ('42 CFR 1001', '1320a-7'),
        ('42 CFR 1001', '1320a-7b'),
        ('42 CFR 1001', '1395hh'),
        ('42 CFR 1001', '1395u(j)'),
        ('42 CFR 1001', '1395u(k)'),
        ('42 CFR 1001', '1395w-104(e)(6), 1395y(d)'),
        ('42 CFR 1001', '1395y(e)'),
        ('43 CFR 8360', 'and 1281c'),
        ('45 CFR 1616', '2996e(b)(6)'),
        ('45 CFR 1632', '2996(g)(e)'),
        ('45 CFR 1632', '2996f(a)(2)(C)'),
        ('45 CFR 1632', '2996f(a)(3)'),
        ('45 CFR 1634', '2996f(a)(3).'),
        ('45 CFR 2522', '12651b-12651d'),
        ('46 CFR 502', '591-596'),
        ('48 CFR 911', '2282a'),
        ('48 CFR 911', '2282b'),
        ('48 CFR 911', '2282c'),
        ('48 CFR 950', '2282a'),
        ('48 CFR 950', '2282b'),
        ('48 CFR 950', '2282c'),
        ('48 CFR 952', '2282a'),
        ('48 CFR 952', '2282b'),
        ('48 CFR 952', '2282c'),
        ('48 CFR 970', '2282a'),
        ('48 CFR 970', '2282b'),
        ('48 CFR 970', '2282c'),
        ('49 CFR 175', '44701'),
        ('49 CFR 581', '322, 30111, 30115, 30117 and 30166'),
        ('5 CFR 2418', '3716, 3717, 3718, 3720A, 3720D.'),
        ('50 CFR 17', '1531-1544'),
        ('50 CFR 22', '1531-1544.'),
        ('50 CFR 22', '703-712'),
        ('50 CFR 70', '460k'),
        ('8 CFR 213', '1183'),
    }
    assert len({part for part, _segment in carried}) == 58
    # Generation 1's own 18, unchanged -- the widening added carries and moved
    # none. 50 CFR 17's is the one that put the Endangered Species Act into its
    # own part's note.
    assert {
        ("12 CFR 324", "5371"), ("12 CFR 324", "5412"), ("14 CFR 121", "46105"),
        ("22 CFR 41", "1102"), ("22 CFR 41", "1103, 1104"), ("22 CFR 41", "1182"),
        ("22 CFR 41", "1184"), ("22 CFR 41", "1201"), ("22 CFR 41", "1258"),
        ("22 CFR 41", "1323"), ("22 CFR 41", "1361"), ("22 CFR 41", "2651a."),
        ("28 CFR 540", "551, 552a"), ("33 CFR 155", "70034"), ("48 CFR 970", "2282a"),
        ("48 CFR 970", "2282b"), ("48 CFR 970", "2282c"), ("50 CFR 17", "1531-1544"),
    } <= carried
    # 33 CFR 155's is the one review I read by hand from the other side: the
    # filers write "33 U.S.C. 70034" (review I, rows 6 and 10) and the note
    # says 46 U.S.C. 70034, the title the section moved to in 2018. The carry
    # is what puts it in the note at all -- and the filer's own reading still
    # reads ABSENT, because "33" to "46" is two substitutions and not one edit.
    # A near miss is a near miss; a stale title prefix is not.
    assert notes.judge(usc_citation(46, "70034"), [(33, "155")]).verdict == "present"
    assert notes.judge(usc_citation(33, "70034"), [(33, "155")]).verdict == "absent"


def test_the_two_carried_titles_the_publishers_own_elision_gets_wrong(notes: CfrAuthorityNotes) -> None:
    """Two of the 124 carries read a label the publisher elided and meant otherwise.

    Recorded rather than repaired, and both are the publisher's elision rather
    than any filer's error. A guard that could tell these two from the other
    122 would need a Code roster and a memory of which label was elided, which
    this reader does not have; what it does have is the measured cost of each,
    which is what makes leaving them the cheaper error rather than the lazier
    one.
    """

    # (1) 22 CFR 41's list changes TITLE at the last item and does not say so.
    # "8 U.S.C. 1101; 1102; 1103, 1104; ... 1323; 1361; 2651a." -- and 2651a is
    # 22 U.S.C. 2651a, the Secretary of State's own authority. The carry reads
    # it as 8 U.S.C. 2651a, which is not a section of title 8 and not what the
    # note means. It costs nothing: no rule in this corpus cites 8 U.S.C. 2651a.
    note = notes.note(22, "41")
    assert note.authority_note.endswith("1323; 1361; 2651a.")
    assert "8:2651a" in {citation.identity for citation in note.citations}
    assert "22:2651a" not in {citation.identity for citation in note.citations}
    # And the guard's cost in the same note: "1185 note (Section 7209 of Pub.
    # L. 108-458, ...)" carries a parenthetical, so it is not a section list
    # and the title does not carry into it. 30 rows whose filers write "8 USC
    # 1185 note" read near-miss against a note that names exactly that.
    # Widening the guard to admit a parenthetical would admit prose, and prose
    # under a supplied title is how a note citation gets invented.
    assert "8 U.S.C. 1101; 1102" in note.authority_note and "1185 note (Section 7209" in note.authority_note
    assert notes.judge(usc_citation(8, "1185"), [(22, "41")]).verdict == "near-miss"

    # (2) 32 CFR 634, which generation 1 did not hold, elides **Pub. L.** and
    # not a U.S.C. title, so three Public Law numbers are read as section
    # RANGES of title 5. Two of them are ordered and therefore span, which is
    # why 5 U.S.C. 301 -- the most-cited section in the corpus -- reads present
    # against a note that never names it.
    note = notes.note(32, "634")
    assert note.authority_note == (
        "Authority: 10 U.S.C. 30112(g); 5 U.S.C. 2951; Pub. L. 89-564; 89-670; 91-605; and 93-87."
    )
    assert {citation.identity for citation in note.citations if citation.family == "usc"} == {
        "10:30112", "5:2951", "5:89", "5:91", "5:93-87",
    }
    assert notes.judge(usc_citation(5, "301"), [(32, "634")]).verdict == "present", "the false span"
    # The publisher's own Public Law reads present, correctly, from the one
    # segment that spells the label out.
    assert notes.judge(public_law_citation("89-564"), [(32, "634")]).verdict == "present"
    # THE COST, MEASURED: two RINs name 32 CFR 634 and carry 92 authority rows
    # between them. Their only title-5 citation is 5 U.S.C. 2951, which the
    # note names outright -- so no row in this corpus is judged by either false
    # span, and the defect is a candidate rather than a live error.
    assert notes.judge(usc_citation(5, "2951"), [(32, "634")]).verdict == "present"


def test_the_note_body_is_the_publishers_words_with_its_entities_decoded() -> None:
    """Every HTML entity ends in a semicolon, and a semicolon is what a note
    splits on -- so an undecoded entity splits a segment down the middle and
    the title carry reads the tail as a section list. Generation 1's 19 CFR
    part 4 is the sharpest case: "Pub. L. 108-7, Division B, Title II,&#xA7;
    211" segmented into a bare "211", which the carry read as 46 U.S.C. 211.
    Decoding deletes that phantom, which is the whole reason this function
    exists."""

    raw = "Authority: 19 U.S.C. 66; Pub. L. 108-7, Division B, Title II,&#xA7; 211; 46 U.S.C. 501."
    assert note_body(raw) == "19 U.S.C. 66; Pub. L. 108-7, Division B, Title II,§ 211; 46 U.S.C. 501."
    assert {citation.identity for citation in read_note_citations(raw) if citation.family == "usc"} == {
        "19:66",
        "46:501",
    }
    # And the other direction, on generation 2's own bytes: 36 CFR 59 writes
    # "L&amp;WCF Act of 1965", which reads as the "WCF Act" undecoded and as
    # the Land and Water Conservation Fund Act decoded.
    assert {citation.identity for citation in read_note_citations(
        "Authority: Sec. 6, L&amp;WCF Act of 1965 as amended; Pub. L. 88-578; 78 Stat. 897; 16 U.S.C. 4601-4 et seq."
    ) if citation.family == "act"} == {"l&wcf act of 1965"}


def test_decoding_the_publishers_ampersand_costs_36_cfr_230_its_second_section(
    notes: CfrAuthorityNotes,
) -> None:
    """The one place decoding LOSES a real citation, and what it costs.

    36 CFR 230's whole note is "16 U.S.C. 2103(d) &amp; 2109(e)." Undecoded it
    splits into "…2103(d) &amp" and "2109(e).", and the carry supplies title 16
    to the tail; decoded it is one segment, and the grammar does not continue a
    section list across "&". So the publisher's own text, spelled correctly,
    reads one section where the mis-spelling read two.

    The cost is two rows and they are named here rather than absorbed: the
    corpus cites 16 U.S.C. 2109 exactly twice, both under rules that name 36
    CFR 230, and the filers write it "16 U.S.C. 2103(d) and 2109(e)" -- the
    same list the note writes with an ampersand. Both read ``near-miss``
    against a note that names it in plain sight. The repair belongs in the
    grammar's treatment of "&" as a list separator, not in a decision to leave
    the publisher's words mis-spelled, so this is a candidate and not a patch.
    """

    note = notes.note(36, "230")
    assert note.authority_note == "Authority: 16 U.S.C. 2103(d) &amp; 2109(e)."
    assert note_body(note.authority_note) == "16 U.S.C. 2103(d) & 2109(e)."
    assert {citation.identity for citation in note.citations} == {"16:2103"}
    part = [(36, "230")]
    assert notes.judge(usc_citation(16, "2103"), part).verdict == "present"
    assert notes.judge(usc_citation(16, "2109"), part).verdict == "near-miss", "the two rows this costs"
    # Undecoded, the carry would have supplied the title to the tail and the
    # same citation would have read present. Shown rather than asserted about,
    # so a change to either side of the trade breaks this test.
    assert {citation.identity for citation in read_note_citations(
        "Authority: 16 U.S.C. 2103(d) &amp;amp; 2109(e)."
    )} == {"16:2103", "16:2109"}


def test_a_subdivisions_note_is_the_parts_witness_and_says_so(notes: CfrAuthorityNotes) -> None:
    """The one judgement call the whole-register fetch forced, and its specimen.

    80 of the 8,240 parts state no authority under their own head and do state
    one under their FIRST subdivision. This reader takes that note as the
    part's witness. That is not a new behaviour: generation 1 read a per-part
    response top-down and stored the first ``<AUTH>`` it met, so 20 CFR 404 and
    416 and 5 CFR 550 -- three of the most-cited parts in the corpus -- were
    already being judged against a Subpart A note without anything saying so.
    Dropping them would have deleted verdicts rather than added any, which is
    the opposite of what widening the cache is for.

    What changed is that the arrangement is now stated: ``authority_level`` and
    ``authority_scope`` name it, so a consumer who wants only part-level
    authority can filter, and ``cfr_note_part`` naming "20 CFR 404" can be
    traced to the words that actually answered. An ``<AUTH>`` under a LATER
    subdivision is a different subdivision's authority and is not read at all.
    """

    subdivision = [note for note in notes.records if note.authority_level == "subdivision"]
    assert len(subdivision) == 80
    assert {note.authority_level for note in notes.records} == {"part", "subdivision"}
    assert all(note.authority_scope == "part" for note in notes.records if note.authority_level == "part")
    # 79 of the 80 name the subpart their note opens under. THE EIGHTIETH DOES
    # NOT, and it is stated rather than tidied: 36 CFR 704's note opens after
    # the part's first subdivision -- so it is not the part's own -- but that
    # subdivision is neither a SUBPART nor a SUBJGRP, so the extractor had no
    # label to report and left the scope at its "part" default. The level is
    # the load-bearing field and it is right; the scope is a name for a thing
    # the document did not name.
    named, unnamed = [n for n in subdivision if n.authority_scope != "part"], [
        n for n in subdivision if n.authority_scope == "part"
    ]
    assert len(named) == 79
    assert all(note.authority_scope.startswith("SUBPART ") for note in named)
    assert [note.cited_as for note in unnamed] == ["36 CFR 704"]
    assert unnamed[0].authority_note == "Authority: Pub. L. 102-307, 106 Stat. 267 (2 U.S.C. 179)."

    # The specimen: 20 CFR 404 is Social Security's own part and the second
    # most-cited part in the corpus. Its head states no authority; Subpart A
    # states this one, and it is what "42 U.S.C. 405" is judged against.
    note = notes.note(20, "404")
    assert (note.authority_level, note.authority_scope) == ("subdivision", "SUBPART A")
    assert note.authority_note == (
        "Authority: Secs. 203, 205(a), 216(j), and 702(a)(5) of the Social Security Act "
        "(42 U.S.C. 403, 405(a), 416(j), and 902(a)(5)) and 48 U.S.C. 1801."
    )
    assert notes.judge(usc_citation(42, "405"), [(20, "404")]).verdict == "present"
    assert notes.judge(usc_citation(42, "403"), [(20, "404")]).verdict == "present"
    # A verdict and never a repair here either: a section Subpart A does not
    # name is absent from it, whatever some later subpart of part 404 may say.
    assert notes.judge(usc_citation(42, "1320b"), [(20, "404")]).verdict == "absent"
    # The other two the campaign's own comparison named.
    assert notes.note(20, "416").authority_level == "subdivision"
    assert notes.note(5, "550").authority_level == "subdivision"
    # And the ordinary case is the overwhelming one.
    assert sum(1 for note in notes.records if note.authority_level == "part") == 8_160
