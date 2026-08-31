"""H2 take 2: read the carried title through the GRAMMAR, not a homemade
tokenizer -- prepend the donor's title and parse `"<title> U.S.C. <text>"`."""
from __future__ import annotations

import collections
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import base_rows_by_box, load_base, load_boxes  # noqa: E402

from refspec.registry.citation_grammar import parse_authority_citation  # noqa: E402
from refspec.registry.unified_agenda_parquet import (  # noqa: E402
    _BARE_SECTION_BOX, _usc_section_oracle, _unstated_kind,
)

_ANY_SCHEME = re.compile(
    r"\b(?:u\.?\s?s\.?\s?c|usc|c\.?\s?f\.?\s?r|cfr|stat|pub\.?\s?l|p\.?\s?l\b|pl\b|public\s+law"
    r"|e\.?\s?o\.?|exec(?:utive)?\s+order|f\.?\s?r\b|fed\.?\s*reg|reorg|proc\.?|proclamation"
    r"|treat|const|d\.?\s?c\.?\s?code|r\.?\s?s\.?)\b",
    re.IGNORECASE,
)
_SECTION_LIST_BOX = re.compile(
    r"^(?:and|or|,)?\s*(?:sec(?:tion)?s?\.?|§{1,2})?\s*"
    r"\d{1,5}[a-z]?(?:[.\-]\d{1,3}[a-z]?)?(?:\([^()]{1,12}\))*"
    r"(?:\s*(?:,|;|\band\b|\bor\b|\bto\b|\bthrough\b|-)\s*"
    r"(?:sec(?:tion)?s?\.?\s*)?\d{1,5}[a-z]?(?:[.\-]\d{1,3}[a-z]?)?(?:\([^()]{1,12}\))*)*"
    r"\s*[.,;]?\s*$",
    re.IGNORECASE,
)
_LEADING_SEC = re.compile(r"^(?:and|or|,)?\s*(?:sec(?:tion)?s?\.?|§{1,2})?\s*", re.IGNORECASE)


def main() -> None:
    boxes = load_boxes()
    by_box = base_rows_by_box(load_base(None))
    oracle = _usc_section_oracle()

    candidates: list[dict] = []
    no_donor = 0
    for (rin, pub), bs in boxes.items():
        rows_of = [by_box.get((rin, pub, i), []) for i in range(len(bs))]
        last = None
        for i, text in enumerate(bs):
            rows = rows_of[i]
            stripped = text.strip()
            if (all(r["usc_title"] is None for r in rows)
                    and not _unstated_kind(text)
                    and not _ANY_SCHEME.search(stripped)
                    and (_SECTION_LIST_BOX.fullmatch(stripped) or _BARE_SECTION_BOX.fullmatch(stripped))):
                if last is None:
                    no_donor += 1
                else:
                    candidates.append({"rin": rin, "pub": pub, "ordinal": i, "text": text,
                                       "donor_ordinal": last[0], "donor_text": last[1],
                                       "carried_title": last[2]})
            titles = [r["usc_title"] for r in rows if r["usc_title"] is not None]
            if titles:
                last = (i, text, titles[-1])

    gates = collections.Counter()
    for c in candidates:
        year = int(c["pub"][:4])
        body = _LEADING_SEC.sub("", c["text"].strip())
        probe = f"{c['carried_title']} U.S.C. {body}"
        reads = [x for x in parse_authority_citation(probe) if x.authority_type == "usc"]
        verdicts = []
        for x in reads:
            if x.usc_section is None:
                verdicts.append({"section": None, "verdict": "no-section"})
                continue
            v = oracle.section_verdict(x.usc_title, x.usc_section, year, appendix=x.usc_appendix)
            end_v = None
            if x.usc_section_end:
                ev = oracle.section_verdict(x.usc_title, x.usc_section_end, year,
                                            appendix=x.usc_appendix)
                end_v = ev.verdict
            verdicts.append({"section": x.usc_section, "section_end": x.usc_section_end,
                             "verdict": v.verdict, "reason": v.reason,
                             "attested_at_edition": v.attested_at_edition,
                             "evidence": list(v.evidence), "end_verdict": end_v})
        if not verdicts:
            gate = "unreadable"
        elif all(v["verdict"] == "exists" and v.get("end_verdict") in (None, "exists")
                 for v in verdicts):
            gate = "exists"
        elif any(v["verdict"] == "absent" or v.get("end_verdict") == "absent" for v in verdicts):
            gate = "absent"
        else:
            gate = "unknown"
        gates[gate] += 1
        c.update(probe=probe, reads=len(reads), verdicts=verdicts, gate=gate)

    print(f"section-only, title-less boxes:            {no_donor + len(candidates):,}")
    print(f"  with NO earlier sibling stating a title: {no_donor:,}")
    print(f"  with an earlier sibling stating a title: {len(candidates):,}")
    print("oracle gate on the carried reading (grammar-parsed):", dict(gates))
    gated = [c for c in candidates if c["gate"] == "exists"]
    rows_new = rows_change = 0
    typ = collections.Counter()
    for c in gated:
        rows = by_box[(c["rin"], c["pub"], c["ordinal"])]
        for r in rows:
            typ[(r["authority_type"], r["parse_status"])] += 1
        if all(r["authority_type"] == "other" and r["parse_status"] == "failed" for r in rows):
            rows_new += len(rows)
        else:
            rows_change += len(rows)
    print(f"gated boxes: {len(gated):,};  baseline rows on them: {rows_new + rows_change:,}")
    print(f"  reading as nothing today (pure arrival): {rows_new:,}")
    print(f"  carrying a reading today (a CHANGE):     {rows_change:,}")
    print("  their (authority_type, parse_status):", dict(typ))
    citations = sum(c["reads"] for c in gated)
    print(f"citations the carry would emit on the gated boxes: {citations:,}"
          f"  (row count {rows_new + rows_change:,} -> {citations:,})")

    out = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch")
    (out / "h2_candidates2.json").write_text(json.dumps(candidates, ensure_ascii=False),
                                             encoding="utf-8")
    keys = sorted((c["rin"], c["pub"], c["ordinal"]) for c in candidates)
    sample = random.Random(20260823).sample(keys, 10)
    idx = {(c["rin"], c["pub"], c["ordinal"]): c for c in candidates}
    picked = [idx[k] for k in sample]
    print("\n=== 10 seeded examples ===")
    for c in picked:
        print(f"  {c['rin']} {c['pub']} ord{c['ordinal']}  text={c['text']!r}")
        print(f"    donor ord{c['donor_ordinal']} {c['donor_text']!r} -> title {c['carried_title']}")
        print(f"    probe={c['probe']!r}  gate={c['gate']}")
        for v in c["verdicts"]:
            print(f"      {v}")
    (out / "h2_seeded2.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print("\n=== named specimens ===")
    for rin, pub, o in (("3072-AC38", "201010", 3), ("3072-AC38", "201010", 4),
                        ("0936-AA07", "201710", 4)):
        c = idx.get((rin, pub, o))
        print(f"  {rin} {pub} ord{o}: {json.dumps(c, ensure_ascii=False) if c else 'NOT A CANDIDATE (no earlier sibling states a U.S.C. title)'}")


main()
