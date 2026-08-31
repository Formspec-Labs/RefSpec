import json
import collections

recs = [json.loads(l) for l in open("population_all.jsonl")]
print("population readings (row,letter):", len(recs))

def rowkey(r):
    return (r["rin"], r["publication_id"], r["ordinal"], r["citation_ordinal"])

rows = {rowkey(r) for r in recs}
texts = {r["authority_text"] for r in recs}
rins = {r["rin"] for r in recs}
print("distinct rows:", len(rows))
print("distinct texts:", len(texts))
print("distinct RINs:", len(rins))

print()
print("== witness 1 (structure) buckets ==")
c1 = collections.Counter(r["structure_bucket"] for r in recs)
for k, v in c1.most_common():
    print(f"  {k}: {v} readings")

print()
print("== witness 2a (note) buckets ==")
c2a = collections.Counter(r["note_bucket"] for r in recs)
for k, v in c2a.most_common():
    print(f"  {k}: {v} readings")

print()
print("== witness 2b (other editions) buckets ==")
c2b = collections.Counter(r["w2b_bucket"] for r in recs)
for k, v in c2b.most_common():
    print(f"  {k}: {v} readings")


def w1_fires(r):
    return r["structure_bucket"] == "witness1-no-such-subsection"


def w2a_fires(r):
    return r["note_bucket"] == "agree-names-NNNx"


def w2b_fires(r):
    return r["w2b_bucket"] in ("text-spells-NNNx", "structural-only-NNNx")


def classify(r):
    w1, w2a, w2b = w1_fires(r), w2a_fires(r), w2b_fires(r)
    if w1 and w2a and w2b:
        return "PUBLISH: 1+2a+2b"
    if w1 and w2a:
        return "PUBLISH: 1+2a"
    if w1 and w2b:
        return "PUBLISH: 1+2b"
    if w1:
        return "CANDIDATE: witness1 alone"
    if w2a or w2b:
        return "CANDIDATE: 2a/2b without 1"
    return "REFUSE: no witness"


print()
print("== cross-tab: publish / candidate / refuse ==")
cclass = collections.Counter(classify(r) for r in recs)
for k, v in sorted(cclass.items()):
    rws = {rowkey(r) for r in recs if classify(r) == k}
    txs = {r["authority_text"] for r in recs if classify(r) == k}
    rns = {r["rin"] for r in recs if classify(r) == k}
    print(f"  {k}: {v} readings / {len(rws)} rows / {len(txs)} texts / {len(rns)} RINs")

# conflict: witness1 fires but note explicitly names bare NNN (disagree)
conflict = [r for r in recs if w1_fires(r) and r["note_bucket"] == "disagree-names-NNN"]
print()
print("CONFLICT (witness1 fires but note names bare NNN):", len(conflict), "readings")
for r in conflict[:10]:
    print(" ", r["rin"], r["publication_id"], r["title"], r["section"], r["letter"], "->", r["nnnx"],
          "note_part=", r["note_part"])

# ambiguous-both-real but a witness still prefers NNNx
amb_but_witnessed = [r for r in recs if r["structure_bucket"] == "ambiguous-both-real" and (w2a_fires(r) or w2b_fires(r))]
print()
print("Ambiguous-by-structure but 2a/2b still prefers NNNx:", len(amb_but_witnessed))

publish = [r for r in recs if classify(r).startswith("PUBLISH")]
candidate = [r for r in recs if classify(r).startswith("CANDIDATE")]
refuse = [r for r in recs if classify(r).startswith("REFUSE")]

print()
print("== tail lesson (item 5), among PUBLISH readings ==")
tail_rows = [r for r in publish if r["has_tail"]]
print("PUBLISH readings with a further tail in the text:", len(tail_rows), "/", len(publish))
tail_kept = [r for r in tail_rows if r["affirmed_tail_reading"] is not None]
tail_dropped = [r for r in tail_rows if r["affirmed_tail_reading"] is None]
print("  of those, tail affirmed by oracle (identity keeps the tail):", len(tail_kept))
print("  of those, tail NOT affirmed by oracle (identity would be bare NNNx, tail unconfirmed):", len(tail_dropped))
for r in tail_kept[:15]:
    print("   KEEP", r["rin"], r["publication_id"], r["section"], r["letter"], "text_tail=", r["text_tail"],
          "-> candidate_identity=", r["candidate_identity"], " | text:", r["authority_text"][:90])
for r in tail_dropped[:15]:
    print("   DROP?", r["rin"], r["publication_id"], r["section"], r["letter"], "text_tail=", r["text_tail"],
          "-> candidate_identity=", r["candidate_identity"], " | text:", r["authority_text"][:90])

with open("publish_rows.jsonl", "w") as f:
    for r in publish:
        f.write(json.dumps(r) + "\n")
with open("candidate_rows.jsonl", "w") as f:
    for r in candidate:
        f.write(json.dumps(r) + "\n")
with open("refuse_rows.jsonl", "w") as f:
    for r in refuse:
        f.write(json.dumps(r) + "\n")

print()
print("wrote publish_rows.jsonl (%d), candidate_rows.jsonl (%d), refuse_rows.jsonl (%d)" % (
    len(publish), len(candidate), len(refuse)))
