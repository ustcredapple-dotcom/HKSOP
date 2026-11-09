"""Real 532 nm purchased-laser geometry, order classification, and portable view."""
import base64
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
from bom import aggregate, load_catalog
from exports import export_result


class Laser532nmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog.json")
        cls.kit = next(k for k in cls.catalog["kits"] if k["id"] == "laser-532nm")
        cls.component = next(c for c in cls.catalog["components"] if c["id"] == "laser-532nm")

    def placement(self, pitch, rotation, *, upper_pair=False):
        # Anchor a measured mounting hole, not the housing or picture centre.
        # The lower pair and right pair share a 25 mm phase; the upper pair does not.
        angle = math.radians(rotation)
        c, s = round(math.cos(angle)), round(math.sin(angle))
        dx, dy = -170, 155 if upper_pair else -155
        target = 12.5 + round((312.5 - 12.5) / pitch) * pitch
        pose = {"id": "green-laser", "kitId": "laser-532nm", "rotationDeg": rotation,
                "xMm": target - c * dx + s * dy,
                "yMm": target - s * dx - c * dy}
        for coordinate in ("xMm", "yMm"):
            pose[coordinate] += round((312.5 - pose[coordinate]) / pitch) * pitch
        return {"layout": {"board": {"widthMm": 625, "heightMm": 625, "pitchMm": pitch,
                                      "edgeOffsetMm": 12.5, "thicknessMm": 12.7,
                                      "holeType": "M6_through"}, "instances": [pose]}}

    def test_dimensions_and_source_port_follow_the_photographed_datums(self):
        geometry = self.kit["layout"]
        self.assertEqual({(h["xMm"], h["yMm"]) for h in geometry["mountingHoleOffsetsMm"]},
                         {(-170, 155), (-120, 155), (-170, -155), (-120, -155),
                          (205, -30), (205, 20)})
        self.assertEqual(geometry["mountingHoleRadiusMm"], 3.2)
        self.assertEqual(geometry["baseBoundsMm"],
                         {"xMin": -208, "xMax": 211, "yMin": -161, "yMax": 161})
        port, = geometry["opticalPortsMm"]
        for name, expected in {"id": "output", "xMm": -208, "yMm": 101,
                               "directionX": -1, "directionY": 0,
                               "wavelengthNm": 532.0002, "beamHeightMm": 95.7}.items():
            self.assertEqual(port[name], expected)
        self.assertEqual(geometry["opticalAxisHeightMm"], 95.7)
        self.assertTrue(geometry["placementAllowed"])
        self.assertEqual(geometry["minimumAlignedMountingHoles"], 2)
        self.assertRegex(geometry["note"], r"估|示意|推")

    def test_both_supported_pitches_accept_two_or_four_aligned_holes_after_rotation(self):
        for pitch in (12.5, 25):
            for rotation in (0, 90, 180, 270):
                for upper_pair, expected_count in ((False, 4), (True, 2)):
                    with self.subTest(pitch=pitch, rotation=rotation, upper_pair=upper_pair):
                        result = aggregate(self.catalog, self.placement(pitch, rotation, upper_pair=upper_pair))
                        validation = result["layoutValidation"]
                        self.assertTrue(validation["valid"], validation["issues"])
                        row, = validation["mountingAlignment"]
                        self.assertEqual((row["alignedCount"], row["totalCount"], row["requiredCount"], row["partial"]),
                                         (expected_count, 6, 2, True))
                        self.assertEqual(len(row["alignedPositionsMm"]), expected_count)

    def test_unsnapped_shift_is_invalid_at_every_quarter_turn(self):
        for pitch in (12.5, 25):
            for rotation in (0, 90, 180, 270):
                with self.subTest(pitch=pitch, rotation=rotation):
                    payload = self.placement(pitch, rotation)
                    payload["layout"]["instances"][0]["xMm"] += 1
                    validation = aggregate(self.catalog, payload)["layoutValidation"]
                    self.assertFalse(validation["valid"])
                    self.assertEqual(validation["mountingAlignment"][0]["alignedCount"], 0)
                    self.assertIn("mounting_mismatch", {issue["code"] for issue in validation["issues"]})

    def test_whole_laser_is_purchased_and_never_generates_a_custom_model_or_drawing(self):
        self.assertEqual(self.kit["category"], "laser")
        self.assertEqual(self.kit["components"], [{"componentId": "laser-532nm", "quantity": 1}])
        self.assertEqual((self.component["kind"], self.component["unit"]), ("standard", "台"))
        self.assertFalse(self.component.get("stepPath"))
        self.assertFalse(self.component.get("drawingPath"))
        self.assertNotIn("manufacturingSpec", self.component)
        result = aggregate(self.catalog, {"items": [{"kitId": "laser-532nm", "quantity": 3}]})
        self.assertEqual(result["manufacturing"], [])
        self.assertEqual(result["lubang"], [])
        self.assertEqual([(row["componentId"], row["quantity"]) for row in result["standard"]],
                         [("laser-532nm", 3)])
        content, mime, _ = export_result(result, "bundle", ROOT / "assets", ROOT / "static")
        self.assertEqual(mime, "application/zip")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertFalse(any(Path(name).suffix.lower() in {".step", ".stp", ".pdf"} for name in archive.namelist()))
            saved = json.loads(archive.read("套件配置.json"))
            self.assertEqual(saved["assets"], {})
            workbook = load_workbook(io.BytesIO(archive.read("通用外购件.xlsx")), data_only=True)
            try:
                row = next(row for row in workbook["通用外购件"].iter_rows(min_row=6, values_only=True)
                           if row[1] == "laser-532nm")
                self.assertEqual((row[4], row[5]), (3, "台"))
            finally:
                workbook.close()

    def test_exported_layout_embeds_the_registered_vector_view_and_port(self):
        result = aggregate(self.catalog, self.placement(25, 90))
        content, mime, _ = export_result(result, "layout-svg", ROOT / "assets", ROOT / "static")
        self.assertTrue(mime.startswith("image/svg+xml"))
        image, = ET.fromstring(content).findall(".//{http://www.w3.org/2000/svg}image")
        uri = image.get("{http://www.w3.org/1999/xlink}href")
        self.assertTrue(uri.startswith("data:image/svg+xml;base64,"))
        embedded = base64.b64decode(uri.split(",", 1)[1])
        self.assertEqual(embedded, (ROOT / "static" / self.kit["layout"]["topViewPath"]).read_bytes())
        drawing = ET.fromstring(embedded)
        self.assertIsNotNone(drawing.find(".//*[@id='optical-output-port'][@data-optical-port='output']"))
        labels = " ".join(drawing.itertext())
        self.assertIn("532", labels)
        self.assertIn("光口", labels)
        self.assertEqual(result["layoutKitMetadata"]["laser-532nm"]["opticalPortsMm"][0]["beamHeightMm"], 95.7)


if __name__ == "__main__":
    unittest.main()
