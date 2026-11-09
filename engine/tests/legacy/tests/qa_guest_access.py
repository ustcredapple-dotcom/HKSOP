"""Independent login-required/readonly HTTP QA after guest access was removed. All data and server sockets are temporary.

The CAD worker is replaced by test artifacts so these checks measure access and
packaging, not STEP/PDF geometry. No production service or database is contacted.
Run from the project with the CAD Python runtime; evidence is written locally.
"""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import Config, PUBLIC_STATIC_FILES, create_server
from breadboard import board_specs
from test_layout import request
from test_shared_kits import project, with_module


class GuestAccessQA(unittest.TestCase):
    requests_made = 0

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="zzlab-guest-independent-")
        cls.root = Path(cls.temp.name)
        cls.static = cls.root / "static"
        (cls.static / "topviews").mkdir(parents=True)
        for filename in PUBLIC_STATIC_FILES:
            (cls.static / filename).write_text("<!doctype html><title>Temporary QA</title>" if filename.endswith(".html") else "/* temporary QA */")
        (cls.static / "private.html").write_text("PRIVATE TEST FILE")
        (cls.static / "topviews" / "test.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="35" height="45" fill="teal"/></svg>')
        (cls.static / "topviews" / "private.html").write_text("PRIVATE TEST FILE")
        cls.catalog = cls.root / "catalog.json"
        cls.catalog.write_text(json.dumps(with_module(), ensure_ascii=False))
        cls.assets = cls.root / "assets"
        cls.assets.mkdir()
        for part in ("plate", "bracket"):
            (cls.assets / f"{part}.step").write_bytes(b"ISO-10303-21; QA FIXTURE")
            (cls.assets / f"{part}.pdf").write_bytes(b"%PDF QA FIXTURE")
        cls.config = Config(cls.catalog, cls.assets, cls.static, "independent-test-token", cls.root / "shared.sqlite3", cls.root / "backup.sqlite3")
        cls.env_patch = patch.dict(os.environ, {"ZZLAB_BOARD_CACHE": str(cls.root / "board-cache")})
        cls.env_patch.start()
        cls.cad_patch = patch("breadboard.ensure_board_artifacts", side_effect=cls.fake_board)
        cls.cad_patch.start()
        cls.server = create_server(cls.config, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        status, data, _ = cls.http("POST", "/api/shared-kits", cls.publish_payload(), role="user")
        assert status == 201, data
        cls.active_id = data["kit"]["id"]
        status, data, _ = cls.http("POST", "/api/shared-kits", cls.publish_payload(), role="user")
        assert status == 201, data
        cls.hidden_id = data["kit"]["id"]
        status, data, _ = cls.http("POST", f"/api/shared-kits/{cls.hidden_id}/unpublish", {}, role="user")
        assert status == 200, data

    @staticmethod
    def fake_board(board, cache):
        spec = board_specs(board)
        target = Path(cache)
        target.mkdir(parents=True, exist_ok=True)
        step, drawing = target / "board.step", target / "board.pdf"
        step.write_bytes(b"ISO-10303-21; QA BOARD FIXTURE")
        drawing.write_bytes(b"%PDF QA BOARD FIXTURE")
        return {"step": step, "drawing": drawing, "spec": spec, "componentId": spec["componentId"]}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.cad_patch.stop()
        cls.env_patch.stop()
        cls.temp.cleanup()

    @staticmethod
    def publish_payload():
        return {"name": "临时登录权限验收", "description": "仅临时数据库", "project": project()}

    @classmethod
    def http(cls, method, route, body=None, role="guest", user="101", auth=True, headers=None, duplicates=()):
        cls.requests_made += 1
        h = {"Host": f"127.0.0.1:{cls.server.server_port}"}
        if auth:
            h.update({"X-ZZLAB-Internal-Token": "independent-test-token", "X-ZZLAB-Role": role})
            if role == "guest":
                h["X-ZZLAB-Guest"] = "1"
            else:
                h.update({"X-ZZLAB-Authenticated": "1", "X-ZZLAB-User-ID": user})
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        if data is not None:
            h.update({"Content-Type": "application/json", "Content-Length": str(len(data)),
                      "Origin": "https://qa.zzlab.example", "X-Forwarded-Host": "qa.zzlab.example",
                      "X-Forwarded-Proto": "https", "Sec-Fetch-Site": "same-origin"})
        for key, value in (headers or {}).items():
            if value is None:
                h.pop(key, None)
            else:
                h[key] = value
        conn = http.client.HTTPConnection("127.0.0.1", cls.server.server_port, timeout=20)
        conn.putrequest(method, "/optics-kits" + route, skip_host=True, skip_accept_encoding=True)
        for key, value in list(h.items()) + list(duplicates):
            conn.putheader(key, value)
        conn.endheaders(data)
        response = conn.getresponse()
        content, status, response_headers = response.read(), response.status, dict(response.getheaders())
        conn.close()
        if response_headers.get("Content-Type", "").startswith("application/json"):
            content = json.loads(content)
        return status, content, response_headers

    def database_snapshot(self):
        with sqlite3.connect(self.config.shared_db) as db:
            return tuple(tuple(db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()) for table in ("shared_kits", "shared_actions"))

    def test_01_editor_catalog_session_and_all_public_assets(self):
        before = self.database_snapshot()
        for role in ("readonly",):
            with self.subTest(role=role):
                status, data, _ = self.http("GET", "/api/session", role=role)
                self.assertEqual(status, 200)
                self.assertEqual(data, {"role": role, "canPublish": False, "canDownload": True, "canDownloadManufacturing": True})
                for route in ["/", "/api/catalog", "/topviews/test.svg"] + ["/" + name for name in PUBLIC_STATIC_FILES]:
                    self.assertEqual(self.http("GET", route, role=role)[0], 200, (role, route))
        self.assertEqual(self.database_snapshot(), before)

    def test_02_active_shared_reads_and_complete_bundle(self):
        before = self.database_snapshot()
        for role in ("readonly",):
            with self.subTest(role=role):
                status, data, _ = self.http("GET", "/api/shared-kits", role=role)
                self.assertEqual(status, 200)
                self.assertEqual(data["withdrawn"], [])
                summary = next(k for k in data["kits"] if k["id"] == self.active_id)
                self.assertFalse(summary["canUnpublish"])
                self.assertFalse(summary.get("canRestore", False))
                self.assertNotIn("author_id", json.dumps(data))
                base = f"/api/shared-kits/{self.active_id}"
                status, saved, headers = self.http("GET", base + "/project", role=role)
                self.assertEqual(status, 200)
                self.assertEqual(saved, project())
                self.assertIn(".zzoptics.json", headers["Content-Disposition"])
                status, svg, _ = self.http("GET", base + "/thumbnail", role=role)
                self.assertEqual(status, 200)
                ElementTree.fromstring(svg)
                status, content, headers = self.http("GET", base + "/bundle", role=role)
                self.assertEqual(status, 200, content)
                self.assertEqual(headers["Content-Type"], "application/zip")
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertEqual(json.loads(archive.read("共享套件工程.zzoptics.json")), project())
                    for filename in ("生产清单.xlsx", "麓邦采购.xlsx", "光路布局.json", "光路总俯视图.svg"):
                        self.assertIn(filename, archive.namelist())
                    self.assertTrue(any(n.endswith(".step") for n in archive.namelist()))
                    self.assertTrue(any(n.endswith(".pdf") for n in archive.namelist()))
        self.assertEqual(self.database_snapshot(), before)

    def test_03_stateless_preview_exports_and_mounting_holes(self):
        before = self.database_snapshot()
        for role in ("readonly",):
            with self.subTest(role=role):
                status, data, _ = self.http("POST", "/api/preview", request(), role=role)
                self.assertEqual(status, 200, data)
                self.assertEqual(data["totals"]["kits"], 3)
                status, data, _ = self.http("POST", "/api/mounting-holes", {**request(), "rowParity": "odd", "columnParity": "odd"}, role=role)
                self.assertEqual(status, 200, data)
                self.assertEqual(len(data["board"]["mountingHoles"]), 4)
                for fmt in ("lubang", "manufacturing", "bundle", "layout-json", "layout-svg"):
                    status, content, headers = self.http("POST", f"/api/export?format={fmt}", request(), role=role)
                    self.assertEqual(status, 200, (role, fmt, content))
                    self.assertIn("attachment", headers["Content-Disposition"])
                    self.assertEqual(headers["Cache-Control"], "no-store")
                    if fmt in ("lubang", "manufacturing", "bundle"):
                        with zipfile.ZipFile(io.BytesIO(content)) as archive:
                            self.assertIsNone(archive.testzip())
                    elif fmt == "layout-json":
                        self.assertEqual(len(content["layout"]["instances"]), 3)
                    else:
                        ElementTree.fromstring(content)
        self.assertEqual(self.database_snapshot(), before)

    def test_04_limited_owner_cannot_publish_manage_or_see_hidden(self):
        before = self.database_snapshot()
        for role in ("readonly",):
            # The readonly identity is the same user who originally published
            # the hidden record. A supplied owner ID cannot restore privileges.
            owner_headers = {"X-ZZLAB-User-ID": "101", "X-ZZLAB-Display-Name": "administrator"}
            for route, body in (("/api/shared-kits", self.publish_payload()),
                                (f"/api/shared-kits/{self.active_id}/unpublish", {}),
                                (f"/api/shared-kits/{self.hidden_id}/restore", {})):
                status, data, _ = self.http("POST", route, body, role=role, headers=owner_headers)
                self.assertEqual(status, 403, data)
            for action in ("project", "thumbnail", "bundle"):
                self.assertEqual(self.http("GET", f"/api/shared-kits/{self.hidden_id}/{action}", role=role, headers=owner_headers)[0], 404)
            data = self.http("GET", "/api/shared-kits", role=role, headers=owner_headers)[1]
            self.assertNotIn(self.hidden_id, json.dumps(data))
            self.assertEqual(data["withdrawn"], [])
        self.assertEqual(self.database_snapshot(), before)

    def test_05_even_trusted_guest_markers_cannot_grant_access(self):
        before = self.database_snapshot()
        routes = [("GET", path, None) for path in ("/", "/index.html", "/app.js", "/topviews/test.svg", "/api/catalog", "/api/session", "/api/shared-kits",
                  f"/api/shared-kits/{self.active_id}/project", f"/api/shared-kits/{self.active_id}/thumbnail", f"/api/shared-kits/{self.active_id}/bundle")]
        routes += [("POST", path, request()) for path in ("/api/preview", "/api/mounting-holes", "/api/export?format=bundle", "/api/export?format=lubang", "/api/export?format=manufacturing", "/api/export?format=layout-json", "/api/export?format=layout-svg")]
        routes += [("POST", path, {}) for path in ("/api/shared-kits", f"/api/shared-kits/{self.active_id}/unpublish", f"/api/shared-kits/{self.hidden_id}/restore")]
        variants = [
            {},  # Previously accepted trusted guest contract is now rejected.
            {"auth": False},
            {"auth": False, "headers": {"X-ZZLAB-Guest": "1", "X-ZZLAB-Role": "guest"}},
            {"headers": {"X-ZZLAB-Internal-Token": "wrong-token"}},
            {"duplicates": [("X-ZZLAB-Internal-Token", "independent-test-token")]},
            {"duplicates": [("X-ZZLAB-Role", "guest")]},
            {"duplicates": [("X-ZZLAB-Guest", "1")]},
            {"headers": {"X-ZZLAB-Authenticated": "1"}},
            {"headers": {"X-ZZLAB-Authenticated": "0"}},
            {"headers": {"X-ZZLAB-Guest": "true"}},
            {"headers": {"X-ZZLAB-Role": "admin"}},
        ]
        for variant in variants:
            for method, route, payload in routes:
                self.assertEqual(self.http(method, route, payload, **variant)[0], 401, (variant, route))
        for role in ("readonly", "user", "admin"):
            for marker in ("1", "0", "", "true"):
                status, data, _ = self.http("GET", "/api/session", role=role, headers={"X-ZZLAB-Guest": marker})
                self.assertEqual(status, 401, (role, marker, data))
        self.assertEqual(self.database_snapshot(), before)

    def test_06_readonly_invalid_claims_and_bounded_routes(self):
        before = self.database_snapshot()
        for variant in ({"headers": {"X-ZZLAB-Authenticated": None}},
                        {"headers": {"X-ZZLAB-Authenticated": "0"}},
                        {"duplicates": [("X-ZZLAB-Authenticated", "1")]},
                        {"duplicates": [("X-ZZLAB-Role", "admin")]}):
            self.assertEqual(self.http("GET", "/api/session", role="readonly", **variant)[0], 401)
        for role in ("readonly",):
            for route in ("/private.html", "/topviews/private.html", "/api/future-management", "/api/shared-kits/" + self.active_id + "/unpublish",
                          "/topviews/%2e%2e/private.html", "/api/shared-kits/not-an-id/project"):
                self.assertEqual(self.http("GET", route, role=role)[0], 404, route)
            for route in ("/api/future-management", "/api/preview/", "/api/export/future", "/api/mounting-holes/future"):
                self.assertEqual(self.http("POST", route, {}, role=role)[0], 403, route)
        self.assertEqual(self.database_snapshot(), before)

    def test_07_cross_origin_and_cross_site_remain_denied(self):
        before = self.database_snapshot()
        for role in ("readonly",):
            for route in ("/api/preview", "/api/export?format=layout-json", "/api/mounting-holes"):
                for variant in ({"headers": {"Origin": "https://unrelated.example"}},
                                {"headers": {"Sec-Fetch-Site": "cross-site"}},
                                {"duplicates": [("Origin", "https://qa.zzlab.example")]},
                                {"duplicates": [("X-Forwarded-Host", "qa.zzlab.example")]}):
                    self.assertEqual(self.http("POST", route, request(), role=role, **variant)[0], 403, (role, route, variant))
        self.assertEqual(self.database_snapshot(), before)

    def test_08_normal_user_and_admin_management_still_work(self):
        for role in ("user", "admin"):
            self.assertEqual(self.http("GET", "/api/session", role=role)[1], {"role": role, "canPublish": True, "canDownload": True, "canDownloadManufacturing": True})
            self.assertFalse(self.http("GET", "/api/session", role=role, user="")[1]["canPublish"])
        status, data, _ = self.http("POST", "/api/shared-kits", self.publish_payload(), role="user")
        self.assertEqual(status, 201, data)
        base = f'/api/shared-kits/{data["kit"]["id"]}'
        self.assertEqual(self.http("POST", base + "/unpublish", {}, role="user", user="202")[0], 403)
        self.assertEqual(self.http("POST", base + "/unpublish", {}, role="user")[0], 200)
        self.assertEqual(self.http("GET", base + "/project", role="readonly")[0], 404)
        self.assertEqual(self.http("GET", base + "/project", role="user")[0], 200)
        self.assertEqual(self.http("POST", base + "/restore", {}, role="admin", user="999")[0], 200)
        self.assertEqual(self.http("GET", base + "/project", role="guest")[0], 401)


if __name__ == "__main__":
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GuestAccessQA))
    paths = ["app.py", "shared_kits.py", "tests/qa_guest_access.py"]
    evidence = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "passed": result.wasSuccessful(), "testGroups": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors),
        "httpRequests": GuestAccessQA.requests_made,
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "sourceSHA256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths},
        "scope": ["anonymous and any guest-marker access denied, including valid internal tokens", "authenticated readonly editor and active downloads", "stateless preview / every export format / mounting-hole selection",
                  "hidden records denied even for original readonly author", "publish / unpublish / restore denied for limited roles",
                  "missing / wrong / duplicated trusted claims", "cross-origin denial and exact route allowlist", "ordinary owner / administrator positive controls"],
        "databaseIsolation": "ephemeral TemporaryDirectory; loopback ephemeral port; production records created: 0",
        "limits": ["CAD worker substituted with fixture STEP/PDF bytes; packaging and permission behavior are real",
                   "Tests invoke the trusted backend boundary; public router header stripping and browser UI are separate root verification",
                   "SharedKitStore is internal and trusts sanitized Handler identities; direct library calls are outside this HTTP contract"],
    }
    (ROOT / "data_evidence" / "login_required_independent_qa.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    sys.exit(0 if result.wasSuccessful() else 1)
