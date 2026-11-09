"""Every editor dependency must load for limited roles, not just dev/member."""
import http.client
import re
import tempfile
import threading
import unittest
from pathlib import Path

from app import Config, create_server

ROOT = Path(__file__).resolve().parents[1]


class EditorStaticAccessTests(unittest.TestCase):
    def test_all_editor_scripts_and_styles_load_for_readonly(self):
        references = re.findall(r'<(?:script|link)\b[^>]*(?:src|href)="([^"]+)"',
                                (ROOT / 'static/index.html').read_text())
        references = [v.removeprefix('./').split('?')[0] for v in references]
        with tempfile.TemporaryDirectory() as folder:
            config = Config(ROOT / 'catalog.json', ROOT / 'assets', ROOT / 'static',
                            'static-test-secret', Path(folder) / 'shared.sqlite3')
            server = create_server(config, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for name in references:
                    with self.subTest(name=name):
                        conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
                        try:
                            conn.request('GET', '/optics-kits/' + name, headers={
                                'X-ZZLAB-Internal-Token': 'static-test-secret',
                                'X-ZZLAB-Authenticated': '1', 'X-ZZLAB-Role': 'readonly',
                                'X-ZZLAB-User-ID': '1'})
                            response = conn.getresponse()
                            self.assertEqual(response.status, 200)
                            self.assertEqual(response.read(), (ROOT / 'static' / name).read_bytes())
                        finally:
                            conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
