"""Admin guest-policy persistence, optimistic updates and actual HTTP boundaries."""
import http.client
import io
import json
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import Config, create_server
import test_shared_kits as shared_tests
from test_layout import request


class AccessSettingsHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        static = self.root / "static"
        (static / "topviews").mkdir(parents=True)
        (static / "index.html").write_text("<title>test</title>")
        (static / "app.js").write_text("/*test*/")
        (static / "topviews/test.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        catalog = self.root / "catalog.json"
        catalog.write_text(json.dumps(shared_tests.with_module()))
        for cid in ("plate", "bracket"):
            (self.root / f"{cid}.step").write_bytes(b"ISO-10303-21; TEST PART")
            (self.root / f"{cid}.pdf").write_bytes(b"%PDF TEST PART")
        self.config = Config(catalog, self.root, static, "access-policy-secret", self.root / "shared.sqlite3", self.root / "backup.sqlite3")
        self.start_server()

    def start_server(self):
        self.server = create_server(self.config, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop_server()
        self.temp.cleanup()

    def http(self, method, route, body=None, role="admin", user_id="101", token="access-policy-secret", probe=False, headers=(), raw=None):
        fields = [("Host", f"127.0.0.1:{self.server.server_port}")]
        if token is not None:
            fields.append(("X-ZZLAB-Internal-Token", token))
        if probe:
            fields.append(("X-ZZLAB-Policy-Probe", "1"))
        elif role is not None:
            fields.append(("X-ZZLAB-Role", role))
            if role == "guest":
                fields.append(("X-ZZLAB-Guest", "1"))
            else:
                fields.append(("X-ZZLAB-Authenticated", "1"))
                if user_id is not None:
                    fields.append(("X-ZZLAB-User-ID", user_id))
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        if data is not None:
            fields += [("Content-Type", "application/json"), ("Content-Length", str(len(data))),
                       ("Origin", "https://zzlab.example"), ("X-Forwarded-Host", "zzlab.example"), ("X-Forwarded-Proto", "https")]
        fields += list(headers)
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            conn.putrequest(method, route, skip_host=True, skip_accept_encoding=True)
            for key, value in fields:
                conn.putheader(key, value)
            conn.endheaders(data)
            response = conn.getresponse()
            content = response.read()
            result = json.loads(content) if response.getheader("Content-Type", "").startswith("application/json") else content
            return response.status, result
        finally:
            conn.close()

    def setting(self):
        status, data = self.http("GET", "/api/admin/guest-access")
        self.assertEqual(status, 200, data)
        return data

    def toggle(self, value, revision=None, **kwargs):
        if revision is None:
            revision = self.setting()["revision"]
        return self.http("POST", "/api/admin/guest-access", {"guestAccessEnabled": value, "revision": revision}, **kwargs)

    def publish(self):
        status, data = self.http("POST", "/api/shared-kits", {"name": "setting QA", "description": "", "project": shared_tests.project()}, role="user")
        self.assertEqual(status, 201, data)
        return data["kit"]["id"]

    def download_policy(self, enabled):
        return self.http("POST", "/api/admin/guest-access", {
            "guestAccessEnabled": True, "guestManufacturingDownloadsEnabled": enabled,
            "revision": self.setting()["revision"]})

    @staticmethod
    def generate_board(board, cache):
        from breadboard import board_specs
        spec = board_specs(board)
        target = Path(cache)
        target.mkdir(parents=True, exist_ok=True)
        step, drawing = target / "board.step", target / "board.pdf"
        step.write_bytes(b"ISO-10303-21; TEST BOARD")
        drawing.write_bytes(b"%PDF TEST BOARD")
        return {"step": step, "drawing": drawing, "spec": spec, "componentId": spec["componentId"]}

    def test_default_off_and_only_authenticated_admin_with_stable_id_can_manage(self):
        self.assertEqual(self.setting(), {"guestAccessEnabled": False, "guestManufacturingDownloadsEnabled": True, "revision": 0, "updatedAt": None})
        self.assertEqual(self.http("GET", "/api/session", role="guest")[0], 401)
        for role in ("user", "readonly", "guest", None):
            for method, body in (("GET", None), ("POST", {"guestAccessEnabled": True, "revision": 0})):
                self.assertIn(self.http(method, "/api/admin/guest-access", body, role=role)[0], (401, 403))
        for user_id in (None, "", "0", "invalid"):
            self.assertEqual(self.http("GET", "/api/admin/guest-access", user_id=user_id)[0], 403)
        for token in (None, "wrong"):
            self.assertEqual(self.http("GET", "/api/admin/guest-access", token=token)[0], 401)

    def test_toggle_persists_across_restart_and_nas_backup_then_revokes_immediately(self):
        status, state = self.toggle(True)
        self.assertEqual(status, 200)
        self.assertTrue(state["guestAccessEnabled"])
        self.assertEqual(state["revision"], 1)
        self.assertIsInstance(state["updatedAt"], str)
        self.assertEqual(state["backup"]["status"], "ok")
        self.assertEqual(self.http("GET", "/api/session", role="guest"), (200, {"role": "guest", "canPublish": False, "canDownload": True, "canDownloadManufacturing": True}))
        self.stop_server()
        self.start_server()
        self.assertTrue(self.setting()["guestAccessEnabled"])
        self.assertEqual(self.http("GET", "/api/session", role="guest")[0], 200)
        with sqlite3.connect(self.config.shared_backup) as database:
            self.assertEqual(database.execute("SELECT guest_enabled,revision FROM optics_access_settings").fetchone(), (1, 1))
            self.assertEqual(database.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        status, state = self.toggle(False)
        self.assertEqual((status, state["revision"]), (200, 2))
        self.assertEqual(self.http("GET", "/api/session", role="guest")[0], 401)
        self.assertEqual(self.http("POST", "/api/preview", request(), role="guest")[0], 401)
        self.assertEqual(self.http("GET", "/internal/guest-access", probe=True), (200, {"guestAccessEnabled": False}))

    def test_revision_conflict_and_concurrent_admins_never_silently_overwrite(self):
        self.assertEqual(self.toggle(True, 0)[0], 200)
        status, error = self.toggle(False, 0)
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "access_settings_conflict")
        self.assertEqual(error["error"]["details"], self.setting())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda value: self.toggle(value, 1), [False, True]))
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        self.assertEqual(self.setting()["revision"], 2)

    def test_invalid_json_fields_types_and_origin_leave_setting_unchanged(self):
        before = self.setting()
        for body in ({}, {"guestAccessEnabled": 1, "revision": 0}, {"guestAccessEnabled": "true", "revision": 0},
                     {"guestAccessEnabled": True, "revision": True}, {"guestAccessEnabled": True, "revision": -1},
                     {"guestAccessEnabled": True, "revision": 0, "author": "admin"}):
            self.assertEqual(self.http("POST", "/api/admin/guest-access", body)[0], 400)
        self.assertEqual(self.http("POST", "/api/admin/guest-access", raw=b'{"guestAccessEnabled":true,"revision":0,"revision":1}')[0], 400)
        for headers in ((("Origin", "https://outside.example"),), (("Sec-Fetch-Site", "cross-site"),)):
            self.assertEqual(self.toggle(True, 0, headers=headers)[0], 403)
        self.assertEqual(self.http("GET", "/api/admin/guest-access", headers=(("Origin", "https://outside.example"),))[0], 403)
        self.assertEqual(self.setting(), before)

    def test_private_probe_requires_exact_internal_identity_and_fails_closed(self):
        self.assertEqual(self.http("GET", "/internal/guest-access", probe=True), (200, {"guestAccessEnabled": False}))
        self.toggle(True)
        self.assertEqual(self.http("GET", "/internal/guest-access", probe=True), (200, {"guestAccessEnabled": True}))
        for role in ("guest", "readonly", "user", "admin", None):
            self.assertEqual(self.http("GET", "/internal/guest-access", role=role)[0], 401)
        for headers in ((("X-ZZLAB-Role", "admin"),), (("X-ZZLAB-Authenticated", "1"),),
                        (("X-ZZLAB-User-ID", "101"),), (("X-ZZLAB-Guest", "1"),),
                        (("X-ZZLAB-Policy-Probe", "1"),), (("Origin", "https://zzlab.example"),),
                        (("X-Forwarded-Host", "zzlab.example"),)):
            self.assertEqual(self.http("GET", "/internal/guest-access", probe=True, headers=headers)[0], 401)
        with patch.object(self.server.shared_store, "connect", side_effect=sqlite3.OperationalError("unavailable")):
            self.assertEqual(self.http("GET", "/internal/guest-access", probe=True), (200, {"guestAccessEnabled": False}))
            self.assertEqual(self.http("GET", "/api/session", role="guest")[0], 401)
            self.assertEqual(self.http("GET", "/api/admin/guest-access")[0], 503)
        with sqlite3.connect(self.config.shared_db) as db:
            db.execute("UPDATE optics_access_settings SET updated_at='corrupt'")
        self.assertEqual(self.http("GET", "/internal/guest-access", probe=True), (200, {"guestAccessEnabled": False}))
        self.assertEqual(self.http("GET", "/api/admin/guest-access")[0], 503)

    def test_backup_warning_is_successful_local_commit_not_repeated_update(self):
        self.server.shared_store.backup_path = self.root / "unmounted" / "backup.sqlite3"
        status, result = self.toggle(True)
        self.assertEqual(status, 200)
        self.assertEqual(result["backup"]["status"], "warning")
        self.assertEqual(self.setting()["revision"], 1)
        self.assertTrue(self.setting()["guestAccessEnabled"])
        self.assertFalse((self.root / "unmounted").exists())
        self.assertEqual(self.toggle(True, 0)[0], 409)

    def test_enabled_guests_use_tools_but_cannot_claim_identity_or_hidden_records(self):
        kid = self.publish()
        self.toggle(True)
        for path in ("/", "/app.js", "/topviews/test.svg", "/api/catalog", "/api/shared-kits", f"/api/shared-kits/{kid}/project", f"/api/shared-kits/{kid}/thumbnail"):
            self.assertEqual(self.http("GET", path, role="guest")[0], 200, path)
        self.assertEqual(self.http("POST", "/api/preview", request(), role="guest")[0], 200)
        self.assertEqual(self.http("POST", "/api/export?format=lubang", request(), role="guest")[0], 200)
        self.assertEqual(self.http("POST", "/api/mounting-holes", {**request(), "rowParity": "odd", "columnParity": "odd"}, role="guest")[0], 200)
        for method, path, data in (("GET", "/api/admin/guest-access", None), ("POST", "/api/admin/guest-access", {"guestAccessEnabled": False, "revision": 1}),
                                    ("POST", "/api/shared-kits", {}), ("POST", f"/api/shared-kits/{kid}/unpublish", {})):
            self.assertEqual(self.http(method, path, data, role="guest")[0], 403)
        for field, val in (("X-ZZLAB-Authenticated", "1"), ("X-ZZLAB-User-ID", "101"), ("X-ZZLAB-User", "admin"), ("X-ZZLAB-Display-Name", "admin")):
            self.assertEqual(self.http("GET", "/api/session", role="guest", headers=((field, val),))[0], 401)
        self.assertEqual(self.http("POST", "/api/preview", request(), role="guest", headers=(("Origin", "https://outside.example"),))[0], 403)
        self.http("POST", f"/api/shared-kits/{kid}/unpublish", {}, role="user")
        for role in ("guest", "readonly"):
            status, listing = self.http("GET", "/api/shared-kits", role=role)
            self.assertEqual(status, 200)
            self.assertEqual(listing["withdrawn"], [])
            for action in ("project", "thumbnail", "bundle"):
                self.assertEqual(self.http("GET", f"/api/shared-kits/{kid}/{action}", role=role)[0], 404)
        self.toggle(False)
        self.assertEqual(self.http("POST", "/api/preview", request(), role="readonly")[0], 200)
        self.assertEqual(self.http("GET", "/api/session", role="readonly"), (200, {"role": "readonly", "canPublish": False, "canDownload": True, "canDownloadManufacturing": True}))

    def test_manufacturing_download_switch_preserves_other_guest_tools(self):
        kid = self.publish()
        self.assertEqual(self.download_policy(False)[0], 200)
        status, session = self.http("GET", "/api/session", role="guest")
        self.assertEqual(status, 200)
        self.assertEqual(session, {"role": "guest", "canPublish": False,
                                  "canDownload": True, "canDownloadManufacturing": False})
        for path in ("/", "/api/catalog", "/api/shared-kits", "/topviews/test.svg",
                     f"/api/shared-kits/{kid}/project", f"/api/shared-kits/{kid}/thumbnail"):
            self.assertEqual(self.http("GET", path, role="guest")[0], 200, path)
        for path, body in (("/api/preview", request()),
                           ("/api/mounting-holes", {**request(), "rowParity": "odd", "columnParity": "odd"})):
            self.assertEqual(self.http("POST", path, body, role="guest")[0], 200, path)
        for kind in ("lubang", "manufacturing", "layout-json", "layout-svg"):
            self.assertEqual(self.http("POST", "/api/export?format=" + kind, request(), role="guest")[0], 200, kind)
        with patch("app.export_result") as export, patch("app.shared_bundle") as bundle:
            for method, path, body in (("POST", "/api/export?format=bundle", request()),
                                      ("GET", f"/api/shared-kits/{kid}/bundle", None)):
                status, error = self.http(method, path, body, role="guest")
                self.assertEqual(status, 403)
                self.assertEqual(error["error"]["code"], "manufacturing_download_forbidden")
            export.assert_not_called()
            bundle.assert_not_called()
        # File locations disclosed as relative catalog metadata are not endpoints;
        # cached/encoded/traversal paths must not become a download bypass.
        for path in ("/assets/plate.step", "/assets/plate.pdf", "/plate.step", "/plate.pdf",
                     "/static/../assets/plate.pdf", "/topviews/%2e%2e/plate.pdf",
                     "/topviews/..%2fplate.pdf", "/board-cache/board.step", "/step/plate.stp",
                     "/drawings/plate.pdf", "/assets%2fplate.pdf", "/assets%252fplate.pdf"):
            self.assertEqual(self.http("GET", path, role="guest")[0], 404, path)
        self.assertEqual(self.http("POST", "/api/cart/export?format=bundle", {}, role="guest")[0], 403)

    def test_old_bundle_links_and_all_member_roles_follow_current_download_policy(self):
        kid = self.publish()
        self.download_policy(True)
        routes = (("POST", "/api/export?format=bundle", request()),
                  ("GET", f"/api/shared-kits/{kid}/bundle", None))
        with patch.dict("os.environ", {"ZZLAB_BOARD_CACHE": str(self.root / "board-cache")}), \
                patch("breadboard.ensure_board_artifacts", side_effect=self.generate_board):
            for enabled in (True, False, True):
                self.assertEqual(self.download_policy(enabled)[0], 200)
                for role in ("guest", "readonly", "user", "admin"):
                    allowed = enabled or role != "guest"
                    self.assertEqual(self.http("GET", "/api/session", role=role)[1]["canDownloadManufacturing"], allowed)
                    for method, route, payload in routes:
                        status, content = self.http(method, route, payload, role=role)
                        self.assertEqual(status, 200 if allowed else 403, (role, enabled, route))
                        if allowed:
                            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                                self.assertTrue(any(name.endswith(".step") for name in archive.namelist()))
                                self.assertTrue(any(name.endswith(".pdf") for name in archive.namelist()))
        self.toggle(False)
        self.assertEqual(self.http("GET", "/api/session", role="guest")[0], 401)

    def test_revocation_during_generation_does_not_send_manufacturing_files(self):
        kid = self.publish()
        for method, route, payload, target in (
                ("POST", "/api/export?format=bundle", request(), "app.export_result"),
                ("GET", f"/api/shared-kits/{kid}/bundle", None, "app.shared_bundle")):
            self.download_policy(True)
            def generate_then_revoke(*args, **kwargs):
                self.assertEqual(self.download_policy(False)[0], 200)
                return b"SECRET CAD CONTENT", "application/zip", "package.zip"
            with patch(target, side_effect=generate_then_revoke):
                status, content = self.http(method, route, payload, role="guest")
                self.assertEqual(status, 403)
                self.assertEqual(content["error"]["code"], "manufacturing_download_forbidden")

    def test_independent_switch_persists_and_old_admin_pages_cannot_reset_it(self):
        status, state = self.download_policy(False)
        self.assertEqual(status, 200)
        self.assertEqual(state["backup"]["status"], "ok")
        self.assertTrue(state["guestAccessEnabled"])
        self.assertFalse(state["guestManufacturingDownloadsEnabled"])
        for value in (False, True):
            self.assertEqual(self.toggle(value)[0], 200)
            self.assertFalse(self.setting()["guestManufacturingDownloadsEnabled"])
        self.stop_server()
        self.start_server()
        self.assertFalse(self.setting()["guestManufacturingDownloadsEnabled"])
        # Simulate restoring the NAS snapshot locally, without SQLite network I/O.
        restored = self.root / "restored.sqlite3"
        restored.write_bytes(self.config.shared_backup.read_bytes())
        with sqlite3.connect(restored) as db:
            self.assertEqual(db.execute("""SELECT guest_enabled,guest_manufacturing_downloads_enabled,revision
                FROM optics_access_settings""").fetchone(), (1, 0, 3))
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_legacy_schema_migration_preserves_original_policy_and_handles_parallel_first_reads(self):
        stamp = "2026-09-29T12:34:56.123Z"
        with sqlite3.connect(self.config.shared_db) as db:
            db.execute("""CREATE TABLE optics_access_settings (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), guest_enabled INTEGER NOT NULL,
                revision INTEGER NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL)""")
            db.execute("INSERT INTO optics_access_settings VALUES(1,1,7,?,'101')", (stamp,))
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.http("GET", "/api/admin/guest-access"), range(16)))
        expected = {"guestAccessEnabled": True, "guestManufacturingDownloadsEnabled": True,
                    "revision": 7, "updatedAt": stamp}
        for status, result in results:
            self.assertEqual(status, 200, result)
            self.assertEqual(result, expected)
        self.assertEqual(self.toggle(True, 7)[0], 200)
        self.assertEqual(self.setting()["revision"], 8)

    def test_download_policy_field_type_conflicts_and_corruption_fail_closed(self):
        before = self.setting()
        for value in (None, 0, 1, "true", [], {}):
            status, _ = self.http("POST", "/api/admin/guest-access", {
                "guestAccessEnabled": True, "guestManufacturingDownloadsEnabled": value, "revision": 0})
            self.assertEqual(status, 400, value)
        self.assertEqual(self.setting(), before)
        self.download_policy(False)
        status, error = self.http("POST", "/api/admin/guest-access", {
            "guestAccessEnabled": True, "guestManufacturingDownloadsEnabled": True, "revision": 0})
        self.assertEqual(status, 409)
        self.assertFalse(error["error"]["details"]["guestManufacturingDownloadsEnabled"])
        with sqlite3.connect(self.config.shared_db) as db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute("UPDATE optics_access_settings SET guest_manufacturing_downloads_enabled=7")
        self.assertEqual(self.http("GET", "/api/admin/guest-access")[0], 503)
        self.assertEqual(self.http("GET", "/api/session", role="guest")[0], 401)
        self.assertTrue(self.http("GET", "/api/session", role="readonly")[1]["canDownloadManufacturing"])


if __name__ == "__main__":
    unittest.main()
