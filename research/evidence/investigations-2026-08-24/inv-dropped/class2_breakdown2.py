import json
from collections import Counter, defaultdict
results = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_scan2_full.json'))

lost = [(r, inst) for r in results for inst in r['instances']]
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
        tags.append('plain_bare_to_bare')
    return tuple(sorted(set(tags)))

cnt = Counter()
texts_by_bucket = defaultdict(set)
rows_by_text_bucket = defaultdict(int)
for r, inst in lost:
    k = bucket_key(inst)
    cnt[k]+=1
    if r['authority_text'] not in texts_by_bucket[k]:
        rows_by_text_bucket[k]+= r['row_count']
    texts_by_bucket[k].add(r['authority_text'])

for k, c in cnt.most_common():
    print(k, '-> instances=', c, 'distinct texts=', len(texts_by_bucket[k]), 'rows(sum over those texts)=', rows_by_text_bucket[k])

print()
print("sep breakdown:")
print(Counter(inst['sep'].lower() for r,inst in lost))

print()
print("=== appendix bucket detail (cross-check vs #60's 162/33) ===")
appx = [(r,inst) for r,inst in lost if inst['appendix_context']]
print("instances:", len(appx), "texts:", len({r['authority_text'] for r,inst in appx}))
for r, inst in appx[:10]:
    print(' ', r['authority_text'], '| rows=', r['row_count'], '| match=', inst['match_text'])
