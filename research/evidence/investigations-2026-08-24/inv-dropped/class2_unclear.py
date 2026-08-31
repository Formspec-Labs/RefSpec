import json, re
results = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_scan3_full.json'))

def bucket_key(inst):
    if inst['appendix_context']:
        return 'appendix'
    if inst['prose_between_full_citations']:
        return 'prose'
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

for r in results:
    for inst in r['instances']:
        if bucket_key(inst) == 'unclear':
            print(r['authority_text'], '| rows=', r['row_count'], '| match=', inst['match_text'], '| start=', inst['start'], 'end=', inst['end'])
