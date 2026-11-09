"""Inspect or verify a current HKSOP project without materializing old revisions."""
from pathlib import Path
import argparse,hashlib,json

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['inspect','verify']);p.add_argument('project',type=Path);a=p.parse_args()
 base=a.project.resolve();base=base.parent if base.is_file() else base
 info=json.loads((base/'project.json').read_text())
 if info.get('format')!='hksop-project-v2':raise ValueError('Expected a current project.json')
 if a.action=='inspect':print(json.dumps(info,ensure_ascii=False,indent=2));return
 results=json.loads((base/'results/index.json').read_text())['files'];rows=results+info.get('history',[])+info.get('modules',[])
 if info.get('currentEngineering'):rows.append(info['currentEngineering'])
 for row in rows:
  source=(base/row['path']).resolve()
  if not source.is_relative_to(base):raise ValueError('Project path escapes its root')
  h=hashlib.sha256()
  with source.open('rb') as f:
   while data:=f.read(4*1024*1024):h.update(data)
  if h.hexdigest()!=row['sha256']:raise ValueError('File checksum mismatch: '+row['path'])
 print(json.dumps({'project':info['name'],'verifiedFiles':len(rows),'passed':True},ensure_ascii=False))
if __name__=='__main__':main()
