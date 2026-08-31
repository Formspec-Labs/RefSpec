"""Raw (pre-normalization) LEGAL_AUTHORITY text lengths, to see a print-column
chop that whitespace collapse would hide."""
from __future__ import annotations

import collections
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path("/Users/mikewolfd/Work/RefSpec")
sys.path.insert(0, str(REPO / "src"))
from refspec.registry.unified_agenda_editions import UNIFIED_AGENDA_EDITION_PINS  # noqa: E402

SOURCE = REPO / "output/registry-real-data-sources/unified-agenda-editions"

raw_lengths = collections.Counter()
raw_lengths_nonlast = collections.Counter()
trailing_space = 0
total = 0
for pin in UNIFIED_AGENDA_EDITION_PINS:
    payload = (SOURCE / f"REGINFO_RIN_DATA_{pin.file_stem}.xml").read_bytes()
    payload = payload.replace(b"\x19", "’".encode())
    root = ET.fromstring(payload)
    for element in root.findall(".//RIN_INFO"):
        lst = element.find("LEGAL_AUTHORITY_LIST")
        if lst is None:
            continue
        kids = [(child.text or "") for child in lst]
        kids = [k for k in kids if " ".join(k.split())]
        for i, raw in enumerate(kids):
            total += 1
            raw_lengths[len(raw)] += 1
            if i + 1 < len(kids):
                raw_lengths_nonlast[len(raw)] += 1
            if raw != raw.rstrip():
                trailing_space += 1
    print(pin.publication_id, file=sys.stderr)

print(f"total boxes: {total:,}   boxes with trailing whitespace in raw XML: {trailing_space:,}")
print("top 25 RAW lengths:")
for ln, c in raw_lengths.most_common(25):
    print(f"  len {ln:>4}: {c:>8,}")
print()
print("RAW lengths >= 150:")
for ln in sorted(k for k in raw_lengths if k >= 150):
    print(f"  len {ln:>4}: {raw_lengths[ln]:>6,}  (non-last {raw_lengths_nonlast.get(ln,0):>5,})")
