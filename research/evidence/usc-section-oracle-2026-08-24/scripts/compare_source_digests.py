"""This generation's source digests against generation 1's re-fetch table.

Generation 1 deleted its sources and re-fetched them for a digest table
(``../usc-section-oracle-2026-08-22/README.md``, "Re-fetched source
digests").  Generation 2 fetched the same 32 URLs two days later and keeps
the bytes.  A row that matches means the publisher served the same file
both times, so generation 1's row-for-row reproduction check carries over
to these bytes; a row that differs means the archive moved and every
comparison against generation 1 has to account for it.

Usage:  python3 compare_source_digests.py <gen1-README.md> <fetch_log.tsv>
"""

import re
import sys
from pathlib import Path

G1_README = Path(sys.argv[1])
LOG = Path(sys.argv[2])
TAB = "\t"

gen1 = {}
for line in G1_README.read_text().splitlines():
    m = re.match(r"\|\s*`([^`]+)`\s*\|\s*`([0-9a-f]{64})`\s*\|\s*([\d,]+)\s*\|", line)
    if m:
        gen1[m.group(1)] = (m.group(2), int(m.group(3).replace(",", "")))

rows = []
for line in LOG.read_text().splitlines()[1:]:
    parts = line.split("\t")
    if len(parts) < 8:
        parts = line.split("\\t")
    if len(parts) < 8:
        continue
    name, url, size, digest = parts[0], parts[1], int(parts[2]), parts[3]
    rows.append((name, url, size, digest))

print(TAB.join(["file", "gen2_bytes", "gen2_sha256", "gen1_sha256", "same_digest", "same_bytes"]))
same = differ = unknown = 0
for name, url, size, digest in sorted(rows):
    key = name
    if key not in gen1 and name.startswith("xml_uscAll"):
        key = "xml_uscAll@119-102.zip"
    g1 = gen1.get(key)
    if g1 is None:
        unknown += 1
        print(TAB.join([name, str(size), digest, "NOT IN GENERATION 1", "", ""]))
        continue
    ok = g1[0] == digest
    same += ok
    differ += not ok
    print(TAB.join([name, str(size), digest, g1[0], "yes" if ok else "NO", "yes" if g1[1] == size else "NO"]))
print()
print(f"identical to generation 1's re-fetch: {same}   different: {differ}   not listed: {unknown}")
