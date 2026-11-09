"""Generate only the laser adapter plate, never the purchased laser model."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import re

from laser_adapter import validate_adapter_spec
from breadboard_worker import font_init, MM
from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeCylinder
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Circ, gp_Vec
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics


def make_model(spec, path):
    b, t, cb = spec["outlineBoundsMm"], spec["thicknessMm"], spec["counterbore"]
    polygon = BRepBuilderAPI_MakePolygon()
    for x, y in ((b["xMin"], b["yMin"]), (b["xMax"], b["yMin"]), (b["xMax"], b["yMax"]), (b["xMin"], b["yMax"])):
        polygon.Add(gp_Pnt(x, y, 0))
    polygon.Close()
    face = BRepBuilderAPI_MakeFace(polygon.Wire(), True)
    holes = [(h, spec["thread"]["stepDiameterMm"]) for h in spec["laserThreadHolesMm"]]
    holes += [(h, cb["clearanceDiameterMm"]) for h in spec["boardMountingHolesMm"]]
    for h, diameter in holes:
        edge = BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(h["xMm"], h["yMm"], 0), gp_Dir(0, 0, 1)), diameter / 2)).Edge()
        wire = BRepBuilderAPI_MakeWire(edge).Wire()
        wire.Reverse()
        face.Add(wire)
    body = BRepPrimAPI_MakePrism(face.Face(), gp_Vec(0, 0, -t), False, True).Shape()
    compound, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(compound)
    for h in spec["boardMountingHolesMm"]:
        cylinder = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(h["xMm"], h["yMm"], .1), gp_Dir(0, 0, -1)), cb["diameterMm"] / 2, cb["depthMm"] + .1).Shape()
        builder.Add(compound, cylinder)
    cut = BRepAlgoAPI_Cut(body, compound)
    if not cut.IsDone():
        raise RuntimeError("Adapter counterbore cut failed")
    body = cut.Shape()
    if not BRepCheck_Analyzer(body, True).IsValid():
        raise RuntimeError("Adapter is not a valid B-rep")
    explorer, solids = TopExp_Explorer(body, TopAbs_SOLID), 0
    while explorer.More():
        solids += 1
        explorer.Next()
    explorer, cylinders = TopExp_Explorer(body, TopAbs_FACE), 0
    while explorer.More():
        if BRepAdaptor_Surface(TopoDS.Face(explorer.Current()), True).GetType() == GeomAbs_Cylinder:
            cylinders += 1
        explorer.Next()
    expected_faces = len(holes) + len(spec["boardMountingHolesMm"])
    if solids != 1 or cylinders != expected_faces:
        raise RuntimeError("Adapter topology differs from the explicit hole scheme")
    mass = GProp_GProps()
    BRepGProp.VolumeProperties_s(body, mass)
    expected = (b["xMax"] - b["xMin"]) * (b["yMax"] - b["yMin"]) * t
    expected -= sum(math.pi * (diameter / 2) ** 2 * t for _, diameter in holes)
    expected -= len(spec["boardMountingHolesMm"]) * math.pi * ((cb["diameterMm"] / 2) ** 2 - (cb["clearanceDiameterMm"] / 2) ** 2) * cb["depthMm"]
    if abs(mass.Mass() - expected) > max(.001, expected * 1e-9):
        raise RuntimeError("Adapter volume differs from analytic hole volume")
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    writer = STEPControl_Writer()
    if writer.Transfer(body, STEPControl_AsIs) != IFSelect_RetDone or writer.Write(str(path)) != IFSelect_RetDone:
        raise RuntimeError("Adapter STEP export failed")
    step = path.read_text()
    step = re.sub(r"(FILE_NAME\([^,]*,\s*)'[^']*'", r"\1'2026-09-28T00:00:00'", step, count=1, flags=re.S)
    step = step.replace("'Open CASCADE Shape Model'", f"'{spec['model']}'", 1)
    step = re.sub(r"'Open CASCADE STEP translator [^']*'", f"'{spec['model']}'", step)
    path.write_text(step)
    return {"valid": True, "solidCount": solids, "cylindricalHoleFaces": cylinders,
            "laserThreadHoleCount": len(spec["laserThreadHolesMm"]), "mountingHoleCount": len(spec["boardMountingHolesMm"]),
            "volumeMm3": mass.Mass(), "analyticVolumeMm3": expected}


def make_topview(spec):
    b, cb, port = spec["outlineBoundsMm"], spec["counterbore"], spec["opticalPortMm"]
    e = html.escape
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-315 -155 605 315" width="1210" height="630" role="img" aria-label="{e(spec["model"])} 底板俯视图">',
           '<rect x="-315" y="-155" width="605" height="315" fill="white"/>',
           f'<g transform="scale(1,-1)"><rect x="{b["xMin"]}" y="{b["yMin"]}" width="{b["xMax"]-b["xMin"]}" height="{b["yMax"]-b["yMin"]}" fill="#edf4f3" stroke="#223e44" stroke-width="1.2"/>']
    for key, color in (("laserThreadHolesMm", "#1b6660"), ("boardMountingHolesMm", "#9b5b08")):
        for h in spec[key]:
            diameter = spec["thread"]["nominalDiameterMm"] if key == "laserThreadHolesMm" else cb["clearanceDiameterMm"]
            out.append(f'<circle cx="{h["xMm"]}" cy="{h["yMm"]}" r="{diameter/2}" fill="white" stroke="{color}" stroke-width=".8"/>')
            if key == "boardMountingHolesMm":
                out.append(f'<circle cx="{h["xMm"]}" cy="{h["yMm"]}" r="{cb["diameterMm"]/2}" fill="none" stroke="{color}" stroke-width=".8"/>')
    out.append(f'<path d="M {port["xMm"]} {port["yMm"]} h -20 m 0 0 l 5 3 m -5 -3 l 5 -3" stroke="#bd4331" fill="none" stroke-width="1.4"/></g>')
    for key in ("laserThreadHolesMm", "boardMountingHolesMm"):
        for h in spec[key]:
            out.append(f'<text x="{h["xMm"]+7}" y="{-h["yMm"]+3}" font-size="7" font-family="sans-serif">{e(h["label"])}</text>')
    out.append(f'<text x="-278" y="150" font-size="9" font-family="sans-serif">{e(spec["model"])} / {spec["thicknessMm"]:g} mm / 加工审核版</text></svg>')
    return "".join(out)


def make_pdf(spec, path):
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase import pdfmetrics as symbol_metrics
    pdfmetrics=symbol_metrics
    symbol_font='CompactHoleSymbols'
    pdfmetrics.registerFont(TTFont(symbol_font,'/System/Library/Fonts/STHeiti Light.ttc',subfontIndex=0))
    SYMBOLS=set('⌀⌴⌵↧')
    def text_width(text,size):
     return sum(size*.7 if ch in SYMBOLS else pdfmetrics.stringWidth(ch,symbol_font,size) for ch in text)
    def draw_compact_line(c,x,y,text,size=8.5):
     """Vector engineering symbols, independent of installed font glyph coverage."""
     for ch in text:
      if ch not in SYMBOLS:
       c.drawString(x,y,ch);x+=pdfmetrics.stringWidth(ch,symbol_font,size);continue
      w=size*.7;mid=x+w*.45;yc=y+size*.32;c.setLineWidth(.5)
      if ch=='⌀':c.circle(mid,yc,size*.24,stroke=1,fill=0);c.line(mid-size*.32,yc-size*.32,mid+size*.32,yc+size*.32)
      elif ch=='⌴':c.line(x+1,y+size*.62,x+1,y+size*.08);c.line(x+1,y+size*.08,x+w-1,y+size*.08);c.line(x+w-1,y+size*.08,x+w-1,y+size*.62)
      elif ch=='⌵':c.line(x+1,y+size*.62,mid,y+size*.08);c.line(mid,y+size*.08,x+w-1,y+size*.62)
      else:
       c.line(mid,y+size*.70,mid,y+size*.08);c.line(x+1,y+size*.70,x+w-1,y+size*.70);c.line(mid,y+size*.08,mid-size*.19,y+size*.27);c.line(mid,y+size*.08,mid+size*.19,y+size*.27)
      x+=w
    def hole_text(x,y,t,size):
        c.saveState();c.translate(x,y);c.scale(1/MM,1/MM);c.setFont(symbol_font,size*MM);draw_compact_line(c,0,0,t,size*MM);c.restoreState()
    b, t, cb = spec["outlineBoundsMm"], spec["thicknessMm"], spec["counterbore"]
    w, h = b["xMax"]-b["xMin"], b["yMax"]-b["yMin"]
    font = font_init()
    c = canvas.Canvas(str(path), pagesize=(420*MM, 297*MM), pageCompression=1, invariant=1)
    c.setTitle(spec["model"] + " 308 nm 激光器安装底板三视图")
    c.setAuthor("ZZLab")
    c.setSubject("仅底板 / 加工审核版 / 孔组基准须核对")
    def text(x, y, value, size=3, align="left", color="#1b3039"):
        c.setFillColor(color); c.setFont(font, size)
        fn = c.drawCentredString if align == "center" else c.drawRightString if align == "right" else c.drawString
        fn(x, y, str(value))
    def line(x1,y1,x2,y2,dash=None,width=.2):
        c.setStrokeColor("#1b3039");c.setLineWidth(width);c.setDash(dash or [])
        c.line(x1,y1,x2,y2);c.setDash([])
    def rect(x,y,ww,hh):
        c.setStrokeColor("#1b3039");c.setLineWidth(.3);c.rect(x,y,ww,hh,fill=0)
    def circle(x,y,r):
        c.setStrokeColor("#1b3039");c.setLineWidth(.2);c.circle(x,y,r,fill=0)
    def arrow(x,y,angle):
        ca,sa=math.cos(angle),math.sin(angle)
        p=c.beginPath();p.moveTo(x,y);p.lineTo(x+1.4*ca+.35*sa,y+1.4*sa-.35*ca);p.lineTo(x+1.4*ca-.35*sa,y+1.4*sa+.35*ca);p.close()
        c.setFillColor("#1b3039");c.drawPath(p,fill=1,stroke=0)
    def dimx(x1,x2,y,edge,label):
        for x in (x1,x2):line(x,edge,x,y-2)
        line(x1,y,x2,y);arrow(x1,y,0);arrow(x2,y,math.pi);text((x1+x2)/2,y+1.5,label,2.8,"center")
    def dimy(y1,y2,x,edge,label):
        for y in (y1,y2):line(edge,y,x-2,y)
        line(x,y1,x,y2);arrow(x,y1,math.pi/2);arrow(x,y2,-math.pi/2)
        c.saveState();c.translate(x-1.5,(y1+y2)/2);c.rotate(90);text(0,0,label,2.8,"center");c.restoreState()
    def paragraph(x,y,value,width,size=2.9,leading=5.5):
        row=""
        for ch in value:
            if ch=="\n" or pdfmetrics.stringWidth(row+ch,font,size)>width:
                text(x,y,row,size);y-=leading;row="" if ch=="\n" else ch
            else:row+=ch
        if row:text(x,y,row,size);y-=leading
        return y
    def frame(page, scale_label="1:2.5"):
        c.scale(MM,MM);rect(8,8,404,281)
        text(16,281,"ZZLAB / 308 nm 激光器安装底板",4.2)
        text(404,281,"加工审核版",4,"right", "#8a520f");line(15,276,405,276)
        rect(15,14,390,35);line(15,28,405,28);line(214,14,214,49)
        text(20,40,f"底板 {w:g} × {h:g} × {t:g} mm",4.2)
        text(20,32,f"材料：{spec['material']}    表面处理：{spec['surfaceTreatment']}",3)
        text(20,19,"仅生成安装底板；不包含外购激光器本体模型",2.8)
        text(220,40,f"图号：{spec['model']}",3)
        text(220,32,"单位：mm / 第一角法 / 图幅 A3",2.8)
        text(220,19,f"第 {page} / 2 页    视图比例 {scale_label}    打印 100%",2.8)
    frame(1)
    s=.4;x0=30;y0=100;front_y=225;side_x=278
    rect(x0,y0,w*s,h*s);rect(x0,front_y,w*s,t*s);rect(side_x,front_y,h*s,t*s)
    text(x0+w*s/2,front_y+t*s+5,"主视图",3.3,"center");text(side_x+h*s/2,front_y+t*s+5,"左视图",3.3,"center")
    text(x0+w*s/2,y0+h*s+14,"俯视图 / 顶面",3.3,"center")
    for key in ("laserThreadHolesMm","boardMountingHolesMm"):
        for hole in spec[key]:
            x=x0+(hole['xMm']-b['xMin'])*s;y=y0+(hole['yMm']-b['yMin'])*s
            radius=spec['thread']['stepDiameterMm']/2 if key=='laserThreadHolesMm' else cb['clearanceDiameterMm']/2
            circle(x,y,radius*s)
            if key=='boardMountingHolesMm':circle(x,y,cb['diameterMm']/2*s)
            else:
                c.setLineWidth(.13);c.arc(x-3*s,y-3*s,x+3*s,y+3*s,startAng=35,extent=285)
            line(x-3,y,x+3,y,[1,.5],.12);line(x,y-3,x,y+3,[1,.5],.12)
            text(x+2,y+(3 if hole['yMm']<0 else -5),hole['label'],2.7)
            for start,coord in ((x0,hole['xMm']-b['xMin']),(side_x,b['yMax']-hole['yMm'])):
                cc=start+coord*s
                for sign in (-1,1):
                    line(cc+sign*radius*s,front_y,cc+sign*radius*s,front_y+t*s,[1,.7],.13)
                    if key=='boardMountingHolesMm':
                        xx=cc+sign*cb['diameterMm']/2*s
                        line(xx,front_y+(t-cb['depthMm'])*s,xx,front_y+t*s,[1,.7],.13)
                if key=='boardMountingHolesMm':line(cc-cb['diameterMm']/2*s,front_y+(t-cb['depthMm'])*s,cc+cb['diameterMm']/2*s,front_y+(t-cb['depthMm'])*s,[1,.7],.13)
    ox=x0-b['xMin']*s;oy=y0-b['yMin']*s
    line(ox-8,oy,ox+15,oy,[3,1,.5,1],.13);line(ox,oy-8,ox,oy+15,[3,1,.5,1],.13)
    arrow(ox+15,oy,math.pi);arrow(ox,oy+15,-math.pi/2)
    text(ox+16,oy,'X',2.7);text(ox+1,oy+16,'Y',2.7);text(ox+2,oy-5,'O (0, 0)',2.7)
    dimx(x0,x0+w*s,86,y0,f'{w:g}');dimy(y0,y0+h*s,20,x0,f'{h:g}');dimy(front_y,front_y+t*s,258,x0+w*s,f'{t:g}')
    port=spec['opticalPortMm'];py=y0+(port['yMm']-b['yMin'])*s
    line(x0,py,x0-10,py);arrow(x0-10,py,0);text(x0+3,py+3,'光口投影',2.6)
    # Hole types stay beside their true projected holes; old coordinate table
    # and datum dimensions remain the location scheme, not duplicated as XYZ.
    for key,threaded in [('boardMountingHolesMm',False),('laserThreadHolesMm',True)]:
        hole=max(spec[key],key=lambda v:(v['yMm'],-v['xMm']))
        hx=x0+(hole['xMm']-b['xMin'])*s;hy=y0+(hole['yMm']-b['yMin'])*s
        radius=3 if threaded else cb['diameterMm']/2
        px,py=hx,hy+radius*s
        tx=174 if threaded else 34;ty=216;ex=tx+7
        line(px,py,ex,ty-2,width=.16);line(ex,ty-2,tx+47,ty-2,width=.16)
        arrow(px,py,math.atan2(ty-2-py,ex-px))
        if threaded:hole_text(tx,ty,'T1–T4: 4× M6×1',2.8)
        else:
            hole_text(tx,ty,f'H1–H4: 4× ⌀{cb["clearanceDiameterMm"]:g} 通',2.8)
            hole_text(tx,ty-5,f'⌴ ⌀{cb["diameterMm"]:g} ↧{cb["depthMm"]:g}  顶面',2.8)
    yy=paragraph(272,205,'孔型与使用说明',123,3.5,6.5)
    for note in ('T1-T4：4-M6×1。', 'H1-H4：4-Ø6.6 通孔，顶面 Ø11 圆柱沉孔深 6.5。',
                 '孔规格见本页短引线；孔位沿用第2页坐标表。原点 O 为激光器主壳体俯视中心投影。',
                 '先固定底板，再安装激光器。壳体可遮住底板固定孔，必须先拧紧 H1-H4。',
                 'STEP 中 M6 螺纹以 Ø5 底孔表示，不含螺旋牙。螺纹按图纸加工。',
                 f'激光器原光轴高 135；叠加本板后距本板底面 {spec["axisHeightMm"]:g}。其他支撑高度另计。'):
        yy=paragraph(272,yy-2,note,123)
    datum='用户已核对孔组基准' if spec['mountingDatumConfirmed'] else ('孔组基准待实物核对（用户填写的基准）' if spec['mountingDatumProvided'] else '孔组基准待实物核对（默认由原三视图估读）')
    paragraph(30,68,datum+'；审核通过后再投产。',365,3.2)
    c.showPage();frame(2)
    text(20,262,'孔位坐标与加工要求',4.3)
    text(20,253,'坐标基准与第 1 页一致；Y 向上。所有尺寸单位 mm。',3)
    cols=[20,38,83,114,145,245]
    for x in cols:line(x,161,x,244)
    for y in [244,233]+[224-i*9 for i in range(8)]:line(20,y,245,y)
    for a,v in zip(cols[:-1],['孔号','孔类型','X','Y','加工标注']):text(a+2,237,v,2.9)
    allholes=[(h,'激光器连接','M6×1') for h in spec['laserThreadHolesMm']]
    allholes += [(h,'主板固定','Ø6.6 通 / Ø11 深6.5') for h in spec['boardMountingHolesMm']]
    for index,(hole,kind,callout) in enumerate(allholes):
        y=227-index*9
        for x,val in zip(cols[:-1],[hole['label'],kind,f"{hole['xMm']:g}",f"{hole['yMm']:g}",callout]):text(x+2,y,val,2.85)
    text(270,259,'H1-H4 顶面圆柱沉孔剖面',3.3)
    ds=min(1.6,55/t);xx=326;top=235;bottom=top-t*ds;half=16
    for sign in (-1,1):
        wide=xx+sign*cb['diameterMm']/2*ds;narrow=xx+sign*cb['clearanceDiameterMm']/2*ds
        line(xx+sign*half,top,wide,top)
        line(xx+sign*half,top,xx+sign*half,bottom)
        line(xx+sign*half,bottom,narrow,bottom)
        line(wide,top,wide,top-cb['depthMm']*ds)
        line(wide,top-cb['depthMm']*ds,narrow,top-cb['depthMm']*ds)
        line(narrow,top-cb['depthMm']*ds,narrow,bottom)
    line(xx,top+5,xx,bottom-5,[4,1,.5,1],.13)
    dimx(xx-5.5*ds,xx+5.5*ds,top+11,top,'Ø11')
    dimx(xx-3.3*ds,xx+3.3*ds,bottom-12,bottom,'Ø6.6')
    dimy(top-cb['depthMm']*ds,top,356,xx+half,'6.5')
    dimy(bottom,top,380,xx+half,f'{t:g}')
    text(278,bottom-22,f'剖面示意 / 比例 {ds:g}:1',2.8)
    yy=151
    details=[datum+'。',
             f'当前 T1 孔组基准：X={spec["mountingOriginXMm"]:g}，Y={spec["mountingOriginYMm"]:g}；四孔矩形间距 50 × 250。',
             '原图安装通槽标注 6.4 × 7.4 贯穿；绝对孔组基准仍须与实物配合核对。本底板加工 M6 螺纹孔，不复制激光器通槽。',
             '底板外形 X：-283 至 260；Y：-130.5 至 130.5。原点距底板左边 283、下边 130.5。',
             f'光口投影参考：X={port["xMm"]:g}，Y={port["yMm"]:g}，出光方向 -X；该位置不是加工孔。',
             '装配顺序：先将底板 H1-H4 固定于主面包板，再从激光器脚部装入连接 T1-T4 的螺钉。螺钉长度由实际叠层与啮合要求确定。',
             '按图面标注加工并去除锐边毛刺；孔表仅作补充；材料和表面处理见标题栏。孔组基准与实物匹配后再投产。']
    for note in details:yy=paragraph(20,yy,note,380,2.9,5.2)-2
    c.save()
    return {"drawingRevision":"thread-designation-only-20261026","pageCount":2}


def generate(raw_spec, out, drawing_only=False):
    spec = validate_adapter_spec(raw_spec)
    out = Path(out);out.mkdir(parents=True, exist_ok=True)
    stem = spec['filenameStem']
    paths = {k:out/(stem+ext) for k,ext in {'step':'.step','drawing':'.pdf','holeSpec':'.json','topView':'.svg'}.items()}
    if drawing_only:
        previous=json.loads((out/'artifact.json').read_text())
        assert previous['spec']==spec and previous['sha256']['step']==hashlib.sha256(paths['step'].read_bytes()).hexdigest()
        validation=previous['geometryValidation']
    else:validation = make_model(spec,paths['step'])
    drawing=make_pdf(spec,paths['drawing'])
    paths['holeSpec'].write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    paths['topView'].write_text(make_topview(spec),encoding='utf-8')
    report = {'digest':spec['digest'],'generatorVersion':spec['generatorVersion'],'spec':spec,
              'geometryValidation':validation,'drawing':drawing,'sha256':{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}}
    (out/'artifact.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--drawing-only',action='store_true')
    args=parser.parse_args();generate(json.loads(Path(args.request).read_text()),args.out,args.drawing_only)
