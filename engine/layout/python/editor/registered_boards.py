"""Trusted, immutable Onshape board geometry; project files contain references only.

Coordinates are millimetres from the lower-left bounding box, +X right, +Y up.
Registered plates never enter the rectangular parametric CAD generator.
"""
from __future__ import annotations

from copy import deepcopy
from contextvars import ContextVar
from functools import lru_cache, wraps
import hashlib
import html
import inspect
import json
import math
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name('catalog.json')
EPS = 1e-6
REFERENCE_FIELDS = {'registeredBoardId', 'registeredBoardRevision'}
COMPATIBILITY_FIELDS = {'widthMm','heightMm','thicknessMm','pitchMm','edgeOffsetMm','holeType','holeDiameterMm','thread'}
_ACTIVE_CATALOG = ContextVar('registered_board_catalog', default=None)


def catalog_operation(function):
    """Use the server-supplied catalog for one call without cross-request state."""
    index=list(inspect.signature(function).parameters).index('catalog')
    @wraps(function)
    def wrapped(*args,**kwargs):
        catalog=kwargs.get('catalog',args[index] if len(args)>index else None)
        token=_ACTIVE_CATALOG.set(catalog)
        try:return function(*args,**kwargs)
        finally:_ACTIVE_CATALOG.reset(token)
    return wrapped


class RegisteredBoardError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def registered(board):
    return isinstance(board, dict) and bool(REFERENCE_FIELDS & board.keys())


@lru_cache(maxsize=8)
def _catalog(path, mtime, size):
    value = json.loads(Path(path).read_text())
    validate_catalog_boards(value)
    return {row['id']: row for row in value.get('registeredBoards', [])}


