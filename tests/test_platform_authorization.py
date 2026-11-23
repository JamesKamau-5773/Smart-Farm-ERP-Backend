"""Platform-admin authorization and the role_required fix.

* role_required reads the role live from the database.
* FARMER, FARM_ADMIN and ADMIN (cooperative admin) keep full access to farm routes.
* SUPER_ADMIN satisfies no role_required check; platform routes use platform_admin_required.
"""
import io

from flask import Blueprint, jsonify

from app import db
from app.models.tenant import Tenant
from app.models.user import Role, User
from app.services.platform_tenant import PlatformTenant
from app.utils.decorators import platform_admin_required, role_required
from tests.base import BaseTestCase

probe_bp = Blueprint('role_probe', __name__)


@probe_bp.route('/role-probe/manager')
@role_required(Role.FARM_MANAGER)
def manager_only():
    return jsonify({'ok': True})


@probe_bp.route('/role-probe/farmer')
@role_required(Role.FARMER)
def farmer_route():
    return jsonify({'ok': True})


@probe_bp.route('/role-probe/platform')
@platform_admin_required
def platform_only():
    return jsonify({'ok': True})


COOPERATIVE = {
    'name': 'Maziwa Cooperative', 'region': 'Central', 'registration_number': 'REG-2026-001',
    'admin_name': 'Co-op Manager', 'admin_username': 'coop_manager',
    'admin_phone_number': '0712000000', 'admin_password': 'StrongPass123',
}


class RoleRequiredTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.app.register_blueprint(probe_bp)

    def _headers_for(self, username, role, tenant=None):
        self.create_user(username=username, password='password', role=role, tenant=tenant)
        token = self.client.post('/api/auth/login', json={'username': username, 'password': 'password'}).get_json()['access_token']
        self.client.delete_cookie('access_token_cookie')
        return {'Authorization': f'Bearer {token}'}

    def test_farm_level_admin_roles_keep_farm_access(self):
        coop = Tenant(name='Coop', tenant_type='cooperative')
        db.session.add(coop)
        db.session.commit()
        for username, role, tenant in (
            ('owner', Role.FARMER, None), ('farm_admin', Role.FARM_ADMIN, None), ('coop_admin', Role.ADMIN, coop),
        ):
            headers = self._headers_for(username, role, tenant)
            self.assertEqual(self.client.get('/role-probe/manager', headers=headers).status_code, 200, role)
            self.assertEqual(self.client.get('/role-probe/farmer', headers=headers).status_code, 200, role)

    def test_role_is_read_live_from_the_database(self):
        headers = self._headers_for('manager', Role.FARM_MANAGER)
        self.assertEqual(self.client.get('/role-probe/manager', headers=headers).status_code, 200)
        manager = User.query.filter_by(username='manager').one()
        manager.role = Role.FARM_HAND
        db.session.commit()
        # Same token, which still says FARM_MANAGER.
        self.assertEqual(self.client.get('/role-probe/manager', headers=headers).status_code, 403)

    def test_super_admin_satisfies_no_role_check(self):
        headers, _, _ = self.platform_admin_session()
        self.assertEqual(self.client.get('/role-probe/farmer', headers=headers).status_code, 403)
        self.assertEqual(self.client.get('/role-probe/manager', headers=headers).status_code, 403)

    def test_platform_admin_required_needs_the_verified_platform_admin(self):
        headers, _, _ = self.platform_admin_session()
        self.assertEqual(self.client.get('/role-probe/platform', headers=headers).status_code, 200)

        pending = self.client.post('/api/auth/login', json={'username': 'platform_admin', 'password': 'password'})
        self.client.delete_cookie('access_token_cookie')
        unverified = {'Authorization': f"Bearer {pending.get_json()['access_token']}"}
        self.assertEqual(self.client.get('/role-probe/platform', headers=unverified).status_code, 403)

        for role in (Role.FARMER, Role.FARM_ADMIN):
            response = self.client.get('/role-probe/platform', headers=self._headers_for(f'u_{role.lower()}', role))
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.get_json()['code'], 'PLATFORM_ADMIN_REQUIRED')


