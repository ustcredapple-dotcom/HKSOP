"""Optical-axis heights and additional elevation materials, derived on the server.

The root board's top is Z=0. Material decomposition uses integer tenths of a
millimetre. Direct root-board kits replace their registered universal posts;
other targets add only requested elevation, never their existing support.
"""
from __future__ import annotations

import math
from pathlib import PurePosixPath

from bom import APIError

ELEVATION_FIELDS = {"elevationMm", "elevationSupportCount"}
POST_SELECTION_FIELDS = {"universalPostSelection"}
EPSILON = 1e-5
AUTO_AXIS_STEP_MM = 12.5
LEGACY_POST_SERIES = "legacy-imperial"


def automatic_axis_target(reference):
    """Round only a requested automatic target, never a saved or achieved Z."""
    return None if reference is None else round(math.ceil((reference-EPSILON)/AUTO_AXIS_STEP_MM)*AUTO_AXIS_STEP_MM, 6)


def post_series(entry):
    return entry.get("seriesId", LEGACY_POST_SERIES)


def tenths(value, label="垫高高度", maximum=1000, allow_zero=True):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or value < (0 if allow_zero else .1) or value > maximum
            or abs(value*10-round(value*10)) > EPSILON):
        raise APIError("invalid_elevation", f"{label}必须为 {'0' if allow_zero else '0.1'} 至 {maximum:g} mm，精度为 0.1 mm。")
    return round(value*10)


def normalize_fields(source):
    """Preserve optional-field absence so legacy saved projects remain unchanged."""
    result = {}
    if "elevationMm" in source:
        value = source["elevationMm"]
        if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 1000 or abs(value*1000-round(value*1000)) > EPSILON:
            raise APIError("invalid_elevation", "垫高高度需为0–1000mm，精确到0.001mm。")
        result["elevationMm"] = round(value,3)
    if "elevationSupportCount" in source:
        count = source["elevationSupportCount"]
        if type(count) is not int or not 1 <= count <= 128:
            raise APIError("invalid_elevation", "垫高支持点数量必须为 1 至 128 的整数。")
        result["elevationSupportCount"] = count
    return result


def normalize_post_fields(source):
    if "universalPostSelection" not in source:
        return {}
    selection = source["universalPostSelection"]
    def valid_id(value):
        return (isinstance(value, str) and 1 <= len(value) <= 80 and value == value.strip()
                and value not in ("__proto__", "constructor", "prototype")
                and not any(ord(c) < 32 for c in value))
    if (not isinstance(selection, dict) or len(selection) > 32
            or any(not valid_id(k) or not valid_id(v) for k, v in selection.items())):
        raise APIError("invalid_post_selection", "换柱选择必须为最多32项的原柱编号与登记柱编号。")
    return {"universalPostSelection": dict(selection)}


def support_count(target, geometry=None, alignment=None, *, board=False):
    if "elevationSupportCount" in target:
        return target["elevationSupportCount"]
    if board:
        if target.get("stageMotion"):
            from moving_stages import module_for
            return len(module_for(target)["lowerAttachmentHoles"])
        return len(target["board"].get("mountingHoles", [])) or 4
    geometry = geometry or {}
    minimum = geometry.get("minimumAlignedMountingHoles")
    mounted_source = (bool(geometry.get("opticalPortsMm"))
                      and type(minimum) is int and minimum >= 2)
    if target["kitId"] == "laser-308nm" or mounted_source:
        if target["kitId"] == "laser-308nm" and target.get("laserAdapter", {}).get("enabled") is True:
            return 4
        return max(minimum if mounted_source else 2, (alignment or {}).get("alignedCount", 0))
    return 1