def validate_catalog_boards(catalog):
    rows=catalog.get('registeredBoards',[])
    if not isinstance(rows,list) or len(rows)>128:raise ValueError('registeredBoards应为最多128个可信板型。')
    ids=set()
    def number(value,low,high):return type(value) in (int,float) and math.isfinite(value) and low<=value<=high
    def identifier(value):return isinstance(value,str) and 0<len(value)<=160 and value.strip()==value and not any(ord(c)<32 for c in value)
    for row in rows:
        if not isinstance(row,dict) or not all(identifier(row.get(k)) for k in ('id','revision','name')) or row['id'] in ids:raise ValueError('登记板型编号、版本及名称无效或重复。')
        ids.add(row['id'])
        if not all(number(row.get(k),low,high) for k,low,high in [('widthMm',1,3000),('heightMm',1,3000),('thicknessMm',.1,100),('pitchMm',1,100),('edgeOffsetMm',0,100)]):raise ValueError('登记板型尺寸无效。')
        rings=[row.get('outlineMm'),*row.get('cutoutsMm',[])] if isinstance(row.get('cutoutsMm',[]),list) else []
        if not rings or len(rings)>65 or any(not isinstance(r,list) or not 3<=len(r)<=2048 for r in rings) or sum(map(len,rings))>8192:raise ValueError('登记板型轮廓点数无效。')
        for ring in rings:
            if any(not isinstance(p,dict) or set(p)!={'xMm','yMm'} or not number(p['xMm'],-EPS,row['widthMm']+EPS) or not number(p['yMm'],-EPS,row['heightMm']+EPS) for p in ring):raise ValueError('登记板型轮廓坐标超出尺寸范围。')
            poly=[(p['xMm'],p['yMm']) for p in ring]
            if abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in _edges(poly)))<=EPS:raise ValueError('登记板型轮廓面积为零。')
        holes=row.get('holesMm');seen=set();points=set()
        if not isinstance(holes,list) or len(holes)>2500:raise ValueError('登记板型最多2500个实际孔。')
        for h in holes:
            if not isinstance(h,dict) or not identifier(h.get('id')) or h['id'] in seen or h.get('type') not in ('thread','clearance','counterbore') or not number(h.get('xMm'),0,row['widthMm']) or not number(h.get('yMm'),0,row['heightMm']) or not number(h.get('diameterMm'),.01,100):raise ValueError('登记板型孔坐标、孔径、孔型或孔编号无效。')
            point=(h['xMm'],h['yMm'])
            polygons=[[(p['xMm'],p['yMm']) for p in ring] for ring in rings]
            if not _inside(point,polygons[0]) or any(_inside(point,ring,False) for ring in polygons[1:]):raise ValueError('登记孔中心位于板面缺口或结构开口中。')
            if point in points:raise ValueError('登记板型实际孔中心重复。')
            points.add(point);seen.add(h['id'])
            if h['type']=='thread' and not identifier(h.get('thread')):raise ValueError('螺纹孔必须登记螺纹规格。')
            if h['type']=='counterbore' and (not number(h.get('counterboreDiameterMm'),h['diameterMm'],100) or not number(h.get('counterboreDepthMm'),.01,row['thicknessMm'])):raise ValueError('圆柱沉孔尺寸未登记。')
        if 'customMountingHoles' in row and type(row['customMountingHoles']) is not bool:raise ValueError('自选沉孔开关须为布尔值。')
        if row.get('customMountingHoles') is True and row.get('mountingHoleIds'):raise ValueError('自选沉孔板不得预选固定孔。')
        mounting=row.get('mountingHoleIds',[])
        if not isinstance(mounting,list) or any(not isinstance(k,str) for k in mounting) or len(mounting)!=len(set(mounting)) or not set(mounting)<=seen or any(h['id'] in mounting and h['type']=='thread' for h in holes):raise ValueError('固定孔只能引用已登记间隙孔或圆柱沉孔。')
        minimum=row.get('minimumAlignedMountingHoles',4)
        if type(minimum) is not int or not 1<=minimum<=128:raise ValueError('登记板型最少固定孔数应为1至128。')
        for key,suffixes in [('topViewPath',{'.svg','.png','.webp'}),('stepPath',{'.step','.stp'}),('drawingPath',{'.pdf'})]:
            value=row.get(key)
            if value is None and key!='topViewPath':continue
            if not isinstance(value,str) or not value or any(s in value for s in ('\\','\x00',':')) or value.startswith('/') or any(p in ('','..','.') for p in value.split('/')) or Path(value).suffix.lower() not in suffixes:raise ValueError('登记板型资产路径无效。')
        contents=row.get('defaultContents',[])
        kit_map={k['id']:k for k in catalog.get('kits',[])}
        if not isinstance(contents,list) or len(contents)>64:raise ValueError('板上预装器件数量无效。')
        for item in contents:
            if (not isinstance(item,dict) or not {'kitId','xMm','yMm','rotationDeg'} <= set(item) or set(item)-{'kitId','xMm','yMm','rotationDeg','optics'}
                or not isinstance(item.get('kitId'),str) or item['kitId'] not in kit_map
                or kit_map[item['kitId']].get('layout',{}).get('placementAllowed') is not True
                or any(not number(item.get(k),-6000,6000) for k in ('xMm','yMm'))
                or type(item.get('rotationDeg')) not in (int,float) or item['rotationDeg'] not in (0,90,180,270)):
                raise ValueError('板上预装器件的型号或位置无效。')
            if 'optics' in item:
                from optics_settings import normalize_optics
                normalize_optics(item['optics'])
        fixed=row.get('fixedOpticalElements',[])
        if not isinstance(fixed,list) or len(fixed)>32:raise ValueError('固定光学参考数量无效。')
        fixed_ids=set()
        for item in fixed:
            if (not isinstance(item,dict) or not identifier(item.get('id')) or item['id'] in fixed_ids or item.get('kitId') not in kit_map
                or item.get('positionLocked') is not True or item.get('participatesInCollision') is not False
                or not isinstance(item.get('centerMm'),dict) or not all(number(item['centerMm'].get(k),-3000,6000) for k in ('xMm','yMm'))
                or not number(item.get('axisHeightMm'),0,6000)):
                raise ValueError('固定光学参考的身份或位置无效。')
            kind=item.get('elementType','lens')
            if kind=='source':
                if not number(item.get('sourceDirectionDeg'),-3600,3600):raise ValueError('固定出光口方向无效。')
            elif kind=='lens':
                if (not number(item.get('surfaceAngleDeg'),-3600,3600) or not number(item.get('lensDiameterMm'),.001,10000)
                    or not isinstance(item.get('topViewPath'),str) or not item['topViewPath'].startswith('topviews/') or '..' in item['topViewPath']
                    or not isinstance(item.get('imageBoundsMm'),dict) or not all(number(item['imageBoundsMm'].get(k),-3000,6000) for k in ('xMin','xMax','yMin','yMax'))
                    or item['imageBoundsMm']['xMin']>=item['imageBoundsMm']['xMax'] or item['imageBoundsMm']['yMin']>=item['imageBoundsMm']['yMax']):raise ValueError('固定透镜几何或资产无效。')
            else:raise ValueError('固定光学类型不支持。')
            fixed_ids.add(item['id'])
        included=row.get('includedComponents',[])
        component_ids={c['id'] for c in catalog.get('components',[])}
        if not isinstance(included,list) or len(included)>64:raise ValueError('板件随附器件清单无效。')
        included_ids=set()
        for item in included:
            if (not isinstance(item,dict) or set(item)!={'componentId','quantity'}
                or not isinstance(item.get('componentId'),str) or item['componentId'] not in component_ids
                or item['componentId'] in included_ids or type(item.get('quantity')) is not int
                or not 1<=item['quantity']<=9999):raise ValueError('板件随附器件身份或数量无效。')
            included_ids.add(item['componentId'])
        refs=row.get('referenceAnnotations')
        if refs is not None:
            if not isinstance(refs,dict) or refs.get('displayOnly') is not True or not identifier(refs.get('revision')):raise ValueError('参考标注必须为明确版本的只显示图层。')
            if any(p.get('kind')=='obstruction-section' for p in refs.get('projections',[]) if isinstance(p,dict)) and not number(refs.get('sectionHeightAboveBoardTopMm'),-3000,6000):raise ValueError('遮挡截面的板顶参考高度无效。')
            def refpoint(p):return isinstance(p,dict) and all(number(p.get(k),-3000,6000) for k in ('xMm','yMm'))
            refids=set()
            for group in ('centers','projections'):
                items=refs.get(group,[])
                if not isinstance(items,list) or len(items)>128:raise ValueError('参考标注数量无效。')
                for item in items:
                    if not isinstance(item,dict) or not identifier(item.get('id')) or item['id'] in refids or not identifier(item.get('label')) or item.get('kind') not in ('center','leg','glass','iontrap','coil','coil-section','obstruction-section'):raise ValueError('参考标注身份无效。')
                    refids.add(item['id'])
                    if item.get('labelPointMm') is not None and not refpoint(item['labelPointMm']):raise ValueError('参考文字位置无效。')
                    if group=='centers' and not refpoint(item):raise ValueError('参考中心坐标无效。')
                    if group=='projections':
                        ring=item.get('outlineMm')
                        if not isinstance(ring,list) or not 3<=len(ring)<=256 or not all(refpoint(q) for q in ring):raise ValueError('参考投影轮廓无效。')
                        voids=item.get('cutoutsMm',[])
                        if not isinstance(voids,list) or len(voids)>256 or any(not isinstance(h,list) or not 3<=len(h)<=256 or not all(refpoint(q) for q in h) for h in voids):raise ValueError('参考投影开口无效。')
    return rows


