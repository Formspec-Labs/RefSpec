import pandas as pd, re, json

df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/legal_authorities_slim.parquet")
hits = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_a_hits.json")
cfr_refs = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/cfr_references_slim.parquet")
notes = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/notes_all.parquet")
notes_idx = {}
for _, r in notes.iterrows():
    notes_idx.setdefault((r.cfr_title, str(r.cfr_part).lower().lstrip("0") or "0"), []).append(r.authority_note)

sub = df.loc[hits["idx"]].copy()
sub["reg_part"] = hits.set_index("idx").loc[hits["idx"], "part"].values
sub["reg_section"] = hits.set_index("idx").loc[hits["idx"], "section"].values

def decisive_line(title, part, value):
    key = (title, str(part).lower().lstrip("0") or "0")
    for note in notes_idx.get(key, []):
        pat = re.compile(rf"[^.]*\b{re.escape(str(part))}\.{re.escape(value)}\b[^.]*\.")
        m = pat.search(note)
        if m:
            return m.group().strip()
    return None

rows_out = []
for text, grp in sub.groupby("authority_text"):
    rep = grp.iloc[0]
    reg_part, reg_section = rep["reg_part"], rep["reg_section"]
    cl = cfr_refs[(cfr_refs.rin==rep.rin) & (cfr_refs.publication_id==rep.publication_id)]
    cfr_list = sorted(set(f"{t} CFR {p}" for t, p in zip(cl.cfr_title, cl.cfr_part) if pd.notna(t)))
    part_matches = any(str(p).lstrip("0") == str(reg_part).lstrip("0") for p in cl.cfr_part if pd.notna(p))
    dline = decisive_line(int(rep.usc_title), reg_part, reg_section)
    rows_out.append({
        "authority_text": text,
        "rows": len(grp), "rins": grp.rin.nunique(),
        "rin_example": rep.rin, "edition_example": rep.publication_id,
        "usc_title": int(rep.usc_title), "usc_section_parsed": rep.usc_section,
        "reg_part_dot_section": f"{reg_part}.{reg_section}",
        "cfr_list": cfr_list,
        "cfr_list_names_the_part": part_matches,
        "usc_section_verdict": rep.usc_section_verdict,
        "authority_in_own_cfr_note": rep.authority_in_own_cfr_note,
        "cfr_note_part": rep.cfr_note_part,
        "decisive_note_line": dline,
    })

out = pd.DataFrame(rows_out).sort_values("authority_text")
pd.set_option("display.max_colwidth", 300)
with open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_a_witness_table.json","w") as f:
    json.dump(rows_out, f, indent=2, default=str)
print(len(out))
print("cfr_list names the reg part:", out["cfr_list_names_the_part"].sum(), "of", len(out))
print("has a decisive note line found:", out["decisive_note_line"].notna().sum())
