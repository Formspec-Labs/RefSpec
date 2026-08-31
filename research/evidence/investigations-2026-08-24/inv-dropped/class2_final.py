import json, re, random
results = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_scan3_full.json'))

def bucket_key(inst):
    if inst['appendix_context']:
        return 'appendix'
    if inst['prose_between_full_citations']:
        return 'prose_trap'
    if inst['end_pin'] or inst['start_pin']:
        return 'subsection'
    if inst['in_comma_list_context']:
        return 'list'
    if inst['compound_endpoint']:
        return 'compound'
    start_num_m = re.match(r'\d+', inst['start'])
    end_num_m = re.match(r'\d+', inst['end'])
    if start_num_m and end_num_m:
        sn, en = int(start_num_m.group(0)), int(end_num_m.group(0))
        if en < sn and len(inst['end']) <= 3:
            return 'abbrev'
    return 'unclear'

by_text = {r['authority_text']: r for r in results}
genuine_texts = set()
for r in results:
    for inst in r['instances']:
        k = bucket_key(inst)
        if k not in ('appendix', 'prose_trap'):
            genuine_texts.add(r['authority_text'])

print("genuine (non-appendix, non-trap) CLASS2 population size:", len(genuine_texts))

sorted_keys = sorted(genuine_texts)
rng = random.Random(20260823)
seed20 = sorted(rng.sample(sorted_keys, 20))
print("=== seeded 20 (CLASS 2) ===")
for t in seed20:
    r = by_text[t]
    tags = sorted({bucket_key(i) for i in r['instances'] if bucket_key(i) not in ('appendix','prose_trap')})
    print(t, '| rows=', r['row_count'], '| rin=', r['sample_rin'], '| editions=', r['editions'], '| subshapes=', tags)
    for inst in r['instances']:
        print('     range:', inst['match_text'], '-> start=', inst['start'], 'end=', inst['end'], 'bucket=', bucket_key(inst))

json.dump(seed20, open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_seed20.json','w'), indent=1)
