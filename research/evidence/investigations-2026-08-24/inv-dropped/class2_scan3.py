import json, re, sys
sys.path.insert(0, '/Users/mikewolfd/Work/RefSpec/src')
from refspec.registry import citation_grammar as g

USC_SECTION_TOKEN = g._USC_SECTION_TOKEN
PINPOINT = g._USC_PINPOINT.pattern

RANGE_SCAN = re.compile(
    rf"(?P<start>{USC_SECTION_TOKEN})(?P<start_pin>(?:{PINPOINT})?)\s*"
    rf"(?P<sep>to|through|thru|-)\s*"
    rf"(?P<end>{USC_SECTION_TOKEN})\s*(?P<end_pin>(?:{PINPOINT})?)",
    re.IGNORECASE,
)
LIST_SEP_BEFORE = re.compile(r"(?:,|\band\b|\bor\b)\s*$", re.IGNORECASE)

data = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_range_texts_raw.json'))

def whole_rows(text):
    cits = g.parse_authority_citation(text)
    return [
        {'authority_type': c.authority_type, 'parse_status': c.parse_status,
         'usc_title': c.usc_title, 'usc_section': c.usc_section, 'usc_section_end': c.usc_section_end,
         'usc_appendix': c.usc_appendix, 'usc_section_span_rule': c.usc_section_span_rule}
        for c in cits
    ]

results = []
for row in data:
    text = row['authority_text']
    normalized = g._normalize_dashes(text)
    rows = whole_rows(text)
    usc_rows_no_end = {r['usc_section'] for r in rows if r['usc_section'] and not r['usc_section_end'] and r['authority_type']=='usc'}
    end_values_present = {r['usc_section_end'] for r in rows if r['usc_section_end']}
    appendix_rows = {r['usc_section'] for r in rows if r['usc_appendix'] and r['usc_section']}

    instances = []
    for m in RANGE_SCAN.finditer(normalized):
        sep = m.group('sep')
        if sep == '-':
            sep_span = normalized[m.end('start') + len(m.group('start_pin')):m.start('end')]
            if not re.fullmatch(r'\s+-\s+', sep_span):
                continue
        start_tok = g._usc_section(m.group('start'))
        end_tok = g._usc_section(m.group('end'))
        if start_tok not in usc_rows_no_end:
            continue
        end_present = end_tok in end_values_present
        if end_present:
            continue
        before = normalized[max(0, m.start()-20):m.start()]
        after_end_pos = m.end()
        after = normalized[after_end_pos:after_end_pos+15]
        in_list = bool(LIST_SEP_BEFORE.search(before))
        appendix_context = start_tok in appendix_rows
        compound_endpoint = bool(re.match(r'-\d', after))
        prose_between = bool(re.match(r'\s*(U\.?S\.?C|C\.?F\.?R)', after, re.IGNORECASE))
        instances.append({
            'match_text': normalized[m.start():m.end()],
            'start': start_tok, 'end': end_tok, 'sep': sep,
            'start_pin': m.group('start_pin'), 'end_pin': m.group('end_pin'),
            'in_comma_list_context': in_list,
            'appendix_context': appendix_context,
            'compound_endpoint': compound_endpoint,
            'prose_between_full_citations': prose_between,
        })

    if instances:
        results.append({
            'authority_text': text, 'row_count': row['row_count'],
            'sample_rin': row['sample_rin'], 'editions': row['editions'],
            'instances': instances, 'whole_rows': rows,
        })

json.dump(results, open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_scan3_full.json','w'), indent=1)

from collections import Counter, defaultdict
lost = [(r, inst) for r in results for inst in r['instances']]
print("total lost instances:", len(lost))

def bucket_key(inst):
    if inst['appendix_context']:
        return 'appendix (excl, #60)'
    if inst['prose_between_full_citations']:
        return 'trap: prose "to" between two full citations'
    if inst['end_pin'] or inst['start_pin']:
        return 'endpoint has parenthesized subsection'
    if inst['in_comma_list_context']:
        return 'range embedded in comma/and/or list'
    if inst['compound_endpoint']:
        return 'endpoint is a compound (hyphenated) section name'
    # remaining: check abbrev asymmetry
    start_num_m = re.match(r'\d+', inst['start'])
    end_num_m = re.match(r'\d+', inst['end'])
    if start_num_m and end_num_m:
        sn, en = int(start_num_m.group(0)), int(end_num_m.group(0))
        if en < sn and len(inst['end']) <= 3:
            return 'shorthand endpoint never expanded (to/through gets no abbreviation, unlike hyphen)'
    return 'other/unclear'

import re as _re
cnt = Counter(); texts_by = defaultdict(set); rows_by = defaultdict(int)
for r, inst in lost:
    k = bucket_key(inst)
    cnt[k]+=1
    if r['authority_text'] not in texts_by[k]:
        rows_by[k]+=r['row_count']
    texts_by[k].add(r['authority_text'])

for k,c in cnt.most_common():
    print(f"{k}: instances={c} texts={len(texts_by[k])} rows={rows_by[k]}")

json.dump({k: sorted(texts_by[k]) for k in texts_by}, open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_bucket_texts.json','w'), indent=1)
