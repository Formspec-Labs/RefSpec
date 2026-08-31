"""Chapter-level oracle: every (title, chapter) in the current release point.

Run 2026-08-22 as an inline heredoc; this file is that heredoc verbatim (the
second of two attempts — the first used a PIECE pattern without the optional
intermediate path segments and matched only 1,524 chapters, missing every
chapter nested under a subtitle or part such as /us/usc/t10/stA/ptI/ch1).

Source: /tmp/silent/xml_uscAll_119-102.zip, i.e.
https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_uscAll@119-102.zip

Reads only the non-appendix title files. A chapter is the identifier of a
<chapter> element whose last path component is chNN; ranged stubs
("ch1...3") are skipped.

Emits /tmp/silent/usc_oracle_chapter.parquet (title, chapter); 2,905 rows.
"""

import re, zipfile, duckdb
_D = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))
TAG = re.compile(rb"<chapter\b[^>]*>")
IDENT = re.compile(rb'identifier="([^"]*)"')
PIECE = re.compile(r"^/us/usc/t(\d+)(?:/[a-zA-Z]+[A-Za-z0-9]*)*?/ch([^/]+)$")
zf = zipfile.ZipFile("/tmp/silent/xml_uscAll_119-102.zip")
out=set()
for n in zf.namelist():
    if not re.fullmatch(r"usc\d+\.xml", n): continue
    for m in TAG.finditer(zf.read(n)):
        im = IDENT.search(m.group(0))
        if not im: continue
        for p in im.group(1).decode().translate(_D).split():
            pm = PIECE.match(p)
            if pm and "..." not in pm.group(2):
                out.add((int(pm.group(1)), pm.group(2).lower()))
con=duckdb.connect()
con.execute("CREATE TABLE c (title INT, chapter VARCHAR)")
con.executemany("INSERT INTO c VALUES (?,?)", list(out))
con.execute("COPY (SELECT DISTINCT * FROM c) TO '/tmp/silent/usc_oracle_chapter.parquet' (FORMAT PARQUET)")
print("chapters:", len(out), "titles:", len({t for t,_ in out}))
print("checks:", sorted([(t,c) for t,c in out if (t,c) in {(10,'55'),(5,'89'),(44,'35'),(41,'85'),(42,'85'),(21,'9')}]))
