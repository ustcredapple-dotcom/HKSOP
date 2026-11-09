"""Real HTTP and isolated SQLite checks: never contact production shared data."""
import copy
import http.client
import io
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Config, create_server
from bom import APIError, aggregate
from shared_kits import Identity, SharedKitStore, prepare_project, project_payload, strict_json, thumbnail_svg
from test_backend import extra
from test_layout import layout_fixture, request


def project():
    return {"format": "zzlab-optics-project", "version": 1,
            "metadata": {"name": "测试工程", "notes": "保留备注", "createdAt": "2026-09-24T01:02:03.000Z", "updatedAt": "2026-09-24T02:03:04.000Z"},
            "catalogVersion": "test-v1", "layout": request()["layout"], "optical": {}, "extras": [],
            "moduleQuantities": [], "ui": {"mountingSelection": {"rowParity": "odd", "columnParity": "even"}, "view": None, "selectedIds": ["a1"]},
            "catalogReferenced": [{"id": "alpha", "name": "测试套件甲"}, {"id": "beta", "name": "测试套件乙"}]}


def with_module():
    catalog = layout_fixture()
    module = copy.deepcopy(catalog["kits"][0])
    module.update(id="module", name="独立模块")
    module["layout"]["placementAllowed"] = False
    catalog["kits"].append(module)
    return catalog


class SharedPayloadTests(unittest.TestCase):
    def test_project_accounting_matches_canvas_not_module_cart(self):
        p = project()
        p["moduleQuantities"] = [["module", 50]]
        p["optical"] = {"a1::mirror": {"model": "NEW-532", "wavelength": "532", "kind": "standard"},
                        "a2::mirror": {"wavelength": "780"}, "module:module::mirror": {"model": "MODULE-ONLY"}}
        p["extras"] = [extra("global", kind="standard", model="GLOBAL", quantity=3),
                       extra("per-kit", kitId="alpha", model="PER-KIT", quantity=2),
                       extra("per-instance", kitId="alpha", instanceId="a2", model="ONE-INSTANCE", quantity=7),
                       extra("module-extra", kitId="module", model="MODULE-EXTRA", quantity=20)]
        catalog = with_module()
        payload = project_payload(p, catalog)
        result = aggregate(catalog, payload)
        rows = {r["model"]: r["quantity"] for r in result["lubang"] + result["standard"]}
        self.assertEqual(rows, {"OPT-OLD": 4, "PER-KIT": 4, "ONE-INSTANCE": 7, "BOLT-M4": 8, "GLOBAL": 3, "NEW-532": 1})
        self.assertEqual(result["totals"]["kits"], 3)
        self.assertEqual(result["totals"]["boards"], 1)
        self.assertEqual(next(e for e in result["layoutExtras"] if e.get("instanceId") == "a2" and e.get("slotId"))["wavelength"], "780")
        self.assertEqual(p["moduleQuantities"], [["module", 50]])
        self.assertEqual(p["optical"]["a2::mirror"], {"wavelength": "780"})

    def test_catalog_optical_option_forces_vendor_as_canvas_does(self):
        catalog = layout_fixture()
        catalog["opticalOptions"] = [{"model": "KNOWN"}]
        p = project()
        p["optical"] = {"a1::mirror": {"model": " KNOWN ", "kind": "standard"}}
        result = prepare_project(p, catalog)
        self.assertEqual(next(r for r in result["lubang"] if r["model"] == "KNOWN")["quantity"], 1)

    def test_fully_validate_all_references_and_fields(self):
        mutations = [
            lambda p: p.update(version=2), lambda p: p.update(format="other"),
            lambda p: p.update(author={"id": "admin"}),
            lambda p: p["layout"]["board"].update(material="forged", stepPath="/etc/passwd"),
            lambda p: p["layout"]["instances"][0].update(kitId="unknown"),
            lambda p: p["layout"]["instances"][0].update(xMm=float("inf")),
            lambda p: p["layout"]["instances"][0].update(rotationDeg=45),
            lambda p: p["layout"]["instances"][1].update(id="a1"),
            lambda p: p["optical"].update({"ghost::mirror": {"wavelength": "532"}}),
            lambda p: p["optical"].update({"a1::unknown": {"model": "M"}}),
            lambda p: p["optical"].update({"a1::mirror": {"model": "M", "quantity": 5}}),
            lambda p: p["extras"].append(extra(instanceId="ghost", kitId="alpha")),
            lambda p: p["extras"].append(extra(kitId="missing")),
            lambda p: p["ui"].update(selectedIds=["ghost"]),
            lambda p: p["ui"].update(view={"x": 0, "y": 0, "w": 1e-100, "h": 100}),
            lambda p: p["metadata"].update(createdAt="yesterday"),
            lambda p: p["metadata"].update(notes="\ud800"),
            lambda p: p["metadata"].update(constructor={}),
            lambda p: p.update(moduleQuantities=[["alpha", 1]]),
            lambda p: p["catalogReferenced"].append({"id": "alpha", "name": "A", "topViewUrl": "https://evil"}),
        ]
        for mutate in mutations:
            p = project()
            mutate(p)
            with self.subTest(p=p), self.assertRaises(APIError):
                prepare_project(p, layout_fixture())

    def test_empty_colliding_and_offboard_layouts_cannot_publish(self):
        for mutate in (lambda p: p["layout"].update(instances=[]),
                       lambda p: p["layout"]["instances"][1].update(xMm=50, yMm=50),
                       lambda p: p["layout"]["instances"][0].update(xMm=0)):
            p = project()
            mutate(p)
            p["ui"]["selectedIds"] = []
            with self.assertRaises(APIError):
                prepare_project(p, layout_fixture())

    def test_project_version_is_snapshot_but_bom_uses_current_catalog(self):
        p = project()
        p["catalogVersion"] = "older-v0"
        result = prepare_project(p, layout_fixture())
        self.assertEqual(result["catalogVersion"], "test-v1")
        self.assertEqual(p["catalogVersion"], "older-v0")

    def test_strict_json_rejects_ambiguous_or_unsafe_keys(self):
        for raw in ('{"name":1,"name":2}', '{"__proto__":{}}', '{"constructor":1}', '{"x":NaN}', '{"x":Infinity}', '[' * 1100 + ']' * 1100):
            with self.assertRaises(APIError):
                strict_json(raw)


class SharedHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.static = cls.root / "static"
        (cls.static / "topviews").mkdir(parents=True)
        (cls.static / "topviews/test.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="35" height="45" fill="teal"/></svg>')
        cls.catalog = cls.root / "catalog.json"
        cls.catalog.write_text(json.dumps(with_module(), ensure_ascii=False))
        cls.assets = cls.root / "assets"
        cls.assets.mkdir()
        for part in ("plate", "bracket"):
            (cls.assets / (part + ".step")).write_bytes(b"ISO-10303-21; TEST")
            (cls.assets / (part + ".pdf")).write_bytes(b"%PDF TEST")
        cls.backup = cls.root / "backup.sqlite3"
        cls.config = Config(cls.catalog, cls.assets, cls.static, "test-secret", cls.root / "shared.sqlite3", cls.backup)
        cls.server = create_server(cls.config, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.dev = create_server(Config(cls.catalog, cls.assets, cls.static, None, cls.root / "dev.sqlite3"), 0)
        cls.dev_thread = threading.Thread(target=cls.dev.serve_forever, daemon=True)
        cls.dev_thread.start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server, cls.dev):
            server.shutdown()
            server.server_close()
        cls.temp.cleanup()

    def http(self, method, route, body=None, user="101", role="user", headers=None, auth=True, dev=False, raw=None):
        server = self.dev if dev else self.server
        h = {"Host": f"127.0.0.1:{server.server_port}"}
        if auth:
            h.update({"X-ZZLAB-Internal-Token": "test-secret", "X-ZZLAB-Authenticated": "1", "X-ZZLAB-Role": role,
                      "X-ZZLAB-User-ID": user, "X-ZZLAB-User": "login-name", "X-ZZLAB-Display-Name": quote("测试发布者" + user, safe="")})
        if body is not None or raw is not None:
            h.update({"Content-Type": "application/json", "Origin": "https://zzlab.example", "X-Forwarded-Host": "zzlab.example", "X-Forwarded-Proto": "https", "Sec-Fetch-Site": "same-origin"})
        if dev:
            h["Origin"] = f"http://127.0.0.1:{server.server_port}"
        h.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=20)
        conn.request(method, "/optics-kits" + route, body=raw if raw is not None else json.dumps(body, ensure_ascii=False).encode() if body is not None else None, headers=h)
        response = conn.getresponse()
        content, response_headers = response.read(), dict(response.getheaders())
        status = response.status
        conn.close()
        return status, json.loads(content) if response_headers.get("Content-Type", "").startswith("application/json") else content, response_headers

    def publish(self, p=None, **kwargs):
        status, body, _ = self.http("POST", "/api/shared-kits", {"name": "共享测试", "description": "内部复用", "project": p or project()}, **kwargs)
        self.assertEqual(status, 201, body)
        return body

    def test_auth_origin_identity_and_role_are_enforced(self):
        data = {"name": "N", "description": "", "project": project()}
        for method, route, payload in (("GET", "/api/shared-kits", None), ("POST", "/api/shared-kits", data)):
            self.assertEqual(self.http(method, route, payload, auth=False)[0], 401)
            self.assertEqual(self.http(method, route, payload, role="guest")[0], 403)
        self.assertEqual(self.http("POST", "/api/shared-kits", data, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.http("POST", "/api/shared-kits", data, headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        for user in ("", "0", "-1", "abc", "12,13"):
            self.assertEqual(self.http("POST", "/api/shared-kits", data, user=user)[0], 403)
        self.publish()  # The authenticated public proxy origin succeeds.

    def test_list_and_snapshot_download_no_private_ids_or_asset_paths(self):
        p = project()
        p["optical"] = {"a1::mirror": {"wavelength": "532"}, "module:module::mirror": {"model": "MODULE"}}
        p["moduleQuantities"] = [["module", 2]]
        published = self.publish(p)
        kid = published["kit"]["id"]
        self.assertEqual(published["backup"]["status"], "ok")
        self.assertEqual(published["kit"]["author"], {"name": "测试发布者101"})
        self.assertEqual(set(published["kit"]["board"]), {"widthMm", "heightMm"})
        status, saved, headers = self.http("GET", f"/api/shared-kits/{kid}/project", user="202")
        self.assertEqual(status, 200)
        self.assertEqual(saved, p)
        self.assertIn(".zzoptics.json", headers["Content-Disposition"])
        status, svg, _ = self.http("GET", f"/api/shared-kits/{kid}/thumbnail", user="202")
        self.assertEqual(status, 200)
        ElementTree.fromstring(svg)
        self.assertEqual(svg.count(b"data:image/svg+xml;base64,"), 2)  # two kits, three placements
        self.assertEqual(svg.count(b"<use "), 3)
        self.assertNotIn(str(self.root).encode(), svg)
        summary = next(k for k in self.http("GET", "/api/shared-kits", user="202")[1]["kits"] if k["id"] == kid)
        self.assertFalse(summary["canUnpublish"])
        self.assertNotIn("author_id", json.dumps(summary))
        self.assertNotIn("project_json", summary)

    def test_unpublish_ownership_hidden_access_and_restore(self):
        kid = self.publish()["kit"]["id"]
        route = f"/api/shared-kits/{kid}"
        self.assertEqual(self.http("POST", route + "/unpublish", {}, user="202")[0], 403)
        status, result, _ = self.http("POST", route + "/unpublish", {})
        self.assertEqual(status, 200)
        self.assertTrue(result["kit"]["canRestore"])
        for endpoint in ("project", "thumbnail", "bundle"):
            self.assertEqual(self.http("GET", route + "/" + endpoint, user="202")[0], 404)
        status, listing, _ = self.http("GET", "/api/shared-kits")
        self.assertNotIn(kid, [k["id"] for k in listing["kits"]])
        self.assertIn(kid, [k["id"] for k in listing["withdrawn"]])
        self.assertNotIn(kid, [k["id"] for k in self.http("GET", "/api/shared-kits", user="202")[1]["withdrawn"]])
        self.assertEqual(self.http("GET", route + "/project")[0], 200)
        self.assertEqual(self.http("POST", route + "/restore", {}, user="999", role="admin")[0], 200)
        self.assertEqual(self.http("GET", route + "/project", user="202")[0], 200)

    def test_unknown_references_invalid_layout_and_forged_fields_do_not_commit(self):
        before = len(self.http("GET", "/api/shared-kits")[1]["kits"])
        for mutate in (lambda p: p["optical"].update({"missing::mirror": {"model": "M"}}),
                       lambda p: p["layout"]["instances"][1].update(xMm=50, yMm=50),
                       lambda p: p.update(thumbnail="<svg onload='bad()'/>"),
                       lambda p: p["layout"]["board"].update(material="injected")):
            p = project()
            mutate(p)
            status = self.http("POST", "/api/shared-kits", {"name": "Bad", "description": "", "project": p})[0]
            self.assertIn(status, (400, 409))
        self.assertEqual(len(self.http("GET", "/api/shared-kits")[1]["kits"]), before)
        self.assertEqual(self.http("POST", "/api/shared-kits", raw=b'{"name":"a","name":"b"}')[0], 400)

    def test_development_identity_ignores_spoofed_proxy_user_and_admin(self):
        result = self.publish(dev=True, user="999", role="admin")
        self.assertEqual(result["kit"]["author"]["name"], "本地开发")
        row = self.dev.shared_store.get(result["kit"]["id"], Identity("dev", "dev", "user"))
        self.assertEqual(row["author_id"], "dev")

    def test_snapshot_persists_restart_and_sqlite_backup_is_restorable(self):
        kid = self.publish()["kit"]["id"]
        store = SharedKitStore(self.config.shared_db)
        self.assertEqual(json.loads(store.get(kid, Identity("101", "A", "user"))["project_json"]), project())
        with sqlite3.connect(self.backup) as db:
            self.assertEqual(json.loads(db.execute("SELECT project_json FROM shared_kits WHERE id=?", (kid,)).fetchone()[0]), project())
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_concurrent_publishes_preserve_unique_records(self):
        before = len(self.http("GET", "/api/shared-kits")[1]["kits"])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.publish(), range(8)))
        self.assertEqual(len({r["kit"]["id"] for r in results}), 8)
        self.assertEqual(len(self.http("GET", "/api/shared-kits")[1]["kits"]), before + 8)
        self.assertTrue(all(r["backup"]["status"] == "ok" for r in results))

    def test_backup_failure_keeps_single_committed_publish_without_mkdir(self):
        bad_parent = self.root / "unmounted-nas" / "backup"
        original = self.server.shared_store.backup_path
        try:
            self.server.shared_store.backup_path = bad_parent / "shared.sqlite3"
            result = self.publish()
            self.assertEqual(result["backup"]["status"], "warning")
            self.assertFalse(bad_parent.parent.exists())
            self.assertEqual(self.http("GET", f'/api/shared-kits/{result["kit"]["id"]}/project')[0], 200)
            self.assertNotIn(str(bad_parent), json.dumps(result))
        finally:
            self.server.shared_store.backup_path = original

    def test_bundle_uses_current_catalog_and_only_canvas_scope(self):
        p = project()
        p["catalogVersion"] = "older-snapshot"
        p["moduleQuantities"] = [["module", 9999]]
        p["optical"] = {"module:module::mirror": {"model": "NOT-ON-CANVAS"}, "a1::mirror": {"wavelength": "532"}}
        kid = self.publish(p)["kit"]["id"]
        def generate(board, cache):
            from breadboard import board_specs
            spec = board_specs(board)
            target = Path(cache)
            target.mkdir(parents=True, exist_ok=True)
            step, drawing = target / "board.step", target / "board.pdf"
            step.write_bytes(b"ISO-10303-21; TEST BOARD")
            drawing.write_bytes(b"%PDF TEST BOARD")
            return {"step": step, "drawing": drawing, "spec": spec, "componentId": spec["componentId"]}
        with patch.dict("os.environ", {"ZZLAB_BOARD_CACHE": str(self.root / "board-cache")}), patch("breadboard.ensure_board_artifacts", side_effect=generate):
            status, content, headers = self.http("GET", f"/api/shared-kits/{kid}/bundle")
        self.assertEqual(status, 200, content)
        self.assertEqual(headers["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(json.loads(archive.read("共享套件工程.zzoptics.json")), p)
            current = json.loads(archive.read("光路布局.json"))
            self.assertEqual(current["catalogVersion"], "test-v1")
            self.assertEqual(aggregate(with_module(), current)["totals"]["kits"], 3)
            self.assertEqual(aggregate(with_module(), current)["totals"]["boards"], 1)
            self.assertNotIn("NOT-ON-CANVAS", archive.read("光路布局.json").decode())
            self.assertIn("older-snapshot", archive.read("共享套件说明.txt").decode())
            self.assertIn("生产清单.xlsx", archive.namelist())


class SharedBackupTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.nas = self.root / "nas"
        self.nas.mkdir()
        self.source = self.root / "source.sqlite3"
        self.target = self.nas / "backup.sqlite3"
        self.store = SharedKitStore(self.source, self.target)
        # Keep a live writer connection so committed content still lives in WAL.
        self.writer = sqlite3.connect(self.source)
        self.writer.execute("PRAGMA journal_mode=WAL")
        self.writer.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
        self.writer.execute("INSERT INTO evidence VALUES ('committed WAL record')")
        self.writer.commit()
        self.connect = sqlite3.connect
        self.opened = []

    def tearDown(self):
        self.writer.close()
        self.temp.cleanup()

    def local_only_connect(self, path, *args, **kwargs):
        target = Path(path)
        self.assertFalse(target.is_relative_to(self.nas), "SQLite must never open a file on the NAS")
        self.opened.append(target)
        return self.connect(path, *args, **kwargs)

    def test_local_snapshot_transports_committed_wal_without_network_sqlite(self):
        self.assertTrue(Path(str(self.source) + "-wal").is_file())
        with patch("shared_kits.sqlite3.connect", side_effect=self.local_only_connect):
            self.assertEqual(self.store.backup(), {"status": "ok"})
        # Verify by copying the archive back locally, just as a real restore does.
        restored = self.root / "restored.sqlite3"
        restored.write_bytes(self.target.read_bytes())
        with self.connect(restored) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(db.execute("SELECT value FROM evidence").fetchone()[0], "committed WAL record")
        snapshots = [p for p in self.opened if p.name == "snapshot.sqlite3"]
        self.assertEqual(len(snapshots), 1)
        self.assertFalse(snapshots[0].parent.exists())
        self.assertEqual(list(self.nas.iterdir()), [self.target])

    def test_copy_fsync_and_replace_failure_preserve_previous_backup_and_cleanup(self):
        self.target.write_bytes(b"previous complete backup")
        def broken_copy(incoming, output, **kwargs):
            output.write(b"incomplete")
            raise OSError("network interrupted")
        for target, failure in (("shared_kits.shutil.copyfileobj", broken_copy),
                                ("shared_kits.os.fsync", OSError("network fsync failed")),
                                ("shared_kits.os.replace", OSError("network rename failed"))):
            self.opened.clear()
            with self.subTest(target=target), patch("shared_kits.sqlite3.connect", side_effect=self.local_only_connect), patch(target, side_effect=failure):
                result = self.store.backup()
            self.assertEqual(result["status"], "warning")
            self.assertEqual(self.target.read_bytes(), b"previous complete backup")
            self.assertEqual(list(self.nas.iterdir()), [self.target])
            self.assertTrue(all(not p.parent.exists() for p in self.opened if p.name == "snapshot.sqlite3"))


if __name__ == "__main__":
    unittest.main()
