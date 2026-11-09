"""Nominal converter heights cannot disable real height checks or alter BOMs."""
import copy
import math
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bom import APIError
from elevation import axis_validation, external_axis_heights, validate_universal_posts, apply_post_validation

def converter(values=(135, 62.5)):
    return {'opticalAxisHeightMm': values[0], 'opticalAssembly': {'verified': True,
        'externalAxisHeightsMm': list(values),
        'nodes': [{'faces': [{'centerMm': [0, 0, h]} for h in values]}]}}

def scene():
    return ({'instances': [{'id': 'laser', 'kitId': 'laser'}, {'id': 'low', 'kitId': 'low'}, {'id': 'c', 'kitId': 'converter'}]},
            {'laser': {'opticalAxisHeightMm': 135}, 'low': {'opticalAxisHeightMm': 62.5}, 'converter': converter()})

def analyze(layout, metadata):
    value, issues = axis_validation(layout, metadata, [])
    return {**value, 'issues': issues, 'valid': not issues}

class ExternalHeightTests(unittest.TestCase):
    def test_declared_faces_are_required_and_strict(self):
        for values in (None, '135,62.5', [], [135], list(range(17)), [135,135], [135,135.000001], [True,62.5], [math.inf,62.5], [math.nan,62.5], [-1,62.5], [10001,62.5], [135,63.5], [135,{}]):
            with self.subTest(values=values):
                g=converter();g['opticalAssembly']['externalAxisHeightsMm']=values
                with self.assertRaises(APIError) as error:external_axis_heights(g)
                self.assertEqual(error.exception.code,'external_axis_heights_invalid')
        for change in ({'verified':False},{'verified':1},{'nodes':[]},{'nodes':[{'faces':[{'centerMm':[0,0,'135']},{'centerMm':[0,0,62.5]}]}]}):
            g=converter();g['opticalAssembly'].update(change)
            with self.assertRaises(APIError):external_axis_heights(g)
        g=converter();g['opticalAssembly']['nodes'][0]['faces'][0]['centerMm']={'x':0,'y':0,'z':135.000005}
        self.assertEqual(external_axis_heights(g),[135,62.5])
        g['opticalAssembly']['nodes'][0]['faces'][0]['centerMm']['z']=135.00002
        with self.assertRaises(APIError):external_axis_heights(g)
        self.assertIsNone(external_axis_heights({'opticalAssembly':{'verified':True}}))
    def test_catalog_rejects_invalid_declaration_even_without_post_series(self):
        g=converter();g['opticalAssembly']['verified']=False
        with self.assertRaises(APIError):validate_universal_posts({'components':[],'kits':[{'id':'c','layout':g}]})
    def test_true_135_to_62p5_connection_and_63p5_rejection(self):
        l,m=scene();before=copy.deepcopy((l,m));r=analyze(l,m)
        self.assertTrue(r['valid']);self.assertEqual(r['connectedAxisHeightsMm'],[62.5,135]);self.assertEqual((l,m),before)
        m['low']['opticalAxisHeightMm']=63.5
        self.assertEqual(analyze(l,m)['issues'][0]['instanceIds'],['low'])
    def test_multiport_converter_without_single_nominal_height_is_resolved(self):
        l,m=scene();m['converter']['opticalAxisHeightMm']=None
        r=analyze(l,m);self.assertTrue(r['valid'])
        row=r['axisHeights'][2]
        self.assertTrue(row['heightResolved'])
        self.assertIsNone(row['effectiveAxisHeightMm'])
        self.assertEqual(row['effectiveExternalAxisHeightsMm'],[135,62.5])
        del m['converter']['opticalAssembly']['externalAxisHeightsMm']
        self.assertEqual(analyze(l,m)['issues'][0]['instanceIds'],['low'])
    def test_disconnected_converter_never_grants_union_exception_but_chain_connects(self):
        l,m=scene();m['low']['opticalAxisHeightMm']=50;m['other']=converter((100,50));l['instances'].append({'id':'d','kitId':'other'})
        self.assertEqual(analyze(l,m)['issues'][0]['instanceIds'],['low'])
        m['bridge']=converter((62.5,100));l['instances'].append({'id':'b','kitId':'bridge'})
        self.assertTrue(analyze(l,m)['valid'])
    def test_world_elevation_includes_child_thickness_adapter_and_instance_once(self):
        l,m=scene();l['board']={'thicknessMm':30};l['subBoards']=[{'id':'sub','board':{'thicknessMm':10},'elevationMm':5}]
        l['instances'][2].update(boardId='sub',elevationMm=2.5,laserAdapter={'enabled':True,'thicknessMm':7.5})
        m['converter']=converter((110,37.5))
        r=analyze(l,m);self.assertTrue(r['valid']);self.assertEqual(r['axisHeights'][2]['effectiveExternalAxisHeightsMm'],[135,62.5])
        l['subBoards'][0]['elevationMm']=6
        self.assertEqual(analyze(l,m)['issues'][0]['instanceIds'],['low'])
    def test_post_adjustments_shift_both_endpoints_and_unresolved_plan_removes_group(self):
        l,m=scene();m['converter']=converter((122.5,50));v=analyze(l,m)
        plan={'supportCounts':{},'heightAdjustments':{'c':12.5},'issues':[]}
        apply_post_validation(v,plan);self.assertTrue(v['valid']);self.assertEqual(v['axisHeights'][2]['effectiveExternalAxisHeightsMm'],[135,62.5])
        v=analyze(l,m);plan['issues']=[{'code':'universal_post_unavailable','instanceIds':['c'],'message':'test unavailable'}]
        apply_post_validation(v,plan);self.assertIsNone(v['axisHeights'][2]['effectiveExternalAxisHeightsMm']);self.assertNotIn('connectedAxisHeightsMm',v);self.assertFalse(v['valid'])
    def test_instance_cannot_forge_converter_declaration(self):
        l,m=scene();m['converter']['opticalAssembly'].pop('externalAxisHeightsMm');l['instances'][2]['externalAxisHeightsMm']=[135,62.5]
        self.assertEqual(analyze(l,m)['issues'][0]['instanceIds'],['low'])
if __name__=='__main__':unittest.main()
