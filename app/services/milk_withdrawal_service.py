"""When a cow's treatment withdrawal ends, and whether her milk may be released.

The withdrawal ends when the *last* running treatment's period ends, so every
treatment counts, not only the latest one: a later treatment with no
withdrawal must not hide an earlier one that is still running.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.livestock import Cow, MedicalRecord
from app.repositories.medical_repo import MedicalRepository
from app.utils.api_errors import ApiError
from app.utils.datetimes import as_utc


@dataclass(frozen=True)
class Withdrawal:
    ends_at: Optional[datetime]
    record: Optional[MedicalRecord]

    @property
    def is_active(self) -> bool:
        return self.ends_at is not None and self.ends_at > datetime.now(timezone.utc)


class MilkWithdrawalService:
    @staticmethod
    def current(cow_id: int, tenant_id: int) -> Withdrawal:
        latest = Withdrawal(None, None)
        for record in MedicalRepository.list_with_withdrawal(cow_id, tenant_id):
            if record.visit_date is None:
                continue
            ends_at = as_utc(record.visit_date) + timedelta(days=int(record.withdrawal_days_recommended))
            if latest.ends_at is None or ends_at > latest.ends_at:
                latest = Withdrawal(ends_at, record)
        return latest

    @staticmethod
    def check_release(cow: Cow, tenant_id: int, override_reason: Optional[str]) -> None:
        """Refuses to release milk during a withdrawal unless a reason for the override is given."""
        withdrawal = MilkWithdrawalService.current(cow.id, tenant_id)
        if withdrawal.is_active and not (override_reason or '').strip():
            raise ApiError(
                'WITHDRAWAL_ACTIVE',
                f'The withdrawal period for {cow.tag_number} runs until {withdrawal.ends_at.isoformat()}. '
                'Send override_reason to release it early.',
                409,
                withdrawal_ends_at=withdrawal.ends_at.isoformat(),
            )
