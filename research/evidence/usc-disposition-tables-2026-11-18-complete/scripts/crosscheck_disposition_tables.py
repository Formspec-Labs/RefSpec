#!/usr/bin/env python3
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


def load_parquet_pairs(parquet_path: Path) -> set[Pair]:
    tbl = pq.read_table(parquet_path, columns=["former_title", "former_section", "new_title", "new_section", "status"])
    pairs: set[Pair] = set()
    for ft, fs, nt, ns, st in zip(
        tbl["former_title"].to_pylist(),
        tbl["former_section"].to_pylist(),
        tbl["new_title"].to_pylist(),
        tbl["new_section"].to_pylist(),
        tbl["status"].to_pylist(),
        strict=True,
    ):
        if nt is not None and ns is not None and st in ("restated", "restated-as-note"):
            pairs.add((int(ft), str(fs), int(nt), str(ns)))
    return pairs


_HRN_TABLE_STOP = (
    r"(?:\n(?:In |The |Subsection |Subsections |Paragraph |Paragraphs |Clause |Subclause |Subparagraph "
    r"|Section \d|This section )|\n[A-Z][A-Z0-9 ,.'()-]{4,}\n|\Z)"
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
        m_hrn = re.search(rf"HISTORICAL AND REVISION NOTES\n(.*?){_HRN_TABLE_STOP}", blk, re.S)
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
        m_hrn = re.search(rf"HISTORICAL AND REVISION NOTES\n(.*?){_HRN_TABLE_STOP}", blk, re.S)
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
            re.S,
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
    # Also check which sections in Subtitles A–D are still live `§ <sec>.` so partial subsection amendments
    # out of live sections (`175, 517, 1376, 1401, 6389` — note `261` was replaced by a cross-reference stub)
    # are distinguished from repealed/renumbered sections.
    ad_body = read_body_raw(pdf, 14)
    sub_e_idx = ad_body.find("\nSubtitle E-Reserve Components\n")
    assert sub_e_idx > 0
    ad_only = ad_body[:sub_e_idx]
    sub_e = ad_body[sub_e_idx:]

    live_ad_non_stub: set[str] = set()
    for m_live in re.finditer(r"(?m)^§\s*(\d+[a-z]*)\.\s+([^\n]+)", ad_only):
        sec_num, heading = m_live.group(1), m_live.group(2)
        if not heading.startswith("Reference to chapter"):
            live_ad_non_stub.add(sec_num)

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
        if m_pp and "prior to repeal by Pub. L. 103-337" in m_pp.group(1):
            for m_cl in re.finditer(
                r"were contained in\s+(.*?)\s+of this title,?\s+prior to repeal by Pub\. L\. 103-337",
                m_pp.group(1),
            ):
                rhs = m_cl.group(1)
                if "note under section" in rhs:
                    continue
                rhs_clean = re.sub(r"\([0-9a-zA-Z]+\)", "", rhs)
                for mr in re.finditer(r"(\d+)\s+to\s+(\d+)", rhs_clean):
                    for k in range(int(mr.group(1)), int(mr.group(2)) + 1):
                        s_old = str(k)
                        if s_old not in live_ad_non_stub:
                            pairs.add((10, s_old, 10, new_sec))
                rhs_rest = re.sub(r"\d+\s+to\s+\d+", "", rhs_clean)
                for s_old in re.findall(rf"\b({_SEC})\b", rhs_rest):
                    if s_old not in live_ad_non_stub:
                        pairs.add((10, s_old, 10, new_sec))
    return pairs


def extract_title49_positivelaw_body_pairs(pdf: Path) -> set[Pair]:
    """Independently extract `(49, old_sec, 49, new_sec)` from statutory credits and HRNs in Title 49."""
    body = read_body_raw(pdf, 25)
    pairs: set[Pair] = set()
    for blk in re.split(r"(?m)^(?=§\d+[a-z]*\.)", body)[1:]:
        m_ns = re.match(r"^§(\d+[a-z]*)\.", blk)
        if not m_ns:
            continue
        new_sec = m_ns.group(1)
        clean = re.sub(r"\s+", " ", blk)
        # Statutory credit `Stat. \d+, § 310x; ... renumbered § 3150x ... Pub. L. 103-272`
        m_cred = re.search(
            rf"Stat\.\s+\d+,\s*§\s*(\d+[a-z]*)\s*;[^)]*?renumbered\s+§\s*{re.escape(new_sec)}\s+and\s+amended\s+Pub\.\s*L\.\s*103-272",
            clean,
        )
        if m_cred:
            pairs.add((49, m_cred.group(1), 49, new_sec))
        # HRNs for sections enacted by Pub. L. 103-272 §1 citing repealed positive-law `334` or `508`
        if re.search(r"\((?:Added )?Pub\.\s*L\.\s*103-272,\s*§\s*1\b", clean):
            m_hrn = re.search(rf"HISTORICAL AND REVISION NOTES\n(.*?){_HRN_TABLE_STOP}", blk, re.S)
            if m_hrn:
                for m_src in re.finditer(r"(?<!App\.:)\b49:(334|508)\b", m_hrn.group(1)):
                    pairs.add((49, m_src.group(1), 49, new_sec))
    return pairs


def verify_pair_agreement(
    name: str,
    body_pairs: set[Pair],
    parquet_pairs: set[Pair],
    *,
    min_body_pairs: int,
    known_publisher_typos: dict[Pair, Pair] | None = None,
) -> dict:
    typos = dict(known_publisher_typos or {})
    if len(body_pairs) < min_body_pairs:
        raise ValueError(
            f"{name}: body-note pair population too small ({len(body_pairs)} < {min_body_pairs})"
        )
    missing = sorted(body_pairs - parquet_pairs - set(typos))
    missing_typos_in_body = sorted(set(typos) - body_pairs)
    missing_typos_in_parquet = sorted(expected_printed for expected_printed in typos.values() if expected_printed not in parquet_pairs)
    if missing or missing_typos_in_body or missing_typos_in_parquet:
        raise ValueError(
            f"{name}: pair-level mismatch! missing_from_parquet={missing[:10]} "
            f"(count={len(missing)}), missing_typos_in_body={missing_typos_in_body}, "
            f"missing_typos_in_parquet={missing_typos_in_parquet}"
        )
    matched = len(body_pairs & parquet_pairs)
    return {
        "table": name,
        "parquet_restated_pairs": len(parquet_pairs),
        "body_note_pairs_extracted": len(body_pairs),
        "body_note_pairs_matched": matched,
        "known_publisher_typos": [
            {
                "body_note_pair": {"former_title": b[0], "former_section": b[1], "new_title": b[2], "new_section": b[3]},
                "printed_table_pair": {"former_title": p[0], "former_section": p[1], "new_title": p[2], "new_section": p[3]},
            }
            for b, p in sorted(typos.items())
        ],
    }


def run_self_test(specs: list[tuple[str, set[Pair], set[Pair], int, dict[Pair, Pair]]]) -> list[dict]:
    """Plant a wrong `new_section` on one matched pair (and any allowlisted typo pair) and prove failure."""
    results = []
    for name, body_pairs, parquet_pairs, min_cnt, typos in specs:
        victims = [sorted(body_pairs & parquet_pairs)[0], *sorted(typos.values())]
        for victim in victims:
            corrupted = (parquet_pairs - {victim}) | {(victim[0], victim[1], victim[2], "999999")}
            try:
                verify_pair_agreement(name, body_pairs, corrupted, min_body_pairs=min_cnt, known_publisher_typos=typos)
            except ValueError as exc:
                results.append({"table": name, "planted_victim": list(victim), "caught": True, "error": str(exc)[:140]})
            else:
                raise SystemExit(f"SELF-TEST FAILED on {name}: planted corruption on {victim} was NOT caught!")
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
        default=Path("/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/refspec-uscode-20261118"),
    )
    ap.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    ap.add_argument("--self-test", action="store_true", help="plant one wrong successor per table and verify failure")
    args = ap.parse_args()

    ev_dir = args.evidence_dir.resolve()
    repo_root = ev_dir.parents[2]
    pdfs: dict[str, Path] = {}
    for fname, (exp_bytes, exp_sha) in SOURCE_PINS.items():
        p = resolve_pdf(fname, args.pdf_dir, repo_root)
        verify_environment_and_pdf(p, exp_bytes, exp_sha)
        pdfs[fname] = p

    specs: list[tuple[str, set[Pair], set[Pair], int, dict[Pair, Pair]]] = [
        (
            "usc-1996-title10-ropma-disposition.parquet",
            extract_title10_subtitle_e_pairs(pdfs["USCODE-1996-title10.pdf"]),
            load_parquet_pairs(ev_dir / "usc-1996-title10-ropma-disposition.parquet"),
            200,
            {},
        ),
        (
            "usc-2017-title34-disposition.parquet",
            extract_title34_codification_pairs(pdfs["USCODE-2017-title34.pdf"]),
            load_parquet_pairs(ev_dir / "usc-2017-title34-disposition.parquet"),
            650,
            # Two verified OLRC print typos in USCODE-2017-title34.pdf front matter:
            # 1) p.4 right prints `42:13136f -> 34:40728` between `42:14136e` and `42:14137`; body §40728 prints `42:14136f`.
            # 2) p.5 left prints `42:3797ee-1 -> 34:16902` after `42:3797ee -> 34:10691` (34:16902 is absent); body §10692 prints `42:3797ee-1`.
            {
                (42, "14136f", 34, "40728"): (42, "13136f", 34, "40728"),
                (42, "3797ee-1", 34, "10692"): (42, "3797ee-1", 34, "16902"),
            },
        ),
        (
            "usc-2011-title41-disposition.parquet",
            extract_hrn_pairs_colon(pdfs["USCODE-2011-title41.pdf"], 4, 41, {41}),
            load_parquet_pairs(ev_dir / "usc-2011-title41-disposition.parquet"),
            150,
            # p.1 prints `46 to 48 -> 8502 to 8504`; body §8501(2) HRN also cites parenthetical words from `41:46(a)`.
            {(41, "46", 41, "8501"): (41, "46", 41, "8502")},
        ),
        (
            "usc-2010-title51-disposition.parquet",
            extract_hrn_pairs_usc(pdfs["USCODE-2010-title51.pdf"], 3, 51, {15, 42}),
            load_parquet_pairs(ev_dir / "usc-2010-title51-disposition.parquet"),
            180,
            {},
        ),
        (
            "usc-2014-title54-disposition.parquet",
            extract_hrn_pairs_usc(pdfs["USCODE-2014-title54.pdf"], 10, 54, {16}),
            load_parquet_pairs(ev_dir / "usc-2014-title54-disposition.parquet"),
            280,
            # p.4 right prints `16 U.S.C. 458a -> 54 U.S.C. 104908` (absent); body §104905 HRN prints `16 U.S.C. 458a`.
            {(16, "458a", 54, "104905"): (16, "458a", 54, "104908")},
        ),
        (
            "usc-1994-title49-positivelaw-disposition.parquet",
            extract_title49_positivelaw_body_pairs(pdfs["USCODE-1994-title49.pdf"]),
            load_parquet_pairs(ev_dir / "usc-1994-title49-positivelaw-disposition.parquet"),
            10,
            {},
        ),
    ]

    summaries = [
        verify_pair_agreement(name, body_p, parq_p, min_body_pairs=min_c, known_publisher_typos=typos)
        for name, body_p, parq_p, min_c, typos in specs
    ]
    planted = run_self_test(specs) if args.self_test else []

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
