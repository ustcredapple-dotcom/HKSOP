"""Support migration changes physical height references, never layout/optic identity."""
import copy
import json
from pathlib import Path
import unittest
from metric_migration import migrate,CAPABILITY
from bom import load_catalog,aggregate,APIError
from shared_kits import project_payload
from test_shared_kits import project
ROOT=Path(__file__).resolve().parents[1]

def example():
 p=project();p.update(catalogVersion='before-metric',catalogReferenced=[])
 p['layout']={'baseMode':'table','board':{'widthMm':900,'heightMm':450,'pitchMm':12.5,'edgeOffsetMm':12.5,'thicknessMm':12.7},'instances':[{'id':'optic','kitId':'pbs-fixed','xMm':100,'yMm':112.5,'rotationDeg':90,'elevationMm':25.4,'universalPostSelection':{'custom-01':'custom-03'}}]};p['ui']['selectedIds']=['optic'];return p

class MetricDefaultTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.catalog=load_catalog(ROOT/'catalog.json')
 def test_equivalent_posts_once_without_mutating_source(self):
  p=example();original=copy.deepcopy(p);q,changes=migrate(p,self.catalog);self.assertEqual(p,original)
  i=q['layout']['instances'][0];self.assertEqual(i['universalPostSelection'],{'custom-post-metric-25mm-m1':'custom-post-metric-37p5mm-m1'});self.assertEqual(i['elevationMm'],25);self.assertEqual(q['layout']['board']['thicknessMm'],12.5)
  for field in ('xMm','yMm','rotationDeg','id','kitId'):self.assertEqual(i[field],p['layout']['instances'][0][field])
  self.assertEqual(migrate(q,self.catalog),(q,[]));self.assertIn(CAPABILITY,q['requires'])
  preview=aggregate(self.catalog,project_payload(p,self.catalog));self.assertEqual(preview['layoutValidation']['axisHeights'][0]['effectiveAxisHeightMm'],100)
  # The current system replaces the explicitly selected post; legacy elevation
  # is no longer converted into additional post length (allow_elevation=False).
  self.assertEqual(preview['universalPostReplacements'][0]['replacementComponentId'],'custom-post-metric-37p5mm-m1')
 def test_modern_user_dimensions_lasers_and_child_lifts_not_scaled(self):
  p=example();p['requires']=[CAPABILITY];p['layout']['instances'][0].pop('universalPostSelection');q,c=migrate(p,self.catalog);self.assertEqual(q,p);self.assertFalse(c)
  p=example();i=p['layout']['instances'][0];i.update(kitId='laser-308nm',elevationMm=25.4);i.pop('universalPostSelection');p['layout']['board']['registeredBoardId']='source-board';q,c=migrate(p,self.catalog);self.assertEqual(q['layout']['instances'],p['layout']['instances']);self.assertEqual(q['layout']['board']['thicknessMm'],12.7)
  p=example();p['layout']['instances'][0]['boardId']='small';q,c=migrate(p,self.catalog);self.assertEqual(q['layout']['instances'][0]['elevationMm'],25.4)
 def test_invalid_requires_and_conflicting_keys_still_rejected(self):
  for bad in (None,'x',[1]):
   p=example();p['requires']=bad;self.assertEqual(migrate(p,self.catalog),(p,[]))
   with self.assertRaises(APIError):project_payload(p,self.catalog)
  p=example();p['layout']['instances'][0]['universalPostSelection']['custom-post-metric-25mm-m1']='custom-post-metric-25mm-m1';self.assertEqual(migrate(p,self.catalog),(p,[]))
  with self.assertRaises(APIError):project_payload(p,self.catalog)
 def test_only_metric_series_is_available_and_no_active_bom_uses_old_posts(self):
  s=self.catalog['universalPostSeries'];self.assertEqual([p['heightMm'] for p in s['posts']],[12.5*i for i in range(1,13)])
  for k in self.catalog['kits']:
   self.assertFalse(set(s['metricMigration']['componentMap'])&{i['componentId'] for i in k['components']},k['id'])
  for k in self.catalog['kits']:
   if k['id'] in ('pbs-fixed','pbs-adjustable','waveplate','motor-1-45','motor-05-45','fiber-coupling','new-aom'):self.assertEqual(k['layout']['opticalAxisHeightMm'],62.5,k['id'])
if __name__=='__main__':unittest.main()
