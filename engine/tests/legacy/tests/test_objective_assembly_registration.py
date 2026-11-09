"""A source assembly is a layout object, never an invented purchase/manufacturing row."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from bom import aggregate
from layout import validate_layout
from test_layout import layout_fixture

SCRIPT=Path(__file__).resolve().parents[1]/'qa/register_objective_assembly.py'
spec=importlib.util.spec_from_file_location('register_objective_assembly',SCRIPT)
register=importlib.util.module_from_spec(spec);spec.loader.exec_module(register)


class ObjectiveAssemblyRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        step=self.root/'source.step';step.write_bytes(b'ISO-10303-21; TEST COMPLETE ASSEMBLY; END-ISO-10303-21;')
        svg=self.root/'static/topviews/test.svg';svg.parent.mkdir(parents=True);svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 40"><path d="M0 0H60V20H40V40H0Z"/></svg>')
        self.manifest={'source':{'documentId':register.DOCUMENT_ID,'elementId':'b7046cbf29467588274024f0',
                                'url':f'https://cad.onshape.com/documents/{register.DOCUMENT_ID}/w/f9aff275881f6d78afe640a9/e/b7046cbf29467588274024f0',
                                'stepPath':str(step),'stepSha256':hashlib.sha256(step.read_bytes()).hexdigest(),'finalAssemblyConfirmed':True},
                       'topViewSha256':hashlib.sha256(svg.read_bytes()).hexdigest(),
                       'installation':{'mountingVerified':False,'supportVerified':False},
                       'layout':{'topViewPath':'topviews/test.svg','widthMm':60,'heightMm':40,'anchorXMm':30,'anchorYMm':20,
                                 'collisionBoundsMm':{'xMin':-30,'xMax':30,'yMin':-20,'yMax':20},
                                 'collisionPolygonsMm':[[{'xMm':x,'yMm':y} for x,y in [(-30,-20),(30,-20),(30,0),(10,0),(10,20),(-30,20)]]],
                                 'mountingHoleOffsetsMm':[{'xMm':0,'yMm':0}],'opticalAxisHeightMm':63.5,'focalLengthMm':25}}
    def tearDown(self):self.temp.cleanup()

    def test_unknown_mount_and_optics_are_explicit_without_guessing_purchase_rows(self):
        kit=register.build_kit(self.manifest,self.root)
        self.assertEqual(kit['components'],[]);self.assertEqual(kit['opticalSlots'],[])
        self.assertTrue(kit['layout']['placementAllowed'])
        self.assertEqual(kit['layout']['mountingHoleOffsetsMm'],[])
        self.assertFalse(kit['layout']['opticalDatumVerified']);self.assertEqual(kit['layout']['opticalType'],'unsupported')
        self.assertNotIn('opticalAxisHeightMm',kit['layout']);self.assertNotIn('focalLengthMm',kit['layout'])
        self.assertIn('保守',kit['layout']['note']);self.assertIn('未登记',kit['notes'])
        catalog=register.update_catalog(layout_fixture(),kit)
        payload={'layout':{'board':{'widthMm':350,'heightMm':225},'instances':[{'id':'objective','kitId':kit['id'],'xMm':100,'yMm':100,'rotationDeg':0}]}}
        preview=aggregate(catalog,payload)
        self.assertEqual(preview['lubang'],[]);self.assertEqual(preview['standard'],[])
        self.assertEqual(len(preview['manufacturing']),1);self.assertTrue(preview['manufacturing'][0]['generatedBoard'])
        self.assertTrue(any('物镜' in text and '不计入采购' in text for text in preview['warnings']))
        self.assertIn('mounting_unconfirmed',{issue['code'] for issue in preview['layoutValidation']['issues']})

    def test_real_manifest_retains_cad_faces_but_does_not_claim_known_coating_or_ports(self):
        root=Path(__file__).resolve().parents[1];manifest=json.loads((root/'data_evidence/optical-frame-2026-10-04/objective-final/manifest.json').read_text())
        if not Path(manifest['source']['stepPath']).is_file():self.skipTest('actual CAD evidence not installed in this environment')
        kit=register.build_kit(manifest,root);assembly=kit['layout']['opticalAssembly']
        self.assertEqual(kit['layout']['opticalType'],'empty');self.assertEqual(len(assembly['nodes']),3)
        self.assertAlmostEqual(kit['layout']['opticalAxisHeightMm'],113.06370626)
        for element in assembly['internalElements']:
            self.assertIsNone(element['opticalDefaults']['coatingFaceIndex'])
            self.assertEqual(element['opticalDefaults'][element['type']]['samples'],[])
            self.assertEqual(len(element['candidateFaces']),2)
        self.assertFalse(assembly['nodes'][-1]['opticalPortConfirmed']);self.assertIsNone(assembly['nodes'][-1]['focalLengthMm'])
        self.assertTrue(all(slot['defaultExisting'] for slot in kit['opticalSlots']))
        self.assertNotIn('Actual ',kit['layout']['note']);self.assertNotIn("['",kit['layout']['note'])
        self.assertIn('5 个安装孔',kit['layout']['note'])
        catalog=register.update_catalog(layout_fixture(),kit)
        preview=aggregate(catalog,{'items':[{'kitId':kit['id'],'quantity':2}]})
        self.assertEqual(preview['totals']['componentQuantity'],0)
        self.assertEqual(preview['lubang'],[]);self.assertEqual(preview['manufacturing'],[])
        face=manifest['internalOpticsGeometry']['bottomMirror']['planes'][0]['centerLayoutMm']
        point=assembly['internalElements'][0]['candidateFaces'][0]['sidePointMm']
        self.assertAlmostEqual(point['yMm'],face[2]-assembly['sideView']['zMin'])

    def test_source_document_and_hash_are_bound_to_the_independent_final_assembly(self):
        for field,value in [('documentId','3a3c1d8089df865b8b4e822a'),('finalAssemblyConfirmed',False),
                            ('stepSha256','0'*64),('elementId','000000000000000000000000')]:
            manifest=copy.deepcopy(self.manifest);manifest['source'][field]=value
            with self.assertRaises(ValueError):register.build_kit(manifest,self.root)
        manifest=copy.deepcopy(self.manifest);manifest['topViewSha256']='0'*64
        with self.assertRaises(ValueError):register.build_kit(manifest,self.root)

    def test_known_mounting_requires_real_coordinates_and_support_evidence(self):
        m=copy.deepcopy(self.manifest);m['installation']['mountingVerified']=True;m['layout']['mountingHoleOffsetsMm']=[]
        with self.assertRaises(ValueError):register.build_kit(m,self.root)
        m=copy.deepcopy(self.manifest);m['installation']['supportVerified']=True
        with self.assertRaises(ValueError):register.build_kit(m,self.root)
        m['layout']['baseBoundsMm']={'xMin':-15,'xMax':15,'yMin':-10,'yMax':10};m['installation']['mountingVerified']=True
        kit=register.build_kit(m,self.root)
        self.assertEqual(kit['layout']['mountingHoleOffsetsMm'],[{'xMm':0,'yMm':0}])
        self.assertEqual(kit['layout']['baseBoundsMm'],m['layout']['baseBoundsMm'])

    def test_update_is_idempotent_and_does_not_change_existing_kits_or_components(self):
        original=layout_fixture();kit=register.build_kit(self.manifest,self.root)
        one=register.update_catalog(original,kit);two=register.update_catalog(one,kit)
        self.assertEqual(one,two)
        self.assertEqual(one['components'],original['components'])
        self.assertEqual(one['kits'][:-1],original['kits'])
        self.assertEqual([k['id'] for k in one['kits']].count(register.KIT_ID),1)
        self.assertEqual(len(original['kits'])+1,len(one['kits']))

    def test_reference_only_bom_exception_does_not_accept_other_missing_or_contradictory_boms(self):
        from bom import APIError, validate_catalog
        kit=register.build_kit(self.manifest,self.root);catalog=register.update_catalog(layout_fixture(),kit)
        preview=aggregate(catalog,{'items':[{'kitId':kit['id'],'quantity':3}]})
        self.assertEqual(preview['totals']['componentQuantity'],0)
        self.assertEqual(preview['items'][0]['quantity'],3)
        self.assertEqual(preview['manufacturing'],[])
        catalog['kits'][-1].pop('bomPolicy')
        with self.assertRaises(APIError) as error:aggregate(catalog,{'items':[{'kitId':kit['id'],'quantity':1}]})
        self.assertEqual(error.exception.code,'kit_bom_missing')
        catalog['kits'][-1]['bomPolicy']='reference-only';catalog['kits'][-1]['components']=copy.deepcopy(catalog['kits'][0]['components'])
        with self.assertRaises(APIError):validate_catalog(catalog)


if __name__=='__main__':unittest.main()
