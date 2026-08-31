import json
import random

def load(path):
    return [json.loads(l) for l in open(path)]

publish = load("publish_rows.jsonl")
candidate = load("candidate_rows.jsonl")
refuse = load("refuse_rows.jsonl")

def rowkey(r):
    return (r["rin"], r["publication_id"], r["ordinal"], r["citation_ordinal"])

def dedupe_rows(recs):
    seen = {}
    for r in recs:
        seen.setdefault(rowkey(r), r)
    return list(seen.values())

publish_rows = sorted(dedupe_rows(publish), key=rowkey)
nonpublish_rows = sorted(dedupe_rows(candidate + refuse), key=rowkey)

print("unique publish rows:", len(publish_rows))
print("unique non-publish (candidate+refuse) rows:", len(nonpublish_rows))

rnd = random.Random(20260823)
publish_sample = rnd.sample(publish_rows, 15)
rnd2 = random.Random(20260823)
nonpublish_sample = rnd2.sample(nonpublish_rows, 10)

with open("specimens_publish.json", "w") as f:
    json.dump(publish_sample, f, indent=2)
with open("specimens_nonpublish.json", "w") as f:
    json.dump(nonpublish_sample, f, indent=2)

print()
print("=== 15 WOULD-PUBLISH SPECIMENS ===")
for r in publish_sample:
    print(f"- {r['rin']} {r['publication_id']} title {r['title']} '{r['section']}({r['letter']})' -> {r['candidate_identity']}")
    print(f"    text: {r['authority_text']}")
    print(f"    structure: {r['structure_bucket']} | note: {r['note_bucket']} ({r['note_part']}) | w2b: {r['w2b_bucket']} ({r['w2b_evidence']})")

print()
print("=== 10 REFUSED / ONE-WITNESS SPECIMENS ===")
for r in nonpublish_sample:
    cls = "witness1-alone" if r["structure_bucket"] == "witness1-no-such-subsection" else (
        "2a/2b-without-1" if (r["note_bucket"] == "agree-names-NNNx" or r["w2b_bucket"] in ("text-spells-NNNx","structural-only-NNNx")) else "no-witness"
    )
    print(f"- {r['rin']} {r['publication_id']} title {r['title']} '{r['section']}({r['letter']})' -> {r['nnnx']}  [{cls}]")
    print(f"    text: {r['authority_text']}")
    print(f"    structure: {r['structure_bucket']} | note: {r['note_bucket']} ({r['note_part']}) | w2b: {r['w2b_bucket']} ({r['w2b_evidence']})")
