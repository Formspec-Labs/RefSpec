"""Extract a U.S.C. section-existence oracle from OLRC USLM XML.

Source: https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_uscAll@119-102.zip
Downloaded 2026-08-22.

Emits {W}/usc_oracle_exact.parquet   (title, section, status, source_file)
       {W}/usc_oracle_ranges.parquet (title, lo_num, lo_suf, hi_num, hi_suf, status, raw)
"""

import os
W = os.environ.get("USC_WORK", str(__import__("pathlib").Path(__file__).resolve().parents[4] / "output/usc-annual-2026-08-24"))

import re
import zipfile
import sys

ZIP = f"{W}/xml_uscAll_119-102.zip"

SECTION_TAG = re.compile(rb"<section\b[^>]*>")
ATTR_IDENT = re.compile(rb'identifier="([^"]*)"')
ATTR_STATUS = re.compile(rb'status="([^"]*)"')
# /us/usc/t42/s7401  or  /us/usc/t42/s6...15a
_DASHES = str.maketrans(dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\x96\x97", "-"))
IDENT_PIECE = re.compile(r"^/us/usc/t(\d+)/s(.+)$")
# Also the removalDescription notes: "Section 6a, act ..." / "Sections 6, 7, ..."
REMOVAL_SECT = re.compile(
    r"<p[^>]*>\s*(?:Section|Sections)\s+([0-9][0-9a-zA-Z–—\-‐,\s’']*?)(?:,|\s+w|\s+act|\s+Pub|\s+act)",
)

exact = []   # (title, section, status)
ranges = []  # (title, lo, hi, status, raw)

zf = zipfile.ZipFile(ZIP)
names = [n for n in zf.namelist() if re.fullmatch(r"usc\d+[A-Za-z]?\.xml", n)]
names.sort()

for name in names:
    data = zf.read(name)
    n_before = len(exact)
    for m in SECTION_TAG.finditer(data):
        tag = m.group(0)
        im = ATTR_IDENT.search(tag)
        if im is None:
            continue
        sm = ATTR_STATUS.search(tag)
        status = sm.group(1).decode() if sm else "current"
        ident = im.group(1).decode()
        ident = ident.translate(_DASHES)
        for piece in ident.split():
            pm = IDENT_PIECE.match(piece)
            if pm is None:
                continue
            title = int(pm.group(1))
            sec = pm.group(2)
            if "..." in sec:
                lo, _, hi = sec.partition("...")
                ranges.append((title, lo.lower(), hi.lower(), status, piece))
            else:
                exact.append((title, sec.lower(), status, name))
    print(f"{name}: +{len(exact)-n_before} exact  (total {len(exact)}, ranges {len(ranges)})",
          file=sys.stderr, flush=True)

import duckdb

con = duckdb.connect()
con.execute("CREATE TABLE ex (title INT, section VARCHAR, status VARCHAR, src VARCHAR)")
con.executemany("INSERT INTO ex VALUES (?,?,?,?)", exact)
con.execute("CREATE TABLE rg (title INT, lo VARCHAR, hi VARCHAR, status VARCHAR, raw VARCHAR)")
con.executemany("INSERT INTO rg VALUES (?,?,?,?,?)", ranges)
con.execute(f"COPY (SELECT DISTINCT title, section, status FROM ex) TO '{W}/usc_oracle_exact.parquet' (FORMAT PARQUET)")
con.execute(f"COPY (SELECT DISTINCT title, lo, hi, status, raw FROM rg) TO '{W}/usc_oracle_ranges.parquet' (FORMAT PARQUET)")
print("exact rows:", con.execute("SELECT count(*) FROM (SELECT DISTINCT title, section FROM ex)").fetchone())
print("range rows:", con.execute("SELECT count(*) FROM (SELECT DISTINCT title, lo, hi FROM rg)").fetchone())
print("titles:", con.execute("SELECT count(DISTINCT title) FROM ex").fetchone())
