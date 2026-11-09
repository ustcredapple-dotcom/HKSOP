"""Dependency plan for incrementally patching the ZZLab machining atlas.

The compositor copies unchanged PDF pages and only redraws changed page bodies.
Folio/TOC relinking is separate; it never invalidates a CAD image.
"""
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def view_signature(job):
    value = dict(style='zzlab-real-cad-front-side-orthographic-r2', sha256=job['sha256'],
                 recipe=job.get('recipe') or {}, displayRotation=job.get('displayRotation'),
                 includeNames=job.get('includeNames'), excludeNames=job.get('excludeNames'),
                 colors=job.get('colors'))
    indices = (job.get('recipe') or {}).get('excludeLeafIndices', job.get('excludeLeafIndices'))
    if indices is not None:
        value['excludeLeafIndices'] = indices
    for key in ('linearDeflectionMm', 'angularDeflectionRad'):
        if key in job:
            value[key] = job[key]
    return digest(value)


def required_views(manifest):
    jobs = {s['viewJob'] for s in manifest['sections'] if s.get('viewJob')}
    missing = [p for p in manifest['parts'] if not p.get('drawingPath')]
    jobs.update(p['viewJob'] for p in missing if not p['isPost'] and p.get('viewJob'))
    posts = [p for p in missing if p['isPost']]
    if posts:
        jobs.add(posts[0]['viewJob'])
    return jobs


def normalized(value):
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items()
                if k not in ('sourceOriginal', 'sourceCad', 'sourceMode', 'sourceUrl')
                and not k.endswith('Path')}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


class PageDependencies:
    def __init__(self, manifest, page_map):
        self.m, self.map = manifest, page_map
        self.parts = {p['id']: p for p in manifest['parts']}
        self.sections = {s['id']: s for s in manifest['sections']}
        self.jobs = {j['id']: j for j in manifest['jobs']}

    def identity(self, item):
        kind = item['kind']
        if kind == 'drawing':
            return digest([kind, item['section'], sorted(item['parts']), item['sourcePage']])
        return digest([kind, item.get('section'), item.get('part'), item.get('slice')])

    def signature(self, item):
        kind = item['kind']
        inputs = {'kind': kind, 'layout': 'zzlab-atlas-body-v1'}
        def locations(ids):
            return {i: self.map['partLocations'][i] for i in ids}
        def view(job):
            return view_signature(self.jobs[job]) if job in self.jobs else None
        if kind == 'cover':
            inputs.update(catalog=self.m['catalogVersion'], kits=sum(len(s['members']) for s in self.sections.values()),
                          parts=len(self.parts), missing=sum(not p.get('drawingPath') for p in self.parts.values()))
        elif kind == 'guide':
            inputs['missing'] = sum(not p.get('drawingPath') for p in self.parts.values())
        elif kind in ('assembly', 'assemblyparts'):
            s = self.sections[item['section']]
            ids = s['parts'] + s['posts']
            inputs.update(section=normalized(s), parts=[normalized(self.parts[p]) for p in ids],
                          locations=locations(ids), view=view(s.get('viewJob')),
                          localLocations={p: [n for n in self.map['partLocations'][p]
                                              if self.map['plan'][n-1].get('section') == s['id']] for p in s['parts']})
        elif kind == 'drawing':
            s = self.sections.get(item['section']) or {}
            inputs.update(source=self.parts[item['parts'][0]]['drawingSha256'], sourcePage=item['sourcePage'],
                          section=[s.get('code'), s.get('name'), item['section']],
                          labels=[[p, self.parts[p]['code'], self.parts[p]['name']] for p in item['parts']])
        elif kind in ('missingpart', 'partcard'):
            p = self.parts[item['part']]
            inputs.update(part=normalized(p), locations=locations([p['id']]), view=view(p.get('viewJob')))
        elif kind == 'kitindex':
            inputs['rows'] = [[m['id'], m['name'], s['code'], len({b['componentId'] for b in m['bom'] if b['componentId'] in self.parts}),
                               self.map['kitLocations'][m['id']]] for m, s in item['rows']]
        elif kind in ('partindex', 'missingindex', 'common', 'smallposts', 'orphanintro', 'referenceintro'):
            inputs['rows'] = normalized(item['rows'])
            if kind not in ('referenceintro',):
                inputs['locations'] = locations([p['id'] for p in item['rows']])
            if kind == 'smallposts':
                inputs['view'] = view(item['rows'][0].get('viewJob'))
        else:
            raise ValueError('Unknown page kind; define its dependencies before reusing it: ' + kind)
        return digest(inputs)


def plan_update(manifest, page_map, old_manifest, old_map):
    new = PageDependencies(manifest, page_map)
    old = PageDependencies(old_manifest, old_map)
    prior = {}
    for n, item in enumerate(old_map['plan'], 1):
        key = old.identity(item)
        if key in prior:
            raise ValueError('Ambiguous old page identity: ' + key)
        prior[key] = (n, old.signature(item))
    result, seen = [], set()
    for n, item in enumerate(page_map['plan'], 1):
        key = new.identity(item)
        if key in seen:
            raise ValueError('Ambiguous new page identity: ' + key)
        seen.add(key)
        previous = prior.get(key)
        unchanged = previous and previous[1] == new.signature(item)
        result.append(dict(page=n, key=key, action='reuse' if unchanged else 'redraw',
                           previousPage=previous[0] if previous else None, signature=new.signature(item)))
    removed = [v[0] for key, v in prior.items() if key not in seen]
    return {'format': 'zzlab-atlas-delta-v1', 'pages': result, 'removedPages': removed,
            'redrawPages': [p['page'] for p in result if p['action'] == 'redraw'],
            'reusedPages': sum(p['action'] == 'reuse' for p in result)}
