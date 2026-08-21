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
