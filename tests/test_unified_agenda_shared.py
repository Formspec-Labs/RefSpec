"""The shared metadata adapter against the copied reader and source mutations."""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest
import unified_agenda_oracle as old

from refspec.registry import unified_agenda_editions as current

FIXTURE = Path(__file__).parent / "fixtures/unified_agenda_shared/edition-202510.xml"


def _pin(payload: bytes, publication="202510", count=1):
    return current.UnifiedAgendaEditionPin(
        file_stem=publication,
        publication_id=publication,
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_byte_length=len(payload),
        expected_record_count=count,
        run_date="2026-07-03-04:00",
    )


def _edition(fields: bytes) -> bytes:
    return b'<REGINFO_RIN_DATA RUN_DATE="2026-07-03-04:00"><RIN_INFO>' + fields + b"</RIN_INFO></REGINFO_RIN_DATA>"


IDENTITY = b"<RIN>1000-AA00</RIN><PUBLICATION><PUBLICATION_ID>202510</PUBLICATION_ID></PUBLICATION>"


def _verdict(reader, payload, pin):
    try:
        result = reader(payload, pin=pin)
    except ValueError:
        return "reject", None
    except Exception as error:
        # The frozen ElementTree reader exposes ParseError for malformed XML.
        if type(error).__name__ != "ParseError":
            raise
        return "reject", None
    return "accept", tuple(dataclasses.asdict(row) for row in result)


@pytest.mark.parametrize(
    "fields",
    [
        b"",
        b"<CFR_LIST/><LEGAL_AUTHORITY_LIST/><TIMETABLE_LIST/><ADDITIONAL_INFO/>",
        b"<CFR_LIST><CFR> 7 CFR   1 </CFR><CFR/><CFR>7 CFR 1</CFR></CFR_LIST>",
        b"<LEGAL_AUTHORITY_LIST><LEGAL_AUTHORITY> 5 USC  301 </LEGAL_AUTHORITY></LEGAL_AUTHORITY_LIST>",
        b"<TIMETABLE_LIST><TIMETABLE><TTBL_ACTION>NPRM</TTBL_ACTION><TTBL_DATE>11/00/2026</TTBL_DATE></TIMETABLE><TIMETABLE/></TIMETABLE_LIST>",
        b"<ADDITIONAL_INFO>Legal authority cont: 5 USC 301\n\nCFR citations cont: 7 CFR 1</ADDITIONAL_INFO>",
        b"<ADDITIONAL_INFO><![CDATA[<b>Literal</b>]]></ADDITIONAL_INFO>",
        b"<CFR_LIST><CFR>first<EM>child</EM>tail</CFR></CFR_LIST>",
        b"<ADDITIONAL_INFO>first<EM>child</EM>tail</ADDITIONAL_INFO>",
        b"<CFR_LIST><UNKNOWN>unknown source tag</UNKNOWN></CFR_LIST>",
        b"<CFR_LIST><CFR>first</CFR></CFR_LIST><CFR_LIST><CFR>second</CFR></CFR_LIST>",
        b"<LEGAL_AUTHORITY_LIST><LEGAL_AUTHORITY>first</LEGAL_AUTHORITY></LEGAL_AUTHORITY_LIST><LEGAL_AUTHORITY_LIST><LEGAL_AUTHORITY>second</LEGAL_AUTHORITY></LEGAL_AUTHORITY_LIST>",
        b"<ADDITIONAL_INFO>first</ADDITIONAL_INFO><ADDITIONAL_INFO>second</ADDITIONAL_INFO>",
        b"<TIMETABLE_LIST><TIMETABLE><TTBL_DATE>first</TTBL_DATE><TTBL_DATE>second</TTBL_DATE></TIMETABLE></TIMETABLE_LIST>",
        b"<TIMETABLE_LIST><TIMETABLE><TTBL_ACTION>first</TTBL_ACTION></TIMETABLE></TIMETABLE_LIST><TIMETABLE_LIST><TIMETABLE><TTBL_ACTION>second</TTBL_ACTION></TIMETABLE></TIMETABLE_LIST>",
    ],
)
def test_field_values_and_verdicts_match_frozen_reader(fields):
    payload = _edition(IDENTITY + fields)
    pin = _pin(payload)
    assert _verdict(current.parse_unified_agenda_edition, payload, pin) == _verdict(
        old.parse_unified_agenda_edition, payload, pin
    )


