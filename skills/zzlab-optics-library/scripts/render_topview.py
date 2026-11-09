"""ZZLab shaded-metal-v1: orthographic CAD display only, OCP 8 + VTK.

No geometry writing, projection recentering, perspective, or synthetic solids.
Job JSON supplies frozen STEP SHA, existing SVG frame, explicit leaf selection
and optional appearance overrides. Paths resolve against --root.
"""
from pathlib import Path
import argparse, base64, hashlib, html, json, math, re
import xml.etree.ElementTree as ET
import vtk
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.IFSelect import IFSelect_RetDone
from OCP.Quantity import Quantity_Color
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorGen, XCAFDoc_ColorSurf
from OCP.collections import Sequence_TDF_Label

STYLE = 'zzlab-shaded-metal-v1'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()

def bounds(shape):
    box = Bnd_Box(); BRepBndLib.AddOptimal_s(shape, box, False, False)
    lo,hi=box.CornerMin(),box.CornerMax()
    return [lo.X(),lo.Y(),lo.Z(),hi.X(),hi.Y(),hi.Z()]

def read_leaves(path):
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString('XmlXCAF'))
    created = app.NewDocument(TCollection_ExtendedString('XmlXCAF'), doc)
    if created: doc = created[0]
    try:
        reader = STEPCAFControl_Reader(); reader.SetColorMode(True); reader.SetNameMode(True)
        assert reader.ReadFile(str(path)) == IFSelect_RetDone and reader.Transfer(doc)
        shapes = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        colors = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
        roots = Sequence_TDF_Label(); shapes.GetFreeShapes(roots); leaves=[]
        def walk(label, parent=TopLoc_Location(), inherited=(.50,.61,.69)):
            ref=TDF_Label(); target=ref if shapes.GetReferredShape_s(label,ref) else label
            position=parent.Multiplied(shapes.GetLocation_s(label)); color=inherited
            for lab in (target,label):
                for kind in (XCAFDoc_ColorGen,XCAFDoc_ColorSurf):
                    found=Quantity_Color()
                    if colors.GetColor_s(lab,kind,found):
                        color=(found.Red(),found.Green(),found.Blue());break
            children=Sequence_TDF_Label()
            if shapes.GetComponents_s(target,children):
                for i in range(1,children.Length()+1):walk(children.Value(i),position,color)
            else:
                attr=TDataStd_Name()
                name=attr.Get().ToExtString() if target.FindAttribute(TDataStd_Name.GetID_s(),attr) else ''
                shape=shapes.GetShape_s(target).Moved(position)
                leaves.append(dict(name=name,shape=shape,color=color,bounds=bounds(shape)))
        for i in range(1,roots.Length()+1):walk(roots.Value(i))
        return leaves
    finally:app.Close(doc)

def mesh(shape):
    BRepMesh_IncrementalMesh(shape,.035,False,.16,True)
    points=vtk.vtkPoints(); cells=vtk.vtkCellArray()
    ex=TopExp_Explorer(shape,TopAbs_FACE)
    while ex.More():
        face=TopoDS.Face(ex.Current()); loc=TopLoc_Location()
        tri=BRep_Tool.Triangulation_s(face,loc)
        if tri:
            offset=points.GetNumberOfPoints()
            for i in range(1,tri.NbNodes()+1):
                p=tri.Node(i).Transformed(loc.Transformation());points.InsertNextPoint(p.X(),p.Y(),p.Z())
            for i in range(1,tri.NbTriangles()+1):
                ids=list(tri.Triangle(i).Get())
                if face.Orientation()==TopAbs_REVERSED:ids.reverse()
                cells.InsertNextCell(3)
                for j in ids:cells.InsertCellPoint(offset+j-1)
        ex.Next()
    pd=vtk.vtkPolyData();pd.SetPoints(points);pd.SetPolys(cells)
    clean=vtk.vtkCleanPolyData();clean.SetInputData(pd);clean.Update()
    return clean.GetOutput()

