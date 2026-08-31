"""Cross-check: does the artifact's stored 'present' verdict for each flagged
row still reproduce under the CURRENT (in-progress-edited) grammar, or has
the concurrent grammar/note-module edit already changed the answer?
Read-only, import-only.
"""
import json
import sys

ROOT = "/Users/mikewolfd/Work/RefSpec"
sys.path.insert(0, f"{ROOT}/src")

from refspec.registry.cfr_authority_notes import CfrAuthorityNotes, usc_citation  # noqa: E402

OUT_DIR = "/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-note-present"

notes = CfrAuthorityNotes.from_repository(ROOT)


def note_for_key(key: str):
    title_s, part = key.split(":", 1)
    return notes.note(int(title_s), part)


matched = json.load(open(f"{OUT_DIR}/part2_matched_rows.json"))
stem_all = json.load(open(f"{OUT_DIR}/part2_coincidental_stem_all.json"))

still_present = 0
drifted = 0
drift_examples = []
for row in matched:
    note = note_for_key(row["note_key"])
    title_s, section = row["identity"].split(":", 1)
    c = usc_citation(int(title_s), section)
    verdict = note.judge(c) if note is not None else None
    row["current_judge_verdict"] = verdict
    if verdict == "present":
        still_present += 1
    else:
        drifted += 1
        drift_examples.append({"row_key": row["row_key"], "identity": row["identity"], "note_key": row["note_key"], "now": verdict})

print(f"[matched_rows] still present under current grammar: {still_present} / drifted: {drifted}")

stem_still_present = 0
stem_drifted = 0
stem_drift_examples = []
for row in stem_all:
    if row["note_key"] is None:
        row["current_judge_verdict"] = None
        continue
    note = note_for_key(row["note_key"])
    title_s, section = row["identity"].split(":", 1)
    c = usc_citation(int(title_s), section)
    verdict = note.judge(c) if note is not None else None
    row["current_judge_verdict"] = verdict
    if verdict == "present":
        stem_still_present += 1
    else:
        stem_drifted += 1
        stem_drift_examples.append({"row_key": row["row_key"], "identity": row["identity"], "note_key": row["note_key"], "now": verdict})

print(f"[coincidental_stem] still present under current grammar: {stem_still_present} / drifted: {stem_drifted}")
print("drift examples (matched_rows):", json.dumps(drift_examples[:10], indent=2))
print("drift examples (coincidental_stem):", json.dumps(stem_drift_examples[:10], indent=2))

with open(f"{OUT_DIR}/part2_matched_rows.json", "w") as f:
    json.dump(matched, f, indent=2, default=str)
with open(f"{OUT_DIR}/part2_coincidental_stem_all.json", "w") as f:
    json.dump(stem_all, f, indent=2, default=str)

summary = {
    "matched_rows_still_present": still_present,
    "matched_rows_drifted": drifted,
    "coincidental_stem_still_present": stem_still_present,
    "coincidental_stem_drifted": stem_drifted,
}
with open(f"{OUT_DIR}/part3_drift_summary.json", "w") as f:
    json.dump(summary, f, indent=2)
