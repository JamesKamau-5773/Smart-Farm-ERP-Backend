"""Putting a cow's milk on hold by hand (from the board, or after a failed test), and clearing it."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.models.livestock import Cow
from app.repositories.cow_repo import CowRepository
from app.services.audit_service import record_audit
from app.utils.api_errors import ApiError
from app.utils.datetimes import parse_iso_datetime
from app.utils.unit_of_work import unit_of_work

MAX_REASON_LENGTH = 120


def require_cow(tenant_id: int, cow_id) -> Cow:
    try:
        cow_pk = int(cow_id)
    except (TypeError, ValueError):
        raise ApiError('VALIDATION_ERROR', 'cow_id is required.')
    cow = CowRepository.get_by_id(cow_pk, tenant_id=tenant_id)
    if cow is None:
        raise ApiError('NOT_FOUND', 'Cow not found in this farm.', 404)
    return cow


class MilkHoldService:
    @staticmethod
    def place(tenant_id: int, data: dict, *, actor_id: Optional[int], ip_address=None) -> Cow:
        cow = require_cow(tenant_id, data.get('cow_id'))
        reason = str(data.get('reason') or '').strip()
        if not reason:
            raise ApiError('VALIDATION_ERROR', 'reason is required.')
        if len(reason) > MAX_REASON_LENGTH:
            raise ApiError('VALIDATION_ERROR', f'reason must be at most {MAX_REASON_LENGTH} characters.')
        try:
            until = parse_iso_datetime(data.get('until'))
        except ValueError:
            raise ApiError('VALIDATION_ERROR', 'until must be an ISO 8601 date-time.')
        if until is not None and until <= datetime.now(timezone.utc):
            raise ApiError('VALIDATION_ERROR', 'until must be in the future.')
        with unit_of_work():
            MilkHoldService.stage(cow, reason, until=until, notes=data.get('notes'), actor_id=actor_id, ip_address=ip_address)
        return cow

    @staticmethod
    def stage(cow: Cow, reason: str, *, until=None, notes=None, actor_id=None, ip_address=None) -> None:
        """Holds the milk and audits it. The caller commits."""
        before = {'is_hardlocked': bool(cow.is_hardlocked), 'hold_reason': cow.hold_reason}
        cow.is_hardlocked = True
        cow.hold_reason = reason[:MAX_REASON_LENGTH]
        cow.hold_until = until
        cow.hold_notes = (notes or '').strip() or None
        cow.hold_set_at = datetime.now(timezone.utc)
        cow.hold_set_by = actor_id
        record_audit(
            user_id=actor_id, action='PLACE_MILK_HOLD', entity_type='Livestock', entity_id=cow.id,
            old_value=before,
            new_value={'is_hardlocked': True, 'hold_reason': cow.hold_reason, 'hold_until': until.isoformat() if until else None},
            ip_address=ip_address,
        )

    @staticmethod
    def clear(cow: Cow) -> None:
        """Forgets a manual hold's details when the milk is released. The caller commits."""
        cow.hold_reason = None
        cow.hold_notes = None
        cow.hold_until = None
        cow.hold_set_at = None
        cow.hold_set_by = None
