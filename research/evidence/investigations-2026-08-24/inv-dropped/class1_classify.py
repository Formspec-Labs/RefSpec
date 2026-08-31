import json, re

d = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_full_analysis.json'))
results = d['results']

# Classify each text
DROPPED = []
NOT_SEPARATOR = []
AMBIGUOUS = []
NEITHER_PIECE_RECOGNIZED = []

for r in results:
    text = r['authority_text']
    pieces = r['pieces']
    pas = r['piece_analyses']
    # first piece is the "whole matched" one typically; check pieces[1:] (after slash) primarily
    # but also check piece[0] in case first piece alone doesn't read (rare)
    any_secondary_reads = any(pa['reads_as_authority'] for pa in pas[1:] if pa is not None)
    r['any_secondary_reads'] = any_secondary_reads
    if any_secondary_reads:
        DROPPED.append(r)
    else:
        NEITHER_PIECE_RECOGNIZED.append(r)

print("Texts where >=1 non-first piece reads_as_authority (strict grammar/stated-fallback):", len(DROPPED))
print("Texts where no non-first piece reads_as_authority under strict grammar:", len(NEITHER_PIECE_RECOGNIZED))
print()
print("=== DROPPED (strict) sample ===")
for r in DROPPED[:40]:
    print(r['authority_text'], '| rows=', r['row_count'])
    for pa in r['piece_analyses']:
        if pa is None:
            print('    piece= <empty>')
            continue
        print('    piece=', repr(pa['piece']), 'recognized_type=', pa['recognized_type'], 'stated_fallback=', pa['stated_fallback'])

print()
print("=== whole-string grammar output for DROPPED candidates ===")
for r in DROPPED:
    print(r['authority_text'], '| rows=', r['row_count'])
    for w in r['whole_grammar_out']:
        print('    WHOLE:', {k:v for k,v in w.items() if v not in (None, False)})
