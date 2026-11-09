"""Resolve saved projects against committed local libraries, without migration."""
import json
import re
import stat
from bom import APIError


def compatible(catalog, project):
    """Candidate selection only; the normal project codec still validates input."""
    layout = project.get('layout', project)
    if not isinstance(layout, dict):
        return False
    boards = {r['id']: r for r in catalog.get('registeredBoards', [])}
    stages = {r['id']: r for r in catalog.get('stageModules', [])}
    kits = {r['id'] for r in catalog.get('kits', [])}
    try:
        for plate in [{'board': layout.get('board', {})}, *layout.get('subBoards', [])]:
            board = plate.get('board', {})
            if board.get('registeredBoardId'):
                row = boards.get(board['registeredBoardId'])
                if not row or row['revision'] != board.get('registeredBoardRevision'):
                    return False
            motion = plate.get('stageMotion')
            if motion:
                row = stages.get(motion['moduleId'])
                if not row or row['revision'] != motion.get('revision'):
                    return False
        refs = [i['kitId'] for i in layout.get('instances', [])]
        refs += [p[0] for p in project.get('moduleQuantities', [])]
        refs += [e['kitId'] for e in project.get('extras', []) if e.get('kitId')]
        return all(k in kits for k in refs)
    except (KeyError, TypeError, AttributeError, IndexError):
        return False


def resolve(library, project):
    if not isinstance(project, dict):
        raise APIError('invalid_project', '工程内容必须为 JSON 对象。')
    version = project.get('catalogVersion')
    if version is not None and (not isinstance(version, str) or len(version) > 200):
        raise APIError('invalid_project', '工程的元件库版本无效。')
    active = library.snapshot()
    if (not version or active[1][0].get('version') == version) and compatible(active[1][0], project):
        return active
    # Receipts are small; skip incomplete staging directories and load only
    # likely candidates. Never change the live library pointer for an old file.
    candidates = []
    for directory in sorted((library.root / 'data/libraries').iterdir(), reverse=True):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', directory.name):
            continue
        try:
            receipt_path = directory / 'receipt.json'
            # macOS cloud placeholders can block read() indefinitely. They are
            # not usable local caches; do not let an unrelated old one stall open.
            if any(getattr(p.stat(), 'st_flags', 0) & getattr(stat, 'SF_DATALESS', 0x40000000)
                   for p in (receipt_path, directory / 'catalog.json')):
                continue
            receipt = json.loads(receipt_path.read_text())
        except (OSError, ValueError):
            continue
        priority = 0 if version and receipt.get('version') == version else 1 if directory.name == library.active else 2
        if priority == 0:
            try:
                result = library.snapshot(directory.name)
                if compatible(result[1][0], project):
                    return result
            except (APIError, OSError, ValueError):
                pass
        candidates.append((priority, directory.name))
    candidates.sort(key=lambda item: item[1], reverse=True)
    candidates.sort(key=lambda item: item[0])
    for _, name in candidates:
        try:
            cached = library.snapshots.get(name)
            catalog = cached[0] if cached else json.loads((library.root / 'data/libraries' / name / 'catalog.json').read_text())
            from local_board_library import extend_catalog
            if not cached:catalog=extend_catalog(catalog,library.root)
            if not compatible(catalog, project):
                continue
            result = library.snapshot(name)
        except (APIError, OSError, ValueError):
            continue
        return result
    raise APIError('project_library_unavailable', '尚未找到包含此工程原板型版本的本地元件库。原工程已保留，请恢复对应版本的库缓存后重试。', 409)
