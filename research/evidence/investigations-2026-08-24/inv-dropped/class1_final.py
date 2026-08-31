import json, re

report = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_report.json'))
d_raw = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_full_analysis.json'))

TRAP_TEXTS = {
    "PL 110-53, sec 1413, The Implementing Recommendations of the 9/11 Commission Act of 2007": "9/11 is part of the act's proper name, not a separator",
    "PL 110-53, sec 1521, The Implementing Recommendations of the 9/11 Commission Act of 2007": "9/11 is part of the act's proper name, not a separator",
    "PL 110-53, sec 1536, The Implementing Recommendations of the 9/11 Commission Act of 2007": "9/11 is part of the act's proper name, not a separator",
    "PL 110-53, sec 711, 9/11 Act": "9/11 is part of the act's proper name, not a separator",
    "Pub. L. 110-53, sec 1413, The Implementing Recommendations of the 9/11 Commission Act of 2007": "9/11 is part of the act's proper name, not a separator",
    "Pub. L. 110-53, sec 1521, The Implementing Recommendations of the 9/11 Commission Act of 2007": "9/11 is part of the act's proper name, not a separator",
    "Pub. L. 110-53, sec 1536, The Implementing Recommendations of the 9/11 Commission Act of 2007": "9/11 is part of the act's proper name, not a separator",
    "Pub. L. 110-53, sec 711, 9/11 Act": "9/11 is part of the act's proper name, not a separator",
    "Pub. L. 117-180, Division G – Hermit’s Peak/Calf Canyon Fire Assistance Act": "Hermit's Peak/Calf Canyon is one compound place name inside one act's title",
    "Pub. L. 117-180, Division G – Hermit’s Peak/Calf Canyon Fire Assistance Act (Act)": "Hermit's Peak/Calf Canyon is one compound place name inside one act's title",
    "PL 106-554, Treasury/General Government Appropriations Act of 2001": "Treasury/General Government Appropriations Act is one division's compound name (PL 106-554 App. D), '/' stands in for 'and'",
    "S/B Improving Head Start for School Readiness Act of 2007, PL 110-134": "'S/B' is a bill-type/docket prefix label, not two authorities",
    "PL 96-354; 5 USC 601. Docket 41683, EDR 468/PSDR-81.": "EDR 468/PSDR-81 are internal docket numbers, not legal authorities",
    "42 USC 7401/et seq": "'et seq' is a continuation marker mis-joined with '/' instead of a space, not a second authority",
}

STRICT_DROP_TEXTS = {
    "33 USC 1321/Clean Water Act",
    "33 USC 2601/Shore Protection Act of 1988",
    "42 USC 11013/Pollution Prevention Act of 1990",
    "42 USC 4111/Clean Air Act Amendments of 1990, section 110(n)(3)",
    "42 USC 4111/Clean Air Act Amendments of 1990, section 129",
    "42 USC 7414, 7601, 7671 / Clean Air Act section 612",
    "42 USC 7671g/Clean Air Act section 608",
    "PL 101-549 /Clean Air Act sections 112 and 183",
}

ALREADY_CAPTURED_TEXTS = {
    "33 USC 1251/33 USC 1345",
    "33 USC 1361(a)/76 Stat 816",
    "33 USC 1361(a)/76 Stat. 816",
    "33 USC 2601/Shore Protection Act of 1988 (PL 100-6-88),4103(b)",
    "42 USC 2021(h)/AEA 274(h)/Reorganization Plan No. 3 of 1970",
    "42 USC 2021(h)/AEA(h)/Reorganization Plan No. 3 of 1970",
}

ACT_ABBREV_TOKEN = re.compile(r'^[A-Za-z]{2,8}$')
KNOWN_ACT_ABBREVS = {"CAA","CAAA","CWA","TSCA","RCRA","RCA","FFDCA","CERCLA","SDWA","FIFRA",
                      "AEA","MPRSA","EPCRA","SARA","FWPCA","EPAAR"}

def classify_remaining(text, pieces):
    # pieces after first
    tail_pieces = [p.strip() for p in pieces[1:]]
    shapes = []
    for tp in tail_pieces:
        if not tp:
            shapes.append("empty")
            continue
        if re.search(r'/', tp):
            pass
        m = re.match(r'^([A-Za-z]{2,8})\.?\s*(\d[\w()\-,.& ]*)?$', tp)
        if m and (m.group(1).upper() in KNOWN_ACT_ABBREVS):
            shapes.append("act_abbrev_number" if m.group(2) else "act_abbrev_bare")
        elif re.match(r'^\d[\w()\-,.]*$', tp):
            shapes.append("bare_number_no_act_token")
        elif '//' in text:
            shapes.append("garbled_double_slash")
        else:
            shapes.append("other:" + tp[:40])
    return shapes

buckets = {
    "trap_not_separator": [],
    "strict_spelled_out_drop": [],
    "already_captured_not_dropped": [],
    "compact_act_abbrev_drop": [],
    "ambiguous_bare_number": [],
    "ambiguous_garbled": [],
    "ambiguous_other": [],
}

texts_seen = set()
for r in report:
    text = r['authority_text']
    texts_seen.add(text)
    if text in TRAP_TEXTS:
        buckets["trap_not_separator"].append((r, TRAP_TEXTS[text]))
        continue
    if text in STRICT_DROP_TEXTS:
        buckets["strict_spelled_out_drop"].append(r)
        continue
    if text in ALREADY_CAPTURED_TEXTS:
        buckets["already_captured_not_dropped"].append(r)
        continue
    shapes = classify_remaining(text, r['pieces'])
    if any(s in ("act_abbrev_number","act_abbrev_bare") for s in shapes):
        buckets["compact_act_abbrev_drop"].append((r, shapes))
    elif any(s == "bare_number_no_act_token" for s in shapes):
        buckets["ambiguous_bare_number"].append((r, shapes))
    elif any(s == "garbled_double_slash" for s in shapes):
        buckets["ambiguous_garbled"].append((r, shapes))
    else:
        buckets["ambiguous_other"].append((r, shapes))

for name, items in buckets.items():
    texts = [it[0]['authority_text'] if isinstance(it, tuple) else it['authority_text'] for it in items]
    rows = sum((it[0]['row_count'] if isinstance(it, tuple) else it['row_count']) for it in items)
    print(f"{name}: {len(items)} texts, {rows} rows")

print()
print("=== ambiguous_other detail ===")
for it in buckets["ambiguous_other"]:
    r, shapes = it
    print(r['authority_text'], '| rows=', r['row_count'], '| shapes=', shapes)

print()
print("=== ambiguous_bare_number detail ===")
for it in buckets["ambiguous_bare_number"]:
    r, shapes = it
    print(r['authority_text'], '| rows=', r['row_count'], '| shapes=', shapes)

print()
print("=== ambiguous_garbled detail ===")
for it in buckets["ambiguous_garbled"]:
    r, shapes = it
    print(r['authority_text'], '| rows=', r['row_count'], '| shapes=', shapes)

json.dump({k: [(it[0]['authority_text'], it[0]['row_count']) if isinstance(it, tuple) else (it['authority_text'], it['row_count']) for it in v]
           for k,v in buckets.items()}, open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_buckets_summary.json','w'), indent=1)
print()
print("total distinct texts across buckets:", sum(len(v) for v in buckets.values()), "vs total input distinct texts", len(texts_seen))
