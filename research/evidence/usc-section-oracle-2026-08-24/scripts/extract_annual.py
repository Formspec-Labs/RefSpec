"""Extract per-year U.S.C. section lists from the OLRC annual historical archives.

GENERATION 2 (2026-08-24).  Identical to generation 1
(``research/evidence/usc-section-oracle-2026-08-22/scripts/extract_annual.py``)
except for two things, both in the filename matcher:

1. **The bug.**  Generation 1 matched archive members with

       FNAME = re.compile(r"(\\d{4})/\\1usc(\\d+)([a-zA-Z]?)\\.htm$")

   which is case-sensitive.  OLRC named twelve annual title volumes with an
   uppercase ``USC`` -- 2010USC12/13/14/51 and 2012USC33/35/36/37/38/39/40/41
   -- so those twelve files were silently skipped and those twelve
   (title, year) pairs got no annual coverage at all.  ``re.IGNORECASE`` on
   the ``usc`` literal is the whole fix.

2. **The guard.**  Every member of every year's listing is now classified and
   written to ``$W/listing_<year>.tsv`` as matched/unmatched, and anything
   unmatched that is not a known non-title member (the year index page, the
   Popular Names table, Tables 1-6) raises.  A skip is never silent again.

Source: https://uscode.house.gov/download/annualhistoricalarchives/XHTML/<YEAR>.zip

Section identity comes from the `<!-- itempath:/NNN/.../Sec. X -->` comments the
OLRC conversion emits.

**UNBRACKETED repealed/omitted blocks are kept**, and where such a block covers
several sections it is printed `Secs. 6 to 15a` or `Secs. 3, 4` and is kept as a
range/list rather than expanded, so the oracle never claims a section number
that was never printed.  The 2012 volumes alone carry 1,544 unbracketed
`repealedhead` and 596 unbracketed `omittedhead` multi-section blocks, and every
one is in the output.

**BRACKETED stubs are deliberately EXCLUDED, and that is a semantic, not an
oversight.**  OLRC also prints withdrawn sections with the heading in square
brackets -- itempath `/400/SUBTITLE I/CHAPTER 3/SUBCHAPTER III/[Sec. 322`,
heading `[<sect>322. Repealed. Pub. L. 109-313, ... Oct. 6, 2006 ...]`
(2012/2012USC40.htm), and likewise `[<sect><sect>1 to 5. Repealed ...]` and
`[<sect>11704. Renumbered <sect>11703]`.  The `Secs?\\.` matcher below does not
strip the leading `[`, so these do not reach the tables: **33,895 section rows
and 4,450 range rows over 1994-2024, 33,848 of the section rows reaching no
other year or form.**

The line is the publisher's own, stated in its metadata and not merely in its
typography: every entry carries a `usckey` beside its `itempath`, and for a
bracketed heading the SECTION FIELD of that key is zeroed.  `40_[322` gets
`usckey:400000000000000000000000000000000`; the live <sect>323 immediately
below it gets `usckey:400000000032300000000000000000000`.  Measured over all 31
archives that holds without exception -- **35,088 of 35,088** non-appendix
bracketed entries carry a zeroed section field, against 1,585,628 unbracketed
entries that carry a real one.  OLRC declines to mint a Code identity for a
bracketed heading, and this extractor follows it: what the annual tables attest
is what the edition printed as LIVE LAW.

The consequence, named: 40 U.S.C. 322 reads unattested at edition 2012 though
the 2012 volume prints a bracketed stub for it (it still reads `exists` -- the
release point carries it repealed and 1994-2005 print it unbracketed).  The
reason it stands: admitting bracketed ranges would move 6 U.S.C. 1 from
`absent` to `exists` on the strength of a 1972 repeal stub in the abolished
"TITLE 6-SURETY BONDS [REPEALED]", for 19 rows filed 2005-2017 that plainly
mean the Homeland Security Act at 6 U.S.C. 101.  See the artifact README's
"Bracketed stubs" section for the full measurement and the follow-up.

Emits $W/usc_oracle_annual.parquet        (year, title, appendix, section)
      $W/usc_oracle_annual_rng.parquet    (year, title, appendix, lo, hi)
"""

import os
import re
import zipfile
import sys

W = os.environ.get("USC_WORK", str(__import__("pathlib").Path(__file__).resolve().parents[4] / "output/usc-annual-2026-08-24"))

YEARS = list(range(1994, 2025))
_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))

