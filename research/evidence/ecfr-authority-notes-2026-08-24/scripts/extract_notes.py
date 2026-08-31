#!/usr/bin/env python3
"""Every CFR part's own authority note, taken from the full title XML.

The eCFR versioner serves a whole title as one XML document. A part is a
``<DIV5 TYPE="PART">``; the agency's statement of authority is an ``<AUTH>``
element and the publisher's source note a ``<SOURCE>`` element, both written
immediately under the part's ``<HEAD>`` and before the part's first
subdivision::

    <DIV5 N="310" TYPE="PART" VOLUME="5">
    <HEAD>PART 310—NEW DRUGS</HEAD>
    <AUTH>
    <HED>Authority:</HED><PSPACE>21 U.S.C. 321, 331, ...
    </PSPACE></AUTH>
    <SOURCE>
    <HED>Source:</HED><PSPACE>40 FR 13998, Mar. 27, 1975, unless otherwise noted.
    </PSPACE></SOURCE>

An ``<AUTH>`` also occurs under ``<DIV6 TYPE="SUBPART">`` and
``<DIV7 TYPE="SUBJGRP">``, where it states the authority of that subdivision
alone. The rule for the part's own note is therefore positional and not a
search: only an ``<AUTH>`` that opens before the part's first ``<DIV6>``,
``<DIV7>``, ``<DIV8>`` or ``<DIV9>`` belongs to the part itself.

**Some heavily-cited parts state no authority at part level at all** -- 20 CFR
404 and 5 CFR 550 open straight into Subpart A, whose ``<AUTH>`` is the first
one in the document. Generation 1, reading a per-part response, took that first
``<AUTH>`` and stored it as the part's note; dropping such parts here would
lose 20 CFR 404 and 416, two of the most-cited parts in the Agenda corpus. So
they are emitted, with the level said out loud rather than blurred:
``authority_level`` is ``"part"`` or ``"subdivision"``, ``authority_scope``
names the subdivision the text was taken from, and a subdivision-sourced row
also carries ``subdivision_authority_notes`` -- every subdivision note in the
part, in document order, so a consumer reading one subpart's authority as the
whole part's can see the rest. Nothing is concatenated and nothing is invented:
each string is one element's text as published. A part with no ``<AUTH>``
anywhere gets no row and is counted instead.

Output is generation-1-compatible: one JSON object per line carrying exactly
the fields ``refspec.registry.cfr_authority_notes.CfrAuthorityNotes.from_file``
reads (``cfr_title``, ``cfr_part``, ``authority_note``, ``source_note``,
``api_url``, ``fetched``, ``raw_sha256``, ``raw_bytes``,
``raw_truncated_at_128k``), plus provenance fields that reader ignores:
``title_issue_date``, ``title_xml_sha256``, ``title_xml_bytes``,
``part_api_url``, ``part_head``, ``authority_level``, ``authority_scope``,
``subdivision_auth_count`` and, where the note came from a subdivision,
``subdivision_authority_notes``.

Three decisions, the first two made to match what generation 1 stored:

* **The label stays on.** ``authority_note`` begins "Authority: " because the
  ``<HED>`` is part of the element and the reader strips it itself
  (``note_body``). Same for "Source: ".
* **Character references are left as the source writes them.** Generation 1's
  per-part responses spelled a section sign ``&#xA7;`` and an em dash
  ``&#x2014;``; the full-title documents spell both as literal UTF-8. Neither
  is decoded nor re-encoded here -- the note is stored as the document writes
  it, and ``note_body``'s ``html.unescape`` makes the two spellings read
  identically. ``&amp;``, ``&lt;`` and ``&gt;`` are XML syntax rather than the
  publisher's characters and are left alone for the same reason.
* **Markup inside the note becomes a single space**, and runs of whitespace
  collapse to one, so ``<PSPACE>620 <I>et seq.</I>\\n</PSPACE>`` reads
  "620 et seq." and a multi-paragraph ``<AUTH>`` (``<HED><PSPACE><P>``) reads
  as one line -- which is how generation 1 stored it and how the publisher
  prints it.

    python3 extract_notes.py XML_DIR OUT_DIR

``XML_DIR`` holds ``manifest.json`` and ``title-{N}.xml`` from
``fetch_titles.py``. Writes ``notes.jsonl`` and ``extraction-census.json``.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

#: The date the corpus was taken off the API, carried in every record the way
#: generation 1 carried its own. A title's own issue date is a separate field,
#: because the two are not the same fact.
FETCHED = "2026-08-24"

#: One pass, one pattern: a division opening, a division closing, or the start
#: of one of the three elements whose text is read. Scanning for five patterns
#: separately re-reads the gap to the farthest of them on every step, which on
#: a 700 MB title is the difference between seconds and hours.
_EVENT = re.compile(rb"<DIV(\d)\b([^>]*)>|</DIV(\d)>|<(AUTH|SOURCE|HEAD)\b[^>]*>")
_CLOSER = {
    b"AUTH": re.compile(rb"</AUTH>"),
    b"SOURCE": re.compile(rb"</SOURCE>"),
    b"HEAD": re.compile(rb"</HEAD>"),
}
_ATTRIBUTE = re.compile(rb'(\w+)="([^"]*)"')

#: A division whose appearance ends the part's header region.
_SUBDIVISION_LEVELS = {b"6", b"7", b"8", b"9"}

_TAG = re.compile(r"<[^>]*>")
_WHITESPACE = re.compile(r"\s+")
_BLOCK = 1 << 22


def flatten(markup: bytes) -> str:
    """An element's text: markup to a space, whitespace collapsed, entities kept."""

    return _WHITESPACE.sub(" ", _TAG.sub(" ", markup.decode("utf-8"))).strip()


