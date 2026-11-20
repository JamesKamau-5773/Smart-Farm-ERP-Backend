"""Identity of the public demo workspace: where it is and who belongs to it.

The only module that knows the demo's names and how its records are flagged.
Login, the read-only guard and the seed all ask this module rather than
checking flags or names themselves.
"""
from __future__ import annotations

from typing import Optional

from flask import current_app

from app import db
from app.models.farm import Farm
from app.models.tenant import Tenant
from app.models.user import Role, User


class DemoAccount:
    TENANT_NAME = 'Silato Farm'
    FARM_NAME = 'Silato Farm'
    FARM_LOCATION = 'Nakuru County'
    # Shown on the demo's receipts and farm profile; obviously not a real registration.
    REGISTRATION_NUMBER = 'DEMO-SILATO-0001'

    # Global-unique columns are namespaced so they can never collide with a real account.
    OWNER_USERNAME = 'demo.silato.owner'
    OWNER_NAME = 'Demo Visitor'

    @staticmethod
    def is_enabled() -> bool:
        return bool(current_app.config.get('DEMO_ENABLED'))

    @staticmethod
    def session_minutes() -> int:
        return int(current_app.config.get('DEMO_SESSION_MINUTES') or 45)

    @staticmethod
    def tenant() -> Optional[Tenant]:
        return Tenant.query.filter_by(is_demo=True).first()

    @staticmethod
    def farm(tenant: Tenant) -> Optional[Farm]:
        return Farm.query.filter_by(tenant_id=tenant.id).order_by(Farm.id.asc()).first()

    @staticmethod
    def owner() -> Optional[User]:
        return User.query.filter_by(username=DemoAccount.OWNER_USERNAME, is_demo=True).first()

    @staticmethod
    def is_demo_user(user: Optional[User]) -> bool:
        """Demo status of an account, from the database (never from the client)."""
        if user is None:
            return False
        if user.is_demo:
            return True
        tenant = user.tenant if user.tenant_id is not None else None
        return bool(tenant is not None and tenant.is_demo)

    @staticmethod
    def is_demo_actor(actor_id) -> bool:
        try:
            user = db.session.get(User, int(actor_id))
        except (TypeError, ValueError):
            return False
        return DemoAccount.is_demo_user(user)

    @staticmethod
    def describe(user: Optional[User]) -> dict:
        """Frontend-facing demo state; part of the login and /me responses."""
        is_demo = DemoAccount.is_demo_user(user)
        return {'is_demo': is_demo, 'read_only': is_demo}

    @staticmethod
    def new_user(*, tenant: Tenant, username: str, name: str, role: str = Role.FARMER) -> User:
        """A demo account: flagged, no email or phone, and no usable password."""
        user = User(
            tenant_id=tenant.id,
            identifier=f'demo:{username}',
            username=username,
            name=name,
            role=role,
            farm_location=DemoAccount.FARM_LOCATION,
            is_active=True,
            is_demo=True,
            requires_password_reset=False,
        )
        user.set_unusable_password()
        return user
