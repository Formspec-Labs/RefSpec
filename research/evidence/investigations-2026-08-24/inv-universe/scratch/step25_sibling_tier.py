import pandas as pd
dfb = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/hyphen_usc_rows2.parquet").reset_index().rename(columns={"index":"idx"})
rb = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_direct_witness.json")
m = dfb.merge(rb, on="idx")
witnessed = m[m.cfr_list_exact_section_match]
not_w = m[~m.cfr_list_exact_section_match]

witnessed_stems = set(zip(witnessed.rin, witnessed.stem))
sibling = not_w[not_w.apply(lambda r: (r.rin, r.stem) in witnessed_stems, axis=1)]
print("sibling-tier rows (same RIN + stem as a directly-witnessed row, but this leaf itself not witnessed):", len(sibling))
print("distinct texts:", sibling.authority_text.nunique(), "distinct RINs:", sibling.rin.nunique())
pd.set_option("display.max_columns", None); pd.set_option("display.width",200)
print(sibling[["rin","authority_text","usc_section","usc_section_verdict","authority_in_own_cfr_note"]].drop_duplicates().to_string())
