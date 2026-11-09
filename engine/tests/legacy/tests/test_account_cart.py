"""Persistent account carts, concurrency, immutable plans and multi-board exports."""
import copy
import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from bom import APIError
from breadboard import board_specs
from cart import CartStore, rows
from exports import export_result
from shared_kits import Identity, SharedKitStore
from test_backend import fixture, extra
from test_layout import layout_fixture, request
import test_access_settings as access_tests


def token(envelope):
    return {key: envelope[key] for key in ("cartId", "revision")}


class AccountCartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.backing = SharedKitStore(self.root / "shared.sqlite3", self.root / "backup.sqlite3")
        self.store = CartStore(self.backing)
        self.user = Identity("101", "用户甲", "user")
        self.catalog = fixture()
        self.serial = 0

    def tearDown(self):
        self.temp.cleanup()

    def add(self, source=None, name="方案", envelope=None, identity=None, **overrides):
        identity = identity or self.user
        envelope = envelope or self.store.read(identity)
        self.serial += 1
        data = {**token(envelope), "requestId": f"test-add-{self.serial:04d}", "name": name,
                "payload": source or {"items": [{"kitId": "alpha", "quantity": 1}]}, **overrides}
        return self.store.add(identity, data, self.catalog)

    def update(self, envelope, choices):
        return self.store.update(self.user, {**token(envelope), "items": choices})

    def test_separate_accounts_persistence_restart_and_backup(self):
        initial = self.store.read(self.user)
        self.assertEqual(initial["revision"], 0)
        self.assertEqual(initial["items"], [])
        added = self.add()
        self.assertEqual(added["backup"]["status"], "ok")
        readonly = Identity("101", "用户甲", "readonly")
        self.assertEqual(self.store.read(readonly)["items"], added["items"])
        admin = Identity("202", "管理员", "admin")
        self.assertEqual(self.store.read(admin)["items"], [])
        self.assertNotEqual(self.store.read(admin)["cartId"], added["cartId"])
        restarted = CartStore(SharedKitStore(self.root / "shared.sqlite3"))
        self.assertEqual(restarted.read(self.user)["items"], added["items"])
        with sqlite3.connect(self.root / "backup.sqlite3") as backup:
            self.assertEqual(backup.execute("SELECT revision FROM optics_carts WHERE account_id='101'").fetchone()[0], 1)

    def test_add_is_immutable_and_accumulates_current_edited_quantities(self):
        source = {"items": [{"kitId": "alpha", "quantity": 1}]}
        first = self.add(source)
        source["items"][0]["quantity"] = 500
        self.catalog["kits"][0]["components"][0]["quantity"] = 1
        choices = copy.deepcopy(first["items"])
        plate = next(row for row in rows(first["preview"]) if row["sourceComponentId"] == "plate")
        target = next(item for item in choices if item["componentId"] == plate["componentId"])
        target.update(quantity=17, selected=False)
        edited = self.update(first, choices)
        added = self.add({"items": [{"kitId": "alpha", "quantity": 2}]}, envelope=edited)
        final = next(item for item in added["items"] if item["componentId"] == target["componentId"])
        self.assertEqual(final["quantity"], 19)
        self.assertFalse(final["selected"])
        self.assertEqual(next(row for row in rows(added["preview"]) if row["componentId"] == target["componentId"])["baseQuantity"], 3)
        self.catalog["kits"][0]["components"][0]["quantity"] = 100
        self.assertEqual(self.store.read(self.user)["items"], added["items"])
        self.assertEqual(added["sources"][0]["kitQuantity"], 1)

    def test_remove_then_add_resurrects_only_new_quantity(self):
        cart = self.add()
        choices = [{**item, "quantity": 50, "selected": False, "removed": True} for item in cart["items"]]
        cart = self.update(cart, choices)
        cart = self.add(envelope=cart)
        for item in cart["items"]:
            self.assertTrue(item["selected"])
            self.assertFalse(item["removed"])
            self.assertLess(item["quantity"], 50)

    def test_delete_takes_precedence_over_selection_and_persists_before_export(self):
        cart = self.add()
        removed_id = cart["items"][0]["componentId"]
        choices = [{**item, "removed": item["componentId"] == removed_id} for item in cart["items"]]
        self.assertTrue(choices[0]["selected"])
        original = copy.deepcopy(choices)
        changed = self.update(cart, choices)
        deleted = next(item for item in changed["items"] if item["componentId"] == removed_id)
        self.assertTrue(deleted["removed"])
        self.assertFalse(deleted["selected"])
        self.assertEqual(choices, original, "normalization must not mutate the caller's request")
        restarted = CartStore(SharedKitStore(self.root / "shared.sqlite3"))
        self.assertEqual(restarted.read(self.user)["items"], changed["items"])
        exported = restarted.for_export(self.user, token(changed), self.catalog)
        self.assertNotIn(removed_id, {row["componentId"] for row in rows(exported)})
        added = self.add(envelope=changed)
        restored = next(item for item in added["items"] if item["componentId"] == removed_id)
        self.assertFalse(restored["removed"])
        self.assertTrue(restored["selected"])
        self.assertEqual(restored["quantity"], cart["items"][0]["quantity"])

    def test_delete_precedence_does_not_accept_duplicate_ids_or_non_boolean_states(self):
        cart = self.add()
        mutations = [lambda items: items.append(copy.deepcopy(items[0])),
                     lambda items: items[0].update(removed="true"),
                     lambda items: items[0].update(removed=1),
                     lambda items: items[0].update(removed=True, selected="true"),
                     lambda items: items[0].update(removed=True, selected=1),
                     lambda items: items[0].update(removed=True, selected=None)]
        for mutate in mutations:
            choices = copy.deepcopy(cart["items"])
            mutate(choices)
            with self.subTest(choices=choices), self.assertRaises(APIError) as caught:
                self.update(cart, choices)
            self.assertEqual(caught.exception.code, "invalid_cart")
            self.assertEqual(self.store.read(self.user)["revision"], cart["revision"])
            self.assertEqual(self.store.read(self.user)["items"], cart["items"])

    def test_idempotent_retry_and_clear_do_not_reapply_addition(self):
        initial = self.store.read(self.user)
        addition = {**token(initial), "requestId": "same-request-001", "name": "同一个请求", "payload": {"items": [{"kitId": "alpha", "quantity": 1}]}}
        first = self.store.add(self.user, addition, self.catalog)
        replay = self.store.add(self.user, addition, self.catalog)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["revision"], 1)
        self.assertEqual(replay["items"], first["items"])
        with self.assertRaises(APIError) as error:
            self.store.add(self.user, {**addition, "name": "不同的请求"}, self.catalog)
        self.assertEqual(error.exception.code, "cart_request_conflict")
        cleared = self.store.clear(self.user, token(first))
        replay = self.store.add(self.user, addition, self.catalog)
        self.assertEqual(replay["items"], [])
        self.assertEqual(replay["revision"], cleared["revision"])

    def test_account_switch_and_stale_mutations_never_write(self):
        first = self.add()
        other = Identity("202", "另一个账户", "admin")
        for operation in (lambda: self.store.clear(other, token(first)),
                          lambda: self.store.update(other, {**token(first), "items": first["items"]}),
                          lambda: self.store.for_export(other, token(first), self.catalog)):
            with self.assertRaises(APIError) as error:
                operation()
            self.assertEqual(error.exception.code, "cart_account_changed")
        changed = self.update(first, first["items"])
        for operation in (lambda: self.store.clear(self.user, token(first)),
                          lambda: self.store.update(self.user, {**token(first), "items": first["items"]}),
                          lambda: self.store.for_export(self.user, token(first), self.catalog)):
            with self.assertRaises(APIError) as error:
                operation()
            self.assertEqual(error.exception.code, "cart_conflict")
        self.assertEqual(self.store.read(self.user)["revision"], changed["revision"])

    def test_concurrent_writers_have_one_winner(self):
        initial = self.store.read(self.user)
        def add(number):
            try:
                self.add(envelope=initial, requestId=f"concurrent-{number}")
                return "ok"
            except APIError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(add, (1001, 1002))), ["cart_conflict", "ok"])
        self.assertEqual(self.store.read(self.user)["revision"], 1)

    def test_source_specific_extras_and_verified_models(self):
        source = {"items": [], "extras": [extra("e1", model="MODEL-A", quantity=3), extra("e2", model="", quantity=1)]}
        first = self.add(source)
        source["extras"][0]["model"] = "MODEL-B"
        second = self.add(source, envelope=first)
        self.assertEqual(len(second["items"]), 4)
        source["extras"][0]["model"] = "model-a"
        third = self.add(source, envelope=second)
        self.assertEqual(len(third["items"]), 5)
        known = [row for row in rows(third["preview"]) if row["model"] == "MODEL-A"]
        self.assertEqual(known[0]["quantity"], 6)
        self.assertEqual(len([row for row in rows(third["preview"]) if row["model"] == "待确认"]), 3)

    def test_empty_export_and_invalid_updates(self):
        cart = self.add()
        for change in ({"quantity": True}, {"quantity": 0}, {"quantity": 10_000_001}, {"selected": 1}, {"removed": 1}):
            choices = copy.deepcopy(cart["items"])
            choices[0].update(change)
            with self.subTest(change=change), self.assertRaises(APIError):
                self.update(cart, choices)
        for choices in ([], [*cart["items"], cart["items"][0]], [{**item, "componentId": "forged"} for item in cart["items"]]):
            with self.subTest(choices=choices), self.assertRaises(APIError):
                self.update(cart, choices)
        cart = self.update(cart, [{**item, "selected": False} for item in cart["items"]])
        with self.assertRaises(APIError) as error:
            self.store.for_export(self.user, token(cart), self.catalog)
        self.assertEqual(error.exception.code, "empty_checkout")

    def test_strict_original_request_and_limits_rollback(self):
        for source in ({"items": [], "checkout": {"items": []}}, {"items": [], "ownerId": "202"}, {"items": [], "paths": ["secret"]}):
            with self.assertRaises(APIError):
                self.add(source)
        with patch("cart.MAX_SOURCES", 1):
            first = self.add()
            with self.assertRaises(APIError) as error:
                self.add(envelope=first)
            self.assertEqual(error.exception.code, "cart_full")
        self.assertEqual(self.store.read(self.user)["revision"], 1)
        with patch("cart.MAX_CART_BYTES", 1), self.assertRaises(APIError):
            self.add(envelope=first)
        self.assertEqual(self.store.read(self.user)["revision"], 1)

    def test_multisource_boards_qty_files_and_original_layouts(self):
        self.catalog = layout_fixture()
        first_request = request()
        first_request["layout"]["instances"] = []
        second_request = copy.deepcopy(first_request)
        second_request["layout"]["board"]["widthMm"] = 400
        first = self.add(first_request, "甲板")
        second = self.add(second_request, "乙板", envelope=first)
        cart = self.add(first_request, "再加甲板", envelope=second)
        self.assertEqual(len(cart["items"]), 2)
        self.assertEqual(sorted(item["quantity"] for item in cart["items"]), [1, 2])
        choices = [{**item, "quantity": item["quantity"] * 3} for item in cart["items"]]
        cart = self.update(cart, choices)
        preview = self.store.for_export(self.user, token(cart), self.catalog)
        cache = (self.root / "board-cache").resolve()
        cache.mkdir()
        def generate(board, root):
            spec = board_specs(board)
            step, pdf = cache / (spec["componentId"] + ".step"), cache / (spec["componentId"] + ".pdf")
            step.write_bytes(b"board STEP fixture")
            pdf.write_bytes(b"board PDF fixture")
            return {"componentId": spec["componentId"], "step": str(step), "drawing": str(pdf)}
        with patch.dict(os.environ, {"ZZLAB_BOARD_CACHE": str(cache)}), patch("breadboard.ensure_board_artifacts", side_effect=generate) as generated:
            data, _, _ = export_result(preview, "bundle", self.root, self.root)
        self.assertEqual(generated.call_count, 2)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            self.assertEqual(len([name for name in names if name.endswith(".step")]), 2)
            self.assertEqual(len([name for name in names if name.endswith(".pdf")]), 2)
            self.assertEqual(len([name for name in names if name.endswith("原布局.json")]), 3)
            self.assertEqual(len([name for name in names if name.endswith("原总俯视图.svg")]), 3)
            config = json.loads(archive.read("套件配置.json"))
            self.assertEqual(config["totals"]["boards"], 9)
            workbook = load_workbook(io.BytesIO(archive.read("生产清单.xlsx")))
            self.assertEqual(sorted(workbook["生产清单"].cell(index, 5).value for index in (6, 7)), [3, 6])
            self.assertEqual(workbook["面包板规格"].max_row, 7)

    def test_exclusion_filters_assets_and_source_reviews(self):
        self.catalog["components"][0]["stepPath"] = None
        cart = self.add()
        choices = [{**item, "selected": False} for item in cart["items"]]
        optic = next(row for row in rows(cart["preview"]) if row["kind"] == "lubang")
        next(item for item in choices if item["componentId"] == optic["componentId"])["selected"] = True
        cart = self.update(cart, choices)
        preview = self.store.for_export(self.user, token(cart), self.catalog)
        self.assertEqual(preview["manufacturing"], [])
        self.assertEqual(preview["reviewGroups"], [])
        data, _, _ = export_result(preview, "bundle", self.root)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertFalse(any(name.endswith((".step", ".pdf")) for name in archive.namelist()))

    def test_partial_group_reviews_name_only_selected_components(self):
        for component in self.catalog["components"][:2]:
            component["manufacturingSpec"] = {"material": "待确认", "surfaceTreatment": "待确认"}
        cart = self.add({"items": [{"kitId": "beta", "quantity": 1}]})
        plate = next(row for row in rows(cart["preview"]) if row["sourceComponentId"] == "plate")
        cart = self.update(cart, [{**item, "selected": item["componentId"] == plate["componentId"]} for item in cart["items"]])
        preview = self.store.for_export(self.user, token(cart), self.catalog)
        group = next(group for group in preview["reviewGroups"] if group["id"] == "manufacture")
        self.assertEqual(group["items"][0]["componentNames"], ["测试plate"])
        self.assertIn("1 种自制件", group["items"][0]["summary"])
        self.assertNotIn("测试bracket", str(group))


