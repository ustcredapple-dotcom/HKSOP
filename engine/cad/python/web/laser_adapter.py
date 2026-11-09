"""Server-derived laser alignment plate geometry and manufacturing identity.

All XY positions use the laser housing-centre datum. The supplied drawing fixes
the 50 x 250 mm pattern but not its absolute housing datum; that remains explicit.
"""
from __future__ import annotations

import hashlib
import json
import math

from bom import APIError

EPS = 1e-5
SCHEMA_VERSION = "zzlab-laser-adapter-v1"
GENERATOR_VERSION = "laser-adapter-2026-09-28.1"
FIELDS = {"enabled", "thicknessMm", "mountingOriginXMm", "mountingOriginYMm", "mountingDatumConfirmed"}
OUTLINE = {"xMin": -283, "xMax": 260, "yMin": -130.5, "yMax": 130.5}
THREAD = {"designation": "M6×1 通螺纹", "nominalDiameterMm": 6, "pitchMm": 1, "stepDiameterMm": 5}
COUNTERBORE = {"clearanceDiameterMm": 6.6, "diameterMm": 11, "depthMm": 6.5}


def _number(value, label, minimum, maximum):
    if (type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum
            or abs(value*10-round(value*10)) > EPS):
        raise APIError("invalid_laser_adapter", f"{label}须为 {minimum:g} 至 {maximum:g} mm，精度 0.1 mm。")
    return round(value*10)/10


def normalize_settings(source):
    if "laserAdapter" not in source:
        return {}
    raw = source["laserAdapter"]
    if (source.get("kitId") != "laser-308nm" or not isinstance(raw, dict) or set(raw)-FIELDS
            or type(raw.get("enabled")) is not bool):
        raise APIError("invalid_laser_adapter", "光轴对齐垫板仅适用于 308 nm 激光器，请使用有效的垫板设置。")
    if not raw["enabled"]:
        raise APIError("invalid_laser_adapter", "关闭激光器垫板时请删除垫板设置字段。")
    result = {"enabled": True, "thicknessMm": _number(raw.get("thicknessMm"), "垫板厚度", 8.5, 50)}
    for field in ("mountingOriginXMm", "mountingOriginYMm"):
        if field in raw:
            result[field] = _number(raw[field], "激光器孔组基准", -500, 500)
    if "mountingDatumConfirmed" in raw:
        if type(raw["mountingDatumConfirmed"]) is not bool:
            raise APIError("invalid_laser_adapter", "实物孔位核对标记必须为布尔值。")
        result["mountingDatumConfirmed"] = raw["mountingDatumConfirmed"]
    return {"laserAdapter": result}


def enabled(instance):
    return isinstance(instance.get("laserAdapter"), dict) and instance["laserAdapter"].get("enabled") is True


def outline_bounds(geometry=None):
    # Keep the physical plate footprint fixed; changed screw datums must fit it.
    return dict(OUTLINE)


def thread_holes(settings):
    ox, oy = float(settings.get("mountingOriginXMm", 83.5)), float(settings.get("mountingOriginYMm", -125))
    return [{"label": f"T{index+1}", "xMm": round(ox+x, 6), "yMm": round(oy+y, 6)}
            for index, (x, y) in enumerate(((0, 0), (50, 0), (50, 250), (0, 250)))]


def _transform(instance, x, y):
    c, s = {0:(1,0), 90:(0,1), 180:(-1,0), 270:(0,-1)}[instance["rotationDeg"]]
    return instance["xMm"]+c*x-s*y, instance["yMm"]+s*x+c*y


def _inverse(instance, x, y):
    c, s = {0:(1,0), 90:(0,1), 180:(-1,0), 270:(0,-1)}[instance["rotationDeg"]]
    dx, dy = x-instance["xMm"], y-instance["yMm"]
    return round(c*dx+s*dy, 6), round(-s*dx+c*dy, 6)