class PlatformRoutesTestCase(BaseTestCase):

    def _create_cooperative(self, headers):
        return self.client.post('/api/tenant/cooperatives', json=COOPERATIVE, headers=headers)

    def test_farm_roles_cannot_create_cooperatives(self):
        coop = Tenant(name='Coop', tenant_type='cooperative')
        db.session.add(coop)
        db.session.commit()
        for role, tenant in ((Role.FARMER, None), (Role.FARM_ADMIN, None), (Role.ADMIN, coop)):
            self.create_user(username=f'u_{role.lower()}', password='password', role=role, tenant=tenant)
            token = self.client.post('/api/auth/login', json={'username': f'u_{role.lower()}', 'password': 'password'}).get_json()['access_token']
            response = self._create_cooperative({'Authorization': f'Bearer {token}'})
            self.assertEqual(response.status_code, 403, role)
        self.assertEqual(Tenant.query.filter_by(tenant_type='cooperative').count(), 1)

    def test_verified_platform_admin_creates_a_cooperative_and_manages_its_members(self):
        headers, _, _ = self.platform_admin_session()
        created = self._create_cooperative(headers)
        self.assertEqual(created.status_code, 201)
        coop_id = created.get_json()['cooperative_id']

        invite = self.client.post(
            f'/api/tenant/cooperatives/{coop_id}/members',
            json={'full_name': 'Jane Farmer', 'phone_number': '0712333444', 'role': Role.FARMER},
            headers=headers,
        )
        self.assertEqual(invite.status_code, 201)
        bulk = self.client.post(
            f'/api/tenant/cooperatives/{coop_id}/members/bulk',
            data={'file': (io.BytesIO(b'full_name,phone_number\nJohn Farmer,0712333445\n'), 'members.csv')},
            content_type='multipart/form-data',
            headers=headers,
        )
        self.assertEqual(bulk.status_code, 201)

    def test_platform_admin_cannot_add_members_to_the_platform_or_demo_tenant(self):
        headers, _, _ = self.platform_admin_session()
        demo = Tenant(name='Demo', tenant_type='single', is_demo=True)
        db.session.add(demo)
        db.session.commit()
        for tenant_id in (PlatformTenant.get().id, demo.id, 999999):
            response = self.client.post(
                f'/api/tenant/cooperatives/tenant_{tenant_id}/members',
                json={'full_name': 'X', 'phone_number': '0712333446', 'role': Role.FARMER},
                headers=headers,
            )
            self.assertEqual(response.status_code, 404, tenant_id)

    def test_cooperative_admin_manages_own_members_only_through_the_tenant_routes(self):
        headers, _, _ = self.platform_admin_session()
        coop = self._create_cooperative(headers).get_json()
        coop_headers = {'Authorization': f"Bearer {coop['access_token']}"}
        self.client.delete_cookie('access_token_cookie')

        refused = self.client.post(
            f"/api/tenant/cooperatives/{coop['cooperative_id']}/members",
            json={'full_name': 'Jane', 'phone_number': '0712333447', 'role': Role.FARMER},
            headers=coop_headers,
        )
        self.assertEqual(refused.status_code, 403)
        own = self.client.post(
            '/api/tenant/members/invite',
            json={'full_name': 'Jane', 'phone_number': '0712333447', 'role': Role.FARMER},
            headers=coop_headers,
        )
        self.assertEqual(own.status_code, 201)

    def test_cross_tenant_password_reset_needs_the_platform_admin(self):
        other = Tenant(name='Other farm', tenant_type='single')
        db.session.add(other)
        db.session.commit()
        target = self.create_user(username='other_hand', password='password', role=Role.FARM_HAND, tenant=other)

        owner = self.get_auth_headers(Role.FARMER)
        self.client.delete_cookie('access_token_cookie')
        self.assertEqual(
            self.client.post(f'/api/tenant/users/{target.id}/password-reset', headers=owner).status_code, 404,
        )

        headers, _, _ = self.platform_admin_session()
        self.assertEqual(
            self.client.post(f'/api/tenant/users/{target.id}/password-reset', headers=headers).status_code, 201,
        )
