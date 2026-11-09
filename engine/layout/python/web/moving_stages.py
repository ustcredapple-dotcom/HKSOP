"""Trusted single-axis stage modules integrated with ordinary sub-board instances.

Saved XY is the CURRENT moving top-plate origin; no executable geometry is
accepted from a project. Fixed datum and Z are derived from the frozen catalog.
Collision boxes are conservative layout screening, never an entity-interference
or real assembly acceptance claim.
"""
from __future__ import annotations
from copy import deepcopy
import json
import math
from pathlib import Path

CAPABILITY = 'zzlab-stage-motion-v2'
EPS = 1e-6


def _error(code, message, status=400):
    from bom import APIError
    raise APIError(code, message, status)


def validate_capabilities(value, layout=None, catalog=None):
    from collision_overrides import CAPABILITY as COLLISION_CAPABILITY
    requirements = value
    supported = {CAPABILITY, COLLISION_CAPABILITY, 'zzlab-metric-supports-v1', 'zzlab-manual-source-mount-v1'}
    if not isinstance(requirements,list) or any(not isinstance(r,str) or r not in supported for r in requirements) or len(requirements)!=len(set(requirements)):
        _error('unsupported_project_capability', '工程声明了当前网站不支持的能力。')
    boards = layout.get('subBoards',[]) if isinstance(layout,dict) else []
    has_stage = isinstance(boards,list) and any(isinstance(p,dict) and 'stageMotion' in p for p in boards)
    if has_stage and CAPABILITY not in requirements:
        _error('stage_capability_required', '位移模块工程必须保留运动能力声明，不能作为静态板导入。')
    if isinstance(layout,dict) and layout.get('collisionOverrides') and COLLISION_CAPABILITY not in requirements:
        _error('collision_overrides_capability_required', '器件碰撞豁免必须保留能力声明，不能按旧布局规则导入。')
    manual_ids={k['id'] for k in (catalog or {}).get('kits',[]) if k.get('layout',{}).get('manualMountingPolicy')}
    if isinstance(layout,dict) and any(isinstance(i,dict) and ('manualMount' in i or i.get('kitId') in manual_ids) for i in layout.get('instances',[])) and 'zzlab-manual-source-mount-v1' not in requirements:
        _error('manual_source_capability_required', '人工支撑光源工程必须保留安装声明能力，不能作为已验证目录光源导入。')
    return list(requirements)


def _catalog(catalog=None):
    if catalog is not None:
        return catalog
    import registered_boards as rb
    current = rb._ACTIVE_CATALOG.get()
    return current if current is not None else json.loads(Path(rb.CATALOG_PATH).read_text())


def module_for(plate, catalog=None):
    state = plate.get('stageMotion') if isinstance(plate, dict) else None
    if state is None:
        return None
    if not isinstance(state, dict) or set(state) != {'moduleId', 'revision', 'qMm'}:
        _error('invalid_stage_motion', '位移台只接受模块编号、固定版本和行程值。')
    module = next((m for m in _catalog(catalog).get('stageModules', []) if m['id'] == state['moduleId']), None)
    if module is None:
        _error('unknown_stage_module', '工程引用的手动位移模块未登记，请更新元件库。', 409)
    if state['revision'] != module['revision']:
        _error('stage_module_changed', '位移模块版本已改变，请重新从元件库加入；不能沿用旧机械尺寸。', 409)
    return module


def limits(module):
    motion = module['motion']
    return motion.get('workingMinMm', motion['minMm']), motion.get('workingMaxMm', motion['maxMm'])


def normalize_stage_motion(plate, catalog=None):
    module = module_for(plate, catalog)
    if module is None:
        from registered_boards import registered, definition
        if registered(plate['board']) and definition(plate['board'], _catalog(catalog)).get('stageOnly'):
            _error('stage_module_required', '这块顶板必须作为完整位移模块加入，不能当作普通静态小板。')
        return {}
    state, runtime = plate['stageMotion'], module['runtime']
    q = state['qMm']
    lo, hi = limits(module)
    if type(q) not in (int, float) or not math.isfinite(q) or q < lo-EPS or q > hi+EPS:
        _error('stage_travel_out_of_range', f'位移量必须在 {lo:g} 至 {hi:g} mm 的工作限位内；q=0 表示机械行程中点。')
    board = plate['board']
    if (board.get('registeredBoardId') != runtime['topBoardId'] or
            board.get('registeredBoardRevision') != runtime['topBoardRevision']):
        _error('stage_board_mismatch', '位移模块必须引用该版本的原上面包板，不能替换板形或孔表。')
    return {'stageMotion': {'moduleId': module['id'], 'revision': module['revision'], 'qMm': float(q)}}


