from unittest import mock
from urllib.parse import parse_qs, urlparse

from app import db
from app.models.auth import SocialAccount
from app.models.user import User
from app.services.google_identity_provider import GoogleAuthError, GoogleIdentity
from tests.auth_helpers import AuthFlowMixin
from tests.base import BaseTestCase

PROVIDER = 'app.api.auth_google.GoogleIdentityProvider'


def _identity(email='jane@gmail.com', verified=True, sub='google-sub-1'):
    return GoogleIdentity(subject=sub, email=email, email_verified=verified, name='Jane Gmail')


class GoogleAuthTestCase(AuthFlowMixin, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.configure_channels()

    def _callback(self, identity=None, error=None):
        with mock.patch(f'{PROVIDER}.fetch_identity', side_effect=error, return_value=identity):
            response = self.client.get('/api/auth/google/callback')
        self.assertEqual(response.status_code, 302)
        location = urlparse(response.headers['Location'])
        self.assertEqual(f'{location.scheme}://{location.netloc}{location.path}',
                         'https://app.example.test/auth/google/complete')
        return response, {k: v[0] for k, v in parse_qs(location.query).items()}

    def test_start_redirects_to_google_when_configured(self):
        with mock.patch(f'{PROVIDER}.is_configured', return_value=True), \
                mock.patch(f'{PROVIDER}.authorization_redirect', return_value=('', 302, {'Location': 'https://accounts.google.com/o'})) as redirect:
            response = self.client.get('/api/auth/google/start?next=/dashboard')
        self.assertEqual(response.status_code, 302)
        redirect.assert_called_once()

    def test_start_rejects_open_redirect_targets(self):
        response = self.client.get('/api/auth/google/start?next=https://evil.example')
        query = parse_qs(urlparse(response.headers['Location']).query)
        self.assertEqual(query['error_code'], ['GOOGLE_UNAVAILABLE'])
        self.assertNotIn('next', query)

    def test_new_user_signup_then_needs_phone_verification(self):
        _, query = self._callback(_identity())
        self.assertEqual(query['result'], 'signup_required')

        pending = self.client.get('/api/auth/google/pending-signup')
        self.assertEqual(pending.status_code, 200)
        pending_body = pending.get_json()
        self.assertEqual(pending_body['email'], 'jane@gmail.com')

        signup = self.client.post('/api/auth/google/signup', json={
            'signup_token': pending_body['signup_token'], 'farm_name': 'Gmail Farm', 'phone_number': '0712345678',
        })
        self.assertEqual(signup.status_code, 201, signup.get_json())
        body = signup.get_json()
        self.assertEqual(body['auth_state'], 'PHONE_VERIFICATION_REQUIRED')
        self.assertTrue(body['account_flags']['email_verified'])
        self.assertFalse(body['account_flags']['has_password'])
        self.assertRegex(body['phone_verification']['message_text'], r'^VERIFY-\d{6}$')

        headers = {'Authorization': f"Bearer {body['access_token']}"}
        gated = self.client.get('/api/hr/staff', headers=headers)
        self.assertEqual((gated.status_code, gated.get_json()['code']), (403, 'PHONE_VERIFICATION_REQUIRED'))
        self.assertEqual(self.client.get('/api/auth/me', headers=headers).get_json()['auth_state'],
                         'PHONE_VERIFICATION_REQUIRED')

        with mock.patch('app.services.whatsapp_message_service.send_message'):
            self.post_whatsapp('254712345678', body['phone_verification']['message_text'])
        # Same session, no re-login needed.
        staff = self.client.get("/api/hr/staff", headers=headers)
        self.assertEqual(staff.status_code, 200, staff.get_json())
        self.assertEqual(self.client.get('/api/auth/me', headers=headers).get_json()['auth_state'], 'ACTIVE')

    def test_signup_ticket_is_required(self):
        response = self.client.post('/api/auth/google/signup', json={
            'signup_token': 'forged', 'farm_name': 'X', 'phone_number': '0712345678',
        })
        self.assertEqual((response.status_code, response.get_json()['code']), (401, 'SIGNUP_SESSION_EXPIRED'))
        self.assertEqual(self.client.get('/api/auth/google/pending-signup').status_code, 404)

    def test_auto_links_only_when_local_email_is_verified(self):
        user = self.make_user(username='jane', email='jane@gmail.com', email_verified=True,
                              phone='+254712345678', phone_verified=True)
        response, query = self._callback(_identity())
        self.assertEqual(query['result'], 'signed_in')
        self.assertIn('access_token_cookie', response.headers.get('Set-Cookie', ''))
        self.assertEqual(SocialAccount.query.one().user_id, user.id)

    def test_unverified_local_email_requires_manual_link(self):
        self.make_user(username='jane', email='jane@gmail.com', email_verified=False)
        response, query = self._callback(_identity())
        self.assertEqual(query['result'], 'link_required')
        self.assertNotIn('access_token_cookie', response.headers.get('Set-Cookie', ''))
        self.assertEqual(SocialAccount.query.count(), 0)

    def test_linked_account_without_verified_phone_is_gated(self):
        user = self.make_user(username='jane', email='jane@gmail.com', email_verified=True)
        db.session.add(SocialAccount(user_id=user.id, provider='google', provider_user_id='google-sub-1'))
        db.session.commit()
        _, query = self._callback(_identity())
        self.assertEqual(query['result'], 'phone_verification_required')

    def test_google_unverified_email_and_errors(self):
        _, query = self._callback(_identity(verified=False))
        self.assertEqual((query['result'], query['error_code']), ('error', 'GOOGLE_EMAIL_UNVERIFIED'))
        _, query = self._callback(error=GoogleAuthError('GOOGLE_STATE_MISMATCH'))
        self.assertEqual(query['error_code'], 'GOOGLE_STATE_MISMATCH')

    def test_disabled_account_cannot_sign_in(self):
        user = self.make_user(username='jane', email='jane@gmail.com', email_verified=True, is_active=False)
        db.session.add(SocialAccount(user_id=user.id, provider='google', provider_user_id='google-sub-1'))
        db.session.commit()
        _, query = self._callback(_identity())
        self.assertEqual(query['error_code'], 'ACCOUNT_DISABLED')

    def test_unlink_requires_a_password(self):
        user = self.make_user(username='jane', password='OwnerPass123')
        db.session.add(SocialAccount(user_id=user.id, provider='google', provider_user_id='google-sub-1'))
        db.session.commit()
        headers = self.bearer('jane', 'OwnerPass123')

        user = db.session.get(User, user.id)
        user.has_password = False
        db.session.commit()
        self.assertEqual(self.client.delete('/api/auth/social/google', headers=headers).get_json()['code'], 'LAST_LOGIN_METHOD')

        user.has_password = True
        db.session.commit()
        response = self.client.delete('/api/auth/social/google', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['account_flags']['linked_providers'], [])
