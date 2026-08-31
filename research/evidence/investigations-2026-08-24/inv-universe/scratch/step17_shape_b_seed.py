import pandas as pd, random, json, re

df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/hyphen_usc_rows2.parquet")
keys = sorted(df["authority_text"].unique().tolist())
print("total distinct keys:", len(keys))
rng = random.Random(20260823)
sample_keys = rng.sample(keys, 20)
sample_keys_sorted = sorted(sample_keys)
print(json.dumps(sample_keys_sorted, indent=2))

with open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_sample_keys.json","w") as f:
    json.dump(sample_keys_sorted, f, indent=2)
