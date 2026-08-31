import json, pandas as pd
recs = []
with open("research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl") as f:
    for line in f:
        r = json.loads(line)
        recs.append({
            "cfr_title": r["cfr_title"], "cfr_part": r["cfr_part"],
            "authority_note": r.get("authority_note") or "",
            "source_note": r.get("source_note") or "",
        })
notes = pd.DataFrame(recs)
notes.to_parquet("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-universe/scratch/notes_all.parquet")
print(len(notes))
