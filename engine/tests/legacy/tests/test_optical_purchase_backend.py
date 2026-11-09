"""Actual browser request -> BOM -> private cart restart -> downloadable order."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from openpyxl import load_workbook

from bom import APIError, aggregate, validate_catalog
from cart import CartStore, canonical, row_identity
from exports import export_result
from shared_kits import Identity, SharedKitStore, prepare_project, project_payload

ROOT = Path(__file__).resolve().parents[1]


class OpticalPurchaseBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which("node") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
        cls.catalog = validate_catalog(json.loads((ROOT / "catalog.json").read_text()))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "request.json"
            legacy = Path(folder) / "legacy.json"
            subprocess.run([node, str(ROOT / "tests/test_optical_purchase_binding.cjs")], cwd=ROOT,
                           env={**os.environ, "ZZLAB_OPTICAL_PURCHASE_PAYLOAD": str(output), "ZZLAB_OPTICAL_LEGACY_PAYLOAD": str(legacy)},
                           check=True, capture_output=True, text=True)
            cls.payload = json.loads(output.read_text())
            cls.legacy_payload = json.loads(legacy.read_text())

    def test_legacy_installed_optics_enter_cart_without_opening_properties(self):
        payload = copy.deepcopy(self.legacy_payload)
        result = aggregate(self.catalog, payload)
        original = aggregate(self.catalog, {**payload, "extras": []})
        self.assertEqual(next(r["quantity"] for r in result["lubang"] if r["model"] == "MPBS24-532"),
                         next(r["quantity"] for r in original["lubang"] if r["model"] == "MPBS24-532"))
        pending = [r for r in result["standard"] if r["model"] == "待确认"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["quantity"], 1)
        with tempfile.TemporaryDirectory() as folder:
            store = CartStore(SharedKitStore(Path(folder) / "cart.sqlite3"))
            user = Identity("legacy-optics-test", "测试者", "user")
            current = store.read(user)
            added = store.add(user, {"cartId": current["cartId"], "revision": current["revision"],
                "requestId": "legacy-without-dialog", "name": "直接恢复后加入", "payload": payload}, self.catalog)
            self.assertEqual(sum(r["quantity"] for r in added["preview"]["standard"] if r["model"] == "待确认"), 1)

    def test_bound_blank_model_and_supplier_reach_cart_and_zip(self):
        result = aggregate(self.catalog, self.payload)
        self.assertTrue(result["layoutValidation"]["valid"], result["layoutValidation"])
        selected = {r["name"]: r for r in result["standard"]}
        self.assertEqual(selected["实测四分之一波片"]["model"], "CUSTOM-QWP")
        self.assertEqual(selected["实测四分之一波片"]["supplier"], "自选供应商")
        self.assertEqual(selected["待选半波片"]["model"], "待确认")
        self.assertEqual(selected["待选半波片"]["quantity"], 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cart.sqlite3"
            user = Identity("bound-optics-test", "测试者", "user")
            store = CartStore(SharedKitStore(path))
            current = store.read(user)
            current = store.add(user, {"cartId": current["cartId"], "revision": current["revision"],
                "requestId": "optical-purchase-integration", "name": "实例绑定光学片", "payload": self.payload}, self.catalog)
            restarted = CartStore(SharedKitStore(path))
            restored = restarted.read(user)
            self.assertEqual(restored["items"], current["items"])
            self.assertEqual(restored["preview"]["cartSources"][0]["layout"]["instances"][0]["optics"]["configured"], True)
            optical_ids = {r["componentId"] for r in restored["preview"]["standard"] if r["name"] in selected}
            current = restarted.update(user, {"cartId": current["cartId"], "revision": current["revision"],
                "items": [{**r, "selected": r["componentId"] in optical_ids} for r in current["items"]]})
            checkout = restarted.for_export(user, {"cartId": current["cartId"], "revision": current["revision"]}, self.catalog)
            data, _, _ = export_result(checkout, "bundle", ROOT / "assets", ROOT / "static")
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                sheet = load_workbook(io.BytesIO(archive.read("通用外购件.xlsx")))["通用外购件"]
                self.assertEqual([c.value for c in sheet[5]][-1], "供应商")
                actual = {sheet.cell(r, 3).value: [sheet.cell(r, c).value for c in (4, 5, 7)] for r in range(6, sheet.max_row + 1)}
                self.assertEqual(actual["实测四分之一波片"], ["CUSTOM-QWP", 1, "自选供应商"])
                self.assertEqual(actual["待选半波片"], ["待确认", 1, "待选供应商"])
                self.assertFalse(any(name.endswith(".step") or name.endswith(".pdf") for name in archive.namelist()))

    def test_pbs_replacement_and_removal_only_affect_target_instance(self):
        raw = copy.deepcopy(self.payload)
        raw["layout"]["instances"].append({"id": "pbs-other", "kitId": "pbs-fixed", "xMm": 275, "yMm": 150, "rotationDeg": 0})
        kit = next(k for k in self.catalog["kits"] if k["id"] == "pbs-fixed")
        slot = kit["opticalSlots"][0]
        original = next(c for c in self.catalog["components"] if c["id"] == slot["replacesComponentId"])
        original_quantity = next(r["quantity"] for r in aggregate(self.catalog, raw)["lubang"] if r["model"] == original["model"])
        replacement = {"id": "pbs-bound", "instanceId": "pbs", "kitId": "pbs-fixed", "slotId": slot["id"],
                       "name": "替换晶体", "model": "CUSTOM-PBS", "kind": "standard", "quantity": slot["quantity"], "unit": "个", "inserted": True}
        raw["extras"].append(replacement)
        replaced = aggregate(self.catalog, raw)
        self.assertEqual(next(r["quantity"] for r in replaced["lubang"] if r["model"] == original["model"]), original_quantity - 1)
        self.assertEqual(next(r["quantity"] for r in replaced["standard"] if r["model"] == "CUSTOM-PBS"), 1)
        replacement["inserted"] = False
        removed = aggregate(self.catalog, raw)
        self.assertEqual(next(r["quantity"] for r in removed["lubang"] if r["model"] == original["model"]), original_quantity - 1)
        self.assertFalse(any(r["model"] == "CUSTOM-PBS" for r in removed["standard"]))

    def test_supplier_separates_same_named_manual_models_without_changing_old_cart_keys(self):
        base = {"kind": "standard", "model": "CUSTOM-532", "unit": "片", "componentId": "extra:one"}
        expected = "cart:" + hashlib.sha256(canonical(["standard", "custom-532", "片"]).encode()).hexdigest()[:40]
        self.assertEqual(row_identity(base, "source"), expected)
        self.assertEqual(row_identity({**base, "supplier": ""}, "source"), expected)
        self.assertNotEqual(row_identity({**base, "supplier": "甲"}, "source"), row_identity({**base, "supplier": "乙"}, "source"))
        raw = copy.deepcopy(self.payload)
        for i, row in enumerate(raw["extras"]):
            row.update(model="SAME-MODEL", supplier=f"供应商{i}")
        result = aggregate(self.catalog, raw)
        self.assertEqual(len([r for r in result["standard"] if r["model"] == "SAME-MODEL"]), 2)

    def test_shared_project_binding_uses_same_purchase_contract(self):
        p = json.loads((ROOT / "qa/optical-rendering-flat.zzoptics.json").read_text())
        iid = next(i["id"] for i in p["layout"]["instances"] if i["kitId"] == "waveplate")
        p["optical"] = {f"{iid}::wave-1": {"inserted": True, "name": "待选波片", "model": "", "supplier": "=literal supplier", "quantity": 1, "unit": "片"},
                        f"{iid}::wave-2": {"inserted": False, "model": "OLD-MODEL", "quantity": 1}}
        payload = project_payload(p, self.catalog)
        result = aggregate(self.catalog, payload)
        row = next(r for r in result["standard"] if r["name"] == "待选波片")
        self.assertEqual(row["supplier"], "=literal supplier")
        self.assertFalse(any(r["model"] == "OLD-MODEL" for r in result["standard"] + result["lubang"]))
        prepare_project(p, self.catalog)
        for change in ({"inserted": "true"}, {"supplier": {"nested": True}}, {"quantity": 2}, {"stepPath": "x.step"}):
            invalid = copy.deepcopy(p)
            invalid["optical"][f"{iid}::wave-1"].update(change)
            with self.assertRaises(APIError):
                project_payload(invalid, self.catalog)

    def test_legacy_shared_engineering_file_derives_only_actual_optical_slots(self):
        p = json.loads((ROOT / "qa/optical-rendering-flat.zzoptics.json").read_text())
        p["optical"] = {}
        before = copy.deepcopy(p)
        payload = project_payload(p, self.catalog)
        self.assertEqual(p, before)
        rows = payload["extras"]
        roles = {i["id"]: i["optics"]["elementType"] for i in p["layout"]["instances"]}
        self.assertFalse(any(roles[r["instanceId"]] in ("coupler", "source") for r in rows))
        iid = next(i["id"] for i in p["layout"]["instances"] if i["kitId"] == "waveplate")
        self.assertEqual([r["inserted"] for r in rows if r["instanceId"] == iid], [True, True])
        p["optical"][iid + "::wave-1"] = {"inserted": False, "model": "REMOVED"}
        changed = project_payload(p, self.catalog)
        self.assertFalse(next(r["inserted"] for r in changed["extras"] if r["instanceId"] == iid and r["slotId"] == "wave-1"))
        pbs = next(r for r in changed["extras"] if roles[r["instanceId"]] == "pbs")
        self.assertTrue(pbs["model"])
        original = aggregate(self.catalog, {"layout": p["layout"]})
        result = aggregate(self.catalog, changed)
        self.assertEqual(next(r["quantity"] for r in result["lubang"] if r["model"] == pbs["model"]),
                         next(r["quantity"] for r in original["lubang"] if r["model"] == pbs["model"]))


if __name__ == "__main__":
    unittest.main()
