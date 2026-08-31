import json
results = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_scan_full.json'))

plain_lost = []
for r in results:
    for inst in r['instances']:
        if not inst['end_present_in_output'] and not inst['appendix_context'] and not inst['end_pin'] and not inst['start_pin'] and not inst['in_comma_list_context']:
            plain_lost.append((r, inst))

print("plain lost count:", len(plain_lost))
for r, inst in plain_lost[:30]:
    print(r['authority_text'], '| rows=', r['row_count'], '| match=', inst['match_text'], '| start=', inst['start'], 'end=', inst['end'])
    print('    whole_rows:', [(w['usc_section'], w['usc_section_end'], w['usc_appendix'], w['parse_status']) for w in r['whole_rows']])
