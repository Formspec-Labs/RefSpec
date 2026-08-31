import pandas as pd, json
hits = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_a_hits.json")
df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/legal_authorities_slim.parquet")
sub = df.loc[hits["idx"]].copy()
sub["reg_part"] = hits.set_index("idx").loc[hits["idx"], "part"].values
sub["reg_section"] = hits.set_index("idx").loc[hits["idx"], "section"].values
ra = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_a_direct_witness.json")
sub = sub.reset_index().rename(columns={"index":"idx"}).merge(ra, on="idx")

exact = sub[sub.cfr_list_exact_match]
print("== shape (a) exact CFR_LIST match ==")
print("rows:", len(exact), "distinct texts:", exact.authority_text.nunique(), "distinct RINs:", exact.rin.nunique())
print()
print("verdict/note crosstab:")
print(exact.groupby(["usc_section_verdict","authority_in_own_cfr_note"], dropna=False).size())
print()
g = exact.groupby(["authority_text","reg_part","reg_section","rin"]).size().reset_index(name="rows")
pd.set_option("display.max_rows", 100)
pd.set_option("display.width", 200)
print(g.to_string())
