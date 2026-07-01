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
            self.assertEqual(data['phone_number'], '+254712345678')

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
