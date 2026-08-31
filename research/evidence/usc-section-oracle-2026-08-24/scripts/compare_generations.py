"""Generation 1 vs generation 2 of the section oracle: the whole proof.

(a) the annual coverage matrix -- which (title, appendix, year) pairs gain
    coverage and which lose it;
(b) per-pair section and range counts for every pair that gained;
(c) every OTHER pair's rows, compared set-for-set and by digest of the sorted
    set -- the claim is that nothing outside the gained pairs moved;
(d) the four release-point tables and the derived enumerated set
    (release point union non-appendix annual, the module's ``enumerated``).

Prints tab-separated blocks; writes nothing.  Usage:

    python3 compare_generations.py <gen1-dir> <gen2-dir>
"""

import sys

import duckdb

G1 = sys.argv[1] if len(sys.argv) > 1 else "research/evidence/usc-section-oracle-2026-08-22"
G2 = sys.argv[2] if len(sys.argv) > 2 else "research/evidence/usc-section-oracle-2026-08-24"

con = duckdb.connect()
for gen, root in (("g1", G1), ("g2", G2)):
    for tag, fname in (
        ("annsec", "usc-oracle-annual-sections.parquet"),
        ("annrng", "usc-oracle-annual-ranges.parquet"),
        ("sec", "usc-oracle-sections.parquet"),
        ("rng", "usc-oracle-ranges.parquet"),
        ("sub", "usc-oracle-subsections.parquet"),
        ("chap", "usc-oracle-chapters.parquet"),
    ):
        con.execute(f"CREATE VIEW {gen}_{tag} AS SELECT * FROM '{root}/{fname}'")


def rows(sql):
    return con.execute(sql).fetchall()


TAB = "\t"

print("=" * 72)
print("(a) ANNUAL COVERAGE MATRIX")
print("=" * 72)
for tag, label in (("annsec", "annual sections"), ("annrng", "annual ranges")):
    g1 = set(rows(f"SELECT DISTINCT title, appendix, year FROM g1_{tag}"))
    g2 = set(rows(f"SELECT DISTINCT title, appendix, year FROM g2_{tag}"))
    print(f"{chr(10)}-- {label}: g1 pairs {len(g1)}, g2 pairs {len(g2)}")
    print("gained (in g2, not in g1):")
    for t, a, y in sorted(g2 - g1):
        print(TAB.join(["", f"title={t}", f"appendix={a}", f"year={y}"]))
    print("lost (in g1, not in g2):")
    for t, a, y in sorted(g1 - g2):
        print(TAB.join(["", f"title={t}", f"appendix={a}", f"year={y}"]))

gained = sorted(
    set(rows("SELECT DISTINCT title, appendix, year FROM g2_annsec"))
    - set(rows("SELECT DISTINCT title, appendix, year FROM g1_annsec"))
)

print()
print("=" * 72)
print("(b) PER-PAIR COUNTS FOR THE GAINED PAIRS (generation 2)")
print("=" * 72)
print(TAB.join(["title", "appendix", "year", "sections", "ranges"]))
for t, a, y in gained:
    ns = rows(f"SELECT count(*) FROM g2_annsec WHERE title={t} AND appendix={a} AND year={y}")[0][0]
    nr = rows(f"SELECT count(*) FROM g2_annrng WHERE title={t} AND appendix={a} AND year={y}")[0][0]
    print(TAB.join([str(t), str(a), str(y), str(ns), str(nr)]))

