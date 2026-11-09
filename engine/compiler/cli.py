"""HKSOP package compiler and isolated runtime entry points (Python stdlib)."""
from pathlib import Path
import argparse,copy,gzip,hashlib,html,json,os,re,shutil,stat,subprocess,sys,time,zipfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

ROOT=Path(__file__).resolve().parents[2]
KINDS=('components','kits','registeredBoards')
PACKAGE_OWNERS={}
PACKAGE_INFO=[]
def read(p):
 p=Path(p);data=p.read_bytes()
 return json.loads(gzip.decompress(data) if p.suffix=='.gz' else data)
def encoded(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
def sha(data):return hashlib.sha256(data).hexdigest()
def write(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(encoded(v))
@lru_cache(maxsize=10000)
def resolved(root):return Path(root).resolve()
@lru_cache(maxsize=20000)
def contained(root,rel):
 root=resolved(root);p=(root/rel).resolve()
 if not p.is_relative_to(root):raise ValueError('Path escapes its root: '+str(rel))
 return p
def identity(s):
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}',s):raise ValueError('Invalid stable ID: '+str(s))
 return s
def environment_value(name,fallback):
 p=ROOT/'config/local-environment.json'
 configured=read(p).get(name) if p.exists() else None
 return configured if configured and Path(configured).is_file() else fallback
def internal(base,rel):
 # Compiler-owned files: packages are copied as regular files by the intake path.
 # Untrusted incoming packages continue to use contained(), including symlink resolution.
 p=Path(rel)
 if p.is_absolute() or '\\' in str(rel) or any(x in ('','.','..') for x in str(rel).split('/')):raise ValueError('Invalid internal reference: '+str(rel))
 return Path(base)/p
def expand(package,trusted=False):
 p=Path(package);m=read(p)
 if m.get('format')!='hksop-package-v1':raise ValueError('Unsupported package format')
 identity(m['packageId']);out=[];seen=set()
 if not isinstance(m.get('records'),list) or not m['records']:raise ValueError('A package needs records')
 for ref in m['records']:
  if ref['kind'] not in KINDS:raise ValueError('Unknown entity kind')
  join=internal if trusted else contained
  common=read(join(p.parent,ref['common'])) if ref.get('common') else {}
  row={**common,**read(join(p.parent,ref['path']))}
  identity(row['id'])
  pair=(ref['kind'],row['id'])
  if pair in seen:raise ValueError('Duplicate record inside package: '+row['id'])
  seen.add(pair);out.append((ref['kind'],row))
 return m,out
def source_catalog():
 global PACKAGE_OWNERS,PACKAGE_INFO
 registry=read(ROOT/'library/registry.json');result=read(ROOT/'library/catalog-meta.json');tables={k:{} for k in KINDS}
 with ThreadPoolExecutor(max_workers=12) as pool:packages=list(pool.map(lambda rel:expand(internal(ROOT,rel),trusted=True),registry['packages']))
 owners={};info=[]
 for rel,(manifest,records) in zip(registry['packages'],packages):
  if manifest['packageId'] in owners:raise ValueError('Duplicate package ID: '+manifest['packageId'])
  owners[manifest['packageId']]=rel
  info.append({'packageId':manifest['packageId'],'name':manifest.get('displayName',manifest['packageId']),'manifest':rel,'records':[{'kind':k,'id':r['id'],'name':r.get('name')} for k,r in records],'declaredAssets':len(manifest.get('assets',[]))})
  for kind,row in records:
   if row['id'] in tables[kind]:raise ValueError('Duplicate '+kind+' ID: '+row['id'])
   tables[kind][row['id']]=row
 for kind in KINDS:
  order=registry['order'][kind]
  if set(order)!=set(tables[kind]):raise ValueError('Registry order differs from package records: '+kind)
  result[kind]=[tables[kind][i] for i in order]
 validate(result)
 PACKAGE_OWNERS=owners
 PACKAGE_INFO=info
 return result
def write_package_index():
 path=ROOT/'library/package-index.json';previous={x['manifest']:x for x in read(path)} if path.exists() else {}
 rows=[{**previous.get(x['manifest'],{}),**x} for x in PACKAGE_INFO]
 write(path,rows)
 page=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>HKSOP 元件目录</title><style>body{font:15px system-ui;max-width:1200px;margin:40px auto}td{padding:9px;border-bottom:1px solid #ddd}input{padding:10px;width:70%}</style><h1>HKSOP 元件目录</h1><p>由当前元件包编译生成；元件与资源定义见各包。</p><input id="search" placeholder="搜索名称、型号或 ID"><table>']
 for row in rows:
  href=row['manifest'].removeprefix('library/')
  page.append('<tr><td><a href="'+html.escape(href,quote=True)+'">'+html.escape(row['name'])+'</a><br><small>'+html.escape(row['packageId'])+'</small></td><td>'+html.escape(', '.join(x['id'] for x in row['records']))+'</td></tr>')
 page.append('</table><script>document.querySelector("#search").addEventListener("input",e=>{const q=e.target.value.toLowerCase();document.querySelectorAll("tr").forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q))})</script></html>')
 (ROOT/'library/index.html').write_text('\n'.join(page))
def validate(c):
 tables={}
 for k in KINDS:
  rows=c.get(k,[]);ids=[r['id'] for r in rows]
  if len(ids)!=len(set(ids)):raise ValueError('Duplicate IDs in '+k)
  tables[k]=set(ids)
 for kit in c['kits']:
  for r in kit.get('components',[]):
   if r['componentId'] not in tables['components']:raise ValueError('Missing component '+r['componentId']+' for '+kit['id'])
   if type(r.get('quantity')) is not int or r['quantity']<=0:raise ValueError('Invalid BOM quantity')
 return {k:len(v) for k,v in tables.items()}
def validate_legacy(c):
 mapping=read(ROOT/'engine/runtime-map.json')['web']
 directories={str((ROOT/i['source']).parent) for rel,i in mapping.items() if rel.endswith('.py') and '/' not in rel}
 sys.path[:0]=sorted(directories)
 from bom import validate_catalog
 validate_catalog(c)
 return True
def transform(value,mapping):
 if isinstance(value,dict):return {k:transform(v,mapping) for k,v in value.items()}
 if isinstance(value,list):return [transform(v,mapping) for v in value]
 if isinstance(value,str):return mapping.get(value,value)
 return value
def snapshot_catalog(snapshot):
 identity(snapshot)
 if snapshot!='web-current':raise ValueError('Only the current library is retained. Historical project JSON must be checked against web-current.')
 return source_catalog()

def remove_tree(path):
 """Do not follow links, including SMB links misreported by DirEntry.is_symlink()."""
 path=Path(path)
 try:mode=path.lstat().st_mode
 except FileNotFoundError:return
 if stat.S_ISDIR(mode):
  for entry in os.scandir(path):remove_tree(Path(entry.path))
  path.rmdir()
 else:path.unlink()

def value_strings(value):
 if isinstance(value,dict):
  for v in value.values():yield from value_strings(v)
 elif isinstance(value,list):
  for v in value:yield from value_strings(v)
 elif isinstance(value,str):yield value

def resource_key(value):
 value=value.removeprefix('/optics-kits/').lstrip('/')
 if value.startswith('library/'):value=value[len('library/'):]
 if value.startswith(('step/','drawings/','templates/','sha256/')):value='assets/'+value
 if value.startswith('topviews/'):value='static/'+value
 return value

def current_assets(catalog,assets):
 values=set(value_strings(catalog));keys={resource_key(v) for v in values}
 for v in values:
  if v in assets['replacements']:keys.add(resource_key(assets['replacements'][v]))
 for rel in read(ROOT/'library/registry.json')['packages']:
  keys.update(a['target'] for a in read(ROOT/rel).get('assets',[]))
 links={k:v for k,v in assets['links'].items() if resource_key(k) in keys or resource_key(v) in keys}
 kept=set(links.values())
 keptkeys={resource_key(x) for x in kept}
 replacements={k:v for k,v in assets['replacements'].items() if resource_key(v) in links or resource_key(v) in keptkeys}
 return {**assets,'links':links,'replacements':replacements,'resources':[r for r in assets.get('resources',[]) if r['stored'] in kept]}

def refresh_package_resources(assets,packages=None):
 provenance={}
 for row in assets.get('resources',[]):provenance.setdefault(row['stored'],[]).append(row)
 def one(rel):
  p=ROOT/rel;m,records=expand(p,trusted=True);values=set(value_strings([r for _,r in records]));keys={resource_key(x) for x in values}
  keys.update(resource_key(assets['replacements'][x]) for x in values if x in assets['replacements'])
  keys.update(a['target'] for a in m.get('assets',[]))
  stored=sorted({v for k,v in assets['links'].items() if resource_key(k) in keys or resource_key(v) in keys})
  for folder in ('cad','drawings','rendering','evidence'):
   # Uploaded assets may legitimately use these folders: remove only generated links.
   d=p.parent/folder
   if d.is_dir():
    for f in d.iterdir():
     if stat.S_ISLNK(f.lstat().st_mode):f.unlink()
  files=[]
  for ref in stored:
   src=ROOT/ref;ext=src.suffix
   folder='cad' if ext in ('.step','.stp','.stl','.glb') else 'rendering' if ext in ('.svg','.png','.jpg') else 'drawings' if ext in ('.pdf','.dxf') else 'evidence'
   local=folder+'/'+src.name;out=p.parent/local;out.parent.mkdir(parents=True,exist_ok=True)
   if not out.exists():out.symlink_to(os.path.relpath(src,out.parent))
   files.append({'path':local,'stored':ref,'sha256':src.stem,'originalReferences':sorted({x.get('logical',x.get('source','')) for x in provenance.get(ref,[])}),'sources':sorted({x.get('source','') for x in provenance.get(ref,[])})})
  write(p.parent/'resource-map.json',{'format':'hksop-package-resources-v1','packageId':m['packageId'],'files':files,'dependencies':m.get('componentDependencies',[])})
  return m['packageId'],len(files)
 selected=packages if packages is not None else read(ROOT/'library/registry.json')['packages']
 with ThreadPoolExecutor(max_workers=12) as pool:counts=dict(pool.map(one,selected))
 index=ROOT/'library/package-index.json'
 if index.exists():write(index,[{**row,'resourceCount':counts.get(row['packageId'],row.get('resourceCount',0))} for row in read(index)])

def collect_unused_assets(assets):
 kept=set(assets['links'].values())
 root=ROOT/'library/assets/sha256'
 def clean_bucket(bucket):
  deleted=0
  if not bucket.is_dir():return 0
  for p in bucket.iterdir():
   if p.relative_to(ROOT).as_posix() not in kept:deleted+=p.stat().st_size;p.unlink()
  return deleted
 if root.exists():
  with ThreadPoolExecutor(max_workers=12) as pool:return sum(pool.map(clean_bucket,list(root.iterdir())))
 return 0
def compile_catalog(snapshot='web-current'):
 c=snapshot_catalog(snapshot);asset=read(ROOT/'library/snapshots'/snapshot/'assets.json')
 mapping=dict(asset['replacements'])
 # Export helpers reject child symlinks. Point asset paths directly at CAS files.
 for old,new in list(mapping.items()):
  key=new
  lead=''
  if key.startswith('/optics-kits/'):lead='/optics-kits/';key=key[len(lead):]
  elif key.startswith('/'):lead='/';key=key[1:]
  if key.startswith('assets/') and key in asset['links']:
   mapping[old]=lead+'assets/'+asset['links'][key].removeprefix('library/assets/')
  elif 'assets/'+key in asset['links']:
   mapping[old]=asset['links']['assets/'+key].removeprefix('library/assets/')
 c=transform(c,mapping);counts=validate(c)
 if snapshot=='web-current':validate_legacy(c)
 dest=ROOT/'library/_build'/snapshot;dest.mkdir(parents=True,exist_ok=True)
 write(dest/'catalog.json',c)
 if snapshot=='web-current':write(ROOT/'library/catalog.json',c)
 index=[]
 for kind in KINDS:
  for row in c.get(kind,[]):index.append({'id':row['id'],'kind':kind,'name':row.get('name'),'revision':row.get('revision'),'category':row.get('category')})
 write(dest/'entity-index.json',index)
 if snapshot=='web-current':
  write(ROOT/'library/entity-index.json',index);write_package_index()
 # Internal-only links provide the old engines with ASCII resource paths.
 def prepare_asset(pair):
  rel,stored=pair
  if not re.fullmatch(r'library/assets/sha256/[a-f0-9]{2}/[a-f0-9]{64}\.[a-z0-9]{1,12}',stored):raise ValueError('Invalid content-store reference')
  target=internal(ROOT,stored)
  if not target.is_file():raise ValueError('Missing stored asset: '+stored)
  if rel.startswith('assets/'):return
  p=dest/rel;p.parent.mkdir(parents=True,exist_ok=True)
  if not p.exists():shutil.copyfile(target,p)
 with ThreadPoolExecutor(max_workers=12) as pool:list(pool.map(prepare_asset,asset['links'].items()))
 write(dest/'build-receipt.json',{'format':'hksop-catalog-build-v1','snapshot':snapshot,'counts':counts,'catalogSha256':sha((dest/'catalog.json').read_bytes()),'sourceStateSha256':source_fingerprint() if snapshot=='web-current' else asset['sourceCatalogSha256'],'resources':len(asset['links']),'generatedAt':time.time()})
 return dest
def source_fingerprint():
 h=hashlib.sha256()
 files=[ROOT/'library/registry.json',ROOT/'library/catalog-meta.json']
 def package_files(rel):
  p=internal(ROOT,rel);result=[p]
  for record in read(p)['records']:
   result.append(internal(p.parent,record['path']))
   if record.get('common'):result.append(internal(p.parent,record['common']))
  return result
 with ThreadPoolExecutor(max_workers=12) as pool:
  for batch in pool.map(package_files,read(ROOT/'library/registry.json')['packages']):files.extend(batch)
  ordered=sorted(set(files));contents=list(pool.map(lambda p:p.read_bytes(),ordered))
 for p,data in zip(ordered,contents):h.update(p.relative_to(ROOT).as_posix().encode());h.update(data)
 return h.hexdigest()
def link_dir(p,target):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists() or p.is_symlink():
  if p.resolve()!=target.resolve():raise ValueError('Existing directory differs: '+str(p))
 else:p.symlink_to(os.path.relpath(target,p.parent),target_is_directory=True)
def copy_static_tree(source,dest,relative_files):
 dest.mkdir(parents=True,exist_ok=True)
 files=[source/rel for rel in relative_files]
 def one(p):
  out=dest/p.relative_to(source);out.parent.mkdir(parents=True,exist_ok=True)
  # These resources are named by content hash and are immutable.
  if not out.exists():shutil.copyfile(p,out)
 with ThreadPoolExecutor(max_workers=12) as pool:list(pool.map(one,files))
def build_runtime(profile='web',snapshot='web-current',_built=None):
 built=_built or compile_catalog(snapshot);mapping=read(ROOT/'engine/runtime-map.json')[profile]
 static_files=[rel.removeprefix('static/topviews/') for rel in read(ROOT/'library/snapshots'/snapshot/'assets.json')['links'] if rel.startswith('static/topviews/')]
 dest=ROOT/'runtime/releases'/(profile+'-'+identity(snapshot));dest.mkdir(parents=True,exist_ok=True)
 def copy_runtime(pair):
  rel,item=pair
  p=internal(ROOT,item['source']);out=dest/rel
  if not rel.isascii():raise ValueError('Non-ASCII executable path: '+rel)
  out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,out)
 with ThreadPoolExecutor(max_workers=12) as pool:list(pool.map(copy_runtime,mapping.items()))
 shutil.copyfile(built/'catalog.json',dest/'catalog.json')
 link_dir(dest/'assets',ROOT/'library/assets')
 (built/'static/topviews').mkdir(parents=True,exist_ok=True)
 copy_static_tree(built/'static/topviews',dest/'static/topviews',static_files)
 if profile=='editor':
  web=ROOT/'runtime/releases/web-web-current'
  if not (web/'hksop-runtime.json').exists():build_runtime('web','web-current',built if snapshot=='web-current' else None)
  local=dest/'data/libraries'/snapshot;local.mkdir(parents=True,exist_ok=True)
  shutil.copyfile(built/'catalog.json',local/'catalog.json')
  link_dir(local/'assets',ROOT/'library/assets')
  copy_static_tree(built/'static/topviews',local/'topviews',static_files)
  write(local/'receipt.json',{'release':snapshot,'snapshot':snapshot,'version':read(built/'catalog.json')['version'],'sourceVerified':True,'nasVerified':True,'verifiedAt':time.time(),'source':'HKSOP current package catalog'})
  write(dest/'data/current.json',{'release':snapshot})
  write(dest/'config.json',{'port':18943,'librarySource':'web-runtime','webLibraryRoot':str(web),'autoSyncSeconds':60,'sourceAuditSeconds':3600,'syncTimeoutSeconds':90,'hksopFrozen':True})
  # Current board definitions are compiled into the unified catalog.
  (dest/'local-boards.json').unlink(missing_ok=True)
  (dest/'PROJECT_LOG.md').touch(exist_ok=True)
 write(dest/'hksop-runtime.json',{'profile':profile,'snapshot':snapshot,'sourceMap':'engine/runtime-map.json','generatedAt':time.time(),'productionServiceChanged':False})
 return dest
def stage_package(path,collection='custom'):
 p=Path(path).resolve();p=p/'package.json' if p.is_dir() else p
 m,records=expand(p);catalog=source_catalog();registry=read(ROOT/'library/registry.json')
 existing=PACKAGE_OWNERS.get(m['packageId'])
 tables={k:{r['id']:r for r in catalog[k]} for k in KINDS}
 oldids={k:set() for k in KINDS}
 if existing:
  _,old=expand(ROOT/existing)
  for k,r in old:oldids[k].add(r['id']);tables[k].pop(r['id'])
 for k,row in records:
  if row['id'] in tables[k]:raise ValueError('An unrelated package owns ID: '+row['id'])
  tables[k][row['id']]=row
 for k in KINDS:catalog[k]=list(tables[k].values())
 validate(catalog)
 validate_legacy(catalog)
 paths={'package.json'}
 for ref in m['records']:
  paths.add(ref['path'])
  if ref.get('common'):paths.add(ref['common'])
 known_assets=read(ROOT/'library/snapshots/web-current/assets.json')
 def resource_key(value):
  value=value.removeprefix('/optics-kits/').lstrip('/')
  if value.startswith(('step/','drawings/','templates/','sha256/')):return 'assets/'+value
  if value.startswith('topviews/'):return 'static/'+value
  return value
 available={resource_key(k) for k in known_assets['replacements']}|set(known_assets['links'])
 available.update(row['stored'].removeprefix('library/') for row in known_assets.get('resources',[]))
 available.update(stored.removeprefix('library/') for stored in known_assets['links'].values())
 declared_targets={}
 for asset in m.get('assets',[]):
  source=contained(p.parent,asset['path'])
  if sha(source.read_bytes())!=asset['sha256']:raise ValueError('Asset checksum mismatch: '+asset['path'])
  target=asset['target']
  if not re.fullmatch(r'(assets/(step|drawings|templates)|static/topviews)/[A-Za-z0-9_.-]+',target):raise ValueError('Asset target must use a supported flat ASCII path')
  if source.suffix.lower()!=Path(target).suffix.lower():raise ValueError('Source and target resource extensions differ')
  if target in declared_targets and declared_targets[target]!=asset['sha256']:raise ValueError('Two different resources declare the same target')
  declared_targets[target]=asset['sha256']
  previous=known_assets['links'].get(known_assets['replacements'].get(target,target))
  if previous and Path(previous).stem!=asset['sha256']:raise ValueError('Asset target already belongs to different content; use a new filename')
  available.add(target)
  paths.add(asset['path'])
 def required_resources(value,key=''):
  if isinstance(value,dict):
   for k,v in value.items():
    if k in ('history','retiredComponents') or 'evidence' in k.lower() or k.lower().startswith('previous'):continue
    yield from required_resources(v,k)
  elif isinstance(value,list):
   for v in value:yield from required_resources(v,key)
  elif isinstance(value,str) and value and (key in ('stepPath','drawingPath','dxfPath','dxfPdfPath','topViewPath','sideViewPath') or value.startswith(('topviews/','static/topviews/'))):yield value
 for _,record in records:
  for value in required_resources(record):
   if resource_key(value) not in available:raise ValueError('Resource is neither registered nor declared in this package: '+value)
 for rel in paths:
  if not rel.isascii():raise ValueError('Package file paths must be ASCII; display names may use Chinese')
 fingerprint=source_fingerprint();asset_fingerprint=sha(encoded(known_assets));sid='stage-'+sha(encoded(m)+fingerprint.encode()+str(time.time_ns()).encode())[:16]
 dest=ROOT/'runtime/staging'/sid
 if dest.exists():raise ValueError('Stage already exists: '+str(dest))
 for rel in sorted(paths):
  source=contained(p.parent,rel);out=contained(dest/'package',rel);out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,out)
 target=existing or 'library/'+collection+'/'+m['packageId']+'/package.json'
 receipt={'format':'hksop-stage-v1','baseFingerprint':fingerprint,'assetFingerprint':asset_fingerprint,'packageId':m['packageId'],'target':target,'oldIds':{k:sorted(v) for k,v in oldids.items()},'files':{rel:sha((dest/'package'/rel).read_bytes()) for rel in paths},'checks':{'recordStructure':True,'bomReferences':True,'declaredAssetHashes':True,'resourceReferences':True},'physicalAcceptance':'not-performed-by-structural-stage'}
 write(dest/'stage.json',receipt);return dest
