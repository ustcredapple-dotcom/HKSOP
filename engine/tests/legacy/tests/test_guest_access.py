"""Login-required optics access, rejected guest markers, and retained readonly tools."""
import http.client
import io
import json
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import test_shared_kits as shared_tests
project = shared_tests.project
from test_layout import request


class GuestAccessHTTPTests(unittest.TestCase):
    setUpClass = classmethod(shared_tests.SharedHTTPTests.setUpClass.__func__)
    tearDownClass = classmethod(shared_tests.SharedHTTPTests.tearDownClass.__func__)

    def call(self, method, path, body=None, role="guest", user_id="101", token="test-secret", headers=(), origin="https://zzlab.example", dev=False):
        server = self.dev if dev else self.server
        fields = [("Host", f"127.0.0.1:{server.server_port}")]
        if token is not None:
            fields.append(("X-ZZLAB-Internal-Token", token))
        fields.append(("X-ZZLAB-Role", role))
        if role == "guest":
            fields.append(("X-ZZLAB-Guest", "1"))
        else:
            fields.append(("X-ZZLAB-Authenticated", "1"))
            if user_id is not None:
                fields.append(("X-ZZLAB-User-ID", user_id))
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            fields += [("Content-Type", "application/json"), ("Content-Length", str(len(data))),
                       ("Origin", f"http://127.0.0.1:{server.server_port}" if dev else origin),
                       ("X-Forwarded-Host", "zzlab.example"), ("X-Forwarded-Proto", "https"), ("Sec-Fetch-Site", "same-origin")]
        fields += list(headers)
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=15)
        try:
            conn.putrequest(method, "/optics-kits" + path, skip_host=True, skip_accept_encoding=True)
            for key, value in fields:
                conn.putheader(key, value)
            conn.endheaders(data)
            response = conn.getresponse()
            raw = response.read()
            returned_headers = dict(response.getheaders())
            result = json.loads(raw) if returned_headers.get("Content-Type", "").startswith("application/json") else raw
            return response.status, result, returned_headers
        finally:
            conn.close()

    def publish(self):
        status, result, _ = self.call("POST", "/api/shared-kits", {"name": "Authenticated snapshot", "description": "test", "project": project()}, role="user")
        self.assertEqual(status, 201, result)
        return result["kit"]["id"]

    def test_session_roles_and_stable_publish_identity(self):
        for role in ("readonly", "user", "admin"):
            status, result, _ = self.call("GET", "/api/session", role=role)
            self.assertEqual(status, 200)
            self.assertEqual(result, {"role": role, "canPublish": role in ("user", "admin"), "canDownload": True, "canDownloadManufacturing": True})
        for user_id in (None, "0", "invalid"):
            result = self.call("GET", "/api/session", role="user", user_id=user_id)[1]
            self.assertFalse(result["canPublish"])
        # Explicit development mode retains its fixed local user; forwarded
        # identity claims cannot turn the local preview into an admin session.
        result = self.call("GET", "/api/session", role="admin", user_id="999", token="wrong", dev=True)[1]
        self.assertEqual(result, {"role": "user", "canPublish": True, "canDownload": True, "canDownloadManufacturing": True})

    def test_untrusted_guest_flags_and_ambiguous_identity_never_authenticate(self):
        for token in (None, "wrong"):
            for method, path, body in (("GET", "/api/session", None), ("GET", "/api/catalog", None),
                                       ("POST", "/api/preview", request())):
                self.assertEqual(self.call(method, path, body, token=token)[0], 401)
        for headers in ((('X-ZZLAB-Role', 'admin'),), (('X-ZZLAB-Authenticated', '1'),),
                        (('X-ZZLAB-Guest', '1'),), (('X-ZZLAB-Internal-Token', 'test-secret'),)):
            self.assertEqual(self.call("GET", "/api/session", headers=headers)[0], 401)
        # Adding a trusted-looking user ID to a guest does not grant ownership.
        status, result, _ = self.call("GET", "/api/session", headers=(("X-ZZLAB-User-ID", "101"),))
        self.assertEqual(status, 401)
        self.assertEqual(result["error"]["code"], "authentication_required")

    def test_guest_denied_all_editor_stateless_shared_and_management_endpoints(self):
        kid = self.publish()
        base = f"/api/shared-kits/{kid}"
        routes = [("GET", path, None) for path in ("/", "/index.html", "/app.js", "/topviews/test.svg", "/api/catalog", "/api/session", "/api/shared-kits", base + "/project", base + "/thumbnail", base + "/bundle")]
        routes += [("POST", path, request()) for path in ("/api/preview", "/api/export?format=bundle", "/api/mounting-holes")]
        routes += [("POST", path, {}) for path in ("/api/shared-kits", base + "/unpublish", base + "/restore")]
        for method, path, data in routes:
            status, result, _ = self.call(method, path, data)
            self.assertEqual(status, 401, path)
            self.assertEqual(result["error"]["code"], "authentication_required")
        # Any Guest header is rejected, including an authenticated member with a
        # stale marker and even marker values 0/empty (not only Guest:1).
        for role in ("readonly", "user", "admin"):
            for marker in ("1", "0", "", "true"):
                status, result, _ = self.call("GET", "/api/session", role=role, headers=(("X-ZZLAB-Guest", marker),))
                self.assertEqual(status, 401, (role, marker))
        self.assertEqual(self.call("GET", "/api/session", dev=True)[0], 401)

    def test_limited_static_and_api_allowlist(self):
        for name in ("index.html", "app.js", "app.css", "private.html"):
            (self.static / name).write_text("test static " + name)
        (self.static / "nested").mkdir(exist_ok=True)
        (self.static / "nested/secret.js").write_text("private script")
        for role in ("readonly",):
            for path in ("/", "/index.html", "/app.js?v=1", "/app.css", "/topviews/test.svg", "/api/catalog"):
                self.assertEqual(self.call("GET", path, role=role)[0], 200, path)
            for path in ("/private.html", "/nested/secret.js", "/assets/plate.step", "/api/unknown",
                         "/../catalog.json", "/topviews/../private.html", "/topviews/%2e%2e/private.html"):
                self.assertEqual(self.call("GET", path, role=role)[0], 404, path)
            self.assertEqual(self.call("POST", "/api/unknown", {}, role=role)[0], 403)
        self.assertEqual(self.call("GET", "/private.html", role="user")[0], 200)

    def test_readonly_can_preview_choose_holes_and_export(self):
        empty_board = {"layout": {"board": request()["layout"]["board"], "instances": []}, "rowParity": "odd", "columnParity": "even"}
        for role in ("readonly",):
            status, result, _ = self.call("POST", "/api/preview", request(), role=role)
            self.assertEqual(status, 200, result)
            self.assertTrue(result["layoutValidation"]["valid"])
            self.assertEqual(result["totals"]["kits"], 3)
            status, result, _ = self.call("POST", "/api/mounting-holes", empty_board, role=role)
            self.assertEqual(status, 200, result)
            self.assertEqual(len(result["mountingHoles"]), 4)
            for kind in ("lubang", "manufacturing", "layout-json", "layout-svg"):
                status, result, headers = self.call("POST", "/api/export?format=" + kind, request(), role=role)
                self.assertEqual(status, 200, result if status != 200 else "")
                self.assertIn("attachment", headers["Content-Disposition"])

    def test_origin_and_collision_rules_are_unchanged_for_limited_roles(self):
        collided = request()
        collided["layout"]["instances"][1].update(xMm=50, yMm=50)
        for role in ("readonly",):
            for path in ("/api/preview", "/api/export?format=lubang", "/api/mounting-holes"):
                status, result, _ = self.call("POST", path, request(), role=role, origin="https://outside.example")
                self.assertEqual(status, 403)
                self.assertEqual(result["error"]["code"], "cross_origin_denied")
            status, result, _ = self.call("POST", "/api/preview", collided, role=role)
            self.assertEqual(status, 200)
            self.assertFalse(result["layoutValidation"]["valid"])
            self.assertEqual(self.call("POST", "/api/export?format=bundle", collided, role=role)[0], 409)
            self.assertEqual(self.call("POST", "/api/export?format=layout-json", collided, role=role)[0], 200)

    def test_active_shared_downloads_but_never_hidden_or_publication_management(self):
        kid = self.publish()
        route = f"/api/shared-kits/{kid}"
        for role in ("readonly",):
            status, result, _ = self.call("GET", "/api/shared-kits", role=role)
            self.assertEqual(status, 200)
            summary = next(k for k in result["kits"] if k["id"] == kid)
            self.assertFalse(summary["canUnpublish"])
            self.assertFalse(summary["canRestore"])
            self.assertEqual(result["withdrawn"], [])
            for endpoint in ("project", "thumbnail"):
                self.assertEqual(self.call("GET", route + "/" + endpoint, role=role)[0], 200)
            for path, data in (("/api/shared-kits", {"name": "Forbidden", "description": "", "project": project()}),
                               (route + "/unpublish", {}), (route + "/restore", {})):
                self.assertEqual(self.call("POST", path, data, role=role)[0], 403)
        self.assertEqual(self.call("POST", route + "/unpublish", {}, role="user")[0], 200)
        for role in ("readonly",):
            for endpoint in ("project", "thumbnail", "bundle"):
                # readonly carries the original owner's real ID but loses all
                # private-share visibility and modification capabilities.
                self.assertEqual(self.call("GET", route + "/" + endpoint, role=role, user_id="101")[0], 404)
            status, result, _ = self.call("GET", "/api/shared-kits", role=role)
            self.assertNotIn(kid, [k["id"] for k in result["kits"]])
            self.assertEqual(result["withdrawn"], [])
        self.assertEqual(self.call("POST", route + "/restore", {}, role="admin", user_id="999")[0], 200)

    def test_readonly_downloads_complete_shared_and_canvas_bundles(self):
        kid = self.publish()
        def generate(board, cache):
            from breadboard import board_specs
            spec = board_specs(board)
            root = Path(cache)
            root.mkdir(parents=True, exist_ok=True)
            step, drawing = root / "test-board.step", root / "test-board.pdf"
            step.write_bytes(b"ISO-10303-21; TEST")
            drawing.write_bytes(b"%PDF TEST")
            return {"step": step, "drawing": drawing, "spec": spec, "componentId": spec["componentId"]}
        with patch.dict("os.environ", {"ZZLAB_BOARD_CACHE": str(self.root / "board-cache")}), patch("breadboard.ensure_board_artifacts", side_effect=generate):
            for role in ("readonly",):
                for method, route, body in (("GET", f"/api/shared-kits/{kid}/bundle", None),
                                            ("POST", "/api/export?format=bundle", request())):
                    status, content, headers = self.call(method, route, body, role=role)
                    self.assertEqual(status, 200, content if status != 200 else "")
                    self.assertEqual(headers["Content-Type"], "application/zip")
                    with zipfile.ZipFile(io.BytesIO(content)) as archive:
                        self.assertIn("生产清单.xlsx", archive.namelist())
                        self.assertIn("麓邦采购.xlsx", archive.namelist())
                        self.assertTrue(any(n.endswith(".step") for n in archive.namelist()))
                        self.assertTrue(any(n.endswith(".pdf") for n in archive.namelist()))
                        if method == "GET":
                            self.assertEqual(json.loads(archive.read("共享套件工程.zzoptics.json")), project())


if __name__ == "__main__":
    unittest.main()
