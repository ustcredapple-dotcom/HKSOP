#!/usr/bin/env python3
"""Derive interaction + port indexes from real production normalizers.

Generate: python tools/build-interaction-index.py --node /path/to/node
Check without Node: python tools/build-interaction-index.py --check
All outputs are sidecars; source catalog, assets and saved projects are untouched.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

REQUIRED_RUNTIME = {'manual_source_mount.py','static/manual-source-mount.js','collision_overrides.py', 'static/collision-overrides.js', 'moving_stages.py', 'static/moving-stages.js', 'bom.py', 'tools/library.py', 'static/global-height.js', 'static/optical-engine.js', 'static/fixed-board-optics.js', 'static/optical-renderer.js',
                    'static/optical-interaction-language.js', 'optical_interaction.py',
                    'tools/build-interaction-index.py', 'tools/build-interaction-index.cjs'}
def sha(value):
    return hashlib.sha256(value).hexdigest()
def record_sha(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8'))
def load(path):
    return json.loads(path.read_bytes())
def check_index(index, catalog, raw, root):
    if index.get('sourceCatalogSha256') != sha(raw):
        raise ValueError('Catalog changed; regenerate interaction indexes')
    for key in ('kits', 'registeredBoards', *(('stageModules',) if catalog.get('stageModules') else ())):
        expected = {r['id']: record_sha(r) for r in catalog[key]}
        records = index.get(key, [])
        actual = {r['id']: r['sourceRecordSha256'] for r in records}
        if len(records) != len(actual) or actual != expected:
            raise ValueError(f'{key} record hashes/IDs are stale or duplicate')
    runtime = index.get('derivation', {}).get('runtimeFiles', [])
    paths = {r['path'] for r in runtime}
    if len(paths) != len(runtime) or not REQUIRED_RUNTIME <= paths:
        raise ValueError('Derived index omits required runtime/build sources')
    for row in runtime:
        file = (root / row['path']).resolve()
        if not file.is_relative_to(root) or not file.is_file() or sha(file.read_bytes()) != row['sha256']:
            raise ValueError(f"Runtime changed: {row['path']}; regenerate interaction indexes")

def port_index(catalog, interaction):
    common = {k: interaction[k] for k in ('catalogVersion', 'sourceCatalogSha256', 'derivation', 'counts')}
    templates = {
        'mirror': {'operator':'mirror','direction':'specular-reflection-at-actual-plane','height':'preserved','power':'Rp/Rs-dependent','polarization':'measured-phase-or-explicit-ideal','gaussian':'q-preserved'},
        'pbs': {'operator':'pbs','direction':'transmitted-and-reflected-at-actual-plane','height':'preserved','power':'ideal-(1+s1)/2-and-(1-s1)/2','polarization':'P-transmitted-S-reflected','gaussian':'q-copied'},
        'waveplate': {'operator':'waveplate','direction':'unchanged','height':'preserved','power':'lossless-model','polarization':'confirmed-retardance-and-fast-axis; reverse-physical-sequence','gaussian':'q-preserved'},
        'lens': {'operator':'lens','direction':'paraxial-slope-with-local-offset','height':'preserved','power':'preserved-no-invented-clipping-loss','polarization':'preserved','gaussian':'thin-lens-q-transform'},
        'coupler': {'operator':'coupler','direction':'receiver-opposite-source-output','height':'actual-source-height-required','power':'terminated-ideal-coupling; configured-source-can-emit','polarization':'source-setting-on-emission','gaussian':'source-q-on-emission'},
        'source': {'operator':'source-emission','direction':'actual-catalog-port-plus-instance-rotation','height':'verified-effective-axis-height','power':'source-setting','polarization':'source-setting','gaussian':'source-diameter-wavefront-and-M2'},
        'empty': {'operator':'confirmed-pass','direction':'unchanged','height':'must-match','power':'preserved','polarization':'preserved','gaussian':'q-preserved'},
        'unknown': {'operator':None,'direction':'unknown','height':'do-not-invent','power':'unknown','polarization':'unknown','gaussian':'unknown','note':'Runtime legacy lens fallback is not a confirmed lens; declare unknown until reviewed.'},
        'unsupported': {'operator':'block','note':'Layout/procurement possible; optical propagation requires a supported explicit declaration and valid datum.'},
        'objective-internal': {'operator':'existing-verified-3d-assembly','note':'Existing internal plane engine and side view; not generic v1 DSL. Real internal surfaces/bases determine direction and Z; no invented objective focal plane.'},
        'moving-mechanical-board': {'operator':None,'note':'Only a trusted moving-stage sub-board container; fixed datum and moving children, exact stack height. No standalone optical surface.'},
        'mechanical-board': {'operator':None,'note':'Actual outline/cutout module boundary and mounted-child transforms; not an optical surface.'},
        'declared': {'operator':'finite-v1-interpreter','note':'Use record.program; inputs and operators are interpreted. Unknown op/version and ambiguous input fail closed.'}
    }
    by_id = {r['id']:r for r in catalog['kits']}
    kits=[]
    for item in interaction['kits']:
        record = by_id[item['id']]; layout = record.get('layout', {}); program = layout.get('opticalInteraction')
        unknown = item['typeBinding']['basis'] == 'unknown-legacy-lens-fallback'
        template = ('moving-mechanical-board' if record.get('stageModuleId') else 'declared' if program else 'objective-internal' if layout.get('opticalAssembly') else
                    'unknown' if unknown else item['typeBinding']['effectiveRuntimeType'])
        if template not in templates: template='unknown'
        kits.append({
            'id':item['id'], 'name':item['name'], 'objectType':'kit', 'sourceRecordSha256':item['sourceRecordSha256'],
            'contractState':'declared' if program else 'legacy-derived', 'templateId':template,
            'physicalClassification':'unknown' if unknown else item['typeBinding']['contractPhysicalType'],
            'legacyTypeBinding':item['typeBinding'], 'program':program,
            'geometry':{k:layout.get(k) for k in ('opticalCenterMm','opticalPortsMm','opticalAxisHeightMm','opticalAxisHeightSource','opticalDirectionDeg','opticalSurfaceAngleDeg','opticalDatumVerified')},
            'internalAssembly':layout.get('opticalAssembly'),
            'acceptance':{'position':'existing-optical-plane/real-port-intersection','direction':'program-input-conditions' if program else 'legacy-operator-specific',
                          'height':'known-effective-height-after-parent-board-and-elevation; must-match',
                          'aperture':'instance-clearApertureMm; clipping-warns-without-inventing-loss',
                          'wavelength':'declared-program-policy plus physical-operator-data' if program else 'existing-operator-data-policy',
                          'configuration':'instance-inserted/configured; confirmed-empty-passes'},
            'defaultInstance':item['simulation']['freshInstanceConfig'],
            'defaultInstanceIsEvidence':False,
            'sourcePrerequisitesMet':item['simulation']['sourceEmissionCatalogPrerequisitesMet'],
            'issues':item['warnings']})
    boards=[{'id':b['id'],'name':b['name'],'objectType':'registered-board','sourceRecordSha256':b['sourceRecordSha256'],
             'contractState':'legacy-derived','templateId':'mechanical-board','program':None,
             'interaction':'module-entry-and-child-transform; board-itself-is-not-optical-surface',
             'simulation':b['simulation'],'revision':b['revision']} for b in interaction['registeredBoards']]
    return {'schema':'zzlab-port-index-v1','libraryProtocol':'zzlab-optics-library-v1',
            'languageFormat':'zzlab-optical-interaction','languageVersion':1, **common,
            'units':{'length':'mm','wavelength':'nm','power':'mW','angle':'degree','origin':'catalog-anchor; local XY +X right +Y up'},
            'templates':templates,'kits':kits,'registeredBoards':boards,'stageModules':interaction.get('stageModules',[]),
            'limitations':'Derived sidecar only. Legacy-derived does not mean a runtime DSL is declared. No catalog/project mutation or physical certification. Unknowns retained.'}

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    temporary.replace(path)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--ports-output', type=Path)
    parser.add_argument('--node', default='node')
    parser.add_argument('--check', action='store_true', help='Check source hashes and membership without requiring Node')
    args=parser.parse_args();root=args.root.resolve();catalog_path=(args.catalog or root/'catalog.json').resolve()
    output=args.output or root/'library/generated/interaction-index.json'
    ports_output=args.ports_output or root/'library/generated/port-index.json'
    raw=catalog_path.read_bytes();catalog=json.loads(raw)
    if args.check:
        for path in (output,ports_output):check_index(load(path),catalog,raw,root)
        print(json.dumps({'valid':True,'checked':[str(output),str(ports_output)]},ensure_ascii=False));return
    result=json.loads(subprocess.check_output([args.node,str(Path(__file__).with_suffix('.cjs')),str(root),str(catalog_path)]))
    for key in ('kits','registeredBoards', *(('stageModules',) if catalog.get('stageModules') else ())):
        by_id={r['id']:r for r in catalog[key]}
        if len(by_id)!=len(catalog[key]) or set(by_id)!={r['id'] for r in result[key]}:raise ValueError(f'{key}: bad ID membership')
        for r in result[key]:r['sourceRecordSha256']=record_sha(by_id[r['id']])
    ports=port_index(catalog,result)
    for value in (result,ports):check_index(value,catalog,raw,root)
    if catalog_path.read_bytes()!=raw:raise ValueError('Catalog changed during derivation')
    write(output,result);write(ports_output,ports)
    print(json.dumps({'valid':True,'counts':result['counts'],'outputs':[str(output.resolve()),str(ports_output.resolve())]},ensure_ascii=False))
if __name__=='__main__':main()
