import json, re

# ---------- CLASS 1 ----------
report = {r['authority_text']: r for r in json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_report.json'))}
buckets_summary = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_buckets_summary.json'))

strict = {
    "33 USC 1321/Clean Water Act","33 USC 2601/Shore Protection Act of 1988",
    "42 USC 11013/Pollution Prevention Act of 1990",
    "42 USC 4111/Clean Air Act Amendments of 1990, section 110(n)(3)",
    "42 USC 4111/Clean Air Act Amendments of 1990, section 129",
    "42 USC 7414, 7601, 7671 / Clean Air Act section 612",
    "42 USC 7671g/Clean Air Act section 608",
    "PL 101-549 /Clean Air Act sections 112 and 183",
}
trap = {t for t,_ in buckets_summary['trap_not_separator']}
already = {t for t,_ in buckets_summary['already_captured_not_dropped']}
compact = {t for t,_ in buckets_summary['compact_act_abbrev_drop']} | {t for t,_ in buckets_summary['ambiguous_other']}
amb_bare = {t for t,_ in buckets_summary['ambiguous_bare_number']}
amb_garbled = {t for t,_ in buckets_summary['ambiguous_garbled']}

raw_all = {r['authority_text']: r for r in json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_slash_texts_raw.json'))}

def rows_for(texts):
    return [{'authority_text': t, 'row_count': raw_all[t]['row_count'], 'sample_rin': raw_all[t]['sample_rin'], 'editions': raw_all[t]['editions']} for t in sorted(texts)]

out1 = {
    'population_total_slash_texts': 276,
    'excluded_date_only': rows_for(set(json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_full_analysis.json'))['excluded_date_only'])),
    'trap_not_separator': rows_for(trap),
    'strict_spelled_out_drop': rows_for(strict),
    'already_captured_not_actually_dropped': rows_for(already),
    'compact_act_abbrev_drop': rows_for(compact),
    'ambiguous_bare_trailing_number': rows_for(amb_bare),
    'ambiguous_garbled_double_slash': rows_for(amb_garbled),
}
json.dump(out1, open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/CLASS1_dropped_rows.json','w'), indent=1)
print("CLASS1 written. sizes:", {k: len(v) if isinstance(v,list) else v for k,v in out1.items()})

# ---------- CLASS 2 ----------
results2 = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class2_scan3_full.json'))
def bucket_key(inst):
    if inst['appendix_context']: return 'appendix_excl_owned_by_60'
    if inst['prose_between_full_citations']: return 'trap_prose_to_between_citations'
    if inst['end_pin'] or inst['start_pin']: return 'endpoint_has_subsection'
    if inst['in_comma_list_context']: return 'range_in_comma_list'
    if inst['compound_endpoint']: return 'endpoint_is_compound_hyphenated_name'
    start_num_m = re.match(r'\d+', inst['start']); end_num_m = re.match(r'\d+', inst['end'])
    if start_num_m and end_num_m:
        sn, en = int(start_num_m.group(0)), int(end_num_m.group(0))
        if en < sn and len(inst['end']) <= 3:
            return 'shorthand_endpoint_never_expanded'
    return 'unclear_likely_source_typo'

out2 = {}
for r in results2:
    for inst in r['instances']:
        k = bucket_key(inst)
        out2.setdefault(k, []).append({
            'authority_text': r['authority_text'], 'row_count': r['row_count'],
            'sample_rin': r['sample_rin'], 'editions': r['editions'],
            'match': inst['match_text'], 'start': inst['start'], 'end': inst['end'],
        })

for k in out2:
    out2[k].sort(key=lambda x: x['authority_text'])

json.dump(out2, open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/CLASS2_dropped_rows.json','w'), indent=1)
print("CLASS2 written. instance counts:", {k: len(v) for k,v in out2.items()})
print("CLASS2 distinct texts:", {k: len({x['authority_text'] for x in v}) for k,v in out2.items()})
print("CLASS2 rows (sum over distinct texts):", {k: sum(dict((x['authority_text'],x['row_count']) for x in v).values()) for k,v in out2.items()})
