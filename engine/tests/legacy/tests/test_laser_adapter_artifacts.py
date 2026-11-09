"""Adapter manufacturing files and immutable account shopping-cart exports."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bom import APIError, aggregate, load_catalog
from cart import CartStore, verified_adapter_row
from exports import export_result
from laser_adapter_artifacts import ensure_adapter_artifacts, _valid_cache
from shared_kits import Identity, SharedKitStore


def adapter_payload(thickness=17.4, confirmed=False):
    return {"layout": {"board": {"widthMm": 1000, "heightMm": 625, "pitchMm": 25, "edgeOffsetMm": 12.5,
                                   "thicknessMm": 12.7, "holeType": "M6_through", "mountingHoles": []},
                       "instances": [{"id": "laser", "kitId": "laser-308nm", "xMm": 304, "yMm": 245.5, "rotationDeg": 0,
                                      "laserAdapter": {"enabled": True, "thicknessMm": thickness, "mountingDatumConfirmed": confirmed}}]}}


def token(cart):
    return {k: cart[k] for k in ("cartId", "revision")}


class AdapterExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog.json")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = CartStore(SharedKitStore(self.root / "test.sqlite3"))
        self.user = Identity("adapter-test", "底板测试", "user")

    def tearDown(self):
        self.temp.cleanup()

    def add(self, payload=None, envelope=None, request_id="adapter-test-001"):
        return self.store.add(self.user, {**token(envelope or self.store.read(self.user)), "name": "激光器方案", "requestId": request_id,
                                          "payload": payload or adapter_payload()}, self.catalog)

    def adapter_only(self, cart, quantity=1):
        cid = next(r["componentId"] for r in cart["preview"]["manufacturing"] if r.get("generatedLaserAdapter"))
        return self.store.update(self.user, {**token(cart), "items": [{**i, "quantity": quantity if i["componentId"] == cid else i["quantity"],
                                                                    "selected": i["componentId"] == cid} for i in cart["items"]]})

    def test_persistent_snapshot_reuses_identical_spec_and_respects_checkout_quantity(self):
        payload = adapter_payload()
        first = self.add(payload)
        original = next(r for r in first["preview"]["manufacturing"] if r.get("generatedLaserAdapter"))
        payload["layout"]["instances"][0]["laserAdapter"]["thicknessMm"] = 25
        second = self.add(envelope=first, request_id="adapter-test-002")
        plates = [r for r in second["preview"]["manufacturing"] if r.get("generatedLaserAdapter")]
        self.assertEqual(len(plates), 1)
        self.assertEqual(plates[0]["quantity"], 2)
        self.assertEqual(plates[0]["adapterSpec"], original["adapterSpec"])
        current = self.adapter_only(second, 7)
        restarted = CartStore(SharedKitStore(self.root / "test.sqlite3"))
        self.assertEqual(restarted.read(self.user)["items"], current["items"])
        preview = restarted.for_export(self.user, token(current), self.catalog)
        self.assertEqual(len(preview["manufacturing"]), 1)
        self.assertEqual(preview["manufacturing"][0]["quantity"], 7)
        self.assertEqual(preview["lubang"], [])
        self.assertEqual(preview["standard"], [])
        self.assertEqual(preview["cartSources"][0]["layout"]["instances"][0]["laserAdapter"]["thicknessMm"], 17.4)
        self.assertEqual(preview["cartSources"][0]["layoutValidation"]["laserAdapters"][0]["spec"], original["adapterSpec"])

    def test_distinct_thickness_or_confirmation_keeps_separate_production_rows(self):
        first = self.add()
        second = self.add(adapter_payload(20), first, "adapter-other-002")
        third = self.add(adapter_payload(17.4, True), second, "adapter-other-003")
        plates = [r for r in third["preview"]["manufacturing"] if r.get("generatedLaserAdapter")]
        self.assertEqual(len(plates), 3)
        self.assertEqual(len({r["adapterSpec"]["digest"] for r in plates}), 3)

    def test_deleted_plate_is_not_manufactured_and_all_unchecked_is_empty(self):
        current = self.add()
        cid = next(r["componentId"] for r in current["preview"]["manufacturing"] if r.get("generatedLaserAdapter"))
        current = self.store.update(self.user, {**token(current), "items": [{**i, "selected": i["componentId"] != cid, "removed": i["componentId"] == cid} for i in current["items"]]})
        preview = self.store.for_export(self.user, token(current), self.catalog)
        self.assertFalse(any(r.get("generatedLaserAdapter") for r in preview["manufacturing"]))
        current = self.store.update(self.user, {**token(current), "items": [{**i, "selected": False} for i in current["items"]]})
        with self.assertRaises(APIError) as error:
            self.store.for_export(self.user, token(current), self.catalog)
        self.assertEqual(error.exception.code, "empty_checkout")

    def test_tampered_specs_paths_and_source_identity_fail_before_file_access(self):
        preview = aggregate(self.catalog, adapter_payload())
        original = next(r for r in preview["manufacturing"] if r.get("generatedLaserAdapter"))
        for change in ({"stepPath": "secret.step"}, {"drawingPath": "secret.pdf"}, {"generatedBoard": True},
                       {"componentId": "forged"}, {"model": "forged"}, {"generatedLaserAdapter": 1}, {"kind": "standard"}):
            with self.subTest(change=change), self.assertRaises(APIError):
                verified_adapter_row({**original, **change})
        for key, value in (("digest", "../secret"), ("filenameStem", "../../secret"), ("thicknessMm", 18),
                           ("material", "forged"), ("counterbore", {"diameterMm": 99})):
            spec = copy.deepcopy(original["adapterSpec"])
            spec[key] = value
            with self.subTest(key=key), self.assertRaises(APIError):
                ensure_adapter_artifacts(spec, self.root / "untouched", cad_python="/missing")
            self.assertFalse((self.root / "untouched").exists())

    def test_production_workbook_has_quantity_material_treatment_hole_table_and_order(self):
        current = self.adapter_only(self.add(), 6)
        preview = self.store.for_export(self.user, token(current), self.catalog)
        data, _, _ = export_result(preview, "manufacturing", ROOT / "assets", ROOT / "static")
        wb = load_workbook(io.BytesIO(data))
        self.assertEqual(wb["生产清单"].cell(6, 5).value, 6)
        self.assertEqual(wb["生产清单"].cell(6, 7).value, "6061 铝合金")
        self.assertEqual(wb["生产清单"].cell(6, 8).value, "黑色阳极氧化")
        values = [c.value for row in wb["激光器底板"].iter_rows() for c in row if isinstance(c.value, str)]
        self.assertTrue(any("先固定底板，再安装激光器" in value for value in values))
        self.assertTrue(any("待实物核对" in value for value in values))
        self.assertEqual(wb["激光器底板孔表"].max_row, 13)

    @unittest.skipUnless(Path(os.environ.get("ZZLAB_CAD_PYTHON", "/missing")).is_file(), "requires operator CAD Python")
    def test_real_cad_artifacts_cache_hashes_bundle_and_all_thickness_limits(self):
        cache = self.root / "cache"
        for thickness in (8.5, 17.4, 50):
            preview = aggregate(self.catalog, adapter_payload(thickness))
            spec = next(r for r in preview["manufacturing"] if r.get("generatedLaserAdapter"))["adapterSpec"]
            result = ensure_adapter_artifacts(spec, cache)
            report = json.loads((result["step"].parent / "artifact.json").read_text())
            self.assertEqual(report["geometryValidation"]["solidCount"], 1)
            self.assertEqual(report["geometryValidation"]["cylindricalHoleFaces"], 12)
            self.assertAlmostEqual(report["geometryValidation"]["volumeMm3"], report["geometryValidation"]["analyticVolumeMm3"], places=5)
            self.assertTrue(_valid_cache(result["step"].parent, spec))
            self.assertEqual(ensure_adapter_artifacts(spec, cache, cad_python="/missing")["step"], result["step"])
            self.assertEqual(json.loads(result["holeSpec"].read_text()), spec)
            if thickness == 17.4:
                result["drawing"].write_bytes(b"invalid cached PDF" * 20)
                self.assertFalse(_valid_cache(result["step"].parent, spec))
                with self.assertRaises(APIError) as unavailable:
                    ensure_adapter_artifacts(spec, cache, cad_python="/missing")
                self.assertEqual(unavailable.exception.code, "cad_unavailable")
                result = ensure_adapter_artifacts(spec, cache)
                self.assertTrue(_valid_cache(result["step"].parent, spec))
        current = self.adapter_only(self.add(), 3)
        preview = self.store.for_export(self.user, token(current), self.catalog)
        with patch.dict(os.environ, {"ZZLAB_LASER_ADAPTER_CACHE": str(cache)}):
            data, _, _ = export_result(preview, "bundle", ROOT / "assets", ROOT / "static")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            config = json.loads(archive.read("套件配置.json"))
            plate, = config["components"]
            self.assertEqual(plate["quantity"], 3)
            assets = config["assets"][plate["componentId"]]
            self.assertEqual(set(assets), {"step", "drawing", "holeSpec", "topView"})
            for path in assets.values():
                self.assertEqual(hashlib.sha256(archive.read(path)).hexdigest(), config["fileChecksums"][path])
            self.assertEqual(json.loads(archive.read(assets["holeSpec"])), plate["adapterSpec"])
            self.assertEqual(len([n for n in archive.namelist() if n.endswith(".step")]), 1)
            self.assertEqual(len([n for n in archive.namelist() if n.endswith(".pdf")]), 1)


if __name__ == "__main__":
    unittest.main()
