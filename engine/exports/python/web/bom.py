"""Validated catalog and kit aggregation. Catalog files are trusted operator input;
checkout quantities only apply to components already derived from the original BOM.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import unicodedata
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from registered_boards import catalog_operation

MAX_KIT_QUANTITY = 9999
MAX_REQUEST_ITEMS = 100
MAX_COMPONENT_QUANTITY = 10_000_000
MAX_EXTRAS = 2000
KINDS = {"custom", "lubang", "standard"}
MANUFACTURING_FIELDS = {"material": "材料", "surfaceTreatment": "表面处理"}


class APIError(Exception):
    def __init__(self, code, message, status=400, details=None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details

    def payload(self):
        result = {"code": self.code, "message": self.message}
        if self.details is not None:
            result["details"] = self.details
        return {"error": result}


def integer(value, label, maximum=MAX_KIT_QUANTITY):
    if type(value) is not int or not 1 <= value <= maximum:
        raise APIError("invalid_quantity", f"{label}必须是 1 至 {maximum} 的整数。")
    return value


def text(value, label, required=False):
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{label}必须是{'非空' if required else ''}字符串")
    if len(value) > 12000 or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError(f"{label}包含无效字符或内容过长")
    return value.strip()


def note_text(value):
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return "；".join(x.strip() for x in value if x.strip())
    return text(value, "notes")


def registered_path(value, field):
    """Only normalized relative names within the configured asset root."""
    if value in (None, ""):
        return None
    if not isinstance(value, str) or "\\" in value or "\x00" in value or ":" in value:
        raise ValueError(f"{field}必须是资产根目录内的相对路径")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in (".", "..", "") for p in value.split("/")):
        raise ValueError(f"{field}不允许绝对路径或路径回退")
    suffixes = {"stepPath": {".step", ".stp"}, "drawingPath": {".pdf"}, "dxfPath": {".dxf"}, "dxfPdfPath": {".pdf"}}[field]
    if path.suffix.lower() not in suffixes:
        raise ValueError(f"{field}文件类型不符")
    return str(path)


def validate_laser_marking(value):
    """Marking assets have a separate contract from machining DXF supplements."""
    if not isinstance(value, dict) or value.get('status') not in ('required', 'none', 'review'):
        raise ValueError('laserMarking必须声明required、none或review状态')
    if set(value) - {'status', 'reason', 'notes', 'files'}:
        raise ValueError('laserMarking含未登记字段')
    result = copy.deepcopy(value)
    for field in ('reason', 'notes'):
        if field in result:
            result[field] = text(result[field], 'laserMarking.' + field)
    files = result.get('files')
    if not isinstance(files, list):
        raise ValueError('laserMarking.files必须是数组')
    seen = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError('激光打标文件必须是对象')
        if set(item) - {'face', 'dxfPath', 'sha256', 'text', 'setupPdfPath', 'setupPdfSha256'}:
            raise ValueError('激光打标文件含未登记字段')
        item['face'] = text(item.get('face'), 'laserMarking.face', True)
        if item['face'].casefold() in seen:
            raise ValueError('激光打标面名称重复')
        seen.add(item['face'].casefold())
        item['dxfPath'] = registered_path(item.get('dxfPath'), 'dxfPath')
        if not item['dxfPath'] or not isinstance(item.get('sha256'), str) or not re.fullmatch(r'[0-9a-fA-F]{64}', item['sha256']):
            raise ValueError('激光打标文件必须登记DXF路径及SHA256')
        if not (item['dxfPath'].startswith('drawings/') or re.fullmatch(r'sha256/[a-f0-9]{2}/[a-f0-9]{64}\.dxf', item['dxfPath'])):
            raise ValueError('激光打标DXF必须登记在drawings/下')
        item['sha256'] = item['sha256'].lower()
        if ('setupPdfPath' in item) != ('setupPdfSha256' in item):
            raise ValueError('打标定位PDF路径及SHA256必须成对登记')
        if 'setupPdfPath' in item:
            item['setupPdfPath'] = registered_path(item['setupPdfPath'], 'drawingPath')
            if not item['setupPdfPath'] or not (item['setupPdfPath'].startswith('drawings/') or re.fullmatch(r'sha256/[a-f0-9]{2}/[a-f0-9]{64}\.pdf', item['setupPdfPath'])):
                raise ValueError('打标定位PDF必须登记在drawings/下')
            if not isinstance(item['setupPdfSha256'], str) or not re.fullmatch(r'[0-9a-fA-F]{64}', item['setupPdfSha256']):
                raise ValueError('打标定位PDF的SHA256无效')
            item['setupPdfSha256'] = item['setupPdfSha256'].lower()
        if 'text' in item:
            item['text'] = text(item['text'], 'laserMarking.text')
    result['files'] = files
    if result['status'] == 'none' and files:
        raise ValueError('无需激光打标的元件不能同时登记打标文件')
    return result


def laser_marking(row):
    value = row.get('laserMarking')
    return copy.deepcopy(value) if isinstance(value, dict) else {
        'status': 'review', 'reason': '尚无激光打标需求的核验记录', 'files': []}


def laser_marking_label(row):
    marking = laser_marking(row)
    if marking['status'] == 'none':
        return '无需打标'
    if marking['status'] == 'review':
        return '待核实是否打标'
    return '需要打标' if marking.get('files') else '需要打标；DXF待补'


def registered_board_laser_marking(row, catalog):
    """Resolve policy only; a matching custom part never creates another BOM row."""
    current = next((board for board in (catalog or {}).get('registeredBoards', [])
                    if board['id'] == row.get('registeredBoardId') and board['revision'] == row.get('registeredBoardRevision')), None)
    if not current:
        return laser_marking({})
    from registered_boards import board_token
    selected=[h['holeId'] for h in row.get('boardSpec',{}).get('board',{}).get('mountingHoles',[])]
    token = board_token(current,selected)
    if (row.get('generatedBoard') or row.get('sourceComponentId', row.get('componentId')) != 'registered-board-' + token
            or any(row.get(field) != current.get(field) for field in ('stepPath', 'drawingPath', 'dxfPath'))):
        return laser_marking({})
    if current.get('laserMarking') is not None:
        return laser_marking(current)
    # A source board may be another view of a separately registered custom part.
    # Exact matching files permit policy reuse, never quantity reuse or subtraction.
    policies = [laser_marking(component) for component in (catalog or {}).get('components', [])
                if component.get('kind') == 'custom' and component.get('laserMarking') is not None
                and current.get('stepPath') and current.get('drawingPath')
                and all(component.get(field) == current.get(field) for field in ('stepPath', 'drawingPath'))]
    if policies and all(policy == policies[0] for policy in policies):
        return copy.deepcopy(policies[0])
    return laser_marking({})


def validate_catalog(data):
    try:
        if not isinstance(data, dict):
            raise ValueError("catalog必须是对象")
        result = copy.deepcopy(data)
        for field in ("version", "updatedAt"):
            result[field] = text(data.get(field), field, True)
        for field in ("categories", "components", "kits"):
            if not isinstance(data.get(field), list):
                raise ValueError(f"{field}必须是数组")
        category_ids, component_ids, kit_ids = set(), set(), set()
        for cat in result["categories"]:
            cid = text(cat.get("id"), "category.id", True)
            if cid in category_ids:
                raise ValueError(f"重复分类ID：{cid}")
            category_ids.add(cid)
            cat["id"], cat["label"] = cid, text(cat.get("label"), "category.label", True)
        for component in result["components"]:
            cid = text(component.get("id"), "component.id", True)
            if cid in component_ids:
                raise ValueError(f"重复组件ID：{cid}")
            component_ids.add(cid)
            component["id"] = cid
            for field in ("name", "unit"):
                component[field] = text(component.get(field), f"component.{field}", True)
            if component.get("kind") not in KINDS:
                raise ValueError(f"组件 {cid} 的kind无效")
            for field in ("model", "status", "sourceUrl"):
                component[field] = text(component.get(field), field)
            component["notes"] = note_text(component.get("notes"))
            if component.get('laserMarking') is not None:
                component['laserMarking'] = validate_laser_marking(component['laserMarking'])
            if component.get("manufacturingSpec") is not None:
                if not isinstance(component["manufacturingSpec"], dict):
                    raise ValueError(f"组件 {cid} 的manufacturingSpec必须是对象")
                spec = component["manufacturingSpec"]
                for field in (*MANUFACTURING_FIELDS, "generalTolerance", "roughness", "threadClass", "processDetails"):
                    if field in spec:
                        spec[field] = text(spec[field], f"manufacturingSpec.{field}")
                if "surfaceRoughness" in spec:
                    spec["surfaceRoughness"] = text(spec["surfaceRoughness"], "manufacturingSpec.surfaceRoughness")
            for field in ("stepPath", "drawingPath"):
                component[field] = registered_path(component.get(field), field)
            if "dxfPath" in component:
                component["dxfPath"] = registered_path(component.get("dxfPath"), "dxfPath")
            if "dxfPdfPath" in component:
                component["dxfPdfPath"] = registered_path(component.get("dxfPdfPath"), "dxfPdfPath")
            if component["sourceUrl"] and urlsplit(component["sourceUrl"]).scheme not in ("http", "https"):
                raise ValueError(f"组件 {cid} 的来源链接只能为HTTP(S)")
        for kit in result["kits"]:
            kid = text(kit.get("id"), "kit.id", True)
            if kid in kit_ids:
                raise ValueError(f"重复套件ID：{kid}")
            kit_ids.add(kid)
            kit["id"], kit["name"] = kid, text(kit.get("name"), "kit.name", True)
            if kit.get("category") not in category_ids:
                raise ValueError(f"套件 {kid} 的分类未登记")
            for field in ("variant", "description", "status", "sourceUrl"):
                kit[field] = text(kit.get(field), field)
            kit["notes"] = note_text(kit.get("notes"))
            if isinstance(kit.get('layout'),dict) and any(key in kit['layout'] for key in ('manualMountingPolicy','sourceAlignmentReference')):
                from manual_source_mount import source_reference
                if kit.get('category')!='laser':raise ValueError('人工支撑仅能登记在laser源套件')
                source_reference(kit['layout'])
            if isinstance(kit.get('layout'), dict) and 'opticalPortsMm' in kit['layout']:
                from optics_settings import validate_kit_source_ports, normalize_source_port_fields
                for port_id, port in validate_kit_source_ports(kit).items():
                    defaults = port.get('sourceDefaults', {})
                    if not isinstance(defaults, dict) or defaults.get('enabled', False) is not False:
                        raise ValueError(f'额外光源口 {port_id} 的目录默认参数必须关闭出光')
                    normalize_source_port_fields({'sourcePorts': {port_id: {'configured': False, 'source': {**defaults, 'enabled': False}}}}, kit)
                    report = port.get('sourceReport')
                    if report is not None:
                        fields = report.get('applyFields') if isinstance(report, dict) else None
                        if not isinstance(fields, list) or not fields or not all(isinstance(f, str) and f in defaults and f != 'enabled' for f in fields):
                            raise ValueError(f'额外光源口 {port_id} 的报告只能应用本口已声明的独立默认参数')
            if isinstance(kit.get('layout'), dict) and 'opticalAssembly' in kit['layout']:
                from optical_interaction import validate_kit_optical_assembly
                validate_kit_optical_assembly(kit['layout'], kit.get('opticalSlots', []))
            if isinstance(kit.get("layout"), dict) and "opticalInteraction" in kit["layout"]:
                # Only trusted catalog records define the interaction language.
                # Project instances retain parameter values, never executable behavior.
                from optical_interaction import validate_kit_optical_interaction
                kit["layout"]["opticalInteraction"] = validate_kit_optical_interaction(kit["layout"])
            requirements = kit.get("pendingRequirements", [])
            if not isinstance(requirements, list):
                raise ValueError(f"套件 {kid} 的pendingRequirements必须是数组")
            for requirement in requirements:
                text(requirement.get("id"), "pendingRequirement.id", True)
                text(requirement.get("label"), "pendingRequirement.label", True)
            if "optionalNotes" in kit:
                if not isinstance(kit["optionalNotes"], list) or not all(isinstance(n, str) for n in kit["optionalNotes"]):
                    raise ValueError("optionalNotes必须是字符串数组")
            if kit["sourceUrl"] and urlsplit(kit["sourceUrl"]).scheme not in ("http", "https"):
                raise ValueError(f"套件 {kid} 的来源链接只能为HTTP(S)")
            if not isinstance(kit.get("components"), list):
                raise ValueError(f"套件 {kid} 缺少components数组")
            if kit.get('bomPolicy') not in (None,'reference-only'):
                raise ValueError(f'套件 {kid} 的BOM用途无效')
            if kit.get('bomPolicy')=='reference-only' and kit['components']:
                raise ValueError(f'仅布局套件 {kid} 不能同时声明采购或制造BOM')
            seen = set()
            for item in kit["components"]:
                cid = item.get("componentId")
                if cid not in component_ids:
                    raise ValueError(f"套件 {kid} 引用了未登记组件 {cid}")
                if cid in seen:
                    raise ValueError(f"套件 {kid} 的组件 {cid} 重复，请在BOM中合并数量")
                seen.add(cid)
                integer(item.get("quantity"), f"套件 {kid} 组件数量", MAX_COMPONENT_QUANTITY)
            slots, slot_ids, replacement_totals = kit.get("opticalSlots", []), set(), {}
            if not isinstance(slots, list):
                raise ValueError(f"套件 {kid} 的opticalSlots必须是数组")
            component_map = {c["id"]: c for c in result["components"]}
            per_kit = {c["componentId"]: c["quantity"] for c in kit["components"]}
            for slot in slots:
                sid = text(slot.get("id"), "opticalSlot.id", True)
                text(slot.get("label"), "opticalSlot.label", True)
                if sid in slot_ids or slot.get("type") not in ("mirror", "waveplate", "pbs", "lens", "optic"):
                    raise ValueError(f"套件 {kid} 光学槽重复或类型无效")
                slot_ids.add(sid)
                integer(slot.get("quantity"), f"套件 {kid} 光学槽数量", MAX_COMPONENT_QUANTITY)
                diameter = slot.get("diameterMm")
                if diameter is not None and (type(diameter) not in (int, float) or not math.isfinite(diameter) or diameter <= 0):
                    raise ValueError("光学槽diameterMm必须为正数或null")
                replace = slot.get("replacesComponentId")
                if replace is not None:
                    if replace not in per_kit or component_map[replace]["kind"] == "custom":
                        raise ValueError(f"套件 {kid} 光学槽只能替换该套件BOM内的外购组件")
                    replacement_totals[replace] = replacement_totals.get(replace, 0) + slot["quantity"]
                    if replacement_totals[replace] > per_kit[replace]:
                        raise ValueError(f"套件 {kid} 光学槽替换数量超过原BOM数量")
        from elevation import validate_materials, validate_universal_posts
        validate_materials(result)
        validate_universal_posts(result)
        from registered_boards import validate_catalog_boards
        validate_catalog_boards(result)
        for board in result.get('registeredBoards', []):
            if board.get('laserMarking') is not None:
                board['laserMarking'] = validate_laser_marking(board['laserMarking'])
        from moving_stages import validate_catalog_modules
        validate_catalog_modules(result)
        return result
    except (ValueError, KeyError, TypeError, AttributeError, APIError) as exc:
        raise APIError("catalog_invalid", f"套件目录校验失败：{exc}", 503) from exc


def load_catalog(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise APIError("catalog_unavailable", "已核实的套件目录尚未发布。", 503) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise APIError("catalog_unavailable", "套件目录暂时无法读取。", 503) from exc
    return validate_catalog(data)


@catalog_operation
def aggregate(catalog, payload, require_items=False):
    # Exported display metadata is accepted for round trips, but recalculated
    # from the authenticated catalog and normalized layout on every request.
    if not isinstance(payload, dict) or set(payload) - {"items", "catalogVersion", "extras", "layout", "layoutValidation", "boardSpecification", "ui", "checkout", "requires"}:
        raise APIError("invalid_request", "请求只允许items、layout、可选catalogVersion、extras和checkout字段。")
    from moving_stages import validate_capabilities
    capabilities=validate_capabilities(payload.get('requires',[]),payload.get('layout'),catalog)
    if "catalogVersion" in payload and payload["catalogVersion"] != catalog["version"]:
        raise APIError("catalog_changed", "套件目录已更新，请刷新后重新确认清单。", 409)
    kits = {k["id"]: k for k in catalog["kits"]}
    layout, layout_metadata, layout_validation = None, {}, None
    if "layout" in payload:
        from layout import validate_layout
        layout, layout_metadata, layout_validation = validate_layout(payload["layout"], kits)
        counts = OrderedDict()
        for instance in layout["instances"]:
            counts[instance["kitId"]] = counts.get(instance["kitId"], 0) + 1
        items = [{"kitId": kid, "quantity": quantity} for kid, quantity in counts.items()]
        if "items" in payload:
            supplied = payload["items"]
            supplied_counts = {}
            if not isinstance(supplied, list):
                raise APIError("layout_count_conflict", "布局模式的套件数量必须由画布生成。")
            for item in supplied:
                if not isinstance(item, dict) or set(item) != {"kitId", "quantity"} or not isinstance(item["kitId"], str):
                    raise APIError("layout_count_conflict", "布局模式的套件数量必须由画布生成。")
                supplied_counts[item["kitId"]] = supplied_counts.get(item["kitId"], 0) + integer(item["quantity"], "套件数量")
            full_counts = dict(counts)
            for plate in layout.get('subBoards',[]):
                if plate.get('stageMotion'):
                    kid=plate['stageMotion']['moduleId']
                    full_counts[kid]=full_counts.get(kid,0)+1
            if supplied_counts != counts and supplied_counts != full_counts:
                raise APIError("layout_count_conflict", "购物单数量与画布实例数量不一致，请根据画布重新生成。")
    else:
        items = payload.get("items")
    if not isinstance(items, list) or len(items) > MAX_REQUEST_ITEMS:
        raise APIError("invalid_request", f"items必须是最多 {MAX_REQUEST_ITEMS} 项的数组。")
    kits = {k["id"]: k for k in catalog["kits"]}
    components = {c["id"]: c for c in catalog["components"]}
    selected = OrderedDict()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"kitId", "quantity"}:
            raise APIError("invalid_request", "每个购物项只允许kitId和quantity。")
        kid = item["kitId"]
        if not isinstance(kid, str) or kid not in kits:
            raise APIError("unknown_kit", "购物单包含未登记的套件。")
        quantity = integer(item["quantity"], "套件数量")
        selected[kid] = integer(selected.get(kid, 0) + quantity, "同一套件合计数量")
    instances = {i["id"]: i for i in layout["instances"]} if layout is not None else {}
    from elevation import universal_post_plan, apply_post_validation
    post_plan = universal_post_plan(catalog, layout, allow_elevation=False)
    apply_post_validation(layout_validation, post_plan, uniform=False)
    post_quantities, post_instances = {}, {}
    for replacement in post_plan["replacements"]:
        key = (replacement["kitId"], replacement["originalComponentId"])
        post_quantities[key] = post_quantities.get(key, 0)+replacement["quantity"]
        post_instances.setdefault(key, set()).add(replacement["instanceId"])
    scoped_selected = dict(selected)
    for plate in layout.get('subBoards',[]) if layout is not None else []:
        if plate.get('stageMotion'):
            kid=plate['stageMotion']['moduleId']
            scoped_selected[kid]=scoped_selected.get(kid,0)+1
    extras = validate_extras(payload.get("extras", []), scoped_selected, kits, instances)
    if require_items and layout is None and not selected and not extras:
        raise APIError("empty_cart", "请先把需要的套件加入购物单。")
    rows, selected_items, optional_notes, requirements = OrderedDict(), [], [], []
    replacements, replacement_quantities = [], {}
    for extra in extras:
        if extra.get("slotId"):
            slot = next(s for s in kits[extra["kitId"]].get("opticalSlots", []) if s["id"] == extra["slotId"])
            original = slot.get("replacesComponentId")
            if original:
                key = (extra["kitId"], original)
                multiplier = 1 if extra.get("instanceId") else scoped_selected[extra["kitId"]]
                replacement_quantities[key] = replacement_quantities.get(key, 0) + slot["quantity"] * multiplier
                replacements.append({"kitId": extra["kitId"], "slotId": extra["slotId"], "componentId": original,
                                     "perKitQuantity": slot["quantity"], "totalQuantity": slot["quantity"] * multiplier,
                                     **({"instanceId": extra["instanceId"]} if extra.get("instanceId") else {}),
                                     "replacementModel": extra["model"]})
    for kid, quantity in selected.items():
        kit = kits[kid]
        if not kit["components"] and kit.get('bomPolicy')!='reference-only':
            raise APIError("kit_bom_missing", f"套件“{kit['name']}”的组成尚未核实，不能导出。", 409)
        selected_items.append({"kitId": kid, "name": kit["name"], "quantity": quantity,
                               "variant": kit["variant"], "sourceUrl": kit["sourceUrl"]})
        for requirement in kit.get("pendingRequirements", []):
            requirements.append({"kitId": kid, "kitName": kit["name"], **requirement})
            optional_notes.append(f"{kit['name']}：可选补充{requirement['label']}；未填写不计入数量。")
        optional_notes.extend(f"{kit['name']}：{note}" for note in kit.get("optionalNotes", []))
        for line in kit["components"]:
            cid, per_kit = line["componentId"], line["quantity"]
            replaced = replacement_quantities.get((kid, cid), 0)+post_quantities.get((kid, cid), 0)
            contribution = per_kit * quantity - replaced
            if contribution == 0:
                continue
            if contribution < 0:
                raise APIError("invalid_optical_replacement", "光学槽替换数量超过原套件用量。")
            component = components[cid]
            if cid not in rows:
                rows[cid] = {"componentId": cid, **{k: component.get(k) for k in (
                    "name", "kind", "model", "unit", "stepPath", "drawingPath", "dxfPath", "dxfPdfPath", "dxfPdfSha256", "status", "notes", "sourceUrl", "manufacturingSpec", "laserMarking")},
                    "quantity": 0, "kits": []}
                if not rows[cid]["model"]:
                    rows[cid]["model"] = "待确认"
                rows[cid]["status"] = rows[cid]["status"] or "待确认"
            rows[cid]["quantity"] = integer(rows[cid]["quantity"] + contribution, "组件合计数量", MAX_COMPONENT_QUANTITY)
            rows[cid]["kits"].append({"kitId": kid, "name": kit["name"], "quantity": contribution,
                                      "perKitQuantity": per_kit if not replaced else f"原用量 {per_kit}，按选型替换 {replaced} 个",
                                      "kitQuantity": quantity, "source": "catalog",
                                      **({"instanceIds": [i["id"] for i in instances.values() if i["kitId"] == kid and i["id"] not in post_instances.get((kid, cid), set())]} if layout is not None else {})})
    # Board accessories belong to each physical board, independently of its optics.
    if layout is not None:
        from registered_boards import registered, definition
        physical_boards = ([] if layout.get('baseMode') == 'table' else [('root', layout['board'])])
        physical_boards += [(p['id'], p['board']) for p in layout.get('subBoards', []) if not p.get('stageMotion')]
        for board_id, board in physical_boards:
            if not registered(board):continue
            board_record=definition(board,catalog)
            for line in board_record.get('includedComponents',[]):
                cid,contribution=line['componentId'],line['quantity']
                component=components[cid]
                if cid not in rows:
                    rows[cid]={'componentId':cid, **{k:component.get(k) for k in ('name','kind','model','unit','stepPath','drawingPath','dxfPath','dxfPdfPath','dxfPdfSha256','status','notes','sourceUrl','manufacturingSpec','laserMarking')},'quantity':0,'kits':[]}
                    rows[cid]['model']=rows[cid]['model'] or '待确认'
                    rows[cid]['status']=rows[cid]['status'] or '待确认'
                rows[cid]['quantity']=integer(rows[cid]['quantity']+contribution,'板件随附器件合计数量',MAX_COMPONENT_QUANTITY)
                rows[cid]['kits'].append({'kitId':None,'name':board_record['name'],'quantity':contribution,'perKitQuantity':contribution,'kitQuantity':1,'source':'registered-board','boardId':board_id,'registeredBoardId':board_record['id']})
    stage_items = []
    if layout is not None:
        from moving_stages import module_for
        for plate in layout.get('subBoards',[]):
            if not plate.get('stageMotion'):continue
            module = module_for(plate,catalog)
            stage_items.append({'moduleId':module['id'],'revision':module['revision'],'boardId':plate['id'],'name':module['name']})
            for line in module['bom']:
                cid, contribution = line['componentId'], line['quantity']
                component = components[cid]
                if cid not in rows:
                    rows[cid] = {'componentId':cid, **{k:component.get(k) for k in ('name','kind','model','unit','stepPath','drawingPath','dxfPath','dxfPdfPath','dxfPdfSha256','status','notes','sourceUrl','manufacturingSpec','laserMarking')},'quantity':0,'kits':[]}
                    rows[cid]['model'] = rows[cid]['model'] or '待确认'
                    rows[cid]['status'] = rows[cid]['status'] or '待确认'
                rows[cid]['quantity'] = integer(rows[cid]['quantity']+contribution,'位移模块组件合计数量',MAX_COMPONENT_QUANTITY)
                rows[cid]['kits'].append({'kitId':module.get('runtime',{}).get('kitId'), 'name':module['name'], 'quantity':contribution,
                                          'perKitQuantity':contribution,'kitQuantity':1,'source':'stage-module','boardId':plate['id'],'stageModuleId':module['id']})
    for module_id in dict.fromkeys(s['moduleId'] for s in stage_items):
        module_items=[s for s in stage_items if s['moduleId']==module_id]
        selected_items.append({'kitId':module_id,'name':module_items[0]['name'],'quantity':len(module_items),'variant':'位移小面包板','sourceUrl':kits.get(module_id,{}).get('sourceUrl','')})
    for extra in extras:
        if extra.get("inserted") is False:
            continue
        kid = extra["kitId"]
        multiplier = scoped_selected[kid] if kid is not None and not extra.get("instanceId") else 1
        total = integer(extra["quantity"] * multiplier, "补充组件合计数量", MAX_COMPONENT_QUANTITY)
        key = ("extra", extra["id"])
        rows[key] = {"componentId": "extra:" + extra["id"], "name": extra["name"], "kind": extra["kind"],
                     "model": extra["model"] or "待确认", "unit": extra["unit"], "quantity": total,
                     "stepPath": None, "drawingPath": None, "status": "用户补充" if known_model(extra["model"]) else "型号待确认",
                     "notes": extra["notes"], "sourceUrl": "", "supplier": extra.get("supplier", ""),
                     "kits": [{"kitId": kid, "name": kits[kid]["name"] if kid is not None else "整个方案",
                               "quantity": total, "perKitQuantity": extra["quantity"], "kitQuantity": multiplier,
                               "source": "extra", "extraId": extra["id"],
                               **({"instanceId": extra["instanceId"]} if extra.get("instanceId") else {})}]}
        optical_notes = []
        if extra.get("supplier"):
            optical_notes.append("供应商：" + extra["supplier"])
        if extra.get("wavelength"):
            optical_notes.append("波长：" + extra["wavelength"])
        if extra.get("opticalType"):
            optical_notes.append("波片类型：" + {"half-wave": "半波片 λ/2", "quarter-wave": "四分之一波片 λ/4"}[extra["opticalType"]])
        if optical_notes:
            rows[key]["notes"] = "；".join(filter(None, [rows[key]["notes"], *optical_notes]))
    # Explicit post choices remain part of the design; do not synthesize risers or shims.
    elevation_groups, elevation_rows = [], post_plan["rows"]
    for row in elevation_rows:
        cid = row["componentId"]
        if cid not in rows:
            rows[cid] = {**row, "quantity": 0, "kits": []}
        rows[cid]["quantity"] = integer(rows[cid]["quantity"]+row["quantity"], "额外垫高组件合计数量", MAX_COMPONENT_QUANTITY)
        rows[cid]["kits"].extend(row["kits"])
    if layout_validation:
        from laser_adapter import adapter_row
        for record in layout_validation.get("laserAdapters", []):
            row = adapter_row(record)
            cid = row["componentId"]
            if cid not in rows:
                rows[cid] = {**row, "quantity": 0, "kits": []}
            rows[cid]["quantity"] = integer(rows[cid]["quantity"]+1, "激光器垫板数量", MAX_COMPONENT_QUANTITY)
            rows[cid]["kits"].extend(row["kits"])
    stage_top_ids={line['componentId'] for module in catalog.get('stageModules',[]) for line in module['bom'] if line.get('role')=='top-plate'}
    for cid,row in rows.items():
        if cid in stage_top_ids:row['stageTopPlate']=True
    review_rows = copy.deepcopy(list(rows.values()))
    rows = merge_purchased_rows(rows)
    result = {"catalogVersion": catalog["version"], "items": selected_items,
              "extras": extras, "elevationAccessories": elevation_groups, "universalPostReplacements": post_plan["replacements"],
              "lubang": [], "manufacturing": [], "standard": [],
              "warnings": [], "pendingRequirements": requirements,
              "replacements": replacements,
              "optionalNotes": list(dict.fromkeys(optional_notes)),
              "stageModules": stage_items,
              "scopeNote": "按已建模器件 + 本次补充项；未填写光学片/螺钉不自动计入。"}
    if capabilities:result["requires"]=capabilities
    kind_key = {"custom": "manufacturing", "lubang": "lubang", "standard": "standard"}
    for row in rows.values():
        result[kind_key[row["kind"]]].append(row)
    result["totals"] = {"kits": sum(selected.values())+len(stage_items), "componentTypes": len(rows),
                        "componentQuantity": sum(row["quantity"] for row in rows.values())}
    if layout is not None:
        from breadboard import board_row
        # Filter entities before merging equal board specifications: a child
        # matching the reference workspace is still a physical board to make.
        table = layout.get('baseMode') == 'table'
        boards = ([] if table else [layout['board']]) + [p['board'] for p in layout.get('subBoards',[]) if not p.get('stageMotion')]
        board_rows = {}
        for b in boards:
            row=board_row(b)
            if row['componentId'] in board_rows:board_rows[row['componentId']]['quantity']+=1
            else:board_rows[row['componentId']]=row
        for board_component in board_rows.values():
            result["manufacturing"].append(board_component)
            board_component["manufacturingSpec"] = manufacturing_spec(board_component)
            review_rows.append(copy.deepcopy(board_component))
        result["totals"]["componentTypes"] += len(board_rows)
        result["totals"]["componentQuantity"] += len(boards)
        result["totals"]["boards"] = len(boards)+len(stage_items)
        result["totals"]["stageModules"] = len(stage_items)
        result["layout"] = layout
        result["layoutValidation"] = layout_validation
        result["layoutExtras"] = validate_extras(payload.get("extras", []), scoped_selected, kits, instances, keep_unfilled=True)
        result["layoutKitMetadata"] = {kid: {**geometry, "name": kits[kid]["name"]} for kid, geometry in layout_metadata.items()}
        result["scopeNote"] += (f" 数量由全部画布实例生成；桌子／无大板模式不加工根板，小面包板共 {len(boards)} 块计入生产单，材料及工艺以生产清单为准。" if table else
                                f" 数量由全部画布实例生成；面包板共 {len(boards)} 块计入生产单，登记板按原外形及孔位计入，材料及工艺以生产清单为准。")
    if stage_items:
        result['scopeNote'] += f' 手动位移模块 {len(stage_items)} 套按登记组合BOM计入，上面包板已包含且不重复加工；厂家台实装定位及制造审签仍待核验。'
    # Dynamically selected catalog posts also use the current component policy.
    for row in result['manufacturing']:
        component = components.get(row['componentId'])
        row['laserMarking'] = registered_board_laser_marking(row, catalog) if row.get('registeredBoard') else laser_marking(component or row)
    review_kits = [kits[kid] for kid in selected]+[kits[m["moduleId"]] for m in stage_items if m["moduleId"] in kits]
    if "checkout" in payload:
        selected_rows = apply_checkout(result, payload["checkout"], require_items)
        source_ids = {cid for row in selected_rows for cid in row.get("componentIds", [row["componentId"]])}
        review_rows = [row for row in review_rows if row["componentId"] in source_ids]
        source_kits = {source["kitId"] for row in selected_rows for source in row["kits"] if source["kitId"] is not None}
        review_kits = [kit for kit in review_kits if kit["id"] in source_kits]
    result["reviewGroups"] = build_review_groups(review_rows, review_kits)
    result["warnings"] = [group["summary"] for group in result["reviewGroups"]]
    if layout_validation and not layout_validation["valid"]:
        result["warnings"].insert(0, f"布局尚不可用：{len(layout_validation['issues'])} 项定位、碰撞或光轴高度问题，请在画布中调整。")
    result["lubangImport"] = lubang_import_plan(result["lubang"])
    return result


def lubang_import_plan(rows):
    """Separate importable model strings from unresolved identities, without guessing.

    This validates declared model syntax and explicit identity doubts, not stock
    or supplier catalog existence. Manufacturing review notes are unrelated.
    """
    ready, blocked = [], []
    for row in rows:
        model = str(row.get("model") or "").strip()
        status, notes = str(row.get("status") or ""), str(row.get("notes") or "")
        reason = None
        if row.get("lubangImportReasons"):
            reason = "；".join(row["lubangImportReasons"])
        elif not known_model(model):
            reason = "尚未填写明确的麓邦产品型号"
        elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/\-]*", model):
            reason = "产品型号须使用半角字母、数字及型号标点，不能含空格或说明文字"
        else:
            # Explicit model/alias doubts block an import; unrelated process,
            # documentation or verification statuses must not block ordering.
            clauses = re.split(r"[；。，,\n]", status + "；" + notes)
            doubtful = [part for part in clauses if pending_text(part) and any(term in part for term in ("采购型号", "型号映射", "别名", "导入尾缀"))]
            if any("型号" in part and pending_text(part) for part in re.split(r"[；。，,\n]", status)) or doubtful:
                reason = "采购型号或原装配别名尚未确认，不能作为厂商型号导入"
        item = {"componentId": row["componentId"], "name": row["name"], "model": model,
                "quantity": row["quantity"]}
        if reason:
            blocked.append({**item, "reason": reason})
        else:
            ready.append(item)
    return {"ready": ready, "blocked": blocked, "readyTypes": len(ready), "blockedTypes": len(blocked)}


def apply_checkout(result, checkout, require_items=False):
    """Select merged rows and override quantities without mutating their source BOM.

    An explicit empty list is a valid review state but cannot produce an order.
    File paths, process fields and original provenance remain catalog-derived.
    """
    categories = ("lubang", "manufacturing", "standard")
    available = {row["componentId"]: row for category in categories for row in result[category]}
    if not isinstance(checkout, dict) or set(checkout) != {"items"} or not isinstance(checkout["items"], list):
        raise APIError("invalid_checkout", "清单确认只允许items数组，每项填写componentId和quantity。")
    if len(checkout["items"]) > len(available):
        raise APIError("invalid_checkout", "清单确认项目数量超过原方案，请重新生成清单。")
    quantities = {}
    for item in checkout["items"]:
        if not isinstance(item, dict) or set(item) != {"componentId", "quantity"}:
            raise APIError("invalid_checkout", "每个清单确认项只允许componentId和quantity。")
        cid = item["componentId"]
        if not isinstance(cid, str) or cid not in available:
            raise APIError("unknown_checkout_component", "清单中包含当前方案没有的器件，请重新生成清单。", 409)
        if cid in quantities:
            raise APIError("duplicate_checkout_component", "清单中同一器件不能重复提交。")
        quantities[cid] = integer(item["quantity"], "导出数量", MAX_COMPONENT_QUANTITY)
    if require_items and not quantities:
        raise APIError("empty_checkout", "请至少勾选一项需要导出的器件。")
    chosen = []
    for category in categories:
        result[category] = [row for row in result[category] if row["componentId"] in quantities]
        for row in result[category]:
            row["baseQuantity"] = row["quantity"]
            row["quantity"] = quantities[row["componentId"]]
            chosen.append(row)
    result["checkout"] = {"items": [{"componentId": row["componentId"], "quantity": row["quantity"]} for row in chosen]}
    result["totals"]["componentTypes"] = len(chosen)
    result["totals"]["componentQuantity"] = sum(row["quantity"] for row in chosen)
    if result.get("layout") is not None:
        result["totals"]["boards"] = sum(row["quantity"] for row in chosen if row.get("generatedBoard") or row.get('registeredBoard') or row.get('stageTopPlate'))
    result["scopeNote"] = "按清单确认后的勾选项目和修改数量导出；原套件、补充选型及布局保留作参考，不代表本次下单数量。未填写光学片/螺钉不自动计入。"
    return chosen


def manufacturing_spec(row):
    """Uniform export view; catalog or generated-board values remain authoritative."""
    spec = row.get("manufacturingSpec")
    if not isinstance(spec, dict):
        board = row.get("boardSpec", {})
        spec = board.get("manufacturingSpec") if isinstance(board,dict) else None
        if not isinstance(spec,dict):
            spec = board if isinstance(board,dict) else {}
    result = {field: str(spec.get(field) or "待确认") for field in MANUFACTURING_FIELDS}
    return result


def pending_text(value):
    value = str(value or "").lower()
    return any(word in value for word in ("待", "未确认", "未核实", "未核对", "未标明", "pending", "unconfirmed", "unknown", "tbd"))


def review_item(code, summary, rows, details="", fields=None, blocking=False):
    item = {"code":code,"summary":summary,"details":details,
            "componentIds":list(dict.fromkeys(r["componentId"] for r in rows)),
            "componentNames":list(dict.fromkeys(r["name"] for r in rows)),
            "blocking":blocking,"blockedExports":["bundle"] if blocking else []}
    if fields is not None:item["fields"]=fields
    return item


def build_review_groups(rows, selected_kits=()):
    """Concise review notes derived after optional optics have replaced the BOM.

    These are procurement/manufacturing review requirements, not application
    exceptions. Only missing registered source files block the complete bundle.
    """
    manufacture,procurement,sources=[],[],[]
    missing_by_field={field:[] for field in MANUFACTURING_FIELDS}
    file_missing,versions,incomplete=[],[],[]
    version_details,incomplete_details=[],[]
    for row in rows:
        status,notes=str(row.get("status") or ""),str(row.get("notes") or "")
        clauses=[part.strip() for part in re.split(r"[；。\n]",status+"；"+notes) if part.strip()]
        if row["kind"]=="custom":
            if not known_model(row.get("model")):
                sources.append(review_item("source_identifier",f"{row['name']}：零件型号或图号待确认。",[row],notes))
            explicit=isinstance(row.get("manufacturingSpec"),dict) or isinstance(row.get("boardSpec"),dict)
            if explicit:
                spec=manufacturing_spec(row)
                missing=[field for field in MANUFACTURING_FIELDS if not spec[field].strip() or pending_text(spec[field])]
            else:
                # Compatibility with archived entries that predate structured
                # process fields. A confirmed legacy row is not reclassified.
                pending_clauses=[part for part in clauses if pending_text(part)]
                missing=[field for field,label in MANUFACTURING_FIELDS.items() if any(label in part for part in pending_clauses)]
            for field in missing:missing_by_field[field].append(row)
            if not row.get("generatedBoard") and not row.get("generatedLaserAdapter"):
                fields=[name for field,name in (("stepPath","STEP"),("drawingPath","图纸")) if not row.get(field)]
                if fields:file_missing.append((row,fields))
            if row.get("generatedLaserAdapter") and not row.get("adapterSpec", {}).get("mountingDatumConfirmed"):
                sources.append(review_item("adapter_mounting_datum",f"{row['name']}：激光器孔组绝对基准待实物核对；图纸为加工审核版。",[row],notes))
            changed_threads = [source for source in row.get("kits", []) if source.get("source") == "universalPostReplacement"
                               and source.get("originalTopThread") and source.get("replacementTopThread")
                               and source["originalTopThread"] != source["replacementTopThread"]]
            if changed_threads:
                details = "；".join(f"实例 {source['instanceId']}：原柱顶部 {source['originalTopThread']} → 替换柱顶部 {source['replacementTopThread']}" for source in changed_threads)
                manufacture.append(review_item("universal_post_connection",f"{row['name']}：换柱后顶部连接螺纹变化，请核对转接件与螺钉。",[row],details))
            version=[part for part in clauses if "版本" in part and pending_text(part)]
            if version:
                versions.append(row);version_details.extend(version)
            partial=[part for part in clauses if any(token in part for token in ("未全部标完","标注不完整","尺寸未补齐","尺寸待补充"))]
            if partial:
                incomplete.append(row);incomplete_details.append(f"{row['name']}："+"；".join(partial))
        else:
            if not known_model(row.get("model")):
                procurement.append(review_item("procurement_model",f"{row['name']}：厂商型号待确认。",[row],notes))
            elif "供应商" in status and pending_text(status):
                procurement.append(review_item("procurement_supplier",f"{row['name']}（{row['model']}）：供应商待确认。",[row],notes))
            elif pending_text(status):
                label="采购型号映射待确认" if ("型号" in status or "别名" in notes or "映射" in notes) else status
                procurement.append(review_item("procurement_confirmation",f"{row['name']}（{row['model']}）：{label}。",[row],notes))
    for code,fields in (("manufacturing_materials",["material","surfaceTreatment"]),):
        active=[field for field in fields if missing_by_field[field]]
        if not active:continue
        affected={r["componentId"]:r for field in active for r in missing_by_field[field]}
        labels="、".join(MANUFACTURING_FIELDS[field] for field in active)
        summary=f"{labels}待确认（涉及 {len(affected)} 种自制件）。"
        detail_parts=[f"{MANUFACTURING_FIELDS[field]}：{len(missing_by_field[field])} 种零件" for field in active]
        details="；".join(detail_parts)+"。已明确的材料和表面处理以生产清单逐件记录为准。"
        manufacture.append(review_item(code,summary,list(affected.values()),details,active))
    if file_missing:
        details="；".join(f"{row['name']}：缺少{' / '.join(fields)}" for row,fields in file_missing)
        sources.append(review_item("source_file_missing",f"{len(file_missing)} 种零件缺少 STEP 或图纸，完整生产包暂不可导出。",
                                   [row for row,_ in file_missing],details,blocking=True))
    if versions:
        sources.append(review_item("source_version",f"{len(versions)} 种零件与原装配的源文件版本对应待核对。",versions,"；".join(dict.fromkeys(version_details))))
    if incomplete:
        sources.append(review_item("drawing_incomplete",f"{len(incomplete)} 种零件的参考图尺寸标注尚未完整。",incomplete,"；".join(incomplete_details)))
    for kit in selected_kits:
        if kit.get('bomPolicy')=='reference-only':
            sources.append({'code':'reference_assembly','summary':f'{kit["name"]}：仅作整装布局参考，内部零件未核对，不计入采购或生产数量。',
                            'details':str(kit.get('notes') or ''),'kitIds':[kit['id']],'componentIds':[],'componentNames':[],
                            'blocking':False,'blockedExports':[]})
            continue
        # Catalog kit statuses for model/supplier/process are derived summaries;
        # row reviews above are precise and disappear after an explicit replacement.
        status=str(kit.get("status") or "")
        if pending_text(status) and not any(term in status for term in ("型号","供应商","规格","工艺")):
            sources.append({"code":"kit_review","summary":f"{kit['name']}：{status}。","details":str(kit.get("notes") or ""),
                            "kitIds":[kit["id"]],"componentIds":[],"componentNames":[],"blocking":False,"blockedExports":[]})
    result=[]
    for gid,title,items in (("manufacture","加工要求",manufacture),("procurement","采购选型",procurement),("sourceFiles","模型与图纸",sources)):
        if not items:continue
        if len(items)<=3:
            summary=title+"："+"；".join(item["summary"].rstrip("。") for item in items)+"。"
        else:
            summary=f"{title}：{len(items)} 项信息需要核对，详见确认事项。"
        result.append({"id":gid,"title":title,"summary":summary,"blocking":any(i["blocking"] for i in items),
                       "blockedExports":["bundle"] if any(i["blocking"] for i in items) else [],"items":items})
    return result


def known_model(value):
    return bool(value and value.strip() and value.strip().lower() not in ("tbd", "unknown", "pending", "unconfirmed")
                and "待确认" not in value and "待定" not in value)


def validate_extras(extras, selected, kits, instances=None, keep_unfilled=False):
    instances = instances or {}
    if not isinstance(extras, list) or len(extras) > MAX_EXTRAS:
        raise APIError("invalid_extras", "extras必须是最多2000项的数组。")
    normalized, ids, filled_slots = [], set(), set()
    allowed = {"id", "kitId", "kind", "name", "model", "quantity", "unit", "notes", "slotId", "wavelength", "opticalType", "instanceId", "inserted", "supplier"}
    for extra in extras:
        if not isinstance(extra, dict) or set(extra) - allowed or not {"id", "kitId", "kind", "name", "quantity", "unit"}.issubset(extra):
            raise APIError("invalid_extras", "补充项包含缺失或未允许的字段。")
        try:
            row = {field: text(extra.get(field), f"extra.{field}", field in ("id", "name", "unit"))
                   for field in ("id", "name", "model", "unit", "notes")}
        except ValueError as exc:
            raise APIError("invalid_extras", str(exc)) from exc
        if any(len(row[k]) > limit for k, limit in (("id", 80), ("name", 256), ("model", 256), ("unit", 24), ("notes", 2000))):
            raise APIError("invalid_extras", "补充项文字过长。")
        if row["id"] in ids:
            raise APIError("invalid_extras", "补充项id不能重复。")
        ids.add(row["id"])
        if extra["kind"] not in ("lubang", "standard"):
            raise APIError("invalid_extras", "补充项类型只能是lubang或standard。")
        kid = extra["kitId"]
        if kid is not None and (not isinstance(kid, str) or kid not in selected):
            raise APIError("invalid_extras", "补充项kitId必须是购物单中的套件，或用null表示整个方案。")
        row.update(kitId=kid, kind=extra["kind"], quantity=integer(extra["quantity"], "补充项数量"))
        if "supplier" in extra:
            try:
                supplier = text(extra["supplier"], "supplier")
            except ValueError as exc:
                raise APIError("invalid_extras", str(exc)) from exc
            if len(supplier) > 256:
                raise APIError("invalid_extras", "供应商名称不能超过256字。")
            row["supplier"] = supplier
        if "inserted" in extra:
            if type(extra["inserted"]) is not bool:
                raise APIError("invalid_optical_parameters", "光学片安装状态必须为布尔值。")
            row["inserted"] = extra["inserted"]
        iid = extra.get("instanceId")
        if "instanceId" in extra:
            if not isinstance(iid, str) or iid not in instances or instances[iid]["kitId"] != kid:
                raise APIError("invalid_extra_instance", "补充项必须关联画布中该套件的有效实例。")
            row["instanceId"] = iid
        if "slotId" in extra:
            sid = extra["slotId"]
            if not isinstance(sid, str) or kid is None:
                raise APIError("invalid_optical_slot", "光学槽必须属于购物单中的套件。")
            slots = {s["id"]: s for s in kits[kid].get("opticalSlots", [])}
            key = (kid, sid, iid)
            duplicate = key in filled_slots or (iid is not None and (kid, sid, None) in filled_slots) or (iid is None and any(k[:2] == (kid, sid) for k in filled_slots))
            if sid not in slots or duplicate:
                raise APIError("invalid_optical_slot", "光学槽未登记或重复提交，不能同时按套件和按实例重复选型。")
            filled_slots.add(key)
            slot = slots[sid]
            if row["quantity"] != slot["quantity"]:
                raise APIError("invalid_optical_quantity", "光学片每套数量应与该套件光学槽数量一致。")
            try:
                wavelength = text(extra.get("wavelength"), "wavelength")
                optical_type = text(extra.get("opticalType"), "opticalType")
            except ValueError as exc:
                raise APIError("invalid_optical_parameters", str(exc)) from exc
            if len(wavelength) > 80 or optical_type not in ("", "half-wave", "quarter-wave"):
                raise APIError("invalid_optical_parameters", "波长过长或波片类型无效。")
            if optical_type and slot["type"] != "waveplate":
                raise APIError("invalid_optical_parameters", "只有波片槽可设置半波片或四分之一波片。")
            row.update(slotId=sid, wavelength=wavelength, opticalType=optical_type)
            if not known_model(row["model"]) and "inserted" not in row:
                # A wavelength alone never creates an item or removes the
                # existing modeled optic. Keep draft values in downloadable layouts.
                if keep_unfilled:
                    normalized.append(row)
                continue
        elif any(k in extra for k in ("wavelength", "opticalType", "inserted")):
            raise APIError("invalid_optical_slot", "波长和波片类型必须关联已登记的光学槽。")
        normalized.append(row)
    return normalized


def merge_purchased_rows(rows):
    merged = OrderedDict()
    for identity, row in rows.items():
        key = (row["kind"], unicodedata.normalize("NFKC", row["model"]).strip().casefold(), row["unit"].strip()) \
            if row["kind"] != "custom" and known_model(row["model"]) else ("identity", identity)
        if row["kind"] == "standard" and row.get("supplier"):
            key += (unicodedata.normalize("NFKC", row["supplier"]).strip().casefold(),)
        if key not in merged:
            row["componentIds"] = [row["componentId"]]
            merged[key] = row
            continue
        existing = merged[key]
        existing["quantity"] = integer(existing["quantity"] + row["quantity"], "同型号组件合计数量", MAX_COMPONENT_QUANTITY)
        existing["componentIds"].append(row["componentId"])
        existing["kits"].extend(row["kits"])
        if row["notes"] and row["notes"] != existing["notes"]:
            existing["notes"] = "；".join(filter(None, [existing["notes"], row["notes"]]))
        if any(k["source"] == "extra" for k in row["kits"]):
            if "含用户补充" not in existing["status"]:
                existing["status"] += "；含用户补充"
    return merged
