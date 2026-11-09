import copy
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Config, create_server
from bom import APIError, aggregate, validate_catalog
from exports import export_result, safe_asset


def fixture():
    """Synthetic test parts only; never written to the production catalog."""
    components = []
    for cid, kind, model in (("plate", "custom", "DRAW-01"), ("bracket", "custom", "DRAW-02"),
                             ("optic", "lubang", "OPT-OLD"), ("bolt", "standard", "BOLT-M4")):
        components.append({"id": cid, "name": "测试"+cid, "kind": kind, "model": model, "unit": "个",
                           "stepPath": f"{cid}.step" if kind == "custom" else None,
                           "drawingPath": f"{cid}.pdf" if kind == "custom" else None,
                           "status": "已核对", "notes": "仅用于测试", "sourceUrl": "https://example.com/source"})
    return validate_catalog({"version": "test-v1", "updatedAt": "2026-09-23", "categories": [{"id": "test", "label": "测试"}],
                             "components": components, "kits": [
        {"id": "alpha", "name": "测试套件甲", "category": "test", "variant": "1", "description": "fixture", "status": "已核对", "notes": "", "sourceUrl": "",
         "components": [{"componentId": "plate", "quantity": 1}, {"componentId": "optic", "quantity": 2}, {"componentId": "bolt", "quantity": 4}],
         "pendingRequirements": [{"id": "screws", "label": "额外螺钉"}],
         "opticalSlots": [{"id": "mirror", "label": "反射镜片", "type": "mirror", "diameterMm": 25.4, "quantity": 1, "replacesComponentId": "optic"}]},
        {"id": "beta", "name": "测试套件乙", "category": "test", "variant": "2", "description": "fixture", "status": "已核对", "notes": "", "sourceUrl": "",
         "components": [{"componentId": "plate", "quantity": 2}, {"componentId": "bracket", "quantity": 1}, {"componentId": "optic", "quantity": 1}]}]})


def payload(**kwargs):
    return {"items": [{"kitId": "alpha", "quantity": 2}, {"kitId": "beta", "quantity": 3}], **kwargs}


