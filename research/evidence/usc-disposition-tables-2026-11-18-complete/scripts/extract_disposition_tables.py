#!/usr/bin/env python3
"""Extract and verify the 2026-11-18 complete U.S.C. disposition tables.

Produces deterministic, zstd-compressed Parquet tables (plus print-order `.txt`
companions) under ``research/evidence/usc-disposition-tables-2026-11-18-complete``
for:

1. ``usc-1996-title10-ropma-disposition.parquet`` — Title 10 Reserve Officer
   Personnel Management Act (`Pub. L. 103-337`, div. A, title XVI, 108 Stat.
   2924, effective Dec. 1, 1994 / Oct. 1, 1996, plus ROPMA technical repeal of
   `10 U.S.C. 5600` by `Pub. L. 104-106`, div. A, title XV, § 1501(c)(26)),
   extracted from `USCODE-1996-title10.pdf` and reconciled two ways between
   Subtitles A–D (`pp. 14–1511`) and Subtitle E (`pp. 1512–1647`).
2. ``usc-2017-title34-disposition.parquet`` — Title 34 editorial
   reclassification (`USCODE-2017-title34.pdf`, `pp. 1–9`, former Titles 42,
   18, and 28 -> Title 34).
3. ``usc-2011-title41-disposition.parquet`` — Title 41 positive-law enactment
   (`Pub. L. 111-350`, `USCODE-2011-title41.pdf`, `pp. 1–3`, former Title 41 ->
   Title 41, including pre-recodification oracle range verification for
   `41 U.S.C. 20a, 20b` inside `17 to 21`).
4. ``usc-2010-title51-disposition.parquet`` — Title 51 positive-law enactment
   (`Pub. L. 111-314`, `USCODE-2010-title51.pdf`, `pp. 1–2`, Table I [former
   Title 15] and Table II [former Title 42] -> Title 51).
5. ``usc-2014-title54-disposition.parquet`` — Title 54 positive-law enactment
   (`Pub. L. 113-287`, `USCODE-2014-title54.pdf`, `pp. 2–9`, former Title 16 ->
   Title 54).
6. ``usc-1994-title49-positivelaw-disposition.parquet`` — Pre-1994 positive-law
   Title 49 sections repealed or renumbered in place by `Pub. L. 103-272`
   (`USCODE-1994-title49.pdf`, closing `49 U.S.C. 3101..3104 -> 31501..31504`,
   `334 -> 45301`, `335 -> repealed`, and `508 -> 5901..5907`).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from string import ascii_lowercase

import pyarrow as pa
import pyarrow.parquet as pq

PDFTOTEXT_VERSION = "pdftotext version 26.10.0"
NS = "{http://www.w3.org/1999/xhtml}"
_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))
_LEADER = re.compile(r"\s*\.(?:\s?\.)+\s*$")

_SUFFIX_ORDER = tuple(ch * k for k in (1, 2, 3, 4) for ch in ascii_lowercase)
_SUFFIX_IDX = {s: i for i, s in enumerate(_SUFFIX_ORDER)}

_SEC_TOK = r"\d+[a-z]*(?:-\d+[a-z]*)*"
_SUBPATH = r"(?:\([0-9a-zA-Z]{1,4}\))+"
_ADDRESS = re.compile(r"^[0-9A-Za-z]{1,4}$")
_GROUP = re.compile(r"\([0-9A-Za-z]{1,4}\)")
_ENTRY_HEAD = re.compile(rf"^({_SEC_TOK})({_SUBPATH})?$")

STATUSES = ("restated", "restated-as-note", "repealed", "eliminated", "see-reference")
FORMER_NOTES = (None, "note", "notes")

SOURCE_PINS: dict[str, tuple[int, str]] = {
    "USCODE-1996-title10.pdf": (
        8_971_147,
        "sha256:d1877b5aa58f17062263fed5a04da62f3ad885b4b01a0da7f0e41d0da15e0010",
    ),
    "USCODE-2017-title34.pdf": (
        2_753_424,
        "sha256:c121b7ca9147571955edbb9857da95e17292f21eb00f0a90741ae5b99c40bcd9",
    ),
    "USCODE-2011-title41.pdf": (
        1_037_994,
        "sha256:3b253b255aa058d05aa4b3e6b6aa2f345ee25a1f98cff5ea19f514c2d0a417c1",
    ),
    "USCODE-2010-title51.pdf": (
        914_412,
        "sha256:66d48661b3bae9b9e9e7a1964a64ff093dc22d94fae81eda6429a4f9551cea84",
    ),
    "USCODE-2014-title54.pdf": (
        1_085_260,
        "sha256:548f857e19f2ce9c384211062872d422142a2b55129251d3f82e35c80eafcf21",
    ),
    "USCODE-1994-title49.pdf": (
        5_165_242,
        "sha256:66f004679e27e0d16356e14b79cb3b4f7ebf63d91307435fa8f53c95bcc2848d",
    ),
}

ORACLE_ANNUAL_PIN = (
    "research/evidence/usc-section-oracle-2026-08-24/usc-oracle-annual-sections.parquet",
    7_594_553,
    "sha256:4757327d2bbcd5258d0fc51f0658df7fc9999c21d5a40dbe0c2d466cf25e7323",
)

PARQUET_SCHEMA = pa.schema(
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


def check_pdftotext_version() -> None:
    proc = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True, check=False)
    banner = (proc.stderr or proc.stdout).splitlines()[0].strip()
    if banner != PDFTOTEXT_VERSION:
        raise SystemExit(f"expected {PDFTOTEXT_VERSION!r}, got {banner!r}")


def verify_pin(path: Path, expected_bytes: int, expected_sha256: str) -> None:
    if not path.is_file():
        raise SystemExit(f"missing pinned input: {path}")
    data = path.read_bytes()
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    if len(data) != expected_bytes or digest != expected_sha256:
        raise SystemExit(
            f"pin mismatch for {path}: expected {expected_bytes} / {expected_sha256}, "
            f"got {len(data)} / {digest}"
        )


def section_order_key(token: str) -> tuple[int, int, str, str] | None:
    m = re.match(r"^(\d+)([a-z]*)(.*)$", token.strip().lower())
    if not m:
        return None
    letters = m.group(2)
    return (int(m.group(1)), len(letters), letters, m.group(3))


def load_oracle_pre_cutoff_sections(repo_root: Path) -> dict[int, list[tuple[tuple[int, int, str, str], str, int]]]:
    """Load `(order_key, section, max_year_or_min_year)` from the pinned annual-sections Parquet."""
    rel, exp_bytes, exp_sha = ORACLE_ANNUAL_PIN
    parq = repo_root / rel
    verify_pin(parq, exp_bytes, exp_sha)
    tbl = pq.read_table(parq, columns=["year", "title", "appendix", "section"])
    min_year: dict[tuple[int, str], int] = {}
    for yr, tt, app, sec in zip(
        tbl["year"].to_pylist(),
        tbl["title"].to_pylist(),
        tbl["appendix"].to_pylist(),
        tbl["section"].to_pylist(),
        strict=True,
    ):
        if app:
            continue
        norm = str(sec).strip().lower()
        key = (int(tt), norm)
        if key not in min_year or int(yr) < min_year[key]:
            min_year[key] = int(yr)
    by_title: dict[int, list[tuple[tuple[int, str], str, int]]] = {}
    for (tt, sec), first_yr in min_year.items():
        okey = section_order_key(sec)
        if okey is not None and re.fullmatch(_SEC_TOK, sec):
            by_title.setdefault(tt, []).append((okey, sec, first_yr))
    for tt in by_title:
        by_title[tt].sort(key=lambda item: item[0])
    return by_title


def page_blocks(pdf: Path, page: int) -> list[dict]:
    xml = subprocess.run(
        ["pdftotext", "-bbox-layout", "-f", str(page), "-l", str(page), str(pdf), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    root = ET.fromstring(xml)
    blocks = []
    for block in root.iter(NS + "block"):
        lines = []
        for line in block.iter(NS + "line"):
            words = [w.text or "" for w in line.iter(NS + "word")]
            if words:
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


def merge_baselines(lines: list[dict], tol: float = 1.5) -> list[dict]:
    merged: list[dict] = []
    for line in sorted(lines, key=lambda ln: (ln["yMin"], ln["xMin"])):
        if merged and abs(merged[-1]["yMin"] - line["yMin"]) < tol:
            merged[-1]["text"] = f"{merged[-1]['text']} {line['text']}"
            merged[-1]["xMax"] = max(merged[-1]["xMax"], line["xMax"])
            continue
        merged.append(dict(line))
    return merged


_FURNITURE = re.compile(
    r"^(Page \d+|TITLE \d+-.+|D ISPOSITION T ABLE.*|Disposition Table.*|\(Showing [Dd]isposition.*|T ABLE [IVX]+.*)$"
)


def _is_furniture(block: dict) -> bool:
    return all(_FURNITURE.match(ln["text"]) for ln in block["lines"])


def _join_wrapped(prev: str, cont: str) -> str:
    return (prev[:-1] + cont) if prev.endswith("-") else f"{prev} {cont}"


def extract_front_matter_entries(
    pdf: Path,
    pages: range,
    splits: dict[str, float],
    f_match,
    n_match,
) -> list[dict]:
    all_ents: list[dict] = []
    for p in pages:
        blocks = page_blocks(pdf, p)
        for half, (lo, hi) in (("left", (0.0, 306.0)), ("right", (306.0, 1e9))):
            f_hdrs = sorted([b for b in blocks if lo <= b["xMin"] < hi and f_match(b)], key=lambda b: b["yMin"])
            n_hdrs = sorted([b for b in blocks if lo <= b["xMin"] < hi and n_match(b)], key=lambda b: b["yMin"])
            if len(f_hdrs) != len(n_hdrs):
                raise SystemExit(f"{pdf.name} p.{p} {half}: header count mismatch {len(f_hdrs)} vs {len(n_hdrs)}")
            split = splits[half]
            for idx, (fh, nh) in enumerate(zip(f_hdrs, n_hdrs, strict=True)):
                if abs(fh["yMax"] - nh["yMax"]) >= 5.0:
                    raise SystemExit(f"{pdf.name} p.{p} {half}: misaligned headers {fh} vs {nh}")
                next_hdr_y = f_hdrs[idx + 1]["yMin"] if idx + 1 < len(f_hdrs) else 1e9
                raw_below = [
                    b
                    for b in blocks
                    if max(fh["yMax"], nh["yMax"]) < b["yMin"] < next_hdr_y
                    and lo <= b["xMin"] < hi
                    and not _is_furniture(b)
                ]
                crossers = [b["yMin"] for b in raw_below if b["xMin"] < split < b["xMax"]]
                y_stop = min(crossers) if crossers else next_hdr_y
                below = [b for b in raw_below if b["yMin"] < y_stop]
                body = merge_baselines([ln for b in below if b["xMax"] < split for ln in b["lines"]])
                vals = merge_baselines([ln for b in below if b["xMin"] >= split for ln in b["lines"]])
                if not body or not vals:
                    raise SystemExit(f"{pdf.name} p.{p} {half}: empty column under header")
                f_margin = min(ln["xMin"] for ln in body)
                v_margin = min(ln["xMin"] for ln in vals)
                events = []
                used_v: set[int] = set()
                for fl in body:
                    matches = [i for i, vl in enumerate(vals) if i not in used_v and abs(fl["yMin"] - vl["yMin"]) < 1.5]
                    if len(matches) > 1:
                        raise SystemExit(f"{pdf.name} p.{p} {half}: multiple values on one baseline: {fl}")
                    if matches:
                        vi = matches[0]
                        used_v.add(vi)
                        events.append((fl["yMin"], fl, vals[vi]))
                    else:
                        events.append((fl["yMin"], fl, None))
                for i, vl in enumerate(vals):
                    if i not in used_v:
                        events.append((vl["yMin"], None, vl))
                events.sort(key=lambda e: e[0])
                ents: list[dict] = []
                for _, fl, vl in events:
                    if fl is not None and fl["xMin"] <= f_margin + 1.5:
                        if vl is None or vl["xMin"] > v_margin + 1.5:
                            raise SystemExit(f"{pdf.name} p.{p} {half}: flush former without flush value: {fl} / {vl}")
                        ents.append(
                            {
                                "page": p,
                                "half": half,
                                "former_header": fh["lines"][0]["text"],
                                "former_text": _LEADER.sub("", fl["text"]).strip(),
                                "new_text": vl["text"].strip(),
                            }
                        )
                    else:
                        if not ents:
                            raise SystemExit(f"{pdf.name} p.{p} {half}: continuation before first entry: {fl} / {vl}")
                        if fl is not None:
                            ents[-1]["former_text"] = _join_wrapped(
                                ents[-1]["former_text"], _LEADER.sub("", fl["text"]).strip()
                            )
                        if vl is not None:
                            if vl["xMin"] <= v_margin + 2.0:
                                raise SystemExit(f"{pdf.name} p.{p} {half}: unindented value continuation: {vl}")
                            ents[-1]["new_text"] = _join_wrapped(ents[-1]["new_text"], vl["text"].strip())
                all_ents.extend(ents)
    return all_ents


def expand_sec_range(
    lo: str,
    hi: str,
    *,
    attested_extras: list[tuple[tuple[int, str], str, int]] | None = None,
    cutoff_year: int | None = None,
) -> list[str]:
    base: list[str]
    if lo.isdigit() and hi.isdigit() and 0 <= int(hi) - int(lo) <= 60:
        base = [str(n) for n in range(int(lo), int(hi) + 1)]
    else:
        m_hi = re.fullmatch(r"(\d+)([a-z]+)", hi)
        m_lo = re.fullmatch(r"(\d+)([a-z]+)", lo)
        c_lo, c_hi = re.fullmatch(r"(\d+[a-z]*)-(\d+)", lo), re.fullmatch(r"(\d+[a-z]*)-(\d+)", hi)
        if lo.isdigit() and m_hi and m_hi.group(1) == lo and m_hi.group(2) in _SUFFIX_IDX:
            base = [lo] + [f"{lo}{_SUFFIX_ORDER[i]}" for i in range(_SUFFIX_IDX[m_hi.group(2)] + 1)]
        elif (
            lo.isdigit()
            and m_hi
            and int(lo) < int(m_hi.group(1))
            and int(m_hi.group(1)) - int(lo) <= 20
            and m_hi.group(2) == "a"
        ):
            base = [str(n) for n in range(int(lo), int(m_hi.group(1)) + 1)] + [hi]
        elif (
            m_lo
            and m_hi
            and m_lo.group(1) == m_hi.group(1)
            and m_lo.group(2) in _SUFFIX_IDX
            and m_hi.group(2) in _SUFFIX_IDX
            and _SUFFIX_IDX[m_lo.group(2)] <= _SUFFIX_IDX[m_hi.group(2)]
        ):
            i0, i1 = _SUFFIX_IDX[m_lo.group(2)], _SUFFIX_IDX[m_hi.group(2)]
            if len(m_lo.group(2)) == len(m_hi.group(2)):
                k = len(m_lo.group(2))
                c0, c1 = m_lo.group(2)[0], m_hi.group(2)[0]
                base = [f"{m_lo.group(1)}{chr(c) * k}" for c in range(ord(c0), ord(c1) + 1)]
            else:
                base = [f"{m_lo.group(1)}{_SUFFIX_ORDER[i]}" for i in range(i0, i1 + 1)]
        elif c_lo and c_hi and c_lo.group(1) == c_hi.group(1) and 0 <= int(c_hi.group(2)) - int(c_lo.group(2)) <= 60:
            base = [f"{c_lo.group(1)}-{n}" for n in range(int(c_lo.group(2)), int(c_hi.group(2)) + 1)]
        else:
            raise ValueError(f"unhandled section range: {lo!r} .. {hi!r}")

    if attested_extras and cutoff_year is not None:
        k_lo, k_hi = section_order_key(lo), section_order_key(hi)
        assert k_lo is not None and k_hi is not None
        known = set(base)
        for okey, sec, first_yr in attested_extras:
            if first_yr < cutoff_year and k_lo <= okey <= k_hi and sec not in known:
                base.append(sec)
                known.add(sec)
        base.sort(key=lambda s: section_order_key(s) or (10**9, 0, s, ""))
    return base


def _range_members(lo: str, hi: str) -> list[str] | None:
    if lo.isdigit() and hi.isdigit() and int(lo) <= int(hi):
        return [str(n) for n in range(int(lo), int(hi) + 1)]
    if len(lo) == 1 and len(hi) == 1 and lo.isalpha() and hi.isalpha() and lo.isupper() == hi.isupper() and lo <= hi:
        return [chr(c) for c in range(ord(lo), ord(hi) + 1)]
    return None


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


def _strip_prose(text: str) -> str:
    p_depth = 0
    b_depth = 0
    start = 0
    out: list[str] = []
    for i, ch in enumerate(text):
        if ch == "(" and b_depth == 0:
            if p_depth == 0:
                out.append(text[start:i])
                start = i
            p_depth += 1
        elif ch == ")" and b_depth == 0:
            p_depth -= 1
            if p_depth == 0:
                group = text[start + 1 : i]
                out.append(text[start : i + 1] if _ADDRESS.match(group) else " ")
                start = i + 1
        elif ch == "[" and p_depth == 0:
            if b_depth == 0:
                out.append(text[start:i])
            b_depth += 1
        elif ch == "]" and p_depth == 0:
            b_depth -= 1
            if b_depth == 0:
                out.append(" ")
                start = i + 1
    if p_depth != 0 or b_depth != 0:
        raise ValueError(f"unbalanced delimiters in former field: {text!r}")
    out.append(text[start:])
    cleaned = re.sub(r"\s+", " ", "".join(out)).strip().strip(".").strip()
    return re.sub(rf"\b({_SEC_TOK})\s+\(", r"\1(", cleaned)


def _split_word_range(
    part: str,
    *,
    attested_extras: list[tuple[tuple[int, str], str, int]] | None = None,
    cutoff_year: int | None = None,
) -> list[str]:
    m = re.split(r"\s+(?:to|through)\s+", part, maxsplit=1)
    if len(m) == 1:
        return [part]
    lo, hi = m[0].strip(), m[1].strip()
    if re.fullmatch(_SEC_TOK, lo) and re.fullmatch(_SEC_TOK, hi):
        return expand_sec_range(lo, hi, attested_extras=attested_extras, cutoff_year=cutoff_year)
    across = re.fullmatch(rf"({_SEC_TOK})({_SUBPATH})", lo)
    if across and re.fullmatch(_SEC_TOK, hi):
        members = expand_sec_range(across.group(1), hi, attested_extras=attested_extras, cutoff_year=cutoff_year)
        return [f"{members[0]}{across.group(2)}", *members[1:]]
    lom = re.fullmatch(rf"({_SEC_TOK})?({_SUBPATH})", lo)
    him = re.fullmatch(r"(\([0-9a-zA-Z]{1,4}\))", hi)
    if lom and him:
        head = lom.group(1) or ""
        sub = lom.group(2)
        stem_end = sub.rfind("(")
        stem = sub[:stem_end]
        last = sub[stem_end + 1 : -1]
        end = him.group(1)[1:-1]
        members = _range_members(last, end)
        if members:
            return [f"{head}{stem}({x})" for x in members]
    if lom and re.fullmatch(_SUBPATH, hi):
        return [f"{lo}-{hi}"]
    raise ValueError(f"unhandled word range: {part!r}")


def parse_former_modern(
    text: str,
    default_title: int | None = None,
    *,
    attested_by_title: dict[int, list[tuple[tuple[int, str], str, int]]] | None = None,
    cutoff_year: int | None = None,
    allow_range_extras: bool = True,
) -> tuple[list[dict], list[str]]:
    work = text.strip()
    title = default_title
    m_usc = re.match(r"^(\d+)\s+U\.S\.C\.\s+(.*)$", work)
    if m_usc:
        title = int(m_usc.group(1))
        work = m_usc.group(2)
    else:
        m_col = re.match(r"^(\d+):(.*)$", work)
        if m_col:
            title = int(m_col.group(1))
            work = m_col.group(2)
    if title is None:
        raise ValueError(f"no former_title for {text!r}")

    cleaned = _strip_prose(work)
    cleaned = re.sub(r"\bnotes?\s+prec\.?\b", "note", cleaned)
    extras = (attested_by_title or {}).get(title) if allow_range_extras else None

    out: list[dict] = []
    skipped: list[str] = []
    section: str | None = None
    previous_sub: str | None = None
    for part in [p.strip() for p in cleaned.split(",") if p.strip()]:
        for piece in _split_word_range(part, attested_extras=extras, cutoff_year=cutoff_year):
            note = None
            base = piece
            for sfx in (" notes", " note"):
                if base.endswith(sfx):
                    note = sfx.strip()
                    base = base[: -len(sfx)].strip()
                    break
            head = _ENTRY_HEAD.match(base)
            if head:
                section, previous_sub = head.group(1), head.group(2)
                out.append({"title": title, "section": section, "subsection": previous_sub, "note": note})
            elif re.fullmatch(rf"({_SEC_TOK})({_SUBPATH})-({_SUBPATH})", base):
                hm = re.match(rf"^({_SEC_TOK})((?:{_SUBPATH})-(?:{_SUBPATH}))$", base)
                assert hm is not None
                section, previous_sub = hm.group(1), hm.group(2)
                out.append({"title": title, "section": section, "subsection": previous_sub, "note": note})
            elif base.startswith("(") and section is not None:
                groups = _GROUP.findall(base)
                path = _inherit(previous_sub, groups) if "".join(groups) == base else base
                out.append({"title": title, "section": section, "subsection": path, "note": note})
                previous_sub = path
            else:
                skipped.append(piece)
    return out, skipped


def parse_new_modern(text: str, default_title: int) -> list[dict]:
    val = text.strip()
    if val in ("Rep.", "(Previously repealed)") or val.startswith(
        ("Previously repealed", "Repealed as ", "(Previously transferred to ")
    ):
        return [{"title": None, "section": None, "subsection": None, "status": "repealed"}]
    if val in ("Elim.", "(Omitted)", "(Previously omitted)", "omitted"):
        return [{"title": None, "section": None, "subsection": None, "status": "eliminated"}]
    if val.startswith(("Not repealed but omitted", "Outside scope", "Outside the scope", "See §")):
        return [{"title": None, "section": None, "subsection": None, "status": "see-reference"}]

    val_clean = val.rstrip(".")
    for pfx in ("Transfer to ", "Previously transferred to "):
        if val_clean.startswith(pfx):
            val_clean = val_clean[len(pfx) :].strip()

    title = default_title
    m_usc = re.match(r"^(\d+)\s+U\.S\.C\.\s+(.*)$", val_clean)
    if m_usc:
        title = int(m_usc.group(1))
        val_clean = m_usc.group(2).strip()

    out: list[dict] = []
    last_sec: str | None = None
    last_sub: str | None = None
    for chunk in [c.strip() for c in re.split(r"[;,]", val_clean) if c.strip()]:
        m_t = re.match(r"^T\.\s*(\d+)\s*§+\s*(.*)$", chunk)
        if m_t:
            title = int(m_t.group(1))
            chunk = m_t.group(2).strip()
        m_col = re.match(r"^(\d+):(.*)$", chunk)
        if m_col:
            title = int(m_col.group(1))
            chunk = m_col.group(2).strip()

        status = "restated"
        if chunk.startswith("note prec."):
            chunk = chunk[len("note prec.") :].strip()
            status = "restated-as-note"
        elif re.search(r"(?:\s*notes?\s+prec\.?|\s*notes?)$", chunk) and not chunk.isdigit():
            m_nt = re.match(rf"^({_SEC_TOK})\s*notes?(?:\s+prec\.?)?$", chunk)
            if m_nt:
                chunk = m_nt.group(1)
                status = "restated-as-note"

        for p in _split_word_range(chunk):
            hm = _ENTRY_HEAD.match(p)
            if hm:
                last_sec, last_sub = hm.group(1), hm.group(2)
                out.append({"title": title, "section": last_sec, "subsection": last_sub, "status": status})
            elif p.startswith("(") and last_sec is not None:
                groups = _GROUP.findall(p)
                sub = _inherit(last_sub, groups) if "".join(groups) == p else p
                last_sub = sub
                out.append({"title": title, "section": last_sec, "subsection": sub, "status": status})
            else:
                raise ValueError(f"unparsed new chunk {p!r} in {text!r}")
    if not out:
        raise ValueError(f"empty new parse for {text!r}")
    return out


def build_front_matter_table(
    pdf: Path,
    pages: range,
    splits: dict[str, float],
    f_match,
    n_match,
    former_title_fn,
    default_new_title: int,
    *,
    attested_by_title: dict[int, list[tuple[tuple[int, str], str, int]]],
    cutoff_year: int,
) -> list[dict]:
    ents = extract_front_matter_entries(pdf, pages, splits, f_match, n_match)
    rows: list[dict] = []
    skipped_all: list[tuple[str, str]] = []
    for e in ents:
        news = parse_new_modern(e["new_text"], default_new_title)
        formers, skipped = parse_former_modern(
            e["former_text"],
            former_title_fn(e),
            attested_by_title=attested_by_title,
            cutoff_year=cutoff_year,
            allow_range_extras=(len(news) == 1),
        )
        skipped_all.extend((e["former_text"], s) for s in skipped)
        if not formers:
            raise SystemExit(f"{pdf.name}: empty formers for {e!r}")
        if len(formers) > 1 and len(news) > 1:
            if len(formers) != len(news):
                raise SystemExit(f"{pdf.name}: mismatched multi-map {e!r} -> {len(formers)} vs {len(news)}")
            pairs = list(zip(formers, news, strict=True))
        else:
            pairs = [(f, n) for f in formers for n in news]
        for f, n in pairs:
            rows.append(
                {
                    "former_title": f["title"],
                    "former_section": f["section"],
                    "former_subsection": f["subsection"],
                    "former_note": f["note"],
                    "new_title": n["title"],
                    "new_section": n["section"],
                    "new_subsection": n["subsection"],
                    "status": n["status"],
                    "former_text": e["former_text"],
                    "new_text": e["new_text"],
                    "page": e["page"],
                    "column": e["half"],
                }
            )
    if skipped_all:
        raise SystemExit(f"{pdf.name}: unparsed former pieces: {skipped_all!r}")
    validate_rows(rows)
    return rows


def _locate_column(pdf: Path, page: int, needle: str, page_cache: dict[int, list[dict]]) -> str:
    if page not in page_cache:
        page_cache[page] = page_blocks(pdf, page)
    compact_needle = re.sub(r"[\s-]+", "", needle.translate(_DASHES))
    for blk in page_cache[page]:
        txt = re.sub(r"[\s-]+", "", "".join(ln["text"] for ln in blk["lines"]))
        if compact_needle in txt:
            return "left" if blk["xMin"] < 306.0 else "right"
    short = compact_needle[:14]
    for blk in page_cache[page]:
        txt = re.sub(r"[\s-]+", "", "".join(ln["text"] for ln in blk["lines"]))
        if short in txt:
            return "left" if blk["xMin"] < 306.0 else "right"
    raise SystemExit(f"{pdf.name} p.{page}: could not locate column for {needle!r}")


def _clean_raw_pages(pdf: Path) -> list[str]:
    raw = subprocess.run(["pdftotext", "-raw", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    raw = raw.translate(_DASHES)
    pages: list[str] = []
    for pg in raw.split("\x0c"):
        lines = []
        for idx, ln in enumerate(pg.splitlines()):
            s = ln.strip()
            if idx < 3 and (
                s.startswith("Page ")
                or re.match(r"^TITLE\s+\d+-", s)
                or (idx == 0 and s.startswith("§"))
            ):
                continue
            lines.append(ln)
        pages.append(re.sub(r"([a-z])-\n([a-z])", r"\1\2", "\n".join(lines)))
    return pages


def _expand_prior_list(spec: str, extras: set[str]) -> list[str]:
    """Expand `591 to 594, 595, and 596` or `1331 to 1338` (including attested `1331a`, `2233a`)."""
    out: list[str] = []
    for chunk in re.split(r",\s*(?:and\s+)?|\s+and\s+", spec.strip()):
        c = chunk.strip()
        if not c:
            continue
        m_rng = re.match(rf"^({_SEC_TOK})\s+to\s+({_SEC_TOK})$", c)
        if m_rng:
            lo, hi = m_rng.group(1), m_rng.group(2)
            members = [str(n) for n in range(int(lo), int(hi) + 1)]
            k_lo, k_hi = section_order_key(lo), section_order_key(hi)
            assert k_lo is not None and k_hi is not None
            for ex in extras:
                k_ex = section_order_key(ex)
                if k_ex and k_lo <= k_ex <= k_hi and ex not in members:
                    members.append(ex)
            members.sort(key=lambda s: section_order_key(s) or (10**9, 0, s, ""))
            out.extend(members)
        else:
            out.append(c)
    return out


def build_title10_ropma_table(pdf: Path) -> list[dict]:
    """Extract and two-way verify Title 10 ROPMA (`Pub. L. 103-337`) from `USCODE-1996-title10.pdf`."""
    pages = _clean_raw_pages(pdf)
    sub_e_start = next(i + 1 for i, pg in enumerate(pages) if re.search(r"(?m)^Subtitle E-Reserve Components\b", pg))

    # 1. Parse Subtitle E (`§§ 10001–18505`) renumberings + Prior Provisions subsection pinpoints
    full_e = "\n".join(f"<<<PAGE:{p}>>>\n{pages[p - 1]}" for p in range(sub_e_start, len(pages) + 1))
    renum_e: dict[str, str] = {}
    pp_pinpoints: dict[str, list[tuple[str | None, str, str | None]]] = {}
    for part in re.split(r"(?m)^(?=§\s*1\d{4}[a-z]*\.)", full_e)[1:]:
        m_new = re.match(r"^§\s*(1\d{4}[a-z]*)\.", part)
        assert m_new is not None
        new_s = m_new.group(1)
        clean = re.sub(r"\s+", " ", re.sub(r"<<<PAGE:\d+>>>", " ", part)).strip()
        m_am = re.search(rf"103-337[^.]*?\brenumbered section ({_SEC_TOK}) of this title as this section", clean)
        if not m_am:
            m_am = re.search(
                rf"Stat\.\s+\d+[A-Za-z0-9-]*,\s*§\s*({_SEC_TOK})\s*;[^)]*?renumbered\s+§\s*{re.escape(new_s)}\b[^)]*?103-337",
                clean,
            )
        if m_am:
            renum_e[m_am.group(1)] = new_s

        m_pp = re.search(
            r"PRIOR PROVISIONS\s+(.*?)(?:\s+AMENDMENTS|\s+EFFECTIVE DATE|\s+CROSS REFERENCES|\s+SECTION REFERRED|\s+HISTORICAL AND REVISION|\s+\[§|\Z)",
            clean,
        )
        if m_pp and "prior to repeal by Pub. L. 103-337" in m_pp.group(1):
            for m_cl in re.finditer(
                r"Provisions similar to those in (.*?)\s+were contained in\s+(.*?)\s+of this title,?\s+prior to repeal by Pub\. L\. 103-337",
                m_pp.group(1),
            ):
                lhs, rhs = m_cl.group(1).strip(), m_cl.group(2).strip()
                if "note under section" in rhs:
                    continue
                new_subs: list[str | None] = [None]
                if lhs.startswith("subsec"):
                    found_ns = re.findall(r"\([0-9a-zA-Z]{1,4}\)", lhs)
                    if found_ns:
                        new_subs = found_ns
                rhs_norm = re.sub(r"^sections?\s+", "", rhs)
                rhs_norm = re.sub(r"\)\s*-\s*\(", ") to (", rhs_norm)
                rhs_norm = re.sub(r",\s+and\s+|\s+and\s+", ", ", rhs_norm)
                parsed_f, skipped_f = parse_former_modern(rhs_norm, 10, allow_range_extras=False)
                if skipped_f:
                    raise SystemExit(f"Subtitle E §{new_s} unparsed PRIOR PROVISIONS rhs {rhs!r}: {skipped_f}")
                for pf in parsed_f:
                    for nsub in new_subs:
                        entry = (pf["subsection"], new_s, nsub)
                        bucket = pp_pinpoints.setdefault(pf["section"], [])
                        if entry not in bucket:
                            bucket.append(entry)

    alphanum_old_renum = {s for s in renum_e if not s.isdigit()}
    alphanum_new_renum = {s for s in renum_e.values() if not s.isdigit()}

    # 2. Parse Subtitles A–D (`pp. 14 .. sub_e_start - 1`) forward stubs + Prior section(s) notes
    paras: list[tuple[int, str]] = []
    cur_p = 14
    buf: list[str] = []
    in_bracket = False
    for pno in range(14, sub_e_start):
        for ln in pages[pno - 1].splitlines():
            s = ln.strip()
            if not s:
                if buf and not in_bracket:
                    paras.append((cur_p, " ".join(buf)))
                    buf = []
                continue
            if (
                not in_bracket
                and buf
                and (
                    s.startswith("[§")
                    or re.match(r"^§\s*\d+[a-z]*\.", s)
                    or re.match(
                        r"^(?:Section \d|Sections \d|Section, |A prior section |Prior sections? |CODIFICATION|PRIOR PROVISIONS|AMENDMENTS|EFFECTIVE DATE|HISTORICAL AND REVISION|CROSS REFERENCES|SECTION REFERRED|CHAPTER |SUBCHAPTER |PART )",
                        s,
                    )
                )
            ):
                paras.append((cur_p, " ".join(buf)))
                buf = [s]
                cur_p = pno
            else:
                if not buf:
                    cur_p = pno
                buf.append(s)
            joined_buf = " ".join(buf)
            in_bracket = ("[" in joined_buf) and ("]" not in joined_buf.split("[")[-1])
    if buf:
        paras.append((cur_p, " ".join(buf)))

    renum_ad: dict[str, tuple[str, int, str, str, str]] = {}
    repeal_ad: dict[str, tuple[list[tuple[str, str | None]], int, str, str, str]] = {}
    bbox_cache: dict[int, list[dict]] = {}

    # Pre-1994 renumberings noted alongside 1994 ones (1986 Pub. L. 99-348 / 99-433)
    pre_ropma_prior = {"1406", "3033", "8033"}

    i = 0
    while i < len(paras):
        pno, text = paras[i]
        m_ren = re.match(rf"^\[§+\s*({_SEC_TOK})\.\s*Renumbered\s+§+\s*(1\d{{4}}[a-z]*)\]$", text)
        if m_ren:
            old_s, new_s = m_ren.group(1), m_ren.group(2)
            renum_ad[old_s] = (new_s, pno, f"§ {old_s}", f"Renumbered § {new_s}", text[:28])
            i += 1
            continue

        is_ropma_stub = text.startswith("[§") and "Repealed" in text and (
            "103-337" in text or ("104-106" in text and "§1501(c)(26)" in text.replace(" ", ""))
        )
        is_ropma_prior_rep = text.startswith("Prior sections ") and "were repealed by Pub. L. 103-337" in text
        if is_ropma_stub or is_ropma_prior_rep:
            hdr = text
            j = i + 1
            captured = 0
            while j < len(paras):
                npno, ntxt = paras[j]
                if re.match(r"^(?:Section \d|Sections \d|Section, )", ntxt):
                    captured += 1
                    if ntxt.startswith("Section, "):
                        m_one = re.match(rf"^\[§\s*({_SEC_TOK})\.\s*Repealed", hdr)
                        assert m_one is not None, hdr
                        secs_here = [m_one.group(1)]
                    elif ntxt.startswith("Sections "):
                        m_many = re.match(r"^Sections\s+(.*?),\s+(?:act|acts|added)\b", ntxt)
                        assert m_many is not None, ntxt
                        secs_here = _expand_prior_list(m_many.group(1), set())
                    else:
                        m_s = re.match(rf"^Section\s+({_SEC_TOK}),\s+", ntxt)
                        assert m_s is not None, ntxt
                        secs_here = [m_s.group(1)]

                    targets: list[tuple[str, str | None]] = []
                    for m_see in re.finditer(r"See sections?\s+(1\d{4}[^.]*?)\s+of this title", ntxt):
                        sb = m_see.group(1)
                        for mr in re.finditer(r"(1\d{4})\s+to\s+(1\d{4})", sb):
                            for k in range(int(mr.group(1)), int(mr.group(2)) + 1):
                                targets.append((str(k), None))
                        sb_rest = re.sub(r"1\d{4}\s+to\s+1\d{4}", "", sb)
                        # Handle `10141(a), (b)` or `10101 and 10213` or `14301 et seq.`
                        sb_rest = sb_rest.replace("et seq.", "").strip()
                        sb_rest = re.sub(r",\s+and\s+|\s+and\s+", ", ", sb_rest)
                        if sb_rest:
                            pf, pskip = parse_former_modern(sb_rest, 10, allow_range_extras=False)
                            if pskip:
                                raise SystemExit(f"Title 10 unparsed See-target {sb!r}: {pskip}")
                            for item in pf:
                                targets.append((item["section"], item["subsection"]))
                    see_clause_m = re.search(r"See sections?\s+1\d{4}[^.]*\.", ntxt)
                    disp_txt = f"Repealed; {see_clause_m.group(0)}" if see_clause_m else "Repealed."
                    for sh in secs_here:
                        repeal_ad[sh] = (targets, npno, f"Section {sh}", disp_txt, ntxt[:28])
                    j += 1
                elif re.match(r"^A prior section \d", ntxt) and "103-337" not in ntxt:
                    # Skip older historical note embedded inside a section-notes run (e.g. 279, 5896, 8373)
                    j += 1
                else:
                    break
            if captured == 0:
                raise SystemExit(f"Title 10 repeal block without Section notes at p.{pno}: {hdr}")
            i = j
            continue

        # Single `A prior section X ... prior to repeal by Pub. L. 103-337` (1003, 2540)
        if text.startswith("A prior section ") and "prior to repeal by Pub. L. 103-337" in text:
            m_old = re.match(rf"^A prior section ({_SEC_TOK}),", text)
            assert m_old is not None, text
            sh = m_old.group(1)
            targets = [(m.group(1), m.group(2)) for m in re.finditer(rf"\b(1\d{{4}}[a-z]*)({_SUBPATH})?\b", text)]
            see_m = re.search(r"See sections?\s+1\d{4}[^.]*\.", text)
            disp_txt = f"Repealed; {see_m.group(0)}" if see_m else "Repealed."
            repeal_ad[sh] = (targets, pno, f"A prior section {sh}", disp_txt, text[:28])
            i += 1
            continue

        # `(A )?Prior section(s) ... renumbered section(s) 1xxxx ...`
        m_pr_one = re.match(
            rf"^(?:A )?[Pp]rior section ({_SEC_TOK}) was renumbered section (1\d{{4}}[a-z]*) of this title\.",
            text,
        )
        if m_pr_one:
            old_s, new_s = m_pr_one.group(1), m_pr_one.group(2)
            if old_s not in pre_ropma_prior:
                renum_ad[old_s] = (new_s, pno, f"Prior section {old_s}", f"Renumbered § {new_s}", text[:28])
            i += 1
            continue

        m_pr_many = re.match(
            r"^Prior sections (.*?) were renumbered sections (1\d{4}.*?) of this title, respectively\.",
            text,
        )
        if m_pr_many:
            olds = _expand_prior_list(m_pr_many.group(1), alphanum_old_renum)
            news = _expand_prior_list(m_pr_many.group(2), alphanum_new_renum)
            if len(olds) != len(news):
                raise SystemExit(f"Title 10 mismatched Prior sections list p.{pno}: {olds} vs {news}")
            for old_s, new_s in zip(olds, news, strict=True):
                renum_ad[old_s] = (new_s, pno, f"Prior section {old_s}", f"Renumbered § {new_s}", text[:28])
            i += 1
            continue

        i += 1

    # Strict two-way reconciliation of all 83 renumberings!
    ad_map = {k: v[0] for k, v in renum_ad.items()}
    if ad_map != renum_e:
        only_ad = sorted(set(ad_map) - set(renum_e))
        only_e = sorted(set(renum_e) - set(ad_map))
        diff_val = {k: (ad_map[k], renum_e[k]) for k in set(ad_map) & set(renum_e) if ad_map[k] != renum_e[k]}
        raise SystemExit(
            f"Title 10 ROPMA two-way renumbering mismatch: only_ad={only_ad}, only_e={only_e}, diff={diff_val}"
        )

    rows: list[dict] = []
    # Combine renumbered + repealed in canonical former_section order
    all_former = sorted(set(renum_ad) | set(repeal_ad), key=lambda s: section_order_key(s) or (10**9, 0, s, ""))
    for sec in all_former:
        if sec in renum_ad:
            new_s, pno, ftxt, ntxt, anchor = renum_ad[sec]
            col = _locate_column(pdf, pno, anchor, bbox_cache)
            rows.append(
                {
                    "former_title": 10,
                    "former_section": sec,
                    "former_subsection": None,
                    "former_note": None,
                    "new_title": 10,
                    "new_section": new_s,
                    "new_subsection": None,
                    "status": "restated",
                    "former_text": ftxt,
                    "new_text": ntxt,
                    "page": pno,
                    "column": col,
                }
            )
            for fsub, ns, nsub in pp_pinpoints.get(sec, []):
                if ns != new_s:
                    rows.append(
                        {
                            "former_title": 10,
                            "former_section": sec,
                            "former_subsection": fsub,
                            "former_note": None,
                            "new_title": 10,
                            "new_section": ns,
                            "new_subsection": nsub,
                            "status": "restated",
                            "former_text": f"{ftxt}{fsub or ''}",
                            "new_text": f"Repealed in part; see § {ns}{nsub or ''}",
                            "page": pno,
                            "column": col,
                        }
                    )
        else:
            targets, pno, ftxt, ntxt, anchor = repeal_ad[sec]
            col = _locate_column(pdf, pno, anchor, bbox_cache)
            pinpoints = pp_pinpoints.get(sec, [])
            has_sub_pinpoint = any(fsub is not None or nsub is not None for fsub, _, nsub in pinpoints)
            if has_sub_pinpoint:
                # Emit exact subsection-resolved mappings from Subtitle E Prior Provisions, plus any forward target not covered
                covered_new = {ns for _, ns, _ in pinpoints}
                for fsub, ns, nsub in pinpoints:
                    rows.append(
                        {
                            "former_title": 10,
                            "former_section": sec,
                            "former_subsection": fsub,
                            "former_note": None,
                            "new_title": 10,
                            "new_section": ns,
                            "new_subsection": nsub,
                            "status": "restated",
                            "former_text": f"{ftxt}{fsub or ''}",
                            "new_text": ntxt,
                            "page": pno,
                            "column": col,
                        }
                    )
                for ns, nsub in targets:
                    if ns not in covered_new:
                        rows.append(
                            {
                                "former_title": 10,
                                "former_section": sec,
                                "former_subsection": None,
                                "former_note": None,
                                "new_title": 10,
                                "new_section": ns,
                                "new_subsection": nsub,
                                "status": "restated",
                                "former_text": ftxt,
                                "new_text": ntxt,
                                "page": pno,
                                "column": col,
                            }
                        )
            elif targets or pinpoints:
                combined_targets: list[tuple[str, str | None]] = list(targets)
                seen_ns = {ns for ns, _ in combined_targets}
                for _, ns, nsub in pinpoints:
                    if ns not in seen_ns:
                        combined_targets.append((ns, nsub))
                        seen_ns.add(ns)
                for ns, nsub in combined_targets:
                    rows.append(
                        {
                            "former_title": 10,
                            "former_section": sec,
                            "former_subsection": None,
                            "former_note": None,
                            "new_title": 10,
                            "new_section": ns,
                            "new_subsection": nsub,
                            "status": "restated",
                            "former_text": ftxt,
                            "new_text": ntxt,
                            "page": pno,
                            "column": col,
                        }
                    )
            else:
                rows.append(
                    {
                        "former_title": 10,
                        "former_section": sec,
                        "former_subsection": None,
                        "former_note": None,
                        "new_title": None,
                        "new_section": None,
                        "new_subsection": None,
                        "status": "repealed",
                        "former_text": ftxt,
                        "new_text": ntxt,
                        "page": pno,
                        "column": col,
                    }
                )
    validate_rows(rows)
    return rows


def build_title49_positivelaw_table(pdf: Path) -> list[dict]:
    """Extract positive-law Title 49 sections repealed or renumbered in place by Pub. L. 103-272."""
    pages = _clean_raw_pages(pdf)
    bbox_cache: dict[int, list[dict]] = {}
    rows: list[dict] = []

    # 1. Bracketed repeal stubs in Subtitle I enacted by Pub. L. 103-272 (`[§§ 334, 335...]` p.44, `[§ 508...]` p.52)
    #    and HRN subsection mapping for `508 -> 5901..5907` (pp. 139–143).
    stub_repeals: dict[str, tuple[int, str, str]] = {}
    for pno in range(25, len(pages) + 1):
        pg = pages[pno - 1]
        for m in re.finditer(r"\[§§?([^\]]*?Repealed\.\s*Pub\.\s*L\.\s*103-272[^\]]*)\]", pg, re.S):
            hdr = re.sub(r"\s+", " ", m.group(0)).strip()
            tail = pg[m.end() : m.end() + 1400]
            if "334, 335" in hdr:
                for sec in ("334", "335"):
                    m_note = re.search(rf"Section {sec},.*?(?=\nSection |\n§|\Z)", tail, re.S)
                    assert m_note is not None
                    ntxt = re.sub(r"\s+", " ", m_note.group(0)).strip()
                    stub_repeals[sec] = (pno, f"§ {sec}", ntxt)
            else:
                m_sec = re.match(rf"^\[§\s*({_SEC_TOK})\.\s*Repealed", hdr)
                assert m_sec is not None, hdr
                sec = m_sec.group(1)
                m_note = re.search(r"Section,.*?(?=\nREGULATIONS|\nSUBCHAPTER|\n§|\Z)", tail, re.S)
                assert m_note is not None
                ntxt = re.sub(r"\s+", " ", m_note.group(0)).strip()
                stub_repeals[sec] = (pno, f"§ {sec}", ntxt)

    if set(stub_repeals) != {"334", "335", "508"}:
        raise SystemExit(f"unexpected Pub. L. 103-272 positive-law repeal stubs: {sorted(stub_repeals)}")

    # Parse Chapter 59 (`§§ 5901–5907`) HRN Source (U.S. Code) entries for `49:508`
    ch59_pinpoints: list[tuple[str | None, str | None, str, str | None]] = []
    body_59 = "\n".join(pages[24:])
    for blk in re.split(r"(?m)^(?=§590\d\.)", body_59)[1:]:
        m_ns = re.match(r"^§(590\d)\.", blk)
        assert m_ns is not None
        new_sec = m_ns.group(1)
        m_hrn = re.search(r"HISTORICAL AND REVISION NOTES\n(.*?)(?:\nIn |\nAMENDMENTS|\nSECTION REFERRED|\Z)", blk, re.S)
        if not m_hrn:
            continue
        hrn_lines = m_hrn.group(1)
        cur_new_sub: str | None = None
        for ln in hrn_lines.splitlines():
            m_rev = re.match(rf"^{new_sec}((?:\([0-9a-zA-Z]+\))*)", ln.strip())
            if m_rev:
                cur_new_sub = m_rev.group(1) or None
            for m_src in re.finditer(r"\b49:508(\([a-z]\))?(?:\s*\((note)\))?", ln):
                fsub = m_src.group(1)
                fnote = m_src.group(2)
                tup = (fsub, fnote, new_sec, cur_new_sub)
                if tup not in ch59_pinpoints:
                    ch59_pinpoints.append(tup)
    if not ch59_pinpoints:
        raise SystemExit("failed to extract Chapter 59 HRN mappings for 49:508")

    # Emit 334, 335, 508
    for sec in ("334", "335", "508"):
        pno, ftxt, ntxt = stub_repeals[sec]
        col = _locate_column(pdf, pno, sec, bbox_cache)
        if sec == "334":
            m_see = re.search(r"See section (\d+) of this title", ntxt)
            assert m_see is not None
            rows.append(
                {
                    "former_title": 49,
                    "former_section": "334",
                    "former_subsection": None,
                    "former_note": None,
                    "new_title": 49,
                    "new_section": m_see.group(1),
                    "new_subsection": None,
                    "status": "restated",
                    "former_text": ftxt,
                    "new_text": f"Repealed; see 49 U.S.C. {m_see.group(1)}",
                    "page": pno,
                    "column": col,
                }
            )
        elif sec == "335":
            rows.append(
                {
                    "former_title": 49,
                    "former_section": "335",
                    "former_subsection": None,
                    "former_note": None,
                    "new_title": None,
                    "new_section": None,
                    "new_subsection": None,
                    "status": "repealed",
                    "former_text": ftxt,
                    "new_text": "Repealed (Pub. L. 103-272, § 4(j)(9)(A))",
                    "page": pno,
                    "column": col,
                }
            )
        elif sec == "508":
            for fsub, fnote, new_sec, new_sub in ch59_pinpoints:
                label_f = f"§ 508{fsub or ''}{' note' if fnote else ''}"
                rows.append(
                    {
                        "former_title": 49,
                        "former_section": "508",
                        "former_subsection": fsub,
                        "former_note": fnote,
                        "new_title": 49,
                        "new_section": new_sec,
                        "new_subsection": new_sub,
                        "status": "restated",
                        "former_text": label_f,
                        "new_text": f"Repealed; restated in 49 U.S.C. {new_sec}{new_sub or ''}",
                        "page": pno,
                        "column": col,
                    }
                )

    # 2. Positive-law sections renumbered in place by Pub. L. 103-272 (`3101..3104 -> 31501..31504`)
    renumbered_49: list[tuple[str, str, int]] = []
    full_49 = "\n".join(f"<<<PAGE:{p}>>>\n{pages[p - 1]}" for p in range(25, len(pages) + 1))
    for blk in re.split(r"(?m)^(?=§\d+[a-z]*\.)", full_49)[1:]:
        m_new = re.match(r"^§(\d+[a-z]*)\.", blk)
        assert m_new is not None
        new_sec = m_new.group(1)
        clean = re.sub(r"\s+", " ", re.sub(r"<<<PAGE:\d+>>>", " ", blk))
        m_am = re.search(r"1994-Pub\. L\. 103-272 renumbered section (\d+[a-z]*) of this title as this section", clean)
        if m_am:
            idx_in_full = full_49.find(blk)
            pgs_before = re.findall(r"<<<PAGE:(\d+)>>>", full_49[:idx_in_full])
            pno = int(pgs_before[-1]) if pgs_before else 25
            renumbered_49.append((m_am.group(1), new_sec, pno))

    if [r[:2] for r in renumbered_49] != [
        ("3101", "31501"),
        ("3102", "31502"),
        ("3103", "31503"),
        ("3104", "31504"),
    ]:
        raise SystemExit(f"unexpected Pub. L. 103-272 in-place renumberings: {renumbered_49}")

    for old_sec, new_sec, pno in renumbered_49:
        col = _locate_column(pdf, pno, f"§ {new_sec}." if pno < 0 else new_sec, bbox_cache)
        rows.append(
            {
                "former_title": 49,
                "former_section": old_sec,
                "former_subsection": None,
                "former_note": None,
                "new_title": 49,
                "new_section": new_sec,
                "new_subsection": None,
                "status": "restated",
                "former_text": f"§ {old_sec}",
                "new_text": f"Renumbered § {new_sec} (Pub. L. 103-272, § 1(c), (e))",
                "page": pno,
                "column": col,
            }
        )

    validate_rows(rows)
    return rows


def validate_rows(rows: list[dict]) -> None:
    if not rows:
        raise SystemExit("refusing to write empty disposition table")
    for r in rows:
        if not re.fullmatch(_SEC_TOK, r["former_section"] or ""):
            raise SystemExit(f"invalid former_section: {r!r}")
        if r["former_note"] not in FORMER_NOTES:
            raise SystemExit(f"invalid former_note: {r!r}")
        if r["status"] not in STATUSES:
            raise SystemExit(f"invalid status: {r!r}")
        if r["column"] not in ("left", "right"):
            raise SystemExit(f"invalid column: {r!r}")


def write_outputs(rows: list[dict], parquet_path: Path, txt_path: Path) -> str:
    table = pa.Table.from_pylist(rows, schema=PARQUET_SCHEMA)
    pq.write_table(table, parquet_path, compression="zstd")
    seen: dict[tuple[int, str, str, str], None] = {}
    for r in rows:
        seen.setdefault((r["page"], r["column"], r["former_text"], r["new_text"]), None)
    txt_path.write_text(
        "".join(f"{page:>4} {column:<5} {former}\t{new}\n" for page, column, former, new in seen),
        encoding="utf-8",
    )
    return "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()


def resolve_pdf(name: str, pdf_dir: Path, repo_root: Path) -> Path:
    candidate = pdf_dir / name
    if candidate.is_file():
        return candidate
    if name == "USCODE-1994-title49.pdf":
        sealed = repo_root / "research/evidence/usc-disposition-tables-2026-08-23/USCODE-1994-title49.pdf"
        if sealed.is_file():
            return sealed
    raise SystemExit(f"missing PDF {name} in {pdf_dir}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--pdf-dir",
        type=Path,
        default=Path("/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/refspec-uscode-20261118"),
        help="directory holding cached GovInfo USCODE-*.pdf files",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="output evidence directory",
    )
    args = ap.parse_args()

    check_pdftotext_version()
    out_dir = args.out_dir.resolve()
    repo_root = out_dir.parents[2]
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs: dict[str, Path] = {}
    for fname, (exp_bytes, exp_sha) in SOURCE_PINS.items():
        path = resolve_pdf(fname, args.pdf_dir, repo_root)
        verify_pin(path, exp_bytes, exp_sha)
        pdfs[fname] = path

    attested_by_title = load_oracle_pre_cutoff_sections(repo_root)

    jobs = [
        (
            "usc-1996-title10-ropma-disposition",
            lambda: build_title10_ropma_table(pdfs["USCODE-1996-title10.pdf"]),
        ),
        (
            "usc-2017-title34-disposition",
            lambda: build_front_matter_table(
                pdfs["USCODE-2017-title34.pdf"],
                range(1, 10),
                {"left": 194.5, "right": 413.5},
                lambda b: len(b["lines"]) == 1 and b["lines"][0]["text"] == "Former Classification",
                lambda b: len(b["lines"]) == 1 and b["lines"][0]["text"] == "New Classification or Disposition",
                lambda _e: None,
                34,
                attested_by_title=attested_by_title,
                cutoff_year=2017,
            ),
        ),
        (
            "usc-2011-title41-disposition",
            lambda: build_front_matter_table(
                pdfs["USCODE-2011-title41.pdf"],
                range(1, 4),
                {"left": 197.45, "right": 416.45},
                lambda b: len(b["lines"]) == 2 and b["lines"][1]["text"] == "Former Sections",
                lambda b: len(b["lines"]) == 2 and b["lines"][1]["text"] == "New Sections",
                lambda _e: 41,
                41,
                attested_by_title=attested_by_title,
                cutoff_year=2010,
            ),
        ),
        (
            "usc-2010-title51-disposition",
            lambda: build_front_matter_table(
                pdfs["USCODE-2010-title51.pdf"],
                range(1, 3),
                {"left": 197.45, "right": 416.45},
                lambda b: len(b["lines"]) == 2 and b["lines"][1]["text"] == "Former Sections",
                lambda b: len(b["lines"]) == 2 and b["lines"][1]["text"] == "New Sections",
                lambda e: int(e["former_header"].split()[1]),
                51,
                attested_by_title=attested_by_title,
                cutoff_year=2010,
            ),
        ),
        (
            "usc-2014-title54-disposition",
            lambda: build_front_matter_table(
                pdfs["USCODE-2014-title54.pdf"],
                range(2, 10),
                {"left": 197.3, "right": 416.3},
                lambda b: len(b["lines"]) == 2 and b["lines"][0]["text"] == "Former United States Code",
                lambda b: len(b["lines"]) == 1 and b["lines"][0]["text"] == "Disposition",
                lambda _e: None,
                54,
                attested_by_title=attested_by_title,
                cutoff_year=2014,
            ),
        ),
        (
            "usc-1994-title49-positivelaw-disposition",
            lambda: build_title49_positivelaw_table(pdfs["USCODE-1994-title49.pdf"]),
        ),
    ]

    for stem, builder in jobs:
        rows = builder()
        parq = out_dir / f"{stem}.parquet"
        txt = out_dir / f"{stem}.txt"
        digest = write_outputs(rows, parq, txt)
        distinct_former = len({(r["former_title"], r["former_section"]) for r in rows})
        printed_entries = len({(r["page"], r["column"], r["former_text"], r["new_text"]) for r in rows})
        print(
            f"{stem}: entries={printed_entries}, rows={len(rows)}, "
            f"former_sections={distinct_former}, bytes={parq.stat().st_size}, {digest}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
