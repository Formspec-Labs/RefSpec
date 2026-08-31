import json, re, sys
sys.path.insert(0, '/Users/mikewolfd/Work/RefSpec/src')
from refspec.registry import citation_grammar as g

USC_SECTION_TOKEN = g._USC_SECTION_TOKEN
PINPOINT = g._USC_PINPOINT.pattern
APPENDIX_MARKER = g._APPENDIX_MARKER

RANGE_SCAN = re.compile(
    rf"(?P<start>{USC_SECTION_TOKEN})(?P<start_pin>(?:{PINPOINT})?)\s*"
    rf"(?P<sep>to|through|thru|-)\s*"
    rf"(?P<end>{USC_SECTION_TOKEN})\s*(?P<end_pin>(?:{PINPOINT})?)",
    re.IGNORECASE,
)

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
    # rows that ARE real usc rows with a start section but NO end -- candidates for a lost range
    usc_rows_no_end = {r['usc_section'] for r in rows if r['usc_section'] and not r['usc_section_end'] and r['authority_type']=='usc'}
    usc_rows_with_end = {r['usc_section'] for r in rows if r['usc_section'] and r['usc_section_end'] and r['authority_type']=='usc'}
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
            continue  # start isn't a real emitted USC row missing its end -> out of scope
        end_present = end_tok in end_values_present
        if end_present:
            continue  # this specific range's end IS captured somewhere (not lost)
        before = normalized[max(0, m.start()-60):m.start()]
        after = normalized[m.end():m.end()+30]
        in_comma_list = bool(re.search(r',\s*$', before))
        appendix_context = start_tok in appendix_rows
        instances.append({
            'match_text': normalized[m.start():m.end()],
            'start': start_tok, 'end': end_tok, 'sep': sep,
            'start_pin': m.group('start_pin'), 'end_pin': m.group('end_pin'),
            'in_comma_list_context': in_comma_list,
            'appendix_context': appendix_context,
        })

    if instances:
        results.append({
            'authority_text': text,
            'row_count': row['row_count'],
            'sample_rin': row['sample_rin'],
            'editions': row['editions'],
            'instances': instances,
            'whole_rows': rows,
        })

json.dump(results, open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_scan2_full.json','w'), indent=1)
print("texts with >=1 genuine lost-range instance:", len(results))
total_instances = sum(len(r['instances']) for r in results)
print("total lost-range instances:", total_instances)
print("total rows (text-level):", sum(r['row_count'] for r in results))
