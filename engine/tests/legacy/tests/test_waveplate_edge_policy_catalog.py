"""Per-kit edge-mount policy is provenance, not altered CAD geometry or a global default."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("waveplate_policy_library", ROOT / "tools/library.py")
LIB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIB)
FLAG = "baseOverhangAllowedWithPartialMounting"


class WaveplateEdgePolicyCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = LIB.load_source(ROOT / "library")

    def layout(self, catalog):
        return next(kit for kit in catalog["kits"] if kit["id"] == "waveplate")["layout"]

    def test_policy_is_explicit_and_restricted_to_old_one_inch_double_waveplate(self):
        enabled = [kit["id"] for kit in self.catalog["kits"] if kit.get("layout", {}).get(FLAG) is True]
        self.assertEqual(enabled, ["waveplate"])
        geometry = self.layout(self.catalog)
        self.assertEqual(geometry["minimumAlignedMountingHoles"], 2)
        self.assertEqual(geometry["baseOverhangPolicySource"]["type"], "user-specified")
        self.assertEqual(geometry["baseOverhangPolicySource"]["confirmedAt"], "2026-10-06")
        for kit in self.catalog["kits"]:
            if kit["id"] in ("waveplate-single-05-m1", "waveplate-double-05-m1"):
                self.assertEqual(kit["layout"]["minimumAlignedMountingHoles"], 4)
                self.assertNotIn(FLAG, kit["layout"])
        LIB.validate_structure(self.catalog)

    def test_real_geometry_and_bom_are_not_shrunk_to_simulate_partial_support(self):
        kit = next(kit for kit in self.catalog["kits"] if kit["id"] == "waveplate")
        geometry = kit["layout"]
        self.assertEqual(geometry["baseBoundsMm"], {"xMin": -17.5, "yMin": -17.5, "xMax": 17.5, "yMax": 17.5})
        self.assertEqual({(h["xMm"], h["yMm"]) for h in geometry["mountingHoleOffsetsMm"]},
                         {(-12.5, -12.5), (-12.5, 12.5), (12.5, -12.5), (12.5, 12.5)})
        self.assertEqual(geometry["topViewPath"], "topviews/kit_waveplate.svg")
        self.assertEqual(geometry["collisionGeometryVersion"], "silhouette-2026-09-24.1")
        self.assertEqual(kit["components"], [{"componentId": "custom-01", "quantity": 1},
                                             {"componentId": "custom-07", "quantity": 1},
                                             {"componentId": "crm-1as", "quantity": 2}])

    def test_flag_is_strictly_boolean_even_for_unplaced_records(self):
        for placement in (True, False):
            for value in (None, 0, 1, "true", [], {}):
                with self.subTest(placement=placement, value=value):
                    catalog = copy.deepcopy(self.catalog)
                    geometry = self.layout(catalog)
                    geometry["placementAllowed"] = placement
                    geometry[FLAG] = value
                    with self.assertRaises(LIB.LibraryError):
                        LIB.validate_structure(catalog)

    def test_enabled_policy_requires_two_or_more_distinct_actual_mounting_holes(self):
        changes = [
            {"minimumAlignedMountingHoles": None}, {"minimumAlignedMountingHoles": True},
            {"minimumAlignedMountingHoles": 1}, {"minimumAlignedMountingHoles": 2.0},
            {"minimumAlignedMountingHoles": 5}, {"minimumAlignedMountingHoles": 129},
            {"mountingHoleOffsetsMm": None}, {"mountingHoleOffsetsMm": []},
            {"mountingHoleOffsetsMm": [{"xMm": 0, "yMm": 0}] * 2},
            {"mountingHoleOffsetsMm": [{"xMm": 0, "yMm": 0}, {"xMm": "25", "yMm": 0}]},
        ]
        for placement in (True, False):
            for change in changes:
                with self.subTest(placement=placement, change=change):
                    catalog = copy.deepcopy(self.catalog)
                    self.layout(catalog).update({"placementAllowed": placement, **change})
                    with self.assertRaises(LIB.LibraryError):
                        LIB.validate_structure(catalog)

    def test_false_or_omitted_flag_does_not_require_two_hole_exception_policy(self):
        for enabled in (False, None):
            catalog = copy.deepcopy(self.catalog)
            geometry = self.layout(catalog)
            if enabled is None:
                geometry.pop(FLAG)
            else:
                geometry[FLAG] = enabled
            geometry.pop("minimumAlignedMountingHoles")
            LIB.validate_structure(catalog)

    def test_machine_schema_declares_flag_type_and_conditional_minimum(self):
        schema = json.loads((ROOT / "library/schemas/kit.schema.json").read_text())
        layout = schema["properties"]["layout"]
        self.assertEqual(layout["properties"][FLAG]["type"], "boolean")
        self.assertEqual(layout["properties"]["minimumAlignedMountingHoles"]["type"], "integer")
        rule = next(row for row in layout["allOf"] if FLAG in row.get("if", {}).get("required", []))
        self.assertIs(rule["if"]["properties"][FLAG]["const"], True)
        self.assertIn("minimumAlignedMountingHoles", rule["then"]["required"])
        self.assertEqual(rule["then"]["properties"]["minimumAlignedMountingHoles"]["minimum"], 2)


if __name__ == "__main__":
    unittest.main()