def definition(board, catalog=None):
    if not isinstance(board, dict) or not all(isinstance(board.get(k), str) and board[k] for k in REFERENCE_FIELDS):
        raise RegisteredBoardError('invalid_registered_board', '登记面包板需要板型编号及固定来源版本。')
    catalog = catalog if catalog is not None else _ACTIVE_CATALOG.get()
    if catalog is None:
        try:
            stat = CATALOG_PATH.stat()
            rows = _catalog(str(CATALOG_PATH), stat.st_mtime_ns, stat.st_size)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RegisteredBoardError('board_registry_unavailable', '面包板目录暂不可用。', 503) from exc
    else:
        rows = {row['id']: row for row in catalog.get('registeredBoards', [])}
    row = rows.get(board['registeredBoardId'])
    if row is None:
        raise RegisteredBoardError('unknown_registered_board', '工程引用的面包板未登记，请更新元件库。', 409)
    if row.get('revision') != board['registeredBoardRevision']:
        raise RegisteredBoardError('registered_board_changed', '这块面包板的来源版本已更新；请重新从元件库加入，不能沿用旧孔位。', 409)
    return row


def allows_covered_mounting(board, catalog=None):
    """Stage top screws can be fastened before the child optics are installed.

    Only trusted catalog stage tops receive this assembly-order exception.
    The stage lower interface is still checked separately against the parent.
    """
    return registered(board) and definition(board, catalog).get("stageOnly") is True



def custom_mounting(row):
    return row.get('customMountingHoles') is True

def mounting_candidates(row):
    return [h['id'] for h in row['holesMm'] if h['type']=='thread' and h.get('thread')=='M6x1.0'] if custom_mounting(row) else row.get('mountingHoleIds', [])

