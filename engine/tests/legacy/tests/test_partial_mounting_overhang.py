"""Catalog-scoped partial support needs real M6 threads, never reference grid dots."""
import copy
import json
from pathlib import Path
import unittest

from bom import APIError, aggregate
from collision_overrides import CAPABILITY
from layout import kit_geometry
from test_stacked_layout import board
from test_registered_boards import point

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    catalog=json.loads((ROOT/'catalog.json').read_text())
    kit=next(k for k in catalog['kits'] if k['id']=='waveplate')
    kit['layout'].update(baseOverhangAllowedWithPartialMounting=True,minimumAlignedMountingHoles=2)
    return catalog


def plan(x=100,y=0,angle=90,pitch=12.5):
    return {'board':board(350,225,pitch),'instances':[{'id':'wp','kitId':'waveplate','xMm':x,'yMm':y,'rotationDeg':angle}]}


def record():
    return dict(id='overhang-plate',revision='QA-1',name='Synthetic real-hole plate',
        widthMm=200,heightMm=150,thicknessMm=12.7,pitchMm=12.5,edgeOffsetMm=12.5,
        outlineMm=[point(x,y) for x,y in [(0,0),(200,0),(200,150),(0,150)]],
        holesMm=[dict(id='T1',**point(87.5,12.5),type='thread',diameterMm=6,thread='M6x1.0'),
                 dict(id='T2',**point(112.5,12.5),type='thread',diameterMm=6,thread='M6x1.0')],
        mountingHoleIds=[],minimumAlignedMountingHoles=1,
        topViewPath='topviews/test.svg',sourceUrl='https://example.com/source',stepPath=None,drawingPath=None)