def axis_validation(layout, metadata, alignments, *, uniform=True):
    plates = {p["id"]: p for p in layout.get("subBoards", [])}
    by_instance = {a["instanceId"]: a for a in alignments}
    heights = []
    for instance in layout["instances"]:
        geometry = metadata[instance["kitId"]]
        from manual_source_mount import accepted_height, source_reference
        manual_reference = source_reference(geometry)
        own = accepted_height(instance,geometry) if manual_reference is not None else geometry.get("opticalAxisHeightMm")
        if own is not None and (type(own) not in (int, float) or not math.isfinite(own) or not 0 <= own <= 10000):
            raise APIError("kit_layout_missing", "套件自身光轴高度未按目录契约登记。", 409)
        plate = plates.get(instance.get("boardId"))
        board_elevation = plate.get("elevationMm", 0) if plate else 0
        thickness = plate["board"]["thicknessMm"] if plate else 0
        from moving_stages import stage_height_offset
        stage_offset = stage_height_offset(plate) if plate else 0
        elevation = instance.get("elevationMm", 0)
        adapter_thickness = instance.get("laserAdapter", {}).get("thicknessMm", 0) if instance.get("laserAdapter", {}).get("enabled") is True else 0
        external = external_axis_heights(geometry)
        base_z = board_elevation+thickness+stage_offset+elevation+adapter_thickness
        heights.append({"instanceId": instance["id"], "kitId": instance["kitId"],
                        "boardId": instance.get("boardId"), "opticalAxisHeightMm": own,
                        "boardElevationMm": board_elevation, "boardThicknessMm": thickness,
                        **({"stageHeightOffsetMm": stage_offset} if plate and plate.get("stageMotion") else {}),
                        "elevationMm": elevation, "adapterThicknessMm": adapter_thickness,
                        "elevationSupportCount": support_count(instance, geometry, by_instance.get(instance["id"])),
                        "heightResolved": own is not None or external is not None,
                        **({"axisHeightEvidence":"user-confirmed-manual-alignment", "catalogHeightVerified":False} if manual_reference is not None and own is not None else {}),
                        **({"globalHeightComparable": False} if isinstance(geometry.get("opticalAssembly"),dict) else {}),
                        **({"effectiveExternalAxisHeightsMm": [round(h+base_z, 6) for h in external]} if external is not None else {}),
                        "effectiveAxisHeightMm": round(own+base_z, 6) if own is not None else None})
    return height_validation(heights) if uniform else ({"axisHeights": heights, "axisHeightReferenceMm": None, "autoAxisHeightTargetMm": None}, [])


def height_validation(heights):
    """Compare achieved heights only; unresolved replacement requests are excluded."""
    known = [h for h in heights if h["effectiveAxisHeightMm"] is not None and h.get("globalHeightComparable",True)]
    reference = max((h["effectiveAxisHeightMm"] for h in known), default=None)
    lower = [h for h in known if reference-h["effectiveAxisHeightMm"] > EPSILON]
    converters = [h["effectiveExternalAxisHeightsMm"] for h in heights if h.get("effectiveExternalAxisHeightsMm")]
    connected = None
    if reference is not None and converters:
        # Only shared physical heights connect converter groups. A disconnected
        # converter elsewhere on the board must not permit an unrelated height.
        values = [reference]+[h["effectiveAxisHeightMm"] for h in known]
        edges = []
        for group in converters:
            start = len(values)
            values.extend(group)
            edges.extend((start, start+n) for n in range(1, len(group)))
        parents = list(range(len(values)))
        def find(index):
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index
        def join(a, b):
            parents[find(a)] = find(b)
        ordered = sorted(range(len(values)), key=values.__getitem__)
        for a, b in zip(ordered, ordered[1:]):
            if values[b]-values[a] <= EPSILON:
                join(a, b)
        for a, b in edges:
            join(a, b)
        lower = [h for index, h in enumerate(known, 1) if find(index) != find(0)]
        connected = sorted(set(value for index, value in enumerate(values) if find(index) == find(0)))
    issues = []
    if lower:
        mismatches = []
        if connected is not None:
            for row in lower:
                actual = row["effectiveAxisHeightMm"]
                nearest = min(connected, key=lambda value: (abs(value-actual), value))
                mismatches.append({"instanceId": row["instanceId"], "effectiveAxisHeightMm": actual,
                                   "nearestConnectedAxisHeightMm": nearest,
                                   "heightDifferenceMm": round(actual-nearest, 6)})
            groups = {}
            for row in mismatches:
                key = (row["effectiveAxisHeightMm"], row["nearestConnectedAxisHeightMm"], row["heightDifferenceMm"])
                groups[key] = groups.get(key, 0)+1
            details = "；".join(f"{actual:g} mm × {count}（比兼容光高 {nearest:g} mm {'高' if delta > 0 else '低'} {abs(delta):g} mm）"
                               for (actual, nearest, delta), count in list(groups.items())[:6])
            if len(groups) > 6:
                details += f"；另有 {len(groups)-6} 组高差"
            message = (f"已计入爬架光高转换，可连通光高：{' / '.join(f'{h:g}' for h in reversed(connected))} mm。"
                       f"{len(lower)} 个器件仍有光高差：{details}；请核对这些器件的柱高、转接块或小板垫高。")
        else:
            message = f"{len(lower)} 个器件的有效光轴低于当前最高光轴 {reference:g} mm；请调整器件或小板垫高，使已知光轴等高。"
        issues.append({"code": "axis_height_mismatch", "instanceIds": [h["instanceId"] for h in lower],
                       "message": message,
                       **({"heightMismatches": mismatches, "connectedAxisHeightsMm": connected} if connected is not None else {}),
                       "axisHeightReferenceMm": reference, "axisHeights": heights})
    return {"axisHeights": heights, "axisHeightReferenceMm": reference,
            **({"connectedAxisHeightsMm": connected} if connected is not None else {}),
            "autoAxisHeightTargetMm": automatic_axis_target(reference)}, issues


