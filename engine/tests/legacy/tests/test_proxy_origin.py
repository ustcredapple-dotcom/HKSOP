"""Browser-origin regression cases with the router's actual rewritten Host.

Previous HTTP smoke tests omitted Origin on successful requests, so they exercised
API-probe behavior and never simulated a public browser passing through the
loopback reverse proxy. These tests use actual HTTP headers, including duplicates.
"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Config, create_server
from test_backend import fixture

PUBLIC_HOST = "zzlab.ngrok.app"
PUBLIC_ORIGIN = "https://zzlab.ngrok.app"
TEST_TOKEN = "proxy-origin-regression-test-only"


class ProxyOriginHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        catalog = cls.root / "catalog.json"
        catalog.write_text(json.dumps(fixture(), ensure_ascii=False))
        cls.servers = {}
        cls.threads = []
        for name, token in (("production", TEST_TOKEN), ("development", None)):
            server = create_server(Config(catalog, cls.root, cls.root / "static", token), 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.servers[name] = server
            cls.threads.append(thread)

    @classmethod
    def tearDownClass(cls):
        for server in cls.servers.values():
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join()
        cls.temporary.cleanup()

    def post(self, headers=(), server_name="production", auth=True, path="/optics-kits/api/preview", payload=None):
        server = self.servers[server_name]
        body = json.dumps(payload if payload is not None else {"items": [{"kitId": "alpha", "quantity": 1}]}).encode()
        request_headers = [("Host", f"127.0.0.1:{server.server_port}"),
                           ("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
        if auth:
            request_headers.extend([("X-ZZLAB-Internal-Token", TEST_TOKEN),
                                    ("X-ZZLAB-Authenticated", "1"), ("X-ZZLAB-Role", "user")])
        # Callers can deliberately duplicate Origin / X-Forwarded-* fields.
        request_headers.extend(headers)
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
            for name, value in request_headers:
                connection.putheader(name, value)
            connection.endheaders(body)
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def proxy_headers(self, origin=PUBLIC_ORIGIN, host=PUBLIC_HOST, proto="https", fetch_site="same-origin"):
        return [("Origin", origin), ("X-Forwarded-Host", host), ("X-Forwarded-Proto", proto),
                ("Sec-Fetch-Site", fetch_site)]

    def assert_denied(self, headers, server_name="production", auth=True, status=403, code="cross_origin_denied"):
        actual, body, _ = self.post(headers, server_name, auth)
        self.assertEqual(actual, status, body.decode(errors="replace"))
        self.assertEqual(json.loads(body)["error"]["code"], code)

    def test_public_browser_preview_accepts_trusted_proxy_origin(self):
        status, body, _ = self.post(self.proxy_headers())
        self.assertEqual(status, 200, body.decode(errors="replace"))
        self.assertEqual(json.loads(body)["totals"]["kits"], 1)

    def test_public_browser_purchase_download_accepts_trusted_proxy_origin(self):
        status, body, headers = self.post(self.proxy_headers(), path="/optics-kits/api/export?format=lubang")
        self.assertEqual(status, 200, body.decode(errors="replace")[:500] if status != 200 else "")
        self.assertEqual(body[:2], b"PK")
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_foreign_same_site_and_wrong_scheme_or_port_are_denied(self):
        for origin, fetch_site in (("https://outside.example", "cross-site"),
                                   ("https://other.zzlab.ngrok.app", "same-site"),
                                   ("http://zzlab.ngrok.app", "same-site"),
                                   ("https://zzlab.ngrok.app:444", "same-origin"),
                                   ("https://zzlab.ngrok.app.", "same-site")):
            with self.subTest(origin=origin):
                self.assert_denied(self.proxy_headers(origin=origin, fetch_site=fetch_site))

    def test_effective_default_port_and_case_are_normalized(self):
        for origin, host in (("https://zzlab.ngrok.app:443", PUBLIC_HOST),
                             (PUBLIC_ORIGIN, "zzlab.ngrok.app:443"),
                             ("https://ZZLAB.NGROK.APP", PUBLIC_HOST),
                             ("https://zzlab.ngrok.app:8443", "zzlab.ngrok.app:8443")):
            with self.subTest(origin=origin, host=host):
                status, body, _ = self.post(self.proxy_headers(origin=origin, host=host))
                self.assertEqual(status, 200, body.decode(errors="replace"))

    def test_cross_site_fetch_metadata_denies_even_matching_or_missing_origin(self):
        self.assert_denied(self.proxy_headers(fetch_site="cross-site"))
        self.assert_denied([("Sec-Fetch-Site", "cross-site")])

    def test_null_list_path_userinfo_and_malformed_origins_are_denied(self):
        for origin in ("null", "", "https://zzlab.ngrok.app/", "https://zzlab.ngrok.app/path",
                       "https://zzlab.ngrok.app?x=1", "https://zzlab.ngrok.app#fragment",
                       "https://person@zzlab.ngrok.app", "https://zzlab.ngrok.app,https://outside.example",
                       "https://zzlab.ngrok.app https://outside.example", "ftp://zzlab.ngrok.app",
                       "https://zzlab.ngrok.app:invalid", "https://zzlab.ngrok.app:65536",
                       "https://zzlab.ngrok.app:0", "https://[::1", "https://zzlab.ngrok.app\\outside"):
            with self.subTest(origin=origin):
                self.assert_denied(self.proxy_headers(origin=origin))

    def test_duplicate_origin_and_forwarded_headers_are_denied(self):
        for name, value in (("Origin", PUBLIC_ORIGIN), ("Origin", "https://outside.example"),
                            ("X-Forwarded-Host", PUBLIC_HOST), ("X-Forwarded-Proto", "https")):
            with self.subTest(name=name, value=value):
                self.assert_denied(self.proxy_headers()+[(name, value)])

    def test_partial_or_ambiguous_forwarding_never_falls_back_to_internal_host(self):
        internal_origin = f"http://127.0.0.1:{self.servers['production'].server_port}"
        candidates = [
            [("X-Forwarded-Host", PUBLIC_HOST)],
            [("X-Forwarded-Proto", "https")],
            [("X-Forwarded-Host", ""), ("X-Forwarded-Proto", "https")],
            [("X-Forwarded-Host", PUBLIC_HOST), ("X-Forwarded-Proto", "")],
            [("X-Forwarded-Host", PUBLIC_HOST+", outside.example"), ("X-Forwarded-Proto", "https")],
            [("X-Forwarded-Host", PUBLIC_HOST), ("X-Forwarded-Proto", "https,http")],
            [("X-Forwarded-Host", "https://"+PUBLIC_HOST), ("X-Forwarded-Proto", "https")],
            [("X-Forwarded-Host", "person@"+PUBLIC_HOST), ("X-Forwarded-Proto", "https")],
            [("X-Forwarded-Host", PUBLIC_HOST+"/path"), ("X-Forwarded-Proto", "https")],
            [("X-Forwarded-Host", PUBLIC_HOST+":65536"), ("X-Forwarded-Proto", "https")],
            [("X-Forwarded-Host", PUBLIC_HOST), ("X-Forwarded-Proto", "ws")],
        ]
        for forwarded in candidates:
            with self.subTest(headers=forwarded):
                self.assert_denied([("Origin", internal_origin), *forwarded])

    def test_forwarding_does_not_bypass_token_or_role_authentication(self):
        self.assert_denied(self.proxy_headers(), auth=False, status=401, code="authentication_required")
        for identity in ([('X-ZZLAB-Internal-Token', 'wrong'), ('X-ZZLAB-Authenticated', '1'), ('X-ZZLAB-Role', 'user')],
                         [('X-ZZLAB-Internal-Token', TEST_TOKEN), ('X-ZZLAB-Authenticated', '0'), ('X-ZZLAB-Role', 'user')]):
            self.assert_denied(self.proxy_headers()+identity, auth=False, status=401, code="authentication_required")
        readonly = [('X-ZZLAB-Internal-Token', TEST_TOKEN), ('X-ZZLAB-Authenticated', '1'), ('X-ZZLAB-Role', 'readonly')]
        status, body, _ = self.post(self.proxy_headers()+readonly, auth=False)
        self.assertEqual(status, 200, body.decode(errors="replace"))

    def test_development_ignores_forwarding_even_with_spoofed_auth_headers(self):
        # Token=None is a plain HTTP local preview, not a trusted reverse proxy.
        self.assert_denied(self.proxy_headers(), server_name="development")
        internal_origin = f"http://127.0.0.1:{self.servers['development'].server_port}"
        status, body, _ = self.post(self.proxy_headers(origin=internal_origin), server_name="development")
        self.assertEqual(status, 200, body.decode(errors="replace"))
        self.assert_denied([("Origin", internal_origin.replace("http:", "https:"))], server_name="development")

    def test_public_browser_mounting_hole_selection_and_auth_boundaries(self):
        data={"layout":{"board":{"widthMm":350,"heightMm":225,"pitchMm":12.5,"edgeOffsetMm":12.5},"instances":[]},"rowParity":"odd","columnParity":"even"}
        path="/optics-kits/api/mounting-holes"
        status,body,_=self.post(self.proxy_headers(),path=path,payload=data)
        self.assertEqual(status,200,body.decode(errors="replace"))
        selected=json.loads(body)
        self.assertEqual(len(selected["mountingHoles"]),4)
        self.assertTrue(selected["layoutValidation"]["valid"])
        self.assertTrue(all((h["columnIndex"]+1)%2==0 and (h["rowIndex"]+1)%2==1 for h in selected["mountingHoles"]))
        status,body,_=self.post(self.proxy_headers(origin="https://outside.example",fetch_site="cross-site"),path=path,payload=data)
        self.assertEqual(status,403)
        self.assertEqual(json.loads(body)["error"]["code"],"cross_origin_denied")
        status,body,_=self.post(self.proxy_headers(),auth=False,path=path,payload=data)
        self.assertEqual(status,401)
        self.assertEqual(json.loads(body)["error"]["code"],"authentication_required")
        readonly=[("X-ZZLAB-Internal-Token",TEST_TOKEN),("X-ZZLAB-Authenticated","1"),("X-ZZLAB-Role","readonly")]
        status,body,_=self.post(self.proxy_headers()+readonly,auth=False,path=path,payload=data)
        self.assertEqual(status,200)
        self.assertEqual(len(json.loads(body)["mountingHoles"]),4)

    def test_no_origin_api_probes_and_direct_same_origin_requests_still_work(self):
        for name in self.servers:
            status, body, _ = self.post(server_name=name)
            self.assertEqual(status, 200, body.decode(errors="replace"))
            origin = f"http://127.0.0.1:{self.servers[name].server_port}"
            status, body, _ = self.post([("Origin", origin)], server_name=name)
            self.assertEqual(status, 200, body.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