def _residue(value):
    result = value % 25
    return 0 if result < EPS or 25-result < EPS else round(result, 6)


def choose_board_holes(instance, owner_board, bounds, threads):
    """Four corner holes in one 25 mm XY phase, ignoring overhead laser casing."""
    if owner_board["holeType"] != "M6_through":
        return []
    pitch, edge = owner_board["pitchMm"], owner_board["edgeOffsetMm"]
    nx = math.floor((owner_board["widthMm"]-2*edge)/pitch)+1
    ny = math.floor((owner_board["heightMm"]-2*edge)/pitch)+1
    unavailable = {(h["columnIndex"], h["rowIndex"]) for h in owner_board.get("mountingHoles", [])}
    groups = {}
    for row in range(ny):
        y = edge+row*pitch
        for column in range(nx):
            if (column, row) in unavailable:
                continue
            x = edge+column*pitch
            lx, ly = _inverse(instance, x, y)
            if min(lx-bounds["xMin"], bounds["xMax"]-lx, ly-bounds["yMin"], bounds["yMax"]-ly) < 7.5-EPS:
                continue
            if any(math.hypot(lx-h["xMm"], ly-h["yMm"]) < 10.5-EPS for h in threads):
                continue
            # This ordering is row/column parity order 00,01,10,11 at 12.5 mm.
            key = (_residue(y-edge), _residue(x-edge))
            groups.setdefault(key, []).append({"xMm": lx, "yMm": ly})
    corners = [(bounds["xMin"], bounds["yMin"]), (bounds["xMax"], bounds["yMin"]),
               (bounds["xMax"], bounds["yMax"]), (bounds["xMin"], bounds["yMax"])]
    mid_x, mid_y = (bounds["xMin"]+bounds["xMax"])/2, (bounds["yMin"]+bounds["yMax"])/2
    choices = []
    for phase, candidates in sorted(groups.items()):
        selected, cost = [], 0
        for cx, cy in corners:
            quadrant = [h for h in candidates if ((h["xMm"] < mid_x-EPS) if cx < mid_x else (h["xMm"] > mid_x+EPS))
                        and ((h["yMm"] < mid_y-EPS) if cy < mid_y else (h["yMm"] > mid_y+EPS))]
            ranked = sorted(quadrant, key=lambda h: ((h["xMm"]-cx)**2+(h["yMm"]-cy)**2, h["yMm"], h["xMm"]))
            chosen = next((h for h in ranked if all(math.hypot(h["xMm"]-p["xMm"], h["yMm"]-p["yMm"]) >= 11-EPS for p in selected)), None)
            if chosen is None:
                break
            selected.append(chosen)
            cost += (chosen["xMm"]-cx)**2+(chosen["yMm"]-cy)**2
        if len(selected) == 4:
            choices.append((round(cost, 8), phase, selected))
    if not choices:
        return []
    chosen = min(choices, key=lambda item: (item[0], item[1]))[2]
    return [{"label": f"H{i+1}", **hole} for i, hole in enumerate(chosen)]