def iter_markup(path: Path):
    """``(kind, payload)`` for every structural event in a title document.

    ``kind`` is ``div-open`` (payload ``(level, number, type)``), ``div-close``
    (payload ``level``), or ``head``/``auth``/``source`` (payload: the
    element's raw inner markup). The document is read in blocks and the buffer
    is trimmed to the earliest byte still needed, so a title that does not fit
    in memory is still one linear pass.
    """

    with path.open("rb") as handle:
        buffer = b""
        position = 0
        eof = False
        while True:
            match = _EVENT.search(buffer, position)
            incomplete_from: int | None = None
            if match is None:
                incomplete_from = position
            elif match.group(4) is not None:
                closer = _CLOSER[match.group(4)]
                end = closer.search(buffer, match.end())
                if end is None:
                    incomplete_from = match.start()
                else:
                    yield match.group(4).decode("ascii").lower(), buffer[match.end() : end.start()]
                    position = end.end()
            elif match.group(1) is not None:
                attributes = dict(_ATTRIBUTE.findall(match.group(2)))
                yield (
                    "div-open",
                    (
                        match.group(1),
                        attributes.get(b"N", b"").decode("utf-8"),
                        attributes.get(b"TYPE", b"").decode("utf-8"),
                    ),
                )
                position = match.end()
            else:
                yield "div-close", match.group(3)
                position = match.end()

            if incomplete_from is None:
                continue
            if eof:
                # Malformed tail: step past it rather than spin.
                if match is None:
                    break
                position = match.end()
                continue
            buffer = buffer[incomplete_from:]
            position = 0
            block = handle.read(_BLOCK)
            if not block:
                eof = True
            buffer += block


class Part:
    """One ``<DIV5 TYPE="PART">`` as the scanner accumulates it."""

    def __init__(self, number: str) -> None:
        self.number = number
        self.head: str | None = None
        self.authority: str | None = None
        self.source: str | None = None
        self.subdivision_notes: list[tuple[str, str]] = []
        self.in_header = True
        self.awaiting_head = True
        self.subdivision = "part"

    @property
    def authority_level(self) -> str | None:
        if self.authority is not None:
            return "part"
        return "subdivision" if self.subdivision_notes else None

    @property
    def note(self) -> str | None:
        """The part's note: its own where it has one, else the first stated
        under it -- which is the one generation 1 stored, reading a per-part
        response top-down."""

        if self.authority is not None:
            return self.authority
        return self.subdivision_notes[0][1] if self.subdivision_notes else None

    @property
    def scope(self) -> str | None:
        if self.authority is not None:
            return "part"
        return self.subdivision_notes[0][0] if self.subdivision_notes else None


def extract_title(path: Path):
    """Every ``Part`` in one title document, in document order."""

    part: Part | None = None
    subdivision = "part"

    for kind, payload in iter_markup(path):
        if kind == "div-open":
            level, number, div_type = payload
            if level == b"5" and div_type == "PART":
                if part is not None:
                    yield part
                part, subdivision = Part(number), "part"
            elif level in _SUBDIVISION_LEVELS:
                if part is not None:
                    part.in_header = False
                    part.awaiting_head = False
                if level in (b"6", b"7"):
                    subdivision = f"{div_type or 'DIV' + level.decode()} {number}".strip()
            else:
                if part is not None:
                    yield part
                part, subdivision = None, "part"
        elif kind == "div-close" and payload == b"5":
            if part is not None:
                yield part
            part, subdivision = None, "part"
        elif kind == "head":
            if part is not None and part.awaiting_head and part.head is None:
                part.head = flatten(payload)
            if part is not None:
                part.awaiting_head = False
        elif kind == "auth":
            if part is None:
                continue
            if part.in_header:
                if part.authority is None:
                    part.authority = flatten(payload)
            else:
                part.subdivision_notes.append((subdivision, flatten(payload)))
        elif kind == "source":
            if part is not None and part.in_header and part.source is None:
                part.source = flatten(payload)
    if part is not None:
        yield part


