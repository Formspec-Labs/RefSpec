import pandas as pd, json
narrow = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_c_narrow_CORRECTED.json")
cfr = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/cfr_references_slim.parquet")
sample_keys = json.load(open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_c_CORRECTED_sample_keys.json"))

out = []
for text in sample_keys:
    grp = narrow[narrow.authority_text == text]
    rep = grp.iloc[0]
    cl = cfr[(cfr.rin==rep.rin)]
    cfr_list = sorted(set(f"{t} CFR {p}" for t,p in zip(cl.cfr_title, cl.cfr_part) if pd.notna(t)))[:6]
    row = {
        "text": text, "rows": len(grp), "rins": int(grp.rin.nunique()),
        "rin_example": rep.rin, "edition_example": rep.publication_id,
        "usc_title": int(rep.usc_title), "usc_section_parsed": rep.usc_section,
        "verdict": rep.usc_section_verdict, "note": rep.authority_in_own_cfr_note, "cfr_note_part": rep.cfr_note_part,
        "cfr_list": cfr_list,
    }
    out.append(row)
    print("---")
    for k,v in row.items():
        print(f"  {k}: {v}")
with open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/shape_c_seeded20_detail.json","w") as f:
    json.dump(out, f, indent=2, default=str)
