import json
import duckdb

r = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/la_with_ordinals.json'))
# distinct boxes
boxes = {}
for x in r:
    key = (x['rin'], x['publication_id'], x['ordinal'])
    boxes.setdefault(key, {'edition': x['edition'], 'box_text_raw': x['box_text_raw'], 'codepoints': set()})
    boxes[key]['codepoints'].add(x['codepoint'])

print('distinct boxes:', len(boxes))

con = duckdb.connect(':memory:')
path = 'output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet'

keys = list(boxes.keys())
# batch query using a VALUES list
values_sql = ",".join(f"('{r_}','{p_}',{o_})" for (r_,p_,o_) in keys)
q = f'''
SELECT rin, publication_id, ordinal, citation_ordinal, authority_text, authority_type, parse_status,
       usc_title, usc_section, usc_section_end, public_law, unstated_kind, act_key, act_section,
       admin_order_kind, admin_order_number, statute_volume, statute_page, cfr_title, cfr_part, cfr_section
FROM read_parquet('{path}')
WHERE (rin, publication_id, ordinal) IN ({values_sql})
'''
rows = con.execute(q).fetchall()
cols = [d[0] for d in con.description]
by_key = {}
for row in rows:
    d = dict(zip(cols, row))
    key = (d['rin'], d['publication_id'], d['ordinal'])
    by_key.setdefault(key, []).append(d)

missing = [k for k in keys if k not in by_key]
print('boxes with NO artifact row at all:', len(missing))
for m in missing[:20]:
    print(' MISSING', m, boxes[m]['box_text_raw'])

# classify parse_status per box (any row failed?)
status_summary = {}
failed_boxes = []
for key, info in boxes.items():
    arows = by_key.get(key, [])
    statuses = set(a['parse_status'] for a in arows)
    status_summary[key] = statuses
    if not arows or statuses == {'failed'} or (arows and all(s in (None,'failed') for s in statuses)):
        failed_boxes.append((key, info['box_text_raw'], statuses))

print()
print('boxes where ALL rows are failed/none (candidate identity-loss cases):', len(failed_boxes))
for f in failed_boxes:
    print(' FAILED-ALL', f)

with open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/la_boxes_with_artifact.json','w') as fh:
    json.dump({
        'boxes': {f'{k[0]}|{k[1]}|{k[2]}': {'box_text_raw': v['box_text_raw'], 'edition': v['edition'], 'codepoints': sorted(v['codepoints'])} for k,v in boxes.items()},
        'artifact_rows': {f'{k[0]}|{k[1]}|{k[2]}': by_key.get(k, []) for k in keys},
    }, fh, indent=2, ensure_ascii=False)
