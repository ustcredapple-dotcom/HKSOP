#!/usr/bin/env python3
# coding: utf-8
"""Additive fast-kit release. Default prepares a delta; --apply activates it.

Only the new records/assets and derived indexes are published. Existing binary
CAD, drawings and atlas are reused by APFS clone; NAS stores a verified delta
with an explicit dependency on its verified base. No router/auth/DB modifications.
"""
from pathlib import Path
import argparse, contextlib, datetime, io, json, os, shutil, subprocess, sys, time, urllib.request, zipfile
import library as lib
ROOT=Path(__file__).resolve().parents[1]
PYTHON=Path('/Users/Shared/ZZLAB/MacMainPreview/.venv/bin/python')
DEFAULT_RUNTIME=Path('/Users/Shared/ZZLAB/OpticsKits')
DEFAULT_NAS=Path('/Volumes/ZZLab_001/ZZLAB Web/Mac service/10_Optics_Kits')

def require(ok,message):
    if not ok:raise lib.LibraryError(message)

def run(args):return subprocess.run([str(x)for x in args],check=True,capture_output=True,text=True)

def create_delta(prepared,out,root,base,node):
    started=time.monotonic()
    require(not out.exists(),'Delta destination already exists')
    plan=lib.read_json(prepared/'stage/stage-plan.json');catalog=lib.load_source(prepared/'stage/library');raw=lib.json_bytes(catalog)
    require(lib.sha(raw)==plan['candidateCatalogSha256'] and raw==(prepared/'stage/catalog.json').read_bytes(),'Candidate changed since checking')
    require(plan['baseCatalogSha256']==lib.file_sha(root/'catalog.json')==lib.file_sha(base/'catalog.json'),'Source/active baseline changed; restage against current catalog')
    require(lib.source_state_sha(root/'library')==plan['baseSourceSha256'],'Source records/reviews changed; restage')
    before=lib.load_source(root/'library');expected={g:{r['id']:r for r in before[k]}for g,k in lib.GROUPS.items()}
    added=[]
    for g,key in lib.GROUPS.items():
        for row in catalog[key]:
            if row['id'] in expected[g]:require(row==expected[g][row['id']],'Fast release cannot replace old records')
            else:lib.validate_new_record(g,row);added.append((g,row))
        require(set(expected[g])<={r['id']for r in catalog[key]},'Fast release cannot remove records')
    require({g for g,r in added}<={'kits','components'} and any(g=='kits'for g,r in added),'No new kit')
    require(all(r.get('fastUpload',{}).get('schema')=='zzlab-fast-kit-upload-v1'for g,r in added if g=='kits'),'Non-fast kit in delta')
    for k,v in before.items():
        if k not in (*lib.GROUPS.values(),'version'):require(catalog[k]==v,'Fast release cannot change catalog capabilities')
    # The data-only path must not accidentally deploy unrelated source/engine edits.
    upgrades=lib.read_json(root/'tools/fast-kit-templates.json').get('runtimeUpgrades',{})
    runtime_updates=[]
    guards=list(base.glob('*.py'))+list((base/'static').glob('*'))
    for p in guards:
        if not p.is_file():continue
        rel=p.relative_to(base)
        if rel.as_posix()=='deploy_support.py':continue
        require((root/rel).is_file(),'Missing application source: '+str(rel))
        oldsha,newsha=lib.file_sha(p),lib.file_sha(root/rel)
        if oldsha!=newsha:
            upgrade=upgrades.get(rel.as_posix(),{})
            require(oldsha==upgrade.get('fromSha256') and newsha==upgrade.get('toSha256'),'Application code changed; ordinary release required: '+str(rel))
            runtime_updates.append(rel.as_posix())
    # Re-use standard stage validation; no CAD redesign or whole-atlas work.
    overrides={r['path']:prepared/'stage'/r['path'] for r in plan['assets']}
    for row in plan['assets']:require(row['mode']=='add' and lib.file_sha(overrides[row['path']])==row['sha256'],'Asset not additive or modified')
    lib.validate_structure(catalog)
    needed={x['componentId'] for g,k in added if g=='kits' for x in k['components']}
    small={'kits':[k for g,k in added if g=='kits'],'components':[r for r in catalog['components'] if r['id'] in needed], 'registeredBoards':[]}
    lib.asset_inventory(small,root,overrides)
    out.mkdir(parents=True);files=out/'files';files.mkdir();paths=[]
    def add(rel,data):
        lib.relative_path(rel);lib.atomic_write(files/rel,data);paths.append(rel)
    for row in plan['assets']:add(row['path'],overrides[row['path']].read_bytes())
    for rel in runtime_updates:add(rel,(root/rel).read_bytes())
    for g,r in added:add(f'library/records/{g}/{r["id"]}.json',lib.json_bytes(r))
    for n in ('manifest.json','catalog-meta.json'):add('library/'+n,(prepared/'stage/library'/n).read_bytes())
    add('catalog.json',raw)
    for p in (prepared/'stage/library/generated').glob('*.json'):add('library/generated/'+p.name,p.read_bytes())
    review=prepared/'stage/library/reviews'/plan['packageId']
    for p in review.rglob('*'):
        if p.is_file():add('library/reviews/'+plan['packageId']+'/'+p.relative_to(review).as_posix(),p.read_bytes())
    run([PYTHON,root/'tools/build-interaction-index.py','--root',root,'--catalog',files/'catalog.json','--output',files/'library/generated/interaction-index.json','--ports-output',files/'library/generated/port-index.json','--node',node])
    paths+=['library/generated/interaction-index.json','library/generated/port-index.json']
    # Bind the unchanged atlas to an explicitly reduced scope, never claim new pages.
    old=lib.read_json(base/'assets/drawings/atlas/current.json');require(old['catalogSha256']==plan['baseCatalogSha256'],'Atlas coverage baseline is stale')
    atlas={**old,'catalogSha256':plan['candidateCatalogSha256'],'coverageCatalogSha256':old.get('coverageCatalogSha256',old['catalogSha256']),
           'coverageMode':'standard-library-excluding-fast-uploads','excludedKitIds':sorted(set(old.get('excludedKitIds',[]))|{r['id']for g,r in added if g=='kits'}),'excludedComponentIds':sorted(set(old.get('excludedComponentIds',[]))|{r['id']for g,r in added if g=='components'}),'pdfRegenerated':False}
    add('assets/drawings/atlas/current.json',lib.json_bytes(atlas))
    html=(base/'static/index.html').read_bytes().replace('完整机加工图册 · B6 R1'.encode(),'标准库图册（不含极速上传）'.encode())
    add('static/index.html',html)
    entries=[]
    for rel in sorted(set(paths)):
        previous=base/rel;source=root/rel
        oldsha=lib.file_sha(previous)if previous.is_file()else None
        sourcesha=lib.file_sha(source)if source.is_file()else None
        require(sourcesha==oldsha or rel in runtime_updates,'Editable source differs from active release: '+rel)
        entries.append({'path':rel,'bytes':(files/rel).stat().st_size,'sha256':lib.file_sha(files/rel),'previousSha256':oldsha,'sourcePreviousSha256':sourcesha})
    from bom import load_catalog
    runtime_digest=lib.sha(lib.json_bytes(load_catalog(files/'catalog.json')))
    receipt={'prepareSeconds':round(time.monotonic()-started,3),'runtimeCatalogSha256':runtime_digest,'schema':'zzlab-fast-library-delta-v1','createdAt':datetime.datetime.now().astimezone().isoformat(),'packageId':plan['packageId'],'baseRelease':base.name,'baseCatalogSha256':plan['baseCatalogSha256'],'candidateCatalogSha256':plan['candidateCatalogSha256'],'baseSourceSha256':plan['baseSourceSha256'],'kitIds':[r['id']for g,r in added if g=='kits'],'files':entries,'atlas':atlas,'onshape':'excluded','physicalCertification':False}
    lib.atomic_write(out/'delta.json',lib.json_bytes(receipt));return receipt

