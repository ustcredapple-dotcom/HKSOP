"""Refresh the real PBS + 0.5-inch motor example after catalog/material changes."""
import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bom import aggregate, load_catalog
from exports import export_result
from layout import choose_mounting_holes
from test_fine_collision_mounting import user_fixture

os.environ.setdefault('ZZLAB_CAD_PYTHON', '/Users/Shared/ZZLAB/OpticsKits/cad-venv/bin/python')
os.environ.setdefault('ZZLAB_BOARD_CACHE', str(ROOT / 'work_backend_qa/stable_cad_cache'))
catalog = load_catalog(ROOT / 'catalog.json')
payload = user_fixture()
payload['catalogVersion'] = catalog['version']
selected = choose_mounting_holes(catalog, {**payload, 'rowParity': 'even', 'columnParity': 'odd'})
payload['layout']['board'] = selected['board']
preview = aggregate(catalog, payload, require_items=True)
assert preview['layoutValidation']['valid'], preview['layoutValidation']
assert not any(row['componentId'] == 'motor-bracket-23' for row in preview['manufacturing'])
board = next(row for row in preview['manufacturing'] if row.get('generatedBoard'))
assert board['quantity'] == 1
spec = board['boardSpec']
expected_coordinates = [(12.5, 25.0), (337.5, 25.0), (12.5, 200.0), (337.5, 200.0)]
assert [(hole['xMm'], hole['yMm']) for hole in spec['mountingHoles']] == expected_coordinates
assert (spec['material'], spec['surfaceTreatment']) == ('6061 铝合金', '黑色阳极氧化')
assert spec['regularHoleCount'] == 455 and spec['mountingHoleCount'] == 4
files = {}
for kind, suffix in [('bundle', 'zip'), ('layout-json', 'json'), ('layout-svg', 'svg')]:
    files[f'示例_精细轮廓与四角沉孔.{suffix}'] = export_result(preview, kind, ROOT / 'assets', ROOT / 'static')[0]
with zipfile.ZipFile(io.BytesIO(files['示例_精细轮廓与四角沉孔.zip'])) as archive:
    names = archive.namelist()
    assert not any('motor-bracket-23' in name or '支架2-3' in name for name in names)
    saved = json.loads(archive.read('套件配置.json'))
    layout_json = json.loads(archive.read('光路布局.json'))
    standalone_json = json.loads(files['示例_精细轮廓与四角沉孔.json'])
    assert layout_json['boardSpecification'] == standalone_json['boardSpecification'] == spec
    wb = load_workbook(io.BytesIO(archive.read('生产清单.xlsx')))
    positions = [(row[3].value, row[4].value) for row in wb['面包板固定孔'].iter_rows(min_row=6)]
    assert positions == expected_coordinates
    production = {row[1].value: row for row in wb['生产清单'].iter_rows(min_row=6)}
    for row in preview['manufacturing']:
        exported = production[row['componentId']]
        assert exported[4].value == row['quantity']
        assert (exported[12].value, exported[13].value) == (row['manufacturingSpec']['material'], row['manufacturingSpec']['surfaceTreatment'])
    assert wb['生产清单'].max_column == 14
    files['示例_生产任务清单.xlsx'] = archive.read('生产清单.xlsx')
    files['示例_四角圆柱沉孔面包板三视图.pdf'] = archive.read(saved['assets'][board['componentId']]['drawing'])
    assert len([name for name in names if name.endswith('.step')]) == len(preview['manufacturing']) == 9
    assert len([name for name in names if name.endswith('.pdf')]) == 9
    for path, checksum in saved['fileChecksums'].items():
        assert hashlib.sha256(archive.read(path)).hexdigest() == checksum
out = ROOT.parents[1] / 'outputs/ZZLab光路套件网页交付'
out.mkdir(parents=True, exist_ok=True)
report = {'catalogVersion': catalog['version'], 'passed': True, 'holes': expected_coordinates,
          'counterbore': spec['counterbore'], 'manufacturing': [{'componentId': row['componentId'], 'quantity': row['quantity'], 'manufacturingSpec': row['manufacturingSpec']} for row in preview['manufacturing']],
          'warnings': preview['warnings'], 'files': []}
for filename, content in files.items():
    (out / filename).write_bytes(content)
    report['files'].append({'name': filename, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
(ROOT / 'work_backend_qa/counterbore_material_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
