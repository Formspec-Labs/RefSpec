import glob, re, json

EDIR = 'output/registry-real-data-sources/unified-agenda-editions'
paths = sorted(glob.glob(f'{EDIR}/REGINFO_RIN_DATA_*.xml'))

CTRL_RE = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x80-\x9f]')
CDATA_RE = re.compile(r'<!\[CDATA\[.*?\]\]>', re.S)
TAG_RE = re.compile(r'<(/?)([A-Za-z_][A-Za-z0-9_]*)([^>]*?)(/?)>')

def stem_of(p):
    return p.split('REGINFO_RIN_DATA_')[1].split('.xml')[0]

per_edition = {}
occurrences = []

for p in paths:
    stem = stem_of(p)
    raw = open(p, 'rb').read()
    text = raw.decode('utf-8')

    # mark CDATA spans (start,end) over full text -- content inside is NOT tag-parsed
    cdata_spans = [(m.start(), m.end(), m.start()+len('<![CDATA[')) for m in CDATA_RE.finditer(text)]

    # collect tag events NOT inside a CDATA span, plus record which CDATA span (if any) a position falls in
    events = []  # (pos, kind, name)  kind: 'open','close','selfclose'
    for m in TAG_RE.finditer(text):
        pos = m.start()
        inside_cdata = False
        for (cs, ce, _cc) in cdata_spans:
            if cs <= pos < ce:
                inside_cdata = True
                break
        if inside_cdata:
            continue
        closing = m.group(1) == '/'
        name = m.group(2)
        selfclose = m.group(4) == '/'
        if selfclose:
            events.append((pos, 'selfclose', name))
        elif closing:
            events.append((pos, 'close', name))
        else:
            events.append((pos, 'open', name))
    events.sort(key=lambda e: e[0])

    ctrl_positions = [(m.start(), ord(m.group(0))) for m in CTRL_RE.finditer(text)]

    # merge: walk events and ctrl positions together maintaining a stack
    stack = []
    ei = 0
    ed = {'file': stem, 'total_occurrences': 0, 'by_codepoint': {}, 'by_element': {}}
    for pos, cp in ctrl_positions:
        while ei < len(events) and events[ei][0] <= pos:
            _, kind, name = events[ei]
            if kind == 'open':
                stack.append(name)
            elif kind == 'close':
                # pop matching name if present at top; else pop till match or ignore
                if stack and stack[-1] == name:
                    stack.pop()
                elif name in stack:
                    # pop until removed (shouldn't normally happen with well-formed input)
                    while stack and stack[-1] != name:
                        stack.pop()
                    if stack:
                        stack.pop()
            # selfclose: no net stack change
            ei += 1
        elem = stack[-1] if stack else 'ROOT'
        key = f'U+{cp:04X}'
        ed['total_occurrences'] += 1
        ed['by_codepoint'][key] = ed['by_codepoint'].get(key, 0) + 1
        bucket = elem if elem in ('LEGAL_AUTHORITY', 'ABSTRACT', 'CFR') else ('other:' + elem)
        ed['by_element'][bucket] = ed['by_element'].get(bucket, 0) + 1

        rin = pub = None
        if elem != 'ROOT':
            rin_start = text.rfind('<RIN_INFO', 0, pos)
            rin_end = text.find('</RIN_INFO>', pos)
            if rin_start != -1 and rin_end != -1:
                record = text[rin_start:rin_end+len('</RIN_INFO>')]
                mrin = re.search(r'<RIN>([^<]*)</RIN>', record)
                mpub = re.search(r'<PUBLICATION_ID>([^<]*)</PUBLICATION_ID>', record)
                rin = mrin.group(1) if mrin else None
                pub = mpub.group(1) if mpub else None

        occurrences.append({
            'edition': stem,
            'byte_pos': pos,
            'codepoint': key,
            'element': elem,
            'rin': rin,
            'publication_id_record': pub,
            'context': text[max(0,pos-50):pos] + ('<U+%04X>' % cp) + text[pos+1:pos+50],
        })
    per_edition[stem] = ed

with open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/a_per_edition.json', 'w') as f:
    json.dump(per_edition, f, indent=2)
with open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/a_occurrences.json', 'w') as f:
    json.dump(occurrences, f, indent=2)

total = sum(r['total_occurrences'] for r in per_edition.values())
print('TOTAL occurrences across 60 editions:', total)
print('editions with any occurrence:', sum(1 for r in per_edition.values() if r['total_occurrences']>0))
for stem, r in per_edition.items():
    if r['total_occurrences']:
        print(stem, r['total_occurrences'], r['by_codepoint'], r['by_element'])