def custom_mounting_error(row, hole_id, chosen):
    """Use actual source edges/holes, never the rectangular bounding box."""
    if not custom_mounting(row):return ''
    from breadboard import COUNTERBORE, MIN_MOUNTING_WEB_MM
    h=next((h for h in row['holesMm'] if h['id']==hole_id),None)
    if not h or hole_id not in mounting_candidates(row):return '只能在已登记的M6螺纹孔位置选择沉孔。'
    r=COUNTERBORE['diameterMm']/2;web=MIN_MOUNTING_WEB_MM;p=(h['xMm'],h['yMm'])
    if row['thicknessMm']<COUNTERBORE['depthMm']+web:return '板厚不足以加工该沉孔。'
    for ring in [row['outlineMm'],*row.get('cutoutsMm',[])]:
        points=[(v['xMm'],v['yMm']) for v in ring]
        if any(_distance(p,a,b)<r+web-EPS for a,b in _edges(points)):return '沉孔距真实板边不足，需保留2 mm边壁。'
    for other in row['holesMm']:
        if other['id']==hole_id:continue
        selected=other['id'] in chosen
        other_r=r if selected else other['diameterMm']/2
        clearance=0 if selected else web
        if math.hypot(p[0]-other['xMm'],p[1]-other['yMm'])<r+other_r+clearance-EPS:return '沉孔与邻孔间距不足。'
    return ''

def board_token(row, selected=()):
    data=[row['id'],row['revision']]
    if custom_mounting(row) and selected:data.append(sorted(selected))
    return hashlib.sha256(json.dumps(data,separators=(',',':')).encode()).hexdigest()[:16]


def normalize_fixed_optics(board,row):
    from optics_settings import normalize_optics
    if 'fixedOptics' not in board:return {}
    raw=board['fixedOptics'];defs={v['id']:v for v in row.get('fixedOpticalElements',[])}
    if not isinstance(raw,dict) or len(raw)>32:raise RegisteredBoardError('invalid_fixed_optics','固定镜架光学设置格式无效。')
    result={}
    for key,value in raw.items():
        if key not in defs or not isinstance(value,dict):raise RegisteredBoardError('invalid_fixed_optics','固定光学设置无效。')
        kind=defs[key].get('elementType','lens')
        allowed={'elementType','inserted','configured','source'} if kind=='source' else {'elementType','inserted','configured','focalLengthMm','clearApertureMm'}
        if set(value)-allowed or value.get('elementType')!=kind:raise RegisteredBoardError('invalid_fixed_optics','固定器件只接受对应光学参数，位置与朝向由目录固定。')
        if kind=='source' and (not isinstance(value.get('source'),dict) or 'directionAngleDeg' in value['source']):raise RegisteredBoardError('invalid_fixed_optics','固定出光口位置与方向不可覆盖。')
        clean=normalize_optics(value)
        if kind=='lens' and 'clearApertureMm' in clean and clean['clearApertureMm']>defs[key]['lensDiameterMm']:raise RegisteredBoardError('invalid_fixed_optics','有效通光口径不能大于镜片外径。')
        result[key]=clean
    return {'fixedOptics':result} if result else {}

def normalize(board):
    if set(board) - REFERENCE_FIELDS - COMPATIBILITY_FIELDS - {'mountingHoles','fixedOptics'}:
        raise RegisteredBoardError('invalid_registered_board', '登记面包板只接受目录引用和已有固定孔选择，不能提交外形或资产路径。')
    row = definition(board)
    b = {key: row[key] for key in ('widthMm','heightMm','thicknessMm','pitchMm','edgeOffsetMm')}
    b.update(holeType='M6_through', thread='M6x1.0', holeDiameterMm=5)
    for key in COMPATIBILITY_FIELDS:
        if key in board and (type(board[key]) is bool or board[key] != b[key]):
            raise RegisteredBoardError('registered_board_fixed_geometry', '登记面包板外形、厚度和孔位固定，不能通过参数框更改；请在原 CAD 中修改后登记新版本。')
    available = set(mounting_candidates(row))
    source = board.get('mountingHoles', [{'holeId': key} for key in row.get('mountingHoleIds', [])])
    if not isinstance(source, list) or len(source) > 128:
        raise RegisteredBoardError('invalid_mounting_holes', '固定孔选择应为已登记孔编号的数组。')
    chosen = []
    for hole in source:
        if not isinstance(hole, dict) or set(hole) != {'holeId'} or not isinstance(hole['holeId'], str) or hole['holeId'] not in available or hole['holeId'] in chosen:
            raise RegisteredBoardError('invalid_mounting_holes', '只可选择源面包板已确认的固定孔，不能重复或把普通螺纹孔当作已加工沉孔。')
        chosen.append(hole['holeId'])
    for key in chosen:
        error=custom_mounting_error(row,key,chosen)
        if error:raise RegisteredBoardError('invalid_mounting_holes',error)
    return {**b, **normalize_fixed_optics(board,row), **{k: board[k] for k in REFERENCE_FIELDS}, 'mountingHoles': [{'holeId': key} for key in mounting_candidates(row) if key in chosen]}


def outline(board):
    if registered(board):
        return [(p['xMm'], p['yMm']) for p in definition(board)['outlineMm']]
    return [(0,0),(board['widthMm'],0),(board['widthMm'],board['heightMm']),(0,board['heightMm'])]


