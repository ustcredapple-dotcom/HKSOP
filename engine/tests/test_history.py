"""Focused retention tests; synthetic packages never touch the real library."""
import copy, hashlib, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'compiler'))
import history, cli

class HistoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  data=b'old STEP';sha=hashlib.sha256(data).hexdigest();self.stored='library/assets/sha256/'+sha[:2]+'/'+sha+'.step';p=self.root/self.stored;p.parent.mkdir(parents=True);p.write_bytes(data)
  self.assets={'links':{'assets/step/old.step':self.stored},'replacements':{'step/old.step':'step/old.step'},'resources':[]}
  self.old={'version':'A','components':[{'id':'leaf','revision':'1','stepPath':'step/old.step'},{'id':'part','revision':'1','componentId':'leaf'}],'kits':[{'id':'kit','revision':'1','name':'Old','components':[{'componentId':'part','quantity':1}]}],'registeredBoards':[]}
  self.registry={'packages':[],'order':{k:[r['id']for r in self.old[k]]for k in cli.KINDS}}
 def tearDown(self):self.tmp.cleanup()
 def changed(self):
  value=copy.deepcopy(self.old);value['version']='C';value['components'][0]['revision']='2';return value
 def test_nested_dependency_and_unchanged_catalog_ledger(self):
  history.observe_catalog(self.root,self.old);middle=copy.deepcopy(self.old);middle['version']='B';history.observe_catalog(self.root,middle)
  plan=history.plan_update(self.root,middle,self.changed(),self.assets)
  self.assertEqual(len(plan['records']),3)
  kit=next(e for e in plan['entries']if e['kind']=='kits');self.assertEqual(kit['catalogVersions'],['A','B'])
  self.assertNotEqual(history.identity(self.old['kits'][0],{r['id']:r for r in self.old['components']}),history.identity(self.old['kits'][0],{r['id']:r for r in self.changed()['components']}))
  rows={r['lifecycle']['originalId']:r for _,r in plan['records']}
  self.assertEqual(rows['kit']['components'][0]['componentId'],rows['part']['id']);self.assertEqual(rows['part']['componentId'],rows['leaf']['id'])
 def test_merge_history_and_reuse(self):
  p=history.plan_update(self.root,self.old,self.changed(),self.assets);history.install(self.root,p,self.registry)
  n=len(history.read_index(self.root)['entries']);again=history.plan_update(self.root,self.old,self.changed(),self.assets);self.assertFalse(again['records']);history.install(self.root,again,self.registry);self.assertEqual(len(history.read_index(self.root)['entries']),n)
  before=self.changed();before['version']='D';after=copy.deepcopy(before);after['components'][0]['revision']='3';history.install(self.root,history.plan_update(self.root,before,after,self.assets),self.registry);self.assertEqual(len(history.read_index(self.root)['entries']),2*n)
 def test_missing_corrupt_and_unregistered_assets_rejected_before_write(self):
  p=history.plan_update(self.root,self.old,self.changed(),self.assets)
  (self.root/self.stored).write_bytes(b'corrupt')
  with self.assertRaisesRegex(ValueError,'hash mismatch'):history.install(self.root,p,self.registry)
  self.assertFalse((self.root/'library/history').exists());(self.root/self.stored).unlink()
  with self.assertRaisesRegex(ValueError,'missing'):history.install(self.root,p,self.registry)
  with self.assertRaisesRegex(ValueError,'not registered'):history.plan_update(self.root,self.old,self.changed(),{'links':{},'replacements':{}})
 def test_explicit_update_choice(self):
  with self.assertRaisesRegex(ValueError,'explicit --history'):cli.history_choice(self.old,self.changed(),None)
  self.assertEqual(cli.history_choice(self.old,self.changed(),'discard'),'discard')
  self.assertEqual(cli.history_choice(self.old,self.changed(),'retain'),'retain')
  added=copy.deepcopy(self.old);added['kits'].append({'id':'new'});self.assertIsNone(cli.history_choice(self.old,added,None))
 def test_paired_browser_url_uses_frozen_preview(self):
  sha='a'*64;assets={'links':{'static/topviews/restored.svg':'library/assets/sha256/aa/'+sha+'.svg'},'replacements':{}}
  record={'layout':{'topViewPath':'topviews/restored.svg','topViewUrl':'./topviews/stale.svg'}}
  frozen,refs=history.freeze_resources(record,assets)
  self.assertEqual(frozen['layout']['topViewUrl'],'./'+frozen['layout']['topViewPath']);self.assertIn(sha,frozen['layout']['topViewUrl'])
 def test_reused_logical_filename_binds_history_to_old_content(self):
  self.setup_transaction();plan=history.plan_update(self.root,self.old,self.changed(),self.assets);history.install(self.root,plan,self.registry)
  data=b'new STEP';sha=hashlib.sha256(data).hexdigest();stored='library/assets/sha256/'+sha[:2]+'/'+sha+'.step';p=self.root/stored;p.parent.mkdir(parents=True);p.write_bytes(data)
  assets=copy.deepcopy(self.assets);assets['links']['assets/step/old.step']=stored;cli.write(self.root/'library/registry.json',self.registry)
  with patch.object(cli,'ROOT',self.root),patch.object(cli,'validate_legacy',return_value=True):
   current=cli.source_catalog();assets=cli.current_assets(current,assets);cli.write(self.root/'library/snapshots/web-current/assets.json',assets)
   built=cli.compile_catalog();catalog=cli.read(built/'catalog.json');oldpart=next(r for r in catalog['components']if r.get('lifecycle',{}).get('originalId')=='leaf')
   self.assertIn(Path(self.stored).stem,oldpart['stepPath']);self.assertNotIn(sha,oldpart['stepPath'])
   cli.collect_unused_assets(assets);self.assertTrue((self.root/self.stored).is_file());self.assertTrue((self.root/stored).is_file())
 def test_resources_browse_export_and_gc_protection(self):
  plan=history.plan_update(self.root,self.old,self.changed(),self.assets);history.install(self.root,plan,self.registry)
  cli.write(self.root/'library/registry.json',self.registry)
  with patch.object(cli,'ROOT',self.root):
   assets=cli.current_assets(self.changed(),self.assets);cli.refresh_package_resources(assets,[plan['packagePath']])
   resource=cli.read((self.root/plan['packagePath']).parent/'resource-map.json');self.assertEqual(len(resource['files']),1);self.assertTrue(((self.root/plan['packagePath']).parent/resource['files'][0]['path']).is_file())
   cli.export_package(self.root/plan['packagePath'],self.root/'history.zip')
   kept=cli.current_assets({'components':[],'kits':[],'registeredBoards':[]},self.assets);self.assertIn(self.stored,kept['links'].values());self.assertEqual(cli.collect_unused_assets(kept),0)
 def setup_transaction(self):
  package=self.root/'library/standard/base';package.mkdir(parents=True)
  manifest={'format':'hksop-package-v1','packageId':'base','records':[],'assets':[]}
  for kind in cli.KINDS:
   for row in self.old[kind]:
    rel=row['id']+'.json';cli.write(package/rel,row);manifest['records'].append({'kind':kind,'path':rel})
  cli.write(package/'package.json',manifest);self.registry['packages']=['library/standard/base/package.json'];cli.write(self.root/'library/registry.json',self.registry);cli.write(self.root/'library/catalog-meta.json',{'version':'A'});cli.write(self.root/'library/snapshots/web-current/assets.json',self.assets)
  import shutil
  incoming=self.root/'incoming';shutil.copytree(package,incoming);row=cli.read(incoming/'kit.json');row['name']='New';cli.write(incoming/'kit.json',row)
  return incoming
 def test_adopt_retain_discard_and_failure_rollback(self):
  incoming=self.setup_transaction()
  def compile_mock(*args):
   history.observe_catalog(self.root,cli.source_catalog());out=self.root/'library/_build/web-current';out.mkdir(parents=True,exist_ok=True);return out
  with patch.object(cli,'ROOT',self.root),patch.object(cli,'validate_legacy',return_value=True),patch.object(cli,'compile_catalog',side_effect=compile_mock):
   with self.assertRaisesRegex(ValueError,'explicit --history'):cli.stage_package(incoming)
   stage=cli.stage_package(incoming,history='retain');(self.root/self.stored).write_bytes(b'bad')
   with self.assertRaisesRegex(ValueError,'hash mismatch'):cli.adopt_stage(stage)
   self.assertEqual(cli.source_catalog()['kits'][0]['name'],'Old');self.assertFalse(list((self.root/'library/history').glob('retained-*')))
   (self.root/self.stored).write_bytes(b'old STEP');stage=cli.stage_package(incoming,history='retain');cli.adopt_stage(stage)
   before=history.read_index(self.root);self.assertEqual(len(before['entries']),3);self.assertEqual(cli.read(self.root/'runtime/last-adoption.json')['historyPolicy'],'retain')
   row=cli.read(incoming/'kit.json');row['name']='Third';cli.write(incoming/'kit.json',row);stage=cli.stage_package(incoming,history='discard');cli.adopt_stage(stage)
   self.assertEqual(history.read_index(self.root)['entries'],before['entries']);self.assertEqual(cli.read(self.root/'runtime/last-adoption.json')['historyPolicy'],'discard')

if __name__=='__main__':unittest.main(verbosity=2)
