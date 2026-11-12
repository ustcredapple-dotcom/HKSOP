"""Versioned, dependency-closed records. CAD bytes stay in the shared CAS."""
from pathlib import Path
import copy,hashlib,json

FORMAT='hksop-history-index-v1'
def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
def digest(value):return hashlib.sha256(encoded(value)).hexdigest()
def read_index(root):
 p=Path(root)/'library/history/index.json'
 return json.loads(p.read_text()) if p.exists() else {'format':FORMAT,'entries':[],'resolutions':[],'definitions':[]}
def dependencies(record):
 found=set()
 def walk(v):
  if isinstance(v,dict):
   for k,x in v.items():
    if k.lower().endswith('componentid')and isinstance(x,str):found.add(x)
    elif k.lower().endswith('componentids')and isinstance(x,list):found.update(i for i in x if isinstance(i,str))
    else:walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
 walk(record);return found
def identity(record,components):
 pending=list(dependencies(record));closure={}
 while pending:
  i=pending.pop()
  if i in closure or i not in components:continue
  closure[i]=digest(components[i]);pending.extend(dependencies(components[i]))
 return digest({'record':record,'dependencies':dict(sorted(closure.items()))})
def observe_catalog(root,catalog):
 """Small identity ledger, not catalog snapshots; bind unchanged definitions across catalog releases."""
 root=Path(root);index=read_index(root);definitions=index.setdefault('definitions',[]);lookup={(d['kind'],d['originalId'],d['identitySha256']):d for d in definitions};parts={r['id']:r for r in catalog['components']};changed=False
 for kind in ('components','kits','registeredBoards'):
  for r in catalog[kind]:
   if r.get('lifecycle',{}).get('state')=='historical':continue
   ident=identity(r,parts);key_=(kind,r['id'],ident);row=lookup.get(key_)
   if row is None:row={'kind':kind,'originalId':r['id'],'identitySha256':ident,'catalogVersions':[]};definitions.append(row);lookup[key_]=row
   if catalog['version']not in row['catalogVersions']:row['catalogVersions'].append(catalog['version']);changed=True
 if changed:
  p=root/'library/history/index.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(encoded(index))
 return index
def verify_assets(root,references):
 checked={}
 for ref in references:
  rel=ref['stored']
  if rel in checked:continue
  p=Path(root)/rel
  if not p.resolve().is_relative_to(Path(root).resolve()):raise ValueError('Historical resource escapes library: '+rel)
  if not p.is_file():raise ValueError('Cannot retain missing historical resource: '+rel)
  h=hashlib.sha256()
  with p.open('rb')as f:
   for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
  if h.hexdigest()!=ref['sha256']:raise ValueError('Historical resource hash mismatch: '+rel)
  checked[rel]={'sha256':h.hexdigest(),'bytes':p.stat().st_size}
 return checked
def strings(v):
 if isinstance(v,dict):
  for x in v.values():yield from strings(x)
 elif isinstance(v,list):
  for x in v:yield from strings(x)
 elif isinstance(v,str):yield v
def key(v):
 v=v.removeprefix('/optics-kits/').removeprefix('./').lstrip('/').removeprefix('library/')
 if v.startswith(('step/','drawings/','templates/','sha256/')):v='assets/'+v
 if v.startswith('topviews/'):v='static/'+v
 return v
def asset_refs(records,assets):
 values=set(strings(records));keys={key(v)for v in values}
 for v in values:
  if v in assets.get('replacements',{}):keys.add(key(assets['replacements'][v]))
 refs=[{'logical':k,'stored':s,'sha256':Path(s).stem}for k,s in assets['links'].items()if key(k)in keys or key(s)in keys]
 available={key(x)for r in refs for x in (r['logical'],r['stored'])}
 def required(v):
  if isinstance(v,dict):
   for k,x in v.items():
    if k in ('history','retiredComponents')or 'evidence'in k.lower()or k.lower().startswith('previous'):continue
    if k in ('stepPath','drawingPath','dxfPath','dxfPdfPath','topViewPath','sideViewPath')and isinstance(x,str)and x and not x.startswith(('https:','http:')):yield x
    else:yield from required(x)
  elif isinstance(v,list):
   for x in v:yield from required(x)
 for value in required(records):
  if key(value)not in available and key(assets.get('replacements',{}).get(value,''))not in available:raise ValueError('Historical resource is not registered: '+value)
 return refs
