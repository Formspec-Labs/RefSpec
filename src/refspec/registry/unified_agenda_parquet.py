"""Typed Parquet tables derived from the pinned Unified Agenda editions.

Pinning 981 MB of XML and a reader is not enough. Without a derived artifact
every consumer re-parses the same sixty files, and each one independently
rediscovers the same two things: that Spring and Fall 2004 are not well-formed
XML, and that the publisher's structured ``CFR_LIST`` needs a citation parse
before it joins to anything. That already happened once -- a downstream session
hit both and had to solve both again -- which is the argument for this module.

The repair happens here, once. The citation parse happens here, once. What a
consumer reads is three flat tables with typed columns.

    unified_agenda_actions          one row per (rin, publication_id)
    unified_agenda_cfr_references   one row per cited CFR reference
    unified_agenda_legal_authorities one row per cited legal authority

**Nothing is filtered.** The publisher's damage is carried into the columns and
labelled, not dropped: ``cfr_title`` is whatever the reference actually says,
including the 115 references to Reserved title 35 and the 36 to title 0, and
``cfr_title_is_possible`` states the verdict without acting on it. A consumer
that wants only real citations filters on that column and can see exactly what
it discarded; a consumer studying publisher data quality reads the same rows
from the other side. Neither has to trust this module's opinion.

``reference_text`` and ``authority_text`` always carry the publisher's original
string beside the parsed fields, so a parse this module got wrong is visible
rather than lost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from refspec.atlas.parquet_artifact import arrow_schema_sha256, file_sha256
from refspec.registry.citation_grammar import parse_authority_citation, parse_cfr_citations
from refspec.registry.unified_agenda_editions import (
    UNIFIED_AGENDA_EDITION_PINS,
    UnifiedAgendaEditionPin,
    parse_unified_agenda_edition,
)

__all__ = [
    "ACTIONS_SCHEMA",
    "CFR_REFERENCES_SCHEMA",
    "LEGAL_AUTHORITIES_SCHEMA",
    "UnifiedAgendaParquetReceipt",
    "build_unified_agenda_parquet",
]

ACTIONS_SCHEMA = pa.schema(
    [
        pa.field("rin", pa.string(), nullable=False),
        pa.field("publication_id", pa.string(), nullable=False),
        pa.field("cfr_reference_count", pa.int32(), nullable=False),
        pa.field("legal_authority_count", pa.int32(), nullable=False),
    ]
)

CFR_REFERENCES_SCHEMA = pa.schema(
    [
        pa.field("rin", pa.string(), nullable=False),
        pa.field("publication_id", pa.string(), nullable=False),
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("reference_text", pa.string(), nullable=False),
        pa.field("cfr_title", pa.int32(), nullable=True),
        pa.field("cfr_part", pa.string(), nullable=True),
        pa.field("cfr_title_is_possible", pa.bool_(), nullable=True),
        pa.field("cfr_section", pa.string(), nullable=True),
        pa.field("cfr_part_is_plausible", pa.bool_(), nullable=True),
        pa.field("citation_ordinal", pa.int32(), nullable=False),
    ]
)

LEGAL_AUTHORITIES_SCHEMA = pa.schema(
    [
        pa.field("rin", pa.string(), nullable=False),
        pa.field("publication_id", pa.string(), nullable=False),
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("authority_text", pa.string(), nullable=False),
        pa.field("authority_type", pa.string(), nullable=True),
        pa.field("usc_title", pa.int32(), nullable=True),
        pa.field("usc_section", pa.string(), nullable=True),
        pa.field("public_law", pa.string(), nullable=True),
        pa.field("executive_order", pa.string(), nullable=True),
    ]
)


@dataclass(frozen=True)
class UnifiedAgendaParquetReceipt:
    """What was built, from which pinned bytes."""

    editions: int
    actions: int
    cfr_references: int
    legal_authorities: int
    source_sha256_by_edition: dict[str, str]
    outputs: dict[str, str]
    schema_digests: dict[str, str]


@dataclass(frozen=True)
class ParsedCfrReference:
    """One publisher CFR reference, split and judged but never discarded."""

    cfr_title: int | None
    cfr_part: str | None
    cfr_title_is_possible: bool | None
    cfr_part_is_plausible: bool | None
    cfr_additional_parts: tuple[str, ...]


def parse_cfr_reference(text: str) -> ParsedCfrReference:
    """Split one publisher CFR reference without repairing or dropping it.

    Every field is nullable and every verdict is separate from every value, so
    a consumer can filter on a judgement while still seeing what was judged.

    ``cfr_title`` is null when the string does not begin with a title number --
    about 5% of the field, carrying ``(app B)``, ``(new)`` and bare ``...``.
    ``cfr_part`` is null when no part can be read without inventing one, which
    now includes rule numbers like ``15c3-3``. ``cfr_part_is_plausible`` is
    false for parts longer than four digits, the publisher's fused-dot damage.
    ``cfr_additional_parts`` carries the tail of a list reference, so
    ``17 CFR parts 37, 38, 39`` does not silently become part 37 alone.
    """

    match = _CFR_REFERENCE.match(text)
    if match is None:
        # A title with no readable part still tells a consumer the title.
        title_only = re.match(r"^\s*(?P<title>\d+)\s*C\.?\s?F\.?\s?R\.?", text, re.IGNORECASE)
        if title_only is None:
            return ParsedCfrReference(None, None, None, None, ())
        title = int(title_only.group("title"))
        return ParsedCfrReference(
            title,
            None,
            1 <= title <= _MAX_CFR_TITLE and title not in CFR_RESERVED_TITLES,
            None,
            (),
        )
    title = int(match.group("title"))
    part = match.group("part")
    digits = "".join(character for character in part if character.isdigit())
    return ParsedCfrReference(
        cfr_title=title,
        cfr_part=part,
        cfr_title_is_possible=1 <= title <= _MAX_CFR_TITLE and title not in CFR_RESERVED_TITLES,
        cfr_part_is_plausible=len(digits) <= _MAX_PLAUSIBLE_PART_DIGITS,
        cfr_additional_parts=tuple(_ADDITIONAL_PARTS.findall(text[match.end() :])),
    )


def _edition_payload(pin: UnifiedAgendaEditionPin, source_root: Path) -> bytes:
    return (source_root / f"REGINFO_RIN_DATA_{pin.file_stem}.xml").read_bytes()


def build_unified_agenda_parquet(
    source_root: Path,
    output_root: Path,
    *,
    pins: tuple[UnifiedAgendaEditionPin, ...] = UNIFIED_AGENDA_EDITION_PINS,
) -> UnifiedAgendaParquetReceipt:
    """Read every pinned edition once and write the three tables."""

    output_root.mkdir(parents=True, exist_ok=True)
    actions: list[dict[str, object]] = []
    references: list[dict[str, object]] = []
    authorities: list[dict[str, object]] = []
    digests: dict[str, str] = {}

    for pin in pins:
        payload = _edition_payload(pin, source_root)
        # parse_unified_agenda_edition authenticates the digest against the pin
        # and applies the 2004 apostrophe repair in memory. Both happen here so
        # no consumer has to know either is necessary.
        records = parse_unified_agenda_edition(payload, pin=pin)
        digests[pin.publication_id] = pin.expected_sha256
        for record in records:
            actions.append(
                {
                    "rin": record.rin,
                    "publication_id": record.publication_id,
                    "cfr_reference_count": len(record.cfr_references),
                    "legal_authority_count": len(record.legal_authorities),
                }
            )
            for ordinal, text in enumerate(record.cfr_references):
                # A structured field is entirely a citation, so a comma-list
                # continues it whatever label it carries -- 953 references in
                # this field list parts with no label at all.
                parsed = parse_cfr_citations(text, list_expansion="always")
                if not parsed:
                    references.append(
                        {
                            "rin": record.rin,
                            "publication_id": record.publication_id,
                            "ordinal": ordinal,
                            "reference_text": text,
                            "cfr_title": None,
                            "cfr_part": None,
                            "cfr_title_is_possible": None,
                            "cfr_section": None,
                            "cfr_part_is_plausible": None,
                            "citation_ordinal": 0,
                        }
                    )
                for citation_ordinal, citation in enumerate(parsed):
                    references.append(
                        {
                            "rin": record.rin,
                            "publication_id": record.publication_id,
                            "ordinal": ordinal,
                            "reference_text": text,
                            "cfr_title": citation.cfr_title,
                            "cfr_part": citation.cfr_part,
                            "cfr_title_is_possible": citation.title_is_possible,
                            "cfr_section": citation.cfr_section,
                            "cfr_part_is_plausible": citation.part_is_plausible,
                            "citation_ordinal": citation_ordinal,
                        }
                    )
            for ordinal, text in enumerate(record.legal_authorities):
                base = {
                    "rin": record.rin,
                    "publication_id": record.publication_id,
                    "ordinal": ordinal,
                    "authority_text": text,
                }
                parsed_authorities = parse_authority_citation(text)
                if not parsed_authorities:
                    authorities.append({**base, "authority_type": None, "usc_title": None,
                                        "usc_section": None, "public_law": None, "executive_order": None})
                for authority in parsed_authorities:
                    authorities.append({**base, "authority_type": authority.authority_type,
                                        "usc_title": authority.usc_title, "usc_section": authority.usc_section,
                                        "public_law": authority.public_law,
                                        "executive_order": authority.executive_order})

    outputs: dict[str, str] = {}
    schema_digests: dict[str, str] = {}
    for name, rows, schema in (
        ("unified_agenda_actions", actions, ACTIONS_SCHEMA),
        ("unified_agenda_cfr_references", references, CFR_REFERENCES_SCHEMA),
        ("unified_agenda_legal_authorities", authorities, LEGAL_AUTHORITIES_SCHEMA),
    ):
        table = pa.Table.from_pylist(rows, schema=schema)
        path = output_root / f"{name}.parquet"
        # Deterministic settings: the same pinned bytes must produce the same
        # file, or this artifact cannot be pinned in turn.
        pq.write_table(table, path, compression="zstd", compression_level=3, write_statistics=False)
        outputs[name] = file_sha256(path)
        schema_digests[name] = arrow_schema_sha256(schema)

    return UnifiedAgendaParquetReceipt(
        editions=len(pins),
        actions=len(actions),
        cfr_references=len(references),
        legal_authorities=len(authorities),
        source_sha256_by_edition=digests,
        outputs=outputs,
        schema_digests=schema_digests,
    )
