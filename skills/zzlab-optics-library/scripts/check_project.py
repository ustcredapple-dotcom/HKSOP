#!/usr/bin/env python3
"""Read-only check of a delivered ZZLab library project, from any skill location."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path, help='Project containing library/ and catalog.json')
    args = parser.parse_args()
    root = args.project.expanduser().resolve()
    required = ['catalog.json', 'library/manifest.json', 'library/catalog-meta.json',
                'library/records', 'tools/library.py', 'bom.py']
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        parser.exit(2, 'Missing project inputs: ' + ', '.join(missing) + '\n')
    try:
        manifest = json.loads((root / 'library/manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        parser.exit(2, 'Invalid manifest: ' + str(exc) + '\n')
    if manifest.get('protocolVersion') != 'zzlab-optics-library-v1':
        parser.exit(2, 'Unsupported library protocol. Read the delivered version before importing.\n')
    # Use this Python so a caller can select the project's installed dependencies.
    result = subprocess.run([sys.executable, str(root / 'tools/library.py'),
                             '--project-root', str(root), 'build', '--check'], cwd=root)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
