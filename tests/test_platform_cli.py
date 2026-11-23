"""Server-side recovery commands: flask platform reset-2fa / transfer-super-admin."""
import ast
from datetime import date
from unittest import mock

from app import db
from app.models.audit import AuditLog
from app.models.hr import Employee
from app.models.mfa import UserMfaCredential, UserMfaRecoveryCode
from app.models.tenant import Tenant
from app.models.user import Role, User
from app.services.platform_tenant import PlatformTenant
from tests.base import BaseTestCase

REASON = 'Lost phone; re-enrolling the authenticator.'


class PlatformCliTestCase(BaseTestCase):

    def _cli(self, *args, input=None):
        result = self.app.test_cli_runner().invoke(args=['platform', *args], input=input)
        db.session.expire_all()
        return result

    def _admin(self):
        return User.query.filter_by(role=Role.SUPER_ADMIN).one()

    # -- reset-2fa --------------------------------------------------------------------------
    def test_reset_2fa_dry_run_changes_nothing(self):
        self.platform_admin_session()
        result = self._cli('reset-2fa', '--reason', REASON, '--dry-run')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('Dry run: nothing was changed.', result.output)
        self.assertIn('delete 10 recovery code(s)', result.output)
        self.assertIsNotNone(db.session.get(UserMfaCredential, self._admin().id))

    def test_reset_2fa_clears_enrolment_ends_sessions_and_audits(self):
        headers, _, _ = self.platform_admin_session()
        admin = self._admin()
        version = admin.token_version
        result = self._cli('reset-2fa', '--reason', REASON, input='y\n')
        self.assertEqual(result.exit_code, 0, result.output)

        admin = self._admin()
        self.assertIsNone(db.session.get(UserMfaCredential, admin.id))
        self.assertEqual(UserMfaRecoveryCode.query.filter_by(user_id=admin.id).count(), 0)
        self.assertEqual(admin.token_version, version + 1)
        self.client.delete_cookie('access_token_cookie')
        self.assertEqual(self.client.get('/api/auth/me', headers=headers).status_code, 401)

        entry = AuditLog.query.filter_by(action='MFA_RESET').one()
        self.assertIsNone(entry.user_id)
        self.assertIn(REASON, entry.new_value)

    def test_reset_2fa_needs_a_reason_and_confirmation(self):
        self.platform_admin_session()
        self.assertNotEqual(self._cli('reset-2fa', '--reason', 'short').exit_code, 0)
        cancelled = self._cli('reset-2fa', '--reason', REASON, input='n\n')
        self.assertNotEqual(cancelled.exit_code, 0)
        self.assertIsNotNone(db.session.get(UserMfaCredential, self._admin().id))

    # -- transfer-super-admin ---------------------------------------------------------------
    def _farm_with_two_owners(self):
        farm = Tenant(name='Second farm', tenant_type='single')
        db.session.add(farm)
        db.session.commit()
        self.create_user(username='co_owner', password='password', role=Role.FARMER, tenant=farm)
        target = self.create_user(username='successor', password='password', role=Role.FARMER, tenant=farm)
        target.phone_number = '0712555000'
        db.session.commit()
        return farm, target

    def test_transfer_dry_run_and_wrong_confirmation_change_nothing(self):
        self.platform_admin_session()
        _, target = self._farm_with_two_owners()
        dry = self._cli('transfer-super-admin', '--to', '0712555000', '--reason', REASON, '--dry-run')
        self.assertEqual(dry.exit_code, 0, dry.output)
        self.assertIn('no farm record is changed', dry.output)
        wrong = self._cli('transfer-super-admin', '--to', '0712555000', '--reason', REASON, input='+254700000000\n')
        self.assertNotEqual(wrong.exit_code, 0)
        self.assertEqual(self._admin().username, 'platform_admin')
        self.assertEqual(db.session.get(User, target.id).role, Role.FARMER)

    def test_transfer_moves_the_role_atomically(self):
        headers, _, _ = self.platform_admin_session()
        old_admin = self._admin()
        farm, target = self._farm_with_two_owners()

        result = self._cli('transfer-super-admin', '--to', '0712555000', '--reason', REASON, input='+254712555000\n')
        self.assertEqual(result.exit_code, 0, result.output)

        platform = PlatformTenant.get()
        new_admin = self._admin()
        self.assertEqual(new_admin.id, target.id)
        self.assertEqual(new_admin.tenant_id, platform.id)
        former = db.session.get(User, old_admin.id)
        self.assertEqual((former.role, former.is_active, former.tenant_id), (Role.FARMER, False, platform.id))
        self.assertIsNone(db.session.get(UserMfaCredential, former.id))
        # The farm keeps its other owner; nothing else moved.
        self.assertEqual(User.query.filter_by(tenant_id=farm.id).count(), 1)
        self.client.delete_cookie('access_token_cookie')
        self.assertEqual(self.client.get('/api/auth/me', headers=headers).status_code, 401)
        entry = AuditLog.query.filter_by(action='SUPER_ADMIN_TRANSFERRED').one()
        self.assertEqual(ast.literal_eval(entry.old_value)["super_admin_user_id"], old_admin.id)

    def test_transfer_rolls_back_completely_on_failure(self):
        self.platform_admin_session()
        _, target = self._farm_with_two_owners()
        with mock.patch('app.services.platform_account_service.record_audit', side_effect=RuntimeError('boom')):
            result = self._cli('transfer-super-admin', '--to', '0712555000', '--reason', REASON, input='+254712555000\n')
        self.assertNotEqual(result.exit_code, 0)
        db.session.rollback()
        self.assertEqual(self._admin().username, 'platform_admin')
        self.assertEqual(db.session.get(User, target.id).role, Role.FARMER)

    def test_transfer_refusals(self):
        self.platform_admin_session()
        lone_farm = Tenant(name='Lone farm', tenant_type='single')
        db.session.add(lone_farm)
        db.session.commit()
        lone = self.create_user(username='lone_owner', password='password', role=Role.FARMER, tenant=lone_farm)
        lone.phone_number = '0712555001'
        staff = self.create_user(username='staffer', password='password', role=Role.FARM_HAND)
        staff.phone_number = '0712555002'
        db.session.add(Employee(
            tenant_id=self.tenant.id, full_name='Staffer', user_id=staff.id, phone_number='0712555002',
            hire_date=date(2026, 1, 1), base_salary=0,
        ))
        inactive = self.create_user(username='gone', password='password', role=Role.FARM_HAND)
        inactive.phone_number = '0712555003'
        inactive.is_active = False
        db.session.commit()

        for phone, expected in (
            ('0712555001', 'last owner'),
            ('0712555002', 'staff record'),
            ('0712555003', 'deactivated'),
            ('0712555999', 'No account'),
        ):
            result = self._cli('transfer-super-admin', '--to', phone, '--reason', REASON, '--dry-run')
            self.assertNotEqual(result.exit_code, 0, phone)
            self.assertIn(expected, result.output, phone)
        self.assertEqual(self._admin().username, 'platform_admin')
