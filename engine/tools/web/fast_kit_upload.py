#!/usr/bin/env python3
# coding: utf-8
"""Prepare a standard rotator ZIP for canvas placement; no atlas, cloud or live writes.

Run with the installed CAD Python, not with scripts from the delivered ZIP.
The output is a normal library package plus a staged catalog and new assets only.
"""
from pathlib import Path, PurePosixPath
import argparse, copy, hashlib, json, math, os, shutil, stat, sys, time, zipfile
import numpy as np
import library as lib
import fast_kit_render as cad
from OCP.gp import gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
import shapely
from vtk.util.numpy_support import vtk_to_numpy

ROOT=Path(__file__).resolve().parents[1]
SCHEMA='zzlab-fast-kit-upload-v1'

def require(ok, message):
    if not ok: raise lib.LibraryError(message)

def matrix(value):
    a=np.asarray(value,dtype=float)
    if a.shape==(3,4): a=np.vstack([a,[0,0,0,1]])
    require(a.shape==(4,4) and np.isfinite(a).all() and np.allclose(a[3],[0,0,0,1]),'Invalid rigid transform')
    require(np.allclose(a[:3,:3].T@a[:3,:3],np.eye(3),atol=1e-7) and abs(np.linalg.det(a[:3,:3])-1)<1e-7,'Transform is not rigid/right handed')
    return a

def display_matrix(layout):
    evidence=layout.get('geometryEvidence',{})
    if not isinstance(evidence,dict):evidence={}
    d=layout.get('topViewRenderEvidence',{}).get('displayTransform') or evidence.get('postBaseRevision',{}).get('displayTransform')
    m=np.eye(4)
    if d:
        m[:3,:3]=d['rotationRows'];m[:3,3]=-m[:3,:3]@np.asarray(d['originSourceMm'])
    return matrix(m)

def optical_layout(source, params):
    """Conjugate the actual CAD turn into the existing fixed-base layout frame."""
    out=copy.deepcopy(source['layout']);d=display_matrix(out)
    c=matrix(params['canonicalPostToAssemblyWorld']);t=matrix(params['topCoreRotationNative'])
    turn=matrix(d@c@t@np.linalg.inv(c)@np.linalg.inv(d))
    require(np.allclose(turn[:3,2],[0,0,1],atol=1e-6) and np.allclose(turn[2],[0,0,1,0],atol=1e-6),'Rotation changes optical height; use full import')
    # Native post bottom y=-4; this also proves that a missing display transform
    # really denotes the existing upright source frame, rather than an inferred fit.
    require(np.linalg.norm((d@c@np.array([0,-4,0,1]))[:3])<.01,'Source frame/post-axis datum mismatch; use full import')
    yaw=math.degrees(math.atan2(turn[1,0],turn[0,0]))
    def point(v):return (turn@np.array([*v,1]))[:3].tolist()
    def vector(v):return (turn[:3,:3]@np.array(v)).tolist()
    center=out['opticalCenterMm']
    if center is None:
        require(out.get('opticalType')=='unsupported' and out.get('opticalDatumVerified') is False,'Missing optical center')
    else:
        v=point([center['xMm'],center['yMm'],out['opticalAxisHeightMm']])
        out['opticalCenterMm']={**center,'xMm':v[0],'yMm':v[1]}
    baseline=out.get('opticalSurfaceAngleDeg',45 if out['opticalType']=='pbs' or source['id'].endswith('-45') else 0)
    out['opticalSurfaceAngleDeg']=(baseline+yaw+180)%360-180
    for key in ('opticalDirectionDeg',):
        if key in out:out[key]=(out[key]+yaw+180)%360-180
    defaults=out.get('opticalDefaults',{})
    if 'surfaceAngleDeg' in defaults:defaults['surfaceAngleDeg']=(defaults['surfaceAngleDeg']+yaw+180)%360-180
    if 'directionAngleDeg' in defaults.get('source',{}):defaults['source']['directionAngleDeg']=(defaults['source']['directionAngleDeg']+yaw+180)%360-180
    program=out.get('opticalInteraction')
    if program:
        require(program.get('model')=='planar' and program.get('version')==1,'Unrecognized optical program; use full import')
        for inp in program.get('inputs',[]):
            if 'direction' in inp:inp['direction']['angleDeg']=(inp['direction']['angleDeg']+yaw+180)%360-180
    if out.get('opticalPortsMm'):raise lib.LibraryError('Multiport layouts need a specific adapter; use full import')
    if out.get('opticalAssembly'):
        assembly=out['opticalAssembly'];require(assembly.get('version')==2,'Unknown optical assembly version')
        for node in assembly.get('nodes',[]):
            for row in [node,*node.get('faces',[])]:
                if 'centerMm' in row:row['centerMm']=point(row['centerMm'])
                if 'normal' in row:row['normal']=vector(row['normal'])
                for key in ('basisU','basisV'):
                    if key in row:row[key]=vector(row[key])
        # Its enclosure contains the fixed post as well; replace from actual CAD below.
    # Historical evidence stays in a frozen evidence file, never as current geometry.
    for key in ('calibration','geometryEvidence','topViewRenderEvidence','opticalGeometryEvidence','sourceUrl','note','status'):
        out.pop(key,None)
    return out,d,turn,yaw

