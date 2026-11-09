"""Removal means no product/assets, with guarded compatibility for saved carts."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from bom import APIError, load_catalog
from cart import CartStore, rows, combine
from elevation import validate_universal_posts
from exports import export_result
from shared_kits import Identity, SharedKitStore

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path('/Users/Shared/ZZLAB/OpticsKits/releases/20261008-182837')
sha = lambda data: hashlib.sha256(data).hexdigest()


class RetiredImperialPostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / 'catalog.json')
        cls.rule = cls.catalog['universalPostSeries']['metricMigration']
        cls.mapping = cls.rule['componentMap']

    def test_only_products_and_files_removed_all_other_records_unchanged(self):
        old = json.loads((BASELINE / 'catalog.json').read_bytes())
        new = json.loads((ROOT / 'catalog.json').read_bytes())
        self.assertEqual(len(self.mapping), 12)
        self.assertEqual(set(self.rule['retiredComponents']), set(self.mapping))
        self.assertFalse(set(self.mapping) & {c['id'] for c in new['components']})
        for group in ('components', 'kits', 'registeredBoards', 'stageModules'):
            self.assertEqual([r for r in old[group] if r['id'] not in self.mapping], new[group])
        for cid, record in self.rule['retiredComponents'].items():
            self.assertFalse((ROOT / 'library/records/components' / (cid + '.json')).exists())
            for key in ('stepPath', 'drawingPath'):
                self.assertFalse((ROOT / 'assets' / record[key]).exists())
        self.assertEqual([x['heightMm'] for x in self.catalog['universalPostSeries']['posts']], [12.5 * i for i in range(1, 13)])

    def fixture(self, folder):
        old = load_catalog(BASELINE / 'catalog.json')
        kit = next(k for k in old['kits'] if k['id'] == 'pbs-adjustable')
        kit['components'] = [{'componentId': cid, 'quantity': n + 1} for n, cid in enumerate(self.mapping)]
        backing = SharedKitStore(Path(folder) / 'cart.sqlite3')
        user = Identity('retirement-fixture', 'fixture', 'user')
        store = CartStore(backing, old)
        first = store.read(user)
        env = store.add(user, {**{k:first[k] for k in ('cartId','revision')}, 'requestId':'legacy-posts-0001',
                              'name':'旧工程', 'payload':{'items':[{'kitId':'pbs-adjustable','quantity':1}]}}, old)
        return backing, user, store, env

    def test_legacy_cart_reads_exports_metric_without_state_or_choice_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            backing, user, store, env = self.fixture(folder)
            choices = copy.deepcopy(env['items'])
            choices[0].update(quantity=17, selected=False)
            choices[1].update(removed=True)
            env = store.update(user, {**{k:env[k] for k in ('cartId','revision')}, 'items':choices})
            def stored():
                with backing.connect() as db:
                    return [tuple(r) for r in db.execute('SELECT * FROM optics_carts')]
            before = stored()
            current = CartStore(backing, self.catalog)
            view = current.read(user)
            self.assertEqual(env['items'], view['items'])
            self.assertEqual(env['revision'], view['revision'])
            current_by_id = {c['id']:c for c in self.catalog['components']}
            for row in view['preview']['manufacturing']:
                target = current_by_id[self.mapping[row['retiredSourceComponentId']]]
                for key in ('name','model','stepPath','drawingPath','manufacturingSpec'):
                    self.assertEqual(row[key], target[key])
                self.assertEqual(row['sourceComponentId'], target['id'])
            result = current.for_export(user, {k:view[k] for k in ('cartId','revision')}, self.catalog)
            self.assertEqual(len(result['manufacturing']), 10)
            data, _, _ = export_result(result, 'bundle', ROOT / 'assets', ROOT / 'static', self.catalog)
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                self.assertIsNone(z.testzip())
                hashes = {sha(z.read(n)) for n in z.namelist()}
                for row in result['manufacturing']:
                    for key in ('stepPath','drawingPath'):
                        self.assertIn(sha((ROOT / 'assets' / row[key]).read_bytes()), hashes)
                for c in load_catalog(BASELINE / 'catalog.json')['components']:
                    if c['id'] in self.mapping:
                        self.assertNotIn(sha((BASELINE / 'assets' / c['stepPath']).read_bytes()), hashes)
            self.assertEqual(stored(), before)

    def test_forged_old_paths_remain_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            backing, user, store, env = self.fixture(folder)
            with backing.connect() as db:
                record, state = store.read_record(db, user)
                state['sources'][0]['preview']['manufacturing'][0]['stepPath'] = '../private.step'
                malformed, _ = combine(state)
                state['choices'] = {r['componentId']:{'quantity':r['quantity'], 'selected':True, 'removed':False} for r in rows(malformed)}
                # Isolated malformed snapshot fixture; no production state access.
                store.save(db, user, record, state)
            current = CartStore(backing, self.catalog)
            view = current.read(user)
            with self.assertRaises(APIError) as caught:
                current.for_export(user, {k:view[k] for k in ('cartId','revision')}, self.catalog)
            self.assertEqual(caught.exception.code, 'cart_source_changed')

    def test_compatibility_descriptors_cannot_target_unknown_or_nonmetric_products(self):
        for mutate in [lambda r:r['retiredComponents'].pop('custom-01'),
                       lambda r:r['retiredComponents']['custom-01'].update(replacementComponentId='custom-09'),
                       lambda r:r['retiredComponents']['custom-01'].update(stepPath='../private.step')]:
            cat = copy.deepcopy(self.catalog)
            mutate(cat['universalPostSeries']['metricMigration'])
            with self.assertRaises(APIError): validate_universal_posts(cat)


if __name__ == '__main__':
    unittest.main()
