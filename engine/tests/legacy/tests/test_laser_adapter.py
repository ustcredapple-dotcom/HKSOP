"""Server-derived adapter geometry, beam row/column rules, and manufacturing BOM."""
import copy
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bom import APIError, aggregate, load_catalog
from laser_adapter import choose_board_holes, normalize_settings, validate_adapter_spec


def board(width=625, height=625, pitch=25):
    return {"widthMm": width, "heightMm": height, "pitchMm": pitch, "edgeOffsetMm": 12.5,
            "thicknessMm": 12.7, "holeType": "M6_through", "mountingHoles": []}


def laser(rotation=0, iid="laser"):
    xy = {0:(304,245.5), 90:(379.5,312.5), 180:(312.5,379.5), 270:(245.5,312.5)}[rotation]
    return {"id": iid, "kitId": "laser-308nm", "xMm": xy[0], "yMm": xy[1], "rotationDeg": rotation,
            "laserAdapter": {"enabled": True, "thicknessMm": 17.4}}


def plan(pitch=25, rotation=0):
    return {"layout": {"board": board(pitch=pitch), "instances": [laser(rotation)]}}


class LaserAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog.json")

    def test_server_infers_four_thread_holes_four_counterbores_and_152_4_axis(self):
        data = plan()
        original = copy.deepcopy(data)
        result = aggregate(self.catalog, data)
        validation = result["layoutValidation"]
        self.assertTrue(validation["valid"], validation["issues"])
        self.assertEqual(data, original, "backend must never silently relocate the laser")
        record, = validation["laserAdapters"]
        spec = record["spec"]
        self.assertEqual(validate_adapter_spec(spec), spec)
        self.assertEqual(record["beamPortMm"], {"xMm": 21, "yMm": 312.5})
        self.assertEqual(validation["mountingAlignment"][0]["alignedCount"], 4)
        self.assertEqual(validation["axisHeights"][0]["adapterThicknessMm"], 17.4)
        self.assertEqual(validation["axisHeights"][0]["effectiveAxisHeightMm"], 152.4)
        self.assertEqual(result["elevationAccessories"], [], "adapter thickness must never become OP1 support material")
        self.assertEqual(spec["outlineBoundsMm"], {"xMin": -283, "xMax": 260, "yMin": -130.5, "yMax": 130.5})
        self.assertEqual({(p["xMm"], p["yMm"]) for p in spec["laserThreadHolesMm"]}, {(x,y) for x in (83.5,133.5) for y in (-125,125)})
        self.assertEqual(spec["counterbore"], {"clearanceDiameterMm":6.6,"diameterMm":11,"depthMm":6.5})
        self.assertEqual(spec["thread"]["stepDiameterMm"], 5)
        self.assertEqual(spec["axisHeightMm"], 152.4)

    def test_metric_height_targets_and_legacy_manual_plates_remain_distinct_explicit_geometry(self):
        for thickness, axis in ((15, 150), (17.4, 152.4), (21.3, 156.3), (8.5, 143.5)):
            with self.subTest(thickness=thickness):
                data = plan()
                data["layout"]["instances"][0]["laserAdapter"]["thicknessMm"] = thickness
                original = copy.deepcopy(data)
                result = aggregate(self.catalog, data)
                spec = validate_adapter_spec(result["layoutValidation"]["laserAdapters"][0]["spec"])
                self.assertEqual(data, original, "explicit old or manual plate values must not be snapped")
                self.assertEqual(spec["opticalAxisHeightMm"], 135)
                self.assertEqual(spec["thicknessMm"], thickness)
                self.assertEqual(spec["axisHeightMm"], axis)
                self.assertEqual(result["layoutValidation"]["axisHeights"][0]["effectiveAxisHeightMm"], axis)
                row, = [r for r in result["manufacturing"] if r.get("generatedLaserAdapter")]
                self.assertEqual(row["adapterSpec"]["thicknessMm"], thickness)

    def test_all_rotations_and_both_board_pitches_keep_four_corner_clearance_and_25mm_phase(self):
        for pitch in (12.5, 25):
            for rotation in (0, 90, 180, 270):
                with self.subTest(pitch=pitch, rotation=rotation):
                    result = aggregate(self.catalog, plan(pitch, rotation))
                    self.assertTrue(result["layoutValidation"]["valid"], result["layoutValidation"]["issues"])
                    record, = result["layoutValidation"]["laserAdapters"]
                    spec = validate_adapter_spec(record["spec"])
                    holes, threads, bounds = spec["boardMountingHolesMm"], spec["laserThreadHolesMm"], spec["outlineBoundsMm"]
                    self.assertEqual(len(holes), 4)
                    self.assertEqual(len({(h["xMm"] > -11.5, h["yMm"] > 0) for h in holes}), 4)
                    for index, h in enumerate(holes):
                        self.assertGreaterEqual(min(h["xMm"]-bounds["xMin"],bounds["xMax"]-h["xMm"],h["yMm"]-bounds["yMin"],bounds["yMax"]-h["yMm"]), 7.5-1e-5)
                        self.assertTrue(all(math.hypot(h["xMm"]-t["xMm"],h["yMm"]-t["yMm"]) >= 10.5-1e-5 for t in threads))
                        for prior in holes[:index]:
                            self.assertGreaterEqual(math.hypot(h["xMm"]-prior["xMm"],h["yMm"]-prior["yMm"]), 13-1e-5)
                            for field in ("xMm", "yMm"):
                                d = (h[field]-prior[field])/25
                                self.assertAlmostEqual(d, round(d), places=6)
                    for h in result["layoutValidation"]["mountingAlignment"][0]["alignedPositionsMm"]:
                        for field in ("xMm", "yMm"):
                            n = (h[field]-12.5)/pitch
                            self.assertAlmostEqual(n, round(n), places=6)

    def test_beam_validation_checks_only_its_row_or_column_and_does_not_snap_server_pose(self):
        for rotation in (0, 90, 180, 270):
            data = plan(rotation=rotation)
            pose = data["layout"]["instances"][0]
            parallel = "xMm" if rotation in (0,180) else "yMm"
            perpendicular = "yMm" if rotation in (0,180) else "xMm"
            pose[parallel] += 1
            result = aggregate(self.catalog, data)
            self.assertTrue(result["layoutValidation"]["valid"], result["layoutValidation"]["issues"])
            pose[perpendicular] += 1
            before = copy.deepcopy(data)
            result = aggregate(self.catalog, data)
            self.assertIn("adapter_beam_off_grid", {i["code"] for i in result["layoutValidation"]["issues"]})
            self.assertEqual(result["layout"], before["layout"] | {"board": result["layout"]["board"]})

    def test_rotated_small_board_uses_owner_holes_and_global_main_board_beam_axis(self):
        owner = board(pitch=12.5)
        owner["mountingHoles"] = [{"columnIndex": c, "rowIndex": r} for c in (0,48) for r in (0,48)]
        plate = {"id":"module","name":"激光器小板","board":owner,"xMm":700,"yMm":100,"rotationDeg":90,"elevationMm":10}
        pose = {**laser(), "boardId":"module", "elevationMm":2}
        data = {"layout":{"board":board(1000,1000),"subBoards":[plate],"instances":[pose]}}
        result = aggregate(self.catalog, data)
        self.assertTrue(result["layoutValidation"]["valid"], result["layoutValidation"]["issues"])
        record, = result["layoutValidation"]["laserAdapters"]
        self.assertEqual((record["boardId"],record["globalRotationDeg"],record["beamPortMm"]), ("module",90,{"xMm":387.5,"yMm":121}))
        self.assertEqual(result["layoutValidation"]["axisHeights"][0]["effectiveAxisHeightMm"],177.1)
        plate["xMm"] += 12.5
        self.assertIn("adapter_beam_off_grid", {i["code"] for i in aggregate(self.catalog,data)["layoutValidation"]["issues"]})

    def test_owner_existing_counterbores_are_excluded_and_plain_holes_are_not_mounts(self):
        data = plan()
        result = aggregate(self.catalog, data)
        positions = result["layoutValidation"]["mountingAlignment"][0]["alignedPositionsMm"]
        owner = copy.deepcopy(result["layout"]["board"])
        owner["mountingHoles"] = [{"columnIndex":round((p["xMm"]-12.5)/25),"rowIndex":round((p["yMm"]-12.5)/25)} for p in positions]
        spec = result["layoutValidation"]["laserAdapters"][0]["spec"]
        changed = choose_board_holes(laser(), owner, spec["outlineBoundsMm"], spec["laserThreadHolesMm"])
        self.assertEqual(len(changed),4)
        self.assertTrue(set((h["xMm"],h["yMm"]) for h in changed).isdisjoint((h["xMm"],h["yMm"]) for h in spec["boardMountingHolesMm"]))
        data["layout"]["board"].update(holeType="plain_through",holeDiameterMm=6.4)
        self.assertIn("adapter_mounting_unavailable", {i["code"] for i in aggregate(self.catalog,data)["layoutValidation"]["issues"]})

    def test_counterbores_under_the_laser_housing_are_valid_for_production(self):
        data = plan()
        data["layout"]["board"] = board(1000, 1000)
        data["layout"]["instances"][0].update(xMm=495.5, yMm=495.5)
        result = aggregate(self.catalog, data)
        self.assertTrue(result["layoutValidation"]["valid"], result["layoutValidation"]["issues"])
        spec = validate_adapter_spec(result["layoutValidation"]["laserAdapters"][0]["spec"])
        self.assertEqual(len(spec["boardMountingHolesMm"]), 4)
        for hole in spec["boardMountingHolesMm"]:
            self.assertTrue(-260 <= hole["xMm"] <= 260 and -119 <= hole["yMm"] <= 119)
        row, = [r for r in result["manufacturing"] if r.get("generatedLaserAdapter")]
        self.assertEqual(row["quantity"], 1)

    def test_bom_merges_identical_geometry_and_keeps_datum_review_nonblocking(self):
        data = plan()
        data["layout"]["board"]["widthMm"] = 1800
        data["layout"]["instances"].append({**laser(iid="laser-two"),"xMm":1004})
        result = aggregate(self.catalog,data)
        self.assertTrue(result["layoutValidation"]["valid"],result["layoutValidation"]["issues"])
        adapters = [r for r in result["manufacturing"] if r.get("generatedLaserAdapter")]
        self.assertEqual(len(adapters),1)
        self.assertEqual(adapters[0]["quantity"],2)
        self.assertEqual(adapters[0]["manufacturingSpec"],{"material":"6061 铝合金","surfaceTreatment":"黑色阳极氧化"})
        reviews = [i for g in result["reviewGroups"] for i in g["items"]]
        self.assertTrue(any(i["code"]=="adapter_mounting_datum" and not i["blocking"] for i in reviews))
        self.assertFalse(any(i["code"]=="source_file_missing" for i in reviews))

    def test_plate_area_collision_and_base_bounds_are_still_enforced(self):
        catalog = copy.deepcopy(self.catalog)
        tiny = next(k for k in catalog["kits"] if k["id"]=="pbs-fixed")["layout"]
        tiny.update(baseBoundsMm={"xMin":-1,"xMax":1,"yMin":-1,"yMax":1},collisionBoundsMm={"xMin":-1,"xMax":1,"yMin":-1,"yMax":1},collisionPolygonsMm=[],mountingHoleOffsetsMm=[{"xMm":0,"yMm":0}],opticalAxisHeightMm=152.4)
        data = plan(pitch=12.5)
        data["layout"]["instances"].append({"id":"corner","kitId":"pbs-fixed","xMm":112.5,"yMm":375,"rotationDeg":0})
        result = aggregate(catalog,data)
        self.assertTrue(result["layoutValidation"]["collisions"], "thin plate corner is physical even outside laser casing silhouette")
        del data["layout"]["instances"][0]["laserAdapter"]
        self.assertEqual(aggregate(catalog,data)["layoutValidation"]["collisions"], [])
        data=plan();data["layout"]["instances"][0]["xMm"]=200
        self.assertTrue(aggregate(self.catalog,data)["layoutValidation"]["outOfBounds"])

    def test_user_datum_is_distinguished_and_thread_edges_cannot_silently_expand_plate(self):
        data=plan();data["layout"]["instances"][0]["laserAdapter"].update(mountingOriginXMm=90,mountingDatumConfirmed=True)
        result=aggregate(self.catalog,data)
        self.assertTrue(result["layoutValidation"]["valid"],result["layoutValidation"]["issues"])
        spec=validate_adapter_spec(result["layoutValidation"]["laserAdapters"][0]["spec"])
        self.assertTrue(spec["mountingDatumProvided"])
        self.assertEqual(spec["datumSource"],"用户声明已按实物核对")
        self.assertEqual(spec["laserThreadHolesMm"][0]["xMm"],90)
        data["layout"]["instances"][0]["laserAdapter"]["mountingOriginYMm"]=-140
        result=aggregate(self.catalog,data)
        self.assertIn("adapter_thread_out_of_bounds",{i["code"] for i in result["layoutValidation"]["issues"]})
        self.assertEqual(result["layoutValidation"]["laserAdapters"][0]["spec"]["outlineBoundsMm"]["yMin"],-130.5)

    def test_strict_settings_and_canonical_generated_spec_reject_forgery(self):
        for settings in (None, False, {"enabled":False}, {"enabled":True}, {"enabled":True,"thicknessMm":8.4},
                         {"enabled":True,"thicknessMm":50.1}, {"enabled":True,"thicknessMm":17.45},
                         {"enabled":True,"thicknessMm":17.4,"holes":[]}, {"enabled":True,"thicknessMm":17.4,"mountingDatumConfirmed":"yes"}):
            with self.subTest(settings=settings),self.assertRaises(APIError):
                normalize_settings({"kitId":"laser-308nm","laserAdapter":settings})
        with self.assertRaises(APIError):
            normalize_settings({"kitId":"pbs-fixed","laserAdapter":{"enabled":True,"thicknessMm":17.4}})
        spec=aggregate(self.catalog,plan())["layoutValidation"]["laserAdapters"][0]["spec"]
        for mutation in (lambda s:s.update(digest="0"*64),lambda s:s.update(filenameStem="../../private"),
                         lambda s:s["boardMountingHolesMm"][0].update(xMm=1000),lambda s:s["thread"].update(stepDiameterMm=7),
                         lambda s:s.update(extra="unknown")):
            forged=copy.deepcopy(spec);mutation(forged)
            with self.assertRaises(APIError):validate_adapter_spec(forged)


if __name__ == "__main__":
    unittest.main()