def external_axis_heights(geometry):
    """Trusted kit declaration, tied to measured mechanical optical faces.

    This is a nominal height compatibility graph, not evidence of an XY ray hit,
    a coating, or an installed optical element. Instance overrides are ignored.
    """
    assembly = geometry.get("opticalAssembly") if isinstance(geometry, dict) else None
    if not isinstance(assembly, dict) or "externalAxisHeightsMm" not in assembly:
        return None
    values = assembly["externalAxisHeightsMm"]
    face_heights = []
    nodes = assembly.get("nodes")
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        faces = node.get("faces")
        for face in faces if isinstance(faces, list) else []:
            center = face.get("centerMm") if isinstance(face, dict) else None
            z = center[2] if isinstance(center, list) and len(center) == 3 else center.get("z") if isinstance(center, dict) else None
            if type(z) in (int, float) and math.isfinite(z):
                face_heights.append(z)
    if (assembly.get("verified") is not True or not isinstance(values, list) or not 2 <= len(values) <= 16
            or any(type(h) not in (int, float) or not math.isfinite(h) or not 0 <= h <= 10000 for h in values)
            or any(abs(a-b) <= EPSILON for n, a in enumerate(values) for b in values[n+1:])
            or any(not any(abs(h-z) <= EPSILON for z in face_heights) for h in values)):
        raise APIError("external_axis_heights_invalid", "爬架外部光高必须属于已核实总装，包含 2–16 个有限、非负、互异且对应真实光学面中心 Z 的高度。", 503)
    return list(values)


def validate_fixed_universal_posts(catalog, posts):
    """Fixed orientation posts remain real BOM rows, never Z-height supports.

    This is a kit-level declaration, not a per-instance override. Cross-record
    membership is checked here because JSON Schema cannot resolve component IDs.
    """
    registered = {post["componentId"] for post in posts}
    for kit in catalog.get("kits", []):
        geometry = kit.get("layout")
        external_axis_heights(geometry)
        if isinstance(geometry, dict) and "globalHeightPolicy" in geometry:
            own = geometry.get("opticalAxisHeightMm")
            assembly = geometry.get("opticalAssembly")
            if (geometry["globalHeightPolicy"] != "fixed-datum" or type(own) not in (int, float)
                    or not math.isfinite(own) or own < 0 or geometry.get("opticalDatumVerified") is not True
                    or not isinstance(assembly, dict) or assembly.get("verified") is not True
                    or not any(abs(f.get("centerMm", [0, 0, float("inf")])[2] - own) < EPSILON
                               for node in assembly.get("nodes", []) for f in node.get("faces", []))):
                raise APIError("fixed_optical_datum_invalid", "固定光高器件必须有已核对的真实光学面与有限光高。", 503)
        if isinstance(geometry, dict) and "postThreadAdapterAccepted" in geometry:
            if type(geometry["postThreadAdapterAccepted"]) is not bool:
                raise APIError("post_thread_adapter_invalid", "柱顶螺纹适配声明必须为布尔值。", 503)
        if not isinstance(geometry, dict) or "fixedUniversalPostComponentIds" not in geometry:
            continue
        fixed = geometry["fixedUniversalPostComponentIds"]
        present = {line["componentId"] for line in kit.get("components", [])}
        if (not isinstance(fixed, list) or len(fixed) > 128
                or any(not isinstance(cid, str) or cid not in registered or cid not in present for cid in fixed)
                or len(set(fixed)) != len(fixed)):
            raise APIError("fixed_universal_posts_invalid",
                           f"套件 {kit.get('id', '')} 的固定柱必须为不重复、属于该套件BOM且已登记柱系列的组件编号数组。", 503)


