"""Bootstrap of the first super admin over HTTP: closed by default, constant-time key check."""
from unittest import mock

from app.models.user import Role, User
from tests.base import BaseTestCase

KEY = 'bootstrap-secret-2026'


class SuperAdminBootstrapTestCase(BaseTestCase):

    def _register(self, key=KEY, phone='0712000020'):
        return self.client.post('/api/auth/register', json={
            'phone_number': phone, 'password': 'StrongPass123', 'role': 'SUPER_ADMIN',
            'name': 'Platform Owner', 'bootstrap_key': key,
        })

    def _open(self, allowed=True, key=KEY):
        self.app.config['ALLOW_SUPER_ADMIN_BOOTSTRAP'] = allowed
        self.app.config['BOOTSTRAP_SUPER_ADMIN_KEY'] = key

    def test_closed_by_default_even_with_the_right_key(self):
        self._open(allowed=False)
        response = self._register()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['code'], 'BOOTSTRAP_UNAVAILABLE')
        self.assertFalse(self.client.get('/api/auth/bootstrap-status').get_json()['bootstrap_available'])

    def test_closed_without_a_configured_key(self):
        self._open(key='')
        self.assertEqual(self._register(key='').status_code, 403)

    def test_wrong_key_is_refused(self):
        self._open()
        response = self._register(key='not-the-key')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['code'], 'INVALID_BOOTSTRAP_KEY')
        self.assertEqual(User.query.filter_by(role=Role.SUPER_ADMIN).count(), 0)

    def test_key_is_compared_in_constant_time(self):
        self._open()
        with mock.patch('app.services.auth_service.hmac.compare_digest', wraps=__import__('hmac').compare_digest) as compare:
            self._register(key='not-the-key')
        compare.assert_called_once()

    def test_open_bootstrap_creates_the_super_admin_in_the_platform_tenant(self):
        self._open()
        self.assertTrue(self.client.get('/api/auth/bootstrap-status').get_json()['bootstrap_available'])
        response = self._register()
        self.assertEqual(response.status_code, 201)
        admin = User.query.filter_by(role=Role.SUPER_ADMIN).one()
        self.assertTrue(admin.tenant.is_platform)
        # Anonymous visitor (this client now holds the new admin's pre-2FA session cookie).
        status = self.app.test_client().get('/api/auth/bootstrap-status')
        self.assertFalse(status.get_json()['bootstrap_available'])

    def test_second_bootstrap_is_refused(self):
        self._open()
        self.assertEqual(self._register().status_code, 201)
        second = self._register(phone='0712000021')
        self.assertEqual(second.status_code, 403)
        self.assertEqual(User.query.filter_by(role=Role.SUPER_ADMIN).count(), 1)
