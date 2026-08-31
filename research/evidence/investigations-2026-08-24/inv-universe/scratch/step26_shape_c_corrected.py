import pandas as pd, json

sub = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_c_full.json")
print("original is_chapter_number pool:", len(sub))

# Use the pinned, authoritative usc_section_verdict instead of my own re-derived is_real_section,
# which mishandled appendix citations (usc_appendix rows are judged against a different, appendix-only
# table the module's `enumerated` deliberately excludes).
corrected = sub[sub.usc_section_verdict != "exists"].copy()
print("corrected pool (verdict != 'exists'):", len(corrected))
print("distinct authority_text:", corrected.authority_text.nunique(), "distinct RINs:", corrected.rin.nunique())
print()
print("verdict/note crosstab (corrected):")
print(corrected.groupby(["usc_section_verdict","authority_in_own_cfr_note"], dropna=False).size())
print()
# how many of the previously-excluded "exists" rows are usc_appendix?  can't check directly (no usc_appendix col pulled)
# but let's at least see title distribution difference
print(corrected.usc_title.value_counts().head(15))
corrected.to_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_c_narrow_CORRECTED.json", orient="records", indent=2)
