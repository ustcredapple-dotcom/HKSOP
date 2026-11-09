import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from breadboard import normalize_board,board_specs,board_row,ensure_board_artifacts,BreadboardError,MANUFACTURING_POLICY_PATH

BASE={'widthMm':350,'heightMm':225,'pitchMm':12.5,'edgeOffsetMm':12.5}
MOUNTS=[{'columnIndex':i,'rowIndex':j} for j in (0,16) for i in (0,26)]

class BreadboardContractTests(unittest.TestCase):
    def test_actual_default_grid_and_thread_representation(self):
        s=board_specs(BASE)
        self.assertEqual((s['gridColumns'],s['gridRows'],s['holeCount']),(27,17,459))
        self.assertEqual(s['board']['thicknessMm'],12.5)
        self.assertEqual(s['board']['holeDiameterMm'],5)
        self.assertEqual(s['stepThreadRepresentation'],'tap_drill_cylinder_no_helical_thread')
        self.assertEqual(s['rightMarginMm'],12.5)
        self.assertEqual(s['topMarginMm'],12.5)
    def test_300_by_150_grid(self):
        s=board_specs({**BASE,'widthMm':300,'heightMm':150})
        self.assertEqual((s['gridColumns'],s['gridRows'],s['holeCount']),(23,11,253))
    def test_remainder_is_right_top_margin(self):
        s=board_specs({**BASE,'widthMm':353,'heightMm':231})
        self.assertEqual(s['rightMarginMm'],15.5)
        self.assertEqual(s['topMarginMm'],18.5)
    def test_plain_hole_is_not_threaded(self):
        b={**BASE,'holeType':'plain_through','holeDiameterMm':6.4}
        s=board_specs(b)
        self.assertIsNone(s['board']['thread'])
        self.assertEqual(s['stepThreadRepresentation'],'plain_cylinder')
        self.assertEqual(s['holeCallout'],'Ø6.4 通孔')
    def test_ids_are_stable_and_change_with_geometry(self):
        a=board_specs(BASE)
        self.assertEqual(a['digest'],board_specs(dict(reversed(list(BASE.items()))))['digest'])
        self.assertNotEqual(a['digest'],board_specs({**BASE,'thicknessMm':15})['digest'])
    def test_row_is_one_new_generated_custom_board(self):
        row=board_row(BASE)
        self.assertEqual(row['quantity'],1);self.assertEqual(row['unit'],'块')
        self.assertTrue(row['generatedBoard']);self.assertIsNone(row['stepPath'])
        self.assertIn('材料：'+row['boardSpec']['material'],row['notes'])
        self.assertIn('表面处理：'+row['boardSpec']['surfaceTreatment'],row['notes'])
    def test_materials_are_operator_policy_not_payload(self):
        policy=json.loads(MANUFACTURING_POLICY_PATH.read_text());s=board_specs(BASE)
        profile=policy['profiles'][policy['generatedBoardProfile']]
        self.assertEqual(s['material'],profile['material'])
        self.assertEqual(s['surfaceTreatment'],profile['surfaceTreatment'])
        self.assertNotIn('generalTolerance',s);self.assertNotIn('roughness',s)
        self.assertNotIn('通用公差',board_row(BASE)['notes']);self.assertNotIn('粗糙度',board_row(BASE)['notes'])
        for key in ('material','surfaceTreatment','manufacturingPolicyVersion','manufacturingProfile'):
            with self.subTest(key=key),self.assertRaises(BreadboardError):normalize_board({**BASE,key:'override'})
    def test_policy_change_invalidates_cache_without_changing_geometry_identity(self):
        before=board_specs(BASE);policy=json.loads(MANUFACTURING_POLICY_PATH.read_text())
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/'policy.json';profile=policy['profiles'][policy['generatedBoardProfile']]
            profile['surfaceTreatment']='测试工艺';file.write_text(json.dumps(policy))
            with patch('breadboard.MANUFACTURING_POLICY_PATH',file):after=board_specs(BASE)
            self.assertNotEqual(before['digest'],after['digest'])
            self.assertEqual(before['model'],after['model']);self.assertEqual(before['geometryDigest'],after['geometryDigest'])
            self.assertEqual(before['board'],after['board'])
            policy['version']+='-changed';file.write_text(json.dumps(policy))
            with patch('breadboard.MANUFACTURING_POLICY_PATH',file):version_change=board_specs(BASE)
            self.assertNotEqual(after['digest'],version_change['digest'])
    def test_missing_operator_policy_fails_closed(self):
        with patch('breadboard.MANUFACTURING_POLICY_PATH',Path('/nonexistent-policy.json')),self.assertRaises(BreadboardError) as err:
            board_specs(BASE)
        self.assertEqual(err.exception.code,'manufacturing_policy_unavailable')
    def test_refuses_invalid_or_unsafe_geometry(self):
        bad=[{**BASE,'widthMm':True},{**BASE,'heightMm':float('nan')},{**BASE,'path':'/etc/passwd'},
             {**BASE,'pitchMm':6},{**BASE,'edgeOffsetMm':2},{**BASE,'thread':'M4'},
             {**BASE,'holeDiameterMm':6},{**BASE,'thicknessMm':0},{**BASE,'holeType':'plain_through','thread':'M6x1.0'},
             {**BASE,'widthMm':638,'heightMm':650},{**BASE,'holeType':'plain_through','holeDiameterMm':20}]
        for b in bad:
            with self.subTest(board=b),self.assertRaises(BreadboardError):normalize_board(b)
    def test_upper_hole_limit(self):
        s=board_specs({**BASE,'widthMm':637.5,'heightMm':637.5})
        self.assertEqual(s['holeCount'],2500)
    def test_missing_cad_has_clear_service_error(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{},clear=True):
            with self.assertRaises(BreadboardError) as err:ensure_board_artifacts(BASE,td)
            self.assertEqual(err.exception.code,'cad_unavailable');self.assertEqual(err.exception.status,503)
    def test_mounts_replace_four_ordinary_holes_and_have_exact_coordinates(self):
        s=board_specs({**BASE,'mountingHoles':MOUNTS})
        self.assertEqual((s['holeCount'],s['regularHoleCount'],s['mountingHoleCount']),(459,455,4))
        self.assertEqual([(h['label'],h['xMm'],h['yMm']) for h in s['mountingHoles']],
                         [('H1',12.5,12.5),('H2',337.5,12.5),('H3',12.5,212.5),('H4',337.5,212.5)])
        self.assertEqual(s['counterbore'],{'clearanceDiameterMm':6.6,'diameterMm':11.0,'depthMm':6.5,'face':'top'})
        self.assertNotEqual(s['digest'],board_specs(BASE)['digest'])
        self.assertEqual(s['digest'],board_specs({**BASE,'mountingHoles':list(reversed(MOUNTS))})['digest'])
        self.assertIn('4个安装孔替换',board_row({**BASE,'mountingHoles':MOUNTS})['notes'])
    def test_mount_indices_reject_bad_shape_duplicates_noninteger_and_offgrid(self):
        invalid=[None,{},[MOUNTS[0]],MOUNTS+[MOUNTS[0]],MOUNTS[:3]+[MOUNTS[0]],
                 [{'columnIndex':True,'rowIndex':0}]+MOUNTS[1:],
                 [{'columnIndex':0.0,'rowIndex':0}]+MOUNTS[1:],
                 [{'columnIndex':27,'rowIndex':0}]+MOUNTS[1:],
                 [{'columnIndex':0,'rowIndex':0,'xMm':12.5}]+MOUNTS[1:]]
        for holes in invalid:
            with self.subTest(holes=holes),self.assertRaises(BreadboardError):normalize_board({**BASE,'mountingHoles':holes})
    def test_mounts_require_25mm_coordinate_phases_and_real_web(self):
        with self.assertRaises(BreadboardError) as err:
            normalize_board({**BASE,'mountingHoles':[{'columnIndex':1,'rowIndex':0}]+MOUNTS[1:]})
        self.assertEqual(err.exception.code,'mounting_hole_spacing')
        for changes,code in [({'thicknessMm':8.4},'mounting_plate_too_thin'),
                             ({'edgeOffsetMm':5},'mounting_hole_near_edge')]:
            with self.subTest(changes=changes),self.assertRaises(BreadboardError) as err:
                normalize_board({**BASE,**changes,'mountingHoles':MOUNTS})
            self.assertEqual(err.exception.code,code)
        # Index spacing 5 with pitch 10 gives valid 50 mm coordinates, but
        # the retained neighboring M6 holes leave only 1.5 mm of material.
        with self.assertRaises(BreadboardError) as err:
            normalize_board({**BASE,'pitchMm':10,'edgeOffsetMm':10,'mountingHoles':[{'columnIndex':i,'rowIndex':j} for i in (0,20) for j in (0,10)]})
        self.assertEqual(err.exception.code,'mounting_hole_web')
        self.assertEqual(normalize_board({**BASE,'thicknessMm':8.5,'mountingHoles':MOUNTS})['thicknessMm'],8.5)
    def test_mounts_allow_staggered_four_holes_on_same_25mm_phase(self):
        holes=[{'columnIndex':i,'rowIndex':j} for i,j in [(0,0),(24,2),(2,14),(26,16)]]
        self.assertEqual(board_specs({**BASE,'mountingHoles':holes})['mountingHoleCount'],4)
    @unittest.skipUnless(os.environ.get('ZZLAB_TEST_CAD_PYTHON'),'set ZZLAB_TEST_CAD_PYTHON for CAD integration')
    def test_generate_verify_cache_and_reuse_offline(self):
        with tempfile.TemporaryDirectory() as td:
            a=ensure_board_artifacts(BASE,td,cad_python=os.environ['ZZLAB_TEST_CAD_PYTHON'])
            self.assertGreater(a['step'].stat().st_size,1000);self.assertGreater(a['drawing'].stat().st_size,1000)
            report=json.loads((a['step'].parent/'artifact.json').read_text())
            self.assertTrue(report['geometryValidation']['valid'])
            self.assertEqual(report['geometryValidation']['cylindricalHoleFaces'],459)
            stamp=a['step'].stat().st_mtime_ns
            with patch.dict(os.environ,{},clear=True):b=ensure_board_artifacts(BASE,td)
            self.assertEqual(a['step'],b['step']);self.assertEqual(b['step'].stat().st_mtime_ns,stamp)
            a['step'].write_text('bad cache')
            with patch.dict(os.environ,{},clear=True),self.assertRaises(BreadboardError):ensure_board_artifacts(BASE,td)
    @unittest.skipUnless(os.environ.get('ZZLAB_TEST_CAD_PYTHON'),'set ZZLAB_TEST_CAD_PYTHON for CAD integration')
    def test_generate_real_counterbores_and_two_sheet_drawing(self):
        with tempfile.TemporaryDirectory() as td:
            a=ensure_board_artifacts({**BASE,'mountingHoles':MOUNTS},td,cad_python=os.environ['ZZLAB_TEST_CAD_PYTHON'])
            report=json.loads((a['step'].parent/'artifact.json').read_text())
            g=report['geometryValidation']
            self.assertEqual((g['regularHoleCount'],g['mountingHoleCount'],g['cylindricalHoleFaces']),(455,4,463))
            self.assertAlmostEqual(g['volumeMm3'],g['analyticVolumeMm3'],places=4)
            self.assertEqual(report['drawing']['pageCount'],2)

if __name__=='__main__':unittest.main()
