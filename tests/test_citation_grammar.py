"""The single citation grammar, and the two defects the port fixed."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from refspec.registry.citation_grammar import (
    CFR_LETTERED_PART_SHARE,
    parse_authority_citation,
    parse_cfr_citations,
    parse_eo_compilation_locators,
)

INDEX_CSV = (
    Path(__file__).resolve().parents[1]
    / "research"
    / "evidence"
    / "cfr-subject-index-2026-08-20"
    / "part-subjects.csv"
)


def _parts(text: str, **kwargs) -> list[str | None]:
    return [citation.cfr_part for citation in parse_cfr_citations(text, **kwargs)]


def test_a_lettered_part_is_not_merged_into_its_numeric_neighbour() -> None:
    """Both ancestor grammars capture (?P<part>\\d+), so "7 CFR 15a" read as 15.

    That is not a rounding error: the OFR's index lists 7 CFR 15 and 7 CFR 15a
    as separate parts, so merging them unions two distinct bodies of regulation.
    """

    assert _parts("7 CFR 15a") == ["15a"]
    assert _parts("42 CFR 59a") == ["59a"]
    assert _parts("7 CFR 15") == ["15"]


@pytest.mark.skipif(not INDEX_CSV.is_file(), reason="CFR subject index evidence is not present")
def test_the_lettered_part_share_is_measured_not_asserted() -> None:
    rows = list(csv.DictReader(INDEX_CSV.open(encoding="utf-8", newline="")))
    parts = {(row["cfr_title"], row["cfr_part"]) for row in rows}
    lettered = {part for part in parts if not part[1].isdigit()}
    assert CFR_LETTERED_PART_SHARE == (len(lettered), len(parts))
    # The specific pair that proves merging is lossy.
    assert ("7", "15") in parts and ("7", "15a") in parts


def test_a_rule_number_never_becomes_a_part() -> None:
    """17 CFR 15c3-3 is a rule under part 240; "15c" is not a part."""

    assert _parts("17 CFR 15c3-3") == [None]
    assert _parts("17 CFR 12d1-1") == [None]


def test_list_expansion_is_a_declared_policy_not_a_default() -> None:
    """Prose and a structured field need opposite answers.

    In the Unified Agenda's CFR field, 953 references list parts with no label
    at all against 43 with a plural label -- so the prose-safe rule drops the
    dominant shape. In a sentence, the same rule stops "part 37" from
    swallowing the next number it sees.
    """

    unlabelled = "40 CFR 60, 61, 63"
    assert _parts(unlabelled) == ["60"]
    assert _parts(unlabelled, list_expansion="always") == ["60", "61", "63"]
    # A plural label licenses expansion under either policy.
    assert _parts("17 CFR parts 37, 38, 39") == ["37", "38", "39"]
    with pytest.raises(ValueError, match="unknown list expansion"):
        parse_cfr_citations("40 CFR 60", list_expansion="sometimes")


def test_an_impossible_title_is_returned_rather_than_dropped() -> None:
    """Both ancestors drop it, which makes a data-quality question unanswerable."""

    reserved = parse_cfr_citations("35 CFR ch. II")
    assert [(c.cfr_title, c.cfr_part, c.title_is_possible) for c in reserved] == [(35, None, True)]
    out_of_range = parse_cfr_citations("234 CFR 100")
    assert out_of_range[0].title_is_possible is False
    assert out_of_range[0].cfr_part == "100"


def test_part_length_asserts_nothing_below_six_digits() -> None:
    """5 CFR 10001 is real (National Council on Disability), so five digits
    proves nothing either way; the evidence signal is OFR-index membership,
    carried as a column in the Agenda tables. Six digits and up stays
    asserted damage."""

    assert parse_cfr_citations("5 CFR 10001")[0].part_is_plausible is True
    assert parse_cfr_citations("40 CFR 60758")[0].part_is_plausible is True  # unknowable by length
    assert parse_cfr_citations("42 CFR 412106")[0].part_is_plausible is False
    assert parse_cfr_citations("48 CFR 9904")[0].part_is_plausible is True


def test_the_boundary_guard_survives_the_port() -> None:
    """The guard blocks OFFSET matching; it does not reject zero-padding.

    The ancestor's hazard was "040 CFR 060" matching at offset 1 as a
    fabricated "40 CFR". The guard alone prevents that: a title may not begin
    mid-token. Whole-token zero-padding is a different thing -- the Agenda
    carries 95 zero-padded titles ("07 CFR 1943" is USDA's title 7) -- and is
    read by its integer value rather than refused.
    """

    # Mid-token: blocked entirely, not read as "40 CFR 60".
    assert parse_cfr_citations("x40 CFR 60") == ()
    # Whole-token zero-padding: read, and the verdict falls on the int.
    padded = parse_cfr_citations("040 CFR 060")
    assert [(c.cfr_title, c.cfr_part, c.title_is_possible) for c in padded] == [(40, "60", True)]
    assert parse_cfr_citations("00 CFR 00")[0].title_is_possible is False


def test_zero_padded_titles_are_read_and_literal_zero_is_labelled() -> None:
    """[1-9]\d* lost 61 valid USDA citations and unlabelled 36 damage rows at once."""

    assert parse_cfr_citations("07 CFR 1943")[0] .cfr_title == 7
    assert parse_cfr_citations("07 CFR 1943")[0].title_is_possible is True
    zero = parse_cfr_citations("0 CFR 150 to 189")[0]
    assert (zero.cfr_title, zero.title_is_possible) == (0, False)


def test_the_part_is_a_join_key_so_leading_zeros_normalize() -> None:
    """"0718" and "718" are one part; the written form survives in the source text."""

    assert parse_cfr_citations("7 CFR 0718")[0].cfr_part == "718"
    assert parse_cfr_citations("00 CFR 00")[0].cfr_part == "0"


def test_sections_are_read_not_discarded() -> None:
    citation = parse_cfr_citations("45 C.F.R. § 302.32(b)")[0]
    assert (citation.cfr_part, citation.cfr_section) == ("302", "32")
    # A trailing period belongs to the sentence, not the section name.
    assert parse_cfr_citations("49 CFR 900.42.")[0].cfr_section == "42"


def test_every_authority_shape_the_agenda_carries() -> None:
    assert [a.authority_type for a in parse_authority_citation("5 U.S.C. 301")] == ["usc"]
    assert parse_authority_citation("PL 107-171")[0].public_law == "107-171"
    assert parse_authority_citation("E.O. 13559")[0].executive_order == "13559"
    assert parse_authority_citation("106 Stat. 4777")[0].statute_volume == 106
    both = parse_authority_citation("5 U.S.C. 301; PL 95-91")
    assert {a.authority_type for a in both} == {"usc", "public_law"}


# --------------------------------------------------------------------------- #
# Lessons carried from the ancestor implementations, each pinned by the case
# that bought it.


def test_the_usc_range_ordering_rule_is_fail_closed() -> None:
    """A hyphen means two things in the U.S. Code; ordering decides which.

    "1395w-4" is one section's name (its suffix is a small ordinal);
    "7401-7671q" is a range (its second endpoint sorts after its first). The
    abbreviated "1484-86" satisfies neither reading honestly, so it stays one
    opaque token — reading it either way would be an invention.
    """

    ranged = parse_authority_citation("42 U.S.C. 7401-7671q")[0]
    assert (ranged.usc_section, ranged.usc_section_end) == ("7401", "7671q")
    spelled = parse_authority_citation("42 U.S.C. 7401 to 7671q")[0]
    assert (spelled.usc_section, spelled.usc_section_end) == ("7401", "7671q")
    compound = parse_authority_citation("12 U.S.C. 1831p-1")[0]
    assert (compound.usc_section, compound.usc_section_end) == ("1831p-1", None)
    assert compound.parse_status == "ok"
    abbreviated = parse_authority_citation("42 U.S.C. 1484-86")[0]
    assert (abbreviated.usc_section, abbreviated.usc_section_end) == ("1484-86", None)


def test_usc_chapters_are_typed_rows_not_failures() -> None:
    """Bought as the largest slice of the citation bakeoff's shared-miss cell.

    citations.py kept chapters out of its authority parse; the Agenda cites
    4,377 of them, so here they are typed rather than 'other'/'failed'.
    """

    chapter = parse_authority_citation("49 U.S.C. ch. 311")[0]
    assert (chapter.authority_type, chapter.usc_chapter) == ("usc_chapter", "311")
    # "22 USC Ch. 34- The Peace Corps Act": the dash is punctuation before a
    # title, not a range separator, because no number follows it.
    named = parse_authority_citation("22 USC Ch. 34- The Peace Corps Act")[0]
    assert (named.usc_chapter, named.usc_chapter_end) == ("34", None)
    assert named.parse_status == "partial"


def test_a_section_list_expands_under_its_title_and_stops_at_citations() -> None:
    listed = parse_authority_citation("42 U.S.C. 1395, 1396, 1397")
    assert [c.usc_section for c in listed] == ["1395", "1396", "1397"]
    assert {c.parse_status for c in listed} == {"partial"}
    # A number that leads another citation form is never a list member.
    mixed = parse_authority_citation("5 U.S.C. 301, 117 Stat. 429")
    assert [(c.authority_type, c.usc_section or c.statute_page) for c in mixed] == [
        ("usc", "301"),
        ("statute_at_large", 429),
    ]


def test_the_title_form_is_the_spelling_statutes_themselves_use() -> None:
    single = parse_authority_citation("section 553 of title 5")[0]
    assert (single.usc_title, single.usc_section, single.parse_status) == (5, "553", "ok")
    plural = parse_authority_citation("sections 3501, 3502 and 3503 of title 44")
    assert [c.usc_section for c in plural] == ["3501", "3502", "3503"]


def test_a_named_code_supplies_its_own_title() -> None:
    """"I.R.C. 337(d)" and "26 U.S.C. 337(d)" must reach one identifier."""

    irc = parse_authority_citation("I.R.C. 337(d)")[0]
    assert (irc.authority_type, irc.usc_title, irc.usc_section) == ("usc", 26, "337")


def test_the_code_names_itself_three_ways() -> None:
    assert parse_authority_citation("49 U.S. Code 106")[0].usc_section == "106"
    annotated = parse_authority_citation("50 U.S.C.A. 4701(a)")[0]
    assert (annotated.usc_title, annotated.usc_section) == (50, "4701")


def test_parse_status_distinguishes_covered_from_embedded() -> None:
    assert parse_authority_citation("5 U.S.C. 301")[0].parse_status == "ok"
    # "et seq." and "as amended" are ignorable tails, not extra prose.
    assert parse_authority_citation("5 U.S.C. 301 et seq.")[0].parse_status == "ok"
    assert parse_authority_citation("42 U.S.C. 2000bb as amended")[0].parse_status == "ok"
    # A stripped subsection is uncovered text: their own worked example.
    assert parse_authority_citation("42 USC 9608 (b)")[0].parse_status == "partial"
    # Unreadable text is retained, never dropped.
    failed = parse_authority_citation("the Commissioner's general authority")[0]
    assert (failed.authority_type, failed.parse_status) == ("other", "failed")


def test_capitalization_is_evidence_for_bare_abbreviations() -> None:
    """Prose contains "eo" and "stat" as word fragments; labels relax the rule."""

    assert parse_authority_citation("Romeo 12345")[0].authority_type == "other"
    assert parse_authority_citation("eo 13559")[0].authority_type == "other"
    assert parse_authority_citation("E.O. 13559")[0].executive_order == "13559"
    assert parse_authority_citation("EO 13559")[0].executive_order == "13559"
    # The spelled form may relax case and accepts early two-digit orders.
    assert parse_authority_citation("Executive Order 11")[0].executive_order == "11"
    assert parse_authority_citation("77 Stat. 392")[0].statute_page == 392


def test_a_compilation_locator_is_never_a_cfr_citation() -> None:
    """"3 CFR, 1977 Comp., p. 123" is the page an EO was printed on.

    Left in the CFR grammar it parses as title 3, part 1977 — plausible on
    every axis and entirely fabricated. The closed separator set was bought
    when an enumerated one left "through" still minting urn:rkaf:us:cfr:3:1949.
    """

    assert parse_cfr_citations("3 CFR, 1977 Comp., p. 123") == ()
    assert parse_cfr_citations("3 CFR 1949 through 1953 Comp") == ()
    locator = parse_eo_compilation_locators("3 CFR, 1977 Comp., p. 123")[0]
    assert (locator.compilation_start, locator.page) == ("1977", "123")
    # A real title-3 citation still parses.
    assert parse_cfr_citations("3 CFR part 100")[0].cfr_part == "100"


def test_the_title_part_spelling_requires_an_anchor() -> None:
    """The ancestor made both anchors optional; "5, part 2" fabricated a citation."""

    assert [(c.cfr_title, c.cfr_part) for c in parse_cfr_citations("title 40, part 60")] == [(40, "60")]
    assert parse_cfr_citations("5, part 2 of the plan") == ()


def test_a_cfr_list_never_swallows_the_next_citations_number() -> None:
    mixed = parse_cfr_citations("17 CFR 240, 15 U.S.C. 78c", list_expansion="always")
    assert [(c.cfr_title, c.cfr_part) for c in mixed] == [(17, "240")]


def test_double_letter_sections_are_one_token() -> None:
    """The ancestors' single-letter capture read "2000bb" as 2000b + stray b."""

    rfra = parse_authority_citation("42 U.S.C. 2000bb")[0]
    assert (rfra.usc_section, rfra.parse_status) == ("2000bb", "ok")
    assert parse_authority_citation("42 U.S.C. 300aa-25")[0].usc_section == "300aa-25"


def test_the_recovered_authority_classes_from_the_malformed_census() -> None:
    """Five classes recovered from 39,856 failed rows; each pinned by its case."""

    appendix = parse_authority_citation("50 USC app 2401 et seq")[0]
    assert (appendix.authority_type, appendix.usc_appendix, appendix.usc_section) == ("usc", True, "2401")
    # The appendix span suppresses the standard form: this is NOT plain 50
    # U.S.C. 2401, which is a different place.
    assert len(parse_authority_citation("50 U.S.C. app. 2401")) == 1

    plural = parse_authority_citation("Executive Orders 13990 and 14008")
    assert [c.executive_order for c in plural] == ["13990", "14008"]

    plan = parse_authority_citation("Reorganization Plan No. 3 of 1970")[0]
    assert (plan.authority_type, plan.reorganization_plan) == ("reorganization_plan", "3-of-1970")

    wrong_column = parse_authority_citation("delegation of authority at 49 CFR 1.95")[0]
    assert (wrong_column.authority_type, wrong_column.cfr_title, wrong_column.cfr_part) == ("cfr", 49, "1")

    for placeholder in ("Not Yet Determined", "...", "None", "TBD"):
        assert parse_authority_citation(placeholder)[0].authority_type == "unstated"
    # Genuinely unreadable text still says failed/other, never unstated.
    assert parse_authority_citation("MNOPF Trustees, Ltd v United States")[0].authority_type == "other"

    # A case-reporter citation is its own family: it locates a decision.
    case = parse_authority_citation("123 F 3d 1460 (Fed Cir 1997)")[0]
    assert (case.authority_type, case.case_volume, case.case_page) == ("case_citation", 123, 1460)
    # "U.S.C." never reads as the U.S. reporter — the C intervenes.
    assert parse_authority_citation("5 U.S.C. 301")[0].authority_type == "usc"