def validate_universal_posts(catalog):
    raw = catalog.get("universalPostSeries")
    if raw is None:
        validate_fixed_universal_posts(catalog, [])
        return []
    if not isinstance(raw, dict) or ("posts" not in raw or set(raw)-{"posts", "metricMigration"}) or not isinstance(raw["posts"], list) or len(raw["posts"]) > 128:
        raise APIError("universal_posts_invalid", "万能柱目录必须为 posts 规格数组。", 503)
    components = {c["id"]: c for c in catalog["components"]}
    if "metricMigration" in raw:
        migration = raw["metricMigration"]
        from metric_migration import REVISION
        if (not isinstance(migration, dict) or not {"revision", "componentMap", "legacyKitIds"} <= set(migration)
                or set(migration) - {"revision", "componentMap", "legacyKitIds", "retiredComponents"}
                or migration.get("revision") != REVISION or not isinstance(migration.get("componentMap"), dict)
                or not isinstance(migration.get("legacyKitIds"), list)
                or any(not isinstance(k, str) or k not in {kit["id"] for kit in catalog["kits"]} for k in migration["legacyKitIds"])
                or len(set(migration["legacyKitIds"])) != len(migration["legacyKitIds"])
                or not isinstance(migration.get("retiredComponents", {}), dict)
                or any((k not in components and k not in migration.get("retiredComponents", {})) or not isinstance(v, str) or v not in components or k == v for k, v in migration["componentMap"].items())):
            raise APIError("metric_migration_invalid", "公制替换表必须引用有效且不同的旧、新规格及既有套件。", 503)
        for old_id, entry in migration.get("retiredComponents", {}).items():
            if (old_id in components or old_id not in migration['componentMap'] or not isinstance(entry, dict)
                    or not {'replacementComponentId', 'stepPath', 'drawingPath'} <= set(entry)
                    or set(entry) - {'replacementComponentId', 'stepPath', 'drawingPath', 'dxfPath'}
                    or entry.get('replacementComponentId') != migration['componentMap'][old_id]):
                raise APIError('metric_migration_invalid', '已删除柱子的兼容记录必须只指向现有公制规格。', 503)
            for field, folder, suffixes in [('stepPath', 'step', {'.step', '.stp'}), ('drawingPath', 'drawings', {'.pdf'}), ('dxfPath', 'drawings', {'.dxf'})]:
                value = entry.get(field)
                if value is None and field == 'dxfPath':
                    continue
                if (not isinstance(value, str) or '\\' in value or '..' in PurePosixPath(value).parts
                        or not value.startswith(folder + '/') or PurePosixPath(value).suffix.lower() not in suffixes):
                    raise APIError('metric_migration_invalid', '历史资产标识必须是原登记的相对路径，仅供核对，不能作为下载入口。', 503)
        metric_ids = {p.get("componentId") for p in raw["posts"] if isinstance(p, dict) and p.get("seriesId") == "metric-12p5-r1"}
        if any(v not in metric_ids for v in migration["componentMap"].values()):
            raise APIError("metric_migration_invalid", "替换目标必须属于公制柱系列。", 503)
    result, ids, sizes = [], set(), set()
    for entry in raw["posts"]:
        if (not isinstance(entry, dict) or not {"componentId", "heightMm"} <= set(entry)
                or set(entry)-{"componentId", "heightMm", "seriesId"}):
            raise APIError("universal_posts_invalid", "万能柱规格必须登记组件编号和总高。", 503)
        series = post_series(entry)
        if (not isinstance(series, str) or not 1 <= len(series) <= 80
                or any(not (c.isascii() and (c.isalnum() or c in "_.-")) for c in series)):
            raise APIError("universal_posts_invalid", "万能柱系列编号必须为1–80个英文字母、数字或_.-。", 503)
        cid = entry["componentId"]
        if not isinstance(cid, str) or cid not in components or cid in ids or components[cid]["kind"] != "custom":
            raise APIError("universal_posts_invalid", "万能柱必须引用未重复的自制组件。", 503)
        if components[cid].get("postTopThread") not in (None, "M4", "M6"):
            raise APIError("universal_posts_invalid", "万能柱顶部螺纹只能登记为 M4 或 M6。", 503)
        size = tenths(entry["heightMm"], "万能柱总高", 1000, False)
        if (series, size) in sizes:
            raise APIError("universal_posts_invalid", "同一万能柱系列的总高规格不能重复。", 503)
        result.append({"componentId": cid, "heightMm": size/10,
                       **({"seriesId": series} if "seriesId" in entry else {})})
        ids.add(cid)
        sizes.add((series, size))
    validate_fixed_universal_posts(catalog, result)
    return sorted(result, key=lambda p: (post_series(p), p["heightMm"]))


