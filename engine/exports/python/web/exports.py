"""In-memory XLSX / ZIP outputs. Only operator-registered CAD assets may be read."""
from __future__ import annotations

import hashlib
import csv
import copy
import io
import json
import os
import tempfile
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from bom import APIError, MANUFACTURING_FIELDS, manufacturing_spec, lubang_import_plan, laser_marking, laser_marking_label

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_ASSET_BYTES = 256 * 1024 * 1024
HEADERS = ["序号", "组件编号", "名称", "型号 / 图号", "数量", "单位"]
MARKING_HEADERS = ['激光打标', '打标数量', '打标面及内容', '打标DXF与定位说明', '打标说明']
LUBANG_TEMPLATE = Path(__file__).resolve().parent / "assets/templates/lbtek-cart-import.xlsx"


def safe_asset(asset_root, registered_name, label):
    if not registered_name:
        raise APIError("asset_missing", f"{label}未登记，无法生成完整生产包。", 409)
    root = Path(asset_root).resolve()
    candidate = root / registered_name
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except FileNotFoundError as exc:
        raise APIError("asset_missing", f"{label}文件不存在，无法生成完整生产包。", 409) from exc
    except (ValueError, OSError) as exc:
        raise APIError("asset_forbidden", f"{label}不在登记的资产目录内。", 409) from exc
    if not resolved.is_file():
        raise APIError("asset_missing", f"{label}不是可读取文件。", 409)
    # Do not follow symlinks even if the present target happens to be inside root.
    current = candidate
    while current != root:
        if current.is_symlink():
            raise APIError("asset_forbidden", f"{label}不允许使用符号链接。", 409)
        current = current.parent
    return resolved


def cell_value(cell, value):
    cell.value = value
    if isinstance(value, str):
        # Explicit string type stops catalog text beginning with =/+/-/@ from
        # becoming executable spreadsheet formulas.
        cell.data_type = "s"


def sheet_table(wb, name, title, headers, rows, widths, generated_at):
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.sheet_properties.tabColor = "253B53"
    cell_value(ws["A2"], title)
    ws["A2"].font = Font(name="Arial", size=15, bold=True, color="253B53")
    cell_value(ws["A3"], f"导出时间：{generated_at}　按已建模器件 + 本次补充项；未填写光学片/螺钉不自动计入。")
    ws["A3"].font = Font(name="Arial", size=10, color="526474")
    for c, header in enumerate(headers, 1):
        cell = ws.cell(5, c)
        cell_value(cell, header)
        cell.fill = PatternFill("solid", fgColor="253B53")
        cell.font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(bottom=Side(style="thin", color="B7C3CF"))
    ws.row_dimensions[5].height = 30
    for r, row in enumerate(rows, 6):
        max_lines = 1
        for c, value in enumerate(row, 1):
            cell = ws.cell(r, c)
            cell_value(cell, value)
            cell.font = Font(name="Arial", size=11, color="253342")
            cell.alignment = Alignment(horizontal="right" if isinstance(value, (int, float)) else "left", vertical="top", wrap_text=True)
            if isinstance(value, int):
                cell.number_format = "#,##0"
            if r % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="F1F5F8")
            if isinstance(value, str):
                width = widths[c-1]
                estimated_width = sum(2 if ord(ch) > 127 else 1 for ch in value)
                max_lines = max(max_lines, (estimated_width + width - 1) // width, len(value.splitlines()))
                if "待确认" in value:
                    cell.font = Font(name="Arial", size=11, color="8A4C08")
        ws.row_dimensions[r].height = max(30, 16 * max_lines + 6)
    if not rows:
        cell_value(ws["A6"], "本次没有此类项目")
        ws["A6"].font = Font(name="Arial", size=11, color="526474")
        ws.row_dimensions[6].height = 24
    for index, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "D6"
    ws.auto_filter.ref = f"A5:{get_column_letter(len(headers))}{max(5, 5+len(rows))}"
    ws.print_title_rows = "1:5"
    ws.print_options.horizontalCentered = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.print_area = f"A1:{get_column_letter(len(headers))}{max(6, 5+len(rows))}"
    return ws


def marking_values(row, asset_map=None):
    marking = laser_marking(row)
    files = marking.get('files', [])
    mapped = (asset_map or {}).get(row['componentId'], {})
    delivered = mapped.get('laserMarking', files)
    missing = mapped.get('laserMarkingMissing', [])
    paths = [p for item in delivered for p in (item.get('dxfPath'), item.get('setupPdfPath')) if p]
    label = laser_marking_label(row) + ('；资料待补' if missing and files else '')
    return [label, row['quantity'] if marking['status'] == 'required' else 0 if marking['status'] == 'none' else '待核实',
            '；'.join(item['face'] + ('：' + item['text'] if item.get('text') else '') for item in files),
            '\n'.join(paths) or ('DXF待补' if marking['status'] == 'required' else ''),
            '；'.join([*(str(marking[field]) for field in ('reason', 'notes') if marking.get(field)), *missing])]


def component_rows(rows, manufacturing=False, asset_map=None):
    result = []
    for index, row in enumerate(rows, 1):
        values = [index, row["componentId"], row["name"], row["model"], row["quantity"], row["unit"]]
        if manufacturing:
            spec=manufacturing_spec(row)
            values.extend(spec[field] for field in MANUFACTURING_FIELDS)
            values.extend(marking_values(row, asset_map))
        result.append(values)
    return result


def manufacturing_csv_bytes(preview, asset_map=None):
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow(HEADERS + list(MANUFACTURING_FIELDS.values()) + MARKING_HEADERS)
    for row in component_rows(preview['manufacturing'], manufacturing=True, asset_map=asset_map):
        # CSV has no explicit string cell type. Escape catalog text formula prefixes.
        writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value for value in row])
    return buffer.getvalue().encode('utf-8-sig')


