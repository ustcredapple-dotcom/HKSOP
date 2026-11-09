"""Resolve captured source references inside HKSOP; never search old source trees."""
from pathlib import Path
import argparse,hashlib,json,shutil,zipfile

ROOT=Path(__file__).resolve().parents[2]
def read(path):return json.loads(Path(path).read_text())
def resolve(value,snapshot):
 ignored=ROOT/'config/ignored-legacy-references.json'
 if ignored.exists():
  exclusions=read(ignored)
  if value in exclusions['sourcePaths'] or value in exclusions['referenceValues']:raise ValueError('This obsolete reference was excluded by the user')
 index=ROOT/'migration/source-path-index.json'
 if index.exists():
  row=read(index)['entries'].get(value)
  if row:return row
 if snapshot!='web-current':raise ValueError('Historical library snapshots are not retained')
 assets=read(ROOT/'library/snapshots'/snapshot/'assets.json')
 matches=[r for r in assets['resources'] if value in (r['source'],r['logical'],r['kind']+'/'+r['logical']) or any(u['value']==value for u in r['uses'])]
 if not matches:raise ValueError('Reference is not captured in HKSOP')
 if len({r['sha256'] for r in matches})!=1:raise ValueError('Reference is ambiguous; specify its exact snapshot/source path')
 return matches[0]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['resolve','extract']);p.add_argument('reference');p.add_argument('--snapshot',default='web-current');p.add_argument('--output',type=Path);a=p.parse_args()
 row=resolve(a.reference,a.snapshot);location=(ROOT/(row.get('stored') or row['archive'])).resolve()
 if not any(location.is_relative_to((ROOT/x).resolve()) for x in ('library/assets','projects')):raise ValueError('Asset path escaped the retained content roots')
 if a.action=='resolve':print(json.dumps({'path':str(location),'member':row.get('member'),'sha256':row['sha256'],'size':row['size']},ensure_ascii=False,indent=2));return
 if not a.output:raise ValueError('--output is required')
 a.output.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256();size=0
 with a.output.open('xb') as out:
  if 'stored' in row:
   with location.open('rb') as source:
    while data:=source.read(4*1024*1024):h.update(data);out.write(data);size+=len(data)
  else:
   with zipfile.ZipFile(location) as z,z.open(row['member']) as source:
    while data:=source.read(4*1024*1024):h.update(data);out.write(data);size+=len(data)
 if h.hexdigest()!=row['sha256'] or size!=row['size']:raise ValueError('Extracted asset checksum or size mismatch')
 print(json.dumps({'output':str(a.output.resolve()),'sha256':h.hexdigest(),'bytes':size},ensure_ascii=False))
if __name__=='__main__':main()
