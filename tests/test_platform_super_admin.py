"""Exactly one super admin, housed in the platform tenant, changed only through PlatformAccountService."""
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.farm import Farm
from app.models.tenant import Tenant
from app.models.user import Role, User
from app.services.platform_account_service import NewSuperAdmin, PlatformAccountService, SuperAdminExists
from app.services.platform_tenant import PlatformTenant
from app.utils.super_admin_guard import SuperAdminChangeRefused, super_admin_changes_allowed
from tests.base import BaseTestCase


def _details(username='second_admin'):
    return NewSuperAdmin(username=username, identifier=f'{username}_id', name=username, password='StrongPass123')


class SingleSuperAdminTestCase(BaseTestCase):

    def test_created_in_the_platform_tenant_without_a_farm(self):
        admin = self.create_platform_admin()
        self.assertTrue(admin.tenant.is_platform)
        self.assertEqual(Farm.query.filter_by(tenant_id=admin.tenant_id).count(), 0)
        self.assertTrue(PlatformAccountService.is_platform_super_admin(admin))

    def test_service_refuses_a_second_super_admin(self):
        self.create_platform_admin()
        with self.assertRaises(SuperAdminExists):
            PlatformAccountService.create_super_admin(_details())

    def test_database_index_refuses_a_second_super_admin(self):
        self.create_platform_admin()
        platform = PlatformTenant.get()
        with super_admin_changes_allowed():
            db.session.add(User(
                tenant_id=platform.id, identifier='x_id', username='x', role=Role.SUPER_ADMIN,
                password_hash='unused',
            ))
            with self.assertRaises(IntegrityError) as error:
                db.session.flush()
        self.assertIn('uq_users_single_super_admin', str(error.exception.orig))
        db.session.rollback()

    def test_super_admin_outside_the_platform_tenant_is_refused(self):
        with super_admin_changes_allowed():
            db.session.add(User(
                tenant_id=self.tenant.id, identifier='y_id', username='y', role=Role.SUPER_ADMIN,
                password_hash='unused',
            ))
            with self.assertRaises(SuperAdminChangeRefused):
                db.session.flush()
        db.session.rollback()

    def test_super_admin_cannot_be_created_outside_the_permitted_scope(self):
        platform = PlatformTenant.get_or_create()
        db.session.add(User(
            tenant_id=platform.id, identifier='z_id', username='z', role=Role.SUPER_ADMIN, password_hash='unused',
        ))
        with self.assertRaises(SuperAdminChangeRefused):
            db.session.flush()
        db.session.rollback()

    def test_farm_user_cannot_be_promoted(self):
        farmer = self.create_user(username='owner', password='password', role=Role.FARMER)
        farmer.role = Role.SUPER_ADMIN
        with self.assertRaises(SuperAdminChangeRefused):
            db.session.commit()
        db.session.rollback()

    def test_super_admin_cannot_be_demoted_deactivated_or_moved_outside_the_scope(self):
        admin = self.create_platform_admin()
        for change in (
            lambda user: setattr(user, 'role', Role.FARMER),
            lambda user: setattr(user, 'is_active', False),
            lambda user: setattr(user, 'tenant_id', self.tenant.id),
        ):
            admin = db.session.get(User, admin.id)
            change(admin)
            with self.assertRaises(SuperAdminChangeRefused):
                db.session.commit()
            db.session.rollback()

    def test_password_and_profile_changes_are_not_blocked(self):
        admin = self.create_platform_admin()
        admin.set_password('AnotherStrongPass456')
        admin.name = 'Platform Owner'
        db.session.commit()
        self.assertTrue(db.session.get(User, admin.id).check_password('AnotherStrongPass456'))

    def test_only_the_super_admin_may_be_active_in_the_platform_tenant(self):
        platform = PlatformTenant.get_or_create()
        db.session.add(User(
            tenant_id=platform.id, identifier='f_id', username='f', role=Role.FARMER, password_hash='unused',
        ))
        with self.assertRaises(SuperAdminChangeRefused):
            db.session.flush()
        db.session.rollback()

    def test_a_deactivated_former_super_admin_may_stay_in_the_platform_tenant(self):
        admin = self.create_platform_admin()
        with super_admin_changes_allowed():
            admin.role = Role.FARMER
            admin.is_active = False
            db.session.commit()
        self.assertTrue(db.session.get(User, admin.id).tenant.is_platform)

    def test_legacy_super_admin_in_a_farm_tenant_can_still_change_password(self):
        # A super admin created before the platform tenant existed lives in a farm tenant.
        user = self.create_user(username='legacy_admin', password='password', role=Role.FARMER)
        db.session.execute(text("UPDATE users SET role = 'SUPER_ADMIN' WHERE id = :id"), {'id': user.id})
        db.session.commit()
        db.session.expire_all()
        legacy = db.session.get(User, user.id)
        legacy.set_password('NewStrongPass789')
        db.session.commit()
        self.assertFalse(PlatformAccountService.is_platform_super_admin(legacy))

    def test_one_platform_tenant_which_is_never_the_demo(self):
        first = PlatformTenant.get_or_create()
        db.session.commit()
        self.assertEqual(PlatformTenant.get_or_create().id, first.id)
        db.session.add(Tenant(name='Another', tenant_type='single', is_platform=True))
        with self.assertRaises(IntegrityError):
            db.session.flush()
        db.session.rollback()
        first = PlatformTenant.get()
        first.is_demo = True
        with self.assertRaises(IntegrityError):
            db.session.flush()
        db.session.rollback()


