"""Release inventory probes must not hide missing kits behind a fixed count."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_support as deploy


def catalog():
    return {'version': 'release-test', 'kits': [
        *({'id': f'kit-{index}'} for index in range(20)), {'id': 'laser-308nm'}
    ]}


class DeployCatalogInventoryTests(unittest.TestCase):
    def test_new_kit_and_arbitrary_order_match_source(self):
        source = catalog()
        actual = copy.deepcopy(source)
        actual['kits'].reverse()
        self.assertEqual(deploy.verify_catalog_inventory(actual, source),
                         sorted(kit['id'] for kit in source['kits']))

    def test_same_count_cannot_hide_replaced_kit(self):
        source = catalog()
        actual = copy.deepcopy(source)
        actual['kits'][-1]['id'] = 'unexpected-kit'
        with self.assertRaisesRegex(RuntimeError, r'missing=.*laser-308nm.*unexpected=.*unexpected-kit'):
            deploy.verify_catalog_inventory(actual, source)

    def test_omitted_new_kit_is_rejected(self):
        source = catalog()
        actual = copy.deepcopy(source)
        actual['kits'].pop()
        with self.assertRaisesRegex(RuntimeError, 'laser-308nm'):
            deploy.verify_catalog_inventory(actual, source)

    def test_duplicate_source_or_release_is_rejected(self):
        for side in ('source', 'release'):
            with self.subTest(side=side):
                source = catalog()
                actual = copy.deepcopy(source)
                target = source if side == 'source' else actual
                target['kits'].append(copy.deepcopy(target['kits'][0]))
                with self.assertRaisesRegex(RuntimeError, 'duplicate kit IDs'):
                    deploy.verify_catalog_inventory(actual, source)

    def test_empty_and_invalid_inventory_is_rejected(self):
        for kits in (None, [], {}, [{'id': ''}], [{'id': None}], [{}], [None]):
            with self.subTest(kits=kits), self.assertRaises(RuntimeError):
                deploy.verify_catalog_inventory({'kits': kits}, catalog())

    def test_download_matrix_checks_all_source_kits(self):
        source = catalog()
        exported = []

        def request(url, headers, payload=None, *args):
            if url.endswith('/api/catalog'):
                return 200, json.dumps(source).encode()
            if url.endswith('/api/preview'):
                return 200, b'{}'
            if url.endswith('/api/export?format=bundle'):
                exported.append(payload['items'][0]['kitId'])
                content = io.BytesIO()
                with zipfile.ZipFile(content, 'w') as archive:
                    archive.writestr('套件配置.json', json.dumps(payload))
                return 200, content.getvalue()
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary)
            (source_path / 'catalog.json').write_text(json.dumps(source))
            with patch.object(deploy, 'SOURCE', source_path), \
                    patch.object(deploy, 'request_status', side_effect=request), \
                    patch.object(deploy, 'verify_layout_downloads', return_value={}), \
                    patch.object(deploy, 'verify_browser_origin', return_value={}):
                report = deploy.verify_download_matrix({})
        self.assertEqual(report['complete_bundles'], 21)
        self.assertEqual(report['expected_blocked_bundles'], 0)
        self.assertEqual(report['source_kit_ids'], sorted(exported))
        self.assertEqual(exported, [kit['id'] for kit in source['kits']])

    def test_inventory_mismatch_stops_before_exports(self):
        source = catalog()
        actual = copy.deepcopy(source)
        actual['kits'].pop()
        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary)
            (source_path / 'catalog.json').write_text(json.dumps(source))
            with patch.object(deploy, 'SOURCE', source_path), \
                    patch.object(deploy, 'request_status', return_value=(200, json.dumps(actual).encode())) as request:
                with self.assertRaisesRegex(RuntimeError, 'laser-308nm'):
                    deploy.verify_download_matrix({})
                request.assert_called_once()

    def test_design_review_bundle_must_be_explicit_and_fail_closed(self):
        source = catalog()
        source['kits'] = [{'id': 'review-kit', 'releaseStage': 'design-review',
                           'bundleStatus': 'blocked', 'bundleNote': '设计检查版；加工图待补齐'}]

        def request(url, headers, payload=None, *args):
            if url.endswith('/api/catalog'):
                return 200, json.dumps(source).encode()
            if url.endswith('/api/preview'):
                return 200, b'{}'
            if url.endswith('/api/export?format=bundle'):
                return 409, b'{"error":{"code":"asset_missing"}}'
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder/'catalog.json').write_text(json.dumps(source))
            with patch.object(deploy, 'SOURCE', folder), \
                    patch.object(deploy, 'request_status', side_effect=request), \
                    patch.object(deploy, 'verify_layout_downloads', return_value={}), \
                    patch.object(deploy, 'verify_browser_origin', return_value={}):
                result = deploy.verify_download_matrix({})
            self.assertEqual(result['expected_blocked_bundles'], 1)
            self.assertEqual(result['complete_bundles'], 0)
            del source['kits'][0]['releaseStage']
            (folder/'catalog.json').write_text(json.dumps(source))
            with patch.object(deploy, 'SOURCE', folder), \
                    patch.object(deploy, 'request_status', side_effect=request):
                with self.assertRaisesRegex(RuntimeError, 'explicitly registered'):
                    deploy.verify_download_matrix({})

class DeploymentProbeBoundsTests(unittest.TestCase):
    def test_default_probe_budget_supports_large_registered_catalog_and_remains_bounded(self):
        class Response(io.BytesIO):
            status=200
        content=b'x'*(1024*1024+20)
        with patch.object(deploy.OPENER,'open',return_value=Response(content)):
            status,received=deploy.request_status(f'http://127.0.0.1:{deploy.PORT}/api/catalog')
        self.assertEqual(status,200);self.assertEqual(received,content)
        with patch.object(deploy.OPENER,'open',return_value=Response(b'x'*(8*1024*1024+1))):
            with self.assertRaisesRegex(RuntimeError,'exceeded'):deploy.request_status(f'http://127.0.0.1:{deploy.PORT}/api/catalog')

    def test_reference_exception_is_bound_to_reviewed_final_source_not_any_blocked_kit(self):
        source=json.loads((Path(__file__).resolve().parents[1]/'catalog.json').read_text())
        kit=next(k for k in source['kits'] if k['id']=='objective-final-assembly')
        self.assertTrue(deploy.registered_reference_assembly(kit))
        for key,value in [('id','other-kit'),('bomPolicy',None),('releaseStage','design-review'),('components',[{'componentId':'x','quantity':1}]),('bundleNote','')]:
            changed=copy.deepcopy(kit);changed[key]=value;self.assertFalse(deploy.registered_reference_assembly(changed))
        for key,value in [('documentId','other'),('elementId','other'),('finalAssemblyConfirmed',False),('bomVerified',True),('stepSha256','bad')]:
            changed=copy.deepcopy(kit);changed['sourceAssembly'][key]=value;self.assertFalse(deploy.registered_reference_assembly(changed))

class ReferenceArchiveDeploymentTests(unittest.TestCase):
    def setUp(self):
        from bom import load_catalog,aggregate
        from exports import export_result
        root=Path(__file__).resolve().parents[1];catalog=load_catalog(root/'catalog.json')
        self.kit=next(k for k in catalog['kits'] if k['id']=='objective-final-assembly')
        self.preview=aggregate(catalog,{'items':[{'kitId':self.kit['id'],'quantity':1}]})
        self.content=export_result(self.preview,'bundle',root/'assets',root/'static')[0]
    def test_real_reference_archive_is_reported_separately_from_manufacturing(self):
        source={'version':'release-test','kits':[self.kit]}
        def request(url,headers,payload=None,*args):
            if url.endswith('/api/catalog'):return 200,json.dumps(source).encode()
            if url.endswith('/api/preview'):return 200,json.dumps(self.preview).encode()
            if url.endswith('/api/export?format=bundle'):return 200,self.content
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'catalog.json').write_text(json.dumps(source))
            with patch.object(deploy,'SOURCE',root),patch.object(deploy,'request_status',side_effect=request),patch.object(deploy,'verify_layout_downloads',return_value={}),patch.object(deploy,'verify_browser_origin',return_value={}):result=deploy.verify_download_matrix({})
        self.assertEqual(result['complete_bundles'],0);self.assertEqual(result['expected_blocked_bundles'],0);self.assertEqual(result['reference_only_packages'],1)
        self.assertEqual(result['kits'][0]['bundle'],'reference_only')
    def test_reference_archive_rejects_phantom_purchase_or_manufacturing_assets(self):
        bad_preview=copy.deepcopy(self.preview);bad_preview['lubang']=[{'model':'ghost','quantity':1}]
        with self.assertRaises(RuntimeError):deploy.verify_reference_assembly_package(self.kit,bad_preview,self.content)
        for extra in ('ghost.step','ghost.PDF'):
            buffer=io.BytesIO(self.content)
            with zipfile.ZipFile(buffer,'a') as z:z.writestr(extra,b'ghost')
            with self.assertRaises(RuntimeError):deploy.verify_reference_assembly_package(self.kit,self.preview,buffer.getvalue())
        buffer=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.content)) as original,zipfile.ZipFile(buffer,'w') as target:
            for name in original.namelist():
                data=original.read(name)
                if name=='套件配置.json':
                    config=json.loads(data);config['components']=[{'componentId':'ghost','quantity':1}];data=json.dumps(config).encode()
                target.writestr(name,data)
        with self.assertRaises(RuntimeError):deploy.verify_reference_assembly_package(self.kit,self.preview,buffer.getvalue())


if __name__ == '__main__':
    unittest.main()
