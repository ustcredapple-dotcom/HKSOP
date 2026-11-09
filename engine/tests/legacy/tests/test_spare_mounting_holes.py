"""Eight physical holes may provide four usable mounts; brown contours decide access."""
import copy
import io
import math
from pathlib import Path
import tempfile
import unittest
from openpyxl import load_workbook

from bom import aggregate
from breadboard import BreadboardError, normalize_board, board_specs
from exports import export_result
from layout import choose_mounting_holes, hole_obstructs_shape, world_geometry
from test_layout import layout_fixture
from test_stacked_layout import plan, board


class SpareMountingTests(unittest.TestCase):
    def setUp(self):
        self.catalog=layout_fixture()
        geometry=self.catalog['kits'][0]['layout']
        geometry.update(collisionBoundsMm={'xMin':-1,'xMax':1,'yMin':-1,'yMax':1},
                        baseBoundsMm={'xMin':-2,'xMax':2,'yMin':-2,'yMax':2},
                        mountingHoleOffsetsMm=[{'xMm':0,'yMm':0}])

    def ready(self,pitch=25):
        layout=plan(pitch)
        layout['instances']=[]
        selected=choose_mounting_holes(self.catalog,{'layout':layout,'boardId':'s1','holeCount':8})
        layout['subBoards'][0]['board']['mountingHoles']=selected['boards'][0]['mountingHoles']
        return layout

    def preview(self,layout):
        return aggregate(self.catalog,{'layout':layout})

    def obstacle(self,hole,iid='obstacle'):
        return {'id':iid,'kitId':'alpha','boardId':'s1','xMm':hole['xMm'],'yMm':hole['yMm'],'rotationDeg':0}

    def test_auto_eight_with_four_matching_on_25_and_eight_matching_on_12p5(self):
        for pitch,aligned in ((25,4),(12.5,8)):
            layout=self.ready(pitch)
            result=self.preview(layout)
            with self.subTest(pitch=pitch):
                self.assertTrue(result['layoutValidation']['valid'],result['layoutValidation'])
                record,=result['layoutValidation']['subBoardMountingAlignment']
                self.assertEqual((record['totalCount'],record['alignedCount'],record['usableCount'],record['requiredCount']),(8,aligned,aligned,4))
                self.assertEqual(sum(h['spare'] for h in record['holes']),8-aligned)

    def test_covered_spare_hole_does_not_block_four_usable_mounts(self):
        layout=self.ready()
        record=self.preview(layout)['layoutValidation']['subBoardMountingAlignment'][0]
        spare=next(h for h in record['holes'] if not h['aligned'])
        layout['instances']=[self.obstacle(spare)]
        result=self.preview(layout)
        self.assertTrue(result['layoutValidation']['valid'],result['layoutValidation'])
        record=result['layoutValidation']['subBoardMountingAlignment'][0]
        self.assertEqual(record['usableCount'],4)
        self.assertTrue(next(h for h in record['holes'] if h['id']==spare['id'])['obstructed'])
        self.assertFalse(result['layoutValidation']['mountingHoleObstructions'])

    def test_three_usable_mounts_fail_without_reporting_each_spare_as_mismatch(self):
        layout=self.ready()
        primary=next(h for h in self.preview(layout)['layoutValidation']['subBoardMountingAlignment'][0]['holes'] if h['aligned'])
        layout['instances']=[self.obstacle(primary)]
        result=self.preview(layout)
        issues=result['layoutValidation']['issues']
        self.assertEqual([i['code'] for i in issues],['sub_board_mounting_insufficient'])
        self.assertEqual((issues[0]['usableCount'],issues[0]['requiredCount']),(3,4))

    def test_four_hole_mode_still_requires_every_hole_and_reverts_when_eight_removed(self):
        layout=self.ready()
        source=self.preview(layout)['layoutValidation']['subBoardMountingAlignment'][0]
        backup_ids={h['id'] for h in source['holes'] if h['spare']}
        spec=board_specs(layout['subBoards'][0]['board'])
        layout['subBoards'][0]['board']['mountingHoles']=[{'columnIndex':h['columnIndex'],'rowIndex':h['rowIndex']} for h in spec['mountingHoles'] if h['label'] in backup_ids]
        result=self.preview(layout)
        self.assertEqual(len([i for i in result['layoutValidation']['issues'] if i['code']=='sub_board_mounting_mismatch']),4)

    def test_table_no_holes_needs_no_mounts_and_selected_eight_need_four_clear(self):
        layout=plan()
        layout.update(baseMode='table',instances=[])
        self.assertEqual(self.preview(layout)['layoutValidation']['subBoardMountingAlignment'][0]['requiredCount'],0)
        layout=self.ready()
        layout['baseMode']='table'
        holes=self.preview(layout)['layoutValidation']['subBoardMountingAlignment'][0]['holes']
        layout['instances']=[self.obstacle(h,f'o{i}') for i,h in enumerate(holes[:4])]
        result=self.preview(layout)
        self.assertTrue(result['layoutValidation']['valid'],result['layoutValidation'])
        self.assertEqual(result['layoutValidation']['subBoardMountingAlignment'][0]['usableCount'],4)
        layout['instances'].append(self.obstacle(holes[4],'o4'))
        self.assertIn('sub_board_mounting_insufficient',{i['code'] for i in self.preview(layout)['layoutValidation']['issues']})

    def test_auto_eight_tries_either_parity_as_primary_and_rotations(self):
        for rotation,position in ((0,(12.5,12.5)),(90,(200,12.5)),(180,(200,150)),(270,(12.5,200))):
            layout=plan()
            layout['instances']=[]
            layout['subBoards'][0].update(rotationDeg=rotation,xMm=position[0],yMm=position[1])
            selected=choose_mounting_holes(self.catalog,{'layout':layout,'boardId':'s1','holeCount':8})
            layout['subBoards'][0]['board']['mountingHoles']=selected['boards'][0]['mountingHoles']
            result=self.preview(layout)
            with self.subTest(rotation=rotation):
                self.assertTrue(result['layoutValidation']['valid'],result['layoutValidation'])
                self.assertGreaterEqual(result['layoutValidation']['subBoardMountingAlignment'][0]['usableCount'],4)

    def test_spare_holes_remain_in_production_spec_svg_and_installation_workbook(self):
        result=self.preview(self.ready())
        child=[r for r in result['manufacturing'] if r.get('generatedBoard') and r['boardSpec']['mountingHoleCount']==8]
        self.assertEqual(len(child),1)
        self.assertEqual(len(child[0]['boardSpec']['mountingHoles']),8)
        data,_,_=export_result(result,'manufacturing',Path('/unused'))
        wb=load_workbook(io.BytesIO(data))
        states=[wb['小板固定孔'].cell(i,12).value for i in range(6,14)]
        self.assertEqual(states.count('可用固定孔'),4)
        self.assertEqual(states.count('备用孔'),4)
        with tempfile.TemporaryDirectory() as temp:
            svg,_,_=export_result(result,'layout-svg',Path(temp),Path(temp))
            self.assertEqual(svg.decode().count(' 备用'),4)


