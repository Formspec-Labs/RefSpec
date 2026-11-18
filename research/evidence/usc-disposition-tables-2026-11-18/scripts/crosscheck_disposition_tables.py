"""Independent cross-checks on the extracted Title 31 and Title 46 disposition tables.

Does NOT import ``extract_disposition_tables.py``. Reads only:
- the derived Parquet tables in this directory,
- the GovInfo source PDFs in ``--cache-dir`` (re-checked by sha256),
- the LoC 1982 Title 31 and 1988 Title 46 front-matter PDFs in ``--cache-dir`` (optional),
- the repository's pinned OLRC annual-sections Parquet (for 1994-2005 46 App. coverage).

Checks performed:
1. Title 31 Historical and Revision Notes (``31:<sec>`` in ``USCODE-1994-title31.pdf``)
   against ``usc-1994-title31-disposition.parquet``, plus 1982 LoC spot verification of
   ``31 U.S.C. 483a -> 9701`` and naive ``-layout`` line-count check on page 2 left.
2. Title 46 Historical and Revision Notes (``46 App.:<sec>`` and pre-codification
   ``46:<sec>`` in ``USCODE-2006-title46.pdf``), OLRC 1994-2005 ``usc46a.htm``
   (434 distinct sections), and 1988 Title 46 LoC spot mappings against
   ``usc-2006-title46-disposition.parquet``, plus naive ``-layout`` check on page 3 left.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq

_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))
_LEADING_DIGITS = re.compile(r"^(\d+)(.*)$")

EXPECTED_PDFS = {
    "USCODE-1994-title31.pdf": (
        "3b319dc182915b409d01c26d5fe46326e0416f5e725aa556738d17ba60340f0a",
        2_088_477,
    ),
    "USCODE-2006-title46.pdf": (
        "6bda1578ab30e947d3f7e746bacd53048a197ef80c946f0f7300276c97a5887d",
        2_449_872,
    ),
}


def _sec_key(sec: str) -> tuple[int, str]:
    m = _LEADING_DIGITS.match(sec.lower())
    assert m is not None, sec
    return (int(m.group(1)), m.group(2))


def _verify_pdf(path: Path, expected_sha: str, expected_bytes: int) -> None:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if len(raw) != expected_bytes or sha != expected_sha:
        raise SystemExit(f"{path.name} drifted: expected {expected_sha} ({expected_bytes}B), got {sha} ({len(raw)}B)")


def _pdftotext(pdf: Path, *extra: str) -> str:
    return subprocess.run(
        ["pdftotext", *extra, str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout.translate(_DASHES)


def _printed_ranges(rows: list[dict]) -> list[tuple[tuple[int, str], tuple[int, str], str]]:
    """Every multi-section printed range in ``former_text``, as (lo_key, hi_key, former_text)."""

    spans: list[tuple[tuple[int, str], tuple[int, str], str]] = []
    seen: set[str] = set()
    for r in rows:
        ft = r["former_text"]
        if ft in seen:
            continue
        seen.add(ft)
        head = ft.split("(")[0].strip()
        for piece in [p.strip() for p in head.split(",") if p.strip()]:
            if " to " in piece:
                lo, _, hi = piece.partition(" to ")
            elif "-" in piece:
                lo, _, hi = piece.partition("-")
            else:
                continue
            lo, hi = lo.strip(), hi.strip()
            if _LEADING_DIGITS.match(lo) and _LEADING_DIGITS.match(hi):
                lk, hk = _sec_key(lo), _sec_key(hi)
                if hk >= lk:
                    spans.append((lk, hk, ft))
    return spans


def _in_printed_range(token: str, spans: list[tuple[tuple[int, str], tuple[int, str], str]]) -> str | None:
    key = _sec_key(token)
    for lo, hi, ft in spans:
        if lo <= key <= hi:
            return ft
    return None


def _table_stats(rows: list[dict], former_title: int) -> dict:
    entries = {(r["page"], r["column"], r["former_text"], r["new_text"]) for r in rows}
    by_sec: dict[str, set[str]] = collections.defaultdict(set)
    by_sec_count: collections.Counter[str] = collections.Counter()
    outside_title: collections.Counter[int] = collections.Counter()
    for r in rows:
        sec = r["former_section"].lower()
        by_sec[sec].add(r["status"])
        by_sec_count[sec] += 1
        if r["new_title"] is not None and r["new_title"] != former_title:
            outside_title[r["new_title"]] += 1
    statuses = dict(collections.Counter(r["status"] for r in rows))
    only_repealed = sum(1 for st in by_sec.values() if st == {"repealed"})
    both_succ_and_rep = sum(
        1 for st in by_sec.values() if (st & {"restated", "restated-as-note"}) and ("repealed" in st)
    )
    return {
        "printed_entries": len(entries),
        "emitted_rows": len(rows),
        "distinct_former_sections": len(by_sec),
        "distinct_former_section_subsection": len({(r["former_section"], r["former_subsection"]) for r in rows}),
        "distinct_successors": len(
            {(r["new_title"], r["new_section"]) for r in rows if r["new_title"] is not None and r["new_section"]}
        ),
        "former_sections_with_multiple_rows": sum(1 for c in by_sec_count.values() if c > 1),
        "statuses": statuses,
        "former_sections_only_repealed": only_repealed,
        "former_sections_with_successor_and_repealed": both_succ_and_rep,
        "successors_outside_title": dict(sorted(outside_title.items())),
        "pages": sorted({r["page"] for r in rows}),
    }


def _extract_hrn_source_tokens(body: str, prefix_re: str) -> set[str]:
    """Extract section tokens from Historical and Revision Notes tables."""

    raw = set(re.findall(prefix_re + r"(\d+[a-z]?(?:-\d+[a-z]?)?)", body))
    out: set[str] = set()
    for tok in raw:
        if "-" in tok:
            lo, _, hi = tok.partition("-")
            m_lo, m_hi = _LEADING_DIGITS.match(lo), _LEADING_DIGITS.match(hi)
            assert m_lo and m_hi
            if int(m_hi.group(1)) >= int(m_lo.group(1)):
                # It is an ascending range inside an HRN table (e.g. 31:240-243)
                if lo.isdigit() and hi.isdigit() and int(hi) - int(lo) <= 60:
                    out.update(str(n) for n in range(int(lo), int(hi) + 1))
                else:
                    out.add(lo)
                    out.add(hi)
                continue
        out.add(tok)
    return out


def check_title31(parquet_path: Path, pdf_path: Path, loc_1982_pdf: Path | None) -> dict:
    _verify_pdf(pdf_path, *EXPECTED_PDFS["USCODE-1994-title31.pdf"])
    rows = pq.read_table(parquet_path).to_pylist()
    table_secs = {r["former_section"].lower() for r in rows}
    spans = _printed_ranges(rows)

    full_txt = _pdftotext(pdf_path)
    body = full_txt[full_txt.find("SUBTITLE I-GENERAL") :]
    # Extract all 31:<sec> references in body, then split pre-1982 former sections
    # (section number <= 1806, or cited in original 1982 HRN) from post-1982
    # positive-law sections (the revised Title 31 enacted by Pub. L. 97-258 itself).
    all_hrn = _extract_hrn_source_tokens(body, r"\b31:")
    # Revised Title 31 sections created in 1982 (e.g. 1305, 3302, 5112, 6501, 9101)
    # appear in 1983/1984 improvement notes ("1983 ACT This amends 31:6501(1)(B)...").
    enacted_secs = set(re.findall(r"^§\s*(\d+[a-z]?)\.", body, re.MULTILINE))
    in_table_exact = sorted(t for t in all_hrn if t.lower() in table_secs)
    not_exact = sorted(t for t in all_hrn if t.lower() not in table_secs)
    in_printed_range = {}
    post_1982_revised = []
    truly_missing = []
    for tok in not_exact:
        covered = _in_printed_range(tok, spans)
        if covered is not None:
            in_printed_range[tok] = covered
        elif tok in enacted_secs:
            post_1982_revised.append(tok)
        else:
            truly_missing.append(tok)

    # Verify 31 U.S.C. 483a -> 9701 in BOTH 1994 § 9701 HRN and 1982 LoC front matter
    s9701_match = re.search(r"§\s*9701\.[\s\S]{0,1800}", body)
    hrn_483a_confirmed = bool(s9701_match and "31:483a" in s9701_match.group(0))
    table_483a = [(r["former_text"], r["new_title"], r["new_section"], r["status"]) for r in rows if r["former_section"] == "483a"]

    loc_check = None
    if loc_1982_pdf and loc_1982_pdf.exists():
        loc_txt = _pdftotext(loc_1982_pdf)
        loc_check = {
            "file": loc_1982_pdf.name,
            "sha256": hashlib.sha256(loc_1982_pdf.read_bytes()).hexdigest(),
            "bytes": loc_1982_pdf.stat().st_size,
            "contains_483a_and_9701": ("483a" in loc_txt and "9701" in loc_txt),
        }

    # Naive -layout spot check on page 2 left (former entries vs leader lines)
    p2_left_rows = len({(r["former_text"], r["new_text"]) for r in rows if r["page"] == 2 and r["column"] == "left"})

    return {
        "stats": _table_stats(rows, 31),
        "hrn_crosscheck": {
            "total_31_tokens_in_body": len(all_hrn),
            "exact_in_table": len(in_table_exact),
            "covered_by_printed_range": in_printed_range,
            "post_1982_revised_title31_self_refs": post_1982_revised,
            "truly_missing": truly_missing,
        },
        "specimen_483a": {
            "table_rows": table_483a,
            "confirmed_in_1994_s9701_hrn": hrn_483a_confirmed,
            "loc_1982_check": loc_check,
        },
        "page2_left_entries": p2_left_rows,
    }


def check_title46(
    parquet_path: Path, pdf_path: Path, olrc_annual_parquet: Path, loc_1988_pdf: Path | None
) -> dict:
    _verify_pdf(pdf_path, *EXPECTED_PDFS["USCODE-2006-title46.pdf"])
    rows = pq.read_table(parquet_path).to_pylist()
    table_secs = {r["former_section"].lower() for r in rows}
    spans = _printed_ranges(rows)

    full_txt = _pdftotext(pdf_path)
    body = full_txt[full_txt.find("Subtitle I-General") :]

    # 1. 46 App.:<sec> HRN tokens
    hrn_app = _extract_hrn_source_tokens(body, r"\b46\s+App\.:")
    app_missing = sorted(t for t in hrn_app if t.lower() not in table_secs)

    # 2. Pre-codification 46:<sec> HRN tokens (< 2100; >= 2100 are enacted positive-law sections)
    hrn_plain_all = _extract_hrn_source_tokens(body, r"\b46:")
    hrn_plain_pre = sorted(t for t in hrn_plain_all if int(_LEADING_DIGITS.match(t).group(1)) < 2100)
    plain_not_exact = sorted(t for t in hrn_plain_pre if t.lower() not in table_secs)
    plain_in_range = {}
    plain_publisher_typos = {}
    plain_truly_missing = []
    for tok in plain_not_exact:
        covered = _in_printed_range(tok, spans)
        if covered is not None:
            plain_in_range[tok] = covered
        elif tok == "525h" and "526h" in table_secs:
            # OLRC's printed HRN for 46 U.S.C. § 4103 prints "46:525h" (a single-digit
            # typo for 46:526h, Motorboat Act of 1940 § 9, which the table maps to 4103).
            plain_publisher_typos[tok] = "OLRC printed HRN typo in § 4103 for 46:526h (table maps 526h -> 4103)"
        else:
            plain_truly_missing.append(tok)

    # 3. OLRC 1994-2005 annual archive 46 App. sections
    ann = pq.read_table(olrc_annual_parquet)
    olrc_46a = {
        s.strip().lower().translate(_DASHES)
        for t, a, s in zip(
            ann.column("title").to_pylist(),
            ann.column("appendix").to_pylist(),
            ann.column("section").to_pylist(),
            strict=True,
        )
        if t == 46 and a
    }
    olrc_not_exact = sorted(s for s in olrc_46a if s not in table_secs)
    olrc_in_range = {}
    olrc_truly_missing = []
    for tok in olrc_not_exact:
        covered = _in_printed_range(tok, spans)
        if covered is not None:
            olrc_in_range[tok] = covered
        else:
            olrc_truly_missing.append(tok)

    # 4. 1988 LoC Title 46 front-matter cross-check (Pub. L. 98-89..100-710)
    loc_check = None
    if loc_1988_pdf and loc_1988_pdf.exists():
        loc_txt = _pdftotext(loc_1988_pdf)
        spot_sections = ["71", "72", "75", "391a", "688", "466c", "1300"]
        table_spots = {
            s: sorted(
                {(r["new_title"], r["new_section"], r["status"]) for r in rows if r["former_section"] == s},
                key=lambda item: (item[0] or 0, item[1] or "", item[2]),
            )
            for s in spot_sections
        }
        loc_check = {
            "file": loc_1988_pdf.name,
            "sha256": hashlib.sha256(loc_1988_pdf.read_bytes()).hexdigest(),
            "bytes": loc_1988_pdf.stat().st_size,
            "notes_transfer_to_46_appendix": "Former sections of Title 46 that are not included" in loc_txt,
            "spot_checks_in_2006_table": table_spots,
        }

    return {
        "stats": _table_stats(rows, 46),
        "hrn_46_app_crosscheck": {
            "total_tokens": len(hrn_app),
            "exact_in_table": len(hrn_app) - len(app_missing),
            "missing": app_missing,
        },
        "hrn_46_pre_codification_crosscheck": {
            "total_tokens_under_2100": len(hrn_plain_pre),
            "exact_in_table": len(hrn_plain_pre) - len(plain_not_exact),
            "covered_by_printed_range": plain_in_range,
            "verified_olrc_hrn_typos": plain_publisher_typos,
            "truly_missing": plain_truly_missing,
        },
        "olrc_1994_2005_46_app_crosscheck": {
            "total_olrc_46a_sections": len(olrc_46a),
            "exact_in_table": len(olrc_46a) - len(olrc_not_exact),
            "covered_by_printed_range": olrc_in_range,
            "truly_missing": olrc_truly_missing,
        },
        "loc_1988_check": loc_check,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact-dir", type=Path, required=True)
    ap.add_argument("--cache-dir", type=Path, required=True)
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    report = {
        "title_31": check_title31(
            args.artifact_dir / "usc-1994-title31-disposition.parquet",
            args.cache_dir / "USCODE-1994-title31.pdf",
            args.cache_dir / "uscode1982-013031001.pdf",
        ),
        "title_46": check_title46(
            args.artifact_dir / "usc-2006-title46-disposition.parquet",
            args.cache_dir / "USCODE-2006-title46.pdf",
            args.repo_root
            / "research/evidence/usc-section-oracle-2026-08-24/usc-oracle-annual-sections.parquet",
            args.cache_dir / "uscode1988-018046000.pdf",
        ),
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    if report["title_31"]["hrn_crosscheck"]["truly_missing"]:
        raise SystemExit(f"Title 31 HRN truly missing: {report['title_31']['hrn_crosscheck']['truly_missing']}")
    if report["title_46"]["hrn_46_app_crosscheck"]["missing"]:
        raise SystemExit(f"Title 46 App HRN missing: {report['title_46']['hrn_46_app_crosscheck']['missing']}")
    if report["title_46"]["hrn_46_pre_codification_crosscheck"]["truly_missing"]:
        raise SystemExit(
            "Title 46 pre-codification HRN missing: "
            f"{report['title_46']['hrn_46_pre_codification_crosscheck']['truly_missing']}"
        )
    if report["title_46"]["olrc_1994_2005_46_app_crosscheck"]["truly_missing"]:
        raise SystemExit(
            f"OLRC 46 App truly missing: {report['title_46']['olrc_1994_2005_46_app_crosscheck']['truly_missing']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