def universal_post_plan(catalog, layout, *, allow_elevation=True):
    """Resolve all posts in each root instance atomically, using exact tenths.

    A compound kit may contain multiple original post sizes. Every size must
    resolve before any of that instance's original quantities are removed.
    """
    result = {"groups": [], "rows": [], "replacements": [], "issues": [], "managedInstanceIds": set(), "supportCounts": {}, "heightAdjustments": {}}
    series = validate_universal_posts(catalog)
    if layout is None or not series:
        if layout and any(i.get("universalPostSelection") for i in layout["instances"]):
            raise APIError("invalid_post_selection", "所选万能柱系列尚未登记。")
        return result
    by_id = {p["componentId"]: p for p in series}
    by_height = {(post_series(p), tenths(p["heightMm"])): p for p in series}
    components = {c["id"]: c for c in catalog["components"]}
    kits = {k["id"]: k for k in catalog["kits"]}
    for instance in layout["instances"]:
        elevation = instance.get("elevationMm", 0) if allow_elevation else 0
        child = bool(instance.get("boardId"))
        selection = normalize_post_fields(instance).get("universalPostSelection", {})
        if child and not selection:
            continue
        kit = kits[instance["kitId"]]
        fixed = set((kit.get("layout") or {}).get("fixedUniversalPostComponentIds", []))
        if set(selection) & fixed:
            raise APIError("invalid_post_selection", "固定横柱或非Z支撑柱不能通过垫高设置替换；请修改机械配置。")
        originals = [line for line in kit["components"] if line["componentId"] in by_id and line["componentId"] not in fixed]
        if set(selection)-{line["componentId"] for line in originals} or any(cid not in by_id for cid in selection.values()):
            raise APIError("invalid_post_selection", "换柱选择必须对应当前套件原柱和目录中已登记的目标柱。")
        if not originals:
            continue
        iid, kid = instance["id"], instance["kitId"]
        if not child:
            result["supportCounts"][iid] = sum(line["quantity"] for line in originals)
        deltas = [tenths(by_id[selection.get(line['componentId'],line['componentId'])]['heightMm'])-tenths(by_id[line['componentId']]['heightMm']) for line in originals]
        if len(set(deltas)) != 1:
            raise APIError("invalid_post_selection", "同一套件的所有支撑柱必须改变相同高度，不能通过换柱使器件倾斜。")
        result["heightAdjustments"][iid] = deltas[0]/10
        if not elevation and not selection:
            continue
        if not child:
            result["managedInstanceIds"].add(iid)
        resolved, missing = [], []
        for line in originals:
            original = by_id[line["componentId"]]
            basis = by_id[selection.get(original["componentId"], original["componentId"])]
            size = tenths(basis["heightMm"])+(0 if child else tenths(elevation))
            original_series = post_series(basis)
            replacement = by_height.get((original_series, size))
            if replacement is None:
                nearest = sorted((p for p in series if post_series(p) == original_series),
                                 key=lambda p: (abs(tenths(p["heightMm"])-size), p["heightMm"]))[:2]
                missing.append({"originalComponentId": original["componentId"], "originalHeightMm": original["heightMm"],
                                "requiredHeightMm": size/10, "nearestAvailableHeightsMm": [p["heightMm"] for p in nearest]})
            else:
                resolved.append({"instanceId": iid, "kitId": kid, "originalComponentId": original["componentId"],
                                 "replacementComponentId": replacement["componentId"], "originalHeightMm": original["heightMm"],
                                 "replacementHeightMm": replacement["heightMm"], "elevationMm": 0 if child else elevation, "quantity": line["quantity"],
                                 **({"selectedBaseComponentId": basis["componentId"], "postHeightDeltaMm": deltas[0]/10} if selection else {})})
        if missing:
            descriptions = [f"原柱 {p['originalHeightMm']:g} mm → 所需 {p['requiredHeightMm']:g} mm（邻近规格 {' / '.join(f'{h:g}' for h in p['nearestAvailableHeightsMm'])} mm）" for p in missing]
            result["issues"].append({"code": "universal_post_unavailable", "instanceIds": [iid], "kitId": kid,
                                     "message": f"{kit['name']} 的万能柱无法按所需高度替换：{'；'.join(descriptions)}。请选择已有规格；未追加 OP1 垫高。",
                                     "requestedElevationMm": elevation, "posts": missing})
            continue
        group = {"mode": "universalPostReplacement", "targetType": "instance", "targetId": iid, "name": kit["name"],
                 "elevationMm": 0 if child else elevation, "supportCount": 1, "materials": [],
                 **({"postHeightDeltaMm": deltas[0]/10} if selection else {})}
        for record in resolved:
            component = components[record["replacementComponentId"]]
            original_thread = components[record["originalComponentId"]].get("postTopThread")
            replacement_thread = component.get("postTopThread")
            if original_thread:
                record["originalTopThread"] = original_thread
            if replacement_thread:
                record["replacementTopThread"] = replacement_thread
            quantity = record["quantity"]
            group["materials"].append({"componentId": component["id"], "name": component["name"], "kind": component["kind"],
                                       "model": component.get("model") or "待确认", "unit": component["unit"],
                                       "heightMm": record["replacementHeightMm"], "originalHeightMm": record["originalHeightMm"],
                                       "replacesComponentId": record["originalComponentId"], "quantityPerSupport": quantity, "quantity": quantity})
            result["rows"].append({"componentId": component["id"], **{key: component.get(key) for key in (
                "name", "kind", "model", "unit", "stepPath", "drawingPath", "status", "notes", "sourceUrl", "manufacturingSpec")},
                "quantity": quantity, "kits": [{"kitId": kid, "name": f"{kit['name']} / 万能柱替换 {record['originalHeightMm']:g} → {record['replacementHeightMm']:g} mm",
                                                "quantity": quantity, "perKitQuantity": quantity, "kitQuantity": 1,
                                                "source": "universalPostReplacement", "targetType": "instance", "targetId": iid,
                                                "instanceId": iid, "replacesComponentId": record["originalComponentId"],
                                                "originalTopThread": original_thread, "replacementTopThread": replacement_thread}]})
        if (kit.get("layout") or {}).get("postThreadAdapterAccepted") is True:
            for record in resolved:
                original_thread, replacement_thread = record.get("originalTopThread"), record.get("replacementTopThread")
                if original_thread and replacement_thread and original_thread != replacement_thread:
                    result["rows"].append({
                        "componentId": f"post-thread-adapter:{original_thread}:{replacement_thread}",
                        "name": "万能柱螺纹适配件", "kind": "standard", "model": "待选", "unit": "个",
                        "quantity": record["quantity"], "status": "规格待选",
                        "notes": f"柱顶 {original_thread} → {replacement_thread}；用户接受用螺套适配。需按实际内外螺纹及旋入深度选型，保持柱端面安装基准；光高与装配需实物确认。",
                        "kits": [{"kitId": kid, "name": kit["name"], "quantity": record["quantity"],
                                  "perKitQuantity": record["quantity"], "kitQuantity": 1, "instanceId": iid,
                                  "source": "universalPostReplacement", "targetType": "instance", "targetId": iid}]
                    })
        result["groups"].append(group)
        result["replacements"].extend(resolved)
    return result


