"""Local-editor exceptions; upstream modules remain strict outside this context."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import math

_notes = ContextVar('zzlab_local_expert_notes', default=None)
_installed = False


def enabled():
    return _notes.get() is not None


def warn(code, message, **details):
    notes = _notes.get()
    if notes is not None:
        item = {'code': code, 'message': message, 'severity': 'warning', **details}
        if item not in notes:
            notes.append(item)


def _mounting_holes(holes, board, nx, ny, nominal, strict):
    if not enabled():
        return strict(holes, board, nx, ny, nominal)
    from breadboard import BreadboardError
    if not isinstance(holes, list) or len(holes) > nx * ny:
        raise BreadboardError('invalid_mounting_holes', '安装孔须为板内实际孔阵位置的数组。')
    clean = []
    for hole in holes:
        if not isinstance(hole, dict) or set(hole) != {'columnIndex', 'rowIndex'}:
            raise BreadboardError('invalid_mounting_holes', '安装孔只接受 columnIndex、rowIndex 两个从 0 开始的孔阵索引。')
        col, row = hole['columnIndex'], hole['rowIndex']
        if type(col) is not int or type(row) is not int or not (0 <= col < nx and 0 <= row < ny):
            raise BreadboardError('invalid_mounting_holes', '安装孔索引必须为板内孔阵的整数位置。')
        clean.append({'columnIndex': col, 'rowIndex': row})
    clean.sort(key=lambda h: (h['rowIndex'], h['columnIndex']))
    if len({(h['columnIndex'], h['rowIndex']) for h in clean}) != len(clean):
        raise BreadboardError('invalid_mounting_holes', '安装孔不能重复。')
    if not clean:
        return clean
    if len(clean) < 4:
        warn('mounting_support_review', f'本板选择了 {len(clean)} 个安装孔；固定方式和承载能力由使用者确认。', mountingHoleCount=len(clean))
    if board['thicknessMm'] < 8.5:
        warn('mounting_plate_too_thin', 'M6 圆柱沉孔深 6.5 mm；当前板厚不足 8.5 mm，请核对沉孔底部厚度。')
    pitch, edge = board['pitchMm'], board['edgeOffsetMm']
    selected = {(h['columnIndex'], h['rowIndex']) for h in clean}
    for hole in clean:
        col, row = hole['columnIndex'], hole['rowIndex']
        x, y = edge + col * pitch, edge + row * pitch
        if min(x, y, board['widthMm'] - x, board['heightMm'] - y) < 7.5 - 1e-7:
            warn('mounting_hole_near_edge', '安装沉孔中心距板边不足 7.5 mm，请核对边壁。', holePositionMm={'xMm': x, 'yMm': y})
        # Only nearby grid points can intersect a counterbore; keep large boards cheap.
        reach = math.ceil((11 + nominal / 2 + 2) / pitch)
        for j in range(max(0, row-reach), min(ny, row+reach+1)):
            for i in range(max(0, col-reach), min(nx, col+reach+1)):
                if (i, j) == (col, row):
                    continue
                other_mount = (i, j) in selected
                minimum = 11 if other_mount else 5.5 + nominal/2 + 2
                if math.hypot(i-col, j-row) * pitch < minimum - 1e-7:
                    warn('mounting_hole_web', '安装沉孔与相邻孔重叠或净距不足，请核对实际加工和固定方式。')
    return clean


def install():
    """Install one context-sensitive hook; never replace strict behavior globally."""
    global _installed
    if _installed:
        return
    import breadboard
    strict = breadboard._normalize_mounting_holes
    def guarded(holes, board, nx, ny, nominal):
        return _mounting_holes(holes, board, nx, ny, nominal, strict)
    breadboard._normalize_mounting_holes = guarded
    _installed = True


@contextmanager
def expert_mode():
    """Yield physical-review warnings for this request, without relaxing JSON checks."""
    install()
    notes = []
    token = _notes.set(notes)
    try:
        yield notes
    finally:
        _notes.reset(token)
