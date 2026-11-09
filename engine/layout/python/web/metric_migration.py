"""Same data-only migration as static/metric-migration.js; never edits a database."""
from copy import deepcopy

CAPABILITY = 'zzlab-metric-supports-v1'
REVISION = 'metric-62p5-20261006'


def migrate(project, catalog):
    rule = catalog.get('universalPostSeries', {}).get('metricMigration', {})
    if rule.get('revision') != REVISION or not isinstance(project, dict):
        return project, []
    if 'requires' in project and (not isinstance(project['requires'], list) or any(not isinstance(x, str) for x in project['requires'])):
        return project, []
    result, changes = deepcopy(project), []
    layout = result.get('layout')
    if not isinstance(layout, dict):
        return project, changes
    legacy = CAPABILITY not in result.get('requires', []) if isinstance(result.get('requires', []), list) else True
    mapping = rule.get('componentMap', {})
    kits = {k['id']: k for k in catalog.get('kits', [])}
    for item in layout.get('instances', []) if isinstance(layout.get('instances'), list) else []:
        if not isinstance(item, dict):
            continue
        refs = {r['componentId'] for r in kits.get(item.get('kitId'), {}).get('components', [])}
        old_series = item.get('kitId') in rule.get('legacyKitIds', []) and legacy
        selection = item.get('universalPostSelection')
        if isinstance(selection, dict):
            new = {}
            for key, value in selection.items():
                nk = mapping[key] if key in mapping and mapping[key] in refs else key
                nv = mapping.get(value, value) if isinstance(value, str) else value
                if nk in new:
                    return project, []
                new[nk] = nv
                if (key, value) != (nk, nv):
                    old_series = True
                    changes.append(dict(instanceId=item.get('id'), field='universalPostSelection', **{'from': [key, value], 'to': [nk, nv]}))
            item['universalPostSelection'] = new
        height = item.get('elevationMm')
        if old_series and not item.get('boardId') and type(height) in (int, float) and height > 0:
            steps = height / 12.7
            if abs(steps - round(steps)) < 1e-7:
                item['elevationMm'] = round(steps) * 12.5
                changes.append(dict(instanceId=item.get('id'), field='elevationMm', **{'from': height, 'to': item['elevationMm']}))
    if legacy:
        plates = layout.get('subBoards', [])
        for entry in [{'id': 'base', 'board': layout.get('board')}] + (plates if isinstance(plates, list) else []):
            b = entry.get('board') if isinstance(entry, dict) else None
            if isinstance(b, dict) and not b.get('registeredBoardId') and b.get('thicknessMm') == 12.7:
                b['thicknessMm'] = 12.5
                changes.append(dict(boardId=entry.get('id'), field='thicknessMm', **{'from': 12.7, 'to': 12.5}))
        changes.append(dict(field='catalogVersion', **{'from': result.get('catalogVersion'), 'to': catalog.get('version')}))
        result['catalogVersion'] = catalog.get('version')
        result['requires'] = [*(result.get('requires', []) if isinstance(result.get('requires', []), list) else []), CAPABILITY]
    return result, changes