ITEMPATH = re.compile(rb"<!-- itempath:([^>]*?) -->")
# THE FIX: case-insensitive on the `usc` literal.  Everything else is
# generation 1's pattern character for character.
FNAME = re.compile(r"(\d{4})/\1usc(\d+)([a-zA-Z]?)\.htm$", re.IGNORECASE)
TOKEN = re.compile(r"^[0-9][0-9A-Za-z.\-]*$")

# Members that are legitimately not title volumes.  Anything unmatched and
# outside this list is a loud failure, not a skip.
NON_TITLE = [
    re.compile(r"^(\d{4})/index\.html?$", re.IGNORECASE),
    re.compile(r"^(\d{4})/\1uscPopularNames\.htm$", re.IGNORECASE),
    re.compile(r"^(\d{4})/\1uscTable\d+\.htm$", re.IGNORECASE),
    re.compile(r"^(\d{4})/usc\.css$", re.IGNORECASE),  # the stylesheet
    # the 2011 archive's two Congress cross-reference tables
    re.compile(r"^(\d{4})/tbl\d+(cd|pl)_[a-z0-9]+\.htm$", re.IGNORECASE),
    re.compile(r"/$"),  # directory entries
]

exact = []
ranges = []
audit = []          # (year, name, status, title, appendix, bytes)
unexpected = []     # anything unmatched that is not a known non-title member
for year in YEARS:
    zf = zipfile.ZipFile(f"{W}/{year}.zip")
    n0, r0 = len(exact), len(ranges)
    listing = []
    for name in zf.namelist():
        info = zf.getinfo(name)
        fm = FNAME.search(name)
        if fm is None:
            known = any(p.search(name) for p in NON_TITLE)
            listing.append((year, name, "non-title" if known else "UNEXPECTED", "", "", info.file_size))
            if not known:
                unexpected.append((year, name, info.file_size))
            continue
        title = int(fm.group(2))
        appendix = bool(fm.group(3))
        listing.append((year, name, "matched", title, appendix, info.file_size))
        data = zf.read(name)
        seen, rng = set(), set()
        for m in ITEMPATH.finditer(data):
            tail = m.group(1).decode("utf-8", "replace").rsplit("/", 1)[-1]
            # Anchored at the start ON PURPOSE, which is what excludes the
            # bracketed stubs ("[Sec. 322", "[Secs. 1 to 5"): a bracketed
            # heading is one OLRC itself refuses a usckey section field for,
            # and attestation here means printed as live law. See the module
            # docstring for the measurement and the two named consequences.
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
    audit.extend(listing)
    with open(f"{W}/listing_{year}.tsv", "w") as fh:
        fh.write("year\tmember\tstatus\ttitle\tappendix\tbytes\n")
        for row in listing:
            fh.write("\t".join(str(c) for c in row) + "\n")
    n_matched = sum(1 for r in listing if r[2] == "matched")
    print(
        f"{year}: {len(exact)-n0} exact, {len(ranges)-r0} ranges, "
        f"{n_matched}/{len(listing)} members matched",
        file=sys.stderr, flush=True,
    )

with open(f"{W}/listing_all.tsv", "w") as fh:
    fh.write("year\tmember\tstatus\ttitle\tappendix\tbytes\n")
    for row in audit:
        fh.write("\t".join(str(c) for c in row) + "\n")

if unexpected:
    for year, name, size in unexpected:
        print(f"UNEXPECTED MEMBER {year} {name} {size}", file=sys.stderr)
    raise SystemExit(
        f"{len(unexpected)} archive members matched neither the title-volume "
        "pattern nor the known non-title members; refusing to extract silently."
    )

import duckdb

con = duckdb.connect()
con.execute("CREATE TABLE a (year INT, title INT, appendix BOOL, section VARCHAR)")
con.executemany("INSERT INTO a VALUES (?,?,?,?)", exact)
con.execute("CREATE TABLE r (year INT, title INT, appendix BOOL, lo VARCHAR, hi VARCHAR)")
con.executemany("INSERT INTO r VALUES (?,?,?,?,?)", ranges)
con.execute(f"COPY (SELECT DISTINCT * FROM a) TO '{W}/usc_oracle_annual.parquet' (FORMAT PARQUET)")
con.execute(f"COPY (SELECT DISTINCT * FROM r) TO '{W}/usc_oracle_annual_rng.parquet' (FORMAT PARQUET)")
print(con.execute("SELECT year, count(*) FROM a GROUP BY 1 ORDER BY 1").fetchall())
print(con.execute("SELECT year, count(*) FROM r GROUP BY 1 ORDER BY 1").fetchall())
