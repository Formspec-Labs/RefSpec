"""Cut the Title 31 (1982) and Title 46 (1983-2006) disposition tables out of GovInfo PDFs.

Sources (pinned by sha256 and byte length below; kept outside git in local cache):
- Title 31 (Pub. L. 97-258, 1982):
  https://www.govinfo.gov/content/pkg/USCODE-1994-title31/pdf/USCODE-1994-title31.pdf
  Pages 1-6 carry "TABLE SHOWING DISPOSITION OF ALL SECTIONS OF FORMER TITLE 31".
- Title 46 (Pub. L. 98-89 .. Pub. L. 109-304, 1983-2006):
  https://www.govinfo.gov/content/pkg/USCODE-2006-title46/pdf/USCODE-2006-title46.pdf
  Pages 1-9 carry "Disposition Table (Showing Disposition of Former Sections of
  Title 46 or Title 46 Appendix)".

Both volumes come from OLRC's ACOMP.exe / AFPL Ghostscript 8.14 typesetting
pipeline, identical in column structure to USCODE-1994-title49.pdf: two table
blocks side by side per page, each two columns ("Former Sections" | "New
Sections"), dot leaders joining former descriptions to new sections, wrapped
continuations indented with no value on their baseline.

Uses ``pdftotext -bbox-layout`` for geometric column separation and baseline
matching (see ``../usc-disposition-tables-2026-08-23/README.md`` on why
``-layout`` fails on side-by-side blocks and justified continuations). Extends
the 2026-08-23 parser cleanly for patterns absent from Title 49's table:
- hyphenated former section tokens (``52-1``, ``82a-1``, ``725q-1a``,
  ``404-1``, ``883-1``, ``1126-1``, ``1295c-1``), distinguished unambiguously
  from ascending section spans because every hyphenated section suffix is
  strictly smaller than its leading section number;
- ``to`` ranges in Title 31 (``46a to 48``, ``317d to 317e-1``, ``488b to
  488b-2``);
- ``note prec.`` in Title 46 (``3 note prec.``);
- mixed section ranges such as ``242-243a``, ``486a to 488``, ``1183-1185a``,
  expanding only the unambiguous integer/same-stem members between endpoints
  without inventing intermediate lettered sections;
- multi-subsection continuations and partial-repeal values in Title 46's new
  column (``8501(c), (e)``, ``3306(a)(5), Rep. in part``, ``Rep. See ...``,
  ``Sec. 2(f) of Pub. L. 98-89``).

Every structural assumption raises rather than dropping a row. Emits the exact
12-column Parquet schema that ``refspec.registry.usc_disposition_tables`` reads.

Run:
    python3 extract_disposition_tables.py --title 31 <pdf> <out.parquet> [--text <out.txt>]
    python3 extract_disposition_tables.py --title 46 <pdf> <out.parquet> [--text <out.txt>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

NS = "{http://www.w3.org/1999/xhtml}"

#: Poppler version pinned so column segmentation is reproducible.
PDFTOTEXT_VERSION = "pdftotext version 26.10.0"

#: Geometric splits common to both OLRC ACOMP.exe volumes (612 x 792 pt letter):
#: Left block: former xMax <= 191.4, new xMin = 197.5 -> midpoint 194.5.
#: Right block: former xMax <= 410.0, new xMin = 416.5 -> midpoint 413.5.
HALF_SPLIT = 306.0
COLUMN_SPLIT = {"left": 194.5, "right": 413.5}
BASELINE_TOLERANCE = 1.5

_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))
_LEADER = re.compile(r"\s*\.(?:\s?\.)+\s*$")


@dataclass(frozen=True)
class SourceSpec:
    former_title: int
    source_url: str
    source_sha256: str
    source_bytes: int
    table_pages: range
    furniture_pattern: re.Pattern[str]


SOURCE_SPECS: dict[int, SourceSpec] = {
    31: SourceSpec(
        former_title=31,
        source_url="https://www.govinfo.gov/content/pkg/USCODE-1994-title31/pdf/USCODE-1994-title31.pdf",
        source_sha256="3b319dc182915b409d01c26d5fe46326e0416f5e725aa556738d17ba60340f0a",
        source_bytes=2_088_477,
        table_pages=range(1, 7),
        furniture_pattern=re.compile(
            r"^(Page \d+|TITLE 31-MONEY AND FINANCE|T ABLE S HOWING.*|F ORMER T ITLE 31.*)$"
        ),
    ),
    46: SourceSpec(
        former_title=46,
        source_url="https://www.govinfo.gov/content/pkg/USCODE-2006-title46/pdf/USCODE-2006-title46.pdf",
        source_sha256="6bda1578ab30e947d3f7e746bacd53048a197ef80c946f0f7300276c97a5887d",
        source_bytes=2_449_872,
        table_pages=range(1, 10),
        furniture_pattern=re.compile(
            r"^(Page \d+|TITLE 46-SHIPPING|Disposition Table.*|\(Showing Disposition.*|Appendix\))$"
        ),
    ),
}


def _run(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def verify_source(pdf: Path, spec: SourceSpec) -> None:
    """Refuse to read a PDF that is not the pinned one, or a drifted poppler."""

    proc = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True, check=True)
    version = proc.stdout + proc.stderr
    if PDFTOTEXT_VERSION not in version:
        raise SystemExit(f"pdftotext drifted: expected {PDFTOTEXT_VERSION!r}, got {version.strip()!r}")
    raw = pdf.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != spec.source_bytes or digest != spec.source_sha256:
        raise SystemExit(
            f"source drifted: expected sha256:{spec.source_sha256} ({spec.source_bytes} bytes), "
            f"observed sha256:{digest} ({len(raw)} bytes) — {spec.source_url}"
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
    """One record per printed baseline, joining poppler-split fragments left to right."""

    merged: list[dict] = []
    for line in sorted(lines, key=lambda ln: (ln["yMin"], ln["xMin"])):
        if merged and abs(merged[-1]["yMin"] - line["yMin"]) < BASELINE_TOLERANCE:
            merged[-1]["text"] = f"{merged[-1]['text']} {line['text']}"
            merged[-1]["xMax"] = max(merged[-1]["xMax"], line["xMax"])
            continue
        merged.append(dict(line))
    return merged


def _is_furniture(block: dict, furniture_re: re.Pattern[str]) -> bool:
    return all(furniture_re.match(line["text"]) for line in block["lines"])


def _header(blocks: list[dict], label: str, half: str) -> dict | None:
    """The two-line column header whose second line is ``<label> Sections``."""

    lo, hi = (0.0, HALF_SPLIT) if half == "left" else (HALF_SPLIT, 1e9)
    found = [
        b
        for b in blocks
        if lo <= b["xMin"] < hi and len(b["lines"]) == 2 and b["lines"][1]["text"] == f"{label} Sections"
    ]
    if len(found) > 1:
        raise SystemExit(f"more than one {label} header in the {half} half")
    return found[0] if found else None


def table_rows(pdf: Path, page: int, half: str, spec: SourceSpec) -> list[dict]:
    """The printed rows of one table block: former line + value at its baseline."""

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
        if b["yMin"] > former_header["yMin"] + BASELINE_TOLERANCE and not _is_furniture(b, spec.furniture_pattern)
    ]
    # Full-width prose following the table (ENACTING CLAUSE(S) on the final page)
    # crosses the column split; stop reading that half at the first such block.
    crossing = [b for b in below if lo <= b["xMin"] < split and b["xMax"] >= split and b["xMax"] < end]
    y_cutoff = min((b["yMin"] for b in crossing), default=1e9)
    below = [b for b in below if b["yMin"] < y_cutoff]

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


def entries(rows: list[dict]) -> list[dict]:
    """Fold indented continuation lines into the entry above them."""

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
# Parsing former and new fields

_BASE_SECTION = r"\d+[a-z]?"
_HYPHEN_SECTION = r"\d+[a-z]?-\d+[a-z]?"
_SUBPATH = r"(?:\([0-9a-zA-Z]{1,4}\))+"
_GROUP = re.compile(r"\([0-9A-Za-z]{1,4}\)")
_SUB_SPAN = re.compile(rf"-{_SUBPATH}")
_ADDRESS = re.compile(r"^[0-9A-Za-z]{1,4}$")
_LETTER_TAIL = re.compile(r"^(\d+)([a-z])$")
_HYPHEN_PARTS = re.compile(r"^(\d+)[a-z]?-(\d+)[a-z]?$")

FORMER_NOTES = (None, "note", "notes", "note prec.")
STATUSES = ("restated", "restated-as-note", "repealed", "eliminated", "see-reference")


def _is_hyphen_section(token: str) -> bool:
    """True for single hyphenated Code sections (``52-1``, ``82a-1``, ``725q-1a``, ``404-1``).

    Every hyphenated section suffix in Title 31 and Title 46 carries a trailing
    numeric suffix strictly smaller than its leading section number, whereas
    every ascending section range ``lo-hi`` has ``hi >= lo``.
    """

    match = _HYPHEN_PARTS.fullmatch(token)
    return bool(match and int(match.group(2)) < int(match.group(1)))


def _is_section(token: str) -> bool:
    return bool(re.fullmatch(_BASE_SECTION, token)) or _is_hyphen_section(token)


def _match_entry_head(piece: str) -> re.Match[str] | None:
    hyphen = re.match(rf"^({_HYPHEN_SECTION})({_SUBPATH})?", piece)
    if hyphen and _is_hyphen_section(hyphen.group(1)):
        return hyphen
    return re.match(rf"^({_BASE_SECTION})({_SUBPATH})?", piece)


def _expand_range(lo: str, hi: str) -> list[str]:
    """Expand printed section spans without inventing intermediate lettered sections.

    Supported shapes:
    - ``N``-``M`` (integers, diff <= 60): ``N .. M``
    - ``N``-``N<letter>`` (same number): ``N, Na .. N<letter>``
    - ``N<l1>``-``N<l2>`` (same number): ``N<l1> .. N<l2>``
    - ``base``-``base-K`` (same stem, K <= 20): ``base, base-1 .. base-K``
    - ``N``-``M<letter>`` (N < M <= N+60): integers ``N .. M`` + ``Ma .. M<letter>``
    - ``N<letter>``-``M`` (N < M <= N+60): ``lo`` + integers ``(N+1) .. M``
    - ``N<l1>``-``N<l2>-K`` (same number, l1 <= l2, K <= 20): ``N<l1> .. N<l2>`` + ``N<l2>-1 .. -K``
    - ``N``-``M<letter>-K`` (N < M <= N+60, K <= 20): ``N .. M`` + ``Ma .. M<letter>`` + ``M<letter>-1 .. -K``
    """

    if lo.isdigit() and hi.isdigit() and 0 <= int(hi) - int(lo) <= 60:
        return [str(n) for n in range(int(lo), int(hi) + 1)]
    lm, hm = _LETTER_TAIL.match(lo), _LETTER_TAIL.match(hi)
    if lo.isdigit() and hm and hm.group(1) == lo:
        return [lo] + [f"{lo}{chr(c)}" for c in range(ord("a"), ord(hm.group(2)) + 1)]
    if lm and hm and lm.group(1) == hm.group(1) and lm.group(2) <= hm.group(2):
        return [f"{lm.group(1)}{chr(c)}" for c in range(ord(lm.group(2)), ord(hm.group(2)) + 1)]
    hi_hyph = re.fullmatch(r"(\d+)([a-z]?)-(\d+)", hi)
    if hi_hyph and f"{hi_hyph.group(1)}{hi_hyph.group(2)}" == lo and 1 <= int(hi_hyph.group(3)) <= 20:
        return [lo] + [f"{lo}-{k}" for k in range(1, int(hi_hyph.group(3)) + 1)]
    # Mixed integer -> higher integer+letter (e.g. 242-243a, 561-563a, 812-817c, 1183-1185a)
    if lo.isdigit() and hm and 0 < int(hm.group(1)) - int(lo) <= 60:
        hi_num = int(hm.group(1))
        return [str(n) for n in range(int(lo), hi_num + 1)] + [
            f"{hi_num}{chr(c)}" for c in range(ord("a"), ord(hm.group(2)) + 1)
        ]
    # Mixed integer+letter -> higher integer (e.g. 46a to 48, 486a to 488, 712b to 716, 91a-96)
    if lm and hi.isdigit() and 0 < int(hi) - int(lm.group(1)) <= 60:
        return [lo] + [str(n) for n in range(int(lm.group(1)) + 1, int(hi) + 1)]
    # Same-number letter -> letter-suffix (e.g. 317d to 317e-1)
    if lm and hi_hyph and hi_hyph.group(1) == lm.group(1) and hi_hyph.group(2) and lm.group(2) <= hi_hyph.group(2):
        stem = f"{hi_hyph.group(1)}{hi_hyph.group(2)}"
        return [f"{lm.group(1)}{chr(c)}" for c in range(ord(lm.group(2)), ord(hi_hyph.group(2)) + 1)] + [
            f"{stem}-{k}" for k in range(1, int(hi_hyph.group(3)) + 1)
        ]
    # Integer -> higher integer+letter-suffix (e.g. 376-382a-1)
    if lo.isdigit() and hi_hyph and hi_hyph.group(2) and 0 < int(hi_hyph.group(1)) - int(lo) <= 60:
        hi_num = int(hi_hyph.group(1))
        stem = f"{hi_num}{hi_hyph.group(2)}"
        return (
            [str(n) for n in range(int(lo), hi_num + 1)]
            + [f"{hi_num}{chr(c)}" for c in range(ord("a"), ord(hi_hyph.group(2)) + 1)]
            + [f"{stem}-{k}" for k in range(1, int(hi_hyph.group(3)) + 1)]
        )
    return [lo, hi]


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
    cleaned = re.sub(r"\s+", " ", "".join(out)).strip().strip(".").strip()
    # Collapse space left when prose sat before a subsection dash: "11(g) -(i)" -> "11(g)-(i)"
    return re.sub(r"\)\s*-\s*\(", ")-(", cleaned)


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
    if not previous:
        return "".join(groups)
    prior = _GROUP.findall(previous)
    want = _shape(groups[0])
    for i in range(len(prior) - 1, -1, -1):
        if _shape(prior[i]) == want:
            return "".join(prior[:i]) + "".join(groups)
    return "".join(groups)


def _range_members(lo: str, hi: str) -> list[str] | None:
    if lo.isdigit() and hi.isdigit() and int(lo) <= int(hi):
        return [str(n) for n in range(int(lo), int(hi) + 1)]
    if len(lo) == 1 and len(hi) == 1 and lo.isalpha() and hi.isalpha() and lo <= hi:
        return [chr(c) for c in range(ord(lo), ord(hi) + 1)]
    return None


def _split_range(part: str) -> list[str]:
    """Expand section ranges (``-`` or ``to``) and same-level subsection spans."""

    if " to " in part:
        lo, _, hi = part.partition(" to ")
        lo, hi = lo.strip(), hi.strip()
        if _is_section(lo) and _is_section(hi):
            return _expand_range(lo, hi)
        return [part]
    if "-" not in part:
        return [part]
    # Single hyphenated section with optional subsection / subsection range (e.g. 52-3(a)-(d), 404-1(6))
    hyph = re.match(rf"^({_HYPHEN_SECTION})(.*)$", part)
    if hyph and _is_hyphen_section(hyph.group(1)):
        sec, rest = hyph.group(1), hyph.group(2)
        if not rest:
            return [sec]
        sub_span = re.fullmatch(rf"({_SUBPATH})-(\([0-9a-zA-Z]{{1,4}}\))", rest)
        if sub_span:
            subpath, hi_group = sub_span.group(1), sub_span.group(2)
            stem_end = subpath.rfind("(")
            stem, last = subpath[:stem_end], subpath[stem_end + 1 : -1]
            members = _range_members(last, hi_group[1:-1])
            if members:
                return [f"{sec}{stem}({m})" for m in members]
        return [part]
    lo, _, hi = part.partition("-")
    lo, hi = lo.strip(), hi.strip()
    if _is_section(lo) and _is_section(hi):
        return _expand_range(lo, hi)
    # Subsection range on a base section or bare subsection path
    lom = re.fullmatch(rf"({_BASE_SECTION})?({_SUBPATH})", lo)
    him = re.fullmatch(r"(\([0-9a-zA-Z]{1,4}\))", hi)
    if lom and him:
        head = lom.group(1) or ""
        stem_end = lom.group(2).rfind("(")
        stem, last = lom.group(2)[:stem_end], lom.group(2)[stem_end + 1 : -1]
        members = _range_members(last, him.group(1)[1:-1])
        if members:
            return [f"{head}{stem}({m})" for m in members]
    return [part]


def parse_former(text: str) -> tuple[list[dict], list[str]]:
    """Every ``(section, subsection, note)`` an entry's former field names."""

    out: list[dict] = []
    skipped: list[str] = []
    section: str | None = None
    previous_sub: str | None = None
    for part in [p.strip() for p in _strip_prose(text).split(",") if p.strip()]:
        for piece in _split_range(part):
            head = _match_entry_head(piece)
            rest = piece[head.end() :].strip() if head else piece
            if head and rest in ("", "note", "notes", "note prec", "note prec."):
                section, previous_sub = head.group(1), head.group(2)
                note = "note prec." if rest.startswith("note prec") else (rest or None)
                out.append({"section": section, "subsection": head.group(2), "note": note})
            elif head and head.group(2) and _SUB_SPAN.fullmatch(rest):
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


