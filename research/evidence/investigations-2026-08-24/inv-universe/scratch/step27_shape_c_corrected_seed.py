import pandas as pd, random, json
narrow = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_c_narrow_CORRECTED.json")
keys = sorted(narrow["authority_text"].unique().tolist())
print("distinct keys:", len(keys))
rng = random.Random(20260823)
sample_keys = sorted(rng.sample(keys, 20))
print(json.dumps(sample_keys, indent=2))
with open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_c_CORRECTED_sample_keys.json","w") as f:
    json.dump(sample_keys, f, indent=2)

g = narrow.groupby(["usc_title","usc_section","authority_text"]).agg(rows=("rin","size"), rins=("rin","nunique")).reset_index()
pd.set_option("display.max_rows", 60); pd.set_option("display.width", 200)
print(g.sort_values("rows", ascending=False).head(30).to_string())
