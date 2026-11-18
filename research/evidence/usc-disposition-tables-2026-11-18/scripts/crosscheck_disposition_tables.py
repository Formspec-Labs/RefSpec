"""Independent cross-checks on the extracted Title 31 and Title 46 disposition tables.

Does NOT import ``extract_disposition_tables.py``. Reads only:
- the derived Parquet tables in this directory,
- the GovInfo source PDFs in ``--cache-dir`` (re-checked by sha256),
- the LoC 1982 Title 31 and 1988 Title 46 front-matter PDFs in ``--cache-dir`` (optional),
- the repository's pinned OLRC annual-sections Parquet (for 1994-2005 46 App. coverage).

Checks performed:
1. Title 31 Historical and Revision Notes in ``USCODE-1994-title31.pdf``:
   - Nonempty body anchor & minimum HRN token/pair populations (refuses empty PDF text),
   - Token coverage across all ``31:<sec>`` HRN references (requiring exact Parquet keys,
     including independently attested range members ``22a`` and ``324b-1``),
   - Tabular leader-dot HRN ``(former -> new)`` destination verification directly from PDF
     body notes against the derived Parquet,
   - Exact destination verification on independently sourced specimens (``31:483a -> 31:9701``,
     ``31:22a -> 31:1108``, ``31:324b-1 -> 31:5112``, ``31:725a -> Elim.``) plus 1982 LoC
     front-matter confirmation of ``483a -> 9701``.
2. Title 46 Historical and Revision Notes in ``USCODE-2006-title46.pdf``:
   - Nonempty body anchor & minimum HRN/OLRC populations (refuses empty PDF text),
   - Token coverage across ``46 App.:<sec>``, pre-codification ``46:<sec>`` (<2100), and
     OLRC 1994-2005 ``usc46a.htm`` (all 434 sections exact, including ``845a, 845b, 1183a``),
   - Tabular leader-dot HRN ``(former -> new)`` destination verification directly from PDF
     body notes against the derived Parquet,
   - Exact destination verification on independently sourced specimens (including respective
     pairs ``454->33:1233``, ``455->33:1234``, ``456->33:1235``, ``457->33:1236`` from
     ``1994usc33.htm``; editorial omission ``111 -> Elim.``; ``466c -> 15:1824a``;
     ``688 -> 46:30104, 30105``; ``1300 -> 46:30701 note``; ``72 -> 46:14503``;
     ``75 -> 46:14512``; ``845a/845b -> Rep.``; ``1183a -> 46:53101 note``).
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

#: Minimum independent population thresholds so empty/truncated PDF text fails loudly.
MIN_TITLE31_HRN_TOKENS = 500
MIN_TITLE31_ENACTED_SECS = 200
MIN_TITLE31_HRN_PAIRS = 250
MIN_TITLE46_APP_TOKENS = 250
MIN_TITLE46_PRE_TOKENS = 250
MIN_TITLE46_HRN_PAIRS = 180
MIN_OLRC_46A_SECTIONS = 400

#: Verified OLRC front-matter-vs-HRN divergences (front-matter table prints a
#: different destination than a body HRN table line; table bytes are preserved
#: faithfully rather than silently rewritten).
VERIFIED_TITLE31_HRN_DIVERGENCES: dict[tuple[str, str], str] = {
    ("665", "1349"): "USCODE-1994-title31.pdf p. 4 front-matter table prints 1549 (OLRC typo for 1349 in § 1349 HRN)",
    ("665", "1350"): "USCODE-1994-title31.pdf p. 4 front-matter table prints 1550 (OLRC typo for 1350 in § 1350 HRN)",
    ("1001", "321"): "§ 321(c) HRN cross-references 31:1001 beside 1002; p. 5 front-matter table maps 1001 -> 301",
}
VERIFIED_TITLE46_HRN_DIVERGENCES: dict[tuple[str, str], str] = {
    ("1244", "113"): "§ 113 HRN cites 46 App.:1244(a); p. 7 front-matter table maps 1244(a) -> 109",
}

#: Independently sourced exact-destination assertions checked against the Parquets
#: (former_section -> sorted list of (new_title, new_section, status)).
EXPECTED_TITLE31_SPECIMENS: dict[str, list[tuple[int | None, str | None, str]]] = {
    "22a": [(31, "1108", "restated")],
    "324b-1": [(31, "5112", "restated")],
    "483a": [(31, "9701", "restated")],
    "725a": [(None, None, "eliminated")],
}
EXPECTED_TITLE46_SPECIMENS: dict[str, list[tuple[int | None, str | None, str]]] = {
    "72": [(46, "14503", "restated")],
    "75": [(46, "14512", "restated")],
    "111": [(None, None, "eliminated")],
    "454": [(33, "1233", "restated")],
    "455": [(33, "1234", "restated")],
    "456": [(33, "1235", "restated")],
    "457": [(33, "1236", "restated")],
    "466c": [(15, "1824a", "restated")],
    "688": [(46, "30104", "restated"), (46, "30105", "restated")],
    "845a": [(None, None, "repealed")],
    "845b": [(None, None, "repealed")],
    "1183a": [(46, "53101", "restated-as-note")],
    "1300": [(46, "30701", "restated-as-note")],
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


def _body_after(full_txt: str, anchor: str, label: str) -> str:
    idx = full_txt.find(anchor)
    if idx < 0:
        raise SystemExit(f"{label}: body anchor {anchor!r} not found in extracted PDF text")
    return full_txt[idx:]


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
    only_eliminated = sum(1 for st in by_sec.values() if st == {"eliminated"})
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
        "former_sections_only_eliminated": only_eliminated,
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
                # Ascending range inside an HRN table (e.g. 31:240-243)
                if lo.isdigit() and hi.isdigit() and int(hi) - int(lo) <= 60:
                    out.update(str(n) for n in range(int(lo), int(hi) + 1))
                else:
                    out.add(lo)
                    out.add(hi)
                continue
        out.add(tok)
    return out


def _extract_hrn_leader_pairs(body: str, prefix_re: str) -> set[tuple[str, str]]:
    """Extract independent ``(former_section, new_section)`` pairs from tabular HRN lines."""

    pat = re.compile(
        r"^\s*(\d+[a-z]?)(?:\([^)]+\))*\s+\.{2,}\s+" + prefix_re + r"(\d+[a-z]?(?:-\d+[a-z]?)?)",
        re.MULTILINE,
    )
    pairs: set[tuple[str, str]] = set()
    for m in pat.finditer(body):
        new_sec, former = m.group(1).lower(), m.group(2).lower()
        if "-" in former:
            lo, _, hi = former.partition("-")
            m_lo, m_hi = _LEADING_DIGITS.match(lo), _LEADING_DIGITS.match(hi)
            if m_lo and m_hi and int(m_hi.group(1)) >= int(m_lo.group(1)):
                # Ascending range on an HRN line; skip composite range pair check here
                continue
        pairs.add((former, new_sec))
    return pairs


def _verify_hrn_pairs(
    pairs: set[tuple[str, str]],
    rows: list[dict],
    expected_title: int,
    verified_divergences: dict[tuple[str, str], str],
) -> dict:
    """Compare independently extracted HRN ``(former -> new)`` pairs against the Parquet."""

    pq_map: dict[str, set[str]] = collections.defaultdict(set)
    for r in rows:
        if r["new_title"] == expected_title and r["new_section"]:
            pq_map[r["former_section"].lower()].add(r["new_section"].lower())
    matched = 0
    documented: dict[str, str] = {}
    mismatched: list[dict] = []
    for former, new_sec in sorted(pairs):
        if new_sec in pq_map.get(former, set()):
            matched += 1
        elif (former, new_sec) in verified_divergences:
            documented[f"{former}->{new_sec}"] = verified_divergences[(former, new_sec)]
        else:
            mismatched.append(
                {
                    "former_section": former,
                    "hrn_new_section": new_sec,
                    "parquet_destinations": sorted(pq_map.get(former, set())),
                }
            )
    return {
        "total_leader_pairs": len(pairs),
        "matched_exact": matched,
        "verified_olrc_divergences": documented,
        "unexpected_mismatches": mismatched,
    }


def _verify_specimens(
    rows: list[dict], expected: dict[str, list[tuple[int | None, str | None, str]]]
) -> dict:
    """Verify exact destination sets against independently sourced primary citations."""

    by_sec: dict[str, set[tuple[int | None, str | None, str]]] = collections.defaultdict(set)
    for r in rows:
        by_sec[r["former_section"].lower()].add((r["new_title"], r["new_section"], r["status"]))
    mismatches: list[dict] = []
    verified: dict[str, list[list]] = {}
    for sec, want in sorted(expected.items()):
        want_sorted = sorted(want, key=lambda item: (item[0] or 0, item[1] or "", item[2]))
        obs_sorted = sorted(by_sec.get(sec.lower(), set()), key=lambda item: (item[0] or 0, item[1] or "", item[2]))
        verified[sec] = [list(item) for item in obs_sorted]
        if obs_sorted != want_sorted:
            mismatches.append(
                {
                    "former_section": sec,
                    "expected": [list(item) for item in want_sorted],
                    "observed": [list(item) for item in obs_sorted],
                }
            )
    return {
        "checked_count": len(expected),
        "verified_destinations": verified,
        "mismatches": mismatches,
    }


def check_title31(parquet_path: Path, pdf_path: Path, loc_1982_pdf: Path | None) -> dict:
    _verify_pdf(pdf_path, *EXPECTED_PDFS["USCODE-1994-title31.pdf"])
    rows = pq.read_table(parquet_path).to_pylist()
    table_secs = {r["former_section"].lower() for r in rows}

    full_txt = _pdftotext(pdf_path)
    body = _body_after(full_txt, "SUBTITLE I-GENERAL", "USCODE-1994-title31.pdf")
    all_hrn = _extract_hrn_source_tokens(body, r"\b31:")
    enacted_secs = set(re.findall(r"^§\s*(\d+[a-z]?)\.", body, re.MULTILINE))
    if len(all_hrn) < MIN_TITLE31_HRN_TOKENS:
        raise SystemExit(f"Title 31 HRN token count too small: {len(all_hrn)} < {MIN_TITLE31_HRN_TOKENS}")
    if len(enacted_secs) < MIN_TITLE31_ENACTED_SECS:
        raise SystemExit(f"Title 31 enacted section heading count too small: {len(enacted_secs)} < {MIN_TITLE31_ENACTED_SECS}")

    in_table_exact = sorted(t for t in all_hrn if t.lower() in table_secs)
    not_exact = sorted(t for t in all_hrn if t.lower() not in table_secs)
    post_1982_revised = []
    truly_missing = []
    for tok in not_exact:
        if tok in enacted_secs:
            post_1982_revised.append(tok)
        else:
            truly_missing.append(tok)

    hrn_pairs = _extract_hrn_leader_pairs(body, r"31:")
    if len(hrn_pairs) < MIN_TITLE31_HRN_PAIRS:
        raise SystemExit(f"Title 31 HRN leader-pair count too small: {len(hrn_pairs)} < {MIN_TITLE31_HRN_PAIRS}")
    pair_check = _verify_hrn_pairs(hrn_pairs, rows, 31, VERIFIED_TITLE31_HRN_DIVERGENCES)
    specimen_check = _verify_specimens(rows, EXPECTED_TITLE31_SPECIMENS)

    # Confirm 31:483a -> 9701 independently in § 9701 HRN and 1982 LoC front matter
    s9701_match = re.search(r"§\s*9701\.[\s\S]{0,1800}", body)
    hrn_483a_confirmed = bool(s9701_match and "31:483a" in s9701_match.group(0))
    table_483a = [
        [r["former_text"], r["new_title"], r["new_section"], r["status"]]
        for r in rows
        if r["former_section"] == "483a"
    ]
    if not hrn_483a_confirmed:
        raise SystemExit("Title 31 § 9701 HRN did not confirm 31:483a")
    if table_483a != [["483a", 31, "9701", "restated"]]:
        raise SystemExit(f"Title 31 483a destination mismatch: {table_483a!r}")

    loc_check = None
    if loc_1982_pdf and loc_1982_pdf.exists():
        loc_txt = _pdftotext(loc_1982_pdf)
        loc_check = {
            "file": loc_1982_pdf.name,
            "sha256": hashlib.sha256(loc_1982_pdf.read_bytes()).hexdigest(),
            "bytes": loc_1982_pdf.stat().st_size,
            "contains_483a_and_9701": ("483a" in loc_txt and "9701" in loc_txt),
        }
        if not loc_check["contains_483a_and_9701"]:
            raise SystemExit("1982 LoC Title 31 PDF failed 483a/9701 confirmation")

    p2_left_rows = len({(r["former_text"], r["new_text"]) for r in rows if r["page"] == 2 and r["column"] == "left"})

    return {
        "stats": _table_stats(rows, 31),
        "hrn_crosscheck": {
            "total_31_tokens_in_body": len(all_hrn),
            "exact_in_table": len(in_table_exact),
            "post_1982_revised_title31_self_refs": post_1982_revised,
            "truly_missing": truly_missing,
        },
        "hrn_destination_pairs": pair_check,
        "independent_specimens": specimen_check,
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

    full_txt = _pdftotext(pdf_path)
    body = _body_after(full_txt, "Subtitle I-General", "USCODE-2006-title46.pdf")

    # 1. 46 App.:<sec> HRN tokens
    hrn_app = _extract_hrn_source_tokens(body, r"\b46\s+App\.:")
    if len(hrn_app) < MIN_TITLE46_APP_TOKENS:
        raise SystemExit(f"Title 46 App HRN token count too small: {len(hrn_app)} < {MIN_TITLE46_APP_TOKENS}")
    app_missing = sorted(t for t in hrn_app if t.lower() not in table_secs)

    # 2. Pre-codification 46:<sec> HRN tokens (< 2100; >= 2100 are enacted positive-law sections)
    hrn_plain_all = _extract_hrn_source_tokens(body, r"\b46:")
    hrn_plain_pre = sorted(t for t in hrn_plain_all if int(_LEADING_DIGITS.match(t).group(1)) < 2100)
    if len(hrn_plain_pre) < MIN_TITLE46_PRE_TOKENS:
        raise SystemExit(
            f"Title 46 pre-codification HRN token count too small: {len(hrn_plain_pre)} < {MIN_TITLE46_PRE_TOKENS}"
        )
    plain_not_exact = sorted(t for t in hrn_plain_pre if t.lower() not in table_secs)
    plain_publisher_typos = {}
    plain_truly_missing = []
    for tok in plain_not_exact:
        if tok == "525h" and "526h" in table_secs:
            plain_publisher_typos[tok] = "OLRC printed HRN typo in § 4103 for 46:526h (table maps 526h -> 4103)"
        else:
            plain_truly_missing.append(tok)

    # 3. Independent tabular HRN (46 App.:<former> -> <new>) pair check
    hrn_pairs = _extract_hrn_leader_pairs(body, r"46\s+App\.:")
    if len(hrn_pairs) < MIN_TITLE46_HRN_PAIRS:
        raise SystemExit(f"Title 46 App HRN leader-pair count too small: {len(hrn_pairs)} < {MIN_TITLE46_HRN_PAIRS}")
    pair_check = _verify_hrn_pairs(hrn_pairs, rows, 46, VERIFIED_TITLE46_HRN_DIVERGENCES)

    # 4. OLRC 1994-2005 annual archive 46 App. sections (all 434 must match exact keys)
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
    if len(olrc_46a) < MIN_OLRC_46A_SECTIONS:
        raise SystemExit(f"OLRC 46 App section count too small: {len(olrc_46a)} < {MIN_OLRC_46A_SECTIONS}")
    olrc_missing = sorted(s for s in olrc_46a if s not in table_secs)

    # 5. Independently sourced destination assertions (including 454-457 respective pairs & § 111 Elim.)
    specimen_check = _verify_specimens(rows, EXPECTED_TITLE46_SPECIMENS)

    # 6. 1988 LoC Title 46 front-matter confirmation
    loc_check = None
    if loc_1988_pdf and loc_1988_pdf.exists():
        loc_txt = _pdftotext(loc_1988_pdf)
        loc_check = {
            "file": loc_1988_pdf.name,
            "sha256": hashlib.sha256(loc_1988_pdf.read_bytes()).hexdigest(),
            "bytes": loc_1988_pdf.stat().st_size,
            "notes_transfer_to_46_appendix": "Former sections of Title 46 that are not included" in loc_txt,
        }
        if not loc_check["notes_transfer_to_46_appendix"]:
            raise SystemExit("1988 LoC Title 46 PDF missing transfer-to-Appendix note")

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
            "verified_olrc_hrn_typos": plain_publisher_typos,
            "truly_missing": plain_truly_missing,
        },
        "hrn_destination_pairs": pair_check,
        "olrc_1994_2005_46_app_crosscheck": {
            "total_olrc_46a_sections": len(olrc_46a),
            "exact_in_table": len(olrc_46a) - len(olrc_missing),
            "missing": olrc_missing,
        },
        "independent_specimens": specimen_check,
        "loc_1988_check": loc_check,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact-dir", type=Path, required=True)
    ap.add_argument("--cache-dir", type=Path, required=True)
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

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

    errors: list[str] = []
    if report["title_31"]["hrn_crosscheck"]["truly_missing"]:
        errors.append(f"Title 31 HRN truly missing: {report['title_31']['hrn_crosscheck']['truly_missing']}")
    if report["title_31"]["hrn_destination_pairs"]["unexpected_mismatches"]:
        errors.append(
            f"Title 31 HRN pair mismatches: {report['title_31']['hrn_destination_pairs']['unexpected_mismatches']}"
        )
    if report["title_31"]["independent_specimens"]["mismatches"]:
        errors.append(
            f"Title 31 specimen mismatches: {report['title_31']['independent_specimens']['mismatches']}"
        )
    if report["title_46"]["hrn_46_app_crosscheck"]["missing"]:
        errors.append(f"Title 46 App HRN missing: {report['title_46']['hrn_46_app_crosscheck']['missing']}")
    if report["title_46"]["hrn_46_pre_codification_crosscheck"]["truly_missing"]:
        errors.append(
            "Title 46 pre-codification HRN missing: "
            f"{report['title_46']['hrn_46_pre_codification_crosscheck']['truly_missing']}"
        )
    if report["title_46"]["hrn_destination_pairs"]["unexpected_mismatches"]:
        errors.append(
            f"Title 46 HRN pair mismatches: {report['title_46']['hrn_destination_pairs']['unexpected_mismatches']}"
        )
    if report["title_46"]["olrc_1994_2005_46_app_crosscheck"]["missing"]:
        errors.append(f"OLRC 46 App missing: {report['title_46']['olrc_1994_2005_46_app_crosscheck']['missing']}")
    if report["title_46"]["independent_specimens"]["mismatches"]:
        errors.append(
            f"Title 46 specimen mismatches: {report['title_46']['independent_specimens']['mismatches']}"
        )
    if errors:
        raise SystemExit("; ".join(errors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
