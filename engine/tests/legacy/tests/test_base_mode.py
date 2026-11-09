"""Root workspace mode: strict persistence, physical child boards, and order files."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from openpyxl import load_workbook

from bom import APIError, aggregate, load_catalog
from breadboard import board_specs
from cart import CartStore
from exports import export_result
from layout import choose_mounting_holes, layout_json, validate_layout
from shared_kits import Identity, SharedKitStore, prepare_project, project_payload, thumbnail_svg
from test_layout import layout_fixture, request
from test_shared_kits import project
from test_stacked_layout import plan
from test_laser_adapter import plan as laser_plan


ROOT = Path(__file__).resolve().parents[1]


def token(envelope):
    return {k: envelope[k] for k in ("cartId", "revision")}


class TableModeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = layout_fixture()
        self.kits = {k["id"]: k for k in self.catalog["kits"]}

    def preview(self, layout):
        return aggregate(self.catalog, {"layout": layout})

    def table(self, stacked=False):
        layout = plan() if stacked else request()["layout"]
        layout["baseMode"] = "table"
        return layout

    def test_optional_mode_preserves_legacy_and_explicit_values(self):
        legacy = request()["layout"]
        self.assertNotIn("baseMode", self.preview(legacy)["layout"])
        explicit = {**legacy, "baseMode": "breadboard"}
        self.assertEqual(self.preview(explicit)["layout"]["baseMode"], "breadboard")
        self.assertEqual(self.preview(explicit)["totals"]["boards"], 1)
        self.assertEqual(self.preview(self.table())["totals"]["boards"], 0)

    def test_mode_is_strict_root_only_in_flat_and_stacked_layouts(self):
        for stacked in (False, True):
            for value in (None, 0, True, "", "Table", "invalid", [], {}):
                layout = self.table(stacked)
                layout["baseMode"] = value
                with self.subTest(stacked=stacked, value=value), self.assertRaises(APIError):
                    self.preview(layout)
        for target in ("board", "instance", "subBoard"):
            layout = self.table(True)
            obj = layout["board"] if target == "board" else layout["instances"][0] if target == "instance" else layout["subBoards"][0]
            obj["baseMode"] = "table"
            with self.subTest(target=target), self.assertRaises(APIError):
                self.preview(layout)
        layout = self.table()
        layout["produceRoot"] = False
        with self.assertRaises(APIError):
            self.preview(layout)

    def test_direct_components_need_no_physical_root_holes_but_bounds_and_collisions_remain(self):
        layout = self.table()
        layout["instances"][0]["xMm"] += 1
        result = self.preview(layout)
        self.assertTrue(result["layoutValidation"]["valid"], result["layoutValidation"])
        layout["baseMode"] = "breadboard"
        self.assertIn("mounting_mismatch", {i["code"] for i in self.preview(layout)["layoutValidation"]["issues"]})
        layout["baseMode"] = "table"
        layout["instances"][1].update(xMm=layout["instances"][0]["xMm"], yMm=50)
        self.assertIn("collision", {i["code"] for i in self.preview(layout)["layoutValidation"]["issues"]})
        layout["instances"][0]["xMm"] = -10
        self.assertIn("out_of_bounds", {i["code"] for i in self.preview(layout)["layoutValidation"]["issues"]})

    def test_independent_children_need_no_root_overlap_or_fasteners_but_own_mounts_remain(self):
        layout = self.table(True)
        layout["board"].update(pitchMm=20, holeType="plain_through")
        layout["subBoards"][0].update(xMm=3, yMm=7)
        result = self.preview(layout)
        self.assertTrue(result["layoutValidation"]["valid"], result["layoutValidation"])
        self.assertEqual(result["totals"]["boards"], 1)
        self.assertNotIn("baseMode", result["layout"]["subBoards"][0])
        layout["instances"][0]["xMm"] += 1
        self.assertIn("mounting_mismatch", {i["code"] for i in self.preview(layout)["layoutValidation"]["issues"]})

    def test_table_keeps_child_overlap_bounds_and_axis_validation(self):
        layout = self.table(True)
        second = copy.deepcopy(layout["subBoards"][0])
        second.update(id="s2", xMm=25)
        layout["subBoards"].append(second)
        self.assertIn("sub_board_collision", {i["code"] for i in self.preview(layout)["layoutValidation"]["issues"]})
        second["xMm"] = 599
        self.assertIn("sub_board_out_of_bounds", {i["code"] for i in self.preview(layout)["layoutValidation"]["issues"]})
        layout["subBoards"].pop()
        layout["instances"].append({"id":"root", "kitId":"beta", "xMm":350, "yMm":300, "rotationDeg":0})
        for kit in self.catalog["kits"]:
            kit["layout"]["opticalAxisHeightMm"] = 63.5
        result = self.preview(layout)
        self.assertIn("axis_height_mismatch", {i["code"] for i in result["layoutValidation"]["issues"]})
        self.assertEqual(sorted(a["effectiveAxisHeightMm"] for a in result["layoutValidation"]["axisHeights"]), [63.5, 76.2])

    def test_root_reference_counterbores_do_not_obstruct_but_child_counterbores_do(self):
        layout = self.table(True)
        layout["board"]["mountingHoles"] = [{"columnIndex":c,"rowIndex":r} for c in (0,2) for r in (0,2)]
        self.assertTrue(self.preview(layout)["layoutValidation"]["valid"])
        child = layout["subBoards"][0]["board"]
        child["mountingHoles"] = [{"columnIndex":c,"rowIndex":r} for c in (0,2) for r in (0,2)]
        layout["instances"][0].update(xMm=25,yMm=25)
        self.assertIn("mounting_hole_obstructed", {i["code"] for i in self.preview(layout)["layoutValidation"]["issues"]})

    def test_child_auto_eight_uses_its_own_grid_and_root_selection_is_rejected(self):
        layout = self.table(True)
        layout["subBoards"][0].update(xMm=3,yMm=7)
        result = choose_mounting_holes(self.catalog, {"layout":layout,"boardId":"s1","holeCount":8})
        self.assertEqual(len(result["boards"][0]["mountingHoles"]), 8)
        self.assertEqual(layout["subBoards"][0]["board"]["mountingHoles"], [])
        for target in (layout, self.table()):
            with self.assertRaises(APIError) as caught:
                choose_mounting_holes(self.catalog, {"layout":target})
            self.assertEqual(caught.exception.code, "no_root_breadboard")

    def test_same_spec_root_reference_is_not_subtracted_from_physical_child_quantity(self):
        layout = self.table(True)
        layout["subBoards"][0]["board"] = copy.deepcopy(layout["board"])
        result = self.preview(layout)
        boards = [r for r in result["manufacturing"] if r.get("generatedBoard")]
        self.assertTrue(result["layoutValidation"]["valid"])
        self.assertEqual([(r["componentId"],r["quantity"]) for r in boards], [(board_specs(layout["board"])["componentId"],1)])
        self.assertEqual(result["totals"]["boards"], 1)
        layout["baseMode"] = "breadboard"
        self.assertEqual([r["quantity"] for r in self.preview(layout)["manufacturing"] if r.get("generatedBoard")], [2])

    def test_root_excluded_before_identical_children_merge_and_custom_parts_retained(self):
        layout = self.table(True)
        child = copy.deepcopy(layout["subBoards"][0])
        child.update(id="s2",xMm=250)
        layout["subBoards"].append(child)
        result = self.preview(layout)
        rows = {r["componentId"]:r for r in result["manufacturing"]}
        self.assertNotIn(board_specs(layout["board"])["componentId"], rows)
        self.assertEqual(rows[board_specs(child["board"])["componentId"]]["quantity"], 2)
        self.assertEqual(rows["plate"]["quantity"], 1)
        self.assertEqual(result["totals"]["boards"], 2)

    def test_layout_and_shared_project_roundtrip_preserve_mode_and_explicit_production_scope(self):
        p = project()
        p["layout"] = self.table()
        original = copy.deepcopy(p)
        preview = prepare_project(p, self.catalog)
        doc = json.loads(layout_json(preview))
        self.assertFalse(doc["boardSpecification"]["productionIncluded"])
        self.assertEqual(aggregate(self.catalog, doc)["totals"]["boards"], 0)
        self.assertEqual(project_payload(p, self.catalog)["layout"]["baseMode"], "table")
        self.assertEqual(p, original)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"topviews").mkdir()
            (root/"topviews/test.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            thumb = thumbnail_svg(preview, root)
            self.assertIn("不加工根板", thumb.decode())
            store = SharedKitStore(root/"shared.sqlite3")
            user = Identity("table-owner", "桌面方案", "user")
            published = store.publish("桌面模块", "无实体大板", p, thumb, user)
            reopened = json.loads(store.get(published["kit"]["id"], user)["project_json"])
            self.assertEqual(reopened, original)
            self.assertEqual(prepare_project(reopened, self.catalog)["totals"]["boards"], 0)


class TableOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = layout_fixture()
        (self.root/"topviews").mkdir()
        (self.root/"topviews/test.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        for part in ("plate", "bracket"):
            (self.root/(part+".step")).write_bytes(b"ISO-10303-21; fixture")
            (self.root/(part+".pdf")).write_bytes(b"%PDF fixture")
        self.cache = (self.root/"cache").resolve()
        self.cache.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def generate(self, board, _):
        spec = board_specs(board)
        result = {"componentId":spec["componentId"]}
        for field,suffix in (("step","step"),("drawing","pdf")):
            path = self.cache/(spec["componentId"]+"."+suffix)
            path.write_bytes(b"generated board fixture")
            result[field] = str(path)
        return result

    def bundle(self, preview):
        with patch.dict(os.environ, {"ZZLAB_BOARD_CACHE":str(self.cache)}), patch("breadboard.ensure_board_artifacts", side_effect=self.generate) as generated:
            data,_,_ = export_result(preview,"bundle",self.root,self.root)
        return zipfile.ZipFile(io.BytesIO(data)), generated

    def test_flat_table_zip_never_calls_root_cad_keeps_parts_and_layout_reference(self):
        data = request()
        data["layout"]["baseMode"] = "table"
        result = aggregate(self.catalog,data)
        archive, generated = self.bundle(result)
        with archive:
            generated.assert_not_called()
            names = archive.namelist()
            self.assertEqual(len([n for n in names if n.endswith(".step")]), 2)
            self.assertEqual(len([n for n in names if n.endswith(".pdf")]), 2)
            self.assertIn("不生成其 STEP", archive.read("桌面工作区说明.txt").decode())
            self.assertIn("不加工根板", archive.read("光路总俯视图.svg").decode())
            config = json.loads(archive.read("套件配置.json"))
            self.assertEqual(config["layout"]["baseMode"], "table")
            self.assertFalse(any(r.get("generatedBoard") for r in config["components"]))
            book = load_workbook(io.BytesIO(archive.read("生产清单.xlsx")))
            self.assertIn("桌面工作区参考", book.sheetnames)
            self.assertNotIn("面包板规格", book.sheetnames)

    def test_table_cart_is_immutable_private_and_mixed_orders_keep_only_actual_board_quantity(self):
        layout = plan()
        layout["baseMode"] = "table"
        layout["subBoards"][0]["board"] = copy.deepcopy(layout["board"])
        store = CartStore(SharedKitStore(self.root/"cart.sqlite3"))
        user = Identity("owner", "测试", "user")
        first = store.add(user,{**token(store.read(user)),"requestId":"table-first","name":"桌面方案","payload":{"layout":layout}},self.catalog)
        self.assertEqual(first["preview"]["totals"]["boards"], 1)
        layout["baseMode"] = "breadboard"
        source = first["preview"]["cartSources"][0]
        self.assertEqual(source["layout"]["baseMode"], "table")
        root_only = {"board":copy.deepcopy(layout["board"]),"instances":[]}
        second = store.add(user,{**token(first),"requestId":"board-second","name":"实际大板","payload":{"layout":root_only}},self.catalog)
        self.assertEqual(second["preview"]["totals"]["boards"],2)
        restarted = CartStore(SharedKitStore(self.root/"cart.sqlite3"))
        self.assertEqual(restarted.read(user)["items"],second["items"])
        self.assertEqual(restarted.read(Identity("other","其他账号","user"))["items"],[])
        result = restarted.for_export(user,token(second),self.catalog)
        boards = [r for r in result["manufacturing"] if r.get("generatedBoard")]
        self.assertEqual([r["quantity"] for r in boards],[2])
        archive, generated = self.bundle(result)
        with archive:
            self.assertEqual(generated.call_count,1)
            self.assertEqual(board_specs(generated.call_args.args[0])["componentId"],board_specs(root_only["board"])["componentId"])
            references = [json.loads(archive.read(n)) for n in archive.namelist() if n.endswith("原布局.json")]
            self.assertEqual(len(references),2)
            self.assertEqual(sum(r["layout"].get("baseMode")=="table" for r in references),1)
            config = json.loads(archive.read("套件配置.json"))
            self.assertEqual(config["totals"]["boards"],2)
            self.assertIn("桌面工作区说明.txt",archive.namelist())

    def test_table_child_export_calls_cad_only_for_child_spec(self):
        layout = plan()
        layout["baseMode"] = "table"
        result = aggregate(self.catalog,{"layout":layout})
        archive, generated = self.bundle(result)
        with archive:
            self.assertEqual(generated.call_count,1)
            self.assertEqual(board_specs(generated.call_args.args[0])["componentId"],board_specs(layout["subBoards"][0]["board"])["componentId"])
            self.assertNotEqual(board_specs(generated.call_args.args[0])["componentId"],board_specs(layout["board"])["componentId"])


class TableLaserAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT/"catalog.json")

    def test_table_keeps_adapter_geometry_axis_and_manufacturing_but_no_root_beam_rule(self):
        for rotation in (0,90,180,270):
            data = laser_plan(rotation=rotation)
            laser = data["layout"]["instances"][0]
            laser["yMm" if rotation in (0,180) else "xMm"] += 1
            before = aggregate(self.catalog,data)
            self.assertIn("adapter_beam_off_grid",{i["code"] for i in before["layoutValidation"]["issues"]})
            data["layout"]["baseMode"] = "table"
            after = aggregate(self.catalog,data)
            with self.subTest(rotation=rotation):
                self.assertTrue(after["layoutValidation"]["valid"],after["layoutValidation"])
                self.assertEqual(after["layout"]["instances"],before["layout"]["instances"])
                self.assertEqual(after["layoutValidation"]["laserAdapters"][0]["spec"],before["layoutValidation"]["laserAdapters"][0]["spec"])
                self.assertEqual(after["layoutValidation"]["axisHeights"][0]["effectiveAxisHeightMm"],152.4)
                self.assertEqual(len([r for r in after["manufacturing"] if r.get("generatedLaserAdapter")]),1)
                self.assertFalse(any(r.get("generatedBoard") for r in after["manufacturing"]))

    def test_table_does_not_export_incomplete_adapter_geometry(self):
        data = laser_plan()
        data["layout"]["baseMode"] = "table"
        data["layout"]["board"]["holeType"] = "plain_through"
        result = aggregate(self.catalog,data)
        self.assertIn("adapter_mounting_unavailable",{i["code"] for i in result["layoutValidation"]["issues"]})
        with self.assertRaises(APIError) as caught:
            export_result(result,"bundle",Path("/unused"))
        self.assertEqual(caught.exception.code,"layout_invalid")


if __name__ == "__main__":
    unittest.main()
