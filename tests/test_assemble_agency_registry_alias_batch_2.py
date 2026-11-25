"""Agency registry alias batch 2: deterministic assembly, verbatim record reading, and zero overlap with batch 1."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from refspec.atlas import v3_registry_alignments_entity as entity_alignments
from tools import analyze_agency_roster_identifiers as census
from tools import assemble_agency_registry_alias_batch as batch1_aliases
from tools import assemble_agency_registry_alias_batch_2 as aliases2

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def releases() -> tuple[Any, ...]:
    return census.load_five_agency_rosters(ROOT)


@pytest.fixture(scope="module")
def report(releases: tuple[Any, ...]) -> dict[str, Any]:
    return aliases2.assemble(ROOT, releases)


def test_committed_batch_2_artifacts_have_no_drift(releases: tuple[Any, ...]) -> None:
    assert aliases2.write_or_check(ROOT, write=False, releases=releases) == []


def test_batch_2_accounts_for_all_94_keys_and_verifies_every_record(
    report: dict[str, Any], releases: tuple[Any, ...]
) -> None:
    keys = [row["name_key"] for row in report["aliases"]]
    assert len(keys) == len(set(keys)) == 94
    decisions = entity_alignments.load_decisions(ROOT / aliases2.DECISIONS_JSON, report)
    assert not decisions.stale
    assert set(decisions.current) == {row["alias_id"] for row in report["aliases"]}
    assert all(row["read"] for alias in report["aliases"] for row in alias["records"])

    b1_keys = {row["name_key"] for row in batch1_aliases.assemble(ROOT, releases)["aliases"]}
    assert not (set(keys) & b1_keys)


def test_batch_2_record_is_unread_when_tampered(report: dict[str, Any], tmp_path: Path) -> None:
    (record,) = next(
        row for row in report["aliases"] if row["alias_id"] == "alias:government-printing-office"
    )["records"]
    assert entity_alignments.alias_record_is_read(record, ROOT)
    assert not entity_alignments.alias_record_is_read({**record, "passage": "nonexistent passage"}, ROOT)
    assert not entity_alignments.alias_record_is_read({**record, "sha256": "sha256:" + "0" * 64}, ROOT)
    assert not entity_alignments.alias_record_is_read(record, tmp_path)
