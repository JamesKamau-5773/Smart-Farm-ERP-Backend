from unittest import mock

from app import db
from app.models.user import Role, User
from tests.auth_helpers import AuthFlowMixin, CapturingEmailSender
from tests.base import BaseTestCase


class RegistrationTestCase(AuthFlowMixin, BaseTestCase):
    def _register(self, **overrides):
        body = {'farm_name': 'Green Farm', 'phone_number': '0712345678', 'password': 'Maziwa2026x', **overrides}
        return self.client.post('/api/auth/register', json=body)

    def test_registration_stores_e164_phone_and_unverified_flags(self):
        response = self._register()
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data['phone_number'], '+254712345678')
        self.assertEqual(data['auth_state'], 'ACTIVE')
        self.assertEqual(data['account_flags'], {
            'needs_phone': False, 'phone_verified': False, 'email_verified': False,
            'has_password': True, 'linked_providers': [],
        })
        user = User.query.filter_by(phone_number='+254712345678').one()
        self.assertEqual(user.identifier, 'phone_254712345678')
        self.assertEqual(user.username, '254712345678')

    def test_registration_with_optional_email_sends_verification(self):
        self.configure_channels()
        sender = CapturingEmailSender()
        with mock.patch('app.services.email_sender.get_email_sender', return_value=sender):
            response = self._register(email='Jane@Example.com')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.query.one().email, 'jane@example.com')
        self.assertEqual([m.to for m in sender.sent], ['jane@example.com'])
        self.assertIn('/verify-email?token=', sender.sent[0].text)

    def test_registration_requires_phone(self):
        response = self._register(phone_number='')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['code'], 'VALIDATION_ERROR')

    def test_registration_rejects_invalid_phone(self):
        response = self._register(phone_number='12345')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['code'], 'INVALID_PHONE')

    def test_registration_enforces_password_policy(self):
        response = self._register(password='password')
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertEqual(body['code'], 'WEAK_PASSWORD')
        self.assertIn('letter_and_digit', body['violations'])

    def test_registration_rejects_phone_in_any_format_already_used(self):
        self.assertEqual(self._register().status_code, 201)
        response = self._register(phone_number='+254 712 345 678', password='Different2026x')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['code'], 'PHONE_IN_USE')

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        self.make_user(username='existing', email='jane@example.com')
        response = self._register(email='JANE@example.com')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['code'], 'EMAIL_IN_USE')


class LoginTestCase(AuthFlowMixin, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user(username='jane', phone='+254712345678', email='jane@example.com')

    def test_login_by_phone_in_every_accepted_format(self):
        for index, login in enumerate(['0712345678', '712345678', '254712345678', '+254712345678']):
            response = self.login(login, 'OwnerPass123', ip=f'10.1.0.{index}')
            self.assertEqual(response.status_code, 200, login)
            self.assertEqual(response.get_json()['sub'], str(self.user.id))

    def test_login_by_email_is_case_insensitive(self):
        response = self.login('JANE@Example.com', 'OwnerPass123')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['phone_number'], '+254712345678')

    def test_login_by_username_and_legacy_fields(self):
        self.assertEqual(self.login('jane', 'OwnerPass123').status_code, 200)
        legacy = self.client.post('/api/auth/login', json={'phone_number': '0712345678', 'password': 'OwnerPass123'})
        self.assertEqual(legacy.status_code, 200)
        legacy_email = self.client.post('/api/auth/login', json={'email': 'jane@example.com', 'password': 'OwnerPass123'})
        self.assertEqual(legacy_email.status_code, 200)

    def test_login_with_legacy_phone_only_in_identifier(self):
        legacy = User(tenant_id=self.tenant.id, identifier='phone_254799000111', username='254799000111',
                      name='Legacy', role=Role.FARMER)
        legacy.set_password('LegacyPass123')
        db.session.add(legacy)
        db.session.commit()
        self.assertEqual(self.login('0799000111', 'LegacyPass123').status_code, 200)

    def test_phone_shaped_username_still_logs_in_when_another_account_holds_that_phone(self):
        # Legacy account whose username is a phone number now owned by another user.
        legacy = User(tenant_id=self.tenant.id, identifier='phone_254712345678', username='254712345678',
                      name='Legacy', role=Role.FARMER)
        legacy.set_password('LegacyPass123')
        db.session.add(legacy)
        db.session.commit()

        legacy_login = self.login('254712345678', 'LegacyPass123')
        self.assertEqual(legacy_login.status_code, 200)
        self.assertEqual(legacy_login.get_json()['sub'], str(legacy.id))
        phone_owner_login = self.login('254712345678', 'OwnerPass123', ip='10.0.0.2')
        self.assertEqual(phone_owner_login.get_json()['sub'], str(self.user.id))

    def test_failures_are_indistinguishable(self):
        wrong_password = self.login('0712345678', 'WrongPass123')
        unknown_user = self.login('0799999999', 'WrongPass123', ip='10.0.0.2')
        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(wrong_password.get_json(), unknown_user.get_json())
        self.assertEqual(wrong_password.get_json()['code'], 'INVALID_CREDENTIALS')

    def test_user_without_phone_can_login_and_is_flagged(self):
        self.make_user(username='nophone', password='NoPhone2026x')
        response = self.login('nophone', 'NoPhone2026x')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['account_flags']['needs_phone'])
        self.assertEqual(data['auth_state'], 'ACTIVE')

    def test_me_reports_live_account_state(self):
        headers = self.bearer('jane', 'OwnerPass123')
        self.user.phone_verified = True
        db.session.commit()
        data = self.client.get('/api/auth/me', headers=headers).get_json()
        self.assertTrue(data['account_flags']['phone_verified'])
        self.assertEqual(data['email'], 'jane@example.com')

    def test_profile_phone_change_resets_verification(self):
        self.user.phone_verified = True
        db.session.commit()
        headers = self.bearer('jane', 'OwnerPass123')
        response = self.client.patch('/api/auth/me', json={'phone_number': '0722000111'}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['phone_number'], '+254722000111')
        self.assertFalse(response.get_json()['account_flags']['phone_verified'])

    def test_profile_rejects_invalid_phone(self):
        headers = self.bearer('jane', 'OwnerPass123')
        response = self.client.patch('/api/auth/me', json={'phone_number': 'abc'}, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['code'], 'INVALID_PHONE')

    def test_bumping_token_version_revokes_existing_tokens(self):
        headers = self.bearer('jane', 'OwnerPass123')
        self.assertEqual(self.client.get('/api/auth/me', headers=headers).status_code, 200)
        self.user.token_version += 1
        db.session.commit()
        self.assertEqual(self.client.get('/api/auth/me', headers=headers).status_code, 401)