def cutouts(board):
    return [[(p['xMm'], p['yMm']) for p in polygon] for polygon in definition(board).get('cutoutsMm', [])] if registered(board) else []


def holes(board, threaded=False):
    if registered(board):
        selected = {h['holeId'] for h in board.get('mountingHoles', [])}
        row=definition(board);result=[]
        for h in row.get('holesMm',[]):
            if threaded and not (h['type']=='thread' and h.get('thread')=='M6x1.0' and h['id'] not in selected):continue
            h=deepcopy(h)
            if custom_mounting(row) and h['id'] in selected:
                from breadboard import COUNTERBORE
                h.update(type='counterbore',diameterMm=COUNTERBORE['clearanceDiameterMm'],counterboreDiameterMm=COUNTERBORE['diameterMm'],counterboreDepthMm=COUNTERBORE['depthMm'])
                h.pop('thread',None);h.pop('tapDrillDiameterMm',None)
            result.append(h)
        return result
    offset, pitch = board['edgeOffsetMm'], board['pitchMm']
    excluded = {(h['columnIndex'], h['rowIndex']) for h in board.get('mountingHoles', [])}
    if threaded and board['holeType'] != 'M6_through':
        return []
    return [{'id': f'grid:{column}:{row}', 'columnIndex': column, 'rowIndex': row,
             'xMm': round(offset+column*pitch,6), 'yMm': round(offset+row*pitch,6),
             'type': 'thread' if board['holeType']=='M6_through' else 'clearance', 'diameterMm': 6 if board['holeType']=='M6_through' else board['holeDiameterMm']}
            for row in range(math.floor((board['heightMm']-2*offset)/pitch+EPS)+1)
            for column in range(math.floor((board['widthMm']-2*offset)/pitch+EPS)+1)
            if not threaded or (column,row) not in excluded]


def aligned(board, point, exclude_mounting=True):
    x,y = point
    if registered(board):
        return any(abs(x-h['xMm']) <= EPS and abs(y-h['yMm']) <= EPS for h in holes(board, threaded=True))
    indices=[]
    for value,size in ((x,board['widthMm']),(y,board['heightMm'])):
        n=(value-board['edgeOffsetMm'])/board['pitchMm']
        if n < -EPS or value > size-board['edgeOffsetMm']+EPS or abs(n-round(n)) > EPS:
            return False
        indices.append(round(n))
    return not exclude_mounting or not any((h['columnIndex'],h['rowIndex']) == tuple(indices) for h in board.get('mountingHoles',[]))


def _distance(p, a, b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)


def _edges(poly):
    return zip(poly,poly[1:]+poly[:1])


def _inside(p, poly, boundary=True):
    if any(_distance(p,a,b) <= EPS for a,b in _edges(poly)):
        return boundary
    result=False
    for a,b in _edges(poly):
        if (a[1]>p[1]) != (b[1]>p[1]) and p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:
            result=not result
    return result


def contains(board, point, clearance=0, strict=False):
    outer,inner=outline(board),cutouts(board)
    if not _inside(point,outer,not strict) or any(_inside(point,p,strict) for p in inner):
        return False
    return clearance <= 0 or all(_distance(point,a,b)+EPS >= clearance for ring in [outer,*inner] for a,b in _edges(ring))


