"""For each unresolved miss, look for the SAME authority string written correctly
somewhere else in the corpus, differing only in the section token."""

import re
import json
import duckdb
import collections

con = duckdb.connect("/tmp/silent/usc.duckdb", read_only=True)
LIVE = {(t, s) for t, s in con.execute("SELECT title, section FROM ora_exact").fetchall()}
LIVE |= {(t, s) for t, s in con.execute(
    "SELECT DISTINCT title, section FROM ora_ann WHERE NOT appendix").fetchall()}

ALL_TEXTS = {}
for txt, n in con.execute(
        "SELECT authority_text, count(*) FROM '/tmp/silent/AGENDA_SNAPSHOT.parquet' GROUP BY 1").fetchall():
    ALL_TEXTS[txt.lower()] = n

recs = json.load(open("/tmp/silent/usc_triage.json"))
LETTERS = [chr(c) for c in range(ord("a"), ord("z") + 1)]
SUF = LETTERS + [c * 2 for c in LETTERS] + [c * 3 for c in LETTERS] + [c * 4 for c in LETTERS]


def cands(t, s):
    out = collections.defaultdict(set)

    def add(k, ss):
        if ss != s and (t, ss) in LIVE:
            out[ss].add(k)
    m = re.match(r"^(\d+)(.*)$", s)
    if not m:
        return out
    num, tail = m.group(1), m.group(2)
    for i in range(len(num) - 1):
        if num[i] != num[i + 1]:
            add("transposed", num[:i] + num[i + 1] + num[i] + num[i + 2:] + tail)
    if len(num) > 1:
        for i in range(len(num)):
            add("digit-dropped", num[:i] + num[i + 1:] + tail)
    for i in range(len(num) + 1):
        for d in "0123456789":
            add("digit-added", num[:i] + d + num[i:] + tail)
    for i in range(len(num)):
        for d in "0123456789":
            if d != num[i]:
                add("digit-changed", num[:i] + d + num[i + 1:] + tail)
    if re.fullmatch(r"\d+", s):
        for suf in SUF:
            add("suffix-restored", s + suf)
    mm = re.fullmatch(r"(\d+)([a-z]+)", s)
    if mm:
        add("suffix-dropped", mm.group(1))
    return out


hits = []
for r in recs:
    if r["cls"] not in ("C12 unresolved", "C11 corroborated-near-miss"):
        continue
    t, s = r["title"], r["section"]
    found = collections.defaultdict(int)
    kinds = {}
    for txt, n in r["specimens"]:
        low = txt.lower()
        for cand, ks in cands(t, s).items():
            sib = re.sub(rf"(?<![0-9a-z]){re.escape(s)}(?![0-9a-z])", cand, low)
            if sib != low and sib in ALL_TEXTS:
                found[cand] += ALL_TEXTS[sib]
                kinds[cand] = sorted(ks)
    if found:
        best = max(found.items(), key=lambda x: x[1])
        hits.append({**{k: r[k] for k in ("title", "section", "rows", "texts", "rins", "cls",
                                          "first_pub", "last_pub")},
                     "sibling": f"{t} USC {best[0]}", "sibling_rows": best[1],
                     "kinds": kinds[best[0]], "n_sibs": len(found),
                     "specimen": r["specimens"][0][0]})

json.dump(hits, open("/tmp/silent/usc_sibling.json", "w"))
byc = collections.Counter(h["cls"] for h in hits)
print("string-sibling hits:", len(hits), byc)
print("unique sibling (exactly one):", sum(1 for h in hits if h["n_sibs"] == 1))
print("rows:", sum(h["rows"] for h in hits))
print("rows (unresolved only):", sum(h["rows"] for h in hits if h["cls"] == "C12 unresolved"))
for h in sorted(hits, key=lambda h: -h["rows"])[:18]:
    print(f"  {h['rows']:5d}r {h['rins']:4d}RIN {h['title']} USC {h['section']:12s} -> {h['sibling']:14s}"
          f" ({h['sibling_rows']} corpus rows, {h['kinds']}, {h['n_sibs']} sibs)  {h['specimen'][:60]!r}")