def lubang_workbook_bytes(import_plan):
    """Fill the supplied vendor template, preserving its first-sheet positions."""
    try:
        wb = load_workbook(LUBANG_TEMPLATE)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise APIError("lubang_template_unavailable", "麓邦购物车导入模板暂时无法读取，请稍后重试。", 503) from exc
    ws = wb["Sheet1"]
    if [ws.cell(3, column).value for column in (1, 2, 3)] != ["序号", "产品型号（Product Name）", "数量（Quantity）"]:
        raise APIError("lubang_template_unavailable", "麓邦导入模板格式与登记版本不一致。", 503)
    # SKU strings may be case-insensitive in the vendor importer. Consolidate
    # multiple local unit labels into a single literal model and integer count.
    quantities = {}
    for item in import_plan["ready"]:
        key = item["model"].casefold()
        if key not in quantities:
            quantities[key] = {"model": item["model"], "quantity": 0}
        quantities[key]["quantity"] += item["quantity"]
    for index, item in enumerate(quantities.values(), 1):
        row = index + 3
        if row > 53:
            for column in (1, 2, 3):
                ws.cell(row, column)._style = copy.copy(ws.cell(5, column)._style)
            ws.row_dimensions[row].height = ws.row_dimensions[5].height
        cell_value(ws.cell(row, 1), index)
        cell_value(ws.cell(row, 2), item["model"])
        cell_value(ws.cell(row, 3), item["quantity"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def lubang_pending_workbook_bytes(preview, import_plan, generated_at):
    wb = Workbook()
    wb.remove(wb.active)
    unit_by_id = {row["componentId"]: row["unit"] for row in preview["lubang"]}
    sheet_table(wb, "未导入项目", "麓邦待确认清单（这些项目未写入购物车导入表）", HEADERS + ["未导入原因"],
                [[index, item["componentId"], item["name"], item["model"], item["quantity"],
                  unit_by_id[item["componentId"]], item["reason"]] for index, item in enumerate(import_plan["blocked"], 1)],
                [8, 24, 36, 30, 12, 10, 80], generated_at)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def workbook_bytes(preview, kind, generated_at, asset_map=None):
    if kind == "lubang":
        plan = lubang_import_plan(preview["lubang"])
        if plan["blocked"]:
            names = "、".join(item["name"] + "（" + (item["model"] or "未填型号") + "）" for item in plan["blocked"][:5])
            raise APIError("lubang_model_unconfirmed", f"以下麓邦器件暂不能导入购物车：{names}。请填写明确的产品型号，或取消这些项目的勾选。完整资料包会另附待确认清单。", 409, {"items": plan["blocked"]})
        return lubang_workbook_bytes(plan)
    wb = Workbook()
    wb.remove(wb.active)
    widths = [8, 24, 30, 24, 12, 10]
    if kind == "manufacturing":
        sheet_table(wb, "生产清单", "自制零件生产清单", HEADERS+list(MANUFACTURING_FIELDS.values())+MARKING_HEADERS,
                    component_rows(preview["manufacturing"], manufacturing=True, asset_map=asset_map), widths+[28, 32, 28, 14, 40, 60, 60], generated_at)
        adapters = [row for row in preview["manufacturing"] if row.get("generatedLaserAdapter")]
        if adapters:
            from laser_adapter import validate_adapter_spec
            specs = [(row, validate_adapter_spec(row.get("adapterSpec"))) for row in adapters]
            sheet_table(wb, "激光器底板", "所选激光器安装底板与装配顺序",
                        ["组件编号", "图号", "数量", "外形 / mm", "厚度 / mm", "材料", "表面处理", "激光器连接孔", "面包板固定孔", "孔组基准状态", "装配顺序"],
                        [[row["componentId"], s["model"], row["quantity"], "543 × 261", s["thicknessMm"], s["material"], s["surfaceTreatment"],
                          "4-M6×1（STEP 以 Ø5 底孔表示）", "4-Ø6.6 通孔；顶面 Ø11 圆柱沉孔深 6.5",
                          "用户已核对孔组基准；加工审核版" if s["mountingDatumConfirmed"] else "孔组基准待实物核对；加工审核版",
                          "先固定底板，再安装激光器；激光器壳体可能遮挡底板沉孔"] for row, s in specs],
                        [48, 34, 12, 24, 16, 28, 32, 50, 52, 48, 64], generated_at)
            sheet_table(wb, "激光器底板孔表", "激光器底板孔位（原点为激光器主壳体俯视中心投影；X 右、Y 上）",
                        ["图号", "孔号", "X / mm", "Y / mm", "加工标注"],
                        [[s["model"], hole["label"], hole["xMm"], hole["yMm"], callout]
                         for _, s in specs for key, callout in (("laserThreadHolesMm", "M6×1"), ("boardMountingHolesMm", "Ø6.6 通孔；顶面 Ø11 圆柱沉孔深 6.5")) for hole in s[key]],
                        [38, 14, 20, 20, 70], generated_at)
    elif kind == "standard":
        purchase_rows = [values + [row.get("supplier") or "待确认"]
                         for values, row in zip(component_rows(preview["standard"]), preview["standard"])]
        sheet_table(wb, "通用外购件", "通用外购件清单", HEADERS + ["供应商"], purchase_rows, widths + [28], generated_at)
    else:
        raise ValueError(kind)
    breakdown = []
    for category in ("lubang", "manufacturing", "standard"):
        for component in preview[category]:
            for kit in component["kits"]:
                breakdown.append([kit["kitId"] or "整个方案", kit["name"], kit["kitQuantity"], component["componentId"], component["name"],
                                  {"lubang":"麓邦", "custom":"自制", "standard":"通用外购"}[component["kind"]],
                                  kit["perKitQuantity"], kit["quantity"], component["unit"], {"extra":"本次补充", "elevation":"额外垫高", "universalPostReplacement":"万能柱替换"}.get(kit.get("source"), "已建模BOM")])
    checkout = "checkout" in preview
    sheet_table(wb, "套件分解", "原方案套件分解（仅供溯源，非下单数量）" if checkout else "套件数量与组件贡献", ["套件编号", "套件名称", "原套件数量" if checkout else "套件数量", "组件编号", "组件名称", "类型", "原每套 / 每方案用量" if checkout else "每套 / 每方案用量", "原方案贡献数量" if checkout else "本项贡献数量", "单位", "来源"],
                breakdown, [24, 36, 14, 24, 32, 14, 22, 22, 10, 18], generated_at)
    if preview.get("layout"):
        board = preview["layout"]["board"]
        names = {k["kitId"]: k["name"] for k in preview["items"]}
        position_rows = []
        for i, instance in enumerate(preview["layout"]["instances"], 1):
            selections = [f"{e['name']} / {e['model']} × {e['quantity']}" for e in preview.get("extras", []) if e.get("instanceId") == instance["id"]]
            geometry = preview["layoutKitMetadata"][instance["kitId"]]
            position_rows.append([i, instance["id"], instance["kitId"], names[instance["kitId"]], instance["xMm"], instance["yMm"],
                                  instance["rotationDeg"], "；".join(selections), str(geometry.get("status", "")), str(geometry.get("notes") or geometry.get("note") or "")])
        sheet_table(wb, "布局位置", "面包板布局位置（所属板左下角为原点；多板总装另见叠装器件位置）",
                    ["图中序号", "实例编号", "套件编号", "套件名称", "X / mm", "Y / mm", "方向 / °", "本实例补充选型", "俯视图状态", "说明"],
                    position_rows, [12, 30, 26, 36, 16, 16, 16, 60, 30, 60], generated_at)
        from breadboard import board_specs
        board_component=next((row for row in preview["manufacturing"] if row.get("generatedBoard")),None)
        if board_component is not None and not preview["layout"].get("subBoards"):
            spec = board_component.get("boardSpec",{}) if board_component else {}
            if not spec:spec = board_specs(board)
            board_process=manufacturing_spec(board_component or {"boardSpec":spec})
            sheet_table(wb, "面包板规格", f"参数面包板规格（本次生产 {board_component['quantity']} 块）", ["项目", "数值", "单位 / 说明"],
                        [["横向边长", board["widthMm"], "mm"], ["纵向边长", board["heightMm"], "mm"],
                         ["厚度", board["thicknessMm"], "mm"], ["孔距", board["pitchMm"], "mm"],
                         ["左 / 下首孔边距", board["edgeOffsetMm"], "mm"],
                         ["右侧余量", spec["rightMarginMm"], "mm"], ["上侧余量", spec["topMarginMm"], "mm"],
                         ["孔阵列", f'{spec["gridColumns"]} 列 × {spec["gridRows"]} 行', f'共 {spec["holeCount"]} 孔'],
                         ["普通孔型", spec["holeCallout"], f'{spec["regularHoleCount"]} 个；固定沉孔替换对应普通孔'],
                         ["固定孔数", spec["mountingHoleCount"], "启用后移动器件不能遮挡固定孔" if spec["mountingHoleCount"] else "未启用安装沉孔"],
                         ["固定沉孔规格", spec["counterboreCallout"] if spec["mountingHoleCount"] else "未启用", "顶面圆柱沉孔；不是锥形沉头孔"],
                         ["STEP 孔表达", board["holeDiameterMm"], "mm；M6 螺纹位置用 Ø5 底孔表示，无螺旋牙；按图纸标注加工" if board["holeType"] == "M6_through" else "mm；普通通孔"],
                         ["材料", board_process["material"], "按本次制造要求"], ["表面处理", board_process["surfaceTreatment"], "按本次制造要求"],
                         ["坐标", "左下角为原点；X向右、Y向上", "器件锚点坐标；逆时针为正方向"],
                         ["生产范围", f"参数面包板 {board_component['quantity']} 块；其余器件以生产清单为准", "生产包包含本次所选自制件 STEP 和三视图；没有修改原 Onshape 设计"]], [26, 60, 66], generated_at)
            if spec.get("mountingHoles"):
                sheet_table(wb,"面包板固定孔","四角 M6 圆柱沉孔位置（序号从左下角1开始）",
                            ["孔号","列号","行号","X / mm","Y / mm","通孔直径 / mm","沉孔直径 / mm","沉孔深度 / mm","说明"],
                            [[h["label"],h["columnIndex"]+1,h["rowIndex"]+1,h["xMm"],h["yMm"],
                              spec["counterbore"]["clearanceDiameterMm"],spec["counterbore"]["diameterMm"],spec["counterbore"]["depthMm"],
                              "顶面圆柱沉孔；各四孔组内坐标差为25 mm整数倍"] for h in spec["mountingHoles"]],
                            [12,12,12,18,18,22,22,22,66],generated_at)
    if preview.get("cartSources"):
        source_rows = [[index, source["name"], source.get("createdAt", ""), source["totals"]["kits"],
                        "含布局，原布局见资料包参考文件夹" if source.get("layout") else "原套件方案"]
                       for index, source in enumerate(preview["cartSources"], 1)]
        sheet_table(wb, "原方案参考", "购物车加入记录（仅供参考，非下单数量）", ["序号", "方案名称", "加入时间", "原套件数量", "参考资料"],
                    source_rows, [8, 48, 32, 16, 65], generated_at)
    if preview.get("cartSources") or preview.get("layout",{}).get("subBoards") or any(row.get('registeredBoard') for row in preview['manufacturing']):
        boards = [row for row in preview["manufacturing"] if row.get("generatedBoard") or row.get('registeredBoard')]
        if boards:
            sheet_table(wb, "面包板规格", "所选面包板与生产数量；登记板长宽为外形包围尺寸，按原 CAD 轮廓生产", ["组件编号", "名称", "数量", "宽 / mm", "高 / mm", "厚 / mm", "孔距 / mm", "普通孔型", "固定孔规格", "材料", "表面处理"],
                        [[row["componentId"], row["name"], row["quantity"], row["boardSpec"]["board"]["widthMm"],
                          row["boardSpec"]["board"]["heightMm"], row["boardSpec"]["board"]["thicknessMm"],
                          row["boardSpec"]["board"]["pitchMm"], row["boardSpec"]["holeCallout"],
                          row["boardSpec"]["counterboreCallout"] if row["boardSpec"]["mountingHoleCount"] else "未启用",
                          manufacturing_spec(row)["material"], manufacturing_spec(row)["surfaceTreatment"]] for row in boards],
                        [48, 45, 12, 15, 15, 15, 15, 34, 50, 28, 32], generated_at)
    # Installation coordinates are a reference for the saved assembly. Quantities
    # to manufacture are still taken only from the selected shopping-cart rows.
    contexts = preview.get("cartSources") or [{"name": "当前方案", **preview}]
    plate_rows, hole_rows, member_rows, axis_rows, elevation_rows, post_rows, table_rows, stage_rows = [], [], [], [], [], [], [], []
    from breadboard import board_specs
    from stacked_layout import aligned, transform_point, global_instance
    for context in contexts:
        assembly = context.get("layout", {})
        source_name = context.get("name", "当前方案")
        table = assembly.get("baseMode") == "table"
        root_name = "桌子／无大板" if table else "大面包板"
        if table:
            reference = assembly["board"]
            table_rows.append([source_name, reference["widthMm"], reference["heightMm"], reference["pitchMm"], reference["edgeOffsetMm"],
                               "仅作布局、坐标与光路参考；不加工根板。小板和自制件仍按所选生产清单加工。"])
        for axis in context.get("layoutValidation", {}).get("axisHeights", []):
            axis_rows.append([source_name, axis["instanceId"], axis["kitId"], axis.get("boardId") or root_name,
                              axis["opticalAxisHeightMm"], axis["boardElevationMm"], axis["boardThicknessMm"]+axis.get("stageHeightOffsetMm",0),
                              axis["elevationMm"], axis["elevationSupportCount"], axis["effectiveAxisHeightMm"],
                              "未实现" if axis.get("heightResolved") is False else "已实现" if axis["effectiveAxisHeightMm"] is not None else "未登记",
                              axis.get("requestedEffectiveAxisHeightMm"), axis.get("postHeightDeltaMm", 0)])
        for replacement in context.get("universalPostReplacements", []):
            post_rows.append([source_name, replacement["instanceId"], replacement["kitId"], replacement["originalComponentId"],
                              replacement["originalHeightMm"], replacement["replacementComponentId"], replacement["replacementHeightMm"],
                              replacement["elevationMm"], replacement["quantity"]])
        for support in context.get("elevationAccessories", []):
            if support.get("mode") == "universalPostReplacement":
                continue
            for material in support["materials"]:
                elevation_rows.append([source_name, support["targetType"], support["targetId"], support["name"],
                                       support["elevationMm"], support["supportCount"], material["name"], material["model"],
                                       material["heightMm"], material["quantityPerSupport"], material["quantity"], material["unit"]])
        if not assembly.get("subBoards"):
            continue
        parent = assembly["board"]
        plates = {p["id"]:p for p in assembly["subBoards"]}
        for plate in plates.values():
            from registered_boards import registered
            if plate.get('stageMotion'):
                report=next((r for r in context.get('layoutValidation',{}).get('stageModules',[]) if r['boardId']==plate['id']),None)
                if report is None:
                    raise APIError('stage_snapshot_missing','位移模块安装快照缺失，请重新加入购物车后导出。',409)
                mount=report['mountingAlignment']; pose=report['fixedPose']
                stage_rows.append([source_name,plate['id'],report['name'],report['moduleId'],report['revision'],report['qMm'],pose['xMm'],pose['yMm'],plate['rotationDeg'],plate['xMm'],plate['yMm'],report['totalHeightMm'],report['topSurfaceZMm'],report['centerGridAligned'],report['currentGridAligned'],report['alignmentStatus'],report['asBuiltAcceptance']])
                from elevation import support_count
                plate_rows.append([source_name,plate['id'],plate['name'],report['moduleId'],plate['xMm'],plate['yMm'],plate['rotationDeg'],mount['totalCount'],plate.get('elevationMm',0),mount['totalCount']])
                for hole in mount['holes']:
                    hole_rows.append([source_name,plate['name']+'（固定基座）',hole['label'],'','',hole['xMm'],hole['yMm'],hole['globalXMm'],hole['globalYMm'],'','','桌面参考' if table else '重合' if hole['aligned'] else '不重合'])
                continue
            b=plate['board']
            # Cart source coordinates are historical references. An unselected
            # old board must not be resolved through a newer geometry revision.
            snapshot=next((r.get('boardSpec') for r in context.get('manufacturing',[]) if r.get('registeredBoard') and r.get('registeredBoardId')==b.get('registeredBoardId') and r.get('registeredBoardRevision')==b.get('registeredBoardRevision')),None) if registered(b) else None
            if snapshot:
                chosen={h['holeId'] for h in b.get('mountingHoles',[])}
                mounts=[{**h,'holeId':h['id'],'label':h['id']} for h in snapshot['allHolesMm'] if h['id'] in chosen]
                spec={**snapshot,'board':b,'mountingHoles':mounts,'mountingHoleCount':len(mounts)}
            else:spec = board_specs(b)
            mounting = next((entry for entry in context.get("layoutValidation",{}).get("subBoardMountingAlignment",[]) if entry['boardId']==plate['id']),{})
            states = {h['id']:h for h in mounting.get('holes',[])}
            from elevation import support_count
            plate_rows.append([source_name,plate["id"],plate["name"],spec["componentId"],plate["xMm"],plate["yMm"],plate["rotationDeg"],spec["mountingHoleCount"],plate.get("elevationMm",0),support_count(plate,board=True)])
            for hole in spec["mountingHoles"]:
                x,y = transform_point(plate,(hole["xMm"],hole["yMm"]))
                hole_rows.append([source_name,plate["name"],hole["label"],hole.get("columnIndex",-1)+1 or '',hole.get("rowIndex",-1)+1 or '',hole["xMm"],hole["yMm"],x,y,
                                  '' if registered(parent) else round((x-parent["edgeOffsetMm"])/parent["pitchMm"])+1,'' if registered(parent) else round((y-parent["edgeOffsetMm"])/parent["pitchMm"])+1,
                                  ("可用固定孔" if states[hole['label']]['usable'] else "备用孔") if (registered(plate['board']) or spec['mountingHoleCount']==8) and hole['label'] in states else
                                  "桌面参考；无需对孔" if table else "重合" if aligned(parent,(x,y)) else "不重合"])
        for instance in assembly["instances"]:
            world = global_instance(instance,plates)
            member_rows.append([source_name,instance["id"],plates.get(instance.get("boardId"),{}).get("name",root_name),instance["xMm"],instance["yMm"],instance["rotationDeg"],world["xMm"],world["yMm"],world["rotationDeg"]])
    if stage_rows:
        sheet_table(wb,'位移模块安装参考','当前上板随行程移动；固定基座不动。中心配网及包围盒筛查不代表实装验收',
                    ['方案','板编号','模块','模块编号','版本','q / mm','固定基座 X / mm','固定基座 Y / mm','方向 / °','上板 X / mm','上板 Y / mm','叠层总高 / mm','板顶 Z / mm','中心态12.5网格','当前态12.5网格','定位状态','实装验收'],
                    stage_rows,[30,28,36,45,12,16,22,22,16,20,20,20,20,20,20,25,25],generated_at)
    if table_rows:
        sheet_table(wb,"桌面工作区参考","桌子／无大板（工作区参考，不计入生产数量）",["方案","宽 / mm","高 / mm","参考网格 / mm","参考首孔边距 / mm","生产范围"],table_rows,[36,20,20,24,28,94],generated_at)
    if plate_rows:
        sheet_table(wb,"小板安装位置","原方案安装参考：大板左下角为原点；小板位置为自身左下角的安装坐标，逆时针角度",["方案","小板编号","小板名称","生产组件编号","大板 X / mm","大板 Y / mm","旋转 / °","固定孔数","小板垫高 / mm","垫高支持点数"],plate_rows,[36,44,32,42,20,20,16,16,20,20],generated_at)
        sheet_table(wb,"小板固定孔","原方案固定孔对照：小板局部坐标与大板安装坐标；行列均从左下角1开始",["方案","小板","孔号","小板列号","小板行号","小板 X / mm","小板 Y / mm","大板 X / mm","大板 Y / mm","大板列号","大板行号","对齐"],hole_rows,[36,32,12,16,16,20,20,20,20,16,16,16],generated_at)
        sheet_table(wb,"叠装器件位置","原方案器件安装参考：板内坐标与总装坐标，逆时针角度",["方案","实例编号","所属面包板","板内 X / mm","板内 Y / mm","板内方向 / °","总装 X / mm","总装 Y / mm","总装方向 / °"],member_rows,[36,36,32,20,20,20,20,20,20],generated_at)
    if axis_rows:
        sheet_table(wb,"光轴高度","原方案光轴高度：工作区基准面为 0；基础柱高差、承载叠层（普通小板厚度或位移模块总高）与垫高累加",["方案","实例编号","套件编号","所属面包板","器件自身光轴 / mm","小板垫高 / mm","承载叠层高 / mm","器件增高 / mm","器件支持点数","有效光轴 / mm","高度状态","未实现目标 / mm","基础柱高差 / mm"],axis_rows,[36,36,26,32,25,24,24,24,24,24,24,18,24],generated_at)
    if elevation_rows:
        sheet_table(wb,"垫高材料","原方案额外垫高材料（仅供溯源，实际下单数量以所选清单为准）",["方案","对象类型","对象编号","对象名称","垫高 / mm","支持点数","材料名称","型号","单件高度 / mm","每点数量","原方案数量","单位"],elevation_rows,[36,18,36,36,20,18,42,28,22,18,18,12],generated_at)
    if post_rows:
        sheet_table(wb,"万能柱替换","根板器件万能柱一换一；原柱已扣除（原方案记录仅供溯源，下单数量以所选清单为准）",["方案","实例编号","套件编号","原柱编号","原柱总高 / mm","替换柱编号","替换柱总高 / mm","增加高度 / mm","原方案替换数量"],post_rows,[36,36,28,28,24,36,24,24,24],generated_at)
    if preview.get("reviewGroups"):
        review_rows=[]
        for group in preview["reviewGroups"]:
            for item in group["items"]:
                review_rows.append([group["title"],item["summary"],"；".join(item.get("componentNames",[])),item.get("details", ""),
                                    "完整生产包待补文件；采购和生产清单可下载" if "bundle" in item.get("blockedExports",[]) else "确认事项；不影响下载审核单"])
        sheet_table(wb, "待确认项目", "加工、采购与来源文件确认事项", ["类别", "事项", "涉及零件", "核对说明", "下载影响"],
                    review_rows, [18, 65, 65, 105, 52], generated_at)
    elif preview["warnings"]:
        sheet_table(wb, "待确认项目", "本次选型待确认项目", ["序号", "项目说明"],
                    [[i, warning] for i, warning in enumerate(preview["warnings"], 1)], [10, 110], generated_at)
    if preview.get("optionalNotes"):
        sheet_table(wb, "可选补充说明", "光学片与螺钉可稍后补充", ["序号", "说明"],
                    [[i, note] for i, note in enumerate(preview["optionalNotes"], 1)], [10, 110], generated_at)
    if checkout:
        for sheet in wb:
            cell_value(sheet["A3"], f"导出时间：{generated_at}　数量以清单确认后的勾选与调整为准；原方案和布局信息仅供参考。")
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def archive_segment(value):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:100].rstrip(' .') or '未命名'
    if re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.I):
        name = '_' + name
    return name


