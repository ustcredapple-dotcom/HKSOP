"""Account-private, persistent shopping carts composed of immutable BOM snapshots."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import unicodedata
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

from bom import APIError, MAX_COMPONENT_QUANTITY, aggregate, build_review_groups, integer, known_model, lubang_import_plan, laser_marking, registered_board_laser_marking
from shared_kits import json_bytes, shape, text

MAX_CART_BYTES = 8 * 1024 * 1024
MAX_SOURCES = 100
MAX_ROWS = 2000
MAX_REVISION = 2**53 - 2
LIMITS = {"maxSources": MAX_SOURCES, "maxRows": MAX_ROWS, "maxBytes": MAX_CART_BYTES}
CATEGORIES = ("lubang", "manufacturing", "standard")


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def rows(preview):
    return [row for category in CATEGORIES for row in preview[category]]


def row_identity(row, source_id):
    """Known SKUs share an order line; unknown manual extras stay source-specific."""
    if row.get("generatedLaserAdapter"):
        spec = verified_adapter_row(row)
        key = ["laser-adapter", spec["digest"]]
    elif row.get("generatedBoard"):
        key = ["board", row["componentId"]]
    elif row["kind"] == "custom":
        key = ["custom", row["componentId"], row["model"], row.get("stepPath"), row.get("drawingPath"), row.get("manufacturingSpec")]
        if row.get("dxfPath"):
            key.append(row["dxfPath"])
    elif known_model(row["model"]):
        key = [row["kind"], unicodedata.normalize("NFKC", row["model"]).strip().casefold(), row["unit"].strip()]
        if row["kind"] == "standard" and row.get("supplier"):
            key.append(unicodedata.normalize("NFKC", row["supplier"]).strip().casefold())
    elif row["componentId"].startswith("extra:"):
        key = ["unknown-extra", source_id, row["componentId"]]
    else:
        key = ["unknown-catalog", row["kind"], row["componentId"], row["unit"]]
    return "cart:" + hashlib.sha256(canonical(key).encode()).hexdigest()[:40]


def verified_adapter_row(row):
    """Stored snapshots retain parameters, never an arbitrary generated path."""
    from laser_adapter import validate_adapter_spec
    spec = validate_adapter_spec(row.get("adapterSpec"))
    if (row.get("generatedLaserAdapter") is not True or row.get("generatedBoard") or
            row.get("kind") != "custom" or row.get("stepPath") or row.get("drawingPath") or row.get("dxfPath") or
            row.get("sourceComponentId", row.get("componentId")) != spec["componentId"] or
            row.get("model") != spec["model"]):
        raise APIError("adapter_asset_mismatch", "激光器底板快照与登记规格不一致，请重新加入购物车。", 409)
    return spec


def combine(state):
    merged, items, source_map = OrderedDict(), OrderedDict(), {}
    optional, requirements, versions = [], [], []
    for source in state["sources"]:
        preview = source["preview"]
        versions.append(preview["catalogVersion"])
        for item in preview["items"]:
            if item["kitId"] not in items:
                items[item["kitId"]] = {**item, "quantity": 0}
            items[item["kitId"]]["quantity"] += item["quantity"]
        optional.extend(f"{source['name']}：{note}" for note in preview.get("optionalNotes", []))
        requirements.extend(preview.get("pendingRequirements", []))
        for original in rows(preview):
            cid = row_identity(original, source["id"])
            for oid in original.get("componentIds", [original["componentId"]]):
                source_map[(source["id"], oid)] = cid
            if cid not in merged:
                merged[cid] = {**copy.deepcopy(original), "componentId": cid, "componentIds": [cid],
                               "sourceComponentId": original["componentId"], "baseQuantity": 0,
                               "quantity": 0, "kits": [], "cartSourceContributions": []}
            row = merged[cid]
            if original["kind"] == "lubang":
                blocked = lubang_import_plan([original])["blocked"]
                if blocked:
                    row["lubangImportReasons"] = list(dict.fromkeys(row.get("lubangImportReasons", []) + [blocked[0]["reason"]]))
            row["baseQuantity"] = integer(row["baseQuantity"] + original["quantity"], "购物车同一器件原始合计数量", MAX_COMPONENT_QUANTITY)
            row["kits"].extend({**copy.deepcopy(kit), "name": f"{source['name']} / {kit['name']}", "sourceId": source["id"]} for kit in original["kits"])
            row["cartSourceContributions"].append({"sourceId": source["id"], "sourceName": source["name"],
                                                   "componentId": original["componentId"], "quantity": original["quantity"]})
    result = {"catalogVersion": versions[-1] if versions else "", "catalogVersions": list(dict.fromkeys(versions)),
              "items": list(items.values()), "extras": [], "replacements": [],
              "lubang": [], "manufacturing": [], "standard": [], "pendingRequirements": requirements,
              "optionalNotes": list(dict.fromkeys(optional)),
              "scopeNote": "购物车独立保存各次加入的方案快照；导出仅包含勾选项目和当前数量。原方案和布局用于参考，不代表最终下单数量。",
              "cartSources": [{"id": source["id"], "name": source["name"], "createdAt": source["createdAt"],
                               **copy.deepcopy(source["preview"])} for source in state["sources"]]}
    for row in merged.values():
        row["quantity"] = state["choices"].get(row["componentId"], {}).get("quantity", row["baseQuantity"])
        result[{"lubang": "lubang", "custom": "manufacturing", "standard": "standard"}[row["kind"]]].append(row)
    result["totals"] = {"kits": sum(item["quantity"] for item in items.values()), "componentTypes": len(merged),
                        "componentQuantity": sum(row["quantity"] for row in merged.values()),
                        "boards": sum(row["quantity"] for row in merged.values() if row.get("generatedBoard") or row.get('registeredBoard') or row.get('stageTopPlate'))}
    result["reviewGroups"] = cart_reviews(state["sources"], source_map, set(merged))
    result["warnings"] = [group["summary"] for group in result["reviewGroups"]]
    result["lubangImport"] = lubang_import_plan(result["lubang"])
    return result, source_map


def cart_reviews(sources, source_map, selected):
    grouped = OrderedDict()
    for source in sources:
        active = any(cid in selected for (sid, _), cid in source_map.items() if sid == source["id"])
        if not active:
            continue
        for group in source["preview"].get("reviewGroups", []):
            for item in group["items"]:
                originals = item.get("componentIds", [])
                ids = list(dict.fromkeys(source_map.get((source["id"], cid)) for cid in originals))
                ids = [cid for cid in ids if cid in selected]
                if originals and not ids:
                    continue
                if group["id"] not in grouped:
                    grouped[group["id"]] = {"id": group["id"], "title": group["title"], "items": []}
                entry = copy.deepcopy(item)
                if originals and any(source_map.get((source["id"], cid)) not in selected for cid in originals):
                    # Grouped material/file reviews contain original counts and
                    # names. Rebuild a partial group rather than only hiding IDs.
                    review_rows = []
                    for row in rows(source["preview"]):
                        cid = source_map.get((source["id"], row["componentId"]))
                        if cid in ids:
                            review_rows.append({**row, "componentId": cid})
                    matches = [candidate for rebuilt in build_review_groups(review_rows) for candidate in rebuilt["items"] if candidate["code"] == item["code"]]
                    if not matches:
                        continue
                    entry = matches[0]
                entry.update(componentIds=ids, sourceId=source["id"], sourceName=source["name"])
                entry["summary"] = f"{source['name']}：{entry['summary']}"
                grouped[group["id"]]["items"].append(entry)
    for group in grouped.values():
        group["blocking"] = any(item.get("blocking") for item in group["items"])
        group["blockedExports"] = ["bundle"] if group["blocking"] else []
        group["summary"] = f"{group['title']}：{len(group['items'])} 项信息需要核对。"
    return list(grouped.values())


def current_source_specs(preview, catalog):
    """Apply an owner-authorized in-place source revision to a derived cart view.

    Row identities, quantities, selections and stored snapshots stay untouched.
    Exact registered paths must still match; this never admits arbitrary assets.
    """
    registered = {c["id"]: c for c in (catalog or {}).get("components", [])}
    retired = (catalog or {}).get('universalPostSeries', {}).get('metricMigration', {}).get('retiredComponents', {})
    for row in preview.get("manufacturing", []):
        source_id = row.get("sourceComponentId", row.get("componentId"))
        previous = retired.get(source_id)
        if previous:
            current = registered.get(previous.get('replacementComponentId'))
            # Retired source files are gone. Exact legacy path identity is only
            # a guard for resolving to the authorized current metric product.
            if (current and current.get('kind') == row.get('kind') == 'custom'
                    and not any(row.get(key) != previous.get(key) for key in ('stepPath', 'drawingPath', 'dxfPath'))):
                row['retiredSourceComponentId'] = source_id
                row['sourceComponentId'] = current['id']
                for key in ('stepPath', 'drawingPath', 'dxfPath', 'name', 'model', 'status', 'notes', 'sourceUrl', 'manufacturingSpec'):
                    row[key] = copy.deepcopy(current.get(key))
            continue
        current = registered.get(source_id)
        if not current or current.get("replaceSourceInExistingCarts") is not True:
            continue
        if current.get("kind") != "custom" or row.get("kind") != "custom":
            continue
        if any(row.get(key) != current.get(key) for key in ("stepPath", "drawingPath", "dxfPath")):
            continue
        for key in ("name", "model", "status", "notes", "sourceUrl", "manufacturingSpec"):
            row[key] = copy.deepcopy(current.get(key))
    for source in preview.get("cartSources", []):
        current_source_specs(source, catalog)
    return preview


def export_preview(state, catalog):
    preview, source_map = combine(state)
    current_source_specs(preview, catalog)
    choices = state["choices"]
    selected = {cid for cid, choice in choices.items() if choice["selected"] and not choice["removed"]}
    if not selected:
        raise APIError("empty_checkout", "请至少勾选一项需要导出的器件。")
    for category in CATEGORIES:
        preview[category] = [row for row in preview[category] if row["componentId"] in selected]
    chosen = rows(preview)
    # Snapshots cannot become an arbitrary historical-path download mechanism.
    registered = {component["id"]: component for component in catalog["components"]}
    for row in preview["manufacturing"]:
        if row.get('registeredBoard'):
            from registered_boards import definition, RegisteredBoardError, board_token, custom_mounting
            try:current=definition({'registeredBoardId':row.get('registeredBoardId'),'registeredBoardRevision':row.get('registeredBoardRevision')},catalog)
            except RegisteredBoardError as exc:raise APIError('cart_source_changed',str(exc),409) from exc
            selected=[h['holeId'] for h in row.get('boardSpec',{}).get('board',{}).get('mountingHoles',[])]
            expected='registered-board-'+board_token(current,selected)
            if custom_mounting(current) and selected:row.setdefault('boardSpec',{})['requiresCustomBoardManufacturing']=True
            if row.get('generatedBoard') or row.get('sourceComponentId')!=expected or any(current.get(field)!=row.get(field) for field in ('stepPath','drawingPath','dxfPath')):
                raise APIError('cart_source_changed',f'{row["name"]}的登记板型或制造文件已更新，请从当前元件库重新加入。',409)
            row['laserMarking'] = registered_board_laser_marking(row, catalog)
            continue
        if row.get("generatedLaserAdapter"):
            row["adapterSpec"] = verified_adapter_row(row)
            row['laserMarking'] = laser_marking({})
            continue
        if row.get("generatedBoard"):
            row['laserMarking'] = laser_marking({})
            continue
        current = registered.get(row["sourceComponentId"])
        if current is None or current["kind"] != "custom" or any(current.get(field) != row.get(field) for field in ("stepPath", "drawingPath")):
            raise APIError("cart_source_changed", f"{row['name']}的登记模型或图纸已更新，请从当前套件重新加入该器件。", 409)
        if row.get("dxfPath") and row["dxfPath"] != current.get("dxfPath"):
            raise APIError("cart_source_changed", f"{row['name']}的登记DXF已更新，请从当前套件重新加入该器件。", 409)
        # Optional DXFs added later are taken only from the current catalog,
        # after the snapshot's STEP and PDF have passed identity checks.
        row["dxfPath"] = current.get("dxfPath")
        # Presentation format changes do not rewrite or re-identify saved cart rows.
        # Resolve only after the original STEP/PDF/DXF paths pass the guards above.
        row["dxfPdfPath"] = current.get("dxfPdfPath")
        row["dxfPdfSha256"] = current.get("dxfPdfSha256")
        row['laserMarking'] = laser_marking(current)
    active_sources = {part["sourceId"] for row in chosen for part in row["cartSourceContributions"]}
    preview["cartSources"] = [source for source in preview["cartSources"] if source["id"] in active_sources]
    preview["checkout"] = {"items": [{"componentId": row["componentId"], "quantity": row["quantity"]} for row in chosen]}
    preview["reviewGroups"] = cart_reviews(state["sources"], source_map, selected)
    preview["warnings"] = [group["summary"] for group in preview["reviewGroups"]]
    preview["totals"].update(componentTypes=len(chosen), componentQuantity=sum(row["quantity"] for row in chosen),
                             boards=sum(row["quantity"] for row in chosen if row.get("generatedBoard") or row.get('registeredBoard') or row.get('stageTopPlate')))
    preview["lubangImport"] = lubang_import_plan(preview["lubang"])
    return preview


def current_marking_view(preview, catalog):
    """Read-only cart presentation: never rewrite stored rows or row identity."""
    registered = {component['id']: component for component in (catalog or {}).get('components', [])}
    for row in preview.get('manufacturing', []):
        if row.get('registeredBoard'):
            row['laserMarking'] = registered_board_laser_marking(row, catalog)
            continue
        if row.get('generatedBoard') or row.get('generatedLaserAdapter'):
            row['laserMarking'] = laser_marking({})
            continue
        current = registered.get(row.get('sourceComponentId', row['componentId']))
        if (current and current.get('kind') == row.get('kind') == 'custom'
                and current.get('model') == row.get('model')
                and all(row.get(field) == current.get(field) for field in ('stepPath', 'drawingPath'))
                and (not row.get('dxfPath') or row.get('dxfPath') == current.get('dxfPath'))):
            row['laserMarking'] = laser_marking(current)
        elif not row.get('generatedBoard') and not row.get('generatedLaserAdapter'):
            # A mismatched snapshot cannot advertise newer marking assets.
            row['laserMarking'] = laser_marking({})
    return preview


class CartStore:
    def __init__(self, store, catalog=None):
        self.store = store
        self.catalog = catalog

    @staticmethod
    def require_identity(identity):
        if identity.role not in ("user", "admin", "readonly") or not identity.id:
            raise APIError("cart_identity_required", "请登录具有完整账号身份的账户后使用购物车。", 403)

    @staticmethod
    def schema(db):
        db.execute("""CREATE TABLE IF NOT EXISTS optics_carts (
            account_id TEXT PRIMARY KEY, cart_id TEXT UNIQUE NOT NULL,
            revision INTEGER NOT NULL, updated_at TEXT, state_json BLOB NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS optics_cart_receipts (
            account_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            PRIMARY KEY(account_id,request_id))""")

    def read_record(self, db, identity):
        self.schema(db)
        row = db.execute("SELECT * FROM optics_carts WHERE account_id=?", (identity.id,)).fetchone()
        if row is None:
            db.execute("INSERT INTO optics_carts VALUES(?,?,0,NULL,?)", (identity.id, uuid.uuid4().hex, json_bytes({"sources": [], "choices": {}})))
            row = db.execute("SELECT * FROM optics_carts WHERE account_id=?", (identity.id,)).fetchone()
        try:
            state = json.loads(row["state_json"])
            if (not isinstance(state, dict) or set(state) != {"sources", "choices"} or
                    not isinstance(state["sources"], list) or not isinstance(state["choices"], dict) or
                    len(state["sources"]) > MAX_SOURCES or len(state["choices"]) > MAX_ROWS or
                    type(row["revision"]) is not int or not 0 <= row["revision"] <= MAX_REVISION):
                raise ValueError("invalid stored cart")
        except (ValueError, TypeError) as exc:
            raise APIError("cart_unavailable", "购物车资料暂时无法读取，请稍后重试。", 503) from exc
        return dict(row), state

    @staticmethod
    def assert_revision(record, payload):
        if not isinstance(payload.get("cartId"), str) or payload["cartId"] != record["cart_id"]:
            raise APIError("cart_account_changed", "登录账号或购物车已变更，请重新载入购物车后再操作。", 409)
        if type(payload.get("revision")) is not int or not 0 <= payload["revision"] < MAX_REVISION:
            raise APIError("invalid_cart", "请提交有效的购物车版本。")
        if payload["revision"] != record["revision"]:
            raise APIError("cart_conflict", "购物车已在其他页面更新，请重新载入后再操作。", 409, {"revision": record["revision"]})

    def envelope(self, record, state):
        preview, _ = combine(state)
        current_source_specs(preview, self.catalog)
        current_marking_view(preview, self.catalog)
        return {"cartId": record["cart_id"], "revision": record["revision"], "updatedAt": record["updated_at"],
                "preview": preview, "items": [{"componentId": row["componentId"], **state["choices"][row["componentId"]]} for row in rows(preview)],
                "sources": [{"id": source["id"], "name": source["name"], "createdAt": source["createdAt"],
                             "kitQuantity": source["preview"]["totals"]["kits"],
                             "componentTypes": source["preview"]["totals"]["componentTypes"],
                             "hasLayout": bool(source["preview"].get("layout"))} for source in state["sources"]], "limits": LIMITS}

    def save(self, db, identity, record, state):
        data = json_bytes(state)
        if len(data) > MAX_CART_BYTES:
            raise APIError("cart_full", "购物车资料超过 8 MiB，请先完成已有订单或清空购物车。", 413)
        stamp, revision = timestamp(), record["revision"] + 1
        db.execute("UPDATE optics_carts SET revision=?,updated_at=?,state_json=? WHERE account_id=?",
                   (revision, stamp, data, identity.id))
        return {**record, "revision": revision, "updated_at": stamp}

    def read(self, identity):
        self.require_identity(identity)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record, state = self.read_record(db, identity)
            return self.envelope(record, state)

    def add(self, identity, payload, catalog):
        self.require_identity(identity)
        shape(payload, {"cartId", "revision", "requestId", "name", "payload"}, {"cartId", "revision", "requestId", "name", "payload"}, "加入购物车请求")
        request_id = payload["requestId"]
        if type(payload["revision"]) is not int or not 0 <= payload["revision"] < MAX_REVISION:
            raise APIError("invalid_cart", "请提交有效的购物车版本。")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
            raise APIError("invalid_cart", "加入购物车请求编号无效。")
        name = text(payload["name"], "购物车方案名称", 160, True).strip()
        source_request = payload["payload"]
        shape(source_request, {"items", "layout", "extras", "catalogVersion", "requires"}, label="加入购物车的原方案")
        fingerprint = hashlib.sha256(canonical({"name": name, "payload": source_request}).encode()).hexdigest()
        replay = False
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record, state = self.read_record(db, identity)
            if payload["cartId"] != record["cart_id"]:
                raise APIError("cart_account_changed", "登录账号或购物车已变更，请重新载入购物车后再操作。", 409)
            receipt = db.execute("SELECT fingerprint FROM optics_cart_receipts WHERE account_id=? AND request_id=?", (identity.id, request_id)).fetchone()
            if receipt is not None:
                if receipt["fingerprint"] != fingerprint:
                    raise APIError("cart_request_conflict", "此加入请求编号已用于不同内容，请重新确认方案。", 409)
                replay = True
            else:
                self.assert_revision(record, payload)
                if len(state["sources"]) >= MAX_SOURCES:
                    raise APIError("cart_full", "购物车最多保存 100 次加入记录，请先完成已有订单或清空购物车。", 409)
                snapshot = aggregate(catalog, source_request, require_items=True)
                if snapshot.get("layout") is not None and not snapshot["layoutValidation"]["valid"]:
                    raise APIError("layout_invalid", "布局存在定位或碰撞问题，请调整后再加入购物车。", 409, snapshot["layoutValidation"])
                normalized = {"catalogVersion": catalog["version"], "extras": snapshot.get("layoutExtras", snapshot.get("extras", []))}
                if snapshot.get("requires"):
                    normalized["requires"] = snapshot["requires"]
                if snapshot.get("layout") is not None:
                    normalized["layout"] = snapshot["layout"]
                else:
                    normalized["items"] = [{"kitId": item["kitId"], "quantity": item["quantity"]} for item in snapshot["items"]]
                old, _ = combine(state)
                old_quantities = {row["componentId"]: row["baseQuantity"] for row in rows(old)}
                state["sources"].append({"id": uuid.uuid4().hex, "name": name, "createdAt": timestamp(), "payload": normalized, "preview": snapshot})
                updated, _ = combine(state)
                if updated["totals"]["componentTypes"] > MAX_ROWS:
                    raise APIError("cart_full", "购物车最多保存 2000 种器件，请先分批导出。", 409)
                for row in rows(updated):
                    cid = row["componentId"]
                    delta = row["baseQuantity"] - old_quantities.get(cid, 0)
                    if not delta:
                        continue
                    choice = state["choices"].get(cid)
                    if choice is None or choice["removed"]:
                        state["choices"][cid] = {"quantity": delta, "selected": True, "removed": False}
                    else:
                        choice["quantity"] = integer(choice["quantity"] + delta, "购物车器件数量", MAX_COMPONENT_QUANTITY)
                record = self.save(db, identity, record, state)
                db.execute("INSERT INTO optics_cart_receipts VALUES(?,?,?)", (identity.id, request_id, fingerprint))
                db.execute("DELETE FROM optics_cart_receipts WHERE account_id=? AND rowid NOT IN (SELECT rowid FROM optics_cart_receipts WHERE account_id=? ORDER BY rowid DESC LIMIT 1000)", (identity.id, identity.id))
            result = self.envelope(record, state)
        return {**result, "backup": self.store.backup(), "replayed": replay}

    def update(self, identity, payload):
        self.require_identity(identity)
        shape(payload, {"cartId", "revision", "items"}, {"cartId", "revision", "items"}, "购物车修改请求")
        if not isinstance(payload["items"], list) or len(payload["items"]) > MAX_ROWS:
            raise APIError("invalid_cart", "购物车项目必须是最多 2000 项的数组。")
        choices = {}
        for item in payload["items"]:
            shape(item, {"componentId", "quantity", "selected", "removed"}, {"componentId", "quantity", "selected", "removed"}, "购物车项目")
            cid = item["componentId"]
            if (not isinstance(cid, str) or cid in choices or type(item["selected"]) is not bool or
                    type(item["removed"]) is not bool):
                raise APIError("invalid_cart", "购物车项目重复或勾选、删除状态无效。")
            choices[cid] = {"quantity": integer(item["quantity"], "购物车数量", MAX_COMPONENT_QUANTITY),
                            # Delete is the user's stronger instruction, even
                            # when an older client sends its previous selection.
                            "selected": item["selected"] and not item["removed"], "removed": item["removed"]}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record, state = self.read_record(db, identity)
            self.assert_revision(record, payload)
            if set(choices) != set(state["choices"]):
                raise APIError("cart_items_changed", "请提交当前购物车的完整项目，删除项目请使用删除标记。", 409)
            state["choices"] = choices
            record = self.save(db, identity, record, state)
            result = self.envelope(record, state)
        return {**result, "backup": self.store.backup()}

    def clear(self, identity, payload):
        self.require_identity(identity)
        shape(payload, {"cartId", "revision"}, {"cartId", "revision"}, "清空购物车请求")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record, _ = self.read_record(db, identity)
            self.assert_revision(record, payload)
            state = {"sources": [], "choices": {}}
            record = self.save(db, identity, record, state)
            result = self.envelope(record, state)
        return {**result, "backup": self.store.backup()}

    def for_export(self, identity, payload, catalog):
        self.require_identity(identity)
        shape(payload, {"cartId", "revision"}, {"cartId", "revision"}, "购物车导出请求")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record, state = self.read_record(db, identity)
            self.assert_revision(record, payload)
            return export_preview(state, catalog)