_LEADING_DIGITS = re.compile(r"^(\d+)(.*)$")


def part_order(part: str) -> tuple[int, str]:
    """A part number's sort key, as the Code orders them: digits, then text."""

    match = _LEADING_DIGITS.match(part)
    return (int(match.group(1)), match.group(2)) if match else (10**9, part)


def main() -> int:
    xml_dir = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((xml_dir / "manifest.json").read_text())

    rows: list[dict] = []
    census: list[dict] = []
    #: Every part number the scanner saw and the head it was published under,
    #: per title. A part here with no row in ``notes.jsonl`` publishes no
    #: authority note; a part in neither does not exist in the title at its
    #: current date; and the head says which of those is a ``[RESERVED]``
    #: placeholder ("PART 405 [RESERVED]") or a whole reserved block ("PARTS
    #: 413-459[RESERVED]"). The coverage census needs all three distinctions
    #: and cannot recover any of them from the notes alone.
    seen_parts: dict[int, dict[str, str | None]] = {}
    for entry in manifest["titles"]:
        if not entry.get("ok"):
            census.append(
                {
                    "title": entry["title"],
                    "date": entry.get("date"),
                    "parts_seen": None,
                    "notes_extracted": None,
                    "parts_without_note": None,
                    "subdivision_only_auth_parts": None,
                    "skipped": entry.get("hole_reason") or "reserved title, no document published",
                }
            )
            continue
        path = xml_dir / entry["path"]
        seen = part_level = subdivision_level = without = 0
        counted: dict[str, int] = {}
        heads: dict[str, str | None] = {}
        for part in extract_title(path):
            seen += 1
            counted[part.number] = counted.get(part.number, 0) + 1
            heads.setdefault(part.number, part.head)
            level = part.authority_level
            if level is None:
                without += 1
                continue
            if level == "part":
                part_level += 1
            else:
                subdivision_level += 1
            row = {
                "api_url": entry["url"],
                "authority_level": level,
                "authority_note": part.note,
                "authority_scope": part.scope,
                "cfr_part": part.number,
                "cfr_title": entry["title"],
                "fetched": FETCHED,
                "part_api_url": f"{entry['url']}?part={part.number}",
                "part_head": part.head,
                "raw_bytes": entry["bytes"],
                "raw_sha256": entry["sha256"],
                "raw_truncated_at_128k": False,
                "source_note": part.source,
                "subdivision_auth_count": len(part.subdivision_notes),
                "title_issue_date": entry["date"],
                "title_xml_bytes": entry["bytes"],
                "title_xml_sha256": entry["sha256"],
            }
            if level == "subdivision":
                row["subdivision_authority_notes"] = [
                    {"scope": scope, "authority_note": text} for scope, text in part.subdivision_notes
                ]
            rows.append(row)
        census.append(
            {
                "title": entry["title"],
                "date": entry["date"],
                "parts_seen": seen,
                "notes_extracted": part_level + subdivision_level,
                "part_level_notes": part_level,
                "subdivision_level_notes": subdivision_level,
                "parts_without_note": without,
                "duplicate_part_numbers": sorted(p for p, n in counted.items() if n > 1),
                "skipped": None,
            }
        )
        seen_parts[entry["title"]] = {number: heads[number] for number in sorted(counted, key=part_order)}
        print(
            f"title {entry['title']}: {seen} parts, {part_level + subdivision_level} notes"
            f" ({subdivision_level} from a subdivision), {without} without",
            flush=True,
        )

    rows.sort(key=lambda row: (row["cfr_title"], part_order(row["cfr_part"])))
    with (out_dir / "notes.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")

    summary = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "fetched": FETCHED,
        "titles_endpoint": manifest["titles_endpoint"],
        "full_endpoint_template": manifest["full_endpoint_template"],
        "notes": len(rows),
        "parts_seen": sum(one["parts_seen"] or 0 for one in census),
        "part_level_notes": sum(one.get("part_level_notes") or 0 for one in census),
        "subdivision_level_notes": sum(one.get("subdivision_level_notes") or 0 for one in census),
        "parts_without_note": sum(one["parts_without_note"] or 0 for one in census),
        "titles": census,
    }
    (out_dir / "extraction-census.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / "parts-seen.json").write_text(json.dumps({str(k): v for k, v in sorted(seen_parts.items())}, indent=1) + "\n")
    print(
        f"done: {summary['notes']} notes from {summary['parts_seen']} parts"
        f" ({summary['subdivision_level_notes']} from a subdivision),"
        f" {summary['parts_without_note']} with no note at all",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
