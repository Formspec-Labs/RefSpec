import json, re, sys
sys.path.insert(0, '/Users/mikewolfd/Work/RefSpec/src')
from refspec.registry.citation_grammar import parse_authority_citation

data = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_slash_texts_raw.json'))

DATE_RE = re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b')
AND_OR_RE = re.compile(r'\band/or\b', re.IGNORECASE)

def whole_grammar_summary(text):
    cits = parse_authority_citation(text)
    out = []
    for c in cits:
        out.append({
            'authority_type': c.authority_type,
            'parse_status': c.parse_status,
            'usc_title': c.usc_title, 'usc_section': c.usc_section, 'usc_section_end': c.usc_section_end,
            'act_key': c.act_key, 'act_section': c.act_section,
            'stated_act_name': c.stated_act_name, 'stated_section': c.stated_section,
            'public_law': c.public_law, 'cfr_title': c.cfr_title, 'cfr_part': c.cfr_part,
            'executive_order': c.executive_order,
        })
    return out

def piece_reads_as_authority(piece):
    piece = piece.strip()
    if not piece:
        return None
    cits = parse_authority_citation(piece)
    recognized = any(c.authority_type not in ('other', 'unstated') for c in cits)
    stated = any(c.stated_act_name is not None for c in cits)
    return {
        'piece': piece,
        'recognized_type': recognized,
        'stated_fallback': stated,
        'reads_as_authority': recognized or stated,
        'grammar_out': whole_grammar_summary(piece),
    }

results = []
excluded_date_only = []
excluded_and_or = []

for row in data:
    text = row['authority_text']
    row_count = row['row_count']
    sample_rin = row.get('sample_rin')
    editions = row.get('editions')

    # find all slash positions
    slash_positions = [m.start() for m in re.finditer(r'/', text)]
    if not slash_positions:
        continue

    # identify date-shaped slash spans
    date_spans = [(m.start(), m.end()) for m in DATE_RE.finditer(text)]
    def in_date_span(pos):
        return any(s <= pos < e for s, e in date_spans)

    non_date_slashes = [p for p in slash_positions if not in_date_span(p)]

    if AND_OR_RE.search(text) and not non_date_slashes:
        excluded_and_or.append(text)
        continue

    if not non_date_slashes:
        excluded_date_only.append(text)
        continue

    # split on non-date slashes only
    pieces = []
    last = 0
    for p in non_date_slashes:
        pieces.append(text[last:p])
        last = p + 1
    pieces.append(text[last:])
    pieces = [pc.strip() for pc in pieces]

    whole_out = whole_grammar_summary(text)

    piece_analyses = [piece_reads_as_authority(pc) for pc in pieces]

    results.append({
        'authority_text': text,
        'row_count': row_count,
        'sample_rin': sample_rin,
        'editions': editions,
        'pieces': pieces,
        'piece_analyses': piece_analyses,
        'whole_grammar_out': whole_out,
    })

print("total candidate texts (has non-date slash):", len(results))
print("excluded as date-only:", len(excluded_date_only))
print("excluded as and/or only:", len(excluded_and_or))
print()
print("=== excluded_date_only ===")
for t in excluded_date_only:
    print(" ", t)
print()

json.dump({
    'results': results,
    'excluded_date_only': excluded_date_only,
    'excluded_and_or': excluded_and_or,
}, open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-dropped/class1_full_analysis.json', 'w'), indent=1)
print("wrote class1_full_analysis.json")
