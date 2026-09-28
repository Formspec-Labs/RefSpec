#!/usr/bin/env python3
"""Independent stdlib-only replay of documented agency candidate digest rules.
No producer imports, source fetching, repository writes, or decision changes.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

COVERED = ['candidates', 'events', 'non_emissions', 'no_fr_bridge']
EXCLUDED = {'content_digest', 'effect_note'}
OWNER_AGGREGATE = 'sha256:7fe88a9167a9363f5c2bfdcd3911953b7323abe1564d40586991c9612f95f4bc'


def digest(value):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def file_receipt(path, repo):
    data = path.read_bytes()
    return dict(path=str(path.relative_to(repo)), sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


def owner_fields(item):
    return {key: value for key, value in item.items() if key not in EXCLUDED}


def item_id(item):
    return item.get('candidate_id', item.get('event_id', item.get('value_id')))


def recompute(report):
    receipt = []
    for group in COVERED:
        for item in report[group]:
            members = [r for r in report['candidates'] if r.get('event_id') == item['event_id']] if group == 'events' else []
            preimage = dict(entry=owner_fields(item), members=[owner_fields(row) for row in members])
            observed = digest(preimage)
            receipt.append(dict(group=group, itemId=item_id(item), coveredEntryFields=sorted(preimage['entry']), members=[item_id(r) for r in members], declared=item['content_digest'], observed=observed, matches=observed == item['content_digest']))
    return receipt


def aggregate(report):
    return digest({key: report[key] for key in COVERED})


def links(report, decisions, rows):
    computed = {r['itemId']: r['observed'] for r in rows}
    decidable = {r['candidate_id'] for r in report['candidates'] if r['relation'] == 'sameEntityAs'}
    decidable |= {e['event_id'] for e in report['events']}
    decidable |= {r['candidate_id'] for r in report['non_emissions']}
    decidable |= {r['value_id'] for r in report['no_fr_bridge']}
    out = []
    for key, decision in sorted(decisions['decisions'].items()):
        out.append(dict(itemId=key, answer=decision['answer'], declared=decision['content_digest'], observed=computed.get(key), decidable=key in decidable, matches=computed.get(key) == decision['content_digest']))
    return out, sorted(decidable - set(decisions['decisions'])), sorted(set(decisions['decisions']) - decidable)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(os.environ.get('REFSPEC_REPO', Path.cwd())))
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.output_dir.resolve()
    if out.is_relative_to(repo):
        parser.error('--output-dir must be outside the repository')
    candidate_path = repo / 'plans/agency-registry-batch-1-candidates.json'
    decisions_path = repo / 'plans/agency-registry-batch-1-decisions.json'
    report, decisions = json.loads(candidate_path.read_text()), json.loads(decisions_path.read_text())
    rows = recompute(report)
    decision_links, missing, unknown = links(report, decisions, rows)
    observed_aggregate = aggregate(report)
    top_digest = digest({k: v for k, v in report.items() if k != 'digest'})
    failures = []
    if report['candidates_digest_covers'] != COVERED: failures.append('aggregate coverage declaration differs')
    if not all(row['matches'] for row in rows): failures.append('item digest mismatch')
    if not all(row['matches'] and row['decidable'] for row in decision_links) or missing or unknown: failures.append('decision link mismatch')
    if not observed_aggregate == report['candidates_digest'] == OWNER_AGGREGATE: failures.append('aggregate digest mismatch')
    if top_digest != report['digest']: failures.append('whole-report digest mismatch')
    mutation_specs = [
        ('bridge-reasoning', 'candidates', 'same:fr136:ecfr:energy-department', 'reasoning', None, 'Changed identity reasoning.', ['same:fr136:ecfr:energy-department'], True),
        ('event-date-basis', 'events', 'event:fr559', 'date_basis', None, 'Changed date policy.', ['event:fr559'], True),
        ('event-result-functions', 'candidates', 'succ:fr232:fr499', 'functions_taken', None, 'Changed transferred functions.', ['event:fr232'], True),
        ('numbered-owner-option', 'candidates', 'same:fr151:ecfr:export-import-bank', 'owner_question', 1, 'Changed option text.', ['same:fr151:ecfr:export-import-bank'], True),
        ('excluded-effect-note', 'candidates', 'same:fr136:ecfr:energy-department', 'effect_note', None, 'Changed effect note.', [], True),
    ]
    mutations=[]
    baseline_computed={r['itemId']:r['observed'] for r in rows}
    for label, group, key, field, index, value, stale_expected, aggregate_changed in mutation_specs:
        changed=copy.deepcopy(report)
        row=next(r for r in changed[group] if item_id(r)==key)
        old=copy.deepcopy(row.get(field))
        if index is None:row[field]=value
        else:row[field]['options'][index]=value
        changed_rows=recompute(changed)
        changed_links,_,_=links(changed,decisions,changed_rows)
        stale=sorted(r['itemId'] for r in changed_links if not r['matches'])
        affected=sorted(r['itemId'] for r in changed_rows if r['observed']!=baseline_computed[r['itemId']])
        aggregate_match=aggregate(changed)==report['candidates_digest']
        ok=stale==stale_expected and aggregate_match != aggregate_changed
        mutations.append(dict(name=label,itemId=key,field=field,optionIndex=index,previousValue=old,replacement=value,changedItemDigests=affected,staleDecisionIds=stale,expectedStaleDecisionIds=stale_expected,aggregateStillMatches=aggregate_match,expectedAggregateChanged=aggregate_changed,checksPass=ok,changedAggregate=aggregate(changed)))
        if not ok:failures.append('mutation expectation failed: '+label)
    changed=copy.deepcopy(report);changed['measured']['agency_mention_total']+=1
    unchanged=(recompute(changed)==rows and aggregate(changed)==observed_aggregate)
    mutations.append(dict(name='excluded-replay-count',field='measured.agency_mention_total',allItemAndAggregateDigestsUnchanged=unchanged,wholeReportDigestChanged=digest({k:v for k,v in changed.items() if k!='digest'})!=top_digest,checksPass=unchanged))
    if not unchanged:failures.append('excluded replay count changed candidate digest')
    refs=[('plans/agency-registry-design.md',169,198),('tools/assemble_agency_registry_batch_1.py',83,88),('tools/assemble_agency_registry_batch_1.py',1355,1375),('tools/assemble_agency_registry_batch_1.py',1542,1601),('tools/assemble_agency_registry_batch_1.py',1667,1668),('tools/assemble_agency_registry_batch_1.py',1887,1894),('src/refspec/atlas/v3_registry_alignments_entity.py',1246,1258),('src/refspec/atlas/v3_registry_alignments_entity.py',1300,1307),('src/refspec/atlas/v3_registry_alignments_entity.py',1336,1346),('docs/decisions.md',5977,5986)]
    contexts=[]
    for name,start,end in refs:
        path=repo/name;lines=path.read_text().splitlines()
        contexts.append(dict(path=name,firstLine=start,lastLine=end,sourceSha256=hashlib.sha256(path.read_bytes()).hexdigest(),text='\n'.join(f'{i}: {lines[i-1]}' for i in range(start,end+1))))
    result=dict(status='passed' if not failures else 'failed',rules=dict(aggregateFields=COVERED,entryExcludedFields=sorted(EXCLUDED),entryPreimage='{"entry": all entry fields except content_digest/effect_note, "members": event member rows with same exclusions in retained order; empty for a non-event}',serialization='UTF-8 JSON; sorted object keys; original array order; no spaces; no terminal LF; non-ASCII unchanged; nonfinite numbers refused',eventRowSelection='rows in retained candidates order whose event_id equals the event id; event rows list checked separately',decisionRule='Only identity rows, events, non-emissions, no-bridge codes are decidable; event result rows bind through their event. A changed item digest stales only its decision.'),inputs=[file_receipt(p,repo) for p in (candidate_path,decisions_path)],counts=dict(itemDigests=len(rows),eventDigests=sum(r['group']=='events' for r in rows),eventResultDigests=sum(r['group']=='candidates' and r['itemId'].startswith('succ:') for r in rows),decisionLinks=len(decision_links)),aggregate=dict(declared=report['candidates_digest'],ledgerApproved=OWNER_AGGREGATE,observed=observed_aggregate,matches=observed_aggregate==report['candidates_digest']==OWNER_AGGREGATE),wholeReport=dict(declared=report['digest'],observed=top_digest,matches=top_digest==report['digest']),items=rows,decisions=decision_links,missingDecisionIds=missing,unknownDecisionIds=unknown,mutations=mutations,failures=failures)
    for event in report['events']:
        observed_members=[r['candidate_id'] for r in report['candidates'] if r.get('event_id')==event['event_id']]
        if observed_members!=event['rows']:failures.append('event member order differs: '+event['event_id'])
    result['status']='failed' if failures else 'passed'
    out.mkdir(parents=True,exist_ok=True)
    (out/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (out/'definition-context.json').write_text(json.dumps(contexts,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],counts=result['counts'],aggregate=observed_aggregate,mutations=len(mutations),failures=failures)))
    return bool(failures)

if __name__=='__main__':raise SystemExit(main())
