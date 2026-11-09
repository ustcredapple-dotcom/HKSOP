"""Compatibility regression: fixed horizontal posts remain in the flat BOM."""
import copy
from pathlib import Path
import sys
import unittest
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bom import APIError, aggregate, load_catalog, validate_catalog
from elevation import universal_post_plan
FIXED = 'custom-post-metric-12p5mm-m1'
NEXT = 'custom-post-metric-25mm-m1'
class FixedPostTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(ROOT/'catalog.json')
        self.kit = copy.deepcopy(next(k for k in self.catalog['kits'] if k['id']=='pbs-fixed'))
        self.kit['id'] = 'fixed-post-regression'
        self.kit['components'] = [{'componentId': FIXED, 'quantity': 2}]
        self.kit['opticalSlots'] = []
        self.kit['layout']['fixedUniversalPostComponentIds'] = [FIXED]
        self.catalog['kits'].append(self.kit)
        self.layout = {'instances':[{'id':'p','kitId':self.kit['id'],'elevationMm':12.5}]}
    def test_catalog_membership_type_uniqueness_and_absent_series(self):
        for raw in (None, FIXED, [FIXED,FIXED], ['missing'], ['mt-am1s5'], [3], [[]], [NEXT]):
            with self.subTest(raw=raw):
                bad=copy.deepcopy(self.catalog);bad['kits'][-1]['layout']['fixedUniversalPostComponentIds']=raw
                with self.assertRaises(APIError) as ctx: validate_catalog(bad)
                self.assertEqual(ctx.exception.code,'catalog_invalid')
        bad=copy.deepcopy(self.catalog);bad.pop('universalPostSeries')
        with self.assertRaises(APIError): validate_catalog(bad)
        validate_catalog(self.catalog)
    def test_fixed_posts_survive_bom_and_root_elevation(self):
        before=copy.deepcopy(self.catalog);plan=universal_post_plan(self.catalog,self.layout)
        self.assertEqual(plan['replacements'],[]);self.assertEqual(plan['issues'],[])
        self.assertEqual(plan['supportCounts'],{});self.assertEqual(plan['managedInstanceIds'],set())
        result=aggregate(self.catalog,{'items':[{'kitId':self.kit['id'],'quantity':3}]})
        row=next(x for x in result['manufacturing'] if x['componentId']==FIXED)
        self.assertEqual(row['quantity'],6);self.assertEqual(self.catalog,before)
    def test_fixed_selection_is_rejected_on_root_and_subboard_even_identity(self):
        for child in (False,True):
            for target in (FIXED,NEXT):
                layout=copy.deepcopy(self.layout);i=layout['instances'][0]
                if child:i['boardId']='sub'
                i['universalPostSelection']={FIXED:target}
                with self.assertRaises(APIError) as ctx:universal_post_plan(self.catalog,layout)
                self.assertEqual(ctx.exception.code,'invalid_post_selection')
    def test_unmarked_and_empty_declaration_keep_original_behavior(self):
        for declaration in (None,[]):
            catalog=copy.deepcopy(self.catalog)
            if declaration is None:catalog['kits'][-1]['layout'].pop('fixedUniversalPostComponentIds')
            else:catalog['kits'][-1]['layout']['fixedUniversalPostComponentIds']=declaration
            plan=universal_post_plan(catalog,self.layout)
            self.assertEqual([(r['originalComponentId'],r['replacementComponentId'],r['quantity']) for r in plan['replacements']],[(FIXED,NEXT,2)])
    def test_mixed_kit_only_replaces_the_unfixed_id(self):
        other='custom-post-metric-37p5mm-m1';self.kit['components'].append({'componentId':other,'quantity':1})
        plan=universal_post_plan(self.catalog,self.layout)
        self.assertEqual(len(plan['replacements']),1)
        self.assertEqual(plan['replacements'][0]['originalComponentId'],other)
        self.assertEqual(plan['replacements'][0]['replacementComponentId'],'custom-post-metric-50mm-m1')
        self.assertEqual(plan['supportCounts'],{'p':1})
if __name__=='__main__':unittest.main()
