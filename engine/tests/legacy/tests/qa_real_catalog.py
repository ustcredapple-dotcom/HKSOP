"""Run the delivered real catalog through physical, BOM and artifact contracts."""
import copy
import hashlib
import io
import json
import math
import os
import sys
import zipfile
from pathlib import Path

from openpyxl import load_workbook
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bom import APIError, aggregate, load_catalog
from exports import export_result
from layout import footprint, transform_point

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT.parents[1]/'outputs'/'ZZLab光路套件网页交付'
OUT.mkdir(parents=True,exist_ok=True)
REPORT=ROOT/'work_backend_qa'/'real_catalog_report.json'
REPORT.parent.mkdir(parents=True,exist_ok=True)
os.environ['ZZLAB_CAD_PYTHON']='/Users/Shared/ZZLAB/OpticsKits/cad-venv/bin/python'
os.environ['ZZLAB_BOARD_CACHE']=str(ROOT/'work_backend_qa'/'stable_cad_cache')
catalog=load_catalog(ROOT/'catalog.json')
board={'widthMm':350,'heightMm':225,'pitchMm':12.5,'edgeOffsetMm':12.5,'thicknessMm':12.7,'holeType':'M6_through'}
report={'catalogVersion':catalog['version'],'catalogSha256':hashlib.sha256((ROOT/'catalog.json').read_bytes()).hexdigest(),'rotations':[],'legacyBundleMatrix':[],'disabledModules':[]}

def payload(instances, board_override=None, extras=None):
    return {'catalogVersion':catalog['version'],'layout':{'board':board_override or board,'instances':instances},'extras':extras or []}

def instance(iid,kid,x=175,y=112.5,rotation=0):
    return {'id':iid,'kitId':kid,'xMm':x,'yMm':y,'rotationDeg':rotation}

allowed=[k for k in catalog['kits'] if k['layout']['placementAllowed']]
disabled=[k for k in catalog['kits'] if not k['layout']['placementAllowed']]
assert len(allowed)+len(disabled)==len(catalog['kits'])
assert len({k['id'] for k in catalog['kits']})==len(catalog['kits'])
for kit in allowed:
    for rotation in (0,90,180,270):
        placed=instance('single',kit['id'],x=0,y=0,rotation=rotation)
        bounds=footprint(placed,kit['layout'])
        holes=kit['layout'].get('mountingHoleOffsetsMm',[])
        hole=holes[0] if holes else {'xMm':0,'yMm':0}
        hx,hy=transform_point(placed,(hole['xMm'],hole['yMm']))
        pitch,edge=board['pitchMm'],board['edgeOffsetMm']
        # Fit the full rotated footprint and align the mounting holes, not the
        # component centre; large instruments no longer fit the old 350x225 probe.
        placed['xMm']=edge+math.ceil((25-bounds['left']+hx-edge)/pitch)*pitch-hx
        placed['yMm']=edge+math.ceil((25-bounds['top']+hy-edge)/pitch)*pitch-hy
        probe_board={**board,
                     'widthMm':max(board['widthMm'],math.ceil((placed['xMm']+bounds['right']+25)/pitch)*pitch),
                     'heightMm':max(board['heightMm'],math.ceil((placed['yMm']+bounds['bottom']+25)/pitch)*pitch)}
        data=payload([placed],probe_board)
        preview=aggregate(catalog,data,require_items=True)
        assert preview['layoutValidation']['valid'],(kit['id'],rotation,preview['layoutValidation'])
        assert preview['totals']['boards']==1
        svg,_,_=export_result(preview,'layout-svg',ROOT/'assets',ROOT/'static')
        assert b'data:image/svg+xml;base64,' in svg
        report['rotations'].append({'kitId':kit['id'],'rotationDeg':rotation,'valid':True,'svgBytes':len(svg)})
for kit in disabled:
    large={**board,'widthMm':700,'heightMm':500}
    preview=aggregate(catalog,payload([instance('module',kit['id'],350,250)],large),require_items=True)
    issues=preview['layoutValidation']['issues']
    assert any(i['code']=='placement_unavailable' and ('角孔' in i['message'] or '叠放' in i['message']) for i in issues),issues
    assert not any(i['code']=='out_of_bounds' for i in issues),issues
    for kind in ('lubang','manufacturing','bundle'):
        try:export_result(preview,kind,ROOT/'assets',ROOT/'static')
        except APIError as error:assert error.code=='layout_invalid'
        else:raise AssertionError((kit['id'],'disabled module exported'))
    export_result(preview,'layout-svg',ROOT/'assets',ROOT/'static')
    report['disabledModules'].append({'kitId':kit['id'],'issues':issues})
for kit in catalog['kits']:
    preview=aggregate(catalog,{'items':[{'kitId':kit['id'],'quantity':1}]},require_items=True)
    content,_,_=export_result(preview,'bundle',ROOT/'assets',ROOT/'static')
    outcome={'kitId':kit['id'],'bundle':'ok','bytes':len(content)}
    report['legacyBundleMatrix'].append(outcome)
assert {r['kitId'] for r in report['legacyBundleMatrix'] if r['bundle']=='ok'}=={k['id'] for k in catalog['kits']}

example=payload([instance('waveplate-1','waveplate',75,62.5),instance('waveplate-2','waveplate',150,62.5),
                 instance('mirror-1','fixed-1-90',62.5,150),instance('mirror-2','fixed-1-90',150,150),instance('mirror-3','fixed-1-90',237.5,150)])
