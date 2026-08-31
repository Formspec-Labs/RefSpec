import pandas as pd
sub = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_a_full.json")
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 220)
row = sub[sub.authority_text.str.contains("1.104-1", na=False)]
print(row.T)
