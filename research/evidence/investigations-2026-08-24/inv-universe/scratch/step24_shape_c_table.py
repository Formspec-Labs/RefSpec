import pandas as pd, json
narrow = pd.read_json("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_c_narrow.json")
cfr = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/cfr_references_slim.parquet")
sample_keys = json.load(open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_c_sample_keys.json"))

for text in sample_keys:
    grp = narrow[narrow.authority_text == text]
    rep = grp.iloc[0]
    cl = cfr[(cfr.rin==rep.rin)]
    cfr_list = sorted(set(f"{t} CFR {p}" for t,p in zip(cl.cfr_title, cl.cfr_part) if pd.notna(t)))[:6]
    print("---")
    print("text:", text)
    print("rows/rins:", len(grp), grp.rin.nunique(), " example rin/ed:", rep.rin, rep.publication_id)
    print("usc_title:", rep.usc_title, " usc_section (parsed):", rep.usc_section, " verdict:", rep.usc_section_verdict)
    print("note:", rep.authority_in_own_cfr_note, rep.cfr_note_part)
    print("cfr_list (any edition, first 6):", cfr_list)
