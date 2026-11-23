"""The platform workspace: where the SUPER_ADMIN lives. It is never a farm.

A migration creates it in every database. ``get_or_create`` only matters for
databases built with ``db.create_all()`` (the tests).
"""
from __future__ import annotations

from typing import Optional

from app import db
from app.models.tenant import Tenant


class PlatformTenant:
    NAME = 'Maziwa Smart Platform'

    @staticmethod
    def get() -> Optional[Tenant]:
        return Tenant.query.filter_by(is_platform=True).first()

    @staticmethod
    def get_or_create() -> Tenant:
        tenant = PlatformTenant.get()
        if tenant is None:
            tenant = Tenant(name=PlatformTenant.NAME, tenant_type='single', is_active=True, is_platform=True)
            db.session.add(tenant)
            db.session.flush()
        return tenant

    @staticmethod
    def is_platform(tenant: Optional[Tenant]) -> bool:
        return bool(tenant is not None and getattr(tenant, 'is_platform', False))
