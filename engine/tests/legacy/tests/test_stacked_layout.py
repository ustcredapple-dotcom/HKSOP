"""Physical two-level assembly, unchanged draft holes, quantities and coordinates."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from openpyxl import load_workbook
from test_layout import layout_fixture
from bom import aggregate, APIError
from breadboard import normalize_board, board_specs, BreadboardError
from layout import choose_mounting_holes, validate_layout, layout_svg, layout_json
from stacked_layout import aligned, global_instance
from exports import export_result


def board(width=200,height=150,pitch=12.5):
    return dict(widthMm=width,heightMm=height,pitchMm=pitch,edgeOffsetMm=12.5,thicknessMm=12.7,holeType='M6_through',mountingHoles=[])

def plan(pitch=25):
    return {'board':board(600,450,pitch),'subBoards':[{'id':'s1','name':'测试小板','board':board(),'xMm':0,'yMm':0,'rotationDeg':0}], 'instances':[{'id':'a1','kitId':'alpha','boardId':'s1','xMm':100,'yMm':75,'rotationDeg':0}]}

class StackedTests(unittest.TestCase):
    def setUp(self):self.catalog=layout_fixture();self.kits={k['id']:k for k in self.catalog['kits']}
    def select(self,l,**kw):return choose_mounting_holes(self.catalog,{'layout':l,'boardId':'s1',**kw})
    def ready(self,pitch=25):
        l=plan(pitch);l['subBoards'][0]['board']['mountingHoles']=self.select(l)['boards'][0]['mountingHoles'];return l
    def codes(self,l):return {i['code'] for i in validate_layout(l,self.kits)[2]['issues']}
    def test_unfastened_and_no_overlap_are_editable_errors(self):
        l=plan();self.assertIn('sub_board_unfastened',self.codes(l));l['subBoards'][0]['xMm']=1;self.assertIn('sub_board_no_overlap',self.codes(l))
    def test_auto4_aligned_on_25_and_obstruction_safe(self):
        l=self.ready();self.assertEqual(self.codes(l),set());p=l['subBoards'][0]
        for h in board_specs(p['board'])['mountingHoles']:
            self.assertTrue(aligned(l['board'],(h['xMm'],h['yMm'])))
            self.assertEqual((h['columnIndex']%2,h['rowIndex']%2),(0,0))
    def test_move_preserves_old_holes_and_flags_mismatch_then_reselect(self):
        l=self.ready();holes=copy.deepcopy(l['subBoards'][0]['board']['mountingHoles']);l['subBoards'][0]['xMm']=12.5
        normalized,_,v=validate_layout(l,self.kits);self.assertIn('sub_board_mounting_mismatch',{i['code'] for i in v['issues']});self.assertEqual(normalized['subBoards'][0]['board']['mountingHoles'],holes)
        selected=self.select(l)['boards'][0]['mountingHoles'];self.assertNotEqual(selected,holes);self.assertEqual(l['subBoards'][0]['board']['mountingHoles'],holes)
        l['subBoards'][0]['board']['mountingHoles']=selected;self.assertEqual(self.codes(l),set())
    def test_rotation_and_translation_are_applied_to_holes_and_components(self):
        l=plan();p=l['subBoards'][0];p.update(xMm=150,yMm=0,rotationDeg=90);p['board']['mountingHoles']=self.select(l)['boards'][0]['mountingHoles'];self.assertEqual(self.codes(l),set())
        world=global_instance(l['instances'][0],{'s1':p});self.assertEqual((world['xMm'],world['yMm'],world['rotationDeg']),(75,100,90));self.assertEqual(l['instances'][0]['xMm'],100)
    def test_root_and_rotated_child_allow_between_hole_component_centers(self):
        l=plan(25);p=l['subBoards'][0];p['board']['pitchMm']=25;p.update(xMm=400,yMm=25,rotationDeg=90)
        l['instances'].append({'id':'root','kitId':'beta','xMm':50,'yMm':300,'rotationDeg':0})
        p['board']['mountingHoles']=self.select(l)['boards'][0]['mountingHoles']
        original=copy.deepcopy(l);normalized,_,validation=validate_layout(l,self.kits)
        self.assertTrue(validation['valid'],validation['issues']);self.assertEqual(l,original)
        self.assertEqual([(i['id'],i['xMm'],i['yMm']) for i in normalized['instances']], [('root',50,300),('a1',100,75)])
        l['instances'][0]['xMm']=112.5
        issues=validate_layout(l,self.kits)[2]['issues'];mismatch=[i for i in issues if i['code']=='mounting_mismatch']
        self.assertEqual([(i['instanceIds'],i.get('boardId')) for i in mismatch],[(['a1'],'s1')])
        l['instances'][0]['xMm']=100;l['instances'][1]['xMm']=62.5
        mismatch=[i for i in validate_layout(l,self.kits)[2]['issues'] if i['code']=='mounting_mismatch']
        self.assertEqual([(i['instanceIds'],i.get('boardId')) for i in mismatch],[(['root'],None)])
    def test_eight_holes_standalone_and_on_fine_parent(self):
        l=plan(12.5);small=l['subBoards'][0]['board'];selected=choose_mounting_holes(self.catalog,{'layout':{'board':small,'instances':[]},'holeCount':8});self.assertEqual(len(selected['mountingHoles']),8)
        normalized=normalize_board({**small,'mountingHoles':selected['mountingHoles']});self.assertEqual(board_specs(normalized)['mountingHoleCount'],8)
        chosen=self.select(l,holeCount=8)['boards'][0];self.assertEqual(len(chosen['mountingHoles']),8);small['mountingHoles']=chosen['mountingHoles'];self.assertEqual(self.codes(l),set())
        l['board']['pitchMm']=25;self.assertEqual(self.codes(l),set());original=copy.deepcopy(l)
        selected=self.select(l,holeCount=8)['boards'][0];self.assertEqual(len(selected['mountingHoles']),8)
        self.assertEqual(l,original)
    def test_eight_requires_two_opposite_parity_groups_and_four_each(self):
        holes=[{'columnIndex':c,'rowIndex':r} for c in (0,2) for r in (0,2,4,6)]
        with self.assertRaises(BreadboardError):normalize_board({**board(),'mountingHoles':holes})
        for hole_count in (0,True,6,9,'8'):
            with self.assertRaises(APIError):self.select(plan(),holeCount=hole_count)
    def test_parent_counterbores_are_not_threaded_mounting_candidates(self):
        l=self.ready();l['board']['mountingHoles']=[{'columnIndex':c,'rowIndex':r} for c in (0,2) for r in (0,2)]
        self.assertFalse(aligned(l['board'],(12.5,12.5)));chosen=self.select(l)['boards'][0]
        self.assertNotIn({'columnIndex':0,'rowIndex':0},chosen['mountingHoles'])
    def test_all_selection_is_atomic_and_each_plate_gets_own_holes(self):
        l=plan();p=copy.deepcopy(l['subBoards'][0]);p.update(id='s2',name='第二块',xMm=250);l['subBoards'].append(p);original=copy.deepcopy(l)
        response=self.select(l,boardId='all');self.assertEqual([r['boardId'] for r in response['boards']],['s1','s2']);self.assertEqual(l,original)
        p['xMm']=251
        with self.assertRaises(APIError):self.select(l,boardId='all')
        self.assertEqual(l['subBoards'][0]['board']['mountingHoles'],[])
    def test_bounds_and_board_overlap(self):
        l=self.ready();p=copy.deepcopy(l['subBoards'][0]);p.update(id='s2',name='第二块',xMm=100);l['subBoards'].append(p);self.assertIn('sub_board_collision',self.codes(l));p['xMm']=500;self.assertIn('sub_board_out_of_bounds',self.codes(l))
    def test_remote_component_blocks_mounting_hole(self):
        l=self.ready();l['instances'].append({'id':'root','kitId':'beta','xMm':12.5,'yMm':12.5,'rotationDeg':0});self.assertIn('mounting_hole_obstructed',self.codes(l));chosen=self.select(l)['boards'][0];self.assertNotIn({'columnIndex':0,'rowIndex':0},chosen['mountingHoles'])
    def test_bad_ids_and_shapes_rejected(self):
        for owner in ('missing',None,[],{}):
            l=plan();l['instances'][0]['boardId']=owner
            with self.subTest(owner=owner),self.assertRaises(APIError):validate_layout(l,self.kits)
        l=plan();l['instances'].append(copy.deepcopy(l['instances'][0]))
        with self.assertRaises(APIError):validate_layout(l,self.kits)
        for value in (None,42,[None],['x']):
            l=plan();l['subBoards']=value
            with self.subTest(value=value),self.assertRaises(APIError):self.select(l)
    def test_multiboard_bom_aggregates_identical_boards(self):
        l=self.ready();p=copy.deepcopy(l['subBoards'][0]);p.update(id='s2',name='第二块',xMm=250);l['subBoards'].append(p)
        preview=aggregate(self.catalog,{'layout':l});self.assertEqual(preview['totals']['boards'],3)
        rows=[r for r in preview['manufacturing'] if r.get('generatedBoard')];self.assertEqual(sorted(r['quantity'] for r in rows),[1,2]);self.assertEqual(preview['totals']['kits'],1)
    def test_spreadsheet_has_local_and_world_coordinates_and_fixed_holes(self):
        l=self.ready();l['subBoards'][0]['xMm']=250;preview=aggregate(self.catalog,{'layout':l})
        data,_,_=export_result(preview,'manufacturing',Path('/nonexistent'));wb=load_workbook(io.BytesIO(data));self.assertEqual(wb['小板安装位置']['E6'].value,250);self.assertEqual(wb['叠装器件位置']['D6'].value,100);self.assertEqual(wb['叠装器件位置']['G6'].value,350);self.assertEqual(wb['小板固定孔']['L6'].value,'重合')
        doc=json.loads(layout_json(preview));self.assertEqual(len(doc['layout']['subBoards']),1)
    def test_invalid_mounts_cannot_export_production(self):
        l=self.ready();l['subBoards'][0]['xMm']=12.5;p=aggregate(self.catalog,{'layout':l})
        for fmt in ('manufacturing','bundle','lubang'):
            with self.assertRaises(APIError) as caught:export_result(p,fmt,Path('/nonexistent'))
            self.assertEqual(caught.exception.code,'layout_invalid')
    def test_svg_contains_board_and_global_component_pose(self):
        l=self.ready();l['subBoards'][0]['xMm']=250;p=aggregate(self.catalog,{'layout':l})
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);(base/'topviews').mkdir();(base/'topviews/test.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            svg=layout_svg(p,base).decode();self.assertIn('data-sub-board="s1"',svg);self.assertIn('translate(350 ',svg)

if __name__=='__main__':unittest.main()
