import pandas as pd, random, json
narrow = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_c_narrow.json")
keys = sorted(narrow["authority_text"].unique().tolist())
print("total distinct keys:", len(keys))
rng = random.Random(20260823)
sample_keys = sorted(rng.sample(keys, 20))
print(json.dumps(sample_keys, indent=2))
with open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_c_sample_keys.json","w") as f:
    json.dump(sample_keys, f, indent=2)
