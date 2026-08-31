import pandas as pd
df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/legal_authorities_slim.parquet")
sub = df[(df.usc_title==41) & (df.usc_section=="85")]
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 220)
print(sub[["rin","publication_id","authority_text","usc_section_verdict","authority_in_own_cfr_note","cfr_note_part","parse_status"]].drop_duplicates())
print()
print("RINs:", sub.rin.unique())
