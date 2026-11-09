"""R6 current versions of the first eight modules, including paired drawings."""
from collections import Counter
import hashlib
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
from exports import export_result
from qa.register_manufacturing_r6 import MAP,CODES,POSTS,KIT_MODULES,sources_by_kit

E=ROOT/'data_evidence/manufacturing-r6-2026-10-04'
KIT_IDS=('new-waveplate-single','new-pbs-05','new-pd','new-lens-filter','new-iris','new-beam-dump','new-aom','new-isolator')
EXPECTED_VENDOR_MODELS={
 'new-waveplate-single':{'CRM-1AS':1,'HWP25-532A':1},'new-pbs-05':{'PCMS05':1,'PBS22-532':1},
 'new-pd':{'DETS36-25M':1},'new-lens-filter':{'FLFT1A':1,'BCX10613-A':1},'new-iris':{'CSD20':1},
 'new-beam-dump':{'LBT1':1},'new-aom':{'AMP-1R':1,'待确认':1},
 'new-isolator':{'ISOC1':1,'ISO780-3-1.5W':1}}
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

class NewKitsCatalogTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.catalog=load_catalog(Path(os.environ.get('R6_CATALOG_PATH',ROOT/'catalog.json')))
  cls.kits={x['id']:x for x in cls.catalog['kits']};cls.components={x['id']:x for x in cls.catalog['components']}
  cls.sources=sources_by_kit()
 def result(self,kid,quantity=1,extras=None):
  return aggregate(self.catalog,dict(items=[dict(kitId=kid,quantity=quantity)],extras=extras or []))
 def test_eight_existing_ids_survive_the_r6_revision(self):
  for kid in KIT_IDS:
   with self.subTest(kit=kid):
    self.assertEqual(sum(k['id']==kid for k in self.catalog['kits']),1)
    self.assertEqual(self.kits[kid]['manufacturingRevision'],'R6')
    self.assertEqual(self.kits[kid]['bundleStatus'],'complete')
    self.assertTrue(self.kits[kid]['layout']['placementAllowed'])
 def test_r6_drawing_step_dxf_are_a_single_frozen_revision(self):
  for code,cid in MAP.items():
   with self.subTest(code=code):
    c=self.components[cid];ev=c['manufacturingEvidence']
    self.assertEqual(c['model'],code+'-R6')
    self.assertEqual(ev['pageCount'],3)
    self.assertEqual(digest(ROOT/'assets'/c['stepPath']),c['sourceStepSha256'])
    self.assertEqual(digest(ROOT/'assets'/c['drawingPath']),ev['drawingSha256'])
    self.assertEqual(digest(ROOT/'assets'/c['dxfPath']),ev['dxfSha256'])
    self.assertEqual(digest(ev['matchedLatestSource']['path']),c['sourceStepSha256'])
    self.assertFalse(c['productionReady']) # Full documents are not a physical production sign-off.
 def test_complete_bundles_include_registered_r6_drawings(self):
  for kid in KIT_IDS:
   with self.subTest(kit=kid):
    result=self.result(kid)
    self.assertFalse(any(x.get('blocking') for x in result['reviewGroups']))
    data,_,_=export_result(result,'bundle',ROOT/'assets',ROOT/'static')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
     names=archive.namelist();r6count=len(CODES[KIT_MODULES[kid]])
     self.assertEqual(sum(n.endswith('.dxf') for n in names),r6count)
     self.assertGreaterEqual(sum(n.endswith('.pdf') for n in names),r6count)
     self.assertGreaterEqual(sum(n.endswith('.step') for n in names),r6count)
 def test_layout_uses_current_r6_assembly_and_real_holes(self):
  layouts=json.loads((ROOT/'data_evidence/r6-2026-10-04/layouts.json').read_text())
  offsets={(-12.5,-12.5),(-12.5,12.5),(12.5,-12.5),(12.5,12.5)}
  for kid in KIT_IDS:
   with self.subTest(kit=kid):
    l=self.kits[kid]['layout'];ev=l['geometryEvidence']
    self.assertEqual(ev['sourceSha256'],self.sources[kid]['assembly']['sha256'])
    self.assertEqual(digest(ev['sourceStep']),ev['sourceSha256'])
    self.assertEqual(digest(ROOT/'static'/l['topViewPath']),ev['imageSha256'])
    for field in ('widthMm','heightMm','anchorXMm','anchorYMm','baseBoundsMm','collisionPolygonsMm','mountingHoleOffsetsMm'):
     self.assertEqual(l[field],layouts[kid][field])
    expected=offsets
    if kid=='new-beam-dump':expected=offsets|{(x+50,y) for x,y in offsets}
    if kid=='new-isolator':expected={(x-50,y) for x,y in offsets}|{(x+50,y) for x,y in offsets}
    self.assertEqual({(p['xMm'],p['yMm']) for p in l['mountingHoleOffsetsMm']},expected)
 def test_procurement_posts_and_hardware_follow_r6_assemblies(self):
  for kid in KIT_IDS:
   for multiplier in (1,3):
    with self.subTest(kit=kid,quantity=multiplier):
     r=self.result(kid,multiplier);post,qty=POSTS[KIT_MODULES[kid]]
     self.assertEqual(next(x['quantity'] for x in r['manufacturing'] if x['componentId']==post),qty*multiplier)
     self.assertEqual(Counter({x['model']:x['quantity'] for x in r['lubang']}),Counter({m:n*multiplier for m,n in EXPECTED_VENDOR_MODELS[kid].items()}))
     self.assertEqual(len(r['standard']),1 if kid=='new-aom' else 0)
     if kid=='new-aom':self.assertIn('导热',r['standard'][0]['name'])
     self.assertIn('螺钉',self.kits[kid]['optionalNotes'][0])
 def test_optical_choice_replaces_included_aom_or_current_isolator_once(self):
  for kid,chosen in [('new-aom','AOM20-532-100'),('new-isolator','ISO780-3-1.5W')]:
   slot,=self.kits[kid]['opticalSlots']
   extra=dict(id='choice',kitId=kid,slotId=slot['id'],name='已选光学元件',kind='lubang',model=chosen,quantity=1,unit='个',inserted=True,supplier='麓邦')
   r=self.result(kid,3,[extra]);self.assertFalse(any(x['componentId']==slot['replacesComponentId'] for x in r['lubang']))
   self.assertEqual([x['quantity'] for x in r['lubang'] if x['model']==chosen],[3])
   self.assertEqual(sum(x['quantity'] for x in r['lubang']),6)
   self.assertEqual(r['replacements'][0]['totalQuantity'],3)
 def test_legacy_isolator_models_are_preserved_but_never_mixed_into_new_bom(self):
  legacy={'new-isolator-adapter-1','new-isolator-adapter-2','new-isolator-vendor-1','new-isolator-vendor-2'}
  self.assertTrue(legacy<=self.components.keys())
  self.assertFalse(legacy&{x['componentId'] for x in self.kits['new-isolator']['components']})
  slot,=self.kits['new-isolator']['opticalSlots'];self.assertEqual(slot['allowedModels'],['ISO780-3-1.5W'])
if __name__=='__main__':unittest.main()
