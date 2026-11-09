"""Stable R3 kit IDs now backed by the supplied R6 machining revision."""
from collections import Counter
import copy
import io
import json
import os
from pathlib import Path
import sys
import unittest
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bom import aggregate,load_catalog
from cart import combine,export_preview,rows
from exports import export_result
from qa.register_manufacturing_r6 import MAP,build_catalog,digest,load
from qa.register_new_kits_r3 import IDS
E=ROOT/'data_evidence/manufacturing-r6-2026-10-04'
class NewKitsR3Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.raw=load(Path(os.environ.get('R6_CATALOG_PATH',ROOT/'catalog.json')));cls.catalog=load_catalog(Path(os.environ.get('R6_CATALOG_PATH',ROOT/'catalog.json')))
  cls.kits={k['id']:k for k in cls.catalog['kits']};cls.components={c['id']:c for c in cls.catalog['components']}
  cls.old=load(E/'catalog-before.json');cls.audit=load(ROOT/'data_evidence/new-kits-2026-10-04/bom-audit.json')
  cls.sources={k['kitId']:k for k in cls.audit['kits']}
 def result(self,kid,qty=1,extras=None):return aggregate(self.catalog,dict(items=[dict(kitId=kid,quantity=qty)],extras=extras or []))
 def test_existing_non_supplemental_kits_and_post_process_specs_are_preserved(self):
  current={k['id']:k for k in self.raw['kits']}
  for kit in self.old['kits']:
   if not kit['id'].startswith('new-'):self.assertEqual(current[kit['id']],kit,kit['id'])
  for old in self.old['components']:
   if old['id'].startswith('custom-'):self.assertEqual(self.components[old['id']],old,old['id'])
  self.assertEqual(self.raw['registeredBoards'],self.old['registeredBoards'])
 def test_registration_is_idempotent_for_manufacturing_slice(self):
  c,_,report=build_catalog(self.raw,'2ed7fb2849af8aa467c0db11')
  by={x['id']:x for x in c['components']}
  for cid in MAP.values():self.assertEqual(by[cid],self.components[cid],cid)
  self.assertEqual(report['registeredCustomParts'],24)
  for kit in c['kits']:
   if kit['id'] in IDS:self.assertEqual(kit['components'],self.kits[kit['id']]['components'])
 def test_twelve_previews_and_manufacturing_pairs_use_r6(self):
  for kid in IDS:
   with self.subTest(kit=kid):
    kit=self.kits[kid];l=kit['layout'];ev=l['geometryEvidence']
    self.assertEqual(kit['manufacturingRevision'],'R6');self.assertEqual(kit['bundleStatus'],'complete')
    self.assertEqual(digest(ev['sourceStep']),ev['sourceSha256'])
    self.assertEqual(digest(ROOT/'static'/l['topViewPath']),ev['imageSha256'])
    for ref in kit['components']:
     c=self.components[ref['componentId']]
     if c['id'] in MAP.values():
      self.assertTrue(c['drawingPath']);self.assertTrue(c['dxfPath']);self.assertFalse(c['productionReady'])
      self.assertEqual(digest(ROOT/'assets'/c['stepPath']),c['sourceStepSha256'])
 def test_whole_commercial_models_stay_and_old_special_fasteners_are_not_ordered(self):
  for kid in IDS:
   with self.subTest(kit=kid):
    r=self.result(kid,3);src=self.sources[kid]
    self.assertEqual(Counter({x['model']:x['quantity'] for x in r['lubang']}),Counter({p['model']:p['quantity']*3 for p in src['vendorParts']}))
    self.assertEqual(r['standard'],[])
    if src.get('post'):
     post,=[x for x in r['manufacturing'] if x['componentId']==src['post']['catalogComponentId']]
     self.assertEqual(post['quantity'],3)
    self.assertEqual(r['lubangImport']['blocked'],[])
 def test_optical_replacements_do_not_duplicate_included_crystals(self):
  for kid in IDS:
   src=self.sources[kid]
   if not src.get('opticalModel'):continue
   slot,=self.kits[kid]['opticalSlots']
   extra=dict(id='chosen',kitId=kid,slotId='optic',name='替换光学片',kind='lubang',model=src['opticalModel'],quantity=1,unit=slot['unit'],inserted=True,supplier='麓邦')
   r=self.result(kid,3,[extra]);self.assertEqual([x['quantity'] for x in r['lubang'] if x['model']==src['opticalModel']],[3])
   self.assertFalse(any(x['componentId']==slot['replacesComponentId'] for x in rows(r)))
 def test_shared_parts_merge_and_r6_part_processes_override_only_their_scope(self):
  r=aggregate(self.catalog,dict(items=[dict(kitId=k,quantity=1) for k in IDS]));by={x['componentId']:x for x in r['manufacturing']}
  self.assertEqual(by['new-r3-13-14-common-target']['quantity'],3)
  for n in (16,17,18,19):self.assertEqual(by[f'new-r3-{n}-r3-adapter']['quantity'],2)
  self.assertEqual(by['custom-02']['quantity'],9)
  for cid in MAP.values():
   c=self.components[cid];self.assertEqual(c['manufacturingSpec']['material'],'316L 不锈钢');self.assertEqual(c['manufacturingSpec']['surfaceTreatment'],'去磁、钝化')
  self.assertEqual(self.components['custom-02']['manufacturingSpec']['surfaceTreatment'],'退磁、喷砂')
 def test_board_reference_is_not_manufactured_and_mounting_phase_remains_real(self):
  r=self.result('new-board-target');self.assertEqual(len(r['manufacturing']),2);self.assertEqual(sorted(x['quantity'] for x in r['manufacturing']),[2,2])
  l=self.kits['new-board-target']['layout'];self.assertEqual(l['geometryEvidence']['excludedReferenceCount'],1)
  self.assertEqual({(p['xMm'],p['yMm']) for p in l['mountingHoleOffsetsMm']},{(0,-6.25),(0,6.25),(50,-6.25),(50,6.25)})
  for pitch,expected in ((12.5,4),(25,2)):
   board=dict(widthMm=500,heightMm=500,pitchMm=pitch,edgeOffsetMm=12.5,thicknessMm=12.7,holeType='M6_through')
   inst=dict(id='tool',kitId='new-board-target',xMm=212.5,yMm=206.25,rotationDeg=0)
   p=aggregate(self.catalog,dict(layout=dict(board=board,instances=[inst])));a,=p['layoutValidation']['mountingAlignment']
   self.assertEqual(a['alignedCount'],expected);self.assertEqual(p['layoutValidation']['valid'],pitch==12.5)
 def test_complete_cart_exports_current_docs_and_deselection_still_removes_parts(self):
  previews=[self.result('new-lens-filter-2inch'),self.result('pbs-fixed')]
  state=dict(sources=[dict(id=f's{i}',name=f'方案{i}',createdAt='2026-10-04',preview=p) for i,p in enumerate(previews)],choices={})
  combined,_=combine(state);state['choices']={r['componentId']:dict(quantity=r['quantity'],selected=True,removed=False) for r in rows(combined)}
  data,_,_=export_result(export_preview(state,self.catalog),'bundle',ROOT/'assets',ROOT/'static')
  with zipfile.ZipFile(io.BytesIO(data)) as z:self.assertEqual(sum(n.endswith('.dxf') for n in z.namelist()),1)
  for row in combined['manufacturing']:
   if row['sourceComponentId']=='new-r3-16-r3-adapter':state['choices'][row['componentId']]['selected']=False
  data,_,_=export_result(export_preview(state,self.catalog),'bundle',ROOT/'assets',ROOT/'static')
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   config=json.loads(z.read('套件配置.json'));self.assertFalse(any(c['sourceComponentId']=='new-r3-16-r3-adapter' for c in config['components']))
   self.assertFalse(any(n.endswith('.dxf') for n in z.namelist()))
   self.assertTrue(any(c.get('model')=='FLFT2A' for c in config['components']))
if __name__=='__main__':unittest.main()