def _create_spec(settings, holes):
    provided = "mountingOriginXMm" in settings or "mountingOriginYMm" in settings
    confirmed = settings.get("mountingDatumConfirmed", False)
    datum_source = "用户声明已按实物核对" if confirmed else ("用户填写基准，待实物核对" if provided else "用户三视图估读，待实物核对")
    notes = ["加工审核版；不能视为已核准生产图", "激光器安装孔间距 50×250 mm；绝对孔组基准来源："+datum_source,
             "先将垫板固定到面包板，再安装激光器；沉孔可位于激光器壳体下方",
             "4×M6×1 通螺纹；STEP 用 Ø5 通底孔表示，不建螺旋牙",
             "4×Ø6.6 通孔，顶面 Ø11 深6.5圆柱沉孔；四固定孔坐标差为25 mm整数倍"]
    value = {"schemaVersion": SCHEMA_VERSION, "generatorVersion": GENERATOR_VERSION,
             "thicknessMm": settings["thicknessMm"], "outlineBoundsMm": dict(OUTLINE),
             "laserThreadHolesMm": thread_holes(settings), "boardMountingHolesMm": holes,
             "thread": dict(THREAD), "counterbore": dict(COUNTERBORE),
             "material": "6061 铝合金", "surfaceTreatment": "黑色阳极氧化",
             "opticalAxisHeightMm": 135, "axisHeightMm": round(135+settings["thicknessMm"], 6),
             "opticalPortMm": {"xMm": -283, "yMm": 67},
             "mountingOriginXMm": float(settings.get("mountingOriginXMm", 83.5)), "mountingOriginYMm": float(settings.get("mountingOriginYMm", -125)),
             "mountingDatumConfirmed": confirmed, "mountingDatumProvided": provided,
             "datumSource": datum_source, "status": "加工审核版", "notes": "；".join(notes)}
    digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**value, "digest": digest, "componentId": "laser-adapter-"+digest[:16],
            "model": "LASER-308-ADP-"+digest[:10].upper(),
            "filenameStem": f"308nm激光器光轴对齐垫板_543x261x{settings['thicknessMm']:g}_{digest[:12]}"}


def validate_adapter_spec(source):
    """Rebuild the complete canonical spec before generated-file/cache access."""
    def invalid():
        raise APIError("invalid_laser_adapter_spec", "激光器垫板规格或几何校验失败，请按当前布局重新生成。", 409)
    if not isinstance(source, dict) or type(source.get("mountingDatumProvided")) is not bool or type(source.get("mountingDatumConfirmed")) is not bool:
        invalid()
    settings = {"enabled": True, "thicknessMm": source.get("thicknessMm"), "mountingDatumConfirmed": source["mountingDatumConfirmed"]}
    if source["mountingDatumProvided"]:
        settings.update(mountingOriginXMm=source.get("mountingOriginXMm"), mountingOriginYMm=source.get("mountingOriginYMm"))
    settings = normalize_settings({"kitId": "laser-308nm", "laserAdapter": settings})["laserAdapter"]
    holes = source.get("boardMountingHolesMm")
    if not isinstance(holes, list) or len(holes) != 4:
        invalid()
    for index, hole in enumerate(holes):
        if (not isinstance(hole, dict) or set(hole) != {"label", "xMm", "yMm"} or hole["label"] != f"H{index+1}"
                or any(type(hole[k]) not in (int, float) or not math.isfinite(hole[k]) for k in ("xMm", "yMm"))):
            invalid()
        x, y = hole["xMm"], hole["yMm"]
        left, lower = index in (0, 3), index in (0, 1)
        if not ((x < -11.5-EPS if left else x > -11.5+EPS) and (y < -EPS if lower else y > EPS)):
            invalid()
        if min(x-OUTLINE["xMin"], OUTLINE["xMax"]-x, y-OUTLINE["yMin"], OUTLINE["yMax"]-y) < 7.5-EPS:
            invalid()
        if any(math.hypot(x-t["xMm"], y-t["yMm"]) < 10.5-EPS for t in thread_holes(settings)):
            invalid()
        for prior in holes[:index]:
            dx, dy = x-prior["xMm"], y-prior["yMm"]
            if math.hypot(dx, dy) < 11-EPS or any(abs(v/25-round(v/25)) > EPS for v in (dx, dy)):
                invalid()
    for hole in thread_holes(settings):
        if min(hole["xMm"]-OUTLINE["xMin"], OUTLINE["xMax"]-hole["xMm"], hole["yMm"]-OUTLINE["yMin"], OUTLINE["yMax"]-hole["yMm"]) < 5-EPS:
            invalid()
    canonical = _create_spec(settings, holes)
    if source != canonical:
        invalid()
    return canonical


