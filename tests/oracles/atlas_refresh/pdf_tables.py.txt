import json,re,xml.etree.ElementTree as ET
from pathlib import Path
import argparse
parser=argparse.ArgumentParser(description='Extract bounded retained PDF tables by word geometry, without producer readers.')
parser.add_argument('--output-dir',type=Path,required=True)
base=parser.parse_args().output_dir.resolve()
NS={'h':'http://www.w3.org/1999/xhtml'}
FOLDS=str.maketrans({'ﬀ':'ff','ﬁ':'fi','ﬂ':'fl','ﬃ':'ffi','ﬄ':'ffl','ﬅ':'st','ﬆ':'st','‐':'-','‑':'-'})
def norm(s):return ' '.join(s.split()).translate(FOLDS)
def pages(name):
 for p in ET.parse(base/name).findall('.//h:page',NS):
  yield [{'text':w.text or '',**{k:float(w.attrib[k]) for k in ('xMin','xMax','yMin','yMax')}} for w in p.findall('.//h:word',NS)]
def group(words):
 result=[]
 for w in sorted(words,key=lambda w:(w['yMin'],w['xMin'])):
  if not result or abs(result[-1][0]['yMin']-w['yMin'])>1.0: result.append([w])
  else:result[-1].append(w)
 return [' '.join(w['text'] for w in sorted(row,key=lambda w:w['xMin'])) for row in result]
cls=[]; class_orphans=[]
for pn,words in enumerate(pages('class-bbox.html'),1):
 anchor=next(w for w in words if w['text']=='Category')
 headers=[next(w for w in words if w['text']==name and abs(w['yMin']-anchor['yMin'])<1) for name in ('Category','Library','Classification','Type')]
 xs=[w['xMin']-1 for w in headers]+[1000]
 starts=sorted([w for w in words if w['text'] in ('Issuance','Submittal') and w['xMin']<xs[1]],key=lambda w:w['yMin'])
 orphan=[w for w in words if min(x['yMin'] for x in starts)-1<=w['yMin']<=max(x['yMin'] for x in starts)+1 and all(abs(w['yMin']-y)>=1 for y in [x['yMin'] for x in starts]+[headers[0]['yMin']])]
 class_orphans.extend({'page':pn,'word':w} for w in orphan)
 assert not orphan,(pn,orphan)
 for n,start in enumerate(starts):
  row_words=[w for w in words if abs(w['yMin']-start['yMin'])<1]
  cells=[' '.join(w['text'] for w in sorted(row_words,key=lambda w:w['xMin']) if xs[i]<=w['xMin']<xs[i+1]) for i in range(4)]
  assert all(cells),(pn,start,cells)
  cls.append({'page':pn,'page_row':n,'y':start['yMin'],'raw_cells':cells,'native':dict(zip(('category','library','classification','type_description'),map(norm,cells)))})
dockets=[];status=None
for pn,words in enumerate(pages('docket-bbox.html'),1):
 text=' '.join(group(words))
 if 'Table 1' in text or 'Table 2' in text:status='active'
 if 'Table 3' in text:status='discontinued'
 anchor=next(w for w in words if w['text']=='Library')
 headers=[next(w for w in words if w['text']==name and abs(w['yMin']-anchor['yMin'])<1) for name in ('Prefix','Library','Definition')]
 xs=[w['xMin']-1 for w in headers]+[1000]
 starts=sorted([w for w in words if w['xMin']>=xs[0] and w['xMin']<xs[1] and w['yMin']>headers[0]['yMin']+1 and re.fullmatch('[A-Z]{1,3}-?',w['text'])],key=lambda w:w['yMin'])
 for n,start in enumerate(starts):
  yend=starts[n+1]['yMin']-1 if n+1<len(starts) else 720
  cells=[' '.join(group([w for w in words if start['yMin']-1<=w['yMin']<yend and xs[i]<=w['xMin']<xs[i+1]])) for i in range(3)]
  assert all(cells),(pn,start,cells)
  dockets.append({'page':pn,'page_row':n,'raw_cells':cells,'native':{'status':status,**dict(zip(('prefix','library','definition'),map(norm,cells)))}})
ua=(base/'ua-glossary.txt').read_text();ua=ua.split('V. Abbreviations',1)[1]
ua=re.sub(r'^\s*(18|19)\s*$', '',ua,flags=re.M)
markers=list(re.finditer(r'^([A-Za-z][A-Za-z. ]*) -- ',ua,re.M))
glossary={m.group(1):norm(ua[m.end():(markers[i+1].start() if i+1<len(markers) else len(ua))]) for i,m in enumerate(markers)}
selected={k:glossary[k] for k in ('U.S.C.','Pub. L.','E.O.')}
result={'unassigned_class_table_words':class_orphans,'classes':cls,'dockets':dockets,'ua':selected,'glossary_labels':list(glossary)}
(base/'independent-extraction.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
print('counts',len(cls),len(dockets),len(selected));print('docketpages',[(p,len([x for x in dockets if x['page']==p])) for p in range(1,7)])
print('classdupAnnualCharges',[r for r in cls if r['native']['type_description']=='Annual Charges Report'])
