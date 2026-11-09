"""Final order choices affect documents and assets without rewriting the plan."""
import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from bom import APIError, MAX_COMPONENT_QUANTITY, aggregate
from exports import HEADERS, MARKING_HEADERS, export_result, workbook_bytes
from test_backend import extra, fixture, payload
from test_layout import layout_fixture, request


def checkout(**quantities):
    return {"items": [{"componentId": cid, "quantity": qty} for cid, qty in quantities.items()]}


class CheckoutTests(unittest.TestCase):
    def test_selection_quantity_totals_and_original_provenance(self):
        catalog = fixture()
        original = copy.deepcopy(catalog)
        preview = aggregate(catalog, payload(checkout=checkout(plate=3, optic=20)))
        self.assertEqual(preview["totals"], {"kits": 5, "componentTypes": 2, "componentQuantity": 23})
        self.assertEqual(preview["standard"], [])
        plate = preview["manufacturing"][0]
        self.assertEqual((plate["quantity"], plate["baseQuantity"]), (3, 8))
        self.assertEqual(sum(k["quantity"] for k in plate["kits"]), 8)
        self.assertEqual(catalog, original)
        self.assertEqual(aggregate(catalog, payload())["totals"]["componentQuantity"], 26)
        workbook = load_workbook(io.BytesIO(workbook_bytes(preview, "manufacturing", "test")))
        self.assertEqual(workbook["生产清单"]["E6"].value, 3)
        self.assertIn("非下单数量", workbook["套件分解"]["A2"].value)
        self.assertIn("原方案", workbook["套件分解"]["H5"].value)

    def test_unchecked_reviews_and_missing_assets_do_not_block_selected_order(self):
        catalog = fixture()
        catalog["components"][0].update(stepPath=None, status="版本待确认")
        catalog["components"][2].update(model="", status="型号待确认")
        full = aggregate(catalog, payload())
        self.assertTrue(any(group["blocking"] for group in full["reviewGroups"]))
        selected = aggregate(catalog, payload(checkout=checkout(bracket=2)))
        self.assertEqual(selected["warnings"], [])
        self.assertEqual(selected["reviewGroups"], [])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "bracket.step").write_bytes(b"STEP fixture")
            (root / "bracket.pdf").write_bytes(b"PDF fixture")
            data, _, _ = export_result(selected, "bundle", root)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(len([n for n in archive.namelist() if n.endswith(".step")]), 1)

    def test_merged_rows_use_primary_id_and_keep_all_selected_source_reviews(self):
        catalog = fixture()
        data = payload(extras=[extra(notes="extra source", quantity=5)])
        data["checkout"] = checkout(optic=1)
        selected = aggregate(catalog, data)
        self.assertEqual(selected["lubang"][0]["baseQuantity"], 12)
        self.assertEqual(selected["lubang"][0]["componentIds"], ["optic", "extra:e1"])
        data["checkout"] = {"items": [{"componentId": "extra:e1", "quantity": 1}]}
        with self.assertRaises(APIError) as error:
            aggregate(catalog, data)
        self.assertEqual(error.exception.code, "unknown_checkout_component")
        catalog["components"][2]["status"] = "型号映射待确认"
        data["checkout"] = checkout(optic=1)
        self.assertTrue(aggregate(catalog, data)["reviewGroups"])

    def test_malformed_checkout_is_rejected(self):
        bad_values = [None, [], {}, {"items": None}, {"items": [], "path": "secret"},
                      {"items": [None]}, {"items": [{"componentId": "plate", "quantity": 2, "stepPath": "secret"}]},
                      {"items": [{"componentId": ["plate"], "quantity": 2}]},
                      checkout(unknown=1), checkout(bracket=1, plate=2) | {"extra": True},
                      {"items": [{"componentId": "plate", "quantity": 1}] * 2}]
        bad_values += [checkout(plate=q) for q in (True, False, 0, -1, 1.5, "2", None, MAX_COMPONENT_QUANTITY + 1)]
        for value in bad_values:
            with self.subTest(value=value), self.assertRaises(APIError):
                aggregate(fixture(), payload(checkout=value))
        self.assertEqual(aggregate(fixture(), payload(checkout=checkout(plate=MAX_COMPONENT_QUANTITY)))["manufacturing"][0]["quantity"], MAX_COMPONENT_QUANTITY)

    def test_empty_selection_can_preview_or_save_layout_but_cannot_order(self):
        data = payload(checkout=checkout())
        preview = aggregate(fixture(), data)
        self.assertEqual(preview["totals"]["componentTypes"], 0)
        self.assertEqual(preview["reviewGroups"], [])
        with self.assertRaises(APIError) as error:
            aggregate(fixture(), data, require_items=True)
        self.assertEqual(error.exception.code, "empty_checkout")
        for kind in ("lubang", "manufacturing", "bundle"):
            with self.subTest(kind=kind), self.assertRaises(APIError) as error:
                export_result(preview, kind, "/unused")
            self.assertEqual(error.exception.code, "empty_checkout")
        data = request() | {"checkout": checkout()}
        preview = aggregate(layout_fixture(), data)
        content, _, _ = export_result(preview, "layout-json", "/unused")
        self.assertEqual(len(json.loads(content)["layout"]["instances"]), 3)

    def test_generated_board_can_be_omitted_or_have_its_quantity_changed(self):
        catalog, data = layout_fixture(), request()
        board = next(r for r in aggregate(catalog, data)["manufacturing"] if r.get("generatedBoard"))
        data["checkout"] = {"items": [{"componentId": board["componentId"], "quantity": 4}]}
        preview = aggregate(catalog, data)
        self.assertEqual(preview["totals"]["boards"], 4)
        workbook = load_workbook(io.BytesIO(workbook_bytes(preview, "manufacturing", "test")))
        self.assertIn("本次生产 4 块", workbook["面包板规格"]["A2"].value)
        self.assertEqual(workbook["生产清单"]["E6"].value, 4)
        data["checkout"] = checkout(optic=2)
        preview = aggregate(catalog, data)
        self.assertEqual(preview["totals"]["boards"], 0)
        with patch("breadboard.ensure_board_artifacts") as generate, patch("layout.layout_svg", return_value=b"<svg/>"):
            content, _, _ = export_result(preview, "bundle", "/unused")
        generate.assert_not_called()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertFalse(any(name.endswith((".step", ".pdf")) for name in archive.namelist()))
            workbook = load_workbook(io.BytesIO(archive.read("生产清单.xlsx")))
            self.assertNotIn("面包板规格", workbook.sheetnames)
            self.assertIn("布局位置", workbook.sheetnames)

    def test_all_export_tables_and_zip_assets_match_final_order(self):
        catalog = fixture()
        catalog["components"][0]["manufacturingSpec"] = {"material": "316L 不锈钢", "surfaceTreatment": "退磁、喷砂"}
        preview = aggregate(catalog, payload(checkout=checkout(plate=5, optic=2, bolt=30)))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "plate.step").write_bytes(b"STEP fixture")
            (root / "plate.pdf").write_bytes(b"PDF fixture")
            data, _, _ = export_result(preview, "bundle", root)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                config = json.loads(archive.read("套件配置.json"))
                self.assertEqual(config["checkout"], preview["checkout"])
                self.assertEqual(config["totals"]["componentQuantity"], 37)
                self.assertEqual(set(config["assets"]), {"plate"})
                self.assertEqual(len(config["fileChecksums"]), 2)
                self.assertTrue(all(path in archive.namelist() for path in config["assets"]["plate"].values()))
                for filename, sheet_name, qty, production in (("麓邦采购.xlsx", "麓邦采购", 2, False),
                                                             ("通用外购件.xlsx", "通用外购件", 30, False),
                                                             ("生产清单.xlsx", "生产清单", 5, True)):
                    workbook = load_workbook(io.BytesIO(archive.read(filename)))
                    if filename == "麓邦采购.xlsx":
                        self.assertEqual(workbook.sheetnames, ["Sheet1", "Sheet2", "Sheet3"])
                        self.assertEqual(workbook["Sheet1"]["B4"].value, "OPT-OLD")
                        self.assertEqual(workbook["Sheet1"]["C4"].value, qty)
                        self.assertEqual(workbook["Sheet1"]["C4"].data_type, "n")
                        continue
                    sheet = workbook[sheet_name]
                    self.assertEqual([cell.value for cell in sheet[5]], HEADERS + (["材料", "表面处理"] + MARKING_HEADERS if production else ["供应商"]))
                    self.assertEqual(sheet["E6"].value, qty)
                    self.assertEqual(sheet["E6"].data_type, "n")
                    self.assertEqual(sheet.auto_filter.ref, "A5:M6" if production else "A5:G6")
                    if production:
                        self.assertEqual(sheet["G6"].value, "316L 不锈钢")
                        self.assertEqual(sheet["H6"].value, "退磁、喷砂")
                    else:
                        self.assertEqual(sheet["G6"].value, "待确认")
                    for tab in workbook:
                        self.assertFalse({"状态", "来源套件与贡献数量", "备注", "来源链接", "STEP文件", "单件图纸"} & {cell.value for cell in tab[5]})


if __name__ == "__main__":
    unittest.main()
