"""Trusted, local planning board packs; never read geometry from user projects."""
from pathlib import Path
import json, hashlib, base64, html, math
from registered_boards import validate_catalog_boards

def extend_catalog(catalog, root):
    path=Path(root)/'local-boards.json'
    if not path.exists():return catalog
    raw=path.read_bytes();pack=json.loads(raw)
    if pack.get('format')!='zzlab-local-board-pack-v1':raise ValueError('Unknown local board pack')
    rows=pack.get('registeredBoards',[])
    if not isinstance(rows,list) or len(rows)>16:raise ValueError('Invalid local board count')
    known={r['id'] for r in catalog.get('registeredBoards',[])}
    for r in rows:
        if r['id'] in known:raise ValueError('Local pack cannot replace upstream boards')
        if r.get('planningOnly') is not True:raise ValueError('Local board pack is planning only')
        assets=[r['topViewPath']]
        for a in r.get('fixedAccessories',[]):
            if a.get('positionLocked') is not True:raise ValueError('Board accessories must be fixed')
            b=a['imageBoundsMm']
            if set(b)!={'xMin','yMin','xMax','yMax'} or any(type(v) not in (int,float) or not math.isfinite(v) for v in b.values()) or not (0<=b['xMin']<b['xMax']<=r['widthMm'] and 0<=b['yMin']<b['yMax']<=r['heightMm']):raise ValueError('Invalid accessory bounds')
            assets.append(a['topViewPath'])
        for rel in assets:
            if not rel.startswith('local-boards/') or Path(rel).suffix not in ('.svg','.png') or '..' in Path(rel).parts or not (Path(root)/'static'/rel).is_file():raise ValueError('Missing local board asset '+rel)
    result={**catalog,'registeredBoards':[*catalog.get('registeredBoards',[]),*rows], 'localBoardPacks':[{'revision':pack['revision'],'sha256':hashlib.sha256(raw).hexdigest(),'planningOnly':True}]}
    validate_catalog_boards(result)
    return result

def accessory_markup(board, row):
    result=[];height=board['heightMm'];esc=lambda t:html.escape(str(t),quote=True)
    for a in row.get('fixedAccessories',[]):
        b=a['imageBoundsMm'];p=Path(__file__).parent/'static'/a['topViewPath']
        data=base64.b64encode(p.read_bytes()).decode();mime='image/svg+xml' if p.suffix=='.svg' else 'image/png'
        result.append(f'<g data-fixed-accessory="{esc(a["id"])}" pointer-events="none"><title>{esc(a["name"])} · 主板固定附件</title><image x="{b["xMin"]}" y="{height-b["yMax"]}" width="{b["xMax"]-b["xMin"]}" height="{b["yMax"]-b["yMin"]}" href="data:{mime};base64,{data}"/></g>')
    inset=row.get('coverInsetMm')
    if inset:result.append(f'<rect x="{inset}" y="{inset}" width="{board["widthMm"]-2*inset}" height="{height-2*inset}" fill="none" stroke="#ba8242" stroke-width=".6" stroke-dasharray="4 3"/>')
    return ''.join(result)

def beam_markup(board,row):
    beam=row.get('referenceBeam')
    if not beam:return ''
    h=board['heightMm'];pts=beam['pointsMm'];d=' '.join(f'{"M" if n==0 else "L"} {x} {h-y}' for n,(x,y) in enumerate(pts));x,y=pts[-1]
    lx,ly=beam.get('labelPointMm',[590,y+6])
    label=html.escape(f"{beam['wavelengthNm']} nm · Y={y:g} · Z={beam['outputHeightMm']:g} · 名义光路参考")
    return f'<g data-fixed-reference-beam="true" pointer-events="none"><path d="{d}" fill="none" stroke="#13ad36" stroke-width="1.1"/><path d="M{x-5} {h-y-3} L{x} {h-y} L{x-5} {h-y+3}" fill="none" stroke="#13ad36" stroke-width="1.1"/><text x="{lx}" y="{h-ly}" font-size="6.5" fill="#087c29" stroke="white" stroke-width="1.3" paint-order="stroke">{label}</text></g>'

def layout_warnings(layout,catalog):
    board=layout.get('board',{});r=next((r for r in catalog.get('registeredBoards',[]) if r['id']==board.get('registeredBoardId') and r['revision']==board.get('registeredBoardRevision')),None)
    if not r or not r.get('fixedAccessories'):return []
    warnings=[]
    for p in layout.get('subBoards',[]):
        w,h=p['board']['widthMm'],p['board']['heightMm'];a=math.radians(p['rotationDeg']);c,s=round(math.cos(a)),round(math.sin(a));pts=[(p['xMm']+c*x-s*y,p['yMm']+s*x+c*y) for x,y in [(0,0),(w,0),(w,h),(0,h)]];b=(min(x for x,y in pts),min(y for x,y in pts),max(x for x,y in pts),max(y for x,y in pts))
        for acc in r['fixedAccessories']:
            q=acc['imageBoundsMm']
            if min(b[2],q['xMax'])>max(b[0],q['xMin']) and min(b[3],q['yMax'])>max(b[1],q['yMin']):warnings.append({'code':'fixed_accessory_overlap','boardId':p['id'],'instanceIds':[],'severity':'warning','message':p['name']+' 与主板固定附件「'+acc['name']+'」的俯视包络重叠。'})
        margin=r.get('coverInsetMm',0)
        if b[0]<margin or b[1]<margin or b[2]>r['widthMm']-margin or b[3]>r['heightMm']-margin:warnings.append({'code':'cover_reservation_overlap','boardId':p['id'],'instanceIds':[],'severity':'warning','message':p['name']+f' 占用了 {margin} mm 罩子预留区。'})
    return warnings
