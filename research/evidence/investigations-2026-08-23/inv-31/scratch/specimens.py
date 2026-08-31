from __future__ import annotations

import json
from pathlib import Path

BOXES = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch/boxes.jsonl")

WANT = {
    ("2126-AA63", "200010"),
    ("3052-AD44", "202210"),
    ("3052-AD42", "202210"),
    ("3072-AC96", "202304"),
    ("3072-AC38", "201010"),
    ("0936-AA07", "201710"),
    ("2060-AP43", "201004"),
    ("2126-AA64", "201410"),
}

found = {}
with BOXES.open(encoding="utf-8") as handle:
    for line in handle:
        row = json.loads(line)
        key = (row["rin"], row["pub"])
        if key in WANT:
            found[key] = row["boxes"]

for key in sorted(WANT):
    boxes = found.get(key)
    print("=" * 78)
    print(f"RIN {key[0]}  edition {key[1]}   boxes={0 if boxes is None else len(boxes)}")
    if boxes is None:
        print("  (record not present in that edition)")
        continue
    for i, text in enumerate(boxes):
        print(f"  [{i:>2}] len={len(text):>3}  {text!r}")
