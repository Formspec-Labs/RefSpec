import pandas as pd, pickle, re

df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/legal_authorities_slim.parquet")
with open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/chapters.pkl","rb") as f:
    chapters = pickle.load(f)
with open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/enumerated.pkl","rb") as f:
    enumerated = pickle.load(f)

bare = df[(df.authority_type=="usc") & df.usc_section.notna() & df.usc_section.str.fullmatch(r"\d+[a-z]?", case=False)].copy()
bare["usc_section_norm"] = bare.usc_section.str.lower()
print("bare-integer usc rows (candidates pool):", len(bare))

def norm_key(row):
    return (int(row.usc_title), row.usc_section_norm) if pd.notna(row.usc_title) else None

bare["key"] = bare.apply(norm_key, axis=1)
bare["is_chapter_number"] = bare["key"].isin(chapters)
bare["is_real_section"] = bare["key"].isin(enumerated)

print()
print("of these, (title,section) also a real chapter number of that title:", bare.is_chapter_number.sum())
sub = bare[bare.is_chapter_number]
print("  distinct authority_text:", sub.authority_text.nunique(), " distinct RINs:", sub.rin.nunique())
print()
print("  cross: also a real SECTION too (candidate ambiguous / two survive):")
print(sub.groupby(["is_real_section"]).size())
print()
print("  verdict/note crosstab among chapter-number matches:")
print(sub.groupby(["usc_section_verdict","authority_in_own_cfr_note"], dropna=False).size())
sub.to_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_c_full.json", orient="records", indent=2)

g = sub.groupby(["usc_title","usc_section","authority_text"]).agg(rows=("rin","size"), rins=("rin","nunique")).reset_index()
pd.set_option("display.max_rows", 300)
pd.set_option("display.width", 220)
print(g.sort_values(["usc_title","usc_section"]).to_string())
