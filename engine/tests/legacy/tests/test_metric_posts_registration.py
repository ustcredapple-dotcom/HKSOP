"""Test additive registration in an isolated copy, never production CAD/assets.

Byte fixtures are deliberately synthetic; this suite verifies registration's
provenance gates and preservation, not the CAD/PDF generator's separate review.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'qa'))
import register_metric_posts as migration
import verify_metric_posts_catalog as verification


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class MetricPostRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='metric-post-registration-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.e = self.root / migration.REL_EVIDENCE
        source_e = ROOT / migration.REL_EVIDENCE
        self.baseline = migration.read(source_e / 'baseline/catalog.json')
        self.targets = migration.read(source_e / 'targets.json')
        template = migration.read(source_e / 'source-manifest-template.json')
        write(self.e / 'targets.json', self.targets)
        write(self.e / 'source-manifest-template.json', template)
        write(self.e / 'baseline/catalog.json', self.baseline)
        write(self.root / 'catalog.json', self.baseline)
        assets = []
        old_by_id = {c['id']: c for c in self.baseline['components']}
        for target in self.targets:
            old = old_by_id[target['oldComponentId']]
            for field in ('stepPath', 'drawingPath'):
                relative = 'assets/' + old[field]
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(('synthetic original: ' + relative).encode())
                assets.append({'componentId': old['id'], 'path': relative, 'sha256': migration.sha(path)})
        write(self.e / 'baseline-manifest.json', {'originalAssets': assets})
        self.source_path = self.e / 'test-source-manifest.json'
        self.stage_path = self.e / 'staged-manifest.json'
        self.review_path = self.e / 'pdf-review.json'
        self.source = copy.deepcopy(template)
        self.source.update(status='verified-native-exports', versionId='a' * 24)
        for row in self.source['exports']:
            path = self.e / 'downloads' / row['downloadFileName']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('synthetic new STEP: ' + row['componentId']).encode())
            row.update(downloadPath=str(path), sha256=migration.sha(path),
                       sourceUrl=f'https://cad.onshape.com/documents/{migration.DOCUMENT}/v/{self.source["versionId"]}/e/{row["elementId"]}')
        write(self.source_path, self.source)
        source_hash = migration.sha(self.source_path)
        parts, reviews = [], []
        for row, target in zip(self.source['exports'], self.targets):
            stage = self.e / 'generated' / f'H{row["heightMm"]:g}mm'
            stage.mkdir(parents=True)
            step, drawing = stage / (row['stem'] + '.step'), stage / (row['stem'] + '_加工审核图.pdf')
            step.write_bytes(Path(row['downloadPath']).read_bytes())
            drawing.write_bytes(('synthetic new PDF: ' + row['componentId']).encode())
            component = dict(row, sourceVersionId=self.source['versionId'])
            part = {'schemaVersion': 'zzlab-metric-post-staged-v1', 'component': component,
                    'downloadPath': row['downloadPath'], 'downloadSha256': row['sha256'],
                    'sourceManifestSha256': source_hash,
                    'geometryValidation': {'valid': True, 'solidCount': 1,
                         'heightMm': target['heightMm'], 'postCylinderHeightMm': target['cylinderHeightMm'],
                         'baseThicknessMm': 4, 'revision': 'M1', 'legacyHeightMm': target['oldHeightMm']},
                    'files': {'step': {'filename': step.name, 'sha256': migration.sha(step)},
                              'drawing': {'filename': drawing.name, 'sha256': migration.sha(drawing)}},
                    'material': '316L 不锈钢', 'surfaceTreatment': '退磁、喷砂',
                    'status': 'awaiting-pdf-visual-review', 'published': False}
            parts.append(part)
            reviews.append({'componentId': row['componentId'], 'drawingSha256': migration.sha(drawing),
                            'pages': [{'page': 1, 'passed': True}, {'page': 2, 'passed': True}]})
        self.staged = {'sourceVersionId': self.source['versionId'], 'parts': parts,
                       'status': 'awaiting-pdf-visual-review', 'published': False}
        self.review = {'passed': True, 'sourceManifestSha256': source_hash, 'parts': reviews}
        self.flush_stage()
        write(self.review_path, self.review)
        self.initial_hash = migration.sha(self.root / 'catalog.json')

    def flush_stage(self):
        write(self.stage_path, self.staged)
        for part in self.staged['parts']:
            write(self.e / 'generated' / f'H{part["component"]["heightMm"]:g}mm' / 'report.json', part)

    def args(self):
        return {'source_manifest': self.source_path, 'staged_manifest': self.stage_path, 'review_path': self.review_path}

    def preflight(self):
        return migration.prepare(self.root, **self.args())

    def assert_unpublished(self):
        self.assertEqual(migration.sha(self.root / 'catalog.json'), self.initial_hash)
        self.assertFalse((self.root / 'assets/step/01_基本安装件' / migration.SERIES).exists())
        migration.original_assets(self.root, self.e)

    def test_readonly_preflight_preserves_all_existing_records(self):
        plan = self.preflight()
        self.assert_unpublished()
        self.assertEqual(len(plan['transfers']), 24)
        self.assertEqual(plan['preservedKitCount'], len(self.baseline['kits']))
        self.assertEqual(plan['catalog']['kits'], self.baseline['kits'])
        self.assertEqual(plan['catalog']['components'][:len(self.baseline['components'])], self.baseline['components'])
        posts = plan['catalog']['universalPostSeries']['posts'][-12:]
        self.assertEqual([p['heightMm'] for p in posts], [12.5 * n for n in range(1, 13)])
        self.assertEqual({p['seriesId'] for p in posts}, {migration.SERIES})
        added = plan['catalog']['components'][-12:]
        self.assertEqual(added[0]['postTopThread'], 'M6')
        self.assertIn('M6×1 贯穿', added[0]['notes'])
        self.assertEqual(added[1]['postTopThread'], 'M4')
        self.assertIn('非 M6 贯穿孔', added[1]['notes'])
        self.assertTrue(all(not c['productionReady'] for c in added))

    def test_apply_and_verify_are_additive_and_idempotent(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            verification.verify(self.root, **self.args())
        plan = self.preflight()
        migration.apply(self.root, plan)
        report = verification.verify(self.root, **self.args())
        self.assertEqual((report['metricPostCount'], report['assetCount'], report['originalAssetsUnchanged']), (12, 24, 24))
        digest = migration.sha(self.root / 'catalog.json')
        migration.apply(self.root, self.preflight())
        self.assertEqual(migration.sha(self.root / 'catalog.json'), digest)
        for row in plan['transfers']:
            self.assertEqual(migration.sha(row['source']), migration.sha(row['destination']))

    def test_workspace_or_old_inch_source_cannot_be_published(self):
        self.source['exports'][0]['sourceUrl'] = self.source['exports'][0]['sourceUrl'].replace('/v/', '/w/')
        write(self.source_path, self.source)
        # Rebind reports and review: a workspace is still not an immutable source.
        digest = migration.sha(self.source_path)
        for part in self.staged['parts']:
            part['sourceManifestSha256'] = digest
        self.review['sourceManifestSha256'] = digest
        self.flush_stage()
        write(self.review_path, self.review)
        with self.assertRaisesRegex(ValueError, 'immutable element'):
            self.preflight()
        self.source['versionId'] = self.targets[0]['originalSourceUrl'].split('/v/')[1].split('/')[0]
        write(self.source_path, self.source)
        with self.assertRaisesRegex(ValueError, 'original inch-post'):
            self.preflight()
        self.assert_unpublished()

    def test_missing_draft_or_wrong_height_is_rejected(self):
        original = copy.deepcopy(self.staged)
        mutations = [lambda s: s.update(status='geometry-validated'),
                     lambda s: s['parts'].pop(),
                     lambda s: s['parts'][0]['geometryValidation'].update(heightMm=12.7)]
        for mutate in mutations:
            self.staged = copy.deepcopy(original)
            mutate(self.staged)
            self.flush_stage()
            with self.assertRaises(ValueError):
                self.preflight()
            self.assert_unpublished()

    def test_review_must_bind_source_bytes_pdf_and_every_page(self):
        original = copy.deepcopy(self.review)
        mutations = [lambda r: r.update(sourceManifestSha256='0' * 64),
                     lambda r: r['parts'][0].update(drawingSha256='0' * 64),
                     lambda r: r['parts'][0]['pages'].pop(),
                     lambda r: r['parts'][0]['pages'][1].update(passed=False)]
        for mutate in mutations:
            self.review = copy.deepcopy(original)
            mutate(self.review)
            write(self.review_path, self.review)
            with self.assertRaises(ValueError):
                self.preflight()
            self.assert_unpublished()

    def test_changed_native_bytes_and_asset_conflicts_are_rejected(self):
        plan = self.preflight()
        native = Path(self.source['exports'][0]['downloadPath'])
        original = native.read_bytes()
        native.write_bytes(original + b' changed')
        with self.assertRaisesRegex(ValueError, 'original native export'):
            self.preflight()
        native.write_bytes(original)
        destination = Path(plan['transfers'][0]['destination'])
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b'pre-existing unrelated bytes')
        with self.assertRaisesRegex(ValueError, 'refusing to replace an existing asset'):
            self.preflight()
        self.assertEqual(destination.read_bytes(), b'pre-existing unrelated bytes')
        self.assertEqual(migration.sha(self.root / 'catalog.json'), self.initial_hash)

    def test_preflight_does_not_authorize_later_changed_inputs(self):
        plan = self.preflight()
        self.review['parts'][0]['pages'][1]['passed'] = False
        write(self.review_path, self.review)
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            migration.apply(self.root, plan)
        self.assert_unpublished()

    def test_cli_rejects_overwriting_review_before_applying(self):
        result = subprocess.run([sys.executable, str(ROOT / 'qa/register_metric_posts.py'),
            '--root', str(self.root), '--source-manifest', str(self.source_path),
            '--staged-manifest', str(self.stage_path), '--review', str(self.review_path),
            '--apply', '--output', str(self.review_path)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Report must be a new file', result.stderr)
        self.assertEqual(migration.read(self.review_path), self.review)
        self.assert_unpublished()

    def test_old_catalog_or_assets_cannot_be_silently_changed(self):
        catalog = copy.deepcopy(self.baseline)
        catalog['kits'][0]['name'] += ' changed'
        write(self.root / 'catalog.json', catalog)
        with self.assertRaisesRegex(ValueError, 'Existing kits'):
            self.preflight()
        write(self.root / 'catalog.json', self.baseline)
        asset = self.root / migration.read(self.e / 'baseline-manifest.json')['originalAssets'][0]['path']
        asset.write_bytes(b'changed old asset')
        with self.assertRaisesRegex(ValueError, 'Original asset changed'):
            self.preflight()


if __name__ == '__main__':
    unittest.main()
