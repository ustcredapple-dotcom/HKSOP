"""Mounted light sources count every supporting hole in elevation purchases."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bom import load_catalog
from elevation import axis_validation, elevation_accessories, support_count


class Laser532ElevationTests(unittest.TestCase):
    def setUp(self):
        self.geometry = {"opticalAxisHeightMm": 95.7,
                         "opticalPortsMm": [{"wavelengthNm": 532}],
                         "minimumAlignedMountingHoles": 2}
        self.target = {"id": "green", "kitId": "laser-532nm", "elevationMm": 55.8}

    def test_all_matched_mounts_contribute_supports_with_two_minimum(self):
        for aligned, expected in [(0, 2), (1, 2), (2, 2), (4, 4), (6, 6)]:
            with self.subTest(aligned=aligned):
                self.assertEqual(support_count(self.target, self.geometry, {"alignedCount": aligned}), expected)
        self.target["elevationSupportCount"] = 3
        self.assertEqual(support_count(self.target, self.geometry, {"alignedCount": 6}), 3)

    def test_ordinary_optics_and_308_adapter_keep_existing_support_rules(self):
        self.assertEqual(support_count(self.target, {"minimumAlignedMountingHoles": 4}, {"alignedCount": 4}), 1)
        self.assertEqual(support_count(self.target, {"opticalPortsMm": [{}]}, {"alignedCount": 4}), 1)
        old = {"kitId": "laser-308nm", "laserAdapter": {"enabled": True}}
        self.assertEqual(support_count(old, self.geometry, {"alignedCount": 6}), 4)
        old["elevationSupportCount"] = 7
        self.assertEqual(support_count(old, self.geometry, {"alignedCount": 6}), 7)

    def test_material_rows_and_height_share_the_support_count(self):
        catalog = copy.deepcopy(load_catalog(ROOT / "catalog.json"))
        source = copy.deepcopy(next(k for k in catalog["kits"] if k["id"] == "laser-308nm"))
        source.update(id="test-mounted-532", name="532 nm laser", layout=self.geometry)
        catalog["kits"].append(source)
        self.target["kitId"] = source["id"]
        layout = {"board": {"thicknessMm": 12.7}, "instances": [self.target]}
        metadata = {source["id"]: self.geometry}
        for count in (2, 4, 6):
            with self.subTest(supports=count):
                alignment = [{"instanceId": "green", "alignedCount": count}]
                axes, issues = axis_validation(layout, metadata, alignment)
                self.assertEqual(issues, [])
                self.assertEqual(axes["axisHeights"][0]["effectiveAxisHeightMm"], 151.5)
                self.assertEqual(axes["axisHeights"][0]["elevationSupportCount"], count)
                groups, rows = elevation_accessories(catalog, layout, metadata, {"mountingAlignment": alignment})
                self.assertEqual(groups[0]["supportCount"], count)
                self.assertEqual([(r["componentId"], r["quantity"]) for r in rows],
                                 [("lbtek-op1-55b6", count), ("elevation-shim-0p8", count)])


if __name__ == "__main__":
    unittest.main()
