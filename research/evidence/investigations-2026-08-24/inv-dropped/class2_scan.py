import json, re, sys
sys.path.insert(0, '/Users/mikewolfd/Work/RefSpec/src')
from refspec.registry import citation_grammar as g

USC_SECTION_TOKEN = g._USC_SECTION_TOKEN
RANGE_SEPARATOR = g._RANGE_SEPARATOR
SPACED_DASH = g._SPACED_DASH
PINPOINT = g._USC_PINPOINT.pattern
APPENDIX_MARKER = g._APPENDIX_MARKER

# scan for START <rangesep> END(pinpoint)? in the DASH-NORMALIZED text (mirrors
# what the grammar itself operates on -- _normalize_dashes runs before every read)
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
    end_values = {r['usc_section_end'] for r in rows if r['usc_section_end']}
    start_values_with_end = {r['usc_section'] for r in rows if r['usc_section_end']}

    instances = []
    for m in RANGE_SCAN.finditer(normalized):
        sep = m.group('sep')
        if sep == '-':
            # only a SPACED dash counts as a range separator (mirrors _SPACED_DASH);
            # a bare hyphen inside e.g. "1395w-4" is a section NAME, not a range.
            span_text = normalized[m.start('start'):m.end('end')]
            # check original spacing around the hyphen actually present in the match
            sep_span = normalized[m.end('start') + len(m.group('start_pin')):m.start('end')]
            if not re.fullmatch(r'\s+-\s+', sep_span):
                continue
        start_tok = g._usc_section(m.group('start'))
        end_tok = g._usc_section(m.group('end'))
        end_pin = m.group('end_pin')
        start_pin = m.group('start_pin')
        # is the endpoint's numeric value captured anywhere for this text?
        end_present = end_tok in end_values
        # context: is this range inside a longer comma list? look at 60 chars before start
        before = normalized[max(0, m.start()-60):m.start()]
        after = normalized[m.end():m.end()+30]
        in_comma_list = bool(re.search(r',\s*$', before)) or bool(re.search(r'^\s*,', after))
        # appendix context: does an appendix marker appear anywhere before this range
        # within the same citation (heuristic: within 40 chars before start, on the
        # same title/USC clause)
        appendix_context = bool(re.search(APPENDIX_MARKER, normalized[max(0,m.start()-40):m.start()], re.IGNORECASE))
        instances.append({
            'match_text': normalized[m.start():m.end()],
            'start': start_tok, 'end': end_tok, 'sep': sep,
            'start_pin': start_pin, 'end_pin': end_pin,
            'end_present_in_output': end_present,
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

json.dump(results, open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_scan_full.json','w'), indent=1)
print("texts with >=1 range instance detected:", len(results))
total_instances = sum(len(r['instances']) for r in results)
print("total range instances detected:", total_instances)
lost = [(r, inst) for r in results for inst in r['instances'] if not inst['end_present_in_output']]
print("lost-endpoint instances (end token not present anywhere in output):", len(lost))
print("distinct texts with >=1 lost instance:", len({r['authority_text'] for r,inst in lost}))
