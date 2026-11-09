"""Compound CAD surfaces use 3D ray hits, not one scalar global axis constraint."""
import unittest
from bom import APIError
from elevation import axis_validation,normalize_fields

class CompoundElevationTests(unittest.TestCase):
 def test_compound_precise_cad_height_is_informational(self):
  layout={'instances':[{'id':'laser','kitId':'source'},{'id':'assembly','kitId':'compound','elevationMm':2,'elevationSupportCount':5}]}
  metadata={'source':{'opticalAxisHeightMm':113.1},'compound':{'opticalAxisHeightMm':113.06370626,'opticalAssembly':{'nodes':[]}}}
  result,issues=axis_validation(layout,metadata,[])
  self.assertEqual(issues,[]);self.assertEqual(result['axisHeightReferenceMm'],113.1)
  compound=result['axisHeights'][1];self.assertFalse(compound['globalHeightComparable'])
  self.assertAlmostEqual(compound['effectiveAxisHeightMm'],115.063706,places=6)
  self.assertEqual(compound['elevationSupportCount'],5)
  result,issues=axis_validation({'instances':[layout['instances'][1]]},metadata,[])
  self.assertIsNone(result['axisHeightReferenceMm']);self.assertEqual(issues,[])
 def test_ordinary_axes_and_support_validators_remain_active(self):
  result,issues=axis_validation({'instances':[{'id':'a','kitId':'a'},{'id':'b','kitId':'b'}]}, {'a':{'opticalAxisHeightMm':113.1},'b':{'opticalAxisHeightMm':113.06370626}},[])
  self.assertEqual(issues[0]['code'],'axis_height_mismatch')
  for fields in ({'elevationMm':-.1},{'elevationMm':1.01},{'elevationSupportCount':0}):
   with self.assertRaises(APIError):normalize_fields(fields)

if __name__=='__main__':unittest.main()
