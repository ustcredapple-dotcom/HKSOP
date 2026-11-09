"""Real-catalog regression for the user-authorized 0.5 inch base exclusion.

The snapshot records all component quantities before the change, excluding only
motor-bracket-23. It also records both unaffected 1 inch variants.
"""
import io
import json
import unittest
import zipfile
from pathlib import Path

from openpyxl import load_workbook

from bom import aggregate, load_catalog
from exports import export_result, safe_asset


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((Path(__file__).parent / "fixtures/motor_base_removal_bom.json").read_text())["expectedPerKit"]


class RealMotorBaseRemovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog.json")

    def test_quantities_and_bundle_exclude_only_requested_base(self):
        for kit_id, expected_per_kit in EXPECTED.items():
            with self.subTest(kit=kit_id):
                preview = aggregate(self.catalog, {"items": [{"kitId": kit_id, "quantity": 3}]})
                actual = {row["componentId"]: row["quantity"] for group in ("manufacturing", "lubang", "standard") for row in preview[group]}
                self.assertEqual(actual, {cid: qty * 3 for cid, qty in expected_per_kit.items()})
                self.assertNotIn("motor-bracket-23", actual)
                content, _, _ = export_result(preview, "bundle", ROOT / "assets", ROOT / "static")
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    self.assertFalse(any("motor-bracket-23" in name or "支架2-3" in name for name in archive.namelist()))
                    config = json.loads(archive.read("套件配置.json"))
                    self.assertNotIn("motor-bracket-23", {row["componentId"] for row in config["components"]})
                    workbook = load_workbook(io.BytesIO(archive.read("生产清单.xlsx")))
                production = {row[1].value: row[4].value for row in workbook["生产清单"].iter_rows(min_row=6)}
                self.assertEqual(production, {row["componentId"]: row["quantity"] for row in preview["manufacturing"]})
                breakdown = workbook["套件分解"]
                self.assertFalse(any(row[3].value == "motor-bracket-23" for row in breakdown.iter_rows(min_row=6)))

    def test_excluded_part_remains_registered_and_original_files_remain_available(self):
        component = next(c for c in self.catalog["components"] if c["id"] == "motor-bracket-23")
        for field in ("stepPath", "drawingPath"):
            self.assertTrue(safe_asset(ROOT / "assets", component[field], field).is_file())


if __name__ == "__main__":
    unittest.main()
