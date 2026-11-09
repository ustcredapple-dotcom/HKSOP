"""Measured coating data survives projects and carts without changing purchases."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from bom import APIError, aggregate
from cart import CartStore
from layout import layout_json
from optics_settings import normalize_optics
from shared_kits import Identity, SharedKitStore
from test_layout import layout_fixture, request


def mirror():
    return dict(elementType='mirror', inserted=True, configured=True,
                mirror=dict(mode='data', model='MEASURED-532', samples=[dict(
                    wavelengthNm=532, incidenceAngleDeg=45, reflectanceP=.96,
                    reflectanceS=.99, phaseDifferenceDeg=173.5)]))


class MirrorPersistenceTests(unittest.TestCase):
    def test_project_and_cart_preserve_bound_coefficients_and_quantities(self):
        catalog, payload = layout_fixture(), request()
        before = aggregate(catalog, payload)
        payload['layout']['instances'][0]['optics'] = mirror()
        result = aggregate(catalog, payload)
        for key in ('items', 'lubang', 'manufacturing', 'standard', 'totals', 'layoutValidation'):
            self.assertEqual(before[key], result[key])
        reopened = aggregate(catalog, json.loads(layout_json(result)))
        self.assertEqual(reopened['layout']['instances'][0]['optics'], mirror())
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'cart.sqlite3'
            identity = Identity('coating-test', 'coating-test', 'user')
            store = CartStore(SharedKitStore(db))
            initial = store.read(identity)
            store.add(identity, dict(cartId=initial['cartId'], revision=initial['revision'],
                      requestId='coating-copy', name='镜面系数工程', payload=payload), catalog)
            payload['layout']['instances'][0]['optics']['mirror']['samples'][0]['reflectanceP'] = .5
            saved = CartStore(SharedKitStore(db)).read(identity)['preview']['cartSources'][0]
            self.assertEqual(saved['layout']['instances'][0]['optics'], mirror())

    def test_incomplete_phase_is_preserved_as_unknown_not_zero(self):
        value = mirror()
        value['mirror']['samples'][0]['phaseDifferenceDeg'] = None
        normalized = normalize_optics(value)
        self.assertIsNone(normalized['mirror']['samples'][0]['phaseDifferenceDeg'])
        normalized['mirror']['samples'][0]['reflectanceP'] = .1
        self.assertEqual(value['mirror']['samples'][0]['reflectanceP'], .96)
        self.assertEqual(normalize_optics(dict(elementType='mirror', inserted=True)),
                         dict(elementType='mirror', inserted=True))
        self.assertEqual(normalize_optics({**mirror(), 'mirror': dict(mode='ideal', samples=[])} )['mirror'],
                         dict(mode='ideal', samples=[]))

    def test_invalid_or_ambiguous_samples_fail_closed(self):
        invalid = [None, [], {}, dict(mode='data'), dict(mode='bad', samples=[]),
                   dict(mode='data', samples=[], model=15), dict(mode='data', samples=[], sourceUrl='https://fake'),
                   dict(mode='data', samples=[mirror()['mirror']['samples'][0]]*257),
                   dict(mode='data', samples=[mirror()['mirror']['samples'][0]]*2)]
        for key, values in {'wavelengthNm': [None, 0, 1e6+1], 'incidenceAngleDeg': [None, -1, 91],
                            'reflectanceP': [-.1, 1.1], 'reflectanceS': [-.1, 1.1],
                            'phaseDifferenceDeg': [-36001, 36001]}.items():
            for value in values + [True, '0.5', float('nan'), float('inf')]:
                item = copy.deepcopy(mirror()['mirror'])
                item['samples'][0][key] = value
                invalid.append(item)
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(APIError):
                normalize_optics({**mirror(), 'mirror': item})
