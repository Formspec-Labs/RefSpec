"""Final per-record table: RIN, edition, full ADDITIONAL_INFO, the
continuation substring (marker to next field boundary), the box texts, and
box-vs-continuation join checks. Read-only. Writes only into the job tmp dir.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

OUT_DIR = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-29")
records = json.loads((OUT_DIR / "raw_marker_records.json").read_text(encoding="utf-8"))

# Boundary candidates, in the order they were found empirically:
#  1. "^" -- the RISC form's own field separator ("^PRFA:", "^PANALYSIS:").
#  2. A blank line ("\n\n") -- the post-1998 convention that replaced "^" as
#     a paragraph break between unrelated overflow fields.
#  3. A second, distinct CONT-style label for a DIFFERENT box ("CFR CITATION
#     CONT:", "CFR CITATIONS CONT:") appearing without a blank line first.
CARET = re.compile(r"\^")
BLANK_LINE = re.compile(r"\n\s*\n")
SIBLING_LABEL = re.compile(r"CFR\s+CITATIONS?\s+CONT", re.IGNORECASE)
LEADER = re.compile(r"^[\s.]+")


def find_boundary(ai: str, start: int) -> int | None:
    candidates = []
    m = CARET.search(ai, start)
    if m:
        candidates.append(m.start())
    m = BLANK_LINE.search(ai, start)
    if m:
        candidates.append(m.start())
    m = SIBLING_LABEL.search(ai, start)
    if m:
        candidates.append(m.start())
    return min(candidates) if candidates else None


rows = []
for rec in records:
    ai = rec["additional_info"]
    for hit in rec["marker_hits"]:
        end = hit["end"]
        boundary = find_boundary(ai, end)
        continuation_end = boundary if boundary is not None else len(ai)
        raw_continuation = ai[end:continuation_end]
        stripped_leader = LEADER.match(raw_continuation)
        continuation = raw_continuation[stripped_leader.end():].strip() if stripped_leader else raw_continuation.strip()
        boxes = rec["legal_authority_boxes"]
        rows.append(
            {
                "rin": rec["rin"],
                "publication_id": rec["publication_id"],
                "marker_text": hit["text"],
                "additional_info_full": ai,
                "continuation_raw_after_marker": raw_continuation,
                "continuation": continuation,
                "legal_authority_boxes": boxes,
                "cfr_boxes": rec["cfr_boxes"],
                "trailing_after_boundary": ai[continuation_end:] if boundary is not None else None,
            }
        )

print(f"Total rows: {len(rows)}")
(OUT_DIR / "final_rows.json").write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")

# Print every row compactly for manual review.
for i, r in enumerate(rows, 1):
    print(f"\n[{i}] RIN {r['rin']} ed {r['publication_id']}  marker={r['marker_text']!r}")
    print(f"    boxes ({len(r['legal_authority_boxes'])}): {r['legal_authority_boxes']}")
    print(f"    continuation: {r['continuation']!r}")
    if r["trailing_after_boundary"]:
        print(f"    [trailing after boundary, excluded]: {r['trailing_after_boundary'][:80]!r}")
