"""Owner-approved post adapter remains explicit and is counted on checkout."""
import copy
import unittest
from pathlib import Path
from bom import aggregate, load_catalog, APIError
from elevation import validate_universal_posts

class PostThreadAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=load_catalog(Path(__file__).resolve().parents[1]/'catalog.json')
        next(c for c in cls.catalog['components'] if c['id']=='custom-post-metric-12p5mm-m1')['postTopThread']='M6'  # Explicit legacy fixture, not current catalogue
    def layout(self):
        return {'baseMode':'table','board':{'widthMm':500,'heightMm':300,'pitchMm':25,'edgeOffsetMm':12.5,'thicknessMm':12.5,'holeType':'M6_through','mountingHoles':[]},'instances':[{'id':'h2','kitId':'motor-2-90-h2-coplanar-r1','xMm':200,'yMm':150,'rotationDeg':0,'universalPostSelection':{'custom-post-metric-12p5mm-m1':'custom-post-metric-25mm-m1'}}]}
    def test_adapted_replacement_adds_pending_purchase_and_retains_nominal_height(self):
        layout=self.layout();before=copy.deepcopy(layout);p=aggregate(self.catalog,{'layout':layout})
        self.assertTrue(p['layoutValidation']['valid']);self.assertEqual(p['layoutValidation']['axisHeights'][0]['effectiveAxisHeightMm'],75)
        adapters=[r for r in p['standard'] if r['componentId'].startswith('post-thread-adapter:')]
        self.assertEqual(len(adapters),1);self.assertEqual(adapters[0]['quantity'],1);self.assertEqual(adapters[0]['model'],'待选');self.assertIn('实物',adapters[0]['notes']);self.assertEqual(layout,before)
    def test_original_post_has_no_new_adapter_purchase(self):
        layout=self.layout();layout['instances'][0].pop('universalPostSelection');p=aggregate(self.catalog,{'layout':layout})
        self.assertFalse(any(r['componentId'].startswith('post-thread-adapter:') for r in p['standard']))
    def test_approval_type_is_not_truthy_string(self):
        catalog=copy.deepcopy(self.catalog);next(k for k in catalog['kits'] if k['id']=='motor-2-90-h2-coplanar-r1')['layout']['postThreadAdapterAccepted']='true'
        with self.assertRaises(APIError):validate_universal_posts(catalog)

if __name__=='__main__':unittest.main()
