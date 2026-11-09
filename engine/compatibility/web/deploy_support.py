#!/usr/bin/env python3
"""Prepare or deploy an incremental ZZLAB integration. Default: print plan only.

--prepare writes reviewable candidates/diffs under deploy_plan, never production.
--deploy is reserved for the root task's explicit ready instruction.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SOURCE = Path(__file__).resolve().parent
MAIN = Path('/Users/Shared/ZZLAB/MacMainPreview')
LIVE = MAIN / 'dashboard-router'
RUNTIME = Path('/Users/Shared/ZZLAB/OpticsKits')
NAS = Path('/Volumes/ZZLab_001/ZZLAB Web/Mac service/10_Optics_Kits')
PYTHON = MAIN / '.venv/bin/python'
LABEL = 'com.zzlab.optics-kits'
PLIST = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'
DOMAIN = f'gui/{os.getuid()}'
PORT = 18923
CAD_RUNTIME = RUNTIME / 'cad-venv'
CAD_PYTHON = CAD_RUNTIME / 'bin/python'
BOARD_CACHE = RUNTIME / 'cache/breadboards'
SHARED_DB = RUNTIME / 'data/shared-kits.sqlite3'
SHARED_BACKUP = NAS / 'shared-data/shared-kits.sqlite3'
BUNDLED_PYTHON = Path('/Users/wjj/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3')
CAD_REQUIREMENTS = SOURCE / 'requirements-cad.txt'
PREFIX = '/optics-kits'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        # Internal identity headers must never follow an unexpected redirect.
        return None


OPENER = build_opener(ProxyHandler({}), NoRedirect())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copy_release_verified(source, destination, workers=8):
    """Copy a new NAS release with bounded IO and per-file hash readback."""
    source, destination = Path(source), Path(destination)
    entries = list(source.rglob('*'))
    if source.is_symlink() or any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in entries):
        raise RuntimeError('NAS release input contains a link or special file.')
    jobs = []
    def copy_one(src, dst):
        shutil.copy2(src, dst)
        if sha(src) != sha(dst):
            raise RuntimeError('NAS module source checksum mismatch: ' + str(Path(src).relative_to(source)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        def schedule(src, dst):
            jobs.append(pool.submit(copy_one, src, dst))
            return dst
        # copytree still rejects an existing destination and creates directories
        # before their file copies. A failed worker propagates to deploy rollback.
        shutil.copytree(source, destination, copy_function=schedule)
        for job in as_completed(jobs):
            job.result()
        # Restore directory attributes after all asynchronous children finish.
        directories = [source, *(p for p in entries if p.is_dir())]
        for job in [pool.submit(shutil.copystat, p, destination / p.relative_to(source)) for p in directories]:
            job.result()
    return {'files': len(jobs), 'sha256_readback': 'passed', 'workers': workers}


def atomic_write(path, content, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.optics-kits-tmp')
    temporary.write_bytes(content.encode() if isinstance(content, str) else content)
    temporary.chmod(mode)
    temporary.replace(path)


def once(text, anchor, replacement):
    if text.count(anchor) != 1:
        raise RuntimeError(f'Expected one integration anchor, found {text.count(anchor)}: {anchor[:85]!r}')
    return text.replace(anchor, replacement, 1)


def patched_base_router(text):
    if 'OPTICS_KITS_INTEGRATION_V1' in text:
        return text
    if PREFIX in text:
        raise RuntimeError('An unknown optics-kits integration already exists; inspect it before deployment.')
    text = once(text, 'ROUTES = (\n',
                'ROUTES = (\n    # OPTICS_KITS_INTEGRATION_V1: same unified login; readonly remains denied.\n'
                '    ("/optics-kits", "127.0.0.1", 18923, True),\n')
    anchor = '          <a class="program-link" href="/xie-resistor/"'
    start = text.index(anchor)
    end = text.index('\n', start)
    text = text[:end] + '\n          __OPTICS_KITS_CARD__' + text[end:]
    marker = 'PRESENCE_BAR = '
    card = ('<a class="program-link" href="/optics-kits/"><span class="program-code">T-06</span>'
            '<span class="program-copy"><strong>光路套件</strong><span>套件选择、采购清单与制造包下载</span>'
            '</span><span class="open" aria-hidden="true">→</span></a>')
    text = once(text, marker, f'OPTICS_KITS_CARD = {card!r}\n\n\n' + marker)
    text = once(text, 'def activity_for_path(path: str) -> str:\n',
                'def activity_for_path(path: str) -> str:\n'
                '    if path == "/optics-kits" or path.startswith("/optics-kits/"):\n'
                '        return "选择光路套件与下载制造包"\n')
    text = once(text, '        .replace("__OUTPUT_EQUIPMENT__", output_equipment)\n',
                '        .replace("__OUTPUT_EQUIPMENT__", output_equipment)\n'
                '        .replace("__OPTICS_KITS_CARD__", OPTICS_KITS_CARD if role in {"user", "admin"} else "")\n')
    text = once(text,
                'timeout = 240 if prefix == "/warehouse" else 900 if prefix in {"/lab-archive", "/arxiv"} else 15',
                'timeout = 240 if prefix in {"/warehouse", "/optics-kits"} else 900 if prefix in {"/lab-archive", "/arxiv"} else 15')
    text = once(text, '            if prefix in {"/lab-archive", "/arxiv"}:\n',
                '            if prefix in {"/lab-archive", "/arxiv", "/optics-kits"}:\n')
    return text


def patched_authenticated_router(text):
    text = patched_base_router(text)
    public_files = sorted(PREFIX + '/' + p.relative_to(SOURCE / 'static').as_posix()
                          for p in (SOURCE / 'static').rglob('*')
                          if p.is_file() and p.suffix in {'.html', '.js', '.css', '.svg', '.png', '.webp', '.ico'})
    readable = [PREFIX, PREFIX + '/', PREFIX + '/api/session', PREFIX + '/api/catalog', PREFIX + '/api/shared-kits', PREFIX + '/api/cart', *public_files]
    helper = '''# OPTICS_KITS_AUTH_V2: login required; readonly editing/downloads only.
def optics_readonly_request_allowed(method: str, path: str) -> bool:
    readable = READABLE_PATHS
    if method == "GET":
        if path in readable:
            return True
        parts = path.split("/")
        return (len(parts) == 6 and parts[:4] == ["", "optics-kits", "api", "shared-kits"]
                and len(parts[4]) == 32 and all(c in "0123456789abcdef" for c in parts[4])
                and parts[5] in {"project", "thumbnail", "bundle"})
    return method == "POST" and path in {
        "/optics-kits/api/preview", "/optics-kits/api/export", "/optics-kits/api/mounting-holes",
        "/optics-kits/api/cart/add", "/optics-kits/api/cart/update", "/optics-kits/api/cart/clear", "/optics-kits/api/cart/export",
    }


'''.replace('READABLE_PATHS', repr(tuple(readable)))
    if 'OPTICS_KITS_AUTH_V2' in text:
        start = text.index('# OPTICS_KITS_AUTH_V2:')
        end = text.index('def xie_guest_request_allowed(', start)
        return text[:start] + helper + text[end:]
    if 'OPTICS_KITS_GUEST_V1' in text:
        start = text.index('# OPTICS_KITS_GUEST_V1:')
        end = text.index('def xie_guest_request_allowed(', start)
        text = text[:start] + helper + text[end:]
        text = once(text,
                    'not (xie_guest_request_allowed(self.command, parsed.path) or optics_guest_request_allowed(self.command, parsed.path)):',
                    'not xie_guest_request_allowed(self.command, parsed.path):')
        text = once(text, '        return optics_guest_request_allowed(method, path)\n',
                    '        return optics_readonly_request_allowed(method, path)\n')
        text = once(text,
                    '        if identity is None and prefix == "/optics-kits" and not secure_upstream:\n'
                    '            headers.update({\n'
                    '                "X-ZZLAB-Guest": "1", "X-ZZLAB-Role": "guest",\n'
                    '                "X-ZZLAB-Internal-Token": os.getenv("ZZLAB_AUTH_INTERNAL_TOKEN", ""),\n'
                    '            })\n', '')
        return text
    text = once(text, 'def xie_guest_request_allowed(method: str, path: str) -> bool:\n',
                helper + 'def xie_guest_request_allowed(method: str, path: str) -> bool:\n')
    text = once(text, '    if role != "readonly":\n        return True\n',
                '    if role != "readonly":\n        return True\n'
                '    if path_has_prefix(path, "/optics-kits"):\n'
                '        return optics_readonly_request_allowed(method, path)\n')
    text = once(text, 'OPTICS_KITS_CARD if role in {"user", "admin"} else ""',
                'OPTICS_KITS_CARD if role in {"user", "admin", "readonly"} else ""')
    # Relative assets need the canonical trailing-slash URL even for direct links.
    text = once(text, '        route = self.route()\n',
                '        if parsed.path == "/optics-kits" and self.command == "GET":\n'
                '            self.redirect_legacy_path("/optics-kits/" + ("?" + parsed.query if parsed.query else ""))\n'
                '            return\n\n'
                '        route = self.route()\n')
    return text


def patched_router(text):
    """Upgrade either fixed policy to the administrator-controlled guest gate."""
    authenticated_guard = 'not xie_guest_request_allowed(self.command, parsed.path):'
    policy_guard = 'not (xie_guest_request_allowed(self.command, parsed.path) or optics_guest_request_allowed(self.command, parsed.path)):'
    guest_headers = (
        '        if identity is None and prefix == "/optics-kits" and not secure_upstream:\n'
        '            headers.update({\n'
        '                "X-ZZLAB-Guest": "1", "X-ZZLAB-Role": "guest",\n'
        '                "X-ZZLAB-Internal-Token": os.getenv("ZZLAB_AUTH_INTERNAL_TOKEN", ""),\n'
        '            })\n')
    if 'OPTICS_KITS_GUEST_POLICY_V3' in text:
        start = text.index('# OPTICS_KITS_GUEST_POLICY_V3:')
        end = text.index('def xie_guest_request_allowed(', start)
        text = text[:start] + text[end:]
        text = once(text, policy_guard, authenticated_guard)
        text = once(text, guest_headers, '')
    text = patched_authenticated_router(text)
    helper = '''# OPTICS_KITS_GUEST_POLICY_V3: administrator setting, checked for every anonymous request.
def optics_guest_access_enabled() -> bool:
    token = os.getenv("ZZLAB_AUTH_INTERNAL_TOKEN", "")
    if not token:
        return False
    connection = http.client.HTTPConnection("127.0.0.1", 18923, timeout=1)
    try:
        connection.request("GET", "/internal/guest-access", headers={
            "X-ZZLAB-Internal-Token": token, "X-ZZLAB-Policy-Probe": "1",
        })
        response = connection.getresponse()
        content = response.read(1025)
        if response.status != 200 or len(content) > 1024:
            return False
        value = json.loads(content)
        return isinstance(value, dict) and value.get("guestAccessEnabled") is True
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def optics_guest_request_allowed(method: str, path: str) -> bool:
    if path == "/optics-kits/api/cart" or path.startswith("/optics-kits/api/cart/"):
        return False
    return optics_readonly_request_allowed(method, path) and optics_guest_access_enabled()


'''
    text = once(text, 'def xie_guest_request_allowed(method: str, path: str) -> bool:\n',
                helper + 'def xie_guest_request_allowed(method: str, path: str) -> bool:\n')
    text = once(text, authenticated_guard, policy_guard)
    text = once(text, '        if identity is None and prefix == "/xie-resistor" and not secure_upstream:\n',
                guest_headers + '        if identity is None and prefix == "/xie-resistor" and not secure_upstream:\n')
    return text


def patched_base_dashboard(text):
    if 'OPTICS_KITS_INTEGRATION_V1' in text:
        return text
    if 'id="optics-kits"' in text:
        raise RuntimeError('Unknown optics-kits dashboard entry exists.')
    text = once(text, 'SITES = (\n', '''SITES = (
    # OPTICS_KITS_INTEGRATION_V1: status only; no new process-control privileges.
    Site(
        id="optics-kits",
        name="光路套件",
        description="套件选择、采购清单与制造包下载",
        port=18923,
        health_url="http://127.0.0.1:18923/healthz",
        unit="macos:optics-kits",
        scope="remote",
        controllable=False,
        local_link=False,
        public_path="/optics-kits/",
        allowed_actions=(),
        offline_hint="请在 Mac 启动光路套件服务",
    ),
''')
    text = once(text, 'def states_for_role(data: dict[str, Any], role: str) -> dict[str, Any]:\n', '''def states_for_role(data: dict[str, Any], role: str) -> dict[str, Any]:
    if role == "readonly" and any(site.get("id") == "optics-kits" for site in data["sites"]):
        visible = [site for site in data["sites"] if site.get("id") != "optics-kits"]
        data = {
            **data,
            "sites": visible,
            "summary": {
                **data.get("summary", {}),
                "total": len(visible),
                "online": sum(item["status"] == "online" for item in visible),
                "degraded": sum(item["status"] == "degraded" for item in visible),
                "offline": sum(item["status"] == "offline" for item in visible),
            },
        }
''')
    return text


def patched_dashboard(text):
    text = patched_base_dashboard(text)
    if 'OPTICS_KITS_GUEST_V1' in text:
        return text
    start = text.index('    if role == "readonly" and any(site.get("id") == "optics-kits"')
    end = text.index('    if role not in {"readonly", "user"}:', start)
    return text[:start] + '    # OPTICS_KITS_GUEST_V1: readonly can open optics; process controls remain unchanged.\n' + text[end:]


def import_review_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_policy(before, after):
    trees = [ast.parse(path.read_text()) for path in (before, after)]
    for name in ('trusted_identity_headers', 'xie_guest_request_allowed',
                 'same_origin_host', 'verify_identity', 'require_login'):
        implementations = [next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
                           for tree in trees]
        assert ast.dump(implementations[0]) == ast.dump(implementations[1]), name
    old = import_review_module(before, '_optics_router_before')
    new = import_review_module(after, '_optics_router_after')
    assert tuple(r for r in new.ROUTES if r[0] != PREFIX) == tuple(r for r in old.ROUTES if r[0] != PREFIX)
    assert new.READONLY_ALLOWED_PREFIXES == old.READONLY_ALLOWED_PREFIXES
    assert new.READONLY_MUTATION_BLOCKED_PREFIXES == old.READONLY_MUTATION_BLOCKED_PREFIXES
    prefixes = {r[0] for r in old.ROUTES} | {'/', '/warehouse', '/sites', '/__presence', '/__presence.js'}
    cases = 0
    for role in ('readonly', 'user', 'admin'):
        for prefix in prefixes:
            for suffix in ('', '/', '/api/catalog', '/download'):
                for method in ('GET', 'HEAD', 'OPTIONS', 'POST', 'PUT', 'PATCH', 'DELETE'):
                    path = prefix + suffix
                    if prefix != PREFIX:
                        assert old.readonly_request_allowed(role, method, path) == new.readonly_request_allowed(role, method, path), (role, method, path)
                    cases += 1
        identity = {'id': 123, 'username': 'integration-check', 'display_name': 'Integration Check', 'role': role}
        for prefix in prefixes:
            assert old.trusted_identity_headers(identity, prefix) == new.trusted_identity_headers(identity, prefix)
        page = new.render_landing_page(identity, []).decode()
        assert 'href="/optics-kits/"' in page
    for method in ('GET', 'HEAD', 'OPTIONS', 'POST', 'PUT', 'PATCH', 'DELETE'):
        assert new.readonly_request_allowed('readonly', method, PREFIX + '/download') is False
    assert not new.xie_guest_request_allowed('GET', PREFIX + '/')
    readable = ('/', '/api/session', '/api/catalog', '/api/shared-kits', '/api/cart',
                '/api/shared-kits/' + 'a' * 32 + '/project', '/api/shared-kits/' + 'a' * 32 + '/bundle',
                '/app.js', '/topviews/kit_waveplate.svg')
    generated = ('/api/preview', '/api/export', '/api/mounting-holes',
                 '/api/cart/add', '/api/cart/update', '/api/cart/clear', '/api/cart/export')
    denied = ('/api/shared-kits', '/api/shared-kits/' + 'a' * 32 + '/unpublish',
              '/api/shared-kits/' + 'a' * 32 + '/restore', '/api/future-write', '/../../auth/admin', '/assets/private.step')
    for method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'):
        for suffix in set(readable + generated + denied):
            expected = (method == 'GET' and suffix in readable) or (method == 'POST' and suffix in generated)
            assert new.optics_readonly_request_allowed(method, PREFIX + suffix) == expected, (method, suffix)
            assert new.readonly_request_allowed('readonly', method, PREFIX + suffix) == expected
    for method in ('GET', 'POST'):
        for path in ('/auth/admin', '/', '/warehouse/', '/optics-kits-evil/api/catalog', '/xie-resistor/'):
            assert not new.optics_readonly_request_allowed(method, path)
    # Personal carts are never anonymous, even while guest access is enabled.
    original_probe = new.optics_guest_access_enabled
    new.optics_guest_access_enabled = lambda: True
    try:
        for suffix in ('/api/cart', '/api/cart/add', '/api/cart/update', '/api/cart/clear', '/api/cart/export'):
            for method in ('GET', 'POST'):
                assert not new.optics_guest_request_allowed(method, PREFIX + suffix)
    finally:
        new.optics_guest_access_enabled = original_probe
    for suffix in ('', '/', '/api/catalog'):
        handler = new.RouterHandler.__new__(new.RouterHandler)
        handler.path = PREFIX + suffix
        route = handler.route()
        assert route[:2] == ('127.0.0.1', PORT) and route[3] == PREFIX
    return cases


def verify_dashboard_policy(before, after):
    def function(path, name):
        tree = ast.parse(path.read_text())
        return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    # The Flask app's entire SSO/session/CSRF/control implementation is untouched.
    assert ast.dump(function(before, 'create_app')) == ast.dump(function(after, 'create_app'))
    namespaces = []
    for path in (before, after):
        namespace = {'Any': object}
        node = function(path, 'states_for_role')
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
        namespaces.append(namespace)
    existing = [
        {'id': 'vacuum-gauge', 'status': 'online', 'controllable': True, 'allowed_actions': ['stop']},
        {'id': 'site-dashboard', 'status': 'online', 'controllable': False, 'allowed_actions': []},
    ]
    added = {'id': 'optics-kits', 'status': 'online', 'controllable': False, 'allowed_actions': []}
    baseline = {'sites': existing, 'summary': {'total': 2, 'online': 2, 'degraded': 0, 'offline': 0}}
    candidate = {'sites': existing + [added], 'summary': {'total': 3, 'online': 3, 'degraded': 0, 'offline': 0}}
    for role in ('readonly', 'user', 'admin'):
        previous = namespaces[0]['states_for_role'](baseline, role)
        current = namespaces[1]['states_for_role'](candidate, role)
        assert [site for site in current['sites'] if site['id'] != 'optics-kits'] == previous['sites']
        optics = next(site for site in current['sites'] if site['id'] == 'optics-kits')
        assert not optics['controllable'] and not optics['allowed_actions']


def token_path():
    # Read only the configured filename. Never echo, copy, or serialize a secret value.
    result = None
    for line in (MAIN / 'config/mac-preview.env').read_text().splitlines():
        line = line.strip().removeprefix('export ')
        if line.startswith('ZZLAB_AUTH_INTERNAL_TOKEN_FILE='):
            values = shlex.split(line.split('=', 1)[1], comments=True)
            if len(values) == 1:
                result = Path(values[0])
    if result is None or not result.is_absolute() or not result.is_file():
        raise RuntimeError('Existing internal token file configuration was not found.')
    return result


def run(args, check=True):
    result = subprocess.run([str(value) for value in args], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {args[0]} {args[1:3]}\n{result.stderr[:600]}')
    return result



def cad_runtime_status():
    if not CAD_PYTHON.is_file():
        return {'ready': False, 'python': str(CAD_PYTHON), 'cache': str(BOARD_CACHE)}
    probe = run([CAD_PYTHON, '-c', 'import json,sys,importlib.metadata as m; from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox; from reportlab.pdfgen import canvas; print(json.dumps({"python":sys.version.split()[0],"cadquery-ocp":m.version("cadquery-ocp"),"reportlab":m.version("reportlab")}))'])
    versions = json.loads(probe.stdout)
    if not versions['python'].startswith('3.12.') or versions['cadquery-ocp'] != '8.0.1.0.0' or versions['reportlab'] != '4.4.9':
        raise RuntimeError('Existing CAD worker differs from the reviewed versions; inspect it instead of silently replacing it.')
    return {'ready': True, 'python': str(CAD_PYTHON), 'versions': versions, 'cache': str(BOARD_CACHE)}


def prepare_cad_runtime():
    """Install only a missing isolated worker; do not alter the live service or shared web Python."""
    if CAD_RUNTIME.exists():
        state = cad_runtime_status()
        if not state['ready']:
            raise RuntimeError('Existing CAD runtime is incomplete; inspect it before retrying.')
        return state
    if not BUNDLED_PYTHON.is_file() or not CAD_REQUIREMENTS.is_file():
        raise RuntimeError('Reviewed Python 3.12 runtime or CAD requirements are unavailable.')
    version = run([BUNDLED_PYTHON, '-c', 'import sys; print(sys.version.split()[0])']).stdout.strip()
    if not version.startswith('3.12.'):
        raise RuntimeError('The CAD worker requires the reviewed bundled Python 3.12 runtime.')
    RUNTIME.mkdir(parents=True, exist_ok=True)
    run([BUNDLED_PYTHON, '-m', 'venv', '--copies', CAD_RUNTIME])
    run([CAD_PYTHON, '-m', 'pip', 'install', '--index-url', 'https://pypi.org/simple', '--only-binary=:all:', '-r', CAD_REQUIREMENTS])
    BOARD_CACHE.mkdir(parents=True, exist_ok=True)
    return cad_runtime_status()


def request_status(url, headers=None, payload=None, max_bytes=8 * 1024 * 1024):
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.port not in (PORT, 18766):
        raise RuntimeError('Deployment probes are restricted to the two local service ports.')
    headers = dict(headers or {})
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        headers['Content-Type'] = 'application/json'
    try:
        with OPENER.open(Request(url, headers=headers, data=body), timeout=30 if body else 4) as response:
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise RuntimeError('Deployment probe response exceeded its expected size.')
            return response.status, content
    except HTTPError as error:
        return error.code, error.read(4096)



def verify_layout_downloads(headers, catalog):
    """Exercise the production-plate worker and the layout collision boundary."""
    base = f'http://127.0.0.1:{PORT}'
    board = {'widthMm': 350, 'heightMm': 225, 'pitchMm': 12.5, 'edgeOffsetMm': 12.5,
             'thicknessMm': 12.7, 'holeType': 'M6_through'}
    payload = {'catalogVersion': catalog['version'], 'layout': {'board': board, 'instances': []}, 'extras': []}
    status, content = request_status(base + '/api/preview', headers, payload)
    preview = json.loads(content) if status == 200 else {}
    rows = [row for row in preview.get('manufacturing', []) if row.get('generatedBoard')]
    if status != 200 or not preview.get('layoutValidation', {}).get('valid') or len(rows) != 1 or rows[0]['quantity'] != 1:
        raise RuntimeError('A blank valid board must produce exactly one manufacturing plate.')
    status, content = request_status(base + '/api/export?format=bundle', headers, payload, 64 * 1024 * 1024)
    if status != 200:
        raise RuntimeError(f'Parameterized plate bundle failed: HTTP {status}')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        if archive.testzip() is not None or len([n for n in names if n.endswith('.step')]) != 1 or len([n for n in names if n.endswith('.pdf')]) != 1:
            raise RuntimeError('A blank plate bundle must contain one valid STEP and one PDF.')
        if not {'光路布局.json', '光路总俯视图.svg', '生产清单.xlsx', '麓邦采购.xlsx'}.issubset(names):
            raise RuntimeError('The plate manufacturing package is missing layout or purchasing outputs.')
    # Reproduce the reported near-edge false positive using the original kits.
    screenshot_instances = [
        {'id': 'pbs', 'kitId': 'pbs-adjustable', 'xMm': 37.5, 'yMm': 187.5, 'rotationDeg': 270},
        {'id': 'mirror', 'kitId': 'motor-05-45', 'xMm': 37.5, 'yMm': 137.5, 'rotationDeg': 90},
    ]
    payload['layout']['instances'] = screenshot_instances
    status, content = request_status(base + '/api/preview', headers, payload)
    if status != 200 or not json.loads(content).get('layoutValidation', {}).get('valid'):
        raise RuntimeError('The reported non-touching shapes with a valid overhanging upper body must be usable.')
    selection = {'catalogVersion': catalog['version'], 'layout': payload['layout'],
                 'rowParity': 'even', 'columnParity': 'odd'}
    status, content = request_status(base + '/api/mounting-holes', headers, selection)
    selected = json.loads(content) if status == 200 else {}
    holes = selected.get('mountingHoles', [])
    if len(holes) != 4 or any((h['rowIndex'] + 1) % 2 or (h['columnIndex'] + 1) % 2 != 1 for h in holes):
        raise RuntimeError('Corner-hole selection failed the independent row/column parity controls.')
    for a in holes:
        for b in holes:
            if any(abs((a[key] - b[key]) * board['pitchMm'] / 25 - round((a[key] - b[key]) * board['pitchMm'] / 25)) > 1e-6 for key in ('columnIndex', 'rowIndex')):
                raise RuntimeError('Selected corner-hole spacing is not a multiple of 25 mm.')
    payload['layout']['board'] = selected['board']
    status, content = request_status(base + '/api/export?format=bundle', headers, payload, 64 * 1024 * 1024)
    if status != 200:
        raise RuntimeError(f'Counterbored board STEP/PDF bundle failed: HTTP {status}')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        saved = json.loads(archive.read('光路布局.json'))
        if archive.testzip() is not None or saved['layout']['board'].get('mountingHoles') != holes:
            raise RuntimeError('Counterbore positions did not survive the complete exported package.')
        if not any(name.endswith('.pdf') and '面包板' in name for name in archive.namelist()):
            raise RuntimeError('The counterbored board drawing is missing.')
    payload['layout']['board'] = board
    candidates = [kit for kit in catalog['kits'] if kit.get('layout', {}).get('placementAllowed') is not False and kit.get('layout', {}).get('mountingHoleOffsetsMm')]
    if not candidates:
        raise RuntimeError('No reviewed placeable kit is available for the layout deployment probe.')
    kit = candidates[0]
    instances = [{'id': f'deploy-overlap-{index}', 'kitId': kit['id'], 'xMm': 175, 'yMm': 112.5, 'rotationDeg': 0} for index in (1, 2)]
    payload['layout']['instances'] = instances
    status, content = request_status(base + '/api/preview', headers, payload)
    invalid = json.loads(content) if status == 200 else {}
    validation = invalid.get('layoutValidation', {})
    if status != 200 or validation.get('valid') is not False or not any(issue.get('code') == 'collision' for issue in validation.get('issues', [])):
        raise RuntimeError('Overlapping kit collision was not exposed as an invalid draft.')
    for format_name in ('lubang', 'manufacturing', 'bundle'):
        status, content = request_status(base + '/api/export?format=' + format_name, headers, payload)
        error = json.loads(content) if status == 409 else {}
        if status != 409 or error.get('error', {}).get('code') != 'layout_invalid':
            raise RuntimeError(f'Invalid layout did not block {format_name} export.')
    for format_name in ('layout-json', 'layout-svg'):
        status, content = request_status(base + '/api/export?format=' + format_name, headers, payload, 64 * 1024 * 1024)
        if status != 200 or not content:
            raise RuntimeError(f'Invalid layout draft could not be saved as {format_name}.')
    return {'blank_board_production_quantity': 1, 'board_step_pdf_bundle': 'passed',
            'reported_false_collision_and_upper_overhang': 'passed',
            'm6_counterbore_selection_and_bundle': 'passed',
            'independent_parity_and_25mm_spacing': 'passed',
            'collision_blocks_purchase_production_bundle': 'passed', 'invalid_draft_json_svg': 'passed'}


def verify_catalog_inventory(catalog, source_catalog):
    """A release must expose every source kit exactly once, regardless of count."""
    def kit_ids(value, label):
        kits = value.get('kits') if isinstance(value, dict) else None
        if not isinstance(kits, list) or not kits:
            raise RuntimeError(f'{label} catalog must contain a nonempty kit list.')
        ids = [kit.get('id') if isinstance(kit, dict) else None for kit in kits]
        if any(not isinstance(kit_id, str) or not kit_id.strip() for kit_id in ids):
            raise RuntimeError(f'{label} catalog contains a missing or invalid kit ID.')
        if len(ids) != len(set(ids)):
            raise RuntimeError(f'{label} catalog contains duplicate kit IDs.')
        return set(ids)

    expected = kit_ids(source_catalog, 'Source')
    actual = kit_ids(catalog, 'Release')
    if actual != expected:
        raise RuntimeError(f'Release catalog differs from source: missing={sorted(expected-actual)}, '
                           f'unexpected={sorted(actual-expected)}.')
    return sorted(expected)


def registered_reference_assembly(kit):
    """Recognize the explicitly reviewed no-BOM references, never arbitrary blocks."""
    source=kit.get('sourceAssembly',{});geometry=kit.get('layout',{})
    fiber_references={
        'laser-ecdl-1030nm': ('PLP-2026-03-007272-Y-01', {
            1:'6f39bd60ac330becc4019af9ce3a83451e58a6f3a21783052464b36a99fa5cec',
            2:'332e64c5b69b74a6ded09c69cb41d6b5bff7e1e45f789c323ba3005737ad5674'}),
        'laser-seed-1870nm': ('PLP-2026-03-007264-S-01', {
            3:'796514609ed7c43e937a61829380b6897bbb0673118298426791e8a983efcab3',
            4:'703b9aa9535dd9e4800cb2b615da9bd3adddc142ee2527283569aae169c04d4c'}),
    }
    if kit.get('id') in fiber_references:
        report_id,source_hashes=fiber_references[kit['id']]
        report=kit.get('sourceReport',{})
        files=report.get('sourceFiles',[])
        return (kit.get('bomPolicy')=='reference-only'
                and kit.get('releaseStage')=='documentation-preview'
                and kit.get('bundleStatus')=='blocked' and bool(kit.get('bundleNote'))
                and kit.get('components')==[] and kit.get('opticalSlots')==[]
                and geometry.get('placementAllowed') is False
                and geometry.get('geometryStatus')=='awaiting-dimensions'
                and geometry.get('opticalType')=='unsupported'
                and geometry.get('opticalDatumVerified') is False
                and geometry.get('opticalPortsMm')==[]
                and not any(geometry.get(key) for key in
                            ('mountingHoleOffsetsMm','collisionBoundsMm','collisionPolygonsMm',
                             'baseBoundsMm','opticalDefaults'))
                and all(geometry.get(key) is None for key in
                        ('widthMm','heightMm','anchorXMm','anchorYMm','opticalAxisHeightMm'))
                and report.get('reportId')==report_id
                and report.get('outputMode')=='FC/APC fiber'
                and len(files)==2 and {f.get('id') for f in files}==set(source_hashes)
                and {f.get('id'):f.get('sha256') for f in files}==source_hashes
                and all(isinstance(f.get('sha256'),str) and len(f['sha256'])==64
                        and all(c in '0123456789abcdef' for c in f['sha256']) for f in files))
    return (kit.get('id')=='objective-final-assembly' and kit.get('bomPolicy')=='reference-only'
            and kit.get('releaseStage')=='layout-reference' and kit.get('bundleStatus')=='blocked'
            and bool(kit.get('bundleNote')) and kit.get('components')==[]
            and source.get('documentId')=='2082505c19c5454b7d3ccd43'
            and source.get('elementId')=='b7046cbf29467588274024f0'
            and source.get('finalAssemblyConfirmed') is True and source.get('bomVerified') is False
            and isinstance(source.get('stepSha256'),str) and len(source['stepSha256'])==64
            and all(char in '0123456789abcdef' for char in source['stepSha256'])
            and geometry.get('placementAllowed') is True
            and geometry.get('opticalAssembly',{}).get('verified') is True)


def verify_reference_assembly_package(kit, preview, content):
    """A reference archive may contain empty order templates, never phantom parts."""
    if not registered_reference_assembly(kit) or any(preview.get(kind)!=[] for kind in ('lubang','manufacturing','standard')):
        raise RuntimeError('Reference-only assembly preview contains fabricated order rows.')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if archive.testzip() is not None or any(name.lower().endswith(('.step','.stp','.pdf','.stl','.iges','.igs','.3mf')) for name in archive.namelist()):
            raise RuntimeError('Reference-only assembly archive contains manufacturing assets or corrupt data.')
        config=json.loads(archive.read('套件配置.json'))
        if (len(config.get('items',[]))!=1 or config['items'][0].get('kitId')!=kit['id'] or config['items'][0].get('quantity')!=1
                or config.get('extras') or config.get('components')!=[] or config.get('assets')!={}
                or config.get('fileChecksums')!={} or config.get('totals',{}).get('componentQuantity')!=0
                or config.get('lubangImport',{}).get('ready') or config.get('lubangImport',{}).get('blocked')):
            raise RuntimeError('Reference-only assembly package contains fabricated order rows or source assets.')
        if not any(item.get('code')=='reference_assembly' and kit['id'] in item.get('kitIds',[])
                   for group in config.get('reviewGroups',[]) for item in group.get('items',[])):
            raise RuntimeError('Reference-only assembly package omits its unregistered-BOM explanation.')
    return {'id':kit['id'],'preview':200,'bundle':'reference_only','bytes':len(content),
            'sha256':hashlib.sha256(content).hexdigest(),'orderRows':0,'manufacturingAssets':0}


def verify_download_matrix(headers):
    base = f'http://127.0.0.1:{PORT}'
    # Match the headers a browser POST receives after the authenticated router
    # rewrites Host. Token-only probes missed the production Origin regression.
    headers = {**headers, 'Origin': 'https://zzlab.ngrok.app',
               'X-Forwarded-Host': 'zzlab.ngrok.app', 'X-Forwarded-Proto': 'https',
               'Sec-Fetch-Site': 'same-origin'}
    status, content = request_status(base + '/api/catalog', headers)
    if status != 200:
        raise RuntimeError('Authenticated catalog probe failed.')
    catalog = json.loads(content)
    kits = catalog.get('kits', [])
    source_catalog = json.loads((SOURCE / 'catalog.json').read_text())
    source_kit_ids = verify_catalog_inventory(catalog, source_catalog)
    # Design-review additions may intentionally lack approved manufacturing
    # drawings. Only an explicit source declaration permits a blocked bundle;
    # existing production kits must still ship complete assets.
    expected_blocked = {kit['id'] for kit in source_catalog['kits']
                        if kit.get('releaseStage') == 'design-review'
                        and kit.get('bundleStatus') == 'blocked' and kit.get('bundleNote')}
    reference_assemblies = {kit['id'] for kit in source_catalog['kits'] if registered_reference_assembly(kit)}
    actual_blocked = {kit['id'] for kit in kits if kit.get('bundleStatus') == 'blocked'}
    if (actual_blocked != expected_blocked | reference_assemblies
            or {kit['id'] for kit in kits if registered_reference_assembly(kit)} != reference_assemblies):
        raise RuntimeError('Blocked bundles must match the explicitly registered source design-review or verified reference-only assembly kits.')
    report = {'catalog_version': catalog['version'], 'source_kit_ids': source_kit_ids,
              'blank_optional_optics': 'allowed', 'kits': []}
    for kit in kits:
        payload = {'items': [{'kitId': kit['id'], 'quantity': 1}], 'extras': [], 'catalogVersion': catalog['version']}
        status, preview_content = request_status(base + '/api/preview', headers, payload)
        if status != 200:
            raise RuntimeError(f'Kit preview failed with optional optics blank: {kit["id"]}: HTTP {status}')
        status, content = request_status(base + '/api/export?format=bundle', headers, payload, 64 * 1024 * 1024)
        if kit['id'] in reference_assemblies:
            if status != 200:
                raise RuntimeError(f'Reference-only archive unavailable: {kit["id"]}: HTTP {status}')
            report['kits'].append(verify_reference_assembly_package(kit,json.loads(preview_content),content))
            continue
        if kit['id'] in expected_blocked:
            error = json.loads(content) if status == 409 else {}
            error_code = error.get('error', {}).get('code') if isinstance(error.get('error'), dict) else error.get('code')
            if status != 409 or error_code not in {'asset_missing', 'bundle_blocked'}:
                raise RuntimeError(f'Design-review bundle did not fail closed: {kit["id"]}: HTTP {status}')
            report['kits'].append({'id': kit['id'], 'preview': 200, 'bundle': 'expected_blocked', 'status': status, 'reason': error_code})
            continue
        if status != 200:
            raise RuntimeError(f'Complete kit bundle failed: {kit["id"]}: HTTP {status}')
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if archive.testzip() is not None:
                raise RuntimeError(f'Bundle ZIP checksum validation failed: {kit["id"]}')
            configuration = json.loads(archive.read('套件配置.json'))
            if configuration['items'][0]['kitId'] != kit['id'] or configuration.get('extras'):
                raise RuntimeError(f'Bundle selection or empty optional optics mismatch: {kit["id"]}')
        report['kits'].append({'id': kit['id'], 'preview': 200, 'bundle': 'passed', 'bytes': len(content),
                               'sha256': hashlib.sha256(content).hexdigest()})
    report['layout_verification'] = verify_layout_downloads(headers, catalog)
    report['browser_origin_verification'] = verify_browser_origin(headers, catalog)
    report.update(complete_bundles=len(kits)-len(expected_blocked)-len(reference_assemblies), expected_blocked_bundles=len(expected_blocked), reference_only_packages=len(reference_assemblies))
    return report


def verify_browser_origin(headers, catalog):
    """Verify real browser-origin exports and retain cross-origin rejection."""
    base = f'http://127.0.0.1:{PORT}'
    payload = {'items': [{'kitId': 'waveplate', 'quantity': 1}], 'extras': [],
               'catalogVersion': catalog['version']}
    for format_name in ('lubang', 'manufacturing'):
        status, content = request_status(base + '/api/export?format=' + format_name,
                                        headers, payload, 64 * 1024 * 1024)
        if status != 200:
            raise RuntimeError(f'Same-origin browser {format_name} export failed: HTTP {status}')
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if archive.testzip() is not None or '[Content_Types].xml' not in archive.namelist():
                raise RuntimeError('Browser spreadsheet export is not a valid XLSX.')
    rejected = [
        {'Origin': 'https://unrelated.example', 'Sec-Fetch-Site': 'cross-site'},
        {'Origin': 'https://other.zzlab.ngrok.app', 'Sec-Fetch-Site': 'same-site'},
        {'Origin': 'http://zzlab.ngrok.app'},
        {'Origin': 'https://zzlab.ngrok.app:444'},
        {'Origin': 'null'},
        {'X-Forwarded-Host': 'zzlab.ngrok.app, unrelated.example'},
    ]
    for changes in rejected:
        status, content = request_status(base + '/api/preview', {**headers, **changes}, payload)
        error = json.loads(content) if status == 403 else {}
        if status != 403 or error.get('error', {}).get('code') != 'cross_origin_denied':
            raise RuntimeError('A cross-origin or ambiguous-origin POST was not rejected.')
    return {'browser_proxy_preview_bundle': 'passed', 'purchase_production_xlsx': 'passed',
            'cross_origin_rejections': len(rejected)}


def wait_health(url, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, _ = request_status(url)
            if status == 200:
                return
        except (OSError, URLError, TimeoutError):
            pass
        time.sleep(.5)
    raise RuntimeError(f'Health check did not succeed: {url}')


def verify_shared_library(headers):
    """Read-only live probes; never publish synthetic kits to the lab library."""
    base = f'http://127.0.0.1:{PORT}/api/shared-kits'
    status, body = request_status(base, headers)
    data = json.loads(body) if status == 200 else {}
    if status != 200 or not isinstance(data.get('kits'), list):
        raise RuntimeError('Shared library listing failed after deployment.')
    status, _ = request_status(base)
    if status != 401:
        raise RuntimeError('Shared library allowed an unauthenticated request.')
    status, _ = request_status(base, {**headers, 'X-ZZLAB-Role': 'readonly'})
    if status != 200:
        raise RuntimeError('Readonly account cannot read the shared library.')
    for path in ('', '/' + 'a' * 32 + '/unpublish', '/' + 'a' * 32 + '/restore'):
        status, _ = request_status(base + path, {**headers, 'X-ZZLAB-Role': 'readonly'}, {})
        if status != 403:
            raise RuntimeError('Readonly account can mutate the shared library.')
    status, body = request_status(base, {**headers, 'Origin': 'https://unrelated.example', 'Sec-Fetch-Site': 'cross-site'}, {})
    if status != 403 or json.loads(body).get('error', {}).get('code') != 'cross_origin_denied':
        raise RuntimeError('Shared publishing failed cross-origin rejection.')
    from shared_kits import SharedKitStore
    if SharedKitStore(SHARED_DB, SHARED_BACKUP).backup().get('status') != 'ok':
        raise RuntimeError('Shared-library NAS snapshot could not be written.')
    # Validate a local copy: network filesystems need no SQLite locking support.
    with tempfile.TemporaryDirectory(prefix='zzlab-shared-backup-check-') as temporary:
        local = Path(temporary) / 'backup.sqlite3'
        shutil.copyfile(SHARED_BACKUP, local)
        with sqlite3.connect(local) as database:
            if database.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Shared-library NAS snapshot failed integrity verification.')
    return {'list': 'passed', 'authentication': 'passed', 'role_boundary': 'passed', 'cross_origin': 'passed', 'nas_snapshot_integrity': 'passed', 'production_test_records_created': 0}


def verify_authenticated_access():
    """Read the persisted policy and test it without changing production settings."""
    base = f'http://127.0.0.1:{PORT}'
    token = token_path().read_text().strip()
    headers = {'X-ZZLAB-Internal-Token': token, 'X-ZZLAB-Authenticated': '1', 'X-ZZLAB-Role': 'readonly',
               'X-ZZLAB-User-ID': '1', 'Origin': 'https://zzlab.ngrok.app',
               'X-Forwarded-Host': 'zzlab.ngrok.app', 'X-Forwarded-Proto': 'https', 'Sec-Fetch-Site': 'same-origin'}
    endpoint = base + '/api/admin/guest-access'
    status, body = request_status(endpoint, {**headers, 'X-ZZLAB-Role': 'admin'})
    policy = json.loads(body) if status == 200 else {}
    if (type(policy.get('guestAccessEnabled')) is not bool or type(policy.get('revision')) is not int or
            type(policy.get('guestManufacturingDownloadsEnabled')) is not bool):
        raise RuntimeError('Admin guest-access policy is unavailable or invalid.')
    enabled = policy['guestAccessEnabled']
    manufacturing_enabled = policy['guestManufacturingDownloadsEnabled']
    for role in ('readonly', 'user'):
        limited = {**headers, 'X-ZZLAB-Role': role}
        for payload in (None, {}):
            status, _ = request_status(endpoint, limited, payload)
            if status not in (403, 404):
                raise RuntimeError(f'{role} unexpectedly accessed guest administration.')
    probe_headers = {'X-ZZLAB-Internal-Token': token, 'X-ZZLAB-Policy-Probe': '1'}
    status, body = request_status(base + '/internal/guest-access', probe_headers)
    if status != 200 or json.loads(body) != {'guestAccessEnabled': enabled}:
        raise RuntimeError('Router policy probe differs from the persisted admin setting.')
    router = 'http://127.0.0.1:18766' + PREFIX
    public_headers = {'Host': 'zzlab.ngrok.app', 'Origin': 'https://zzlab.ngrok.app', 'Sec-Fetch-Site': 'same-origin'}
    forged = {**public_headers, 'X-ZZLAB-Authenticated': '1', 'X-ZZLAB-Role': 'admin',
              'X-ZZLAB-User-ID': '1', 'X-ZZLAB-Guest': '1', 'X-ZZLAB-Internal-Token': 'forged'}
    for browser_headers in (public_headers, forged):
        for path in ('/', '/index.html', '/api/catalog', '/api/session', '/api/shared-kits', '/topviews/kit_waveplate.svg'):
            status, body = request_status(router + path, browser_headers)
            if status != (200 if enabled else 302):
                raise RuntimeError(f'Anonymous access differs from admin setting at {path}: HTTP {status}')
            if enabled and path == '/api/session' and json.loads(body).get('role') != 'guest':
                raise RuntimeError('Forged browser identity was not stripped.')
            if enabled and path == '/api/session' and json.loads(body).get('canDownloadManufacturing') is not manufacturing_enabled:
                raise RuntimeError('Guest manufacturing capability differs from administrator setting.')
        for path in ('/api/shared-kits', '/api/admin/guest-access', '/api/shared-kits/' + 'a' * 32 + '/unpublish'):
            status, _ = request_status(router + path, browser_headers, {})
            if status != 401:
                raise RuntimeError('Anonymous visitor can modify the shared service.')
        status, _ = request_status(router + '/api/cart', browser_headers)
        if status != 302:
            raise RuntimeError('Anonymous visitor can read a personal cart.')
        for path in ('/api/cart/add', '/api/cart/update', '/api/cart/clear', '/api/cart/export?format=bundle'):
            status, _ = request_status(router + path, browser_headers, {})
            if status != 401:
                raise RuntimeError('Anonymous visitor can modify or export a personal cart.')
        payload = {'items': [{'kitId': 'waveplate', 'quantity': 1}], 'extras': []}
        status, body = request_status(router + '/api/export?format=manufacturing', browser_headers, payload)
        if status != (200 if enabled else 401):
            raise RuntimeError('Anonymous export differs from the saved administrator setting.')
        if enabled:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                if archive.testzip() is not None:
                    raise RuntimeError('Guest export integrity failed.')
        status, body = request_status(router + '/api/export?format=bundle', browser_headers, payload, 64 * 1024 * 1024)
        if status != (200 if enabled and manufacturing_enabled else 403 if enabled else 401):
            raise RuntimeError('Guest manufacturing bundle differs from the saved independent download setting.')
        if status == 200:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                if archive.testzip() is not None:
                    raise RuntimeError('Guest manufacturing bundle integrity failed.')
    guest = {'X-ZZLAB-Internal-Token': token, 'X-ZZLAB-Guest': '1', 'X-ZZLAB-Role': 'guest'}
    status, _ = request_status(base + '/api/catalog', guest)
    if status != (200 if enabled else 401):
        raise RuntimeError('Backend guest enforcement differs from administrator setting.')
    for path in ('/api/catalog', '/api/shared-kits', '/index.html'):
        status, _ = request_status(base + path, headers)
        if status != 200:
            raise RuntimeError(f'Readonly account cannot access {path}.')
    status, body = request_status(base + '/api/session', headers)
    if status != 200 or json.loads(body) != {'role': 'readonly', 'canPublish': False, 'canDownload': True, 'canDownloadManufacturing': True}:
        raise RuntimeError('Readonly capabilities changed unexpectedly.')
    payload = {'items': [{'kitId': 'waveplate', 'quantity': 1}], 'extras': []}
    status, body = request_status(base + '/api/preview', headers, payload)
    if status != 200 or json.loads(body)['totals']['kits'] != 1:
        raise RuntimeError('Readonly preview failed.')
    exports = {}
    for format_name in ('lubang', 'manufacturing', 'bundle'):
        status, body = request_status(base + '/api/export?format=' + format_name, headers, payload, 64 * 1024 * 1024)
        if status != 200:
            raise RuntimeError(f'Readonly {format_name} export failed: HTTP {status}')
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            if archive.testzip() is not None:
                raise RuntimeError('Readonly export ZIP integrity failed.')
        exports[format_name] = {'status': status, 'bytes': len(body)}
    return {'guest_access_enabled': enabled, 'guest_manufacturing_downloads_enabled': manufacturing_enabled, 'policy_revision': policy['revision'],
            'anonymous_access_matches_setting': 'passed', 'admin_only_policy': 'passed',
            'trusted_internal_probe': 'passed', 'spoofed_identity_denied': 'passed',
            'readonly_use_download_preserved': 'passed', 'readonly_exports': exports,
            'production_settings_changed_by_verification': False, 'production_test_records_created': 0}



def verify_library_source(project_root=None, python=None):
    """Reject stale generated catalogs before touching the release or plan."""
    project_root = Path(project_root or SOURCE).resolve()
    compiler = project_root / 'tools/library.py'
    if not compiler.is_file() or not (project_root / 'library/manifest.json').is_file():
        raise RuntimeError('Structured library source or compiler is missing.')
    result = subprocess.run([str(python or PYTHON), str(compiler),
                             '--project-root', str(project_root), 'build', '--check', '--require-derived-index'],
                            cwd=project_root, text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Library source validation failed; release was not prepared.\n' +
                           (result.stderr or result.stdout).strip()[-6000:])
    return {'source_validation': 'passed', 'catalog_sha256': sha(project_root / 'catalog.json'),
            'protocol_version': json.loads((project_root / 'library/manifest.json').read_text())['protocolVersion']}


def prepare():
    library = verify_library_source()
    plan = SOURCE / 'deploy_plan'
    plan.mkdir(exist_ok=True)
    metadata = {'created_at': datetime.now().astimezone().isoformat(), 'files': {}, 'library': library,
                'prefix': PREFIX + '/', 'port': PORT, 'readonly_access': 'edit_and_download_no_publishing',
                'guest_access': 'administrator_controlled_default_off',
                'runtime': str(RUNTIME), 'nas_source': str(NAS), 'cad_runtime': cad_runtime_status(),
                'worker_environment': {'ZZLAB_CAD_PYTHON': str(CAD_PYTHON), 'ZZLAB_BOARD_CACHE': str(BOARD_CACHE)}}
    for name, patcher in [('router.py', patched_router), ('app.py', patched_dashboard)]:
        original_bytes = (LIVE / name).read_bytes()
        original = original_bytes.decode()
        candidate = patcher(original)
        ast.parse(candidate)
        atomic_write(plan / ('before_' + name), original)
        atomic_write(plan / name, candidate)
        difference = ''.join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                                fromfile=str(LIVE / name), tofile=str(LIVE / name)))
        atomic_write(plan / (name + '.patch'), difference)
        metadata['files'][name] = {'before_sha256': hashlib.sha256(original_bytes).hexdigest(), 'candidate_sha256': sha(plan / name)}
    metadata['role_regression_cases'] = verify_policy(plan / 'before_router.py', plan / 'router.py')
    verify_dashboard_policy(plan / 'before_app.py', plan / 'app.py')
    metadata['dashboard_role_and_session_regression'] = 'passed'
    atomic_write(plan / 'plan.json', json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    return plan, metadata


def ignore_source(directory, names):
    excluded = {'deploy_plan', 'deploy_history', '__pycache__', '.git', '.venv', 'node_modules', '.pytest_cache'}
    # Adoption history stays in the editable source and past NAS releases;
    # only the current authoritative records/reviews belong in each runtime.
    if Path(directory).resolve() == (SOURCE / 'library').resolve():
        excluded.add('backups')
    # Review logs are protocol evidence; other logs are runtime artifacts.
    review_evidence = Path(directory).resolve().is_relative_to((SOURCE / 'library' / 'reviews').resolve())
    return [name for name in names if name in excluded or name.startswith('.env') or name.endswith('.pyc') or (name.endswith('.log') and not review_evidence)]


def copy_runtime_source(destination):
    # Work also contains large geometry/spreadsheet QA trees; publish only named inputs.
    required_files = ('app.py', 'access_settings.py', 'shared_kits.py', 'manual_source_mount.py', 'metric_migration.py', 'cart.py', 'bom.py', 'exports.py', 'layout.py', 'stacked_layout.py', 'collision_overrides.py', 'moving_stages.py', 'optics_settings.py', 'optical_interaction.py', 'elevation.py', 'laser_adapter.py', 'laser_adapter_artifacts.py', 'laser_adapter_worker.py', 'breadboard.py', 'breadboard_worker.py', 'registered_boards.py', 'requirements.txt', 'requirements-cad.txt', 'catalog.json', 'manufacturing_specs.json')
    optional_files = ('BACKEND.md', 'BREADBOARD.md', 'PROJECT_FILES.md', 'SHARED_KITS.md', 'OPTICAL_RENDERING.md', '部署说明.md', 'deploy_support.py', 'optical_options.json', 'AGENTS.md', 'ARCHITECTURE.md')
    directories = ('assets', 'static', 'data_evidence', 'library', 'tools', 'skills')
    for name in required_files:
        if not (SOURCE / name).is_file():
            raise RuntimeError(f'Application input missing: {name}')
    destination.mkdir(parents=True, exist_ok=False)
    for name in required_files + optional_files + directories:
        source = SOURCE / name
        if not source.exists():
            continue
        if source.is_symlink() or (source.is_dir() and any(path.is_symlink() for path in source.rglob('*'))):
            raise RuntimeError(f'Release input contains an unreviewed symlink: {name}')
        if source.is_dir():
            shutil.copytree(source, destination / name, ignore=ignore_source)
        else:
            shutil.copy2(source, destination / name)


def bootstrap_service(*, check=True):
    """launchd can return EIO briefly while the previous job is unloading."""
    for attempt, delay in enumerate((0.5, 1, 2, 4, 0)):
        result = run(['launchctl', 'bootstrap', DOMAIN, PLIST], check=False)
        if result.returncode == 0:
            return result
        if result.returncode != 5 or not delay:
            if check:
                raise RuntimeError(f'Unable to register optics service after {attempt+1} attempt(s): {result.stderr[:600]}')
            return result
        time.sleep(delay)


def verify_listener_ownership():
    result = run(['/usr/sbin/lsof', '-nP', f'-iTCP:{PORT}', '-sTCP:LISTEN', '-t'], check=False)
    for value in set(result.stdout.split()):
        if not value.isdigit():
            raise RuntimeError('Could not identify the existing optics service listener.')
        process = run(['/bin/ps', '-p', value, '-o', 'command='])
        arguments = shlex.split(process.stdout.strip())
        if str(RUNTIME / 'current/app.py') not in arguments or '--auth-token-file' not in arguments:
            raise RuntimeError(f'Port {PORT} is held by preview or unrelated PID {value}; stop the owned preview before deploying.')


def deploy():
    plan, metadata = prepare()
    verify_listener_ownership()
    for name in ('app.py', 'catalog.json'):
        if not (SOURCE / name).is_file():
            raise RuntimeError(f'Application input missing: {name}')
    for name in ('assets', 'static'):
        if not (SOURCE / name).is_dir():
            raise RuntimeError(f'Application directory missing: {name}')
    run([PYTHON, '-c', 'import openpyxl'])
    if not cad_runtime_status()['ready']:
        raise RuntimeError('CAD runtime is missing; run --prepare-runtime before deploying.')
    BOARD_CACHE.mkdir(parents=True, exist_ok=True)
    secret_file = token_path()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    release = RUNTIME / 'releases' / stamp
    backup = RUNTIME / 'backups' / stamp
    backup.mkdir(parents=True, exist_ok=False)
    SHARED_DB.parent.mkdir(parents=True, exist_ok=True)
    if SHARED_DB.exists():
        with sqlite3.connect(SHARED_DB) as source_db, sqlite3.connect(backup / 'shared-kits.sqlite3') as backup_db:
            source_db.backup(backup_db)
    # Only provision the NAS backup directory when the existing volume is mounted.
    if not Path('/Volumes/ZZLab_001').is_mount():
        raise RuntimeError('NAS volume is not mounted; shared-library backup cannot be configured.')
    SHARED_BACKUP.parent.mkdir(parents=True, exist_ok=True)
    for name in ('router.py', 'app.py'):
        shutil.copy2(LIVE / name, backup / name)
    old_target = os.readlink(RUNTIME / 'current') if (RUNTIME / 'current').is_symlink() else None
    if (RUNTIME / 'current').exists() and old_target is None:
        raise RuntimeError('Existing current is not a managed symlink; refusing to overwrite it.')
    previous_plist = PLIST.read_bytes() if PLIST.exists() else None
    previous_launcher = (RUNTIME / 'bin/run-optics-kits').read_bytes() if (RUNTIME / 'bin/run-optics-kits').exists() else None
    if previous_plist:
        (backup / PLIST.name).write_bytes(previous_plist)
    if previous_launcher:
        (backup / 'run-optics-kits').write_bytes(previous_launcher)
    copy_runtime_source(release)
    shutil.copytree(plan, backup / 'integration_plan')
    command = [str(PYTHON), '-u', str(RUNTIME / 'current/app.py'), '--port', str(PORT),
               '--catalog', str(RUNTIME / 'current/catalog.json'), '--assets', str(RUNTIME / 'current/assets'),
               '--static', str(RUNTIME / 'current/static'), '--auth-token-file', str(secret_file),
               '--shared-db', str(SHARED_DB), '--shared-backup', str(SHARED_BACKUP)]
    launcher = '#!/bin/zsh\nset -euo pipefail\nexec ' + ' '.join(shlex.quote(value) for value in command) + '\n'
    plist_data = {'Label': LABEL, 'ProgramArguments': [str(RUNTIME / 'bin/run-optics-kits')],
                  'WorkingDirectory': str(RUNTIME / 'current'), 'RunAtLoad': True, 'KeepAlive': True,
                  'ThrottleInterval': 5, 'EnvironmentVariables': {'PYTHONUNBUFFERED': '1', 'ZZLAB_CAD_PYTHON': str(CAD_PYTHON), 'ZZLAB_BOARD_CACHE': str(BOARD_CACHE)},
                  'StandardOutPath': str(RUNTIME / 'logs/stdout.log'),
                  'StandardErrorPath': str(RUNTIME / 'logs/stderr.log')}
    atomic_write(backup / 'deployment.json', json.dumps(dict(metadata, previous_current=old_target,
                 release=str(release), backup=str(backup)), ensure_ascii=False, indent=2))
    changed_live = False
    try:
        (RUNTIME / 'logs').mkdir(exist_ok=True)
        link = RUNTIME / 'current.next'
        if link.is_symlink():
            link.unlink()
        link.symlink_to(release)
        link.replace(RUNTIME / 'current')
        atomic_write(RUNTIME / 'bin/run-optics-kits', launcher, 0o755)
        atomic_write(PLIST, plistlib.dumps(plist_data), 0o644)
        run(['launchctl', 'bootout', f'{DOMAIN}/{LABEL}'], check=False)
        run(['launchctl', 'enable', f'{DOMAIN}/{LABEL}'])
        bootstrap_service()
        wait_health(f'http://127.0.0.1:{PORT}/healthz')
        unauthorized, _ = request_status(f'http://127.0.0.1:{PORT}/api/catalog')
        if unauthorized not in (401, 403):
            raise RuntimeError('Backend is not enforcing the existing unified-auth proxy boundary.')
        internal_token = secret_file.read_text().strip()
        base_headers = {'X-ZZLAB-Internal-Token': internal_token, 'X-ZZLAB-Authenticated': '1',
                        'X-ZZLAB-User': 'deployment-check', 'X-ZZLAB-User-ID': '1', 'X-ZZLAB-Role': 'user'}
        denied_cases = [
            ({'X-ZZLAB-Internal-Token': ''}, 401),
            ({'X-ZZLAB-Internal-Token': 'invalid-deployment-probe'}, 401),
            ({'X-ZZLAB-Authenticated': ''}, 401),
            ({'X-ZZLAB-Role': ''}, 403),
            ({'X-ZZLAB-Role': 'unsupported-role'}, 403),
        ]
        for changes, expected in denied_cases:
            status, _ = request_status(f'http://127.0.0.1:{PORT}/api/catalog', {**base_headers, **changes})
            if status != expected:
                raise RuntimeError(f'Backend authentication rejection check failed: HTTP {status}')
        for role, expected in [('user', 200), ('admin', 200), ('readonly', 200)]:
            status, _ = request_status(f'http://127.0.0.1:{PORT}/api/catalog', {**base_headers, 'X-ZZLAB-Role': role})
            if status != expected:
                raise RuntimeError(f'Backend role boundary failed for {role}: HTTP {status}')
        download_report = verify_download_matrix(base_headers)
        metadata['shared_library_verification'] = verify_shared_library(base_headers)
        metadata['shared_library_storage'] = {'database': str(SHARED_DB), 'nas_backup': str(SHARED_BACKUP), 'outside_release': True}
        atomic_write(backup / 'download_verification.json', json.dumps(download_report, ensure_ascii=False, indent=2))
        metadata['download_verification'] = {'complete_bundles': download_report['complete_bundles'], 'expected_blocked_bundles': download_report['expected_blocked_bundles'], 'reference_only_packages': download_report['reference_only_packages'], 'blank_optional_optics': 'allowed', 'layout_verification': download_report['layout_verification'], 'browser_origin_verification': download_report['browser_origin_verification']}
        del internal_token
        del base_headers
        for name, hashes in metadata['files'].items():
            if sha(LIVE / name) != hashes['before_sha256']:
                raise RuntimeError(f'Live {name} changed during staging; refusing to overwrite concurrent work.')
        changed_live = True
        for name in ('router.py', 'app.py'):
            atomic_write(LIVE / name, (plan / name).read_bytes())
        run(['launchctl', 'kickstart', '-k', f'{DOMAIN}/com.zzlab.mac-preview-router'])
        run(['launchctl', 'kickstart', '-k', f'{DOMAIN}/com.zzlab.mac-preview-dashboard'])
        wait_health('http://127.0.0.1:18766/__router_health')
        metadata['access_verification'] = verify_authenticated_access()
        nas_release = NAS / 'releases' / stamp
        metadata['nas_copy_verification'] = copy_release_verified(release, nas_release)
        shutil.copytree(plan, NAS / 'integration' / stamp)
        atomic_write(NAS / 'CURRENT_RELEASE.txt', stamp + '\n')
        metadata.update(status='deployed', release=str(release), backup=str(backup), nas_release=str(nas_release))
        atomic_write(backup / 'result.json', json.dumps(metadata, ensure_ascii=False, indent=2))
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
    except Exception:
        if changed_live:
            for name, hashes in metadata['files'].items():
                if sha(LIVE / name) == hashes['candidate_sha256']:
                    atomic_write(LIVE / name, (backup / name).read_bytes())
            run(['launchctl', 'kickstart', '-k', f'{DOMAIN}/com.zzlab.mac-preview-router'], check=False)
            run(['launchctl', 'kickstart', '-k', f'{DOMAIN}/com.zzlab.mac-preview-dashboard'], check=False)
        run(['launchctl', 'bootout', f'{DOMAIN}/{LABEL}'], check=False)
        if old_target is not None:
            rollback_link = RUNTIME / 'current.rollback'
            rollback_link.symlink_to(old_target)
            rollback_link.replace(RUNTIME / 'current')
        elif (RUNTIME / 'current').is_symlink():
            (RUNTIME / 'current').unlink()
        if previous_launcher:
            atomic_write(RUNTIME / 'bin/run-optics-kits', previous_launcher, 0o755)
        if previous_plist:
            atomic_write(PLIST, previous_plist)
            bootstrap_service(check=False)
        elif PLIST.exists():
            PLIST.unlink()
        raise


def main():
    if not __debug__:
        raise RuntimeError('Do not run this safety-checked deployment script with Python optimization enabled.')
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--prepare', action='store_true')
    modes.add_argument('--prepare-runtime', action='store_true')
    modes.add_argument('--deploy', action='store_true')
    args = parser.parse_args()
    if args.prepare_runtime:
        print(json.dumps(dict(prepare_cad_runtime(), status='worker_prepared_not_deployed'), ensure_ascii=False, indent=2))
    elif args.deploy:
        deploy()
    elif args.prepare:
        plan, metadata = prepare()
        print(json.dumps(dict(metadata, status='prepared_not_deployed', plan=str(plan)), ensure_ascii=False, indent=2))
    else:
        print('No production changes. Use --prepare-runtime for a missing isolated CAD worker, --prepare for reviewable diffs; --deploy only after the root task confirms ready.')


if __name__ == '__main__':
    main()
