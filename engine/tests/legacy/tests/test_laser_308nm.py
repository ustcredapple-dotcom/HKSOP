"""308 nm purchased laser: real catalog placement, accounting, and portable view."""
import base64
import copy
import io
import json
import math
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as ET
import zipfile

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bom import APIError, aggregate, load_catalog
from exports import export_result


class Laser308nmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog.json")
        cls.kit = next(k for k in cls.catalog["kits"] if k["id"] == "laser-308nm")
        cls.component = next(c for c in cls.catalog["components"] if c["id"] == "laser-308nm")

    def placement(self, pitch, rotation):
        # Put the first mounting hole on a real board hole near the board center.
        # This is deliberately independent of the browser's snapping algorithm.
        angle = math.radians(rotation)
        c, s = round(math.cos(angle)), round(math.sin(angle))
        dx, dy = 83.5, -125
        target = 12.5 + round((312.5 - 12.5) / pitch) * pitch
        pose = {"id": "laser-1", "kitId": "laser-308nm",
                "xMm": target - c * dx + s * dy,
                "yMm": target - s * dx - c * dy,
                "rotationDeg": rotation}
        # Whole-pitch translation preserves screw alignment while centering the housing.
        for coordinate in ("xMm", "yMm"):
            pose[coordinate] += round((312.5 - pose[coordinate]) / pitch) * pitch
        return {
            "layout": {
                "board": {"widthMm": 625, "heightMm": 625, "pitchMm": pitch,
                          "edgeOffsetMm": 12.5, "thicknessMm": 12.7, "holeType": "M6_through"},
                "instances": [pose],
            }
        }

    def test_catalog_registers_a_purchased_complete_laser_without_manufacturing_assets(self):
        self.assertEqual(self.kit["category"], "laser")
        self.assertEqual(self.kit["components"], [{"componentId": "laser-308nm", "quantity": 1}])
        self.assertEqual(self.component["kind"], "standard")
        self.assertEqual(self.component["unit"], "台")
        self.assertFalse(self.component["stepPath"])
        self.assertFalse(self.component["drawingPath"])
        self.assertNotIn("manufacturingSpec", self.component)
        self.assertTrue(self.kit["layout"]["placementAllowed"])
        self.assertEqual(self.kit["layout"]["minimumAlignedMountingHoles"], 2)

    def test_four_confirmed_mounting_offsets_and_optical_output_are_registered(self):
        geometry = self.kit["layout"]
        self.assertEqual({(h["xMm"], h["yMm"]) for h in geometry["mountingHoleOffsetsMm"]},
                         {(x, y) for x in (83.5, 133.5) for y in (-125, 125)})
        ports = geometry["opticalPortsMm"]
        self.assertEqual(len(ports), 1)
        for name, expected in {"id": "output", "xMm": -283, "yMm": 67,
                               "directionX": -1, "directionY": 0,
                               "wavelengthNm": 308.366, "beamHeightMm": 135}.items():
            self.assertEqual(ports[0][name], expected)
        self.assertRegex(geometry["note"], r"估|示意")

    def test_both_board_pitches_accept_all_quarter_turns_by_mounting_holes(self):
        for pitch in (12.5, 25):
            for rotation in (0, 90, 180, 270):
                with self.subTest(pitch=pitch, rotation=rotation):
                    data = self.placement(pitch, rotation)
                    pose = data["layout"]["instances"][0]
                    result = aggregate(self.catalog, data)
                    self.assertTrue(result["layoutValidation"]["valid"], result["layoutValidation"]["issues"])
                    self.assertEqual(result["standard"][0]["quantity"], 1)
                    self.assertTrue(all(row.get("generatedBoard") for row in result["manufacturing"]))
                    pose["xMm"] += 1
                    invalid = aggregate(self.catalog, data)["layoutValidation"]
                    self.assertFalse(invalid["valid"])
                    self.assertIn("mounting_mismatch", {issue["code"] for issue in invalid["issues"]})

    def test_two_aligned_holes_allow_31_25_pitch_at_every_quarter_turn(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                result = aggregate(self.catalog, self.placement(31.25, rotation))
                validation = result["layoutValidation"]
                self.assertTrue(validation["valid"], validation["issues"])
                record, = validation["mountingAlignment"]
                self.assertEqual((record["instanceId"], record["alignedCount"], record["totalCount"],
                                  record["requiredCount"], record["partial"]), ("laser-1", 2, 4, 2, True))
                self.assertEqual(len(record["alignedPositionsMm"]), 2)
                # The accepted layout must pass the same gate used for order export.
                _, mime, _ = export_result(result, "manufacturing", ROOT / "assets", ROOT / "static")
                self.assertIn("spreadsheetml", mime)

    def test_50_pitch_reports_four_aligned_holes_and_zero_one_hole_cases_fail(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                full = aggregate(self.catalog, self.placement(50, rotation))["layoutValidation"]
                self.assertTrue(full["valid"], full["issues"])
                self.assertEqual([(r["alignedCount"], r["totalCount"], r["requiredCount"], r["partial"])
                                  for r in full["mountingAlignment"]], [(4, 4, 2, False)])
        for pitch in (20, 100):
            with self.subTest(pitch=pitch):
                data = self.placement(pitch, 0)
                for dx, count in ((0, 1), (1, 0)):
                    data["layout"]["instances"][0]["xMm"] += dx
                    result = aggregate(self.catalog, data)
                    validation = result["layoutValidation"]
                    self.assertFalse(validation["valid"])
                    self.assertEqual(validation["mountingAlignment"][0]["alignedCount"], count)
                    self.assertEqual({issue["code"] for issue in validation["issues"]}, {"mounting_mismatch"})
                    with self.assertRaises(APIError) as error:
                        export_result(result, "manufacturing", ROOT / "assets", ROOT / "static")
                    self.assertEqual(error.exception.code, "layout_invalid")

    def test_minimum_rule_accepts_three_holes_without_relaxing_other_components(self):
        catalog = copy.deepcopy(self.catalog)
        laser = next(k for k in catalog["kits"] if k["id"] == "laser-308nm")
        laser["layout"]["mountingHoleOffsetsMm"][-1]["xMm"] += 1
        data = self.placement(25, 0)
        validation = aggregate(catalog, data)["layoutValidation"]
        self.assertTrue(validation["valid"], validation["issues"])
        self.assertEqual(validation["mountingAlignment"][0]["alignedCount"], 3)
        del laser["layout"]["minimumAlignedMountingHoles"]
        validation = aggregate(catalog, data)["layoutValidation"]
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["mountingAlignment"][0]["requiredCount"], 4)
        # An ordinary catalog PBS still needs all four screws, even though one fits.
        data = self.placement(50, 0)
        data["layout"]["instances"] = [{"id": "pbs", "kitId": "pbs-fixed", "xMm": 325,
                                        "yMm": 325, "rotationDeg": 0}]
        validation = aggregate(self.catalog, data)["layoutValidation"]
        self.assertFalse(validation["valid"])
        self.assertEqual([(r["alignedCount"], r["requiredCount"]) for r in validation["mountingAlignment"]], [(1, 4)])

    def test_duplicate_offsets_cannot_satisfy_minimum_two_distinct_holes(self):
        catalog = copy.deepcopy(self.catalog)
        geometry = next(k for k in catalog["kits"] if k["id"] == "laser-308nm")["layout"]
        geometry["mountingHoleOffsetsMm"] = [{"xMm": 83.5, "yMm": -125},
                                             {"xMm": 83.500001, "yMm": -125},
                                             {"xMm": 83.5, "yMm": -125}]
        validation = aggregate(catalog, self.placement(25, 0))["layoutValidation"]
        self.assertFalse(validation["valid"])
        self.assertEqual([(r["alignedCount"], r["totalCount"], r["requiredCount"])
                          for r in validation["mountingAlignment"]], [(1, 1, 2)])
        self.assertEqual({issue["code"] for issue in validation["issues"]}, {"mounting_mismatch"})

    def test_partial_alignment_does_not_relax_bounds_or_collision(self):
        data = self.placement(31.25, 0)
        pose = data["layout"]["instances"][0]
        pose["xMm"] -= 156.25
        validation = aggregate(self.catalog, data)["layoutValidation"]
        self.assertEqual(validation["mountingAlignment"][0]["alignedCount"], 2)
        self.assertFalse(validation["valid"])
        self.assertIn("out_of_bounds", {issue["code"] for issue in validation["issues"]})
        data = self.placement(31.25, 0)
        data["layout"]["instances"].append({**data["layout"]["instances"][0], "id": "laser-2"})
        validation = aggregate(self.catalog, data)["layoutValidation"]
        self.assertEqual([r["alignedCount"] for r in validation["mountingAlignment"]], [2, 2])
        self.assertFalse(validation["valid"])
        self.assertIn("collision", {issue["code"] for issue in validation["issues"]})

    def test_rotated_small_board_preserves_local_and_global_alignment_records(self):
        data = self.placement(31.25, 0)
        small = data["layout"]["board"]
        small["mountingHoles"] = [{"columnIndex": c, "rowIndex": r} for c in (0, 16) for r in (0, 16)]
        data["layout"]["board"] = {**small, "widthMm": 900, "heightMm": 900, "pitchMm": 25, "mountingHoles": []}
        data["layout"]["subBoards"] = [{"id": "module", "name": "激光器小板", "board": small,
                                         "xMm": 625, "yMm": 0, "rotationDeg": 90}]
        data["layout"]["instances"][0]["boardId"] = "module"
        validation = aggregate(self.catalog, data)["layoutValidation"]
        self.assertTrue(validation["valid"], validation["issues"])
        record, = validation["mountingAlignment"]
        self.assertEqual((record["boardId"], record["alignedCount"], record["requiredCount"], record["partial"]),
                         ("module", 2, 2, True))
        self.assertEqual(record["globalAlignedPositionsMm"],
                         [{"xMm": round(625-p["yMm"], 6), "yMm": p["xMm"]} for p in record["alignedPositionsMm"]])

    def test_quantity_and_download_keep_laser_out_of_custom_manufacturing(self):
        result = aggregate(self.catalog, {"items": [{"kitId": "laser-308nm", "quantity": 3}]})
        self.assertEqual(result["manufacturing"], [])
        self.assertEqual(result["lubang"], [])
        self.assertEqual([(r["componentId"], r["quantity"], r["unit"]) for r in result["standard"]],
                         [("laser-308nm", 3, "台")])
        content, mime, _ = export_result(result, "bundle", ROOT / "assets", ROOT / "static")
        self.assertEqual(mime, "application/zip")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertFalse(any(Path(name).suffix.lower() in {".step", ".stp", ".pdf"} for name in archive.namelist()))
            saved = json.loads(archive.read("套件配置.json"))
            self.assertEqual(saved["assets"], {})
            self.assertEqual([(r["componentId"], r["quantity"]) for r in saved["components"]], [("laser-308nm", 3)])
            workbook = load_workbook(io.BytesIO(archive.read("通用外购件.xlsx")), data_only=True)
            rows = list(workbook["通用外购件"].iter_rows(min_row=6, values_only=True))
            row = next(row for row in rows if row[1] == "laser-308nm")
            self.assertEqual((row[4], row[5]), (3, "台"))
            workbook.close()
            production = load_workbook(io.BytesIO(archive.read("生产清单.xlsx")), data_only=True)
            self.assertFalse(any(row[1] == "laser-308nm" for row in production["生产清单"].iter_rows(min_row=6, values_only=True)))
            production.close()

    def test_portable_top_view_contains_the_actual_optical_port_marker(self):
        result = aggregate(self.catalog, self.placement(25, 90))
        self.assertTrue(result["layoutValidation"]["valid"], result["layoutValidation"]["issues"])
        content, mime, _ = export_result(result, "layout-svg", ROOT / "assets", ROOT / "static")
        self.assertTrue(mime.startswith("image/svg+xml"))
        images = ET.fromstring(content).findall(".//{http://www.w3.org/2000/svg}image")
        self.assertEqual(len(images), 1)
        uri = images[0].get("{http://www.w3.org/1999/xlink}href")
        self.assertTrue(uri.startswith("data:image/svg+xml;base64,"))
        embedded = base64.b64decode(uri.split(",", 1)[1])
        self.assertEqual(embedded, (ROOT / "static" / self.kit["layout"]["topViewPath"]).read_bytes())
        drawing = ET.fromstring(embedded)
        self.assertIsNotNone(drawing.find(".//*[@id='optical-output-port'][@data-optical-port='output']"))
        text = " ".join(drawing.itertext())
        self.assertIn("光口", text)
        self.assertIn("308", text)
        self.assertEqual(result["layoutKitMetadata"]["laser-308nm"]["opticalPortsMm"][0]["beamHeightMm"], 135)


if __name__ == "__main__":
    unittest.main()
