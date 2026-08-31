import pandas as pd
df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/hyphen_usc_rows2.parquet").reset_index().rename(columns={"index":"idx"})
res = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_witness.json")
m = df.merge(res[["idx","reg_witness_parts","act_witness_parts","has_reg_witness","has_act_witness"]], on="idx")
witnessed = m[m.has_reg_witness]
print("== shape (b) reg-suffix, witnessed subset ==")
print("rows:", len(witnessed), "distinct authority_text:", witnessed.authority_text.nunique(), "distinct RINs:", witnessed.rin.nunique())
print()
print("verdict/note crosstab (witnessed):")
print(witnessed.groupby(["usc_section_verdict","authority_in_own_cfr_note"], dropna=False).size())
print()
g = witnessed.groupby(["usc_title","usc_section","authority_text"]).agg(rows=("rin","size"), rins=("rin","nunique")).reset_index()
pd.set_option("display.max_rows", 200)
pd.set_option("display.width", 200)
print(g.sort_values(["usc_title","usc_section"]).to_string())
witnessed.to_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_witnessed_full.json", orient="records", indent=2)

print()
print("== NOT witnessed (740 rows) - verdict distribution (candidates for real compound sections OR unwitnessed regs) ==")
not_w = m[~m.has_reg_witness]
print("rows:", len(not_w), "distinct authority_text:", not_w.authority_text.nunique())
print(not_w.groupby(["usc_section_verdict"], dropna=False).size())
not_w.to_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_not_witnessed_full.json", orient="records", indent=2)