_TITLE_REF = re.compile(r"^T\.\s*(\d+)\s*§+\s*(.*)$")
_SEE_ALSO = re.compile(r"\(See[^()]*(?:\([^()]*\)[^()]*)*\)", re.IGNORECASE)


def parse_new(text: str, default_title: int) -> list[dict]:
    """Every successor a printed value names, with its status."""

    raw = text.strip()
    if raw in ("Rep.", "Rep"):
        return [{"title": None, "section": None, "subsection": None, "status": "repealed"}]
    if raw in ("Elim.", "Elim"):
        return [{"title": None, "section": None, "subsection": None, "status": "eliminated"}]
    if raw.startswith("Rep. See "):
        return [{"title": None, "section": None, "subsection": None, "status": "repealed"}]
    if _SEE_ALSO.fullmatch(raw) or raw.startswith("Sec. "):
        return [{"title": None, "section": None, "subsection": None, "status": "see-reference"}]

    out: list[dict] = []
    title = default_title
    last_section: str | None = None
    last_sub: str | None = None
    for chunk in [c.strip() for c in re.split(r"[;,]", raw) if c.strip()]:
        chunk = _SEE_ALSO.sub("", chunk).strip()
        if not chunk:
            continue
        if chunk in ("Rep.", "Rep. in part"):
            out.append({"title": None, "section": None, "subsection": None, "status": "repealed"})
            continue
        ref = _TITLE_REF.match(chunk)
        if ref:
            title, chunk = int(ref.group(1)), ref.group(2).strip()
            last_section = None
            last_sub = None
        status = "restated"
        if chunk.endswith(" note"):
            chunk, status = chunk[: -len(" note")].strip(), "restated-as-note"
        if not chunk:
            continue
        if chunk.startswith("(") and last_section is not None:
            if "-" in chunk:
                out.append({"title": title, "section": last_section, "subsection": chunk, "status": status})
            else:
                groups = _GROUP.findall(chunk)
                path = _inherit(last_sub, groups) if "".join(groups) == chunk else chunk
                out.append({"title": title, "section": last_section, "subsection": path, "status": status})
                last_sub = path
            continue
        matched = _match_entry_head(chunk)
        if matched:
            sec, sub = matched.group(1), matched.group(2)
            rest = chunk[matched.end() :].strip()
            if rest == "":
                out.append({"title": title, "section": sec, "subsection": sub, "status": status})
                last_section, last_sub = sec, sub
                continue
            if sub is not None and _SUB_SPAN.fullmatch(rest):
                full_sub = f"{sub}{rest}"
                out.append({"title": title, "section": sec, "subsection": full_sub, "status": status})
                last_section, last_sub = sec, full_sub
                continue
        lo, _, hi = chunk.partition("-")
        if hi and _is_section(lo.strip()) and _is_section(hi.strip()):
            for member in _expand_range(lo.strip(), hi.strip()):
                out.append({"title": title, "section": member, "subsection": None, "status": status})
            last_section, last_sub = None, None
            continue
        raise SystemExit(f"unparsed new-section chunk {chunk!r} in {text!r}")
    if not out:
        raise SystemExit(f"a printed value that names nothing: {text!r}")
    return out


