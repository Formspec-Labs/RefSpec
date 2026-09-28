#!/usr/bin/env python3
"""Read-only independent agency artifact check; no refspec/producer imports or fetching.

Run with the repository's Python (rdflib, pyarrow, backports.zstd). The expected
rows come directly from the candidate JSON and recorded owner answers. This is
a bounded artifact comparison, not a replacement generic fidelity verifier.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, os, subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import pyarrow.parquet as pq
import rdflib
from backports import zstd
from rdflib.plugins.serializers.nt import _quoteLiteral

A = rdflib.Namespace('https://refspec.org/ns/atlas/v3#')
R = rdflib.Namespace('https://rulespec.org/ns/v1#')
RDF = rdflib.RDF
KEY = 'agency-registry-2026-09-26'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def sorted_rows(rows):
    return sorted(rows, key=canonical)


def differences(expected, actual, path=''):
    if type(expected) is not type(actual):
        return [dict(path=path, expected=expected, actual=actual)]
    if isinstance(expected, dict):
        out=[]
        for key in sorted(set(expected)|set(actual)):
            if key not in expected or key not in actual:
                out.append(dict(path=path+'/'+key, expected=expected.get(key,'<missing>'), actual=actual.get(key,'<missing>')))
            else:
                out.extend(differences(expected[key], actual[key], path+'/'+key))
        return out
    if isinstance(expected,list):
        out=[]
        if len(expected)!=len(actual): out.append(dict(path=path+'/length', expected=len(expected), actual=len(actual)))
        for i,(e,a) in enumerate(zip(expected,actual)):out.extend(differences(e,a,path+'/'+str(i)))
        return out
    return [] if expected==actual else [dict(path=path,expected=expected,actual=actual)]


def expected_from_plans(c, d):
    decisions=d['decisions'];reviewer=d['reviewer_iri']
    def decision(item_id):
        return {**decisions[item_id], 'note':decisions[item_id].get('note'), 'reviewer':reviewer}
    def parent(endpoint):
        return (endpoint.get('parent') or {}).get('resource_iri')
    bridges=[];events=[];non=[];event_details={}
    for row in c['candidates']:
        if row.get('relation')!='sameEntityAs' or decisions[row['candidate_id']]['answer']!='yes':continue
        s,o=row['source'],row['target']
        bridges.append(dict(candidate_id=row['candidate_id'],subject=s['resource_iri'],subject_publisher_name=s['publisher_name'],subject_parent=parent(s),object=o['resource_iri'],object_release_key=o['release_key'],object_publisher_name=o['publisher_name'],object_parent=parent(o),relation=row['relation_iri'],basis=row['proposed_basis'],reasoning=row['reasoning'],evidence_tier='E4',warrant='humanReview',decision=decision(row['candidate_id'])))
    for event in c['events']:
        eid=event['event_id'];details=[]
        assert decisions[eid]['answer'] in ('accept','accept-every-row','1')
        rows=[r for r in c['candidates'] if r.get('event_id')==eid]
        assert set(event['rows'])=={r['candidate_id'] for r in rows}
        for row in rows:
            target=row['target']
            events.append(dict(event_id=eid,effective_date=event['effective_date'],date_basis=event['date_basis'],originals=[o['resource_iri'] for o in event['originals']],result=target['resource_iri'],result_publisher_name=target['publisher_name'],functions_taken=row.get('functions_taken'),reasoning=row['reasoning'],public_records=event['public_records'],evidence_tier='E4',warrant='humanReview',decision=decision(eid)))
            item=dict(publisherName=target['publisher_name'],reasoning=row['reasoning'],resourceIri=target['resource_iri'],rowId=row['candidate_id'])
            if row.get('functions_taken') is not None:item['functionsTaken']=row['functions_taken']
            details.append(item)
        event_details[eid]=dict(dateBasis=event['date_basis'],effectiveDate=event['effective_date'],eventId=eid,originals=[dict(publisherName=o['publisher_name'],resourceIri=o['resource_iri']) for o in event['originals']],results=sorted(details,key=lambda r:r['rowId']))
    special={'same:fr151:ecfr:export-import-bank':('2','sameOrganizationReverseLookupCostRejected'),'same:fr296:fh:300000070':('1','heldForStatutoryRenameBasis')}
    for row in c['candidates']:
        item_id=row['candidate_id']
        if item_id not in special:continue
        answer,reason=special[item_id]
        assert decisions[item_id]['answer']==answer
        non.append(dict(item_id=item_id,reason=reason,reasoning=row['owner_question']['options'][int(answer)-1],subject=row['source']['resource_iri'],subject_value=None,object=row['target']['resource_iri'],closest_alternative=None,decision=decision(item_id)))
    for row in c['non_emissions']:
        item_id=row['candidate_id'];assert decisions[item_id]['answer']=='confirm'
        non.append(dict(item_id=item_id,reason='withdrawn',reasoning=row['reason'],subject=row['source']['resource_iri'],subject_value=None,object=row['target']['resource_iri'],closest_alternative=row.get('closest_alternative'),decision=decision(item_id)))
    for row in c['no_fr_bridge']:
        item_id=row['value_id'];assert decisions[item_id]['answer']=='confirm'
        non.append(dict(item_id=item_id,reason=row['reason'],reasoning=row['reasoning'],subject=None,subject_value=row['value'],object=None,closest_alternative=None,decision=decision(item_id)))
    return {'bridges':sorted_rows(bridges),'events':sorted_rows(events),'non-emissions':sorted_rows(non)},event_details


def check_raw_endpoints(repo,c):
    """Read source JSON fields directly, without producer roster readers."""
    fr_path=repo/'tests/fixtures/federal_register_native_controls/fr-agencies-2026-08-15.json'
    ecfr_path=repo/'tests/fixtures/cfr_list_of_subjects/ecfr-agencies-2026-08-15.json'
    fh_paths=sorted((repo/'tests/fixtures/federal_hierarchy_complete').glob('fh-orgs-all-page-*.json'))
    fr={r['id']:r for r in json.loads(fr_path.read_text())}
    ecfr={}
    def visit(rows,parent=None):
        for row in rows:
            ecfr[row['slug']]=(row,parent);visit(row.get('children',[]),row['slug'])
    visit(json.loads(ecfr_path.read_text())['agencies'])
    fh={r['fhorgid']:(r,p) for p in fh_paths for r in json.loads(p.read_text())['orglist']}
    endpoints={}
    for row in c['candidates']+c['non_emissions']:
        for role in ('source','target'):
            e=row[role];endpoints[e['resource_iri']]=e
    for event in c['events']:
        for e in event['originals']:endpoints[e['resource_iri']]=e
    errors=[];receipts=[]
    for iri,e in sorted(endpoints.items()):
        if e['roster']=='federal-register-agencies':
            raw=fr[e['id']];path=fr_path;name=raw['name'];parent=raw['parent_id']
            parent_value=None if parent is None else dict(resource_iri='urn:ref:federal-register-agency:'+str(parent),publisher_name=fr[parent]['name'])
            context={k:raw[k] for k in ('id','slug','name','short_name','parent_id')}
        elif e['roster']=='ecfr-agencies':
            raw,parent=ecfr[e['slug']];path=ecfr_path;name=raw['name']
            parent_value=None if parent is None else dict(resource_iri='urn:ref:ecfr-agency:'+parent,publisher_name=ecfr[parent][0]['name'])
            context={k:raw[k] for k in ('slug','name','short_name')};context['parentSlugFromNesting']=parent
        elif e['roster']=='federal-hierarchy-organizations':
            raw,path=fh[int(iri.rsplit(':',1)[1])];name=raw['fhorgname'];parent=raw['fhdeptindagencyorgid']
            parent_value=None if parent==raw['fhorgid'] else dict(resource_iri='urn:ref:federal-hierarchy-org:'+str(parent),publisher_name=fh[parent][0]['fhorgname'])
            context={k:raw[k] for k in ('fhorgid','fhorgname','fhorgtype','fhdeptindagencyorgid','fhagencyorgname')}
        else:raise ValueError('unexpected endpoint roster '+e['roster'])
        observed=dict(publisher_name=name,parent=parent_value);wanted={k:e[k] for k in observed}
        delta=differences(wanted,observed,'raw-endpoint/'+iri);errors.extend(delta)
        receipts.append(dict(resourceIri=iri,sourcePath=str(path.relative_to(repo)),sourceSha256=sha(path),sourceContext=context,match=not delta))
    return errors,receipts,[fr_path,ecfr_path,*fh_paths]


def read_graph(path):
    data=zstd.decompress(path.read_bytes());dataset=rdflib.Dataset();dataset.parse(data=data.decode(),format='nquads')
    graph=rdflib.Graph()
    for s,p,o,_ in dataset.quads():graph.add((s,p,o))
    return graph,len(dataset)


def check_rdf(g,c,d,expected,details,decision_sha):
    errors=[];snapshot={'events':[], 'bridges':[], 'nonEmissionAbsences':[]}
    def check(label,e,a):
        errors.extend(differences(e,a,label))
    def one(s,p):
        values=list(g.objects(s,p))
        if len(values)!=1:
            errors.append(dict(path=f'{s}/{p}/cardinality',expected=1,actual=len(values)))
            return values[0] if values else None
        return values[0]
    def strings(s,p):return sorted(str(x) for x in g.objects(s,p))
    payloads={s:json.loads(str(o)) for s,o in g.subject_objects(A.nativePayload)}
    event_nodes=set(g.subjects(RDF.type,A.OrganizationChangeEvent));assertion_nodes=set(g.subjects(RDF.type,RDF.Statement))
    # The physical producer class can differ from rdf:Statement; rdf:subject defines each bridge assertion.
    assertion_nodes=set(g.subjects(RDF.subject,None))
    check('RDF/event-count',len(details),len(event_nodes));check('RDF/bridge-count',len(expected['bridges']),len(assertion_nodes))
    by_item=defaultdict(list)
    for record,payload in payloads.items():
        owner=payload.get('ownerDecision',{});item_id=owner.get('itemId');by_item[item_id].append((record,payload))
        raw=d['decisions'].get(item_id,{})
        owner_expected=dict(answer=raw.get('answer'),channel=raw.get('channel'),contentDigest=raw.get('content_digest'),decidedOn=raw.get('decided_on'),decisionsFile='plans/agency-registry-batch-1-decisions.json',decisionsFileSha256='sha256:'+decision_sha,itemId=item_id)
        if 'note' in raw:owner_expected['note']=raw['note']
        check(f'{item_id}/ownerDecision',owner_expected,owner)
        check(f'{item_id}/reviewer',d['reviewer_iri'],payload.get('reviewerIri'))
        check(f'{item_id}/evidenceTier','E4',payload.get('evidenceTier'))
        check(f'{item_id}/decision','adopted',payload.get('decision'))
        check(f'{item_id}/decidedAt',raw.get('decided_on','')+'T00:00:00+00:00',payload.get('decidedAt'))
        literal=one(record,A.nativePayload);native_digest='sha256:'+hashlib.sha256(str(literal).encode()).hexdigest()
        check(f'{item_id}/sourceDigest',native_digest,str(one(record,A.sourceDigest)))
        # README section 'RDF record digests': sorted N-Triples predicate-object lines.
        lines=sorted(f'{p.n3()} {_quoteLiteral(o) if isinstance(o,rdflib.Literal) else o.n3()} .' for p,o in g.predicate_objects(record) if p!=A.contentDigest)
        record_digest='sha256:'+hashlib.sha256(('\n'.join(lines)+'\n').encode()).hexdigest()
        bindings=list(g.subjects(A.evidenceSourceRecord,record));check(f'{item_id}/binding-count',1,len(bindings))
        for binding in bindings:
            for predicate,value in ((R.attestor,d['reviewer_iri']),(R.attestedAt,raw.get('decided_on','')+'T00:00:00+00:00'),(R.decision,str(R.approved)),(R.assertionOrigin,str(R.humanAsserted)),(R.attestorKind,str(R.humanUser)),(R.epistemicBasis,str(R.editorialAssertion)),(R.evidentiaryFunction,str(R.supports)),(R.evidenceRole,str(R.textualEvidence)),(A.evidenceSourceDigest,record_digest)):
                check(f'{item_id}/binding/{predicate}',value,str(one(binding,predicate)))
    seen_event_nodes=set();seen_bridge_nodes=set()
    for event in c['events']:
        eid=event['event_id'];pairs=by_item[eid]
        check(f'{eid}/source-count',len(event['public_records']),len(pairs))
        check(f'{eid}/publicRecords',sorted_rows(event['public_records']),sorted_rows([p.get('publicRecord') for _,p in pairs]))
        targets=set()
        for record,payload in pairs:
            got=copy.deepcopy(payload.get('event',{}))
            if 'results' in got:got['results'].sort(key=lambda r:r['rowId'])
            check(f'{eid}/event-native',details[eid],got)
            check(f'{eid}/sourceLocator',payload['publicRecord']['url'],str(one(record,A.sourceLocator)))
            for binding in g.subjects(A.evidenceSourceRecord,record):targets.add(one(binding,R.bindsAssertion))
        check(f'{eid}/event-target-count',1,len(targets))
        for node in targets:
            seen_event_nodes.add(node)
            check(f'{eid}/type',True,(node,RDF.type,A.OrganizationChangeEvent) in g)
            check(f'{eid}/originals',sorted(o['resource_iri'] for o in event['originals']),strings(node,A.originalOrganization))
            check(f'{eid}/results',sorted(r['resourceIri'] for r in details[eid]['results']),strings(node,A.resultingOrganization))
            literal=one(node,R.effectiveDate)
            check(f'{eid}/effectiveDate',event['effective_date']+'T00:00:00+00:00',str(literal))
            check(f'{eid}/effectiveDate-datatype',str(rdflib.XSD.dateTime),str(getattr(literal,'datatype',None)))
            snapshot['events'].append(dict(eventId=eid,node=str(node),effectiveDate=str(literal),originals=strings(node,A.originalOrganization),results=strings(node,A.resultingOrganization),evidenceRecords=sorted(str(r) for r,_ in pairs),event=details[eid]))
    actual_triples=set()
    for node in assertion_nodes:
        actual_triples.add((str(one(node,RDF.subject)),str(one(node,RDF.predicate)),str(one(node,RDF.object))))
    expected_triples={(r['subject'],r['relation'],r['object']) for r in expected['bridges']}
    check('RDF/bridge-triples',sorted(expected_triples),sorted(actual_triples))
    for row in expected['bridges']:
        item_id=row['candidate_id'];raw_row=next(r for r in c['candidates'] if r['candidate_id']==item_id);pairs=by_item[item_id];check(item_id+'/source-count',2,len(pairs))
        roles=[];targets=set()
        for record,payload in pairs:
            roles.append(payload.get('endpointRole'))
            for key,value in (('decisionBasis',row['basis']),('reasoning',row['reasoning']),('subjectIri',row['subject']),('predicateIri',row['relation']),('objectIri',row['object']),('publisherNames',dict(subject=row['subject_publisher_name'],object=row['object_publisher_name'])),('parents',{role:{'publisherName':raw_row[endpoint]['parent']['publisher_name'],'resourceIri':raw_row[endpoint]['parent']['resource_iri']} for role,endpoint in [('subject','source'),('object','target')] if raw_row[endpoint].get('parent')}),('nameSimilarityUsed',False)):
                check(item_id+'/'+key,value,payload.get(key))
            role=payload.get('endpointRole');ep=payload.get('endpointRecord',{})
            check(item_id+'/endpoint/'+str(role)+'/resourceIri',row.get(role),ep.get('resourceIri'))
            check(item_id+'/endpoint/'+str(role)+'/publisherName',row.get(str(role)+'_publisher_name'),ep.get('publisherName'))
            check(item_id+'/endpoint/'+str(role)+'/value',row.get(str(role)+'_publisher_name'),ep.get('value'))
            for binding in g.subjects(A.evidenceSourceRecord,record):targets.add(one(binding,R.bindsAssertion))
        check(item_id+'/endpointRoles',['object','subject'],sorted(roles));check(item_id+'/assertion-count',1,len(targets));seen_bridge_nodes.update(targets)
        snapshot['bridges'].append(dict(candidateId=item_id,nodes=sorted(map(str,targets)),subject=row['subject'],relation=row['relation'],object=row['object'],evidenceRecords=sorted(str(r) for r,_ in pairs)))
    check('RDF/event-coverage',sorted(map(str,event_nodes)),sorted(map(str,seen_event_nodes)))
    check('RDF/bridge-coverage',sorted(map(str,assertion_nodes)),sorted(map(str,seen_bridge_nodes)))
    check('RDF/item-coverage',sorted(set(details)|{r['candidate_id'] for r in expected['bridges']}),sorted(by_item))
    check('RDF/source-record-count',sum(len(e['public_records']) for e in c['events'])+2*len(expected['bridges']),len(payloads))
    for row in expected['non-emissions']:
        present=bool(by_item.get(row['item_id'])) or bool(row['subject'] and (row['subject'],str(A.sameEntityAs),row['object']) in actual_triples)
        if row['subject_value']=='CISA':present=present or any(t[0].endswith(':CISA') or t[2].endswith(':CISA') for t in actual_triples)
        check(row['item_id']+'/no-emitted-bridge',False,present)
        snapshot['nonEmissionAbsences'].append(dict(itemId=row['item_id'],absent=not present))
    for rows in snapshot.values():rows.sort(key=canonical)
    return errors,snapshot


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,default=Path(os.environ.get('REFSPEC_REPO',Path.cwd())))
    ap.add_argument('--distribution',type=Path,default=Path('output/atlas-3.1-agency-2026-09-27/distribution'))
    ap.add_argument('--agency-view',type=Path,default=Path('output/agency-registry-view'))
    ap.add_argument('--claim-receipt',type=Path,default=Path(__file__).resolve().parent.parent/'claim-receipt.json',help='Retained manual primary-source review; compared to the same candidate fields')
    ap.add_argument('--evidence-dir',type=Path,help='Optional original primary-evidence directory; hashes every retained source without fetching')
    ap.add_argument('--output-dir',type=Path,required=True)
    args=ap.parse_args();repo=args.repo.resolve();out=args.output_dir.resolve()
    if out.is_relative_to(repo):ap.error('--output-dir must be outside the repository (read-only check)')
    dist=args.distribution if args.distribution.is_absolute() else repo/args.distribution
    view=args.agency_view if args.agency_view.is_absolute() else repo/args.agency_view
    cp=repo/'plans/agency-registry-batch-1-candidates.json';dp=repo/'plans/agency-registry-batch-1-decisions.json'
    c=json.loads(cp.read_text());d=json.loads(dp.read_text());expected,details=expected_from_plans(c,d)
    actual={key:sorted_rows(pq.read_table(view/'tables'/f'agency-registry-{key}.parquet').to_pylist()) for key in expected}
    errors=differences(expected,actual,'Parquet');checks=[]
    endpoint_errors,endpoint_receipts,roster_paths=check_raw_endpoints(repo,c);errors.extend(endpoint_errors)
    claim_checks=[]
    if args.claim_receipt.exists():
        claims=json.loads(args.claim_receipt.read_text())
        errors.extend(differences(sorted(details),sorted(r['eventId'] for r in claims['events']),'manual-review/event-coverage'))
        for reviewed in claims['events']:
            event=next(e for e in c['events'] if e['event_id']==reviewed['eventId'])
            rows=[r for r in c['candidates'] if r.get('event_id')==event['event_id']]
            selected=dict(ownerDecision=d['decisions'][event['event_id']],selectedDate=event['effective_date'],selectedDateBasis=event['date_basis'],originals=event['originals'],results=[dict(candidateId=r['candidate_id'],target=r['target'],functionsTaken=r.get('functions_taken')) for r in rows])
            retained={key:reviewed[key] for key in selected}
            delta=differences(selected,retained,'manual-review/'+event['event_id']);errors.extend(delta)
            claim_checks.append(dict(eventId=event['event_id'],match=not delta,claimStatuses=sorted(set(x['status'] for x in reviewed['claims']))))
    view_manifest=json.loads((view/'view-manifest.json').read_text())
    for member in view_manifest['members']:
        file=view/member['path'];errors.extend(differences(member['sha256'],'sha256:'+sha(file),'view-manifest/'+member['path']))
    manifest=json.loads((dist/'atlas-manifest.json').read_text())
    pack_row=next(p for p in manifest['packs'] if p['path']==f'packs/mappings/{KEY}.nq.zst')
    pack_file=dist/pack_row['path'];errors.extend(differences(pack_row['transport']['digest'],'sha256:'+sha(pack_file),'RDF-manifest/pack-transport-digest'))
    errors.extend(differences(pack_row['content']['digest'],'sha256:'+hashlib.sha256(zstd.decompress(pack_file.read_bytes())).hexdigest(),'RDF-manifest/pack-content-digest'))
    items={r.get('candidate_id',r.get('event_id',r.get('value_id'))):r for key in ('candidates','events','non_emissions','no_fr_bridge') for r in c[key]}
    for item_id,decision in d['decisions'].items():
        errors.extend(differences(items[item_id]['content_digest'],decision['content_digest'],item_id+'/candidate-bound-decision'))
    pack=dist/'packs/mappings'/f'{KEY}.nq.zst';g,nquads=read_graph(pack)
    rdf_errors,snapshot=check_rdf(g,c,d,expected,details,sha(dp));errors.extend(rdf_errors)
    # Real-output mutations demonstrate sensitivity; all mutations are isolated in memory.
    for label,table,key,value in [('date','events','effective_date','1900-01-01'),('date-basis','events','date_basis','wrong basis'),('functions','events','functions_taken','all functions'),('result-name','events','result_publisher_name','wrong name'),('result-iri','events','result','urn:wrong'),('originals','events','originals',[]),('owner-answer','events','decision',{}),('bridge-parent','bridges','object_parent','urn:wrong'),('bridge-basis','bridges','basis','wrong basis'),('non-emission-reason','non-emissions','reason','wrong'),('non-emission-decision','non-emissions','decision',{})]:
        changed=copy.deepcopy(actual);changed[table][0][key]=value
        found=differences(expected,changed,'Parquet');checks.append(dict(mutation=label,detected=bool(found),differenceCount=len(found)))
    changed=copy.deepcopy(actual);changed['events'].pop();checks.append(dict(mutation='drop-event-result',detected=bool(differences(expected,changed))))
    event_node=next(g.subjects(RDF.type,A.OrganizationChangeEvent));old=next(g.objects(event_node,R.effectiveDate));g.remove((event_node,R.effectiveDate,old));g.add((event_node,R.effectiveDate,rdflib.Literal('1900-01-01T00:00:00+00:00',datatype=rdflib.XSD.dateTime,normalize=False)))
    mutation_errors,_=check_rdf(g,c,d,expected,details,sha(dp));checks.append(dict(mutation='RDF-effective-date',detected=bool(mutation_errors),differenceCount=len(mutation_errors)))
    g.remove((event_node,R.effectiveDate,None));g.add((event_node,R.effectiveDate,old))
    record,literal=next((s,o) for s,o in g.subject_objects(A.nativePayload) if '"event":' in str(o));payload=json.loads(str(literal));payload['event']['dateBasis']='wrong basis';g.remove((record,A.nativePayload,literal));g.add((record,A.nativePayload,rdflib.Literal(canonical(payload),datatype=literal.datatype)))
    mutation_errors,_=check_rdf(g,c,d,expected,details,sha(dp));checks.append(dict(mutation='RDF-native-date-basis-and-digest',detected=bool(mutation_errors),differenceCount=len(mutation_errors)))
    errors.extend(dict(path='mutation/'+m['mutation'],expected=True,actual=False) for m in checks if not m['detected'])
    source_hashes=[]
    if args.evidence_dir:
        ev=args.evidence_dir.resolve()
        for receipt in json.loads((ev/'source-receipts.json').read_text()):
            path=ev/receipt['retainedPath'];observed=sha(path);ok=observed==receipt['sha256'] and path.stat().st_size==receipt['bytes']
            source_hashes.append(dict(sourceUrl=receipt['sourceUrl'],sha256=observed,match=ok))
            if not ok:errors.append(dict(path='source-hash/'+receipt['retainedPath'],expected=receipt['sha256'],actual=observed))
    paths=[cp,dp,dist/'atlas-manifest.json',pack,view/'view-manifest.json']+[view/'tables'/f'agency-registry-{key}.parquet' for key in expected]
    paths.extend(roster_paths)
    generic_manifest=dist.parent/'parquet-view/view-manifest.json'
    if generic_manifest.exists():paths.append(generic_manifest)
    digests=[dict(path=str(p.relative_to(repo)) if p.is_relative_to(repo) else str(p),sha256=sha(p),bytes=p.stat().st_size) for p in paths]
    receipt=dict(checkedAtUtc=datetime.now(timezone.utc).isoformat(),repoHead=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),status='passed' if not errors else 'failed',counts=dict(events=len(details),eventResults=len(actual['events']),bridges=len(actual['bridges']),nonEmissions=len(actual['non-emissions']),rdfQuads=nquads,rdfEventEvidenceRecords=sum(len(e['public_records']) for e in c['events']),rdfBridgeEvidenceRecords=2*len(actual['bridges']),ownerDecisions=len(d['decisions'])),digests=digests,errors=errors,mutationChecks=checks,retainedSourceHashChecks=source_hashes,manualSourceReviewFieldChecks=claim_checks,rawRosterEndpointsChecked=len(endpoint_receipts),limits=['Owner date and identity choices preserved, not re-adjudicated.','Expected output derived from raw candidates and owner decisions; no producer semantic imports.','Generic Atlas typed Parquet intentionally omits change events; dedicated registry view checked separately.','Public-source factual review is a separate claim receipt, not replaced by matching candidate text.','Decision digest equality is checked; the owner candidate-content digest algorithm is not re-derived.', 'SourceRecord sourceDigest hashes its emitted native JSON; primary public-document bytes are separately retained and hashed.', 'This bounded comparison does not qualify all Atlas construction units.'])
    out.mkdir(parents=True,exist_ok=True)
    for name,data in [('artifact-comparison.json',receipt),('actual-agency-tables.json',actual),('actual-agency-rdf.json',snapshot),('raw-roster-endpoints.json',endpoint_receipts)]:
        (out/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(dict(status=receipt['status'],counts=receipt['counts'],differences=len(errors),mutationsDetected=sum(x['detected'] for x in checks),mutationCount=len(checks))))
    if errors:print(json.dumps(errors[:10],indent=2));return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
