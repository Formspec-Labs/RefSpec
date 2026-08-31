import pandas as pd, re
df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/legal_authorities_slim.parquet")

# bare N{3,4}.N{3,4} anywhere in text, with NO "USC"/"U.S.C"/"CFR" marker within 15 chars before it
pat = re.compile(r"(?<!\d)\d{3,4}\.\d{3,4}(?!\d)")
usc_marker = re.compile(r"U\.?\s*S\.?\s*C", re.IGNORECASE)
cfr_marker = re.compile(r"CFR", re.IGNORECASE)

def classify(text):
    if not isinstance(text, str):
        return []
    out = []
    for m in pat.finditer(text):
        prefix = text[max(0, m.start()-20):m.start()]
        out.append((m.group(), bool(usc_marker.search(prefix)), bool(cfr_marker.search(prefix))))
    return out

mask = df["authority_text"].fillna("").str.contains(r"\d{3,4}\.\d{3,4}", regex=True)
sub = df[mask].copy()
print("rows with any NNN(N).NNN(N) pattern in authority_text:", len(sub))

results = []
for idx, row in sub.iterrows():
    for token, has_usc, has_cfr in classify(row["authority_text"]):
        results.append({"idx": idx, "token": token, "has_usc_marker_nearby": has_usc, "has_cfr_marker_nearby": has_cfr,
                         "authority_type": row["authority_type"], "parse_status": row["parse_status"],
                         "rin": row["rin"], "authority_text": row["authority_text"]})
res = pd.DataFrame(results)
print(res.groupby(["has_usc_marker_nearby","has_cfr_marker_nearby","authority_type"]).size())
res.to_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_d_all.json", orient="records", indent=2)

no_marker = res[~res.has_usc_marker_nearby & ~res.has_cfr_marker_nearby]
print()
print("== no title/scheme marker within 20 chars (the true 'bare OSHA-shape' pool) ==")
print("rows:", len(no_marker), "distinct texts:", no_marker.authority_text.nunique(), "distinct RINs:", no_marker.rin.nunique())
print(no_marker.groupby(["authority_type","parse_status"]).size())
no_marker.to_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_d_no_marker.json", orient="records", indent=2)
