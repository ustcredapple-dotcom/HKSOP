"""Internal optical settings are bound to catalog surfaces, never source geometry or BOM."""
import copy
from pathlib import Path
import tempfile
import unittest

from bom import APIError, aggregate
from cart import CartStore
from layout import validate_layout
from optics_settings import normalize_internal_fields, normalize_optics
from shared_kits import Identity, SharedKitStore, project_payload
from stacked_layout import global_instance
from test_layout import layout_fixture
from test_stacked_layout import board


def settings():
    return {'lower-mirror':{'elementType':'mirror','inserted':True,'configured':True,'surfaceAngleDeg':45,
                            'mirror':{'mode':'data','model':'INTERNAL-MEASURED','samples':[{'wavelengthNm':532,'incidenceAngleDeg':45,'reflectanceP':.95,'reflectanceS':.99,'phaseDifferenceDeg':170}]},'source':{'enabled':False}}}


class InternalOpticsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.catalog=layout_fixture();self.kit=self.catalog['kits'][0]
        self.kit['layout']['opticalAssembly']={'verified':False,'internalElements':[{'id':'lower-mirror','name':'下镜','type':'mirror'},{'id':'side-dichroic','name':'侧镜','type':'mirror'}]}
        self.instance={'id':'a','kitId':self.kit['id'],'xMm':100,'yMm':75,'rotationDeg':0,'internalOptics':settings()}
        self.layout={'board':board(300,225),'instances':[self.instance]}

    def test_layout_and_shared_project_preserve_independent_internal_settings(self):
        preview=aggregate(self.catalog,{'layout':self.layout});saved=preview['layout']['instances'][0]['internalOptics']
        self.assertEqual(saved,settings())
        saved['lower-mirror']['mirror']['samples'][0]['reflectanceP']=.1
        self.assertEqual(self.instance['internalOptics'],settings())
        project={'format':'zzlab-optics-project','version':1,'metadata':{'name':'内部光路','notes':'','createdAt':'2026-10-04T00:00:00Z','updatedAt':'2026-10-04T00:00:00Z'},'catalogVersion':self.catalog['version'],
                 'layout':self.layout,'optical':{},'extras':[],'moduleQuantities':[],'ui':{'selectedIds':[],'view':None}}
        result=project_payload(project,self.catalog)
        self.assertEqual(result['layout']['instances'][0]['internalOptics'],settings())
        for row in preview['lubang']+preview['standard']+preview['manufacturing']:
            self.assertNotEqual(row['model'],'INTERNAL-MEASURED')

    def test_stacked_transform_preserves_ids_and_does_not_share_nested_data(self):
        layout={'baseMode':'table','board':board(600,450),'subBoards':[{'id':'p','name':'小板','board':board(300,225),'xMm':50,'yMm':50,'rotationDeg':90}],
                'instances':[{**self.instance,'boardId':'p'}]}
        local=aggregate(self.catalog,{'layout':layout})['layout']
        world=global_instance(local['instances'][0],{'p':local['subBoards'][0]})
        self.assertEqual(world['internalOptics'],settings())
        world['internalOptics']['lower-mirror']['inserted']=False
        self.assertTrue(local['instances'][0]['internalOptics']['lower-mirror']['inserted'])

    def test_unregistered_ids_types_recursive_data_and_independent_sources_are_rejected(self):
        invalid=[None,[],{'not-in-catalog':settings()['lower-mirror']},
                 {'lower-mirror':{'elementType':'pbs','inserted':True}},
                 {'lower-mirror':{'elementType':'mirror','inserted':True,'source':{'enabled':True}}},
                 {'lower-mirror':{'elementType':'mirror','inserted':True,'internalOptics':{}}},
                 {'lower-mirror':{'elementType':'mirror','inserted':True,'center':{'x':0,'y':0}}}]
        for value in invalid:
            with self.assertRaises(APIError):normalize_internal_fields({'internalOptics':value},self.kit)
        bare=copy.deepcopy(self.kit);bare['layout'].pop('opticalAssembly')
        with self.assertRaises(APIError):normalize_internal_fields({'internalOptics':{}},bare)
        self.assertEqual(normalize_internal_fields({},bare),{})

    def test_dichroic_nullable_exact_data_and_internal_coating_face_are_preserved(self):
        self.kit['layout']['opticalAssembly']['internalElements'][1]['type']='dichroic'
        sample={'wavelengthNm':532,'incidenceAngleDeg':45,'reflectanceP':.99,'reflectanceS':None,'transmittanceP':.005,'transmittanceS':None,'reflectionPhaseDifferenceDeg':None,'transmissionPhaseDifferenceDeg':None}
        config={'elementType':'dichroic','inserted':True,'coatingFaceIndex':None,'dichroic':{'mode':'data','model':'DM20-425SP','samples':[sample]}}
        clean=normalize_internal_fields({'internalOptics':{'side-dichroic':config}},self.kit)
        self.assertEqual(clean['internalOptics']['side-dichroic'],config)
        clean['internalOptics']['side-dichroic']['dichroic']['samples'][0]['reflectanceP']=.1
        self.assertEqual(sample['reflectanceP'],.99)
        for face in (False,True,-1,2,'0',.1):
            with self.assertRaises(APIError):normalize_internal_fields({'internalOptics':{'side-dichroic':{**config,'coatingFaceIndex':face}}},self.kit)
        with self.assertRaises(APIError):normalize_optics(config)
        for change in ({'reflectanceP':1.1},{'transmittanceP':.1},{'wavelengthNm':None},{'incidenceAngleDeg':float('nan')},{'reflectionPhaseDifferenceDeg':float('inf')}):
            invalid=copy.deepcopy(config);invalid['dichroic']['samples'][0].update(change)
            with self.assertRaises(APIError):normalize_internal_fields({'internalOptics':{'side-dichroic':invalid}},self.kit)
        empty={**config,'dichroic':{'mode':'data','samples':[]}}
        self.assertEqual(normalize_internal_fields({'internalOptics':{'side-dichroic':empty}},self.kit)['internalOptics']['side-dichroic'],empty)

    def test_account_cart_restart_keeps_internal_optics_without_new_order_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            database=Path(folder)/'cart.sqlite3';backup=Path(folder)/'backup.sqlite3'
            store=CartStore(SharedKitStore(database,backup));user=Identity('test-internal','测试','user');initial=store.read(user)
            added=store.add(user,{'cartId':initial['cartId'],'revision':initial['revision'],'requestId':'internal-optics-001','name':'内部光路','payload':{'layout':self.layout}},self.catalog)
            restarted=CartStore(SharedKitStore(database,backup));result=restarted.for_export(user,{'cartId':added['cartId'],'revision':added['revision']},self.catalog)
            self.assertEqual(result['cartSources'][0]['layout']['instances'][0]['internalOptics'],settings())
            expected=aggregate(self.catalog,{'layout':{**self.layout,'instances':[{k:v for k,v in self.instance.items() if k!='internalOptics'}]}})
            self.assertEqual(result['totals']['componentQuantity'],expected['totals']['componentQuantity'])


if __name__=='__main__':unittest.main()
