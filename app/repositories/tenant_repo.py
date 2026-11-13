from __future__ import annotations

from app import db
from app.models.tenant import Tenant


class TenantRepository:
    @staticmethod
    def get_by_id(tenant_id: int) -> Tenant | None:
        return db.session.get(Tenant, tenant_id)
