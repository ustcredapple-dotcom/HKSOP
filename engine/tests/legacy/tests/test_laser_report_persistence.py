"""Resolved report source parameters stay explicit in portable/cart snapshots."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from bom import aggregate
from cart import CartStore
from layout import layout_json
from shared_kits import Identity, SharedKitStore
from test_layout import layout_fixture, request


def report_optics():
    return {"elementType": "source", "inserted": True, "configured": True,
            "source": {"enabled": True, "wavelengthNm": 308.366, "powerMw": 118,
                       "beamDiameterMm": 1.264, "beamQualityM2": 1.071,
                       "polarizationType": "linear", "polarizationAngleDeg": 37,
                       "wavefrontRadiusMm": None, "directionAngleDeg": 180}}


class LaserReportPersistenceTests(unittest.TestCase):
    def test_layout_export_preserves_full_and_sparse_user_source_parameters(self):
        catalog = layout_fixture()
        for settings in [report_optics(), {"elementType": "source", "inserted": True,
                         "source": {"enabled": False, "powerMw": 0, "wavefrontRadiusMm": None}}]:
            with self.subTest(settings=settings):
                payload = request()
                payload["layout"]["instances"][0]["optics"] = copy.deepcopy(settings)
                before = copy.deepcopy(payload)
                result = aggregate(catalog, payload)
                reopened = aggregate(catalog, json.loads(layout_json(result)))
                self.assertEqual(reopened["layout"]["instances"][0]["optics"], settings)
                self.assertEqual(payload, before)

    def test_cart_freezes_report_parameters_and_does_not_rewrite_procurement(self):
        catalog = layout_fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "laser-report.sqlite3"
            identity = Identity("laser-report-test", "Report test", "user")
            store = CartStore(SharedKitStore(path))
            current = store.read(identity)
            payload = request()
            bare = aggregate(catalog, payload)
            payload["layout"]["instances"][0]["optics"] = report_optics()
            store.add(identity, {"cartId": current["cartId"], "revision": current["revision"],
                      "requestId": "laser-report-cart-test", "name": "Report source",
                      "payload": payload}, catalog)
            payload["layout"]["instances"][0]["optics"]["source"]["powerMw"] = 91
            restored = CartStore(SharedKitStore(path)).read(identity)
            snapshot = restored["preview"]["cartSources"][0]
            self.assertEqual(snapshot["layout"]["instances"][0]["optics"], report_optics())
            for field in ("lubang", "manufacturing", "standard"):
                self.assertEqual(snapshot[field], bare[field])


if __name__ == "__main__":
    unittest.main()
