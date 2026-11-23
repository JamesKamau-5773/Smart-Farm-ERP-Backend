"""Moving a super admin created before the platform tenant existed: move-super-admin / split-super-admin.

Both change only the super admin account, its sessions and audit entries. Farm records are never
modified, moved or deleted.
"""
from datetime import date

from sqlalchemy import text

from app import db
from app.models.audit import AuditLog
from app.models.farm import Farm
from app.models.livestock import Cow
from app.models.tenant import Tenant
from app.models.user import Role, User
from app.services.platform_account_service import PlatformAccountService
from app.services.platform_tenant import PlatformTenant
from tests.base import BaseTestCase

REASON = 'Move the super admin out of its farm workspace.'
NEW_PASSWORD = 'Platform-Owner-2026!'


class LegacySuperAdminTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        PlatformTenant.get_or_create()
        db.session.commit()

    def _legacy_admin(self, tenant=None):
        """A super admin in a farm tenant, as bootstrapped before this phase (bypasses the guard, like old data)."""
        user = self.create_user(username='legacy_admin', password='password', role=Role.FARMER, tenant=tenant)
        db.session.execute(text("UPDATE users SET role = 'SUPER_ADMIN' WHERE id = :id"), {'id': user.id})
        db.session.commit()
        db.session.expire_all()
        return db.session.get(User, user.id)

    def _cli(self, *args, input=None):
        result = self.app.test_cli_runner().invoke(args=['platform', *args], input=input)
        db.session.expire_all()
        return result

    def _snapshot(self, tenant_id):
        return {
            'contents': PlatformAccountService.tenant_contents(tenant_id),
            'farms': [(farm.id, farm.name, farm.is_active) for farm in Farm.query.filter_by(tenant_id=tenant_id)],
            'cows': [(cow.id, cow.tag_number, cow.tenant_id) for cow in Cow.query.filter_by(tenant_id=tenant_id)],
        }

    def _add_cow(self, tenant_id):
        db.session.add(Cow(tenant_id=tenant_id, tag_number='KE-001', name='Daisy', date_of_birth=date(2022, 1, 1)))
        db.session.commit()

    # -- status -----------------------------------------------------------------------------
    def test_status_is_read_only(self):
        admin = self._legacy_admin()
        before = self._snapshot(admin.tenant_id)
        result = self._cli('status')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('in platform tenant=False', result.output)
        self.assertEqual(self._snapshot(admin.tenant_id), before)

    # -- move -------------------------------------------------------------------------------
    def test_move_dry_run_changes_nothing(self):
        admin = self._legacy_admin()
        result = self._cli('move-super-admin', '--reason', REASON, '--dry-run')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('Dry run: nothing was changed.', result.output)
        self.assertEqual(db.session.get(User, admin.id).tenant_id, self.tenant.id)

    def test_move_changes_only_the_account(self):
        admin = self._legacy_admin()
        version = admin.token_version
        before = self._snapshot(self.tenant.id)

        result = self._cli('move-super-admin', '--reason', REASON, input='y\n')
        self.assertEqual(result.exit_code, 0, result.output)

        moved = db.session.get(User, admin.id)
        self.assertEqual(moved.tenant_id, PlatformTenant.get().id)
        self.assertEqual(moved.token_version, version + 1)
        self.assertTrue(PlatformAccountService.is_platform_super_admin(moved))
        # The old tenant keeps its farm shell untouched; only the account left it.
        after = self._snapshot(self.tenant.id)
        self.assertEqual(after['farms'], before['farms'])
        self.assertEqual(after['cows'], before['cows'])
        self.assertEqual(db.session.get(Tenant, self.tenant.id).name, 'Default Tenant')
        self.assertEqual(AuditLog.query.filter_by(action='SUPER_ADMIN_MOVED').count(), 1)

    def test_move_refuses_a_tenant_with_farm_data_and_changes_nothing(self):
        admin = self._legacy_admin()
        self._add_cow(self.tenant.id)
        self.create_user(username='farm_hand', password='password', role=Role.FARM_HAND)
        before = self._snapshot(self.tenant.id)

        result = self._cli('move-super-admin', '--reason', REASON, input='y\n')
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('cows: 1', result.output)
        self.assertIn('users: 1', result.output)
        self.assertIn('split-super-admin', result.output)
        self.assertEqual(db.session.get(User, admin.id).tenant_id, self.tenant.id)
        self.assertEqual(self._snapshot(self.tenant.id), before)
        self.assertEqual(AuditLog.query.count(), 0)

    # -- split ------------------------------------------------------------------------------
    def test_split_dry_run_changes_nothing(self):
        admin = self._legacy_admin()
        self._add_cow(self.tenant.id)
        result = self._cli('split-super-admin', '--reason', REASON, '--username', 'platform_owner', '--dry-run')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('cows: 1', result.output)
        self.assertEqual(db.session.get(User, admin.id).role, Role.SUPER_ADMIN)
        self.assertIsNone(User.query.filter_by(username='platform_owner').first())

    def test_split_keeps_the_farm_with_the_old_account(self):
        admin = self._legacy_admin()
        self._add_cow(self.tenant.id)
        before = self._snapshot(self.tenant.id)

        result = self._cli(
            'split-super-admin', '--reason', REASON, '--username', 'platform_owner', '--name', 'Platform Owner',
            input=f'{NEW_PASSWORD}\n{NEW_PASSWORD}\nplatform_owner\n',
        )
        self.assertEqual(result.exit_code, 0, result.output)

        former = db.session.get(User, admin.id)
        self.assertEqual((former.role, former.tenant_id, former.is_active), (Role.FARMER, self.tenant.id, True))
        self.assertEqual(self._snapshot(self.tenant.id), before)

        new_admin = User.query.filter_by(role=Role.SUPER_ADMIN).one()
        self.assertEqual(new_admin.username, 'platform_owner')
        self.assertTrue(PlatformAccountService.is_platform_super_admin(new_admin))
        self.assertEqual(AuditLog.query.filter_by(action='SUPER_ADMIN_SPLIT').count(), 1)

        # The old account now works as the farm owner; the new one must complete 2FA.
        farmer = self.client.post('/api/auth/login', json={'username': 'legacy_admin', 'password': 'password'})
        self.assertFalse(farmer.get_json()['is_platform_admin'])
        self.assertEqual(farmer.get_json()['farm_id'], f'farm_{self.farm.id}')
        platform = self.client.post('/api/auth/login', json={'username': 'platform_owner', 'password': NEW_PASSWORD})
        self.assertTrue(platform.get_json()['is_platform_admin'])
        self.assertFalse(platform.get_json()['mfa_verified'])

    def test_split_refusals_change_nothing(self):
        admin = self._legacy_admin()
        self.create_user(username='taken', password='password', role=Role.FARM_HAND)
        taken = self._cli('split-super-admin', '--reason', REASON, '--username', 'taken')
        self.assertNotEqual(taken.exit_code, 0)
        self.assertIn('already taken', taken.output)
        weak = self._cli(
            'split-super-admin', '--reason', REASON, '--username', 'platform_owner',
            input='short\nshort\n',
        )
        self.assertNotEqual(weak.exit_code, 0)
        self.assertIn('password policy', weak.output)
        self.assertEqual(db.session.get(User, admin.id).role, Role.SUPER_ADMIN)

    def test_commands_refuse_once_the_admin_is_on_the_platform(self):
        self.create_platform_admin()
        for command in (('move-super-admin',), ('split-super-admin', '--username', 'other')):
            result = self._cli(*command, '--reason', REASON, '--dry-run')
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn('already in the platform tenant', result.output)

    def test_demo_tenant_is_never_involved(self):
        demo = Tenant(name='Silato Farm', tenant_type='single', is_demo=True)
        db.session.add(demo)
        db.session.commit()
        self._add_cow(demo.id)
        before = self._snapshot(demo.id)
        self._legacy_admin()
        self._cli('move-super-admin', '--reason', REASON, input='y\n')
        self.assertEqual(self._snapshot(demo.id), before)
        self.assertFalse(PlatformTenant.get().is_demo)

    def test_cows_saved_without_a_tenant_never_land_in_the_platform_tenant(self):
        from app.models import livestock

        # Leave the platform tenant as the only tenant, which the old fallback would have picked.
        db.session.delete(self.farm)
        db.session.delete(db.session.get(Tenant, self.tenant.id))
        db.session.commit()
        self.assertEqual(Tenant.query.count(), 1)
        with self.app.test_request_context():
            self.assertIsNone(livestock._resolve_default_tenant_id())
