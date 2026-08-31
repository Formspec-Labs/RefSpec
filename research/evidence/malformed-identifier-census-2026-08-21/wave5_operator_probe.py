"""Wave 5: candidate whole-value label repairs, measured against the grammar.

Wave 4's four label repairs (lowercase Stat, stray comma, stuttered "et",
dropped U) came from reading the residue's LABEL damage. This probe reads the
rest of it and measures each candidate the same way: apply the operator to the
failed pool, re-parse with the real grammar, and count only rows that go from
``other``/``failed`` to a typed citation whose numbers are in series.

Run: ``uv run python research/evidence/malformed-identifier-census-2026-08-21/wave5_operator_probe.py``
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
TABLE = ROOT / "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"

from refspec.registry.citation_grammar import parse_authority_citation  # noqa: E402

USC = r"\d{1,2}\s*U\.?\s?S\.?\s?C\.?"

#: (name, pattern, replacement). Each is whole-value anchored and names ONE
#: operation over ONE label.
CANDIDATES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "comma-after-usc-label",
        re.compile(rf"^({USC})\s*,\s*(?=[\ddc§as])", re.IGNORECASE),
        r"\1 ",
    ),
    (
        "space-inside-usc-label",
        re.compile(r"^(\d{1,2}\s*U\.?\s?S\.?\s?C)\s+\.\s*", re.IGNORECASE),
        r"\1. ",
    ),
    (
        "doubled-period-after-usc-label",
        re.compile(r"^(\d{1,2}\s*U\.?\s?S\.?\s?C)\.\.\s*", re.IGNORECASE),
        r"\1. ",
    ),
    (
        "stray-period-before-usc-label",
        re.compile(r"^(\d{1,2})\s*\.\s*(U\.?\s?S\.?\s?C)", re.IGNORECASE),
        r"\1 \2",
    ),
    (
        "stuttered-usc-label",
        re.compile(r"^(\d{1,2}\s*U\.?\s?S\.?\s?C\.?)\s+U\.?\s?S\.?\s?C\.?\s+", re.IGNORECASE),
        r"\1 ",
    ),
    (
        "stray-letter-before-title",
        re.compile(rf"^[A-Za-z](\d{{1,2}}\s*U\.?\s?S\.?\s?C\.?\s+\d)", re.IGNORECASE),
        r"\1",
    ),
    (
        "letter-o-for-zero-in-title",
        re.compile(r"^(\d)[oO](\s*U\.?\s?S\.?\s?C\.?\s+\d)", re.IGNORECASE),
        r"\g<1>0\2",
    ),
    (
        "unmatched-open-paren",
        re.compile(r"^([^()]*)\((?=[^()]*\([^()]*\)[^()]*$)", re.IGNORECASE),
        r"\1",
    ),
    (
        "parenthesised-whole-citation",
        re.compile(r"^([^()]*)\(((?:[^()]|\([^()]*\))*)\)\s*$"),
        r"\1\2",
    ),
    (
        "unmatched-close-paren",
        re.compile(r"^([^()]*)\)\s*$"),
        r"\1",
    ),
)


def readable(text: str) -> tuple[bool, str]:
    """Whether the grammar reads a typed citation out of the whole value."""

    citations = parse_authority_citation(text)
    kinds = {c.authority_type for c in citations}
    if kinds == {"other"} or kinds == {"unstated"}:
        return False, ""
    return True, ",".join(sorted(kinds))


def main() -> None:
    rows = pq.read_table(TABLE).to_pylist()
    failed = [r for r in rows if r["parse_status"] == "failed" and r["authority_type"] == "other"]
    by_text: dict[str, int] = collections.Counter(r["authority_text"] for r in failed)
    print(f"failed(other): {len(failed)} rows, {len(by_text)} distinct")

    claimed: set[str] = set()
    for name, pattern, replacement in CANDIDATES:
        wins: dict[str, tuple[str, str]] = {}
        for text in by_text:
            if text in claimed:
                continue
            repaired, count = pattern.subn(replacement, text, count=1)
            if not count or repaired == text:
                continue
            ok, kinds = readable(repaired)
            if ok:
                wins[text] = (repaired, kinds)
        rowcount = sum(by_text[t] for t in wins)
        print(f"\n== {name}: {rowcount} rows, {len(wins)} distinct ==")
        for text, (repaired, kinds) in sorted(wins.items(), key=lambda kv: -by_text[kv[0]])[:14]:
            print(f"   {by_text[text]:4d}  {text!r} -> {repaired!r}  [{kinds}]")
        claimed |= set(wins)

    print(f"\nTOTAL distinct claimed: {len(claimed)}, rows: {sum(by_text[t] for t in claimed)}")


if __name__ == "__main__":
    main()
