import json,unittest,copy
from pathlib import Path
from xml.etree import ElementTree as ET
import registered_boards as rb

class ReferenceAnnotations(unittest.TestCase):
    def test_export_layers_and_no_geometry_changes(self):
        catalog=json.loads((Path(__file__).resolve().parents[1]/'catalog.json').read_text())
        rb.validate_catalog_boards(catalog)
        token=rb._ACTIVE_CATALOG.set(catalog)
        try:
            for r in catalog['registeredBoards']:
                if 'referenceAnnotations' not in r:continue
                b=rb.normalize({'registeredBoardId':r['id'],'registeredBoardRevision':r['revision']})
                before=(rb.outline(b),rb.cutouts(b),rb.holes(b))
                svg=ET.fromstring('<svg>'+rb.svg_markup(b)+'</svg>')
                if r['id']=='optical-frame-for1':
                    self.assertEqual(r['referenceAnnotations']['sectionHeightAboveBoardTopMm'],113.06370626)
                    sections=svg.findall('.//*[@data-reference-kind="obstruction-section"]/path')
                    self.assertGreaterEqual(len(sections),10)
                    for p in sections:
                        self.assertNotEqual(p.get('fill'),'none')
                        self.assertEqual(p.get('fill-rule'),'evenodd')
                        self.assertEqual(p.get('stroke-dasharray'),'none')
                    for kind in ('leg','glass','coil','coil-section','iontrap'):
                        self.assertEqual(len(svg.findall(f'.//*[@data-reference-kind="{kind}"]')),0)
                    self.assertIsNone(svg.find('.//*[@data-reference-center="iontrap-center"]'))
                    self.assertIn('113.064 mm',rb.svg_markup(b))
                else:
                    self.assertEqual(len(svg.findall('.//*[@data-reference-kind="leg"]')),13)
                    self.assertEqual(len(svg.findall('.//*[@data-reference-kind="iontrap"]')),12)
                    self.assertEqual(len(svg.findall('.//*[@data-reference-kind="coil-section"]')),8)
                    coil=svg.find('.//*[@data-reference-kind="coil"]/path')
                    self.assertEqual(coil.get('fill'),'none')
                    self.assertEqual(coil.get('fill-rule'),'evenodd')
                    self.assertEqual(coil.get('d').count('M '),136)
                    self.assertIsNotNone(svg.find('.//*[@data-reference-center="iontrap-center"]'))
                self.assertEqual(len(svg.findall('.//*[@data-board-hole]')),len(r['holesMm']))
                self.assertIsNone(svg.find('.//*[@data-reference-center="glass-center"]'))
                self.assertEqual(svg.find('.//*[@class="board-reference-annotations"]').get('pointer-events'),'none')
                annotations=r.pop('referenceAnnotations')
                self.assertEqual(before,(rb.outline(b),rb.cutouts(b),rb.holes(b)))
                self.assertNotIn('referenceAnnotations',b)
                self.assertNotIn('board-reference-annotations',rb.svg_markup(b))
                r['referenceAnnotations']=annotations
        finally:rb._ACTIVE_CATALOG.reset(token)

    def test_invalid_reference_data_rejected(self):
        catalog=json.loads((Path(__file__).resolve().parents[1]/'catalog.json').read_text())
        rows=[r for r in catalog['registeredBoards'] if r.get('referenceAnnotations')]
        for bad in [False,None]:
            c=copy.deepcopy(catalog);r=next(r for r in c['registeredBoards'] if r.get('referenceAnnotations'));r['referenceAnnotations']['displayOnly']=bad
            with self.assertRaises(ValueError):rb.validate_catalog_boards(c)
        c=copy.deepcopy(catalog);r=next(r for r in c['registeredBoards'] if r.get('referenceAnnotations'))
        r=next(r for r in c['registeredBoards'] if r['id']=='optical-frame-for2')
        r['referenceAnnotations']['projections'][0]['cutoutsMm'][0][0]['xMm']=float('nan')
        with self.assertRaises(ValueError):rb.validate_catalog_boards(c)
        c=copy.deepcopy(catalog);r=next(r for r in c['registeredBoards'] if r['id']=='optical-frame-for1')
        r['referenceAnnotations']['sectionHeightAboveBoardTopMm']=float('nan')
        with self.assertRaises(ValueError):rb.validate_catalog_boards(c)
        rows[0]['referenceAnnotations']['centers'][0]['xMm']=float('nan')
        with self.assertRaises(ValueError):rb.validate_catalog_boards(catalog)

if __name__=='__main__':unittest.main()
