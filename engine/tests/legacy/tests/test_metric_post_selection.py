"""Metric post selection is explicit; old assets, instances and cart rows stay distinct."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from openpyxl import load_workbook
from bom import APIError, aggregate, validate_catalog
from cart import CartStore
from elevation import automatic_axis_target, universal_post_plan, validate_universal_posts
from exports import export_result, workbook_bytes
from layout import layout_json
from shared_kits import Identity, SharedKitStore, prepare_project
from test_universal_post_replacement import catalog_fixture
from test_shared_kits import project


def fixture():
    catalog = catalog_fixture()
    original = next(c for c in catalog['components'] if c['id'] == 'custom-01')
    for n in range(1,13):
        cid = f'test-metric-{n}'
        catalog['components'].append({**copy.deepcopy(original),'id':cid,'name':f'公制柱 {n*12.5:g} mm',
          'model':f'TEST-METRIC-{n}','stepPath':f'metric-r1/{cid}.step','drawingPath':f'metric-r1/{cid}.pdf','postTopThread':'M6' if n==1 else 'M4'})
        catalog['universalPostSeries']['posts'].append({'componentId':cid,'heightMm':n*12.5,'seriesId':'metric-12p5-r1'})
    k = copy.deepcopy(next(k for k in catalog['kits'] if k['id']=='pbs-fixed'))
    k.update(id='test-optic',name='Test optic',components=[{'componentId':'custom-01','quantity':2}],opticalSlots=[],pendingRequirements=[])
    catalog['kits'].append(k)
    return validate_catalog(catalog)


def layout(selection=None,elevation=0):
    instance={'id':'i','kitId':'test-optic','xMm':112.5,'yMm':112.5,'rotationDeg':0,'elevationMm':elevation}
    if selection is not None:instance['universalPostSelection']=selection
    return {'baseMode':'table','board':{'widthMm':600,'heightMm':400,'pitchMm':25,'edgeOffsetMm':12.5,'thicknessMm':12.7},'instances':[instance]}


class MetricPostSelectionTests(unittest.TestCase):
    def setUp(self):self.catalog=fixture()

    def test_automatic_target_is_separate_from_achieved_height(self):
        for value,expected in [(None,None),(0,0),(62.5,62.5),(63.1,75),(135,137.5),(150,150),(152.4,162.5)]:
            self.assertEqual(automatic_axis_target(value),expected)
        result=aggregate(self.catalog,{'layout':layout()})
        self.assertEqual(result['layoutValidation']['axisHeightReferenceMm'],63.5)
        self.assertEqual(result['layoutValidation']['autoAxisHeightTargetMm'],75)
        self.assertEqual(result['layout']['instances'][0]['elevationMm'],0)

    def test_explicit_metric_base_changes_real_height_and_bom_not_kit(self):
        source=layout({'custom-01':'test-metric-2'});before=copy.deepcopy(self.catalog)
        result=aggregate(self.catalog,{'layout':source});axis=result['layoutValidation']['axisHeights'][0]
        self.assertEqual(axis['postHeightDeltaMm'],-.4);self.assertEqual(axis['effectiveAxisHeightMm'],63.1)
        self.assertEqual([(r['componentId'],r['quantity'])for r in result['manufacturing']],[('test-metric-2',2)])
        self.assertEqual(result['layout']['instances'][0]['universalPostSelection'],{'custom-01':'test-metric-2'})
        self.assertEqual(self.catalog,before)
        wb=load_workbook(io.BytesIO(workbook_bytes(result,'manufacturing','2026-10-05T00:00:00Z')))
        self.assertEqual(wb['光轴高度']['M5'].value,'基础柱高差 / mm')
        self.assertEqual(wb['光轴高度']['M6'].value,-.4)

    def test_increment_uses_selected_series_and_keeps_old_manual_selection(self):
        result=aggregate(self.catalog,{'layout':layout({'custom-01':'test-metric-2'},12.5)})
        self.assertEqual(result['universalPostReplacements'][0]['replacementComponentId'],'test-metric-3')
        self.assertEqual(result['layoutValidation']['axisHeights'][0]['effectiveAxisHeightMm'],75.6)
        old=aggregate(self.catalog,{'layout':layout(None,25.4)})
        self.assertEqual(old['universalPostReplacements'][0]['replacementComponentId'],'custom-post-2inch')
        self.assertEqual(old['layoutValidation']['axisHeights'][0]['effectiveAxisHeightMm'],88.9)
        unavailable=universal_post_plan(self.catalog,layout(None,12.1))
        self.assertEqual(unavailable['issues'][0]['code'],'universal_post_unavailable')
        unavailable=universal_post_plan(self.catalog,layout({'custom-01':'test-metric-2'},13.1))
        self.assertEqual(unavailable['issues'][0]['code'],'universal_post_unavailable')

    def test_child_retains_selected_post_but_extra_elevation_uses_op1(self):
        source=layout({'custom-01':'test-metric-2'},10)
        source['subBoards']=[{'id':'small','name':'Small','board':{**source['board'],'widthMm':250,'heightMm':250},'xMm':0,'yMm':0,'rotationDeg':0}]
        source['instances'][0]['boardId']='small'
        result=aggregate(self.catalog,{'layout':source})
        self.assertEqual(result['universalPostReplacements'][0]['replacementComponentId'],'test-metric-2')
        self.assertEqual(result['layoutValidation']['axisHeights'][0]['effectiveAxisHeightMm'],85.8)
        self.assertTrue(any(r['model']=='OP1-10B6' for r in result['lubang']))
        self.assertEqual(result['universalPostReplacements'][0]['elevationMm'],0)

    def test_top_thread_change_remains_marked_for_connection_review(self):
        result=aggregate(self.catalog,{'layout':layout({'custom-01':'test-metric-1'})})
        record=result['universalPostReplacements'][0]
        self.assertEqual((record['originalTopThread'],record['replacementTopThread']),('M4','M6'))
        reviews=[item for group in result['reviewGroups'] for item in group['items'] if item['code']=='universal_post_connection']
        self.assertEqual(len(reviews),1);self.assertIn('螺纹',reviews[0]['summary']);self.assertIn('核对',reviews[0]['summary'])
        self.assertEqual(result['layoutValidation']['axisHeights'][0]['effectiveAxisHeightMm'],50.6)

    def test_invalid_and_tilting_selections_are_rejected(self):
        for choice in [{'custom-01':'not-registered'},{'other-post':'test-metric-2'},None,[],{'__proto__':'x'}]:
            source=layout();source['instances'][0]['universalPostSelection']=choice
            with self.subTest(choice=choice),self.assertRaises(APIError):aggregate(self.catalog,{'layout':source})
        kit=next(k for k in self.catalog['kits']if k['id']=='test-optic')
        kit['components'].append({'componentId':'custom-03','quantity':1})
        with self.assertRaises(APIError):aggregate(self.catalog,{'layout':layout({'custom-01':'test-metric-2'})})
        self.assertEqual(len(validate_universal_posts(self.catalog)),24)
        duplicate=copy.deepcopy(self.catalog);duplicate['universalPostSeries']['posts'][-1]['seriesId']='metric-12p5-r1';duplicate['universalPostSeries']['posts'][-1]['heightMm']=25
        with self.assertRaises(APIError):validate_universal_posts(duplicate)

    def test_save_shared_and_cart_keep_original_and_metric_assets_distinct(self):
        source=layout({'custom-01':'test-metric-2'})
        result=aggregate(self.catalog,{'layout':source})
        reopened=aggregate(self.catalog,json.loads(layout_json(result)))
        self.assertEqual(reopened['layout']['instances'][0]['universalPostSelection'],source['instances'][0]['universalPostSelection'])
        p=project();p.update(layout=source,catalogVersion=self.catalog['version'],catalogReferenced=[{'id':'test-optic','name':'Test optic'}],ui={**p['ui'],'selectedIds':['i']})
        self.assertEqual(prepare_project(p,self.catalog)['manufacturing'][0]['componentId'],'test-metric-2')
        with tempfile.TemporaryDirectory() as folder:
            store=CartStore(SharedKitStore(Path(folder)/'cart.sqlite3'));identity=Identity('metric-test','Test','user');state=store.read(identity)
            for serial,request in enumerate([layout(),source]):
                state=store.add(identity,{'cartId':state['cartId'],'revision':state['revision'],'requestId':f'add-metric-{serial}','name':f'Post {serial}','payload':{'layout':request}},self.catalog)
            rows=state['preview']['manufacturing'];self.assertEqual({r['sourceComponentId']for r in rows},{'custom-01','test-metric-2'})
            preview=store.for_export(identity,{'cartId':state['cartId'],'revision':state['revision']},self.catalog)
            assets=Path(folder)/'assets'
            for cid in ['custom-01','test-metric-2']:
                c=next(c for c in self.catalog['components']if c['id']==cid)
                for field in ['stepPath','drawingPath']:
                    target=assets/c[field];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((cid+' fixture '+field).encode())
            content,_,_=export_result(preview,'bundle',assets,Path(__file__).resolve().parents[1]/'static')
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                steps=[z.read(n)for n in z.namelist()if n.endswith('.step')]
                self.assertCountEqual(steps,[b'custom-01 fixture stepPath',b'test-metric-2 fixture stepPath'])

if __name__=='__main__':unittest.main()
