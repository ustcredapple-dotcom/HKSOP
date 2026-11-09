"""Read the website's published library; never write to the website or NAS."""
from pathlib import Path
import hashlib, json, os, re, shutil, tempfile, datetime, fcntl
from urllib.parse import urlsplit, unquote
from bom import load_catalog
ROOT = Path(__file__).resolve().parent
# UI-only upstream changes must not prevent ordinary catalog updates. A changed
# optical interpreter requires an explicit local engine upgrade, not a mixed run.
PROTOCOL_GUARDS = ('static/optical-engine.js', 'static/optical-assembly-engine.js',
    'static/optical-interaction-language.js', 'optical_interaction.py',
    'optics_settings.py', 'manufacturing_specs.json')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_or_restore_snapshot(stage, destination, hashes):
    """Restore missing cache entries atomically without replacing existing data."""
    for name, expected in hashes.items():
        target = destination/name
        # lexists keeps a broken symlink in the "existing, do not replace" case.
        if not os.path.lexists(target):
            if digest(stage/name) != expected:
                raise ValueError('本地回读校验失败：'+name)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(stage/name, target)
            except FileExistsError:
                pass  # Another receiver supplied it; verify its bytes below.
        if digest(target) != expected:
            raise ValueError('现有缓存已改变；未覆盖缓存。')


def source_path(root=ROOT):
    config = json.loads((root/'config.json').read_text())
    if config.get('librarySource') != 'web-runtime':
        raise ValueError('未配置网页版正式库源。')
    return Path(config['webLibraryRoot']).resolve(strict=True)


def source_signature(root=ROOT):
    """Cheap change signal; full byte hashes are checked on receive and audit."""
    source = source_path(root)
    paths = [source/'catalog.json', *(source/n for n in PROTOCOL_GUARDS)]
    paths += sorted(p for p in (source/'static/topviews').iterdir()
                    if p.suffix.lower() in ('.svg', '.png', '.webp'))
    signature = [str(source)]
    for path in paths:
        st = path.lstat()
        signature.append([str(path.relative_to(source)), st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino])
    return hashlib.sha256(json.dumps(signature).encode()).hexdigest()


def receive(root):
    source = source_path(root)
    release = source.name
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', release):
        raise ValueError('网页版发布标识无效，保留本地缓存。')
    signature = source_signature(root)
    upstream = json.loads((root/'upstream-manifest.json').read_text())
    for name in PROTOCOL_GUARDS:
        if digest(source/name) != upstream['sha256'][name]:
            raise ValueError('网页版光学协议引擎已升级，需更新本地引擎；现有工程与缓存保留。')
    libraries = root/'data/libraries'
    libraries.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.staging-', dir=libraries))
    try:
        old = None
        try:
            old_name = json.loads((root/'data/current.json').read_text())['release']
            if re.fullmatch(r'[A-Za-z0-9_-]{1,150}', old_name):
                old = libraries/old_name
        except (OSError, ValueError, KeyError):
            pass
        hashes = {}
        catalog_bytes = (source/'catalog.json').read_bytes()
        (stage/'catalog.json').write_bytes(catalog_bytes)
        hashes['catalog.json'] = hashlib.sha256(catalog_bytes).hexdigest()
        catalog = load_catalog(stage/'catalog.json')
        (stage/'topviews').mkdir()
        for path in sorted((source/'static/topviews').iterdir()):
            if path.suffix.lower() not in ('.svg', '.png', '.webp'):
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError('俯视图必须为正式发布的普通文件：'+path.name)
            data = path.read_bytes()
            name = 'topviews/'+path.name
            sha = hashlib.sha256(data).hexdigest()
            hashes[name] = sha
            # Deduplicate only our own immutable cache, never hardlink the source.
            if old and (old/name).is_file() and digest(old/name) == sha:
                os.link(old/name, stage/name)
            else:
                (stage/name).write_bytes(data)
        def check_refs(value):
            if isinstance(value, dict):
                for key, val in value.items():
                    if key in ('topViewPath', 'topViewUrl') and isinstance(val, str) and val:
                        parsed = urlsplit(val)
                        rel = unquote(parsed.path).removeprefix('/optics-kits/').removeprefix('/').removeprefix('./')
                        if parsed.scheme or parsed.netloc or rel not in hashes:
                            raise ValueError('俯视图未包含在正式库中：'+val)
                    check_refs(val)
            elif isinstance(value, list):
                for val in value:
                    check_refs(val)
        check_refs(catalog)
        for name, expected in hashes.items():
            if digest(stage/name) != expected:
                raise ValueError('本地回读校验失败：'+name)
        if source_signature(root) != signature or digest(source/'catalog.json') != hashes['catalog.json']:
            raise ValueError('网页版正在发布，自动重试；现有本地库保留。')
        content = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        snapshot = release+'-'+content[:16]
        receipt = {'release':release, 'snapshot':snapshot, 'version':catalog['version'],
            'sourceMode':'web-runtime', 'sourceVerified':True, 'source':str(source),
            'sourceSignature':signature, 'contentSha256':content,
            'verifiedAt':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds'),
            'sha256':hashes, 'fileCount':len(hashes)}
        (stage/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
        destination = libraries/snapshot
        if destination.exists():
            verify_or_restore_snapshot(stage, destination, hashes)
        else:
            stage.rename(destination)
        pointer = root/'data/current.json.tmp'
        pointer.write_text(json.dumps({'release':snapshot})+'\n')
        os.replace(pointer, root/'data/current.json')
        return {key:val for key, val in receipt.items() if key != 'sha256'}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def sync(root=ROOT):
    root = Path(root)
    (root/'data').mkdir(exist_ok=True)
    with (root/'data/library-sync.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return receive(root)


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args()
    try:
        print(json.dumps({'ok':True, **sync(args.root)}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok':False, 'message':str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
