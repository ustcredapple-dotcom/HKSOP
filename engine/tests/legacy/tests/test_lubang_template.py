"""Official cart-template coordinates, explicit identity blockers and no lost rows."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from openpyxl import load_workbook

from bom import APIError, aggregate, lubang_import_plan
from cart import CartStore
from exports import LUBANG_TEMPLATE, export_result, lubang_workbook_bytes
from shared_kits import Identity, SharedKitStore
from test_backend import fixture, payload, extra


class LubangTemplateTests(unittest.TestCase):
    def setUp(self):
        self.catalog = fixture()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for cid in ("plate", "bracket"):
            (self.root / f"{cid}.step").write_bytes(b"STEP fixture")
            (self.root / f"{cid}.pdf").write_bytes(b"PDF fixture")

    def tearDown(self):
        self.temp.cleanup()

    def test_original_template_coordinates_images_and_asset_unchanged(self):
        original = LUBANG_TEMPLATE.read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(), "2d1a85caaa930228d5d738eb931e3176621b6916330d12a62280c9ec27e92b88")
        preview = aggregate(self.catalog, payload(checkout={"items": [{"componentId": "optic", "quantity": 19}]}))
        content, mime, filename = export_result(preview, "lubang", self.root)
        book = load_workbook(io.BytesIO(content))
        self.assertEqual(book.sheetnames, ["Sheet1", "Sheet2", "Sheet3"])
        self.assertEqual(book["Sheet1"]["A2"].value, "产品型号导入清单")
        self.assertEqual([book["Sheet1"].cell(3, col).value for col in (1, 2, 3)], ["序号", "产品型号（Product Name）", "数量（Quantity）"])
        self.assertEqual([book["Sheet1"].cell(4, col).value for col in (1, 2, 3)], [1, "OPT-OLD", 19])
        self.assertEqual(book["Sheet1"]["C4"].data_type, "n")
        self.assertEqual(book["Sheet1"]["B4"].data_type, "s")
        self.assertEqual(len(book["Sheet1"]._images), 2)
        self.assertEqual(set(str(r) for r in book["Sheet1"].merged_cells.ranges), {"A1:C1", "A2:C2", "E2:H4"})
        self.assertIn("请使用半角", book["Sheet1"]["E2"].value)
        self.assertEqual(LUBANG_TEMPLATE.read_bytes(), original)

    def test_unknown_alias_and_non_sku_values_block_direct_import(self):
        base = aggregate(self.catalog, payload())
        for model, status, notes in (("", "已核对", ""), ("待确认", "已核对", ""),
                                      ("PBS24-532-1", "采购型号待确认", "原装配别名映射待确认"),
                                      ("ＭＴ-Ａ１", "已核对", ""), ("MT A1", "已核对", ""),
                                      ('=HYPERLINK("https://bad")', "已核对", ""),
                                      ("MODEL", "已核对", "原装配别名待确认")):
            preview = copy.deepcopy(base)
            preview["lubang"][0].update(model=model, status=status, notes=notes)
            with self.subTest(model=model), self.assertRaises(APIError) as error:
                export_result(preview, "lubang", self.root)
            self.assertEqual(error.exception.code, "lubang_model_unconfirmed")
            self.assertEqual(error.exception.status, 409)
            self.assertEqual(error.exception.details["items"][0]["componentId"], "optic")

    def test_process_and_source_reviews_do_not_block_a_declared_model(self):
        for status in ("材料待确认", "工艺待确认", "图纸待审核", "原文件版本待确认", "用户补充", "型号已核对，材料待确认"):
            row = {"componentId": "test", "name": "test", "model": "OPM-12.5BS", "quantity": 4,
                   "status": status, "notes": "表面处理待确认；来源文件待核对；采购型号已确认，图纸待核对"}
            self.assertEqual(lubang_import_plan([row])["blocked"], [], status)

    def test_zip_preserves_valid_and_blocked_quantities_without_silent_omission(self):
        self.catalog["components"][2].update(model="PBS24-532-1", status="采购型号待确认", notes="导入尾缀 -1 的映射待确认")
        preview = aggregate(self.catalog, payload(extras=[extra(model="CRM-1AS", quantity=4)]))
        self.assertEqual((preview["lubangImport"]["readyTypes"], preview["lubangImport"]["blockedTypes"]), (1, 1))
        content, _, _ = export_result(preview, "bundle", self.root)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertIn("麓邦待确认清单.xlsx", archive.namelist())
            self.assertIn("麓邦导入说明.txt", archive.namelist())
            config = json.loads(archive.read("套件配置.json"))
            self.assertEqual(sum(item["quantity"] for bucket in ("ready", "blocked") for item in config["lubangImport"][bucket]), 11)
            book = load_workbook(io.BytesIO(archive.read("麓邦采购.xlsx")))
            self.assertEqual((book["Sheet1"]["B4"].value, book["Sheet1"]["C4"].value), ("CRM-1AS", 4))
            self.assertIsNone(book["Sheet1"]["B5"].value)
            pending = load_workbook(io.BytesIO(archive.read("麓邦待确认清单.xlsx")))["未导入项目"]
            self.assertEqual((pending["D6"].value, pending["E6"].value), ("PBS24-532-1", 7))
            self.assertIn("未导入", archive.read("麓邦导入说明.txt").decode())
            self.assertEqual(len([name for name in archive.namelist() if name.endswith(".step")]), 2)

    def test_same_model_case_variants_merge_supplier_quantity_without_guessing(self):
        ready = [{"model": "MOP-50", "quantity": 2}, {"model": "mop-50", "quantity": 3}, {"model": "MOP-50-P4", "quantity": 1}]
        book = load_workbook(io.BytesIO(lubang_workbook_bytes({"ready": ready})))
        sheet = book["Sheet1"]
        self.assertEqual((sheet["B4"].value, sheet["C4"].value), ("MOP-50", 5))
        self.assertEqual((sheet["B5"].value, sheet["C5"].value), ("MOP-50-P4", 1))

    def test_more_than_fifty_rows_are_retained_in_template_columns(self):
        ready = [{"model": f"MODEL-{index}", "quantity": index + 1} for index in range(65)]
        book = load_workbook(io.BytesIO(lubang_workbook_bytes({"ready": ready})))
        self.assertEqual((book["Sheet1"]["A68"].value, book["Sheet1"]["B68"].value, book["Sheet1"]["C68"].value), (65, "MODEL-64", 65))
        self.assertEqual(book["Sheet1"]["B68"].style_id, book["Sheet1"]["B5"].style_id)

    def test_cart_metadata_keeps_primary_ids_and_pending_source_on_merged_sku(self):
        store = CartStore(SharedKitStore(self.root / "shared.sqlite3"))
        who = Identity("101", "test", "user")
        cart = store.read(who)
        source = {"items": [{"kitId": "alpha", "quantity": 1}]}
        cart = store.add(who, {"cartId": cart["cartId"], "revision": cart["revision"], "requestId": "lbtek-add-001", "name": "已明确", "payload": source}, self.catalog)
        self.catalog["components"][2].update(status="采购型号待确认", notes="原装配别名待确认")
        cart = store.add(who, {"cartId": cart["cartId"], "revision": cart["revision"], "requestId": "lbtek-add-002", "name": "待确认", "payload": source}, self.catalog)
        blocked = cart["preview"]["lubangImport"]["blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertTrue(blocked[0]["componentId"].startswith("cart:"))
        self.assertEqual(blocked[0]["quantity"], 4)
        choices = [{**item, "selected": item["componentId"] != blocked[0]["componentId"]} for item in cart["items"]]
        cart = store.update(who, {"cartId": cart["cartId"], "revision": cart["revision"], "items": choices})
        selected = store.for_export(who, {"cartId": cart["cartId"], "revision": cart["revision"]}, self.catalog)
        self.assertEqual(selected["lubangImport"]["blocked"], [])


if __name__ == "__main__":
    unittest.main()
