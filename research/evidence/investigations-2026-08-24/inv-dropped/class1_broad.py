import json, re

report = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_report.json'))

TRAP_TEXTS = {
    "PL 110-53, sec 1413, The Implementing Recommendations of the 9/11 Commission Act of 2007",
    "PL 110-53, sec 1521, The Implementing Recommendations of the 9/11 Commission Act of 2007",
    "PL 110-53, sec 1536, The Implementing Recommendations of the 9/11 Commission Act of 2007",
    "PL 110-53, sec 711, 9/11 Act",
    "Pub. L. 110-53, sec 1413, The Implementing Recommendations of the 9/11 Commission Act of 2007",
    "Pub. L. 110-53, sec 1521, The Implementing Recommendations of the 9/11 Commission Act of 2007",
    "Pub. L. 110-53, sec 1536, The Implementing Recommendations of the 9/11 Commission Act of 2007",
    "Pub. L. 110-53, sec 711, 9/11 Act",
    "Pub. L. 117-180, Division G – Hermit’s Peak/Calf Canyon Fire Assistance Act",
    "Pub. L. 117-180, Division G – Hermit’s Peak/Calf Canyon Fire Assistance Act (Act)",
    "PL 106-554, Treasury/General Government Appropriations Act of 2001",
    "S/B Improving Head Start for School Readiness Act of 2007, PL 110-134",
}

# strict genuine-drop texts already identified (spelled-out act name, section stated or not)
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

# already-captured-by-whole-string-scan (not actually dropped)
ALREADY_CAPTURED_TEXTS = {
    "33 USC 1251/33 USC 1345",
    "33 USC 1361(a)/76 Stat 816",
    "33 USC 1361(a)/76 Stat. 816",
    "33 USC 2601/Shore Protection Act of 1988 (PL 100-6-88),4103(b)",
    "42 USC 2021(h)/AEA 274(h)/Reorganization Plan No. 3 of 1970",
    "42 USC 2021(h)/AEA(h)/Reorganization Plan No. 3 of 1970",
}

remaining = [r for r in report if r['authority_text'] not in TRAP_TEXTS
             and r['authority_text'] not in STRICT_DROP_TEXTS
             and r['authority_text'] not in ALREADY_CAPTURED_TEXTS]

print("remaining unclassified texts:", len(remaining))
for r in remaining:
    print(r['authority_text'], '| rows=', r['row_count'])
