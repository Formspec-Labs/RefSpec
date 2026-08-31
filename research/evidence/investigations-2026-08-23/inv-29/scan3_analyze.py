"""Analyze the 67 CONT-marker records: continuation boundary, box overflow
status (does the box end in a declared-incomplete placeholder?), and dedupe
by (rin, continuation text) to see the distinct authorial events versus the
per-edition repeat count.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

OUT_DIR = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-29")
records = json.loads((OUT_DIR / "raw_marker_records.json").read_text(encoding="utf-8"))

# The RISC form's internal field-separator convention observed in samples:
# "^PRFA:  N", "^PANALYSIS:  Regulatory Evaluation" -- a caret introduces the
# next overflowed field. Bare "^" without a following label letter is also
# treated as a boundary, conservatively.
NEXT_FIELD = re.compile(r"\^")

_UNSTATED_SENTINEL_RE = re.compile(r"^\s*(\.\.\.|\. \. \.)\s*$")


def box_is_declared_incomplete(box_text: str) -> bool:
    return bool(_UNSTATED_SENTINEL_RE.match(box_text))


rows = []
for rec in records:
    ai = rec["additional_info"]
    for hit in rec["marker_hits"]:
        end = hit["end"]
        boundary = NEXT_FIELD.search(ai, end)
        continuation_end = boundary.start() if boundary else len(ai)
        continuation = ai[end:continuation_end].strip()
        tail_label = ai[boundary.start():boundary.start() + 20] if boundary else None
        boxes = rec["legal_authority_boxes"]
        last_box = boxes[-1] if boxes else None
        rows.append(
            {
                "rin": rec["rin"],
                "publication_id": rec["publication_id"],
                "marker_text": hit["text"],
                "continuation": continuation,
                "tail_label": tail_label,
                "additional_info_full": ai,
                "legal_authority_boxes": boxes,
                "last_box_declared_incomplete": box_is_declared_incomplete(last_box) if last_box else None,
                "last_box_text": last_box,
                "box_count": len(boxes),
            }
        )

print(f"Total (record, marker-hit) rows: {len(rows)}")
distinct_rins = {r["rin"] for r in rows}
distinct_editions = {r["publication_id"] for r in rows}
print(f"Distinct RINs: {len(distinct_rins)}")
print(f"Distinct editions: {len(distinct_editions)}")
print()

# Box overflow status
declared = sum(1 for r in rows if r["last_box_declared_incomplete"])
not_declared = sum(1 for r in rows if r["last_box_declared_incomplete"] is False)
no_box = sum(1 for r in rows if r["last_box_declared_incomplete"] is None)
print(f"Records whose LAST legal-authority box IS the '...' placeholder: {declared}")
print(f"Records whose last box is NOT '...' (no declared-incomplete flag): {not_declared}")
print(f"Records with NO legal-authority boxes at all: {no_box}")
print()

# Distinct (rin, continuation) authorial events
distinct_events = {}
for r in rows:
    key = (r["rin"], r["continuation"])
    distinct_events.setdefault(key, []).append(r["publication_id"])

print(f"Distinct (RIN, continuation-text) authorial events: {len(distinct_events)}")
print()
print("=" * 100)
for (rin, continuation), editions in sorted(distinct_events.items()):
    print(f"RIN {rin}  editions={sorted(editions)}")
    print(f"  continuation: {continuation!r}")
    print()

OUT_DIR.mkdir(parents=True, exist_ok=True)
(OUT_DIR / "rows_with_continuation.json").write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
print(f"Wrote {len(rows)} rows to {OUT_DIR / 'rows_with_continuation.json'}")
