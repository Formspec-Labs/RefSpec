import glob, re, json

EDIR = 'output/registry-real-data-sources/unified-agenda-editions'
paths = sorted(glob.glob(f'{EDIR}/REGINFO_RIN_DATA_*.xml'))

def stem_of(p):
    return p.split('REGINFO_RIN_DATA_')[1].split('.xml')[0]

RIN_INFO_RE = re.compile(r'<RIN_INFO>.*?</RIN_INFO>', re.S)
RIN_RE = re.compile(r'<RIN>([^<]*)</RIN>')
ABSTRACT_CDATA_RE = re.compile(r'<ABSTRACT><!\[CDATA\[(.*?)\]\]></ABSTRACT>', re.S)
ABSTRACT_PLAIN_RE = re.compile(r'<ABSTRACT>(.*?)</ABSTRACT>', re.S)

per_edition = {}
html_records = []
total_abstracts = 0
plain_abstracts_without_cdata = 0

for p in paths:
    stem = stem_of(p)
    text = open(p, 'rb').read().decode('utf-8')
    ed_total = 0
    ed_doctype = 0
    ed_p_or_html = 0
    for rm in RIN_INFO_RE.finditer(text):
        record = rm.group(0)
        m = ABSTRACT_CDATA_RE.search(record)
        used_cdata = True
        if m is None:
            m = ABSTRACT_PLAIN_RE.search(record)
            used_cdata = False
        if m is None:
            continue
        content = m.group(1)
        ed_total += 1
        total_abstracts += 1
        if not used_cdata:
            plain_abstracts_without_cdata += 1
        has_doctype = content.lstrip().startswith('<!DOCTYPE html>') or content.lstrip().upper().startswith('<!DOCTYPE HTML')
        has_p = bool(re.search(r'<p[\s/>]', content, re.IGNORECASE)) or bool(re.search(r'<p>', content, re.IGNORECASE))
        has_html = bool(re.search(r'<html[\s/>]', content, re.IGNORECASE))
        if has_doctype:
            ed_doctype += 1
        if has_doctype or has_p or has_html:
            ed_p_or_html += 1
            mrin = RIN_RE.search(record)
            html_records.append({
                'edition': stem,
                'rin': mrin.group(1) if mrin else None,
                'has_doctype': has_doctype,
                'has_p': has_p,
                'has_html': has_html,
                'first_200': content[:200],
            })
    per_edition[stem] = {'total_abstracts': ed_total, 'doctype_count': ed_doctype, 'html_or_p_count': ed_p_or_html}

with open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/b_html_abstracts.json','w') as f:
    json.dump({'per_edition': per_edition, 'records': html_records, 'total_abstracts_all': total_abstracts, 'plain_without_cdata': plain_abstracts_without_cdata}, f, indent=2, ensure_ascii=False)

print('total abstract elements across corpus:', total_abstracts)
print('plain (non-CDATA) abstracts:', plain_abstracts_without_cdata)
print('total HTML-marked abstracts:', len(html_records))
first_edition = None
for stem in per_edition:
    pass
for p in paths:
    stem = stem_of(p)
    c = per_edition[stem]['html_or_p_count']
    if c:
        print(stem, per_edition[stem])
