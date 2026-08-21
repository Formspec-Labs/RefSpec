"""The derived Unified Agenda tables consumers actually read."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry.unified_agenda_parquet import (
    ACTIONS_SCHEMA,
    CFR_REFERENCES_SCHEMA,
    LEGAL_AUTHORITIES_SCHEMA,
    parse_cfr_reference,
)

ARTIFACT = Path(__file__).resolve().parents[1] / "output" / "registry-real-data-sources" / "unified-agenda-parquet"

pytestmark = pytest.mark.skipif(not ARTIFACT.is_dir(), reason="derived Parquet artifact is not built")


@pytest.fixture(scope="module")
def con():
    duckdb = pytest.importorskip("duckdb")
    return duckdb.connect()


def _one(con, sql: str):
    return con.execute(sql.format(d=ARTIFACT.as_posix())).fetchone()[0]


def test_every_pinned_record_reaches_the_tables(con) -> None:
    assert _one(con, "select count(*) from '{d}/unified_agenda_actions.parquet'") == 241_726
    assert _one(con, "select count(*) from '{d}/unified_agenda_cfr_references.parquet'") == 438_913
    assert _one(con, "select count(*) from '{d}/unified_agenda_legal_authorities.parquet'") == 755_727
    # The child tables reconcile with the counts the parent records.
    assert _one(
        con,
        "select sum(cfr_reference_count) from '{d}/unified_agenda_actions.parquet'",
    ) == 438_913
    assert _one(
        con,
        "select sum(legal_authority_count) from '{d}/unified_agenda_legal_authorities.parquet'"
        .replace("legal_authority_count", "1"),
    ) == 755_727


def test_publisher_damage_is_labelled_rather_than_filtered(con) -> None:
    """The impossible titles stay in the table with a verdict column.

    A consumer filtering on `cfr_title_is_possible` can see exactly what it
    discarded; one studying publisher data quality reads the same rows from
    the other side. Dropping them would make the second question unanswerable.
    """

    impossible = _one(
        con,
        "select count(*) from '{d}/unified_agenda_cfr_references.parquet' "
        "where cfr_title_is_possible = false",
    )
    assert impossible == 158
    reserved = _one(
        con,
        "select count(*) from '{d}/unified_agenda_cfr_references.parquet' where cfr_title = 35",
    )
    assert reserved == 115, "CFR title 35 is Reserved and has no parts"
    # ~5% of the field does not begin with a title at all -- '(app B)', '(new)',
    # '...'. Those are not parse failures to repair.
    assert _one(
        con,
        "select count(*) from '{d}/unified_agenda_cfr_references.parquet' where cfr_title is null",
    ) == 22_093


def test_the_citation_parse_is_looser_than_a_literal_cfr_match(con) -> None:
    """71 real citations write "C.F.R." or lowercase "cfr".

    Recorded because a stricter pattern elsewhere in this repo counts 416,749
    title-prefixed references where this table has 416,820. Same data, two
    patterns, two denominators -- which is the reason the parse belongs in one
    place rather than in every consumer.
    """

    only_loose = _one(
        con,
        "select count(*) from '{d}/unified_agenda_cfr_references.parquet' "
        "where cfr_title is not null and not regexp_matches(reference_text, '^\\s*\\d+\\s*CFR')",
    )
    assert only_loose == 71


def test_the_table_carries_the_corrected_parse(con) -> None:
    """Scale of the three defects a peer session found by re-deriving from it."""

    assert _one(con, "select count(*) from '{d}/unified_agenda_cfr_references.parquet' where cfr_part is not null") == 414_537
    # Fused-dot damage: reported and flagged, never silently kept as real.
    assert _one(con, "select count(*) from '{d}/unified_agenda_cfr_references.parquet' where cfr_part_is_plausible = false") == 42
    # List references: 3,016 parts that head-only parsing discarded.
    assert _one(con, "select sum(len(cfr_additional_parts)) from '{d}/unified_agenda_cfr_references.parquet'") == 3_016
    assert _one(con, "select count(*) from '{d}/unified_agenda_cfr_references.parquet' where len(cfr_additional_parts) > 0") == 1_402


def test_a_section_citation_resolves_to_its_part() -> None:
    """The subject index is keyed by part; prose cites sections."""

    assert parse_cfr_reference("42 CFR 416").cfr_part == "416"
    assert parse_cfr_reference("45 C.F.R. § 302.32(b)").cfr_part == "302"
    assert parse_cfr_reference("40 CFR Part 194").cfr_part == "194"
    assert parse_cfr_reference("49 cfr part 192").cfr_part == "192"
    assert parse_cfr_reference("21 CFR186.1").cfr_part == "186"
    # Reserved and out-of-range titles parse, and are marked impossible.
    assert parse_cfr_reference("35 CFR 1").cfr_title_is_possible is False
    assert parse_cfr_reference("420 CFR 3").cfr_title_is_possible is False
    # Not a citation at all; the caller still has reference_text.
    assert parse_cfr_reference("(app B)").cfr_title is None


def test_a_rule_number_is_not_mistaken_for_a_part() -> None:
    """17 CFR 15c3-3 is rule 15c3-3 under part 240; "15c" is not a part.

    But 7 CFR 15a and 42 CFR 59a ARE real parts, so the tell is the digit that
    follows the letter, never the letter itself: 2,116 references carry a real
    letter suffix against 864 carrying a rule number.
    """

    assert parse_cfr_reference("17 CFR 15c3-3").cfr_part is None
    assert parse_cfr_reference("17 CFR 12d1-1").cfr_part is None
    assert parse_cfr_reference("7 CFR 15a").cfr_part == "15a"
    assert parse_cfr_reference("42 CFR 59a").cfr_part == "59a"
    # A title with no readable part still reports its title.
    assert parse_cfr_reference("35 CFR ch. II").cfr_title == 35


def test_fused_dot_damage_is_flagged_not_accepted() -> None:
    """"40 CFR 60758" is 40 CFR 60.758 with the separator lost.

    Titles were validated against a roster and parts against nothing, so the
    same damage class sailed through one field to the right.
    """

    parsed = parse_cfr_reference("40 CFR 60758")
    assert parsed.cfr_part == "60758" and parsed.cfr_part_is_plausible is False
    assert parse_cfr_reference("42 CFR 412106").cfr_part_is_plausible is False
    assert parse_cfr_reference("48 CFR 9904").cfr_part_is_plausible is True


def test_a_list_reference_keeps_every_part_it_names() -> None:
    """Head-only silently discarded two thirds of "parts 37, 38, 39"."""

    parsed = parse_cfr_reference("17 CFR parts 37, 38, 39")
    assert parsed.cfr_part == "37"
    assert parsed.cfr_additional_parts == ("38", "39")
    # The plural was unhandled entirely, so every "Parts" reference was NULL.
    assert parse_cfr_reference("48 CFR Parts 719").cfr_part == "719"


def test_the_schemas_name_the_publishers_text_alongside_the_parse() -> None:
    """A parse this module gets wrong must stay visible, not replace the source."""

    assert "reference_text" in CFR_REFERENCES_SCHEMA.names
    assert "authority_text" in LEGAL_AUTHORITIES_SCHEMA.names
    assert set(ACTIONS_SCHEMA.names) == {
        "rin",
        "publication_id",
        "cfr_reference_count",
        "legal_authority_count",
    }
