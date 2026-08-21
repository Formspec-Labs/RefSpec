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
from refspec.registry.cfr_list_of_subjects import CFR_RESERVED_TITLES
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
    "parse_cfr_reference",
]

#: The CFR is titles 1-50. Anything else cannot be a CFR citation, whatever the
#: publisher wrote. Reserved titles are real numbers with no content.
_MAX_CFR_TITLE = 50

# "40 CFR 194", "40 CFR Part 194", "40 C.F.R. 194.5", "5 CFR part 2635 App B".
# The part is taken up to the first dot: a section cite (302.32) names part 302,
# which is the granularity the CFR subject index is keyed at.
_CFR_REFERENCE = re.compile(
    r"^\s*(?P<title>\d+)\s*C\.?\s?F\.?\s?R\.?\s*"
    # "part", "pt.", one or more section signs, or any mixture, in any order:
    # the field carries "45 CFR part 302", "45 CFR § 302.32(b)" and
    # "45 CFR §§ 1302.90(e)". Omitting the section sign silently returned a
    # NULL part for every section-level citation, which is the commonest
    # shape in prose and the one this table exists to resolve.
    r"(?:(?:part|pt\.?|§)+\s*)*"
    r"(?P<part>\d+[A-Za-z]?)?",
    re.IGNORECASE,
)

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
    ]
)

LEGAL_AUTHORITIES_SCHEMA = pa.schema(
    [
        pa.field("rin", pa.string(), nullable=False),
        pa.field("publication_id", pa.string(), nullable=False),
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("authority_text", pa.string(), nullable=False),
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


def parse_cfr_reference(text: str) -> tuple[int | None, str | None, bool | None]:
    """Split one publisher CFR reference into (title, part, title_is_possible).

    Returns ``(None, None, None)`` when the string does not begin with a title
    number -- roughly 15% of the field, which carries values like ``(app B)``,
    ``(new)`` and bare ``...``. Those are not parse failures to repair; they are
    what the publisher wrote, and the caller still has ``reference_text``.
    """

    match = _CFR_REFERENCE.match(text)
    if match is None:
        return None, None, None
    title = int(match.group("title"))
    possible = 1 <= title <= _MAX_CFR_TITLE and title not in CFR_RESERVED_TITLES
    return title, match.group("part"), possible


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
                title, part, possible = parse_cfr_reference(text)
                references.append(
                    {
                        "rin": record.rin,
                        "publication_id": record.publication_id,
                        "ordinal": ordinal,
                        "reference_text": text,
                        "cfr_title": title,
                        "cfr_part": part,
                        "cfr_title_is_possible": possible,
                    }
                )
            for ordinal, text in enumerate(record.legal_authorities):
                authorities.append(
                    {
                        "rin": record.rin,
                        "publication_id": record.publication_id,
                        "ordinal": ordinal,
                        "authority_text": text,
                    }
                )

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