preview=aggregate(catalog,example,require_items=True)
assert preview['layoutValidation']['valid'],preview['layoutValidation']
assert {r['model']:r['quantity'] for r in preview['lubang']}=={'CRM-1AS':4,'MT-FLF1S':3}
custom={r['componentId']:r['quantity'] for r in preview['manufacturing'] if not r.get('generatedBoard')}
assert custom=={'custom-01':5,'custom-07':2,'custom-13':3},custom
assert len([r for r in preview['manufacturing'] if r.get('generatedBoard') and r['quantity']==1])==1
for kind,suffix in (('bundle','zip'),('layout-json','json'),('layout-svg','svg')):
    content,_,_=export_result(preview,kind,ROOT/'assets',ROOT/'static')
    target=OUT/f'布局示例_2波片_3固定镜架.{suffix}'
    target.write_bytes(content)
    report.setdefault('exampleFiles',[]).append({'name':target.name,'size':len(content),'sha256':hashlib.sha256(content).hexdigest()})
    if kind=='bundle':
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert len([n for n in archive.namelist() if n.endswith('.step')])==4
            assert len([n for n in archive.namelist() if n.endswith('.pdf')])==4
            saved=json.loads(archive.read('套件配置.json'))
            for path,checksum in saved['fileChecksums'].items():assert hashlib.sha256(archive.read(path)).hexdigest()==checksum
            wb=load_workbook(io.BytesIO(archive.read('生产清单.xlsx')))
            amounts={row[1].value:row[4].value for row in wb['生产清单'].iter_rows(min_row=6)}
            assert amounts['custom-01']==5 and amounts['custom-07']==2 and amounts['custom-13']==3
            assert sum(row.get('generatedBoard',False) for row in saved['components'])==1
            assert wb['布局位置'].max_row==10
            assert '面包板规格' in wb.sheetnames
            generated_board=next(row for row in saved['components'] if row.get('generatedBoard'))
            (OUT/'参数面包板三视图.pdf').write_bytes(archive.read(saved['assets'][generated_board['componentId']]['drawing']))
            (OUT/'总俯视图.svg').write_bytes(archive.read('光路总俯视图.svg'))
            report['exampleArchiveFiles']=archive.namelist()
report['exampleBom']={'lubang':[{key:r[key] for key in ('model','quantity')} for r in preview['lubang']],
                      'manufacturing':[{key:r[key] for key in ('componentId','name','quantity')} for r in preview['manufacturing']]}

invalid=copy.deepcopy(example)
invalid['layout']['instances'][1].update(xMm=75,yMm=62.5)
bad=aggregate(catalog,invalid)
assert not bad['layoutValidation']['valid'] and bad['layoutValidation']['collisions']
for kind in ('lubang','manufacturing','bundle'):
    try:export_result(bad,kind,ROOT/'assets',ROOT/'static')
    except APIError as error:assert error.code=='layout_invalid'
    else:raise AssertionError('Real overlap exported')
for kind in ('layout-json','layout-svg'):export_result(bad,kind,ROOT/'assets',ROOT/'static')
report['overlapBlocked']=True

selected=copy.deepcopy(example)
selected['extras']=[{'id':'mirror-1-choice','kitId':'fixed-1-90','instanceId':'mirror-1','slotId':'mirror','kind':'lubang','name':'宽带介质膜平面反射镜','model':'BDM1-A','quantity':1,'unit':'片','wavelength':'532 nm','notes':''},
                    {'id':'mirror-2-choice','kitId':'fixed-1-90','instanceId':'mirror-2','slotId':'mirror','kind':'lubang','name':'宽带介质膜平面反射镜','model':'BDM1-B','quantity':1,'unit':'片','wavelength':'780 nm','notes':''}]
chosen=aggregate(catalog,selected)
models={r['model']:r['quantity'] for r in chosen['lubang']}
assert models=={'CRM-1AS':4,'MT-FLF1S':3,'BDM1-A':1,'BDM1-B':1},models
for model,iid in (('BDM1-A','mirror-1'),('BDM1-B','mirror-2')):
    row=next(r for r in chosen['lubang'] if r['model']==model)
    assert row['kits'][0]['instanceId']==iid and row['kits'][0]['quantity']==1
report['instanceOptics']={'passed':True,'modelQuantities':models}
pbs=payload([instance('pbs-1','pbs-fixed',75,112.5),instance('pbs-2','pbs-fixed',175,112.5)],extras=[{
    'id':'pbs-1-choice','kitId':'pbs-fixed','instanceId':'pbs-1','slotId':'pbs','kind':'lubang','name':'PBS 光学件','model':'MPBS24-780','quantity':1,'unit':'个','wavelength':'780 nm','notes':''}])
pbs_preview=aggregate(catalog,pbs)
models={r['model']:r['quantity'] for r in pbs_preview['lubang']}
assert models['MPBS24-532']==1 and models['MPBS24-780']==1 and models['PCMS1']==2,models
assert pbs_preview['replacements'][0]['totalQuantity']==1
report['instanceReplacement']={'passed':True,'modelQuantities':models}
report['summary']={'ordinaryKits':len(allowed),'validQuarterTurnChecks':len(report['rotations']),'disabledModules':len(disabled),'legacyBundlePass':len(report['legacyBundleMatrix']),'exampleUniqueStepFiles':4,'exampleUniqueDrawingFiles':4,'boardQuantity':1,'passed':True}
REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report['summary'],ensure_ascii=False))
print(json.dumps(report['exampleFiles'],ensure_ascii=False))
