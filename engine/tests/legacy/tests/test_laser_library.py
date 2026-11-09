"""Factory-source registration, order semantics and physical installation boundaries."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bom import aggregate, load_catalog
from exports import export_result
from deploy_support import registered_reference_assembly


class LaserLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / 'catalog.json')
        cls.kits = {k['id']: k for k in cls.catalog['kits']}

    def test_three_reported_main_lasers_are_purchased_whole_without_fabricated_cad(self):
        quantities = {'laser-399nm': 2, 'laser-556nm': 3, 'laser-935nm': 4}
        result = aggregate(self.catalog, {'items': [{'kitId': k, 'quantity': q} for k, q in quantities.items()]})
        self.assertEqual(result['manufacturing'], [])
        self.assertEqual(result['lubang'], [])
        self.assertEqual({r['componentId']:r['quantity'] for r in result['standard']}, quantities)
        content, _, _ = export_result(result, 'bundle', ROOT / 'assets', ROOT / 'static')
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertFalse(any(Path(n).suffix.lower() in {'.step', '.stp', '.pdf'} for n in archive.namelist()))

    def test_source_pdfs_and_mechanical_views_are_real_reviewed_assets(self):
        for identity in ('laser-399nm', 'laser-556nm', 'laser-935nm'):
            with self.subTest(identity=identity):
                layout = self.kits[identity]['layout']
                svg = (ROOT / 'static' / layout['topViewPath']).read_text()
                self.assertIn('<svg', svg)
                self.assertIn(identity.removeprefix('laser-').removesuffix('nm'), svg)
                self.assertGreater(layout['widthMm'], 0)
                self.assertGreater(layout['heightMm'], 0)
                self.assertTrue(layout['collisionPolygonsMm'])
                for source in layout['sourceReport']['sourceFiles']:
                    data = (ROOT / source['path']).read_bytes()
                    self.assertTrue(data.startswith(b'%PDF-'))
                    self.assertEqual(hashlib.sha256(data).hexdigest(), source['sha256'])

    def test_unconfirmed_clamping_positions_do_not_become_fictitious_board_holes(self):
        for identity in ('laser-556nm', 'laser-935nm'):
            kit = self.kits[identity]
            self.assertEqual(kit['layout']['mountingHoleOffsetsMm'], [])
            payload = {'layout': {'board': {'widthMm':1600,'heightMm':900,'pitchMm':25,'edgeOffsetMm':12.5,
                                          'thicknessMm':12.7,'holeType':'M6_through'},
                                  'instances': [{'id':'laser', 'kitId':identity,'xMm':700,'yMm':450,'rotationDeg':0}]}}
            result = aggregate(self.catalog, payload)
            self.assertIn('mounting_unconfirmed', {i['code'] for i in result['layoutValidation']['issues']})
            payload['layout']['baseMode'] = 'table'
            table = aggregate(self.catalog, payload)
            self.assertNotIn('mounting_unconfirmed', {i['code'] for i in table['layoutValidation']['issues']})

    def test_399_unknown_optical_datums_remain_explicit(self):
        layout = self.kits['laser-399nm']['layout']
        self.assertIsNone(layout['opticalAxisHeightMm'])
        self.assertFalse(layout['opticalDatumVerified'])
        self.assertTrue(layout['placementAllowed'])
        self.assertIn('待', layout['opticalSimulationNote'])
        self.assertEqual(layout['opticalDefaults']['source']['wavelengthNm'], 398.90264)

    def test_fiber_seed_is_reference_only_and_cannot_duplicate_the_935_purchase(self):
        seed = self.kits['laser-seed-1870nm']
        self.assertTrue(registered_reference_assembly(seed))
        self.assertFalse(seed['layout']['placementAllowed'])
        self.assertEqual(seed['layout']['opticalPortsMm'], [])
        result = aggregate(self.catalog, {'items':[{'kitId':'laser-seed-1870nm','quantity':3},
                                                  {'kitId':'laser-935nm','quantity':1}]})
        self.assertEqual([(r['componentId'],r['quantity']) for r in result['standard']], [('laser-935nm',1)])
        self.assertEqual(result['manufacturing'], [])
        for mutation in ('id','parts','sha','port','source'):
            forged = copy.deepcopy(seed)
            if mutation == 'id': forged['id'] = 'arbitrary-reference'
            if mutation == 'parts': forged['components'] = [{'componentId':'laser-935nm','quantity':1}]
            if mutation == 'sha': forged['sourceReport']['sourceFiles'][0]['sha256'] = '0'*64
            if mutation == 'port': forged['layout']['opticalPortsMm'] = [{'xMm':0,'yMm':0}]
            if mutation == 'source': forged['layout']['opticalDefaults'] = {'elementType':'source','source':{'enabled':True}}
            self.assertFalse(registered_reference_assembly(forged), mutation)


if __name__ == '__main__':
    unittest.main()
