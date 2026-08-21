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


def test_a_section_citation_resolves_to_its_part() -> None:
    """The subject index is keyed by part; prose cites sections."""

    assert parse_cfr_reference("42 CFR 416") == (42, "416", True)
    assert parse_cfr_reference("45 C.F.R. § 302.32(b)") == (45, "302", True)
    assert parse_cfr_reference("40 CFR Part 194") == (40, "194", True)
    assert parse_cfr_reference("49 cfr part 192") == (49, "192", True)
    # Reserved and out-of-range titles parse, and are marked impossible.
    assert parse_cfr_reference("35 CFR 1") == (35, "1", False)
    assert parse_cfr_reference("420 CFR 3") == (420, "3", False)
    # Not a citation at all; the caller still has reference_text.
    assert parse_cfr_reference("(app B)") == (None, None, None)


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
