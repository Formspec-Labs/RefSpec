"""Cut the 1994 Title 49 disposition table out of the govinfo PDF.

Source (pinned by sha256 and byte length below):
https://www.govinfo.gov/content/pkg/USCODE-1994-title49/pdf/USCODE-1994-title49.pdf

Pages 1-12 of that volume carry "TABLE SHOWING DISPOSITION OF FORMER SECTIONS
OF TITLE 49": two table blocks per page, each two columns ("Title 49 Former
Sections" | "Title 49 New Sections"), rows joined by a dot leader, long former
descriptions wrapped onto indented continuation lines that carry no value.

Why ``-bbox-layout`` and not ``-layout``
---------------------------------------
``pdftotext -layout`` renders both table blocks side by side on one text line,
so a row of the left block and an unrelated row of the right block share a
line; and inside a block, justified continuation lines
(``1515(e)(2)(B),         and         Postal``) put runs of three or more
spaces in the middle of the *former* field, which defeats every "split on the
widest gap" rule. ``-bbox-layout`` gives each line its own bounding box, and
poppler already segments the page into the four sub-columns as separate
blocks, so the split is geometric and checkable rather than typographic.

The pairing is by baseline: a table row is one former-column line and the
new-column line at the same ``yMin``. A continuation line has no new-column
line at its baseline, which is exactly how the print says "still the same
row".

Every structural assumption is asserted, and a violated one raises rather than
dropping a row: one former-column block per table block, no line straddling
the column split, every new-column line matched to a former-column line.

Emits a Parquet table, one row per (former section token x successor), each
carrying the table's own text in ``former_text`` and ``new_text`` so nothing
the printed row said is lost.

Run:
    python3 extract_disposition_table.py <pdf> <out.parquet> [--json <out.json>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://www.w3.org/1999/xhtml}"

#: The pinned source. Both are re-checked before a single page is read.
SOURCE_URL = "https://www.govinfo.gov/content/pkg/USCODE-1994-title49/pdf/USCODE-1994-title49.pdf"
SOURCE_SHA256 = "66f004679e27e0d16356e14b79cb3b4f7ebf63d91307435fa8f53c95bcc2848d"
SOURCE_BYTES = 5165242
#: The extractor pinned too: poppler's column segmentation is what this reads.
PDFTOTEXT_VERSION = "pdftotext version 26.06.0"

#: Pages carrying the table, and the x geometry of the four sub-columns. The
#: header blocks sit at exactly these x on every one of the twelve pages, so
#: the split between "former" and "new" is the midpoint between the former
#: header's right edge and the new header's left edge.
TABLE_PAGES = range(1, 13)
COLUMN_SPLIT = {"left": (167.0 + 230.0) / 2, "right": (386.0 + 449.0) / 2}
HALF_SPLIT = 306.0
#: Two baselines are the same row when their yMin differ by less than this.
BASELINE_TOLERANCE = 1.5

_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))


def _run(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def verify_source(pdf: Path) -> None:
    """Refuse to read a PDF that is not the pinned one, or a drifted poppler."""

    version = _run(["pdftotext", "-v"]) + subprocess.run(
        ["pdftotext", "-v"], capture_output=True, text=True, check=True
    ).stderr
    if PDFTOTEXT_VERSION not in version:
        raise SystemExit(f"pdftotext drifted: expected {PDFTOTEXT_VERSION!r}")
    raw = pdf.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != SOURCE_BYTES or digest != SOURCE_SHA256:
        raise SystemExit(
            f"source drifted: expected sha256:{SOURCE_SHA256} ({SOURCE_BYTES} bytes), "
            f"observed sha256:{digest} ({len(raw)} bytes) — {SOURCE_URL}"
        )


def page_blocks(pdf: Path, page: int) -> list[dict]:
    """Every poppler block on one page, with its lines and their boxes."""

    xml = _run(["pdftotext", "-bbox-layout", "-f", str(page), "-l", str(page), str(pdf), "-"])
    root = ET.fromstring(xml)
    blocks = []
    for block in root.iter(NS + "block"):
        lines = []
        for line in block.iter(NS + "line"):
            words = [w.text or "" for w in line.iter(NS + "word")]
            if not words:
                continue
            lines.append(
                {
                    "xMin": float(line.get("xMin")),
                    "xMax": float(line.get("xMax")),
                    "yMin": float(line.get("yMin")),
                    "text": " ".join(words).translate(_DASHES),
                }
            )
        if lines:
            blocks.append(
                {
                    "xMin": float(block.get("xMin")),
                    "xMax": float(block.get("xMax")),
                    "yMin": float(block.get("yMin")),
                    "yMax": float(block.get("yMax")),
                    "lines": lines,
                }
            )
    return blocks


def merge_baselines(lines: list[dict]) -> list[dict]:
    """One record per printed baseline, whatever poppler split it into.

    A justified continuation line — ``303(a)(14) (words     after     2d`` —
    comes back from ``-bbox-layout`` as four ``<line>`` elements, because the
    inter-word gaps are wider than poppler's line-break threshold. They share a
    baseline, so they are one printed line and are joined left to right.
    """

    merged: list[dict] = []
    for line in sorted(lines, key=lambda ln: (ln["yMin"], ln["xMin"])):
        if merged and abs(merged[-1]["yMin"] - line["yMin"]) < BASELINE_TOLERANCE:
            merged[-1]["text"] = f"{merged[-1]['text']} {line['text']}"
            merged[-1]["xMax"] = max(merged[-1]["xMax"], line["xMax"])
            continue
        merged.append(dict(line))
    return merged


#: Running heads, folios and the repeated table caption. Excluded by what they
#: say, because they sit inside the column geometry and nothing else does.
_FURNITURE = re.compile(r"^(Page \d+|TITLE 49[-—]TRANSPORTATION|T ITLE 49[-—]Continued)$")


def _is_furniture(block: dict) -> bool:
    return all(_FURNITURE.match(line["text"]) for line in block["lines"])


def _header(blocks: list[dict], label: str, half: str) -> dict | None:
    """The two-line ``Title 49`` / ``<label> Sections`` column header."""

    lo, hi = (0.0, HALF_SPLIT) if half == "left" else (HALF_SPLIT, 1e9)
    found = [
        b
        for b in blocks
        if lo <= b["xMin"] < hi and len(b["lines"]) == 2 and b["lines"][1]["text"] == f"{label} Sections"
    ]
    if len(found) > 1:
        raise SystemExit(f"more than one {label} header in the {half} half")
    return found[0] if found else None


def table_rows(pdf: Path, page: int, half: str) -> list[dict]:
    """The printed rows of one table block: former line + value at its baseline.

    Returns one record per *printed line* of the former column, with
    ``new`` set only on the lines a value shares a baseline with.
    """

    blocks = page_blocks(pdf, page)
    former_header = _header(blocks, "Former", half)
    new_header = _header(blocks, "New", half)
    if former_header is None or new_header is None:
        if former_header is not new_header:
            raise SystemExit(f"page {page} {half}: one column header without the other")
        return []

    split = COLUMN_SPLIT[half]
    lo = 0.0 if half == "left" else HALF_SPLIT

    end = HALF_SPLIT if half == "left" else 1e9
    below = [
        b
        for b in blocks
        if b["yMin"] > former_header["yMin"] + BASELINE_TOLERANCE and not _is_furniture(b)
    ]
    # EVERY block inside the column, not the first: poppler splits a column
    # wherever the print leaves a gap, so pages 4-11 carry the former sections
    # in two or three blocks. Taking only the topmost silently dropped 464 of
    # the table's 864 former sections — and hid it, because the values under
    # the gap were filtered out by the same y-window and never went unmatched.
    # Prose that follows the table (page 12's ENACTING CLAUSES) is set to the
    # full width of the half, so it crosses the column split and is excluded
    # by ``xMax < split`` rather than by any guess about its wording.
    former_blocks = [b for b in below if lo <= b["xMin"] and b["xMax"] < split]
    if not former_blocks:
        raise SystemExit(f"page {page} {half}: a column header with no column under it")
    value_blocks = [b for b in below if split <= b["xMin"] and b["xMax"] < end]

    body_lines = merge_baselines([line for b in former_blocks for line in b["lines"]])
    value_lines = merge_baselines([line for b in value_blocks for line in b["lines"]])

    for line in body_lines:
        if line["xMax"] >= split:
            raise SystemExit(f"page {page} {half}: former-column line crosses the split: {line['text']!r}")

    rows = [
        {
            "page": page,
            "half": half,
            "x": line["xMin"],
            "y": line["yMin"],
            "former_line": line["text"],
            "new": None,
            "new_x": None,
        }
        for line in body_lines
    ]

    # A printed value can wrap too — 305(h) restates as five spans and needs
    # two lines for them. A value line with no former line at its baseline
    # belongs to the value above it, and must be indented past it to say so.
    last = None
    for value in value_lines:
        at = [row for row in rows if abs(row["y"] - value["yMin"]) < BASELINE_TOLERANCE]
        if len(at) > 1:
            raise SystemExit(f"page {page} {half}: two former lines on one baseline: {[r['former_line'] for r in at]}")
        if at:
            if at[0]["new"] is not None:
                raise SystemExit(f"page {page} {half}: two values on one baseline: {at[0]['former_line']!r}")
            at[0]["new"], at[0]["new_x"] = value["text"], value["xMin"]
            last = at[0]
            continue
        if last is None or value["xMin"] <= last["new_x"] + 1.0:
            raise SystemExit(f"page {page} {half}: an unattached value at y={value['yMin']}: {value['text']!r}")
        last["new"] = f"{last['new']} {value['text']}"
    return rows


_LEADER = re.compile(r"\s*\.(?:\s?\.)+\s*$")


def entries(rows: list[dict]) -> list[dict]:
    """Fold continuation lines into the entry above them.

    An entry line carries a value; a continuation line does not and is indented
    past its entry's left edge. A line with neither property is a defect and
    raises: the print has no third kind.
    """

    out: list[dict] = []
    for row in rows:
        text = _LEADER.sub("", row["former_line"])
        if row["new"] is not None and (not out or row["x"] <= out[-1]["x"] + 1.0):
            out.append(
                {
                    "page": row["page"],
                    "half": row["half"],
                    "y": row["y"],
                    "x": row["x"],
                    "former_text": text,
                    "new_text": row["new"],
                }
            )
            continue
        if not out or row["x"] <= out[-1]["x"] + 1.0:
            raise SystemExit(f"page {row['page']} {row['half']}: a line that is neither entry nor continuation: {row!r}")
        prev = out[-1]["former_text"]
        if row["new"] is not None:
            raise SystemExit(f"page {row['page']} {row['half']}: an indented line carrying a value: {row!r}")
        out[-1]["former_text"] = prev[:-1] + text if prev.endswith("-") else f"{prev} {text}"
    for entry in out:
        if not entry["former_text"][:1].isdigit():
            raise SystemExit(f"an entry that does not open with a section number: {entry!r}")
    return out


# --------------------------------------------------------------------------- #
# Parsing the two printed fields into the columns a lookup needs.

#: A section token: digits, then an optional letter tail (``1601b``, ``2517a``).
#: No hyphenated tail: the former numbering has none, so every ``-`` in a
#: former field is a span, and admitting ``1601-1601b`` as one token would
#: silently swallow the spans this table is mostly made of.
_SECTION = r"\d+[a-z]?"
#: A subsection path glued to the section with no space: ``(a)(1)``, ``(2)(A)``.
_SUBPATH = r"(?:\([0-9a-zA-Z]{1,4}\))+"
_ENTRY_HEAD = re.compile(rf"^({_SECTION})({_SUBPATH})?")
_LETTER_TAIL = re.compile(r"^(\d+)([a-z])$")


def _expand_range(lo: str, hi: str) -> list[str]:
    """``1601``-``1601b`` -> 1601, 1601a, 1601b; ``2616``-``2618`` -> 2616-2618.

    Only the two shapes the table actually prints. Anything else keeps the
    endpoints and says so by returning them alone, because inventing the
    members of a span nobody printed is how a table becomes a guess.
    """

    if lo.isdigit() and hi.isdigit() and 0 <= int(hi) - int(lo) <= 60:
        return [str(n) for n in range(int(lo), int(hi) + 1)]
    lm, hm = _LETTER_TAIL.match(lo), _LETTER_TAIL.match(hi)
    if lo.isdigit() and hm and hm.group(1) == lo:
        return [lo] + [f"{lo}{chr(c)}" for c in range(ord("a"), ord(hm.group(2)) + 1)]
    if lm and hm and lm.group(1) == hm.group(1) and lm.group(2) <= hm.group(2):
        return [f"{lm.group(1)}{chr(c)}" for c in range(ord(lm.group(2)), ord(hm.group(2)) + 1)]
    return [lo, hi]


#: A parenthesised group is an *address* — a subsection — only when it holds a
#: short alphanumeric label and nothing else. Everything longer, everything
#: with a space, and everything with a group nested inside it is the table's
#: prose about which words of the former section moved: ``(1st sentence)``,
#: ``(less (c), (g), and (h))``, ``(related to 1471(c))``. Prose is dropped
#: from the parsed address and kept whole in ``former_text``.
_ADDRESS = re.compile(r"^[0-9A-Za-z]{1,4}$")


def _strip_prose(text: str) -> str:
    """Leave only the section-and-subsection addresses an entry names."""

    out: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch == "[":
            if depth == 0:
                out.append(text[start:i])
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                out.append(" ")
                start = i + 1
        elif ch == "(":
            if depth == 0:
                out.append(text[start:i])
                start = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                group = text[start + 1 : i]
                out.append(text[start : i + 1] if _ADDRESS.match(group) else " ")
                start = i + 1
    if depth != 0:
        raise SystemExit(f"unbalanced parentheses in a former field: {text!r}")
    out.append(text[start:])
    return re.sub(r"\s+", " ", "".join(out)).strip().strip(".").strip()


#: The only two things a former field says beyond an address: that the entry
#: disposes of the section's *notes* rather than its text.
FORMER_NOTES = (None, "note", "notes")

_GROUP = re.compile(r"\([0-9A-Za-z]{1,4}\)")
_SUB_SPAN = re.compile(rf"-{_SUBPATH}")


def _shape(group: str) -> str:
    label = group[1:-1]
    if label.isdigit():
        return "digit"
    if label.isalpha() and label.islower():
        return "lower"
    if label.isalpha() and label.isupper():
        return "upper"
    return "mixed"


def _inherit(previous: str | None, groups: list[str]) -> str:
    """Where a bare ``(x)`` after a comma sits in the path before it.

    ``16(3)(c), (g)`` is 16(3)(c) and 16(3)**(g)**, not 16(g);
    ``1602(a)(1), (2)(A), (B)`` is (a)(1), (a)(2)(A), (a)(2)(B);
    but ``1553(a)(8)-(10), (b)`` is (a)(8..10) and plain **(b)**.

    The rule the print follows: a bare group continues at the level of the
    *deepest* component of the previous path with the same label shape — a
    letter continues a letter, a number a number, a capital a capital. That
    also settles ``(d)(4)(A)(i), (ii)``, where a lowercase roman numeral at
    level four continues level four rather than reading as a subsection (i).
    """

    if not previous:
        return "".join(groups)
    prior = _GROUP.findall(previous)
    want = _shape(groups[0])
    for i in range(len(prior) - 1, -1, -1):
        if _shape(prior[i]) == want:
            return "".join(prior[:i]) + "".join(groups)
    return "".join(groups)


def parse_former(text: str) -> tuple[list[dict], list[str]]:
    """Every ``(section, subsection)`` an entry's former field names.

    ``1421(b) (last sentence), (c)`` -> 1421(b) and 1421(c);
    ``1427 (last sentence), 1428`` -> 1427 and 1428;
    ``1601-1601b`` -> 1601, 1601a, 1601b;
    ``1553(a)(8)-(10), (b)`` -> 1553(a)(8), 1553(a)(9), 1553(a)(10), 1553(b).

    The descriptive parentheticals ("1st sentence", "related to ...") are NOT
    parsed: they stay whole in ``former_text``. What is parsed is only what a
    citation can carry — the section number and the subsection path.

    Returns the addresses and, beside them, every comma-piece that named no
    address, so a caller can hold that list to a known length instead of
    letting a parse failure look like a row the table never printed.
    """

    out: list[dict] = []
    skipped: list[str] = []
    section: str | None = None
    previous_sub: str | None = None
    for part in [p.strip() for p in _strip_prose(text).split(",") if p.strip()]:
        for piece in _split_range(part):
            head = _ENTRY_HEAD.match(piece)
            rest = piece[head.end() :].strip() if head else piece
            if head and rest in ("", "note", "notes"):
                section, previous_sub = head.group(1), head.group(2)
                out.append({"section": section, "subsection": head.group(2), "note": rest or None})
            elif head and head.group(2) and _SUB_SPAN.fullmatch(rest):
                # A span across subsection levels — (e)(5)-(7)(A) — that no
                # rule can enumerate without inventing the members. Kept whole
                # and printed as it stands; its first group still answers a
                # subsection question, which is all a citation ever carries.
                section = head.group(1)
                previous_sub = f"{head.group(2)}{rest}"
                out.append({"section": section, "subsection": previous_sub, "note": None})
            elif not head and piece.startswith("(") and section is not None:
                groups = _GROUP.findall(piece)
                path = _inherit(previous_sub, groups) if _GROUP.fullmatch(piece) or "".join(groups) == piece else piece
                out.append({"section": section, "subsection": path, "note": None})
                previous_sub = path
            else:
                skipped.append(piece)
    return out, skipped


def _split_range(part: str) -> list[str]:
    """Expand ``1601-1601b`` / ``(a)(8)-(10)`` in place; leave anything else."""

    if "-" not in part:
        return [part]
    lo, _, hi = part.partition("-")
    lo, hi = lo.strip(), hi.strip()
    if re.fullmatch(_SECTION, lo) and re.fullmatch(_SECTION, hi):
        return _expand_range(lo, hi)
    # 2122(b)-2124: a span of whole sections that starts mid-section. The
    # subsection rides on the first member only, which is what the print says.
    across = re.fullmatch(rf"({_SECTION})({_SUBPATH})", lo)
    if across and re.fullmatch(_SECTION, hi):
        members = _expand_range(across.group(1), hi)
        return [f"{members[0]}{across.group(2)}", *members[1:]]
    # 1155-1157(b): the mirror, ending mid-section.
    across = re.fullmatch(rf"({_SECTION})({_SUBPATH})", hi)
    if across and re.fullmatch(_SECTION, lo):
        members = _expand_range(lo, across.group(1))
        return [*members[:-1], f"{members[-1]}{across.group(2)}"]
    lom, him = re.fullmatch(rf"({_SECTION})?({_SUBPATH})", lo), re.fullmatch(r"(\([0-9a-zA-Z]{1,4}\))", hi)
    if lom and him:
        head = lom.group(1) or ""
        stem = lom.group(2)[: stem_end] if (stem_end := lom.group(2).rfind("(")) >= 0 else ""
        last = lom.group(2)[stem_end + 1 : -1]
        end = him.group(1)[1:-1]
        members = _range_members(last, end)
        if members:
            return [f"{head}{stem}({m})" for m in members]
    return [part]


def _range_members(lo: str, hi: str) -> list[str] | None:
    if lo.isdigit() and hi.isdigit() and int(lo) <= int(hi):
        return [str(n) for n in range(int(lo), int(hi) + 1)]
    if len(lo) == 1 and len(hi) == 1 and lo.isalpha() and hi.isalpha() and lo <= hi:
        return [chr(c) for c in range(ord(lo), ord(hi) + 1)]
    return None


#: What the printed value says happened, beyond naming a successor.
STATUSES = ("restated", "restated-as-note", "repealed", "eliminated", "see-reference")

_TITLE_REF = re.compile(r"^T\.\s*(\d+)\s*§+\s*(.*)$")
#: ``10702 (See also 10701(a))`` — a balanced aside, nested parens and all.
_SEE_ALSO = re.compile(r"\(See[^()]*(?:\([^()]*\)[^()]*)*\)", re.I)


def parse_new(text: str) -> list[dict]:
    """Every successor a printed value names, with the status it carries.

    ``Rep.`` -> repealed, no successor. ``Elim.`` -> eliminated, no successor.
    ``T. 42 § 6362`` -> title 42 section 6362. ``40103 note`` -> section 40103,
    as a note. ``44716, 44717, 44722`` -> three successors, all returned.
    ``(See ...)`` -> a pointer the table gives instead of a successor.
    """

    value = text.strip().rstrip(".") if text.strip() in ("Rep.", "Elim.") else text.strip()
    if value == "Rep":
        return [{"title": None, "section": None, "subsection": None, "status": "repealed"}]
    if value == "Elim":
        return [{"title": None, "section": None, "subsection": None, "status": "eliminated"}]
    if _SEE_ALSO.fullmatch(value):
        return [{"title": None, "section": None, "subsection": None, "status": "see-reference"}]

    out: list[dict] = []
    #: ``T. 50 §§ 151-154, 156, 157`` states its title once and then goes on
    #: listing sections of it, so the title carries across the commas until
    #: another ``T. NN`` replaces it.
    title = 49
    for chunk in [c.strip() for c in re.split(r"[;,]", value) if c.strip()]:
        chunk = _SEE_ALSO.sub("", chunk).strip()
        ref = _TITLE_REF.match(chunk)
        if ref:
            title, chunk = int(ref.group(1)), ref.group(2).strip()
        status = "restated"
        if chunk.endswith(" note"):
            chunk, status = chunk[: -len(" note")].strip(), "restated-as-note"
        if not chunk:
            continue
        sub = None
        pinpoint = re.fullmatch(rf"({_SECTION})({_SUBPATH})", chunk)
        if pinpoint:
            chunk, sub = pinpoint.group(1), pinpoint.group(2)
        lo, _, hi = chunk.partition("-")
        if hi and re.fullmatch(_SECTION, lo.strip()) and re.fullmatch(_SECTION, hi.strip()):
            for member in _expand_range(lo.strip(), hi.strip()):
                out.append({"title": title, "section": member, "subsection": None, "status": status})
            continue
        out.append({"title": title, "section": chunk, "subsection": sub, "status": status})
    if not out:
        raise SystemExit(f"a printed value that names nothing: {text!r}")
    return out


def build(pdf: Path) -> list[dict]:
    """The whole derived table: one record per (former section x successor)."""

    printed: list[dict] = []
    for page in TABLE_PAGES:
        for half in ("left", "right"):
            printed.extend(entries(table_rows(pdf, page, half)))

    out: list[dict] = []
    prose: list[tuple[str, str]] = []
    for entry in printed:
        formers, skipped = parse_former(entry["former_text"])
        news = parse_new(entry["new_text"])
        prose.extend((entry["former_text"], piece) for piece in skipped)
        if not formers:
            raise SystemExit(f"an entry naming no former section: {entry!r}")
        for former in formers:
            for new in news:
                out.append(
                    {
                        "former_title": 49,
                        "former_section": former["section"],
                        "former_subsection": former["subsection"],
                        "former_note": former["note"],
                        "new_title": new["title"],
                        "new_section": new["section"],
                        "new_subsection": new["subsection"],
                        "status": new["status"],
                        "former_text": entry["former_text"],
                        "new_text": entry["new_text"],
                        "page": entry["page"],
                        "column": entry["half"],
                    }
                )

    #: The one comma-piece in the whole table that names no address: the
    #: second half of ``20(11) ... , 2d sentence (less 1st-5th provisos)``,
    #: which is prose about the row's first half. Frozen so a parse that
    #: starts dropping addresses fails here instead of shrinking quietly.
    if prose != [
        (
            "20(11) (1st sentence 2d proviso related to released value), "
            "2d sentence (less 1st-5th provisos).",
            "2d sentence",
        )
    ]:
        raise SystemExit(f"former fields whose pieces named no address: {prose!r}")
    for row in out:
        if not re.fullmatch(_SECTION, row["former_section"] or ""):
            raise SystemExit(f"a parsed former section that is not a section token: {row!r}")
        if row["former_note"] not in FORMER_NOTES:
            raise SystemExit(f"a former field saying something new: {row!r}")
        if row["status"] not in STATUSES:
            raise SystemExit(f"an undeclared status: {row!r}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--text", type=Path, default=None, help="the printed entries, in print order, for reading against the pages")
    args = ap.parse_args()

    verify_source(args.pdf)
    rows = build(args.pdf)

    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema(
        [
            ("former_title", pa.int32()),
            ("former_section", pa.string()),
            ("former_subsection", pa.string()),
            ("former_note", pa.string()),
            ("new_title", pa.int32()),
            ("new_section", pa.string()),
            ("new_subsection", pa.string()),
            ("status", pa.string()),
            ("former_text", pa.string()),
            ("new_text", pa.string()),
            ("page", pa.int32()),
            ("column", pa.string()),
        ]
    )
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, args.out, compression="zstd")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    if args.text:
        seen: dict[tuple, None] = {}
        for row in rows:
            seen.setdefault((row["page"], row["column"], row["former_text"], row["new_text"]), None)
        args.text.write_text(
            "".join(f"{page:>3} {column:<5} {former}\t{new}\n" for page, column, former, new in seen) or "\n"
        )

    printed_entries = len({(r["page"], r["column"], r["former_text"], r["new_text"]) for r in rows})
    print(f"printed entries : {printed_entries}")
    print(f"emitted rows    : {len(rows)}")
    print(f"former sections : {len({r['former_section'] for r in rows if r['former_section']})}")
    print(f"statuses        : {sorted({r['status'] for r in rows})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