def readable_part_name(name):
    name = re.sub(r'\s*[·•]\s*公制(?:\s+[A-Z]\d+)?\s*$', '', name)
    return archive_segment(re.sub(r'^参数面包板\s*', '面包板 ', name))


def unique_archive_name(name, used):
    """Keep distinct files distinct on both case-sensitive and insensitive disks."""
    candidate, ordinal = name, 2
    while candidate.casefold() in used:
        candidate = f'{name} ({ordinal})'
        ordinal += 1
    used.add(candidate.casefold())
    return candidate


from registered_boards import catalog_operation


@catalog_operation
def export_result(preview, kind, asset_root, static_root=None, catalog=None):
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if kind in ("layout-json", "layout-svg"):
        from layout import layout_json, layout_svg
        if kind == "layout-json":
            return layout_json(preview), "application/json; charset=utf-8", "光路布局.json"
        return layout_svg(preview, static_root or Path(asset_root).parent / "static"), "image/svg+xml; charset=utf-8", "光路总俯视图.svg"
    if "checkout" in preview and not any(preview[category] for category in ("lubang", "manufacturing", "standard")):
        raise APIError("empty_checkout", "请至少勾选一项需要导出的器件。")
    if preview.get("layout") is not None and not preview.get("layoutValidation", {}).get("valid", False):
        validation = preview.get("layoutValidation", {})
        raise APIError("layout_invalid", "布局不可用：存在碰撞、接触、越界、安装孔或光轴高度问题。请先调整布局；仍可保存 JSON / SVG 草稿。", 409, validation)
    for source in preview.get("cartSources", []):
        if source.get("layout") is not None and not source.get("layoutValidation", {}).get("valid", False):
            raise APIError("layout_invalid", f"购物车方案“{source['name']}”的原布局存在定位或碰撞问题。", 409, source.get("layoutValidation"))
    if kind in ("lubang", "manufacturing"):
        name = "麓邦采购.xlsx" if kind == "lubang" else "生产清单.xlsx"
        return workbook_bytes(preview, kind, generated_at), XLSX_MIME, name
    if kind != "bundle":
        raise APIError("invalid_format", "format必须为lubang、manufacturing、bundle、layout-json或layout-svg。")
    files, asset_map, used_folders, total_bytes = {}, {}, set(), 0
    marking_files, marking_manifest, marking_folders, marking_map = [], [], set(), {}
    for row in preview["manufacturing"]:
        asset_map[row["componentId"]] = {}
        folder = None
        generated_files, registered_root = None, Path(asset_root).resolve()
        if row.get('boardSpec',{}).get('requiresCustomBoardManufacturing'):
            raise APIError('custom_board_drawing_required','自选沉孔位置已保存在工程中；请据此生成对应STEP和加工图后再下载生产包，当前基板文件仍为全螺纹孔。',409)
        if row.get('registeredBoard') and row.get('generatedBoard'):
            raise APIError('registered_board_no_generator','登记异形面包板不能使用矩形参数生成器，请重新加入当前板型。',409)
        if row.get("generatedLaserAdapter"):
            from cart import verified_adapter_row
            from laser_adapter_artifacts import ensure_adapter_artifacts
            spec = verified_adapter_row(row)
            cache_root = Path(os.environ.get("ZZLAB_LASER_ADAPTER_CACHE", str(Path(tempfile.gettempdir()) / "zzlab-optics-laser-adapters"))).resolve()
            generated_files = ensure_adapter_artifacts(spec, cache_root)
            if generated_files["componentId"] != row.get("sourceComponentId", row["componentId"]):
                raise APIError("adapter_asset_mismatch", "生成的激光器底板与当前规格不一致，请重试。", 409)
            registered_root = cache_root
        elif row.get("generatedBoard"):
            from breadboard import ensure_board_artifacts, BreadboardError
            cache_root = Path(os.environ.get("ZZLAB_BOARD_CACHE", str(Path(tempfile.gettempdir()) / "zzlab-optics-breadboards"))).resolve()
            try:
                board = row.get("boardSpec", {}).get("board") or preview["layout"]["board"]
                generated_files = ensure_board_artifacts(board, cache_root)
            except BreadboardError as exc:
                raise APIError(exc.code, str(exc), exc.status) from exc
            if generated_files["componentId"] != row.get("sourceComponentId", row["componentId"]):
                raise APIError("board_asset_mismatch", "生成的面包板与当前规格不一致，请重试。", 409)
            registered_root = cache_root
        asset_fields = [("stepPath", "STEP", "step"), ("drawingPath", "单件图纸", "drawing")]
        if generated_files is None and row.get("dxfPath"):
            asset_fields.append(("dxfPdfPath", "补充图纸 PDF", "drawingSupplement"))
        if row.get("generatedLaserAdapter"):
            asset_fields += [(None, "孔位规格", "holeSpec"), (None, "底板俯视图", "topView")]
        for field, label, map_key in asset_fields:
            registered_name = row.get(field) if field else None
            if generated_files is not None:
                try:
                    registered_name = str(Path(generated_files[map_key]).relative_to(registered_root))
                except ValueError as exc:
                    raise APIError("asset_forbidden", "生成文件不在专用 CAD 缓存目录中。", 409) from exc
            path = safe_asset(registered_root, registered_name, f"{row['name']}的{label}")
            allowed_suffixes = {"step": {".step", ".stp"}, "drawing": {".pdf"}, "drawingSupplement": {".pdf"}, "holeSpec": {".json"}, "topView": {".svg"}}
            if path.suffix.lower() not in allowed_suffixes[map_key]:
                raise APIError("asset_forbidden", "登记资产的文件类型不正确。", 409)
            # The same registered file is included only once even if two
            # component records intentionally reference the shared asset.
            if path not in files:
                if folder is None:
                    folder = unique_archive_name(readable_part_name(row['name']), used_folders)
                suffix = {'step': '', 'drawing': '_图纸', 'drawingSupplement': '_补充图纸',
                          'holeSpec': '_孔位', 'topView': '_俯视图'}[map_key]
                name = f"自制件/{folder}/{folder}{suffix}{path.suffix.lower()}"
                try:
                    size = path.stat().st_size
                    total_bytes += size
                    if total_bytes > MAX_ASSET_BYTES:
                        raise APIError("bundle_too_large", "本次生产包文件超过256MB，请分批导出。", 413)
                    data = path.read_bytes()
                except OSError as exc:
                    raise APIError("asset_missing", f"{row['name']}的{label}暂时无法读取。", 409) from exc
                if len(data) != size:
                    raise APIError("asset_changed", f"{row['name']}文件正在更新，请稍后重试。", 409)
                digest = hashlib.sha256(data).hexdigest()
                files[path] = {"name": name, "data": data, "sha256": digest}
            if map_key == "drawingSupplement" and row.get("dxfPdfSha256") and files[path]["sha256"] != row["dxfPdfSha256"]:
                raise APIError("asset_changed", f"{row['name']}的转换图纸校验失败，请重新核对登记文件。", 409)
            asset_map[row["componentId"]][map_key] = files[path]["name"]
        marking = laser_marking(row)
        marking_entry = {'componentId': row['componentId'], 'name': row['name'], 'status': marking['status'],
                         'quantity': row['quantity'] if marking['status'] == 'required' else 0 if marking['status'] == 'none' else None,
                         'reason': marking.get('reason', ''), 'notes': marking.get('notes', ''), 'files': [], 'missing': []}
        marking_folder = unique_archive_name(readable_part_name(row['name']), marking_folders)
        marking_faces = set()
        for face in marking.get('files', []):
            face_name = unique_archive_name(archive_segment(face['face']), marking_faces)
            item = {'face': face['face'], 'text': face.get('text', '')}
            for path_key, hash_key, suffix in (('dxfPath', 'sha256', '.dxf'), ('setupPdfPath', 'setupPdfSha256', '_定位说明.pdf')):
                if not face.get(path_key):
                    continue
                try:
                    path = safe_asset(asset_root, face[path_key], f"{row['name']}的{face['face']}激光打标资料")
                except APIError as exc:
                    if exc.code != 'asset_missing':
                        raise
                    marking_entry['missing'].append(f"{face['face']}：{path_key}文件待补")
                    continue
                expected_suffix = '.dxf' if path_key == 'dxfPath' else '.pdf'
                if path.suffix.lower() != expected_suffix:
                    raise APIError('asset_forbidden', '激光打标资料文件类型不正确。', 409)
                try:
                    size = path.stat().st_size
                    total_bytes += size
                    if total_bytes > MAX_ASSET_BYTES:
                        raise APIError('bundle_too_large', '本次生产包文件超过256MB，请分批导出。', 413)
                    data = path.read_bytes()
                except OSError as exc:
                    raise APIError('asset_missing', f"{row['name']}的激光打标资料暂时无法读取。", 409) from exc
                digest = hashlib.sha256(data).hexdigest()
                if len(data) != size or digest != face.get(hash_key):
                    raise APIError('asset_changed', f"{row['name']}的激光打标资料校验失败，请核对当前登记文件。", 409)
                name = f'激光打标/{marking_folder}/{face_name}{suffix}'
                marking_files.append({'name': name, 'data': data, 'sha256': digest})
                item[path_key], item[hash_key] = name, digest
            if item.get('dxfPath') or item.get('setupPdfPath'):
                marking_entry['files'].append(item)
        if marking['status'] == 'required' and not marking.get('files'):
            marking_entry['missing'].append('打标DXF待补')
        marking_map[row['componentId']] = {'laserMarking': marking_entry['files'], 'laserMarkingMissing': marking_entry['missing']}
        marking_manifest.append(marking_entry)
    # A catalog board module may carry its exact nominal source assembly.
    # Attach only when this specific board remains in the selected manufacturing
    # rows; a child kit or unchecked board cannot bypass checkout selection.
    board_assemblies=[]
    if catalog:
        for row in preview['manufacturing']:
            if not row.get('registeredBoard') or row.get('generatedBoard'):continue
            board=next((b for b in catalog.get('registeredBoards',[]) if b['id']==row.get('registeredBoardId') and b['revision']==row.get('registeredBoardRevision')),None)
            ref=(board or {}).get('assemblyReference')
            if not ref:continue
            token=hashlib.sha256(json.dumps([board['id'],board['revision']],separators=(',',':')).encode()).hexdigest()[:16]
            if row.get('sourceComponentId',row['componentId'])!='registered-board-'+token or any(row.get(k)!=board.get(k) for k in ('stepPath','drawingPath')):
                raise APIError('asset_changed','模块面包板来源已变化，请重新加入。',409)
            path=safe_asset(asset_root,ref.get('stepPath'),'模块名义总装')
            if path.suffix.lower() not in ('.step','.stp') or ref.get('sourceExact') is not True:
                raise APIError('asset_forbidden','模块总装来源登记不完整。',409)
            size=path.stat().st_size;total_bytes+=size
            if total_bytes>MAX_ASSET_BYTES:raise APIError('bundle_too_large','本次生产包文件超过256MB，请分批导出。',413)
            data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
            if len(data)!=size or digest!=ref.get('sourceStepSha256'):
                raise APIError('asset_changed','模块名义总装校验失败。',409)
            name='总装参考/'+archive_segment(board['id'])+path.suffix.lower()
            files[path]={'name':name,'data':data,'sha256':digest}
            board_assemblies.append({'boardId':board['id'],'revision':board['revision'],'path':name,'sha256':digest,'scope':'原包名义装配；不包含后续画布增删、移动或实际镜片选择；不另计制造数量。'})
    # Fast uploads carry a nominal full assembly as a reference attachment, not
    # another manufacturing row. Selection/checkout still controls production.
    fast_assemblies = []
    if catalog:
        by_kit = {k["id"]: k for k in catalog.get("kits", [])}
        selected_ids = {r.get("kitId") for r in preview.get("items", [])}
        for context in preview.get("cartSources", []):
            selected_ids.update(r.get("kitId") for r in context.get("items", []))
        selected_parts = {r.get("componentId") for r in preview["manufacturing"]}
        for kid in sorted(selected_ids - {None}):
            kit = by_kit.get(kid, {})
            if kit.get("fastUpload", {}).get("schema") != "zzlab-fast-kit-upload-v1":
                continue
            post_ids = {r["componentId"] for r in kit.get("components", [])
                        if r["componentId"].startswith("custom-rotpost-")}
            if not post_ids or not post_ids <= selected_parts:
                continue
            ref = kit.get("assemblyReference", {})
            path = safe_asset(asset_root, ref.get("stepPath"), "极速套件完整总装")
            if path.suffix.lower() not in (".step", ".stp") or not ref.get("sourceExact"):
                raise APIError("asset_forbidden", "极速套件总装来源登记不完整。", 409)
            size = path.stat().st_size
            total_bytes += size
            if total_bytes > MAX_ASSET_BYTES:
                raise APIError("bundle_too_large", "本次生产包文件超过256MB，请分批导出。", 413)
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if len(data) != size or digest != ref.get("sourceStepSha256"):
                raise APIError("asset_changed", "极速套件总装校验失败，请重新核对登记文件。", 409)
            name = "总装参考/" + archive_segment(kid) + path.suffix.lower()
            files[path] = {"name": name, "data": data, "sha256": digest}
            fast_assemblies.append({"kitId": kid, "path": name, "sha256": digest,
                "scope": "生成时名义固定姿态；不包含画布移动、后续换柱/选配或实物验收；不另计生产数量。",
                "atlasIncluded": False, "onshapeUploaded": False})
    # Reviewed nominal assemblies remain references, never manufacturing rows.
    # Explicit opt-in avoids exporting historic or unverified assembly records.
    reviewed_assemblies = []
    if catalog:
        by_part = {c["id"]: c for c in catalog.get("components", [])}
        selected_rows = {r["componentId"]: r for r in preview["manufacturing"]}
        for kid in sorted(selected_ids - {None}):
            kit = by_kit.get(kid, {})
            ref = kit.get("assemblyReference", {})
            if ref.get("includeInBundle") is not True:
                continue
            required = [by_part[r["componentId"]] for r in kit.get("components", [])
                        if by_part.get(r["componentId"], {}).get("kind") == "custom"
                        and by_part.get(r["componentId"], {}).get("stepPath")
                        and by_part.get(r["componentId"], {}).get("drawingPath")]
            # Unchecking or replacing a required custom part suppresses the
            # nominal assembly, whose fixed source pose would no longer apply.
            if not required or any(p["id"] not in selected_rows
                    or any(selected_rows[p["id"]].get(k) != p.get(k)
                           for k in ("stepPath", "drawingPath")) for p in required):
                continue
            if not (ref.get("sourceExact") is True
                    or ref.get("sourceDerivedByVerifiedSinglePartReplacement") is True):
                raise APIError("asset_forbidden", "套件总装来源登记不完整。", 409)
            attachment_rows = []
            for key, hash_key, suffixes, label in (
                ("stepPath", "sourceStepSha256", (".step", ".stp"), "完整总装"),
                ("drawingPath", "sourceDrawingSha256", (".pdf",), "装配说明"),
            ):
                path = safe_asset(asset_root, ref.get(key), label)
                if path.suffix.lower() not in suffixes:
                    raise APIError("asset_forbidden", "套件总装资料类型不正确。", 409)
                size = path.stat().st_size
                total_bytes += size
                if total_bytes > MAX_ASSET_BYTES:
                    raise APIError("bundle_too_large", "本次生产包文件超过256MB，请分批导出。", 413)
                data = path.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                if len(data) != size or digest != ref.get(hash_key):
                    raise APIError("asset_changed", "套件总装资料校验失败，请重新核对登记文件。", 409)
                name = "总装参考/" + archive_segment(kid) + "_" + label + path.suffix.lower()
                files[path] = {"name": name, "data": data, "sha256": digest}
                attachment_rows.append({"path": name, "sha256": digest})
            reviewed_assemblies.append({"kitId": kid, "files": attachment_rows,
                "scope": "原始名义姿态参考；不包含画布移动、换柱或镜片选配，不另计制造数量；未实物验收。"})
    config = {"catalogVersion": preview["catalogVersion"], "generatedAt": generated_at,
              "items": preview["items"], "extras": preview.get("extras", []),
              "opticalReplacements": preview.get("replacements", []), "elevationAccessories": preview.get("elevationAccessories", []),
              "universalPostReplacements": preview.get("universalPostReplacements", []),
              "scopeNote": preview.get("scopeNote"), "optionalNotes": preview.get("optionalNotes", []),
              "components": preview["lubang"]+preview["manufacturing"]+preview["standard"],
              "warnings": preview["warnings"], "reviewGroups": preview.get("reviewGroups", []), "totals": preview["totals"], "assets": asset_map,
              "laserMarking": marking_manifest,
              "fileChecksums": {f["name"]: f["sha256"] for f in [*files.values(), *marking_files]}}
    if board_assemblies:
        config['boardModuleAssemblies']=board_assemblies
    if fast_assemblies:
        config["fastKitAssemblies"] = fast_assemblies
    if reviewed_assemblies:
        config["reviewedKitAssemblies"] = reviewed_assemblies
    import_plan = lubang_import_plan(preview["lubang"])
    config["lubangImport"] = import_plan
    if preview.get("requires"):
        config["requires"] = preview["requires"]
    if "checkout" in preview:
        config["checkout"] = preview["checkout"]
    if "cartSources" in preview:
        config["cartSources"] = preview["cartSources"]
        config["catalogVersions"] = preview.get("catalogVersions", [])
    if preview.get("layout") is not None:
        config["layout"] = preview["layout"]
        config["layoutKitMetadata"] = preview["layoutKitMetadata"]
        config["layoutValidation"] = preview["layoutValidation"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("麓邦采购.xlsx", lubang_workbook_bytes(import_plan))
        if import_plan["blocked"]:
            archive.writestr("麓邦待确认清单.xlsx", lubang_pending_workbook_bytes(preview, import_plan, generated_at))
            instructions = ["麓邦购物车导入说明", "麓邦采购.xlsx 使用提供的官方模板，可到 https://www.lbtek.com/cart 选择文件导入。",
                            f"本次已写入 {len(import_plan['ready'])} 个清单项目；另有 {len(import_plan['blocked'])} 个项目未导入。",
                            "未导入项目完整列于麓邦待确认清单.xlsx，请确认产品型号后再采购；不要将该待确认清单当作导入表。",
                            "所有项目仍保留在套件配置.json 中，可按 lubangImport.ready / blocked 对账。", ""]
            instructions.extend(f"- {item['name']} / {item['model'] or '未填型号'} × {item['quantity']}：{item['reason']}" for item in import_plan["blocked"])
            archive.writestr("麓邦导入说明.txt", "\n".join(instructions).encode("utf-8"))
        archive.writestr("生产清单.xlsx", workbook_bytes(preview, "manufacturing", generated_at, marking_map))
        archive.writestr('生产清单.csv', manufacturing_csv_bytes(preview, marking_map))
        marking_notes = ['激光打标交付说明', '打标数量以本次所选生产清单为准；每个面DXF为独立文件，定位说明PDF用于摆放及定位。',
                         'required表示需要打标；none表示无需打标；review表示是否打标待核实。',
                         '文件齐备不代表制造工艺已批准。缺图的条目为待补资料，不能据此直接打标。', '']
        for entry in marking_manifest:
            marking_notes.append(f"{entry['name']}：{entry['status']}；打标数量 {entry['quantity'] if entry['quantity'] is not None else '待核实'}；" +
                                 '；'.join([entry['reason'], entry['notes'], *entry['missing']]).strip('；'))
        archive.writestr('激光打标/打标说明.txt', '\n'.join(marking_notes).encode('utf-8'))
        archive.writestr('激光打标/打标文件清单.json', json.dumps(marking_manifest, ensure_ascii=False, indent=2).encode('utf-8'))
        if preview["standard"]:
            archive.writestr("通用外购件.xlsx", workbook_bytes(preview, "standard", generated_at))
        archive.writestr("套件配置.json", json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8"))
        table_contexts = [source for source in (preview.get("cartSources") or [{"name": "当前方案", **preview}])
                          if source.get("layout", {}).get("baseMode") == "table"]
        if table_contexts:
            reference_notes = ["桌子／无大板：工作区与生产范围说明", "根工作区仅作布局、坐标和光路参考，不是待加工面包板，资料包不生成其 STEP 或图纸。",
                               "所有实际小面包板、垫板和其它自制件仍按所选生产清单加工；购物车中手动调整后的数量以生产清单为准。",
                               "桌面参考网格不代表存在安装螺纹孔；不据此要求小板固定孔或直接放置器件的孔位与桌面对齐。", ""]
            for source in table_contexts:
                board = source["layout"]["board"]
                reference_notes.append(f"{source.get('name', '当前方案')}：工作区 {board['widthMm']:g} × {board['heightMm']:g} mm；参考网格 {board['pitchMm']:g} mm。")
            archive.writestr("桌面工作区说明.txt", "\n".join(reference_notes).encode("utf-8"))
        if preview.get("layout") is not None:
            from layout import layout_json, layout_svg
            archive.writestr("光路布局.json", layout_json(preview))
            archive.writestr("光路总俯视图.svg", layout_svg(preview, static_root or Path(asset_root).parent / "static"))
        used_source_names = set()
        for source in preview.get("cartSources", []):
            if source.get("layout") is not None:
                from layout import layout_json, layout_svg
                folder = '原方案参考/' + unique_archive_name(archive_segment(source['name']), used_source_names)
                archive.writestr(folder + "/原布局.json", layout_json(source))
                archive.writestr(folder + "/原总俯视图.svg", layout_svg(source, static_root or Path(asset_root).parent / "static"))
        for item in [*files.values(), *marking_files]:
            archive.writestr(item["name"], item["data"])
    return buffer.getvalue(), "application/zip", "光路套件生产包.zip"
