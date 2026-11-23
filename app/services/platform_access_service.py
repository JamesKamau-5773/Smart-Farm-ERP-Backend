"""Platform-admin authorization: who may act across tenants.

Passes only when the signed-in user, loaded live from the database (never from
token claims), is the active SUPER_ADMIN, lives in the platform tenant, and the
current session (its token id) has passed two-factor authentication.
"""
from __future__ import annotations

from typing import Optional

from flask_jwt_extended import get_jwt, get_jwt_identity

from app import db
from app.models.tenant import Tenant
from app.models.user import User
from app.services.mfa_service import MfaService
from app.services.platform_account_service import PlatformAccountService
from app.utils.api_errors import ApiError
from app.utils.jwt_payload import parse_public_int_id


class PlatformAccessService:
    @staticmethod
    def is_verified_platform_admin(user: Optional[User], jti: Optional[str]) -> bool:
        return PlatformAccountService.is_platform_super_admin(user) and MfaService.session_verified(user, jti)

    @staticmethod
    def current_platform_admin() -> Optional[User]:
        """The verified platform admin making this request, or None. Needs a verified JWT in the request."""
        identity = get_jwt_identity()
        try:
            user = db.session.get(User, int(identity)) if identity is not None else None
        except (TypeError, ValueError):
            user = None
        jti = (get_jwt() or {}).get('jti')
        return user if PlatformAccessService.is_verified_platform_admin(user, jti) else None

    @staticmethod
    def target_farm_tenant(tenant_id) -> Tenant:
        """A tenant the platform admin may administer: any farm or cooperative tenant, never the
        platform tenant itself or the demo. Unknown, platform and demo ids all look the same."""
        try:
            tenant_pk = parse_public_int_id(str(tenant_id).strip(), 'tenant_')
        except (TypeError, ValueError):
            raise ApiError('NOT_FOUND', 'Tenant not found.', 404)
        tenant = db.session.get(Tenant, tenant_pk)
        if tenant is None or tenant.is_platform or tenant.is_demo:
            raise ApiError('NOT_FOUND', 'Tenant not found.', 404)
        return tenant
