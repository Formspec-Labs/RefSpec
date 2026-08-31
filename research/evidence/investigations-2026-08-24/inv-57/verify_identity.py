import json, re

data = json.load(open('/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-57/la_boxes_with_artifact.json'))
boxes = data['boxes']
artifact_rows = data['artifact_rows']

DASH_CPS = {0x96, 0x97}
QUOTE_CPS = {0x91, 0x92, 0x93, 0x94}

bridged = []       # byte sits between two alnum chars AND some artifact usc_section/admin_order_number/etc value spans across it (joined with '-')
not_bridged_but_harmless = []  # byte is decorative (quote mark, punctuation between clauses) with no citation number touching it
unclear = []

for key, info in boxes.items():
    text = info['box_text_raw']
    cps = info['codepoints']
    rows = artifact_rows[key]
    for cpstr in cps:
        cp = int(cpstr[2:], 16)
        idx = text.find(chr(cp))
        if idx == -1:
            continue
        before_ch = text[idx-1] if idx > 0 else ''
        after_ch = text[idx+1] if idx+1 < len(text) else ''
        alnum_adjacent = before_ch.isalnum() and after_ch.isalnum()
        # gather all string-valued identity fields from rows
        joined_hit = False
        for row in rows:
            for field in ('usc_section','usc_section_end','admin_order_number','act_section','statute_page','public_law','cfr_section','cfr_part'):
                v = row.get(field)
                if v is None:
                    continue
                v = str(v)
                # does v contain both a fragment ending at 'before_ch' region and a fragment starting at 'after_ch' region, joined by '-'?
                # crude check: does v contain '-' and does v's pre-dash part end matching text right before idx, and post-dash part match text right after idx?
                if '-' in v:
                    pre, _, post = v.rpartition('-')
                    # check suffix of "before idx" text ends with pre (some tail) and prefix of "after idx" text starts with post
                    before_text = text[:idx]
                    after_text = text[idx+1:]
                    if pre and before_text.endswith(pre) and post and after_text.startswith(post):
                        joined_hit = True
        if joined_hit:
            bridged.append((key, cpstr, text))
        elif not alnum_adjacent:
            not_bridged_but_harmless.append((key, cpstr, text))
        else:
            unclear.append((key, cpstr, text, [{'type':r['authority_type'],'status':r['parse_status'],'usc':r['usc_section'],'usc_end':r['usc_section_end'],'pl':r['public_law']} for r in rows]))

print('bridged (byte correctly joined into one citation token):', len(bridged))
print('not bridged but harmless (byte not between citation digits):', len(not_bridged_but_harmless))
print('UNCLEAR (byte between alnum chars, no bridging match found -- needs manual look):', len(unclear))
print()
for u in unclear:
    print('UNCLEAR:', u)
