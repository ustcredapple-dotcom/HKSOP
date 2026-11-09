"""Global post choices preserve geometry; uniform-height and riser synthesis are retired."""
import copy
import unittest
from pathlib import Path
from bom import load_catalog, aggregate
from elevation import axis_validation
from shared_kits import prepare_project

class GlobalHeightTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.catalog=load_catalog(Path(__file__).resolve().parents[1]/'catalog.json')
 def layout(self):
  return {'board':{'widthMm':350,'heightMm':225,'thicknessMm':12.5,'pitchMm':12.5,'edgeOffsetMm':12.5,'holeType':'M6_through','mountingHoles':[]},'instances':[{'id':'w','kitId':'waveplate','xMm':100,'yMm':100,'rotationDeg':0}]}
 def test_explicit_post_selection_produces_correct_bom(self):
  layout=self.layout();layout['instances'][0]['universalPostSelection']={'custom-post-metric-25mm-m1':'custom-post-metric-37p5mm-m1'};before=copy.deepcopy(layout)
  r=aggregate(self.catalog,{'layout':layout,'extras':[]})
  self.assertEqual(r['elevationAccessories'],[]);self.assertTrue(r['layoutValidation']['valid']);self.assertEqual(r['layoutValidation']['axisHeights'][0]['effectiveAxisHeightMm'],75)
  self.assertEqual(r['universalPostReplacements'][0]['replacementComponentId'],'custom-post-metric-37p5mm-m1')
  rows={p['componentId']:p for p in r['manufacturing']};self.assertEqual(rows['custom-post-metric-37p5mm-m1']['quantity'],1);self.assertNotIn('custom-post-metric-25mm-m1',rows);self.assertEqual(layout,before)
 def test_old_height_offsets_are_preserved_without_riser_purchase(self):
  layout=self.layout();layout['instances'][0]['elevationMm']=5.4;before=copy.deepcopy(layout);r=aggregate(self.catalog,{'layout':layout,'extras':[]})
  self.assertEqual(r['layout']['instances'][0]['elevationMm'],5.4);self.assertAlmostEqual(r['layoutValidation']['axisHeights'][0]['effectiveAxisHeightMm'],67.9)
  self.assertEqual(r['elevationAccessories'],[]);self.assertEqual(r['universalPostReplacements'],[]);self.assertFalse(any(i['code'] in ['axis_height_mismatch','universal_post_unavailable'] for i in r['layoutValidation']['issues']));self.assertEqual(before,layout)
 def test_unrelated_heights_do_not_block_layout(self):
  layout=self.layout();layout['instances'].append({'id':'x','kitId':'waveplate','xMm':225,'yMm':100,'rotationDeg':0,'universalPostSelection':{'custom-post-metric-25mm-m1':'custom-post-metric-50mm-m1'}})
  r=aggregate(self.catalog,{'layout':layout,'extras':[]});self.assertTrue(r['layoutValidation']['valid']);self.assertEqual([r['effectiveAxisHeightMm'] for r in r['layoutValidation']['axisHeights']],[62.5,87.5])

if __name__=='__main__':unittest.main()
