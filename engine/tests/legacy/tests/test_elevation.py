"""Real height contracts, catalog-only extra materials, and account/export persistence."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import PUBLIC_STATIC_FILES
from bom import APIError, aggregate, load_catalog, validate_catalog
from cart import CartStore
from elevation import decompose_height, validate_materials
from exports import export_result
from layout import layout_json, validate_layout
from shared_kits import Identity, SharedKitStore, project_payload
from test_layout import layout_fixture, request
from test_shared_kits import project


def board(width=1100, height=625, pitch=25):
    return {"widthMm": width, "heightMm": height, "pitchMm": pitch, "edgeOffsetMm": 12.5,
            "thicknessMm": 12.7, "holeType": "M6_through", "mountingHoles": []}


def arrangement(*, small=False, raised=False):
    laser = {"id": "laser", "kitId": "laser-308nm", "xMm": 304, "yMm": 312.5, "rotationDeg": 0}
    ordinary = {"id": "optic", "kitId": "pbs-fixed", "xMm": 800, "yMm": 300, "rotationDeg": 0}
    result = {"board": board(), "instances": [laser, ordinary]}
    if small:
        ordinary.update(boardId="small", xMm=75, yMm=75)
        plate = {"id": "small", "name": "光学模块", "board": board(200, 150, 12.5), "xMm": 800, "yMm": 0, "rotationDeg": 0}
        plate["board"]["mountingHoles"] = [{"columnIndex": x, "rowIndex": y} for x in (0, 14) for y in (0, 10)]
        result["subBoards"] = [plate]
        if raised:
            plate["elevationMm"] = 58.8
    elif raised:
        ordinary["elevationMm"] = 71.5
    return result


class ElevationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog.json")
        cls.materials = validate_materials(cls.catalog)

    def test_real_catalog_keeps_new_parts_available_and_original_kit_bom_unchanged(self):
        self.assertIn("elevation.js", PUBLIC_STATIC_FILES)
        self.assertEqual(len(self.catalog["elevationMaterials"]["posts"]), 20)
        components = {c["id"]: c for c in self.catalog["components"]}
        for kind in ("posts", "spacers"):
            for material in self.materials[kind]:
                self.assertEqual(components[material["componentId"]]["kind"], "lubang")
                self.assertFalse(components[material["componentId"]]["stepPath"])
        for kit in self.catalog["kits"]:
            self.assertFalse(any(line["componentId"].startswith("lbtek-op1-") for line in kit["components"]),
                             "new elevation materials must not be silently inserted into original kit BOM")

    def test_tenths_decomposition_is_exact_longest_post_first_and_deterministic(self):
        expected = {
            71.5: [("lbtek-op1-70b6", 1), ("lbtek-op1-1c", 1), ("elevation-shim-0p5", 1)],
            58.8: [("lbtek-op1-55b6", 1), ("lbtek-op1-3c", 1), ("elevation-shim-0p8", 1)],
            12.7: [("lbtek-op1-12p5b6", 1), ("elevation-shim-0p2", 1)],
            1000: [("lbtek-op1-500b6", 2)],
            0: [],
        }
        for value, pairs in expected.items():
            with self.subTest(height=value):
                before = copy.deepcopy(self.materials)
                result = decompose_height(value, self.materials)
                self.assertEqual([(r["componentId"], r["quantityPerSupport"]) for r in result], pairs)
                self.assertEqual(sum(round(r["heightMm"]*10)*r["quantityPerSupport"] for r in result), round(value*10))
                self.assertEqual(self.materials, before)
        for tenth in range(1, 10):
            row, = decompose_height(tenth/10, self.materials)
            self.assertEqual((row["componentId"], row["quantityPerSupport"]), (f"elevation-shim-0p{tenth}", 1))

    def test_real_axis_mismatch_blocks_export_and_raises_only_added_support_height(self):
        unraised = aggregate(self.catalog, {"layout": arrangement()})
        validation = unraised["layoutValidation"]
        self.assertEqual(validation["axisHeightReferenceMm"], 135)
        self.assertEqual([r["effectiveAxisHeightMm"] for r in validation["axisHeights"]], [135, 63.5])
        self.assertEqual({i["code"] for i in validation["issues"]}, {"axis_height_mismatch"})
        with self.assertRaises(APIError) as error:
            export_result(unraised, "manufacturing", ROOT / "assets", ROOT / "static")
        self.assertEqual(error.exception.code, "layout_invalid")
        raised = aggregate(self.catalog, {"layout": arrangement(small=True, raised=True)})
        self.assertTrue(raised["layoutValidation"]["valid"], raised["layoutValidation"]["issues"])
        self.assertEqual([r["effectiveAxisHeightMm"] for r in raised["layoutValidation"]["axisHeights"]], [135, 135])
        support, = raised["elevationAccessories"]
        self.assertEqual((support["targetType"], support["supportCount"], support["elevationMm"]), ("board", 4, 58.8))
        self.assertEqual({r["model"]: r["quantity"] for r in raised["lubang"] if r["model"].startswith("OP1-")}, {"OP1-55B6": 4, "OP1-3C": 4})
        self.assertEqual(next(r for r in raised["standard"] if r["componentId"] == "elevation-shim-0p8")["quantity"], 4)
        self.assertEqual([(r["componentId"], r["quantity"]) for r in raised["manufacturing"] if not r.get("generatedBoard")],
                         [(r["componentId"], r["quantity"]) for r in unraised["manufacturing"] if not r.get("generatedBoard")])

    def test_small_board_elevation_and_thickness_count_once_but_root_thickness_never_counts(self):
        raw = arrangement(small=True, raised=True)
        raw["board"]["thicknessMm"] = 30
        before = copy.deepcopy(raw)
        result = aggregate(self.catalog, {"layout": raw})
        self.assertEqual(raw, before)
        self.assertTrue(result["layoutValidation"]["valid"], result["layoutValidation"]["issues"])
        optic = next(r for r in result["layoutValidation"]["axisHeights"] if r["instanceId"] == "optic")
        self.assertEqual((optic["opticalAxisHeightMm"], optic["boardElevationMm"], optic["boardThicknessMm"],
                          optic["elevationMm"], optic["effectiveAxisHeightMm"]), (63.5, 58.8, 12.7, 0, 135))
        group, = result["elevationAccessories"]
        self.assertEqual((group["targetType"], group["targetId"], group["supportCount"]), ("board", "small", 4))
        self.assertEqual([(r["model"], r["quantity"]) for r in group["materials"]], [("OP1-55B6", 4), ("OP1-3C", 4), ("待确认", 4)])
        raw["subBoards"][0]["elevationMm"] = 20
        raw["instances"][1].update(elevationMm=38.8, elevationSupportCount=2)
        combined = aggregate(self.catalog, {"layout": raw})
        self.assertTrue(combined["layoutValidation"]["valid"], combined["layoutValidation"]["issues"])
        self.assertEqual([(r["elevationMm"], r["supportCount"]) for r in combined["elevationAccessories"]], [(20, 4), (38.8, 2)])

    def test_default_laser_support_count_follows_matching_holes_and_explicit_count_overrides(self):
        for pitch, x, y, expected in ((25, 304, 312.5, 4), (31.25, 304, 325, 2)):
            with self.subTest(pitch=pitch):
                raw = {"board": board(625, 625, pitch), "instances": [{"id": "laser", "kitId": "laser-308nm", "xMm": x, "yMm": y, "rotationDeg": 0, "elevationMm": 10}]}
                result = aggregate(self.catalog, {"layout": raw})
                self.assertTrue(result["layoutValidation"]["valid"], result["layoutValidation"]["issues"])
                group, = result["elevationAccessories"]
                self.assertEqual(group["supportCount"], expected)
                self.assertEqual(group["materials"][0]["quantity"], expected)
                raw["instances"][0]["elevationSupportCount"] = 3
                group, = aggregate(self.catalog, {"layout": raw})["elevationAccessories"]
                self.assertEqual(group["materials"][0]["quantity"], 3)
        raw = arrangement(small=True, raised=True)
        raw["subBoards"][0]["board"]["mountingHoles"] = []
        self.assertEqual(aggregate(self.catalog, {"layout": raw})["elevationAccessories"][0]["supportCount"], 4)

    def test_optional_fields_round_trip_and_invalid_precision_or_support_counts_fail(self):
        for owner in ("instance", "board"):
            for field, values in (("elevationMm", (-.1, 1000.1, .01, True, "20", None, float("inf"))),
                                  ("elevationSupportCount", (0, 129, 1.5, True, "4", None))):
                for value in values:
                    with self.subTest(owner=owner, field=field, value=value):
                        raw = arrangement(small=True)
                        target = raw["instances"][1] if owner == "instance" else raw["subBoards"][0]
                        target[field] = value
                        with self.assertRaises(APIError) as error:
                            aggregate(self.catalog, {"layout": raw})
                        self.assertEqual(error.exception.code, "invalid_elevation")
        result = aggregate(self.catalog, {"layout": arrangement(small=True, raised=True)})
        again = aggregate(self.catalog, json.loads(layout_json(result)))
        self.assertEqual(again["layout"], result["layout"])
        self.assertEqual(again["elevationAccessories"], result["elevationAccessories"])
        self.assertEqual(again["totals"], result["totals"])
        self.assertNotIn("elevationMm", again["layout"]["instances"][0])

    def test_unknown_axes_are_excluded_and_forged_validation_or_materials_are_not_trusted(self):
        catalog = layout_fixture()
        catalog["kits"][0]["layout"]["opticalAxisHeightMm"] = 63.5
        result = aggregate(catalog, request())
        self.assertTrue(result["layoutValidation"]["valid"])
        self.assertEqual([r["effectiveAxisHeightMm"] for r in result["layoutValidation"]["axisHeights"]], [63.5, 63.5, None])
        forged = {"layout": arrangement(), "layoutValidation": {"valid": True, "axisHeightReferenceMm": 1, "axisHeights": []}}
        self.assertFalse(aggregate(self.catalog, forged)["layoutValidation"]["valid"])
        with self.assertRaises(APIError) as error:
            aggregate(self.catalog, {"layout": arrangement(raised=True), "elevationAccessories": []})
        self.assertEqual(error.exception.code, "invalid_request")

    def test_material_catalog_references_and_steps_are_verified(self):
        for change in (lambda c: c["elevationMaterials"]["posts"][0].update(componentId="missing"),
                       lambda c: c["elevationMaterials"]["posts"][0].update(heightMm=.05),
                       lambda c: c["elevationMaterials"]["posts"].append(c["elevationMaterials"]["posts"][0]),
                       lambda c: c["elevationMaterials"]["fractionalShim"].update(kind="custom")):
            bad = copy.deepcopy(self.catalog)
            change(bad)
            with self.assertRaises(APIError) as error:
                validate_catalog(bad)
            self.assertEqual(error.exception.code, "catalog_invalid")

    def test_spreadsheets_and_package_preserve_height_and_additional_material_records(self):
        result = aggregate(self.catalog, {"layout": arrangement(small=True, raised=True)})
        content, _, _ = export_result(result, "manufacturing", ROOT / "assets", ROOT / "static")
        wb = load_workbook(io.BytesIO(content), data_only=True)
        self.assertIn("光轴高度", wb.sheetnames)
        self.assertIn("垫高材料", wb.sheetnames)
        self.assertEqual(wb["光轴高度"]["J7"].value, 135)
        self.assertEqual(wb["垫高材料"]["E6"].value, 58.8)
        wb.close()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "board.step").write_bytes(b"test board")
            (root / "board.pdf").write_bytes(b"test drawing")
            from breadboard import board_specs
            def generated(board, cache):
                return {"componentId": board_specs(board)["componentId"], "step": root / "board.step", "drawing": root / "board.pdf"}
            with patch.dict("os.environ", {"ZZLAB_BOARD_CACHE": temp}), patch("breadboard.ensure_board_artifacts", side_effect=generated):
                content, _, _ = export_result(result, "bundle", ROOT / "assets", ROOT / "static")
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                saved = json.loads(archive.read("套件配置.json"))
                self.assertEqual(saved["elevationAccessories"], result["elevationAccessories"])
                self.assertEqual(saved["layoutValidation"]["axisHeightReferenceMm"], 135)
                self.assertTrue(any(c["componentId"] == "elevation-shim-0p8" for c in saved["components"]))

    def test_cart_persists_and_exports_extra_materials_with_source_height_records(self):
        with tempfile.TemporaryDirectory() as temp:
            cart = CartStore(SharedKitStore(Path(temp) / "cart.sqlite3"))
            user = Identity("test-elevation-user", "高度测试", "user")
            empty = cart.read(user)
            source = {"layout": arrangement(small=True, raised=True)}
            added = cart.add(user, {"cartId": empty["cartId"], "revision": empty["revision"], "requestId": "height-test-0001", "name": "激光等高方案", "payload": source}, self.catalog)
            source["layout"]["instances"][1]["elevationMm"] = 0
            exported = cart.for_export(user, {"cartId": added["cartId"], "revision": added["revision"]}, self.catalog)
            self.assertEqual(next(r for r in exported["lubang"] if r["model"] == "OP1-55B6")["quantity"], 4)
            self.assertEqual(next(r for r in exported["standard"] if r["sourceComponentId"] == "elevation-shim-0p8")["quantity"], 4)
            self.assertEqual(exported["cartSources"][0]["elevationAccessories"][0]["elevationMm"], 58.8)
            content, _, _ = export_result(exported, "manufacturing", ROOT / "assets", ROOT / "static")
            wb = load_workbook(io.BytesIO(content), data_only=True)
            self.assertEqual(wb["垫高材料"]["E6"].value, 58.8)
            wb.close()

    def test_portable_module_height_metadata_is_validated_but_inactive_at_root(self):
        p = project()
        p["metadata"]["moduleElevation"] = {"elevationMm": 58.8, "elevationSupportCount": 4}
        catalog = layout_fixture()
        result = aggregate(catalog, project_payload(p, catalog))
        self.assertEqual(result["elevationAccessories"], [])
        self.assertEqual(p["metadata"]["moduleElevation"]["elevationMm"], 58.8)
        for value in ({"heightMm": 20}, {"elevationMm": .01}, {"elevationSupportCount": 0}, None, []):
            bad = copy.deepcopy(p)
            bad["metadata"]["moduleElevation"] = value
            with self.assertRaises(APIError):
                project_payload(bad, catalog)


if __name__ == "__main__":
    unittest.main()
