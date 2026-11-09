"""Personal cart routes through the real login proxy, with isolated test storage."""
import json
import unittest

import test_guest_router as router_tests


class AccountCartRouterTests(unittest.TestCase):
    setUpClass = classmethod(router_tests.GuestRouterTests.setUpClass.__func__)
    tearDownClass = classmethod(router_tests.GuestRouterTests.tearDownClass.__func__)
    request = router_tests.GuestRouterTests.request

    def test_readonly_personal_cart_survives_canvas_changes_and_strips_forged_identity(self):
        base = '/optics-kits/api/cart'
        status, body, _ = self.request(base, 'readonly')
        self.assertEqual(status, 200, body)
        initial = json.loads(body)
        token = {key: initial[key] for key in ('cartId', 'revision')}
        addition = {**token, 'requestId': 'router-cart-add-001', 'name': '隔离测试波片方案',
                    'payload': {'items': [{'kitId': 'waveplate', 'quantity': 1}], 'extras': []}}
        status, body, _ = self.request(base + '/add', 'readonly', addition,
                                     {'X-ZZLAB-User-ID': '999', 'X-ZZLAB-Role': 'admin'})
        self.assertEqual(status, 200, body)
        added = json.loads(body)
        self.assertEqual(added['cartId'], initial['cartId'])
        self.assertTrue(added['items'])
        status, _, _ = self.request('/optics-kits/api/preview', 'readonly', {'items': [], 'extras': []})
        self.assertEqual(status, 200)
        persisted = json.loads(self.request(base, 'readonly')[1])
        self.assertEqual(persisted['items'], added['items'])
        self.assertEqual(persisted['revision'], added['revision'])
        status, body, _ = self.request(base + '/export?format=manufacturing', 'readonly',
                                      {key: added[key] for key in ('cartId', 'revision')})
        self.assertEqual(status, 200, body[:300])
        self.assertTrue(body.startswith(b'PK'))
        status, body, _ = self.request(base + '/clear', 'readonly',
                                      {key: added[key] for key in ('cartId', 'revision')})
        self.assertEqual(status, 200, body)
        self.assertFalse(json.loads(body)['items'])
        self.assertEqual(self.request('/optics-kits/api/shared-kits', 'readonly', {})[0], 403)
        for route in ('/api/cart/future-write', '/api/cart'):
            self.assertEqual(self.request('/optics-kits' + route, 'readonly', {})[0], 403)

    def test_guest_cannot_reach_account_cart_even_when_enabled(self):
        endpoint = '/optics-kits/api/admin/guest-access'
        initial = json.loads(self.request(endpoint, 'admin')[1])
        status, body, _ = self.request(endpoint, 'admin', {'guestAccessEnabled': True, 'revision': initial['revision']})
        self.assertEqual(status, 200, body)
        try:
            status, _, headers = self.request('/optics-kits/api/cart')
            self.assertEqual(status, 302)
            self.assertIn('/auth/login?', headers.get('Location', ''))
            for action in ('add', 'update', 'clear', 'export?format=bundle'):
                self.assertEqual(self.request('/optics-kits/api/cart/' + action, body={})[0], 401)
            self.assertEqual(self.request('/optics-kits/api/session')[0], 200)
            self.assertEqual(self.request('/optics-kits/api/export?format=lubang', body={
                'items': [{'kitId': 'waveplate', 'quantity': 1}], 'extras': []})[0], 200)
        finally:
            current = json.loads(self.request(endpoint, 'admin')[1])
            self.request(endpoint, 'admin', {'guestAccessEnabled': False, 'revision': current['revision']})


if __name__ == '__main__':
    unittest.main()