#: Printed entries where both sides are equal-length ranges paired 1-to-1
#: respectively (verified from primary codification notes), rather than a
#: Cartesian product where every former section maps to every successor.
RESPECTIVE_RANGE_ENTRIES: dict[tuple[int, str, str], str] = {
    (46, "454-457", "T. 33 §§ 1233-1236"): (
        "Act of Apr. 28, 1908, ch. 151, §§ 1-4, 35 Stat. 69 (1994usc33.htm Codification notes: "
        "46:454 -> 33:1233, 46:455 -> 33:1234, 46:456 -> 33:1235, 46:457 -> 33:1236)"
    ),
}

#: Independently attested alphanumeric former sections falling strictly inside a
#: printed range entry (verified from the volume's own Historical and Revision
#: Notes or OLRC 1994-2005 annual ``usc46a.htm``). ``_expand_range`` never
#: invents unattested intermediate lettered/hyphenated sections; only sections
#: attested in primary OLRC sources are emitted beside the integer range members,
#: preserving the enclosing entry's verbatim ``former_text`` and ``new_text``.
ATTESTED_RANGE_MEMBERS: dict[tuple[int, str], tuple[tuple[str, str], ...]] = {
    (31, "22-24"): (
        ("22a", "USCODE-1994-title31.pdf p. 79 § 1108(g) HRN cites 31:22a"),
    ),
    (31, "324b to 324c"): (
        ("324b-1", "USCODE-1994-title31.pdf § 5112 HRN cites 31:324b-1"),
    ),
    (46, "843-848"): (
        ("845a", "OLRC 1994-2005 usc46a.htm attests 46 App. § 845a"),
        ("845b", "OLRC 1994-2005 usc46a.htm attests 46 App. § 845b"),
    ),
    (46, "1183-1185a"): (
        ("1183a", "OLRC 1994-2005 usc46a.htm attests 46 App. § 1183a"),
    ),
}

