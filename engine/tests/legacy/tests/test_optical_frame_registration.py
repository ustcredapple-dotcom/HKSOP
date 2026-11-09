"""Registration binds real source hashes and never fabricates source manufacturing assets."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from test_registered_boards import record
from test_layout import layout_fixture

SCRIPT=Path(__file__).resolve().parents[1]/'qa/register_optical_frame_boards.py'
spec=importlib.util.spec_from_file_location('register_optical_frame_boards',SCRIPT)
register=importlib.util.module_from_spec(spec);spec.loader.exec_module(register)

class OpticalFrameRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.step=self.root/'source.step';self.step.write_bytes(b'CAD full restored holes test')
        self.svg=self.root/'source.svg';self.svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.extraction=record();self.extraction.update(id='optical-frame-for1',registrationReady=True,sourceStep='source.step',
            sourceSha256=hashlib.sha256(self.step.read_bytes()).hexdigest(),sourceEvidence=[],warnings=[],audit={'validShape':True,'unclassifiedHoleIds':[]})
    def tearDown(self):self.temp.cleanup()
    def build(self,value=None):return register.build_record(value or self.extraction,self.svg,{'sourceUrl':'https://cad.onshape.com/documents/known'},self.root)
    def test_exact_shape_holes_and_source_assets_are_preserved(self):
        row,copies=self.build();self.assertEqual(row['outlineMm'],self.extraction['outlineMm']);self.assertEqual(row['cutoutsMm'],self.extraction['cutoutsMm'])
        self.assertEqual(row['holesMm'],self.extraction['holesMm']);self.assertEqual(row['sourceMaterial'],'7075 铝合金')
        self.assertIsNone(row['drawingPath']);self.assertEqual(copies[1][0],self.step.resolve())
        self.assertNotIn('generatedBoard',row);self.assertEqual(row['revision'],'2026-10-04.1')
        mot=copy.deepcopy(self.extraction);mot['id']='optical-frame-middle';self.assertEqual(self.build(mot)[0]['sourceMaterial'],'待确认')
    def test_unknown_geometry_abandoned_parts_and_bad_source_are_rejected(self):
        for changes in [{'id':'objective-old'},{'registrationReady':False},{'warnings':['unclassified']},{'sourceSha256':'0'*64},{'sourceStep':'../outside.step'},
                        {'audit':{'validShape':True,'unclassifiedHoleIds':['hole']}}]:
            value={**self.extraction,**changes}
            with self.assertRaises(ValueError):self.build(value)
    def test_incremental_registration_preserves_other_catalog_data(self):
        original=layout_fixture();original['registeredBoards']=[record()]
        row,_=self.build();result=register.update_catalog(original,[row]);again=register.update_catalog(result,[row])
        self.assertEqual(result,again);self.assertEqual(result['registeredBoards'][0],original['registeredBoards'][0])
        for field in ('kits','components','version','categories'):self.assertEqual(result[field],original[field])

if __name__=='__main__':unittest.main()
