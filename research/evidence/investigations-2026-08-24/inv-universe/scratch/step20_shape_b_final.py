import pandas as pd, random, json

dfb = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/hyphen_usc_rows2.parquet").reset_index().rename(columns={"index":"idx"})
rb = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_direct_witness.json")
m = dfb.merge(rb, on="idx")

witnessed = m[m.cfr_list_exact_section_match]
print("== shape (b) DIRECTLY witnessed by the rule's own CFR_LIST (structured match) ==")
print("rows:", len(witnessed), "distinct authority_text:", witnessed.authority_text.nunique(), "distinct RINs:", witnessed.rin.nunique())
print()
print("verdict/note crosstab:")
print(witnessed.groupby(["usc_section_verdict","authority_in_own_cfr_note"], dropna=False).size())
print()
g = witnessed.groupby(["usc_title","usc_section","authority_text"]).agg(rows=("rin","size"), rins=("rin","nunique")).reset_index()
pd.set_option("display.max_rows", 300)
pd.set_option("display.width", 220)
print(g.sort_values(["usc_title","usc_section"]).to_string())
witnessed.to_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_witnessed_final.json", orient="records", indent=2)

# seeded 20 over sorted distinct witnessed keys
keys = sorted(witnessed["authority_text"].unique().tolist())
print()
print("distinct witnessed keys:", len(keys))
if len(keys) > 60:
    rng = random.Random(20260823)
    sample_keys = sorted(rng.sample(keys, 20))
else:
    sample_keys = keys
with open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_witnessed_sample_keys.json","w") as f:
    json.dump(sample_keys, f, indent=2)
print("sample size used:", len(sample_keys))
