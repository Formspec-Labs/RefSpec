"""The two summary tables in the report, from triage.json + the working DB.

Run 2026-08-22 as two inline heredocs; this file is both, verbatim in
substance: (1) per-class pairs / distinct texts / rows / parse_status=ok rows,
(2) the three evidence groups A/B/C with RIN counts.
"""

import json, collections, duckdb

recs = json.load(open('/tmp/silent/usc_triage.json'))
con = duckdb.connect('/tmp/silent/usc.duckdb', read_only=True)

rt = collections.defaultdict(set); ok = collections.Counter(); rn = collections.defaultdict(set)
for t, s, a, txt in con.execute(
        "SELECT DISTINCT usc_title,usc_section,usc_appendix,authority_text FROM rowsv WHERE NOT exists_anywhere").fetchall():
    rt[(t, s, a)].add(txt)
for t, s, a, n in con.execute(
        "SELECT usc_title,usc_section,usc_appendix,count(*) FROM rowsv WHERE NOT exists_anywhere AND parse_status='ok' GROUP BY 1,2,3").fetchall():
    ok[(t, s, a)] = n
for t, s, a, r in con.execute(
        "SELECT DISTINCT usc_title,usc_section,usc_appendix,rin FROM rowsv WHERE NOT exists_anywhere").fetchall():
    rn[(t, s, a)].add(r)

# (1) per class
tx = collections.defaultdict(set); ag = collections.defaultdict(lambda: [0, 0, 0])
for r in recs:
    k = r['cls']; key = (r['title'], r['section'], r['appendix'])
    tx[k] |= rt[key]; ag[k][0] += 1; ag[k][1] += r['rows']; ag[k][2] += ok[key]
print(f"{'class':34s}{'pairs':>7s}{'texts':>7s}{'rows':>8s}{'ok-rows':>9s}")
tot = [0, 0, 0]; allt = set()
for k in sorted(ag):
    print(f"{k:34s}{ag[k][0]:7d}{len(tx[k]):7d}{ag[k][1]:8d}{ag[k][2]:9d}")
    tot[0] += ag[k][0]; tot[1] += ag[k][1]; tot[2] += ag[k][2]; allt |= tx[k]
print(f"{'TOTAL':34s}{tot[0]:7d}{len(allt):7d}{tot[1]:8d}{tot[2]:9d}")

# (2) the three groups
G = {'A derivable parser defect': {'C0', 'C1', 'C2', 'C3', 'C7', 'C8', 'C8b', 'C8c'},
     'B real when written / oracle window': {'C5', 'C6', 'C9'},
     'C detected, target is a lead': {'C10', 'C11', 'C12'}}
print()
for g, ks in G.items():
    sel = [r for r in recs if r['cls'].split()[0] in ks]
    t = set(); ri = set(); rows = 0; okr = 0
    for r in sel:
        k = (r['title'], r['section'], r['appendix']); t |= rt[k]; ri |= rn[k]; rows += r['rows']; okr += ok[k]
    print(f"{g:38s} pairs={len(sel):5d} texts={len(t):5d} rows={rows:6d} ok-rows={okr:6d} RINs={len(ri):5d}")
