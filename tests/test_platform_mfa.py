"""Two-factor authentication (TOTP) for the super admin, and what its sessions may do."""
from datetime import datetime, timedelta, timezone

from flask_jwt_extended import decode_token

from app import db
from app.models.audit import AuditLog
from app.models.mfa import MfaSession, UserMfaCredential, UserMfaRecoveryCode
from app.models.user import Role
from app.services.mfa_service import MfaService
from app.services.totp_service import TotpService
from app.utils import secret_cipher
from tests.base import BaseTestCase


def _bearer(token):
    return {'Authorization': f'Bearer {token}'}


def _lifetime_minutes(token):
    claims = decode_token(token)
    return (claims['exp'] - claims['iat']) / 60


class PlatformMfaTestCase(BaseTestCase):

    def _login(self, username='platform_admin', password='password'):
        response = self.client.post('/api/auth/login', json={'username': username, 'password': password})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def _actions(self, action):
        return AuditLog.query.filter_by(action=action).count()

    # -- before 2FA -------------------------------------------------------------------------
    def test_password_login_gives_a_short_session_limited_to_2fa(self):
        self.create_platform_admin()
        body = self._login()
        self.assertTrue(body['is_platform_admin'])
        self.assertFalse(body['mfa_enrolled'])
        self.assertFalse(body['mfa_verified'])
        self.assertAlmostEqual(_lifetime_minutes(body['access_token']), 10, delta=0.1)
        headers = _bearer(body['access_token'])

        me = self.client.get('/api/auth/me', headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(
            {key: me.get_json()[key] for key in ('is_platform_admin', 'mfa_enrolled', 'mfa_verified')},
            {'is_platform_admin': True, 'mfa_enrolled': False, 'mfa_verified': False},
        )
        for method, path in (
            ('get', '/api/tenant/profile'),
            ('post', '/api/tenant/cooperatives'),
            ('post', '/api/auth/password'),
            ('get', '/api/finance/ledger'),
        ):
            response = getattr(self.client, method)(path, json={}, headers=headers)
            self.assertEqual(response.status_code, 403, path)
            self.assertEqual(response.get_json()['code'], 'MFA_REQUIRED', path)

    # -- enrolment --------------------------------------------------------------------------
    def test_enrolment_stores_the_secret_encrypted_and_returns_a_qr_uri(self):
        admin = self.create_platform_admin()
        headers = _bearer(self._login()['access_token'])
        response = self.client.post('/api/auth/mfa/enrollment', headers=headers)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['otpauth_uri'].startswith('otpauth://totp/'))
        self.assertIn('issuer=Maziwa%20Smart', body['otpauth_uri'])
        stored = db.session.get(UserMfaCredential, admin.id)
        self.assertNotIn(body['secret'], stored.secret_ciphertext)
        self.assertEqual(secret_cipher.decrypt(stored.secret_ciphertext), body['secret'])
        self.assertIsNone(stored.confirmed_at)

    def test_wrong_confirmation_code_is_refused_and_audited(self):
        self.create_platform_admin()
        headers = _bearer(self._login()['access_token'])
        self.client.post('/api/auth/mfa/enrollment', headers=headers)
        response = self.client.post('/api/auth/mfa/enrollment/confirm', json={'code': '000000'}, headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()['code'], 'MFA_INVALID_CODE')
        self.assertEqual(self._actions('MFA_FAILED'), 1)
        failure = AuditLog.query.filter_by(action='MFA_FAILED').one()
        self.assertNotIn('000000', failure.new_value or '')

    def test_confirmed_enrolment_returns_recovery_codes_once_and_a_verified_session(self):
        admin = self.create_platform_admin()
        pending_token = self._login()['access_token']
        headers, _, codes = self.platform_admin_session_from(pending_token)

        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)
        stored = [row.code_hash for row in UserMfaRecoveryCode.query.filter_by(user_id=admin.id)]
        self.assertEqual(len(stored), 10)
        self.assertFalse(set(codes) & set(stored))  # Only hashes are kept.
        self.assertEqual(self._actions('MFA_ENROLLED'), 1)

        me = self.client.get('/api/auth/me', headers=headers).get_json()
        self.assertTrue(me['mfa_enrolled'])
        self.assertTrue(me['mfa_verified'])
        self.assertAlmostEqual(_lifetime_minutes(headers['Authorization'][7:]), 30, delta=0.1)
        # The pre-2FA token is revoked (a fresh client, so no session cookie stands in for it).
        self.assertEqual(self.app.test_client().get('/api/auth/me', headers=_bearer(pending_token)).status_code, 401)
        # Enrolment cannot be restarted from the API.
        again = self.client.post('/api/auth/mfa/enrollment', headers=headers)
        self.assertEqual(again.status_code, 409)

    def platform_admin_session_from(self, pending_token):
        headers = _bearer(pending_token)
        secret = self.client.post('/api/auth/mfa/enrollment', headers=headers).get_json()['secret']
        code = TotpService.code_at(secret, TotpService.current_step())
        body = self.client.post('/api/auth/mfa/enrollment/confirm', json={'code': code}, headers=headers).get_json()
        return _bearer(body['access_token']), secret, body['recovery_codes']

    # -- verification -----------------------------------------------------------------------
    def test_totp_verification_and_no_replay(self):
        _, secret, _ = self.platform_admin_session()
        # Enrolment used the current step; the next one is still inside the accepted window.
        code = TotpService.code_at(secret, TotpService.current_step() + 1)

        pending = _bearer(self._login()['access_token'])
        self.assertFalse(self.client.get('/api/auth/me', headers=pending).get_json()['mfa_verified'])
        verified = self.client.post('/api/auth/mfa/verify', json={'code': code}, headers=pending)
        self.assertEqual(verified.status_code, 200)
        self.assertTrue(verified.get_json()['mfa_verified'])

        replay = self.client.post('/api/auth/mfa/verify', json={'code': code}, headers=_bearer(self._login()['access_token']))
        self.assertEqual(replay.status_code, 401)

    def test_recovery_code_works_once(self):
        _, _, codes = self.platform_admin_session()
        first = self.client.post(
            '/api/auth/mfa/verify', json={'recovery_code': codes[0].upper()},
            headers=_bearer(self._login()['access_token']),
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self._actions('MFA_RECOVERY_CODE_USED'), 1)
        again = self.client.post(
            '/api/auth/mfa/verify', json={'recovery_code': codes[0]},
            headers=_bearer(self._login()['access_token']),
        )
        self.assertEqual(again.status_code, 401)

    def test_code_attempts_are_rate_limited(self):
        self.platform_admin_session()
        headers = _bearer(self._login()['access_token'])
        statuses = [
            self.client.post('/api/auth/mfa/verify', json={'code': '000000'}, headers=headers).status_code
            for _ in range(6)
        ]
        self.assertEqual(statuses[:5], [401] * 5)
        self.assertEqual(statuses[5], 429)

    def test_verified_session_ends_when_it_expires(self):
        headers, _, _ = self.platform_admin_session()
        jti = decode_token(headers['Authorization'][7:])['jti']
        session = db.session.get(MfaSession, jti)
        admin = session.user_id
        from app.models.user import User
        user = db.session.get(User, admin)
        self.assertTrue(MfaService.session_verified(user, jti))
        later = datetime.now(timezone.utc) + timedelta(minutes=31)
        self.assertFalse(MfaService.session_verified(user, jti, now=later))

    # -- after 2FA --------------------------------------------------------------------------
    def test_verified_session_may_use_platform_routes_but_not_farm_routes(self):
        headers, _, _ = self.platform_admin_session()
        self.assertEqual(self.client.get('/api/tenant/profile', headers=headers).status_code, 200)
        farm = self.client.get('/api/finance/ledger', headers=headers)
        self.assertEqual(farm.status_code, 403)
        self.assertEqual(farm.get_json()['code'], 'PLATFORM_SCOPE')

    def test_logout_revokes_the_verified_session(self):
        headers, _, _ = self.platform_admin_session()
        self.assertEqual(self.client.post('/api/auth/logout', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me', headers=headers).status_code, 401)

    # -- configuration and farm users -------------------------------------------------------
    def test_enrolment_needs_an_encryption_key(self):
        self.create_platform_admin()
        self.app.config['MFA_ENCRYPTION_KEYS'] = ''
        headers = _bearer(self._login()['access_token'])
        response = self.client.post('/api/auth/mfa/enrollment', headers=headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['code'], 'MFA_NOT_CONFIGURED')

    def test_farm_users_are_unaffected(self):
        headers = self.get_auth_headers(Role.FARMER)
        me = self.client.get('/api/auth/me', headers=headers).get_json()
        self.assertEqual(
            {key: me[key] for key in ('is_platform_admin', 'mfa_enrolled', 'mfa_verified')},
            {'is_platform_admin': False, 'mfa_enrolled': False, 'mfa_verified': False},
        )
        self.assertAlmostEqual(_lifetime_minutes(headers['Authorization'][7:]), 120, delta=0.1)
        refused = self.client.post('/api/auth/mfa/enrollment', headers=headers)
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.get_json()['code'], 'MFA_NOT_AVAILABLE')


class TotpServiceTestCase(BaseTestCase):

    def test_accepts_one_step_of_drift_and_refuses_used_steps(self):
        secret = TotpService.new_secret()
        now = datetime(2026, 11, 23, 12, 0, 10, tzinfo=timezone.utc)
        step = TotpService.current_step(now)
        for offset in (-1, 0, 1):
            self.assertEqual(TotpService.matching_step(secret, TotpService.code_at(secret, step + offset), now=now), step + offset)
        self.assertIsNone(TotpService.matching_step(secret, TotpService.code_at(secret, step + 2), now=now))
        self.assertIsNone(TotpService.matching_step(secret, TotpService.code_at(secret, step), last_used_step=step, now=now))
        self.assertIsNone(TotpService.matching_step(secret, 'abc', now=now))
