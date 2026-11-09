"""Optical simulation data survives real persistence without changing procurement."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from bom import APIError, aggregate
from cart import CartStore
from layout import layout_json
from optics_settings import normalize_optics
from shared_kits import Identity, SharedKitStore, prepare_project, project_payload
from stacked_layout import global_instance
from test_layout import layout_fixture, request
from test_shared_kits import project


def optics():
    return {"elementType": "waveplate", "inserted": True, "configured": True, "surfaceAngleDeg": -45,
            "pbsHandedness": "right", "fastAxisDeg": 22.5, "retardanceDeg": 180,
            "designWavelengthNm": 532, "focalLengthMm": None, "clearApertureMm": 25.4,
            "waveplates": [{"inserted": True, "fastAxisDeg": 22.5, "retardanceDeg": 180, "designWavelengthNm": 532},
                           {"inserted": True, "fastAxisDeg": 45, "retardanceDeg": 90, "designWavelengthNm": 532}],
            "source": {"enabled": True, "wavelengthNm": 532, "powerMw": 1, "beamDiameterMm": 2,
                       "polarizationType": "elliptical", "polarizationAngleDeg": 20, "ellipticityDeg": -15,
                       "wavefrontRadiusMm": None, "beamQualityM2": 1.2, "directionAngleDeg": -90}}


class OpticsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.catalog = layout_fixture()

    def test_old_layout_unchanged_and_new_round_trip_is_independent(self):
        raw = request()
        old = aggregate(self.catalog, raw)
        self.assertNotIn("optics", old["layout"]["instances"][0])
        raw["layout"]["instances"][0]["optics"] = optics()
        before = copy.deepcopy(raw)
        rendered = aggregate(self.catalog, raw)
        self.assertEqual(raw, before)
        self.assertEqual(rendered["layout"]["instances"][0]["optics"], optics())
        for field in ("items", "lubang", "manufacturing", "standard", "replacements", "totals", "layoutValidation"):
            self.assertEqual(rendered[field], old[field], f"simulation must not alter {field}")
        again = aggregate(self.catalog, json.loads(layout_json(rendered)))
        self.assertEqual(again["layout"], rendered["layout"])
        raw["layout"]["instances"][0]["optics"]["source"]["wavelengthNm"] = 780
        rendered["layout"]["instances"][0]["optics"]["waveplates"][0]["fastAxisDeg"] = 70
        self.assertEqual(again["layout"]["instances"][0]["optics"], optics())

    def test_stacked_layout_preserves_local_angles_and_detaches_world_view(self):
        raw = request()["layout"]
        raw["instances"] = [dict(raw["instances"][0], boardId="plate", optics=optics())]
        raw["subBoards"] = [{"id": "plate", "name": "测试小板", "board": copy.deepcopy(raw["board"]),
                             "xMm": 0, "yMm": 0, "rotationDeg": 90}]
        result = aggregate(self.catalog, {"layout": raw})["layout"]
        local = result["instances"][0]
        self.assertEqual(local["optics"], optics())
        world = global_instance(local, {"plate": result["subBoards"][0]})
        self.assertEqual(world["rotationDeg"], 90)
        self.assertEqual(world["optics"]["source"]["directionAngleDeg"], -90)
        world["optics"]["source"]["directionAngleDeg"] = 180
        self.assertEqual(local["optics"], optics())

    def test_project_payload_and_shared_database_preserve_optics_not_runtime(self):
        p = project()
        p["layout"]["instances"][0]["optics"] = optics()
        p["opticalRendering"] = {"generated": True, "visible": False, "autoRestore": True}
        payload = project_payload(p, self.catalog)
        self.assertEqual(payload["layout"]["instances"][0]["optics"], optics())
        prepare_project(p, self.catalog)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "isolated.sqlite3"
            identity = Identity("optics-test", "测试者", "user")
            store = SharedKitStore(path)
            published = store.publish("光路参数工程", "", p, b"<svg/>", identity)
            p["layout"]["instances"][0]["optics"]["source"]["powerMw"] = 50
            stored = json.loads(SharedKitStore(path).get(published["kit"]["id"], identity)["project_json"])
            self.assertEqual(stored["layout"]["instances"][0]["optics"], optics())
            self.assertEqual(stored["opticalRendering"], {"generated": True, "visible": False, "autoRestore": True})
        for runtime in ("rays", "segments", "pending", "renderProgress"):
            bad = project()
            bad["layout"]["instances"][0]["optics"] = {**optics(), runtime: []}
            with self.assertRaises(APIError):
                project_payload(bad, self.catalog)
        for prefs in ({"generated": 1, "visible": True, "autoRestore": True}, {"generated": True},
                      {"generated": True, "visible": True, "autoRestore": True, "segments": []}):
            bad = project()
            bad["opticalRendering"] = prefs
            with self.assertRaises(APIError):
                project_payload(bad, self.catalog)

    def test_account_cart_snapshot_survives_restart_and_edit_without_bom_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "isolated.sqlite3"
            identity = Identity("optics-test", "测试者", "user")
            store = CartStore(SharedKitStore(path))
            current = store.read(identity)
            payload = request()
            payload["layout"]["instances"][0]["optics"] = optics()
            envelope = store.add(identity, {"cartId": current["cartId"], "revision": current["revision"],
                "requestId": "optics-snapshot-test", "name": "光路参数工程", "payload": payload}, self.catalog)
            payload["layout"]["instances"][0]["optics"]["waveplates"][1]["retardanceDeg"] = 270
            restored = CartStore(SharedKitStore(path)).read(identity)
            snapshot = restored["preview"]["cartSources"][0]
            self.assertEqual(snapshot["layout"]["instances"][0]["optics"], optics())
            self.assertEqual(restored["items"], envelope["items"])
            self.assertEqual(snapshot["lubang"], aggregate(self.catalog, request())["lubang"])

    def test_all_types_optional_values_and_physical_endpoints(self):
        for element in ("empty", "mirror", "pbs", "waveplate", "lens", "coupler", "source"):
            value = {"elementType": element, "inserted": False}
            self.assertEqual(normalize_optics(value), value)
        config = optics()
        config.update(focalLengthMm=-50, waveplates=[])
        config["source"].update(wavefrontRadiusMm=-1e12, enabled=False, powerMw=0, beamQualityM2=100)
        self.assertEqual(normalize_optics(config), config)
        config["source"].update(wavefrontRadiusMm=1e-6)
        config["focalLengthMm"] = 1e-6
        self.assertEqual(normalize_optics(config), config)

    def test_unknown_fields_nonfinite_values_and_injected_assets_are_rejected(self):
        invalid = [None, [], {}, {"elementType": "mirror"}, {"elementType": "x", "inserted": True},
            {**optics(), "inserted": 1}, {**optics(), "configured": 1}, {**optics(), "configured": "true"},
            {**optics(), "source": {}}, {**optics(), "pbsHandedness": "up"},
            {**optics(), "stepPath": "/etc/passwd"}, {**optics(), "source": {"enabled": True, "assetUrl": "https://bad"}},
            {**optics(), "waveplates": [dict(optics()["waveplates"][0], model="fake")]},
            {**optics(), "waveplates": [{"inserted": True}] * 9},
            {**optics(), "waveplates": [{"inserted": "true"}]},
            {**optics(), "source": {"enabled": True, "polarizationType": []}}]
        for key, values in {"surfaceAngleDeg": [3601, True], "retardanceDeg": [36001], "fastAxisDeg": [-3601],
                            "designWavelengthNm": [0, 1e6 + 1], "clearApertureMm": [0, 10001],
                            "focalLengthMm": [0, 1e-8, 1e6 + 1]}.items():
            invalid.extend({**optics(), key: value} for value in values + ["1", float("nan"), float("inf")])
        for key, values in {"enabled": [1, None], "wavelengthNm": [0, 1e6+1], "powerMw": [-1, 1e9+1],
                            "beamDiameterMm": [0, 10001], "polarizationAngleDeg": [3601], "ellipticityDeg": [46, -46],
                            "wavefrontRadiusMm": [0, 1e-8, 1e12+1], "beamQualityM2": [.9, 101],
                            "directionAngleDeg": [-3601]}.items():
            invalid.extend({**optics(), "source": {**optics()["source"], key: value}} for value in values + ["1", float("nan"), float("inf")])
        for config in invalid:
            with self.subTest(config=config):
                payload = request()
                payload["layout"]["instances"][0]["optics"] = config
                with self.assertRaises(APIError) as error:
                    aggregate(self.catalog, payload)
                self.assertEqual(error.exception.code, "invalid_optics")


if __name__ == "__main__":
    unittest.main()