class AccountCartHTTPTests(unittest.TestCase):
    setUp = access_tests.AccessSettingsHTTPTests.setUp
    tearDown = access_tests.AccessSettingsHTTPTests.tearDown
    start_server = access_tests.AccessSettingsHTTPTests.start_server
    stop_server = access_tests.AccessSettingsHTTPTests.stop_server
    http = access_tests.AccessSettingsHTTPTests.http

    def test_identity_roles_and_private_account_scope(self):
        for role in ("user", "readonly", "admin"):
            status, data = self.http("GET", "/api/cart", role=role)
            self.assertEqual(status, 200, data)
            self.assertEqual(data["items"], [])
        status, first = self.http("GET", "/api/cart", role="readonly")
        body = {**token(first), "requestId": "http-add-0001", "name": "只读个人订单", "payload": {"items": [{"kitId": "alpha", "quantity": 1}]}}
        status, added = self.http("POST", "/api/cart/add", body, role="readonly")
        self.assertEqual(status, 200, added)
        self.assertTrue(added["items"])
        status, _ = self.http("POST", "/api/cart/export?format=lubang", token(added), role="readonly")
        self.assertEqual(status, 200)
        self.assertEqual(self.http("POST", "/api/shared-kits", {}, role="readonly")[0], 403)
        status, other = self.http("GET", "/api/cart", user_id="202")
        self.assertEqual(other["items"], [])
        status, error = self.http("POST", "/api/cart/clear", token(added), user_id="202")
        self.assertEqual((status, error["error"]["code"]), (409, "cart_account_changed"))
        for uid in (None, "0", "invalid"):
            self.assertEqual(self.http("GET", "/api/cart", user_id=uid)[0], 403)
        self.assertEqual(self.http("GET", "/api/cart", headers=(("X-ZZLAB-User-ID", "202"),))[0], 403)
        self.assertEqual(self.http("GET", "/api/cart", token="forged")[0], 401)

    def test_guest_has_no_cart_and_strict_origin_body_validation(self):
        self.server.access_settings.update({"guestAccessEnabled": True, "revision": 0}, Identity("101", "admin", "admin"))
        self.assertEqual(self.http("GET", "/api/cart", role="guest")[0], 404)
        self.assertEqual(self.http("POST", "/api/cart/clear", {}, role="guest")[0], 403)
        _, first = self.http("GET", "/api/cart")
        self.assertEqual(self.http("POST", "/api/cart/clear", {**token(first), "accountId": "202"})[0], 400)
        self.assertEqual(self.http("POST", "/api/cart/clear", token(first), headers=(("Origin", "https://evil.example"),))[0], 403)
        duplicate = ('{"cartId":"' + first["cartId"] + '","revision":0,"revision":0}').encode()
        self.assertEqual(self.http("POST", "/api/cart/clear", raw=duplicate)[0], 400)
        self.assertEqual(self.http("POST", "/api/cart/export?format=layout-json", token(first))[0], 400)


if __name__ == "__main__":
    unittest.main()