_SECTION_ORDER_RE = re.compile(r"^(\d+)(.*)$")


def _section_order(section: str) -> tuple[int, str]:
    match = _SECTION_ORDER_RE.match(section.lower())
    if match is None:
        raise SystemExit(f"cannot order section token {section!r}")
    return (int(match.group(1)), match.group(2))


def _with_attested_range_members(
    former_title: int, former_text: str, formers: list[dict]
) -> list[dict]:
    """Insert independently attested alphanumeric range members in section order."""

    extras = ATTESTED_RANGE_MEMBERS.get((former_title, former_text))
    if not extras:
        return formers
    existing = {f["section"].lower() for f in formers}
    keys = [_section_order(f["section"]) for f in formers]
    lo_key, hi_key = min(keys), max(keys)
    merged = list(formers)
    for member, _evidence in extras:
        mkey = _section_order(member)
        if not (lo_key < mkey < hi_key):
            raise SystemExit(
                f"attested range member {member!r} does not fall strictly inside {former_text!r}"
            )
        if member.lower() in existing:
            raise SystemExit(f"attested range member {member!r} already emitted for {former_text!r}")
        merged.append({"section": member, "subsection": None, "note": None})
        existing.add(member.lower())
    merged.sort(key=lambda item: _section_order(item["section"]))
    return merged


