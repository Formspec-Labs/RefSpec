import pandas as pd, json

cfr = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/cfr_references_slim.parquet")
# index by rin -> set of (cfr_title, cfr_part, cfr_section) across ALL editions of that RIN (rule identity persists)
cfr_by_rin = {}
for rin, grp in cfr.groupby("rin"):
    cfr_by_rin[rin] = set(
        (int(t), str(p) if pd.notna(p) else None, str(s) if pd.notna(s) else None)
        for t, p, s in zip(grp.cfr_title, grp.cfr_part, grp.cfr_section)
        if pd.notna(t)
    )

# ---- shape (a): reg-shaped part.section ----
hits = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_a_hits.json")
df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/legal_authorities_slim.parquet")
sub = df.loc[hits["idx"]].copy()
sub["reg_part"] = hits.set_index("idx").loc[hits["idx"], "part"].values
sub["reg_section"] = hits.set_index("idx").loc[hits["idx"], "section"].values

def direct_witness(rin, title, part, section):
    entries = cfr_by_rin.get(rin, set())
    exact = (title, str(part), str(section)) in entries
    part_only = any(t==title and p==str(part) for t,p,s in entries)
    # also try section without letter-suffix variants (loose): section stem match
    return exact, part_only

results_a = []
for idx, row in sub.iterrows():
    exact, part_only = direct_witness(row.rin, int(row.usc_title), row.reg_part, row.reg_section)
    results_a.append({"idx": idx, "cfr_list_exact_match": exact, "cfr_list_part_match": part_only})
ra = pd.DataFrame(results_a)
print("== shape (a): direct CFR_LIST witness ==")
print("exact part.section match:", ra.cfr_list_exact_match.sum(), "of", len(ra))
print("part-only match:", ra.cfr_list_part_match.sum(), "of", len(ra))
ra.to_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_a_direct_witness.json", orient="records")

# ---- shape (b): hyphenated compound ----
dfb = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/hyphen_usc_rows2.parquet")
results_b = []
for idx, row in dfb.iterrows():
    entries = cfr_by_rin.get(row.rin, set())
    exact = any(t==int(row.usc_title) and s==row.usc_section for t,p,s in entries)
    matched_parts = sorted(set(p for t,p,s in entries if t==int(row.usc_title) and s==row.usc_section and p))
    results_b.append({"idx": idx, "cfr_list_exact_section_match": exact, "matched_parts": matched_parts})
rb = pd.DataFrame(results_b)
print()
print("== shape (b): direct CFR_LIST witness (exact cfr_section == usc_section value) ==")
print("exact section match:", rb.cfr_list_exact_section_match.sum(), "of", len(rb))
rb.to_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_direct_witness.json", orient="records")
