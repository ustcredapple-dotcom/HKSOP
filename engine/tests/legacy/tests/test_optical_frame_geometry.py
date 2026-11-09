"""Verify the published CAD extraction evidence without guessing thread types."""
import hashlib,json,math,unittest,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data_evidence/optical-frame-2026-10-04/extracted'
class ExtractedBoardGeometry(unittest.TestCase):
 def record(self,name):return json.loads((BASE/f'optical-frame-{name}.json').read_text())
 def test_verified_semantic_counts_and_physical_dimensions(self):
  cases={'middle':((200,350,23),{'thread':199,'clearance':12,'counterbore':4}),'down':((400,400,14),{'thread':469,'counterbore':12}),'for1':((1225,775,25),{'thread':1432,'clearance':214,'counterbore':16}),'for2':((1225,962.5,25),{'thread':1500,'clearance':208,'counterbore':20}),'for3':((1225,962.5,25),{'thread':1504,'clearance':208,'counterbore':20})}
  for name,(dims,counts)in cases.items():
   with self.subTest(board=name):
    d=self.record(name);self.assertTrue(d['registrationReady']);self.assertEqual(tuple(d[k]for k in['widthMm','heightMm','thicknessMm']),dims);self.assertEqual(d['audit']['holeCounts'],counts)
    self.assertEqual(len(set(h['id']for h in d['holesMm'])),len(d['holesMm']));self.assertEqual(d['mountingHoleIds'],[h['id']for h in d['holesMm']if h['type']=='counterbore'])
    for h in d['holesMm']:
     self.assertGreaterEqual(h['xMm'],0);self.assertLessEqual(h['xMm'],dims[0]);self.assertGreaterEqual(h['yMm'],0);self.assertLessEqual(h['yMm'],dims[1])
     if h['type']=='thread':self.assertEqual(h['thread'],'M6x1.0');self.assertEqual(h['diameterMm'],6);self.assertEqual(h['drillDiameterMm'],5);self.assertTrue(h['classificationEvidence'])
     if h['type']=='counterbore':self.assertEqual(h['counterboreDiameterMm'],11.25);self.assertEqual(h['counterboreDepthMm'],6)
 def test_dowel_difference_changes_only_expected_hole_volume(self):
  for name,count in [('middle',12),('for1',214),('for2',208),('for3',208)]:
   d=self.record(name);difference=d['audit']['threadDifference'];self.assertEqual(len(difference['removedDowelHoleIds']),count)
   expected=count*math.pi*2.5**2*d['thicknessMm'];self.assertAlmostEqual(difference['volumeIncreaseMm3'],expected,places=3)
   self.assertEqual(set(difference['removedDowelHoleIds']),{h['id']for h in d['holesMm']if h['type']=='clearance'})
 def test_opening_side_coordinate_mapping_is_right_handed(self):
  for name in ['middle','down','for1','for2','for3']:
   d=self.record(name);m=d['audit']['coordinateMapping'];self.assertTrue(m['rightHanded']);self.assertEqual(m['localX'],'X');self.assertEqual(m['thicknessAxis'],'Y')
   ysign=m['localAxisSigns'][1];self.assertEqual(m['viewNormalInSourceAxes'],[0,-ysign,0])
   for h in d['holesMm']:
    if h['type']=='counterbore':self.assertEqual(h['counterboreOpeningSide'],'selected-top')
  self.assertEqual(self.record('middle')['audit']['coordinateMapping']['localY'],'-Z')
  self.assertEqual(self.record('down')['audit']['coordinateMapping']['localY'],'Z')
 def test_source_hashes_and_svg_scale_match(self):
  for name in ['middle','down','for1','for2','for3']:
   d=self.record(name);source=Path(d['sourceStep']);source=source if source.is_absolute()else ROOT/source
   self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),d['sourceSha256'])
   for item in d['sourceEvidence']:
    p=Path(item['path']);p=p if p.is_absolute()else ROOT/p;self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),item['sha256'])
   svg=ET.parse(BASE/f'optical-frame-{name}.svg').getroot();self.assertEqual(list(map(float,svg.attrib['viewBox'].split())),[0,0,d['widthMm'],d['heightMm']])
   circles=[e for e in svg.iter()if 'data-hole-id'in e.attrib];self.assertEqual(len(circles),len(d['holesMm']));self.assertEqual({e.attrib['data-hole-id']for e in circles},{h['id']for h in d['holesMm']})
 def test_stepped_upper_support_cannot_be_registered_as_one_flat_plane(self):
  d=self.record('up');self.assertFalse(d['registrationReady']);self.assertTrue(d['audit']['intermediateBroadFaces']);self.assertEqual(d['thicknessMm'],50);self.assertTrue(d['warnings'])
if __name__=='__main__':unittest.main()
