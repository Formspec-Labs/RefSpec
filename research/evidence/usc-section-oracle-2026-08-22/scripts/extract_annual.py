"""Extract per-year U.S.C. section lists from the OLRC annual historical archives.

Source: https://uscode.house.gov/download/annualhistoricalarchives/XHTML/<YEAR>.zip
Downloaded 2026-08-22.

Section identity comes from the `<!-- itempath:/NNN/.../Sec. X -->` comments the
OLRC conversion emits.  Repealed/omitted blocks are printed as
`Secs. 6 to 15a` and `Secs. 3, 4`; those are kept as ranges/lists rather than
expanded, so the oracle never claims a section number that was never printed.

Emits /tmp/silent/usc_oracle_annual.parquet        (year, title, appendix, section)
      /tmp/silent/usc_oracle_annual_rng.parquet    (year, title, appendix, lo, hi)
"""

import re
import zipfile
import sys

YEARS = list(range(1994, 2025))
_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))

ITEMPATH = re.compile(rb"<!-- itempath:([^>]*?) -->")
FNAME = re.compile(r"(\d{4})/\1usc(\d+)([a-zA-Z]?)\.htm$")
TOKEN = re.compile(r"^[0-9][0-9A-Za-z.\-]*$")

exact = []
ranges = []
for year in YEARS:
    zf = zipfile.ZipFile(f"/tmp/silent/usc_annual_{year}.zip")
    n0, r0 = len(exact), len(ranges)
    for name in zf.namelist():
        fm = FNAME.search(name)
        if fm is None:
            continue
        title = int(fm.group(2))
        appendix = bool(fm.group(3))
        data = zf.read(name)
        seen, rng = set(), set()
        for m in ITEMPATH.finditer(data):
            tail = m.group(1).decode("utf-8", "replace").rsplit("/", 1)[-1]
            mm = re.match(r"Secs?\.\s+(.*)$", tail)
            if mm is None:
                continue
            body = mm.group(1).strip().translate(_DASHES)
            # "6 to 15a", "3, 4", "1301 to 1305, 1307", "3568"
            for chunk in body.split(","):
                chunk = chunk.strip()
                span = re.fullmatch(r"(\S+)\s+to\s+(\S+)", chunk)
                if span and TOKEN.match(span.group(1)) and TOKEN.match(span.group(2)):
                    rng.add((span.group(1).lower(), span.group(2).lower()))
                elif TOKEN.match(chunk):
                    seen.add(chunk.lower())
        exact.extend((year, title, appendix, s) for s in seen)
        ranges.extend((year, title, appendix, a, b) for a, b in rng)
    print(f"{year}: {len(exact)-n0} exact, {len(ranges)-r0} ranges", file=sys.stderr, flush=True)

import duckdb

con = duckdb.connect()
con.execute("CREATE TABLE a (year INT, title INT, appendix BOOL, section VARCHAR)")
con.executemany("INSERT INTO a VALUES (?,?,?,?)", exact)
con.execute("CREATE TABLE r (year INT, title INT, appendix BOOL, lo VARCHAR, hi VARCHAR)")
con.executemany("INSERT INTO r VALUES (?,?,?,?,?)", ranges)
con.execute("COPY (SELECT DISTINCT * FROM a) TO '/tmp/silent/usc_oracle_annual.parquet' (FORMAT PARQUET)")
con.execute("COPY (SELECT DISTINCT * FROM r) TO '/tmp/silent/usc_oracle_annual_rng.parquet' (FORMAT PARQUET)")
print(con.execute("SELECT year, count(*) FROM a GROUP BY 1 ORDER BY 1").fetchall())
print(con.execute("SELECT year, count(*) FROM r GROUP BY 1 ORDER BY 1").fetchall())
