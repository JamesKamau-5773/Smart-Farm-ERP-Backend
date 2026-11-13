"""The tenant/farm a request may see, taken from the JWT claims and nothing else."""
from __future__ import annotations

from dataclasses import dataclass

from flask import g

from app.utils.api_errors import ApiError
from app.utils.context import get_tenant_id_from_context
from app.utils.jwt_payload import parse_public_int_id


@dataclass(frozen=True)
class FarmScope:
    tenant_id: int
    farm_id: int | None  # None only for tokens issued without an active farm

    @classmethod
    def from_request(cls) -> 'FarmScope':
        tenant_id = get_tenant_id_from_context()
        if not tenant_id:
            raise ApiError('VALIDATION_ERROR', 'Tenant context is missing.', status=400)
        farm_id = None
        raw_farm = getattr(g, 'farm_id', None)
        if raw_farm is not None:
            try:
                farm_id = parse_public_int_id(str(raw_farm), 'farm_')
            except (TypeError, ValueError):
                farm_id = None
        return cls(tenant_id=tenant_id, farm_id=farm_id)