def build(pdf: Path, spec: SourceSpec) -> list[dict]:
    """The whole derived table: one record per (former section token x successor)."""

    printed: list[dict] = []
    for page in spec.table_pages:
        for half in ("left", "right"):
            printed.extend(entries(table_rows(pdf, page, half, spec)))

    out: list[dict] = []
    prose: list[tuple[str, str]] = []
    seen_attested: set[tuple[int, str]] = set()
    seen_respective: set[tuple[int, str, str]] = set()
    for entry in printed:
        formers, skipped = parse_former(entry["former_text"])
        news = parse_new(entry["new_text"], spec.former_title)
        prose.extend((entry["former_text"], piece) for piece in skipped)
        if not formers:
            raise SystemExit(f"an entry naming no former section: {entry!r}")
        attested_key = (spec.former_title, entry["former_text"])
        if attested_key in ATTESTED_RANGE_MEMBERS:
            formers = _with_attested_range_members(spec.former_title, entry["former_text"], formers)
            seen_attested.add(attested_key)
        respective_key = (spec.former_title, entry["former_text"], entry["new_text"])
        if respective_key in RESPECTIVE_RANGE_ENTRIES:
            if len(formers) != len(news):
                raise SystemExit(f"respective-range length mismatch: {entry!r}")
            pairs = list(zip(formers, news, strict=True))
            seen_respective.add(respective_key)
        elif len(formers) > 1 and len(news) > 1:
            raise SystemExit(
                f"unreviewed multi-former x multi-new entry (verify respective vs Cartesian): {entry!r}"
            )
        else:
            pairs = [(former, new) for former in formers for new in news]
        for former, new in pairs:
            out.append(
                {
                    "former_title": spec.former_title,
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

    expected_attested = {k for k in ATTESTED_RANGE_MEMBERS if k[0] == spec.former_title}
    if seen_attested != expected_attested:
        raise SystemExit(f"unmatched ATTESTED_RANGE_MEMBERS: {sorted(expected_attested - seen_attested)}")
    expected_respective = {k for k in RESPECTIVE_RANGE_ENTRIES if k[0] == spec.former_title}
    if seen_respective != expected_respective:
        raise SystemExit(f"unmatched RESPECTIVE_RANGE_ENTRIES: {sorted(expected_respective - seen_respective)}")

    if prose:
        raise SystemExit(f"former fields whose pieces named no address: {prose!r}")
    for row in out:
        if not _is_section(row["former_section"] or ""):
            raise SystemExit(f"a parsed former section that is not a section token: {row!r}")
        if row["new_section"] is not None and not _is_section(row["new_section"]):
            raise SystemExit(f"a parsed new section that is not a section token: {row!r}")
        if row["former_note"] not in FORMER_NOTES:
            raise SystemExit(f"a former field saying something new: {row!r}")
        if row["status"] not in STATUSES:
            raise SystemExit(f"an undeclared status: {row!r}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--title", type=int, choices=sorted(SOURCE_SPECS), required=True)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument(
        "--text",
        type=Path,
        default=None,
        help="the printed entries, in print order, for reading against the pages",
    )
    args = ap.parse_args()

    spec = SOURCE_SPECS[args.title]
    verify_source(args.pdf, spec)
    rows = build(args.pdf, spec)

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
        args.json.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.text:
        seen: dict[tuple, None] = {}
        for row in rows:
            seen.setdefault((row["page"], row["column"], row["former_text"], row["new_text"]), None)
        args.text.write_text(
            "".join(f"{page:>3} {column:<5} {former}\t{new}\n" for page, column, former, new in seen) or "\n",
            encoding="utf-8",
        )

    printed_entries = len({(r["page"], r["column"], r["former_text"], r["new_text"]) for r in rows})
    print(f"title           : {spec.former_title}")
    print(f"printed entries : {printed_entries}")
    print(f"emitted rows    : {len(rows)}")
    print(f"former sections : {len({r['former_section'] for r in rows if r['former_section']})}")
    print(f"statuses        : {sorted({r['status'] for r in rows})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
