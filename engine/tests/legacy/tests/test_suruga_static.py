"""Static placement of the existing Suruga reference assembly, no motion claims."""
import copy,json,unittest
from pathlib import Path
from bom import aggregate,APIError
from test_stacked_layout import board

class SurugaStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=json.loads((Path(__file__).resolve().parents[1]/'catalog.json').read_text())
        cls.kit=next(k for k in cls.catalog['kits'] if k['id']=='suruga-xyz-grid-reference-r1')
    def preview(self,x=87.5,rotation=0):
        return aggregate(self.catalog,{'layout':{'board':board(400,300,25),'instances':[dict(id='xyz',kitId=self.kit['id'],xMm=x,yMm=87.5,rotationDeg=rotation)]}})
    def test_static_placement_and_four_rotations_snap_to_real_adapter_holes(self):
        for r in (0,90,180,270):
            v=self.preview(rotation=r)['layoutValidation'];self.assertTrue(v['valid'],v['issues'])
            self.assertEqual(v['mountingAlignment'][0]['alignedCount'],4)
            self.assertIsNone(v['axisHeights'][0]['opticalAxisHeightMm'])
    def test_bounds_and_wrong_hole_phase_still_rejected(self):
        self.assertIn('out_of_bounds',{i['code'] for i in self.preview(x=12.5)['layoutValidation']['issues']})
        self.assertIn('mounting_mismatch',{i['code'] for i in self.preview(x=100)['layoutValidation']['issues']})
    def test_no_optic_or_extra_oem_procurement_in_added_body(self):
        self.assertTrue(self.kit['layout']['placementAllowed'])
        self.assertEqual(self.kit['runtimeCompatibility']['xyzMotion'],'unsupported')
        self.assertEqual(self.kit['opticalSlots'],[])
        p=self.preview();actual={r['componentId']:r['quantity'] for g in ('manufacturing','standard','lubang') for r in p[g] if not r['componentId'].startswith('breadboard-')}
        self.assertEqual(actual,{r['componentId']:r['quantity'] for r in self.kit['components']})
        self.assertFalse(any('post' in k or 'mirror' in k for k in actual))
        self.assertEqual(len(self.kit['mountedExistingHardware']),2)
        for h in self.kit['mountedExistingHardware']:self.assertEqual(h['procurement'],'existing-excluded')
