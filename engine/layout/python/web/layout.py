"""Breadboard poses use millimetres and a lower-left origin; catalog owns geometry."""
from __future__ import annotations

import base64
import html
import json
import math
from pathlib import Path, PurePosixPath

from bom import APIError

MAX_INSTANCES = 500
MAX_LAYOUT_ASSET_BYTES = 32 * 1024 * 1024
EPSILON = 1e-5


def number(value, label, minimum=0, maximum=5000):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise APIError("invalid_layout", f"{label}必须是 {minimum} 至 {maximum} 之间的有限数字。")
    return round(value, 6)


def kit_geometry(kit):
    geometry = kit.get("layout")
    if not isinstance(geometry, dict):
        raise APIError("kit_layout_missing", f"套件“{kit['name']}”尚未登记俯视图尺寸。", 409)
    result = dict(geometry)
    if "baseOverhangAllowedWithPartialMounting" in geometry:
        if type(geometry["baseOverhangAllowedWithPartialMounting"]) is not bool:
            raise APIError("kit_layout_missing", "底座部分悬出规则必须为目录中的布尔值。", 409)
        if geometry["baseOverhangAllowedWithPartialMounting"]:
            minimum = geometry.get("minimumAlignedMountingHoles")
            holes = geometry.get("mountingHoleOffsetsMm")
            if (type(minimum) is not int or not 2 <= minimum <= 128 or
                    not isinstance(holes, list) or len(holes) < minimum):
                raise APIError("kit_layout_missing", "底座部分悬出必须登记至少两个实际安装孔及明确的最少对齐孔数。", 409)
    for field in ("widthMm", "heightMm"):
        result[field] = number(geometry.get(field), f"{kit['name']} {field}", 0.01, 5000)
    result["anchorXMm"] = number(geometry.get("anchorXMm"), "安装锚点 X", 0, result["widthMm"])
    result["anchorYMm"] = number(geometry.get("anchorYMm"), "安装锚点 Y", 0, result["heightMm"])
    path = result.get("topViewPath")
    if path is None and isinstance(result.get("topViewUrl"), str):
        path = result["topViewUrl"].removeprefix("./")
    if not isinstance(path, str) or not path or "\\" in path or ":" in path or "\x00" in path or any(p in ("", ".", "..") for p in path.split("/")):
        raise APIError("kit_layout_missing", f"套件“{kit['name']}”的俯视图路径未登记。", 409)
    if PurePosixPath(path).is_absolute() or PurePosixPath(path).suffix.lower() not in (".svg", ".png", ".webp"):
        raise APIError("kit_layout_missing", f"套件“{kit['name']}”的俯视图格式未登记。", 409)
    result["topViewPath"] = path
    return result


def local_bounds(geometry, field="collisionBoundsMm"):
    bounds = geometry.get(field)
    if bounds is None:
        # Conservative compatibility fallback: the complete registered image envelope.
        bounds = {"xMin": -geometry["anchorXMm"], "xMax": geometry["widthMm"]-geometry["anchorXMm"],
                  "yMin": geometry["anchorYMm"]-geometry["heightMm"], "yMax": geometry["anchorYMm"]}
    if not isinstance(bounds, dict) or set(bounds) != {"xMin", "xMax", "yMin", "yMax"}:
        raise APIError("kit_layout_missing", "套件边界未按目录契约登记。", 409)
    result = {key: number(value, "器件边界", -5000, 5000) for key, value in bounds.items()}
    if result["xMin"] >= result["xMax"] or result["yMin"] >= result["yMax"]:
        raise APIError("kit_layout_missing", "套件边界必须具有正的宽度和高度。", 409)
    return result


def footprint(instance, geometry, field="collisionBoundsMm"):
    bounds = local_bounds(geometry, field)
    theta = math.radians(instance["rotationDeg"])
    c, s = round(math.cos(theta)), round(math.sin(theta))
    points = []
    for dx, dy in ((bounds["xMin"], bounds["yMin"]), (bounds["xMax"], bounds["yMin"]),
                   (bounds["xMin"], bounds["yMax"]), (bounds["xMax"], bounds["yMax"])):
        points.append((instance["xMm"]+c*dx-s*dy, instance["yMm"]+s*dx+c*dy))
    return {"left": min(p[0] for p in points), "right": max(p[0] for p in points),
            "top": min(p[1] for p in points), "bottom": max(p[1] for p in points)}


def rect_polygon(bounds):
    return [(bounds["xMin"], bounds["yMin"]), (bounds["xMax"], bounds["yMin"]),
            (bounds["xMax"], bounds["yMax"]), (bounds["xMin"], bounds["yMax"])]


def collision_polygons(geometry):
    raw = geometry.get("collisionPolygonsMm")
    if raw in (None, []):
        return [rect_polygon(local_bounds(geometry))]
    if not isinstance(raw, list) or len(raw) > 128:
        raise APIError("kit_layout_missing", "套件细轮廓片区未按目录契约登记。", 409)
    result, vertices = [], 0
    for polygon in raw:
        if not isinstance(polygon, list) or not 3 <= len(polygon) <= 2048:
            raise APIError("kit_layout_missing", "套件细轮廓必须为至少三个点的多边形。", 409)
        points = []
        for point in polygon:
            if not isinstance(point, dict) or set(point) != {"xMm", "yMm"}:
                raise APIError("kit_layout_missing", "套件细轮廓点必须使用xMm、yMm坐标。", 409)
            value = (number(point["xMm"], "轮廓X", -5000, 5000), number(point["yMm"], "轮廓Y", -5000, 5000))
            if not points or value != points[-1]:
                points.append(value)
        if points[0] == points[-1]:
            points.pop()
        vertices += len(points)
        area = sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(points, points[1:]+points[:1]))
        if len(points) < 3 or abs(area) <= EPSILON or vertices > 8192:
            raise APIError("kit_layout_missing", "套件细轮廓退化或点数过多。", 409)
        result.append(points)
    return result


def transform_point(instance, point):
    c, sine = {0:(1,0), 90:(0,1), 180:(-1,0), 270:(0,-1)}[instance["rotationDeg"]]
    return instance["xMm"]+c*point[0]-sine*point[1], instance["yMm"]+sine*point[0]+c*point[1]


def polygon_bounds(points):
    return {"left": min(p[0] for p in points), "right": max(p[0] for p in points),
            "top": min(p[1] for p in points), "bottom": max(p[1] for p in points)}