def beam_alignment(instance, geometry, root_board, plate=None):
    port = next((p for p in geometry.get("opticalPortsMm", []) if p.get("id") == "output"), None)
    if port is None:
        raise APIError("kit_layout_missing", "激光器光口位置尚未登记。", 409)
    x, y = _transform(instance, port["xMm"], port["yMm"])
    rotation = instance["rotationDeg"]
    if plate:
        x, y = _transform(plate, x, y)
        rotation = (rotation+plate["rotationDeg"]) % 360
    coordinate, limit = (y, root_board["heightMm"]) if rotation in (0, 180) else (x, root_board["widthMm"])
    n = (coordinate-root_board["edgeOffsetMm"])/root_board["pitchMm"]
    valid = coordinate >= root_board["edgeOffsetMm"]-EPS and coordinate <= limit-root_board["edgeOffsetMm"]+EPS and abs(n-round(n)) <= EPS
    return {"beamPortMm": {"xMm": round(x, 6), "yMm": round(y, 6)}, "globalRotationDeg": rotation, "beamAligned": valid}


def derive_adapter(instance, geometry, owner_board):
    settings = instance["laserAdapter"]
    threads = thread_holes(settings)
    holes = choose_board_holes(instance, owner_board, OUTLINE, threads)
    record = {"instanceId": instance["id"], "boardId": instance.get("boardId"),
              "spec": _create_spec(settings, holes), **beam_alignment(instance, geometry, owner_board)}
    issues = []
    def issue(code, message):
        issues.append({"code": code, "instanceIds": [instance["id"]], "message": message})
    if len(holes) != 4:
        message = ("激光器垫板需要连接面包板的 M6 螺纹孔；当前承接板为普通通孔，请调整板孔类型。"
                   if owner_board["holeType"] != "M6_through" else
                   "垫板内找不到四个可用固定孔：沉孔可位于激光器机身下方，但不能与激光器安装螺纹孔或承接板已有沉孔重合，且须满足孔边距及水平、竖直 25 mm 倍数间距。")
        issue("adapter_mounting_unavailable", message)
    if any(min(t["xMm"]-OUTLINE["xMin"], OUTLINE["xMax"]-t["xMm"], t["yMm"]-OUTLINE["yMin"], OUTLINE["yMax"]-t["yMm"]) < 5-EPS for t in threads):
        issue("adapter_thread_out_of_bounds", "激光器螺纹孔组超出垫板有效范围，M6 孔中心须距边至少 5 mm；请核对实物基准。")
    if not record["beamAligned"]:
        issue("adapter_beam_off_grid", "激光器光口未沿大面包板有效孔行或孔列出光，请调整激光器位置。")
    alignment = {"instanceId": instance["id"], "kitId": instance["kitId"], "alignedCount": len(holes),
                 "totalCount": 4, "requiredCount": 4, "partial": False,
                 "alignedPositionsMm": [{"xMm": round(p[0], 6), "yMm": round(p[1], 6)} for hole in holes for p in [_transform(instance, hole["xMm"], hole["yMm"])]]}
    return record, alignment, issues


def adapter_row(record):
    spec = record["spec"]
    return {"componentId": spec["componentId"], "name": f"308 nm 激光器光轴对齐垫板 · {spec['thicknessMm']:g} mm",
            "model": spec["model"], "kind": "custom", "unit": "块", "quantity": 1, "status": spec["status"],
            "notes": spec["notes"], "stepPath": None, "drawingPath": None, "sourceUrl": "",
            "manufacturingSpec": {"material": spec["material"], "surfaceTreatment": spec["surfaceTreatment"]},
            "generatedLaserAdapter": True, "adapterSpec": spec,
            "kits": [{"kitId": "laser-308nm", "name": "308 nm 激光器光轴对齐垫板", "kitQuantity": 1,
                      "perKitQuantity": 1, "quantity": 1, "source": "laserAdapter", "instanceId": record["instanceId"]}]}
