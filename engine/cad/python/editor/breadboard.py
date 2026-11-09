"""Parameterized breadboard contract and isolated CAD/PDF worker invocation.
Imports only the standard library so the web service need not have OpenCascade.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

GENERATOR_VERSION = 'bb-2026-09-27.1'
LEGACY_GENERATOR_VERSION = 'bb-2026-09-24.4'
# Geometry ID is intentionally independent of drawing/manufacturing revisions.
# Keep the previously shipped geometry token to preserve identical STEP bytes.
GEOMETRY_VERSION = 'bb-2026-09-24.2'
MANUFACTURING_POLICY_PATH = Path(__file__).with_name('manufacturing_specs.json')
MAX_HOLES = 2500
CAD_TIMEOUT_SECONDS = 180
_ALLOWED = {'widthMm', 'heightMm', 'pitchMm', 'edgeOffsetMm', 'thicknessMm', 'holeType', 'holeDiameterMm', 'thread', 'mountingHoles'}
# MISUMI mounting-hole drawing: d=6.6, d1=11, Z=6.5 for M6.
# The 2 mm web/bottom rule is an application geometry limit, not a load rating.
COUNTERBORE = {'clearanceDiameterMm': 6.6, 'diameterMm': 11.0, 'depthMm': 6.5, 'face': 'top'}
MIN_MOUNTING_WEB_MM = 2.0
COUNTERBORE_SOURCE = 'https://us.misumi-ec.com/pdf/fa/2019/2019_US_2250.pdf'


class BreadboardError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def _number(value, label, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise BreadboardError('invalid_board', f'{label}必须为 {low:g} 至 {high:g} 之间的有限数字。')
    return round(float(value), 6)


def manufacturing_profile():
    """Read operator policy only; manufacturing fields are not request inputs."""
    try:
        policy=json.loads(MANUFACTURING_POLICY_PATH.read_text())
        key=policy['generatedBoardProfile'];profile=policy['profiles'][key]
        fields=('material','surfaceTreatment','threadClass')
        if not isinstance(policy['version'],str) or any(not isinstance(profile.get(k),str) or not profile[k] for k in fields):
            raise ValueError('Incomplete manufacturing profile')
        return policy['version'],key,{k:profile[k] for k in fields}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise BreadboardError('manufacturing_policy_unavailable','面包板制造工艺配置不可用，请管理员检查工艺配置文件。',503) from exc


def normalize_board(board):
    from registered_boards import registered, normalize, RegisteredBoardError
    if registered(board):
        try:return normalize(board)
        except RegisteredBoardError as exc:raise BreadboardError(exc.code,str(exc),exc.status) from exc
    if not isinstance(board, dict) or set(board) - _ALLOWED:
        raise BreadboardError('invalid_board', '面包板只允许边长、孔距、边距、厚度和登记的孔方案参数。')
    b = {
        'widthMm': _number(board.get('widthMm'), '面包板宽度', 25, 3000),
        'heightMm': _number(board.get('heightMm'), '面包板高度', 25, 3000),
        'pitchMm': _number(board.get('pitchMm', 12.5), '孔距', 1, 100),
        'edgeOffsetMm': _number(board.get('edgeOffsetMm', 12.5), '左/下首孔边距', 0, 100),
        'thicknessMm': _number(board.get('thicknessMm', 12.5), '面包板厚度', 3, 50),
    }
    hole_type = board.get('holeType', 'M6_through')
    if hole_type not in ('M6_through', 'plain_through'):
        raise BreadboardError('invalid_board', '孔方案必须为 M6_through 或 plain_through。')
    b['holeType'] = hole_type
    if hole_type == 'M6_through':
        if board.get('thread', 'M6x1.0') != 'M6x1.0':
            raise BreadboardError('invalid_board', '当前螺纹方案为 M6×1.00。')
        b['thread'] = 'M6x1.0'
        b['holeDiameterMm'] = _number(board.get('holeDiameterMm', 5), 'M6 STEP 简化底孔直径', 5, 5)
        nominal = 6.0
    else:
        if board.get('thread') not in (None, ''):
            raise BreadboardError('invalid_board', '光孔方案不能同时指定螺纹。')
        b['thread'] = None
        b['holeDiameterMm'] = _number(board.get('holeDiameterMm', 6.4), '光孔直径', 1, 20)
        nominal = b['holeDiameterMm']
    if b['pitchMm'] < nominal + 2:
        raise BreadboardError('invalid_board', f'孔距至少为 {nominal+2:g} mm（孔公称直径加 2 mm）。')
    if not nominal/2+2 <= b['edgeOffsetMm'] <= b['pitchMm']:
        raise BreadboardError('invalid_board', f'首孔边距须不小于 {nominal/2+2:g} mm，且不大于孔距。')
    if min(b['widthMm'], b['heightMm']) < 2*b['edgeOffsetMm']:
        raise BreadboardError('invalid_board', '面包板边长不能小于首孔边距的两倍。')
    nx, ny = _grid_counts(b)
    if nx*ny > MAX_HOLES:
        raise BreadboardError('board_too_many_holes', f'此板需要 {nx*ny} 个孔，当前单板最多支持 {MAX_HOLES} 个孔；请增大孔距或缩小尺寸。')
    b['mountingHoles'] = _normalize_mounting_holes(board.get('mountingHoles', []), b, nx, ny, nominal)
    return b


def _grid_counts(b):
    return tuple(math.floor((b[dimension]-2*b['edgeOffsetMm'])/b['pitchMm'] + 1e-9)+1 for dimension in ('widthMm','heightMm'))


def _normalize_mounting_holes(holes, b, nx, ny, nominal):
    if not isinstance(holes, list) or len(holes) not in (0, 4, 8):
        raise BreadboardError('invalid_mounting_holes', '面包板安装孔须为空、4个或奇偶双组8个孔阵位置。')
    clean=[]
    for hole in holes:
        if not isinstance(hole,dict) or set(hole)!={'columnIndex','rowIndex'}:
            raise BreadboardError('invalid_mounting_holes', '安装孔只接受 columnIndex、rowIndex 两个从 0 开始的孔阵索引。')
        col,row=hole['columnIndex'],hole['rowIndex']
        if type(col) is not int or type(row) is not int or not (0<=col<nx and 0<=row<ny):
            raise BreadboardError('invalid_mounting_holes', '安装孔索引必须为板内孔阵的整数位置。')
        clean.append({'columnIndex':col,'rowIndex':row})
    clean.sort(key=lambda v:(v['rowIndex'],v['columnIndex']))
    if not clean:return clean
    if len({(h['columnIndex'],h['rowIndex']) for h in clean})!=len(clean):
        raise BreadboardError('invalid_mounting_holes', '安装孔不能重复。')
    if len(clean)==8:
        groups={}
        for h in clean:groups.setdefault((h['columnIndex']%2,h['rowIndex']%2),[]).append(h)
        keys=list(groups)
        if len(keys)!=2 or any(len(g)!=4 for g in groups.values()) or keys[0][0]==keys[1][0] or keys[0][1]==keys[1][1]:
            raise BreadboardError('mounting_hole_spacing','八孔须由行列奇偶均相反的两组四孔组成。')
    if b['thicknessMm'] < COUNTERBORE['depthMm']+MIN_MOUNTING_WEB_MM:
        raise BreadboardError('mounting_plate_too_thin', 'M6 圆柱沉孔深 6.5 mm；板厚至少 8.5 mm，以保留 2 mm 沉孔底部厚度。')
    e,p=b['edgeOffsetMm'],b['pitchMm'];r=COUNTERBORE['diameterMm']/2
    points=[(e+h['columnIndex']*p,e+h['rowIndex']*p) for h in clean]
    keys={(h['columnIndex'],h['rowIndex']) for h in clean}
    for n,(x,y) in enumerate(points):
        if min(x,y,b['widthMm']-x,b['heightMm']-y) < r+MIN_MOUNTING_WEB_MM-1e-7:
            raise BreadboardError('mounting_hole_near_edge','圆柱沉孔中心距板边至少为 7.5 mm，以保留 2 mm 边壁。')
        for prior,(ox,oy) in enumerate(points[:n]):
            if len(clean)==8 and (clean[n]['columnIndex']%2,clean[n]['rowIndex']%2)!=(clean[prior]['columnIndex']%2,clean[prior]['rowIndex']%2):continue
            if any(abs(delta/25-round(delta/25))>1e-7 for delta in (x-ox,y-oy)):
                raise BreadboardError('mounting_hole_spacing','任意两个安装孔的水平、竖直坐标差均须为 25 mm 的整数倍。')
        # The full grid is retained: a larger counterbore must not break into
        # an adjacent regular hole or another counterbore.
        for j in range(ny):
            for i in range(nx):
                if (i,j)==(clean[n]['columnIndex'],clean[n]['rowIndex']):continue
                counterbore_neighbor = (i,j) in keys
                neighbor_r=r if counterbore_neighbor else nominal/2
                minimum_web=0 if counterbore_neighbor else MIN_MOUNTING_WEB_MM
                if math.hypot(x-(e+i*p),y-(e+j*p)) < r+neighbor_r+minimum_web-1e-7:
                    raise BreadboardError('mounting_hole_web','圆柱沉孔不能互相重叠；与普通孔之间仍须保留至少 2 mm 净距，请增大孔距。')
    return clean


def board_specs(board):
    b = normalize_board(board)
    from registered_boards import registered, specs
    if registered(b):return specs(b)
    nx, ny = _grid_counts(b)
    e, p = b['edgeOffsetMm'], b['pitchMm']
    right = round(b['widthMm'] - e - (nx-1)*p, 6)
    top = round(b['heightMm'] - e - (ny-1)*p, 6)
    policy_version,profile_key,profile=manufacturing_profile()
    # Keep existing account-cart board identities and cached 0/4-hole artifacts valid.
    generator_version = GENERATOR_VERSION if len(b['mountingHoles']) == 8 else LEGACY_GENERATOR_VERSION
    canonical = json.dumps({'generator':generator_version,'board':b,'manufacturingPolicyVersion':policy_version,
                            'manufacturingProfile':profile_key,'manufacturing':profile}, sort_keys=True, separators=(',',':'))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    token = digest[:12]
    geometry_digest=hashlib.sha256(json.dumps({'generator':GEOMETRY_VERSION,'board':b},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    fmt = lambda v: f'{v:g}'
    hole_label = 'M6×1.00' if b['holeType']=='M6_through' else f'Ø{fmt(b["holeDiameterMm"])} 通孔'
    stem = f'面包板_{fmt(b["widthMm"])}x{fmt(b["heightMm"])}x{fmt(b["thicknessMm"])}_{"M6" if b["holeType"]=="M6_through" else "D"+fmt(b["holeDiameterMm"])}_{token}'
    mounts=[dict(hole,label=f'H{i+1}',xMm=round(e+hole['columnIndex']*p,6),yMm=round(e+hole['rowIndex']*p,6)) for i,hole in enumerate(b['mountingHoles'])]
    return {
        'generatorVersion':generator_version,'board':b,'digest':digest,
        'componentId':'breadboard-'+token,'model':'ZZ-BB-'+geometry_digest[:12].upper(),'filenameStem':stem,
        'geometryDigest':geometry_digest,'manufacturingPolicyVersion':policy_version,'manufacturingProfile':profile_key,
        'gridColumns':nx,'gridRows':ny,'holeCount':nx*ny,'holeCallout':hole_label,
        'regularHoleCount':nx*ny-len(mounts),'mountingHoleCount':len(mounts),'mountingHoles':mounts,
        'counterbore':dict(COUNTERBORE),'counterboreCallout':'Ø6.6 通孔；顶面 Ø11 圆柱沉孔，深 6.5',
        'mountingScrew':'M6 内六角圆柱头螺钉（ISO 4762 / DIN 912）；长度、等级及材质待选',
        'counterboreSourceUrl':COUNTERBORE_SOURCE,'mountingMinimumWebMm':MIN_MOUNTING_WEB_MM,
        'leftMarginMm':e,'bottomMarginMm':e,'rightMarginMm':right,'topMarginMm':top,
        'coordinateSystem':'New parameter model: XY breadboard plane, origin lower-left on top face, +Z up; bottom face Z=-thickness.',
        **profile,'threadClass':profile['threadClass'] if b['holeType']=='M6_through' else '不适用',
        'stepThreadRepresentation':'tap_drill_cylinder_no_helical_thread' if b['holeType']=='M6_through' else 'plain_cylinder',
    }


def board_row(board):
    from registered_boards import registered, row
    if registered(board):return row(board)
    s = board_specs(board); b=s['board']
    notes = [f'新参数板；{s["gridColumns"]}列×{s["gridRows"]}行，共{s["holeCount"]}孔；其中{s["regularHoleCount"]}个{s["holeCallout"]}；孔距{b["pitchMm"]:g} mm',
             f'左/下边距{b["edgeOffsetMm"]:g} mm，右边距{s["rightMarginMm"]:g} mm，上边距{s["topMarginMm"]:g} mm',
             f'材料：{s["material"]}；表面处理：{s["surfaceTreatment"]}']
    if s['mountingHoleCount']:
        notes.append(f'{s["mountingHoleCount"]}个安装孔替换对应普通孔：{s["counterboreCallout"]}；孔位见图纸，各组内坐标差为25 mm整数倍')
        notes.append('圆柱头螺钉头部下沉；螺钉长度及拧紧要求待确认')
    else:notes.append('未设置面包板安装沉孔；不复制原归档板角部沉孔')
    if b['holeType']=='M6_through':notes.append('STEP 用 Ø5 通底孔表示 M6 螺纹位置，未建螺旋牙；螺纹等级待确认，按 PDF 标注加工')
    return {'componentId':s['componentId'],'name':f'参数面包板 {b["widthMm"]:g} × {b["heightMm"]:g} × {b["thicknessMm"]:g} mm',
            'model':s['model'],'kind':'custom','unit':'块','quantity':1,'status':'加工审核版',
            'notes':'；'.join(notes),'stepPath':None,'drawingPath':None,'sourceUrl':'','kits':[],
            'generatedBoard':True,'boardSpec':s}


def _valid_cache(folder, spec):
    try:
        if folder.is_symlink():return False
        report=json.loads((folder/'artifact.json').read_text())
        if report.get('digest')!=spec['digest'] or report.get('generatorVersion')!=spec['generatorVersion']:return False
        for key, suffix in (('step','.step'),('drawing','.pdf')):
            f=folder/(spec['filenameStem']+suffix)
            if f.is_symlink() or not f.is_file() or f.stat().st_size<100:return False
            if hashlib.sha256(f.read_bytes()).hexdigest()!=report['sha256'][key]:return False
        return True
    except (OSError,ValueError,KeyError):return False


def ensure_board_artifacts(board, cache_dir, cad_python=None):
    from registered_boards import registered
    if registered(board):
        raise BreadboardError('registered_board_no_generator','登记异形面包板使用已核对的原模型和图纸；不能按矩形参数自动生成，缺失制造资料须补齐后再下载。',409)
    """Return trusted generated paths; cached results work even if CAD is offline.

    cad_python is an operator-set path, never a request field. The caller should
    pass a private, writable cache root. Worker output is committed atomically.
    """
    spec=board_specs(board)
    cache=Path(cache_dir).resolve();cache.mkdir(parents=True,exist_ok=True)
    folder=cache/spec['digest']
    if _valid_cache(folder,spec):return _result(folder,spec)
    python=cad_python or os.environ.get('ZZLAB_CAD_PYTHON')
    if not python or not Path(python).is_file():
        raise BreadboardError('cad_unavailable','面包板 CAD 生成服务尚未配置，请管理员设置 ZZLAB_CAD_PYTHON。',503)
    worker=Path(__file__).with_name('breadboard_worker.py').resolve()
    # Serialize heavyweight CAD jobs across server threads/processes. Validate
    # again after acquiring the lock so concurrent identical requests share work.
    with (cache/'.cad-worker.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        if _valid_cache(folder,spec):return _result(folder,spec)
        tmp=Path(tempfile.mkdtemp(prefix='.board-',dir=cache))
        try:
            input_path=tmp/'request.json';input_path.write_text(json.dumps(spec['board'],ensure_ascii=False))
            try:
                p=subprocess.run([str(python),str(worker),'--request',str(input_path),'--out',str(tmp)],
                                 cwd=str(worker.parent),capture_output=True,text=True,timeout=CAD_TIMEOUT_SECONDS,check=False)
            except OSError as exc:
                raise BreadboardError('cad_unavailable','面包板 CAD 解释器无法启动，请检查服务配置。',503) from exc
            except subprocess.TimeoutExpired as exc:
                raise BreadboardError('cad_timeout','面包板 CAD 生成超过 180 秒，请缩小板尺寸或增大孔距后重试。',503) from exc
            if p.returncode!=0 or not _valid_cache(tmp,spec):
                raise BreadboardError('cad_failed','面包板 STEP / 图纸生成未完成，请检查 CAD 服务依赖或参数后重试。',503)
            if folder.exists():shutil.rmtree(folder)
            tmp.rename(folder)
        finally:
            if tmp.exists():shutil.rmtree(tmp)
    return _result(folder,spec)


def _result(folder,spec):
    return {'step':folder/(spec['filenameStem']+'.step'),'drawing':folder/(spec['filenameStem']+'.pdf'),
            'spec':spec,'componentId':spec['componentId'],'model':spec['model'],'filenameStem':spec['filenameStem']}