def history_id(original,identity):return original[:170]+'--history-'+identity[:12]
def freeze_resources(record,assets):
 refs=asset_refs([record],assets);lookup={}
 for ref in refs:
  logical=ref['logical'];folder='static/topviews'if logical.startswith('static/topviews/')else 'assets/drawings'if Path(ref['stored']).suffix in ('.pdf','.dxf')else 'assets/step'
  alias=folder+'/history-'+Path(ref['stored']).name
  lookup[key(logical)]=alias;lookup[key(ref['stored'])]=alias
  ref['originalLogical']=logical;ref['logical']=alias
 def walk(v):
  if isinstance(v,dict):
   out={k:walk(x)for k,x in v.items()}
   # Imported records can carry a stale browser URL alongside their verified
   # topViewPath. The frozen display must use that same immutable resource.
   if isinstance(v.get('topViewPath'),str)and isinstance(v.get('topViewUrl'),str)and out['topViewPath']!=v['topViewPath']:out['topViewUrl']='./'+out['topViewPath'].removeprefix('static/').removeprefix('./')
   return out
  if isinstance(v,list):return[walk(x)for x in v]
  if not isinstance(v,str):return v
  alias=lookup.get(key(v))or lookup.get(key(assets.get('replacements',{}).get(v,'')))
  if not alias:return v
  if v.startswith('/optics-kits/'):return '/optics-kits/'+alias
  if v.startswith(('./topviews/','topviews/')):return ('./'if v.startswith('./')else'')+alias.removeprefix('static/')
  if v.startswith(('step/','drawings/','sha256/')):return alias.removeprefix('assets/')
  return ('./'if v.startswith('./')else'/'if v.startswith('/')else'')+alias
 return walk(record),refs
def plan_update(root,before,after,assets):
 """Prepare retention only after the caller has selected history=retain."""
 kinds=('components','kits','registeredBoards');old={k:{r['id']:r for r in before[k]}for k in kinds};new={k:{r['id']:r for r in after[k]}for k in kinds}
 changed={k:{i for i,r in old[k].items()if r.get('lifecycle',{}).get('state')!='historical'and new[k].get(i)!=r}for k in kinds}
 selected={k:set(v)for k,v in changed.items()}
 impacted=set(changed['components'])
 while True:
  more={i for i,r in old['components'].items()if r.get('lifecycle',{}).get('state')!='historical'and dependencies(r).intersection(impacted)}-impacted
  if not more:break
  impacted.update(more)
 selected['components'].update(impacted)
 for i,r in old['kits'].items():
  if r.get('lifecycle',{}).get('state')!='historical'and dependencies(r).intersection(impacted):selected['kits'].add(i)
 for i,r in old['registeredBoards'].items():
  if r.get('lifecycle',{}).get('state')!='historical'and dependencies(r).intersection(impacted):selected['registeredBoards'].add(i)
 for i in selected['kits']:selected['components'].update(dependencies(old['kits'][i]).intersection(old['components']))
 for i in selected['registeredBoards']:selected['components'].update(dependencies(old['registeredBoards'][i]).intersection(old['components']))
 while True:
  more={d for i in selected['components']for d in dependencies(old['components'][i])if d in old['components']}-selected['components']
  if not more:break
  selected['components'].update(more)
 if not any(selected.values()):return None
 index=read_index(root);existing={e['recordId']:e for e in index['entries']};idmap={};identities={}
 for i in selected['components']:identities[('components',i)]=identity(old['components'][i],old['components']);idmap[i]=i if old['components'][i].get('lifecycle',{}).get('state')=='historical'else history_id(i,identities[('components',i)])
 for kind in ('kits','registeredBoards'):
  for i in selected[kind]:
   ident=identity(old[kind][i],old['components']);identities[(kind,i)]=ident;idmap[i]=history_id(i,ident)
 token='retained-'+digest(sorted(identities.values()))[:20];package='library/history/'+token+'/package.json';records=[];entries=[];resolutions=[]
 for kind in kinds:
  for i in sorted(selected[kind]):
   original=old[kind][i];rid=idmap[i];version=before['version'];versions={version}
   for d in index.get('definitions',[]):
    if d['kind']==kind and d['originalId']==i and d['identitySha256']==identities[(kind,i)]:versions.update(d['catalogVersions'])
   for v in sorted(versions):resolutions.append({'catalogVersion':v,'kind':kind,'originalId':i,'recordId':rid,'revision':original.get('revision')})
   if rid in existing:continue
   row,refs=freeze_resources(original,assets);row['id']=rid
   def rebind(v):
    if isinstance(v,dict):
     for k,x in v.items():
      if k.lower().endswith('componentid')and isinstance(x,str):v[k]=idmap.get(x,x)
      elif k.lower().endswith('componentids')and isinstance(x,list):v[k]=[idmap.get(i,i)if isinstance(i,str)else i for i in x]
      else:rebind(x)
    elif isinstance(v,list):
     for x in v:rebind(x)
   rebind(row)
   row['lifecycle']={'state':'historical','canCreate':False,'historyId':token,'originalId':i,'revision':original.get('revision'),'sourceRecordSha256':digest(original)}
   records.append((kind,row))
   entries.append({'historyId':token,'kind':kind,'originalId':i,'recordId':rid,'revision':original.get('revision'),'sourceRecordSha256':digest(original),'sourceRecordPath':str(Path(package).parent/'source-records'/kind/(i+'.json')),'recordSha256':digest(row),'identitySha256':identities[(kind,i)],'packagePath':package,'catalogVersions':sorted(versions),'assetReferences':refs,'dependencyComponentIds':sorted(dependencies(row)),'retentionReason':'Explicit history=retain for this replacement; dependency closure frozen.','replacementId':i if i in new[kind]else None})
 posts={r['componentId']:r for r in before.get('universalPostSeries',{}).get('posts',[])}
 for e in entries:
  if e['kind']=='components'and e['originalId']in posts:e['catalogMetadata']={'universalPost':{**posts[e['originalId']],'componentId':e['recordId'],'seriesId':posts[e['originalId']].get('seriesId','post')[:35]+'-h-'+e['identitySha256'][:12]}}
 return {'packagePath':package,'packageId':token,'records':records,'entries':entries,'resolutions':resolutions,'sources':{kind:{i:old[kind][i]for i in selected[kind]}for kind in kinds}}
