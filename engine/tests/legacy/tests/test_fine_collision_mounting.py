"""Fine projection collision and explicit four-corner counterbore selection."""
import copy
import io
import json
import math
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree
from openpyxl import load_workbook

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bom import APIError,aggregate,load_catalog
from exports import export_result
from layout import choose_mounting_holes,polygons_touch,world_geometry,shapes_touch,hole_obstructs_shape

ROOT=Path(__file__).resolve().parents[1]


def request(instances=None, **board_fields):
    board={"widthMm":350,"heightMm":225,"pitchMm":12.5,"edgeOffsetMm":12.5,"thicknessMm":12.7,**board_fields}
    return {"layout":{"board":board,"instances":instances or []}}


def placed(iid,kid,x,y,rotation=0):
    return {"id":iid,"kitId":kid,"xMm":x,"yMm":y,"rotationDeg":rotation}


def user_fixture():
    return request([placed("pbs","pbs-adjustable",37.5,187.5,270),placed("motor","motor-05-45",37.5,137.5,90)])


class FineCollisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.catalog=load_catalog(ROOT/'catalog.json')

    def test_concave_empty_region_is_not_filled_by_bounding_box(self):
        l_shape=[(0,0),(40,0),(40,10),(10,10),(10,40),(0,40)]
        self.assertFalse(polygons_touch(l_shape,[(20,20),(30,20),(30,30),(20,30)]))
        self.assertTrue(polygons_touch(l_shape,[(10,20),(20,20),(20,30),(10,30)]))
        self.assertTrue(polygons_touch(l_shape,[(4,4),(6,4),(6,6),(4,6)]))
        self.assertTrue(polygons_touch(l_shape,[(40,0),(45,0),(45,5),(40,5)]))

    def test_disconnected_regions_keep_the_space_between_them_open(self):
        geometry={"widthMm":100,"heightMm":100,"anchorXMm":50,"anchorYMm":50,
                  "collisionPolygonsMm":[[{"xMm":x,"yMm":y} for x,y in p] for p in
                    [[(-40,-5),(-30,-5),(-30,5),(-40,5)],[(30,-5),(40,-5),(40,5),(30,5)]]],
                  "baseBoundsMm":{"xMin":-5,"xMax":5,"yMin":-5,"yMax":5},"mountingHoleOffsetsMm":[]}
        small={"widthMm":10,"heightMm":10,"anchorXMm":5,"anchorYMm":5,"mountingHoleOffsetsMm":[]}
        a=world_geometry(placed('a','fixture',100,100),geometry)
        b=world_geometry(placed('b','fixture',100,100),small)
        self.assertFalse(shapes_touch(a,b))
        b=world_geometry(placed('b','fixture',132.5,100),small)
        self.assertTrue(shapes_touch(a,b))

    def test_user_pbs_and_motor_bbox_overlap_but_fine_shapes_are_clear(self):
        preview=aggregate(self.catalog,user_fixture())
        self.assertTrue(preview['layoutValidation']['valid'],preview['layoutValidation'])
        self.assertFalse(preview['layoutValidation']['collisions'])
        self.assertFalse(preview['layoutValidation']['outOfBounds'])
        svg,_,_=export_result(preview,'layout-svg',ROOT/'assets',ROOT/'static')
        root=ElementTree.fromstring(svg)
        view=list(map(float,root.attrib['viewBox'].split()))
        self.assertLess(view[0],-15.197)
        self.assertTrue(root.findall('.//{http://www.w3.org/2000/svg}polygon'))

    def test_true_collision_is_still_blocked_after_fine_contour_change(self):
        data=user_fixture();data['layout']['instances'][1]['yMm']=162.5
        preview=aggregate(self.catalog,data)
        self.assertFalse(preview['layoutValidation']['valid'])
        self.assertEqual(preview['layoutValidation']['collisions'][0]['instanceIds'],['pbs','motor'])
        with self.assertRaises(APIError) as error:export_result(preview,'lubang',ROOT/'assets',ROOT/'static')
        self.assertEqual(error.exception.code,'layout_invalid')

    def test_only_base_must_be_on_board(self):
        data=request([placed('motor','motor-05-45',37.5,137.5,90)])
        self.assertTrue(aggregate(self.catalog,data)['layoutValidation']['valid'])
        data['layout']['instances'][0]['xMm']=12.5
        validation=aggregate(self.catalog,data)['layoutValidation']
        self.assertFalse(validation['valid'])
        self.assertTrue(validation['outOfBounds'])
        self.assertTrue(all(i['boundary']=='baseBoundsMm' for i in validation['outOfBounds']))


class MountingSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.catalog=load_catalog(ROOT/'catalog.json')

    def assert_spacing(self,holes):
        self.assertEqual(len(holes),4)
        for a in holes:
            for b in holes:
                for axis in ('xMm','yMm'):
                    self.assertAlmostEqual((a[axis]-b[axis])/25,round((a[axis]-b[axis])/25),places=6)

    def test_four_corner_selection_obeys_one_based_row_and_column_parity(self):
        for row in ('any','odd','even'):
            for col in ('any','odd','even'):
                with self.subTest(row=row,column=col):
                    selection=choose_mounting_holes(self.catalog,{**request(),"rowParity":row,"columnParity":col})
                    self.assertTrue(selection['layoutValidation']['valid'])
                    self.assert_spacing(selection['holes'])
                    for hole in selection['holes']:
                        if row!='any':self.assertEqual((hole['rowIndex']+1)%2,1 if row=='odd' else 0)
                        if col!='any':self.assertEqual((hole['columnIndex']+1)%2,1 if col=='odd' else 0)
                    self.assertEqual(selection['counterbore'],{'clearanceDiameterMm':6.6,'diameterMm':11.0,'depthMm':6.5,'face':'top'})

    def test_solver_avoids_real_fixture_and_does_not_mutate_input(self):
        data=user_fixture();unchanged=copy.deepcopy(data)
        selected=choose_mounting_holes(self.catalog,data)
        self.assertEqual(data,unchanged)
        self.assert_spacing(selected['holes'])
        self.assertTrue(selected['layoutValidation']['valid'])
        applied=copy.deepcopy(data);applied['layout']['board']=selected['board']
        self.assertFalse(aggregate(self.catalog,applied)['layoutValidation']['mountingHoleObstructions'])

    def test_moving_kit_over_existing_hole_blocks_without_reselecting(self):
        selected=choose_mounting_holes(self.catalog,request())
        data=request([placed('mirror','fixed-1-90',25,25)])
        data['layout']['board']=selected['board']
        original=copy.deepcopy(selected['mountingHoles'])
        preview=aggregate(self.catalog,data)
        self.assertFalse(preview['layoutValidation']['valid'])
        self.assertTrue(preview['layoutValidation']['mountingHoleObstructions'])
        self.assertEqual(preview['layout']['board']['mountingHoles'],original)
        with self.assertRaises(APIError):export_result(preview,'manufacturing',ROOT/'assets',ROOT/'static')
        replacement=choose_mounting_holes(self.catalog,data)
        self.assertTrue(replacement['layoutValidation']['valid'])
        self.assertNotEqual(replacement['mountingHoles'],original)

    def test_counterbore_disk_contact_with_actual_boundary_is_blocked(self):
        geometry={'widthMm':10,'heightMm':10,'anchorXMm':5,'anchorYMm':5,'mountingHoleOffsetsMm':[]}
        shape=world_geometry(placed('test','test',30,30),geometry)
        self.assertTrue(hole_obstructs_shape((19.5,30),5.5,shape))
        self.assertFalse(hole_obstructs_shape((19.49,30),5.5,shape))

    def test_mounting_reference_circles_do_not_obstruct_outside_brown_contour(self):
        geometry={'widthMm':10,'heightMm':10,'anchorXMm':5,'anchorYMm':5,
                  'mountingHoleOffsetsMm':[{'xMm':20,'yMm':0}]}
        shape=world_geometry(placed('test','test',30,30),geometry)
        self.assertFalse(hole_obstructs_shape((58.8,30),5.5,shape))
        self.assertFalse(hole_obstructs_shape((58.81,30),5.5,shape))

    def test_impossible_selection_fails_explicitly_and_never_clears_saved_holes(self):
        data=request(widthMm=25,heightMm=25)
        original=copy.deepcopy(data)
        with self.assertRaises(APIError) as error:choose_mounting_holes(self.catalog,data)
        self.assertEqual(error.exception.code,'mounting_holes_unavailable')
        self.assertEqual(data,original)
        with self.assertRaises(APIError) as error:choose_mounting_holes(self.catalog,request(thicknessMm=5))
        self.assertEqual(error.exception.code,'mounting_plate_too_thin')
        with self.assertRaises(APIError):choose_mounting_holes(self.catalog,{**request(),'rowParity':'wrong'})

    def test_nonstandard_pitch_still_satisfies_25mm_coordinate_differences(self):
        selection=choose_mounting_holes(self.catalog,request(pitchMm=20,edgeOffsetMm=20,widthMm=500,heightMm=400))
        self.assert_spacing(selection['holes'])
        self.assertTrue(selection['layoutValidation']['valid'])

    def test_svg_json_and_workbook_keep_four_hole_coordinates_and_specification(self):
        selected=choose_mounting_holes(self.catalog,request())
        data=request();data['layout']['board']=selected['board']
        preview=aggregate(self.catalog,data)
        exported,_,_=export_result(preview,'layout-json',ROOT/'assets',ROOT/'static')
        saved=json.loads(exported)
        self.assertEqual(saved['boardSpecification']['mountingHoleCount'],4)
        self.assertEqual(saved['boardSpecification']['regularHoleCount'],455)
        self.assertEqual(saved['boardSpecification']['counterbore']['depthMm'],6.5)
        saved['boardSpecification']['counterbore']['depthMm']=999
        checked=aggregate(self.catalog,saved)
        self.assertEqual(checked['manufacturing'][0]['boardSpec']['counterbore']['depthMm'],6.5)
        svg,_,_=export_result(preview,'layout-svg',ROOT/'assets',ROOT/'static')
        self.assertEqual(svg.count(b'data-mounting-hole='),4)
        self.assertIn('Ø11'.encode(),svg)
        workbook,_,_=export_result(preview,'manufacturing',ROOT/'assets',ROOT/'static')
        wb=load_workbook(io.BytesIO(workbook))
        ws=wb['面包板固定孔']
        self.assertEqual(ws['A6'].value,'H1')
        self.assertEqual(ws['B6'].value,1)
        self.assertEqual(ws['D6'].value,12.5)
        self.assertEqual(ws['G6'].value,11)
        self.assertEqual(ws['H6'].value,6.5)


if __name__=='__main__':unittest.main()
