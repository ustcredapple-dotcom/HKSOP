"""Authenticated, immutable laboratory layout snapshots and reversible publication.

Only project data are persisted. Catalog assets, manufacturing rules and BOMs are
always resolved by the server; none can be supplied by a published project.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import uuid
import zipfile
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bom import APIError, aggregate, validate_extras
from exports import export_result, safe_asset
from layout import footprint, validate_layout

FORMAT = "zzlab-optics-project"
MAX_PROJECT_BYTES = 8 * 1024 * 1024
MAX_SHARED_BODY = MAX_PROJECT_BYTES + 16384
MAX_SHARED_KITS = 1000
LIMITS = {"maxProjectBytes": MAX_PROJECT_BYTES, "maxInstances": 500,
          "maxNameLength": 120, "maxDescriptionLength": 2000, "maxSharedKits": MAX_SHARED_KITS}
DOWNLOAD_NOTICE = "工程保存发布时的完整快照；生产包按当前套件目录重新校验，只统计该面包板画布上的套件与补充项。"
FORBIDDEN_KEYS = {"__proto__", "prototype", "constructor"}


def invalid(message, code="invalid_project", status=400):
    raise APIError(code, message, status)


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result or key in FORBIDDEN_KEYS:
                invalid("JSON 含重复或不安全的字段。")
            result[key] = value
        return result

    def constant(_):
        invalid("工程不能含非有限数字。")

    try:
        result = json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
        safe_tree(result)
        return result
    except (ValueError, RecursionError) as exc:
        raise APIError("invalid_json", "请求不是有效的 JSON。") from exc


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def shape(value, allowed, required=(), label="工程"):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required).issubset(value):
        invalid(f"{label}包含缺失或未允许的字段。")
    return value


def text(value, label, maximum=256, required=False):
    if (not isinstance(value, str) or len(value) > maximum or
            any(ord(c) < 32 and c not in "\n\r\t" or ord(c) == 127 for c in value) or
            (required and not value.strip())):
        invalid(f"{label}为空、过长或含无效文字。")
    return value


def identifier(value, label):
    text(value, label, 80, True)
    if value.strip() != value or value in FORBIDDEN_KEYS:
        invalid(f"{label}无效。")
    return value


def number(value, label, minimum, maximum, integer=False):
    if (type(value) not in (int, float) or not math.isfinite(value) or
            not minimum <= value <= maximum or (integer and value != int(value))):
        invalid(f"{label}必须是范围内的{'整数' if integer else '有限数字'}。")
    return value


def sequence(value, label, limit=2000):
    if not isinstance(value, list) or len(value) > limit:
        invalid(f"{label}必须是最多 {limit} 项的数组。")
    return value


def safe_tree(value):
    count = 0
    def walk(item, depth):
        nonlocal count
        count += 1
        if count > 100000 or depth > 32:
            invalid("工程结构过于复杂。")
        if type(item) is str:
            if any(0xD800 <= ord(c) <= 0xDFFF for c in item):
                invalid("工程含无效 Unicode 文字。")
            return
        if item is None or type(item) is bool:
            return
        if type(item) in (int, float):
            if abs(item) > 1.7976931348623157e308 or not math.isfinite(item):
                invalid("工程不能含非有限数字。")
            return
        if isinstance(item, dict):
            if any(not isinstance(k, str) or k in FORBIDDEN_KEYS or any(0xD800 <= ord(c) <= 0xDFFF for c in k) for k in item):
                invalid("工程包含不安全字段。")
            for child in item.values():
                walk(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
        else:
            invalid("工程只能包含 JSON 数据。")
    walk(value, 0)


def _timestamp(value):
    text(value, "工程时间", 40, True)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})", value):
        invalid("工程时间格式无效。")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        invalid("工程时间格式无效。")


from registered_boards import catalog_operation


@catalog_operation
def project_payload(project, catalog):
    """Validate a complete v1 project, then convert only canvas selections to BOM input.

    Valid inactive/module configuration survives in the snapshot but cannot add
    unseen modules to the canvas order. Partial optical values also survive.
    """
    safe_tree(project)
    from manual_source_mount import upgrade_legacy_r3_project
    project, _ = upgrade_legacy_r3_project(project, catalog)
    from metric_migration import migrate
    project, _ = migrate(project, catalog)
    if len(json_bytes(project)) > MAX_PROJECT_BYTES:
        invalid("工程文件不能超过 8 MiB。", "request_too_large", 413)
    fields = {"format", "version", "metadata", "catalogVersion", "layout", "optical", "extras", "moduleQuantities", "ui", "catalogReferenced", "opticalRendering", "requires"}
    shape(project, fields, fields - {"catalogReferenced", "opticalRendering", "requires"})
    from moving_stages import validate_capabilities
    capabilities=validate_capabilities(project.get('requires',[]),project.get('layout'),catalog)
    if "opticalRendering" in project:
        prefs = shape(project["opticalRendering"], {"generated", "visible", "autoRestore"}, {"generated", "visible", "autoRestore"}, "光路恢复与显示偏好")
        if any(type(value) is not bool for value in prefs.values()):
            invalid("光路恢复与显示偏好必须为布尔值。")
    if project["format"] != FORMAT or type(project["version"]) is not int or project["version"] != 1:
        invalid("不支持此工程格式或版本。", "unsupported_project_version")
    meta = shape(project["metadata"], {"name", "notes", "createdAt", "updatedAt", "moduleElevation", "opticalAxisTargetMm"}, {"name", "notes", "createdAt", "updatedAt"}, "工程名称和备注")
    text(meta["name"], "工程名称", 160, True)
    text(meta["notes"], "工程备注", 20000)
    _timestamp(meta["createdAt"])
    _timestamp(meta["updatedAt"])
    if "opticalAxisTargetMm" in meta:
        h = meta["opticalAxisTargetMm"]
        if type(h) not in (int, float) or not 12.5 <= h <= 1000 or abs(h*10-round(h*10)) > 1e-8:
            invalid("整体光高需为12.5–1000 mm，精确到0.1 mm。")
    if "moduleElevation" in meta:
        from elevation import ELEVATION_FIELDS, normalize_fields
        shape(meta["moduleElevation"], ELEVATION_FIELDS, set(), "小板模块垫高设置")
        normalize_fields(meta["moduleElevation"])
    text(project["catalogVersion"], "目录版本", 128)
    kits = {k["id"]: k for k in catalog["kits"]}
    def kit(kid):
        identifier(kid, "套件编号")
        if kid not in kits:
            invalid("工程引用了当前目录未登记的套件。", "unknown_kit")
        return kits[kid]
    normalized, _, _ = validate_layout(project["layout"], kits)
    from elevation import universal_post_plan
    universal_post_plan(catalog, normalized, allow_elevation=False)
    instances = {i["id"]: i for i in normalized["instances"]}
    for iid in instances:
        identifier(iid, "实例编号")
        if "::" in iid or iid.startswith("module:"):
            invalid("实例编号与光学选配目标冲突。")
    selected = {i["kitId"] for i in instances.values()} | {p["stageMotion"]["moduleId"] for p in normalized.get("subBoards",[]) if p.get("stageMotion")}
    extras = sequence(project["extras"], "补充项")
    # Check even inactive configurations; filtering must never conceal bad references.
    for extra in extras:
        shape(extra, {"id", "kitId", "kind", "name", "model", "quantity", "unit", "notes", "instanceId", "slotId", "wavelength", "opticalType", "inserted", "supplier"}, {"id", "kitId", "kind", "name", "quantity", "unit"}, "补充项")
        identifier(extra["id"], "补充项编号")
        if extra["kitId"] is not None:
            kit(extra["kitId"])
        for field in ("model", "notes", "wavelength", "opticalType", "supplier"):
            if field in extra:
                text(extra[field], field, {"notes": 2000, "wavelength": 80}.get(field, 256))
    validated_extras = validate_extras(extras, dict.fromkeys(kits, 1), kits, instances, keep_unfilled=True)
    optical = project["optical"]
    if not isinstance(optical, dict) or len(optical) > 2000:
        invalid("光学选配必须是最多 2000 项的对象。")
    # Simulation-only earlier projects still describe installed physical optics.
    # Derive their pending purchase rows without modifying the saved project.
    # Explicit purchase entries and legacy extra rows always take precedence.
    optical = copy.deepcopy(optical)
    components = {c["id"]: c for c in catalog["components"]}
    for iid, instance in instances.items():
        config = instance.get("optics", {})
        if config.get("elementType") not in ("waveplate", "mirror", "pbs", "lens"):
            continue
        slots = kits[instance["kitId"]].get("opticalSlots", [])
        wave_slots = [s for s in slots if s["type"] == "waveplate"]
        for slot in slots:
            key = iid + "::" + slot["id"]
            if key in optical and optical[key] != {}:
                continue
            if any(e.get("slotId") == slot["id"] and e["kitId"] == instance["kitId"]
                   and (not e.get("instanceId") or e["instanceId"] == iid) for e in validated_extras):
                continue
            if config["elementType"] == "waveplate" and slot["type"] == "waveplate":
                index = wave_slots.index(slot)
                plates = config.get("waveplates")
                if plates is None:
                    inserted = index == 0 and config["inserted"]
                else:
                    inserted = index < len(plates) and plates[index]["inserted"]
            elif config["elementType"] in ("mirror", "pbs", "lens") and len(slots) == 1:
                inserted = config["inserted"]
            else:
                continue
            if not inserted and not config.get("configured"):
                continue
            original = components.get(slot.get("replacesComponentId"), {})
            optical[key] = {"inserted": inserted, "name": original.get("name") or slot["label"],
                            "model": original.get("model") or "", "kind": original.get("kind") or "standard",
                            "quantity": slot["quantity"], "unit": slot.get("unit") or "片",
                            "supplier": "麓邦" if original.get("kind") == "lubang" else ""}
    generated, all_optical = [], []
    for key, value in optical.items():
        text(key, "光学选配目标", 180, True)
        if "::" not in key:
            invalid("光学选配目标格式无效。")
        target, sid = key.rsplit("::", 1)
        iid = None
        if target.startswith("module:"):
            kid = target[7:]
            if kit(kid).get("layout", {}).get("placementAllowed") is not False:
                invalid("光学选配目标不是独立模块。")
        else:
            if target not in instances:
                invalid("光学选配引用了不存在的实例。", "unknown_instance")
            iid, kid = target, instances[target]["kitId"]
        identifier(sid, "光学槽编号")
        slot = next((s for s in kits[kid].get("opticalSlots", []) if s["id"] == sid), None)
        if slot is None:
            invalid("光学选配位置未登记。", "unknown_slot")
        shape(value, {"model", "wavelength", "opticalType", "kind", "name", "notes", "unit", "quantity", "inserted", "supplier"}, label="光学选配")
        for field, val in value.items():
            if field == "inserted":
                if type(val) is not bool:
                    invalid("光学片安装状态必须为布尔值。")
            elif field == "quantity":
                number(val, "选配数量", 1, 9999, True)
                if val != slot["quantity"]:
                    invalid("光学选配数量与目录不一致。")
            elif field == "kind":
                if val not in ("", "lubang", "standard"):
                    invalid("光学选配类型无效。")
            else:
                text(val, field, {"notes": 2000, "unit": 24, "wavelength": 80}.get(field, 256))
        if value.get("opticalType", "") not in ("", "half-wave", "quarter-wave") or (value.get("opticalType") and slot["type"] != "waveplate"):
            invalid("波片类型与光学槽不符。")
        model = value.get("model", "").strip()
        known = bool(model) and (any(o.get("model") == model for o in catalog.get("opticalOptions", []))
                                or any(c.get("kind") == "lubang" and c.get("model") == model for c in catalog.get("components", [])))
        row = {"id": "shared-optical-" + hashlib.sha256(key.encode()).hexdigest()[:40], "kitId": kid,
               "kind": "lubang" if known or value.get("kind") == "lubang" else "standard",
               "name": value.get("name", "").strip() or slot["label"], "model": model, "quantity": slot["quantity"], "unit": slot.get("unit") or "片",
               "notes": value.get("notes", ""), "slotId": sid, "wavelength": value.get("wavelength", ""), "opticalType": value.get("opticalType", "")}
        if "inserted" in value:
            row["inserted"] = value["inserted"]
        if "supplier" in value:
            row["supplier"] = value["supplier"]
        if iid:
            row["instanceId"] = iid
        all_optical.append(row)
        if iid and ("inserted" in value or any(value.get(k, "").strip() for k in ("model", "wavelength", "opticalType"))):
            generated.append(row)
    # Reject duplicate slot declarations even when a module or an empty optical
    # selection would otherwise be ignored by the canvas accounting.
    validate_extras(validated_extras + all_optical, dict.fromkeys(kits, 1), kits, instances, keep_unfilled=True)
    module_ids = set()
    for pair in sequence(project["moduleQuantities"], "独立模块数量"):
        if not isinstance(pair, list) or len(pair) != 2:
            invalid("独立模块数量必须为 [套件编号, 数量]。")
        kid, quantity = pair
        if kit(kid).get("layout", {}).get("placementAllowed") is not False or kid in module_ids:
            invalid("独立模块数量引用无效或重复。")
        number(quantity, "独立模块数量", 1, 9999, True)
        module_ids.add(kid)
    ui = shape(project["ui"], {"mountingSelection", "view", "selectedIds"}, label="页面状态")
    if "mountingSelection" in ui:
        mount = shape(ui["mountingSelection"], {"rowParity", "columnParity"}, {"rowParity", "columnParity"}, "安装孔行列选择")
        if any(v not in ("any", "odd", "even") for v in mount.values()):
            invalid("安装孔行列选择无效。")
    if ui.get("view") is not None:
        view = shape(ui["view"], {"x", "y", "w", "h"}, {"x", "y", "w", "h"}, "视窗")
        for field, val in view.items():
            number(val, "视窗", 0.001 if field in ("w", "h") else -1e7, 1e7)
    selected_ids = sequence(ui.get("selectedIds", []), "选中实例", 500)
    if any(not isinstance(iid, str) or iid not in instances for iid in selected_ids) or len(set(selected_ids)) != len(selected_ids):
        invalid("选中状态引用了不存在或重复的实例。")
    for ref in sequence(project.get("catalogReferenced", []), "目录引用"):
        shape(ref, {"id", "name"}, {"id", "name"}, "目录引用")
        kit(ref["id"])
        text(ref["name"], "目录名称", 256, True)
    active_extras = [e for e in extras if e.get("instanceId") in instances or not e.get("instanceId") and (e["kitId"] is None or e["kitId"] in selected)]
    return {"catalogVersion": catalog["version"], "layout": normalized, "extras": copy.deepcopy(active_extras) + generated, **({"requires":capabilities} if capabilities else {})}


def prepare_project(project, catalog):
    payload = project_payload(project, catalog)
    if not payload["layout"]["instances"] and not any(p.get("stageMotion") for p in payload["layout"].get("subBoards", [])):
        invalid("共享固定套件需要在面包板上放置至少一个套件。", "empty_shared_layout")
    preview = aggregate(catalog, payload, require_items=True)
    if not preview["layoutValidation"]["valid"]:
        invalid("布局仍有碰撞、底座越界或安装孔问题，请修正后再共享。", "invalid_shared_layout", 409)
    return preview


@catalog_operation
def thumbnail_svg(preview, static_root, catalog=None):
    """Only server-registered assets, once per kit, in a bounded portable SVG."""
    if preview.get('layout',{}).get('subBoards') or preview.get('layout',{}).get('baseMode') == 'table' or preview.get('layoutValidation',{}).get('laserAdapters'):
        from layout import layout_svg
        return layout_svg(preview, static_root)
    board, instances = preview["layout"]["board"], preview["layout"]["instances"]
    width, height = board["widthMm"], board["heightMm"]
    bounds = [footprint(i, preview["layoutKitMetadata"][i["kitId"]], "imageBoundsMm") for i in instances]
    left, right = min([0] + [b["left"] for b in bounds]), max([width] + [b["right"] for b in bounds])
    bottom, top = min([0] + [b["top"] for b in bounds]), max([height] + [b["bottom"] for b in bounds])
    content = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="{left-8:g} {height-top-8:g} {right-left+16:g} {top-bottom+16:g}">',
               '<title>ZZLab 共享固定套件 · 发布时俯视图</title>', '<defs>']
    assets, total = {}, 0
    for instance in instances:
        kid = instance["kitId"]
        if kid in assets:
            continue
        g = preview["layoutKitMetadata"][kid]
        asset = safe_asset(static_root, g["topViewPath"], "共享套件俯视图")
        total += asset.stat().st_size
        if total > 16 * 1024 * 1024:
            invalid("共享预览资源过大。", "thumbnail_too_large", 413)
        mime = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp"}.get(asset.suffix.lower())
        if not mime:
            invalid("共享俯视图格式未登记。")
        assets[kid] = f"kit{len(assets)}"
        encoded = base64.b64encode(asset.read_bytes()).decode("ascii")
        content.append(f'<image id="{assets[kid]}" x="{-g["anchorXMm"]:g}" y="{-g["anchorYMm"]:g}" width="{g["widthMm"]:g}" height="{g["heightMm"]:g}" preserveAspectRatio="none" xlink:href="data:{mime};base64,{encoded}"/>')
    content += ['</defs>', f'<rect width="{width:g}" height="{height:g}" rx="2" fill="#e8ece9" stroke="#55716a" stroke-width="0.6"/>']
    for i in instances:
        name = html.escape(preview["layoutKitMetadata"][i["kitId"]].get("name", i["kitId"]))
        content.append(f'<g transform="translate({i["xMm"]:g} {height-i["yMm"]:g}) rotate({-i["rotationDeg"]})"><title>{name}</title><use xlink:href="#{assets[i["kitId"]]}"/></g>')
    content.append('</svg>')
    return "\n".join(content).encode("utf-8")


@dataclass(frozen=True)
class Identity:
    id: str | None
    name: str
    role: str

    def require_id(self):
        if not self.id:
            invalid("账号身份资料不完整，请重新登录后再共享。", "identity_required", 403)


class SharedKitStore:
    def __init__(self, path, backup_path=None):
        self.path = Path(path)
        self.backup_path = Path(backup_path) if backup_path else None
        self._ready = False
        self._init_lock = threading.Lock()
        self._backup_lock = threading.Lock()

    @contextmanager
    def connect(self):
        with self._init_lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
                    db.execute("PRAGMA journal_mode=WAL")
                    db.execute("""CREATE TABLE IF NOT EXISTS shared_kits (
                        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                        author_id TEXT NOT NULL, author_name TEXT NOT NULL, created_at TEXT NOT NULL,
                        catalog_version TEXT NOT NULL, project_json BLOB NOT NULL, thumbnail_svg BLOB NOT NULL,
                        instance_count INTEGER NOT NULL, width REAL NOT NULL, height REAL NOT NULL,
                        active INTEGER NOT NULL DEFAULT 1, changed_at TEXT NOT NULL)""")
                    db.execute("CREATE INDEX IF NOT EXISTS shared_visibility ON shared_kits(active, created_at)")
                    db.execute("""CREATE TABLE IF NOT EXISTS shared_actions (
                        id INTEGER PRIMARY KEY, kit_id TEXT NOT NULL, action TEXT NOT NULL,
                        actor_id TEXT NOT NULL, created_at TEXT NOT NULL)""")
                self._ready = True
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def managed(row, identity):
        return bool(identity.id and (identity.role == "admin" or row["author_id"] == identity.id))

    def summary(self, row, identity):
        active = bool(row["active"])
        allowed = self.managed(row, identity)
        return {"id": row["id"], "name": row["name"], "description": row["description"],
                "author": {"name": row["author_name"]}, "createdAt": row["created_at"],
                "instanceCount": row["instance_count"], "board": {"widthMm": row["width"], "heightMm": row["height"]},
                "catalogVersion": row["catalog_version"], "status": "published" if active else "unpublished",
                "canUnpublish": active and allowed, "canRestore": not active and allowed}

    def listing(self, identity):
        with self.connect() as db:
            rows = db.execute("SELECT id,name,description,author_id,author_name,created_at,catalog_version,instance_count,width,height,active FROM shared_kits WHERE active=1 OR author_id=? OR ? ORDER BY created_at DESC, id DESC",
                              (identity.id, bool(identity.id and identity.role == "admin"))).fetchall()
        return {"kits": [self.summary(r, identity) for r in rows if r["active"]],
                "withdrawn": [self.summary(r, identity) for r in rows if not r["active"] and self.managed(r, identity)],
                "limits": LIMITS, "downloadNotice": DOWNLOAD_NOTICE}

    def get(self, kit_id, identity):
        if not re.fullmatch(r"[a-f0-9]{32}", kit_id):
            invalid("共享套件不存在。", "not_found", 404)
        with self.connect() as db:
            row = db.execute("SELECT * FROM shared_kits WHERE id=?", (kit_id,)).fetchone()
        if row is None or not row["active"] and not self.managed(row, identity):
            invalid("共享套件不存在或已撤下。", "not_found", 404)
        return row

    def publish(self, name, description, project, thumbnail, identity):
        identity.require_id()
        name = text(name, "共享套件名称", 120, True).strip()
        description = text(description, "共享说明", 2000).strip()
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        kit_id = uuid.uuid4().hex
        board = project["layout"]["board"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM shared_kits").fetchone()[0] >= MAX_SHARED_KITS:
                invalid("共享库已达到容量上限，请联系管理员。", "shared_library_full", 409)
            db.execute("INSERT INTO shared_kits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                kit_id, name, description, identity.id, identity.name, now, project["catalogVersion"],
                json_bytes(project), thumbnail, len(project["layout"]["instances"]), board["widthMm"], board["heightMm"], 1, now))
            db.execute("INSERT INTO shared_actions(kit_id,action,actor_id,created_at) VALUES (?,?,?,?)", (kit_id, "publish", identity.id, now))
        return {"kit": self.summary(self.get(kit_id, identity), identity), "backup": self.backup()}

    def change_visibility(self, kit_id, identity, active):
        identity.require_id()
        row = self.get(kit_id, identity)
        if not self.managed(row, identity):
            invalid("只有发布者或管理员可以撤下或恢复此套件。", "forbidden", 403)
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE shared_kits SET active=?, changed_at=? WHERE id=?", (int(active), now, kit_id))
            db.execute("INSERT INTO shared_actions(kit_id,action,actor_id,created_at) VALUES (?,?,?,?)", (kit_id, "restore" if active else "unpublish", identity.id, now))
        return {"kit": self.summary(self.get(kit_id, identity), identity), "backup": self.backup()}

    def backup(self):
        if self.backup_path is None:
            return {"status": "not_configured"}
        target = self.backup_path
        temporary = None
        try:
            with self._backup_lock:
                if not target.parent.is_dir() or target.resolve() == self.path.resolve():
                    raise OSError("backup parent unavailable")
                parts = target.absolute().parts
                if len(parts) > 2 and parts[1] == "Volumes" and not Path(*parts[:3]).is_mount():
                    raise OSError("NAS is not mounted")
                # SQLite journal/locking operations are unreliable on SMB. Make
                # a coherent, standalone snapshot locally and close both DBs
                # before transferring ordinary bytes to the mounted NAS.
                with tempfile.TemporaryDirectory(prefix="shared-kits-snapshot-") as local_dir:
                    snapshot = Path(local_dir) / "snapshot.sqlite3"
                    with self.connect() as source:
                        with closing(sqlite3.connect(snapshot)) as destination, destination:
                            source.backup(destination)
                            destination.execute("PRAGMA journal_mode=DELETE")
                    fd, name = tempfile.mkstemp(prefix=".shared-kits-", suffix=".sqlite3", dir=target.parent)
                    temporary = Path(name)
                    with os.fdopen(fd, "wb") as output, snapshot.open("rb") as incoming:
                        shutil.copyfileobj(incoming, output, length=1024 * 1024)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, target)
                    temporary = None
            return {"status": "ok"}
        except (OSError, sqlite3.Error):
            return {"status": "warning", "message": "已保存服务器，NAS 备份暂未完成。"}
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


def shared_bundle(row, catalog, assets, static):
    project = strict_json(row["project_json"])
    preview = prepare_project(project, catalog)
    content, mime, _ = export_result(preview, "bundle", assets, static, catalog=catalog)
    output = io.BytesIO(content)
    with zipfile.ZipFile(output, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("共享套件工程.zzoptics.json", row["project_json"])
        archive.writestr("共享套件说明.txt", "\n".join((row["name"], DOWNLOAD_NOTICE,
                         f"发布时工程目录：{project['catalogVersion']}", f"本次生产目录：{catalog['version']}", row["description"])).encode("utf-8"))
    return output.getvalue(), mime, "共享套件生产包.zip"
