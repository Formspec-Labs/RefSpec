"""Independent pair-level body-note cross-check for the 6 complete U.S.C. disposition tables.

Verifies every extracted Parquet table in
``research/evidence/usc-disposition-tables-2026-11-18-complete`` against
``(former_title, former_section) -> (new_title, new_section)`` pairs extracted
independently from the body pages of each pinned GovInfo U.S. Code PDF
(Historical and Revision Notes, Codification Notes, Subtitle E Amendments /
Prior Provisions, and statutory credits), without importing the extractor or
registry modules.

Requires non-empty body-note pair populations for every volume, checks full
pair-level membership (`(former_title, former_section, new_title, new_section)`),
and supports `--self-test` to plant a wrong `new_section` in each table in
memory and prove the check rejects all six.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq

PDFTOTEXT_VERSION = "pdftotext version 26.10.0"
_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))
_SEC = r"\d+[a-z]*(?:-\d+[a-z]*)*"

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

TITLE49_FRONT_PIN = (
    "research/evidence/usc-disposition-tables-2026-08-23/usc-1994-title49-disposition.parquet",
    37_672,
    "sha256:8403212c0193b3361accf7ff4be238420634beb5aa5740d78b9960fef5b2aedd",
)

Pair = tuple[int, str, int, str]


def verify_environment_and_pdf(pdf: Path, expected_bytes: int, expected_sha: str) -> None:
    proc = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True, check=False)
    banner = (proc.stderr or proc.stdout).splitlines()[0].strip()
    if banner != PDFTOTEXT_VERSION:
        raise SystemExit(f"expected {PDFTOTEXT_VERSION!r}, got {banner!r}")
    data = pdf.read_bytes()
    sha = "sha256:" + hashlib.sha256(data).hexdigest()
    if len(data) != expected_bytes or sha != expected_sha:
        raise SystemExit(f"PDF pin mismatch on {pdf}: {len(data)} / {sha}")


def read_body_raw(pdf: Path, start_page: int) -> str:
    txt = subprocess.run(
        ["pdftotext", "-raw", "-f", str(start_page), str(pdf), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.translate(_DASHES)
    cleaned_pages = []
    for pg in txt.split("\x0c"):
        lines = []
        for idx, ln in enumerate(pg.splitlines()):
            s = ln.strip()
            if idx < 3 and (s.startswith("Page ") or re.match(r"^TITLE\s+\d+-", s) or (idx == 0 and s.startswith("§"))):
                continue
            lines.append(ln)
        cleaned_pages.append(re.sub(r"([a-z])-\n([a-z])", r"\1\2", "\n".join(lines)))
    return "\n".join(cleaned_pages)


def load_parquet_pairs(parquet_path: Path, *, include_notes: bool = True) -> set[Pair]:
    tbl = pq.read_table(parquet_path, columns=["former_title", "former_section", "new_title", "new_section", "status"])
    allowed_statuses = ("restated", "restated-as-note") if include_notes else ("restated",)
    pairs: set[Pair] = set()
    for ft, fs, nt, ns, st in zip(
        tbl["former_title"].to_pylist(),
        tbl["former_section"].to_pylist(),
        tbl["new_title"].to_pylist(),
        tbl["new_section"].to_pylist(),
        tbl["status"].to_pylist(),
        strict=True,
    ):
        if nt is not None and ns is not None and st in allowed_statuses:
            pairs.add((int(ft), str(fs), int(nt), str(ns)))
    return pairs


_HRN_TABLE_STOP = (
    r"(?:\n(?:In |The |Subsection |Subsections |Paragraph |Paragraphs |Clause |Subclause |Subparagraph "
    r"|Section \d|This section |This chapter |This amends )|\n[A-Z][A-Z0-9 ,.'()-]{4,}\n|\Z)"
)


def extract_hrn_pairs_colon(pdf: Path, start_page: int, new_title: int, allowed_former_titles: set[int]) -> set[Pair]:
    """Extract `(former_title, former_sec, new_title, new_sec)` from tabular `41:<sec>` HRNs (Title 41)."""
    body = read_body_raw(pdf, start_page)
    pairs: set[Pair] = set()
    for blk in re.split(r"(?m)^(?=§\s*\d+[a-z]*\.)", body)[1:]:
        m_ns = re.match(r"^§\s*(\d+[a-z]*)\.", blk)
        if not m_ns:
            continue
        new_sec = m_ns.group(1)
        m_hrn = re.search(rf"HISTORICAL AND REVISION NOTES\n(.*?){_HRN_TABLE_STOP}", blk, re.DOTALL)
        if not m_hrn:
            continue
        hrn = re.sub(r"\s+", " ", m_hrn.group(1))
        for m_src in re.finditer(rf"\b(\d+):({_SEC})\b", hrn):
            ft = int(m_src.group(1))
            fs = m_src.group(2)
            if ft in allowed_former_titles:
                pairs.add((ft, fs, new_title, new_sec))
    return pairs


def extract_hrn_pairs_usc(pdf: Path, start_page: int, new_title: int, allowed_former_titles: set[int]) -> set[Pair]:
    """Extract `(former_title, former_sec, new_title, new_sec)` from tabular `<T> U.S.C. <sec>` HRNs (Titles 51, 54)."""
    body = read_body_raw(pdf, start_page)
    pairs: set[Pair] = set()
    for blk in re.split(r"(?m)^(?=§\s*\d+[a-z]*\.)", body)[1:]:
        m_ns = re.match(r"^§\s*(\d+[a-z]*)\.", blk)
        if not m_ns:
            continue
        new_sec = m_ns.group(1)
        m_hrn = re.search(rf"HISTORICAL AND REVISION NOTES\n(.*?){_HRN_TABLE_STOP}", blk, re.DOTALL)
        if not m_hrn:
            continue
        hrn = re.sub(r"\s+", " ", m_hrn.group(1))
        for m_src in re.finditer(rf"\b(\d+)\s+U\.S\.C\.\s+(?:notes?\s+prec\.\s+)?({_SEC})\b", hrn):
            ft = int(m_src.group(1))
            fs = m_src.group(2)
            if ft in allowed_former_titles:
                pairs.add((ft, fs, new_title, new_sec))
    return pairs


def extract_title34_codification_pairs(pdf: Path) -> set[Pair]:
    """Extract `(former_title, former_sec, 34, new_sec)` from body CODIFICATION notes in Title 34."""
    body = read_body_raw(pdf, 10)
    pairs: set[Pair] = set()
    for blk in re.split(r"(?m)^(?=§\s*\d+[a-z]*\.)", body)[1:]:
        m_ns = re.match(r"^§\s*(\d+[a-z]*)\.", blk)
        if not m_ns:
            continue
        new_sec = m_ns.group(1)
        m_cod = re.search(
            r"CODIFICATION\n(.*?)(?:\nPRIOR PROVISIONS|\nAMENDMENTS|\nEFFECTIVE DATE|\nCHANGE OF NAME|\nTRANSFER OF FUNCTIONS|\Z)",
            blk,
            re.DOTALL,
        )
        if not m_cod:
            continue
        cod = re.sub(r"\s+", " ", m_cod.group(1))
        for m in re.finditer(
            rf"Section was formerly classified to section ({_SEC}) of Title (\d+)",
            cod,
        ):
            fs, ft = m.group(1), int(m.group(2))
            if ft in {18, 28, 42}:
                pairs.add((ft, fs, 34, new_sec))
    return pairs


def extract_title10_subtitle_e_pairs(pdf: Path) -> set[Pair]:
    """Independently extract `(10, old_sec, 10, new_sec)` from Subtitle E (`pp. 1512–1647`) only."""
    ad_body = read_body_raw(pdf, 14)
    sub_e_idx = ad_body.find("\nSubtitle E-Reserve Components\n")
    assert sub_e_idx > 0
    sub_e = ad_body[sub_e_idx:]

    pairs: set[Pair] = set()
    for blk in re.split(r"(?m)^(?=§\s*1\d{4}[a-z]*\.)", sub_e)[1:]:
        m_ns = re.match(r"^§\s*(1\d{4}[a-z]*)\.", blk)
        assert m_ns is not None
        new_sec = m_ns.group(1)
        clean = re.sub(r"\s+", " ", blk)
        for m_ren in re.finditer(rf"103-337[^.]*?\brenumbered section ({_SEC}) of this title as this section", clean):
            pairs.add((10, m_ren.group(1), 10, new_sec))
        m_pp = re.search(
            r"PRIOR PROVISIONS\s+(.*?)(?:\s+AMENDMENTS|\s+EFFECTIVE DATE|\s+CROSS REFERENCES|\s+SECTION REFERRED|\s+\[§|\Z)",
            clean,
        )
        if m_pp and "by Pub. L. 103-337" in m_pp.group(1):
            for m_cl in re.finditer(
                r"were contained in\s+(.*?)\s+of this title,?\s+prior to (?:repeal|amendment|general amendment) by Pub\. L\. 103-337([^.]*)\.",
                m_pp.group(1),
            ):
                rhs, sec_cite = m_cl.group(1), m_cl.group(2)
                if "904(" in sec_cite or "note under section" in rhs:
                    continue
                rhs_clean = re.sub(r"^formula \d+ of the table in ", "", rhs)
                rhs_clean = re.sub(r"\([0-9a-zA-Z]+\)", "", rhs_clean)
                for mr in re.finditer(r"(\d+)\s+to\s+(\d+)", rhs_clean):
                    for k in range(int(mr.group(1)), int(mr.group(2)) + 1):
                        pairs.add((10, str(k), 10, new_sec))
                rhs_rest = re.sub(r"\d+\s+to\s+\d+", "", rhs_clean)
                for s_old in re.findall(rf"\b({_SEC})\b", rhs_rest):
                    pairs.add((10, s_old, 10, new_sec))
    return pairs


def _load_front_title49_former_sections(repo_root: Path) -> set[str]:
    rel, exp_bytes, exp_sha = TITLE49_FRONT_PIN
    p = repo_root / rel
    data = p.read_bytes()
    sha = "sha256:" + hashlib.sha256(data).hexdigest()
    if len(data) != exp_bytes or sha != exp_sha:
        raise SystemExit(f"Title 49 front-table pin mismatch on {p}: {len(data)} / {sha}")
    return {str(s).strip().lower() for s in pq.read_table(p, columns=["former_section"])["former_section"].to_pylist()}


def extract_title10_non_successor_statuses(pdf: Path) -> dict[tuple[int, str], set[str]]:
    """Independently extract ALL Title 10 ROPMA `see-reference` and `repealed` section statuses from Subtitles A–D."""
    full_body = read_body_raw(pdf, 14)
    m_sub_e = re.search(r"(?m)^Subtitle E-Reserve Components\b", full_body)
    if not m_sub_e:
        raise SystemExit("Subtitle E heading not found in USCODE-1996-title10.pdf")
    ad_text = full_body[: m_sub_e.start()]

    paras: list[str] = []
    buf: list[str] = []
    in_b = False
    for ln in ad_text.splitlines():
        s = ln.strip()
        if not s:
            if buf and not in_b:
                paras.append(" ".join(buf))
                buf = []
            continue
        if (
            not in_b
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
            paras.append(" ".join(buf))
            buf = [s]
        else:
            buf.append(s)
        joined = " ".join(buf)
        in_b = ("[" in joined) and ("]" not in joined.split("[")[-1])
    if buf:
        paras.append(" ".join(buf))

    def expand_list(spec: str) -> list[str]:
        out: list[str] = []
        for chunk in re.split(r",\s*(?:and\s+)?|\s+and\s+", spec.strip()):
            c = chunk.strip()
            if not c:
                continue
            mr = re.match(rf"^({_SEC})\s+to\s+({_SEC})$", c)
            if mr:
                out.extend(str(n) for n in range(int(mr.group(1)), int(mr.group(2)) + 1))
            else:
                out.append(c)
        return out

    statuses: dict[tuple[int, str], set[str]] = {}
    i = 0
    while i < len(paras):
        txt = paras[i]
        is_stub = txt.startswith("[§") and "Repealed" in txt and (
            ("103-337" in txt and "title XVI" in txt)
            or ("104-106" in txt and "§1501(c)(26)" in txt.replace(" ", ""))
        )
        is_prior_rep = txt.startswith("Prior sections ") and "were repealed by Pub. L. 103-337" in txt
        if is_stub or is_prior_rep:
            j = i + 1
            while j < len(paras):
                nt = paras[j]
                if re.match(r"^(?:Section \d|Sections \d|Section, )", nt):
                    if nt.startswith("Section, "):
                        m1 = re.match(rf"^\[§\s*({_SEC})\.\s*Repealed", txt)
                        assert m1 is not None
                        secs = [m1.group(1)]
                    elif nt.startswith("Sections "):
                        mm = re.match(r"^Sections\s+(.*?),\s+(?:act|acts|added)\b", nt)
                        assert mm is not None
                        secs = expand_list(mm.group(1))
                    else:
                        ms = re.match(rf"^Section\s+({_SEC}),\s+", nt)
                        assert ms is not None
                        secs = [ms.group(1)]
                    see_clauses = [m.group(1) for m in re.finditer(r"See sections?\s+(\d+[a-z]*(?:[^.]|\bet seq\.)*?)\s+of this title", nt)]
                    has_concrete = any("et seq." not in sc for sc in see_clauses)
                    has_et_seq = any("et seq." in sc for sc in see_clauses)
                    if not has_concrete:
                        st = "see-reference" if has_et_seq else "repealed"
                        for s_old in secs:
                            statuses[(10, s_old)] = {st}
                    j += 1
                elif re.match(r"^A prior section \d", nt) and "103-337" not in nt:
                    j += 1
                else:
                    break
            i = j
            continue
        if txt.startswith("A prior section ") and "prior to repeal by Pub. L. 103-337" in txt:
            m_old = re.match(rf"^A prior section ({_SEC}),", txt)
            assert m_old is not None
            concrete = re.findall(r"\b1\d{4}[a-z]*\b", txt)
            if not concrete:
                statuses[(10, m_old.group(1))] = {"repealed"}
        i += 1
    sub_e_covered = {fs for _, fs, _, _ in extract_title10_subtitle_e_pairs(pdf)}
    for fs in list(statuses):
        if fs[1] in sub_e_covered:
            del statuses[fs]
    see_cnt = sum(1 for v in statuses.values() if v == {"see-reference"})
    rep_cnt = sum(1 for v in statuses.values() if v == {"repealed"})
    if see_cnt != 39 or rep_cnt != 19:
        raise SystemExit(f"unexpected Title 10 non-successor status counts: see={see_cnt}, repealed={rep_cnt}")
    return statuses


def extract_title49_positivelaw_body_pairs(pdf: Path, repo_root: Path) -> set[Pair]:
    """Independently extract `(49, old_sec, 49, new_sec)` from statutory credits and HRN tables in Title 49."""
    front_former = _load_front_title49_former_sections(repo_root)
    body = read_body_raw(pdf, 25)
    pairs: set[Pair] = set()
    for blk in re.split(r"(?m)^(?=§\d+[a-z]*\.)", body)[1:]:
        m_ns = re.match(r"^§(\d+[a-z]*)\.", blk)
        if not m_ns:
            continue
        new_sec = m_ns.group(1)
        clean = re.sub(r"\s+", " ", blk)
        # Statutory credit `Stat. \d+, § 310x; ... renumbered § 3150x [and amended] Pub. L. 103-272`
        m_cred = re.search(
            rf"Stat\.\s+\d+,\s*§\s*(\d+[a-z]*)\s*;.{{0,350}}?renumbered\s+§\s*{re.escape(new_sec)}(?:\s+and\s+amended)?,?\s+Pub\.\s*L\.\s*103-272",
            clean,
        )
        if m_cred and m_cred.group(1).lower() not in front_former:
            pairs.add((49, m_cred.group(1).lower(), 49, new_sec))
        # HRN table rows ONLY (stopping before prose like `This chapter restates 49:508` or `This amends 49:47531`)
        if re.search(r"\((?:Added )?Pub\.\s*L\.\s*103-272,\s*§\s*1\b", clean):
            m_hrn = re.search(rf"HISTORICAL AND REVISION NOTES\n(.*?){_HRN_TABLE_STOP}", blk, re.DOTALL)
            if m_hrn:
                for m_src in re.finditer(r"\b49:(\d+[a-z]*)\b", m_hrn.group(1)):
                    prefix = m_hrn.group(1)[max(0, m_src.start() - 10) : m_src.start()]
                    if "App" in prefix:
                        continue
                    fsec = m_src.group(1).lower()
                    if fsec not in front_former:
                        pairs.add((49, fsec, 49, new_sec))
    return pairs


PinpointRow = tuple[int, str, str | None, str | None, int | None, str | None, str | None, str]


def load_parquet_rows(parquet_path: Path) -> list[dict]:
    return pq.read_table(parquet_path).to_pylist()


def extract_title49_positivelaw_body_pinpoints(pdf: Path, repo_root: Path) -> set[PinpointRow]:
    """Independently extract ALL 49 positive-law Title 49 row tuples (HRN tables + repeal stub + renumberings)."""
    front_former = _load_front_title49_former_sections(repo_root)
    body = read_body_raw(pdf, 25)
    out: set[PinpointRow] = set()
    for m_stub in re.finditer(r"\[§§?([^\]]*?Repealed\.\s*Pub\.\s*L\.\s*103-272[^\]]*)\]", body, re.DOTALL):
        hdr = re.sub(r"\s+", " ", m_stub.group(0)).strip()
        tail = body[m_stub.end() : m_stub.end() + 1400]
        if "334, 335" in hdr:
            for sec in ("334", "335"):
                mn = re.search(rf"Section {sec},.*?(?=\nSection |\n§|\Z)", tail, re.DOTALL)
                if mn and "See section" not in mn.group(0):
                    out.add((49, sec, None, None, None, None, None, "repealed"))
    for blk in re.split(r"(?m)^(?=§\d+[a-z]*\.)", body)[1:]:
        m_ns = re.match(r"^§(\d+[a-z]*)\.", blk)
        if not m_ns:
            continue
        new_sec = m_ns.group(1)
        clean = re.sub(r"\s+", " ", blk)
        m_cred = re.search(
            rf"Stat\.\s+\d+,\s*§\s*(\d+[a-z]*)\s*;.{{0,350}}?renumbered\s+§\s*{re.escape(new_sec)}(?:\s+and\s+amended)?,?\s+Pub\.\s*L\.\s*103-272",
            clean,
        )
        if m_cred and m_cred.group(1).lower() not in front_former:
            out.add((49, m_cred.group(1).lower(), None, None, 49, new_sec, None, "restated"))
        if not re.search(r"\((?:Added )?Pub\.\s*L\.\s*103-272,\s*§\s*1\b", clean):
            continue
        m_hrn = re.search(rf"HISTORICAL AND REVISION NOTES\n(.*?){_HRN_TABLE_STOP}", blk, re.DOTALL)
        if not m_hrn:
            continue
        cur_new_sub: str | None = None
        for ln in m_hrn.group(1).splitlines():
            m_rev = re.match(rf"^{re.escape(new_sec)}((?:\([0-9a-zA-Z]+\))*)", ln.strip())
            if m_rev:
                cur_new_sub = m_rev.group(1) or None
            for m_src in re.finditer(
                r"\b49:(\d+[a-z]*)((?:\([0-9a-zA-Z]+\))*)(?:,\s*(\([0-9a-zA-Z]+\)))?(?:\s*\((note(?:\s+prec\.)?)\))?",
                ln,
            ):
                prefix = ln[max(0, m_src.start() - 10) : m_src.start()]
                if "App" in prefix:
                    continue
                fsec = m_src.group(1).lower()
                if fsec in front_former:
                    continue
                fsub = m_src.group(2) or None
                extra = m_src.group(3)
                fnote = "note" if m_src.group(4) else None
                out.add((49, fsec, fsub, fnote, 49, new_sec, cur_new_sub, "restated"))
                if fsub and extra:
                    stem = fsub[: fsub.rfind("(")]
                    out.add((49, fsec, stem + extra, fnote, 49, new_sec, cur_new_sub, "restated"))
    return out


def verify_pair_agreement(
    name: str,
    body_pairs: set[Pair],
    parquet_pairs: set[Pair],
    *,
    min_body_pairs: int,
    known_publisher_typos: dict[Pair, Pair] | None = None,
    strict_no_extra_on_covered_former: bool = False,
    allowed_extra_pairs: set[Pair] | None = None,
) -> dict:
    typos = dict(known_publisher_typos or {})
    allowed_extra = set(allowed_extra_pairs or ())
    if len(body_pairs) < min_body_pairs:
        raise ValueError(
            f"{name}: body-note pair population too small ({len(body_pairs)} < {min_body_pairs})"
        )
    missing = sorted(body_pairs - parquet_pairs - set(typos))
    missing_typos_in_body = sorted(set(typos) - body_pairs)
    missing_typos_in_parquet = sorted(expected_printed for expected_printed in typos.values() if expected_printed not in parquet_pairs)
    extra_on_covered: list[Pair] = []
    if strict_no_extra_on_covered_former:
        covered_former = {(ft, fs) for ft, fs, _, _ in body_pairs}
        extra_on_covered = sorted(
            p
            for p in parquet_pairs
            if (p[0], p[1]) in covered_former
            and p not in body_pairs
            and p not in set(typos.values())
            and p not in allowed_extra
        )
    if missing or missing_typos_in_body or missing_typos_in_parquet or extra_on_covered:
        raise ValueError(
            f"{name}: pair-level mismatch! missing_from_parquet={missing[:10]} "
            f"(count={len(missing)}), extra_on_covered_former={extra_on_covered[:10]} "
            f"(count={len(extra_on_covered)}), missing_typos_in_body={missing_typos_in_body}, "
            f"missing_typos_in_parquet={missing_typos_in_parquet}"
        )
    matched = len(body_pairs & parquet_pairs)
    return {
        "table": name,
        "parquet_restated_pairs": len(parquet_pairs),
        "body_note_pairs_extracted": len(body_pairs),
        "body_note_pairs_matched": matched,
        "extra_on_covered_former_checked": strict_no_extra_on_covered_former,
        "known_publisher_typos": [
            {
                "body_note_pair": {"former_title": b[0], "former_section": b[1], "new_title": b[2], "new_section": b[3]},
                "printed_table_pair": {"former_title": p[0], "former_section": p[1], "new_title": p[2], "new_section": p[3]},
            }
            for b, p in sorted(typos.items())
        ],
    }


def verify_pinpoint_and_status_integrity(
    name: str,
    rows: list[dict],
    *,
    expected_pinpoints: set[PinpointRow] | None = None,
    exact_pinpoints: bool = False,
    forbidden_pinpoints: set[PinpointRow] | None = None,
    expected_statuses: dict[tuple[int, str], set[str]] | None = None,
    exact_non_successor_statuses: bool = False,
) -> None:
    """Verify row-level status invariants, exact pinpoint tuples, and non-successor statuses."""
    valid_statuses = {"restated", "restated-as-note", "repealed", "eliminated", "see-reference"}
    observed_pinpoints: set[PinpointRow] = set()
    statuses_by_sec: dict[tuple[int, str], set[str]] = {}
    for row in rows:
        st = row["status"]
        if st not in valid_statuses:
            raise ValueError(f"{name}: invalid status {st!r} on {row}")
        has_succ = row["new_title"] is not None and row["new_section"] is not None
        if (st in ("restated", "restated-as-note")) != has_succ:
            raise ValueError(f"{name}: status/successor mismatch on {row}")
        if st == "see-reference" and not str(row["new_text"]).strip():
            raise ValueError(f"{name}: see-reference row missing printed disposition text: {row}")
        statuses_by_sec.setdefault((int(row["former_title"]), str(row["former_section"])), set()).add(st)
        observed_pinpoints.add(
            (
                int(row["former_title"]),
                str(row["former_section"]),
                row["former_subsection"],
                row["former_note"],
                int(row["new_title"]) if row["new_title"] is not None else None,
                str(row["new_section"]) if row["new_section"] is not None else None,
                row["new_subsection"],
                st,
            )
        )
    if expected_pinpoints:
        missing_pp = sorted(expected_pinpoints - observed_pinpoints)
        extra_pp = sorted(observed_pinpoints - expected_pinpoints) if exact_pinpoints else []
        if missing_pp or extra_pp:
            raise ValueError(f"{name}: pinpoint row mismatch! missing={missing_pp[:10]}, extra={extra_pp[:10]}")
    if forbidden_pinpoints:
        bad_pp = sorted(forbidden_pinpoints & observed_pinpoints)
        if bad_pp:
            raise ValueError(f"{name}: forbidden pinpoint rows present: {bad_pp[:10]}")
    if expected_statuses:
        for key, want_statuses in expected_statuses.items():
            got = statuses_by_sec.get(key, set())
            if got != want_statuses:
                raise ValueError(f"{name}: status mismatch on {key}: expected={sorted(want_statuses)}, observed={sorted(got)}")
        if exact_non_successor_statuses:
            observed_non_succ = {
                k: v for k, v in statuses_by_sec.items() if v & {"repealed", "eliminated", "see-reference"}
            }
            expected_non_succ = {
                k: v for k, v in expected_statuses.items() if v & {"repealed", "eliminated", "see-reference"}
            }
            if observed_non_succ != expected_non_succ:
                extra_st = sorted(set(observed_non_succ) - set(expected_non_succ))
                raise ValueError(f"{name}: unexpected non-successor status sections: {extra_st[:10]}")


def run_self_test(
    specs: list[tuple[str, set[Pair], set[Pair], int, dict[Pair, Pair], bool, set[Pair]]],
    t49p_rows: list[dict],
    t49p_body_pinpoints: set[PinpointRow],
    t10_rows: list[dict],
    t10_non_succ_statuses: dict[tuple[int, str], set[str]],
) -> list[dict]:
    """Plant wrong successors, EXTRA spurious successors, wrong/extra pinpoints, and wrong statuses; prove every one fails."""
    results = []
    for name, body_pairs, parquet_pairs, min_cnt, typos, strict_extra, allowed_extra in specs:
        victims = [min(body_pairs & parquet_pairs), *sorted(typos.values())]
        for victim in victims:
            corrupted = (parquet_pairs - {victim}) | {(victim[0], victim[1], victim[2], "999999")}
            try:
                verify_pair_agreement(
                    name,
                    body_pairs,
                    corrupted,
                    min_body_pairs=min_cnt,
                    known_publisher_typos=typos,
                    strict_no_extra_on_covered_former=strict_extra,
                    allowed_extra_pairs=allowed_extra,
                )
            except ValueError as exc:
                results.append({"table": name, "mutation": "replace_successor", "planted_victim": list(victim), "caught": True, "error": str(exc)[:140]})
            else:
                raise SystemExit(f"SELF-TEST FAILED on {name}: planted corruption on {victim} was NOT caught!")
        if strict_extra:
            victim = min(body_pairs & parquet_pairs)
            with_extra = parquet_pairs | {(victim[0], victim[1], victim[2], "999999")}
            try:
                verify_pair_agreement(
                    name,
                    body_pairs,
                    with_extra,
                    min_body_pairs=min_cnt,
                    known_publisher_typos=typos,
                    strict_no_extra_on_covered_former=True,
                    allowed_extra_pairs=allowed_extra,
                )
            except ValueError as exc:
                results.append({"table": name, "mutation": "extra_spurious_successor", "planted_victim": [victim[0], victim[1], victim[2], "999999"], "caught": True, "error": str(exc)[:140]})
            else:
                raise SystemExit(f"SELF-TEST FAILED on {name}: planted extra spurious successor alongside {victim} was NOT caught!")

    # Planted wrong pinpoint on Title 49 positive-law (`508(d) -> 5903(a)` instead of `(b)`)
    mutated_pp = [dict(r) for r in t49p_rows]
    for r in mutated_pp:
        if r["former_section"] == "508" and r["former_subsection"] == "(d)":
            r["new_subsection"] = "(a)"
    try:
        verify_pinpoint_and_status_integrity(
            "usc-1994-title49-positivelaw-disposition.parquet",
            mutated_pp,
            expected_pinpoints=t49p_body_pinpoints,
            exact_pinpoints=True,
        )
    except ValueError as exc:
        results.append({"table": "usc-1994-title49-positivelaw-disposition.parquet", "mutation": "wrong_pinpoint", "caught": True, "error": str(exc)[:140]})
    else:
        raise SystemExit("SELF-TEST FAILED: planted wrong pinpoint on 508(d) was NOT caught!")

    # Planted EXTRA spurious pinpoint alongside genuine row (`508(d) -> 5903(a)` added alongside `508(d) -> 5903(b)`)
    extra_pp_rows = [dict(r) for r in t49p_rows] + [
        {
            **next(r for r in t49p_rows if r["former_section"] == "508" and r["former_subsection"] == "(d)"),
            "new_subsection": "(a)",
        }
    ]
    try:
        verify_pinpoint_and_status_integrity(
            "usc-1994-title49-positivelaw-disposition.parquet",
            extra_pp_rows,
            expected_pinpoints=t49p_body_pinpoints,
            exact_pinpoints=True,
        )
    except ValueError as exc:
        results.append({"table": "usc-1994-title49-positivelaw-disposition.parquet", "mutation": "extra_pinpoint_508d_5903a", "caught": True, "error": str(exc)[:140]})
    else:
        raise SystemExit("SELF-TEST FAILED: planted extra pinpoint 508(d)->5903(a) was NOT caught!")

    # Planted wrong status on Title 49 positive-law (`335` mutated from `repealed` to `eliminated`)
    mutated_st = [dict(r) for r in t49p_rows]
    for r in mutated_st:
        if r["former_section"] == "335":
            r["status"] = "eliminated"
    try:
        verify_pinpoint_and_status_integrity(
            "usc-1994-title49-positivelaw-disposition.parquet",
            mutated_st,
            expected_statuses={(49, "335"): {"repealed"}},
        )
    except ValueError as exc:
        results.append({"table": "usc-1994-title49-positivelaw-disposition.parquet", "mutation": "wrong_status", "caught": True, "error": str(exc)[:140]})
    else:
        raise SystemExit("SELF-TEST FAILED: planted wrong status on 335 was NOT caught!")

    # Planted status flip on Title 10 (`3360` mutated from `see-reference` to `repealed`)
    mutated_t10 = [dict(r) for r in t10_rows]
    for r in mutated_t10:
        if r["former_section"] == "3360":
            r["status"] = "repealed"
    try:
        verify_pinpoint_and_status_integrity(
            "usc-1996-title10-ropma-disposition.parquet",
            mutated_t10,
            expected_statuses=t10_non_succ_statuses,
            exact_non_successor_statuses=True,
        )
    except ValueError as exc:
        results.append({"table": "usc-1996-title10-ropma-disposition.parquet", "mutation": "flip_3360_see_reference_to_repealed", "caught": True, "error": str(exc)[:140]})
    else:
        raise SystemExit("SELF-TEST FAILED: planted status flip on 10:3360 was NOT caught!")
    return results


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
        default=Path(__file__).resolve().parents[4] / "output" / "registry-real-data-sources",
    )
    ap.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    ap.add_argument("--self-test", action="store_true", help="plant one wrong successor per table and verify failure")
    args = ap.parse_args()

    ev_dir = args.evidence_dir.resolve()
    repo_root = Path(__file__).resolve().parents[4]
    pdfs: dict[str, Path] = {}
    for fname, (exp_bytes, exp_sha) in SOURCE_PINS.items():
        p = resolve_pdf(fname, args.pdf_dir, repo_root)
        verify_environment_and_pdf(p, exp_bytes, exp_sha)
        pdfs[fname] = p

    specs: list[tuple[str, set[Pair], set[Pair], int, dict[Pair, Pair], bool, set[Pair]]] = [
        (
            "usc-1996-title10-ropma-disposition.parquet",
            extract_title10_subtitle_e_pairs(pdfs["USCODE-1996-title10.pdf"]),
            load_parquet_pairs(ev_dir / "usc-1996-title10-ropma-disposition.parquet"),
            200,
            {},
            True,
            # Three forward `See section` pointers whose Subtitle E sections omit a PRIOR PROVISIONS block:
            {(10, "3843", 10, "14509"), (10, "3850", 10, "14514"), (10, "8850", 10, "14514")},
        ),
        (
            "usc-2017-title34-disposition.parquet",
            extract_title34_codification_pairs(pdfs["USCODE-2017-title34.pdf"]),
            load_parquet_pairs(ev_dir / "usc-2017-title34-disposition.parquet", include_notes=False),
            650,
            # Two verified OLRC print typos in USCODE-2017-title34.pdf front matter:
            # 1) p.8 right prints `42:13136f -> 34:40728` between `42:14136e` and `42:14137`; body §40728 prints `42:14136f`.
            # 2) p.5 left prints `42:3797ee-1 -> 34:16902` after `42:3797ee -> 34:10691` (34:16902 is absent); body §10692 (p.169 right) prints `42:3797ee-1`.
            {
                (42, "14136f", 34, "40728"): (42, "13136f", 34, "40728"),
                (42, "3797ee-1", 34, "10692"): (42, "3797ee-1", 34, "16902"),
            },
            True,
            # Two multi-destination sections whose secondary destination uses non-standard Codification wording:
            {(42, "3716", 34, "30502"), (42, "5611", 34, "20710")},
        ),
        (
            "usc-2011-title41-disposition.parquet",
            extract_hrn_pairs_colon(pdfs["USCODE-2011-title41.pdf"], 4, 41, {41}),
            load_parquet_pairs(ev_dir / "usc-2011-title41-disposition.parquet"),
            150,
            # p.1 right prints `46 to 48 -> 8502 to 8504`; body §8501(2) HRN also cites parenthetical words from `41:46(a)`.
            {(41, "46", 41, "8501"): (41, "46", 41, "8502")},
            True,
            # § 114 HRN cites `41:403(11)` via prose rather than the tabular Source column:
            {(41, "403", 41, "114")},
        ),
        (
            "usc-2010-title51-disposition.parquet",
            extract_hrn_pairs_usc(pdfs["USCODE-2010-title51.pdf"], 3, 51, {15, 42}),
            load_parquet_pairs(ev_dir / "usc-2010-title51-disposition.parquet"),
            180,
            {},
            True,
            set(),
        ),
        (
            "usc-2014-title54-disposition.parquet",
            extract_hrn_pairs_usc(pdfs["USCODE-2014-title54.pdf"], 10, 54, {16}),
            load_parquet_pairs(ev_dir / "usc-2014-title54-disposition.parquet"),
            280,
            # p.4 right prints `16 U.S.C. 458a -> 54 U.S.C. 104908` (absent); body §104905 HRN prints `16 U.S.C. 458a`.
            {(16, "458a", 54, "104905"): (16, "458a", 54, "104908")},
            True,
            set(),
        ),
        (
            "usc-1994-title49-positivelaw-disposition.parquet",
            extract_title49_positivelaw_body_pairs(pdfs["USCODE-1994-title49.pdf"], repo_root),
            load_parquet_pairs(ev_dir / "usc-1994-title49-positivelaw-disposition.parquet"),
            22,
            {},
            True,
            set(),
        ),
    ]

    summaries = [
        verify_pair_agreement(
            name,
            body_p,
            parq_p,
            min_body_pairs=min_c,
            known_publisher_typos=typos,
            strict_no_extra_on_covered_former=strict_extra,
            allowed_extra_pairs=allowed_extra,
        )
        for name, body_p, parq_p, min_c, typos, strict_extra, allowed_extra in specs
    ]

    # Row-level pinpoint & status integrity checks across all 6 tables
    t49p_rows = load_parquet_rows(ev_dir / "usc-1994-title49-positivelaw-disposition.parquet")
    t49p_body_pinpoints = extract_title49_positivelaw_body_pinpoints(pdfs["USCODE-1994-title49.pdf"], repo_root)
    verify_pinpoint_and_status_integrity(
        "usc-1994-title49-positivelaw-disposition.parquet",
        t49p_rows,
        expected_pinpoints=t49p_body_pinpoints,
        exact_pinpoints=True,
        forbidden_pinpoints={(49, "508", "(d)", None, 49, "5901", "(7)", "restated")},
        expected_statuses={(49, "335"): {"repealed"}, (49, "3102"): {"restated"}, (49, "501"): {"restated"}},
        exact_non_successor_statuses=True,
    )
    t10_rows = load_parquet_rows(ev_dir / "usc-1996-title10-ropma-disposition.parquet")
    t10_non_succ_statuses = extract_title10_non_successor_statuses(pdfs["USCODE-1996-title10.pdf"])
    verify_pinpoint_and_status_integrity(
        "usc-1996-title10-ropma-disposition.parquet",
        t10_rows,
        expected_pinpoints={
            (10, "1376", "(a)", None, 10, "12774", None, "restated"),
            (10, "3385", None, None, 10, "14308", "(f)", "restated"),
            (10, "6389", "(f)(3)", None, 10, "14705", None, "restated"),
        },
        forbidden_pinpoints={
            (10, "3385", None, None, 10, "14308", "(a)", "restated"),
            (10, "3385", None, None, 10, "14308", "(d)", "restated"),
        },
        expected_statuses=t10_non_succ_statuses,
        exact_non_successor_statuses=True,
    )
    verify_pinpoint_and_status_integrity(
        "usc-2011-title41-disposition.parquet",
        load_parquet_rows(ev_dir / "usc-2011-title41-disposition.parquet"),
        expected_pinpoints={(41, "422", "(g)", None, 41, "1502", None, "restated")},
        expected_statuses={(41, "20a"): {"repealed"}, (41, "20b"): {"repealed"}},
    )
    verify_pinpoint_and_status_integrity(
        "usc-2014-title54-disposition.parquet",
        load_parquet_rows(ev_dir / "usc-2014-title54-disposition.parquet"),
        expected_pinpoints={
            (16, "470h-2", "(k)", None, 54, "306113", None, "restated"),
            (16, "470h-2", "(l)", None, 54, "306114", None, "restated"),
            (16, "5952", "(7)(B)", None, 54, "101913", None, "restated"),
            (16, "5952", "(7)(D)", None, 54, "101913", None, "restated"),
        },
        expected_statuses={(16, "457"): {"see-reference"}, (16, "19bb"): {"repealed"}},
    )
    verify_pinpoint_and_status_integrity(
        "usc-2017-title34-disposition.parquet",
        load_parquet_rows(ev_dir / "usc-2017-title34-disposition.parquet"),
        expected_statuses={(42, "3797dd-1"): {"eliminated"}},
    )
    verify_pinpoint_and_status_integrity(
        "usc-2010-title51-disposition.parquet",
        load_parquet_rows(ev_dir / "usc-2010-title51-disposition.parquet"),
    )

    planted = (
        run_self_test(specs, t49p_rows, t49p_body_pinpoints, t10_rows, t10_non_succ_statuses)
        if args.self_test
        else []
    )

    report = {
        "pdftotext_version": PDFTOTEXT_VERSION,
        "tables_checked": len(summaries),
        "summaries": summaries,
        "planted_corruption_self_test": planted,
    }
    report_path = ev_dir / "crosscheck-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for s in summaries:
        print(
            f"{s['table']}: matched {s['body_note_pairs_matched']}/{s['body_note_pairs_extracted']} "
            f"body-note pairs (parquet restated pairs={s['parquet_restated_pairs']}, "
            f"known_publisher_typos={len(s['known_publisher_typos'])})"
        )
    if planted:
        print(f"planted corruption self-test: {len(planted)}/{len(planted)} caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
