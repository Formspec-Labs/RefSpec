import json, re, sys
sys.path.insert(0, '/Users/mikewolfd/Work/RefSpec/src')
from refspec.registry import citation_grammar as g

results = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_scan2_full.json'))

plain = []
for r in results:
    for inst in r['instances']:
        if not inst['appendix_context'] and not inst['end_pin'] and not inst['start_pin'] and not inst['in_comma_list_context']:
            plain.append((r, inst))

compound_endpoint = []
prose_between = []
abbrev_asym = []
weird_other = []

for r, inst in plain:
    text = r['authority_text']
    normalized = g._normalize_dashes(text)
    match_text = inst['match_text']
    idx = normalized.find(match_text)
    end_end_pos = idx + len(match_text)
    tail = normalized[end_end_pos:end_end_pos+15]
    # compound endpoint: end immediately followed by -digit (a real compound name suffix truncated by our scan)
    if re.match(r'-\d', tail):
        compound_endpoint.append((r, inst, tail))
        continue
    if re.search(r'^\s*(U\.?S\.?C|C\.?F\.?R)', tail, re.IGNORECASE):
        prose_between.append((r, inst, tail))
        continue
    start_num = int(re.match(r'\d+', inst['start']).group(0))
    end_num_m = re.match(r'\d+', inst['end'])
    end_num = int(end_num_m.group(0)) if end_num_m else None
    if end_num is not None and end_num < start_num and len(inst['end']) <= len(inst['start']):
        abbrev_asym.append((r, inst))
        continue
    weird_other.append((r, inst))

print("compound_endpoint:", len(compound_endpoint), "texts:", len({r['authority_text'] for r,i,t in compound_endpoint}), "rows:", sum(r['row_count'] for r,i,t in compound_endpoint))
print("prose_between (already counted above too):", len(prose_between), "texts:", len({r['authority_text'] for r,i,t in prose_between}))
print("abbrev_asym:", len(abbrev_asym), "texts:", len({r['authority_text'] for r,i in abbrev_asym}), "rows:", sum(r['row_count'] for r,i in abbrev_asym))
print("weird_other:", len(weird_other), "texts:", len({r['authority_text'] for r,i in weird_other}))
print()
print("=== weird_other full list ===")
for r, inst in weird_other:
    print(' ', r['authority_text'], '| rows=', r['row_count'], '| start=', inst['start'], 'end=', inst['end'])