@pytest.mark.parametrize(
    "identity",
    [
        IDENTITY.replace(b"<RIN>1000-AA00</RIN>", b""),
        IDENTITY.replace(b"<RIN>1000-AA00</RIN>", b"<RIN/>"),
        IDENTITY.replace(b"<RIN>1000-AA00</RIN>", b"<RIN>1000-AA00</RIN><RIN>different</RIN>"),
        IDENTITY.replace(b"202510", b"202410"),
        IDENTITY.replace(b"<PUBLICATION_ID>202510</PUBLICATION_ID>", b""),
        IDENTITY.replace(b"<PUBLICATION>", b"<PUBLICATION/><PUBLICATION>"),
        IDENTITY.replace(b"<PUBLICATION>", b"<PUBLICATION><OTHER/></PUBLICATION><PUBLICATION>"),
        IDENTITY.replace(
            b"<PUBLICATION_ID>202510</PUBLICATION_ID>",
            b"<PUBLICATION_ID>202510</PUBLICATION_ID><PUBLICATION_ID>202410</PUBLICATION_ID>",
        ),
    ],
)
def test_refspec_identity_acceptance_stays_separate_from_acquisition(identity):
    payload = _edition(identity)
    pin = _pin(payload)
    assert _verdict(current.parse_unified_agenda_edition, payload, pin) == _verdict(
        old.parse_unified_agenda_edition, payload, pin
    )


def test_exact_source_fixture_matches_frozen_reader():
    payload = FIXTURE.read_bytes()
    pin = _pin(payload, count=2)
    assert _verdict(current.parse_unified_agenda_edition, payload, pin) == _verdict(
        old.parse_unified_agenda_edition, payload, pin
    )


@pytest.mark.parametrize("publication", ["200404", "200410", "202510"])
def test_known_repair_is_checked_after_original_byte_pin(publication):
    payload = _edition(IDENTITY.replace(b"202510", publication.encode()) + b"<ABSTRACT>Department\x19s</ABSTRACT>")
    pin = _pin(payload, publication=publication)
    assert _verdict(current.parse_unified_agenda_edition, payload, pin) == _verdict(
        old.parse_unified_agenda_edition, payload, pin
    )
    with pytest.raises(current.UnifiedAgendaEditionError, match="byte length drifted"):
        current.parse_unified_agenda_edition(payload + b" ", pin=pin)


INTENTIONAL_DIVERGENCES = {
    "doctype": ("accept", "reject"),
    "misplaced_record": ("accept", "reject"),
    "nested_record": ("accept", "reject"),
}


@pytest.mark.parametrize("name", INTENTIONAL_DIVERGENCES)
def test_only_named_source_shape_divergences_change_verdict(name):
    payload = _edition(IDENTITY)
    count = 1
    if name == "doctype":
        payload = b"<!DOCTYPE REGINFO_RIN_DATA>" + payload
    elif name == "misplaced_record":
        payload = payload.replace(b"<RIN_INFO>", b"<WRAPPER><RIN_INFO>").replace(
            b"</RIN_INFO>", b"</RIN_INFO></WRAPPER>"
        )
    else:
        payload = _edition(IDENTITY + b"<RIN_INFO>" + IDENTITY + b"</RIN_INFO>")
        count = 2
    pin = _pin(payload, count=count)
    assert (
        tuple(
            _verdict(reader, payload, pin)[0]
            for reader in (old.parse_unified_agenda_edition, current.parse_unified_agenda_edition)
        )
        == INTENTIONAL_DIVERGENCES[name]
    )


def test_malformed_tail_returns_no_partial_tuple_and_uses_receiver_error():
    payload = _edition(IDENTITY) + b"<trailing>"
    with pytest.raises(current.UnifiedAgendaEditionError, match="XML"):
        current.parse_unified_agenda_edition(payload, pin=_pin(payload))


def test_callback_edition_refusal_keeps_its_receiver_diagnostic():
    payload = _edition(IDENTITY.replace(b"202510", b"202410"))
    with pytest.raises(current.UnifiedAgendaEditionError, match="record declares publication '202410'") as raised:
        current.parse_unified_agenda_edition(payload, pin=_pin(payload))
    assert "malformed" not in str(raised.value)
