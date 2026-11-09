"""Real proxy + backend HTTP tests using temporary stores and test identities."""
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import Config, create_server
import deploy_support as deploy


class GuestRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        folder = Path(cls.temporary.name)
        cls.backend = create_server(Config(shared_db=folder / 'shared.sqlite3', auth_token='guest-router-test'), 0)
        candidate = folder / 'router.py'
        original = (deploy.LIVE / 'router.py').read_text()
        candidate.write_text(deploy.patched_router(original).replace(
            '"127.0.0.1", 18923, timeout=1', f'"127.0.0.1", {cls.backend.server_port}, timeout=1'))
        cls.router_module = deploy.import_review_module(candidate, '_guest_router_test')
        cls.router_module.ROUTES = tuple((p, h, cls.backend.server_port if p == deploy.PREFIX else port, strip)
                                         for p, h, port, strip in cls.router_module.ROUTES)
        class TestRouter(cls.router_module.RouterHandler):
            def verify_identity(self):
                role = self.headers.get('X-Test-Role')
                return None if not role else {'id': 11, 'username': 'qa', 'display_name': 'QA', 'role': role}
            def log_message(self, *args):
                pass
        cls.router = cls.router_module.ThreadingHTTPServer(('127.0.0.1', 0), TestRouter)
        cls.environment = patch.dict(os.environ, {'ZZLAB_AUTH_INTERNAL_TOKEN': 'guest-router-test', 'ROUTER_EXTERNAL_SCHEME': 'https'})
        cls.environment.start()
        cls.presence = patch.object(cls.router_module, 'record_presence', lambda *args: None)
        cls.presence.start()
        cls.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (cls.backend, cls.router)]
        for thread in cls.threads:
            thread.start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.router, cls.backend):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join()
        cls.presence.stop()
        cls.environment.stop()
        cls.temporary.cleanup()

    def request(self, path, role=None, body=None, extra=None):
        headers = {'Host': 'zzlab.ngrok.app', 'Origin': 'https://zzlab.ngrok.app', 'Sec-Fetch-Site': 'same-origin'}
        if role:
            headers['X-Test-Role'] = role
        if body is not None:
            headers['Content-Type'] = 'application/json'
        headers.update(extra or {})
        connection = http.client.HTTPConnection('127.0.0.1', self.router.server_port, timeout=15)
        try:
            connection.request('POST' if body is not None else 'GET', path,
                               body=None if body is None else json.dumps(body).encode(), headers=headers)
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_anonymous_cannot_load_interface_or_downloads(self):
        for file in (ROOT / 'static').rglob('*'):
            if file.is_file():
                status, body, _ = self.request('/optics-kits/' + file.relative_to(ROOT / 'static').as_posix())
                self.assertEqual(status, 302, file.name)
                self.assertEqual(body, b'', file.name)
        for path in ('/', '/api/session', '/api/catalog', '/api/shared-kits',
                     '/api/shared-kits/' + 'a' * 32 + '/bundle', '/api/shared-kits/' + 'a' * 32 + '/project'):
            status, _, headers = self.request('/optics-kits' + path)
            self.assertEqual(status, 302)
            self.assertTrue(headers['Location'].startswith('/auth/login?next='))
        for path in ('/api/preview', '/api/export?format=bundle', '/api/mounting-holes'):
            self.assertEqual(self.request('/optics-kits' + path, body={})[0], 401)

    def test_readonly_can_read_edit_generate_and_download(self):
        payload = {'items': [{'kitId': 'waveplate', 'quantity': 1}], 'extras': []}
        for role in ('readonly',):
            for path in ('/', '/api/catalog', '/api/shared-kits'):
                self.assertEqual(self.request('/optics-kits' + path, role)[0], 200)
            status, body, _ = self.request('/optics-kits/api/preview', role, payload)
            self.assertEqual(status, 200, body)
            self.assertEqual(json.loads(body)['totals']['kits'], 1)
            status, body, headers = self.request('/optics-kits/api/export?format=manufacturing', role, payload)
            self.assertEqual(status, 200, body[:200])
            self.assertTrue(body.startswith(b'PK'))
            self.assertIn('attachment', headers['Content-Disposition'])

    def test_guest_headers_cannot_spoof_admin(self):
        extra = {'X-ZZLAB-Authenticated': '1', 'X-ZZLAB-User-ID': '11', 'X-ZZLAB-Role': 'admin',
                 'X-ZZLAB-Guest': '0', 'X-ZZLAB-Internal-Token': 'guest-router-test'}
        status, body, _ = self.request('/optics-kits/api/session', extra=extra)
        self.assertEqual(status, 302)
        self.assertEqual(body, b'')
        self.assertEqual(self.request('/optics-kits/api/shared-kits', body={}, extra=extra)[0], 401)

    def test_readonly_cannot_publish_or_manage_even_with_forged_proxy_headers(self):
        for path in ('/api/shared-kits', '/api/shared-kits/' + 'a' * 32 + '/unpublish',
                     '/api/shared-kits/' + 'a' * 32 + '/restore'):
            self.assertEqual(self.request('/optics-kits' + path, 'readonly', {},
                             {'X-ZZLAB-Role': 'admin', 'X-ZZLAB-User-ID': '11'})[0], 403)
        status, body, _ = self.request('/optics-kits/api/session', 'readonly')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'role': 'readonly', 'canPublish': False, 'canDownload': True, 'canDownloadManufacturing': True})

    def test_member_and_admin_keep_publishing_capability(self):
        for role in ('user', 'admin'):
            status, body, _ = self.request('/optics-kits/api/session', role)
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)['canPublish'])

    def test_origin_and_unrelated_login_boundary_remain(self):
        for role in ('readonly',):
            status, body, _ = self.request('/optics-kits/api/preview', role, {},
                             {'Origin': 'https://other.example', 'Sec-Fetch-Site': 'cross-site'})
            self.assertEqual(status, 403)
            self.assertEqual(json.loads(body)['error']['code'], 'cross_origin_denied')
        self.assertEqual(self.request('/warehouse/')[0], 302)
        self.assertEqual(self.request('/optics-kits/api/future-write', body={})[0], 401)
        status, _, headers = self.request('/optics-kits', 'readonly')
        self.assertIn(status, (301, 302, 307, 308))
        self.assertEqual(headers['Location'], '/optics-kits/')

    def test_authenticated_assets_and_readonly_homepage_still_available(self):
        for path in ('/index.html', '/app.js', '/shared-kits.js', '/topviews/kit_waveplate.svg'):
            status, body, _ = self.request('/optics-kits' + path, 'readonly')
            self.assertEqual(status, 200)
            self.assertEqual(body, (ROOT / 'static' / path.removeprefix('/')).read_bytes())
        status, body, _ = self.request('/', 'readonly')
        self.assertEqual(status, 200)
        self.assertIn(b'href="/optics-kits/"', body)

    def test_admin_toggle_controls_actual_anonymous_router_and_backend(self):
        endpoint = '/optics-kits/api/admin/guest-access'
        status, body, _ = self.request(endpoint, 'admin')
        self.assertEqual(status, 200, body)
        initial = json.loads(body)
        self.assertFalse(initial['guestAccessEnabled'])
        payload = {'guestAccessEnabled': True, 'revision': initial['revision']}
        for role, expected in ((None, 401), ('readonly', 403), ('user', 403)):
            self.assertEqual(self.request(endpoint, role, payload)[0], expected)
        status, body, _ = self.request(endpoint, 'admin', payload)
        self.assertEqual(status, 200, body)
        enabled = json.loads(body)
        try:
            self.assertTrue(enabled['guestAccessEnabled'])
            status, body, _ = self.request('/optics-kits/api/session')
            self.assertEqual(status, 200, body)
            self.assertEqual(json.loads(body), {'role': 'guest', 'canPublish': False, 'canDownload': True, 'canDownloadManufacturing': True})
            status, body, _ = self.request('/optics-kits/api/session', extra={
                'X-ZZLAB-Role': 'admin', 'X-ZZLAB-Authenticated': '1', 'X-ZZLAB-User-ID': '11'})
            self.assertEqual(json.loads(body)['role'], 'guest')
            status, body, headers = self.request('/optics-kits/api/export?format=manufacturing',
                             body={'items': [{'kitId': 'waveplate', 'quantity': 1}], 'extras': []})
            self.assertEqual(status, 200, body[:200])
            self.assertTrue(body.startswith(b'PK'))
            self.assertIn('attachment', headers['Content-Disposition'])
            self.assertEqual(self.request('/optics-kits/api/shared-kits', body={})[0], 401)
            self.assertEqual(self.request(endpoint, body=payload)[0], 401)
            self.assertEqual(self.request(endpoint, 'admin', payload)[0], 409)
            for role in (None, 'admin'):
                self.assertNotEqual(self.request('/optics-kits/internal/guest-access', role, extra={
                    'X-ZZLAB-Policy-Probe': '1', 'X-ZZLAB-Internal-Token': 'guest-router-test'})[0], 200)
            with patch.object(self.router_module, 'optics_guest_access_enabled', return_value=False):
                self.assertEqual(self.request('/optics-kits/')[0], 302)
                self.assertEqual(self.request('/optics-kits/', 'readonly')[0], 200)
        finally:
            status, body, _ = self.request(endpoint, 'admin')
            self.assertEqual(status, 200, body)
            status, body, _ = self.request(endpoint, 'admin', {
                'guestAccessEnabled': False, 'revision': json.loads(body)['revision']})
            self.assertEqual(status, 200, body)
        self.assertEqual(self.request('/optics-kits/')[0], 302)
        self.assertEqual(self.request('/optics-kits/api/export?format=bundle', body={})[0], 401)
        self.assertEqual(self.request('/optics-kits/', 'readonly')[0], 200)

    def test_admin_can_revoke_guest_manufacturing_without_disabling_anonymous_editor(self):
        endpoint = '/optics-kits/api/admin/guest-access'
        before = json.loads(self.request(endpoint, 'admin')[1])
        payload = {'items': [{'kitId': 'waveplate', 'quantity': 1}], 'extras': []}
        def save(enabled):
            current = json.loads(self.request(endpoint, 'admin')[1])
            status, body, _ = self.request(endpoint, 'admin', {
                'guestAccessEnabled': True, 'guestManufacturingDownloadsEnabled': enabled,
                'revision': current['revision']})
            self.assertEqual(status, 200, body)
        try:
            for enabled in (True, False, True):
                save(enabled)
                for role in (None, 'readonly', 'user', 'admin'):
                    allowed = enabled or role is not None
                    status, body, _ = self.request('/optics-kits/api/session', role)
                    self.assertEqual(status, 200, body)
                    self.assertEqual(json.loads(body)['canDownloadManufacturing'], allowed)
                    self.assertEqual(self.request('/optics-kits/', role)[0], 200)
                    self.assertEqual(self.request('/optics-kits/api/preview', role, payload)[0], 200)
                    with patch('app.export_result', return_value=(b'CAD ZIP', 'application/zip', 'package.zip')) as export:
                        status, body, headers = self.request('/optics-kits/api/export?format=bundle', role, payload)
                        self.assertEqual(status, 200 if allowed else 403, (enabled, role))
                        self.assertEqual(headers['Cache-Control'], 'no-store')
                        if allowed:
                            export.assert_called_once()
                            self.assertEqual(body, b'CAD ZIP')
                        else:
                            export.assert_not_called()
                            self.assertEqual(json.loads(body)['error']['code'], 'manufacturing_download_forbidden')
                    status, body, _ = self.request('/optics-kits/api/export?format=manufacturing', role, payload)
                    self.assertEqual(status, 200, body[:200])
                    self.assertTrue(body.startswith(b'PK'))
                if not enabled:
                    status, body, _ = self.request('/optics-kits/api/export?format=bundle', body=payload, extra={
                        'X-ZZLAB-Role': 'admin', 'X-ZZLAB-Authenticated': '1', 'X-ZZLAB-User-ID': '11'})
                    self.assertEqual(status, 403, body)
                    for route in ('/assets/private.step', '/drawings/file.pdf', '/board-cache/board.step'):
                        status, body, _ = self.request('/optics-kits' + route)
                        self.assertIn(status, (302, 404))
                        self.assertNotIn(b'ISO-10303', body)
        finally:
            current = json.loads(self.request(endpoint, 'admin')[1])
            status, body, _ = self.request(endpoint, 'admin', {
                'guestAccessEnabled': before['guestAccessEnabled'],
                'guestManufacturingDownloadsEnabled': before['guestManufacturingDownloadsEnabled'],
                'revision': current['revision']})
            self.assertEqual(status, 200, body)

    def test_policy_probe_errors_and_malformed_responses_fail_closed(self):
        module = self.router_module
        for status, body in ((503, b'{}'), (200, b'not json'), (200, b'{"guestAccessEnabled":"true"}'),
                             (200, b'[]'), (200, b'{"guestAccessEnabled":false}'), (200, b'x' * 1025)):
            with self.subTest(status=status, body=body[:40]):
                from unittest.mock import MagicMock
                connection = MagicMock()
                response = connection.getresponse.return_value
                response.status = status
                response.read.return_value = body
                with patch.object(module.http.client, 'HTTPConnection', return_value=connection):
                    self.assertFalse(module.optics_guest_access_enabled())
                connection.close.assert_called_once()
        with patch.object(module.http.client, 'HTTPConnection') as factory:
            factory.return_value.request.side_effect = OSError('probe unavailable')
            self.assertFalse(module.optics_guest_access_enabled())
            factory.return_value.close.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