def adopt_stage(path):
 lock=ROOT/'runtime/locks/library.lock';lock.parent.mkdir(parents=True,exist_ok=True)
 try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
 except FileExistsError:raise ValueError('Another library write is active; inspect runtime/locks/library.lock')
 try:
  os.write(fd,str(os.getpid()).encode());os.close(fd)
  return _adopt_stage(path)
 finally:lock.unlink(missing_ok=True)
def _adopt_stage(path):
 dest=Path(path).resolve();receipt=read(dest/'stage.json')
 if receipt['baseFingerprint']!=source_fingerprint():raise ValueError('Library changed since staging; create a new stage')
 if receipt['assetFingerprint']!=sha(encoded(read(ROOT/'library/snapshots/web-current/assets.json'))):raise ValueError('Assets changed since staging; create a new stage')
 for rel,expected in receipt['files'].items():
  if sha(contained(dest/'package',rel).read_bytes())!=expected:raise ValueError('Staged file changed: '+rel)
 m,records=expand(dest/'package/package.json');target=contained(ROOT,receipt['target']).parent
 registry=read(ROOT/'library/registry.json')
 before_catalog=source_catalog()
 allowed_targets={PACKAGE_OWNERS[m['packageId']]} if m['packageId'] in PACKAGE_OWNERS else set()
 allowed_targets.update('library/'+section+'/'+m['packageId']+'/package.json' for section in ('custom','standard'))
 if receipt['target'] not in allowed_targets:raise ValueError('Stage target does not match package identity')
 if receipt['packageId']!=m['packageId']:raise ValueError('Stage identity changed')
 assets=read(ROOT/'library/snapshots/web-current/assets.json')
 before_assets=copy.deepcopy(assets)
 # Resolve every destination before changing definitions; a generated asset link
 # must not turn an upload into a write to the shared immutable content store.
 for rel in receipt['files']:contained(target,rel)
 transaction=ROOT/'runtime/transactions'/('adopt-'+str(time.time_ns()));transaction.mkdir(parents=True)
 backup=transaction/'previous-package';had_target=target.exists();created_assets=[];moved=False;installed=False
 metadata=['library/registry.json','library/catalog-meta.json','library/snapshots/web-current/assets.json','library/snapshots/web-current/catalog.json.gz','library/snapshots/index.json']
 previous={rel:(ROOT/rel).read_bytes() if (ROOT/rel).exists() else None for rel in metadata}
 write(transaction/'transaction.json',{'state':'in-progress','target':receipt['target'],'policy':'temporary rollback; delete after success'})
 for rel,data in previous.items():
  if data is not None:
   q=transaction/'metadata'/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(data)
 try:
  if had_target:os.replace(target,backup);moved=True
  target.mkdir(parents=True,exist_ok=True);installed=True
  for rel in receipt['files']:
   out=contained(target,rel);out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(dest/'package'/rel,out)
  if receipt['target'] not in registry['packages']:registry['packages'].append(receipt['target'])
  for k in KINDS:
   order=[i for i in registry['order'][k] if i not in receipt['oldIds'][k]]
   order.extend(row['id'] for kind,row in records if kind==k);registry['order'][k]=order
  for a in m.get('assets',[]):
   source=contained(target,a['path']);ext=source.suffix.lower();stored=ROOT/'library/assets/sha256'/a['sha256'][:2]/(a['sha256']+ext);stored.parent.mkdir(parents=True,exist_ok=True)
   if not stored.exists():shutil.copyfile(source,stored);created_assets.append(stored)
   if sha(stored.read_bytes())!=a['sha256']:raise ValueError('Stored asset mismatch')
   assets['links'][a['target']]=stored.relative_to(ROOT).as_posix()
   _,relative=a['target'].split('/',1);assets['replacements'][relative]=relative;assets['replacements'][a['target']]=a['target']
  meta=read(ROOT/'library/catalog-meta.json');meta['version']='hksop-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+sha(encoded(m))[:8];meta['updatedAt']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());registry['catalogVersion']=meta['version']
  write(ROOT/'library/catalog-meta.json',meta);write(ROOT/'library/registry.json',registry)
  after_catalog=source_catalog();after_bytes=encoded(after_catalog);assets=current_assets(after_catalog,assets);assets['sourceCatalogSha256']=sha(after_bytes)
  (ROOT/'library/snapshots/web-current/catalog.json.gz').write_bytes(gzip.compress(after_bytes,mtime=0));write(ROOT/'library/snapshots/web-current/assets.json',assets)
  current_row={'id':'web-current','role':'current-only','version':after_catalog['version'],'sha256':sha(after_bytes),'counts':validate(after_catalog),'assetCount':len(assets['links']),'missingCount':len(assets.get('missing',[]))}
  write(ROOT/'library/snapshots/index.json',{'format':'hksop-snapshot-index-v1','snapshots':[current_row]})
  remove_tree(ROOT/'library/_build/web-current')
  result=compile_catalog();refresh_package_resources(assets,[receipt['target']])
 except Exception:
  if installed:remove_tree(target)
  if moved:os.replace(backup,target)
  for rel,data in previous.items():
   p=ROOT/rel
   if data is None:p.unlink(missing_ok=True)
   else:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
  for p in created_assets:p.unlink(missing_ok=True)
  remove_tree(ROOT/'library/_build/web-current');compile_catalog()
  if had_target:refresh_package_resources(before_assets,[receipt['target']])
  remove_tree(transaction)
  raise
 # Commit succeeded: rollback copies and staged input must not become permanent versions.
 remove_tree(transaction)
 removed=collect_unused_assets(assets)
 for profile in ('web','editor'):
  runtime=ROOT/'runtime/releases'/(profile+'-web-current')
  if runtime.exists():
   remove_tree(runtime);build_runtime(profile,'web-current',result)
 write(ROOT/'runtime/last-adoption.json',{'adoptedAt':time.time(),'catalog':str(result),'target':receipt['target'],'releasedAssetBytes':removed,'historyRetained':False})
 remove_tree(dest)
 return result
