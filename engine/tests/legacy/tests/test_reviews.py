"""Reviews describe unresolved engineering inputs, while exports retain confirmed facts."""
import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from openpyxl import load_workbook

from bom import APIError, aggregate, build_review_groups, manufacturing_spec, validate_catalog
from exports import export_result
from test_backend import extra, fixture, payload
from test_layout import layout_fixture, request


def process_spec(material="316L 不锈钢", treatment="退磁、喷砂", **overrides):
    return {"material": material, "surfaceTreatment": treatment, "generalTolerance": "待确认",
            "roughness": "待确认", "threadClass": "待确认", "processDetails": "喷砂要求及退磁验收指标待确认",
            **overrides}


def review_items(preview, group_id):
    return next((g["items"] for g in preview["reviewGroups"] if g["id"] == group_id), [])


def pbs_catalog(layout=False):
    catalog = layout_fixture() if layout else fixture()
    optic = next(c for c in catalog["components"] if c["id"] == "optic")
    optic.update(model="PBS24-532-1", status="型号映射待确认", notes="原装配别名需映射厂商型号")
    catalog["kits"][0]["status"] = "型号待确认"
    catalog["kits"][0]["components"][1]["quantity"] = 1
    return catalog


class ReviewTests(unittest.TestCase):
    def test_confirmed_materials_do_not_create_unrequested_process_reviews(self):
        catalog = fixture()
        for component in catalog["components"][:2]:
            component["manufacturingSpec"] = process_spec()
            component["notes"] = "旧备注：材料、表面处理待确认；工艺待确认"
        preview = aggregate(catalog, payload())
        self.assertEqual(preview["warnings"], [])
        self.assertEqual(preview["reviewGroups"], [])
        self.assertEqual(preview["manufacturing"][0]["manufacturingSpec"]["material"], "316L 不锈钢")

    def test_internal_acceptance_details_do_not_create_extra_requirements(self):
        catalog = fixture()
        catalog["components"][0]["manufacturingSpec"] = process_spec(
            generalTolerance="测试已确认", roughness="测试已确认", threadClass="测试已确认")
        self.assertEqual(review_items(aggregate(catalog, payload()), "manufacture"), [])

    def test_repeated_unconfirmed_materials_are_one_compact_review(self):
        catalog = fixture()
        for component in catalog["components"][:2]:
            component["manufacturingSpec"] = process_spec("待确认", "待确认")
        preview = aggregate(catalog, payload())
        self.assertEqual(len(preview["warnings"]), 1)
        group = preview["reviewGroups"][0]
        self.assertEqual(group["id"], "manufacture")
        self.assertFalse(group["blocking"])
        self.assertEqual(group["blockedExports"], [])
        self.assertEqual(len(group["items"]), 1)
        item = group["items"][0]
        self.assertEqual(item["code"], "manufacturing_materials")
        self.assertEqual(item["componentIds"], ["plate", "bracket"])
        self.assertEqual(item["fields"], ["material", "surfaceTreatment"])

    def test_unconfirmed_material_is_not_inferred_from_name(self):
        catalog = fixture()
        catalog["components"][0]["name"] = "6061 不锈钢测试零件"
        catalog["components"][0]["manufacturingSpec"] = process_spec("待确认", "待确认")
        preview = aggregate(catalog, payload())
        item = review_items(preview, "manufacture")[0]
        self.assertEqual(item["fields"], ["material", "surfaceTreatment"])
        self.assertEqual(preview["manufacturing"][0]["manufacturingSpec"]["material"], "待确认")

    def test_explicit_pbs_selection_removes_resolved_alias_review(self):
        catalog = pbs_catalog()
        data = {"items": [{"kitId": "alpha", "quantity": 2}]}
        self.assertEqual(len(review_items(aggregate(catalog, data), "procurement")), 1)
        data["extras"] = [extra(kitId="alpha", slotId="mirror", quantity=1, model="PBS24-532")]
        preview = aggregate(catalog, data)
        self.assertEqual({r["model"]: r["quantity"] for r in preview["lubang"]}, {"PBS24-532": 2})
        self.assertEqual(review_items(preview, "procurement"), [])
        self.assertFalse(any("型号" in warning for warning in preview["warnings"]))

    def test_partial_instance_selection_keeps_only_unresolved_alias(self):
        catalog = pbs_catalog(layout=True)
        data = request()
        data["layout"]["instances"] = data["layout"]["instances"][:2]
        data["extras"] = [extra(kitId="alpha", instanceId="a1", slotId="mirror", quantity=1, model="PBS24-532")]
        preview = aggregate(catalog, data)
        self.assertEqual({r["model"]: r["quantity"] for r in preview["lubang"]}, {"PBS24-532-1": 1, "PBS24-532": 1})
        self.assertEqual(len(review_items(preview, "procurement")), 1)
        self.assertEqual(review_items(preview, "procurement")[0]["componentIds"], ["optic"])
        data["extras"].append(extra("second", kitId="alpha", instanceId="a2", slotId="mirror", quantity=1, model="PBS24-780"))
        self.assertEqual(review_items(aggregate(catalog, data), "procurement"), [])

    def test_source_reviews_are_grouped_and_missing_files_are_only_bundle_blocker(self):
        catalog = fixture()
        for component in catalog["components"][:2]:
            component.update(status="几何已配对", notes="源文件版本与原装配对应待核对")
        catalog["components"][0]["stepPath"] = None
        catalog["components"][1]["notes"] += "；参考图尺寸未全部标完"
        preview = aggregate(catalog, payload())
        self.assertEqual(len(preview["warnings"]), 1)
        source = preview["reviewGroups"][0]
        by_code = {i["code"]: i for i in source["items"]}
        self.assertEqual(set(by_code), {"source_file_missing", "source_version", "drawing_incomplete"})
        self.assertEqual(by_code["source_version"]["componentIds"], ["plate", "bracket"])
        self.assertTrue(source["blocking"])
        self.assertEqual(source["blockedExports"], ["bundle"])
        self.assertEqual([i["code"] for i in source["items"] if i["blocking"]], ["source_file_missing"])
        # Restoring any registered part works generically, without a kit-ID exception.
        catalog["components"][0]["stepPath"] = "restored-original.step"
        restored = aggregate(catalog, payload())
        self.assertFalse(restored["reviewGroups"][0]["blocking"])
        self.assertNotIn("source_file_missing", {i["code"] for i in review_items(restored, "sourceFiles")})

    def test_unknown_procurement_model_still_requires_review(self):
        catalog = fixture()
        catalog["components"][2].update(model="", status="已建模")
        preview = aggregate(catalog, payload())
        self.assertEqual(review_items(preview, "procurement")[0]["code"], "procurement_model")
        self.assertFalse(preview["reviewGroups"][0]["blocking"])

    def test_legacy_confirmed_rows_remain_compatible(self):
        preview = aggregate(fixture(), payload())
        self.assertEqual(preview["reviewGroups"], [])
        self.assertEqual(preview["warnings"], [])

    def test_invalid_manufacturing_fields_rejected(self):
        for bad in ([], {"material": 316}, {"processDetails": ["test"]}, {"roughness": True}):
            catalog = fixture()
            catalog["components"][0]["manufacturingSpec"] = bad
            with self.subTest(bad=bad), self.assertRaises(APIError):
                validate_catalog(catalog)

    def test_spec_priority_only_presents_requested_material_and_treatment(self):
        self.assertEqual(manufacturing_spec({"boardSpec": {"material": "6061 铝合金"}})["material"], "6061 铝合金")
        row = {"boardSpec": {"material": "old", "manufacturingSpec": {"material": "nested"}},
               "manufacturingSpec": {"material": "explicit", "surfaceRoughness": "test-Ra"}}
        self.assertEqual(manufacturing_spec(row)["material"], "explicit")
        self.assertEqual(set(manufacturing_spec(row)), {"material", "surfaceTreatment"})


class ReviewExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for cid in ("plate", "bracket"):
            (self.root / f"{cid}.step").write_bytes(b"test-step")
            (self.root / f"{cid}.pdf").write_bytes(b"test-pdf")
        self.catalog = fixture()
        for component in self.catalog["components"][:2]:
            component["manufacturingSpec"] = process_spec()

    def tearDown(self):
        self.temp.cleanup()

    def test_production_workbook_and_zip_keep_confirmed_specs_and_concise_reviews(self):
        self.catalog["components"][2]["model"] = ""
        preview = aggregate(self.catalog, payload())
        data, _, _ = export_result(preview, "bundle", self.root)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            config = json.loads(archive.read("套件配置.json"))
            self.assertEqual(config["reviewGroups"], preview["reviewGroups"])
            self.assertEqual(len(config["warnings"]), 1)
            workbook = load_workbook(io.BytesIO(archive.read("生产清单.xlsx")))
        sheet = workbook["生产清单"]
        self.assertTrue(config["assets"]["plate"]["step"].startswith("自制件/"))
        self.assertTrue(config["assets"]["plate"]["drawing"].endswith(".pdf"))
        self.assertEqual(sheet["G5"].value, "材料")
        self.assertEqual(sheet["G6"].value, "316L 不锈钢")
        self.assertEqual(sheet["H6"].value, "退磁、喷砂")
        self.assertEqual(sheet.max_column, 8)
        self.assertNotIn("通用公差", [cell.value for cell in sheet[5]])
        self.assertNotIn("粗糙度", [cell.value for cell in sheet[5]])
        review = workbook["待确认项目"]
        self.assertEqual(review.max_row, 6)
        self.assertIn("厂商型号待确认", review["B6"].value)
        self.assertIn("不影响下载", review["E6"].value)

    def test_missing_file_still_allows_review_workbooks_but_rejects_bundle(self):
        self.catalog["components"][0]["stepPath"] = None
        preview = aggregate(self.catalog, payload())
        for kind in ("lubang", "manufacturing"):
            data, _, _ = export_result(preview, kind, self.root)
            self.assertGreater(len(data), 1000)
        with self.assertRaises(APIError) as caught:
            export_result(preview, "bundle", self.root)
        self.assertEqual(caught.exception.code, "asset_missing")

    def test_generated_board_values_used_in_both_production_and_board_spec_sheets(self):
        data = request()
        data["layout"]["instances"] = []
        preview = aggregate(layout_fixture(), data)
        board = preview["manufacturing"][0]
        self.assertEqual(review_items(preview, "sourceFiles"), [])
        # Stored generation specification is authoritative, independent of policy reloads.
        board.pop("manufacturingSpec", None)
        board["boardSpec"].update(process_spec("6061 铝合金", "黑色阳极氧化",
                                              processDetails="氧化膜厚及遮蔽部位待确认"))
        exported, _, _ = export_result(preview, "manufacturing", self.root)
        workbook = load_workbook(io.BytesIO(exported))
        sheet = workbook["生产清单"]
        self.assertEqual(sheet["G6"].value, "6061 铝合金")
        self.assertEqual(sheet["H6"].value, "黑色阳极氧化")
        values = {row[0].value: row[1].value for row in workbook["面包板规格"].iter_rows(min_row=6)}
        self.assertEqual(values["材料"], "6061 铝合金")
        self.assertEqual(values["表面处理"], "黑色阳极氧化")
        self.assertNotIn("通用公差", values)
        self.assertNotIn("粗糙度", values)
        self.assertNotIn("工艺补充要求", values)


if __name__ == "__main__":
    unittest.main()