def render(job,root,out,frames_root=None):
    source=root/job['stepPath'];old=(frames_root or root)/job['originalSvg']
    assert sha(source)==job['stepSha256']
    assert sha(old)==job['originalSvgSha256']
    all_leaves=read_leaves(source)
    names=[l['name'] for l in all_leaves]
    exclude=set(job.get('excludeNames',[])); include=job.get('includeNames')
    assert exclude.issubset(names),exclude-set(names)
    if include is not None:assert set(include).issubset(names),set(include)-set(names)
    leaves=[l for l in all_leaves if l['name'] not in exclude and (include is None or l['name'] in include)]
    assert leaves
    x0,y0,x1,y1=job['boundsMm'];w=x1-x0;h=y1-y0
    assert w>0 and h>0 and all(math.isfinite(v) for v in [x0,y0,x1,y1])
    ext=[min(l['bounds'][i] for l in leaves) for i in range(3)]+[max(l['bounds'][i] for l in leaves) for i in range(3,6)]
    assert ext[0]>=x0-.01 and ext[1]>=y0-.01 and ext[3]<=x1+.01 and ext[4]<=y1+.01,(job['id'],'CAD outside original frame',ext,job['boundsMm'])
    ppm=min(10,900/max(w,h));width=max(1,round(w*ppm));height=max(1,round(h*ppm))
    ren=vtk.vtkRenderer();ren.SetBackground(1,1,1);ren.SetBackgroundAlpha(0)
    ren.SetUseSSAO(True);ren.SetSSAORadius(5);ren.SetSSAOBias(.03);ren.SetSSAOKernelSize(64);ren.SetSSAOBlur(True)
    appearance=[];triangles=0
    for leaf in leaves:
        color=job.get('colors',{}).get(leaf['name'],leaf['color'])
        pd=mesh(leaf['shape']);triangles+=pd.GetNumberOfCells()
        normals=vtk.vtkPolyDataNormals();normals.SetInputData(pd);normals.SetFeatureAngle(32);normals.ConsistencyOn()
        mapper=vtk.vtkPolyDataMapper();mapper.SetInputConnection(normals.GetOutputPort())
        actor=vtk.vtkActor();actor.SetMapper(mapper)
        prop=actor.GetProperty();prop.SetColor(*color);prop.SetInterpolationToPhong()
        prop.SetAmbient(.32);prop.SetDiffuse(.68);prop.SetSpecular(.42);prop.SetSpecularPower(35)
        ren.AddActor(actor)
        edge=vtk.vtkFeatureEdges();edge.SetInputData(pd);edge.BoundaryEdgesOn();edge.FeatureEdgesOn();edge.NonManifoldEdgesOff();edge.ManifoldEdgesOff();edge.SetFeatureAngle(32);edge.ColoringOff()
        em=vtk.vtkPolyDataMapper();em.SetInputConnection(edge.GetOutputPort());em.SetResolveCoincidentTopologyToPolygonOffset()
        ea=vtk.vtkActor();ea.SetMapper(em);ea.GetProperty().SetColor(.12,.17,.20);ea.GetProperty().SetLineWidth(.8);ea.GetProperty().LightingOff();ren.AddActor(ea)
        appearance.append(dict(name=leaf['name'],sourceColor=leaf['color'],renderColor=color,boundsMm=leaf['bounds']))
    win=vtk.vtkRenderWindow();win.SetOffScreenRendering(1);win.SetAlphaBitPlanes(1);win.SetMultiSamples(8);win.SetSize(width,height);win.AddRenderer(ren)
    cx,cy=(x0+x1)/2,(y0+y1)/2;distance=max(1000,ext[5]+1000)
    camera=ren.GetActiveCamera();camera.SetPosition(cx,cy,distance);camera.SetFocalPoint(cx,cy,0);camera.SetViewUp(0,1,0);camera.ParallelProjectionOn();camera.SetParallelScale(h/2)
    camera.SetUseExplicitAspectRatio(True);camera.SetExplicitAspectRatio(w/h)
    # Explicit window center keeps the mm frame fixed; only <0.1% pixel aspect rounding.
    for pos,intensity in [((cx-400,cy+500,distance),.85),((cx+500,cy-200,distance),.35)]:
        light=vtk.vtkLight();light.SetLightTypeToSceneLight();light.SetPosition(*pos);light.SetFocalPoint(cx,cy,0);light.SetIntensity(intensity);ren.AddLight(light)
    ren.ResetCameraClippingRange();win.Render()
    shot=vtk.vtkWindowToImageFilter();shot.SetInput(win);shot.SetInputBufferTypeToRGBA();shot.ReadFrontBufferOff();shot.Update()
    writer=vtk.vtkPNGWriter();writer.WriteToMemoryOn();writer.SetInputConnection(shot.GetOutputPort());writer.Write()
    png=bytes(memoryview(writer.GetResult()));win.Finalize()
    out.mkdir(parents=True,exist_ok=True)
    pngpath=out/(job['id']+'.png');pngpath.write_bytes(png)
    tree=ET.fromstring(old.read_text()); vb=list(map(float,tree.attrib['viewBox'].split()))
    assert abs(vb[2]-w)<.0001 and abs(vb[3]-h)<.0001
    desc=next((e.text or '' for e in tree if e.tag.endswith('desc')),'')
    meta=dict(style=STYLE,sourceStepSha256=job['stepSha256'],geometryModified=False,worldFrame='+X right; +Y up; view from +Z',boundsMm=job['boundsMm'],excludedLeaves=sorted(exclude),leafCount=len(leaves),linearDeflectionMm=.035)
    attrs=' '.join(f'{key}="{html.escape(tree.attrib[key],quote=True)}"' for key in ['viewBox','width','height'] if key in tree.attrib)
    encoded=base64.b64encode(png).decode()
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" {attrs}><title>{html.escape(job["id"])} · 原装配金属质感俯视图</title><desc>真实 STEP 正交着色；{STYLE}；仅显示更新，原尺寸/原点/孔位/碰撞/光学基准不变。原参考说明：{html.escape(desc)}</desc><metadata>{html.escape(json.dumps(meta,ensure_ascii=False))}</metadata><image x="{vb[0]}" y="{vb[1]}" width="{vb[2]}" height="{vb[3]}" preserveAspectRatio="none" href="data:image/png;base64,{encoded}"/></svg>\n'
    path=out/Path(job['originalSvg']).name;path.write_text(svg)
    report={**meta,'id':job['id'],'svg':path.name,'svgSha256':sha(path),'png':pngpath.name,'pixelSize':[width,height],'triangles':triangles,'appearance':appearance}
    (out/(job['id']+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--frames-root',type=Path);p.add_argument('--jobs',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--only')
    a=p.parse_args();jobs=json.loads(a.jobs.read_text());results=[]
    for job in jobs:
        if a.only and job['id']!=a.only:continue
        print('Rendering',job['id'],flush=True);results.append(render(job,a.root,a.out,a.frames_root))
        print('Rendered',job['id'],results[-1]['leafCount'],flush=True)
    if not a.only:(a.out/'render-report.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
