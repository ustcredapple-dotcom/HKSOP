"""Report-backed laser defaults must not invent geometry or an extra laser order.

Compare the published catalog to the separately transcribed report evidence and
the pre-change catalog, then exercise actual BOM/export and deployment guards.
No network, production state, source CAD or PDF files are changed by these tests.
"""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "data_evidence/lasers-2026-10-05"
sys.path.insert(0, str(ROOT))

from bom import APIError, aggregate, load_catalog
import deploy_support as deploy
from exports import export_result


def read(path):
    return json.loads(path.read_text())


def kit(catalog, kit_id):
    return next(row for row in catalog["kits"] if row["id"] == kit_id)


class LaserReportCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = read(ROOT / "catalog.json")
        cls.catalog = load_catalog(ROOT / "catalog.json")
        cls.before = read(EVIDENCE / "catalog-before.json")
        cls.audit = read(EVIDENCE / "report-audit/engineering-data.json")
        cls.main = kit(cls.raw, "laser-308nm")
        cls.seed = kit(cls.raw, "laser-ecdl-1030nm")

    def test_308_source_defaults_match_independently_audited_main_output(self):
        observed = self.main["layout"]["opticalDefaults"]["source"]
        report = self.main["layout"]["sourceReport"]
        audit = self.audit["main308"]
        expected = {
            "wavelengthNm": audit["wavelength"]["nominalCenterNm"]["value"],
            "powerMw": audit["power"]["mainOutput"]["value"],
            "beamDiameterMm": audit["summaryBeam"]["collimationDiameter"]["value"],
            "beamQualityM2": audit["summaryBeam"]["mSquared"]["value"],
            "polarizationType": audit["polarization"]["type"]["value"],
        }
        self.assertEqual(expected, {"wavelengthNm": 308.366, "powerMw": 118,
                                   "beamDiameterMm": 1.264, "beamQualityM2": 1.071,
                                   "polarizationType": "linear"})
        for name, value in expected.items():
            with self.subTest(field=name):
                self.assertEqual(observed[name], value)
                self.assertEqual(report["reportedParameters"][name], value)
        self.assertEqual(set(report["applyFields"]), set(expected))
        self.assertFalse(observed["enabled"], "New source defaults must not automatically turn emission on")
        self.assertEqual(report["reportId"], audit["identity"]["serialNumber"])
        self.assertEqual(observed["directionAngleDeg"], 180)

    def test_308_unknown_polarization_and_window_q_remain_disclosed_assumptions(self):
        layout = self.main["layout"]
        report = layout["sourceReport"]
        params = report["reportedParameters"]
        self.assertIsNone(params["axisRelativeToBoardDeg"])
        self.assertIsNone(params["windowWavefrontRadiusMm"])
        self.assertIsNone(layout["opticalDefaults"]["source"]["wavefrontRadiusMm"])
        self.assertEqual(params["extinctionRatioDb"], 23.7)
        self.assertEqual(params["beamDiameterDefinition"], "D4σ; Gaussian-equivalent simulation")
        notes = " ".join(report["simulationNotes"])
        self.assertIn("平波前", notes)
        self.assertIn("偏振角0°只是初始假设", notes)
        self.assertIn("不由它推断完整Stokes", notes)
        self.assertNotIn("polarizationAngleDeg", report["applyFields"])
        self.assertNotIn("wavefrontRadiusMm", report["applyFields"])

    def test_308_all_prior_placement_geometry_and_estimation_caveats_are_preserved(self):
        old = kit(self.before, "laser-308nm")["layout"]
        current = self.main["layout"]
        fields = ("topViewPath", "topViewUrl", "widthMm", "heightMm", "anchorXMm", "anchorYMm",
                  "baseBoundsMm", "collisionBoundsMm", "collisionPolygonsMm", "mountingHoleOffsetsMm",
                  "mountingHoleRadiusMm", "minimumAlignedMountingHoles", "placementAllowed",
                  "opticalAxisHeightMm", "collisionGeometryVersion")
        for field in fields:
            with self.subTest(field=field):
                self.assertEqual(current[field], old[field])
        # The calibrated spatial port is identical; only its wavelength metadata changes.
        old_ports = copy.deepcopy(old["opticalPortsMm"])
        new_ports = copy.deepcopy(current["opticalPortsMm"])
        for port in old_ports + new_ports:
            port.pop("wavelengthNm")
        self.assertEqual(new_ports, old_ports)
        self.assertEqual(new_ports, [{"id": "output", "xMm": -283, "yMm": 67,
                                     "directionX": -1, "directionY": 0, "beamHeightMm": 135}])
        for field, value in old["calibration"].items():
            with self.subTest(calibration=field):
                self.assertEqual(current["calibration"][field], value)
        self.assertTrue(current["calibration"]["manualVerification"]["estimatedDetailsRemainEstimated"])
        def geometry_tree(path):
            tree = ET.parse(path).getroot()
            for parent in tree.iter():
                for child in list(parent):
                    if child.tag.rsplit("}", 1)[-1] in ("title", "desc", "text"):
                        parent.remove(child)
                # Report wavelength and visible model labels intentionally changed;
                # keep every graphic path, dimension, transform and port coordinate.
                parent.attrib.pop("data-wavelength-nm", None)
                parent.text = None
                parent.tail = None
            return ET.tostring(tree)
        self.assertEqual(geometry_tree(ROOT / "static" / current["topViewPath"]),
                         geometry_tree(EVIDENCE / "laser-308nm-before.svg"))

    def test_report_files_are_the_audited_pdf_bytes_not_just_64_character_labels(self):
        audited = {row["id"]: row for row in self.audit["sources"]}
        reports = (self.main["layout"]["sourceReport"], self.seed["sourceReport"])
        self.assertEqual({r["id"] for r in reports[0]["sourceFiles"]}, {3, 4})
        self.assertEqual({r["id"] for r in reports[1]["sourceFiles"]}, {1, 2})
        for report in reports:
            for source in report["sourceFiles"]:
                with self.subTest(file=source["id"]):
                    path = (ROOT / source["path"]).resolve()
                    self.assertTrue(path.is_relative_to(EVIDENCE / "source"))
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source["sha256"])
                    self.assertEqual(source["sha256"], audited[source["id"]]["sha256"])
                    self.assertEqual(source["pages"], audited[source["id"]]["pages"])

    def test_ecdl_report_is_1030_nm_fiber_seed_not_308_nm_or_a_free_space_beam(self):
        reported = self.seed["sourceReport"]
        audit = self.audit["catEyeEcdl"]
        self.assertEqual(reported["reportId"], audit["identity"]["serialNumber"])
        self.assertEqual(reported["wavelengthNm"], audit["operatingWavelength"]["value"])
        point = next(p for p in audit["powerPoints"] if p["wavelengthNm"] == 1030)
        self.assertEqual(reported["powerMw"], point["powerMw"])
        self.assertEqual(reported["testCurrentMa"], point["driveCurrentMa"])
        self.assertEqual(reported["outputMode"], "FC/APC fiber")
        self.assertEqual(reported["polarizationType"], audit["polarization"]["type"]["value"])
        self.assertEqual(reported["extinctionRatioDb"], audit["polarization"]["extinctionRatioDb"]["value"])
        for key in ("beamDiameterMm", "beamQualityM2", "axisRelativeToBoardDeg"):
            self.assertIsNone(reported[key])

    def test_ecdl_thumbnail_cannot_supply_dummy_dimensions_or_an_optical_port(self):
        layout = self.seed["layout"]
        geometry = self.seed["geometryEvidence"]
        self.assertIs(layout["placementAllowed"], False)
        self.assertEqual(layout["geometryStatus"], "awaiting-dimensions")
        self.assertEqual(geometry["status"], "awaiting-dimensions")
        self.assertIs(geometry["calibrationVerified"], False)
        self.assertEqual(layout["opticalType"], "unsupported")
        self.assertIs(layout["opticalDatumVerified"], False)
        self.assertEqual(layout["opticalPortsMm"], [])
        for name in ("widthMm", "heightMm", "bodyHeightMm", "anchorXMm", "anchorYMm",
                     "baseBoundsMm", "collisionBoundsMm", "collisionPolygonsMm",
                     "mountingHoleOffsetsMm", "opticalPortPositionMm", "opticalAxisHeightMm"):
            with self.subTest(field=name):
                self.assertIsNone(layout.get(name))
                self.assertIsNone(geometry[name])
        self.assertNotIn("opticalDefaults", layout)
        xml = ET.parse(ROOT / "static" / layout["topViewPath"]).getroot()
        self.assertNotIn("mm", xml.attrib["width"])
        self.assertNotIn("mm", xml.attrib["height"])
        self.assertIn("尺寸待补", "".join(xml.itertext()))
        self.assertIn("控制机箱", "".join(xml.itertext()))

    def test_imported_ecdl_cannot_be_forced_onto_a_dimensioned_board(self):
        payload = {"layout": {
            "board": {"widthMm": 900, "heightMm": 625, "thicknessMm": 12.7,
                      "pitchMm": 25, "edgeOffsetMm": 12.5, "holeType": "M6_through"},
            "instances": [{"id": "seed", "kitId": self.seed["id"], "xMm": 300, "yMm": 300,
                           "rotationDeg": 0}],
        }}
        with self.assertRaises(APIError):
            aggregate(self.catalog, payload)

    def test_ecdl_reference_creates_no_purchase_or_manufacturing_item(self):
        self.assertEqual(self.seed["components"], [])
        self.assertEqual(self.seed["opticalSlots"], [])
        self.assertEqual(self.seed["bomPolicy"], "reference-only")
        self.assertNotIn(self.seed["id"], {c["id"] for c in self.raw["components"]})
        self.assertEqual({c["id"] for c in self.raw["components"]},
                         {c["id"] for c in self.before["components"]})
        result = aggregate(self.catalog, {"items": [{"kitId": self.seed["id"], "quantity": 1}]})
        for key in ("lubang", "standard", "manufacturing"):
            self.assertEqual(result[key], [])
        self.assertEqual(result["totals"]["componentQuantity"], 0)
        self.assertTrue(any(i["code"] == "reference_assembly" for g in result["reviewGroups"] for i in g["items"]))
        content = export_result(result, "bundle", ROOT / "assets", ROOT / "static")[0]
        report = deploy.verify_reference_assembly_package(self.seed, result, content)
        self.assertEqual(report["orderRows"], 0)
        self.assertEqual(report["manufacturingAssets"], 0)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertFalse(any(n.lower().endswith((".step", ".stp", ".pdf")) for n in archive.namelist()))

    def test_deployment_reference_exception_rejects_other_kits_orders_or_source_identity(self):
        self.assertTrue(deploy.registered_reference_assembly(self.seed))
        mutations = [
            ("id", "some-other-pending-laser"), ("bomPolicy", "normal"),
            ("releaseStage", "design-review"), ("bundleStatus", "complete"), ("bundleNote", ""),
            ("components", [{"componentId": "laser-308nm", "quantity": 1}]),
            ("opticalSlots", [{"id": "invented-purchase-slot"}]),
        ]
        for name, value in mutations:
            with self.subTest(field=name):
                changed = copy.deepcopy(self.seed); changed[name] = value
                self.assertFalse(deploy.registered_reference_assembly(changed))
        for name, value in (("reportId", "PLP-2026-03-007272-01"), ("outputMode", "free space"),
                            ("sourceFiles", [])):
            with self.subTest(report_field=name):
                changed = copy.deepcopy(self.seed); changed["sourceReport"][name] = value
                self.assertFalse(deploy.registered_reference_assembly(changed))

    def test_deployment_reference_exception_rejects_invented_geometry_or_emission(self):
        mutations = {
            "placementAllowed": True, "geometryStatus": "verified", "opticalType": "source",
            "opticalDatumVerified": True, "widthMm": 100, "heightMm": 100,
            "anchorXMm": 50, "anchorYMm": 50, "opticalAxisHeightMm": 63.5,
            "mountingHoleOffsetsMm": [{"xMm": 0, "yMm": 0}],
            "baseBoundsMm": {"xMin": 0, "yMin": 0, "xMax": 100, "yMax": 100},
            "collisionBoundsMm": {"xMin": 0, "yMin": 0, "xMax": 100, "yMax": 100},
            "collisionPolygonsMm": [[{"xMm": 0, "yMm": 0}, {"xMm": 100, "yMm": 0}, {"xMm": 0, "yMm": 100}]],
            "opticalPortsMm": [{"id": "output", "xMm": 0, "yMm": 0, "directionX": 1, "directionY": 0}],
            "opticalDefaults": {"elementType": "source", "source": {"enabled": True}},
        }
        for name, value in mutations.items():
            with self.subTest(field=name):
                changed = copy.deepcopy(self.seed); changed["layout"][name] = value
                self.assertFalse(deploy.registered_reference_assembly(changed))

    def test_deployment_reference_exception_is_tied_to_the_two_reviewed_report_hashes(self):
        for index in (0, 1):
            for value in ("not-a-sha", "0" * 64):
                with self.subTest(file=index, sha=value):
                    changed = copy.deepcopy(self.seed)
                    changed["sourceReport"]["sourceFiles"][index]["sha256"] = value
                    self.assertFalse(deploy.registered_reference_assembly(changed))
        changed = copy.deepcopy(self.seed)
        changed["sourceReport"]["sourceFiles"][1]["id"] = 1
        self.assertFalse(deploy.registered_reference_assembly(changed))


if __name__ == "__main__":
    unittest.main()
