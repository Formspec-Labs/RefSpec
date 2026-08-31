import pandas as pd, json, re

df = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/hyphen_usc_rows2.parquet")
cfr_refs = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/cfr_references_slim.parquet")
notes = pd.read_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/notes_all.parquet")
notes_by_title = {}
for _, r in notes.iterrows():
    notes_by_title.setdefault(r.cfr_title, []).append((str(r.cfr_part), r.authority_note, r.source_note or ""))

sample_keys = json.load(open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_sample_keys.json"))

def find_witness(title, value):
    # value like "472-8" (may itself contain full hyphen chain) -- search "part.value" pattern
    hits = []
    pat = re.compile(rf"(?<!\d)(\d+)\.{re.escape(value)}(?!\d)")
    for part, note, source in notes_by_title.get(title, []):
        text = note + " " + source
        m = pat.search(text)
        if m:
            sent_pat = re.compile(rf"[^.]*\b{re.escape(m.group(0))}\b[^.]*\.")
            sm = sent_pat.search(text)
            hits.append((part, sm.group().strip() if sm else m.group(0)))
    return hits

rows_out = []
for text in sample_keys:
    grp = df[df.authority_text == text]
    rep = grp.iloc[0]
    cl = cfr_refs[(cfr_refs.rin==rep.rin) & (cfr_refs.publication_id==rep.publication_id)]
    cfr_list = sorted(set(f"{t} CFR {p}" for t, p in zip(cl.cfr_title, cl.cfr_part) if pd.notna(t)))
    title = int(rep.usc_title)
    witnesses = find_witness(title, rep.usc_section)
    rows_out.append({
        "authority_text": text,
        "rows": len(grp), "rins": grp.rin.nunique(),
        "rin_example": rep.rin, "edition_example": rep.publication_id,
        "usc_title": title, "usc_section_parsed": rep.usc_section,
        "usc_section_verdict": rep.usc_section_verdict,
        "authority_in_own_cfr_note": rep.authority_in_own_cfr_note,
        "cfr_note_part": rep.cfr_note_part,
        "cfr_list": cfr_list,
        "reg_witnesses": witnesses,
    })

with open("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/shape_b_sample_table.json","w") as f:
    json.dump(rows_out, f, indent=2, default=str)

for r in rows_out:
    print("---")
    print("text:", r["authority_text"])
    print("rows/rins:", r["rows"], r["rins"], " example:", r["rin_example"], r["edition_example"])
    print("usc:", r["usc_title"], r["usc_section_parsed"], " verdict:", r["usc_section_verdict"])
    print("note:", r["authority_in_own_cfr_note"], r["cfr_note_part"])
    print("cfr_list:", r["cfr_list"])
    print("reg_witnesses:", r["reg_witnesses"])
