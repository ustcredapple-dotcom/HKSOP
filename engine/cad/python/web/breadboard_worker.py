"""Isolated OpenCascade/reportlab worker for a new parameterized breadboard."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

from breadboard import board_specs, GENERATOR_VERSION
from OCP.BRep import BRep_Tool, BRep_Builder
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
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

MM = 72 / 25.4
FONT = 'ZZLabChinese'


def positions(spec):
    b=spec['board'];e,p=b['edgeOffsetMm'],b['pitchMm']
    return ([round(e+i*p,6) for i in range(spec['gridColumns'])],
            [round(e+j*p,6) for j in range(spec['gridRows'])])


def make_model(spec, path):
    b=spec['board'];w,h,t,d=b['widthMm'],b['heightMm'],b['thicknessMm'],b['holeDiameterMm']
    # Extrude one planar face with exact circular inner wires. This avoids a
    # costly chain of thousands of Boolean cuts and preserves one valid solid.
    polygon=BRepBuilderAPI_MakePolygon()
    for x,y in ((0,0),(w,0),(w,h),(0,h)):polygon.Add(gp_Pnt(x,y,0))
    polygon.Close();face=BRepBuilderAPI_MakeFace(polygon.Wire(),True)
    xs,ys=positions(spec)
    mounting={(p['columnIndex'],p['rowIndex']) for p in spec['mountingHoles']}
    cb=spec['counterbore']
    for j,y in enumerate(ys):
        for i,x in enumerate(xs):
            diameter=cb['clearanceDiameterMm'] if (i,j) in mounting else d
            edge=BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(x,y,0),gp_Dir(0,0,1)),diameter/2)).Edge()
            wire=BRepBuilderAPI_MakeWire(edge).Wire();wire.Reverse();face.Add(wire)
    body=BRepPrimAPI_MakePrism(face.Face(),gp_Vec(0,0,-t),False,True).Shape()
    if mounting:
        # One Boolean for the four cylindrical top recesses. The matching
        # clearance holes already replace their ordinary grid-hole wires.
        compound=TopoDS_Compound();builder=BRep_Builder();builder.MakeCompound(compound)
        for hole in spec['mountingHoles']:
            tool=BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(hole['xMm'],hole['yMm'],.1),gp_Dir(0,0,-1)),cb['diameterMm']/2,cb['depthMm']+.1).Shape()
            builder.Add(compound,tool)
        cut=BRepAlgoAPI_Cut(body,compound)
        if not cut.IsDone():raise RuntimeError('Counterbore cut did not complete')
        body=cut.Shape()
    if not BRepCheck_Analyzer(body,True).IsValid():raise RuntimeError('Generated plate is not a valid B-rep')
    ex=TopExp_Explorer(body,TopAbs_SOLID);solids=0
    while ex.More():solids+=1;ex.Next()
    if solids!=1:raise RuntimeError('Generated plate must contain one solid')
    ex=TopExp_Explorer(body,TopAbs_FACE);cylinders=0
    while ex.More():
        surf=BRepAdaptor_Surface(TopoDS.Face(ex.Current()),True)
        if surf.GetType()==GeomAbs_Cylinder:cylinders+=1
        ex.Next()
    if cylinders!=spec['holeCount']+spec['mountingHoleCount']:raise RuntimeError('Generated cylindrical face count differs from hole scheme')
    mass=GProp_GProps();BRepGProp.VolumeProperties_s(body,mass)
    expected=(w*h-spec['regularHoleCount']*math.pi*(d/2)**2-spec['mountingHoleCount']*math.pi*(cb['clearanceDiameterMm']/2)**2)*t
    expected-=spec['mountingHoleCount']*math.pi*((cb['diameterMm']/2)**2-(cb['clearanceDiameterMm']/2)**2)*cb['depthMm']
    if abs(mass.Mass()-expected)>max(.001,expected*1e-9):raise RuntimeError('Generated plate volume differs from analytic hole volume')
    Interface_Static.SetCVal_s('write.step.schema','AP214IS')
    Interface_Static.SetCVal_s('write.step.unit','MM')
    writer=STEPControl_Writer()
    if writer.Transfer(body,STEPControl_AsIs)!=IFSelect_RetDone or writer.Write(str(path))!=IFSelect_RetDone:
        raise RuntimeError('STEP export failed')
    # Stabilize the header timestamp; the generator version identifies the model
    # revision. Cached geometry and all drawing content are parameter-determined.
    step=path.read_text()
    step=re.sub(r"(FILE_NAME\([^,]*,\s*)'[^']*'",r"\1'2026-09-23T00:00:00'",step,count=1,flags=re.S)
    step=step.replace("'Open CASCADE Shape Model'",f"'{spec['model']}'",1)
    step=re.sub(r"'Open CASCADE STEP translator [^']*'",f"'{spec['model']}'",step)
    path.write_text(step)
    return {'solidCount':solids,'cylindricalHoleFaces':cylinders,'regularHoleCount':spec['regularHoleCount'],'mountingHoleCount':spec['mountingHoleCount'],'volumeMm3':mass.Mass(),'analyticVolumeMm3':expected,'valid':True}


def font_init():
    font_path=Path(os.environ.get('ZZLAB_CAD_FONT','/System/Library/Fonts/STHeiti Light.ttc'))
    if font_path.is_file():pdfmetrics.registerFont(TTFont(FONT,str(font_path),subfontIndex=0))
    else:pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'));return 'STSong-Light'
    return FONT


def make_pdf(spec,path):
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
    b=spec['board'];w,h,t,p,d=b['widthMm'],b['heightMm'],b['thicknessMm'],b['pitchMm'],b['holeDiameterMm']
    mounts=spec['mountingHoles'];mounting={(v['columnIndex'],v['rowIndex']):v for v in mounts};cb=spec['counterbore']
    pages=2 if mounts else 1
    font=font_init();c=canvas.Canvas(str(path),pagesize=(420*MM,297*MM),pageCompression=1,invariant=1)
    c.setTitle(spec['model']+' 参数面包板三视图');c.setAuthor('ZZLab');c.setSubject('新参数板加工审核图')
    c.scale(MM,MM)
    def text(x,y,s,size=3.0,color='#172c34',align='left'):
        c.setFillColor(color);c.setFont(font,size)
        (c.drawRightString if align=='right' else c.drawCentredString if align=='center' else c.drawString)(x,y,str(s))
    def line(x1,y1,x2,y2,width=.2,dash=None,color='#172c34'):
        c.setStrokeColor(color);c.setLineWidth(width);c.setDash(dash or [])
        c.line(x1,y1,x2,y2);c.setDash([])
    def rect(x,y,ww,hh,width=.32,fill=None):
        c.setStrokeColor('#172c34');c.setLineWidth(width)
        if fill:c.setFillColor(fill)
        c.rect(x,y,ww,hh,stroke=1,fill=bool(fill))
    def arrow(x,y,angle,size=1.5):
        ca,sa=math.cos(angle),math.sin(angle)
        pp=c.beginPath();pp.moveTo(x,y);pp.lineTo(x+size*ca+.38*sa,y+size*sa-.38*ca);pp.lineTo(x+size*ca-.38*sa,y+size*sa+.38*ca);pp.close()
        c.setFillColor('#172c34');c.drawPath(pp,stroke=0,fill=1)
    def dimx(x1,x2,y,yedge,label):
        for xx in (x1,x2):line(xx,yedge-1 if y<yedge else yedge+1,xx,y-2 if y<yedge else y+2,.14)
        line(x1,y,x2,y,.16);arrow(x1,y,0);arrow(x2,y,math.pi);text((x1+x2)/2,y+1.5,label,2.9,align='center')
    def dimy(y1,y2,x,xedge,label):
        for yy in (y1,y2):line(xedge-1 if x<xedge else xedge+1,yy,x-2 if x<xedge else x+2,yy,.14)
        line(x,y1,x,y2,.16);arrow(x,y1,math.pi/2);arrow(x,y2,-math.pi/2)
        c.saveState();c.translate(x-1.5,(y1+y2)/2);c.rotate(90);text(0,0,label,2.9,align='center');c.restoreState()
    def paragraph(x,y,s,width,size=2.75,leading=4.8):
        row=''
        for ch in s:
            if ch=='\n' or (pdfmetrics.stringWidth(row+ch,font,size)>width and ch not in '。，；、）'):
                text(x,y,row,size);y-=leading;row='' if ch=='\n' else ch
            else:row+=ch
        if row:text(x,y,row,size);y-=leading
        return y
    def titleblock(page,scale_text):
        rect(15,14,390,35,.35);line(15,28,405,28,.2);line(215,14,215,49,.2);line(320,14,320,49,.2)
        text(20,40,'参数面包板',5.0);text(20,32.5,f'{w:g} × {h:g} × {t:g} mm',3.6)
        text(20,19.5,'新参数模型 / 原 Onshape 设计保持不变',2.7)
        text(220,41,f'图号：{spec["model"]}',2.7);text(220,33.5,'状态：加工审核版',2.7,color='#8a520f')
        text(220,19.5,'单位：mm   投影：第一角法',2.7)
        text(325,41,f'比例：{scale_text}   图幅：A3',2.9);text(325,33.5,f'第 {page} 张 / 共 {pages} 张',2.8)
        text(325,19.5,'打印请使用实际大小 / 100%',2.7)
    rect(8,8,404,281,.5)
    text(15,281,'ZZLAB / 光路模块化',3.4,color='#16736f')
    text(405,281,'新参数面包板 · 加工审核版',4.5,align='right')
    line(15,277,405,277,.25)
    limit=min(230/w,130/h,340/(w+h),22/t,2)
    scale=next(s for s in (2,1,.5,.4,.25,.2,.1,.05,.04,.025,.02,.01) if s<=limit+1e-9)
    scale_text=f'{scale:g}:1' if scale>=1 else f'1:{1/scale:g}'
    x0=28;y0=216-h*scale;xs,ys=positions(spec)
    # Front XZ and left view YZ above the plan: explicit first-angle projection.
    yfront=245;right_start=x0+w*scale+28
    for xx,ww,label in ((x0,w*scale,'主视图'),(right_start,h*scale,'左视图')):
        rect(xx,yfront,ww,t*scale,.35);text(xx+ww/2,yfront+t*scale+4,label,3.2,align='center')
    for axis,coordinates,start,reverse in (('columnIndex',xs,x0,False),('rowIndex',ys,right_start,True)):
        for i,coordinate in enumerate(coordinates):
            # Ordinary and counterbored holes at the same projected position
            # both remain visible as hidden edges where applicable.
            count=sum(v[axis]==i for v in mounts)
            ordinary_count=(len(ys) if axis=='columnIndex' else len(xs))-count
            center=(h-coordinate) if reverse else coordinate
            for diameter,depth in ([(d,t)] if ordinary_count else [])+([(cb['clearanceDiameterMm'],t-cb['depthMm'])] if count else []):
                for sign in (-1,1):line(start+(center+sign*diameter/2)*scale,yfront,start+(center+sign*diameter/2)*scale,yfront+depth*scale,.10,[1.2,.8],color='#647077')
            if count:
                floor=yfront+(t-cb['depthMm'])*scale
                for sign in (-1,1):line(start+(center+sign*cb['diameterMm']/2)*scale,floor,start+(center+sign*cb['diameterMm']/2)*scale,yfront+t*scale,.12,[1.2,.8])
                for sign in (-1,1):line(start+(center+sign*cb['clearanceDiameterMm']/2)*scale,floor,start+(center+sign*cb['diameterMm']/2)*scale,floor,.12,[1.2,.8])
    # Thickness dimension uses outside arrows when the projected plate is thin.
    dx=x0+w*scale+7
    line(x0+w*scale+1,yfront,dx+2,yfront,.14);line(x0+w*scale+1,yfront+t*scale,dx+2,yfront+t*scale,.14)
    line(dx,yfront-3,dx,yfront+t*scale+3,.16);arrow(dx,yfront,-math.pi/2);arrow(dx,yfront+t*scale,math.pi/2)
    text(dx+2,yfront+t*scale/2-1.0,f'{t:g}',2.9)
    # Top view: exact circle centers and grid, simplified thread symbol.
    rect(x0,y0,w*scale,h*scale,.4)
    for j,yy in enumerate(ys):
        for i,xx in enumerate(xs):
            x,y=x0+xx*scale,y0+yy*scale
            diameter=cb['clearanceDiameterMm'] if (i,j) in mounting else d
            c.setLineWidth(.18);c.setStrokeColor('#172c34');c.circle(x,y,diameter/2*scale,stroke=1,fill=0)
            if (i,j) in mounting:
                c.setLineWidth(.25);c.circle(x,y,cb['diameterMm']/2*scale,stroke=1,fill=0)
                # Full callouts and coordinates have a separate legible plan sheet.
            elif b['holeType']=='M6_through':
                r=3*scale;c.setLineWidth(.10);c.arc(x-r,y-r,x+r,y+r,startAng=45,extent=270)
    text(x0+w*scale/2,235 if mounts else 223,'俯视图',3.2,align='center')
    dimx(x0,x0+w*scale,y0-10,y0,f'{w:g}')
    dimy(y0,y0+h*scale,x0-12,x0,f'{h:g}')
    # Coordinate datum cross and hole-array relation supplement small edge gaps.
    line(x0,y0,x0+8,y0,.25);arrow(x0+8,y0,math.pi,1.2);text(x0+9,y0-1.2,'X',2.5)
    line(x0,y0,x0,y0+8,.25);arrow(x0,y0+8,-math.pi/2,1.2);text(x0-1.1,y0+9,'Y',2.5)
    text(x0-3,y0-3.8,'O',2.5)
    text(x0,y0-18,f'{spec["regularHoleCount"]} × {spec["holeCallout"]}'+(f'；另 {len(mounts)} 个安装沉孔 H1-H{len(mounts)}，见第 2 张' if mounts else '，等距矩形孔阵'),3.0)
    text(x0,y0-24,f'X(i) = {b["edgeOffsetMm"]:g} + (i-1) × {p:g}，i = 1…{spec["gridColumns"]}',2.8)
    text(x0,y0-30,f'Y(j) = {b["edgeOffsetMm"]:g} + (j-1) × {p:g}，j = 1…{spec["gridRows"]}',2.8)
    # Compact group callouts use the existing view and grid/datum scheme.
    if spec['regularHoleCount']:
        i,j=min(((i,j) for i in range(len(xs)) for j in range(len(ys)) if (i,j) not in mounting),key=lambda z:(-ys[z[1]],xs[z[0]]))
        hx,hy=x0+xs[i]*scale,y0+ys[j]*scale
        px,py=hx,hy+d/2*scale;tx=x0+7;ty=227
        ex=max(tx+4,min(hx+7,x0+55))
        line(px,py,ex,ty-2,.16);line(ex,ty-2,tx+48,ty-2,.16)
        arrow(px,py,math.atan2(ty-2-py,ex-px),1.2)
        co=spec['holeCallout'].replace('通螺纹','').replace('通孔','通')
        hole_text(tx,ty,f'{spec["regularHoleCount"]}× {co}',2.8)
        if mounts:text(tx,ty-5,f'普通阵列孔（H1–H{len(mounts)}除外）',2.5)
    if mounts:
        for v in mounts:
            hx,hy=x0+v['xMm']*scale,y0+v['yMm']*scale
            text(hx+cb['diameterMm']/2*scale+1,hy+1,v['label'],2.3)
        v=max(mounts,key=lambda v:(v['yMm'],v['xMm']))
        hx,hy=x0+v['xMm']*scale,y0+v['yMm']*scale
        px,py=hx,hy+cb['diameterMm']/2*scale
        tx=x0+w*scale-62;ty=227;ex=max(tx+4,hx+4)
        line(px,py,ex,ty-2,.16);line(ex,ty-2,tx+58,ty-2,.16)
        arrow(px,py,math.atan2(ty-2-py,ex-px),1.2)
        hole_text(tx,ty,f'H1–H{len(mounts)}: {len(mounts)}× ⌀{cb["clearanceDiameterMm"]:g} 通',2.7)
        hole_text(tx,ty-5,f'⌴ ⌀{cb["diameterMm"]:g} ↧{cb["depthMm"]:g}  顶面',2.7)
    # Right-hand specification panel has readable dimensions even at small scale.
    rx,rw,ry=278,120,215
    rect(rx,ry-8,rw,8,.25,fill='#edf4f2');text(rx+3,ry-5.5,'孔阵列与制造参数',3.3)
    rows=[('外形 / mm',f'{w:g} × {h:g} × {t:g}'),('普通阵列孔',f'{spec["regularHoleCount"]} × '+spec['holeCallout']),
          ('列数 × 行数',f'{spec["gridColumns"]} × {spec["gridRows"]} = {spec["holeCount"]} 孔'),
          ('X / Y 孔距',f'{p:g} / {p:g} mm'),('左 / 下首孔边距',f'{b["edgeOffsetMm"]:g} / {b["edgeOffsetMm"]:g} mm'),
          ('右 / 上末孔边距',f'{spec["rightMarginMm"]:g} / {spec["topMarginMm"]:g} mm'),
          ('安装沉孔' if mounts else '孔径几何',f'{len(mounts)} × Ø6.6 通；Ø11 深 6.5' if mounts else f'Ø{d:g} 通孔'+('（螺纹简化底孔）' if b['holeType']=='M6_through' else '')),
          ('材料',spec['material']),('表面处理',spec['surfaceTreatment']),('螺纹等级',spec['threadClass'])]
    yy=ry-8
    for label,value in rows:
        rect(rx,yy-8,rw,8,.15);line(rx+43,yy-8,rx+43,yy,.15)
        text(rx+3,yy-5.5,label,2.7);text(rx+46,yy-5.5,value,2.65);yy-=8
    yy-=8;text(rx,yy,'技术说明',3.3);yy-=6
    notes=[
      '1. 本图对应网页新建参数板；'+(f'H1-H{len(mounts)} 为安装沉孔，替换对应普通孔，孔位总数不增加。' if mounts else '全阵列采用同一孔型，不复刻原归档面包板的角部沉孔。'),
      '2. 孔中心坐标以俯视图左下角 O 为基准；边距按首孔与末孔实际位置标注。',
      '3. 新模型坐标：板面 XY；顶面 Z=0，底面 Z=-厚度。',
    ]
    if b['holeType']=='M6_through':notes.append('4. '+(f'除 H1-H{len(mounts)} 外，' if mounts else '')+'阵列孔为 M6×1.00。STEP 仅用 Ø5 通底孔简化表示，不建螺旋牙；以本图螺纹标注加工。')
    else:notes.append('4. '+(f'除 H1-H{len(mounts)} 外，' if mounts else '')+'阵列孔均为标注直径的普通通孔，无螺纹。')
    notes.append('5. 材料与表面处理按本图制造参数执行。'+('螺纹等级待确认。' if b['holeType']=='M6_through' else ''))
    for note in notes:yy=paragraph(rx,yy,note,rw,2.65,4.2)-1
    # Fixed title block; no guessed material, finish or tolerance.
    titleblock(1,scale_text)
    c.showPage()
    if mounts:
        c.scale(MM,MM)
        rect(8,8,404,281,.5);text(15,281,'ZZLAB / 光路模块化',3.4,color='#16736f')
        text(405,281,'安装孔孔位与圆柱沉孔详图',4.5,align='right');line(15,277,405,277,.25)
        text(22,261,f'{len(mounts)} × M6 圆柱头螺钉安装孔',4.3)
        text(22,252,'Ø6.6 通孔；顶面 Ø11 圆柱沉孔，深 6.5 mm',3.7)
        text(22,243,'孔中心坐标：从板左下角 O 量取，X 向右、Y 向上，单位 mm',3.1)
        # Mounting-hole coordinates; indices shown 1-based to the machinist.
        columns=[22,44,72,100,145,190];yy=235
        for row in [('孔号','列号','行号','X / mm','Y / mm')]+[(v['label'],v['columnIndex']+1,v['rowIndex']+1,f'{v["xMm"]:g}',f'{v["yMm"]:g}') for v in mounts]:
            rect(columns[0],yy-10,columns[-1]-columns[0],10,.2)
            for xx in columns[1:-1]:line(xx,yy-10,xx,yy,.15)
            for i,value in enumerate(row):text(columns[i]+3,yy-6.5,value,3.1)
            yy-=10
        yy-=9
        for note in [
            f'{len(mounts)}个安装孔替换对应普通孔。不得在这些位置继续攻 M6 螺纹。',
            '每组四孔内 X/Y 坐标差为25 mm整数倍；八孔时为奇偶相反的两组，组间不受此限。',
            f'沉孔底部余厚 = {t:g} - 6.5 = {t-6.5:g} mm。安装孔上表面开口，沉孔底面为平面。',
            '适配 ISO 4762 / DIN 912 M6 内六角圆柱头螺钉：头部公称 Ø10、高 6，名义下沉量 0.5 mm。',
            '本孔方案按无垫圈设置。螺钉长度、等级、材质及下方螺纹啮合长度须按实际装配选定。',
            '2 mm 边壁/底厚下限仅为本工具的几何规则；安装受力与强度要求仍待确认。',
        ]:yy=paragraph(22,yy,note,168,3.0,5.0)-3
        # Longitudinal section through one representative stepped hole.
        ds=2 if t<=25 else 1; cx=297; ybottom=190; ytop=ybottom+t*ds; floor=ytop-cb['depthMm']*ds
        outer=19; rr=cb['diameterMm']/2*ds;rt=cb['clearanceDiameterMm']/2*ds
        for sign in (-1,1):
            pp=c.beginPath();pp.moveTo(cx+sign*outer,ytop);pp.lineTo(cx+sign*rr,ytop);pp.lineTo(cx+sign*rr,floor);pp.lineTo(cx+sign*rt,floor);pp.lineTo(cx+sign*rt,ybottom);pp.lineTo(cx+sign*outer,ybottom);pp.close()
            c.setFillColor('#e8eeec');c.setStrokeColor('#172c34');c.setLineWidth(.4);c.drawPath(pp,stroke=1,fill=1)
        line(cx,ytop+1,cx,ybottom-1,.15,[5,1,1,1])
        dimx(cx-rr,cx+rr,ytop+9,ytop,'Ø11')
        dimx(cx-rt,cx+rt,ybottom-9,ybottom,'Ø6.6 通')
        dimy(floor,ytop,cx+outer+12,cx+outer,'6.5 深')
        dimy(ybottom,ytop,cx-outer-12,cx-outer,f'{t:g}')
        text(cx,ytop+20,f'H1-H{len(mounts)} 共用局部剖面  {ds}:1',3.7,align='center')
        text(cx,ytop+3,'顶面 Z=0',2.8,align='center')
        text(cx,ybottom-20,'圆柱沉孔 / 平底',3.2,align='center')
        text(cx,ybottom-27,'不可加工为锥形沉头孔',3.2,align='center')
        yy=143
        for note in ['尺寸依据：MISUMI Brackets for Stands，M6 安装孔 d=6.6、d1=11、Z=6.5。',
                     f'材料：{spec["material"]}；表面处理：{spec["surfaceTreatment"]}。'+('螺纹等级待确认。' if b['holeType']=='M6_through' else ''),
                     '本页未标注的外形、普通孔和孔阵参数见第 1 张。']:
            yy=paragraph(227,yy,note,171,3.0,5.2)-5
        text(227,yy,'来源：MISUMI 2019_US_2250.pdf',2.65,color='#16736f')
        c.linkURL(spec['counterboreSourceUrl'],(227,yy-1,392,yy+4),relative=1,thickness=0)
        titleblock(2,f'局部 {ds}:1')
        c.showPage()
    c.save()
    return {'pageCount':pages,'paper':'A3 landscape','scale':scale,'projection':'first-angle','font':font,'drawingRevision':'thread-designation-only-20261026'}


def generate(board,out,drawing_only=False):
    started=time.monotonic();spec=board_specs(board);out.mkdir(parents=True,exist_ok=True)
    step=out/(spec['filenameStem']+'.step');pdf=out/(spec['filenameStem']+'.pdf')
    if drawing_only:
        previous=json.loads((out/'artifact.json').read_text())
        assert previous['digest']==spec['digest'] and previous['sha256']['step']==hashlib.sha256(step.read_bytes()).hexdigest()
        geometry=previous['geometryValidation']
    else:geometry=make_model(spec,step)
    drawing=make_pdf(spec,pdf)
    meta={'digest':spec['digest'],'generatorVersion':spec['generatorVersion'],'spec':spec,'geometryValidation':geometry,'drawing':drawing,
          'elapsedSeconds':time.monotonic()-started,'sha256':{'step':hashlib.sha256(step.read_bytes()).hexdigest(),'drawing':hashlib.sha256(pdf.read_bytes()).hexdigest()}}
    (out/'artifact.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    return meta


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--request',required=True,type=Path);ap.add_argument('--out',required=True,type=Path);ap.add_argument('--drawing-only',action='store_true');a=ap.parse_args()
    m=generate(json.loads(a.request.read_text()),a.out,a.drawing_only);print(json.dumps({'ok':True,'elapsedSeconds':m['elapsedSeconds'],'holeCount':m['spec']['holeCount']},ensure_ascii=False))
