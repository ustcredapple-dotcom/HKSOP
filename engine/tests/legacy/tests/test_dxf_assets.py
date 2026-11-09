"""Optional registered DXFs follow the same selected-asset boundary as PDFs."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from bom import APIError, aggregate, validate_catalog
from cart import combine, export_preview, row_identity, rows
from exports import export_result
from test_backend import fixture
import test_access_settings as access_tests


def state_for(preview):
    state = {'sources': [{'id': 's1', 'name': '方案', 'createdAt': '2026-10-04T00:00:00.000Z', 'preview': preview}], 'choices': {}}
    combined, _ = combine(state)
    state['choices'] = {row['componentId']: {'selected': True, 'removed': False, 'quantity': row['quantity']} for row in rows(combined)}
    return state


class DxfAssetTests(unittest.TestCase):
    def setUp(self):
        self.catalog = fixture()
        self.catalog['components'][0].update(dxfPath='plate.dxf', dxfPdfPath='plate_DXF.pdf', dxfPdfSha256=hashlib.sha256(b'plate_DXF.pdf').hexdigest())

    def test_catalog_rejects_wrong_suffix_and_escaping_dxf(self):
        for path in ('../secret.dxf', '/secret.dxf', 'safe/../secret.dxf', 'x.pdf', 'x.DXF/../x.dxf', 'x\\y.dxf'):
            with self.subTest(path=path), self.assertRaises(APIError):
                validate_catalog({**self.catalog, 'components': [{**self.catalog['components'][0], 'dxfPath': path}] + self.catalog['components'][1:]})

    def test_bundle_copies_pdf_instead_of_dxf_and_hash_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('plate.step', 'plate.pdf', 'plate.dxf', 'plate_DXF.pdf'):
                (root/name).write_bytes(name.encode())
            preview = aggregate(self.catalog, {'items': [{'kitId': 'alpha', 'quantity': 3}]})
            content, _, _ = export_result(preview, 'bundle', root)
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                config = json.loads(z.read('套件配置.json'))
                self.assertFalse(any(n.endswith('.dxf') for n in z.namelist()))
                self.assertEqual(len([n for n in z.namelist() if n.endswith('.pdf')]), 2)
                path = config['assets']['plate']['drawingSupplement']
                self.assertEqual(z.read(path), b'plate_DXF.pdf')
                self.assertIn(path, config['fileChecksums'])
            (root/'plate_DXF.pdf').unlink()
            with self.assertRaises(APIError) as caught:
                export_result(preview, 'bundle', root)
            self.assertEqual(caught.exception.code, 'asset_missing')

    def test_older_cart_can_receive_current_optional_dxf_only(self):
        old = copy.deepcopy(self.catalog)
        del old['components'][0]['dxfPath']
        del old['components'][0]['dxfPdfPath']
        del old['components'][0]['dxfPdfSha256']
        original = aggregate(old, {'items': [{'kitId': 'alpha', 'quantity': 1}]})
        state = state_for(original)
        preview = export_preview(state, self.catalog)
        self.assertEqual(preview['manufacturing'][0]['dxfPath'], 'plate.dxf')
        self.assertEqual(preview['manufacturing'][0]['dxfPdfPath'], 'plate_DXF.pdf')
        self.assertIsNone(state['sources'][0]['preview']['manufacturing'][0].get('dxfPdfPath'))
        self.assertIsNone(state['sources'][0]['preview']['manufacturing'][0].get('dxfPath'))
        row = original['manufacturing'][0]
        self.assertEqual(row_identity(row, 's1'), row_identity({**row, 'dxfPath': None}, 's1'))

    def test_cart_rejects_changed_or_forged_historical_dxf(self):
        preview = aggregate(self.catalog, {'items': [{'kitId': 'alpha', 'quantity': 1}]})
        for path in ('old.dxf', '../outside.dxf', '/outside.dxf'):
            with self.subTest(path=path):
                altered = copy.deepcopy(preview)
                altered['manufacturing'][0]['dxfPath'] = path
                with self.assertRaises(APIError) as caught:
                    export_preview(state_for(altered), self.catalog)
                self.assertEqual(caught.exception.code, 'cart_source_changed')

    def test_new_drawing_cannot_be_mixed_with_old_snapshot_step(self):
        old = copy.deepcopy(self.catalog)
        old['components'][0]['drawingPath'] = None
        old['components'][0]['stepPath'] = 'old-geometry.step'
        old['components'][0].pop('dxfPath', None)
        state = state_for(aggregate(old, {'items': [{'kitId': 'alpha', 'quantity': 1}]}))
        with self.assertRaises(APIError) as caught:
            export_preview(state, self.catalog)
        self.assertEqual(caught.exception.code, 'cart_source_changed')

    def test_deselected_dxf_is_not_read_or_exported(self):
        preview = aggregate(self.catalog, {'items': [{'kitId': 'alpha', 'quantity': 1}]})
        state = state_for(preview)
        combined, _ = combine(state)
        for row in combined['manufacturing']:
            state['choices'][row['componentId']]['selected'] = False
        selected = export_preview(state, self.catalog)
        with tempfile.TemporaryDirectory() as temp:
            content, _, _ = export_result(selected, 'bundle', temp)
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                self.assertFalse(any(n.endswith('.dxf') for n in z.namelist()))


class GuestDxfHTTPTests(unittest.TestCase):
    setUp = access_tests.AccessSettingsHTTPTests.setUp
    tearDown = access_tests.AccessSettingsHTTPTests.tearDown
    start_server = access_tests.AccessSettingsHTTPTests.start_server
    stop_server = access_tests.AccessSettingsHTTPTests.stop_server
    http = access_tests.AccessSettingsHTTPTests.http
    setting = access_tests.AccessSettingsHTTPTests.setting
    download_policy = access_tests.AccessSettingsHTTPTests.download_policy

    def test_guest_dxf_uses_manufacturing_download_permission(self):
        catalog = json.loads(self.config.catalog.read_text())
        catalog['components'][0].update(dxfPath='plate.dxf',dxfPdfPath='plate_DXF.pdf')
        self.config.catalog.write_text(json.dumps(catalog))
        (self.root/'plate.dxf').write_bytes(b'0\nSECTION\nTEST-DXF')
        (self.root/'plate_DXF.pdf').write_bytes(b'%PDF-converted-fixture')
        payload = {'items': [{'kitId': 'alpha', 'quantity': 1}]}
        self.assertEqual(self.download_policy(False)[0], 200)
        status, response = self.http('POST', '/api/export?format=bundle', payload, role='guest')
        self.assertEqual(status, 403)
        self.assertEqual(response['error']['code'], 'manufacturing_download_forbidden')
        for path in ('/assets/plate.dxf', '/plate.dxf', '/assets/plate_DXF.pdf', '/plate_DXF.pdf'):
            self.assertEqual(self.http('GET', path, role='guest')[0], 404)
        for role in ('readonly', 'guest'):
            if role == 'guest':
                self.assertEqual(self.download_policy(True)[0], 200)
            status, content = self.http('POST', '/api/export?format=bundle', payload, role=role)
            self.assertEqual(status, 200, content if status != 200 else '')
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                self.assertFalse(any(n.endswith('.dxf') for n in z.namelist()))
                name=json.loads(z.read('套件配置.json'))['assets']['plate']['drawingSupplement']
                self.assertEqual(z.read(name), b'%PDF-converted-fixture')


if __name__ == '__main__':
    unittest.main()
