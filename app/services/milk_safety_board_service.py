"""The milk safety board: which cows' milk is on hold, until when, and why. Read only."""
from __future__ import annotations

from app.models.livestock import Cow, MilkTestResult
from app.repositories.cow_repo import CowRepository
from app.repositories.medical_repo import MedicalRepository
from app.repositories.milk_test_repo import MilkTestRepository
from app.services.milk_safety_serializers import MilkTestSerializer
from app.services.milk_withdrawal_service import MilkWithdrawalService
from app.utils.datetimes import as_utc, iso
from app.utils.user_display import display_name

HIGH_SEVERITY_DAYS = 14
MEDIUM_SEVERITY_DAYS = 7


class MilkSafetyBoardService:
    @staticmethod
    def board(tenant_id: int, *, page: int, per_page: int, severity: str = '', search: str = '') -> dict:
        items = [MilkSafetyBoardService.item(cow, tenant_id) for cow in CowRepository.list_hardlocked(tenant_id, search)]
        # Severity is derived, so it is filtered before paging rather than after.
        if severity:
            items = [item for item in items if item['severity'] == severity]
        total = len(items)
        start = (page - 1) * per_page
        return {
            'items': items[start:start + per_page],
            'meta': {'page': page, 'per_page': per_page, 'total': total, 'pages': (total + per_page - 1) // per_page if total else 0},
        }

    @staticmethod
    def item(cow: Cow, tenant_id: int) -> dict:
        withdrawal = MilkWithdrawalService.current(cow.id, tenant_id)
        treatment = withdrawal.record or MedicalRepository.latest_for_cow(cow.id, tenant_id)
        latest_test = MilkTestRepository.latest_for_cow(cow.id, tenant_id)
        hold_until = as_utc(cow.hold_until)
        ends = [value for value in (withdrawal.ends_at, hold_until) if value is not None]
        days = int(withdrawal.record.withdrawal_days_recommended) if withdrawal.record else 0
        vet_name = display_name(treatment.vet_id) if treatment else None
        failed_test = latest_test is not None and latest_test.result == MilkTestResult.FAIL

        return {
            'cow_id': cow.id,
            'cow_name': cow.name,
            'cow_tag': cow.tag_number,
            'severity': MilkSafetyBoardService._severity(days),
            'source': 'treatment' if withdrawal.record else 'manual',
            'reason': cow.hold_reason or (treatment.diagnosis if treatment else 'Hold active'),
            'lock_expires': iso(max(ends)) if ends else None,
            'withdrawal_ends_at': iso(withdrawal.ends_at),
            'hold_until': iso(hold_until),
            'withdrawal_active': withdrawal.is_active,
            'can_release': not withdrawal.is_active and not failed_test,
            'section': 'clinical',
            'medication': treatment.medication if treatment else None,
            'treated_at': iso(as_utc(treatment.visit_date)) if treatment else None,
            'vet_id': treatment.vet_id if treatment else None,
            'vet_name': vet_name,
            'updated_at': iso(as_utc(cow.hold_set_at) or (as_utc(treatment.visit_date) if treatment else None)),
            'updated_by': display_name(cow.hold_set_by) or vet_name,
            'notes': cow.hold_notes or (treatment.remarks if treatment else None),
            'latest_test': MilkTestSerializer.serialize(latest_test) if latest_test else None,
        }

    @staticmethod
    def _severity(withdrawal_days: int) -> str:
        if withdrawal_days >= HIGH_SEVERITY_DAYS:
            return 'high'
        if withdrawal_days >= MEDIUM_SEVERITY_DAYS:
            return 'medium'
        return 'low'
