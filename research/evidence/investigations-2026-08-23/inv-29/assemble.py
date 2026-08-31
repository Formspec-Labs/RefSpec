"""Assemble the final records.json: one entry per (rin, publication_id, marker
hit) with the verbatim ADDITIONAL_INFO, the box texts, the continuation, the
grammar's parsed rows, and duplicate-vs-box flags. Read-only against the repo;
writes only into the job tmp dir.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, "/Users/mikewolfd/Work/RefSpec/src")
from refspec.registry.citation_grammar import parse_authority_citation  # noqa: E402

OUT_DIR = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-29")
final_rows = json.loads((OUT_DIR / "final_rows.json").read_text(encoding="utf-8"))


def identity(citation) -> tuple:
    return (
        citation.authority_type,
        citation.usc_title,
        citation.usc_section,
        citation.public_law,
        citation.statute_volume,
        citation.statute_page,
        citation.executive_order,
        citation.cfr_title,
        citation.cfr_part,
        citation.admin_order_kind,
        citation.admin_order_number,
        citation.fr_volume,
        citation.fr_page,
    )


final = []
for r in final_rows:
    box_identities = set()
    for box_text in r["legal_authority_boxes"]:
        for c in parse_authority_citation(box_text):
            box_identities.add(identity(c))
    parsed = parse_authority_citation(r["continuation"])
    parsed_rows = []
    duplicate_count = 0
    for c in parsed:
        is_dup = identity(c) in box_identities
        duplicate_count += is_dup
        d = {k: v for k, v in asdict(c).items() if v not in (None, False)}
        d["duplicates_existing_box_row"] = is_dup
        parsed_rows.append(d)
    final.append(
        {
            "rin": r["rin"],
            "publication_id": r["publication_id"],
            "marker_text": r["marker_text"],
            "additional_info_full_verbatim": r["additional_info_full"],
            "continuation_verbatim": r["continuation"],
            "trailing_text_excluded_by_boundary_rule": r["trailing_after_boundary"],
            "legal_authority_boxes_verbatim": r["legal_authority_boxes"],
            "cfr_boxes_verbatim": r["cfr_boxes"],
            "box_declared_incomplete": r["legal_authority_boxes"][-1] == "..." if r["legal_authority_boxes"] else None,
            "grammar_row_count": len(parsed_rows),
            "grammar_rows": parsed_rows,
            "duplicate_row_count": duplicate_count,
        }
    )

(OUT_DIR / "records.json").write_text(json.dumps(final, indent=2, sort_keys=True), encoding="utf-8")
print(f"Wrote {len(final)} records to {OUT_DIR / 'records.json'}")
print(f"Total grammar rows: {sum(r['grammar_row_count'] for r in final)}")
print(f"Total duplicate-of-box rows: {sum(r['duplicate_row_count'] for r in final)}")
