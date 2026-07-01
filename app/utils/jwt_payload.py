from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


ALLOWED_TENANT_TYPES = {"single", "cooperative"}


def normalize_tenant_type(value: Optional[str]) -> str:
    if not value:
        return "single"
    value = value.strip().lower()
    if value not in ALLOWED_TENANT_TYPES:
        raise ValueError(f"Invalid tenant_type '{value}'. Must be one of: {sorted(ALLOWED_TENANT_TYPES)}")
    return value


def public_tenant_id(tenant_pk: int) -> str:
    return f"tenant_{tenant_pk}"


def public_farm_id(farm_pk: int) -> str:
    return f"farm_{farm_pk}"


def parse_public_id(value: str, prefix: str) -> str:
    value = (value or "").strip()
    if value.startswith(prefix):
        return value[len(prefix) :]
    return value


def parse_public_int_id(value: str, prefix: str) -> int:
    raw = parse_public_id(value, prefix)
    return int(raw)


def build_auth_payload(*,
    user_id: int,
    name: str,
    phone_number: str,
    role: str,
    tenant_pk: int,
    tenant_name: str,
    tenant_type: str,
    active_farm_pk: int,
    active_farm_name: str,
    available_farms: List[Tuple[int, str]],
) -> Dict[str, Any]:
    tenant_type = normalize_tenant_type(tenant_type)

    farms_payload = [{"id": public_farm_id(fid), "name": fname} for fid, fname in available_farms]

    return {
        "sub": str(user_id),
        "name": name,
        "phone_number": phone_number,
        "role": role,
        "tenant_id": public_tenant_id(tenant_pk),
        "tenant_name": tenant_name,
        "tenant_type": tenant_type,
        "farm_id": public_farm_id(active_farm_pk),
        "farm_name": active_farm_name,
        "available_farms": farms_payload,
    }
