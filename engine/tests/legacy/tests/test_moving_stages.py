"""Integrated motion uses explicit synthetic geometry; no vendor fit claims."""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import load_workbook
from bom import APIError, aggregate, validate_catalog
from moving_stages import fixed_pose, module_for, rotate, world_bodies
from shared_kits import project_payload, prepare_project
from stacked_layout import global_instance
from exports import export_result
from layout import layout_svg, choose_mounting_holes
from test_layout import layout_fixture
from test_stacked_layout import board
from test_shared_kits import project
import registered_boards as rb


def fixture():
    c=layout_fixture()
    c['kits'][0]['layout'].update(widthMm=4,heightMm=4,anchorXMm=2,anchorYMm=2,
        collisionBoundsMm=dict(xMin=-2,yMin=-2,xMax=2,yMax=2),baseBoundsMm=dict(xMin=-2,yMin=-2,xMax=2,yMax=2),
        mountingHoleOffsetsMm=[{'xMm':0,'yMm':0}],opticalAxisHeightMm=62.5)
    c['registeredBoards']=[dict(id='stage-top',revision='R1',name='Synthetic top',stageOnly=True,
        widthMm=50,heightMm=50,thicknessMm=8.5,pitchMm=12.5,edgeOffsetMm=12.5,
        outlineMm=[dict(xMm=x,yMm=y) for x,y in [(0,0),(50,0),(50,50),(0,50)]],
        holesMm=[dict(id=f'T{x}-{y}',xMm=x,yMm=y,type='thread',diameterMm=6,thread='M6x1.0') for x in [12.5,37.5] for y in [12.5,25,37.5]],
        mountingHoleIds=[],minimumAlignedMountingHoles=1,topViewPath='topviews/test.svg',stepPath='plate.step',drawingPath='plate.pdf')]
    c['stageModules']=[dict(id='stage-synthetic',revision='R1',name='Synthetic XY stage',stage=dict(heightMm=17),
        runtime=dict(topBoardId='stage-top',topBoardRevision='R1',kitId='stage-synthetic',baseBoundsMm=dict(xMin=-25,xMax=25,yMin=-25,yMax=25),
                     fixedTopView=dict(src='topviews/test.svg',widthMm=80,heightMm=50,anchorXMm=55,anchorYMm=25),
                     movingTopView=dict(src='topviews/test.svg',widthMm=50,heightMm=50,anchorXMm=25,anchorYMm=25)),
        stack=dict(bottomAdapterThicknessMm=12,topPlateThicknessMm=8.5,totalHeightMm=37.5),
        centerTopOriginMm=dict(xMm=-25,yMm=-25),lowerGrid=dict(pitchMm=12.5,originXMm=0,originYMm=0),
        topSurface=dict(widthMm=50,heightMm=50,holes=[dict(h,usable=True) for h in c['registeredBoards'][0]['holesMm']]),
        lowerAttachmentHoles=[dict(id=f'B{x}-{y}',xMm=x,yMm=y) for x in [-12.5,12.5] for y in [-12.5,12.5]],
        motion=dict(axis='x',minMm=-3.25,maxMm=3.25,workingMinMm=-3,workingMaxMm=3),
        collisionBodies=[dict(id='base',frame='fixed',boundsMm=dict(xMin=-55,xMax=25,yMin=-25,yMax=25,zMin=0,zMax=29)),dict(id='top',frame='moving',boundsMm=dict(xMin=0,xMax=50,yMin=0,yMax=50,zMin=-8.5,zMax=0))],
        bom=[dict(componentId='plate',quantity=1,role='top-plate'),dict(componentId='bracket',quantity=1,role='bottom-adapter'),dict(componentId='bolt',quantity=4,role='fastener')])]
    c['kits'].append({**copy.deepcopy(c['kits'][0]),'id':'stage-synthetic','name':'Synthetic XY stage','stageModuleId':'stage-synthetic','components':[{k:x[k] for k in ('componentId','quantity')} for x in c['stageModules'][0]['bom']],'opticalSlots':[],'pendingRequirements':[]})
    return validate_catalog(c)


def plan(q=0,rotation=0,child=True):
    dx,dy=rotate(-25+q,-25,rotation)
    p=dict(id='s1',name='Synthetic stage',board=dict(registeredBoardId='stage-top',registeredBoardRevision='R1'),
           xMm=200+dx,yMm=200+dy,rotationDeg=rotation,stageMotion=dict(moduleId='stage-synthetic',revision='R1',qMm=q))
    return dict(board=board(600,450,25),subBoards=[p],instances=[dict(id='a1',kitId='alpha',boardId='s1',xMm=12.5,yMm=12.5,rotationDeg=0)] if child else [])


