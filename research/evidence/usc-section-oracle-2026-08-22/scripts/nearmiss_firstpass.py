"""Near-miss analysis for parsed U.S.C. citations that hit no real section."""

import re
import duckdb
import json
import sys

DB = "/tmp/silent/usc.duckdb"
con = duckdb.connect(DB, read_only=True)

# ---- oracle in memory -----------------------------------------------------
exact = set()
for t, s in con.execute("SELECT title, section FROM ora_exact").fetchall():
    exact.add((t, s))
ann = set()
for t, s in con.execute(
    "SELECT DISTINCT title, section FROM ora_ann WHERE NOT appendix").fetchall():
    ann.add((t, s))
LIVE = exact | ann


def key(s):
    m = re.match(r"^(\d+)(.*)$", s)
    return (int(m.group(1)), m.group(2)) if m else None


rng = con.execute("SELECT title, lo, hi FROM ora_rng").fetchall()
rng += [(t, lo, hi) for t, lo, hi in con.execute(
    "SELECT title, lo, hi FROM ora_ann_rng WHERE NOT appendix").fetchall()]
rng_by_title = {}
for t, lo, hi in rng:
    klo, khi = key(lo), key(hi)
    if klo and khi:
        rng_by_title.setdefault(t, []).append((klo, khi))


def exists(t, s):
    if (t, s) in LIVE:
        return True
    k = key(s)
    if k is None:
        return False
    for klo, khi in rng_by_title.get(t, ()):
        if klo <= k <= khi:
            return True
    return False


# ---- corpus ---------------------------------------------------------------
misses = con.execute("""
    SELECT title, section, appendix, rows, texts, rins, first_pub, last_pub, all_note
    FROM verdict2 WHERE NOT exists_anywhere
""").fetchall()

# every (rin, title, section) the corpus states anywhere, for corroboration
rin_pairs = set()
for r, t, s in con.execute(
        "SELECT DISTINCT rin, usc_title, usc_section FROM rowsv").fetchall():
    rin_pairs.add((r, t, s))
rins_of = {}
for r, t, s, a in con.execute(
        "SELECT DISTINCT rin, usc_title, usc_section, usc_appendix FROM rowsv").fetchall():
    rins_of.setdefault((t, s, a), set()).add(r)

LETTERS = [chr(c) for c in range(ord("a"), ord("z") + 1)]
SUFFIXES = LETTERS + [c * 2 for c in LETTERS] + [c * 3 for c in LETTERS] + [c * 4 for c in LETTERS]


def candidates(t, s):
    """Small-edit neighbours of (t, s), tagged by the edit that produced them."""
    out = {}

    def add(kind, tt, ss):
        if (tt, ss) != (t, s) and exists(tt, ss):
            out.setdefault((tt, ss), set()).add(kind)

    # leading-zero pad
    if re.match(r"^0\d", s):
        add("zero-pad", t, s.lstrip("0"))
    # subsection letter restored / dropped
    m = re.match(r"^(\d+)$", s)
    if m:
        for suf in SUFFIXES:
            add("suffix-restored", t, s + suf)
    m = re.match(r"^(\d+)[a-z]+$", s)
    if m:
        add("suffix-dropped", t, m.group(1))
    # digit edits on the numeric stem
    m = re.match(r"^(\d+)(.*)$", s)
    if m:
        num, tail = m.group(1), m.group(2)
        for i in range(len(num) - 1):          # transposition
            if num[i] != num[i + 1]:
                add("transposed", t, num[:i] + num[i + 1] + num[i] + num[i + 2:] + tail)
        for i in range(len(num)):              # deletion
            if len(num) > 1:
                add("digit-dropped", t, num[:i] + num[i + 1:] + tail)
        for i in range(len(num) + 1):          # insertion
            for d in "0123456789":
                add("digit-added", t, num[:i] + d + num[i:] + tail)
        for i in range(len(num)):              # substitution
            for d in "0123456789":
                if d != num[i]:
                    add("digit-changed", t, num[:i] + d + num[i + 1:] + tail)
    # wrong title
    for tt in list(range(1, 55)):
        if tt != t:
            add("other-title", tt, s)
    return out


rows = []
for (t, s, appendix, nrows, ntexts, nrins, fp, lp, all_note) in misses:
    cands = {} if appendix else candidates(t, s)
    my_rins = rins_of.get((t, s, appendix), set())
    corroborated = []
    for (ct, cs), kinds in cands.items():
        hits = sum(1 for r in my_rins if (r, ct, cs) in rin_pairs)
        if hits:
            corroborated.append((ct, cs, sorted(kinds), hits))
    rows.append({
        "title": t, "section": s, "appendix": appendix, "rows": nrows,
        "texts": ntexts, "rins": nrins, "first_pub": fp, "last_pub": lp,
        "n_cand": len(cands),
        "cand_kinds": sorted({k for ks in cands.values() for k in ks}),
        "cands": sorted([[ct, cs, sorted(k)] for (ct, cs), k in cands.items()])[:12],
        "corroborated": sorted(corroborated, key=lambda x: -x[3]),
    })

with open("/tmp/silent/usc_nearmiss.json", "w") as fh:
    json.dump(rows, fh)
print("misses:", len(rows))
print("with >=1 corroborated near-miss:", sum(1 for r in rows if r["corroborated"]))
print("rows covered by corroborated:", sum(r["rows"] for r in rows if r["corroborated"]))