def verify_delta(delta,target,previous=True,source=False):
    manifest=lib.read_json(delta/'delta.json')
    for row in manifest['files']:
        rel=lib.relative_path(row['path']);p=delta/'files'/rel
        require(p.is_file() and not p.is_symlink() and lib.file_sha(p)==row['sha256'],'Delta file changed: '+rel)
        if previous:
            old=target/rel;require((lib.file_sha(old)if old.is_file()else None)==row['sourcePreviousSha256' if source else 'previousSha256'],'Base file changed: '+rel)
    return manifest

def clone_candidate(delta,base,destination):
    verify_delta(delta,base);require(not destination.exists(),'Release destination exists')
    # -c explicitly requests copy-on-write on macOS; fail instead of full-copy fallback.
    run(['/bin/cp','-cR',base,destination])
    for row in lib.read_json(delta/'delta.json')['files']:
        lib.atomic_write(destination/row['path'],(delta/'files'/row['path']).read_bytes())
    require(lib.json_bytes(lib.load_source(destination/'library'))==(destination/'catalog.json').read_bytes(),'Cloned source/catalog mismatch')
    return destination

def request(base,path,payload=None,headers=None):
    data=lib.json_bytes(payload)if payload is not None else None
    h={**(headers or {})};
    if data is not None:h['Content-Type']='application/json'
    # Local endpoint only; no auth headers may follow redirects.
    from urllib.request import HTTPRedirectHandler,ProxyHandler,build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args):return None
    with build_opener(ProxyHandler({}),NoRedirect()).open(urllib.request.Request(base+path,data=data,headers=h),timeout=60)as r:return r.read()

