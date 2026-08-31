"""Wave 5's anatomy: the 3,516 decomposed into named sub-shapes.

Waves 1-4 clustered the residue at seven coarse names ("prose/damage",
"bare numbers"). Wave 5 splits the two largest clusters into sub-shapes with
counts and specimens, because a named sub-cluster is a deliverable even where
nothing is recovered from it.

Run: ``uv run python research/evidence/malformed-identifier-census-2026-08-21/wave5_anatomy_probe.py``
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
TABLE = ROOT / "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"


def load():
    rows = pq.read_table(TABLE).to_pylist()
    failed = [r for r in rows if r["parse_status"] == "failed" and r["authority_type"] == "other"]
    return rows, failed


# --- sub-shape classifier -------------------------------------------------
#
# Ordered: the first matching rule names the row. Every rule is a *shape*
# statement about the text, never a recovery.

DATEISH = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
DATE_WORD = re.compile(rf"\b{MONTHS}\.?\s+\d{{1,2}},?\s+\d{{4}}\b", re.IGNORECASE)
NUM = r"\d{1,6}[A-Za-z]{0,3}(?:[-.]\d{1,5}[A-Za-z]?)?(?:\([^()]{1,12}\))*"
BARE_NUMS = re.compile(rf"^(?:[Ss]ecs?\.?\s+|[Ss]ections?\s+|§+\s*)?{NUM}"
                       rf"(?:\s*(?:,|and|&|or|through|to|;|-)\s*(?:[Ss]ecs?\.?\s+|§+\s*)?{NUM})*"
                       r"[\s.,;:]*$")
HAS_ALPHA_WORD = re.compile(r"[A-Za-z]{4,}")
ACTWORD = re.compile(r"\b(?:Act|Acts|Amendments?|Law|Code|Statute|Convention|Treaty|Agreement|Protocol|Plan|Order|Resolution)\b", re.IGNORECASE)
ABBREV = re.compile(r"\b[A-Z][A-Z0-9']{1,9}\b")
PL_LABEL = re.compile(r"\b(?:Pub(?:lic)?\.?\s*L(?:aw)?\.?|P\.?\s?L\.?)\b", re.IGNORECASE)
BILL = re.compile(r"\b(?:H\.?\s?R\.?|S\.?\s?J?\.?\s?Res\.?|H\.?\s?J?\.?\s?Res\.?|S\.)\s*\d", re.IGNORECASE)
USC_LABEL = re.compile(r"\bU\.?\s?S\.?\s?C\.?\b", re.IGNORECASE)
CFR_LABEL = re.compile(r"\bC\.?\s?F\.?\s?R\.?\b", re.IGNORECASE)
STAT_LABEL = re.compile(r"\bStat(?:\.|ute|utes)?\b", re.IGNORECASE)
FR_LABEL = re.compile(r"\bF\.?\s?R\.?\b|\bFed\.?\s?Reg\b", re.IGNORECASE)
DESIGNATOR_ONLY = re.compile(r"^(?:[Tt]itles?|[Ss]ubtitles?|[Cc]hapters?|[Pp]arts?|[Ss]ubparts?|[Dd]ivs?\.?|[Dd]ivisions?|[Ss]ubch\.?)\s+[IVXLCDM0-9A-Za-z\-]{1,12}[\s.,;]*$")
ANAPHORA = re.compile(r"\bthe\s+Act\b|\bsaid\s+Act\b|\bthis\s+Act\b|\bthat\s+Act\b", re.IGNORECASE)
COURT_RULE = re.compile(r"\bFed\.?\s?R\.?\s|\bRules?\s+of\s+(?:Civil|Criminal|Bankruptcy|Appellate)", re.IGNORECASE)
DC = re.compile(r"\bD\.?\s?C\.?\s+(?:Law|Code|Official|Register|Mun)|DCR\b|D\.C\. Council", re.IGNORECASE)
STATE_CODE = re.compile(r"\b(?:Ann\.?\s+Code|Rev\.?\s+Stat|Gen\.?\s+Laws|Comp\.?\s+Laws)\b", re.IGNORECASE)
OMB_CONTROL = re.compile(r"^\d{4}-\d{4}$")


def sub_shape(text: str) -> str:
    s = text.strip().strip('"“”‘’ ')
    low = s.lower()

    if not s:
        return "empty"
    if COURT_RULE.search(s):
        return "court-rule"
    if DC.search(s):
        return "dc-instrument"
    if STATE_CODE.search(s):
        return "state-code"

    bare = bool(BARE_NUMS.match(s))
    if bare:
        # split the bare-number family by what the number LOOKS like
        digits = re.findall(r"\d+", s)
        if OMB_CONTROL.match(s):
            return "bare:omb-control-shape"
        if re.match(r"^\s*(?:[Ss]ecs?\.?|[Ss]ections?|§+)\s", s):
            return "bare:marked-section"
        if len(digits) == 1:
            n = digits[0]
            if len(n) >= 4 and 1789 <= int(n) <= 2035:
                return "bare:year-shaped"
            return f"bare:single-number-{len(n)}digit"
        return "bare:multi-number"

    if DESIGNATOR_ONLY.match(s):
        return "designator-only"
    if ANAPHORA.search(s) and not ACTWORD.search(re.sub(r"\bthe\s+Act\b|\bsaid\s+Act\b|\bthis\s+Act\b|\bthat\s+Act\b", "", s, flags=re.IGNORECASE)):
        return "anaphoric-act"
    if DATEISH.search(s) or DATE_WORD.search(s):
        return "date-fragment"
    if BILL.search(s):
        return "bill-number"
    if PL_LABEL.search(s):
        return "pl-label"
    if USC_LABEL.search(s):
        return "usc-label"
    if CFR_LABEL.search(s):
        return "cfr-label"
    if STAT_LABEL.search(s):
        return "stat-label"
    if FR_LABEL.search(s) and re.search(r"\d", s):
        return "fr-label"
    if ACTWORD.search(s):
        return "act-prose"
    words = re.findall(r"[A-Za-z]{2,}", s)
    caps = ABBREV.findall(s)
    if caps and not [w for w in words if w.lower() not in {c.lower() for c in caps} and len(w) > 3]:
        return "abbreviation"
    if HAS_ALPHA_WORD.search(s):
        return "other-prose"
    return "residue"


def main() -> None:
    rows, failed = load()
    print(f"rows {len(rows)}  failed(other) {len(failed)}")

    tally = collections.Counter()
    distinct = collections.defaultdict(set)
    specimens = collections.defaultdict(collections.Counter)
    for r in failed:
        shape = sub_shape(r["authority_text"])
        tally[shape] += 1
        distinct[shape].add(r["authority_text"])
        specimens[shape][r["authority_text"]] += 1

    print("\n== sub-shapes ==")
    for shape, n in tally.most_common():
        print(f"{n:5d}  {len(distinct[shape]):4d} distinct  {shape}")
        for text, c in specimens[shape].most_common(6):
            print(f"          {c:4d}  {text!r}")

    # --- publication-date fence feasibility --------------------------------
    print("\n== edition span of failed rows ==")
    ed = collections.Counter(r["publication_id"] for r in failed)
    print("earliest", min(ed), "latest", max(ed), "spread", len(ed))


if __name__ == "__main__":
    main()
