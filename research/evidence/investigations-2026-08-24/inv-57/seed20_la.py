import json, random

r = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/la_with_ordinals.json'))
# sort by (rin, publication_id, ordinal, byte_pos) for a stable population before seeding, per repo convention
pop = sorted(r, key=lambda x: (x['rin'], x['publication_id'], x['ordinal'], x['byte_pos']))
random.seed(20260823)
sample = random.sample(pop, 20)
sample.sort(key=lambda x: (x['rin'], x['publication_id'], x['ordinal']))

def with_marker(text, cp):
    idx = text.find(chr(int(cp[2:], 16)))
    return text[:idx] + f'<{cp}>' + text[idx+1:]

out = []
for s in sample:
    verbatim = with_marker(s['box_text_raw'], s['codepoint'])
    out.append({
        'rin': s['rin'], 'publication_id': s['publication_id'], 'ordinal': s['ordinal'],
        'box_count': s['box_count'], 'codepoint': s['codepoint'], 'verbatim': verbatim,
    })
    print(f"{s['rin']} {s['publication_id']} ordinal={s['ordinal']}/{s['box_count']} {s['codepoint']}: {verbatim}")

with open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/a_seeded20_legal_authority.json', 'w') as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
