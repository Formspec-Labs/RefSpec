import json
results = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_scan_full.json'))

lost = []
for r in results:
    for inst in r['instances']:
        if not inst['end_present_in_output']:
            lost.append((r, inst))

print("total lost instances:", len(lost))

def bucket_key(inst):
    tags = []
    if inst['appendix_context']:
        tags.append('appendix')
    if inst['end_pin']:
        tags.append('end_has_subsection')
    if inst['start_pin']:
        tags.append('start_has_subsection')
    if inst['in_comma_list_context']:
        tags.append('in_comma_list')
    if not tags:
        tags.append('plain')
    return tuple(sorted(set(tags)))

from collections import Counter, defaultdict
cnt = Counter()
rows_by_bucket = defaultdict(int)
texts_by_bucket = defaultdict(set)
for r, inst in lost:
    k = bucket_key(inst)
    cnt[k]+=1
    rows_by_bucket[k]+= r['row_count']
    texts_by_bucket[k].add(r['authority_text'])

for k, c in cnt.most_common():
    print(k, '-> instances=', c, 'rows(text-level, may double count if text has multiple buckets)=', rows_by_bucket[k], 'distinct texts=', len(texts_by_bucket[k]))

print()
print("sep type breakdown among lost:")
sepcnt = Counter(inst['sep'].lower() for r,inst in lost)
print(sepcnt)

print()
print("appendix_context count (to exclude / cross check vs #60's 162 rows/33 texts):")
appendix_lost = [(r,inst) for r,inst in lost if inst['appendix_context']]
print("instances:", len(appendix_lost), "distinct texts:", len({r['authority_text'] for r,inst in appendix_lost}), "sum rows:", sum(r['row_count'] for r,inst in appendix_lost))