def apply_post_validation(validation, plan, *, uniform=True):
    """Do not claim an unbuildable post replacement achieved the desired Z."""
    if validation is None:
        return
    for axis in validation.get("axisHeights", []):
        if axis["instanceId"] in plan["supportCounts"]:
            # The axis table reports physical posts; a replacement materials
            # group remains one complete kit, whose rows contain all posts.
            axis["elevationSupportCount"] = plan["supportCounts"][axis["instanceId"]]
        delta = plan["heightAdjustments"].get(axis["instanceId"], 0)
        if delta:
            axis["postHeightDeltaMm"] = delta
            if axis["effectiveAxisHeightMm"] is not None:
                axis["effectiveAxisHeightMm"] = round(axis["effectiveAxisHeightMm"]+delta, 6)
            if axis.get("effectiveExternalAxisHeightsMm") is not None:
                axis["effectiveExternalAxisHeightsMm"] = [round(h+delta, 6) for h in axis["effectiveExternalAxisHeightsMm"]]
    unresolved = {iid for issue in plan["issues"] for iid in issue["instanceIds"]}
    for axis in validation.get("axisHeights", []):
        if axis["instanceId"] in unresolved:
            axis["requestedEffectiveAxisHeightMm"] = axis["effectiveAxisHeightMm"]
            axis["effectiveAxisHeightMm"] = None
            axis["heightResolved"] = False
            if "effectiveExternalAxisHeightsMm" in axis:
                axis["effectiveExternalAxisHeightsMm"] = None
    axes, issues = height_validation(validation.get("axisHeights", [])) if uniform else ({"axisHeights": validation.get("axisHeights", []), "axisHeightReferenceMm": None, "autoAxisHeightTargetMm": None}, [])
    validation.pop("connectedAxisHeightsMm", None)
    validation.update(axes)
    validation["issues"] = [issue for issue in validation["issues"] if issue["code"] != "axis_height_mismatch"] + plan["issues"] + issues
    validation["valid"] = not validation["issues"]
    validation["messages"] = list(dict.fromkeys(issue["message"] for issue in validation["issues"]))


