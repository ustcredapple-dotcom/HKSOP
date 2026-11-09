"""Direct-board post replacement, exact physical heights and immutable exports."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bom import APIError, aggregate, load_catalog, validate_catalog
from breadboard import board_specs
from cart import CartStore
from elevation import universal_post_plan
from exports import export_result
from shared_kits import Identity, SharedKitStore, prepare_project
from test_elevation import arrangement, board
from test_shared_kits import project


def catalog_fixture():
    """Real kit BOM plus isolated new-post fixtures; never edits live assets."""
    catalog = load_catalog(ROOT / 'catalog.json')
    components = {c['id']: c for c in catalog['components']}
    posts = [{'componentId': cid, 'heightMm': h} for cid, h in
             [('custom-02', 12.7), ('custom-01', 25.4), ('custom-03', 38.1)]]
    for half_inches in range(4, 13):
        label = str(half_inches//2) + ('p5' if half_inches % 2 else '')
        cid = f'custom-post-{label}inch'
        component = copy.deepcopy(components['custom-01'])
        component.update(id=cid, name=f'万能柱 {half_inches/2:g} inch', model=f'TEST-POST-{label}',
                         stepPath=f'posts/{cid}.step', drawingPath=f'posts/{cid}.pdf', postTopThread='M4')
        if cid in components:
            components[cid].update(component)
        else:
            catalog['components'].append(component)
        posts.append({'componentId': cid, 'heightMm': half_inches*12.7})
    for cid in ('custom-01', 'custom-02', 'custom-03'):
        components[cid]['postTopThread'] = 'M6' if cid == 'custom-02' else 'M4'
    catalog['universalPostSeries'] = {'posts': posts}
    return validate_catalog(catalog)


def single(kid='pbs-fixed', elevation=25.4):
    return {'board': board(500, 400), 'instances': [
        {'id': 'optic', 'kitId': kid, 'xMm': 100, 'yMm': 100, 'rotationDeg': 0, 'elevationMm': elevation}]}


def rows_by_id(preview, kind='manufacturing'):
    return {r['componentId']: r for r in preview[kind]}


class UniversalPostReplacementTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog_fixture()

    def test_root_post_is_replaced_one_for_one_not_added_and_support_override_is_ignored(self):
        layout = single()
        layout['instances'][0]['elevationSupportCount'] = 128
        before = copy.deepcopy(layout)
        result = aggregate(self.catalog, {'layout': layout})
        self.assertEqual(layout, before)
        self.assertTrue(result['layoutValidation']['valid'], result['layoutValidation']['issues'])
        rows = rows_by_id(result)
        self.assertNotIn('custom-01', rows)
        self.assertEqual(rows['custom-post-2inch']['quantity'], 1)
        self.assertEqual(rows['custom-post-2inch']['manufacturingSpec']['material'], '316L 不锈钢')
        self.assertEqual([r for r in result['lubang'] if r['model'].startswith('OP1-')], [])
        group, = result['elevationAccessories']
        self.assertEqual((group['mode'], group['supportCount']), ('universalPostReplacement', 1))
        material, = group['materials']
        self.assertEqual((material['replacesComponentId'], material['heightMm'], material['quantity']), ('custom-01', 50.8, 1))
        axis, = result['layoutValidation']['axisHeights']
        self.assertEqual((axis['effectiveAxisHeightMm'], axis['heightResolved']), (88.9, True))
        self.assertEqual(axis['elevationSupportCount'], 1)
        self.assertEqual(result['universalPostReplacements'][0]['instanceId'], 'optic')
        source, = rows['custom-post-2inch']['kits']
        self.assertEqual((source['source'], source['instanceId'], source['quantity']), ('universalPostReplacement', 'optic', 1))

    def test_identical_kits_on_root_and_small_board_keep_separate_original_quantities(self):
        layout = {'board': board(1500, 625), 'instances': [
            {'id': 'changed', 'kitId': 'pbs-fixed', 'xMm': 100, 'yMm': 100, 'rotationDeg': 0, 'elevationMm': 25.4},
            {'id': 'unchanged', 'kitId': 'pbs-fixed', 'xMm': 300, 'yMm': 100, 'rotationDeg': 0},
            {'id': 'small-optic', 'kitId': 'pbs-fixed', 'boardId': 'small', 'xMm': 75, 'yMm': 75, 'rotationDeg': 0, 'elevationMm': 10}],
            'subBoards': [{'id': 'small', 'name': '小板', 'board': board(200, 150, 12.5), 'xMm': 1000, 'yMm': 0, 'rotationDeg': 0, 'elevationMm': 20}]}
        result = aggregate(self.catalog, {'layout': layout})
        rows = rows_by_id(result)
        self.assertEqual(rows['custom-01']['quantity'], 2)
        self.assertEqual(rows['custom-01']['kits'][0]['instanceIds'], ['unchanged', 'small-optic'])
        self.assertEqual(rows['custom-post-2inch']['quantity'], 1)
        self.assertEqual(rows['custom-08']['quantity'], 3)
        groups = {g['targetId']: g for g in result['elevationAccessories']}
        self.assertEqual(groups['small']['materials'][0]['quantity'], 4)
        self.assertEqual(groups['small-optic']['materials'][0]['quantity'], 1)
        self.assertEqual(groups['changed']['mode'], 'universalPostReplacement')
        self.assertEqual({r['model']: r['quantity'] for r in result['lubang'] if r['model'].startswith('OP1-')}, {'OP1-20B6': 4, 'OP1-10B6': 1})

    def test_compound_multiple_post_sizes_replace_atomically_without_quantity_cross_talk(self):
        kit = next(k for k in self.catalog['kits'] if k['id'] == 'pbs-fixed')
        kit['components'] = [{'componentId': cid, 'quantity': q} for cid, q in [('custom-01', 8), ('custom-02', 1), ('custom-03', 2)]]
        result = aggregate(self.catalog, {'layout': single()})
        post_rows = {cid: row['quantity'] for cid, row in rows_by_id(result).items() if not row.get('generatedBoard')}
        self.assertEqual(post_rows, {'custom-post-2inch': 8, 'custom-03': 1, 'custom-post-2p5inch': 2})
        self.assertEqual(sum(r['quantity'] for r in result['universalPostReplacements']), 11)
        self.assertEqual(result['layoutValidation']['axisHeights'][0]['elevationSupportCount'], 11)
        self.assertEqual(result['elevationAccessories'][0]['supportCount'], 1)
        # The shortest original reaches an available 6-inch post, but others
        # overflow. No partial replacement and no fallback OP1 is permitted.
        failure = aggregate(self.catalog, {'layout': single(elevation=139.7)})
        post_rows = {cid: row['quantity'] for cid, row in rows_by_id(failure).items() if not row.get('generatedBoard')}
        self.assertEqual(post_rows, {'custom-01': 8, 'custom-02': 1, 'custom-03': 2})
        self.assertEqual(failure['universalPostReplacements'], [])
        self.assertEqual(failure['elevationAccessories'], [])
        self.assertFalse(failure['layoutValidation']['valid'])
        self.assertEqual(failure['layoutValidation']['axisHeights'][0]['elevationSupportCount'], 11)
        unchanged = single(elevation=0)
        unchanged['instances'][0]['elevationSupportCount'] = 77
        self.assertEqual(aggregate(self.catalog, {'layout': unchanged})['layoutValidation']['axisHeights'][0]['elevationSupportCount'], 11)

    def test_non_step_and_out_of_range_heights_are_unresolved_and_block_export_cart_share(self):
        for elevation in (.1, 71.5, 1000):
            with self.subTest(elevation=elevation):
                layout = single(elevation=elevation)
                result = aggregate(self.catalog, {'layout': layout})
                self.assertEqual({i['code'] for i in result['layoutValidation']['issues']}, {'universal_post_unavailable'})
                axis, = result['layoutValidation']['axisHeights']
                self.assertIsNone(axis['effectiveAxisHeightMm'])
                self.assertIsNone(result['layoutValidation']['axisHeightReferenceMm'])
                self.assertEqual(axis['requestedEffectiveAxisHeightMm'], 63.5+elevation)
                self.assertFalse(axis['heightResolved'])
                self.assertEqual(result['elevationAccessories'], [])
                self.assertEqual(rows_by_id(result)['custom-01']['quantity'], 1)
                with self.assertRaises(APIError) as error:
                    export_result(result, 'manufacturing', ROOT/'assets', ROOT/'static')
                self.assertEqual(error.exception.code, 'layout_invalid')
                saved = project()
                saved.update(layout=layout, catalogReferenced=[{'id': 'pbs-fixed', 'name': 'PBS'}])
                saved['ui']['selectedIds'] = []
                with self.assertRaises(APIError) as error:
                    prepare_project(saved, self.catalog)
                self.assertEqual(error.exception.code, 'invalid_shared_layout')
        with tempfile.TemporaryDirectory() as temp:
            cart = CartStore(SharedKitStore(Path(temp)/'cart.sqlite3'))
            user = Identity('unavailable-post', '测试', 'user')
            empty = cart.read(user)
            with self.assertRaises(APIError) as error:
                cart.add(user, {**{k: empty[k] for k in ('cartId', 'revision')}, 'requestId': 'unavailable-post-0001', 'name': '无可用柱', 'payload': {'layout': single(elevation=.1)}}, self.catalog)
            self.assertEqual(error.exception.code, 'layout_invalid')

    def test_zero_elevation_and_non_layout_kit_purchase_preserve_original_posts(self):
        for payload, expected in [({'layout': single(elevation=0)}, 1), ({'items': [{'kitId': 'pbs-fixed', 'quantity': 3}]}, 3)]:
            result = aggregate(self.catalog, payload)
            self.assertEqual(rows_by_id(result)['custom-01']['quantity'], expected)
            self.assertEqual(result['elevationAccessories'], [])
            self.assertEqual(result['universalPostReplacements'], [])
        # Laser has no universal post and retains the OP1 plus fractional shim policy.
        layout = arrangement()
        layout['instances'] = [layout['instances'][0]]
        layout['instances'][0]['elevationMm'] = 71.5
        result = aggregate(self.catalog, {'layout': layout})
        self.assertTrue(result['layoutValidation']['valid'])
        self.assertEqual({r['model']: r['quantity'] for r in result['lubang']}, {'OP1-70B6': 4, 'OP1-1C': 4})
        self.assertEqual(result['universalPostReplacements'], [])

    def test_real_series_aligns_root_waveplate_with_laser_and_keeps_small_board_op1(self):
        catalog = load_catalog(ROOT/'catalog.json')
        legacy_posts = [p for p in catalog['universalPostSeries']['posts'] if p.get('seriesId', 'legacy-imperial') == 'legacy-imperial']
        self.assertEqual([p['heightMm'] for p in legacy_posts], [n*127/10 for n in range(1, 13)])
        components = {c['id']: c for c in catalog['components']}
        for spec in legacy_posts:
            component = components[spec['componentId']]
            self.assertEqual(component['postTopThread'], 'M6' if spec['heightMm'] == 12.7 else 'M4')
            self.assertEqual(component['manufacturingSpec']['material'], '316L 不锈钢')
            self.assertEqual(component['manufacturingSpec']['surfaceTreatment'], '退磁、喷砂')
        layout = arrangement(small=True)
        layout['board']['widthMm'] = 1500
        layout['instances'][0].update(yMm=245.5, laserAdapter={'enabled': True, 'thicknessMm': 17.4})
        layout['instances'].append({'id': 'root-waveplate', 'kitId': 'waveplate', 'xMm': 800, 'yMm': 300, 'rotationDeg': 0, 'elevationMm': 88.9})
        layout['subBoards'][0].update(xMm=1100, elevationMm=76.2)
        result = aggregate(catalog, {'layout': layout})
        self.assertTrue(result['layoutValidation']['valid'], result['layoutValidation']['issues'])
        self.assertEqual([a['effectiveAxisHeightMm'] for a in result['layoutValidation']['axisHeights']], [152.4]*3)
        replacement, = result['universalPostReplacements']
        self.assertEqual((replacement['replacementComponentId'], replacement['replacementHeightMm']), ('custom-post-4p5inch', 114.3))
        self.assertEqual(rows_by_id(result)['custom-01']['quantity'], 1, 'small-board PBS keeps its original post')
        self.assertEqual(rows_by_id(result)['custom-post-4p5inch']['quantity'], 1)
        support = next(g for g in result['elevationAccessories'] if g['targetType'] == 'board')
        self.assertEqual([(r['model'], r['quantity']) for r in support['materials']], [('OP1-75B6', 4), ('OP1-1C', 4), ('待确认', 4)])

    def test_thread_change_is_nonblocking_manufacturing_review(self):
        result = aggregate(self.catalog, {'layout': single('pbs-adjustable', 25.4)})
        record, = result['universalPostReplacements']
        self.assertEqual((record['originalTopThread'], record['replacementTopThread']), ('M6', 'M4'))
        reviews = [item for group in result['reviewGroups'] for item in group['items'] if item['code'] == 'universal_post_connection']
        self.assertEqual(len(reviews), 1)
        self.assertFalse(reviews[0]['blocking'])
        self.assertIn('M6 →', reviews[0]['details'])
        self.assertEqual(rows_by_id(result)['custom-03']['quantity'], 1)

    def test_catalog_rejects_ambiguous_or_unregistered_series_and_invalid_top_threads(self):
        changes = [lambda c: c.update(universalPostSeries=[]),
                   lambda c: c['universalPostSeries']['posts'][0].update(componentId='missing'),
                   lambda c: c['universalPostSeries']['posts'][0].update(componentId='laser-308nm'),
                   lambda c: c['universalPostSeries']['posts'][0].update(heightMm=12.71),
                   lambda c: c['universalPostSeries']['posts'][0].update(heightMm=25.4),
                   lambda c: c['universalPostSeries']['posts'].append(c['universalPostSeries']['posts'][0]),
                   lambda c: next(p for p in c['components'] if p['id'] == 'custom-01').update(postTopThread='M8')]
        for change in changes:
            with self.subTest(change=change):
                bad = copy.deepcopy(self.catalog)
                change(bad)
                with self.assertRaises(APIError) as error:
                    validate_catalog(bad)
                self.assertEqual(error.exception.code, 'catalog_invalid')

    def test_same_spec_replacements_merge_but_cart_override_and_export_keep_new_assets_only(self):
        layout = single()
        layout['instances'].append({**layout['instances'][0], 'id': 'optic2', 'xMm': 250})
        result = aggregate(self.catalog, {'layout': layout})
        self.assertTrue(result['layoutValidation']['valid'])
        self.assertEqual(rows_by_id(result)['custom-post-2inch']['quantity'], 2)
        saved = project()
        saved.update(layout=layout, catalogReferenced=[{'id': 'pbs-fixed', 'name': 'PBS'}])
        saved['ui']['selectedIds'] = []
        self.assertEqual(prepare_project(saved, self.catalog)['universalPostReplacements'], result['universalPostReplacements'])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cart = CartStore(SharedKitStore(root/'cart.sqlite3'))
            user = Identity('replacement-user', '测试', 'user')
            empty = cart.read(user)
            envelope = cart.add(user, {**{k: empty[k] for k in ('cartId', 'revision')}, 'requestId': 'post-replacement-0001', 'name': '换柱方案', 'payload': {'layout': layout}}, self.catalog)
            new = next(r for r in envelope['preview']['manufacturing'] if r.get('sourceComponentId') == 'custom-post-2inch')
            choices = copy.deepcopy(envelope['items'])
            for choice in choices:
                choice['selected'] = choice['componentId'] == new['componentId']
                if choice['selected']:
                    choice['quantity'] = 7
            envelope = cart.update(user, {**{k: envelope[k] for k in ('cartId', 'revision')}, 'items': choices})
            exported = cart.for_export(user, {k: envelope[k] for k in ('cartId', 'revision')}, self.catalog)
            self.assertEqual(exported['manufacturing'][0]['quantity'], 7)
            self.assertEqual(exported['cartSources'][0]['universalPostReplacements'], result['universalPostReplacements'])
            # Isolated registered fixture assets demonstrate exact archive selection.
            for field in ('stepPath', 'drawingPath'):
                asset = root/exported['manufacturing'][0][field]
                asset.parent.mkdir(parents=True, exist_ok=True)
                asset.write_bytes(b'fixture source only')
            content, _, _ = export_result(exported, 'bundle', root, ROOT/'static')
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
                self.assertEqual(sum(n.endswith('.step') for n in names), 1)
                self.assertTrue(any(n.endswith('custom-post-2inch.step') for n in names))
                config = json.loads(archive.read('套件配置.json'))
                self.assertEqual(config['components'][0]['quantity'], 7)
                self.assertEqual(config['cartSources'][0]['universalPostReplacements'], result['universalPostReplacements'])
                production = archive.read('生产清单.xlsx')
            wb = load_workbook(io.BytesIO(production), data_only=True)
            self.assertEqual(wb['生产清单']['E6'].value, 7)
            self.assertEqual(wb['万能柱替换']['D6'].value, 'custom-01')
            self.assertEqual(wb['万能柱替换']['F6'].value, 'custom-post-2inch')
            self.assertEqual(wb['万能柱替换']['I6'].value, 1)
            self.assertNotIn('垫高材料', wb.sheetnames)
            wb.close()


if __name__ == '__main__':
    unittest.main()
