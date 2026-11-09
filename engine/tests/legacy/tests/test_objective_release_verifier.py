"""Release acceptance remains read-only and refuses policy/geometry drift."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('verify_objective_boards_release',ROOT/'qa/verify_objective_boards_release.py')
verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)
POLICY={'guestAccessEnabled':False,'guestManufacturingDownloadsEnabled':True,'revision':4,'updatedAt':'2026-10-04T01:00:00Z'}

class ObjectiveReleaseVerifierTests(unittest.TestCase):
 def test_both_independent_guest_flags_and_revision_must_match(self):
  verify.policy_equal(POLICY,copy.deepcopy(POLICY),'test')
  for key,value in [('guestAccessEnabled',True),('guestManufacturingDownloadsEnabled',False),('revision',5)]:
   with self.assertRaises(RuntimeError):verify.policy_equal(POLICY,{**POLICY,key:value},'test')
  with self.assertRaises(RuntimeError):verify.policy_equal({'guestAccessEnabled':False},POLICY,'test')
 def test_get_cannot_send_payload_or_select_a_mutating_method(self):
  with patch.object(verify.deploy,'request_status',return_value=(200,b'{}')) as request:
   verify.get('http://127.0.0.1:1','/api/catalog',{'test':'local'})
   request.assert_called_once_with('http://127.0.0.1:1/api/catalog',{'test':'local'},max_bytes=16*1024*1024)
 def test_baseline_capture_is_local_only_and_never_overwrites_original_evidence(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'baseline.json'
   with patch.object(verify,'headers',return_value={}),patch.object(verify,'policy',return_value=POLICY):
    verify.capture_baseline(path);saved=path.read_bytes()
    with self.assertRaises(RuntimeError):verify.capture_baseline(path)
   self.assertEqual(path.read_bytes(),saved);self.assertEqual(json.loads(saved)['policy'],POLICY)
 def test_actual_source_audit_checks_catalog_without_service_requests(self):
  # Version bump belongs to the release owner; never edit the working catalog in a test.
  catalog=verify.load_catalog(ROOT/'catalog.json');catalog['version']=verify.VERSION
  with patch.object(verify,'load_catalog',return_value=catalog),patch.object(verify.deploy,'request_status',side_effect=AssertionError('No network in local audit')):
   source,hashes,audit=verify.source_inventory(ROOT)
  self.assertEqual(len(audit['boards']),5);self.assertTrue(audit['objective']['defaultExisting']);self.assertEqual(source['version'],'2026-10-04.2')
  self.assertIn('registered_boards.py',hashes)
  for name in verify.NEW_JS:self.assertIn('static/'+name,hashes)
  self.assertEqual(len([name for name in hashes if name.startswith('assets/step/OpticalFrame/')]),5)
  changed=copy.deepcopy(catalog);changed['registeredBoards'][0]['holesMm'][0]['type']='clearance'
  with patch.object(verify,'load_catalog',return_value=changed),self.assertRaises(RuntimeError):verify.source_inventory(ROOT)

if __name__=='__main__':unittest.main()