def unpack_checked(archive, output):
    digest=lib.file_sha(archive);receipt_path=archive.parent/'DELIVERY_RECEIPT.json'
    require(receipt_path.is_file(),'Missing generator DELIVERY_RECEIPT.json beside ZIP')
    receipt=lib.read_json(receipt_path)
    require(receipt.get('sha256')==digest and receipt.get('allMemberCrcAndSha256Passed') is True and receipt.get('sourceStable') is True,'ZIP does not match completed generator receipt')
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist();names=[i.filename for i in infos]
        require(len(names)==len(set(names)) and len(names)<5000,'Duplicate/oversized ZIP inventory')
        require(sum(i.file_size for i in infos)<1024**3,'Package exceeds 1 GiB fast-import limit')
        for i in infos:
            lib.relative_path(i.filename.rstrip('/'))
            require(not stat.S_ISLNK(i.external_attr>>16) and not i.flag_bits&1,'ZIP links/encryption unsupported')
        manifest=json.loads(z.read('FILE_MANIFEST.json'))
        entries={r['path']:r for r in manifest['files']}
        require(set(entries)==set(names)-{'FILE_MANIFEST.json'},'ZIP manifest membership mismatch')
        for i in infos:
            data=z.read(i.filename) # also verifies member CRC
            if i.filename!='FILE_MANIFEST.json':
                r=entries[i.filename];require(len(data)==r['bytes'] and lib.sha(data)==r['sha256'],'Corrupt ZIP member: '+i.filename)
            target=lib.contained(output,i.filename);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    return {'archiveSha256':digest,'members':len(names),'bytes':archive.stat().st_size,'generatorReceiptSha256':lib.file_sha(receipt_path)}