def extra(eid="e1", **kwargs):
    return {"id": eid, "kitId": None, "kind": "lubang", "name": "补充光学件", "model": "OPT-OLD",
            "quantity": 4, "unit": "个", "notes": "用户补充", **kwargs}


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = fixture()

    def test_shared_parts_sum_and_trace_contributions(self):
        result = aggregate(self.catalog, payload())
        custom = {r["componentId"]: r for r in result["manufacturing"]}
        self.assertEqual(custom["plate"]["quantity"], 8)
        self.assertEqual([r["quantity"] for r in custom["plate"]["kits"]], [2, 6])
        self.assertEqual(result["lubang"][0]["quantity"], 7)
        self.assertEqual(result["standard"][0]["quantity"], 8)
        self.assertEqual(result["totals"], {"kits": 5, "componentTypes": 4, "componentQuantity": 26})
        self.assertTrue(result["optionalNotes"])
        self.assertFalse(result["warnings"])

    def test_duplicate_cart_lines_merge_without_loss(self):
        result = aggregate(self.catalog, {"items": [{"kitId": "alpha", "quantity": 1}, {"kitId": "alpha", "quantity": 2}]})
        self.assertEqual(result["items"][0]["quantity"], 3)
        self.assertEqual(result["manufacturing"][0]["quantity"], 3)

    def test_bad_quantities_and_overflow_rejected(self):
        for quantity in (True, False, 0, -1, 1.5, "2", 10000, None):
            with self.subTest(quantity=quantity), self.assertRaises(APIError):
                aggregate(self.catalog, {"items": [{"kitId": "alpha", "quantity": quantity}]})
        bad = copy.deepcopy(self.catalog)
        bad["kits"][0]["components"][0]["quantity"] = 10_000_000
        with self.assertRaises(APIError):
            aggregate(bad, {"items": [{"kitId": "alpha", "quantity": 2}]})

    def test_request_paths_and_unknown_ids_rejected(self):
        for data in ({"items": [], "path": "/etc/passwd"}, {"items": [{"kitId": "../../etc/passwd", "quantity": 1}]},
                     {"items": [{"kitId": "alpha", "quantity": 1, "stepPath": "/etc/passwd"}]}):
            with self.assertRaises(APIError):
                aggregate(self.catalog, data)

    def test_empty_preview_and_version_conflict(self):
        self.assertEqual(aggregate(self.catalog, {"items": []})["totals"]["kits"], 0)
        with self.assertRaises(APIError) as caught:
            aggregate(self.catalog, payload(catalogVersion="old"))
        self.assertEqual(caught.exception.status, 409)
        with self.assertRaises(APIError):
            aggregate(self.catalog, {"items": []}, require_items=True)

    def test_optional_extras_multiply_and_merge_existing_sku(self):
        result = aggregate(self.catalog, payload(extras=[extra(quantity=3, kitId="alpha"), extra("e2", model="opt-old", quantity=4)]))
        self.assertEqual(len(result["lubang"]), 1)
        self.assertEqual(result["lubang"][0]["quantity"], 17)  # modeled7 + 3*2 + overall4
        self.assertEqual(sum(k["quantity"] for k in result["lubang"][0]["kits"]), 17)

    def test_unknown_extra_models_not_merged(self):
        result = aggregate(self.catalog, payload(extras=[extra(model=""), extra("e2", model="待确认")]))
        self.assertEqual(len(result["lubang"]), 3)
        self.assertEqual(sum(x["quantity"] for x in result["lubang"]), 15)
        self.assertTrue(result["warnings"])

    def test_invalid_extra_fields_and_nonselected_kit(self):
        for item in (extra(stepPath="/etc/passwd"), extra(kitId="unknown"), extra(kind="custom"), extra(quantity=True)):
            with self.assertRaises(APIError):
                aggregate(self.catalog, payload(extras=[item]))

    def test_optical_slot_replacement_preserves_other_kit_contribution(self):
        optic = extra(kitId="alpha", slotId="mirror", quantity=1, model="OPT-NEW", wavelength="780 nm", opticalType="")
        result = aggregate(self.catalog, payload(extras=[optic]))
        quantities = {r["model"]: r["quantity"] for r in result["lubang"]}
        self.assertEqual(quantities, {"OPT-OLD": 5, "OPT-NEW": 2})  # alpha residual2 + beta3
        old = next(r for r in result["lubang"] if r["model"] == "OPT-OLD")
        self.assertEqual(next(k["quantity"] for k in old["kits"] if k["kitId"] == "beta"), 3)
        self.assertIn("780 nm", next(r["notes"] for r in result["lubang"] if r["model"] == "OPT-NEW"))
        self.assertEqual(result["replacements"][0]["totalQuantity"], 2)

    def test_blank_optical_model_preserves_bom_and_does_not_guess(self):
        result = aggregate(self.catalog, payload(extras=[extra(kitId="alpha", slotId="mirror", quantity=1, model="", wavelength="780 nm")]))
        self.assertEqual(result["lubang"][0]["quantity"], 7)
        self.assertEqual(result["extras"], [])
        self.assertEqual(result["replacements"], [])

    def test_manual_optical_model_can_use_other_supplier(self):
        optic = extra(kitId="alpha", slotId="mirror", quantity=1, model="OTHER-MIRROR", kind="standard")
        result = aggregate(self.catalog, payload(extras=[optic]))
        self.assertEqual(result["lubang"][0]["quantity"], 5)
        row = next(r for r in result["standard"] if r["model"] == "OTHER-MIRROR")
        self.assertEqual(row["quantity"], 2)
        self.assertEqual(result["replacements"][0]["totalQuantity"], 2)

    def test_optical_replacement_cannot_be_forged(self):
        base = extra(kitId="alpha", slotId="mirror", quantity=1)
        for update in ({"slotId": "not-declared"}, {"quantity": 2}, {"replacesComponentId": "plate"}, {"opticalType": "half-wave"}):
            with self.subTest(update=update), self.assertRaises(APIError):
                aggregate(self.catalog, payload(extras=[{**base, **update}]))
        with self.assertRaises(APIError):
            aggregate(self.catalog, payload(extras=[base, {**base, "id": "second"}]))

    def test_catalog_rejects_escape_paths_and_custom_optic_replacement(self):
        for path in ("/etc/passwd.step", "../outside.step", "safe/../../out.step", "a\\b.step", "a/./b.step"):
            bad = copy.deepcopy(self.catalog)
            bad["components"][0]["stepPath"] = path
            with self.assertRaises(APIError):
                validate_catalog(bad)
        bad = copy.deepcopy(self.catalog)
        bad["kits"][0]["opticalSlots"][0]["replacesComponentId"] = "plate"
        with self.assertRaises(APIError):
            validate_catalog(bad)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for cid in ("plate", "bracket"):
            (self.root/f"{cid}.step").write_bytes(b"ISO-10303-21;\nTEST-ONLY\nEND-ISO-10303-21;")
            (self.root/f"{cid}.pdf").write_bytes(b"%PDF-1.4\nTEST-ONLY\n%%EOF")
        self.catalog = fixture()
        self.preview = aggregate(self.catalog, payload())

    def tearDown(self):
        self.temp.cleanup()

    def test_zip_assets_are_unique_quantities_are_in_workbook(self):
        data, mime, name = export_result(self.preview, "bundle", self.root)
        self.assertEqual(mime, "application/zip")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            for required in ("麓邦采购.xlsx", "生产清单.xlsx", "通用外购件.xlsx", "套件配置.json"):
                self.assertIn(required, names)
            self.assertEqual(len([n for n in names if n.endswith(".step")]), 2)
            self.assertEqual(len([n for n in names if n.endswith(".pdf")]), 2)
            config = json.loads(z.read("套件配置.json"))
            self.assertEqual(config["totals"]["componentQuantity"], 26)
            self.assertEqual(len(config["fileChecksums"]), 4)
            wb = load_workbook(io.BytesIO(z.read("生产清单.xlsx")))
            ws = wb["生产清单"]
            self.assertEqual(ws["E6"].value, 8)
            self.assertEqual(ws["E6"].data_type, "n")
            self.assertEqual(ws.max_column, 13)
            self.assertEqual(ws["G5"].value, "材料")
            self.assertTrue(config["assets"]["plate"]["step"].startswith("自制件/"))
            self.assertEqual(ws.freeze_panes, "D6")
            self.assertTrue(ws.auto_filter.ref)
            self.assertTrue(wb["套件分解"]["H6"].value > 0)

    def test_missing_asset_fails_whole_bundle(self):
        (self.root/"plate.pdf").unlink()
        with self.assertRaises(APIError) as caught:
            export_result(self.preview, "bundle", self.root)
        self.assertEqual(caught.exception.code, "asset_missing")
        self.assertEqual(caught.exception.status, 409)

    def test_symlink_asset_rejected(self):
        (self.root/"plate.step").unlink()
        (self.root/"plate.step").symlink_to(self.root/"bracket.step")
        with self.assertRaises(APIError) as caught:
            export_result(self.preview, "bundle", self.root)
        self.assertEqual(caught.exception.code, "asset_forbidden")
        with self.assertRaises(APIError):
            safe_asset(self.root, "../outside.step", "asset")

    def test_formula_like_catalog_text_is_literal(self):
        self.preview["manufacturing"][0]["name"] = '=HYPERLINK("https://invalid.example","click")'
        data, _, _ = export_result(self.preview, "manufacturing", self.root)
        wb = load_workbook(io.BytesIO(data))
        self.assertEqual(wb["生产清单"]["C6"].data_type, "s")
        self.assertTrue(wb["生产清单"]["C6"].value.startswith("="))
        self.assertIn("可选补充说明", wb.sheetnames)

    def test_empty_optional_fields_do_not_block_export(self):
        data, _, _ = export_result(self.preview, "lubang", self.root)
        self.assertGreater(len(data), 1000)

    def test_shared_registered_file_deduplication(self):
        for key in ("stepPath", "drawingPath"):
            self.preview["manufacturing"][1][key] = self.preview["manufacturing"][0][key]
        data, _, _ = export_result(self.preview, "bundle", self.root)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertEqual(len([n for n in z.namelist() if n.endswith(".step")]), 1)
            self.assertEqual(len([n for n in z.namelist() if n.endswith(".pdf")]), 1)

    def test_human_readable_names_keep_duplicate_parts_and_traceability(self):
        for index, row in enumerate(self.preview['manufacturing']):
            row['componentId'] = f'cart_abcdef0123456789_{index}'
            row['name'] = '万能柱 25 mm · 公制 M1'
        data, _, _ = export_result(self.preview, 'bundle', self.root)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            files = z.namelist()
            for name in ('万能柱 25 mm', '万能柱 25 mm (2)'):
                self.assertIn(f'自制件/{name}/{name}.step', files)
                self.assertIn(f'自制件/{name}/{name}_图纸.pdf', files)
            self.assertFalse(any('cart_' in n or '公制 M1' in n for n in files))
            config = json.loads(z.read('套件配置.json'))
            for row in self.preview['manufacturing']:
                mapped = config['assets'][row['componentId']]
                for kind, source in (('step', 'stepPath'), ('drawing', 'drawingPath')):
                    self.assertEqual(z.read(mapped[kind]), (self.root/row[source]).read_bytes())
                    self.assertIn(mapped[kind], config['fileChecksums'])

    def test_archive_names_preserve_dimensions_and_cannot_escape_folders(self):
        from exports import readable_part_name, unique_archive_name
        self.assertEqual(readable_part_name('参数面包板 200 × 200 × 12.5 mm'), '面包板 200 × 200 × 12.5 mm')
        self.assertEqual(readable_part_name('../CON:零件'), '_CON_零件')
        self.assertEqual(readable_part_name('CON'), '_CON')
        used = set()
        self.assertEqual(unique_archive_name('AOM', used), 'AOM')
        self.assertEqual(unique_archive_name('aom', used), 'aom (2)')


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.catalog = cls.root/"catalog.json"
        cls.catalog.write_text(json.dumps(fixture(), ensure_ascii=False))
        cls.server = create_server(Config(cls.catalog, cls.root, cls.root/"static", "test-secret"), 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, path, data=None, auth=True, **headers):
        h = {"Content-Type": "application/json"}
        if auth:
            h.update({"X-ZZLAB-Internal-Token": "test-secret", "X-ZZLAB-Authenticated": "true", "X-ZZLAB-Role": "user"})
        h.update(headers)
        request = urllib.request.Request(self.url+path, data=None if data is None else json.dumps(data).encode(), headers=h)
        try:
            return urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            return error

    def test_health_catalog_prefix_and_auth(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(self.request("/healthz", auth=False).status, 200)
        self.assertEqual(self.request("/api/catalog", auth=False).status, 401)
        self.assertEqual(self.request("/optics-kits/api/catalog").status, 200)
        self.assertEqual(self.request("/api/catalog", **{"X-ZZLAB-Role": "readonly"}).status, 200)
        self.assertEqual(self.request("/api/catalog", **{"X-ZZLAB-Internal-Token": "bad"}).status, 401)

    def test_preview_and_download_response(self):
        with self.request("/optics-kits/api/preview", payload()) as response:
            self.assertEqual(json.load(response)["manufacturing"][0]["quantity"], 8)
        with self.request("/api/export?format=lubang", payload()) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("filename*=UTF-8''", response.headers["Content-Disposition"])
            self.assertEqual(response.read(2), b"PK")

    def test_checkout_http_preview_and_export_use_final_selection(self):
        data = payload(checkout={"items": [{"componentId": "optic", "quantity": 19}]})
        with self.request("/api/preview", data) as response:
            preview = json.load(response)
            self.assertEqual(preview["totals"]["componentQuantity"], 19)
            self.assertEqual(preview["manufacturing"], [])
        with self.request("/api/export?format=bundle", data) as response:
            self.assertEqual(response.status, 200)
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                workbook = load_workbook(io.BytesIO(archive.read("麓邦采购.xlsx")))
                self.assertEqual(workbook["Sheet1"]["B4"].value, "OPT-OLD")
                self.assertEqual(workbook["Sheet1"]["C4"].value, 19)
                self.assertFalse(any(name.startswith("自制件/") for name in archive.namelist()))
        data["checkout"]["items"][0]["quantity"] = True
        self.assertEqual(self.request("/api/export?format=lubang", data).status, 400)
        data["checkout"]["items"] = []
        with self.request("/api/export?format=lubang", data) as response:
            self.assertEqual(response.status, 400)
            self.assertEqual(json.load(response)["error"]["code"], "empty_checkout")

    def test_no_arbitrary_download_or_cross_origin(self):
        self.assertEqual(self.request("/api/download?path=/etc/passwd").status, 404)
        self.assertEqual(self.request("/api/export?format=bundle&path=/etc/passwd", payload()).status, 400)
        self.assertEqual(self.request("/api/preview", payload(), Origin="https://unrelated.example").status, 403)
        self.assertEqual(self.request("/api/preview", {"items": [], "assets": ["/etc/passwd"]}).status, 400)
        self.assertEqual(self.request("/%2e%2e/catalog.json").status, 404)


if __name__ == "__main__":
    unittest.main()