print()
print("=" * 72)
print("(c) EVERY OTHER PAIR, ROW-FOR-ROW")
print("=" * 72)
gained_set = {(t, a, y) for t, a, y in gained}
for tag, expr, label in (
    ("annsec", "section", "annual sections"),
    ("annrng", "lo || '..' || hi", "annual ranges"),
):
    d1 = {}
    d2 = {}
    for gen, store in (("g1", d1), ("g2", d2)):
        for t, a, y, digest, n in rows(
            f"""SELECT title, appendix, year,
                       md5(string_agg({expr}, '' ORDER BY {expr})) AS digest,
                       count(*) AS n
                FROM {gen}_{tag} GROUP BY 1,2,3"""
        ):
            store[(t, a, y)] = (digest, n)
    shared = sorted((set(d1) | set(d2)) - gained_set)
    differing = [k for k in shared if d1.get(k) != d2.get(k)]
    print(f"{chr(10)}-- {label}: {len(shared)} pairs outside the gained set, compared by md5 of the sorted row set")
    print(f"   identical: {len(shared) - len(differing)}   differing: {len(differing)}")
    for k in differing:
        print(f"   DIFFERS {k}: g1={d1.get(k)} g2={d2.get(k)}")
    where = ""
    if gained:
        where = " AND NOT (" + " OR ".join(
            f"(title={t} AND appendix={a} AND year={y})" for t, a, y in gained
        ) + ")"
    only1 = rows(
        f"SELECT count(*) FROM (SELECT * FROM g1_{tag} WHERE true{where} "
        f"EXCEPT SELECT * FROM g2_{tag} WHERE true{where})"
    )[0][0]
    only2 = rows(
        f"SELECT count(*) FROM (SELECT * FROM g2_{tag} WHERE true{where} "
        f"EXCEPT SELECT * FROM g1_{tag} WHERE true{where})"
    )[0][0]
    print(f"   EXCEPT g1-g2: {only1}   EXCEPT g2-g1: {only2}")

print()
print("=" * 72)
print("(d) THE FOUR RELEASE-POINT TABLES, AND THE ENUMERATED SET")
print("=" * 72)
print(TAB.join(["table", "g1_rows", "g2_rows", "only_in_g1", "only_in_g2"]))
for tag, fname in (
    ("sec", "usc-oracle-sections"),
    ("rng", "usc-oracle-ranges"),
    ("sub", "usc-oracle-subsections"),
    ("chap", "usc-oracle-chapters"),
):
    n1 = rows(f"SELECT count(*) FROM g1_{tag}")[0][0]
    n2 = rows(f"SELECT count(*) FROM g2_{tag}")[0][0]
    o1 = rows(f"SELECT count(*) FROM (SELECT * FROM g1_{tag} EXCEPT SELECT * FROM g2_{tag})")[0][0]
    o2 = rows(f"SELECT count(*) FROM (SELECT * FROM g2_{tag} EXCEPT SELECT * FROM g1_{tag})")[0][0]
    print(TAB.join([fname, str(n1), str(n2), str(o1), str(o2)]))

for gen in ("g1", "g2"):
    con.execute(
        f"""CREATE VIEW {gen}_enum AS
            SELECT DISTINCT title, lower(section) AS section FROM {gen}_sec
            UNION
            SELECT DISTINCT title, lower(section) FROM {gen}_annsec WHERE appendix = false"""
    )
n1 = rows("SELECT count(*) FROM g1_enum")[0][0]
n2 = rows("SELECT count(*) FROM g2_enum")[0][0]
print(f"{chr(10)}enumerated (release point U non-appendix annual): g1 {n1}  g2 {n2}  delta {n2 - n1}")
new = rows("SELECT title, section FROM (SELECT * FROM g2_enum EXCEPT SELECT * FROM g1_enum) ORDER BY title, section")
gone = rows("SELECT title, section FROM (SELECT * FROM g1_enum EXCEPT SELECT * FROM g2_enum) ORDER BY title, section")
print(f"pairs appearing ONLY because a previously-skipped volume prints them: {len(new)}")
for t, s in new:
    print(TAB.join(["", "NEW", str(t), s]))
print(f"pairs lost: {len(gone)}")
for t, s in gone:
    print(TAB.join(["", "LOST", str(t), s]))

a1 = rows("SELECT count(*) FROM (SELECT DISTINCT title, appendix, section FROM g1_annsec)")[0][0]
a2 = rows("SELECT count(*) FROM (SELECT DISTINCT title, appendix, section FROM g2_annsec)")[0][0]
print(f"{chr(10)}distinct (title, appendix, section) in annual sections: g1 {a1}  g2 {a2}")
print("annual sections total rows: g1",
      rows("SELECT count(*) FROM g1_annsec")[0][0], " g2",
      rows("SELECT count(*) FROM g2_annsec")[0][0])
print("annual ranges total rows:   g1",
      rows("SELECT count(*) FROM g1_annrng")[0][0], " g2",
      rows("SELECT count(*) FROM g2_annrng")[0][0])
