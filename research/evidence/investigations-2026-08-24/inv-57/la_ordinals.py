import glob, re, json

EDIR = 'output/registry-real-data-sources/unified-agenda-editions'

occ = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/a_occurrences.json'))
la_occ = [o for o in occ if o['element'] == 'LEGAL_AUTHORITY']

by_edition = {}
for o in la_occ:
    by_edition.setdefault(o['edition'], []).append(o)

RIN_INFO_RE = re.compile(r'<RIN_INFO>.*?</RIN_INFO>', re.S)
RIN_RE = re.compile(r'<RIN>([^<]*)</RIN>')
PUB_RE = re.compile(r'<PUBLICATION_ID>([^<]*)</PUBLICATION_ID>')
LA_LIST_RE = re.compile(r'<LEGAL_AUTHORITY_LIST>(.*?)</LEGAL_AUTHORITY_LIST>', re.S)
LA_BOX_RE = re.compile(r'<LEGAL_AUTHORITY>(.*?)</LEGAL_AUTHORITY>', re.S)

results = []
for stem, occs in by_edition.items():
    path = f'{EDIR}/REGINFO_RIN_DATA_{stem}.xml'
    text = open(path, 'rb').read().decode('utf-8')
    for o in occs:
        pos = o['byte_pos']
        rin_start = text.rfind('<RIN_INFO', 0, pos)
        rin_end = text.find('</RIN_INFO>', pos) + len('</RIN_INFO>')
        record = text[rin_start:rin_end]
        mrin = RIN_RE.search(record)
        mpub = PUB_RE.search(record)
        mlist = LA_LIST_RE.search(record)
        ordinal = None
        box_text = None
        box_count = None
        if mlist:
            list_text = mlist.group(1)
            list_start_abs = rin_start + mlist.start(1)
            boxes = list(LA_BOX_RE.finditer(list_text))
            box_count = len(boxes)
            for idx, b in enumerate(boxes):
                b_start_abs = list_start_abs + b.start()
                b_end_abs = list_start_abs + b.end()
                if b_start_abs <= pos < b_end_abs:
                    ordinal = idx
                    box_text = b.group(1)
                    break
        results.append({
            'edition': stem,
            'rin': mrin.group(1) if mrin else None,
            'publication_id': mpub.group(1) if mpub else None,
            'ordinal': ordinal,
            'box_count': box_count,
            'box_text_raw': box_text,
            'codepoint': o['codepoint'],
            'byte_pos': pos,
        })

with open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/la_with_ordinals.json', 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print('total', len(results))
missing = [r for r in results if r['ordinal'] is None]
print('missing ordinal:', len(missing))
for m in missing[:5]:
    print(m)
