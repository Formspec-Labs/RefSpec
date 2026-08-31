"""H2: carry the last-stated U.S.C. title across sibling boxes, oracle-gated."""
from __future__ import annotations

import collections
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import base_rows_by_box, load_base, load_boxes  # noqa: E402

from refspec.registry.unified_agenda_parquet import (  # noqa: E402
    _BARE_SECTION_BOX, _USC_SECTION_ORACLE_DIR, _usc_section_oracle, _unstated_kind,
)

_ANY_SCHEME = re.compile(
    r"\b(?:u\.?\s?s\.?\s?c|usc|c\.?\s?f\.?\s?r|cfr|stat|pub\.?\s?l|p\.?\s?l\b|pl\b|public\s+law"
    r"|e\.?\s?o\.?|exec(?:utive)?\s+order|f\.?\s?r\b|fed\.?\s*reg|reorg|proc\.?|proclamation"
    r"|treat|const|d\.?\s?c\.?\s?code|r\.?\s?s\.?)\b",
    re.IGNORECASE,
)
#: A box that is one or more bare section designations and nothing else.
_SECTION_LIST_BOX = re.compile(
    r"^(?:and|or|,)?\s*(?:sec(?:tion)?s?\.?|§{1,2})?\s*"
    r"(?P<first>\d{1,5}[a-z]?(?:[.\-]\d{1,3}[a-z]?)?)(?:\([^()]{1,12}\))*"
    r"(?:\s*(?:,|;|\band\b|\bor\b|\bto\b|\bthrough\b|-)\s*"
    r"(?:sec(?:tion)?s?\.?\s*)?\d{1,5}[a-z]?(?:[.\-]\d{1,3}[a-z]?)?(?:\([^()]{1,12}\))*)*"
    r"\s*[.,;]?\s*$",
    re.IGNORECASE,
)
_SECTION_TOKEN = re.compile(r"\d{1,5}[a-z]?(?:[.\-]\d{1,3}[a-z]?)?")


def main() -> None:
    boxes = load_boxes()
    by_box = base_rows_by_box(load_base(None))
    oracle = _usc_section_oracle()
    print("oracle dir:", _USC_SECTION_ORACLE_DIR, "->", "loaded" if oracle else "MISSING")

    candidates: list[dict] = []
    pool_status = collections.Counter()
    pool_no_donor = 0
    donor_distance = collections.Counter()
    for (rin, pub), bs in boxes.items():
        rows_of = [by_box.get((rin, pub, i), []) for i in range(len(bs))]
        # last stated usc_title at each ordinal, looking only at LOWER ordinals
        last_title: int | None = None
        last_title_ord: int | None = None
        last_title_text: str | None = None
        for i, text in enumerate(bs):
            rows = rows_of[i]
            titleless = all(r["usc_title"] is None for r in rows)
            silent = all(r["authority_type"] == "other" and r["parse_status"] == "failed"
                         for r in rows) and bool(rows)
            stripped = text.strip()
            is_section_only = (
                not _unstated_kind(text)
                and not _ANY_SCHEME.search(stripped)
                and bool(_SECTION_LIST_BOX.fullmatch(stripped) or _BARE_SECTION_BOX.fullmatch(stripped))
            )
            if titleless and is_section_only:
                for r in rows:
                    pool_status[(r["authority_type"], r["parse_status"])] += 1
                if last_title is None:
                    pool_no_donor += 1
                else:
                    donor_distance[i - last_title_ord] += 1
                    candidates.append({
                        "rin": rin, "pub": pub, "ordinal": i, "text": text,
                        "donor_ordinal": last_title_ord, "donor_text": last_title_text,
                        "carried_title": last_title,
                        "sections": _SECTION_TOKEN.findall(stripped),
                        "row_types": [(r["authority_type"], r["parse_status"]) for r in rows],
                        "rows": len(rows),
                    })
            titles = [r["usc_title"] for r in rows if r["usc_title"] is not None]
            if titles:
                last_title, last_title_ord, last_title_text = titles[-1], i, text

    print(f"\nsection-only, title-less boxes:            {pool_no_donor + len(candidates):,}")
    print(f"  with NO earlier sibling stating a title: {pool_no_donor:,}")
    print(f"  with an earlier sibling stating a title: {len(candidates):,}")
    print("(authority_type, parse_status) on those boxes' rows today:")
    for (a, s), c in pool_status.most_common():
        print(f"   {a:<14} {s:<12} {c:>7,}")
    print("distance from the donor box (ordinal delta):")
    for d, c in sorted(donor_distance.items())[:12]:
        print(f"   +{d}: {c:>6,}")
    print(f"   (max delta {max(donor_distance) if donor_distance else 0})")

    # ---- oracle gate --------------------------------------------------------
    exists = absent = unknown = 0
    per_candidate = []
    for c in candidates:
        year = int(c["pub"][:4])
        verdicts = []
        for s in c["sections"]:
            v = oracle.section_verdict(c["carried_title"], s, year)
            verdicts.append({"section": s, "verdict": v.verdict, "reason": v.reason,
                             "attested_at_edition": v.attested_at_edition,
                             "evidence": list(v.evidence)})
        all_exist = bool(verdicts) and all(v["verdict"] == "exists" for v in verdicts)
        any_absent = any(v["verdict"] == "absent" for v in verdicts)
        if all_exist:
            exists += 1
        elif any_absent:
            absent += 1
        else:
            unknown += 1
        per_candidate.append({**c, "verdicts": verdicts,
                              "gate": "exists" if all_exist else ("absent" if any_absent else "unknown")})

    print(f"\noracle on the carried (title, section):")
    print(f"  every section EXISTS under the carried title: {exists:,}")
    print(f"  at least one ABSENT:                          {absent:,}")
    print(f"  otherwise UNKNOWN:                            {unknown:,}")
    rows_gated = sum(c["rows"] for c, p in zip(candidates, per_candidate) if p["gate"] == "exists")
    print(f"  baseline rows on the gated (exists) boxes:    {rows_gated:,}")

    out = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch")
    (out / "h2_candidates.json").write_text(json.dumps(per_candidate, ensure_ascii=False),
                                            encoding="utf-8")

    # ---- 10 seeded examples over the sorted candidate keys ------------------
    keys = sorted((c["rin"], c["pub"], c["ordinal"]) for c in candidates)
    sample = random.Random(20260823).sample(keys, 10)
    index = {(c["rin"], c["pub"], c["ordinal"]): c for c in per_candidate}
    print("\n=== 10 seeded examples (random.Random(20260823).sample over sorted keys) ===")
    picked = [index[k] for k in sample]
    for c in picked:
        print(f"  {c['rin']} {c['pub']} ord{c['ordinal']}  text={c['text']!r}")
        print(f"      donor ord{c['donor_ordinal']} text={c['donor_text']!r}  carried title={c['carried_title']}")
        print(f"      gate={c['gate']}  {c['verdicts']}")
    (out / "h2_seeded.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1),
                                        encoding="utf-8")

    # ---- named specimens ----------------------------------------------------
    print("\n=== named specimens ===")
    for rin, pub, ordinal in (("3072-AC38", "201010", 3), ("0936-AA07", "201710", 4)):
        c = index.get((rin, pub, ordinal))
        print(f"  {rin} {pub} ord{ordinal}: {c if c else 'NOT A CANDIDATE (no earlier sibling states a U.S.C. title)'}")


main()