def smoke(base,manifest,headers=None):
    catalog=json.loads(request(base,'/api/catalog',headers=headers));require(lib.sha(lib.json_bytes(catalog))==manifest['runtimeCatalogSha256'],'Live catalog mismatch')
    rows=[]
    for kid in manifest['kitIds']:
        kit=next(k for k in catalog['kits']if k['id']==kid);svg=request(base,'/'+kit['layout']['topViewPath'],headers=headers)
        require(lib.sha(svg)==kit['layout']['geometryEvidence']['imageSha256'],'Live image mismatch')
        payload={'catalogVersion':catalog['version'],'items':[{'kitId':kid,'quantity':1}],'extras':[]}
        preview=json.loads(request(base,'/api/preview',payload,headers));require(preview.get('totals'),'Empty BOM preview')
        data=request(base,'/api/export?format=bundle',payload,headers)
        with zipfile.ZipFile(io.BytesIO(data))as z:
            require(z.testzip()is None and any(n.lower().endswith('.step')for n in z.namelist()),'Exported ZIP is unusable')
            require(any('激光' in n for n in z.namelist()),'Missing marking files in download')
            step_hashes={lib.sha(z.read(n))for n in z.namelist()if n.lower().endswith(('.step','.stp'))}
            require(kit['assemblyReference']['sourceStepSha256'] in step_hashes,'Missing exact full assembly in download')
            for row in kit['components']:
                component=next(c for c in catalog['components']if c['id']==row['componentId'])
                if component['id'].startswith('custom-rotpost-'):require(component['sourceStepSha256'] in step_hashes,'Missing exact new post in download')
        layout={'catalogVersion':catalog['version'],'layout':{'board':{'widthMm':500,'heightMm':500,'pitchMm':12.5,'edgeOffsetMm':12.5,'thicknessMm':12.7,'holeType':'M6_through'},'instances':[{'id':'fast-probe','kitId':kid,'xMm':250,'yMm':250,'rotationDeg':0}]},'extras':[]}
        result=json.loads(request(base,'/api/preview',layout,headers));require(result.get('layoutValidation',{}).get('valid'),'New kit cannot be placed')
        rows.append({'kitId':kid,'imageSha256':lib.sha(svg),'downloadBytes':len(data),'downloadSha256':lib.sha(data),'placementPassed':True})
    return {'passed':True,'kits':rows}

def write_source_delta(delta,root,backup,written):
    manifest=verify_delta(delta,root,source=True)
    for row in manifest['files']:
        p=root/row['path'];b=backup/'source-before'/row['path']
        if p.exists():b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,b)
        lib.atomic_write(p,(delta/'files'/row['path']).read_bytes());written.append(row)

def restore_source_delta(root,backup,written):
    for row in reversed(written):
        p=root/row['path'];require(lib.file_sha(p)==row['sha256'],'Source changed concurrently; preserve it for manual recovery')
        b=backup/'source-before'/row['path']
        if b.exists():lib.atomic_write(p,b.read_bytes())
        else:p.unlink()

