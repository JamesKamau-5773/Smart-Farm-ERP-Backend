"""The single SUPER_ADMIN account: the only code that creates, moves or demotes it.

Every change runs inside ``super_admin_changes_allowed()``; the model guard in
app/models/user.py refuses the same change anywhere else. The partial unique
index ``uq_users_single_super_admin`` is the final guard against a second one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app import db
from app.models.user import Role, User
from app.services.platform_tenant import PlatformTenant
from app.utils.super_admin_guard import SuperAdminChangeRefused, super_admin_changes_allowed


class SuperAdminExists(SuperAdminChangeRefused):
    """A super admin already exists; there can only be one."""


@dataclass(frozen=True)
class NewSuperAdmin:
    username: str
    identifier: str
    name: str
    password: str
    phone_number: Optional[str] = None
    email: Optional[str] = None


class PlatformAccountService:
    @staticmethod
    def super_admin() -> Optional[User]:
        return User.query.filter_by(role=Role.SUPER_ADMIN).first()

    @staticmethod
    def is_platform_super_admin(user: Optional[User]) -> bool:
        """The live database answer: the SUPER_ADMIN, active, in the platform tenant."""
        return bool(
            user is not None
            and user.role == Role.SUPER_ADMIN
            and user.is_active
            and PlatformTenant.is_platform(user.tenant)
        )

    @staticmethod
    def create_super_admin(details: NewSuperAdmin) -> User:
        """Creates the super admin in the platform tenant. Flushes; the caller commits.

        Raises SuperAdminExists when one already exists (checked here, and by the
        unique index if two requests race).
        """
        if PlatformAccountService.super_admin() is not None:
            raise SuperAdminExists('A super admin already exists.')
        tenant = PlatformTenant.get_or_create()
        user = User(
            tenant_id=tenant.id,
            identifier=details.identifier,
            username=details.username,
            name=details.name,
            phone_number=details.phone_number,
            email=details.email,
            role=Role.SUPER_ADMIN,
            is_active=True,
        )
        user.set_password(details.password)
        with super_admin_changes_allowed():
            db.session.add(user)
            try:
                db.session.flush()
            except IntegrityError as error:
                if 'uq_users_single_super_admin' in str(error.orig):
                    raise SuperAdminExists('A super admin already exists.') from error
                raise
        return user