class MovingStageTests(unittest.TestCase):
    def setUp(self):
        self.c=fixture();self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.path=self.root/'catalog.json';self.path.write_text(json.dumps(self.c));self.patch=patch.object(rb,'CATALOG_PATH',self.path);self.patch.start()
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def preview(self,p):return aggregate(self.c,{'layout':p,'requires':['zzlab-stage-motion-v2']})
    def test_stage_top_fixing_screws_may_be_covered_but_other_rules_remain(self):
        from layout import validate_layout
        top=self.c['registeredBoards'][0]
        fixing=dict(id='F1',xMm=13.5,yMm=12.5,type='counterbore',diameterMm=3.2,counterboreDiameterMm=6.5,counterboreDepthMm=2,usable=False)
        top['holesMm'].append(fixing);top['mountingHoleIds']=['F1']
        self.c['stageModules'][0]['topSurface']['holes'].append(copy.deepcopy(fixing))
        validate_catalog(self.c)
        self.path.write_text(json.dumps(self.c))
        for q in (0,1):
            with self.subTest(q=q):
                result=self.preview(plan(q))
                self.assertTrue(result['layoutValidation']['valid'],result['layoutValidation']['issues'])
                self.assertEqual(result['layout']['subBoards'][0]['board']['mountingHoles'],[{'holeId':'F1'}])
        p=plan();p['subBoards'][0]['yMm']+=1
        self.assertIn('stage_mounting_mismatch',{i['code'] for i in self.preview(p)['layoutValidation']['issues']})
        p=plan();p['instances'][0]['xMm']=25
        self.assertIn('mounting_mismatch',{i['code'] for i in self.preview(p)['layoutValidation']['issues']})
        p=plan();p['instances'][0]['xMm']=-5
        self.assertIn('out_of_bounds',{i['code'] for i in self.preview(p)['layoutValidation']['issues']})
        p=plan();p['subBoards'][0]['board']['mountingHoles']=[{'holeId':'T12.5-12.5'}]
        with self.assertRaises(APIError):self.preview(p)
        # The exact same cover on an ordinary board must still be rejected.
        top['stageOnly']=False;self.path.write_text(json.dumps(self.c))
        p=plan();child={k:v for k,v in p['instances'][0].items() if k!='boardId'}
        v=validate_layout({'board':p['subBoards'][0]['board'],'instances':[child]}, {k['id']:k for k in self.c['kits']})[2]
        self.assertIn('mounting_hole_obstructed',{i['code'] for i in v['issues']})
        self.assertFalse(rb.allows_covered_mounting({'stageOnly':True}))

    def test_current_catalog_all_stage_tops_and_no_ordinary_boards_allow_cover(self):
        c=json.loads((Path(__file__).resolve().parents[1]/'catalog.json').read_text())
        stage_ids={m['runtime']['topBoardId'] for m in c['stageModules']}
        self.assertEqual(len(c['stageModules']),7)
        for row in c['registeredBoards']:
            b=dict(registeredBoardId=row['id'],registeredBoardRevision=row['revision'])
            self.assertEqual(rb.allows_covered_mounting(b,c),row['id'] in stage_ids)

    def test_quarter_rotations_and_working_limits_preserve_fixed_mounting_and_child_motion(self):
        for angle in (0,90,180,270):
            reports=[]
            for q in (-3,0,1,3):
                p=plan(q,angle);preview=self.preview(p);v=preview['layoutValidation'];self.assertTrue(v['valid'],v['issues'])
                r=v['stageModules'][0];self.assertEqual(r['fixedPose'],dict(xMm=200,yMm=200,rotationDeg=angle))
                self.assertTrue(r['centerGridAligned']);self.assertEqual(r['currentGridAligned'],q==0)
                self.assertEqual(v['axisHeights'][0]['effectiveAxisHeightMm'],100)
                self.assertEqual(v['axisHeights'][0]['boardThicknessMm'],8.5)
                self.assertEqual(v['axisHeights'][0]['stageHeightOffsetMm'],29)
                world=global_instance(p['instances'][0],{'s1':p['subBoards'][0]});dx,dy=rotate(-12.5+q,-12.5,angle)
                self.assertEqual((world['xMm'],world['yMm']),(200+dx,200+dy));reports.append(r)
            self.assertTrue(all(r['mountingAlignment']==reports[0]['mountingAlignment'] for r in reports))
    def test_limit_unknown_revision_and_board_forgery_rejected(self):
        for mutate,code in [(lambda p:p['stageMotion'].update(qMm=3.1),'stage_travel_out_of_range'),(lambda p:p['stageMotion'].update(qMm=float('nan')),'stage_travel_out_of_range'),(lambda p:p['stageMotion'].update(revision='R0'),'stage_module_changed'),(lambda p:p['stageMotion'].update(moduleId='fake'),'unknown_stage_module'),(lambda p:p['stageMotion'].update(fixedX=2),'invalid_stage_motion'),(lambda p:p.pop('stageMotion'),'stage_module_required')]:
            layout=plan();mutate(layout['subBoards'][0])
            with self.subTest(code=code),self.assertRaises(APIError) as error:self.preview(layout)
            self.assertEqual(error.exception.code,code)
    def test_displacement_off_mother_grid_is_valid_but_moving_base_is_not(self):
        p=plan(1);self.assertTrue(self.preview(p)['layoutValidation']['valid'])
        p['subBoards'][0]['yMm']+=1
        codes={i['code'] for i in self.preview(p)['layoutValidation']['issues']};self.assertIn('stage_mounting_mismatch',codes);self.assertNotIn('sub_board_no_overlap',codes)
    def test_children_only_use_real_threaded_holes(self):
        p=plan();p['instances'][0]['xMm']=25
        self.assertIn('mounting_mismatch',{i['code'] for i in self.preview(p)['layoutValidation']['issues']})
    def test_owned_child_legal_external_keepout_and_sweep(self):
        p=plan();self.assertTrue(self.preview(p)['layoutValidation']['valid'])
        p['instances'].append(dict(id='outside',kitId='alpha',xMm=162.5,yMm=200,rotationDeg=0))
        self.assertIn('stage_keepout_collision',{i['code'] for i in self.preview(p)['layoutValidation']['issues']})
        b=world_bodies(plan(-3)['subBoards'][0],True);c=world_bodies(plan(3)['subBoards'][0],True)
        self.assertEqual(b,c);self.assertAlmostEqual(next(x for x in b if x['frame']=='moving')['xMin'],171.75)
    def test_stage_bom_once_and_real_top_thickness_retained(self):
        p=plan(child=False);preview=self.preview(p)
        rows={r['componentId']:r for r in preview['manufacturing']+preview['standard']}
        self.assertEqual(rows['plate']['quantity'],1);self.assertEqual(rows['bracket']['quantity'],1);self.assertEqual(rows['bolt']['quantity'],4)
        self.assertFalse(any(r.get('registeredBoard') for r in rows.values()))
        self.assertEqual(preview['totals']['stageModules'],1);self.assertEqual(preview['totals']['boards'],2)
        explicit=aggregate(self.c,{'layout':p,'requires':['zzlab-stage-motion-v2'],'items':[{'kitId':'stage-synthetic','quantity':1}]})
        self.assertEqual(next(r['quantity'] for r in explicit['manufacturing'] if r['componentId']=='plate'),1)
        q=copy.deepcopy(p['subBoards'][0]);q.update(id='s2',xMm=375);p['subBoards'].append(q)
        rows={r['componentId']:r for r in self.preview(p)['manufacturing']+self.preview(p)['standard']};self.assertEqual(rows['plate']['quantity'],2)
    def test_capability_is_required_and_complete_project_preserved(self):
        p=project();p.update(layout=plan(),requires=['zzlab-stage-motion-v2']);p['ui']['selectedIds']=[]
        payload=project_payload(p,self.c);self.assertEqual(payload['layout']['subBoards'][0]['stageMotion'],p['layout']['subBoards'][0]['stageMotion'])
        del p['requires']
        with self.assertRaises(APIError) as error:project_payload(p,self.c)
        self.assertEqual(error.exception.code,'stage_capability_required')
    def test_root_stage_top_and_unmarked_capability_cannot_degrade_to_static(self):
        p=plan(child=False)
        with self.assertRaises(APIError) as error:aggregate(self.c,{'layout':p})
        self.assertEqual(error.exception.code,'stage_capability_required')
        with self.assertRaises(APIError) as error:self.preview({'board':p['subBoards'][0]['board'],'instances':[]})
        self.assertEqual(error.exception.code,'stage_module_required')
    def test_per_stage_extras_multiply_and_survive_project_roundtrip(self):
        p=plan(child=False);second=copy.deepcopy(p['subBoards'][0]);second.update(id='s2',xMm=375);p['subBoards'].append(second)
        extra=dict(id='stage-screw-extra',kitId='stage-synthetic',kind='standard',name='测试附加件',model='TEST-M4',quantity=3,unit='个',notes='')
        result=aggregate(self.c,{'layout':p,'requires':['zzlab-stage-motion-v2'],'extras':[extra]})
        self.assertEqual(next(r['quantity'] for r in result['standard'] if r['model']=='TEST-M4'),6)
        self.assertEqual(next(r['quantity'] for r in result['manufacturing'] if r['componentId']=='plate'),2)
        saved=project();saved.update(layout=p,extras=[extra],requires=['zzlab-stage-motion-v2']);saved['ui']['selectedIds']=[]
        payload=project_payload(saved,self.c);self.assertEqual(payload['extras'],[extra])
        self.assertEqual(next(r['quantity'] for r in aggregate(self.c,payload)['standard'] if r['model']=='TEST-M4'),6)
    def test_catalog_runtime_rejects_broken_mappings(self):
        for mutate in [lambda m:m['runtime']['fixedTopView'].update(widthMm=0),lambda m:m['runtime']['movingTopView'].update(anchorXMm=float('inf')),lambda m:m['runtime']['baseBoundsMm'].update(xMax=float('nan')),lambda m:m['motion'].update(maxMm=float('inf')),lambda m:m['topSurface']['holes'][0].update(xMm=25),lambda m:m['bom'][0].update(quantity=2)]:
            c=copy.deepcopy(self.c);mutate(c['stageModules'][0])
            with self.assertRaises(APIError):validate_catalog(c)
    def test_no_autodrill_on_catalog_lower_interface(self):
        with self.assertRaises(APIError) as error:choose_mounting_holes(self.c,{'layout':plan(),'boardId':'s1'})
        self.assertEqual(error.exception.code,'stage_fixed_holes')
        self.assertEqual(choose_mounting_holes(self.c,{'layout':plan(),'boardId':'all'})['boards'],[])
        p=plan(child=False);p['baseMode']='table';p['subBoards'].append(dict(id='ordinary',name='普通板',board=board(100,100),xMm=375,yMm=50,rotationDeg=0))
        chosen=choose_mounting_holes(self.c,{'layout':p,'boardId':'all'})
        self.assertEqual([b['boardId'] for b in chosen['boards']],['ordinary']);self.assertEqual(chosen['skippedBoardIds'],['s1'])
    def test_cart_snapshot_export_is_independent_of_current_canvas(self):
        from cart import CartStore
        from shared_kits import Identity, SharedKitStore
        p=plan(1,child=False);p['baseMode']='table'
        store=CartStore(SharedKitStore(self.root/'cart.sqlite3'));user=Identity('stage-test','测试','user')
        initial=store.read(user)
        data={k:initial[k] for k in ('cartId','revision')}
        saved=store.add(user,{**data,'name':'位移台','requestId':'moving-stage-test-001','payload':{'layout':p,'requires':['zzlab-stage-motion-v2']}},self.c)
        p['subBoards'].clear()
        reread=store.read(user)
        snapshot=reread['preview']['cartSources'][0]
        self.assertEqual(snapshot['layout']['subBoards'][0]['stageMotion']['qMm'],1)
        self.assertEqual(reread['preview']['totals']['boards'],1)
        self.assertEqual(snapshot['layoutValidation']['stageModules'][0]['fixedPose']['xMm'],200)
        data,_,_=export_result(reread['preview'],'manufacturing',self.root)
        self.assertIn('位移模块安装参考',load_workbook(io.BytesIO(data)).sheetnames)
    def test_fixed_base_bounds_and_moving_top_overhang(self):
        p=plan(3,child=False);p['baseMode']='table';p['board']['widthMm']=225
        self.assertNotIn('sub_board_out_of_bounds',{i['code'] for i in self.preview(p)['layoutValidation']['issues']})
        p['subBoards'][0]['xMm']+=1
        self.assertIn('sub_board_out_of_bounds',{i['code'] for i in self.preview(p)['layoutValidation']['issues']})
    def test_empty_stage_can_be_shared_as_a_complete_module(self):
        p=project();p.update(layout=plan(child=False),requires=['zzlab-stage-motion-v2']);p['ui']['selectedIds']=[]
        self.assertEqual(prepare_project(p,self.c)['totals']['stageModules'],1)
    def test_export_shows_fixed_interface_and_z_and_layered_topview(self):
        preview=self.preview(plan(1));data,_,_=export_result(preview,'manufacturing',self.root)
        wb=load_workbook(io.BytesIO(data),data_only=True);self.assertIn('位移模块安装参考',wb.sheetnames)
        cells=[v for row in wb['位移模块安装参考'].values for v in row]
        self.assertIn('stage-synthetic',cells);self.assertIn(37.5,cells)
        (self.root/'topviews').mkdir();(self.root/'topviews/test.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        svg=layout_svg(preview,self.root).decode();self.assertIn('data-stage-layer="fixedTopView"',svg);self.assertIn('data-stage-layer="movingTopView"',svg)

if __name__=='__main__':unittest.main()