def apply(delta,root,runtime,nas,local_editor):
    """Activate a checked delta with source rollback and the existing service identity."""
    import deploy_support as deploy
    require(runtime==DEFAULT_RUNTIME and nas==DEFAULT_NAS,'Live activation only supports the configured ZZLab service')
    require(Path('/Volumes/ZZLab_001').is_mount(),'NAS is not mounted')
    base=(runtime/'current').resolve();m=verify_delta(delta,base)
    require(base.name==m['baseRelease'] and lib.source_state_sha(root/'library')==m['baseSourceSha256'],'Live/source baseline changed')
    verify_delta(delta,root,source=True);stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-fast'
    release=runtime/'releases'/stamp;backup=runtime/'backups'/stamp;backup.mkdir(parents=True)
    clone_candidate(delta,base,release)
    # Save a recoverable delta before switching live. The full base is protected.
    marker=(nas/'CURRENT_RELEASE.txt').read_text().strip();pointer=nas/'CURRENT_FAST_RELEASE.json';oldpointer=pointer.read_bytes()if pointer.exists()else None
    chain=[];full_base=base.name
    if (base/'fast-release.json').exists():
        prior=lib.read_json(base/'fast-release.json');full_base=prior['fullBaseRelease'];chain=prior['deltaChain']
    require(marker==full_base and lib.file_sha(nas/'releases'/full_base/'catalog.json')==lib.read_json(nas/'releases'/full_base/'assets/drawings/atlas/current.json')['catalogSha256'],'Verified NAS base unavailable')
    for ancestor in chain:require((nas/'deltas'/ancestor/'delta.json').is_file(),'Required NAS delta missing')
    dest=nas/'deltas'/stamp;require(not dest.exists(),'NAS delta exists');shutil.copytree(delta,dest);verify_delta(dest,base)
    release_info={'release':stamp,'fullBaseRelease':full_base,'deltaChain':chain+[stamp],'effectiveCatalogSha256':m['candidateCatalogSha256'],'restoration':'Clone releases/fullBaseRelease, then apply each deltas/id/files in order; verify each delta previous/new SHA. Never delete the base while this chain is current.'}
    lib.atomic_write(release/'fast-release.json',lib.json_bytes(release_info));lib.atomic_write(dest/'release.json',lib.json_bytes(release_info))
    written=[];switched=False;lock=root/'library/.adopt.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        os.close(fd);require((runtime/'current').resolve()==base,'Active release changed during preparation');verify_delta(delta,root,source=True)
        write_source_delta(delta,root,backup,written)
        require(lib.json_bytes(lib.load_source(root/'library'))==(root/'catalog.json').read_bytes(),'Editable source build mismatch')
        link=runtime/('current.'+stamp);link.symlink_to(release);os.replace(link,runtime/'current');switched=True
        run(['launchctl','kickstart','-k',deploy.DOMAIN+'/'+deploy.LABEL]);deploy.wait_health(f'http://127.0.0.1:{deploy.PORT}/healthz')
        headers={'X-ZZLAB-Internal-Token':deploy.token_path().read_text().strip(),'X-ZZLAB-Authenticated':'1','X-ZZLAB-User-ID':'1','X-ZZLAB-User':'fast-import-check','X-ZZLAB-Role':'user'}
        result=smoke(f'http://127.0.0.1:{deploy.PORT}',m,headers)
        status,_=deploy.request_status(f'http://127.0.0.1:{deploy.PORT}/api/catalog');require(status in(401,403),'Authentication boundary failed')
        local=run([PYTHON,local_editor/'sync_library.py','--root',local_editor]);result['localEditor']=json.loads(local.stdout);require(result['localEditor'].get('ok')is True,'Local editor sync failed')
        lib.atomic_write(pointer,lib.json_bytes(release_info));result.update(release_info,nasDelta=str(dest),status='published',atlasUpdated=False,onshapeUpdated=False)
        lib.atomic_write(backup/'result.json',lib.json_bytes(result));lib.atomic_write(dest/'result.json',lib.json_bytes(result));return result
    except Exception:
        if switched:
            link=runtime/('rollback.'+stamp);link.symlink_to(base);os.replace(link,runtime/'current');run(['launchctl','kickstart','-k',deploy.DOMAIN+'/'+deploy.LABEL])
        restore_source_delta(root,backup,written)
        if switched:run([PYTHON,local_editor/'sync_library.py','--root',local_editor])
        if oldpointer is not None:lib.atomic_write(pointer,oldpointer)
        else:pointer.unlink(missing_ok=True)
        lib.atomic_write(backup/'rollback.json',lib.json_bytes({'status':'rolled-back','baseRelease':base.name,'unactivatedDelta':str(dest)}));raise
    finally:lock.unlink(missing_ok=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('prepared',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--base',type=Path,default=DEFAULT_RUNTIME/'current');p.add_argument('--node',default='node');p.add_argument('--candidate',type=Path);p.add_argument('--apply',action='store_true');p.add_argument('--local-editor',type=Path,default=Path('/Users/wjj/Documents/Codex/2026-10-09/ti-q/outputs/ZZLab本地光路编辑器'))
    a=p.parse_args();m=create_delta(a.prepared.resolve(),a.out.resolve(),a.root.resolve(),a.base.resolve(),a.node)
    if a.candidate:clone_candidate(a.out.resolve(),a.base.resolve(),a.candidate.resolve())
    if a.apply:
        sys.path.insert(0,str(a.root.resolve()));m=apply(a.out.resolve(),a.root.resolve(),DEFAULT_RUNTIME,DEFAULT_NAS,a.local_editor)
    print(json.dumps({'status':m.get('status','prepared-not-published'),'kitIds':m.get('kitIds'), 'delta':str(a.out.resolve()),'files':len(m.get('files',[]))},ensure_ascii=False))
