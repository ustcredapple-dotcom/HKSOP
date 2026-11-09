"""Exact source-board geometry, immutable references and non-fabricated exports."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from xml.etree import ElementTree

from openpyxl import load_workbook
from bom import APIError, aggregate, validate_catalog
from breadboard import BreadboardError, normalize_board, board_specs, ensure_board_artifacts
from exports import export_result
from layout import choose_mounting_holes, layout_svg, validate_layout
from stacked_layout import aligned, plate_polygon
from test_layout import layout_fixture
from test_stacked_layout import board
import registered_boards as rb


def point(x,y):return {'xMm':x,'yMm':y}


def record():
    outline=[(0,0),(100,0),(100,40),(40,40),(40,100),(0,100)]
    cutout=[(50,5),(80,5),(80,35),(50,35)]
    mounts=[(12.5,12.5),(87.5,12.5),(12.5,87.5),(37.5,12.5)]
    return {'id':'fixture-l-board','revision':'source-01','name':'异形测试板 Al7075',
            'widthMm':100,'heightMm':100,'thicknessMm':12,'pitchMm':12.5,'edgeOffsetMm':12.5,
            'outlineMm':[point(*p) for p in outline],'cutoutsMm':[[point(*p) for p in cutout]],
            'holesMm':[{'id':'T1',**point(12.5,62.5),'type':'thread','diameterMm':6,'thread':'M6x1.0'},
                       {'id':'T2',**point(37.5,62.5),'type':'thread','diameterMm':6,'thread':'M6x1.0'},
                       {'id':'T3',**point(25,25),'type':'thread','diameterMm':4,'thread':'M4x0.7'}]+
                      [{'id':f'M{i+1}',**point(*p),'type':'counterbore','diameterMm':6.6,'counterboreDiameterMm':11,'counterboreDepthMm':6.5} for i,p in enumerate(mounts)],
            'mountingHoleIds':['M1','M2','M3','M4'],'minimumAlignedMountingHoles':4,
            'topViewPath':'topviews/fixture-l.svg','sourceUrl':'https://cad.onshape.com/documents/fixture',
            'sourceMaterial':'Al7075','stepPath':None,'drawingPath':None}


def reference():return {'registeredBoardId':'fixture-l-board','registeredBoardRevision':'source-01'}


class RegisteredBoardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.catalog=layout_fixture();self.catalog['registeredBoards']=[record()]
        self.path=self.root/'catalog.json';self.path.write_text(json.dumps(self.catalog))
        self.patcher=patch.object(rb,'CATALOG_PATH',self.path);self.patcher.start()
        self.kits={k['id']:k for k in self.catalog['kits']}
        tiny={'topViewPath':'topviews/test.svg','widthMm':10,'heightMm':10,'anchorXMm':5,'anchorYMm':5,
              'baseBoundsMm':{'xMin':-5,'yMin':-5,'xMax':5,'yMax':5},
              'collisionBoundsMm':{'xMin':-5,'yMin':-5,'xMax':5,'yMax':5},
              'mountingHoleOffsetsMm':[point(0,0)]}
        self.kits['alpha']['layout']=tiny
    def tearDown(self):self.patcher.stop();self.temp.cleanup()
    def layout(self,instances=None):return {'board':reference(),'instances':instances or []}
    def stack(self):return {'baseMode':'table','board':board(300,225),'subBoards':[{'id':'source','name':'原板','board':reference(),'xMm':0,'yMm':0,'rotationDeg':0}], 'instances':[]}
    def codes(self,layout):return {i['code'] for i in validate_layout(layout,self.kits)[2]['issues']}

    def test_immutable_reference_defaults_and_explicit_mount_choices(self):
        b=normalize_board(reference());self.assertEqual(b['widthMm'],100)
        self.assertEqual(b['mountingHoles'],[{'holeId':f'M{i}'} for i in range(1,5)])
        self.assertEqual(normalize_board({**b,'mountingHoles':[]})['mountingHoles'],[])
        for data in [{**b,'widthMm':101},{**b,'registeredBoardRevision':'old'},{**b,'outlineMm':[]},
                     {**b,'stepPath':'invented.step'},{**b,'mountingHoles':[{'holeId':'T1'}]},
                     {**b,'mountingHoles':[{'holeId':'M1'},{'holeId':'M1'}]}]:
            with self.assertRaises(BreadboardError):normalize_board(data)
        spec=board_specs(b);self.assertEqual(spec['holeCount'],7);self.assertEqual(spec['material'],'Al7075')
        self.assertEqual(spec['mountingHoles'][0]['xMm'],12.5)

    def test_exact_thread_holes_no_grid_invention_or_m4_as_m6(self):
        b=normalize_board(reference())
        self.assertTrue(aligned(b,(12.5,62.5)))
        for p in [(25,62.5),(62.5,62.5),(62.5,12.5),(25,25),(12.5,12.5)]:self.assertFalse(aligned(b,p),p)
        item={'id':'a','kitId':'alpha','xMm':12.5,'yMm':62.5,'rotationDeg':0}
        self.assertEqual(self.codes(self.layout([item])),set())
        item['xMm']=25
        self.assertIn('mounting_mismatch',self.codes(self.layout([item])))

    def test_concave_notch_and_internal_cutout_are_not_material(self):
        b=normalize_board(reference())
        self.assertFalse(rb.contains(b,(60,60)));self.assertFalse(rb.contains(b,(60,20)))
        self.assertTrue(rb.contains(b,(20,60)))
        self.assertFalse(rb.contains_polygon(b,[(30,30),(50,30),(50,50),(30,50)]))
        self.assertFalse(rb.contains_polygon(b,[(45,2),(85,2),(85,38),(45,38)]),'base surrounds a cutout')
        item={'id':'a','kitId':'alpha','xMm':62.5,'yMm':62.5,'rotationDeg':0}
        self.assertIn('out_of_bounds',self.codes(self.layout([item])))

    def test_rotated_outline_and_plate_collision_use_material_not_aabb(self):
        layout=self.stack();layout['subBoards'].append({'id':'inside-notch','name':'缺口内小板','board':board(25,25),'xMm':60,'yMm':60,'rotationDeg':0})
        self.assertNotIn('sub_board_collision',self.codes(layout))
        layout['subBoards'][1].update(xMm=52,yMm=7)
        self.assertNotIn('sub_board_collision',self.codes(layout),'plate fits completely into internal cutout')
        layout['subBoards'][1].update(xMm=30,yMm=30)
        self.assertIn('sub_board_collision',self.codes(layout))
        plate=layout['subBoards'][0];plate.update(rotationDeg=90,xMm=100)
        self.assertIn((60.0,40.0),plate_polygon(plate))

    def test_root_component_in_notch_not_wrongly_blocked_by_board(self):
        layout=self.stack();layout['instances']=[{'id':'root','kitId':'alpha','xMm':62.5,'yMm':62.5,'rotationDeg':0}]
        self.assertNotIn('collision',self.codes(layout))
        layout['instances'][0].update(xMm=25,yMm=62.5)
        self.assertIn('collision',self.codes(layout))

    def test_registered_auto_selection_reuses_only_existing_holes(self):
        result=choose_mounting_holes(self.catalog,{'layout':self.layout(),'holeCount':8})
        self.assertEqual({h['holeId'] for h in result['mountingHoles']},{'M1','M2','M3','M4'})
        with self.assertRaises(APIError) as caught:
            choose_mounting_holes(self.catalog,{'layout':self.layout()},candidate_filter=lambda x,y:x<50)
        self.assertEqual(caught.exception.code,'registered_mounting_unavailable')

    def test_source_boards_enter_bom_once_with_original_material_and_missing_assets(self):
        preview=aggregate(self.catalog,{'layout':self.stack()})
        self.assertEqual(preview['totals']['boards'],1)
        row=preview['manufacturing'][0]
        self.assertTrue(row['registeredBoard']);self.assertFalse(row.get('generatedBoard',False))
        self.assertEqual(row['manufacturingSpec']['material'],'Al7075')
        self.assertTrue(any(g.get('blocking') for g in preview['reviewGroups']))
        workbook,_,_=export_result(preview,'manufacturing',self.root)
        sheets=load_workbook(io.BytesIO(workbook),data_only=True)
        self.assertIn('面包板规格',sheets.sheetnames)
        self.assertTrue(any('Al7075' in str(v) for row in sheets['面包板规格'] for cell in row for v in [cell.value]))
        with patch('breadboard.ensure_board_artifacts',side_effect=AssertionError('must not fabricate rectangle')):
            with self.assertRaises(APIError) as caught:export_result(preview,'bundle',self.root)
        self.assertEqual(caught.exception.code,'asset_missing')
        with self.assertRaises(BreadboardError) as caught:ensure_board_artifacts(reference(),self.root)
        self.assertEqual(caught.exception.code,'registered_board_no_generator')

    def test_svg_uses_actual_paths_and_explicit_holes(self):
        for layout in [self.layout(),self.stack()]:
            preview=aggregate(self.catalog,{'layout':layout});svg=layout_svg(preview,self.root)
            document=ElementTree.fromstring(svg)
            self.assertEqual(len(document.findall('.//*[@data-board-hole]')),7)
            self.assertTrue(any(node.get('fill-rule')=='evenodd' for node in document.iter()))
            self.assertIn(b'M 0,100 L 100,100 L 100,60 L 40,60',svg)

    def test_registered_manufacturing_assets_pass_through_without_regeneration(self):
        entry=self.catalog['registeredBoards'][0]
        entry.update(stepPath='source/source.step',drawingPath='source/source.pdf')
        self.path.write_text(json.dumps(self.catalog));folder=self.root/'source';folder.mkdir()
        step=b'ISO-10303-21; VERIFIED FIXTURE SOURCE GEOMETRY; END-ISO-10303-21;'
        pdf=b'%PDF-1.4\n VERIFIED FIXTURE SOURCE DRAWING\n%%EOF'
        (folder/'source.step').write_bytes(step);(folder/'source.pdf').write_bytes(pdf)
        preview=aggregate(self.catalog,{'layout':self.stack()})
        with patch('breadboard.ensure_board_artifacts',side_effect=AssertionError('must not fabricate rectangle')):
            data,_,_=export_result(preview,'bundle',self.root)
        archive=zipfile.ZipFile(io.BytesIO(data))
        self.assertEqual([archive.read(name) for name in archive.namelist() if name.endswith('.step')],[step])
        self.assertEqual([archive.read(name) for name in archive.namelist() if name.endswith('.pdf')],[pdf])

    def test_catalog_bounds_references_and_asset_paths_are_checked(self):
        self.assertEqual(len(validate_catalog(self.catalog)['registeredBoards']),1)
        for mutate in [lambda r:r.update(outlineMm=[point(0,0)]),lambda r:r.update(mountingHoleIds=['T1']),
                       lambda r:r.update(stepPath='../wrong.step'),lambda r:r['holesMm'][0].update(xMm=101),
                       lambda r:r.update(cutoutsMm=[r['outlineMm']]*65)]:
            catalog=copy.deepcopy(self.catalog);mutate(catalog['registeredBoards'][0])
            with self.assertRaises(APIError):validate_catalog(catalog)

    def test_account_cart_keeps_board_and_rejects_changed_revision(self):
        from cart import CartStore
        from shared_kits import Identity, SharedKitStore
        store=CartStore(SharedKitStore(self.root/'cart.sqlite3',self.root/'backup.sqlite3'))
        user=Identity('test','test','user');empty=store.read(user)
        added=store.add(user,{'cartId':empty['cartId'],'revision':empty['revision'],'requestId':'registered-board-001','name':'异形板','payload':{'layout':self.stack()}},self.catalog)
        payload={'cartId':added['cartId'],'revision':added['revision']}
        result=store.for_export(user,payload,self.catalog)
        self.assertEqual(result['totals']['boards'],1)
        self.assertEqual(result['manufacturing'][0]['manufacturingSpec']['material'],'Al7075')
        changed=copy.deepcopy(self.catalog);changed['registeredBoards'][0]['revision']='source-02'
        with self.assertRaises(APIError) as caught:store.for_export(user,payload,changed)
        self.assertEqual(caught.exception.code,'cart_source_changed')

    def test_catalog_context_is_scoped_to_each_aggregate_call(self):
        with patch.object(rb,'CATALOG_PATH',self.root/'nonexistent.json'):
            self.assertEqual(aggregate(self.catalog,{'layout':self.stack()})['totals']['boards'],1)
            with self.assertRaises(BreadboardError):normalize_board(reference())


if __name__=='__main__':unittest.main()