class PartialMountingOverhangTests(unittest.TestCase):
    def setUp(self):self.c=fixture()
    def preview(self,p,c=None,**extra):return aggregate(c or self.c,{'layout':p,**extra})
    def codes(self,r):return {i['code'] for i in r['layoutValidation']['issues']}
    def alignment(self,r):return r['layoutValidation']['mountingAlignment'][0]

    def test_real_old_dual_waveplate_all_rotations_both_grids_and_four_edges(self):
        for pitch in (12.5,25):
            for angle in (0,90,180,270):
                for x,y in ((100,0),(0,100),(350,100),(100,225)):
                    with self.subTest(pitch=pitch,angle=angle,x=x,y=y):
                        p=plan(x,y,angle,pitch);before=copy.deepcopy(p);r=self.preview(p)
                        self.assertTrue(r['layoutValidation']['valid'],r['layoutValidation']['issues'])
                        self.assertEqual(self.alignment(r)['alignedCount'],2)
                        self.assertEqual(self.alignment(r)['requiredCount'],2)
                        self.assertEqual(p,before)

    def test_one_or_zero_mounts_still_fail_installation_and_bounds(self):
        for x,y,count in ((0,0,1),(100,-12.5,0),(100,1,0)):
            with self.subTest(x=x,y=y):
                r=self.preview(plan(x,y));self.assertEqual(self.alignment(r)['alignedCount'],count)
                self.assertTrue({'mounting_mismatch','out_of_bounds'} <= self.codes(r))

    def test_regular_counterbores_do_not_count_as_threaded_support(self):
        for columns,count in (((6,16),1),((6,8),0)):
            p=plan();p['board']['mountingHoles']=[dict(columnIndex=x,rowIndex=y) for x in columns for y in (0,2)]
            r=self.preview(p)
            self.assertEqual(self.alignment(r)['alignedCount'],count)
            self.assertTrue({'mounting_mismatch','out_of_bounds'} <= self.codes(r))
            self.assertIn('mounting_hole_obstructed',self.codes(r))

    def test_plain_grid_cannot_provide_threaded_support(self):
        p=plan();p['board'].update(holeType='plain_through',holeDiameterMm=6.6)
        r=self.preview(p);self.assertEqual(self.alignment(r)['alignedCount'],0)
        self.assertTrue({'mounting_mismatch','out_of_bounds'} <= self.codes(r))

    def test_registered_board_uses_only_actual_m6_threads(self):
        c=copy.deepcopy(self.c);c['registeredBoards']=[record()]
        p=plan();p['board']=dict(registeredBoardId='overhang-plate',registeredBoardRevision='QA-1')
        self.assertTrue(self.preview(p,c)['layoutValidation']['valid'])
        for kind in ('missing','clearance','counterbore','M4'):
            altered=copy.deepcopy(c);holes=altered['registeredBoards'][0]['holesMm']
            if kind=='missing':holes.pop()
            elif kind=='M4':holes[-1].update(thread='M4x0.7',diameterMm=4)
            else:
                holes[-1]['type']=kind;holes[-1].pop('thread')
                if kind=='counterbore':holes[-1].update(diameterMm=6.6,counterboreDiameterMm=11,counterboreDepthMm=6.5)
            with self.subTest(kind=kind):
                r=self.preview(p,altered);self.assertEqual(self.alignment(r)['alignedCount'],1)
                self.assertTrue({'mounting_mismatch','out_of_bounds'} <= self.codes(r))

    def test_table_root_dots_cannot_allow_overhang_but_real_child_can(self):
        p=plan();p['baseMode']='table'
        r=self.preview(p);self.assertIn('out_of_bounds',self.codes(r))
        # In-board table placement remains legal; it is only a work area.
        p['instances'][0]['yMm']=50;self.assertTrue(self.preview(p)['layoutValidation']['valid'])
        p=plan();p['baseMode']='table';p['instances'][0]['boardId']='small'
        p['subBoards']=[dict(id='small',name='实际小板',board=board(200,150),xMm=50,yMm=25,rotationDeg=0)]
        r=self.preview(p);self.assertTrue(r['layoutValidation']['valid'],r['layoutValidation']['issues'])
        self.assertEqual(self.alignment(r)['boardId'],'small')
        # Supporting small board itself must still fit within the work area.
        p['subBoards'][0]['xMm']=300
        self.assertIn('sub_board_out_of_bounds',self.codes(self.preview(p)))

    def test_child_on_physical_parent_obeys_its_own_board_boundary(self):
        p=plan();p['instances'][0]['boardId']='small'
        small=board(200,150)
        small['mountingHoles']=[dict(columnIndex=x,rowIndex=y) for x in (0,14) for y in (2,10)]
        p['subBoards']=[dict(id='small',name='已固定小板',board=small,xMm=50,yMm=25,rotationDeg=90)]
        # Rotate the whole carrier into the mother plate; child remains local.
        p['subBoards'][0].update(xMm=200,yMm=12.5)
        r=self.preview(p);self.assertTrue(r['layoutValidation']['valid'],r['layoutValidation']['issues'])
        self.assertEqual(self.alignment(r)['alignedCount'],2)

    def test_opt_in_does_not_affect_other_kits_or_allow_catalog_flag_forgery(self):
        p=plan();p['instances'][0]['kitId']='pbs-fixed'
        r=self.preview(p);self.assertIn('out_of_bounds',self.codes(r))
        c=copy.deepcopy(self.c);g=next(k for k in c['kits'] if k['id']=='waveplate')['layout']
        for value in (False,None):
            if value is None:g.pop('baseOverhangAllowedWithPartialMounting',None)
            else:g['baseOverhangAllowedWithPartialMounting']=value
            r=self.preview(plan(),c);self.assertEqual(self.alignment(r)['alignedCount'],2)
            self.assertIn('out_of_bounds',self.codes(r))
        p=plan();p['instances'][0]['baseOverhangAllowedWithPartialMounting']=True
        with self.assertRaises(APIError):self.preview(p)

    def test_invalid_flag_and_minimum_fail_closed(self):
        original=next(k for k in self.c['kits'] if k['id']=='waveplate')
        for value in (1,'true',None,[]):
            k=copy.deepcopy(original);k['layout']['baseOverhangAllowedWithPartialMounting']=value
            with self.subTest(flag=value),self.assertRaises(APIError):kit_geometry(k)
        for value in (None,True,1,0,5):
            k=copy.deepcopy(original);k['layout']['minimumAlignedMountingHoles']=value
            with self.subTest(minimum=value),self.assertRaises(APIError):kit_geometry(k)

    def test_collision_is_unchanged_and_pair_waiver_does_not_enable_bad_support(self):
        p=plan();p['instances'].append({**p['instances'][0],'id':'other'})
        r=self.preview(p);self.assertIn('collision',self.codes(r));self.assertNotIn('out_of_bounds',self.codes(r))
        p['collisionOverrides']=[dict(instanceIds=['wp','other'])]
        self.assertTrue(self.preview(p,requires=[CAPABILITY])['layoutValidation']['valid'])
        for i in p['instances']:i.update(xMm=0,yMm=0)
        r=self.preview(p,requires=[CAPABILITY])
        self.assertNotIn('collision',self.codes(r))
        self.assertTrue({'mounting_mismatch','out_of_bounds'} <= self.codes(r))


if __name__=='__main__':unittest.main()
