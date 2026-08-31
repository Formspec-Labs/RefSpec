from __future__ import annotations

import collections
import json
from pathlib import Path

BOXES = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch/boxes.jsonl")

records = 0
records_multi = 0
boxes_total = 0
per_record = collections.Counter()
lengths = collections.Counter()
lengths_nonlast = collections.Counter()   # boxes that have a successor
lengths_last = collections.Counter()

with BOXES.open(encoding="utf-8") as handle:
    for line in handle:
        row = json.loads(line)
        boxes = row["boxes"]
        records += 1
        boxes_total += len(boxes)
        per_record[len(boxes)] += 1
        if len(boxes) > 1:
            records_multi += 1
        for i, text in enumerate(boxes):
            lengths[len(text)] += 1
            if i + 1 < len(boxes):
                lengths_nonlast[len(text)] += 1
            else:
                lengths_last[len(text)] += 1

print(f"records with >=1 box: {records:,}")
print(f"records with  >1 box: {records_multi:,}  ({records_multi/records:.2%})")
print(f"boxes total:          {boxes_total:,}")
print()
print("boxes per record (top 15):")
for n, c in sorted(per_record.items())[:15]:
    print(f"  {n:>3} boxes: {c:>8,} records")
print(f"  max boxes on one record: {max(per_record)}")
print()
print("box text length -- top 25 lengths overall:")
for ln, c in lengths.most_common(25):
    print(f"  len {ln:>4}: {c:>8,}")
print()
print("box text length -- top 20 among boxes that HAVE a successor:")
for ln, c in lengths_nonlast.most_common(20):
    print(f"  len {ln:>4}: {c:>8,}")
print()
print("long tail: counts at lengths 60..80 (non-last vs last)")
for ln in range(58, 82):
    print(f"  len {ln:>3}: non-last {lengths_nonlast.get(ln,0):>7,}   last {lengths_last.get(ln,0):>7,}   all {lengths.get(ln,0):>7,}")
print()
mx = max(lengths)
print("max box length:", mx)
print("count of boxes >  70 chars:", sum(c for ln, c in lengths.items() if ln > 70))
print("count of boxes >= 60 chars:", sum(c for ln, c in lengths.items() if ln >= 60))
