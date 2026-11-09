"""Independent marking assets, current cart metadata, and truthful production lists."""
import copy
import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from openpyxl import load_workbook

from bom import APIError, aggregate, validate_catalog
from cart import combine, current_marking_view, export_preview, row_identity
from exports import export_result
from test_backend import fixture
from test_dxf_assets import state_for


class LaserMarkingExportTests(unittest.TestCase):
    def setUp(self):
        self.catalog = fixture()
        self.dxf = b'0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n'
        self.pdf = b'%PDF-setup-fixture'
        self.marking = {'status': 'required', 'reason': '零件身份识别', 'notes': '按定位图核对表面', 'files': [
            {'face': '顶面', 'text': 'P-01', 'dxfPath': 'drawings/marks/top.dxf', 'sha256': hashlib.sha256(self.dxf).hexdigest(),
             'setupPdfPath': 'drawings/marks/top.pdf', 'setupPdfSha256': hashlib.sha256(self.pdf).hexdigest()}]}
        self.catalog['components'][0]['laserMarking'] = copy.deepcopy(self.marking)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'drawings/marks').mkdir(parents=True)
        for name in ('plate.step', 'plate.pdf'):
            (self.root/name).write_bytes(name.encode())
        (self.root/'drawings/marks/top.dxf').write_bytes(self.dxf)
        (self.root/'drawings/marks/top.pdf').write_bytes(self.pdf)

    def tearDown(self):
        self.temp.cleanup()

    def preview(self, catalog=None):
        return aggregate(catalog or self.catalog, {'items': [{'kitId': 'alpha', 'quantity': 3}]})

    def test_validation_rejects_traversal_bad_hash_and_unpaired_pdf(self):
        for mutation in ({'dxfPath': '../outside.dxf'}, {'sha256': 'bad'}, {'setupPdfSha256': None}, {'setupPdfPath': 'drawings/marks/top.dxf'}):
            catalog = copy.deepcopy(self.catalog)
            catalog['components'][0]['laserMarking']['files'][0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(APIError):
                validate_catalog(catalog)
        for status in ('unknown', None, False):
            catalog = copy.deepcopy(self.catalog)
            catalog['components'][0]['laserMarking']['status'] = status
            with self.subTest(status=status), self.assertRaises(APIError):
                validate_catalog(catalog)

    def test_bundle_has_independent_face_dxf_pdf_selected_quantities_and_checksums(self):
        preview = self.preview()
        preview['manufacturing'][0]['quantity'] = 7
        content, _, _ = export_result(preview, 'bundle', self.root)
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            self.assertIsNone(z.testzip())
            dxf_name = '激光打标/测试plate/顶面.dxf'
            pdf_name = '激光打标/测试plate/顶面_定位说明.pdf'
            self.assertEqual(z.read(dxf_name), self.dxf)
            self.assertEqual(z.read(pdf_name), self.pdf)
            config = json.loads(z.read('套件配置.json'))
            self.assertEqual(config['laserMarking'][0]['quantity'], 7)
            self.assertEqual(config['fileChecksums'][dxf_name], self.marking['files'][0]['sha256'])
            sheet = load_workbook(io.BytesIO(z.read('生产清单.xlsx')))['生产清单']
            self.assertEqual((sheet['I6'].value, sheet['J6'].value), ('需要打标', 7))
            self.assertIn(dxf_name, sheet['L6'].value)
            csv_rows = list(csv.reader(io.StringIO(z.read('生产清单.csv').decode('utf-8-sig'))))
            self.assertEqual(csv_rows[1][9], '7')
            self.assertIn(dxf_name, csv_rows[1][11])

    def test_old_cart_resolves_current_marking_and_does_not_mutate_state_or_identity(self):
        old = copy.deepcopy(self.catalog)
        old['components'][0].pop('laserMarking')
        state = state_for(self.preview(old))
        before = copy.deepcopy(state)
        cid = combine(state)[0]['manufacturing'][0]['componentId']
        state['choices'][cid]['quantity'] = 11
        before = copy.deepcopy(state)
        preview = export_preview(state, self.catalog)
        row = preview['manufacturing'][0]
        self.assertEqual(row['laserMarking'], self.marking)
        self.assertEqual(row['quantity'], 11)
        self.assertEqual(state, before)
        historical = state['sources'][0]['preview']['manufacturing'][0]
        self.assertEqual(row_identity(historical, 's1'), row_identity({**historical, 'laserMarking': self.marking}, 's1'))
        # The derived webpage view also resolves current metadata without writing a snapshot.
        display = copy.deepcopy(preview)
        display['manufacturing'][0].pop('laserMarking')
        current_marking_view(display, self.catalog)
        self.assertEqual(display['manufacturing'][0]['laserMarking'], self.marking)
        self.assertEqual(state, before)
        changed = copy.deepcopy(self.catalog)
        changed['components'][0]['stepPath'] = 'new.step'
        with self.assertRaises(APIError) as caught:
            export_preview(state, changed)
        self.assertEqual(caught.exception.code, 'cart_source_changed')
        current_marking_view(display, changed)
        self.assertEqual(display['manufacturing'][0]['laserMarking']['status'], 'review')

    def test_missing_required_and_unknown_are_explicit_without_blocking_bundle(self):
        for metadata in ({'status': 'required', 'files': []}, {'status': 'review', 'reason': '待核实', 'files': []}, {'status': 'none', 'files': []}):
            catalog = copy.deepcopy(self.catalog)
            catalog['components'][0]['laserMarking'] = metadata
            content, _, _ = export_result(self.preview(catalog), 'bundle', self.root)
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                sheet = load_workbook(io.BytesIO(z.read('生产清单.xlsx')))['生产清单']
                expected = {'required': ('需要打标；DXF待补', 3), 'review': ('待核实是否打标', '待核实'), 'none': ('无需打标', 0)}[metadata['status']]
                self.assertEqual((sheet['I6'].value, sheet['J6'].value), expected)
                self.assertFalse(any(name.endswith('.dxf') for name in z.namelist()))
        (self.root/'drawings/marks/top.dxf').unlink()
        content, _, _ = export_result(self.preview(), 'bundle', self.root)
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            manifest = json.loads(z.read('激光打标/打标文件清单.json'))
            self.assertTrue(manifest[0]['missing'])
            sheet = load_workbook(io.BytesIO(z.read('生产清单.xlsx')))['生产清单']
            self.assertIn('资料待补', sheet['I6'].value)
            self.assertIn('dxfPath文件待补', sheet['M6'].value)

    def test_corrupt_or_symlinked_marking_rejected_and_deselected_assets_not_read(self):
        (self.root/'drawings/marks/top.dxf').write_bytes(b'changed')
        with self.assertRaises(APIError) as caught:
            export_result(self.preview(), 'bundle', self.root)
        self.assertEqual(caught.exception.code, 'asset_changed')
        (self.root/'drawings/marks/top.dxf').unlink()
        (self.root/'drawings/marks/top.dxf').symlink_to(self.root/'plate.step')
        with self.assertRaises(APIError) as caught:
            export_result(self.preview(), 'bundle', self.root)
        self.assertEqual(caught.exception.code, 'asset_forbidden')
        state = state_for(self.preview())
        for choice in state['choices'].values():
            choice['selected'] = False
        # Keep the external optic selected, so no manufacturing file is touched.
        combined_id = combine(state)[0]['lubang'][0]['componentId']
        state['choices'][combined_id]['selected'] = True
        selected = export_preview(state, self.catalog)
        self.assertEqual(selected['manufacturing'], [])
        export_result(selected, 'bundle', self.root)



class RegisteredBoardMarkingTests(unittest.TestCase):
    def setUp(self):
        from test_layout import layout_fixture
        from test_registered_boards import record, reference
        from test_stacked_layout import board
        self.catalog = layout_fixture()
        self.catalog['registeredBoards'] = [record()]
        self.board_record = self.catalog['registeredBoards'][0]
        self.board_record.update(stepPath='step/board.step', drawingPath='drawings/board.pdf')
        self.board_ref = reference()
        self.layout = {'baseMode':'table', 'board':board(300,225), 'subBoards':[
            {'id':'b1','name':'实体板','board':self.board_ref,'xMm':0,'yMm':0,'rotationDeg':0}], 'instances':[]}

    def preview(self, catalog=None):
        return aggregate(catalog or self.catalog, {'layout':self.layout})

    def test_current_registered_policy_keeps_single_board_quantity(self):
        self.board_record['laserMarking'] = {'status':'required','reason':'原凹字按激光打标处理','files':[]}
        preview = self.preview()
        self.assertEqual(len(preview['manufacturing']), 1)
        self.assertEqual(preview['manufacturing'][0]['quantity'], 1)
        self.assertEqual(preview['totals']['boards'], 1)
        self.assertEqual(preview['manufacturing'][0]['laserMarking']['status'], 'required')
        workbook,_,_ = export_result(preview, 'manufacturing', tempfile.gettempdir())
        sheet = load_workbook(io.BytesIO(workbook))['生产清单']
        self.assertEqual((sheet['I6'].value, sheet['J6'].value), ('需要打标；DXF待补', 1))

    def test_old_cart_reads_current_board_policy_without_snapshot_or_quantity_change(self):
        state = state_for(self.preview())
        cid = combine(state)[0]['manufacturing'][0]['componentId']
        state['choices'][cid]['quantity'] = 4
        original = copy.deepcopy(state)
        self.board_record['laserMarking'] = {'status':'required','files':[]}
        exported = export_preview(state, self.catalog)
        self.assertEqual(exported['manufacturing'][0]['quantity'], 4)
        self.assertEqual(exported['manufacturing'][0]['laserMarking']['status'], 'required')
        display,_ = combine(state)
        current_marking_view(display, self.catalog)
        self.assertEqual(display['manufacturing'][0]['laserMarking']['status'], 'required')
        self.assertEqual(state, original)
        changed = copy.deepcopy(self.catalog)
        changed['registeredBoards'][0]['stepPath'] = 'step/new-board.step'
        current_marking_view(display, changed)
        self.assertEqual(display['manufacturing'][0]['laserMarking']['status'], 'review')
        with self.assertRaises(APIError) as caught:
            export_preview(state, changed)
        self.assertEqual(caught.exception.code, 'cart_source_changed')

    def test_same_custom_policy_reuses_metadata_without_creating_second_part(self):
        custom = self.catalog['components'][0]
        custom.update(stepPath=self.board_record['stepPath'], drawingPath=self.board_record['drawingPath'],
                      laserMarking={'status':'required','files':[]})
        preview = self.preview()
        self.assertEqual(len(preview['manufacturing']), 1)
        self.assertEqual(preview['manufacturing'][0]['quantity'], 1)
        self.assertEqual(preview['totals']['componentTypes'], 1)
        self.assertEqual(preview['manufacturing'][0]['laserMarking']['status'], 'required')
        custom['drawingPath'] = 'drawings/different-revision.pdf'
        self.assertEqual(self.preview()['manufacturing'][0]['laserMarking']['status'], 'review')

    def test_parametric_board_keeps_review_and_policy_is_never_inferred_from_shape(self):
        from test_stacked_layout import board
        self.board_record['laserMarking'] = {'status':'required','files':[]}
        preview = aggregate(self.catalog, {'layout':{'board':board(300,225),'instances':[]}})
        self.assertTrue(preview['manufacturing'][0]['generatedBoard'])
        self.assertEqual(preview['manufacturing'][0]['laserMarking']['status'], 'review')
        state = state_for(preview)
        self.assertEqual(export_preview(state,self.catalog)['manufacturing'][0]['laserMarking']['status'], 'review')


if __name__ == '__main__':
    unittest.main()
