"""Isolated independent access-toggle QA; never enables production guest access."""
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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import Config, create_server
from breadboard import board_specs
from test_layout import request
from test_shared_kits import project, with_module


class AccessToggleQA(unittest.TestCase):
    requests_made = 0

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zzlab-toggle-independent-")
        self.root = Path(self.temp.name)
        static = self.root / "static"
        (static / "topviews").mkdir(parents=True)
        (static / "index.html").write_text("<title>Isolated toggle QA</title>")
        (static / "app.js").write_text("/* isolated QA */")
        (static / "topviews/test.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="35" height="45"/></svg>')
        catalog = self.root / "catalog.json"
        catalog.write_text(json.dumps(with_module(), ensure_ascii=False))
        assets = self.root / "assets"
        assets.mkdir()
        for part in ("plate", "bracket"):
            (assets / f"{part}.step").write_bytes(b"ISO-10303-21; QA FIXTURE")
            (assets / f"{part}.pdf").write_bytes(b"%PDF QA FIXTURE")
        self.config = Config(catalog, assets, static, "isolated-policy-token", self.root / "shared.sqlite3", self.root / "backup.sqlite3")
        self.environment = patch.dict(os.environ, {"ZZLAB_BOARD_CACHE": str(self.root / "board-cache")})
        self.environment.start()
        self.cad = patch("breadboard.ensure_board_artifacts", side_effect=self.fake_board)
        self.cad.start()
        self.start_server()

    def start_server(self):
        self.server = create_server(self.config, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def tearDown(self):
        self.stop_server()
        self.cad.stop()
        self.environment.stop()
        self.temp.cleanup()

    @staticmethod
    def fake_board(board, cache):
        spec = board_specs(board)
        target = Path(cache)
        target.mkdir(parents=True, exist_ok=True)
        step, drawing = target / "board.step", target / "board.pdf"
        step.write_bytes(b"ISO-10303-21; QA BOARD")
        drawing.write_bytes(b"%PDF QA BOARD")
        return {"step": step, "drawing": drawing, "spec": spec, "componentId": spec["componentId"]}

    def http(self, method, path, body=None, role="admin", user="101", headers=None, duplicates=()):
        type(self).requests_made += 1
        h = {"Host": f"127.0.0.1:{self.server.server_port}"}
        if role is not None:
            h.update({"X-ZZLAB-Internal-Token": "isolated-policy-token", "X-ZZLAB-Role": role})
            if role == "guest":
                h["X-ZZLAB-Guest"] = "1"
            else:
                h.update({"X-ZZLAB-Authenticated": "1", "X-ZZLAB-User-ID": user})
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        if data is not None:
            h.update({"Content-Type": "application/json", "Content-Length": str(len(data)),
                      "Origin": "https://toggle.qa.example", "X-Forwarded-Host": "toggle.qa.example",
                      "X-Forwarded-Proto": "https", "Sec-Fetch-Site": "same-origin"})
        for key, value in (headers or {}).items():
            if value is None:
                h.pop(key, None)
            else:
                h[key] = value
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=20)
        conn.putrequest(method, path if path.startswith("/internal/") else "/optics-kits" + path,
                        skip_host=True, skip_accept_encoding=True)
        for key, value in list(h.items()) + list(duplicates):
            conn.putheader(key, value)
        conn.endheaders(data)
        response = conn.getresponse()
        status, content, rh = response.status, response.read(), dict(response.getheaders())
        conn.close()
        if rh.get("Content-Type", "").startswith("application/json"):
            content = json.loads(content)
        return status, content, rh

    def setting(self):
        status, value, _ = self.http("GET", "/api/admin/guest-access")
        self.assertEqual(status, 200, value)
        return value

    def toggle(self, enabled, revision=None):
        if revision is None:
            revision = self.setting()["revision"]
        return self.http("POST", "/api/admin/guest-access", {"guestAccessEnabled": enabled, "revision": revision})

    def probe(self, headers=None, duplicates=()):
        h = {"X-ZZLAB-Internal-Token": "isolated-policy-token", "X-ZZLAB-Policy-Probe": "1"}
        h.update(headers or {})
        return self.http("GET", "/internal/guest-access", role=None, headers=h, duplicates=duplicates)

    def publish(self):
        status, data, _ = self.http("POST", "/api/shared-kits", {"name": "临时开关验收", "description": "无生产数据", "project": project()}, role="user")
        self.assertEqual(status, 201, data)
        return data["kit"]["id"]

    def shared_snapshot(self):
        with sqlite3.connect(self.config.shared_db) as db:
            return tuple(tuple(db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()) for table in ("shared_kits", "shared_actions"))

    def test_01_fresh_default_off_and_no_session_escalation(self):
        self.assertEqual(self.setting(), {"guestAccessEnabled": False, "guestManufacturingDownloadsEnabled": True, "revision": 0, "updatedAt": None})
        self.assertFalse(self.probe()[1]["guestAccessEnabled"])
        for role in (None, "guest"):
            for path in ("/", "/app.js", "/api/session", "/api/catalog", "/api/shared-kits"):
                self.assertEqual(self.http("GET", path, role=role)[0], 401, (role, path))
            self.assertEqual(self.http("POST", "/api/preview", request(), role=role)[0], 401)
        for role in ("readonly", "user", "admin"):
            status, data, _ = self.http("GET", "/api/session", role=role)
            self.assertEqual(status, 200)
            self.assertEqual(data["role"], role)
            self.assertEqual(data["canPublish"], role != "readonly")
            self.assertTrue(data["canDownload"])

    def test_02_enable_guest_use_download_but_no_session_privileges(self):
        status, setting, _ = self.toggle(True)
        self.assertEqual(status, 200, setting)
        self.assertEqual(setting["revision"], 1)
        self.assertTrue(setting["guestAccessEnabled"])
        self.assertTrue(self.probe()[1]["guestAccessEnabled"])
        before = self.shared_snapshot()
        status, session, _ = self.http("GET", "/api/session", role="guest")
        self.assertEqual(status, 200)
        self.assertEqual(session["role"], "guest")
        self.assertFalse(session["canPublish"])
        self.assertTrue(session["canDownload"])
        for path in ("/", "/app.js", "/api/catalog", "/api/shared-kits"):
            self.assertEqual(self.http("GET", path, role="guest")[0], 200, path)
        for role in ("guest", "readonly"):
            self.assertEqual(self.http("POST", "/api/preview", request(), role=role)[0], 200)
            self.assertEqual(self.http("POST", "/api/mounting-holes", request(), role=role)[0], 200)
            for fmt in ("lubang", "manufacturing", "bundle", "layout-json", "layout-svg"):
                status, content, headers = self.http("POST", "/api/export?format=" + fmt, request(), role=role)
                self.assertEqual(status, 200, (role, fmt, content))
                self.assertIn("attachment", headers["Content-Disposition"])
                if fmt in ("lubang", "manufacturing", "bundle"):
                    with zipfile.ZipFile(io.BytesIO(content)) as archive:
                        self.assertIsNone(archive.testzip())
        self.assertEqual(self.shared_snapshot(), before)
        # Enabling access does not let an untrusted direct request claim guest.
        self.assertEqual(self.http("GET", "/api/catalog", role=None)[0], 401)

    def test_03_close_revokes_same_headers_immediately_readonly_survives(self):
        self.assertEqual(self.toggle(True)[0], 200)
        self.assertEqual(self.http("GET", "/api/catalog", role="guest")[0], 200)
        self.assertEqual(self.toggle(False)[0], 200)
        self.assertFalse(self.probe()[1]["guestAccessEnabled"])
        for path in ("/", "/api/session", "/api/catalog", "/api/shared-kits"):
            self.assertEqual(self.http("GET", path, role="guest")[0], 401)
            self.assertEqual(self.http("GET", path, role="readonly")[0], 200)
        for path in ("/api/preview", "/api/export?format=manufacturing", "/api/mounting-holes"):
            self.assertEqual(self.http("POST", path, request(), role="guest")[0], 401)
            self.assertEqual(self.http("POST", path, request(), role="readonly")[0], 200)

    def test_04_publish_hidden_and_admin_routes_stay_private_when_on(self):
        active, hidden = self.publish(), self.publish()
        self.assertEqual(self.http("POST", f"/api/shared-kits/{hidden}/unpublish", {}, role="user")[0], 200)
        self.assertEqual(self.toggle(True)[0], 200)
        before = self.shared_snapshot()
        for role in ("guest", "readonly"):
            listing = self.http("GET", "/api/shared-kits", role=role)[1]
            self.assertNotIn(hidden, json.dumps(listing))
            self.assertEqual(listing["withdrawn"], [])
            for action in ("project", "thumbnail", "bundle"):
                self.assertEqual(self.http("GET", f"/api/shared-kits/{active}/{action}", role=role)[0], 200)
                self.assertEqual(self.http("GET", f"/api/shared-kits/{hidden}/{action}", role=role)[0], 404)
            for path in ("/api/shared-kits", f"/api/shared-kits/{active}/unpublish", f"/api/shared-kits/{hidden}/restore"):
                self.assertEqual(self.http("POST", path, {}, role=role)[0], 403)
            self.assertIn(self.http("GET", "/api/admin/guest-access", role=role)[0], (403, 404))
            self.assertEqual(self.http("POST", "/api/admin/guest-access", {"guestAccessEnabled": False, "revision": 1}, role=role)[0], 403)
        # A trusted guest claim cannot carry an owner ID or authenticated name.
        for field in ("X-ZZLAB-User-ID", "X-ZZLAB-User", "X-ZZLAB-Display-Name", "X-ZZLAB-Authenticated"):
            self.assertEqual(self.http("GET", f"/api/shared-kits/{hidden}/project", role="guest", headers={field: "101"})[0], 401)
        self.assertEqual(self.shared_snapshot(), before)

    def test_05_only_stable_admin_can_change_policy_and_origin_is_checked(self):
        before = self.setting()
        body = {"guestAccessEnabled": True, "revision": 0}
        for role in (None, "readonly", "user", "guest"):
            self.assertIn(self.http("POST", "/api/admin/guest-access", body, role=role)[0], (401, 403))
        for user in ("", "0", "-1", "NaN", "1,2"):
            self.assertEqual(self.http("GET", "/api/admin/guest-access", user=user)[0], 403)
            self.assertEqual(self.http("POST", "/api/admin/guest-access", body, user=user)[0], 403)
        for kwargs in ({"headers": {"Origin": "https://unrelated.example"}},
                       {"headers": {"Sec-Fetch-Site": "cross-site"}},
                       {"duplicates": [("Origin", "https://toggle.qa.example")]},
                       {"duplicates": [("X-ZZLAB-Role", "admin")]},
                       {"duplicates": [("X-ZZLAB-User-ID", "101")]}):
            self.assertIn(self.http("POST", "/api/admin/guest-access", body, **kwargs)[0], (401, 403))
        self.assertEqual(self.http("GET", "/api/admin/guest-access", headers={"Origin": "https://unrelated.example"})[0], 403)
        self.assertEqual(self.setting(), before)

    def test_06_strict_boolean_revision_and_atomic_conflict(self):
        before = self.setting()
        invalid = [{"guestAccessEnabled": value, "revision": 0} for value in (0, 1, "true", None, [], {})]
        invalid += [{"guestAccessEnabled": True, "revision": value} for value in (True, False, "0", -1, 0.5, None)]
        invalid += [{"guestAccessEnabled": True}, {"guestAccessEnabled": True, "revision": 0, "material": "forged"}]
        for body in invalid:
            self.assertEqual(self.http("POST", "/api/admin/guest-access", body)[0], 400, body)
        self.assertEqual(self.setting(), before)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.toggle(True, 0), range(2)))
        self.assertEqual(sorted(r[0] for r in results), [200, 409])
        loser = next(r[1] for r in results if r[0] == 409)
        self.assertEqual(loser["error"]["code"], "access_settings_conflict")
        self.assertEqual(self.setting()["revision"], 1)
        self.assertTrue(self.setting()["guestAccessEnabled"])
        self.assertEqual(self.toggle(False, 0)[0], 409)
        self.assertTrue(self.setting()["guestAccessEnabled"])

    def test_07_internal_probe_isolated_from_session_and_spoofing(self):
        self.assertEqual(self.probe()[0], 200)
        variants = [{"X-ZZLAB-Internal-Token": None}, {"X-ZZLAB-Internal-Token": "wrong"},
                    {"X-ZZLAB-Policy-Probe": None}, {"X-ZZLAB-Policy-Probe": "true"},
                    {"X-ZZLAB-Role": "admin"}, {"X-ZZLAB-Authenticated": "1"},
                    {"X-ZZLAB-Guest": "1"}, {"X-ZZLAB-User-ID": "101"},
                    {"Origin": "https://toggle.qa.example"}, {"X-Forwarded-Host": "toggle.qa.example"}]
        for headers in variants:
            self.assertNotEqual(self.probe(headers=headers)[0], 200, headers)
        for key, value in (("X-ZZLAB-Policy-Probe", "1"), ("X-ZZLAB-Internal-Token", "isolated-policy-token")):
            self.assertNotEqual(self.probe(duplicates=[(key, value)])[0], 200)
        for role in ("readonly", "user", "admin"):
            self.assertNotEqual(self.http("GET", "/internal/guest-access", role=role)[0], 200)
        self.assertFalse(self.setting()["guestAccessEnabled"])

    def test_08_setting_and_backup_survive_restart(self):
        status, changed, _ = self.toggle(True)
        self.assertEqual(status, 200, changed)
        self.assertEqual(changed["backup"]["status"], "ok")
        self.assertTrue(self.config.shared_backup.is_file())
        with sqlite3.connect(self.config.shared_backup) as backup:
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        before = self.setting()
        self.stop_server()
        self.start_server()
        self.assertEqual(self.setting(), before)
        self.assertEqual(self.http("GET", "/api/catalog", role="guest")[0], 200)
        self.assertEqual(self.toggle(False)[0], 200)
        before = self.setting()
        self.stop_server()
        self.start_server()
        self.assertEqual(self.setting(), before)
        self.assertEqual(self.http("GET", "/api/catalog", role="guest")[0], 401)

    def test_09_unavailable_or_corrupt_settings_fail_closed(self):
        self.assertEqual(self.toggle(True)[0], 200)
        with patch.object(self.server.shared_store, "connect", side_effect=sqlite3.OperationalError("isolated test failure")):
            status, policy, _ = self.probe()
            self.assertEqual(status, 200)
            self.assertEqual(policy, {"guestAccessEnabled": False})
            self.assertEqual(self.http("GET", "/api/catalog", role="guest")[0], 401)
            self.assertEqual(self.http("GET", "/api/admin/guest-access")[0], 503)
            # Core member catalog does not depend on the guest policy store.
            self.assertEqual(self.http("GET", "/api/catalog", role="readonly")[0], 200)
        self.assertTrue(self.setting()["guestAccessEnabled"])
        with sqlite3.connect(self.config.shared_db) as db:
            db.execute("UPDATE optics_access_settings SET updated_at='invalid timestamp' WHERE singleton=1")
        self.assertEqual(self.probe()[1], {"guestAccessEnabled": False})
        self.assertEqual(self.http("GET", "/api/catalog", role="guest")[0], 401)
        self.assertEqual(self.http("GET", "/api/admin/guest-access")[0], 503)
        self.assertEqual(self.toggle(False, 1)[0], 503)


if __name__ == "__main__":
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AccessToggleQA))
    sources = ("app.py", "access_settings.py", "shared_kits.py", "deploy_support.py", "tests/qa_access_toggle.py")
    evidence = {
        "createdAt": datetime.now(timezone.utc).isoformat(), "passed": result.wasSuccessful(),
        "testGroups": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "httpRequests": AccessToggleQA.requests_made, "elapsedSeconds": round(time.perf_counter() - started, 3),
        "sourceSHA256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
        "productionRecordsCreated": 0, "productionGuestSettingChanged": False,
        "isolation": "TemporaryDirectory databases and backups; ephemeral loopback ports only",
        "limits": ["CAD generation is replaced by fixture bytes; HTTP authorization, storage and packaging are real",
                   "Router policy query failures and external session verification are covered separately by root"]}
    (ROOT / "data_evidence/access_toggle_independent_qa.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    sys.exit(0 if result.wasSuccessful() else 1)
