"""Marking files participate in the existing authoritative asset trust gates."""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from bom import validate_laser_marking
import test_library_protocol as protocol

lib, ROOT = protocol.lib, protocol.ROOT


class LaserMarkingProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dxf = b'0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n'
        self.pdf = b'%PDF-1.4\nfixture setup only\n%%EOF\n'
        self.marking = {'status': 'required', 'reason': '识别', 'files': [
            {'face': '顶面', 'text': 'P-01', 'dxfPath': 'drawings/marking/top.dxf', 'sha256': lib.sha(self.dxf),
             'setupPdfPath': 'drawings/marking/top.pdf', 'setupPdfSha256': lib.sha(self.pdf)}]}
        self.catalog = {'version': 'fixture', 'updatedAt': '2026-10-11', 'categories': [], 'kits': [], 'registeredBoards': [],
                        'components': [{'id': 'part', 'name': '测试件', 'kind': 'standard', 'unit': '个', 'laserMarking': self.marking}]}
        for relative, data in ((self.marking['files'][0]['dxfPath'], self.dxf), (self.marking['files'][0]['setupPdfPath'], self.pdf)):
            lib.atomic_write(self.root/'assets'/relative, data)

    def test_dxf_and_setup_pdf_are_indexed_with_nested_references(self):
        lib.validate_structure(self.catalog)
        rows = lib.asset_inventory(self.catalog, self.root)
        self.assertEqual({row['path'] for row in rows}, {'assets/drawings/marking/top.dxf', 'assets/drawings/marking/top.pdf'})
        self.assertTrue(any('/laserMarking/files/0/dxfPath' in ref for row in rows for ref in row['references']))
        self.assertTrue(any('/laserMarking/files/0/setupPdfPath' in ref for row in rows for ref in row['references']))
        self.assertEqual(next(row['sha256'] for row in rows if row['path'].endswith('.pdf')), lib.sha(self.pdf))

    def test_each_marking_and_setup_hash_must_match_frozen_record(self):
        for field in ('sha256', 'setupPdfSha256'):
            catalog = copy.deepcopy(self.catalog)
            catalog['components'][0]['laserMarking']['files'][0][field] = '0'*64
            with self.subTest(field=field), self.assertRaisesRegex(lib.LibraryError, 'laser marking hash mismatch'):
                lib.asset_inventory(catalog, self.root)

    def test_each_registered_file_must_exist(self):
        for field in ('dxfPath', 'setupPdfPath'):
            catalog = copy.deepcopy(self.catalog)
            catalog['components'][0]['laserMarking']['files'][0][field] = 'drawings/missing.' + ('dxf' if field == 'dxfPath' else 'pdf')
            with self.subTest(field=field), self.assertRaisesRegex(lib.LibraryError, 'Missing runtime asset'):
                lib.asset_inventory(catalog, self.root)

    def test_marking_is_confined_to_drawings_without_widening_package_whitelist(self):
        for path in ('step/top.dxf', 'marking/top.dxf', 'drawings/../secret.dxf', '/drawings/top.dxf', 'drawings/x.pdf'):
            catalog = copy.deepcopy(self.catalog)
            catalog['components'][0]['laserMarking']['files'][0]['dxfPath'] = path
            with self.subTest(path=path), self.assertRaises(lib.LibraryError):
                lib.validate_structure(catalog)
        catalog = copy.deepcopy(self.catalog)
        catalog['components'][0]['laserMarking']['files'][0]['setupPdfPath'] = 'step/top.pdf'
        with self.assertRaises(lib.LibraryError):
            list(lib.asset_references(catalog))

    def test_schema_contract_has_states_required_files_pairs_and_reusable_board_ref(self):
        schema = json.loads((ROOT/'library/schemas/component.schema.json').read_text())
        marking = schema['$defs']['laserMarking']
        self.assertEqual(schema['properties']['laserMarking'], {'$ref': '#/$defs/laserMarking'})
        self.assertEqual(set(marking['required']), {'status', 'files'})
        self.assertEqual(set(marking['properties']['status']['enum']), {'required', 'none', 'review'})
        item = marking['properties']['files']['items']
        self.assertEqual(set(item['required']), {'face', 'dxfPath', 'sha256'})
        self.assertEqual(item['dependentRequired'], {'setupPdfPath': ['setupPdfSha256'], 'setupPdfSha256': ['setupPdfPath']})
        self.assertFalse(item['additionalProperties'])
        for field, good, bad in (('dxfPath','drawings/打标/顶面.dxf','step/top.dxf'), ('setupPdfPath','drawings/打标/顶面.pdf','drawings/top.dxf')):
            pattern = item['properties'][field]['pattern']
            self.assertRegex(good, pattern)
            self.assertIsNone(re.search(pattern, bad))
            for illegal in ('drawings/../top.'+good.rsplit('.',1)[1], 'drawings//top.'+good.rsplit('.',1)[1]):
                self.assertIsNone(re.search(pattern, illegal))
        board = json.loads((ROOT/'library/schemas/board.schema.json').read_text())
        self.assertEqual(board['properties']['laserMarking']['$ref'], 'component.schema.json#/$defs/laserMarking')
        for mutate in (lambda value: value.pop('files'), lambda value: value.update(unregistered=True),
                       lambda value: value['files'][0].pop('setupPdfSha256'),
                       lambda value: value['files'][0].update(unregistered=True)):
            value = copy.deepcopy(self.marking)
            mutate(value)
            with self.assertRaises(ValueError):
                validate_laser_marking(value)

    def test_board_marking_uses_same_nested_asset_and_hash_checks(self):
        # asset_inventory accepts board records independently of geometry validation.
        catalog = {'components': [], 'kits': [], 'registeredBoards': [{'id':'board', 'laserMarking':copy.deepcopy(self.marking)}]}
        self.assertEqual(len(lib.asset_inventory(catalog, self.root)), 2)
        catalog['registeredBoards'][0]['laserMarking']['files'][0]['setupPdfSha256'] = '0'*64
        with self.assertRaisesRegex(lib.LibraryError, 'boards/board/laserMarking'):
            lib.asset_inventory(catalog, self.root)

    def test_marking_package_stages_both_assets_without_touching_active_source(self):
        fixture = protocol.LibraryProtocolTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.part_b['laserMarking'] = copy.deepcopy(self.marking)
        lib.atomic_write(fixture.package/'records/part-b.json', lib.json_bytes(fixture.part_b))
        fixture.package_spec['assets'] = []
        for relative, data in ((self.marking['files'][0]['dxfPath'], self.dxf), (self.marking['files'][0]['setupPdfPath'], self.pdf)):
            payload = 'payload/' + Path(relative).name
            lib.atomic_write(fixture.package/payload, data)
            fixture.package_spec['assets'].append({'root':'assets','path':relative,'source':payload,'sha256':lib.sha(data)})
        fixture.write_package()
        before = lib.source_state_sha(fixture.source)
        stage = fixture.make_stage()
        index = lib.read_json(stage/'library/generated/asset-index.json')['assets']
        self.assertEqual(len(index), 2)
        self.assertTrue(all((stage/row['path']).is_file() for row in index))
        self.assertEqual(lib.source_state_sha(fixture.source), before)
        self.assertFalse((fixture.root/'assets').exists())


if __name__ == '__main__':
    unittest.main()
