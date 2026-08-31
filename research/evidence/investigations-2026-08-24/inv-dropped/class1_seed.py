import json, random

report = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_report.json'))
by_text = {r['authority_text']: r for r in report}

strict = {
    "33 USC 1321/Clean Water Act",
    "33 USC 2601/Shore Protection Act of 1988",
    "42 USC 11013/Pollution Prevention Act of 1990",
    "42 USC 4111/Clean Air Act Amendments of 1990, section 110(n)(3)",
    "42 USC 4111/Clean Air Act Amendments of 1990, section 129",
    "42 USC 7414, 7601, 7671 / Clean Air Act section 612",
    "42 USC 7671g/Clean Air Act section 608",
    "PL 101-549 /Clean Air Act sections 112 and 183",
}

buckets_summary = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_buckets_summary.json'))
compact = {t for t,_ in buckets_summary['compact_act_abbrev_drop']}
ambiguous_bare = {t for t,_ in buckets_summary['ambiguous_bare_number']}
ambiguous_other = {t for t,_ in buckets_summary['ambiguous_other']}
compact |= ambiguous_other  # SARA texts folded in

dropped_population = strict | compact | ambiguous_bare
print("dropped_population size:", len(dropped_population))

sorted_keys = sorted(dropped_population)
rng = random.Random(20260823)
seed20 = rng.sample(sorted_keys, 20)
seed20_sorted = sorted(seed20)
print("=== seeded 20 ===")
for t in seed20_sorted:
    r = by_text[t]
    print(t, '| rows=', r['row_count'], '| sample_rin=', r['sample_rin'], '| editions=', r['editions'])

json.dump({'population_size': len(dropped_population), 'sorted_keys': sorted_keys, 'seed20': seed20_sorted},
          open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_seed20.json','w'), indent=1)
