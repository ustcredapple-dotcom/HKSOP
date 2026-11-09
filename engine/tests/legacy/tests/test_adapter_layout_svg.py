"""Assembly SVG and shared thumbnails retain plate hardware over the laser image."""
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

from bom import aggregate, load_catalog
from layout import layout_svg
from shared_kits import thumbnail_svg
from test_laser_adapter import board, laser, plan

ROOT = Path(__file__).resolve().parents[1]
SVG = "{http://www.w3.org/2000/svg}"


class AdapterLayoutSvgTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog.json")

    def test_flat_svg_draws_plate_below_image_and_all_holes_above_image(self):
        preview = aggregate(self.catalog, plan())
        doc = ET.fromstring(layout_svg(preview, ROOT / "static"))
        nodes = list(doc.iter())
        plate = doc.find(".//*[@data-adapter-layer='plate']")
        holes = doc.find(".//*[@data-adapter-layer='holes']")
        images = doc.findall(".//"+SVG+"image")
        self.assertLess(nodes.index(plate), min(nodes.index(i) for i in images))
        self.assertGreater(nodes.index(holes), max(nodes.index(i) for i in images))
        self.assertEqual(plate.find(SVG+"rect").get("width"), "543")
        self.assertEqual(plate.find(SVG+"rect").get("height"), "261")
        spec = preview["layoutValidation"]["laserAdapters"][0]["spec"]
        for kind, field, radii in (("counterbore", "boardMountingHolesMm", [5.5, 3.3]),
                                  ("thread", "laserThreadHolesMm", [3])):
            markers = holes.findall(f".//*[@data-hole-type='{kind}']")
            self.assertEqual(len(markers), 4)
            for marker, actual in zip(markers, spec[field]):
                self.assertEqual(marker.get("data-adapter-hole"), actual["label"])
                circles = marker.findall(SVG+"circle")
                self.assertEqual([float(c.get("r")) for c in circles], radii)
                self.assertTrue(all(float(c.get("cx")) == actual["xMm"] and float(c.get("cy")) == -actual["yMm"] for c in circles))
        label = doc.find(".//*[@data-adapter-axis-label='laser']")
        self.assertIn("有效光轴 152.4 mm", label.text)
        port = doc.find(".//*[@data-adapter-optical-port='output']")
        self.assertEqual((float(port.get("cx")), float(port.get("cy"))), (21,312.5))
        ray = doc.find(".//*[@data-adapter-layer='beam']/"+SVG+"line")
        self.assertLess(float(ray.get("x2")), float(ray.get("x1")))
        self.assertEqual(ray.get("y2"), ray.get("y1"))

    def test_rotated_small_board_renders_global_ray_but_keeps_local_plate_holes(self):
        owner=board(pitch=12.5)
        owner["mountingHoles"]=[{"columnIndex":c,"rowIndex":r} for c in (0,48) for r in (0,48)]
        small={"id":"module","name":"激光器小板","board":owner,"xMm":700,"yMm":100,"rotationDeg":90,"elevationMm":10}
        data={"layout":{"board":board(1000,1000),"subBoards":[small],"instances":[{**laser(),"boardId":"module","elevationMm":2}]}}
        preview=aggregate(self.catalog,data)
        doc=ET.fromstring(layout_svg(preview,ROOT/"static"))
        self.assertEqual(doc.find(".//*[@data-adapter-layer='holes']").get("transform"),"translate(454.5 596) rotate(-90)")
        self.assertIn("有效光轴 177.1 mm",doc.find(".//*[@data-adapter-axis-label='laser']").text)
        port=doc.find(".//*[@data-adapter-optical-port='output']")
        self.assertEqual((float(port.get("cx")),float(port.get("cy"))),(387.5,879))
        ray=doc.find(".//*[@data-adapter-layer='beam']/"+SVG+"line")
        self.assertEqual(ray.get("x2"),ray.get("x1"))
        self.assertGreater(float(ray.get("y2")),float(ray.get("y1")))
        children=list(doc)
        self.assertLess(children.index(doc.find(".//*[@data-sub-board='module']")),children.index(doc.find(".//*[@data-adapter-layer='plate']")))

    def test_shared_thumbnail_uses_same_adapter_assembly_artwork_and_no_adapter_stays_clean(self):
        preview=aggregate(self.catalog,plan())
        thumb=ET.fromstring(thumbnail_svg(preview,ROOT/"static"))
        self.assertIsNotNone(thumb.find(".//*[@data-adapter-layer='plate']"))
        self.assertEqual(len(thumb.findall(".//*[@data-adapter-hole]")),8)
        self.assertIn("152.4 mm",thumb.find(".//*[@data-adapter-axis-label='laser']").text)
        data=plan();del data["layout"]["instances"][0]["laserAdapter"]
        plain=ET.fromstring(layout_svg(aggregate(self.catalog,data),ROOT/"static"))
        self.assertIsNone(plain.find(".//*[@data-laser-adapter]"))


if __name__ == "__main__":
    unittest.main()