def boxes_touch(a, b):
    return (min(a["right"],b["right"])-max(a["left"],b["left"]) >= -EPSILON and
            min(a["bottom"],b["bottom"])-max(a["top"],b["top"]) >= -EPSILON)


def point_segment_distance(point, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length2 = dx*dx+dy*dy
    fraction = max(0, min(1, ((point[0]-a[0])*dx+(point[1]-a[1])*dy)/length2)) if length2 else 0
    return math.hypot(point[0]-a[0]-fraction*dx, point[1]-a[1]-fraction*dy)


def point_in_polygon(point, polygon):
    inside = False
    for a, b in zip(polygon, polygon[1:]+polygon[:1]):
        if point_segment_distance(point,a,b) <= EPSILON:
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            crossing = a[0]+(point[1]-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if point[0] < crossing:
                inside = not inside
    return inside


def segments_touch(a, b, c, d):
    if not boxes_touch(polygon_bounds([a,b]),polygon_bounds([c,d])):
        return False
    if min(point_segment_distance(a,c,d),point_segment_distance(b,c,d),
           point_segment_distance(c,a,b),point_segment_distance(d,a,b)) <= EPSILON:
        return True
    cross = lambda u,v,w:(v[0]-u[0])*(w[1]-u[1])-(v[1]-u[1])*(w[0]-u[0])
    return cross(a,b,c)*cross(a,b,d) < 0 and cross(c,d,a)*cross(c,d,b) < 0


def polygons_touch(a, b):
    if not boxes_touch(polygon_bounds(a),polygon_bounds(b)):
        return False
    for a1,a2 in zip(a,a[1:]+a[:1]):
        for b1,b2 in zip(b,b[1:]+b[:1]):
            if segments_touch(a1,a2,b1,b2):
                return True
    return point_in_polygon(a[0],b) or point_in_polygon(b[0],a)


def circle_touches_polygon(center, radius, polygon, bounds=None):
    circle_box = {"left":center[0]-radius,"right":center[0]+radius,"top":center[1]-radius,"bottom":center[1]+radius}
    if not boxes_touch(circle_box, bounds or polygon_bounds(polygon)):
        return False
    return point_in_polygon(center,polygon) or any(point_segment_distance(center,a,b) <= radius+EPSILON for a,b in zip(polygon,polygon[1:]+polygon[:1]))


def world_geometry(instance, geometry):
    from laser_adapter import enabled, outline_bounds
    polygons = [[transform_point(instance,p) for p in poly] for poly in collision_polygons(geometry)]
    base = [transform_point(instance,p) for p in rect_polygon(local_bounds(geometry,"baseBoundsMm"))]
    if enabled(instance):
        adapter = [transform_point(instance,p) for p in rect_polygon(outline_bounds(geometry))]
        polygons.append(adapter)
        base_box = polygon_bounds(base+adapter)
        base = [(base_box["left"],base_box["top"]),(base_box["right"],base_box["top"]),
                (base_box["right"],base_box["bottom"]),(base_box["left"],base_box["bottom"])]
    radius = number(geometry.get("mountingHoleRadiusMm",3.3), "安装孔保护半径", .01, 100)
    mounts = []
    for hole in geometry.get("mountingHoleOffsetsMm",[]):
        if not isinstance(hole,dict) or set(hole) != {"xMm","yMm"}:
            raise APIError("kit_layout_missing", "套件安装孔偏移未按目录契约登记。",409)
        point = (number(hole["xMm"],"安装孔X",-5000,5000),number(hole["yMm"],"安装孔Y",-5000,5000))
        mounts.append((*transform_point(instance,point),radius))
    return {"instance":instance,"polygons":polygons,"polygonBounds":[polygon_bounds(p) for p in polygons],
            "bounds":polygon_bounds([point for p in polygons for point in p]),
            "basePolygon":base,"baseBounds":polygon_bounds(base),"mounts":mounts}


def shapes_touch(a, b):
    if not boxes_touch(a["bounds"],b["bounds"]):
        return False
    return any(boxes_touch(ab,bb) and polygons_touch(ap,bp)
               for ap,ab in zip(a["polygons"],a["polygonBounds"]) for bp,bb in zip(b["polygons"],b["polygonBounds"]))


def hole_obstructs_shape(center, radius, shape):
    # The brown physical silhouette alone determines access. Blue base bounds
    # and mounting reference circles do not add invisible obstruction zones.
    return any(circle_touches_polygon(center,radius,p,b) for p,b in zip(shape["polygons"],shape["polygonBounds"]))


def mounting_alignment(instance, geometry, board):
    """Count distinct holes meeting the catalog's minimum layout alignment rule.

    This records geometric coincidence only; it is not a load-bearing check.
    """
    offsets = []
    for hole in geometry["mountingHoleOffsetsMm"]:
        if not isinstance(hole, dict) or set(hole) != {"xMm", "yMm"}:
            raise APIError("kit_layout_missing", "套件安装孔偏移未按目录契约登记。", 409)
        point = (number(hole["xMm"], "安装孔X偏移", -5000, 5000),
                 number(hole["yMm"], "安装孔Y偏移", -5000, 5000))
        if not any(abs(point[0]-prior[0]) <= EPSILON and abs(point[1]-prior[1]) <= EPSILON for prior in offsets):
            offsets.append(point)
    required = geometry.get("minimumAlignedMountingHoles", len(offsets))
    if type(required) is not int or not 1 <= required <= 128:
        raise APIError("kit_layout_missing", "套件最少对齐安装孔数必须为 1 至 128 的整数。", 409)
    aligned, mismatched = [], []
    for offset in offsets:
        x, y = transform_point(instance, offset)
        from registered_boards import registered, aligned as board_aligned
        if registered(board) or geometry.get("baseOverhangAllowedWithPartialMounting") is True:
            # Partial support may rely only on real M6 threads. A regular-grid
            # counterbore/clearance hole is not a threaded mounting location.
            threaded = registered(board) or board.get("holeType") == "M6_through"
            (aligned if threaded and board_aligned(board,(x,y)) else mismatched).append({'xMm':round(x,6),'yMm':round(y,6)})
            continue
        on_grid = True
        for coordinate, limit in ((x, board["widthMm"]), (y, board["heightMm"])):
            grid = (coordinate-board["edgeOffsetMm"])/board["pitchMm"]
            if grid < -EPSILON or coordinate > limit-board["edgeOffsetMm"]+EPSILON or abs(grid-round(grid)) > EPSILON:
                on_grid = False
                break
        (aligned if on_grid else mismatched).append({"xMm": round(x, 6), "yMm": round(y, 6)})
    return {"instanceId": instance["id"], "kitId": instance["kitId"],
            "alignedCount": len(aligned), "totalCount": len(offsets), "requiredCount": required,
            "partial": 0 < len(aligned) < len(offsets), "alignedPositionsMm": aligned}, mismatched


def base_mode_fields(raw):
    """Root-only optional mode; old projects retain their original shape."""
    if "baseMode" not in raw:
        return {}
    if not isinstance(raw["baseMode"], str) or raw["baseMode"] not in ("breadboard", "table"):
        raise APIError("invalid_layout", "工作区模式必须为 breadboard 或 table。")
    return {"baseMode": raw["baseMode"]}


def validate_layout(raw, kits, *, allow_stage_top=False):
    from collision_overrides import normalize_fields as normalize_overrides, pair_keys, permits
    from breadboard import normalize_board, board_specs, BreadboardError
    from elevation import ELEVATION_FIELDS, POST_SELECTION_FIELDS, normalize_fields, normalize_post_fields, axis_validation
    from optics_settings import normalize_fields as normalize_optics_fields, normalize_internal_fields, normalize_source_port_fields
    from manual_source_mount import normalize_fields as normalize_manual_mount, source_reference, accepted_height, output_point, output_aligned
    from laser_adapter import normalize_settings, enabled as adapter_enabled, derive_adapter
    from registered_boards import registered, aligned as board_aligned, contains_polygon, allows_covered_mounting
    if isinstance(raw, dict) and 'subBoards' in raw:
        from stacked_layout import validate_stacked
        return validate_stacked(raw, kits)
    if not isinstance(raw, dict) or not {"board", "instances"} <= set(raw) or set(raw)-{"board", "instances", "baseMode", "collisionOverrides"}:
        raise APIError("invalid_layout", "layout必须包含board和instances。")
    mode = base_mode_fields(raw)
    table = mode.get("baseMode") == "table"
    try:
        board = normalize_board(raw["board"])
    except BreadboardError as exc:
        raise APIError(exc.code, str(exc), exc.status) from exc
    if registered(board) and not allow_stage_top:
        from registered_boards import definition
        if definition(board).get('stageOnly'):
            raise APIError('stage_module_required','位移台专用顶板不能作为独立静态根板，需保留完整位移模块。')
    if not isinstance(raw["instances"], list) or len(raw["instances"]) > MAX_INSTANCES:
        raise APIError("invalid_layout", f"画布最多支持 {MAX_INSTANCES} 个器件。")
    overrides = normalize_overrides(raw, [i['id'] for i in raw['instances'] if isinstance(i,dict) and isinstance(i.get('id'),str)])
    waived_pairs = pair_keys(overrides)
    result, ids, metadata, shapes, issues, alignments, adapters = [], set(), {}, [], [], [], []
    def issue(code, instance_ids, message, **details):
        issues.append({"code": code, "instanceIds": instance_ids, "message": message, **details})
    for source in raw["instances"]:
        required = {"id", "kitId", "xMm", "yMm", "rotationDeg"}
        if not isinstance(source, dict) or not required <= set(source) or set(source)-required-ELEVATION_FIELDS-POST_SELECTION_FIELDS-{"laserAdapter", "optics", "internalOptics", "sourcePorts", "manualMount"}:
            raise APIError("invalid_layout", "每个器件必须包含id、kitId、xMm、yMm和rotationDeg。")
        iid, kid = source["id"], source["kitId"]
        if not isinstance(iid, str) or not 1 <= len(iid) <= 80 or any(ord(c) < 32 for c in iid) or iid in ids:
            raise APIError("invalid_layout", "画布器件ID不能为空、过长或重复。")
        if not isinstance(kid, str) or kid not in kits:
            raise APIError("unknown_kit", "画布包含未登记的套件。")
        ids.add(iid)
        if type(source["rotationDeg"]) is not int or source["rotationDeg"] not in (0, 90, 180, 270):
            raise APIError("invalid_layout", "器件方向必须为0、90、180或270度。")
        instance = {"id": iid, "kitId": kid,
                    "xMm": number(source["xMm"], "器件X坐标", -5000, 10000),
                    "yMm": number(source["yMm"], "器件Y坐标", -5000, 10000),
                    "rotationDeg": source["rotationDeg"], **normalize_fields(source), **normalize_post_fields(source), **normalize_settings(source), **normalize_optics_fields(source), **normalize_internal_fields(source,kits[kid]), **normalize_source_port_fields(source,kits[kid]), **normalize_manual_mount(source,kits[kid])}
        if kid not in metadata:
            metadata[kid] = kit_geometry(kits[kid])
        geometry = metadata[kid]
        manual_reference = source_reference(geometry)
        if manual_reference is not None:
            if adapter_enabled(instance) or instance.get('elevationMm',0) or instance.get('universalPostSelection'):
                raise APIError('invalid_manual_mount','人工支撑光源直接声明板面起光高，不能同时使用自动垫板、垫高或万能柱替换。',409)
            if accepted_height(instance,geometry) is None:
                issue('manual_mount_unconfirmed',[iid],'此光源需手动支撑和压板固定，填写手调后的板面光轴高并明确确认；目标62.5mm不是已测量高度。')
            if not table and not output_aligned(instance,geometry,board):
                issue('source_reference_off_grid',[iid],'名义出光口XY参考尚未落在本板已有孔阵或孔列上；此参考不是安装孔。')
        alignment = None
        mounting = geometry.get("mountingHoleOffsetsMm")
        mounting_known = isinstance(mounting, list) and 1 <= len(mounting) <= 128
        # The drawing anchor is not necessarily a screw hole. For a registered
        # mounting pattern, layout compatibility is decided below by its rotated
        # holes and catalog minimum; the anchor may lie between board holes.
        # Keep the legacy anchor check for unverified mounting references, which
        # remain unconfirmed rather than gaining inferred compatibility.
        if not mounting_known and not table and manual_reference is None:
            for field in (() if registered(board) else ("xMm", "yMm")):
                grid = (instance[field]-board["edgeOffsetMm"])/board["pitchMm"]
                limit = board["widthMm"] if field == "xMm" else board["heightMm"]
                if grid < -EPSILON or instance[field] > limit-board["edgeOffsetMm"]+EPSILON or abs(grid-round(grid)) > EPSILON:
                    issue("off_grid", [iid], f"器件 {iid}（{kits[kid]['name']}）的安装锚点没有落在板内有效孔阵格点上。")
                    break
            if registered(board) and not board_aligned(board,(instance['xMm'],instance['yMm'])):
                issue('off_grid',[iid],f'器件 {iid} 的安装锚点没有落在登记板实际螺纹孔上。')
        if geometry.get("placementAllowed") is False:
            reason = geometry.get("note") or geometry.get("notes") or "安装定位条件尚未核实。"
            issue("placement_unavailable", [iid], f"器件 {iid}（{kits[kid]['name']}）当前不能放置在参数面包板：{reason}")
        else:
            if adapter_enabled(instance) and registered(board):
                issue('adapter_registered_board_unsupported',[iid],'激光器自动垫板当前使用规则孔阵；登记异形板须另行确认垫板实际固定孔，未自动加工。')
            elif adapter_enabled(instance):
                record, alignment, adapter_issues = derive_adapter(instance, geometry, board)
                adapters.append(record)
                alignments.append(alignment)
                issues.extend(i for i in adapter_issues if not (table and i["code"] == "adapter_beam_off_grid"))
            elif not mounting_known and not table and manual_reference is None:
                issue("mounting_unconfirmed", [iid], f"器件 {iid}（{kits[kid]['name']}）的安装孔位尚未核实，不能确认与参数面包板匹配。")
            elif mounting_known:
                alignment, mismatches = mounting_alignment(instance, geometry, board)
                alignments.append(alignment)
                if not table and alignment["alignedCount"] < alignment["requiredCount"]:
                    if "minimumAlignedMountingHoles" in geometry:
                        message = f"器件 {iid}（{kits[kid]['name']}）仅有 {alignment['alignedCount']} 个安装孔对准面包板孔阵，至少需要 {alignment['requiredCount']} 个不同的孔对齐；请调整孔距或位置。"
                    else:
                        message = f"器件 {iid}（{kits[kid]['name']}）有 {len(mismatches)} 个安装孔未对准面包板孔阵；请调整孔距或位置。"
                    issue("mounting_mismatch", [iid], message, holePositionsMm=mismatches,
                          alignedCount=alignment["alignedCount"], totalCount=alignment["totalCount"],
                          requiredCount=alignment["requiredCount"])
        shape = world_geometry(instance,geometry)
        box = shape["baseBounds"]
        partial_support = (geometry.get("baseOverhangAllowedWithPartialMounting") is True and
                           not table and not adapter_enabled(instance) and alignment is not None and
                           alignment["requiredCount"] >= 2 and alignment["alignedCount"] >= alignment["requiredCount"])
        if not partial_support and (not contains_polygon(board,shape['basePolygon']) if registered(board) else box["left"] < -EPSILON or box["top"] < -EPSILON or box["right"] > board["widthMm"]+EPSILON or box["bottom"] > board["heightMm"]+EPSILON):
            issue("out_of_bounds", [iid], f"器件 {iid}（{kits[kid]['name']}）的底座边界超出面包板边界。", boundary="baseBoundsMm")
        for prior in shapes:
            if not permits('collision', [prior['instance']['id'], iid], waived_pairs) and shapes_touch(shape,prior) and len(issues) < 250:
                prior_id=prior["instance"]["id"]
                issue("collision", [prior_id,iid], f"器件 {prior_id} 与 {iid} 的实际俯视轮廓相交或接触，当前布局不可用。")
        shapes.append(shape)
        result.append(instance)
    spec = board_specs(board)
    counterbore_radius = spec.get("counterbore",{}).get("diameterMm",11)/2
    for hole in ([] if table or allows_covered_mounting(board) else spec.get("mountingHoles",[])):
        center = (hole["xMm"],hole["yMm"])
        radius = hole.get('counterboreDiameterMm',hole.get('diameterMm',counterbore_radius*2))/2
        for shape in shapes:
            if hole_obstructs_shape(center,radius,shape):
                iid=shape["instance"]["id"]
                issue("mounting_hole_obstructed",[iid],f"固定孔 {hole['label']} 的沉孔范围被器件 {iid} 遮挡；请移动器件或明确重新选择固定孔。",holeLabel=hole["label"],holePositionMm={"xMm":center[0],"yMm":center[1]})
    normalized = {"board": board, "instances": result, **mode, **overrides}
    axes, axis_issues = axis_validation(normalized, metadata, alignments, uniform=False)
    issues.extend(axis_issues)
    validation = {"valid": not issues, "issues": issues, **axes,
                  "mountingAlignment": alignments, "laserAdapters": adapters,
                  "collisions": [i for i in issues if i["code"] == "collision"],
                  "outOfBounds": [i for i in issues if i["code"] == "out_of_bounds"],
                  "mountingHoleObstructions": [i for i in issues if i["code"] == "mounting_hole_obstructed"],
                  "messages": list(dict.fromkeys(i["message"] for i in issues))}
    return normalized, metadata, validation


from registered_boards import catalog_operation


@catalog_operation
def choose_mounting_holes(catalog, payload, candidate_filter=None):
    """Explicitly select four unobstructed corner holes; never mutate a saved plan.

    HTTP payload: {catalogVersion?, layout, rowParity?, columnParity?}. Parity is
    'any' / 'odd' / 'even', based on 1-based rows from bottom and columns from left.
    """
    from breadboard import board_specs, normalize_board, BreadboardError
    if not isinstance(payload,dict) or set(payload)-{"catalogVersion","layout","rowParity","columnParity","boardId","holeCount","requires"} or "layout" not in payload:
        raise APIError("invalid_request","选孔请求只允许layout、catalogVersion、rowParity和columnParity。")
    if 'requires' in payload or isinstance(payload.get('layout'),dict) and payload['layout'].get('collisionOverrides'):
        from moving_stages import validate_capabilities
        validate_capabilities(payload.get('requires',[]), payload['layout'])
    if "catalogVersion" in payload and payload["catalogVersion"] != catalog["version"]:
        raise APIError("catalog_changed","套件目录已更新，请刷新后重新选择安装孔。",409)
    count=payload.get('holeCount',4)
    if type(count) is not int or count not in (4,8):
        raise APIError('invalid_request','安装孔数量只能是4或8。')
    if isinstance(payload['layout'],dict) and 'subBoards' in payload['layout']:
        from stacked_layout import choose_stacked
        return choose_stacked(catalog,payload)
    if isinstance(payload['layout'],dict) and payload['layout'].get('baseMode') == 'table':
        raise APIError('no_root_breadboard','桌子／无大板没有待加工的根板；请选择小面包板打孔，或切换为大面包板模式。')
    if 'boardId' in payload:
        raise APIError('invalid_layout','只有叠装工程可以指定小板。')
    from registered_boards import registered
    if registered(payload['layout'].get('board')):
        return choose_registered_mounting(catalog,payload,candidate_filter)
    if count==8:
        attempts=[]
        row=payload.get('rowParity','any');column=payload.get('columnParity','any')
        if row not in ('any','odd','even') or column not in ('any','odd','even'):
            raise APIError('invalid_parity','行列奇偶选项无效。')
        for rp in (['odd','even'] if row=='any' else [row]):
            for cp in (['odd','even'] if column=='any' else [column]):
                try:
                    groups=[choose_mounting_holes(catalog,{**payload,'holeCount':4,'rowParity':r,'columnParity':c},candidate_filter) for r,c in ((rp,cp),('even' if rp=='odd' else 'odd','even' if cp=='odd' else 'odd'))]
                    b=normalize_board({**groups[0]['board'],'mountingHoles':sum([g['mountingHoles'] for g in groups],[])})
                    layout,_,validation=validate_layout({**payload['layout'],'board':b},{k['id']:k for k in catalog['kits']})
                    spec=board_specs(b);score=sum(min(h['xMm'],b['widthMm']-h['xMm'])**2+min(h['yMm'],b['heightMm']-h['yMm'])**2 for h in spec['mountingHoles'])
                    attempts.append((score,{'mountingHoles':b['mountingHoles'],'board':b,'holes':spec['mountingHoles'],'counterbore':spec['counterbore'],'layoutValidation':validation,'selection':{'rowParity':rp,'columnParity':cp},'note':'已选择奇偶双组共8个孔。每组四孔横纵间距为25 mm整数倍；两组之间不要求25 mm。'}))
                except (APIError,BreadboardError):continue
        if not attempts:
            raise APIError('mounting_holes_unavailable','找不到奇偶双组共8个无遮挡且可用的孔；大板孔距25 mm时可能只有一组重合，请改选四孔或调整位置。',409)
        return min(attempts,key=lambda x:x[0])[1]
    parities = {key:payload.get(key,"any") for key in ("rowParity","columnParity")}
    if any(value not in ("any","odd","even") for value in parities.values()):
        raise APIError("invalid_parity","行列选择必须为any、odd或even，序号从左下角1开始。")
    source = payload["layout"]
    if not isinstance(source,dict) or not isinstance(source.get("board"),dict):
        raise APIError("invalid_layout","请先创建面包板布局。")
    # This is an explicit re-selection operation. Old positions remain untouched
    # unless the caller applies the returned board after a successful response.
    cleared = {**source,"board":{**source["board"],"mountingHoles":[]}}
    kits = {k["id"]:k for k in catalog["kits"]}
    layout,metadata,validation = validate_layout(cleared,kits)
    if any(i["code"] in ("placement_unavailable","mounting_unconfirmed") for i in validation["issues"]):
        raise APIError("mounting_layout_unconfirmed","有套件的安装定位尚未确认，不能自动选择无遮挡固定孔。",409,validation)
    board=layout["board"]
    spec=board_specs(board)
    radius=spec["counterbore"]["diameterMm"]/2
    minimum_web=spec["mountingMinimumWebMm"]
    if board["thicknessMm"] < spec["counterbore"]["depthMm"]+minimum_web:
        raise APIError("mounting_plate_too_thin","M6圆柱沉孔深6.5 mm；板厚至少8.5 mm，才能保留2 mm沉孔底部厚度。")
    shapes=[world_geometry(i,metadata[i["kitId"]]) for i in layout["instances"]]
    width,height,pitch,edge=(board[k] for k in ("widthMm","heightMm","pitchMm","edgeOffsetMm"))
    groups={}
    def selected(index,parity):
        return parity=="any" or (index+1)%2==(1 if parity=="odd" else 0)
    def phase(value):
        residual=round(value%25,6)
        return 0 if abs(residual-25)<EPSILON else residual
    for row in range(spec["gridRows"]):
        if not selected(row,parities["rowParity"]):continue
        y=round(edge+row*pitch,6)
        for column in range(spec["gridColumns"]):
            if not selected(column,parities["columnParity"]):continue
            x=round(edge+column*pitch,6)
            if candidate_filter is not None and not candidate_filter(x,y):continue
            if min(x,y,width-x,height-y) < radius+minimum_web-EPSILON:continue
            if abs(x-width/2)<=EPSILON or abs(y-height/2)<=EPSILON:continue
            if any(hole_obstructs_shape((x,y),radius,shape) for shape in shapes):continue
            # Shared residues modulo25 guarantee every horizontal and vertical
            # coordinate difference is an integer multiple of25, for any pitch.
            key=(phase(x),phase(y))
            right,top=x>width/2,y>height/2
            corner=(1 if right else 0)+(2 if top else 0)
            cost=(width-x if right else x)**2+(height-y if top else y)**2
            candidate={"columnIndex":column,"rowIndex":row}
            score=(cost,row,column)
            entry=groups.setdefault(key,{})
            if corner not in entry or score<entry[corner][0]:entry[corner]=(score,candidate)
    possibilities=[]
    for phase_key,corners in groups.items():
        if len(corners)==4:
            holes=[corners[i][1] for i in range(4)]
            possibilities.append((sum(corners[i][0][0] for i in range(4)),phase_key,holes))
    if not possibilities:
        raise APIError("mounting_holes_unavailable","当前行列选择下，无法在四角找到无遮挡且坐标差为25 mm倍数的4个固定孔。请更换行列奇偶、移动器件或调整面包板尺寸。",409)
    first_error=None
    for _,_,holes in sorted(possibilities,key=lambda item:(item[0],item[1])):
        try:
            chosen_board=normalize_board({**board,"mountingHoles":holes})
        except BreadboardError as exc:
            if first_error is None:first_error=exc
            continue
        chosen_layout,_,chosen_validation=validate_layout({**layout,"board":chosen_board},kits)
        if chosen_validation["mountingHoleObstructions"]:continue
        chosen_spec=board_specs(chosen_board)
        return {"mountingHoles":chosen_board["mountingHoles"],"board":chosen_layout["board"],
                "holes":chosen_spec["mountingHoles"],"counterbore":chosen_spec["counterbore"],
                "layoutValidation":chosen_validation,"selection":parities,
                "note":"已按当前布局选择靠近四角的4个M6圆柱沉孔，水平和竖直坐标差均为25 mm整数倍。移动器件后保持原孔位；遮挡时须明确重新选孔。"}
    if first_error is not None:
        raise APIError(first_error.code,str(first_error),first_error.status) from first_error
    raise APIError("mounting_holes_unavailable","未能找到满足孔位及避让要求的四角固定孔，请调整布局。",409)


def choose_registered_mounting(catalog,payload,candidate_filter=None):
    from breadboard import normalize_board, board_specs
    from registered_boards import definition,custom_mounting,mounting_candidates,custom_mounting_error
    source=payload['layout'];b=normalize_board(source['board']);record=definition(b)
    kits={k['id']:k for k in catalog['kits']}
    local,metadata,_=validate_layout({**source,'board':{**b,'mountingHoles':[]}},kits)
    shapes=[world_geometry(i,metadata[i['kitId']]) for i in local['instances']]
    available=set(mounting_candidates(record));selected=[]
    for h in record['holesMm']:
        if h['id'] not in available:continue
        x,y=h['xMm'],h['yMm'];radius=5.5 if custom_mounting(record) else h.get('counterboreDiameterMm',h['diameterMm'])/2
        if custom_mounting_error(record,h['id'],[]):continue
        if candidate_filter is not None and not candidate_filter(x,y):continue
        if any(hole_obstructs_shape((x,y),radius,shape) for shape in shapes):continue
        selected.append({'holeId':h['id']})
    required=record.get('minimumAlignedMountingHoles',4)
    if custom_mounting(record):
        wanted=payload.get('holeCount',4)
        if type(wanted) is not int or wanted not in (4,8):raise APIError('invalid_mounting_holes','自动选孔支持4个或8个沉孔。')
        points={h['id']:h for h in record['holesMm']};pool=selected;selected=[]
        while pool and len(selected)<wanted:
            def score(v):
                p=points[v['holeId']]
                if not selected:return (p['xMm']-b['widthMm']/2)**2+(p['yMm']-b['heightMm']/2)**2
                return min((p['xMm']-points[q['holeId']]['xMm'])**2+(p['yMm']-points[q['holeId']]['yMm'])**2 for q in selected)
            pool.sort(key=score,reverse=True);v=pool.pop(0)
            if not custom_mounting_error(record,v['holeId'],[q['holeId'] for q in selected]):selected.append(v)
        required=wanted
    if len(selected)<required:
        raise APIError('registered_mounting_unavailable',f'源面包板仅有 {len(selected)} 个对齐且无遮挡的已登记固定孔，至少需要 {required} 个；不会在原模型上推测或新增沉孔。',409)
    local['board']=normalize_board({**b,'mountingHoles':selected})
    local,_,validation=validate_layout(local,kits);spec=board_specs(local['board'])
    return {'mountingHoles':selected,'board':local['board'],'holes':spec['mountingHoles'],'counterbore':spec['counterbore'],
            'layoutValidation':validation,'selection':{'rowParity':'any','columnParity':'any'},
            'note':'已保存自选沉孔位置；按工程生成对应STEP和加工图后加工。' if custom_mounting(record) else '已选择源面包板中对齐且无遮挡的固定孔；保留原孔型，不新增孔，也不套用矩形板的奇偶打孔规则。'}


def layout_document(preview):
    from breadboard import board_specs
    if "layout" not in preview:
        raise APIError("layout_required", "请先创建面包板布局。")
    return {"catalogVersion": preview["catalogVersion"], "layout": preview["layout"],
            **({"requires":preview["requires"]} if preview.get("requires") else {}),
            "extras": preview.get("layoutExtras", preview.get("extras", [])),
            "layoutValidation": preview.get("layoutValidation", {"valid": True, "issues": []}),
            "boardSpecification": {**board_specs(preview["layout"]["board"]),
                                   **({"productionIncluded": False, "purpose": "桌子／无大板；仅作工作区参考，不加工根板"}
                                      if preview["layout"].get("baseMode") == "table" else {})}}


def layout_json(preview):
    return json.dumps(layout_document(preview), ensure_ascii=False, indent=2).encode("utf-8")


def layout_svg(preview, static_root):
    if preview.get('layout',{}).get('subBoards'):
        from stacked_layout import stacked_svg
        return stacked_svg(preview,static_root)
    from exports import safe_asset
    doc = layout_document(preview)
    board = doc["layout"]["board"]
    width, height, pitch, offset = (board[k] for k in ("widthMm", "heightMm", "pitchMm", "edgeOffsetMm"))
    margin, footer = max(15, min(width, height)*0.04), 58
    visual_bounds = [footprint(i,preview["layoutKitMetadata"][i["kitId"]],"imageBoundsMm") for i in doc["layout"]["instances"]]
    visual_bounds.extend(world_geometry(i,preview["layoutKitMetadata"][i["kitId"]])["bounds"] for i in doc["layout"]["instances"])
    x_min = min([0]+[b["left"] for b in visual_bounds])
    x_max = max([width]+[b["right"] for b in visual_bounds])
    y_min = min([0]+[b["top"] for b in visual_bounds])
    y_max = max([height]+[b["bottom"] for b in visual_bounds])
    view_left,view_top = x_min-margin,height-y_max-margin
    view_width,view_height = x_max-x_min+2*margin,y_max-y_min+2*margin+footer
    footer_y = height-y_min
    n = lambda x: f"{x:g}"
    e = lambda x: html.escape(str(x), quote=True)
    radius = min(1.5, pitch*0.08)
    last_x = offset + math.floor((width-2*offset)/pitch)*pitch
    last_y = offset + math.floor((height-2*offset)/pitch)*pitch
    grid_left, grid_top = max(0, offset-radius), max(0, height-last_y-radius)
    grid_right, grid_bottom = min(width, last_x+radius), min(height, height-offset+radius)
    table = doc["layout"].get("baseMode") == "table"
    scope = "桌子／无大板：网格仅作工作区参考，不加工根板；小板和自制件以生产清单为准。" if table else "参数面包板数量以生产清单为准。"
    content = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{n(view_width)}mm" height="{n(view_height)}mm" viewBox="{view_left:g} {view_top:g} {view_width:g} {view_height:g}">',
               '<title>ZZLab 面包板光路总俯视图</title>',
               f'<desc>实际尺寸单位为毫米。{scope}器件投影视图与安装锚点按目录登记数据。</desc>',
               f'<defs><pattern id="holes" x="{n(offset-pitch/2)}" y="{n(height-offset-pitch/2)}" width="{n(pitch)}" height="{n(pitch)}" patternUnits="userSpaceOnUse"><circle cx="{n(pitch/2)}" cy="{n(pitch/2)}" r="{radius:g}" fill="#86938f"/></pattern></defs>',
               f'<rect x="0" y="0" width="{n(width)}" height="{n(height)}" rx="2" fill="#f1f4f1" stroke="#3f5550" stroke-width="0.5"/>',
               f'<rect x="{n(grid_left)}" y="{n(grid_top)}" width="{n(grid_right-grid_left)}" height="{n(grid_bottom-grid_top)}" fill="url(#holes)"/>']
    from registered_boards import registered, svg_markup
    if registered(board):content=content[:3]+[svg_markup(board,static_root)]
    content.append('<!-- board-surfaces-end -->')
    invalid_ids = {iid for issue in preview.get("layoutValidation", {}).get("issues", []) for iid in issue.get("instanceIds", [])}
    adapter_records = {a["instanceId"]: a for a in preview.get("layoutValidation", {}).get("laserAdapters", [])}
    axis_heights = {a["instanceId"]: a.get("effectiveAxisHeightMm") for a in preview.get("layoutValidation", {}).get("axisHeights", [])}
    if adapter_records:
        content.append('<defs><marker id="laser-adapter-beam-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0 L7 3.5 L0 7 Z" fill="#7752a4"/></marker></defs>')
    # Plates are below every component image. The separate hole/beam overlay is
    # emitted last, so the laser's opaque housing cannot hide assembly references.
    for instance in doc["layout"]["instances"]:
        record = adapter_records.get(instance["id"])
        if not record:
            continue
        boundary = record["spec"]["outlineBoundsMm"]
        content.append(f'<g data-laser-adapter="{e(instance["id"])}" data-adapter-layer="plate" transform="translate({instance["xMm"]:g} {height-instance["yMm"]:g}) rotate({-instance["rotationDeg"]})"><title>{e(record["spec"]["notes"])}</title><rect x="{boundary["xMin"]:g}" y="{-boundary["yMax"]:g}" width="{boundary["xMax"]-boundary["xMin"]:g}" height="{boundary["yMax"]-boundary["yMin"]:g}" fill="#bedbec" fill-opacity="0.45" stroke="#28739b" stroke-width="1.1"/></g>')
    cached, total = {}, 0
    for index, instance in enumerate(doc["layout"]["instances"], 1):
        geometry = preview["layoutKitMetadata"][instance["kitId"]]
        path = geometry["topViewPath"]
        if path not in cached:
            asset = safe_asset(static_root, path, "套件俯视图")
            total += asset.stat().st_size
            if total > MAX_LAYOUT_ASSET_BYTES:
                raise APIError("layout_too_large", "俯视图资源超过32MB，请分批导出。", 413)
            mime = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp"}[asset.suffix.lower()]
            cached[path] = f"data:{mime};base64," + base64.b64encode(asset.read_bytes()).decode("ascii")
        title = f"{index}. {instance['id']} · {geometry.get('name', instance['kitId'])} · ({instance['xMm']:g}, {instance['yMm']:g}) mm · {instance['rotationDeg']}°"
        content.extend([f'<g transform="translate({instance["xMm"]:g} {height-instance["yMm"]:g}) rotate({-instance["rotationDeg"]})"><title>{e(title)}</title>',
                        f'<image x="{-geometry["anchorXMm"]:g}" y="{-geometry["anchorYMm"]:g}" width="{geometry["widthMm"]:g}" height="{geometry["heightMm"]:g}" xlink:href="{cached[path]}" preserveAspectRatio="none"/>', '</g>',
                        f'<circle cx="{instance["xMm"]:g}" cy="{height-instance["yMm"]:g}" r="1.2" fill="none" stroke="#16736f" stroke-width="0.4"/>',
                        f'<text x="{instance["xMm"]+2:g}" y="{height-instance["yMm"]-2:g}" font-family="Arial,sans-serif" font-size="4" fill="#13534c">{index}</text>'])
        collision_color = "#c84c45" if instance["id"] in invalid_ids else "#c28b37"
        for polygon in collision_polygons(geometry):
            points=" ".join(f"{x:g},{-y:g}" for x,y in polygon)
            content.append(f'<g transform="translate({instance["xMm"]:g} {height-instance["yMm"]:g}) rotate({-instance["rotationDeg"]})"><polygon points="{points}" fill="none" stroke="{collision_color}" stroke-width="0.45" stroke-dasharray="3 1.8"/></g>')
        boundary=local_bounds(geometry,"baseBoundsMm")
        content.append(f'<g transform="translate({instance["xMm"]:g} {height-instance["yMm"]:g}) rotate({-instance["rotationDeg"]})"><rect x="{boundary["xMin"]:g}" y="{-boundary["yMax"]:g}" width="{boundary["xMax"]-boundary["xMin"]:g}" height="{boundary["yMax"]-boundary["yMin"]:g}" fill="none" stroke="#267da2" stroke-width="0.45" stroke-dasharray=".7 1.4"/></g>')
    spec=doc["boardSpecification"]
    blocked_holes={i.get("holeLabel") for i in preview.get("layoutValidation",{}).get("mountingHoleObstructions",[])}
    for hole in spec.get("mountingHoles",[]):
        x,y=hole["xMm"],height-hole["yMm"]
        radius=hole.get('counterboreDiameterMm',hole.get('diameterMm',spec['counterbore'].get('diameterMm',11)))/2
        clearance=hole.get('diameterMm',spec['counterbore'].get('clearanceDiameterMm',6.6))/2
        color="#c84c45" if hole["label"] in blocked_holes else "#245d69"
        content.extend([f'<circle data-mounting-hole="{hole["label"]}" cx="{x:g}" cy="{y:g}" r="{radius:g}" fill="#d9e2e2" fill-opacity="0.8" stroke="{color}" stroke-width="0.5"/>',
                        f'<circle cx="{x:g}" cy="{y:g}" r="{clearance:g}" fill="#ffffff" stroke="{color}" stroke-width="0.5"/>',
                        f'<text x="{x+radius+1:g}" y="{y-radius-1:g}" font-family="Arial,sans-serif" font-size="4" fill="{color}">{hole["label"]}</text>'])
    for instance in doc["layout"]["instances"]:
        record = adapter_records.get(instance["id"])
        if not record:
            continue
        adapter_spec = record["spec"]
        boundary = adapter_spec["outlineBoundsMm"]
        content.append(f'<g data-laser-adapter="{e(instance["id"])}" data-adapter-layer="holes" transform="translate({instance["xMm"]:g} {height-instance["yMm"]:g}) rotate({-instance["rotationDeg"]})"><rect x="{boundary["xMin"]:g}" y="{-boundary["yMax"]:g}" width="{boundary["xMax"]-boundary["xMin"]:g}" height="{boundary["yMax"]-boundary["yMin"]:g}" fill="none" stroke="#28739b" stroke-width="0.7"/>')
        for hole in adapter_spec["boardMountingHolesMm"]:
            hx, hy = hole["xMm"], -hole["yMm"]
            content.extend([f'<g data-adapter-hole="{e(hole["label"])}" data-hole-type="counterbore"><title>{e(hole["label"])} · Ø6.6 通孔 / Ø11 深6.5 圆柱沉孔</title>',
                            f'<circle cx="{hx:g}" cy="{hy:g}" r="5.5" fill="#e2f0f8" fill-opacity="0.85" stroke="#21648b" stroke-width="0.65"/>',
                            f'<circle cx="{hx:g}" cy="{hy:g}" r="3.3" fill="#ffffff" fill-opacity="0.8" stroke="#21648b" stroke-width="0.55"/>',
                            f'<text x="{hx+6.5:g}" y="{hy-6:g}" font-family="Arial,sans-serif" font-size="4.3" fill="#174f72" stroke="#fff" stroke-width="1.2" paint-order="stroke fill">{e(hole["label"])}</text></g>'])
        for hole in adapter_spec["laserThreadHolesMm"]:
            hx, hy = hole["xMm"], -hole["yMm"]
            content.extend([f'<g data-adapter-hole="{e(hole["label"])}" data-hole-type="thread"><title>{e(hole["label"])} · M6×1 通螺纹 / STEP Ø5 底孔</title>',
                            f'<circle cx="{hx:g}" cy="{hy:g}" r="3" fill="#ffffff" fill-opacity="0.85" stroke="#31526f" stroke-width="0.6"/>',
                            f'<path d="M{hx-2:g} {hy:g} H{hx+2:g} M{hx:g} {hy-2:g} V{hy+2:g}" fill="none" stroke="#31526f" stroke-width="0.45"/>',
                            f'<text x="{hx+4:g}" y="{hy-4:g}" font-family="Arial,sans-serif" font-size="4" fill="#174f72" stroke="#fff" stroke-width="1.2" paint-order="stroke fill">{e(hole["label"])} M6</text></g>'])
        content.append('</g>')
        port = record["beamPortMm"]
        rotation = record["globalRotationDeg"]
        dx, dy = {0:(-1,0),90:(0,-1),180:(1,0),270:(0,1)}[rotation]
        ray_distance = port["xMm"] if dx < 0 else width-port["xMm"] if dx > 0 else port["yMm"] if dy < 0 else height-port["yMm"]
        ray_length = max(12, min(60, ray_distance if ray_distance > 0 else 40))
        px, py = port["xMm"], height-port["yMm"]
        content.extend([f'<g data-laser-adapter="{e(instance["id"])}" data-adapter-layer="beam"><title>实际光口与出光方向；紫色线为光轴参考</title>',
                        f'<line x1="{px:g}" y1="{py:g}" x2="{px+dx*ray_length:g}" y2="{py-dy*ray_length:g}" stroke="#7752a4" stroke-width="1" stroke-dasharray="4 1.4" marker-end="url(#laser-adapter-beam-arrow)"/>',
                        f'<circle data-adapter-optical-port="output" cx="{px:g}" cy="{py:g}" r="2.4" fill="#fff" stroke="#7752a4" stroke-width="1"/></g>'])
        box = footprint(instance, {"baseBoundsMm": boundary}, "baseBoundsMm")
        effective = axis_heights.get(instance["id"])
        axis_label = f"{effective:g} mm" if effective is not None else "未登记"
        content.append(f'<text data-adapter-axis-label="{e(instance["id"])}" x="{box["left"]+4:g}" y="{height-box["bottom"]-5:g}" font-family="Arial,sans-serif" font-size="5" fill="#174f72" stroke="#fff" stroke-width="1.4" paint-order="stroke fill">垫板 {adapter_spec["thicknessMm"]:g} mm · 有效光轴 {e(axis_label)}</text>')
    valid = preview.get("layoutValidation", {}).get("valid", True)
    validation_label = "有效布局" if valid else "无效布局草稿 · 不可用于采购或生产"
    content.extend([f'<text x="0" y="{footer_y+10:g}" font-family="Arial, sans-serif" font-size="5" fill="#203e38">ZZLab · {n(width)} × {n(height)} mm · 孔距 {n(pitch)} mm · {len(doc["layout"]["instances"])} 个套件</text>',
                    f'<text x="0" y="{footer_y+18:g}" font-family="Arial, sans-serif" font-size="3.5" fill="#526c65">琥珀色虚线：实际俯视轮廓（冲突红色）；蓝色点线：底座。上部允许伸出板外。</text>',
                    f'<text x="0" y="{footer_y+25:g}" font-family="Arial, sans-serif" font-size="3.5" fill="#526c65">孔位坐标从画布左下角计，X 向右，Y 向上；轮廓或锚点待核实项以目录说明为准。</text>',
                    f'<text x="0" y="{footer_y+33:g}" font-family="Arial,sans-serif" font-size="3.5" fill="#526c65">{e(scope) if table else f"固定沉孔 {spec['mountingHoleCount']} 个：" + (e(spec["counterboreCallout"]) if spec["mountingHoleCount"] else "未启用")}</text>',
                    f'<text x="0" y="{footer_y+44:g}" font-family="Arial, sans-serif" font-size="5" fill="{"#16736f" if valid else "#b52c1a"}">{validation_label}</text>', '</svg>'])
    return "\n".join(content).encode("utf-8")