def validate_materials(catalog):
    raw = catalog.get("elevationMaterials")
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw)-{"posts", "spacers", "fractionalShim", "notes"}:
        raise APIError("elevation_materials_invalid", "垫高材料目录格式不正确。", 503)
    components = {c["id"]: c for c in catalog["components"]}
    result = {"posts": [], "spacers": []}
    seen = set()
    for group in ("posts", "spacers"):
        entries = raw.get(group, [])
        if not isinstance(entries, list) or len(entries) > 128:
            raise APIError("elevation_materials_invalid", "垫高接杆和垫片目录必须为最多 128 项的数组。", 503)
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"componentId", "heightMm"}:
                raise APIError("elevation_materials_invalid", "垫高规格必须登记组件编号和高度。", 503)
            cid = entry["componentId"]
            if not isinstance(cid, str) or cid not in components or cid in seen:
                raise APIError("elevation_materials_invalid", "垫高材料引用了未登记或重复组件。", 503)
            if components[cid]["kind"] != "lubang":
                raise APIError("elevation_materials_invalid", "额外垫高接杆与 OP1 垫片必须为登记的麓邦外购件。", 503)
            units = tenths(entry["heightMm"], "垫高材料高度", 1000, False)
            result[group].append({"componentId": cid, "heightMm": units/10})
            seen.add(cid)
        result[group].sort(key=lambda item: (-item["heightMm"], item["componentId"]))
    shim = raw.get("fractionalShim", {"kind": "standard", "unit": "片"})
    if (not isinstance(shim, dict) or shim.get("kind", "standard") != "standard"
            or not isinstance(shim.get("unit", "片"), str) or not shim.get("unit", "片").strip()):
        raise APIError("elevation_materials_invalid", "尾差精密调整片必须登记为通用外购件。", 503)
    result["fractionalShim"] = dict(shim)
    return result


