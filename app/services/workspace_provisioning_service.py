"""Creates a new tenant + farm + owner account (self-service sign-up)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from app import db
from app.models.farm import Farm
from app.models.tenant import Tenant
from app.models.user import User


@dataclass(frozen=True)
class WorkspaceRequest:
    farm_name: str
    tenant_name: str
    tenant_type: str
    role: str
    display_name: str
    username: str
    identifier: str
    phone_number: Optional[str]
    email: Optional[str] = None
    email_verified: bool = False
    password: Optional[str] = None


class WorkspaceProvisioningService:
    @staticmethod
    def create(request: WorkspaceRequest) -> Tuple[User, Tenant, Farm]:
        """Adds the records to the session and flushes; the caller commits."""
        tenant = Tenant(name=request.tenant_name, tenant_type=request.tenant_type)
        db.session.add(tenant)
        db.session.flush()

        farm = Farm(tenant_id=tenant.id, name=request.farm_name)
        db.session.add(farm)
        db.session.flush()

        user = User(
            tenant_id=tenant.id,
            identifier=request.identifier,
            username=request.username,
            name=request.display_name,
            email=request.email,
            email_verified=request.email_verified,
            phone_number=request.phone_number,
            role=request.role,
            is_active=True,
        )
        if request.password:
            user.set_password(request.password)
        else:
            user.set_unusable_password()
        db.session.add(user)
        db.session.flush()
        return user, tenant, farm
