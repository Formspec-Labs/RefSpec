import json, re, sys
sys.path.insert(0, '/Users/mikewolfd/Work/RefSpec/src')
from refspec.registry.citation_grammar import parse_authority_citation

d = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_full_analysis.json'))
results = d['results']

KEY_FIELDS = ['authority_type','usc_title','usc_section','usc_section_end','act_key','act_section',
              'public_law','cfr_title','cfr_part','executive_order']

def citation_key(c):
    return tuple(c.get(k) for k in KEY_FIELDS)

def full_citation_set(text):
    cits = parse_authority_citation(text)
    return set(citation_key({
        'authority_type': c.authority_type, 'usc_title': c.usc_title, 'usc_section': c.usc_section,
        'usc_section_end': c.usc_section_end, 'act_key': c.act_key, 'act_section': c.act_section,
        'public_law': c.public_law, 'cfr_title': c.cfr_title, 'cfr_part': c.cfr_part,
        'executive_order': c.executive_order,
    }) for c in cits)

report = []
for r in results:
    text = r['authority_text']
    whole_set = full_citation_set(text)
    pieces = r['pieces']
    piece_infos = []
    for pc in pieces:
        pc = pc.strip()
        if not pc:
            piece_infos.append(None)
            continue
        piece_cits = parse_authority_citation(pc)
        recognized = any(c.authority_type not in ('other','unstated') for c in piece_cits)
        stated = any(c.stated_act_name is not None for c in piece_cits)
        piece_set = full_citation_set(pc)
        # is any of this piece's recognized-type identity already present in whole?
        present_in_whole = bool(piece_set & whole_set) if recognized else None
        piece_infos.append({
            'piece': pc, 'recognized_type': recognized, 'stated_fallback': stated,
            'reads_as_authority': recognized or stated,
            'present_in_whole': present_in_whole,
            'has_specific_section': stated and any(c.stated_section for c in piece_cits),
            'stated_section_value': next((c.stated_section for c in piece_cits if c.stated_section), None),
            'stated_act_value': next((c.stated_act_name for c in piece_cits if c.stated_act_name), None),
        })
    r['piece_infos'] = piece_infos
    report.append(r)

json.dump(report, open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_report.json','w'), indent=1)

# Now bucket
GENUINE_DROP = []
for r in report:
    for pi in r['piece_infos'][1:] if len(r['piece_infos'])>1 else []:
        if pi is None:
            continue
        if pi['recognized_type'] and pi['present_in_whole'] is False:
            GENUINE_DROP.append((r, pi))
        elif pi['stated_fallback'] and not pi['recognized_type']:
            # stated fallback pieces are never "present_in_whole" since we don't track them in whole_set
            GENUINE_DROP.append((r, pi))

print("genuine-drop piece instances (pre-trap-filtering):", len(GENUINE_DROP))
seen_texts = set()
for r, pi in GENUINE_DROP:
    if r['authority_text'] in seen_texts:
        continue
    seen_texts.add(r['authority_text'])
    print(r['authority_text'], '| rows=', r['row_count'], '| dropped piece=', repr(pi['piece']), '| act=', pi['stated_act_value'], '| section=', pi['stated_section_value'], '| recognized_type=', pi['recognized_type'])
print("distinct texts:", len(seen_texts))