def export_package(package,output):
 p=Path(package);p=p/'package.json' if p.is_dir() else p;m,records=expand(p)
 # Delivers the editable package and explicit direct resources. Dependency closure is recorded.
 paths={'package.json'}
 for r in m['records']:
  paths.add(r['path'])
  if r.get('common'):paths.add(r['common'])
 for a in m.get('assets',[]):paths.add(a['path'])
 output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as z:
  for rel in sorted(paths):z.write(contained(p.parent,rel),m['packageId']+'/'+rel)
 with zipfile.ZipFile(output) as z:
  if z.testzip() is not None:raise ValueError('ZIP verification failed')
 return output
def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
 q=sub.add_parser('catalog');q.add_argument('action',choices=['build','check','list']);q.add_argument('--snapshot',default='web-current')
 q=sub.add_parser('runtime');q.add_argument('action',choices=['build']);q.add_argument('--profile',choices=['web','editor'],default='web');q.add_argument('--snapshot',default='web-current')
 q=sub.add_parser('package');q.add_argument('action',choices=['check','stage','adopt','export']);q.add_argument('path');q.add_argument('--collection',choices=['custom','standard'],default='custom');q.add_argument('--output')
 q=sub.add_parser('trace');q.add_argument('scene');q.add_argument('--node');q.add_argument('--snapshot',default='web-current');q.add_argument('--profile',choices=['web','editor'],default='editor')
 q=sub.add_parser('serve');q.add_argument('--profile',choices=['web','editor'],default='editor');q.add_argument('--snapshot',default='web-current');q.add_argument('--port',type=int,default=18943)
 args=p.parse_args()
 if args.command=='catalog':
  c=snapshot_catalog(args.snapshot)
  if args.action=='build':result={'built':str(compile_catalog(args.snapshot)),'counts':validate(c)}
  elif args.action=='check':result={'valid':validate_legacy(c),'counts':validate(c),'sourceFingerprint':source_fingerprint()}
  else:result={k:[{'id':x['id'],'name':x.get('name'),'revision':x.get('revision')} for x in c[k]] for k in KINDS}
 elif args.command=='runtime':result={'runtime':str(build_runtime(args.profile,args.snapshot))}
 elif args.command=='package':
  if args.action=='check':m,records=expand(Path(args.path)/'package.json' if Path(args.path).is_dir() else args.path);result={'packageId':m['packageId'],'records':len(records),'recordStructure':'valid'}
  elif args.action=='stage':result={'stage':str(stage_package(args.path,args.collection))}
  elif args.action=='adopt':result={'built':str(adopt_stage(args.path))}
  else:
   if not args.output:raise ValueError('--output is required')
   result={'archive':str(export_package(args.path,args.output))}
 elif args.command=='trace':
  runtime=build_runtime(args.profile,args.snapshot);tool=runtime/'tools/trace-optical-scene.cjs'
  if not tool.exists():tool.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'engine/tools/web/trace-optical-scene.cjs',tool)
  return subprocess.call([args.node or environment_value('node','node'),str(tool),str(Path(args.scene).resolve())],cwd=runtime)
 else:
  runtime=build_runtime(args.profile,args.snapshot)
  cmd=[environment_value('runtimePython',sys.executable),'-B',str(runtime/('server.py' if args.profile=='editor' else 'app.py')),'--port',str(args.port)]
  if args.profile=='web':cmd+=['--shared-db',str(ROOT/'runtime/user-data/shared-kits.sqlite3')]
  env=dict(os.environ);cad=environment_value('cadPython',None)
  if cad:env['ZZLAB_CAD_PYTHON']=cad
  return subprocess.call(cmd,cwd=runtime,env=env)
 print(json.dumps(result,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':
 try:sys.exit(main())
 except Exception as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False),file=sys.stderr);sys.exit(2)
