import pandas as pd, re, json

df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/hyphen_usc_rows2.parquet")
notes = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/notes_all.parquet")

# group notes by title, concat text with part markers for searching
by_title = {}
for title, grp in notes.groupby("cfr_title"):
    # keep list of (part, text) so we can report which part matched
    by_title[title] = list(zip(grp["cfr_part"], grp["authority_note"], grp["source_note"]))

results = []
for _, row in df.iterrows():
    title = row["usc_title"]
    stem, leaf = row["stem"], row["leaf"]
    value = row["usc_section"]  # e.g. "472-8"
    reg_pat = re.compile(rf"(?<!\d)(?P<part>\d+)\.{re.escape(value)}(?!\d)")
    act_pat = re.compile(rf"{title}\s*U\.?\s*S\.?\s*C\.?[A-Za-z]{{0,3}}\.?\s*{stem}(?![\d-])")
    hit_parts = []
    act_witness_parts = []
    for part, note, source in by_title.get(title, []):
        text = note + " " + source
        m = reg_pat.search(text)
        if m:
            hit_parts.append((part, m.group("part")))
            if act_pat.search(text):
                act_witness_parts.append(part)
    results.append({
        "idx": row.name, "usc_title": title, "usc_section": value, "stem": stem, "leaf": leaf,
        "reg_witness_parts": hit_parts, "act_witness_parts": act_witness_parts,
        "has_reg_witness": len(hit_parts) > 0, "has_act_witness": len(act_witness_parts) > 0,
    })

res = pd.DataFrame(results)
print("rows with ANY reg-shape witness (part.stem-leaf appears in some note under this title):", res.has_reg_witness.sum())
print("rows with ALSO an act-section witness (base stem named as issuing authority):", res.has_act_witness.sum())
res.to_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_witness.json", orient="records", indent=2)
