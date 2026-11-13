from unittest import mock

from app import db
from app.models.auth import VerificationChallenge
from app.models.tenant import Tenant
from app.models.user import Role, User
from tests.auth_helpers import AuthFlowMixin, CapturingEmailSender, extract_token
from tests.base import BaseTestCase

GENERIC = "If an account exists, we've sent instructions."


class PasswordRecoveryTestCase(AuthFlowMixin, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.configure_channels()
        self.user = self.make_user(username='jane', phone='+254712345678', email='jane@example.com', email_verified=True)
        self.email_sender = CapturingEmailSender()
        patcher = mock.patch('app.services.email_sender.get_email_sender', return_value=self.email_sender)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _forgot(self, **body):
        return self.client.post('/api/auth/password/forgot', json=body)

    def _reset(self, token, password='BrandNew2026x', confirm=None):
        return self.client.post('/api/auth/password/reset', json={
            'token': token, 'password': password, 'confirm_password': confirm or password,
        })

    def test_options_list_platform_channels(self):
        channels = self.client.get('/api/auth/password/forgot/options').get_json()['channels']
        self.assertEqual({c['id']: c['enabled'] for c in channels}, {'whatsapp': True, 'email': True})

    def test_whatsapp_response_is_identical_for_unknown_numbers(self):
        known = self._forgot(channel='whatsapp', phone_number='0712345678')
        unknown = self._forgot(channel='whatsapp', phone_number='0799000999')
        self.assertEqual((known.status_code, unknown.status_code), (202, 202))
        known_body, unknown_body = known.get_json(), unknown.get_json()
        self.assertEqual(known_body.keys(), unknown_body.keys())
        self.assertEqual(known_body['message'], GENERIC)
        self.assertRegex(unknown_body['message_text'], r'^RESET-\d{6}$')
        self.assertEqual(VerificationChallenge.query.count(), 1)

    @mock.patch('app.services.whatsapp_message_service.send_message')
    def test_whatsapp_reset_end_to_end_revokes_sessions(self, send_message):
        old_session = self.bearer('jane', 'OwnerPass123')
        code = self._forgot(channel='whatsapp', phone_number='+254712345678').get_json()['message_text']

        self.post_whatsapp('254712345678', code)
        reply = send_message.call_args.args[1]['text']['body']
        self.assertIn('https://app.example.test/reset-password?token=', reply)
        token = extract_token(reply)

        self.assertTrue(self.client.post('/api/auth/password/reset/validate', json={'token': token}).get_json()['valid'])
        response = self._reset(token)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(self.client.get('/api/auth/me', headers=old_session).status_code, 401)
        self.assertEqual(self.login('jane', 'OwnerPass123', ip='10.0.0.2').status_code, 401)
        self.assertEqual(self.login('jane', 'BrandNew2026x', ip='10.0.0.3').status_code, 200)
        self.assertTrue(db.session.get(User, self.user.id).phone_verified)
        # Single use.
        self.assertEqual(self._reset(token).get_json()['code'], 'RESET_TOKEN_INVALID')

    @mock.patch('app.services.whatsapp_message_service.send_message')
    def test_reset_code_from_another_number_sends_no_link(self, send_message):
        code = self._forgot(channel='whatsapp', phone_number='0712345678').get_json()['message_text']
        self.post_whatsapp('254799999999', code)
        self.assertNotIn('token=', send_message.call_args.args[1]['text']['body'])

    def test_email_reset_end_to_end(self):
        response = self._forgot(channel='email', email='JANE@example.com')
        self.assertEqual((response.status_code, response.get_json()['message']), (202, GENERIC))
        [message] = self.email_sender.sent
        self.assertEqual(message.to, 'jane@example.com')
        self.assertEqual(self._reset(extract_token(message.text)).status_code, 200)

    def test_email_reset_is_silent_for_unverified_or_unknown_email(self):
        self.make_user(username='unverified', email='unverified@example.com')
        responses = [
            self._forgot(channel='email', email='unverified@example.com'),
            self._forgot(channel='email', email='nobody@example.com'),
        ]
        self.assertEqual({r.get_json()['message'] for r in responses}, {GENERIC})
        self.assertEqual(self.email_sender.sent, [])

    def test_reset_enforces_policy_and_locks_after_five_failures(self):
        self._forgot(channel='email', email='jane@example.com')
        token = extract_token(self.email_sender.sent[0].text)
        self.assertEqual(self._reset(token, 'weak').get_json()['code'], 'WEAK_PASSWORD')
        self.assertEqual(self._reset(token, 'BrandNew2026x', 'Mismatch2026x').get_json()['code'], 'PASSWORD_MISMATCH')
        for _ in range(3):
            self._reset(token, 'weak')
        self.assertEqual(self._reset(token).get_json()['code'], 'RESET_TOKEN_INVALID')

    def test_expired_reset_link_is_rejected(self):
        self._forgot(channel='email', email='jane@example.com')
        token = extract_token(self.email_sender.sent[0].text)
        challenge = VerificationChallenge.query.one()
        challenge.expires_at = challenge.expires_at.replace(year=2000)
        db.session.commit()
        response = self.client.post('/api/auth/password/reset/validate', json={'token': token})
        self.assertEqual((response.status_code, response.get_json()['code']), (400, 'RESET_TOKEN_INVALID'))

    def test_disabled_channel_is_reported(self):
        self.app.config['RESEND_API_KEY'] = None
        response = self._forgot(channel='email', email='jane@example.com')
        self.assertEqual(response.get_json()['code'], 'CHANNEL_DISABLED')


class AdminPasswordResetTestCase(AuthFlowMixin, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user(username='owner', password='OwnerPass123', role=Role.FARMER)
        self.farmhand = self.make_user(username='hand', password='HandPass123', role=Role.FARM_HAND, phone='+254722000333')

    def _issue(self, user_id, headers):
        return self.client.post(f'/api/tenant/users/{user_id}/password-reset', json={}, headers=headers)

    def test_owner_can_reset_staff_and_existing_sessions_end(self):
        hand_client = self.app.test_client()
        hand_session = self.bearer('hand', 'HandPass123', client=hand_client, ip='10.0.0.5')
        response = self._issue(self.farmhand.id, self.bearer('owner', 'OwnerPass123'))
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(body['user']['id'], self.farmhand.id)
        self.assertEqual(hand_client.get('/api/auth/me', headers=hand_session).status_code, 401)

        reset = self.client.post('/api/auth/password/reset', json={
            'token': extract_token(body['reset_url']), 'password': 'FreshStart2026', 'confirm_password': 'FreshStart2026',
        })
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(self.login('hand', 'FreshStart2026', ip='10.0.0.6').status_code, 200)

    def test_staff_cannot_reset_owner_or_peers(self):
        headers = self.bearer('hand', 'HandPass123')
        self.assertEqual(self._issue(self.owner.id, headers).get_json()['code'], 'FORBIDDEN')

    def test_farm_admin_cannot_reset_single_farm_owner(self):
        self.make_user(username='admin', password='AdminPass123', role=Role.FARM_ADMIN)
        response = self._issue(self.owner.id, self.bearer('admin', 'AdminPass123'))
        self.assertEqual((response.status_code, response.get_json()['code']), (403, 'FORBIDDEN_TARGET'))

    def test_cannot_reset_self_or_users_in_other_tenants(self):
        headers = self.bearer('owner', 'OwnerPass123')
        self.assertEqual(self._issue(self.owner.id, headers).get_json()['code'], 'FORBIDDEN_TARGET')

        other_tenant = Tenant(name='Other', tenant_type='single')
        db.session.add(other_tenant)
        db.session.commit()
        outsider = self.make_user(username='outsider', tenant=other_tenant, role=Role.FARM_HAND)
        self.assertEqual(self._issue(outsider.id, headers).status_code, 404)