def project(source_path, frame, out, kit_id):
    leaves=cad.read_leaves(source_path);tr=gp_Trsf();tr.SetValues(*frame[:3].flatten().tolist())
    foot=[];triangles=0
    for leaf in leaves:
        leaf['shape']=BRepBuilderAPI_Transform(leaf['shape'],tr,True).Shape();leaf['bounds']=cad.bounds(leaf['shape'])
        mesh=cad.mesh(leaf['shape']);require(mesh.GetNumberOfPoints()>0,'Empty STEP leaf')
        v=vtk_to_numpy(mesh.GetPoints().GetData());t=vtk_to_numpy(mesh.GetPolys().GetData()).reshape(-1,4)[:,1:]
        triangles+=len(t);xy=v[t,:2].astype(float);a=xy[:,1]-xy[:,0];b=xy[:,2]-xy[:,0]
        xy=xy[np.abs(a[:,0]*b[:,1]-a[:,1]*b[:,0])>1e-9]
        if len(xy):foot.append(shapely.union_all(shapely.polygons(xy),grid_size=.0001))
    require(bool(foot),'Empty CAD projection')
    ext=[min(l['bounds'][i] for l in leaves)for i in range(3)]+[max(l['bounds'][i]for l in leaves)for i in range(3,6)]
    posts=[l for l in leaves if max(abs(l['bounds'][i]-v)for i,v in [(0,-17.5),(1,-17.5),(2,0),(3,17.5),(4,17.5)])<.01]
    require(len(posts)==1 and BRepCheck_Analyzer(posts[0]['shape']).IsValid(),'Fixed post footprint/solid did not read back')
    outline=shapely.union_all(foot,grid_size=.0001).buffer(.15,quad_segs=4).simplify(.025,preserve_topology=True)
    polys=list(outline.geoms)if outline.geom_type=='MultiPolygon'else[outline]
    polygons=[[{'xMm':round(x,6),'yMm':round(y,6)}for x,y in list(p.exterior.coords)[:-1]]for p in polys if p.area>1e-7]
    bounds=[math.floor(ext[0]-2),math.floor(ext[1]-2),math.ceil(ext[3]+2),math.ceil(ext[4]+2)]
    svg=out/(kit_id+'.svg');svg.parent.mkdir(parents=True,exist_ok=True)
    svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {bounds[2]-bounds[0]} {bounds[3]-bounds[1]}"><desc>CAD frame; origin=fixed post axis, +X right, +Y up</desc></svg>')
    job={'id':kit_id,'stepPath':str(source_path),'stepSha256':lib.file_sha(source_path),'originalSvg':str(svg),'originalSvgSha256':lib.file_sha(svg),'boundsMm':bounds}
    report=cad.render(job,Path('/'),out,prepared_leaves=leaves)
    return {'boundsMm':ext,'frameMm':bounds,'collisionPolygonsMm':polygons,'collisionBoundsMm':dict(zip(['xMin','yMin','xMax','yMax'],outline.bounds)),'leafCount':len(leaves),'triangleCount':triangles,'fixedPostReadbackPassed':True,'render':report},svg

