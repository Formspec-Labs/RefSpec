import duckdb, json, random, re

con = duckdb.connect(':memory:')
path = 'output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet'

q = f"""
WITH box_counts AS (
  SELECT rin, publication_id, count(DISTINCT ordinal) AS box_count, max(ordinal) AS max_ordinal
  FROM read_parquet('{path}')
  WHERE authority_source = 'box'
  GROUP BY rin, publication_id
),
ellipsis AS (
  SELECT rin, publication_id, ordinal AS e_ordinal
  FROM read_parquet('{path}')
  WHERE unstated_kind = 'more-citations-follow'
)
SELECT e.rin, e.publication_id, e.e_ordinal, bc.box_count
FROM ellipsis e
JOIN box_counts bc USING (rin, publication_id)
WHERE e.e_ordinal <> bc.max_ordinal
ORDER BY e.rin, e.publication_id
"""
rows = con.execute(q).fetchall()
print('mid-list rows (58 expected):', len(rows))

random.seed(20260823)
sample = random.sample(rows, 10)
sample.sort(key=lambda r: (r[0], r[1]))

EDIR = 'output/registry-real-data-sources/unified-agenda-editions'
LA_LIST_RE = re.compile(r'<LEGAL_AUTHORITY_LIST>(.*?)</LEGAL_AUTHORITY_LIST>', re.S)
LA_BOX_RE = re.compile(r'<LEGAL_AUTHORITY>(.*?)</LEGAL_AUTHORITY>', re.S)
RIN_INFO_RE = re.compile(r'<RIN_INFO>.*?</RIN_INFO>', re.S)
RIN_RE = re.compile(r'<RIN>([^<]*)</RIN>')

specimens = []
for rin, pub, e_ordinal, box_count in sample:
    path_xml = f'{EDIR}/REGINFO_RIN_DATA_{pub}.xml'
    text = open(path_xml, 'rb').read().decode('utf-8')
    found_boxes = None
    for rm in RIN_INFO_RE.finditer(text):
        record = rm.group(0)
        mrin = RIN_RE.search(record)
        if mrin and mrin.group(1) == rin:
            mlist = LA_LIST_RE.search(record)
            if mlist:
                found_boxes = [b.group(1) for b in LA_BOX_RE.finditer(mlist.group(1))]
            break
    specimens.append({
        'rin': rin, 'publication_id': pub, 'ellipsis_ordinal': e_ordinal, 'box_count': box_count,
        'boxes': found_boxes,
    })

with open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/c_midlist_specimens.json', 'w') as f:
    json.dump(specimens, f, indent=2, ensure_ascii=False)

for s in specimens:
    print('===', s['rin'], s['publication_id'], 'ellipsis@', s['ellipsis_ordinal'], 'of', s['box_count'], 'boxes')
    for i, b in enumerate(s['boxes']):
        marker = ' <-- ELLIPSIS' if i == s['ellipsis_ordinal'] else ''
        print(f'  [{i}] {b}{marker}')
