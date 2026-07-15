import io
import json
from tests.base import BaseTestCase
from app.models.user import User, Role
from app.models.tenant import Tenant
from app.models.farm import Farm
from app import db

class AuthTestCase(BaseTestCase):

    def _create_tenant_user(self, *, tenant_type: str = 'single', farm_count: int = 1):
        tenant = Tenant(name='Jivu Cooperative Ltd', tenant_type=tenant_type)
        db.session.add(tenant)
        db.session.flush()

        farms = []
        for i in range(farm_count):
            farm = Farm(tenant_id=tenant.id, name=f'Farm {i + 1}')
            db.session.add(farm)
            farms.append(farm)
        db.session.flush()

        user = User(
            tenant_id=tenant.id,
            identifier='user_1',
            username='testuser',
            name='James Mwangi',
            email='farmer@jivu.com',
            role=Role.FARMER,
        )
        user.set_password('password')
        db.session.add(user)
        db.session.commit()

        return user, tenant, farms

    def test_login(self):
        """Login returns access_token and required tenant/farm payload."""
        self._create_tenant_user(tenant_type='single', farm_count=1)

        with self.client:
            response = self.client.post(
                '/api/auth/login',
                data=json.dumps(dict(
                    username='testuser',
                    password='password'
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data.decode())
            self.assertTrue(data['access_token'])
            for key in [
                'sub', 'name', 'phone_number', 'role',
                'tenant_id', 'tenant_name', 'tenant_type',
                'farm_id', 'farm_name', 'available_farms'
            ]:
                self.assertIn(key, data)

            self.assertIn(data['tenant_type'], ['single', 'cooperative'])
            self.assertEqual(len(data['available_farms']), 1)

    def test_logout(self):
        """Test user logout."""
        self._create_tenant_user(tenant_type='single', farm_count=1)
        login_resp = self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(
                username='testuser',
                password='password'
            )),
            content_type='application/json'
        )
        token = json.loads(login_resp.data.decode())['access_token']

        with self.client:
            response = self.client.post(
                '/api/auth/logout',
                headers={'Authorization': f'Bearer {token}'},
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data.decode())
            self.assertEqual(data['message'], 'Successfully logged out.')

    def test_switch_farm_cooperative(self):
        """Cooperative users can switch farms and receive a new token/payload."""
        user, tenant, farms = self._create_tenant_user(tenant_type='cooperative', farm_count=2)
        farm_1 = farms[0]
        farm_2 = farms[1]

        with self.client:
            login_resp = self.client.post(
                '/api/auth/login',
                data=json.dumps(dict(
                    username='testuser',
                    password='password',
                    farm_id=f'farm_{farm_1.id}'
                )),
                content_type='application/json'
            )
            self.assertEqual(login_resp.status_code, 200)
            login_data = json.loads(login_resp.data.decode())
            token = login_data['access_token']
            self.assertEqual(login_data['farm_id'], f'farm_{farm_1.id}')

            switch_resp = self.client.post(
                '/api/auth/switch-farm',
                data=json.dumps({"farm_id": f'farm_{farm_2.id}'}),
                headers={'Authorization': f'Bearer {token}'},
                content_type='application/json'
            )
            self.assertEqual(switch_resp.status_code, 200)
            switch_data = json.loads(switch_resp.data.decode())
            self.assertEqual(switch_data['farm_id'], f'farm_{farm_2.id}')

    def test_register_workspace(self):
        with self.client:
            response = self.client.post(
                '/api/auth/register',
                data=json.dumps(dict(
                    farm_name='Green Valley Farm',
                    tenant_name='Green Valley Holdings',
                    name='Amina Njeri',
                    phone_number='+254712345678',
                    password='StrongPass123',
                    tenant_type='single',
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 201)
            data = json.loads(response.data.decode())
            self.assertIn('access_token', data)
            self.assertEqual(data['tenant_name'], 'Green Valley Holdings')
            self.assertEqual(data['farm_name'], 'Green Valley Farm')
            self.assertEqual(data['role'], Role.FARMER)
            self.assertEqual(data['phone_number'], '254712345678')

    def test_register_workspace_ignores_client_role_without_bootstrap_key(self):
        with self.client:
            response = self.client.post(
                '/api/auth/register',
                data=json.dumps(dict(
                    farm_name='Role Check Farm',
                    tenant_name='Role Check Tenant',
                    name='Admin Attempt',
                    phone_number='+254700000001',
                    password='StrongPass123',
                    role='SUPER_ADMIN',
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 403)
            data = json.loads(response.data.decode())
            self.assertIn('bootstrap', data['error'].lower())

    def test_register_workspace_allows_super_admin_with_valid_bootstrap_key(self):
        original_key = self.app.config['BOOTSTRAP_SUPER_ADMIN_KEY']
        self.app.config['BOOTSTRAP_SUPER_ADMIN_KEY'] = 'bootstrap-secret-2026'

        try:
            with self.client:
                response = self.client.post(
                    '/api/auth/register',
                    data=json.dumps(dict(
                        farm_name='Bootstrap Farm',
                        tenant_name='Bootstrap Tenant',
                        name='System Admin',
                        phone_number='+254700000002',
                        password='StrongPass123',
                        role='SUPER_ADMIN',
                        bootstrap_key='bootstrap-secret-2026',
                    )),
                    content_type='application/json'
                )
                self.assertEqual(response.status_code, 201)
                data = json.loads(response.data.decode())
                self.assertEqual(data['role'], Role.SUPER_ADMIN)
        finally:
            self.app.config['BOOTSTRAP_SUPER_ADMIN_KEY'] = original_key

    def test_register_workspace_rejects_duplicate_username(self):
        self._create_tenant_user(tenant_type='single', farm_count=1)
        with self.client:
            response = self.client.post(
                '/api/auth/register',
                data=json.dumps(dict(
                    farm_name='Duplicate Farm',
                    phone_number='testuser',
                    password='StrongPass123',
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 409)

    def test_login_with_phone_number_payload(self):
        self._create_tenant_user(tenant_type='single', farm_count=1)
        with self.client:
            response = self.client.post(
                '/api/auth/login',
                data=json.dumps(dict(
                    phone_number='testuser',
                    password='password'
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data.decode())
            self.assertTrue(data['access_token'])

    def test_super_admin_cannot_be_deleted_without_override(self):
        self.create_user(username='platform_admin', password='password', role=Role.SUPER_ADMIN)

        with self.app.app_context():
            admin = User.query.filter_by(username='platform_admin').first()
            db.session.delete(admin)
            with self.assertRaises(ValueError):
                db.session.commit()
            db.session.rollback()

    def test_super_admin_can_be_deleted_with_explicit_override(self):
        self.create_user(username='platform_admin', password='password', role=Role.SUPER_ADMIN)
        original = self.app.config.get('ALLOW_SUPER_ADMIN_REMOVAL', False)
        self.app.config['ALLOW_SUPER_ADMIN_REMOVAL'] = True

        try:
            with self.app.app_context():
                admin = User.query.filter_by(username='platform_admin').first()
                db.session.delete(admin)
                db.session.commit()
                self.assertIsNone(User.query.filter_by(username='platform_admin').first())
        finally:
            self.app.config['ALLOW_SUPER_ADMIN_REMOVAL'] = original

    def test_superadmin_can_create_cooperative(self):
        self.create_user(username='platform_admin', password='password', role=Role.SUPER_ADMIN)

        login_resp = self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(
                username='platform_admin',
                password='password'
            )),
            content_type='application/json'
        )
        self.assertEqual(login_resp.status_code, 200)
        token = json.loads(login_resp.data.decode())['access_token']

        response = self.client.post(
            '/api/tenant/cooperatives',
            data=json.dumps({
                'name': 'Maziwa Cooperative',
                'region': 'Central',
                'registration_number': 'REG-2026-001',
                'admin_name': 'Co-op Manager',
                'admin_username': 'coop_manager',
                'admin_phone_number': '0712000000',
                'admin_password': 'StrongPass123',
            }),
            content_type='application/json',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.data.decode())
        self.assertEqual(data['tenant_type'], 'cooperative')
        self.assertEqual(data['cooperative_name'], 'Maziwa Cooperative')
        self.assertEqual(data['region'], 'Central')
        self.assertEqual(data['registration_number'], 'REG-2026-001')
        self.assertIn('admin', data)

    def test_member_invite_can_be_claimed(self):
        self.create_user(username='platform_admin', password='password', role=Role.SUPER_ADMIN)

        login_resp = self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(
                username='platform_admin',
                password='password'
            )),
            content_type='application/json'
        )
        token = json.loads(login_resp.data.decode())['access_token']

        coop_resp = self.client.post(
            '/api/tenant/cooperatives',
            data=json.dumps({
                'name': 'Sunrise Cooperative',
                'region': 'Nairobi',
                'registration_number': 'REG-2026-002',
                'admin_name': 'Manager',
                'admin_username': 'sunrise_admin',
                'admin_phone_number': '0712000001',
                'admin_password': 'StrongPass123',
            }),
            content_type='application/json',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(coop_resp.status_code, 201)
        coop_data = json.loads(coop_resp.data.decode())

        invite_resp = self.client.post(
            f"/api/tenant/cooperatives/{coop_data['cooperative_id']}/members",
            data=json.dumps({
                'full_name': 'Jane Farmer',
                'phone_number': '0712333444',
                'role': Role.FARMER,
            }),
            content_type='application/json',
            headers={'Authorization': f"Bearer {coop_data['access_token']}"},
        )
        self.assertEqual(invite_resp.status_code, 201)
        invite_data = json.loads(invite_resp.data.decode())

        claim_resp = self.client.post(
            '/api/auth/claim-account',
            data=json.dumps({
                'token': invite_data['invite_token'],
                'password': 'MemberPass123',
            }),
            content_type='application/json'
        )
        self.assertEqual(claim_resp.status_code, 200)
        claim_data = json.loads(claim_resp.data.decode())
        self.assertEqual(claim_data['cooperative_id'], coop_data['cooperative_id'])
        self.assertEqual(claim_data['role'], Role.FARMER)

    def test_bulk_member_csv_import_creates_invites(self):
        self.create_user(username='platform_admin', password='password', role=Role.SUPER_ADMIN)

        login_resp = self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(
                username='platform_admin',
                password='password'
            )),
            content_type='application/json'
        )
        token = json.loads(login_resp.data.decode())['access_token']

        coop_resp = self.client.post(
            '/api/tenant/cooperatives',
            data=json.dumps({
                'name': 'Bulk Import Cooperative',
                'region': 'Rift Valley',
                'registration_number': 'REG-2026-003',
                'admin_name': 'Manager',
                'admin_username': 'bulk_admin',
                'admin_phone_number': '0712000002',
                'admin_password': 'StrongPass123',
            }),
            content_type='application/json',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(coop_resp.status_code, 201)
        coop_data = json.loads(coop_resp.data.decode())

        csv_payload = (
            'full_name,phone_number,farm_location\n'
            'Jane Farmer,0712333444,Plot A\n'
            'John Farmer,0712333445,Plot B\n'
        )

        import_resp = self.client.post(
            f"/api/tenant/cooperatives/{coop_data['cooperative_id']}/members/bulk",
            data={
                'file': (io.BytesIO(csv_payload.encode('utf-8')), 'members.csv'),
            },
            content_type='multipart/form-data',
            headers={'Authorization': f"Bearer {coop_data['access_token']}"},
        )
        self.assertEqual(import_resp.status_code, 201)
        import_data = json.loads(import_resp.data.decode())
        self.assertEqual(import_data['created_count'], 2)
        self.assertEqual(len(import_data['members']), 2)
        self.assertEqual(import_data['members'][0]['farm_location'], 'Plot A')
        self.assertTrue(import_data['members'][0]['invite_url'])

    def test_staff_list_ignores_invalid_authorization_header_when_cookies_are_valid(self):
        self._create_tenant_user(tenant_type='single', farm_count=1)

        with self.client:
            login_resp = self.client.post(
                '/api/auth/login',
                data=json.dumps(dict(
                    username='testuser',
                    password='password'
                )),
                content_type='application/json'
            )
            self.assertEqual(login_resp.status_code, 200)

            response = self.client.get(
                '/api/hr/staff',
                headers={'Authorization': 'Bearer null'},
            )
            self.assertEqual(response.status_code, 200)
