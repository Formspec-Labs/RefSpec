"""The pinned Unified Agenda edition series."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from refspec.registry.unified_agenda_editions import (
    UNIFIED_AGENDA_EDITION_PINS,
    UNIFIED_AGENDA_EXPECTED_EDITION_COUNT,
    UNIFIED_AGENDA_EXPECTED_RECORD_COUNT,
    UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS,
    UnifiedAgendaEditionError,
    UnifiedAgendaEditionPin,
    parse_unified_agenda_edition,
)

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "output" / "registry-real-data-sources" / "unified-agenda-editions"


def _payload(pin: UnifiedAgendaEditionPin) -> bytes:
    return (SOURCE_ROOT / f"REGINFO_RIN_DATA_{pin.file_stem}.xml").read_bytes()


def test_the_roster_is_the_whole_published_series() -> None:
    assert len(UNIFIED_AGENDA_EDITION_PINS) == UNIFIED_AGENDA_EXPECTED_EDITION_COUNT == 60
    ids = [pin.publication_id for pin in UNIFIED_AGENDA_EDITION_PINS]
    assert len(set(ids)) == len(ids), "an edition is pinned twice"
    assert min(ids) == "199510" and max(ids) == "202510"
    # Spring 2012 is not published. The twice-yearly series from Fall 1995
    # implies 61 editions; the publisher serves 60, and this is the missing one.
    assert "201204" not in set(ids)


def test_the_filename_is_not_authoritative_for_the_edition() -> None:
    """One legacy file breaks the YYYYMM naming; its records name it correctly."""

    odd = [pin for pin in UNIFIED_AGENDA_EDITION_PINS if pin.file_stem != pin.publication_id]
    assert [(pin.file_stem, pin.publication_id) for pin in odd] == [("2012", "201210")]


@pytest.mark.skipif(not SOURCE_ROOT.is_dir(), reason="pinned captures are not present")
@pytest.mark.slow
def test_every_pinned_edition_reads_back_exactly() -> None:
    total = 0
    for pin in UNIFIED_AGENDA_EDITION_PINS:
        payload = _payload(pin)
        assert "sha256:" + hashlib.sha256(payload).hexdigest() == pin.expected_sha256
        records = parse_unified_agenda_edition(payload, pin=pin)
        assert len(records) == pin.expected_record_count
        assert {record.publication_id for record in records} == {pin.publication_id}
        total += len(records)
    assert total == UNIFIED_AGENDA_EXPECTED_RECORD_COUNT == 241_726


@pytest.mark.skipif(not SOURCE_ROOT.is_dir(), reason="pinned captures are not present")
def test_the_two_mangled_editions_are_the_only_ones_needing_repair() -> None:
    """0x19 is a control character XML forbids; it appears twice in 981 MB.

    The repair is applied to the in-memory copy only, so the pinned digest
    still authenticates the bytes the publisher actually served.
    """

    carrying = [
        pin.publication_id for pin in UNIFIED_AGENDA_EDITION_PINS if b"\x19" in _payload(pin)
    ]
    assert tuple(carrying) == UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS == ("200404", "200410")
    for pin in UNIFIED_AGENDA_EDITION_PINS:
        if pin.publication_id in carrying:
            # Exactly one occurrence each, and the file parses once repaired.
            assert _payload(pin).count(b"\x19") == 1
            assert parse_unified_agenda_edition(_payload(pin), pin=pin)


@pytest.mark.skipif(not SOURCE_ROOT.is_dir(), reason="pinned captures are not present")
def test_a_drifted_capture_is_refused_rather_than_read() -> None:
    pin = UNIFIED_AGENDA_EDITION_PINS[0]
    payload = _payload(pin)
    with pytest.raises(UnifiedAgendaEditionError, match="byte length drifted"):
        parse_unified_agenda_edition(payload + b" ", pin=pin)
    swapped = payload.replace(b"<RIN>", b"<RIN>X", 1)
    assert len(swapped) != len(payload) or swapped != payload
    with pytest.raises(UnifiedAgendaEditionError):
        parse_unified_agenda_edition(swapped, pin=pin)


def test_a_pin_must_describe_a_real_edition() -> None:
    good = UNIFIED_AGENDA_EDITION_PINS[0]
    with pytest.raises(UnifiedAgendaEditionError, match="YYYYMM"):
        UnifiedAgendaEditionPin(
            file_stem=good.file_stem,
            publication_id="200507",  # July is not an agenda edition
            expected_sha256=good.expected_sha256,
            expected_byte_length=good.expected_byte_length,
            expected_record_count=good.expected_record_count,
            run_date=good.run_date,
        )
    with pytest.raises(UnifiedAgendaEditionError, match="sha256"):
        UnifiedAgendaEditionPin(
            file_stem=good.file_stem,
            publication_id=good.publication_id,
            expected_sha256="sha256:NOTHEX",
            expected_byte_length=good.expected_byte_length,
            expected_record_count=good.expected_record_count,
            run_date=good.run_date,
        )


@pytest.mark.skipif(not SOURCE_ROOT.is_dir(), reason="pinned captures are not present")
@pytest.mark.slow
def test_the_structured_cfr_field_carries_impossible_titles() -> None:
    """A title validator catches what no citation regex would.

    The Agenda's CFR_LIST is a structured, publisher-parsed field -- the very
    thing whose absence blocks the court-opinion route -- and it is still
    wrong 158 times in 416,749 title-prefixed references. 115 of those name
    title 35, which is Reserved and has no parts at all.

    Recorded, not repaired: the damage is the publisher's. What matters is
    that it is detectable by a rule about the CFR (titles run 1-50, 35 is
    Reserved) rather than by anything about citation syntax, which is why a
    validity check that cannot fail proves nothing about an extractor.
    """

    import re
    from collections import Counter

    from refspec.registry.cfr_list_of_subjects import CFR_RESERVED_TITLES

    leading_title = re.compile(r"^\s*(\d+)\s*CFR")
    impossible: Counter[int] = Counter()
    total = 0
    for pin in UNIFIED_AGENDA_EDITION_PINS:
        for record in parse_unified_agenda_edition(_payload(pin), pin=pin):
            for reference in record.cfr_references:
                match = leading_title.match(reference)
                if match is None:
                    continue
                total += 1
                title = int(match.group(1))
                if not 1 <= title <= 50 or title in CFR_RESERVED_TITLES:
                    impossible[title] += 1

    assert total == 416_749
    # Title 35 is EXCLUDED from "impossible" here even though today's index
    # reserves it: it was the Panama Canal title through the 2000 revision,
    # and the 115 citations of it come from 1990s editions. A validity rule
    # must carry the calendar of the data it judges.
    impossible.pop(35, None)
    assert sum(impossible.values()) == 43
    assert set(impossible) == {0, 59, 60, 234, 420}


@pytest.mark.skipif(not SOURCE_ROOT.is_dir(), reason="pinned captures are not present")
@pytest.mark.slow
def test_the_continuation_population_is_the_whole_series() -> None:
    """98 legal-authority lists live in ADDITIONAL_INFO and in no structured field.

    The Agenda's form gives a filer a fixed number of legal-authority boxes,
    and a filer whose list outran them typed the rest into the free-text
    ADDITIONAL_INFO field under a label. The XSD declares that field an
    unrestricted string with no documentation whatever
    (reginfo-rin-data-ver10262011.xsd line 177), so nothing but reading the 60
    editions can say what is in it.

    Two label families, both counted here over every one of the 241,726
    records rather than over a sample: "AUTHORIT(Y|IES) ... CONT" (67 records,
    17 RINs, 16 editions) and "Additional Legal Authority(ies)" together with
    the single "Continue from #8 Legal Authority" (31 records, 8 RINs, 11
    editions). 23 distinct RINs across 18 editions, 199510 through 200510; the
    practice stops after Fall 2005.

    Only 11 of the 98 also carry the ellipsis in their BOX list -- the
    publisher's own "there are more citations" marker -- so the ellipsis is not
    how a consumer finds these, and a list continuing without one is the common
    case rather than the exception.
    """

    from refspec.registry.unified_agenda_editions import (
        CONTINUATION_LABEL_FAMILIES,
        legal_authority_continuations,
    )

    found: dict[str, list[tuple[str, str]]] = {family: [] for family in CONTINUATION_LABEL_FAMILIES}
    markers: dict[str, int] = {}
    records_seen = 0
    for pin in UNIFIED_AGENDA_EDITION_PINS:
        for record in parse_unified_agenda_edition(_payload(pin), pin=pin):
            records_seen += 1
            for continuation in legal_authority_continuations(record.additional_info):
                found[continuation.label_family].append((record.rin, record.publication_id))
                markers[continuation.marker] = markers.get(continuation.marker, 0) + 1
                assert continuation.text, "an empty continuation is not a continuation"

    assert records_seen == UNIFIED_AGENDA_EXPECTED_RECORD_COUNT
    assert {family: len(rows) for family, rows in found.items()} == {
        "legal-authority-cont": 67,
        "additional-legal-authority": 31,
    }
    assert {family: len({rin for rin, _edition in rows}) for family, rows in found.items()} == {
        "legal-authority-cont": 17,
        "additional-legal-authority": 8,
    }
    assert {family: len({edition for _rin, edition in rows}) for family, rows in found.items()} == {
        "legal-authority-cont": 16,
        "additional-legal-authority": 11,
    }
    every = [key for rows in found.values() for key in rows]
    assert len(every) == len(set(every)) == 98, "a record is read once per family, and none twice"
    assert len({rin for rin, _edition in every}) == 23
    assert min(edition for _rin, edition in every) == "199510"
    assert max(edition for _rin, edition in every) == "200510"

    # Every spelling the filers typed, counted. Six case-folded spellings in
    # the CONT family and four in the other; a new one is a new row here rather
    # than a silent miss.
    assert markers == {
        "LEGAL AUTHORITY CONT:": 39,
        "LEGAL AUTHORITIES CONT:": 13,
        "ADDITIONAL LEGAL AUTHORITIES:": 11,
        "Additional Legal Authorities:": 7,
        "Additional Legal Authority:": 7,
        "LEGAL AUTHORITY CONTINUED:": 4,
        "Legal Authority continued:": 4,
        "Legal Authority Continue.........": 3,
        "Additional Legal Authorities": 3,
        "Legal Authority (Continued)": 2,
        "Legal Authority Continued....": 2,
        "Additional legal authority information:": 2,
        "Continue from #8 Legal Authority...........": 1,
    }
    assert sum(markers.values()) == 98


def test_a_continuation_stops_where_the_next_field_begins() -> None:
    """The boundary rule, stated and tested on each of its three shapes.

    A continuation runs from its label's END to the first of: the publisher's
    "^" paragraph mark (written "^P", which starts the next field -- "^PRFA:
    N", "^PANALYSIS: Regulatory Evaluation"), a blank line, or another of the
    form's fields continuing under its own label.

    The third fires on NOTHING in the pinned corpus, and is kept for the reason
    a rule measuring zero is ever kept: the regression it guards is silent by
    construction. Every "CFR CITATIONS CONT:" and "STATUTORY DEADLINE CONT:" in
    the 60 editions already sits behind a paragraph mark or a blank line, so a
    filer who separated two field continuations with a semicolon instead would
    hand a CFR part list to the authority parser and nothing would say so.
    """

    from refspec.registry.unified_agenda_editions import legal_authority_continuations

    # The paragraph mark. RIN 3235-AG65, Fall 1995, verbatim.
    caret = legal_authority_continuations(
        "LEGAL AUTHORITY CONT: 15 USC 77(g); 15 USC 77(j); 15 USC 77 (eee) ^PRFA:  N"
    )
    assert [(one.label_family, one.text) for one in caret] == [
        ("legal-authority-cont", "15 USC 77(g); 15 USC 77(j); 15 USC 77 (eee)")
    ]
    # The blank line. RIN 3235-AH16, Spring 1999, verbatim -- and the field
    # behind it is another CONT label, which the blank line already stops.
    blank = legal_authority_continuations(
        "LEGAL AUTHORITY CONT: 15 USC 78i; 15 USC 78o; 15 USC 78q; 15 USC 78w; 15 USC 78mm \n"
        "\nCFR CITATION CONT: 17 CFR 249.617 (Revision)"
    )
    assert [one.text for one in blank] == [
        "15 USC 78i; 15 USC 78o; 15 USC 78q; 15 USC 78w; 15 USC 78mm"
    ]
    # And the third boundary, on a string the corpus does not contain: the same
    # two fields with a semicolon between them instead of a blank line.
    stitched = legal_authority_continuations(
        "LEGAL AUTHORITY CONT: 15 USC 78i; 15 USC 78mm; CFR CITATION CONT: 17 CFR 249.617"
    )
    assert [one.text for one in stitched] == ["15 USC 78i; 15 USC 78mm;"]
    # The word "continued" in prose is not a label, because a label ends in a
    # colon -- so a continuation is never cut in half by its own sentence.
    assert [one.text for one in legal_authority_continuations(
        "LEGAL AUTHORITY CONT: 29 USC 1027, as continued by Pub. L. 104-191"
    )] == ["29 USC 1027, as continued by Pub. L. 104-191"]

    # A marker at the END of a record, and a marker in the MIDDLE of one: the
    # label may be preceded by anything (RIN 0938-AG59 writes a docket number
    # in front of it) and the extraction starts at the label's end either way.
    assert [one.text for one in legal_authority_continuations(
        "HSQ-215 ^PLEGAL AUTHORITY CONT: 42 USC 1395f(b) 42 USC 1395l 42 USC 1395ww"
    )] == ["42 USC 1395f(b) 42 USC 1395l 42 USC 1395ww"]
    # A label with nothing behind it yields nothing rather than an empty row.
    assert legal_authority_continuations("LEGAL AUTHORITY CONT: ^PRFA: N") == ()
    assert legal_authority_continuations("") == ()
    # Another field's continuation is not this field's, whatever it says.
    assert legal_authority_continuations("STATUTORY DEADLINE CONT: 07/01/1997") == ()
    assert legal_authority_continuations("CFR CITATIONS CONT: 8 CFR 232, 233") == ()
    # And a label that names the field without continuing it is not read: a
    # filer restating a list is not a filer extending one, and nothing in the
    # label says which. (0938-AI52 199804, 1090-AA67 199804, verbatim heads.)
    assert legal_authority_continuations("Legal Authority: PL-105-33, sec 4505") == ()
    assert legal_authority_continuations("8. Legal Authority: OMB Circular A-110") == ()
    assert legal_authority_continuations("Additional authority DOT Order 5660.1A") == ()


@pytest.mark.skipif(not SOURCE_ROOT.is_dir(), reason="pinned captures are not present")
def test_the_specimen_continuation_reads_to_thirteen_citations() -> None:
    """SEC RIN 3235-AG65, Spring 1996: 13 citations in no structured field.

    The record's 16 boxes end with the publisher's own ellipsis -- "there are
    more citations" -- and the 13 that follow are these. Every identity is
    pinned, because the whole point of reading a free-text field is that a
    change in what it yields must be visible.

    Row 3 is the one to read twice. The filer wrote "15 USC 77 eee", which is
    15 U.S.C. 77eee (Trust Indenture Act sec. 305) to any reader -- and the
    section-existence oracle refuses to say so, because 15 U.S.C. 77 is ITSELF
    a current section of title 15 and no question the oracle can ask separates
    two real sections. So the row publishes the section its own text supports,
    77, with the letters left as uncovered text (which is what makes the row
    partial), and the refusal is legible in the oracle's candidate list rather
    than hidden in a silently wrong number. See
    ``test_a_space_before_a_lettered_suffix_needs_the_oracle_as_witness``.
    """

    from refspec.registry.citation_grammar import parse_authority_citation
    from refspec.registry.unified_agenda_editions import legal_authority_continuations

    pin = next(one for one in UNIFIED_AGENDA_EDITION_PINS if one.publication_id == "199604")
    record = next(
        one
        for one in parse_unified_agenda_edition(_payload(pin), pin=pin)
        if one.rin == "3235-AG65"
    )
    assert record.legal_authorities[-1] == "...", "the boxes declare themselves incomplete"
    assert len(record.legal_authorities) == 16

    continuations = legal_authority_continuations(record.additional_info)
    assert [one.label_family for one in continuations] == ["legal-authority-cont"]
    assert continuations[0].text == (
        "15 USC 77g; 15 USC 77j; 15 USC 77 eee; 15 USC 77ggg; 15 USC 77nnn; 15 USC 77sss; "
        "15 USC 78d; 15 USC 78ff; 15 USC 80a-20; 15 USC 80a-23; 15 USC 80b-4; 15 USC 80b-11; "
        "15 USC 78ll(d)"
    )

    rows = parse_authority_citation(continuations[0].text)
    assert [(row.authority_type, row.parse_status, row.usc_title, row.usc_section) for row in rows] == [
        ("usc", "partial", 15, "77g"),
        ("usc", "partial", 15, "77j"),
        ("usc", "partial", 15, "77"),
        ("usc", "partial", 15, "77ggg"),
        ("usc", "partial", 15, "77nnn"),
        ("usc", "partial", 15, "77sss"),
        ("usc", "partial", 15, "78d"),
        ("usc", "partial", 15, "78ff"),
        ("usc", "partial", 15, "80a-20"),
        ("usc", "partial", 15, "80a-23"),
        ("usc", "partial", 15, "80b-4"),
        ("usc", "partial", 15, "80b-11"),
        ("usc", "partial", 15, "78ll"),
    ]
    assert len(rows) == 13
    # None of the 13 restates a box: the boxes are 77c-77d, 77s, 77ttt, 78c,
    # 78i, 78j, 78l-78q, 78s, 78w, 78x, 79q, 79t, 80a-29, 80a-37, 80b-3 and the
    # ellipsis, and this continuation names fifteen other places.
    assert not {row.usc_section for row in rows} & {
        "77c", "77s", "77ttt", "78c", "78i", "78j", "78l", "78s", "78w", "78x",
        "79q", "79t", "80a-29", "80a-37", "80b-3",
    }
