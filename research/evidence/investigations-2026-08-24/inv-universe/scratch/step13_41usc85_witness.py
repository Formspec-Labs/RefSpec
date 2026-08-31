import pandas as pd
cfr = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/cfr_references_slim.parquet")
sub = cfr[(cfr.rin=="3037-AA23") & (cfr.publication_id=="202510")]
print(sub.to_string())

notes = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/notes_all.parquet")
for t, p in sub[["cfr_title","cfr_part"]].drop_duplicates().itertuples(index=False):
    n = notes[(notes.cfr_title==t) & (notes.cfr_part.astype(str)==str(p))]
    print("====", t, p, "====")
    if len(n):
        print(n.iloc[0]["authority_note"][:800])
    else:
        print("(no note record - not in cache)")
