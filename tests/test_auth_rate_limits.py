from tests.auth_helpers import AuthFlowMixin
from tests.base import BaseTestCase


class AuthRateLimitTestCase(AuthFlowMixin, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.configure_channels()
        self.make_user(username='jane', phone='+254712345678')

    def test_login_is_limited_per_ip(self):
        statuses = [self.login('jane', 'WrongPass123', ip='10.9.0.1').status_code for _ in range(6)]
        self.assertEqual(statuses[:5], [401] * 5)
        self.assertEqual(statuses[5], 429)

    def test_login_is_limited_per_account_across_ips(self):
        # Every phone format counts against the same account bucket.
        formats = ['0712345678', '+254712345678', '254712345678', '712345678']
        statuses = [
            self.login(formats[i % 4], 'WrongPass123', ip=f'10.8.0.{i}').status_code
            for i in range(11)
        ]
        self.assertEqual(statuses[:10], [401] * 10)
        response = self.login('0712345678', 'WrongPass123', ip='10.8.1.1')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()['code'], 'RATE_LIMITED')
        self.assertIn('Retry-After', response.headers)

    def test_forgot_password_is_limited_per_phone(self):
        def forgot(ip):
            return self.client.post('/api/auth/password/forgot', json={
                'channel': 'whatsapp', 'phone_number': '0712345678',
            }, environ_base={'REMOTE_ADDR': ip}).status_code

        self.assertEqual([forgot(f'10.7.0.{i}') for i in range(3)], [202] * 3)
        self.assertEqual(forgot('10.7.1.1'), 429)

    def test_forgot_password_is_limited_per_ip(self):
        statuses = [
            self.client.post('/api/auth/password/forgot', json={
                'channel': 'whatsapp', 'phone_number': f'07120000{i:02d}',
            }, environ_base={'REMOTE_ADDR': '10.6.0.1'}).status_code
            for i in range(6)
        ]
        self.assertEqual(statuses, [202] * 5 + [429])

    def test_phone_verification_start_is_limited_per_user(self):
        headers = self.bearer('jane', 'OwnerPass123', ip='10.5.0.1')
        statuses = [
            self.client.post('/api/auth/phone/verification', json={}, headers=headers).status_code
            for _ in range(4)
        ]
        self.assertEqual(statuses, [201, 201, 201, 429])