def install(root,plan,registry):
 if not plan:return []
 root=Path(root);created=[];index=read_index(root)
 resolved={(x['catalogVersion'],x['kind'],x['originalId']):x['recordId']for x in index['resolutions']}
 for r in plan['resolutions']:
  k=(r['catalogVersion'],r['kind'],r['originalId'])
  if k in resolved and resolved[k]!=r['recordId']:raise ValueError('Conflicting history version mapping: '+str(k))
 verified=verify_assets(root,[ref for e in plan['entries']for ref in e['assetReferences']])
 if plan['records']:
  p=root/plan['packagePath'];assert not p.exists(),p;p.parent.mkdir(parents=True);created.append(p.parent)
  m={'format':'hksop-package-v1','packageId':plan['packageId'],'displayName':'历史版本 · '+plan['packageId'],'revision':'frozen','records':[],'origin':'explicit history=retain','assets':[],'componentDependencies':sorted({d for e in plan['entries']for d in e['dependencyComponentIds']})}
  for kind,row in plan['records']:
   rel='records/'+row['id']+'.json';q=p.parent/rel;q.parent.mkdir(exist_ok=True);q.write_bytes(encoded(row));m['records'].append({'kind':kind,'path':rel})
   if row['id']not in registry['order'][kind]:registry['order'][kind].append(row['id'])
  p.write_bytes(encoded(m));registry['packages'].append(plan['packagePath'])
  for entry in plan['entries']:
   q=root/entry['sourceRecordPath'];q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(encoded(plan['sources'][entry['kind']][entry['originalId']]))
 for entry in plan['entries']:entry['assetVerification']={ref['stored']:verified[ref['stored']]for ref in entry['assetReferences']}
 index['entries'].extend(plan['entries'])
 seen={(x['catalogVersion'],x['kind'],x['originalId'],x['recordId'])for x in index['resolutions']}
 for row in plan['resolutions']:
  identity=(row['catalogVersion'],row['kind'],row['originalId'],row['recordId'])
  if identity not in seen:index['resolutions'].append(row);seen.add(identity)
 p=root/'library/history/index.json';p.parent.mkdir(exist_ok=True);p.write_bytes(encoded(index));return created
