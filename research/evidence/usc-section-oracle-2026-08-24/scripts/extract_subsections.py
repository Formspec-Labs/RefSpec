"""Subsection-level oracle: every (title, section, subsection) in the current
release point.

Run 2026-08-22 as an inline heredoc; this file is that heredoc verbatim.

Source: {W}/xml_uscAll_119-102.zip, i.e.
https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_uscAll@119-102.zip

Reads only the non-appendix title files (usc\\d+.xml), so appendix titles
(usc05A, usc11a, usc18a, usc28a, usc50A) contribute nothing. A subsection is
any identifier with exactly one path component under a section:
identifier="/us/usc/t21/s321/p" -> (21, "321", "p"). Dashes inside the
section name are normalised with the grammar's own _DASHES table.

Emits {W}/usc_oracle_subsec.parquet (title, section, sub); 160,209 rows.
"""

import os
W = os.environ.get("USC_WORK", "/Users/mikewolfd/Work/RefSpec/output/usc-annual-2026-08-24")

import re, zipfile, duckdb
_D = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))
PAT = re.compile(rb'identifier="/us/usc/t(\d+)/s([^"/]+)/([a-zA-Z0-9]+)"')
zf = zipfile.ZipFile(f"{W}/xml_uscAll_119-102.zip")
out=set()
for n in zf.namelist():
    if not re.fullmatch(r"usc\d+\.xml", n): continue
    for m in PAT.finditer(zf.read(n)):
        out.add((int(m.group(1)), m.group(2).decode().translate(_D).lower(), m.group(3).decode().lower()))
con=duckdb.connect()
con.execute("CREATE TABLE s (title INT, section VARCHAR, sub VARCHAR)")
con.executemany("INSERT INTO s VALUES (?,?,?)", list(out))
con.execute(f"COPY (SELECT DISTINCT * FROM s) TO '{W}/usc_oracle_subsec.parquet' (FORMAT PARQUET)")
print("subsections:", len(out))
print(con.execute("SELECT * FROM s WHERE title=21 AND section IN ('321','371') AND sub IN ('p','a')").fetchall())
