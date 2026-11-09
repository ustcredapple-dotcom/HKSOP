"""Frozen SLM assembly, shared review drawings and source-specific processing."""
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from openpyxl import load_workbook
from pypdf import PdfReader
from bom import aggregate
from exports import export_result
from qa.register_slm import (ROOT, EVIDENCE, SOURCE, IDS, ADAPTER, HEAD, POST,
                             COMPONENT_STEP_SHA, build_catalog, digest, load)


class SlmCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = load(ROOT/'catalog.json')
        cls.layouts = load(EVIDENCE/'layouts.json')
        cls.posts = load(EVIDENCE/'post-compatibility-audit.json')
        cls.catalog, cls.transfers, cls.report = build_catalog(cls.original, cls.layouts, cls.posts)

    def result(self):
        return aggregate(self.catalog, {'items': [{'kitId': IDS[0], 'quantity': 2}, {'kitId': IDS[1], 'quantity': 3}]})

    def test_incremental_registration_keeps_existing_components(self):
        new_ids = {ADAPTER, HEAD, 'new-slm-m4x16', 'new-slm-m6x8-review', 'new-slm-dowel-d2'}
        for section, ids in [('components', new_ids), ('kits', set(IDS)), ('categories', {'slm'})]:
            actual = {r['id']: r for r in self.catalog[section]}
            for record in self.original[section]:
                if record['id'] not in ids:
                    self.assertEqual(actual[record['id']], record)
        again, _, _ = build_catalog(self.catalog, self.layouts, self.posts)
        self.assertEqual(again, self.catalog)

    def test_full_review_files_source_hashes_and_three_pages(self):
        adapter = next(c for c in self.catalog['components'] if c['id'] == ADAPTER)
        self.assertTrue(adapter['drawingPath'])
        self.assertTrue(adapter['dxfPath'])
        self.assertTrue(adapter['sourceDocumentsComplete'])
        self.assertEqual(adapter['sourceStepSha256'], COMPONENT_STEP_SHA)
        self.assertFalse(adapter['productionReady'])
        pdf = SOURCE/'工程图/21-SLM_R1_加工工程图.pdf'
        reader = PdfReader(pdf)
        self.assertEqual(len(reader.pages), 3)
        text = '\n'.join(p.extract_text() for p in reader.pages)
        self.assertIn('去磁、钝化', text)
        self.assertIn('H03', text)
        self.assertEqual(digest(pdf), adapter['sourceDrawingSha256'])

    def test_variants_share_one_adapter_and_original_post_sku(self):
        result = self.result()
        manufacture = {r['componentId']: r for r in result['manufacturing']}
        self.assertEqual(set(manufacture), {ADAPTER, POST})
        self.assertEqual(manufacture[ADAPTER]['quantity'], 5)
        self.assertEqual(manufacture[POST]['quantity'], 5)
        standards = {r['componentId']: r for r in result['standard']}
        self.assertEqual(standards[HEAD]['quantity'], 5)
        self.assertEqual(standards['new-slm-dowel-d2']['quantity'], 10)
        self.assertIn('待', standards['new-slm-m6x8-review']['status'])
        self.assertFalse(result['lubang'])
        self.assertFalse(any(g.get('blocking') for g in result['reviewGroups']))

    def test_cannot_accept_unverified_post_or_wrong_topview(self):
        posts = copy.deepcopy(self.posts)
        posts[IDS[0]]['passed'] = False
        with self.assertRaisesRegex(ValueError, 'post has not passed'):
            build_catalog(self.original, self.layouts, posts)
        layouts = copy.deepcopy(self.layouts)
        layouts[IDS[0]]['geometryEvidence']['sourceSha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'top view'):
            build_catalog(self.original, layouts, self.posts)

    def test_optical_reference_is_explicitly_unsupported_not_false_mirror(self):
        for kit in self.catalog['kits']:
            if kit['id'] not in IDS:
                continue
            self.assertEqual(kit['layout']['opticalType'], 'unsupported')
            self.assertEqual(kit['layout']['opticalCenterMm'], {'xMm': 0, 'yMm': 0})
            self.assertEqual(kit['layout']['opticalAxisHeightMm'], 63.5)
            self.assertEqual(kit['bundleStatus'], 'complete')
            self.assertIn('/v/2ed7fb2849af8aa467c0db11/', kit['sourceUrl'])

    def test_complete_bundle_contains_step_pdf_dxf_and_correct_materials(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for dest, source in self.transfers.items():
                (root/dest).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, root/dest)
            post = next(c for c in self.catalog['components'] if c['id'] == POST)
            for key in ('stepPath', 'drawingPath'):
                (root/post[key]).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT/'assets'/post[key], root/post[key])
            content, _, _ = export_result(self.result(), 'bundle', root)
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                config = json.loads(z.read('套件配置.json'))
                self.assertEqual(len([n for n in z.namelist() if n.endswith('.step')]), 2)
                self.assertEqual(len([n for n in z.namelist() if n.endswith('.pdf')]), 2)
                self.assertEqual(len([n for n in z.namelist() if n.endswith('.dxf')]), 1)
                self.assertIn('dxf', config['assets'][ADAPTER])
                book = load_workbook(io.BytesIO(z.read('生产清单.xlsx')))
                table = list(book['生产清单'].values)
                adapter = next(r for r in table if '21-SLM-R1' in r)
                postrow = next(r for r in table if 'ZZ-01' in r)
                self.assertIn('去磁、钝化', adapter)
                self.assertIn('退磁、喷砂', postrow)


if __name__ == '__main__':
    unittest.main()
