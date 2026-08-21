"""The single citation grammar, and the two defects the port fixed."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from refspec.registry.citation_grammar import (
    CFR_LETTERED_PART_SHARE,
    parse_authority_citation,
    parse_cfr_citations,
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
    assert [(c.cfr_title, c.cfr_part, c.title_is_possible) for c in reserved] == [(35, None, False)]
    out_of_range = parse_cfr_citations("234 CFR 100")
    assert out_of_range[0].title_is_possible is False
    assert out_of_range[0].cfr_part == "100"


def test_fused_dot_damage_is_flagged_on_the_part() -> None:
    fused = parse_cfr_citations("40 CFR 60758")[0]
    assert fused.cfr_part == "60758" and fused.part_is_plausible is False
    assert parse_cfr_citations("48 CFR 9904")[0].part_is_plausible is True


def test_the_boundary_guard_survives_the_port() -> None:
    """Without it "040 CFR 060" matches at offset 1 and reports 40 CFR 60."""

    assert parse_cfr_citations("040 CFR 060") == ()


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
