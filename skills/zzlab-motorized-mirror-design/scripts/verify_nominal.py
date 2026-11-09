"""Hash-bound, named-leaf nominal STEP audit; never edits models or runs motors."""
from pathlib import Path
import argparse,hashlib,json,math,sys

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def finite(value):
    v=float(value)
    if not math.isfinite(v):raise ValueError('Nonfinite geometric value')
    return v

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',required=True,type=Path);ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--cad-deps',type=Path);args=ap.parse_args()
    if args.cad_deps:
        if not args.cad_deps.is_dir():raise ValueError('CAD dependency directory missing')
        sys.path.insert(0,str(args.cad_deps.resolve()))
    import cadquery as cq
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_Label,TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.TopLoc import TopLoc_Location

    cfgpath=args.config.resolve();out=args.output.resolve()
    if out.exists():raise FileExistsError('Output must be a new path')
    cfg=json.loads(cfgpath.read_text(encoding='utf8'))
    if cfg.get('format')!='zzlab-mirror-nominal-check-v1' or cfg.get('units')!='mm':
        raise ValueError('Expected versioned config and explicitly confirmed mm units')
    tol=finite(cfg.get('intersectionVolumeToleranceMm3',1e-6))
    if not 0<=tol<=1e-3:raise ValueError('Unsupported boolean-volume tolerance; review numerical basis')
    if tol!=1e-6 and not cfg.get('volumeToleranceReason'):raise ValueError('Nondefault tolerance needs reason')
    specs=cfg['assemblies']
    if not specs or len({s['id'] for s in specs})!=len(specs):raise ValueError('Need unique nonempty assemblies')
    rows=[];errors=[]

    def read_leaves(path):
        doc=TDocStd_Document(TCollection_ExtendedString('MDTV-XCAF'))
        reader=STEPCAFControl_Reader();reader.SetNameMode(True);reader.ReadFile(str(path))
        if not reader.Transfer(doc):raise ValueError('STEP transfer failed')
        st=XCAFDoc_DocumentTool.ShapeTool_s(doc.Main());roots=TDF_LabelSequence();st.GetFreeShapes(roots)
        result=[]
        def name(label):
            attr=TDataStd_Name()
            return attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(),attr) else ''
        def walk(label,parent=TopLoc_Location()):
            ref=TDF_Label();target=ref if st.GetReferredShape_s(label,ref) else label
            loc=parent.Multiplied(st.GetLocation_s(label));kids=TDF_LabelSequence()
            n=name(label) or name(target)
            if st.GetComponents_s(target,kids):
                for k in range(1,kids.Length()+1):walk(kids.Value(k),loc)
            else:result.append((n,cq.Shape.cast(st.GetShape_s(target).Located(loc))))
        for k in range(1,roots.Length()+1):walk(roots.Value(k))
        return result

    for spec in specs:
        path=(cfgpath.parent/spec['path']).resolve()
        if out==path or out==cfgpath:raise ValueError('Output overlaps input')
        actualsha=sha(path)
        if actualsha!=spec['sha256']:raise ValueError('STEP SHA mismatch: '+spec['id'])
        leaves=read_leaves(path);names=[n for n,s in leaves];expected=spec['expectedLeafNames']
        if not names or len(set(names))!=len(names) or len(set(expected))!=len(expected) or set(names)!=set(expected):
            raise ValueError('Complete named leaf membership mismatch: '+spec['id'])
        excluded=spec.get('nonPhysicalReviewLeafNames',[])
        if not set(excluded)<=set(names) or len(set(excluded))!=len(excluded):raise ValueError('Invalid exclusion list')
        if excluded and not spec.get('reviewExclusionReason'):raise ValueError('Review-only exclusion needs reason')
        physical={n:s for n,s in leaves if n not in excluded}
        if not physical:raise ValueError('No physical leaves')
        singles=spec.get('singleSolidLeafNames',[])
        if len(set(singles))!=len(singles) or not set(singles)<=set(physical):raise ValueError('Invalid single-solid leaf list')
        solidrows=[]
        for n,s in physical.items():
            valid=s.isValid();count=len(s.Solids());volume=finite(s.Volume())
            if not valid or count<1 or volume<=0:errors.append({'assembly':spec['id'],'kind':'invalid-solid','leaf':n})
            if n in singles and count!=1:errors.append({'assembly':spec['id'],'kind':'disconnected-custom-part','leaf':n,'solidCount':count})
            solidrows.append({'name':n,'valid':valid,'solidCount':count,'volumeMm3':volume})
        keepoutrows=[]
        if not spec.get('keepouts'):raise ValueError('At least one optical keepout required')
        for k in spec['keepouts']:
            origin=[finite(v) for v in k['originMm']];axis=[finite(v) for v in k['axis']]
            r=finite(k['radiusMm']);length=finite(k['lengthMm'])
            if len(origin)!=3 or len(axis)!=3 or sum(v*v for v in axis)<=0 or r<=0 or length<=0:raise ValueError('Invalid cylinder')
            channel=cq.Solid.makeCylinder(r,length,cq.Vector(*origin),cq.Vector(*axis))
            tests=[]
            for n,s in physical.items():
                vol=finite(s.intersect(channel).Volume());gap=finite(s.distance(channel))
                passed=vol<=tol
                tests.append({'leaf':n,'overlapMm3':vol,'minimumDistanceMm':gap,'passed':passed})
                if not passed:errors.append({'assembly':spec['id'],'kind':'optical-intrusion','keepout':k['id'],'leaf':n,'overlapMm3':vol})
            keepoutrows.append({'id':k['id'],'definition':k,'tests':tests})
        planes=[]
        for g in spec.get('coplanarGroups',[]):
            ns=g['leafNames'];b=g['bound'];offset=finite(g.get('datumOffsetMm',0));target=finite(g['expectedPlaneMm']);eps=finite(g['toleranceMm'])
            if len(ns)<2 or len(set(ns))!=len(ns) or not set(ns)<=set(physical) or not isinstance(b,int) or not 0<=b<=5 or eps<0:raise ValueError('Invalid plane group')
            vals=[]
            for n in ns:
                box=physical[n].BoundingBox();bounds=[box.xmin,box.ymin,box.zmin,box.xmax,box.ymax,box.zmax]
                vals.append(finite(bounds[b]+offset))
            passed=max(vals)-min(vals)<=eps and all(abs(v-target)<=eps for v in vals)
            planes.append({'id':g['id'],'valuesMm':vals,'expectedPlaneMm':target,'passed':passed})
            if not passed:errors.append({'assembly':spec['id'],'kind':'noncoplanar','group':g['id']})
        rows.append({'id':spec['id'],'stepPath':spec['path'],'stepSha256':actualsha,'leafCount':len(leaves),'physicalLeafCount':len(physical),'excludedReviewLeaves':excluded,'reviewExclusionReason':spec.get('reviewExclusionReason'),'solids':solidrows,'keepouts':keepoutrows,'coplanarGroups':planes})
    result={'format':'zzlab-mirror-nominal-check-receipt-v1','status':'failed' if errors else 'passed','units':'mm','configSha256':sha(cfgpath),'checkerSha256':sha(Path(__file__).resolve()),'cadqueryVersion':cq.__version__,'assemblies':rows,'failures':errors,'scope':'Actual nominal STEP membership/solid/coplanarity/optical-cylinder checks only. Caller defines full keepout range; no manufacturing tolerance, motion, tools, torque, FEM, cloud or physical tests certified.'}
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'status':result['status'],'assemblies':len(rows),'failures':len(errors),'receipt':str(out)},ensure_ascii=False))
    return 1 if errors else 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        print(json.dumps({'status':'error','errorType':type(exc).__name__,'message':str(exc)},ensure_ascii=False),file=sys.stderr)
        sys.exit(2)
