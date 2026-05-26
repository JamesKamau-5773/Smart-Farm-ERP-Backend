import unittest
from app import create_app, db
from config import TestConfig

from app.models.tenant import Tenant
from app.models.farm import Farm
from app.models.user import User

class BaseTestCase(unittest.TestCase):
    """A base test case for the application."""

    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.tenant = Tenant(name='Default Tenant', tenant_type='single')
        db.session.add(self.tenant)
        db.session.flush()

        self.farm = Farm(tenant_id=self.tenant.id, name='Default Farm')
        db.session.add(self.farm)
        db.session.commit()

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

    def create_user(self, *, username: str, password: str, role: str, tenant: Tenant | None = None, name: str | None = None, email: str | None = None, identifier: str | None = None):
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

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