class NoEndpointAssignsSuperAdminTestCase(BaseTestCase):

    def _owner_headers(self):
        return self.get_auth_headers(Role.FARMER)

    def test_member_invite_refuses_super_admin_role(self):
        response = self.client.post(
            '/api/tenant/members/invite',
            json={'full_name': 'Sneaky', 'phone_number': '0712000009', 'role': Role.SUPER_ADMIN},
            headers=self._owner_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.query.filter_by(role=Role.SUPER_ADMIN).count(), 0)

    def test_onboarding_provision_refuses_super_admin_role(self):
        response = self.client.post(
            '/api/onboarding/provision',
            json={'employee_id': 1, 'role': Role.SUPER_ADMIN, 'password': 'StrongPass123!x'},
            headers=self._owner_headers(),
        )
        self.assertIn(response.status_code, (400, 404))
        self.assertEqual(User.query.filter_by(role=Role.SUPER_ADMIN).count(), 0)

    def test_registration_cannot_create_a_super_admin_without_the_bootstrap_key(self):
        response = self.client.post('/api/auth/register', json={
            'farm_name': 'X', 'phone_number': '0712000010', 'password': 'StrongPass123', 'role': 'SUPER_ADMIN',
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.query.filter_by(role=Role.SUPER_ADMIN).count(), 0)

    def test_bootstrap_refused_once_a_super_admin_exists(self):
        self.create_platform_admin()
        self.app.config['BOOTSTRAP_SUPER_ADMIN_KEY'] = 'bootstrap-secret-2026'
        self.app.config['ALLOW_SUPER_ADMIN_BOOTSTRAP'] = True
        response = self.client.post('/api/auth/register', json={
            'phone_number': '0712000011', 'password': 'StrongPass123', 'role': 'SUPER_ADMIN',
            'bootstrap_key': 'bootstrap-secret-2026',
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.query.filter_by(role=Role.SUPER_ADMIN).count(), 1)

    def test_super_admin_login_creates_no_farm(self):
        admin = self.create_platform_admin()
        response = self.client.post('/api/auth/login', json={'username': 'platform_admin', 'password': 'password'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()['farm_id'])
        self.assertEqual(Farm.query.filter_by(tenant_id=admin.tenant_id).count(), 0)
