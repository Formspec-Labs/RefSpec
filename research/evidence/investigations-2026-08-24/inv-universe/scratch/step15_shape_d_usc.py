import pandas as pd
df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/legal_authorities_slim.parquet")
res = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_d_no_marker.json")
usc_rows = res[res.authority_type=="usc"]
idxs = usc_rows["idx"].unique().tolist()
sub = df.loc[idxs]
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 220)
print(sub[["rin","publication_id","authority_text","usc_title","usc_section","usc_section_verdict","authority_in_own_cfr_note","cfr_note_part"]].drop_duplicates().to_string())
