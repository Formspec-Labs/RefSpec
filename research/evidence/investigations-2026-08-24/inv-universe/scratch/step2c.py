import pandas as pd
df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/legal_authorities_slim.parquet")
sub = df[df.authority_text=="40 U.S.C. 102.01, 322, 5331"]
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)
print(sub[["rin","publication_id","ordinal","citation_ordinal","authority_type","parse_status","usc_title","usc_section","usc_section_verdict","authority_in_own_cfr_note","cfr_note_part"]])
