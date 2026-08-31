import glob, re, json, sys
from xml.etree import ElementTree as ET

EDIR = 'output/registry-real-data-sources/unified-agenda-editions'
paths = sorted(glob.glob(f'{EDIR}/REGINFO_RIN_DATA_*.xml'))

CTRL_RE = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x80-\x9f]')

TAG_RE = re.compile(r'<([A-Za-z_][A-Za-z0-9_]*)[ >]')

def publication_id_from_filename(p):
    stem = p.split('REGINFO_RIN_DATA_')[1].split('.xml')[0]
    return stem

results = {}
all_occurrences = []

for p in paths:
    stem = publication_id_from_filename(p)
    raw = open(p, 'rb').read()
    text = raw.decode('utf-8')
    per_edition = {'file': stem, 'total_occurrences': 0, 'by_codepoint': {}, 'by_element': {}}
    for m in CTRL_RE.finditer(text):
        cp = ord(m.group(0))
        pos = m.start()
        per_edition['total_occurrences'] += 1
        key = f'U+{cp:04X}'
        per_edition['by_codepoint'][key] = per_edition['by_codepoint'].get(key, 0) + 1

        # find enclosing element: scan backward for nearest '<TAG>' opening tag
        # find nearest preceding '<' that starts an opening tag (not closing, not comment)
        window_start = max(0, pos - 400)
        before = text[window_start:pos]
        # find all tag opens/closes in before, take the last one
        tag_iter = list(re.finditer(r'<(/?)([A-Za-z_][A-Za-z0-9_]*)([ >/])', before))
        elem = 'UNKNOWN'
        if tag_iter:
            last = tag_iter[-1]
            closing = last.group(1) == '/'
            name = last.group(2)
            elem = ('/' if closing else '') + name

        # find enclosing RIN_INFO record: search backward for last <RIN_INFO and check we're before </RIN_INFO>
        rin_start = text.rfind('<RIN_INFO', 0, pos)
        rin_end = text.find('</RIN_INFO>', pos)
        rin = None
        pub = None
        record_snippet = None
        if rin_start != -1 and rin_end != -1:
            record = text[rin_start:rin_end+len('</RIN_INFO>')]
            mrin = re.search(r'<RIN>([^<]*)</RIN>', record)
            mpub = re.search(r'<PUBLICATION_ID>([^<]*)</PUBLICATION_ID>', record)
            rin = mrin.group(1) if mrin else None
            pub = mpub.group(1) if mpub else None

        elem_bucket = elem if elem in ('LEGAL_AUTHORITY','ABSTRACT','CFR','ADDITIONAL_INFO') else ('other:' + elem)
        per_edition['by_element'][elem_bucket] = per_edition['by_element'].get(elem_bucket, 0) + 1

        occ = {
            'edition': stem,
            'byte_pos': pos,
            'codepoint': key,
            'element': elem,
            'rin': rin,
            'publication_id_record': pub,
            'context': text[max(0,pos-40):pos] + '<U+%04X>' % cp + text[pos+1:pos+40],
        }
        all_occurrences.append(occ)
    results[stem] = per_edition

with open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/a_per_edition.json', 'w') as f:
    json.dump(results, f, indent=2)
with open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/a_occurrences.json', 'w') as f:
    json.dump(all_occurrences, f, indent=2)

total = sum(r['total_occurrences'] for r in results.values())
print('TOTAL occurrences across 60 editions:', total)
print('editions with any occurrence:', sum(1 for r in results.values() if r['total_occurrences']>0))
for stem, r in results.items():
    if r['total_occurrences']:
        print(stem, r['total_occurrences'], r['by_codepoint'], r['by_element'])