class CounterboreContourTests(unittest.TestCase):
    def test_blue_base_and_reference_mount_circles_are_not_physical_obstacles(self):
        geometry={'widthMm':80,'heightMm':80,'anchorXMm':40,'anchorYMm':40,
                  'baseBoundsMm':{'xMin':-40,'xMax':40,'yMin':-40,'yMax':40},
                  'collisionBoundsMm':{'xMin':-5,'xMax':5,'yMin':-5,'yMax':5},
                  'mountingHoleOffsetsMm':[{'xMm':20,'yMm':0}]}
        instance={'id':'a','kitId':'test','xMm':100,'yMm':100,'rotationDeg':0}
        shape=world_geometry(instance,geometry)
        self.assertFalse(hole_obstructs_shape((120,100),5.5,shape))
        self.assertTrue(hole_obstructs_shape((110.5,100),5.5,shape))
        self.assertFalse(hole_obstructs_shape((110.5001,100),5.5,shape))
        geometry['collisionPolygonsMm']=[[{'xMm':x,'yMm':y} for x,y in ((-40,-40),(40,-40),(40,-30),(-30,-30),(-30,40),(-40,40))]]
        shape=world_geometry(instance,geometry)
        self.assertFalse(hole_obstructs_shape((120,120),5.5,shape))
        self.assertTrue(hole_obstructs_shape((65,100),5.5,shape))

    def test_auto_and_applied_holes_ignore_large_blue_base_outside_small_brown_shape(self):
        catalog=layout_fixture()
        geometry=catalog['kits'][0]['layout']
        geometry.update(baseBoundsMm={'xMin':-100,'xMax':100,'yMin':-75,'yMax':75},
                        collisionBoundsMm={'xMin':-1,'xMax':1,'yMin':-1,'yMax':1},
                        mountingHoleOffsetsMm=[{'xMm':0,'yMm':0}])
        layout={'board':board(),'instances':[{'id':'a','kitId':'alpha','xMm':100,'yMm':75,'rotationDeg':0}]}
        selected=choose_mounting_holes(catalog,{'layout':layout})
        self.assertEqual(len(selected['mountingHoles']),4)
        layout['board']=selected['board']
        self.assertTrue(aggregate(catalog,{'layout':layout})['layoutValidation']['valid'])

    def test_close_counterbores_need_no_extra_web_but_cannot_overlap(self):
        source=board(80,80,25/3)
        source.update(edgeOffsetMm=8,holeType='plain_through',holeDiameterMm=1)
        source['mountingHoles']=[{'columnIndex':c,'rowIndex':r} for low in (0,1) for c in (low,low+6) for r in (low,low+6)]
        accepted=normalize_board(source)
        points=[(h['xMm'],h['yMm']) for h in board_specs(accepted)['mountingHoles']]
        minimum=min(math.dist(p,q) for i,p in enumerate(points) for q in points[:i])
        self.assertGreaterEqual(minimum,11)
        self.assertLess(minimum,13)
        # Regular grid holes still need the original 2 mm web.
        source['holeDiameterMm']=3
        with self.assertRaises(BreadboardError) as caught:
            normalize_board(source)
        self.assertEqual(caught.exception.code,'mounting_hole_web')
        # Merely removing an intersecting selected hole is not allowed either:
        # duplicates are not distinct counterbores, and edge/bottom remain strict.
        source['holeDiameterMm']=1
        source['mountingHoles'][1]=copy.deepcopy(source['mountingHoles'][0])
        with self.assertRaises(BreadboardError):normalize_board(source)


if __name__=='__main__':unittest.main()
