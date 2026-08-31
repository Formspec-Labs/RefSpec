import glob, re, json, bisect, time

EDIR = 'output/registry-real-data-sources/unified-agenda-editions'
paths = sorted(glob.glob(f'{EDIR}/REGINFO_RIN_DATA_*.xml'))

CTRL_RE = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x80-\x9f]')
CDATA_RE = re.compile(r'<!\[CDATA\[.*?\]\]>', re.S)
TAG_RE = re.compile(r'<(/?)([A-Za-z_][A-Za-z0-9_]*)([^>]*?)(/?)>')
RIN_INFO_OPEN = re.compile(r'<RIN_INFO>')
RIN_TAG = re.compile(r'<RIN>([^<]*)</RIN>')
PUB_TAG = re.compile(r'<PUBLICATION_ID>([^<]*)</PUBLICATION_ID>')

def stem_of(p):
    return p.split('REGINFO_RIN_DATA_')[1].split('.xml')[0]

per_edition = {}
occurrences = []

for p in paths:
    t0 = time.time()
    stem = stem_of(p)
    raw = open(p, 'rb').read()
    text = raw.decode('utf-8')

    cdata_starts = []
    cdata_ends = []
    for m in CDATA_RE.finditer(text):
        cdata_starts.append(m.start())
        cdata_ends.append(m.end())

    def in_cdata(pos):
        i = bisect.bisect_right(cdata_starts, pos) - 1
        if i >= 0 and pos < cdata_ends[i]:
            return True
        return False

    events = []
    for m in TAG_RE.finditer(text):
        pos = m.start()
        if in_cdata(pos):
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
    event_positions = [e[0] for e in events]

    # RIN_INFO record boundaries, precomputed once
    rin_info_starts = [m.start() for m in RIN_INFO_OPEN.finditer(text)]
    # for each record start, find its RIN and PUBLICATION_ID once, and end position
    record_index = []  # (start, end, rin, pub)
    for i, s in enumerate(rin_info_starts):
        e = text.find('</RIN_INFO>', s)
        e = e + len('</RIN_INFO>') if e != -1 else len(text)
        chunk = text[s:min(e, s+2000)]  # RIN/PUB are near the top of the record
        mrin = RIN_TAG.search(chunk)
        mpub = PUB_TAG.search(chunk)
        record_index.append((s, e, mrin.group(1) if mrin else None, mpub.group(1) if mpub else None))
    record_starts = [r[0] for r in record_index]

    def record_for(pos):
        i = bisect.bisect_right(record_starts, pos) - 1
        if i >= 0 and pos < record_index[i][1]:
            return record_index[i]
        return (None, None, None, None)

    ctrl_positions = [(m.start(), ord(m.group(0))) for m in CTRL_RE.finditer(text)]

    stack = []
    ei = 0
    ed = {'file': stem, 'total_occurrences': 0, 'by_codepoint': {}, 'by_element': {}}
    for pos, cp in ctrl_positions:
        # advance events up to pos using bisect for the starting index then a simple while loop
        while ei < len(events) and events[ei][0] <= pos:
            _, kind, name = events[ei]
            if kind == 'open':
                stack.append(name)
            elif kind == 'close':
                if stack and stack[-1] == name:
                    stack.pop()
                elif name in stack:
                    while stack and stack[-1] != name:
                        stack.pop()
                    if stack:
                        stack.pop()
            ei += 1
        elem = stack[-1] if stack else 'ROOT'
        key = f'U+{cp:04X}'
        ed['total_occurrences'] += 1
        ed['by_codepoint'][key] = ed['by_codepoint'].get(key, 0) + 1
        bucket = elem if elem in ('LEGAL_AUTHORITY', 'ABSTRACT', 'CFR') else ('other:' + elem)
        ed['by_element'][bucket] = ed['by_element'].get(bucket, 0) + 1

        rs, re_, rin, pub = record_for(pos) if elem != 'ROOT' else (None, None, None, None)

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
    print(stem, 'occ=', ed['total_occurrences'], 'time=%.1fs' % (time.time()-t0), flush=True)

with open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/a_per_edition.json', 'w') as f:
    json.dump(per_edition, f, indent=2)
with open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/a_occurrences.json', 'w') as f:
    json.dump(occurrences, f, indent=2)

total = sum(r['total_occurrences'] for r in per_edition.values())
print('TOTAL occurrences across 60 editions:', total)
