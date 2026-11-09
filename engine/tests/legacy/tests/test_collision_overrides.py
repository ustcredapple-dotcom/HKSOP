"""User pair waivers persist without relaxing mounting or unrelated collision rules."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from bom import APIError, aggregate
from collision_overrides import CAPABILITY, MAX_OVERRIDES, permits, pair_keys
from cart import CartStore
from exports import export_result
from layout import choose_mounting_holes, validate_layout
from shared_kits import Identity, SharedKitStore, prepare_project, project_payload, shared_bundle, thumbnail_svg
from test_layout import layout_fixture
from test_shared_kits import project
from test_stacked_layout import board
from test_moving_stages import fixture as stage_fixture, plan as stage_plan


def fixture():
    c = layout_fixture()
    for kit in c['kits']:
        kit['layout'].update(
            baseBoundsMm=dict(xMin=-5,xMax=5,yMin=-5,yMax=5),
            collisionBoundsMm=dict(xMin=-15,xMax=15,yMin=-15,yMax=15),
            opticalAxisHeightMm=62.5)
    return c


def instance(iid, **changes):
    return dict(id=iid,kitId='alpha',xMm=100,yMm=100,rotationDeg=0) | changes


def plan():
    return dict(board=board(400,300),instances=[instance('b'),instance('a')])


def waive(layout, *pairs):
    layout['collisionOverrides'] = [dict(instanceIds=list(p)) for p in pairs]
    return layout


def payload(layout):
    return {'layout':layout,'requires':[CAPABILITY]}


class CollisionOverrideTests(unittest.TestCase):
    def setUp(self):
        self.c = fixture()
        self.kits = {k['id']:k for k in self.c['kits']}

    def codes(self, preview):
        return [i['code'] for i in preview['layoutValidation']['issues']]

    def test_precise_pair_is_normalized_not_mutated_and_bom_unchanged(self):
        p = plan(); before = aggregate(self.c, {'layout':p})
        self.assertIn('collision', self.codes(before))
        waive(p, ('b','a')); original = copy.deepcopy(p)
        result = aggregate(self.c,payload(p))
        self.assertTrue(result['layoutValidation']['valid'],result['layoutValidation']['issues'])
        self.assertEqual(result['layout']['collisionOverrides'],[{'instanceIds':['a','b']}])
        self.assertEqual(p, original)
        for category in ('items','manufacturing','lubang','standard','totals'):
            self.assertEqual(result[category], before[category])
        p['collisionOverrides'] = []
        self.assertIn('collision', self.codes(aggregate(self.c,{'layout':p})))

    def test_only_declared_pair_not_same_kit_or_transitive_pairs(self):
        p = waive(plan(),('a','b'));p['instances'].append(instance('c'))
        result = aggregate(self.c,payload(p))
        pairs = {frozenset(i['instanceIds']) for i in result['layoutValidation']['collisions']}
        self.assertEqual(pairs,{frozenset(('a','c')),frozenset(('b','c'))})
        p['collisionOverrides'].append({'instanceIds':['c','b']})
        result = aggregate(self.c,payload(p))
        self.assertEqual([set(i['instanceIds']) for i in result['layoutValidation']['collisions']],[{'a','c'}])

    def test_canonical_pair_order_is_stable_for_reordered_instances(self):
        p = waive(plan(),('b','a'),('d','c'));p['instances'] += [instance('d',xMm=200),instance('c',xMm=200)]
        expected=[{'instanceIds':['a','b']},{'instanceIds':['c','d']}]
        self.assertEqual(aggregate(self.c,payload(p))['layout']['collisionOverrides'],expected)
        p['instances'].reverse();p['collisionOverrides'].reverse()
        self.assertEqual(aggregate(self.c,payload(p))['layout']['collisionOverrides'],expected)

    def test_malformed_self_duplicate_dangling_board_and_limit_rejected(self):
        invalid=[None,{},True,[None],[{}],[{'instanceIds':'ab'}],[{'instanceIds':['a']}],
                 [{'instanceIds':['a','b','c']}],[{'instanceIds':['a','a']}],
                 [{'instanceIds':['a','missing']}],[{'instanceIds':['a',None]}],
                 [{'instanceIds':['a',{}]}],[{'instanceIds':['a','b'],'note':'free pass'}],
                 [{'instanceIds':['a','b']},{'instanceIds':['b','a']}],
                 [{'instanceIds':['a','b']}]*(MAX_OVERRIDES+1)]
        for value in invalid:
            p=plan();p['collisionOverrides']=value
            with self.subTest(value=str(value)[:90]), self.assertRaises(APIError) as caught:
                aggregate(self.c,payload(p))
            self.assertEqual(caught.exception.code,'invalid_collision_overrides')
        p=plan();p['subBoards']=[dict(id='small',name='小板',board=board(100,100),xMm=250,yMm=0,rotationDeg=0)]
        waive(p,('a','small'))
        with self.assertRaises(APIError) as caught:aggregate(self.c,payload(p))
        self.assertEqual(caught.exception.code,'invalid_collision_overrides')

    def test_capability_is_required_on_preview_project_and_hole_request(self):
        p=waive(plan(),('a','b'))
        for action in (lambda:aggregate(self.c,{'layout':p}),lambda:choose_mounting_holes(self.c,{'layout':p})):
            with self.assertRaises(APIError) as caught:action()
            self.assertEqual(caught.exception.code,'collision_overrides_capability_required')
        doc=project();doc['layout']=p
        with self.assertRaises(APIError) as caught:project_payload(doc,self.c)
        self.assertEqual(caught.exception.code,'collision_overrides_capability_required')
        for required in ([CAPABILITY,CAPABILITY],[CAPABILITY,'future'],CAPABILITY):
            with self.assertRaises(APIError) as caught:aggregate(self.c,{'layout':p,'requires':required})
            self.assertEqual(caught.exception.code,'unsupported_project_capability')
        p['collisionOverrides']=[]
        self.assertEqual(aggregate(self.c,{'layout':p})['layout']['collisionOverrides'],[])

    def test_mounting_bounds_height_and_obstruction_still_block(self):
        p=waive(plan(),('a','b'))
        p['instances'][0]['xMm']=100.1
        self.assertIn('mounting_mismatch',self.codes(aggregate(self.c,payload(p))))
        p['instances'][0]['xMm']=0
        self.assertIn('out_of_bounds',self.codes(aggregate(self.c,payload(p))))
        p=waive(plan(),('a','b'));p['instances'][0]['kitId']='beta'
        c=copy.deepcopy(self.c);c['kits'][1]['layout']['opticalAxisHeightMm']=75
        self.assertIn('axis_height_mismatch',self.codes(aggregate(c,payload(p))))
        p=waive(plan(),('a','b'))
        p['board']['mountingHoles']=[dict(columnIndex=x,rowIndex=y) for x in (0,2) for y in (0,2)]
        for i in p['instances']:i.update(xMm=12.5,yMm=12.5)
        result=aggregate(self.c,payload(p));self.assertNotIn('collision',self.codes(result))
        self.assertIn('mounting_hole_obstructed',self.codes(result))
        with self.assertRaises(APIError) as caught:export_result(result,'lubang',Path('/nonexistent'))
        self.assertEqual(caught.exception.code,'layout_invalid')

    def test_cross_board_pair_waived_but_board_instance_and_board_overlap_remain(self):
        p=waive(plan(),('a','b'));p['baseMode']='table'
        p['subBoards']=[dict(id='small',name='小板',board=board(200,150),xMm=0,yMm=0,rotationDeg=0)]
        p['instances'][0]['boardId']='small'
        # Root and child occupy same world XY; their height mismatch also remains.
        result=aggregate(self.c,payload(p));collisions=result['layoutValidation']['collisions']
        self.assertFalse(any(len(i['instanceIds'])==2 for i in collisions))
        self.assertTrue(any(i['code']=='collision' and i['instanceIds']==['a'] for i in collisions))
        other=copy.deepcopy(p['subBoards'][0]);other.update(id='other',name='第二板',xMm=50);p['subBoards'].append(other)
        self.assertIn('sub_board_collision',self.codes(aggregate(self.c,payload(p))))
        keys=pair_keys({'collisionOverrides':[{'instanceIds':['a','b']}]})
        for code,ids in [('stage_keepout_collision',['a','b']),('sub_board_collision',['a','b']),('collision',['a']),('collision',['a','b','c'])]:
            self.assertFalse(permits(code,ids,keys))

    def test_cross_subboard_pair_and_local_pair_are_projected_independently(self):
        p=waive(plan(),('a','b'),('b','c'));p['baseMode']='table'
        p['subBoards']=[dict(id='s1',name='第一板',board=board(200,150),xMm=0,yMm=0,rotationDeg=0),
                        dict(id='s2',name='第二板',board=board(200,150),xMm=0,yMm=0,rotationDeg=0)]
        p['instances'][0]['boardId']='s1';p['instances'][1]['boardId']='s2'
        p['instances'].append(instance('c',boardId='s1'))
        result=aggregate(self.c,payload(p))
        pairs=[set(i['instanceIds']) for i in result['layoutValidation']['collisions'] if len(i['instanceIds'])==2]
        self.assertEqual(pairs,[{'a','c'}])
        self.assertEqual(len(result['layout']['collisionOverrides']),2)

    def test_stage_capability_coexists_and_stage_keepout_not_waived(self):
        c=stage_fixture();p=stage_plan()
        p['instances'].append(instance('outside',xMm=187.5,yMm=187.5))
        waive(p,('a1','outside'))
        requirements=['zzlab-stage-motion-v2',CAPABILITY]
        result=aggregate(c,{'layout':p,'requires':requirements})
        self.assertEqual(result['requires'],requirements)
        self.assertNotIn('collision',self.codes(result))
        self.assertIn('stage_keepout_collision',self.codes(result))
        with self.assertRaises(APIError) as caught:aggregate(c,payload(p))
        self.assertEqual(caught.exception.code,'stage_capability_required')

    def test_four_and_eight_hole_derived_validation_preserves_waiver(self):
        for count in (4,8):
            p=waive(plan(),('a','b'));original=copy.deepcopy(p)
            chosen=choose_mounting_holes(self.c,{**payload(p),'holeCount':count})
            self.assertEqual(len(chosen['mountingHoles']),count)
            self.assertTrue(chosen['layoutValidation']['valid'],chosen['layoutValidation']['issues'])
            self.assertEqual(p,original)
            p['board']=chosen['board']
            self.assertTrue(aggregate(self.c,payload(p))['layoutValidation']['valid'])

    def test_stacked_choose_holes_keeps_local_waivers_without_dangling_cross_pairs(self):
        p=waive(plan(),('a','b'),('a','remote'));p['baseMode']='table'
        p['subBoards']=[dict(id='s1',name='第一板',board=board(200,150),xMm=0,yMm=0,rotationDeg=0)]
        for i in p['instances']:i.update(boardId='s1',xMm=100,yMm=75)
        p['instances'].append(instance('remote',xMm=300,yMm=200,elevationMm=12.7))
        for count in (4,8):
            chosen=choose_mounting_holes(self.c,{**payload(p),'boardId':'s1','holeCount':count})['boards'][0]
            self.assertTrue(chosen['layoutValidation']['valid'],chosen['layoutValidation']['issues'])
            self.assertEqual(len(chosen['mountingHoles']),count)
        self.assertEqual(len(p['collisionOverrides']),2)

    def test_project_sharing_cart_and_bundle_roundtrip(self):
        p=waive(plan(),('b','a'));p['baseMode']='table'
        doc=project();doc.update(layout=p,requires=[CAPABILITY]);doc['ui']['selectedIds']=[]
        saved=project_payload(doc,self.c);preview=prepare_project(doc,self.c)
        expected=[{'instanceIds':['a','b']}]
        self.assertEqual(saved['layout']['collisionOverrides'],expected)
        data,_,_=export_result(preview,'layout-json',Path('/nonexistent'))
        exported=json.loads(data);self.assertEqual(exported['requires'],[CAPABILITY]);self.assertEqual(exported['layout']['collisionOverrides'],expected)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);assets=root/'assets';assets.mkdir();static=root/'static';(static/'topviews').mkdir(parents=True)
            (static/'topviews/test.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            for name in ('plate','bracket'):
                (assets/(name+'.step')).write_text('ISO-10303-21; TEST')
                (assets/(name+'.pdf')).write_text('%PDF-TEST')
            bundle,_,_=export_result(preview,'bundle',assets,static,catalog=self.c)
            with zipfile.ZipFile(io.BytesIO(bundle)) as z:
                config=json.loads(z.read('套件配置.json'));self.assertEqual(config['requires'],[CAPABILITY]);self.assertEqual(config['layout']['collisionOverrides'],expected)
            store=SharedKitStore(root/'shared.sqlite3');user=Identity('waiver-qa','隔离验收','user')
            thumbnail=thumbnail_svg(preview,static,catalog=self.c)
            published=store.publish('碰撞豁免验收','仅测试',doc,thumbnail,user)
            shared=store.get(published['kit']['id'],user)
            restored=json.loads(shared['project_json']);self.assertEqual(project_payload(restored,self.c),saved)
            shared_zip,_,_=shared_bundle(shared,self.c,assets,static)
            with zipfile.ZipFile(io.BytesIO(shared_zip)) as z:
                self.assertEqual(json.loads(z.read('共享套件工程.zzoptics.json'))['requires'],[CAPABILITY])
            cart=CartStore(store);initial=cart.read(user)
            added=cart.add(user,{**{k:initial[k] for k in ('cartId','revision')},'name':'人工豁免','requestId':'waiver-cart-1','payload':saved},self.c)
            p['instances'].clear();p['collisionOverrides'].clear()
            reread=cart.read(user)['preview'];source=reread['cartSources'][0]
            self.assertEqual(source['layout']['collisionOverrides'],expected);self.assertEqual(source['requires'],[CAPABILITY])
            cart_zip,_,_=export_result(reread,'bundle',assets,static,catalog=self.c)
            with zipfile.ZipFile(io.BytesIO(cart_zip)) as z:
                source=json.loads(z.read('套件配置.json'))['cartSources'][0]
                self.assertEqual(source['layout']['collisionOverrides'],expected)
                self.assertEqual(source['requires'],[CAPABILITY])


if __name__=='__main__':unittest.main()
