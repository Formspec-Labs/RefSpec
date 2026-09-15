"""Frozen Unified Agenda reader from RefSpec cf0f3e7b; test-only oracle."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


_ROOT_TAG = "REGINFO_RIN_DATA"


_RECORD_TAG = "RIN_INFO"


_MANGLED_APOSTROPHE = b"\x19"


UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS: tuple[str, ...] = ("200404", "200410")


class UnifiedAgendaEditionError(ValueError):
    """Raised when a pinned edition does not match what this module expects."""


@dataclass(frozen=True)
class UnifiedAgendaEditionPin:
    """Exact identity of one pinned Unified Agenda edition export."""

    file_stem: str
    publication_id: str
    expected_sha256: str
    expected_byte_length: int
    expected_record_count: int
    run_date: str

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.expected_sha256) is None:
            raise UnifiedAgendaEditionError("expected_sha256 must be sha256:<64 lowercase hex>")
        if self.expected_byte_length <= 0:
            raise UnifiedAgendaEditionError("expected_byte_length must be positive")
        if self.expected_record_count <= 0:
            raise UnifiedAgendaEditionError("expected_record_count must be positive")
        if not re.fullmatch(r"(19|20)\d{2}(04|10)", self.publication_id):
            raise UnifiedAgendaEditionError(f"publication_id must be YYYYMM with MM in 04/10: {self.publication_id!r}")


@dataclass(frozen=True)
class TimetableEntry:
    """One row of a RIN's timetable, exactly as the publisher wrote it.

    ``fr_citation`` is the raw "VV FR PPPPP" string or ``None`` when the row
    carries none — projected future actions usually don't. ``date_text`` keeps
    the publisher's MM/DD/YYYY verbatim, because a projected month is written
    with a zero day ("11/00/2026") and normalizing that would invent a date.
    """

    action: str
    date_text: str
    fr_citation: str | None


@dataclass(frozen=True)
class UnifiedAgendaRecord:
    """One regulatory action, with the publisher's own citation lists."""

    rin: str
    publication_id: str
    cfr_references: tuple[str, ...]
    legal_authorities: tuple[str, ...]
    timetable: tuple[TimetableEntry, ...] = ()
    #: ``ADDITIONAL_INFO`` as published, whitespace INTACT. The XSD declares it
    #: an unrestricted string with no documentation at all
    #: (reginfo-rin-data-ver10262011.xsd line 177), and the filers use it as a
    #: continuation sheet: when a citation list outruns its boxes the rest of
    #: it is typed here under a label. See
    #: :func:`legal_authority_continuations`.
    #:
    #: Whitespace is intact and every other field's is collapsed, deliberately:
    #: this one field carries SEVERAL of the form's fields inside it, and what
    #: separates them is a blank line or the publisher's own "^P" paragraph
    #: mark. Collapsing that erases the only thing that says where one field's
    #: continuation ends.
    additional_info: str = ""


def _text(element: ET.Element | None) -> str:
    return "" if element is None else " ".join((element.text or "").split())


def _raw_text(element: ET.Element | None) -> str:
    """Everything an element holds, whitespace intact.

    ``itertext`` rather than ``.text`` so that a child element could never take
    its tail text away with it. Measured over all 241,726 records of the 60
    pinned editions: no ``ADDITIONAL_INFO`` element has a child, so today the
    two spellings agree -- and if one ever grows one, nothing vanishes.
    """

    return "" if element is None else "".join(element.itertext())


def parse_unified_agenda_edition(
    payload: bytes,
    *,
    pin: UnifiedAgendaEditionPin,
) -> tuple[UnifiedAgendaRecord, ...]:
    """Read one pinned edition, refusing anything that is not exactly it.

    The digest is taken over the bytes as served, before the apostrophe
    repair, so a capture can always be re-verified against what the endpoint
    returned. The repair is applied only to the in-memory copy handed to the
    parser.
    """

    if len(payload) != pin.expected_byte_length:
        raise UnifiedAgendaEditionError(
            f"{pin.file_stem} byte length drifted: expected {pin.expected_byte_length}, got {len(payload)}"
        )
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if digest != pin.expected_sha256:
        raise UnifiedAgendaEditionError(f"{pin.file_stem} digest drifted: expected {pin.expected_sha256}, got {digest}")

    repaired = payload.replace(_MANGLED_APOSTROPHE, "\u2019".encode())
    if (repaired is not payload and repaired != payload) != (
        pin.publication_id in UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS
    ):
        raise UnifiedAgendaEditionError(
            f"{pin.file_stem} mangled-apostrophe presence does not match the recorded roster"
        )

    root = ET.fromstring(repaired)
    if root.tag != _ROOT_TAG:
        raise UnifiedAgendaEditionError(f"{pin.file_stem} root element is {root.tag!r}, not {_ROOT_TAG!r}")

    records: list[UnifiedAgendaRecord] = []
    for element in root.findall(f".//{_RECORD_TAG}"):
        publication_id = _text(element.find("PUBLICATION/PUBLICATION_ID"))
        if publication_id != pin.publication_id:
            raise UnifiedAgendaEditionError(
                f"{pin.file_stem} record declares publication {publication_id!r}, not the pinned {pin.publication_id!r}"
            )
        cfr_list = element.find("CFR_LIST")
        authority_list = element.find("LEGAL_AUTHORITY_LIST")
        timetable_list = element.find("TIMETABLE_LIST")
        timetable = tuple(
            TimetableEntry(
                action=_text(entry.find("TTBL_ACTION")),
                date_text=_text(entry.find("TTBL_DATE")),
                fr_citation=_text(entry.find("FR_CITATION")) or None,
            )
            for entry in ([] if timetable_list is None else timetable_list.findall("TIMETABLE"))
        )
        records.append(
            UnifiedAgendaRecord(
                rin=_text(element.find("RIN")),
                publication_id=publication_id,
                # `if element:` on an ElementTree node tests child count, not
                # presence, and is deprecated for exactly that ambiguity -- an
                # empty <CFR_LIST> is falsy while being perfectly present.
                cfr_references=tuple(
                    text for child in (() if cfr_list is None else cfr_list) if (text := _text(child))
                ),
                legal_authorities=tuple(
                    text for child in (() if authority_list is None else authority_list) if (text := _text(child))
                ),
                timetable=timetable,
                # Whitespace INTACT -- see the field's own comment on
                # UnifiedAgendaRecord for why this one field is not collapsed.
                additional_info=_raw_text(element.find("ADDITIONAL_INFO")),
            )
        )

    if len(records) != pin.expected_record_count:
        raise UnifiedAgendaEditionError(
            f"{pin.file_stem} record count drifted: expected {pin.expected_record_count}, got {len(records)}"
        )
    return tuple(records)