def prepare(archive, output, root):
    started=time.monotonic();output=output.resolve();root=root.resolve()
    require(not output.exists(),'Output must be new; refusing to overwrite previous results')
    output.mkdir(parents=True);unpack=output/'input';package=output/'package';package.mkdir()
    check=unpack_checked(archive,unpack)
    status=lib.read_json(unpack/'核验/交付状态.json');checks=lib.read_json(unpack/'核验/几何核验.json')
    require(status.get('schema')=='zzlab-simple-kit-rotation-v1' and status.get('localGeometryPassed') is True and status.get('laserOutlineReadbackPassed') is True and checks.get('passed') is True,'Generator validation incomplete')
    params=lib.read_json(unpack/'标准协议/角度参数与孔位.json');kit=lib.read_json(unpack/'标准协议/套件记录.json');post=lib.read_json(unpack/'标准协议/特制柱记录.json')
    frozen=lib.read_json(unpack/'可复建源/source-inputs/source-records.json')
    trust=lib.read_json(root/'tools/fast-kit-templates.json')
    require(lib.file_sha(unpack/'可复建源/geometry.py') in trust['geometryGeneratorSha256'],'Generator version not admitted; review it once before fast import')
    base=lib.load_source(root/'library');require(lib.json_bytes(base)==(root/'catalog.json').read_bytes(),'Source/runtime catalog mismatch')
    source=next((k for k in base['kits'] if k['id']==params['kitId']),None)
    require(source is not None and source['id'] in trust['kits'],'Source kit not admitted')
    ref=source['assemblyReference'];assembly_sha=lib.file_sha(root/'assets'/ref['stepPath'])
    require(assembly_sha==params['sourceAssemblySha256']==trust['kits'][source['id']]['assemblySha256'],'Baseline geometry changed; rebase package before fast import')
    require(frozen['kit']['id']==source['id'] and frozen['kit']['components']==source['components'],'Baseline BOM changed')
    existing={p['id']:p for p in base['components']};old_post=frozen['post']['id']
    require(lib.file_sha(root/'assets'/existing[old_post]['stepPath'])==params['sourcePostSha256'],'Baseline post changed')
    require(post['sourceReference']['componentId']==old_post and post['id'] not in existing and all(k['id']!=kit['id']for k in base['kits']),'Duplicate variant or post identity')
    expected=[{**r,'componentId':post['id'] if r['componentId']==old_post else r['componentId']}for r in source['components']]
    require(kit['components']==expected and kit['opticalSlots']==source['opticalSlots'],'Unexpected variant BOM/optical slot change')
    require(post['manufacturingEvidence']['generatorSha256'] in trust['geometryGeneratorSha256'],'Post generator claim mismatch')
    layout,frame,turn,yaw=optical_layout(source,params)
    assembly=lib.contained(unpack,kit['assemblyReference']['packagePath'])
    require(lib.file_sha(assembly)==kit['assemblyReference'].get('sourceStepSha256',kit['assemblyReference'].get('stepSha256')),'Assembly digest mismatch')
    geometry,svg=project(assembly,frame,output/'preview',kit['id'])
    require(geometry['leafCount']==checks['readbackLeafCount'],'Assembly leaf count differs from generator receipt')
    x0,y0,x1,y1=geometry['frameMm'];image_path='topviews/'+svg.name
    layout.update(widthMm=x1-x0,heightMm=y1-y0,anchorXMm=-x0,anchorYMm=y1,topViewPath=image_path,topViewUrl='./'+image_path,placementAllowed=True,collisionBoundsMm=geometry['collisionBoundsMm'],collisionPolygonsMm=geometry['collisionPolygonsMm'],collisionGeometryVersion=SCHEMA,
        status='极速上传：真实总装俯视图、固定底座安装孔和光学基准已接入',
        geometryEvidence={'sourceStep':kit['assemblyReference']['stepPath'],'sourceSha256':lib.file_sha(assembly),'imageSha256':lib.file_sha(svg),'partCount':geometry['leafCount'],'meshDeflectionMm':.035,'guardMm':.15,'displayTransform':frame.tolist()},
        topViewRenderEvidence={'style':cad.STYLE,'sourceStepSha256':lib.file_sha(assembly),'imageSha256':lib.file_sha(svg)},
        opticalGeometryEvidence={'scope':'Rigidly transformed existing catalog optical datums; prior uncertainties preserved; no new physical certification','baselineKitId':source['id'],'baselineRecordSha256':lib.sha(lib.json_bytes(source)),'layoutTurn':turn.tolist(),'additionalLayoutYawDeg':yaw})
    if layout.get('opticalAssembly'):layout['opticalAssembly']['bounds']={'min':geometry['boundsMm'][:3],'max':geometry['boundsMm'][3:]}
    require(layout['mountingHoleOffsetsMm']==source['layout']['mountingHoleOffsetsMm'] and layout['baseBoundsMm']==source['layout']['baseBoundsMm'],'Fixed base moved')
    kit['layout']=layout;kit.pop('sourceLayout',None)
    kit.update(status='极速上传 · 可布局 · 加工审核版',releaseStage='fast-upload',productionReady=False)
    kit['fastUpload']={'schema':SCHEMA,'archiveSha256':check['archiveSha256'],'atlas':'excluded-by-user-scope','onshape':'excluded-by-user-scope','physicalAssemblyValidated':False,'productionApprovalGranted':False}
    assets=[]
    def asset(root_name,relative,src):
        lib.relative_path(relative);dst=package/root_name/relative;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        assets.append({'root':root_name,'path':relative,'source':str(dst.relative_to(package)),'sha256':lib.file_sha(dst),'mode':'add'})
    asset('assets',kit['assemblyReference']['stepPath'],assembly);kit['assemblyReference'].pop('packagePath',None);kit['assemblyReference']['sourceStepSha256']=lib.file_sha(assembly)
    pa=post.pop('packageAssets');pl=post.pop('packageLaserMarking')
    asset('assets',post['stepPath'],lib.contained(unpack,pa['step']));asset('assets',post['drawingPath'],lib.contained(unpack,pa['drawing']))
    for f,pf in zip(post['laserMarking']['files'],pl[0]['files'],strict=True):
        for field in ('dxfPath','setupPdfPath'):asset('assets',f[field],lib.contained(unpack,pf[field]))
    asset('static',image_path,svg)
    # Validate only the newly delivered PDFs for basic readability; no page redraw.
    from pypdf import PdfReader
    for a in assets:
        p=package/a['source'];lib.verify_new_asset(p,a['root']+'/'+a['path'])
        if p.suffix.lower()=='.pdf':require(len(PdfReader(p).pages)>0,'Empty/unreadable PDF')
    evidence=package/'evidence';evidence.mkdir()
    report={'schema':SCHEMA,**check,'kitId':kit['id'],'sourceKitId':source['id'],'additionalLayoutYawDeg':yaw,'fixedMountingHolesPreserved':True,'sourceGeometryChecksReused':True,'geometry':geometry,'atlas':'not-requested','onshape':'not-requested','physicalCertification':False,'prepareSeconds':round(time.monotonic()-started,3)}
    lib.atomic_write(evidence/'check.json',lib.json_bytes(report));lib.atomic_write(evidence/'baseline-kit.json',lib.json_bytes(source))
    for name in ['交付状态.json','几何核验.json','激光文件核验.json']:shutil.copy2(unpack/'核验'/name,evidence/name)
    reviews={name:{'status':'reviewed','reviewer':'ZZLab fast import checks + inherited generator evidence','reason':reason,'evidence':[{'path':str(p.relative_to(package)),'sha256':lib.file_sha(p)}for p in sorted(evidence.iterdir())]}for name,reason in {
        'sourceReviewed':'ZIP CRC/hash and external completion receipt; known generator and unchanged baseline source CAD.',
        'geometryReviewed':'New assembly STEP parsed and projected; actual fixed post footprint read back; generator geometry checks reused.',
        'interactionReviewed':'Existing supported optical declarations conjugated by measured rigid transform; mounting points fixed; physical uncertainty retained.',
        'bomReviewed':'Existing component IDs/quantities and optical slots unchanged; only new post replaced; new STEP/PDF/marking files readable.'}.items()}
    records=[]
    for group,row in [('kits',kit),('components',post)]:
        path=f'records/{group}/{row["id"]}.json';lib.atomic_write(package/path,lib.json_bytes(row));records.append({'type':group,'id':row['id'],'path':path,'mode':'add'})
    spec={'protocolVersion':lib.PROTOCOL_VERSION,'packageId':'fast-'+check['archiveSha256'][:20],'baseCatalogSha256':lib.sha(lib.json_bytes(base)),'records':records,'assets':assets,'metadataPatch':{'version':base['version'].split('.fast-')[0]+'.fast-'+check['archiveSha256'][:10]},'notes':'User-selected fast upload: canvas/download usability, no atlas/Onshape, no physical/manufacturing approval.','reviews':reviews}
    lib.atomic_write(package/'package.json',lib.json_bytes(spec))
    lib.stage_package(package,root/'library',root,output/'stage')
    report['totalSeconds']=round(time.monotonic()-started,3);report['package']=str(package);report['stage']=str(output/'stage')
    lib.atomic_write(output/'receipt.json',lib.json_bytes(report))
    print(json.dumps({k:report[k]for k in ['kitId','sourceKitId','additionalLayoutYawDeg','totalSeconds','stage']},ensure_ascii=False),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--root',type=Path,default=ROOT)
    a=p.parse_args()
    try:prepare(a.archive.resolve(),a.output,a.root)
    except Exception as e:print(f'Fast import stopped: {e}',file=sys.stderr);raise
