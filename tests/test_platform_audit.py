"""Audit entries for this phase carry the actor, the IP address (for HTTP actions) and a timestamp."""
from app.models.audit import AuditLog
from app.models.user import Role, User
from app.services.totp_service import TotpService
from tests.base import BaseTestCase

COOPERATIVE = {
    'name': 'Audit Cooperative', 'region': 'Central', 'registration_number': 'REG-AUDIT-1',
    'admin_name': 'Co-op Manager', 'admin_username': 'coop_audit', 'admin_phone_number': '0712000077',
    'admin_password': 'StrongPass123',
}
IP = '203.0.113.7'


class PlatformAuditTestCase(BaseTestCase):

    def _entry(self, action):
        entry = AuditLog.query.filter_by(action=action).order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(entry, action)
        self.assertIsNotNone(entry.timestamp, action)
        return entry

    def test_http_actions_record_actor_ip_and_time(self):
        admin = self.create_platform_admin()
        environ = {'REMOTE_ADDR': IP}
        login = self.client.post('/api/auth/login', json={'username': 'platform_admin', 'password': 'password'},
                                 environ_base=environ)
        pending = {'Authorization': f"Bearer {login.get_json()['access_token']}"}
        secret = self.client.post('/api/auth/mfa/enrollment', headers=pending, environ_base=environ).get_json()['secret']
        self.client.post('/api/auth/mfa/enrollment/confirm', json={'code': '000000'}, headers=pending, environ_base=environ)
        confirmed = self.client.post(
            '/api/auth/mfa/enrollment/confirm', json={'code': TotpService.code_at(secret, TotpService.current_step())},
            headers=pending, environ_base=environ,
        ).get_json()
        verified = {'Authorization': f"Bearer {confirmed['access_token']}"}
        self.client.post('/api/auth/mfa/verify', json={'recovery_code': confirmed['recovery_codes'][0]},
                         headers=verified, environ_base=environ)
        created = self.client.post('/api/tenant/cooperatives', json=COOPERATIVE, headers=verified, environ_base=environ)
        self.assertEqual(created.status_code, 201)

        for action in ('MFA_FAILED', 'MFA_ENROLLED', 'MFA_RECOVERY_CODE_USED', 'COOPERATIVE_CREATED'):
            entry = self._entry(action)
            self.assertEqual(entry.user_id, admin.id, action)
            self.assertEqual(entry.ip_address, IP, action)
        coop = self._entry('COOPERATIVE_CREATED')
        self.assertEqual(coop.entity_type, 'Tenant')
        self.assertIn('Audit Cooperative', coop.new_value)

    def test_cli_actions_record_the_server_actor_and_reason(self):
        self.platform_admin_session()
        reason = 'Authenticator lost during farm visit.'
        result = self.app.test_cli_runner().invoke(args=['platform', 'reset-2fa', '--reason', reason], input='y\n')
        self.assertEqual(result.exit_code, 0, result.output)
        entry = self._entry('MFA_RESET')
        self.assertIsNone(entry.user_id)
        self.assertIn(reason, entry.new_value)
        self.assertIn('os_user', entry.new_value)
        self.assertEqual(entry.entity_id, User.query.filter_by(role=Role.SUPER_ADMIN).one().id)
