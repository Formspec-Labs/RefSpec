import pandas as pd, json

witnessed = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_witnessed_final.json")
cfr = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/cfr_references_slim.parquet")

rows_out = []
for text, grp in witnessed.groupby("authority_text"):
    rep = grp.iloc[0]
    cl = cfr[(cfr.rin==rep.rin)]
    cfr_list_all_editions = sorted(set(f"{t} CFR {p}" + (f".{s}" if pd.notna(s) else "") for t,p,s in zip(cl.cfr_title, cl.cfr_part, cl.cfr_section) if pd.notna(t)))
    matched = [x for x in cfr_list_all_editions if x.endswith("."+rep.usc_section)]
    rows_out.append({
        "authority_text": text, "rows": len(grp), "rins": grp.rin.nunique(),
        "rin": rep.rin, "usc_title": int(rep.usc_title), "usc_section_parsed": rep.usc_section,
        "usc_section_verdict": rep.usc_section_verdict, "note_verdict": rep.authority_in_own_cfr_note,
        "cfr_list_matched_entries": matched,
        "cfr_list_full": cfr_list_all_editions[:8],
    })
for r in sorted(rows_out, key=lambda r: r["authority_text"]):
    print("---")
    for k,v in r.items():
        print(f"  {k}: {v}")