def _cross(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _proper_cross(a,b,c,d):
    # Cross products scale with edge length. Compare signed distances against the
    # geometric tolerance so 180/270 degree rounding at a shared endpoint does
    # not become a false proper intersection.
    ab=EPS*math.hypot(b[0]-a[0],b[1]-a[1]);cd=EPS*math.hypot(d[0]-c[0],d[1]-c[1])
    ac,ad,ca,cb=_cross(a,b,c),_cross(a,b,d),_cross(c,d,a),_cross(c,d,b)
    return ((ac>ab and ad<-ab) or (ad>ab and ac<-ab)) and ((ca>cd and cb<-cd) or (cb>cd and ca<-cd))


def contains_polygon(board, polygon):
    if not all(contains(board,p) for p in polygon):
        return False
    for a,b in _edges(polygon):
        if not contains(board,((a[0]+b[0])/2,(a[1]+b[1])/2)):
            return False
        if any(_proper_cross(a,b,c,d) for ring in [outline(board),*cutouts(board)] for c,d in _edges(ring)):
            return False
    return not any(_inside(ring[0],polygon,False) for ring in cutouts(board))


def _transform(p, pose):
    angle=math.radians(pose.get('rotationDeg',0));c,s=math.cos(angle),math.sin(angle)
    return pose.get('xMm',0)+c*p[0]-s*p[1],pose.get('yMm',0)+s*p[0]+c*p[1]


def _inverse(p, pose):
    angle=math.radians(pose.get('rotationDeg',0));c,s=math.cos(angle),math.sin(angle)
    x,y=p[0]-pose.get('xMm',0),p[1]-pose.get('yMm',0)
    return c*x+s*y,-s*x+c*y


def world_outline(plate):
    return [_transform(p,plate) for p in outline(plate['board'])]


def overlaps_polygon(board, pose, polygon, touch=False):
    """Polygon against the actual plate material, excluding internal cut-outs."""
    local=[_inverse(p,pose) for p in polygon]
    if any(contains(board,p,strict=not touch) for p in local):
        return True
    outer,inner=outline(board),cutouts(board)
    if any(_inside(p,local,touch) for p in outer):
        return True
    for a,b in _edges(local):
        if contains(board,((a[0]+b[0])/2,(a[1]+b[1])/2),strict=not touch):
            return True
        for ring in [outer,*inner]:
            for c,d in _edges(ring):
                if _proper_cross(a,b,c,d):
                    return True
                if touch and min(_distance(a,c,d),_distance(b,c,d),_distance(c,a,b),_distance(d,a,b)) <= EPS:
                    return True
    # Coincident boundaries can enclose common material without interior vertices.
    for a,b in _edges(outer):
        length=math.hypot(b[0]-a[0],b[1]-a[1])
        if length <= EPS:continue
        for side in (-1,1):
            p=((a[0]+b[0])/2-side*(b[1]-a[1])*1e-4/length,(a[1]+b[1])/2+side*(b[0]-a[0])*1e-4/length)
            if contains(board,p,strict=True) and _inside(p,local,False):return True
    return False


def plates_overlap(a,b):
    # Test real material probes on both boundaries. The polygon test alone would
    # fill the second board's cut-outs, so every probe checks both board materials.
    def within(point,p):return contains(p['board'],_inverse(point,p),strict=True)
    rings_a=[[_transform(v,a) for v in ring] for ring in [outline(a['board']),*cutouts(a['board'])]]
    rings_b=[[_transform(v,b) for v in ring] for ring in [outline(b['board']),*cutouts(b['board'])]]
    for ring in [*rings_a,*rings_b]:
        for p,q in _edges(ring):
            length=math.hypot(q[0]-p[0],q[1]-p[1])
            if not length:continue
            for f in (0,0.5,1):
                for side in (-1,1):
                    probe=(p[0]+f*(q[0]-p[0])-side*(q[1]-p[1])*1e-4/length,p[1]+f*(q[1]-p[1])+side*(q[0]-p[0])*1e-4/length)
                    if within(probe,a) and within(probe,b):return True
    for ra in rings_a:
        for rb in rings_b:
            if any(_proper_cross(p,q,r,s) for p,q in _edges(ra) for r,s in _edges(rb)):return True
    return False


def circle_touches(board, pose, center, radius):
    point=_inverse(center,pose)
    return contains(board,point) or any(_distance(point,a,b) <= radius+EPS for ring in [outline(board),*cutouts(board)] for a,b in _edges(ring))


def specs(board):
    b=normalize(board);row=definition(b)
    selected={h['holeId'] for h in b['mountingHoles']}
    mounts=[{**deepcopy(h),'holeId':h['id'],'label':h['id']} for h in row['holesMm'] if h['id'] in selected]
    token=board_token(row,selected)
    custom=custom_mounting(row) and bool(selected)
    if custom:
        from breadboard import COUNTERBORE
        mounts=[{**h,'type':'counterbore','diameterMm':COUNTERBORE['clearanceDiameterMm'],
                 'counterboreDiameterMm':COUNTERBORE['diameterMm'],'counterboreDepthMm':COUNTERBORE['depthMm']} for h in mounts]
    material=row.get('sourceMaterial') or '待确认'
    return {'board':b,'registeredBoard':True,'registeredBoardId':row['id'],'registeredBoardRevision':row['revision'],
            'componentId':'registered-board-'+token,'model':row.get('model') or row['name'],
            'digest':token,'geometryDigest':token,'filenameStem':row['name'],'generatorVersion':'registered-source',
            'gridColumns':0,'gridRows':0,'holeCount':len(row['holesMm']),
            'regularHoleCount':len(row['holesMm'])-(len(selected) if custom_mounting(row) else len(row.get('mountingHoleIds',[]))),
            'mountingHoleCount':len(mounts),'mountingHoles':mounts,'allHolesMm':[next((m for m in mounts if m['holeId']==h['id']),deepcopy(h)) for h in row['holesMm']],
            'customMountingHoles':custom_mounting(row),'requiresCustomBoardManufacturing':custom,
            'minimumAlignedMountingHoles':row.get('minimumAlignedMountingHoles',4),
            'holeCallout':'按原 CAD 登记孔位和孔型；非完整矩形孔阵',
            'counterbore':dict(COUNTERBORE) if custom else {},'counterboreCallout':'自选：Ø6.6通；顶面Ø11深6.5，待生成对应加工资料' if custom else '默认全螺纹孔，无预制沉孔' if custom_mounting(row) else '源模型已有固定孔；孔型与尺寸见登记图',
            'material':material,'surfaceTreatment':row.get('sourceSurfaceTreatment') or '待确认','threadClass':'待确认',
            'coordinateSystem':'Registered source: XY plane, lower-left bounding-box origin; +X right, +Y up.',
            'topViewPath':row.get('topViewPath'),'stepPath':row.get('stepPath'),'drawingPath':row.get('drawingPath'),
            'sourceUrl':row.get('sourceUrl',''),'name':row['name'],'notes':row.get('notes','')}


def row(board):
    spec=specs(board)
    return {'componentId':spec['componentId'],'name':spec['name'],'model':spec['model'],'kind':'custom','unit':'块','quantity':1,
            'registeredBoard':True,'boardSpec':spec,'requiresCustomBoardManufacturing':spec['requiresCustomBoardManufacturing'],'registeredBoardId':spec['registeredBoardId'],'registeredBoardRevision':spec['registeredBoardRevision'],
            'stepPath':spec['stepPath'],'drawingPath':spec['drawingPath'],'sourceUrl':spec['sourceUrl'],'kits':[],
            'status':'自选沉孔；待生成对应加工模型和图纸' if spec['requiresCustomBoardManufacturing'] else '登记板型；制造资料待补齐' if not spec['stepPath'] or not spec['drawingPath'] else '原模型登记板型',
            'notes':'；'.join(filter(None,[spec['notes'],'固定外形及源孔位；不按包围盒生成矩形板','材料：'+spec['material']])),
            'manufacturingSpec':{k:spec[k] for k in ('material','surfaceTreatment','threadClass')}}


def reference_svg_markup(board):
    """Paint-only references. These never enter board geometry or mounting checks."""
    refs=(definition(board) or {}).get('referenceAnnotations', {})
    if refs.get('displayOnly') is not True:
        return ''
    colors={'leg':'#8b5b35','glass':'#128795','iontrap':'#934d9e','center':'#506d61','coil':'#b78042','coil-section':'#c36d22','obstruction-section':'#b65b24'}
    y=lambda v:board['heightMm']-v
    esc=lambda s:html.escape(str(s),quote=True)
    def label(p,text,color,size=22,anchor='start'):
        return f'<text x="{p["xMm"]:g}" y="{y(p["yMm"]):g}" fill="{color}" stroke="#fbfcf9" stroke-width="4" paint-order="stroke" font-family="Arial, sans-serif" font-size="{size}" font-weight="600" text-anchor="{anchor}">{esc(text)}</text>'
    pieces=['<g class="board-reference-annotations" pointer-events="none" aria-label="位置参考标注，不参与干涉检测">']
    for p in refs.get('projections',[]):
        ring=p.get('outlineMm',[])
        if len(ring)<3:continue
        color=colors.get(p['kind'],colors['center']);leg=p['kind']=='leg'
        if p['kind'] in ('coil','coil-section','obstruction-section'):
            section=p['kind'] in ('coil-section','obstruction-section')
            d=' '.join('M '+' L '.join(f'{v["xMm"]:g},{y(v["yMm"]):g}' for v in r)+' Z' for r in [ring,*p.get('cutoutsMm',[])])
            fill=color if section else 'none';width='2.2' if section else '1.3';dash='none' if section else '8 6'
            pieces.append(f'<g data-reference-kind="{esc(p["kind"])}" data-reference-id="{esc(p["id"])}"><title>{esc(p.get("description",p["label"]))} · 仅位置参考，不参与干涉检测</title><path d="{d}" fill="{fill}" fill-opacity=".30" fill-rule="evenodd" stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}"/>')
            if p.get('labelPointMm'):pieces.append(label(p['labelPointMm'],p['label'],color,16 if p['kind']=='obstruction-section' else 20,'middle' if p['kind']=='obstruction-section' else 'start'))
            pieces.append('</g>')
            continue
        points=' '.join(f'{v["xMm"]:g},{y(v["yMm"]):g}' for v in ring)
        pieces.append(f'<g data-reference-kind="{esc(p["kind"])}" data-reference-id="{esc(p["id"])}"><title>{esc(p.get("description",p["label"]))} · 仅位置参考，不参与干涉检测</title><polygon points="{points}" fill="{color}" fill-opacity="{".12" if leg else ".08"}" stroke="{color}" stroke-width="{"1.6" if leg else "2.2"}" stroke-dasharray="{"5 4" if leg else "9 5"}"/>')
        if p.get('labelPointMm'):pieces.append(label(p['labelPointMm'],p['label'],color,18 if leg else 22,'middle' if leg else 'start'))
        pieces.append('</g>')
    for p in refs.get('centers',[]):
        color=colors.get(p.get('kind'),colors['center']);cx=p['xMm'];cy=y(p['yMm'])
        pieces.append(f'<g data-reference-center="{esc(p["id"])}"><title>{esc(p.get("description",p["label"]))} ({cx:g}, {p["yMm"]:g}) mm · 仅位置参考</title><path d="M {cx-16:g} {cy:g} H {cx+16:g} M {cx:g} {cy-16:g} V {cy+16:g}" fill="none" stroke="{color}" stroke-width="1.7"/><circle cx="{cx:g}" cy="{cy:g}" r="7" fill="#fbfcf9" fill-opacity=".85" stroke="{color}" stroke-width="1.7"/>')
        if p.get('labelPointMm'):
            lp=p['labelPointMm'];pieces.append(f'<path d="M {cx+8:g} {cy+5:g} L {lp["xMm"]-8:g} {y(lp["yMm"])-6:g}" fill="none" stroke="{color}" stroke-width="1"/>')
        pieces.append(label(p.get('labelPointMm',{'xMm':cx+23,'yMm':p['yMm']+18}),p['label'],color))
        pieces.append('</g>')
    if refs.get('sectionReferenceNote'):pieces.append(label({'xMm':board['widthMm']/2,'yMm':54},refs['sectionReferenceNote'],colors['coil'],16,'middle'))
    pieces.append(label({'xMm':board['widthMm']/2,'yMm':28},'位置参考 · 不参与干涉检测',colors['center'],18,'middle'))
    return ''.join(pieces)+'</g>'



def fixed_optics_svg_markup(board, static_root=None):
    import base64
    result=[]
    for d in (definition(board) or {}).get('fixedOpticalElements',[]):
        if d.get('elementType')=='source':
            x,y=d['centerMm']['xMm'],board['heightMm']-d['centerMm']['yMm']
            result.append(f'<g data-fixed-board-optic="{html.escape(d["id"])}"><title>{html.escape(d["name"])}</title><circle cx="{x}" cy="{y}" r="5" fill="#dcffed" stroke="#167963" stroke-width="1"/></g>')
            continue
        path=Path(static_root or Path(__file__).parent/'static')/d['topViewPath'];b=d['imageBoundsMm']
        data=base64.b64encode(path.read_bytes()).decode('ascii')
        result.append(f'<g data-fixed-board-optic="{html.escape(d["id"])}"><title>{html.escape(d["name"])} · 固定位置</title><image x="{b["xMin"]}" y="{board["heightMm"]-b["yMax"]}" width="{b["xMax"]-b["xMin"]}" height="{b["yMax"]-b["yMin"]}" href="data:image/svg+xml;base64,{data}"/></g>')
    return ''.join(result)

def svg_markup(board, static_root=None):
    """Standalone SVG fragment in the existing board coordinate system (Y down)."""
    h=board['heightMm'];rings=[outline(board),*cutouts(board)]
    path=' '.join('M '+' L '.join(f'{x:g},{h-y:g}' for x,y in ring)+' Z' for ring in rings)
    pieces=[f'<path class="breadboard" d="{path}" fill="#f8faf7" fill-rule="evenodd" stroke="#58766f" stroke-width="0.7"/>']
    for hole in holes(board):
        radius=hole.get('diameterMm',6)/2
        pieces.append(f'<circle data-board-hole="{html.escape(hole["id"],quote=True)}" cx="{hole["xMm"]:g}" cy="{h-hole["yMm"]:g}" r="{radius:g}" fill="#dfe8e2" stroke="#86938f" stroke-width="0.35"/>')
        if hole['type']=='counterbore':
            pieces.append(f'<circle cx="{hole["xMm"]:g}" cy="{h-hole["yMm"]:g}" r="{hole.get("counterboreDiameterMm",hole["diameterMm"])/2:g}" fill="none" stroke="#86938f" stroke-width="0.35"/>')
    from local_board_library import accessory_markup
    return ''.join(pieces)+reference_svg_markup(board)+fixed_optics_svg_markup(board,static_root)+accessory_markup(board,definition(board))