def rotate(x, y, degrees):
    # Exact quarter turns keep mounting grid checks free of trig drift.
    return ((x, y), (-y, x), (-x, -y), (y, -x))[(degrees//90)%4]


def fixed_pose(plate, module=None):
    module = module or module_for(plate)
    q = plate['stageMotion']['qMm']
    origin = module['centerTopOriginMm']
    dx, dy = rotate(origin['xMm']+(q if module['motion']['axis']=='x' else 0),
                    origin['yMm']+(q if module['motion']['axis']=='y' else 0), plate['rotationDeg'])
    return {'xMm': plate['xMm']-dx, 'yMm': plate['yMm']-dy, 'rotationDeg': plate['rotationDeg']}


def stage_height_offset(plate):
    module = module_for(plate)
    return module['stack']['totalHeightMm']-module['stack']['topPlateThicknessMm'] if module else 0


def mounting_alignment(plate, parent, table=False):
    from stacked_layout import aligned
    from layout import transform_point
    module = module_for(plate)
    pose = fixed_pose(plate, module)
    holes = []
    for h in module['lowerAttachmentHoles']:
        world = transform_point(pose, (h['xMm'], h['yMm']))
        matches = table or aligned(parent, world)
        holes.append({'id':h['id'], 'label':h['id'], 'xMm':h['xMm'], 'yMm':h['yMm'],
                      'globalXMm':round(world[0],6), 'globalYMm':round(world[1],6),
                      'aligned':matches, 'obstructed':False, 'usable':matches, 'spare':False})
    return {'boardId':plate['id'], 'stageModuleId':module['id'], 'frame':'fixed', 'onTable':table,
            'totalCount':len(holes), 'requiredCount':0 if table else len(holes),
            'alignedCount':sum(h['aligned'] for h in holes), 'usableCount':sum(h['usable'] for h in holes), 'holes':holes}


def world_bodies(plate, swept=False):
    from layout import transform_point
    module = module_for(plate)
    fixed = fixed_pose(plate, module)
    values = []
    for body in module['collisionBodies']:
        b = body['boundsMm']; moving = body['frame']=='moving'
        pose = plate if moving else fixed
        offsets = [0]
        if swept and moving:
            offsets = [module['motion'][key]-plate['stageMotion']['qMm'] for key in ('minMm','maxMm')]
        points = [transform_point(pose, (x+(q if module['motion']['axis']=='x' else 0),
                                       y+(q if module['motion']['axis']=='y' else 0)))
                  for q in offsets for x in (b['xMin'], b['xMax']) for y in (b['yMin'], b['yMax'])]
        z = plate.get('elevationMm',0)+(module['stack']['totalHeightMm'] if moving else 0)
        values.append({'id':body['id'], 'frame':body['frame'], 'quality':'conservative',
                       'xMin':min(p[0] for p in points), 'xMax':max(p[0] for p in points),
                       'yMin':min(p[1] for p in points), 'yMax':max(p[1] for p in points),
                       'zMin':z+b['zMin'], 'zMax':z+b['zMax']})
    return values


def boxes_overlap(a, b):
    return all(min(a[k+'Max'],b[k+'Max'])-max(a[k+'Min'],b[k+'Min']) > EPS for k in 'xyz')


def validation(plate, parent, table=False):
    from stacked_layout import aligned
    from layout import transform_point
    module = module_for(plate)
    pose = fixed_pose(plate, module)
    origin = module['centerTopOriginMm']
    center = {**pose}
    dx, dy = rotate(origin['xMm'], origin['yMm'], plate['rotationDeg'])
    center.update(xMm=pose['xMm']+dx,yMm=pose['yMm']+dy)
    # Nominal 12.5 grid relation is distinct from whether ALL top holes coincide
    # with a 25 mm mother grid. The fixed attachment holes decide mounting.
    grid = module['lowerGrid']
    def grid_aligned(p):
        origin = (parent['edgeOffsetMm'],parent['edgeOffsetMm']) if not parent.get('registeredBoardId') else (grid['originXMm'],grid['originYMm'])
        return all(abs((v-o)/grid['pitchMm']-round((v-o)/grid['pitchMm'])) <= EPS
                   for v,o in zip(p,origin))
    usable = [h for h in module['topSurface']['holes'] if h.get('usable') is True]
    return {'boardId':plate['id'], 'moduleId':module['id'], 'revision':module['revision'], 'name':module['name'],
            'qMm':plate['stageMotion']['qMm'], 'fixedPose':pose,
            'totalHeightMm':module['stack']['totalHeightMm'], 'topSurfaceZMm':plate.get('elevationMm',0)+module['stack']['totalHeightMm'],
            'centerGridAligned':all(grid_aligned(transform_point(center,(h['xMm'],h['yMm']))) for h in usable),
            'currentGridAligned':all(grid_aligned(transform_point(plate,(h['xMm'],h['yMm']))) for h in usable),
            'mountingAlignment':mounting_alignment(plate,parent,table),
            'collisionBodies':world_bodies(plate), 'fullTravelSweep':world_bodies(plate,True),
            'collisionPolicy':'vendor-full-travel-fixed-keepout-plus-current-moving-plate',
            'sweepPolicy':'full-nominal-travel-envelope-reference; not a solid interference or acceptance test',
            'baseBoundaryResolved':bool(module['runtime'].get('baseBoundsMm')),
            'alignmentStatus':module.get('alignmentStatus','nominal-design'),
            'manufacturingStatus':module.get('manufacturingStatus','review-required'),
            'asBuiltAcceptance':module.get('asBuiltAcceptance','not-performed')}


def validate_catalog_modules(catalog):
    """Defense for runtime mappings as well as imported mechanical references."""
    from pathlib import PurePosixPath
    rows=catalog.get('stageModules',[])
    if not isinstance(rows,list) or len(rows)>64:raise ValueError('stageModules 必须为最多64个可信位移模块。')
    def finite(value):return type(value) in (int,float) and math.isfinite(value)
    def bounds(b, axes='xy'):
        return isinstance(b,dict) and all(finite(b.get(k+s)) for k in axes for s in ('Min','Max')) and all(b[k+'Min']<b[k+'Max'] for k in axes)
    def asset(path):
        return isinstance(path,str) and path and not path.startswith('/') and not any(c in path for c in ('\\',':','\x00')) and '..' not in PurePosixPath(path).parts and PurePosixPath(path).suffix.lower() in ('.svg','.png','.webp')
    ids=set();components={c['id'] for c in catalog['components']};kits={k['id']:k for k in catalog['kits']}
    boards={b['id']:b for b in catalog.get('registeredBoards',[])}
    for m in rows:
        if not isinstance(m,dict) or not isinstance(m.get('id'),str) or m['id'] in ids or not m.get('revision'):raise ValueError('位移模块编号或版本无效。')
        ids.add(m['id']);runtime=m.get('runtime',{});b=boards.get(runtime.get('topBoardId'))
        if b is None or b['revision']!=runtime.get('topBoardRevision') or not b.get('stageOnly'):raise ValueError('位移模块必须引用已登记专用顶板版本。')
        if not bounds(runtime.get('baseBoundsMm')):raise ValueError('位移模块固定承载底面必须有有效尺寸。')
        for key in ('fixedTopView','movingTopView'):
            v=runtime.get(key,{})
            if not asset(v.get('src')) or not all(finite(v.get(k)) for k in ('widthMm','heightMm','anchorXMm','anchorYMm')) or not 0<v['widthMm']<=10000 or not 0<v['heightMm']<=10000:raise ValueError('位移台图层尺寸、锚点或资源路径无效。')
        stack=m['stack'];motion=m['motion'];lo,hi=limits(m)
        if any(not finite(stack.get(k)) or stack[k]<0 for k in ('totalHeightMm','topPlateThicknessMm','bottomAdapterThicknessMm')) or not finite(m['stage'].get('heightMm')):raise ValueError('位移模块叠层高度无效。')
        if abs(stack['topPlateThicknessMm']-b['thicknessMm'])>EPS or abs(stack['totalHeightMm']-stack['topPlateThicknessMm']-stack['bottomAdapterThicknessMm']-m['stage']['heightMm'])>EPS:raise ValueError('位移台总高与厂家台、转接件和顶板高度不一致。')
        if motion['axis'] not in ('x','y') or not all(finite(x) for x in (motion['minMm'],motion['maxMm'],lo,hi)) or not motion['minMm']<=lo<=0<=hi<=motion['maxMm']:raise ValueError('位移轴或工作限位无效。')
        if not all(finite(m['centerTopOriginMm'].get(k)) for k in ('xMm','yMm')):raise ValueError('位移台居中上板原点无效。')
        g=m['lowerGrid']
        if not all(finite(g.get(k)) for k in ('pitchMm','originXMm','originYMm')) or g['pitchMm']<=0:raise ValueError('位移台名义孔网无效。')
        holes=m.get('lowerAttachmentHoles',[])
        if not holes or len({h['id'] for h in holes})!=len(holes) or any(not all(finite(h.get(k)) for k in ('xMm','yMm')) for h in holes):raise ValueError('位移模块固定孔无效。')
        bodies=m.get('collisionBodies',[])
        if not bodies or any(body.get('frame') not in ('fixed','moving') or not bounds(body.get('boundsMm'),'xyz') for body in bodies):raise ValueError('位移模块保守碰撞区无效。')
        top=m['topSurface']
        if top.get('widthMm')!=b['widthMm'] or top.get('heightMm')!=b['heightMm']:raise ValueError('位移模块与登记顶板外形尺寸不一致。')
        usable={h['id']:h for h in top['holes'] if h.get('usable') is True}
        actual={h['id']:h for h in b['holesMm'] if h['type']=='thread' and h.get('thread')=='M6x1.0'}
        if not usable or usable.keys()!=actual.keys() or any(h.get('type')!='thread' or h.get('thread')!='M6x1.0' or any(not finite(h.get(k)) or abs(h[k]-actual[hid][k])>EPS for k in ('xMm','yMm')) for hid,h in usable.items()):raise ValueError('位移模块可用M6孔与登记顶板真实孔表不一致。')
        lines=m['bom']
        if len({line['componentId'] for line in lines})!=len(lines) or any(line['componentId'] not in components or type(line['quantity']) is not int or line['quantity']<1 for line in lines):raise ValueError('位移模块BOM引用无效。')
        if sum(line['quantity'] for line in lines if line.get('role')=='top-plate')!=1:raise ValueError('位移模块BOM必须且只能包含一块顶板。')
        kit=kits.get(runtime.get('kitId'))
        if kit is None or kit.get('stageModuleId')!=m['id'] or {x['componentId']:x['quantity'] for x in kit['components']}!={x['componentId']:x['quantity'] for x in lines}:raise ValueError('位移模块套件身份或组合BOM不一致。')
    return rows


def svg_layers(plate, canvas_height, static_root):
    """Portable drawing uses catalog-owned layer assets, never project paths."""
    import base64
    import html
    from exports import safe_asset
    module=module_for(plate); pose=fixed_pose(plate,module); parts=[]
    runtime=module['runtime']
    for key in ('fixedTopView','movingTopView'):
        view=runtime.get(key)
        if not view:continue
        path=safe_asset(static_root,view['src'],'位移模块俯视图')
        mime={'.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp'}.get(path.suffix.lower())
        if mime is None:_error('stage_asset_invalid','位移模块俯视图文件类型无效。',409)
        q=plate['stageMotion']['qMm'] if key=='movingTopView' else 0
        dx,dy=rotate(q if module['motion']['axis']=='x' else 0,q if module['motion']['axis']=='y' else 0,plate['rotationDeg'])
        src=f'data:{mime};base64,'+base64.b64encode(path.read_bytes()).decode('ascii')
        parts.append(f'<g data-stage-layer="{key}" data-stage-board="{html.escape(plate["id"],quote=True)}" transform="translate({pose["xMm"]+dx:g} {canvas_height-pose["yMm"]-dy:g}) rotate({-plate["rotationDeg"]})"><image href="{src}" x="{-view["anchorXMm"]:g}" y="{-view["anchorYMm"]:g}" width="{view["widthMm"]:g}" height="{view["heightMm"]:g}"/></g>')
    return ''.join(parts)