def decompose_height(height_mm, materials):
    """Pure longest-post-first decomposition; quantities are per support point."""
    remaining = tenths(height_mm)
    if not remaining:
        return []
    if not materials:
        raise APIError("elevation_materials_unavailable", "垫高材料规格尚未登记，暂不能生成垫高采购清单。", 409)
    result = []
    for group in ("posts", "spacers"):
        for item in sorted(materials.get(group, []), key=lambda value: (-value["heightMm"], value["componentId"])):
            size = tenths(item["heightMm"], "垫高材料高度", 1000, False)
            count, remaining = divmod(remaining, size)
            if count:
                result.append({**item, "quantityPerSupport": count, "materialType": group[:-1]})
    if remaining >= 10:
        raise APIError("elevation_materials_unavailable", "已登记接杆与 OP1 垫片无法补齐整数毫米余量，请补齐垫片规格。", 409)
    if remaining:
        result.append({"componentId": f"elevation-shim-0p{remaining}", "heightMm": remaining/10,
                       "quantityPerSupport": 1, "materialType": "fractionalShim"})
    return result


def elevation_accessories(catalog, layout, metadata, validation, post_plan=None):
    """Build display groups and component rows solely from normalized layout/catalog."""
    if layout is None:
        return [], []
    post_plan = post_plan if post_plan is not None else universal_post_plan(catalog, layout)
    materials = validate_materials(catalog)
    components = {c["id"]: c for c in catalog["components"]}
    kits = {k["id"]: k for k in catalog["kits"]}
    alignments = {a["instanceId"]: a for a in validation.get("mountingAlignment", [])}
    groups, rows = [], []
    targets = [("board", p) for p in layout.get("subBoards", [])] + [("instance", i) for i in layout["instances"]]
    for target_type, target in targets:
        if target_type == "instance" and target["id"] in post_plan["managedInstanceIds"]:
            continue
        elevation = target.get("elevationMm", 0)
        if not elevation:
            continue
        board = target_type == "board"
        kid = None if board else target["kitId"]
        name = target["name"] if board else kits[kid]["name"]
        supports = support_count(target, metadata.get(kid), alignments.get(target["id"]), board=board)
        group = {"targetType": target_type, "targetId": target["id"], "name": name,
                 "elevationMm": elevation, "supportCount": supports, "materials": []}
        support_spec = None
        if board:
            board_definition = next((b for b in catalog.get("registeredBoards",[]) if b["id"] == target["board"].get("registeredBoardId")), {})
            support_spec = board_definition.get("customElevationSupport")
        if support_spec and abs(support_spec["heightMm"]-elevation) < EPSILON:
            if support_spec["componentId"] not in components:
                raise APIError("elevation_materials_unavailable", "定制支腿缺少元件记录。",409)
            support_parts = [{**support_spec,"quantityPerSupport":1,"materialType":"customSupport"}]
        else:
            support_parts = decompose_height(elevation, materials)
        for part in support_parts:
            if part["materialType"] == "fractionalShim":
                shim = materials["fractionalShim"]
                component = {"id": part["componentId"], "name": f"精密调整片 · {part['heightMm']:g} mm",
                             "kind": "standard", "model": "待确认", "unit": shim.get("unit", "片"),
                             "stepPath": None, "drawingPath": None, "status": "厚度已确定；采购型号待确认",
                             "notes": f"垫高尾差调整，每片厚 {part['heightMm']:g} mm；采购时选择所需内孔与外径。", "sourceUrl": ""}
            else:
                component = components[part["componentId"]]
            quantity = part["quantityPerSupport"]*supports
            group["materials"].append({"componentId": component["id"], "name": component["name"], "kind": component["kind"],
                                       "model": component.get("model") or "待确认", "unit": component["unit"],
                                       "heightMm": part["heightMm"], "quantityPerSupport": part["quantityPerSupport"], "quantity": quantity})
            rows.append({"componentId": component["id"], **{key: component.get(key) for key in (
                "name", "kind", "model", "unit", "stepPath", "drawingPath", "status", "notes", "sourceUrl", "manufacturingSpec")},
                         "quantity": quantity, "kits": [{"kitId": kid, "name": f"{name} / 额外垫高 {elevation:g} mm",
                                                          "quantity": quantity, "perKitQuantity": part["quantityPerSupport"],
                                                          "kitQuantity": supports, "source": "elevation", "targetType": target_type,
                                                          "targetId": target["id"], **({"instanceId": target["id"]} if not board else {"boardId": target["id"]})}]})
        groups.append(group)
    return groups+post_plan["groups"], rows+post_plan["rows"]
