import json, re
results = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_scan2_full.json'))

plain = []
for r in results:
    for inst in r['instances']:
        if not inst['appendix_context'] and not inst['end_pin'] and not inst['start_pin'] and not inst['in_comma_list_context']:
            plain.append((r, inst))

print("plain_bare_to_bare count:", len(plain))

# sub-classify: is 'end' itself immediately followed by another full USC/CFR/PL/EO citation marker (prose 'to')?
prose_between_citations = []
abbrev_asymmetry = []
other_plain = []
for r, inst in plain:
    text = r['authority_text']
    end = inst['end']
    match_text = inst['match_text']
    # heuristic: does the ORIGINAL text contain "U.S.C." or "USC" or "CFR" shortly after the matched end token?
    idx = text.find(match_text[-len(end):]) if match_text else -1
    tail = text[idx+len(end):idx+len(end)+15] if idx>=0 else ''
    if re.search(r'\s*(U\.?S\.?C|C\.?F\.?R)', tail, re.IGNORECASE):
        prose_between_citations.append((r, inst, tail))
    elif len(end) <= 2 and len(inst['start']) >= 3 and int(re.sub(r'\D','',end) or 0) < int(re.sub(r'\D','',inst['start']) or 0):
        abbrev_asymmetry.append((r, inst))
    else:
        other_plain.append((r, inst))

print("prose_between_citations:", len(prose_between_citations), "texts:", len({r['authority_text'] for r,i,t in prose_between_citations}))
print("abbrev_asymmetry (end is short/smaller than start, abbreviation-shaped):", len(abbrev_asymmetry), "texts:", len({r['authority_text'] for r,i in abbrev_asymmetry}))
print("other_plain:", len(other_plain), "texts:", len({r['authority_text'] for r,i in other_plain}))

print()
print("=== prose_between_citations sample ===")
for r, inst, tail in prose_between_citations[:15]:
    print(' ', r['authority_text'], '| rows=', r['row_count'], '| match=', inst['match_text'], '| tail=', repr(tail))

print()
print("=== abbrev_asymmetry sample ===")
for r, inst in abbrev_asymmetry[:20]:
    print(' ', r['authority_text'], '| rows=', r['row_count'], '| start=', inst['start'], 'end=', inst['end'])

print()
print("=== other_plain sample (first 30) ===")
for r, inst in other_plain[:30]:
    print(' ', r['authority_text'], '| rows=', r['row_count'], '| start=', inst['start'], 'end=', inst['end'])
