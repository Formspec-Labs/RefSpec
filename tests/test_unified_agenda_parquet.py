"""The derived Unified Agenda tables consumers actually read."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry.unified_agenda_parquet import (
    ACTIONS_SCHEMA,
    CFR_REFERENCES_SCHEMA,
    LEGAL_AUTHORITIES_SCHEMA,
)

ARTIFACT = Path(__file__).resolve().parents[1] / "output" / "registry-real-data-sources" / "unified-agenda-parquet"

pytestmark = pytest.mark.skipif(not ARTIFACT.is_dir(), reason="derived Parquet artifact is not built")


@pytest.fixture(scope="module")
def con():
    duckdb = pytest.importorskip("duckdb")
    return duckdb.connect()


def _one(con, sql: str):
    return con.execute(sql.format(d=ARTIFACT.as_posix())).fetchone()[0]





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

def test_the_tables_carry_what_the_shared_grammar_reads(con) -> None:
    """One row per parsed citation, so a list reference is no longer head-only."""

    assert _one(con, "select count(*) from '{d}/unified_agenda_actions.parquet'") == 241_726
    assert _one(con, "select count(*) from '{d}/unified_agenda_cfr_references.parquet'") == 445_064
    # Sections were discarded entirely before the grammar was shared.
    assert _one(
        con,
        "select count(*) from '{d}/unified_agenda_cfr_references.parquet' where cfr_section is not null",
    ) == 106_940
    # Damage is labelled, never filtered.
    assert _one(
        con,
        "select count(*) from '{d}/unified_agenda_cfr_references.parquet' "
        "where cfr_title_is_possible = false",
    ) > 0


def test_the_authority_field_is_no_longer_shipped_as_raw_text(con) -> None:
    """755,727 authorities shipped unparsed until the grammar moved here."""

    total = _one(con, "select count(*) from '{d}/unified_agenda_legal_authorities.parquet'")
    parsed = _one(
        con,
        "select count(*) from '{d}/unified_agenda_legal_authorities.parquet' "
        "where authority_type is not null",
    )
    assert total == 763_218
    assert parsed == 718_606
    kinds = con.execute(
        f"select distinct authority_type from '{ARTIFACT.as_posix()}/unified_agenda_legal_authorities.parquet' "
        "where authority_type is not null"
    ).fetchall()
    assert {row[0] for row in kinds} == {"usc", "public_law", "executive_order", "statute_at_large"}
