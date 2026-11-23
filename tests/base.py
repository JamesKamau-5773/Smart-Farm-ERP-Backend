import unittest
from typing import Optional
from app import create_app, db
from config import TestConfig

from app.models.tenant import Tenant
from app.models.farm import Farm
from app.models.user import User
from app.models.user import Role

class BaseTestCase(unittest.TestCase):
    """A base test case for the application."""

    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        # unittest skips tearDown when setUp raises (here or in a subclass). Without this the
        # open session keeps its locks and the next test's drop_all() waits forever.
        self.addCleanup(self._release_database)
        db.session.rollback()
        db.session.remove()
        db.drop_all()
        db.create_all()

        self.tenant = Tenant(name='Default Tenant', tenant_type='single')
        db.session.add(self.tenant)
        db.session.flush()

        self.farm = Farm(tenant_id=self.tenant.id, name='Default Farm')
        db.session.add(self.farm)
        db.session.commit()
        self.tenant_id = self.tenant.id
        self.user_id = None

    def create_tenant(self, *, name='Tenant', tenant_type='single'):
        tenant = Tenant(name=name, tenant_type=tenant_type)
        db.session.add(tenant)
        db.session.flush()
        return tenant

    def create_farm(self, *, tenant: Tenant, name='Farm'):
        farm = Farm(tenant_id=tenant.id, name=name)
        db.session.add(farm)
        db.session.flush()
        return farm

    def create_user(self, *, username: str, password: str, role: str, tenant: Optional[Tenant] = None, name: Optional[str] = None, email: Optional[str] = None, identifier: Optional[str] = None):
        tenant = tenant or self.tenant
        user = User(
            tenant_id=tenant.id,
            identifier=identifier or f"{username}_id",
            username=username,
            name=name or username,
            email=email or f"{username}@example.com",
            role=role,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    def create_platform_admin(self, *, username: str = 'platform_admin', password: str = 'password',
                              phone_number: Optional[str] = None):
        """The one SUPER_ADMIN, in the platform tenant, created the only way the app allows."""
        from app.services.platform_account_service import NewSuperAdmin, PlatformAccountService

        user = PlatformAccountService.create_super_admin(NewSuperAdmin(
            username=username,
            identifier=f'{username}_id',
            name=username,
            password=password,
            phone_number=phone_number,
            email=f'{username}@example.com',
        ))
        db.session.commit()
        return user

    def platform_admin_session(self, *, username: str = 'platform_admin', password: str = 'password'):
        """Creates the super admin, signs in and completes 2FA enrolment.

        Returns (headers for the verified session, TOTP secret, recovery codes).
        """
        from app.services.totp_service import TotpService

        self.create_platform_admin(username=username, password=password)
        login = self.client.post('/api/auth/login', json={'username': username, 'password': password})
        self.assertEqual(login.status_code, 200)
        pending = {'Authorization': f"Bearer {login.get_json()['access_token']}"}
        enrolment = self.client.post('/api/auth/mfa/enrollment', headers=pending)
        self.assertEqual(enrolment.status_code, 200)
        secret = enrolment.get_json()['secret']
        code = TotpService.code_at(secret, TotpService.current_step())
        confirmed = self.client.post('/api/auth/mfa/enrollment/confirm', json={'code': code}, headers=pending)
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        body = confirmed.get_json()
        return {'Authorization': f"Bearer {body['access_token']}"}, secret, body['recovery_codes']

    def get_auth_headers(self, role: str = Role.FARMER):
        username = f'test_{role.lower()}'
        password = 'password'
        self.create_user(username=username, password=password, role=role)
        response = self.client.post(
            '/api/auth/login',
            json={'username': username, 'password': password},
        )
        self.assertEqual(response.status_code, 200)
        return {'Authorization': f"Bearer {response.get_json()['access_token']}"}

    def tearDown(self):
        db.session.rollback()
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.app_context.pop()
        self._database_released = True

    def _release_database(self):
        if getattr(self, '_database_released', False):
            return
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()
        self.app_context.pop()
