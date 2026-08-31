"""Twenty seeded sections from the twelve recovered volumes, read back out of
the raw archive file with the heading OLRC printed beside them.

The point is to look at the added rows rather than count them: for each sampled
``(year, title, section)`` this prints the ``<!-- itempath: ... -->`` comment
the extractor matched on and the ``<h3 class="section-head">`` line that
follows it, straight out of ``YYYY/YYYYUSCNN.htm``.

Usage:  python3 seeded_headings.py <gen2-dir> <zip-dir> [n]
"""

import random
import re
import sys
import zipfile
from html import unescape
from pathlib import Path

import duckdb

G2 = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("research/evidence/usc-section-oracle-2026-08-24")
ZIPS = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output/usc-annual-2026-08-24")
N = int(sys.argv[3]) if len(sys.argv) > 3 else 20

GAINED = [(12, 2010), (13, 2010), (14, 2010), (51, 2010)] + [(t, 2012) for t in (33, 35, 36, 37, 38, 39, 40, 41)]

con = duckdb.connect()
rows = con.execute(
    f"""SELECT year, title, section
        FROM '{G2}/usc-oracle-annual-sections.parquet'
        WHERE appendix = false
          AND (year, title) IN ({','.join(f"({y},{t})" for t, y in GAINED)})
        ORDER BY year, title, section"""
).fetchall()
print(f"candidate sections in the twelve recovered volumes: {len(rows)}")

rng = random.Random(20260824)
sample = sorted(rng.sample(rows, min(N, len(rows))))

HEAD = re.compile(rb'<h3 class="section-head">(.*?)</h3>', re.S)
cache: dict[int, zipfile.ZipFile] = {}
TAB = "\t"
print(TAB.join(["year", "title", "section", "member", "itempath", "printed_heading"]))
for year, title, section in sample:
    zf = cache.setdefault(year, zipfile.ZipFile(ZIPS / f"{year}.zip"))
    member = next(
        n for n in zf.namelist()
        if re.search(rf"{year}/{year}usc0*{title}\.htm$", n, re.IGNORECASE)
    )
    data = zf.read(member)
    pat = re.compile(
        rb"<!-- itempath:([^>]*?/Secs?\. "
        + re.escape(section.encode()).replace(rb"\-", rb"[-\xe2\x80\x93]")
        + rb"(?:[ ,][^>]*?)?) -->",
        re.IGNORECASE,
    )
    m = pat.search(data)
    if m is None:
        print(TAB.join([str(year), str(title), section, member, "NOT FOUND", ""]))
        continue
    itempath = m.group(1).decode("utf-8", "replace")
    hm = HEAD.search(data, m.end(), m.end() + 4000)
    heading = unescape(hm.group(1).decode("utf-8", "replace")).replace("\n", " ") if hm else ""
    print(TAB.join([str(year), str(title), section, member, itempath, heading]))
