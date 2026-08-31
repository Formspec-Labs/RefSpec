import json
report = {r['authority_text']: r for r in json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_report.json'))}
seed20 = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_seed20.json'))['seed20']

for t in seed20:
    r = report[t]
    print(f"TEXT: {t}  (rows={r['row_count']}, rin={r['sample_rin']}, editions={r['editions']})")
    print(f"  WHOLE-STRING grammar output: {[(w['authority_type'], w.get('usc_section')) for w in r['whole_grammar_out']]}")
    for pi in r['piece_infos']:
        if pi is None: continue
        print(f"    piece {pi['piece']!r}: recognized_type={pi['recognized_type']} stated_act={pi['stated_act_value']} stated_section={pi['stated_section_value']}")
    print()
